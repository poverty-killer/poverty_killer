from __future__ import annotations

from .models import WorldAwarenessEvent


def dedupe_identity(event: WorldAwarenessEvent) -> str:
    return event.identity.dedupe_key


def is_duplicate(candidate: WorldAwarenessEvent, existing_events: list[WorldAwarenessEvent]) -> bool:
    candidate_key = dedupe_identity(candidate)
    return any(dedupe_identity(event) == candidate_key for event in existing_events)


def dedupe_events(events: list[WorldAwarenessEvent]) -> list[WorldAwarenessEvent]:
    seen: set[str] = set()
    output: list[WorldAwarenessEvent] = []

    for event in events:
        key = dedupe_identity(event)
        if key in seen:
            continue
        seen.add(key)
        output.append(event)

    return output
