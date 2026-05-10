from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import hashlib

from .enums import (
    DecayProfileName,
    NormalizedEventClass,
)
from .models import (
    EventAttribution,
    EventHints,
    EventIdentity,
    EventTiming,
    ReplayMetadata,
    SourceDescriptor,
    WorldAwarenessEvent,
)


def stable_event_hash(payload: dict[str, Any]) -> str:
    """
    Generates a deterministic hash for replay/audit purposes.
    """
    material = repr(sorted(payload.items())).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def build_dedupe_key(
    source_name: str,
    normalized_event_class: NormalizedEventClass,
    primary_symbol: str | None,
    event_timestamp_utc: datetime | None,
) -> str:
    ts = event_timestamp_utc.isoformat() if event_timestamp_utc else "no_event_ts"
    sym = primary_symbol or "no_symbol"
    return f"{source_name}|{normalized_event_class.value}|{sym}|{ts}"


def derive_event_id(dedupe_key: str) -> str:
    return hashlib.sha256(dedupe_key.encode("utf-8")).hexdigest()[:24]


def create_world_awareness_event(
    *,
    source: SourceDescriptor,
    source_event_type: str,
    normalized_event_class: NormalizedEventClass,
    decay_profile: DecayProfileName,
    discovery_timestamp_utc: datetime | None = None,
    event_timestamp_utc: datetime | None = None,
    effective_timestamp_utc: datetime | None = None,
    fresh_until_utc: datetime | None = None,
    symbol_candidates: list[str] | None = None,
    issuer_candidates: list[str] | None = None,
    entity_candidates: list[str] | None = None,
    actor_candidates: list[str] | None = None,
    hints: EventHints | None = None,
    raw_payload: dict[str, Any] | None = None,
    raw_payload_ref: str | None = None,
    notes: list[str] | None = None,
) -> WorldAwarenessEvent:
    """
    Constructs a subordinate event object with deterministic replay identity.
    """
    discovered = discovery_timestamp_utc or datetime.now(timezone.utc)
    symbols = symbol_candidates or []
    dedupe_key = build_dedupe_key(
        source_name=source.source_name,
        normalized_event_class=normalized_event_class,
        primary_symbol=symbols[0] if symbols else None,
        event_timestamp_utc=event_timestamp_utc,
    )
    event_id = derive_event_id(dedupe_key)

    payload_hash = stable_event_hash(raw_payload) if raw_payload else None

    return WorldAwarenessEvent(
        source=source,
        identity=EventIdentity(
            event_id=event_id,
            dedupe_key=dedupe_key,
            source_event_type=source_event_type,
            normalized_event_class=normalized_event_class,
        ),
        timing=EventTiming(
            event_timestamp_utc=event_timestamp_utc,
            discovery_timestamp_utc=discovered,
            effective_timestamp_utc=effective_timestamp_utc,
            fresh_until_utc=fresh_until_utc,
            decay_profile=decay_profile,
        ),
        attribution=EventAttribution(
            symbol_candidates=symbols,
            issuer_candidates=issuer_candidates or [],
            entity_candidates=entity_candidates or [],
            actor_candidates=actor_candidates or [],
        ),
        hints=hints or EventHints(),
        replay=ReplayMetadata(
            raw_payload_ref=raw_payload_ref,
            payload_hash=payload_hash,
            notes=notes or [],
        ),
        raw_payload=raw_payload,
        canonical_truth_claimed=False,
        live_attached=False,
    )
