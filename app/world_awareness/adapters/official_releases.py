from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..enums import SourceFamily
from ..models import WorldAwarenessEvent
from ..normalizer import normalize_source_payload


@dataclass
class OfficialReleasesAdapter:
    """
    Starter official issuer release family adapter scaffold.

    Intended for later lawful integration with issuer-hosted release surfaces.
    """

    source_family: SourceFamily = SourceFamily.OFFICIAL_ISSUER_RELEASES

    def fetch(self) -> list[dict[str, Any]]:
        """
        Placeholder subordinate fetch surface.

        Pre-integration default returns no live data.
        """
        return []

    def normalize_payload(self, payload: dict[str, Any]) -> WorldAwarenessEvent:
        return normalize_source_payload(
            source_family=self.source_family,
            source_event_type=str(payload.get("source_event_type", "official_issuer_release")),
            raw_payload=payload,
            source_url=payload.get("source_url"),
        )

    def fetch_and_normalize(self) -> list[WorldAwarenessEvent]:
        return [self.normalize_payload(payload) for payload in self.fetch()]
