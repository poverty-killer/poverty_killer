"""
app/risk/drawdown_guard.py
POVERTY_KILLER — SOVEREIGN DRAWDOWN CONSTITUTION (CITADEL-GRADE)

This module is the canonical drawdown and equity-kinematics authority for the
platform. It models equity impairment as a kinematic hazard surface and emits
deterministic, replay-safe, auditable drawdown advisories.

ARCHITECTURAL ROLE
------------------
Owns locally:
- drawdown state tracking
- high-water-mark governance
- drawdown velocity / acceleration analytics
- aggression multiplier derivation
- drawdown advisories
- forensic snapshots
- bounded reset governance
- mutation journaling
- advisory transition tracking

Does NOT own:
- portfolio equity computation
- exposure accounting
- kill switch implementation
- execution authority
- stale-data generation

DESIGN PRINCIPLES
-----------------
1. Drawdown as Kinematics
   Drawdown is modeled as a dynamic process, not only a static threshold.

2. Deterministic and Replay-Safe
   All updates are timestamp-driven. No wall-clock dependence is required in the
   risk logic itself.

3. Bounded Governance
   Reset and override semantics are explicit, journaled, and truthfully scoped.

4. Confidence and Quality Awareness
   Advisories encode warmup / stale / degraded conditions explicitly.

5. Preserve-Aware Compatibility
   Legacy update(...) -> DrawdownAdvisory remains available while richer
   constitutional outputs are introduced.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation, ROUND_DOWN, getcontext
from enum import Enum, IntEnum, unique
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.utils.enums import (
    AuthorityTier,
    HazardVelocity,
    InvariantViolationSeverity,
    PriorityClass,
    RiskAction,
    RiskLevel,
    RiskVetoReason,
)

getcontext().prec = 28
logger = logging.getLogger(__name__)


# ============================================================================
# HELPERS / CONSTANTS
# ============================================================================

ZERO = Decimal("0")
ONE = Decimal("1")
NS_PER_SEC = 1_000_000_000


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


def _quantize_ratio(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"), rounding=ROUND_DOWN)


# ============================================================================
# ENUMS
# ============================================================================

@unique
class DrawdownQuality(str, Enum):
    INITIALIZING = "INITIALIZING"
    LIVE = "LIVE"
    STALE = "STALE"
    AMBIGUOUS = "AMBIGUOUS"
    RESET = "RESET"


@unique
class DrawdownTransitionType(str, Enum):
    INITIAL = "INITIAL"
    ESCALATION = "ESCALATION"
    RELAXATION = "RELAXATION"
    LATERAL = "LATERAL"


@unique
class DrawdownReasonCode(str, Enum):
    NOMINAL = "NOMINAL"
    CAUTION_DRAWDOWN = "CAUTION_DRAWDOWN"
    SOFT_STOP_DRAWDOWN = "SOFT_STOP_DRAWDOWN"
    HARD_STOP_DRAWDOWN = "HARD_STOP_DRAWDOWN"
    VELOCITY_BREACH = "VELOCITY_BREACH"
    ACCELERATION_BREACH = "ACCELERATION_BREACH"
    STALE_EQUITY_STREAM = "STALE_EQUITY_STREAM"
    TIMESTAMP_REGRESSION = "TIMESTAMP_REGRESSION"
    RESET_APPLIED = "RESET_APPLIED"
    INVALID_EQUITY = "INVALID_EQUITY"


class DrawdownPrecedence(IntEnum):
    INVALID_STREAM = 100
    HARD_STOP = 90
    VELOCITY_VETO = 85
    CRITICAL = 70
    HIGH = 50
    DEGRADED_STREAM = 40
    CAUTION = 20
    NOMINAL = 0


# ============================================================================
# LEGACY CONTRACTS (PRESERVED)
# ============================================================================

@dataclass(frozen=True)
class EquityKinematics:
    """
    Legacy-compatible kinematic snapshot.
    """
    drawdown_pct: float
    velocity_bps_s: float
    acceleration_bps_s2: float
    hwm_distance_pct: float
    is_clamped: bool


@dataclass(frozen=True)
class DrawdownAdvisory:
    """
    Legacy-compatible advisory.
    """
    hazard_level: RiskLevel
    severity: InvariantViolationSeverity
    aggression_multiplier: Decimal
    kinematics: EquityKinematics


# ============================================================================
# CANONICAL MODELS
# ============================================================================

@dataclass(frozen=True, slots=True)
class DrawdownPolicyConfig:
    initial_capital: Decimal
    caution_pct: Decimal = Decimal("0.04")
    soft_stop_pct: Decimal = Decimal("0.07")
    hard_stop_pct: Decimal = Decimal("0.12")

    hazard_velocity_limit_bps_s: Decimal = Decimal("15.0")
    hazard_acceleration_limit_bps_s2: Decimal = Decimal("50.0")

    lookback_window: int = 1000
    min_samples: int = 50
    smoothing_samples: int = 5

    stale_update_ns: int = 5_000_000_000
    min_valid_equity: Decimal = Decimal("0.01")

    recovery_step_per_update: Decimal = Decimal("0.10")
    critical_multiplier_floor: Decimal = Decimal("0.10")

    journal_capacity: int = 50000

    def __post_init__(self) -> None:
        object.__setattr__(self, "initial_capital", _ensure_positive(_d(self.initial_capital, field_name="initial_capital"), "initial_capital"))
        object.__setattr__(self, "caution_pct", _ensure_non_negative(_d(self.caution_pct, field_name="caution_pct"), "caution_pct"))
        object.__setattr__(self, "soft_stop_pct", _ensure_non_negative(_d(self.soft_stop_pct, field_name="soft_stop_pct"), "soft_stop_pct"))
        object.__setattr__(self, "hard_stop_pct", _ensure_non_negative(_d(self.hard_stop_pct, field_name="hard_stop_pct"), "hard_stop_pct"))
        object.__setattr__(self, "hazard_velocity_limit_bps_s", _ensure_non_negative(_d(self.hazard_velocity_limit_bps_s, field_name="hazard_velocity_limit_bps_s"), "hazard_velocity_limit_bps_s"))
        object.__setattr__(self, "hazard_acceleration_limit_bps_s2", _ensure_non_negative(_d(self.hazard_acceleration_limit_bps_s2, field_name="hazard_acceleration_limit_bps_s2"), "hazard_acceleration_limit_bps_s2"))
        object.__setattr__(self, "min_valid_equity", _ensure_positive(_d(self.min_valid_equity, field_name="min_valid_equity"), "min_valid_equity"))
        object.__setattr__(self, "recovery_step_per_update", _ensure_non_negative(_d(self.recovery_step_per_update, field_name="recovery_step_per_update"), "recovery_step_per_update"))
        object.__setattr__(self, "critical_multiplier_floor", _ensure_non_negative(_d(self.critical_multiplier_floor, field_name="critical_multiplier_floor"), "critical_multiplier_floor"))

        if self.caution_pct > self.soft_stop_pct:
            raise ValueError("caution_pct cannot exceed soft_stop_pct")
        if self.soft_stop_pct > self.hard_stop_pct:
            raise ValueError("soft_stop_pct cannot exceed hard_stop_pct")
        if self.lookback_window < 8:
            raise ValueError("lookback_window must be >= 8")
        if self.min_samples < 2:
            raise ValueError("min_samples must be >= 2")
        if self.smoothing_samples < 2:
            raise ValueError("smoothing_samples must be >= 2")
        if self.smoothing_samples > self.lookback_window:
            raise ValueError("smoothing_samples cannot exceed lookback_window")
        if self.stale_update_ns < 0:
            raise ValueError("stale_update_ns must be >= 0")
        if self.journal_capacity < 100:
            raise ValueError("journal_capacity must be >= 100")


@dataclass(frozen=True, slots=True)
class CanonicalEquityKinematics:
    drawdown_pct: Decimal
    velocity_bps_s: Decimal
    acceleration_bps_s2: Decimal
    hwm_distance_pct: Decimal
    equity: Decimal
    high_water_mark: Decimal
    sample_count: int
    hazard_velocity: HazardVelocity
    is_clamped: bool


@dataclass(frozen=True, slots=True)
class CanonicalDrawdownAdvisory:
    hazard_level: RiskLevel
    severity: InvariantViolationSeverity
    risk_action: RiskAction
    authority_tier: AuthorityTier
    priority: PriorityClass

    aggression_multiplier: Decimal
    confidence: Decimal
    quality: DrawdownQuality

    reason: str
    primary_reason_code: DrawdownReasonCode
    precedence: int

    valid_until_ns: int
    reevaluate_after_ns: int
    timestamp_ns: int

    transition_type: DrawdownTransitionType
    kinematics: CanonicalEquityKinematics
    provenance: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "aggression_multiplier", _quantize_ratio(_d(self.aggression_multiplier, field_name="aggression_multiplier")))
        object.__setattr__(self, "confidence", _quantize_ratio(_d(self.confidence, field_name="confidence")))
        if self.aggression_multiplier < ZERO or self.aggression_multiplier > ONE:
            raise ValueError("aggression_multiplier must be in [0,1]")
        if self.confidence < ZERO or self.confidence > ONE:
            raise ValueError("confidence must be in [0,1]")

    def to_legacy(self) -> DrawdownAdvisory:
        return DrawdownAdvisory(
            hazard_level=self.hazard_level,
            severity=self.severity,
            aggression_multiplier=self.aggression_multiplier,
            kinematics=EquityKinematics(
                drawdown_pct=float(self.kinematics.drawdown_pct),
                velocity_bps_s=float(self.kinematics.velocity_bps_s),
                acceleration_bps_s2=float(self.kinematics.acceleration_bps_s2),
                hwm_distance_pct=float(self.kinematics.hwm_distance_pct),
                is_clamped=self.kinematics.is_clamped,
            ),
        )


@dataclass(frozen=True, slots=True)
class DrawdownMutationRecord:
    sequence: int
    timestamp_ns: int
    event: str
    version: int
    payload: Dict[str, Any]


@dataclass(frozen=True, slots=True)
class DrawdownInvariantReport:
    valid: bool
    version: int
    violations: Tuple[str, ...] = field(default_factory=tuple)
    warnings: Tuple[str, ...] = field(default_factory=tuple)


# ============================================================================
# ENGINE
# ============================================================================

class DrawdownGuard:
    """
    Sovereign equity protection authority.
    """

    LOOKBACK_WINDOW: int = 1000
    MIN_SAMPLES: int = 50
    SAMPLING_INTERVAL_MS: int = 100

    def __init__(
        self,
        initial_capital: Decimal,
        hard_stop_pct: Decimal = Decimal("0.12"),
        soft_stop_pct: Decimal = Decimal("0.07"),
        hazard_velocity_limit: float = 15.0,
    ):
        self.policy = DrawdownPolicyConfig(
            initial_capital=_d(initial_capital, field_name="initial_capital"),
            hard_stop_pct=_d(hard_stop_pct, field_name="hard_stop_pct"),
            soft_stop_pct=_d(soft_stop_pct, field_name="soft_stop_pct"),
            hazard_velocity_limit_bps_s=Decimal(str(hazard_velocity_limit)),
        )

        # Preserve legacy class attributes
        self.LOOKBACK_WINDOW = self.policy.lookback_window
        self.MIN_SAMPLES = self.policy.min_samples

        self._initial_capital = self.policy.initial_capital
        self._hwm = self.policy.initial_capital

        # [0]=equity, [1]=ts_ns, [2]=drawdown_pct
        self._history = np.zeros((self.policy.lookback_window, 3), dtype=np.float64)
        self._ptr = 0
        self._is_full = False

        self._last_velocity_bps_s = Decimal("0")
        self._last_ts_ns = 0
        self._active_multiplier = Decimal("1.0")
        self._last_advisory: Optional[CanonicalDrawdownAdvisory] = None

        self._version = 0
        self._mutation_seq = 0
        self._mutation_journal: List[DrawdownMutationRecord] = []

    # ------------------------------------------------------------------
    # Legacy compatibility API
    # ------------------------------------------------------------------

    def update(self, current_equity: Decimal, ts_ns: int) -> DrawdownAdvisory:
        """
        Legacy compatibility projection.
        """
        return self.update_canonical(current_equity=current_equity, ts_ns=ts_ns).to_legacy()

    # ------------------------------------------------------------------
    # Canonical API
    # ------------------------------------------------------------------

    def update_canonical(self, current_equity: Decimal, ts_ns: int) -> CanonicalDrawdownAdvisory:
        current_equity = _d(current_equity, field_name="current_equity")

        if current_equity < self.policy.min_valid_equity:
            return self._build_stream_failure_advisory(
                ts_ns=ts_ns,
                current_equity=current_equity,
                reason="invalid_equity_below_minimum",
                code=DrawdownReasonCode.INVALID_EQUITY,
            )

        if self._last_ts_ns and ts_ns < self._last_ts_ns:
            return self._build_stream_failure_advisory(
                ts_ns=ts_ns,
                current_equity=current_equity,
                reason="timestamp_regression_detected",
                code=DrawdownReasonCode.TIMESTAMP_REGRESSION,
            )

        if current_equity > self._hwm:
            self._hwm = current_equity
            self._append_mutation(
                timestamp_ns=ts_ns,
                event="HWM_ADVANCED",
                payload={"new_hwm": str(self._hwm)},
            )

        dd_pct = (self._hwm - current_equity) / self._hwm if self._hwm > ZERO else ZERO

        self._history[self._ptr] = [float(current_equity), float(ts_ns), float(dd_pct)]
        self._ptr = (self._ptr + 1) % self.policy.lookback_window
        if self._ptr == 0:
            self._is_full = True

        recent = self._get_recent_history(self.policy.smoothing_samples)
        velocity_bps_s = Decimal("0")
        acceleration_bps_s2 = Decimal("0")

        if len(recent) >= 2:
            first_dd = Decimal(str(recent[0, 2]))
            last_dd = Decimal(str(recent[-1, 2]))
            first_ts = int(recent[0, 1])
            last_ts = int(recent[-1, 1])

            dt_s = Decimal(str(max((last_ts - first_ts) / NS_PER_SEC, 1e-9)))
            dd_change = last_dd - first_dd

            # Positive velocity = worsening drawdown, negative = recovery
            velocity_bps_s = (dd_change * Decimal("10000")) / dt_s

            if self._last_ts_ns > 0:
                step_dt_s = Decimal(str(max((ts_ns - self._last_ts_ns) / NS_PER_SEC, 1e-9)))
                acceleration_bps_s2 = (velocity_bps_s - self._last_velocity_bps_s) / step_dt_s

        advisory = self._resolve_advisory(
            current_equity=current_equity,
            ts_ns=ts_ns,
            dd_pct=dd_pct,
            velocity_bps_s=velocity_bps_s,
            acceleration_bps_s2=acceleration_bps_s2,
        )

        self._last_velocity_bps_s = velocity_bps_s
        self._last_ts_ns = ts_ns
        self._active_multiplier = advisory.aggression_multiplier
        self._last_advisory = advisory
        self._bump_version()

        self._append_mutation(
            timestamp_ns=ts_ns,
            event="ADVISORY_UPDATED",
            payload={
                "drawdown_pct": str(dd_pct),
                "velocity_bps_s": str(velocity_bps_s),
                "acceleration_bps_s2": str(acceleration_bps_s2),
                "hazard_level": advisory.hazard_level.name,
                "multiplier": str(advisory.aggression_multiplier),
                "reason_code": advisory.primary_reason_code.value,
            },
        )

        return advisory

    # ------------------------------------------------------------------
    # Internal core logic
    # ------------------------------------------------------------------

    def _resolve_advisory(
        self,
        *,
        current_equity: Decimal,
        ts_ns: int,
        dd_pct: Decimal,
        velocity_bps_s: Decimal,
        acceleration_bps_s2: Decimal,
    ) -> CanonicalDrawdownAdvisory:
        hazard = RiskLevel.NONE
        severity = InvariantViolationSeverity.ADVISORY
        risk_action = RiskAction.ALLOW
        authority_tier = AuthorityTier.ADVISORY
        priority = PriorityClass.DEFERRED
        multiplier = Decimal("1.0")
        quality = DrawdownQuality.LIVE
        confidence = Decimal("1.0")
        precedence = DrawdownPrecedence.NOMINAL
        primary_reason = DrawdownReasonCode.NOMINAL
        reasons: List[str] = ["drawdown_nominal"]

        sample_count = len(self._active_history())
        if sample_count < self.policy.min_samples:
            quality = DrawdownQuality.INITIALIZING
            confidence = Decimal("0.5000")
            reasons = ["drawdown_guard_initializing"]
            primary_reason = DrawdownReasonCode.NOMINAL
            priority = PriorityClass.NORMAL

        if self._last_ts_ns > 0 and (ts_ns - self._last_ts_ns) > self.policy.stale_update_ns:
            quality = DrawdownQuality.STALE
            confidence = Decimal("0.6000")
            hazard = max(hazard, RiskLevel.HIGH)
            severity = InvariantViolationSeverity.WARNING
            risk_action = RiskAction.THROTTLE
            authority_tier = AuthorityTier.ADVISORY
            priority = PriorityClass.URGENT
            multiplier = min(multiplier, Decimal("0.5000"))
            precedence = max(precedence, DrawdownPrecedence.DEGRADED_STREAM)
            primary_reason = DrawdownReasonCode.STALE_EQUITY_STREAM
            reasons = [f"stale_equity_stream>{self.policy.stale_update_ns}ns"]

        # Positive velocity means worsening drawdown
        worsening_velocity = velocity_bps_s > ZERO
        worsening_accel = acceleration_bps_s2 > ZERO

        if dd_pct >= self.policy.hard_stop_pct:
            hazard = RiskLevel.VETO
            severity = InvariantViolationSeverity.HARD_FLAT
            risk_action = RiskAction.FORCE_FLAT
            authority_tier = AuthorityTier.TERMINAL
            priority = PriorityClass.REALTIME
            multiplier = ZERO
            precedence = DrawdownPrecedence.HARD_STOP
            primary_reason = DrawdownReasonCode.HARD_STOP_DRAWDOWN
            reasons = [f"hard_stop_drawdown_breach:{dd_pct}"]

        elif worsening_velocity and velocity_bps_s >= self.policy.hazard_velocity_limit_bps_s:
            hazard = RiskLevel.VETO
            severity = InvariantViolationSeverity.HARD_FLAT
            risk_action = RiskAction.FORCE_FLAT
            authority_tier = AuthorityTier.TERMINAL
            priority = PriorityClass.REALTIME
            multiplier = ZERO
            precedence = DrawdownPrecedence.VELOCITY_VETO
            primary_reason = DrawdownReasonCode.VELOCITY_BREACH
            reasons = [f"velocity_breach:{velocity_bps_s}bps_s"]

        elif worsening_accel and acceleration_bps_s2 >= self.policy.hazard_acceleration_limit_bps_s2:
            hazard = RiskLevel.CRITICAL
            severity = InvariantViolationSeverity.SAFE_MODE
            risk_action = RiskAction.SAFE_MODE
            authority_tier = AuthorityTier.SOFT_BLOCK
            priority = PriorityClass.URGENT
            multiplier = Decimal("0.2500")
            precedence = DrawdownPrecedence.CRITICAL
            primary_reason = DrawdownReasonCode.ACCELERATION_BREACH
            reasons = [f"acceleration_breach:{acceleration_bps_s2}bps_s2"]

        elif dd_pct >= self.policy.soft_stop_pct or (worsening_velocity and velocity_bps_s >= (self.policy.hazard_velocity_limit_bps_s * Decimal("0.7"))):
            hazard = RiskLevel.CRITICAL
            severity = InvariantViolationSeverity.SAFE_MODE
            risk_action = RiskAction.SAFE_MODE
            authority_tier = AuthorityTier.SOFT_BLOCK
            priority = PriorityClass.URGENT

            dist_to_death = Decimal(str(max(float(self.policy.hard_stop_pct - dd_pct), 0.0)))
            multiplier = max(self.policy.critical_multiplier_floor, dist_to_death * Decimal("5.0"))
            precedence = DrawdownPrecedence.CRITICAL
            primary_reason = DrawdownReasonCode.SOFT_STOP_DRAWDOWN
            reasons = [f"soft_stop_drawdown:{dd_pct}"]

        elif dd_pct >= self.policy.caution_pct or (worsening_velocity and velocity_bps_s >= (self.policy.hazard_velocity_limit_bps_s * Decimal("0.4"))):
            hazard = RiskLevel.HIGH
            severity = InvariantViolationSeverity.WARNING
            risk_action = RiskAction.THROTTLE
            authority_tier = AuthorityTier.ADVISORY
            priority = PriorityClass.NORMAL
            multiplier = Decimal("0.7500")
            precedence = DrawdownPrecedence.HIGH
            primary_reason = DrawdownReasonCode.CAUTION_DRAWDOWN
            reasons = [f"caution_drawdown:{dd_pct}"]

        # Recovery hysteresis
        if self._active_multiplier < ONE and multiplier > self._active_multiplier:
            multiplier = min(multiplier, self._active_multiplier + self.policy.recovery_step_per_update)

        hazard_velocity = self._classify_hazard_velocity(velocity_bps_s, acceleration_bps_s2)

        kinematics = CanonicalEquityKinematics(
            drawdown_pct=dd_pct,
            velocity_bps_s=velocity_bps_s,
            acceleration_bps_s2=acceleration_bps_s2,
            hwm_distance_pct=(ONE - (self._initial_capital / self._hwm)) if self._hwm > ZERO else ZERO,
            equity=current_equity,
            high_water_mark=self._hwm,
            sample_count=sample_count,
            hazard_velocity=hazard_velocity,
            is_clamped=(multiplier < ONE),
        )

        transition = self._derive_transition(hazard, multiplier)
        valid_until_ns = ts_ns + self.policy.stale_update_ns
        reevaluate_after_ns = self.policy.min_samples if quality == DrawdownQuality.INITIALIZING else self.SAMPLING_INTERVAL_MS * 1_000_000

        return CanonicalDrawdownAdvisory(
            hazard_level=hazard,
            severity=severity,
            risk_action=risk_action,
            authority_tier=authority_tier,
            priority=priority,
            aggression_multiplier=_quantize_ratio(multiplier),
            confidence=confidence,
            quality=quality,
            reason=" | ".join(reasons),
            primary_reason_code=primary_reason,
            precedence=int(precedence),
            valid_until_ns=valid_until_ns,
            reevaluate_after_ns=reevaluate_after_ns,
            timestamp_ns=ts_ns,
            transition_type=transition,
            kinematics=kinematics,
            provenance={
                "sample_count": sample_count,
                "policy": {
                    "caution_pct": str(self.policy.caution_pct),
                    "soft_stop_pct": str(self.policy.soft_stop_pct),
                    "hard_stop_pct": str(self.policy.hard_stop_pct),
                    "hazard_velocity_limit_bps_s": str(self.policy.hazard_velocity_limit_bps_s),
                    "hazard_acceleration_limit_bps_s2": str(self.policy.hazard_acceleration_limit_bps_s2),
                },
            },
        )

    def _build_stream_failure_advisory(
        self,
        *,
        ts_ns: int,
        current_equity: Decimal,
        reason: str,
        code: DrawdownReasonCode,
    ) -> CanonicalDrawdownAdvisory:
        kinematics = CanonicalEquityKinematics(
            drawdown_pct=ZERO,
            velocity_bps_s=ZERO,
            acceleration_bps_s2=ZERO,
            hwm_distance_pct=ZERO,
            equity=current_equity,
            high_water_mark=self._hwm,
            sample_count=len(self._active_history()),
            hazard_velocity=HazardVelocity.DECAPITATING,
            is_clamped=True,
        )

        advisory = CanonicalDrawdownAdvisory(
            hazard_level=RiskLevel.VETO,
            severity=InvariantViolationSeverity.HARD_FLAT,
            risk_action=RiskAction.BLOCK_ALL_NEW,
            authority_tier=AuthorityTier.HARD_BLOCK,
            priority=PriorityClass.REALTIME,
            aggression_multiplier=ZERO,
            confidence=Decimal("1.0"),
            quality=DrawdownQuality.AMBIGUOUS,
            reason=reason,
            primary_reason_code=code,
            precedence=int(DrawdownPrecedence.INVALID_STREAM),
            valid_until_ns=0,
            reevaluate_after_ns=self.SAMPLING_INTERVAL_MS * 1_000_000,
            timestamp_ns=ts_ns,
            transition_type=self._derive_transition(RiskLevel.VETO, ZERO),
            kinematics=kinematics,
            provenance={"stream_failure": True},
        )

        self._append_mutation(
            timestamp_ns=ts_ns,
            event="STREAM_FAILURE",
            payload={"reason": reason, "code": code.value, "equity": str(current_equity)},
        )
        return advisory

    # ------------------------------------------------------------------
    # History / analytics
    # ------------------------------------------------------------------

    def _get_recent_history(self, n: int) -> np.ndarray:
        if not self._is_full:
            return self._history[:self._ptr][-n:]
        idx = np.arange(self._ptr - n, self._ptr) % self.policy.lookback_window
        return self._history[idx]

    def _active_history(self) -> np.ndarray:
        return self._history if self._is_full else self._history[:self._ptr]

    def _classify_hazard_velocity(
        self,
        velocity_bps_s: Decimal,
        acceleration_bps_s2: Decimal,
    ) -> HazardVelocity:
        if velocity_bps_s >= self.policy.hazard_velocity_limit_bps_s:
            return HazardVelocity.DECAPITATING
        if velocity_bps_s > ZERO or acceleration_bps_s2 > ZERO:
            return HazardVelocity.ACCELERATING
        return HazardVelocity.STABLE

    def _derive_transition(
        self,
        hazard: RiskLevel,
        multiplier: Decimal,
    ) -> DrawdownTransitionType:
        if self._last_advisory is None:
            return DrawdownTransitionType.INITIAL

        prior_rank = (self._last_advisory.hazard_level.value, self._last_advisory.aggression_multiplier)
        new_rank = (hazard.value, multiplier)

        if new_rank[0] > prior_rank[0] or (new_rank[0] == prior_rank[0] and new_rank[1] < prior_rank[1]):
            return DrawdownTransitionType.ESCALATION
        if new_rank[0] < prior_rank[0] or (new_rank[0] == prior_rank[0] and new_rank[1] > prior_rank[1]):
            return DrawdownTransitionType.RELAXATION
        return DrawdownTransitionType.LATERAL

    # ------------------------------------------------------------------
    # Forensics / governance / invariants
    # ------------------------------------------------------------------

    def get_forensic_state(self) -> Dict[str, Any]:
        active = self._active_history()
        if len(active) < self.policy.min_samples:
            return {
                "status": DrawdownQuality.INITIALIZING.value,
                "hwm": float(self._hwm),
                "sample_count": int(len(active)),
                "version": self._version,
            }

        equity_stream = active[:, 0]
        returns = np.diff(equity_stream) / equity_stream[:-1] if len(equity_stream) > 1 else np.array([0.0])
        volatility = np.std(returns) * np.sqrt(252 * 28800) if len(returns) > 0 else 0.0
        max_observed_v = float(np.max(np.abs(np.diff(equity_stream) / equity_stream[:-1] * 10000))) if len(equity_stream) > 1 else 0.0

        current_equity = Decimal(str(equity_stream[-1]))
        current_dd = (self._hwm - current_equity) / self._hwm if self._hwm > ZERO else ZERO

        return {
            "version": self._version,
            "hwm": float(self._hwm),
            "current_multiplier": float(self._active_multiplier),
            "kinematics": {
                "velocity_bps_s": float(self._last_velocity_bps_s),
                "drawdown_pct": float(current_dd),
            },
            "statistical": {
                "equity_volatility_annualized": float(volatility),
                "max_observed_v_bps": max_observed_v,
                "sample_count": len(active),
            },
            "policy": {
                "caution_pct": float(self.policy.caution_pct),
                "soft_stop_pct": float(self.policy.soft_stop_pct),
                "hard_stop_pct": float(self.policy.hard_stop_pct),
                "v_limit": float(self.policy.hazard_velocity_limit_bps_s),
                "a_limit": float(self.policy.hazard_acceleration_limit_bps_s2),
            },
            "last_advisory": None if self._last_advisory is None else self._last_advisory.to_legacy().__dict__,
        }

    def reset_authority(
        self,
        current_equity: Decimal,
        *,
        issuer: str = "UNKNOWN",
        reason: str = "MANUAL_RESET",
        ts_ns: Optional[int] = None,
    ) -> None:
        """
        Sovereign reset path.

        This is a governance event. It resets HWM and clears the active sample
        buffer. Intended for capital injection, board-authorized reset, or
        explicit recovery action.
        """
        ts_ns = ts_ns if ts_ns is not None else self._last_ts_ns
        current_equity = _ensure_positive(_d(current_equity, field_name="current_equity"), "current_equity")

        logger.critical("[DRAWDOWN_GOVERNANCE] Reset HWM to %s issuer=%s reason=%s", current_equity, issuer, reason)

        self._hwm = current_equity
        self._ptr = 0
        self._is_full = False
        self._history.fill(0)
        self._last_velocity_bps_s = ZERO
        self._active_multiplier = ONE
        self._last_advisory = None
        self._bump_version()
        self._append_mutation(
            timestamp_ns=ts_ns,
            event="AUTHORITY_RESET",
            payload={
                "issuer": issuer,
                "reason": reason,
                "new_hwm": str(current_equity),
            },
        )

    def mutation_journal(self, limit: Optional[int] = None) -> List[DrawdownMutationRecord]:
        if limit is None or limit >= len(self._mutation_journal):
            return list(self._mutation_journal)
        return self._mutation_journal[-limit:]

    def validate_invariants(self) -> DrawdownInvariantReport:
        violations: List[str] = []
        warnings: List[str] = []

        if self._hwm <= ZERO:
            violations.append("hwm_non_positive")

        if self._active_multiplier < ZERO or self._active_multiplier > ONE:
            violations.append("active_multiplier_out_of_bounds")

        active = self._active_history()
        if len(active) > 1:
            ts = active[:, 1]
            if np.any(np.diff(ts) < 0):
                violations.append("history_timestamp_regression")

        if self._last_advisory is not None and (self._last_advisory.aggression_multiplier < ZERO or self._last_advisory.aggression_multiplier > ONE):
            violations.append("advisory_multiplier_out_of_bounds")

        if len(active) < self.policy.min_samples:
            warnings.append("warming_state")

        return DrawdownInvariantReport(
            valid=len(violations) == 0,
            version=self._version,
            violations=tuple(violations),
            warnings=tuple(warnings),
        )

    # ------------------------------------------------------------------
    # Internal journal / version helpers
    # ------------------------------------------------------------------

    def _append_mutation(
        self,
        *,
        timestamp_ns: int,
        event: str,
        payload: Dict[str, Any],
    ) -> None:
        self._mutation_seq += 1
        self._mutation_journal.append(
            DrawdownMutationRecord(
                sequence=self._mutation_seq,
                timestamp_ns=timestamp_ns,
                event=event,
                version=self._version,
                payload=payload,
            )
        )
        if len(self._mutation_journal) > self.policy.journal_capacity:
            self._mutation_journal = self._mutation_journal[-self.policy.journal_capacity:]

    def _bump_version(self) -> None:
        self._version += 1


__all__ = [
    "EquityKinematics",
    "DrawdownAdvisory",
    "DrawdownQuality",
    "DrawdownTransitionType",
    "DrawdownReasonCode",
    "DrawdownPrecedence",
    "DrawdownPolicyConfig",
    "CanonicalEquityKinematics",
    "CanonicalDrawdownAdvisory",
    "DrawdownMutationRecord",
    "DrawdownInvariantReport",
    "DrawdownGuard",
]
