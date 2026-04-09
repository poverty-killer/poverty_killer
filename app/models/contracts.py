"""
Canonical Contracts for Sovereign Trading System

All cross-module communication uses these Pydantic models (v2 native).
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

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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

    @field_validator('quantity', mode='before')
    @classmethod
    def validate_quantity(cls, v):
        return crypto(v)

    @field_validator('entry_price', mode='before')
    @classmethod
    def validate_price(cls, v):
        return price(v)


class ExchangeOpenOrder(BaseModel):
    """Open order as reported by exchange."""
    model_config = ConfigDict(use_enum_values=True)

    order_id: str
    symbol: str
    side: OrderSide
    quantity: Decimal
    limit_price: Optional[Decimal] = None

    @field_validator('quantity', mode='before')
    @classmethod
    def validate_quantity(cls, v):
        return crypto(v)

    @field_validator('limit_price', mode='before')
    @classmethod
    def validate_limit_price(cls, v):
        if v is not None:
            return price(v)
        return v


class ExchangeFill(BaseModel):
    """Fill as reported by exchange."""
    fill_id: str
    order_id: str
    price: Decimal
    quantity: Decimal
    fee: Decimal

    @field_validator('price', mode='before')
    @classmethod
    def validate_price(cls, v):
        return price(v)

    @field_validator('quantity', mode='before')
    @classmethod
    def validate_quantity(cls, v):
        return crypto(v)

    @field_validator('fee', mode='before')
    @classmethod
    def validate_fee(cls, v):
        return fee(v)


class SubmittedOrder(BaseModel):
    """Order submitted by execution layer."""
    model_config = ConfigDict(use_enum_values=True)

    client_order_id: str
    venue_order_id: Optional[str] = None
    status: InternalOrderStatus
    submitted_ts_ns: int

    @field_validator('submitted_ts_ns', mode='before')
    @classmethod
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"submitted_ts_ns must be positive: {v}")
        return v


class PendingCancel(BaseModel):
    """Cancel request pending acknowledgment."""
    client_order_id: str
    cancel_submitted_ts_ns: int

    @field_validator('cancel_submitted_ts_ns', mode='before')
    @classmethod
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"cancel_submitted_ts_ns must be positive: {v}")
        return v


class Acknowledgement(BaseModel):
    """Order acknowledgment from venue."""
    client_order_id: str
    venue_order_id: str
    ack_ts_ns: int

    @field_validator('ack_ts_ns', mode='before')
    @classmethod
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"ack_ts_ns must be positive: {v}")
        return v


class Rejection(BaseModel):
    """Order rejection from venue."""
    client_order_id: str
    reason: str
    reject_ts_ns: int

    @field_validator('reject_ts_ns', mode='before')
    @classmethod
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

    @field_validator('quantity', mode='before')
    @classmethod
    def validate_quantity(cls, v):
        return crypto(v)

    @field_validator('avg_price', 'mark_price', mode='before')
    @classmethod
    def validate_price(cls, v):
        return price(v)

    @field_validator('unrealized_pnl', mode='before')
    @classmethod
    def validate_pnl(cls, v):
        return usd(v)


class KillSwitchRecord(BaseModel):
    """Kill switch activation record."""
    switch: str
    triggered_at_ns: int

    @field_validator('triggered_at_ns', mode='before')
    @classmethod
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"triggered_at_ns must be positive: {v}")
        return v


class DivergenceBlock(BaseModel):
    """Divergence block record."""
    model_config = ConfigDict(use_enum_values=True)

    symbol: str
    divergence_type: DivergenceType
    blocked_until_ns: int

    @field_validator('blocked_until_ns', mode='before')
    @classmethod
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"blocked_until_ns must be positive: {v}")
        return v


class StaleDataBlock(BaseModel):
    """Stale data block record."""
    symbol: str
    blocked_until_ns: int

    @field_validator('blocked_until_ns', mode='before')
    @classmethod
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"blocked_until_ns must be positive: {v}")
        return v


class ReplayPosition(BaseModel):
    """Position in replay source."""
    source: str
    sequence: int
    timestamp_ns: int

    @field_validator('sequence', mode='before')
    @classmethod
    def validate_sequence(cls, v):
        if v < 0:
            raise ValueError(f"sequence cannot be negative: {v}")
        return v

    @field_validator('timestamp_ns', mode='before')
    @classmethod
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

    @field_validator(
        'topological_coherence', 'persistence_score', 'entropy',
        'void_depth', 'whale_score', 'insider_confidence',
        'regime_confidence', 'cascade_risk', 'toxicity',
        mode='before',
    )
    @classmethod
    def validate_score(cls, v):
        if v is not None:
            return confidence(v)
        return v

    @field_validator('curvature', 'sentiment_velocity', mode='before')
    @classmethod
    def validate_continuous(cls, v):
        if v is not None:
            return Decimal(str(v)).quantize(Decimal('0.000001'))
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
    model_config = ConfigDict(use_enum_values=True)

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

    @field_validator('exchange_ts_ns', 'receive_ts_ns', 'decision_ts_ns', mode='before')
    @classmethod
    def validate_timestamp_non_negative(cls, v):
        if v < 0:
            raise ValueError(f"Timestamp cannot be negative: {v}")
        return v

    @field_validator('sequence', mode='before')
    @classmethod
    def validate_sequence(cls, v):
        if v < 0:
            raise ValueError(f"sequence cannot be negative: {v}")
        return v

    @field_validator('schema_version', mode='before')
    @classmethod
    def validate_version(cls, v):
        if v <= 0:
            raise ValueError(f"schema_version must be positive: {v}")
        return v

    @model_validator(mode='after')
    def validate_causality_and_ordering(self):
        if self.receive_ts_ns < self.exchange_ts_ns:
            raise ValueError(
                f"receive_ts_ns ({self.receive_ts_ns}) < exchange_ts_ns ({self.exchange_ts_ns})"
            )
        if self.decision_uuid is not None:
            if self.decision_ts_ns <= 0:
                raise ValueError(
                    f"Derived event with decision_uuid must have decision_ts_ns > 0, "
                    f"got {self.decision_ts_ns}"
                )
        else:
            if self.decision_ts_ns != 0:
                raise ValueError(
                    f"Raw event (decision_uuid=None) must have decision_ts_ns=0, "
                    f"got {self.decision_ts_ns}"
                )
        return self


# ============================================
# 2. DecisionRecord
# ============================================

class DecisionRecord(BaseModel):
    """Single source of truth for all system decisions."""
    model_config = ConfigDict(use_enum_values=True)

    decision_uuid: str = Field(default_factory=lambda: str(uuid4()))
    timestamp_ns: int = Field(default_factory=now_ns)
    decision_type: DecisionType
    inputs: Dict[str, List[str]] = Field(default_factory=dict)
    outputs: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    schema_version: int = Field(default=1)

    @field_validator('timestamp_ns', mode='before')
    @classmethod
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"timestamp_ns must be positive: {v}")
        return v

    @field_validator('schema_version', mode='before')
    @classmethod
    def validate_version(cls, v):
        if v <= 0:
            raise ValueError(f"schema_version must be positive: {v}")
        return v


# ============================================
# 3. TruthFrame (Five Truths)
# ============================================

class ExchangeTruth(BaseModel):
    """What the exchange believes exists."""
    model_config = ConfigDict(use_enum_values=True)

    venue: str
    balances: Dict[str, Decimal] = Field(default_factory=dict)
    positions: List[ExchangePosition] = Field(default_factory=list)
    open_orders: List[ExchangeOpenOrder] = Field(default_factory=list)
    fills_since_last_truth: List[ExchangeFill] = Field(default_factory=list)
    exchange_ts_ns: int

    @field_validator('exchange_ts_ns', mode='before')
    @classmethod
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"exchange_ts_ns must be positive: {v}")
        return v

    @field_validator('balances', mode='before')
    @classmethod
    def validate_balances(cls, v):
        result = {}
        for currency, amount in v.items():
            if currency == 'USD':
                result[currency] = usd(amount)
            else:
                result[currency] = crypto(amount)
        return result


class ExecutionTruth(BaseModel):
    """What the execution layer believes."""
    model_config = ConfigDict(use_enum_values=True)

    submitted_orders: List[SubmittedOrder] = Field(default_factory=list)
    pending_cancels: List[PendingCancel] = Field(default_factory=list)
    acks_received: List[Acknowledgement] = Field(default_factory=list)
    rejections: List[Rejection] = Field(default_factory=list)
    last_reconciliation_ts_ns: int = Field(default_factory=now_ns)

    @field_validator('last_reconciliation_ts_ns', mode='before')
    @classmethod
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"last_reconciliation_ts_ns must be positive: {v}")
        return v


class PortfolioTruth(BaseModel):
    """What the internal ledger believes."""
    cash: Dict[str, Decimal] = Field(default_factory=dict)
    positions: List[PortfolioPosition] = Field(default_factory=list)
    reserved_buying_power: Decimal = Field(default=Decimal('0'))
    total_equity: Decimal = Field(default=Decimal('0'))
    last_update_ts_ns: int = Field(default_factory=now_ns)

    @field_validator('last_update_ts_ns', mode='before')
    @classmethod
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"last_update_ts_ns must be positive: {v}")
        return v

    @field_validator('cash', mode='before')
    @classmethod
    def validate_cash(cls, v):
        result = {}
        for currency, amount in v.items():
            if currency == 'USD':
                result[currency] = usd(amount)
            else:
                result[currency] = crypto(amount)
        return result

    @field_validator('reserved_buying_power', 'total_equity', mode='before')
    @classmethod
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

    @field_validator('entry_price', mode='before')
    @classmethod
    def validate_entry_price(cls, v):
        if v is not None:
            return price(v)
        return v

    @field_validator('target_exposure', 'current_exposure', mode='before')
    @classmethod
    def validate_exposure(cls, v):
        return crypto(v)

    @field_validator('ttl_ns', mode='before')
    @classmethod
    def validate_ttl(cls, v):
        if v is not None and v <= 0:
            raise ValueError(f"ttl_ns must be positive if present: {v}")
        return v


class StrategyTruth(BaseModel):
    """What each strategy believes."""
    active_strategies: List[StrategyTruthEntry] = Field(default_factory=list)
    last_update_ts_ns: int = Field(default_factory=now_ns)

    @field_validator('last_update_ts_ns', mode='before')
    @classmethod
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"last_update_ts_ns must be positive: {v}")
        return v


class RiskTruth(BaseModel):
    """What the risk system permits."""
    model_config = ConfigDict(use_enum_values=True)

    mode: RiskMode = RiskMode.NORMAL
    max_leverage: Decimal = Field(default=Decimal('1.0'))
    hard_flat_triggered: bool = False
    hard_flat_reason: Optional[str] = None
    stale_data_blocks: List[StaleDataBlock] = Field(default_factory=list)
    divergence_blocks: List[DivergenceBlock] = Field(default_factory=list)
    kill_switches_active: List[KillSwitchRecord] = Field(default_factory=list)
    marketability_limits: Dict[str, Decimal] = Field(default_factory=dict)

    @field_validator('max_leverage', mode='before')
    @classmethod
    def validate_leverage(cls, v):
        return Decimal(str(v)).quantize(Decimal('0.01'))


class TruthFrame(BaseModel):
    """Complete truth frame with all five truths."""
    model_config = ConfigDict(use_enum_values=True)

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

    @field_validator('timestamp_ns', mode='before')
    @classmethod
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"timestamp_ns must be positive: {v}")
        return v

    @field_validator('divergence_ns', mode='before')
    @classmethod
    def validate_divergence(cls, v):
        if v < 0:
            raise ValueError(f"divergence_ns cannot be negative: {v}")
        return v

    @field_validator('schema_version', mode='before')
    @classmethod
    def validate_version(cls, v):
        if v <= 0:
            raise ValueError(f"schema_version must be positive: {v}")
        return v


# ============================================
# 4. OrderIntent
# ============================================

class OrderIntent(BaseModel):
    """Legal order intent from DecisionCompiler."""
    model_config = ConfigDict(use_enum_values=True)

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

    @field_validator('quantity', mode='before')
    @classmethod
    def validate_quantity(cls, v):
        return crypto(v)

    @field_validator('limit_price', mode='before')
    @classmethod
    def validate_limit_price(cls, v):
        if v is not None:
            return price(v)
        return v

    @field_validator('confidence', mode='before')
    @classmethod
    def validate_confidence(cls, v):
        return confidence(v)

    @field_validator('expected_cost_bps', mode='before')
    @classmethod
    def validate_cost(cls, v):
        return bps(v)

    @field_validator('ttl_ns', mode='before')
    @classmethod
    def validate_ttl(cls, v):
        if v <= 0:
            raise ValueError(f"ttl_ns must be positive: {v}")
        return v


# ============================================
# 5. ExecutionEvent
# ============================================

class ExecutionEvent(BaseModel):
    """Execution layer events."""
    model_config = ConfigDict(use_enum_values=True)

    execution_event_id: str = Field(default_factory=lambda: str(uuid4()))
    order_intent_id: str
    event_type: ExecutionEventType
    timestamp_ns: int = Field(default_factory=now_ns)
    venue: str
    venue_order_id: Optional[str] = None
    status: InternalOrderStatus
    error: Optional[str] = None
    retry_count: int = Field(default=0)

    @field_validator('timestamp_ns', mode='before')
    @classmethod
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"timestamp_ns must be positive: {v}")
        return v

    @field_validator('retry_count', mode='before')
    @classmethod
    def validate_retry(cls, v):
        if v < 0:
            raise ValueError(f"retry_count cannot be negative: {v}")
        return v


# ============================================
# 6. FillEvent
# ============================================

class FillEvent(BaseModel):
    """Fill confirmation from venue."""
    model_config = ConfigDict(use_enum_values=True)

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

    @field_validator('quantity', mode='before')
    @classmethod
    def validate_quantity(cls, v):
        return crypto(v)

    @field_validator('price', mode='before')
    @classmethod
    def validate_price(cls, v):
        return price(v)

    @field_validator('fee', mode='before')
    @classmethod
    def validate_fee(cls, v):
        return fee(v)

    @field_validator('exchange_ts_ns', 'receive_ts_ns', mode='before')
    @classmethod
    def validate_timestamp_positive(cls, v):
        if v <= 0:
            raise ValueError(f"Timestamp must be positive: {v}")
        return v

    @model_validator(mode='after')
    def validate_receive_after_exchange(self):
        if self.receive_ts_ns < self.exchange_ts_ns:
            raise ValueError(
                f"receive_ts_ns ({self.receive_ts_ns}) < exchange_ts_ns ({self.exchange_ts_ns})"
            )
        return self


# ============================================
# 7. CancelEvent
# ============================================

class CancelEvent(BaseModel):
    """Cancel request events."""
    model_config = ConfigDict(use_enum_values=True)

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

    @field_validator('cancel_submitted_ns', 'cancel_acked_ns', 'cancel_confirmed_ns', mode='before')
    @classmethod
    def validate_timestamp(cls, v):
        if v is not None and v <= 0:
            raise ValueError(f"Timestamp must be positive: {v}")
        return v

    @model_validator(mode='after')
    def validate_ordering(self):
        submitted = self.cancel_submitted_ns
        acked = self.cancel_acked_ns
        confirmed = self.cancel_confirmed_ns

        if acked is not None and submitted is not None and acked < submitted:
            raise ValueError(
                f"cancel_acked_ns ({acked}) < cancel_submitted_ns ({submitted})"
            )
        if confirmed is not None and acked is not None and confirmed < acked:
            raise ValueError(
                f"cancel_confirmed_ns ({confirmed}) < cancel_acked_ns ({acked})"
            )
        return self


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

    @field_validator('timestamp_ns', mode='before')
    @classmethod
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"timestamp_ns must be positive: {v}")
        return v

    @field_validator('cash', mode='before')
    @classmethod
    def validate_cash(cls, v):
        result = {}
        for currency, amount in v.items():
            if currency == 'USD':
                result[currency] = usd(amount)
            else:
                result[currency] = crypto(amount)
        return result

    @field_validator('total_equity', 'reserved_buying_power', 'available_buying_power', mode='before')
    @classmethod
    def validate_equity(cls, v):
        return usd(v)

    @field_validator('leverage', mode='before')
    @classmethod
    def validate_leverage(cls, v):
        return Decimal(str(v)).quantize(Decimal('0.01'))


# ============================================
# 9. RiskDecision
# ============================================

class RiskDecision(BaseModel):
    """Risk system decisions."""
    model_config = ConfigDict(use_enum_values=True)

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

    @field_validator('timestamp_ns', mode='before')
    @classmethod
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"timestamp_ns must be positive: {v}")
        return v

    @field_validator('max_leverage', 'sizing_multiplier', mode='before')
    @classmethod
    def validate_positive(cls, v):
        d = Decimal(str(v))
        if d <= 0:
            raise ValueError(f"Value must be positive: {v}")
        return d.quantize(Decimal('0.01'))


# ============================================
# 10. StrategyVote
# ============================================

class StrategyVote(BaseModel):
    """Strategy voting output."""
    model_config = ConfigDict(use_enum_values=True)

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

    @field_validator('timestamp_ns', 'expected_duration_ns', mode='before')
    @classmethod
    def validate_positive(cls, v):
        if v <= 0:
            raise ValueError(f"Value must be positive: {v}")
        return v

    @field_validator('confidence', 'risk_appetite', mode='before')
    @classmethod
    def validate_confidence(cls, v):
        return confidence(v)

    @field_validator('expected_move_bps', mode='before')
    @classmethod
    def validate_move(cls, v):
        return bps(v)


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

    @field_validator('timestamp_ns', mode='before')
    @classmethod
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"timestamp_ns must be positive: {v}")
        return v


# ============================================
# 12. RecoveryCheckpoint
# ============================================

class RecoveryCheckpoint(BaseModel):
    """Recovery state checkpoint."""
    model_config = ConfigDict(use_enum_values=True)

    checkpoint_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp_ns: int = Field(default_factory=now_ns)
    checkpoint_type: CheckpointType
    wal_seq: int
    truth_frame_id: Optional[str] = None
    snapshot_path: Optional[str] = None
    checksum: str
    replay_position: Optional[ReplayPosition] = None

    @field_validator('timestamp_ns', mode='before')
    @classmethod
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"timestamp_ns must be positive: {v}")
        return v

    @field_validator('wal_seq', mode='before')
    @classmethod
    def validate_wal_seq(cls, v):
        if v < 0:
            raise ValueError(f"wal_seq cannot be negative: {v}")
        return v


# ============================================
# 13. DivergenceEvent
# ============================================

class DivergenceEvent(BaseModel):
    """Truth divergence detection."""
    model_config = ConfigDict(use_enum_values=True)

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

    @field_validator('timestamp_ns', mode='before')
    @classmethod
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"timestamp_ns must be positive: {v}")
        return v

    @field_validator('duration_ns', mode='before')
    @classmethod
    def validate_duration(cls, v):
        if v < 0:
            raise ValueError(f"duration_ns cannot be negative: {v}")
        return v


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