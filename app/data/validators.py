"""
Validators - Data Integrity and Stale Data Checks
Validates incoming market data for integrity, ordering, and staleness.
Prevents trading on corrupted or stale data.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional, Tuple, Dict, Any
from dataclasses import dataclass

from app.models import Candle, OrderBookSnapshot
from app.constants import STALE_DATA_THRESHOLD_SECONDS

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of data validation."""
    is_valid: bool
    error: Optional[str] = None
    warnings: List[str] = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


class DataValidator:
    """
    Validates incoming market data for integrity and staleness.
    Checks: stale bars, ordering, duplicates, malformed values, impossible OHLCV.
    """

    def __init__(self, stale_threshold_seconds: int = STALE_DATA_THRESHOLD_SECONDS):
        """
        Initialize validator.

        Args:
            stale_threshold_seconds: Seconds before data is considered stale
        """
        self.stale_threshold_seconds = stale_threshold_seconds
        self._last_timestamps: Dict[str, datetime] = {}

    def validate_candle(self, candle: Candle, current_time: Optional[datetime] = None) -> ValidationResult:
        """
        Validate a single candle.

        Args:
            candle: Candle to validate
            current_time: Current time for staleness check

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

        # 3. Check for stale data
        if current_time is None:
            current_time = datetime.utcnow()
        candle_age = (current_time - candle.timestamp).total_seconds()
        if candle_age > self.stale_threshold_seconds:
            errors.append(f"Stale candle: {candle_age:.1f}s old (threshold {self.stale_threshold_seconds}s)")

        # 4. Check ordering against previous candle
        last_timestamp = self._last_timestamps.get(candle.symbol)
        if last_timestamp:
            if candle.timestamp <= last_timestamp:
                errors.append(f"Out of order: {candle.timestamp} <= last {last_timestamp}")
            time_diff = (candle.timestamp - last_timestamp).total_seconds()
            if time_diff < 0:
                errors.append(f"Negative time diff: {time_diff}s")
            if time_diff > 300:  # 5 minute gap
                warnings.append(f"Large time gap: {time_diff:.1f}s")

        # Update last timestamp if valid enough
        if not errors:
            self._last_timestamps[candle.symbol] = candle.timestamp

        return ValidationResult(
            is_valid=len(errors) == 0,
            error="; ".join(errors) if errors else None,
            warnings=warnings
        )

    def validate_candles(self, candles: List[Candle], current_time: Optional[datetime] = None) -> ValidationResult:
        """
        Validate a list of candles.

        Args:
            candles: List of candles to validate
            current_time: Current time for staleness check

        Returns:
            ValidationResult with aggregated status
        """
        all_errors = []
        all_warnings = []

        for i, candle in enumerate(candles):
            result = self.validate_candle(candle, current_time)
            if not result.is_valid:
                all_errors.append(f"Candle {i}: {result.error}")
            all_warnings.extend(result.warnings)

        return ValidationResult(
            is_valid=len(all_errors) == 0,
            error="; ".join(all_errors) if all_errors else None,
            warnings=all_warnings
        )

    def validate_order_book(self, order_book: OrderBookSnapshot, current_time: Optional[datetime] = None) -> ValidationResult:
        """
        Validate an order book snapshot.

        Args:
            order_book: Order book to validate
            current_time: Current time for staleness check

        Returns:
            ValidationResult with status and errors/warnings
        """
        errors = []
        warnings = []

        # 1. Check for stale data
        if current_time is None:
            current_time = datetime.utcnow()
        book_age = (current_time - order_book.timestamp).total_seconds()
        if book_age > self.stale_threshold_seconds:
            errors.append(f"Stale order book: {book_age:.1f}s old")

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
        Check if a timestamp is stale.

        Args:
            timestamp: Timestamp to check
            current_time: Current time

        Returns:
            True if stale
        """
        if current_time is None:
            current_time = datetime.utcnow()
        age = (current_time - timestamp).total_seconds()
        return age > self.stale_threshold_seconds

    def get_stale_status(self, symbol: str, current_time: Optional[datetime] = None) -> Tuple[bool, float]:
        """
        Get stale status for a symbol.

        Args:
            symbol: Trading symbol
            current_time: Current time

        Returns:
            Tuple of (is_stale, age_seconds)
        """
        if current_time is None:
            current_time = datetime.utcnow()

        last_ts = self._last_timestamps.get(symbol)
        if last_ts is None:
            return True, float('inf')

        age = (current_time - last_ts).total_seconds()
        return age > self.stale_threshold_seconds, age

    def reset_symbol(self, symbol: str) -> None:
        """
        Reset tracking for a symbol.

        Args:
            symbol: Trading symbol
        """
        if symbol in self._last_timestamps:
            del self._last_timestamps[symbol]
            logger.debug(f"Reset validator for {symbol}")

    def reset_all(self) -> None:
        """Reset all tracking."""
        self._last_timestamps.clear()
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