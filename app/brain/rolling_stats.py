"""
Rolling Statistics - Efficient O(1) Calculations
Uses ring buffer for memory efficiency.
Provides mean, variance, std, z‑score, skew, kurtosis, correlation.
Zero allocations after initialization.

NOTE: This module is for **analytical signal processing only**.
It uses `float64` for performance and must NOT be used for monetary truth,
risk, or accounting calculations (which require Decimal).
"""

import numpy as np
from typing import Optional, Tuple
from app.brain.ring_buffer import RingBuffer

# Machine epsilon for precision
EPS = np.finfo(float).eps


class RollingStats:
    """
    Efficient rolling statistics calculator.
    O(1) updates using Welford's algorithm.
    Zero allocations after initialization.
    """

    def __init__(self, window_size: int = 100, track_timestamps: bool = False):
        """
        Initialize rolling statistics.

        Args:
            window_size: Number of samples in rolling window (must be > 0)
            track_timestamps: Whether to store timestamps
        """
        if window_size <= 0:
            raise ValueError("window_size must be positive")
        self.window_size = window_size
        self._buffer = RingBuffer(window_size, track_timestamps=track_timestamps)

        # Welford's algorithm state
        self._count = 0
        self._mean = 0.0
        self._m2 = 0.0  # Sum of squared differences
        self._m3 = 0.0  # Sum of cubed differences (skew)
        self._m4 = 0.0  # Sum of fourth powers (kurtosis)
        self._sum = 0.0

    def update(self, value: float, timestamp_ns: Optional[int] = None) -> None:
        """
        Update statistics with new value.

        Args:
            value: New value to add
            timestamp_ns: Optional nanosecond timestamp (must be int or None)
        """
        if timestamp_ns is not None and not isinstance(timestamp_ns, int):
            raise TypeError("timestamp_ns must be int or None")

        # If buffer is full, remove oldest first
        if len(self._buffer) == self.window_size:
            oldest = self._buffer.first()
            self._remove(oldest)

        # Add new value
        self._buffer.append(value, timestamp_ns)
        self._add(value)

    def _add(self, x: float) -> None:
        """Add value to Welford algorithm."""
        n = self._count + 1
        delta = x - self._mean
        delta_n = delta / n
        delta_n2 = delta_n * delta_n

        # Update moments (order matters: m4, m3, m2, mean)
        self._m4 += (
            delta * delta_n * delta_n * (n * n - 3 * n + 3)
            + 6 * delta_n2 * self._m2
            - 4 * delta_n * self._m3
        )
        self._m3 += delta * delta_n * (n - 2) - 3 * delta_n * self._m2
        self._m2 += delta * delta_n * (n - 1)
        self._mean += delta_n
        self._count = n
        self._sum += x

    def _remove(self, x: float) -> None:
        """Remove value from Welford algorithm (for sliding window)."""
        n = self._count
        if n <= 0:
            return

        delta = x - self._mean
        n_minus_1 = n - 1

        # Inverse update: keep previous m2/m3 before they are changed
        prev_m2 = self._m2
        prev_m3 = self._m3

        delta_n = delta / n_minus_1 if n_minus_1 > 0 else 0.0
        delta_n2 = delta_n * delta_n

        self._mean = (n * self._mean - x) / n_minus_1 if n_minus_1 > 0 else 0.0
        self._m2 -= delta * delta_n * n
        self._m3 -= delta * delta_n * (n - 2) - 3 * delta_n * prev_m2
        self._m4 -= (
            delta * delta_n * delta_n * (n * n - 3 * n + 3)
            + 6 * delta_n2 * prev_m2
            - 4 * delta_n * prev_m3
        )

        self._count = n_minus_1
        self._sum -= x

    def mean(self) -> float:
        """Get rolling mean."""
        return self._mean

    def variance(self) -> float:
        """Get rolling variance (population variance)."""
        if self._count < 2:
            return 0.0
        # Guard against floating‑point drift below zero
        return max(0.0, self._m2 / self._count)

    def sample_variance(self) -> float:
        """Get rolling sample variance (unbiased)."""
        if self._count < 2:
            return 0.0
        return max(0.0, self._m2 / (self._count - 1))

    def std(self) -> float:
        """Get rolling standard deviation."""
        return np.sqrt(self.variance())

    def sample_std(self) -> float:
        """Get rolling sample standard deviation."""
        return np.sqrt(self.sample_variance())

    def skew(self) -> float:
        """Get rolling skewness (measure of asymmetry)."""
        if self._count < 3:
            return 0.0
        var = self.variance()
        if var < EPS:
            return 0.0
        return self._m3 / (self._count * var ** 1.5)

    def kurtosis(self) -> float:
        """Get rolling kurtosis (measure of tail heaviness)."""
        if self._count < 4:
            return 0.0
        var = self.variance()
        if var < EPS:
            return 0.0
        return self._m4 / (self._count * var * var) - 3.0

    def zscore(self, value: float) -> float:
        """Calculate z‑score of a value against rolling distribution."""
        std = self.std()
        if std < EPS:
            return 0.0
        return (value - self.mean()) / std

    def quantile(self, q: float) -> float:
        """
        Estimate quantile from histogram.
        Note: This requires full data access (O(window_size) per call).
        For real‑time, consider using reservoir sampling.

        Args:
            q: Quantile (0‑1)

        Returns:
            Estimated quantile value
        """
        if len(self._buffer) == 0:
            return 0.0

        data = self._buffer.get()
        # buffer.get() returns empty array when buffer is empty;
        # the len check above already guarantees data is non‑empty.
        return np.percentile(data, q * 100)

    def percentile(self, p: float) -> float:
        """Alias for quantile."""
        return self.quantile(p / 100)

    def sum(self) -> float:
        """Get rolling sum."""
        return self._sum

    def count(self) -> int:
        """Get number of samples in window."""
        return self._count

    def is_full(self) -> bool:
        """Check if window is full."""
        return self._count == self.window_size

    def get_buffer(self) -> RingBuffer:
        """Get underlying ring buffer (for direct access)."""
        return self._buffer

    def get_values(self) -> np.ndarray:
        """Get all values in window."""
        return self._buffer.get()

    def get_values_with_timestamps(self) -> Tuple[np.ndarray, np.ndarray]:
        """Get values with timestamps."""
        return self._buffer.get_with_timestamps()

    def reset(self) -> None:
        """Reset all statistics."""
        self._buffer.clear()
        self._count = 0
        self._mean = 0.0
        self._m2 = 0.0
        self._m3 = 0.0
        self._m4 = 0.0
        self._sum = 0.0

    def get_stats(self) -> dict:
        """Get all statistics as dictionary."""
        return {
            "count": self._count,
            "mean": self.mean(),
            "variance": self.variance(),
            "std": self.std(),
            "skew": self.skew(),
            "kurtosis": self.kurtosis(),
            "sum": self._sum,
            "is_full": self.is_full(),
        }


