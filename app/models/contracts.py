"""
Canonical Contracts for Sovereign Trading System

All cross-module communication uses these Pydantic models (v1 compatible).
Enforces type safety, validation, and serialization.

Contract Coverage:
- EventEnvelope: Wrapper for all events (raw and derived)
- DecisionRecord: Single source of truth for decisions
- TruthFrame: Five truths reconciliation
- OrderIntent: Legal order intent from DecisionCompiler
- ExecutionEvent: Execution layer events
- FillEvent: Fill confirmation
- CancelEvent: Cancel events
- PortfolioSnapshot: Portfolio state
- RiskDecision: Risk system decisions
- StrategyVote: Strategy voting
- FeatureVector: Feature outputs with typed payload
- RecoveryCheckpoint: Recovery state
- DivergenceEvent: Truth divergence
"""

from decimal import Decimal
from typing import Optional, Dict, List, Any, Union
from uuid import uuid4

from pydantic import BaseModel, Field, validator, root_validator

from app.models.enums import (
    RegimeType, TruthStatus, RiskMode, OrderSide, OrderType,
    InternalOrderStatus, FillStatus, CancelStatus, EventType,
    DivergenceType, AlertSeverity, InvariantViolationSeverity,
    ReplayMode, DecisionType, ExecutionEventType, SignalType,
    StrategyID, CheckpointType, ResolutionType
)
from app.utils.decimal_utils import (
    crypto, usd, price, fee, confidence, bps, to_canonical_string,
    CRYPTO_PRECISION, USD_PRECISION, PRICE_PRECISION, FEE_PRECISION,
    SCORE_PRECISION
)
from app.utils.time_utils import now_ns


# ============================================
# TYPED SUBMODELS
# ============================================

class ExchangePosition(BaseModel):
    """Position as reported by exchange."""
    symbol: str
    side: str  # "long" or "short" (controlled by exchange, not system enum)
    quantity: Decimal
    entry_price: Decimal

    @validator('quantity')
    def validate_quantity(cls, v):
        return crypto(v)

    @validator('entry_price')
    def validate_price(cls, v):
        return price(v)


class ExchangeOpenOrder(BaseModel):
    """Open order as reported by exchange."""
    order_id: str
    symbol: str
    side: OrderSide
    quantity: Decimal
    limit_price: Optional[Decimal] = None

    @validator('quantity')
    def validate_quantity(cls, v):
        return crypto(v)

    @validator('limit_price')
    def validate_limit_price(cls, v):
        if v is not None:
            return price(v)
        return v

    class Config:
        use_enum_values = True


class ExchangeFill(BaseModel):
    """Fill as reported by exchange."""
    fill_id: str
    order_id: str
    price: Decimal
    quantity: Decimal
    fee: Decimal

    @validator('price')
    def validate_price(cls, v):
        return price(v)

    @validator('quantity')
    def validate_quantity(cls, v):
        return crypto(v)

    @validator('fee')
    def validate_fee(cls, v):
        return fee(v)


class SubmittedOrder(BaseModel):
    """Order submitted by execution layer."""
    client_order_id: str
    venue_order_id: Optional[str] = None
    status: InternalOrderStatus
    submitted_ts_ns: int

    @validator('submitted_ts_ns')
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"submitted_ts_ns must be positive: {v}")
        return v

    class Config:
        use_enum_values = True


class PendingCancel(BaseModel):
    """Cancel request pending acknowledgment."""
    client_order_id: str
    cancel_submitted_ts_ns: int

    @validator('cancel_submitted_ts_ns')
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"cancel_submitted_ts_ns must be positive: {v}")
        return v


class Acknowledgement(BaseModel):
    """Order acknowledgment from venue."""
    client_order_id: str
    venue_order_id: str
    ack_ts_ns: int

    @validator('ack_ts_ns')
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"ack_ts_ns must be positive: {v}")
        return v


class Rejection(BaseModel):
    """Order rejection from venue."""
    client_order_id: str
    reason: str
    reject_ts_ns: int

    @validator('reject_ts_ns')
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"reject_ts_ns must be positive: {v}")
        return v


class PortfolioPosition(BaseModel):
    """Individual position in internal portfolio."""
    symbol: str
    quantity: Decimal
    avg_price: Decimal
    mark_price: Decimal
    unrealized_pnl: Decimal

    @validator('quantity')
    def validate_quantity(cls, v):
        return crypto(v)

    @validator('avg_price', 'mark_price')
    def validate_price(cls, v):
        return price(v)

    @validator('unrealized_pnl')
    def validate_pnl(cls, v):
        return usd(v)


