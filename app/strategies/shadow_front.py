"""
Shadow-Front Strategy - Flagship Alpha Strategy
CITADEL GRADE — DETERMINISTIC · REPLAY-SAFE · NO WALL-CLOCK

Role: Convert lawful upstream whale accumulation + sentiment ignition signals
      into executable strategy behavior with institutional-grade gating.

Core capabilities:
- Entry gating: whale score threshold + sentiment velocity threshold
- Exit management: TP (2%), SL (1.5%), time-based (30 min), whale zone exit
- Institutional overlays: insider urgency (1.2x), macro pause (0.5x)
- Macro kill suppression: full block when macro_kill active
- Bull trap detection: reduced confidence on divergence
- Toxicity block: entry blocked, position exit when regime >= TOXIC
- Position sizing: risk-based formula (capital parameterized)
- Performance tracking: trade count, win count, PnL
- Cooldown and reset: full state clearance

All imports from proven live contracts only.
No dead imports. No guessed semantics. No fake state machine integration.
"""

import logging
from typing import Optional, Dict, Any

from app.models import StrategySignal, WhaleFlowScore
from app.constants import SleeveType
from app.models.enums import RegimeType
from app.brain.toxicity_engine import ToxicityAlert, ToxicityRegime
from app.brain.sentiment_velocity import MacroSignal
from app.brain.insider_signal_engine import InsiderSignalSnapshot
from app.brain.whale_zone_engine import WhalePresenceZone

logger = logging.getLogger(__name__)

# Machine epsilon
EPS = 1e-12

# Position management thresholds
TAKE_PROFIT_PCT: float = 0.020   # 2.0%
STOP_LOSS_PCT: float = 0.015     # 1.5%
MAX_HOLD_SECONDS: int = 1800     # 30 minutes
COOLDOWN_SECONDS: int = 30       # Post-exit cooldown

# Entry thresholds (from config at runtime)
# MIN_WHALE_SCORE and MIN_SENTIMENT_VELOCITY removed — values come from config

# Base confidence clamp
MIN_BASE_CONFIDENCE: float = 0.50

# Institutional multipliers
INSIDER_BOOST: float = 1.2
MACRO_PAUSE_REDUCTION: float = 0.5
BULL_TRAP_REDUCTION: float = 0.85


