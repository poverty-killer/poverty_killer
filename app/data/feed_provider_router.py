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


class FeedProviderLane(str, Enum):
    CRYPTO_MARKET_DATA = "crypto_market_data"
    EQUITY_ETF_MARKET_DATA = "equity_etf_market_data"
    OPTIONS_MARKET_DATA = "options_market_data"
    REFERENCE_MARKET_DATA = "reference_market_data"
    EVENT_NEWS_ADVISORY = "event_news_advisory"


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
        "MISSING_TRANSPORT",
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
    provider_lane: str
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
    coverage_scope: str
    public_no_signup: bool = False
    jurisdiction_flag: str | None = None
    transport_adapter: str | None = None
    signup_or_entitlement: str | None = None
    provider_health: str = FeedProviderHealth.UNKNOWN.value
    last_error: str | None = None
    reason_codes: tuple[str, ...] = ()
    execution_location: str | None = None
    transport_mode: str | None = None

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
            "provider_lane": self.provider_lane,
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
            "coverage_scope": self.coverage_scope,
            "public_no_signup": self.public_no_signup,
            "jurisdiction_flag": self.jurisdiction_flag,
            "transport_adapter": self.transport_adapter,
            "signup_or_entitlement": self.signup_or_entitlement,
            "provider_health": self.provider_health,
            "last_error": self.last_error,
            "reason_codes": self.reason_codes,
            "execution_location": self.execution_location,
            "transport_mode": self.transport_mode,
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
    provider_lane: str | None = None
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
            "provider_lane": self.request.provider_lane,
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
        self._configured_provider_ids = tuple(configured_provider_ids or ())
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

        if not self._configured_provider_ids:
            result = FeedSelectionResult(
                selected_provider=None,
                request=request,
                status="FAILED_CLOSED",
                reason="MISSING_MARKET_DATA_PROVIDER_CONFIG",
                fallback_path=(),
                skipped={},
            )
            self._last_selection = result
            return result

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
            reason = self._missing_truth_reason(request, skipped)
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
        if request.provider_lane and provider.provider_lane != request.provider_lane:
            reasons.append("UNSUPPORTED_PROVIDER_LANE")
        if provider.auth_required and provider.credentials_present is not True:
            reasons.append("MISSING_CREDENTIALS")
        for descriptor_reason in provider.reason_codes:
            if descriptor_reason in PROVIDER_FAILURE_REASON_CODES:
                reasons.append(descriptor_reason)
        if request.execution_required:
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

    def _missing_truth_reason(
        self,
        request: FeedProviderRequest,
        skipped: Mapping[str, tuple[str, ...]],
    ) -> str:
        lane = request.provider_lane or _lane_for_asset_and_capability(request.asset_class, request.required_data_type)
        all_reasons = tuple(reason for reasons in skipped.values() for reason in reasons)
        if "MISSING_ENTITLEMENT" in all_reasons:
            return "MISSING_ENTITLEMENT"
        if "MISSING_TRANSPORT" in all_reasons or "TRANSPORT_ADAPTER_NOT_IMPLEMENTED" in all_reasons:
            if lane == FeedProviderLane.OPTIONS_MARKET_DATA.value:
                return "MISSING_OPTIONS_FEED_TRUTH"
            if lane == FeedProviderLane.EQUITY_ETF_MARKET_DATA.value:
                return "MISSING_EQUITY_MARKET_DATA_TRUTH"
            return "MISSING_MARKET_TRUTH"
        if lane == FeedProviderLane.OPTIONS_MARKET_DATA.value:
            return "MISSING_OPTIONS_FEED_TRUTH"
        if lane == FeedProviderLane.EQUITY_ETF_MARKET_DATA.value:
            return "MISSING_EQUITY_MARKET_DATA_TRUTH"
        return "MISSING_MARKET_TRUTH"

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
            provider_id="alpaca_crypto_stream",
            provider_type=FeedProviderType.EXECUTABLE_MARKET_DATA.value,
            provider_lane=FeedProviderLane.CRYPTO_MARKET_DATA.value,
            asset_classes=("crypto",),
            data_capabilities=("trades", "order_book", "ticker", "candles"),
            auth_required=True,
            credentials_present=alpaca_creds_present,
            rate_limit_policy="alpaca_account_market_data_limits_respected",
            freshness_policy={"quote_stale_seconds": 10, "order_book_stale_seconds": 10, "candle_stale_seconds": 60},
            quality_checks=("execution_location_required", "timestamp_required", "crossed_book_reject"),
            execution_eligible=True,
            advisory_only=False,
            priority=1,
            coverage_scope="alpaca_crypto_us_realtime_stream",
            signup_or_entitlement="alpaca_credentials_and_stream_entitlement_required",
            transport_adapter="alpaca_crypto_websocket",
            execution_location="alpaca",
            transport_mode="stream",
        ),
        FeedProviderDescriptor(
            provider_id="alpaca_crypto_rest",
            provider_type=FeedProviderType.EXECUTABLE_MARKET_DATA.value,
            provider_lane=FeedProviderLane.CRYPTO_MARKET_DATA.value,
            asset_classes=("crypto",),
            data_capabilities=("trades", "order_book", "ticker", "candles"),
            auth_required=True,
            credentials_present=alpaca_creds_present,
            rate_limit_policy="alpaca_account_market_data_limits_respected",
            freshness_policy={"quote_stale_seconds": 10, "order_book_stale_seconds": 10, "candle_stale_seconds": 60},
            quality_checks=("execution_location_required", "timestamp_required", "crossed_book_reject"),
            execution_eligible=True,
            advisory_only=False,
            priority=2,
            coverage_scope="alpaca_crypto_us_batched_rest",
            signup_or_entitlement="alpaca_credentials_and_data_entitlement_required",
            transport_adapter="alpaca_crypto_rest",
            execution_location="alpaca",
            transport_mode="rest",
        ),
        FeedProviderDescriptor(
            provider_id="kraken_public",
            provider_type=FeedProviderType.REFERENCE_MARKET_DATA.value,
            provider_lane=FeedProviderLane.CRYPTO_MARKET_DATA.value,
            asset_classes=("crypto",),
            data_capabilities=("trades", "order_book", "ticker", "candles"),
            auth_required=False,
            credentials_present=None,
            rate_limit_policy="public_exchange_limits_respected",
            freshness_policy={"order_book_stale_seconds": 10, "candle_stale_seconds": 60},
            quality_checks=("crossed_book_reject", "duplicate_candle_dedupe", "timestamp_required"),
            execution_eligible=False,
            advisory_only=True,
            priority=10,
            coverage_scope="cross_venue_crypto_basis_and_resilience_advisory",
            public_no_signup=True,
            transport_adapter="kraken_public_ws_rest",
            provider_health=FeedProviderHealth.UNKNOWN.value,
            execution_location="kraken",
            transport_mode="stream_and_rest",
        ),
        FeedProviderDescriptor(
            provider_id="coinbase_public",
            provider_type=FeedProviderType.REFERENCE_MARKET_DATA.value,
            provider_lane=FeedProviderLane.CRYPTO_MARKET_DATA.value,
            asset_classes=("crypto",),
            data_capabilities=("order_book", "candles"),
            auth_required=False,
            credentials_present=None,
            rate_limit_policy="coinbase_exchange_public_market_data_limits_respected",
            freshness_policy={"order_book_stale_seconds": 10, "candle_stale_seconds": 60},
            quality_checks=("crossed_book_reject", "duplicate_candle_dedupe", "timestamp_required"),
            execution_eligible=False,
            advisory_only=True,
            priority=20,
            coverage_scope="cross_venue_crypto_basis_advisory_rest",
            public_no_signup=True,
            transport_adapter="coinbase_exchange_public_rest",
            provider_health=FeedProviderHealth.UNKNOWN.value,
            execution_location="coinbase",
            transport_mode="rest",
        ),
        FeedProviderDescriptor(
            provider_id="binance_us_public",
            provider_type=FeedProviderType.EXECUTABLE_MARKET_DATA.value,
            provider_lane=FeedProviderLane.CRYPTO_MARKET_DATA.value,
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
            coverage_scope="public_us_crypto_spot_market_data_candidate",
            public_no_signup=True,
            jurisdiction_flag="US_PUBLIC_CRYPTO_MARKET_DATA",
            transport_adapter="not_implemented",
            provider_health=FeedProviderHealth.UNKNOWN.value,
            reason_codes=("MISSING_TRANSPORT",),
        ),
        FeedProviderDescriptor(
            provider_id="coingecko_reference",
            provider_type=FeedProviderType.REFERENCE_MARKET_DATA.value,
            provider_lane=FeedProviderLane.REFERENCE_MARKET_DATA.value,
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
            coverage_scope="reference_price_metadata_only",
            public_no_signup=True,
            transport_adapter="not_implemented",
        ),
        FeedProviderDescriptor(
            provider_id="coinmarketcap_reference",
            provider_type=FeedProviderType.REFERENCE_MARKET_DATA.value,
            provider_lane=FeedProviderLane.REFERENCE_MARKET_DATA.value,
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
            coverage_scope="reference_price_metadata_only",
            signup_or_entitlement="api_key_required",
            transport_adapter="not_implemented",
        ),
        FeedProviderDescriptor(
            provider_id="alpaca_market_data",
            provider_type=FeedProviderType.EXECUTABLE_MARKET_DATA.value,
            provider_lane=FeedProviderLane.EQUITY_ETF_MARKET_DATA.value,
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
            coverage_scope="alpaca_market_data_entitlement_unknown",
            signup_or_entitlement="alpaca_market_data_entitlement_required",
            transport_adapter="not_implemented",
            reason_codes=("MISSING_ENTITLEMENT", "MISSING_TRANSPORT"),
        ),
        FeedProviderDescriptor(
            provider_id="alpaca_iex_limited",
            provider_type=FeedProviderType.EXECUTABLE_MARKET_DATA.value,
            provider_lane=FeedProviderLane.EQUITY_ETF_MARKET_DATA.value,
            asset_classes=("equity", "etf"),
            data_capabilities=("trades", "ticker", "candles"),
            auth_required=True,
            credentials_present=alpaca_creds_present,
            rate_limit_policy="alpaca_iex_limited_entitlement_required",
            freshness_policy={"quote_stale_seconds": 10, "candle_stale_seconds": 60},
            quality_checks=("limited_iex_coverage_label", "stale_quote_reject"),
            execution_eligible=False,
            advisory_only=False,
            priority=55,
            coverage_scope="limited_iex_not_full_sip",
            signup_or_entitlement="alpaca_iex_or_market_data_entitlement_required",
            transport_adapter="not_implemented",
            reason_codes=("MISSING_ENTITLEMENT", "MISSING_TRANSPORT"),
        ),
        FeedProviderDescriptor(
            provider_id="tiingo_optional",
            provider_type=FeedProviderType.EXECUTABLE_MARKET_DATA.value,
            provider_lane=FeedProviderLane.EQUITY_ETF_MARKET_DATA.value,
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
            coverage_scope="credentialed_equity_reference_or_delayed_candidate",
            signup_or_entitlement="api_key_required",
            transport_adapter="not_implemented",
            reason_codes=("MISSING_TRANSPORT",),
        ),
        FeedProviderDescriptor(
            provider_id="polygon_or_massive_optional",
            provider_type=FeedProviderType.EXECUTABLE_MARKET_DATA.value,
            provider_lane=FeedProviderLane.OPTIONS_MARKET_DATA.value,
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
            coverage_scope="credentialed_equity_options_market_data_candidate",
            signup_or_entitlement="api_key_or_entitlement_required",
            transport_adapter="not_implemented",
            reason_codes=("MISSING_TRANSPORT",),
        ),
        FeedProviderDescriptor(
            provider_id="sec_edgar",
            provider_type=FeedProviderType.PUBLIC_EVENT_ADVISORY.value,
            provider_lane=FeedProviderLane.EVENT_NEWS_ADVISORY.value,
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
            coverage_scope="official_public_filings_advisory_only",
            public_no_signup=True,
            transport_adapter="world_awareness_sec_edgar",
        ),
        FeedProviderDescriptor(
            provider_id="openinsider",
            provider_type=FeedProviderType.PUBLIC_EVENT_ADVISORY.value,
            provider_lane=FeedProviderLane.EVENT_NEWS_ADVISORY.value,
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
            coverage_scope="public_insider_activity_advisory_only",
            public_no_signup=True,
            transport_adapter="world_awareness_openinsider",
        ),
        FeedProviderDescriptor(
            provider_id="capitol_trades",
            provider_type=FeedProviderType.PUBLIC_EVENT_ADVISORY.value,
            provider_lane=FeedProviderLane.EVENT_NEWS_ADVISORY.value,
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
            coverage_scope="public_political_disclosure_advisory_only",
            public_no_signup=True,
            transport_adapter="world_awareness_capitol_trades",
        ),
        FeedProviderDescriptor(
            provider_id="official_company_press_releases",
            provider_type=FeedProviderType.PUBLIC_EVENT_ADVISORY.value,
            provider_lane=FeedProviderLane.EVENT_NEWS_ADVISORY.value,
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
            coverage_scope="official_issuer_release_advisory_only",
            public_no_signup=True,
            transport_adapter="world_awareness_official_releases",
        ),
        FeedProviderDescriptor(
            provider_id="official_calendars",
            provider_type=FeedProviderType.PUBLIC_EVENT_ADVISORY.value,
            provider_lane=FeedProviderLane.EVENT_NEWS_ADVISORY.value,
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
            coverage_scope="official_calendar_advisory_only",
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
            provider_lane=_lane_for_asset_and_capability(asset_class, required_data_type),
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


def _lane_for_asset_and_capability(asset_class: str, capability: str) -> str:
    normalized_asset = _normalize_asset_class(asset_class)
    normalized_capability = _normalize_capability(capability)
    if normalized_capability in {"reference_price", "metadata"}:
        return FeedProviderLane.REFERENCE_MARKET_DATA.value
    if normalized_capability in {"filings", "news/events"} or normalized_asset == "macro/events":
        return FeedProviderLane.EVENT_NEWS_ADVISORY.value
    if normalized_asset == "options":
        return FeedProviderLane.OPTIONS_MARKET_DATA.value
    if normalized_asset in {"equity", "etf"}:
        return FeedProviderLane.EQUITY_ETF_MARKET_DATA.value
    return FeedProviderLane.CRYPTO_MARKET_DATA.value