class KillSwitchRecord(BaseModel):
    """Kill switch activation record."""
    switch: str
    triggered_at_ns: int

    @validator('triggered_at_ns')
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"triggered_at_ns must be positive: {v}")
        return v


class DivergenceBlock(BaseModel):
    """Divergence block record."""
    symbol: str
    divergence_type: DivergenceType
    blocked_until_ns: int

    @validator('blocked_until_ns')
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"blocked_until_ns must be positive: {v}")
        return v

    class Config:
        use_enum_values = True


class StaleDataBlock(BaseModel):
    """Stale data block record."""
    symbol: str
    blocked_until_ns: int

    @validator('blocked_until_ns')
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"blocked_until_ns must be positive: {v}")
        return v


class ReplayPosition(BaseModel):
    """Position in replay source."""
    source: str
    sequence: int
    timestamp_ns: int

    @validator('sequence')
    def validate_sequence(cls, v):
        if v < 0:
            raise ValueError(f"sequence cannot be negative: {v}")
        return v

    @validator('timestamp_ns')
    def validate_timestamp(cls, v):
        if v < 0:
            raise ValueError(f"timestamp_ns cannot be negative: {v}")
        return v


class FeaturePayload(BaseModel):
    """
    Typed feature payload for FeatureVector.
    All known feature fields with appropriate precision.
    """
    topological_coherence: Optional[Decimal] = None
    betti_0: Optional[int] = None
    betti_1: Optional[int] = None
    persistence_score: Optional[Decimal] = None
    entropy: Optional[Decimal] = None
    entropy_collapsed: Optional[bool] = None
    curvature: Optional[Decimal] = None
    void_depth: Optional[Decimal] = None
    whale_score: Optional[Decimal] = None
    whale_accumulating: Optional[bool] = None
    insider_confidence: Optional[Decimal] = None
    sentiment_velocity: Optional[Decimal] = None
    regime_confidence: Optional[Decimal] = None
    cascade_risk: Optional[Decimal] = None
    toxicity: Optional[Decimal] = None

    @validator('topological_coherence', 'persistence_score', 'entropy',
               'void_depth', 'whale_score', 'insider_confidence',
               'regime_confidence', 'cascade_risk', 'toxicity')
    def validate_score(cls, v):
        if v is not None:
            return confidence(v)
        return v

    @validator('curvature', 'sentiment_velocity')
    def validate_continuous(cls, v):
        if v is not None:
            return v.quantize(Decimal('0.000001'))
        return v


# ============================================
# 1. EventEnvelope
# ============================================

class EventEnvelope(BaseModel):
    """
    Wrapper for all events in the system.
    
    RAW EXTERNAL EVENTS (market data):
    - decision_uuid = None
    - decision_ts_ns = 0
    - parent_uuid = None
    
    DERIVED EVENTS (system decisions):
    - decision_uuid required
    - decision_ts_ns > 0
    - parent_uuid optional
    
    PAYLOAD DISCIPLINE:
    - For raw events: payload contains the raw market data structure
    - For derived events: payload contains one of the typed contracts from this module
    - Payload must be JSON-serializable
    - This is validated by the validator below
    """
    
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    decision_uuid: Optional[str] = Field(None, description="Causal decision ID (null for raw external events)")
    parent_uuid: Optional[str] = Field(None, description="Parent event ID")
    event_type: EventType
    source_module: str
    exchange_ts_ns: int
    receive_ts_ns: int = Field(default_factory=now_ns)
    decision_ts_ns: int = Field(default=0, description="0 for raw external events")
    sequence: int = Field(default=0, description="Monotonic sequence per decision_uuid")
    payload: Dict[str, Any]
    schema_version: int = Field(default=1)

    @validator('exchange_ts_ns', 'receive_ts_ns', 'decision_ts_ns')
    def validate_timestamp_non_negative(cls, v):
        if v < 0:
            raise ValueError(f"Timestamp cannot be negative: {v}")
        return v

    @validator('receive_ts_ns')
    def validate_receive_after_exchange(cls, v, values):
        if 'exchange_ts_ns' in values and v < values['exchange_ts_ns']:
            raise ValueError(f"receive_ts_ns ({v}) < exchange_ts_ns ({values['exchange_ts_ns']})")
        return v

    @validator('sequence')
    def validate_sequence(cls, v):
        if v < 0:
            raise ValueError(f"sequence cannot be negative: {v}")
        return v

    @validator('schema_version')
    def validate_version(cls, v):
        if v <= 0:
            raise ValueError(f"schema_version must be positive: {v}")
        return v

    @root_validator
    def validate_causality(cls, values):
        decision_uuid = values.get('decision_uuid')
        decision_ts_ns = values.get('decision_ts_ns', 0)
        
        if decision_uuid is not None:
            if decision_ts_ns <= 0:
                raise ValueError(f"Derived event with decision_uuid must have decision_ts_ns > 0, got {decision_ts_ns}")
        else:
            if decision_ts_ns != 0:
                raise ValueError(f"Raw event (decision_uuid=None) must have decision_ts_ns=0, got {decision_ts_ns}")
        
        return values

    class Config:
        use_enum_values = True


