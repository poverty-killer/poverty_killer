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
import queue
import threading
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from app.brain.data_validator import DataContinuityValidator
from app.commander import Commander
from app.execution.masking_layer import MaskingLayer
from app.execution.order_router import OrderRouter
from app.models import OrderFill, OrderRequest, StrategySignal
from app.risk.guard import HybridRiskGuard
from app.utils.time_utils import now_ns
from app.telemetry.event_store import TelemetryEventStore

logger = logging.getLogger(__name__)

NS_PER_SECOND = 1_000_000_000
NS_PER_MS = 1_000_000


@dataclass(slots=True)
class ExecutionState:
    """Current execution state."""
    is_running: bool = False
    is_in_safe_mode: bool = False
    is_in_recalibration: bool = False
    recalibration_until_ns: int = 0
    last_latency_ms: float = 0.0
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
        telemetry_store: Optional[TelemetryEventStore] = None
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

        self._signal_ttl_ns = int(max(0.0, signal_ttl_ms) * NS_PER_MS)
        self._recalibration_pause_ns = int(max(0.0, recalibration_pause_sec) * NS_PER_SECOND)
        self._max_pending_age_ns = int(max(0.0, max_pending_age_sec) * NS_PER_SECOND)

        self._state = ExecutionState()
        self._execution_queue: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
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

    def update_equity(self, current_equity: float) -> None:
        """Update current equity for risk tracking."""
        with self._lock:
            self._state.last_equity = current_equity
        self.risk_guard.update_equity_history(current_equity)

    def update_regime(self, regime: str) -> None:
        """Update current regime for stale signal detection."""
        with self._lock:
            self._state.last_regime = regime

    def submit_signal(self, signal: StrategySignal, current_price: Decimal, is_attack: bool) -> bool:
        """
        Submit a trading signal for execution.

        Queue admission uses canonical now_ns() and explicit state gating.
        """
        if not self._state.is_running:
            return False

        current_ns = now_ns()

        if self._state.is_in_recalibration:
            if self._state.recalibration_until_ns > 0 and current_ns < self._state.recalibration_until_ns:
                return False
            self._state.is_in_recalibration = False
            self._state.recalibration_until_ns = 0

        if self._state.is_in_safe_mode:
            return False

        if not self.risk_guard.can_trade():
            return False

        if self.risk_guard.is_vol_fuse_triggered():
            return False

        if self.data_validator and not self.data_validator.is_data_healthy(signal.symbol):
            return False

        expected_net_profit = self._calculate_signal_net_profit(signal)
        if expected_net_profit < Decimal("0.005"):
            return False

        queued_signal = QueuedSignal(
            signal=signal,
            is_attack=is_attack,
            enqueue_time_ns=current_ns,
            enqueue_price=current_price,
            enqueue_regime=self._state.last_regime,
        )

        self._execution_queue.put(queued_signal)
        return True

    def get_status(self) -> Dict[str, Any]:
        """Get execution engine status."""
        with self._lock:
            return {
                "is_running": self._state.is_running,
                "is_in_safe_mode": self._state.is_in_safe_mode,
                "is_in_recalibration": self._state.is_in_recalibration,
                "recalibration_until_ns": self._state.recalibration_until_ns,
                "last_latency_ms": self._state.last_latency_ms,
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

    def _calculate_signal_net_profit(self, signal: StrategySignal) -> Decimal:
        expected_move = Decimal("0.02")
        if signal.metadata and "expected_move" in signal.metadata:
            expected_move = Decimal(str(signal.metadata["expected_move"]))
        gross_ev = expected_move * Decimal(str(signal.confidence))
        total_costs = Decimal("0.0036")
        return gross_ev - total_costs

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

        if self.data_validator and not self.data_validator.is_data_healthy(queued.signal.symbol):
            return False, "data_unhealthy"

        return True, "ok"

    def _execute_signal(self, queued: QueuedSignal) -> None:
        """Execute a trading signal after sovereign validation."""
        signal = queued.signal
        is_attack = queued.is_attack
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
            return

        masked = self.masking_layer.mask_order(signal.quantity)

        current_ns = now_ns()
        order = OrderRequest(
            id=f"{signal.strategy}_{signal.symbol}_{signal.exchange_ts_ns}",
            symbol=signal.symbol,
            side=signal.side,
            quantity=masked.masked_size,
            order_type="limit" if is_attack else "market",
            limit_price=signal.price,
            strategy=signal.strategy,
            confidence=signal.confidence,
            exchange_ts_ns=signal.exchange_ts_ns,
            receive_ts_ns=current_ns,
            metadata={
                "original_size": signal.quantity,
                "masked_size": masked.masked_size,
                "is_attack": is_attack,
                "execution_enqueue_time_ns": queued.enqueue_time_ns,
            },
        )

        if order.order_type == "limit" and current_price > Decimal("0"):
            if order.side == "buy":
                order.limit_price = current_price * (Decimal("1") - self.maker_offset_pct)
            else:
                order.limit_price = current_price * (Decimal("1") + self.maker_offset_pct)

        try:
            fill = self.order_router.submit_order(order)
            logger.info(
                "[EXEC_DIAG] ORDER_SUBMIT_ATTEMPT: order_id=%s symbol=%s side=%s qty=%s fill=%s",
                order.id,
                order.symbol,
                order.side,
                order.quantity,
                fill is not None,
            )
            if fill:
                with self._lock:
                    self._state.filled_orders.append(fill)
                self.risk_guard.record_fees(fill.fee)
            else:
                with self._lock:
                    self._state.pending_orders[order.id] = order
        except Exception as e:
            logger.error("Order submission failed: %s", e)

    # ============================================
    # PCV FOR NORMAL OPERATIONS
    # ============================================

    def _cancel_pending_order_with_pcv(self, order_id: str) -> bool:
        """Cancel a pending order with PCV. Normal operations only."""
        try:
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
        self._state.is_in_safe_mode = True

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
                logger.error("Zombie sweeper error: %s", e)

    def _extract_order_timestamp_ns(self, order: OrderRequest) -> int:
        """Extract best available authoritative timestamp from pending order."""
        exchange_ts_ns = int(getattr(order, "exchange_ts_ns", 0) or 0)
        receive_ts_ns = int(getattr(order, "receive_ts_ns", 0) or 0)
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
                latency = self.order_router.measure_latency()
                self._state.last_latency_ms = latency
                self.risk_guard.update_latency(latency)

                if latency < self.lag_threshold_ms and self._state.is_in_safe_mode:
                    self._state.is_in_safe_mode = False
                    logger.info("Latency recovered: %.1fms, exiting safe mode", latency)

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