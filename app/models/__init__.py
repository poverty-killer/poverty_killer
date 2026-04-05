"""
Canonical Models for Sovereign Trading System

This package provides all canonical contracts, events, invariants, and enums
required by the system. Import from this module for all model needs.

Usage:
    from app.models import (
        EventEnvelope, TruthFrame, OrderIntent, FillEvent,
        EventType, OrderSide, RegimeType, NormalInvariant,
        FusionDecision, DarkPoolPrint, OptionsFlow, StrategySignal,
    )
"""

# ============================================
# Enums
# ============================================

from app.models.enums import (
    # Core enums
    RegimeType,
    TruthStatus,
    RiskMode,
    OrderSide,
    OrderType,
    InternalOrderStatus,
    FillStatus,
    CancelStatus,
    EventType,
    DivergenceType,
    ShadowFrontState,
    LiquidityVoidState,
    AlertSeverity,
    InvariantViolationSeverity,
    ReplayMode,
    SourceType,
    # Contract enums
    DecisionType,
    ExecutionEventType,
    SignalType,
    CheckpointType,
    ResolutionType,
)


# ============================================
# Contracts
# ============================================

from app.models.contracts import (
    # Typed submodels
    ExchangePosition,
    ExchangeOpenOrder,
    ExchangeFill,
    SubmittedOrder,
    PendingCancel,
    Acknowledgement,
    Rejection,
    PortfolioPosition,
    KillSwitchRecord,
    DivergenceBlock,
    StaleDataBlock,
    ReplayPosition,
    FeaturePayload,
    # Core contracts
    EventEnvelope,
    DecisionRecord,
    ExchangeTruth,
    ExecutionTruth,
    PortfolioTruth,
    StrategyTruthEntry,
    StrategyTruth,
    RiskTruth,
    TruthFrame,
    OrderIntent,
    ExecutionEvent,
    FillEvent,
    CancelEvent,
    PortfolioSnapshot,
    RiskDecision,
    StrategyVote,
    FeatureVector,
    RecoveryCheckpoint,
    DivergenceEvent,
)


# ============================================
# Fusion Decision
# ============================================

from app.models.fusion import FusionDecision


# ============================================
# Signals
# ============================================

from app.models.signals import DarkPoolPrint, OptionsFlow, StrategySignal


# ============================================
# Market Data
# ============================================

from app.models.market_data import (
    Candle,
    OrderBookSnapshot,
    LiquidityMetrics,
    PhysicalVerification,
    WhaleFlowScore,
    EntropyScore,
)


# ============================================
# Events
# ============================================

from app.models.events import (
    BaseEvent,
    TradeEvent,
    QuoteEvent,
    OrderBookLevel,
    OrderBookSnapshotEvent,
    OrderBookDeltaEvent,
    ClockTickEvent,
    AuditEvent,
    HeartbeatEvent,
    ReplayStartEvent,
    ReplayEndEvent,
)


# ============================================
# Invariants
# ============================================

from app.models.invariants import (
    NormalInvariant,
    NORMAL_INVARIANTS,
    KillSwitchInvariant,
    KILL_SWITCH_INVARIANTS,
    RecoveryInvariant,
    RECOVERY_INVARIANTS,
    ReplayPurityInvariant,
    REPLAY_PURITY_INVARIANTS,
    InvariantViolationEvent,
    InvariantCheckResult,
    InvariantBatchCheckResult,
)


# ============================================
# Exports
# ============================================

__all__ = [
    # Enums
    'RegimeType',
    'TruthStatus',
    'RiskMode',
    'OrderSide',
    'OrderType',
    'InternalOrderStatus',
    'FillStatus',
    'CancelStatus',
    'EventType',
    'DivergenceType',
    'ShadowFrontState',
    'LiquidityVoidState',
    'AlertSeverity',
    'InvariantViolationSeverity',
    'ReplayMode',
    'SourceType',
    'DecisionType',
    'ExecutionEventType',
    'SignalType',
    'CheckpointType',
    'ResolutionType',
    # Contract submodels
    'ExchangePosition',
    'ExchangeOpenOrder',
    'ExchangeFill',
    'SubmittedOrder',
    'PendingCancel',
    'Acknowledgement',
    'Rejection',
    'PortfolioPosition',
    'KillSwitchRecord',
    'DivergenceBlock',
    'StaleDataBlock',
    'ReplayPosition',
    'FeaturePayload',
    # Core contracts
    'EventEnvelope',
    'DecisionRecord',
    'ExchangeTruth',
    'ExecutionTruth',
    'PortfolioTruth',
    'StrategyTruthEntry',
    'StrategyTruth',
    'RiskTruth',
    'TruthFrame',
    'OrderIntent',
    'ExecutionEvent',
    'FillEvent',
    'CancelEvent',
    'PortfolioSnapshot',
    'RiskDecision',
    'StrategyVote',
    'FeatureVector',
    'RecoveryCheckpoint',
    'DivergenceEvent',
    # Fusion decision
    'FusionDecision',
    # Signals
    'DarkPoolPrint',
    'OptionsFlow',
    'StrategySignal',
    # Market Data
    'Candle',
    'OrderBookSnapshot',
    'LiquidityMetrics',
    'PhysicalVerification',
    'WhaleFlowScore',
    'EntropyScore',
    # Events
    'BaseEvent',
    'TradeEvent',
    'QuoteEvent',
    'OrderBookLevel',
    'OrderBookSnapshotEvent',
    'OrderBookDeltaEvent',
    'ClockTickEvent',
    'AuditEvent',
    'HeartbeatEvent',
    'ReplayStartEvent',
    'ReplayEndEvent',
    # Invariants
    'NormalInvariant',
    'NORMAL_INVARIANTS',
    'KillSwitchInvariant',
    'KILL_SWITCH_INVARIANTS',
    'RecoveryInvariant',
    'RECOVERY_INVARIANTS',
    'ReplayPurityInvariant',
    'REPLAY_PURITY_INVARIANTS',
    'InvariantViolationEvent',
    'InvariantCheckResult',
    'InvariantBatchCheckResult',
]
