from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from app.market.venue_capabilities import (
    CapabilityAwareCandidate,
    CredentialStatus,
    PortalAssetClass,
    PortalEnvironment,
    PortalPolicyMode,
    PortalSelectionRequest,
    PortalSelectionResult,
    VenueCapability,
    normalize_asset_class,
    normalize_symbol,
)


ALPACA_PAPER_EQUITIES = (
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "META",
    "GOOGL",
    "TSLA",
    "AMD",
    "JPM",
    "V",
    "MA",
    "UNH",
    "HD",
    "COST",
    "AVGO",
    "CRM",
    "NFLX",
    "XOM",
    "JNJ",
    "PG",
    "KO",
    "PEP",
    "WMT",
)
ALPACA_PAPER_ETFS = ("SPY", "QQQ", "DIA", "IWM", "XLK", "XLF", "XLE", "XLV", "XLY")
ALPACA_PAPER_CRYPTO = ("BTC/USD", "ETH/USD", "SOL/USD")
KRAKEN_CRYPTO = ("BTC/USD", "ETH/USD", "SOL/USD")


@dataclass(frozen=True)
class VenueCapabilityRegistry:
    capabilities: tuple[VenueCapability, ...]

    def configured_portals(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(cap.portal_key for cap in self.capabilities))

    def usable_portals(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(cap.portal_key for cap in self.capabilities if cap.enabled and not cap.live_blocked))

    def capabilities_for_symbol(self, symbol: str, *, environment: str | None = None) -> tuple[VenueCapability, ...]:
        return tuple(
            cap
            for cap in self.capabilities
            if cap.matches_symbol(symbol) and (environment is None or cap.environment == environment)
        )

    def capabilities_for_asset_class(self, asset_class: str, *, environment: str | None = None) -> tuple[VenueCapability, ...]:
        return tuple(
            cap
            for cap in self.capabilities
            if cap.matches_asset_class(asset_class) and (environment is None or cap.environment == environment)
        )

    def resolve(self, request: PortalSelectionRequest) -> PortalSelectionResult:
        candidates = self.capabilities_for_symbol(request.symbol, environment=request.environment)
        if request.asset_class is not None:
            candidates = tuple(cap for cap in candidates if cap.matches_asset_class(request.asset_class))

        usable: list[VenueCapability] = []
        rejected: dict[str, tuple[str, ...]] = {}
        for cap in candidates:
            ok, reasons = cap.supports_request(request)
            if ok:
                usable.append(cap)
            else:
                rejected[cap.capability_key] = reasons

        mode = PortalPolicyMode(request.policy_mode)
        if mode == PortalPolicyMode.FAIL_CLOSED:
            reasons = ("FAIL_CLOSED_POLICY",) if usable else ("NO_USABLE_PORTAL",)
            return PortalSelectionResult(None, tuple(candidates), rejected, "blocked", reasons)

        if mode == PortalPolicyMode.EXPLICIT_PREFERRED_VENUE:
            preferred = normalize_symbol(request.preferred_venue or "")
            preferred_matches = [
                cap
                for cap in usable
                if normalize_symbol(cap.venue_id) == preferred
                or normalize_symbol(cap.portal_key) == preferred
                or normalize_symbol(cap.portal_name) == preferred
            ]
            if len(preferred_matches) == 1:
                return PortalSelectionResult(preferred_matches[0], tuple(candidates), rejected, "selected", ())
            if not request.allow_fallback:
                return PortalSelectionResult(None, tuple(candidates), rejected, "blocked", ("PREFERRED_PORTAL_UNSUPPORTED",))
            usable = [cap for cap in usable if cap not in preferred_matches]

        if len(usable) == 1:
            return PortalSelectionResult(usable[0], tuple(candidates), rejected, "selected", ())
        if len(usable) > 1:
            return PortalSelectionResult(None, tuple(candidates), rejected, "blocked", ("AMBIGUOUS_PORTAL",))
        return PortalSelectionResult(None, tuple(candidates), rejected, "blocked", ("NO_USABLE_PORTAL",))

    def build_candidate_identities(
        self,
        *,
        symbols: Iterable[str],
        active_markets: Iterable[str],
        environment: str = PortalEnvironment.PAPER.value,
        discovery_mode: str = "active_markets",
    ) -> tuple[CapabilityAwareCandidate, ...]:
        active = {normalize_asset_class(market) for market in active_markets}
        requested_symbols = {normalize_symbol(symbol) for symbol in symbols}
        identities: list[CapabilityAwareCandidate] = []
        capability_source = (
            self.capabilities
            if discovery_mode == "registry"
            else tuple(cap for symbol in symbols for cap in self.capabilities_for_symbol(symbol, environment=environment))
        )
        seen: set[str] = set()
        for cap in capability_source:
            if cap.environment != environment:
                continue
            if cap.normalized_symbol != "*" and cap.normalized_symbol not in requested_symbols:
                continue
            if cap.asset_class not in active and not (
                cap.asset_class == PortalAssetClass.US_EQUITY.value and PortalAssetClass.EQUITY.value in active
            ):
                continue
            if cap.capability_key in seen:
                continue
            seen.add(cap.capability_key)
            request = PortalSelectionRequest(
                symbol=cap.symbol,
                asset_class=cap.asset_class,
                environment=environment,
                policy_mode=PortalPolicyMode.CAPABILITY_FIRST.value,
                order_type=cap.default_order_type or "limit",
                time_in_force=cap.default_time_in_force,
            )
            ok, reasons = cap.supports_request(request)
            identities.append(CapabilityAwareCandidate.from_capability(cap, tradable=ok, reasons=reasons))
        return tuple(identities)


