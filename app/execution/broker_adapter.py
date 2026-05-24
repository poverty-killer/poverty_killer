"""
POVERTY KILLER — Broker Adapter Contract

Pre-integration, pure Protocol/ABC definitions only.

This module defines the abstract interface that all broker adapters
must implement. PaperBroker and OrderRouter are existing concrete
implementations. Future adapters (Alpaca, IB, etc.) will implement
this contract.

Design constraints:
- No concrete implementations (Protocol/ABC only).
- No imports from runtime modules (MainLoop, SignalFusion, Risk).
- No network calls.
- No side effects.
- No order routing authority — this is a contract, not an executor.

Author: D / DeepSeek — Stage 2-G0B
Date: 2026-05-03
Status: PRE-INTEGRATION — PURE CONTRACT — NO IMPLEMENTATION
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum, unique
from typing import (
    Protocol, Optional, List, Dict, Any,
    FrozenSet, Tuple,
)


# ────────────────────────────────────────────────────────────────
# Broker Enums
# ────────────────────────────────────────────────────────────────

@unique
class BrokerMode(str, Enum):
    """Execution mode for broker adapter."""
    PAPER = "paper"              # Simulated execution
    LIVE = "live"                # Real execution (requires Board approval)
    SANDBOX = "sandbox"          # Test environment


@unique
class OrderRejectReason(str, Enum):
    """Taxonomy of order rejection reasons."""
    # Session / market
    MARKET_CLOSED = "market_closed"
    HALTED = "halted"
    OUTSIDE_SESSION = "outside_session"

    # Instrument
    INSTRUMENT_NOT_SUPPORTED = "instrument_not_supported"
    INSTRUMENT_NOT_TRADABLE = "instrument_not_tradable"
    CONTRACT_EXPIRED = "contract_expired"

    # Order validation
    INVALID_QUANTITY = "invalid_quantity"
    INVALID_PRICE = "invalid_price"
    MIN_NOTIONAL_NOT_MET = "min_notional_not_met"
    MAX_ORDER_QTY_EXCEEDED = "max_order_qty_exceeded"

    # Risk / margin
    INSUFFICIENT_BUYING_POWER = "insufficient_buying_power"
    INSUFFICIENT_MARGIN = "insufficient_margin"
    MARGIN_CALL = "margin_call"
    SHORT_LOCATE_UNAVAILABLE = "short_locate_unavailable"
    BORROW_UNAVAILABLE = "borrow_unavailable"

    # Operational
    RATE_LIMIT = "rate_limit"
    EXCHANGE_REJECTION = "exchange_rejection"
    DUPLICATE_ORDER = "duplicate_order"
    UNKNOWN_SYMBOL = "unknown_symbol"
    ADAPTER_ERROR = "adapter_error"


@unique
class BrokerOrderState(str, Enum):
    """Canonical order state taxonomy."""
    PENDING = "pending"                    # Accepted by adapter, not yet sent
    SENT = "sent"                          # Sent to venue
    ACKNOWLEDGED = "acknowledged"          # Venue acknowledged receipt
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"
    REPLACED = "replaced"


# ────────────────────────────────────────────────────────────────
# Broker Order Models
# ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class BrokerOrderRequest:
    """
    Canonical order request for any broker adapter.

    This is the universal order format that all strategies and the
    execution engine will use. Broker adapters translate this into
    venue-specific formats.
    """
    # Identity
    client_order_id: str                    # Our order ID (idempotency key)
    instrument_id: str
    symbol: str
    asset_class: str
    venue: str

    # Order details
    side: str                               # "buy" or "sell"
    quantity: Decimal
    order_type: str                         # "market", "limit", "stop", "stop_limit"
    limit_price: Optional[Decimal] = None
    stop_price: Optional[Decimal] = None
    time_in_force: str = "DAY"              # "DAY", "GTC", "IOC", "FOK"

    # Execution controls
    reduce_only: bool = False               # Only closes/reduces position
    protective_only: bool = False           # Exit-only (Moving Floor authority)
    max_slippage_bps: Decimal = Decimal("50")
    participation_limit_pct: Decimal = Decimal("5")

    # Auth trail
    decision_uuid: str = ""
    strategy_id: str = ""
    risk_decision_id: str = ""

    # Session policy
    session_policy: str = "reject_if_closed"  # "reject", "hold_for_open", "allow_extended"

    # Metadata
    urgency: str = "normal"                  # "low", "normal", "high", "emergency"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def notional_usd(self) -> Decimal:
        """Approximate notional value for sanity checks."""
        if self.limit_price:
            return self.quantity * self.limit_price
        return Decimal("0")


@dataclass(frozen=True)
class BrokerFill:
    """
    Canonical fill report from any broker adapter.
    """
    fill_id: str
    client_order_id: str
    decision_uuid: str
    symbol: str
    side: str
    filled_quantity: Decimal
    fill_price: Decimal
    fee: Decimal
    fee_currency: str
    exchange_ts_ns: int                     # Venue timestamp of fill
    adapter_ts_ns: int                      # Adapter local timestamp
    venue: str
    liquidity: str = "unknown"              # "maker", "taker"
    remaining_quantity: Decimal = Decimal("0")


@dataclass(frozen=True)
class BrokerOrderStatus:
    """
    Current status of an order from broker perspective.
    """
    client_order_id: str
    venue_order_id: Optional[str]
    state: BrokerOrderState
    filled_quantity: Decimal
    remaining_quantity: Decimal
    average_fill_price: Optional[Decimal]
    fee_total: Decimal
    reject_reason: Optional[OrderRejectReason] = None
    reject_message: Optional[str] = None
    last_update_ns: int = 0
    fills: Tuple[BrokerFill, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class BrokerAccountSnapshot:
    """
    Account state snapshot from broker.

    BOARD ESCALATION: Margin/borrow fields require broker-specific data.
    """
    account_id: str
    currency: str
    total_equity: Decimal
    cash: Decimal
    buying_power: Decimal                  # Available for new positions
    margin_used: Decimal
    margin_requirement: Decimal
    margin_call: bool = False
    short_positions_value: Decimal = Decimal("0")
    borrow_used: Decimal = Decimal("0")
    available_to_withdraw: Decimal = Decimal("0")
    timestamp_ns: int = 0


# ────────────────────────────────────────────────────────────────
# Broker Adapter Protocol
# ────────────────────────────────────────────────────────────────

class BrokerAdapter(Protocol):
    """
    Protocol for broker/execution adapters.

    Every broker adapter must:
    - Declare supported asset classes and venues.
    - Accept canonical BrokerOrderRequest and return BrokerFill/BrokerOrderStatus.
    - Handle session-aware rejection.
    - Support paper/live mode separation.
    - Use decision_uuid for idempotency.

    This is a Protocol, not an ABC — adapters can implement through
    duck typing. No concrete implementation exists in this file.
    """

    @property
    def adapter_id(self) -> str:
        """Unique broker adapter identifier."""
        ...

    @property
    def broker_mode(self) -> BrokerMode:
        """PAPER, LIVE, or SANDBOX."""
        ...

    @property
    def supported_asset_classes(self) -> FrozenSet[str]:
        """Asset classes this broker can execute."""
        ...

    @property
    def supported_venues(self) -> FrozenSet[str]:
        """Venues this broker can route to."""
        ...

    @property
    def supported_order_types(self) -> FrozenSet[str]:
        """Order types this broker supports."""
        ...

    def is_connected(self) -> bool:
        """Check if broker connection is alive."""
        ...

    def is_instrument_supported(self, symbol: str, asset_class: str) -> bool:
        """Check if this broker supports a specific instrument."""
        ...

    def submit_order(self, request: BrokerOrderRequest) -> BrokerOrderStatus:
        """
        Submit an order for execution.

        Must return immediately with PENDING/REJECTED status.
        Fill updates come via query methods or callbacks.
        """
        ...

    def cancel_order(self, client_order_id: str) -> BrokerOrderStatus:
        """Cancel an open order."""
        ...

    def replace_order(
        self, client_order_id: str, request: BrokerOrderRequest
    ) -> BrokerOrderStatus:
        """Replace (cancel+replace) an open order."""
        ...

    def get_order_status(self, client_order_id: str) -> BrokerOrderStatus:
        """Query current order status."""
        ...

    def get_open_orders(self, symbol: Optional[str] = None) -> List[BrokerOrderStatus]:
        """Get all open orders, optionally filtered by symbol."""
        ...

    def get_fills(
        self,
        symbol: Optional[str] = None,
        since_ns: Optional[int] = None,
        limit: int = 100,
    ) -> List[BrokerFill]:
        """Query fills, optionally filtered."""
        ...

    def get_account(self) -> BrokerAccountSnapshot:
        """Get current account state."""
        ...

    def get_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get current positions."""
        ...

    def estimate_margin_requirement(
        self, symbol: str, side: str, quantity: Decimal, price: Decimal
    ) -> Decimal:
        """Estimate margin required for a potential order."""
        ...

    def check_short_availability(self, symbol: str, quantity: Decimal) -> Tuple[bool, str]:
        """
        Check if short shares/contracts are available.

        BOARD ESCALATION: Requires broker-specific locate/borrow data.
        Returns (available: bool, reason: str).
        """
        ...


