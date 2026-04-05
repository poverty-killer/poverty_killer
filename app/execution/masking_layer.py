"""
Masking Layer - Stochastic Execution Camouflage
Prevents exchange AI from flagging bot as "Toxic Arbitrage."
Adds non-linear jitter to order timing and size randomization.
Simulates human-like execution patterns.
"""

import numpy as np
import logging
import random
from typing import Dict, Optional, Tuple, Any
from dataclasses import dataclass
from collections import deque

from app.brain.ring_buffer import RingBuffer
from app.brain.rolling_stats import RollingStats

logger = logging.getLogger(__name__)

# Machine epsilon for precision
EPS = np.finfo(float).eps


@dataclass
class MaskedOrder:
    """Order with masking applied."""
    original_size: float
    masked_size: float
    original_delay_ms: float
    masked_delay_ms: float
    jitter_applied_ms: float
    size_jitter_percent: float


class MaskingLayer:
    """
    Stochastic masking for execution camouflage.
    Prevents exchange AI from detecting bot patterns.
    Uses non-linear jitter and adaptive randomization.
    """

    def __init__(
        self,
        base_delay_ms: float = 10.0,
        min_delay_ms: float = 1.0,
        max_delay_ms: float = 50.0,
        size_jitter_percent: float = 0.01,      # 1% jitter
        size_jitter_distribution: str = "gaussian",  # "gaussian" or "uniform"
        delay_jitter_distribution: str = "exponential",  # "exponential" or "uniform"
        volatility_adaptive: bool = True,
        exchange: str = "kraken"
    ):
        """
        Initialize masking layer.

        Args:
            base_delay_ms: Base delay for order submission
            min_delay_ms: Minimum delay
            max_delay_ms: Maximum delay
            size_jitter_percent: Maximum size jitter percentage
            size_jitter_distribution: Distribution for size jitter
            delay_jitter_distribution: Distribution for delay jitter
            volatility_adaptive: Whether to adapt jitter to market volatility
            exchange: Exchange name for calibration
        """
        self.base_delay_ms = base_delay_ms
        self.min_delay_ms = min_delay_ms
        self.max_delay_ms = max_delay_ms
        self.size_jitter_percent = size_jitter_percent
        self.size_jitter_distribution = size_jitter_distribution
        self.delay_jitter_distribution = delay_jitter_distribution
        self.volatility_adaptive = volatility_adaptive
        self.exchange = exchange

        # Exchange-specific calibration
        self._exchange_multipliers = {
            "kraken": 1.0,      # Baseline
            "alpaca": 1.2,      # More aggressive masking for US equities
            "ibkr": 0.8         # Futures have different pattern detection
        }
        self._calibration = self._exchange_multipliers.get(exchange.lower(), 1.0)

        # Volatility tracking
        self._volatility_history = RingBuffer(max_size=100)
        self._volatility_stats = RollingStats(window_size=50)

        # Order history (for pattern detection)
        self._order_timestamps = RingBuffer(max_size=1000, track_timestamps=True)
        self._order_sizes = RingBuffer(max_size=1000)

        logger.info(f"MaskingLayer initialized for {exchange}: base_delay={base_delay_ms}ms, "
                   f"size_jitter={size_jitter_percent:.2%}, distribution={delay_jitter_distribution}")

    def update_volatility(self, volatility: float) -> None:
        """
        Update market volatility for adaptive jitter.

        Args:
            volatility: Current market volatility
        """
        self._volatility_history.append(volatility)
        self._volatility_stats.update(volatility)

    def _calculate_adaptive_jitter_ms(self, base_jitter_ms: float) -> float:
        """
        Calculate adaptive jitter based on market volatility.

        Args:
            base_jitter_ms: Base jitter value

        Returns:
            Adjusted jitter with volatility factor
        """
        if not self.volatility_adaptive or self._volatility_stats.count() < 20:
            return base_jitter_ms

        current_vol = self._volatility_history.last() if len(self._volatility_history) > 0 else 0.0
        avg_vol = self._volatility_stats.mean()

        if avg_vol < EPS:
            return base_jitter_ms

        # Lower jitter during high volatility (need speed)
        # Higher jitter during low volatility (can afford camouflage)
        volatility_factor = min(1.0, avg_vol / max(current_vol, EPS))
        jitter_ms = base_jitter_ms * volatility_factor

        return max(self.min_delay_ms / 2, min(self.max_delay_ms / 2, jitter_ms))

    def _generate_delay_jitter(self) -> float:
        """
        Generate delay jitter using specified distribution.

        Returns:
            Jitter in milliseconds
        """
        base_jitter = self.base_delay_ms * 0.3  # 30% of base delay

        if self.delay_jitter_distribution == "exponential":
            # Exponential distribution - more small jitters, occasional large
            jitter = np.random.exponential(scale=base_jitter)
        elif self.delay_jitter_distribution == "uniform":
            # Uniform distribution
            jitter = np.random.uniform(0, base_jitter * 2)
        else:
            # Gaussian (normal)
            jitter = abs(np.random.normal(loc=base_jitter, scale=base_jitter / 2))

        # Apply volatility adaptation
        jitter = self._calculate_adaptive_jitter_ms(jitter)

        # Clamp to allowed range
        return max(self.min_delay_ms, min(self.max_delay_ms, jitter))

    def _generate_size_jitter(self, size: float) -> float:
        """
        Generate size jitter using specified distribution.

        Args:
            size: Original order size

        Returns:
            Jittered size
        """
        max_jitter = size * self.size_jitter_percent

        if self.size_jitter_distribution == "gaussian":
            # Gaussian jitter (most human-like)
            jitter_factor = 1.0 + np.random.normal(loc=0, scale=self.size_jitter_percent / 2)
        else:
            # Uniform jitter
            jitter_factor = 1.0 + np.random.uniform(-self.size_jitter_percent, self.size_jitter_percent)

        # Ensure size is positive
        jittered_size = size * jitter_factor
        return max(0.0001, jittered_size)

    def _detect_pattern_risk(self) -> float:
        """
        Detect if bot is exhibiting pattern risk.
        Returns risk score (0-1, higher = more detectable).

        Returns:
            Pattern risk score
        """
        if len(self._order_timestamps) < 10:
            return 0.0

        # Get recent timestamps
        timestamps = list(self._order_timestamps.get_with_timestamps()[1])[-20:]

        if len(timestamps) < 10:
            return 0.0

        # Calculate intervals
        intervals = [(timestamps[i] - timestamps[i-1]) / 1_000_000 for i in range(1, len(timestamps))]  # ms

        if len(intervals) < 5:
            return 0.0

        # Check for periodicity (regular intervals)
        interval_std = np.std(intervals)
        interval_mean = np.mean(intervals)

        if interval_mean < EPS:
            return 0.0

        coefficient_of_variation = interval_std / interval_mean

        # Low CV = high periodicity = high risk
        pattern_risk = max(0.0, 1.0 - coefficient_of_variation)

        return pattern_risk

    def mask_order(self, size: float, current_volatility: Optional[float] = None) -> MaskedOrder:
        """
        Apply stochastic masking to order.

        Args:
            size: Original order size
            current_volatility: Current market volatility (for adaptive jitter)

        Returns:
            MaskedOrder with applied masking
        """
        # Update volatility if provided
        if current_volatility is not None:
            self.update_volatility(current_volatility)

        # Generate delay jitter
        delay_jitter = self._generate_delay_jitter()

        # Generate size jitter
        size_jitter_percent_actual = self.size_jitter_percent

        # Increase jitter if pattern risk is high
        pattern_risk = self._detect_pattern_risk()
        if pattern_risk > 0.7:
            size_jitter_percent_actual *= 1.5
            logger.debug(f"High pattern risk ({pattern_risk:.2f}), increasing jitter")

        jittered_size = size * (1 + np.random.uniform(-size_jitter_percent_actual, size_jitter_percent_actual))

        # Ensure size is within exchange limits (will be rounded later)
        jittered_size = max(size * 0.9, min(size * 1.1, jittered_size))

        # Apply calibration
        jittered_size = jittered_size * (1 + (np.random.random() - 0.5) * 0.02 * self._calibration)

        # Store for pattern detection
        self._order_timestamps.append(1.0, int(np.datetime64('now').astype('int64')))
        self._order_sizes.append(jittered_size)

        return MaskedOrder(
            original_size=size,
            masked_size=jittered_size,
            original_delay_ms=self.base_delay_ms,
            masked_delay_ms=delay_jitter,
            jitter_applied_ms=delay_jitter - self.base_delay_ms,
            size_jitter_percent=(jittered_size / size) - 1.0
        )

    def simulate_false_signal(self, exchange: str, symbol: str) -> Dict[str, Any]:
        """
        Simulate a false signal to break cross-exchange pattern detection.

        Args:
            exchange: Target exchange for false signal
            symbol: Symbol to simulate

        Returns:
            Simulated signal details
        """
        # Only simulate occasionally (5% of the time)
        if random.random() > 0.05:
            return {"executed": False, "reason": "not_selected"}

        # Don't simulate if we're actually trading on this exchange
        if exchange == self.exchange:
            return {"executed": False, "reason": "primary_exchange"}

        # Generate random size (micro-lot)
        size = np.random.uniform(0.001, 0.01)

        logger.debug(f"Simulating false signal on {exchange} for {symbol} size={size:.4f}")

        return {
            "executed": True,
            "exchange": exchange,
            "symbol": symbol,
            "size": size,
            "side": "buy" if random.random() > 0.5 else "sell",
            "timestamp_ns": int(np.datetime64('now').astype('int64'))
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get masking layer statistics."""
        return {
            "exchange": self.exchange,
            "pattern_risk": self._detect_pattern_risk(),
            "volatility_adaptive": self.volatility_adaptive,
            "current_volatility": self._volatility_history.last() if len(self._volatility_history) > 0 else 0.0,
            "orders_masked": len(self._order_timestamps),
            "size_jitter_distribution": self.size_jitter_distribution,
            "delay_jitter_distribution": self.delay_jitter_distribution,
            "calibration": self._calibration
        }