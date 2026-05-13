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
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import (
    CancelStatus,
    CheckpointType,
    DecisionType,
    DivergenceType,
    EventType,
    ExecutionEventType,
    InternalOrderStatus,
    OrderSide,
    OrderType,
    ResolutionType,
    RiskMode,
    SignalType,
    StrategyID,
    TruthStatus,
)
from app.utils.decimal_utils import (
    bps,
    confidence,
    crypto,
    fee,
    price,
    to_canonical_string,
    usd,
)
from app.utils.time_utils import now_ns


def _base_model_config(*, use_enum_values: bool = False) -> ConfigDict:
    return ConfigDict(
        extra="forbid",
        use_enum_values=use_enum_values,
        json_encoders={Decimal: to_canonical_string},
    )


def _require_non_blank(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name} must be non-blank")
    return stripped


def _quantize_ratio(value: Any, field_name: str, allow_zero: bool = True) -> Decimal:
    d = Decimal(str(value)).quantize(Decimal("0.01"))
    if allow_zero:
        if d < 0:
            raise ValueError(f"{field_name} cannot be negative: {value}")
    else:
        if d <= 0:
            raise ValueError(f"{field_name} must be positive: {value}")
    return d


# ============================================
# TYPED SUBMODELS
# ============================================


class ExchangePosition(BaseModel):
    """Position as reported by exchange."""

    model_config = _base_model_config()

    symbol: str
    side: str  # "long" or "short" (controlled by exchange, not system enum)
    quantity: Decimal
    entry_price: Decimal

    @field_validator("symbol", "side", mode="before")
    @classmethod
    def validate_required_strings(cls, v, info):
        return _require_non_blank(v, info.field_name)

    @field_validator("quantity", mode="before")
    @classmethod
    def validate_quantity(cls, v):
        q = crypto(v)
        if q < 0:
            raise ValueError(f"quantity cannot be negative: {v}")
        return q

    @field_validator("entry_price", mode="before")
    @classmethod
    def validate_price(cls, v):
        p = price(v)
        if p <= 0:
            raise ValueError(f"entry_price must be positive: {v}")
        return p


class ExchangeOpenOrder(BaseModel):
    """Open order as reported by exchange."""

    model_config = _base_model_config(use_enum_values=True)

    order_id: str
    symbol: str
    side: OrderSide
    quantity: Decimal
    limit_price: Optional[Decimal] = None
    order_id_namespace: Optional[str] = None
    client_order_id: Optional[str] = None
    venue_order_id: Optional[str] = None
    broker_order_id: Optional[str] = None
    exchange_txid: Optional[str] = None
    command_id_namespace: Optional[str] = None
    command_order_id: Optional[str] = None
    mapping_status: Optional[str] = None
    is_terminal_mapping: bool = False
    terminal_reason: Optional[str] = None

    @field_validator("order_id", "symbol", mode="before")
    @classmethod
    def validate_required_strings(cls, v, info):
        return _require_non_blank(v, info.field_name)

    @field_validator(
        "order_id_namespace",
        "client_order_id",
        "venue_order_id",
        "broker_order_id",
        "exchange_txid",
        "command_id_namespace",
        "command_order_id",
        "mapping_status",
        "terminal_reason",
        mode="before",
    )
    @classmethod
    def validate_optional_strings(cls, v, info):
        if v is None:
            return v
        return _require_non_blank(v, info.field_name)

    @field_validator("quantity", mode="before")
    @classmethod
    def validate_quantity(cls, v):
        q = crypto(v)
        if q <= 0:
            raise ValueError(f"quantity must be positive: {v}")
        return q

    @field_validator("limit_price", mode="before")
    @classmethod
    def validate_limit_price(cls, v):
        if v is not None:
            p = price(v)
            if p <= 0:
                raise ValueError(f"limit_price must be positive: {v}")
            return p
        return v


class ExchangeFill(BaseModel):
    """Fill as reported by exchange."""

    model_config = _base_model_config()

    fill_id: str
    order_id: str
    price: Decimal
    quantity: Decimal
    fee: Decimal

    @field_validator("fill_id", "order_id", mode="before")
    @classmethod
    def validate_required_strings(cls, v, info):
        return _require_non_blank(v, info.field_name)

    @field_validator("price", mode="before")
    @classmethod
    def validate_price(cls, v):
        p = price(v)
        if p <= 0:
            raise ValueError(f"price must be positive: {v}")
        return p

    @field_validator("quantity", mode="before")
    @classmethod
    def validate_quantity(cls, v):
        q = crypto(v)
        if q <= 0:
            raise ValueError(f"quantity must be positive: {v}")
        return q

    @field_validator("fee", mode="before")
    @classmethod
    def validate_fee(cls, v):
        f = fee(v)
        if f < 0:
            raise ValueError(f"fee cannot be negative: {v}")
        return f