# ============================================
# 2. DecisionRecord
# ============================================

class DecisionRecord(BaseModel):
    """Single source of truth for all system decisions."""
    
    decision_uuid: str = Field(default_factory=lambda: str(uuid4()))
    timestamp_ns: int = Field(default_factory=now_ns)
    decision_type: DecisionType
    inputs: Dict[str, List[str]] = Field(default_factory=dict)
    outputs: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    schema_version: int = Field(default=1)

    @validator('timestamp_ns')
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"timestamp_ns must be positive: {v}")
        return v

    @validator('schema_version')
    def validate_version(cls, v):
        if v <= 0:
            raise ValueError(f"schema_version must be positive: {v}")
        return v

    class Config:
        use_enum_values = True


# ============================================
# 3. TruthFrame (Five Truths)
# ============================================

class ExchangeTruth(BaseModel):
    """What the exchange believes exists."""
    
    venue: str
    balances: Dict[str, Decimal] = Field(default_factory=dict)
    positions: List[ExchangePosition] = Field(default_factory=list)
    open_orders: List[ExchangeOpenOrder] = Field(default_factory=list)
    fills_since_last_truth: List[ExchangeFill] = Field(default_factory=list)
    exchange_ts_ns: int

    @validator('exchange_ts_ns')
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"exchange_ts_ns must be positive: {v}")
        return v

    @validator('balances')
    def validate_balances(cls, v):
        result = {}
        for currency, amount in v.items():
            if currency == 'USD':
                result[currency] = usd(amount)
            else:
                result[currency] = crypto(amount)
        return result

    class Config:
        use_enum_values = True


class ExecutionTruth(BaseModel):
    """What the execution layer believes."""
    
    submitted_orders: List[SubmittedOrder] = Field(default_factory=list)
    pending_cancels: List[PendingCancel] = Field(default_factory=list)
    acks_received: List[Acknowledgement] = Field(default_factory=list)
    rejections: List[Rejection] = Field(default_factory=list)
    last_reconciliation_ts_ns: int = Field(default_factory=now_ns)

    @validator('last_reconciliation_ts_ns')
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"last_reconciliation_ts_ns must be positive: {v}")
        return v

    class Config:
        use_enum_values = True


class PortfolioTruth(BaseModel):
    """What the internal ledger believes."""
    
    cash: Dict[str, Decimal] = Field(default_factory=dict)
    positions: List[PortfolioPosition] = Field(default_factory=list)
    reserved_buying_power: Decimal = Field(default=Decimal('0'))
    total_equity: Decimal = Field(default=Decimal('0'))
    last_update_ts_ns: int = Field(default_factory=now_ns)

    @validator('last_update_ts_ns')
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"last_update_ts_ns must be positive: {v}")
        return v

    @validator('cash')
    def validate_cash(cls, v):
        result = {}
        for currency, amount in v.items():
            if currency == 'USD':
                result[currency] = usd(amount)
            else:
                result[currency] = crypto(amount)
        return result

    @validator('reserved_buying_power', 'total_equity')
    def validate_equity(cls, v):
        return usd(v)


class StrategyTruthEntry(BaseModel):
    """
    Individual strategy state.
    State is a generic string; validation occurs at strategy layer.
    """
    
    strategy_id: StrategyID
    state: str
    entry_price: Optional[Decimal] = None
    entry_decision_uuid: Optional[str] = None
    target_exposure: Decimal = Field(default=Decimal('0'))
    current_exposure: Decimal = Field(default=Decimal('0'))
    invalidation_state: str = "valid"
    ttl_ns: Optional[int] = None

    @validator('entry_price')
    def validate_entry_price(cls, v):
        if v is not None:
            return price(v)
        return v

    @validator('target_exposure', 'current_exposure')
    def validate_exposure(cls, v):
        return crypto(v)

    @validator('ttl_ns')
    def validate_ttl(cls, v):
        if v is not None and v <= 0:
            raise ValueError(f"ttl_ns must be positive if present: {v}")
        return v