class RollingCorrelation:
    """
    Efficient rolling correlation between two time series.
    O(1) updates using Welford's algorithm.
    """

    def __init__(self, window_size: int = 100):
        """
        Initialize rolling correlation.

        Args:
            window_size: Rolling window size (must be > 0)
        """
        if window_size <= 0:
            raise ValueError("window_size must be positive")
        self.window_size = window_size
        self._buffer_x = RingBuffer(window_size)
        self._buffer_y = RingBuffer(window_size)

        # Welford's algorithm for covariance
        self._count = 0
        self._mean_x = 0.0
        self._mean_y = 0.0
        self._cov = 0.0
        self._var_x = 0.0
        self._var_y = 0.0

    def update(self, x: float, y: float) -> None:
        """
        Update correlation with new pair.

        Args:
            x: First value
            y: Second value
        """
        # Remove oldest if full
        if len(self._buffer_x) == self.window_size:
            oldest_x = self._buffer_x.first()
            oldest_y = self._buffer_y.first()
            self._remove(oldest_x, oldest_y)

        self._buffer_x.append(x)
        self._buffer_y.append(y)
        self._add(x, y)

    def _add(self, x: float, y: float) -> None:
        """Add new pair to Welford algorithm."""
        n = self._count + 1

        delta_x = x - self._mean_x
        delta_y = y - self._mean_y

        self._mean_x += delta_x / n
        self._mean_y += delta_y / n

        if n > 1:
            self._cov += delta_x * delta_y * (n - 1) / n
            self._var_x += delta_x * delta_x * (n - 1) / n
            self._var_y += delta_y * delta_y * (n - 1) / n

        self._count = n

    def _remove(self, x: float, y: float) -> None:
        """Remove oldest pair from sliding window."""
        n = self._count
        if n <= 0:
            return

        n_minus_1 = n - 1
        if n_minus_1 <= 0:
            self.reset()
            return

        delta_x = x - self._mean_x
        delta_y = y - self._mean_y

        self._mean_x = (n * self._mean_x - x) / n_minus_1
        self._mean_y = (n * self._mean_y - y) / n_minus_1

        self._cov -= delta_x * delta_y * n / n_minus_1
        self._var_x -= delta_x * delta_x * n / n_minus_1
        self._var_y -= delta_y * delta_y * n / n_minus_1

        # Guard against floating‑point drift below zero
        self._var_x = max(0.0, self._var_x)
        self._var_y = max(0.0, self._var_y)
        # cov can be negative legitimately; no clamp needed

        self._count = n_minus_1

    def correlation(self) -> float:
        """Get rolling correlation coefficient."""
        # Protect against zero or negative variance due to rounding
        denom = self._var_x * self._var_y
        if denom < EPS:
            return 0.0
        # Clamp correlation to [-1, 1] in case of residual floating error
        raw = self._cov / np.sqrt(denom)
        return max(-1.0, min(1.0, raw))

    def covariance(self) -> float:
        """Get rolling covariance."""
        if self._count < 2:
            return 0.0
        return self._cov / self._count

    def count(self) -> int:
        """Get number of samples."""
        return self._count

    def reset(self) -> None:
        """Reset all statistics."""
        self._buffer_x.clear()
        self._buffer_y.clear()
        self._count = 0
        self._mean_x = 0.0
        self._mean_y = 0.0
        self._cov = 0.0
        self._var_x = 0.0
        self._var_y = 0.0
