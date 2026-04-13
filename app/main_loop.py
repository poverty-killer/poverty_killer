"""
Main Loop - Sovereign Market-Data / Brain / State / Risk-Ingress Pipeline

Role:
    MainLoop is the authoritative upstream event-processing core.
    It receives market data ticks and drives:
        1. Data continuity validation
        2. Signal brain updates (TPE, Shan's Curve, whale, regime, fusion state)
        3. Risk state assessment (guard, VoL, recalibration)
        4. Recalibration state machine advancement
        5. Emergency liquidation gate (CRISIS_ABORT / EMERGENCY_HALT only)
        6. Execution engine event drain (process_events only)
        7. Health logging and diagnostics

    Signal submission boundary:
        MainLoop does NOT submit execution signals.
        StrategySignal construction, StrategyVote aggregation,
        DecisionCompiler, OrderIntent, and ExecutionEngine.submit_signal()
        belong to a separate downstream layer not yet authorized.
        This boundary is explicitly documented and enforced.

Integration note:
    MainLoop is a standalone class. Feed adapters (WebSocket clients,
    REST pollers) must call on_order_book / on_candle / on_trade /
    on_equity_update to drive the pipeline. Wiring from main.py is
    a separate authorized pass.

Timing authority:
    - All exchange timestamps come from market data (authoritative int ns)
    - Wall-clock time.time_ns() used ONLY for receive-side latency tracking
    - No random number generation
    - DataContinuityValidator.record_data() requires datetime at its boundary;
      conversion from ns is performed locally via datetime.utcfromtimestamp()
"""

import logging
import time
import threading
from datetime import datetime
from typing import Optional, Dict, Any
from dataclasses import dataclass

from app.config import Config
from app.commander import Commander
from app.risk.guard import HybridRiskGuard
from app.brain.signal_fusion import SignalFusion
from app.brain.data_validator import DataContinuityValidator
from app.brain.recalibrator import Recalibrator
from app.brain.topological_engine import TopologicalEngine, TopologicalSignal
from app.execution.engine import ExecutionEngine
from app.models import (
    OrderBookSnapshot,
    Candle,
    FusionDecision,
)

logger = logging.getLogger(__name__)


def _ns_to_datetime(ns: int) -> datetime:
    """
    Convert nanosecond timestamp to UTC datetime.

    Used only at DataContinuityValidator boundary which requires datetime.
    All internal state uses int nanoseconds.
    """
    return datetime.utcfromtimestamp(ns / 1_000_000_000.0)


@dataclass
class LoopMetrics:
    """
    Per-iteration metrics for the main loop.
    All counters are monotonically increasing.
    """
    iteration_count: int = 0
    last_candle_exchange_ts_ns: int = 0
    last_order_book_exchange_ts_ns: int = 0
    last_trade_exchange_ts_ns: int = 0
    last_equity_update_ns: int = 0
    last_risk_assessment_ns: int = 0
    last_recalibration_check_ns: int = 0
    last_health_log_iteration: int = 0
    consecutive_errors: int = 0
    emergency_liquidations: int = 0
    recalibration_entries: int = 0
    recalibration_exits: int = 0


