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

from pydantic import BaseModel, Field, validator, root_validator

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
    
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: EventType
    source_module: str
    exchange_ts_ns: int
    receive_ts_ns: int = Field(default_factory=now_ns)
    schema_version: int = Field(default=1)

    @validator('exchange_ts_ns', 'receive_ts_ns')
    def validate_timestamp_non_negative(cls, v):
        if v < 0:
            raise ValueError(f"Timestamp cannot be negative: {v}")
        return v

    @validator('receive_ts_ns')
    def validate_receive_after_exchange(cls, v, values):
        if 'exchange_ts_ns' in values and v < values['exchange_ts_ns']:
            raise ValueError(f"receive_ts_ns ({v}) < exchange_ts_ns ({values['exchange_ts_ns']})")
        return v

    @validator('schema_version')
    def validate_version(cls, v):
        if v <= 0:
            raise ValueError(f"schema_version must be positive: {v}")
        return v

    class Config:
        use_enum_values = True


# ============================================
# MARKET DATA EVENTS (Raw External)
# ============================================

class TradeEvent(BaseEvent):
    """Individual trade execution event."""
    
    event_type: EventType = EventType.TRADE
    symbol: str
    price: Decimal
    quantity: Decimal
    side: OrderSide
    trade_id: str
    aggressor: Optional[bool] = None  # True = buy side initiated

    @validator('price')
    def validate_price(cls, v):
        return price(v)

    @validator('quantity')
    def validate_quantity(cls, v):
        return crypto(v)

    class Config:
        use_enum_values = True


class QuoteEvent(BaseEvent):
    """Best bid/ask quote event."""
    
    event_type: EventType = EventType.QUOTE
    symbol: str
    bid_price: Decimal
    bid_size: Decimal
    ask_price: Decimal
    ask_size: Decimal

    @validator('bid_price', 'ask_price')
    def validate_price(cls, v):
        return price(v)

    @validator('bid_size', 'ask_size')
    def validate_size(cls, v):
        return crypto(v)


class OrderBookLevel(BaseModel):
    """Single level in order book."""
    price: Decimal
    size: Decimal

    @validator('price')
    def validate_price(cls, v):
        return price(v)

    @validator('size')
    def validate_size(cls, v):
        return crypto(v)


class OrderBookSnapshotEvent(BaseEvent):
    """Full order book snapshot."""
    
    event_type: EventType = EventType.ORDER_BOOK_SNAPSHOT
    symbol: str
    bids: List[OrderBookLevel] = Field(default_factory=list)
    asks: List[OrderBookLevel] = Field(default_factory=list)
    sequence: int = Field(default=0, description="Exchange sequence number")

    @validator('sequence')
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

    @validator('sequence')
    def validate_sequence(cls, v):
        if v < 0:
            raise ValueError(f"sequence cannot be negative: {v}")
        return v

    @validator('bid_removals', 'ask_removals', each_item=True)
    def validate_removal_price(cls, v):
        return price(v)


class ClockTickEvent(BaseEvent):
    """Synthetic clock tick for deterministic replay."""
    
    event_type: EventType = EventType.CLOCK_TICK
    tick_number: int = Field(default=0, description="Tick counter since start")
    elapsed_ns: int = Field(default=0, description="Elapsed nanoseconds from start")

    @validator('tick_number')
    def validate_tick(cls, v):
        if v < 0:
            raise ValueError(f"tick_number cannot be negative: {v}")
        return v

    @validator('elapsed_ns')
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
    
    event_type: EventType = EventType.AUDIT_EVENT
    severity: AlertSeverity
    message: str
    decision_uuid: Optional[str] = Field(None, description="Linked decision UUID if applicable")
    data: Dict[str, Any] = Field(default_factory=dict)

    @validator('decision_uuid')
    def validate_decision_uuid(cls, v):
        # Audit events may have decision_uuid = None for system logs
        return v

    class Config:
        use_enum_values = True


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

    @validator('latency_ms')
    def validate_latency(cls, v):
        if v < 0:
            raise ValueError(f"latency_ms cannot be negative: {v}")
        if v > 300000:  # 5 minutes maximum reasonable latency
            raise ValueError(f"latency_ms unreasonably high: {v} ms")
        return v

    @validator('queue_sizes', each_item=True)
    def validate_queue_size(cls, v):
        if v < 0:
            raise ValueError(f"queue size cannot be negative: {v}")
        if v > 1000000:  # 1M items maximum per queue
            raise ValueError(f"queue size unreasonably large: {v}")
        return v


# ============================================
# REPLAY CONTROL EVENTS
# ============================================

class ReplayStartEvent(BaseEvent):
    """Marks the beginning of a replay session."""
    
    event_type: EventType = EventType.REPLAY_START
    replay_mode: ReplayMode
    source_path: str
    source_type: SourceType
    start_timestamp_ns: int
    end_timestamp_ns: Optional[int] = None
    replay_seed: int = Field(default=0, description="Random seed for deterministic replay")

    @validator('start_timestamp_ns', 'end_timestamp_ns')
    def validate_timestamp(cls, v):
        if v is not None and v <= 0:
            raise ValueError(f"Timestamp must be positive: {v}")
        return v

    @validator('replay_seed')
    def validate_seed(cls, v):
        if v < 0:
            raise ValueError(f"replay_seed cannot be negative: {v}")
        return v

    @root_validator
    def validate_timestamp_ordering(cls, values):
        start = values.get('start_timestamp_ns')
        end = values.get('end_timestamp_ns')
        
        if end is not None and end <= start:
            raise ValueError(f"end_timestamp_ns ({end}) must be greater than start_timestamp_ns ({start})")
        
        return values


class ReplayEndEvent(BaseEvent):
    """Marks the end of a replay session."""
    
    event_type: EventType = EventType.REPLAY_END
    replay_mode: ReplayMode
    events_processed: int
    duration_ns: int
    checksum: str
    verification_passed: bool

    @validator('events_processed', 'duration_ns')
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
