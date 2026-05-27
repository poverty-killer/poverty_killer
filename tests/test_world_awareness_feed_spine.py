from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.api.operator_readonly_api import OperatorSnapshotProvider, get_operator_router
from app.world_awareness.adapters.alpaca_news import AlpacaNewsAdapter
from app.world_awareness.adapters.economic_calendar import EconomicCalendarAdapter
from app.world_awareness.adapters.insider_transactions import FinnhubInsiderAdapter, SecInsiderFilingsAdapter
from app.world_awareness.config import ExternalFeedProviderConfig, WorldAwarenessConfig
from app.world_awareness.enums import (
    DirectionalityHint,
    ExternalFeedStatus,
    ExternalFeedType,
    ExternalVerificationStatus,
)
from app.world_awareness.feed_spine import build_provider_registry, normalize_external_event, world_awareness_summary


T0 = datetime(2026, 5, 26, 12, 0, tzinfo=timezone.utc)


def test_external_event_normalization_is_advisory_and_non_trading():
    event = normalize_external_event(
        provider="alpaca_news",
        feed_type=ExternalFeedType.NEWS,
        payload={
            "id": "news-1",
            "symbols": ["BTC/USD"],
            "asset_class": "crypto",
            "title": "Fixture headline",
            "summary": "Fixture only.",
            "published_at": T0.isoformat(),
            "sentiment": "0.65",
            "confidence": 0.8,
            "relevance": 0.9,
            "verification_status": "confirmed",
            "source_url": "https://example.test/news-1",
        },
        received_time=T0 + timedelta(minutes=1),
    )

    assert event.event_id == "news-1"
    assert event.provider == "alpaca_news"
    assert event.feed_type == ExternalFeedType.NEWS
    assert event.symbols == ["BTC/USD"]
    assert event.direction_hint == DirectionalityHint.BULLISH
    assert event.verification_status == ExternalVerificationStatus.CONFIRMED
    assert event.advisory_only is True
    assert event.decisionframe_eligible is False
    assert event.can_trade() is False
    evidence = event.to_decisionframe_evidence()
    assert evidence["authority_class"] == "ADVISORY"
    assert evidence["signal"] == "NONE"
    assert evidence["score_delta"] == 0.0
    assert "ADVISORY_ONLY_NO_TRADE_AUTHORITY" in evidence["reason_codes"]


def test_stale_event_is_marked_stale_and_cannot_be_fresh_truth():
    event = normalize_external_event(
        provider="economic_calendar",
        feed_type=ExternalFeedType.ECONOMIC_CALENDAR,
        payload={
            "event_id": "macro-old",
            "topic": "macro",
            "event_time": (T0 - timedelta(days=2)).isoformat(),
            "verification_status": "confirmed",
        },
        received_time=T0,
        stale_after_seconds=3600,
    )

    assert event.stale is True
    assert event.verification_status == ExternalVerificationStatus.STALE
    assert "FEED_STALE" in event.reason_codes


def test_provider_registry_is_disabled_by_default_and_credentials_are_not_printed():
    registry = build_provider_registry(WorldAwarenessConfig(), env={})
    by_provider = {entry.provider_name: entry for entry in registry}

    assert by_provider["alpaca_news"].status == ExternalFeedStatus.FEED_DISABLED
    assert by_provider["finnhub_insider"].status == ExternalFeedStatus.FEED_DISABLED
    assert all(entry.advisory_only is True for entry in registry)
    assert all("secret" not in repr(entry).lower() for entry in registry)


def test_enabled_provider_without_required_key_fails_soft_as_missing_credential():
    cfg = WorldAwarenessConfig(
        alpaca_news=ExternalFeedProviderConfig(
            provider_name="alpaca_news",
            enabled=True,
            credential_env_keys=["APCA_API_KEY_ID", "APCA_API_SECRET_KEY"],
        )
    )

    entry = build_provider_registry(cfg, env={"APCA_API_KEY_ID": "present"})[0]

    assert entry.provider_name == "alpaca_news"
    assert entry.status == ExternalFeedStatus.CREDENTIAL_MISSING
    assert "CREDENTIAL_MISSING" in entry.reason_codes


def test_insider_adapters_are_equity_advisory_not_crypto_execution_authority():
    sec = SecInsiderFilingsAdapter()
    finnhub = FinnhubInsiderAdapter()

    sec_event = sec.normalize_payload({"id": "form4-1", "ticker": "AAPL", "transaction_date": T0.isoformat()})
    finnhub_event = finnhub.normalize_payload({"id": "fh-1", "symbol": "MSFT", "transaction_date": T0.isoformat()})

    assert sec_event.asset_class == "equity"
    assert finnhub_event.asset_class == "equity"
    assert sec_event.feed_type == ExternalFeedType.SEC_FILING
    assert finnhub_event.feed_type == ExternalFeedType.INSIDER_TRANSACTION
    assert sec_event.can_trade() is False
    assert finnhub_event.to_decisionframe_evidence()["signal"] == "NONE"


def test_safe_adapters_do_not_fetch_live_data_by_default():
    adapters = [
        AlpacaNewsAdapter(),
        SecInsiderFilingsAdapter(),
        FinnhubInsiderAdapter(),
        EconomicCalendarAdapter(),
    ]

    for adapter in adapters:
        assert adapter.fetch() == []
        status = adapter.status(env={})
        assert status.status in {ExternalFeedStatus.FEED_DISABLED, ExternalFeedStatus.CREDENTIAL_MISSING}


def test_world_awareness_summary_is_advisory_only_and_counts_events():
    fresh = normalize_external_event(
        provider="alpaca_news",
        feed_type=ExternalFeedType.NEWS,
        payload={"event_id": "fresh", "symbol": "BTC/USD", "event_time": T0.isoformat(), "relevance": 0.9},
        received_time=T0,
    )
    stale = normalize_external_event(
        provider="economic_calendar",
        feed_type=ExternalFeedType.ECONOMIC_CALENDAR,
        payload={"event_id": "stale", "event_time": (T0 - timedelta(days=5)).isoformat()},
        received_time=T0,
        stale_after_seconds=60,
    )

    summary = world_awareness_summary(events=[fresh, stale])

    assert summary["authority_class"] == "ADVISORY"
    assert summary["direct_trade_authority"] is False
    assert summary["event_count"] == 2
    assert summary["advisory_event_count"] == 2
    assert summary["stale_event_count"] == 1
    assert summary["high_relevance_event_count"] == 1
    assert summary["decisionframe_eligible_count"] == 0


def test_operator_world_awareness_endpoint_safe_defaults():
    provider = OperatorSnapshotProvider()
    summary = provider.world_awareness()
    assert summary["feed_can_trade"] is False
    assert summary["market_truth_bypass_allowed"] is False
    assert summary["netedge_bypass_allowed"] is False
    assert summary["guardrail_bypass_allowed"] is False

    routes = {route.path for route in get_operator_router(provider).routes}
    assert "/operator/world-awareness" in routes
