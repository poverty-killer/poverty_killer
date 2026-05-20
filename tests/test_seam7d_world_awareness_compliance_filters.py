from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.world_awareness.adapters.capitol_trades import CapitolTradesAdapter
from app.world_awareness.adapters.official_calendars import OfficialCalendarsAdapter
from app.world_awareness.adapters.official_releases import OfficialReleasesAdapter
from app.world_awareness.adapters.openinsider import OpenInsiderAdapter
from app.world_awareness.adapters.quiver_free import QuiverFreeAdapter
from app.world_awareness.adapters.sec_edgar import SecEdgarAdapter
from app.world_awareness.config import PersistenceConfig, WorldAwarenessConfig
from app.world_awareness.decay import decay_weight
from app.world_awareness.dedupe import dedupe_events, is_duplicate
from app.world_awareness.enums import ConfidenceHint, NormalizedEventClass, SourceFamily
from app.world_awareness.models import WorldAwarenessEvent
from app.world_awareness.normalizer import normalize_source_payload
from app.world_awareness.persistence import WorldAwarenessRepository
from app.world_awareness.replay import build_replay_checkpoint, is_replay_duplicate
from app.world_awareness.scheduler import build_schedule, due_tasks
from app.world_awareness.source_catalog import (
    build_source_catalog,
    get_source_descriptor,
    source_status_signature,
)
from app.world_awareness.trust import trust_score_for_source


CONTRIBUTION_KEYS = {
    "module_name",
    "source_name",
    "status",
    "input_truth",
    "output_summary",
    "effect",
    "reason",
}


def _assert_contribution_shape(evidence: dict[str, str]) -> None:
    assert set(evidence) == CONTRIBUTION_KEYS
    assert all(isinstance(value, str) and value for value in evidence.values())


def _fixture_payload(symbol: str = "AAPL") -> dict[str, object]:
    return {
        "symbol": symbol,
        "issuer": "Fixture Issuer",
        "actor": "Fixture Actor",
        "source_event_type": "deterministic_cache_fixture",
        "fixture_only": True,
    }


def _advisory_evidence(
    *,
    module_name: str,
    source_name: str,
    status: str,
    effect: str,
    reason: str,
) -> dict[str, str]:
    return {
        "module_name": module_name,
        "source_name": source_name,
        "status": status,
        "input_truth": "deterministic_local_cache_fixture",
        "output_summary": "normalized advisory event; canonical_truth_claimed=false live_attached=false",
        "effect": effect,
        "reason": reason,
    }


def test_source_catalog_reports_blocked_cache_and_replay_statuses_without_fetching():
    catalog = build_source_catalog()
    assert SourceFamily.SEC_EDGAR in catalog
    assert all(descriptor.integration_status == "not_live_attached" for descriptor in catalog.values())

    live_blocked = source_status_signature(SourceFamily.SEC_EDGAR)
    _assert_contribution_shape(live_blocked)
    assert live_blocked["status"] == "INTENTIONALLY_BLOCKED_LIVE_ONLY"
    assert live_blocked["effect"] == "INTENTIONALLY_BLOCKED"

    cache_ready = source_status_signature(SourceFamily.OPENINSIDER, local_cache_available=True)
    _assert_contribution_shape(cache_ready)
    assert cache_ready["status"] == "ACTIVE_LOCAL_CACHE"

    replay_ready = source_status_signature(SourceFamily.CAPITOL_TRADES, replay_available=True)
    _assert_contribution_shape(replay_ready)
    assert replay_ready["status"] == "ACTIVE_REPLAY"

    premium_blocked = source_status_signature(SourceFamily.QUIVER_FREE)
    _assert_contribution_shape(premium_blocked)
    assert premium_blocked["status"] == "INTENTIONALLY_BLOCKED_PREMIUM_KEY_MISSING"


def test_openinsider_adapter_normalizes_cache_fixture_or_returns_missing_truth():
    adapter = OpenInsiderAdapter()
    assert adapter.fetch() == []
    assert adapter.fetch_and_normalize() == []

    event = adapter.normalize_payload(_fixture_payload("MSFT"))
    assert event.identity.normalized_event_class == NormalizedEventClass.INSIDER_ACTIVITY
    assert event.attribution.symbol_candidates == ["MSFT"]
    assert event.canonical_truth_claimed is False
    assert event.live_attached is False

    evidence = _advisory_evidence(
        module_name="OpenInsiderAdapter",
        source_name=event.source.source_name,
        status="ACTIVE_CACHE_SIGNAL",
        effect="INSIDER_PUBLIC_FILING_ADVISORY",
        reason="LOCAL_CACHE_FIXTURE_NORMALIZED_NOT_MNPI",
    )
    _assert_contribution_shape(evidence)


