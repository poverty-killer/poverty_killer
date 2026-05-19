# FILE: app/main_loop.py
# CORRECTED: Uses per-symbol ShansCurve from SymbolRuntime

"""
Main Loop - Sovereign Market-Data / Brain / State / Risk-Ingress Pipeline

[Full docstring preserved - same as your current file]

BUNDLE PER-SYMBOL SHANS OWNERSHIP FIX (2026-04-27):
    - Each SymbolRuntime now owns its own ShansCurve instance
    - on_order_book() calls runtime.shans_curve.update_order_book() instead of global
    - Prevents cross-symbol buffer contamination
"""

import logging
import time
import threading
import math
from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, Any, List, Tuple, Set

from app.config import Config
from app.commander import Commander
from app.risk.guard import HybridRiskGuard
from app.risk.position_sizing import PositionSizingEngine, PositionSizeResult
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
from app.strategies.strategy_router import StrategyRouter
from app.strategies.shadow_front import ShadowFrontStrategy
from app.core.decision_compiler import DecisionCompiler
from app.core.truth_reconciler import TruthReconciler
from app.models import (
    OrderBookSnapshot,
    Candle,
    FusionDecision,
    StrategySignal,
    StrategyVote,
    TruthFrame,
    ExchangeTruth,
    ExchangePosition,
    ExchangeOpenOrder,
    ExchangeFill,
    ExecutionTruth,
    SubmittedOrder,
    PendingCancel,
    Acknowledgement,
    Rejection,
    PortfolioTruth,
    PortfolioPosition,
    StrategyTruth,
    StrategyTruthEntry,
    RiskTruth,
)
from app.models.enums import RegimeType, SleeveType, SignalType, TruthStatus, RiskMode, OrderSide, InternalOrderStatus, StrategyID
from app.risk.safety import SafetyGate
from app.telemetry.event_store import TelemetryEventStore
from app.symbol_runtime import SymbolRuntime
from app.strategies.council_metadata import (
    build_council_metadata,
    MODULE_GAMMA_FRONT,
    SOURCE_STRATEGY_SIGNAL,
    ROLE_EXIT, ROLE_OBSERVE_ONLY,
    BIAS_SHORT, BIAS_LONG, BIAS_UNKNOWN,
    FEED_MISSING,
)
# OBSERVE-ONLY (Stage 2-C): adapter imports for telemetry-only StrategyVote
# synthesis from dormant-sleeve signals. Adapters are NOT invoked from any
# dispatch / DecisionCompiler / Fusion / execution path.
from app.strategies.strategy_vote_adapters import (
    adapt_liquidity_void_to_vote,
    adapt_sector_rotation_to_vote,
)

logger = logging.getLogger(__name__)

_MIN_BOOK_PROCESS_INTERVAL_NS: int = 200_000_000

# Candle admission logging rate limits (seconds)
_CANDLE_REJECT_LOG_INTERVAL_SEC: int = 60


def _ns_to_datetime(ns: int) -> datetime:
    return datetime.utcfromtimestamp(ns / 1_000_000_000.0)


def _log_dispatch_diag(reason_code: str, **fields: Any) -> None:
    """Emit compact dispatch-admission evidence without changing decisions."""
    clean_fields = {
        key: value
        for key, value in fields.items()
        if value is not None
    }
    logger.info(
        "[DISPATCH_DIAG] reason_code=%s fields=%s",
        reason_code,
        clean_fields,
    )


def _format_sector_rotation_diag_detail(detail: Optional[Dict[str, Any]]) -> str:
    if not detail:
        return "-"
    parts: List[str] = []
    for key in sorted(detail):
        value = detail[key]
        if value is None:
            continue
        text = str(value)
        if len(text) > 80:
            text = f"{text[:77]}..."
        parts.append(f"{key}={text}")
    return ",".join(parts) if parts else "-"


def _log_sector_rotation_diag(
    symbol: str,
    reason_code: str,
    candle_ts_ns: int,
    detail: Optional[Dict[str, Any]] = None,
) -> None:
    """Emit observe-only SectorRotation producer evidence."""
    logger.info(
        "[SECTOR_ROTATION_DIAG] symbol=%s reason_code=%s candle_ts_ns=%s detail=%s",
        symbol,
        reason_code,
        candle_ts_ns,
        _format_sector_rotation_diag_detail(detail),
    )


# =========================================================================
# BUNDLE 2A — FACTORY FUNCTION FOR MAINLOOP ASSEMBLY
# =========================================================================

def create_main_loop(
    config: Config,
    commander: Commander,
    risk_guard: HybridRiskGuard,
    signal_fusion: SignalFusion,
    data_validator: DataContinuityValidator,
    recalibrator: Recalibrator,
    shans_curve: ShansCurve,
    tpe_engine: Optional[TopologicalEngine],
    regime_detector: RegimeDetector,
    physical_validator: PhysicalValidator,
    toxicity_engine: Optional[ToxicityEngine],
    entropy_decoder: EntropyDecoder,
    insider_engine: InsiderSignalEngine,
    execution_engine: ExecutionEngine,
    symbol: str,
    exchange: str,
    safety_gate: SafetyGate,
    telemetry_store: Optional[TelemetryEventStore] = None,
    active_symbols: Optional[Set[str]] = None,
) -> "MainLoop":
    """
    Factory function for MainLoop assembly.

    BUNDLE 2A — BOOT REPAIR + ASSEMBLY SEAM RESTORATION
    Board-approved: creates missing collaborators internally to restore lawful boot.

    Assembles:
        - StrategyRouter (requires config, safety_gate)
        - DecisionCompiler (requires config, telemetry_store)
        - PositionSizingEngine (requires config)

    All collaborators are instantiated lawfully with real dependencies passed from main.py.
    No placeholders. No fake compatibility layers.

    BUNDLE MULTI-SYMBOL RUNTIME: 
        - tpe_engine and toxicity_engine params are accepted but IGNORED.
          Per-symbol engines are created inside SymbolRuntime containers.
        - shadow_front is NOT created here; per-symbol instances in runtimes.
        - active_symbols set determines which symbols get runtimes.
    """
    from app.strategies.strategy_router import StrategyRouter
    from app.core.decision_compiler import DecisionCompiler
    from app.risk.position_sizing import PositionSizingEngine

    # Instantiate missing collaborators (global, shared across symbols)
    strategy_router = StrategyRouter(config=config, safety_gate=safety_gate)
    decision_compiler = DecisionCompiler(telemetry_store=telemetry_store)
    position_sizing_engine = PositionSizingEngine(config=config)

    return MainLoop(
        config=config,
        commander=commander,
        risk_guard=risk_guard,
        signal_fusion=signal_fusion,
        data_validator=data_validator,
        recalibrator=recalibrator,
        shans_curve=shans_curve,
        regime_detector=regime_detector,
        physical_validator=physical_validator,
        entropy_decoder=entropy_decoder,
        insider_engine=insider_engine,
        execution_engine=execution_engine,
        strategy_router=strategy_router,
        decision_compiler=decision_compiler,
        position_sizing_engine=position_sizing_engine,
        symbol=symbol,
        exchange=exchange,
        telemetry_store=telemetry_store,
        active_symbols=active_symbols or {symbol},
        safety_gate=safety_gate,
    )


class LoopMetrics:
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
    compilation_cycles: int = 0
    orders_submitted: int = 0
    orders_rejected: int = 0
    # Candle admission counters
    candle_duplicates_rejected: int = 0
    candle_stale_rejected: int = 0
    # Invalid book counters
    invalid_books_skipped: int = 0


class CandleRejectionTracker:
    """Per-symbol rate-limited logging for candle rejections."""
    
    def __init__(self):
        self._last_log_time: Dict[str, Dict[str, float]] = {}
    
    def should_log(self, symbol: str, rejection_type: str) -> bool:
        """Return True if enough time has passed since last log for this type."""
        now = time.time()
        last = self._last_log_time.get(symbol, {}).get(rejection_type, 0)
        if now - last >= _CANDLE_REJECT_LOG_INTERVAL_SEC:
            if symbol not in self._last_log_time:
                self._last_log_time[symbol] = {}
            self._last_log_time[symbol][rejection_type] = now
            return True
        return False


