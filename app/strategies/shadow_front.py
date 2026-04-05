"""
Shadow-Front Manifold - Flagship Alpha Strategy
Detects whale accumulation + sentiment ignition with institutional-grade precision.
Integrates macro-overlay, insider signals, and toxicity detection for unfair advantage.
"""

import logging
import numpy as np
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timedelta

from app.models import (
    WhaleFlowScore, SentimentVelocity, EntropyScore,
    OrderBookSnapshot, StrategySignal, CurvatureSignal,
    MacroSignal, InsiderSignal, ToxicityAlert
)
from app.brain.shadow_front_state import ShadowFrontStateMachine
from app.constants import SleeveType, RegimeType, ShadowFrontState
from app.brain.ring_buffer import RingBuffer
from app.brain.rolling_stats import RollingStats

logger = logging.getLogger(__name__)

# Machine epsilon
EPS = np.finfo(float).eps


class ShadowFrontStrategy:
    """
    Flagship strategy: Shadow-Front Manifold.
    Detects whale accumulation, sentiment ignition, and executes with institutional precision.
    Integrated with macro, insider, and toxicity signals for unfair advantage.
    """

    def __init__(self, config: Any, symbol: str):
        """
        Initialize Shadow-Front strategy.

        Args:
            config: Configuration object
            symbol: Trading symbol
        """
        self.config = config
        self.symbol = symbol
        self.state_machine = ShadowFrontStateMachine(symbol)

        # Strategy parameters
        self.whale_threshold_z = config.strategies.whale_threshold_z
        self.sentiment_threshold = config.strategies.sentiment_velocity_threshold
        self.min_confidence = config.strategies.min_confidence
        self.whale_zone_tolerance = config.strategies.whale_zone_tolerance

        # Performance tracking
        self._trade_count = 0
        self._win_count = 0
        self._total_pnl = 0.0
        self._pnl_history = RingBuffer(max_size=100)

        # Recent signals for context
        self._recent_whale_scores = RingBuffer(max_size=20)
        self._recent_sentiment_velocities = RingBuffer(max_size=20)

        # Macro/Insider/Toxicity state
        self._macro_pause = False
        self._insider_aligned = False
        self._toxicity_high = False

        logger.info(f"ShadowFrontStrategy initialized for {symbol}")

    def update_macro_state(self, macro_signal: Optional[MacroSignal]) -> None:
        """Update macro state from sentiment velocity."""
        if macro_signal:
            self._macro_pause = macro_signal.macro_pause or macro_signal.macro_kill

    def update_insider_state(self, insider_signal: Optional[InsiderSignal]) -> None:
        """Update insider state from insider engine."""
        if insider_signal and insider_signal.detected:
            self._insider_aligned = True
        else:
            self._insider_aligned = False

    def update_toxicity_state(self, toxicity_alert: Optional[ToxicityAlert]) -> None:
        """Update toxicity state from toxicity engine."""
        if toxicity_alert and toxicity_alert.is_toxic:
            self._toxicity_high = True
        else:
            self._toxicity_high = False

    def update_whale(self, whale_score: WhaleFlowScore) -> None:
        """Update with new whale score."""
        self._recent_whale_scores.append(whale_score.score)
        self.state_machine.update_whale_signal(whale_score)

    def update_sentiment(self, sentiment: SentimentVelocity) -> None:
        """Update with new sentiment velocity."""
        self._recent_sentiment_velocities.append(sentiment.velocity)
        self.state_machine.update_sentiment_signal(sentiment)

    def update_price(self, price: float, timestamp_ns: int) -> Optional[StrategySignal]:
        """
        Update with current price and check for entry/exit.

        Args:
            price: Current price
            timestamp_ns: Exchange timestamp

        Returns:
            StrategySignal if action needed, else None
        """
        # Update state machine with price
        action = self.state_machine.update_price(price)

        if action == "enter":
            return self._generate_entry_signal(price, timestamp_ns)
        elif action == "exit":
            return self._generate_exit_signal(price, timestamp_ns)

        return None

    def _generate_entry_signal(self, price: float, timestamp_ns: int) -> Optional[StrategySignal]:
        """
        Generate entry signal with institutional confidence.

        Args:
            price: Current price
            timestamp_ns: Exchange timestamp

        Returns:
            StrategySignal or None
        """
        # Get current whale and sentiment
        whale_score = self._recent_whale_scores.last() if len(self._recent_whale_scores) > 0 else 0.0
        sentiment_vel = self._recent_sentiment_velocities.last() if len(self._recent_sentiment_velocities) > 0 else 0.0

        # Base confidence from state machine
        base_confidence = self.state_machine._calculate_confidence()

        # Apply institutional boosts
        confidence = base_confidence

        # Insider alignment boost
        if self._insider_aligned:
            confidence = min(0.95, confidence * 1.3)
            logger.info(f"INSIDER ALIGNMENT BOOST: confidence={confidence:.2f}")

        # Toxicity override - if toxic, stand down
        if self._toxicity_high:
            logger.warning(f"TOXICITY DETECTED - standing down for {self.symbol}")
            return None

        # Macro pause override
        if self._macro_pause:
            logger.info(f"MACRO PAUSE ACTIVE - standing down for {self.symbol}")
            return None

        # Confidence threshold
        if confidence < self.min_confidence:
            logger.debug(f"Confidence too low: {confidence:.2f} < {self.min_confidence:.2f}")
            return None

        # Calculate position size
        position_size = self._calculate_position_size(confidence, price)

        # Create signal
        signal = StrategySignal(
            strategy=SleeveType.SHADOW_FRONT,
            symbol=self.symbol,
            side="buy",
            confidence=confidence,
            quantity=position_size,
            price=price,
            exchange_ts_ns=timestamp_ns,
            reason=f"Whale={whale_score:.2f}, Sentiment={sentiment_vel:.2f}, Confidence={confidence:.2f}",
            metadata={
                "whale_score": whale_score,
                "sentiment_velocity": sentiment_vel,
                "insider_aligned": self._insider_aligned,
                "macro_pause": self._macro_pause,
                "toxicity_high": self._toxicity_high
            }
        )

        # Update state machine
        self.state_machine.set_entry(price, position_size)

        logger.info(f"SHADOW-FRONT ENTRY: {self.symbol} @ {price:.2f}, size={position_size:.4f}, conf={confidence:.2f}")
        return signal

    def _generate_exit_signal(self, price: float, timestamp_ns: int) -> Optional[StrategySignal]:
        """
        Generate exit signal.

        Args:
            price: Current price
            timestamp_ns: Exchange timestamp

        Returns:
            StrategySignal or None
        """
        if not self.state_machine.is_in_position():
            return None

        # Calculate P&L
        entry_price = self.state_machine.entry_price or price
        pnl_percent = (price - entry_price) / entry_price

        # Check exit conditions with institutional awareness
        should_exit = self._should_exit(price, pnl_percent)

        if not should_exit:
            return None

        # Calculate quantity
        quantity = self.state_machine.position_size

        # Update P&L tracking
        pnl = quantity * (price - entry_price)
        self._total_pnl += pnl
        self._pnl_history.append(pnl)
        self._trade_count += 1
        if pnl > 0:
            self._win_count += 1

        signal = StrategySignal(
            strategy=SleeveType.SHADOW_FRONT,
            symbol=self.symbol,
            side="sell",
            confidence=self.state_machine._calculate_confidence(),
            quantity=quantity,
            price=price,
            exchange_ts_ns=timestamp_ns,
            reason=f"Exit at {pnl_percent:.2%}",
            metadata={
                "entry_price": entry_price,
                "exit_price": price,
                "pnl_percent": pnl_percent,
                "hold_seconds": self.state_machine.hold_duration_seconds
            }
        )

        # Update state machine
        self.state_machine.set_exit(price, pnl)

        logger.info(f"SHADOW-FRONT EXIT: {self.symbol} @ {price:.2f}, PnL={pnl_percent:.2%}")
        return signal

    def _should_exit(self, current_price: float, pnl_percent: float) -> bool:
        """
        Determine if exit conditions are met with institutional awareness.

        Args:
            current_price: Current price
            pnl_percent: Current P&L percentage

        Returns:
            True if should exit
        """
        # Take profit: +2%
        if pnl_percent >= 0.02:
            return True

        # Stop loss: -1.5%
        if pnl_percent <= -0.015:
            return True

        # Price leaves whale zone
        if not self.state_machine._is_price_in_whale_zone(current_price):
            return True

        # Sentiment velocity drop
        if len(self._recent_sentiment_velocities) > 0:
            recent_vel = self._recent_sentiment_velocities.get()
            if len(recent_vel) > 5 and recent_vel[-1] < 0.5:
                return True

        # Toxicity spike - exit immediately
        if self._toxicity_high:
            logger.warning(f"TOXICITY SPIKE - exiting position for {self.symbol}")
            return True

        # Insider reversal - exit if insider signal reverses
        if self._insider_aligned and self.state_machine.entry_time:
            hold_minutes = (datetime.utcnow() - self.state_machine.entry_time).total_seconds() / 60
            if hold_minutes > 30:
                # Insider signals typically last 30-45 minutes
                return True

        # Time-based exit (max 30 minutes)
        if self.state_machine.entry_time:
            hold_seconds = (datetime.utcnow() - self.state_machine.entry_time).total_seconds()
            if hold_seconds > 1800:
                return True

        return False

    def _calculate_position_size(self, confidence: float, price: float) -> float:
        """
        Calculate position size with institutional risk management.

        Args:
            confidence: Signal confidence
            price: Current price

        Returns:
            Position size in units
        """
        # Base size from available capital (would come from portfolio)
        # Using simulated $20,000 capital, max 2% risk per trade
        max_risk_usd = 20000.0 * 0.02  # $400 max risk

        # Stop distance in percentage
        stop_distance = 0.015  # 1.5% stop

        # Position size based on risk
        base_size = max_risk_usd / (price * stop_distance)

        # Apply confidence scaling
        size = base_size * confidence

        # Apply institutional modifiers
        if self._insider_aligned:
            size *= 1.2  # 20% boost for insider alignment

        if self._macro_pause:
            size *= 0.5  # 50% reduction during macro uncertainty

        # Ensure within min/max
        min_size = 0.0001  # Min BTC size
        max_size = 1.0     # Max BTC size for $20k account

        return max(min_size, min(max_size, size))

    def get_performance(self) -> Dict[str, Any]:
        """Get strategy performance metrics."""
        win_rate = self._win_count / max(self._trade_count, 1)
        avg_pnl = self._total_pnl / max(self._trade_count, 1)

        return {
            "symbol": self.symbol,
            "trade_count": self._trade_count,
            "win_count": self._win_count,
            "win_rate": win_rate,
            "total_pnl": self._total_pnl,
            "avg_pnl": avg_pnl,
            "current_state": self.state_machine.current_state.value,
            "in_position": self.state_machine.is_in_position(),
            "whale_zone_active": self.state_machine.whale_zone_low is not None
        }

    def reset(self) -> None:
        """Reset strategy state."""
        self.state_machine.reset()
        self._trade_count = 0
        self._win_count = 0
        self._total_pnl = 0.0
        self._pnl_history.clear()
        self._recent_whale_scores.clear()
        self._recent_sentiment_velocities.clear()
        logger.info(f"ShadowFrontStrategy reset for {self.symbol}")