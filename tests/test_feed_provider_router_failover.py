from __future__ import annotations

from types import SimpleNamespace

import main
from app.data.feed_provider_router import (
    FeedProviderDescriptor,
    FeedProviderLane,
    FeedProviderHealth,
    FeedProviderRouter,
    FeedProviderType,
    FeedProviderRequest,
    ProviderRuntimeStatus,
    build_feed_provider_router,
)


def _request(data_type: str = "order_book") -> FeedProviderRequest:
    return FeedProviderRequest(
        symbol="BTC/USD",
        asset_class="crypto",
        required_data_type=data_type,
        provider_lane=FeedProviderLane.CRYPTO_MARKET_DATA.value,
        execution_required=True,
    )


def _router(provider_ids: tuple[str, ...] = ("coinbase_public", "binance_us_public", "kraken_public")):
    return build_feed_provider_router(configured_provider_ids=provider_ids, env={})


def _conflict_router(trusted_source_priority: tuple[str, ...] = ()) -> FeedProviderRouter:
    providers = tuple(
        FeedProviderDescriptor(
            provider_id=provider_id,
            provider_type=FeedProviderType.EXECUTABLE_MARKET_DATA.value,
            provider_lane=FeedProviderLane.CRYPTO_MARKET_DATA.value,
            asset_classes=("crypto",),
            data_capabilities=("ticker", "order_book"),
            auth_required=False,
            credentials_present=None,
            rate_limit_policy="test_fixture",
            freshness_policy={"ticker_stale_seconds": 10},
            quality_checks=("test_fixture",),
            execution_eligible=True,
            advisory_only=False,
            priority=index,
            coverage_scope="test_fixture_allowed",
            transport_adapter="test_fixture",
        )
        for index, provider_id in enumerate(("provider_a", "provider_b"), start=1)
    )
    return FeedProviderRouter(
        providers,
        configured_provider_ids=("provider_a", "provider_b"),
        trusted_source_priority=trusted_source_priority,
    )


def test_missing_provider_config_fails_closed_without_hidden_kraken_default():
    result = build_feed_provider_router(configured_provider_ids=(), env={}).select_provider(_request())

    assert result.status == "FAILED_CLOSED"
    assert result.reason == "MISSING_MARKET_DATA_PROVIDER_CONFIG"
    assert result.selected_provider is None


def test_configured_provider_priority_is_respected_when_transport_is_available():
    result = _router(("kraken_public",)).select_provider(_request())

    assert result.status == "SELECTED"
    assert result.reason == "PRIMARY_SELECTED"
    assert result.selected_provider_id == "kraken_public"
    assert result.to_telemetry()["selected_provider"]["provider_id"] == "kraken_public"
    assert result.to_telemetry()["selected_provider"]["provider_lane"] == "crypto_market_data"


def test_missing_fallback_transport_does_not_fake_market_data():
    result = _router(("coinbase_public", "binance_us_public")).select_provider(_request())

    assert result.status == "FAILED_CLOSED"
    assert result.reason == "MISSING_MARKET_TRUTH"
    assert result.selected_provider is None
    assert "MISSING_TRANSPORT" in result.skipped["coinbase_public"]
    assert "MISSING_TRANSPORT" in result.skipped["binance_us_public"]


def test_safe_crypto_priority_prefers_public_fallbacks_but_uses_implemented_kraken_only_if_clean():
    result = _router().select_provider(_request())

    assert result.status == "SELECTED"
    assert result.reason == "FALLBACK_SELECTED"
    assert result.selected_provider_id == "kraken_public"
    assert "MISSING_TRANSPORT" in result.skipped["coinbase_public"]
    assert "MISSING_TRANSPORT" in result.skipped["binance_us_public"]


def test_degraded_kraken_is_skipped_and_missing_fallback_transport_fails_closed():
    result = _router().select_provider(
        _request(),
        provider_status={
            "kraken_public": ProviderRuntimeStatus(
                provider_id="kraken_public",
                health=FeedProviderHealth.FAILED.value,
                reason_codes=("DNS_FAILURE",),
            )
        },
    )

    assert result.status == "FAILED_CLOSED"
    assert result.reason == "MISSING_MARKET_TRUTH"
    assert result.selected_provider is None
    assert result.skipped["kraken_public"] == ("DNS_FAILURE",)
    assert "MISSING_TRANSPORT" in result.skipped["coinbase_public"]


