"""
Order Router - Exchange Adapter with Ghost Detection & PCV
The "Nervous System" of the Poverty Killer.

Paper-trading proof hardening goals for this bundle:
- preserve sovereign PaperBroker live paper path
- eliminate fake paper fills and placeholder price truth
- keep cancellation/status/position surfaces coherent for sustained paper runs
- improve runtime observability without broad redesign

This file remains the exchange adapter authority. It does not redesign paper
execution; it truthfully delegates live paper execution to the sovereign
PaperBroker while keeping the existing ExecutionEngine contract intact.

BUNDLE 3B-P — EXCHANGE ACCOUNT / ORDER DATA ADAPTER FOUNDATIONS
Added methods:
- fetch_balances(): Get account balances from Kraken
- fetch_open_orders(): Get open orders from Kraken
- fetch_fills(): Get fill/trade history from Kraken
- fetch_positions(): Derive positions from orders + fills
- _call_kraken_private(): Reusable private API caller
- get_exchange_truth_snapshot(): Returns real exchange data using fetch_* methods

All methods are standalone fetchers. No automatic polling. No wiring to
TruthFrame. That belongs in Bundle 3B.

BUNDLE F1 — TELEMETRY HOOKS
- Accepts optional telemetry_store for fill/rejection recording
- Records fills via FillRecorder when paper or live fills occur
- Records rejections when order submission fails
- No semantic changes to order routing logic
"""

import base64
import hashlib
import hmac
import logging
import math
import threading
import time
import urllib.parse
from dataclasses import dataclass
from decimal import Decimal as _Decimal
from typing import Any, Dict, List, Optional, Tuple

import requests

from app.execution.fee_model import FeeModel as _FeeModel
from app.execution.latency_model import LatencyModel as _LatencyModel
from app.execution.paper_broker import PaperBroker as _SovereignPaperBroker, PaperBrokerConfig as _PaperBrokerConfig
from app.execution.slippage_model import SlippageModel as _SlippageModel
from app.models import OrderFill, OrderRequest
from app.models.enums import (
    InternalOrderStatus,
    OrderSide as _CanonicalOrderSide,
    OrderType as _CanonicalOrderType,
    SleeveType,
)
from app.utils.time_utils import now_ns
from app.telemetry.event_store import TelemetryEventStore
from app.telemetry.fill_recorder import FillRecorder
import app.utils.enums as _pb_enums

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class OrderStatus:
    """Order status from exchange or paper broker cache."""
    order_id: str
    status: str  # pending, open, filled, cancelled, expired, rejected
    filled_quantity: _Decimal = _Decimal("0")
    filled_price: _Decimal = _Decimal("0")
    remaining_quantity: _Decimal = _Decimal("0")
    timestamp_ns: int = 0


