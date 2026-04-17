"""
app/meta/market_allocator.py
POVERTY_KILLER — SOVEREIGN CAPITAL ALLOCATOR (CITADEL-GRADE)

This module is the canonical capital allocation authority for symbol/sleeve-level
trade capacity. It converts portfolio capital, regime state, volatility,
confidence, exposure posture, and risk clamps into bounded deployable capital
decisions.

ARCHITECTURAL ROLE
------------------
Owns locally:
- deployable capital budgeting
- regime-aware symbol allocation
- reserve-aware capacity calculation
- confidence/risk/drawdown/health integrated scaling
- allocation journaling
- allocation snapshots

Does NOT own:
- execution authority
- exposure truth generation
- unified risk generation
- drawdown computation
- market regime generation

DESIGN PRINCIPLES
-----------------
1. Allocate Conservatively
   Capital is allocated from deployable capital, not naive total equity.

2. Respect Existing Sovereign Truth
   Exposure, drawdown, health, and unified risk are inputs, not re-derived here.

3. Typed, Auditable Decisions
   Allocation decisions are immutable, journaled, and serializer-ready.

4. Compatibility Without Fake Truth
   Legacy convenience methods remain, but missing canonical inputs degrade quality
   rather than pretending full certainty.

5. Risk Mitigation First
   Unknown, degraded, or contradictory conditions reduce or suppress capacity.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_DOWN, getcontext
from enum import Enum, unique
from typing import Any, Dict, List, Optional

from app.utils.enums import RegimeType, SleeveType
from app.utils.ids import generate_correlation_id, generate_request_id

getcontext().prec = 28
logger = logging.getLogger(__name__)


# ============================================================================
# HELPERS
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


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"), rounding=ROUND_DOWN)


def _now_ns() -> int:
    return time.time_ns()


# ============================================================================
# ENUMS
# ============================================================================

@unique
class AllocationQuality(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    DEGRADED = "DEGRADED"


@unique
class TimestampSource(str, Enum):
    EXPLICIT_INPUT = "EXPLICIT_INPUT"
    LOCAL_GENERATION_TIME = "LOCAL_GENERATION_TIME"


# ============================================================================
# MODELS
# ============================================================================

@dataclass(frozen=True, slots=True)
class AllocationPolicyConfig:
    base_allocation_pct: Decimal = Decimal("0.10")
    max_total_utilization: Decimal = Decimal("0.80")
    risk_free_reserve: Decimal = Decimal("0.20")
    minimum_capacity_floor: Decimal = Decimal("0.00")

    volatility_floor_multiplier: Decimal = Decimal("0.10")
    confidence_floor_multiplier: Decimal = Decimal("0.10")

    regime_multipliers: Optional[Dict[RegimeType, Decimal]] = None
    sleeve_multipliers: Optional[Dict[SleeveType, Decimal]] = None

    journal_capacity: int = 50000

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_allocation_pct", _ensure_non_negative(_d(self.base_allocation_pct, field_name="base_allocation_pct"), "base_allocation_pct"))
        object.__setattr__(self, "max_total_utilization", _ensure_non_negative(_d(self.max_total_utilization, field_name="max_total_utilization"), "max_total_utilization"))
        object.__setattr__(self, "risk_free_reserve", _ensure_non_negative(_d(self.risk_free_reserve, field_name="risk_free_reserve"), "risk_free_reserve"))
        object.__setattr__(self, "minimum_capacity_floor", _ensure_non_negative(_d(self.minimum_capacity_floor, field_name="minimum_capacity_floor"), "minimum_capacity_floor"))
        object.__setattr__(self, "volatility_floor_multiplier", _ensure_non_negative(_d(self.volatility_floor_multiplier, field_name="volatility_floor_multiplier"), "volatility_floor_multiplier"))
        object.__setattr__(self, "confidence_floor_multiplier", _ensure_non_negative(_d(self.confidence_floor_multiplier, field_name="confidence_floor_multiplier"), "confidence_floor_multiplier"))

        for name in [
            "base_allocation_pct",
            "max_total_utilization",
            "risk_free_reserve",
            "volatility_floor_multiplier",
            "confidence_floor_multiplier",
        ]:
            if getattr(self, name) > ONE:
                raise ValueError(f"{name} cannot exceed 1")

        if self.risk_free_reserve > ONE:
            raise ValueError("risk_free_reserve cannot exceed 1")
        if self.max_total_utilization > ONE:
            raise ValueError("max_total_utilization cannot exceed 1")
        if self.journal_capacity < 100:
            raise ValueError("journal_capacity must be >= 100")

        if self.regime_multipliers is None:
            object.__setattr__(self, "regime_multipliers", {
                RegimeType.UNKNOWN: Decimal("0.00"),
                RegimeType.TRENDING_LONG_STRONG: Decimal("1.20"),
                RegimeType.TRENDING_LONG_EXHAUSTING: Decimal("0.70"),
                RegimeType.TRENDING_SHORT_STRONG: Decimal("1.20"),
                RegimeType.TRENDING_SHORT_EXHAUSTING: Decimal("0.70"),
                RegimeType.RANGING_COMPRESSED: Decimal("0.60"),
                RegimeType.RANGING_EXPANDING: Decimal("0.50"),
                RegimeType.CRISIS_LIQUIDITY_VOID: Decimal("0.10"),
                RegimeType.CRISIS_VOLATILITY_SPIKE: Decimal("0.10"),
                RegimeType.CRISIS_INFRA_FAILURE: Decimal("0.00"),
                RegimeType.REGIME_BREAK_DETECTED: Decimal("0.25"),
            })

        if self.sleeve_multipliers is None:
            object.__setattr__(self, "sleeve_multipliers", {
                SleeveType.SHADOW_FRONT: Decimal("1.00"),
                SleeveType.GAMMA_FRONT: Decimal("1.00"),
                SleeveType.LIQUIDITY_VOID: Decimal("0.70"),
                SleeveType.SECTOR_ROTATION: Decimal("0.80"),
                SleeveType.ADAPTIVE_DC: Decimal("0.80"),
                SleeveType.HEDGING_FLOW: Decimal("1.20"),
                SleeveType.POVERTY_KILLER_AGGREGATE: Decimal("1.00"),
            })


@dataclass(frozen=True, slots=True)
class AllocationContext:
    timestamp_ns: int
    total_equity: Decimal
    current_utilization: Decimal = Decimal("0")
    reserved_notional: Decimal = Decimal("0")
    drawdown_multiplier: Decimal = Decimal("1.0")
    risk_multiplier: Decimal = Decimal("1.0")
    health_multiplier: Decimal = Decimal("1.0")
    signal_confidence: Decimal = Decimal("1.0")

    def __post_init__(self) -> None:
        if self.timestamp_ns <= 0:
            raise ValueError("timestamp_ns must be positive")
        object.__setattr__(self, "total_equity", _ensure_non_negative(_d(self.total_equity, field_name="total_equity"), "total_equity"))
        for field_name in [
            "current_utilization",
            "drawdown_multiplier",
            "risk_multiplier",
            "health_multiplier",
            "signal_confidence",
        ]:
            val = _ensure_non_negative(_d(getattr(self, field_name), field_name=field_name), field_name)
            if val > ONE:
                raise ValueError(f"{field_name} cannot exceed 1")
            object.__setattr__(self, field_name, val)

        object.__setattr__(self, "reserved_notional", _ensure_non_negative(_d(self.reserved_notional, field_name="reserved_notional"), "reserved_notional"))


@dataclass(frozen=True, slots=True)
class AllocationDecision:
    allocation_id: int
    correlation_id: int
    timestamp_ns: int
    timestamp_source: TimestampSource

    symbol: str
    sleeve: SleeveType
    regime: RegimeType

    total_equity: Decimal
    reserve_buffer: Decimal
    deployable_capital: Decimal
    remaining_utilization_budget: Decimal

    base_capacity: Decimal
    regime_multiplier: Decimal
    sleeve_multiplier: Decimal
    volatility_multiplier: Decimal
    confidence_multiplier: Decimal
    drawdown_multiplier: Decimal
    risk_multiplier: Decimal
    health_multiplier: Decimal

    final_capacity: Decimal
    quality: AllocationQuality
    completeness_notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AllocationReport:
    timestamp_ns: int
    timestamp_source: TimestampSource
    total_equity: Decimal
    reserve_buffer: Decimal
    deployable_capital: Decimal
    max_utilization_budget: Decimal
    remaining_utilization_budget: Decimal
    reserved_notional: Decimal
    quality: AllocationQuality
    notes: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class AllocationJournalRecord:
    sequence: int
    allocation_id: int
    timestamp_ns: int
    timestamp_source: TimestampSource
    symbol: str
    sleeve: str
    regime: str
    final_capacity: Decimal
    quality: AllocationQuality


# ============================================================================
# ENGINE
# ============================================================================

class MarketAllocator:
    """
    Sovereign allocation authority.

    Legacy:
        calculate_trade_capacity(...)
        get_allocation_report(...)

    Canonical:
        calculate_trade_capacity_detailed(...)
        build_allocation_report(...)
        journal(...)
    """

    def __init__(
        self,
        base_allocation_pct: Decimal = Decimal("0.10"),
        max_total_utilization: Decimal = Decimal("0.80"),
        risk_free_reserve: Decimal = Decimal("0.20")
    ):
        self.policy = AllocationPolicyConfig(
            base_allocation_pct=base_allocation_pct,
            max_total_utilization=max_total_utilization,
            risk_free_reserve=risk_free_reserve,
        )

        # Preserve legacy attribute names
        self.base_pct = self.policy.base_allocation_pct
        self.max_utilization = self.policy.max_total_utilization
        self.reserve = self.policy.risk_free_reserve
        self.regime_multipliers = self.policy.regime_multipliers

        self._journal: List[AllocationJournalRecord] = []
        self._journal_seq = 0

    # ------------------------------------------------------------------
    # Legacy compatibility API
    # ------------------------------------------------------------------

    def calculate_trade_capacity(
        self,
        symbol: str,
        total_equity: Decimal,
        regime: RegimeType,
        volatility_score: float
    ) -> Decimal:
        """
        Legacy compatibility adapter.

        Because the legacy path lacks canonical context inputs such as explicit
        timestamp, sleeve, reserved notional, drawdown clamp, risk clamp,
        health clamp, and signal confidence, the resulting decision is degraded.
        """
        decision = self.calculate_trade_capacity_detailed(
            symbol=symbol,
            sleeve=SleeveType.POVERTY_KILLER_AGGREGATE,
            regime=regime,
            volatility_score=Decimal(str(volatility_score)),
            context=AllocationContext(
                timestamp_ns=_now_ns(),
                total_equity=_d(total_equity, field_name="total_equity"),
                signal_confidence=ONE,
            ),
            timestamp_source=TimestampSource.LOCAL_GENERATION_TIME,
            compatibility_mode=True,
        )
        return decision.final_capacity

    def get_allocation_report(self, total_equity: Decimal) -> Dict[str, Any]:
        """
        Legacy-compatible report.

        Uses local generation time because legacy signature lacks explicit
        canonical timestamp/context.
        """
        report = self.build_allocation_report(
            context=AllocationContext(
                timestamp_ns=_now_ns(),
                total_equity=_d(total_equity, field_name="total_equity"),
            ),
            timestamp_source=TimestampSource.LOCAL_GENERATION_TIME,
            compatibility_mode=True,
        )
        return {
            "total_equity": report.total_equity,
            "available_for_deployment": report.deployable_capital,
            "reserve_buffer": report.reserve_buffer,
        }

    # ------------------------------------------------------------------
    # Canonical API
    # ------------------------------------------------------------------

    def calculate_trade_capacity_detailed(
        self,
        *,
        symbol: str,
        sleeve: SleeveType,
        regime: RegimeType,
        volatility_score: Decimal,
        context: AllocationContext,
        timestamp_source: TimestampSource = TimestampSource.EXPLICIT_INPUT,
        compatibility_mode: bool = False,
    ) -> AllocationDecision:
        if not symbol:
            raise ValueError("symbol must be non-empty")

        volatility_score = _ensure_non_negative(_d(volatility_score, field_name="volatility_score"), "volatility_score")
        notes: List[str] = []
        quality = AllocationQuality.COMPLETE

        if volatility_score > ONE:
            quality = AllocationQuality.DEGRADED
            notes.append("volatility_score_gt_1_clamped")
            volatility_score = ONE

        if timestamp_source != TimestampSource.EXPLICIT_INPUT:
            quality = AllocationQuality.DEGRADED
            notes.append(f"timestamp_source={timestamp_source.value}")

        if compatibility_mode:
            quality = AllocationQuality.DEGRADED
            notes.append("legacy_compatibility_projection")
            notes.append("reserved_notional_unknown")
            notes.append("drawdown_risk_health_clamps_defaulted")

        total_equity = context.total_equity
        if total_equity <= ZERO:
            return AllocationDecision(
                allocation_id=generate_request_id(),
                correlation_id=generate_correlation_id(),
                timestamp_ns=context.timestamp_ns,
                timestamp_source=timestamp_source,
                symbol=symbol,
                sleeve=sleeve,
                regime=regime,
                total_equity=total_equity,
                reserve_buffer=ZERO,
                deployable_capital=ZERO,
                remaining_utilization_budget=ZERO,
                base_capacity=ZERO,
                regime_multiplier=ZERO,
                sleeve_multiplier=ZERO,
                volatility_multiplier=ZERO,
                confidence_multiplier=ZERO,
                drawdown_multiplier=context.drawdown_multiplier,
                risk_multiplier=context.risk_multiplier,
                health_multiplier=context.health_multiplier,
                final_capacity=ZERO,
                quality=AllocationQuality.DEGRADED,
                completeness_notes=tuple(["non_positive_equity"] + notes),
            )

        reserve_buffer = total_equity * self.policy.risk_free_reserve
        deployable_capital = max(ZERO, total_equity - reserve_buffer)

        max_utilization_budget = total_equity * self.policy.max_total_utilization
        consumed_budget = min(max_utilization_budget, context.reserved_notional + (total_equity * context.current_utilization))
        remaining_utilization_budget = max(ZERO, max_utilization_budget - consumed_budget)

        base_capacity = deployable_capital * self.policy.base_allocation_pct
        regime_multiplier = self.policy.regime_multipliers.get(regime, ZERO)
        sleeve_multiplier = self.policy.sleeve_multipliers.get(sleeve, ONE)

        # Higher volatility -> smaller multiplier, bounded by floor
        volatility_multiplier = max(
            self.policy.volatility_floor_multiplier,
            ONE - volatility_score
        )

        confidence_multiplier = max(
            self.policy.confidence_floor_multiplier,
            context.signal_confidence
        )

        raw_capacity = (
            base_capacity
            * regime_multiplier
            * sleeve_multiplier
            * volatility_multiplier
            * confidence_multiplier
            * context.drawdown_multiplier
            * context.risk_multiplier
            * context.health_multiplier
        )

        final_capacity = min(raw_capacity, remaining_utilization_budget)
        final_capacity = max(self.policy.minimum_capacity_floor, final_capacity)
        final_capacity = _quantize_money(final_capacity)

        self._append_journal(
            AllocationJournalRecord(
                sequence=self._journal_seq + 1,
                allocation_id=generate_request_id(),
                timestamp_ns=context.timestamp_ns,
                timestamp_source=timestamp_source,
                symbol=symbol,
                sleeve=sleeve.value,
                regime=regime.name if hasattr(regime, "name") else str(regime),
                final_capacity=final_capacity,
                quality=quality,
            )
        )

        logger.info(
            "[ALLOCATOR] symbol=%s sleeve=%s regime=%s final_capacity=%s quality=%s",
            symbol,
            sleeve.value,
            regime.name if hasattr(regime, "name") else str(regime),
            final_capacity,
            quality.value,
        )

        return AllocationDecision(
            allocation_id=generate_request_id(),
            correlation_id=generate_correlation_id(),
            timestamp_ns=context.timestamp_ns,
            timestamp_source=timestamp_source,
            symbol=symbol,
            sleeve=sleeve,
            regime=regime,
            total_equity=total_equity,
            reserve_buffer=reserve_buffer,
            deployable_capital=deployable_capital,
            remaining_utilization_budget=remaining_utilization_budget,
            base_capacity=base_capacity,
            regime_multiplier=regime_multiplier,
            sleeve_multiplier=sleeve_multiplier,
            volatility_multiplier=volatility_multiplier,
            confidence_multiplier=confidence_multiplier,
            drawdown_multiplier=context.drawdown_multiplier,
            risk_multiplier=context.risk_multiplier,
            health_multiplier=context.health_multiplier,
            final_capacity=final_capacity,
            quality=quality,
            completeness_notes=tuple(notes),
        )

    def build_allocation_report(
        self,
        *,
        context: AllocationContext,
        timestamp_source: TimestampSource = TimestampSource.EXPLICIT_INPUT,
        compatibility_mode: bool = False,
    ) -> AllocationReport:
        notes: List[str] = []
        quality = AllocationQuality.COMPLETE

        if timestamp_source != TimestampSource.EXPLICIT_INPUT:
            quality = AllocationQuality.DEGRADED
            notes.append(f"timestamp_source={timestamp_source.value}")

        if compatibility_mode:
            quality = AllocationQuality.DEGRADED
            notes.append("legacy_compatibility_projection")

        total_equity = context.total_equity
        reserve_buffer = total_equity * self.policy.risk_free_reserve
        deployable_capital = max(ZERO, total_equity - reserve_buffer)
        max_utilization_budget = total_equity * self.policy.max_total_utilization
        consumed_budget = min(max_utilization_budget, context.reserved_notional + (total_equity * context.current_utilization))
        remaining_utilization_budget = max(ZERO, max_utilization_budget - consumed_budget)

        return AllocationReport(
            timestamp_ns=context.timestamp_ns,
            timestamp_source=timestamp_source,
            total_equity=total_equity,
            reserve_buffer=reserve_buffer,
            deployable_capital=deployable_capital,
            max_utilization_budget=max_utilization_budget,
            remaining_utilization_budget=remaining_utilization_budget,
            reserved_notional=context.reserved_notional,
            quality=quality,
            notes=tuple(notes),
        )

    def journal(self, limit: Optional[int] = None) -> List[AllocationJournalRecord]:
        if limit is None or limit >= len(self._journal):
            return list(self._journal)
        return self._journal[-limit:]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _append_journal(self, record: AllocationJournalRecord) -> None:
        self._journal_seq += 1
        self._journal.append(
            AllocationJournalRecord(
                sequence=self._journal_seq,
                allocation_id=record.allocation_id,
                timestamp_ns=record.timestamp_ns,
                timestamp_source=record.timestamp_source,
                symbol=record.symbol,
                sleeve=record.sleeve,
                regime=record.regime,
                final_capacity=record.final_capacity,
                quality=record.quality,
            )
        )
        if len(self._journal) > self.policy.journal_capacity:
            self._journal = self._journal[-self.policy.journal_capacity:]


__all__ = [
    "AllocationQuality",
    "TimestampSource",
    "AllocationPolicyConfig",
    "AllocationContext",
    "AllocationDecision",
    "AllocationReport",
    "AllocationJournalRecord",
    "MarketAllocator",
]
