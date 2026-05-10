"""
POVERTY_KILLER world-awareness subsystem.

This package contains a subordinate, pre-integration, non-canonical
external-context subsystem intended for later lawful wiring into the bot.

Authority boundaries:
- no TruthFrame ownership
- no active strategy authority
- no risk/execution authority
- no live consumer attachment by default
"""

from .config import WorldAwarenessConfig
from .enums import (
    SourceFamily,
    TrustTier,
    NormalizedEventClass,
    SourceLatencyClass,
    DirectionalityHint,
    MagnitudeHint,
    ConfidenceHint,
    DecayProfileName,
)
from .models import (
    SourceDescriptor,
    EventIdentity,
    EventTiming,
    EventAttribution,
    EventHints,
    ReplayMetadata,
    WorldAwarenessEvent,
)

__all__ = [
    "WorldAwarenessConfig",
    "SourceFamily",
    "TrustTier",
    "NormalizedEventClass",
    "SourceLatencyClass",
    "DirectionalityHint",
    "MagnitudeHint",
    "ConfidenceHint",
    "DecayProfileName",
    "SourceDescriptor",
    "EventIdentity",
    "EventTiming",
    "EventAttribution",
    "EventHints",
    "ReplayMetadata",
    "WorldAwarenessEvent",
]
