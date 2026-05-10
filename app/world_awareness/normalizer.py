from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .decay import compute_fresh_until
from .enums import (
    ConfidenceHint,
    DecayProfileName,
    DirectionalityHint,
    MagnitudeHint,
    NormalizedEventClass,
    SourceFamily,
)
from .events import create_world_awareness_event
from .models import EventHints, WorldAwarenessEvent
from .source_catalog import get_source_descriptor
from .trust import default_confidence_for_source


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _listify(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value).strip()
    return [text] if text else []


def _normalized_event_class_for_source(source_family: SourceFamily) -> NormalizedEventClass:
    mapping = {
        SourceFamily.SEC_EDGAR: NormalizedEventClass.REGULATORY_FILING,
        SourceFamily.OPENINSIDER: NormalizedEventClass.INSIDER_ACTIVITY,
        SourceFamily.CAPITOL_TRADES: NormalizedEventClass.POLITICAL_DISCLOSURE,
        SourceFamily.QUIVER_FREE: NormalizedEventClass.ALTERNATIVE_SIGNAL,
        SourceFamily.OFFICIAL_ISSUER_RELEASES: NormalizedEventClass.ISSUER_RELEASE,
        SourceFamily.OFFICIAL_CALENDARS: NormalizedEventClass.CALENDAR_EVENT,
        SourceFamily.OFFICIAL_MACRO_RELEASES: NormalizedEventClass.MACRO_RELEASE,
    }
    return mapping.get(source_family, NormalizedEventClass.UNKNOWN)


def _decay_profile_for_source(source_family: SourceFamily) -> DecayProfileName:
    mapping = {
        SourceFamily.SEC_EDGAR: DecayProfileName.REGULATORY_FILING_FRESH,
        SourceFamily.OPENINSIDER: DecayProfileName.INSIDER_DISCLOSURE_DELAYED,
        SourceFamily.CAPITOL_TRADES: DecayProfileName.POLITICAL_DISCLOSURE_DELAYED,
        SourceFamily.QUIVER_FREE: DecayProfileName.GENERIC_CONTEXT,
        SourceFamily.OFFICIAL_ISSUER_RELEASES: DecayProfileName.ISSUER_RELEASE_WINDOWED,
        SourceFamily.OFFICIAL_CALENDARS: DecayProfileName.CALENDAR_EVENT_WINDOWED,
        SourceFamily.OFFICIAL_MACRO_RELEASES: DecayProfileName.MACRO_RELEASE_WINDOWED,
    }
    return mapping.get(source_family, DecayProfileName.GENERIC_CONTEXT)


def normalize_source_payload(
    *,
    source_family: SourceFamily,
    source_event_type: str,
    raw_payload: dict[str, Any],
    source_url: str | None = None,
    event_timestamp_utc: datetime | None = None,
) -> WorldAwarenessEvent:
    """
    Converts a raw source payload into a subordinate normalized event object.
    """
    source = get_source_descriptor(source_family)
    normalized_class = _normalized_event_class_for_source(source_family)
    decay_profile = _decay_profile_for_source(source_family)

    discovered = _utc_now()
    fresh_until = compute_fresh_until(discovered, decay_profile)

    confidence = default_confidence_for_source(source_family)

    symbol_candidates = _listify(
        raw_payload.get("symbol_candidates")
        or raw_payload.get("symbols")
        or raw_payload.get("symbol")
        or raw_payload.get("ticker")
    )
    issuer_candidates = _listify(
        raw_payload.get("issuer_candidates")
        or raw_payload.get("issuer")
        or raw_payload.get("company")
        or raw_payload.get("issuer_name")
    )
    entity_candidates = _listify(
        raw_payload.get("entity_candidates")
        or raw_payload.get("entity")
        or raw_payload.get("entities")
    )
    actor_candidates = _listify(
        raw_payload.get("actor_candidates")
        or raw_payload.get("actor")
        or raw_payload.get("insider")
        or raw_payload.get("politician")
    )

    return create_world_awareness_event(
        source=source.model_copy(update={"source_url": source_url or source.source_url}),
        source_event_type=source_event_type,
        normalized_event_class=normalized_class,
        decay_profile=decay_profile,
        discovery_timestamp_utc=discovered,
        event_timestamp_utc=event_timestamp_utc,
        fresh_until_utc=fresh_until,
        symbol_candidates=symbol_candidates,
        issuer_candidates=issuer_candidates,
        entity_candidates=entity_candidates,
        actor_candidates=actor_candidates,
        hints=EventHints(
            directionality_hint=DirectionalityHint.UNKNOWN,
            magnitude_hint=MagnitudeHint.UNKNOWN,
            confidence_hint=confidence,
        ),
        raw_payload=raw_payload,
    )
