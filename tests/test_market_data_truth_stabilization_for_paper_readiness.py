from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import aiohttp

from app.data.market_feeds import MarketFeeds
from app.data.polling_client import PollingClient
from app.data.websocket_client import KrakenWebSocketClient
from app.models import Candle, OrderBookSnapshot
from app.utils.time_utils import now_ns


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        symbol_universe=["BTC/USD"],
        data=SimpleNamespace(max_candles_per_symbol=100, polling_interval_seconds=1),
        risk=SimpleNamespace(stale_data_threshold_seconds=60),
    )


def _dns_failure() -> aiohttp.ClientConnectorError:
    return aiohttp.ClientConnectorError(
        SimpleNamespace(host="api.kraken.com", port=443, ssl=True),
        OSError("dns failure"),
    )


def _book(ts_ns: int) -> OrderBookSnapshot:
    return OrderBookSnapshot(
        symbol="BTC/USD",
        exchange_ts_ns=ts_ns,
        bids=[(100.0, 1.0), (99.0, 2.0)],
        asks=[(101.0, 1.5), (102.0, 2.5)],
    )


def _candle(ts_ns: int, close: float = 100.5) -> Candle:
    return Candle(
        symbol="BTC/USD",
        exchange_ts_ns=ts_ns,
        open=100.0,
        high=max(101.0, close),
        low=99.0,
        close=close,
        volume=10.0,
        timeframe="1m",
    )


def test_rest_dns_failure_plus_clean_websocket_truth_is_partial_not_total_death():
    feeds = MarketFeeds(_config())
    ts_ns = now_ns()
    websocket = KrakenWebSocketClient(symbols=["BTC/USD"])
    websocket._connected = True
    websocket._messages_processed = 2
    websocket._last_message_time_ns = ts_ns
    polling = PollingClient(symbols=["BTC/USD"])
    polling._record_polling_failure(
        "BTC/USD",
        "candle",
        _dns_failure(),
        endpoint="https://api.kraken.com/0/public/OHLC",
    )
    feeds.websocket_client = websocket
    feeds.polling_client = polling
    feeds.order_books["BTC/USD"] = _book(ts_ns)
    feeds.candles.add_candle(_candle(ts_ns))

    truth = feeds.get_feed_truth_status()

    assert truth["status"] == "WEBSOCKET_ACTIVE_REST_DNS_FAILED"
    assert truth["market_truth"] == "MARKET_DATA_PARTIAL_TRUTH"
    assert truth["websocket"]["status"] == "WEBSOCKET_ACTIVE"
    assert truth["rest"]["latest_failure"]["status"] == "DNS_FAILURE_RECORDED"
    assert "MISSING_ORDER_BOOK_TRUTH:BTC/USD" not in truth["missing_truth"]
    assert "MISSING_CANDLE_TRUTH:BTC/USD" not in truth["missing_truth"]


def test_crossed_book_snapshot_is_quarantined_and_later_clean_snapshot_recovers():
    callback = Mock()
    client = KrakenWebSocketClient(symbols=["BTC/USD"], on_order_book=callback)
    crossed = {
        "channel": "book",
        "type": "snapshot",
        "data": [
            {
                "symbol": "BTC/USD",
                "timestamp": "2026-05-21T17:00:00.000Z",
                "bids": [{"price": "101.0", "qty": "1.0"}],
                "asks": [{"price": "100.0", "qty": "1.0"}],
            }
        ],
    }
    clean = {
        "channel": "book",
        "type": "snapshot",
        "data": [
            {
                "symbol": "BTC/USD",
                "timestamp": "2026-05-21T17:00:01.000Z",
                "bids": [{"price": "100.0", "qty": "1.0"}],
                "asks": [{"price": "101.0", "qty": "1.0"}],
            }
        ],
    }

    asyncio.run(client._parse_order_book(crossed, now_ns()))
    assert callback.call_count == 0
    assert client.get_stats()["book_quality_by_symbol"]["BTC/USD"]["status"] == "BOOK_QUARANTINED"
    assert client.get_stats()["book_quality_by_symbol"]["BTC/USD"]["reason"] == "CROSSED_BOOK_PREVENTED"

    asyncio.run(client._parse_order_book(clean, now_ns()))
    assert callback.call_count == 1
    emitted = callback.call_args[0][0]
    assert emitted.best_bid == 100.0
    assert emitted.best_ask == 101.0
    assert client.get_stats()["book_quality_by_symbol"]["BTC/USD"]["status"] == "BOOK_ACTIVE"


