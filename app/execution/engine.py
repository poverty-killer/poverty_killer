"""
Execution Engine - The "Body" of the Poverty Killer
SOVEREIGN GRADE - Execution-layer bounded hardening pass

This module is the active execution body on the live spine:
    main.py:SovereignHeartbeat -> MainLoop -> ExecutionEngine -> OrderRouter

This hardening pass preserves the existing execution architecture while removing
execution-side dishonesty from the active path:
- process_events() is now a truthful compatibility surface, not fake work
- wall-clock datetimes are removed from active execution decisions
- queue TTL / recalibration timing now uses canonical now_ns()
- pending-order age checks now use authoritative order timestamps when available
- remaining wall-clock behavior is limited to sleep-based thread pacing only

Preserved live responsibilities:
- Signal queueing and validation
- Queue TTL rejection
- Price sanity rejection
- Regime drift rejection
- Data-health gating
- Fire-and-forget emergency liquidation
- Normal-mode PCV cancellation
- Zombie sweep / monitor / executor background loops

BUNDLE F1 Ã¢â‚¬â€ TELEMETRY INTEGRATION
- Added telemetry_store parameter
- Pass telemetry_store to OrderRouter
"""

import concurrent.futures
import logging
import math
import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from app.brain.data_validator import DataContinuityValidator
from app.commander import Commander
from app.core.market_snapshot import validate_market_snapshot_for_execution
from app.execution.masking_layer import MaskingLayer
from app.execution.oms_lifecycle import OmsReasonCode
from app.execution.order_router import OrderRouter
from app.models import OrderFill, OrderRequest, StrategySignal
from app.models.contracts import DecisionRecord, EventEnvelope
from app.models.enums import EventType
from app.risk.guard import HybridRiskGuard
from app.risk.net_edge_governor import (
    AdversarialBurdens,
    CandidateContext,
    CandidateType,
    EconomicDecision,
    ExecutionEconomics,
    NetEdgeGovernor,
)
from app.risk.trade_efficiency_governor import TradeEfficiencyGovernor
from app.utils.time_utils import now_ns
from app.telemetry.event_store import TelemetryEventStore

logger = logging.getLogger(__name__)

NS_PER_SECOND = 1_000_000_000
NS_PER_MS = 1_000_000
ECONOMIC_NET_PROFIT_FLOOR = Decimal("0.005")
_BPS_DIVISOR = Decimal("10000")
_DEFAULT_MODELED_FEE_BPS = Decimal("6.0")
_DEFAULT_MODELED_SPREAD_BPS = Decimal("10.0")
_DEFAULT_MODELED_SLIPPAGE_BPS = Decimal("8.0")
_DEFAULT_MODELED_LATENCY_DRAG_BPS = Decimal("4.0")
_DEFAULT_MODELED_PARTIAL_FILL_BPS = Decimal("4.0")
_DEFAULT_MODELED_EXIT_COST_BPS = Decimal("4.0")


@dataclass(slots=True)
class ExecutionState:
    """Current execution state."""
    is_running: bool = False
    is_in_safe_mode: bool = False
    safe_mode_entered_at_ns: int = 0
    last_latency_ok_at_ns: int = 0
    safe_mode_recovery_state: str = "normal"
    is_in_recalibration: bool = False
    recalibration_until_ns: int = 0
    last_latency_ms: float = 0.0
    last_latency_truth: Dict[str, Any] = field(default_factory=dict)
    pending_orders: Dict[str, OrderRequest] = field(default_factory=dict)
    filled_orders: List[OrderFill] = field(default_factory=list)
    last_health_check_ns: int = 0
    last_equity: float = 0.0
    last_regime: str = "unknown"
    is_emergency_liquidation_in_progress: bool = False


@dataclass(slots=True)
class QueuedSignal:
    """Signal stored in execution queue with deterministic metadata."""
    signal: StrategySignal
    is_attack: bool
    enqueue_time_ns: int
    enqueue_price: Decimal
    enqueue_regime: str
    decision_uuid: Optional[str] = None


@dataclass(frozen=True, slots=True)
class ExecutionSpineResult:
    """Normalized result returned by the governed decision-to-router spine."""
    decision_uuid: Optional[str]
    client_order_id: Optional[str]
    broker_order_id: Optional[str]
    normalized_status: str
    route: str
    reason_code: Optional[str] = None
    message: Optional[str] = None
    fill: Optional[OrderFill] = None
    gateway_response: Optional[Any] = None
    decision_artifact: Optional[Dict[str, Any]] = None
    pre_trade_guardrail_verdict: Optional[Dict[str, Any]] = None
    block_evidence: Optional[Dict[str, Any]] = None
    candidate_lifecycle: Optional[Dict[str, Any]] = None


@dataclass(frozen=True, slots=True)
class LatencyTruthResult:
    """Classified latency truth at the execution safety boundary."""

    status: str
    reason_code: str
    latency_ms: Optional[float]
    threshold_ms: float
    source: str
    safe_mode_required: bool
    missing_source: Optional[str] = None
    staleness_ms: Optional[float] = None
    source_scope: str = "unknown"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "reason_code": self.reason_code,
            "latency_ms": self.latency_ms,
            "threshold_ms": self.threshold_ms,
            "source": self.source,
            "safe_mode_required": self.safe_mode_required,
            "missing_source": self.missing_source,
            "staleness_ms": self.staleness_ms,
            "source_scope": self.source_scope,
        }


def _latency_source_scope(source: str, measurement: Dict[str, Any]) -> str:
    normalized = str(source or "").strip().lower()
    feed_type = str(measurement.get("feed_type") or "").strip().lower()
    if normalized in {"market_data.candle_rtt", "market_data_candle_rtt"}:
        return "market_data_candle_rtt"
    if normalized in {"market_data.book_rtt", "market_data_book_rtt"}:
        return "market_data_book_rtt"
    if normalized == "market_data.rest_polling_rtt":
        if "candle" in feed_type:
            return "market_data_candle_rtt"
        if "book" in feed_type:
            return "market_data_book_rtt"
        return "market_data_rest_polling_rtt"
    if normalized in {"broker.order_rtt", "broker_order_rtt", "order_router.broker_order_rtt"}:
        return "broker_order_rtt"
    if normalized in {"system.loop_lag", "system_loop_lag"}:
        return "system_loop_lag"
    if normalized in {"order_router.websocket_rtt", "websocket_rtt"}:
        return "websocket_rtt"
    return normalized.replace(".", "_") or "unknown"


def _decimal_from_any(value: Any, *, field_name: str) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception as exc:
        raise ValueError(f"{field_name} missing or invalid") from exc


def _decimal_or_default(value: Any, default: Decimal) -> Decimal:
    if value is None:
        return default
    try:
        candidate = Decimal(str(value))
    except Exception:
        return default
    if not candidate.is_finite() or candidate < Decimal("0"):
        return default
    return candidate


def _bps_to_fraction(value: Decimal) -> Decimal:
    return value / _BPS_DIVISOR


def _expected_move_fraction(
    metadata: Dict[str, Any],
    supplied: Dict[str, Any],
) -> Optional[Decimal]:
    for key in ("expected_move", "expected_move_fraction"):
        value = supplied.get(key, metadata.get(key))
        if value is None:
            continue
        try:
            candidate = Decimal(str(value))
        except Exception:
            continue
        if candidate > Decimal("0"):
            return candidate
    for key in ("expected_move_bps", "gross_edge_bps"):
        value = supplied.get(key, metadata.get(key))
        if value is None:
            continue
        try:
            candidate = Decimal(str(value)) / _BPS_DIVISOR
        except Exception:
            continue
        if candidate > Decimal("0"):
            return candidate
    return None


