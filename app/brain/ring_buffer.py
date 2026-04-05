"""
Ring Buffer - Zero-Allocation Memory Manager
Fixed-size NumPy ring buffers for high-frequency data storage.
Pre-allocates memory on init, zero allocations during runtime.
Critical for eliminating micro-stutters in the event loop.

ANALYTICAL/NON-MONETARY BOUNDARY:
This module provides analytical signal processing primitives using float64
for performance. It is NOT used for monetary truth, risk, or accounting.
All financial calculations must use Decimal elsewhere.
"""

import numpy as np
from typing import Optional, Tuple, Any, List
from dataclasses import dataclass
from app.utils.time_utils import now_ns

# Machine epsilon for precision
EPS = np.finfo(float).eps


class RingBuffer:
    """
    Fixed-size NumPy ring buffer for zero-allocation history.
    Pre-allocates memory on init, no allocations during runtime.
    Supports multiple data types and optional timestamp tracking.
    """

    def __init__(self, max_size: int, dtype: type = np.float64, track_timestamps: bool = False):
        """
        Initialize ring buffer.

        Args:
            max_size: Maximum number of elements to store
            dtype: NumPy data type for values
            track_timestamps: If True, maintain parallel timestamp buffer
        """
        if max_size <= 0:
            raise ValueError(f"max_size must be positive, got {max_size}")
        self.max_size = max_size
        self.dtype = dtype
        self.track_timestamps = track_timestamps

        # Pre-allocated buffers
        self._buffer = np.zeros(max_size, dtype=dtype)
        self._head = 0
        self._size = 0

        # Optional timestamp buffer
        self._ts_buffer: Optional[np.ndarray] = None
        if track_timestamps:
            self._ts_buffer = np.zeros(max_size, dtype=np.int64)  # nanoseconds

    def enable_timestamp_tracking(self) -> None:
        """
        Enable timestamp tracking after initialization.
        Allocates timestamp buffer if not already present.
        Existing timestamps remain zero.
        """
        if self.track_timestamps:
            return
        self.track_timestamps = True
        self._ts_buffer = np.zeros(self.max_size, dtype=np.int64)

    def append(self, value: float, timestamp_ns: Optional[int] = None) -> None:
        """
        Append value to buffer (overwrites oldest when full).

        Args:
            value: Value to append
            timestamp_ns: Optional nanosecond timestamp for tracking
        """
        if self.track_timestamps and timestamp_ns is not None:
            if timestamp_ns < 0:
                raise ValueError(f"timestamp_ns must be non-negative, got {timestamp_ns}")
            self._ts_buffer[self._head] = timestamp_ns
        self._buffer[self._head] = value

        self._head = (self._head + 1) % self.max_size
        if self._size < self.max_size:
            self._size += 1

    def append_batch(self, values: List[float], timestamps_ns: Optional[List[int]] = None) -> None:
        """
        Append multiple values efficiently.

        Args:
            values: List of values to append
            timestamps_ns: Optional list of timestamps
        """
        for i, val in enumerate(values):
            ts = timestamps_ns[i] if timestamps_ns else None
            self.append(val, ts)

    def get(self) -> np.ndarray:
        """
        Get all values in order (oldest to newest).

        Returns:
            NumPy array of values
        """
        if self._size < self.max_size:
            return self._buffer[:self._size]
        return np.concatenate([self._buffer[self._head:], self._buffer[:self._head]])

    def get_with_timestamps(self) -> Tuple[np.ndarray, np.ndarray]:
        """
        Get values with timestamps.

        Returns:
            Tuple of (values array, timestamps array)
        """
        if not self.track_timestamps or self._ts_buffer is None:
            raise ValueError("Timestamps not enabled for this buffer")

        values = self.get()
        if self._size < self.max_size:
            timestamps = self._ts_buffer[:self._size]
        else:
            timestamps = np.concatenate([self._ts_buffer[self._head:], self._ts_buffer[:self._head]])

        return values, timestamps

    def get_window(self, window_size: int) -> np.ndarray:
        """
        Get most recent window of values.

        Args:
            window_size: Number of most recent values to return

        Returns:
            NumPy array of recent values
        """
        window_size = min(window_size, self._size)
        if window_size <= 0:
            return np.array([])

        if self._size < self.max_size:
            # Not yet wrapped
            start = max(0, self._size - window_size)
            return self._buffer[start:self._size]
        else:
            # Wrapped around
            if window_size <= self._head:
                # All in first segment
                return self._buffer[self._head - window_size:self._head]
            else:
                # Spans both segments
                first_part = self._buffer[self._head:]
                remaining = window_size - len(first_part)
                second_part = self._buffer[:remaining]
                return np.concatenate([first_part, second_part])

    def get_window_with_timestamps(self, window_size: int) -> Tuple[np.ndarray, np.ndarray]:
        """
        Get most recent window with timestamps.

        Args:
            window_size: Number of most recent values to return

        Returns:
            Tuple of (values array, timestamps array)
        """
        if not self.track_timestamps or self._ts_buffer is None:
            raise ValueError("Timestamps not enabled for this buffer")

        values = self.get_window(window_size)
        # Get corresponding timestamps - this requires tracking indices
        # Simpler approach: use get_with_timestamps and slice
        full_values, full_ts = self.get_with_timestamps()
        return full_values[-window_size:], full_ts[-window_size:]

    def get_recent(self, count: int) -> np.ndarray:
        """Alias for get_window."""
        return self.get_window(count)

    def get_all(self) -> np.ndarray:
        """Alias for get."""
        return self.get()

    def last(self) -> float:
        """
        Get most recent value.

        Returns:
            Most recent value
        """
        if self._size == 0:
            return 0.0

        if self._head == 0:
            return self._buffer[-1]
        return self._buffer[self._head - 1]

    def last_with_timestamp(self) -> Tuple[float, int]:
        """
        Get most recent value with timestamp.

        Returns:
            Tuple of (value, timestamp_ns)
        """
        if not self.track_timestamps or self._ts_buffer is None:
            raise ValueError("Timestamps not enabled for this buffer")

        if self._size == 0:
            return 0.0, 0

        if self._head == 0:
            idx = -1
        else:
            idx = self._head - 1

        return self._buffer[idx], self._ts_buffer[idx]

    def first(self) -> float:
        """
        Get oldest value.

        Returns:
            Oldest value
        """
        if self._size == 0:
            return 0.0

        if self._size < self.max_size:
            return self._buffer[0]
        else:
            return self._buffer[self._head]

    def first_with_timestamp(self) -> Tuple[float, int]:
        """
        Get oldest value with timestamp.

        Returns:
            Tuple of (value, timestamp_ns)
        """
        if not self.track_timestamps or self._ts_buffer is None:
            raise ValueError("Timestamps not enabled for this buffer")

        if self._size == 0:
            return 0.0, 0

        if self._size < self.max_size:
            idx = 0
        else:
            idx = self._head

        return self._buffer[idx], self._ts_buffer[idx]

    def __len__(self) -> int:
        """Return current number of elements."""
        return self._size

    def is_full(self) -> bool:
        """Check if buffer has reached capacity."""
        return self._size == self.max_size

    def is_empty(self) -> bool:
        """Check if buffer is empty."""
        return self._size == 0

    def clear(self) -> None:
        """Clear all data from buffer (maintains allocated memory)."""
        self._buffer.fill(0)
        if self._ts_buffer is not None:
            self._ts_buffer.fill(0)
        self._head = 0
        self._size = 0

    def get_stats(self) -> dict:
        """Get buffer statistics."""
        return {
            "max_size": self.max_size,
            "current_size": self._size,
            "head_position": self._head,
            "is_full": self.is_full(),
            "dtype": str(self.dtype),
            "track_timestamps": self.track_timestamps
        }


