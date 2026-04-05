"""
Replay Source Reader for Sovereign Trading System

This module provides deterministic replay source reading for Stage 0.
Reads recorded market data from JSONL files and yields events in order.

Replay Purity Invariants Enforced:
- RP-01: No wall clock reads — all timestamps from recorded data
- RP-02: No live network calls — reads only from local files
- RP-04: No external mutable state — read-only file access

JSONL Format:
    Each line is a JSON object with:
    - event_type: string (must match EventType values)
    - exchange_ts_ns: integer (nanoseconds, nonnegative)
    - payload: object (event-specific data, does NOT include base fields)

Timestamps are sorted by exchange_ts_ns. Ties are broken by original line order.
"""

import json
import os
import tempfile
import logging
from pathlib import Path
from typing import Optional, Iterator, Dict, Any, Union, List, Tuple

from app.models.enums import EventType, SourceType
from app.models.events import (
    TradeEvent, QuoteEvent, OrderBookSnapshotEvent,
    OrderBookDeltaEvent, ClockTickEvent
)
from app.models.contracts import EventEnvelope
from app.utils.time_utils import is_monotonic

logger = logging.getLogger(__name__)


class ReplaySourceError(Exception):
    """Base exception for replay source errors."""
    pass


class ReplaySourceFormatError(ReplaySourceError):
    """Raised when source file format is invalid."""
    pass


class ReplaySourceConsistencyError(ReplaySourceError):
    """Raised when replay source has consistency issues."""
    pass


