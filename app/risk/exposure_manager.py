"""
app/risk/exposure_manager.py
POVERTY_KILLER — SOVEREIGN EXPOSURE ENGINE (CITADEL-GRADE)

This module is the canonical portfolio inventory, reservation, and effective
exposure authority. It extends filled-position accounting into a hedge-aware,
status-weighted, audit-journaled exposure system suitable for live orchestration,
risk gating, replay, reconciliation, and recovery.

CORE CAPABILITIES
-----------------
- Decimal-safe filled inventory accounting
- Status-weighted pending reservation model
- Direction-aware pre-flight validation
- Hedge-aware raw vs residual exposure accounting
- Reservation certainty weighting
- Reservation dedupe / idempotency controls
- Mutation journal for replay / forensics
- Versioned, quality-annotated snapshots
- Controlled reconciliation path
- Backward-aware compatibility with legacy API surface

ARCHITECTURAL ROLE
------------------
- This module is a sovereign risk-state authority.
- It does NOT directly own execution authority.
- Orchestrator, router, execution engine, and unified risk authority consume
  this module's exposure truth surface.

DESIGN PRINCIPLES
-----------------
1. Effective Exposure, Not Just Positions
   Exposure includes filled state plus unresolved but live pending intent.

2. Hedge Awareness
   Raw and residual exposure are separated so portfolio stabilization is visible.

3. Weighted Truth
   Pending exposure is not binary. Reservation confidence depends on lifecycle.

4. Deterministic Governance
   Validation, updates, and snapshots are structured and versioned.

5. Auditability
   State mutations are journaled in canonical form for replay and forensics.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation, ROUND_DOWN, getcontext
from enum import Enum, unique
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.utils.enums import (
    AuthorityTier,
    EventSource,
    InvariantViolationSeverity,
    OrderSide,
    PositionSide,
    PriorityClass,
    ReplayMode,
    RiskAction,
    RiskLevel,
    RiskVetoReason,
    SleeveType,
    TradeIntent,
)

getcontext().prec = 28
logger = logging.getLogger(__name__)


# P3B/B1 authority seam marker:
# ExposureManager is the canonical portfolio-risk authority for the governed
# PAPER runtime. It does not own execution or broker authority; the live path
# consumes its verdict as risk evidence before broker submission.
EXPOSURE_AUTHORITY_STATUS = "LIVE_RUNTIME"


# ============================================================================
# CONSTANTS / HELPERS
# ============================================================================

ZERO = Decimal("0")
ONE = Decimal("1")


def _d(value: Any, *, field_name: str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"invalid decimal for {field_name}: {value!r}") from exc


def _ensure_non_negative(value: Decimal, field_name: str) -> Decimal:
    if value < ZERO:
        raise ValueError(f"{field_name} must be >= 0, got {value}")
    return value


def _ensure_positive(value: Decimal, field_name: str) -> Decimal:
    if value <= ZERO:
        raise ValueError(f"{field_name} must be > 0, got {value}")
    return value


def _enum_from_ledger(enum_cls: Any, value: Any, *, field_name: str) -> Any:
    if value is None:
        raise ValueError(f"{field_name} is required")
    if isinstance(value, enum_cls):
        return value
    raw = str(value)
    for member in enum_cls:
        if raw == member.value or raw == member.name:
            return member
    raise ValueError(f"unsupported {field_name}: {value!r}")


def _safe_div(n: Decimal, d: Decimal) -> Decimal:
    return ZERO if d == ZERO else (n / d)


def _abs(value: Decimal) -> Decimal:
    return abs(value)


def _quantize_down(value: Decimal, step: Decimal) -> Decimal:
    if step <= ZERO:
        return value
    units = (value / step).to_integral_value(rounding=ROUND_DOWN)
    return units * step


def _now_ns() -> int:
    return time.time_ns()


def _signed_qty_for_side(side: OrderSide, qty: Decimal) -> Decimal:
    if side == OrderSide.BUY:
        return qty
    if side == OrderSide.SELL:
        return -qty
    raise ValueError(f"unsupported side: {side}")


def _position_side_from_qty(qty: Decimal) -> PositionSide:
    if qty > ZERO:
        return PositionSide.LONG
    if qty < ZERO:
        return PositionSide.SHORT
    return PositionSide.FLAT


# ============================================================================
# ENUMS
# ============================================================================

@unique
class ReservationStatus(str, Enum):
    CREATED = "CREATED"
    ROUTING = "ROUTING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    STALE = "STALE"
    CANCELLED = "CANCELLED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


@unique
class ExposureSnapshotQuality(str, Enum):
    LIVE = "LIVE"
    PARTIAL_MARKS = "PARTIAL_MARKS"
    STALE_MARKS = "STALE_MARKS"
    RECOVERING = "RECOVERING"
    RECONCILED_WITH_ATTRIBUTION_LOSS = "RECONCILED_WITH_ATTRIBUTION_LOSS"
    AMBIGUOUS = "AMBIGUOUS"


@unique
class MutationType(str, Enum):
    RESERVATION_CREATED = "RESERVATION_CREATED"
    RESERVATION_UPDATED = "RESERVATION_UPDATED"
    RESERVATION_RELEASED = "RESERVATION_RELEASED"
    FILL_APPLIED = "FILL_APPLIED"
    MTM_UPDATED = "MTM_UPDATED"
    RECONCILED = "RECONCILED"
    EQUITY_UPDATED = "EQUITY_UPDATED"
    AGGREGATES_RECOMPUTED = "AGGREGATES_RECOMPUTED"


# ============================================================================
# MODELS
# ============================================================================

@dataclass(frozen=True, slots=True)
class ExposurePolicyConfig:
    initial_equity: Decimal
    max_utilization: Decimal = Decimal("0.80")
    max_asset_concentration: Decimal = Decimal("0.25")
    max_drawdown_unrealized: Decimal = Decimal("0.05")
    quantity_step: Decimal = Decimal("0.0001")
    min_reservation_qty: Decimal = Decimal("0.0001")
    stale_reservation_ns: int = 5_000_000_000
    mark_stale_ns: int = 10_000_000_000
    journal_capacity: int = 50_000
    sleeve_caps: Optional[Dict[SleeveType, Decimal]] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "initial_equity", _ensure_positive(_d(self.initial_equity, field_name="initial_equity"), "initial_equity"))
        object.__setattr__(self, "max_utilization", _ensure_positive(_d(self.max_utilization, field_name="max_utilization"), "max_utilization"))
        object.__setattr__(self, "max_asset_concentration", _ensure_positive(_d(self.max_asset_concentration, field_name="max_asset_concentration"), "max_asset_concentration"))
        object.__setattr__(self, "max_drawdown_unrealized", _ensure_positive(_d(self.max_drawdown_unrealized, field_name="max_drawdown_unrealized"), "max_drawdown_unrealized"))
        object.__setattr__(self, "quantity_step", _ensure_positive(_d(self.quantity_step, field_name="quantity_step"), "quantity_step"))
        object.__setattr__(self, "min_reservation_qty", _ensure_positive(_d(self.min_reservation_qty, field_name="min_reservation_qty"), "min_reservation_qty"))

        if self.max_utilization > ONE:
            raise ValueError("max_utilization cannot exceed 1")
        if self.max_asset_concentration > ONE:
            raise ValueError("max_asset_concentration cannot exceed 1")
        if self.max_drawdown_unrealized > ONE:
            raise ValueError("max_drawdown_unrealized cannot exceed 1")
        if self.stale_reservation_ns < 0:
            raise ValueError("stale_reservation_ns must be >= 0")
        if self.mark_stale_ns < 0:
            raise ValueError("mark_stale_ns must be >= 0")
        if self.journal_capacity < 100:
            raise ValueError("journal_capacity must be >= 100")

        default_caps = {
            SleeveType.SHADOW_FRONT: Decimal("0.40"),
            SleeveType.GAMMA_FRONT: Decimal("0.30"),
            SleeveType.LIQUIDITY_VOID: Decimal("0.20"),
            SleeveType.SECTOR_ROTATION: Decimal("0.20"),
            SleeveType.ADAPTIVE_DC: Decimal("0.10"),
            SleeveType.HEDGING_FLOW: Decimal("0.50"),
            SleeveType.POVERTY_KILLER_AGGREGATE: Decimal("1.00"),
        }

        if self.sleeve_caps is None:
            object.__setattr__(self, "sleeve_caps", default_caps)
        else:
            normalized: Dict[SleeveType, Decimal] = {}
            for sleeve, cap in self.sleeve_caps.items():
                dec = _ensure_positive(_d(cap, field_name=f"sleeve_caps[{sleeve}]"), f"sleeve_caps[{sleeve}]")
                if dec > ONE:
                    raise ValueError(f"sleeve cap for {sleeve} cannot exceed 1")
                normalized[sleeve] = dec
            object.__setattr__(self, "sleeve_caps", normalized)


@dataclass(frozen=True, slots=True)
class PositionState:
    symbol: str
    sleeve: SleeveType
    qty: Decimal = ZERO
    wap: Decimal = ZERO
    mark_price: Decimal = ZERO
    mark_ts_ns: int = 0
    realized_pnl: Decimal = ZERO
    unrealized_pnl: Decimal = ZERO
    fees_paid: Decimal = ZERO
    last_update_ns: int = 0
    source: EventSource = EventSource.RISK

    @property
    def notional_book(self) -> Decimal:
        return _abs(self.qty * self.wap)

    @property
    def notional_mark(self) -> Decimal:
        px = self.mark_price if self.mark_price > ZERO else self.wap
        return _abs(self.qty * px)

    @property
    def signed_mark_exposure(self) -> Decimal:
        px = self.mark_price if self.mark_price > ZERO else self.wap
        return self.qty * px

    @property
    def position_side(self) -> PositionSide:
        return _position_side_from_qty(self.qty)


@dataclass(frozen=True, slots=True)
class PendingReservation:
    reservation_id: str
    sleeve: SleeveType
    symbol: str
    side: OrderSide
    qty: Decimal
    price: Decimal
    trade_intent: TradeIntent = TradeIntent.UNKNOWN
    reduce_only: bool = False
    is_hedge: bool = False
    status: ReservationStatus = ReservationStatus.CREATED
    confidence_weight: Decimal = Decimal("0.40")
    replay_mode: ReplayMode = ReplayMode.LIVE
    created_at_ns: int = field(default_factory=_now_ns)
    last_update_ns: int = field(default_factory=_now_ns)
    filled_qty: Decimal = ZERO
    cancelled_qty: Decimal = ZERO
    client_order_id: Optional[str] = None
    dedupe_key: Optional[str] = None
    source: EventSource = EventSource.ORCHESTRATOR

    def __post_init__(self) -> None:
        object.__setattr__(self, "qty", _ensure_positive(_d(self.qty, field_name="qty"), "qty"))
        object.__setattr__(self, "price", _ensure_positive(_d(self.price, field_name="price"), "price"))
        object.__setattr__(self, "filled_qty", _ensure_non_negative(_d(self.filled_qty, field_name="filled_qty"), "filled_qty"))
        object.__setattr__(self, "cancelled_qty", _ensure_non_negative(_d(self.cancelled_qty, field_name="cancelled_qty"), "cancelled_qty"))
        object.__setattr__(self, "confidence_weight", _ensure_non_negative(_d(self.confidence_weight, field_name="confidence_weight"), "confidence_weight"))

        if self.confidence_weight > ONE:
            raise ValueError("confidence_weight cannot exceed 1")

    @property
    def open_qty(self) -> Decimal:
        remaining = self.qty - self.filled_qty - self.cancelled_qty
        return remaining if remaining > ZERO else ZERO

    @property
    def signed_open_qty(self) -> Decimal:
        return _signed_qty_for_side(self.side, self.open_qty)

    @property
    def open_notional(self) -> Decimal:
        return self.open_qty * self.price

    @property
    def weighted_open_notional(self) -> Decimal:
        return self.open_notional * self.confidence_weight


@dataclass(frozen=True, slots=True)
class MutationRecord:
    sequence: int
    timestamp_ns: int
    mutation_type: MutationType
    version: int
    symbol: Optional[str]
    sleeve: Optional[str]
    payload: Dict[str, Any]


@dataclass(frozen=True, slots=True)
class ExposureSurface:
    gross_book_notional: Decimal
    gross_mark_notional: Decimal
    gross_long_mark_notional: Decimal
    gross_short_mark_notional: Decimal
    net_mark_exposure: Decimal

    hedge_mark_exposure: Decimal
    raw_net_exposure: Decimal
    residual_net_exposure: Decimal

    reserved_notional_weighted: Decimal
    reserved_hedge_notional_weighted: Decimal
    effective_gross_notional: Decimal

    total_unrealized_pnl: Decimal
    total_realized_pnl: Decimal
    total_fees_paid: Decimal


@dataclass(frozen=True, slots=True)
class ExposureIntentValidation:
    authorized: bool
    reason: str

    risk_level: RiskLevel
    risk_action: RiskAction
    severity: InvariantViolationSeverity
    authority_tier: AuthorityTier
    priority: PriorityClass
    veto_reason: Optional[RiskVetoReason] = None

    projected_order_notional: Decimal = ZERO
    current_global_utilization: Decimal = ZERO
    projected_global_utilization: Decimal = ZERO
    current_sleeve_utilization: Decimal = ZERO
    projected_sleeve_utilization: Decimal = ZERO
    current_asset_concentration: Decimal = ZERO
    projected_asset_concentration: Decimal = ZERO

    current_position_qty: Decimal = ZERO
    projected_position_qty: Decimal = ZERO
    reduces_exposure: bool = False
    increases_exposure: bool = False
    expands_gross: bool = False
    reservation_aware: bool = True
    hedge_aware: bool = True

    rationale: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class FillResult:
    sleeve: SleeveType
    symbol: str
    old_qty: Decimal
    new_qty: Decimal
    old_wap: Decimal
    new_wap: Decimal
    realized_pnl_delta: Decimal
    total_realized_pnl: Decimal
    fee_paid: Decimal
    effective_gross_after: Decimal
    residual_net_exposure_after: Decimal
    sleeve_usage_after: Decimal
    reversed_position: bool
    position_closed: bool


@dataclass(frozen=True, slots=True)
class SleeveExposureSnapshot:
    sleeve: SleeveType
    filled_book_notional: Decimal
    filled_mark_notional: Decimal
    reserved_notional_weighted: Decimal
    reserved_hedge_notional_weighted: Decimal
    effective_notional: Decimal
    raw_net_exposure: Decimal
    residual_net_exposure: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    utilization: Decimal
    symbols: int
    reservations: int


@dataclass(frozen=True, slots=True)
class GlobalExposureSnapshot:
    timestamp_ns: int
    equity: Decimal

    gross_book_notional: Decimal
    gross_mark_notional: Decimal
    gross_long_mark_notional: Decimal
    gross_short_mark_notional: Decimal
    net_mark_exposure: Decimal

    hedge_mark_exposure: Decimal
    raw_net_exposure: Decimal
    residual_net_exposure: Decimal

    reserved_notional_weighted: Decimal
    reserved_hedge_notional_weighted: Decimal
    effective_gross_notional: Decimal

    total_unrealized_pnl: Decimal
    total_realized_pnl: Decimal
    total_fees_paid: Decimal

    utilization_pct: Decimal
    hazard_level: RiskLevel
    hazard_action: RiskAction
    severity: InvariantViolationSeverity


@dataclass(frozen=True, slots=True)
class ExposureRiskSnapshot:
    version: int
    timestamp_ns: int
    global_snapshot: GlobalExposureSnapshot
    sleeves: Dict[str, SleeveExposureSnapshot]
    positions: Dict[str, Dict[str, Dict[str, Any]]]
    reservations: Dict[str, Dict[str, Any]]
    quality: ExposureSnapshotQuality
    reconciliation_attribution_loss: bool


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    symbol: str
    exchange_qty: Decimal
    exchange_price: Decimal
    affected_sleeves: tuple[SleeveType, ...]
    previous_total_qty: Decimal
    new_total_qty: Decimal
    reconciled: bool
    attribution_lost: bool
    rationale: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class ExposureInvariantReport:
    valid: bool
    version: int
    violations: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)


# ============================================================================
# ENGINE
# ============================================================================

class ExposureManager:
    """
    Sovereign exposure authority with:
    - filled inventory accounting
    - status-weighted reservations
    - hedge-aware residual exposure
    - mutation journaling

    P3B/B1 authority posture:
    - This class is the canonical portfolio-risk authority for governed PAPER.
    - It supplies pre-trade risk evidence to MainLoop/DecisionFrame/ExecutionEngine.
    - It does not own broker mutation or execution routing authority.
    """

    def __init__(
        self,
        initial_equity: Decimal,
        max_utilization: Decimal = Decimal("0.80"),
        max_asset_concentration: Decimal = Decimal("0.25"),
        sleeve_limits: Optional[Dict[SleeveType, Decimal]] = None,
    ):
        self.policy = ExposurePolicyConfig(
            initial_equity=_d(initial_equity, field_name="initial_equity"),
            max_utilization=_d(max_utilization, field_name="max_utilization"),
            max_asset_concentration=_d(max_asset_concentration, field_name="max_asset_concentration"),
            sleeve_caps=sleeve_limits,
        )

        self._lock = threading.RLock()
        self._version = 0
        self._mutation_seq = 0
        self._reconciliation_attribution_loss = False

        self._total_equity: Decimal = self.policy.initial_equity

        self._inventory: Dict[SleeveType, Dict[str, PositionState]] = {
            sleeve: {} for sleeve in SleeveType
        }
        self._reservations: Dict[str, PendingReservation] = {}
        self._reservation_dedupe: Dict[str, str] = {}

        self._mutation_journal: List[MutationRecord] = []

        # Aggregate caches
        self._gross_book_notional: Decimal = ZERO
        self._gross_mark_notional: Decimal = ZERO
        self._gross_long_mark_notional: Decimal = ZERO
        self._gross_short_mark_notional: Decimal = ZERO
        self._net_mark_exposure: Decimal = ZERO

        self._hedge_mark_exposure: Decimal = ZERO
        self._raw_net_exposure: Decimal = ZERO
        self._residual_net_exposure: Decimal = ZERO

        self._reserved_notional_weighted: Decimal = ZERO
        self._reserved_hedge_notional_weighted: Decimal = ZERO
        self._effective_gross_notional: Decimal = ZERO

        self._sleeve_usage_book: Dict[SleeveType, Decimal] = {sleeve: ZERO for sleeve in SleeveType}
        self._sleeve_usage_mark: Dict[SleeveType, Decimal] = {sleeve: ZERO for sleeve in SleeveType}
        self._sleeve_reserved_notional: Dict[SleeveType, Decimal] = {sleeve: ZERO for sleeve in SleeveType}
        self._sleeve_reserved_hedge_notional: Dict[SleeveType, Decimal] = {sleeve: ZERO for sleeve in SleeveType}
    # ------------------------------------------------------------------
    # Legacy + canonical validation
    # ------------------------------------------------------------------

    def validate_intent(
        self,
        sleeve: SleeveType,
        symbol: str,
        side: OrderSide,
        qty: Decimal,
        price: Decimal,
    ) -> Tuple[bool, str, RiskLevel]:
        result = self.validate_intent_detailed(
            sleeve=sleeve,
            symbol=symbol,
            side=side,
            qty=qty,
            price=price,
            trade_intent=TradeIntent.UNKNOWN,
            reduce_only=False,
            is_hedge=(sleeve == SleeveType.HEDGING_FLOW),
        )
        return result.authorized, result.reason, result.risk_level

    def validate_intent_detailed(
        self,
        sleeve: SleeveType,
        symbol: str,
        side: OrderSide,
        qty: Decimal,
        price: Decimal,
        *,
        trade_intent: TradeIntent = TradeIntent.UNKNOWN,
        reduce_only: bool = False,
        is_hedge: bool = False,
    ) -> ExposureIntentValidation:
        with self._lock:
            if side not in {OrderSide.BUY, OrderSide.SELL}:
                return self._reject_validation(
                    reason="INVALID_SIDE",
                    risk_level=RiskLevel.HIGH,
                    risk_action=RiskAction.BLOCK_ALL_NEW,
                    severity=InvariantViolationSeverity.WARNING,
                    authority_tier=AuthorityTier.HARD_BLOCK,
                    priority=PriorityClass.URGENT,
                    veto_reason=RiskVetoReason.EXPOSURE_LIMIT,
                    rationale=("invalid_order_side_for_validation",),
                )

            qty = _ensure_positive(_d(qty, field_name="qty"), "qty")
            price = _ensure_positive(_d(price, field_name="price"), "price")

            current_pos = self._inventory[sleeve].get(symbol)
            current_qty = current_pos.qty if current_pos is not None else ZERO

            pending_signed_qty = self._pending_signed_qty_for(sleeve=sleeve, symbol=symbol)
            current_effective_qty = current_qty + pending_signed_qty

            proposed_signed_qty = _signed_qty_for_side(side, qty)
            projected_position_qty = current_effective_qty + proposed_signed_qty
            order_notional = qty * price

            current_global_utilization = self.current_utilization()
            current_sleeve_utilization = self.sleeve_utilization(sleeve)
            current_asset_concentration = self.asset_concentration(symbol)

            reduces_exposure, increases_exposure, expands_gross = self._classify_directional_effect(
                current_effective_qty=current_effective_qty,
                proposed_signed_qty=proposed_signed_qty,
                reduce_only=reduce_only,
                trade_intent=trade_intent,
            )

            weighted_reservation_delta = order_notional * self._default_confidence_weight(ReservationStatus.CREATED)

            # Hedge-aware treatment: hedges still count, but their contribution
            # to effective gross is discounted relative to speculative opens.
            if is_hedge and (increases_exposure or expands_gross):
                weighted_reservation_delta *= Decimal("0.50")

            projected_effective_gross = self._effective_gross_notional + (
                weighted_reservation_delta if (increases_exposure or expands_gross) else ZERO
            )
            projected_global_utilization = _safe_div(projected_effective_gross, self._total_equity)

            if reduce_only and not reduces_exposure:
                return self._reject_validation(
                    reason="REDUCE_ONLY_VIOLATION",
                    risk_level=RiskLevel.HIGH,
                    risk_action=RiskAction.BLOCK_ALL_NEW,
                    severity=InvariantViolationSeverity.WARNING,
                    authority_tier=AuthorityTier.HARD_BLOCK,
                    priority=PriorityClass.URGENT,
                    projected_order_notional=order_notional,
                    current_global_utilization=current_global_utilization,
                    projected_global_utilization=current_global_utilization,
                    current_sleeve_utilization=current_sleeve_utilization,
                    projected_sleeve_utilization=current_sleeve_utilization,
                    current_asset_concentration=current_asset_concentration,
                    projected_asset_concentration=current_asset_concentration,
                    current_position_qty=current_effective_qty,
                    projected_position_qty=projected_position_qty,
                    reduces_exposure=reduces_exposure,
                    increases_exposure=increases_exposure,
                    expands_gross=expands_gross,
                    veto_reason=RiskVetoReason.EXPOSURE_LIMIT,
                    rationale=("reduce_only_trade_would_not_reduce_exposure",),
                )

            if projected_effective_gross > (self._total_equity * self.policy.max_utilization):
                return self._reject_validation(
                    reason="GLOBAL_UTILIZATION_BREACH",
                    risk_level=RiskLevel.HIGH,
                    risk_action=RiskAction.BLOCK_ALL_NEW,
                    severity=InvariantViolationSeverity.WARNING,
                    authority_tier=AuthorityTier.HARD_BLOCK,
                    priority=PriorityClass.URGENT,
                    projected_order_notional=order_notional,
                    current_global_utilization=current_global_utilization,
                    projected_global_utilization=projected_global_utilization,
                    current_sleeve_utilization=current_sleeve_utilization,
                    projected_sleeve_utilization=current_sleeve_utilization,
                    current_asset_concentration=current_asset_concentration,
                    projected_asset_concentration=current_asset_concentration,
                    current_position_qty=current_effective_qty,
                    projected_position_qty=projected_position_qty,
                    reduces_exposure=reduces_exposure,
                    increases_exposure=increases_exposure,
                    expands_gross=expands_gross,
                    veto_reason=RiskVetoReason.EXPOSURE_LIMIT,
                    rationale=("effective_global_utilization_limit_exceeded",),
                )

            sleeve_cap = self._total_equity * self.policy.sleeve_caps.get(sleeve, Decimal("0.10"))
            current_sleeve_effective = self._sleeve_usage_mark[sleeve] + self._sleeve_reserved_notional[sleeve]
            projected_sleeve_effective = current_sleeve_effective + (
                weighted_reservation_delta if (increases_exposure or expands_gross) else ZERO
            )
            projected_sleeve_utilization = _safe_div(projected_sleeve_effective, self._total_equity)

            if projected_sleeve_effective > sleeve_cap:
                return self._reject_validation(
                    reason=f"SLEEVE_CONCENTRATION_BREACH:{sleeve.name}",
                    risk_level=RiskLevel.MEDIUM,
                    risk_action=RiskAction.THROTTLE,
                    severity=InvariantViolationSeverity.WARNING,
                    authority_tier=AuthorityTier.SOFT_BLOCK,
                    priority=PriorityClass.NORMAL,
                    projected_order_notional=order_notional,
                    current_global_utilization=current_global_utilization,
                    projected_global_utilization=projected_global_utilization,
                    current_sleeve_utilization=current_sleeve_utilization,
                    projected_sleeve_utilization=projected_sleeve_utilization,
                    current_asset_concentration=current_asset_concentration,
                    projected_asset_concentration=current_asset_concentration,
                    current_position_qty=current_effective_qty,
                    projected_position_qty=projected_position_qty,
                    reduces_exposure=reduces_exposure,
                    increases_exposure=increases_exposure,
                    expands_gross=expands_gross,
                    veto_reason=RiskVetoReason.CONCENTRATION_LIMIT,
                    rationale=("effective_sleeve_concentration_limit_exceeded",),
                )

            current_asset_effective = self._asset_total_mark_notional(symbol) + self._asset_reserved_notional(symbol)
            projected_asset_effective = current_asset_effective + (
                weighted_reservation_delta if (increases_exposure or expands_gross) else ZERO
            )
            projected_asset_concentration = _safe_div(projected_asset_effective, self._total_equity)

            if projected_asset_concentration > self.policy.max_asset_concentration:
                return self._reject_validation(
                    reason="ASSET_CONCENTRATION_VETO",
                    risk_level=RiskLevel.HIGH,
                    risk_action=RiskAction.BLOCK_ALL_NEW,
                    severity=InvariantViolationSeverity.WARNING,
                    authority_tier=AuthorityTier.HARD_BLOCK,
                    priority=PriorityClass.URGENT,
                    projected_order_notional=order_notional,
                    current_global_utilization=current_global_utilization,
                    projected_global_utilization=projected_global_utilization,
                    current_sleeve_utilization=current_sleeve_utilization,
                    projected_sleeve_utilization=projected_sleeve_utilization,
                    current_asset_concentration=current_asset_concentration,
                    projected_asset_concentration=projected_asset_concentration,
                    current_position_qty=current_effective_qty,
                    projected_position_qty=projected_position_qty,
                    reduces_exposure=reduces_exposure,
                    increases_exposure=increases_exposure,
                    expands_gross=expands_gross,
                    veto_reason=RiskVetoReason.CONCENTRATION_LIMIT,
                    rationale=("effective_asset_concentration_limit_exceeded",),
                )

            return ExposureIntentValidation(
                authorized=True,
                reason="AUTHORIZED",
                risk_level=RiskLevel.NONE,
                risk_action=RiskAction.ALLOW,
                severity=InvariantViolationSeverity.ADVISORY,
                authority_tier=AuthorityTier.ADVISORY,
                priority=PriorityClass.DEFERRED,
                veto_reason=None,
                projected_order_notional=order_notional,
                current_global_utilization=current_global_utilization,
                projected_global_utilization=projected_global_utilization,
                current_sleeve_utilization=current_sleeve_utilization,
                projected_sleeve_utilization=projected_sleeve_utilization,
                current_asset_concentration=current_asset_concentration,
                projected_asset_concentration=projected_asset_concentration,
                current_position_qty=current_effective_qty,
                projected_position_qty=projected_position_qty,
                reduces_exposure=reduces_exposure,
                increases_exposure=increases_exposure,
                expands_gross=expands_gross,
                reservation_aware=True,
                hedge_aware=True,
                rationale=("intent_authorized_under_sovereign_effective_exposure_policy",),
            )

    def evaluate_pre_trade_portfolio_gate(
        self,
        *,
        policy_version: str,
        sleeve: Any,
        symbol: str,
        side: Any,
        qty: Any,
        price: Any,
        action: Optional[str] = None,
        broker_position_backed: bool = False,
        max_utilization: Optional[Any] = None,
        max_asset_concentration: Optional[Any] = None,
        cash_reserve_pct: Optional[Any] = None,
        correlation_threshold: Optional[Any] = None,
        correlation_slash_factor: Optional[Any] = None,
        correlation_pairs: Optional[Dict[Any, Any]] = None,
        correlation_truth_status: Optional[str] = None,
        existing_positions: Iterable[Dict[str, Any]] = (),
        open_orders: Iterable[Dict[str, Any]] = (),
        reservations: Iterable[Dict[str, Any]] = (),
    ) -> Dict[str, Any]:
        """
        Canonical read-only PAPER pre-trade portfolio-risk gate.

        This method is intentionally side-effect free. It does not reserve,
        release, fill, route, or call a broker. Runtime callers consume the
        returned evidence before broker submission; durable reservation mutation
        remains owned by the paper-scoped reservation lifecycle after broker ack.
        """
        with self._lock:
            policy = str(policy_version or "UNKNOWN_POLICY")
            normalized_symbol = self._normalize_symbol(symbol)
            side_value = _enum_from_ledger(OrderSide, side, field_name="side")
            qty_dec = _ensure_positive(_d(qty, field_name="qty"), "qty")
            price_dec = _ensure_positive(_d(price, field_name="price"), "price")
            action_text = str(action or side_value.value or "").strip().lower()

            max_util = (
                _d(max_utilization, field_name="max_utilization")
                if max_utilization is not None
                else self.policy.max_utilization
            )
            max_asset = (
                _d(max_asset_concentration, field_name="max_asset_concentration")
                if max_asset_concentration is not None
                else self.policy.max_asset_concentration
            )
            cash_reserve = (
                _d(cash_reserve_pct, field_name="cash_reserve_pct")
                if cash_reserve_pct is not None
                else ZERO
            )
            if cash_reserve < ZERO or cash_reserve >= ONE:
                return self._portfolio_gate_evidence(
                    status="CONTRIBUTED_BLOCK",
                    reason_code="PORTFOLIO_RISK_POLICY_INVALID",
                    summary="Portfolio risk policy has an invalid cash reserve.",
                    policy_version=policy,
                    symbol=symbol,
                    original_qty=qty_dec,
                    adjusted_qty=ZERO,
                    price=price_dec,
                    details={"cash_reserve_pct": str(cash_reserve)},
                )
            effective_max_utilization = min(max_util, ONE - cash_reserve)

            if side_value == OrderSide.SELL:
                if action_text == "sell_to_close" and broker_position_backed:
                    return self._portfolio_gate_evidence(
                        status="CONTRIBUTED_ALLOW",
                        reason_code="EXPOSURE_REDUCE_ONLY_BROKER_BACKED",
                        summary="Broker-position-backed exit is reduce-only and does not open fresh exposure.",
                        policy_version=policy,
                        symbol=symbol,
                        original_qty=qty_dec,
                        adjusted_qty=qty_dec,
                        price=price_dec,
                        details={
                            "reduce_only": True,
                            "broker_position_backed": True,
                            "side": side_value.value,
                            "action": action_text,
                        },
                    )
                return self._portfolio_gate_evidence(
                    status="CONTRIBUTED_BLOCK",
                    reason_code="SELL_REQUIRES_BROKER_POSITION_BACKED_AUTHORITY",
                    summary="SELL intent is not broker-position-backed reduce-only authority.",
                    policy_version=policy,
                    symbol=symbol,
                    original_qty=qty_dec,
                    adjusted_qty=ZERO,
                    price=price_dec,
                    details={
                        "reduce_only": action_text == "sell_to_close",
                        "broker_position_backed": bool(broker_position_backed),
                        "side": side_value.value,
                        "action": action_text,
                    },
                )

            external = self._external_exposure_summary(
                symbol=normalized_symbol,
                fallback_price=price_dec,
                existing_positions=existing_positions,
                open_orders=open_orders,
                reservations=reservations,
            )
            internal_global = self._effective_gross_notional
            internal_asset = self._asset_total_mark_notional(symbol) + self._asset_reserved_notional(symbol)
            use_internal_global = internal_global > ZERO
            use_internal_asset = internal_asset > ZERO
            current_global = internal_global if use_internal_global else external["total_notional"]
            current_asset = internal_asset if use_internal_asset else external["symbol_notional"]
            existing_symbols = set(self._active_exposure_symbols_locked())
            existing_symbols.update(external["symbols"])
            existing_symbols.discard(normalized_symbol)

            adjusted_qty = qty_dec
            slash_details = self._correlation_slash_decision(
                symbol=normalized_symbol,
                existing_symbols=existing_symbols,
                correlation_pairs=correlation_pairs or {},
                correlation_truth_status=correlation_truth_status,
                correlation_threshold=(
                    _d(correlation_threshold, field_name="correlation_threshold")
                    if correlation_threshold is not None
                    else Decimal("1")
                ),
                correlation_slash_factor=(
                    _d(correlation_slash_factor, field_name="correlation_slash_factor")
                    if correlation_slash_factor is not None
                    else ONE
                ),
            )
            if slash_details["blocked"]:
                return self._portfolio_gate_evidence(
                    status="CONTRIBUTED_BLOCK",
                    reason_code=slash_details["reason_code"],
                    summary=slash_details["summary"],
                    policy_version=policy,
                    symbol=symbol,
                    original_qty=qty_dec,
                    adjusted_qty=ZERO,
                    price=price_dec,
                    details={
                        **slash_details,
                        "current_global_notional_source": "internal" if use_internal_global else "external",
                        "current_asset_notional_source": "internal" if use_internal_asset else "external",
                    },
                )
            if slash_details["slash_applied"]:
                adjusted_qty = _quantize_down(qty_dec * slash_details["slash_factor"], self.policy.quantity_step)
                if adjusted_qty <= ZERO:
                    return self._portfolio_gate_evidence(
                        status="CONTRIBUTED_BLOCK",
                        reason_code="CORRELATION_SLASH_ZERO_QUANTITY",
                        summary="Correlation slash reduced the candidate below minimum executable quantity.",
                        policy_version=policy,
                        symbol=symbol,
                        original_qty=qty_dec,
                        adjusted_qty=ZERO,
                        price=price_dec,
                        details=slash_details,
                    )

            adjusted_notional = adjusted_qty * price_dec
            projected_global = current_global + adjusted_notional
            projected_asset = current_asset + adjusted_notional
            projected_global_utilization = _safe_div(projected_global, self._total_equity)
            projected_asset_concentration = _safe_div(projected_asset, self._total_equity)

            base_details = {
                "policy_version": policy,
                "max_utilization": str(effective_max_utilization),
                "configured_max_utilization": str(max_util),
                "cash_reserve_pct": str(cash_reserve),
                "max_asset_concentration": str(max_asset),
                "current_global_notional": str(current_global),
                "current_global_notional_source": "internal" if use_internal_global else "external",
                "current_asset_notional": str(current_asset),
                "current_asset_notional_source": "internal" if use_internal_asset else "external",
                "projected_order_notional": str(adjusted_notional),
                "projected_global_notional": str(projected_global),
                "projected_asset_notional": str(projected_asset),
                "projected_global_utilization": str(projected_global_utilization),
                "projected_asset_concentration": str(projected_asset_concentration),
                "existing_correlated_symbols": sorted(existing_symbols),
                "external_exposure_counts": external["source_counts"],
                "external_duplicates_skipped": external["duplicates_skipped"],
                **slash_details,
            }

            if projected_global_utilization > effective_max_utilization:
                return self._portfolio_gate_evidence(
                    status="CONTRIBUTED_BLOCK",
                    reason_code="GLOBAL_UTILIZATION_BREACH",
                    summary="ExposureManager blocked broker intent above B1 effective portfolio utilization cap.",
                    policy_version=policy,
                    symbol=symbol,
                    original_qty=qty_dec,
                    adjusted_qty=adjusted_qty,
                    price=price_dec,
                    details=base_details,
                )

            if projected_asset_concentration > max_asset:
                asset_cap_notional = self._total_equity * max_asset
                asset_headroom = asset_cap_notional - current_asset
                if asset_headroom <= ZERO:
                    return self._portfolio_gate_evidence(
                        status="CONTRIBUTED_BLOCK",
                        reason_code="ASSET_CONCENTRATION_VETO",
                        summary="ExposureManager blocked broker intent because current symbol exposure is already at or above the B1 concentration cap.",
                        policy_version=policy,
                        symbol=symbol,
                        original_qty=qty_dec,
                        adjusted_qty=adjusted_qty,
                        price=price_dec,
                        details={
                            **base_details,
                            "asset_cap_notional": str(asset_cap_notional),
                            "asset_headroom_notional": str(asset_headroom),
                            "concentration_clamp_applied": False,
                        },
                    )

                clamped_qty = _quantize_down(asset_headroom / price_dec, self.policy.quantity_step)
                if clamped_qty <= ZERO:
                    return self._portfolio_gate_evidence(
                        status="CONTRIBUTED_BLOCK",
                        reason_code="ASSET_CONCENTRATION_CLAMP_ZERO_QUANTITY",
                        summary="Per-symbol concentration clamp reduced the candidate below minimum executable quantity.",
                        policy_version=policy,
                        symbol=symbol,
                        original_qty=qty_dec,
                        adjusted_qty=ZERO,
                        price=price_dec,
                        details={
                            **base_details,
                            "asset_cap_notional": str(asset_cap_notional),
                            "asset_headroom_notional": str(asset_headroom),
                            "concentration_clamp_applied": True,
                            "pre_clamp_quantity": str(adjusted_qty),
                            "clamped_quantity": str(clamped_qty),
                        },
                    )

                adjusted_qty = clamped_qty
                adjusted_notional = adjusted_qty * price_dec
                projected_global = current_global + adjusted_notional
                projected_asset = current_asset + adjusted_notional
                projected_global_utilization = _safe_div(projected_global, self._total_equity)
                projected_asset_concentration = _safe_div(projected_asset, self._total_equity)
                base_details = {
                    **base_details,
                    "asset_cap_notional": str(asset_cap_notional),
                    "asset_headroom_notional": str(asset_headroom),
                    "concentration_clamp_applied": True,
                    "pre_clamp_quantity": str(qty_dec),
                    "pre_clamp_adjusted_quantity": str(
                        _quantize_down(qty_dec * slash_details["slash_factor"], self.policy.quantity_step)
                        if slash_details["slash_applied"]
                        else qty_dec
                    ),
                    "clamped_quantity": str(adjusted_qty),
                    "projected_order_notional": str(adjusted_notional),
                    "projected_global_notional": str(projected_global),
                    "projected_asset_notional": str(projected_asset),
                    "projected_global_utilization": str(projected_global_utilization),
                    "projected_asset_concentration": str(projected_asset_concentration),
                }

            if base_details.get("concentration_clamp_applied") is True:
                reason_code = "ASSET_CONCENTRATION_CLAMP_APPLIED"
            else:
                reason_code = "CORRELATION_SLASH_APPLIED" if slash_details["slash_applied"] else "EXPOSURE_MANAGER_AUTHORIZED"
            summary = (
                "ExposureManager clamped broker intent to the remaining B1 per-symbol concentration headroom before economic re-evaluation."
                if reason_code == "ASSET_CONCENTRATION_CLAMP_APPLIED"
                else
                "ExposureManager applied correlation slash before economic re-evaluation."
                if slash_details["slash_applied"]
                else "ExposureManager authorized broker intent under B1 portfolio-risk policy."
            )
            return self._portfolio_gate_evidence(
                status="CONTRIBUTED_ALLOW",
                reason_code=reason_code,
                summary=summary,
                policy_version=policy,
                symbol=symbol,
                original_qty=qty_dec,
                adjusted_qty=adjusted_qty,
                price=price_dec,
                details=base_details,
            )

    def _portfolio_gate_evidence(
        self,
        *,
        status: str,
        reason_code: str,
        summary: str,
        policy_version: str,
        symbol: str,
        original_qty: Decimal,
        adjusted_qty: Decimal,
        price: Decimal,
        details: Dict[str, Any],
    ) -> Dict[str, Any]:
        adjusted_notional = adjusted_qty * price if adjusted_qty > ZERO else ZERO
        return {
            "module": "ExposureManager",
            "authority_class": "RISK",
            "status": status,
            "reason_code": reason_code,
            "summary": summary,
            "policy_version": policy_version,
            "symbol": symbol,
            "authorized": status != "CONTRIBUTED_BLOCK",
            "route_permitted": status != "CONTRIBUTED_BLOCK",
            "broker_post": False,
            "exposure_manager_called": True,
            "live_wired": True,
            "active_veto_owner": True,
            "original_quantity": str(original_qty),
            "adjusted_quantity": str(adjusted_qty),
            "adjusted_notional": str(adjusted_notional),
            "adjusted": adjusted_qty != original_qty,
            "details": details,
        }

    def _external_exposure_summary(
        self,
        *,
        symbol: str,
        fallback_price: Decimal,
        existing_positions: Iterable[Dict[str, Any]],
        open_orders: Iterable[Dict[str, Any]],
        reservations: Iterable[Dict[str, Any]],
    ) -> Dict[str, Any]:
        total = ZERO
        symbol_total = ZERO
        symbols: set[str] = set()
        seen_keys: set[str] = set()
        duplicates_skipped = 0
        source_counts = {"positions": 0, "open_orders": 0, "reservations": 0}

        for source_name, rows in (
            ("positions", existing_positions),
            ("open_orders", open_orders),
            ("reservations", reservations),
        ):
            for row in rows or ():
                if not isinstance(row, dict):
                    continue
                if source_name == "open_orders" and not self._external_order_active(row):
                    continue
                if source_name == "reservations" and not self._external_reservation_active(row):
                    continue
                row_symbol = self._normalize_symbol(row.get("symbol"))
                if not row_symbol:
                    continue
                dedupe_key = self._external_exposure_dedupe_key(row, source_name)
                if dedupe_key and dedupe_key in seen_keys:
                    duplicates_skipped += 1
                    continue
                if dedupe_key:
                    seen_keys.add(dedupe_key)
                notional = self._external_row_notional(row, fallback_price=fallback_price)
                if notional <= ZERO:
                    continue
                symbols.add(row_symbol)
                total += notional
                source_counts[source_name] += 1
                if row_symbol == symbol:
                    symbol_total += notional

        return {
            "total_notional": total,
            "symbol_notional": symbol_total,
            "symbols": symbols,
            "source_counts": source_counts,
            "duplicates_skipped": duplicates_skipped,
        }

    def _external_row_notional(self, row: Dict[str, Any], *, fallback_price: Decimal) -> Decimal:
        for key in ("notional", "market_value", "current_exposure", "notional_basis", "value"):
            value = row.get(key)
            if value not in (None, ""):
                try:
                    return abs(_d(value, field_name=key))
                except ValueError:
                    continue
        qty = None
        for key in ("quantity", "qty", "open_qty", "remaining_qty", "original_qty"):
            value = row.get(key)
            if value not in (None, ""):
                try:
                    qty = abs(_d(value, field_name=key))
                    break
                except ValueError:
                    continue
        if qty is None or qty <= ZERO:
            return ZERO
        price = None
        for key in (
            "mark_price",
            "current_price",
            "average_entry_price",
            "avg_entry_price",
            "limit_price",
            "price_basis",
            "price",
        ):
            value = row.get(key)
            if value not in (None, ""):
                try:
                    price = _d(value, field_name=key)
                    break
                except ValueError:
                    continue
        if price is None or price <= ZERO:
            price = fallback_price
        return qty * price if price > ZERO else ZERO

    @staticmethod
    def _external_order_active(row: Dict[str, Any]) -> bool:
        status = str(row.get("status", "open")).strip().lower()
        return status in {"open", "accepted", "pending", "new", "partially_filled", "unknown", "active"}

    @staticmethod
    def _external_reservation_active(row: Dict[str, Any]) -> bool:
        status = str(row.get("status", "active")).strip().lower()
        return status in {
            "active",
            "reserved",
            "pending",
            "unknown",
            "created",
            "routing",
            "acknowledged",
            "partially_filled",
        }

    @staticmethod
    def _external_exposure_dedupe_key(row: Dict[str, Any], source_name: str) -> Optional[str]:
        for key in ("reservation_dedupe_key", "dedupe_key", "client_order_id", "order_id", "reservation_id", "id"):
            value = row.get(key)
            if value not in (None, ""):
                return f"{source_name}:{value}"
        return None

    def _active_exposure_symbols_locked(self) -> set[str]:
        symbols: set[str] = set()
        for sleeve_positions in self._inventory.values():
            for symbol, position in sleeve_positions.items():
                if position.qty != ZERO:
                    symbols.add(self._normalize_symbol(symbol))
        for reservation in self._reservations.values():
            if reservation.open_qty > ZERO and reservation.status not in {
                ReservationStatus.CANCELLED,
                ReservationStatus.FILLED,
                ReservationStatus.REJECTED,
                ReservationStatus.EXPIRED,
            }:
                symbols.add(self._normalize_symbol(reservation.symbol))
        return symbols

    def _correlation_slash_decision(
        self,
        *,
        symbol: str,
        existing_symbols: set[str],
        correlation_pairs: Dict[Any, Any],
        correlation_truth_status: Optional[str],
        correlation_threshold: Decimal,
        correlation_slash_factor: Decimal,
    ) -> Dict[str, Any]:
        if not existing_symbols:
            return {
                "blocked": False,
                "slash_applied": False,
                "reason_code": "CORRELATION_EMPTY_BOOK_ALLOW",
                "summary": "No existing exposure requires correlation truth.",
                "max_correlation": None,
                "max_correlation_symbol": None,
                "slash_factor": ONE,
                "correlation_truth_status": correlation_truth_status or "EMPTY_BOOK_NOT_REQUIRED",
            }

        truth_status = str(correlation_truth_status or "").strip().upper()
        if truth_status in {"MISSING", "STALE", "UNKNOWN", "UNAVAILABLE"}:
            return {
                "blocked": True,
                "slash_applied": False,
                "reason_code": f"CORRELATION_TRUTH_{truth_status}",
                "summary": "Correlation truth is missing or stale while existing exposure is present.",
                "max_correlation": None,
                "max_correlation_symbol": None,
                "slash_factor": ONE,
                "correlation_truth_status": truth_status,
            }

        max_corr: Optional[Decimal] = None
        max_symbol: Optional[str] = None
        for existing in sorted(existing_symbols):
            lookup = self._lookup_correlation_pair(correlation_pairs, symbol, existing)
            if lookup is None:
                continue
            corr, pair_status = lookup
            if pair_status in {"STALE", "MISSING", "UNKNOWN", "UNAVAILABLE"}:
                return {
                    "blocked": True,
                    "slash_applied": False,
                    "reason_code": f"CORRELATION_TRUTH_{pair_status}",
                    "summary": "Pair-level correlation truth is missing or stale while existing exposure is present.",
                    "max_correlation": None,
                    "max_correlation_symbol": existing,
                    "slash_factor": ONE,
                    "correlation_truth_status": pair_status,
                }
            abs_corr = abs(corr)
            if max_corr is None or abs_corr > max_corr:
                max_corr = abs_corr
                max_symbol = existing

        if max_corr is None:
            return {
                "blocked": True,
                "slash_applied": False,
                "reason_code": "CORRELATION_TRUTH_MISSING",
                "summary": "No correlation pair was supplied for existing exposure.",
                "max_correlation": None,
                "max_correlation_symbol": None,
                "slash_factor": ONE,
                "correlation_truth_status": truth_status or "MISSING",
            }

        if max_corr >= correlation_threshold:
            return {
                "blocked": False,
                "slash_applied": True,
                "reason_code": "CORRELATION_SLASH_APPLIED",
                "summary": "Correlation threshold breached; candidate quantity is slashed before NetEdge.",
                "max_correlation": str(max_corr),
                "max_correlation_symbol": max_symbol,
                "slash_factor": correlation_slash_factor,
                "correlation_threshold": str(correlation_threshold),
                "correlation_truth_status": truth_status or "FRESH",
            }

        return {
            "blocked": False,
            "slash_applied": False,
            "reason_code": "CORRELATION_BELOW_THRESHOLD",
            "summary": "Correlation truth was present and below the B1 slash threshold.",
            "max_correlation": str(max_corr),
            "max_correlation_symbol": max_symbol,
            "slash_factor": ONE,
            "correlation_threshold": str(correlation_threshold),
            "correlation_truth_status": truth_status or "FRESH",
        }

    def _lookup_correlation_pair(
        self,
        correlation_pairs: Dict[Any, Any],
        symbol: str,
        existing: str,
    ) -> Optional[Tuple[Decimal, str]]:
        if not correlation_pairs:
            return None
        candidates = (
            (symbol, existing),
            (existing, symbol),
            tuple(sorted((symbol, existing))),
            f"{symbol}|{existing}",
            f"{existing}|{symbol}",
            f"{symbol}:{existing}",
            f"{existing}:{symbol}",
        )
        value = None
        for key in candidates:
            if key in correlation_pairs:
                value = correlation_pairs[key]
                break
        if value is None:
            return None
        status = "FRESH"
        if isinstance(value, dict):
            status = str(value.get("status") or value.get("truth_status") or "FRESH").strip().upper()
            value = value.get("correlation")
        try:
            return _d(value, field_name="correlation"), status
        except ValueError:
            return None

    @staticmethod
    def _normalize_symbol(symbol: Any) -> str:
        return str(symbol or "").strip().upper().replace("-", "/")

    # ------------------------------------------------------------------
    # Reservation management
    # ------------------------------------------------------------------

    def reserve_intent(
        self,
        reservation_id: str,
        sleeve: SleeveType,
        symbol: str,
        side: OrderSide,
        qty: Decimal,
        price: Decimal,
        *,
        trade_intent: TradeIntent = TradeIntent.UNKNOWN,
        reduce_only: bool = False,
        replay_mode: ReplayMode = ReplayMode.LIVE,
        is_hedge: bool = False,
        client_order_id: Optional[str] = None,
        dedupe_key: Optional[str] = None,
        status: ReservationStatus = ReservationStatus.CREATED,
    ) -> PendingReservation:
        with self._lock:
            if reservation_id in self._reservations:
                return self._reservations[reservation_id]

            if dedupe_key is not None and dedupe_key in self._reservation_dedupe:
                existing_id = self._reservation_dedupe[dedupe_key]
                if existing_id in self._reservations:
                    return self._reservations[existing_id]

            result = self.validate_intent_detailed(
                sleeve=sleeve,
                symbol=symbol,
                side=side,
                qty=qty,
                price=price,
                trade_intent=trade_intent,
                reduce_only=reduce_only,
                is_hedge=is_hedge,
            )
            if not result.authorized:
                raise ValueError(f"reservation rejected: {result.reason}")

            qty = _quantize_down(_d(qty, field_name="qty"), self.policy.quantity_step)
            if qty < self.policy.min_reservation_qty:
                raise ValueError("reservation below minimum reservation quantity")

            confidence = self._default_confidence_weight(status)

            reservation = PendingReservation(
                reservation_id=reservation_id,
                sleeve=sleeve,
                symbol=symbol,
                side=side,
                qty=qty,
                price=_d(price, field_name="price"),
                trade_intent=trade_intent,
                reduce_only=reduce_only,
                is_hedge=is_hedge,
                status=status,
                confidence_weight=confidence,
                replay_mode=replay_mode,
                client_order_id=client_order_id,
                dedupe_key=dedupe_key,
            )

            self._reservations[reservation_id] = reservation
            if dedupe_key is not None:
                self._reservation_dedupe[dedupe_key] = reservation_id

            self._bump_version()
            self.recompute_aggregates()
            self._append_mutation(
                mutation_type=MutationType.RESERVATION_CREATED,
                symbol=symbol,
                sleeve=sleeve,
                payload={
                    "reservation_id": reservation_id,
                    "side": side.value,
                    "qty": str(qty),
                    "price": str(price),
                    "status": status.value,
                    "confidence_weight": str(confidence),
                    "is_hedge": is_hedge,
                    "trade_intent": trade_intent.value,
                },
            )
            return reservation

    def update_reservation_status(
        self,
        reservation_id: str,
        *,
        status: ReservationStatus,
    ) -> Optional[PendingReservation]:
        with self._lock:
            reservation = self._reservations.get(reservation_id)
            if reservation is None:
                return None

            updated = replace(
                reservation,
                status=status,
                confidence_weight=self._default_confidence_weight(status),
                last_update_ns=_now_ns(),
            )
            self._reservations[reservation_id] = updated
            self._bump_version()
            self.recompute_aggregates()
            self._append_mutation(
                mutation_type=MutationType.RESERVATION_UPDATED,
                symbol=updated.symbol,
                sleeve=updated.sleeve,
                payload={
                    "reservation_id": reservation_id,
                    "status": status.value,
                    "confidence_weight": str(updated.confidence_weight),
                },
            )
            return updated

    def release_reservation(
        self,
        reservation_id: str,
        *,
        cancelled_qty: Optional[Decimal] = None,
    ) -> Optional[PendingReservation]:
        with self._lock:
            reservation = self._reservations.get(reservation_id)
            if reservation is None:
                return None

            if cancelled_qty is None:
                self._remove_reservation(reservation_id)
                return None

            cancelled_qty = _ensure_non_negative(_d(cancelled_qty, field_name="cancelled_qty"), "cancelled_qty")
            updated = replace(
                reservation,
                cancelled_qty=min(reservation.qty, reservation.cancelled_qty + cancelled_qty),
                last_update_ns=_now_ns(),
            )

            if updated.open_qty <= ZERO:
                self._remove_reservation(reservation_id)
                return None

            self._reservations[reservation_id] = updated
            self._bump_version()
            self.recompute_aggregates()
            self._append_mutation(
                mutation_type=MutationType.RESERVATION_RELEASED,
                symbol=updated.symbol,
                sleeve=updated.sleeve,
                payload={
                    "reservation_id": reservation_id,
                    "cancelled_qty": str(cancelled_qty),
                    "open_qty": str(updated.open_qty),
                },
            )
            return updated

    def apply_fill_to_reservation(
        self,
        reservation_id: str,
        *,
        fill_qty: Decimal,
    ) -> Optional[PendingReservation]:
        with self._lock:
            reservation = self._reservations.get(reservation_id)
            if reservation is None:
                return None

            fill_qty = _ensure_non_negative(_d(fill_qty, field_name="fill_qty"), "fill_qty")
            updated = replace(
                reservation,
                filled_qty=min(reservation.qty, reservation.filled_qty + fill_qty),
                status=ReservationStatus.PARTIALLY_FILLED,
                confidence_weight=self._default_confidence_weight(ReservationStatus.PARTIALLY_FILLED),
                last_update_ns=_now_ns(),
            )

            if updated.open_qty <= ZERO:
                self._remove_reservation(reservation_id, terminal_status=ReservationStatus.FILLED)
                return None

            self._reservations[reservation_id] = updated
            self._bump_version()
            self.recompute_aggregates()
            self._append_mutation(
                mutation_type=MutationType.RESERVATION_UPDATED,
                symbol=updated.symbol,
                sleeve=updated.sleeve,
                payload={
                    "reservation_id": reservation_id,
                    "fill_qty": str(fill_qty),
                    "filled_qty_total": str(updated.filled_qty),
                    "open_qty": str(updated.open_qty),
                },
            )
            return updated

    def guarded_open_reservation(
        self,
        *,
        state_store: Any,
        reservation_id: str,
        client_order_id: str,
        decision_uuid: Optional[str],
        reservation_dedupe_key: str,
        symbol: str,
        side: Any,
        sleeve: Any,
        qty: Decimal,
        price_basis: Any,
        order_type: Optional[str] = None,
        source_lifecycle_phase: Optional[str] = None,
        source_idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        result = self._guard_result(reservation_id=reservation_id, client_order_id=client_order_id)
        if state_store is None:
            return self._guard_failed(result, "missing_state_store")

        try:
            price = _ensure_positive(_d(price_basis, field_name="price_basis"), "price_basis")
            qty_dec = _ensure_positive(_d(qty, field_name="qty"), "qty")
            side_enum = _enum_from_ledger(OrderSide, side, field_name="side")
            sleeve_enum = _enum_from_ledger(SleeveType, sleeve, field_name="sleeve")
        except ValueError as exc:
            return self._guard_failed(result, str(exc))

        if state_store.get_reservation_release_tombstone(reservation_id=reservation_id) is not None:
            return self._guard_failed(result, "release_tombstone_present")

        existing_active = self._active_ledger_row_for_dedupe(state_store, reservation_dedupe_key)
        if existing_active is not None:
            if existing_active.get("reservation_id") == reservation_id:
                return self._guard_idempotent(result, "active_reservation_already_persisted")
            return self._guard_failed(result, "duplicate_active_dedupe_conflict")

        with self._lock:
            existing_memory = self._reservations.get(reservation_id)
            if existing_memory is not None:
                if existing_memory.dedupe_key == reservation_dedupe_key:
                    return self._guard_idempotent(result, "reservation_already_open")
                return self._guard_failed(result, "reservation_id_dedupe_conflict")

        mutation_applied = False
        try:
            reservation = self.reserve_intent(
                reservation_id=reservation_id,
                sleeve=sleeve_enum,
                symbol=symbol,
                side=side_enum,
                qty=qty_dec,
                price=price,
                client_order_id=client_order_id,
                dedupe_key=reservation_dedupe_key,
            )
            mutation_applied = True
        except Exception as exc:
            return self._guard_failed(result, f"reserve_intent_failed:{exc}")

        row = self._reservation_to_ledger_row(reservation, is_active=True, is_terminal=False)
        row.update({
            "decision_uuid": decision_uuid,
            "order_type": order_type,
            "source_lifecycle_phase": source_lifecycle_phase,
            "source_idempotency_key": source_idempotency_key or reservation_dedupe_key,
        })
        if state_store.upsert_reservation_ledger(row):
            result.update({
                "applied": True,
                "persistence_applied": True,
                "mutation_applied": mutation_applied,
            })
            return result

        rollback_applied = self._rollback_open_reservation(reservation_id, reservation_dedupe_key)
        result.update({
            "failed_reason": "ledger_upsert_failed_rollback_applied" if rollback_applied else "ledger_upsert_failed_recovery_needed",
            "mutation_applied": mutation_applied,
            "rollback_applied": rollback_applied,
        })
        return result

    def guarded_apply_fill_to_reservation(
        self,
        *,
        state_store: Any,
        reservation_id: str,
        client_order_id: str,
        fill_idempotency_key: str,
        cumulative_filled_qty: Any,
        fill_delta_qty: Optional[Any] = None,
        status_source: str,
        source_event_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        result = self._guard_result(reservation_id=reservation_id, client_order_id=client_order_id)
        if state_store is None:
            return self._guard_failed(result, "missing_state_store")

        with self._lock:
            reservation = self._reservations.get(reservation_id)
        if reservation is None:
            return self._guard_failed(result, "reservation_missing")

        ledger = state_store.get_reservation_ledger(reservation_id)
        if ledger is None:
            return self._guard_failed(result, "reservation_ledger_missing")

        existing_progress = state_store.list_reservation_fill_progress(reservation_id)
        if any(item.get("fill_idempotency_key") == fill_idempotency_key for item in existing_progress):
            return self._guard_idempotent(result, "fill_key_already_recorded")

        try:
            cumulative = _ensure_non_negative(_d(cumulative_filled_qty, field_name="cumulative_filled_qty"), "cumulative_filled_qty")
        except ValueError as exc:
            return self._guard_failed(result, str(exc))

        max_seen = self._max_recorded_cumulative_fill(existing_progress)
        if cumulative <= reservation.filled_qty or (max_seen is not None and cumulative <= max_seen):
            return self._guard_failed(result, "non_advancing_cumulative_fill")

        delta = cumulative - reservation.filled_qty
        if fill_delta_qty is not None:
            try:
                requested_delta = _ensure_non_negative(_d(fill_delta_qty, field_name="fill_delta_qty"), "fill_delta_qty")
            except ValueError as exc:
                return self._guard_failed(result, str(exc))
            delta = min(delta, requested_delta)
        if delta <= ZERO:
            return self._guard_failed(result, "non_advancing_fill_delta")

        progress = {
            "fill_idempotency_key": fill_idempotency_key,
            "reservation_id": reservation_id,
            "client_order_id": client_order_id,
            "cumulative_filled_qty": str(cumulative),
            "fill_delta_qty": str(delta),
            "status_source": status_source,
            "source_event_id": source_event_id,
            "applied_at_ns": _now_ns(),
        }
        if not state_store.record_reservation_fill_progress(progress):
            return self._guard_failed(result, "fill_progress_persist_failed")
        result["persistence_applied"] = True

        try:
            updated = self.apply_fill_to_reservation(reservation_id, fill_qty=delta)
            result["mutation_applied"] = True
        except Exception as exc:
            return self._guard_failed(result, f"fill_mutation_failed_recovery_needed:{exc}")

        row = self._terminal_or_active_row_after_fill(reservation, updated, cumulative)
        if state_store.upsert_reservation_ledger(row):
            result["applied"] = True
            return result

        result["failed_reason"] = "ledger_upsert_failed_recovery_needed"
        return result

    def guarded_release_reservation(
        self,
        *,
        state_store: Any,
        reservation_id: str,
        client_order_id: str,
        reservation_dedupe_key: str,
        release_idempotency_key: str,
        release_reason: str,
        terminal_status: str,
        terminal_source: str,
        released_qty: Any,
        released_notional: Optional[Any] = None,
        source_event_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        result = self._guard_result(reservation_id=reservation_id, client_order_id=client_order_id)
        if state_store is None:
            return self._guard_failed(result, "missing_state_store")

        terminal_reservation_status = self._reservation_status_from_terminal_proof(terminal_status)
        if terminal_reservation_status is None:
            return self._guard_failed(result, "unsupported_terminal_status")

        existing_by_key = state_store.get_reservation_release_tombstone(
            release_idempotency_key=release_idempotency_key,
        )
        if existing_by_key is not None:
            if existing_by_key.get("reservation_id") == reservation_id:
                return self._guard_idempotent(result, "release_key_already_recorded")
            return self._guard_failed(result, "release_key_conflict")

        existing_by_reservation = state_store.get_reservation_release_tombstone(reservation_id=reservation_id)
        if existing_by_reservation is not None:
            return self._guard_failed(result, "reservation_already_released")

        with self._lock:
            reservation = self._reservations.get(reservation_id)
        if reservation is None:
            return self._guard_failed(result, "reservation_missing")

        try:
            released_qty_dec = _ensure_non_negative(_d(released_qty, field_name="released_qty"), "released_qty")
        except ValueError as exc:
            return self._guard_failed(result, str(exc))

        tombstone = {
            "release_idempotency_key": release_idempotency_key,
            "reservation_id": reservation_id,
            "client_order_id": client_order_id,
            "decision_uuid": self._decision_uuid_from_dedupe_key(reservation_dedupe_key, client_order_id),
            "reservation_dedupe_key": reservation_dedupe_key,
            "release_reason": release_reason,
            "terminal_status": terminal_status,
            "terminal_source": terminal_source,
            "released_qty": str(released_qty_dec),
            "released_notional": None if released_notional is None else str(released_notional),
            "released_at_ns": _now_ns(),
            "source_event_id": source_event_id,
            "release_applied": True,
            "exposure_release_scope": "reservation_only",
        }
        if not state_store.record_reservation_release_tombstone(tombstone):
            return self._guard_failed(result, "release_tombstone_persist_failed")
        result["persistence_applied"] = True

        terminal_row = self._terminal_ledger_row_for_release(
            reservation,
            terminal_status=terminal_reservation_status,
            terminal_reason=release_reason,
            terminal_source=terminal_source,
            source_idempotency_key=release_idempotency_key,
        )
        try:
            self._remove_reservation(reservation_id, terminal_status=terminal_reservation_status)
            result["mutation_applied"] = True
        except Exception as exc:
            return self._guard_failed(result, f"release_mutation_failed_recovery_needed:{exc}")

        if state_store.upsert_reservation_ledger(terminal_row):
            result["applied"] = True
            return result

        result["failed_reason"] = "terminal_ledger_upsert_failed_recovery_needed"
        return result

    def age_stale_reservations(self, now_ns: Optional[int] = None) -> List[str]:
        with self._lock:
            now_ns = _now_ns() if now_ns is None else now_ns
            stale_ids: List[str] = []

            for rid, reservation in list(self._reservations.items()):
                if reservation.status in {
                    ReservationStatus.CANCELLED,
                    ReservationStatus.FILLED,
                    ReservationStatus.REJECTED,
                    ReservationStatus.EXPIRED,
                }:
                    continue

                if (now_ns - reservation.last_update_ns) > self.policy.stale_reservation_ns:
                    updated = replace(
                        reservation,
                        status=ReservationStatus.STALE,
                        confidence_weight=self._default_confidence_weight(ReservationStatus.STALE),
                        last_update_ns=now_ns,
                    )
                    self._reservations[rid] = updated
                    stale_ids.append(rid)

            if stale_ids:
                self._bump_version()
                self.recompute_aggregates()
                for rid in stale_ids:
                    reservation = self._reservations[rid]
                    self._append_mutation(
                        mutation_type=MutationType.RESERVATION_UPDATED,
                        symbol=reservation.symbol,
                        sleeve=reservation.sleeve,
                        payload={
                            "reservation_id": rid,
                            "status": ReservationStatus.STALE.value,
                        },
                    )

            return stale_ids

    # ------------------------------------------------------------------
    # Fill handling / inventory accounting
    # ------------------------------------------------------------------

    def handle_fill(
        self,
        sleeve: SleeveType,
        symbol: str,
        side: OrderSide,
        fill_qty: Decimal,
        fill_price: Decimal,
        fee_paid: Decimal,
        ts_ns: int,
    ) -> None:
        self.handle_fill_detailed(
            sleeve=sleeve,
            symbol=symbol,
            side=side,
            fill_qty=fill_qty,
            fill_price=fill_price,
            fee_paid=fee_paid,
            ts_ns=ts_ns,
            reservation_id=None,
        )

    def handle_fill_detailed(
        self,
        sleeve: SleeveType,
        symbol: str,
        side: OrderSide,
        fill_qty: Decimal,
        fill_price: Decimal,
        fee_paid: Decimal,
        ts_ns: int,
        reservation_id: Optional[str] = None,
    ) -> FillResult:
        with self._lock:
            fill_qty = _ensure_positive(_d(fill_qty, field_name="fill_qty"), "fill_qty")
            fill_price = _ensure_positive(_d(fill_price, field_name="fill_price"), "fill_price")
            fee_paid = _ensure_non_negative(_d(fee_paid, field_name="fee_paid"), "fee_paid")

            if side not in {OrderSide.BUY, OrderSide.SELL}:
                raise ValueError(f"unsupported side for fill handling: {side}")

            qty_signed = _signed_qty_for_side(side, fill_qty)

            if symbol not in self._inventory[sleeve]:
                self._inventory[sleeve][symbol] = PositionState(
                    symbol=symbol,
                    sleeve=sleeve,
                    last_update_ns=ts_ns,
                )

            pos = self._inventory[sleeve][symbol]
            old_qty = pos.qty
            old_wap = pos.wap

            realized_pnl_delta = ZERO
            reversed_position = False

            if old_qty == ZERO:
                new_qty = qty_signed
                new_wap = fill_price
            elif (old_qty > ZERO and qty_signed > ZERO) or (old_qty < ZERO and qty_signed < ZERO):
                total_cost = (old_qty * pos.wap) + (qty_signed * fill_price)
                new_qty = old_qty + qty_signed
                new_wap = _abs(total_cost / new_qty) if new_qty != ZERO else ZERO
            else:
                reduction_qty = min(_abs(old_qty), _abs(qty_signed))
                if old_qty > ZERO:
                    realized_pnl_delta = (fill_price - pos.wap) * reduction_qty
                else:
                    realized_pnl_delta = (pos.wap - fill_price) * reduction_qty

                new_qty = old_qty + qty_signed

                if (old_qty > ZERO and new_qty < ZERO) or (old_qty < ZERO and new_qty > ZERO):
                    reversed_position = True
                    new_wap = fill_price
                elif new_qty == ZERO:
                    new_wap = ZERO
                else:
                    new_wap = pos.wap

            current_mark = pos.mark_price if pos.mark_price > ZERO else fill_price
            updated = replace(
                pos,
                qty=new_qty,
                wap=new_wap,
                mark_price=current_mark,
                mark_ts_ns=ts_ns if current_mark == fill_price else pos.mark_ts_ns,
                realized_pnl=pos.realized_pnl + realized_pnl_delta,
                fees_paid=pos.fees_paid + fee_paid,
                last_update_ns=ts_ns,
            )

            if updated.qty == ZERO:
                updated = replace(updated, unrealized_pnl=ZERO, mark_price=fill_price, mark_ts_ns=ts_ns)
            elif updated.qty > ZERO:
                updated = replace(updated, unrealized_pnl=(updated.mark_price - updated.wap) * updated.qty)
            else:
                updated = replace(updated, unrealized_pnl=(updated.wap - updated.mark_price) * _abs(updated.qty))

            self._inventory[sleeve][symbol] = updated

            if reservation_id is not None:
                self.apply_fill_to_reservation(reservation_id, fill_qty=fill_qty)

            self._bump_version()
            self.recompute_aggregates()
            self._append_mutation(
                mutation_type=MutationType.FILL_APPLIED,
                symbol=symbol,
                sleeve=sleeve,
                payload={
                    "side": side.value,
                    "fill_qty": str(fill_qty),
                    "fill_price": str(fill_price),
                    "fee_paid": str(fee_paid),
                    "old_qty": str(old_qty),
                    "new_qty": str(updated.qty),
                    "reservation_id": reservation_id,
                },
            )

            position_closed = updated.qty == ZERO

            logger.info(
                "[EXPOSURE_SYNC] sleeve=%s symbol=%s old_qty=%s new_qty=%s residual_exposure=%s",
                sleeve.value,
                symbol,
                old_qty,
                updated.qty,
                self._residual_net_exposure,
            )

            return FillResult(
                sleeve=sleeve,
                symbol=symbol,
                old_qty=old_qty,
                new_qty=updated.qty,
                old_wap=old_wap,
                new_wap=updated.wap,
                realized_pnl_delta=realized_pnl_delta,
                total_realized_pnl=updated.realized_pnl,
                fee_paid=fee_paid,
                effective_gross_after=self._effective_gross_notional,
                residual_net_exposure_after=self._residual_net_exposure,
                sleeve_usage_after=self._sleeve_usage_mark[sleeve] + self._sleeve_reserved_notional[sleeve],
                reversed_position=reversed_position,
                position_closed=position_closed,
            )

    # ------------------------------------------------------------------
    # MTM updates
    # ------------------------------------------------------------------

    def update_unrealized_pnl(self, symbol: str, current_mid_price: Decimal) -> None:
        self.update_unrealized_pnl_detailed(symbol=symbol, current_mid_price=current_mid_price)

    def update_unrealized_pnl_detailed(self, symbol: str, current_mid_price: Decimal) -> Dict[SleeveType, Decimal]:
        with self._lock:
            current_mid_price = _ensure_positive(_d(current_mid_price, field_name="current_mid_price"), "current_mid_price")
            updated_map: Dict[SleeveType, Decimal] = {}
            now_ns = _now_ns()

            for sleeve in SleeveType:
                if symbol in self._inventory[sleeve]:
                    pos = self._inventory[sleeve][symbol]
                    if pos.qty == ZERO:
                        unrealized = ZERO
                    elif pos.qty > ZERO:
                        unrealized = (current_mid_price - pos.wap) * pos.qty
                    else:
                        unrealized = (pos.wap - current_mid_price) * _abs(pos.qty)

                    self._inventory[sleeve][symbol] = replace(
                        pos,
                        mark_price=current_mid_price,
                        mark_ts_ns=now_ns,
                        unrealized_pnl=unrealized,
                    )
                    updated_map[sleeve] = unrealized

            if updated_map:
                self._bump_version()
                self.recompute_aggregates()
                self._append_mutation(
                    mutation_type=MutationType.MTM_UPDATED,
                    symbol=symbol,
                    sleeve=None,
                    payload={"current_mid_price": str(current_mid_price)},
                )

            return updated_map

    # ------------------------------------------------------------------
    # Equity / capital adjustments
    # ------------------------------------------------------------------

    def update_equity(self, new_equity: Decimal) -> None:
        with self._lock:
            new_equity = _ensure_positive(_d(new_equity, field_name="new_equity"), "new_equity")
            old_equity = self._total_equity
            self._total_equity = new_equity
            self._bump_version()
            self._append_mutation(
                mutation_type=MutationType.EQUITY_UPDATED,
                symbol=None,
                sleeve=None,
                payload={
                    "old_equity": str(old_equity),
                    "new_equity": str(new_equity),
                },
            )

    # ------------------------------------------------------------------
    # Snapshots / surfaces / hazards
    # ------------------------------------------------------------------

    def get_risk_snapshot(self, current_prices: Dict[str, Decimal]) -> Dict[str, Any]:
        snapshot = self.get_risk_snapshot_typed(current_prices=current_prices)
        return {
            "timestamp_ns": snapshot.timestamp_ns,
            "global": {
                "equity": float(snapshot.global_snapshot.equity),
                "gross_notional": float(snapshot.global_snapshot.gross_mark_notional),
                "net_delta": float(snapshot.global_snapshot.net_mark_exposure),
                "raw_net_exposure": float(snapshot.global_snapshot.raw_net_exposure),
                "residual_net_exposure": float(snapshot.global_snapshot.residual_net_exposure),
                "hedge_mark_exposure": float(snapshot.global_snapshot.hedge_mark_exposure),
                "total_unrealized_pnl": float(snapshot.global_snapshot.total_unrealized_pnl),
                "utilization_pct": float(snapshot.global_snapshot.utilization_pct),
                "reserved_notional_weighted": float(snapshot.global_snapshot.reserved_notional_weighted),
                "reserved_hedge_notional_weighted": float(snapshot.global_snapshot.reserved_hedge_notional_weighted),
                "effective_gross_notional": float(snapshot.global_snapshot.effective_gross_notional),
            },
            "sleeves": {
                key: {
                    "filled_mark_notional": float(val.filled_mark_notional),
                    "reserved_notional_weighted": float(val.reserved_notional_weighted),
                    "reserved_hedge_notional_weighted": float(val.reserved_hedge_notional_weighted),
                    "effective_notional": float(val.effective_notional),
                    "raw_net_exposure": float(val.raw_net_exposure),
                    "residual_net_exposure": float(val.residual_net_exposure),
                    "unrealized_pnl": float(val.unrealized_pnl),
                    "realized_pnl": float(val.realized_pnl),
                    "utilization": float(val.utilization),
                }
                for key, val in snapshot.sleeves.items()
            },
            "hazard_level": snapshot.global_snapshot.hazard_level,
            "version": snapshot.version,
            "quality": snapshot.quality.value,
            "reconciliation_attribution_loss": snapshot.reconciliation_attribution_loss,
        }

    def get_risk_snapshot_typed(self, current_prices: Dict[str, Decimal]) -> ExposureRiskSnapshot:
        with self._lock:
            for symbol, px in current_prices.items():
                self.update_unrealized_pnl_detailed(symbol=symbol, current_mid_price=px)

            total_u_pnl = ZERO
            total_r_pnl = ZERO
            total_fees = ZERO

            sleeves: Dict[str, SleeveExposureSnapshot] = {}
            positions_blob: Dict[str, Dict[str, Dict[str, Any]]] = {}
            reservations_blob: Dict[str, Dict[str, Any]] = {}

            for sleeve, assets in self._inventory.items():
                sleeve_u = sum((p.unrealized_pnl for p in assets.values()), start=ZERO)
                sleeve_r = sum((p.realized_pnl for p in assets.values()), start=ZERO)
                sleeve_f = sum((p.fees_paid for p in assets.values()), start=ZERO)

                total_u_pnl += sleeve_u
                total_r_pnl += sleeve_r
                total_fees += sleeve_f

                sleeve_reserved = self._sleeve_reserved_notional[sleeve]
                sleeve_reserved_hedge = self._sleeve_reserved_hedge_notional[sleeve]
                sleeve_effective = self._sleeve_usage_mark[sleeve] + sleeve_reserved
                sleeve_raw_net = sum((p.signed_mark_exposure for p in assets.values()), start=ZERO)
                sleeve_residual = sleeve_raw_net
                if sleeve == SleeveType.HEDGING_FLOW:
                    sleeve_residual = ZERO

                sleeves[sleeve.value] = SleeveExposureSnapshot(
                    sleeve=sleeve,
                    filled_book_notional=self._sleeve_usage_book[sleeve],
                    filled_mark_notional=self._sleeve_usage_mark[sleeve],
                    reserved_notional_weighted=sleeve_reserved,
                    reserved_hedge_notional_weighted=sleeve_reserved_hedge,
                    effective_notional=sleeve_effective,
                    raw_net_exposure=sleeve_raw_net,
                    residual_net_exposure=sleeve_residual,
                    realized_pnl=sleeve_r,
                    unrealized_pnl=sleeve_u,
                    utilization=_safe_div(sleeve_effective, self._total_equity),
                    symbols=len(assets),
                    reservations=sum(1 for r in self._reservations.values() if r.sleeve == sleeve and r.open_qty > ZERO),
                )

                positions_blob[sleeve.value] = {
                    symbol: {
                        "qty": p.qty,
                        "wap": p.wap,
                        "mark_price": p.mark_price,
                        "mark_ts_ns": p.mark_ts_ns,
                        "notional_book": p.notional_book,
                        "notional_mark": p.notional_mark,
                        "signed_mark_exposure": p.signed_mark_exposure,
                        "realized_pnl": p.realized_pnl,
                        "unrealized_pnl": p.unrealized_pnl,
                        "fees_paid": p.fees_paid,
                        "position_side": p.position_side.value,
                        "last_update_ns": p.last_update_ns,
                    }
                    for symbol, p in assets.items()
                }

            for rid, reservation in self._reservations.items():
                reservations_blob[rid] = {
                    "reservation_id": reservation.reservation_id,
                    "sleeve": reservation.sleeve.value,
                    "symbol": reservation.symbol,
                    "side": reservation.side.value,
                    "qty": reservation.qty,
                    "filled_qty": reservation.filled_qty,
                    "cancelled_qty": reservation.cancelled_qty,
                    "open_qty": reservation.open_qty,
                    "price": reservation.price,
                    "open_notional": reservation.open_notional,
                    "weighted_open_notional": reservation.weighted_open_notional,
                    "reduce_only": reservation.reduce_only,
                    "is_hedge": reservation.is_hedge,
                    "trade_intent": reservation.trade_intent.value,
                    "status": reservation.status.value,
                    "confidence_weight": reservation.confidence_weight,
                    "created_at_ns": reservation.created_at_ns,
                    "last_update_ns": reservation.last_update_ns,
                    "client_order_id": reservation.client_order_id,
                    "dedupe_key": reservation.dedupe_key,
                }

            hazard_level, hazard_action, severity = self._calculate_current_hazard(total_u_pnl)

            global_snapshot = GlobalExposureSnapshot(
                timestamp_ns=_now_ns(),
                equity=self._total_equity,
                gross_book_notional=self._gross_book_notional,
                gross_mark_notional=self._gross_mark_notional,
                gross_long_mark_notional=self._gross_long_mark_notional,
                gross_short_mark_notional=self._gross_short_mark_notional,
                net_mark_exposure=self._net_mark_exposure,
                hedge_mark_exposure=self._hedge_mark_exposure,
                raw_net_exposure=self._raw_net_exposure,
                residual_net_exposure=self._residual_net_exposure,
                reserved_notional_weighted=self._reserved_notional_weighted,
                reserved_hedge_notional_weighted=self._reserved_hedge_notional_weighted,
                effective_gross_notional=self._effective_gross_notional,
                total_unrealized_pnl=total_u_pnl,
                total_realized_pnl=total_r_pnl,
                total_fees_paid=total_fees,
                utilization_pct=_safe_div(self._effective_gross_notional, self._total_equity),
                hazard_level=hazard_level,
                hazard_action=hazard_action,
                severity=severity,
            )

            quality = self._derive_snapshot_quality()

            return ExposureRiskSnapshot(
                version=self._version,
                timestamp_ns=global_snapshot.timestamp_ns,
                global_snapshot=global_snapshot,
                sleeves=sleeves,
                positions=positions_blob,
                reservations=reservations_blob,
                quality=quality,
                reconciliation_attribution_loss=self._reconciliation_attribution_loss,
            )

    def exposure_surface(self) -> ExposureSurface:
        with self._lock:
            total_u = ZERO
            total_r = ZERO
            total_f = ZERO
            for sleeve_positions in self._inventory.values():
                for pos in sleeve_positions.values():
                    total_u += pos.unrealized_pnl
                    total_r += pos.realized_pnl
                    total_f += pos.fees_paid

            return ExposureSurface(
                gross_book_notional=self._gross_book_notional,
                gross_mark_notional=self._gross_mark_notional,
                gross_long_mark_notional=self._gross_long_mark_notional,
                gross_short_mark_notional=self._gross_short_mark_notional,
                net_mark_exposure=self._net_mark_exposure,
                hedge_mark_exposure=self._hedge_mark_exposure,
                raw_net_exposure=self._raw_net_exposure,
                residual_net_exposure=self._residual_net_exposure,
                reserved_notional_weighted=self._reserved_notional_weighted,
                reserved_hedge_notional_weighted=self._reserved_hedge_notional_weighted,
                effective_gross_notional=self._effective_gross_notional,
                total_unrealized_pnl=total_u,
                total_realized_pnl=total_r,
                total_fees_paid=total_f,
            )

    def mutation_journal(self, *, limit: Optional[int] = None) -> List[MutationRecord]:
        with self._lock:
            if limit is None or limit >= len(self._mutation_journal):
                return list(self._mutation_journal)
            return self._mutation_journal[-limit:]

    def validate_invariants(self) -> ExposureInvariantReport:
        with self._lock:
            violations: List[str] = []
            warnings: List[str] = []

            # Reservation invariants
            for rid, r in self._reservations.items():
                if r.filled_qty > r.qty:
                    violations.append(f"reservation_filled_gt_qty:{rid}")
                if r.cancelled_qty > r.qty:
                    violations.append(f"reservation_cancelled_gt_qty:{rid}")
                if r.open_qty < ZERO:
                    violations.append(f"reservation_negative_open_qty:{rid}")

            # Position invariants
            for sleeve, positions in self._inventory.items():
                for symbol, p in positions.items():
                    if p.qty == ZERO and p.wap != ZERO:
                        warnings.append(f"flat_position_nonzero_wap:{sleeve.value}:{symbol}")
                    if p.fees_paid < ZERO:
                        violations.append(f"negative_fees:{sleeve.value}:{symbol}")

            # Aggregate invariants
            before = (
                self._gross_book_notional,
                self._gross_mark_notional,
                self._reserved_notional_weighted,
                self._effective_gross_notional,
            )
            self.recompute_aggregates()
            after = (
                self._gross_book_notional,
                self._gross_mark_notional,
                self._reserved_notional_weighted,
                self._effective_gross_notional,
            )

            if before != after:
                warnings.append("aggregate_cache_changed_on_recompute")

            return ExposureInvariantReport(
                valid=len(violations) == 0,
                version=self._version,
                violations=tuple(violations),
                warnings=tuple(warnings),
            )

    def _calculate_current_hazard(
        self,
        u_pnl: Decimal,
    ) -> Tuple[RiskLevel, RiskAction, InvariantViolationSeverity]:
        utilization = _safe_div(self._effective_gross_notional, self._total_equity)

        if utilization > self.policy.max_utilization:
            return RiskLevel.VETO, RiskAction.BLOCK_ALL_NEW, InvariantViolationSeverity.HARD_FLAT

        if u_pnl < -(self._total_equity * self.policy.max_drawdown_unrealized):
            return RiskLevel.CRITICAL, RiskAction.SAFE_MODE, InvariantViolationSeverity.SAFE_MODE

        return RiskLevel.NONE, RiskAction.ALLOW, InvariantViolationSeverity.ADVISORY

    # ------------------------------------------------------------------
    # Recovery / reconciliation
    # ------------------------------------------------------------------

    def force_inventory_sync(
        self,
        symbol: str,
        exchange_qty: Decimal,
        exchange_price: Decimal,
    ) -> None:
        self.force_inventory_sync_detailed(
            symbol=symbol,
            exchange_qty=exchange_qty,
            exchange_price=exchange_price,
        )

    def force_inventory_sync_detailed(
        self,
        symbol: str,
        exchange_qty: Decimal,
        exchange_price: Decimal,
    ) -> ReconciliationResult:
        with self._lock:
            exchange_qty = _d(exchange_qty, field_name="exchange_qty")
            exchange_price = _ensure_positive(_d(exchange_price, field_name="exchange_price"), "exchange_price")

            logger.critical("[EXPOSURE_RECON] FORCING SYNC symbol=%s exchange_qty=%s", symbol, exchange_qty)

            previous_total_qty = ZERO
            affected: List[SleeveType] = []

            reservation_ids = [rid for rid, r in self._reservations.items() if r.symbol == symbol]
            for rid in reservation_ids:
                self._remove_reservation(rid, silent=True)

            attribution_lost = False

            for sleeve in SleeveType:
                if symbol in self._inventory[sleeve]:
                    pos = self._inventory[sleeve][symbol]
                    previous_total_qty += pos.qty
                    affected.append(sleeve)

                    self._inventory[sleeve][symbol] = replace(
                        pos,
                        qty=ZERO,
                        wap=ZERO,
                        mark_price=exchange_price,
                        mark_ts_ns=_now_ns(),
                        unrealized_pnl=ZERO,
                        last_update_ns=_now_ns(),
                    )

            if exchange_qty != ZERO:
                agg = SleeveType.POVERTY_KILLER_AGGREGATE
                rebuilt = PositionState(
                    symbol=symbol,
                    sleeve=agg,
                    qty=exchange_qty,
                    wap=exchange_price,
                    mark_price=exchange_price,
                    mark_ts_ns=_now_ns(),
                    last_update_ns=_now_ns(),
                )
                self._inventory[agg][symbol] = rebuilt
                if agg not in affected:
                    affected.append(agg)
                attribution_lost = True

            self._reconciliation_attribution_loss = self._reconciliation_attribution_loss or attribution_lost

            self._bump_version()
            self.recompute_aggregates()
            self._append_mutation(
                mutation_type=MutationType.RECONCILED,
                symbol=symbol,
                sleeve=None,
                payload={
                    "exchange_qty": str(exchange_qty),
                    "exchange_price": str(exchange_price),
                    "attribution_lost": attribution_lost,
                },
            )

            return ReconciliationResult(
                symbol=symbol,
                exchange_qty=exchange_qty,
                exchange_price=exchange_price,
                affected_sleeves=tuple(affected),
                previous_total_qty=previous_total_qty,
                new_total_qty=exchange_qty,
                reconciled=True,
                attribution_lost=attribution_lost,
                rationale=("forced_symbol_reconciliation_complete",),
            )

    # ------------------------------------------------------------------
    # Utilities / views
    # ------------------------------------------------------------------

    def current_utilization(self) -> Decimal:
        with self._lock:
            return _safe_div(self._effective_gross_notional, self._total_equity)

    def sleeve_utilization(self, sleeve: SleeveType) -> Decimal:
        with self._lock:
            effective = self._sleeve_usage_mark[sleeve] + self._sleeve_reserved_notional[sleeve]
            return _safe_div(effective, self._total_equity)

    def asset_concentration(self, symbol: str) -> Decimal:
        with self._lock:
            effective = self._asset_total_mark_notional(symbol) + self._asset_reserved_notional(symbol)
            return _safe_div(effective, self._total_equity)

    def position_for(self, sleeve: SleeveType, symbol: str) -> Optional[PositionState]:
        with self._lock:
            return self._inventory[sleeve].get(symbol)

    def reservations_for(self, sleeve: Optional[SleeveType] = None, symbol: Optional[str] = None) -> List[PendingReservation]:
        with self._lock:
            out = []
            for reservation in self._reservations.values():
                if sleeve is not None and reservation.sleeve != sleeve:
                    continue
                if symbol is not None and reservation.symbol != symbol:
                    continue
                if reservation.open_qty > ZERO:
                    out.append(reservation)
            return out

    def export_reservation_ledger_rows(self, *, active_only: bool = True) -> List[Dict[str, Any]]:
        """
        Export in-memory reservations into the passive StateStore ledger shape.

        This helper does not persist, reserve, release, or authorize exposure.
        Missing fields that are not carried by PendingReservation are emitted as
        None so future wiring cannot mistake them for source-proven facts.
        """
        with self._lock:
            rows: List[Dict[str, Any]] = []
            for reservation in self._reservations.values():
                is_terminal = self._is_terminal_reservation(reservation)
                is_active = not is_terminal and reservation.open_qty > ZERO
                if active_only and not is_active:
                    continue
                rows.append(self._reservation_to_ledger_row(reservation, is_active=is_active, is_terminal=is_terminal))
            return rows

    def hydrate_reservations_from_ledger(
        self,
        rows: Iterable[Dict[str, Any]],
        *,
        release_tombstones: Optional[Iterable[Dict[str, Any]]] = None,
        fill_progress: Optional[Iterable[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Restore active PendingReservation state from passive ledger rows.

        The helper is intentionally local to ExposureManager. It does not call
        reserve_intent, release_reservation, apply_fill_to_reservation, StateStore,
        execution, router, or broker paths.
        """
        released_ids, released_dedupe_keys = self._released_reservation_keys(release_tombstones)
        fill_progress_by_reservation = self._fill_progress_by_reservation(fill_progress)
        hydrated: List[str] = []
        skipped: List[Dict[str, str]] = []

        with self._lock:
            for row in rows:
                reservation_id = str(row.get("reservation_id") or "")
                dedupe_key = str(row.get("reservation_dedupe_key") or row.get("client_order_id") or "")

                if not reservation_id:
                    skipped.append({"reservation_id": "", "reason": "missing_reservation_id"})
                    continue
                if row.get("is_terminal") is True or row.get("terminal_status"):
                    skipped.append({"reservation_id": reservation_id, "reason": "terminal_ledger_row"})
                    continue
                if row.get("is_active") is False:
                    skipped.append({"reservation_id": reservation_id, "reason": "inactive_ledger_row"})
                    continue
                if reservation_id in released_ids or (dedupe_key and dedupe_key in released_dedupe_keys):
                    skipped.append({"reservation_id": reservation_id, "reason": "release_tombstone_present"})
                    continue

                try:
                    status = _enum_from_ledger(ReservationStatus, row.get("status"), field_name="status")
                except ValueError:
                    skipped.append({"reservation_id": reservation_id, "reason": "invalid_status"})
                    continue
                if status in self._terminal_reservation_statuses():
                    skipped.append({"reservation_id": reservation_id, "reason": "terminal_status"})
                    continue

                price_basis = row.get("price_basis")
                if price_basis is None:
                    skipped.append({"reservation_id": reservation_id, "reason": "missing_price_basis"})
                    continue

                try:
                    price = _ensure_positive(_d(price_basis, field_name="price_basis"), "price_basis")
                    qty = _ensure_positive(_d(row.get("original_qty"), field_name="original_qty"), "original_qty")
                    filled_qty = _ensure_non_negative(_d(row.get("filled_qty", ZERO), field_name="filled_qty"), "filled_qty")
                    cancelled_qty = _ensure_non_negative(_d(row.get("cancelled_qty", ZERO), field_name="cancelled_qty"), "cancelled_qty")
                    sleeve = _enum_from_ledger(SleeveType, row.get("sleeve"), field_name="sleeve")
                    side = _enum_from_ledger(OrderSide, row.get("side"), field_name="side")
                except ValueError as exc:
                    skipped.append({"reservation_id": reservation_id, "reason": str(exc)})
                    continue

                try:
                    recovered_filled_qty = self._recovered_filled_qty(
                        reservation_id=reservation_id,
                        original_qty=qty,
                        ledger_filled_qty=filled_qty,
                        progress_rows=fill_progress_by_reservation.get(reservation_id, ()),
                    )
                except ValueError as exc:
                    skipped.append({"reservation_id": reservation_id, "reason": str(exc)})
                    continue
                filled_qty = recovered_filled_qty
                if filled_qty > ZERO and status in {
                    ReservationStatus.CREATED,
                    ReservationStatus.ROUTING,
                    ReservationStatus.ACKNOWLEDGED,
                    ReservationStatus.STALE,
                    ReservationStatus.UNKNOWN,
                }:
                    status = ReservationStatus.PARTIALLY_FILLED

                if filled_qty + cancelled_qty >= qty:
                    skipped.append({"reservation_id": reservation_id, "reason": "no_open_quantity"})
                    continue

                existing_for_dedupe = self._reservation_dedupe.get(dedupe_key) if dedupe_key else None
                if existing_for_dedupe is not None and existing_for_dedupe != reservation_id:
                    skipped.append({"reservation_id": reservation_id, "reason": "duplicate_dedupe_conflict"})
                    continue

                existing = self._reservations.get(reservation_id)
                if existing is not None and existing.dedupe_key and dedupe_key and existing.dedupe_key != dedupe_key:
                    skipped.append({"reservation_id": reservation_id, "reason": "reservation_id_dedupe_conflict"})
                    continue

                confidence_weight = row.get("confidence_weight")
                if confidence_weight is None:
                    confidence = self._default_confidence_weight(status)
                else:
                    try:
                        confidence = _ensure_non_negative(_d(confidence_weight, field_name="confidence_weight"), "confidence_weight")
                    except ValueError as exc:
                        skipped.append({"reservation_id": reservation_id, "reason": str(exc)})
                        continue

                created_at_ns = int(row.get("created_at_ns") or _now_ns())
                updated_at_ns = int(row.get("updated_at_ns") or created_at_ns)

                reservation = PendingReservation(
                    reservation_id=reservation_id,
                    sleeve=sleeve,
                    symbol=str(row.get("symbol") or ""),
                    side=side,
                    qty=qty,
                    price=price,
                    trade_intent=TradeIntent.UNKNOWN,
                    reduce_only=False,
                    is_hedge=False,
                    status=status,
                    confidence_weight=confidence,
                    replay_mode=ReplayMode.RECOVERY,
                    created_at_ns=created_at_ns,
                    last_update_ns=updated_at_ns,
                    filled_qty=filled_qty,
                    cancelled_qty=cancelled_qty,
                    client_order_id=row.get("client_order_id"),
                    dedupe_key=dedupe_key or None,
                    source=EventSource.HYDRATION,
                )

                self._reservations[reservation_id] = reservation
                if dedupe_key:
                    self._reservation_dedupe[dedupe_key] = reservation_id
                hydrated.append(reservation_id)

            if hydrated:
                self._bump_version()
            self.recompute_aggregates()
            invariant_report = self.validate_invariants()

        return {
            "hydrated": tuple(hydrated),
            "skipped": tuple(skipped),
            "valid": invariant_report.valid,
            "violations": invariant_report.violations,
            "warnings": invariant_report.warnings,
        }

    @staticmethod
    def _fill_progress_by_reservation(
        fill_progress: Optional[Iterable[Dict[str, Any]]],
    ) -> Dict[str, List[Dict[str, Any]]]:
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        if fill_progress is None:
            return grouped
        for progress in fill_progress:
            reservation_id = str(progress.get("reservation_id") or "")
            if not reservation_id:
                continue
            grouped.setdefault(reservation_id, []).append(progress)
        return grouped

    @staticmethod
    def _recovered_filled_qty(
        *,
        reservation_id: str,
        original_qty: Decimal,
        ledger_filled_qty: Decimal,
        progress_rows: Iterable[Dict[str, Any]],
    ) -> Decimal:
        max_progress: Optional[Decimal] = None
        for progress in progress_rows:
            try:
                cumulative = _ensure_non_negative(
                    _d(progress.get("cumulative_filled_qty"), field_name="cumulative_filled_qty"),
                    "cumulative_filled_qty",
                )
            except ValueError as exc:
                raise ValueError(f"invalid_fill_progress:{exc}") from exc
            if cumulative > original_qty:
                raise ValueError("fill_progress_exceeds_original_qty")
            if max_progress is None or cumulative > max_progress:
                max_progress = cumulative
        if max_progress is None or max_progress <= ledger_filled_qty:
            return ledger_filled_qty
        logger.info(
            "Recovered reservation fill progress during hydrate: %s ledger=%s recovered=%s",
            reservation_id,
            ledger_filled_qty,
            max_progress,
        )
        return max_progress

    def iter_positions(self) -> Iterable[PositionState]:
        with self._lock:
            for sleeve_positions in self._inventory.values():
                for pos in sleeve_positions.values():
                    yield pos

    def recompute_aggregates(self) -> None:
        with self._lock:
            gross_book = ZERO
            gross_mark = ZERO
            gross_long = ZERO
            gross_short = ZERO
            net_mark = ZERO

            hedge_mark = ZERO
            raw_net = ZERO

            reserved_weighted = ZERO
            reserved_hedge_weighted = ZERO

            sleeve_book = {s: ZERO for s in SleeveType}
            sleeve_mark = {s: ZERO for s in SleeveType}
            sleeve_reserved = {s: ZERO for s in SleeveType}
            sleeve_reserved_hedge = {s: ZERO for s in SleeveType}

            for sleeve, positions in self._inventory.items():
                for pos in positions.values():
                    gross_book += pos.notional_book
                    gross_mark += pos.notional_mark
                    sleeve_book[sleeve] += pos.notional_book
                    sleeve_mark[sleeve] += pos.notional_mark

                    signed = pos.signed_mark_exposure
                    net_mark += signed
                    raw_net += signed

                    if sleeve == SleeveType.HEDGING_FLOW:
                        hedge_mark += signed

                    if pos.qty > ZERO:
                        gross_long += pos.notional_mark
                    elif pos.qty < ZERO:
                        gross_short += pos.notional_mark

            for reservation in self._reservations.values():
                if reservation.open_qty <= ZERO:
                    continue

                current = self._inventory[reservation.sleeve].get(reservation.symbol)
                current_qty = current.qty if current is not None else ZERO
                pending_ex_self = self._pending_signed_qty_for(
                    sleeve=reservation.sleeve,
                    symbol=reservation.symbol,
                    exclude_reservation_id=reservation.reservation_id,
                )
                effective_qty = current_qty + pending_ex_self

                reduces, increases, expands = self._classify_directional_effect(
                    current_effective_qty=effective_qty,
                    proposed_signed_qty=reservation.signed_open_qty,
                    reduce_only=reservation.reduce_only,
                    trade_intent=reservation.trade_intent,
                )

                weighted = reservation.weighted_open_notional

                if reservation.is_hedge:
                    reserved_hedge_weighted += weighted
                    sleeve_reserved_hedge[reservation.sleeve] += weighted

                if increases or expands:
                    reserved_weighted += weighted
                    sleeve_reserved[reservation.sleeve] += weighted

            self._gross_book_notional = gross_book
            self._gross_mark_notional = gross_mark
            self._gross_long_mark_notional = gross_long
            self._gross_short_mark_notional = gross_short
            self._net_mark_exposure = net_mark

            self._hedge_mark_exposure = hedge_mark
            self._raw_net_exposure = raw_net
            self._residual_net_exposure = raw_net - hedge_mark

            self._reserved_notional_weighted = reserved_weighted
            self._reserved_hedge_notional_weighted = reserved_hedge_weighted
            self._effective_gross_notional = gross_mark + reserved_weighted

            self._sleeve_usage_book = sleeve_book
            self._sleeve_usage_mark = sleeve_mark
            self._sleeve_reserved_notional = sleeve_reserved
            self._sleeve_reserved_hedge_notional = sleeve_reserved_hedge

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _guard_result(*, reservation_id: str, client_order_id: Optional[str]) -> Dict[str, Any]:
        return {
            "applied": False,
            "idempotent": False,
            "failed_reason": None,
            "persistence_applied": False,
            "mutation_applied": False,
            "rollback_applied": False,
            "reservation_id": reservation_id,
            "client_order_id": client_order_id,
        }

    @staticmethod
    def _guard_failed(result: Dict[str, Any], reason: str) -> Dict[str, Any]:
        result["failed_reason"] = reason
        return result

    @staticmethod
    def _guard_idempotent(result: Dict[str, Any], reason: str) -> Dict[str, Any]:
        result["idempotent"] = True
        result["failed_reason"] = reason
        return result

    @staticmethod
    def _active_ledger_row_for_dedupe(state_store: Any, dedupe_key: str) -> Optional[Dict[str, Any]]:
        for row in state_store.list_reservation_ledger(active_only=True, include_terminal=False):
            if row.get("reservation_dedupe_key") == dedupe_key:
                return row
        return None

    @staticmethod
    def _max_recorded_cumulative_fill(progress_rows: Iterable[Dict[str, Any]]) -> Optional[Decimal]:
        max_seen: Optional[Decimal] = None
        for row in progress_rows:
            try:
                seen = _d(row.get("cumulative_filled_qty"), field_name="cumulative_filled_qty")
            except ValueError:
                continue
            if max_seen is None or seen > max_seen:
                max_seen = seen
        return max_seen

    def _rollback_open_reservation(self, reservation_id: str, dedupe_key: Optional[str]) -> bool:
        with self._lock:
            if reservation_id not in self._reservations:
                return False
            reservation = self._reservations[reservation_id]
            if dedupe_key and reservation.dedupe_key != dedupe_key:
                return False
            self._remove_reservation(reservation_id, silent=True)
            return True

    def _terminal_or_active_row_after_fill(
        self,
        previous: PendingReservation,
        updated: Optional[PendingReservation],
        cumulative_filled_qty: Decimal,
    ) -> Dict[str, Any]:
        if updated is not None:
            return self._reservation_to_ledger_row(updated, is_active=True, is_terminal=False)
        terminal = replace(
            previous,
            status=ReservationStatus.FILLED,
            confidence_weight=self._default_confidence_weight(ReservationStatus.FILLED),
            filled_qty=min(previous.qty, cumulative_filled_qty),
            cancelled_qty=ZERO,
            last_update_ns=_now_ns(),
        )
        return self._reservation_to_ledger_row(terminal, is_active=False, is_terminal=True)

    @staticmethod
    def _reservation_status_from_terminal_proof(terminal_status: str) -> Optional[ReservationStatus]:
        normalized = str(terminal_status or "").strip().lower()
        mapping = {
            "filled": ReservationStatus.FILLED,
            "closed": ReservationStatus.FILLED,
            "canceled": ReservationStatus.CANCELLED,
            "cancelled": ReservationStatus.CANCELLED,
            "rejected": ReservationStatus.REJECTED,
            "expired": ReservationStatus.EXPIRED,
        }
        return mapping.get(normalized)

    def _terminal_ledger_row_for_release(
        self,
        reservation: PendingReservation,
        *,
        terminal_status: ReservationStatus,
        terminal_reason: str,
        terminal_source: str,
        source_idempotency_key: str,
    ) -> Dict[str, Any]:
        if terminal_status == ReservationStatus.FILLED:
            final_reservation = replace(
                reservation,
                status=terminal_status,
                confidence_weight=self._default_confidence_weight(terminal_status),
                filled_qty=reservation.qty,
                cancelled_qty=ZERO,
                last_update_ns=_now_ns(),
            )
        else:
            final_reservation = replace(
                reservation,
                status=terminal_status,
                confidence_weight=self._default_confidence_weight(terminal_status),
                cancelled_qty=reservation.qty - reservation.filled_qty,
                last_update_ns=_now_ns(),
            )
        row = self._reservation_to_ledger_row(final_reservation, is_active=False, is_terminal=True)
        row.update({
            "terminal_reason": terminal_reason,
            "terminal_source": terminal_source,
            "source_lifecycle_phase": "guarded_release_reservation",
            "source_idempotency_key": source_idempotency_key,
        })
        return row

    def _reservation_to_ledger_row(
        self,
        reservation: PendingReservation,
        *,
        is_active: bool,
        is_terminal: bool,
    ) -> Dict[str, Any]:
        dedupe_key = reservation.dedupe_key or reservation.client_order_id or reservation.reservation_id
        terminal_status = reservation.status.value if is_terminal else None
        return {
            "reservation_id": reservation.reservation_id,
            "client_order_id": reservation.client_order_id,
            "decision_uuid": self._decision_uuid_from_dedupe_key(dedupe_key, reservation.client_order_id),
            "reservation_dedupe_key": dedupe_key,
            "symbol": reservation.symbol,
            "side": reservation.side.value,
            "sleeve": reservation.sleeve.value,
            "order_type": None,
            "original_qty": str(reservation.qty),
            "open_qty": str(reservation.open_qty),
            "filled_qty": str(reservation.filled_qty),
            "cancelled_qty": str(reservation.cancelled_qty),
            "price_basis": str(reservation.price),
            "notional_basis": str(reservation.qty * reservation.price),
            "status": reservation.status.value,
            "confidence_weight": str(reservation.confidence_weight),
            "created_at_ns": reservation.created_at_ns,
            "updated_at_ns": reservation.last_update_ns,
            "terminal_status": terminal_status,
            "terminal_reason": terminal_status,
            "terminal_source": "exposure_manager_export" if is_terminal else None,
            "source_lifecycle_phase": "exposure_manager_export",
            "source_idempotency_key": dedupe_key,
            "is_active": is_active,
            "is_terminal": is_terminal,
        }

    @staticmethod
    def _decision_uuid_from_dedupe_key(dedupe_key: Optional[str], client_order_id: Optional[str]) -> Optional[str]:
        if not dedupe_key or not client_order_id:
            return None
        suffix = f":{client_order_id}"
        if dedupe_key.endswith(suffix):
            decision_uuid = dedupe_key[: -len(suffix)]
            return decision_uuid or None
        return None

    @staticmethod
    def _terminal_reservation_statuses() -> set[ReservationStatus]:
        return {
            ReservationStatus.CANCELLED,
            ReservationStatus.FILLED,
            ReservationStatus.REJECTED,
            ReservationStatus.EXPIRED,
        }

    def _is_terminal_reservation(self, reservation: PendingReservation) -> bool:
        return reservation.status in self._terminal_reservation_statuses() or reservation.open_qty <= ZERO

    @staticmethod
    def _released_reservation_keys(
        release_tombstones: Optional[Iterable[Dict[str, Any]]],
    ) -> Tuple[set[str], set[str]]:
        released_ids: set[str] = set()
        released_dedupe_keys: set[str] = set()
        if release_tombstones is None:
            return released_ids, released_dedupe_keys
        for tombstone in release_tombstones:
            if tombstone.get("release_applied", True) is False:
                continue
            reservation_id = tombstone.get("reservation_id")
            dedupe_key = tombstone.get("reservation_dedupe_key")
            if reservation_id:
                released_ids.add(str(reservation_id))
            if dedupe_key:
                released_dedupe_keys.add(str(dedupe_key))
        return released_ids, released_dedupe_keys

    def _default_confidence_weight(self, status: ReservationStatus) -> Decimal:
        mapping = {
            ReservationStatus.CREATED: Decimal("0.40"),
            ReservationStatus.ROUTING: Decimal("0.60"),
            ReservationStatus.ACKNOWLEDGED: Decimal("1.00"),
            ReservationStatus.PARTIALLY_FILLED: Decimal("1.00"),
            ReservationStatus.STALE: Decimal("0.50"),
            ReservationStatus.CANCELLED: ZERO,
            ReservationStatus.FILLED: ZERO,
            ReservationStatus.REJECTED: ZERO,
            ReservationStatus.EXPIRED: ZERO,
            ReservationStatus.UNKNOWN: Decimal("0.30"),
        }
        return mapping[status]

    def _reject_validation(
        self,
        *,
        reason: str,
        risk_level: RiskLevel,
        risk_action: RiskAction,
        severity: InvariantViolationSeverity,
        authority_tier: AuthorityTier,
        priority: PriorityClass,
        veto_reason: Optional[RiskVetoReason],
        rationale: tuple[str, ...],
        projected_order_notional: Decimal = ZERO,
        current_global_utilization: Decimal = ZERO,
        projected_global_utilization: Decimal = ZERO,
        current_sleeve_utilization: Decimal = ZERO,
        projected_sleeve_utilization: Decimal = ZERO,
        current_asset_concentration: Decimal = ZERO,
        projected_asset_concentration: Decimal = ZERO,
        current_position_qty: Decimal = ZERO,
        projected_position_qty: Decimal = ZERO,
        reduces_exposure: bool = False,
        increases_exposure: bool = False,
        expands_gross: bool = False,
    ) -> ExposureIntentValidation:
        return ExposureIntentValidation(
            authorized=False,
            reason=reason,
            risk_level=risk_level,
            risk_action=risk_action,
            severity=severity,
            authority_tier=authority_tier,
            priority=priority,
            veto_reason=veto_reason,
            projected_order_notional=projected_order_notional,
            current_global_utilization=current_global_utilization,
            projected_global_utilization=projected_global_utilization,
            current_sleeve_utilization=current_sleeve_utilization,
            projected_sleeve_utilization=projected_sleeve_utilization,
            current_asset_concentration=current_asset_concentration,
            projected_asset_concentration=projected_asset_concentration,
            current_position_qty=current_position_qty,
            projected_position_qty=projected_position_qty,
            reduces_exposure=reduces_exposure,
            increases_exposure=increases_exposure,
            expands_gross=expands_gross,
            reservation_aware=True,
            hedge_aware=True,
            rationale=rationale,
        )

    def _classify_directional_effect(
        self,
        *,
        current_effective_qty: Decimal,
        proposed_signed_qty: Decimal,
        reduce_only: bool,
        trade_intent: TradeIntent,
    ) -> tuple[bool, bool, bool]:
        projected = current_effective_qty + proposed_signed_qty

        current_abs = _abs(current_effective_qty)
        projected_abs = _abs(projected)

        reduces = projected_abs < current_abs
        increases = projected_abs > current_abs
        expands = increases

        if current_effective_qty == ZERO:
            reduces = False
            increases = True
            expands = True
        elif current_effective_qty > ZERO and proposed_signed_qty < ZERO and projected >= ZERO:
            reduces = True
            increases = False
            expands = False
        elif current_effective_qty < ZERO and proposed_signed_qty > ZERO and projected <= ZERO:
            reduces = True
            increases = False
            expands = False
        elif current_effective_qty > ZERO and proposed_signed_qty > ZERO:
            reduces = False
            increases = True
            expands = True
        elif current_effective_qty < ZERO and proposed_signed_qty < ZERO:
            reduces = False
            increases = True
            expands = True
        elif projected == ZERO:
            reduces = True
            increases = False
            expands = False
        else:
            if current_effective_qty > ZERO > projected:
                reduces = False
                increases = True
                expands = True
            elif current_effective_qty < ZERO < projected:
                reduces = False
                increases = True
                expands = True

        if reduce_only or trade_intent in {TradeIntent.CLOSE, TradeIntent.REDUCE, TradeIntent.FLATTEN}:
            expands = False if reduces else expands

        return reduces, increases, expands

    def _asset_total_mark_notional(self, symbol: str) -> Decimal:
        total = ZERO
        for sleeve_positions in self._inventory.values():
            pos = sleeve_positions.get(symbol)
            if pos is not None:
                total += pos.notional_mark
        return total

    def _asset_reserved_notional(self, symbol: str) -> Decimal:
        total = ZERO
        for reservation in self._reservations.values():
            if reservation.symbol != symbol or reservation.open_qty <= ZERO:
                continue

            current = self._inventory[reservation.sleeve].get(symbol)
            current_qty = current.qty if current is not None else ZERO
            pending_ex_self = self._pending_signed_qty_for(
                sleeve=reservation.sleeve,
                symbol=symbol,
                exclude_reservation_id=reservation.reservation_id,
            )
            effective_qty = current_qty + pending_ex_self

            reduces, increases, expands = self._classify_directional_effect(
                current_effective_qty=effective_qty,
                proposed_signed_qty=reservation.signed_open_qty,
                reduce_only=reservation.reduce_only,
                trade_intent=reservation.trade_intent,
            )
            if increases or expands:
                total += reservation.weighted_open_notional
        return total

    def _pending_signed_qty_for(
        self,
        *,
        sleeve: SleeveType,
        symbol: str,
        exclude_reservation_id: Optional[str] = None,
    ) -> Decimal:
        total = ZERO
        for rid, reservation in self._reservations.items():
            if exclude_reservation_id is not None and rid == exclude_reservation_id:
                continue
            if reservation.sleeve == sleeve and reservation.symbol == symbol and reservation.open_qty > ZERO:
                total += reservation.signed_open_qty * reservation.confidence_weight
        return total

    def _remove_reservation(
        self,
        reservation_id: str,
        *,
        terminal_status: Optional[ReservationStatus] = None,
        silent: bool = False,
    ) -> None:
        reservation = self._reservations.get(reservation_id)
        if reservation is None:
            return

        final_reservation = reservation if terminal_status is None else replace(
            reservation,
            status=terminal_status,
            confidence_weight=self._default_confidence_weight(terminal_status),
            last_update_ns=_now_ns(),
        )

        dedupe_key = final_reservation.dedupe_key
        del self._reservations[reservation_id]
        if dedupe_key is not None and self._reservation_dedupe.get(dedupe_key) == reservation_id:
            del self._reservation_dedupe[dedupe_key]

        self._bump_version()
        self.recompute_aggregates()

        if not silent:
            self._append_mutation(
                mutation_type=MutationType.RESERVATION_RELEASED,
                symbol=final_reservation.symbol,
                sleeve=final_reservation.sleeve,
                payload={
                    "reservation_id": reservation_id,
                    "terminal_status": final_reservation.status.value,
                },
            )

    def _derive_snapshot_quality(self) -> ExposureSnapshotQuality:
        now_ns = _now_ns()

        if self._reconciliation_attribution_loss:
            return ExposureSnapshotQuality.RECONCILED_WITH_ATTRIBUTION_LOSS

        has_stale_marks = False
        has_partial_marks = False
        for sleeve_positions in self._inventory.values():
            for pos in sleeve_positions.values():
                if pos.qty == ZERO:
                    continue
                if pos.mark_price <= ZERO or pos.mark_ts_ns == 0:
                    has_partial_marks = True
                elif (now_ns - pos.mark_ts_ns) > self.policy.mark_stale_ns:
                    has_stale_marks = True

        if has_stale_marks:
            return ExposureSnapshotQuality.STALE_MARKS
        if has_partial_marks:
            return ExposureSnapshotQuality.PARTIAL_MARKS
        return ExposureSnapshotQuality.LIVE

    def _append_mutation(
        self,
        *,
        mutation_type: MutationType,
        symbol: Optional[str],
        sleeve: Optional[SleeveType],
        payload: Dict[str, Any],
    ) -> None:
        self._mutation_seq += 1
        record = MutationRecord(
            sequence=self._mutation_seq,
            timestamp_ns=_now_ns(),
            mutation_type=mutation_type,
            version=self._version,
            symbol=symbol,
            sleeve=None if sleeve is None else sleeve.value,
            payload=payload,
        )
        self._mutation_journal.append(record)
        if len(self._mutation_journal) > self.policy.journal_capacity:
            self._mutation_journal = self._mutation_journal[-self.policy.journal_capacity:]

    def _bump_version(self) -> None:
        self._version += 1


def exposure_authority_seam_metadata() -> Dict[str, Any]:
    """
    Return static seam metadata for governance/test visibility.

    This helper has no runtime side effects.
    """
    return {
        "authority_module": "app.risk.exposure_manager",
        "authority_class": "ExposureManager",
        "status": EXPOSURE_AUTHORITY_STATUS,
        "live_wired": True,
        "active_veto_owner": True,
        "policy_version": "P3B_B1_V1",
        "scope": "paper_runtime_only",
        "notes": (
            "Canonical PAPER portfolio-risk authority",
            "Broker mutation remains owned by execution/router and paper-scoped lifecycle",
        ),
    }


__all__ = [
    "ReservationStatus",
    "ExposureSnapshotQuality",
    "MutationType",
    "ExposurePolicyConfig",
    "PositionState",
    "PendingReservation",
    "MutationRecord",
    "ExposureSurface",
    "ExposureIntentValidation",
    "FillResult",
    "SleeveExposureSnapshot",
    "GlobalExposureSnapshot",
    "ExposureRiskSnapshot",
    "ReconciliationResult",
    "ExposureInvariantReport",
    "ExposureManager",
    "exposure_authority_seam_metadata",
]
