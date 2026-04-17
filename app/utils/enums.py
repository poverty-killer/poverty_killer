"""
app/utils/enums.py
POVERTY_KILLER — TAXONOMIC SHIM + POLICY LAYER

All enum class definitions have been harvested into app.models.enums (ONE AUTHORITY).
This module re-exports all enum classes from models.enums for backward compatibility,
and retains the policy tables (frozensets, lifecycle transition map, helper functions)
that depend on those enums.

DO NOT define new enum classes here.
To add enum classes: edit app/models/enums.py directly.
"""

from __future__ import annotations

from typing import Final, FrozenSet

# ============================================================================
# ALL ENUM CLASS RE-EXPORTS (authority: app.models.enums)
# ============================================================================

from app.models.enums import (  # noqa: F401
    CRISIS_REGIMES,
    is_crisis_regime,

    RegimeType,
    LiquidityRegime,
    ToxicityLevel,
    BookIntegrity,
    Marketability,
    SlippageClass,
    SignalDirection,
    TradeIntent,
    PositionSide,
    ExposureState,
    OrderSide,
    OrderType,
    TimeInForce,
    ExecutionConstraint,
    SelfTradePreventionMode,
    VenueCapability,
    OrderStatus,
    InternalOrderStatus,
    ExecutionReportType,
    FillLiquidity,
    FillStatus,
    CancelStatus,
    RecoveryState,
    PersistenceState,
    RiskLevel,
    RiskAction,
    InvariantViolationSeverity,
    HazardVelocity,
    RiskVetoReason,
    RejectReason,
    CancelReason,
    InfraFaultType,
    SleeveType,
    ExecutionMode,
    LatencyTier,
    DegradationMode,
    AuthorityTier,
    ControlMode,
    RiskProfile,
    AssetClass,
    MarketSession,
    ExchangeType,
    PositionStatus,
    EventType,
    EventSource,
    PriorityClass,
    ReplayMode,
    TruthStatus,
    RiskMode,
    AlertSeverity,
    DivergenceType,
    ShadowFrontState,
    LiquidityVoidState,
    LiquidityVoidStatus,
    SourceType,
    CheckpointType,
    DecisionType,
    ExecutionEventType,
    SignalType,
    StrategyID,
    ResolutionType,
    CollapseQuality,
)

# ============================================================================
# TAXONOMY VERSION
# ============================================================================

TAXONOMY_VERSION: Final[str] = "2.0.0"


# ============================================================================
# CANONICAL CLASSIFICATION SETS (policy tables — depend on models.enums classes)
# ============================================================================

TERMINAL_ORDER_STATUSES: Final[FrozenSet[OrderStatus]] = frozenset({
    OrderStatus.VALIDATION_REJECTED,
    OrderStatus.FULLY_FILLED,
    OrderStatus.CANCELLED,
    OrderStatus.REJECTED,
    OrderStatus.EXPIRED,
    OrderStatus.DONE_FOR_DAY,
    OrderStatus.ORPHANED,
})

ACTIVE_ORDER_STATUSES: Final[FrozenSet[OrderStatus]] = frozenset({
    OrderStatus.CREATED,
    OrderStatus.VALIDATED,
    OrderStatus.ROUTING,
    OrderStatus.ROUTED,
    OrderStatus.PENDING_NEW,
    OrderStatus.SENT,
    OrderStatus.PENDING_ACK,
    OrderStatus.ACKNOWLEDGED,
    OrderStatus.PARTIAL_FILL,
    OrderStatus.PENDING_CANCEL,
    OrderStatus.REPLACE_PENDING,
    OrderStatus.RECONCILING,
    OrderStatus.RECOVERED,
})

FILL_ELIGIBLE_ORDER_STATUSES: Final[FrozenSet[OrderStatus]] = frozenset({
    OrderStatus.ROUTED,
    OrderStatus.PENDING_NEW,
    OrderStatus.SENT,
    OrderStatus.PENDING_ACK,
    OrderStatus.ACKNOWLEDGED,
    OrderStatus.PARTIAL_FILL,
    OrderStatus.PENDING_CANCEL,
    OrderStatus.REPLACE_PENDING,
    OrderStatus.RECOVERED,
})

CANCELABLE_ORDER_STATUSES: Final[FrozenSet[OrderStatus]] = frozenset({
    OrderStatus.ROUTED,
    OrderStatus.PENDING_NEW,
    OrderStatus.SENT,
    OrderStatus.PENDING_ACK,
    OrderStatus.ACKNOWLEDGED,
    OrderStatus.PARTIAL_FILL,
    OrderStatus.REPLACE_PENDING,
    OrderStatus.RECOVERED,
})

REPLACEABLE_ORDER_STATUSES: Final[FrozenSet[OrderStatus]] = frozenset({
    OrderStatus.ACKNOWLEDGED,
    OrderStatus.PARTIAL_FILL,
    OrderStatus.RECOVERED,
})