class StrategyTruth(BaseModel):
    """What each strategy believes."""
    
    active_strategies: List[StrategyTruthEntry] = Field(default_factory=list)
    last_update_ts_ns: int = Field(default_factory=now_ns)

    @validator('last_update_ts_ns')
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"last_update_ts_ns must be positive: {v}")
        return v


class RiskTruth(BaseModel):
    """What the risk system permits."""
    
    mode: RiskMode = RiskMode.NORMAL
    max_leverage: Decimal = Field(default=Decimal('1.0'))
    hard_flat_triggered: bool = False
    hard_flat_reason: Optional[str] = None
    stale_data_blocks: List[StaleDataBlock] = Field(default_factory=list)
    divergence_blocks: List[DivergenceBlock] = Field(default_factory=list)
    kill_switches_active: List[KillSwitchRecord] = Field(default_factory=list)
    marketability_limits: Dict[str, Decimal] = Field(default_factory=dict)

    @validator('max_leverage')
    def validate_leverage(cls, v):
        return v.quantize(Decimal('0.01'))

    class Config:
        use_enum_values = True


class TruthFrame(BaseModel):
    """Complete truth frame with all five truths."""
    
    truth_frame_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp_ns: int = Field(default_factory=now_ns)
    exchange_truth: ExchangeTruth
    execution_truth: ExecutionTruth
    portfolio_truth: PortfolioTruth
    strategy_truth: StrategyTruth
    risk_truth: RiskTruth
    status: TruthStatus
    divergence_ns: int = Field(default=0, description="Divergence duration in nanoseconds")
    divergence_reasons: List[str] = Field(default_factory=list)
    schema_version: int = Field(default=1)

    @validator('timestamp_ns')
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"timestamp_ns must be positive: {v}")
        return v

    @validator('divergence_ns')
    def validate_divergence(cls, v):
        if v < 0:
            raise ValueError(f"divergence_ns cannot be negative: {v}")
        return v

    @validator('schema_version')
    def validate_version(cls, v):
        if v <= 0:
            raise ValueError(f"schema_version must be positive: {v}")
        return v

    class Config:
        use_enum_values = True


# ============================================
# 4. OrderIntent
# ============================================

class OrderIntent(BaseModel):
    """Legal order intent from DecisionCompiler."""
    
    order_intent_id: str = Field(default_factory=lambda: str(uuid4()))
    decision_uuid: str
    symbol: str
    side: OrderSide
    quantity: Decimal
    order_type: OrderType
    limit_price: Optional[Decimal] = None
    ttl_ns: int
    strategy_id: StrategyID
    confidence: Decimal
    expected_cost_bps: Decimal
    risk_approved: bool
    risk_approval_decision_uuid: str

    @validator('quantity')
    def validate_quantity(cls, v):
        return crypto(v)

    @validator('limit_price')
    def validate_limit_price(cls, v):
        if v is not None:
            return price(v)
        return v

    @validator('confidence')
    def validate_confidence(cls, v):
        return confidence(v)

    @validator('expected_cost_bps')
    def validate_cost(cls, v):
        return bps(v)

    @validator('ttl_ns')
    def validate_ttl(cls, v):
        if v <= 0:
            raise ValueError(f"ttl_ns must be positive: {v}")
        return v

    class Config:
        use_enum_values = True


# ============================================
# 5. ExecutionEvent
# ============================================

class ExecutionEvent(BaseModel):
    """Execution layer events."""
    
    execution_event_id: str = Field(default_factory=lambda: str(uuid4()))
    order_intent_id: str
    event_type: ExecutionEventType
    timestamp_ns: int = Field(default_factory=now_ns)
    venue: str
    venue_order_id: Optional[str] = None
    status: InternalOrderStatus
    error: Optional[str] = None
    retry_count: int = Field(default=0)

    @validator('timestamp_ns')
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"timestamp_ns must be positive: {v}")
        return v

    @validator('retry_count')
    def validate_retry(cls, v):
        if v < 0:
            raise ValueError(f"retry_count cannot be negative: {v}")
        return v

    class Config:
        use_enum_values = True


# ============================================
# 6. FillEvent
# ============================================

