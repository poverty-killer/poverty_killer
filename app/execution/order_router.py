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
import json
import logging
import math
import threading
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal as _Decimal
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

import requests

from app.execution.fee_model import FeeModel as _FeeModel
from app.execution.latency_model import LatencyModel as _LatencyModel
from app.execution.broker_gateway import (
    BrokerGatewayError,
    BrokerGatewayResponse,
    BrokerOrderSubmitRequest as _GatewayOrderSubmitRequest,
    NormalizedBrokerStatus as _GatewayStatus,
)
from app.execution.broker_read_policy import (
    BROKER_READ_NOT_AUTHORIZED,
    BrokerReadPermissionProfile,
    READ_ACCOUNT_ACTIVITIES,
    READ_FEE_HYDRATION,
    READ_FILL_ACTIVITY_HYDRATION,
    broker_read_allowed,
    broker_read_profile_from_env,
    coerce_broker_read_profile,
)
from app.execution.oms_lifecycle import (
    OmsOrderState,
    OmsReasonCode,
    canonical_state_from_broker_status,
    is_terminal_oms_state,
)
from app.execution.paper_broker import PaperBroker as _SovereignPaperBroker, PaperBrokerConfig as _PaperBrokerConfig
from app.execution.slippage_model import SlippageModel as _SlippageModel
from app.models import EventEnvelope, OrderFill, OrderRequest
from app.models.enums import (
    EventType,
    InternalOrderStatus,
    OrderSide as _CanonicalOrderSide,
    OrderType as _CanonicalOrderType,
    SleeveType,
)
from app.state.state_store import StateStore
from app.utils.time_utils import now_ns
from app.telemetry.event_store import TelemetryEventStore
from app.telemetry.fill_recorder import FillRecorder, build_passive_reservation_candidate_delta
import app.utils.enums as _pb_enums

logger = logging.getLogger(__name__)

INTERNAL_PAPER_EXECUTION_BROKER = "internal_paper"


_STATUS_EVIDENCE_OPEN_OR_PENDING = {
    "open",
    "pending",
    "accepted",
    "acknowledged",
    "partially_filled",
    "partial_fill",
    "partial",
}
_STATUS_EVIDENCE_TERMINAL = {
    "filled",
    "closed",
    "canceled",
    "cancelled",
    "rejected",
    "expired",
}


@dataclass(slots=True)
class OrderStatus:
    """Order status from exchange or paper broker cache."""
    order_id: str
    status: str  # pending, open, filled, cancelled, expired, rejected
    filled_quantity: _Decimal = _Decimal("0")
    filled_price: _Decimal = _Decimal("0")
    remaining_quantity: _Decimal = _Decimal("0")
    timestamp_ns: int = 0


