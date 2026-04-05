"""
Execution Engine - The "Body" of the Poverty Killer
SOVEREIGN GRADE - Final Version
HARDENED with:
- FIRE-AND-FORGET Emergency Liquidation using NON-BLOCKING ThreadPoolExecutor
- Signal TTL (500ms) - rejects signals older than 500ms
- Price Sanity Check - rejects if price moved >2% while in queue
- Regime Re-validation - checks if regime changed during queue
- Full risk guard integration
- Maker fee priority in Attack Mode
"""

import logging
import time
import threading
import queue
import signal
import sys
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
import concurrent.futures

from app.models import OrderRequest, OrderFill, StrategySignal
from app.risk.guard import HybridRiskGuard
from app.execution.masking_layer import MaskingLayer
from app.execution.order_router import OrderRouter
from app.commander import Commander
from app.brain.data_validator import DataContinuityValidator

logger = logging.getLogger(__name__)


@dataclass
class ExecutionState:
    """Current execution state."""
    is_running: bool = False
    is_in_safe_mode: bool = False
    is_in_recalibration: bool = False
    recalibration_until: Optional[datetime] = None
    last_latency_ms: float = 0.0
    pending_orders: Dict[str, OrderRequest] = field(default_factory=dict)
    filled_orders: List[OrderFill] = field(default_factory=list)
    last_health_check: Optional[datetime] = None
    last_equity: float = 0.0
    last_regime: str = "unknown"
    is_emergency_liquidation_in_progress: bool = False

    __slots__ = ("is_running", "is_in_safe_mode", "is_in_recalibration",
                 "recalibration_until", "last_latency_ms", "pending_orders",
                 "filled_orders", "last_health_check", "last_equity", "last_regime",
                 "is_emergency_liquidation_in_progress")


@dataclass
class QueuedSignal:
    """Signal stored in execution queue with metadata."""
    signal: StrategySignal
    is_attack: bool
    enqueue_time: datetime
    enqueue_price: float
    enqueue_regime: str

    __slots__ = ("signal", "is_attack", "enqueue_time", "enqueue_price", "enqueue_regime")


