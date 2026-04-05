"""
Event Normalizer for Sovereign Trading System

This module validates and filters replay event envelopes to enforce replay purity.
All events entering the replay pipeline must pass through this normalizer.

Replay Purity Rules Enforced:
- Raw external events: receive_ts_ns must equal exchange_ts_ns (no wall clock reads)
- Raw external events: decision_uuid = None, decision_ts_ns = 0
- Derived events: decision_uuid != None, decision_ts_ns > 0
- Optional timestamp monotonicity validation

This module performs validation and filtering, not schema transformation.
"""

import logging
from typing import Optional, Iterator, Dict, Any, List, Union

from app.models.enums import EventType
from app.models.contracts import EventEnvelope
from app.utils.time_utils import is_monotonic

logger = logging.getLogger(__name__)


class EventNormalizerError(Exception):
    """Base exception for event normalizer errors."""
    pass


class EventNormalizerValidationError(EventNormalizerError):
    """Raised when event validation fails."""
    pass


class NormalizerStats:
    """Statistics for event normalization."""
    
    def __init__(self):
        self.total_events = 0
        self.valid_events = 0
        self.invalid_events = 0
        self.filtered_events = 0
        self.last_timestamp_ns: Optional[int] = None
        self.last_event_type: Optional[EventType] = None
    
    def reset(self) -> None:
        """Reset statistics."""
        self.total_events = 0
        self.valid_events = 0
        self.invalid_events = 0
        self.filtered_events = 0
        self.last_timestamp_ns = None
        self.last_event_type = None


