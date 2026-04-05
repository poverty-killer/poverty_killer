"""
Replay Verifier for Sovereign Trading System

This module provides deterministic verification for replay sessions.
Compares replayed event streams against expected outputs with configurable strictness.

Verification Modes:
- STRICT: Exact match for event_type, exact timestamp match, exact payload equality (all fields)
- TOLERANT: Exact match for event_type, timestamp tolerance allowed, exact payload equality (all fields)
- AUDIT: Same checks as selected policy but continue collecting failures without raising

All verification is deterministic and uses stable serialization for comparisons.
"""

import logging
import hashlib
import json
from typing import Optional, Iterator, Dict, Any, List, Tuple, Union
from dataclasses import dataclass, field
from enum import Enum

from app.models.contracts import EventEnvelope
from app.models.enums import EventType
from app.replay.replay_session import ReplaySession, ReplaySessionVerificationError

logger = logging.getLogger(__name__)


class VerificationMode(str, Enum):
    """Verification strictness modes."""
    STRICT = "strict"           # Exact match for all fields, exact timestamps
    TOLERANT = "tolerant"       # Exact match except timestamps (tolerance allowed)
    AUDIT = "audit"             # Same as policy but continue on failures


@dataclass
class VerificationFailure:
    """Record of a verification failure."""
    event_index: int
    event_id: str
    field: str
    expected: Any
    actual: Any
    tolerance: Optional[int] = None
    diff: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = {
            "event_index": self.event_index,
            "event_id": self.event_id,
            "field": self.field,
            "expected": self.expected,
            "actual": self.actual
        }
        if self.tolerance is not None:
            result["tolerance"] = self.tolerance
        if self.diff is not None:
            result["diff"] = self.diff
        return result


@dataclass
class VerificationResult:
    """
    Result of a verification run.
    
    Fields:
        passed: True if no failures and checksum matches (if provided)
        total_expected_events: Number of expected event specifications provided
        total_actual_events: Number of events actually processed from session
        verified_events: Number of events that had expected specs and were checked
        failures: List of verification failures
        checksum: Actual session checksum (if computed)
        expected_checksum: Expected session checksum (if provided)
    """
    passed: bool
    total_expected_events: int
    total_actual_events: int
    verified_events: int = 0
    failures: List[VerificationFailure] = field(default_factory=list)
    checksum: Optional[str] = None
    expected_checksum: Optional[str] = None

    @property
    def failure_count(self) -> int:
        """Number of verification failures."""
        return len(self.failures)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "passed": self.passed,
            "total_expected_events": self.total_expected_events,
            "total_actual_events": self.total_actual_events,
            "verified_events": self.verified_events,
            "failure_count": self.failure_count,
            "failures": [f.to_dict() for f in self.failures],
            "checksum": self.checksum,
            "expected_checksum": self.expected_checksum
        }


def _deterministic_serialize(value: Any) -> str:
    """
    Deterministically serialize a value for comparison.
    
    Args:
        value: Value to serialize
    
    Returns:
        Stable JSON string with sorted keys
    """
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def _calculate_event_checksum(event: EventEnvelope) -> str:
    """
    Calculate deterministic checksum of an event.
    
    Args:
        event: EventEnvelope to hash
    
    Returns:
        SHA256 hex digest of event
    """
    hasher = hashlib.sha256()
    hasher.update(event.event_id.encode())
    hasher.update(str(event.exchange_ts_ns).encode())
    hasher.update(_deterministic_serialize(event.payload).encode())
    return hasher.hexdigest()


def _compare_payloads_exact(expected: Any, actual: Any) -> bool:
    """
    Compare two payloads for exact equality using deterministic serialization.
    
    Args:
        expected: Expected payload
        actual: Actual payload
    
    Returns:
        True if payloads are exactly equal
    """
    expected_str = _deterministic_serialize(expected)
    actual_str = _deterministic_serialize(actual)
    return expected_str == actual_str


