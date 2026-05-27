from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

from app.api.operator_readonly_api import OperatorSnapshotProvider, create_operator_app
from app.world_awareness.adapters.alpaca_news import AlpacaNewsAdapter, AlpacaNewsRateLimitError
from app.world_awareness.config import ExternalFeedProviderConfig, WorldAwarenessConfig
from app.world_awareness.enums import ExternalFeedStatus, ExternalVerificationStatus
from app.world_awareness.feed_spine import WorldAwarenessEventCache


T0 = datetime(2026, 5, 26, 12, 0, tzinfo=timezone.utc)
ENV = {"APCA_API_KEY_ID": "test-key-id", "APCA_API_SECRET_KEY": "test-secret-key"}


class FakeAlpacaNewsClient:
    def __init__(self, payloads):
        self.payloads = payloads
        self.calls = []

    def get_news(self, **params):
        self.calls.append(params)
        return {"news": self.payloads}


class RateLimitedClient:
    def get_news(self, **_params):
        raise AlpacaNewsRateLimitError("fixture rate limit")


class NetworkFailureClient:
    def get_news(self, **_params):
        raise OSError("fixture network failure")


class StatusCodeRateLimitClient:
    def get_news(self, **_params):
        error = RuntimeError("fixture generic rate limit")
        error.status_code = 429
        raise error


def _enabled_config(stale_after_seconds: int = 3600) -> ExternalFeedProviderConfig:
    return ExternalFeedProviderConfig(
        provider_name="alpaca_news",
        enabled=True,
        credential_env_keys=["APCA_API_KEY_ID", "APCA_API_SECRET_KEY"],
        max_items_per_fetch=10,
        stale_after_seconds=stale_after_seconds,
    )


def _endpoint(app, path: str):
    for route in app.routes:
        if route.path == path and "GET" in (route.methods or set()):
            return route.endpoint
    raise AssertionError(f"route not found: {path}")


def test_alpaca_news_provider_disabled_by_default():
    adapter = AlpacaNewsAdapter()

    status = adapter.status(env=ENV)
    poll = adapter.poll(env=ENV, received_time=T0)

    assert status.status == ExternalFeedStatus.FEED_DISABLED
    assert poll.status == ExternalFeedStatus.FEED_DISABLED
    assert poll.events == ()
    assert poll.provider_snapshot.status == ExternalFeedStatus.FEED_DISABLED


def test_alpaca_news_missing_credentials_fails_soft_without_secret_output():
    adapter = AlpacaNewsAdapter(config=_enabled_config())

    poll = adapter.poll(env={"APCA_API_KEY_ID": "present-only"}, received_time=T0)
    serialized = json.dumps(poll.provider_snapshot.__dict__, default=str)

    assert poll.status == ExternalFeedStatus.CREDENTIAL_MISSING
    assert poll.events == ()
    assert "present-only" not in serialized
    assert "test-secret-key" not in serialized


def test_fake_alpaca_news_payload_normalizes_as_advisory_event():
    client = FakeAlpacaNewsClient(
        [
            {
                "id": 101,
                "headline": "Bitcoin ETF fixture headline",
                "summary": "Fixture only.",
                "url": "https://example.test/news/101",
                "symbols": ["BTC/USD"],
                "created_at": T0.isoformat(),
                "sentiment": "0.7",
                "relevance": "0.9",
                "verification_status": "confirmed",
            }
        ]
    )
    adapter = AlpacaNewsAdapter(config=_enabled_config(), client=client)

    result = adapter.poll(env=ENV, symbols=["BTC/USD"], limit=5, received_time=T0 + timedelta(seconds=30))
    event = result.events[0]

    assert result.status == ExternalFeedStatus.FEED_READY
    assert client.calls[0]["symbols"] == "BTC/USD"
    assert client.calls[0]["limit"] == 5
    assert event.event_id == "101"
    assert event.provider == "alpaca_news"
    assert event.symbols == ["BTC/USD"]
    assert event.title == "Bitcoin ETF fixture headline"
    assert event.verification_status == ExternalVerificationStatus.CONFIRMED
    assert event.advisory_only is True
    assert event.decisionframe_eligible is False
    evidence = event.to_decisionframe_evidence()
    assert evidence["signal"] == "NONE"
    assert evidence["score_delta"] == 0.0
    assert event.can_trade() is False


