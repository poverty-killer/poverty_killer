"""
Rolling Window - Bounded OHLCV Storage
Maintains a fixed-size rolling window of candles per symbol.
Prevents unbounded memory growth with 1000-candle cap.
"""

import logging
from collections import deque
from typing import Dict, List, Optional, Any
from datetime import datetime
from threading import RLock

from app.models import Candle

logger = logging.getLogger(__name__)


class RollingWindow:
    """
    Bounded rolling storage for OHLCV candles.
    Thread-safe with 1000-candle cap per symbol.
    """

    def __init__(self, max_candles: int = 1000):
        """
        Initialize rolling window.

        Args:
            max_candles: Maximum candles to keep per symbol
        """
        self.max_candles = max_candles
        self._windows: Dict[str, deque] = {}
        self._lock = RLock()
        logger.info(f"RollingWindow initialized: max_candles={max_candles}")

    def _get_or_create_window(self, symbol: str) -> deque:
        """Get or create a window for a symbol."""
        with self._lock:
            if symbol not in self._windows:
                self._windows[symbol] = deque(maxlen=self.max_candles)
            return self._windows[symbol]

    def add_candle(self, candle: Candle) -> None:
        """
        Add a candle to the rolling window.

        Args:
            candle: Candle to add
        """
        with self._lock:
            window = self._get_or_create_window(candle.symbol)
            window.append(candle)

    def add_candles(self, candles: List[Candle]) -> None:
        """
        Add multiple candles to the rolling window.

        Args:
            candles: List of candles to add
        """
        with self._lock:
            for candle in candles:
                self.add_candle(candle)

    def get_candles(self, symbol: str, count: Optional[int] = None) -> List[Candle]:
        """
        Get recent candles for a symbol.

        Args:
            symbol: Trading symbol
            count: Number of candles to return (None = all)

        Returns:
            List of candles (most recent last)
        """
        with self._lock:
            if symbol not in self._windows:
                return []

            window = self._windows[symbol]
            if count is None:
                return list(window)
            return list(window)[-count:]

    def get_last_candle(self, symbol: str) -> Optional[Candle]:
        """
        Get the most recent candle for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Most recent candle or None
        """
        with self._lock:
            if symbol not in self._windows or not self._windows[symbol]:
                return None
            return self._windows[symbol][-1]

    def get_candle_at_index(self, symbol: str, index: int) -> Optional[Candle]:
        """
        Get candle at specific index (0 = oldest, -1 = newest).

        Args:
            symbol: Trading symbol
            index: Index position

        Returns:
            Candle or None
        """
        with self._lock:
            if symbol not in self._windows:
                return None
            window = self._windows[symbol]
            try:
                return window[index]
            except IndexError:
                return None

    def get_candle_by_time(self, symbol: str, timestamp: datetime) -> Optional[Candle]:
        """
        Get candle by timestamp.

        Args:
            symbol: Trading symbol
            timestamp: Timestamp to search for

        Returns:
            Candle or None
        """
        with self._lock:
            if symbol not in self._windows:
                return None
            for candle in self._windows[symbol]:
                if candle.timestamp == timestamp:
                    return candle
            return None

    def get_candles_since(self, symbol: str, since: datetime) -> List[Candle]:
        """
        Get candles since a specific time.

        Args:
            symbol: Trading symbol
            since: Timestamp to start from

        Returns:
            List of candles after since
        """
        with self._lock:
            if symbol not in self._windows:
                return []
            return [c for c in self._windows[symbol] if c.timestamp >= since]

    def get_candles_range(self, symbol: str, start: datetime, end: datetime) -> List[Candle]:
        """
        Get candles within a time range.

        Args:
            symbol: Trading symbol
            start: Start timestamp
            end: End timestamp

        Returns:
            List of candles in range
        """
        with self._lock:
            if symbol not in self._windows:
                return []
            return [c for c in self._windows[symbol] if start <= c.timestamp <= end]

    def get_count(self, symbol: str) -> int:
        """
        Get number of candles stored for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Number of candles
        """
        with self._lock:
            if symbol not in self._windows:
                return 0
            return len(self._windows[symbol])

    def clear_symbol(self, symbol: str) -> None:
        """
        Clear all candles for a symbol.

        Args:
            symbol: Trading symbol
        """
        with self._lock:
            if symbol in self._windows:
                self._windows[symbol].clear()
                logger.debug(f"Cleared window for {symbol}")

    def clear_all(self) -> None:
        """Clear all windows."""
        with self._lock:
            self._windows.clear()
            logger.info("Cleared all rolling windows")

    def get_symbols(self) -> List[str]:
        """Get all symbols with data."""
        with self._lock:
            return list(self._windows.keys())

    def is_full(self, symbol: str) -> bool:
        """
        Check if window has reached max capacity.

        Args:
            symbol: Trading symbol

        Returns:
            True if window is full
        """
        with self._lock:
            if symbol not in self._windows:
                return False
            return len(self._windows[symbol]) >= self.max_candles

    def get_oldest_timestamp(self, symbol: str) -> Optional[datetime]:
        """
        Get oldest timestamp in window.

        Args:
            symbol: Trading symbol

        Returns:
            Oldest timestamp or None
        """
        with self._lock:
            if symbol not in self._windows or not self._windows[symbol]:
                return None
            return self._windows[symbol][0].timestamp

    def get_newest_timestamp(self, symbol: str) -> Optional[datetime]:
        """
        Get newest timestamp in window.

        Args:
            symbol: Trading symbol

        Returns:
            Newest timestamp or None
        """
        with self._lock:
            if symbol not in self._windows or not self._windows[symbol]:
                return None
            return self._windows[symbol][-1].timestamp

    def get_time_range(self, symbol: str) -> tuple:
        """
        Get time range of stored candles.

        Args:
            symbol: Trading symbol

        Returns:
            Tuple of (oldest, newest) timestamps
        """
        return (self.get_oldest_timestamp(symbol), self.get_newest_timestamp(symbol))

    def to_dict(self, symbol: str) -> List[Dict[str, Any]]:
        """
        Convert window to list of dictionaries for serialization.

        Args:
            symbol: Trading symbol

        Returns:
            List of candle dictionaries
        """
        with self._lock:
            if symbol not in self._windows:
                return []
            return [
                {
                    "symbol": c.symbol,
                    "timestamp": c.timestamp.isoformat(),
                    "open": c.open,
                    "high": c.high,
                    "low": c.low,
                    "close": c.close,
                    "volume": c.volume,
                    "timeframe": c.timeframe,
                }
                for c in self._windows[symbol]
            ]