class OrderRouter:
    """
    Order Router - Exchange Adapter with Ghost Detection.

    Live paper path:
        ExecutionEngine -> OrderRouter.submit_order() -> SovereignPaperBroker

    This hardening pass preserves the existing public surface while replacing
    fake paper fills with status-coherent paper-broker-driven execution.

    BUNDLE 3B-P: Added exchange account/order data fetching methods.
    
    BUNDLE F1: Added telemetry hooks for fills and rejections.
    """

    def __init__(
        self,
        primary_exchange: str = "kraken",
        secondary_exchange: str = "coinbase",
        primary_api_key: str = "",
        primary_api_secret: str = "",
        secondary_api_key: str = "",
        secondary_api_secret: str = "",
        latency_threshold_ms: float = 200.0,
        ghost_ratio_threshold: float = 3.0,
        pcv_max_attempts: int = 5,
        pcv_retry_delay_sec: float = 0.5,
        rest_fallback_enabled: bool = True,
        paper_mode: bool = True,
        telemetry_store: Optional[TelemetryEventStore] = None
    ):
        self.primary_exchange = primary_exchange
        self.secondary_exchange = secondary_exchange
        self.primary_api_key = primary_api_key
        self.primary_api_secret = primary_api_secret
        self.secondary_api_key = secondary_api_key
        self.secondary_api_secret = secondary_api_secret
        self.latency_threshold_ms = latency_threshold_ms
        self.ghost_ratio_threshold = ghost_ratio_threshold
        self.pcv_max_attempts = pcv_max_attempts
        self.pcv_retry_delay_sec = pcv_retry_delay_sec
        self.rest_fallback_enabled = rest_fallback_enabled
        self.paper_mode = paper_mode

        self._paper_broker: Optional[_SovereignPaperBroker] = None
        if paper_mode:
            self._paper_broker = _SovereignPaperBroker(
                fee_model=_FeeModel(),
                slippage_model=_SlippageModel(),
                latency_model=_LatencyModel(),
                config=_PaperBrokerConfig(enable_short_selling=True),
            )
            logger.info("SovereignPaperBroker (app/execution/paper_broker.py) wired on live paper path")

        self._websocket_connected = False
        self._last_websocket_ping_ns = 0
        self._last_websocket_pong_ns = 0

        self._pending_orders: Dict[str, OrderRequest] = {}
        self._order_status_cache: Dict[str, OrderStatus] = {}
        self._paper_reports_index: int = 0
        self._paper_last_mid_by_symbol: Dict[str, _Decimal] = {}

        # STAGE 2-F3: Symbol-indexed live market mid cache, populated by MainLoop
        # on every accepted order-book ingress. Separate from
        # _paper_last_mid_by_symbol (which is populated only after paper matching)
        # to break the chicken-and-egg defect where execution validation could
        # never observe a real market mid before the first paper order filled.
        # Pure cache; no order/matching/position/cash/risk side effects.
        self._latest_market_mid_by_symbol: Dict[str, _Decimal] = {}
        self._latest_market_mid_ts_ns_by_symbol: Dict[str, int] = {}

        self._fill_recorder: Optional[FillRecorder] = None
        if telemetry_store:
            self._fill_recorder = FillRecorder(telemetry_store)
            logger.info("FillRecorder wired for telemetry")

        self._endpoints = {
            "kraken": {
                "rest": "https://api.kraken.com/0",
                "public": "https://api.kraken.com/0/public",
                "private": "https://api.kraken.com/0/private",
                "time": "/public/Time",
                "order": "/private/AddOrder",
                "cancel": "/private/CancelOrder",
                "status": "/private/QueryOrders",
                "open_orders": "/private/OpenOrders",
                "balance": "/private/Balance",
                "trades_history": "/private/TradesHistory",
                "closed_orders": "/private/ClosedOrders",
            },
            "alpaca": {
                "rest": "https://paper-api.alpaca.markets/v2",
                "order": "/orders",
                "cancel": "/orders/{order_id}",
                "status": "/orders/{order_id}",
                "open_orders": "/orders",
                "positions": "/positions"
            }
        }

        self._session = requests.Session()
        self._lock = threading.Lock()

    def _record_fill_telemetry(
        self,
        order: OrderRequest,
        fill: OrderFill,
        *,
        venue_fill_id: str,
    ) -> None:
        """
        Bridge active OrderFill execution output into FillEvent telemetry.

        Compatibility mapping:
        - execution_event_id uses OrderRequest.id as the execution source ID.
        - order_intent_id intentionally mirrors OrderRequest.id while
          OrderIntent remains dormant and not runtime-wired.
        - decision_uuid preserves causal decision-chain linkage.
        """
        if not self._fill_recorder:
            return
        if not order.decision_uuid:
            logger.warning("Skipping fill telemetry for order %s: missing decision_uuid", order.id)
            return

        from decimal import Decimal
        from app.models.contracts import FillEvent

        fill_event = FillEvent(
            fill_event_id=f"fill_{order.id}_{fill.exchange_ts_ns}",
            execution_event_id=order.id,
            order_intent_id=order.id,
            decision_uuid=order.decision_uuid,
            symbol=order.symbol,
            side=order.side,
            quantity=Decimal(str(fill.quantity)),
            price=Decimal(str(fill.price)),
            fee=Decimal(str(fill.fee)),
            fee_currency=fill.fee_currency,
            venue_fill_id=venue_fill_id,
            exchange_ts_ns=fill.exchange_ts_ns,
            receive_ts_ns=fill.receive_ts_ns,
        )
        self._fill_recorder.record_fill(fill_event, metadata=order.metadata)

    def _record_rejection_telemetry(self, order: OrderRequest, reason: str) -> None:
        """Record order rejection telemetry without changing routing authority."""
        if not self._fill_recorder:
            return
        if not order.decision_uuid:
            logger.warning("Skipping rejection telemetry for order %s: missing decision_uuid", order.id)
            return

        self._fill_recorder.record_rejection(
            client_order_id=order.id,
            decision_uuid=order.decision_uuid,
            reason=reason,
            reject_ts_ns=now_ns(),
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            order_type=order.order_type,
            limit_price=order.limit_price,
            metadata=order.metadata,
        )

    def _record_order_submission_telemetry(self, order: OrderRequest) -> None:
        """Record order-submission telemetry as a first-class replay event."""
        if not self._fill_recorder:
            return
        if not order.decision_uuid:
            logger.warning("Skipping order submission telemetry for order %s: missing decision_uuid", order.id)
            return

        self._fill_recorder.record_order_submitted(
            client_order_id=order.id,
            decision_uuid=order.decision_uuid,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            order_type=order.order_type,
            limit_price=order.limit_price,
            exchange_ts_ns=order.exchange_ts_ns,
            receive_ts_ns=order.receive_ts_ns,
            venue_order_id=None,
            metadata=order.metadata,
        )

    # ============================================
    # WEBSOCKET HEALTH MONITORING
    # ============================================

    def update_websocket_health(self, ping_ns: int, pong_ns: int):
        with self._lock:
            self._last_websocket_ping_ns = ping_ns
            self._last_websocket_pong_ns = pong_ns
            self._websocket_connected = (pong_ns - ping_ns) < (self.latency_threshold_ms * 1_000_000)

    def is_websocket_connected(self) -> bool:
        with self._lock:
            if not self._websocket_connected:
                return False
            if self._last_websocket_pong_ns == 0:
                return False
            age_ns = now_ns() - self._last_websocket_pong_ns
            return age_ns < 30_000_000_000  # 30 seconds stale timeout

    def get_websocket_rtt_ms(self) -> float:
        with self._lock:
            if self._last_websocket_ping_ns == 0 or self._last_websocket_pong_ns == 0:
                return float("inf")
            return (self._last_websocket_pong_ns - self._last_websocket_ping_ns) / 1_000_000

    def measure_latency(self) -> float:
        return self.get_websocket_rtt_ms()

    # ============================================
    # KRAKEN API AUTHENTICATION
    # ============================================

    def _kraken_sign(self, urlpath: str, data: dict) -> dict:
        postdata = urllib.parse.urlencode(data)
        encoded = (str(data.get("nonce", "")) + postdata).encode()
        message = urlpath.encode() + hashlib.sha256(encoded).digest()

        if not self.primary_api_secret:
            return {}

        mac = hmac.new(base64.b64decode(self.primary_api_secret), message, hashlib.sha512)
        sigdigest = base64.b64encode(mac.digest()).decode()

        return {
            "API-Key": self.primary_api_key,
            "API-Sign": sigdigest,
        }

    # ============================================
    # BUNDLE 3B-P: REUSABLE PRIVATE API CALLER
    # ============================================

    def _call_kraken_private(self, endpoint_path: str, data: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """
        Reusable private API caller for Kraken.

        Args:
            endpoint_path: Path from self._endpoints (e.g., "/private/Balance")
            data: POST data dict (nonce will be added automatically)

        Returns:
            Parsed JSON response result dict, or None on error
        """
        if self.paper_mode:
            logger.debug("Paper mode: skipping Kraken private API call")
            return None

        if not self.primary_api_key or not self.primary_api_secret:
            logger.warning("Kraken API credentials missing, cannot call %s", endpoint_path)
            return None

        url = f"{self._endpoints['kraken']['rest']}{endpoint_path}"
        request_data = data.copy() if data else {}
        request_data["nonce"] = str(int(time.time() * 1000))

        headers = self._kraken_sign(endpoint_path, request_data)

        try:
            response = self._session.post(url, data=request_data, headers=headers, timeout=10.0)
            if response.status_code != 200:
                logger.error("Kraken private API error: HTTP %d for %s", response.status_code, endpoint_path)
                return None

            result = response.json()
            if result.get("error"):
                logger.error("Kraken private API error: %s for %s", result["error"], endpoint_path)
                return None

            return result.get("result")

        except Exception as e:
            logger.error("Kraken private API exception for %s: %s", endpoint_path, e)
            return None

    # ============================================
    # BUNDLE 3B-P: BALANCE FETCHING
    # ============================================

    def fetch_balances(self) -> Dict[str, _Decimal]:
        """
        Fetch account balances from Kraken.

        Returns:
            Dict mapping currency (e.g., "USD", "BTC") to Decimal balance.
            Returns empty dict if paper mode or API error.
        """
        if self.paper_mode:
            # Paper mode: return simulated balances from paper broker
            if self._paper_broker:
                return {
                    "USD": _Decimal(str(self._paper_broker.balance)),
                }
            return {}

        result = self._call_kraken_private(self._endpoints["kraken"]["balance"])
        if not result:
            return {}

        balances = {}
        for currency, balance_str in result.items():
            try:
                balance = _Decimal(str(balance_str))
                if balance > 0:
                    balances[currency] = balance
            except Exception:
                logger.debug("Failed to parse balance for %s: %s", currency, balance_str)

        return balances

    # ============================================
    # BUNDLE 3B-P: OPEN ORDERS FETCHING
    # ============================================

    def fetch_open_orders(self) -> List[Dict[str, Any]]:
        """
        Fetch open orders from Kraken.

        Returns:
            List of open orders with full details.
            Returns empty list if paper mode or API error.
        """
        if self.paper_mode:
            # Paper mode: return open orders from paper broker
            if self._paper_broker:
                orders = []
                for client_id, order in self._paper_broker.open_orders.items():
                    orders.append({
                        "order_id": str(order.order_id),
                        "client_id": client_id,
                        "symbol": order.symbol,
                        "side": order.side.value,
                        "order_type": order.order_type.value,
                        "quantity": float(order.quantity),
                        "remaining_quantity": float(order.remaining_quantity),
                        "filled_quantity": float(order.filled_quantity),
                        "limit_price": float(order.limit_price) if order.limit_price else None,
                        "status": order.status.value,
                        "created_at_ns": order.created_at_ns,
                    })
                return orders
            return []

        result = self._call_kraken_private(self._endpoints["kraken"]["open_orders"])
        if not result:
            return []

        orders = []
        open_data = result.get("open", {})
        for order_id, order_info in open_data.items():
            descr = order_info.get("descr", {})
            orders.append({
                "order_id": order_id,
                "symbol": descr.get("pair", ""),
                "side": descr.get("type", ""),
                "order_type": descr.get("ordertype", ""),
                "quantity": float(order_info.get("vol", 0)),
                "remaining_quantity": float(order_info.get("vol_exec", 0)),
                "limit_price": float(descr.get("price", 0)) if descr.get("price") else None,
                "status": order_info.get("status", "unknown"),
                "created_at_ns": int(order_info.get("opentm", 0)) * 1_000_000_000 if order_info.get("opentm") else 0,
            })

        return orders

    # ============================================
    # BUNDLE 3B-P: FILL HISTORY FETCHING
    # ============================================

    def fetch_fills(self, start_time_ns: Optional[int] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Fetch fill/trade history from Kraken.

        Args:
            start_time_ns: Optional start time in nanoseconds (filters trades after this time)
            limit: Maximum number of trades to return

        Returns:
            List of fills with price, quantity, fee, timestamp.
            Returns empty list if paper mode or API error.
        """
        if self.paper_mode:
            # Paper mode: return fills from paper broker execution reports
            if self._paper_broker:
                fills = []
                for report in self._paper_broker.execution_reports:
                    if report.filled_quantity and report.filled_quantity > 0:
                        fills.append({
                            "order_id": str(report.order_id),
                            "client_id": report.client_id,
                            "symbol": report.symbol,
                            "quantity": float(report.filled_quantity),
                            "price": float(report.fill_price) if report.fill_price else 0.0,
                            "fee": float(report.fee),
                            "timestamp_ns": report.timestamp_ns,
                            "liquidity": report.liquidity.value if report.liquidity else "unknown",
                        })
                # Sort by timestamp descending, apply limit
                fills.sort(key=lambda x: x["timestamp_ns"], reverse=True)
                if start_time_ns:
                    fills = [f for f in fills if f["timestamp_ns"] > start_time_ns]
                return fills[:limit]
            return []

        data = {"limit": limit}
        if start_time_ns:
            # Kraken expects Unix timestamp in seconds
            data["start"] = int(start_time_ns / 1_000_000_000)

        result = self._call_kraken_private(self._endpoints["kraken"]["trades_history"], data)
        if not result:
            return []

        fills = []
        trades = result.get("trades", {})
        for trade_id, trade_info in trades.items():
            fills.append({
                "trade_id": trade_id,
                "order_id": trade_info.get("ordertxid", ""),
                "symbol": trade_info.get("pair", ""),
                "side": trade_info.get("type", ""),
                "quantity": float(trade_info.get("vol", 0)),
                "price": float(trade_info.get("price", 0)),
                "fee": float(trade_info.get("fee", 0)),
                "cost": float(trade_info.get("cost", 0)),
                "timestamp_ns": int(trade_info.get("time", 0)) * 1_000_000_000,
            })

        return fills

    # ============================================
    # BUNDLE 3B-P: POSITION DERIVATION
    # ============================================

    def fetch_positions(self) -> List[Dict[str, Any]]:
        """
        Derive open positions from open orders and fills.

        Kraken does not have a direct positions endpoint. Positions are derived by:
        1. Aggregating net quantity from fills
        2. Adjusting for open orders that are not yet filled

        Returns:
            List of positions with symbol, quantity, average_entry_price.
            Returns empty list if paper mode or API error.
        """
        if self.paper_mode:
            # Paper mode: return positions from paper broker
            if self._paper_broker:
                positions = []
                for symbol, pos in self._paper_broker.positions.items():
                    if pos.quantity != 0:
                        positions.append({
                            "symbol": symbol,
                            "quantity": float(pos.quantity),
                            "average_entry_price": float(pos.average_price) if pos.average_price else 0.0,
                            "realized_pnl": float(pos.realized_pnl),
                        })
                return positions
            return []

        # Fetch fills to aggregate net position
        fills = self.fetch_fills(limit=500)
        position_map: Dict[str, Dict[str, Any]] = {}

        for fill in fills:
            symbol = fill["symbol"]
            quantity = fill["quantity"]
            side = fill["side"]
            price = fill["price"]

            if symbol not in position_map:
                position_map[symbol] = {
                    "symbol": symbol,
                    "quantity": 0.0,
                    "total_cost": 0.0,
                    "average_entry_price": 0.0,
                }

            # BUY adds positive quantity, SELL subtracts
            if side.lower() == "buy":
                position_map[symbol]["quantity"] += quantity
                position_map[symbol]["total_cost"] += quantity * price
            else:
                position_map[symbol]["quantity"] -= quantity

        # Calculate average entry prices
        positions = []
        for symbol, pos in position_map.items():
            if abs(pos["quantity"]) > 0.000001:  # Non-zero tolerance
                avg_price = pos["total_cost"] / abs(pos["quantity"]) if pos["quantity"] != 0 else 0.0
                positions.append({
                    "symbol": symbol,
                    "quantity": pos["quantity"],
                    "average_entry_price": avg_price,
                })

        return positions

    # ============================================
    # BUNDLE 3B-P: EXCHANGE TRUTH SNAPSHOT (COMPLETED FOUNDATION)
    # ============================================

    def get_exchange_truth_snapshot(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        """
        Return a real snapshot of exchange-side truth for later ExchangeTruth hydration.

        This is the completed foundation for Bundle 3B. It returns real data
        from the fetch_* methods. Bundle 3B will wire this to main_loop.

        Args:
            symbol: Optional symbol filter (currently unused, returns all data)

        Returns:
            Dict with:
            - balances: Dict[str, Decimal] from fetch_balances()
            - positions: List[Dict] from fetch_positions()
            - open_orders: List[Dict] from fetch_open_orders()
            - fills_since_last_call: List[Dict] from fetch_fills()
        """
        return {
            "balances": self.fetch_balances(),
            "positions": self.fetch_positions(),
            "open_orders": self.fetch_open_orders(),
            "fills_since_last_call": self.fetch_fills(limit=100),
        }

    # ============================================
    # PAPER PATH HELPERS
    # ============================================

    def _paper_side(self, order: OrderRequest):
        """
        Compatibility shim mapping only.

        Canonical enum authority is app.models.enums.OrderSide.
        app.utils.enums is imported here only because PaperBroker's preserved
        compatibility surface still consumes that shim namespace.
        """
        if order.side == _CanonicalOrderSide.BUY:
            return _pb_enums.OrderSide.BUY
        if order.side == _CanonicalOrderSide.SELL:
            return _pb_enums.OrderSide.SELL
        raise ValueError(f"Unsupported canonical order side for paper bridge: {order.side!r}")

    def _paper_order_type(self, order: OrderRequest):
        """
        Compatibility shim mapping only.

        Canonical enum authority is app.models.enums.OrderType.
        This bridge intentionally narrows POST_ONLY into LIMIT for the preserved
        PaperBroker legacy submit surface.
        """
        if order.order_type in (_CanonicalOrderType.LIMIT, _CanonicalOrderType.POST_ONLY):
            return _pb_enums.OrderType.LIMIT
        if order.order_type == _CanonicalOrderType.MARKET:
            return _pb_enums.OrderType.MARKET
        raise ValueError(f"Unsupported canonical order type for paper bridge: {order.order_type!r}")

    def _map_paper_report_status_to_cache(self, report_status: Any) -> str:
        """
        Narrow PaperBroker lifecycle truth into the router's preserved coarse cache.

        This cache is compatibility-oriented only; it is not a full canonical
        lifecycle authority.
        """
        if report_status == _pb_enums.OrderStatus.FULLY_FILLED:
            return "filled"
        if report_status == _pb_enums.OrderStatus.CANCELLED:
            return "cancelled"
        if report_status == _pb_enums.OrderStatus.REJECTED:
            return "rejected"
        if report_status == _pb_enums.OrderStatus.EXPIRED:
            return "expired"
        if report_status in {
            _pb_enums.OrderStatus.PARTIAL_FILL,
            _pb_enums.OrderStatus.ACKNOWLEDGED,
            _pb_enums.OrderStatus.PENDING_NEW,
            _pb_enums.OrderStatus.REPLACED,
            _pb_enums.OrderStatus.CREATED,
            _pb_enums.OrderStatus.VALIDATED,
            _pb_enums.OrderStatus.ROUTING,
            _pb_enums.OrderStatus.ROUTED,
            _pb_enums.OrderStatus.SENT,
            _pb_enums.OrderStatus.PENDING_ACK,
        }:
            return "pending"

        status_name = getattr(report_status, "name", str(report_status)).upper()
        if status_name in {"FULLY_FILLED", "FILLED"}:
            return "filled"
        if "PARTIAL" in status_name:
            return "pending"
        if "CANCELLED" in status_name:
            return "cancelled"
        if "REJECTED" in status_name:
            return "rejected"
        if "EXPIRED" in status_name:
            return "expired"
        return "pending"

    def _get_latest_paper_fill_report(self, client_id: str):
        if self._paper_broker is None:
            return None

        for report in reversed(self._paper_broker.execution_reports):
            if report.client_id != client_id:
                continue
            if report.filled_quantity and report.filled_quantity > _Decimal("0"):
                return report
        return None

    def _sync_paper_reports(self) -> None:
        """Synchronize paper broker execution reports into router status cache."""
        if self._paper_broker is None:
            return

        reports = self._paper_broker.execution_reports
        if self._paper_reports_index >= len(reports):
            return

        new_reports = reports[self._paper_reports_index:]
        for report in new_reports:
            client_id = report.client_id
            mapped_status = self._map_paper_report_status_to_cache(report.status)

            filled_qty = report.filled_quantity or _Decimal("0")
            filled_price = report.fill_price if report.fill_price is not None else _Decimal("0")
            remaining_qty = _Decimal("0")
            if client_id in self._paper_broker.open_orders:
                remaining_qty = self._paper_broker.open_orders[client_id].remaining_quantity

            self._order_status_cache[client_id] = OrderStatus(
                order_id=client_id,
                status=mapped_status,
                filled_quantity=filled_qty,
                filled_price=filled_price,
                remaining_quantity=remaining_qty,
                timestamp_ns=int(report.timestamp_ns),
            )

            if mapped_status == "filled":
                self._pending_orders.pop(client_id, None)
            elif mapped_status in {"cancelled", "expired", "rejected"}:
                self._pending_orders.pop(client_id, None)

        self._paper_reports_index = len(reports)

    def _paper_mark_price(self, symbol: str) -> _Decimal:
        if symbol in self._latest_market_mid_by_symbol:
            return self._latest_market_mid_by_symbol[symbol]
        if symbol in self._paper_last_mid_by_symbol:
            return self._paper_last_mid_by_symbol[symbol]
        fallback = self._get_simulated_price(symbol)
        return _Decimal(str(fallback))

    def _drive_paper_matching(self, order: OrderRequest, ts_ns: int) -> None:
        if self._paper_broker is None:
            return

        mark_price = self._paper_mark_price(order.symbol)
        self._paper_last_mid_by_symbol[order.symbol] = mark_price
        paper_order = self._paper_broker.open_orders.get(order.id)
        match_ts_ns = (paper_order.eligible_at_ns + 1) if paper_order is not None else ts_ns
        self._paper_broker.process_matching(
            current_ts_ns=match_ts_ns,
            current_price=mark_price,
            book_imbalance=_Decimal("0"),
            toxicity=_Decimal("0"),
        )
        self._sync_paper_reports()

    # ============================================
    # ORDER SUBMISSION WITH POST-ONLY FLAG
    # ============================================

    def submit_order(self, order: OrderRequest) -> Optional[OrderFill]:
        """Submit order to exchange or sovereign paper broker."""
        self._record_order_submission_telemetry(order)
        if self.paper_mode:
            return self._submit_order_paper(order)

        try:
            if not self._websocket_connected:
                if self.rest_fallback_enabled:
                    logger.warning("WebSocket unhealthy, using REST fallback for %s", order.id)
                    return self._submit_order_rest(order)
                logger.error("WebSocket unhealthy and REST fallback disabled for %s", order.id)
                return None

            if self.primary_exchange == "kraken":
                return self._submit_order_kraken(order)
            if self.primary_exchange == "alpaca":
                return self._submit_order_alpaca(order)

            logger.error("Unsupported exchange: %s", self.primary_exchange)
            return None
        except Exception as e:
            logger.error("Order submission failed: %s", e)
            if self.rest_fallback_enabled:
                return self._submit_order_rest(order)
            return None

    def _submit_order_paper(self, order: OrderRequest) -> Optional[OrderFill]:
        """
        Delegate paper execution to sovereign PaperBroker.

        Truthful behavior:
        - no fake immediate hardcoded fill
        - live status and open-order state come from paper broker reports
        - immediate match attempt is preserved for continuity, but result is broker-driven
        
        BUNDLE F1: Records fills and rejections via FillRecorder when telemetry enabled.
        """
        if self._paper_broker is None:
            logger.error("SovereignPaperBroker not initialized — paper_mode must be True at construction")
            return None

        pb_side = self._paper_side(order)
        pb_order_type = self._paper_order_type(order)

        ts_ns: int = getattr(order, "exchange_ts_ns", None) or now_ns()

        submit_price: Optional[_Decimal] = None
        if pb_order_type == _pb_enums.OrderType.LIMIT and order.limit_price is not None:
            submit_price = _Decimal(str(order.limit_price))

        self._paper_broker.submit_order(
            symbol=order.symbol,
            side=pb_side,
            order_type=pb_order_type,
            quantity=_Decimal(str(order.quantity)),
            price=submit_price,
            ts_ns=ts_ns,
            client_id=order.id,
        )

        self._pending_orders[order.id] = order
        self._order_status_cache[order.id] = OrderStatus(
            order_id=order.id,
            status="pending",
            timestamp_ns=ts_ns,
        )

        self._drive_paper_matching(order, ts_ns)

        status = self._order_status_cache.get(order.id)
        if status is None or status.status != "filled":
            logger.info("PAPER MODE: order queued/pending %s %s %s", order.side, order.quantity, order.symbol)
            return None

        fill_report = self._get_latest_paper_fill_report(order.id)
        fill_fee = _Decimal("0")
        fee_currency = "USD"
        exchange_fill_ts_ns = ts_ns
        fill_receive_ts_ns = ts_ns

        if fill_report is not None:
            fill_fee = _Decimal(str(fill_report.fee))
            if int(fill_report.timestamp_ns) > 0:
                exchange_fill_ts_ns = int(fill_report.timestamp_ns)
                fill_receive_ts_ns = int(fill_report.timestamp_ns)

        latency_ms = float(self._paper_broker.latency.get_current_latency_ns()) / 1_000_000
        logger.info(
            "PAPER MODE (sovereign): %s %s %s @ %.8f status=filled",
            order.side,
            status.filled_quantity,
            order.symbol,
            status.filled_price,
        )

        fill = OrderFill(
            order_id=order.id,
            symbol=order.symbol,
            side=order.side,
            quantity=status.filled_quantity,
            price=status.filled_price,
            fee=fill_fee,
            fee_currency=fee_currency,
            status=InternalOrderStatus.FILLED,
            exchange_ts_ns=exchange_fill_ts_ns,
            receive_ts_ns=fill_receive_ts_ns,
            latency_ms=latency_ms,
        )

        # BUNDLE F1: Record fill to telemetry
        self._record_fill_telemetry(order, fill, venue_fill_id=order.id)

        return fill

    def _submit_order_kraken(self, order: OrderRequest) -> Optional[OrderFill]:
        endpoint = self._endpoints["kraken"]["order"]
        url = f"{self._endpoints['kraken']['rest']}{endpoint}"

        order_type = "limit" if order.order_type == "limit" else "market"
        data = {
            "pair": order.symbol.replace("/", ""),
            "type": order.side,
            "ordertype": order_type,
            "volume": str(order.quantity),
            "oflags": "post"
        }

        if order.limit_price:
            data["price"] = str(order.limit_price)

        headers = self._kraken_sign(endpoint, data)

        try:
            response = self._session.post(url, data=data, headers=headers, timeout=5.0)
            if response.status_code == 200:
                result = response.json()
                if result.get("error"):
                    logger.error("Kraken order error: %s", result["error"])
                    # BUNDLE F1: Record rejection
                    self._record_rejection_telemetry(order, f"Kraken error: {result['error']}")
                    return None

                txid = result.get("result", {}).get("txid", [])
                if txid:
                    order_id = txid[0]
                    logger.info("Kraken order submitted: %s", order_id)
                    if order.order_type == "market":
                        return self._get_order_fill(order_id, order)
                    self._pending_orders[order.id] = order
                    return None

            logger.error("Kraken order failed: %s", response.status_code)
            # BUNDLE F1: Record rejection
            self._record_rejection_telemetry(order, f"Kraken HTTP {response.status_code}")
            return None
        except Exception as e:
            logger.error("Kraken order exception: %s", e)
            # BUNDLE F1: Record rejection
            self._record_rejection_telemetry(order, f"Kraken exception: {str(e)}")
            return None

    def _submit_order_alpaca(self, order: OrderRequest) -> Optional[OrderFill]:
        endpoint = self._endpoints["alpaca"]["order"]
        url = f"{self._endpoints['alpaca']['rest']}{endpoint}"

        order_type = "limit" if order.order_type == "limit" else "market"
        data = {
            "symbol": order.symbol,
            "qty": str(order.quantity),
            "side": order.side,
            "type": order_type,
            "time_in_force": "day"
        }

        if order.order_type == "limit":
            data["limit_price"] = str(order.limit_price)
            data["order_class"] = "simple"
            data["post_only"] = True

        try:
            response = self._session.post(url, json=data, timeout=5.0)
            if response.status_code == 200:
                result = response.json()
                order_id = result.get("id")
                logger.info("Alpaca order submitted: %s", order_id)
                if order.order_type == "market":
                    return self._get_order_fill(order_id, order)
                self._pending_orders[order.id] = order
                return None

            logger.error("Alpaca order failed: %s - %s", response.status_code, response.text)
            # BUNDLE F1: Record rejection
            self._record_rejection_telemetry(order, f"Alpaca HTTP {response.status_code}: {response.text[:200]}")
            return None
        except Exception as e:
            logger.error("Alpaca order exception: %s", e)
            # BUNDLE F1: Record rejection
            self._record_rejection_telemetry(order, f"Alpaca exception: {str(e)}")
            return None

    def _submit_order_rest(self, order: OrderRequest) -> Optional[OrderFill]:
        logger.info("REST fallback for order %s", order.id)
        if self.primary_exchange == "kraken":
            return self._submit_order_kraken(order)
        if self.primary_exchange == "alpaca":
            return self._submit_order_alpaca(order)
        return self._submit_order_paper(order)

    def _get_order_fill(self, order_id: str, order: OrderRequest) -> Optional[OrderFill]:
        try:
            if self.primary_exchange == "kraken":
                return self._get_kraken_order_fill(order_id, order)
            if self.primary_exchange == "alpaca":
                return self._get_alpaca_order_fill(order_id, order)
            return None
        except Exception as e:
            logger.error("Failed to get order fill: %s", e)
            return None

    def _get_kraken_order_fill(self, order_id: str, order: OrderRequest) -> Optional[OrderFill]:
        endpoint = self._endpoints["kraken"]["status"]
        url = f"{self._endpoints['kraken']['rest']}{endpoint}"

        data = {"txid": order_id}
        headers = self._kraken_sign(endpoint, data)

        try:
            response = self._session.post(url, data=data, headers=headers, timeout=5.0)
            if response.status_code == 200:
                result = response.json()
                if result.get("error"):
                    return None

                order_data = result.get("result", {}).get(order_id, {})
                if order_data.get("status") == "closed":
                    ts_ns = now_ns()
                    fill = OrderFill(
                        order_id=order.id,
                        symbol=order.symbol,
                        side=order.side,
                        quantity=_Decimal(str(order_data.get("vol_exec", 0))),
                        price=_Decimal(str(order_data.get("price", 0))),
                        fee=_Decimal(str(order_data.get("fee", 0))),
                        fee_currency=order_data.get("fee_currency", "USD"),
                        status=InternalOrderStatus.FILLED,
                        exchange_ts_ns=ts_ns,
                        receive_ts_ns=ts_ns,
                        latency_ms=self.measure_latency(),
                    )
                    # BUNDLE F1: Record fill to telemetry
                    self._record_fill_telemetry(order, fill, venue_fill_id=order_id)
                    return fill
            return None
        except Exception as e:
            logger.error("Failed to get Kraken order fill: %s", e)
            return None

    def _get_alpaca_order_fill(self, order_id: str, order: OrderRequest) -> Optional[OrderFill]:
        endpoint = self._endpoints["alpaca"]["status"].replace("{order_id}", order_id)
        url = f"{self._endpoints['alpaca']['rest']}{endpoint}"

        try:
            response = self._session.get(url, timeout=5.0)
            if response.status_code == 200:
                result = response.json()
                if result.get("status") == "filled":
                    ts_ns = now_ns()
                    fill = OrderFill(
                        order_id=order.id,
                        symbol=order.symbol,
                        side=order.side,
                        quantity=_Decimal(str(result.get("filled_qty", 0))),
                        price=_Decimal(str(result.get("filled_avg_price", 0))),
                        fee=_Decimal(str(result.get("fees", 0))),
                        fee_currency="USD",
                        status=InternalOrderStatus.FILLED,
                        exchange_ts_ns=ts_ns,
                        receive_ts_ns=ts_ns,
                        latency_ms=self.measure_latency(),
                    )
                    # BUNDLE F1: Record fill to telemetry
                    self._record_fill_telemetry(order, fill, venue_fill_id=order_id)
                    return fill
            return None
        except Exception as e:
            logger.error("Failed to get Alpaca order fill: %s", e)
            return None

    def _get_simulated_price(self, symbol: str) -> float:
        if symbol in self._paper_last_mid_by_symbol:
            return float(self._paper_last_mid_by_symbol[symbol])
        if "BTC" in symbol or "XBT" in symbol:
            return 50000.0
        if "ETH" in symbol:
            return 3000.0
        return 100.0

    # ============================================
    # POST-CANCELLATION VERIFICATION (PCV)
    # ============================================

    def cancel_order(self, order_id: str) -> bool:
        if self.paper_mode:
            return self._cancel_order_paper(order_id)

        try:
            if not self._websocket_connected and self.rest_fallback_enabled:
                return self._cancel_order_rest(order_id)

            if self.primary_exchange == "kraken":
                return self._cancel_order_kraken(order_id)
            if self.primary_exchange == "alpaca":
                return self._cancel_order_alpaca(order_id)
            return False
        except Exception as e:
            logger.error("Order cancellation failed: %s", e)
            if self.rest_fallback_enabled:
                return self._cancel_order_rest(order_id)
            return False

    def _cancel_order_paper(self, order_id: str) -> bool:
        """Cancel paper order through sovereign paper broker when available."""
        logger.info("PAPER MODE: Cancelling order %s", order_id)
        self._pending_orders.pop(order_id, None)

        if self._paper_broker and order_id in self._paper_broker.open_orders:
            try:
                self._paper_broker.cancel_order(order_id, now_ns())
                self._sync_paper_reports()
            except Exception as exc:
                logger.debug("Paper broker cancel delegation failed for %s: %s", order_id, exc)

        self._order_status_cache[order_id] = OrderStatus(
            order_id=order_id,
            status="cancelled",
            timestamp_ns=now_ns(),
        )
        return True

    def _cancel_order_kraken(self, order_id: str) -> bool:
        endpoint = self._endpoints["kraken"]["cancel"]
        url = f"{self._endpoints['kraken']['rest']}{endpoint}"

        data = {"txid": order_id}
        headers = self._kraken_sign(endpoint, data)

        try:
            response = self._session.post(url, data=data, headers=headers, timeout=5.0)
            if response.status_code == 200:
                result = response.json()
                if result.get("error"):
                    logger.error("Kraken cancel error: %s", result["error"])
                    return False
                return True
            return False
        except Exception as e:
            logger.error("Kraken cancel exception: %s", e)
            return False

    def _cancel_order_alpaca(self, order_id: str) -> bool:
        endpoint = self._endpoints["alpaca"]["cancel"].replace("{order_id}", order_id)
        url = f"{self._endpoints['alpaca']['rest']}{endpoint}"

        try:
            response = self._session.delete(url, timeout=5.0)
            if response.status_code in [200, 204]:
                return True
            logger.error("Alpaca cancel failed: %s", response.status_code)
            return False
        except Exception as e:
            logger.error("Alpaca cancel exception: %s", e)
            return False

    def _cancel_order_rest(self, order_id: str) -> bool:
        logger.info("REST cancellation for order %s", order_id)
        if self.primary_exchange == "kraken":
            return self._cancel_order_kraken(order_id)
        if self.primary_exchange == "alpaca":
            return self._cancel_order_alpaca(order_id)
        return self._cancel_order_paper(order_id)

    def get_order_status(self, order_id: str) -> str:
        """Get order status with coherent paper/live fallback."""
        if self.paper_mode:
            self._sync_paper_reports()

        if order_id in self._order_status_cache:
            cached = self._order_status_cache[order_id]
            age_ns = max(0, now_ns() - cached.timestamp_ns)
            if cached.timestamp_ns > 0 and age_ns < 1_000_000_000:
                return cached.status

        status = self._query_order_status(order_id)
        self._order_status_cache[order_id] = OrderStatus(
            order_id=order_id,
            status=status,
            timestamp_ns=now_ns(),
        )
        return status

    def _query_order_status(self, order_id: str) -> str:
        if self.paper_mode:
            self._sync_paper_reports()
            if order_id in self._order_status_cache:
                return self._order_status_cache[order_id].status
            if order_id in self._pending_orders:
                return "pending"
            return "cancelled"

        if self.primary_exchange == "kraken":
            return self._query_kraken_order_status(order_id)
        if self.primary_exchange == "alpaca":
            return self._query_alpaca_order_status(order_id)
        return "unknown"

    def _query_kraken_order_status(self, order_id: str) -> str:
        endpoint = self._endpoints["kraken"]["status"]
        url = f"{self._endpoints['kraken']['rest']}{endpoint}"

        data = {"txid": order_id}
        headers = self._kraken_sign(endpoint, data)

        try:
            response = self._session.post(url, data=data, headers=headers, timeout=5.0)
            if response.status_code == 200:
                result = response.json()
                if result.get("error"):
                    return "unknown"

                order_data = result.get("result", {}).get(order_id, {})
                status = order_data.get("status", "unknown")
                if status == "closed":
                    return "filled"
                if status == "cancelled":
                    return "cancelled"
                if status == "expired":
                    return "expired"
                if status == "rejected":
                    return "rejected"
                return "pending"
            return "unknown"
        except Exception as e:
            logger.error("Failed to query Kraken order status: %s", e)
            return "unknown"

    def _query_alpaca_order_status(self, order_id: str) -> str:
        endpoint = self._endpoints["alpaca"]["status"].replace("{order_id}", order_id)
        url = f"{self._endpoints['alpaca']['rest']}{endpoint}"

        try:
            response = self._session.get(url, timeout=5.0)
            if response.status_code == 200:
                result = response.json()
                return result.get("status", "unknown")
            return "unknown"
        except Exception as e:
            logger.error("Failed to query Alpaca order status: %s", e)
            return "unknown"

    def verify_cancellation(self, order_id: str) -> bool:
        for _attempt in range(self.pcv_max_attempts):
            status = self.get_order_status(order_id)
            if status in ["cancelled", "expired", "rejected"]:
                logger.info("PCV confirmed: Order %s is %s", order_id, status)
                self._pending_orders.pop(order_id, None)
                return True
            if status == "filled":
                logger.warning("PCV: Order %s filled before cancellation", order_id)
                return False
            time.sleep(self.pcv_retry_delay_sec)

        logger.error("PCV failed: Order %s still pending after %d attempts", order_id, self.pcv_max_attempts)
        return False

    # ============================================
    # EMERGENCY REST FALLBACK
    # ============================================

    def close_all_positions(self) -> bool:
        """Emergency close all positions via REST API or sovereign paper broker state."""
        logger.critical("EMERGENCY: Closing all positions via REST/paper path")
        positions = self._get_open_positions()

        if not positions:
            logger.info("No open positions to close")
            return True

        success = True
        for position in positions:
            try:
                ts_ns = now_ns()
                close_order = OrderRequest(
                    id=f"close_{position['symbol']}_{ts_ns}",
                    symbol=position["symbol"],
                    side="sell" if position["side"] == "buy" else "buy",
                    quantity=position["quantity"],
                    order_type="market",
                    strategy=SleeveType.HEDGING_FLOW,
                    confidence=1.0,
                    exchange_ts_ns=ts_ns,
                    receive_ts_ns=ts_ns,
                    metadata={"emergency_close": True},
                )
                fill = self._submit_order_rest(close_order)
                if fill:
                    logger.info("Closed position %s: %s @ %s", position["symbol"], position["quantity"], fill.price)
                else:
                    logger.error("Failed to close position %s", position["symbol"])
                    success = False
            except Exception as e:
                logger.error("Error closing position %s: %s", position["symbol"], e)
                success = False

        return success

    def _get_open_positions(self) -> List[Dict[str, Any]]:
        if self.paper_mode:
            if self._paper_broker is None:
                return []
            positions = []
            for symbol, pos in self._paper_broker.positions.items():
                if pos.quantity != _Decimal("0"):
                    side = "buy" if pos.quantity > _Decimal("0") else "sell"
                    positions.append({
                        "symbol": symbol,
                        "side": side,
                        "quantity": abs(pos.quantity),
                        "order_id": f"paper_{symbol}",
                    })
            return positions

        if self.primary_exchange == "kraken":
            return self._get_kraken_open_positions()
        if self.primary_exchange == "alpaca":
            return self._get_alpaca_open_positions()
        return []

    def _get_kraken_open_positions(self) -> List[Dict[str, Any]]:
        endpoint = self._endpoints["kraken"]["open_orders"]
        url = f"{self._endpoints['kraken']['rest']}{endpoint}"

        data = {}
        headers = self._kraken_sign(endpoint, data)

        try:
            response = self._session.post(url, data=data, headers=headers, timeout=5.0)
            if response.status_code == 200:
                result = response.json()
                if result.get("error"):
                    return []

                orders = result.get("result", {}).get("open", {})
                positions = []
                for order_id, order_data in orders.items():
                    positions.append({
                        "symbol": order_data.get("descr", {}).get("pair", ""),
                        "side": order_data.get("descr", {}).get("type", ""),
                        "quantity": float(order_data.get("vol", 0)),
                        "order_id": order_id
                    })
                return positions
            return []
        except Exception as e:
            logger.error("Failed to get Kraken open positions: %s", e)
            return []

    def _get_alpaca_open_positions(self) -> List[Dict[str, Any]]:
        endpoint = self._endpoints["alpaca"]["open_orders"]
        url = f"{self._endpoints['alpaca']['rest']}{endpoint}"

        try:
            response = self._session.get(url, timeout=5.0)
            if response.status_code == 200:
                orders = response.json()
                positions = []
                for order in orders:
                    if order.get("status") == "open":
                        positions.append({
                            "symbol": order.get("symbol", ""),
                            "side": order.get("side", ""),
                            "quantity": float(order.get("qty", 0)),
                            "order_id": order.get("id", "")
                        })
                return positions
            return []
        except Exception as e:
            logger.error("Failed to get Alpaca open positions: %s", e)
            return []

    # ============================================
    # UTILITY METHODS
    # ============================================

    def update_market_mid(self, symbol: str, mid_price: float, exchange_ts_ns: int) -> None:
        """
        STAGE 2-F3: Symbol-indexed live market mid cache updater.

        MainLoop calls this on every accepted order-book ingress so that
        execution validation can observe a real per-symbol market mid even
        before any paper order has filled. Pure cache update: no order
        submission, no matching, no position changes, no cash changes, no
        risk-state changes. Validates inputs and silently no-ops on invalid
        values to keep the call site inside MainLoop hot-path safe.
        """
        if not isinstance(symbol, str) or not symbol:
            return
        if not isinstance(mid_price, (int, float)):
            return
        try:
            f = float(mid_price)
        except (ValueError, TypeError):
            return
        if not math.isfinite(f) or f <= 0.0:
            return
        if not isinstance(exchange_ts_ns, int) or exchange_ts_ns <= 0:
            return
        self._latest_market_mid_by_symbol[symbol] = _Decimal(str(f))
        self._latest_market_mid_ts_ns_by_symbol[symbol] = exchange_ts_ns

    def get_mid_price(self, symbol: str) -> _Decimal:
        # STAGE 2-F3: Prefer the live market mid cache (populated by MainLoop on
        # every accepted order-book ingress). This is the authoritative source
        # for execution validation. Falls back to the post-paper-match cache
        # (_paper_last_mid_by_symbol) and finally to the legacy hardcoded
        # simulated-price helper only when no real mid has been observed yet.
        # See post-patch report for the BLOCKER TRACKED on legacy hardcoded
        # constants in _get_simulated_price for cold-start authority paths.
        if symbol in self._latest_market_mid_by_symbol:
            return self._latest_market_mid_by_symbol[symbol]
        return _Decimal(str(self._get_simulated_price(symbol)))

    def get_actual_positions(self) -> List[Dict[str, Any]]:
        """Compatibility helper used by execution emergency path."""
        return self._get_open_positions()

    def get_ghost_status(self) -> Dict[str, Any]:
        return {
            "websocket_connected": self._websocket_connected,
            "primary_exchange": self.primary_exchange,
            "secondary_exchange": self.secondary_exchange,
            "ghost_ratio_threshold": self.ghost_ratio_threshold,
            "latency_threshold_ms": self.latency_threshold_ms,
            "current_latency_ms": self.measure_latency(),
            "websocket_rtt_ms": self.get_websocket_rtt_ms(),
            "paper_mode": self.paper_mode,
            "pending_orders_count": len(self._pending_orders),
            "paper_status_cache_size": len(self._order_status_cache) if self.paper_mode else 0,
        }
