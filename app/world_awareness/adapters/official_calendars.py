from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..enums import SourceFamily
from ..models import WorldAwarenessEvent
from ..normalizer import normalize_source_payload


@dataclass
class OfficialCalendarsAdapter:
    """
    Starter official calendar / macro-release adapter scaffold.

    Supports both official calendar families and official macro release families
    in a pre-integration subordinate context lane.
    """

    source_family: SourceFamily = SourceFamily.OFFICIAL_CALENDARS

    def fetch(self) -> list[dict[str, Any]]:
        """
        Placeholder subordinate fetch surface.

        Pre-integration default returns no live data.
        """
        return []

    def normalize_payload(self, payload: dict[str, Any]) -> WorldAwarenessEvent:
        source_family_value = payload.get("source_family")
        source_family = (
            SourceFamily(source_family_value)
            if source_family_value in {member.value for member in SourceFamily}
            else self.source_family
        )

        return normalize_source_payload(
            source_family=source_family,
            source_event_type=str(payload.get("source_event_type", "official_calendar_event")),
            raw_payload=payload,
            source_url=payload.get("source_url"),
        )

    def fetch_and_normalize(self) -> list[WorldAwarenessEvent]:
        return [self.normalize_payload(payload) for payload in self.fetch()]
