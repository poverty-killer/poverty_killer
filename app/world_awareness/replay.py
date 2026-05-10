from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .models import WorldAwarenessEvent


@dataclass(frozen=True)
class ReplayCheckpoint:
    ingestion_batch_id: str | None
    payload_hash: str | None
    event_id: str
    dedupe_key: str


def build_replay_checkpoint(event: WorldAwarenessEvent) -> ReplayCheckpoint:
    return ReplayCheckpoint(
        ingestion_batch_id=event.replay.ingestion_batch_id,
        payload_hash=event.replay.payload_hash,
        event_id=event.identity.event_id,
        dedupe_key=event.identity.dedupe_key,
    )


def replay_identity_set(events: Iterable[WorldAwarenessEvent]) -> set[str]:
    return {event.identity.event_id for event in events}


def dedupe_key_set(events: Iterable[WorldAwarenessEvent]) -> set[str]:
    return {event.identity.dedupe_key for event in events}


def is_replay_duplicate(event: WorldAwarenessEvent, prior_events: Iterable[WorldAwarenessEvent]) -> bool:
    event_identities = replay_identity_set(prior_events)
    dedupe_identities = dedupe_key_set(prior_events)
    return (
        event.identity.event_id in event_identities
        or event.identity.dedupe_key in dedupe_identities
    )