def test_alpaca_news_event_cache_dedupes_by_provider_event_id():
    payload = {
        "id": "dup-1",
        "headline": "Duplicate fixture",
        "symbols": ["ETH/USD"],
        "created_at": T0.isoformat(),
    }
    adapter = AlpacaNewsAdapter(config=_enabled_config(), client=FakeAlpacaNewsClient([payload]))
    result = adapter.poll(env=ENV, received_time=T0)
    cache = WorldAwarenessEventCache(max_events=5)

    added, duplicates = cache.upsert(result.events)
    added_again, duplicates_again = cache.upsert(result.events)

    assert added == 1
    assert duplicates == 0
    assert added_again == 0
    assert duplicates_again == 1
    assert cache.duplicate_event_ignored_count == 1
    assert len(cache.events()) == 1


def test_alpaca_news_stale_payload_marks_provider_stale():
    old_time = T0 - timedelta(hours=5)
    adapter = AlpacaNewsAdapter(
        config=_enabled_config(stale_after_seconds=60),
        client=FakeAlpacaNewsClient(
            [{"id": "old-1", "headline": "Old fixture", "created_at": old_time.isoformat()}]
        ),
    )

    result = adapter.poll(env=ENV, received_time=T0)

    assert result.status == ExternalFeedStatus.FEED_STALE
    assert result.events[0].stale is True
    assert "FEED_STALE" in result.events[0].reason_codes


def test_alpaca_news_rate_limit_and_network_errors_map_to_provider_status():
    rate_limited = AlpacaNewsAdapter(config=_enabled_config(), client=RateLimitedClient())
    unavailable = AlpacaNewsAdapter(config=_enabled_config(), client=NetworkFailureClient())
    generic_rate_limited = AlpacaNewsAdapter(config=_enabled_config(), client=StatusCodeRateLimitClient())

    rate_result = rate_limited.poll(env=ENV, received_time=T0)
    unavailable_result = unavailable.poll(env=ENV, received_time=T0)
    generic_rate_result = generic_rate_limited.poll(env=ENV, received_time=T0)

    assert rate_result.status == ExternalFeedStatus.FEED_RATE_LIMITED
    assert rate_result.provider_snapshot.error_count == 1
    assert unavailable_result.status == ExternalFeedStatus.FEED_UNAVAILABLE
    assert unavailable_result.provider_snapshot.error_count == 1
    assert generic_rate_result.status == ExternalFeedStatus.FEED_RATE_LIMITED


def test_operator_api_returns_cached_world_awareness_provider_and_events():
    adapter = AlpacaNewsAdapter(
        config=_enabled_config(),
        client=FakeAlpacaNewsClient(
            [
                {
                    "id": "api-1",
                    "headline": "Operator API fixture",
                    "symbols": ["SOL/USD"],
                    "created_at": T0.isoformat(),
                }
            ]
        ),
    )
    result = adapter.poll(env=ENV, received_time=T0)
    cache = WorldAwarenessEventCache()
    cache.upsert(result.events)
    cache.mark_provider(result.provider_snapshot)
    config = WorldAwarenessConfig(alpaca_news=_enabled_config())
    provider = OperatorSnapshotProvider(
        world_awareness_cache=cache,
        world_awareness_config=config,
        world_awareness_env=ENV,
    )
    app = create_operator_app(provider=provider)

    summary = _endpoint(app, "/operator/world-awareness")()
    providers = _endpoint(app, "/operator/world-awareness/providers")()
    events = _endpoint(app, "/operator/world-awareness/events")()
    serialized = json.dumps(summary, default=str)

    assert summary["feed_can_trade"] is False
    assert summary["market_truth_bypass_allowed"] is False
    assert summary["netedge_bypass_allowed"] is False
    assert summary["guardrail_bypass_allowed"] is False
    assert providers["providers"][0]["provider"] == "alpaca_news"
    assert events["event_count"] == 1
    assert events["events"][0]["advisory_only"] is True
    assert events["events"][0]["decisionframe_eligible"] is False
    assert "test-key-id" not in serialized
    assert "test-secret-key" not in serialized
