"""
Replay Module for Sovereign Trading System

This package provides deterministic replay capabilities for Stage 0:
- Source reading from JSONL files
- Event normalization and validation
- Cursor management for position tracking
- Session orchestration for replay and verification

Usage:
    from app.replay import (
        ReplaySource, ReplaySession, ReplayCursor,
        EventNormalizer, create_market_data_normalizer,
        replay_session, verify_replay_session
    )
"""

# ============================================
# Source Module
# ============================================

from app.replay.source import (
    ReplaySource,
    ReplaySourceError,
    ReplaySourceFormatError,
    ReplaySourceConsistencyError,
    open_replay_source,
)


# ============================================
# Normalizer Module
# ============================================

from app.replay.normalizer import (
    EventNormalizer,
    EventNormalizerError,
    EventNormalizerValidationError,
    NormalizerStats,
    normalize_event,
    normalize_events,
    create_market_data_normalizer,
    create_system_event_normalizer,
)


# ============================================
# Cursor Module
# ============================================

from app.replay.replay_cursor import (
    ReplayCursor,
    ReplayCursorError,
    ReplayCursorSeekError,
    ReplayCursorStateError,
    CursorState,
    create_replay_cursor,
)


# ============================================
# Session Module
# ============================================

from app.replay.replay_session import (
    ReplaySession,
    ReplaySessionError,
    ReplaySessionLoadError,
    ReplaySessionVerificationError,
    replay_session,
    verify_replay_session,
)


# ============================================
# Exports
# ============================================

__all__ = [
    # Source
    'ReplaySource',
    'ReplaySourceError',
    'ReplaySourceFormatError',
    'ReplaySourceConsistencyError',
    'open_replay_source',
    # Normalizer
    'EventNormalizer',
    'EventNormalizerError',
    'EventNormalizerValidationError',
    'NormalizerStats',
    'normalize_event',
    'normalize_events',
    'create_market_data_normalizer',
    'create_system_event_normalizer',
    # Cursor
    'ReplayCursor',
    'ReplayCursorError',
    'ReplayCursorSeekError',
    'ReplayCursorStateError',
    'CursorState',
    'create_replay_cursor',
    # Session
    'ReplaySession',
    'ReplaySessionError',
    'ReplaySessionLoadError',
    'ReplaySessionVerificationError',
    'replay_session',
    'verify_replay_session',
]