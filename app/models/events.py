"""
Event-Specific Models for Sovereign Trading System

This file defines specialized event types that complement the canonical contracts
in contracts.py. These are used for:
- Stage 0 replay: market data events (trade, quote, order book)
- System events: heartbeat monitoring, audit logs
- Replay control: start/end markers

All raw market data events follow the same causality rules as EventEnvelope:
- decision_uuid = None
- decision_ts_ns = 0
- parent_uuid = None

These models do NOT replace the canonical contracts. They are separate
and are typically wrapped in EventEnvelope for system-wide event bus.

This file requires EventType.HEARTBEAT, EventType.REPLAY_START,
and EventType.REPLAY_END to be present in app/models/enums.py.
"""

from decimal import Decimal
from typing import Optional, Dict, List, Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import (
    EventType, OrderSide, AlertSeverity, ReplayMode, SourceType
)
from app.utils.decimal_utils import (
    crypto, usd, price, to_canonical_string,
    CRYPTO_PRECISION, USD_PRECISION, PRICE_PRECISION
)
from app.utils.time_utils import now_ns


# ============================================
# BASE EVENT (Shared Fields)
# ============================================

class BaseEvent(BaseModel):
    """
    Base class for all events.
    Provides common fields and validation.
    """

    model_config = ConfigDict(use_enum_values=True)

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: EventType
    source_module: str
    exchange_ts_ns: int
    receive_ts_ns: int = Field(default_factory=now_ns)
    schema_version: int = Field(default=1)

    @field_validator('exchange_ts_ns', 'receive_ts_ns', mode='before')
    @classmethod
    def validate_timestamp_non_negative(cls, v):
        if v < 0:
            raise ValueError(f"Timestamp cannot be negative: {v}")
        return v

    @field_validator('schema_version', mode='before')
    @classmethod
    def validate_version(cls, v):
        if v <= 0:
            raise ValueError(f"schema_version must be positive: {v}")
        return v

    @model_validator(mode='after')
    def validate_receive_after_exchange(self):
        if self.receive_ts_ns < self.exchange_ts_ns:
            raise ValueError(
                f"receive_ts_ns ({self.receive_ts_ns}) < exchange_ts_ns ({self.exchange_ts_ns})"
            )
        return self


# ============================================
# MARKET DATA EVENTS (Raw External)
# ============================================

class TradeEvent(BaseEvent):
    """Individual trade execution event."""

    model_config = ConfigDict(use_enum_values=True)

    event_type: EventType = EventType.TRADE
    symbol: str
    price: Decimal
    quantity: Decimal
    side: OrderSide
    trade_id: str
    aggressor: Optional[bool] = None  # True = buy side initiated

    @field_validator('price', mode='before')
    @classmethod
    def validate_price(cls, v):
        return price(v)

    @field_validator('quantity', mode='before')
    @classmethod
    def validate_quantity(cls, v):
        return crypto(v)


class QuoteEvent(BaseEvent):
    """Best bid/ask quote event."""

    event_type: EventType = EventType.QUOTE
    symbol: str
    bid_price: Decimal
    bid_size: Decimal
    ask_price: Decimal
    ask_size: Decimal

    @field_validator('bid_price', 'ask_price', mode='before')
    @classmethod
    def validate_price(cls, v):
        return price(v)

    @field_validator('bid_size', 'ask_size', mode='before')
    @classmethod
    def validate_size(cls, v):
        return crypto(v)


class OrderBookLevel(BaseModel):
    """Single level in order book."""
    price: Decimal
    size: Decimal

    @field_validator('price', mode='before')
    @classmethod
    def validate_price(cls, v):
        return price(v)

    @field_validator('size', mode='before')
    @classmethod
    def validate_size(cls, v):
        return crypto(v)


class OrderBookSnapshotEvent(BaseEvent):
    """Full order book snapshot."""

    event_type: EventType = EventType.ORDER_BOOK_SNAPSHOT
    symbol: str
    bids: List[OrderBookLevel] = Field(default_factory=list)
    asks: List[OrderBookLevel] = Field(default_factory=list)
    sequence: int = Field(default=0, description="Exchange sequence number")

    @field_validator('sequence', mode='before')
    @classmethod
    def validate_sequence(cls, v):
        if v < 0:
            raise ValueError(f"sequence cannot be negative: {v}")
        return v


class OrderBookDeltaEvent(BaseEvent):
    """Order book delta (update)."""

    event_type: EventType = EventType.ORDER_BOOK_DELTA
    symbol: str
    bids: List[OrderBookLevel] = Field(default_factory=list)  # New/updated levels
    asks: List[OrderBookLevel] = Field(default_factory=list)  # New/updated levels
    bid_removals: List[Decimal] = Field(default_factory=list)  # Prices to remove
    ask_removals: List[Decimal] = Field(default_factory=list)  # Prices to remove
    sequence: int = Field(default=0, description="Exchange sequence number")

    @field_validator('sequence', mode='before')
    @classmethod
    def validate_sequence(cls, v):
        if v < 0:
            raise ValueError(f"sequence cannot be negative: {v}")
        return v

    @field_validator('bid_removals', 'ask_removals', mode='before')
    @classmethod
    def validate_removal_prices(cls, v):
        if v is None:
            return v
        return [price(item) for item in v]


