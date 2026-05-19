from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping


class PortalEnvironment(str, Enum):
    PAPER = "paper"
    SANDBOX = "sandbox"
    LIVE = "live"
    BACKTEST = "backtest"


class PortalAssetClass(str, Enum):
    EQUITY = "equity"
    US_EQUITY = "us_equity"
    ETF = "etf"
    CRYPTO = "crypto"
    OPTION = "option"
    FUTURE = "future"
    FOREX = "forex"
    COMMODITY = "commodity"
    INDEX_PRODUCT = "index_product"
    UNKNOWN = "unknown"


class PortalPolicyMode(str, Enum):
    EXPLICIT_PREFERRED_VENUE = "explicit_preferred_venue"
    CAPABILITY_FIRST = "capability_first"
    FAIL_CLOSED = "fail_closed"


UNKNOWN_PORTAL_QUALITY: Mapping[str, str] = {
    "speed": "UNKNOWN",
    "fees": "UNKNOWN",
    "spread": "UNKNOWN",
    "liquidity": "UNKNOWN",
    "buying_power": "UNKNOWN",
    "data_freshness": "UNKNOWN",
    "reliability": "UNKNOWN",
}


def normalize_asset_class(value: str | PortalAssetClass | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, PortalAssetClass):
        return value.value
    normalized = str(value).strip().lower()
    if normalized == "us_equity":
        return PortalAssetClass.US_EQUITY.value
    if normalized in {"etf", "fund"}:
        return PortalAssetClass.ETF.value
    if normalized in {"stock", "equity"}:
        return PortalAssetClass.EQUITY.value
    return normalized


def normalize_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper()


@dataclass(frozen=True)
class VenueCapability:
    venue_id: str
    portal_name: str
    environment: str
    asset_class: str
    symbol: str
    normalized_symbol: str
    venue_symbol_format: str
    quote_source: str
    market_data_available: bool
    tradability_source: str
    supported_order_types: frozenset[str]
    supported_time_in_force: frozenset[str]
    fractional_support: bool
    min_notional: Decimal | None
    min_quantity: Decimal | None
    quantity_step: Decimal | None
    market_session_status_source: str
    execution_adapter: str
    reconciliation_adapter: str
    read_only: bool
    paper_mutation: bool
    sandbox_mutation: bool
    live_mutation: bool
    live_blocked: bool
    supported_actions: frozenset[str] = frozenset({"buy"})
    enabled: bool = True
    disabled_reason: str | None = None
    unavailable_reason: str | None = None
    fail_closed_reason_code: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    portal_quality_metrics: Mapping[str, str] = field(default_factory=lambda: dict(UNKNOWN_PORTAL_QUALITY))

    @property
    def portal_key(self) -> str:
        return f"{self.venue_id}_{self.environment}"

    @property
    def capability_key(self) -> str:
        return f"{self.portal_key}:{self.asset_class}:{self.normalized_symbol}"

    @property
    def mutation_authorized_by_default(self) -> bool:
        return False

    def matches_symbol(self, symbol: str) -> bool:
        requested = normalize_symbol(symbol)
        return self.normalized_symbol == requested or self.normalized_symbol == "*"

    def matches_asset_class(self, asset_class: str | None) -> bool:
        requested = normalize_asset_class(asset_class)
        if requested is None:
            return True
        if self.asset_class == PortalAssetClass.UNKNOWN.value:
            return True
        if requested == self.asset_class:
            return True
        return {requested, self.asset_class} <= {PortalAssetClass.EQUITY.value, PortalAssetClass.US_EQUITY.value}

    def supports_request(self, request: "PortalSelectionRequest") -> tuple[bool, tuple[str, ...]]:
        reasons: list[str] = []
        if not self.enabled:
            reasons.append(self.fail_closed_reason_code or self.disabled_reason or "PORTAL_DISABLED")
        if self.environment != request.environment:
            reasons.append("ENVIRONMENT_UNSUPPORTED")
        if request.environment == PortalEnvironment.LIVE.value and self.live_blocked:
            reasons.append("LIVE_BLOCKED")
        if not self.matches_symbol(request.symbol):
            reasons.append("SYMBOL_UNSUPPORTED")
        if not self.matches_asset_class(request.asset_class):
            reasons.append("ASSET_UNSUPPORTED")
        if request.action and request.action.lower() not in self.supported_actions:
            reasons.append("ACTION_UNSUPPORTED")
        if request.order_type and request.order_type.lower() not in self.supported_order_types:
            reasons.append("ORDER_TYPE_UNSUPPORTED")
        if request.time_in_force and request.time_in_force.upper() not in self.supported_time_in_force:
            reasons.append("TIME_IN_FORCE_UNSUPPORTED")
        if self.unavailable_reason:
            reasons.append(self.unavailable_reason)
        return not reasons, tuple(dict.fromkeys(reasons))


@dataclass(frozen=True)
class CapabilityAwareCandidate:
    raw_symbol: str
    normalized_symbol: str
    venue_id: str
    portal_name: str
    asset_class: str
    environment: str
    quote_source: str
    execution_adapter: str
    reconciliation_adapter: str
    tradable: bool
    market_data_available: bool
    unavailable_reason: str | None
    disabled_reason: str | None
    fail_closed_reason_code: str | None
    capability_key: str
    mutation_authorized: bool = False

    @classmethod
    def from_capability(cls, capability: VenueCapability, *, tradable: bool, reasons: tuple[str, ...] = ()) -> "CapabilityAwareCandidate":
        reason = "|".join(reasons) if reasons else capability.unavailable_reason
        return cls(
            raw_symbol=capability.symbol,
            normalized_symbol=capability.normalized_symbol,
            venue_id=capability.venue_id,
            portal_name=capability.portal_name,
            asset_class=capability.asset_class,
            environment=capability.environment,
            quote_source=capability.quote_source,
            execution_adapter=capability.execution_adapter,
            reconciliation_adapter=capability.reconciliation_adapter,
            tradable=tradable,
            market_data_available=capability.market_data_available,
            unavailable_reason=reason,
            disabled_reason=capability.disabled_reason,
            fail_closed_reason_code=capability.fail_closed_reason_code,
            capability_key=capability.capability_key,
            mutation_authorized=capability.mutation_authorized_by_default,
        )


@dataclass(frozen=True)
class PortalSelectionRequest:
    symbol: str
    asset_class: str | None = None
    environment: str = PortalEnvironment.PAPER.value
    action: str = "buy"
    order_type: str = "limit"
    time_in_force: str = "DAY"
    policy_mode: str = PortalPolicyMode.FAIL_CLOSED.value
    preferred_venue: str | None = None
    allow_fallback: bool = False


@dataclass(frozen=True)
class PortalSelectionResult:
    selected: VenueCapability | None
    candidates: tuple[VenueCapability, ...]
    rejected: Mapping[str, tuple[str, ...]]
    status: str
    reason_codes: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return self.selected is not None and self.status == "selected"

    @property
    def ambiguous(self) -> bool:
        return "AMBIGUOUS_PORTAL" in self.reason_codes