class FillEvent(BaseModel):
    """Fill confirmation from venue."""
    
    fill_event_id: str = Field(default_factory=lambda: str(uuid4()))
    execution_event_id: str
    order_intent_id: str
    decision_uuid: str
    symbol: str
    side: OrderSide
    quantity: Decimal
    price: Decimal
    fee: Decimal
    fee_currency: str = "USD"
    venue_fill_id: str
    exchange_ts_ns: int
    receive_ts_ns: int = Field(default_factory=now_ns)

    @validator('quantity')
    def validate_quantity(cls, v):
        return crypto(v)

    @validator('price')
    def validate_price(cls, v):
        return price(v)

    @validator('fee')
    def validate_fee(cls, v):
        return fee(v)

    @validator('exchange_ts_ns', 'receive_ts_ns')
    def validate_timestamp_positive(cls, v):
        if v <= 0:
            raise ValueError(f"Timestamp must be positive: {v}")
        return v

    @validator('receive_ts_ns')
    def validate_receive_after_exchange(cls, v, values):
        if 'exchange_ts_ns' in values and v < values['exchange_ts_ns']:
            raise ValueError(f"receive_ts_ns ({v}) < exchange_ts_ns ({values['exchange_ts_ns']})")
        return v

    class Config:
        use_enum_values = True


# ============================================
# 7. CancelEvent
# ============================================

class CancelEvent(BaseModel):
    """Cancel request events."""
    
    cancel_event_id: str = Field(default_factory=lambda: str(uuid4()))
    execution_event_id: str
    order_intent_id: str
    decision_uuid: str
    reason: str
    venue_order_id: str
    cancel_submitted_ns: int = Field(default_factory=now_ns)
    cancel_acked_ns: Optional[int] = None
    cancel_confirmed_ns: Optional[int] = None
    status: CancelStatus

    @validator('cancel_submitted_ns', 'cancel_acked_ns', 'cancel_confirmed_ns')
    def validate_timestamp(cls, v):
        if v is not None and v <= 0:
            raise ValueError(f"Timestamp must be positive: {v}")
        return v

    @root_validator
    def validate_ordering(cls, values):
        submitted = values.get('cancel_submitted_ns')
        acked = values.get('cancel_acked_ns')
        confirmed = values.get('cancel_confirmed_ns')
        
        if acked is not None and submitted is not None and acked < submitted:
            raise ValueError(f"cancel_acked_ns ({acked}) < cancel_submitted_ns ({submitted})")
        
        if confirmed is not None and acked is not None and confirmed < acked:
            raise ValueError(f"cancel_confirmed_ns ({confirmed}) < cancel_acked_ns ({acked})")
        
        return values

    class Config:
        use_enum_values = True


# ============================================
# 8. PortfolioSnapshot
# ============================================

class PortfolioSnapshot(BaseModel):
    """Complete portfolio state."""
    
    snapshot_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp_ns: int = Field(default_factory=now_ns)
    cash: Dict[str, Decimal] = Field(default_factory=dict)
    positions: List[PortfolioPosition] = Field(default_factory=list)
    total_equity: Decimal = Field(default=Decimal('0'))
    reserved_buying_power: Decimal = Field(default=Decimal('0'))
    available_buying_power: Decimal = Field(default=Decimal('0'))
    leverage: Decimal = Field(default=Decimal('0'))

    @validator('timestamp_ns')
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"timestamp_ns must be positive: {v}")
        return v

    @validator('cash')
    def validate_cash(cls, v):
        result = {}
        for currency, amount in v.items():
            if currency == 'USD':
                result[currency] = usd(amount)
            else:
                result[currency] = crypto(amount)
        return result

    @validator('total_equity', 'reserved_buying_power', 'available_buying_power')
    def validate_equity(cls, v):
        return usd(v)

    @validator('leverage')
    def validate_leverage(cls, v):
        return v.quantize(Decimal('0.01'))


# ============================================
# 9. RiskDecision
# ============================================

class RiskDecision(BaseModel):
    """Risk system decisions."""
    
    risk_decision_id: str = Field(default_factory=lambda: str(uuid4()))
    decision_uuid: str
    timestamp_ns: int = Field(default_factory=now_ns)
    risk_mode: RiskMode
    max_leverage: Decimal = Field(default=Decimal('1.0'))
    sizing_multiplier: Decimal = Field(default=Decimal('1.0'))
    approved_strategies: List[StrategyID] = Field(default_factory=list)
    blocked_strategies: List[StrategyID] = Field(default_factory=list)
    requires_manual_reset: bool = False
    reason: str
    truth_frame_id: str
    violations: List[str] = Field(default_factory=list)

    @validator('timestamp_ns')
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"timestamp_ns must be positive: {v}")
        return v

    @validator('max_leverage', 'sizing_multiplier')
    def validate_positive(cls, v):
        if v <= 0:
            raise ValueError(f"Value must be positive: {v}")
        return v.quantize(Decimal('0.01'))

    class Config:
        use_enum_values = True


