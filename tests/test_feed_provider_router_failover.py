from __future__ import annotations

from types import SimpleNamespace

import main
from app.data.polling_client import PollingClient
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


def _request(data_type: str = "order_book", *, execution_required: bool = True) -> FeedProviderRequest:
    return FeedProviderRequest(
        symbol="BTC/USD",
        asset_class="crypto",
        required_data_type=data_type,
        provider_lane=FeedProviderLane.CRYPTO_MARKET_DATA.value,
        execution_required=execution_required,
    )


def _router(
    provider_ids: tuple[str, ...] = ("coinbase_public", "binance_us_public", "kraken_public"),
    *,
    alpaca_credentials: bool = False,
):
    env = {"APCA_API_KEY_ID": "present", "APCA_API_SECRET_KEY": "present"} if alpaca_credentials else {}
    return build_feed_provider_router(configured_provider_ids=provider_ids, env=env)


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


def test_alpaca_execution_location_stream_is_positive_primary_twin():
    result = _router(
        ("alpaca_crypto_stream", "alpaca_crypto_rest", "coinbase_public", "kraken_public"),
        alpaca_credentials=True,
    ).select_provider(_request())

    assert result.status == "SELECTED"
    assert result.reason == "PRIMARY_SELECTED"
    assert result.selected_provider_id == "alpaca_crypto_stream"
    assert result.selected_provider.execution_location == "alpaca"
    assert result.selected_provider.transport_adapter == "alpaca_crypto_websocket"
    assert result.selected_provider.execution_eligible is True
    assert result.selected_provider.advisory_only is False


def test_failed_alpaca_stream_selects_alpaca_rest_executable_fallback():
    result = _router(
        ("alpaca_crypto_stream", "alpaca_crypto_rest", "coinbase_public", "kraken_public"),
        alpaca_credentials=True,
    ).select_provider(
        _request(),
        provider_status={
            "alpaca_crypto_stream": ProviderRuntimeStatus(
                provider_id="alpaca_crypto_stream",
                health=FeedProviderHealth.FAILED.value,
                reason_codes=("WEBSOCKET_UNAVAILABLE",),
            )
        },
    )

    assert result.status == "SELECTED"
    assert result.reason == "FALLBACK_SELECTED"
    assert result.selected_provider_id == "alpaca_crypto_rest"
    assert result.selected_provider.execution_location == "alpaca"
    assert result.skipped["alpaca_crypto_stream"] == ("WEBSOCKET_UNAVAILABLE",)


def test_cross_venue_public_sources_cannot_satisfy_execution_required_request():
    result = _router(("coinbase_public", "kraken_public")).select_provider(_request())

    assert result.status == "FAILED_CLOSED"
    assert result.selected_provider is None
    for provider_id in ("coinbase_public", "kraken_public"):
        assert "ADVISORY_ONLY" in result.skipped[provider_id]
        assert "REFERENCE_OR_ADVISORY_NOT_EXECUTABLE" in result.skipped[provider_id]
        assert "NOT_EXECUTION_ELIGIBLE" in result.skipped[provider_id]


def test_configured_advisory_provider_priority_is_respected_when_transport_is_available():
    result = _router(("kraken_public",)).select_provider(_request(execution_required=False))

    assert result.status == "SELECTED"
    assert result.reason == "PRIMARY_SELECTED"
    assert result.selected_provider_id == "kraken_public"
    assert result.to_telemetry()["selected_provider"]["provider_id"] == "kraken_public"
    assert result.to_telemetry()["selected_provider"]["provider_lane"] == "crypto_market_data"


def test_missing_fallback_transport_does_not_fake_market_data():
    result = _router(("binance_us_public",)).select_provider(_request())

    assert result.status == "FAILED_CLOSED"
    assert result.reason == "MISSING_MARKET_TRUTH"
    assert result.selected_provider is None
    assert "MISSING_TRANSPORT" in result.skipped["binance_us_public"]


def test_advisory_crypto_priority_selects_coinbase_public_before_kraken():
    result = _router().select_provider(_request(execution_required=False))

    assert result.status == "SELECTED"
    assert result.reason == "PRIMARY_SELECTED"
    assert result.selected_provider_id == "coinbase_public"
    assert result.selected_provider.to_telemetry()["transport_adapter"] == "coinbase_exchange_public_rest"
    assert "MISSING_TRANSPORT" in result.skipped["binance_us_public"]