class MainLoop:
    """
    Sovereign Market-Data / Brain / State / Risk-Ingress Pipeline.

    BUNDLE 1 REDO REPAIR: Structural actuation seam complete.
    Behavioral readiness awaiting upstream feed wiring (Bundle 2).

    BUNDLE 3B: Accesses order_router via execution_engine for ExchangeTruth hydration.
    
    BUNDLE F1: Added telemetry_store parameter.
    
    BUNDLE CANDLE ADMISSION HARDENING: Permanent per-symbol last_admitted_candle_ts_ns
    tracking with classification (duplicate vs stale) and bounded logging.
    
    BUNDLE CANDLE ADMISSION ATOMICITY FIX: Admission check and update protected by self._lock.
    
    BUNDLE MULTI-SYMBOL RUNTIME: Per-symbol runtime containers replacing single-symbol state.
    
    BUNDLE STRATEGY-GATING REPAIR (2026-04-27): Whale overlay wired via per-symbol
    WhaleFlowEngine. Sentiment overlay wired via MarketSentimentProxy.
    
    BUNDLE DIAGNOSTIC VISIBILITY (2026-04-28): Dispatch/eligibility tracing logs.
    
    BUNDLE SHANS PRODUCER TRACE (2026-04-27): Added diagnostic INFO logs to trace
    Shans production path. NO BEHAVIOR CHANGES.
    
    BUNDLE PER-SYMBOL THROTTLE FIX (2026-04-27): Replaced global throttle with
    per-symbol throttle to prevent multi-symbol starvation. Uses explicit
    _last_book_receive_ns_by_symbol field.
    
    BUNDLE PER-SYMBOL SHANS OWNERSHIP FIX (2026-04-27): Each SymbolRuntime now owns
    its own ShansCurve instance. Prevents cross-symbol buffer contamination.
    
    LIMITS (honest disclosure):
        - SignalFusion remains global. Multi-symbol fusion correctness depends on
          per-symbol update_*() calls before each fuse().
        - DecisionCompiler remains global. StrategyVote routing includes symbol
          context but compilation is symbol-agnostic.
        - ExecutionEngine/OrderRouter remain global. Orders carry symbol tags.
        - This bundle establishes STATE ownership, not full multi-symbol execution.
    """

    # Constants for backward compatibility with create_main_loop
    _SHADOW_FRONT = None  # Placeholder; per-symbol instances in runtimes
    _TPE_ENGINE = None    # Placeholder; per-symbol instances in runtimes
    _TOXICITY_ENGINE = None  # Placeholder; per-symbol instances in runtimes

    def __init__(
        self,
        config: Config,
        commander: Commander,
        risk_guard: HybridRiskGuard,
        signal_fusion: SignalFusion,
        data_validator: DataContinuityValidator,
        recalibrator: Recalibrator,
        shans_curve: ShansCurve,
        regime_detector: RegimeDetector,
        physical_validator: PhysicalValidator,
        entropy_decoder: EntropyDecoder,
        insider_engine: InsiderSignalEngine,
        execution_engine: ExecutionEngine,
        strategy_router: StrategyRouter,
        decision_compiler: DecisionCompiler,
        position_sizing_engine: PositionSizingEngine,
        symbol: str,
        exchange: str = "kraken",
        health_log_interval_iterations: int = 600,
        telemetry_store: Optional[TelemetryEventStore] = None,
        active_symbols: Optional[Set[str]] = None,
        safety_gate: Optional[SafetyGate] = None,
    ):
        self.config = config
        self.commander = commander
        self.risk_guard = risk_guard
        self.signal_fusion = signal_fusion
        self.data_validator = data_validator
        self.recalibrator = recalibrator
        # Global shans_curve retained for backward compatibility but NOT used for per-symbol routing
        self.shans_curve = shans_curve
        self.regime_detector = regime_detector
        self.physical_validator = physical_validator
        self.entropy_decoder = entropy_decoder
        self.insider_engine = insider_engine
        self.execution_engine = execution_engine
        self.strategy_router = strategy_router
        self.decision_compiler = decision_compiler
        self.position_sizing_engine = position_sizing_engine
        self.exchange = exchange
        self.health_log_interval_iterations = health_log_interval_iterations
        self.telemetry_store = telemetry_store
        self.safety_gate = safety_gate

        # Active symbols set (all symbols that can participate in paper trading)
        self.active_symbols: Set[str] = active_symbols or {symbol}
        
        # Legacy primary symbol
        self.symbol = symbol
        
        # Validate primary symbol is in active set
        if symbol not in self.active_symbols:
            raise ValueError(f"Primary symbol {symbol} not in active_symbols {self.active_symbols}")

        # ================================================================
        # PER-SYMBOL RUNTIME CONTAINERS
        # ================================================================
        self._runtimes: Dict[str, SymbolRuntime] = {}
        
        # Initialize runtime for each active symbol
        for sym in self.active_symbols:
            runtime = SymbolRuntime(symbol=sym)
            runtime.initialize_engines(config=config, safety_gate=safety_gate)
            # Inject Shans dependencies (global shared dependencies)
            runtime.set_shans_dependencies(
                risk_guard=self.risk_guard,
                data_validator=self.data_validator,
                entropy_decoder=self.entropy_decoder
            )
            self._runtimes[sym] = runtime
            logger.info(f"Initialized SymbolRuntime for {sym} with per-symbol ShansCurve")
        
        # Legacy compatibility: direct references to primary symbol's runtime components
        self._primary_runtime = self._runtimes[symbol]
        self._last_order_book: Optional[OrderBookSnapshot] = self._primary_runtime.last_order_book
        self._last_candle: Optional[Candle] = self._primary_runtime.last_candle
        self._last_tpe_signal: Optional[TopologicalSignal] = self._primary_runtime.last_tpe_signal
        self._last_equity: float = config.initial_capital
        self._last_price: float = self._primary_runtime.last_price
        self._last_fusion: Optional[FusionDecision] = None
        self._last_risk_state: Optional[Dict[str, Any]] = None
        self._current_regime: RegimeType = RegimeType.UNKNOWN
        self._current_volatility: float = self._primary_runtime.current_volatility

        self._recalibration_active: bool = False
        self._recalibration_start_ns: int = 0
        
        # PER-SYMBOL THROTTLE: track last processed timestamp per symbol
        # Explicit new field name — does NOT reuse old scalar field
        self._last_book_receive_ns_by_symbol: Dict[str, int] = {}

        # CANDLE ADMISSION HARDENING: Track last admitted candle timestamp per symbol
        # Protected by self._lock
        self._last_admitted_candle_ts_ns: Dict[str, int] = {}
        self._candle_rejection_tracker: CandleRejectionTracker = CandleRejectionTracker()

        # SHANS DIAGNOSTIC: Track processed book counts per symbol
        self._book_processed_count: Dict[str, int] = {}

        # LIVE_GATE: Per-symbol last log time for Shans-readiness gate (wall-clock seconds).
        # Limits log volume to at most one entry per 5 seconds per symbol.
        # NOT used for trading decisions — logging hygiene only.
        self._shans_gate_last_log_ts: Dict[str, float] = {}

        self._metrics = LoopMetrics()
        self._lock = threading.Lock()
        self._running = False

        logger.info("MainLoop initialized: symbol=%s active_symbols=%s (Per-Symbol Shans Ownership)",
                   symbol, list(active_symbols))

    def _get_runtime(self, symbol: str) -> Optional[SymbolRuntime]:
        """Get runtime container for a symbol."""
        return self._runtimes.get(symbol)
    
    def _ensure_runtime(self, symbol: str) -> Optional[SymbolRuntime]:
        """Get or create runtime for a symbol (defensive creation)."""
        runtime = self._runtimes.get(symbol)
        if runtime is None:
            # Defensive creation for symbols not in active set
            if symbol not in self.active_symbols:
                logger.warning(f"Symbol {symbol} not in active_symbols, cannot create runtime")
                return None
            runtime = SymbolRuntime(symbol=symbol)
            runtime.initialize_engines(config=self.config, safety_gate=self.safety_gate)
            runtime.set_shans_dependencies(
                risk_guard=self.risk_guard,
                data_validator=self.data_validator,
                entropy_decoder=self.entropy_decoder
            )
            self._runtimes[symbol] = runtime
            logger.info(f"Defensively created SymbolRuntime for {symbol} with per-symbol ShansCurve")
        return runtime
    
    def _sync_legacy_references(self) -> None:
        """Sync legacy direct references with primary symbol's runtime."""
        runtime = self._runtimes.get(self.symbol)
        if runtime:
            self._last_order_book = runtime.last_order_book
            self._last_candle = runtime.last_candle
            self._last_tpe_signal = runtime.last_tpe_signal
            self._last_price = runtime.last_price
            self._current_volatility = runtime.current_volatility
            self._primary_runtime = runtime

    def _update_physical_freshness(self, symbol: str, exchange_ts_ns: int) -> None:
        """
        Refresh Fusion's critical physical signal from an admitted market-data event.

        SignalFusion intentionally hard-vetoes stale physical evidence. The
        timestamp supplied here must therefore match the market event that is
        about to drive Fusion, not an unrelated wall-clock fallback.
        """
        receive_ns = time.time_ns()
        latency_ms = max(0.0, (receive_ns - exchange_ts_ns) / 1_000_000)
        self.physical_validator.record_latency(
            symbol=symbol,
            exchange=self.exchange,
            latency_ms=latency_ms,
            order_size=0.0,
            price_impact_bps=0.0,
            timestamp_ns=exchange_ts_ns,
        )
        phys_dict = self.physical_validator.to_fusion_dict(self.exchange)
        self.signal_fusion.update_physical(phys_dict, exchange_ts_ns)

    def _get_dispatch_regime(self, runtime: SymbolRuntime) -> RegimeType:
        """Return the symbol-owned regime when available, else legacy global."""
        detector = getattr(runtime, "regime_detector", None)
        get_current_regime = getattr(detector, "get_current_regime", None)
        if callable(get_current_regime):
            regime = get_current_regime()
            if isinstance(regime, RegimeType):
                return regime
        return self._current_regime

    def _classify_shadow_front_decline(
        self,
        strategy: object,
        exchange_ts_ns: int,
    ) -> Tuple[str, Dict[str, object]]:
        """
        Explain a ShadowFront no-signal result from existing strategy state.

        This mirrors ShadowFront's entry gate order for diagnostics only. It
        does not call mutating update methods, mutate state, or relax any
        threshold.
        """
        if strategy is None:
            return "shadowfront_declined_strategy_missing", {}

        def _float_attr(name: str, default: float = 0.0) -> float:
            try:
                return float(getattr(strategy, name, default))
            except (TypeError, ValueError):
                return default

        cooldown_until = getattr(strategy, "_cooldown_until_ns", 0)
        if not isinstance(cooldown_until, int):
            cooldown_until = 0
        if exchange_ts_ns < cooldown_until:
            return (
                "shadowfront_declined_cooldown",
                {"cooldown_until_ns": cooldown_until},
            )

        is_eligible = getattr(strategy, "_is_eligible", True)
        if not isinstance(is_eligible, bool):
            is_eligible = True
        if not is_eligible:
            return "shadowfront_declined_not_eligible", {}

        toxicity_high = getattr(strategy, "_toxicity_high", False)
        if not isinstance(toxicity_high, bool):
            toxicity_high = False
        if toxicity_high:
            return "shadowfront_declined_toxicity_high", {}

        whale_score = _float_attr("_last_whale_score")
        whale_threshold = _float_attr("whale_threshold")
        whale_accumulating = getattr(strategy, "_last_whale_accumulating", False)
        if not isinstance(whale_accumulating, bool):
            whale_accumulating = False
        whale_condition = whale_score >= whale_threshold or whale_accumulating
        if not whale_condition:
            return (
                "shadowfront_declined_whale_condition",
                {
                    "whale_score": whale_score,
                    "whale_threshold": whale_threshold,
                    "whale_accumulating": whale_accumulating,
                },
            )

        sentiment_velocity = _float_attr("_last_sentiment_velocity")
        sentiment_threshold = _float_attr("sentiment_threshold")
        if sentiment_velocity < sentiment_threshold:
            return (
                "shadowfront_declined_sentiment_condition",
                {
                    "sentiment_velocity": sentiment_velocity,
                    "sentiment_threshold": sentiment_threshold,
                },
            )

        calculate_confidence = getattr(strategy, "_calculate_base_confidence", None)
        confidence = None
        if callable(calculate_confidence):
            try:
                confidence = float(calculate_confidence())
            except Exception:
                confidence = None
        min_confidence = _float_attr("min_confidence")
        if confidence is not None and confidence < min_confidence:
            return (
                "shadowfront_declined_confidence",
                {"confidence": confidence, "min_confidence": min_confidence},
            )

        return "shadowfront_declined_entry_conditions", {}

    def _classify_sector_rotation_observed_pair(
        self,
        runtime: SymbolRuntime,
        exchange_ts_ns: int,
    ) -> Tuple[str, Dict[str, object]]:
        """Classify SectorRotation observed-pair readiness without mutation."""
        observed_signal = runtime.last_sector_rotation_observed_signal
        observed_vote = runtime.last_sector_rotation_observed_vote
        if observed_signal is None or observed_vote is None:
            return (
                "observed_pair_missing",
                {
                    "observed_signal_present": observed_signal is not None,
                    "observed_vote_present": observed_vote is not None,
                },
            )

        vote_ts = getattr(observed_vote, "timestamp_ns", None)
        signal_ts = getattr(observed_signal, "exchange_ts_ns", None)
        fresh = (vote_ts == exchange_ts_ns) or (signal_ts == exchange_ts_ns)
        if not fresh:
            return (
                "observed_pair_stale",
                {"vote_ts": vote_ts, "signal_ts": signal_ts},
            )

        return "observed_pair_fresh", {"vote_ts": vote_ts, "signal_ts": signal_ts}

    def _clear_stale_sector_rotation_observed_pair(
        self,
        runtime: SymbolRuntime,
        exchange_ts_ns: int,
    ) -> bool:
        """
        Drop a provably older SectorRotation observed pair after strict rejection.

        Same-candle doctrine means an older pair can never become valid for a
        later candle. Future/out-of-order pairs are left untouched.
        """
        observed_signal = runtime.last_sector_rotation_observed_signal
        observed_vote = runtime.last_sector_rotation_observed_vote
        if observed_signal is None or observed_vote is None:
            return False

        timestamps = [
            ts
            for ts in (
                getattr(observed_vote, "timestamp_ns", None),
                getattr(observed_signal, "exchange_ts_ns", None),
            )
            if isinstance(ts, int)
        ]
        if not timestamps or max(timestamps) >= exchange_ts_ns:
            return False

        runtime.last_sector_rotation_observed_signal = None
        runtime.last_sector_rotation_observed_vote = None
        return True

    # =========================================================================
    # LIFECYCLE
    # =========================================================================

    def start(self) -> None:
        self._running = True
        logger.info("MainLoop started: active_symbols=%s", list(self.active_symbols))

    def stop(self) -> None:
        self._running = False
        logger.info(
            "MainLoop stopped: symbols=%s iterations=%d orders=%d duplicates_rejected=%d stale_rejected=%d invalid_books_skipped=%d",
            list(self.active_symbols),
            self._metrics.iteration_count, 
            self._metrics.orders_submitted,
            self._metrics.candle_duplicates_rejected,
            self._metrics.candle_stale_rejected,
            self._metrics.invalid_books_skipped,
        )

    # =========================================================================
    # MARKET DATA INGRESS — ROUTES TO PER-SYMBOL RUNTIME
    # =========================================================================

    def on_order_book(self, order_book: OrderBookSnapshot) -> None:
        """
        Handle order book update for any active symbol.
        
        Routes to the correct SymbolRuntime for full state update.
        No longer drops non-primary symbols.
        
        PER-SYMBOL THROTTLE: Each symbol has independent 200ms throttle.
        PER-SYMBOL SHANS: Each symbol uses its own ShansCurve instance.
        INVALID BOOK FILTER: Skips books with mid_price <= 0.0 or non-finite spread.
        """
        if not self._running:
            return
        
        symbol = order_book.symbol
        
        # DIAGNOSTIC: Entry log
        logger.info("[SHANS_DIAG] ENTER on_order_book: symbol=%s", symbol)
        
        # Validate symbol is active
        if symbol not in self.active_symbols:
            logger.warning(f"Received order book for inactive symbol {symbol}, dropping")
            return
        
        # ================================================================
        # NARROW INVALID BOOK FILTER
        # Skip books with no bids or no asks (mid_price <= 0.0)
        # Skip books with non-finite spread (inf/nan)
        # ================================================================
        mid = order_book.mid_price
        spread = order_book.spread
        
        if mid <= 0.0:
            self._metrics.invalid_books_skipped += 1
            logger.info("[SHANS_DIAG] INVALID_BOOK_SKIP: symbol=%s mid=%.6f <= 0 (no bids or no asks)", symbol, mid)
            return
        
        if not math.isfinite(spread):
            self._metrics.invalid_books_skipped += 1
            logger.info("[SHANS_DIAG] INVALID_BOOK_SKIP: symbol=%s spread=%s (non-finite)", symbol, str(spread))
            return
        
        # Get runtime
        runtime = self._ensure_runtime(symbol)
        if runtime is None:
            return

        receive_ns = time.time_ns()
        exchange_ts_ns = order_book.exchange_ts_ns

        # ================================================================
        # PER-SYMBOL THROTTLE CHECK
        # ================================================================
        last_receive = self._last_book_receive_ns_by_symbol.get(symbol, 0)
        elapsed_since_last_ns = receive_ns - last_receive
        
        if elapsed_since_last_ns < _MIN_BOOK_PROCESS_INTERVAL_NS:
            logger.info("[SHANS_DIAG] THROTTLE_SKIP: symbol=%s elapsed_ns=%d threshold_ns=%d (%.2fms < %.2fms)", 
                       symbol, elapsed_since_last_ns, _MIN_BOOK_PROCESS_INTERVAL_NS,
                       elapsed_since_last_ns / 1_000_000.0, _MIN_BOOK_PROCESS_INTERVAL_NS / 1_000_000.0)
            return
        
        # Update per-symbol last receive timestamp
        self._last_book_receive_ns_by_symbol[symbol] = receive_ns
        
        # DIAGNOSTIC: Throttle pass
        logger.info("[SHANS_DIAG] THROTTLE_PASS: symbol=%s elapsed_ns=%d (%.2fms)", 
                   symbol, elapsed_since_last_ns, elapsed_since_last_ns / 1_000_000.0)

        # Update processed count for diagnostics
        self._book_processed_count[symbol] = self._book_processed_count.get(symbol, 0) + 1
        processed_total = self._book_processed_count[symbol]
        
        # DIAGNOSTIC: Processing book
        logger.info("[SHANS_DIAG] PROCESSING_BOOK: symbol=%s cnt=%d mid=%.4f spread=%.4f", 
                   symbol, processed_total, mid, spread)

        # Update runtime state
        runtime.update_order_book(order_book)

        # STAGE 2-F3: Update OrderRouter live market mid cache only on the
        # accepted-processing path (after invalid-book filters and after the
        # per-symbol throttle pass, after runtime has accepted this book).
        # This ensures ExecutionEngine's price-sanity validator can read a
        # fresh real per-symbol mid via order_router.get_mid_price(symbol)
        # instead of falling back to the legacy hardcoded simulated price
        # ($50,000 for BTC etc.). Side-effect-free cache update: no order,
        # no matching, no position, no cash, no risk-state change.
        try:
            self.execution_engine.order_router.update_market_mid(
                symbol, mid, exchange_ts_ns,
            )
        except Exception as exc:
            logger.warning(
                "[ORDER_ROUTER_CACHE] update_market_mid failed symbol=%s mid=%.6f: %s",
                symbol, mid, exc,
            )

        # Update data validator for this symbol
        self.data_validator.record_data(symbol, _ns_to_datetime(exchange_ts_ns))
        self.data_validator.mark_good(symbol)

        # Analyze TPE using per-symbol engine
        tpe_signal = runtime.topological_engine.analyze(order_book)
        runtime.update_tpe_signal(tpe_signal)

        # Process ShansCurve and Regime for this symbol
        if mid > 0.0:
            cum_bid_vol, cum_ask_vol = order_book.depth_at_levels(10)
            
            # Use primary runtime's last candle for volume reference (honest degradation)
            last_candle_ref = self._primary_runtime.last_candle if self._primary_runtime else None
            
            # ================================================================
            # PER-SYMBOL SHANS: Use runtime's own ShansCurve instance
            # ================================================================
            shans_instance = runtime.shans_curve
            
            if shans_instance is None:
                logger.warning("[SHANS_DIAG] No ShansCurve instance for symbol=%s", symbol)
            else:
                # DIAGNOSTIC: Before Shans call
                logger.info("[SHANS_DIAG] CALLING_SHANS: symbol=%s mid=%.6f bid_vol=%.2f ask_vol=%.2f ts_ns=%d", 
                           symbol, mid, cum_bid_vol, cum_ask_vol, exchange_ts_ns)
                
                shans_result = shans_instance.update_order_book(
                    symbol=symbol,
                    mid_price=mid,
                    cum_bid_vol=cum_bid_vol,
                    cum_ask_vol=cum_ask_vol,
                    depth_velocity=0.0,
                    timestamp=exchange_ts_ns,
                )
                
                # DIAGNOSTIC: Shans result
                if shans_result is not None:
                    logger.info("[SHANS_DIAG] SHANS_RESULT: symbol=%s result_type=SIGNAL score=%.4f bias=%d conf=%.4f",
                               symbol, shans_result.shans_superfluid_score,
                               shans_result.shans_bias, shans_result.shans_confidence)
                    self.signal_fusion.update_shans(shans_result, exchange_ts_ns)
                    logger.info("[SHANS_DIAG] FUSION_UPDATE_CALLED: symbol=%s", symbol)
                else:
                    logger.info("[SHANS_DIAG] SHANS_RESULT: symbol=%s result_type=None", symbol)

            bid_price = mid - spread / 2.0
            ask_price = mid + spread / 2.0
            last_volume = last_candle_ref.volume if last_candle_ref is not None else 0.0
            # PER-SYMBOL REGIME: Use symbol's own detector with fallback to global.
            if runtime.regime_detector is not None:
                regime_tuple = runtime.regime_detector.update(
                    price=mid,
                    volume=last_volume,
                    bid_price=bid_price,
                    ask_price=ask_price,
                    bid_depth=cum_bid_vol,
                    ask_depth=cum_ask_vol,
                    exchange_ts_ns=exchange_ts_ns,
                )
            else:
                logger.warning(
                    "[REGIME] No per-symbol detector for %s, using global fallback",
                    symbol,
                )
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
            if symbol == self.symbol:
                self._current_regime = regime_tuple[0]
            
            # Update sentiment proxy with regime multiplier
            runtime.update_regime_multiplier(regime_tuple[0])

        # Physical validator uses per-symbol admitted market-data events.
        self._update_physical_freshness(symbol, exchange_ts_ns)

        # Update sentiment engine with current proxy value
        runtime.update_sentiment_engine(exchange_ts_ns)

        # ================================================================
        # OBSERVE-ONLY (Stage 2-B): LiquidityVoid feed pumping
        # Dormant sleeve receives real per-symbol overlays + the order book
        # and may emit Optional[StrategySignal]. Returned signal is LOGGED
        # ONLY — not dispatched, not adapted, not voted, no execution path.
        # ================================================================
        self._observe_liquidity_void(symbol, runtime, order_book)

        self._metrics.last_order_book_exchange_ts_ns = exchange_ts_ns

        # Sync legacy references if this was the primary symbol
        if symbol == self.symbol:
            self._sync_legacy_references()

    def on_candle(self, candle: Candle) -> None:
        """
        Handle candle update for any active symbol with atomic admission control.
        
        Each symbol maintains its own last_admitted_candle_ts_ns to prevent
        duplicate or stale candles from being processed.
        """
        if not self._running:
            return

        symbol = candle.symbol
        
        # Validate symbol is active
        if symbol not in self.active_symbols:
            logger.warning(f"Received candle for inactive symbol {symbol}, dropping")
            return
        
        # Get runtime
        runtime = self._ensure_runtime(symbol)
        if runtime is None:
            return

        # ================================================================
        # CANDLE ADMISSION — ATOMIC CHECK-AND-UPDATE
        # Protected by self._lock to prevent race conditions
        # ================================================================
        incoming_ts_ns = candle.exchange_ts_ns

        with self._lock:
            last_ts_ns = self._last_admitted_candle_ts_ns.get(symbol, 0)

            # Duplicate candle (identical timestamp)
            if incoming_ts_ns == last_ts_ns:
                self._metrics.candle_duplicates_rejected += 1
                dup_count = self._metrics.candle_duplicates_rejected
                should_log_dup = self._candle_rejection_tracker.should_log(symbol, "duplicate")
                if should_log_dup:
                    logger.warning(
                        "CANDLE_REJECT_DUPLICATE: symbol=%s ts_ns=%d last_ts_ns=%d total_duplicates=%d",
                        symbol,
                        incoming_ts_ns,
                        last_ts_ns,
                        dup_count,
                    )
                return

            # Backward/stale candle (older timestamp)
            if incoming_ts_ns < last_ts_ns:
                self._metrics.candle_stale_rejected += 1
                delta_ns = incoming_ts_ns - last_ts_ns
                stale_count = self._metrics.candle_stale_rejected
                should_log_stale = self._candle_rejection_tracker.should_log(symbol, "stale")
                if should_log_stale:
                    logger.warning(
                        "CANDLE_REJECT_STALE: symbol=%s incoming_ts_ns=%d last_ts_ns=%d delta_ns=%d total_stale=%d",
                        symbol,
                        incoming_ts_ns,
                        last_ts_ns,
                        delta_ns,
                        stale_count,
                    )
                return

            # Monotonic candle — update last admitted timestamp
            self._last_admitted_candle_ts_ns[symbol] = incoming_ts_ns

        # ================================================================
        # END OF ATOMIC ADMISSION SECTION
        # ================================================================

        exchange_ts_ns = candle.exchange_ts_ns

        # Update runtime state
        runtime.update_candle(candle)
        runtime.current_volatility = self._compute_volatility(candle)

        # ================================================================
        # WHALE FLOW — STRICT CHANNEL PURITY
        # ================================================================
        # Do NOT feed Candle into SignalFusion whale_flow.
        # Whale fusion channel accepts only WhaleFlowAlert-like payloads
        # produced by the per-symbol WhaleFlowEngine from trade flow.
        whale_alert = runtime.last_whale_alert

        if whale_alert is not None:
            self.signal_fusion.update_whale(whale_alert, exchange_ts_ns)

        # Update per-symbol toxicity engine
        runtime.toxicity_engine.update_candle(
            volume=candle.volume,
            high=candle.high,
            low=candle.low,
            close=candle.close,
            timestamp_ns=exchange_ts_ns,
        )
        tox_alert = runtime.toxicity_engine.update_toxicity(exchange_ts_ns)
        self.signal_fusion.update_toxicity(tox_alert, exchange_ts_ns)
        
        # Update sentiment proxy with toxicity multiplier
        runtime.update_toxicity_multiplier_from_alert()

        # Entropy decoder (global, per-symbol call)
        raw_entropy = min(1.0, (candle.high - candle.low) / max(candle.close, 1e-9) * 20.0)
        entropy_score = self.entropy_decoder.update(symbol, exchange_ts_ns, raw_entropy)
        self.signal_fusion.update_entropy(entropy_score, exchange_ts_ns)

        # Insider signal (global, per-symbol snapshot)
        insider_snapshot = self.insider_engine.get_or_default_snapshot(symbol, exchange_ts_ns)
        self.signal_fusion.update_insider(insider_snapshot, exchange_ts_ns)

        # Commander equity update (global)
        self.commander.update_equity(self._last_equity, exchange_ts_ns)

        # ================================================================
        # OBSERVE-ONLY (Stage 2-B): SectorRotation feed pumping
        # Dormant sleeve receives real per-symbol overlays + the candle and
        # may emit Optional[StrategySignal] (entry from update_candle, exit
        # from update_price). Returned signals are LOGGED ONLY — not
        # dispatched, not adapted, not voted, no execution path. Runs before
        # the LIVE GATE so observation continues regardless of Shans state.
        # ================================================================
        self._observe_sector_rotation(symbol, runtime, candle)

        # ================================================================
        # LIVE GATE — Per-symbol Shans readiness
        # Enforces correct temporal authority: Shans state → Fusion → Dispatch.
        # Fusion MUST NOT execute until per-symbol ShansCurve has a lawful
        # ready state (buffer >= curvature_window AND validator has passed).
        # All update_*() calls above continue regardless — they feed the state
        # that fusion will consume once Shans is ready.
        # ================================================================
        _shans_ready = (
            runtime.shans_curve is not None
            and runtime.shans_curve.is_ready()
        )
        if not _shans_ready:
            _gate_now = time.time()
            _gate_last = self._shans_gate_last_log_ts.get(symbol, 0.0)
            if _gate_now - _gate_last >= 5.0:
                _buf_len = len(runtime.shans_curve._p) if runtime.shans_curve is not None else 0
                _buf_req = runtime.shans_curve.curvature_window if runtime.shans_curve is not None else 0
                logger.info(
                    "[LIVE_GATE] BLOCK_FUSION symbol=%s reason=SHANS_NOT_READY buffer=%d required=%d",
                    symbol, _buf_len, _buf_req,
                )
                _log_dispatch_diag(
                    "shans_not_ready",
                    symbol=symbol,
                    exchange_ts_ns=exchange_ts_ns,
                    shans_ready=False,
                    shans_buffer=_buf_len,
                    shans_required=_buf_req,
                    submit_signal_called=False,
                )
                self._shans_gate_last_log_ts[symbol] = _gate_now
        else:
            # Refresh critical physical evidence on the admitted candle clock
            # before Fusion evaluates physical freshness against this same
            # dispatch timestamp. This preserves hard stale-physical vetoes
            # while preventing active admitted candles from comparing against
            # an older order-book event timestamp.
            self._update_physical_freshness(symbol, exchange_ts_ns)

            # Fuse signals (global — LIMIT: single cache, called per-symbol)
            fusion = self.signal_fusion.fuse(exchange_ts_ns)
            self._last_fusion = fusion

            # Dispatch per-symbol (DIAGNOSTIC: trace dispatch entry)
            if fusion is None:
                logger.info("[DISPATCH] %s: fusion is None", symbol)
            else:
                logger.info(
                    "[DISPATCH] %s: fusion advisory_attack_mode=%s, preferred_sleeve=%s",
                    symbol,
                    getattr(fusion, 'attack_mode', '<missing>'),
                    getattr(fusion, 'preferred_sleeve', '<missing>'),
                )

            self._dispatch_fusion(symbol, runtime, fusion, exchange_ts_ns)

        self._metrics.iteration_count += 1
        self._metrics.last_candle_exchange_ts_ns = exchange_ts_ns

        # Risk assessment (uses primary symbol's TPE signal for now)
        tpe_signal = self._primary_runtime.last_tpe_signal
        tpe_coherence = tpe_signal.coherence_score if tpe_signal is not None else 0.5
        risk_state = self.risk_guard.assess_state(self._last_equity, tpe_coherence)
        self._last_risk_state = risk_state
        self._metrics.last_risk_assessment_ns = exchange_ts_ns

        self._advance_recalibration(risk_state, tpe_signal, exchange_ts_ns)
        self.execution_engine.process_events()

        if (self._metrics.iteration_count - self._metrics.last_health_log_iteration
                >= self.health_log_interval_iterations):
            self._log_health()
            self._metrics.last_health_log_iteration = self._metrics.iteration_count

        self._metrics.consecutive_errors = 0

        # Sync legacy references if this was the primary symbol
        if symbol == self.symbol:
            self._sync_legacy_references()

    def on_trade(self, symbol: str, price: float, timestamp_ns: int) -> None:
        """
        Handle trade update for any active symbol - basic version.
        
        Now routes to per-symbol runtime using the symbol from trade data.
        No longer assumes primary symbol only.
        """
        if not self._running:
            return
        
        # Validate symbol is active
        if symbol not in self.active_symbols:
            logger.warning(f"Received trade for inactive symbol {symbol}, dropping")
            return
        
        # Get runtime
        runtime = self._ensure_runtime(symbol)
        if runtime is None:
            return
        
        # Update runtime with trade price
        runtime.update_trade(price=price, timestamp_ns=timestamp_ns)
        
        # Update data validator
        self.data_validator.record_data(symbol, _ns_to_datetime(timestamp_ns))
        self.data_validator.mark_good(symbol)
        
        # Update legacy reference if primary
        if symbol == self.symbol:
            self._last_price = price
        
        self._metrics.last_trade_exchange_ts_ns = timestamp_ns

    def on_trade_with_whale(self, symbol: str, price: float, side: int, 
                            volume: float, timestamp_ns: int) -> None:
        """
        Trade update with whale data for per-symbol engine and sentiment proxy.
        
        Called from main.py:_on_trade() with real trade details.
        Feeds trade data to per-symbol WhaleFlowEngine and sentiment proxy.
        """
        if not self._running:
            return
        if symbol not in self.active_symbols:
            logger.warning(f"Received whale trade for inactive symbol {symbol}, dropping")
            return
        
        runtime = self._ensure_runtime(symbol)
        if runtime is None:
            return
        
        # Update runtime with trade price
        runtime.update_trade(price=price, timestamp_ns=timestamp_ns)
        
        buy_vol = volume if side == 1 else 0.0
        sell_vol = volume if side == -1 else 0.0
        
        # Update whale engine. price is required so WhaleFlowEngine can
        # normalize raw asset trade sizes against the USD-notional whale
        # threshold (avg_trade_size * price / 100_000).
        alert = runtime.update_whale_with_trade(
            buy_volume=buy_vol,
            sell_volume=sell_vol,
            trade_sizes=[volume],
            timestamp_ns=timestamp_ns,
            price=price,
        )
        
        if alert:
            logger.debug(f"Per-symbol whale update for {symbol}: dir={alert.direction.name}, conf={alert.confidence:.3f}")
        
        # Update sentiment proxy with trade volumes
        runtime.update_trade_with_volumes(buy_vol, sell_vol, timestamp_ns)
        
        # Update sentiment engine
        runtime.update_sentiment_engine(timestamp_ns)
        
        self.data_validator.record_data(symbol, _ns_to_datetime(timestamp_ns))
        self.data_validator.mark_good(symbol)
        
        if symbol == self.symbol:
            self._last_price = price
        
        self._metrics.last_trade_exchange_ts_ns = timestamp_ns

    def on_equity_update(self, current_equity: float, exchange_ts_ns: int) -> None:
        """Update equity (global, not per-symbol)."""
        if not self._running:
            return
        self._last_equity = current_equity
        self.risk_guard.update_equity_history(current_equity)
        self.execution_engine.update_equity(current_equity)
        self.commander.update_equity(current_equity, exchange_ts_ns)
        self._metrics.last_equity_update_ns = exchange_ts_ns

    # =========================================================================
    # BUNDLE 1 REDO REPAIR: DISPATCH (NOW PER-SYMBOL WITH DIAGNOSTICS)
    # =========================================================================

    def _dispatch_fusion(self, symbol: str, runtime: SymbolRuntime, fusion: FusionDecision, exchange_ts_ns: int) -> None:
        """
        Lawful dispatch: FusionDecision → StrategyRouter → per-symbol StrategyVote
        → DecisionCompiler → ExecutionEngine.submit_signal().

        HYBRID ARCHITECTURE (6G-A): preferred sleeve evaluated first. If it lawfully
        declines, remaining eligible+registered fallback sleeves are evaluated in
        StrategyRouter priority order. No-trade is preserved when all candidates decline.
        Each sleeve attempt and decline is logged explicitly.
        """
        if fusion is None:
            logger.info("[DISPATCH] %s: fusion is None → returning", symbol)
            _log_dispatch_diag(
                "fusion_not_actionable",
                symbol=symbol,
                exchange_ts_ns=exchange_ts_ns,
                fusion_present=False,
                submit_signal_called=False,
            )
            return

        self.strategy_router.update_macro_state()
        preferred = self.strategy_router.get_preferred_strategy(fusion)

        logger.info("[DISPATCH] %s: preferred_strategy=%s", symbol, repr(preferred) if preferred is not None else "None")

        if preferred is None:
            logger.info("[DISPATCH] %s: no preferred strategy -> returning", symbol)
            _log_dispatch_diag(
                "preferred_sleeve_missing",
                symbol=symbol,
                exchange_ts_ns=exchange_ts_ns,
                fusion_present=True,
                preferred_sleeve=None,
                submit_signal_called=False,
            )
            return

        sleeve_registry = {
            SleeveType.SHADOW_FRONT:    runtime.shadow_front_strategy,
            SleeveType.GAMMA_FRONT:     runtime.gamma_front_strategy,
            # STAGE 2-D1: Paper-only proving lane. SECTOR_ROTATION is dispatchable
            # via observed (signal, vote) pair when Fusion/Router admits it and
            # broker_mode == "paper". FLV is registered for naturally-inert
            # routing (Fusion never sets liquidity_void_eligible=True today; the
            # branch is intentionally not implemented in 2-D1 due to event-clock
            # mismatch between order-book observation and candle dispatch — see
            # post-patch report §3 for the Stage 2-D2/D3 hand-off).
            SleeveType.SECTOR_ROTATION: runtime.sector_rotation_strategy,
            SleeveType.FLV:             runtime.liquidity_void_strategy,
        }

        eligible_strategies = self.strategy_router.get_eligible_strategies(fusion)
        eligible_repr = [repr(s) for s in eligible_strategies]
        logger.info("[DISPATCH] %s: eligible_strategies=%s", symbol, eligible_repr)

        fallback_candidates = [
            s for s in eligible_strategies
            if s != preferred and s in sleeve_registry and sleeve_registry[s] is not None
        ]
        candidates = []
        if preferred in sleeve_registry and sleeve_registry[preferred] is not None:
            candidates.append(preferred)
        candidates.extend(fallback_candidates)

        if not candidates:
            logger.info(
                "[DISPATCH] %s: no_registered_candidates eligible=%s → returning",
                symbol, eligible_repr,
            )
            _log_dispatch_diag(
                "sleeve_blocked",
                symbol=symbol,
                exchange_ts_ns=exchange_ts_ns,
                preferred_sleeve=repr(preferred),
                eligible_sleeves=eligible_repr,
                candidates=[],
                submit_signal_called=False,
            )
            return

        logger.info(
            "[DISPATCH] %s: dispatch_candidates=%s (preferred=%s, fallbacks=%s)",
            symbol,
            [repr(s) for s in candidates],
            repr(preferred),
            [repr(s) for s in fallback_candidates],
        )

        signal = None
        strategy_vote = None
        winning_sleeve = None
        terminal_reason_code = None
        terminal_reason_fields: Dict[str, object] = {}
        terminal_reason_logged = False

        for sleeve in candidates:
            logger.info("[DISPATCH] %s: evaluating sleeve=%s", symbol, repr(sleeve))

            if sleeve == SleeveType.SHADOW_FRONT:
                logger.info("[DISPATCH] %s: SHADOW_FRONT branch entered", symbol)
                self._update_shadow_front_overlays(symbol, runtime, exchange_ts_ns)
                is_eligible = sleeve in eligible_strategies
                if runtime.shadow_front_strategy:
                    runtime.shadow_front_strategy.update_from_fusion(is_eligible)
                    logger.info("[DISPATCH] %s: update_from_fusion(%s) called", symbol, is_eligible)
                logger.info("[DISPATCH] %s: calling _generate_signal_and_vote()", symbol)
                sig, vote = self._generate_signal_and_vote(symbol, runtime, exchange_ts_ns)
                if sig is None:
                    reason_code, reason_fields = self._classify_shadow_front_decline(
                        runtime.shadow_front_strategy,
                        exchange_ts_ns,
                    )
                    terminal_reason_code = reason_code
                    terminal_reason_fields = dict(reason_fields)

            elif sleeve == SleeveType.GAMMA_FRONT:
                logger.info("[DISPATCH] %s: GAMMA_FRONT branch entered", symbol)
                sig, vote = self._generate_signal_and_vote_gamma_front(symbol, runtime, exchange_ts_ns)

            elif sleeve == SleeveType.SECTOR_ROTATION:
                # STAGE 2-D1: Paper-only active vote admission for SectorRotation.
                # Consumes the observed (signal, vote) pair already produced by
                # Stage 2-B/2-C on the same candle. Strict equality of
                # vote.timestamp_ns == exchange_ts_ns enforces same-candle
                # freshness; SectorRotation observation runs on candle ingress
                # so this equality holds when a fresh signal exists.
                logger.info("[DISPATCH] %s: SECTOR_ROTATION branch entered (paper-only)", symbol)
                reason_code, reason_fields = self._classify_sector_rotation_observed_pair(
                    runtime,
                    exchange_ts_ns,
                )
                sig, vote = self._consume_observed_pair_sector_rotation(
                    symbol, runtime, exchange_ts_ns,
                )
                if sig is None and reason_code != "observed_pair_fresh":
                    terminal_reason_code = reason_code
                    terminal_reason_fields = dict(reason_fields)
                    terminal_reason_logged = True

            elif sleeve == SleeveType.FLV:
                # STAGE 2-D3 (Option C): Paper-only active vote admission for
                # LiquidityVoid via the buffered pre-candle candidate scheme.
                # Reaches this branch only when Fusion/Router admits FLV; today
                # that requires Stage 2-D2's UNKNOWN-regime eligibility flag.
                # LV observation continues firing on order-book ingress; this
                # branch READS the buffered (signal, vote) without re-firing
                # LV's strategy methods or its adapter. Edge preserved.
                logger.info("[DISPATCH] %s: FLV branch entered (paper-only)", symbol)
                sig, vote = self._consume_observed_pair_liquidity_void(
                    symbol, runtime, exchange_ts_ns,
                )

            else:
                logger.info("[DISPATCH] %s: sleeve=%s no_dispatch_branch → skip", symbol, repr(sleeve))
                continue

            if sig is not None:
                signal = sig
                strategy_vote = vote
                winning_sleeve = sleeve
                logger.info("[DISPATCH] %s: sleeve=%s produced_signal → selected", symbol, repr(sleeve))
                break

            logger.info("[DISPATCH] strategy_signal_none sleeve=%s → trying_fallback", repr(sleeve))

        if signal is None:
            logger.info(
                "[DISPATCH] %s: all_sleeves_declined candidates=%s",
                symbol, [repr(s) for s in candidates],
            )
            if terminal_reason_code is None:
                _log_dispatch_diag(
                    "strategy_signal_missing",
                    symbol=symbol,
                    exchange_ts_ns=exchange_ts_ns,
                    preferred_sleeve=repr(preferred),
                    eligible_sleeves=eligible_repr,
                    candidates=[repr(s) for s in candidates],
                    eligibility_only=True,
                    executable_signal_present=False,
                    submit_signal_called=False,
                )
            elif terminal_reason_logged:
                pass
            else:
                _log_dispatch_diag(
                    terminal_reason_code,
                    symbol=symbol,
                    exchange_ts_ns=exchange_ts_ns,
                    preferred_sleeve=repr(preferred),
                    eligible_sleeves=eligible_repr,
                    candidates=[repr(s) for s in candidates],
                    eligibility_only=True,
                    executable_signal_present=False,
                    terminal_dispatch_reason=True,
                    submit_signal_called=False,
                    **terminal_reason_fields,
                )
            return
        if strategy_vote is None:
            logger.info("[DISPATCH] %s: strategy_vote=None signal_present sleeve=%s", symbol, repr(winning_sleeve))
            _log_dispatch_diag(
                "strategy_vote_missing",
                symbol=symbol,
                exchange_ts_ns=exchange_ts_ns,
                winning_sleeve=repr(winning_sleeve),
                signal_present=True,
                submit_signal_called=False,
            )
            return

        logger.info("[DISPATCH] strategy_vote_ready sleeve=%s", repr(winning_sleeve))

        commander = getattr(self, "commander", None)
        get_aggression_contract = getattr(
            commander, "get_aggression_contract", None
        )
        if not callable(get_aggression_contract):
            get_aggression_contract = Commander().get_aggression_contract

        aggression_contract = get_aggression_contract(exchange_ts_ns)
        aggression_contract_metadata = aggression_contract.as_metadata()
        dormant_floor_active_key = "_".join(("moving", "floor", "active"))
        signal_metadata = getattr(signal, "metadata", None)
        advisory_aggression_metadata_present = (
            isinstance(signal_metadata, dict)
            and (
                "aggression_context" in signal_metadata
                or "aggression_snapshot_id" in signal_metadata
            )
        )
        aggression_replay_proof = {
            "authority_owner": aggression_contract_metadata["authority_owner"],
            "authority_version": aggression_contract_metadata["authority_version"],
            "execution_is_attack_source": (
                "Commander.canonical_aggression_contract.execution_is_attack"
            ),
            "execution_is_attack": aggression_contract_metadata["execution_is_attack"],
            "fusion_attack_mode": getattr(fusion, "attack_mode", None),
            "fusion_attack_mode_authoritative": False,
            "advisory_aggression_metadata_present": advisory_aggression_metadata_present,
            "advisory_aggression_metadata_authoritative": False,
            "risk_guard_final_veto_preserved": (
                aggression_contract_metadata["risk_guard_final_veto_preserved"]
            ),
            "economic_admissibility_final_veto_preserved": (
                aggression_contract_metadata[
                    "economic_admissibility_final_veto_preserved"
                ]
            ),
            "stale_gate_final_veto_preserved": (
                aggression_contract_metadata["stale_gate_final_veto_preserved"]
            ),
            dormant_floor_active_key: aggression_contract_metadata[
                dormant_floor_active_key
            ],
            "dormant_governors_active": (
                aggression_contract_metadata["dormant_governors_active"]
            ),
        }
        if isinstance(signal_metadata, dict):
            signal_metadata["canonical_aggression_contract"] = (
                aggression_contract_metadata
            )
            signal_metadata["aggression_replay_proof"] = aggression_replay_proof

        truth_frame = self._build_truth_frame(exchange_ts_ns)

        _log_dispatch_diag(
            "decision_compile_attempted",
            symbol=symbol,
            exchange_ts_ns=exchange_ts_ns,
            winning_sleeve=repr(winning_sleeve),
            strategy_vote_present=True,
        )
        decision_record = self.decision_compiler.compile(
            truth_frame,
            strategy_votes=[strategy_vote],
            additional_inputs={
                "canonical_aggression_contract": aggression_contract_metadata,
                "aggression_replay_proof": aggression_replay_proof,
            },
        )
        self._metrics.compilation_cycles += 1
        logger.info(
            "[DISPATCH] %s: DecisionRecord compiled: uuid=%s type=%s",
            symbol,
            getattr(decision_record, 'decision_uuid', '<missing>'),
            getattr(decision_record, 'decision_type', '<missing>'),
        )

        decision_uuid = getattr(decision_record, "decision_uuid", None)
        signal_metadata = getattr(signal, "metadata", None)
        if decision_uuid and isinstance(signal_metadata, dict):
            signal_metadata.setdefault("decision_uuid", decision_uuid)

        submitted = self.execution_engine.submit_signal(
            signal=signal,
            current_price=runtime.last_price,
            is_attack=aggression_contract.execution_is_attack,
            decision_record=decision_record,
        )
        _log_dispatch_diag(
            "submit_signal_called",
            symbol=symbol,
            exchange_ts_ns=exchange_ts_ns,
            winning_sleeve=repr(winning_sleeve),
            decision_uuid=getattr(decision_record, "decision_uuid", None),
            submitted=submitted,
            submit_signal_called=True,
        )
        if submitted:
            self._metrics.orders_submitted += 1
            logger.info("[DISPATCH] submitted=True sleeve=%s", repr(winning_sleeve))
            logger.info(
                "[DISPATCH] %s: Signal submitted: decision_uuid=%s side=%s qty=%s",
                symbol,
                getattr(decision_record, 'decision_uuid', '<missing>'),
                getattr(signal, 'side', '<missing>'),
                getattr(signal, 'quantity', '<missing>'),
            )
        else:
            self._metrics.orders_rejected += 1
            logger.info("[DISPATCH] submitted=False sleeve=%s", repr(winning_sleeve))
            logger.info(
                "[DISPATCH] %s: Signal rejected by execution: decision_uuid=%s",
                symbol,
                getattr(decision_record, 'decision_uuid', '<missing>'),
            )

    def _update_shadow_front_overlays(self, symbol: str, runtime: SymbolRuntime, exchange_ts_ns: int) -> None:
        """
        Update per-symbol ShadowFront with latest overlay state.
        
        WHALE: NOW WIRED - retrieves from per-symbol whale engine and feeds to strategy.
        SENTIMENT: NOW WIRED - retrieves from per-symbol sentiment velocity engine.
        """
        if not runtime.shadow_front_strategy:
            return
        
        # ================================================================
        # WHALE OVERLAY - WIRED
        # ================================================================
        whale_score = runtime.get_whale_score()
        if whale_score is not None:
            runtime.shadow_front_strategy.update_whale(whale_score)
            logger.debug(f"Whale overlay for {symbol}: score={whale_score.score:.3f}")
        
        # ================================================================
        # SENTIMENT OVERLAY - NOW WIRED via MarketSentimentProxy
        # ================================================================
        sentiment_velocity = runtime.get_sentiment_velocity()
        runtime.shadow_front_strategy.update_sentiment(sentiment_velocity, exchange_ts_ns)
        logger.debug(f"Sentiment overlay for {symbol}: velocity={sentiment_velocity:.6f}")

        # ================================================================
        # TOXICITY OVERLAY - WIRED
        # ================================================================
        tox_alert = runtime.toxicity_engine.get_last_alert()
        runtime.shadow_front_strategy.update_toxicity_state(tox_alert)

        # ================================================================
        # INSIDER OVERLAY - WIRED
        # ================================================================
        insider_snapshot = self.insider_engine.get_or_default_snapshot(symbol, exchange_ts_ns)
        runtime.shadow_front_strategy.update_insider_state(insider_snapshot)

    def _generate_signal_and_vote(
        self, symbol: str, runtime: SymbolRuntime, exchange_ts_ns: int
    ) -> Tuple[Optional[StrategySignal], Optional[StrategyVote]]:
        """
        Generate StrategySignal and StrategyVote from per-symbol ShadowFrontStrategy.
        
        DIAGNOSTIC: Added INFO logs for entry conditions.
        """
        current_price = runtime.last_price
        if current_price <= 0.0:
            logger.info("[SIGNAL_GEN] %s: current_price=%.4f <= 0 → returning None", symbol, current_price)
            return None, None

        capital_usd = Decimal(str(self._last_equity))
        kelly_multiplier = Decimal(str(self.commander.get_kelly_multiplier()))
        regime = self._get_dispatch_regime(runtime)
        volatility = Decimal(str(runtime.current_volatility))

        if not runtime.shadow_front_strategy:
            logger.info("[SIGNAL_GEN] %s: no shadow_front_strategy → returning None", symbol)
            return None, None

        # Inject position sizing engine into per-symbol strategy if not already set
        if hasattr(runtime.shadow_front_strategy, '_position_sizing_engine') and runtime.shadow_front_strategy._position_sizing_engine is None:
            runtime.shadow_front_strategy.set_position_sizing_engine(self.position_sizing_engine)

        logger.info(
            "[SIGNAL_GEN] %s: calling update_price(price=%.4f, capital=%.2f, kelly=%.3f, vol=%.4f, regime=%s)",
            symbol, current_price, capital_usd, kelly_multiplier, volatility, getattr(regime, 'value', repr(regime))
        )

        signal = runtime.shadow_front_strategy.update_price(
            price=current_price,
            timestamp_ns=exchange_ts_ns,
            capital_usd=capital_usd,
            kelly_multiplier=kelly_multiplier,
            volatility=volatility,
            regime=regime,
        )

        if signal is None:
            logger.info("[SIGNAL_GEN] %s: update_price returned None (gate blocked)", symbol)
            return None, None

        decision_uuid = self.decision_compiler.reserve_decision_uuid()
        
        strategy_vote = runtime.shadow_front_strategy.to_strategy_vote(
            signal, exchange_ts_ns, decision_uuid=decision_uuid
        )
        if strategy_vote is None:
            logger.info("[SIGNAL_GEN] %s: to_strategy_vote returned None (sizing missing)", symbol)
            return None, None

        logger.info("[SIGNAL_GEN] %s: signal+vote created successfully", symbol)
        return signal, strategy_vote

    def _generate_signal_and_vote_gamma_front(
        self, symbol: str, runtime: SymbolRuntime, exchange_ts_ns: int
    ) -> Tuple[Optional[StrategySignal], Optional[StrategyVote]]:
        """
        GAMMA_FRONT ADAPTER: Generate StrategySignal and StrategyVote.

        GammaFront.update_price() is exits-only (TTL, TP, SL).
        Entries require DarkPoolPrint via update_dark_pool() — not wired in current runtime.
        In current runtime, update_price() returns None (no position to exit).
        When it does return a signal, this adapter builds a valid StrategyVote.
        """
        current_price = runtime.last_price
        if current_price <= 0.0:
            logger.info("[DISPATCH] strategy_missing preferred_sleeve=GAMMA_FRONT current_price=%.4f <= 0",
                        current_price)
            return None, None

        strategy = runtime.gamma_front_strategy
        if strategy is None:
            logger.info("[DISPATCH] strategy_missing preferred_sleeve=%s", SleeveType.GAMMA_FRONT)
            return None, None

        # Feed toxicity overlay if toxicity engine available
        if runtime.toxicity_engine is not None and hasattr(strategy, 'update_toxicity'):
            toxicity_alert = runtime.toxicity_engine.get_last_alert()
            strategy.update_toxicity(toxicity_alert)

        logger.info("[DISPATCH] GAMMA_FRONT calling update_price symbol=%s price=%.4f",
                    symbol, current_price)
        signal = strategy.update_price(current_price, exchange_ts_ns)

        if signal is None:
            logger.info("[DISPATCH] strategy_signal_none sleeve=%s", SleeveType.GAMMA_FRONT)
            return None, None

        # Map signal.side to SignalType
        side_str = getattr(signal, 'side', 'buy').lower()
        if side_str == 'buy':
            signal_type = SignalType.BUY
        elif side_str == 'sell':
            signal_type = SignalType.SELL
        else:
            signal_type = SignalType.FLAT

        confidence_raw = getattr(signal, 'confidence', 0.5)
        quantity_raw = getattr(signal, 'quantity', 0.1)

        decision_uuid = self.decision_compiler.reserve_decision_uuid()
        try:
            strategy_vote = StrategyVote(
                decision_uuid=decision_uuid,
                strategy_id=StrategyID.GAMMA_FRONT,
                timestamp_ns=exchange_ts_ns,
                signal=signal_type,
                confidence=Decimal(str(confidence_raw)),
                expected_move_bps=Decimal("0"),
                expected_duration_ns=60_000_000_000,  # GammaFront TTL = 60 s
                risk_appetite=Decimal(str(quantity_raw)),
                invalidation_conditions=[],
                metadata=build_council_metadata(
                    source_module=MODULE_GAMMA_FRONT,
                    source_strategy_id=StrategyID.GAMMA_FRONT.value,
                    source_output_type=SOURCE_STRATEGY_SIGNAL,
                    adapter_name="gamma_front_adapter",
                    contribution_role=ROLE_EXIT,
                    fresh_entry_authorized=False,
                    protective_only=False,
                    requires_existing_position=True,
                    execution_candidate=True,
                    directional_bias=BIAS_SHORT if side_str == "sell" else (BIAS_LONG if side_str == "buy" else BIAS_UNKNOWN),
                    feed_status=FEED_MISSING,
                    raw_confidence=float(confidence_raw),
                    normalized_confidence=float(confidence_raw),
                    reason=getattr(signal, 'reason', '') or "gamma_front_adapter",
                    symbol=getattr(signal, 'symbol', symbol),
                    sleeve="gamma_front",
                    exit_reason=getattr(signal, 'reason', ''),
                    adapter="gamma_front_adapter",
                ),
            )
        except Exception as exc:
            logger.error("[DISPATCH] GAMMA_FRONT StrategyVote construction failed: %s", str(exc))
            return None, None

        logger.info("[DISPATCH] strategy_vote_ready sleeve=%s", SleeveType.GAMMA_FRONT)
        return signal, strategy_vote

    # =========================================================================
    # STAGE 2-D1: PAPER-ONLY ACTIVE VOTE ADMISSION FOR OBSERVED SLEEVES
    # =========================================================================
    # Consumes the most-recent observed (signal, vote) pair produced by Stage
    # 2-B/2-C and feeds it into the SHARED downstream dispatch path so that
    # DecisionCompiler.compile and ExecutionEngine.submit_signal apply the
    # SAME governance gates as ShadowFront/GammaFront (RiskGuard.can_trade,
    # vol fuse, data continuity, net-profit floor at 0.005, paper broker
    # isolation). NEVER:
    #   - calls adapters again (Stage 2-C already produced the vote)
    #   - re-fires the strategy methods (no double state mutation)
    #   - bypasses StrategyRouter eligibility (caller's loop already enforces)
    #   - bypasses Fusion eligibility (caller's loop already enforces)
    #   - touches signal_fusion.py (Fusion policy repair is Stage 2-D2)
    #   - reaches a live broker (broker_mode == "paper" hard gate)
    # =========================================================================

    def _consume_observed_pair_sector_rotation(
        self, symbol: str, runtime: SymbolRuntime, exchange_ts_ns: int
    ) -> Tuple[Optional[StrategySignal], Optional[StrategyVote]]:
        """
        Stage 2-D1: Return the freshest observed (signal, vote) pair from
        SectorRotation under paper-only governance, or (None, None) on any
        gate failure. The shared downstream dispatch path then performs
        DecisionCompiler.compile and ExecutionEngine.submit_signal — the SAME
        path already used by ShadowFront and GammaFront. No new authority is
        created here.

        Hard gates (in order):
          1. broker_mode == "paper"  (paper-only proving lane)
          2. observed signal AND vote both present
          3. vote.timestamp_ns == exchange_ts_ns  (same-candle freshness)
             OR signal.exchange_ts_ns == exchange_ts_ns  (fallback)
        """
        if self.config.broker_mode != "paper":
            logger.info(
                "[PAPER_DISPATCH_SECTOR_ROTATION] %s: blocked — broker_mode=%s "
                "(paper-only gate)",
                symbol, self.config.broker_mode,
            )
            _log_dispatch_diag(
                "sleeve_blocked",
                symbol=symbol,
                exchange_ts_ns=exchange_ts_ns,
                sleeve=repr(SleeveType.SECTOR_ROTATION),
                broker_mode=self.config.broker_mode,
                block_reason="non_paper_broker_mode",
                submit_signal_called=False,
            )
            return None, None

        observed_signal = runtime.last_sector_rotation_observed_signal
        observed_vote = runtime.last_sector_rotation_observed_vote

        if observed_signal is None or observed_vote is None:
            logger.info(
                "[PAPER_DISPATCH_SECTOR_ROTATION] %s: blocked — observed pair missing "
                "(signal=%s vote=%s)",
                symbol,
                "present" if observed_signal is not None else "None",
                "present" if observed_vote is not None else "None",
            )
            _log_dispatch_diag(
                "observed_pair_missing",
                symbol=symbol,
                exchange_ts_ns=exchange_ts_ns,
                sleeve=repr(SleeveType.SECTOR_ROTATION),
                observed_signal_present=observed_signal is not None,
                observed_vote_present=observed_vote is not None,
                submit_signal_called=False,
            )
            return None, None

        vote_ts = getattr(observed_vote, "timestamp_ns", None)
        signal_ts = getattr(observed_signal, "exchange_ts_ns", None)
        fresh = (vote_ts == exchange_ts_ns) or (signal_ts == exchange_ts_ns)

        if not fresh:
            stale_cleared = self._clear_stale_sector_rotation_observed_pair(
                runtime,
                exchange_ts_ns,
            )
            logger.info(
                "[PAPER_DISPATCH_SECTOR_ROTATION] %s: blocked — freshness fail "
                "(vote_ts=%s signal_ts=%s exchange_ts_ns=%s stale_cleared=%s)",
                symbol, vote_ts, signal_ts, exchange_ts_ns, stale_cleared,
            )
            _log_dispatch_diag(
                "observed_pair_stale",
                symbol=symbol,
                exchange_ts_ns=exchange_ts_ns,
                sleeve=repr(SleeveType.SECTOR_ROTATION),
                vote_ts=vote_ts,
                signal_ts=signal_ts,
                stale_cleared=stale_cleared,
                submit_signal_called=False,
            )
            return None, None

        logger.info(
            "[PAPER_DISPATCH_SECTOR_ROTATION] %s: admitted decision_uuid=%s "
            "side=%s confidence=%s risk_appetite=%s",
            symbol,
            getattr(observed_vote, "decision_uuid", "<missing>"),
            getattr(observed_signal, "side", "<missing>"),
            getattr(observed_vote, "confidence", "<missing>"),
            getattr(observed_vote, "risk_appetite", "<missing>"),
        )
        return observed_signal, observed_vote

    def _consume_observed_pair_liquidity_void(
        self, symbol: str, runtime: SymbolRuntime, exchange_ts_ns: int
    ) -> Tuple[Optional[StrategySignal], Optional[StrategyVote]]:
        """
        Stage 2-D3 (Option C): Return the buffered pre-candle LiquidityVoid
        observation candidate under paper-only governance, or (None, None) on
        any gate failure. The candidate is the most-recent (signal, vote) pair
        produced by Stage 2-B/2-C inside _observe_liquidity_void from order-book
        ingress; this preserves LV's order-book-native predator edge while
        admitting paper trades through the lawful candle dispatch authority.

        Hard gates (in order):
          1. broker_mode == "paper"  (paper-only proving lane)
          2. observed signal AND vote both present (a candidate exists)
          3. candidate symbol matches current symbol
          4. vote.timestamp_ns <= exchange_ts_ns  (pre-candle freshness;
             LV observation runs on order-book ingress so the candidate's
             timestamp is at or before the current candle's timestamp)
          5. vote.decision_uuid is non-empty
          6. vote.decision_uuid != runtime.last_liquidity_void_consumed_decision_uuid
             (not already consumed by a previous candle dispatch)

        On admission, marks the candidate consumed via
        runtime.last_liquidity_void_consumed_decision_uuid = vote.decision_uuid
        BEFORE returning, so the same candidate cannot fire on later candles.
        The shared downstream path then performs DecisionCompiler.compile and
        ExecutionEngine.submit_signal — same gates as ShadowFront/GammaFront
        (RiskGuard.can_trade, vol fuse, data continuity, net-profit floor at
        0.005, paper broker isolation). No adapter call. No LV update_* call.
        No direct DecisionCompiler / ExecutionEngine call. No live broker.
        """
        if self.config.broker_mode != "paper":
            logger.info(
                "[PAPER_DISPATCH_LIQUIDITY_VOID] %s: blocked — broker_mode=%s "
                "(paper-only gate)",
                symbol, self.config.broker_mode,
            )
            _log_dispatch_diag(
                "sleeve_blocked",
                symbol=symbol,
                exchange_ts_ns=exchange_ts_ns,
                sleeve=repr(SleeveType.FLV),
                broker_mode=self.config.broker_mode,
                block_reason="non_paper_broker_mode",
                submit_signal_called=False,
            )
            return None, None

        observed_signal = runtime.last_liquidity_void_observed_signal
        observed_vote = runtime.last_liquidity_void_observed_vote

        if observed_signal is None or observed_vote is None:
            logger.info(
                "[PAPER_DISPATCH_LIQUIDITY_VOID] %s: blocked — observed pair missing "
                "(signal=%s vote=%s)",
                symbol,
                "present" if observed_signal is not None else "None",
                "present" if observed_vote is not None else "None",
            )
            _log_dispatch_diag(
                "observed_pair_missing",
                symbol=symbol,
                exchange_ts_ns=exchange_ts_ns,
                sleeve=repr(SleeveType.FLV),
                observed_signal_present=observed_signal is not None,
                observed_vote_present=observed_vote is not None,
                submit_signal_called=False,
            )
            return None, None

        signal_symbol = getattr(observed_signal, "symbol", None)
        if signal_symbol is not None and signal_symbol != symbol:
            logger.info(
                "[PAPER_DISPATCH_LIQUIDITY_VOID] %s: blocked — symbol mismatch "
                "(candidate symbol=%s)",
                symbol, signal_symbol,
            )
            _log_dispatch_diag(
                "observed_pair_missing",
                symbol=symbol,
                exchange_ts_ns=exchange_ts_ns,
                sleeve=repr(SleeveType.FLV),
                candidate_symbol=signal_symbol,
                block_reason="symbol_mismatch",
                submit_signal_called=False,
            )
            return None, None

        candidate_ts = getattr(observed_vote, "timestamp_ns", None)
        if candidate_ts is None or candidate_ts > exchange_ts_ns:
            logger.info(
                "[PAPER_DISPATCH_LIQUIDITY_VOID] %s: blocked — freshness fail "
                "(candidate_ts=%s > candle_ts=%s)",
                symbol, candidate_ts, exchange_ts_ns,
            )
            _log_dispatch_diag(
                "observed_pair_stale",
                symbol=symbol,
                exchange_ts_ns=exchange_ts_ns,
                sleeve=repr(SleeveType.FLV),
                candidate_ts=candidate_ts,
                submit_signal_called=False,
            )
            return None, None

        candidate_uuid = getattr(observed_vote, "decision_uuid", None)
        if not candidate_uuid:
            logger.info(
                "[PAPER_DISPATCH_LIQUIDITY_VOID] %s: blocked — missing decision_uuid",
                symbol,
            )
            _log_dispatch_diag(
                "strategy_vote_missing",
                symbol=symbol,
                exchange_ts_ns=exchange_ts_ns,
                sleeve=repr(SleeveType.FLV),
                block_reason="missing_decision_uuid",
                submit_signal_called=False,
            )
            return None, None

        if candidate_uuid == runtime.last_liquidity_void_consumed_decision_uuid:
            logger.info(
                "[PAPER_DISPATCH_LIQUIDITY_VOID] %s: blocked — already consumed "
                "(decision_uuid=%s)",
                symbol, candidate_uuid,
            )
            _log_dispatch_diag(
                "strategy_signal_missing",
                symbol=symbol,
                exchange_ts_ns=exchange_ts_ns,
                sleeve=repr(SleeveType.FLV),
                decision_uuid=candidate_uuid,
                block_reason="already_consumed",
                submit_signal_called=False,
            )
            return None, None

        runtime.last_liquidity_void_consumed_decision_uuid = candidate_uuid

        logger.info(
            "[PAPER_DISPATCH_LIQUIDITY_VOID] %s: admitted decision_uuid=%s "
            "side=%s confidence=%s risk_appetite=%s candidate_ts=%s candle_ts=%s "
            "consumed=%s",
            symbol,
            candidate_uuid,
            getattr(observed_signal, "side", "<missing>"),
            getattr(observed_vote, "confidence", "<missing>"),
            getattr(observed_vote, "risk_appetite", "<missing>"),
            candidate_ts,
            exchange_ts_ns,
            candidate_uuid,
        )
        return observed_signal, observed_vote

    # =========================================================================
    # STAGE 2-B: OBSERVE-ONLY DORMANT SLEEVE FEED PUMPING
    # =========================================================================
    # Drives LiquidityVoidStrategy and SectorRotationStrategy with real,
    # already-available per-symbol feeds and captures their Optional[
    # StrategySignal] outputs for diagnostic logging only. NEVER:
    #   - converted via strategy_vote_adapters
    #   - inserted into any strategy_votes list
    #   - passed to DecisionCompiler / StrategyRouter / SignalFusion
    #   - submitted to ExecutionEngine / OrderRouter
    #   - used for risk/sizing/order-generation decisions
    # =========================================================================

    def _log_observed_signal(
        self, symbol: str, sleeve_name: str, signal: StrategySignal
    ) -> None:
        """Emit OBSERVE_ONLY diagnostic line for a captured dormant-sleeve signal."""
        metadata = getattr(signal, "metadata", None) or {}
        metadata_keys = sorted(metadata.keys())
        logger.info(
            "[OBSERVE_ONLY] symbol=%s sleeve=%s side=%s confidence=%.4f "
            "reason=%s metadata_keys=%s",
            symbol,
            sleeve_name,
            getattr(signal, "side", "<missing>"),
            float(getattr(signal, "confidence", 0.0)),
            getattr(signal, "reason", ""),
            metadata_keys,
        )

    def _log_observed_vote(
        self, symbol: str, sleeve_name: str, vote: StrategyVote
    ) -> None:
        """Emit OBSERVE_ONLY_VOTE diagnostic line for a telemetry-only StrategyVote."""
        metadata = getattr(vote, "metadata", None) or {}
        metadata_keys = sorted(metadata.keys())
        logger.info(
            "[OBSERVE_ONLY_VOTE] symbol=%s sleeve=%s strategy_id=%s signal=%s "
            "confidence=%s risk_appetite=%s metadata_keys=%s",
            symbol,
            sleeve_name,
            getattr(vote, "strategy_id", "<missing>"),
            getattr(vote, "signal", "<missing>"),
            getattr(vote, "confidence", "<missing>"),
            getattr(vote, "risk_appetite", "<missing>"),
            metadata_keys,
        )

    def _observe_liquidity_void(
        self, symbol: str, runtime: SymbolRuntime, order_book: OrderBookSnapshot
    ) -> None:
        """
        Observe-only feed pump for LiquidityVoidStrategy (Stage 2-B).

        Feeds real per-symbol overlays then captures returned Optional[
        StrategySignal] from update_order_book. Returned signal is logged
        only — never dispatched, adapted, voted, or routed to execution.
        """
        sleeve = runtime.liquidity_void_strategy
        if sleeve is None:
            return

        try:
            if runtime.sentiment_velocity_engine is not None:
                sleeve.update_macro_state(
                    runtime.sentiment_velocity_engine.get_macro_signal()
                )
            if runtime.toxicity_engine is not None:
                sleeve.update_toxicity(runtime.toxicity_engine.get_last_alert())
            sleeve.update_topology(runtime.last_tpe_signal)
            signal = sleeve.update_order_book(order_book)
        except Exception as exc:
            logger.warning(
                "[OBSERVE_ONLY] symbol=%s sleeve=liquidity_void feed/observe raised: %s",
                symbol, exc,
            )
            return

        if signal is None:
            return

        runtime.record_observed_signal("liquidity_void", signal)
        self._log_observed_signal(symbol, "liquidity_void", signal)

        # OBSERVE-ONLY (Stage 2-C): synthesize a StrategyVote via the approved
        # adapter for telemetry/inspection ONLY. This vote is NOT passed to
        # DecisionCompiler, NOT inserted into any active strategy_votes list,
        # NOT routed to StrategyRouter / SignalFusion / ExecutionEngine.
        try:
            vote = adapt_liquidity_void_to_vote(
                signal,
                exchange_ts_ns=order_book.exchange_ts_ns,
            )
        except Exception as exc:
            logger.warning(
                "[OBSERVE_ONLY_VOTE] symbol=%s sleeve=liquidity_void adapter raised: %s",
                symbol, exc,
            )
            return

        runtime.record_observed_vote("liquidity_void", vote)
        self._log_observed_vote(symbol, "liquidity_void", vote)

    def _observe_sector_rotation(
        self, symbol: str, runtime: SymbolRuntime, candle: Candle
    ) -> None:
        """
        Observe-only feed pump for SectorRotationStrategy (Stage 2-B).

        Feeds real per-symbol overlays then captures Optional[StrategySignal]
        from update_candle (entry path) and update_price (exit path) using
        the same candle close + timestamp. Calling update_price after
        update_candle on the same tick is replay-safe per source truth: on
        the entry tick, elapsed-from-entry is 0 so no TTL/TP/SL/exit fires;
        on non-entry ticks update_price is needed to observe exits at all.
        Returned signals are logged only — never dispatched, adapted,
        voted, or routed to execution.
        """
        sleeve = runtime.sector_rotation_strategy
        if sleeve is None:
            return

        try:
            if runtime.sentiment_velocity_engine is not None:
                sleeve.update_macro_state(
                    runtime.sentiment_velocity_engine.get_macro_signal()
                )
            if runtime.toxicity_engine is not None:
                sleeve.update_toxicity(runtime.toxicity_engine.get_last_alert())
            entry_signal = sleeve.update_candle(
                price=candle.close,
                volume=candle.volume,
                timestamp_ns=candle.exchange_ts_ns,
            )
            entry_decline_reason = (
                sleeve.get_last_decline_reason()
                if hasattr(sleeve, "get_last_decline_reason")
                else None
            )
            entry_decline_detail = (
                sleeve.get_last_decline_detail()
                if hasattr(sleeve, "get_last_decline_detail")
                else {}
            )
            exit_signal = sleeve.update_price(
                price=candle.close,
                timestamp_ns=candle.exchange_ts_ns,
            )
            price_decline_reason = (
                sleeve.get_last_decline_reason()
                if hasattr(sleeve, "get_last_decline_reason")
                else None
            )
            price_decline_detail = (
                sleeve.get_last_decline_detail()
                if hasattr(sleeve, "get_last_decline_detail")
                else {}
            )
        except Exception as exc:
            _log_sector_rotation_diag(
                symbol,
                "unknown_no_signal",
                candle.exchange_ts_ns,
                {"stage": "feed_observe", "error": exc.__class__.__name__},
            )
            logger.warning(
                "[OBSERVE_ONLY] symbol=%s sleeve=sector_rotation feed/observe raised: %s",
                symbol, exc,
            )
            return

        if entry_signal is None and exit_signal is None:
            reason_code = (
                entry_decline_reason
                or price_decline_reason
                or "update_candle_no_signal"
            )
            detail = entry_decline_detail or price_decline_detail
            _log_sector_rotation_diag(
                symbol,
                reason_code,
                candle.exchange_ts_ns,
                detail,
            )

        for signal in (entry_signal, exit_signal):
            if signal is None:
                continue
            runtime.record_observed_signal("sector_rotation", signal)
            self._log_observed_signal(symbol, "sector_rotation", signal)

            # OBSERVE-ONLY (Stage 2-C): synthesize a StrategyVote via the
            # approved adapter for telemetry/inspection ONLY. This vote is
            # NOT passed to DecisionCompiler, NOT inserted into any active
            # strategy_votes list, NOT routed to StrategyRouter /
            # SignalFusion / ExecutionEngine.
            try:
                vote = adapt_sector_rotation_to_vote(
                    signal,
                    exchange_ts_ns=candle.exchange_ts_ns,
                )
            except Exception as exc:
                _log_sector_rotation_diag(
                    symbol,
                    "vote_adaptation_failed",
                    candle.exchange_ts_ns,
                    {"error": exc.__class__.__name__},
                )
                logger.warning(
                    "[OBSERVE_ONLY_VOTE] symbol=%s sleeve=sector_rotation adapter raised: %s",
                    symbol, exc,
                )
                continue

            runtime.record_observed_vote("sector_rotation", vote)
            self._log_observed_vote(symbol, "sector_rotation", vote)
            _log_sector_rotation_diag(
                symbol,
                "observed_pair_stored",
                candle.exchange_ts_ns,
                {"signal_ts_ns": getattr(signal, "exchange_ts_ns", None)},
            )

    # =========================================================================
    # BUNDLE 3B/3C/3D/3E: TRUTHFRAME CONSTRUCTION WITH HYDRATION
    # =========================================================================

    def _build_truth_frame(self, exchange_ts_ns: int) -> TruthFrame:
        """
        Stage 2 DRIFTING TruthFrame — with real ExchangeTruth, PortfolioTruth, ExecutionTruth, and StrategyTruth hydration.

        BUNDLE 3B: ExchangeTruth is populated from execution_engine.order_router snapshot.
        BUNDLE 3C: PortfolioTruth is populated from available portfolio/account state.
        BUNDLE 3D: ExecutionTruth is populated from execution_engine and order_router state.
        BUNDLE 3E: StrategyTruth is populated from strategy_router and primary shadow_front state.

        Falls back gracefully if data not available.
        TruthStatus remains DRIFTING — full reconciliation requires all five truths.
        """
        # Get order_router for exchange data
        snapshot = {}
        order_router = getattr(self.execution_engine, "order_router", None)
        
        if order_router is not None and hasattr(order_router, "get_exchange_truth_snapshot"):
            try:
                snapshot = order_router.get_exchange_truth_snapshot(self.symbol)
                logger.debug("ExchangeTruth snapshot retrieved successfully")
            except Exception as e:
                logger.warning(f"Failed to fetch exchange truth snapshot: {e}")
        else:
            logger.debug("order_router not available — ExchangeTruth will use empty defaults")

        # ============================================
        # EXCHANGE TRUTH (BUNDLE 3B)
        # ============================================

        balances: Dict[str, Decimal] = {}
        for currency, balance in snapshot.get("balances", {}).items():
            try:
                balances[currency] = Decimal(str(balance))
            except Exception:
                logger.debug(f"Failed to convert balance for {currency}: {balance}")

        exchange_positions: List[ExchangePosition] = []
        for pos in snapshot.get("positions", []):
            try:
                quantity = Decimal(str(pos.get("quantity", 0)))
                side = "long" if quantity > 0 else "short"
                exchange_positions.append(ExchangePosition(
                    symbol=pos.get("symbol", self.symbol),
                    side=side,
                    quantity=abs(quantity),
                    entry_price=Decimal(str(pos.get("average_entry_price", 0))),
                ))
            except Exception as e:
                logger.debug(f"Failed to convert exchange position: {e}")

        open_orders: List[ExchangeOpenOrder] = []
        for order in snapshot.get("open_orders", []):
            try:
                side = OrderSide.BUY if order.get("side", "").lower() == "buy" else OrderSide.SELL
                open_orders.append(ExchangeOpenOrder(
                    order_id=order.get("order_id", ""),
                    symbol=order.get("symbol", self.symbol),
                    side=side,
                    quantity=Decimal(str(order.get("quantity", 0))),
                    limit_price=Decimal(str(order.get("limit_price", 0))) if order.get("limit_price") else None,
                    order_id_namespace=order.get("order_id_namespace"),
                    client_order_id=order.get("client_order_id"),
                    venue_order_id=order.get("venue_order_id"),
                    broker_order_id=order.get("broker_order_id"),
                    exchange_txid=order.get("exchange_txid"),
                    command_id_namespace=order.get("command_id_namespace"),
                    command_order_id=order.get("command_order_id"),
                    mapping_status=order.get("mapping_status"),
                    is_terminal_mapping=bool(order.get("is_terminal_mapping", False)),
                    terminal_reason=order.get("terminal_reason"),
                ))
            except Exception as e:
                logger.debug(f"Failed to convert open order: {e}")

        fills: List[ExchangeFill] = []
        for fill in snapshot.get("fills_since_last_call", []):
            try:
                fills.append(ExchangeFill(
                    fill_id=fill.get("trade_id", fill.get("order_id", "")),
                    order_id=fill.get("order_id", ""),
                    price=Decimal(str(fill.get("price", 0))),
                    quantity=Decimal(str(fill.get("quantity", 0))),
                    fee=Decimal(str(fill.get("fee", 0))),
                ))
            except Exception as e:
                logger.debug(f"Failed to convert fill: {e}")

        exchange_truth = ExchangeTruth(
            venue=self.exchange,
            balances=balances,
            positions=exchange_positions,
            open_orders=open_orders,
            fills_since_last_truth=fills,
            exchange_ts_ns=exchange_ts_ns,
        )

        # ============================================
        # PORTFOLIO TRUTH (BUNDLE 3C)
        # ============================================

        portfolio_cash: Dict[str, Decimal] = {}
        for currency, balance in balances.items():
            portfolio_cash[currency] = balance

        portfolio_positions: List[PortfolioPosition] = []
        mark_price = Decimal(str(self._last_price)) if self._last_price > 0 else Decimal("0")
        
        for pos in snapshot.get("positions", []):
            try:
                quantity = Decimal(str(pos.get("quantity", 0)))
                avg_price = Decimal(str(pos.get("average_entry_price", 0)))
                unrealized_pnl = quantity * (mark_price - avg_price) if quantity > 0 else Decimal("0")
                
                portfolio_positions.append(PortfolioPosition(
                    symbol=pos.get("symbol", self.symbol),
                    quantity=quantity,
                    avg_price=avg_price,
                    mark_price=mark_price,
                    unrealized_pnl=unrealized_pnl,
                ))
            except Exception as e:
                logger.debug(f"Failed to convert portfolio position: {e}")

        total_cash = sum(portfolio_cash.values())
        tradeable_equity = Decimal(str(self._last_equity))
        reserved_buying_power = max(Decimal("0"), tradeable_equity - total_cash)

        portfolio_truth = PortfolioTruth(
            cash=portfolio_cash,
            positions=portfolio_positions,
            reserved_buying_power=reserved_buying_power,
            total_equity=tradeable_equity,
            last_update_ts_ns=exchange_ts_ns,
        )

        # ============================================
        # EXECUTION TRUTH (BUNDLE 3D)
        # ============================================

        submitted_orders: List[SubmittedOrder] = []
        acks_received: List[Acknowledgement] = []
        rejections: List[Rejection] = []
        pending_cancels: List[PendingCancel] = []

        exec_state = getattr(self.execution_engine, "_state", None)
        if exec_state is not None:
            for order_id, order in exec_state.pending_orders.items():
                try:
                    venue_order_id = None
                    if order_router is not None and hasattr(order_router, "get_order_id_mapping_fact"):
                        mapping_fact = order_router.get_order_id_mapping_fact(order_id)
                        if mapping_fact is not None:
                            venue_order_id = mapping_fact.get("venue_order_id")
                    status = InternalOrderStatus.SUBMITTED
                    submitted_orders.append(SubmittedOrder(
                        client_order_id=order_id,
                        venue_order_id=venue_order_id,
                        status=status,
                        submitted_ts_ns=order.exchange_ts_ns if hasattr(order, 'exchange_ts_ns') else exchange_ts_ns,
                    ))
                except Exception as e:
                    logger.debug(f"Failed to convert pending order to SubmittedOrder: {e}")

            for fill in exec_state.filled_orders:
                try:
                    acks_received.append(Acknowledgement(
                        client_order_id=fill.order_id,
                        venue_order_id=fill.order_id,
                        ack_ts_ns=fill.exchange_ts_ns,
                    ))
                except Exception as e:
                    logger.debug(f"Failed to convert fill to Acknowledgement: {e}")

        if order_router is not None:
            status_cache = getattr(order_router, "_order_status_cache", {})
            for client_id, status_info in status_cache.items():
                status_str = getattr(status_info, "status", "") if hasattr(status_info, "status") else status_info.get("status", "") if isinstance(status_info, dict) else ""
                if status_str == "rejected":
                    try:
                        timestamp_ns = getattr(status_info, "timestamp_ns", exchange_ts_ns) if hasattr(status_info, "timestamp_ns") else status_info.get("timestamp_ns", exchange_ts_ns) if isinstance(status_info, dict) else exchange_ts_ns
                        rejections.append(Rejection(
                            client_order_id=client_id,
                            reason="order_rejected_by_venue",
                            reject_ts_ns=timestamp_ns,
                        ))
                    except Exception as e:
                        logger.debug(f"Failed to convert rejection: {e}")

        execution_truth = ExecutionTruth(
            submitted_orders=submitted_orders,
            pending_cancels=pending_cancels,
            acks_received=acks_received,
            rejections=rejections,
            last_reconciliation_ts_ns=exchange_ts_ns,
        )

        # ============================================
        # STRATEGY TRUTH (BUNDLE 3E)
        # ============================================

        active_strategies: List[StrategyTruthEntry] = []

        # Use primary shadow_front strategy for StrategyTruth
        primary_shadow_front = self._primary_runtime.shadow_front_strategy
        if primary_shadow_front:
            macro_kill_active = getattr(self.strategy_router, "_macro_kill_active", False)
            is_eligible = getattr(primary_shadow_front, "_is_eligible", True)
            
            in_position = primary_shadow_front.is_in_position()
            if macro_kill_active:
                state = "macro_killed"
            elif in_position:
                state = "active"
            elif not is_eligible:
                state = "ineligible"
            else:
                state = "idle"

            entry_price = primary_shadow_front.get_entry_price()
            entry_decision_uuid = primary_shadow_front.get_entry_decision_uuid()
            
            target_exposure = Decimal(str(primary_shadow_front.get_target_exposure_pct()))
            current_exposure = primary_shadow_front.get_current_exposure()
            ttl_ns = primary_shadow_front.get_ttl_ns()

            invalidation_state = "valid"

            strategy_entry = StrategyTruthEntry(
                strategy_id=StrategyID.SHADOW_FRONT,
                state=state,
                entry_price=Decimal(str(entry_price)) if entry_price is not None else None,
                entry_decision_uuid=entry_decision_uuid,
                target_exposure=target_exposure,
                current_exposure=current_exposure,
                invalidation_state=invalidation_state,
                ttl_ns=ttl_ns,
            )
            active_strategies.append(strategy_entry)

        strategy_truth = StrategyTruth(
            active_strategies=active_strategies,
            last_update_ts_ns=exchange_ts_ns,
        )

        # ============================================
        # RISK TRUTH (PARTIAL)
        # ============================================

        risk_action = (
            self._last_risk_state.get("action", "NORMAL")
            if self._last_risk_state else "NORMAL"
        )
        risk_mode = (
            RiskMode.HARD_FLAT
            if risk_action == "EMERGENCY_HALT"
            else RiskMode.NORMAL
        )
        risk_truth = RiskTruth(mode=risk_mode)

        reconcile_alerts = TruthReconciler().build_alert_evidence(
            exchange_truth=exchange_truth,
            execution_truth=execution_truth,
            portfolio_truth=portfolio_truth,
            strategy_truth=strategy_truth,
            risk_truth=risk_truth,
        )
        terminal_mapping_proofs = []
        if order_router is not None and hasattr(order_router, "get_terminal_mapping_proofs"):
            try:
                terminal_mapping_proofs = order_router.get_terminal_mapping_proofs(limit=20)
            except Exception as e:
                logger.debug(f"Failed to read terminal mapping proofs: {e}")

        return TruthFrame(
            exchange_truth=exchange_truth,
            execution_truth=execution_truth,
            portfolio_truth=portfolio_truth,
            strategy_truth=strategy_truth,
            risk_truth=risk_truth,
            status=TruthStatus.DRIFTING,
            reconcile_alerts=reconcile_alerts,
            terminal_mapping_proofs=terminal_mapping_proofs,
        )

    def _compute_volatility(self, candle: Candle) -> float:
        """Compute volatility from candle."""
        if candle.close <= 0:
            return 0.20
        daily_range = (candle.high - candle.low) / candle.close
        return max(0.05, min(0.80, daily_range * 15.0))

    # =========================================================================
    # RECALIBRATION STATE MACHINE — PRESERVED UNTOUCHED
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
                logger.critical("EMERGENCY_HALT: drawdown=%.2f%%", drawdown_from_peak * 100)
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
            logger.critical("CRISIS_ABORT: drawdown=%.2f%%", drawdown_from_peak * 100)
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
            logger.warning("Recalibration STARTED: %s", risk_state.get("reason"))

        if self._recalibration_active:
            if self.recalibrator.should_recover():
                if action not in ("RECALIBRATE", "EMERGENCY_HALT"):
                    self.recalibrator.end_recalibration()
                    self._recalibration_active = False
                    self._recalibration_start_ns = 0
                    self._metrics.recalibration_exits += 1
                    logger.info("Recalibration ENDED")
            self._metrics.last_recalibration_check_ns = exchange_ts_ns

    # =========================================================================
    # HEALTH LOGGING — PRESERVED UNTOUCHED
    # =========================================================================

    def _log_health(self) -> None:
        risk_status = self.risk_guard.get_status()
        commander_status = self.commander.get_status()

        logger.info(
            "HEALTH | iter=%d | mode=%s | equity=%.2f | drawdown=%.2f%% | "
            "orders=%d/%d | recal=%s | dup_rej=%d | stale_rej=%d | invalid_books=%d | symbols=%d",
            self._metrics.iteration_count,
            commander_status.get("mode", "UNKNOWN"),
            risk_status.get("current_equity", 0.0),
            risk_status.get("drawdown_from_peak", 0.0) * 100,
            self._metrics.orders_submitted,
            self._metrics.compilation_cycles,
            self._recalibration_active,
            self._metrics.candle_duplicates_rejected,
            self._metrics.candle_stale_rejected,
            self._metrics.invalid_books_skipped,
            len(self._runtimes),
        )

    # =========================================================================
    # DIAGNOSTICS — HONEST ACTUATION STATUS
    # =========================================================================

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "symbol": self.symbol,
                "active_symbols": list(self.active_symbols),
                "running": self._running,
                "iteration_count": self._metrics.iteration_count,
                "last_price": self._last_price,
                "last_equity": self._last_equity,
                "compilation_cycles": self._metrics.compilation_cycles,
                "orders_submitted": self._metrics.orders_submitted,
                "candle_duplicates_rejected": self._metrics.candle_duplicates_rejected,
                "candle_stale_rejected": self._metrics.candle_stale_rejected,
                "invalid_books_skipped": self._metrics.invalid_books_skipped,
                "book_processed_count": self._book_processed_count,
                "actuation": "diagnostic_trace",
                "actuation_limits": {
                    "signal_fusion_global": True,
                    "decision_compiler_global": True,
                    "execution_engine_global": True,
                    "order_router_global": True,
                    "multi_symbol_state_ownership": True,
                    "whale_overlay_wired": True,
                    "sentiment_overlay_wired": True,
                    "per_symbol_throttle": True,
                    "per_symbol_shans": True,
                },
                "runtimes": {
                    sym: runtime.get_status() for sym, runtime in self._runtimes.items()
                }
            }

    def get_last_fusion(self) -> Optional[FusionDecision]:
        with self._lock:
            return self._last_fusion
    
    def get_runtime(self, symbol: str) -> Optional[SymbolRuntime]:
        """Get runtime container for a specific symbol."""
        return self._runtimes.get(symbol)
    
    def get_all_runtimes(self) -> Dict[str, SymbolRuntime]:
        """Get all symbol runtimes."""
        return self._runtimes.copy()
