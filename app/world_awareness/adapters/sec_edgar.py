from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..enums import SourceFamily
from ..models import WorldAwarenessEvent
from ..normalizer import normalize_source_payload


@dataclass
class SecEdgarAdapter:
    """
    Starter SEC EDGAR adapter scaffold.

    This adapter is intentionally non-live-attached and suitable for later
    fetch-layer integration once a lawful Tier 1/approved integration step exists.
    """

    source_family: SourceFamily = SourceFamily.SEC_EDGAR

    def fetch(self) -> list[dict[str, Any]]:
        """
        Placeholder subordinate fetch surface.

        Pre-integration default returns no live data.
        """
        return []

    def normalize_payload(self, payload: dict[str, Any]) -> WorldAwarenessEvent:
        return normalize_source_payload(
            source_family=self.source_family,
            source_event_type=str(payload.get("source_event_type", "sec_filing")),
            raw_payload=payload,
            source_url=payload.get("source_url"),
        )

    def fetch_and_normalize(self) -> list[WorldAwarenessEvent]:
        return [self.normalize_payload(payload) for payload in self.fetch()]
