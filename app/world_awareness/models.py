from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .enums import (
    ConfidenceHint,
    DecayProfileName,
    DirectionalityHint,
    ExternalFeedType,
    ExternalVerificationStatus,
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


class ExternalIntelligenceEvent(BaseModel):
    """
    UI/DecisionFrame-facing advisory event contract.

    This model is intentionally subordinate. It can preserve external context
    and advisory hints, but it cannot become broker, market-truth, risk, or
    execution authority.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    event_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    feed_type: ExternalFeedType
    source_url: str | None = None
    source_id: str | None = None
    symbols: list[str] = Field(default_factory=list)
    asset_class: str | None = None
    topic: str = "unknown"
    title: str = ""
    summary: str = ""
    event_time: datetime | None = None
    received_time: datetime
    freshness_seconds: int = Field(default=0, ge=0)
    stale: bool = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    relevance: float = Field(default=0.0, ge=0.0, le=1.0)
    sentiment: float | None = Field(default=None, ge=-1.0, le=1.0)
    severity: str = "UNKNOWN"
    direction_hint: DirectionalityHint = DirectionalityHint.UNKNOWN
    verification_status: ExternalVerificationStatus = ExternalVerificationStatus.UNVERIFIED
    advisory_only: bool = True
    decisionframe_eligible: bool = False
    reason_codes: list[str] = Field(default_factory=lambda: ["ADVISORY_ONLY"])
    raw_payload_hash: str | None = None

    def can_trade(self) -> bool:
        return False

    def to_decisionframe_evidence(self) -> dict[str, Any]:
        status = "STALE" if self.stale else "ADVISORY"
        if self.verification_status == ExternalVerificationStatus.UNVERIFIED:
            status = "UNVERIFIED"
        if self.verification_status == ExternalVerificationStatus.CONFLICTING:
            status = "CONFLICTING"
        return {
            "module_name": "WorldAwareness",
            "authority_class": "ADVISORY",
            "status": status,
            "signal": "NONE",
            "confidence": self.confidence,
            "score_delta": 0.0,
            "reason_codes": tuple(dict.fromkeys([*self.reason_codes, "ADVISORY_ONLY_NO_TRADE_AUTHORITY"])),
            "metadata": {
                "event_id": self.event_id,
                "provider": self.provider,
                "feed_type": self.feed_type.value,
                "symbols": tuple(self.symbols),
                "topic": self.topic,
                "stale": self.stale,
                "verification_status": self.verification_status.value,
                "decisionframe_eligible": self.decisionframe_eligible,
            },
        }