class ExecutionEngine:
    """
    Tactical Execution Engine - Sovereign Grade.
    
    Features:
    - Signal TTL (500ms) - rejects stale signals
    - Price Sanity Check - rejects if price moved >2% while in queue
    - Regime Re-validation - checks if regime changed during queue
    - FIRE-AND-FORGET Emergency Liquidation - NON-BLOCKING ThreadPoolExecutor
    - Velocity-of-Loss Fuse (4% in 60 seconds = emergency shutdown)
    - Post-Cancellation Verification (PCV) - normal mode only
    - Zombie Order Sweeper (auto-cancel stuck orders)
    - Lag Monitoring (auto-safe mode on high latency)
    - Maker fee priority in Attack Mode
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
        emergency_cancel_workers: int = 10
    ):
        """
        Initialize execution engine.

        Args:
            commander: Global commander for attack mode
            risk_guard: Hybrid risk guard for safety checks
            order_router: Order router for exchange communication
            masking_layer: Stochastic masking for execution camouflage
            data_validator: Data continuity validator for market health
            signal_ttl_ms: Max time signal can stay in queue (milliseconds)
            price_sanity_threshold_pct: Max price movement before rejecting signal
            zombie_sweep_interval_sec: How often to check for zombie orders
            max_pending_age_sec: Max age for pending orders before cancellation
            lag_threshold_ms: Latency threshold before auto-safe mode
            recalibration_pause_sec: How long to pause after floor breach
            maker_offset_pct: Offset from mid price for maker orders (0.1%)
            emergency_cancel_workers: Max threads for emergency cancel pool
        """
        self.commander = commander
        self.risk_guard = risk_guard
        self.order_router = order_router
        self.masking_layer = masking_layer
        self.data_validator = data_validator

        self.signal_ttl_ms = signal_ttl_ms
        self.price_sanity_threshold_pct = price_sanity_threshold_pct
        self.zombie_sweep_interval_sec = zombie_sweep_interval_sec
        self.max_pending_age_sec = max_pending_age_sec
        self.lag_threshold_ms = lag_threshold_ms
        self.recalibration_pause_sec = recalibration_pause_sec
        self.maker_offset_pct = maker_offset_pct
        self.emergency_cancel_workers = emergency_cancel_workers

        self._state = ExecutionState()
        self._execution_queue: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._sweeper_thread: Optional[threading.Thread] = None
        self._monitor_thread: Optional[threading.Thread] = None
        self._executor_thread: Optional[threading.Thread] = None
        self._emergency_executor: Optional[concurrent.futures.ThreadPoolExecutor] = None

        # Register callbacks with risk guard
        self.risk_guard.register_recalibrate_callback(self._on_recalibration)
        self.risk_guard.register_emergency_callback(self._on_emergency)
        self.risk_guard.register_zombie_callback(self._on_zombie_detected)
        self.risk_guard.register_lag_callback(self._on_lag_detected)
        self.risk_guard.register_vol_fuse_callback(self._on_vol_fuse)

        logger.info(f"ExecutionEngine initialized: signal_ttl={signal_ttl_ms}ms, "
                   f"price_sanity={price_sanity_threshold_pct:.1%}, "
                   f"emergency_workers={emergency_cancel_workers}, "
                   f"maker_offset={maker_offset_pct:.2%}")

    # ============================================
    # PUBLIC METHODS
    # ============================================

    def start(self) -> None:
        """Start execution engine threads."""
        if self._state.is_running:
            return

        self._state.is_running = True
        self._state.last_health_check = datetime.utcnow()

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

    def update_equity(self, current_equity: float) -> None:
        """Update current equity for VoL tracking."""
        with self._lock:
            self._state.last_equity = current_equity
        self.risk_guard.update_equity_history(current_equity)

    def update_regime(self, regime: str) -> None:
        """Update current regime for stale signal detection."""
        with self._lock:
            self._state.last_regime = regime

    def submit_signal(self, signal: StrategySignal, current_price: float, is_attack: bool) -> bool:
        """
        Submit a trading signal for execution with TTL and sanity checks.

        Args:
            signal: Strategy signal to execute
            current_price: Current market price at submission time
            is_attack: Whether in attack mode

        Returns:
            True if accepted, False if rejected
        """
        if not self._state.is_running:
            return False

        if self._state.is_in_recalibration:
            if self._state.recalibration_until and datetime.utcnow() < self._state.recalibration_until:
                return False
            else:
                self._state.is_in_recalibration = False
                self._state.recalibration_until = None

        if self._state.is_in_safe_mode:
            return False

        if not self.risk_guard.can_trade():
            return False

        if self.risk_guard.is_vol_fuse_triggered():
            return False

        if self.data_validator and not self.data_validator.is_data_healthy(signal.symbol):
            return False

        expected_net_profit = self._calculate_signal_net_profit(signal)
        if expected_net_profit < 0.005:
            return False

        queued_signal = QueuedSignal(
            signal=signal,
            is_attack=is_attack,
            enqueue_time=datetime.utcnow(),
            enqueue_price=current_price,
            enqueue_regime=self._state.last_regime
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
                "recalibration_until": self._state.recalibration_until.isoformat() if self._state.recalibration_until else None,
                "last_latency_ms": self._state.last_latency_ms,
                "pending_orders_count": len(self._state.pending_orders),
                "pending_orders_value": sum(o.quantity * (o.limit_price or 0) for o in self._state.pending_orders.values()),
                "filled_orders_count": len(self._state.filled_orders),
                "execution_queue_size": self._execution_queue.qsize(),
                "last_equity": self._state.last_equity,
                "last_regime": self._state.last_regime
            }

    # ============================================
    # INTERNAL METHODS
    # ============================================

    def _calculate_signal_net_profit(self, signal: StrategySignal) -> float:
        expected_move = 0.02
        if signal.metadata and "expected_move" in signal.metadata:
            expected_move = signal.metadata["expected_move"]
        gross_ev = expected_move * signal.confidence
        total_costs = (0.26 + 0.10) / 100
        return gross_ev - total_costs

    def _validate_signal_before_execution(self, queued: QueuedSignal, current_price: float) -> Tuple[bool, str]:
        """Validate signal before execution with TTL, price sanity, and regime checks."""
        age_ms = (datetime.utcnow() - queued.enqueue_time).total_seconds() * 1000
        if age_ms > self.signal_ttl_ms:
            return False, f"stale: {age_ms:.1f}ms"

        price_change_pct = abs(current_price - queued.enqueue_price) / queued.enqueue_price
        if price_change_pct > self.price_sanity_threshold_pct:
            return False, f"price_moved: {price_change_pct:.2%}"

        if self._state.last_regime and queued.enqueue_regime:
            if self._state.last_regime != queued.enqueue_regime:
                severe = (
                    (queued.enqueue_regime == "trending" and self._state.last_regime == "crisis") or
                    (queued.enqueue_regime == "crisis" and self._state.last_regime == "trending")
                )
                if severe:
                    return False, f"regime_changed: {queued.enqueue_regime} -> {self._state.last_regime}"

        if self.data_validator and not self.data_validator.is_data_healthy(queued.signal.symbol):
            return False, "data_unhealthy"

        return True, "ok"

    def _execute_signal(self, queued: QueuedSignal) -> None:
        """Execute a trading signal after validation."""
        signal = queued.signal
        is_attack = queued.is_attack
        current_price = self.order_router.get_mid_price(signal.symbol)

        is_valid, reason = self._validate_signal_before_execution(queued, current_price)
        if not is_valid:
            logger.warning(f"Signal rejected: {signal.id} - {reason}")
            return

        masked = self.masking_layer.mask_order(signal.quantity)

        order = OrderRequest(
            id=f"{signal.strategy}_{signal.symbol}_{int(time.time() * 1000)}",
            symbol=signal.symbol,
            side=signal.side,
            quantity=masked.masked_size,
            order_type="limit" if is_attack else "market",
            limit_price=signal.price,
            strategy=signal.strategy,
            confidence=signal.confidence,
            metadata={"original_size": signal.quantity, "masked_size": masked.masked_size, "is_attack": is_attack}
        )

        if order.order_type == "limit" and current_price > 0:
            if order.side == "buy":
                order.limit_price = current_price * (1 - self.maker_offset_pct)
            else:
                order.limit_price = current_price * (1 + self.maker_offset_pct)

        try:
            fill = self.order_router.submit_order(order)
            if fill:
                with self._lock:
                    self._state.filled_orders.append(fill)
                self.risk_guard.record_fees(fill.fee)
            else:
                with self._lock:
                    self._state.pending_orders[order.id] = order
        except Exception as e:
            logger.error(f"Order submission failed: {e}")

    # ============================================
    # PCV FOR NORMAL OPERATIONS
    # ============================================

    def _cancel_pending_order_with_pcv(self, order_id: str) -> bool:
        """Cancel a pending order with PCV. ONLY for normal operations."""
        try:
            cancel_success = self.order_router.cancel_order(order_id)
            if not cancel_success:
                return False

            for attempt in range(5):
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
            logger.error(f"PCV cancellation failed: {e}")
            return False

    # ============================================
    # FIRE-AND-FORGET EMERGENCY LIQUIDATION - NON-BLOCKING
    # ============================================

    def _emergency_liquidate_all(self) -> None:
        """
        EMERGENCY LIQUIDATION - FIRE-AND-FORGET SEQUENCE.
        NON-BLOCKING ThreadPoolExecutor with shutdown(wait=False).
        No sequential sleep. No PCV. Instantly flatten the portfolio.
        """
        if self._state.is_emergency_liquidation_in_progress:
            logger.warning("Emergency liquidation already in progress")
            return

        with self._lock:
            self._state.is_emergency_liquidation_in_progress = True
            order_ids = list(self._state.pending_orders.keys())
            self._state.pending_orders.clear()

        logger.critical(f"EMERGENCY LIQUIDATION: FIRE-AND-FORGET for {len(order_ids)} orders")

        # Step 1: Fire-and-Forget cancellations using NON-BLOCKING ThreadPoolExecutor
        if order_ids:
            max_workers = min(self.emergency_cancel_workers, len(order_ids))
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
            
            for order_id in order_ids:
                executor.submit(self._emergency_cancel_order, order_id)
            
            # CRITICAL: wait=False ensures the main thread does NOT block
            executor.shutdown(wait=False)
            self._emergency_executor = executor

        # Step 2: Instantly flatten positions (no waiting for cancel threads)
        try:
            self.order_router.close_all_positions()
            logger.critical("EMERGENCY LIQUIDATION: MARKET SELL COMMANDS ISSUED")
        except Exception as e:
            logger.error(f"Emergency liquidation execution failed: {e}")

        # Step 3: Quick non-blocking check
        try:
            remaining = self.order_router.get_actual_positions()
            if remaining:
                logger.critical(f"WARNING: {len(remaining)} positions remain after liquidation")
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
            logger.debug(f"Emergency cancel failed for {order_id}: {e}")

    def _normal_cancel_all_orders(self) -> None:
        """Normal mode cancellation with PCV. Used for recalibration, not emergencies."""
        with self._lock:
            order_ids = list(self._state.pending_orders.keys())

        for order_id in order_ids:
            self._cancel_pending_order_with_pcv(order_id)

    # ============================================
    # RISK GUARD CALLBACKS
    # ============================================

    def _on_recalibration(self) -> None:
        """Handle recalibration trigger - NORMAL MODE with PCV."""
        logger.warning("RECALIBRATION TRIGGERED: Pausing trading")
        self._state.is_in_recalibration = True
        self._state.recalibration_until = datetime.utcnow() + timedelta(seconds=self.recalibration_pause_sec)
        self._normal_cancel_all_orders()

    def _on_emergency(self) -> None:
        """Handle emergency trigger - FIRE-AND-FORGET."""
        logger.critical("EMERGENCY TRIGGERED: Fire-and-forget liquidation")
        self._emergency_liquidate_all()

    def _on_zombie_detected(self) -> None:
        """Handle zombie order detection - NORMAL MODE with PCV."""
        logger.warning("ZOMBIE ORDERS DETECTED: Sweeping...")
        self._sweep_zombie_orders()

    def _on_lag_detected(self) -> None:
        """Handle lag detection."""
        logger.warning("LAG DETECTED: Entering safe mode")
        self._state.is_in_safe_mode = True

    def _on_vol_fuse(self) -> None:
        """Handle VoL fuse trigger - FIRE-AND-FORGET."""
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
                logger.error(f"Zombie sweeper error: {e}")

    def _sweep_zombie_orders(self) -> None:
        """Sweep and cancel zombie orders (normal mode with PCV)."""
        with self._lock:
            zombie_orders = []
            for order_id, order in self._state.pending_orders.items():
                if (datetime.utcnow() - order.timestamp).total_seconds() > self.max_pending_age_sec:
                    zombie_orders.append(order_id)

        for order_id in zombie_orders:
            self._cancel_pending_order_with_pcv(order_id)

        with self._lock:
            oldest_ts = None
            for order in self._state.pending_orders.values():
                if oldest_ts is None or order.timestamp < oldest_ts:
                    oldest_ts = order.timestamp
            total_value = sum(o.quantity * (o.limit_price or 0) for o in self._state.pending_orders.values())
            self.risk_guard.update_pending_orders(
                count=len(self._state.pending_orders),
                total_value=total_value,
                oldest_timestamp=oldest_ts
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
                    logger.info(f"Latency recovered: {latency:.1f}ms, exiting safe mode")

                if self.order_router.is_websocket_connected():
                    self.risk_guard.update_websocket_heartbeat()

                self._state.last_health_check = datetime.utcnow()
                time.sleep(1.0)
            except Exception as e:
                logger.error(f"Monitor loop error: {e}")
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
                logger.error(f"Executor loop error: {e}")