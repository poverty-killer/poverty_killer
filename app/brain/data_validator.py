"""
Data Continuity Validator - The "Oracle Shield"
Ensures market data is continuous before feeding to TPE.
Detects gaps, out-of-order packets, and stale data.
If data is compromised, returns NaN to prevent false topological voids.

FIXED:
- Sequence ID syncs even after gap detection (prevents infinite rejection loop)
- Timestamp syncs even after gap detection (recovery symmetry)
- Heartbeat tracking isolated to WebSocket ping/pong frames
- Proper recovery counter after gaps
- UTC-explicit datetime boundary conversion
- Stronger sequence ID validation (int, positive)
"""

import logging
import math
import re
from typing import Optional, Tuple, Dict, Any
from datetime import datetime, timezone
from dataclasses import dataclass

from app.utils.time_utils import now_ns

logger = logging.getLogger(__name__)

# Symbol validation: alphanumeric, hyphen, period, underscore, slash (Kraken v2 canonical: BTC/USD)
_SYMBOL_PATTERN = re.compile(r"^[A-Za-z0-9\-\._/]+$")


def _datetime_to_ns(dt: datetime) -> int:
    """Convert datetime to nanoseconds since epoch (UTC, replay‑safe)."""
    # Ensure UTC: if naive, assume UTC; if aware, convert to UTC
    if dt.tzinfo is None:
        # Naive datetime - assume UTC (standard for exchange timestamps)
        dt_utc = dt.replace(tzinfo=timezone.utc)
    else:
        # Aware datetime - convert to UTC
        dt_utc = dt.astimezone(timezone.utc)
    
    # Get POSIX timestamp (seconds since epoch in UTC)
    return int(dt_utc.timestamp() * 1_000_000_000)


def _ns_to_datetime(ns: int) -> datetime:
    """Convert nanoseconds since epoch to UTC datetime (boundary output only)."""
    # Always return UTC-aware datetime
    return datetime.fromtimestamp(ns / 1_000_000_000, tz=timezone.utc)


@dataclass
class ContinuityState:
    """Tracks continuity for a single symbol."""
    last_sequence_id: Optional[int] = None
    last_timestamp_ns: Optional[int] = None
    last_websocket_heartbeat_ns: Optional[int] = None
    gap_detected: bool = False
    gap_start_ns: Optional[int] = None
    consecutive_good: int = 0
    last_valid_data_ns: Optional[int] = None