class ClockTickEvent(BaseEvent):
    """Synthetic clock tick for deterministic replay."""

    event_type: EventType = EventType.CLOCK_TICK
    tick_number: int = Field(default=0, description="Tick counter since start")
    elapsed_ns: int = Field(default=0, description="Elapsed nanoseconds from start")

    @field_validator('tick_number', mode='before')
    @classmethod
    def validate_tick(cls, v):
        if v < 0:
            raise ValueError(f"tick_number cannot be negative: {v}")
        return v

    @field_validator('elapsed_ns', mode='before')
    @classmethod
    def validate_elapsed(cls, v):
        if v < 0:
            raise ValueError(f"elapsed_ns cannot be negative: {v}")
        return v


# ============================================
# AUDIT EVENT
# ============================================

class AuditEvent(BaseEvent):
    """
    Audit log entry for forensic analysis.
    
    This event captures system-level audit information including:
    - Configuration changes
    - Manual interventions
    - Security events
    - Compliance records
    """

    model_config = ConfigDict(use_enum_values=True)

    event_type: EventType = EventType.AUDIT_EVENT
    severity: AlertSeverity
    message: str
    decision_uuid: Optional[str] = Field(None, description="Linked decision UUID if applicable")
    data: Dict[str, Any] = Field(default_factory=dict)

    @field_validator('decision_uuid', mode='before')
    @classmethod
    def validate_decision_uuid(cls, v):
        # Audit events may have decision_uuid = None for system logs
        return v


# ============================================
# HEARTBEAT EVENT
# ============================================

class HeartbeatEvent(BaseEvent):
    """
    System heartbeat for monitoring.
    
    CONSTITUTIONAL EXCEPTION: latency_ms uses float for telemetry only.
    Core accounting and replay paths use integer nanoseconds exclusively.
    This float field is explicitly isolated and cannot contaminate monetary truth.
    """

    event_type: EventType = EventType.HEARTBEAT
    components_healthy: Dict[str, bool] = Field(default_factory=dict)
    latency_ms: float = Field(default=0.0, description="Monitoring telemetry only - CONSTITUTIONAL EXCEPTION")
    queue_sizes: Dict[str, int] = Field(default_factory=dict)

    @field_validator('latency_ms', mode='before')
    @classmethod
    def validate_latency(cls, v):
        if v < 0:
            raise ValueError(f"latency_ms cannot be negative: {v}")
        if v > 300000:  # 5 minutes maximum reasonable latency
            raise ValueError(f"latency_ms unreasonably high: {v} ms")
        return v

    @field_validator('queue_sizes', mode='before')
    @classmethod
    def validate_queue_sizes(cls, v):
        if v is None:
            return v
        for key, size in v.items():
            if size < 0:
                raise ValueError(f"queue size cannot be negative: {size}")
            if size > 1000000:  # 1M items maximum per queue
                raise ValueError(f"queue size unreasonably large: {size}")
        return v


# ============================================
# REPLAY CONTROL EVENTS
# ============================================

class ReplayStartEvent(BaseEvent):
    """Marks the beginning of a replay session."""

    model_config = ConfigDict(use_enum_values=True)

    event_type: EventType = EventType.REPLAY_START
    replay_mode: ReplayMode
    source_path: str
    source_type: SourceType
    start_timestamp_ns: int
    end_timestamp_ns: Optional[int] = None
    replay_seed: int = Field(default=0, description="Random seed for deterministic replay")

    @field_validator('start_timestamp_ns', 'end_timestamp_ns', mode='before')
    @classmethod
    def validate_timestamp(cls, v):
        if v is not None and v <= 0:
            raise ValueError(f"Timestamp must be positive: {v}")
        return v

    @field_validator('replay_seed', mode='before')
    @classmethod
    def validate_seed(cls, v):
        if v < 0:
            raise ValueError(f"replay_seed cannot be negative: {v}")
        return v

    @model_validator(mode='after')
    def validate_timestamp_ordering(self):
        start = self.start_timestamp_ns
        end = self.end_timestamp_ns
        if end is not None and end <= start:
            raise ValueError(
                f"end_timestamp_ns ({end}) must be greater than start_timestamp_ns ({start})"
            )
        return self


class ReplayEndEvent(BaseEvent):
    """Marks the end of a replay session."""

    model_config = ConfigDict(use_enum_values=True)

    event_type: EventType = EventType.REPLAY_END
    replay_mode: ReplayMode
    events_processed: int
    duration_ns: int
    checksum: str
    verification_passed: bool

    @field_validator('events_processed', 'duration_ns', mode='before')
    @classmethod
    def validate_positive(cls, v):
        if v < 0:
            raise ValueError(f"Value cannot be negative: {v}")
        return v


# ============================================
# EXPORTS
# ============================================

__all__ = [
    # Base
    'BaseEvent',
    # Market Data Events
    'TradeEvent',
    'QuoteEvent',
    'OrderBookLevel',
    'OrderBookSnapshotEvent',
    'OrderBookDeltaEvent',
    'ClockTickEvent',
    # Audit Event
    'AuditEvent',
    # System Events
    'HeartbeatEvent',
    # Replay Control Events
    'ReplayStartEvent',
    'ReplayEndEvent',
]