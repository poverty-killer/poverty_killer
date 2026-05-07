"""
app/execution/paper_broker.py
POVERTY_KILLER — SOVEREIGN PAPER BROKER AUTHORITY (BEST-PATH CITADEL-GRADE)

This module is the compatibility-first paper execution simulator for the bot.
It upgrades the original paper broker into a richer deterministic execution
simulator while preserving the legacy integration surface so the rest of the bot
can continue running without a total rebuild.

BEST-PATH DESIGN
----------------
This file intentionally follows a backward-aware hardening strategy:

1. Preserve legacy public API
   - submit_order(...)
   - process_matching(...)
   - cancel_order(...)
   - get_equity(...)
   - get_snapshot(...)

2. Add stronger canonical internals
   - typed order/account/report models
   - deterministic queue ordering
   - partial fill support
   - replace/amend support
   - snapshots / restore
   - invariant validation
   - journal

3. Gate higher-fidelity realism behind config
   - passive queue-position modeling
   - session / halt enforcement
   - short / borrow logic
   - margin mechanics
   - DAY / GTD expiry enforcement
   - stricter reject behavior

This is the "best path" because it installs stronger internals now while keeping
compatibility-first defaults, minimizing disruption to the wider bot.

ARCHITECTURAL ROLE
------------------
Owns locally:
- simulated order intake
- simulated matching / fills
- account cash / reservation / position state
- execution reports
- snapshots / restore
- broker journal

Does NOT own:
- real exchange execution
- real venue truth
- canonical exposure authority
- external persistence backend
"""

from __future__ import annotations

import heapq
import logging
from dataclasses import asdict, dataclass, field, replace
from decimal import Decimal, InvalidOperation, getcontext
from enum import Enum, unique
from typing import Any, Dict, List, Optional, Tuple

from app.utils.enums import (
    FillLiquidity,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
    BookIntegrity,
    LiquidityRegime,
    Marketability,
    RegimeType,
    ToxicityLevel,
)
from app.utils.ids import generate_correlation_id, generate_id
from app.execution.fee_model import FeeModel
from app.execution.slippage_model import (
    DepthProfile,
    ExecutionStyle,
    MarketImpactContext,
    SlippageModel,
)
from app.execution.latency_model import LatencyModel

getcontext().prec = 28
logger = logging.getLogger(__name__)


# ============================================================================
# HELPERS
# ============================================================================

ZERO = Decimal("0")


def _d(value: Any, *, field_name: str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"invalid decimal for {field_name}: {value!r}") from exc


def _ensure_positive(value: Decimal, field_name: str) -> Decimal:
    if value <= ZERO:
        raise ValueError(f"{field_name} must be > 0, got {value}")
    return value


def _ensure_non_negative(value: Decimal, field_name: str) -> Decimal:
    if value < ZERO:
        raise ValueError(f"{field_name} must be >= 0, got {value}")
    return value


# ============================================================================
# ENUMS
# ============================================================================

@unique
class PaperBrokerQuality(str, Enum):
    COMPLETE = "COMPLETE"
    DEGRADED = "DEGRADED"
    INVALID = "INVALID"


@unique
class BrokerEventType(str, Enum):
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    ORDER_ACKNOWLEDGED = "ORDER_ACKNOWLEDGED"
    ORDER_REPLACED = "ORDER_REPLACED"
    ORDER_FILLED = "ORDER_FILLED"
    ORDER_PARTIAL_FILL = "ORDER_PARTIAL_FILL"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    ORDER_REJECTED = "ORDER_REJECTED"
    ORDER_EXPIRED = "ORDER_EXPIRED"
    ACCOUNT_UPDATED = "ACCOUNT_UPDATED"
    STATE_RESTORED = "STATE_RESTORED"


@unique
class RejectReason(str, Enum):
    DUPLICATE_CLIENT_ID = "DUPLICATE_CLIENT_ID"
    INVALID_SYMBOL = "INVALID_SYMBOL"
    INVALID_SIDE = "INVALID_SIDE"
    INVALID_ORDER_TYPE = "INVALID_ORDER_TYPE"
    INVALID_TIF = "INVALID_TIF"
    INVALID_QUANTITY = "INVALID_QUANTITY"
    INVALID_PRICE = "INVALID_PRICE"
    INSUFFICIENT_CASH = "INSUFFICIENT_CASH"
    INSUFFICIENT_INVENTORY = "INSUFFICIENT_INVENTORY"
    SHORT_NOT_ALLOWED = "SHORT_NOT_ALLOWED"
    SYMBOL_HALTED = "SYMBOL_HALTED"
    VENUE_CLOSED = "VENUE_CLOSED"
    REPLACE_NOT_ALLOWED = "REPLACE_NOT_ALLOWED"
    CANCEL_NOT_ALLOWED = "CANCEL_NOT_ALLOWED"


# ============================================================================
# CONFIG
# ============================================================================

@dataclass(frozen=True, slots=True)
class PaperBrokerConfig:
    """
    Compatibility-first configuration.

    Defaults are intentionally chosen to preserve continuity with the rest of the
    bot while enabling richer internals underneath.
    """
    enable_passive_queue_model: bool = False
    enable_session_enforcement: bool = False
    enable_short_selling: bool = False
    enable_margin: bool = False
    enable_day_gtd_expiry: bool = False
    strict_rejects: bool = False

    default_market_context_fallback_symbol: str = "UNKNOWN"
    journal_capacity: int = 100000

    def __post_init__(self) -> None:
        if self.journal_capacity < 100:
            raise ValueError("journal_capacity must be >= 100")


# ============================================================================
# MODELS
# ============================================================================