class SubmittedOrder(BaseModel):
    """Order submitted by execution layer."""

    model_config = _base_model_config(use_enum_values=True)

    client_order_id: str
    venue_order_id: Optional[str] = None
    status: InternalOrderStatus
    submitted_ts_ns: int

    @field_validator("client_order_id", mode="before")
    @classmethod
    def validate_client_order_id(cls, v):
        return _require_non_blank(v, "client_order_id")

    @field_validator("venue_order_id", mode="before")
    @classmethod
    def validate_venue_order_id(cls, v):
        if v is None:
            return v
        return _require_non_blank(v, "venue_order_id")

    @field_validator("submitted_ts_ns", mode="before")
    @classmethod
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"submitted_ts_ns must be positive: {v}")
        return v


class PendingCancel(BaseModel):
    """Cancel request pending acknowledgment."""

    model_config = _base_model_config()

    client_order_id: str
    cancel_submitted_ts_ns: int

    @field_validator("client_order_id", mode="before")
    @classmethod
    def validate_client_order_id(cls, v):
        return _require_non_blank(v, "client_order_id")

    @field_validator("cancel_submitted_ts_ns", mode="before")
    @classmethod
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"cancel_submitted_ts_ns must be positive: {v}")
        return v


class Acknowledgement(BaseModel):
    """Order acknowledgment from venue."""

    model_config = _base_model_config()

    client_order_id: str
    venue_order_id: str
    ack_ts_ns: int

    @field_validator("client_order_id", "venue_order_id", mode="before")
    @classmethod
    def validate_required_strings(cls, v, info):
        return _require_non_blank(v, info.field_name)

    @field_validator("ack_ts_ns", mode="before")
    @classmethod
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"ack_ts_ns must be positive: {v}")
        return v


class Rejection(BaseModel):
    """Order rejection from venue."""

    model_config = _base_model_config()

    client_order_id: str
    reason: str
    reject_ts_ns: int

    @field_validator("client_order_id", "reason", mode="before")
    @classmethod
    def validate_required_strings(cls, v, info):
        return _require_non_blank(v, info.field_name)

    @field_validator("reject_ts_ns", mode="before")
    @classmethod
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"reject_ts_ns must be positive: {v}")
        return v


class PortfolioPosition(BaseModel):
    """Individual position in internal portfolio."""

    model_config = _base_model_config()

    symbol: str
    quantity: Decimal
    avg_price: Decimal
    mark_price: Decimal
    unrealized_pnl: Decimal

    @field_validator("symbol", mode="before")
    @classmethod
    def validate_symbol(cls, v):
        return _require_non_blank(v, "symbol")

    @field_validator("quantity", mode="before")
    @classmethod
    def validate_quantity(cls, v):
        return crypto(v)

    @field_validator("avg_price", "mark_price", mode="before")
    @classmethod
    def validate_price(cls, v):
        p = price(v)
        if p < 0:
            raise ValueError(f"price cannot be negative: {v}")
        return p

    @field_validator("unrealized_pnl", mode="before")
    @classmethod
    def validate_pnl(cls, v):
        return usd(v)


class KillSwitchRecord(BaseModel):
    """Kill switch activation record."""

    model_config = _base_model_config()

    switch: str
    triggered_at_ns: int

    @field_validator("switch", mode="before")
    @classmethod
    def validate_switch(cls, v):
        return _require_non_blank(v, "switch")

    @field_validator("triggered_at_ns", mode="before")
    @classmethod
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"triggered_at_ns must be positive: {v}")
        return v


class DivergenceBlock(BaseModel):
    """Divergence block record."""

    model_config = _base_model_config(use_enum_values=True)

    symbol: str
    divergence_type: DivergenceType
    blocked_until_ns: int

    @field_validator("symbol", mode="before")
    @classmethod
    def validate_symbol(cls, v):
        return _require_non_blank(v, "symbol")

    @field_validator("blocked_until_ns", mode="before")
    @classmethod
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"blocked_until_ns must be positive: {v}")
        return v


class StaleDataBlock(BaseModel):
    """Stale data block record."""

    model_config = _base_model_config()

    symbol: str
    blocked_until_ns: int

    @field_validator("symbol", mode="before")
    @classmethod
    def validate_symbol(cls, v):
        return _require_non_blank(v, "symbol")

    @field_validator("blocked_until_ns", mode="before")
    @classmethod
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"blocked_until_ns must be positive: {v}")
        return v