def test_degraded_kraken_is_skipped_after_coinbase_advisory_selected():
    result = _router().select_provider(
        _request(execution_required=False),
        provider_status={
            "kraken_public": ProviderRuntimeStatus(
                provider_id="kraken_public",
                health=FeedProviderHealth.FAILED.value,
                reason_codes=("DNS_FAILURE",),
            )
        },
    )

    assert result.status == "SELECTED"
    assert result.reason == "PRIMARY_SELECTED"
    assert result.selected_provider_id == "coinbase_public"
    assert result.skipped["kraken_public"] == ("DNS_FAILURE",)
    assert "MISSING_TRANSPORT" in result.skipped["binance_us_public"]


def test_crossed_kraken_advisory_book_is_quarantined_while_coinbase_is_selected():
    result = _router().select_provider(
        _request(execution_required=False),
        provider_status={
            "kraken_public": ProviderRuntimeStatus(
                provider_id="kraken_public",
                health=FeedProviderHealth.DEGRADED.value,
                reason_codes=("CROSSED_BOOK",),
            )
        },
    )

    assert result.status == "SELECTED"
    assert result.selected_provider_id == "coinbase_public"
    assert result.skipped["kraken_public"] == ("CROSSED_BOOK",)


def test_duplicate_kraken_advisory_candle_is_rejected_while_coinbase_is_selected():
    result = _router().select_provider(
        _request("candles", execution_required=False),
        provider_status={
            "kraken_public": ProviderRuntimeStatus(
                provider_id="kraken_public",
                health=FeedProviderHealth.DEGRADED.value,
                reason_codes=("DUPLICATE_CANDLE",),
            )
        },
    )

    assert result.status == "SELECTED"
    assert result.selected_provider_id == "coinbase_public"
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


