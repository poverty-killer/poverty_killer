from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from ..config import ExternalFeedProviderConfig, WorldAwarenessConfig
from ..enums import ExternalFeedType
from ..feed_spine import ProviderRegistryEntry, normalize_external_event, provider_entry
from ..models import ExternalIntelligenceEvent


@dataclass
class SecInsiderFilingsAdapter:
    """Disabled-by-default SEC/Form 3/4/5-style advisory lane."""

    config: ExternalFeedProviderConfig = field(default_factory=lambda: WorldAwarenessConfig().sec_insider_filings)

    def status(self, *, env: Mapping[str, str] | None = None) -> ProviderRegistryEntry:
        return provider_entry(self.config, feed_type=ExternalFeedType.SEC_FILING, env=env)

    def fetch(self) -> list[dict[str, Any]]:
        return []

    def normalize_payload(self, payload: Mapping[str, Any], *, received_time=None) -> ExternalIntelligenceEvent:
        normalized = dict(payload)
        normalized.setdefault("asset_class", "equity")
        return normalize_external_event(
            provider=self.config.provider_name,
            feed_type=ExternalFeedType.SEC_FILING,
            payload=normalized,
            received_time=received_time,
            stale_after_seconds=self.config.stale_after_seconds,
            default_asset_class="equity",
        )

    def fetch_and_normalize(self) -> list[ExternalIntelligenceEvent]:
        return [self.normalize_payload(payload) for payload in self.fetch()]


@dataclass
class FinnhubInsiderAdapter:
    """Disabled-by-default Finnhub-style insider transaction advisory lane."""

    config: ExternalFeedProviderConfig = field(default_factory=lambda: WorldAwarenessConfig().finnhub_insider)

    def status(self, *, env: Mapping[str, str] | None = None) -> ProviderRegistryEntry:
        return provider_entry(self.config, feed_type=ExternalFeedType.INSIDER_TRANSACTION, env=env)

    def fetch(self) -> list[dict[str, Any]]:
        return []

    def normalize_payload(self, payload: Mapping[str, Any], *, received_time=None) -> ExternalIntelligenceEvent:
        normalized = dict(payload)
        normalized.setdefault("asset_class", "equity")
        return normalize_external_event(
            provider=self.config.provider_name,
            feed_type=ExternalFeedType.INSIDER_TRANSACTION,
            payload=normalized,
            received_time=received_time,
            stale_after_seconds=self.config.stale_after_seconds,
            default_asset_class="equity",
        )

    def fetch_and_normalize(self) -> list[ExternalIntelligenceEvent]:
        return [self.normalize_payload(payload) for payload in self.fetch()]
