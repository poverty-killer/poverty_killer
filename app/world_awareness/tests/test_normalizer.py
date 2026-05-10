from app.world_awareness.enums import NormalizedEventClass, SourceFamily
from app.world_awareness.normalizer import normalize_source_payload


def test_normalizer_builds_subordinate_event_for_sec_payload():
    payload = {
        "symbol": "AAPL",
        "issuer": "Apple Inc.",
        "source_event_type": "10-k",
    }

    event = normalize_source_payload(
        source_family=SourceFamily.SEC_EDGAR,
        source_event_type="10-k",
        raw_payload=payload,
    )

    assert event.source.source_family == SourceFamily.SEC_EDGAR
    assert event.identity.normalized_event_class == NormalizedEventClass.REGULATORY_FILING
    assert event.attribution.symbol_candidates == ["AAPL"]
    assert event.canonical_truth_claimed is False
    assert event.live_attached is False


def test_normalizer_uses_source_family_mapping_for_openinsider():
    payload = {
        "ticker": "MSFT",
        "insider": "John Doe",
    }

    event = normalize_source_payload(
        source_family=SourceFamily.OPENINSIDER,
        source_event_type="insider_trade",
        raw_payload=payload,
    )

    assert event.source.source_family == SourceFamily.OPENINSIDER
    assert event.identity.normalized_event_class == NormalizedEventClass.INSIDER_ACTIVITY
    assert event.attribution.symbol_candidates == ["MSFT"]
    assert event.attribution.actor_candidates == ["John Doe"]