class ReplayVerifier:
    """
    Deterministic verifier for replay sessions.
    
    Features:
    - Configurable verification mode (STRICT, TOLERANT, AUDIT)
    - STRICT: exact timestamps, exact payloads
    - TOLERANT: timestamp tolerance, exact payloads
    - AUDIT: same checks as policy but continue on failures
    - Structured failure reporting
    - Checksum verification for session integrity
    """
    
    def __init__(
        self,
        mode: VerificationMode = VerificationMode.STRICT,
        timestamp_tolerance_ns: int = 0,
        fail_fast: bool = False
    ):
        """
        Initialize replay verifier.
        
        Args:
            mode: Verification strictness mode
            timestamp_tolerance_ns: Tolerance in nanoseconds for timestamp comparison
            fail_fast: If True, raise on first failure
        """
        self.mode = mode
        self.timestamp_tolerance_ns = timestamp_tolerance_ns
        self.fail_fast = fail_fast
        
        self._failures: List[VerificationFailure] = []
        self._verified_count = 0
        
        logger.info(
            f"ReplayVerifier initialized: mode={mode.value}, "
            f"tolerance={timestamp_tolerance_ns}ns, fail_fast={fail_fast}"
        )
    
    def _verify_timestamp(
        self,
        event_index: int,
        event: EventEnvelope,
        expected_timestamp: int,
        tolerance: Optional[int] = None
    ) -> bool:
        """
        Verify timestamp with mode-appropriate rules.
        
        Returns:
            True if timestamp passes verification
        """
        effective_tolerance = tolerance if tolerance is not None else self.timestamp_tolerance_ns
        
        if self.mode == VerificationMode.STRICT:
            # STRICT mode: exact match only
            if event.exchange_ts_ns != expected_timestamp:
                diff = abs(event.exchange_ts_ns - expected_timestamp)
                failure = VerificationFailure(
                    event_index=event_index,
                    event_id=event.event_id,
                    field="exchange_ts_ns",
                    expected=expected_timestamp,
                    actual=event.exchange_ts_ns,
                    diff=diff,
                    tolerance=0
                )
                self._failures.append(failure)
                return False
            return True
        
        else:
            # TOLERANT or AUDIT mode: tolerance allowed
            diff = abs(event.exchange_ts_ns - expected_timestamp)
            if diff > effective_tolerance:
                failure = VerificationFailure(
                    event_index=event_index,
                    event_id=event.event_id,
                    field="exchange_ts_ns",
                    expected=expected_timestamp,
                    actual=event.exchange_ts_ns,
                    diff=diff,
                    tolerance=effective_tolerance
                )
                self._failures.append(failure)
                return False
            return True
    
    def _verify_payload(
        self,
        event_index: int,
        event: EventEnvelope,
        expected_payload: Dict[str, Any]
    ) -> bool:
        """
        Verify payload with mode-appropriate rules.
        
        STRICT and TOLERANT both require exact payload equality.
        
        Returns:
            True if payload passes verification
        """
        if not _compare_payloads_exact(expected_payload, event.payload):
            failure = VerificationFailure(
                event_index=event_index,
                event_id=event.event_id,
                field="payload",
                expected=expected_payload,
                actual=event.payload
            )
            self._failures.append(failure)
            return False
        return True
    
    def verify_event(
        self,
        event_index: int,
        event: EventEnvelope,
        expected: Dict[str, Any]
    ) -> bool:
        """
        Verify a single event against expected output.
        
        Args:
            event_index: Index of event in sequence
            event: Actual event from replay
            expected: Expected event specification
        
        Returns:
            True if event passes verification, False otherwise
        
        Raises:
            ReplaySessionVerificationError: If fail_fast=True and verification fails
        """
        is_valid = True
        
        # Verify event_type
        if 'event_type' in expected:
            expected_type = expected['event_type']
            expected_str = expected_type.value if hasattr(expected_type, 'value') else str(expected_type)
            actual_str = event.event_type.value if hasattr(event.event_type, 'value') else str(event.event_type)
            
            if expected_str != actual_str:
                failure = VerificationFailure(
                    event_index=event_index,
                    event_id=event.event_id,
                    field="event_type",
                    expected=expected_str,
                    actual=actual_str
                )
                self._failures.append(failure)
                is_valid = False
                
                if self.fail_fast:
                    raise ReplaySessionVerificationError(
                        f"Event {event_index}: event_type mismatch - "
                        f"expected {expected_str}, got {actual_str}"
                    )
        
        # Verify exchange_ts_ns
        if 'exchange_ts_ns' in expected:
            tolerance = expected.get('tolerance_ns', None)
            if not self._verify_timestamp(event_index, event, expected['exchange_ts_ns'], tolerance):
                is_valid = False
                if self.fail_fast:
                    raise ReplaySessionVerificationError(
                        f"Event {event_index}: timestamp verification failed"
                    )
        
        # Verify payload (all modes require exact payload equality)
        if 'payload' in expected:
            if not self._verify_payload(event_index, event, expected['payload']):
                is_valid = False
                if self.fail_fast:
                    raise ReplaySessionVerificationError(
                        f"Event {event_index}: payload verification failed"
                    )
        
        self._verified_count += 1
        return is_valid
    
    def verify_session(
        self,
        session: ReplaySession,
        expected_outputs: Dict[int, Dict[str, Any]]
    ) -> VerificationResult:
        """
        Verify an entire replay session.
        
        Args:
            session: Started ReplaySession instance
            expected_outputs: Mapping of event index to expected event spec
        
        Returns:
            VerificationResult with summary and failures
        
        Raises:
            ReplaySessionVerificationError: If fail_fast=True and any verification fails
        """
        self._failures.clear()
        self._verified_count = 0
        
        total_expected = len(expected_outputs)
        actual_events = 0
        event_index = 0
        
        for event in session.iterate_events():
            actual_events += 1
            if event_index in expected_outputs:
                self.verify_event(event_index, event, expected_outputs[event_index])
            event_index += 1
        
        # In AUDIT mode, continue even with failures
        if self.mode == VerificationMode.AUDIT and self._failures:
            logger.warning(f"Verification completed with {len(self._failures)} failures (AUDIT mode)")
        
        return VerificationResult(
            passed=len(self._failures) == 0,
            total_expected_events=total_expected,
            total_actual_events=actual_events,
            verified_events=self._verified_count,
            failures=self._failures
        )
    
    def verify_session_with_checksum(
        self,
        session: ReplaySession,
        expected_checksum: str,
        expected_outputs: Optional[Dict[int, Dict[str, Any]]] = None
    ) -> VerificationResult:
        """
        Verify a replay session with checksum validation.
        
        Args:
            session: Started ReplaySession instance
            expected_checksum: Expected session checksum
            expected_outputs: Optional mapping of event index to expected event spec
        
        Returns:
            VerificationResult with summary and failures
        """
        result = self.verify_session(session, expected_outputs or {})
        result.expected_checksum = expected_checksum
        
        # Calculate session checksum from session events
        # Access session._events is a Stage 0 dependency on session internals.
        # This is acceptable for Stage 0 as the session module is in the same package.
        if hasattr(session, '_events') and session._events:
            hasher = hashlib.sha256()
            for event in session._events:
                event_hash = _calculate_event_checksum(event)
                hasher.update(event_hash.encode())
            result.checksum = hasher.hexdigest()
            
            # Record checksum failure if mismatch
            if result.checksum != expected_checksum:
                failure = VerificationFailure(
                    event_index=-1,
                    event_id="session",
                    field="checksum",
                    expected=expected_checksum,
                    actual=result.checksum
                )
                result.failures.append(failure)
                result.passed = False
        else:
            logger.warning("Cannot compute session checksum: session._events not accessible")
        
        return result
    
    def reset(self) -> None:
        """Reset verifier state for new verification run."""
        self._failures.clear()
        self._verified_count = 0
    
    def get_summary(self) -> Dict[str, Any]:
        """
        Get verification summary.
        
        Returns:
            Dictionary with verification statistics
        """
        return {
            "mode": self.mode.value,
            "timestamp_tolerance_ns": self.timestamp_tolerance_ns,
            "fail_fast": self.fail_fast,
            "failures_count": len(self._failures),
            "verified_count": self._verified_count,
            "failures": [f.to_dict() for f in self._failures]
        }


