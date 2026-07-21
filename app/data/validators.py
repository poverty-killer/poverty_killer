"""
Validators - Data Integrity and Stale Data Checks
Validates incoming market data for integrity, ordering, and staleness.
Prevents trading on corrupted or stale data.

TIMESTAMP TRUTH:
- Authoritative staleness checks use exchange_ts_ns (nanoseconds)
- Wall-clock (datetime.utcnow) used ONLY for telemetry/logging
- All external callers provide current_time_ns for authoritative checks
"""

import logging
from datetime import datetime
from typing import List, Optional, Tuple, Dict, Any
from dataclasses import dataclass, field

from app.models import Candle, OrderBookSnapshot
from app.constants import STALE_DATA_THRESHOLD_SECONDS
from app.utils.time_utils import now_ns

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of data validation."""
    is_valid: bool
    error: Optional[str] = None
    warnings: List[str] = field(default_factory=list)


class DataValidator:
    """
    Validates incoming market data for integrity and staleness.
    Checks: stale bars, ordering, duplicates, malformed values, impossible OHLCV.
    
    TIMESTAMP AUTHORITY:
    - For authoritative staleness checks, callers must provide current_time_ns
    - Wall-clock fallback (datetime.utcnow) used ONLY when caller omits timestamp
    - This is a constitutional exception for backward compatibility
    """

    def __init__(self, stale_threshold_seconds: int = STALE_DATA_THRESHOLD_SECONDS):
        """
        Initialize validator.

        Args:
            stale_threshold_seconds: Seconds before data is considered stale
        """
        self.stale_threshold_seconds = stale_threshold_seconds
        self._last_timestamps_ns: Dict[str, int] = {}

    def _is_stale_ns(self, timestamp_ns: int, current_time_ns: int) -> bool:
        """Check if a nanosecond timestamp is stale."""
        age_ns = current_time_ns - timestamp_ns
        age_sec = age_ns / 1_000_000_000.0
        return age_sec > self.stale_threshold_seconds

    @staticmethod
    def _timeframe_ns(timeframe: Any) -> Optional[int]:
        text = str(timeframe or "").strip().lower()
        if len(text) < 2:
            return None
        unit_ns = {
            "s": 1_000_000_000,
            "m": 60_000_000_000,
            "h": 3_600_000_000_000,
            "d": 86_400_000_000_000,
        }.get(text[-1])
        try:
            amount = int(text[:-1])
        except ValueError:
            return None
        if unit_ns is None or amount <= 0:
            return None
        return amount * unit_ns

    def validate_candle(
        self,
        candle: Candle,
        current_time_ns: Optional[int] = None
    ) -> ValidationResult:
        """
        Validate a single candle.

        Args:
            candle: Candle to validate
            current_time_ns: Current time in nanoseconds (authoritative)

        Returns:
            ValidationResult with status and errors/warnings
        """
        errors = []
        warnings = []

        # 1. Check for malformed values
        if candle.open <= 0:
            errors.append(f"Open price <= 0: {candle.open}")
        if candle.high <= 0:
            errors.append(f"High price <= 0: {candle.high}")
        if candle.low <= 0:
            errors.append(f"Low price <= 0: {candle.low}")
        if candle.close <= 0:
            errors.append(f"Close price <= 0: {candle.close}")
        if candle.volume < 0:
            errors.append(f"Volume negative: {candle.volume}")

        # 2. Check impossible OHLCV
        if candle.high < candle.low:
            errors.append(f"High ({candle.high}) < Low ({candle.low})")
        if candle.high < candle.open and candle.high < candle.close:
            warnings.append(f"High ({candle.high}) below both open and close")
        if candle.low > candle.open and candle.low > candle.close:
            warnings.append(f"Low ({candle.low}) above both open and close")

        # 3. Check for future/in-progress and stale data (authoritative path).
        # Aggregated bars carry their exchange bar-start as exchange_ts_ns; a
        # validated deterministic close is the lawful freshness reference.
        if current_time_ns is not None:
            freshness_ts_ns = candle.exchange_ts_ns
            recorded_close = getattr(candle, "candle_close_ts_ns", None)
            if recorded_close is not None:
                if isinstance(recorded_close, bool) or not isinstance(recorded_close, int):
                    errors.append("Candle close timestamp must be an integer nanosecond value")
                else:
                    timeframe_ns = self._timeframe_ns(getattr(candle, "timeframe", None))
                    expected_close = candle.exchange_ts_ns + timeframe_ns if timeframe_ns is not None else None
                    if expected_close is None or recorded_close != expected_close:
                        errors.append("Candle close timestamp is inconsistent with exchange start/timeframe")
                    elif getattr(candle, "candle_closed_at_receive", None) is not True:
                        errors.append("Candle was not closed at transport receipt")
                    else:
                        freshness_ts_ns = recorded_close
            if freshness_ts_ns > current_time_ns:
                errors.append("Future or in-progress candle timestamp")
            elif self._is_stale_ns(freshness_ts_ns, current_time_ns):
                age_sec = (current_time_ns - freshness_ts_ns) / 1_000_000_000.0
                errors.append(f"Stale candle: {age_sec:.1f}s old (threshold {self.stale_threshold_seconds}s)")
        else:
            # Telemetry fallback — wall-clock permitted
            current_time = datetime.utcnow()
            candle_age = (current_time - candle.timestamp).total_seconds()
            if candle_age > self.stale_threshold_seconds:
                warnings.append(f"Candle age (telemetry): {candle_age:.1f}s old")

        # 4. Check ordering against previous candle
        last_timestamp_ns = self._last_timestamps_ns.get(candle.symbol)
        if last_timestamp_ns is not None:
            if candle.exchange_ts_ns <= last_timestamp_ns:
                errors.append(f"Out of order: {candle.exchange_ts_ns} <= last {last_timestamp_ns}")
            time_diff_ns = candle.exchange_ts_ns - last_timestamp_ns
            time_diff_sec = time_diff_ns / 1_000_000_000.0
            if time_diff_sec < 0:
                errors.append(f"Negative time diff: {time_diff_sec}s")
            if time_diff_sec > 300:  # 5 minute gap
                warnings.append(f"Large time gap: {time_diff_sec:.1f}s")

        # Update last timestamp if valid enough
        if not errors:
            self._last_timestamps_ns[candle.symbol] = candle.exchange_ts_ns

        return ValidationResult(
            is_valid=len(errors) == 0,
            error="; ".join(errors) if errors else None,
            warnings=warnings
        )

    def validate_candles(
        self,
        candles: List[Candle],
        current_time_ns: Optional[int] = None
    ) -> ValidationResult:
        """
        Validate a list of candles.

        Args:
            candles: List of candles to validate
            current_time_ns: Current time in nanoseconds (authoritative)

        Returns:
            ValidationResult with aggregated status
        """
        all_errors = []
        all_warnings = []

        for i, candle in enumerate(candles):
            result = self.validate_candle(candle, current_time_ns)
            if not result.is_valid:
                all_errors.append(f"Candle {i}: {result.error}")
            all_warnings.extend(result.warnings)

        return ValidationResult(
            is_valid=len(all_errors) == 0,
            error="; ".join(all_errors) if all_errors else None,
            warnings=all_warnings
        )

    def validate_order_book(
        self,
        order_book: OrderBookSnapshot,
        current_time_ns: Optional[int] = None
    ) -> ValidationResult:
        """
        Validate an order book snapshot.

        Args:
            order_book: Order book to validate
            current_time_ns: Current time in nanoseconds (authoritative)

        Returns:
            ValidationResult with status and errors/warnings
        """
        errors = []
        warnings = []

        # 1. Check for stale data (authoritative path)
        if current_time_ns is not None:
            if order_book.exchange_ts_ns > current_time_ns:
                errors.append("Future order book timestamp")
            elif self._is_stale_ns(order_book.exchange_ts_ns, current_time_ns):
                age_sec = (current_time_ns - order_book.exchange_ts_ns) / 1_000_000_000.0
                errors.append(f"Stale order book: {age_sec:.1f}s old")
        else:
            # Telemetry fallback — wall-clock permitted
            current_time = datetime.utcnow()
            book_age = (current_time - order_book.timestamp).total_seconds()
            if book_age > self.stale_threshold_seconds:
                warnings.append(f"Order book age (telemetry): {book_age:.1f}s old")

        # 2. Check bids are sorted descending
        if order_book.bids:
            for i in range(1, len(order_book.bids)):
                if order_book.bids[i][0] >= order_book.bids[i-1][0]:
                    errors.append(f"Bids not descending at index {i}: {order_book.bids[i-1][0]} <= {order_book.bids[i][0]}")

        # 3. Check asks are sorted ascending
        if order_book.asks:
            for i in range(1, len(order_book.asks)):
                if order_book.asks[i][0] <= order_book.asks[i-1][0]:
                    errors.append(f"Asks not ascending at index {i}: {order_book.asks[i-1][0]} >= {order_book.asks[i][0]}")

        # 4. Check spread is positive
        if order_book.bids and order_book.asks:
            if order_book.bids[0][0] >= order_book.asks[0][0]:
                errors.append(f"Negative spread: bid {order_book.bids[0][0]} >= ask {order_book.asks[0][0]}")

        # 5. Check for negative prices or sizes
        for bid_price, bid_size in order_book.bids:
            if bid_price <= 0:
                errors.append(f"Bid price <= 0: {bid_price}")
            if bid_size <= 0:
                warnings.append(f"Bid size <= 0: {bid_size}")
        for ask_price, ask_size in order_book.asks:
            if ask_price <= 0:
                errors.append(f"Ask price <= 0: {ask_price}")
            if ask_size <= 0:
                warnings.append(f"Ask size <= 0: {ask_size}")

        return ValidationResult(
            is_valid=len(errors) == 0,
            error="; ".join(errors) if errors else None,
            warnings=warnings
        )

    def is_stale(self, timestamp: datetime, current_time: Optional[datetime] = None) -> bool:
        """
        Check if a timestamp is stale (telemetry only).
        
        WARNING: This method uses wall-clock datetime. Use only for monitoring.
        For authoritative staleness checks, use exchange_ts_ns with current_time_ns.
        """
        if current_time is None:
            current_time = datetime.utcnow()
        age = (current_time - timestamp).total_seconds()
        return age > self.stale_threshold_seconds

    def get_stale_status(self, symbol: str, current_time_ns: Optional[int] = None) -> Tuple[bool, float]:
        """
        Get stale status for a symbol.

        Args:
            symbol: Trading symbol
            current_time_ns: Current time in nanoseconds (authoritative)

        Returns:
            Tuple of (is_stale, age_seconds)
        """
        last_ts_ns = self._last_timestamps_ns.get(symbol)
        if last_ts_ns is None:
            return True, float('inf')

        if current_time_ns is not None:
            age_ns = current_time_ns - last_ts_ns
            age_sec = age_ns / 1_000_000_000.0
            return age_sec > self.stale_threshold_seconds, age_sec

        # Telemetry fallback
        return True, float('inf')

    def reset_symbol(self, symbol: str) -> None:
        """Reset tracking for a symbol."""
        if symbol in self._last_timestamps_ns:
            del self._last_timestamps_ns[symbol]
            logger.debug(f"Reset validator for {symbol}")

    def reset_all(self) -> None:
        """Reset all tracking."""
        self._last_timestamps_ns.clear()
        logger.info("Reset all validators")

    def validate_price(self, price: float, symbol: str) -> ValidationResult:
        """
        Validate a single price.

        Args:
            price: Price to validate
            symbol: Symbol for context

        Returns:
            ValidationResult
        """
        errors = []
        if price <= 0:
            errors.append(f"Price <= 0: {price}")
        if price > 1e9:  # $1 billion sanity check
            errors.append(f"Price > $1B: {price}")

        return ValidationResult(
            is_valid=len(errors) == 0,
            error="; ".join(errors) if errors else None
        )

    def validate_quantity(self, quantity: float, symbol: str) -> ValidationResult:
        """
        Validate a trade quantity.

        Args:
            quantity: Quantity to validate
            symbol: Symbol for context

        Returns:
            ValidationResult
        """
        errors = []
        if quantity <= 0:
            errors.append(f"Quantity <= 0: {quantity}")
        if quantity > 1e9:  # Sanity check
            errors.append(f"Quantity > 1B: {quantity}")

        return ValidationResult(
            is_valid=len(errors) == 0,
            error="; ".join(errors) if errors else None
        )

    def validate_ohlcv_consistency(self, candle: Candle) -> ValidationResult:
        """
        Validate OHLCV consistency (high >= open/close >= low).

        Args:
            candle: Candle to validate

        Returns:
            ValidationResult
        """
        errors = []
        if candle.high < candle.open:
            errors.append(f"High ({candle.high}) < Open ({candle.open})")
        if candle.high < candle.close:
            errors.append(f"High ({candle.high}) < Close ({candle.close})")
        if candle.low > candle.open:
            errors.append(f"Low ({candle.low}) > Open ({candle.open})")
        if candle.low > candle.close:
            errors.append(f"Low ({candle.low}) > Close ({candle.close})")

        return ValidationResult(
            is_valid=len(errors) == 0,
            error="; ".join(errors) if errors else None
        )