@dataclass(slots=True)
class ActiveOrderIdMapping:
    """Namespace-safe command mapping for active cancel/status."""
    client_order_id: str
    broker: str
    symbol: str
    side: str
    order_type: str
    venue_order_id: Optional[str]
    broker_order_id: Optional[str]
    exchange_txid: Optional[str]
    command_id_namespace: str
    command_order_id: str
    id_mapping_source: str
    submit_ts_ns: int
    ack_ts_ns: int
    status: str = "acknowledged"
    is_terminal: bool = False
    terminal_reason: Optional[str] = None
    durable: bool = False


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
        telemetry_store: Optional[TelemetryEventStore] = None,
        state_store: Optional[StateStore] = None,
        reservation_lifecycle_coordinator: Optional[Any] = None,
        reservation_lifecycle_enabled: bool = False,
        execution_broker: str = INTERNAL_PAPER_EXECUTION_BROKER,
        broker_gateway_adapter: Optional[Any] = None,
        broker_read_profile: Optional[Any] = None,
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
        self._telemetry_store = telemetry_store
        self._state_store = state_store
        self._reservation_lifecycle_coordinator = reservation_lifecycle_coordinator
        self._reservation_lifecycle_enabled = bool(reservation_lifecycle_enabled)
        self.execution_broker = str(execution_broker or INTERNAL_PAPER_EXECUTION_BROKER).strip().lower()
        self._broker_gateway_adapter = broker_gateway_adapter
        adapter_profile = getattr(broker_gateway_adapter, "broker_read_permission_profile", None)
        self._broker_read_profile: BrokerReadPermissionProfile = (
            coerce_broker_read_profile(broker_read_profile)
            if broker_read_profile is not None
            else (
                coerce_broker_read_profile(adapter_profile)
                if adapter_profile is not None
                else broker_read_profile_from_env()
            )
        )
        self._external_paper_broker_requested = bool(
            self.paper_mode and self.execution_broker != INTERNAL_PAPER_EXECUTION_BROKER
        )
        self._validate_execution_broker_selection()
        self._gateway_responses_by_client_order_id: Dict[str, BrokerGatewayResponse] = {}
        self._gateway_reconciliation_by_client_order_id: Dict[str, Dict[str, Any]] = {}
        self._shutdown_reconciliation: Dict[str, Any] = {}
        self._fill_hydration_results: List[Dict[str, Any]] = []
        self._broker_fill_activity_cache: Optional[List[Dict[str, Any]]] = None
        self._broker_fill_activity_fetch_error: Optional[str] = None
        self._broker_fee_hydration_results: List[Dict[str, Any]] = []
        self._broker_fee_activity_cache: Optional[List[Dict[str, Any]]] = None
        self._broker_fee_activity_fetch_error: Optional[str] = None
        self._broker_fee_hydration_skipped: bool = False
        self._broker_fee_hydration_skip_reason: Optional[str] = None
        self._cancel_denials_by_order_id: Dict[str, str] = {}
        self._oms_lifecycle_counts: Dict[str, int] = {
            "submitted": 0,
            "acknowledged": 0,
            "open": 0,
            "partially_filled": 0,
            "filled": 0,
            "cancel_requested": 0,
            "canceled": 0,
            "rejected": 0,
            "expired": 0,
            "reconciliation_conflicts": 0,
            "cancel_authorized": 0,
            "cancel_denied": 0,
        }
        self._broker_boundary_events: List[Dict[str, Any]] = []
        self._reservation_lifecycle_ack_open_results: List[Dict[str, Any]] = []
        self._reservation_lifecycle_partial_fill_results: List[Dict[str, Any]] = []
        self._reservation_lifecycle_full_fill_results: List[Dict[str, Any]] = []
        self._reservation_lifecycle_terminal_non_fill_results: List[Dict[str, Any]] = []

        self._paper_broker: Optional[_SovereignPaperBroker] = None
        if paper_mode and not self._external_paper_broker_requested:
            self._paper_broker = _SovereignPaperBroker(
                fee_model=_FeeModel(),
                slippage_model=_SlippageModel(),
                latency_model=_LatencyModel(),
                config=_PaperBrokerConfig(enable_short_selling=True),
            )
            logger.info("SovereignPaperBroker (app/execution/paper_broker.py) wired on live paper path")
        elif self._external_paper_broker_requested:
            logger.info("Internal SovereignPaperBroker not wired: external paper broker gateway selected")

        self._websocket_connected = False
        self._last_websocket_ping_ns = 0
        self._last_websocket_pong_ns = 0
        self._market_data_latency_source = "websocket"
        self._last_rest_market_data_request_ns = 0
        self._last_rest_market_data_response_ns = 0
        self._last_rest_market_data_latency_ms = float("inf")
        self._last_rest_market_data_provider_id: Optional[str] = None
        self._last_rest_market_data_exchange: Optional[str] = None
        self._last_rest_market_data_symbol: Optional[str] = None
        self._last_rest_market_data_feed_type: Optional[str] = None

        self._pending_orders: Dict[str, OrderRequest] = {}
        self._order_status_cache: Dict[str, OrderStatus] = {}
        self._active_order_id_mappings: Dict[Tuple[str, str], ActiveOrderIdMapping] = {}
        self._terminal_mapping_proofs: List[Dict[str, Any]] = []
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
        logger.info(
            "OrderRouter execution route: paper_mode=%s execution_broker=%s primary_exchange=%s broker_gateway_adapter=%s",
            self.paper_mode,
            self.execution_broker,
            self.primary_exchange,
            getattr(getattr(self._broker_gateway_adapter, "identity", None), "adapter_id", None),
        )

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
        self._hydrate_durable_order_mappings()
        self._reconcile_hydrated_gateway_order_mappings()

    def _validate_execution_broker_selection(self) -> None:
        """Fail closed when an external paper broker request cannot route to a gateway."""
        if not self.paper_mode and self.execution_broker != INTERNAL_PAPER_EXECUTION_BROKER:
            raise ValueError("external_execution_broker_requires_paper_mode")
        if not self._external_paper_broker_requested:
            return
        identity_error = self._broker_gateway_identity_error()
        if identity_error is not None:
            raise ValueError(identity_error)

    def _broker_gateway_identity_error(self) -> Optional[str]:
        if self._broker_gateway_adapter is None:
            return "external_paper_broker_requires_broker_gateway_adapter"
        identity = getattr(self._broker_gateway_adapter, "identity", None)
        if identity is None:
            return "broker_gateway_adapter_identity_missing"
        if getattr(identity, "environment", None) != "paper":
            return "broker_gateway_adapter_environment_not_paper"
        if getattr(identity, "live_blocked", None) is not True:
            return "broker_gateway_adapter_live_endpoint_not_blocked"
        if getattr(identity, "venue_id", None) != self.primary_exchange:
            return "broker_gateway_adapter_primary_exchange_mismatch"
        return None

    def _record_fill_telemetry(
        self,
        order: OrderRequest,
        fill: OrderFill,
        *,
        venue_fill_id: str,
        venue_order_id: Optional[str] = None,
        broker_order_id: Optional[str] = None,
        exchange_txid: Optional[str] = None,
        id_mapping_source: Optional[str] = None,
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

        metadata = self._metadata_with_lifecycle_context(
            order,
            self._build_order_lifecycle_replay_context(
                order,
                lifecycle_source="order_router.fill_observation",
                lifecycle_phase="full_fill",
                submit_seen=True,
                full_fill_seen=True,
                terminal_state="filled",
                terminal_reason="full_fill_observed",
                venue_order_id=venue_order_id,
                broker_order_id=broker_order_id,
                exchange_txid=exchange_txid,
                venue_fill_id=venue_fill_id,
                original_qty=order.quantity,
                fill_delta_qty=fill.quantity,
                cumulative_filled_qty=fill.quantity,
                remaining_qty=_Decimal("0"),
                avg_fill_price=fill.price,
                cumulative_fee=fill.fee,
                is_terminal=True,
                status_source="order_router.fill_observation",
                id_mapping_source=id_mapping_source,
            ),
        )
        strategy_value = self._order_value(order.strategy)
        metadata["strategy"] = strategy_value
        metadata["sleeve"] = strategy_value
        metadata["paper_mode"] = bool(self.paper_mode)
        metadata["requested_qty"] = str(order.quantity)

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
        self._fill_recorder.record_fill(fill_event, metadata=metadata)

    def _record_rejection_telemetry(self, order: OrderRequest, reason: str) -> None:
        """Record order rejection telemetry without changing routing authority."""
        if not self._fill_recorder:
            return
        if not order.decision_uuid:
            logger.warning("Skipping rejection telemetry for order %s: missing decision_uuid", order.id)
            return

        metadata = self._metadata_with_lifecycle_context(
            order,
            self._build_order_lifecycle_replay_context(
                order,
                lifecycle_source="order_router.rejection_observation",
                lifecycle_phase="rejected",
                submit_seen=True,
                reject_seen=True,
                terminal_state="rejected",
                terminal_reason=reason,
                original_qty=order.quantity,
                cumulative_filled_qty=_Decimal("0"),
                remaining_qty=order.quantity,
                cumulative_fee=_Decimal("0"),
                is_terminal=True,
                status_source="order_router.rejection_observation",
                id_mapping_source="order_router.client_order_id",
            ),
        )

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
            metadata=metadata,
        )

    def _record_order_submission_telemetry(self, order: OrderRequest) -> None:
        """Record order-submission telemetry as a first-class replay event."""
        if not self._fill_recorder:
            return
        if not order.decision_uuid:
            logger.warning("Skipping order submission telemetry for order %s: missing decision_uuid", order.id)
            return

        metadata = self._metadata_with_lifecycle_context(
            order,
            self._build_order_lifecycle_replay_context(
                order,
                lifecycle_source="order_router.submit_attempt",
                lifecycle_phase="order_submitted",
                submit_seen=True,
                original_qty=order.quantity,
                cumulative_filled_qty=_Decimal("0"),
                remaining_qty=order.quantity,
                cumulative_fee=_Decimal("0"),
                is_terminal=False,
                status_source="order_router.submit_attempt",
                id_mapping_source="order_router.client_order_id",
            ),
        )

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
            metadata=metadata,
        )

    def _build_order_lifecycle_replay_context(
        self,
        order: OrderRequest,
        *,
        lifecycle_source: str,
        lifecycle_phase: str,
        submit_seen: bool = False,
        ack_seen: Optional[bool] = None,
        reject_seen: Optional[bool] = None,
        partial_fill_seen: Optional[bool] = None,
        full_fill_seen: Optional[bool] = None,
        cancel_seen: Optional[bool] = None,
        terminal_state: Optional[str] = None,
        terminal_reason: Optional[str] = None,
        venue_order_id: Optional[str] = None,
        broker_order_id: Optional[str] = None,
        exchange_txid: Optional[str] = None,
        venue_fill_id: Optional[str] = None,
        original_qty: Optional[Any] = None,
        cumulative_filled_qty: Optional[Any] = None,
        fill_delta_qty: Optional[Any] = None,
        remaining_qty: Optional[Any] = None,
        avg_fill_price: Optional[Any] = None,
        cumulative_fee: Optional[Any] = None,
        is_terminal: Optional[bool] = None,
        status_source: Optional[str] = None,
        id_mapping_source: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Passive lifecycle replay facts only.

        This context is emitted for audit/replay analysis and deliberately
        refuses execution, cache, or exposure authority. It does not mutate
        router, broker, risk, or reservation state.
        """
        passive_mapping_id_namespaces = ["client_order_id"]
        if venue_order_id is not None:
            passive_mapping_id_namespaces.append("venue_order_id")
        if broker_order_id is not None:
            passive_mapping_id_namespaces.append("broker_order_id")
        if exchange_txid is not None:
            passive_mapping_id_namespaces.append("exchange_txid")
        passive_mapping_namespace = (
            "client_order_id"
            if passive_mapping_id_namespaces == ["client_order_id"]
            else "mixed/passive"
        )

        resolved_idempotency_key = idempotency_key or f"{order.decision_uuid}:{order.id}:{lifecycle_phase}"
        reservation_candidate_delta = build_passive_reservation_candidate_delta(
            lifecycle_phase=lifecycle_phase,
            client_order_id=order.id,
            decision_uuid=order.decision_uuid,
            symbol=order.symbol,
            side=order.side,
            quantity=original_qty,
            price_basis=order.limit_price if avg_fill_price is None else avg_fill_price,
            fill_delta_qty=fill_delta_qty,
            cumulative_filled_qty=cumulative_filled_qty,
            remaining_qty=remaining_qty,
            terminal_state=terminal_state,
            terminal_reason=terminal_reason,
            status_source=status_source,
            idempotency_key=resolved_idempotency_key,
        )

        return {
            "lifecycle_context_version": 1,
            "lifecycle_source": lifecycle_source,
            "client_order_id": order.id,
            "venue_order_id": str(venue_order_id) if venue_order_id is not None else None,
            "decision_uuid": order.decision_uuid,
            "event_family": "order_lifecycle",
            "lifecycle_phase": lifecycle_phase,
            "order_id_namespace": "client_order_id",
            "passive_mapping_namespace": passive_mapping_namespace,
            "passive_mapping_id_namespaces": passive_mapping_id_namespaces,
            "submit_seen": bool(submit_seen),
            "ack_seen": ack_seen,
            "reject_seen": reject_seen,
            "partial_fill_seen": partial_fill_seen,
            "full_fill_seen": full_fill_seen,
            "cancel_seen": cancel_seen,
            "is_terminal": is_terminal,
            "terminal_state": terminal_state,
            "terminal_reason": terminal_reason,
            "broker_order_id": str(broker_order_id) if broker_order_id is not None else None,
            "exchange_txid": str(exchange_txid) if exchange_txid is not None else None,
            "venue_fill_id": str(venue_fill_id) if venue_fill_id is not None else None,
            "original_qty": str(original_qty) if original_qty is not None else None,
            "cumulative_filled_qty": (
                str(cumulative_filled_qty) if cumulative_filled_qty is not None else None
            ),
            "fill_delta_qty": str(fill_delta_qty) if fill_delta_qty is not None else None,
            "remaining_qty": str(remaining_qty) if remaining_qty is not None else None,
            "avg_fill_price": str(avg_fill_price) if avg_fill_price is not None else None,
            "cumulative_fee": str(cumulative_fee) if cumulative_fee is not None else None,
            "status_source": status_source,
            "id_mapping_source": id_mapping_source,
            "idempotency_key": resolved_idempotency_key,
            "mapping_authoritative": False,
            "active_cancel_status_mapping_ready": False,
            "router_cache_authoritative": False,
            "exposure_reservation_authority": False,
            "exposure_reservation_mutated": False,
            "reservation_mapping_ready": False,
            "reservation_delta_authoritative": False,
            "reservation_candidate_delta": reservation_candidate_delta,
            "reservation_candidate_authoritative": False,
        }

    def _metadata_with_lifecycle_context(
        self,
        order: OrderRequest,
        lifecycle_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        metadata = dict(order.metadata) if isinstance(order.metadata, dict) else {}
        metadata["order_lifecycle_replay_context"] = lifecycle_context
        metadata["order_id_namespace"] = lifecycle_context.get("order_id_namespace")
        metadata["passive_mapping_namespace"] = lifecycle_context.get("passive_mapping_namespace")
        metadata["passive_mapping_id_namespaces"] = lifecycle_context.get("passive_mapping_id_namespaces")
        metadata["mapping_authoritative"] = False
        metadata["active_cancel_status_mapping_ready"] = False
        metadata["router_cache_authoritative"] = False
        metadata["reservation_mapping_ready"] = False
        metadata["reservation_delta_authoritative"] = False
        metadata["reservation_candidate_delta"] = lifecycle_context.get("reservation_candidate_delta")
        metadata["reservation_candidate_authoritative"] = False
        metadata["exposure_reservation_authority"] = False
        metadata["exposure_reservation_mutated"] = False
        return metadata

    def _order_value(self, value: Any) -> str:
        if hasattr(value, "value"):
            return str(value.value)
        return str(value)

    def _reservation_open_dedupe_key(self, order: OrderRequest) -> Optional[str]:
        metadata = order.metadata if isinstance(order.metadata, dict) else {}
        explicit_key = metadata.get("reservation_dedupe_key")
        if explicit_key:
            return str(explicit_key)
        if order.decision_uuid:
            return f"{order.decision_uuid}:{order.id}"
        return None

    def _reservation_lifecycle_paper_enabled(self) -> bool:
        return bool(self._reservation_lifecycle_enabled and self.paper_mode)

    def _record_reservation_ack_open(
        self,
        order: OrderRequest,
        *,
        ack_source: str,
        source_event_id: str,
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "action": "order_acknowledged",
            "applied": False,
            "idempotent": False,
            "skipped": True,
            "failed_reason": None,
            "client_order_id": getattr(order, "id", None),
            "reservation_id": None,
            "mutation_attempted": False,
            "broker_command_performed": False,
            "telemetry_authority_used": False,
            "exposure_manager_called": False,
            "ack_source": ack_source,
        }

        if not self._reservation_lifecycle_enabled:
            result["failed_reason"] = "reservation_lifecycle_disabled"
            self._reservation_lifecycle_ack_open_results.append(result)
            return result
        if not self._reservation_lifecycle_paper_enabled():
            result["failed_reason"] = "reservation_lifecycle_non_paper_blocked"
            self._reservation_lifecycle_ack_open_results.append(result)
            return result
        if self._reservation_lifecycle_coordinator is None:
            result["failed_reason"] = "reservation_lifecycle_coordinator_missing"
            self._reservation_lifecycle_ack_open_results.append(result)
            return result

        client_order_id = str(getattr(order, "id", "") or "").strip()
        if not client_order_id:
            result["failed_reason"] = "missing_client_order_id"
            self._reservation_lifecycle_ack_open_results.append(result)
            return result

        dedupe_key = self._reservation_open_dedupe_key(order)
        if not dedupe_key:
            result["failed_reason"] = "missing_stable_reservation_dedupe_key"
            self._reservation_lifecycle_ack_open_results.append(result)
            return result

        order_type = self._order_value(order.order_type).lower()
        if order_type != "limit":
            result["failed_reason"] = "unsupported_order_type_for_reservation_open"
            self._reservation_lifecycle_ack_open_results.append(result)
            return result

        price_basis = order.limit_price
        if price_basis is None:
            result["failed_reason"] = "missing_price_basis"
            self._reservation_lifecycle_ack_open_results.append(result)
            return result
        try:
            if _Decimal(str(price_basis)) <= _Decimal("0"):
                result["failed_reason"] = "non_positive_price_basis"
                self._reservation_lifecycle_ack_open_results.append(result)
                return result
        except Exception:
            result["failed_reason"] = "invalid_price_basis"
            self._reservation_lifecycle_ack_open_results.append(result)
            return result

        try:
            coordinator_result = self._reservation_lifecycle_coordinator.on_order_acknowledged(
                client_order_id=client_order_id,
                reservation_id=client_order_id,
                decision_uuid=order.decision_uuid,
                reservation_dedupe_key=dedupe_key,
                symbol=order.symbol,
                side=order.side,
                sleeve=order.strategy,
                qty=order.quantity,
                price_basis=price_basis,
                order_type=order_type,
                source_lifecycle_phase="order_acknowledged",
                source_idempotency_key=f"{dedupe_key}:order_acknowledged:{source_event_id}",
                price_basis_source_proven=True,
                mutation_authority_source="direct_lifecycle",
            )
        except Exception as exc:
            result["failed_reason"] = f"reservation_lifecycle_call_failed:{exc}"
            self._reservation_lifecycle_ack_open_results.append(result)
            logger.exception("Reservation lifecycle ack/open call failed for %s", client_order_id)
            return result

        result.update(dict(coordinator_result))
        result["ack_source"] = ack_source
        self._reservation_lifecycle_ack_open_results.append(result)
        return result

    def _record_reservation_partial_fill(
        self,
        order: OrderRequest,
        *,
        fill_idempotency_key: str,
        cumulative_filled_qty: Any,
        fill_delta_qty: Any,
        status_source: str,
        source_event_id: str,
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "action": "partial_fill",
            "applied": False,
            "idempotent": False,
            "skipped": True,
            "failed_reason": None,
            "client_order_id": getattr(order, "id", None),
            "reservation_id": None,
            "mutation_attempted": False,
            "broker_command_performed": False,
            "telemetry_authority_used": False,
            "exposure_manager_called": False,
            "status_source": status_source,
        }

        if not self._reservation_lifecycle_enabled:
            result["failed_reason"] = "reservation_lifecycle_disabled"
            self._reservation_lifecycle_partial_fill_results.append(result)
            return result
        if not self._reservation_lifecycle_paper_enabled():
            result["failed_reason"] = "reservation_lifecycle_non_paper_blocked"
            self._reservation_lifecycle_partial_fill_results.append(result)
            return result
        if self._reservation_lifecycle_coordinator is None:
            result["failed_reason"] = "reservation_lifecycle_coordinator_missing"
            self._reservation_lifecycle_partial_fill_results.append(result)
            return result

        client_order_id = str(getattr(order, "id", "") or "").strip()
        if not client_order_id:
            result["failed_reason"] = "missing_client_order_id"
            self._reservation_lifecycle_partial_fill_results.append(result)
            return result

        dedupe_key = self._reservation_open_dedupe_key(order)
        if not dedupe_key:
            result["failed_reason"] = "missing_stable_reservation_dedupe_key"
            self._reservation_lifecycle_partial_fill_results.append(result)
            return result
        if not str(fill_idempotency_key or "").strip():
            result["failed_reason"] = "missing_stable_fill_idempotency_key"
            self._reservation_lifecycle_partial_fill_results.append(result)
            return result
        if cumulative_filled_qty is None:
            result["failed_reason"] = "missing_cumulative_filled_qty"
            self._reservation_lifecycle_partial_fill_results.append(result)
            return result
        if fill_delta_qty is None:
            result["failed_reason"] = "missing_fill_delta_qty"
            self._reservation_lifecycle_partial_fill_results.append(result)
            return result

        try:
            coordinator_result = self._reservation_lifecycle_coordinator.on_partial_fill(
                client_order_id=client_order_id,
                reservation_id=client_order_id,
                reservation_dedupe_key=dedupe_key,
                fill_idempotency_key=fill_idempotency_key,
                cumulative_filled_qty=cumulative_filled_qty,
                fill_delta_qty=fill_delta_qty,
                status_source=status_source,
                source_event_id=source_event_id,
                mutation_authority_source="direct_lifecycle",
            )
        except Exception as exc:
            result["failed_reason"] = f"reservation_lifecycle_partial_fill_call_failed:{exc}"
            self._reservation_lifecycle_partial_fill_results.append(result)
            logger.exception("Reservation lifecycle partial-fill call failed for %s", client_order_id)
            return result

        result.update(dict(coordinator_result))
        result["status_source"] = status_source
        self._reservation_lifecycle_partial_fill_results.append(result)
        return result

    def _record_reservation_full_fill(
        self,
        order: OrderRequest,
        *,
        release_idempotency_key: str,
        cumulative_filled_qty: Any,
        fill_delta_qty: Any,
        status_source: str,
        terminal_source: str,
        source_event_id: str,
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "action": "full_fill",
            "applied": False,
            "idempotent": False,
            "skipped": True,
            "failed_reason": None,
            "client_order_id": getattr(order, "id", None),
            "reservation_id": None,
            "mutation_attempted": False,
            "broker_command_performed": False,
            "telemetry_authority_used": False,
            "exposure_manager_called": False,
            "status_source": status_source,
            "terminal_status": "filled",
            "terminal_source": terminal_source,
        }

        if not self._reservation_lifecycle_enabled:
            result["failed_reason"] = "reservation_lifecycle_disabled"
            self._reservation_lifecycle_full_fill_results.append(result)
            return result
        if not self._reservation_lifecycle_paper_enabled():
            result["failed_reason"] = "reservation_lifecycle_non_paper_blocked"
            self._reservation_lifecycle_full_fill_results.append(result)
            return result
        if self._reservation_lifecycle_coordinator is None:
            result["failed_reason"] = "reservation_lifecycle_coordinator_missing"
            self._reservation_lifecycle_full_fill_results.append(result)
            return result

        client_order_id = str(getattr(order, "id", "") or "").strip()
        if not client_order_id:
            result["failed_reason"] = "missing_client_order_id"
            self._reservation_lifecycle_full_fill_results.append(result)
            return result

        dedupe_key = self._reservation_open_dedupe_key(order)
        if not dedupe_key:
            result["failed_reason"] = "missing_stable_reservation_dedupe_key"
            self._reservation_lifecycle_full_fill_results.append(result)
            return result
        if not str(release_idempotency_key or "").strip():
            result["failed_reason"] = "missing_stable_release_idempotency_key"
            self._reservation_lifecycle_full_fill_results.append(result)
            return result
        if cumulative_filled_qty is None:
            result["failed_reason"] = "missing_cumulative_filled_qty"
            self._reservation_lifecycle_full_fill_results.append(result)
            return result

        try:
            coordinator_result = self._reservation_lifecycle_coordinator.on_full_fill(
                client_order_id=client_order_id,
                reservation_id=client_order_id,
                reservation_dedupe_key=dedupe_key,
                release_idempotency_key=release_idempotency_key,
                cumulative_filled_qty=cumulative_filled_qty,
                fill_idempotency_key=f"{release_idempotency_key}:fill",
                fill_delta_qty=fill_delta_qty,
                status_source=status_source,
                source_event_id=source_event_id,
                terminal_source=terminal_source,
                mutation_authority_source="direct_lifecycle",
            )
        except Exception as exc:
            result["failed_reason"] = f"reservation_lifecycle_full_fill_call_failed:{exc}"
            self._reservation_lifecycle_full_fill_results.append(result)
            logger.exception("Reservation lifecycle full-fill call failed for %s", client_order_id)
            return result

        result.update(dict(coordinator_result))
        result["status_source"] = status_source
        result["terminal_status"] = "filled"
        result["terminal_source"] = terminal_source
        self._reservation_lifecycle_full_fill_results.append(result)
        return result

    def _record_reservation_terminal_non_fill(
        self,
        order: OrderRequest,
        *,
        release_idempotency_key: str,
        terminal_status: str,
        terminal_source: str,
        terminal_reason: str,
        source_event_id: str,
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "action": "terminal_non_fill",
            "applied": False,
            "idempotent": False,
            "skipped": True,
            "failed_reason": None,
            "client_order_id": getattr(order, "id", None),
            "reservation_id": None,
            "mutation_attempted": False,
            "broker_command_performed": False,
            "telemetry_authority_used": False,
            "exposure_manager_called": False,
            "terminal_status": terminal_status,
            "terminal_source": terminal_source,
            "terminal_reason": terminal_reason,
        }

        if not self._reservation_lifecycle_enabled:
            result["failed_reason"] = "reservation_lifecycle_disabled"
            self._reservation_lifecycle_terminal_non_fill_results.append(result)
            return result
        if not self._reservation_lifecycle_paper_enabled():
            result["failed_reason"] = "reservation_lifecycle_non_paper_blocked"
            self._reservation_lifecycle_terminal_non_fill_results.append(result)
            return result
        if self._reservation_lifecycle_coordinator is None:
            result["failed_reason"] = "reservation_lifecycle_coordinator_missing"
            self._reservation_lifecycle_terminal_non_fill_results.append(result)
            return result

        client_order_id = str(getattr(order, "id", "") or "").strip()
        if not client_order_id:
            result["failed_reason"] = "missing_client_order_id"
            self._reservation_lifecycle_terminal_non_fill_results.append(result)
            return result

        dedupe_key = self._reservation_open_dedupe_key(order)
        if not dedupe_key:
            result["failed_reason"] = "missing_stable_reservation_dedupe_key"
            self._reservation_lifecycle_terminal_non_fill_results.append(result)
            return result
        if not str(release_idempotency_key or "").strip():
            result["failed_reason"] = "missing_stable_release_idempotency_key"
            self._reservation_lifecycle_terminal_non_fill_results.append(result)
            return result

        try:
            coordinator_result = self._reservation_lifecycle_coordinator.on_terminal_non_fill(
                client_order_id=client_order_id,
                reservation_id=client_order_id,
                decision_uuid=order.decision_uuid,
                reservation_dedupe_key=dedupe_key,
                release_idempotency_key=release_idempotency_key,
                terminal_status=terminal_status,
                terminal_source=terminal_source,
                terminal_reason=terminal_reason,
                source_event_id=source_event_id,
                mutation_authority_source="direct_lifecycle",
            )
        except Exception as exc:
            result["failed_reason"] = f"reservation_lifecycle_terminal_non_fill_call_failed:{exc}"
            self._reservation_lifecycle_terminal_non_fill_results.append(result)
            logger.exception("Reservation lifecycle terminal non-fill call failed for %s", client_order_id)
            return result

        result.update(dict(coordinator_result))
        result["terminal_status"] = terminal_status
        result["terminal_source"] = terminal_source
        result["terminal_reason"] = terminal_reason
        self._reservation_lifecycle_terminal_non_fill_results.append(result)
        return result

    def _mapping_broker(self) -> str:
        return "paper" if self.paper_mode else str(self.primary_exchange).lower()

    def _value_as_str(self, value: Any) -> str:
        if hasattr(value, "value"):
            return str(value.value)
        return str(value)

    def _command_namespace_for_broker(self, broker: str) -> str:
        if broker == "kraken":
            return "exchange_txid"
        if broker == "alpaca":
            return "venue_order_id"
        if broker == "paper":
            return "client_order_id"
        return ""

    def _mapping_to_store_record(self, mapping: ActiveOrderIdMapping) -> Dict[str, Any]:
        return {
            "client_order_id": mapping.client_order_id,
            "broker": mapping.broker,
            "symbol": mapping.symbol,
            "side": mapping.side,
            "order_type": mapping.order_type,
            "venue_order_id": mapping.venue_order_id,
            "broker_order_id": mapping.broker_order_id,
            "exchange_txid": mapping.exchange_txid,
            "command_id_namespace": mapping.command_id_namespace,
            "command_order_id": mapping.command_order_id,
            "id_mapping_source": mapping.id_mapping_source,
            "submit_ts_ns": mapping.submit_ts_ns,
            "ack_ts_ns": mapping.ack_ts_ns,
            "status": mapping.status,
            "is_terminal": mapping.is_terminal,
            "terminal_reason": mapping.terminal_reason,
        }

    def _mapping_from_record(self, record: Dict[str, Any]) -> Optional[ActiveOrderIdMapping]:
        try:
            return ActiveOrderIdMapping(
                client_order_id=str(record["client_order_id"]),
                broker=str(record["broker"]),
                symbol=str(record.get("symbol") or ""),
                side=str(record.get("side") or ""),
                order_type=str(record.get("order_type") or ""),
                venue_order_id=record.get("venue_order_id"),
                broker_order_id=record.get("broker_order_id"),
                exchange_txid=record.get("exchange_txid"),
                command_id_namespace=str(record["command_id_namespace"]),
                command_order_id=str(record["command_order_id"]),
                id_mapping_source=str(record.get("id_mapping_source") or ""),
                submit_ts_ns=int(record.get("submit_ts_ns") or 0),
                ack_ts_ns=int(record.get("ack_ts_ns") or 0),
                status=str(record.get("status") or "unknown"),
                is_terminal=bool(record.get("is_terminal")),
                terminal_reason=record.get("terminal_reason"),
                durable=True,
            )
        except Exception as exc:
            logger.error("Invalid stored order ID mapping: %s", exc)
            return None

    def _hydrate_durable_order_mappings(self) -> None:
        """Load non-terminal durable order mappings for broker-truth reconciliation."""
        if self._state_store is None:
            return
        broker = self._gateway_order_mapping_broker() if self._external_paper_broker_requested else self._mapping_broker()
        try:
            records = self._state_store.list_order_id_mappings(
                broker=broker,
                include_terminal=False,
            )
        except Exception as exc:
            logger.warning(
                "[OMS_DIAG] DURABLE_MAPPING_HYDRATION_FAILED fields=%s",
                {"broker": broker, "reason_code": str(exc), "broker_post": False},
            )
            return

        hydrated = 0
        for record in records:
            mapping = self._mapping_from_record(record)
            if mapping is None:
                continue
            self._active_order_id_mappings[(mapping.broker, mapping.client_order_id)] = mapping
            hydrated += 1
        if hydrated:
            logger.info(
                "[OMS_DIAG] DURABLE_MAPPING_HYDRATED fields=%s",
                {
                    "broker": broker,
                    "hydrated_mappings": hydrated,
                    "broker_post": False,
                },
            )

    def _reconcile_hydrated_gateway_order_mappings(self) -> None:
        """Read-only broker reconciliation for persisted external PAPER mappings."""
        if not self._external_paper_broker_requested or self._broker_gateway_adapter is None:
            return
        broker = self._gateway_order_mapping_broker()
        mappings = [
            mapping
            for (mapping_broker, _client_order_id), mapping in list(self._active_order_id_mappings.items())
            if mapping_broker == broker and not mapping.is_terminal
        ]
        for mapping in mappings:
            self._reconcile_gateway_mapping(mapping, source_event="startup_hydrated_mapping")

    def _reconcile_gateway_mapping(
        self,
        mapping: ActiveOrderIdMapping,
        *,
        source_event: str,
    ) -> Dict[str, Any]:
        adapter = self._broker_gateway_adapter
        evidence: Dict[str, Any] = {
            "client_order_id": mapping.client_order_id,
            "broker_order_id": mapping.broker_order_id or mapping.venue_order_id,
            "status": OmsOrderState.RECONCILIATION_CONFLICT.value,
            "reason_codes": [],
            "source_event": source_event,
            "account_status": "not_checked",
            "open_orders_count": None,
            "positions_count": None,
            "order_id_mapping_present": True,
            "broker_truth_wins_after_ack": True,
            "local_state_authority": "supporting_evidence_only",
            "mutation_performed": False,
        }
        if adapter is None or not mapping.command_order_id:
            evidence["reason_codes"].append(OmsReasonCode.BROKER_STATE_UNKNOWN.value)
            self._gateway_reconciliation_by_client_order_id[mapping.client_order_id] = evidence
            self._record_oms_state(OmsOrderState.RECONCILIATION_CONFLICT.value)
            return evidence

        try:
            status_response = adapter.get_order_status(mapping.command_order_id)
            open_orders_response = adapter.get_open_orders()
            positions_response = adapter.get_positions()
            account_response = adapter.get_account()
        except BrokerGatewayError as exc:
            evidence["reason_codes"].append(exc.reason_code or OmsReasonCode.BROKER_STATE_UNKNOWN.value)
            self._gateway_reconciliation_by_client_order_id[mapping.client_order_id] = evidence
            self._record_oms_state(OmsOrderState.RECONCILIATION_CONFLICT.value)
            logger.info("[OMS_DIAG] GATEWAY_MAPPING_RECONCILIATION fields=%s", evidence)
            return evidence

        responses = (status_response, open_orders_response, positions_response, account_response)
        evidence["mutation_performed"] = any(bool(getattr(item, "mutation_occurred", False)) for item in responses)
        evidence["account_status"] = (
            str((account_response.payload or {}).get("status"))
            if isinstance(account_response.payload, dict)
            else "unknown"
        )
        open_orders = open_orders_response.payload if isinstance(open_orders_response.payload, list) else []
        positions = positions_response.payload if isinstance(positions_response.payload, list) else []
        evidence["open_orders_count"] = len(open_orders)
        evidence["positions_count"] = len(positions)

        if any(not item.ok for item in responses):
            evidence["reason_codes"].append(OmsReasonCode.BROKER_STATE_UNKNOWN.value)
        if evidence["mutation_performed"]:
            evidence["reason_codes"].append(OmsReasonCode.RECONCILIATION_CONFLICT.value)

        broker_status = str(getattr(status_response, "normalized_status", "") or "")
        oms_state = canonical_state_from_broker_status(broker_status)
        payload = status_response.payload if isinstance(status_response.payload, dict) else {}
        payload_symbol = payload.get("symbol")
        if payload_symbol and self._normalize_broker_symbol(payload_symbol) != self._normalize_broker_symbol(mapping.symbol):
            evidence["reason_codes"].append(OmsReasonCode.RECONCILIATION_CONFLICT.value)
            oms_state = OmsOrderState.RECONCILIATION_CONFLICT.value
        if not status_response.ok:
            oms_state = OmsOrderState.RECONCILIATION_CONFLICT.value

        evidence["status"] = oms_state
        evidence["broker_normalized_status"] = broker_status
        if oms_state in {OmsOrderState.FILLED.value, OmsOrderState.PARTIALLY_FILLED.value} or (
            self._decimal_from_payload(payload, ("filled_qty", "filled_quantity", "qty")) or _Decimal("0")
        ) > 0:
            evidence["fill_hydration"] = self._hydrate_fill_ledger_from_broker_payload(
                mapping,
                payload,
                source_event=source_event,
            )
        evidence["reason_codes"] = tuple(dict.fromkeys(evidence["reason_codes"]))
        self._gateway_reconciliation_by_client_order_id[mapping.client_order_id] = evidence
        self._record_oms_state(oms_state)

        if oms_state == OmsOrderState.RECONCILIATION_CONFLICT.value:
            self._mark_active_order_mapping_terminal_for_broker(
                mapping.client_order_id,
                mapping.broker,
                status="reconciliation_conflict",
                terminal_reason=f"{source_event}_conflict",
            )
            self._pending_orders.pop(mapping.client_order_id, None)
        elif is_terminal_oms_state(oms_state):
            self._mark_active_order_mapping_terminal_for_broker(
                mapping.client_order_id,
                mapping.broker,
                status=oms_state.lower(),
                terminal_reason=f"{source_event}_terminal",
            )
            self._pending_orders.pop(mapping.client_order_id, None)
        else:
            mapping.status = oms_state.lower()
            if self._state_store is not None:
                mapping.durable = self._state_store.upsert_order_id_mapping(
                    self._mapping_to_store_record(mapping)
                )

        logger.info("[OMS_DIAG] GATEWAY_MAPPING_RECONCILIATION fields=%s", evidence)
        return evidence

    def finalize_oms_shutdown_reconciliation(self) -> Dict[str, Any]:
        """Perform read-only broker reconciliation immediately before shutdown accounting."""
        evidence: Dict[str, Any] = {
            "source_event": "shutdown_final_reconciliation",
            "performed": False,
            "account_status": "not_checked",
            "open_orders_count": None,
            "local_open_orders_before_final_reconcile": 0,
            "broker_confirmed_open_orders": 0,
            "local_open_orders_after_final_reconcile": 0,
            "local_open_without_broker_match_count": 0,
            "final_state_unknown_count": 0,
            "reconciliation_conflict_count": 0,
            "fill_hydration_attempted_count": 0,
            "fill_hydration_count": 0,
            "fill_hydration_partial_count": 0,
            "fill_hydration_missing_count": 0,
            "fill_hydration_conflict_count": 0,
            "broker_filled_orders": 0,
            "broker_partially_filled_orders": 0,
            "broker_canceled_with_fill_count": 0,
            "tca_records_count": 0,
            "tca_unknown_count": 0,
            "broker_fee_hydration_attempted_count": 0,
            "broker_fee_hydration_count": 0,
            "broker_fee_hydration_pending_count": 0,
            "broker_fee_hydration_unmatched_count": 0,
            "broker_fee_hydration_conflict_count": 0,
            "broker_fee_activity_records_seen_count": 0,
            "broker_fee_activity_records_matched_count": 0,
            "broker_fee_activity_duplicate_ignored_count": 0,
            "fee_hydration_skipped": False,
            "fee_hydration_skip_reason": None,
            "account_activity_read_authorized": self._broker_read_allowed(READ_ACCOUNT_ACTIVITIES),
            "broker_read_profile": self._broker_read_profile.name,
            "tca_complete_count": 0,
            "tca_estimated_count": 0,
            "tca_fee_pending_count": 0,
            "realized_vs_modeled_netedge_available_count": 0,
            "realized_vs_modeled_netedge_unknown_count": 0,
            "positions_count": None,
            "local_order_id_mappings": 0,
            "local_fills": 0,
            "legacy_local_fills": 0,
            "broker_open_orders_matched_mapping_count": 0,
            "broker_open_orders_unmatched_count": 0,
            "reconciled_active_mappings": 0,
            "final_nonterminal_resolutions": (),
            "reason_codes": [],
            "mutation_performed": False,
            "broker_truth_wins_after_ack": True,
            "local_state_authority": "supporting_evidence_only",
        }
        if not self._external_paper_broker_requested or self._broker_gateway_adapter is None:
            evidence["reason_codes"].append("BROKER_GATEWAY_NOT_ACTIVE")
            self._shutdown_reconciliation = evidence
            return evidence

        broker = self._gateway_order_mapping_broker()
        final_resolutions: List[Dict[str, Any]] = []
        for (mapping_broker, _client_order_id), mapping in list(self._active_order_id_mappings.items()):
            if mapping_broker == broker and not mapping.is_terminal:
                resolution = self._reconcile_gateway_mapping(mapping, source_event="shutdown_active_mapping")
                final_resolutions.append(resolution)
                evidence["reconciled_active_mappings"] += 1

        try:
            open_orders_response = self._broker_gateway_adapter.get_open_orders()
            positions_response = self._broker_gateway_adapter.get_positions()
            account_response = self._broker_gateway_adapter.get_account()
        except BrokerGatewayError as exc:
            evidence["reason_codes"].append(exc.reason_code or OmsReasonCode.BROKER_STATE_UNKNOWN.value)
            self._shutdown_reconciliation = evidence
            logger.info("[OMS_DIAG] SHUTDOWN_RECONCILIATION fields=%s", evidence)
            return evidence

        responses = (open_orders_response, positions_response, account_response)
        evidence["performed"] = True
        evidence["mutation_performed"] = any(bool(getattr(item, "mutation_occurred", False)) for item in responses)
        if evidence["mutation_performed"]:
            evidence["reason_codes"].append(OmsReasonCode.RECONCILIATION_CONFLICT.value)
        if any(not item.ok for item in responses):
            evidence["reason_codes"].append(OmsReasonCode.BROKER_STATE_UNKNOWN.value)

        open_orders = open_orders_response.payload if isinstance(open_orders_response.payload, list) else []
        positions = positions_response.payload if isinstance(positions_response.payload, list) else []
        open_order_ids = self._broker_open_order_identity_set(open_orders)
        evidence["open_orders_count"] = len(open_orders)
        evidence["broker_confirmed_open_orders"] = len(open_orders)
        evidence["positions_count"] = len(positions)
        evidence["account_status"] = (
            str((account_response.payload or {}).get("status"))
            if isinstance(account_response.payload, dict)
            else "unknown"
        )

        mapping_rows: List[Dict[str, Any]] = []
        if self._state_store is not None:
            try:
                mapping_rows = self._state_store.list_order_id_mappings(broker=broker, include_terminal=True)
            except Exception:
                mapping_rows = []
            self._hydrate_missing_fill_ledger_for_terminal_filled_mappings(
                mapping_rows,
                source_event="shutdown_final_reconciliation_terminal_fill_ledger",
            )
            counter = getattr(self._state_store, "count_table_rows", None)
            if callable(counter):
                evidence["legacy_local_fills"] = int(counter("fills"))
                evidence["local_fills"] = int(counter("broker_fill_ledger"))
        evidence["local_order_id_mappings"] = len(mapping_rows)
        evidence["local_open_orders_before_final_reconcile"] = sum(
            1 for row in mapping_rows if self._is_local_open_order_mapping(row)
        )
        mapped_order_identities: set[str] = set()
        for row in mapping_rows:
            mapping = self._mapping_from_record(row)
            if mapping is not None:
                mapped_order_identities.update(self._mapping_identity_values(mapping))
        matched_open_orders = 0
        for open_order in open_orders:
            row_identities = self._broker_open_order_identity_set([open_order])
            if row_identities & mapped_order_identities:
                matched_open_orders += 1
        evidence["broker_open_orders_matched_mapping_count"] = matched_open_orders
        evidence["broker_open_orders_unmatched_count"] = max(0, len(open_orders) - matched_open_orders)
        for row in mapping_rows:
            if not self._is_local_open_order_mapping(row):
                continue
            mapping = self._mapping_from_record(row)
            if mapping is None:
                continue
            resolution = self._resolve_nonterminal_mapping_against_final_broker_truth(
                mapping,
                open_order_ids=open_order_ids,
                source_event="shutdown_final_reconciliation",
            )
            final_resolutions.append(resolution)
            if OmsReasonCode.BROKER_FINAL_STATE_UNKNOWN.value in resolution.get("reason_codes", ()):
                evidence["final_state_unknown_count"] += 1
            if resolution.get("status") == OmsOrderState.RECONCILIATION_CONFLICT.value:
                evidence["reconciliation_conflict_count"] += 1

        if self._state_store is not None:
            try:
                mapping_rows = self._state_store.list_order_id_mappings(broker=broker, include_terminal=True)
            except Exception:
                mapping_rows = []
            self._hydrate_deferred_broker_fees(source_event="shutdown_final_reconciliation_fee_hydration")
            counter = getattr(self._state_store, "count_table_rows", None)
            if callable(counter):
                evidence["legacy_local_fills"] = int(counter("fills"))
                evidence["local_fills"] = int(counter("broker_fill_ledger"))
        local_open_after = [
            row for row in mapping_rows
            if self._is_local_open_order_mapping(row)
        ]
        evidence["local_open_orders_after_final_reconcile"] = len(local_open_after)
        local_open_without_broker_match_count = 0
        for row in local_open_after:
            mapping = self._mapping_from_record(row)
            if mapping is None or not self._mapping_matches_broker_open_orders(mapping, open_order_ids):
                local_open_without_broker_match_count += 1
        evidence["local_open_without_broker_match_count"] = local_open_without_broker_match_count
        evidence["final_nonterminal_resolutions"] = tuple(final_resolutions)
        evidence["fill_hydration_attempted_count"] = len(self._fill_hydration_results)
        evidence["fill_hydration_count"] = sum(
            1 for result in self._fill_hydration_results if result.get("inserted") is True
        )
        evidence["fill_hydration_partial_count"] = sum(
            1 for result in self._fill_hydration_results if result.get("status") == "PARTIAL"
        )
        evidence["fill_hydration_missing_count"] = sum(
            1
            for result in self._fill_hydration_results
            if OmsReasonCode.FILL_LEDGER_UNAVAILABLE.value in result.get("reason_codes", ())
        )
        evidence["fill_hydration_conflict_count"] = sum(
            1 for result in self._fill_hydration_results if result.get("status") == "CONFLICT"
        )
        evidence["tca_records_count"] = sum(
            1 for result in self._fill_hydration_results if result.get("inserted") is True
        )
        evidence["tca_unknown_count"] = sum(
            1
            for result in self._fill_hydration_results
            if result.get("inserted") is True
            and result.get("execution_quality_verdict") == "UNKNOWN_INSUFFICIENT_BROKER_DETAIL"
        )
        evidence["realized_vs_modeled_netedge_available_count"] = sum(
            1 for result in self._fill_hydration_results if result.get("realized_netedge_available") is True
        )
        evidence["realized_vs_modeled_netedge_unknown_count"] = max(
            0,
            int(evidence["tca_records_count"]) - int(evidence["realized_vs_modeled_netedge_available_count"]),
        )
        evidence.update(self._broker_fee_hydration_summary())
        evidence["broker_filled_orders"] = sum(
            1 for row in mapping_rows if str(row.get("status") or "").lower() == "filled"
        )
        evidence["broker_partially_filled_orders"] = sum(
            1 for row in mapping_rows if str(row.get("status") or "").lower() in {"partially_filled", "partial_fill", "partial"}
        )
        evidence["broker_canceled_with_fill_count"] = sum(
            1
            for result in self._fill_hydration_results
            if str(result.get("known_broker_terminal_status") or "").lower() in {"canceled", "cancelled"}
            and result.get("inserted") is True
        )
        evidence["reconciliation_conflict_count"] = max(
            int(evidence["reconciliation_conflict_count"]),
            int(self._oms_lifecycle_counts.get("reconciliation_conflicts", 0) or 0),
        )
        evidence["reason_codes"] = tuple(dict.fromkeys(evidence["reason_codes"]))
        self._shutdown_reconciliation = evidence
        logger.info("[OMS_DIAG] SHUTDOWN_RECONCILIATION fields=%s", evidence)
        return evidence

    def _register_active_order_id_mapping(
        self,
        order: OrderRequest,
        *,
        broker: str,
        venue_order_id: Optional[str],
        broker_order_id: Optional[str],
        exchange_txid: Optional[str],
        id_mapping_source: str,
        ack_ts_ns: int,
        status: str = "acknowledged",
        is_terminal: bool = False,
        terminal_reason: Optional[str] = None,
    ) -> bool:
        namespace = self._command_namespace_for_broker(broker)
        command_order_id = {
            "client_order_id": order.id,
            "venue_order_id": venue_order_id,
            "exchange_txid": exchange_txid,
        }.get(namespace)
        if not namespace or not command_order_id:
            logger.error("Unsafe order ID mapping for %s/%s: missing %s", broker, order.id, namespace)
            return False

        mapping = ActiveOrderIdMapping(
            client_order_id=order.id,
            broker=broker,
            symbol=order.symbol,
            side=self._value_as_str(order.side),
            order_type=self._value_as_str(order.order_type),
            venue_order_id=str(venue_order_id) if venue_order_id is not None else None,
            broker_order_id=str(broker_order_id) if broker_order_id is not None else None,
            exchange_txid=str(exchange_txid) if exchange_txid is not None else None,
            command_id_namespace=namespace,
            command_order_id=str(command_order_id),
            id_mapping_source=id_mapping_source,
            submit_ts_ns=int(getattr(order, "exchange_ts_ns", 0) or 0),
            ack_ts_ns=int(ack_ts_ns),
            status=status,
            is_terminal=is_terminal,
            terminal_reason=terminal_reason,
        )

        if self._state_store is not None:
            mapping.durable = self._state_store.upsert_order_id_mapping(
                self._mapping_to_store_record(mapping)
            )
        self._active_order_id_mappings[(broker, order.id)] = mapping
        return mapping.durable or self.paper_mode

    def _get_active_order_id_mapping(self, client_order_id: str, broker: str) -> Optional[ActiveOrderIdMapping]:
        mapping = self._active_order_id_mappings.get((broker, client_order_id))
        if mapping is not None:
            return mapping
        if self._state_store is None:
            return None
        record = self._state_store.get_order_id_mapping(client_order_id, broker)
        if record is None:
            return None
        mapping = self._mapping_from_record(record)
        if mapping is not None:
            self._active_order_id_mappings[(broker, client_order_id)] = mapping
        return mapping

    def _mark_active_order_mapping_terminal(
        self,
        client_order_id: str,
        *,
        status: str,
        terminal_reason: Optional[str],
    ) -> None:
        broker = self._mapping_broker()
        self._mark_active_order_mapping_terminal_for_broker(
            client_order_id,
            broker,
            status=status,
            terminal_reason=terminal_reason,
        )

    def _mark_active_order_mapping_terminal_for_broker(
        self,
        client_order_id: str,
        broker: str,
        *,
        status: str,
        terminal_reason: Optional[str],
    ) -> None:
        mapping = self._get_active_order_id_mapping(client_order_id, broker)
        if mapping is None:
            return
        mapping.status = status
        mapping.is_terminal = True
        mapping.terminal_reason = terminal_reason
        self._pending_orders.pop(client_order_id, None)
        if self._state_store is not None:
            mapping.durable = self._state_store.upsert_order_id_mapping(
                self._mapping_to_store_record(mapping)
            )

    def is_order_terminal(self, client_order_id: str) -> bool:
        """Return whether broker/local OMS truth says an order is terminal."""
        client_id = str(client_order_id or "").strip()
        if not client_id:
            return False
        for broker in {self._gateway_order_mapping_broker(), self._mapping_broker(), "paper"}:
            mapping = self._get_order_id_mapping_read_only(client_id, broker)
            if mapping is not None and mapping.is_terminal:
                self._pending_orders.pop(client_id, None)
                return True
        status = self.get_order_status(client_id)
        canonical_state = canonical_state_from_broker_status(status)
        if is_terminal_oms_state(canonical_state):
            self._pending_orders.pop(client_id, None)
            return True
        return False

    def _resolve_live_command_order_id(self, client_order_id: str, *, allow_terminal_status: bool = False) -> Optional[str]:
        broker = self._mapping_broker()
        mapping = self._get_active_order_id_mapping(client_order_id, broker)
        if mapping is None:
            logger.error("No active order ID mapping for %s/%s; refusing live command", broker, client_order_id)
            return None
        if not mapping.durable:
            logger.error("Non-durable order ID mapping for %s/%s; refusing live command", broker, client_order_id)
            return None
        if mapping.is_terminal and not allow_terminal_status:
            logger.info("Terminal order mapping for %s/%s prevents live cancel", broker, client_order_id)
            return None
        expected_namespace = self._command_namespace_for_broker(broker)
        if mapping.command_id_namespace != expected_namespace or not mapping.command_order_id:
            logger.error("Unsafe order ID namespace for %s/%s; refusing live command", broker, client_order_id)
            return None
        return mapping.command_order_id

    def _get_order_id_mapping_read_only(
        self,
        client_order_id: str,
        broker: str,
    ) -> Optional[ActiveOrderIdMapping]:
        mapping = self._active_order_id_mappings.get((broker, client_order_id))
        if mapping is not None:
            return mapping
        if self._state_store is None:
            return None
        record = self._state_store.get_order_id_mapping(client_order_id, broker)
        if record is None:
            return None
        return self._mapping_from_record(record)

    def _status_evidence_base(
        self,
        *,
        client_order_id: str,
        broker: str,
        command_id_namespace: Optional[str] = None,
        command_order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return {
            "client_order_id": client_order_id,
            "broker": broker,
            "venue": broker,
            "command_id_namespace": command_id_namespace,
            "command_order_id": command_order_id,
            "status_raw": None,
            "status_classification": "unknown_or_failed",
            "terminal_observed": False,
            "status_refresh_succeeded": False,
            "failure_reason": None,
            "mutation_performed": False,
            "command_performed": False,
            "recommended_action": "alert_only_retry_under_guard_or_board_review",
            "prohibited_actions": [
                "auto_cancel",
                "auto_terminalize",
                "broker_repair",
                "pending_cleanup",
                "exposure_release",
                "reservation_mutation",
            ],
        }

    def _classify_status_evidence(self, status_raw: Any) -> Tuple[str, bool]:
        status = str(status_raw or "").strip().lower()
        if status in _STATUS_EVIDENCE_TERMINAL:
            return "terminal_observed", True
        if status in _STATUS_EVIDENCE_OPEN_OR_PENDING:
            return "open_or_pending", False
        return "unknown_or_failed", False

    def _status_evidence_with_result(
        self,
        evidence: Dict[str, Any],
        *,
        status_raw: Any,
        failure_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        classification, terminal_observed = self._classify_status_evidence(status_raw)
        evidence["status_raw"] = str(status_raw) if status_raw is not None else None
        evidence["status_classification"] = classification
        evidence["terminal_observed"] = terminal_observed
        evidence["status_refresh_succeeded"] = failure_reason is None and classification != "unknown_or_failed"
        evidence["failure_reason"] = failure_reason
        if classification == "open_or_pending":
            evidence["recommended_action"] = "preserve_pending_and_continue_alert_monitoring"
        elif classification == "terminal_observed":
            evidence["recommended_action"] = "record_terminal_proof_for_board_policy_review"
        return evidence

    def _status_evidence_failure(
        self,
        evidence: Dict[str, Any],
        *,
        classification: str,
        failure_reason: str,
    ) -> Dict[str, Any]:
        evidence["status_classification"] = classification
        evidence["failure_reason"] = failure_reason
        evidence["status_refresh_succeeded"] = False
        evidence["terminal_observed"] = False
        if classification == "mapping_missing_or_unsafe":
            evidence["recommended_action"] = "fail_closed_mapping_review"
            evidence["prohibited_actions"] = ["live_status_request", *evidence["prohibited_actions"]]
        elif classification == "broker_orphan_no_mapping":
            evidence["recommended_action"] = "manual_orphan_review"
            evidence["prohibited_actions"] = ["live_status_request", *evidence["prohibited_actions"]]
        return evidence

    def _status_evidence_http_failure(self, status_code: int) -> str:
        if status_code == 429:
            return "rate_limited"
        if status_code in {401, 403}:
            return "auth_failed"
        return f"http_{status_code}"

    def _status_evidence_broker_error(self, errors: Any) -> str:
        text = " ".join(str(item) for item in errors) if isinstance(errors, list) else str(errors)
        lowered = text.lower()
        if "rate" in lowered:
            return "rate_limited"
        if "auth" in lowered or "key" in lowered or "permission" in lowered:
            return "auth_failed"
        return "broker_error"

    def _query_kraken_status_evidence(
        self,
        command_order_id: str,
        evidence: Dict[str, Any],
    ) -> Dict[str, Any]:
        endpoint = self._endpoints["kraken"]["status"]
        url = f"{self._endpoints['kraken']['rest']}{endpoint}"
        data = {"txid": command_order_id}
        headers = self._kraken_sign(endpoint, data)

        try:
            response = self._session.post(url, data=data, headers=headers, timeout=5.0)
            if response.status_code != 200:
                return self._status_evidence_with_result(
                    evidence,
                    status_raw=None,
                    failure_reason=self._status_evidence_http_failure(response.status_code),
                )
            result = response.json()
        except Exception:
            return self._status_evidence_with_result(
                evidence,
                status_raw=None,
                failure_reason="malformed_or_unavailable_response",
            )

        if not isinstance(result, dict):
            return self._status_evidence_with_result(
                evidence,
                status_raw=None,
                failure_reason="malformed_response",
            )
        if result.get("error"):
            return self._status_evidence_with_result(
                evidence,
                status_raw=None,
                failure_reason=self._status_evidence_broker_error(result.get("error")),
            )
        order_data = result.get("result", {}).get(command_order_id)
        if not isinstance(order_data, dict):
            return self._status_evidence_with_result(
                evidence,
                status_raw=None,
                failure_reason="missing_order_status",
            )
        return self._status_evidence_with_result(
            evidence,
            status_raw=order_data.get("status", "unknown"),
        )

    def _query_alpaca_status_evidence(
        self,
        command_order_id: str,
        evidence: Dict[str, Any],
    ) -> Dict[str, Any]:
        endpoint = self._endpoints["alpaca"]["status"].replace("{order_id}", command_order_id)
        url = f"{self._endpoints['alpaca']['rest']}{endpoint}"

        try:
            response = self._session.get(url, timeout=5.0)
            if response.status_code != 200:
                return self._status_evidence_with_result(
                    evidence,
                    status_raw=None,
                    failure_reason=self._status_evidence_http_failure(response.status_code),
                )
            result = response.json()
        except Exception:
            return self._status_evidence_with_result(
                evidence,
                status_raw=None,
                failure_reason="malformed_or_unavailable_response",
            )

        if not isinstance(result, dict):
            return self._status_evidence_with_result(
                evidence,
                status_raw=None,
                failure_reason="malformed_response",
            )
        return self._status_evidence_with_result(
            evidence,
            status_raw=result.get("status", "unknown"),
        )

    def _query_paper_status_evidence(
        self,
        client_order_id: str,
        evidence: Dict[str, Any],
    ) -> Dict[str, Any]:
        if self._paper_broker is None:
            return self._status_evidence_with_result(
                evidence,
                status_raw=None,
                failure_reason="paper_broker_unavailable",
            )

        for report in reversed(self._paper_broker.execution_reports):
            if getattr(report, "client_id", None) != client_order_id:
                continue
            return self._status_evidence_with_result(
                evidence,
                status_raw=self._map_paper_report_status_to_cache(getattr(report, "status", None)),
            )

        paper_order = self._paper_broker.open_orders.get(client_order_id)
        if paper_order is not None:
            return self._status_evidence_with_result(
                evidence,
                status_raw=self._map_paper_report_status_to_cache(getattr(paper_order, "status", None)),
            )

        return self._status_evidence_with_result(
            evidence,
            status_raw=None,
            failure_reason="paper_order_absent_not_terminal_proof",
        )

    def get_order_status_evidence(
        self,
        client_order_id: str,
        broker: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return guarded read-only status evidence without cache or terminal mutation."""
        broker_name = str(broker or self._mapping_broker()).lower()
        client_id = str(client_order_id or "").strip()
        evidence = self._status_evidence_base(client_order_id=client_id, broker=broker_name)

        if not client_id:
            return self._status_evidence_failure(
                evidence,
                classification="broker_orphan_no_mapping",
                failure_reason="missing_client_order_id",
            )

        mapping = self._get_order_id_mapping_read_only(client_id, broker_name)
        if mapping is None:
            return self._status_evidence_failure(
                evidence,
                classification="mapping_missing_or_unsafe",
                failure_reason="missing_mapping",
            )

        evidence["command_id_namespace"] = mapping.command_id_namespace
        evidence["command_order_id"] = mapping.command_order_id
        expected_namespace = self._command_namespace_for_broker(broker_name)
        if not expected_namespace or mapping.command_id_namespace != expected_namespace or not mapping.command_order_id:
            return self._status_evidence_failure(
                evidence,
                classification="mapping_missing_or_unsafe",
                failure_reason="unsafe_command_namespace",
            )
        if not mapping.durable:
            return self._status_evidence_failure(
                evidence,
                classification="mapping_missing_or_unsafe",
                failure_reason="non_durable_mapping",
            )
        if mapping.is_terminal:
            evidence["status_raw"] = mapping.status
            return self._status_evidence_failure(
                evidence,
                classification="mapping_missing_or_unsafe",
                failure_reason="terminal_mapping",
            )

        if broker_name == "kraken":
            return self._query_kraken_status_evidence(mapping.command_order_id, evidence)
        if broker_name == "alpaca":
            return self._query_alpaca_status_evidence(mapping.command_order_id, evidence)
        if broker_name == "paper":
            return self._query_paper_status_evidence(client_id, evidence)
        return self._status_evidence_failure(
            evidence,
            classification="mapping_missing_or_unsafe",
            failure_reason="unsupported_broker",
        )

    def mark_terminal_from_status_evidence(self, evidence: Dict[str, Any]) -> Dict[str, Any]:
        """Apply explicit terminal status evidence to mapping state only."""
        if not isinstance(evidence, dict):
            return {
                "applied": False,
                "reason": "invalid_evidence",
                "client_order_id": "",
                "terminal_status": None,
                "terminal_reason": None,
                "mutation_scope": [],
            }

        client_id = str(evidence.get("client_order_id") or "").strip()
        broker_name = str(evidence.get("broker") or self._mapping_broker()).lower()
        terminal_status = str(evidence.get("status_raw") or "").strip().lower()
        result = {
            "applied": False,
            "reason": "not_applied",
            "client_order_id": client_id,
            "terminal_status": terminal_status or None,
            "terminal_reason": None,
            "mutation_scope": [],
        }

        if evidence.get("status_classification") != "terminal_observed" or evidence.get("terminal_observed") is not True:
            result["reason"] = "non_terminal_evidence"
            return result
        if not client_id:
            result["reason"] = "missing_client_order_id"
            return result
        if terminal_status not in _STATUS_EVIDENCE_TERMINAL:
            result["reason"] = "unsupported_terminal_status"
            return result

        mapping = self._get_order_id_mapping_read_only(client_id, broker_name)
        if mapping is None:
            result["reason"] = "missing_mapping"
            return result
        if not mapping.durable or self._state_store is None:
            result["reason"] = "non_durable_mapping"
            return result

        expected_namespace = self._command_namespace_for_broker(broker_name)
        evidence_namespace = str(evidence.get("command_id_namespace") or "")
        evidence_command_id = str(evidence.get("command_order_id") or "")
        if (
            not expected_namespace
            or mapping.command_id_namespace != expected_namespace
            or evidence_namespace != mapping.command_id_namespace
            or evidence_command_id != mapping.command_order_id
        ):
            result["reason"] = "unsafe_command_namespace"
            return result

        terminal_reason = f"status_evidence_{terminal_status}"
        result["terminal_reason"] = terminal_reason
        if mapping.is_terminal:
            if mapping.status == terminal_status:
                result["reason"] = "already_terminal"
                return result
            result["reason"] = "terminal_status_conflict"
            return result

        if not self._state_store.mark_order_id_mapping_terminal(
            client_id,
            broker_name,
            status=terminal_status,
            terminal_reason=terminal_reason,
        ):
            result["reason"] = "state_store_update_failed"
            return result

        active_mapping = self._active_order_id_mappings.get((broker_name, client_id))
        mutation_scope = ["state_store_order_id_mapping"]
        if active_mapping is not None:
            active_mapping.status = terminal_status
            active_mapping.is_terminal = True
            active_mapping.terminal_reason = terminal_reason
            active_mapping.durable = True
            mutation_scope.append("active_order_id_mapping")

        result["applied"] = True
        result["reason"] = "terminal_mapping_updated"
        result["mutation_scope"] = mutation_scope
        self._record_terminal_mapping_proof(evidence, result, mapping)
        return result

    def _record_terminal_mapping_proof(
        self,
        evidence: Dict[str, Any],
        result: Dict[str, Any],
        mapping: ActiveOrderIdMapping,
    ) -> None:
        timestamp_ns = now_ns()
        proof = {
            "event_type": "terminal_mapping_proof",
            "proof_type": "terminal_mapping_proof",
            "client_order_id": mapping.client_order_id,
            "broker": mapping.broker,
            "venue": evidence.get("venue") or mapping.broker,
            "command_id_namespace": mapping.command_id_namespace,
            "command_order_id": mapping.command_order_id,
            "terminal_status": result.get("terminal_status"),
            "terminal_reason": result.get("terminal_reason"),
            "status_evidence_classification": evidence.get("status_classification"),
            "mutation_applied": bool(result.get("applied")),
            "mutation_scope": "mapping_only",
            "mapping_mutation_scope": list(result.get("mutation_scope") or []),
            "pending_cleanup_performed": False,
            "exposure_release_performed": False,
            "reservation_release_performed": False,
            "reservation_candidate_delta": build_passive_reservation_candidate_delta(
                lifecycle_phase="terminal_mapping_proof",
                client_order_id=mapping.client_order_id,
                decision_uuid=None,
                symbol=mapping.symbol,
                side=mapping.side,
                terminal_state=result.get("terminal_status"),
                terminal_reason=result.get("terminal_reason"),
                status_source="mark_terminal_from_status_evidence",
                idempotency_key=f"{mapping.client_order_id}:terminal_mapping_proof:{result.get('terminal_status')}",
            ),
            "reservation_candidate_authoritative": False,
            "orphan_repair_performed": False,
            "cancel_command_performed": False,
            "submit_command_performed": False,
            "broker_command_performed": False,
            "command_authority": False,
            "repair_authority": False,
            "source": "mark_terminal_from_status_evidence",
            "timestamp_ns": timestamp_ns,
        }
        self._terminal_mapping_proofs.append(proof)
        self._terminal_mapping_proofs = self._terminal_mapping_proofs[-100:]
        self._emit_terminal_mapping_proof_event(proof, timestamp_ns)

    def _emit_terminal_mapping_proof_event(self, proof: Dict[str, Any], timestamp_ns: int) -> None:
        if self._telemetry_store is None:
            return
        try:
            event = EventEnvelope(
                decision_uuid=None,
                parent_uuid=None,
                event_type=EventType.AUDIT_EVENT,
                source_module="order_router",
                exchange_ts_ns=timestamp_ns,
                receive_ts_ns=timestamp_ns,
                decision_ts_ns=0,
                sequence=0,
                payload=dict(proof),
                schema_version=1,
            )
            self._telemetry_store.record_event(event)
        except Exception as exc:
            logger.debug("Terminal mapping proof telemetry append skipped: %s", exc)

    def get_terminal_mapping_proofs(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Return passive terminal mapping proof facts for audit/status surfaces."""
        proofs = self._terminal_mapping_proofs if limit is None else self._terminal_mapping_proofs[-int(limit):]
        return [dict(proof) for proof in proofs]

    def get_order_id_mapping_fact(self, client_order_id: str) -> Optional[Dict[str, Any]]:
        """Return the durable mapping fact for truth/reconcile hydration."""
        mapping = self._get_active_order_id_mapping(client_order_id, self._mapping_broker())
        if mapping is None:
            return None
        return self._mapping_to_store_record(mapping)

    def _get_order_id_mapping_by_namespace(
        self,
        broker: str,
        id_namespace: str,
        order_id: str,
    ) -> Optional[ActiveOrderIdMapping]:
        if not order_id:
            return None
        if self._state_store is not None:
            record = self._state_store.get_order_id_mapping_by_namespace(
                broker,
                id_namespace,
                order_id,
            )
            if record is not None:
                return self._mapping_from_record(record)

        for mapping_broker, client_order_id in list(self._active_order_id_mappings.keys()):
            if mapping_broker != broker:
                continue
            mapping = self._active_order_id_mappings[(mapping_broker, client_order_id)]
            if str(getattr(mapping, id_namespace, "") or "") == str(order_id):
                return mapping
            if id_namespace == "command_order_id" and mapping.command_order_id == str(order_id):
                return mapping
        return None

    def _normalized_open_order_fact(
        self,
        *,
        broker: str,
        raw_order_id: str,
        order_id_namespace: str,
        symbol: str,
        side: str,
        order_type: str = "",
        quantity: Any = 0,
        remaining_quantity: Any = None,
        limit_price: Any = None,
        status: str = "open",
        created_at_ns: int = 0,
        client_order_id: Optional[str] = None,
        paper_internal_order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        mapping = None
        if client_order_id:
            mapping = self._get_active_order_id_mapping(client_order_id, broker)
        if mapping is None and raw_order_id:
            mapping = self._get_order_id_mapping_by_namespace(
                broker,
                order_id_namespace,
                raw_order_id,
            )

        mapping_status = "broker_orphan"
        resolved_client_id = client_order_id
        venue_order_id = None
        broker_order_id = paper_internal_order_id
        exchange_txid = None
        command_id_namespace = None
        command_order_id = None
        is_terminal_mapping = False
        terminal_reason = None

        if mapping is not None:
            resolved_client_id = mapping.client_order_id
            venue_order_id = mapping.venue_order_id
            broker_order_id = mapping.broker_order_id
            exchange_txid = mapping.exchange_txid
            command_id_namespace = mapping.command_id_namespace
            command_order_id = mapping.command_order_id
            is_terminal_mapping = mapping.is_terminal
            terminal_reason = mapping.terminal_reason
            mapping_status = "terminal_local_broker_open" if mapping.is_terminal else "mapped"
        elif broker == "paper" and client_order_id:
            command_id_namespace = "client_order_id"
            command_order_id = client_order_id
            mapping_status = "mapped"

        if broker == "kraken":
            exchange_txid = exchange_txid or raw_order_id
            venue_order_id = venue_order_id or raw_order_id
        elif broker == "alpaca":
            venue_order_id = venue_order_id or raw_order_id
            broker_order_id = broker_order_id or raw_order_id
        elif broker == "paper":
            venue_order_id = venue_order_id or paper_internal_order_id
            broker_order_id = broker_order_id or paper_internal_order_id

        return {
            "broker": broker,
            "order_id": str(raw_order_id),
            "order_id_namespace": order_id_namespace,
            "client_order_id": resolved_client_id,
            "venue_order_id": venue_order_id,
            "broker_order_id": broker_order_id,
            "exchange_txid": exchange_txid,
            "command_id_namespace": command_id_namespace,
            "command_order_id": command_order_id,
            "mapping_status": mapping_status,
            "is_terminal_mapping": is_terminal_mapping,
            "terminal_reason": terminal_reason,
            "symbol": symbol,
            "side": side,
            "order_type": order_type,
            "quantity": quantity,
            "remaining_quantity": remaining_quantity,
            "limit_price": limit_price,
            "status": status,
            "created_at_ns": created_at_ns,
        }

    def _record_order_lifecycle_telemetry(
        self,
        order: OrderRequest,
        *,
        lifecycle_source: str,
        lifecycle_phase: str,
        event_ts_ns: int,
        submit_seen: bool = True,
        ack_seen: Optional[bool] = None,
        reject_seen: Optional[bool] = None,
        partial_fill_seen: Optional[bool] = None,
        full_fill_seen: Optional[bool] = None,
        cancel_seen: Optional[bool] = None,
        terminal_state: Optional[str] = None,
        terminal_reason: Optional[str] = None,
        venue_order_id: Optional[str] = None,
        broker_order_id: Optional[str] = None,
        exchange_txid: Optional[str] = None,
        venue_fill_id: Optional[str] = None,
        original_qty: Optional[Any] = None,
        fill_delta_qty: Optional[Any] = None,
        cumulative_filled_qty: Optional[Any] = None,
        remaining_qty: Optional[Any] = None,
        avg_fill_price: Optional[Any] = None,
        cumulative_fee: Optional[Any] = None,
        is_terminal: Optional[bool] = None,
        status_source: Optional[str] = None,
        id_mapping_source: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> None:
        """Emit passive lifecycle telemetry without creating router authority."""
        if not self._fill_recorder:
            return
        if not order.decision_uuid:
            logger.warning("Skipping lifecycle telemetry for order %s: missing decision_uuid", order.id)
            return

        lifecycle_context = self._build_order_lifecycle_replay_context(
            order,
            lifecycle_source=lifecycle_source,
            lifecycle_phase=lifecycle_phase,
            submit_seen=submit_seen,
            ack_seen=ack_seen,
            reject_seen=reject_seen,
            partial_fill_seen=partial_fill_seen,
            full_fill_seen=full_fill_seen,
            cancel_seen=cancel_seen,
            terminal_state=terminal_state,
            terminal_reason=terminal_reason,
            venue_order_id=venue_order_id,
            broker_order_id=broker_order_id,
            exchange_txid=exchange_txid,
            venue_fill_id=venue_fill_id,
            original_qty=original_qty,
            fill_delta_qty=fill_delta_qty,
            cumulative_filled_qty=cumulative_filled_qty,
            remaining_qty=remaining_qty,
            avg_fill_price=avg_fill_price,
            cumulative_fee=cumulative_fee,
            is_terminal=is_terminal,
            status_source=status_source,
            id_mapping_source=id_mapping_source,
            idempotency_key=idempotency_key,
        )
        metadata = self._metadata_with_lifecycle_context(order, lifecycle_context)
        canonical_state = self._oms_state_for_lifecycle_phase(lifecycle_phase)
        metadata["canonical_order_state"] = canonical_state
        metadata["oms_order_state"] = canonical_state
        self._record_oms_state(canonical_state)
        self._fill_recorder.record_order_lifecycle_event(
            lifecycle_phase=lifecycle_phase,
            client_order_id=order.id,
            decision_uuid=order.decision_uuid,
            event_ts_ns=int(event_ts_ns),
            lifecycle_source=lifecycle_source,
            symbol=order.symbol,
            side=order.side,
            order_type=order.order_type,
            limit_price=order.limit_price,
            submit_seen=submit_seen,
            ack_seen=ack_seen,
            reject_seen=reject_seen,
            partial_fill_seen=partial_fill_seen,
            full_fill_seen=full_fill_seen,
            cancel_seen=cancel_seen,
            terminal_state=terminal_state,
            terminal_reason=terminal_reason,
            venue_order_id=venue_order_id,
            broker_order_id=broker_order_id,
            exchange_txid=exchange_txid,
            venue_fill_id=venue_fill_id,
            original_qty=original_qty,
            fill_delta_qty=fill_delta_qty,
            cumulative_filled_qty=cumulative_filled_qty,
            remaining_qty=remaining_qty,
            avg_fill_price=avg_fill_price,
            cumulative_fee=cumulative_fee,
            is_terminal=is_terminal,
            status_source=status_source,
            id_mapping_source=id_mapping_source,
            idempotency_key=idempotency_key,
            metadata=metadata,
        )

    # ============================================
    # WEBSOCKET HEALTH MONITORING
    # ============================================

    def update_websocket_health(self, ping_ns: int, pong_ns: int):
        with self._lock:
            self._last_websocket_ping_ns = ping_ns
            self._last_websocket_pong_ns = pong_ns
            self._websocket_connected = (pong_ns - ping_ns) < (self.latency_threshold_ms * 1_000_000)

    def set_market_data_latency_source(self, source: str) -> None:
        normalized = str(source or "websocket").strip().lower()
        if normalized not in {"websocket", "rest_polling"}:
            raise ValueError(f"unsupported_market_data_latency_source:{source}")
        with self._lock:
            self._market_data_latency_source = normalized

    def update_rest_market_data_latency(
        self,
        *,
        request_start_ns: int,
        response_received_ns: int,
        exchange: str,
        provider_id: str,
        symbol: str,
        feed_type: str,
    ) -> None:
        with self._lock:
            self._last_rest_market_data_request_ns = int(request_start_ns or 0)
            self._last_rest_market_data_response_ns = int(response_received_ns or 0)
            if self._last_rest_market_data_request_ns > 0 and self._last_rest_market_data_response_ns > 0:
                self._last_rest_market_data_latency_ms = (
                    self._last_rest_market_data_response_ns - self._last_rest_market_data_request_ns
                ) / 1_000_000.0
            else:
                self._last_rest_market_data_latency_ms = float("inf")
            self._last_rest_market_data_exchange = str(exchange or "")
            self._last_rest_market_data_provider_id = str(provider_id or "")
            self._last_rest_market_data_symbol = str(symbol or "")
            self._last_rest_market_data_feed_type = str(feed_type or "")

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

    def get_rest_market_data_rtt_ms(self) -> float:
        with self._lock:
            if self._last_rest_market_data_request_ns == 0 or self._last_rest_market_data_response_ns == 0:
                return float("inf")
            return self._last_rest_market_data_latency_ms

    def get_latency_measurement(self) -> Dict[str, Any]:
        with self._lock:
            if self._market_data_latency_source == "rest_polling":
                rest_latency_ms = (
                    self._last_rest_market_data_latency_ms
                    if self._last_rest_market_data_request_ns > 0
                    and self._last_rest_market_data_response_ns > 0
                    else float("inf")
                )
                return {
                    "latency_ms": rest_latency_ms,
                    "source": "market_data.rest_polling_rtt",
                    "request_start_ns": self._last_rest_market_data_request_ns,
                    "response_received_ns": self._last_rest_market_data_response_ns,
                    "exchange": self._last_rest_market_data_exchange,
                    "provider_id": self._last_rest_market_data_provider_id,
                    "symbol": self._last_rest_market_data_symbol,
                    "feed_type": self._last_rest_market_data_feed_type,
                }
            websocket_rtt_ms = (
                (self._last_websocket_pong_ns - self._last_websocket_ping_ns) / 1_000_000
                if self._last_websocket_ping_ns > 0 and self._last_websocket_pong_ns > 0
                else float("inf")
            )
            return {
                "latency_ms": websocket_rtt_ms,
                "source": "order_router.websocket_rtt",
                "ping_ns": self._last_websocket_ping_ns,
                "pong_ns": self._last_websocket_pong_ns,
            }

    def measure_latency(self) -> float:
        measurement = self.get_latency_measurement()
        try:
            return float(measurement.get("latency_ms"))
        except (TypeError, ValueError):
            return float("inf")

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

    def fetch_normalized_open_orders(self) -> List[Dict[str, Any]]:
        """Fetch broker open orders with explicit ID namespaces for reconcile."""
        if self.paper_mode:
            if self._paper_broker is None:
                return []
            facts = []
            for client_id, order in self._paper_broker.open_orders.items():
                facts.append(
                    self._normalized_open_order_fact(
                        broker="paper",
                        raw_order_id=str(order.order_id),
                        order_id_namespace="paper_broker_internal_order_id",
                        symbol=order.symbol,
                        side=order.side.value,
                        order_type=order.order_type.value,
                        quantity=str(order.quantity),
                        remaining_quantity=str(order.remaining_quantity),
                        limit_price=str(order.limit_price) if order.limit_price else None,
                        status=order.status.value,
                        created_at_ns=order.created_at_ns,
                        client_order_id=client_id,
                        paper_internal_order_id=str(order.order_id),
                    )
                )
            return facts

        if self.primary_exchange == "kraken":
            result = self._call_kraken_private(self._endpoints["kraken"]["open_orders"])
            if not result:
                return []
            facts = []
            open_data = result.get("open", {})
            for order_id, order_info in open_data.items():
                descr = order_info.get("descr", {})
                quantity = _Decimal(str(order_info.get("vol", 0)))
                filled_quantity = _Decimal(str(order_info.get("vol_exec", 0)))
                remaining_quantity = max(_Decimal("0"), quantity - filled_quantity)
                facts.append(
                    self._normalized_open_order_fact(
                        broker="kraken",
                        raw_order_id=str(order_id),
                        order_id_namespace="exchange_txid",
                        symbol=descr.get("pair", ""),
                        side=descr.get("type", ""),
                        order_type=descr.get("ordertype", ""),
                        quantity=str(quantity),
                        remaining_quantity=str(remaining_quantity),
                        limit_price=str(descr.get("price")) if descr.get("price") else None,
                        status=order_info.get("status", "open"),
                        created_at_ns=(
                            int(order_info.get("opentm", 0)) * 1_000_000_000
                            if order_info.get("opentm")
                            else 0
                        ),
                    )
                )
            return facts

        if self.primary_exchange == "alpaca":
            endpoint = self._endpoints["alpaca"]["open_orders"]
            url = f"{self._endpoints['alpaca']['rest']}{endpoint}"
            try:
                response = self._session.get(url, timeout=5.0)
                if response.status_code != 200:
                    return []
                facts = []
                for order in response.json():
                    status = str(order.get("status", "open"))
                    if status in {"filled", "canceled", "cancelled", "expired", "rejected"}:
                        continue
                    order_id = str(order.get("id", ""))
                    if not order_id:
                        continue
                    quantity = _Decimal(str(order.get("qty", 0)))
                    filled_quantity = _Decimal(str(order.get("filled_qty", 0) or 0))
                    remaining_quantity = max(_Decimal("0"), quantity - filled_quantity)
                    facts.append(
                        self._normalized_open_order_fact(
                            broker="alpaca",
                            raw_order_id=order_id,
                            order_id_namespace="venue_order_id",
                            symbol=order.get("symbol", ""),
                            side=order.get("side", ""),
                            order_type=order.get("type", ""),
                            quantity=str(quantity),
                            remaining_quantity=str(remaining_quantity),
                            limit_price=str(order.get("limit_price")) if order.get("limit_price") else None,
                            status=status,
                            created_at_ns=0,
                        )
                    )
                return facts
            except Exception as e:
                logger.error("Failed to fetch Alpaca normalized open orders: %s", e)
                return []

        return []

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
            "open_orders": self.fetch_normalized_open_orders(),
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

    def _paper_lifecycle_idempotency_key(
        self,
        order: OrderRequest,
        *,
        lifecycle_phase: str,
        broker_order_id: Optional[str],
        event_ts_ns: int,
        source_event_id: str,
    ) -> str:
        venue_or_broker_id = broker_order_id or "unknown_broker_order_id"
        return (
            f"{order.decision_uuid}:{order.id}:{lifecycle_phase}:"
            f"{venue_or_broker_id}:{int(event_ts_ns)}:{source_event_id}"
        )

    def _record_paper_report_lifecycle(
        self,
        order: OrderRequest,
        report: Any,
        *,
        source_event_id: str,
    ) -> None:
        """Record passive lifecycle facts already emitted by PaperBroker."""
        report_status = getattr(report, "status", None)
        event_ts_ns = int(getattr(report, "timestamp_ns", 0) or now_ns())
        broker_order_id = str(getattr(report, "order_id", "")) or None
        paper_order = self._paper_broker.open_orders.get(order.id) if self._paper_broker else None

        original_qty = order.quantity
        fill_delta_qty = getattr(report, "filled_quantity", None)
        fill_price = getattr(report, "fill_price", None)
        report_fee = getattr(report, "fee", None)

        if report_status == _pb_enums.OrderStatus.ACKNOWLEDGED:
            remaining_qty = paper_order.remaining_quantity if paper_order is not None else original_qty
            idempotency_key = self._paper_lifecycle_idempotency_key(
                order,
                lifecycle_phase="order_acknowledged",
                broker_order_id=broker_order_id,
                event_ts_ns=event_ts_ns,
                source_event_id=source_event_id,
            )
            self._record_order_lifecycle_telemetry(
                order,
                lifecycle_source="order_router.paper_report",
                lifecycle_phase="order_acknowledged",
                event_ts_ns=event_ts_ns,
                ack_seen=True,
                venue_order_id=broker_order_id,
                broker_order_id=broker_order_id,
                original_qty=original_qty,
                cumulative_filled_qty=_Decimal("0"),
                remaining_qty=remaining_qty,
                cumulative_fee=_Decimal("0"),
                is_terminal=False,
                status_source="paper_broker.execution_report",
                id_mapping_source="paper_broker.execution_report",
                idempotency_key=idempotency_key,
            )
            self._record_reservation_ack_open(
                order,
                ack_source="paper_broker.execution_report",
                source_event_id=idempotency_key,
            )
            return

        if report_status == _pb_enums.OrderStatus.PARTIAL_FILL:
            cumulative_filled = (
                paper_order.filled_quantity
                if paper_order is not None
                else (fill_delta_qty or _Decimal("0"))
            )
            remaining_qty = (
                paper_order.remaining_quantity
                if paper_order is not None
                else max(_Decimal("0"), _Decimal(str(original_qty)) - _Decimal(str(cumulative_filled)))
            )
            avg_fill_price = paper_order.average_fill_price if paper_order is not None else fill_price
            cumulative_fee = paper_order.fee_paid if paper_order is not None else report_fee
            idempotency_key = self._paper_lifecycle_idempotency_key(
                order,
                lifecycle_phase="order_partially_filled",
                broker_order_id=broker_order_id,
                event_ts_ns=event_ts_ns,
                source_event_id=source_event_id,
            )
            self._record_order_lifecycle_telemetry(
                order,
                lifecycle_source="order_router.paper_report",
                lifecycle_phase="order_partially_filled",
                event_ts_ns=event_ts_ns,
                partial_fill_seen=True,
                venue_order_id=broker_order_id,
                broker_order_id=broker_order_id,
                venue_fill_id=source_event_id,
                original_qty=original_qty,
                fill_delta_qty=fill_delta_qty,
                cumulative_filled_qty=cumulative_filled,
                remaining_qty=remaining_qty,
                avg_fill_price=avg_fill_price,
                cumulative_fee=cumulative_fee,
                is_terminal=False,
                status_source="paper_broker.execution_report",
                id_mapping_source="paper_broker.execution_report",
                idempotency_key=idempotency_key,
            )
            self._record_reservation_partial_fill(
                order,
                fill_idempotency_key=idempotency_key,
                cumulative_filled_qty=cumulative_filled,
                fill_delta_qty=fill_delta_qty,
                status_source="paper_broker.execution_report",
                source_event_id=source_event_id,
            )
            return

        if report_status == _pb_enums.OrderStatus.FULLY_FILLED:
            idempotency_key = self._paper_lifecycle_idempotency_key(
                order,
                lifecycle_phase="order_fully_filled",
                broker_order_id=broker_order_id,
                event_ts_ns=event_ts_ns,
                source_event_id=source_event_id,
            )
            self._record_reservation_full_fill(
                order,
                release_idempotency_key=f"{idempotency_key}:release",
                cumulative_filled_qty=original_qty,
                fill_delta_qty=fill_delta_qty,
                status_source="paper_broker.execution_report",
                terminal_source="paper_broker.execution_report",
                source_event_id=source_event_id,
            )
            return

        if report_status == _pb_enums.OrderStatus.CANCELLED:
            remaining_qty = paper_order.remaining_quantity if paper_order is not None else None
            idempotency_key = self._paper_lifecycle_idempotency_key(
                order,
                lifecycle_phase="order_canceled",
                broker_order_id=broker_order_id,
                event_ts_ns=event_ts_ns,
                source_event_id=source_event_id,
            )
            self._record_order_lifecycle_telemetry(
                order,
                lifecycle_source="order_router.paper_report",
                lifecycle_phase="order_canceled",
                event_ts_ns=event_ts_ns,
                cancel_seen=True,
                terminal_state="canceled",
                terminal_reason="paper_broker_cancelled",
                venue_order_id=broker_order_id,
                broker_order_id=broker_order_id,
                original_qty=original_qty,
                remaining_qty=remaining_qty,
                is_terminal=True,
                status_source="paper_broker.execution_report",
                id_mapping_source="paper_broker.execution_report",
                idempotency_key=idempotency_key,
            )
            self._record_reservation_terminal_non_fill(
                order,
                release_idempotency_key=f"{idempotency_key}:release",
                terminal_status="cancelled",
                terminal_source="paper_broker.execution_report",
                terminal_reason="paper_broker_cancelled",
                source_event_id=source_event_id,
            )
            return

        if report_status == _pb_enums.OrderStatus.REJECTED:
            idempotency_key = self._paper_lifecycle_idempotency_key(
                order,
                lifecycle_phase="order_rejected",
                broker_order_id=broker_order_id,
                event_ts_ns=event_ts_ns,
                source_event_id=source_event_id,
            )
            self._record_order_lifecycle_telemetry(
                order,
                lifecycle_source="order_router.paper_report",
                lifecycle_phase="order_rejected",
                event_ts_ns=event_ts_ns,
                reject_seen=True,
                terminal_state="rejected",
                terminal_reason="paper_broker_rejected",
                venue_order_id=broker_order_id,
                broker_order_id=broker_order_id,
                original_qty=original_qty,
                remaining_qty=_Decimal("0"),
                is_terminal=True,
                status_source="paper_broker.execution_report",
                id_mapping_source="paper_broker.execution_report",
                idempotency_key=idempotency_key,
            )
            self._record_reservation_terminal_non_fill(
                order,
                release_idempotency_key=f"{idempotency_key}:release",
                terminal_status="rejected",
                terminal_source="paper_broker.execution_report",
                terminal_reason="paper_broker_rejected",
                source_event_id=source_event_id,
            )
            return

        if report_status == _pb_enums.OrderStatus.EXPIRED:
            idempotency_key = self._paper_lifecycle_idempotency_key(
                order,
                lifecycle_phase="order_expired",
                broker_order_id=broker_order_id,
                event_ts_ns=event_ts_ns,
                source_event_id=source_event_id,
            )
            self._record_order_lifecycle_telemetry(
                order,
                lifecycle_source="order_router.paper_report",
                lifecycle_phase="order_expired",
                event_ts_ns=event_ts_ns,
                terminal_state="expired",
                terminal_reason="paper_broker_expired",
                venue_order_id=broker_order_id,
                broker_order_id=broker_order_id,
                original_qty=original_qty,
                is_terminal=True,
                status_source="paper_broker.execution_report",
                id_mapping_source="paper_broker.execution_report",
                idempotency_key=idempotency_key,
            )
            self._record_reservation_terminal_non_fill(
                order,
                release_idempotency_key=f"{idempotency_key}:release",
                terminal_status="expired",
                terminal_source="paper_broker.execution_report",
                terminal_reason="paper_broker_expired",
                source_event_id=source_event_id,
            )

    def _sync_paper_reports(self) -> None:
        """Synchronize paper broker execution reports into router status cache."""
        if self._paper_broker is None:
            return

        reports = self._paper_broker.execution_reports
        if self._paper_reports_index >= len(reports):
            return

        new_reports = reports[self._paper_reports_index:]
        for offset, report in enumerate(new_reports):
            client_id = report.client_id
            mapped_status = self._map_paper_report_status_to_cache(report.status)
            order = self._pending_orders.get(client_id)
            source_event_id = f"paper_report_{self._paper_reports_index + offset}"

            filled_qty = report.filled_quantity or _Decimal("0")
            filled_price = report.fill_price if report.fill_price is not None else _Decimal("0")
            remaining_qty = _Decimal("0")
            if client_id in self._paper_broker.open_orders:
                remaining_qty = self._paper_broker.open_orders[client_id].remaining_quantity

            if order is not None:
                self._record_paper_report_lifecycle(
                    order,
                    report,
                    source_event_id=source_event_id,
                )

            self._order_status_cache[client_id] = OrderStatus(
                order_id=client_id,
                status=mapped_status,
                filled_quantity=filled_qty,
                filled_price=filled_price,
                remaining_quantity=remaining_qty,
                timestamp_ns=int(report.timestamp_ns),
            )

            if mapped_status == "filled":
                self._mark_active_order_mapping_terminal(
                    client_id,
                    status="filled",
                    terminal_reason="paper_broker_filled",
                )
                self._pending_orders.pop(client_id, None)
            elif mapped_status in {"cancelled", "expired", "rejected"}:
                self._mark_active_order_mapping_terminal(
                    client_id,
                    status=mapped_status,
                    terminal_reason=f"paper_broker_{mapped_status}",
                )
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
            if self._order_requests_gateway_route(order):
                if not self._should_use_external_paper_gateway():
                    logger.error(
                        "External paper broker requested but gateway route is unavailable: execution_broker=%s primary_exchange=%s",
                        self.execution_broker,
                        self.primary_exchange,
                    )
                    self._record_rejection_telemetry(order, "external_paper_gateway_unavailable")
                    return None
                self._submit_order_gateway(order)
                return None
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

        paper_order = self._paper_broker.submit_order(
            symbol=order.symbol,
            side=pb_side,
            order_type=pb_order_type,
            quantity=_Decimal(str(order.quantity)),
            price=submit_price,
            ts_ns=ts_ns,
            client_id=order.id,
        )
        paper_order_id = (
            paper_order.get("order_id")
            if isinstance(paper_order, dict)
            else getattr(paper_order, "order_id", None)
        )
        self._register_active_order_id_mapping(
            order,
            broker="paper",
            venue_order_id=str(paper_order_id) if paper_order_id is not None else None,
            broker_order_id=str(paper_order_id) if paper_order_id is not None else None,
            exchange_txid=None,
            id_mapping_source="paper_broker.submit_order",
            ack_ts_ns=ts_ns,
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
        paper_venue_order_id = str(fill_report.order_id) if fill_report is not None else None
        self._record_fill_telemetry(
            order,
            fill,
            venue_fill_id=order.id,
            venue_order_id=paper_venue_order_id,
            broker_order_id=paper_venue_order_id,
            id_mapping_source="paper_broker.execution_report",
        )

        return fill

    def get_gateway_response(self, client_order_id: str) -> Optional[BrokerGatewayResponse]:
        """Return the normalized external broker-paper response for a routed client order."""
        return self._gateway_responses_by_client_order_id.get(client_order_id)

    def get_gateway_reconciliation(self, client_order_id: str) -> Optional[Dict[str, Any]]:
        """Return read-only post-ack reconciliation evidence for a routed client order."""
        evidence = self._gateway_reconciliation_by_client_order_id.get(client_order_id)
        return dict(evidence) if evidence is not None else None

    def get_oms_shutdown_accounting(self) -> Dict[str, Any]:
        """Return OMS lifecycle accounting without issuing broker mutation."""
        mapping_rows: List[Dict[str, Any]] = []
        table_counts: Dict[str, int] = {}
        if self._state_store is not None:
            try:
                mapping_rows = self._state_store.list_order_id_mappings()
            except Exception:
                mapping_rows = []
            for table in (
                "orders",
                "fills",
                "broker_fill_ledger",
                "order_id_mappings",
                "reservation_ledger",
                "reservation_fill_progress",
                "reservation_release_tombstones",
            ):
                counter = getattr(self._state_store, "count_table_rows", None)
                if callable(counter):
                    table_counts[table] = counter(table)

        request_counts = self._broker_gateway_request_counts()
        latest_reconciliation = (
            next(reversed(self._gateway_reconciliation_by_client_order_id.values()))
            if self._gateway_reconciliation_by_client_order_id
            else {}
        )
        shutdown_reconciliation = dict(self._shutdown_reconciliation or {})
        if shutdown_reconciliation:
            latest_reconciliation = shutdown_reconciliation
        post_events = [
            event for event in self._broker_boundary_events
            if str(event.get("request_method") or "").upper() == "POST"
        ]
        cancel_events = [
            event for event in self._broker_boundary_events
            if str(event.get("request_method") or "").upper() == "DELETE"
        ]
        order_post_attempted = sum(1 for event in post_events if event.get("broker_post_attempted") is True)
        order_post_authorized = sum(1 for event in post_events if event.get("broker_post_authorized") is True)
        order_post_acknowledged = sum(
            1 for event in post_events
            if event.get("broker_boundary_result") == "BROKER_POST_ACKNOWLEDGED"
        )
        cancel_attempted = len(cancel_events)
        cancel_authorized = sum(1 for event in cancel_events if event.get("broker_post_authorized") is True)
        cancel_acknowledged = sum(
            1 for event in cancel_events
            if event.get("broker_boundary_result") == "BROKER_CANCEL_ACKNOWLEDGED"
        )
        terminal_statuses = {"filled", "canceled", "cancelled", "rejected", "expired", "reconciliation_conflict"}
        terminal_orders = sum(1 for row in mapping_rows if str(row.get("status") or "").lower() in terminal_statuses)
        local_open_orders = sum(1 for row in mapping_rows if self._is_local_open_order_mapping(row))
        broker_confirmed_open_orders = (
            int(shutdown_reconciliation.get("broker_confirmed_open_orders", 0) or 0)
            if shutdown_reconciliation.get("performed")
            else local_open_orders
        )
        reconciliation_conflicts = max(
            int(self._oms_lifecycle_counts.get("reconciliation_conflicts", 0) or 0),
            int(shutdown_reconciliation.get("reconciliation_conflict_count", 0) or 0),
        )
        fill_hydration_missing_count = max(
            int(shutdown_reconciliation.get("fill_hydration_missing_count", 0) or 0),
            sum(
                1
                for result in self._fill_hydration_results
                if OmsReasonCode.FILL_LEDGER_UNAVAILABLE.value in result.get("reason_codes", ())
            ),
        )
        fill_hydration_attempted_count = max(
            int(shutdown_reconciliation.get("fill_hydration_attempted_count", 0) or 0),
            len(self._fill_hydration_results),
        )
        fill_hydration_count = max(
            int(shutdown_reconciliation.get("fill_hydration_count", 0) or 0),
            sum(1 for result in self._fill_hydration_results if result.get("inserted") is True),
        )
        fill_hydration_partial_count = max(
            int(shutdown_reconciliation.get("fill_hydration_partial_count", 0) or 0),
            sum(1 for result in self._fill_hydration_results if result.get("status") == "PARTIAL"),
        )
        fill_hydration_conflict_count = max(
            int(shutdown_reconciliation.get("fill_hydration_conflict_count", 0) or 0),
            sum(1 for result in self._fill_hydration_results if result.get("status") == "CONFLICT"),
        )
        tca_records_count = max(
            int(shutdown_reconciliation.get("tca_records_count", 0) or 0),
            sum(1 for result in self._fill_hydration_results if result.get("inserted") is True),
        )
        tca_unknown_count = max(
            int(shutdown_reconciliation.get("tca_unknown_count", 0) or 0),
            sum(
                1
                for result in self._fill_hydration_results
                if result.get("inserted") is True
                and result.get("execution_quality_verdict") == "UNKNOWN_INSUFFICIENT_BROKER_DETAIL"
            ),
        )
        realized_netedge_available_count = max(
            int(shutdown_reconciliation.get("realized_vs_modeled_netedge_available_count", 0) or 0),
            sum(1 for result in self._fill_hydration_results if result.get("realized_netedge_available") is True),
        )
        realized_netedge_unknown_count = max(0, int(tca_records_count) - int(realized_netedge_available_count))
        broker_fee_summary = self._broker_fee_hydration_summary()
        active_pending_order_ids = tuple(self._pending_orders.keys())
        pending_terminal_leak_ids = []
        for order_id in active_pending_order_ids:
            for broker in {self._gateway_order_mapping_broker(), self._mapping_broker(), "paper"}:
                mapping = self._get_order_id_mapping_read_only(order_id, broker)
                if mapping is not None and mapping.is_terminal:
                    pending_terminal_leak_ids.append(order_id)
                    break
        return {
            "submitted_count": int(self._oms_lifecycle_counts.get("submitted", 0)),
            "acknowledged_count": int(self._oms_lifecycle_counts.get("acknowledged", 0)),
            "acknowledged_count_legacy_note": "legacy lifecycle count; use order_post_acknowledged and cancel_acknowledged for broker mutation truth",
            "order_post_attempted": int(order_post_attempted),
            "order_post_authorized": int(order_post_authorized),
            "order_post_acknowledged": int(order_post_acknowledged),
            "cancel_attempted": int(cancel_attempted),
            "cancel_authorized": int(cancel_authorized),
            "cancel_acknowledged": int(cancel_acknowledged),
            "active_pending_orders": len(self._pending_orders),
            "active_pending_order_ids": active_pending_order_ids,
            "terminal_orders": int(terminal_orders),
            "open_orders": int(broker_confirmed_open_orders),
            "local_open_orders_before_final_reconcile": int(
                shutdown_reconciliation.get("local_open_orders_before_final_reconcile", local_open_orders) or 0
            ),
            "broker_confirmed_open_orders": int(broker_confirmed_open_orders),
            "local_open_orders_after_final_reconcile": int(
                shutdown_reconciliation.get("local_open_orders_after_final_reconcile", local_open_orders) or 0
            ),
            "local_open_without_broker_match_count": int(
                shutdown_reconciliation.get("local_open_without_broker_match_count", 0) or 0
            ),
            "final_state_unknown_count": int(shutdown_reconciliation.get("final_state_unknown_count", 0) or 0),
            "reconciliation_conflict_count": int(reconciliation_conflicts),
            "fill_hydration_attempted_count": int(fill_hydration_attempted_count),
            "fill_hydration_count": int(fill_hydration_count),
            "fill_hydration_partial_count": int(fill_hydration_partial_count),
            "fill_hydration_missing_count": int(fill_hydration_missing_count),
            "fill_hydration_conflict_count": int(fill_hydration_conflict_count),
            "broker_filled_orders": int(shutdown_reconciliation.get("broker_filled_orders", 0) or 0),
            "broker_partially_filled_orders": int(shutdown_reconciliation.get("broker_partially_filled_orders", 0) or 0),
            "broker_canceled_with_fill_count": int(shutdown_reconciliation.get("broker_canceled_with_fill_count", 0) or 0),
            "tca_records_count": int(tca_records_count),
            "tca_unknown_count": int(tca_unknown_count),
            "broker_fee_hydration_attempted_count": max(
                int(shutdown_reconciliation.get("broker_fee_hydration_attempted_count", 0) or 0),
                int(broker_fee_summary.get("broker_fee_hydration_attempted_count", 0) or 0),
            ),
            "broker_fee_hydration_count": max(
                int(shutdown_reconciliation.get("broker_fee_hydration_count", 0) or 0),
                int(broker_fee_summary.get("broker_fee_hydration_count", 0) or 0),
            ),
            "broker_fee_hydration_pending_count": max(
                int(shutdown_reconciliation.get("broker_fee_hydration_pending_count", 0) or 0),
                int(broker_fee_summary.get("broker_fee_hydration_pending_count", 0) or 0),
            ),
            "broker_fee_hydration_unmatched_count": max(
                int(shutdown_reconciliation.get("broker_fee_hydration_unmatched_count", 0) or 0),
                int(broker_fee_summary.get("broker_fee_hydration_unmatched_count", 0) or 0),
            ),
            "broker_fee_hydration_conflict_count": max(
                int(shutdown_reconciliation.get("broker_fee_hydration_conflict_count", 0) or 0),
                int(broker_fee_summary.get("broker_fee_hydration_conflict_count", 0) or 0),
            ),
            "broker_fee_activity_records_seen_count": max(
                int(shutdown_reconciliation.get("broker_fee_activity_records_seen_count", 0) or 0),
                int(broker_fee_summary.get("broker_fee_activity_records_seen_count", 0) or 0),
            ),
            "broker_fee_activity_records_matched_count": max(
                int(shutdown_reconciliation.get("broker_fee_activity_records_matched_count", 0) or 0),
                int(broker_fee_summary.get("broker_fee_activity_records_matched_count", 0) or 0),
            ),
            "broker_fee_activity_duplicate_ignored_count": max(
                int(shutdown_reconciliation.get("broker_fee_activity_duplicate_ignored_count", 0) or 0),
                int(broker_fee_summary.get("broker_fee_activity_duplicate_ignored_count", 0) or 0),
            ),
            "fee_hydration_skipped": bool(
                shutdown_reconciliation.get("fee_hydration_skipped")
                or broker_fee_summary.get("fee_hydration_skipped")
            ),
            "fee_hydration_skip_reason": (
                shutdown_reconciliation.get("fee_hydration_skip_reason")
                or broker_fee_summary.get("fee_hydration_skip_reason")
            ),
            "fee_hydration_status": (
                shutdown_reconciliation.get("fee_hydration_status")
                or broker_fee_summary.get("fee_hydration_status")
            ),
            "account_activity_read_authorized": bool(
                shutdown_reconciliation.get(
                    "account_activity_read_authorized",
                    broker_fee_summary.get("account_activity_read_authorized"),
                )
            ),
            "broker_read_profile": (
                shutdown_reconciliation.get("broker_read_profile")
                or broker_fee_summary.get("broker_read_profile")
            ),
            "tca_complete_count": max(
                int(shutdown_reconciliation.get("tca_complete_count", 0) or 0),
                int(broker_fee_summary.get("tca_complete_count", 0) or 0),
            ),
            "tca_estimated_count": max(
                int(shutdown_reconciliation.get("tca_estimated_count", 0) or 0),
                int(broker_fee_summary.get("tca_estimated_count", 0) or 0),
            ),
            "tca_fee_pending_count": max(
                int(shutdown_reconciliation.get("tca_fee_pending_count", 0) or 0),
                int(broker_fee_summary.get("tca_fee_pending_count", 0) or 0),
            ),
            "realized_vs_modeled_netedge_available_count": int(realized_netedge_available_count),
            "realized_vs_modeled_netedge_unknown_count": int(realized_netedge_unknown_count),
            "filled_orders": sum(1 for row in mapping_rows if str(row.get("status") or "").lower() == "filled"),
            "canceled_orders": sum(1 for row in mapping_rows if str(row.get("status") or "").lower() in {"canceled", "cancelled"}),
            "rejected_orders": sum(1 for row in mapping_rows if str(row.get("status") or "").lower() == "rejected"),
            "expired_orders": sum(1 for row in mapping_rows if str(row.get("status") or "").lower() == "expired"),
            "mappings": len(mapping_rows),
            "local_orders": int(table_counts.get("orders", 0)),
            "legacy_local_fills": int(table_counts.get("fills", 0)),
            "local_fills": int(table_counts.get("broker_fill_ledger", table_counts.get("fills", 0))),
            "local_order_id_mappings": int(table_counts.get("order_id_mappings", len(mapping_rows))),
            "local_reservation_ledger": int(table_counts.get("reservation_ledger", 0)),
            "local_reservation_fill_progress": int(table_counts.get("reservation_fill_progress", 0)),
            "local_reservation_release_tombstones": int(table_counts.get("reservation_release_tombstones", 0)),
            "last_broker_account_status": latest_reconciliation.get("account_status"),
            "last_broker_open_orders_count": latest_reconciliation.get("open_orders_count"),
            "last_broker_positions_count": latest_reconciliation.get("positions_count"),
            "shutdown_reconciliation": shutdown_reconciliation,
            "broker_open_orders_unmatched_count": int(
                shutdown_reconciliation.get("broker_open_orders_unmatched_count", 0) or 0
            ),
            "reconciliation_conflicts": int(reconciliation_conflicts),
            "cancel_authorized_count": int(self._oms_lifecycle_counts.get("cancel_authorized", 0)),
            "cancel_denied_count": int(self._oms_lifecycle_counts.get("cancel_denied", 0)),
            "pending_terminal_leak_count": len(set(pending_terminal_leak_ids)),
            "pending_terminal_leak_ids": tuple(dict.fromkeys(pending_terminal_leak_ids)),
            "mutation_method_counts": {
                "GET": int(request_counts.get("GET", 0) or 0),
                "POST": int(request_counts.get("POST", 0) or 0),
                "DELETE": int(request_counts.get("DELETE", 0) or 0),
            },
            "broker_boundary_event_history_replayed_in_shutdown": True,
            "broker_boundary_event_history_count": len(self._broker_boundary_events),
            "broker_boundary_events": tuple(dict(event) for event in self._broker_boundary_events[-20:]),
            "cancel_denials": dict(self._cancel_denials_by_order_id),
        }

    def _broker_gateway_request_counts(self) -> Dict[str, int]:
        adapter = self._broker_gateway_adapter
        counts = getattr(adapter, "request_counts", {}) if adapter is not None else {}
        return {str(key).upper(): int(value) for key, value in dict(counts).items()}

    def _record_oms_state(self, state: str) -> None:
        key_by_state = {
            OmsOrderState.ROUTER_SUBMITTED.value: "submitted",
            OmsOrderState.BROKER_ACKNOWLEDGED.value: "acknowledged",
            OmsOrderState.OPEN.value: "open",
            OmsOrderState.PARTIALLY_FILLED.value: "partially_filled",
            OmsOrderState.FILLED.value: "filled",
            OmsOrderState.CANCEL_REQUESTED.value: "cancel_requested",
            OmsOrderState.CANCELED.value: "canceled",
            OmsOrderState.REJECTED.value: "rejected",
            OmsOrderState.EXPIRED.value: "expired",
            OmsOrderState.RECONCILIATION_CONFLICT.value: "reconciliation_conflicts",
        }
        key = key_by_state.get(str(state))
        if key:
            self._oms_lifecycle_counts[key] = int(self._oms_lifecycle_counts.get(key, 0)) + 1

    def _oms_state_for_lifecycle_phase(self, lifecycle_phase: str) -> str:
        return {
            "order_submitted": OmsOrderState.ROUTER_SUBMITTED.value,
            "order_acknowledged": OmsOrderState.BROKER_ACKNOWLEDGED.value,
            "order_partially_filled": OmsOrderState.PARTIALLY_FILLED.value,
            "order_fully_filled": OmsOrderState.FILLED.value,
            "cancel_requested": OmsOrderState.CANCEL_REQUESTED.value,
            "order_canceled": OmsOrderState.CANCELED.value,
            "order_rejected": OmsOrderState.REJECTED.value,
            "order_expired": OmsOrderState.EXPIRED.value,
            "reconciliation_conflict": OmsOrderState.RECONCILIATION_CONFLICT.value,
        }.get(str(lifecycle_phase), OmsOrderState.INTENT_CREATED.value)

    def _record_broker_boundary_telemetry(
        self,
        order: OrderRequest,
        *,
        response: Optional[BrokerGatewayResponse],
        broker_post_attempted: bool,
        broker_post_authorized: bool,
        broker_boundary_result: str,
        reason_code: Optional[str] = None,
    ) -> Dict[str, Any]:
        request_counts = self._broker_gateway_request_counts()
        event = {
            "client_order_id": order.id,
            "decision_uuid": order.decision_uuid,
            "symbol": order.symbol,
            "side": self._value_as_str(order.side),
            "broker_post_attempted": bool(broker_post_attempted),
            "broker_post_authorized": bool(broker_post_authorized),
            "broker_post_acknowledged": bool(response is not None and response.ok and response.broker_order_id),
            "broker_order_id": getattr(response, "broker_order_id", None) if response is not None else None,
            "broker_boundary_result": broker_boundary_result,
            "reason_code": reason_code or (getattr(response, "reason_code", None) if response is not None else None),
            "request_method": getattr(response, "request_method", None) if response is not None else None,
            "endpoint_path": getattr(response, "endpoint_path", None) if response is not None else None,
            "normalized_status": getattr(response, "normalized_status", None) if response is not None else None,
            "mutation_occurred": bool(getattr(response, "mutation_occurred", False)) if response is not None else False,
            "mutation_method_counts": {
                "GET": int(request_counts.get("GET", 0) or 0),
                "POST": int(request_counts.get("POST", 0) or 0),
                "DELETE": int(request_counts.get("DELETE", 0) or 0),
            },
        }
        self._broker_boundary_events.append(event)
        logger.info("[OMS_DIAG] BROKER_BOUNDARY_RESULT fields=%s", event)
        return event

    def _should_use_external_paper_gateway(self) -> bool:
        return (
            self.paper_mode
            and self._broker_gateway_adapter is not None
            and self._broker_gateway_identity_error() is None
        )

    def _order_requests_gateway_route(self, order: OrderRequest) -> bool:
        if self._external_paper_broker_requested:
            return True
        if self._broker_gateway_adapter is None:
            return False
        metadata = order.metadata if isinstance(order.metadata, dict) else {}
        requested_adapter = str(metadata.get("execution_adapter") or "").strip().lower()
        identity = getattr(self._broker_gateway_adapter, "identity", None)
        adapter_id = str(getattr(identity, "adapter_id", "") or "").strip().lower()
        return bool(requested_adapter and adapter_id and requested_adapter == adapter_id)

    def _gateway_order_mapping_broker(self) -> str:
        identity = getattr(self._broker_gateway_adapter, "identity", None)
        return str(getattr(identity, "venue_id", "") or self.primary_exchange or "").strip().lower()

    def _normalize_broker_symbol(self, value: Any) -> str:
        return str(value or "").replace("/", "").upper()

    def _is_local_open_order_mapping(self, row: Dict[str, Any]) -> bool:
        if bool(row.get("is_terminal")):
            return False
        status = str(row.get("status") or "").strip().lower()
        return status in {
            "open",
            "accepted",
            "acknowledged",
            "broker_acknowledged",
            "partially_filled",
            "partial_fill",
            "partial",
            "pending",
            "new",
        }

    def _broker_open_order_identity_set(self, open_orders: List[Dict[str, Any]]) -> set[str]:
        identities: set[str] = set()
        for row in open_orders:
            if not isinstance(row, dict):
                continue
            for key in ("id", "order_id", "client_order_id"):
                value = str(row.get(key) or "").strip()
                if value:
                    identities.add(value)
        return identities

    def _mapping_identity_values(self, mapping: ActiveOrderIdMapping) -> set[str]:
        return {
            value
            for value in (
                str(mapping.client_order_id or "").strip(),
                str(mapping.command_order_id or "").strip(),
                str(mapping.broker_order_id or "").strip(),
                str(mapping.venue_order_id or "").strip(),
                str(mapping.exchange_txid or "").strip(),
            )
            if value
        }

    def _mapping_matches_broker_open_orders(
        self,
        mapping: ActiveOrderIdMapping,
        open_order_ids: set[str],
    ) -> bool:
        return bool(self._mapping_identity_values(mapping) & open_order_ids)

    def _decimal_from_payload(self, payload: Dict[str, Any], keys: Tuple[str, ...]) -> Optional[_Decimal]:
        for key in keys:
            if key not in payload or payload.get(key) in (None, ""):
                continue
            try:
                return _Decimal(str(payload.get(key)))
            except Exception:
                return None
        return None

    def _payload_value(self, payload: Dict[str, Any], keys: Tuple[str, ...]) -> Any:
        for key in keys:
            if key in payload and payload.get(key) not in (None, ""):
                return payload.get(key)
        return None

    def _broker_read_allowed(self, family: str, activity_type: Any | None = None) -> bool:
        return broker_read_allowed(family, activity_type, profile=self._broker_read_profile)

    def _fee_activity_read_authorized(self) -> bool:
        return self._broker_read_allowed(READ_ACCOUNT_ACTIVITIES, "CFEE,FEE") and self._broker_read_allowed(
            READ_FEE_HYDRATION,
            "CFEE,FEE",
        )

    def _broker_fill_activities(self) -> List[Dict[str, Any]]:
        if self._broker_fill_activity_cache is not None:
            return list(self._broker_fill_activity_cache)
        self._broker_fill_activity_cache = []
        if not (
            self._broker_read_allowed(READ_ACCOUNT_ACTIVITIES, "FILL")
            and self._broker_read_allowed(READ_FILL_ACTIVITY_HYDRATION, "FILL")
        ):
            self._broker_fill_activity_fetch_error = BROKER_READ_NOT_AUTHORIZED
            return []
        adapter = self._broker_gateway_adapter
        getter = getattr(adapter, "get_account_activities", None)
        if not callable(getter):
            self._broker_fill_activity_fetch_error = "broker_activity_method_missing"
            return []
        try:
            response = getter(activity_types="FILL", page_size=100)
        except BrokerGatewayError as exc:
            self._broker_fill_activity_fetch_error = exc.reason_code
            return []
        if not getattr(response, "ok", False):
            self._broker_fill_activity_fetch_error = str(getattr(response, "reason_code", None) or "broker_activity_get_failed")
            return []
        payload = response.payload
        if isinstance(payload, dict):
            payload = payload.get("activities", payload.get("items", []))
        if not isinstance(payload, list):
            self._broker_fill_activity_fetch_error = "broker_activity_invalid_shape"
            return []
        self._broker_fill_activity_cache = [item for item in payload if isinstance(item, dict)]
        return list(self._broker_fill_activity_cache)

    def _broker_fee_activities(self) -> List[Dict[str, Any]]:
        if self._broker_fee_activity_cache is not None:
            return list(self._broker_fee_activity_cache)
        self._broker_fee_activity_cache = []
        if not self._fee_activity_read_authorized():
            self._broker_fee_activity_fetch_error = BROKER_READ_NOT_AUTHORIZED
            return []
        adapter = self._broker_gateway_adapter
        getter = getattr(adapter, "get_fee_activities", None)
        try:
            if callable(getter):
                response = getter(page_size=100)
            else:
                getter = getattr(adapter, "get_account_activities", None)
                if not callable(getter):
                    self._broker_fee_activity_fetch_error = "broker_fee_activity_method_missing"
                    return []
                response = getter(activity_types="CFEE,FEE", page_size=100)
        except BrokerGatewayError as exc:
            self._broker_fee_activity_fetch_error = exc.reason_code
            return []
        if not getattr(response, "ok", False):
            self._broker_fee_activity_fetch_error = str(
                getattr(response, "reason_code", None) or "broker_fee_activity_get_failed"
            )
            return []
        payload = response.payload
        if isinstance(payload, dict):
            payload = payload.get("activities", payload.get("items", []))
        if not isinstance(payload, list):
            self._broker_fee_activity_fetch_error = "broker_fee_activity_invalid_shape"
            return []
        self._broker_fee_activity_cache = [item for item in payload if isinstance(item, dict)]
        return list(self._broker_fee_activity_cache)

    def _matching_broker_fill_activity(
        self,
        *,
        broker_order_id: str,
        client_order_id: str,
    ) -> Optional[Dict[str, Any]]:
        for activity in self._broker_fill_activities():
            activity_order_id = str(activity.get("order_id") or activity.get("broker_order_id") or "").strip()
            activity_client_id = str(activity.get("client_order_id") or "").strip()
            if broker_order_id and activity_order_id == broker_order_id:
                return activity
            if client_order_id and activity_client_id == client_order_id:
                return activity
        return None

    def _normalized_broker_fee_activity(self, activity: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        activity_type = str(activity.get("activity_type") or activity.get("type") or "").strip().upper()
        if activity_type not in {"CFEE", "FEE"}:
            return None
        activity_id = str(activity.get("id") or activity.get("activity_id") or "").strip()
        fee_amount = self._decimal_from_payload(
            activity,
            ("net_amount", "amount", "fee", "commission", "commission_amount"),
        )
        raw_amount = fee_amount
        if fee_amount is not None:
            fee_amount = abs(fee_amount)
        fee_currency = str(
            activity.get("currency")
            or activity.get("currency_code")
            or activity.get("fee_currency")
            or activity.get("commission_currency")
            or ""
        ).strip()
        transaction_time = str(
            self._payload_value(activity, ("transaction_time", "date", "created_at", "updated_at"))
            or ""
        ).strip()
        order_ids = {
            str(value).strip()
            for value in (
                activity.get("order_id"),
                activity.get("broker_order_id"),
                activity.get("client_order_id"),
            )
            if str(value or "").strip()
        }
        quantity = self._decimal_from_payload(activity, ("qty", "quantity", "cum_qty"))
        price = self._decimal_from_payload(activity, ("price", "avg_price"))
        return {
            "raw": activity,
            "activity_id": activity_id or None,
            "activity_key": activity_id
            or "|".join(
                (
                    activity_type,
                    str(activity.get("symbol") or ""),
                    str(raw_amount),
                    fee_currency,
                    transaction_time,
                    str(activity.get("description") or ""),
                )
            ),
            "activity_type": activity_type,
            "fee_amount": fee_amount,
            "fee_amount_signed": str(raw_amount) if raw_amount is not None else None,
            "fee_currency": fee_currency or None,
            "symbol": activity.get("symbol"),
            "symbol_norm": self._normalize_broker_symbol(activity.get("symbol")),
            "order_ids": order_ids,
            "quantity": quantity,
            "price": price,
            "transaction_time": transaction_time or None,
            "transaction_ts_ns": self._timestamp_ns_from_broker_text(transaction_time),
            "description": activity.get("description"),
        }

    def _fill_row_identity_values(self, row: Dict[str, Any]) -> set[str]:
        return {
            str(value).strip()
            for value in (
                row.get("broker_order_id"),
                row.get("client_order_id"),
                row.get("broker_activity_id"),
            )
            if str(value or "").strip()
        }

    def _decimal_text_equal(self, left: Any, right: Any) -> bool:
        left_decimal = self._decimal_from_payload({"value": left}, ("value",))
        right_decimal = self._decimal_from_payload({"value": right}, ("value",))
        return left_decimal is not None and right_decimal is not None and left_decimal == right_decimal

    def _fee_activity_composite_matches_row(self, activity: Dict[str, Any], row: Dict[str, Any]) -> bool:
        if not activity.get("symbol_norm"):
            return False
        if activity["symbol_norm"] != self._normalize_broker_symbol(row.get("symbol")):
            return False
        activity_ts_ns = activity.get("transaction_ts_ns")
        row_ts_ns = row.get("fill_ts_ns")
        try:
            row_ts_ns = int(row_ts_ns) if row_ts_ns is not None else None
        except Exception:
            row_ts_ns = None
        if activity_ts_ns is None or row_ts_ns is None:
            return False
        if abs(int(activity_ts_ns) - int(row_ts_ns)) > 36 * 60 * 60 * 1_000_000_000:
            return False
        if activity.get("quantity") is not None and not self._decimal_text_equal(activity.get("quantity"), row.get("quantity")):
            return False
        if activity.get("price") is not None and not self._decimal_text_equal(activity.get("price"), row.get("price")):
            return False
        return True

    def _fee_activity_match_for_fill_row(
        self,
        *,
        row: Dict[str, Any],
        activity: Dict[str, Any],
        all_rows: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        row_identities = self._fill_row_identity_values(row)
        if row_identities and row_identities & set(activity.get("order_ids", set())):
            return {
                "confidence": "EXACT",
                "keys": tuple(sorted(row_identities & set(activity.get("order_ids", set())))),
            }
        if not self._fee_activity_composite_matches_row(activity, row):
            return None
        matching_rows = [
            candidate
            for candidate in all_rows
            if self._fee_activity_composite_matches_row(activity, candidate)
        ]
        if len(matching_rows) == 1 and str(matching_rows[0].get("fill_id")) == str(row.get("fill_id")):
            return {
                "confidence": "STRONG",
                "keys": ("symbol", "fill_timestamp_window", "quantity_or_price_when_available"),
            }
        return {"confidence": "AMBIGUOUS", "keys": ("composite_many_to_one",)}

    def _fee_tca_fields_for_fill_row(self, row: Dict[str, Any], fee: _Decimal) -> Dict[str, Any]:
        notional = self._decimal_from_payload(row, ("notional",))
        price = self._decimal_from_payload(row, ("price",))
        quantity = self._decimal_from_payload(row, ("quantity",))
        if notional is None and price is not None and quantity is not None:
            notional = price * quantity
        fee_bps = (fee / notional) * _Decimal("10000") if notional is not None and notional > 0 else None
        modeled_net_edge = self._decimal_from_payload(row, ("modeled_net_edge",))
        slippage_bps = self._decimal_from_payload(row, ("slippage_bps",))
        realized_vs_modeled = None
        if modeled_net_edge is not None and slippage_bps is not None and fee_bps is not None:
            realized_drag = (max(slippage_bps, _Decimal("0")) + fee_bps) / _Decimal("10000")
            realized_vs_modeled = modeled_net_edge - realized_drag
        if modeled_net_edge is None or slippage_bps is None or fee_bps is None:
            tca_status = "UNKNOWN"
            verdict = "UNKNOWN_INSUFFICIENT_BROKER_DETAIL"
        elif slippage_bps > _Decimal("1"):
            tca_status = "HYDRATED"
            verdict = "WORSE_THAN_MODELED"
        elif slippage_bps < _Decimal("-1"):
            tca_status = "HYDRATED"
            verdict = "BETTER_THAN_MODELED"
        else:
            tca_status = "HYDRATED"
            verdict = "IN_LINE"
        return {
            "fee_bps": str(fee_bps) if fee_bps is not None else None,
            "tca_status": tca_status,
            "execution_quality_verdict": verdict,
            "realized_vs_modeled_netedge": str(realized_vs_modeled) if realized_vs_modeled is not None else None,
            "realized_netedge_available": realized_vs_modeled is not None,
        }

    def _insert_legacy_fill_after_fee_match(
        self,
        row: Dict[str, Any],
        *,
        fee: _Decimal,
        fee_currency: str,
    ) -> bool:
        if self._state_store is None:
            return False
        quantity = self._decimal_from_payload(row, ("quantity",))
        price = self._decimal_from_payload(row, ("price",))
        if quantity is None or price is None:
            return False
        timestamp = str(row.get("fill_timestamp") or "").strip()
        if not timestamp:
            return False
        return bool(
            self._state_store.insert_fill(
                {
                    "id": f"legacy:{row.get('fill_id')}",
                    "order_id": row.get("client_order_id"),
                    "symbol": row.get("symbol"),
                    "side": row.get("side"),
                    "quantity": float(quantity),
                    "price": float(price),
                    "fee": float(fee),
                    "fee_currency": fee_currency,
                    "timestamp": timestamp,
                    "exchange_order_id": row.get("broker_order_id"),
                    "latency_ms": None,
                }
            )
        )

    def _hydrate_deferred_broker_fees(self, *, source_event: str) -> None:
        if self._state_store is None:
            return
        lister = getattr(self._state_store, "list_broker_fill_ledger", None)
        updater = getattr(self._state_store, "update_broker_fill_fee_hydration", None)
        if not callable(lister) or not callable(updater):
            return
        all_rows = lister(missing_fee_only=False)
        missing_fee_rows = [
            row
            for row in all_rows
            if not str(row.get("fee") or "").strip() or not str(row.get("fee_currency") or "").strip()
        ]
        if not missing_fee_rows:
            return
        if not self._fee_activity_read_authorized():
            self._broker_fee_hydration_skipped = True
            self._broker_fee_hydration_skip_reason = BROKER_READ_NOT_AUTHORIZED
            logger.info(
                "[OMS_DIAG] BROKER_FEE_HYDRATION_SKIPPED fields=%s",
                {
                    "source_event": source_event,
                    "status": "SKIPPED_NOT_AUTHORIZED",
                    "reason_code": BROKER_READ_NOT_AUTHORIZED,
                    "broker_read_profile": self._broker_read_profile.name,
                    "account_activity_read_authorized": False,
                    "fee_hydration_allowed": False,
                },
            )
            return
        normalized_activities: List[Dict[str, Any]] = []
        seen_activity_keys: set[str] = set()
        for activity in self._broker_fee_activities():
            normalized = self._normalized_broker_fee_activity(activity)
            if normalized is None:
                continue
            activity_key = str(normalized.get("activity_key") or "")
            if activity_key and activity_key in seen_activity_keys:
                self._broker_fee_hydration_results.append(
                    {
                        "source_event": source_event,
                        "status": "DUPLICATE_IGNORED",
                        "reason_code": "DUPLICATE_BROKER_FEE_ACTIVITY",
                        "broker_fee_activity_id": normalized.get("activity_id"),
                        "broker_fee_activity_type": normalized.get("activity_type"),
                    }
                )
                continue
            if activity_key:
                seen_activity_keys.add(activity_key)
            normalized_activities.append(normalized)

        used_activity_keys: set[str] = set()
        for row in missing_fee_rows:
            base_result: Dict[str, Any] = {
                "source_event": source_event,
                "fill_id": row.get("fill_id"),
                "broker_order_id": row.get("broker_order_id"),
                "client_order_id": row.get("client_order_id"),
                "symbol": row.get("symbol"),
                "status": "FEE_PENDING_BROKER_ACTIVITY",
                "reason_code": "FEE_ACTIVITY_NOT_YET_POSTED",
                "inserted": False,
                "updated": False,
                "duplicate_ignored": False,
                "tca_status": row.get("tca_status") or "UNKNOWN",
                "execution_quality_verdict": row.get("execution_quality_verdict") or "UNKNOWN_INSUFFICIENT_BROKER_DETAIL",
            }
            if self._broker_fee_activity_fetch_error:
                base_result["reason_code"] = "FEE_ACTIVITY_QUERY_FAILED"
                base_result["fetch_error"] = self._broker_fee_activity_fetch_error
                self._broker_fee_hydration_results.append(base_result)
                continue
            if not normalized_activities:
                self._broker_fee_hydration_results.append(base_result)
                continue

            matches = []
            for activity in normalized_activities:
                activity_key = str(activity.get("activity_key") or "")
                if activity_key and activity_key in used_activity_keys:
                    continue
                match = self._fee_activity_match_for_fill_row(row=row, activity=activity, all_rows=missing_fee_rows)
                if match is not None:
                    matches.append((activity, match))

            ambiguous = [item for item in matches if item[1].get("confidence") == "AMBIGUOUS"]
            valid_matches = [item for item in matches if item[1].get("confidence") in {"EXACT", "STRONG"}]
            if ambiguous and not valid_matches:
                conflict = dict(base_result)
                conflict.update(
                    {
                        "status": "FEE_ACTIVITY_CONFLICT",
                        "reason_code": "FEE_ACTIVITY_AMBIGUOUS_MATCH",
                        "matched_activity_count": len(ambiguous),
                    }
                )
                self._broker_fee_hydration_results.append(conflict)
                continue
            if not valid_matches:
                unmatched = dict(base_result)
                unmatched.update(
                    {
                        "status": "FEE_ACTIVITY_UNMATCHED",
                        "reason_code": "FEE_ACTIVITY_UNMATCHED",
                    }
                )
                self._broker_fee_hydration_results.append(unmatched)
                continue
            if len(valid_matches) > 1:
                conflict = dict(base_result)
                conflict.update(
                    {
                        "status": "FEE_ACTIVITY_CONFLICT",
                        "reason_code": "MULTIPLE_FEE_ACTIVITY_MATCHES",
                        "matched_activity_count": len(valid_matches),
                    }
                )
                self._broker_fee_hydration_results.append(conflict)
                continue

            activity, match = valid_matches[0]
            result = dict(base_result)
            result.update(
                {
                    "broker_fee_activity_id": activity.get("activity_id"),
                    "broker_fee_activity_type": activity.get("activity_type"),
                    "fee_match_confidence": match.get("confidence"),
                    "fee_match_keys": tuple(match.get("keys") or ()),
                }
            )
            fee_amount = activity.get("fee_amount")
            fee_currency = activity.get("fee_currency")
            if fee_amount is None or not fee_currency:
                result.update(
                    {
                        "status": "FEE_UNAVAILABLE",
                        "reason_code": "FEE_AMOUNT_OR_CURRENCY_MISSING",
                        "missing_fields": tuple(
                            field
                            for field, value in (("fee_amount", fee_amount), ("fee_currency", fee_currency))
                            if value in (None, "")
                        ),
                    }
                )
                self._broker_fee_hydration_results.append(result)
                continue

            tca_fields = self._fee_tca_fields_for_fill_row(row, fee_amount)
            fee_source = "BROKER_CFEE" if activity.get("activity_type") == "CFEE" else "BROKER_FEE"
            update_status = updater(
                str(row.get("fill_id")),
                fee=fee_amount,
                fee_currency=str(fee_currency),
                fee_bps=tca_fields.get("fee_bps"),
                tca_status=tca_fields.get("tca_status"),
                execution_quality_verdict=tca_fields.get("execution_quality_verdict"),
                realized_vs_modeled_netedge=tca_fields.get("realized_vs_modeled_netedge"),
                metadata_updates={
                    "fee_status": "FEE_ACTIVITY_MATCHED",
                    "fee_source": fee_source,
                    "broker_fee_activity_id": activity.get("activity_id"),
                    "broker_fee_activity_type": activity.get("activity_type"),
                    "broker_fee_amount": str(fee_amount),
                    "broker_fee_amount_signed": activity.get("fee_amount_signed"),
                    "broker_fee_currency": fee_currency,
                    "broker_fee_symbol": activity.get("symbol"),
                    "broker_fee_quantity": str(activity.get("quantity")) if activity.get("quantity") is not None else None,
                    "broker_fee_price": str(activity.get("price")) if activity.get("price") is not None else None,
                    "broker_fee_transaction_time": activity.get("transaction_time"),
                    "fee_hydrated_at": now_ns(),
                    "fee_hydration_reason_code": "BROKER_CFEE_FEE_ACTIVITY_MATCHED",
                    "fee_match_confidence": match.get("confidence"),
                    "fee_match_keys": tuple(match.get("keys") or ()),
                    "fee_activity_description": activity.get("description"),
                },
            )
            if update_status in {"updated", "duplicate"}:
                if activity.get("activity_key"):
                    used_activity_keys.add(str(activity.get("activity_key")))
                result.update(
                    {
                        "status": "FEE_ACTIVITY_MATCHED",
                        "reason_code": "BROKER_CFEE_FEE_ACTIVITY_MATCHED",
                        "updated": update_status == "updated",
                        "duplicate_ignored": update_status == "duplicate",
                        "fee_available": True,
                        "fee_currency_available": True,
                        "fee_source": fee_source,
                        "fee_amount": str(fee_amount),
                        "fee_currency": fee_currency,
                        "fee_bps": tca_fields.get("fee_bps"),
                        "tca_status": tca_fields.get("tca_status"),
                        "execution_quality_verdict": tca_fields.get("execution_quality_verdict"),
                        "realized_netedge_available": bool(tca_fields.get("realized_netedge_available")),
                        "legacy_fill_inserted": self._insert_legacy_fill_after_fee_match(
                            row,
                            fee=fee_amount,
                            fee_currency=str(fee_currency),
                        )
                        if update_status == "updated"
                        else False,
                    }
                )
            else:
                result.update(
                    {
                        "status": "FEE_ACTIVITY_CONFLICT" if update_status == "conflict" else "FEE_UNAVAILABLE",
                        "reason_code": f"FEE_HYDRATION_{str(update_status).upper()}",
                        "ledger_status": update_status,
                    }
                )
            self._broker_fee_hydration_results.append(result)
        logger.info("[OMS_DIAG] BROKER_FEE_HYDRATION fields=%s", tuple(self._broker_fee_hydration_results[-len(missing_fee_rows):]))

    def _broker_fee_hydration_summary(self) -> Dict[str, Any]:
        rows: List[Dict[str, Any]] = []
        if self._state_store is not None:
            lister = getattr(self._state_store, "list_broker_fill_ledger", None)
            if callable(lister):
                rows = lister(missing_fee_only=False)
        matched_results = [
            result for result in self._broker_fee_hydration_results
            if result.get("status") == "FEE_ACTIVITY_MATCHED"
        ]
        pending_results = [
            result for result in self._broker_fee_hydration_results
            if result.get("status") == "FEE_PENDING_BROKER_ACTIVITY"
        ]
        unmatched_results = [
            result for result in self._broker_fee_hydration_results
            if result.get("status") in {"FEE_ACTIVITY_UNMATCHED", "FEE_UNAVAILABLE"}
        ]
        conflict_results = [
            result for result in self._broker_fee_hydration_results
            if result.get("status") == "FEE_ACTIVITY_CONFLICT"
        ]
        duplicate_results = [
            result for result in self._broker_fee_hydration_results
            if result.get("status") == "DUPLICATE_IGNORED" or result.get("duplicate_ignored") is True
        ]
        tca_complete_count = 0
        tca_estimated_count = 0
        tca_fee_pending_count = 0
        for row in rows:
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            if (
                str(row.get("tca_status") or "").upper() == "HYDRATED"
                and str(row.get("execution_quality_verdict") or "") != "UNKNOWN_INSUFFICIENT_BROKER_DETAIL"
            ):
                tca_complete_count += 1
            if metadata.get("fee_source") == "ESTIMATED_POLICY":
                tca_estimated_count += 1
            if not str(row.get("fee") or "").strip() or not str(row.get("fee_currency") or "").strip():
                tca_fee_pending_count += 1
        return {
            "broker_fee_hydration_attempted_count": len(self._broker_fee_hydration_results),
            "broker_fee_hydration_count": sum(1 for result in matched_results if result.get("updated") is True),
            "broker_fee_hydration_pending_count": len(pending_results),
            "broker_fee_hydration_unmatched_count": len(unmatched_results),
            "broker_fee_hydration_conflict_count": len(conflict_results),
            "broker_fee_activity_records_seen_count": len(self._broker_fee_activity_cache or ()),
            "broker_fee_activity_records_matched_count": len(
                {
                    str(result.get("broker_fee_activity_id") or result.get("fill_id") or "")
                    for result in matched_results
                    if str(result.get("broker_fee_activity_id") or result.get("fill_id") or "")
                }
            ),
            "broker_fee_activity_duplicate_ignored_count": len(duplicate_results),
            "fee_hydration_skipped": bool(self._broker_fee_hydration_skipped),
            "fee_hydration_skip_reason": self._broker_fee_hydration_skip_reason,
            "fee_hydration_status": (
                "SKIPPED_NOT_AUTHORIZED"
                if self._broker_fee_hydration_skipped
                else ("AUTHORIZED" if self._fee_activity_read_authorized() else "NOT_AUTHORIZED")
            ),
            "account_activity_read_authorized": self._broker_read_allowed(READ_ACCOUNT_ACTIVITIES),
            "broker_read_profile": self._broker_read_profile.name,
            "tca_complete_count": int(tca_complete_count),
            "tca_estimated_count": int(tca_estimated_count),
            "tca_fee_pending_count": int(tca_fee_pending_count),
        }

    def _timestamp_ns_from_broker_text(self, value: Any) -> Optional[int]:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except Exception:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp() * 1_000_000_000)

    def _order_metadata_decimal(self, metadata: Dict[str, Any], keys: Tuple[str, ...]) -> Optional[_Decimal]:
        for key in keys:
            value = metadata.get(key)
            if value in (None, ""):
                continue
            try:
                return _Decimal(str(value))
            except Exception:
                continue
        return None

    def _fill_tca_fields(
        self,
        *,
        mapping: ActiveOrderIdMapping,
        quantity: _Decimal,
        price: _Decimal,
        fee: Optional[_Decimal],
        fill_ts_ns: Optional[int],
        order: Optional[OrderRequest],
    ) -> Dict[str, Any]:
        metadata = dict(getattr(order, "metadata", {}) or {}) if order is not None else {}
        net_edge = metadata.get("net_edge_evaluation") if isinstance(metadata.get("net_edge_evaluation"), dict) else {}
        context = metadata.get("net_edge_context") if isinstance(metadata.get("net_edge_context"), dict) else {}
        reference = self._order_metadata_decimal(
            metadata,
            ("modeled_entry_price", "reference_price", "decision_reference_price", "signal_price"),
        )
        if reference is None and order is not None and getattr(order, "limit_price", None) is not None:
            reference = _Decimal(str(order.limit_price))
        modeled_net_edge = self._order_metadata_decimal(
            dict(net_edge),
            ("net_adversarial_edge", "net_edge", "modeled_net_edge"),
        )
        if modeled_net_edge is None:
            modeled_net_edge = self._order_metadata_decimal(
                dict(context),
                ("net_adversarial_edge", "net_edge", "modeled_net_edge"),
            )

        notional = quantity * price
        slippage: Optional[_Decimal] = None
        slippage_bps: Optional[_Decimal] = None
        if reference is not None and reference > 0:
            if str(mapping.side).lower() == "sell":
                slippage = reference - price
            else:
                slippage = price - reference
            slippage_bps = (slippage / reference) * _Decimal("10000")

        fee_bps: Optional[_Decimal] = None
        if fee is not None and notional > 0:
            fee_bps = (fee / notional) * _Decimal("10000")

        decision_ts_ns = int(getattr(order, "exchange_ts_ns", 0) or mapping.submit_ts_ns or 0)
        ack_ts_ns = int(mapping.ack_ts_ns or 0)
        latency_decision_to_ack_ms = None
        latency_ack_to_fill_ms = None
        if decision_ts_ns > 0 and ack_ts_ns > 0 and ack_ts_ns >= decision_ts_ns:
            latency_decision_to_ack_ms = str((ack_ts_ns - decision_ts_ns) / 1_000_000)
        if ack_ts_ns > 0 and fill_ts_ns is not None and fill_ts_ns >= ack_ts_ns:
            latency_ack_to_fill_ms = str((fill_ts_ns - ack_ts_ns) / 1_000_000)

        realized_vs_modeled = None
        if modeled_net_edge is not None and slippage_bps is not None and fee_bps is not None:
            realized_drag = (max(slippage_bps, _Decimal("0")) + fee_bps) / _Decimal("10000")
            realized_vs_modeled = modeled_net_edge - realized_drag

        if slippage_bps is None or fee_bps is None or modeled_net_edge is None:
            tca_status = "UNKNOWN"
            verdict = "UNKNOWN_INSUFFICIENT_BROKER_DETAIL"
        elif slippage_bps > _Decimal("1"):
            tca_status = "HYDRATED"
            verdict = "WORSE_THAN_MODELED"
        elif slippage_bps < _Decimal("-1"):
            tca_status = "HYDRATED"
            verdict = "BETTER_THAN_MODELED"
        else:
            tca_status = "HYDRATED"
            verdict = "IN_LINE"

        return {
            "notional": str(notional),
            "modeled_entry_price": str(reference) if reference is not None else None,
            "modeled_net_edge": str(modeled_net_edge) if modeled_net_edge is not None else None,
            "realized_vs_modeled_netedge": str(realized_vs_modeled) if realized_vs_modeled is not None else None,
            "slippage": str(slippage) if slippage is not None else None,
            "slippage_bps": str(slippage_bps) if slippage_bps is not None else None,
            "fee_bps": str(fee_bps) if fee_bps is not None else None,
            "latency_decision_to_ack_ms": latency_decision_to_ack_ms,
            "latency_ack_to_fill_ms": latency_ack_to_fill_ms,
            "tca_status": tca_status,
            "execution_quality_verdict": verdict,
            "realized_netedge_available": realized_vs_modeled is not None,
        }

    def _hydrate_fill_ledger_from_broker_payload(
        self,
        mapping: ActiveOrderIdMapping,
        payload: Dict[str, Any],
        *,
        source_event: str,
        order: Optional[OrderRequest] = None,
    ) -> Dict[str, Any]:
        """Hydrate fill truth from broker payload/activity without inventing facts."""
        result: Dict[str, Any] = {
            "client_order_id": mapping.client_order_id,
            "broker_order_id": mapping.broker_order_id or mapping.venue_order_id,
            "source_event": source_event,
            "status": "NOT_APPLICABLE",
            "reason_codes": (),
            "inserted": False,
            "legacy_fill_inserted": False,
            "duplicate_ignored": False,
            "tca_status": "UNKNOWN",
            "execution_quality_verdict": "UNKNOWN_INSUFFICIENT_BROKER_DETAIL",
        }
        if self._state_store is None:
            result["status"] = "MISSING_TRUTH"
            result["reason_codes"] = (OmsReasonCode.FILL_LEDGER_UNAVAILABLE.value,)
            self._fill_hydration_results.append(result)
            return result

        broker_order_id = str(mapping.broker_order_id or mapping.venue_order_id or mapping.command_order_id)
        activity = self._matching_broker_fill_activity(
            broker_order_id=broker_order_id,
            client_order_id=mapping.client_order_id,
        )
        activity_payload = activity or {}

        activity_symbol = activity_payload.get("symbol")
        if activity_symbol and self._normalize_broker_symbol(activity_symbol) != self._normalize_broker_symbol(mapping.symbol):
            result["status"] = "CONFLICT"
            result["reason_codes"] = (OmsReasonCode.RECONCILIATION_CONFLICT.value,)
            result["conflict_field"] = "symbol"
            self._fill_hydration_results.append(result)
            logger.info("[OMS_DIAG] FILL_LEDGER_CONFLICT fields=%s", result)
            return result
        activity_side = activity_payload.get("side")
        if activity_side and str(activity_side).strip().lower() != str(mapping.side).strip().lower():
            result["status"] = "CONFLICT"
            result["reason_codes"] = (OmsReasonCode.RECONCILIATION_CONFLICT.value,)
            result["conflict_field"] = "side"
            self._fill_hydration_results.append(result)
            logger.info("[OMS_DIAG] FILL_LEDGER_CONFLICT fields=%s", result)
            return result

        quantity = (
            self._decimal_from_payload(activity_payload, ("qty", "quantity", "filled_qty"))
            or self._decimal_from_payload(payload, ("filled_qty", "filled_quantity", "qty"))
        )
        price = (
            self._decimal_from_payload(activity_payload, ("price", "filled_avg_price", "avg_fill_price"))
            or self._decimal_from_payload(payload, ("filled_avg_price", "avg_fill_price", "filled_price", "price"))
        )
        fee = (
            self._decimal_from_payload(activity_payload, ("commission", "fee", "commission_amount"))
            or self._decimal_from_payload(payload, ("fee", "commission", "commission_amount"))
        )
        fee_currency = str(
            activity_payload.get("fee_currency")
            or activity_payload.get("commission_currency")
            or payload.get("fee_currency")
            or payload.get("commission_currency")
            or ""
        ).strip()
        timestamp = str(
            self._payload_value(activity_payload, ("transaction_time", "filled_at", "updated_at"))
            or self._payload_value(payload, ("filled_at", "updated_at", "transaction_time"))
            or ""
        ).strip()
        missing = []
        if quantity is None or quantity <= 0:
            missing.append("filled_qty")
        if price is None or price <= 0:
            missing.append("filled_avg_price")
        if not timestamp:
            missing.append("timestamp")
        if missing:
            result["status"] = "MISSING_TRUTH"
            result["reason_codes"] = (OmsReasonCode.FILL_LEDGER_UNAVAILABLE.value,)
            result["missing_fields"] = tuple(missing)
            self._fill_hydration_results.append(result)
            logger.info("[OMS_DIAG] FILL_LEDGER_UNAVAILABLE fields=%s", result)
            return result

        broker_activity_id = str(activity_payload.get("id") or activity_payload.get("activity_id") or "").strip() or None
        fill_id = (
            f"broker_activity:{mapping.broker}:{broker_activity_id}"
            if broker_activity_id
            else f"broker_fill:{mapping.broker}:{broker_order_id}:{quantity}:{price}:{timestamp}"
        )
        fill_ts_ns = self._timestamp_ns_from_broker_text(timestamp)
        hydration_status = "HYDRATED" if fee is not None and fee_currency else "PARTIAL"
        hydration_reason = (
            "BROKER_FILL_DETAIL_HYDRATED"
            if hydration_status == "HYDRATED"
            else "BROKER_FILL_FEE_DETAIL_UNAVAILABLE"
        )
        tca_fields = self._fill_tca_fields(
            mapping=mapping,
            quantity=quantity,
            price=price,
            fee=fee,
            fill_ts_ns=fill_ts_ns,
            order=order,
        )
        metadata = dict(getattr(order, "metadata", {}) or {}) if order is not None else {}
        candidate_lifecycle = metadata.get("candidate_lifecycle") if isinstance(metadata.get("candidate_lifecycle"), dict) else {}
        fill_record = {
            "fill_id": fill_id,
            "broker_order_id": broker_order_id,
            "client_order_id": mapping.client_order_id,
            "decision_uuid": getattr(order, "decision_uuid", None) if order is not None else None,
            "frame_id": metadata.get("frame_id"),
            "candidate_id": candidate_lifecycle.get("candidate_id"),
            "snapshot_id": metadata.get("snapshot_id"),
            "symbol": mapping.symbol,
            "side": mapping.side,
            "action": metadata.get("action") or ("sell_to_close" if str(mapping.side).lower() == "sell" else "buy_to_open"),
            "quantity": str(quantity),
            "price": str(price),
            "notional": tca_fields.get("notional"),
            "fill_timestamp": timestamp,
            "fill_ts_ns": fill_ts_ns,
            "broker_activity_id": broker_activity_id,
            "fee": str(fee) if fee is not None else None,
            "fee_currency": fee_currency or None,
            "liquidity_flag": activity_payload.get("liquidity") or activity_payload.get("liquidity_flag"),
            "source": "broker_activity" if activity_payload else "broker_order_status",
            "hydration_status": hydration_status,
            "hydration_reason_code": hydration_reason,
            "tca_status": tca_fields.get("tca_status"),
            "execution_quality_verdict": tca_fields.get("execution_quality_verdict"),
            "modeled_entry_price": tca_fields.get("modeled_entry_price"),
            "modeled_net_edge": tca_fields.get("modeled_net_edge"),
            "realized_vs_modeled_netedge": tca_fields.get("realized_vs_modeled_netedge"),
            "slippage": tca_fields.get("slippage"),
            "slippage_bps": tca_fields.get("slippage_bps"),
            "fee_bps": tca_fields.get("fee_bps"),
            "latency_decision_to_ack_ms": tca_fields.get("latency_decision_to_ack_ms"),
            "latency_ack_to_fill_ms": tca_fields.get("latency_ack_to_fill_ms"),
            "metadata": {
                "source_event": source_event,
                "broker_activity_available": bool(activity_payload),
                "broker_activity_fetch_error": self._broker_fill_activity_fetch_error,
                "order_status": payload.get("status"),
                "net_edge_evaluation": metadata.get("net_edge_evaluation"),
                "net_edge_context": metadata.get("net_edge_context"),
                "fee_status": "FEE_ACTIVITY_MATCHED" if fee is not None and fee_currency else "FEE_PENDING_BROKER_ACTIVITY",
                "fee_source": "BROKER_FILL_ACTIVITY" if fee is not None and fee_currency else "UNAVAILABLE",
                "fee_hydration_reason_code": hydration_reason,
            },
            "created_at_ns": now_ns(),
            "observed_at_ns": now_ns(),
        }
        ledger_status = self._state_store.upsert_broker_fill_ledger(fill_record)
        result.update(
            {
                "status": hydration_status if ledger_status in {"inserted", "duplicate"} else "CONFLICT",
                "reason_codes": () if ledger_status in {"inserted", "duplicate"} else (OmsReasonCode.RECONCILIATION_CONFLICT.value,),
                "hydration_reason_code": hydration_reason,
                "inserted": ledger_status == "inserted",
                "duplicate_ignored": ledger_status == "duplicate",
                "ledger_status": ledger_status,
                "fill_id": fill_id,
                "broker_activity_id": broker_activity_id,
                "quantity": str(quantity),
                "price": str(price),
                "known_broker_terminal_status": str(payload.get("status") or "").lower() or None,
                "fee_available": fee is not None,
                "fee_currency_available": bool(fee_currency),
                "tca_status": tca_fields.get("tca_status"),
                "execution_quality_verdict": tca_fields.get("execution_quality_verdict"),
                "realized_netedge_available": bool(tca_fields.get("realized_netedge_available")),
            }
        )
        if fee is not None and fee_currency:
            legacy_fill_id = f"legacy:{fill_id}"
            legacy_inserted = self._state_store.insert_fill(
                {
                    "id": legacy_fill_id,
                    "order_id": mapping.client_order_id,
                    "symbol": mapping.symbol,
                    "side": mapping.side,
                    "quantity": float(quantity),
                    "price": float(price),
                    "fee": float(fee),
                    "fee_currency": fee_currency,
                    "timestamp": timestamp,
                    "exchange_order_id": broker_order_id,
                    "latency_ms": None,
                }
            )
            result["legacy_fill_inserted"] = bool(legacy_inserted)
        self._fill_hydration_results.append(result)
        logger.info("[OMS_DIAG] FILL_LEDGER_HYDRATION fields=%s", result)
        return result

    def _local_fill_exists_for_order(self, client_order_id: str) -> bool:
        if self._state_store is None:
            return False
        counter = getattr(self._state_store, "count_fills_for_order", None)
        if not callable(counter):
            return False
        return int(counter(client_order_id) or 0) > 0

    def _record_fill_ledger_unavailable(
        self,
        mapping: ActiveOrderIdMapping,
        *,
        source_event: str,
        missing_fields: Tuple[str, ...],
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "client_order_id": mapping.client_order_id,
            "broker_order_id": mapping.broker_order_id or mapping.venue_order_id,
            "source_event": source_event,
            "status": "MISSING_TRUTH",
            "reason_codes": (OmsReasonCode.FILL_LEDGER_UNAVAILABLE.value,),
            "missing_fields": tuple(missing_fields),
            "inserted": False,
        }
        self._fill_hydration_results.append(result)
        logger.info("[OMS_DIAG] FILL_LEDGER_UNAVAILABLE fields=%s", result)
        return result

    def _hydrate_missing_fill_ledger_for_terminal_filled_mappings(
        self,
        mapping_rows: List[Dict[str, Any]],
        *,
        source_event: str,
    ) -> None:
        """Hydrate or explain terminal mappings that broker truth says filled."""
        adapter = self._broker_gateway_adapter
        for row in mapping_rows:
            status = str(row.get("status") or "").strip().lower()
            if status not in {"filled", "partially_filled", "partial_fill", "partial", "canceled", "cancelled"}:
                continue
            mapping = self._mapping_from_record(row)
            if mapping is None:
                continue
            if self._local_fill_exists_for_order(mapping.client_order_id):
                continue
            if adapter is None or not mapping.command_order_id:
                self._record_fill_ledger_unavailable(
                    mapping,
                    source_event=source_event,
                    missing_fields=("broker_order_status",),
                )
                continue
            try:
                status_response = adapter.get_order_status(mapping.command_order_id)
            except BrokerGatewayError:
                self._record_fill_ledger_unavailable(
                    mapping,
                    source_event=source_event,
                    missing_fields=("broker_order_status",),
                )
                continue
            broker_status = str(getattr(status_response, "normalized_status", "") or "")
            payload = status_response.payload if isinstance(status_response.payload, dict) else {}
            broker_state = canonical_state_from_broker_status(broker_status)
            broker_filled_qty = self._decimal_from_payload(payload, ("filled_qty", "filled_quantity", "qty"))
            has_fill_quantity = broker_filled_qty is not None and broker_filled_qty > 0
            if not status_response.ok:
                self._record_fill_ledger_unavailable(
                    mapping,
                    source_event=source_event,
                    missing_fields=("broker_filled_status",),
                )
                continue
            if broker_state not in {OmsOrderState.FILLED.value, OmsOrderState.PARTIALLY_FILLED.value} and not has_fill_quantity:
                if status == "filled":
                    self._record_fill_ledger_unavailable(
                        mapping,
                        source_event=source_event,
                        missing_fields=("broker_filled_status",),
                    )
                continue
            self._hydrate_fill_ledger_from_broker_payload(
                mapping,
                payload,
                source_event=source_event,
            )

    def _resolve_nonterminal_mapping_against_final_broker_truth(
        self,
        mapping: ActiveOrderIdMapping,
        *,
        open_order_ids: set[str],
        source_event: str,
    ) -> Dict[str, Any]:
        evidence: Dict[str, Any] = {
            "client_order_id": mapping.client_order_id,
            "broker_order_id": mapping.broker_order_id or mapping.venue_order_id,
            "source_event": source_event,
            "status": "UNKNOWN",
            "broker_confirmed_open": False,
            "reason_codes": [],
            "mutation_performed": False,
        }
        if self._mapping_matches_broker_open_orders(mapping, open_order_ids):
            evidence["status"] = OmsOrderState.OPEN.value
            evidence["broker_confirmed_open"] = True
            mapping.status = "open"
            if self._state_store is not None:
                mapping.durable = self._state_store.upsert_order_id_mapping(
                    self._mapping_to_store_record(mapping)
                )
            return evidence

        adapter = self._broker_gateway_adapter
        if adapter is None or not mapping.command_order_id:
            evidence["status"] = OmsOrderState.RECONCILIATION_CONFLICT.value
            evidence["reason_codes"].append(OmsReasonCode.BROKER_FINAL_STATE_UNKNOWN.value)
            self._mark_active_order_mapping_terminal_for_broker(
                mapping.client_order_id,
                mapping.broker,
                status="reconciliation_conflict",
                terminal_reason=f"{source_event}_broker_final_state_unknown",
            )
            self._record_oms_state(OmsOrderState.RECONCILIATION_CONFLICT.value)
            return evidence

        try:
            status_response = adapter.get_order_status(mapping.command_order_id)
        except BrokerGatewayError as exc:
            evidence["status"] = OmsOrderState.RECONCILIATION_CONFLICT.value
            evidence["reason_codes"].append(exc.reason_code or OmsReasonCode.BROKER_FINAL_STATE_UNKNOWN.value)
            self._mark_active_order_mapping_terminal_for_broker(
                mapping.client_order_id,
                mapping.broker,
                status="reconciliation_conflict",
                terminal_reason=f"{source_event}_broker_final_state_unknown",
            )
            self._record_oms_state(OmsOrderState.RECONCILIATION_CONFLICT.value)
            return evidence

        evidence["mutation_performed"] = bool(getattr(status_response, "mutation_occurred", False))
        if evidence["mutation_performed"]:
            evidence["reason_codes"].append(OmsReasonCode.RECONCILIATION_CONFLICT.value)
        broker_status = str(getattr(status_response, "normalized_status", "") or "")
        oms_state = canonical_state_from_broker_status(broker_status)
        payload = status_response.payload if isinstance(status_response.payload, dict) else {}
        payload_symbol = payload.get("symbol")
        if payload_symbol and self._normalize_broker_symbol(payload_symbol) != self._normalize_broker_symbol(mapping.symbol):
            evidence["reason_codes"].append(OmsReasonCode.RECONCILIATION_CONFLICT.value)
            oms_state = OmsOrderState.RECONCILIATION_CONFLICT.value
        if not status_response.ok:
            evidence["reason_codes"].append(status_response.reason_code or OmsReasonCode.BROKER_FINAL_STATE_UNKNOWN.value)
            oms_state = OmsOrderState.RECONCILIATION_CONFLICT.value
        elif not is_terminal_oms_state(oms_state):
            evidence["reason_codes"].append(OmsReasonCode.BROKER_FINAL_STATE_UNKNOWN.value)
            oms_state = OmsOrderState.RECONCILIATION_CONFLICT.value

        evidence["status"] = oms_state
        evidence["broker_normalized_status"] = broker_status
        if oms_state in {OmsOrderState.FILLED.value, OmsOrderState.PARTIALLY_FILLED.value} or (
            self._decimal_from_payload(payload, ("filled_qty", "filled_quantity", "qty")) or _Decimal("0")
        ) > 0:
            evidence["fill_hydration"] = self._hydrate_fill_ledger_from_broker_payload(
                mapping,
                payload,
                source_event=source_event,
            )
        terminal_status = "reconciliation_conflict" if oms_state == OmsOrderState.RECONCILIATION_CONFLICT.value else oms_state.lower()
        self._mark_active_order_mapping_terminal_for_broker(
            mapping.client_order_id,
            mapping.broker,
            status=terminal_status,
            terminal_reason=f"{source_event}_terminal_or_unmatched",
        )
        self._record_oms_state(oms_state)
        evidence["reason_codes"] = tuple(dict.fromkeys(evidence["reason_codes"]))
        return evidence

    def _post_ack_gateway_reconciliation(
        self,
        order: OrderRequest,
        response: BrokerGatewayResponse,
    ) -> Dict[str, Any]:
        """Collect broker-canonical read-only truth immediately after an ack."""
        adapter = self._broker_gateway_adapter
        broker_order_id = str(response.broker_order_id or "").strip()
        evidence: Dict[str, Any] = {
            "client_order_id": order.id,
            "broker_order_id": broker_order_id or None,
            "status": "UNKNOWN",
            "reason_codes": [],
            "account_status": "not_checked",
            "open_orders_count": None,
            "positions_count": None,
            "order_id_mapping_present": False,
            "broker_truth_wins_after_ack": True,
            "local_state_authority": "supporting_evidence_only",
            "mutation_performed": False,
        }
        if adapter is None or not broker_order_id:
            evidence["status"] = OmsOrderState.RECONCILIATION_CONFLICT.value
            evidence["reason_codes"].append(OmsReasonCode.BROKER_STATE_UNKNOWN.value)
            self._record_oms_state(OmsOrderState.RECONCILIATION_CONFLICT.value)
            return evidence

        try:
            status_response = adapter.get_order_status(broker_order_id)
            open_orders_response = adapter.get_open_orders()
            positions_response = adapter.get_positions()
            account_response = adapter.get_account()
        except BrokerGatewayError as exc:
            evidence["status"] = OmsOrderState.RECONCILIATION_CONFLICT.value
            evidence["reason_codes"].append(exc.reason_code or OmsReasonCode.BROKER_STATE_UNKNOWN.value)
            self._record_oms_state(OmsOrderState.RECONCILIATION_CONFLICT.value)
            return evidence

        responses = (status_response, open_orders_response, positions_response, account_response)
        evidence["mutation_performed"] = any(bool(getattr(item, "mutation_occurred", False)) for item in responses)
        evidence["account_status"] = (
            str((account_response.payload or {}).get("status"))
            if isinstance(account_response.payload, dict)
            else "unknown"
        )
        open_orders = open_orders_response.payload if isinstance(open_orders_response.payload, list) else []
        positions = positions_response.payload if isinstance(positions_response.payload, list) else []
        evidence["open_orders_count"] = len(open_orders)
        evidence["positions_count"] = len(positions)
        evidence["order_id_mapping_present"] = self._get_active_order_id_mapping(
            order.id,
            self._gateway_order_mapping_broker(),
        ) is not None

        if any(not item.ok for item in responses):
            evidence["reason_codes"].append(OmsReasonCode.BROKER_STATE_UNKNOWN.value)
        if evidence["mutation_performed"]:
            evidence["reason_codes"].append(OmsReasonCode.RECONCILIATION_CONFLICT.value)

        broker_status = str(getattr(status_response, "normalized_status", "") or "")
        oms_state = canonical_state_from_broker_status(broker_status)
        payload = status_response.payload if isinstance(status_response.payload, dict) else {}
        payload_symbol = payload.get("symbol")
        if payload_symbol and self._normalize_broker_symbol(payload_symbol) != self._normalize_broker_symbol(order.symbol):
            evidence["reason_codes"].append(OmsReasonCode.RECONCILIATION_CONFLICT.value)
            oms_state = OmsOrderState.RECONCILIATION_CONFLICT.value

        if not evidence["order_id_mapping_present"]:
            evidence["reason_codes"].append(OmsReasonCode.RECONCILIATION_CONFLICT.value)
            oms_state = OmsOrderState.RECONCILIATION_CONFLICT.value

        evidence["status"] = oms_state
        evidence["broker_normalized_status"] = broker_status
        if oms_state in {OmsOrderState.FILLED.value, OmsOrderState.PARTIALLY_FILLED.value} or (
            self._decimal_from_payload(payload, ("filled_qty", "filled_quantity", "qty")) or _Decimal("0")
        ) > 0:
            mapping = self._get_active_order_id_mapping(order.id, self._gateway_order_mapping_broker())
            if mapping is not None:
                evidence["fill_hydration"] = self._hydrate_fill_ledger_from_broker_payload(
                    mapping,
                    payload,
                    source_event="post_ack_reconciliation",
                    order=order,
                )
        evidence["reason_codes"] = tuple(dict.fromkeys(evidence["reason_codes"]))
        self._gateway_reconciliation_by_client_order_id[order.id] = evidence
        self._record_oms_state(oms_state)
        logger.info("[OMS_DIAG] POST_ACK_RECONCILIATION fields=%s", evidence)
        return evidence

    def _submit_order_gateway(self, order: OrderRequest) -> BrokerGatewayResponse:
        """
        Route an external broker-paper order through the governed gateway.

        The gateway response is canonical broker truth. This method never
        fabricates a fill and never falls back to the simulated PaperBroker.
        """
        request = self._gateway_request_from_order(order)
        self._record_oms_state(OmsOrderState.ROUTER_SUBMITTED.value)
        broker_post_authorized = self._broker_gateway_identity_error() is None
        try:
            response = self._broker_gateway_adapter.submit_order(request)
        except BrokerGatewayError as exc:
            identity = self._broker_gateway_adapter.identity
            response = BrokerGatewayResponse(
                adapter_id=identity.adapter_id,
                venue_id=identity.venue_id,
                portal_id=identity.portal_id,
                environment=identity.environment,
                request_method="POST",
                endpoint_path="/v2/orders",
                ok=False,
                mutation_occurred=False,
                live_blocked=identity.live_blocked,
                client_order_id=order.id,
                normalized_status=_GatewayStatus.REJECTED.value,
                reason_code=exc.reason_code,
                message=exc.message,
                reconciliation_metadata={
                    "source": identity.adapter_id,
                    "blocked_before_submit": True,
                },
            )
        self._gateway_responses_by_client_order_id[order.id] = response
        ack_ts_ns = now_ns()
        blocked_before_submit = bool(
            isinstance(response.reconciliation_metadata, dict)
            and response.reconciliation_metadata.get("blocked_before_submit")
        )
        boundary_result = (
            "BROKER_POST_ACKNOWLEDGED"
            if response.ok and response.broker_order_id
            else ("BROKER_POST_BLOCKED_BEFORE_SUBMIT" if blocked_before_submit else "BROKER_POST_REJECTED")
        )
        self._record_broker_boundary_telemetry(
            order,
            response=response,
            broker_post_attempted=not blocked_before_submit,
            broker_post_authorized=broker_post_authorized,
            broker_boundary_result=boundary_result,
        )

        if response.ok and response.broker_order_id:
            self._register_active_order_id_mapping(
                order,
                broker=response.venue_id,
                venue_order_id=response.broker_order_id,
                broker_order_id=response.broker_order_id,
                exchange_txid=None,
                id_mapping_source=f"{response.adapter_id}.submit_order_response",
                ack_ts_ns=ack_ts_ns,
            )
            self._record_order_lifecycle_telemetry(
                order,
                lifecycle_source=f"{response.adapter_id}.submit_order_response",
                lifecycle_phase="order_acknowledged",
                event_ts_ns=ack_ts_ns,
                ack_seen=True,
                venue_order_id=response.broker_order_id,
                broker_order_id=response.broker_order_id,
                original_qty=order.quantity,
                cumulative_filled_qty=_Decimal("0"),
                remaining_qty=order.quantity,
                cumulative_fee=_Decimal("0"),
                is_terminal=response.normalized_status
                in {
                    _GatewayStatus.FILLED.value,
                    _GatewayStatus.REJECTED.value,
                    _GatewayStatus.CANCELED.value,
                    _GatewayStatus.EXPIRED.value,
                },
                status_source=f"{response.adapter_id}.submit_order_response",
                id_mapping_source=f"{response.adapter_id}.submit_order_response",
                idempotency_key=(
                    f"{order.decision_uuid}:{order.id}:order_acknowledged:"
                    f"{response.broker_order_id}:{ack_ts_ns}:{response.adapter_id}_submit_order"
                ),
            )
            reconciliation = self._post_ack_gateway_reconciliation(order, response)
            oms_state = str(reconciliation.get("status") or canonical_state_from_broker_status(response.normalized_status))
            if response.normalized_status in {_GatewayStatus.ACCEPTED.value, _GatewayStatus.OPEN.value}:
                self._pending_orders[order.id] = order
            if is_terminal_oms_state(oms_state):
                self._pending_orders.pop(order.id, None)
                terminal_status = oms_state.lower()
                if oms_state == OmsOrderState.RECONCILIATION_CONFLICT.value:
                    terminal_status = "reconciliation_conflict"
                self._mark_active_order_mapping_terminal_for_broker(
                    order.id,
                    response.venue_id,
                    status=terminal_status,
                    terminal_reason=(
                        "post_ack_reconciliation_conflict"
                        if oms_state == OmsOrderState.RECONCILIATION_CONFLICT.value
                        else "post_ack_broker_terminal_status"
                    ),
                )
            self._order_status_cache[order.id] = OrderStatus(
                order_id=order.id,
                status=response.normalized_status,
                timestamp_ns=ack_ts_ns,
            )
            return response

        self._order_status_cache[order.id] = OrderStatus(
            order_id=order.id,
            status=response.normalized_status,
            timestamp_ns=ack_ts_ns,
        )
        self._record_rejection_telemetry(order, response.reason_code or response.message or "broker_gateway_rejected")
        self._record_oms_state(OmsOrderState.REJECTED.value)
        return response

    def _gateway_request_from_order(self, order: OrderRequest) -> _GatewayOrderSubmitRequest:
        side = str(getattr(order.side, "value", order.side)).lower()
        order_type = str(getattr(order.order_type, "value", order.order_type)).lower()
        metadata = order.metadata if isinstance(order.metadata, dict) else {}
        time_in_force = str(metadata.get("time_in_force") or metadata.get("tif") or "day")
        asset_class = metadata.get("asset_class")
        return _GatewayOrderSubmitRequest(
            symbol=order.symbol,
            side=side,
            order_type=order_type,
            time_in_force=time_in_force,
            quantity=_Decimal(str(order.quantity)),
            limit_price=_Decimal(str(order.limit_price)) if order.limit_price is not None else None,
            client_order_id=order.id,
            asset_class=str(asset_class) if asset_class is not None else None,
            metadata={
                "decision_uuid": order.decision_uuid,
                "strategy": str(getattr(order.strategy, "value", order.strategy)),
                "execution_adapter": metadata.get("execution_adapter"),
                "portal_name": metadata.get("portal_name"),
                "venue_id": metadata.get("venue_id"),
                "environment": metadata.get("environment"),
            },
        )

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
                    ack_ts_ns = now_ns()
                    self._register_active_order_id_mapping(
                        order,
                        broker="kraken",
                        venue_order_id=order_id,
                        broker_order_id=None,
                        exchange_txid=order_id,
                        id_mapping_source="order_router.kraken_submit_response",
                        ack_ts_ns=ack_ts_ns,
                    )
                    self._record_order_lifecycle_telemetry(
                        order,
                        lifecycle_source="order_router.kraken_submit_response",
                        lifecycle_phase="order_acknowledged",
                        event_ts_ns=ack_ts_ns,
                        ack_seen=True,
                        venue_order_id=order_id,
                        broker_order_id=None,
                        exchange_txid=order_id,
                        original_qty=order.quantity,
                        cumulative_filled_qty=_Decimal("0"),
                        remaining_qty=order.quantity,
                        cumulative_fee=_Decimal("0"),
                        is_terminal=False,
                        status_source="kraken.add_order_response",
                        id_mapping_source="order_router.kraken_submit_response",
                        idempotency_key=(
                            f"{order.decision_uuid}:{order.id}:order_acknowledged:"
                            f"{order_id}:{ack_ts_ns}:kraken_add_order"
                        ),
                    )
                    self._record_reservation_ack_open(
                        order,
                        ack_source="order_router.kraken_submit_response",
                        source_event_id=f"{order_id}:{ack_ts_ns}:kraken_add_order",
                    )
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
                ack_ts_ns = now_ns()
                self._register_active_order_id_mapping(
                    order,
                    broker="alpaca",
                    venue_order_id=order_id,
                    broker_order_id=order_id,
                    exchange_txid=None,
                    id_mapping_source="order_router.alpaca_submit_response",
                    ack_ts_ns=ack_ts_ns,
                )
                self._record_order_lifecycle_telemetry(
                    order,
                    lifecycle_source="order_router.alpaca_submit_response",
                    lifecycle_phase="order_acknowledged",
                    event_ts_ns=ack_ts_ns,
                    ack_seen=True,
                    venue_order_id=order_id,
                    broker_order_id=order_id,
                    original_qty=order.quantity,
                    cumulative_filled_qty=_Decimal("0"),
                    remaining_qty=order.quantity,
                    cumulative_fee=_Decimal("0"),
                    is_terminal=False,
                    status_source="alpaca.submit_order_response",
                    id_mapping_source="order_router.alpaca_submit_response",
                    idempotency_key=(
                        f"{order.decision_uuid}:{order.id}:order_acknowledged:"
                        f"{order_id}:{ack_ts_ns}:alpaca_submit_order"
                    ),
                )
                self._record_reservation_ack_open(
                    order,
                    ack_source="order_router.alpaca_submit_response",
                    source_event_id=f"{order_id}:{ack_ts_ns}:alpaca_submit_order",
                )
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
                    self._record_fill_telemetry(
                        order,
                        fill,
                        venue_fill_id=order_id,
                        venue_order_id=order_id,
                        exchange_txid=order_id,
                        id_mapping_source="kraken.query_order_status",
                    )
                    self._mark_active_order_mapping_terminal(
                        order.id,
                        status="filled",
                        terminal_reason="kraken_query_order_status_closed",
                    )
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
                    self._record_fill_telemetry(
                        order,
                        fill,
                        venue_fill_id=order_id,
                        venue_order_id=order_id,
                        id_mapping_source="alpaca.order_status",
                    )
                    self._mark_active_order_mapping_terminal(
                        order.id,
                        status="filled",
                        terminal_reason="alpaca_order_status_filled",
                    )
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
        if self._should_use_external_paper_gateway():
            return self._cancel_order_external_paper_gateway(order_id)
        if self.paper_mode:
            return self._cancel_order_paper(order_id)

        try:
            if not self._websocket_connected and self.rest_fallback_enabled:
                return self._cancel_order_rest(order_id)

            command_order_id = self._resolve_live_command_order_id(order_id)
            if command_order_id is None:
                return False

            if self.primary_exchange == "kraken":
                success = self._cancel_order_kraken(command_order_id)
                if success:
                    self._mark_active_order_mapping_terminal(
                        order_id,
                        status="cancelled",
                        terminal_reason="kraken_cancel_accepted",
                    )
                return success
            if self.primary_exchange == "alpaca":
                success = self._cancel_order_alpaca(command_order_id)
                if success:
                    self._mark_active_order_mapping_terminal(
                        order_id,
                        status="cancelled",
                        terminal_reason="alpaca_cancel_accepted",
                    )
                return success
            return False
        except Exception as e:
            logger.error("Order cancellation failed: %s", e)
            if self.rest_fallback_enabled:
                return self._cancel_order_rest(order_id)
            return False

    def _record_cancel_denial_once(self, order_id: str, reason_code: str) -> bool:
        if order_id in self._cancel_denials_by_order_id:
            return False
        self._cancel_denials_by_order_id[order_id] = reason_code
        self._oms_lifecycle_counts["cancel_denied"] = int(self._oms_lifecycle_counts.get("cancel_denied", 0)) + 1
        logger.warning(
            "[OMS_DIAG] CANCEL_DENIED fields=%s",
            {
                "client_order_id": order_id,
                "reason_code": reason_code,
                "cancel_authorized": False,
                "broker_command_performed": False,
            },
        )
        return False

    def _cancel_order_external_paper_gateway(self, order_id: str) -> bool:
        """Cancel an acknowledged external PAPER order through broker authority."""
        client_order_id = str(order_id or "").strip()
        if not client_order_id:
            return self._record_cancel_denial_once("", OmsReasonCode.BROKER_STATE_UNKNOWN.value)

        identity_error = self._broker_gateway_identity_error()
        identity = getattr(self._broker_gateway_adapter, "identity", None)
        if identity_error is not None or identity is None:
            return self._record_cancel_denial_once(client_order_id, OmsReasonCode.CAPABILITY_UNAUTHORIZED.value)
        if getattr(identity, "environment", None) != "paper" or getattr(identity, "live_blocked", None) is not True:
            return self._record_cancel_denial_once(client_order_id, OmsReasonCode.LIVE_OR_REAL_MONEY_BLOCKED.value)
        if not hasattr(self._broker_gateway_adapter, "cancel_order"):
            return self._record_cancel_denial_once(client_order_id, OmsReasonCode.CAPABILITY_UNAUTHORIZED.value)

        broker = self._gateway_order_mapping_broker()
        mapping = self._get_active_order_id_mapping(client_order_id, broker)
        if mapping is None or not mapping.command_order_id:
            return self._record_cancel_denial_once(client_order_id, OmsReasonCode.BROKER_STATE_UNKNOWN.value)
        if mapping.is_terminal:
            return self._record_cancel_denial_once(client_order_id, OmsReasonCode.CANCEL_ALREADY_ATTEMPTED.value)

        order = self._pending_orders.get(client_order_id)
        cancel_request_ts_ns = now_ns()
        if order is not None:
            self._record_order_lifecycle_telemetry(
                order,
                lifecycle_source="order_router.gateway_cancel_request",
                lifecycle_phase="cancel_requested",
                event_ts_ns=cancel_request_ts_ns,
                cancel_seen=True,
                venue_order_id=mapping.venue_order_id,
                broker_order_id=mapping.broker_order_id,
                original_qty=order.quantity,
                remaining_qty=order.quantity,
                is_terminal=False,
                status_source="order_router.gateway_cancel_request",
                id_mapping_source=mapping.id_mapping_source,
                idempotency_key=(
                    f"{order.decision_uuid}:{client_order_id}:cancel_requested:"
                    f"{mapping.command_order_id}:{cancel_request_ts_ns}:gateway_cancel_request"
                ),
            )

        try:
            response = self._broker_gateway_adapter.cancel_order(mapping.command_order_id)
        except BrokerGatewayError as exc:
            reason = (
                OmsReasonCode.CANCEL_NOT_FOUND.value
                if str(exc.reason_code).upper() in {"HTTP_404", "BROKER_404"}
                else exc.reason_code
            )
            return self._record_cancel_denial_once(client_order_id, reason or OmsReasonCode.BROKER_STATE_UNKNOWN.value)

        self._record_broker_boundary_telemetry(
            order or SimpleNamespace(
                id=client_order_id,
                symbol=mapping.symbol or "UNKNOWN",
                side=mapping.side or "buy",
                order_type=mapping.order_type or "limit",
                strategy=SleeveType.SECTOR_ROTATION,
                confidence=0.0,
                decision_uuid=None,
                exchange_ts_ns=max(1, int(mapping.submit_ts_ns or cancel_request_ts_ns)),
                receive_ts_ns=max(1, cancel_request_ts_ns),
            ),
            response=response,
            broker_post_attempted=False,
            broker_post_authorized=True,
            broker_boundary_result="BROKER_CANCEL_ACKNOWLEDGED" if response.ok else "BROKER_CANCEL_REJECTED",
            reason_code=response.reason_code,
        )

        if not response.ok:
            reason = response.reason_code or OmsReasonCode.BROKER_STATE_UNKNOWN.value
            if reason == "HTTP_404":
                reason = OmsReasonCode.CANCEL_NOT_FOUND.value
            return self._record_cancel_denial_once(client_order_id, reason)

        self._oms_lifecycle_counts["cancel_authorized"] = int(self._oms_lifecycle_counts.get("cancel_authorized", 0)) + 1
        self._pending_orders.pop(client_order_id, None)
        self._order_status_cache[client_order_id] = OrderStatus(
            order_id=client_order_id,
            status="canceled",
            timestamp_ns=now_ns(),
        )
        self._mark_active_order_mapping_terminal_for_broker(
            client_order_id,
            broker,
            status="canceled",
            terminal_reason="gateway_cancel_acknowledged",
        )
        if order is not None:
            event_ts_ns = now_ns()
            self._record_order_lifecycle_telemetry(
                order,
                lifecycle_source=f"{response.adapter_id}.cancel_order_response",
                lifecycle_phase="order_canceled",
                event_ts_ns=event_ts_ns,
                cancel_seen=True,
                terminal_state="canceled",
                terminal_reason="gateway_cancel_acknowledged",
                venue_order_id=mapping.venue_order_id,
                broker_order_id=mapping.broker_order_id,
                original_qty=order.quantity,
                remaining_qty=_Decimal("0"),
                is_terminal=True,
                status_source=f"{response.adapter_id}.cancel_order_response",
                id_mapping_source=mapping.id_mapping_source,
                idempotency_key=(
                    f"{order.decision_uuid}:{client_order_id}:order_canceled:"
                    f"{mapping.command_order_id}:{event_ts_ns}:gateway_cancel_response"
                ),
            )
        logger.info(
            "[OMS_DIAG] CANCEL_ACKNOWLEDGED fields=%s",
            {
                "client_order_id": client_order_id,
                "broker_order_id": mapping.broker_order_id,
                "cancel_authorized": True,
                "broker_command_performed": True,
                "reason_code": "CANCEL_ACKNOWLEDGED",
            },
        )
        return True

    def _cancel_order_paper(self, order_id: str) -> bool:
        """Cancel paper order through sovereign paper broker when available."""
        logger.info("PAPER MODE: Cancelling order %s", order_id)
        order = self._pending_orders.get(order_id)
        paper_order = self._paper_broker.open_orders.get(order_id) if self._paper_broker else None
        broker_order_id = str(paper_order.order_id) if paper_order is not None else None
        cancel_request_ts_ns = now_ns()
        if order is not None:
            self._record_order_lifecycle_telemetry(
                order,
                lifecycle_source="order_router.cancel_request",
                lifecycle_phase="cancel_requested",
                event_ts_ns=cancel_request_ts_ns,
                cancel_seen=True,
                venue_order_id=broker_order_id,
                broker_order_id=broker_order_id,
                original_qty=order.quantity,
                remaining_qty=paper_order.remaining_quantity if paper_order is not None else None,
                is_terminal=False,
                status_source="order_router.cancel_request",
                id_mapping_source=(
                    "paper_broker.open_orders" if broker_order_id is not None else "order_router.client_order_id"
                ),
                idempotency_key=self._paper_lifecycle_idempotency_key(
                    order,
                    lifecycle_phase="cancel_requested",
                    broker_order_id=broker_order_id,
                    event_ts_ns=cancel_request_ts_ns,
                    source_event_id="cancel_request",
                ),
            )
        self._pending_orders.pop(order_id, None)

        if self._paper_broker and order_id in self._paper_broker.open_orders:
            try:
                report = self._paper_broker.cancel_order(order_id, now_ns())
                if order is not None and report is not None:
                    report_status = getattr(report, "status", None)
                    report_ts_ns = int(getattr(report, "timestamp_ns", 0) or now_ns())
                    report_broker_id = str(getattr(report, "order_id", "")) or broker_order_id
                    if report_status == _pb_enums.OrderStatus.CANCELLED:
                        idempotency_key = self._paper_lifecycle_idempotency_key(
                            order,
                            lifecycle_phase="order_canceled",
                            broker_order_id=report_broker_id,
                            event_ts_ns=report_ts_ns,
                            source_event_id="cancel_report",
                        )
                        self._record_order_lifecycle_telemetry(
                            order,
                            lifecycle_source="order_router.paper_cancel_report",
                            lifecycle_phase="order_canceled",
                            event_ts_ns=report_ts_ns,
                            cancel_seen=True,
                            terminal_state="canceled",
                            terminal_reason="paper_broker_cancelled",
                            venue_order_id=report_broker_id,
                            broker_order_id=report_broker_id,
                            original_qty=order.quantity,
                            remaining_qty=paper_order.remaining_quantity if paper_order is not None else None,
                            is_terminal=True,
                            status_source="paper_broker.cancel_order",
                            id_mapping_source="paper_broker.execution_report",
                            idempotency_key=idempotency_key,
                        )
                        self._record_reservation_terminal_non_fill(
                            order,
                            release_idempotency_key=f"{idempotency_key}:release",
                            terminal_status="cancelled",
                            terminal_source="paper_broker.cancel_order",
                            terminal_reason="paper_broker_cancelled",
                            source_event_id="cancel_report",
                        )
                    elif report_status == _pb_enums.OrderStatus.REJECTED:
                        self._record_order_lifecycle_telemetry(
                            order,
                            lifecycle_source="order_router.paper_cancel_report",
                            lifecycle_phase="cancel_rejected",
                            event_ts_ns=report_ts_ns,
                            cancel_seen=True,
                            terminal_state=None,
                            terminal_reason=None,
                            venue_order_id=report_broker_id,
                            broker_order_id=report_broker_id,
                            original_qty=order.quantity,
                            remaining_qty=paper_order.remaining_quantity if paper_order is not None else None,
                            is_terminal=False,
                            status_source="paper_broker.cancel_order",
                            id_mapping_source="paper_broker.execution_report",
                            idempotency_key=self._paper_lifecycle_idempotency_key(
                                order,
                                lifecycle_phase="cancel_rejected",
                                broker_order_id=report_broker_id,
                                event_ts_ns=report_ts_ns,
                                source_event_id="cancel_report",
                            ),
                        )
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
        command_order_id = self._resolve_live_command_order_id(order_id)
        if command_order_id is None:
            return False
        if self.primary_exchange == "kraken":
            success = self._cancel_order_kraken(command_order_id)
            if success:
                self._mark_active_order_mapping_terminal(
                    order_id,
                    status="cancelled",
                    terminal_reason="kraken_cancel_accepted",
                )
            return success
        if self.primary_exchange == "alpaca":
            success = self._cancel_order_alpaca(command_order_id)
            if success:
                self._mark_active_order_mapping_terminal(
                    order_id,
                    status="cancelled",
                    terminal_reason="alpaca_cancel_accepted",
                )
            return success
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
        if self.paper_mode and self._should_use_external_paper_gateway():
            return self._query_external_paper_gateway_order_status(order_id)
        if self.paper_mode:
            self._sync_paper_reports()
            if order_id in self._order_status_cache:
                return self._order_status_cache[order_id].status
            if order_id in self._pending_orders:
                return "pending"
            return "cancelled"

        if self.primary_exchange == "kraken":
            mapping = self._get_active_order_id_mapping(order_id, "kraken")
            if mapping is not None and mapping.is_terminal:
                return mapping.status
            command_order_id = self._resolve_live_command_order_id(order_id)
            if command_order_id is None:
                return "unknown"
            status = self._query_kraken_order_status(command_order_id)
            if status in {"filled", "cancelled", "expired", "rejected"}:
                self._mark_active_order_mapping_terminal(
                    order_id,
                    status=status,
                    terminal_reason="kraken_status_terminal",
                )
            return status
        if self.primary_exchange == "alpaca":
            mapping = self._get_active_order_id_mapping(order_id, "alpaca")
            if mapping is not None and mapping.is_terminal:
                return mapping.status
            command_order_id = self._resolve_live_command_order_id(order_id)
            if command_order_id is None:
                return "unknown"
            status = self._query_alpaca_order_status(command_order_id)
            if status in {"filled", "cancelled", "expired", "rejected"}:
                self._mark_active_order_mapping_terminal(
                    order_id,
                    status=status,
                    terminal_reason="alpaca_status_terminal",
                )
            return status
        return "unknown"

    def _query_external_paper_gateway_order_status(self, client_order_id: str) -> str:
        broker = self._gateway_order_mapping_broker()
        mapping = self._get_active_order_id_mapping(client_order_id, broker)
        if mapping is None or not mapping.command_order_id:
            return "unknown"
        if mapping.is_terminal:
            return mapping.status
        try:
            response = self._broker_gateway_adapter.get_order_status(mapping.command_order_id)
        except BrokerGatewayError as exc:
            logger.warning(
                "[OMS_DIAG] BROKER_STATUS_UNKNOWN fields=%s",
                {
                    "client_order_id": client_order_id,
                    "broker": broker,
                    "reason_code": exc.reason_code or OmsReasonCode.BROKER_STATE_UNKNOWN.value,
                    "broker_command_performed": False,
                },
            )
            return "unknown"
        status = str(response.normalized_status or "unknown")
        if status in {"filled", "canceled", "cancelled", "expired", "rejected"}:
            self._mark_active_order_mapping_terminal_for_broker(
                client_order_id,
                broker,
                status=status,
                terminal_reason="gateway_status_terminal",
            )
            self._pending_orders.pop(client_order_id, None)
        return status

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
            "market_data_latency_source": self._market_data_latency_source,
            "rest_market_data_rtt_ms": self.get_rest_market_data_rtt_ms(),
            "rest_market_data_provider_id": self._last_rest_market_data_provider_id,
            "rest_market_data_exchange": self._last_rest_market_data_exchange,
            "paper_mode": self.paper_mode,
            "execution_broker": self.execution_broker,
            "external_paper_broker_requested": self._external_paper_broker_requested,
            "broker_gateway_adapter": getattr(getattr(self._broker_gateway_adapter, "identity", None), "adapter_id", None),
            "broker_gateway_route_available": self._should_use_external_paper_gateway(),
            "pending_orders_count": len(self._pending_orders),
            "paper_status_cache_size": len(self._order_status_cache) if self.paper_mode else 0,
        }
