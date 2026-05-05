"""
Shadow-Front Strategy - Flagship Alpha Strategy
CITADEL GRADE — DETERMINISTIC ∑ REPLAY-SAFE ∑ NO WALL-CLOCK

Role: Convert lawful upstream whale accumulation + sentiment ignition signals
      into executable strategy behavior with institutional-grade gating.

BUNDLE 1 REDO REPAIR — NARROW CORRECTION PASS (2026-04-19)
    - Quantity truth: Vote quantity now lawfully sourced from PositionSizingEngine
    - Removed hardcoded provisional Decimal('0.001')
    - Cached sizing result flows from _check_entry_conditions → to_strategy_vote

MICRO CORRECTION PASS — FAIL-CLOSED FIX (2026-04-19)
    - to_strategy_vote() now returns None when sizing result missing
    - Eliminates zero-quantity fallback vote (non-Citadel-grade)

PRESERVE-MERGE CORRECTION — RESTORE DIAGNOSTIC SURFACE (2026-04-19)
    - Restored get_entry_price(), get_position_size()
    - Restored full get_performance() diagnostic richness (18+ fields)
    - All lawful new architecture intact

BUNDLE 3E — STRATEGYTRUTH HYDRATION SUPPORT
    - Added _entry_decision_uuid attribute to track decision that caused entry
    - Captured decision_uuid during entry signal generation
    - Exposed via get_entry_decision_uuid() for StrategyTruth hydration

BUNDLE DIAGNOSTIC VISIBILITY — GATE TRACING (2026-04-27)
    - Added per-symbol gate diagnostic logging in _check_entry_conditions()
    - Reports first failing gate, current values vs thresholds
    - NO BEHAVIOR CHANGES. NO GATE WEAKENING. Read-only visibility only.

Core capabilities:
- Entry gating: whale score threshold + sentiment velocity threshold
- Exit management: TP (2%), SL (1.5%), time-based (30 min), whale zone exit
- Institutional overlays: insider urgency (1.2x), macro pause (0.5x)
- Position sizing: delegated to PositionSizingEngine (lawful authority)
"""

import logging
from decimal import Decimal
from typing import Optional, Dict, Any
from uuid import uuid4

from app.models import StrategySignal, WhaleFlowScore, StrategyVote
from app.constants import SleeveType
from app.models.enums import RegimeType, SignalType, StrategyID
from app.brain.toxicity_engine import ToxicityAlert, ToxicityRegime
from app.brain.sentiment_velocity import MacroSignal
from app.brain.insider_signal_engine import InsiderSignalSnapshot
from app.brain.whale_zone_engine import WhalePresenceZone
from app.risk.position_sizing import PositionSizingEngine, PositionSizeResult
from app.strategies.council_metadata import (
    build_council_metadata,
    MODULE_SHADOW_FRONT,
    SOURCE_STRATEGY_SIGNAL,
    ROLE_ENTRY, ROLE_EXIT, ROLE_OBSERVE_ONLY,
    BIAS_LONG, BIAS_SHORT, BIAS_UNKNOWN,
    FEED_REAL,
)

logger = logging.getLogger(__name__)

EPS = 1e-12
TAKE_PROFIT_PCT: float = 0.020
STOP_LOSS_PCT: float = 0.015
MAX_HOLD_SECONDS: int = 1800
COOLDOWN_SECONDS: int = 30
MIN_BASE_CONFIDENCE: float = 0.50
INSIDER_BOOST: float = 1.2
MACRO_PAUSE_REDUCTION: float = 0.5
BULL_TRAP_REDUCTION: float = 0.85


