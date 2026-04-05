"""
Replay Session Orchestrator for Sovereign Trading System

This module manages deterministic replay sessions for Stage 0.
Handles source loading, event normalization, cursor iteration, and verification.

Session Lifecycle:
1. Load source events
2. Normalize events (validate replay purity)
3. Initialize cursor at start or recovered position
4. Iterate events deterministically
5. Verify against expected outputs (in VERIFY mode)

Session timing is based on replay event timestamps, not wall clock.
Operational telemetry timing (session_duration_ns in get_progress) uses
wall clock for monitoring only and does not affect replay determinism.
"""

import logging
import hashlib
import json
from typing import Optional, Iterator, Dict, Any, List, Union
from pathlib import Path

from app.replay.source import ReplaySource, ReplaySourceError
from app.replay.normalizer import EventNormalizer, EventNormalizerError, create_market_data_normalizer
from app.replay.replay_cursor import ReplayCursor, ReplayCursorError, create_replay_cursor
from app.models.contracts import EventEnvelope, ReplayPosition
from app.models.enums import ReplayMode, EventType, SourceType
from app.models.events import ReplayStartEvent, ReplayEndEvent
from app.utils.time_utils import now_ns

logger = logging.getLogger(__name__)


class ReplaySessionError(Exception):
    """Base exception for replay session errors."""
    pass


class ReplaySessionLoadError(ReplaySessionError):
    """Raised when session fails to load source."""
    pass


class ReplaySessionVerificationError(ReplaySessionError):
    """Raised when verification fails."""
    pass


def _deterministic_serialize_payload(payload: Any) -> str:
    """
    Deterministically serialize payload for checksum calculation.
    
    Args:
        payload: Payload to serialize
    
    Returns:
        Stable JSON string with sorted keys
    """
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def _calculate_event_hash(event: EventEnvelope) -> str:
    """
    Calculate deterministic hash of an event for checksum.
    
    Args:
        event: EventEnvelope to hash
    
    Returns:
        SHA256 hex digest of event
    """
    hasher = hashlib.sha256()
    hasher.update(event.event_id.encode())
    hasher.update(str(event.exchange_ts_ns).encode())
    hasher.update(_deterministic_serialize_payload(event.payload).encode())
    return hasher.hexdigest()


