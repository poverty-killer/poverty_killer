"""
Time Utilities for Sovereign Trading System
Master Rebuild Pack v3 Final - Canonical Timing Authority

All system timestamps use integer nanoseconds since Unix epoch.
Provides deterministic time source that can be overridden during replay.

Replay Purity Rules (RP-01):
- During normal operation, use now_ns() for current time
- During replay, set_replay_time_ns() overrides the time source
- now_ns() must be used for all time-dependent decisions
- No module may call time.time_ns() directly

Thread Safety Note:
This module is not thread-safe for concurrent replay time manipulation.
Replay time should be set/advanced/cleared from a single thread only.
"""

import time
from typing import Optional, Tuple, Type
from types import TracebackType


# Nanosecond conversion constants
NS_PER_SECOND = 1_000_000_000
NS_PER_MS = 1_000_000
NS_PER_US = 1_000

# Maximum reasonable timestamp (2^63-1 nanoseconds ≈ year 2242)
# Used to catch obviously erroneous timestamps, not to restrict legitimate future timestamps
MAX_REASONABLE_TIMESTAMP_NS = 2**63 - 1  # ~9.22e18 ns

# Replay override state (private module variable)
_replay_time_ns: Optional[int] = None


# ============================================
# CORE TIME FUNCTIONS
# ============================================

def now_ns() -> int:
    """
    Get current time in nanoseconds since Unix epoch.
    
    In replay mode, returns the injected replay time.
    In normal mode, returns system wall-clock time.
    
    Returns:
        Nanosecond timestamp
    
    Note:
        This function is the SOLE canonical timing authority for the system.
        All time-dependent decisions must use now_ns().
        No module may call time.time_ns() directly.
    """
    if _replay_time_ns is not None:
        return _replay_time_ns
    return time.time_ns()


def set_replay_time_ns(timestamp_ns: int) -> None:
    """
    Set replay time override.
    
    When set, now_ns() returns this value instead of wall-clock time.
    Use for deterministic replay of recorded sessions.
    
    Args:
        timestamp_ns: Replay timestamp in nanoseconds since Unix epoch
    
    Raises:
        ValueError: If timestamp_ns is negative or exceeds MAX_REASONABLE_TIMESTAMP_NS
    """
    global _replay_time_ns
    if timestamp_ns < 0:
        raise ValueError(f"timestamp_ns cannot be negative: {timestamp_ns}")
    if timestamp_ns > MAX_REASONABLE_TIMESTAMP_NS:
        raise ValueError(
            f"timestamp_ns exceeds reasonable maximum ({MAX_REASONABLE_TIMESTAMP_NS}): {timestamp_ns}"
        )
    _replay_time_ns = timestamp_ns


def advance_replay_time_ns(delta_ns: int) -> int:
    """
    Advance replay time by delta nanoseconds.
    
    Only valid when replay mode is active.
    
    Args:
        delta_ns: Nanoseconds to advance (must be positive; zero is allowed but has no effect)
    
    Returns:
        New replay timestamp
    
    Raises:
        RuntimeError: If replay mode is not active
        ValueError: If delta_ns is negative
    """
    global _replay_time_ns
    if _replay_time_ns is None:
        raise RuntimeError("Cannot advance time when replay mode is not active")
    if delta_ns < 0:
        raise ValueError(f"delta_ns cannot be negative: {delta_ns}")
    
    _replay_time_ns += delta_ns
    return _replay_time_ns


def clear_replay_time() -> None:
    """
    Clear replay time override.
    
    Returns to wall-clock time for all subsequent calls to now_ns().
    """
    global _replay_time_ns
    _replay_time_ns = None


def is_replay_mode() -> bool:
    """
    Check if replay mode is active.
    
    Returns:
        True if replay time is set, False otherwise
    """
    return _replay_time_ns is not None


# ============================================
# CONVERSION HELPERS (Boundary Use Only)
# ============================================

def seconds_to_ns(seconds: int) -> int:
    """
    Convert seconds to nanoseconds.
    
    This is a boundary conversion helper for config/input values.
    For core replay timestamps, use integer nanoseconds directly.
    
    Args:
        seconds: Seconds (integer)
    
    Returns:
        Nanoseconds (integer)
    
    Raises:
        ValueError: If seconds is negative
    """
    if seconds < 0:
        raise ValueError(f"seconds cannot be negative: {seconds}")
    return seconds * NS_PER_SECOND


def ms_to_ns(ms: int) -> int:
    """
    Convert milliseconds to nanoseconds.
    
    This is a boundary conversion helper for config/input values.
    For core replay timestamps, use integer nanoseconds directly.
    
    Args:
        ms: Milliseconds (integer)
    
    Returns:
        Nanoseconds (integer)
    
    Raises:
        ValueError: If ms is negative
    """
    if ms < 0:
        raise ValueError(f"ms cannot be negative: {ms}")
    return ms * NS_PER_MS


def us_to_ns(us: int) -> int:
    """
    Convert microseconds to nanoseconds.
    
    This is a boundary conversion helper for config/input values.
    For core replay timestamps, use integer nanoseconds directly.
    
    Args:
        us: Microseconds (integer)
    
    Returns:
        Nanoseconds (integer)
    
    Raises:
        ValueError: If us is negative
    """
    if us < 0:
        raise ValueError(f"us cannot be negative: {us}")
    return us * NS_PER_US


