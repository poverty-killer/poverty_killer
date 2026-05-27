from __future__ import annotations

from datetime import datetime, timezone

from app.world_awareness.enums import ExternalFeedType
from app.world_awareness.models import ExternalIntelligenceEvent
from app.world_awareness.persistent_cache import PersistentWorldAwarenessEventCache


T0 = datetime(2026, 5, 27, 12, 0, tzinfo=timezone.utc)


def _event(event_id: str) -> ExternalIntelligenceEvent:
    return ExternalIntelligenceEvent(
        event_id=event_id,
        provider="alpaca_news",
        feed_type=ExternalFeedType.NEWS,
        symbols=["BTC/USD"],
        title=f"fixture {event_id}",
        received_time=T0,
        advisory_only=True,
        decisionframe_eligible=False,
    )


def test_persistent_world_awareness_cache_dedupes_across_reload(tmp_path):
    path = tmp_path / "world" / "events.jsonl"
    cache = PersistentWorldAwarenessEventCache(max_events=10, path=path)

    added, duplicates = cache.upsert([_event("event-1")])
    reloaded = PersistentWorldAwarenessEventCache(max_events=10, path=path)
    added_again, duplicates_again = reloaded.upsert([_event("event-1")])

    assert added == 1
    assert duplicates == 0
    assert added_again == 0
    assert duplicates_again == 1
    assert reloaded.status()["event_count"] == 1
    assert reloaded.events()[0].can_trade() is False


def test_persistent_world_awareness_cache_respects_max_event_cap(tmp_path):
    path = tmp_path / "world" / "events.jsonl"
    cache = PersistentWorldAwarenessEventCache(max_events=2, path=path)

    cache.upsert([_event("event-1"), _event("event-2"), _event("event-3")])
    rows = cache.events(limit=10)

    assert len(rows) == 2
    assert {row.event_id for row in rows} == {"event-2", "event-3"}


def test_persistent_world_awareness_cache_handles_corrupt_lines(tmp_path):
    path = tmp_path / "world" / "events.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("not-json\n", encoding="utf-8")

    cache = PersistentWorldAwarenessEventCache(max_events=10, path=path)

    assert cache.status()["status"] == "DEGRADED"
    assert cache.status()["corrupt_line_count"] == 1