class MainLoop:
    """
    Sovereign Market-Data / Brain / State / Risk-Ingress Pipeline.

    Proven collaborator contracts (all verified from live repo):

    OrderBookSnapshot (app/models/market_data.py):
        Fields: symbol, exchange_ts_ns, bids, asks, exchange_latency_ns
        Properties: mid_price, best_bid, best_ask, spread, spread_bps,
                    depth_at_levels(n), imbalance
        NO total_bid_liquidity_usd — does not exist

    FusionDecision (app/models/fusion.py):
        Fields: exchange_ts_ns, attack_mode, confidence,
                shadow_front_eligible, liquidity_void_eligible,
                entropy_decoder_eligible, gamma_front_eligible,
                sector_rotation_eligible, preferred_sleeve, deprioritized_sleeves,
                reason, regime, physical_verification_score,
                shans_superfluid_score, shans_bias, shans_confidence
        NO side, quantity, expected_net_profit_pct — do not exist

    DataContinuityValidator (app/brain/data_validator.py):
        Methods: record_data(symbol, timestamp: datetime),
                 mark_good(symbol), is_data_healthy(symbol),
                 record_websocket_heartbeat(symbol)
        NO update_heartbeat — does not exist

    SignalFusion.get_macro_signal(exchange_ts_ns: int, whale_score: float):
        whale_score is a FLOOR value, not the sole input.
        Implementation: effective = max(whale_score, cached_whale.score) when fresh.
        Passing 0.0 is correct: update_whale() runs immediately before on the same
        tick, so cached_whale is always fresh. max(0.0, cached_score) = cached_score.
        Passing any positive value would artificially inflate above cache truth.

    HybridRiskGuard (app/risk/guard.py):
        assess_state(current_equity: float, tpe_coherence: float) -> Dict
        update_equity_history(current_equity: float)
        can_trade() -> bool

    Recalibrator (app/brain/recalibrator.py):
        evaluate_regime(price_drop_pct, tpe_signal, drop_duration_sec) -> str
        start_recalibration(reason, duration_seconds)
        end_recalibration()
        should_recover() -> bool
        is_in_recalibration() -> bool
        get_recalibration_remaining() -> float
        get_recovery_strategy() -> Dict
        min_recalibration_seconds: float (attribute)

    ExecutionEngine (app/execution/engine.py):
        process_events() — drain the execution queue, no signal submission
        update_equity(current_equity: float)
        _emergency_liquidate_all() — fire-and-forget, non-blocking

    Commander (app/commander.py):
        update_equity(current_equity: float, timestamp_ns: int)
        is_attack_mode() -> bool
        get_kelly_multiplier() -> float
        get_status() -> Dict
    """

    def __init__(
        self,
        config: Config,
        commander: Commander,
        risk_guard: HybridRiskGuard,
        signal_fusion: SignalFusion,
        data_validator: DataContinuityValidator,
        recalibrator: Recalibrator,
        tpe_engine: TopologicalEngine,
        execution_engine: ExecutionEngine,
        symbol: str,
        health_log_interval_iterations: int = 600,
    ):
        """
        Initialize the main loop.

        Args:
            config: Configuration object
            commander: Global commander (attack mode, Kelly multiplier)
            risk_guard: Hybrid risk guard (equity, VoL, fuses)
            signal_fusion: Signal fusion brain
            data_validator: Data continuity validator
            recalibrator: Topological recalibration engine
            tpe_engine: Topological persistence engine
            execution_engine: Execution engine (event drain only)
            symbol: Primary trading symbol
            health_log_interval_iterations: Health log cadence in candle ticks
        """
        self.config = config
        self.commander = commander
        self.risk_guard = risk_guard
        self.signal_fusion = signal_fusion
        self.data_validator = data_validator
        self.recalibrator = recalibrator
        self.tpe_engine = tpe_engine
        self.execution_engine = execution_engine
        self.symbol = symbol
        self.health_log_interval_iterations = health_log_interval_iterations

        # Per-tick state — all guarded by _lock
        self._last_order_book: Optional[OrderBookSnapshot] = None
        self._last_candle: Optional[Candle] = None
        self._last_tpe_signal: Optional[TopologicalSignal] = None
        self._last_equity: float = config.initial_capital
        self._last_price: float = 0.0
        self._last_fusion: Optional[FusionDecision] = None
        self._last_risk_state: Optional[Dict[str, Any]] = None

        # Recalibration state machine
        self._recalibration_active: bool = False
        self._recalibration_start_ns: int = 0

        self._metrics = LoopMetrics()
        self._lock = threading.Lock()
        self._running = False

        logger.info(
            "MainLoop initialized: symbol=%s, health_log_interval=%d",
            symbol, health_log_interval_iterations
        )

    # =========================================================================
    # LIFECYCLE
    # =========================================================================

    def start(self) -> None:
        """Mark loop as active. ExecutionEngine must be started separately."""
        self._running = True
        logger.info("MainLoop started: symbol=%s", self.symbol)

    def stop(self) -> None:
        """Mark loop as inactive."""
        self._running = False
        logger.info(
            "MainLoop stopped: symbol=%s, candle_iterations=%d, "
            "emergency_liquidations=%d, recalibration_entries=%d",
            self.symbol,
            self._metrics.iteration_count,
            self._metrics.emergency_liquidations,
            self._metrics.recalibration_entries,
        )

    # =========================================================================
    # MARKET DATA INGRESS — called by feed adapters
    # =========================================================================

    def on_order_book(self, order_book: OrderBookSnapshot) -> None:
        """
        Ingest an authoritative order book snapshot.

        Drives:
          - Data continuity record (record_data + mark_good)
          - TPE analysis (real coherence score for risk guard)
          - Signal fusion Shan's Curve update (cached state mutation)
          - Last price update from mid_price (proven @property)

        Proven fields used:
          exchange_ts_ns, mid_price (@property), depth_at_levels() (method)

        Args:
            order_book: Authoritative L2 order book snapshot
        """
        if not self._running:
            return

        receive_ns = time.time_ns()
        exchange_ts_ns = order_book.exchange_ts_ns

        with self._lock:
            self._last_order_book = order_book
            mid = order_book.mid_price  # proven @property
            if mid > 0.0:
                self._last_price = mid

        # Data continuity — record_data requires datetime boundary
        self.data_validator.record_data(
            self.symbol,
            _ns_to_datetime(exchange_ts_ns)
        )
        self.data_validator.mark_good(self.symbol)

        # TPE analysis — produces TopologicalSignal.coherence_score
        tpe_signal = self.tpe_engine.analyze(order_book)
        with self._lock:
            self._last_tpe_signal = tpe_signal

        # Shan's Curve — mutates signal_fusion cached state, return value unused
        self.signal_fusion.update_shans(
            order_book,
            self.signal_fusion.get_current_regime(),
            None
        )

        self._metrics.last_order_book_exchange_ts_ns = exchange_ts_ns

        # Receive-side latency tracking (wall-clock vs exchange timestamp)
        latency_ms = (receive_ns - exchange_ts_ns) / 1_000_000
        if latency_ms > 200.0:
            logger.warning(
                "Order book receive latency spike: %.1fms symbol=%s ts_ns=%d",
                latency_ms, self.symbol, exchange_ts_ns
            )

    def on_candle(self, candle: Candle) -> None:
        """
        Ingest an authoritative candle.

        Drives:
          - Whale flow update (mutates signal_fusion._cached_whale)
          - Regime update (mutates signal_fusion._cached_regime)
          - Macro + insider signal retrieval (float scores for fusion only)
          - Signal fusion (fuse() — for state tracking, not signal submission)
          - Commander equity sync
          - Risk state assessment with real TPE coherence
          - Recalibration state machine advancement
          - Execution engine event drain (process_events only)
          - Health logging

        Signal submission is NOT performed here.
        Fusion state is stored for downstream layer consumption via get_last_fusion().

        Args:
            candle: Authoritative OHLCV candle
        """
        if not self._running:
            return

        exchange_ts_ns = candle.exchange_ts_ns

        with self._lock:
            self._last_candle = candle
            if candle.close > 0.0:
                self._last_price = candle.close

        # Whale flow — update_whale() mutates _cached_whale, returns None
        self.signal_fusion.update_whale(candle)

        # Regime — update_regime() mutates _cached_regime, returns None
        # Liquidity: derived from proven depth_at_levels() on last order book
        # bid_depth and ask_depth are in base units; multiply by price for USD proxy
        with self._lock:
            ob = self._last_order_book
            last_price = self._last_price

        liquidity_usd: float = 0.0
        if ob is not None and last_price > 0.0:
            bid_depth, ask_depth = ob.depth_at_levels(10)  # proven method
            liquidity_usd = (bid_depth + ask_depth) * last_price

        self.signal_fusion.update_regime(
            [candle], 0, liquidity_usd, exchange_ts_ns
        )

        # Commander equity sync
        self.commander.update_equity(self._last_equity, exchange_ts_ns)

        # get_macro_signal(exchange_ts_ns: int, whale_score: float) -> float
        #
        # whale_score=0.0 is the provably correct floor value, not a fallback.
        #
        # Proof from signal_fusion.py get_macro_signal():
        #   effective_whale_score = whale_score  # starts at 0.0
        #   if self._cached_whale is not None and not stale:
        #       effective_whale_score = max(effective_whale_score, self._cached_whale.score)
        #
        # update_whale(candle) was called immediately above on this same tick,
        # so _cached_whale is always fresh (age = 0 << STALENESS_THRESHOLD_NS = 5s).
        # Therefore: effective_whale_score = max(0.0, cached_whale.score) = cached_whale.score.
        # Passing any positive value > 0 would inflate above cache truth.
        # 0.0 is the exact correct floor for the cache-dominates semantics.
        macro_score: float = self.signal_fusion.get_macro_signal(
            exchange_ts_ns, 0.0
        )

        # get_insider_signal() -> float: returns cached urgency if fresh, else 0.0
        insider_score: float = self.signal_fusion.get_insider_signal()

        # fuse() — produces FusionDecision for state tracking and downstream consumption
        # MainLoop does NOT use fusion output for signal submission
        with self._lock:
            ob_snapshot = self._last_order_book

        fusion: FusionDecision = self.signal_fusion.fuse(
            regime=None,           # reads from _cached_regime
            whale_score=None,      # reads from _cached_whale
            macro_signal=macro_score,
            insider_signal=insider_score,
            order_book=ob_snapshot
        )

        with self._lock:
            self._last_fusion = fusion

        self._metrics.iteration_count += 1
        self._metrics.last_candle_exchange_ts_ns = exchange_ts_ns

        # TPE coherence for risk guard — from last TPE signal or honest midpoint
        with self._lock:
            tpe_signal = self._last_tpe_signal

        tpe_coherence: float = (
            tpe_signal.coherence_score
            if tpe_signal is not None
            else 0.5  # no TPE data yet — honest midpoint, not a biased value
        )

        # Risk state assessment with real TPE coherence
        risk_state = self.risk_guard.assess_state(self._last_equity, tpe_coherence)
        with self._lock:
            self._last_risk_state = risk_state
        self._metrics.last_risk_assessment_ns = exchange_ts_ns

        # Recalibration state machine
        self._advance_recalibration(risk_state, tpe_signal, exchange_ts_ns)

        # Execution engine event drain — process_events() only, no signal submission
        self.execution_engine.process_events()

        # Health logging cadence
        if (self._metrics.iteration_count - self._metrics.last_health_log_iteration
                >= self.health_log_interval_iterations):
            self._log_health()
            self._metrics.last_health_log_iteration = self._metrics.iteration_count

        self._metrics.consecutive_errors = 0

    def on_trade(self, size: float, price: float, side: int, exchange_ts_ns: int) -> None:
        """
        Ingest an authoritative trade tick.

        Drives:
          - Data continuity record (record_data + mark_good)
          - Last price update

        Trade-level toxicity engine update is handled by the orchestrator
        (app/execution/orchestrator.py) which has direct ToxicityEngine access.
        MainLoop does not duplicate that path.

        Args:
            size: Trade size in base units
            price: Trade price in quote currency
            side: +1 for buy, -1 for sell
            exchange_ts_ns: Authoritative exchange nanosecond timestamp
        """
        if not self._running:
            return

        self.data_validator.record_data(
            self.symbol,
            _ns_to_datetime(exchange_ts_ns)
        )
        self.data_validator.mark_good(self.symbol)

        if price > 0.0:
            with self._lock:
                self._last_price = price

        self._metrics.last_trade_exchange_ts_ns = exchange_ts_ns

    def on_equity_update(self, current_equity: float, exchange_ts_ns: int) -> None:
        """
        Receive authoritative portfolio equity from exchange reconciliation.

        Drives:
          - Internal equity state update
          - HybridRiskGuard.update_equity_history() — VoL tracking
          - ExecutionEngine.update_equity() — equity sync
          - Commander.update_equity() — attack mode drawdown check

        All three proven from live repo:
          - HybridRiskGuard.update_equity_history(current_equity: float)
          - ExecutionEngine.update_equity(current_equity: float)
          - Commander.update_equity(current_equity: float, timestamp_ns: int)

        Args:
            current_equity: Total portfolio equity in USD
            exchange_ts_ns: Authoritative exchange nanosecond timestamp
        """
        if not self._running:
            return

        with self._lock:
            self._last_equity = current_equity

        self.risk_guard.update_equity_history(current_equity)
        self.execution_engine.update_equity(current_equity)
        self.commander.update_equity(current_equity, exchange_ts_ns)

        self._metrics.last_equity_update_ns = exchange_ts_ns
        # =========================================================================
    # RECALIBRATION STATE MACHINE
    # =========================================================================

    def _advance_recalibration(
        self,
        risk_state: Dict[str, Any],
        tpe_signal: Optional[TopologicalSignal],
        exchange_ts_ns: int,
    ) -> None:
        """
        Advance the recalibration state machine on every candle tick.

        State transitions (proven from Recalibrator live contract):
            NORMAL → EMERGENCY_LIQUIDATION:
                when risk_state["action"] == "EMERGENCY_HALT"
                OR recalibrator returns "CRISIS_ABORT"
            NORMAL → RECALIBRATING:
                when risk_state["action"] == "RECALIBRATE"
            RECALIBRATING → NORMAL:
                when recalibrator.should_recover() == True
                AND risk_state["action"] not in ("RECALIBRATE", "EMERGENCY_HALT")
            RECALIBRATING (extended):
                when should_recover() == True but conditions still unfavorable

        Proven Recalibrator methods used:
            evaluate_regime(price_drop_pct: float,
                            tpe_signal: Optional[TopologicalSignal],
                            drop_duration_sec: float) -> str
            start_recalibration(reason: str, duration_seconds: float)
            end_recalibration()
            should_recover() -> bool
            min_recalibration_seconds: float (attribute)

        Proven ExecutionEngine method used:
            _emergency_liquidate_all() — fire-and-forget, NON-BLOCKING ThreadPoolExecutor

        Args:
            risk_state: Output of risk_guard.assess_state()
            tpe_signal: Last TopologicalSignal or None
            exchange_ts_ns: Authoritative exchange nanosecond timestamp
        """
        action: str = risk_state.get("action", "AGGRESSIVE")
        drawdown_from_peak: float = risk_state.get("drawdown_from_peak", 0.0)

        # EMERGENCY_HALT — highest priority, bypasses recalibration
        if action == "EMERGENCY_HALT":
            if not self._recalibration_active:
                logger.critical(
                    "EMERGENCY_HALT from risk guard — initiating fire-and-forget "
                    "liquidation: drawdown=%.2f%% reason=%s",
                    drawdown_from_peak * 100,
                    risk_state.get("reason", "unknown")
                )
                self._metrics.emergency_liquidations += 1
                self.execution_engine._emergency_liquidate_all()
            return

        # Topological regime evaluation — real TPE geometry, not hardcoded
        drop_duration_sec: float = (
            (exchange_ts_ns - self._recalibration_start_ns) / 1_000_000_000.0
            if self._recalibration_active and self._recalibration_start_ns > 0
            else 0.0
        )

        regime_decision: str = self.recalibrator.evaluate_regime(
            price_drop_pct=drawdown_from_peak,
            tpe_signal=tpe_signal,
            drop_duration_sec=drop_duration_sec
        )

        # CRISIS_ABORT from recalibrator → emergency liquidation
        if regime_decision == "CRISIS_ABORT" and not self._recalibration_active:
            logger.critical(
                "CRISIS_ABORT from recalibrator — initiating fire-and-forget "
                "liquidation: drawdown=%.2f%% betti_1=%d persistence=%.3f",
                drawdown_from_peak * 100,
                tpe_signal.betti_1 if tpe_signal is not None else 0,
                tpe_signal.persistence_score if tpe_signal is not None else 0.0
            )
            self._metrics.emergency_liquidations += 1
            self.execution_engine._emergency_liquidate_all()
            return

        # Enter recalibration if risk guard demands it
        if action == "RECALIBRATE" and not self._recalibration_active:
            self._recalibration_active = True
            self._recalibration_start_ns = exchange_ts_ns
            self._metrics.recalibration_entries += 1
            self.recalibrator.start_recalibration(
                reason=risk_state.get("reason", "risk_guard_floor_breach"),
                duration_seconds=self.recalibrator.min_recalibration_seconds
            )
            logger.warning(
                "Recalibration STARTED: reason=%s drawdown=%.2f%% "
                "betti_1=%d coherence=%.3f",
                risk_state.get("reason", "unknown"),
                drawdown_from_peak * 100,
                tpe_signal.betti_1 if tpe_signal is not None else 0,
                tpe_signal.coherence_score if tpe_signal is not None else 0.0
            )

        # Advance recalibration: check if ready to exit
        if self._recalibration_active:
            if self.recalibrator.should_recover():
                if action not in ("RECALIBRATE", "EMERGENCY_HALT"):
                    self.recalibrator.end_recalibration()
                    self._recalibration_active = False
                    self._recalibration_start_ns = 0
                    self._metrics.recalibration_exits += 1
                    logger.info(
                        "Recalibration ENDED — resuming upstream pipeline: "
                        "action=%s drawdown=%.2f%%",
                        action, drawdown_from_peak * 100
                    )
                else:
                    # Conditions still unfavorable — extend recalibration
                    logger.info(
                        "Recalibration cooldown elapsed but conditions unfavorable "
                        "(action=%s) — extending by %.0fs",
                        action, self.recalibrator.min_recalibration_seconds
                    )
                    self.recalibrator.start_recalibration(
                        reason="extended_" + risk_state.get("reason", "unfavorable"),
                        duration_seconds=self.recalibrator.min_recalibration_seconds
                    )

            self._metrics.last_recalibration_check_ns = exchange_ts_ns

    # =========================================================================
    # HEALTH LOGGING
    # =========================================================================

    def _log_health(self) -> None:
        """
        Log health summary at regular candle-tick intervals.

        All status methods proven from live repo:
          - HybridRiskGuard.get_status() -> Dict
          - Recalibrator.get_status() -> Dict
          - ExecutionEngine.get_status() -> Dict
          - Commander.get_status() -> Dict
          - Recalibrator.get_recovery_strategy() -> Dict
          - Recalibrator.get_recalibration_remaining() -> float
        """
        risk_status = self.risk_guard.get_status()
        recal_status = self.recalibrator.get_status()
        exec_status = self.execution_engine.get_status()
        commander_status = self.commander.get_status()

        logger.info(
            "HEALTH | iter=%d | mode=%s | equity=%.2f | tradeable=%.2f | "
            "drawdown=%.2f%% | can_trade=%s | recalibrating=%s | "
            "pending_orders=%d | exec_queue=%d | "
            "emergency_liquidations=%d | recal_entries=%d",
            self._metrics.iteration_count,
            commander_status.get("mode", "UNKNOWN"),
            risk_status.get("current_equity", 0.0),
            risk_status.get("tradeable_equity", 0.0),
            risk_status.get("drawdown_from_peak", 0.0) * 100,
            risk_status.get("can_trade", False),
            recal_status.get("is_in_recalibration", False),
            exec_status.get("pending_orders_count", 0),
            exec_status.get("execution_queue_size", 0),
            self._metrics.emergency_liquidations,
            self._metrics.recalibration_entries,
        )

        # Fusion state summary — monitoring only, not for signal generation
        with self._lock:
            fusion = self._last_fusion
        if fusion is not None:
            logger.debug(
                "FUSION STATE | attack=%s | sleeve=%s | conf=%.3f | "
                "shans_superfluid=%.3f | shans_bias=%s",
                fusion.attack_mode,
                fusion.preferred_sleeve,
                fusion.confidence,
                fusion.shans_superfluid_score,
                fusion.shans_bias,
            )

        # Physical fuse alert
        if risk_status.get("physical_fuse_triggered"):
            logger.critical("HEALTH ALERT: Physical fuse triggered!")

        # VoL fuse alert
        if risk_status.get("vol_fuse_triggered"):
            logger.critical("HEALTH ALERT: VoL fuse triggered!")

        # Exchange outage alert
        if risk_status.get("outage_detected"):
            logger.critical("HEALTH ALERT: Exchange outage detected!")

        # Recalibration recovery strategy
        if recal_status.get("is_in_recalibration"):
            strategy = self.recalibrator.get_recovery_strategy()
            remaining = self.recalibrator.get_recalibration_remaining()
            logger.info(
                "RECALIBRATION ACTIVE | remaining=%.0fs | attempt=%d | "
                "betti_1=%d | persistence=%.3f | strategy=%s",
                remaining,
                recal_status.get("recovery_attempts", 0),
                recal_status.get("last_betti_1_count", 0),
                recal_status.get("last_persistence_score", 0.0),
                strategy.get("description", "unknown")
            )
            # =========================================================================
    # DIAGNOSTICS
    # =========================================================================

    def get_status(self) -> Dict[str, Any]:
        """
        Get current main loop status for monitoring and dashboard.

        All fields sourced from proven internal state only.

        Returns:
            Status dictionary
        """
        with self._lock:
            last_price = self._last_price
            last_equity = self._last_equity
            tpe_signal = self._last_tpe_signal
            fusion = self._last_fusion

        return {
            "symbol": self.symbol,
            "running": self._running,
            "iteration_count": self._metrics.iteration_count,
            "recalibration_active": self._recalibration_active,
            "recalibration_remaining_sec": (
                self.recalibrator.get_recalibration_remaining()
                if self._recalibration_active else 0.0
            ),
            "last_price": last_price,
            "last_equity": last_equity,
            "last_candle_ts_ns": self._metrics.last_candle_exchange_ts_ns,
            "last_order_book_ts_ns": self._metrics.last_order_book_exchange_ts_ns,
            "last_trade_ts_ns": self._metrics.last_trade_exchange_ts_ns,
            "last_equity_update_ns": self._metrics.last_equity_update_ns,
            "tpe_coherence": (
                tpe_signal.coherence_score if tpe_signal is not None else None
            ),
            "tpe_super_void": (
                tpe_signal.super_void_detected if tpe_signal is not None else None
            ),
            "tpe_betti_1": (
                tpe_signal.betti_1 if tpe_signal is not None else None
            ),
            "tpe_persistence": (
                tpe_signal.persistence_score if tpe_signal is not None else None
            ),
            # Fusion state exposed for downstream signal submission layer
            "fusion_attack_mode": (
                fusion.attack_mode if fusion is not None else None
            ),
            "fusion_preferred_sleeve": (
                fusion.preferred_sleeve if fusion is not None else None
            ),
            "fusion_confidence": (
                fusion.confidence if fusion is not None else None
            ),
            "fusion_regime": (
                fusion.regime if fusion is not None else None
            ),
            "fusion_shans_superfluid": (
                fusion.shans_superfluid_score if fusion is not None else None
            ),
            "fusion_shans_bias": (
                fusion.shans_bias if fusion is not None else None
            ),
            "emergency_liquidations": self._metrics.emergency_liquidations,
            "recalibration_entries": self._metrics.recalibration_entries,
            "recalibration_exits": self._metrics.recalibration_exits,
            "consecutive_errors": self._metrics.consecutive_errors,
            # Signal submission boundary: NOT performed by MainLoop
            "signal_submission": "downstream_layer_not_yet_authorized",
        }

    def get_last_fusion(self) -> Optional[FusionDecision]:
        """
        Return the last FusionDecision for downstream layer consumption.

        The downstream signal submission layer (StrategyVote -> DecisionCompiler
        -> OrderIntent -> ExecutionEngine) reads fusion state from here.
        MainLoop does not act on fusion for signal submission purposes.

        Returns:
            Last FusionDecision or None if no candle tick received yet
        """
        with self._lock:
            return self._last_fusion

    def get_last_tpe_signal(self) -> Optional[TopologicalSignal]:
        """
        Return the last TopologicalSignal for downstream layer consumption.

        Returns:
            Last TopologicalSignal or None if no order book tick received yet
        """
        with self._lock:
            return self._last_tpe_signal

    def get_metrics(self) -> LoopMetrics:
        """Return raw loop metrics (read-only reference)."""
        return self._metrics

    def is_recalibrating(self) -> bool:
        """Return True if recalibration is currently active."""
        return self._recalibration_active

    def reset_metrics(self) -> None:
        """Reset loop metrics. Use only after recalibration or for testing."""
        self._metrics = LoopMetrics()
        logger.info("MainLoop metrics reset for %s", self.symbol)


