from __future__ import annotations

from app.data.feed_provider_router import (
    FeedProviderHealth,
    FeedProviderRequest,
    ProviderRuntimeStatus,
    build_feed_provider_router,
)


def _request(data_type: str = "order_book") -> FeedProviderRequest:
    return FeedProviderRequest(
        symbol="BTC/USD",
        asset_class="crypto",
        required_data_type=data_type,
        execution_required=True,
    )


def _router(provider_ids: tuple[str, ...] = ("kraken_public", "coinbase_public", "binance_us_public")):
    return build_feed_provider_router(configured_provider_ids=provider_ids, env={})


def test_healthy_primary_provider_is_selected():
    result = _router().select_provider(_request())

    assert result.status == "SELECTED"
    assert result.reason == "PRIMARY_SELECTED"
    assert result.selected_provider_id == "kraken_public"
    assert result.to_telemetry()["selected_provider"]["provider_id"] == "kraken_public"


def test_primary_dns_failure_falls_back_to_secondary_provider():
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

    assert result.status == "SELECTED"
    assert result.reason == "FALLBACK_SELECTED"
    assert result.selected_provider_id == "coinbase_public"
    assert result.skipped["kraken_public"] == ("DNS_FAILURE",)
    assert result.fallback_path[0] == "coinbase_public"


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

    assert result.selected_provider_id == "coinbase_public"
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

    assert result.selected_provider_id == "coinbase_public"
    assert result.skipped["kraken_public"] == ("DUPLICATE_CANDLE",)


def test_missing_credentials_provider_is_skipped_with_reason():
    result = _router(("coinmarketcap_reference",)).select_provider(
        FeedProviderRequest(
            symbol="BTC/USD",
            asset_class="crypto",
            required_data_type="reference_price",
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
    router = _router(("kraken_public", "coinbase_public"))

    result = router.select_provider(
        _request("ticker"),
        provider_status={
            "kraken_public": ProviderRuntimeStatus(
                provider_id="kraken_public",
                health=FeedProviderHealth.HEALTHY.value,
                observed_value=100.0,
            ),
            "coinbase_public": ProviderRuntimeStatus(
                provider_id="coinbase_public",
                health=FeedProviderHealth.HEALTHY.value,
                observed_value=110.0,
            ),
        },
    )

    assert result.status == "FAILED_CLOSED"
    assert result.reason == "PROVIDER_CONFLICT"
    assert result.selected_provider is None
    assert result.conflicts == {"kraken_public": 100.0, "coinbase_public": 110.0}


def test_provider_conflict_can_use_explicit_trusted_priority():
    router = build_feed_provider_router(
        configured_provider_ids=("kraken_public", "coinbase_public"),
        trusted_source_priority=("coinbase_public",),
        env={},
    )

    result = router.select_provider(
        _request("ticker"),
        provider_status={
            "kraken_public": ProviderRuntimeStatus(
                provider_id="kraken_public",
                health=FeedProviderHealth.HEALTHY.value,
                observed_value=100.0,
            ),
            "coinbase_public": ProviderRuntimeStatus(
                provider_id="coinbase_public",
                health=FeedProviderHealth.HEALTHY.value,
                observed_value=110.0,
            ),
        },
    )

    assert result.status == "SELECTED_WITH_TRUSTED_SOURCE_CONFLICT"
    assert result.reason == "TRUSTED_SOURCE_PRIORITY"
    assert result.selected_provider_id == "coinbase_public"


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

    assert telemetry["status"] == "SELECTED"
    assert telemetry["reason"] == "FALLBACK_SELECTED"
    assert telemetry["selected_provider_id"] == "coinbase_public"
    assert telemetry["skipped"]["kraken_public"] == ("DNS_FAILURE",)


def test_router_telemetry_does_not_touch_broker_mutation_path():
    result = _router().select_provider(_request())
    telemetry = result.to_telemetry()
    serialized = repr(telemetry).lower()

    assert "order_router" not in serialized
    assert "broker_gateway" not in serialized
    assert "broker mutation" not in serialized
    assert telemetry["selected_provider"]["provider_type"] == "executable_market_data"