HIGH_RISK_LEVELS: Final[FrozenSet[RiskLevel]] = frozenset({
    RiskLevel.HIGH,
    RiskLevel.CRITICAL,
    RiskLevel.VETO,
    RiskLevel.PANIC,
})

BLOCKING_RISK_ACTIONS: Final[FrozenSet[RiskAction]] = frozenset({
    RiskAction.BLOCK_NEW_LONG,
    RiskAction.BLOCK_NEW_SHORT,
    RiskAction.BLOCK_ALL_NEW,
    RiskAction.FORCE_DELEVER,
    RiskAction.FORCE_FLAT,
    RiskAction.SAFE_MODE,
    RiskAction.KILL_SWITCH,
})


# ============================================================================
# ORDER LIFECYCLE TRANSITION CONTRACT
# ============================================================================

ALLOWED_ORDER_STATUS_TRANSITIONS: Final[dict[OrderStatus, FrozenSet[OrderStatus]]] = {
    OrderStatus.UNKNOWN: frozenset({
        OrderStatus.CREATED, OrderStatus.RECOVERED,
        OrderStatus.RECONCILING, OrderStatus.ORPHANED,
    }),
    OrderStatus.CREATED: frozenset({
        OrderStatus.VALIDATED, OrderStatus.VALIDATION_REJECTED,
    }),
    OrderStatus.VALIDATED: frozenset({
        OrderStatus.ROUTING, OrderStatus.REJECTED,
    }),
    OrderStatus.ROUTING: frozenset({
        OrderStatus.ROUTED, OrderStatus.REJECTED, OrderStatus.STALE,
    }),
    OrderStatus.ROUTED: frozenset({
        OrderStatus.PENDING_NEW, OrderStatus.PENDING_ACK, OrderStatus.ACKNOWLEDGED,
        OrderStatus.REJECTED, OrderStatus.EXPIRED, OrderStatus.RECOVERED,
    }),
    OrderStatus.PENDING_NEW: frozenset({
        OrderStatus.SENT, OrderStatus.PENDING_ACK, OrderStatus.ACKNOWLEDGED,
        OrderStatus.REJECTED, OrderStatus.EXPIRED, OrderStatus.CANCELLED,
    }),
    OrderStatus.SENT: frozenset({
        OrderStatus.PENDING_ACK, OrderStatus.ACKNOWLEDGED, OrderStatus.REJECTED,
        OrderStatus.EXPIRED, OrderStatus.RECOVERED,
    }),
    OrderStatus.PENDING_ACK: frozenset({
        OrderStatus.ACKNOWLEDGED, OrderStatus.PARTIAL_FILL, OrderStatus.FULLY_FILLED,
        OrderStatus.REJECTED, OrderStatus.EXPIRED, OrderStatus.RECOVERED,
    }),
    OrderStatus.ACKNOWLEDGED: frozenset({
        OrderStatus.PARTIAL_FILL, OrderStatus.FULLY_FILLED, OrderStatus.PENDING_CANCEL,
        OrderStatus.REPLACE_PENDING, OrderStatus.CANCELLED, OrderStatus.EXPIRED,
        OrderStatus.DONE_FOR_DAY, OrderStatus.RECOVERED,
    }),
    OrderStatus.PARTIAL_FILL: frozenset({
        OrderStatus.PARTIAL_FILL, OrderStatus.FULLY_FILLED, OrderStatus.PENDING_CANCEL,
        OrderStatus.REPLACE_PENDING, OrderStatus.CANCELLED, OrderStatus.EXPIRED,
        OrderStatus.DONE_FOR_DAY, OrderStatus.RECOVERED,
    }),
    OrderStatus.PENDING_CANCEL: frozenset({
        OrderStatus.CANCELLED, OrderStatus.CANCEL_REJECTED, OrderStatus.PARTIAL_FILL,
        OrderStatus.FULLY_FILLED, OrderStatus.EXPIRED, OrderStatus.RECOVERED,
    }),
    OrderStatus.CANCEL_REJECTED: frozenset({
        OrderStatus.PENDING_CANCEL, OrderStatus.PARTIAL_FILL, OrderStatus.FULLY_FILLED,
        OrderStatus.REPLACE_PENDING, OrderStatus.CANCELLED, OrderStatus.EXPIRED,
        OrderStatus.RECOVERED,
    }),
    OrderStatus.REPLACE_PENDING: frozenset({
        OrderStatus.REPLACED, OrderStatus.REPLACE_REJECTED, OrderStatus.PARTIAL_FILL,
        OrderStatus.FULLY_FILLED, OrderStatus.CANCELLED, OrderStatus.EXPIRED,
        OrderStatus.RECOVERED,
    }),
    OrderStatus.REPLACED: frozenset({
        OrderStatus.ACKNOWLEDGED, OrderStatus.PARTIAL_FILL, OrderStatus.FULLY_FILLED,
        OrderStatus.PENDING_CANCEL, OrderStatus.REPLACE_PENDING, OrderStatus.CANCELLED,
        OrderStatus.EXPIRED, OrderStatus.RECOVERED,
    }),
    OrderStatus.REPLACE_REJECTED: frozenset({
        OrderStatus.ACKNOWLEDGED, OrderStatus.PARTIAL_FILL, OrderStatus.PENDING_CANCEL,
        OrderStatus.REPLACE_PENDING, OrderStatus.FULLY_FILLED, OrderStatus.CANCELLED,
        OrderStatus.EXPIRED, OrderStatus.RECOVERED,
    }),
    OrderStatus.RECOVERED: frozenset({
        OrderStatus.RECONCILING, OrderStatus.ACKNOWLEDGED, OrderStatus.PARTIAL_FILL,
        OrderStatus.FULLY_FILLED, OrderStatus.PENDING_CANCEL, OrderStatus.CANCELLED,
        OrderStatus.REPLACED, OrderStatus.REJECTED, OrderStatus.EXPIRED, OrderStatus.ORPHANED,
    }),
    OrderStatus.RECONCILING: frozenset({
        OrderStatus.RECOVERED, OrderStatus.ACKNOWLEDGED, OrderStatus.PARTIAL_FILL,
        OrderStatus.FULLY_FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED,
        OrderStatus.EXPIRED, OrderStatus.ORPHANED,
    }),
    OrderStatus.STALE: frozenset({
        OrderStatus.RECOVERED, OrderStatus.RECONCILING,
        OrderStatus.ORPHANED, OrderStatus.REJECTED,
    }),
    OrderStatus.VALIDATION_REJECTED: frozenset(),
    OrderStatus.FULLY_FILLED: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
    OrderStatus.REJECTED: frozenset(),
    OrderStatus.EXPIRED: frozenset(),
    OrderStatus.DONE_FOR_DAY: frozenset(),
    OrderStatus.ORPHANED: frozenset(),
}


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def is_terminal_order_status(status: OrderStatus) -> bool:
    return status in TERMINAL_ORDER_STATUSES


