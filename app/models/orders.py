"""
Canonical Order Models for Sovereign Trading System

This file defines the canonical order lifecycle contracts for the execution layer.
All order submission, fill, and status tracking uses these models.

TIMESTAMP TRUTH:
- exchange_ts_ns: Authoritative exchange timestamp (REQUIRED, no default)
- receive_ts_ns: Local receive timestamp for monitoring/telemetry (REQUIRED, no default)

Importer migration: execution files (engine.py, order_router.py, orchestrator.py)
will be updated in Bundle 3 to import from this module instead of the tombstone.
"""

from decimal import Decimal
from typing import Dict, Any, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import OrderSide, OrderType, InternalOrderStatus, SleeveType
from app.utils.decimal_utils import crypto, price, fee, usd


def _require_non_blank(value: str, field_name: str) -> str:
    """Require non-blank string value."""
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name} must be non-blank")
    return stripped


def _base_model_config() -> ConfigDict:
    """Base configuration for order models."""
    return ConfigDict(extra="forbid", use_enum_values=True)


class OrderRequest(BaseModel):
    """
    Order request from strategy/execution layer to broker.
    
    This is the canonical order request contract. All order submissions
    must use this model.
    
    Fields:
    - id: Unique order identifier (client-generated)
    - symbol: Trading symbol
    - side: BUY or SELL
    - quantity: Order quantity in base units (Decimal)
    - order_type: MARKET, LIMIT, or POST_ONLY
    - limit_price: Required for LIMIT and POST_ONLY orders (Decimal)
    - strategy: SleeveType enum (canonical sleeve identity)
    - confidence: Signal confidence (0-1)
    - decision_uuid: Optional decision ID for telemetry causality
    - exchange_ts_ns: Authoritative exchange timestamp (REQUIRED, no default)
    - receive_ts_ns: Local receive timestamp for monitoring (REQUIRED, no default)
    - metadata: Additional context
    """
    
    model_config = _base_model_config()
    
    id: str = Field(default_factory=lambda: str(uuid4()))
    symbol: str
    side: OrderSide
    quantity: Decimal
    order_type: OrderType = OrderType.MARKET
    limit_price: Optional[Decimal] = None
    strategy: SleeveType
    confidence: float = Field(ge=0.0, le=1.0)
    decision_uuid: Optional[str] = None
    exchange_ts_ns: int  # REQUIRED — no default
    receive_ts_ns: int   # REQUIRED — monitoring/telemetry only
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    @field_validator("id", "symbol", mode="before")
    @classmethod
    def validate_required_strings(cls, v, info):
        return _require_non_blank(v, info.field_name)

    @field_validator("decision_uuid", mode="before")
    @classmethod
    def validate_optional_decision_uuid(cls, v):
        if v is None:
            return v
        return _require_non_blank(v, "decision_uuid")
    
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
    
    @field_validator("exchange_ts_ns", "receive_ts_ns", mode="before")
    @classmethod
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"timestamp must be positive: {v}")
        return v
    
    @model_validator(mode="after")
    def validate_order_shape(self):
        if self.order_type in (OrderType.LIMIT, OrderType.POST_ONLY) and self.limit_price is None:
            raise ValueError(f"limit_price is required for {self.order_type} orders")
        if self.order_type == OrderType.MARKET and self.limit_price is not None:
            raise ValueError("limit_price must be None for MARKET orders")
        return self
    
    @property
    def exchange_ts_sec(self) -> float:
        """Convert exchange timestamp to seconds (display only)."""
        return self.exchange_ts_ns / 1_000_000_000.0
    
    @property
    def notional_usd(self) -> Decimal:
        """Calculate notional value in USD (Decimal)."""
        if self.limit_price:
            return self.quantity * self.limit_price
        return Decimal("0")


class OrderFill(BaseModel):
    """
    Order fill confirmation from broker/exchange.
    
    This is the canonical fill contract. All fill confirmations
    must use this model.
    
    Fields:
    - order_id: Client order ID (matches OrderRequest.id)
    - symbol: Trading symbol
    - side: BUY or SELL
    - quantity: Filled quantity (Decimal)
    - price: Fill price (Decimal)
    - fee: Fee paid (Decimal)
    - fee_currency: Currency of fee (default USD)
    - status: InternalOrderStatus enum (canonical execution status)
    - exchange_ts_ns: Authoritative exchange timestamp (REQUIRED, no default)
    - receive_ts_ns: Local receive timestamp for monitoring (REQUIRED, no default)
    - latency_ms: Execution latency in milliseconds (monitoring/telemetry)
    - venue_order_id: Exchange order ID (if available)
    """
    
    model_config = _base_model_config()
    
    order_id: str
    symbol: str
    side: OrderSide
    quantity: Decimal
    price: Decimal
    fee: Decimal = Field(default=Decimal("0"))
    fee_currency: str = "USD"
    status: InternalOrderStatus
    exchange_ts_ns: int  # REQUIRED — no default
    receive_ts_ns: int   # REQUIRED — monitoring/telemetry only
    latency_ms: float = 0.0
    venue_order_id: Optional[str] = None
    
    @field_validator("order_id", "symbol", "fee_currency", mode="before")
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
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"timestamp must be positive: {v}")
        return v
    
    @field_validator("latency_ms", mode="before")
    @classmethod
    def validate_latency(cls, v):
        if v < 0:
            raise ValueError(f"latency_ms cannot be negative: {v}")
        if v > 60000:  # 60 seconds max reasonable latency
            raise ValueError(f"latency_ms unreasonably high: {v}")
        return v
    
    @field_validator("venue_order_id", mode="before")
    @classmethod
    def validate_venue_order_id(cls, v):
        if v is not None:
            return _require_non_blank(v, "venue_order_id")
        return v
    
    @property
    def exchange_ts_sec(self) -> float:
        """Convert exchange timestamp to seconds (display only)."""
        return self.exchange_ts_ns / 1_000_000_000.0
    
    @property
    def notional_usd(self) -> Decimal:
        """Calculate notional value in USD (Decimal)."""
        return self.quantity * self.price
    
    @property
    def net_amount_usd(self) -> Decimal:
        """Calculate net amount after fees (Decimal)."""
        if self.side == OrderSide.BUY:
            return -self.notional_usd - self.fee
        else:
            return self.notional_usd - self.fee


# ============================================
# EXPORTS
# ============================================

__all__ = [
    "OrderRequest",
    "OrderFill",
]