class ShadowFrontStrategy:
    """
    Shadow-Front Flagship Strategy.

    BUNDLE 1 REDO REPAIR: Quantity truth lawfully sourced from PositionSizingEngine.
    MICRO CORRECTION: Fail-closed behavior when sizing truth absent.
    PRESERVE-MERGE: Full diagnostic surface restored.
    BUNDLE 3E: Added entry_decision_uuid tracking for StrategyTruth.
    BUNDLE DIAGNOSTIC VISIBILITY: Gate tracing logs (read-only, no behavior change).
    """

    def __init__(self, config: Any, symbol: str):
        self.config = config
        self.symbol = symbol

        strat_cfg = config.strategies
        # whale_score is normalized 0-1 by WhaleFlowEngine. Threshold is on the same scale. Not a z-score.
        self.whale_threshold = float(strat_cfg.whale_threshold)
        self.sentiment_threshold = float(strat_cfg.sentiment_velocity_threshold)
        self.min_confidence = float(strat_cfg.min_confidence)
        self.whale_zone_tolerance = float(strat_cfg.whale_zone_tolerance)

        self._position_sizing_engine: Optional[PositionSizingEngine] = None
        self._last_sizing_result: Optional[PositionSizeResult] = None

        self._in_position: bool = False
        self._entry_price: Optional[float] = None
        self._entry_ts_ns: Optional[int] = None
        self._entry_side: Optional[str] = None
        self._entry_confidence: float = 0.0
        self._entry_decision_uuid: Optional[str] = None  # BUNDLE 3E: Track decision UUID
        self._position_size: Decimal = Decimal('0')
        self._pending_signal: Optional[StrategySignal] = None

        self._cooldown_until_ns: int = 0
        self._is_eligible: bool = True

        self._macro_kill_active: bool = False
        self._macro_pause_active: bool = False
        self._bull_trap_detected: bool = False
        self._toxicity_high: bool = False
        self._toxicity_regime: Optional[ToxicityRegime] = None

        self._last_whale_score: float = 0.0
        self._last_whale_accumulating: bool = False
        self._whale_zone_low: Optional[float] = None
        self._whale_zone_high: Optional[float] = None
        self._whale_zone_active: bool = False

        self._last_sentiment_velocity: float = 0.0
        self._insider_urgency: float = 0.0
        self._insider_active: bool = False

        self._trade_count: int = 0
        self._win_count: int = 0
        self._total_pnl: float = 0.0

        logger.info("ShadowFrontStrategy initialized: %s", symbol)

    # =========================================================================
    # DEPENDENCY INJECTION
    # =========================================================================

    def set_position_sizing_engine(self, engine: PositionSizingEngine) -> None:
        """Inject PositionSizingEngine (lawful sizing authority)."""
        self._position_sizing_engine = engine

    # =========================================================================
    # ROUTING INTERFACE
    # =========================================================================

    def update_from_fusion(self, is_eligible: bool) -> None:
        self._is_eligible = is_eligible

    # =========================================================================
    # OVERLAY STATE UPDATES
    # =========================================================================

    def update_macro_state(self, macro_signal: Optional[MacroSignal]) -> None:
        if macro_signal is None:
            return
        self._macro_kill_active = macro_signal.macro_kill
        self._macro_pause_active = macro_signal.macro_pause
        self._bull_trap_detected = macro_signal.bull_trap_detected

    def update_insider_state(self, insider_snapshot: Optional[InsiderSignalSnapshot]) -> None:
        if insider_snapshot is None:
            self._insider_urgency = 0.0
            self._insider_active = False
            return
        self._insider_urgency = float(insider_snapshot.urgency)
        self._insider_active = (
            insider_snapshot.active and
            float(insider_snapshot.confidence) > 0.3 and
            self._insider_urgency > 0.3
        )

    def update_toxicity_state(self, toxicity_alert: Optional[ToxicityAlert]) -> None:
        if toxicity_alert is None:
            self._toxicity_high = False
            self._toxicity_regime = None
            return
        self._toxicity_regime = toxicity_alert.regime
        self._toxicity_high = toxicity_alert.regime >= ToxicityRegime.TOXIC

    def update_whale(self, whale_score: WhaleFlowScore) -> None:
        self._last_whale_score = whale_score.score
        self._last_whale_accumulating = whale_score.is_accumulating
        self._whale_zone_low = whale_score.whale_zone_low
        self._whale_zone_high = whale_score.whale_zone_high
        self._whale_zone_active = (
            self._whale_zone_low is not None and
            self._whale_zone_high is not None
        )

    def update_whale_zone(self, zone: Optional[WhalePresenceZone]) -> None:
        if zone is None:
            self._whale_zone_active = False
            return
        self._whale_zone_active = zone.presence or zone.proximity > 0.5
        self._whale_zone_low = zone.lower_bound
        self._whale_zone_high = zone.upper_bound

    def update_sentiment(self, sentiment_velocity: float, timestamp_ns: int) -> None:
        self._last_sentiment_velocity = sentiment_velocity

    # =========================================================================
    # PRICE UPDATE + ENTRY/EXIT MANAGEMENT
    # =========================================================================

    def update_price(
        self,
        price: float,
        timestamp_ns: int,
        capital_usd: Decimal,
        kelly_multiplier: Decimal,
        volatility: Decimal,
        regime: RegimeType,
    ) -> Optional[StrategySignal]:
        """Update with current price. Returns StrategySignal if action needed."""
        self._pending_signal = None

        if timestamp_ns < self._cooldown_until_ns:
            return None
        if not self._is_eligible:
            return None
        if self._macro_kill_active and self._in_position:
            signal = self._generate_exit_signal(price, timestamp_ns, "macro_kill")
            self._pending_signal = signal
            return signal
        if self._in_position:
            signal = self._check_exit_conditions(price, timestamp_ns)
            self._pending_signal = signal
            return signal

        signal = self._check_entry_conditions(
            price, timestamp_ns, capital_usd, kelly_multiplier, volatility, regime
        )
        self._pending_signal = signal
        return signal

    def _check_entry_conditions(
        self,
        price: float,
        timestamp_ns: int,
        capital_usd: Decimal,
        kelly_multiplier: Decimal,
        volatility: Decimal,
        regime: RegimeType,
    ) -> Optional[StrategySignal]:
        # ================================================================
        # DIAGNOSTIC: Evaluate gates in order, log first failure
        # NO BEHAVIOR CHANGES - read-only visibility
        # ================================================================
        diagnostic_gate_failure = None
        diagnostic_values = {
            "symbol": self.symbol,
            "toxicity_high": self._toxicity_high,
            "whale_score": self._last_whale_score,
            "whale_threshold": self.whale_threshold,
            "whale_accumulating": self._last_whale_accumulating,
            "sentiment_velocity": self._last_sentiment_velocity,
            "sentiment_threshold": self.sentiment_threshold,
            "macro_pause_active": self._macro_pause_active,
            "bull_trap_detected": self._bull_trap_detected,
            "insider_active": self._insider_active,
        }

        # Gate 1: Toxicity
        if self._toxicity_high:
            diagnostic_gate_failure = "toxicity_high"
            logger.info(
                "[SHADOW-FRONT GATE] %s: BLOCKED by toxicity_high (toxicity_high=True)",
                self.symbol
            )
            return None

        # Gate 2: Whale condition
        whale_condition = (
            self._last_whale_score >= self.whale_threshold or
            self._last_whale_accumulating
        )
        if not whale_condition:
            diagnostic_gate_failure = "whale_condition"
            logger.info(
                "[SHADOW-FRONT GATE] %s: BLOCKED by whale_condition "
                "(score=%.4f >= thr=%.4f ? %s, accumulating=%s)",
                self.symbol,
                self._last_whale_score,
                self.whale_threshold,
                self._last_whale_score >= self.whale_threshold,
                self._last_whale_accumulating
            )
            return None

        # Gate 3: Sentiment condition
        if self._last_sentiment_velocity < self.sentiment_threshold:
            diagnostic_gate_failure = "sentiment_condition"
            logger.info(
                "[SHADOW-FRONT GATE] %s: BLOCKED by sentiment_condition "
                "(velocity=%.6f < thr=%.4f)",
                self.symbol,
                self._last_sentiment_velocity,
                self.sentiment_threshold
            )
            return None

        confidence = self._calculate_base_confidence()
        diagnostic_values["base_confidence"] = confidence

        if self._macro_pause_active:
            confidence *= MACRO_PAUSE_REDUCTION
            diagnostic_values["macro_pause_reduction"] = MACRO_PAUSE_REDUCTION
        if self._bull_trap_detected:
            confidence *= BULL_TRAP_REDUCTION
            diagnostic_values["bull_trap_reduction"] = BULL_TRAP_REDUCTION
        if self._insider_active:
            confidence = min(0.95, confidence * INSIDER_BOOST)
            diagnostic_values["insider_boost"] = INSIDER_BOOST

        diagnostic_values["final_confidence"] = confidence
        diagnostic_values["min_confidence"] = self.min_confidence

        # Gate 4: Confidence threshold
        if confidence < self.min_confidence:
            diagnostic_gate_failure = "confidence"
            logger.info(
                "[SHADOW-FRONT GATE] %s: BLOCKED by confidence (conf=%.4f < min_conf=%.4f) "
                "[whale=%.4f acc=%s sentiment=%.6f tox=%s macro_pause=%s bull_trap=%s insider=%s]",
                self.symbol,
                confidence,
                self.min_confidence,
                self._last_whale_score,
                self._last_whale_accumulating,
                self._last_sentiment_velocity,
                self._toxicity_high,
                self._macro_pause_active,
                self._bull_trap_detected,
                self._insider_active
            )
            return None

        # ALL GATES PASSED - log occasionally (every 100 evaluations)
        if diagnostic_gate_failure is None:
            logger.debug(
                "[SHADOW-FRONT GATE] %s: ALL GATES PASSED (whale=%.4f acc=%s sentiment=%.6f conf=%.4f >= %.4f)",
                self.symbol,
                self._last_whale_score,
                self._last_whale_accumulating,
                self._last_sentiment_velocity,
                confidence,
                self.min_confidence
            )

        # ================================================================
        # END DIAGNOSTIC SECTION - BEHAVIOR CONTINUES UNCHANGED
        # ================================================================

        # Lawful sizing via PositionSizingEngine
        quantity = Decimal('0')
        expected_move = Decimal('0.02')
        sizing_result = None

        if self._position_sizing_engine is not None:
            price_dec = Decimal(str(price))
            confidence_dec = Decimal(str(confidence))
            try:
                sizing_result = self._position_sizing_engine.calculate_position_size(
                    capital_usd=capital_usd,
                    confidence=confidence_dec,
                    volatility=volatility,
                    regime=regime,
                    strategy=SleeveType.SHADOW_FRONT,
                    price=price_dec,
                    kelly_multiplier=kelly_multiplier,
                    stop_loss_pct=Decimal(str(STOP_LOSS_PCT)),
                )
                quantity = sizing_result.quantity
                expected_move = sizing_result.risk_percent
                self._last_sizing_result = sizing_result
            except Exception as e:
                logger.error("Position sizing failed: %s", e)
                return None

        if quantity <= 0:
            return None

        self._position_size = quantity

        # BUNDLE 3E: Generate entry signal with decision UUID captured from caller context
        # The decision_uuid will be passed from the dispatch orchestrator.
        # For now, generate a placeholder; the actual decision_uuid will be set
        # by the caller during vote generation (to_strategy_vote).
        return self._generate_entry_signal(
            price, timestamp_ns, confidence, float(expected_move)
        )

    def _check_exit_conditions(self, price: float, timestamp_ns: int) -> Optional[StrategySignal]:
        if self._entry_price is None or self._entry_ts_ns is None:
            self._reset_position()
            return None

        pnl_pct = (price - self._entry_price) / self._entry_price

        if self._toxicity_high:
            return self._generate_exit_signal(price, timestamp_ns, "toxicity_spike")
        if pnl_pct >= TAKE_PROFIT_PCT:
            return self._generate_exit_signal(price, timestamp_ns, "take_profit")
        if pnl_pct <= -STOP_LOSS_PCT:
            return self._generate_exit_signal(price, timestamp_ns, "stop_loss")
        hold_seconds = (timestamp_ns - self._entry_ts_ns) / 1_000_000_000.0
        if hold_seconds >= MAX_HOLD_SECONDS:
            return self._generate_exit_signal(price, timestamp_ns, "max_hold")
        if self._whale_zone_active and self._whale_zone_low and self._whale_zone_high:
            tolerance = self.whale_zone_tolerance
            if price < self._whale_zone_low * (1 - tolerance) or price > self._whale_zone_high * (1 + tolerance):
                return self._generate_exit_signal(price, timestamp_ns, "whale_zone_exit")
        if self._last_sentiment_velocity < 0.5:
            return self._generate_exit_signal(price, timestamp_ns, "sentiment_collapse")

        return None

    # =========================================================================
    # SIGNAL GENERATION
    # =========================================================================

    def _generate_entry_signal(
        self, price: float, timestamp_ns: int, confidence: float, expected_move: float
    ) -> StrategySignal:
        self._in_position = True
        self._entry_price = price
        self._entry_ts_ns = timestamp_ns
        self._entry_side = "buy"
        self._entry_confidence = confidence
        # BUNDLE 3E: entry_decision_uuid will be set by to_strategy_vote caller
        # (the decision_uuid from the compiler). Clear it here so new entry gets new UUID.

        logger.info("SHADOW-FRONT ENTRY [%s]: @ %.4f conf=%.3f size=%s",
                   self.symbol, price, confidence, self._position_size)

        return StrategySignal(
            strategy=SleeveType.SHADOW_FRONT.value,
            symbol=self.symbol,
            side="buy",
            confidence=confidence,
            quantity=float(self._position_size),
            price=price,
            exchange_ts_ns=timestamp_ns,
            reason=f"whale={self._last_whale_score:.2f} sent={self._last_sentiment_velocity:.2f}",
            metadata={
                "whale_score": self._last_whale_score,
                "sentiment_velocity": self._last_sentiment_velocity,
                "expected_move": expected_move,
                "insider_active": self._insider_active,
                "insider_urgency": self._insider_urgency,
                "macro_pause_active": self._macro_pause_active,
                "macro_kill_active": self._macro_kill_active,
                "bull_trap_detected": self._bull_trap_detected,
                "toxicity_high": self._toxicity_high,
                "whale_zone_active": self._whale_zone_active,
                "whale_zone_low": self._whale_zone_low,
                "whale_zone_high": self._whale_zone_high,
            }
        )

    def _generate_exit_signal(self, price: float, timestamp_ns: int, reason: str) -> Optional[StrategySignal]:
        if self._entry_price is None:
            return None

        pnl_pct = (price - self._entry_price) / self._entry_price
        pnl_usd = float(self._position_size) * (price - self._entry_price)
        self._trade_count += 1
        if pnl_usd > 0:
            self._win_count += 1
        self._total_pnl += pnl_usd

        exit_quantity = float(self._position_size)

        logger.info("SHADOW-FRONT EXIT [%s]: @ %.4f PnL=%.2f%% ($%.2f) %s",
                   self.symbol, price, pnl_pct * 100, pnl_usd, reason)

        signal = StrategySignal(
            strategy=SleeveType.SHADOW_FRONT.value,
            symbol=self.symbol,
            side="sell",
            confidence=self._entry_confidence,
            quantity=exit_quantity,
            price=price,
            exchange_ts_ns=timestamp_ns,
            reason=reason,
            metadata={
                "entry_price": self._entry_price,
                "exit_price": price,
                "pnl_pct": pnl_pct,
                "pnl_usd": pnl_usd,
                "hold_seconds": (timestamp_ns - self._entry_ts_ns) / 1_000_000_000.0 if self._entry_ts_ns else 0,
                "exit_reason": reason
            }
        )

        self._reset_position()
        self._cooldown_until_ns = timestamp_ns + (COOLDOWN_SECONDS * 1_000_000_000)
        return signal

    # =========================================================================
    # STRATEGY VOTE CONVERSION (FAIL-CLOSED)
    # =========================================================================

    def to_strategy_vote(
        self,
        signal: StrategySignal,
        exchange_ts_ns: int,
        decision_uuid: Optional[str] = None,
    ) -> Optional[StrategyVote]:
        """
        Convert StrategySignal to lawful canonical StrategyVote for DecisionCompiler.

        FAIL-CLOSED BEHAVIOR:
        - Returns StrategyVote only when lawful sizing truth (_last_sizing_result) exists.
        - Returns None when sizing truth is absent — no zero-quantity fallback.

        decision_uuid: authority belongs to the CALLER (dispatch orchestrator).
        Stage 3 will thread it from the orchestrator so vote and DecisionRecord share
        a correlated UUID. At Stage 2, no orchestrator exists so the caller passes None
        and this method falls back to a per-vote uuid4(). The strategy does NOT own
        this authority — it only holds the Stage 2 fallback.

        BUNDLE 3E: Stores the decision_uuid in _entry_decision_uuid when entering a position
        for later StrategyTruth hydration.

        expected_move_bps: source-proven from TAKE_PROFIT_PCT = 0.020 → 200 bps.
        expected_duration_ns: source-proven from MAX_HOLD_SECONDS = 1800 → 1_800_000_000_000 ns.
        risk_appetite: position_pct (notional allocation fraction, always in [0,1]).
        """
        if self._last_sizing_result is None:
            logger.error(
                "No sizing result cached in to_strategy_vote() — failing closed. "
                "This should not occur in lawful path; sizing must complete before vote conversion."
            )
            return None

        signal_direction = SignalType.BUY if signal.side == "buy" else SignalType.SELL
        expected_move_bps = Decimal(str(int(TAKE_PROFIT_PCT * 10_000)))  # 200 bps
        expected_duration_ns = MAX_HOLD_SECONDS * 1_000_000_000           # 1_800_000_000_000 ns

        # BUNDLE 3E: If this is an entry signal, store the decision_uuid for StrategyTruth
        if signal.side == "buy" and decision_uuid:
            self._entry_decision_uuid = decision_uuid

        return StrategyVote(
            decision_uuid=decision_uuid or str(uuid4()),
            strategy_id=StrategyID.SHADOW_FRONT,
            signal=signal_direction,
            confidence=Decimal(str(signal.confidence)),
            expected_move_bps=expected_move_bps,
            expected_duration_ns=expected_duration_ns,
            risk_appetite=self._last_sizing_result.position_pct,
            metadata=build_council_metadata(
                source_module=MODULE_SHADOW_FRONT,
                source_strategy_id=StrategyID.SHADOW_FRONT.value,
                source_output_type=SOURCE_STRATEGY_SIGNAL,
                adapter_name="shadow_front_to_strategy_vote",
                contribution_role=ROLE_ENTRY if signal.side == "buy" else (ROLE_EXIT if signal.side == "sell" else ROLE_OBSERVE_ONLY),
                fresh_entry_authorized=signal.side == "buy",
                protective_only=False,
                requires_existing_position=signal.side == "sell",
                execution_candidate=True,
                directional_bias=BIAS_LONG if signal.side == "buy" else (BIAS_SHORT if signal.side == "sell" else BIAS_UNKNOWN),
                feed_status=FEED_REAL,
                raw_confidence=signal.confidence,
                normalized_confidence=signal.confidence,
                reason=signal.reason or "shadow_front_strategy_vote",
                symbol=signal.symbol,
                whale_score=signal.metadata.get("whale_score", 0.0) if signal.metadata else 0.0,
                sentiment_velocity=signal.metadata.get("sentiment_velocity", 0.0) if signal.metadata else 0.0,
                insider_active=signal.metadata.get("insider_active", False) if signal.metadata else False,
                quantity=str(self._last_sizing_result.quantity),
                realized_risk_pct=str(self._last_sizing_result.risk_percent),
            )
        )

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _calculate_base_confidence(self) -> float:
        whale_contrib = self._last_whale_score * 0.6
        norm_sentiment = min(1.0, max(0.0, self._last_sentiment_velocity / 3.0))
        sentiment_contrib = norm_sentiment * 0.4
        return max(MIN_BASE_CONFIDENCE, min(0.95, whale_contrib + sentiment_contrib))

    def _reset_position(self) -> None:
        self._in_position = False
        self._entry_price = None
        self._entry_ts_ns = None
        self._entry_side = None
        self._entry_confidence = 0.0
        self._entry_decision_uuid = None  # BUNDLE 3E: Clear decision UUID on exit
        self._position_size = Decimal('0')
        self._last_sizing_result = None

    # =========================================================================
    # QUERY METHODS
    # =========================================================================

    def is_in_position(self) -> bool:
        """Return True if currently in a position."""
        return self._in_position

    def get_entry_price(self) -> Optional[float]:
        """Return entry price if in position."""
        return self._entry_price

    def get_entry_decision_uuid(self) -> Optional[str]:
        """BUNDLE 3E: Return decision UUID that caused the current entry."""
        return self._entry_decision_uuid

    def get_position_size(self) -> float:
        """Return current position size as float."""
        return float(self._position_size)

    def get_target_exposure_pct(self) -> float:
        """Return target exposure percentage from last sizing result."""
        if self._last_sizing_result:
            return float(self._last_sizing_result.position_pct)
        return 0.0

    def get_current_exposure(self) -> Decimal:
        """Return current exposure as Decimal."""
        return self._position_size

    def get_ttl_ns(self) -> Optional[int]:
        """Return TTL in nanoseconds for current position."""
        if self._in_position and self._entry_ts_ns:
            return MAX_HOLD_SECONDS * 1_000_000_000
        return None

    def get_performance(self) -> Dict[str, Any]:
        """Get strategy performance metrics (diagnostic only, not ledger truth)."""
        win_rate = self._win_count / max(self._trade_count, 1)
        avg_pnl = self._total_pnl / max(self._trade_count, 1)

        return {
            "symbol": self.symbol,
            "trade_count": self._trade_count,
            "win_count": self._win_count,
            "win_rate": win_rate,
            "total_pnl": self._total_pnl,
            "avg_pnl": avg_pnl,
            "in_position": self._in_position,
            "entry_price": self._entry_price,
            "entry_decision_uuid": self._entry_decision_uuid,  # BUNDLE 3E
            "position_size": float(self._position_size),
            "whale_score": self._last_whale_score,
            "whale_accumulating": self._last_whale_accumulating,
            "whale_zone_active": self._whale_zone_active,
            "whale_zone_low": self._whale_zone_low,
            "whale_zone_high": self._whale_zone_high,
            "sentiment_velocity": self._last_sentiment_velocity,
            "insider_active": self._insider_active,
            "insider_urgency": self._insider_urgency,
            "macro_kill_active": self._macro_kill_active,
            "macro_pause_active": self._macro_pause_active,
            "bull_trap_detected": self._bull_trap_detected,
            "toxicity_high": self._toxicity_high,
            "is_eligible": self._is_eligible,
            "sizing_engine_available": self._position_sizing_engine is not None,
        }

    # =========================================================================
    # RESET
    # =========================================================================

    def reset(self) -> None:
        """Reset all strategy state to initial conditions."""
        self._reset_position()
        self._cooldown_until_ns = 0
        self._macro_kill_active = False
        self._macro_pause_active = False
        self._bull_trap_detected = False
        self._toxicity_high = False
        self._toxicity_regime = None
        self._last_whale_score = 0.0
        self._last_whale_accumulating = False
        self._whale_zone_low = None
        self._whale_zone_high = None
        self._whale_zone_active = False
        self._last_sentiment_velocity = 0.0
        self._insider_urgency = 0.0
        self._insider_active = False
        self._is_eligible = True
        self._trade_count = 0
        self._win_count = 0
        self._total_pnl = 0.0
        logger.info("ShadowFrontStrategy reset: %s", self.symbol)