def _alpaca_equity_capability(symbol: str, *, asset_class: str, etf_capable: bool = False) -> VenueCapability:
    return VenueCapability(
        venue_id="alpaca",
        portal_name="alpaca_paper",
        environment=PortalEnvironment.PAPER.value,
        asset_class=asset_class,
        symbol=symbol,
        normalized_symbol=normalize_symbol(symbol),
        venue_symbol_format=symbol,
        quote_source="alpaca_data_latest_quote",
        market_data_available=True,
        tradability_source="static_capability_fixture",
        supported_order_types=frozenset({"limit"}),
        supported_time_in_force=frozenset({"DAY"}),
        default_order_type="limit",
        default_time_in_force="DAY",
        fractional_support=True,
        min_notional=Decimal("1.00"),
        min_quantity=None,
        quantity_step=Decimal("0.000001"),
        market_session_status_source="alpaca_paper_clock",
        execution_adapter="alpaca_paper_rest",
        reconciliation_adapter="alpaca_paper_rest_reconciliation",
        read_only=True,
        paper_mutation=True,
        sandbox_mutation=False,
        live_mutation=False,
        live_blocked=True,
        credential_status=CredentialStatus.CONFIGURED.value,
        order_constraint_source="alpaca_equity_order_constraints",
        metadata={"etf_capable": etf_capable},
    )


def _alpaca_crypto_capability(symbol: str) -> VenueCapability:
    return VenueCapability(
        venue_id="alpaca",
        portal_name="alpaca_paper",
        environment=PortalEnvironment.PAPER.value,
        asset_class=PortalAssetClass.CRYPTO.value,
        symbol=symbol,
        normalized_symbol=normalize_symbol(symbol),
        venue_symbol_format=symbol,
        quote_source="alpaca_data_crypto_latest_quote",
        market_data_available=True,
        tradability_source="static_capability_fixture",
        supported_order_types=frozenset({"limit"}),
        supported_actions=frozenset({"buy", "sell_to_close"}),
        supported_time_in_force=frozenset({"GTC", "IOC"}),
        default_order_type="limit",
        default_time_in_force="GTC",
        fractional_support=True,
        min_notional=Decimal("10.00"),
        min_quantity=None,
        quantity_step=None,
        market_session_status_source="alpaca_crypto_clock",
        execution_adapter="alpaca_paper_rest",
        reconciliation_adapter="alpaca_paper_rest_reconciliation",
        read_only=True,
        paper_mutation=True,
        sandbox_mutation=False,
        live_mutation=False,
        live_blocked=True,
        credential_status=CredentialStatus.CONFIGURED.value,
        order_constraint_source="alpaca_crypto_orders_support_gtc_ioc_not_day",
    )


