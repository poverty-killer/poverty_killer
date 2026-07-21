from __future__ import annotations

import asyncio
import copy
import json
import math
import socket
import sqlite3
import threading
import time
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

import main
from app.config import DataConfig
from app.data.feed_provider_router import (
    FeedProviderLane,
    FeedProviderRequest,
    build_feed_provider_router,
)
from app.data.market_feeds import MarketFeeds
from app.data.polling_client import (
    BatchedAlpacaPollingClient,
    MarketDataRequestBudget,
    MarketDataTransportPolicy,
    _RequestBudget,
)
from app.data.validators import DataValidator
from app.data.websocket_client import AlpacaCryptoWebSocketClient
from app.market.capability_registry import (
    MARKET_DATA_OBSERVE_ONLY,
    MarketBreadthObservation,
    MarketDataUniverseSnapshot,
    build_market_data_universe_snapshot,
)
from app.models import Candle, OrderBookSnapshot
from app.state.state_store import StateStore
from app.utils.time_utils import now_ns


BASE_NS = 1_800_000_000_000_000_000
CREDS = {"APCA_API_KEY_ID": "stage4-key", "APCA_API_SECRET_KEY": "stage4-secret"}


def _symbols(count: int) -> list[str]:
    return [f"ASSET{index:04d}/USD" for index in range(count)]


