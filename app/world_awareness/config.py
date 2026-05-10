from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SourcePollingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    min_poll_interval_seconds: int = Field(default=300, ge=1)
    timeout_seconds: int = Field(default=20, ge=1)
    max_items_per_fetch: int = Field(default=100, ge=1)
    backoff_seconds: int = Field(default=60, ge=1)


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

    persistence: PersistenceConfig = Field(default_factory=PersistenceConfig)
    replay: ReplayConfig = Field(default_factory=ReplayConfig)
