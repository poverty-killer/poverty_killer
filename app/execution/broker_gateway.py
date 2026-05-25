from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping, Protocol


class BrokerGatewayError(Exception):
    """Fail-closed gateway error with sanitized reason codes only."""

    def __init__(self, reason_code: str, *, message: str | None = None) -> None:
        self.reason_code = reason_code
        self.message = message or reason_code
        super().__init__(self.message)


class BrokerEnvironment(str, Enum):
    PAPER = "paper"
    SANDBOX = "sandbox"
    LIVE = "live"
    BACKTEST = "backtest"


class BrokerCredentialStatus(str, Enum):
    CONFIGURED = "configured"
    MISSING = "missing"
    UNKNOWN = "unknown"


class NormalizedBrokerStatus(str, Enum):
    ACCEPTED = "accepted"
    OPEN = "open"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    REJECTED = "rejected"
    CANCELED = "canceled"
    EXPIRED = "expired"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class BrokerAdapterIdentity:
    adapter_id: str
    venue_id: str
    portal_id: str
    environment: str
    base_url: str
    credential_status: str
    supported_methods: frozenset[str]
    supported_asset_classes: frozenset[str]
    live_blocked: bool


@dataclass(frozen=True)
class BrokerOrderSubmitRequest:
    symbol: str
    side: str
    order_type: str
    time_in_force: str
    quantity: Decimal
    client_order_id: str
    limit_price: Decimal | None = None
    asset_class: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def notional_cap_basis(self) -> Decimal | None:
        if self.limit_price is None:
            return None
        return self.quantity * self.limit_price


@dataclass(frozen=True)
class BrokerGatewayResponse:
    adapter_id: str
    venue_id: str
    portal_id: str
    environment: str
    request_method: str
    endpoint_path: str
    ok: bool
    mutation_occurred: bool
    live_blocked: bool
    broker_order_id: str | None = None
    client_order_id: str | None = None
    raw_broker_status: str | None = None
    normalized_status: str = NormalizedBrokerStatus.UNKNOWN.value
    reason_code: str | None = None
    message: str | None = None
    payload: Any = None
    reconciliation_metadata: Mapping[str, Any] = field(default_factory=dict)


class BrokerGatewayAdapter(Protocol):
    @property
    def identity(self) -> BrokerAdapterIdentity:
        ...

    @property
    def request_counts(self) -> Mapping[str, int]:
        ...

    def get_account(self) -> BrokerGatewayResponse:
        ...

    def get_positions(self) -> BrokerGatewayResponse:
        ...

    def get_open_orders(self) -> BrokerGatewayResponse:
        ...

    def get_clock(self) -> BrokerGatewayResponse:
        ...

    def get_asset(self, symbol: str) -> BrokerGatewayResponse:
        ...

    def get_order_status(self, order_id: str) -> BrokerGatewayResponse:
        ...

    def get_account_activities(self, *, activity_types: str = "FILL", page_size: int = 100) -> BrokerGatewayResponse:
        ...

    def submit_order(self, order: BrokerOrderSubmitRequest) -> BrokerGatewayResponse:
        ...

    def cancel_order(self, order_id: str) -> BrokerGatewayResponse:
        ...
