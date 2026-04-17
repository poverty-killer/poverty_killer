"""
Main Loop - Sovereign Market-Data / Brain / State / Risk-Ingress Pipeline

WIRED — integrated into main.py:SovereignHeartbeat as of Board bundle pass 2026-04-15.
Receives events via callbacks from PollingClient (candles, order books) and
KrakenWebSocketClient (candles, trades). Drives fusion, recalibration, and TPE
with authoritative exchange timestamps.

Signal_fusion call sites: ALL REPAIRED.
Shans payload: CLEARED — on_order_book processes through ShansCurve and passes
    ShansCurveSignal to signal_fusion.
Regime: WIRED — RegimeDetector.update() called from on_order_book() with real
    bid/ask spread and depth. Volume from last candle (L1 proxy; honest degradation).
Physical: WIRED — PhysicalValidator records real order book receive latency;
    to_fusion_dict() feeds health_score to signal_fusion.
Toxicity: WIRED — ToxicityEngine.update_candle() + update_toxicity() from on_candle().
Entropy: WIRED — EntropyDecoder.update() with range-based proxy from candle OHLC.
    Same instance shared with ShansCurve (ShansCurve reads entropy_history[-1]).
Insider: PARTIALLY WIRED — InsiderSignalEngine.get_or_default_snapshot() feeds
    active=False snapshot; urgency=0.0 until external observation feed added.

Signal submission boundary (preserved):
    MainLoop does NOT submit execution signals.
    StrategySignal, StrategyVote, DecisionCompiler, OrderIntent, ExecutionEngine.submit_signal()
    belong to a separate downstream layer not yet authorized.

Timing authority:
    - All exchange timestamps come from market data (authoritative int ns)
    - Wall-clock time.time_ns() used ONLY for receive-side latency tracking
    - DataContinuityValidator.record_data() requires datetime; conversion performed locally
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
from app.brain.shans_curve import ShansCurve
from app.brain.topological_engine import TopologicalEngine, TopologicalSignal
from app.brain.regime_detector import RegimeDetector
from app.brain.physical_validator import PhysicalValidator
from app.brain.toxicity_engine import ToxicityEngine, ToxicityAlert
from app.brain.entropy_decoder import EntropyDecoder
from app.brain.insider_signal_engine import InsiderSignalEngine, InsiderSignalSnapshot
from app.execution.engine import ExecutionEngine
from app.models import (
    OrderBookSnapshot,
    Candle,
    FusionDecision,
)
from app.models.enums import RegimeType

logger = logging.getLogger(__name__)

# Book event throttle: process pipeline at most every 200ms of wall-clock time.
# Prevents WS queue backlog when Kraken sends high-frequency (100+/sec) book updates.
# Measured in receive_ns (wall clock) not exchange_ts to avoid cross-symbol timestamp drift.
# At ~70ms pipeline time per event: 200ms interval → 5 runs/sec → 35% asyncio load.
_MIN_BOOK_PROCESS_INTERVAL_NS: int = 200_000_000  # 200ms → max 5 book pipeline runs/sec


def _ns_to_datetime(ns: int) -> datetime:
    """
    Convert nanosecond timestamp to UTC datetime.
    Used only at DataContinuityValidator boundary which requires datetime.
    """
    return datetime.utcfromtimestamp(ns / 1_000_000_000.0)


@dataclass
class LoopMetrics:
    """Per-iteration metrics. All counters monotonically increasing."""
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

    OrderBookSnapshot: symbol, exchange_ts_ns, mid_price (@property),
        depth_at_levels(n) -> Tuple[float, float], spread, spread_bps, imbalance

    FusionDecision: exchange_ts_ns, attack_mode, confidence,
        shadow_front_eligible, liquidity_void_eligible, entropy_decoder_eligible,
        gamma_front_eligible, sector_rotation_eligible, preferred_sleeve,
        deprioritized_sleeves, reason, regime, physical_verification_score,
        shans_superfluid_score, shans_bias, shans_confidence

    DataContinuityValidator: record_data(symbol, timestamp: datetime),
        mark_good(symbol), is_data_healthy(symbol)

    ShansCurve: update_order_book(symbol, mid_price, cum_bid_vol, cum_ask_vol,
        depth_velocity, timestamp) -> Optional[ShansCurveSignal]

    RegimeDetector: update(price, volume, bid_price, ask_price, bid_depth,
        ask_depth, exchange_ts_ns) -> Tuple[RegimeType, float]

    PhysicalValidator: record_latency(symbol, exchange, latency_ms, order_size,
        price_impact_bps, timestamp_ns) -> PhysicalVerification;
        to_fusion_dict(exchange) -> {"health_score": float}

    ToxicityEngine: update_candle(volume, high, low, close, timestamp_ns),
        update_toxicity(current_ts_ns) -> ToxicityAlert

    EntropyDecoder: update(symbol, exchange_ts_ns, raw_entropy) -> EntropyScore

    InsiderSignalEngine: get_or_default_snapshot(symbol, timestamp_ns)
        -> InsiderSignalSnapshot (active=False if no observations)

    SignalFusion — LIVE CONTRACT (all call sites repaired):
        update_*(payload, timestamp_ns), fuse(current_ts_ns), get_last_fusion()

    HybridRiskGuard: assess_state(equity, tpe_coherence) -> Dict,
        update_equity_history(equity), can_trade() -> bool

    Recalibrator: evaluate_regime(price_drop_pct, tpe_signal, drop_duration_sec) -> str,
        start_recalibration(reason, duration_seconds), end_recalibration(),
        should_recover() -> bool, min_recalibration_seconds: float

    ExecutionEngine: process_events(), update_equity(equity),
        _emergency_liquidate_all()

    Commander: update_equity(equity, timestamp_ns), is_attack_mode(),
        get_kelly_multiplier(), get_status()
    """

    def __init__(
        self,
        config: Config,
        commander: Commander,
        risk_guard: HybridRiskGuard,
        signal_fusion: SignalFusion,
        data_validator: DataContinuityValidator,
        recalibrator: Recalibrator,
        shans_curve: ShansCurve,
        tpe_engine: TopologicalEngine,
        regime_detector: RegimeDetector,
        physical_validator: PhysicalValidator,
        toxicity_engine: ToxicityEngine,
        entropy_decoder: EntropyDecoder,
        insider_engine: InsiderSignalEngine,
        execution_engine: ExecutionEngine,
        symbol: str,
        exchange: str = "kraken",
        health_log_interval_iterations: int = 600,
    ):
        self.config = config
        self.commander = commander
        self.risk_guard = risk_guard
        self.signal_fusion = signal_fusion
        self.data_validator = data_validator
        self.recalibrator = recalibrator
        self.shans_curve = shans_curve
        self.tpe_engine = tpe_engine
        self.regime_detector = regime_detector
        self.physical_validator = physical_validator
        self.toxicity_engine = toxicity_engine
        self.entropy_decoder = entropy_decoder
        self.insider_engine = insider_engine
        self.execution_engine = execution_engine
        self.symbol = symbol
        self.exchange = exchange
        self.health_log_interval_iterations = health_log_interval_iterations

        self._last_order_book: Optional[OrderBookSnapshot] = None
        self._last_candle: Optional[Candle] = None
        self._last_tpe_signal: Optional[TopologicalSignal] = None
        self._last_equity: float = config.initial_capital
        self._last_price: float = 0.0
        self._last_fusion: Optional[FusionDecision] = None
        self._last_risk_state: Optional[Dict[str, Any]] = None

        self._recalibration_active: bool = False
        self._recalibration_start_ns: int = 0
        self._last_book_receive_ns: int = 0

        self._metrics = LoopMetrics()
        self._lock = threading.Lock()
        self._running = False

        logger.info("MainLoop initialized: symbol=%s", symbol)

    # =========================================================================
    # LIFECYCLE
    # =========================================================================

    def start(self) -> None:
        self._running = True
        logger.info("MainLoop started: symbol=%s", self.symbol)

    def stop(self) -> None:
        self._running = False
        logger.info(
            "MainLoop stopped: symbol=%s iterations=%d emergency_liquidations=%d",
            self.symbol, self._metrics.iteration_count, self._metrics.emergency_liquidations,
        )

    # =========================================================================
    # MARKET DATA INGRESS — called by SovereignHeartbeat feed callbacks
    # =========================================================================

    def on_order_book(self, order_book: OrderBookSnapshot) -> None:
        """
        Ingest authoritative order book snapshot.

        Drives:
          - Data continuity (record_data + mark_good)
          - TPE analysis (real coherence score)
          - ShansCurve processing → signal_fusion shans slot (ShansCurveSignal payload)
          - Regime detection → signal_fusion regime slot (real L2-derived signal)
          - Physical latency → signal_fusion physical slot (health_score dict)
          - Price update from mid_price
        """
        if not self._running:
            return
        if order_book.symbol != self.symbol:
            return  # Reject foreign-symbol books: MainLoop is single-symbol; all pipeline state is self.symbol

        receive_ns = time.time_ns()
        exchange_ts_ns = order_book.exchange_ts_ns

        # Throttle: skip if pipeline ran within the last 200ms of wall-clock time.
        # Drains the WS queue instantly for burst periods; prevents asyncio loop overload.
        if receive_ns - self._last_book_receive_ns < _MIN_BOOK_PROCESS_INTERVAL_NS:
            return
        self._last_book_receive_ns = receive_ns

        with self._lock:
            self._last_order_book = order_book
            mid = order_book.mid_price
            if mid > 0.0:
                self._last_price = mid
            last_candle_ref = self._last_candle  # snapshot for regime volume proxy

        self.data_validator.record_data(self.symbol, _ns_to_datetime(exchange_ts_ns))
        self.data_validator.mark_good(self.symbol)

        tpe_signal = self.tpe_engine.analyze(order_book)
        with self._lock:
            self._last_tpe_signal = tpe_signal

        if mid > 0.0:
            cum_bid_vol, cum_ask_vol = order_book.depth_at_levels(10)

            # Shan's Curve — ShansCurveSignal → signal_fusion shans slot
            shans_result = self.shans_curve.update_order_book(
                symbol=self.symbol,
                mid_price=mid,
                cum_bid_vol=cum_bid_vol,
                cum_ask_vol=cum_ask_vol,
                depth_velocity=0.0,
                timestamp=exchange_ts_ns,
            )
            if shans_result is not None:
                self.signal_fusion.update_shans(shans_result, exchange_ts_ns)

            # Regime — real L2-derived signal
            # bid/ask from spread; depth from depth_at_levels; volume from last candle (L1 proxy)
            spread = order_book.spread
            bid_price = mid - spread / 2.0
            ask_price = mid + spread / 2.0
            last_volume = last_candle_ref.volume if last_candle_ref is not None else 0.0
            regime_tuple = self.regime_detector.update(
                price=mid,
                volume=last_volume,
                bid_price=bid_price,
                ask_price=ask_price,
                bid_depth=cum_bid_vol,
                ask_depth=cum_ask_vol,
                exchange_ts_ns=exchange_ts_ns,
            )
            self.signal_fusion.update_regime(regime_tuple, exchange_ts_ns)

        # Physical — real network latency from order book receive-side measurement
        latency_ms = (receive_ns - exchange_ts_ns) / 1_000_000
        latency_ms_clamped = max(0.0, latency_ms)
        self.physical_validator.record_latency(
            symbol=self.symbol,
            exchange=self.exchange,
            latency_ms=latency_ms_clamped,
            order_size=0.0,
            price_impact_bps=0.0,
            timestamp_ns=exchange_ts_ns,
        )
        phys_dict = self.physical_validator.to_fusion_dict(self.exchange)
        self.signal_fusion.update_physical(phys_dict, exchange_ts_ns)

        self._metrics.last_order_book_exchange_ts_ns = exchange_ts_ns

        if latency_ms > 200.0:
            logger.warning(
                "Order book receive latency spike: %.1fms symbol=%s",
                latency_ms, self.symbol,
            )

    def on_candle(self, candle: Candle) -> None:
        """
        Ingest authoritative candle.

        Drives:
          - Whale flow update (signal_fusion whale slot)
          - Toxicity update (candle proxy mode → ToxicityAlert → signal_fusion toxicity slot)
          - Entropy update (range-based proxy → EntropyScore → signal_fusion entropy slot)
          - Insider update (real engine; active=False until observations added)
          - Commander equity sync
          - fuse(exchange_ts_ns) — authoritative timestamp, not wall-clock
          - Risk state assessment with real TPE coherence
          - Recalibration state machine
          - Execution engine event drain
          - Health logging

        Regime slot updated from on_order_book() — not here.
        Signal submission NOT performed here.
        """
        if not self._running:
            return

        exchange_ts_ns = candle.exchange_ts_ns

        with self._lock:
            self._last_candle = candle
            if candle.close > 0.0:
                self._last_price = candle.close

        self.signal_fusion.update_whale(candle, exchange_ts_ns)

        # Toxicity — candle proxy mode (real engine, honest degraded input)
        self.toxicity_engine.update_candle(
            volume=candle.volume,
            high=candle.high,
            low=candle.low,
            close=candle.close,
            timestamp_ns=exchange_ts_ns,
        )
        tox_alert: ToxicityAlert = self.toxicity_engine.update_toxicity(exchange_ts_ns)
        self.signal_fusion.update_toxicity(tox_alert, exchange_ts_ns)

        # Entropy — realized intrabar range proxy (candle high - low normalized by close)
        # Scale of 20: maps typical crypto range/close (0.002–0.05) to [0.04–1.0]
        raw_entropy = min(1.0, (candle.high - candle.low) / max(candle.close, 1e-9) * 20.0)
        entropy_score = self.entropy_decoder.update(self.symbol, exchange_ts_ns, raw_entropy)
        self.signal_fusion.update_entropy(entropy_score, exchange_ts_ns)

        # Insider — real engine state; active=False until external observations added
        insider_snapshot = self.insider_engine.get_or_default_snapshot(self.symbol, exchange_ts_ns)
        self.signal_fusion.update_insider(insider_snapshot, exchange_ts_ns)

        self.commander.update_equity(self._last_equity, exchange_ts_ns)

        fusion: FusionDecision = self.signal_fusion.fuse(exchange_ts_ns)
        with self._lock:
            self._last_fusion = fusion

        self._metrics.iteration_count += 1
        self._metrics.last_candle_exchange_ts_ns = exchange_ts_ns

        with self._lock:
            tpe_signal = self._last_tpe_signal

        tpe_coherence: float = (
            tpe_signal.coherence_score if tpe_signal is not None else 0.5
        )

        risk_state = self.risk_guard.assess_state(self._last_equity, tpe_coherence)
        with self._lock:
            self._last_risk_state = risk_state
        self._metrics.last_risk_assessment_ns = exchange_ts_ns

        self._advance_recalibration(risk_state, tpe_signal, exchange_ts_ns)

        self.execution_engine.process_events()

        if (self._metrics.iteration_count - self._metrics.last_health_log_iteration
                >= self.health_log_interval_iterations):
            self._log_health()
            self._metrics.last_health_log_iteration = self._metrics.iteration_count

        self._metrics.consecutive_errors = 0

    def on_trade(self, size: float, price: float, side: int, exchange_ts_ns: int) -> None:
        """
        Ingest authoritative trade tick.
        Drives data continuity and price update only.
        Toxicity engine update is handled by SovereignHeartbeat (direct ToxicityEngine access).
        """
        if not self._running:
            return

        self.data_validator.record_data(self.symbol, _ns_to_datetime(exchange_ts_ns))
        self.data_validator.mark_good(self.symbol)

        if price > 0.0:
            with self._lock:
                self._last_price = price

        self._metrics.last_trade_exchange_ts_ns = exchange_ts_ns

    def on_equity_update(self, current_equity: float, exchange_ts_ns: int) -> None:
        """
        Receive authoritative portfolio equity.

        Drives:
          - Internal equity state
          - HybridRiskGuard.update_equity_history()
          - ExecutionEngine.update_equity()
          - Commander.update_equity()
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
        action: str = risk_state.get("action", "AGGRESSIVE")
        drawdown_from_peak: float = risk_state.get("drawdown_from_peak", 0.0)

        if action == "EMERGENCY_HALT":
            if not self._recalibration_active:
                logger.critical(
                    "EMERGENCY_HALT: drawdown=%.2f%% reason=%s — fire-and-forget liquidation",
                    drawdown_from_peak * 100,
                    risk_state.get("reason", "unknown"),
                )
                self._metrics.emergency_liquidations += 1
                self.execution_engine._emergency_liquidate_all()
            return

        drop_duration_sec: float = (
            (exchange_ts_ns - self._recalibration_start_ns) / 1_000_000_000.0
            if self._recalibration_active and self._recalibration_start_ns > 0
            else 0.0
        )

        regime_decision: str = self.recalibrator.evaluate_regime(
            price_drop_pct=drawdown_from_peak,
            tpe_signal=tpe_signal,
            drop_duration_sec=drop_duration_sec,
        )

        if regime_decision == "CRISIS_ABORT" and not self._recalibration_active:
            logger.critical(
                "CRISIS_ABORT from recalibrator: drawdown=%.2f%% betti_1=%d — liquidation",
                drawdown_from_peak * 100,
                tpe_signal.betti_1 if tpe_signal is not None else 0,
            )
            self._metrics.emergency_liquidations += 1
            self.execution_engine._emergency_liquidate_all()
            return

        if action == "RECALIBRATE" and not self._recalibration_active:
            self._recalibration_active = True
            self._recalibration_start_ns = exchange_ts_ns
            self._metrics.recalibration_entries += 1
            self.recalibrator.start_recalibration(
                reason=risk_state.get("reason", "risk_guard_floor_breach"),
                duration_seconds=self.recalibrator.min_recalibration_seconds,
            )
            logger.warning(
                "Recalibration STARTED: reason=%s drawdown=%.2f%%",
                risk_state.get("reason", "unknown"),
                drawdown_from_peak * 100,
            )

        if self._recalibration_active:
            if self.recalibrator.should_recover():
                if action not in ("RECALIBRATE", "EMERGENCY_HALT"):
                    self.recalibrator.end_recalibration()
                    self._recalibration_active = False
                    self._recalibration_start_ns = 0
                    self._metrics.recalibration_exits += 1
                    logger.info("Recalibration ENDED: action=%s", action)
                else:
                    logger.info(
                        "Recalibration cooldown elapsed but conditions unfavorable (action=%s) — extending",
                        action,
                    )
                    self.recalibrator.start_recalibration(
                        reason="extended_" + risk_state.get("reason", "unfavorable"),
                        duration_seconds=self.recalibrator.min_recalibration_seconds,
                    )
            self._metrics.last_recalibration_check_ns = exchange_ts_ns

    # =========================================================================
    # HEALTH LOGGING
    # =========================================================================

    def _log_health(self) -> None:
        risk_status = self.risk_guard.get_status()
        recal_status = self.recalibrator.get_status()
        exec_status = self.execution_engine.get_status()
        commander_status = self.commander.get_status()

        logger.info(
            "HEALTH | iter=%d | mode=%s | equity=%.2f | drawdown=%.2f%% | "
            "can_trade=%s | recalibrating=%s | pending_orders=%d | "
            "emergency_liquidations=%d | recal_entries=%d",
            self._metrics.iteration_count,
            commander_status.get("mode", "UNKNOWN"),
            risk_status.get("current_equity", 0.0),
            risk_status.get("drawdown_from_peak", 0.0) * 100,
            risk_status.get("can_trade", False),
            recal_status.get("is_in_recalibration", False),
            exec_status.get("pending_orders_count", 0),
            self._metrics.emergency_liquidations,
            self._metrics.recalibration_entries,
        )

        with self._lock:
            fusion = self._last_fusion
        if fusion is not None:
            logger.debug(
                "FUSION | attack=%s | sleeve=%s | conf=%.3f | shans=%.3f | bias=%s",
                fusion.attack_mode, fusion.preferred_sleeve, fusion.confidence,
                fusion.shans_superfluid_score, fusion.shans_bias,
            )

        if risk_status.get("physical_fuse_triggered"):
            logger.critical("HEALTH ALERT: Physical fuse triggered!")
        if risk_status.get("vol_fuse_triggered"):
            logger.critical("HEALTH ALERT: VoL fuse triggered!")
        if risk_status.get("outage_detected"):
            logger.critical("HEALTH ALERT: Exchange outage detected!")

        if recal_status.get("is_in_recalibration"):
            strategy = self.recalibrator.get_recovery_strategy()
            remaining = self.recalibrator.get_recalibration_remaining()
            logger.info(
                "RECALIBRATION ACTIVE | remaining=%.0fs | attempt=%d | strategy=%s",
                remaining,
                recal_status.get("recovery_attempts", 0),
                strategy.get("description", "unknown"),
            )

    # =========================================================================
    # DIAGNOSTICS
    # =========================================================================

    def get_status(self) -> Dict[str, Any]:
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
            "tpe_coherence": tpe_signal.coherence_score if tpe_signal is not None else None,
            "tpe_betti_1": tpe_signal.betti_1 if tpe_signal is not None else None,
            "fusion_attack_mode": fusion.attack_mode if fusion is not None else None,
            "fusion_preferred_sleeve": fusion.preferred_sleeve if fusion is not None else None,
            "fusion_confidence": fusion.confidence if fusion is not None else None,
            "fusion_regime": fusion.regime if fusion is not None else None,
            "emergency_liquidations": self._metrics.emergency_liquidations,
            "recalibration_entries": self._metrics.recalibration_entries,
            "recalibration_exits": self._metrics.recalibration_exits,
            "signal_submission": "downstream_layer_not_yet_authorized",
        }

    def get_last_fusion(self) -> Optional[FusionDecision]:
        with self._lock:
            return self._last_fusion

    def get_last_tpe_signal(self) -> Optional[TopologicalSignal]:
        with self._lock:
            return self._last_tpe_signal

    def get_metrics(self) -> LoopMetrics:
        return self._metrics

    def is_recalibrating(self) -> bool:
        return self._recalibration_active

    def reset_metrics(self) -> None:
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
    shans_curve: ShansCurve,
    tpe_engine: TopologicalEngine,
    regime_detector: RegimeDetector,
    physical_validator: PhysicalValidator,
    toxicity_engine: ToxicityEngine,
    entropy_decoder: EntropyDecoder,
    insider_engine: InsiderSignalEngine,
    execution_engine: ExecutionEngine,
    symbol: str,
    exchange: str = "kraken",
) -> MainLoop:
    return MainLoop(
        config=config,
        commander=commander,
        risk_guard=risk_guard,
        signal_fusion=signal_fusion,
        data_validator=data_validator,
        recalibrator=recalibrator,
        shans_curve=shans_curve,
        tpe_engine=tpe_engine,
        regime_detector=regime_detector,
        physical_validator=physical_validator,
        toxicity_engine=toxicity_engine,
        entropy_decoder=entropy_decoder,
        insider_engine=insider_engine,
        execution_engine=execution_engine,
        symbol=symbol,
        exchange=exchange,
    )