class ExecutionEngine:
    """
    Tactical Execution Engine - Sovereign Grade.

    Hardening status for this bundle:
    - process_events(): truthful compatibility surface
    - active-path timing: canonical now_ns()
    - queue TTL / recalibration timing: replay-safe relative to canonical time source
    - sleep() remains only as non-authoritative thread pacing
    
    BUNDLE F1: Added telemetry_store parameter for fill/rejection recording.
    """

    def __init__(
        self,
        commander: Commander,
        risk_guard: HybridRiskGuard,
        order_router: OrderRouter,
        masking_layer: MaskingLayer,
        data_validator: Optional[DataContinuityValidator] = None,
        signal_ttl_ms: float = 500.0,
        price_sanity_threshold_pct: float = 0.02,
        zombie_sweep_interval_sec: float = 5.0,
        max_pending_age_sec: float = 5.0,
        lag_threshold_ms: float = 200.0,
        recalibration_pause_sec: float = 14400.0,
        maker_offset_pct: float = 0.001,
        emergency_cancel_workers: int = 10,
        telemetry_store: Optional[TelemetryEventStore] = None,
        shadow_read_only: bool = False,
        trade_efficiency_governor: Optional[TradeEfficiencyGovernor] = None,
        net_edge_governor: Optional[NetEdgeGovernor] = None,
    ):
        self.commander = commander
        self.risk_guard = risk_guard
        self.order_router = order_router
        self.masking_layer = masking_layer
        self.data_validator = data_validator
        self.telemetry_store = telemetry_store

        self.signal_ttl_ms = signal_ttl_ms
        self.price_sanity_threshold_pct = Decimal(str(price_sanity_threshold_pct))
        self.zombie_sweep_interval_sec = zombie_sweep_interval_sec
        self.max_pending_age_sec = max_pending_age_sec
        self.lag_threshold_ms = lag_threshold_ms
        self.recalibration_pause_sec = recalibration_pause_sec
        self.maker_offset_pct = Decimal(str(maker_offset_pct))
        self.emergency_cancel_workers = emergency_cancel_workers
        self.shadow_read_only = bool(shadow_read_only)
        self.trade_efficiency_governor = trade_efficiency_governor or TradeEfficiencyGovernor()
        self.net_edge_governor = net_edge_governor or NetEdgeGovernor(self.trade_efficiency_governor)

        self._signal_ttl_ns = int(max(0.0, signal_ttl_ms) * NS_PER_MS)
        self._recalibration_pause_ns = int(max(0.0, recalibration_pause_sec) * NS_PER_SECOND)
        self._max_pending_age_ns = int(max(0.0, max_pending_age_sec) * NS_PER_SECOND)

        self._state = ExecutionState()
        self._execution_queue: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._shadow_read_only_events: List[Dict[str, Any]] = []
        self._shadow_broker_mutation_counts: Dict[str, int] = {
            "POST": 0,
            "PATCH": 0,
            "DELETE": 0,
            "cancel": 0,
            "replace": 0,
            "sell": 0,
            "rebalance": 0,
        }
        self._last_admission_block_result: Optional[ExecutionSpineResult] = None
        self._cancel_attempted_order_ids: set[str] = set()
        self._zombie_sweeper_errors: int = 0
        self._sweeper_thread: Optional[threading.Thread] = None
        self._monitor_thread: Optional[threading.Thread] = None
        self._executor_thread: Optional[threading.Thread] = None
        self._emergency_executor: Optional[concurrent.futures.ThreadPoolExecutor] = None

        self.risk_guard.register_recalibrate_callback(self._on_recalibration)
        self.risk_guard.register_emergency_callback(self._on_emergency)
        self.risk_guard.register_zombie_callback(self._on_zombie_detected)
        self.risk_guard.register_lag_callback(self._on_lag_detected)
        self.risk_guard.register_vol_fuse_callback(self._on_vol_fuse)

        logger.info(
            "ExecutionEngine initialized: signal_ttl=%sms, price_sanity=%.1f%%, emergency_workers=%d, maker_offset=%.2f%%",
            signal_ttl_ms,
            price_sanity_threshold_pct * 100.0,
            emergency_cancel_workers,
            maker_offset_pct * 100.0,
        )

    # ============================================
    # PUBLIC METHODS
    # ============================================

    def start(self) -> None:
        """Start execution engine background threads."""
        if self._state.is_running:
            return

        self._state.is_running = True
        self._state.last_health_check_ns = now_ns()

        self._sweeper_thread = threading.Thread(target=self._zombie_sweeper_loop, daemon=True)
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._executor_thread = threading.Thread(target=self._executor_loop, daemon=True)

        self._sweeper_thread.start()
        self._monitor_thread.start()
        self._executor_thread.start()

        logger.info("ExecutionEngine started")

    def stop(self) -> None:
        """Stop execution engine."""
        self._state.is_running = False
        if self._emergency_executor:
            self._emergency_executor.shutdown(wait=False)
        logger.info("ExecutionEngine stopped")

    def process_events(self) -> None:
        """
        Truthful compatibility surface.

        The live engine processes queued execution asynchronously in
        _executor_loop() after start(). There is no separate synchronous event
        pump to run here. This method intentionally performs no execution work
        and exists only so higher-level heartbeat/support code can call it
        without introducing a second execution authority.
        """
        return

    def get_shadow_read_only_events(self) -> Tuple[Dict[str, Any], ...]:
        """Return in-memory shadow broker-mutation blocks for diagnostics/tests."""
        with self._lock:
            return tuple(dict(event) for event in self._shadow_read_only_events)

    def get_shadow_broker_mutation_counts(self) -> Dict[str, int]:
        """Return broker mutation counts proven by the shadow gate."""
        with self._lock:
            return dict(self._shadow_broker_mutation_counts)

    def get_oms_shutdown_accounting(self) -> Dict[str, Any]:
        """Return execution/router OMS accounting for shutdown diagnostics."""
        router_accounting: Dict[str, Any] = {}
        getter = getattr(self.order_router, "get_oms_shutdown_accounting", None)
        if callable(getter):
            router_accounting = getter()
        with self._lock:
            pending_count = len(self._state.pending_orders)
            pending_ids = tuple(self._state.pending_orders.keys())
            zombie_sweeper_errors = int(self._zombie_sweeper_errors)
            cancel_attempted_count = len(self._cancel_attempted_order_ids)
        result = dict(router_accounting)
        result["engine_pending_orders"] = pending_count
        result["engine_pending_order_ids"] = pending_ids
        result["zombie_sweeper_errors"] = zombie_sweeper_errors
        result["zombie_cancel_attempted_count"] = cancel_attempted_count
        return result

    def get_last_admission_block_result(self) -> Optional[ExecutionSpineResult]:
        """Return the last pre-router signal admission block, if any."""
        return self._last_admission_block_result

    def update_equity(self, current_equity: float) -> None:
        """Update current equity for risk tracking."""
        with self._lock:
            self._state.last_equity = current_equity
        self.risk_guard.update_equity_history(current_equity)

    def update_regime(self, regime: str) -> None:
        """Update current regime for stale signal detection."""
        with self._lock:
            self._state.last_regime = regime

    def submit_signal(
        self,
        signal: StrategySignal,
        current_price: Decimal,
        is_attack: bool,
        decision_uuid: Optional[str] = None,
        decision_record: Optional[DecisionRecord] = None,
    ) -> bool:
        """
        Submit a trading signal for execution.

        Queue admission uses canonical now_ns() and explicit state gating.
        """
        self._last_admission_block_result = None
        resolved_decision_uuid = decision_uuid
        if resolved_decision_uuid is None and isinstance(signal.metadata, dict):
            candidate = signal.metadata.get("decision_uuid")
            if isinstance(candidate, str) and candidate.strip():
                resolved_decision_uuid = candidate.strip()

        if decision_record is not None and isinstance(signal.metadata, dict):
            decision_artifact = self._decision_artifact_summary(decision_record)
            artifact_uuid = decision_artifact.get("decision_uuid")
            if resolved_decision_uuid is None and isinstance(artifact_uuid, str) and artifact_uuid.strip():
                resolved_decision_uuid = artifact_uuid.strip()
            signal.metadata.setdefault("decision_uuid", resolved_decision_uuid)
            signal.metadata["compiled_decision_artifact"] = decision_artifact
            guardrail_verdict = self._extract_pre_trade_guardrail_verdict(decision_artifact)
            if guardrail_verdict is not None:
                signal.metadata.setdefault("pre_trade_guardrail_verdict", guardrail_verdict)

        decision_artifact = (
            self._decision_artifact_summary(decision_record)
            if decision_record is not None
            else None
        )
        guardrail_verdict = self._normalized_pre_trade_guardrail_verdict(signal)

        if not self._state.is_running:
            return self._record_admission_block(
                signal=signal,
                decision_uuid=resolved_decision_uuid,
                reason_code="EXECUTION_ENGINE_NOT_RUNNING",
                message="ExecutionEngine is not running.",
                decision_artifact=decision_artifact,
                guardrail_verdict=guardrail_verdict,
            )

        current_ns = now_ns()

        if self._state.is_in_recalibration:
            if self._state.recalibration_until_ns > 0 and current_ns < self._state.recalibration_until_ns:
                return self._record_admission_block(
                    signal=signal,
                    decision_uuid=resolved_decision_uuid,
                    reason_code="RECALIBRATION_ACTIVE",
                    message="ExecutionEngine recalibration gate blocked signal admission.",
                    decision_artifact=decision_artifact,
                    guardrail_verdict=guardrail_verdict,
                )
            self._state.is_in_recalibration = False
            self._state.recalibration_until_ns = 0

        if self._state.is_in_safe_mode:
            return self._record_admission_block(
                signal=signal,
                decision_uuid=resolved_decision_uuid,
                reason_code="SAFE_MODE_ACTIVE",
                message="ExecutionEngine safe-mode gate blocked signal admission.",
                decision_artifact=decision_artifact,
                guardrail_verdict=guardrail_verdict,
                block_evidence=self._safe_mode_block_evidence(),
            )

        if not self.risk_guard.can_trade():
            return self._record_admission_block(
                signal=signal,
                decision_uuid=resolved_decision_uuid,
                reason_code="RISK_GUARD_BLOCKED",
                message="Risk guard blocked signal admission.",
                decision_artifact=decision_artifact,
                guardrail_verdict=guardrail_verdict,
            )

        if self.risk_guard.is_vol_fuse_triggered():
            return self._record_admission_block(
                signal=signal,
                decision_uuid=resolved_decision_uuid,
                reason_code="VOL_FUSE_TRIGGERED",
                message="Volatility fuse blocked signal admission.",
                decision_artifact=decision_artifact,
                guardrail_verdict=guardrail_verdict,
            )

        data_health_evidence = self._data_health_block_evidence(signal, current_ns=current_ns)
        if data_health_evidence and data_health_evidence.get("data_healthy") is not True:
            return self._record_admission_block(
                signal=signal,
                decision_uuid=resolved_decision_uuid,
                reason_code="DATA_UNHEALTHY",
                message="Data validator blocked signal admission.",
                decision_artifact=decision_artifact,
                guardrail_verdict=guardrail_verdict,
                block_evidence=data_health_evidence,
            )

        net_edge_evaluation = self.evaluate_signal_net_edge(
            signal,
            current_ns=current_ns,
            current_price=current_price,
        )
        if net_edge_evaluation.get("admissible") is not True:
            return self._record_admission_block(
                signal=signal,
                decision_uuid=resolved_decision_uuid,
                reason_code="ECONOMIC_ADMISSIBILITY_BLOCKED",
                message="Execution economic admissibility gate blocked signal admission.",
                decision_artifact=decision_artifact,
                guardrail_verdict=guardrail_verdict,
                block_evidence=net_edge_evaluation,
            )

        guardrail_signal_mismatch = self._pre_trade_guardrail_signal_mismatch_evidence(
            signal,
            guardrail_verdict,
        )
        if guardrail_signal_mismatch is not None:
            return self._record_admission_block(
                signal=signal,
                decision_uuid=resolved_decision_uuid,
                reason_code="PRE_TRADE_GUARDRAIL_SIGNAL_MISMATCH",
                message="Pre-trade guardrail does not authorize this signal symbol/side.",
                decision_artifact=decision_artifact,
                guardrail_verdict=guardrail_verdict,
                block_evidence=guardrail_signal_mismatch,
            )

        if guardrail_verdict is not None and guardrail_verdict.get("route_permitted") is not True:
            logger.info(
                "[EXEC_DIAG] PRE_TRADE_GUARDRAIL_BLOCKED: symbol=%s verdict=%s reasons=%s",
                signal.symbol,
                guardrail_verdict.get("verdict"),
                guardrail_verdict.get("reason_codes"),
            )
            return self._record_admission_block(
                signal=signal,
                decision_uuid=resolved_decision_uuid,
                reason_code="PRE_TRADE_GUARDRAIL_BLOCKED",
                message="Pre-trade guardrail blocked signal admission before OrderRouter.",
                decision_artifact=decision_artifact,
                guardrail_verdict=guardrail_verdict,
            )

        signal_metadata = signal.metadata if isinstance(signal.metadata, dict) else {}
        if (
            guardrail_verdict is None
            and signal_metadata.get("execution_adapter") == "alpaca_paper_rest"
        ):
            self._last_admission_block_result = ExecutionSpineResult(
                decision_uuid=resolved_decision_uuid,
                client_order_id=None,
                broker_order_id=None,
                normalized_status="blocked",
                route="execution_engine",
                reason_code="PRE_TRADE_GUARDRAIL_MISSING",
                message="External Alpaca PAPER route requires a pre-trade guardrail verdict before broker routing.",
                decision_artifact=(
                    self._decision_artifact_summary(decision_record)
                    if decision_record is not None
                    else None
                ),
                pre_trade_guardrail_verdict=None,
            )
            return False

        if self.shadow_read_only:
            self._last_admission_block_result = self._record_shadow_read_only_block(
                signal=signal,
                current_price=current_price,
                is_attack=is_attack,
                decision_uuid=resolved_decision_uuid,
                decision_record=decision_record,
                guardrail_verdict=guardrail_verdict,
            )
            return False

        queued_signal = QueuedSignal(
            signal=signal,
            decision_uuid=resolved_decision_uuid,
            is_attack=is_attack,
            enqueue_time_ns=current_ns,
            enqueue_price=current_price if isinstance(current_price, Decimal) else Decimal(str(current_price)),
            enqueue_regime=self._state.last_regime,
        )

        self._execution_queue.put(queued_signal)
        logger.info(
            "[EXEC_DIAG] SIGNAL_SUBMITTED: strategy=%s symbol=%s side=%s qty=%s",
            signal.strategy,
            signal.symbol,
            signal.side,
            signal.quantity,
        )
        return True

    def execute_compiled_decision(
        self,
        decision_record: DecisionRecord,
        signal: StrategySignal,
        current_price: Decimal,
        is_attack: bool,
    ) -> ExecutionSpineResult:
        """
        Synchronously execute a compiled decision through the governed spine.

        DecisionRecord remains the immutable decision artifact, submit_signal()
        performs the same admission used by the active dispatch route, and
        _execute_signal() routes only through OrderRouter.submit_order().
        """
        decision_uuid = getattr(decision_record, "decision_uuid", None)
        decision_artifact = self._decision_artifact_summary(decision_record)
        guardrail_verdict = self._extract_pre_trade_guardrail_verdict(decision_artifact)
        if not isinstance(decision_uuid, str) or not decision_uuid.strip():
            return ExecutionSpineResult(
                decision_uuid=None,
                client_order_id=None,
                broker_order_id=None,
                normalized_status="blocked",
                route="execution_engine",
                reason_code="decision_uuid_missing",
                message="DecisionRecord decision_uuid is required before routing",
                decision_artifact=decision_artifact,
                pre_trade_guardrail_verdict=guardrail_verdict,
            )

        signal_metadata = signal.metadata if isinstance(signal.metadata, dict) else {}
        signal_for_execution = signal.model_copy(
            update={
                "metadata": {
                    **signal_metadata,
                    "decision_uuid": decision_uuid,
                    "compiled_decision_artifact": decision_artifact,
                    **({"pre_trade_guardrail_verdict": guardrail_verdict} if guardrail_verdict is not None else {}),
                }
            }
        )
        admitted = self.submit_signal(
            signal_for_execution,
            current_price=current_price,
            is_attack=is_attack,
            decision_uuid=decision_uuid,
            decision_record=decision_record,
        )
        if not admitted:
            block_result = self._last_admission_block_result
            if (
                block_result is not None
                and block_result.decision_uuid == decision_uuid
            ):
                return block_result
            return ExecutionSpineResult(
                decision_uuid=decision_uuid,
                client_order_id=None,
                broker_order_id=None,
                normalized_status="blocked",
                route="execution_engine",
                reason_code="execution_admission_blocked",
                message="ExecutionEngine.submit_signal declined the compiled decision",
                decision_artifact=decision_artifact,
                pre_trade_guardrail_verdict=guardrail_verdict,
            )

        queued = self._pop_matching_queued_signal(decision_uuid, signal_for_execution)
        if queued is None:
            return ExecutionSpineResult(
                decision_uuid=decision_uuid,
                client_order_id=None,
                broker_order_id=None,
                normalized_status="unknown",
                route="execution_engine",
                reason_code="queued_signal_missing",
                message="Compiled decision was admitted but no matching queued signal was available",
                decision_artifact=decision_artifact,
                pre_trade_guardrail_verdict=guardrail_verdict,
            )
        result = self._execute_signal(queued)
        if result is None:
            return ExecutionSpineResult(
                decision_uuid=decision_uuid,
                client_order_id=None,
                broker_order_id=None,
                normalized_status="unknown",
                route="execution_engine",
                reason_code="execution_result_missing",
                decision_artifact=decision_artifact,
                pre_trade_guardrail_verdict=guardrail_verdict,
            )
        return result

    def get_status(self) -> Dict[str, Any]:
        """Get execution engine status."""
        with self._lock:
            return {
                "is_running": self._state.is_running,
                "is_in_safe_mode": self._state.is_in_safe_mode,
                "safe_mode_entered_at_ns": self._state.safe_mode_entered_at_ns,
                "last_latency_ok_at_ns": self._state.last_latency_ok_at_ns,
                "safe_mode_recovery_state": self._state.safe_mode_recovery_state,
                "is_in_recalibration": self._state.is_in_recalibration,
                "recalibration_until_ns": self._state.recalibration_until_ns,
                "last_latency_ms": self._state.last_latency_ms,
                "last_latency_truth": dict(self._state.last_latency_truth),
                "pending_orders_count": len(self._state.pending_orders),
                "pending_orders_value": sum(o.quantity * (o.limit_price or Decimal("0")) for o in self._state.pending_orders.values()),
                "filled_orders_count": len(self._state.filled_orders),
                "execution_queue_size": self._execution_queue.qsize(),
                "last_equity": self._state.last_equity,
                "last_regime": self._state.last_regime,
                "last_health_check_ns": self._state.last_health_check_ns,
            }

    # ============================================
    # INTERNAL METHODS
    # ============================================

    def _classify_latency_truth(
        self,
        latency_ms: Any,
        *,
        current_ns: Optional[int] = None,
    ) -> LatencyTruthResult:
        """Classify router latency without converting missing timing into fake lag."""
        threshold = float(self.lag_threshold_ms)
        latency_measurement = latency_ms if isinstance(latency_ms, dict) else {}
        source = str(latency_measurement.get("source") or "order_router.websocket_rtt")
        source_scope = _latency_source_scope(source, latency_measurement)
        current_ns = int(current_ns or now_ns())

        is_market_data_rest_latency = source in {
            "market_data.rest_polling_rtt",
            "market_data.candle_rtt",
            "market_data.book_rtt",
            "market_data_candle_rtt",
            "market_data_book_rtt",
        }

        if is_market_data_rest_latency:
            request_start_ns = int(latency_measurement.get("request_start_ns") or 0)
            response_received_ns = int(latency_measurement.get("response_received_ns") or 0)
            latency_value_raw = latency_measurement.get("latency_ms")
        else:
            ping_ns = int(latency_measurement.get("ping_ns") or getattr(self.order_router, "_last_websocket_ping_ns", 0) or 0)
            pong_ns = int(latency_measurement.get("pong_ns") or getattr(self.order_router, "_last_websocket_pong_ns", 0) or 0)
            latency_value_raw = (
                latency_measurement.get("latency_ms")
                if isinstance(latency_ms, dict)
                else latency_ms
            )

        try:
            latency_value = float(latency_value_raw)
        except (TypeError, ValueError):
            return LatencyTruthResult(
                status="INVALID_TIMESTAMP_TRUTH",
                reason_code="LATENCY_VALUE_NOT_NUMERIC",
                latency_ms=None,
                threshold_ms=threshold,
                source=source,
                safe_mode_required=True,
                missing_source="order_router.get_latency_measurement",
                source_scope=source_scope,
            )

        if is_market_data_rest_latency:
            if request_start_ns > 0 and response_received_ns > 0 and response_received_ns < request_start_ns:
                return LatencyTruthResult(
                    status="CLOCK_DELTA_INVALID",
                    reason_code="REST_RESPONSE_BEFORE_REQUEST",
                    latency_ms=None,
                    threshold_ms=threshold,
                    source=source,
                    safe_mode_required=True,
                    source_scope=source_scope,
                )

            if not math.isfinite(latency_value):
                missing = "rest_request_or_response_timestamp"
                if request_start_ns > 0 and response_received_ns > 0:
                    missing = "finite_rest_polling_rtt"
                return LatencyTruthResult(
                    status="MISSING_LATENCY_TRUTH",
                    reason_code="REST_RTT_NOT_READY",
                    latency_ms=None,
                    threshold_ms=threshold,
                    source=source,
                    safe_mode_required=False,
                    missing_source=missing,
                    source_scope=source_scope,
                )

            if latency_value < 0:
                return LatencyTruthResult(
                    status="CLOCK_DELTA_INVALID",
                    reason_code="NEGATIVE_REST_RTT",
                    latency_ms=latency_value,
                    threshold_ms=threshold,
                    source=source,
                    safe_mode_required=True,
                    source_scope=source_scope,
                )

            if response_received_ns > 0:
                staleness_ms = max(0.0, (current_ns - response_received_ns) / NS_PER_MS)
                if staleness_ms > 30_000.0:
                    return LatencyTruthResult(
                        status="STALE_MARKET_DATA_LATENCY_TRUTH",
                        reason_code="REST_RTT_STALE",
                        latency_ms=latency_value,
                        threshold_ms=threshold,
                        source=source,
                        safe_mode_required=False,
                        staleness_ms=staleness_ms,
                        source_scope=source_scope,
                    )

            if latency_value > threshold:
                return LatencyTruthResult(
                    status="MARKET_DATA_LATENCY_DEGRADED",
                    reason_code="REST_LATENCY_THRESHOLD_EXCEEDED",
                    latency_ms=latency_value,
                    threshold_ms=threshold,
                    source=source,
                    safe_mode_required=False,
                    source_scope=source_scope,
                )

            return LatencyTruthResult(
                status="LATENCY_OK",
                reason_code="REST_LATENCY_WITHIN_THRESHOLD",
                latency_ms=latency_value,
                threshold_ms=threshold,
                source=source,
                safe_mode_required=False,
                source_scope=source_scope,
            )

        if ping_ns > 0 and pong_ns > 0 and pong_ns < ping_ns:
            return LatencyTruthResult(
                status="CLOCK_DELTA_INVALID",
                reason_code="WEBSOCKET_PONG_BEFORE_PING",
                latency_ms=None,
                threshold_ms=threshold,
                source=source,
                safe_mode_required=True,
                source_scope=source_scope,
            )

        if not math.isfinite(latency_value):
            missing = "websocket_ping_or_pong_timestamp"
            if ping_ns > 0 and pong_ns > 0:
                missing = "finite_websocket_rtt"
            return LatencyTruthResult(
                status="MISSING_LATENCY_TRUTH",
                reason_code="WEBSOCKET_RTT_NOT_READY",
                latency_ms=None,
                threshold_ms=threshold,
                source=source,
                safe_mode_required=True,
                missing_source=missing,
                source_scope=source_scope,
            )

        if latency_value < 0:
            return LatencyTruthResult(
                status="CLOCK_DELTA_INVALID",
                reason_code="NEGATIVE_WEBSOCKET_RTT",
                latency_ms=latency_value,
                threshold_ms=threshold,
                source=source,
                safe_mode_required=True,
                source_scope=source_scope,
            )

        if pong_ns > 0:
            staleness_ms = max(0.0, (current_ns - pong_ns) / NS_PER_MS)
            if staleness_ms > 30_000.0:
                return LatencyTruthResult(
                    status="STALE_MARKET_TRUTH",
                    reason_code="WEBSOCKET_RTT_STALE",
                    latency_ms=latency_value,
                    threshold_ms=threshold,
                    source=source,
                    safe_mode_required=True,
                    staleness_ms=staleness_ms,
                    source_scope=source_scope,
                )

        if latency_value > threshold:
            return LatencyTruthResult(
                status="LAG_ABORT_ACTIVE",
                reason_code="LATENCY_THRESHOLD_EXCEEDED",
                latency_ms=latency_value,
                threshold_ms=threshold,
                source=source,
                safe_mode_required=True,
                source_scope=source_scope,
            )

        return LatencyTruthResult(
            status="LATENCY_OK",
            reason_code="LATENCY_WITHIN_THRESHOLD",
            latency_ms=latency_value,
            threshold_ms=threshold,
            source=source,
            safe_mode_required=False,
            source_scope=source_scope,
        )

    def _apply_latency_truth(self, latency_truth: LatencyTruthResult) -> None:
        """Apply classified latency truth to execution and risk safety state."""
        self._state.last_latency_truth = latency_truth.to_dict()
        self._state.last_latency_ms = (
            latency_truth.latency_ms
            if latency_truth.latency_ms is not None
            else 0.0
        )

        if latency_truth.status == "LATENCY_OK":
            self.risk_guard.update_latency(latency_truth.latency_ms or 0.0)
            self._state.last_latency_ok_at_ns = now_ns()
            self._state.safe_mode_recovery_state = "LATENCY_OK_CONFIRMED"
            if self._state.is_in_safe_mode:
                self._state.is_in_safe_mode = False
                self._state.safe_mode_entered_at_ns = 0
                logger.info(
                    "Latency recovered: %.1fms, exiting safe mode",
                    latency_truth.latency_ms or 0.0,
                )
            return

        if latency_truth.safe_mode_required is not True:
            self._state.safe_mode_recovery_state = latency_truth.status
            logger.info(
                "LATENCY EVIDENCE ONLY: status=%s reason=%s source=%s scope=%s latency_ms=%s threshold=%.1fms",
                latency_truth.status,
                latency_truth.reason_code,
                latency_truth.source,
                latency_truth.source_scope,
                latency_truth.latency_ms,
                latency_truth.threshold_ms,
            )
            return

        if latency_truth.status == "LAG_ABORT_ACTIVE":
            self.risk_guard.update_latency(latency_truth.latency_ms or 0.0)
            self._state.safe_mode_recovery_state = "LAG_ABORT_ACTIVE"
            return

        if not self._state.is_in_safe_mode:
            logger.warning(
                "LATENCY TRUTH BLOCK: status=%s reason=%s source=%s missing_source=%s threshold=%.1fms",
                latency_truth.status,
                latency_truth.reason_code,
                latency_truth.source,
                latency_truth.missing_source,
                latency_truth.threshold_ms,
            )
            self._state.safe_mode_entered_at_ns = now_ns()
        self._state.is_in_safe_mode = True
        self._state.safe_mode_recovery_state = latency_truth.status

    def _record_admission_block(
        self,
        *,
        signal: StrategySignal,
        decision_uuid: Optional[str],
        reason_code: str,
        message: str,
        decision_artifact: Optional[Dict[str, Any]],
        guardrail_verdict: Optional[Dict[str, Any]],
        block_evidence: Optional[Dict[str, Any]] = None,
    ) -> bool:
        signal_metadata = signal.metadata if isinstance(signal.metadata, dict) else {}
        candidate_lifecycle = signal_metadata.get("candidate_lifecycle")
        candidate_lifecycle = dict(candidate_lifecycle) if isinstance(candidate_lifecycle, dict) else None
        self._last_admission_block_result = ExecutionSpineResult(
            decision_uuid=decision_uuid,
            client_order_id=None,
            broker_order_id=None,
            normalized_status="blocked",
            route="execution_engine",
            reason_code=reason_code,
            message=message,
            decision_artifact=decision_artifact,
            pre_trade_guardrail_verdict=guardrail_verdict,
            block_evidence=block_evidence,
            candidate_lifecycle=candidate_lifecycle,
        )
        logger.info(
            "[EXEC_DIAG] SIGNAL_ADMISSION_BLOCKED: symbol=%s side=%s decision_uuid=%s reason_code=%s opportunity_verdict=%s block_evidence=%s",
            getattr(signal, "symbol", None),
            getattr(signal, "side", None),
            decision_uuid,
            reason_code,
            (candidate_lifecycle or {}).get("opportunity_verdict"),
            block_evidence or {},
        )
        return False

    def _safe_mode_block_evidence(self) -> Dict[str, Any]:
        latency_truth = dict(self._state.last_latency_truth)
        return {
            "latency_truth_status": latency_truth.get("status"),
            "latency_truth_reason_code": latency_truth.get("reason_code"),
            "latency_ms": latency_truth.get("latency_ms"),
            "threshold_ms": latency_truth.get("threshold_ms", self.lag_threshold_ms),
            "latency_source": latency_truth.get("source"),
            "latency_source_scope": latency_truth.get("source_scope"),
            "safe_mode_entered_at_ns": self._state.safe_mode_entered_at_ns,
            "last_latency_ok_at_ns": self._state.last_latency_ok_at_ns,
            "safe_mode_recovery_state": self._state.safe_mode_recovery_state,
        }

    def _data_health_block_evidence(
        self,
        signal: StrategySignal,
        *,
        current_ns: int,
    ) -> Dict[str, Any]:
        metadata = signal.metadata if isinstance(signal.metadata, dict) else {}
        market_truth = metadata.get("execution_market_truth")
        market_truth = dict(market_truth) if isinstance(market_truth, dict) else {}
        snapshot = (
            metadata.get("market_truth_snapshot")
            or metadata.get("candidate_market_snapshot")
            or market_truth.get("market_truth_snapshot")
        )
        snapshot = dict(snapshot) if isinstance(snapshot, dict) else {}
        requires_snapshot = metadata.get("requires_canonical_market_snapshot") is True
        source_type = (
            snapshot.get("source_type")
            or market_truth.get("data_source_type")
            or metadata.get("data_source_type")
            or "unknown"
        )
        latest_book_ts_ns = snapshot.get("book_ts_ns") or market_truth.get("latest_book_ts_ns")
        latest_candle_ts_ns = snapshot.get("candle_id") or market_truth.get("latest_candle_ts_ns")
        observed_symbol = snapshot.get("symbol") or market_truth.get("symbol") or metadata.get("market_truth_symbol")

        if self.data_validator is None:
            if snapshot or requires_snapshot:
                return validate_market_snapshot_for_execution(
                    snapshot or None,
                    signal_symbol=signal.symbol,
                    signal_exchange_ts_ns=getattr(signal, "exchange_ts_ns", None),
                    current_ns=current_ns,
                    monitor_evidence=None,
                )
            return {}

        monitor_evidence: Dict[str, Any] = {}
        snapshot_fn = getattr(self.data_validator, "health_snapshot", None)
        if callable(snapshot_fn):
            monitor_evidence = snapshot_fn(
                signal.symbol,
                current_ns=current_ns,
                latest_book_ts_ns=latest_book_ts_ns,
                latest_candle_ts_ns=latest_candle_ts_ns,
                source_type=str(source_type),
                observed_symbol=observed_symbol,
            )
            if snapshot or requires_snapshot:
                return validate_market_snapshot_for_execution(
                    snapshot or None,
                    signal_symbol=signal.symbol,
                    signal_exchange_ts_ns=getattr(signal, "exchange_ts_ns", None),
                    current_ns=current_ns,
                    monitor_evidence=monitor_evidence,
                )
            return monitor_evidence

        healthy = bool(self.data_validator.is_data_healthy(signal.symbol))
        legacy_evidence = {
            "symbol": signal.symbol,
            "gap_detected": None,
            "last_valid_data_ns": None,
            "last_valid_data_age_ms": None,
            "max_stale_age_ms": None,
            "latest_book_ts_ns": latest_book_ts_ns,
            "latest_candle_ts_ns": latest_candle_ts_ns,
            "data_health_reason_code": (
                "DATA_HEALTHY" if healthy else "DATA_HEALTH_UNKNOWN"
            ),
            "data_source_type": str(source_type),
            "data_healthy": healthy,
        }
        if snapshot or requires_snapshot:
            return validate_market_snapshot_for_execution(
                snapshot or None,
                signal_symbol=signal.symbol,
                signal_exchange_ts_ns=getattr(signal, "exchange_ts_ns", None),
                current_ns=current_ns,
                monitor_evidence=legacy_evidence,
            )
        return legacy_evidence

    def _record_shadow_read_only_block(
        self,
        *,
        signal: StrategySignal,
        current_price: Decimal,
        is_attack: bool,
        decision_uuid: Optional[str],
        decision_record: Optional[DecisionRecord],
        guardrail_verdict: Optional[Dict[str, Any]],
    ) -> ExecutionSpineResult:
        ts_ns = now_ns()
        signal_metadata = signal.metadata if isinstance(signal.metadata, dict) else {}
        decision_artifact = (
            self._decision_artifact_summary(decision_record)
            if decision_record is not None
            else signal_metadata.get("compiled_decision_artifact")
        )
        if not isinstance(decision_artifact, dict):
            decision_artifact = None
        edge_attribution = signal_metadata.get("edge_attribution")
        if not isinstance(edge_attribution, dict) and isinstance(decision_artifact, dict):
            metadata = decision_artifact.get("metadata")
            if isinstance(metadata, dict):
                edge_attribution = metadata.get("edge_attribution")
        if not isinstance(edge_attribution, dict):
            edge_attribution = {}
        candidate_lifecycle = signal_metadata.get("candidate_lifecycle")
        candidate_lifecycle = dict(candidate_lifecycle) if isinstance(candidate_lifecycle, dict) else {}
        opportunity_scorecard = signal_metadata.get("opportunity_scorecard")
        opportunity_scorecard = dict(opportunity_scorecard) if isinstance(opportunity_scorecard, dict) else {}

        guardrail = guardrail_verdict if isinstance(guardrail_verdict, dict) else {}
        asset_class = (
            signal_metadata.get("asset_class")
            or guardrail.get("asset_class")
            or guardrail.get("capability_identity", {}).get("asset_class")
            or "unknown"
        )
        order_type = (
            signal_metadata.get("order_type")
            or guardrail.get("order_type")
            or ("limit" if is_attack else "market")
        )
        payload = {
            "timestamp_ns": ts_ns,
            "symbol": getattr(signal, "symbol", None),
            "asset_class": asset_class,
            "side": getattr(signal, "side", None),
            "order_type": str(order_type).lower(),
            "notional_intent": (
                signal_metadata.get("requested_notional")
                or guardrail.get("requested_notional")
            ),
            "quantity_intent": str(getattr(signal, "quantity", "")),
            "current_price": str(current_price),
            "guardrail_verdict": guardrail_verdict,
            "edge_attribution": edge_attribution,
            "candidate_lifecycle": candidate_lifecycle,
            "opportunity_scorecard": opportunity_scorecard,
            "reason": "SHADOW_READ_ONLY_BLOCKED_BROKER_MUTATION",
            "shadow_read_only": True,
            "broker_post_patch_delete_count": 0,
            "broker_mutation_counts": self.get_shadow_broker_mutation_counts(),
            "confirmation": {
                "broker_mutation_impossible_at_execution_gate": True,
                "order_router_submit_order_reached": False,
                "live_mode": False,
            },
        }

        with self._lock:
            self._shadow_read_only_events.append(dict(payload))

        if self.telemetry_store is not None:
            event = EventEnvelope(
                decision_uuid=decision_uuid,
                event_type=EventType.AUDIT_EVENT,
                source_module="app.execution.engine.shadow_read_only",
                exchange_ts_ns=int(getattr(signal, "exchange_ts_ns", 0) or ts_ns),
                receive_ts_ns=ts_ns,
                decision_ts_ns=ts_ns,
                payload=payload,
            )
            self.telemetry_store.record_event(event)

        logger.info(
            "[EXEC_DIAG] SHADOW_READ_ONLY_BLOCKED_BROKER_MUTATION: symbol=%s side=%s qty=%s decision_uuid=%s",
            getattr(signal, "symbol", None),
            getattr(signal, "side", None),
            getattr(signal, "quantity", None),
            decision_uuid,
        )
        return ExecutionSpineResult(
            decision_uuid=decision_uuid,
            client_order_id=None,
            broker_order_id=None,
            normalized_status="blocked",
            route="shadow_read_only",
            reason_code="SHADOW_READ_ONLY_BLOCKED_BROKER_MUTATION",
            message="Shadow read-only runtime blocked broker mutation before OrderRouter.",
            decision_artifact=decision_artifact,
            pre_trade_guardrail_verdict=guardrail_verdict,
            candidate_lifecycle=candidate_lifecycle or None,
        )

    def evaluate_signal_net_edge(
        self,
        signal: StrategySignal,
        *,
        current_ns: Optional[int] = None,
        current_price: Optional[Decimal] = None,
    ) -> Dict[str, Any]:
        """
        Active NetEdge admission precheck.

        This is a modeled economic gate, not a broker fact source. Runtime may
        supply richer economics in signal.metadata["net_edge_context"]; missing
        expected edge remains fail-closed.
        """
        current_time_ns = int(current_ns or now_ns())
        metadata = signal.metadata if isinstance(signal.metadata, dict) else {}
        try:
            candidate, model_inputs = self._build_net_edge_candidate_context(
                signal,
                current_ns=current_time_ns,
                current_price=current_price,
            )
        except ValueError as exc:
            result = {
                "status": "BLOCK",
                "admissible": False,
                "decision": EconomicDecision.DENY.value,
                "reason_code": "NET_EDGE_MISSING_TRUTH",
                "message": str(exc),
                "source": "NetEdgeGovernor",
                "cost_model_source": "active_execution_modeled_costs",
                "broker_post": False,
            }
            if isinstance(metadata, dict):
                metadata["net_edge_evaluation"] = result
            return result

        evaluation = self.net_edge_governor.evaluate(
            current_time_ns,
            candidate,
            kill_switch_active=False,
        )
        result = self._net_edge_evaluation_to_dict(evaluation)
        result["admissible"] = evaluation.decision in {
            EconomicDecision.ALLOW,
            EconomicDecision.ALLOW_REDUCED,
            EconomicDecision.HEDGE_ONLY,
            EconomicDecision.REDUCE_ONLY,
        }
        result["status"] = "PASS" if result["admissible"] else "BLOCK"
        result["source"] = "NetEdgeGovernor"
        result["model_inputs"] = model_inputs
        result["broker_post"] = False
        if isinstance(metadata, dict):
            metadata["net_edge_context"] = model_inputs
            metadata["net_edge_evaluation"] = result
            metadata["economics_context"] = {
                "verified": True,
                "authority": "NetEdgeGovernor",
                "decision": result.get("decision"),
                "reason_code": result.get("reason_code"),
                "net_adversarial_edge": result.get("net_adversarial_edge"),
                "model_inputs": model_inputs,
            }
        return result

    def _is_signal_economically_admissible(self, signal: StrategySignal) -> bool:
        """
        Canonical execution-side economic admissibility boundary.

        NetEdgeGovernor is the active economic authority for signal admission.
        """
        return self.evaluate_signal_net_edge(signal).get("admissible") is True

    def _calculate_signal_net_profit(self, signal: StrategySignal) -> Decimal:
        expected_move = Decimal("0.02")
        if signal.metadata and "expected_move" in signal.metadata:
            expected_move = Decimal(str(signal.metadata["expected_move"]))
        gross_ev = expected_move * Decimal(str(signal.confidence))
        total_costs = Decimal("0.0036")
        return gross_ev - total_costs

    def _build_net_edge_candidate_context(
        self,
        signal: StrategySignal,
        *,
        current_ns: int,
        current_price: Optional[Decimal] = None,
    ) -> Tuple[CandidateContext, Dict[str, Any]]:
        metadata = signal.metadata if isinstance(signal.metadata, dict) else {}
        supplied = metadata.get("net_edge_context")
        supplied = dict(supplied) if isinstance(supplied, dict) else {}

        confidence = _decimal_from_any(
            supplied.get("estimate_confidence", getattr(signal, "confidence", None)),
            field_name="estimate_confidence",
        )
        expected_move = _expected_move_fraction(metadata, supplied)
        if expected_move is None:
            raise ValueError("expected_move or expected_move_bps is required for NetEdge")
        gross_edge = _decimal_from_any(
            supplied.get("gross_edge", expected_move * confidence),
            field_name="gross_edge",
        )
        if gross_edge <= Decimal("0"):
            raise ValueError("gross_edge must be positive for NetEdge")

        signal_price = getattr(signal, "price", None) or current_price
        price = _decimal_from_any(signal_price, field_name="price")
        quantity = _decimal_from_any(getattr(signal, "quantity", None), field_name="quantity")
        if price <= Decimal("0") or quantity <= Decimal("0"):
            raise ValueError("positive signal price and quantity are required for NetEdge")

        side = str(getattr(signal, "side", "") or "").lower()
        candidate_type = CandidateType.FRESH_ENTRY
        if side == "sell":
            candidate_type = CandidateType.CLOSE if metadata.get("requires_existing_position") or metadata.get("protective_only") else CandidateType.FRESH_ENTRY

        valid_until_ns = int(
            supplied.get("valid_until_ns")
            or metadata.get("valid_until_ns")
            or (current_ns + max(self._signal_ttl_ns, NS_PER_SECOND))
        )
        if valid_until_ns < current_ns:
            raise ValueError("NetEdge valid_until_ns is stale")

        spread_bps = _decimal_or_default(
            supplied.get("spread_bps", metadata.get("spread_bps")),
            _DEFAULT_MODELED_SPREAD_BPS,
        )
        fee_bps = _decimal_or_default(
            supplied.get("fee_bps", metadata.get("fee_bps")),
            _DEFAULT_MODELED_FEE_BPS,
        )
        slippage_bps = _decimal_or_default(
            supplied.get("slippage_bps", metadata.get("slippage_bps")),
            _DEFAULT_MODELED_SLIPPAGE_BPS,
        )
        latency_drag_bps = _decimal_or_default(
            supplied.get("latency_drag_bps", metadata.get("latency_drag_bps")),
            _DEFAULT_MODELED_LATENCY_DRAG_BPS,
        )
        partial_fill_drag_bps = _decimal_or_default(
            supplied.get("partial_fill_drag_bps", metadata.get("partial_fill_drag_bps")),
            _DEFAULT_MODELED_PARTIAL_FILL_BPS,
        )
        exit_execution_cost_bps = _decimal_or_default(
            supplied.get("exit_execution_cost_bps", metadata.get("exit_execution_cost_bps")),
            _DEFAULT_MODELED_EXIT_COST_BPS,
        )

        costs = ExecutionEconomics(
            fee_cost=_bps_to_fraction(fee_bps),
            spread_cost=_bps_to_fraction(spread_bps),
            slippage_cost=_bps_to_fraction(slippage_bps),
            latency_drag=_bps_to_fraction(latency_drag_bps),
            partial_fill_drag=_bps_to_fraction(partial_fill_drag_bps),
            exit_execution_cost=_bps_to_fraction(exit_execution_cost_bps),
        )
        burdens = AdversarialBurdens(
            borrow_burden=_bps_to_fraction(_decimal_or_default(supplied.get("borrow_bps"), Decimal("0"))),
            funding_burden=_bps_to_fraction(_decimal_or_default(supplied.get("funding_bps"), Decimal("0"))),
            carry_burden=_bps_to_fraction(_decimal_or_default(supplied.get("carry_bps"), Decimal("0"))),
            capital_burden=_bps_to_fraction(_decimal_or_default(supplied.get("capital_bps"), Decimal("0"))),
            margin_burden=_bps_to_fraction(_decimal_or_default(supplied.get("margin_bps"), Decimal("0"))),
            regime_burden=_bps_to_fraction(_decimal_or_default(supplied.get("regime_bps"), Decimal("0"))),
            adverse_exit_allowance=_bps_to_fraction(_decimal_or_default(supplied.get("adverse_exit_bps"), Decimal("0"))),
        )
        sleeve_id = str(
            supplied.get("sleeve_id")
            or metadata.get("sleeve")
            or getattr(signal, "strategy", None)
            or "unknown"
        )
        context = CandidateContext(
            symbol=str(getattr(signal, "symbol", "") or ""),
            sleeve_id=sleeve_id,
            candidate_type=candidate_type,
            gross_edge=gross_edge,
            gross_edge_source=str(supplied.get("gross_edge_source") or "signal_expected_move_x_confidence"),
            estimate_confidence=confidence,
            timestamp_ns=current_ns,
            valid_until_ns=valid_until_ns,
            costs=costs,
            burdens=burdens,
        )
        model_inputs = {
            "symbol": context.symbol,
            "sleeve_id": context.sleeve_id,
            "candidate_type": context.candidate_type.value,
            "expected_move": str(expected_move),
            "gross_edge": str(gross_edge),
            "estimate_confidence": str(confidence),
            "fee_bps": str(fee_bps),
            "spread_bps": str(spread_bps),
            "slippage_bps": str(slippage_bps),
            "latency_drag_bps": str(latency_drag_bps),
            "partial_fill_drag_bps": str(partial_fill_drag_bps),
            "exit_execution_cost_bps": str(exit_execution_cost_bps),
            "valid_until_ns": valid_until_ns,
            "cost_model_source": "active_execution_modeled_costs",
            "default_total_cost_bps_preserves_legacy_36bps_floor": True,
        }
        return context, model_inputs

    def _net_edge_evaluation_to_dict(self, evaluation: Any) -> Dict[str, Any]:
        return {
            "timestamp_ns": getattr(evaluation, "timestamp_ns", None),
            "symbol": getattr(evaluation, "symbol", None),
            "sleeve_id": getattr(evaluation, "sleeve_id", None),
            "candidate_type": getattr(getattr(evaluation, "candidate_type", None), "value", getattr(evaluation, "candidate_type", None)),
            "gross_edge_source": getattr(evaluation, "gross_edge_source", None),
            "gross_edge": str(getattr(evaluation, "gross_edge", "")),
            "total_modeled_cost": str(getattr(evaluation, "total_modeled_cost", "")),
            "total_modeled_burden": str(getattr(evaluation, "total_modeled_burden", "")),
            "net_adversarial_edge": str(getattr(evaluation, "net_adversarial_edge", "")),
            "estimate_confidence": str(getattr(evaluation, "estimate_confidence", "")),
            "decision": getattr(getattr(evaluation, "decision", None), "value", getattr(evaluation, "decision", None)),
            "sizing_multiplier": str(getattr(evaluation, "sizing_multiplier", "")),
            "sleeve_efficiency_state": getattr(getattr(evaluation, "sleeve_efficiency_state", None), "value", getattr(evaluation, "sleeve_efficiency_state", None)),
            "reason_code": getattr(evaluation, "reason_code", None),
            "reevaluation_conditions": tuple(getattr(evaluation, "reevaluation_conditions", ()) or ()),
        }

    def _decision_artifact_summary(self, decision_record: DecisionRecord) -> Dict[str, Any]:
        return {
            "decision_uuid": getattr(decision_record, "decision_uuid", None),
            "timestamp_ns": getattr(decision_record, "timestamp_ns", None),
            "decision_type": str(getattr(decision_record, "decision_type", "unknown")),
            "inputs": dict(getattr(decision_record, "inputs", {}) or {}),
            "outputs": dict(getattr(decision_record, "outputs", {}) or {}),
            "metadata": dict(getattr(decision_record, "metadata", {}) or {}),
            "schema_version": getattr(decision_record, "schema_version", None),
        }

    def _extract_pre_trade_guardrail_verdict(
        self,
        decision_artifact: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        outputs = decision_artifact.get("outputs")
        if isinstance(outputs, dict):
            additional = outputs.get("additional")
            if isinstance(additional, dict):
                verdict = additional.get("pre_trade_guardrail_verdict")
                if isinstance(verdict, dict):
                    return verdict
        inputs = decision_artifact.get("inputs")
        if isinstance(inputs, dict):
            verdict = inputs.get("pre_trade_guardrail_verdict")
            if isinstance(verdict, dict):
                return verdict
        return None

    def _normalized_pre_trade_guardrail_verdict(
        self,
        signal: StrategySignal,
    ) -> Optional[Dict[str, Any]]:
        metadata = signal.metadata if isinstance(signal.metadata, dict) else {}
        verdict = metadata.get("pre_trade_guardrail_verdict")
        if isinstance(verdict, dict):
            return verdict
        return None

    def _pre_trade_guardrail_signal_mismatch_evidence(
        self,
        signal: StrategySignal,
        guardrail_verdict: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(guardrail_verdict, dict):
            return None

        def _normalized(value: Any) -> str:
            raw = getattr(value, "value", value)
            return str(raw or "").strip().lower()

        signal_symbol = _normalized(getattr(signal, "symbol", None))
        signal_side = _normalized(getattr(signal, "side", None))
        guardrail_symbol = _normalized(guardrail_verdict.get("symbol"))
        guardrail_side = _normalized(guardrail_verdict.get("side"))

        mismatch_reasons: List[str] = []
        if guardrail_symbol and signal_symbol and guardrail_symbol != signal_symbol:
            mismatch_reasons.append("PRE_TRADE_GUARDRAIL_SYMBOL_MISMATCH")
        if guardrail_side and signal_side and guardrail_side != signal_side:
            mismatch_reasons.append("PRE_TRADE_GUARDRAIL_SIDE_MISMATCH")
        if not mismatch_reasons:
            return None

        return {
            "reason_codes": tuple(mismatch_reasons),
            "signal_symbol": getattr(signal, "symbol", None),
            "guardrail_symbol": guardrail_verdict.get("symbol"),
            "signal_side": getattr(signal, "side", None),
            "guardrail_side": guardrail_verdict.get("side"),
            "guardrail_route_permitted": guardrail_verdict.get("route_permitted"),
            "blocked_before_order_router": True,
        }

    def _pop_matching_queued_signal(
        self,
        decision_uuid: str,
        signal: StrategySignal,
    ) -> Optional[QueuedSignal]:
        buffered: List[QueuedSignal] = []
        matched: Optional[QueuedSignal] = None
        while True:
            try:
                queued = self._execution_queue.get_nowait()
            except queue.Empty:
                break
            if (
                matched is None
                and queued.decision_uuid == decision_uuid
                and queued.signal.symbol == signal.symbol
                and queued.signal.exchange_ts_ns == signal.exchange_ts_ns
            ):
                matched = queued
                continue
            buffered.append(queued)
        for item in buffered:
            self._execution_queue.put(item)
        return matched

    def _validate_signal_before_execution(self, queued: QueuedSignal, current_price: Decimal) -> Tuple[bool, str]:
        """Validate queued signal with TTL, price sanity, and regime checks."""
        current_ns = now_ns()
        age_ns = max(0, current_ns - queued.enqueue_time_ns)
        age_ms = age_ns / NS_PER_MS
        if age_ns > self._signal_ttl_ns:
            return False, f"stale:{age_ms:.1f}ms"

        if queued.enqueue_price <= Decimal("0"):
            return False, "invalid_enqueue_price"

        price_change_pct = abs(current_price - queued.enqueue_price) / queued.enqueue_price
        if price_change_pct > self.price_sanity_threshold_pct:
            return False, f"price_moved:{price_change_pct:.2%}"

        if self._state.last_regime and queued.enqueue_regime:
            if self._state.last_regime != queued.enqueue_regime:
                severe = (
                    (queued.enqueue_regime == "trending" and self._state.last_regime == "crisis") or
                    (queued.enqueue_regime == "crisis" and self._state.last_regime == "trending")
                )
                if severe:
                    return False, f"regime_changed:{queued.enqueue_regime}->{self._state.last_regime}"

        data_health_evidence = self._data_health_block_evidence(queued.signal, current_ns=current_ns)
        if data_health_evidence and data_health_evidence.get("data_healthy") is not True:
            return False, f"data_unhealthy:{data_health_evidence.get('data_health_reason_code')}"

        return True, "ok"

    def _execute_signal(self, queued: QueuedSignal) -> Optional[ExecutionSpineResult]:
        """Execute a trading signal after sovereign validation."""
        signal = queued.signal
        is_attack = queued.is_attack
        signal_metadata = signal.metadata if isinstance(signal.metadata, dict) else {}
        candidate_lifecycle = signal_metadata.get("candidate_lifecycle")
        candidate_lifecycle = dict(candidate_lifecycle) if isinstance(candidate_lifecycle, dict) else None
        decision_artifact = signal_metadata.get("compiled_decision_artifact")
        if not isinstance(decision_artifact, dict):
            decision_artifact = None
        guardrail_verdict = self._normalized_pre_trade_guardrail_verdict(signal)
        if guardrail_verdict is None and signal_metadata.get("execution_adapter") == "alpaca_paper_rest":
            return ExecutionSpineResult(
                decision_uuid=queued.decision_uuid,
                client_order_id=None,
                broker_order_id=None,
                normalized_status="blocked",
                route="execution_engine",
                reason_code="PRE_TRADE_GUARDRAIL_MISSING",
                message="External Alpaca PAPER route requires a pre-trade guardrail verdict before OrderRouter.",
                decision_artifact=decision_artifact,
                pre_trade_guardrail_verdict=None,
                candidate_lifecycle=candidate_lifecycle,
            )
        guardrail_signal_mismatch = self._pre_trade_guardrail_signal_mismatch_evidence(
            signal,
            guardrail_verdict,
        )
        if guardrail_signal_mismatch is not None:
            return ExecutionSpineResult(
                decision_uuid=queued.decision_uuid,
                client_order_id=None,
                broker_order_id=None,
                normalized_status="blocked",
                route="execution_engine",
                reason_code="PRE_TRADE_GUARDRAIL_SIGNAL_MISMATCH",
                message="Pre-trade guardrail does not authorize this signal symbol/side.",
                decision_artifact=decision_artifact,
                pre_trade_guardrail_verdict=guardrail_verdict,
                block_evidence=guardrail_signal_mismatch,
                candidate_lifecycle=candidate_lifecycle,
            )
        current_price = self.order_router.get_mid_price(signal.symbol)

        is_valid, reason = self._validate_signal_before_execution(queued, current_price)
        if not is_valid:
            logger.warning("Signal rejected: %s/%s - %s", signal.strategy, signal.symbol, reason)
            logger.info(
                "[EXEC_DIAG] SIGNAL_REJECTED: strategy=%s symbol=%s reason=%s",
                signal.strategy,
                signal.symbol,
                reason,
            )
            return ExecutionSpineResult(
                decision_uuid=queued.decision_uuid,
                client_order_id=None,
                broker_order_id=None,
                normalized_status="blocked",
                route="execution_engine",
                reason_code=reason,
                decision_artifact=decision_artifact,
                pre_trade_guardrail_verdict=guardrail_verdict,
                candidate_lifecycle=candidate_lifecycle,
            )

        if self.shadow_read_only:
            return self._record_shadow_read_only_block(
                signal=signal,
                current_price=current_price,
                is_attack=is_attack,
                decision_uuid=queued.decision_uuid,
                decision_record=None,
                guardrail_verdict=guardrail_verdict,
            )

        masked = self.masking_layer.mask_order(signal.quantity)
        resolved_order_type = str(
            signal_metadata.get("order_type")
            or (guardrail_verdict or {}).get("order_type")
            or ("limit" if is_attack else "market")
        ).lower()

        if resolved_order_type == "limit":
            if current_price > Decimal("0"):
                if signal.side == "buy":
                    limit_price_for_order = (
                        current_price * (Decimal("1") - self.maker_offset_pct)
                        if is_attack
                        else current_price
                    )
                else:
                    limit_price_for_order = (
                        current_price * (Decimal("1") + self.maker_offset_pct)
                        if is_attack
                        else current_price
                    )
            elif signal.price is not None:
                limit_price_for_order = Decimal(str(signal.price))
            else:
                logger.warning(
                    "[EXEC_DIAG] SIGNAL_REJECTED: strategy=%s symbol=%s reason=limit_order_no_price",
                    signal.strategy,
                    signal.symbol,
                )
                return ExecutionSpineResult(
                    decision_uuid=queued.decision_uuid,
                    client_order_id=None,
                    broker_order_id=None,
                    normalized_status="blocked",
                    route="execution_engine",
                    reason_code="limit_order_no_price",
                    decision_artifact=decision_artifact,
                    pre_trade_guardrail_verdict=guardrail_verdict,
                    candidate_lifecycle=candidate_lifecycle,
                )
        else:
            limit_price_for_order = None

        current_ns = now_ns()
        order_metadata = {
            "original_size": signal.quantity,
            "masked_size": masked.masked_size,
            "is_attack": is_attack,
            "execution_enqueue_time_ns": queued.enqueue_time_ns,
        }
        for key in (
            "asset_class",
            "venue_id",
            "portal_name",
            "environment",
            "execution_adapter",
            "reconciliation_adapter",
            "capability_key",
            "time_in_force",
            "order_constraint_verdict",
            "source_signal_id",
            "order_intent_id",
            "requested_notional",
            "compiled_decision_artifact",
            "pre_trade_guardrail_verdict",
            "edge_attribution",
            "candidate_lifecycle",
            "opportunity_scorecard",
            "decision_frame",
            "active_threshold_profile",
            "frame_id",
            "frame_output",
            "frame_status",
            "market_truth_snapshot",
            "candidate_market_snapshot",
            "requires_canonical_market_snapshot",
            "snapshot_id",
            "candle_id",
        ):
            if key in signal_metadata:
                order_metadata[key] = signal_metadata[key]
        if isinstance(guardrail_verdict, dict):
            capability_identity = guardrail_verdict.get("capability_identity")
            if isinstance(capability_identity, dict):
                for key in (
                    "asset_class",
                    "venue_id",
                    "portal_name",
                    "environment",
                    "execution_adapter",
                    "reconciliation_adapter",
                    "capability_key",
                ):
                    if key not in order_metadata and capability_identity.get(key) is not None:
                        order_metadata[key] = capability_identity[key]
            if "time_in_force" not in order_metadata and guardrail_verdict.get("time_in_force"):
                order_metadata["time_in_force"] = str(guardrail_verdict["time_in_force"]).lower()
            if "order_type" not in order_metadata and guardrail_verdict.get("order_type"):
                order_metadata["order_type"] = str(guardrail_verdict["order_type"]).lower()
        aggression_contract_metadata = signal_metadata.get(
            "canonical_aggression_contract"
        )
        if isinstance(aggression_contract_metadata, dict):
            order_metadata["canonical_aggression_contract"] = dict(
                aggression_contract_metadata
            )
            order_metadata["execution_is_attack_source"] = (
                "Commander.canonical_aggression_contract.execution_is_attack"
            )
            order_metadata["execution_is_attack_matches_contract"] = (
                aggression_contract_metadata.get("execution_is_attack") == is_attack
            )

        aggression_replay_proof = signal_metadata.get("aggression_replay_proof")
        if isinstance(aggression_replay_proof, dict):
            order_metadata["aggression_replay_proof"] = dict(aggression_replay_proof)

        portfolio_replay_context = signal_metadata.get("portfolio_replay_context")
        if isinstance(portfolio_replay_context, dict):
            order_metadata["portfolio_replay_context"] = dict(portfolio_replay_context)

        exposure_snapshot_replay_context = signal_metadata.get(
            "exposure_snapshot_replay_context"
        )
        if isinstance(exposure_snapshot_replay_context, dict):
            order_metadata["exposure_snapshot_replay_context"] = dict(
                exposure_snapshot_replay_context
            )

        if "aggression_context" in signal_metadata or "aggression_snapshot_id" in signal_metadata:
            order_metadata["advisory_aggression_metadata_present"] = True
            if "aggression_snapshot_id" in signal_metadata:
                order_metadata["advisory_aggression_snapshot_id"] = signal_metadata[
                    "aggression_snapshot_id"
                ]

        order = OrderRequest(
            id=f"{signal.strategy}_{signal.symbol}_{signal.exchange_ts_ns}",
            symbol=signal.symbol,
            side=signal.side,
            quantity=Decimal(str(masked.masked_size)),
            order_type=resolved_order_type,
            limit_price=limit_price_for_order,
            strategy=signal.strategy,
            confidence=signal.confidence,
            exchange_ts_ns=signal.exchange_ts_ns,
            receive_ts_ns=current_ns,
            decision_uuid=queued.decision_uuid,
            metadata=order_metadata,
        )

        try:
            fill = self.order_router.submit_order(order)
            gateway_response = None
            gateway_response_getter = getattr(self.order_router, "get_gateway_response", None)
            if callable(gateway_response_getter):
                gateway_response = gateway_response_getter(order.id)
            logger.info(
                "[EXEC_DIAG] PAPERBROKER_REACH_COUNT: strategy=%s symbol=%s side=%s qty=%s",
                signal.strategy,
                order.symbol,
                order.side,
                order.quantity,
            )
            logger.info(
                "[EXEC_DIAG] ORDER_SUBMIT_ATTEMPT: order_id=%s symbol=%s side=%s qty=%s fill=%s",
                order.id,
                order.symbol,
                order.side,
                order.quantity,
                fill is not None,
            )
            if fill:
                logger.info(
                    "[EXEC_DIAG] PAPER_FILL_COUNT: order_id=%s symbol=%s qty=%s price=%s",
                    order.id,
                    order.symbol,
                    fill.quantity,
                    fill.price,
                )
                with self._lock:
                    self._state.filled_orders.append(fill)
                self.risk_guard.record_fees(fill.fee)
                return ExecutionSpineResult(
                    decision_uuid=queued.decision_uuid,
                    client_order_id=order.id,
                    broker_order_id=getattr(fill, "venue_order_id", None),
                    normalized_status="filled",
                    route="paper_broker",
                    fill=fill,
                    gateway_response=None,
                    decision_artifact=decision_artifact,
                    pre_trade_guardrail_verdict=guardrail_verdict,
                    candidate_lifecycle=candidate_lifecycle,
                )

            if gateway_response is not None:
                normalized_status = str(getattr(gateway_response, "normalized_status", "unknown"))
                if normalized_status in {"accepted", "open", "partially_filled", "unknown"}:
                    with self._lock:
                        self._state.pending_orders[order.id] = order
                return ExecutionSpineResult(
                    decision_uuid=queued.decision_uuid,
                    client_order_id=order.id,
                    broker_order_id=getattr(gateway_response, "broker_order_id", None),
                    normalized_status=normalized_status,
                    route=str(getattr(gateway_response, "adapter_id", "broker_gateway")),
                    reason_code=getattr(gateway_response, "reason_code", None),
                    message=getattr(gateway_response, "message", None),
                    fill=None,
                    gateway_response=gateway_response,
                    decision_artifact=decision_artifact,
                    pre_trade_guardrail_verdict=guardrail_verdict,
                    candidate_lifecycle=candidate_lifecycle,
                )

            else:
                with self._lock:
                    self._state.pending_orders[order.id] = order
                return ExecutionSpineResult(
                    decision_uuid=queued.decision_uuid,
                    client_order_id=order.id,
                    broker_order_id=None,
                    normalized_status="pending",
                    route="paper_broker",
                    fill=None,
                    gateway_response=None,
                    decision_artifact=decision_artifact,
                    pre_trade_guardrail_verdict=guardrail_verdict,
                    candidate_lifecycle=candidate_lifecycle,
                )
        except Exception as e:
            logger.error("Order submission failed: %s", e)
            return ExecutionSpineResult(
                decision_uuid=queued.decision_uuid,
                client_order_id=order.id if "order" in locals() else None,
                broker_order_id=None,
                normalized_status="unknown",
                route="order_router",
                reason_code="order_submission_exception",
                message=str(e),
                decision_artifact=decision_artifact,
                pre_trade_guardrail_verdict=guardrail_verdict,
                candidate_lifecycle=candidate_lifecycle,
            )

    # ============================================
    # PCV FOR NORMAL OPERATIONS
    # ============================================

    def _cancel_pending_order_with_pcv(self, order_id: str) -> bool:
        """Cancel a pending order with PCV. Normal operations only."""
        if order_id in self._cancel_attempted_order_ids:
            logger.info(
                "[OMS_DIAG] CANCEL_SKIPPED fields=%s",
                {
                    "client_order_id": order_id,
                    "reason_code": OmsReasonCode.CANCEL_ALREADY_ATTEMPTED.value,
                    "broker_command_performed": False,
                },
            )
            return False
        if self.shadow_read_only:
            logger.info(
                "[EXEC_DIAG] SHADOW_READ_ONLY_BLOCKED_CANCEL: order_id=%s",
                order_id,
            )
            return False
        try:
            self._cancel_attempted_order_ids.add(order_id)
            cancel_success = self.order_router.cancel_order(order_id)
            if not cancel_success:
                return False

            for _attempt in range(5):
                status = self.order_router.get_order_status(order_id)
                if status in ["cancelled", "expired", "rejected"]:
                    with self._lock:
                        if order_id in self._state.pending_orders:
                            del self._state.pending_orders[order_id]
                    return True
                if status == "filled":
                    return False
                time.sleep(0.5)
            return False
        except Exception as e:
            logger.error("PCV cancellation failed: %s", e)
            return False

    # ============================================
    # FIRE-AND-FORGET EMERGENCY LIQUIDATION - NON-BLOCKING
    # ============================================

    def _emergency_liquidate_all(self) -> None:
        """
        Emergency liquidation - fire-and-forget sequence.
        """
        if self.shadow_read_only:
            logger.critical(
                "SHADOW_READ_ONLY_BLOCKED_EMERGENCY_LIQUIDATION: broker mutation remains disabled"
            )
            with self._lock:
                self._state.is_emergency_liquidation_in_progress = False
            return
        if self._state.is_emergency_liquidation_in_progress:
            logger.warning("Emergency liquidation already in progress")
            return

        with self._lock:
            self._state.is_emergency_liquidation_in_progress = True
            order_ids = list(self._state.pending_orders.keys())
            self._state.pending_orders.clear()

        logger.critical("EMERGENCY LIQUIDATION: FIRE-AND-FORGET for %d orders", len(order_ids))

        if order_ids:
            max_workers = min(self.emergency_cancel_workers, len(order_ids))
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
            for order_id in order_ids:
                executor.submit(self._emergency_cancel_order, order_id)
            executor.shutdown(wait=False)
            self._emergency_executor = executor

        try:
            self.order_router.close_all_positions()
            logger.critical("EMERGENCY LIQUIDATION: MARKET SELL COMMANDS ISSUED")
        except Exception as e:
            logger.error("Emergency liquidation execution failed: %s", e)

        try:
            remaining = self.order_router.get_actual_positions()
            if remaining:
                logger.critical("WARNING: %d positions remain after liquidation", len(remaining))
        except Exception:
            pass

        with self._lock:
            self._state.is_emergency_liquidation_in_progress = False
            self._state.is_running = False

        logger.critical("EMERGENCY LIQUIDATION COMPLETE")

    def _emergency_cancel_order(self, order_id: str) -> None:
        """Fire-and-forget cancel helper."""
        if self.shadow_read_only:
            logger.info(
                "[EXEC_DIAG] SHADOW_READ_ONLY_BLOCKED_EMERGENCY_CANCEL: order_id=%s",
                order_id,
            )
            return
        try:
            self.order_router.cancel_order(order_id)
        except Exception as e:
            logger.debug("Emergency cancel failed for %s: %s", order_id, e)

    def _normal_cancel_all_orders(self) -> None:
        """Normal mode cancellation with PCV."""
        with self._lock:
            order_ids = list(self._state.pending_orders.keys())

        for order_id in order_ids:
            self._cancel_pending_order_with_pcv(order_id)

    # ============================================
    # RISK GUARD CALLBACKS
    # ============================================

    def _on_recalibration(self) -> None:
        """Handle recalibration trigger - normal mode with PCV."""
        logger.warning("RECALIBRATION TRIGGERED: Pausing trading")
        self._state.is_in_recalibration = True
        self._state.recalibration_until_ns = now_ns() + self._recalibration_pause_ns
        self._normal_cancel_all_orders()

    def _on_emergency(self) -> None:
        """Handle emergency trigger - fire-and-forget."""
        logger.critical("EMERGENCY TRIGGERED: Fire-and-forget liquidation")
        self._emergency_liquidate_all()

    def _on_zombie_detected(self) -> None:
        """Handle zombie order detection - normal mode with PCV."""
        logger.warning("ZOMBIE ORDERS DETECTED: Sweeping...")
        self._sweep_zombie_orders()

    def _on_lag_detected(self) -> None:
        """Handle lag detection."""
        logger.warning("LAG DETECTED: Entering safe mode")
        if not self._state.is_in_safe_mode or self._state.safe_mode_entered_at_ns <= 0:
            self._state.safe_mode_entered_at_ns = now_ns()
        self._state.is_in_safe_mode = True
        self._state.safe_mode_recovery_state = "LAG_DETECTED"

    def _on_vol_fuse(self) -> None:
        """Handle VoL fuse trigger - fire-and-forget."""
        logger.critical("VoL FUSE TRIGGERED: Fire-and-forget liquidation")
        self._emergency_liquidate_all()

    # ============================================
    # BACKGROUND THREADS
    # ============================================

    def _zombie_sweeper_loop(self) -> None:
        """Background thread for zombie order sweeping."""
        while self._state.is_running:
            try:
                time.sleep(self.zombie_sweep_interval_sec)
                self._sweep_zombie_orders()
            except Exception as e:
                self._zombie_sweeper_errors += 1
                logger.error(
                    "Zombie sweeper error: %s reason_code=%s",
                    e,
                    OmsReasonCode.ZOMBIE_SWEEP_FAILED.value,
                )

    def _normalize_timestamp_ns(self, value: Any) -> int:
        if value is None:
            return 0
        if isinstance(value, datetime):
            dt = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * NS_PER_SECOND)
        try:
            candidate = int(value)
        except (TypeError, ValueError):
            return 0
        if candidate <= 0:
            return 0
        if candidate < 10_000_000_000:
            return candidate * NS_PER_SECOND
        if candidate < 10_000_000_000_000:
            return candidate * NS_PER_MS
        return candidate

    def _extract_order_timestamp_ns(self, order: OrderRequest) -> int:
        """Extract best available authoritative timestamp from pending order."""
        exchange_ts_ns = self._normalize_timestamp_ns(getattr(order, "exchange_ts_ns", 0))
        receive_ts_ns = self._normalize_timestamp_ns(getattr(order, "receive_ts_ns", 0))
        if exchange_ts_ns > 0:
            return exchange_ts_ns
        if receive_ts_ns > 0:
            return receive_ts_ns
        return 0

    def _sweep_zombie_orders(self) -> None:
        """Sweep and cancel zombie orders (normal mode with PCV)."""
        current_ns = now_ns()

        with self._lock:
            zombie_orders: List[str] = []
            for order_id, order in self._state.pending_orders.items():
                order_ts_ns = self._extract_order_timestamp_ns(order)
                if order_ts_ns > 0 and (current_ns - order_ts_ns) > self._max_pending_age_ns:
                    zombie_orders.append(order_id)

        for order_id in zombie_orders:
            self._cancel_pending_order_with_pcv(order_id)

        with self._lock:
            oldest_ts_ns: Optional[int] = None
            for order in self._state.pending_orders.values():
                order_ts_ns = self._extract_order_timestamp_ns(order)
                if order_ts_ns <= 0:
                    continue
                if oldest_ts_ns is None or order_ts_ns < oldest_ts_ns:
                    oldest_ts_ns = order_ts_ns

            total_value = sum(o.quantity * (o.limit_price or Decimal("0")) for o in self._state.pending_orders.values())
            self.risk_guard.update_pending_orders(
                count=len(self._state.pending_orders),
                total_value=float(total_value),  # explicit float() at risk boundary — risk_guard is out of F4A scope
                oldest_timestamp=oldest_ts_ns,
            )

    def _monitor_loop(self) -> None:
        """Background thread for latency monitoring."""
        while self._state.is_running:
            try:
                if hasattr(self.order_router, "get_latency_measurement"):
                    measured_latency = self.order_router.get_latency_measurement()
                else:
                    measured_latency = self.order_router.measure_latency()
                latency_truth = self._classify_latency_truth(measured_latency)
                self._apply_latency_truth(latency_truth)

                if self.order_router.is_websocket_connected():
                    self.risk_guard.update_websocket_heartbeat()

                self._state.last_health_check_ns = now_ns()
                time.sleep(1.0)
            except Exception as e:
                logger.error("Monitor loop error: %s", e)
                time.sleep(5.0)

    def _executor_loop(self) -> None:
        """Background thread for executing queued signals with TTL."""
        while self._state.is_running:
            try:
                try:
                    queued = self._execution_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                self._execute_signal(queued)
            except Exception as e:
                logger.error("Executor loop error: %s", e)