class EventNormalizer:
    """
    Validates and filters replay event envelopes.
    
    Features:
    - Validates timestamp monotonicity
    - Validates receive_ts_ns == exchange_ts_ns for raw replay events
    - Validates causality rules (decision_uuid vs decision_ts_ns)
    - Optional event type filtering
    - Configurable error handling (fail-fast or continue-on-error)
    """
    
    def __init__(
        self,
        validate_monotonic: bool = True,
        validate_receive_timestamp: bool = True,
        allowed_event_types: Optional[List[EventType]] = None,
        filter_event_types: Optional[List[EventType]] = None,
        fail_fast: bool = True
    ):
        """
        Initialize event normalizer.
        
        Args:
            validate_monotonic: Whether to validate timestamp monotonicity
            validate_receive_timestamp: Whether to require receive_ts_ns == exchange_ts_ns
            allowed_event_types: If provided, only these event types are allowed
            filter_event_types: If provided, these event types are filtered out
            fail_fast: If True, raise on validation errors; if False, log and continue
        """
        self.validate_monotonic = validate_monotonic
        self.validate_receive_timestamp = validate_receive_timestamp
        self.allowed_event_types = set(allowed_event_types) if allowed_event_types else None
        self.filter_event_types = set(filter_event_types) if filter_event_types else None
        self.fail_fast = fail_fast
        
        self._stats = NormalizerStats()
        self._last_timestamp_ns: Optional[int] = None
        
        logger.info(
            f"EventNormalizer initialized: validate_monotonic={validate_monotonic}, "
            f"validate_receive_timestamp={validate_receive_timestamp}, "
            f"fail_fast={fail_fast}, allowed={allowed_event_types}, filter={filter_event_types}"
        )
    
    def normalize(self, envelope: EventEnvelope) -> Optional[EventEnvelope]:
        """
        Validate and filter a single event envelope.
        
        Args:
            envelope: Raw event envelope from replay source
        
        Returns:
            Validated event envelope, or None if filtered out
        
        Raises:
            EventNormalizerValidationError: On validation failure when fail_fast=True
        """
        self._stats.total_events += 1
        
        # Apply filtering rules
        if self.allowed_event_types and envelope.event_type not in self.allowed_event_types:
            self._stats.filtered_events += 1
            logger.debug(f"Filtered event by allowed list: {envelope.event_type}")
            return None
        
        if self.filter_event_types and envelope.event_type in self.filter_event_types:
            self._stats.filtered_events += 1
            logger.debug(f"Filtered event by filter list: {envelope.event_type}")
            return None
        
        # Validate timestamp monotonicity
        if self.validate_monotonic:
            valid, reason = is_monotonic(self._last_timestamp_ns, envelope.exchange_ts_ns)
            if not valid:
                self._stats.invalid_events += 1
                error_msg = f"Timestamp monotonicity failed for {envelope.event_type}: {reason}"
                if self.fail_fast:
                    raise EventNormalizerValidationError(error_msg)
                else:
                    logger.error(error_msg)
                    return None
        
        self._last_timestamp_ns = envelope.exchange_ts_ns
        self._stats.last_timestamp_ns = envelope.exchange_ts_ns
        self._stats.last_event_type = envelope.event_type
        
        # Validate causality rules
        if envelope.decision_uuid is None:
            # Raw external event: decision_ts_ns must be 0
            if envelope.decision_ts_ns != 0:
                self._stats.invalid_events += 1
                error_msg = (
                    f"Raw event {envelope.event_type} has decision_uuid=None but "
                    f"decision_ts_ns={envelope.decision_ts_ns} (expected 0)"
                )
                if self.fail_fast:
                    raise EventNormalizerValidationError(error_msg)
                else:
                    logger.error(error_msg)
                    return None
        else:
            # Derived event: decision_ts_ns must be > 0
            if envelope.decision_ts_ns <= 0:
                self._stats.invalid_events += 1
                error_msg = (
                    f"Derived event {envelope.event_type} has decision_uuid={envelope.decision_uuid} "
                    f"but decision_ts_ns={envelope.decision_ts_ns} (expected > 0)"
                )
                if self.fail_fast:
                    raise EventNormalizerValidationError(error_msg)
                else:
                    logger.error(error_msg)
                    return None
        
        # Validate receive timestamp equals exchange timestamp (replay purity)
        if self.validate_receive_timestamp:
            if envelope.receive_ts_ns != envelope.exchange_ts_ns:
                self._stats.invalid_events += 1
                error_msg = (
                    f"Raw replay event {envelope.event_type}: receive_ts_ns ({envelope.receive_ts_ns}) "
                    f"!= exchange_ts_ns ({envelope.exchange_ts_ns}) — violates replay purity (RP-01)"
                )
                if self.fail_fast:
                    raise EventNormalizerValidationError(error_msg)
                else:
                    logger.error(error_msg)
                    return None
        
        self._stats.valid_events += 1
        return envelope
    
    def normalize_stream(
        self,
        envelopes: Iterator[EventEnvelope]
    ) -> Iterator[EventEnvelope]:
        """
        Validate and filter a stream of event envelopes.
        
        Behavior depends on fail_fast setting:
        - fail_fast=True: Raises on first validation error
        - fail_fast=False: Logs errors and continues, skipping invalid events
        
        Args:
            envelopes: Iterator of raw event envelopes
        
        Yields:
            Validated event envelopes (filtered events are skipped)
        
        Raises:
            EventNormalizerValidationError: On validation failure when fail_fast=True
        """
        self.reset_stats()
        
        for envelope in envelopes:
            try:
                normalized = self.normalize(envelope)
                if normalized is not None:
                    yield normalized
            except EventNormalizerValidationError:
                if self.fail_fast:
                    raise
                # Continue processing other events when fail_fast=False
                continue
    
    def reset_stats(self) -> None:
        """Reset normalization statistics."""
        self._stats.reset()
        self._last_timestamp_ns = None
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get normalization statistics.
        
        Returns:
            Dictionary with statistics
        """
        return {
            "total_events": self._stats.total_events,
            "valid_events": self._stats.valid_events,
            "invalid_events": self._stats.invalid_events,
            "filtered_events": self._stats.filtered_events,
            "last_timestamp_ns": self._stats.last_timestamp_ns,
            "last_event_type": self._stats.last_event_type.value if self._stats.last_event_type else None,
        }


# ============================================
# Convenience Functions
# ============================================

def normalize_event(
    envelope: EventEnvelope,
    validate_monotonic: bool = True,
    validate_receive_timestamp: bool = True,
    fail_fast: bool = True
) -> Optional[EventEnvelope]:
    """
    Normalize a single event envelope using default normalizer.
    
    Args:
        envelope: Raw event envelope
        validate_monotonic: Whether to validate timestamp monotonicity
        validate_receive_timestamp: Whether to require receive_ts_ns == exchange_ts_ns
        fail_fast: If True, raise on validation errors
    
    Returns:
        Validated event envelope, or None if filtered
    
    Raises:
        EventNormalizerValidationError: On validation failure when fail_fast=True
    """
    normalizer = EventNormalizer(
        validate_monotonic=validate_monotonic,
        validate_receive_timestamp=validate_receive_timestamp,
        fail_fast=fail_fast
    )
    return normalizer.normalize(envelope)


def normalize_events(
    envelopes: Iterator[EventEnvelope],
    validate_monotonic: bool = True,
    validate_receive_timestamp: bool = True,
    allowed_event_types: Optional[List[EventType]] = None,
    filter_event_types: Optional[List[EventType]] = None,
    fail_fast: bool = True
) -> Iterator[EventEnvelope]:
    """
    Normalize a stream of event envelopes.
    
    Args:
        envelopes: Iterator of raw event envelopes
        validate_monotonic: Whether to validate timestamp monotonicity
        validate_receive_timestamp: Whether to require receive_ts_ns == exchange_ts_ns
        allowed_event_types: If provided, only these event types are allowed
        filter_event_types: If provided, these event types are filtered out
        fail_fast: If True, raise on first validation error
    
    Yields:
        Validated event envelopes
    
    Raises:
        EventNormalizerValidationError: On validation failure when fail_fast=True
    """
    normalizer = EventNormalizer(
        validate_monotonic=validate_monotonic,
        validate_receive_timestamp=validate_receive_timestamp,
        allowed_event_types=allowed_event_types,
        filter_event_types=filter_event_types,
        fail_fast=fail_fast
    )
    yield from normalizer.normalize_stream(envelopes)


def create_market_data_normalizer(fail_fast: bool = True) -> EventNormalizer:
    """
    Create a normalizer configured for market data events only.
    
    Args:
        fail_fast: If True, raise on validation errors
    
    Returns:
        EventNormalizer configured for market data
    """
    market_event_types = [
        EventType.TRADE,
        EventType.QUOTE,
        EventType.ORDER_BOOK_SNAPSHOT,
        EventType.ORDER_BOOK_DELTA,
        EventType.CLOCK_TICK,
    ]
    return EventNormalizer(
        validate_monotonic=True,
        validate_receive_timestamp=True,
        allowed_event_types=market_event_types,
        fail_fast=fail_fast
    )


def create_system_event_normalizer(fail_fast: bool = True) -> EventNormalizer:
    """
    Create a normalizer configured for system events (audit, heartbeat, replay control).
    
    System events include:
    - AUDIT_EVENT: Audit logs
    - HEARTBEAT: System heartbeat monitoring
    - REPLAY_START: Replay session start
    - REPLAY_END: Replay session end
    
    Args:
        fail_fast: If True, raise on validation errors
    
    Returns:
        EventNormalizer configured for system events
    """
    system_event_types = [
        EventType.AUDIT_EVENT,
        EventType.HEARTBEAT,
        EventType.REPLAY_START,
        EventType.REPLAY_END,
    ]
    return EventNormalizer(
        validate_monotonic=True,
        validate_receive_timestamp=True,
        allowed_event_types=system_event_types,
        fail_fast=fail_fast
    )


__all__ = [
    'EventNormalizer',
    'EventNormalizerError',
    'EventNormalizerValidationError',
    'NormalizerStats',
    'normalize_event',
    'normalize_events',
    'create_market_data_normalizer',
    'create_system_event_normalizer',
]