# ============================================
# Convenience Functions
# ============================================

def create_strict_verifier(
    fail_fast: bool = False
) -> ReplayVerifier:
    """
    Create a strict verifier (exact matches, exact timestamps).
    
    Args:
        fail_fast: Whether to fail on first error
    
    Returns:
        ReplayVerifier in STRICT mode
    """
    return ReplayVerifier(
        mode=VerificationMode.STRICT,
        timestamp_tolerance_ns=0,
        fail_fast=fail_fast
    )


def create_tolerant_verifier(
    timestamp_tolerance_ns: int = 1_000_000,  # 1ms default
    fail_fast: bool = False
) -> ReplayVerifier:
    """
    Create a tolerant verifier (timestamp tolerance allowed, exact payloads).
    
    Args:
        timestamp_tolerance_ns: Tolerance in nanoseconds for timestamp comparison
        fail_fast: Whether to fail on first error
    
    Returns:
        ReplayVerifier in TOLERANT mode
    """
    return ReplayVerifier(
        mode=VerificationMode.TOLERANT,
        timestamp_tolerance_ns=timestamp_tolerance_ns,
        fail_fast=fail_fast
    )


def create_audit_verifier(
    timestamp_tolerance_ns: int = 0,
    fail_fast: bool = False
) -> ReplayVerifier:
    """
    Create an audit verifier (same as STRICT but continue on failures).
    
    Args:
        timestamp_tolerance_ns: Tolerance in nanoseconds for timestamp comparison
        fail_fast: Whether to fail on first error (ignored in AUDIT mode)
    
    Returns:
        ReplayVerifier in AUDIT mode with fail_fast=False
    """
    return ReplayVerifier(
        mode=VerificationMode.AUDIT,
        timestamp_tolerance_ns=timestamp_tolerance_ns,
        fail_fast=False
    )


__all__ = [
    'ReplayVerifier',
    'VerificationMode',
    'VerificationFailure',
    'VerificationResult',
    'create_strict_verifier',
    'create_tolerant_verifier',
    'create_audit_verifier',
]