def test_book_updates_are_truncated_to_subscribed_depth_before_emission():
    callback = Mock()
    client = KrakenWebSocketClient(symbols=["BTC/USD"], on_order_book=callback, book_depth=3)
    snapshot = {
        "channel": "book",
        "type": "snapshot",
        "data": [
            {
                "symbol": "BTC/USD",
                "timestamp": "2026-05-21T17:00:00.000Z",
                "bids": [
                    {"price": "100.0", "qty": "1.0"},
                    {"price": "99.0", "qty": "1.0"},
                    {"price": "98.0", "qty": "1.0"},
                ],
                "asks": [
                    {"price": "101.0", "qty": "1.0"},
                    {"price": "102.0", "qty": "1.0"},
                    {"price": "103.0", "qty": "1.0"},
                ],
            }
        ],
    }
    update = {
        "channel": "book",
        "type": "update",
        "data": [
            {
                "symbol": "BTC/USD",
                "timestamp": "2026-05-21T17:00:01.000Z",
                "bids": [{"price": "99.5", "qty": "1.0"}],
                "asks": [{"price": "101.5", "qty": "1.0"}],
            }
        ],
    }

    asyncio.run(client._parse_order_book(snapshot, now_ns()))
    asyncio.run(client._parse_order_book(update, now_ns()))

    emitted = callback.call_args[0][0]
    assert len(emitted.bids) == 3
    assert len(emitted.asks) == 3
    assert [price for price, _ in emitted.bids] == [100.0, 99.5, 99.0]
    assert [price for price, _ in emitted.asks] == [101.0, 101.5, 102.0]


def test_duplicate_candle_is_quarantined_without_corrupting_callback_window():
    callback = Mock()
    client = KrakenWebSocketClient(symbols=["BTC/USD"], on_candle=callback)
    first = {
        "channel": "ohlc",
        "data": [
            {
                "symbol": "BTC/USD",
                "interval_begin": "2026-05-21T17:00:00.000Z",
                "open": "100.0",
                "high": "101.0",
                "low": "99.0",
                "close": "100.5",
                "volume": "10.0",
            }
        ],
    }
    duplicate_update = {
        "channel": "ohlc",
        "data": [
            {
                "symbol": "BTC/USD",
                "interval_begin": "2026-05-21T17:00:00.000Z",
                "open": "100.0",
                "high": "102.0",
                "low": "99.0",
                "close": "101.5",
                "volume": "12.0",
            }
        ],
    }
    next_interval = {
        "channel": "ohlc",
        "data": [
            {
                "symbol": "BTC/USD",
                "interval_begin": "2026-05-21T17:01:00.000Z",
                "open": "101.5",
                "high": "103.0",
                "low": "101.0",
                "close": "102.0",
                "volume": "8.0",
            }
        ],
    }

    asyncio.run(client._parse_candle(first, now_ns()))
    asyncio.run(client._parse_candle(duplicate_update, now_ns()))
    asyncio.run(client._parse_candle(next_interval, now_ns()))

    assert callback.call_count == 2
    emitted = [call.args[0] for call in callback.call_args_list]
    assert [c.exchange_ts_ns for c in emitted] == sorted(c.exchange_ts_ns for c in emitted)
    assert client.get_stats()["candle_duplicate_rejections_by_symbol"]["BTC/USD"] == 1


def test_missing_required_market_truth_still_fails_closed():
    feeds = MarketFeeds(_config())

    truth = feeds.get_feed_truth_status()

    assert truth["status"] == "FAILED_CLOSED"
    assert truth["market_truth"] == "MISSING_FEED_TRUTH"
    assert "MISSING_ORDER_BOOK_TRUTH:BTC/USD" in truth["missing_truth"]
    assert "MISSING_CANDLE_TRUTH:BTC/USD" in truth["missing_truth"]