# =========================================================================
# MODULE-LEVEL FACTORY
# =========================================================================

def create_main_loop(
    config: Config,
    commander: Commander,
    risk_guard: HybridRiskGuard,
    signal_fusion: SignalFusion,
    data_validator: DataContinuityValidator,
    recalibrator: Recalibrator,
    tpe_engine: TopologicalEngine,
    execution_engine: ExecutionEngine,
    symbol: str,
) -> MainLoop:
    """
    Factory function for MainLoop construction.

    All parameters match proven live constructors.

    Args:
        config: Configuration object (Config.from_env())
        commander: Commander instance
        risk_guard: HybridRiskGuard instance
        signal_fusion: SignalFusion instance
        data_validator: DataContinuityValidator instance
        recalibrator: Recalibrator instance
        tpe_engine: TopologicalEngine instance
        execution_engine: ExecutionEngine instance
        symbol: Primary trading symbol (e.g. "XBT/USD")

    Returns:
        Configured MainLoop instance (not yet started)
    """
    return MainLoop(
        config=config,
        commander=commander,
        risk_guard=risk_guard,
        signal_fusion=signal_fusion,
        data_validator=data_validator,
        recalibrator=recalibrator,
        tpe_engine=tpe_engine,
        execution_engine=execution_engine,
        symbol=symbol,
    )