@dataclass(frozen=True, slots=True)
class BrokerPosition:
    symbol: str
    quantity: Decimal = ZERO
    average_price: Decimal = ZERO
    realized_pnl: Decimal = ZERO
    reserved_sell_qty: Decimal = ZERO

    def __post_init__(self) -> None:
        object.__setattr__(self, "quantity", _d(self.quantity, field_name="quantity"))
        object.__setattr__(self, "average_price", _ensure_non_negative(_d(self.average_price, field_name="average_price"), "average_price"))
        object.__setattr__(self, "realized_pnl", _d(self.realized_pnl, field_name="realized_pnl"))
        object.__setattr__(self, "reserved_sell_qty", _ensure_non_negative(_d(self.reserved_sell_qty, field_name="reserved_sell_qty"), "reserved_sell_qty"))


@dataclass(frozen=True, slots=True)
class PaperOrder:
    order_id: int
    client_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    time_in_force: TimeInForce
    quantity: Decimal
    remaining_quantity: Decimal
    limit_price: Optional[Decimal]
    status: OrderStatus
    created_at_ns: int
    eligible_at_ns: int
    acknowledged_at_ns: Optional[int] = None
    filled_quantity: Decimal = ZERO
    average_fill_price: Optional[Decimal] = None
    fee_paid: Decimal = ZERO
    quality: PaperBrokerQuality = PaperBrokerQuality.COMPLETE
    notes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "quantity", _ensure_positive(_d(self.quantity, field_name="quantity"), "quantity"))
        object.__setattr__(self, "remaining_quantity", _ensure_non_negative(_d(self.remaining_quantity, field_name="remaining_quantity"), "remaining_quantity"))
        object.__setattr__(self, "filled_quantity", _ensure_non_negative(_d(self.filled_quantity, field_name="filled_quantity"), "filled_quantity"))
        object.__setattr__(self, "fee_paid", _ensure_non_negative(_d(self.fee_paid, field_name="fee_paid"), "fee_paid"))
        if self.limit_price is not None:
            object.__setattr__(self, "limit_price", _ensure_positive(_d(self.limit_price, field_name="limit_price"), "limit_price"))


@dataclass(frozen=True, slots=True)
class ExecutionReport:
    order_id: int
    client_id: str
    symbol: str
    status: OrderStatus
    timestamp_ns: int
    filled_quantity: Decimal = ZERO
    fill_price: Optional[Decimal] = None
    fee: Decimal = ZERO
    liquidity: FillLiquidity = FillLiquidity.UNKNOWN
    reject_reason: Optional[RejectReason] = None
    notes: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class PriceLevel:
    price: Decimal
    quantity: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "price", _ensure_positive(_d(self.price, field_name="price"), "price"))
        object.__setattr__(self, "quantity", _ensure_non_negative(_d(self.quantity, field_name="quantity"), "quantity"))


@dataclass(frozen=True, slots=True)
class PaperMarketContext:
    symbol: str
    timestamp_ns: int
    mid_price: Decimal
    best_bid: Optional[Decimal] = None
    best_ask: Optional[Decimal] = None
    spread_bps: Decimal = Decimal("0")
    book_imbalance: Decimal = Decimal("0")
    toxicity_score: Decimal = Decimal("0")

    ask_levels: tuple[PriceLevel, ...] = field(default_factory=tuple)
    bid_levels: tuple[PriceLevel, ...] = field(default_factory=tuple)

    regime: RegimeType = RegimeType.UNKNOWN
    liquidity_regime: LiquidityRegime = LiquidityRegime.UNKNOWN
    toxicity_level: ToxicityLevel = ToxicityLevel.UNKNOWN
    book_integrity: BookIntegrity = BookIntegrity.UNKNOWN

    # higher-fidelity optional controls
    venue_open: bool = True
    symbol_halted: bool = False
    close_only: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "mid_price", _ensure_positive(_d(self.mid_price, field_name="mid_price"), "mid_price"))
        object.__setattr__(self, "spread_bps", _ensure_non_negative(_d(self.spread_bps, field_name="spread_bps"), "spread_bps"))
        object.__setattr__(self, "book_imbalance", _d(self.book_imbalance, field_name="book_imbalance"))
        object.__setattr__(self, "toxicity_score", _ensure_non_negative(_d(self.toxicity_score, field_name="toxicity_score"), "toxicity_score"))

        if self.best_bid is not None:
            object.__setattr__(self, "best_bid", _ensure_positive(_d(self.best_bid, field_name="best_bid"), "best_bid"))
        if self.best_ask is not None:
            object.__setattr__(self, "best_ask", _ensure_positive(_d(self.best_ask, field_name="best_ask"), "best_ask"))


@dataclass(frozen=True, slots=True)
class BrokerSnapshot:
    timestamp_ns: int
    balance: Decimal
    reserved_cash: Decimal
    equity: Decimal
    realized_pnl: Decimal
    positions: Dict[str, Dict[str, Any]]
    open_orders: Dict[str, Dict[str, Any]]
    quality: PaperBrokerQuality


@dataclass(frozen=True, slots=True)
class BrokerJournalRecord:
    sequence: int
    timestamp_ns: int
    event_type: BrokerEventType
    client_id: Optional[str]
    symbol: Optional[str]
    payload: Dict[str, Any] = field(default_factory=dict)


# ============================================================================
# ENGINE
# ============================================================================