class ReplaySession:
    """
    Deterministic replay session orchestrator.
    
    Manages complete replay lifecycle with purity guarantees.
    
    Session Modes:
    - REPLAY: Execute session, emit events, track position
    - VERIFY: Execute session and verify outputs against expected
    """
    
    def __init__(
        self,
        source_path: Union[str, Path],
        replay_mode: ReplayMode = ReplayMode.REPLAY,
        source_identifier: Optional[str] = None,
        expected_outputs: Optional[Dict[int, Dict[str, Any]]] = None,
        validate_monotonic: bool = True,
        validate_receive_timestamp: bool = True,
        fail_fast: bool = True
    ):
        """
        Initialize replay session.
        
        Args:
            source_path: Path to replay source file
            replay_mode: Session mode (REPLAY or VERIFY)
            source_identifier: Optional source identifier (defaults to source_path stem)
            expected_outputs: For VERIFY mode, mapping of event index -> expected state
            validate_monotonic: Whether to validate timestamp monotonicity
            validate_receive_timestamp: Whether to require receive_ts_ns == exchange_ts_ns
            fail_fast: Whether to fail on first error
        """
        self.source_path = Path(source_path)
        self.replay_mode = replay_mode
        self.source_identifier = source_identifier or self.source_path.stem
        self.expected_outputs = expected_outputs or {}
        self.validate_monotonic = validate_monotonic
        self.validate_receive_timestamp = validate_receive_timestamp
        self.fail_fast = fail_fast
        
        self._source: Optional[ReplaySource] = None
        self._normalizer: Optional[EventNormalizer] = None
        self._cursor: Optional[ReplayCursor] = None
        self._events: Optional[List[EventEnvelope]] = None
        self._event_count = 0
        self._processed_count = 0
        self._verification_failures: List[Dict[str, Any]] = []
        
        # Telemetry only - not used for replay determinism
        self._telemetry_start_ns: Optional[int] = None
        self._telemetry_end_ns: Optional[int] = None
        
        logger.info(
            f"ReplaySession initialized: source={self.source_path}, "
            f"mode={replay_mode.value}, identifier={self.source_identifier}"
        )
    
    def __enter__(self):
        """Start session."""
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """End session."""
        self.end()
    
    def start(self) -> None:
        """
        Start replay session.
        
        Loads source, normalizes events, initializes cursor.
        
        Raises:
            ReplaySessionLoadError: If source loading or normalization fails
        """
        # Telemetry only - not used for replay determinism
        self._telemetry_start_ns = now_ns()
        
        logger.info(f"Replay session started: mode={self.replay_mode.value}")
        
        try:
            # Load and normalize all events
            self._load_and_normalize_events()
            
            # Initialize cursor
            self._initialize_cursor()
            
        except Exception as e:
            raise ReplaySessionLoadError(f"Failed to start replay session: {e}")
    
    def _load_and_normalize_events(self) -> None:
        """Load and normalize all events from source."""
        events: List[EventEnvelope] = []
        
        with ReplaySource(self.source_path) as source:
            normalizer = create_market_data_normalizer(
                fail_fast=self.fail_fast,
                validate_monotonic=self.validate_monotonic,
                validate_receive_timestamp=self.validate_receive_timestamp
            )
            self._normalizer = normalizer
            
            for envelope in source:
                normalized = normalizer.normalize(envelope)
                if normalized is not None:
                    events.append(normalized)
            
            # Log statistics
            stats = normalizer.get_stats()
            logger.info(
                f"Normalized {stats['valid_events']} events "
                f"({stats['filtered_events']} filtered, {stats['invalid_events']} invalid)"
            )
            
            if stats['invalid_events'] > 0 and self.fail_fast:
                raise ReplaySessionLoadError(
                    f"Found {stats['invalid_events']} invalid events with fail_fast=True"
                )
        
        self._events = events
        self._event_count = len(events)
        
        logger.info(f"Loaded {self._event_count} events for replay")
    
    def _initialize_cursor(self) -> None:
        """Initialize replay cursor."""
        if not self._events:
            raise ReplaySessionLoadError("No events loaded for replay")
        
        self._cursor = create_replay_cursor(
            events=self._events,
            source_identifier=self.source_identifier,
            replay_mode=self.replay_mode
        )
    
    def end(self) -> None:
        """
        End replay session.
        
        Records telemetry and verification results.
        """
        # Telemetry only - not used for replay determinism
        self._telemetry_end_ns = now_ns()
        
        # Calculate checksum of all processed events for verification
        checksum = self._calculate_session_checksum()
        
        # Use processed count from cursor, not remaining
        processed = self._processed_count
        
        verification_passed = len(self._verification_failures) == 0
        
        logger.info(
            f"Replay session ended: processed={processed}/{self._event_count}, "
            f"checksum={checksum[:16]}..., "
            f"verification={'PASSED' if verification_passed else 'FAILED'}"
        )
        
        if self._verification_failures:
            logger.error(f"Verification failures: {len(self._verification_failures)}")
            for failure in self._verification_failures[:5]:  # Log first 5
                logger.error(f"  {failure}")
    
    def _calculate_session_checksum(self) -> str:
        """
        Calculate deterministic checksum of session.
        
        Returns:
            SHA256 hex digest of event hashes
        """
        hasher = hashlib.sha256()
        
        if self._events:
            # Iterate through all events for deterministic checksum
            for event in self._events:
                event_hash = _calculate_event_hash(event)
                hasher.update(event_hash.encode())
        
        return hasher.hexdigest()
    
    def iterate_events(self) -> Iterator[EventEnvelope]:
        """
        Iterate through events in deterministic order.
        
        Yields:
            EventEnvelope objects in replay order
        
        Raises:
            ReplaySessionError: If session not started
        """
        if self._cursor is None:
            raise ReplaySessionError("Session not started. Call start() first.")
        
        event_index = 0
        for event in self._cursor:
            # In VERIFY mode, check against expected outputs
            if self.replay_mode == ReplayMode.VERIFY:
                self._verify_event(event_index, event)
            
            event_index += 1
            self._processed_count += 1
            yield event
    
    def _verify_event(self, index: int, event: EventEnvelope) -> None:
        """
        Verify event against expected output.
        
        Args:
            index: Event index
            event: Actual event
        
        Raises:
            ReplaySessionVerificationError: If verification fails and fail_fast=True
        """
        if index in self.expected_outputs:
            expected = self.expected_outputs[index]
            
            # Verify event_type
            if 'event_type' in expected:
                # Handle both string and enum values safely
                actual_type = event.event_type.value if hasattr(event.event_type, 'value') else str(event.event_type)
                expected_type = expected['event_type'].value if hasattr(expected['event_type'], 'value') else str(expected['event_type'])
                
                if expected_type != actual_type:
                    failure = {
                        'index': index,
                        'field': 'event_type',
                        'expected': expected_type,
                        'actual': actual_type
                    }
                    self._verification_failures.append(failure)
                    
                    if self.fail_fast:
                        raise ReplaySessionVerificationError(
                            f"Event {index}: event_type mismatch - "
                            f"expected {expected_type}, got {actual_type}"
                        )
            
            # Verify timestamp (if within tolerance)
            if 'exchange_ts_ns' in expected:
                tolerance = expected.get('tolerance_ns', 0)
                diff = abs(event.exchange_ts_ns - expected['exchange_ts_ns'])
                if diff > tolerance:
                    failure = {
                        'index': index,
                        'field': 'exchange_ts_ns',
                        'expected': expected['exchange_ts_ns'],
                        'actual': event.exchange_ts_ns,
                        'diff': diff,
                        'tolerance': tolerance
                    }
                    self._verification_failures.append(failure)
                    
                    if self.fail_fast:
                        raise ReplaySessionVerificationError(
                            f"Event {index}: timestamp mismatch - "
                            f"expected {expected['exchange_ts_ns']}, "
                            f"got {event.exchange_ts_ns} (diff={diff}ns, tolerance={tolerance}ns)"
                        )
    
    def get_current_position(self) -> Optional[ReplayPosition]:
        """Get current replay position."""
        if self._cursor is None:
            return None
        return self._cursor.get_current_position()
    
    def get_progress(self) -> Dict[str, Any]:
        """
        Get session progress metrics.
        
        Returns:
            Dictionary with progress information
            - session_duration_ns is telemetry only (wall clock)
            - All other fields are deterministic
        """
        if self._cursor is None:
            return {"status": "not_started"}
        
        progress = self._cursor.get_progress()
        
        # Telemetry only - not used for replay determinism
        duration = 0
        if self._telemetry_start_ns:
            end = self._telemetry_end_ns or now_ns()
            duration = end - self._telemetry_start_ns
        
        progress["session_duration_ns"] = duration  # Telemetry only
        progress["verification_failures"] = len(self._verification_failures)
        progress["verification_passed"] = len(self._verification_failures) == 0
        progress["processed_count"] = self._processed_count
        progress["total_count"] = self._event_count
        
        return progress
    
    def get_stats(self) -> Dict[str, Any]:
        """Get session statistics."""
        return {
            "source_path": str(self.source_path),
            "source_identifier": self.source_identifier,
            "replay_mode": self.replay_mode.value,
            "event_count": self._event_count,
            "processed_count": self._processed_count,
            "verification_failures": len(self._verification_failures),
            "fail_fast": self.fail_fast,
            "validate_monotonic": self.validate_monotonic,
            "validate_receive_timestamp": self.validate_receive_timestamp
        }
    
    def seek_to_timestamp(self, timestamp_ns: int) -> None:
        """
        Seek to timestamp within session.
        
        Args:
            timestamp_ns: Target timestamp
        
        Raises:
            ReplaySessionError: If session not started or seek fails
        """
        if self._cursor is None:
            raise ReplaySessionError("Session not started. Call start() first.")
        
        self._cursor.seek_to_timestamp(timestamp_ns)
        logger.info(f"Seeked to timestamp {timestamp_ns}")
    
    def seek_to_index(self, index: int) -> None:
        """
        Seek to event index within session.
        
        Args:
            index: Target event index
        
        Raises:
            ReplaySessionError: If session not started or seek fails
        """
        if self._cursor is None:
            raise ReplaySessionError("Session not started. Call start() first.")
        
        self._cursor.seek_to_index(index)
        logger.info(f"Seeked to index {index}")
    
    def reset(self) -> None:
        """Reset session to beginning."""
        if self._cursor is not None:
            self._cursor.reset()
            self._processed_count = 0
            self._verification_failures.clear()
            logger.info("Session reset to beginning")
    
    def snapshot_state(self) -> Dict[str, Any]:
        """
        Snapshot session state for crash recovery.
        
        Returns:
            Dictionary with cursor state and session metadata
        """
        if self._cursor is None:
            return {}
        
        return {
            "cursor_state": self._cursor.snapshot_state(),
            "source_path": str(self.source_path),
            "source_identifier": self.source_identifier,
            "replay_mode": self.replay_mode.value,
            "event_count": self._event_count,
            "processed_count": self._processed_count
        }
    
    def restore_state(self, state: Dict[str, Any]) -> None:
        """
        Restore session state from snapshot.
        
        Args:
            state: State dictionary from snapshot_state()
        
        Raises:
            ReplaySessionError: If restore fails
        """
        if self._cursor is None:
            raise ReplaySessionError("Session not started. Call start() first.")
        
        cursor_state = state.get("cursor_state")
        if not cursor_state:
            raise ReplaySessionError("No cursor state in snapshot")
        
        try:
            self._cursor.restore_state(cursor_state)
            self._processed_count = state.get("processed_count", 0)
            self._verification_failures.clear()
            logger.info("Session state restored")
        except ReplayCursorError as e:
            raise ReplaySessionError(f"Failed to restore cursor state: {e}")


