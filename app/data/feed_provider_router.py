from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence


class FeedProviderType(str, Enum):
    EXECUTABLE_MARKET_DATA = "executable_market_data"
    REFERENCE_MARKET_DATA = "reference_market_data"
    PUBLIC_EVENT_ADVISORY = "public_event_advisory"
    NEWS_SENTIMENT_ADVISORY = "news_sentiment_advisory"


class FeedProviderHealth(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


EXECUTABLE_DATA_CAPABILITIES = frozenset(
    {
        "trades",
        "order_book",
        "ticker",
        "candles",
    }
)

PROVIDER_FAILURE_REASON_CODES = frozenset(
    {
        "DNS_FAILURE",
        "REST_UNAVAILABLE",
        "WEBSOCKET_UNAVAILABLE",
        "WEBSOCKET_STALE",
        "CANDLE_STALE",
        "ORDER_BOOK_STALE",
        "CROSSED_BOOK",
        "DUPLICATE_CANDLE",
        "MISSING_CREDENTIALS",
        "MISSING_ENTITLEMENT",
        "RATE_LIMITED",
        "UNSUPPORTED_ASSET",
        "UNSUPPORTED_DATA_TYPE",
        "PROVIDER_CONFLICT",
        "TRANSPORT_ADAPTER_NOT_IMPLEMENTED",
    }
)

FAILOVER_REASON_CODES = frozenset(
    {
        "DNS_FAILURE",
        "REST_UNAVAILABLE",
        "WEBSOCKET_UNAVAILABLE",
        "WEBSOCKET_STALE",
        "CANDLE_STALE",
        "ORDER_BOOK_STALE",
        "CROSSED_BOOK",
        "DUPLICATE_CANDLE",
        "RATE_LIMITED",
    }
)


@dataclass(frozen=True)
class FeedProviderDescriptor:
    provider_id: str
    provider_type: str
    asset_classes: tuple[str, ...]
    data_capabilities: tuple[str, ...]
    auth_required: bool
    credentials_present: bool | None
    rate_limit_policy: str
    freshness_policy: Mapping[str, Any]
    quality_checks: tuple[str, ...]
    execution_eligible: bool
    advisory_only: bool
    priority: int
    public_no_signup: bool = False
    jurisdiction_flag: str | None = None
    transport_adapter: str | None = None
    signup_or_entitlement: str | None = None
    provider_health: str = FeedProviderHealth.UNKNOWN.value
    last_error: str | None = None
    reason_codes: tuple[str, ...] = ()

    def supports_asset_class(self, asset_class: str) -> bool:
        requested = _normalize_asset_class(asset_class)
        return requested in self.asset_classes

    def supports_capability(self, capability: str) -> bool:
        return _normalize_capability(capability) in self.data_capabilities

    @property
    def credential_status(self) -> str:
        if not self.auth_required:
            return "not_applicable"
        if self.credentials_present is True:
            return "present"
        if self.credentials_present is False:
            return "missing"
        return "unknown"

    def to_telemetry(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "provider_type": self.provider_type,
            "asset_classes": self.asset_classes,
            "data_capabilities": self.data_capabilities,
            "auth_required": self.auth_required,
            "credentials_present": self.credentials_present,
            "credential_status": self.credential_status,
            "rate_limit_policy": self.rate_limit_policy,
            "freshness_policy": dict(self.freshness_policy),
            "quality_checks": self.quality_checks,
            "execution_eligible": self.execution_eligible,
            "advisory_only": self.advisory_only,
            "priority": self.priority,
            "public_no_signup": self.public_no_signup,
            "jurisdiction_flag": self.jurisdiction_flag,
            "transport_adapter": self.transport_adapter,
            "signup_or_entitlement": self.signup_or_entitlement,
            "provider_health": self.provider_health,
            "last_error": self.last_error,
            "reason_codes": self.reason_codes,
        }


@dataclass(frozen=True)
class ProviderRuntimeStatus:
    provider_id: str
    health: str = FeedProviderHealth.UNKNOWN.value
    reason_codes: tuple[str, ...] = ()
    freshness_ns: int | None = None
    quality_status: str | None = None
    last_error: str | None = None
    observed_value: float | None = None

    def failure_reasons(self) -> tuple[str, ...]:
        return tuple(code for code in self.reason_codes if code in PROVIDER_FAILURE_REASON_CODES)


@dataclass(frozen=True)
class FeedProviderRequest:
    symbol: str
    asset_class: str
    required_data_type: str
    execution_required: bool = True


@dataclass(frozen=True)
class FeedSelectionResult:
    selected_provider: FeedProviderDescriptor | None
    request: FeedProviderRequest
    status: str
    reason: str
    fallback_path: tuple[str, ...] = ()
    skipped: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    conflicts: Mapping[str, float] = field(default_factory=dict)

    @property
    def selected_provider_id(self) -> str | None:
        if self.selected_provider is None:
            return None
        return self.selected_provider.provider_id

    def to_telemetry(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "symbol": self.request.symbol,
            "asset_class": self.request.asset_class,
            "required_data_type": self.request.required_data_type,
            "execution_required": self.request.execution_required,
            "selected_provider": self.selected_provider.to_telemetry() if self.selected_provider else None,
            "selected_provider_id": self.selected_provider_id,
            "fallback_path": self.fallback_path,
            "skipped": {provider: tuple(reasons) for provider, reasons in self.skipped.items()},
            "conflicts": dict(self.conflicts),
        }


class FeedProviderRouter:
    def __init__(
        self,
        providers: Iterable[FeedProviderDescriptor],
        configured_provider_ids: Sequence[str] | None = None,
        trusted_source_priority: Sequence[str] | None = None,
        conflict_tolerance_bps: float = 50.0,
    ) -> None:
        self._providers = {provider.provider_id: provider for provider in providers}
        configured = tuple(configured_provider_ids or ())
        self._configured_provider_ids = configured or tuple(
            provider.provider_id
            for provider in sorted(self._providers.values(), key=lambda item: item.priority)
        )
        self._trusted_source_priority = tuple(trusted_source_priority or ())
        self._conflict_tolerance_bps = float(conflict_tolerance_bps)
        self._last_selection: FeedSelectionResult | None = None

    @property
    def providers(self) -> Mapping[str, FeedProviderDescriptor]:
        return dict(self._providers)

    @property
    def configured_provider_ids(self) -> tuple[str, ...]:
        return tuple(self._configured_provider_ids)

    @property
    def last_selection(self) -> FeedSelectionResult | None:
        return self._last_selection

    def select_provider(
        self,
        request: FeedProviderRequest,
        provider_status: Mapping[str, ProviderRuntimeStatus] | None = None,
    ) -> FeedSelectionResult:
        provider_status = provider_status or {}
        skipped: dict[str, tuple[str, ...]] = {}
        candidates: list[FeedProviderDescriptor] = []

        for provider_id in self._configured_provider_ids:
            provider = self._providers.get(provider_id)
            if provider is None:
                skipped[provider_id] = ("PROVIDER_NOT_REGISTERED",)
                continue

            reasons = self._filter_reasons(provider, request, provider_status.get(provider_id))
            if reasons:
                skipped[provider_id] = reasons
                continue
            candidates.append(provider)

        conflict_result = self._conflict_result(request, candidates, provider_status, skipped)
        if conflict_result is not None:
            self._last_selection = conflict_result
            return conflict_result

        if not candidates:
            reason = "MISSING_MARKET_TRUTH"
            if skipped and all("MISSING_CREDENTIALS" in reasons for reasons in skipped.values()):
                reason = "MISSING_CREDENTIALS"
            result = FeedSelectionResult(
                selected_provider=None,
                request=request,
                status="FAILED_CLOSED",
                reason=reason,
                fallback_path=(),
                skipped=skipped,
            )
            self._last_selection = result
            return result

        selected = candidates[0]
        result = FeedSelectionResult(
            selected_provider=selected,
            request=request,
            status="SELECTED",
            reason="PRIMARY_SELECTED" if selected.provider_id == self._configured_provider_ids[0] else "FALLBACK_SELECTED",
            fallback_path=tuple(provider.provider_id for provider in candidates),
            skipped=skipped,
        )
        self._last_selection = result
        return result

    def _filter_reasons(
        self,
        provider: FeedProviderDescriptor,
        request: FeedProviderRequest,
        status: ProviderRuntimeStatus | None,
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        if not provider.supports_asset_class(request.asset_class):
            reasons.append("UNSUPPORTED_ASSET")
        if not provider.supports_capability(request.required_data_type):
            reasons.append("UNSUPPORTED_DATA_TYPE")
        if provider.auth_required and provider.credentials_present is not True:
            reasons.append("MISSING_CREDENTIALS")
        if request.execution_required:
            required = _normalize_capability(request.required_data_type)
            if required in EXECUTABLE_DATA_CAPABILITIES:
                if provider.advisory_only:
                    reasons.append("ADVISORY_ONLY")
                if provider.provider_type != FeedProviderType.EXECUTABLE_MARKET_DATA.value:
                    reasons.append("REFERENCE_OR_ADVISORY_NOT_EXECUTABLE")
                if not provider.execution_eligible:
                    reasons.append("NOT_EXECUTION_ELIGIBLE")

        if status:
            runtime_reasons = status.failure_reasons()
            if status.health == FeedProviderHealth.FAILED.value:
                reasons.extend(runtime_reasons or ("PROVIDER_FAILED",))
            elif runtime_reasons:
                if any(reason in FAILOVER_REASON_CODES for reason in runtime_reasons):
                    reasons.extend(runtime_reasons)

        return tuple(dict.fromkeys(reasons))

    def _conflict_result(
        self,
        request: FeedProviderRequest,
        candidates: Sequence[FeedProviderDescriptor],
        provider_status: Mapping[str, ProviderRuntimeStatus],
        skipped: Mapping[str, tuple[str, ...]],
    ) -> FeedSelectionResult | None:
        observed = {
            provider.provider_id: provider_status[provider.provider_id].observed_value
            for provider in candidates
            if provider.provider_id in provider_status
            and provider_status[provider.provider_id].observed_value is not None
        }
        if len(observed) < 2:
            return None

        values = list(observed.values())
        low = min(values)
        high = max(values)
        if low <= 0:
            conflict_bps = float("inf")
        else:
            conflict_bps = ((high - low) / low) * 10_000.0
        if conflict_bps <= self._conflict_tolerance_bps:
            return None

        for trusted_provider_id in self._trusted_source_priority:
            trusted = next((provider for provider in candidates if provider.provider_id == trusted_provider_id), None)
            if trusted is not None:
                return FeedSelectionResult(
                    selected_provider=trusted,
                    request=request,
                    status="SELECTED_WITH_TRUSTED_SOURCE_CONFLICT",
                    reason="TRUSTED_SOURCE_PRIORITY",
                    fallback_path=tuple(provider.provider_id for provider in candidates),
                    skipped=skipped,
                    conflicts=observed,
                )

        return FeedSelectionResult(
            selected_provider=None,
            request=request,
            status="FAILED_CLOSED",
            reason="PROVIDER_CONFLICT",
            fallback_path=tuple(provider.provider_id for provider in candidates),
            skipped=skipped,
            conflicts=observed,
        )


def build_default_feed_provider_registry(env: Mapping[str, str] | None = None) -> tuple[FeedProviderDescriptor, ...]:
    env = env or {}
    alpaca_creds_present = bool(env.get("APCA_API_KEY_ID") and env.get("APCA_API_SECRET_KEY"))
    return (
        FeedProviderDescriptor(
            provider_id="kraken_public",
            provider_type=FeedProviderType.EXECUTABLE_MARKET_DATA.value,
            asset_classes=("crypto",),
            data_capabilities=("trades", "order_book", "ticker", "candles"),
            auth_required=False,
            credentials_present=None,
            rate_limit_policy="public_exchange_limits_respected",
            freshness_policy={"order_book_stale_seconds": 10, "candle_stale_seconds": 60},
            quality_checks=("crossed_book_reject", "duplicate_candle_dedupe", "timestamp_required"),
            execution_eligible=True,
            advisory_only=False,
            priority=10,
            public_no_signup=True,
            transport_adapter="kraken_public_ws_rest",
            provider_health=FeedProviderHealth.UNKNOWN.value,
        ),
        FeedProviderDescriptor(
            provider_id="coinbase_public",
            provider_type=FeedProviderType.EXECUTABLE_MARKET_DATA.value,
            asset_classes=("crypto",),
            data_capabilities=("trades", "order_book", "ticker", "candles"),
            auth_required=False,
            credentials_present=None,
            rate_limit_policy="public_market_data_terms_and_limits_required",
            freshness_policy={"order_book_stale_seconds": 10, "candle_stale_seconds": 60},
            quality_checks=("crossed_book_reject", "duplicate_candle_dedupe", "timestamp_required"),
            execution_eligible=True,
            advisory_only=False,
            priority=20,
            public_no_signup=True,
            transport_adapter="not_implemented",
            provider_health=FeedProviderHealth.UNKNOWN.value,
            reason_codes=("TRANSPORT_ADAPTER_NOT_IMPLEMENTED",),
        ),
        FeedProviderDescriptor(
            provider_id="binance_us_public",
            provider_type=FeedProviderType.EXECUTABLE_MARKET_DATA.value,
            asset_classes=("crypto",),
            data_capabilities=("trades", "order_book", "ticker", "candles"),
            auth_required=False,
            credentials_present=None,
            rate_limit_policy="public_market_data_limits_and_us_jurisdiction_review_required",
            freshness_policy={"order_book_stale_seconds": 10, "candle_stale_seconds": 60},
            quality_checks=("crossed_book_reject", "duplicate_candle_dedupe", "timestamp_required"),
            execution_eligible=True,
            advisory_only=False,
            priority=30,
            public_no_signup=True,
            jurisdiction_flag="US_PUBLIC_CRYPTO_MARKET_DATA",
            transport_adapter="not_implemented",
            provider_health=FeedProviderHealth.UNKNOWN.value,
            reason_codes=("TRANSPORT_ADAPTER_NOT_IMPLEMENTED",),
        ),
        FeedProviderDescriptor(
            provider_id="coingecko_reference",
            provider_type=FeedProviderType.REFERENCE_MARKET_DATA.value,
            asset_classes=("crypto",),
            data_capabilities=("reference_price", "ticker"),
            auth_required=False,
            credentials_present=None,
            rate_limit_policy="public_reference_limits_respected",
            freshness_policy={"reference_price_stale_seconds": 300},
            quality_checks=("reference_only",),
            execution_eligible=False,
            advisory_only=True,
            priority=100,
            public_no_signup=True,
            transport_adapter="not_implemented",
        ),
        FeedProviderDescriptor(
            provider_id="coinmarketcap_reference",
            provider_type=FeedProviderType.REFERENCE_MARKET_DATA.value,
            asset_classes=("crypto",),
            data_capabilities=("reference_price", "metadata"),
            auth_required=True,
            credentials_present=bool(env.get("COINMARKETCAP_API_KEY")),
            rate_limit_policy="credential_entitlement_required",
            freshness_policy={"reference_price_stale_seconds": 300},
            quality_checks=("reference_only",),
            execution_eligible=False,
            advisory_only=True,
            priority=110,
            signup_or_entitlement="api_key_required",
            transport_adapter="not_implemented",
        ),
        FeedProviderDescriptor(
            provider_id="alpaca_market_data",
            provider_type=FeedProviderType.EXECUTABLE_MARKET_DATA.value,
            asset_classes=("equity", "etf"),
            data_capabilities=("trades", "order_book", "ticker", "candles"),
            auth_required=True,
            credentials_present=alpaca_creds_present,
            rate_limit_policy="alpaca_market_data_entitlement_required",
            freshness_policy={"quote_stale_seconds": 10, "candle_stale_seconds": 60},
            quality_checks=("entitlement_check", "stale_quote_reject"),
            execution_eligible=True,
            advisory_only=False,
            priority=50,
            signup_or_entitlement="alpaca_market_data_entitlement_required",
            transport_adapter="not_implemented",
        ),
        FeedProviderDescriptor(
            provider_id="tiingo_optional",
            provider_type=FeedProviderType.EXECUTABLE_MARKET_DATA.value,
            asset_classes=("equity", "etf"),
            data_capabilities=("ticker", "candles"),
            auth_required=True,
            credentials_present=bool(env.get("TIINGO_API_KEY")),
            rate_limit_policy="credential_entitlement_required",
            freshness_policy={"quote_stale_seconds": 60},
            quality_checks=("entitlement_check", "stale_quote_reject"),
            execution_eligible=False,
            advisory_only=False,
            priority=90,
            signup_or_entitlement="api_key_required",
            transport_adapter="not_implemented",
        ),
        FeedProviderDescriptor(
            provider_id="polygon_or_massive_optional",
            provider_type=FeedProviderType.EXECUTABLE_MARKET_DATA.value,
            asset_classes=("equity", "etf", "options"),
            data_capabilities=("trades", "order_book", "ticker", "candles"),
            auth_required=True,
            credentials_present=bool(env.get("POLYGON_API_KEY") or env.get("MASSIVE_API_KEY")),
            rate_limit_policy="credential_entitlement_required",
            freshness_policy={"quote_stale_seconds": 10},
            quality_checks=("entitlement_check", "stale_quote_reject"),
            execution_eligible=False,
            advisory_only=False,
            priority=95,
            signup_or_entitlement="api_key_or_entitlement_required",
            transport_adapter="not_implemented",
        ),
        FeedProviderDescriptor(
            provider_id="sec_edgar",
            provider_type=FeedProviderType.PUBLIC_EVENT_ADVISORY.value,
            asset_classes=("equity", "etf", "macro/events"),
            data_capabilities=("filings", "news/events"),
            auth_required=False,
            credentials_present=None,
            rate_limit_policy="sec_fair_access_user_agent_required",
            freshness_policy={"event_stale_seconds": 86_400},
            quality_checks=("official_source", "advisory_only"),
            execution_eligible=False,
            advisory_only=True,
            priority=200,
            public_no_signup=True,
            transport_adapter="world_awareness_sec_edgar",
        ),
        FeedProviderDescriptor(
            provider_id="openinsider",
            provider_type=FeedProviderType.PUBLIC_EVENT_ADVISORY.value,
            asset_classes=("equity",),
            data_capabilities=("news/events",),
            auth_required=False,
            credentials_present=None,
            rate_limit_policy="terms_review_and_respectful_rate_limit_required",
            freshness_policy={"event_stale_seconds": 86_400},
            quality_checks=("advisory_only",),
            execution_eligible=False,
            advisory_only=True,
            priority=210,
            public_no_signup=True,
            transport_adapter="world_awareness_openinsider",
        ),
        FeedProviderDescriptor(
            provider_id="capitol_trades",
            provider_type=FeedProviderType.PUBLIC_EVENT_ADVISORY.value,
            asset_classes=("equity", "macro/events"),
            data_capabilities=("news/events",),
            auth_required=False,
            credentials_present=None,
            rate_limit_policy="terms_review_and_respectful_rate_limit_required",
            freshness_policy={"event_stale_seconds": 86_400},
            quality_checks=("advisory_only",),
            execution_eligible=False,
            advisory_only=True,
            priority=220,
            public_no_signup=True,
            transport_adapter="world_awareness_capitol_trades",
        ),
        FeedProviderDescriptor(
            provider_id="official_company_press_releases",
            provider_type=FeedProviderType.PUBLIC_EVENT_ADVISORY.value,
            asset_classes=("equity",),
            data_capabilities=("news/events",),
            auth_required=False,
            credentials_present=None,
            rate_limit_policy="official_public_pages_respectful_rate_limit_required",
            freshness_policy={"event_stale_seconds": 86_400},
            quality_checks=("official_source", "advisory_only"),
            execution_eligible=False,
            advisory_only=True,
            priority=230,
            public_no_signup=True,
            transport_adapter="world_awareness_official_releases",
        ),
        FeedProviderDescriptor(
            provider_id="official_calendars",
            provider_type=FeedProviderType.PUBLIC_EVENT_ADVISORY.value,
            asset_classes=("macro/events", "equity"),
            data_capabilities=("news/events",),
            auth_required=False,
            credentials_present=None,
            rate_limit_policy="official_public_pages_respectful_rate_limit_required",
            freshness_policy={"event_stale_seconds": 86_400},
            quality_checks=("official_source", "advisory_only"),
            execution_eligible=False,
            advisory_only=True,
            priority=240,
            public_no_signup=True,
            transport_adapter="world_awareness_official_calendars",
        ),
    )


def build_feed_provider_router(
    configured_provider_ids: Sequence[str] | None = None,
    trusted_source_priority: Sequence[str] | None = None,
    env: Mapping[str, str] | None = None,
) -> FeedProviderRouter:
    return FeedProviderRouter(
        build_default_feed_provider_registry(env=env),
        configured_provider_ids=configured_provider_ids,
        trusted_source_priority=trusted_source_priority,
    )


def select_configured_market_data_provider(
    *,
    symbol: str,
    asset_class: str,
    required_data_type: str,
    configured_provider_ids: Sequence[str],
    env: Mapping[str, str] | None = None,
) -> FeedSelectionResult:
    router = build_feed_provider_router(configured_provider_ids=configured_provider_ids, env=env)
    return router.select_provider(
        FeedProviderRequest(
            symbol=symbol,
            asset_class=asset_class,
            required_data_type=required_data_type,
            execution_required=True,
        )
    )


def _normalize_asset_class(asset_class: str) -> str:
    normalized = str(asset_class or "").strip().lower()
    if normalized in {"stock", "us_equity"}:
        return "equity"
    if normalized == "fund":
        return "etf"
    return normalized


def _normalize_capability(capability: str) -> str:
    normalized = str(capability or "").strip().lower()
    aliases = {
        "book": "order_book",
        "depth": "order_book",
        "ohlc": "candles",
        "candle": "candles",
        "quote": "ticker",
        "events": "news/events",
        "news": "news/events",
    }
    return aliases.get(normalized, normalized)