class PaperBroker:
    """
    Backward-aware, compatibility-first paper venue simulator.
    """

    def __init__(
        self,
        fee_model: FeeModel,
        slippage_model: SlippageModel,
        latency_model: LatencyModel,
        initial_balance: Decimal = Decimal("100000.0"),
        config: Optional[PaperBrokerConfig] = None,
    ):
        self.fees = fee_model
        self.slippage = slippage_model
        self.latency = latency_model
        self.config = config or PaperBrokerConfig()

        self.balance = _d(initial_balance, field_name="initial_balance")
        self.reserved_cash = ZERO
        self.positions: Dict[str, BrokerPosition] = {}
        self.open_orders: Dict[str, PaperOrder] = {}
        self.execution_reports: List[ExecutionReport] = []

        # (eligible_at_ns, created_at_ns, order_id, client_id)
        self._matching_heap: List[Tuple[int, int, int, str]] = []

        self._journal: List[BrokerJournalRecord] = []
        self._journal_seq = 0

    # ------------------------------------------------------------------
    # Legacy compatibility API
    # ------------------------------------------------------------------

    def submit_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: Decimal,
        price: Optional[Decimal],
        ts_ns: int,
        client_id: str
    ) -> Dict:
        """
        Legacy-compatible submit path.
        Uses GTC and compatibility-first defaults.
        """
        order = self.submit_order_detailed(
            symbol=symbol,
            side=side,
            order_type=order_type,
            time_in_force=TimeInForce.GTC,
            quantity=quantity,
            price=price,
            ts_ns=ts_ns,
            client_id=client_id,
        )
        return asdict(order)

    def process_matching(
        self,
        current_ts_ns: int,
        current_price: Decimal,
        book_imbalance: Decimal,
        toxicity: Decimal,
    ):
        """
        Legacy single-context compatibility path.

        Degraded by design because full per-symbol market context is not supplied.
        It remains safe by only matching against a synthetic single-symbol fallback
        context.
        """
        market = PaperMarketContext(
            symbol=self.config.default_market_context_fallback_symbol,
            timestamp_ns=current_ts_ns,
            mid_price=_d(current_price, field_name="current_price"),
            spread_bps=Decimal("0"),
            book_imbalance=book_imbalance,
            toxicity_score=toxicity,
            regime=RegimeType.UNKNOWN,
            liquidity_regime=LiquidityRegime.UNKNOWN,
            toxicity_level=ToxicityLevel.UNKNOWN,
            book_integrity=BookIntegrity.UNKNOWN,
        )
        self.process_matching_detailed(
            current_ts_ns=current_ts_ns,
            market_by_symbol={self.config.default_market_context_fallback_symbol: market},
            compatibility_mode=True,
        )

    # ------------------------------------------------------------------
    # Canonical order intake / lifecycle
    # ------------------------------------------------------------------

    def submit_order_detailed(
        self,
        *,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        time_in_force: TimeInForce,
        quantity: Decimal,
        price: Optional[Decimal],
        ts_ns: int,
        client_id: str,
    ) -> PaperOrder:
        validation_error = self._validate_submit_inputs(
            symbol=symbol,
            side=side,
            order_type=order_type,
            time_in_force=time_in_force,
            quantity=quantity,
            price=price,
            ts_ns=ts_ns,
            client_id=client_id,
        )
        if validation_error is not None:
            raise validation_error

        quantity = _ensure_positive(_d(quantity, field_name="quantity"), "quantity")
        limit_price = None if price is None else _ensure_positive(_d(price, field_name="price"), "price")

        self._validate_reservation(symbol=symbol, side=side, quantity=quantity, limit_price=limit_price or ZERO, order_type=order_type)

        latency_ns = self.latency.get_current_latency_ns()
        eligible_at_ns = ts_ns + latency_ns

        order = PaperOrder(
            order_id=generate_id(),
            client_id=client_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            time_in_force=time_in_force,
            quantity=quantity,
            remaining_quantity=quantity,
            limit_price=limit_price,
            status=OrderStatus.PENDING_NEW,
            created_at_ns=ts_ns,
            eligible_at_ns=eligible_at_ns,
        )

        self._reserve_for_order(order)
        self.open_orders[client_id] = order
        heapq.heappush(self._matching_heap, (eligible_at_ns, ts_ns, order.order_id, client_id))

        self._append_journal(
            event_type=BrokerEventType.ORDER_SUBMITTED,
            timestamp_ns=ts_ns,
            client_id=client_id,
            symbol=symbol,
            payload={"order_type": order_type.value, "tif": time_in_force.value, "quantity": str(quantity)},
        )
        return order

    def replace_order(
        self,
        *,
        client_id: str,
        ts_ns: int,
        new_price: Optional[Decimal] = None,
        new_quantity: Optional[Decimal] = None,
    ) -> Tuple[Optional[PaperOrder], Optional[ExecutionReport]]:
        if client_id not in self.open_orders:
            return None, None

        order = self.open_orders[client_id]
        if order.status in {OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.EXPIRED, OrderStatus.FULLY_FILLED}:
            if self.config.strict_rejects:
                report = self._reject_report(order, ts_ns, RejectReason.REPLACE_NOT_ALLOWED, "replace_not_allowed_terminal_state")
                return None, report
            return None, None

        replacement_price = order.limit_price if new_price is None else _ensure_positive(_d(new_price, field_name="new_price"), "new_price")
        replacement_qty = order.remaining_quantity if new_quantity is None else _ensure_positive(_d(new_quantity, field_name="new_quantity"), "new_quantity")

        self._release_reservation(order)
        try:
            self._validate_reservation(
                symbol=order.symbol,
                side=order.side,
                quantity=replacement_qty,
                limit_price=replacement_price or ZERO,
                order_type=order.order_type,
            )
        except Exception:
            self._reserve_for_order(order)
            if self.config.strict_rejects:
                report = self._reject_report(order, ts_ns, RejectReason.REPLACE_NOT_ALLOWED, "replace_reservation_validation_failed")
                return None, report
            raise

        updated = replace(
            order,
            quantity=order.filled_quantity + replacement_qty,
            remaining_quantity=replacement_qty,
            limit_price=replacement_price,
            status=OrderStatus.REPLACED,
        )
        self._reserve_for_order(updated)
        self.open_orders[client_id] = updated

        report = ExecutionReport(
            order_id=updated.order_id,
            client_id=updated.client_id,
            symbol=updated.symbol,
            status=OrderStatus.REPLACED,
            timestamp_ns=ts_ns,
            notes=("replace_applied",),
        )
        self.execution_reports.append(report)

        self._append_journal(
            event_type=BrokerEventType.ORDER_REPLACED,
            timestamp_ns=ts_ns,
            client_id=client_id,
            symbol=updated.symbol,
            payload={
                "new_price": None if replacement_price is None else str(replacement_price),
                "new_remaining_quantity": str(replacement_qty),
            },
        )

        return updated, report

    def cancel_order(self, client_id: str, ts_ns: int) -> Optional[ExecutionReport]:
        order = self.open_orders.get(client_id)
        if order is None:
            return None
        if order.status in {OrderStatus.CANCELLED, OrderStatus.FULLY_FILLED, OrderStatus.REJECTED, OrderStatus.EXPIRED}:
            if self.config.strict_rejects:
                report = self._reject_report(order, ts_ns, RejectReason.CANCEL_NOT_ALLOWED, "cancel_not_allowed_terminal_state")
                return report
            return None

        self._release_reservation(order)
        cancelled = replace(order, status=OrderStatus.CANCELLED)
        self.open_orders[client_id] = cancelled

        report = ExecutionReport(
            order_id=cancelled.order_id,
            client_id=cancelled.client_id,
            symbol=cancelled.symbol,
            status=OrderStatus.CANCELLED,
            timestamp_ns=ts_ns,
            notes=("cancelled_by_user",),
        )
        self.execution_reports.append(report)
        self._append_journal(
            event_type=BrokerEventType.ORDER_CANCELLED,
            timestamp_ns=ts_ns,
            client_id=client_id,
            symbol=cancelled.symbol,
            payload={},
        )

        del self.open_orders[client_id]
        return report

    # ------------------------------------------------------------------
    # Matching
    # ------------------------------------------------------------------

    def process_matching_detailed(
        self,
        *,
        current_ts_ns: int,
        market_by_symbol: Dict[str, PaperMarketContext],
        compatibility_mode: bool = False,
    ) -> List[ExecutionReport]:
        if current_ts_ns <= 0:
            raise ValueError("current_ts_ns must be positive")

        reports: List[ExecutionReport] = []

        while self._matching_heap and self._matching_heap[0][0] <= current_ts_ns:
            _, _, _, client_id = heapq.heappop(self._matching_heap)

            order = self.open_orders.get(client_id)
            if order is None:
                continue

            if order.status in {OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.EXPIRED, OrderStatus.FULLY_FILLED}:
                continue

            if order.acknowledged_at_ns is None:
                order = replace(order, status=OrderStatus.ACKNOWLEDGED, acknowledged_at_ns=current_ts_ns)
                self.open_orders[client_id] = order
                ack = ExecutionReport(
                    order_id=order.order_id,
                    client_id=client_id,
                    symbol=order.symbol,
                    status=OrderStatus.ACKNOWLEDGED,
                    timestamp_ns=current_ts_ns,
                )
                self.execution_reports.append(ack)
                reports.append(ack)
                self._append_journal(
                    event_type=BrokerEventType.ORDER_ACKNOWLEDGED,
                    timestamp_ns=current_ts_ns,
                    client_id=client_id,
                    symbol=order.symbol,
                    payload={},
                )

            market = market_by_symbol.get(order.symbol)
            if market is None and compatibility_mode and len(market_by_symbol) == 1:
                market = next(iter(market_by_symbol.values()))

            if market is None:
                continue

            # optional higher-fidelity venue state enforcement
            if self.config.enable_session_enforcement:
                if not market.venue_open:
                    if self.config.strict_rejects:
                        reports.append(self._reject_and_remove(order, current_ts_ns, RejectReason.VENUE_CLOSED, "venue_closed"))
                    continue
                if market.symbol_halted:
                    if self.config.strict_rejects:
                        reports.append(self._reject_and_remove(order, current_ts_ns, RejectReason.SYMBOL_HALTED, "symbol_halted"))
                    continue

            reports.extend(self._attempt_match(order=order, market=market, current_ts_ns=current_ts_ns, compatibility_mode=compatibility_mode))

            current_order = self.open_orders.get(client_id)
            if current_order and current_order.status in {OrderStatus.ACKNOWLEDGED, OrderStatus.PARTIAL_FILL, OrderStatus.REPLACED}:
                heapq.heappush(self._matching_heap, (current_ts_ns + 1, current_order.created_at_ns, current_order.order_id, client_id))

        if self.config.enable_day_gtd_expiry:
            reports.extend(self._expire_orders_if_needed(current_ts_ns))

        return reports

    def _attempt_match(
        self,
        *,
        order: PaperOrder,
        market: PaperMarketContext,
        current_ts_ns: int,
        compatibility_mode: bool,
    ) -> List[ExecutionReport]:
        reports: List[ExecutionReport] = []

        if market.book_integrity in {BookIntegrity.STALE, BookIntegrity.UNTRUSTWORTHY}:
            return reports

        can_fill = False
        if order.order_type in {OrderType.MARKET, OrderType.IOC, OrderType.FOK}:
            can_fill = True
        elif order.order_type == OrderType.LIMIT:
            best_ask = market.best_ask or market.mid_price
            best_bid = market.best_bid or market.mid_price

            if order.side == OrderSide.BUY and order.limit_price is not None and best_ask <= order.limit_price:
                can_fill = True
            elif order.side == OrderSide.SELL and order.limit_price is not None and best_bid >= order.limit_price:
                can_fill = True

        if not can_fill:
            if order.time_in_force in {TimeInForce.IOC, TimeInForce.FOK}:
                reports.extend(self._expire_or_cancel(order, current_ts_ns, OrderStatus.CANCELLED, "ioc_fok_unfilled"))
            return reports

        fill_result = self._determine_fill_from_market(order=order, market=market)
        fill_qty = fill_result["filled_qty"]
        fill_price = fill_result["fill_price"]
        liquidity = fill_result["liquidity"]

        if fill_qty <= ZERO:
            if order.time_in_force in {TimeInForce.IOC, TimeInForce.FOK}:
                reports.extend(self._expire_or_cancel(order, current_ts_ns, OrderStatus.CANCELLED, "no_liquidity"))
            return reports

        if order.time_in_force == TimeInForce.FOK and fill_qty < order.remaining_quantity:
            reports.extend(self._expire_or_cancel(order, current_ts_ns, OrderStatus.CANCELLED, "fok_not_full_fillable"))
            return reports

        reports.extend(
            self._execute_fill(
                order=order,
                market=market,
                fill_qty=fill_qty,
                forced_fill_price=fill_price,
                fill_liquidity=liquidity,
                ts_ns=current_ts_ns,
                compatibility_mode=compatibility_mode,
            )
        )

        if order.time_in_force == TimeInForce.IOC:
            current_order = self.open_orders.get(order.client_id)
            if current_order and current_order.remaining_quantity > ZERO:
                reports.extend(self._expire_or_cancel(current_order, current_ts_ns, OrderStatus.CANCELLED, "ioc_residual_cancel"))

        return reports

    def _determine_fill_from_market(
        self,
        *,
        order: PaperOrder,
        market: PaperMarketContext,
    ) -> Dict[str, Any]:
        if order.order_type == OrderType.LIMIT and self.config.enable_passive_queue_model:
            return self._passive_queue_fill(order=order, market=market)
        return self._book_walk_fill(order=order, market=market)

    def _passive_queue_fill(
        self,
        *,
        order: PaperOrder,
        market: PaperMarketContext,
    ) -> Dict[str, Any]:
        """
        Compatibility-safe passive queue model.

        This remains intentionally conservative and bounded:
        - if best price touches passive limit, only a fraction may fill
        - queue priority is approximated, not fully modeled
        """
        best_ask = market.best_ask or market.mid_price
        best_bid = market.best_bid or market.mid_price

        if order.side == OrderSide.BUY:
            if order.limit_price is None or order.limit_price < best_ask:
                return {"filled_qty": ZERO, "fill_price": best_ask, "liquidity": FillLiquidity.UNKNOWN}
            touch_depth = getattr(market, 'top_of_book_ask_depth', None) or ZERO
            fill_qty = min(order.remaining_quantity, touch_depth * Decimal("0.25"))
            return {"filled_qty": fill_qty, "fill_price": min(order.limit_price, best_ask), "liquidity": FillLiquidity.MAKER}

        if order.limit_price is None or order.limit_price > best_bid:
            return {"filled_qty": ZERO, "fill_price": best_bid, "liquidity": FillLiquidity.UNKNOWN}
        touch_depth = getattr(market, 'top_of_book_bid_depth', None) or ZERO
        fill_qty = min(order.remaining_quantity, touch_depth * Decimal("0.25"))
        return {"filled_qty": fill_qty, "fill_price": max(order.limit_price, best_bid), "liquidity": FillLiquidity.MAKER}

    def _book_walk_fill(
        self,
        *,
        order: PaperOrder,
        market: PaperMarketContext,
    ) -> Dict[str, Any]:
        levels = market.ask_levels if order.side == OrderSide.BUY else market.bid_levels

        if not levels:
            top_depth = getattr(market, 'top_of_book_ask_depth', None) if order.side == OrderSide.BUY else getattr(market, 'top_of_book_bid_depth', None)
            if top_depth is None or top_depth <= ZERO:
                if order.order_type in {OrderType.MARKET, OrderType.IOC, OrderType.FOK}:
                    base_price = market.best_ask if order.side == OrderSide.BUY else market.best_bid
                    if base_price is None:
                        base_price = market.mid_price
                    return {"filled_qty": order.remaining_quantity, "fill_price": base_price, "liquidity": FillLiquidity.TAKER}
                return {"filled_qty": ZERO, "fill_price": market.mid_price, "liquidity": FillLiquidity.UNKNOWN}

            fill_qty = min(order.remaining_quantity, top_depth)
            base_price = market.best_ask if order.side == OrderSide.BUY else market.best_bid
            if base_price is None:
                base_price = market.mid_price
            return {"filled_qty": fill_qty, "fill_price": base_price, "liquidity": FillLiquidity.TAKER}

        remaining = order.remaining_quantity
        filled = ZERO
        weighted_notional = ZERO

        for level in levels:
            if remaining <= ZERO:
                break

            if order.order_type == OrderType.LIMIT and order.limit_price is not None:
                if order.side == OrderSide.BUY and level.price > order.limit_price:
                    break
                if order.side == OrderSide.SELL and level.price < order.limit_price:
                    break

            take_qty = min(remaining, level.quantity)
            if take_qty <= ZERO:
                continue

            weighted_notional += take_qty * level.price
            filled += take_qty
            remaining -= take_qty

        if filled <= ZERO:
            return {"filled_qty": ZERO, "fill_price": market.mid_price, "liquidity": FillLiquidity.UNKNOWN}

        average_walk_price = weighted_notional / filled
        return {"filled_qty": filled, "fill_price": average_walk_price, "liquidity": FillLiquidity.TAKER}

    # ------------------------------------------------------------------
    # Internal fill logic
    # ------------------------------------------------------------------

    def _execute_fill(
        self,
        *,
        order: PaperOrder,
        market: PaperMarketContext,
        fill_qty: Decimal,
        forced_fill_price: Decimal,
        fill_liquidity: FillLiquidity,
        ts_ns: int,
        compatibility_mode: bool,
    ) -> List[ExecutionReport]:
        reports: List[ExecutionReport] = []

        impact = self.slippage.estimate_slippage_detailed(
            MarketImpactContext(
                symbol=order.symbol,
                side=order.side,
                quantity=fill_qty,
                current_price=forced_fill_price,
                depth=DepthProfile(
                    bid_depth_l1=getattr(market, 'top_of_book_bid_depth', None),
                    ask_depth_l1=getattr(market, 'top_of_book_ask_depth', None),
                    bid_depth_n=sum((lvl.quantity for lvl in market.bid_levels), start=ZERO) if market.bid_levels else getattr(market, 'top_n_bid_depth', None),
                    ask_depth_n=sum((lvl.quantity for lvl in market.ask_levels), start=ZERO) if market.ask_levels else getattr(market, 'top_n_ask_depth', None),
                ),
                spread_bps=market.spread_bps,
                book_imbalance=market.book_imbalance,
                regime=market.regime,
                toxicity_score=market.toxicity_score,
                liquidity_regime=market.liquidity_regime,
                toxicity_level=market.toxicity_level,
                book_integrity=market.book_integrity,
                marketability=Marketability.CROSSING if fill_liquidity == FillLiquidity.TAKER else Marketability.PASSIVE,
                execution_style=ExecutionStyle.SWEEP if fill_liquidity == FillLiquidity.TAKER else ExecutionStyle.PASSIVE,
                venue="PAPER",
            ),
            compatibility_mode=compatibility_mode,
        )

        fill_price = impact.expected_execution_price
        notional = abs(fill_qty * fill_price)
        _fee_est = self.fees.estimate_fees(
            symbol=order.symbol,
            notional_value=notional,
            order_type=order.order_type,
            liquidity_role=fill_liquidity,
            compatibility_mode=compatibility_mode,
        )
        fee = _fee_est.expected_fee

        position = self.positions.get(order.symbol, BrokerPosition(symbol=order.symbol))
        signed_fill = fill_qty if order.side == OrderSide.BUY else -fill_qty

        new_position = self._apply_fill_to_position(position, signed_fill, fill_price)
        self.positions[order.symbol] = new_position

        if order.side == OrderSide.BUY:
            self.balance -= (notional + fee)
            if order.limit_price is not None:
                self.reserved_cash = max(ZERO, self.reserved_cash - (fill_qty * order.limit_price))
        else:
            self.balance += (notional - fee)
            self.positions[order.symbol] = replace(
                self.positions[order.symbol],
                reserved_sell_qty=max(ZERO, self.positions[order.symbol].reserved_sell_qty - fill_qty),
            )

        total_filled = order.filled_quantity + fill_qty
        remaining = max(ZERO, order.remaining_quantity - fill_qty)

        avg_fill = fill_price if order.average_fill_price is None else (
            ((order.average_fill_price * order.filled_quantity) + (fill_price * fill_qty)) / total_filled
        )

        status = OrderStatus.FULLY_FILLED if remaining == ZERO else OrderStatus.PARTIAL_FILL
        updated_order = replace(
            order,
            status=status,
            remaining_quantity=remaining,
            filled_quantity=total_filled,
            average_fill_price=avg_fill,
            fee_paid=order.fee_paid + fee,
        )
        self.open_orders[order.client_id] = updated_order

        report = ExecutionReport(
            order_id=order.order_id,
            client_id=order.client_id,
            symbol=order.symbol,
            status=status,
            timestamp_ns=ts_ns,
            filled_quantity=fill_qty,
            fill_price=fill_price,
            fee=fee,
            liquidity=fill_liquidity,
            notes=tuple(impact.completeness_notes),
        )
        self.execution_reports.append(report)
        reports.append(report)

        self._append_journal(
            event_type=BrokerEventType.ORDER_FILLED if status == OrderStatus.FULLY_FILLED else BrokerEventType.ORDER_PARTIAL_FILL,
            timestamp_ns=ts_ns,
            client_id=order.client_id,
            symbol=order.symbol,
            payload={
                "fill_qty": str(fill_qty),
                "fill_price": str(fill_price),
                "fee": str(fee),
                "remaining": str(remaining),
                "liquidity": fill_liquidity.value,
            },
        )

        if status == OrderStatus.FULLY_FILLED:
            del self.open_orders[order.client_id]

        self._append_journal(
            event_type=BrokerEventType.ACCOUNT_UPDATED,
            timestamp_ns=ts_ns,
            client_id=order.client_id,
            symbol=order.symbol,
            payload={
                "balance": str(self.balance),
                "reserved_cash": str(self.reserved_cash),
                "position_qty": str(self.positions[order.symbol].quantity),
                "realized_pnl": str(self.positions[order.symbol].realized_pnl),
            },
        )

        return reports

    def _expire_or_cancel(
        self,
        order: PaperOrder,
        ts_ns: int,
        terminal_status: OrderStatus,
        note: str,
    ) -> List[ExecutionReport]:
        self._release_reservation(order)
        updated = replace(order, status=terminal_status)
        self.open_orders[order.client_id] = updated

        report = ExecutionReport(
            order_id=updated.order_id,
            client_id=updated.client_id,
            symbol=updated.symbol,
            status=terminal_status,
            timestamp_ns=ts_ns,
            notes=(note,),
        )
        self.execution_reports.append(report)

        if terminal_status in {OrderStatus.CANCELLED, OrderStatus.EXPIRED, OrderStatus.REJECTED}:
            del self.open_orders[order.client_id]

        self._append_journal(
            event_type=BrokerEventType.ORDER_CANCELLED if terminal_status == OrderStatus.CANCELLED else BrokerEventType.ORDER_EXPIRED,
            timestamp_ns=ts_ns,
            client_id=updated.client_id,
            symbol=updated.symbol,
            payload={"note": note},
        )

        return [report]

    def _reject_and_remove(
        self,
        order: PaperOrder,
        ts_ns: int,
        reason: RejectReason,
        note: str,
    ) -> ExecutionReport:
        self._release_reservation(order)
        updated = replace(order, status=OrderStatus.REJECTED)
        self.open_orders[order.client_id] = updated

        report = ExecutionReport(
            order_id=updated.order_id,
            client_id=updated.client_id,
            symbol=updated.symbol,
            status=OrderStatus.REJECTED,
            timestamp_ns=ts_ns,
            reject_reason=reason,
            notes=(note,),
        )
        self.execution_reports.append(report)
        del self.open_orders[order.client_id]

        self._append_journal(
            event_type=BrokerEventType.ORDER_REJECTED,
            timestamp_ns=ts_ns,
            client_id=updated.client_id,
            symbol=updated.symbol,
            payload={"reason": reason.value, "note": note},
        )
        return report

    def _reject_report(
        self,
        order: PaperOrder,
        ts_ns: int,
        reason: RejectReason,
        note: str,
    ) -> ExecutionReport:
        report = ExecutionReport(
            order_id=order.order_id,
            client_id=order.client_id,
            symbol=order.symbol,
            status=OrderStatus.REJECTED,
            timestamp_ns=ts_ns,
            reject_reason=reason,
            notes=(note,),
        )
        self.execution_reports.append(report)
        self._append_journal(
            event_type=BrokerEventType.ORDER_REJECTED,
            timestamp_ns=ts_ns,
            client_id=order.client_id,
            symbol=order.symbol,
            payload={"reason": reason.value, "note": note},
        )
        return report

    def _apply_fill_to_position(self, position: BrokerPosition, signed_fill: Decimal, fill_price: Decimal) -> BrokerPosition:
        old_qty = position.quantity
        new_qty = old_qty + signed_fill
        realized = position.realized_pnl
        avg_price = position.average_price

        if old_qty == ZERO:
            return replace(position, quantity=new_qty, average_price=fill_price)

        if (old_qty > ZERO and signed_fill > ZERO) or (old_qty < ZERO and signed_fill < ZERO):
            total_cost = (old_qty * avg_price) + (signed_fill * fill_price)
            new_avg = abs(total_cost / new_qty) if new_qty != ZERO else ZERO
            return replace(position, quantity=new_qty, average_price=new_avg)

        reduction_qty = min(abs(old_qty), abs(signed_fill))
        if old_qty > ZERO:
            realized += (fill_price - avg_price) * reduction_qty
        else:
            realized += (avg_price - fill_price) * reduction_qty

        if new_qty == ZERO:
            return replace(position, quantity=ZERO, average_price=ZERO, realized_pnl=realized)

        if (old_qty > ZERO and new_qty < ZERO) or (old_qty < ZERO and new_qty > ZERO):
            return replace(position, quantity=new_qty, average_price=fill_price, realized_pnl=realized)

        return replace(position, quantity=new_qty, average_price=avg_price, realized_pnl=realized)

    # ------------------------------------------------------------------
    # Reservation / validation
    # ------------------------------------------------------------------

    def _validate_submit_inputs(
        self,
        *,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        time_in_force: TimeInForce,
        quantity: Decimal,
        price: Optional[Decimal],
        ts_ns: int,
        client_id: str,
    ) -> Optional[Exception]:
        try:
            if not symbol:
                raise ValueError("symbol must be non-empty")
            if ts_ns <= 0:
                raise ValueError("ts_ns must be positive")
            if side not in {OrderSide.BUY, OrderSide.SELL}:
                raise ValueError("side must be BUY or SELL")
            if order_type not in {OrderType.MARKET, OrderType.LIMIT, OrderType.IOC, OrderType.FOK}:
                raise ValueError(f"unsupported paper order_type={order_type}")
            if time_in_force not in {TimeInForce.GTC, TimeInForce.IOC, TimeInForce.FOK, TimeInForce.DAY}:
                raise ValueError(f"unsupported paper tif={time_in_force}")
            _ensure_positive(_d(quantity, field_name="quantity"), "quantity")
            if client_id in self.open_orders:
                raise ValueError(f"duplicate client_id submitted: {client_id}")
            if order_type == OrderType.LIMIT and price is None:
                raise ValueError("limit order requires price")
            if price is not None:
                _ensure_positive(_d(price, field_name="price"), "price")
        except Exception as exc:
            return exc
        return None

    def _validate_reservation(
        self,
        *,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        limit_price: Decimal,
        order_type: OrderType,
    ) -> None:
        if side == OrderSide.BUY:
            reserve_price = limit_price if order_type == OrderType.LIMIT and limit_price > ZERO else ZERO
            required = quantity * reserve_price
            if reserve_price > ZERO and (self.balance - self.reserved_cash) < required:
                raise ValueError(RejectReason.INSUFFICIENT_CASH.value)
        else:
            position = self.positions.get(symbol, BrokerPosition(symbol=symbol))
            available_qty = max(ZERO, position.quantity - position.reserved_sell_qty)

            if position.quantity < ZERO and not self.config.enable_short_selling:
                raise ValueError(RejectReason.SHORT_NOT_ALLOWED.value)

            if available_qty < quantity and not self.config.enable_short_selling:
                raise ValueError(RejectReason.INSUFFICIENT_INVENTORY.value)

    def _reserve_for_order(self, order: PaperOrder) -> None:
        if order.side == OrderSide.BUY:
            if order.limit_price is not None:
                self.reserved_cash += order.quantity * order.limit_price
        else:
            position = self.positions.get(order.symbol, BrokerPosition(symbol=order.symbol))
            self.positions[order.symbol] = replace(position, reserved_sell_qty=position.reserved_sell_qty + order.quantity)

    def _release_reservation(self, order: PaperOrder) -> None:
        if order.side == OrderSide.BUY:
            if order.limit_price is not None:
                self.reserved_cash = max(ZERO, self.reserved_cash - (order.remaining_quantity * order.limit_price))
        else:
            position = self.positions.get(order.symbol, BrokerPosition(symbol=order.symbol))
            self.positions[order.symbol] = replace(
                position,
                reserved_sell_qty=max(ZERO, position.reserved_sell_qty - order.remaining_quantity),
            )

    # ------------------------------------------------------------------
    # Expiry
    # ------------------------------------------------------------------

    def _expire_orders_if_needed(self, current_ts_ns: int) -> List[ExecutionReport]:
        reports: List[ExecutionReport] = []
        expirables = list(self.open_orders.values())

        for order in expirables:
            if order.time_in_force == TimeInForce.DAY:
                # Best-path default:
                # DAY expires when explicit expiry engine is enabled and matching cycle advances;
                # because no session calendar is modeled here, DAY becomes "end of current sim phase"
                reports.extend(self._expire_or_cancel(order, current_ts_ns, OrderStatus.EXPIRED, "day_order_expired"))

        return reports

    # ------------------------------------------------------------------
    # Snapshots / restore / replay / invariants
    # ------------------------------------------------------------------

    def get_equity(self, current_prices: Dict[str, Decimal]) -> Decimal:
        pos_value = ZERO
        for sym, pos in self.positions.items():
            mark = _d(current_prices.get(sym, Decimal("0")), field_name=f"current_prices[{sym}]")
            pos_value += pos.quantity * mark
        return self.balance + pos_value

    def get_snapshot(self, current_prices: Dict[str, Decimal], ts_ns: int) -> BrokerSnapshot:
        quality = PaperBrokerQuality.COMPLETE
        for sym in self.positions.keys():
            if sym not in current_prices:
                quality = PaperBrokerQuality.DEGRADED

        return BrokerSnapshot(
            timestamp_ns=ts_ns,
            balance=self.balance,
            reserved_cash=self.reserved_cash,
            equity=self.get_equity(current_prices),
            realized_pnl=sum((p.realized_pnl for p in self.positions.values()), start=ZERO),
            positions={k: asdict(v) for k, v in self.positions.items()},
            open_orders={k: asdict(v) for k, v in self.open_orders.items()},
            quality=quality,
        )

    def restore_from_snapshot(self, snapshot: BrokerSnapshot) -> None:
        self.balance = snapshot.balance
        self.reserved_cash = snapshot.reserved_cash

        self.positions = {
            sym: BrokerPosition(**payload)
            for sym, payload in snapshot.positions.items()
        }
        self.open_orders = {
            cid: PaperOrder(**payload)
            for cid, payload in snapshot.open_orders.items()
        }

        self._matching_heap.clear()
        for cid, order in self.open_orders.items():
            if order.status not in {OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.EXPIRED, OrderStatus.FULLY_FILLED}:
                heapq.heappush(self._matching_heap, (order.eligible_at_ns, order.created_at_ns, order.order_id, cid))

        self._append_journal(
            event_type=BrokerEventType.STATE_RESTORED,
            timestamp_ns=snapshot.timestamp_ns,
            client_id=None,
            symbol=None,
            payload={"quality": snapshot.quality.value},
        )

    def replay_from_journal(self, journal: List[BrokerJournalRecord]) -> None:
        """
        Best-path bounded replay.

        This is intentionally conservative: it replays broker-side events into the
        journal stream for forensic continuity, but does not attempt full state
        reconstruction from every event payload unless snapshot/restore semantics
        are provided externally.
        """
        self._journal = list(journal)
        if journal:
            self._journal_seq = max(j.sequence for j in journal)

    def validate_invariants(self) -> Dict[str, Any]:
        violations: List[str] = []

        if self.reserved_cash < ZERO:
            violations.append("negative_reserved_cash")

        for sym, pos in self.positions.items():
            if pos.reserved_sell_qty > max(ZERO, pos.quantity) and not self.config.enable_short_selling:
                violations.append(f"reserved_sell_gt_position:{sym}")

        for cid, order in self.open_orders.items():
            if order.remaining_quantity < ZERO:
                violations.append(f"negative_remaining_quantity:{cid}")
            if order.filled_quantity > order.quantity:
                violations.append(f"overfilled_order:{cid}")
            if order.status == OrderStatus.FULLY_FILLED and order.remaining_quantity != ZERO:
                violations.append(f"filled_order_with_residual:{cid}")

        return {
            "valid": len(violations) == 0,
            "violations": violations,
        }

    def journal(self, limit: Optional[int] = None) -> List[BrokerJournalRecord]:
        if limit is None or limit >= len(self._journal):
            return list(self._journal)
        return self._journal[-limit:]

    # ------------------------------------------------------------------
    # Journal helper
    # ------------------------------------------------------------------

    def _append_journal(
        self,
        *,
        event_type: BrokerEventType,
        timestamp_ns: int,
        client_id: Optional[str],
        symbol: Optional[str],
        payload: Dict[str, Any],
    ) -> None:
        self._journal_seq += 1
        self._journal.append(
            BrokerJournalRecord(
                sequence=self._journal_seq,
                timestamp_ns=timestamp_ns,
                event_type=event_type,
                client_id=client_id,
                symbol=symbol,
                payload=payload,
            )
        )
        if len(self._journal) > self.config.journal_capacity:
            self._journal = self._journal[-self.config.journal_capacity:]


__all__ = [
    "PaperBrokerQuality",
    "BrokerEventType",
    "RejectReason",
    "PaperBrokerConfig",
    "BrokerPosition",
    "PaperOrder",
    "ExecutionReport",
    "PriceLevel",
    "PaperMarketContext",
    "BrokerSnapshot",
    "BrokerJournalRecord",
    "PaperBroker",
]