def test_sec_edgar_adapter_normalizes_filing_metadata_without_scraping():
    adapter = SecEdgarAdapter()
    assert adapter.fetch() == []

    event = adapter.normalize_payload({**_fixture_payload("NVDA"), "form_type": "8-K"})
    assert event.identity.normalized_event_class == NormalizedEventClass.REGULATORY_FILING
    assert event.hints.confidence_hint == ConfidenceHint.HIGH
    assert event.canonical_truth_claimed is False

    evidence = _advisory_evidence(
        module_name="SecEdgarAdapter",
        source_name=event.source.source_name,
        status="ACTIVE_CACHE_SIGNAL",
        effect="SEC_FILING_ADVISORY",
        reason="LOCAL_CACHE_FIXTURE_NORMALIZED_NO_LIVE_EDGAR_CALL",
    )
    _assert_contribution_shape(evidence)


def test_capitol_trades_adapter_normalizes_disclosure_fixture_without_fabricating_trade_truth():
    adapter = CapitolTradesAdapter()
    assert adapter.fetch() == []

    event = adapter.normalize_payload(_fixture_payload("TSLA"))
    assert event.identity.normalized_event_class == NormalizedEventClass.POLITICAL_DISCLOSURE
    assert event.hints.confidence_hint == ConfidenceHint.MEDIUM
    assert event.canonical_truth_claimed is False

    evidence = _advisory_evidence(
        module_name="CapitolTradesAdapter",
        source_name=event.source.source_name,
        status="ACTIVE_CACHE_SIGNAL",
        effect="LEGISLATIVE_TRADE_ADVISORY",
        reason="LOCAL_CACHE_FIXTURE_NORMALIZED_DISCLOSURE_DELAYED",
    )
    _assert_contribution_shape(evidence)


def test_quiver_free_adapter_blocks_unconfigured_premium_or_normalizes_cache_fixture():
    blocked = source_status_signature(SourceFamily.QUIVER_FREE)
    assert blocked["status"] == "INTENTIONALLY_BLOCKED_PREMIUM_KEY_MISSING"

    adapter = QuiverFreeAdapter()
    assert adapter.fetch() == []
    event = adapter.normalize_payload(_fixture_payload("AMZN"))
    assert event.identity.normalized_event_class == NormalizedEventClass.ALTERNATIVE_SIGNAL
    assert event.canonical_truth_claimed is False

    evidence = _advisory_evidence(
        module_name="QuiverFreeAdapter",
        source_name=event.source.source_name,
        status="ACTIVE_CACHE_SIGNAL",
        effect="WORLD_AWARENESS_EVENT",
        reason="LOCAL_CACHE_FIXTURE_NORMALIZED_NO_PREMIUM_CALL",
    )
    _assert_contribution_shape(evidence)


def test_official_calendar_and_release_adapters_normalize_fixture_or_report_missing():
    calendar = OfficialCalendarsAdapter()
    release = OfficialReleasesAdapter()
    assert calendar.fetch() == []
    assert release.fetch() == []

    calendar_event = calendar.normalize_payload(_fixture_payload("SPY"))
    release_event = release.normalize_payload(_fixture_payload("GOOGL"))

    assert calendar_event.identity.normalized_event_class == NormalizedEventClass.CALENDAR_EVENT
    assert release_event.identity.normalized_event_class == NormalizedEventClass.ISSUER_RELEASE
    assert calendar_event.canonical_truth_claimed is False
    assert release_event.live_attached is False

    calendar_evidence = _advisory_evidence(
        module_name="OfficialCalendarsAdapter",
        source_name=calendar_event.source.source_name,
        status="ACTIVE_CACHE_SIGNAL",
        effect="OFFICIAL_CALENDAR_ADVISORY",
        reason="LOCAL_CACHE_FIXTURE_NORMALIZED_NO_LIVE_CALENDAR_CALL",
    )
    release_evidence = _advisory_evidence(
        module_name="OfficialReleasesAdapter",
        source_name=release_event.source.source_name,
        status="ACTIVE_CACHE_SIGNAL",
        effect="OFFICIAL_RELEASE_ADVISORY",
        reason="LOCAL_CACHE_FIXTURE_NORMALIZED_NO_LIVE_RELEASE_CALL",
    )
    _assert_contribution_shape(calendar_evidence)
    _assert_contribution_shape(release_evidence)