def _kraken_crypto_capability(symbol: str) -> VenueCapability:
    venue_symbol = symbol.replace("/", "")
    if symbol == "BTC/USD":
        venue_symbol = "XBTUSD"
    return VenueCapability(
        venue_id="kraken",
        portal_name="kraken_paper",
        environment=PortalEnvironment.PAPER.value,
        asset_class=PortalAssetClass.CRYPTO.value,
        symbol=symbol,
        normalized_symbol=normalize_symbol(symbol),
        venue_symbol_format=venue_symbol,
        quote_source="kraken_websocket_or_polling",
        market_data_available=True,
        tradability_source="instrument_registry",
        supported_order_types=frozenset({"limit", "market"}),
        supported_time_in_force=frozenset({"DAY", "GTC", "IOC"}),
        default_order_type="limit",
        default_time_in_force="GTC",
        fractional_support=True,
        min_notional=Decimal("10.00"),
        min_quantity=None,
        quantity_step=None,
        market_session_status_source="crypto_24_7",
        execution_adapter="sovereign_paper_broker",
        reconciliation_adapter="sovereign_paper_broker_snapshot",
        read_only=True,
        paper_mutation=True,
        sandbox_mutation=False,
        live_mutation=False,
        live_blocked=True,
        credential_status=CredentialStatus.CONFIGURED.value,
    )


def _disabled_placeholder(venue_id: str, reason: str) -> VenueCapability:
    return VenueCapability(
        venue_id=venue_id,
        portal_name=f"{venue_id}_disabled",
        environment=PortalEnvironment.PAPER.value,
        asset_class=PortalAssetClass.UNKNOWN.value,
        symbol="*",
        normalized_symbol="*",
        venue_symbol_format="UNKNOWN",
        quote_source="unconfigured",
        market_data_available=False,
        tradability_source="unconfigured",
        supported_order_types=frozenset(),
        supported_time_in_force=frozenset(),
        default_order_type=None,
        default_time_in_force=None,
        fractional_support=False,
        min_notional=None,
        min_quantity=None,
        quantity_step=None,
        market_session_status_source="unconfigured",
        execution_adapter="missing",
        reconciliation_adapter="missing",
        read_only=False,
        paper_mutation=False,
        sandbox_mutation=False,
        live_mutation=False,
        live_blocked=True,
        supported_actions=frozenset(),
        credential_status=(
            CredentialStatus.MISSING.value if reason == "CREDENTIALS_MISSING" else CredentialStatus.UNKNOWN.value
        ),
        enabled=False,
        disabled_reason=reason,
        unavailable_reason=reason,
        fail_closed_reason_code=reason,
    )


def _live_blocked_placeholder() -> VenueCapability:
    return VenueCapability(
        venue_id="alpaca",
        portal_name="alpaca_live_blocked",
        environment=PortalEnvironment.LIVE.value,
        asset_class=PortalAssetClass.UNKNOWN.value,
        symbol="*",
        normalized_symbol="*",
        venue_symbol_format="UNKNOWN",
        quote_source="live_blocked",
        market_data_available=False,
        tradability_source="live_blocked",
        supported_order_types=frozenset(),
        supported_time_in_force=frozenset(),
        default_order_type=None,
        default_time_in_force=None,
        fractional_support=False,
        min_notional=None,
        min_quantity=None,
        quantity_step=None,
        market_session_status_source="live_blocked",
        execution_adapter="live_blocked",
        reconciliation_adapter="live_blocked",
        read_only=False,
        paper_mutation=False,
        sandbox_mutation=False,
        live_mutation=False,
        live_blocked=True,
        supported_actions=frozenset(),
        credential_status=CredentialStatus.MISSING.value,
        enabled=False,
        disabled_reason="LIVE_BLOCKED",
        unavailable_reason="LIVE_BLOCKED",
        fail_closed_reason_code="LIVE_BLOCKED",
    )


def build_default_capability_registry() -> VenueCapabilityRegistry:
    capabilities: list[VenueCapability] = []
    capabilities.extend(_kraken_crypto_capability(symbol) for symbol in KRAKEN_CRYPTO)
    capabilities.extend(
        _alpaca_equity_capability(symbol, asset_class=PortalAssetClass.EQUITY.value)
        for symbol in ALPACA_PAPER_EQUITIES
    )
    capabilities.extend(
        _alpaca_equity_capability(symbol, asset_class=PortalAssetClass.ETF.value, etf_capable=True)
        for symbol in ALPACA_PAPER_ETFS
    )
    capabilities.extend(_alpaca_crypto_capability(symbol) for symbol in ALPACA_PAPER_CRYPTO)
    capabilities.append(_live_blocked_placeholder())
    for venue_id, reason in (
        ("coinbase", "ADAPTER_MISSING"),
        ("interactive_brokers", "CREDENTIALS_MISSING"),
        ("schwab", "NOT_CONFIGURED"),
        ("tradier", "CAPABILITY_UNPROVEN"),
        ("binance_us", "ADAPTER_MISSING"),
    ):
        capabilities.append(_disabled_placeholder(venue_id, reason))
    return VenueCapabilityRegistry(tuple(capabilities))
