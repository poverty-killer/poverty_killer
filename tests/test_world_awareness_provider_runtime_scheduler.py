from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

from app.api.operator_readonly_api import OperatorSnapshotProvider, create_operator_app
from app.world_awareness.adapters.alpaca_news import AlpacaNewsAdapter, AlpacaNewsRateLimitError
from app.world_awareness.config import ExternalFeedProviderConfig, WorldAwarenessConfig
from app.world_awareness.enums import ExternalFeedStatus
from app.world_awareness.feed_spine import WorldAwarenessEventCache
from app.world_awareness.scheduler import WorldAwarenessProviderRuntime


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


def _enabled_config() -> ExternalFeedProviderConfig:
    return ExternalFeedProviderConfig(
        provider_name="alpaca_news",
        enabled=True,
        credential_env_keys=["APCA_API_KEY_ID", "APCA_API_SECRET_KEY"],
        min_poll_interval_seconds=60,
        backoff_seconds=600,
        max_items_per_fetch=25,
        stale_after_seconds=3600,
    )


def _runtime(client) -> WorldAwarenessProviderRuntime:
    config = WorldAwarenessConfig(alpaca_news=_enabled_config())
    adapter = AlpacaNewsAdapter(config=config.alpaca_news, client=client)
    return WorldAwarenessProviderRuntime(
        config=config,
        cache=WorldAwarenessEventCache(),
        env=ENV,
        adapters={"alpaca_news": adapter},
    )


def _endpoint(app, path: str, method: str = "GET"):
    for route in app.routes:
        if route.path == path and method in (route.methods or set()):
            return route.endpoint
    raise AssertionError(f"route not found: {method} {path}")


def test_provider_runtime_does_not_auto_start_or_poll_on_init():
    client = FakeAlpacaNewsClient([{"id": "not-polled"}])
    runtime = _runtime(client)
    snapshot = runtime.status_snapshot(as_of_utc=T0)

    assert snapshot["auto_start"] is False
    assert snapshot["manual_poll_only"] is True
    assert snapshot["provider_polling_active"] is False
    assert snapshot["feed_can_trade"] is False
    assert snapshot["decisionframe_score_impact"] == 0.0
    assert client.calls == []


def test_due_calculation_refuses_disabled_and_accepts_enabled_when_due():
    disabled = WorldAwarenessProviderRuntime(config=WorldAwarenessConfig(), cache=WorldAwarenessEventCache(), env=ENV)
    disabled_decision = disabled.due_decision("alpaca_news", as_of_utc=T0, force=True)

    enabled = _runtime(FakeAlpacaNewsClient([]))
    enabled_decision = enabled.due_decision("alpaca_news", as_of_utc=datetime(2100, 1, 1, tzinfo=timezone.utc))

    assert disabled_decision.allowed is False
    assert disabled_decision.reason_code == "FEED_DISABLED"
    assert enabled_decision.allowed is True
    assert enabled_decision.reason_code == "PROVIDER_DUE"


def test_manual_poll_updates_cache_and_next_poll_without_trading_authority():
    client = FakeAlpacaNewsClient(
        [
            {
                "id": "poll-1",
                "headline": "Runtime poll fixture",
                "symbols": ["BTC/USD"],
                "created_at": T0.isoformat(),
            }
        ]
    )
    runtime = _runtime(client)

    result = runtime.poll_provider("alpaca_news", as_of_utc=T0, force=True, symbols=["BTC/USD"], limit=10)
    snapshot = runtime.status_snapshot(as_of_utc=T0 + timedelta(seconds=1))

    assert result["allowed"] is True
    assert result["status"] == "POLL_COMPLETE"
    assert result["events_added"] == 1
    assert result["broker_call_occurred"] is False
    assert result["trade_authority"] is False
    assert result["decisionframe_score_impact"] == 0.0
    assert client.calls[0]["symbols"] == "BTC/USD"
    provider = snapshot["providers"][0]
    assert provider["poll_count"] == 1
    assert provider["last_added_count"] == 1
    assert provider["next_poll_time"] == (T0 + timedelta(seconds=60)).isoformat()
    assert snapshot["cache"]["event_count"] == 1


def test_manual_poll_dedupes_repeated_events():
    client = FakeAlpacaNewsClient(
        [
            {
                "id": "dup-runtime",
                "headline": "Duplicate runtime fixture",
                "symbols": ["ETH/USD"],
                "created_at": T0.isoformat(),
            }
        ]
    )
    runtime = _runtime(client)

    first = runtime.poll_provider("alpaca_news", as_of_utc=T0, force=True)
    second = runtime.poll_provider("alpaca_news", as_of_utc=T0 + timedelta(seconds=1), force=True)

    assert first["events_added"] == 1
    assert second["events_added"] == 0
    assert second["duplicates_ignored"] == 1
    assert runtime.status_snapshot()["cache"]["duplicate_event_ignored_count"] == 1


def test_rate_limit_uses_backoff_and_fails_soft():
    runtime = _runtime(RateLimitedClient())

    result = runtime.poll_provider("alpaca_news", as_of_utc=T0, force=True)
    provider = runtime.status_snapshot(as_of_utc=T0)["providers"][0]

    assert result["allowed"] is True
    assert result["status"] == "POLL_FAILED_SOFT"
    assert result["provider_status"] == ExternalFeedStatus.FEED_RATE_LIMITED.value
    assert provider["error_count"] == 1
    assert provider["consecutive_error_count"] == 1
    assert provider["next_poll_time"] == (T0 + timedelta(seconds=600)).isoformat()


def test_operator_manual_poll_endpoint_is_read_only_and_does_not_expose_secrets():
    runtime = _runtime(
        FakeAlpacaNewsClient(
            [
                {
                    "id": "operator-poll-1",
                    "headline": "Operator poll fixture",
                    "symbols": ["SOL/USD"],
                    "created_at": T0.isoformat(),
                }
            ]
        )
    )
    provider = OperatorSnapshotProvider(world_awareness_runtime=runtime)
    app = create_operator_app(provider=provider)

    status = _endpoint(app, "/operator/world-awareness/runtime")()
    result = _endpoint(app, "/operator/intent/world-awareness/poll", "POST")(
        {"provider": "alpaca_news", "force": True, "symbols": ["SOL/USD"], "limit": 5}
    )
    summary = _endpoint(app, "/operator/world-awareness")()
    serialized = json.dumps({"status": status, "result": result, "summary": summary}, default=str)

    assert status["manual_poll_only"] is True
    assert result["allowed"] is True
    assert result["broker_call_occurred"] is False
    assert result["runtime_mutation_occurred"] is False
    assert result["trading_mutation_occurred"] is False
    assert result["world_awareness_cache_mutation_occurred"] is True
    assert result["live_endpoint_touched"] is False
    assert result["real_money_touched"] is False
    assert summary["event_count"] == 1
    assert summary["events"][0]["advisory_only"] is True
    assert summary["events"][0]["decisionframe_eligible"] is False
    assert "test-key-id" not in serialized
    assert "test-secret-key" not in serialized
