from datetime import datetime, timezone

from app.world_awareness.enums import (
    ConfidenceHint,
    DecayProfileName,
    DirectionalityHint,
    MagnitudeHint,
    NormalizedEventClass,
    SourceFamily,
    SourceLatencyClass,
    TrustTier,
)
from app.world_awareness.models import (
    EventAttribution,
    EventHints,
    EventIdentity,
    EventTiming,
    ReplayMetadata,
    SourceDescriptor,
    WorldAwarenessEvent,
)


def test_world_awareness_event_defaults_to_non_authoritative():
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
            source_event_type="filing",
            normalized_event_class=NormalizedEventClass.REGULATORY_FILING,
        ),
        timing=EventTiming(
            discovery_timestamp_utc=datetime.now(timezone.utc),
            decay_profile=DecayProfileName.REGULATORY_FILING_FRESH,
        ),
        attribution=EventAttribution(symbol_candidates=["AAPL"]),
        hints=EventHints(
            directionality_hint=DirectionalityHint.UNKNOWN,
            magnitude_hint=MagnitudeHint.UNKNOWN,
            confidence_hint=ConfidenceHint.HIGH,
        ),
        replay=ReplayMetadata(),
    )

    assert event.canonical_truth_claimed is False
    assert event.live_attached is False
    assert event.is_authoritative() is False
    assert event.requires_future_integration_decision() is True