class MultiRingBuffer:
    """
    Manages multiple ring buffers per symbol.
    Provides automatic cleanup based on TTL.
    """

    def __init__(self, max_size: int = 1000, dtype: type = np.float64):
        """
        Initialize multi-ring buffer manager.

        Args:
            max_size: Default max size for each buffer
            dtype: Default data type
        """
        self.max_size = max_size
        self.dtype = dtype
        self._buffers: dict = {}
        self._last_activity: dict = {}

    def get_buffer(self, symbol: str, track_timestamps: bool = False) -> RingBuffer:
        """
        Get or create ring buffer for symbol.

        Args:
            symbol: Trading symbol
            track_timestamps: Whether to track timestamps

        Returns:
            RingBuffer instance
        """
        if symbol not in self._buffers:
            self._buffers[symbol] = RingBuffer(
                max_size=self.max_size,
                dtype=self.dtype,
                track_timestamps=track_timestamps
            )
        return self._buffers[symbol]

    def append(self, symbol: str, value: float, timestamp_ns: Optional[int] = None) -> None:
        """
        Append value to symbol's buffer.

        Args:
            symbol: Trading symbol
            value: Value to append
            timestamp_ns: Optional timestamp
        """
        buffer = self.get_buffer(symbol, track_timestamps=False)
        if timestamp_ns is not None:
            if timestamp_ns < 0:
                raise ValueError(f"timestamp_ns must be non-negative, got {timestamp_ns}")
            if not buffer.track_timestamps:
                buffer.enable_timestamp_tracking()
        buffer.append(value, timestamp_ns)
        self._last_activity[symbol] = timestamp_ns or now_ns()

    def get(self, symbol: str) -> np.ndarray:
        """Get all values for symbol."""
        if symbol not in self._buffers:
            return np.array([])
        return self._buffers[symbol].get()

    def get_window(self, symbol: str, window: int) -> np.ndarray:
        """Get recent window for symbol."""
        if symbol not in self._buffers:
            return np.array([])
        return self._buffers[symbol].get_window(window)

    def evict_expired(self, current_ts_ns: int, ttl_seconds: float = 60.0) -> int:
        """
        Evict buffers for symbols that haven't been updated within TTL.

        Args:
            current_ts_ns: Current exchange timestamp in nanoseconds
            ttl_seconds: Time-to-live in seconds

        Returns:
            Number of evicted symbols
        """
        if ttl_seconds <= 0:
            raise ValueError(f"ttl_seconds must be positive, got {ttl_seconds}")
        ttl_ns = int(ttl_seconds * 1_000_000_000)
        evicted = 0
        expired = []

        for symbol, last_ts in self._last_activity.items():
            if current_ts_ns - last_ts > ttl_ns:
                expired.append(symbol)

        for symbol in expired:
            del self._buffers[symbol]
            del self._last_activity[symbol]
            evicted += 1

        if evicted > 0:
            import logging
            logging.getLogger(__name__).debug(f"Evicted {evicted} expired buffers")

        return evicted

    def clear(self, symbol: str) -> None:
        """Clear buffer for a specific symbol."""
        if symbol in self._buffers:
            self._buffers[symbol].clear()
            self._last_activity[symbol] = 0

    def clear_all(self) -> None:
        """Clear all buffers."""
        self._buffers.clear()
        self._last_activity.clear()


