from __future__ import annotations

import asyncio
from types import SimpleNamespace

import aiohttp

from app.core.decision_compiler import DecisionCompiler
from app.data.market_feeds import MarketFeeds
from app.data.polling_client import PollingClient
from app.data.websocket_client import KrakenWebSocketClient
from app.models.contracts import (
    ExchangeTruth,
    ExecutionTruth,
    PortfolioTruth,
    RiskTruth,
    StrategyTruth,
    TruthFrame,
)
from app.models.enums import TruthStatus
from app.monitoring.alerts import AlertType, SovereignSentinel
from app.monitoring.health import ComponentCriticality, HealthMonitor


T0_NS = 1_779_200_000_000_000_000


class FailingDnsSession:
    def get(self, *args, **kwargs):
        conn_key = SimpleNamespace(host="api.kraken.com", port=443, ssl=True)
        raise aiohttp.ClientConnectorError(conn_key, OSError("dns failure"))


def _config():
    return SimpleNamespace(
        symbol_universe=["BTC/USD"],
        data=SimpleNamespace(max_candles_per_symbol=10, polling_interval_seconds=1),
        risk=SimpleNamespace(stale_data_threshold_seconds=60),
    )


def _truth_frame() -> TruthFrame:
    return TruthFrame(
        truth_frame_id="kraken-rest-dns-feed-truth",
        timestamp_ns=T0_NS,
        exchange_truth=ExchangeTruth(venue="alpaca_paper_read_only", exchange_ts_ns=T0_NS),
        execution_truth=ExecutionTruth(last_reconciliation_ts_ns=T0_NS),
        portfolio_truth=PortfolioTruth(last_update_ts_ns=T0_NS),
        strategy_truth=StrategyTruth(last_update_ts_ns=T0_NS),
        risk_truth=RiskTruth(),
        status=TruthStatus.RECONCILED,
    )


def test_polling_client_records_dns_failure_without_fake_candle_truth():
    emitted_candles = []
    emitted_truth = []
    polling = PollingClient(
        symbols=["BTC/USD"],
        on_candle=emitted_candles.append,
        on_feed_truth=emitted_truth.append,
    )
    polling._session = FailingDnsSession()

    asyncio.run(polling._fetch_candles("BTC/USD"))

    stats = polling.get_stats()
    failure = stats["last_failure_status"]
    assert failure["status"] == "DNS_FAILURE_RECORDED"
    assert failure["rest_status"] == "REST_POLLING_DEGRADED"
    assert failure["market_truth"] == "MISSING_CANDLE_TRUTH"
    assert failure["endpoint_domain"] == "api.kraken.com"
    assert emitted_candles == []
    assert emitted_truth[-1]["status"] == "DNS_FAILURE_RECORDED"


def test_polling_client_records_dns_failure_without_fake_order_book_truth():
    emitted_books = []
    polling = PollingClient(symbols=["BTC/USD"], on_order_book=emitted_books.append)
    polling._session = FailingDnsSession()

    asyncio.run(polling._fetch_order_book("BTC/USD"))

    failure = polling.get_stats()["last_failure_status"]
    assert failure["status"] == "DNS_FAILURE_RECORDED"
    assert failure["market_truth"] == "MISSING_ORDER_BOOK_TRUTH"
    assert failure["endpoint_domain"] == "api.kraken.com"
    assert emitted_books == []


def test_websocket_active_rest_dns_failure_is_partial_market_truth():
    feeds = MarketFeeds(_config())
    websocket = KrakenWebSocketClient(symbols=["BTC/USD"])
    websocket._connected = True
    websocket._messages_processed = 3
    websocket._last_message_time_ns = T0_NS

    polling = PollingClient(symbols=["BTC/USD"])
    polling._record_polling_failure(
        "BTC/USD",
        "candle",
        aiohttp.ClientConnectorError(
            SimpleNamespace(host="api.kraken.com", port=443, ssl=True),
            OSError("dns failure"),
        ),
        endpoint="https://api.kraken.com/0/public/OHLC",
    )

    feeds.websocket_client = websocket
    feeds.polling_client = polling

    truth = feeds.get_feed_truth_status()
    assert truth["status"] == "WEBSOCKET_ACTIVE_REST_DNS_FAILED"
    assert truth["market_truth"] == "MARKET_DATA_PARTIAL_TRUTH"
    assert truth["websocket"]["status"] == "WEBSOCKET_ACTIVE"
    assert truth["rest"]["latest_failure"]["status"] == "DNS_FAILURE_RECORDED"
    assert "MISSING_CANDLE_TRUTH" in truth["missing_truth"]
    assert "MISSING_ORDER_BOOK_TRUTH:BTC/USD" in truth["missing_truth"]


