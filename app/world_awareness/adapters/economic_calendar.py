from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from ..config import ExternalFeedProviderConfig, WorldAwarenessConfig
from ..enums import ExternalFeedType
from ..feed_spine import ProviderRegistryEntry, normalize_external_event, provider_entry
from ..models import ExternalIntelligenceEvent


@dataclass
class EconomicCalendarAdapter:
    """Provider-TBD economic/calendar advisory lane.

    It is represented now so UI/contracts do not need a rebuild later, but it
    performs no network calls and has no trading authority.
    """

    config: ExternalFeedProviderConfig = field(default_factory=lambda: WorldAwarenessConfig().economic_calendar)

    def status(self, *, env: Mapping[str, str] | None = None) -> ProviderRegistryEntry:
        return provider_entry(self.config, feed_type=ExternalFeedType.ECONOMIC_CALENDAR, env=env)

    def fetch(self) -> list[dict[str, Any]]:
        return []

    def normalize_payload(self, payload: Mapping[str, Any], *, received_time=None) -> ExternalIntelligenceEvent:
        return normalize_external_event(
            provider=self.config.provider_name,
            feed_type=ExternalFeedType.ECONOMIC_CALENDAR,
            payload=payload,
            received_time=received_time,
            stale_after_seconds=self.config.stale_after_seconds,
        )

    def fetch_and_normalize(self) -> list[ExternalIntelligenceEvent]:
        return [self.normalize_payload(payload) for payload in self.fetch()]
