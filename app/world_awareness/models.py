from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .enums import (
    ConfidenceHint,
    DecayProfileName,
    DirectionalityHint,
    MagnitudeHint,
    NormalizedEventClass,
    SourceFamily,
    SourceLatencyClass,
    TrustTier,
)


class SourceDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_family: SourceFamily
    source_name: str = Field(min_length=1)
    trust_tier: TrustTier
    source_latency_class: SourceLatencyClass
    source_url: str | None = None
    integration_status: str = Field(default="not_live_attached")
    notes: list[str] = Field(default_factory=list)


class EventIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(min_length=1)
    dedupe_key: str = Field(min_length=1)
    source_event_type: str = Field(min_length=1)
    normalized_event_class: NormalizedEventClass


class EventTiming(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_timestamp_utc: datetime | None = None
    discovery_timestamp_utc: datetime
    effective_timestamp_utc: datetime | None = None
    fresh_until_utc: datetime | None = None
    decay_profile: DecayProfileName


class EventAttribution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol_candidates: list[str] = Field(default_factory=list)
    issuer_candidates: list[str] = Field(default_factory=list)
    entity_candidates: list[str] = Field(default_factory=list)
    actor_candidates: list[str] = Field(default_factory=list)


class EventHints(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    directionality_hint: DirectionalityHint = DirectionalityHint.UNKNOWN
    magnitude_hint: MagnitudeHint = MagnitudeHint.UNKNOWN
    confidence_hint: ConfidenceHint = ConfidenceHint.UNKNOWN


class ReplayMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ingestion_batch_id: str | None = None
    raw_payload_ref: str | None = None
    payload_hash: str | None = None
    revision_count: int = Field(default=0, ge=0)
    replayable: bool = True
    notes: list[str] = Field(default_factory=list)


class WorldAwarenessEvent(BaseModel):
    """
    Subordinate external-context event object.

    This object is intentionally non-canonical and non-authoritative by default.
    It exists to preserve normalized external context for later lawful consumers.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    source: SourceDescriptor
    identity: EventIdentity
    timing: EventTiming
    attribution: EventAttribution = Field(default_factory=EventAttribution)
    hints: EventHints = Field(default_factory=EventHints)
    replay: ReplayMetadata = Field(default_factory=ReplayMetadata)

    raw_payload: dict[str, Any] | None = None
    canonical_truth_claimed: bool = False
    live_attached: bool = False

    def is_authoritative(self) -> bool:
        return False

    def requires_future_integration_decision(self) -> bool:
        return True