def test_normalizer_dedupe_decay_and_trust_are_deterministic_on_provided_events():
    event_ts = datetime(2026, 5, 20, 14, 30, tzinfo=timezone.utc)
    event_1 = normalize_source_payload(
        source_family=SourceFamily.SEC_EDGAR,
        source_event_type="fixture_filing",
        raw_payload=_fixture_payload("AAPL"),
        event_timestamp_utc=event_ts,
    )
    event_2 = normalize_source_payload(
        source_family=SourceFamily.SEC_EDGAR,
        source_event_type="fixture_filing",
        raw_payload=_fixture_payload("AAPL"),
        event_timestamp_utc=event_ts,
    )
    event_3 = normalize_source_payload(
        source_family=SourceFamily.SEC_EDGAR,
        source_event_type="fixture_filing",
        raw_payload=_fixture_payload("MSFT"),
        event_timestamp_utc=event_ts,
    )

    assert is_duplicate(event_2, [event_1]) is True
    deduped = dedupe_events([event_1, event_2, event_3])
    assert [event.identity.dedupe_key for event in deduped] == [
        event_1.identity.dedupe_key,
        event_3.identity.dedupe_key,
    ]

    assert decay_weight(event_1.timing.discovery_timestamp_utc, event_1.timing.fresh_until_utc, event_1.timing.discovery_timestamp_utc) == 1.0
    stale_weight = decay_weight(
        event_1.timing.fresh_until_utc + timedelta(days=2),
        event_1.timing.fresh_until_utc,
        event_1.timing.discovery_timestamp_utc,
    )
    assert 0.0 <= stale_weight <= 1.0
    assert trust_score_for_source(SourceFamily.SEC_EDGAR) > trust_score_for_source(SourceFamily.OPENINSIDER)


def test_persistence_and_replay_label_cache_and_replay_truth(tmp_path):
    config = PersistenceConfig(storage_root=str(tmp_path))
    repository = WorldAwarenessRepository(config)
    event = normalize_source_payload(
        source_family=SourceFamily.OFFICIAL_CALENDARS,
        source_event_type="fixture_calendar",
        raw_payload=_fixture_payload("QQQ"),
    )

    repository.append_normalized_event(event)
    rows = repository.load_normalized_events()
    assert len(rows) == 1
    assert rows[0]["canonical_truth_claimed"] is False
    assert rows[0]["live_attached"] is False
    assert rows[0]["replay"]["replayable"] is True

    checkpoint = build_replay_checkpoint(event)
    assert checkpoint.event_id == event.identity.event_id
    assert checkpoint.dedupe_key == event.identity.dedupe_key
    assert is_replay_duplicate(event, [event]) is True

    evidence = {
        "module_name": "WorldAwarenessRepository",
        "source_name": event.source.source_name,
        "status": "ACTIVE_REPLAY",
        "input_truth": "local_tmp_cache_replay",
        "output_summary": "persisted normalized event with canonical_truth_claimed=false live_attached=false",
        "effect": "SOURCE_STATUS",
        "reason": "CACHE_REPLAY_LABELED",
    }
    _assert_contribution_shape(evidence)


def test_scheduler_builds_due_tasks_without_fetching_or_network_calls():
    config = WorldAwarenessConfig()
    tasks = build_schedule(config)
    assert {task.source_family for task in tasks} == set(SourceFamily)

    future_due = due_tasks(tasks, max(task.next_run_utc for task in tasks) + timedelta(seconds=1))
    assert {task.source_family for task in future_due} == set(SourceFamily)

    disabled_config = WorldAwarenessConfig()
    disabled_config.openinsider.enabled = False
    disabled_tasks = build_schedule(disabled_config)
    disabled_due = due_tasks(disabled_tasks, max(task.next_run_utc for task in disabled_tasks) + timedelta(seconds=1))
    assert SourceFamily.OPENINSIDER not in {task.source_family for task in disabled_due}


def test_target_world_awareness_modules_do_not_expose_broker_or_live_trading_authority():
    objects = [
        OpenInsiderAdapter(),
        SecEdgarAdapter(),
        CapitolTradesAdapter(),
        QuiverFreeAdapter(),
        OfficialCalendarsAdapter(),
        OfficialReleasesAdapter(),
        WorldAwarenessRepository(PersistenceConfig(storage_root="state/world_awareness_test", create_dirs_if_missing=False)),
    ]
    forbidden = {
        "submit_order",
        "cancel_order",
        "replace_order",
        "rebalance",
        "liquidate",
        "broker_gateway",
        "order_router",
        "execution_engine",
    }

    for obj in objects:
        for attr in forbidden:
            assert not hasattr(obj, attr), f"{type(obj).__name__} exposes {attr}"

    for descriptor in build_source_catalog().values():
        assert descriptor.integration_status == "not_live_attached"