class ReplayPosition(BaseModel):
    """Position in replay source."""

    model_config = _base_model_config()

    source: str
    sequence: int
    timestamp_ns: int

    @field_validator("source", mode="before")
    @classmethod
    def validate_source(cls, v):
        return _require_non_blank(v, "source")

    @field_validator("sequence", mode="before")
    @classmethod
    def validate_sequence(cls, v):
        if v < 0:
            raise ValueError(f"sequence cannot be negative: {v}")
        return v

    @field_validator("timestamp_ns", mode="before")
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

    model_config = _base_model_config()

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
        "topological_coherence",
        "persistence_score",
        "entropy",
        "void_depth",
        "whale_score",
        "insider_confidence",
        "regime_confidence",
        "cascade_risk",
        "toxicity",
        mode="before",
    )
    @classmethod
    def validate_score(cls, v):
        if v is not None:
            return confidence(v)
        return v

    @field_validator("curvature", "sentiment_velocity", mode="before")
    @classmethod
    def validate_continuous(cls, v):
        if v is not None:
            return Decimal(str(v)).quantize(Decimal("0.000001"))
        return v

    @field_validator("betti_0", "betti_1", mode="before")
    @classmethod
    def validate_betti(cls, v):
        if v is not None and v < 0:
            raise ValueError(f"Betti number cannot be negative: {v}")
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
    """

    model_config = _base_model_config(use_enum_values=True)

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    decision_uuid: Optional[str] = Field(
        None,
        description="Causal decision ID (null for raw external events)",
    )
    parent_uuid: Optional[str] = Field(None, description="Parent event ID")
    event_type: EventType
    source_module: str
    exchange_ts_ns: int
    receive_ts_ns: int = Field(default_factory=now_ns)
    decision_ts_ns: int = Field(default=0, description="0 for raw external events")
    sequence: int = Field(default=0, description="Monotonic sequence per decision_uuid")
    payload: Dict[str, Any]
    schema_version: int = Field(default=1)

    @field_validator("event_id", mode="before")
    @classmethod
    def validate_event_id(cls, v):
        return _require_non_blank(v, "event_id")

    @field_validator("decision_uuid", "parent_uuid", "source_module", mode="before")
    @classmethod
    def validate_optional_strings(cls, v, info):
        if info.field_name == "source_module":
            return _require_non_blank(v, info.field_name)
        if v is None:
            return v
        return _require_non_blank(v, info.field_name)

    @field_validator("exchange_ts_ns", "receive_ts_ns", "decision_ts_ns", mode="before")
    @classmethod
    def validate_timestamp_non_negative(cls, v):
        if v < 0:
            raise ValueError(f"Timestamp cannot be negative: {v}")
        return v

    @field_validator("sequence", mode="before")
    @classmethod
    def validate_sequence(cls, v):
        if v < 0:
            raise ValueError(f"sequence cannot be negative: {v}")
        return v

    @field_validator("schema_version", mode="before")
    @classmethod
    def validate_version(cls, v):
        if v <= 0:
            raise ValueError(f"schema_version must be positive: {v}")
        return v

    @field_validator("payload", mode="before")
    @classmethod
    def validate_payload(cls, v):
        if v is None:
            raise ValueError("payload cannot be None")
        if not isinstance(v, dict):
            raise TypeError(f"payload must be a dict, got {type(v).__name__}")
        return v

    @model_validator(mode="after")
    def validate_causality_and_ordering(self):
        if self.receive_ts_ns < self.exchange_ts_ns:
            raise ValueError(
                f"receive_ts_ns ({self.receive_ts_ns}) < exchange_ts_ns ({self.exchange_ts_ns})"
            )
        if self.decision_uuid is not None:
            if self.decision_ts_ns <= 0:
                raise ValueError(
                    "Derived event with decision_uuid must have decision_ts_ns > 0, "
                    f"got {self.decision_ts_ns}"
                )
        else:
            if self.decision_ts_ns != 0:
                raise ValueError(
                    "Raw event (decision_uuid=None) must have decision_ts_ns=0, "
                    f"got {self.decision_ts_ns}"
                )
            if self.parent_uuid is not None:
                raise ValueError("Raw event (decision_uuid=None) must have parent_uuid=None")
        return self


# ============================================
# 2. DecisionRecord
# ============================================


class DecisionRecord(BaseModel):
    """Single source of truth for all system decisions."""

    model_config = _base_model_config(use_enum_values=True)

    decision_uuid: str = Field(default_factory=lambda: str(uuid4()))
    timestamp_ns: int = Field(default_factory=now_ns)
    decision_type: DecisionType
    inputs: Dict[str, List[str]] = Field(default_factory=dict)
    outputs: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    schema_version: int = Field(default=1)

    @field_validator("decision_uuid", mode="before")
    @classmethod
    def validate_decision_uuid(cls, v):
        return _require_non_blank(v, "decision_uuid")

    @field_validator("timestamp_ns", mode="before")
    @classmethod
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"timestamp_ns must be positive: {v}")
        return v

    @field_validator("schema_version", mode="before")
    @classmethod
    def validate_version(cls, v):
        if v <= 0:
            raise ValueError(f"schema_version must be positive: {v}")
        return v

    @field_validator("inputs", "outputs", "metadata", mode="before")
    @classmethod
    def validate_mapping_not_none(cls, v):
        if v is None:
            raise ValueError("mapping field cannot be None")
        return v


# ============================================
# 3. TruthFrame (Five Truths)
# ============================================


class ExchangeTruth(BaseModel):
    """What the exchange believes exists."""

    model_config = _base_model_config(use_enum_values=True)

    venue: str
    balances: Dict[str, Decimal] = Field(default_factory=dict)
    positions: List[ExchangePosition] = Field(default_factory=list)
    open_orders: List[ExchangeOpenOrder] = Field(default_factory=list)
    fills_since_last_truth: List[ExchangeFill] = Field(default_factory=list)
    exchange_ts_ns: int

    @field_validator("venue", mode="before")
    @classmethod
    def validate_venue(cls, v):
        return _require_non_blank(v, "venue")

    @field_validator("exchange_ts_ns", mode="before")
    @classmethod
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"exchange_ts_ns must be positive: {v}")
        return v

    @field_validator("balances", mode="before")
    @classmethod
    def validate_balances(cls, v):
        if v is None:
            raise ValueError("balances cannot be None")
        result: Dict[str, Decimal] = {}
        for currency, amount in v.items():
            currency_key = _require_non_blank(currency, "balances currency")
            result[currency_key] = usd(amount) if currency_key == "USD" else crypto(amount)
        return result


class ExecutionTruth(BaseModel):
    """What the execution layer believes."""

    model_config = _base_model_config(use_enum_values=True)

    submitted_orders: List[SubmittedOrder] = Field(default_factory=list)
    pending_cancels: List[PendingCancel] = Field(default_factory=list)
    acks_received: List[Acknowledgement] = Field(default_factory=list)
    rejections: List[Rejection] = Field(default_factory=list)
    last_reconciliation_ts_ns: int = Field(default_factory=now_ns)

    @field_validator("last_reconciliation_ts_ns", mode="before")
    @classmethod
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"last_reconciliation_ts_ns must be positive: {v}")
        return v


class PortfolioTruth(BaseModel):
    """What the internal ledger believes."""

    model_config = _base_model_config()

    cash: Dict[str, Decimal] = Field(default_factory=dict)
    positions: List[PortfolioPosition] = Field(default_factory=list)
    reserved_buying_power: Decimal = Field(default=Decimal("0"))
    total_equity: Decimal = Field(default=Decimal("0"))
    last_update_ts_ns: int = Field(default_factory=now_ns)

    @field_validator("last_update_ts_ns", mode="before")
    @classmethod
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"last_update_ts_ns must be positive: {v}")
        return v

    @field_validator("cash", mode="before")
    @classmethod
    def validate_cash(cls, v):
        if v is None:
            raise ValueError("cash cannot be None")
        result: Dict[str, Decimal] = {}
        for currency, amount in v.items():
            currency_key = _require_non_blank(currency, "cash currency")
            result[currency_key] = usd(amount) if currency_key == "USD" else crypto(amount)
        return result

    @field_validator("reserved_buying_power", "total_equity", mode="before")
    @classmethod
    def validate_equity(cls, v, info):
        d = usd(v)
        if d < 0:
            raise ValueError(f"{info.field_name} cannot be negative: {v}")
        return d


class StrategyTruthEntry(BaseModel):
    """
    Individual strategy state.
    State is a generic string; validation occurs at strategy layer.
    """

    model_config = _base_model_config(use_enum_values=True)

    strategy_id: StrategyID
    state: str
    entry_price: Optional[Decimal] = None
    entry_decision_uuid: Optional[str] = None
    target_exposure: Decimal = Field(default=Decimal("0"))
    current_exposure: Decimal = Field(default=Decimal("0"))
    invalidation_state: str = "valid"
    ttl_ns: Optional[int] = None

    @field_validator("state", "invalidation_state", mode="before")
    @classmethod
    def validate_required_strings(cls, v, info):
        return _require_non_blank(v, info.field_name)

    @field_validator("entry_decision_uuid", mode="before")
    @classmethod
    def validate_optional_uuid(cls, v):
        if v is None:
            return v
        return _require_non_blank(v, "entry_decision_uuid")

    @field_validator("entry_price", mode="before")
    @classmethod
    def validate_entry_price(cls, v):
        if v is not None:
            p = price(v)
            if p <= 0:
                raise ValueError(f"entry_price must be positive: {v}")
            return p
        return v

    @field_validator("target_exposure", "current_exposure", mode="before")
    @classmethod
    def validate_exposure(cls, v):
        q = crypto(v)
        if q < 0:
            raise ValueError(f"exposure cannot be negative: {v}")
        return q

    @field_validator("ttl_ns", mode="before")
    @classmethod
    def validate_ttl(cls, v):
        if v is not None and v <= 0:
            raise ValueError(f"ttl_ns must be positive if present: {v}")
        return v


class StrategyTruth(BaseModel):
    """What each strategy believes."""

    model_config = _base_model_config()

    active_strategies: List[StrategyTruthEntry] = Field(default_factory=list)
    last_update_ts_ns: int = Field(default_factory=now_ns)

    @field_validator("last_update_ts_ns", mode="before")
    @classmethod
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"last_update_ts_ns must be positive: {v}")
        return v


class RiskTruth(BaseModel):
    """What the risk system permits."""

    model_config = _base_model_config(use_enum_values=True)

    mode: RiskMode = RiskMode.NORMAL
    max_leverage: Decimal = Field(default=Decimal("1.0"))
    hard_flat_triggered: bool = False
    hard_flat_reason: Optional[str] = None
    stale_data_blocks: List[StaleDataBlock] = Field(default_factory=list)
    divergence_blocks: List[DivergenceBlock] = Field(default_factory=list)
    kill_switches_active: List[KillSwitchRecord] = Field(default_factory=list)
    marketability_limits: Dict[str, Decimal] = Field(default_factory=dict)

    @field_validator("max_leverage", mode="before")
    @classmethod
    def validate_leverage(cls, v):
        return _quantize_ratio(v, "max_leverage", allow_zero=True)

    @field_validator("hard_flat_reason", mode="before")
    @classmethod
    def validate_hard_flat_reason(cls, v):
        if v is None:
            return v
        return _require_non_blank(v, "hard_flat_reason")

    @field_validator("marketability_limits", mode="before")
    @classmethod
    def validate_marketability_limits(cls, v):
        if v is None:
            raise ValueError("marketability_limits cannot be None")
        result: Dict[str, Decimal] = {}
        for symbol, limit in v.items():
            symbol_key = _require_non_blank(symbol, "marketability_limits symbol")
            q = crypto(limit)
            if q < 0:
                raise ValueError(f"marketability limit cannot be negative: {limit}")
            result[symbol_key] = q
        return result

    @model_validator(mode="after")
    def validate_hard_flat_fields(self):
        if self.hard_flat_triggered and not self.hard_flat_reason:
            raise ValueError("hard_flat_reason is required when hard_flat_triggered is True")
        return self


class TruthFrame(BaseModel):
    """Complete truth frame with all five truths."""

    model_config = _base_model_config(use_enum_values=True)

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
    reconcile_alerts: List[Dict[str, Any]] = Field(default_factory=list)
    schema_version: int = Field(default=1)

    @field_validator("truth_frame_id", mode="before")
    @classmethod
    def validate_truth_frame_id(cls, v):
        return _require_non_blank(v, "truth_frame_id")

    @field_validator("timestamp_ns", mode="before")
    @classmethod
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"timestamp_ns must be positive: {v}")
        return v

    @field_validator("divergence_ns", mode="before")
    @classmethod
    def validate_divergence(cls, v):
        if v < 0:
            raise ValueError(f"divergence_ns cannot be negative: {v}")
        return v

    @field_validator("schema_version", mode="before")
    @classmethod
    def validate_version(cls, v):
        if v <= 0:
            raise ValueError(f"schema_version must be positive: {v}")
        return v

    @field_validator("divergence_reasons", mode="before")
    @classmethod
    def validate_divergence_reasons(cls, v):
        if v is None:
            raise ValueError("divergence_reasons cannot be None")
        return [_require_non_blank(item, "divergence_reasons item") for item in v]

    @model_validator(mode="after")
    def validate_truth_consistency(self):
        if self.status == TruthStatus.RECONCILED:
            if self.divergence_ns != 0:
                raise ValueError("RECONCILED TruthFrame must have divergence_ns == 0")
            if self.divergence_reasons:
                raise ValueError("RECONCILED TruthFrame must not have divergence_reasons")
        else:
            if self.divergence_reasons and self.divergence_ns == 0:
                raise ValueError(
                    "TruthFrame with divergence_reasons must have divergence_ns > 0 when not RECONCILED"
                )
        return self


# ============================================
# 4. OrderIntent
# ============================================


class OrderIntent(BaseModel):
    """
    Legal pre-execution order intent from decision/risk layers.

    Compatibility note:
    - OrderIntent is not currently the active execution submit contract.
    - Active execution submits use OrderRequest (app/models/orders.py).
    - This model remains conceptual/dormant until a future Board-approved
      runtime wiring packet activates it.
    """

    model_config = _base_model_config(use_enum_values=True)

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

    @field_validator("order_intent_id", "decision_uuid", "symbol", mode="before")
    @classmethod
    def validate_required_strings(cls, v, info):
        return _require_non_blank(v, info.field_name)

    @field_validator("risk_approval_decision_uuid", mode="before")
    @classmethod
    def validate_risk_approval_uuid(cls, v):
        if not isinstance(v, str):
            raise TypeError("risk_approval_decision_uuid must be a string")
        return v.strip()

    @field_validator("quantity", mode="before")
    @classmethod
    def validate_quantity(cls, v):
        q = crypto(v)
        if q <= 0:
            raise ValueError(f"quantity must be positive: {v}")
        return q

    @field_validator("limit_price", mode="before")
    @classmethod
    def validate_limit_price(cls, v):
        if v is not None:
            p = price(v)
            if p <= 0:
                raise ValueError(f"limit_price must be positive: {v}")
            return p
        return v

    @field_validator("confidence", mode="before")
    @classmethod
    def validate_confidence(cls, v):
        return confidence(v)

    @field_validator("expected_cost_bps", mode="before")
    @classmethod
    def validate_cost(cls, v):
        d = bps(v)
        if d < 0:
            raise ValueError(f"expected_cost_bps cannot be negative: {v}")
        return d

    @field_validator("ttl_ns", mode="before")
    @classmethod
    def validate_ttl(cls, v):
        if v <= 0:
            raise ValueError(f"ttl_ns must be positive: {v}")
        return v

    @model_validator(mode="after")
    def validate_order_shape(self):
        if self.order_type == OrderType.MARKET and self.limit_price is not None:
            raise ValueError("limit_price must be None for MARKET orders")
        if self.order_type in {OrderType.LIMIT, OrderType.POST_ONLY} and self.limit_price is None:
            raise ValueError("limit_price is required for LIMIT and POST_ONLY orders")
        if self.risk_approved:
            if not self.risk_approval_decision_uuid:
                raise ValueError(
                    "risk_approval_decision_uuid is required and must be non-blank "
                    "when risk_approved is True"
                )
        else:
            if self.risk_approval_decision_uuid:
                raise ValueError(
                    "risk_approval_decision_uuid must be blank when risk_approved is False"
                )
        return self


# ============================================
# 5. ExecutionEvent
# ============================================


class ExecutionEvent(BaseModel):
    """Execution layer events."""

    model_config = _base_model_config(use_enum_values=True)

    execution_event_id: str = Field(default_factory=lambda: str(uuid4()))
    order_intent_id: str
    event_type: ExecutionEventType
    timestamp_ns: int = Field(default_factory=now_ns)
    venue: str
    venue_order_id: Optional[str] = None
    status: InternalOrderStatus
    error: Optional[str] = None
    retry_count: int = Field(default=0)

    @field_validator("execution_event_id", "order_intent_id", "venue", mode="before")
    @classmethod
    def validate_required_strings(cls, v, info):
        return _require_non_blank(v, info.field_name)

    @field_validator("venue_order_id", "error", mode="before")
    @classmethod
    def validate_optional_strings(cls, v, info):
        if v is None:
            return v
        return _require_non_blank(v, info.field_name)

    @field_validator("timestamp_ns", mode="before")
    @classmethod
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"timestamp_ns must be positive: {v}")
        return v

    @field_validator("retry_count", mode="before")
    @classmethod
    def validate_retry(cls, v):
        if v < 0:
            raise ValueError(f"retry_count cannot be negative: {v}")
        return v

    @model_validator(mode="after")
    def validate_execution_semantics(self):
        if self.event_type in {
            ExecutionEventType.ACK,
            ExecutionEventType.CANCEL_ACK,
            ExecutionEventType.PARTIAL_FILL,
            ExecutionEventType.FULL_FILL,
        } and not self.venue_order_id:
            raise ValueError(f"venue_order_id is required for event_type={self.event_type}")

        if self.event_type == ExecutionEventType.REJECT and not self.error:
            raise ValueError("error is required for REJECT events")

        return self


# ============================================
# 6. FillEvent
# ============================================


class FillEvent(BaseModel):
    """
    Fill telemetry contract emitted from execution fill outcomes.

    Active compatibility mapping:
    - execution_event_id identifies the execution/order event source.
    - order_intent_id may carry active OrderRequest.id as a compatibility
      bridge until OrderIntent is runtime-wired.
    - decision_uuid remains the causal decision-chain authority.
    """

    model_config = _base_model_config(use_enum_values=True)

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

    @field_validator(
        "fill_event_id",
        "execution_event_id",
        "order_intent_id",
        "decision_uuid",
        "symbol",
        "fee_currency",
        "venue_fill_id",
        mode="before",
    )
    @classmethod
    def validate_required_strings(cls, v, info):
        return _require_non_blank(v, info.field_name)

    @field_validator("quantity", mode="before")
    @classmethod
    def validate_quantity(cls, v):
        q = crypto(v)
        if q <= 0:
            raise ValueError(f"quantity must be positive: {v}")
        return q

    @field_validator("price", mode="before")
    @classmethod
    def validate_price(cls, v):
        p = price(v)
        if p <= 0:
            raise ValueError(f"price must be positive: {v}")
        return p

    @field_validator("fee", mode="before")
    @classmethod
    def validate_fee(cls, v):
        f = fee(v)
        if f < 0:
            raise ValueError(f"fee cannot be negative: {v}")
        return f

    @field_validator("exchange_ts_ns", "receive_ts_ns", mode="before")
    @classmethod
    def validate_timestamp_positive(cls, v):
        if v <= 0:
            raise ValueError(f"Timestamp must be positive: {v}")
        return v

    @model_validator(mode="after")
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

    model_config = _base_model_config(use_enum_values=True)

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

    @field_validator(
        "cancel_event_id",
        "execution_event_id",
        "order_intent_id",
        "decision_uuid",
        "reason",
        "venue_order_id",
        mode="before",
    )
    @classmethod
    def validate_required_strings(cls, v, info):
        return _require_non_blank(v, info.field_name)

    @field_validator(
        "cancel_submitted_ns",
        "cancel_acked_ns",
        "cancel_confirmed_ns",
        mode="before",
    )
    @classmethod
    def validate_timestamp(cls, v):
        if v is not None and v <= 0:
            raise ValueError(f"Timestamp must be positive: {v}")
        return v

    @model_validator(mode="after")
    def validate_ordering(self):
        submitted = self.cancel_submitted_ns
        acked = self.cancel_acked_ns
        confirmed = self.cancel_confirmed_ns

        if acked is not None and acked < submitted:
            raise ValueError(
                f"cancel_acked_ns ({acked}) < cancel_submitted_ns ({submitted})"
            )
        if confirmed is not None and acked is not None and confirmed < acked:
            raise ValueError(
                f"cancel_confirmed_ns ({confirmed}) < cancel_acked_ns ({acked})"
            )
        if confirmed is not None and acked is None:
            raise ValueError("cancel_confirmed_ns cannot be set when cancel_acked_ns is None")

        return self


# ============================================
# 8. PortfolioSnapshot
# ============================================


class PortfolioSnapshot(BaseModel):
    """Complete portfolio state."""

    model_config = _base_model_config()

    snapshot_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp_ns: int = Field(default_factory=now_ns)
    cash: Dict[str, Decimal] = Field(default_factory=dict)
    positions: List[PortfolioPosition] = Field(default_factory=list)
    total_equity: Decimal = Field(default=Decimal("0"))
    reserved_buying_power: Decimal = Field(default=Decimal("0"))
    available_buying_power: Decimal = Field(default=Decimal("0"))
    leverage: Decimal = Field(default=Decimal("0"))

    @field_validator("snapshot_id", mode="before")
    @classmethod
    def validate_snapshot_id(cls, v):
        return _require_non_blank(v, "snapshot_id")

    @field_validator("timestamp_ns", mode="before")
    @classmethod
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"timestamp_ns must be positive: {v}")
        return v

    @field_validator("cash", mode="before")
    @classmethod
    def validate_cash(cls, v):
        if v is None:
            raise ValueError("cash cannot be None")
        result: Dict[str, Decimal] = {}
        for currency, amount in v.items():
            currency_key = _require_non_blank(currency, "cash currency")
            result[currency_key] = usd(amount) if currency_key == "USD" else crypto(amount)
        return result

    @field_validator(
        "total_equity",
        "reserved_buying_power",
        "available_buying_power",
        mode="before",
    )
    @classmethod
    def validate_equity(cls, v, info):
        d = usd(v)
        if d < 0:
            raise ValueError(f"{info.field_name} cannot be negative: {v}")
        return d

    @field_validator("leverage", mode="before")
    @classmethod
    def validate_leverage(cls, v):
        return _quantize_ratio(v, "leverage", allow_zero=True)


# ============================================
# 9. RiskDecision
# ============================================


class RiskDecision(BaseModel):
    """Risk system decisions."""

    model_config = _base_model_config(use_enum_values=True)

    risk_decision_id: str = Field(default_factory=lambda: str(uuid4()))
    decision_uuid: str
    timestamp_ns: int = Field(default_factory=now_ns)
    risk_mode: RiskMode
    max_leverage: Decimal = Field(default=Decimal("1.0"))
    sizing_multiplier: Decimal = Field(default=Decimal("1.0"))
    approved_strategies: List[StrategyID] = Field(default_factory=list)
    blocked_strategies: List[StrategyID] = Field(default_factory=list)
    requires_manual_reset: bool = False
    reason: str
    truth_frame_id: str
    violations: List[str] = Field(default_factory=list)

    @field_validator("risk_decision_id", "decision_uuid", "reason", "truth_frame_id", mode="before")
    @classmethod
    def validate_required_strings(cls, v, info):
        return _require_non_blank(v, info.field_name)

    @field_validator("timestamp_ns", mode="before")
    @classmethod
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"timestamp_ns must be positive: {v}")
        return v

    @field_validator("max_leverage", "sizing_multiplier", mode="before")
    @classmethod
    def validate_positive(cls, v, info):
        return _quantize_ratio(v, info.field_name, allow_zero=False)

    @field_validator("violations", mode="before")
    @classmethod
    def validate_violations(cls, v):
        if v is None:
            raise ValueError("violations cannot be None")
        return [_require_non_blank(item, "violations item") for item in v]

    @model_validator(mode="after")
    def validate_strategy_sets(self):
        overlap = set(self.approved_strategies).intersection(set(self.blocked_strategies))
        if overlap:
            raise ValueError(
                f"approved_strategies and blocked_strategies must be disjoint, overlap={sorted(overlap)}"
            )
        return self


# ============================================
# 10. StrategyVote
# ============================================


class StrategyVote(BaseModel):
    """Strategy voting output."""

    model_config = _base_model_config(use_enum_values=True)

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

    @field_validator("vote_id", "decision_uuid", mode="before")
    @classmethod
    def validate_required_strings(cls, v, info):
        return _require_non_blank(v, info.field_name)

    @field_validator("timestamp_ns", "expected_duration_ns", mode="before")
    @classmethod
    def validate_positive(cls, v):
        if v <= 0:
            raise ValueError(f"Value must be positive: {v}")
        return v

    @field_validator("confidence", "risk_appetite", mode="before")
    @classmethod
    def validate_confidence(cls, v):
        return confidence(v)

    @field_validator("expected_move_bps", mode="before")
    @classmethod
    def validate_move(cls, v):
        return bps(v)

    @field_validator("invalidation_conditions", mode="before")
    @classmethod
    def validate_invalidation_conditions(cls, v):
        if v is None:
            raise ValueError("invalidation_conditions cannot be None")
        return [_require_non_blank(item, "invalidation_conditions item") for item in v]

    @field_validator("metadata", mode="before")
    @classmethod
    def validate_metadata(cls, v):
        if v is None:
            raise ValueError("metadata cannot be None")
        return v


# ============================================
# 11. FeatureVector
# ============================================


class FeatureVector(BaseModel):
    """Feature engine outputs with typed payload."""

    model_config = _base_model_config()

    feature_vector_id: str = Field(default_factory=lambda: str(uuid4()))
    decision_uuid: str
    timestamp_ns: int = Field(default_factory=now_ns)
    symbol: str
    features: FeaturePayload = Field(default_factory=FeaturePayload)

    @field_validator("feature_vector_id", "decision_uuid", "symbol", mode="before")
    @classmethod
    def validate_required_strings(cls, v, info):
        return _require_non_blank(v, info.field_name)

    @field_validator("timestamp_ns", mode="before")
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

    model_config = _base_model_config(use_enum_values=True)

    checkpoint_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp_ns: int = Field(default_factory=now_ns)
    checkpoint_type: CheckpointType
    wal_seq: int
    truth_frame_id: Optional[str] = None
    snapshot_path: Optional[str] = None
    checksum: str
    replay_position: Optional[ReplayPosition] = None

    @field_validator("checkpoint_id", "checksum", mode="before")
    @classmethod
    def validate_required_strings(cls, v, info):
        return _require_non_blank(v, info.field_name)

    @field_validator("truth_frame_id", "snapshot_path", mode="before")
    @classmethod
    def validate_optional_strings(cls, v, info):
        if v is None:
            return v
        return _require_non_blank(v, info.field_name)

    @field_validator("timestamp_ns", mode="before")
    @classmethod
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"timestamp_ns must be positive: {v}")
        return v

    @field_validator("wal_seq", mode="before")
    @classmethod
    def validate_wal_seq(cls, v):
        if v < 0:
            raise ValueError(f"wal_seq cannot be negative: {v}")
        return v

    @model_validator(mode="after")
    def validate_checkpoint_semantics(self):
        if self.checkpoint_type == CheckpointType.TRUTH_FRAME:
            if not self.truth_frame_id:
                raise ValueError("truth_frame_id is required for TRUTH_FRAME checkpoints")
            if self.snapshot_path is not None:
                raise ValueError("snapshot_path must be None for TRUTH_FRAME checkpoints")

        if self.checkpoint_type == CheckpointType.SNAPSHOT:
            if not self.snapshot_path:
                raise ValueError("snapshot_path is required for SNAPSHOT checkpoints")
            if self.truth_frame_id is not None:
                raise ValueError("truth_frame_id must be None for SNAPSHOT checkpoints")

        return self


# ============================================
# 13. DivergenceEvent
# ============================================


class DivergenceEvent(BaseModel):
    """Truth divergence detection."""

    model_config = _base_model_config(use_enum_values=True)

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

    @field_validator("divergence_id", "truth_frame_id", mode="before")
    @classmethod
    def validate_required_strings(cls, v, info):
        return _require_non_blank(v, info.field_name)

    @field_validator("resolution_action", mode="before")
    @classmethod
    def validate_optional_resolution_action(cls, v):
        if v is None:
            return v
        return _require_non_blank(v, "resolution_action")

    @field_validator("timestamp_ns", mode="before")
    @classmethod
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"timestamp_ns must be positive: {v}")
        return v

    @field_validator("duration_ns", mode="before")
    @classmethod
    def validate_duration(cls, v):
        if v < 0:
            raise ValueError(f"duration_ns cannot be negative: {v}")
        return v

    @field_validator("magnitude", mode="before")
    @classmethod
    def validate_magnitude(cls, v):
        if v is None:
            return v
        m = confidence(v)
        if m < 0:
            raise ValueError(f"magnitude cannot be negative: {v}")
        return m

    @field_validator("expected", "observed", mode="before")
    @classmethod
    def validate_maps(cls, v):
        if v is None:
            raise ValueError("expected/observed cannot be None")
        if not isinstance(v, dict):
            raise TypeError(f"expected/observed must be dict, got {type(v).__name__}")
        return v


# ============================================
# EXPORTS
# ============================================

__all__ = [
    # Typed submodels
    "ExchangePosition",
    "ExchangeOpenOrder",
    "ExchangeFill",
    "SubmittedOrder",
    "PendingCancel",
    "Acknowledgement",
    "Rejection",
    "PortfolioPosition",
    "KillSwitchRecord",
    "DivergenceBlock",
    "StaleDataBlock",
    "ReplayPosition",
    "FeaturePayload",
    # Core contracts
    "EventEnvelope",
    "DecisionRecord",
    "ExchangeTruth",
    "ExecutionTruth",
    "PortfolioTruth",
    "StrategyTruthEntry",
    "StrategyTruth",
    "RiskTruth",
    "TruthFrame",
    "OrderIntent",
    "ExecutionEvent",
    "FillEvent",
    "CancelEvent",
    "PortfolioSnapshot",
    "RiskDecision",
    "StrategyVote",
    "FeatureVector",
    "RecoveryCheckpoint",
    "DivergenceEvent",
]