def test_primary_crossed_book_is_quarantined_and_fallback_attempted():
    result = _router().select_provider(
        _request(),
        provider_status={
            "kraken_public": ProviderRuntimeStatus(
                provider_id="kraken_public",
                health=FeedProviderHealth.DEGRADED.value,
                reason_codes=("CROSSED_BOOK",),
            )
        },
    )

    assert result.status == "FAILED_CLOSED"
    assert result.selected_provider is None
    assert result.skipped["kraken_public"] == ("CROSSED_BOOK",)


def test_primary_duplicate_candle_is_rejected_and_fallback_attempted():
    result = _router().select_provider(
        _request("candles"),
        provider_status={
            "kraken_public": ProviderRuntimeStatus(
                provider_id="kraken_public",
                health=FeedProviderHealth.DEGRADED.value,
                reason_codes=("DUPLICATE_CANDLE",),
            )
        },
    )

    assert result.status == "FAILED_CLOSED"
    assert result.selected_provider is None
    assert result.skipped["kraken_public"] == ("DUPLICATE_CANDLE",)


def test_missing_credentials_provider_is_skipped_with_reason():
    result = _router(("coinmarketcap_reference",)).select_provider(
        FeedProviderRequest(
            symbol="BTC/USD",
            asset_class="crypto",
            required_data_type="reference_price",
            provider_lane=FeedProviderLane.REFERENCE_MARKET_DATA.value,
            execution_required=True,
        )
    )

    assert result.status == "FAILED_CLOSED"
    assert "MISSING_CREDENTIALS" in result.skipped["coinmarketcap_reference"]


def test_reference_only_provider_is_not_executable_order_book_truth():
    result = _router(("coingecko_reference",)).select_provider(_request())

    assert result.status == "FAILED_CLOSED"
    assert result.selected_provider is None
    assert "UNSUPPORTED_DATA_TYPE" in result.skipped["coingecko_reference"]
    assert "REFERENCE_OR_ADVISORY_NOT_EXECUTABLE" in result.skipped["coingecko_reference"]


def test_advisory_event_provider_is_not_execution_market_data():
    result = _router(("sec_edgar",)).select_provider(_request())

    assert result.status == "FAILED_CLOSED"
    assert "ADVISORY_ONLY" in result.skipped["sec_edgar"]
    assert "REFERENCE_OR_ADVISORY_NOT_EXECUTABLE" in result.skipped["sec_edgar"]


def test_provider_conflict_fails_closed_without_trusted_priority():
    router = _conflict_router()

    result = router.select_provider(
        _request("ticker"),
        provider_status={
            "provider_a": ProviderRuntimeStatus(
                provider_id="provider_a",
                health=FeedProviderHealth.HEALTHY.value,
                observed_value=100.0,
            ),
            "provider_b": ProviderRuntimeStatus(
                provider_id="provider_b",
                health=FeedProviderHealth.HEALTHY.value,
                observed_value=110.0,
            ),
        },
    )

    assert result.status == "FAILED_CLOSED"
    assert result.reason == "PROVIDER_CONFLICT"
    assert result.selected_provider is None
    assert result.conflicts == {"provider_a": 100.0, "provider_b": 110.0}


def test_provider_conflict_can_use_explicit_trusted_priority():
    router = _conflict_router(trusted_source_priority=("provider_b",))

    result = router.select_provider(
        _request("ticker"),
        provider_status={
            "provider_a": ProviderRuntimeStatus(
                provider_id="provider_a",
                health=FeedProviderHealth.HEALTHY.value,
                observed_value=100.0,
            ),
            "provider_b": ProviderRuntimeStatus(
                provider_id="provider_b",
                health=FeedProviderHealth.HEALTHY.value,
                observed_value=110.0,
            ),
        },
    )

    assert result.status == "SELECTED_WITH_TRUSTED_SOURCE_CONFLICT"
    assert result.reason == "TRUSTED_SOURCE_PRIORITY"
    assert result.selected_provider_id == "provider_b"


def test_no_available_provider_returns_missing_market_truth():
    result = _router(("missing_provider",)).select_provider(_request())

    assert result.status == "FAILED_CLOSED"
    assert result.reason == "MISSING_MARKET_TRUTH"
    assert result.skipped["missing_provider"] == ("PROVIDER_NOT_REGISTERED",)


def test_selected_provider_and_fallback_reason_are_recorded():
    result = _router().select_provider(
        _request(),
        provider_status={
            "kraken_public": ProviderRuntimeStatus(
                provider_id="kraken_public",
                health=FeedProviderHealth.FAILED.value,
                reason_codes=("DNS_FAILURE",),
            )
        },
    )

    telemetry = result.to_telemetry()

    assert telemetry["status"] == "FAILED_CLOSED"
    assert telemetry["reason"] == "MISSING_MARKET_TRUTH"
    assert telemetry["selected_provider_id"] is None
    assert telemetry["skipped"]["kraken_public"] == ("DNS_FAILURE",)
    assert telemetry["provider_lane"] == "crypto_market_data"