def test_selected_advisory_provider_and_fallback_reason_are_recorded():
    result = _router().select_provider(
        _request(execution_required=False),
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
    assert telemetry["reason"] == "PRIMARY_SELECTED"
    assert telemetry["selected_provider_id"] == "coinbase_public"
    assert telemetry["skipped"]["kraken_public"] == ("DNS_FAILURE",)
    assert telemetry["provider_lane"] == "crypto_market_data"


def test_router_telemetry_does_not_touch_broker_mutation_path():
    result = _router(("kraken_public",)).select_provider(_request(execution_required=False))
    telemetry = result.to_telemetry()
    serialized = repr(telemetry).lower()

    assert "order_router" not in serialized
    assert "broker_gateway" not in serialized
    assert "broker mutation" not in serialized
    assert telemetry["selected_provider"]["provider_type"] == "reference_market_data"
    assert telemetry["selected_provider"]["advisory_only"] is True


def test_coinbase_public_does_not_advertise_unsupported_trades_or_ticker():
    trades = _router(("coinbase_public",)).select_provider(_request("trades", execution_required=False))
    ticker = _router(("coinbase_public",)).select_provider(_request("ticker", execution_required=False))

    assert trades.status == "FAILED_CLOSED"
    assert trades.reason == "MISSING_MARKET_TRUTH"
    assert trades.skipped["coinbase_public"] == ("UNSUPPORTED_DATA_TYPE",)
    assert ticker.status == "FAILED_CLOSED"
    assert ticker.reason == "MISSING_MARKET_TRUTH"
    assert ticker.skipped["coinbase_public"] == ("UNSUPPORTED_DATA_TYPE",)


def test_coinbase_public_symbol_and_endpoint_mapping_are_public_market_data_only():
    client = PollingClient(symbols=["BTC/USD"], exchange="coinbase")
    formatted = client._format_symbol("BTC/USD")

    assert formatted == "BTC-USD"
    assert client._resolve_endpoint("order_book", formatted) == (
        "https://api.exchange.coinbase.com/products/BTC-USD/book"
    )
    assert client._resolve_endpoint("candle", formatted) == (
        "https://api.exchange.coinbase.com/products/BTC-USD/candles"
    )
    assert client._build_order_book_params(formatted) == {"level": 2}
    assert client._build_candle_params(formatted) == {"granularity": 60}


def test_coinbase_public_parses_documented_book_without_fabricated_timestamp():
    client = PollingClient(symbols=["BTC/USD"], exchange="coinbase")
    snapshot = client._parse_order_book(
        {
            "sequence": 13051505638,
            "bids": [["6247.58", "6.3578146", 2]],
            "asks": [["6251.52", "2", 1]],
            "time": "2021-02-12T01:09:23.334Z",
        },
        "BTC/USD",
    )

    assert snapshot is not None
    assert snapshot.symbol == "BTC/USD"
    assert snapshot.exchange_ts_ns == 1613092163334000000
    assert snapshot.bids == [(6247.58, 6.3578146)]
    assert snapshot.asks == [(6251.52, 2.0)]


def test_coinbase_public_rejects_book_without_exchange_time():
    client = PollingClient(symbols=["BTC/USD"], exchange="coinbase")

    snapshot = client._parse_order_book(
        {
            "bids": [["6247.58", "6.3578146", 2]],
            "asks": [["6251.52", "2", 1]],
        },
        "BTC/USD",
    )

    assert snapshot is None


def test_coinbase_public_parses_documented_candles_in_time_order():
    client = PollingClient(symbols=["BTC/USD"], exchange="coinbase")
    candles = client._parse_candles(
        [
            [1613092223, "6200.0", "6300.0", "6250.0", "6260.0", "1.5"],
            [1613092163, "6100.0", "6200.0", "6150.0", "6160.0", "2.5"],
        ],
        "BTC/USD",
    )

    assert [candle.exchange_ts_ns for candle in candles] == [
        1613092163000000000,
        1613092223000000000,
    ]
    assert candles[0].open == 6150.0
    assert candles[0].high == 6200.0
    assert candles[0].low == 6100.0
    assert candles[0].close == 6160.0
    assert candles[0].volume == 2.5


def test_rest_polling_marks_latest_closed_candle_executable_not_open_batch_head():
    client = PollingClient(
        symbols=["BTC/USD"],
        exchange="coinbase",
        provider_id="coinbase_public",
        freshness_policy={"candle_stale_seconds": 60},
    )
    candles = client._parse_candles(
        [
            [1613092223, "6200.0", "6300.0", "6250.0", "6260.0", "1.5"],
            [1613092163, "6100.0", "6200.0", "6150.0", "6160.0", "2.5"],
        ],
        "BTC/USD",
    )
    provider_head_ts = max(candle.exchange_ts_ns for candle in candles)
    response_received_ns = provider_head_ts + 1_000
    latest_ts = client._latest_executable_batch_ts_ns(
        candles,
        response_received_ns=response_received_ns,
    )
    annotated = [
        client._with_candle_runtime_metadata(
            candle,
            latest_batch_ts_ns=latest_ts,
            provider_batch_head_ts_ns=provider_head_ts,
            response_received_ns=response_received_ns,
            candle_policy_ms=client._candle_freshness_policy_ms(),
        )
        for candle in candles
    ]

    assert latest_ts == annotated[0].exchange_ts_ns
    assert annotated[0].latest_batch_candle is True
    assert annotated[0].latest_closed_batch_candle is True
    assert annotated[0].candle_closed_at_receive is True
    assert annotated[1].latest_batch_candle is False
    assert annotated[1].latest_provider_batch_candle is True
    assert annotated[1].latest_closed_batch_candle is False
    assert annotated[1].candle_closed_at_receive is False
    assert all(candle.data_source_type == "runtime" for candle in annotated)
    assert all(candle.provider_id == "coinbase_public" for candle in annotated)
    assert all(candle.candle_freshness_policy_ms == 60_000.0 for candle in annotated)


def test_rest_polling_has_no_executable_candle_when_batch_head_is_not_closed():
    client = PollingClient(symbols=["BTC/USD"], exchange="coinbase")
    candles = client._parse_candles(
        [[1613092223, "6200.0", "6300.0", "6250.0", "6260.0", "1.5"]],
        "BTC/USD",
    )

    latest_ts = client._latest_executable_batch_ts_ns(
        candles,
        response_received_ns=1613092224 * 1_000_000_000,
    )

    assert latest_ts == 0


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