class ReplaySource:
    """
    Deterministic replay source reader.
    
    Reads JSONL files where each line contains a serialized event.
    Events are yielded in order of exchange_ts_ns (monotonic).
    
    Format:
        Each line is a JSON object with:
        - event_type: string (must match EventType values)
        - exchange_ts_ns: integer (nanoseconds)
        - payload: object (event-specific data)
    
    For ties in exchange_ts_ns, original line order is preserved.
    
    Source files must be read-only and deterministic.
    """
    
    def __init__(
        self,
        source_path: Union[str, Path],
        source_type: SourceType = SourceType.JSONL,
        validate_monotonic: bool = True
    ):
        """
        Initialize replay source reader.
        
        Args:
            source_path: Path to replay source file
            source_type: Format of source file (JSONL only for Stage 0)
            validate_monotonic: Whether to validate timestamp monotonicity
        
        Raises:
            ReplaySourceFormatError: If source_type is not JSONL or file not found
        """
        self.source_path = Path(source_path)
        self.source_type = source_type
        self.validate_monotonic = validate_monotonic
        
        if not self.source_path.exists():
            raise ReplaySourceFormatError(f"Source file not found: {self.source_path}")
        
        if source_type != SourceType.JSONL:
            raise ReplaySourceFormatError(
                f"Stage 0 supports only JSONL, got {source_type}"
            )
        
        self._event_count = 0
        self._last_timestamp_ns: Optional[int] = None
        self._file_handle: Optional[Any] = None
        
        logger.info(f"ReplaySource initialized: {self.source_path}")
    
    def __enter__(self):
        """Open file handle for iteration."""
        self._file_handle = open(self.source_path, 'r', encoding='utf-8')
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Close file handle."""
        if self._file_handle:
            self._file_handle.close()
            self._file_handle = None
    
    def __iter__(self) -> Iterator[EventEnvelope]:
        """
        Iterate over events in source file in order.
        
        Events are sorted by exchange_ts_ns, with ties broken by line number.
        
        Returns:
            Iterator of EventEnvelope objects
        
        Raises:
            ReplaySourceFormatError: On malformed JSON or missing fields
            ReplaySourceConsistencyError: On timestamp non-monotonic (if validation enabled)
        """
        if self._file_handle is None:
            raise ReplaySourceError("Source not opened. Use context manager (with statement).")
        
        # Reset state for iteration
        self._event_count = 0
        self._last_timestamp_ns = None
        
        # Read all lines and collect with line numbers
        lines: List[Tuple[int, int, EventType, Dict[str, Any]]] = []
        for line_num, line in enumerate(self._file_handle, 1):
            line = line.strip()
            if not line:
                continue
            
            try:
                data = json.loads(line)
            except json.JSONDecodeError as e:
                raise ReplaySourceFormatError(
                    f"Line {line_num}: Invalid JSON - {e}"
                )
            
            # Validate required fields
            if 'event_type' not in data:
                raise ReplaySourceFormatError(
                    f"Line {line_num}: Missing 'event_type' field"
                )
            
            if 'exchange_ts_ns' not in data:
                raise ReplaySourceFormatError(
                    f"Line {line_num}: Missing 'exchange_ts_ns' field"
                )
            
            if 'payload' not in data:
                raise ReplaySourceFormatError(
                    f"Line {line_num}: Missing 'payload' field"
                )
            
            ts_ns = data['exchange_ts_ns']
            
            # Validate timestamp type and range
            if not isinstance(ts_ns, int):
                raise ReplaySourceFormatError(
                    f"Line {line_num}: exchange_ts_ns must be integer, got {type(ts_ns).__name__}"
                )
            
            if ts_ns < 0:
                raise ReplaySourceFormatError(
                    f"Line {line_num}: exchange_ts_ns cannot be negative: {ts_ns}"
                )
            
            # Parse event_type
            try:
                event_type = EventType(data['event_type'])
            except ValueError:
                raise ReplaySourceFormatError(
                    f"Line {line_num}: Unknown event_type '{data['event_type']}'"
                )
            
            lines.append((ts_ns, line_num, event_type, data['payload']))
        
        # Sort by exchange_ts_ns, then line number for determinism
        lines.sort(key=lambda x: (x[0], x[1]))
        
        # Yield events in order
        for ts_ns, line_num, event_type, payload in lines:
            # Validate monotonicity
            if self.validate_monotonic:
                valid, reason = is_monotonic(self._last_timestamp_ns, ts_ns)
                if not valid:
                    raise ReplaySourceConsistencyError(
                        f"Timestamp non-monotonic at line {line_num}: {reason}"
                    )
            
            self._last_timestamp_ns = ts_ns
            
            # Parse payload into typed event model with the actual timestamp
            typed_event = self._parse_payload(event_type, payload, ts_ns, line_num)
            
            # Wrap in EventEnvelope with deterministic receive_ts_ns
            # During replay, receive_ts_ns = exchange_ts_ns (no wall clock)
            envelope = EventEnvelope(
                event_type=event_type,
                source_module="replay_source",
                exchange_ts_ns=ts_ns,
                receive_ts_ns=ts_ns,  # Deterministic: use exchange timestamp
                payload=typed_event.dict() if hasattr(typed_event, 'dict') else typed_event,
                decision_uuid=None,
                decision_ts_ns=0
            )
            
            self._event_count += 1
            yield envelope
    
    def _parse_payload(
        self,
        event_type: EventType,
        payload: Dict[str, Any],
        exchange_ts_ns: int,
        line_num: int
    ) -> Any:
        """
        Parse payload into typed event model with the actual timestamp.
        
        Payload contains event-specific fields only (no base event fields).
        Base fields (event_type, exchange_ts_ns, receive_ts_ns) are provided
        explicitly to construct the typed event with correct timestamps.
        
        Args:
            event_type: Type of event
            payload: Raw payload dictionary
            exchange_ts_ns: Exchange timestamp in nanoseconds
            line_num: Line number for error reporting
        
        Returns:
            Typed event model
        
        Raises:
            ReplaySourceFormatError: On invalid payload
        """
        try:
            if event_type == EventType.TRADE:
                return TradeEvent(
                    event_type=EventType.TRADE,
                    source_module="replay_source",
                    exchange_ts_ns=exchange_ts_ns,
                    receive_ts_ns=exchange_ts_ns,  # Deterministic replay
                    **payload
                )
            elif event_type == EventType.QUOTE:
                return QuoteEvent(
                    event_type=EventType.QUOTE,
                    source_module="replay_source",
                    exchange_ts_ns=exchange_ts_ns,
                    receive_ts_ns=exchange_ts_ns,
                    **payload
                )
            elif event_type == EventType.ORDER_BOOK_SNAPSHOT:
                return OrderBookSnapshotEvent(
                    event_type=EventType.ORDER_BOOK_SNAPSHOT,
                    source_module="replay_source",
                    exchange_ts_ns=exchange_ts_ns,
                    receive_ts_ns=exchange_ts_ns,
                    **payload
                )
            elif event_type == EventType.ORDER_BOOK_DELTA:
                return OrderBookDeltaEvent(
                    event_type=EventType.ORDER_BOOK_DELTA,
                    source_module="replay_source",
                    exchange_ts_ns=exchange_ts_ns,
                    receive_ts_ns=exchange_ts_ns,
                    **payload
                )
            elif event_type == EventType.CLOCK_TICK:
                return ClockTickEvent(
                    event_type=EventType.CLOCK_TICK,
                    source_module="replay_source",
                    exchange_ts_ns=exchange_ts_ns,
                    receive_ts_ns=exchange_ts_ns,
                    **payload
                )
            else:
                # For other event types, return raw payload
                # These may include derived events that use different schemas
                return payload
        except Exception as e:
            raise ReplaySourceFormatError(
                f"Line {line_num}: Invalid payload for {event_type.value}: {e}"
            )
    
    def get_event_count(self) -> int:
        """
        Get number of events yielded in current iteration.
        
        Returns:
            Event count
        """
        return self._event_count
    
    def get_source_info(self) -> Dict[str, Any]:
        """
        Get information about the source file.
        
        Returns:
            Dictionary with source metadata
        """
        stat = self.source_path.stat() if self.source_path.exists() else None
        return {
            "path": str(self.source_path),
            "source_type": self.source_type.value,
            "exists": self.source_path.exists(),
            "size_bytes": stat.st_size if stat else 0,
            "modified_at": stat.st_mtime if stat else None,
            "validate_monotonic": self.validate_monotonic,
        }
    
    @staticmethod
    def create_test_source(events: List[Tuple[Union[EventType, str], int, Dict[str, Any]]]) -> 'ReplaySource':
        """
        Create a test replay source from in-memory events.
        
        This is primarily for testing. Writes events to a temporary JSONL file.
        
        Args:
            events: List of (event_type, exchange_ts_ns, payload) tuples
                   event_type can be EventType enum or string
        
        Returns:
            ReplaySource instance
        
        Raises:
            ReplaySourceError: If test source creation fails
        """
        tmp_path = None
        try:
            # Create temporary file with .jsonl extension
            fd, tmp_path = tempfile.mkstemp(suffix='.jsonl', text=True)
            # Use os.fdopen to get file object, then close descriptor after
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                for event_type, ts_ns, payload in events:
                    # Convert enum to string if needed
                    if hasattr(event_type, 'value'):
                        type_str = event_type.value
                    else:
                        type_str = str(event_type)
                    
                    line = json.dumps({
                        'event_type': type_str,
                        'exchange_ts_ns': ts_ns,
                        'payload': payload
                    })
                    f.write(line + '\n')
            
            # Return ReplaySource with the path
            return ReplaySource(tmp_path)
        except Exception as e:
            # Clean up on error
            if tmp_path and Path(tmp_path).exists():
                try:
                    Path(tmp_path).unlink()
                except Exception:
                    pass
            raise ReplaySourceError(f"Failed to create test source: {e}")


# ============================================
# Convenience Functions
# ============================================

def open_replay_source(
    source_path: Union[str, Path],
    validate_monotonic: bool = True
) -> ReplaySource:
    """
    Open a replay source for reading.
    
    Args:
        source_path: Path to replay source file
        validate_monotonic: Whether to validate timestamp monotonicity
    
    Returns:
        ReplaySource instance
    
    Raises:
        ReplaySourceFormatError: If source format is invalid
    """
    return ReplaySource(
        source_path=source_path,
        source_type=SourceType.JSONL,
        validate_monotonic=validate_monotonic
    )


__all__ = [
    'ReplaySource',
    'ReplaySourceError',
    'ReplaySourceFormatError',
    'ReplaySourceConsistencyError',
    'open_replay_source',
]