# ────────────────────────────────────────────────────────────────
# Supported Declarations (for documentation)
# ────────────────────────────────────────────────────────────────

PAPER_BROKER_SUPPORTED_ASSETS: FrozenSet[str] = frozenset({
    "crypto", "equity", "etf", "future",
})

PAPER_BROKER_SUPPORTED_VENUES: FrozenSet[str] = frozenset({
    "KRAKEN", "NYSE", "NASDAQ", "CME", "PAPER",
})

PAPER_BROKER_SUPPORTED_ORDER_TYPES: FrozenSet[str] = frozenset({
    "market", "limit", "stop", "stop_limit",
})

KRAKEN_BROKER_SUPPORTED_ASSETS: FrozenSet[str] = frozenset({"crypto"})
KRAKEN_BROKER_SUPPORTED_VENUES: FrozenSet[str] = frozenset({"KRAKEN"})
KRAKEN_BROKER_SUPPORTED_ORDER_TYPES: FrozenSet[str] = frozenset({
    "market", "limit", "stop_loss", "take_profit", "stop_loss_limit", "take_profit_limit",
})


# ────────────────────────────────────────────────────────────────
# Module Exports
# ────────────────────────────────────────────────────────────────

__all__ = [
    "BrokerMode",
    "OrderRejectReason",
    "BrokerOrderState",
    "BrokerOrderRequest",
    "BrokerFill",
    "BrokerOrderStatus",
    "BrokerAccountSnapshot",
    "BrokerAdapter",
    "PAPER_BROKER_SUPPORTED_ASSETS",
    "PAPER_BROKER_SUPPORTED_VENUES",
    "PAPER_BROKER_SUPPORTED_ORDER_TYPES",
    "KRAKEN_BROKER_SUPPORTED_ASSETS",
    "KRAKEN_BROKER_SUPPORTED_VENUES",
    "KRAKEN_BROKER_SUPPORTED_ORDER_TYPES",
]