def test_market_status_preserves_websocket_provenance_and_missing_rest_truth():
    feeds = MarketFeeds(_config())
    websocket = KrakenWebSocketClient(symbols=["BTC/USD"])
    websocket._connected = True
    websocket._messages_processed = 1
    websocket._last_message_time_ns = T0_NS
    polling = PollingClient(symbols=["BTC/USD"])
    polling._record_polling_failure(
        "BTC/USD",
        "order_book",
        aiohttp.ClientConnectorError(
            SimpleNamespace(host="api.kraken.com", port=443, ssl=True),
            OSError("dns failure"),
        ),
        endpoint="https://api.kraken.com/0/public/Depth",
    )
    feeds.websocket_client = websocket
    feeds.polling_client = polling

    status = feeds.get_market_status()
    assert status["websocket_connected"] is True
    assert status["feed_truth_status"] == "WEBSOCKET_ACTIVE_REST_DNS_FAILED"
    assert status["feed_truth"]["market_truth"] == "MARKET_DATA_PARTIAL_TRUTH"
    assert status["feed_truth"]["rest"]["latest_failure"]["market_truth"] == "MISSING_ORDER_BOOK_TRUTH"


def test_health_reports_rest_dns_failure_as_degraded_market_data():
    health = HealthMonitor(stale_threshold_ms=500)
    feed_truth = {
        "status": "WEBSOCKET_ACTIVE_REST_DNS_FAILED",
        "market_truth": "MARKET_DATA_PARTIAL_TRUTH",
        "missing_truth": ("MISSING_CANDLE_TRUTH", "MISSING_ORDER_BOOK_TRUTH"),
    }

    health.record_market_data_truth(
        component_name="kraken_market_data",
        ts_ns=T0_NS,
        feed_truth=feed_truth,
        criticality=ComponentCriticality.IMPORTANT,
    )

    snapshot = health.get_snapshot_canonical(current_ts_ns=T0_NS + 1_000_000)
    component = snapshot.components["kraken_market_data"]
    assert component["metadata"]["feed_truth_status"] == "WEBSOCKET_ACTIVE_REST_DNS_FAILED"
    assert component["metadata"]["market_truth"] == "MARKET_DATA_PARTIAL_TRUTH"
    assert component["metadata"]["reason_code"] == "REST_DNS_FAILURE"


def test_alerts_record_local_rest_dns_failure_without_external_dispatch(tmp_path, monkeypatch):
    def forbidden_post(*args, **kwargs):
        raise AssertionError("external alert dispatch must not run in deterministic test")

    monkeypatch.setattr("app.monitoring.alerts.requests.post", forbidden_post)
    sentinel = SovereignSentinel(
        webhook_url=None,
        telegram_bot_token=None,
        telegram_chat_id=None,
        alert_cooldown_sec=0.0,
        state_file=str(tmp_path / "alert_state.json"),
    )

    sentinel.alert_rest_dns_failure("kraken", "api.kraken.com", "BTC/USD", "candle")

    recent = sentinel.get_recent_alerts()
    assert len(recent) == 1
    assert recent[0]["type"] == AlertType.REST_DNS_FAILURE.value
    assert recent[0]["data"]["reason"] == "DNS_FAILURE_RECORDED"
    assert recent[0]["data"]["market_truth"] == "MARKET_DATA_PARTIAL_TRUTH"


def test_decision_compiler_carries_feed_truth_attribution_without_market_facts():
    compiler = DecisionCompiler()
    feed_truth = {
        "KrakenMarketFeeds": {
            "module_name": "MarketFeeds",
            "category": "market_data",
            "status": "WEBSOCKET_ACTIVE_REST_DNS_FAILED",
            "input_source": "Kraken websocket stats and PollingClient DNS failure telemetry",
            "output_summary": "websocket active; REST candle/book truth missing",
            "effect": "ADVISORY",
            "reason": "MARKET_DATA_PARTIAL_TRUTH",
            "timestamp": T0_NS,
        }
    }

    record = compiler.compile(
        truth_frame=_truth_frame(),
        additional_inputs={
            "market_data_attribution": feed_truth,
            "market_truth_summary": {
                "status": "MARKET_DATA_PARTIAL_TRUTH",
                "missing_truth": ("MISSING_CANDLE_TRUTH", "MISSING_ORDER_BOOK_TRUTH"),
            },
        },
    )

    assert record.metadata["market_data_attribution"] == feed_truth
    assert record.metadata["market_truth_summary"]["status"] == "MARKET_DATA_PARTIAL_TRUTH"
    assert "pnl" not in str(record.metadata).lower()
    assert "slippage" not in str(record.metadata).lower()