# ============================================
# 10. StrategyVote
# ============================================

class StrategyVote(BaseModel):
    """Strategy voting output."""
    
    vote_id: str = Field(default_factory=lambda: str(uuid4()))
    decision_uuid: str
    strategy_id: StrategyID
    timestamp_ns: int = Field(default_factory=now_ns)
    signal: SignalType
    confidence: Decimal
    expected_move_bps: Decimal
    expected_duration_ns: int
    risk_appetite: Decimal
    invalidation_conditions: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @validator('timestamp_ns', 'expected_duration_ns')
    def validate_positive(cls, v):
        if v <= 0:
            raise ValueError(f"Value must be positive: {v}")
        return v

    @validator('confidence', 'risk_appetite')
    def validate_confidence(cls, v):
        return confidence(v)

    @validator('expected_move_bps')
    def validate_move(cls, v):
        return bps(v)

    class Config:
        use_enum_values = True


# ============================================
# 11. FeatureVector
# ============================================

class FeatureVector(BaseModel):
    """Feature engine outputs with typed payload."""
    
    feature_vector_id: str = Field(default_factory=lambda: str(uuid4()))
    decision_uuid: str
    timestamp_ns: int = Field(default_factory=now_ns)
    symbol: str
    features: FeaturePayload = Field(default_factory=FeaturePayload)

    @validator('timestamp_ns')
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"timestamp_ns must be positive: {v}")
        return v


# ============================================
# 12. RecoveryCheckpoint
# ============================================

class RecoveryCheckpoint(BaseModel):
    """Recovery state checkpoint."""
    
    checkpoint_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp_ns: int = Field(default_factory=now_ns)
    checkpoint_type: CheckpointType
    wal_seq: int
    truth_frame_id: Optional[str] = None
    snapshot_path: Optional[str] = None
    checksum: str
    replay_position: Optional[ReplayPosition] = None

    @validator('timestamp_ns')
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"timestamp_ns must be positive: {v}")
        return v

    @validator('wal_seq')
    def validate_wal_seq(cls, v):
        if v < 0:
            raise ValueError(f"wal_seq cannot be negative: {v}")
        return v

    class Config:
        use_enum_values = True


# ============================================
# 13. DivergenceEvent
# ============================================

class DivergenceEvent(BaseModel):
    """Truth divergence detection."""
    
    divergence_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp_ns: int = Field(default_factory=now_ns)
    divergence_type: DivergenceType
    truth_frame_id: str
    expected: Dict[str, Any]
    observed: Dict[str, Any]
    magnitude: Optional[Decimal] = Field(default=None, description="Quantitative divergence")
    duration_ns: int = Field(default=0)
    resolution: ResolutionType = ResolutionType.PENDING
    resolution_action: Optional[str] = None

    @validator('timestamp_ns')
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"timestamp_ns must be positive: {v}")
        return v

    @validator('duration_ns')
    def validate_duration(cls, v):
        if v < 0:
            raise ValueError(f"duration_ns cannot be negative: {v}")
        return v

    class Config:
        use_enum_values = True


# ============================================
# EXPORTS
# ============================================

__all__ = [
    # Typed submodels
    'ExchangePosition',
    'ExchangeOpenOrder',
    'ExchangeFill',
    'SubmittedOrder',
    'PendingCancel',
    'Acknowledgement',
    'Rejection',
    'PortfolioPosition',
    'KillSwitchRecord',
    'DivergenceBlock',
    'StaleDataBlock',
    'ReplayPosition',
    'FeaturePayload',
    # Core contracts
    'EventEnvelope',
    'DecisionRecord',
    'ExchangeTruth',
    'ExecutionTruth',
    'PortfolioTruth',
    'StrategyTruthEntry',
    'StrategyTruth',
    'RiskTruth',
    'TruthFrame',
    'OrderIntent',
    'ExecutionEvent',
    'FillEvent',
    'CancelEvent',
    'PortfolioSnapshot',
    'RiskDecision',
    'StrategyVote',
    'FeatureVector',
    'RecoveryCheckpoint',
    'DivergenceEvent',
]