def ns_to_seconds(ns: int) -> float:
    """
    Convert nanoseconds to seconds (for display only).
    
    Warning: Returns float, which may lose precision for large values.
    Use only for display/logging, never for core timing calculations.
    
    Args:
        ns: Nanoseconds
    
    Returns:
        Seconds as float (display only)
    """
    return ns / NS_PER_SECOND


def ns_to_ms(ns: int) -> float:
    """
    Convert nanoseconds to milliseconds (for display only).
    
    Warning: Returns float, which may lose precision for large values.
    Use only for display/logging, never for core timing calculations.
    
    Args:
        ns: Nanoseconds
    
    Returns:
        Milliseconds as float (display only)
    """
    return ns / NS_PER_MS


def ns_to_us(ns: int) -> float:
    """
    Convert nanoseconds to microseconds (for display only).
    
    Warning: Returns float, which may lose precision for large values.
    Use only for display/logging, never for core timing calculations.
    
    Args:
        ns: Nanoseconds
    
    Returns:
        Microseconds as float (display only)
    """
    return ns / NS_PER_US


# ============================================
# TIMESTAMP VALIDATION
# ============================================

def is_monotonic(previous_ts_ns: Optional[int], current_ts_ns: int) -> Tuple[bool, str]:
    """
    Validate that timestamp is monotonic (non-decreasing).
    
    Args:
        previous_ts_ns: Previous timestamp, or None for first call
        current_ts_ns: Current timestamp to validate
    
    Returns:
        Tuple of (is_valid, reason)
        - If valid: (True, "ok")
        - If invalid: (False, reason string)
    """
    if previous_ts_ns is None:
        return True, "ok"
    
    if current_ts_ns < previous_ts_ns:
        delta_ns = previous_ts_ns - current_ts_ns
        return False, f"timestamp reversal: {current_ts_ns} < {previous_ts_ns} (delta={delta_ns}ns)"
    
    return True, "ok"


def age_ns(timestamp_ns: int) -> int:
    """
    Calculate age of a timestamp relative to current time.
    
    Args:
        timestamp_ns: Timestamp to check
    
    Returns:
        Age in nanoseconds
    
    Raises:
        ValueError: If timestamp_ns is negative or in future
    """
    current = now_ns()
    if timestamp_ns < 0:
        raise ValueError(f"timestamp_ns cannot be negative: {timestamp_ns}")
    if timestamp_ns > current:
        raise ValueError(f"timestamp_ns is in future: {timestamp_ns} > {current}")
    return current - timestamp_ns


def is_stale(timestamp_ns: int, max_age_ns: int) -> Tuple[bool, str]:
    """
    Check if a timestamp is stale (older than max_age).
    
    Args:
        timestamp_ns: Timestamp to check
        max_age_ns: Maximum allowed age in nanoseconds
    
    Returns:
        Tuple of (is_stale, reason)
    """
    if timestamp_ns < 0:
        return True, f"negative timestamp: {timestamp_ns}"
    
    try:
        age = age_ns(timestamp_ns)
    except ValueError as e:
        return True, str(e)
    
    if age > max_age_ns:
        return True, f"stale: age {age}ns > {max_age_ns}ns"
    
    return False, "ok"


# ============================================
# REPLAY CONTEXT MANAGER
# ============================================

class ReplayTimeContext:
    """
    Context manager for temporary replay time override.
    
    Within the context, now_ns() returns the specified timestamp.
    Time does not automatically advance; use advance_replay_time_ns()
    to move time forward if needed.
    
    Usage:
        with ReplayTimeContext(recorded_timestamp):
            assert now_ns() == recorded_timestamp
            advance_replay_time_ns(1000)
            assert now_ns() == recorded_timestamp + 1000
    
    Args:
        timestamp_ns: Nanosecond timestamp to use during context
    
    Raises:
        ValueError: If timestamp_ns is negative or exceeds MAX_REASONABLE_TIMESTAMP_NS
    """
    
    def __init__(self, timestamp_ns: int):
        if timestamp_ns < 0:
            raise ValueError(f"timestamp_ns cannot be negative: {timestamp_ns}")
        if timestamp_ns > MAX_REASONABLE_TIMESTAMP_NS:
            raise ValueError(
                f"timestamp_ns exceeds reasonable maximum ({MAX_REASONABLE_TIMESTAMP_NS}): {timestamp_ns}"
            )
        self.timestamp_ns = timestamp_ns
        self._previous_replay_time: Optional[int] = None
    
    def __enter__(self) -> None:
        global _replay_time_ns
        self._previous_replay_time = _replay_time_ns
        _replay_time_ns = self.timestamp_ns
    
    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        global _replay_time_ns
        _replay_time_ns = self._previous_replay_time


# ============================================
# EXPORTS
# ============================================

__all__ = [
    # Constants
    'NS_PER_SECOND',
    'NS_PER_MS',
    'NS_PER_US',
    # Core functions
    'now_ns',
    'set_replay_time_ns',
    'advance_replay_time_ns',
    'clear_replay_time',
    'is_replay_mode',
    # Boundary conversions
    'seconds_to_ns',
    'ms_to_ns',
    'us_to_ns',
    # Display conversions
    'ns_to_seconds',
    'ns_to_ms',
    'ns_to_us',
    # Validation
    'is_monotonic',
    'age_ns',
    'is_stale',
    # Context manager
    'ReplayTimeContext',
]