class DataContinuityValidator:
    """
    Data Continuity Validator - The "Oracle Shield".
    
    Validates incoming market data for:
    - Sequence ID monotonicity (no gaps)
    - Timestamp progression (no backwards time)
    - Stale data detection
    
    Heartbeat tracking is isolated to WebSocket ping/pong frames.
    Recovery after gaps: syncs to new sequence/timestamp and counts consecutive good packets.
    
    INTERNAL TIMING AUTHORITY: nanoseconds (via now_ns()).
    Datetime is used only at input/output boundaries (explicit UTC conversion).
    """

    def __init__(
        self,
        max_sequence_gap: int = 1,
        max_timestamp_gap_sec: float = 2.0,
        max_stale_age_sec: float = 5.0,
        recovery_required_good: int = 3,
        websocket_heartbeat_timeout_sec: float = 30.0
    ):
        """
        Initialize data continuity validator.

        Args:
            max_sequence_gap: Maximum allowed sequence ID gap (must be >= 1)
            max_timestamp_gap_sec: Maximum allowed timestamp gap in seconds (must be > 0)
            max_stale_age_sec: Max age before data is considered stale (must be > 0)
            recovery_required_good: Number of good packets needed after gap (must be >= 1)
            websocket_heartbeat_timeout_sec: Timeout for WebSocket heartbeats (must be > 0)
        """
        # Strong constructor guards
        if max_sequence_gap < 1:
            raise ValueError(f"max_sequence_gap must be >= 1, got {max_sequence_gap}")
        if not math.isfinite(max_timestamp_gap_sec) or max_timestamp_gap_sec <= 0.0:
            raise ValueError(f"max_timestamp_gap_sec must be positive finite, got {max_timestamp_gap_sec}")
        if not math.isfinite(max_stale_age_sec) or max_stale_age_sec <= 0.0:
            raise ValueError(f"max_stale_age_sec must be positive finite, got {max_stale_age_sec}")
        if recovery_required_good < 1:
            raise ValueError(f"recovery_required_good must be >= 1, got {recovery_required_good}")
        if not math.isfinite(websocket_heartbeat_timeout_sec) or websocket_heartbeat_timeout_sec <= 0.0:
            raise ValueError(f"websocket_heartbeat_timeout_sec must be positive finite, got {websocket_heartbeat_timeout_sec}")

        self.max_sequence_gap = max_sequence_gap
        self.max_timestamp_gap_ns = int(max_timestamp_gap_sec * 1_000_000_000)
        self.max_stale_age_ns = int(max_stale_age_sec * 1_000_000_000)
        self.recovery_required_good = recovery_required_good
        self.websocket_heartbeat_timeout_ns = int(websocket_heartbeat_timeout_sec * 1_000_000_000)

        self._state: Dict[str, ContinuityState] = {}

        logger.info(f"DataContinuityValidator initialized: max_gap={max_sequence_gap}, "
                   f"max_timestamp_gap={max_timestamp_gap_sec}s, "
                   f"stale_age={max_stale_age_sec}s, "
                   f"recovery_required={recovery_required_good}")

    def validate_numeric(
        self,
        value: float,
        name: str = "value",
        allow_nan: bool = False,
        allow_inf: bool = False,
        min_val: Optional[float] = None,
        max_val: Optional[float] = None
    ) -> Tuple[bool, str]:
        """
        Validate a numeric value with configurable analytical checks.
        
        Args:
            value: The numeric value to validate
            name: Name of the value for error messages
            allow_nan: Whether NaN is allowed (default False)
            allow_inf: Whether infinity is allowed (default False)
            min_val: Optional minimum allowed value (inclusive)
            max_val: Optional maximum allowed value (inclusive)
            
        Returns:
            Tuple of (is_valid, reason)
        """
        # NaN check
        if math.isnan(value):
            if not allow_nan:
                return False, f"{name} is NaN"
            return True, "ok"
        
        # Infinity check
        if math.isinf(value):
            if not allow_inf:
                return False, f"{name} is infinite"
            return True, "ok"
        
        # Range checks
        if min_val is not None and value < min_val:
            return False, f"{name} ({value}) < minimum ({min_val})"
        if max_val is not None and value > max_val:
            return False, f"{name} ({value}) > maximum ({max_val})"
        
        return True, "ok"

    def validate_price_volume(
        self,
        price: float,
        volume: float,
        allow_zero_volume: bool = False
    ) -> Tuple[bool, str]:
        """
        Validate price and volume for market data.
        
        Args:
            price: Price (must be > 0 and finite)
            volume: Volume (must be >= 0 and finite; zero allowed if allow_zero_volume=True)
            allow_zero_volume: Whether volume = 0 is acceptable
            
        Returns:
            Tuple of (is_valid, reason)
        """
        # Validate price
        price_valid, price_reason = self.validate_numeric(
            price, name="price", allow_nan=False, allow_inf=False, min_val=0.0
        )
        if not price_valid:
            return False, price_reason
        if price <= 0.0:
            return False, f"price must be > 0: {price}"
        
        # Validate volume
        volume_min = 0.0 if allow_zero_volume else 1e-12  # tiny positive epsilon
        volume_valid, volume_reason = self.validate_numeric(
            volume, name="volume", allow_nan=False, allow_inf=False, min_val=volume_min
        )
        if not volume_valid:
            return False, volume_reason
        
        return True, "ok"

    def _validate_symbol(self, symbol: str) -> Tuple[bool, str]:
        """Validate symbol format."""
        if not symbol or not isinstance(symbol, str):
            return False, f"symbol must be non‑empty string, got {type(symbol)}"
        if not _SYMBOL_PATTERN.match(symbol):
            return False, f"symbol contains invalid characters: {symbol}"
        if len(symbol) > 32:
            return False, f"symbol too long (max 32): {symbol}"
        return True, "ok"

    def _get_state(self, symbol: str) -> ContinuityState:
        """Get or create state for symbol after validating symbol format."""
        symbol_valid, symbol_reason = self._validate_symbol(symbol)
        if not symbol_valid:
            raise ValueError(f"Invalid symbol: {symbol_reason}")
        
        if symbol not in self._state:
            self._state[symbol] = ContinuityState()
        return self._state[symbol]

    def validate_sequence(
        self,
        symbol: str,
        sequence_id: Optional[int],
        timestamp: datetime
    ) -> Tuple[bool, str]:
        """
        Validate sequence ID continuity.
        CRITICAL FIX: Updates last_sequence_id even when gap detected
        to allow recovery counting on subsequent packets.

        Args:
            symbol: Trading symbol
            sequence_id: Exchange sequence ID (if available)
            timestamp: Message timestamp (datetime, converted to ns internally)

        Returns:
            Tuple of (is_valid, reason)
        """
        state = self._get_state(symbol)

        # If no sequence ID provided, skip sequence check
        if sequence_id is None:
            return True, "no_sequence_id"

        # STRONGER VALIDATION: type and positivity
        if not isinstance(sequence_id, int):
            return False, f"sequence_id must be int, got {type(sequence_id)}"
        if sequence_id <= 0:
            return False, f"sequence_id must be > 0, got {sequence_id}"

        # Check monotonicity and gap
        if state.last_sequence_id is not None:
            if sequence_id <= state.last_sequence_id:
                return False, f"sequence_id decreased: {sequence_id} <= {state.last_sequence_id}"

            gap = sequence_id - state.last_sequence_id
            
            # Gap detected
            if gap > self.max_sequence_gap:
                state.gap_detected = True
                state.gap_start_ns = _datetime_to_ns(timestamp)
                state.consecutive_good = 0
                
                # CRITICAL FIX: Update to current sequence ID so future packets
                # are compared against the new baseline, not the old one
                state.last_sequence_id = sequence_id
                
                return False, f"sequence_gap: {gap} > {self.max_sequence_gap}"

        # Update state (no gap, or first packet)
        state.last_sequence_id = sequence_id
        return True, "ok"

    def validate_timestamp(
        self,
        symbol: str,
        timestamp: datetime
    ) -> Tuple[bool, str]:
        """
        Validate timestamp progression.
        CRITICAL FIX: Updates last_timestamp_ns even when gap detected
        for recovery symmetry with sequence-gap behavior.

        Args:
            symbol: Trading symbol
            timestamp: Message timestamp (datetime, converted to ns internally)

        Returns:
            Tuple of (is_valid, reason)
        """
        state = self._get_state(symbol)
        timestamp_ns = _datetime_to_ns(timestamp)

        if state.last_timestamp_ns is not None:
            # Check for time reversal
            if timestamp_ns < state.last_timestamp_ns:
                return False, f"timestamp reversal: {timestamp} < {_ns_to_datetime(state.last_timestamp_ns)}"

            # Check for excessive gap
            gap_ns = timestamp_ns - state.last_timestamp_ns
            if gap_ns > self.max_timestamp_gap_ns:
                state.gap_detected = True
                state.gap_start_ns = timestamp_ns
                state.consecutive_good = 0
                # CRITICAL FIX: Update baseline timestamp for recovery symmetry
                state.last_timestamp_ns = timestamp_ns
                gap_sec = gap_ns / 1_000_000_000
                return False, f"timestamp_gap: {gap_sec:.2f}s > {self.max_timestamp_gap_ns / 1_000_000_000}s"

        # Update state
        state.last_timestamp_ns = timestamp_ns
        return True, "ok"

    def validate_staleness(
        self,
        symbol: str,
        timestamp: datetime,
        current_time: Optional[datetime] = None
    ) -> Tuple[bool, str]:
        """
        Validate data staleness.

        Args:
            symbol: Trading symbol
            timestamp: Message timestamp (datetime, converted to ns internally)
            current_time: Current time (datetime, defaults to now_ns())

        Returns:
            Tuple of (is_valid, reason)
        """
        timestamp_ns = _datetime_to_ns(timestamp)
        current_ns = now_ns() if current_time is None else _datetime_to_ns(current_time)

        age_ns = current_ns - timestamp_ns
        if age_ns > self.max_stale_age_ns:
            age_sec = age_ns / 1_000_000_000
            return False, f"stale_data: {age_sec:.1f}s > {self.max_stale_age_ns / 1_000_000_000}s"

        return True, "ok"

    # ============================================
    # WEBSOCKET HEARTBEAT (Isolated - No Trade Data)
    # ============================================

    def record_websocket_heartbeat(self, symbol: str) -> None:
        """
        Record a WebSocket ping/pong heartbeat.
        This is called by the WebSocket client on explicit ping/pong frames,
        NOT on trade data. Isolated from trade volume.
        """
        state = self._get_state(symbol)
        state.last_websocket_heartbeat_ns = now_ns()
        logger.debug(f"WebSocket heartbeat recorded for {symbol}")

    def is_websocket_alive(self, symbol: str) -> bool:
        """
        Check if WebSocket connection is alive based on heartbeats.

        Args:
            symbol: Trading symbol

        Returns:
            True if heartbeat received within timeout
        """
        state = self._get_state(symbol)
        if state.last_websocket_heartbeat_ns is None:
            return True  # No heartbeats yet, assume alive

        age_ns = now_ns() - state.last_websocket_heartbeat_ns
        return age_ns <= self.websocket_heartbeat_timeout_ns

    # ============================================
    # DATA HEALTH (Separate from Heartbeat)
    # ============================================

    def record_data(self, symbol: str, timestamp: datetime) -> None:
        """Record that valid data was received."""
        state = self._get_state(symbol)
        state.last_valid_data_ns = _datetime_to_ns(timestamp)

    def mark_good(self, symbol: str) -> None:
        """
        Mark a good data point (used for recovery counting).
        Only called after all validations pass.
        """
        state = self._get_state(symbol)
        if state.gap_detected:
            state.consecutive_good += 1
            if state.consecutive_good >= self.recovery_required_good:
                state.gap_detected = False
                logger.info(f"Data feed recovered for {symbol} after {state.consecutive_good} good packets")
        else:
            state.consecutive_good = 0

    def is_data_healthy(self, symbol: str) -> bool:
        """
        Check if symbol's data feed is healthy (no gaps, not stale).

        Args:
            symbol: Trading symbol

        Returns:
            True if data is continuous and healthy
        """
        state = self._get_state(symbol)

        # Check if in recovery mode
        if state.gap_detected:
            return False

        # Check last valid data
        if state.last_valid_data_ns:
            age_ns = now_ns() - state.last_valid_data_ns
            if age_ns > self.max_stale_age_ns:
                return False

        return True

    def health_snapshot(
        self,
        symbol: str,
        *,
        current_ns: Optional[int] = None,
        latest_book_ts_ns: Optional[int] = None,
        latest_candle_ts_ns: Optional[int] = None,
        source_type: str = "unknown",
        observed_symbol: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Return machine-readable data-health evidence without mutating state.

        Execution admission uses this stricter snapshot so missing timestamp
        truth cannot be converted into implicit health.
        """
        current_ns = int(current_ns or now_ns())
        source = str(source_type or "unknown").lower()
        snapshot: Dict[str, Any] = {
            "symbol": symbol,
            "gap_detected": None,
            "last_valid_data_ns": None,
            "last_valid_data_age_ms": None,
            "max_stale_age_ms": self.max_stale_age_ns / 1_000_000.0,
            "latest_book_ts_ns": latest_book_ts_ns,
            "latest_candle_ts_ns": latest_candle_ts_ns,
            "data_source_type": source,
            "data_health_reason_code": "DATA_HEALTH_UNKNOWN",
            "data_healthy": False,
        }

        if observed_symbol is not None and str(observed_symbol) != str(symbol):
            snapshot["observed_symbol"] = observed_symbol
            snapshot["data_health_reason_code"] = "DATA_SYMBOL_MISMATCH"
            return snapshot

        if source in {"backfill", "replay", "synthetic", "observe_only"}:
            snapshot["data_health_reason_code"] = "DATA_BACKFILL_OBSERVE_ONLY"
            return snapshot

        try:
            state = self._get_state(symbol)
        except ValueError:
            snapshot["data_health_reason_code"] = "DATA_SYMBOL_MISMATCH"
            return snapshot

        snapshot["gap_detected"] = bool(state.gap_detected)
        snapshot["last_valid_data_ns"] = state.last_valid_data_ns

        if state.gap_detected:
            snapshot["data_health_reason_code"] = "DATA_GAP_ACTIVE"
            return snapshot

        if state.last_valid_data_ns is None:
            snapshot["data_health_reason_code"] = "DATA_TIMESTAMP_MISSING"
            return snapshot

        age_ns = max(0, current_ns - state.last_valid_data_ns)
        snapshot["last_valid_data_age_ms"] = age_ns / 1_000_000.0
        if age_ns > self.max_stale_age_ns:
            snapshot["data_health_reason_code"] = "DATA_STALE"
            return snapshot

        snapshot["data_health_reason_code"] = "DATA_HEALTHY"
        snapshot["data_healthy"] = True
        return snapshot

    def validate(
        self,
        symbol: str,
        timestamp: datetime,
        sequence_id: Optional[int] = None,
        current_time: Optional[datetime] = None
    ) -> Tuple[bool, str]:
        """
        Full validation pipeline for market data.

        Args:
            symbol: Trading symbol
            timestamp: Message timestamp
            sequence_id: Exchange sequence ID (if available)
            current_time: Current time (defaults to now_ns())

        Returns:
            Tuple of (is_valid, reason)
        """
        # Check staleness first (most critical)
        is_stale, stale_reason = self.validate_staleness(symbol, timestamp, current_time)
        if not is_stale:
            return False, stale_reason

        # Check timestamp progression
        is_ts_valid, ts_reason = self.validate_timestamp(symbol, timestamp)
        if not is_ts_valid:
            return False, ts_reason

        # Check sequence ID (will update last_sequence_id even on gap)
        is_seq_valid, seq_reason = self.validate_sequence(symbol, sequence_id, timestamp)
        if not is_seq_valid:
            return False, seq_reason

        # All checks passed - mark good for recovery
        self.mark_good(symbol)
        self.record_data(symbol, timestamp)

        return True, "ok"

    def get_continuity_status(self, symbol: str) -> Dict[str, Any]:
        """Get continuity status for a symbol."""
        state = self._get_state(symbol)
        return {
            "symbol": symbol,
            "is_data_healthy": self.is_data_healthy(symbol),
            "is_websocket_alive": self.is_websocket_alive(symbol),
            "last_sequence_id": state.last_sequence_id,
            "last_timestamp": _ns_to_datetime(state.last_timestamp_ns).isoformat() if state.last_timestamp_ns else None,
            "last_websocket_heartbeat": _ns_to_datetime(state.last_websocket_heartbeat_ns).isoformat() if state.last_websocket_heartbeat_ns else None,
            "last_valid_data": _ns_to_datetime(state.last_valid_data_ns).isoformat() if state.last_valid_data_ns else None,
            "gap_detected": state.gap_detected,
            "consecutive_good": state.consecutive_good,
            "recovery_required": self.recovery_required_good
        }

    def reset(self, symbol: str) -> None:
        """Reset state for a symbol."""
        if symbol in self._state:
            del self._state[symbol]
        logger.info(f"Reset continuity validator for {symbol}")

    def reset_all(self) -> None:
        """Reset all state."""
        self._state.clear()
        logger.info("Reset all continuity validators")