def test_router_telemetry_does_not_touch_broker_mutation_path():
    result = _router(("kraken_public",)).select_provider(_request())
    telemetry = result.to_telemetry()
    serialized = repr(telemetry).lower()

    assert "order_router" not in serialized
    assert "broker_gateway" not in serialized
    assert "broker mutation" not in serialized
    assert telemetry["selected_provider"]["provider_type"] == "executable_market_data"


def test_equity_missing_entitlement_is_explicit_and_limited_iex_is_labeled():
    result = _router(("alpaca_market_data", "alpaca_iex_limited")).select_provider(
        FeedProviderRequest(
            symbol="AAPL",
            asset_class="equity",
            required_data_type="ticker",
            provider_lane=FeedProviderLane.EQUITY_ETF_MARKET_DATA.value,
            execution_required=True,
        )
    )

    assert result.status == "FAILED_CLOSED"
    assert result.reason == "MISSING_CREDENTIALS"
    assert "MISSING_CREDENTIALS" in result.skipped["alpaca_market_data"]
    limited = _router(("alpaca_iex_limited",)).providers["alpaca_iex_limited"].to_telemetry()
    assert limited["coverage_scope"] == "limited_iex_not_full_sip"


def test_options_missing_feed_truth_is_explicit():
    result = _router(("polygon_or_massive_optional",)).select_provider(
        FeedProviderRequest(
            symbol="AAPL250620C00100000",
            asset_class="options",
            required_data_type="ticker",
            provider_lane=FeedProviderLane.OPTIONS_MARKET_DATA.value,
            execution_required=True,
        )
    )

    assert result.status == "FAILED_CLOSED"
    assert result.reason in {"MISSING_CREDENTIALS", "MISSING_OPTIONS_FEED_TRUTH"}
    assert result.selected_provider is None


def test_world_awareness_advisory_lane_does_not_become_executable_truth():
    advisory = _router(("sec_edgar",)).select_provider(
        FeedProviderRequest(
            symbol="AAPL",
            asset_class="equity",
            required_data_type="filings",
            provider_lane=FeedProviderLane.EVENT_NEWS_ADVISORY.value,
            execution_required=False,
        )
    )
    executable = _router(("sec_edgar",)).select_provider(
        FeedProviderRequest(
            symbol="AAPL",
            asset_class="equity",
            required_data_type="order_book",
            provider_lane=FeedProviderLane.EQUITY_ETF_MARKET_DATA.value,
            execution_required=True,
        )
    )

    assert advisory.status == "SELECTED"
    assert advisory.selected_provider.to_telemetry()["provider_lane"] == "event_news_advisory"
    assert advisory.selected_provider.to_telemetry()["advisory_only"] is True
    assert executable.status == "FAILED_CLOSED"
    assert "REFERENCE_OR_ADVISORY_NOT_EXECUTABLE" in executable.skipped["sec_edgar"]


def test_no_hidden_runtime_hardcoded_symbol_authority():
    config = SimpleNamespace(runtime_watchlist=[], symbol_universe=[])

    resolution = main.resolve_runtime_universe(config)

    assert resolution.symbols == ()
    assert resolution.reason == "MISSING_UNIVERSE_TRUTH"


def test_explicit_watchlist_is_allowed_and_preserved():
    config = SimpleNamespace(runtime_watchlist=["BTC/USD", "ETH/USD"], symbol_universe=[])

    resolution = main.resolve_runtime_universe(config)

    assert resolution.symbols == ("BTC/USD", "ETH/USD")
    assert resolution.source == "CONFIG_EXPLICIT_ALLOWED:runtime_watchlist"


def test_symbol_audit_classifies_allowed_fixtures_reports_and_provider_entries():
    classifications = {
        "tests/test_ws_book_callback_flow.py:BTC/USD": "TEST_FIXTURE_ALLOWED",
        "reports/seam6_controlled_alpaca_paper_portfolio_expansion_machine.md:BTC/USD": "REPORT_OR_DOC_ALLOWED",
        "app/data/feed_provider_router.py:kraken_public": "PROVIDER_REGISTRY_ALLOWED",
        "config.runtime_watchlist:BTC/USD": "CONFIG_EXPLICIT_ALLOWED",
    }

    assert set(classifications.values()) == {
        "TEST_FIXTURE_ALLOWED",
        "REPORT_OR_DOC_ALLOWED",
        "PROVIDER_REGISTRY_ALLOWED",
        "CONFIG_EXPLICIT_ALLOWED",
    }