def _rfc3339_ns(timestamp_ns: int) -> str:
    seconds, fraction_ns = divmod(int(timestamp_ns), 1_000_000_000)
    prefix = datetime.fromtimestamp(seconds, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    return f"{prefix}.{fraction_ns:09d}Z"


def _snapshot_payload(
    symbols: list[str] | tuple[str, ...],
    *,
    received_ns: int | None = None,
) -> dict:
    current_ns = int(received_ns if received_ns is not None else now_ns())
    quote_timestamp = _rfc3339_ns(current_ns - 1_000_000_000)
    minute_ns = 60_000_000_000
    bar_timestamp = _rfc3339_ns((current_ns // minute_ns - 1) * minute_ns)
    return {
        "snapshots": {
            symbol: {
                "latestQuote": {"t": quote_timestamp, "bp": 99.5, "ap": 100.5, "bs": 5, "as": 6},
                "latestTrade": {"t": quote_timestamp, "p": 100.0, "s": 0.25},
                "minuteBar": {
                    "t": bar_timestamp,
                    "o": 99.0,
                    "h": 101.0,
                    "l": 98.5,
                    "c": 100.0,
                    "v": 25.0,
                    "n": 8,
                },
            }
            for symbol in symbols
        }
    }


def _order_book_payload(
    symbols: list[str] | tuple[str, ...],
    *,
    received_ns: int | None = None,
) -> dict:
    current_ns = int(received_ns if received_ns is not None else now_ns())
    timestamp = _rfc3339_ns(current_ns - 1_000_000_000)
    return {
        "orderbooks": {
            symbol: {
                "t": timestamp,
                "b": [{"p": 99.5, "s": 5.0}, {"p": 99.0, "s": 8.0}],
                "a": [{"p": 100.5, "s": 6.0}, {"p": 101.0, "s": 9.0}],
            }
            for symbol in symbols
        }
    }


def _policy(**overrides) -> MarketDataTransportPolicy:
    values = {
        "batch_size": 50,
        "max_concurrency": 3,
        "global_requests_per_minute": 10_000,
        "provider_requests_per_minute": 10_000,
        "request_timeout_seconds": 1.0,
        "max_retries": 0,
        "backoff_base_seconds": 0.001,
        "backoff_max_seconds": 0.01,
        "circuit_failure_threshold": 2,
        "circuit_cooldown_seconds": 1.0,
        "job_queue_size": 4,
        "failure_history_size": 10,
        "callback_timeout_seconds": 0.01,
    }
    values.update(overrides)
    return MarketDataTransportPolicy(**values)


def _observation(symbol: str, quality: float = 1.0, *, cross_venue: bool = True) -> MarketBreadthObservation:
    event_ns = BASE_NS - 1_000_000_000
    scale = Decimal(str(quality))
    return MarketBreadthObservation(
        symbol=symbol,
        provider_id="alpaca_crypto_rest",
        execution_location="alpaca",
        observed_at_ns=BASE_NS - 500_000_000,
        latest_source_event_ns=event_ns,
        expected_samples=8,
        received_samples=8,
        dollar_volumes=tuple(Decimal("100000") * scale * Decimal(index + 1) for index in range(8)),
        trade_counts=tuple(max(1, int(100 * quality) + index) for index in range(8)),
        spreads_bps=tuple(10.0 / quality + index * 0.01 for index in range(8)),
        depth_usd=tuple(Decimal("50000") * scale + Decimal(index * 100) for index in range(8)),
        log_returns=(0.001, -0.001, 0.0015, -0.0005, 0.0007, -0.0008, 0.0006),
        event_lag_ms=tuple(20.0 / quality + index * 0.1 for index in range(8)),
        gap_seconds=tuple(1.0 / quality + index * 0.01 for index in range(7)),
        observation_started_ns=event_ns - 3_600_000_000_000,
        listing_started_ns=event_ns - 30 * 86_400_000_000_000,
        listing_age_source="synthetic_provider_fixture",
        quote_currency="USD",
        quote_currency_fundable=True,
        execution_mid=Decimal("100"),
        cross_venue_mid=Decimal("100.05") if cross_venue else None,
        cross_venue_provider_id="kraken_public" if cross_venue else None,
        cross_venue_source_event_ns=event_ns - 10_000_000 if cross_venue else None,
        cross_venue_received_at_ns=event_ns - 5_000_000 if cross_venue else None,
        min_order_size=Decimal("0.001"),
        min_trade_increment=Decimal("0.0001"),
        price_increment=Decimal("0.01"),
    )


def _universe(
    observations,
    *,
    as_of_ns: int = BASE_NS,
    created_at_ns: int | None = None,
    prior_snapshot=None,
    held=(),
    open_orders=(),
    lifecycle=(),
    candidates: int = 2,
    capacity: int = 5,
    residence_ns: int = 900_000_000_000,
    unranked=(),
) -> MarketDataUniverseSnapshot:
    return build_market_data_universe_snapshot(
        observations,
        catalog_snapshot_id="catalog-stage4",
        broker_universe_snapshot_id="broker-universe-stage4",
        as_of_ns=as_of_ns,
        created_at_ns=created_at_ns if created_at_ns is not None else as_of_ns + 1,
        prior_snapshot=prior_snapshot,
        held_symbols=held,
        open_order_symbols=open_orders,
        lifecycle_symbols=lifecycle,
        deep_candidate_limit=candidates,
        deep_subscription_limit=capacity,
        min_residence_ns=residence_ns,
        unranked_symbols=unranked,
    )


@pytest.mark.parametrize("catalog_size", [1, 6, 56, 511])
def test_batched_alpaca_request_count_scales_with_batches_not_symbols(catalog_size: int):
    symbols = _symbols(catalog_size)
    deep = symbols[: min(7, catalog_size)]
    calls: list[tuple[str, tuple[str, ...]]] = []
    breadth: list[dict] = []
    books: list[object] = []

    async def request_json(endpoint, params):
        requested = tuple(str(params["symbols"]).split(","))
        calls.append((endpoint, requested))
        await asyncio.sleep(0.001)
        payload = _snapshot_payload(requested) if endpoint.endswith("/snapshots") else _order_book_payload(requested)
        return 200, {}, payload

    client = BatchedAlpacaPollingClient(
        breadth_symbols=symbols,
        deep_symbols=deep,
        protected_symbols=deep[:1],
        deep_poll_enabled=True,
        request_headers=CREDS,
        policy=_policy(),
        request_json=request_json,
        on_breadth_snapshot=breadth.append,
        on_order_book=books.append,
    )
    asyncio.run(client.poll_once())

    expected = math.ceil(catalog_size / 50) + math.ceil(len(deep) / 50)
    stats = client.get_stats()
    assert len(calls) == expected
    assert stats["metrics"]["requests_started"] == expected
    assert stats["metrics"]["max_inflight"] <= 3
    assert stats["metrics"]["queue_high_water"] <= 4
    assert len(breadth) == catalog_size
    assert len(books) == len(deep)
    assert all(endpoint.startswith("https://data.alpaca.markets/v1beta3/crypto/us/") for endpoint, _ in calls)
    assert all("orders" not in endpoint for endpoint, _ in calls)


def test_protected_deep_jobs_precede_catalogue_breadth_under_a_single_worker():
    symbols = _symbols(56)
    protected = symbols[-1]
    calls: list[tuple[str, tuple[str, ...]]] = []

    async def request_json(endpoint, params):
        requested = tuple(str(params["symbols"]).split(","))
        calls.append((endpoint, requested))
        payload = _snapshot_payload(requested) if endpoint.endswith("/snapshots") else _order_book_payload(requested)
        return 200, {}, payload

    client = BatchedAlpacaPollingClient(
        breadth_symbols=symbols,
        deep_symbols=[protected],
        protected_symbols=[protected],
        deep_poll_enabled=True,
        request_headers=CREDS,
        policy=_policy(max_concurrency=1),
        request_json=request_json,
    )
    assert asyncio.run(client.poll_once()) is True
    assert calls[0][0].endswith("/latest/orderbooks")
    assert calls[0][1] == (protected,)
    assert calls[1][0].endswith("/snapshots")
    assert protected in calls[1][1]


def test_shared_request_budget_survives_client_replacement_without_resetting_rate_history():
    clock = [100.0]
    sleeps: list[float] = []
    policy = _policy(
        max_concurrency=1,
        global_requests_per_minute=1,
        provider_requests_per_minute=1,
    )

    async def controlled_sleep(delay: float):
        sleeps.append(delay)
        clock[0] += delay

    budget = MarketDataRequestBudget(policy, monotonic=lambda: clock[0], sleep=controlled_sleep)

    async def request_json(endpoint, params):
        requested = tuple(str(params["symbols"]).split(","))
        return 200, {}, _snapshot_payload(requested)

    clients = [
        BatchedAlpacaPollingClient(
            breadth_symbols=["BTC/USD"],
            request_headers=CREDS,
            policy=policy,
            request_json=request_json,
            request_budget=budget,
            monotonic=lambda: clock[0],
            sleep=controlled_sleep,
        )
        for _ in range(2)
    ]

    async def exercise():
        assert await clients[0].poll_once() is True
        assert await clients[1].poll_once() is True

    asyncio.run(exercise())
    assert clients[0]._budget is clients[1]._budget is budget
    assert budget.wait_count == 1
    assert sleeps == [60.0]


def test_request_budget_waits_only_until_the_full_provider_window_releases():
    clock = [0.0]
    sleeps: list[float] = []

    async def advance(delay: float):
        sleeps.append(delay)
        clock[0] += delay

    budget = MarketDataRequestBudget(
        _policy(
            max_concurrency=1,
            global_requests_per_minute=10,
            provider_requests_per_minute=1,
        ),
        monotonic=lambda: clock[0],
        sleep=advance,
    )

    async def exercise():
        async with budget.slot("alpaca_crypto_rest"):
            pass
        clock[0] = 30.0
        async with budget.slot("alpaca_crypto_rest"):
            pass

    asyncio.run(exercise())
    assert sleeps == [pytest.approx(30.0)]
    assert budget.wait_count == 1


def test_malformed_breadth_member_isolated_without_discarding_protected_batch_truth():
    failures: list[dict] = []
    breadth: list[dict] = []

    async def request_json(endpoint, params):
        requested = tuple(str(params["symbols"]).split(","))
        if endpoint.endswith("/snapshots"):
            payload = _snapshot_payload(requested)
            payload["snapshots"]["ETH/USD"]["latestQuote"]["bp"] = "NaN"
        else:
            payload = _order_book_payload(requested)
        return 200, {}, payload

    client = BatchedAlpacaPollingClient(
        breadth_symbols=["BTC/USD", "ETH/USD"],
        deep_symbols=["BTC/USD"],
        protected_symbols=["BTC/USD"],
        deep_poll_enabled=True,
        request_headers=CREDS,
        policy=_policy(),
        request_json=request_json,
        on_breadth_snapshot=breadth.append,
        on_feed_truth=failures.append,
    )
    assert asyncio.run(client.poll_once()) is False
    assert [item["symbol"] for item in breadth] == ["BTC/USD"]
    assert failures[-1]["status"] == "MALFORMED_SNAPSHOT"
    assert failures[-1]["symbol"] == "ETH/USD"

    boolean_snapshot = _snapshot_payload(["BTC/USD"])["snapshots"]["BTC/USD"]
    boolean_snapshot["latestQuote"]["bp"] = True
    with pytest.raises(ValueError, match="numeric_required"):
        client._normalize_snapshot("BTC/USD", boolean_snapshot)
    boolean_book = _order_book_payload(["BTC/USD"])["orderbooks"]["BTC/USD"]
    boolean_book["b"][0]["s"] = True
    with pytest.raises(ValueError, match="numeric_required"):
        client._normalize_order_book("BTC/USD", boolean_book, receive_ts_ns=now_ns())


def test_rank_clock_quality_uses_worst_snapshot_component_age(monkeypatch):
    current_ns = BASE_NS
    import app.data.polling_client as polling_module
    import app.data.market_feeds as market_feeds_module

    monkeypatch.setattr(polling_module, "now_ns", lambda: current_ns)
    monkeypatch.setattr(market_feeds_module, "now_ns", lambda: current_ns)
    client = BatchedAlpacaPollingClient(
        breadth_symbols=["BTC/USD"],
        request_headers=CREDS,
        policy=_policy(),
        request_json=lambda *_args, **_kwargs: None,
    )
    payload = _snapshot_payload(["BTC/USD"], received_ns=current_ns)
    payload["snapshots"]["BTC/USD"]["latestTrade"]["t"] = _rfc3339_ns(
        current_ns - 30_000_000_000
    )
    normalized = client._normalize_snapshot(
        "BTC/USD", payload["snapshots"]["BTC/USD"]
    )
    assert normalized["component_max_age_ms"] == pytest.approx(30_000.0)
    normalized["bid_size"] = 1.0
    normalized["ask_size"] = 100.0

    feeds, _events, _polling, _sockets = _market_feeds()
    feeds._ranking_constraints["BTC/USD"] = {
        "min_order_size": "0.001",
        "min_trade_increment": "0.0001",
        "price_increment": "0.01",
        "quote_currency": "USD",
        "quote_currency_fundable": True,
        "listing_started_ns": None,
        "listing_age_source": None,
    }
    feeds._breadth_observations["BTC/USD"].append(normalized)
    observation = feeds._build_rank_observation("BTC/USD")
    assert observation.event_lag_ms[0] == pytest.approx(30_000.0)
    assert observation.depth_usd == (Decimal("99.5"),)


def test_rest_transport_suppresses_duplicate_bars_books_and_refuses_stale_breadth(monkeypatch):
    current_ns = 1_790_000_000_000_000_000
    snapshot_payload = _snapshot_payload(["BTC/USD"], received_ns=current_ns)
    order_book_payload = _order_book_payload(["BTC/USD"], received_ns=current_ns)
    candles: list[Candle] = []
    breadth: list[dict] = []
    books: list[OrderBookSnapshot] = []

    import app.data.polling_client as polling_module

    monkeypatch.setattr(polling_module, "now_ns", lambda: current_ns)

    async def request_json(endpoint, _params):
        return 200, {}, snapshot_payload if endpoint.endswith("/snapshots") else order_book_payload

    client = BatchedAlpacaPollingClient(
        breadth_symbols=["BTC/USD"],
        deep_symbols=["BTC/USD"],
        protected_symbols=["BTC/USD"],
        deep_poll_enabled=True,
        request_headers=CREDS,
        policy=_policy(),
        request_json=request_json,
        on_candle=candles.append,
        on_breadth_snapshot=breadth.append,
        on_order_book=books.append,
    )
    asyncio.run(client.poll_once())
    asyncio.run(client.poll_once())
    stats = client.get_stats()
    assert len(candles) == len(breadth) == len(books) == 1
    assert stats["metrics"]["duplicate_snapshots_suppressed"] == 1
    assert stats["metrics"]["duplicate_order_books_suppressed"] == 1

    stale = copy.deepcopy(snapshot_payload["snapshots"]["BTC/USD"])
    stale["latestQuote"]["t"] = _rfc3339_ns(current_ns - 11_000_000_000)
    with pytest.raises(ValueError, match="stale_quote"):
        client._normalize_snapshot("BTC/USD", stale)
    stale_trade = copy.deepcopy(snapshot_payload["snapshots"]["BTC/USD"])
    stale_trade["latestTrade"]["t"] = _rfc3339_ns(current_ns - 30_000_000_000)
    normalized = client._normalize_snapshot("BTC/USD", stale_trade)
    assert normalized["trade_age_ms"] == 30_000.0
    stale_book = copy.deepcopy(order_book_payload["orderbooks"]["BTC/USD"])
    stale_book["t"] = _rfc3339_ns(current_ns - 11_000_000_000)
    with pytest.raises(ValueError, match="stale_order_book"):
        client._normalize_order_book("BTC/USD", stale_book, receive_ts_ns=current_ns)


def test_transport_failures_are_reason_coded_bounded_and_secret_safe():
    failures: list[dict] = []

    async def dns_failure(_endpoint, _params):
        raise socket.gaierror("synthetic dns failure")

    client = BatchedAlpacaPollingClient(
        breadth_symbols=["BTC/USD"],
        deep_symbols=["BTC/USD"],
        protected_symbols=["BTC/USD"],
        request_headers=CREDS,
        policy=_policy(failure_history_size=5),
        request_json=dns_failure,
        on_feed_truth=failures.append,
    )
    asyncio.run(client.poll_once())
    for _ in range(12):
        asyncio.run(client._emit_failure("SYNTHETIC_FAILURE", ValueError("bad payload")))

    stats = client.get_stats()
    assert failures[0]["reason_code"] == "DNS_FAILURE"
    assert len(stats["failure_history"]) == 5
    assert len(stats["event_history"]) == 5
    rendered = json.dumps(stats, sort_keys=True)
    assert CREDS["APCA_API_KEY_ID"] not in rendered
    assert CREDS["APCA_API_SECRET_KEY"] not in rendered


def test_rate_limit_opens_circuit_and_blocks_followup_request():
    calls = 0
    failures: list[dict] = []

    async def rate_limited(_endpoint, _params):
        nonlocal calls
        calls += 1
        return 429, {"Retry-After": "1"}, {"message": "limited"}

    client = BatchedAlpacaPollingClient(
        breadth_symbols=["BTC/USD"],
        request_headers=CREDS,
        policy=_policy(),
        request_json=rate_limited,
        on_feed_truth=failures.append,
    )
    asyncio.run(client.poll_once())
    asyncio.run(client.poll_once())

    stats = client.get_stats()
    assert calls == 1
    assert stats["metrics"]["rate_limited"] == 1
    assert stats["circuit_state"] == "OPEN"
    assert failures[0]["reason_code"] == "RATE_LIMITED"
    assert failures[-1]["reason_code"] == "CIRCUIT_OPEN"


def test_non_json_rate_limit_response_preserves_status_and_retry_after_headers():
    class Response:
        status = 429
        headers = {"Retry-After": "17"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def json(self, **_kwargs):
            raise ValueError("synthetic non-json provider body")

    class Session:
        @staticmethod
        def get(*_args, **_kwargs):
            return Response()

    client = BatchedAlpacaPollingClient(
        breadth_symbols=["BTC/USD"],
        deep_symbols=["BTC/USD"],
        protected_symbols=["BTC/USD"],
        request_headers=CREDS,
        policy=_policy(),
        request_json=lambda *_args, **_kwargs: None,
    )
    client._session = Session()
    client._request_json_override = None

    status, headers, payload = asyncio.run(
        client._default_request_json(client.SNAPSHOTS_ENDPOINT, {"symbols": "BTC/USD"})
    )
    assert status == 429
    assert headers["Retry-After"] == "17"
    assert payload == {}


def test_retry_after_is_respected_and_only_one_half_open_probe_can_run():
    clock = [100.0]
    calls = 0

    async def exercise():
        nonlocal calls
        probe_started = asyncio.Event()
        release_probe = asyncio.Event()

        async def request_json(_endpoint, _params):
            nonlocal calls
            calls += 1
            if calls == 1:
                return 429, {"Retry-After": "120"}, {"message": "limited"}
            probe_started.set()
            await release_probe.wait()
            return 200, {}, {"snapshots": {}}

        client = BatchedAlpacaPollingClient(
            breadth_symbols=["BTC/USD"],
            request_headers=CREDS,
            policy=_policy(max_retries=0, backoff_max_seconds=1.0),
            request_json=request_json,
            monotonic=lambda: clock[0],
        )
        with pytest.raises(RuntimeError, match="HTTP_429_RATE_LIMITED"):
            await client._request(client.SNAPSHOTS_ENDPOINT, {"symbols": "BTC/USD"})
        assert client._circuit_open_until == 220.0

        clock[0] = 220.0
        probe = asyncio.create_task(
            client._request(client.SNAPSHOTS_ENDPOINT, {"symbols": "BTC/USD"})
        )
        await asyncio.wait_for(probe_started.wait(), timeout=1.0)
        with pytest.raises(RuntimeError, match="half_open_probe_inflight"):
            await client._request(client.SNAPSHOTS_ENDPOINT, {"symbols": "ETH/USD"})
        release_probe.set()
        assert await asyncio.wait_for(probe, timeout=1.0) == {"snapshots": {}}
        assert client._circuit_state == "CLOSED"
        assert calls == 2

    asyncio.run(exercise())


def test_inflight_success_cannot_clear_or_shorten_a_sibling_retry_after_circuit():
    clock = [0.0]
    success_started = asyncio.Event()
    release_success = asyncio.Event()

    async def request_json(_endpoint, params):
        if params["symbols"] == "SUCCESS/USD":
            success_started.set()
            await release_success.wait()
            return 200, {}, {"ok": True}
        return 429, {"Retry-After": "120"}, {"message": "rate limited"}

    client = BatchedAlpacaPollingClient(
        breadth_symbols=["SUCCESS/USD", "RATE/USD"],
        request_headers=CREDS,
        policy=_policy(max_concurrency=2, max_retries=0),
        request_json=request_json,
        monotonic=lambda: clock[0],
    )

    async def exercise():
        success = asyncio.create_task(
            client._request(client.SNAPSHOTS_ENDPOINT, {"symbols": "SUCCESS/USD"})
        )
        await success_started.wait()
        rate_limited = asyncio.create_task(
            client._request(client.SNAPSHOTS_ENDPOINT, {"symbols": "RATE/USD"})
        )
        while client._circuit_state != "OPEN":
            await asyncio.sleep(0)
        release_success.set()
        return await asyncio.gather(success, rate_limited, return_exceptions=True)

    success_result, rate_result = asyncio.run(exercise())
    assert success_result == {"ok": True}
    assert isinstance(rate_result, RuntimeError)
    assert "429" in str(rate_result)
    assert client._circuit_state == "OPEN"
    assert client._circuit_open_until == pytest.approx(120.0)

    client._open_circuit("CONCURRENT_GENERIC_FAILURE", 30.0)
    assert client._circuit_open_until == pytest.approx(120.0)


def test_timeout_and_slow_consumer_fail_closed_without_unbounded_wait():
    request_failures: list[dict] = []

    async def never_returns(_endpoint, _params):
        await asyncio.sleep(1.0)
        return 200, {}, {}

    timeout_client = BatchedAlpacaPollingClient(
        breadth_symbols=["BTC/USD"],
        request_headers=CREDS,
        policy=_policy(request_timeout_seconds=0.01),
        request_json=never_returns,
        on_feed_truth=request_failures.append,
    )
    asyncio.run(timeout_client.poll_once())
    assert request_failures[-1]["reason_code"] == "REQUEST_TIMEOUT"

    callback_failures: list[dict] = []

    async def slow_callback(_value):
        await asyncio.sleep(0.1)

    async def success(endpoint, params):
        requested = str(params["symbols"]).split(",")
        return 200, {}, _snapshot_payload(requested)

    callback_client = BatchedAlpacaPollingClient(
        breadth_symbols=["BTC/USD"],
        request_headers=CREDS,
        policy=_policy(callback_timeout_seconds=0.01),
        request_json=success,
        on_breadth_snapshot=slow_callback,
        on_feed_truth=callback_failures.append,
    )
    asyncio.run(callback_client.poll_once())
    assert callback_client.get_stats()["metrics"]["callback_timeouts"] == 1
    assert callback_failures[-1]["status"] == "SLOW_CONSUMER"

    sync_failures: list[dict] = []

    def slow_sync_callback(_value):
        time.sleep(0.02)

    sync_callback_client = BatchedAlpacaPollingClient(
        breadth_symbols=["BTC/USD"],
        request_headers=CREDS,
        policy=_policy(callback_timeout_seconds=0.01),
        request_json=success,
        on_breadth_snapshot=slow_sync_callback,
        on_feed_truth=sync_failures.append,
    )
    asyncio.run(sync_callback_client.poll_once())
    assert sync_callback_client.get_stats()["metrics"]["callback_timeouts"] == 1
    assert sync_failures[-1]["status"] == "SLOW_CONSUMER"


def test_cancelled_poll_cycle_cancels_workers_and_releases_request_budget():
    request_started: asyncio.Event
    request_cancelled: asyncio.Event

    async def exercise():
        nonlocal request_started, request_cancelled
        request_started = asyncio.Event()
        request_cancelled = asyncio.Event()

        async def blocked_request(_endpoint, _params):
            request_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                request_cancelled.set()
                raise

        client = BatchedAlpacaPollingClient(
            breadth_symbols=["BTC/USD"],
            request_headers=CREDS,
            policy=_policy(request_timeout_seconds=10.0),
            request_json=blocked_request,
        )
        poll = asyncio.create_task(client.poll_once())
        await asyncio.wait_for(request_started.wait(), timeout=1.0)
        poll.cancel()
        await asyncio.gather(poll, return_exceptions=True)
        await asyncio.wait_for(request_cancelled.wait(), timeout=1.0)
        assert client._budget is not None
        assert client._budget.inflight == 0

    asyncio.run(exercise())


def test_cancelled_rate_waiter_cannot_decrement_another_requests_inflight_count():
    async def exercise():
        sleep_started = asyncio.Event()
        release_sleep = asyncio.Event()

        async def blocked_sleep(_delay: float):
            sleep_started.set()
            await release_sleep.wait()

        budget = _RequestBudget(
            _policy(max_concurrency=2, global_requests_per_minute=1, provider_requests_per_minute=1),
            monotonic=lambda: 10.0,
            sleep=blocked_sleep,
        )
        async with budget.slot("alpaca_crypto_rest"):
            assert budget.inflight == 1

            async def wait_for_slot():
                async with budget.slot("alpaca_crypto_rest"):
                    raise AssertionError("cancelled waiter entered the request slot")

            waiter = asyncio.create_task(wait_for_slot())
            await asyncio.wait_for(sleep_started.wait(), timeout=1.0)
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)
            assert budget.inflight == 1
        assert budget.inflight == 0

    asyncio.run(exercise())


def test_rest_timestamp_and_closed_bar_metadata_are_nanosecond_exact(monkeypatch):
    client = BatchedAlpacaPollingClient(
        breadth_symbols=["BTC/USD"],
        deep_symbols=["BTC/USD"],
        protected_symbols=["BTC/USD"],
        deep_poll_enabled=True,
        request_headers=CREDS,
        policy=_policy(),
        request_json=lambda *_args, **_kwargs: None,
    )
    event_ns = client._parse_iso8601_ns("2026-07-18T12:00:00.123456789Z")
    assert event_ns % 1_000_000_000 == 123_456_789
    received_ns = event_ns + 60_000_000_000
    raw = _snapshot_payload(["BTC/USD"], received_ns=received_ns)["snapshots"]["BTC/USD"]
    raw["minuteBar"]["t"] = "2026-07-18T12:00:00.123456789Z"

    import app.data.polling_client as polling_module

    monkeypatch.setattr(polling_module, "now_ns", lambda: received_ns)
    normalized = client._normalize_snapshot("BTC/USD", raw)
    candle = normalized["candle"]
    assert candle.candle_close_ts_ns == event_ns + 60_000_000_000
    assert candle.candle_closed_at_receive is True
    assert candle.candle_batch_received_ns == candle.candle_close_ts_ns

    monkeypatch.setattr(polling_module, "now_ns", lambda: event_ns + 59_999_999_999)
    with pytest.raises(ValueError, match="in_progress_minute_bar"):
        client._normalize_snapshot("BTC/USD", raw)
    with pytest.raises(ValueError, match="future_order_book"):
        client._normalize_order_book(
            "BTC/USD",
            _order_book_payload(["BTC/USD"], received_ns=event_ns + 1_000_000_000)["orderbooks"]["BTC/USD"],
            receive_ts_ns=event_ns - 1,
        )


def test_validator_uses_verified_bar_close_and_refuses_future_truth():
    validator = DataValidator(stale_threshold_seconds=10)
    start_ns = BASE_NS - 60_000_000_000
    candle = Candle(
        symbol="BTC/USD",
        exchange_ts_ns=start_ns,
        open=100,
        high=101,
        low=99,
        close=100,
        volume=1,
        timeframe="1m",
        candle_close_ts_ns=BASE_NS,
        candle_closed_at_receive=True,
    )
    assert validator.validate_candle(candle, BASE_NS + 9_000_000_000).is_valid is True

    inconsistent = candle.model_copy(update={"candle_close_ts_ns": BASE_NS + 1})
    assert "inconsistent" in str(validator.validate_candle(inconsistent, BASE_NS + 2).error)
    future = candle.model_copy(update={"exchange_ts_ns": BASE_NS + 1, "candle_close_ts_ns": BASE_NS + 60_000_000_001})
    assert "Future or in-progress" in str(validator.validate_candle(future, BASE_NS).error)

    book = OrderBookSnapshot(
        symbol="BTC/USD",
        exchange_ts_ns=BASE_NS + 1,
        receive_ts_ns=BASE_NS,
        bids=[(99.0, 1.0)],
        asks=[(101.0, 1.0)],
    )
    assert "Future order book" in str(validator.validate_order_book(book, BASE_NS).error)


def test_rest_fallback_requires_a_successful_protected_symbol_probe_before_activation():
    failures: list[dict] = []

    async def unavailable(_endpoint, _params):
        return 503, {}, {"message": "synthetic unavailable"}

    client = BatchedAlpacaPollingClient(
        breadth_symbols=["BTC/USD", "ETH/USD"],
        deep_symbols=["BTC/USD", "ETH/USD"],
        protected_symbols=["BTC/USD"],
        deep_poll_enabled=True,
        request_headers=CREDS,
        policy=_policy(),
        request_json=unavailable,
        on_feed_truth=failures.append,
    )

    with pytest.raises(RuntimeError, match="initial_probe_failed"):
        asyncio.run(client.start(require_initial_success=True))
    assert client.is_running is False
    assert client._task is None
    assert failures
    assert all(failure["executable_truth"] is False for failure in failures)


def test_rest_probe_refused_by_market_validator_cannot_activate():
    failures: list[dict] = []

    async def success(endpoint, params):
        requested = str(params["symbols"]).split(",")
        payload = _snapshot_payload(requested) if endpoint.endswith("/snapshots") else _order_book_payload(requested)
        return 200, {}, payload

    client = BatchedAlpacaPollingClient(
        breadth_symbols=["BTC/USD"],
        deep_symbols=["BTC/USD"],
        protected_symbols=["BTC/USD"],
        deep_poll_enabled=True,
        request_headers=CREDS,
        policy=_policy(),
        request_json=success,
        on_candle=lambda _candle: False,
        on_order_book=lambda _book: True,
        on_feed_truth=failures.append,
    )
    with pytest.raises(RuntimeError, match="initial_probe_failed"):
        asyncio.run(client.start(require_initial_success=True))
    assert any(item["status"] == "CALLBACK_REJECTED" for item in failures)
    assert client.is_running is False


def test_deep_updates_never_evict_protected_symbols_and_fail_when_capacity_is_impossible():
    symbols = ["BTC/USD", "ETH/USD", "SOL/USD", "LINK/USD"]
    client = BatchedAlpacaPollingClient(
        breadth_symbols=symbols,
        deep_symbols=["BTC/USD", "ETH/USD"],
        protected_symbols=["BTC/USD"],
        request_headers=CREDS,
        policy=_policy(),
        request_json=lambda *_args, **_kwargs: None,
    )
    selected = client.update_deep_symbols(
        ["SOL/USD", "LINK/USD", "ETH/USD"],
        protected_symbols=["BTC/USD", "ETH/USD"],
        limit=3,
    )
    assert selected == ("BTC/USD", "ETH/USD", "SOL/USD")
    with pytest.raises(ValueError, match="protected_deep_capacity_exceeded"):
        client.update_deep_symbols([], protected_symbols=["BTC/USD", "ETH/USD"], limit=1)


def test_initial_deep_allocation_reserves_capacity_for_every_protected_symbol():
    protected = {f"HELD{index:02d}/USD" for index in range(25)}
    entries = tuple(f"ENTRY{index:02d}/USD" for index in range(20))
    selected = main.resolve_initial_market_data_deep_symbols(
        protected_symbols=protected,
        entry_symbols=entries,
        primary_symbol=entries[0],
        candidate_limit=12,
        subscription_limit=30,
    )

    assert len(selected) == 30
    assert protected.issubset(selected)
    assert selected[-5:] == entries[:5]
    with pytest.raises(RuntimeError, match="PROTECTED_DEEP_CAPACITY_EXCEEDED"):
        main.resolve_initial_market_data_deep_symbols(
            protected_symbols=protected,
            entry_symbols=entries,
            primary_symbol=entries[0],
            candidate_limit=12,
            subscription_limit=24,
        )


def test_alpaca_websocket_parses_nanosecond_events_and_rejects_bad_market_truth():
    quotes: list[dict] = []
    books: list[object] = []
    client = AlpacaCryptoWebSocketClient(
        symbols=["BTC/USD"],
        key_id="key",
        secret_key="secret",
        on_quote=quotes.append,
        on_order_book=books.append,
    )
    receive_ns = client._parse_rfc3339_ns("2026-07-19T12:00:01.123456789Z")
    quote = [{"T": "q", "S": "BTC/USD", "t": "2026-07-19T12:00:00.123456789Z", "bp": 99, "ap": 101, "bs": 2, "as": 3}]
    book = [{"T": "o", "S": "BTC/USD", "t": "2026-07-19T12:00:00.223456789Z", "r": True, "b": [{"p": 99, "s": 2}], "a": [{"p": 101, "s": 3}]}]
    asyncio.run(client._process_message(json.dumps(quote), receive_ns))
    asyncio.run(client._process_message(json.dumps(quote), receive_ns + 1))
    asyncio.run(client._process_message(json.dumps(book), receive_ns + 1))

    assert quotes[0]["exchange_ts_ns"] % 1_000_000_000 == 123_456_789
    assert books[0].exchange_ts_ns % 1_000_000_000 == 223_456_789
    assert quotes[0]["provider_id"] == "alpaca_crypto_stream"
    assert quotes[0]["execution_location"] == "alpaca"
    assert client.get_feed_truth_status()["duplicate_events_rejected"] == 1

    crossed = [{"T": "q", "S": "BTC/USD", "t": "2026-07-19T12:00:00.323456789Z", "bp": 101, "ap": 100, "bs": 2, "as": 3}]
    with pytest.raises(ValueError, match="crossed_or_locked"):
        asyncio.run(client._process_message(json.dumps(crossed), receive_ns + 2))
    recovered = [{"T": "q", "S": "BTC/USD", "t": "2026-07-19T12:00:00.223456789Z", "bp": 99, "ap": 101, "bs": 2, "as": 3}]
    asyncio.run(client._process_message(json.dumps(recovered), receive_ns + 3))
    assert len(quotes) == 2
    nonfinite = [{"T": "q", "S": "BTC/USD", "t": "2026-07-19T12:00:00.423456789Z", "bp": "NaN", "ap": 101, "bs": 2, "as": 3}]
    with pytest.raises(ValueError, match="positive_finite"):
        asyncio.run(client._process_message(json.dumps(nonfinite), receive_ns + 4))
    boolean_price = [{"T": "q", "S": "BTC/USD", "t": "2026-07-19T12:00:00.523456789Z", "bp": True, "ap": 101, "bs": 2, "as": 3}]
    with pytest.raises(ValueError, match="numeric_required"):
        asyncio.run(client._process_message(json.dumps(boolean_price), receive_ns + 5))


def test_alpaca_websocket_normalizes_taker_side_for_existing_whale_flow_contract():
    trades: list[dict] = []
    client = AlpacaCryptoWebSocketClient(
        symbols=["BTC/USD"],
        key_id="key",
        secret_key="secret",
        on_trade=trades.append,
    )
    receive_ns = client._parse_rfc3339_ns("2026-07-19T12:00:03Z")
    buyer = [{"T": "t", "S": "BTC/USD", "t": "2026-07-19T12:00:01Z", "p": 100, "s": 2, "i": 1, "tks": "B"}]
    seller = [{"T": "t", "S": "BTC/USD", "t": "2026-07-19T12:00:02Z", "p": 101, "s": 3, "i": 2, "tks": "S"}]
    asyncio.run(client._process_message(json.dumps(buyer), receive_ns))
    asyncio.run(client._process_message(json.dumps(seller), receive_ns))

    assert [trade["side"] for trade in trades] == [1, -1]
    assert all(type(trade["side"]) is int for trade in trades)

    malformed = [{"T": "t", "S": "BTC/USD", "t": "2026-07-19T12:00:02.5Z", "p": 101, "s": 1, "i": 3, "tks": "?"}]
    with pytest.raises(ValueError, match="taker_side_invalid"):
        asyncio.run(client._process_message(json.dumps(malformed), receive_ns))


def test_alpaca_websocket_builds_bounded_stateful_book_from_reset_deltas_and_deletions():
    books: list[OrderBookSnapshot] = []
    client = AlpacaCryptoWebSocketClient(
        symbols=["BTC/USD"],
        key_id="key",
        secret_key="secret",
        on_order_book=books.append,
        order_book_level_limit=2,
    )
    receive_ns = client._parse_rfc3339_ns("2026-07-19T12:00:04Z")
    reset = [{
        "T": "o",
        "S": "BTC/USD",
        "t": "2026-07-19T12:00:01Z",
        "r": True,
        "b": [{"p": 99, "s": 2}, {"p": 98, "s": 1}],
        "a": [{"p": 101, "s": 3}, {"p": 102, "s": 1}],
    }]
    delta = [{
        "T": "o",
        "S": "BTC/USD",
        "t": "2026-07-19T12:00:02Z",
        "b": [{"p": 99, "s": 0}, {"p": 100, "s": 4}],
        "a": [],
    }]
    asyncio.run(client._process_message(json.dumps(reset), receive_ns))
    asyncio.run(client._process_message(json.dumps(delta), receive_ns))

    assert books[-1].bids == [(100.0, 4.0), (98.0, 1.0)]
    assert books[-1].asks == [(101.0, 3.0), (102.0, 1.0)]
    assert len(client._order_book_levels_by_symbol["BTC/USD"]["bids"]) <= 2
    assert len(client._order_book_levels_by_symbol["BTC/USD"]["asks"]) <= 2

    crossed = [{
        "T": "o",
        "S": "BTC/USD",
        "t": "2026-07-19T12:00:03Z",
        "b": [{"p": 102, "s": 1}],
        "a": [],
    }]
    with pytest.raises(ValueError, match="invalid_or_crossed"):
        asyncio.run(client._process_message(json.dumps(crossed), receive_ns))
    assert max(client._order_book_levels_by_symbol["BTC/USD"]["bids"]) == Decimal("100")

    no_reset = AlpacaCryptoWebSocketClient(
        symbols=["BTC/USD"],
        key_id="key",
        secret_key="secret",
        on_order_book=books.append,
    )
    with pytest.raises(ValueError, match="incremental_before_reset"):
        asyncio.run(no_reset._process_message(json.dumps(delta), receive_ns))


class _HandshakeWebSocket:
    def __init__(self, responses: list[object]):
        self.responses = [json.dumps(item) for item in responses]
        self.sent: list[dict] = []
        self.closed = False

    async def recv(self):
        if not self.responses:
            raise RuntimeError("synthetic_no_more_handshake_messages")
        return self.responses.pop(0)

    async def send(self, value):
        self.sent.append(json.loads(value))

    async def close(self):
        self.closed = True


def _subscription_ack(symbols: list[str]) -> dict:
    return {
        "T": "subscription",
        "trades": symbols,
        "quotes": symbols,
        "orderbooks": symbols,
        "bars": symbols,
        "updatedBars": [],
        "dailyBars": [],
    }


def test_alpaca_websocket_requires_official_greeting_auth_and_full_subscription_ack():
    socket = _HandshakeWebSocket(
        [
            [{"T": "success", "msg": "connected"}],
            [{"T": "success", "msg": "authenticated"}],
            [_subscription_ack(["BTC/USD"])],
        ]
    )
    truth: list[dict] = []

    async def connect_factory(*_args, **_kwargs):
        return socket

    client = AlpacaCryptoWebSocketClient(
        symbols=["BTC/USD"],
        key_id="key",
        secret_key="secret",
        connect_factory=connect_factory,
        on_feed_truth=truth.append,
    )

    async def exercise():
        assert await client.connect() is True
        assert client.is_connected is True
        assert client.get_feed_truth_status()["subscriptions"] == {
            "trades": ("BTC/USD",),
            "quotes": ("BTC/USD",),
            "orderbooks": ("BTC/USD",),
            "bars": ("BTC/USD",),
            "updatedBars": (),
            "dailyBars": (),
        }
        await client.stop()

    asyncio.run(exercise())
    assert [item["action"] for item in socket.sent] == ["auth", "subscribe"]
    assert truth[0]["status"] == "WEBSOCKET_ACTIVE"
    assert truth[0]["transport_active"] is True
    assert truth[0]["executable_truth"] is False
    assert socket.closed is True


def test_alpaca_websocket_preserves_market_event_delivered_with_initial_subscription_ack():
    event_ns = now_ns() - 1_000_000_000
    socket = _HandshakeWebSocket(
        [
            [{"T": "success", "msg": "connected"}],
            [{"T": "success", "msg": "authenticated"}],
            [
                _subscription_ack(["BTC/USD"]),
                {
                    "T": "q",
                    "S": "BTC/USD",
                    "t": _rfc3339_ns(event_ns),
                    "bp": 99,
                    "ap": 101,
                    "bs": 2,
                    "as": 3,
                },
            ],
        ]
    )
    quotes: list[dict] = []

    async def connect_factory(*_args, **_kwargs):
        return socket

    client = AlpacaCryptoWebSocketClient(
        symbols=["BTC/USD"],
        key_id="key",
        secret_key="secret",
        connect_factory=connect_factory,
        on_quote=quotes.append,
    )

    async def exercise():
        assert await client.connect() is True
        await client.stop()

    asyncio.run(exercise())
    assert [quote["symbol"] for quote in quotes] == ["BTC/USD"]


def test_alpaca_websocket_subscription_mismatch_never_becomes_active_and_closes_socket():
    socket = _HandshakeWebSocket(
        [
            [{"T": "success", "msg": "connected"}],
            [{"T": "success", "msg": "authenticated"}],
            [_subscription_ack([])],
        ]
    )
    truth: list[dict] = []

    async def connect_factory(*_args, **_kwargs):
        return socket

    client = AlpacaCryptoWebSocketClient(
        symbols=["BTC/USD"],
        key_id="key",
        secret_key="secret",
        connect_factory=connect_factory,
        on_feed_truth=truth.append,
    )
    assert asyncio.run(client.connect()) is False
    assert client.is_connected is False
    assert socket.closed is True
    assert truth[-1]["status"] == "WEBSOCKET_UNAVAILABLE"
    assert truth[-1]["executable_truth"] is False


def test_alpaca_websocket_subscription_ack_and_new_symbol_event_share_one_frame_safely():
    quotes: list[dict] = []
    socket = _HandshakeWebSocket([])
    client = AlpacaCryptoWebSocketClient(
        symbols=["BTC/USD"],
        key_id="key",
        secret_key="secret",
        on_quote=quotes.append,
    )
    client._websocket = socket
    client._connected = True
    client._authenticated = True
    client._subscriptions = {
        channel: (("BTC/USD",) if channel in {"trades", "quotes", "orderbooks", "bars"} else ())
        for channel in ("trades", "quotes", "orderbooks", "bars", "updatedBars", "dailyBars")
    }

    async def exercise():
        update = asyncio.create_task(client.update_symbols(["BTC/USD", "ETH/USD"]))
        while client._subscription_waiter is None:
            await asyncio.sleep(0)
        receive_ns = client._parse_rfc3339_ns("2026-07-19T12:00:01Z")
        await client._process_message(
            json.dumps(
                [
                    _subscription_ack(["BTC/USD", "ETH/USD"]),
                    {
                        "T": "q",
                        "S": "ETH/USD",
                        "t": "2026-07-19T12:00:00Z",
                        "bp": 99,
                        "ap": 101,
                        "bs": 2,
                        "as": 3,
                    },
                ]
            ),
            receive_ns,
        )
        assert await update == ("BTC/USD", "ETH/USD")

    asyncio.run(exercise())
    assert [item["symbol"] for item in quotes] == ["ETH/USD"]
    assert client.symbols == ("BTC/USD", "ETH/USD")


def test_alpaca_websocket_drops_only_known_removed_symbol_race_during_subscription_change():
    quotes: list[dict] = []
    socket = _HandshakeWebSocket([])
    client = AlpacaCryptoWebSocketClient(
        symbols=["BTC/USD", "ETH/USD"],
        key_id="key",
        secret_key="secret",
        on_quote=quotes.append,
    )
    client._websocket = socket
    client._connected = True
    client._authenticated = True
    client._subscriptions = {
        channel: (("BTC/USD", "ETH/USD") if channel in {"trades", "quotes", "orderbooks", "bars"} else ())
        for channel in ("trades", "quotes", "orderbooks", "bars", "updatedBars", "dailyBars")
    }

    async def exercise():
        update = asyncio.create_task(client.update_symbols(["BTC/USD"]))
        while client._subscription_waiter is None:
            await asyncio.sleep(0)
        receive_ns = client._parse_rfc3339_ns("2026-07-19T12:00:01Z")
        removed_inflight = {
            "T": "q",
            "S": "ETH/USD",
            "t": "2026-07-19T12:00:00Z",
            "bp": 99,
            "ap": 101,
            "bs": 2,
            "as": 3,
        }
        await client._process_message([removed_inflight], receive_ns)
        with pytest.raises(ValueError, match="alpaca_websocket_unsubscribed_symbol"):
            await client._process_message(
                [{**removed_inflight, "S": "SOL/USD"}],
                receive_ns,
            )
        await client._process_message([_subscription_ack(["BTC/USD"])], receive_ns)
        assert await update == ("BTC/USD",)

    asyncio.run(exercise())
    assert quotes == []
    assert client.symbols == ("BTC/USD",)
    assert client.get_feed_truth_status()["subscription_transition_events_dropped"] == 1


def test_alpaca_websocket_failed_subscription_ack_invalidates_transport_once():
    truth: list[dict] = []
    socket = _HandshakeWebSocket([])
    client = AlpacaCryptoWebSocketClient(
        symbols=["BTC/USD"],
        key_id="key",
        secret_key="secret",
        on_feed_truth=truth.append,
        ping_timeout=1,
    )
    client._websocket = socket
    client._connected = True
    client._authenticated = True

    async def exercise():
        update = asyncio.create_task(client.update_symbols(["BTC/USD", "ETH/USD"]))
        while client._subscription_waiter is None:
            await asyncio.sleep(0)
        await client._process_message(json.dumps([_subscription_ack(["BTC/USD"])]), now_ns())
        with pytest.raises(RuntimeError, match="subscription_ack_mismatch"):
            await update
        assert client.is_connected is False
        await client._emit_truth(
            "MALFORMED_WEBSOCKET_PAYLOAD",
            exc=ValueError("second terminal path"),
            executable_truth=False,
        )

    asyncio.run(exercise())
    assert [item["status"] for item in truth] == ["WEBSOCKET_SUBSCRIPTION_FAILED"]


def test_alpaca_websocket_orders_per_channel_and_refuses_future_or_same_channel_regression():
    quotes: list[dict] = []
    candles: list[Candle] = []
    client = AlpacaCryptoWebSocketClient(
        symbols=["BTC/USD"],
        key_id="key",
        secret_key="secret",
        on_quote=quotes.append,
        on_candle=candles.append,
    )
    current_quote = [{"T": "q", "S": "BTC/USD", "t": "2026-07-19T12:00:30Z", "bp": 99, "ap": 101, "bs": 2, "as": 3}]
    older_closed_bar = [{"T": "b", "S": "BTC/USD", "t": "2026-07-19T11:59:00Z", "o": 99, "h": 101, "l": 98, "c": 100, "v": 5}]
    older_quote = [{"T": "q", "S": "BTC/USD", "t": "2026-07-19T12:00:25Z", "bp": 99, "ap": 101, "bs": 2, "as": 3}]
    future_quote = [{"T": "q", "S": "BTC/USD", "t": "2030-07-19T12:00:40Z", "bp": 99, "ap": 101, "bs": 2, "as": 3}]

    receive_ns = client._parse_rfc3339_ns("2026-07-19T12:00:31Z")
    asyncio.run(client._process_message(json.dumps(current_quote), receive_ns))
    asyncio.run(client._process_message(json.dumps(older_closed_bar), receive_ns + 1))
    with pytest.raises(ValueError, match="out_of_order_event"):
        asyncio.run(client._process_message(json.dumps(older_quote), receive_ns + 2))
    with pytest.raises(ValueError, match="future_event"):
        asyncio.run(client._process_message(json.dumps(future_quote), receive_ns + 3))

    assert len(quotes) == 1
    assert len(candles) == 1
    assert candles[0].candle_close_ts_ns == client._parse_rfc3339_ns("2026-07-19T12:00:00Z")


def test_alpaca_websocket_market_validator_refusal_propagates_to_transport():
    client = AlpacaCryptoWebSocketClient(
        symbols=["BTC/USD"],
        key_id="key",
        secret_key="secret",
        on_quote=lambda _quote: False,
    )
    quote = [{"T": "q", "S": "BTC/USD", "t": "2026-07-19T12:00:00Z", "bp": 99, "ap": 101, "bs": 2, "as": 3}]
    with pytest.raises(ValueError, match="callback_rejected"):
        asyncio.run(
            client._process_message(
                json.dumps(quote),
                client._parse_rfc3339_ns("2026-07-19T12:00:01Z"),
            )
        )
    assert client._last_event_time_ns_by_channel_symbol == {}


def test_alpaca_websocket_slow_consumer_and_queue_are_bounded_and_secret_safe():
    truth: list[dict] = []

    async def slow_quote(_value):
        await asyncio.sleep(0.1)

    client = AlpacaCryptoWebSocketClient(
        symbols=["BTC/USD"],
        key_id="private-key",
        secret_key="private-secret",
        on_quote=slow_quote,
        on_feed_truth=truth.append,
        max_queue_size=1,
        callback_timeout_seconds=0.01,
    )

    async def exercise():
        client._running = True
        worker = asyncio.create_task(client._process_queue())
        await client._message_queue.put(
            (
                json.dumps([{"T": "q", "S": "BTC/USD", "t": "2026-07-19T12:00:00.123456789Z", "bp": 99, "ap": 101, "bs": 2, "as": 3}]),
                client._parse_rfc3339_ns("2026-07-19T12:00:01.123456789Z"),
            )
        )
        async def wait_for_truth():
            while not truth:
                await asyncio.sleep(0.005)

        await asyncio.wait_for(wait_for_truth(), timeout=1.0)
        client._running = False
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)

    asyncio.run(exercise())
    assert truth[-1]["status"] == "WEBSOCKET_SLOW_CONSUMER"
    status = client.get_feed_truth_status()
    assert status["queue_high_water"] <= 1
    rendered = json.dumps(status, sort_keys=True)
    assert "private-key" not in rendered
    assert "private-secret" not in rendered


def test_alpaca_websocket_backpressure_emits_once_and_terminates_receive_authority():
    truth: list[dict] = []

    class ReceiveSocket:
        def __init__(self):
            self.messages = ["first", "second", "third"]
            self.closed = False

        async def recv(self):
            return self.messages.pop(0)

        async def close(self):
            self.closed = True

    client = AlpacaCryptoWebSocketClient(
        symbols=["BTC/USD"],
        key_id="key",
        secret_key="secret",
        on_feed_truth=truth.append,
        max_queue_size=1,
    )
    socket = ReceiveSocket()

    async def exercise():
        client._websocket = socket
        client._running = True
        client._connected = True
        client._authenticated = True
        await client._receive_messages()
        assert client._message_queue.qsize() == 1
        assert client.is_connected is False
        await client.stop()

    asyncio.run(exercise())
    assert [item["status"] for item in truth] == ["WEBSOCKET_BACKPRESSURE"]
    assert client.get_feed_truth_status()["queue_drops"] == 1
    assert socket.closed is True


class _FakePolling:
    def __init__(self, events: list[str], **kwargs):
        self.events = events
        self.kwargs = kwargs
        self.label = "rest" if kwargs.get("deep_poll_enabled") else "breadth"
        self.is_running = False
        self.deep_symbols = tuple(kwargs.get("deep_symbols") or ())
        self.fail_start = False

    async def start(self, *, require_initial_success: bool = False):
        self.is_running = True
        if self.label == "rest":
            assert require_initial_success is True
        self.events.append(f"{self.label}:start")
        if self.fail_start:
            raise RuntimeError("synthetic_rest_probe_failure")

    async def stop(self):
        self.is_running = False
        self.events.append(f"{self.label}:stop")

    def update_deep_symbols(self, candidates, *, protected_symbols, limit):
        assert len(protected_symbols) <= limit
        self.deep_symbols = tuple(candidates)
        return self.deep_symbols

    def get_stats(self):
        return {"running": self.is_running, "label": self.label}


class _FakeWebSocket:
    def __init__(
        self,
        events: list[str],
        *,
        fail_start: bool = False,
        emit_failure_on_start: bool = False,
        **kwargs,
    ):
        self.events = events
        self.kwargs = kwargs
        self.fail_start = fail_start
        self.emit_failure_on_start = emit_failure_on_start
        self._connected = False
        self.symbols = tuple(kwargs.get("symbols") or ())

    async def start(self):
        self.events.append("stream:start")
        if self.fail_start:
            raise RuntimeError("synthetic_stream_failure")
        self._connected = True
        if self.emit_failure_on_start:
            self._connected = False
            await self.kwargs["on_feed_truth"](
                {
                    "status": "WEBSOCKET_UNAVAILABLE",
                    "exception_type": "ConnectionError",
                    "executable_truth": False,
                }
            )

    async def stop(self):
        self._connected = False
        self.events.append("stream:stop")

    async def update_symbols(self, symbols):
        self.symbols = tuple(symbols)
        return self.symbols

    def get_feed_truth_status(self):
        return {"status": "WEBSOCKET_ACTIVE" if self._connected else "WEBSOCKET_INACTIVE"}


def _market_config(symbols: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        symbol_universe=symbols,
        crypto_market_data_providers=[
            "alpaca_crypto_stream",
            "alpaca_crypto_rest",
            "coinbase_public",
            "kraken_public",
        ],
        data=DataConfig(
            max_candles_per_symbol=100,
            market_data_batch_size=10,
            market_data_max_concurrency=2,
            market_data_global_requests_per_minute=100,
            market_data_provider_requests_per_minute=100,
            market_data_job_queue_size=8,
            market_data_failure_history_size=10,
            market_data_observations_per_symbol=10,
            market_data_deep_candidate_limit=2,
            market_data_deep_subscription_limit=5,
        ),
        risk=SimpleNamespace(stale_data_threshold_seconds=60),
    )


def _market_feeds(
    *,
    fail_stream: bool = False,
    fail_rest: bool = False,
    stream_fails_during_activation: bool = False,
):
    symbols = ["BTC/USD", "ETH/USD", "SOL/USD"]
    events: list[str] = []
    polling: list[_FakePolling] = []
    sockets: list[_FakeWebSocket] = []
    router = build_feed_provider_router(
        configured_provider_ids=("alpaca_crypto_stream", "alpaca_crypto_rest", "coinbase_public", "kraken_public"),
        env=CREDS,
    )

    def polling_factory(**kwargs):
        instance = _FakePolling(events, **kwargs)
        instance.fail_start = bool(fail_rest and instance.label == "rest")
        polling.append(instance)
        return instance

    def websocket_factory(**kwargs):
        instance = _FakeWebSocket(
            events,
            fail_start=fail_stream,
            emit_failure_on_start=stream_fails_during_activation,
            **kwargs,
        )
        sockets.append(instance)
        return instance

    feeds = MarketFeeds(
        _market_config(symbols),
        symbols=symbols,
        deep_symbols=symbols,
        protected_symbols=["BTC/USD"],
        env=CREDS,
        feed_provider_router=router,
        alpaca_polling_factory=polling_factory,
        alpaca_websocket_factory=websocket_factory,
    )
    return feeds, events, polling, sockets


def test_real_batched_rest_fallback_probe_activates_only_with_current_protected_truth(monkeypatch):
    current_ns = [BASE_NS + 1_000_000_000]
    requests: list[str] = []
    activation_sequence: list[str] = []

    import app.data.market_feeds as market_feeds_module
    import app.data.polling_client as polling_module

    monkeypatch.setattr(market_feeds_module, "now_ns", lambda: current_ns[0])
    monkeypatch.setattr(polling_module, "now_ns", lambda: current_ns[0])

    async def request_json(endpoint, params):
        requests.append(endpoint)
        requested = tuple(str(params["symbols"]).split(","))
        payload = (
            _snapshot_payload(requested, received_ns=current_ns[0])
            if endpoint.endswith("/snapshots")
            else _order_book_payload(requested, received_ns=current_ns[0])
        )
        return 200, {}, payload

    def polling_factory(**kwargs):
        return BatchedAlpacaPollingClient(**kwargs, request_json=request_json)

    class FailingStream:
        async def start(self):
            raise RuntimeError("synthetic_stream_unavailable")

        async def stop(self):
            return None

    config = _market_config(["BTC/USD", "ETH/USD"])
    config.risk = SimpleNamespace(stale_data_threshold_seconds=10)
    feeds = MarketFeeds(
        config,
        symbols=["BTC/USD", "ETH/USD"],
        deep_symbols=["BTC/USD"],
        protected_symbols=["BTC/USD"],
        env=CREDS,
        alpaca_polling_factory=polling_factory,
        alpaca_websocket_factory=lambda **_kwargs: FailingStream(),
    )
    feeds.register_order_book_callback(
        lambda book: activation_sequence.append(f"book:{book.symbol}")
    )
    feeds.register_candle_callback(
        lambda candle: activation_sequence.append(f"candle:{candle.symbol}")
    )
    feeds.register_transport_truth_callback(
        lambda truth: activation_sequence.append("truth:executable")
        if truth.get("executable_truth") is True
        else None
    )

    async def exercise():
        await feeds.start()
        status = feeds.get_feed_truth_status()
        assert status["active_provider_id"] == "alpaca_crypto_rest"
        assert status["executable_truth"] is True
        assert status["transport_truth"]["executable_truth"] is True
        assert status["transport_truth"]["status"] == "EXECUTABLE_MARKET_TRUTH_ACTIVE"
        assert feeds.get_last_candle("BTC/USD") is not None
        assert feeds.get_order_book("BTC/USD") is not None
        assert activation_sequence[:3] == [
            "book:BTC/USD",
            "candle:BTC/USD",
            "truth:executable",
        ]

        current_ns[0] += 12_000_000_000
        stale_status = feeds.get_feed_truth_status()
        assert stale_status["executable_truth"] is False
        assert stale_status["transport_truth"]["executable_truth"] is False
        assert "STALE_ORDER_BOOK_TRUTH:BTC/USD" in stale_status["missing_truth"]
        await feeds.stop()

    asyncio.run(exercise())
    assert any(endpoint.endswith("/snapshots") for endpoint in requests)
    assert any(endpoint.endswith("/latest/orderbooks") for endpoint in requests)


def test_rest_probe_consumer_rejection_aborts_activation_without_executable_truth(monkeypatch):
    current_ns = BASE_NS + 1_000_000_000
    truth_events: list[dict] = []
    callback_sequence: list[str] = []

    import app.data.market_feeds as market_feeds_module
    import app.data.polling_client as polling_module

    monkeypatch.setattr(market_feeds_module, "now_ns", lambda: current_ns)
    monkeypatch.setattr(polling_module, "now_ns", lambda: current_ns)

    async def request_json(endpoint, params):
        requested = tuple(str(params["symbols"]).split(","))
        payload = (
            _snapshot_payload(requested, received_ns=current_ns)
            if endpoint.endswith("/snapshots")
            else _order_book_payload(requested, received_ns=current_ns)
        )
        return 200, {}, payload

    def polling_factory(**kwargs):
        return BatchedAlpacaPollingClient(**kwargs, request_json=request_json)

    class FailingStream:
        async def start(self):
            raise RuntimeError("synthetic_stream_unavailable")

        async def stop(self):
            return None

    config = _market_config(["BTC/USD"])
    config.risk = SimpleNamespace(stale_data_threshold_seconds=10)
    feeds = MarketFeeds(
        config,
        symbols=["BTC/USD"],
        deep_symbols=["BTC/USD"],
        protected_symbols=["BTC/USD"],
        env=CREDS,
        alpaca_polling_factory=polling_factory,
        alpaca_websocket_factory=lambda **_kwargs: FailingStream(),
    )
    feeds.register_order_book_callback(
        lambda book: callback_sequence.append(f"book:{book.symbol}")
    )

    def reject_candle(candle):
        callback_sequence.append(f"candle:{candle.symbol}")
        return False

    feeds.register_candle_callback(reject_candle)
    feeds.register_transport_truth_callback(truth_events.append)

    async def exercise():
        with pytest.raises(RuntimeError, match="selected_market_data_transport_unavailable"):
            await feeds.start()
        status = feeds.get_feed_truth_status()
        assert status["status"] == "FAILED_CLOSED"
        assert status["executable_truth"] is False
        await feeds.stop()

    asyncio.run(exercise())
    assert callback_sequence == ["book:BTC/USD", "candle:BTC/USD"]
    assert not any(event.get("executable_truth") is True for event in truth_events)


def test_stream_breadth_rest_diagnostics_cannot_overwrite_active_provider_truth():
    feeds, _events, polling, _sockets = _market_feeds()

    async def exercise():
        await feeds.start()
        before = copy.deepcopy(feeds._transport_truth)
        breadth = next(item for item in polling if item.label == "breadth")
        await breadth.kwargs["on_feed_truth"](
            {
                "status": "SNAPSHOT_BATCH_FAILED",
                "provider_id": "alpaca_crypto_rest",
                "exception_type": "TimeoutError",
                "executable_truth": False,
            }
        )
        assert feeds._active_provider_id == "alpaca_crypto_stream"
        assert feeds._transport_truth == before
        assert feeds._failover_task is None
        await feeds.stop()

    asyncio.run(exercise())


def test_initial_stream_activation_failure_stops_old_clients_before_rest_fallback():
    feeds, events, polling, sockets = _market_feeds(fail_stream=True)

    async def exercise():
        await feeds.start()
        assert feeds.get_feed_truth_status()["active_provider_id"] == "alpaca_crypto_rest"
        await feeds.stop()

    asyncio.run(exercise())
    assert len(sockets) == 1
    assert len(polling) == 2
    assert events.index("stream:stop") < events.index("rest:start")
    assert events.index("breadth:stop") < events.index("rest:start")


def test_stream_failure_emitted_during_activation_cannot_be_resurrected_as_active():
    feeds, events, polling, sockets = _market_feeds(stream_fails_during_activation=True)

    async def exercise():
        await feeds.start()
        assert feeds.get_feed_truth_status()["active_provider_id"] == "alpaca_crypto_rest"
        await feeds.stop()

    asyncio.run(exercise())
    assert len(sockets) == 1
    assert len(polling) == 2
    assert events.index("stream:stop") < events.index("rest:start")


def test_initial_stream_and_rest_activation_failures_accumulate_and_leave_no_selected_provider():
    feeds, _events, _polling, _sockets = _market_feeds(fail_stream=True, fail_rest=True)
    truth_events: list[dict] = []
    feeds.register_transport_truth_callback(truth_events.append)

    async def exercise():
        with pytest.raises(RuntimeError, match="selected_market_data_transport_unavailable"):
            await feeds.start()
        status = feeds.get_feed_truth_status()
        assert status["status"] == "FAILED_CLOSED"
        assert status["active_provider_id"] is None
        assert status["provider_selection"]["selected_provider"] is None
        assert set(status["provider_runtime_status"]) == {"alpaca_crypto_stream", "alpaca_crypto_rest"}
        await feeds.stop()

    asyncio.run(exercise())
    assert truth_events[-1]["status"] == "FAILED_CLOSED"
    assert truth_events[-1]["selected_provider_id"] is None
    assert truth_events[-1]["executable_truth"] is False


def test_runtime_transport_failure_switches_to_rest_then_fails_closed_without_cross_venue():
    feeds, events, polling, sockets = _market_feeds()

    async def exercise():
        await feeds.start()
        stream = sockets[0]
        await stream.kwargs["on_feed_truth"](
            {"status": "WEBSOCKET_UNAVAILABLE", "exception_type": "ConnectionError", "executable_truth": False}
        )
        await asyncio.wait_for(feeds._failover_task, timeout=1.0)
        assert feeds.get_feed_truth_status()["active_provider_id"] == "alpaca_crypto_rest"
        rest = next(item for item in polling if item.label == "rest")
        await rest.kwargs["on_feed_truth"](
            {"status": "SNAPSHOT_BATCH_FAILED", "exception_type": "TimeoutError", "executable_truth": False}
        )
        await asyncio.wait_for(feeds._failover_task, timeout=1.0)
        status = feeds.get_feed_truth_status()
        assert status["status"] == "FAILED_CLOSED"
        assert status["executable_truth"] is False
        assert status["active_provider_id"] is None
        await feeds.stop()

    asyncio.run(exercise())
    assert events.index("stream:stop") < events.index("rest:start")


def test_stale_transport_generation_and_observe_only_candidate_never_reach_execution_callbacks():
    feeds, _events, _polling, _sockets = _market_feeds()
    received: list[str] = []
    feeds.register_candle_callback(lambda candle: received.append(candle.symbol))
    feeds._execution_truth_active = True
    feeds._execution_consumer_seeded = True
    feeds._active_provider_id = "alpaca_crypto_stream"
    feeds._active_transport_generation = 9
    timestamp = now_ns()
    btc = Candle(symbol="BTC/USD", exchange_ts_ns=timestamp, open=100, high=101, low=99, close=100, volume=1)
    eth = Candle(symbol="ETH/USD", exchange_ts_ns=timestamp, open=100, high=101, low=99, close=100, volume=1)
    feeds.candles.add_candle(btc)
    feeds.order_books["BTC/USD"] = OrderBookSnapshot(
        symbol="BTC/USD",
        exchange_ts_ns=timestamp,
        receive_ts_ns=timestamp,
        bids=[(99.0, 1.0)],
        asks=[(101.0, 1.0)],
    )

    async def exercise():
        await feeds._on_transport_candle(btc, 8, "alpaca_crypto_stream")
        await feeds._on_transport_candle(eth, 9, "alpaca_crypto_stream")
        await feeds._on_transport_candle(btc, 9, "alpaca_crypto_stream")

    asyncio.run(exercise())
    assert received == ["BTC/USD"]
    assert feeds.get_last_candle("ETH/USD") is not None


def test_invalid_observe_only_deep_events_are_isolated_from_protected_truth():
    feeds, _events, _polling, _sockets = _market_feeds()
    feeds._execution_truth_active = True
    feeds._execution_consumer_seeded = True
    feeds._active_provider_id = "alpaca_crypto_stream"
    feeds._active_transport_generation = 9
    feeds._transport_state = "ACTIVE"
    current_ns = now_ns()
    feeds.candles.add_candle(
        Candle(
            symbol="BTC/USD",
            exchange_ts_ns=current_ns,
            open=100,
            high=101,
            low=99,
            close=100,
            volume=1,
        )
    )
    feeds.order_books["BTC/USD"] = OrderBookSnapshot(
        symbol="BTC/USD",
        exchange_ts_ns=current_ns,
        receive_ts_ns=current_ns,
        bids=[(99.0, 1.0)],
        asks=[(101.0, 1.0)],
    )
    invalid_candle = Candle(
        symbol="ETH/USD",
        exchange_ts_ns=current_ns + 60_000_000_000,
        open=100,
        high=101,
        low=99,
        close=100,
        volume=1,
    )
    invalid_book = OrderBookSnapshot(
        symbol="ETH/USD",
        exchange_ts_ns=current_ns + 60_000_000_000,
        receive_ts_ns=current_ns,
        bids=[(99.0, 1.0)],
        asks=[(101.0, 1.0)],
    )

    async def exercise():
        for _ in range(12):
            assert await feeds._on_transport_candle(
                invalid_candle,
                9,
                "alpaca_crypto_stream",
            ) is True
        assert await feeds._on_transport_order_book(
            invalid_book,
            9,
            "alpaca_crypto_stream",
        ) is True

    asyncio.run(exercise())
    status = feeds.get_feed_truth_status()
    assert status["executable_truth"] is True
    assert feeds.get_last_candle("ETH/USD") is None
    assert feeds.get_order_book("ETH/USD") is None
    assert len(status["observe_only_rejections"]) == 10
    assert {item["reason"] for item in status["observe_only_rejections"]} == {
        "CANDLE_VALIDATION_REJECTED",
        "ORDER_BOOK_VALIDATION_REJECTED",
    }
    assert all(item["execution_authorized"] is False for item in status["observe_only_rejections"])


def test_invalid_protected_event_still_revokes_executable_truth():
    feeds, _events, _polling, _sockets = _market_feeds()
    truth_events: list[dict] = []
    feeds.register_transport_truth_callback(truth_events.append)
    feeds._execution_truth_active = True
    feeds._active_provider_id = "alpaca_crypto_stream"
    feeds._active_transport_generation = 9
    feeds._transport_state = "ACTIVE"
    current_ns = now_ns()
    invalid = OrderBookSnapshot(
        symbol="BTC/USD",
        exchange_ts_ns=current_ns + 60_000_000_000,
        receive_ts_ns=current_ns,
        bids=[(99.0, 1.0)],
        asks=[(101.0, 1.0)],
    )

    assert asyncio.run(
        feeds._on_transport_order_book(invalid, 9, "alpaca_crypto_stream")
    ) is False
    assert feeds._execution_truth_active is False
    assert feeds._transport_truth["reason"] == "EXECUTION_CONSUMER_REJECTED"
    assert truth_events[-1]["status"] == "EXECUTION_CONSUMER_REJECTED"
    assert truth_events[-1]["executable_truth"] is False
    assert tuple(feeds._observe_only_rejections) == ()


def test_stream_callbacks_wait_for_complete_protected_truth_before_dispatch():
    feeds, _events, _polling, sockets = _market_feeds()
    candles: list[str] = []
    books: list[str] = []
    trades: list[str] = []
    feeds.register_candle_callback(lambda candle: candles.append(candle.symbol))
    feeds.register_order_book_callback(lambda book: books.append(book.symbol))
    feeds.register_trade_callback(lambda trade: trades.append(trade["symbol"]))

    async def exercise():
        await feeds.start()
        stream = sockets[0]
        generation = feeds._active_transport_generation
        current_ns = now_ns()
        minute_ns = 60_000_000_000
        candle = Candle(
            symbol="BTC/USD",
            exchange_ts_ns=(current_ns // minute_ns - 1) * minute_ns,
            open=100,
            high=101,
            low=99,
            close=100,
            volume=1,
            timeframe="1m",
            candle_close_ts_ns=(current_ns // minute_ns) * minute_ns,
            candle_closed_at_receive=True,
            candle_batch_received_ns=current_ns,
            provider_id="alpaca_crypto_stream",
        )
        first_book = OrderBookSnapshot(
            symbol="BTC/USD",
            exchange_ts_ns=current_ns - 1_000_000_000,
            receive_ts_ns=current_ns,
            bids=[(99.0, 1.0)],
            asks=[(101.0, 1.0)],
        )
        trade = {
            "symbol": "BTC/USD",
            "price": 100.0,
            "volume": 1.0,
            "side": 1,
            "exchange_ts_ns": current_ns,
            "receive_ts_ns": current_ns,
        }

        assert await stream.kwargs["on_trade"](trade) is True
        assert await stream.kwargs["on_candle"](candle) is True
        assert candles == []
        assert trades == []
        assert feeds.get_feed_truth_status()["executable_truth"] is False
        assert await stream.kwargs["on_order_book"](first_book) is True
        assert books == ["BTC/USD"]
        assert candles == ["BTC/USD"]
        assert feeds.get_feed_truth_status()["executable_truth"] is True
        assert await feeds._on_transport_trade(trade, generation, "alpaca_crypto_stream") is True
        second_book = first_book.model_copy(update={"exchange_ts_ns": current_ns})
        assert await feeds._on_transport_order_book(second_book, generation, "alpaca_crypto_stream") is True
        assert trades == ["BTC/USD"]
        assert books == ["BTC/USD", "BTC/USD"]
        await feeds.stop()

    asyncio.run(exercise())


def test_seeded_consumer_keeps_fresh_book_and_trade_observation_when_candle_gate_is_stale(monkeypatch):
    feeds, _events, _polling, sockets = _market_feeds()
    feeds.validator.stale_threshold_seconds = 10
    candles: list[str] = []
    books: list[int] = []
    trades: list[int] = []
    feeds.register_candle_callback(lambda candle: candles.append(candle.symbol))
    feeds.register_order_book_callback(lambda book: books.append(book.exchange_ts_ns))
    feeds.register_trade_callback(lambda trade: trades.append(trade["exchange_ts_ns"]))

    current_ns = [BASE_NS]
    import app.data.market_feeds as market_feeds_module

    monkeypatch.setattr(market_feeds_module, "now_ns", lambda: current_ns[0])

    async def exercise():
        await feeds.start()
        stream = sockets[0]
        generation = feeds._active_transport_generation
        candle_start_ns = BASE_NS - 60_000_000_000
        candle = Candle(
            symbol="BTC/USD",
            exchange_ts_ns=candle_start_ns,
            open=100,
            high=101,
            low=99,
            close=100,
            volume=1,
            timeframe="1m",
            candle_close_ts_ns=BASE_NS,
            candle_closed_at_receive=True,
            candle_batch_received_ns=BASE_NS,
            candle_freshness_policy_ms=60_000.0,
            provider_id="alpaca_crypto_stream",
        )
        first_book = OrderBookSnapshot(
            symbol="BTC/USD",
            exchange_ts_ns=BASE_NS,
            receive_ts_ns=BASE_NS,
            bids=[(99.0, 1.0)],
            asks=[(101.0, 1.0)],
        )
        assert await stream.kwargs["on_candle"](candle) is True
        assert await stream.kwargs["on_order_book"](first_book) is True
        assert feeds._execution_consumer_seeded is True
        assert feeds.get_feed_truth_status()["executable_truth"] is True

        current_ns[0] += 11_000_000_000
        next_book = first_book.model_copy(
            update={
                "exchange_ts_ns": current_ns[0],
                "receive_ts_ns": current_ns[0],
            }
        )
        trade = {
            "symbol": "BTC/USD",
            "price": 100.0,
            "volume": 1.0,
            "side": 1,
            "exchange_ts_ns": current_ns[0],
            "receive_ts_ns": current_ns[0],
        }
        assert await feeds._on_transport_order_book(
            next_book,
            generation,
            "alpaca_crypto_stream",
        ) is True
        assert await feeds._on_transport_trade(
            trade,
            generation,
            "alpaca_crypto_stream",
        ) is True
        status = feeds.get_feed_truth_status()
        assert status["executable_truth"] is False
        assert status["execution_consumer_seeded"] is True
        assert status["missing_truth"] == ("STALE_MARKET_TRUTH:BTC/USD",)

        current_ns[0] = BASE_NS + 60_000_000_000
        recovery_book = first_book.model_copy(
            update={
                "exchange_ts_ns": current_ns[0],
                "receive_ts_ns": current_ns[0],
            }
        )
        recovery_candle = candle.model_copy(
            update={
                "exchange_ts_ns": BASE_NS,
                "candle_close_ts_ns": current_ns[0],
                "candle_batch_received_ns": current_ns[0],
            }
        )
        assert await feeds._on_transport_order_book(
            recovery_book,
            generation,
            "alpaca_crypto_stream",
        ) is True
        assert await feeds._on_transport_candle(
            recovery_candle,
            generation,
            "alpaca_crypto_stream",
        ) is True
        assert feeds.get_feed_truth_status()["executable_truth"] is True
        await feeds.stop()

    asyncio.run(exercise())
    assert candles == ["BTC/USD", "BTC/USD"]
    assert books == [BASE_NS, BASE_NS + 11_000_000_000, BASE_NS + 60_000_000_000]
    assert trades == [BASE_NS + 11_000_000_000]


def test_activation_probe_is_cached_without_execution_notification_and_old_generation_is_purged():
    feeds, _events, _polling, _sockets = _market_feeds()
    received: list[str] = []
    feeds.register_candle_callback(lambda candle: received.append(candle.symbol))
    feeds._active_provider_id = "alpaca_crypto_rest"
    feeds._active_transport_generation = 7
    feeds._transport_state = "ACTIVATING"
    feeds._execution_truth_active = False
    source_ns = now_ns() - 1_000_000_000
    candle = Candle(symbol="BTC/USD", exchange_ts_ns=source_ns, open=100, high=101, low=99, close=100, volume=1)
    book = OrderBookSnapshot(
        symbol="BTC/USD",
        exchange_ts_ns=source_ns,
        receive_ts_ns=source_ns + 1,
        bids=[(99.0, 1.0)],
        asks=[(101.0, 1.0)],
    )

    async def exercise():
        await feeds._on_transport_candle(candle, 7, "alpaca_crypto_rest")
        await feeds._on_transport_order_book(book, 7, "alpaca_crypto_rest")
        assert feeds.get_last_candle("BTC/USD") is candle
        assert feeds.get_order_book("BTC/USD") is book
        assert received == []
        await feeds._on_transport_candle(candle.model_copy(update={"exchange_ts_ns": source_ns + 1}), 6, "alpaca_crypto_rest")
        await feeds._stop_active_clients()

    asyncio.run(exercise())
    assert feeds.get_last_candle("BTC/USD") is None
    assert feeds.get_order_book("BTC/USD") is None
    assert received == []


def test_stream_trade_and_quote_noise_cannot_evict_rankable_breadth_snapshots():
    feeds, _events, _polling, _sockets = _market_feeds()
    feeds._active_provider_id = "alpaca_crypto_stream"
    feeds._active_transport_generation = 3
    feeds._execution_truth_active = True
    retained = [{"candle": object(), "identity": index} for index in range(10)]
    feeds._breadth_observations["ETH/USD"].extend(retained)
    source_ns = now_ns() - 1_000_000

    async def exercise():
        for index in range(100):
            await feeds._on_transport_trade(
                {
                    "symbol": "ETH/USD",
                    "price": 100.0,
                    "volume": 1.0,
                    "exchange_ts_ns": source_ns + index,
                },
                3,
                "alpaca_crypto_stream",
            )
            await feeds._on_transport_quote(
                {
                    "symbol": "ETH/USD",
                    "bid": 99.0,
                    "ask": 101.0,
                    "exchange_ts_ns": source_ns + index,
                },
                3,
                "alpaca_crypto_stream",
            )

    asyncio.run(exercise())
    assert list(feeds._breadth_observations["ETH/USD"]) == retained


def test_stale_active_transport_clears_old_truth_before_rest_fallback_activation():
    feeds, events, _polling, _sockets = _market_feeds()

    async def exercise():
        await feeds.start()
        checked_ns = now_ns()
        stale_ns = checked_ns - 70_000_000_000
        feeds.candles.add_candle(
            Candle(symbol="BTC/USD", exchange_ts_ns=stale_ns, open=100, high=101, low=99, close=100, volume=1)
        )
        feeds.order_books["BTC/USD"] = OrderBookSnapshot(
            symbol="BTC/USD",
            exchange_ts_ns=stale_ns,
            receive_ts_ns=stale_ns,
            bids=[(99.0, 1.0)],
            asks=[(101.0, 1.0)],
        )
        feeds._transport_activated_at_ns = checked_ns - 11_000_000_000
        assert await feeds._check_transport_health_once(current_ns=checked_ns) == "ORDER_BOOK_STALE"
        await asyncio.wait_for(feeds._failover_task, timeout=1.0)
        status = feeds.get_feed_truth_status()
        assert status["active_provider_id"] == "alpaca_crypto_rest"
        assert feeds.get_last_candle("BTC/USD") is None
        assert feeds.get_order_book("BTC/USD") is None
        await feeds.stop()

    asyncio.run(exercise())
    assert events.index("stream:stop") < events.index("rest:start")


def test_rank_snapshot_is_causal_deterministic_pareto_based_and_observe_only():
    observations = [_observation("BTC/USD", 3.0), _observation("ETH/USD", 2.0), _observation("SOL/USD", 1.0, cross_venue=False)]
    forward = _universe(observations)
    reverse = _universe(list(reversed(observations)))

    assert forward.to_dict() == reverse.to_dict()
    assert forward.snapshot_id == reverse.snapshot_id
    assert all(item.activation_mode == MARKET_DATA_OBSERVE_ONLY for item in forward.memberships)
    assert all(item.execution_authorized is False for item in forward.memberships)
    assert all(item.pareto_front >= 1 for item in forward.memberships)
    missing_basis = next(item for item in forward.memberships if item.symbol == "SOL/USD")
    assert dict(missing_basis.percentiles)["cross_venue_basis_bps"] == 0.0
    sourced_basis = next(item for item in forward.memberships if item.symbol == "BTC/USD")
    assert sourced_basis.cross_venue_provider_id == "kraken_public"
    assert sourced_basis.cross_venue_source_event_ns is not None
    assert sourced_basis.cross_venue_received_at_ns is not None
    assert not hasattr(forward.memberships[0], "weighted_score")

    future = replace(observations[0], latest_source_event_ns=BASE_NS + 1)
    with pytest.raises(ValueError, match="future_market_observation_refused"):
        _universe([future, *observations[1:]])
    nonfinite = replace(observations[0], spreads_bps=(float("nan"),))
    with pytest.raises(ValueError, match="domain_invalid"):
        _universe([nonfinite, *observations[1:]])
    wrong_venue = replace(observations[0], execution_location="kraken")
    with pytest.raises(ValueError, match="single_execution_location_provider_required|execution_location_observation_required"):
        _universe([wrong_venue, *observations[1:]])
    late_cross_venue = replace(observations[0], cross_venue_received_at_ns=observations[0].observed_at_ns + 1)
    with pytest.raises(ValueError, match="cross_venue_advisory_provenance_invalid"):
        _universe([late_cross_venue, *observations[1:]])
    malformed_sample_arrays = replace(observations[0], log_returns=observations[0].log_returns[:-1])
    with pytest.raises(ValueError, match="sample_array_lengths_invalid"):
        _universe([malformed_sample_arrays, *observations[1:]])


def test_capacity_math_uses_exact_broker_quantity_and_price_increments():
    constrained = replace(
        _observation("BTC/USD", 2.0),
        depth_usd=tuple(Decimal("10") for _ in range(8)),
        execution_mid=Decimal("100.05"),
        min_order_size=Decimal("0.00101"),
        min_trade_increment=Decimal("0.001"),
        price_increment=Decimal("0.1"),
    )
    snapshot = _universe([constrained, _observation("ETH/USD")])
    metrics = dict(next(item for item in snapshot.memberships if item.symbol == "BTC/USD").metrics)

    # ceil(0.00101 / 0.001) * 0.001 = 0.002 quantity and
    # ceil(100.05 / 0.1) * 0.1 = 100.1 price, so minimum notional is 0.2002.
    assert math.isclose(metrics["capacity_multiple"], 10.0 / 0.2002, rel_tol=0.0, abs_tol=1e-12)
    assert math.isclose(
        metrics["estimated_min_order_impact_bps"],
        0.2002 / 10.0 * 10_000.0,
        rel_tol=0.0,
        abs_tol=1e-12,
    )


def test_rank_snapshot_preserves_incomplete_catalog_scope_as_explicit_unranked_observe_only():
    snapshot = _universe(
        [_observation("BTC/USD", 2.0), _observation("ETH/USD", 1.0)],
        held=("BTC/USD",),
        unranked=("SOL/USD",),
    )
    restored = MarketDataUniverseSnapshot.from_dict(snapshot.to_dict())

    assert restored.unranked_symbols == ("SOL/USD",)
    assert {item.symbol for item in restored.memberships} == {"BTC/USD", "ETH/USD"}
    assert "SOL/USD" not in restored.deep_symbols
    assert restored.execution_authorized is False
    assert all(item.execution_authorized is False for item in restored.memberships)

    with pytest.raises(ValueError, match="ranked_unranked_overlap"):
        _universe(
            [_observation("BTC/USD")],
            unranked=("BTC/USD",),
        )
    with pytest.raises(ValueError, match="protected_symbol_observation_missing"):
        _universe(
            [_observation("BTC/USD")],
            held=("SOL/USD",),
            unranked=("SOL/USD",),
        )


def test_rank_replay_rejects_future_created_or_symbol_scope_changed_prior_snapshot():
    observations = [_observation("BTC/USD", 2.0), _observation("ETH/USD", 1.0)]
    future_created = _universe(
        observations,
        created_at_ns=BASE_NS + 100,
    )
    with pytest.raises(ValueError, match="future_prior_universe_refused"):
        _universe(
            observations,
            as_of_ns=BASE_NS + 50,
            created_at_ns=BASE_NS + 51,
            prior_snapshot=future_created,
        )

    incomplete_prior = _universe([observations[0]])
    with pytest.raises(ValueError, match="prior_market_data_universe_symbol_scope_mismatch"):
        _universe(
            observations,
            as_of_ns=BASE_NS + 10,
            created_at_ns=BASE_NS + 11,
            prior_snapshot=incomplete_prior,
        )


def test_cross_venue_advisory_ingress_rejects_future_source_or_receipt_regression(monkeypatch):
    feeds, _events, _polling, _sockets = _market_feeds()
    import app.data.market_feeds as market_feeds_module

    monkeypatch.setattr(market_feeds_module, "now_ns", lambda: BASE_NS)
    feeds.record_cross_venue_advisory(
        symbol="BTC/USD",
        provider_id="kraken_public",
        midpoint="100.01",
        source_event_ns=BASE_NS - 10_000_000,
        received_at_ns=BASE_NS - 1_000_000,
    )
    with pytest.raises(ValueError, match="time_regression"):
        feeds.record_cross_venue_advisory(
            symbol="BTC/USD",
            provider_id="coinbase_public",
            midpoint="100.02",
            source_event_ns=BASE_NS - 11_000_000,
            received_at_ns=BASE_NS,
        )
    with pytest.raises(ValueError, match="time_regression"):
        feeds.record_cross_venue_advisory(
            symbol="BTC/USD",
            provider_id="coinbase_public",
            midpoint="100.02",
            source_event_ns=BASE_NS - 5_000_000,
            received_at_ns=BASE_NS - 2_000_000,
        )
    with pytest.raises(ValueError, match="future_receipt_refused"):
        feeds.record_cross_venue_advisory(
            symbol="BTC/USD",
            provider_id="coinbase_public",
            midpoint="100.02",
            source_event_ns=BASE_NS + 1,
            received_at_ns=BASE_NS + 1,
        )


def test_protected_membership_and_minimum_residence_survive_rank_churn():
    symbols = ["BTC/USD", "ETH/USD", "SOL/USD", "LINK/USD"]
    first = _universe(
        [_observation(symbol, quality) for symbol, quality in zip(symbols, (4.0, 3.0, 2.0, 1.0))],
        held=("SOL/USD",),
        open_orders=("LINK/USD",),
        candidates=1,
        capacity=3,
    )
    initial_candidate = next(item for item in first.memberships if item.deep_selected and not item.protected)
    second = _universe(
        [_observation(symbol, quality) for symbol, quality in zip(symbols, (1.0, 4.0, 2.0, 3.0))],
        as_of_ns=BASE_NS + 10_000_000_000,
        created_at_ns=BASE_NS + 10_000_000_001,
        prior_snapshot=first,
        held=("SOL/USD",),
        open_orders=("LINK/USD",),
        candidates=1,
        capacity=3,
    )
    retained = next(item for item in second.memberships if item.symbol == initial_candidate.symbol)
    assert retained.deep_selected is True
    assert retained.residence_started_ns == initial_candidate.residence_started_ns
    assert "MINIMUM_RESIDENCE_RETAINED" in retained.reason_codes
    assert {"SOL/USD", "LINK/USD"}.issubset(second.deep_symbols)

    with pytest.raises(ValueError, match="protected_deep_capacity_exceeded"):
        _universe(
            [_observation(symbol) for symbol in symbols],
            held=("BTC/USD", "ETH/USD"),
            open_orders=("SOL/USD",),
            candidates=1,
            capacity=2,
        )


def test_universe_application_clears_removed_dynamic_executable_caches(tmp_path: Path):
    symbols = ["BTC/USD", "ETH/USD", "SOL/USD"]
    constraints = {
        symbol: {
            "min_order_size": "0.001",
            "min_trade_increment": "0.0001",
            "price_increment": "0.01",
            "quote_currency": "USD",
            "quote_currency_fundable": True,
            "listing_started_ns": None,
            "listing_age_source": None,
        }
        for symbol in symbols[:2]
    }
    store = StateStore(str(tmp_path / "stage4-removed-cache.db"))
    feeds = MarketFeeds(
        _market_config(symbols),
        symbols=symbols,
        deep_symbols=symbols,
        protected_symbols=["BTC/USD"],
        env=CREDS,
        ranking_constraints=constraints,
        ranking_state_store=store,
        ranking_catalog_snapshot_id="catalog-stage4",
        ranking_broker_universe_snapshot_id="broker-universe-stage4",
        held_symbols=["BTC/USD"],
    )
    source_ns = now_ns() - 1_000_000_000
    feeds.candles.add_candle(
        Candle(symbol="SOL/USD", exchange_ts_ns=source_ns, open=100, high=101, low=99, close=100, volume=1)
    )
    feeds.order_books["SOL/USD"] = OrderBookSnapshot(
        symbol="SOL/USD",
        exchange_ts_ns=source_ns,
        receive_ts_ns=source_ns + 1,
        bids=[(99.0, 1.0)],
        asks=[(101.0, 1.0)],
    )
    feeds.depth_history["SOL/USD"] = [1000.0]
    feeds.spread_history["SOL/USD"] = [5.0]
    breadth_marker = {"symbol": "SOL/USD", "executable_source": True}
    feeds._breadth_observations["SOL/USD"].append(breadth_marker)
    snapshot = _universe(
        [_observation("BTC/USD", 2.0), _observation("ETH/USD", 1.0)],
        held=("BTC/USD",),
        candidates=1,
        capacity=3,
    )
    wrong_role_snapshot = _universe(
        [_observation("BTC/USD", 2.0), _observation("ETH/USD", 1.0)],
        lifecycle=("BTC/USD",),
        candidates=1,
        capacity=3,
    )

    with pytest.raises(ValueError, match="role_lineage_mismatch"):
        asyncio.run(feeds.apply_universe_snapshot(wrong_role_snapshot))
    asyncio.run(feeds.apply_universe_snapshot(snapshot))
    assert "SOL/USD" not in feeds.deep_symbols
    assert feeds.get_last_candle("SOL/USD") is None
    assert feeds.get_order_book("SOL/USD") is None
    assert "SOL/USD" not in feeds.depth_history
    assert "SOL/USD" not in feeds.spread_history
    assert list(feeds._breadth_observations["SOL/USD"]) == [breadth_marker]
    store.close()


def test_pending_deep_subscription_event_is_cached_observe_only_without_execution_callback(tmp_path: Path):
    symbols = ["BTC/USD", "ETH/USD"]
    constraints = {
        symbol: {
            "min_order_size": "0.001",
            "min_trade_increment": "0.0001",
            "price_increment": "0.01",
            "quote_currency": "USD",
            "quote_currency_fundable": True,
            "listing_started_ns": None,
            "listing_age_source": None,
        }
        for symbol in symbols
    }
    store = StateStore(str(tmp_path / "stage4-pending-deep.db"))
    feeds = MarketFeeds(
        _market_config(symbols),
        symbols=symbols,
        deep_symbols=["BTC/USD"],
        protected_symbols=["BTC/USD"],
        env=CREDS,
        ranking_constraints=constraints,
        ranking_state_store=store,
        ranking_catalog_snapshot_id="catalog-stage4",
        ranking_broker_universe_snapshot_id="broker-universe-stage4",
        held_symbols=["BTC/USD"],
    )
    execution_callbacks: list[str] = []
    feeds.register_candle_callback(lambda candle: execution_callbacks.append(candle.symbol))
    feeds._active_provider_id = "alpaca_crypto_stream"
    feeds._active_transport_generation = 7
    feeds._transport_state = "ACTIVE"
    feeds._execution_truth_active = True
    event_ns = now_ns() - 1_000_000_000

    class EmitsDuringSubscriptionAck:
        async def update_symbols(self, selected):
            assert tuple(selected) == ("BTC/USD", "ETH/USD")
            accepted = await feeds._on_transport_candle(
                Candle(
                    symbol="ETH/USD",
                    exchange_ts_ns=event_ns,
                    open=100,
                    high=101,
                    low=99,
                    close=100,
                    volume=1,
                    provider_id="alpaca_crypto_stream",
                ),
                7,
                "alpaca_crypto_stream",
            )
            assert accepted is True

    feeds.websocket_client = EmitsDuringSubscriptionAck()
    snapshot = _universe(
        [_observation("BTC/USD", 2.0), _observation("ETH/USD", 1.0)],
        held=("BTC/USD",),
        candidates=1,
        capacity=3,
    )
    asyncio.run(feeds.apply_universe_snapshot(snapshot))
    assert feeds.deep_symbols == ("BTC/USD", "ETH/USD")
    assert feeds.get_last_candle("ETH/USD") is not None
    assert execution_callbacks == []
    store.close()


def test_market_data_universe_persists_reloads_and_rejects_tampering(tmp_path: Path):
    snapshot = _universe([_observation("BTC/USD", 2.0), _observation("ETH/USD", 1.0)], held=("BTC/USD",))
    database = tmp_path / "stage4.db"
    store = StateStore(str(database))
    assert store.persist_market_data_universe_snapshot(snapshot) == "persisted"
    assert store.persist_market_data_universe_snapshot(snapshot) == "duplicate"
    loaded = store.get_market_data_universe_snapshot(snapshot.snapshot_id, strict=True)
    assert MarketDataUniverseSnapshot.from_dict(loaded) == snapshot
    store.close()

    payload = copy.deepcopy(loaded)
    payload["memberships"][0]["execution_authorized"] = True
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE market_data_universe_snapshots SET payload = ? WHERE snapshot_id = ?",
            (json.dumps(payload, sort_keys=True, separators=(",", ":")), snapshot.snapshot_id),
        )
        connection.commit()
    restarted = StateStore(str(database), read_only=True)
    with pytest.raises(RuntimeError, match="semantic_integrity_failed"):
        restarted.get_market_data_universe_snapshot(snapshot.snapshot_id, strict=True)
    restarted.close()


def test_market_data_universe_rejects_boolean_metrics_and_reason_strings_before_hash_acceptance():
    snapshot = _universe([_observation("BTC/USD", 2.0), _observation("ETH/USD", 1.0)])
    boolean_metric = copy.deepcopy(snapshot.to_dict())
    boolean_metric["memberships"][0]["metrics"]["clock_quality"] = True
    with pytest.raises(ValueError, match="boolean_metric_invalid"):
        MarketDataUniverseSnapshot.from_dict(boolean_metric)

    reason_string = copy.deepcopy(snapshot.to_dict())
    reason_string["memberships"][0]["reason_codes"] = "DYNAMIC_MEMBERSHIP_OBSERVE_ONLY"
    with pytest.raises(ValueError, match="reason_codes_invalid"):
        MarketDataUniverseSnapshot.from_dict(reason_string)


def test_market_data_ranking_schema_rejects_non_string_provenance_before_normalization():
    observation = _observation("BTC/USD").to_dict()
    for field_name in (
        "provider_id",
        "execution_location",
        "listing_age_source",
        "quote_currency",
        "cross_venue_provider_id",
    ):
        malformed = copy.deepcopy(observation)
        malformed[field_name] = 7
        with pytest.raises(ValueError, match="nonempty_string_required"):
            MarketBreadthObservation.from_dict(malformed)

    snapshot = _universe([_observation("BTC/USD"), _observation("ETH/USD")]).to_dict()
    for field_name in (
        "snapshot_id",
        "schema_version",
        "catalog_snapshot_id",
        "broker_universe_snapshot_id",
        "activation_mode",
        "provider_id",
        "execution_location",
        "snapshot_hash",
    ):
        malformed = copy.deepcopy(snapshot)
        malformed[field_name] = 7
        with pytest.raises(ValueError, match="nonempty_string_required"):
            MarketDataUniverseSnapshot.from_dict(malformed)

    malformed_membership = copy.deepcopy(snapshot)
    malformed_membership["memberships"][0]["cross_venue_provider_id"] = 7
    with pytest.raises(ValueError, match="nonempty_string_required"):
        MarketDataUniverseSnapshot.from_dict(malformed_membership)


def test_market_data_universe_strict_read_rejects_relational_column_tampering(tmp_path: Path):
    snapshot = _universe([_observation("BTC/USD", 2.0), _observation("ETH/USD", 1.0)])
    database = tmp_path / "stage4-column-integrity.db"
    store = StateStore(str(database))
    assert store.persist_market_data_universe_snapshot(snapshot) == "persisted"
    store.close()

    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE market_data_universe_snapshots SET catalog_snapshot_id = ? WHERE snapshot_id = ?",
            ("tampered-catalog", snapshot.snapshot_id),
        )
        connection.commit()
    restarted = StateStore(str(database), read_only=True)
    with pytest.raises(RuntimeError, match="column_integrity_failed:catalog_snapshot_id"):
        restarted.get_market_data_universe_snapshot(snapshot.snapshot_id, strict=True)
    with pytest.raises(RuntimeError, match="column_integrity_failed:catalog_snapshot_id"):
        restarted.get_latest_market_data_universe_snapshot(
            catalog_snapshot_id="tampered-catalog",
            broker_universe_snapshot_id=snapshot.broker_universe_snapshot_id,
            strict=True,
        )
    restarted.close()


def test_rank_restart_requires_exact_role_lineage_not_only_same_symbol_union(tmp_path: Path, monkeypatch):
    symbols = ["BTC/USD", "ETH/USD"]
    snapshot = _universe(
        [_observation("BTC/USD", 2.0), _observation("ETH/USD", 1.0)],
        held=("BTC/USD",),
    )
    store = StateStore(str(tmp_path / "stage4-role-integrity.db"))
    assert store.persist_market_data_universe_snapshot(snapshot) == "persisted"
    import app.data.market_feeds as market_feeds_module

    monkeypatch.setattr(market_feeds_module, "now_ns", lambda: BASE_NS + 10)
    constraints = {
        symbol: {
            "min_order_size": "0.001",
            "min_trade_increment": "0.0001",
            "price_increment": "0.01",
            "quote_currency": "USD",
            "quote_currency_fundable": True,
            "listing_started_ns": None,
            "listing_age_source": None,
        }
        for symbol in symbols
    }
    feeds = MarketFeeds(
        _market_config(symbols),
        symbols=symbols,
        deep_symbols=["BTC/USD"],
        protected_symbols=["BTC/USD"],
        env=CREDS,
        ranking_constraints=constraints,
        ranking_state_store=store,
        ranking_catalog_snapshot_id=snapshot.catalog_snapshot_id,
        ranking_broker_universe_snapshot_id=snapshot.broker_universe_snapshot_id,
        held_symbols=[],
        open_order_symbols=[],
        lifecycle_symbols=["BTC/USD"],
    )
    assert feeds.get_feed_truth_status()["universe_ranking"]["status"] == "PRIOR_SCOPE_MISMATCH_COLLECTING_BREADTH"
    assert feeds._latest_universe_snapshot is None
    store.close()


def test_rank_restart_rejects_future_created_snapshot_even_when_as_of_is_past(
    tmp_path: Path,
    monkeypatch,
):
    store = StateStore(str(tmp_path / "future-created-rank.db"))
    snapshot = _universe(
        [_observation("BTC/USD")],
        as_of_ns=BASE_NS,
        created_at_ns=BASE_NS + 10,
        candidates=1,
        capacity=2,
    )
    assert store.persist_market_data_universe_snapshot(snapshot) == "persisted"

    import app.data.market_feeds as market_feeds_module

    monkeypatch.setattr(market_feeds_module, "now_ns", lambda: BASE_NS + 5)
    feeds = MarketFeeds(
        _market_config(["BTC/USD"]),
        symbols=["BTC/USD"],
        deep_symbols=["BTC/USD"],
        protected_symbols=[],
        env=CREDS,
        ranking_constraints={
            "BTC/USD": {
                "min_order_size": "0.001",
                "min_trade_increment": "0.0001",
                "price_increment": "0.01",
                "quote_currency": "USD",
                "quote_currency_fundable": True,
                "listing_started_ns": None,
                "listing_age_source": None,
            }
        },
        ranking_state_store=store,
        ranking_catalog_snapshot_id="catalog-stage4",
        ranking_broker_universe_snapshot_id="broker-universe-stage4",
    )
    status = feeds.get_feed_truth_status()["universe_ranking"]
    assert status["status"] == "BLOCKED_RANKING_STATE_INVALID"
    assert feeds._latest_universe_snapshot is None
    assert feeds._ranking_enabled is False
    store.close()


def test_marketfeeds_breadth_callback_builds_persists_and_applies_observe_only_universe(tmp_path: Path):
    symbols = ["BTC/USD", "ETH/USD"]
    config = _market_config(symbols)
    config.data = DataConfig(
        max_candles_per_symbol=100,
        market_data_observations_per_symbol=10,
        market_data_rank_min_observations=3,
        market_data_rank_refresh_seconds=15,
        market_data_deep_candidate_limit=1,
        market_data_deep_subscription_limit=3,
        market_data_job_queue_size=8,
        market_data_failure_history_size=10,
    )
    store = StateStore(str(tmp_path / "rank-runtime.db"))
    constraints = {
        symbol: {
            "min_order_size": "0.001",
            "min_trade_increment": "0.0001",
            "price_increment": "0.01",
            "quote_currency": "USD",
            "quote_currency_fundable": True,
            "listing_started_ns": None,
            "listing_age_source": None,
        }
        for symbol in symbols
    }
    feeds = MarketFeeds(
        config,
        symbols=symbols,
        deep_symbols=symbols,
        protected_symbols=["BTC/USD"],
        env=CREDS,
        ranking_constraints=constraints,
        ranking_state_store=store,
        ranking_catalog_snapshot_id="catalog-runtime-stage4",
        ranking_broker_universe_snapshot_id="broker-runtime-stage4",
        held_symbols=["BTC/USD"],
    )
    feeds._active_transport_generation = 7
    base = now_ns() - 5_000_000_000
    feeds.record_cross_venue_advisory(
        symbol="BTC/USD",
        provider_id="kraken_public",
        midpoint="100.05",
        source_event_ns=base,
        received_at_ns=base + 1_000_000,
    )

    def event(symbol: str, index: int) -> dict:
        source_ns = base + (index + 1) * 1_000_000_000
        received_ns = source_ns + 10_000_000
        price = 100.0 + index
        return {
            "symbol": symbol,
            "provider_id": "alpaca_crypto_rest",
            "execution_location": "alpaca",
            "executable_source": True,
            "quote_exchange_ts_ns": source_ns,
            "trade_exchange_ts_ns": source_ns,
            "bar_exchange_ts_ns": source_ns,
            "bid": price - 0.5,
            "ask": price + 0.5,
            "bid_size": 5.0,
            "ask_size": 6.0,
            "trade_price": price,
            "trade_size": 0.25,
            "trade_count": 8 + index,
            "candle": Candle(
                symbol=symbol,
                exchange_ts_ns=source_ns,
                open=price - 1,
                high=price + 1,
                low=price - 2,
                close=price,
                volume=25 + index,
                provider_id="alpaca_crypto_rest",
            ),
            "received_at_ns": received_ns,
        }

    async def exercise():
        duplicate = event("ETH/USD", 0)
        duplicate["received_at_ns"] += 50_000_000
        await feeds._on_breadth_snapshot(event("ETH/USD", 0), 7)
        await feeds._on_breadth_snapshot(duplicate, 7)
        for index in range(3):
            if index > 0:
                await feeds._on_breadth_snapshot(event("ETH/USD", index), 7)
                if index == 2:
                    assert feeds._rank_refresh_task is None
                    assert feeds._ranking_status["status"] == "COLLECTING_PROTECTED_BREADTH"
                    assert feeds._ranking_status["symbols"] == ("BTC/USD",)
            await feeds._on_breadth_snapshot(event("BTC/USD", index), 7)
        await asyncio.wait_for(feeds._rank_refresh_task, timeout=1.0)

    asyncio.run(exercise())
    rank_status = feeds.get_feed_truth_status()["universe_ranking"]
    assert rank_status["status"] == "OBSERVE_ONLY_UNIVERSE_CURRENT"
    assert rank_status["execution_authorized"] is False
    assert feeds._rankable_breadth_count("ETH/USD") == 3
    persisted = store.get_market_data_universe_snapshot(rank_status["snapshot_id"], strict=True)
    snapshot = MarketDataUniverseSnapshot.from_dict(persisted)
    assert snapshot.activation_mode == MARKET_DATA_OBSERVE_ONLY
    assert snapshot.execution_authorized is False
    assert "BTC/USD" in snapshot.deep_symbols
    btc = next(item for item in snapshot.memberships if item.symbol == "BTC/USD")
    assert btc.cross_venue_provider_id == "kraken_public"
    assert btc.cross_venue_source_event_ns is not None
    assert btc.cross_venue_received_at_ns is not None
    restored = MarketFeeds(
        config,
        symbols=symbols,
        deep_symbols=["BTC/USD"],
        protected_symbols=["BTC/USD"],
        env=CREDS,
        ranking_constraints=constraints,
        ranking_state_store=store,
        ranking_catalog_snapshot_id="catalog-runtime-stage4",
        ranking_broker_universe_snapshot_id="broker-runtime-stage4",
        held_symbols=["BTC/USD"],
    )
    restored_status = restored.get_feed_truth_status()["universe_ranking"]
    assert restored_status["status"] == "OBSERVE_ONLY_UNIVERSE_RESTORED"
    assert restored._latest_universe_snapshot.snapshot_id == snapshot.snapshot_id
    assert restored.deep_symbols == snapshot.deep_symbols
    assert restored_status["unranked_symbols"] == ()
    store.close()


def test_incomplete_dynamic_symbol_cannot_block_or_enter_ranked_universe(tmp_path: Path):
    symbols = ["BTC/USD", "ETH/USD"]
    config = _market_config(symbols)
    config.data = DataConfig(
        max_candles_per_symbol=100,
        market_data_observations_per_symbol=10,
        market_data_rank_min_observations=3,
        market_data_rank_refresh_seconds=15,
        market_data_deep_candidate_limit=1,
        market_data_deep_subscription_limit=3,
        market_data_job_queue_size=8,
        market_data_failure_history_size=10,
    )
    constraints = {
        symbol: {
            "min_order_size": "0.001",
            "min_trade_increment": "0.0001",
            "price_increment": "0.01",
            "quote_currency": "USD",
            "quote_currency_fundable": True,
            "listing_started_ns": None,
            "listing_age_source": None,
        }
        for symbol in symbols
    }
    store = StateStore(str(tmp_path / "incomplete-rank-runtime.db"))
    feeds = MarketFeeds(
        config,
        symbols=symbols,
        deep_symbols=["BTC/USD"],
        protected_symbols=["BTC/USD"],
        env=CREDS,
        ranking_constraints=constraints,
        ranking_state_store=store,
        ranking_catalog_snapshot_id="catalog-incomplete-stage4",
        ranking_broker_universe_snapshot_id="broker-incomplete-stage4",
        held_symbols=["BTC/USD"],
    )
    feeds._active_transport_generation = 9
    base = now_ns() - 5_000_000_000

    def event(index: int) -> dict:
        source_ns = base + (index + 1) * 1_000_000_000
        price = 100.0 + index
        return {
            "symbol": "BTC/USD",
            "provider_id": "alpaca_crypto_rest",
            "execution_location": "alpaca",
            "executable_source": True,
            "quote_exchange_ts_ns": source_ns,
            "trade_exchange_ts_ns": source_ns,
            "bar_exchange_ts_ns": source_ns,
            "bid": price - 0.5,
            "ask": price + 0.5,
            "bid_size": 5.0,
            "ask_size": 6.0,
            "trade_price": price,
            "trade_size": 0.25,
            "trade_count": 8 + index,
            "candle": Candle(
                symbol="BTC/USD",
                exchange_ts_ns=source_ns,
                open=price - 1,
                high=price + 1,
                low=price - 2,
                close=price,
                volume=25 + index,
                provider_id="alpaca_crypto_rest",
            ),
            "received_at_ns": source_ns + 10_000_000,
        }

    async def exercise():
        for index in range(3):
            await feeds._on_breadth_snapshot(event(index), 9)
        await asyncio.wait_for(feeds._rank_refresh_task, timeout=1.0)

    asyncio.run(exercise())
    rank_status = feeds.get_feed_truth_status()["universe_ranking"]
    assert rank_status["status"] == "OBSERVE_ONLY_UNIVERSE_CURRENT"
    assert rank_status["unranked_symbols"] == ("ETH/USD",)
    assert rank_status["unranked_reason"] == "INSUFFICIENT_EXECUTION_LOCATION_OBSERVATIONS"
    snapshot = MarketDataUniverseSnapshot.from_dict(
        store.get_market_data_universe_snapshot(rank_status["snapshot_id"], strict=True)
    )
    assert snapshot.unranked_symbols == ("ETH/USD",)
    assert tuple(item.symbol for item in snapshot.memberships) == ("BTC/USD",)
    assert snapshot.deep_symbols == ("BTC/USD",)
    assert snapshot.execution_authorized is False
    store.close()


def test_silent_dynamic_symbol_becomes_explicitly_unranked_despite_minimum_residence(
    tmp_path: Path,
    monkeypatch,
):
    import app.data.market_feeds as market_feeds_module

    clock = [BASE_NS]
    monkeypatch.setattr(market_feeds_module, "now_ns", lambda: clock[0])
    symbols = ["BTC/USD", "ETH/USD"]
    config = _market_config(symbols)
    config.data = DataConfig(
        max_candles_per_symbol=100,
        breadth_poll_interval_seconds=15.0,
        market_data_observations_per_symbol=10,
        market_data_rank_min_observations=3,
        market_data_rank_refresh_seconds=15,
        market_data_rank_observation_max_age_seconds=45.0,
        market_data_deep_candidate_limit=1,
        market_data_deep_subscription_limit=3,
        market_data_min_residence_seconds=900,
        market_data_job_queue_size=8,
        market_data_failure_history_size=10,
    )
    constraints = {
        symbol: {
            "min_order_size": "0.001",
            "min_trade_increment": "0.0001",
            "price_increment": "0.01",
            "quote_currency": "USD",
            "quote_currency_fundable": True,
            "listing_started_ns": None,
            "listing_age_source": None,
        }
        for symbol in symbols
    }
    store = StateStore(str(tmp_path / "silent-rank-runtime.db"))
    feeds = MarketFeeds(
        config,
        symbols=symbols,
        deep_symbols=symbols,
        protected_symbols=["BTC/USD"],
        env=CREDS,
        ranking_constraints=constraints,
        ranking_state_store=store,
        ranking_catalog_snapshot_id="catalog-silent-stage4",
        ranking_broker_universe_snapshot_id="broker-silent-stage4",
        held_symbols=["BTC/USD"],
    )
    feeds._active_transport_generation = 10
    rank_as_ofs: list[int] = []
    original_build_rank_observation = feeds._build_rank_observation

    def track_rank_as_of(symbol: str, *, current_ns: int | None = None):
        rank_as_ofs.append(int(current_ns or 0))
        return original_build_rank_observation(symbol, current_ns=current_ns)

    feeds._build_rank_observation = track_rank_as_of

    def event(symbol: str, source_ns: int, price: float) -> dict:
        return {
            "symbol": symbol,
            "provider_id": "alpaca_crypto_rest",
            "execution_location": "alpaca",
            "executable_source": True,
            "quote_exchange_ts_ns": source_ns,
            "trade_exchange_ts_ns": source_ns,
            "bar_exchange_ts_ns": source_ns,
            "bid": price - 0.5,
            "ask": price + 0.5,
            "bid_size": 5.0,
            "ask_size": 6.0,
            "trade_price": price,
            "trade_size": 0.25,
            "trade_count": 8,
            "candle": Candle(
                symbol=symbol,
                exchange_ts_ns=source_ns,
                open=price - 1,
                high=price + 1,
                low=price - 2,
                close=price,
                volume=25,
                provider_id="alpaca_crypto_rest",
            ),
            "received_at_ns": source_ns + 10_000_000,
        }

    async def exercise():
        for index in range(3):
            await feeds._on_breadth_snapshot(
                event("ETH/USD", BASE_NS - (5 - index) * 1_000_000_000, 100.0 + index),
                10,
            )
        for index in range(3):
            await feeds._on_breadth_snapshot(
                event("BTC/USD", BASE_NS - (5 - index) * 1_000_000_000, 110.0 + index),
                10,
            )
        await asyncio.wait_for(feeds._rank_refresh_task, timeout=1.0)
        first = feeds._latest_universe_snapshot
        assert first is not None
        assert first.unranked_symbols == ()
        assert "ETH/USD" in first.deep_symbols

        clock[0] += 61_000_000_000
        await feeds._on_breadth_snapshot(
            event("BTC/USD", clock[0] - 1_000_000_000, 120.0),
            10,
        )
        await asyncio.wait_for(feeds._rank_refresh_task, timeout=1.0)

    asyncio.run(exercise())
    second = feeds._latest_universe_snapshot
    assert second is not None
    assert second.unranked_symbols == ("ETH/USD",)
    assert "ETH/USD" not in second.deep_symbols
    assert second.execution_authorized is False
    assert rank_as_ofs == [BASE_NS, BASE_NS, BASE_NS + 61_000_000_000]
    store.close()


def test_offline_full_catalog_soak_has_bounded_state_and_zero_dynamic_execution_authority():
    symbols = _symbols(600)
    request_count = 0

    async def request_json(endpoint, params):
        nonlocal request_count
        request_count += 1
        requested = str(params["symbols"]).split(",")
        payload = _snapshot_payload(requested) if endpoint.endswith("/snapshots") else _order_book_payload(requested)
        return 200, {}, payload

    client = BatchedAlpacaPollingClient(
        breadth_symbols=symbols,
        deep_symbols=symbols[:12],
        protected_symbols=symbols[:4],
        deep_poll_enabled=True,
        request_headers=CREDS,
        policy=_policy(batch_size=50, max_concurrency=4, job_queue_size=8, failure_history_size=7),
        request_json=request_json,
    )
    for _ in range(20):
        asyncio.run(client.poll_once())
    stats = client.get_stats()
    expected_per_cycle = math.ceil(600 / 50) + math.ceil(12 / 50)
    assert request_count == 20 * expected_per_cycle
    assert stats["metrics"]["max_inflight"] <= 4
    assert stats["metrics"]["queue_high_water"] <= 8
    assert len(stats["failure_history"]) <= 7
    assert len(stats["event_history"]) <= 7

    observations = [_observation(symbol, 1.0 + index / 1000.0) for index, symbol in enumerate(symbols)]
    snapshot = _universe(
        observations,
        held=tuple(symbols[:4]),
        candidates=12,
        capacity=20,
    )
    assert len(snapshot.memberships) == 600
    assert len(snapshot.deep_symbols) == 16
    assert all(item.activation_mode == MARKET_DATA_OBSERVE_ONLY for item in snapshot.memberships)
    assert all(item.execution_authorized is False for item in snapshot.memberships)


def test_runtime_routes_alpaca_to_marketfeeds_and_keeps_internal_harness_legacy(monkeypatch):
    started: list[str] = []

    class FakeThread:
        def __init__(self, *, target, name, daemon):
            self.target = target
            self.name = name
            self.daemon = daemon

        def start(self):
            started.append(self.name)

    monkeypatch.setattr(main.threading, "Thread", FakeThread)
    runtime = object.__new__(main.SovereignHeartbeat)
    runtime._threads = []
    runtime._health_check_loop = lambda: None
    runtime._start_market_feeds = lambda: started.append("marketfeeds")
    runtime._start_whale_websocket = lambda: started.append("legacy-websocket")
    runtime._start_polling_client = lambda: started.append("legacy-polling")

    runtime._execution_broker = main.ALPACA_PAPER_EXECUTION_BROKER
    runtime._start_background_threads()
    assert started == ["pk-health-check", "marketfeeds"]

    started.clear()
    runtime._threads.clear()
    runtime._execution_broker = main.INTERNAL_PAPER_EXECUTION_BROKER
    runtime._start_background_threads()
    assert started == ["pk-health-check", "legacy-websocket", "legacy-polling"]


def test_runtime_shutdown_cancels_market_feeds_and_joins_before_closing_state():
    scheduled: list[str] = []

    class FakeTask:
        def done(self):
            return False

        def cancel(self):
            scheduled.append("feed_cancelled")

    class FakeLoop:
        def is_running(self):
            return True

        def call_soon_threadsafe(self, callback):
            scheduled.append("feed_cancel_scheduled")
            callback()

    shell = object.__new__(main.SovereignHeartbeat)
    shell._market_feeds_loop = FakeLoop()
    shell._market_feeds_task = FakeTask()
    main.SovereignHeartbeat._request_market_feeds_stop(shell)
    assert scheduled == ["feed_cancel_scheduled", "feed_cancelled"]

    events: list[str] = []

    class StopOwner:
        def __init__(self, label):
            self.label = label

        def stop(self):
            events.append(f"{self.label}_stop")

        def get_oms_shutdown_accounting(self):
            return {}

    class StateOwner:
        def close(self):
            events.append("state_close")

    runtime = object.__new__(main.SovereignHeartbeat)
    runtime._running = True
    runtime._stopping = False
    runtime._shutdown_complete = False
    runtime._shutdown_reason_code = None
    runtime._broker_flatten_performed_on_shutdown = False
    runtime._last_error = None
    runtime._threads = []
    runtime._stop_event = threading.Event()
    runtime.main_loop = StopOwner("main")
    runtime.execution_engine = StopOwner("execution")
    runtime.state_store = StateOwner()
    runtime._request_market_feeds_stop = lambda: events.append("feed_cancel")
    runtime._join_background_threads = lambda: events.append("threads_joined")
    runtime._write_runtime_heartbeat = lambda **_kwargs: events.append("heartbeat")

    main.SovereignHeartbeat.stop(runtime, reason_code="STAGE4_SHUTDOWN_TEST_NO_FLATTEN")
    assert events.index("feed_cancel") < events.index("main_stop")
    assert events.index("threads_joined") < events.index("state_close")
    assert events[-1] == "heartbeat"


def test_runtime_status_and_rest_latency_follow_current_transport_truth():
    class CaptureRouter:
        def __init__(self):
            self.kwargs = None

        def update_rest_market_data_latency(self, **kwargs):
            self.kwargs = kwargs

        def get_ghost_status(self):
            return {}

    runtime = object.__new__(main.SovereignHeartbeat)
    runtime.order_router = CaptureRouter()
    runtime._selected_market_data_provider_id = "alpaca_crypto_stream"
    runtime._primary_feed_venue = "alpaca"
    runtime._on_rest_latency(
        {
            "provider_id": "alpaca_crypto_rest",
            "exchange": "alpaca",
            "request_start_ns": 10,
            "response_received_ns": 20,
            "symbol": "BTC/USD",
            "feed_type": "snapshot",
        }
    )
    assert runtime.order_router.kwargs["provider_id"] == "alpaca_crypto_rest"

    status_owner = SimpleNamespace(get_status=lambda: {})
    runtime._running = True
    runtime._shutdown_reason_code = None
    runtime._last_error = None
    runtime.commander = SimpleNamespace(is_attack_mode=lambda: False, get_status=lambda: {})
    runtime.execution_engine = status_owner
    runtime.risk_guard = status_owner
    runtime.recalibrator = status_owner
    runtime.shans_curve = SimpleNamespace(get_stats=lambda: {})
    runtime.main_loop = status_owner
    runtime._active_symbols = set()
    runtime._capability_candidates = ()
    runtime._primary_symbol = "BTC/USD"
    runtime._universe_resolution = SimpleNamespace(
        source="broker_catalog",
        reason="UNIVERSE_READY_FROM_BROKER_CATALOG",
    )
    runtime._runtime_universe_symbols = ("BTC/USD", "ETH/USD")
    runtime._market_data_provider_selection = SimpleNamespace(
        to_telemetry=lambda: {},
        reason="PRIMARY_SELECTED",
    )
    runtime._configured_market_data_providers = ("alpaca_crypto_stream", "alpaca_crypto_rest")
    runtime._market_feeds = SimpleNamespace(
        deep_symbols=("BTC/USD", "ETH/USD"),
        get_feed_truth_status=lambda: {"status": "ACTIVE"},
    )
    runtime._feed_symbols = ("BTC/USD", "ETH/USD", "SOL/USD")
    runtime._initial_deep_symbols = ("BTC/USD",)
    runtime._execution_callback_symbols = {"BTC/USD"}
    runtime._execution_broker = main.ALPACA_PAPER_EXECUTION_BROKER
    runtime._execution_primary_exchange = "alpaca"
    runtime._execution_adapter_id = "alpaca_paper_rest"

    status = runtime.get_status()
    assert status["market_data_deep_symbols"] == ["BTC/USD", "ETH/USD"]
    assert status["missing_universe_feed_truth_reason"] is None
    assert status["shutdown_reason_code"] is None
    assert status["last_runtime_error_type"] is None

    failed_router = build_feed_provider_router(
        configured_provider_ids=("coinbase_public", "kraken_public"),
        env={},
    )
    failed_selection = failed_router.select_provider(
        FeedProviderRequest(
            symbol="BTC/USD",
            asset_class="crypto",
            required_data_type="order_book",
            provider_lane=FeedProviderLane.CRYPTO_MARKET_DATA.value,
            execution_required=True,
        )
    )
    assert failed_selection.selected_provider_id is None
    runtime._feed_provider_router = failed_router
    runtime._market_data_provider_selection = SimpleNamespace(
        selected_provider_id="alpaca_crypto_stream",
        to_telemetry=lambda: {},
        reason="PRIMARY_SELECTED",
    )
    runtime._selected_market_data_provider_id = "alpaca_crypto_stream"
    runtime._last_error = None
    runtime._shutdown_reason_code = None
    runtime._stop_event = threading.Event()
    runtime._on_market_transport_truth(
        {"status": "FAILED_CLOSED", "executable_truth": False}
    )
    assert runtime._selected_market_data_provider_id == ""
    assert runtime._market_data_provider_selection is failed_selection
    assert runtime._last_error == "RuntimeError"
    assert runtime._running is False
    assert runtime._stop_event.is_set() is True
    assert runtime._shutdown_reason_code == "MARKET_DATA_EXECUTABLE_TRUTH_FAILED_CLOSED_NO_FLATTEN"
    failed_status = runtime.get_status()
    assert failed_status["running"] is False
    assert failed_status["shutdown_reason_code"] == "MARKET_DATA_EXECUTABLE_TRUTH_FAILED_CLOSED_NO_FLATTEN"
    assert failed_status["last_runtime_error_type"] == "RuntimeError"

    runtime._running = True
    runtime._selected_market_data_provider_id = "alpaca_crypto_stream"
    runtime._last_error = None
    runtime._shutdown_reason_code = None
    runtime._stop_event = threading.Event()
    runtime._on_market_transport_truth(
        {
            "status": "EXECUTION_CONSUMER_REJECTED",
            "active_provider_id": "alpaca_crypto_stream",
            "transport_activated": True,
            "executable_truth": False,
        }
    )
    assert runtime._running is False
    assert runtime._stop_event.is_set() is True
    assert runtime._shutdown_reason_code == "MARKET_DATA_EXECUTABLE_TRUTH_FAILED_CLOSED_NO_FLATTEN"
    assert runtime._selected_market_data_provider_id == "alpaca_crypto_stream"


def test_runtime_market_data_callbacks_report_main_loop_acceptance_and_failure():
    class AcceptingMainLoop:
        def __init__(self):
            self.candles = []
            self.books = []

        def on_candle(self, candle):
            self.candles.append(candle)

        def on_order_book(self, book):
            self.books.append(book)

    runtime = object.__new__(main.SovereignHeartbeat)
    runtime._candle_recv_count = 0
    runtime._book_recv_count = 0
    runtime._last_error = None
    runtime._last_loop_ts = None
    runtime.main_loop = AcceptingMainLoop()
    candle = Candle(
        symbol="BTC/USD",
        exchange_ts_ns=BASE_NS,
        open=100,
        high=101,
        low=99,
        close=100,
        volume=1,
    )
    book = OrderBookSnapshot(
        symbol="BTC/USD",
        exchange_ts_ns=BASE_NS,
        bids=[(99.5, 2.0)],
        asks=[(100.5, 3.0)],
    )

    assert main.SovereignHeartbeat._on_candle(runtime, candle) is True
    assert main.SovereignHeartbeat._on_order_book(runtime, book) is True
    assert runtime.main_loop.candles == [candle]
    assert runtime.main_loop.books == [book]
    assert runtime._last_loop_ts is not None
    assert runtime._last_error is None

    class FailingMainLoop:
        @staticmethod
        def on_candle(_candle):
            raise RuntimeError("synthetic candle consumer failure")

        @staticmethod
        def on_order_book(_book):
            raise ValueError("synthetic book consumer failure")

    runtime.main_loop = FailingMainLoop()
    assert main.SovereignHeartbeat._on_candle(runtime, candle) is False
    assert runtime._last_error == "RuntimeError"
    assert main.SovereignHeartbeat._on_order_book(runtime, book) is False
    assert runtime._last_error == "ValueError"


def test_protected_market_data_callback_rejection_propagates_to_transport():
    feeds, _events, _polling, _sockets = _market_feeds()
    feeds.register_candle_callback(lambda _candle: False)
    feeds.register_order_book_callback(lambda _book: False)

    async def exercise():
        await feeds.start()
        generation = feeds._active_transport_generation
        current_ns = now_ns()
        minute_ns = 60_000_000_000
        candle = Candle(
            symbol="BTC/USD",
            exchange_ts_ns=(current_ns // minute_ns - 1) * minute_ns,
            open=100,
            high=101,
            low=99,
            close=100,
            volume=1,
            timeframe="1m",
            candle_close_ts_ns=(current_ns // minute_ns) * minute_ns,
            candle_closed_at_receive=True,
            candle_batch_received_ns=current_ns,
            provider_id="alpaca_crypto_stream",
        )
        book = OrderBookSnapshot(
            symbol="BTC/USD",
            exchange_ts_ns=current_ns - 1_000_000_000,
            receive_ts_ns=current_ns,
            bids=[(99.5, 2.0)],
            asks=[(100.5, 3.0)],
        )

        feeds.candles.add_candle(candle)
        feeds.order_books["BTC/USD"] = book
        feeds._execution_consumer_seeded = True

        assert await feeds._on_transport_candle(candle, generation, "alpaca_crypto_stream") is False
        status = feeds.get_feed_truth_status()
        assert status["executable_truth"] is False
        assert status["transport_truth"]["reason"] == "EXECUTION_CONSUMER_REJECTED"
        feeds._execution_truth_active = True
        feeds._execution_consumer_seeded = True
        assert await feeds._on_transport_order_book(book, generation, "alpaca_crypto_stream") is False
        assert feeds.get_feed_truth_status()["executable_truth"] is False
        await feeds.stop()

    asyncio.run(exercise())


def test_cross_venue_sources_remain_advisory_and_launcher_defaults_to_alpaca_execution_location():
    router = build_feed_provider_router(
        configured_provider_ids=("coinbase_public", "kraken_public"),
        env={},
    )
    result = router.select_provider(
        FeedProviderRequest(
            symbol="BTC/USD",
            asset_class="crypto",
            required_data_type="order_book",
            provider_lane=FeedProviderLane.CRYPTO_MARKET_DATA.value,
            execution_required=True,
        )
    )
    assert result.selected_provider is None
    assert all("ADVISORY_ONLY" in result.skipped[provider] for provider in ("coinbase_public", "kraken_public"))

    launcher = Path("scripts/run_bounded_paper.ps1").read_text(encoding="utf-8")
    expected = "alpaca_crypto_stream,alpaca_crypto_rest,coinbase_public,kraken_public"
    assert launcher.count(expected) == 2
    assert "coinbase_public,kraken_public'" not in launcher


def test_data_config_enforces_transport_budget_relationships():
    configured = DataConfig()
    assert configured.market_data_deep_candidate_limit <= configured.market_data_deep_subscription_limit
    assert configured.market_data_provider_requests_per_minute <= configured.market_data_global_requests_per_minute
    with pytest.raises(ValueError, match="per-provider request budget"):
        DataConfig(market_data_global_requests_per_minute=10, market_data_provider_requests_per_minute=11)
    with pytest.raises(ValueError, match="deep candidate limit"):
        DataConfig(market_data_deep_candidate_limit=31, market_data_deep_subscription_limit=30)
    with pytest.raises(ValueError, match="maximum age must cover"):
        DataConfig(
            breadth_poll_interval_seconds=15.0,
            market_data_rank_observation_max_age_seconds=14.0,
        )


@pytest.mark.parametrize(
    "field_name",
    [
        "breadth_poll_interval_seconds",
        "market_data_batch_size",
        "market_data_max_concurrency",
        "market_data_global_requests_per_minute",
        "market_data_provider_requests_per_minute",
        "market_data_request_timeout_seconds",
        "market_data_callback_timeout_seconds",
        "market_data_shutdown_timeout_seconds",
        "market_data_max_retries",
        "market_data_backoff_base_seconds",
        "market_data_backoff_max_seconds",
        "market_data_circuit_failure_threshold",
        "market_data_circuit_cooldown_seconds",
        "market_data_job_queue_size",
        "market_data_failure_history_size",
        "market_data_event_dedupe_history_size",
        "market_data_order_book_levels_per_side",
        "market_data_observations_per_symbol",
        "market_data_rank_min_observations",
        "market_data_rank_refresh_seconds",
        "market_data_rank_observation_max_age_seconds",
        "market_data_deep_candidate_limit",
        "market_data_deep_subscription_limit",
        "market_data_min_residence_seconds",
    ],
)
def test_data_config_rejects_boolean_numeric_transport_controls(field_name: str):
    with pytest.raises(ValueError, match="boolean values are invalid"):
        DataConfig(**{field_name: True})
