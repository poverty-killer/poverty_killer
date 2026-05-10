from pathlib import Path

from app.world_awareness.config import PersistenceConfig
from app.world_awareness.enums import (
    DecayProfileName,
    NormalizedEventClass,
    SourceFamily,
    SourceLatencyClass,
    TrustTier,
)
from app.world_awareness.models import (
    EventIdentity,
    EventTiming,
    SourceDescriptor,
    WorldAwarenessEvent,
)
from app.world_awareness.persistence import WorldAwarenessRepository


def test_repository_appends_and_loads_normalized_events(tmp_path: Path):
    repo = WorldAwarenessRepository(
        PersistenceConfig(storage_root=str(tmp_path))
    )

    event = WorldAwarenessEvent(
        source=SourceDescriptor(
            source_family=SourceFamily.SEC_EDGAR,
            source_name="data.sec.gov",
            trust_tier=TrustTier.FREE_PRIMARY,
            source_latency_class=SourceLatencyClass.SOURCE_DEPENDENT,
        ),
        identity=EventIdentity(
            event_id="evt_1",
            dedupe_key="dedupe_1",
            source_event_type="10-k",
            normalized_event_class=NormalizedEventClass.REGULATORY_FILING,
        ),
        timing=EventTiming(
            discovery_timestamp_utc=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
            decay_profile=DecayProfileName.REGULATORY_FILING_FRESH,
        ),
    )

    repo.append_normalized_event(event)
    rows = repo.load_normalized_events()

    assert len(rows) == 1
    assert rows[0]["identity"]["event_id"] == "evt_1"
