from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SourcePollingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    min_poll_interval_seconds: int = Field(default=300, ge=1)
    timeout_seconds: int = Field(default=20, ge=1)
    max_items_per_fetch: int = Field(default=100, ge=1)
    backoff_seconds: int = Field(default=60, ge=1)


class ExternalFeedProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    provider_name: str
    credential_env_keys: list[str] = Field(default_factory=list)
    min_poll_interval_seconds: int = Field(default=300, ge=1)
    timeout_seconds: int = Field(default=20, ge=1)
    max_items_per_fetch: int = Field(default=100, ge=1)
    backoff_seconds: int = Field(default=300, ge=1)
    stale_after_seconds: int = Field(default=3600, ge=1)
    advisory_only: bool = True


class PersistenceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    storage_root: str = "state/world_awareness"
    raw_event_store_name: str = "raw_source_events.jsonl"
    normalized_event_store_name: str = "normalized_world_events.jsonl"
    revision_store_name: str = "event_revisions.jsonl"
    create_dirs_if_missing: bool = True


class ReplayConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enable_replay_index: bool = True
    enable_payload_hashing: bool = True
    retain_raw_payload_refs: bool = True


class WorldAwarenessConfig(BaseModel):
    """
    Subordinate pre-integration config surface.

    This config does not authorize live consumer attachment.
    """

    model_config = ConfigDict(extra="forbid")

    subsystem_enabled: bool = True
    live_attachment_enabled: bool = False
    canonical_truth_enabled: bool = False

    sec_edgar: SourcePollingConfig = Field(default_factory=SourcePollingConfig)
    openinsider: SourcePollingConfig = Field(default_factory=SourcePollingConfig)
    capitol_trades: SourcePollingConfig = Field(default_factory=SourcePollingConfig)
    quiver_free: SourcePollingConfig = Field(default_factory=SourcePollingConfig)
    official_releases: SourcePollingConfig = Field(default_factory=SourcePollingConfig)
    official_calendars: SourcePollingConfig = Field(default_factory=SourcePollingConfig)

    alpaca_news: ExternalFeedProviderConfig = Field(
        default_factory=lambda: ExternalFeedProviderConfig(
            provider_name="alpaca_news",
            credential_env_keys=["APCA_API_KEY_ID", "APCA_API_SECRET_KEY"],
            stale_after_seconds=3600,
        )
    )
    sec_insider_filings: ExternalFeedProviderConfig = Field(
        default_factory=lambda: ExternalFeedProviderConfig(
            provider_name="sec_insider_filings",
            stale_after_seconds=259200,
        )
    )
    finnhub_insider: ExternalFeedProviderConfig = Field(
        default_factory=lambda: ExternalFeedProviderConfig(
            provider_name="finnhub_insider",
            credential_env_keys=["FINNHUB_API_KEY"],
            stale_after_seconds=259200,
        )
    )
    economic_calendar: ExternalFeedProviderConfig = Field(
        default_factory=lambda: ExternalFeedProviderConfig(
            provider_name="economic_calendar",
            stale_after_seconds=21600,
        )
    )
    crypto_onchain: ExternalFeedProviderConfig = Field(
        default_factory=lambda: ExternalFeedProviderConfig(
            provider_name="crypto_onchain",
            stale_after_seconds=900,
        )
    )
    social_sentiment: ExternalFeedProviderConfig = Field(
        default_factory=lambda: ExternalFeedProviderConfig(
            provider_name="social_sentiment",
            stale_after_seconds=900,
        )
    )

    persistence: PersistenceConfig = Field(default_factory=PersistenceConfig)
    replay: ReplayConfig = Field(default_factory=ReplayConfig)
