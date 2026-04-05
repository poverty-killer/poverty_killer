"""
Replay Cursor for Sovereign Trading System

This module provides deterministic replay cursor management for Stage 0.
Tracks replay position, handles event iteration, and supports seeking.

Replay Purity Invariants Enforced:
- Deterministic event ordering
- Exact position tracking for crash recovery
- No wall clock dependencies in cursor logic

ReplayPosition Semantics:
- source: Source file path or module identifier (consistent across all uses)
- sequence: Event index in the sorted event list
- timestamp_ns: Event exchange timestamp
"""

import logging
from typing import Optional, Iterator, Dict, Any, List, Tuple
from dataclasses import dataclass

from app.models.contracts import EventEnvelope, ReplayPosition
from app.models.enums import ReplayMode
from app.utils.time_utils import is_monotonic

logger = logging.getLogger(__name__)


class ReplayCursorError(Exception):
    """Base exception for replay cursor errors."""
    pass


class ReplayCursorSeekError(ReplayCursorError):
    """Raised when seeking to an invalid position."""
    pass


class ReplayCursorStateError(ReplayCursorError):
    """Raised when cursor state is invalid or malformed."""
    pass


@dataclass
class CursorState:
    """Internal cursor state."""
    position: ReplayPosition
    event_index: int = 0
    events_processed: int = 0
    current_timestamp_ns: Optional[int] = None
    current_event_id: Optional[str] = None
    is_exhausted: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for persistence.
        
        Returns:
            Dictionary representation of cursor state
        """
        return {
            "position": {
                "source": self.position.source,
                "sequence": self.position.sequence,
                "timestamp_ns": self.position.timestamp_ns
            },
            "event_index": self.event_index,
            "events_processed": self.events_processed,
            "current_timestamp_ns": self.current_timestamp_ns,
            "current_event_id": self.current_event_id,
            "is_exhausted": self.is_exhausted
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CursorState':
        """
        Create cursor state from dictionary.
        
        Args:
            data: Dictionary from to_dict()
        
        Returns:
            CursorState instance
        
        Raises:
            ReplayCursorStateError: If data is malformed or missing required fields
        """
        pos_data = data.get("position")
        if not pos_data:
            raise ReplayCursorStateError("Missing 'position' field in state data")
        
        if "source" not in pos_data:
            raise ReplayCursorStateError("Missing 'source' in position data")
        
        if "sequence" not in pos_data:
            raise ReplayCursorStateError("Missing 'sequence' in position data")
        
        if "timestamp_ns" not in pos_data:
            raise ReplayCursorStateError("Missing 'timestamp_ns' in position data")
        
        position = ReplayPosition(
            source=pos_data["source"],
            sequence=pos_data["sequence"],
            timestamp_ns=pos_data["timestamp_ns"]
        )
        
        return cls(
            position=position,
            event_index=data.get("event_index", 0),
            events_processed=data.get("events_processed", 0),
            current_timestamp_ns=data.get("current_timestamp_ns"),
            current_event_id=data.get("current_event_id"),
            is_exhausted=data.get("is_exhausted", False)
        )


class ReplayCursor:
    """
    Deterministic replay cursor for event iteration and position tracking.
    
    Features:
    - Iterates over events with deterministic ordering
    - Tracks exact replay position for crash recovery
    - Supports seeking to specific timestamps or event indices
    - Provides idempotent event consumption
    
    ReplayPosition fields are used consistently:
    - source: Source file path or module identifier
    - sequence: Event index in the sorted list
    - timestamp_ns: Event exchange timestamp
    """
    
    def __init__(
        self,
        events: List[EventEnvelope],
        source_identifier: str,
        replay_mode: ReplayMode = ReplayMode.REPLAY,
        initial_position: Optional[ReplayPosition] = None
    ):
        """
        Initialize replay cursor.
        
        Args:
            events: List of events in deterministic order (already sorted)
            source_identifier: Source file path or module identifier for ReplayPosition
            replay_mode: Current replay mode
            initial_position: Optional starting position (for recovery)
        
        Raises:
            ReplayCursorError: If events list is empty
            ReplayCursorSeekError: If initial position not found
        """
        if not events:
            raise ReplayCursorError("Events list cannot be empty")
        
        self._events = events
        self._source_identifier = source_identifier
        self._replay_mode = replay_mode
        self._cursor_state: Optional[CursorState] = None
        self._current_index = 0
        self._events_processed = 0
        
        # Validate event ordering (should be already sorted by source)
        self._validate_event_ordering()
        
        # Initialize position
        if initial_position:
            self._seek_to_position(initial_position)
        else:
            self._initialize_cursor()
        
        logger.info(
            f"ReplayCursor initialized: {len(events)} events, source={source_identifier}, "
            f"mode={replay_mode.value}, start_index={self._current_index}"
        )
    
    def _validate_event_ordering(self) -> None:
        """Validate that events are in monotonic timestamp order."""
        last_ts = None
        for i, event in enumerate(self._events):
            if last_ts is not None:
                valid, reason = is_monotonic(last_ts, event.exchange_ts_ns)
                if not valid:
                    raise ReplayCursorError(
                        f"Events not in monotonic order at index {i}: {reason}"
                    )
            last_ts = event.exchange_ts_ns
    
    def _initialize_cursor(self) -> None:
        """Initialize cursor at start position."""
        self._current_index = 0
        self._events_processed = 0
        first_event = self._events[0]
        self._cursor_state = CursorState(
            position=ReplayPosition(
                source=self._source_identifier,
                sequence=0,
                timestamp_ns=first_event.exchange_ts_ns
            ),
            event_index=0,
            events_processed=0,
            current_timestamp_ns=first_event.exchange_ts_ns,
            current_event_id=first_event.event_id,
            is_exhausted=False
        )
    
    def _seek_to_position(self, position: ReplayPosition) -> None:
        """
        Seek to a specific replay position.
        
        Matching criteria:
        - source must match the cursor's source_identifier
        - sequence must match the event index
        - timestamp_ns must match the event's exchange timestamp
        
        Args:
            position: Target position to seek to
        
        Raises:
            ReplayCursorSeekError: If position not found or source mismatch
        """
        # Validate source matches
        if position.source != self._source_identifier:
            raise ReplayCursorSeekError(
                f"Position source '{position.source}' does not match cursor source '{self._source_identifier}'"
            )
        
        # Validate sequence is within range
        if position.sequence < 0 or position.sequence >= len(self._events):
            raise ReplayCursorSeekError(
                f"Sequence {position.sequence} out of range (0-{len(self._events)-1})"
            )
        
        # Validate timestamp matches
        target_event = self._events[position.sequence]
        if target_event.exchange_ts_ns != position.timestamp_ns:
            raise ReplayCursorSeekError(
                f"Timestamp mismatch at sequence {position.sequence}: "
                f"position timestamp {position.timestamp_ns} != "
                f"event timestamp {target_event.exchange_ts_ns}"
            )
        
        self._current_index = position.sequence
        self._events_processed = position.sequence
        self._cursor_state = CursorState(
            position=position,
            event_index=position.sequence,
            events_processed=position.sequence,
            current_timestamp_ns=target_event.exchange_ts_ns,
            current_event_id=target_event.event_id,
            is_exhausted=False
        )
        logger.info(f"Seeked to position: sequence={position.sequence}")
    
    def __iter__(self) -> Iterator[EventEnvelope]:
        """Iterate over events from current position."""
        return self
    
    def __next__(self) -> EventEnvelope:
        """
        Get next event from cursor.
        
        Returns:
            Next EventEnvelope
        
        Raises:
            StopIteration: When no more events
            ReplayCursorStateError: If cursor not initialized
        """
        if self._cursor_state is None:
            raise ReplayCursorStateError("Cursor not initialized")
        
        if self._cursor_state.is_exhausted:
            raise StopIteration
        
        if self._current_index >= len(self._events):
            self._cursor_state.is_exhausted = True
            raise StopIteration
        
        event = self._events[self._current_index]
        
        # Update cursor state
        self._cursor_state.position = ReplayPosition(
            source=self._source_identifier,
            sequence=self._current_index,
            timestamp_ns=event.exchange_ts_ns
        )
        self._cursor_state.event_index = self._current_index
        self._cursor_state.events_processed = self._events_processed + 1
        self._cursor_state.current_timestamp_ns = event.exchange_ts_ns
        self._cursor_state.current_event_id = event.event_id
        
        self._current_index += 1
        self._events_processed += 1
        
        return event
    
    def seek_to_timestamp(self, timestamp_ns: int) -> None:
        """
        Seek to the first event at or after given timestamp.
        
        Args:
            timestamp_ns: Target timestamp in nanoseconds
        
        Raises:
            ReplayCursorSeekError: If timestamp not found
        """
        for idx, event in enumerate(self._events):
            if event.exchange_ts_ns >= timestamp_ns:
                self._current_index = idx
                self._events_processed = idx
                self._cursor_state = CursorState(
                    position=ReplayPosition(
                        source=self._source_identifier,
                        sequence=idx,
                        timestamp_ns=event.exchange_ts_ns
                    ),
                    event_index=idx,
                    events_processed=idx,
                    current_timestamp_ns=event.exchange_ts_ns,
                    current_event_id=event.event_id,
                    is_exhausted=False
                )
                logger.info(f"Seeked to timestamp {timestamp_ns} (index {idx})")
                return
        
        raise ReplayCursorSeekError(f"Timestamp {timestamp_ns} not found (beyond end)")
    
    def seek_to_index(self, index: int) -> None:
        """
        Seek to a specific event index.
        
        Args:
            index: Target event index (0-based)
        
        Raises:
            ReplayCursorSeekError: If index out of range
        """
        if index < 0 or index >= len(self._events):
            raise ReplayCursorSeekError(
                f"Index {index} out of range (0-{len(self._events)-1})"
            )
        
        event = self._events[index]
        self._current_index = index
        self._events_processed = index
        self._cursor_state = CursorState(
            position=ReplayPosition(
                source=self._source_identifier,
                sequence=index,
                timestamp_ns=event.exchange_ts_ns
            ),
            event_index=index,
            events_processed=index,
            current_timestamp_ns=event.exchange_ts_ns,
            current_event_id=event.event_id,
            is_exhausted=False
        )
        logger.info(f"Seeked to index {index}")
    
    def get_current_position(self) -> Optional[ReplayPosition]:
        """
        Get current replay position.
        
        Returns:
            Current ReplayPosition, or None if cursor not initialized
        """
        if self._cursor_state is None:
            return None
        return self._cursor_state.position
    
    def get_cursor_state(self) -> Optional[CursorState]:
        """Get full cursor state."""
        return self._cursor_state
    
    def get_progress(self) -> Dict[str, Any]:
        """
        Get replay progress metrics.
        
        Returns:
            Dictionary with progress information
            - progress_percent is for display/telemetry only
        """
        total = len(self._events)
        processed = self._events_processed
        remaining = total - processed
        
        # progress_percent is for display/telemetry only
        progress_pct = (processed / total * 100) if total > 0 else 0.0
        
        return {
            "total_events": total,
            "processed_events": processed,
            "remaining_events": remaining,
            "progress_percent": progress_pct,  # Display/telemetry only
            "current_timestamp_ns": self._cursor_state.current_timestamp_ns if self._cursor_state else None,
            "current_event_id": self._cursor_state.current_event_id if self._cursor_state else None,
            "is_exhausted": self._cursor_state.is_exhausted if self._cursor_state else False,
            "replay_mode": self._replay_mode.value
        }
    
    def has_next(self) -> bool:
        """Check if there are more events."""
        if self._cursor_state is None:
            return False
        return (not self._cursor_state.is_exhausted and 
                self._current_index < len(self._events))
    
    def get_remaining_count(self) -> int:
        """Get number of remaining events."""
        return len(self._events) - self._events_processed
    
    def reset(self) -> None:
        """Reset cursor to beginning."""
        self._initialize_cursor()
        logger.info("Cursor reset to beginning")
    
    def snapshot_state(self) -> Dict[str, Any]:
        """
        Create a snapshot of cursor state for recovery.
        
        Returns:
            Dictionary containing cursor state
        """
        if self._cursor_state is None:
            return {}
        return self._cursor_state.to_dict()
    
    def restore_state(self, state: Dict[str, Any]) -> None:
        """
        Restore cursor state from snapshot.
        
        Args:
            state: Cursor state dictionary from snapshot_state()
        
        Raises:
            ReplayCursorStateError: If state is invalid or position not found
        """
        try:
            cursor_state = CursorState.from_dict(state)
            
            # Validate source matches
            if cursor_state.position.source != self._source_identifier:
                raise ReplayCursorStateError(
                    f"State source '{cursor_state.position.source}' does not match "
                    f"cursor source '{self._source_identifier}'"
                )
            
            # Validate sequence is within range
            if cursor_state.position.sequence < 0 or cursor_state.position.sequence >= len(self._events):
                raise ReplayCursorStateError(
                    f"State sequence {cursor_state.position.sequence} out of range "
                    f"(0-{len(self._events)-1})"
                )
            
            # Validate timestamp matches
            target_event = self._events[cursor_state.position.sequence]
            if target_event.exchange_ts_ns != cursor_state.position.timestamp_ns:
                raise ReplayCursorStateError(
                    f"Timestamp mismatch at sequence {cursor_state.position.sequence}: "
                    f"state timestamp {cursor_state.position.timestamp_ns} != "
                    f"event timestamp {target_event.exchange_ts_ns}"
                )
            
            self._current_index = cursor_state.position.sequence
            self._events_processed = cursor_state.events_processed
            self._cursor_state = cursor_state
            
            logger.info(f"Restored cursor state: index {self._current_index}")
        except ReplayCursorStateError:
            raise
        except Exception as e:
            raise ReplayCursorStateError(f"Failed to restore cursor state: {e}")


# ============================================
# Factory Functions
# ============================================

def create_replay_cursor(
    events: List[EventEnvelope],
    source_identifier: str,
    replay_mode: ReplayMode = ReplayMode.REPLAY,
    initial_position: Optional[ReplayPosition] = None
) -> ReplayCursor:
    """
    Create a replay cursor for event iteration.
    
    Args:
        events: List of events in deterministic order (must not be empty)
        source_identifier: Source file path or module identifier
        replay_mode: Current replay mode
        initial_position: Optional starting position
    
    Returns:
        ReplayCursor instance
    
    Raises:
        ReplayCursorError: If events list is empty
    """
    return ReplayCursor(
        events=events,
        source_identifier=source_identifier,
        replay_mode=replay_mode,
        initial_position=initial_position
    )


__all__ = [
    'ReplayCursor',
    'ReplayCursorError',
    'ReplayCursorSeekError',
    'ReplayCursorStateError',
    'CursorState',
    'create_replay_cursor',
]