class RollingStatistics:
    """
    Rolling statistics calculator using ring buffer.
    Efficient mean, variance, std, z-score calculations.
    """

    def __init__(self, window_size: int = 100):
        """
        Initialize rolling statistics.

        Args:
            window_size: Rolling window size
        """
        if window_size <= 0:
            raise ValueError(f"window_size must be positive, got {window_size}")
        self.window_size = window_size
        self._buffer = RingBuffer(window_size)
        self._sum = 0.0
        self._sum_sq = 0.0

    def update(self, value: float) -> None:
        """
        Update with new value.

        Args:
            value: New value
        """
        if len(self._buffer) == self.window_size:
            # Remove oldest value before adding new
            oldest = self._buffer.first()
            self._sum -= oldest
            self._sum_sq -= oldest * oldest

        self._buffer.append(value)
        self._sum += value
        self._sum_sq += value * value

    def mean(self) -> float:
        """Calculate rolling mean."""
        n = len(self._buffer)
        if n == 0:
            return 0.0
        return self._sum / n

    def variance(self) -> float:
        """Calculate rolling variance."""
        n = len(self._buffer)
        if n < 2:
            return 0.0
        mean = self.mean()
        return (self._sum_sq / n) - (mean * mean)

    def std(self) -> float:
        """Calculate rolling standard deviation."""
        return np.sqrt(max(0.0, self.variance()))

    def zscore(self, value: float) -> float:
        """Calculate z-score of a value."""
        mean = self.mean()
        std = self.std()
        if std < EPS:
            return 0.0
        return (value - mean) / std

    def reset(self) -> None:
        """Reset statistics."""
        self._buffer.clear()
        self._sum = 0.0
        self._sum_sq = 0.0