# ============================================
# Convenience Functions
# ============================================

def replay_session(
    source_path: Union[str, Path],
    replay_mode: ReplayMode = ReplayMode.REPLAY,
    source_identifier: Optional[str] = None,
    fail_fast: bool = True
) -> ReplaySession:
    """
    Create and start a replay session.
    
    Args:
        source_path: Path to replay source file
        replay_mode: Session mode (REPLAY or VERIFY)
        source_identifier: Optional source identifier
        fail_fast: Whether to fail on first error
    
    Returns:
        Started ReplaySession instance
    """
    session = ReplaySession(
        source_path=source_path,
        replay_mode=replay_mode,
        source_identifier=source_identifier,
        fail_fast=fail_fast
    )
    session.start()
    return session


def verify_replay_session(
    source_path: Union[str, Path],
    expected_outputs: Dict[int, Dict[str, Any]],
    source_identifier: Optional[str] = None,
    fail_fast: bool = True
) -> ReplaySession:
    """
    Create and start a verification replay session.
    
    Args:
        source_path: Path to replay source file
        expected_outputs: Expected outputs mapping
        source_identifier: Optional source identifier
        fail_fast: Whether to fail on first verification error
    
    Returns:
        Started ReplaySession instance in VERIFY mode
    """
    session = ReplaySession(
        source_path=source_path,
        replay_mode=ReplayMode.VERIFY,
        source_identifier=source_identifier,
        expected_outputs=expected_outputs,
        fail_fast=fail_fast
    )
    session.start()
    return session


__all__ = [
    'ReplaySession',
    'ReplaySessionError',
    'ReplaySessionLoadError',
    'ReplaySessionVerificationError',
    'replay_session',
    'verify_replay_session',
]