def is_active_order_status(status: OrderStatus) -> bool:
    return status in ACTIVE_ORDER_STATUSES


def is_fill_eligible_order_status(status: OrderStatus) -> bool:
    return status in FILL_ELIGIBLE_ORDER_STATUSES


def is_cancelable_order_status(status: OrderStatus) -> bool:
    return status in CANCELABLE_ORDER_STATUSES


def is_replaceable_order_status(status: OrderStatus) -> bool:
    return status in REPLACEABLE_ORDER_STATUSES


def is_high_risk_level(level: RiskLevel) -> bool:
    return level in HIGH_RISK_LEVELS


def is_blocking_risk_action(action: RiskAction) -> bool:
    return action in BLOCKING_RISK_ACTIONS


def is_valid_order_status_transition(
    current: OrderStatus,
    new: OrderStatus,
) -> bool:
    """Returns True if the lifecycle transition is allowed under canonical rules."""
    return new in ALLOWED_ORDER_STATUS_TRANSITIONS.get(current, frozenset())


__all__ = [
    "TAXONOMY_VERSION",
    "CRISIS_REGIMES", "is_crisis_regime",
    "RegimeType", "LiquidityRegime", "ToxicityLevel", "BookIntegrity",
    "Marketability", "SlippageClass",
    "SignalDirection", "TradeIntent", "PositionSide", "ExposureState",
    "OrderSide", "OrderType", "TimeInForce", "ExecutionConstraint",
    "SelfTradePreventionMode", "VenueCapability",
    "OrderStatus", "InternalOrderStatus", "ExecutionReportType", "FillLiquidity",
    "FillStatus", "CancelStatus", "RecoveryState", "PersistenceState",
    "RiskLevel", "RiskAction", "InvariantViolationSeverity", "HazardVelocity", "RiskVetoReason",
    "RejectReason", "CancelReason", "InfraFaultType",
    "SleeveType", "ExecutionMode", "LatencyTier", "DegradationMode", "AuthorityTier",
    "ControlMode", "RiskProfile", "AssetClass", "MarketSession", "ExchangeType", "PositionStatus",
    "EventType", "EventSource", "PriorityClass", "ReplayMode",
    "TruthStatus", "RiskMode", "AlertSeverity",
    "DivergenceType", "ShadowFrontState", "LiquidityVoidState", "LiquidityVoidStatus",
    "SourceType", "CheckpointType",
    "DecisionType", "ExecutionEventType", "SignalType", "StrategyID", "ResolutionType",
    "CollapseQuality",
    "TERMINAL_ORDER_STATUSES", "ACTIVE_ORDER_STATUSES", "FILL_ELIGIBLE_ORDER_STATUSES",
    "CANCELABLE_ORDER_STATUSES", "REPLACEABLE_ORDER_STATUSES",
    "HIGH_RISK_LEVELS", "BLOCKING_RISK_ACTIONS", "ALLOWED_ORDER_STATUS_TRANSITIONS",
    "is_terminal_order_status", "is_active_order_status", "is_fill_eligible_order_status",
    "is_cancelable_order_status", "is_replaceable_order_status",
    "is_high_risk_level", "is_blocking_risk_action", "is_valid_order_status_transition",
]
