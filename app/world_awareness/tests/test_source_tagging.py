from app.world_awareness.enums import ConfidenceHint, SourceFamily, TrustTier
from app.world_awareness.trust import (
    base_trust_tier_for_source,
    default_confidence_for_source,
    trust_score_for_source,
)


def test_official_release_family_maps_to_official_primary():
    trust_tier = base_trust_tier_for_source(SourceFamily.OFFICIAL_ISSUER_RELEASES)
    confidence = default_confidence_for_source(SourceFamily.OFFICIAL_ISSUER_RELEASES)

    assert trust_tier == TrustTier.OFFICIAL_PRIMARY_PUBLIC
    assert confidence == ConfidenceHint.VERY_HIGH


def test_sec_edgar_maps_to_free_primary():
    trust_tier = base_trust_tier_for_source(SourceFamily.SEC_EDGAR)
    score = trust_score_for_source(SourceFamily.SEC_EDGAR)

    assert trust_tier == TrustTier.FREE_PRIMARY
    assert score > 0.5


def test_secondary_sources_map_below_official_primary():
    openinsider_score = trust_score_for_source(SourceFamily.OPENINSIDER)
    official_score = trust_score_for_source(SourceFamily.OFFICIAL_CALENDARS)

    assert official_score > openinsider_score
