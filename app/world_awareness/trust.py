from __future__ import annotations

from .enums import ConfidenceHint, SourceFamily, TrustTier


def base_trust_tier_for_source(source_family: SourceFamily) -> TrustTier:
    if source_family in {
        SourceFamily.OFFICIAL_ISSUER_RELEASES,
        SourceFamily.OFFICIAL_CALENDARS,
        SourceFamily.OFFICIAL_MACRO_RELEASES,
    }:
        return TrustTier.OFFICIAL_PRIMARY_PUBLIC

    if source_family == SourceFamily.SEC_EDGAR:
        return TrustTier.FREE_PRIMARY

    if source_family in {
        SourceFamily.OPENINSIDER,
        SourceFamily.CAPITOL_TRADES,
        SourceFamily.QUIVER_FREE,
    }:
        return TrustTier.FREE_SECONDARY

    return TrustTier.DERIVED_SECONDARY


def default_confidence_for_source(source_family: SourceFamily) -> ConfidenceHint:
    tier = base_trust_tier_for_source(source_family)

    if tier == TrustTier.OFFICIAL_PRIMARY_PUBLIC:
        return ConfidenceHint.VERY_HIGH
    if tier == TrustTier.FREE_PRIMARY:
        return ConfidenceHint.HIGH
    if tier == TrustTier.FREE_SECONDARY:
        return ConfidenceHint.MEDIUM
    return ConfidenceHint.LOW


def confidence_score(confidence_hint: ConfidenceHint) -> float:
    mapping = {
        ConfidenceHint.LOW: 0.30,
        ConfidenceHint.MEDIUM: 0.55,
        ConfidenceHint.HIGH: 0.78,
        ConfidenceHint.VERY_HIGH: 0.92,
        ConfidenceHint.UNKNOWN: 0.40,
    }
    return mapping[confidence_hint]


def trust_score_for_source(source_family: SourceFamily) -> float:
    return confidence_score(default_confidence_for_source(source_family))