class ShadowFrontStrategy:
    """
    Shadow-Front Flagship Strategy.

    Converts upstream signals into executable strategy behavior:
    - Whale accumulation + sentiment ignition → entry
    - TP/SL/Time/Zone → exit
    - Macro/toxicity/insider → confidence modulation

    State is managed locally (self-contained).
    All timing uses exchange_ts_ns exclusively (replay-safe).
    Long-only by repo truth (old file hardcoded side="buy").
    """

    def __init__(self, config: Any, symbol: str):
        """
        Initialize Shadow-Front strategy.

        Args:
            config: Configuration object (access to strategy parameters)
            symbol: Trading symbol this instance tracks
        """
        self.config = config
        self.symbol = symbol

        # Strategy parameters from config
        strat_cfg = config.strategies
        self.whale_threshold_z = float(strat_cfg.whale_threshold_z)
        self.sentiment_threshold = float(strat_cfg.sentiment_velocity_threshold)
        self.min_confidence = float(strat_cfg.min_confidence)
        self.whale_zone_tolerance = float(strat_cfg.whale_zone_tolerance)

        # Position state (local, no external dependency)
        self._in_position: bool = False
        self._entry_price: Optional[float] = None
        self._entry_ts_ns: Optional[int] = None
        self._entry_side: Optional[str] = None
        self._position_size: float = 0.0
        self._entry_confidence: float = 0.0

        # Cooldown (exchange-time nanoseconds)
        self._cooldown_until_ns: int = 0

        # Overlay state
        self._macro_kill_active: bool = False
        self._macro_pause_active: bool = False
        self._bull_trap_detected: bool = False
        self._toxicity_high: bool = False
        self._toxicity_regime: Optional[ToxicityRegime] = None

        # Whale and zone state
        self._last_whale_score: float = 0.0
        self._last_whale_accumulating: bool = False
        self._whale_zone_low: Optional[float] = None
        self._whale_zone_high: Optional[float] = None
        self._whale_zone_active: bool = False

        # Sentiment state
        self._last_sentiment_velocity: float = 0.0

        # Insider state
        self._insider_urgency: float = 0.0
        self._insider_active: bool = False

        # Performance tracking (diagnostic only, not ledger truth)
        self._trade_count: int = 0
        self._win_count: int = 0
        self._total_pnl: float = 0.0

        logger.info(
            "ShadowFrontStrategy initialized for %s: whale_threshold=%.2f, "
            "sentiment_threshold=%.2f, min_confidence=%.2f, zone_tolerance=%.2f%%",
            symbol, self.whale_threshold_z, self.sentiment_threshold,
            self.min_confidence, self.whale_zone_tolerance * 100
        )

    # =========================================================================
    # OVERLAY STATE UPDATES
    # =========================================================================

    def update_macro_state(self, macro_signal: Optional[MacroSignal]) -> None:
        """Update macro overlay state from sentiment velocity engine."""
        if macro_signal is None:
            return

        self._macro_kill_active = macro_signal.macro_kill
        self._macro_pause_active = macro_signal.macro_pause
        self._bull_trap_detected = macro_signal.bull_trap_detected

        if self._macro_kill_active and self._in_position:
            logger.warning(
                "SHADOW-FRONT [%s]: macro_kill active — position exits on next price tick",
                self.symbol
            )

    def update_insider_state(self, insider_snapshot: Optional[InsiderSignalSnapshot]) -> None:
        """Update insider state from InsiderSignalEngine using urgency property."""
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
        """Update toxicity state from toxicity engine."""
        if toxicity_alert is None:
            self._toxicity_high = False
            self._toxicity_regime = None
            return

        self._toxicity_regime = toxicity_alert.regime
        self._toxicity_high = toxicity_alert.regime >= ToxicityRegime.TOXIC

    def update_whale(self, whale_score: WhaleFlowScore) -> None:
        """
        Update with new whale score.

        Stores score, accumulation flag, and zone bounds for entry/exit decisions.
        """
        self._last_whale_score = whale_score.score
        self._last_whale_accumulating = whale_score.is_accumulating
        self._whale_zone_low = whale_score.whale_zone_low
        self._whale_zone_high = whale_score.whale_zone_high
        self._whale_zone_active = (
            self._whale_zone_low is not None and
            self._whale_zone_high is not None
        )

    def update_whale_zone(self, zone: Optional[WhalePresenceZone]) -> None:
        """Update whale zone from WhaleZoneEngine."""
        if zone is None:
            self._whale_zone_active = False
            self._whale_zone_low = None
            self._whale_zone_high = None
            return

        self._whale_zone_active = zone.presence or zone.proximity > 0.5
        self._whale_zone_low = zone.lower_bound
        self._whale_zone_high = zone.upper_bound

    def update_sentiment(self, sentiment_velocity: float, timestamp_ns: int) -> None:
        """
        Update with new sentiment velocity.

        Args:
            sentiment_velocity: Current sentiment velocity (z-score)
            timestamp_ns: Exchange timestamp (reserved for future history)
        """
        self._last_sentiment_velocity = sentiment_velocity
        # timestamp_ns reserved for future use (signature stability)

    # =========================================================================
    # PRICE UPDATE + ENTRY/EXIT MANAGEMENT
    # =========================================================================

    def update_price(
        self,
        price: float,
        timestamp_ns: int,
        capital_usd: float,
        volatility: float = 0.20,
        regime: RegimeType = RegimeType.UNKNOWN
    ) -> Optional[StrategySignal]:
        """
        Update with current price and check for entry/exit.

        This is the core orchestration method for the strategy.

        Args:
            price: Current market price
            timestamp_ns: Exchange timestamp (nanoseconds)
            capital_usd: Current capital for position sizing
            volatility: Current volatility (annualized) for sizing
            regime: Current market regime for confidence adjustment

        Returns:
            StrategySignal if action needed, else None
        """
        # Cooldown check
        if timestamp_ns < self._cooldown_until_ns:
            return None

        # Macro kill override (highest priority)
        if self._macro_kill_active:
            if self._in_position:
                return self._generate_exit_signal(price, timestamp_ns, "macro_kill")
            return None

        # Exit if in position
        if self._in_position:
            return self._check_exit_conditions(price, timestamp_ns)

        # Entry if not in position
        return self._check_entry_conditions(price, timestamp_ns, capital_usd, volatility, regime)

    def _check_entry_conditions(
        self,
        price: float,
        timestamp_ns: int,
        capital_usd: float,
        volatility: float,
        regime: RegimeType
    ) -> Optional[StrategySignal]:
        """Check all entry conditions and generate entry signal if met."""
        # Toxicity block
        if self._toxicity_high:
            return None

        # Whale condition
        whale_condition = (
            self._last_whale_score >= self.whale_threshold_z or
            self._last_whale_accumulating
        )
        if not whale_condition:
            return None

        # Sentiment condition
        if self._last_sentiment_velocity < self.sentiment_threshold:
            return None

        # Calculate base confidence
        confidence = self._calculate_base_confidence()

        # Apply macro adjustments
        if self._macro_pause_active:
            confidence *= MACRO_PAUSE_REDUCTION

        if self._bull_trap_detected:
            confidence *= BULL_TRAP_REDUCTION

        # Apply insider boost
        if self._insider_active:
            confidence = min(0.95, confidence * INSIDER_BOOST)

        # Final confidence threshold
        if confidence < self.min_confidence:
            return None

        # Calculate position size
        position_size = self._calculate_position_size(
            capital_usd=capital_usd,
            price=price,
            confidence=confidence,
            volatility=volatility,
            regime=regime
        )

        if position_size <= EPS:
            return None

        # Generate entry signal
        return self._generate_entry_signal(
            price=price,
            timestamp_ns=timestamp_ns,
            confidence=confidence,
            position_size=position_size
        )

    def _check_exit_conditions(
        self,
        price: float,
        timestamp_ns: int
    ) -> Optional[StrategySignal]:
        """Check all exit conditions in priority order."""
        if self._entry_price is None or self._entry_ts_ns is None or self._entry_side is None:
            # Inconsistent state — force reset
            logger.error("SHADOW-FRONT [%s]: inconsistent position state — forcing reset", self.symbol)
            self._reset_position()
            return None

        # Calculate PnL percentage
        if self._entry_side == "buy":
            pnl_pct = (price - self._entry_price) / self._entry_price
        else:
            pnl_pct = (self._entry_price - price) / self._entry_price

        # Priority 1: Toxicity spike
        if self._toxicity_high:
            return self._generate_exit_signal(price, timestamp_ns, "toxicity_spike")

        # Priority 2: Take profit
        if pnl_pct >= TAKE_PROFIT_PCT:
            return self._generate_exit_signal(price, timestamp_ns, f"take_profit pnl={pnl_pct:.4f}")

        # Priority 3: Stop loss
        if pnl_pct <= -STOP_LOSS_PCT:
            return self._generate_exit_signal(price, timestamp_ns, f"stop_loss pnl={pnl_pct:.4f}")

        # Priority 4: Time-based (max hold)
        hold_seconds = (timestamp_ns - self._entry_ts_ns) / 1_000_000_000.0
        if hold_seconds >= MAX_HOLD_SECONDS:
            return self._generate_exit_signal(price, timestamp_ns, f"max_hold {hold_seconds:.0f}s")

        # Priority 5: Whale zone exit
        if self._whale_zone_active and self._whale_zone_low and self._whale_zone_high:
            tolerance = self.whale_zone_tolerance
            low_bound = self._whale_zone_low * (1 - tolerance)
            high_bound = self._whale_zone_high * (1 + tolerance)
            if price < low_bound or price > high_bound:
                return self._generate_exit_signal(price, timestamp_ns, "price_exited_whale_zone")

        # Priority 6: Sentiment velocity collapse
        if self._last_sentiment_velocity < 0.5:
            return self._generate_exit_signal(price, timestamp_ns, "sentiment_collapse")

        return None

    # =========================================================================
    # SIGNAL GENERATION
    # =========================================================================

    def _generate_entry_signal(
        self,
        price: float,
        timestamp_ns: int,
        confidence: float,
        position_size: float
    ) -> StrategySignal:
        """Generate entry signal and update position state."""
        # Update position state
        self._in_position = True
        self._entry_price = price
        self._entry_ts_ns = timestamp_ns
        self._entry_side = "buy"  # Long-only by repo truth
        self._position_size = position_size
        self._entry_confidence = confidence

        logger.info(
            "SHADOW-FRONT ENTRY [%s]: @ %.4f size=%.6f conf=%.3f whale=%.2f sentiment=%.2f",
            self.symbol, price, position_size, confidence,
            self._last_whale_score, self._last_sentiment_velocity
        )

        return StrategySignal(
            strategy=SleeveType.SHADOW_FRONT.value,
            symbol=self.symbol,
            side="buy",
            confidence=confidence,
            quantity=position_size,
            price=price,
            exchange_ts_ns=timestamp_ns,
            reason=(
                f"whale={self._last_whale_score:.2f} "
                f"sentiment={self._last_sentiment_velocity:.2f} "
                f"conf={confidence:.2f}"
            ),
            metadata={
                "whale_score": self._last_whale_score,
                "sentiment_velocity": self._last_sentiment_velocity,
                "insider_active": self._insider_active,
                "insider_urgency": self._insider_urgency,
                "macro_pause_active": self._macro_pause_active,
                "macro_kill_active": self._macro_kill_active,
                "bull_trap_detected": self._bull_trap_detected,
                "toxicity_high": self._toxicity_high,
                "whale_zone_active": self._whale_zone_active,
                "whale_zone_low": self._whale_zone_low,
                "whale_zone_high": self._whale_zone_high
            }
        )

    def _generate_exit_signal(
        self,
        price: float,
        timestamp_ns: int,
        reason: str
    ) -> StrategySignal:
        """Generate exit signal, update performance, and reset position state."""
        if self._entry_price is None or self._entry_side is None:
            logger.error("SHADOW-FRONT [%s]: exit without valid entry state", self.symbol)
            self._reset_position()
            return None

        # Calculate PnL
        if self._entry_side == "buy":
            pnl_pct = (price - self._entry_price) / self._entry_price
            pnl_usd = self._position_size * (price - self._entry_price)
        else:
            pnl_pct = (self._entry_price - price) / self._entry_price
            pnl_usd = self._position_size * (self._entry_price - price)

        # Update performance tracking
        self._trade_count += 1
        if pnl_usd > 0:
            self._win_count += 1
        self._total_pnl += pnl_usd

        # Determine exit side
        exit_side = "sell" if self._entry_side == "buy" else "buy"

        logger.info(
            "SHADOW-FRONT EXIT [%s]: @ %.4f PnL=%.2f%% ($%.2f) reason=%s",
            self.symbol, price, pnl_pct * 100, pnl_usd, reason
        )

        signal = StrategySignal(
            strategy=SleeveType.SHADOW_FRONT.value,
            symbol=self.symbol,
            side=exit_side,
            confidence=self._entry_confidence,
            quantity=self._position_size,
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

        # Reset position state and set cooldown
        self._reset_position()
        self._cooldown_until_ns = timestamp_ns + (COOLDOWN_SECONDS * 1_000_000_000)

        return signal

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _calculate_base_confidence(self) -> float:
        """
        Calculate base confidence from whale score and sentiment velocity.

        Formula:
            confidence = (whale_score * 0.6) + (normalized_sentiment * 0.4)
            where normalized_sentiment = min(1.0, sentiment_velocity / 3.0)
        """
        whale_contrib = self._last_whale_score * 0.6

        # Normalize sentiment velocity (typical max ~3.0)
        norm_sentiment = min(1.0, max(0.0, self._last_sentiment_velocity / 3.0))
        sentiment_contrib = norm_sentiment * 0.4

        confidence = whale_contrib + sentiment_contrib

        # Clamp to [MIN_BASE_CONFIDENCE, 0.95]
        return max(MIN_BASE_CONFIDENCE, min(0.95, confidence))

    def _calculate_position_size(
        self,
        capital_usd: float,
        price: float,
        confidence: float,
        volatility: float,
        regime: RegimeType
    ) -> float:
        """
        Calculate position size using risk-based formula.

        Formula:
            risk_capital = capital * 0.02 * confidence
            stop_distance = 0.015 (1.5%)
            size = risk_capital / (price * stop_distance)

        Args:
            capital_usd: Total capital in USD
            price: Current asset price
            confidence: Signal confidence (0-1)
            volatility: Current volatility (annualized)
            regime: Current market regime

        Returns:
            Position size in base units
        """
        if price <= EPS or capital_usd <= EPS:
            return 0.0

        # Risk per trade: 2% of capital, scaled by confidence
        risk_per_trade_pct = 0.02
        risk_capital = capital_usd * risk_per_trade_pct * confidence

        # Stop distance: 1.5%
        stop_distance = STOP_LOSS_PCT

        # Size = risk_capital / (price * stop_distance)
        size = risk_capital / (price * stop_distance)

        # Apply regime adjustments
        if regime == RegimeType.CRISIS:
            size *= 0.5
        elif regime == RegimeType.RANGING:
            size *= 0.7

        # Apply volatility adjustment (inverse: higher vol = smaller size)
        if volatility > 0.30:
            size *= 0.7
        elif volatility < 0.15:
            size *= 1.2

        # Minimum size only (instrument constraint)
        # No hard maximum cap — risk-based sizing already limits position
        min_size = 0.0001  # Minimum BTC size (instrument-specific)

        return max(min_size, size)

    def _reset_position(self) -> None:
        """Reset position state to neutral."""
        self._in_position = False
        self._entry_price = None
        self._entry_ts_ns = None
        self._entry_side = None
        self._position_size = 0.0
        self._entry_confidence = 0.0

    # =========================================================================
    # QUERY METHODS
    # =========================================================================

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
            "position_size": self._position_size,
            "whale_score": self._last_whale_score,
            "whale_accumulating": self._last_whale_accumulating,
            "whale_zone_active": self._whale_zone_active,
            "sentiment_velocity": self._last_sentiment_velocity,
            "insider_active": self._insider_active,
            "insider_urgency": self._insider_urgency,
            "macro_kill_active": self._macro_kill_active,
            "macro_pause_active": self._macro_pause_active,
            "bull_trap_detected": self._bull_trap_detected,
            "toxicity_high": self._toxicity_high,
            # cooldown_remaining_sec removed — requires timestamp parameter for truthful reporting
        }

    def is_in_position(self) -> bool:
        """Return True if currently in a position."""
        return self._in_position

    def get_entry_price(self) -> Optional[float]:
        """Return entry price if in position."""
        return self._entry_price

    def get_position_size(self) -> float:
        """Return current position size."""
        return self._position_size

    # =========================================================================
    # RESET
    # =========================================================================

    def reset(self) -> None:
        """Reset all strategy state to initial conditions."""
        self._in_position = False
        self._entry_price = None
        self._entry_ts_ns = None
        self._entry_side = None
        self._position_size = 0.0
        self._entry_confidence = 0.0
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

        self._trade_count = 0
        self._win_count = 0
        self._total_pnl = 0.0

        logger.info("ShadowFrontStrategy reset for %s", self.symbol)