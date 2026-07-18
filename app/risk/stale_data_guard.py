"""
app/risk/stale_data_guard.py
POVERTY_KILLER — CANONICAL TEMPORAL INTEGRITY GUARD (CITADEL-GRADE)

This module provides a deterministic, replay-safe, institution-grade temporal
integrity monitor for market data freshness and exchange timestamp continuity.

It models feed staleness as a temporal hazard surface:
- absolute drift
- drift velocity
- drift acceleration
- jitter / variance
- entropy of arrival intervals
- skewness / tail-fatness
- micro-stalls / heartbeat collapse
- continuity invariant violations

ARCHITECTURAL ROLE
------------------
- This module is a risk-analysis authority, not an execution engine.
- It emits canonical temporal assessments and risk advisories.
- Orchestrator / risk authority decide how advisories are enforced.

DESIGN PRINCIPLES
-----------------
1. Deterministic and Replay-Safe
   Inputs and outputs are explicit and serializable.

2. Bounded Numerical Behavior
   All critical calculations guard against divide-by-zero, warmup distortion,
   and undefined statistical states.

3. Compatibility Without Weakness
   Legacy evaluate(...) and validate_continuity_invariant(...) entrypoints are
   preserved while canonical structured outputs are introduced.

4. Strong Temporal Semantics
   Exchange time continuity, future-dating, stale arrivals, and drift kinematics
   are all classified explicitly.

5. Low-Latency Friendly
   Rolling numpy buffers are preserved for efficient analytics.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, Final, Optional, Tuple

import numpy as np

from app.utils.enums import (
    AuthorityTier,
    BookIntegrity,
    DegradationMode,
    EventSource,
    HazardVelocity,
    InvariantViolationSeverity,
    PriorityClass,
    ReplayMode,
    RiskAction,
    RiskLevel,
    RiskVetoReason,
)

logger = logging.getLogger(__name__)


# ============================================================================
# CONSTANTS
# ============================================================================

NS_PER_MS: Final[int] = 1_000_000
NS_PER_SEC: Final[int] = 1_000_000_000
DEFAULT_WINDOW_SIZE: Final[int] = 1000
DEFAULT_MIN_SAMPLES: Final[int] = 50
DEFAULT_FUTURE_SKEW_TOLERANCE_MS: Final[int] = 50
DEFAULT_MAX_FORWARD_GAP_MS: Final[int] = 5_000
DEFAULT_ZSCORE_WARNING: Final[float] = 2.0
DEFAULT_ZSCORE_HIGH: Final[float] = 3.0
DEFAULT_VELOCITY_CRITICAL_NS_PER_S: Final[float] = 1e8


# ============================================================================
# MODELS
# ============================================================================

@dataclass(frozen=True, slots=True)
class TemporalGuardConfig:
    """
    Canonical stale-data / temporal integrity policy.
    """
    symbol: str
    max_drift_ms: int = 500
    window_size: int = DEFAULT_WINDOW_SIZE
    min_samples: int = DEFAULT_MIN_SAMPLES
    sigma_limit: float = 3.0
    future_skew_tolerance_ms: int = DEFAULT_FUTURE_SKEW_TOLERANCE_MS
    max_forward_gap_ms: int = DEFAULT_MAX_FORWARD_GAP_MS
    zscore_warning: float = DEFAULT_ZSCORE_WARNING
    zscore_high: float = DEFAULT_ZSCORE_HIGH
    critical_velocity_ns_per_s: float = DEFAULT_VELOCITY_CRITICAL_NS_PER_S
    micro_stall_interval_ns: int = 0
    stale_arrival_ms: Optional[int] = None
    suppress_until_warm: bool = False

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("symbol must be non-empty")
        if self.max_drift_ms <= 0:
            raise ValueError("max_drift_ms must be > 0")
        if self.window_size < 8:
            raise ValueError("window_size must be >= 8")
        if self.min_samples < 2:
            raise ValueError("min_samples must be >= 2")
        if self.min_samples > self.window_size:
            raise ValueError("min_samples cannot exceed window_size")
        if self.sigma_limit <= 0:
            raise ValueError("sigma_limit must be > 0")
        if self.future_skew_tolerance_ms < 0:
            raise ValueError("future_skew_tolerance_ms must be >= 0")
        if self.max_forward_gap_ms < 0:
            raise ValueError("max_forward_gap_ms must be >= 0")
        if self.zscore_warning < 0 or self.zscore_high < 0:
            raise ValueError("z-score thresholds must be >= 0")
        if self.zscore_warning > self.zscore_high:
            raise ValueError("zscore_warning cannot exceed zscore_high")
        if self.critical_velocity_ns_per_s < 0:
            raise ValueError("critical_velocity_ns_per_s must be >= 0")
        if self.micro_stall_interval_ns < 0:
            raise ValueError("micro_stall_interval_ns must be >= 0")
        if self.stale_arrival_ms is not None and self.stale_arrival_ms < 0:
            raise ValueError("stale_arrival_ms must be >= 0 if provided")


@dataclass(frozen=True, slots=True)
class TemporalInput:
    """
    Canonical input observation.
    """
    current_ts_ns: int
    exchange_ts_ns: int
    local_received_ts_ns: Optional[int] = None
    source: EventSource = EventSource.MARKET_DATA
    replay_mode: ReplayMode = ReplayMode.LIVE
    degradation_mode: DegradationMode = DegradationMode.NORMAL
    book_integrity: BookIntegrity = BookIntegrity.UNKNOWN

    def __post_init__(self) -> None:
        if self.current_ts_ns < 0:
            raise ValueError("current_ts_ns must be >= 0")
        if self.exchange_ts_ns < 0:
            raise ValueError("exchange_ts_ns must be >= 0")
        if self.local_received_ts_ns is not None and self.local_received_ts_ns < 0:
            raise ValueError("local_received_ts_ns must be >= 0")


@dataclass(frozen=True, slots=True)
class TemporalKinematics:
    """
    Physical state of latency and timestamp drift.
    """
    drift_ns: int
    velocity_ns_s: float
    acceleration_ns_s2: float
    jitter_sigma_ns: float
    z_score: float
    entropy: float
    skewness: float
    sample_count: int
    interval_ns: int
    micro_stalls_detected: int
    uptime_ns: int


@dataclass(frozen=True, slots=True)
class TemporalInvariantStatus:
    """
    Hard continuity invariant status.
    """
    valid: bool
    future_dated: bool
    regressed: bool
    excessive_forward_gap: bool
    local_clock_regressed: bool
    receipt_after_assessment: bool
    reason: Optional[str] = None
    veto_reason: Optional[RiskVetoReason] = None


@dataclass(frozen=True, slots=True)
class TemporalRiskAssessment:
    """
    Canonical temporal risk advisory emitted by this module.
    """
    symbol: str
    timestamp_ns: int
    exchange_ts_ns: int
    local_received_ts_ns: int

    risk_level: RiskLevel
    severity: InvariantViolationSeverity
    risk_action: RiskAction
    authority_tier: AuthorityTier
    priority: PriorityClass
    hazard_velocity: HazardVelocity

    invariant_status: TemporalInvariantStatus
    kinematics: TemporalKinematics

    warm: bool
    suppress_reason: Optional[str]

    rationale: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        """Stable replay/guardrail evidence without enum or dataclass leakage."""
        return {
            "symbol": self.symbol,
            "timestamp_ns": self.timestamp_ns,
            "exchange_ts_ns": self.exchange_ts_ns,
            "local_received_ts_ns": self.local_received_ts_ns,
            "risk_level": self.risk_level.value,
            "severity": self.severity.value,
            "risk_action": self.risk_action.value,
            "authority_tier": self.authority_tier.value,
            "priority": self.priority.value,
            "hazard_velocity": self.hazard_velocity.value,
            "invariant_status": {
                "valid": self.invariant_status.valid,
                "future_dated": self.invariant_status.future_dated,
                "regressed": self.invariant_status.regressed,
                "excessive_forward_gap": self.invariant_status.excessive_forward_gap,
                "local_clock_regressed": self.invariant_status.local_clock_regressed,
                "receipt_after_assessment": self.invariant_status.receipt_after_assessment,
                "reason": self.invariant_status.reason,
                "veto_reason": (
                    self.invariant_status.veto_reason.value
                    if self.invariant_status.veto_reason is not None
                    else None
                ),
            },
            "kinematics": {
                "drift_ns": self.kinematics.drift_ns,
                "velocity_ns_s": self.kinematics.velocity_ns_s,
                "acceleration_ns_s2": self.kinematics.acceleration_ns_s2,
                "jitter_sigma_ns": self.kinematics.jitter_sigma_ns,
                "z_score": self.kinematics.z_score,
                "entropy": self.kinematics.entropy,
                "skewness": self.kinematics.skewness,
                "sample_count": self.kinematics.sample_count,
                "interval_ns": self.kinematics.interval_ns,
                "micro_stalls_detected": self.kinematics.micro_stalls_detected,
                "uptime_ns": self.kinematics.uptime_ns,
            },
            "warm": self.warm,
            "suppress_reason": self.suppress_reason,
            "rationale": self.rationale,
            "warnings": self.warnings,
        }


# ============================================================================
# ENGINE
# ============================================================================

class StaleDataGuard:
    """
    Sovereign Temporal Monitor.

    Uses rolling numpy buffers for bounded-latency analytics while exposing
    canonical structured outputs for orchestrator/risk integration.
    """

    WINDOW_SIZE: Final[int] = DEFAULT_WINDOW_SIZE
    MIN_SAMPLES: Final[int] = DEFAULT_MIN_SAMPLES

    def __init__(self, symbol: str, max_drift_ms: int = 500):
        self.config = TemporalGuardConfig(
            symbol=symbol,
            max_drift_ms=max_drift_ms,
        )

        self.symbol = self.config.symbol
        self.max_drift_ns = self.config.max_drift_ms * NS_PER_MS

        # Rolling state:
        # [:,0] drift_ns
        # [:,1] interval_ns
        # [:,2] arrival/current_ts_ns
        # [:,3] exchange_ts_ns
        self._buffer = np.zeros((self.config.window_size, 4), dtype=np.int64)
        self._ptr = 0
        self._is_full = False

        # Running state
        self._last_drift = 0
        self._last_velocity = 0.0
        self._last_arrival_ts_ns = 0
        self._last_exchange_ts_ns = 0
        self._last_assessment_ts_ns = 0

        # Compatibility attribute
        self.sigma_limit = self.config.sigma_limit

    # ------------------------------------------------------------------
    # Canonical API
    # ------------------------------------------------------------------

    def assess(self, observation: TemporalInput) -> TemporalRiskAssessment:
        """
        Canonical temporal integrity assessment.
        """
        rationale = []
        warnings = []

        arrival_ts_ns = int(
            observation.local_received_ts_ns
            if observation.local_received_ts_ns is not None
            else observation.current_ts_ns
        )

        invariant_status = self._validate_invariant_status(
            incoming_exchange_ts_ns=observation.exchange_ts_ns,
            current_ts_ns=observation.current_ts_ns,
            local_received_ts_ns=arrival_ts_ns,
        )

        interval_ns = (
            arrival_ts_ns - self._last_arrival_ts_ns
            if self._last_arrival_ts_ns > 0 else 0
        )

        drift_ns = arrival_ts_ns - observation.exchange_ts_ns

        if self._last_arrival_ts_ns > 0:
            dt_s = max(
                (arrival_ts_ns - self._last_arrival_ts_ns) / NS_PER_SEC,
                1e-9,
            )
            velocity_ns_s = (drift_ns - self._last_drift) / dt_s
            acceleration_ns_s2 = (velocity_ns_s - self._last_velocity) / dt_s
        else:
            # A first observation has no temporal derivative. Inventing a
            # denominator here creates a false velocity and a false SAFE_MODE.
            velocity_ns_s = 0.0
            acceleration_ns_s2 = 0.0

        self._push_sample(
            drift_ns=drift_ns,
            interval_ns=interval_ns,
            arrival_ts_ns=arrival_ts_ns,
            exchange_ts_ns=observation.exchange_ts_ns,
        )

        active = self._active_view()
        stats = self._compute_statistics(active, current_drift_ns=drift_ns)

        if not invariant_status.valid:
            rationale.append(f"invariant_violation:{invariant_status.reason}")
        if abs(drift_ns) > self.max_drift_ns:
            rationale.append("absolute_drift_limit_breach")
        if abs(velocity_ns_s) > self.config.critical_velocity_ns_per_s:
            rationale.append("critical_drift_velocity")
        if stats["z_score"] >= self.config.zscore_high:
            rationale.append("high_zscore_outlier")
        elif stats["z_score"] >= self.config.zscore_warning:
            warnings.append("elevated_zscore_outlier")
        if stats["micro_stalls"] > 0:
            warnings.append(f"micro_stalls:{stats['micro_stalls']}")
        if observation.book_integrity in {
            BookIntegrity.STALE,
            BookIntegrity.UNTRUSTWORTHY,
            BookIntegrity.CROSSED,
        }:
            warnings.append(f"book_integrity={observation.book_integrity.value}")

        warm = len(active) >= self.config.min_samples
        suppress_reason = None

        risk_level, severity, risk_action, authority_tier, priority = self._resolve_hazard(
            drift_ns=drift_ns,
            velocity_ns_s=velocity_ns_s,
            acceleration_ns_s2=acceleration_ns_s2,
            sigma_ns=stats["std_drift"],
            z_score=stats["z_score"],
            invariant_status=invariant_status,
            warm=warm,
        )

        if not warm and self.config.suppress_until_warm:
            suppress_reason = "warming_up"
            risk_level = RiskLevel.NONE
            severity = InvariantViolationSeverity.ADVISORY
            risk_action = RiskAction.ADVISE
            authority_tier = AuthorityTier.ADVISORY
            priority = PriorityClass.DEFERRED

        hazard_velocity = self._classify_hazard_velocity(
            velocity_ns_s=velocity_ns_s,
            acceleration_ns_s2=acceleration_ns_s2,
        )

        kinematics = TemporalKinematics(
            drift_ns=drift_ns,
            velocity_ns_s=float(velocity_ns_s),
            acceleration_ns_s2=float(acceleration_ns_s2),
            jitter_sigma_ns=float(stats["std_drift"]),
            z_score=float(stats["z_score"]),
            entropy=float(stats["entropy"]),
            skewness=float(stats["skewness"]),
            sample_count=len(active),
            interval_ns=int(interval_ns),
            micro_stalls_detected=int(stats["micro_stalls"]),
            uptime_ns=int(stats["uptime_ns"]),
        )

        assessment = TemporalRiskAssessment(
            symbol=self.symbol,
            timestamp_ns=observation.current_ts_ns,
            exchange_ts_ns=observation.exchange_ts_ns,
            local_received_ts_ns=arrival_ts_ns,
            risk_level=risk_level,
            severity=severity,
            risk_action=risk_action,
            authority_tier=authority_tier,
            priority=priority,
            hazard_velocity=hazard_velocity,
            invariant_status=invariant_status,
            kinematics=kinematics,
            warm=warm,
            suppress_reason=suppress_reason,
            rationale=tuple(rationale),
            warnings=tuple(warnings),
        )

        self._last_drift = drift_ns
        self._last_velocity = velocity_ns_s
        self._last_arrival_ts_ns = arrival_ts_ns
        self._last_exchange_ts_ns = observation.exchange_ts_ns
        self._last_assessment_ts_ns = observation.current_ts_ns

        return assessment

    # ------------------------------------------------------------------
    # Backward-aware compatibility API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        current_ts_ns: int,
        exchange_ts_ns: int,
    ) -> Tuple[RiskLevel, InvariantViolationSeverity, TemporalKinematics]:
        """
        Legacy compatibility facade.

        Preserves old return shape:
            (RiskLevel, InvariantViolationSeverity, TemporalKinematics)
        """
        assessment = self.assess(
            TemporalInput(
                current_ts_ns=current_ts_ns,
                exchange_ts_ns=exchange_ts_ns,
            )
        )
        return assessment.risk_level, assessment.severity, assessment.kinematics

    def validate_continuity_invariant(self, incoming_exchange_ts_ns: int) -> bool:
        """
        Legacy compatibility boolean check.
        """
        current_ts_ns = time.time_ns()
        status = self._validate_invariant_status(
            incoming_exchange_ts_ns=incoming_exchange_ts_ns,
            current_ts_ns=current_ts_ns,
            local_received_ts_ns=current_ts_ns,
        )
        if not status.valid:
            if status.future_dated:
                logger.critical("[TEMPORAL_VETO] Impossible Future TS: %s", incoming_exchange_ts_ns)
            elif status.regressed:
                logger.error("[TEMPORAL_VETO] Time Regression: %s < %s", incoming_exchange_ts_ns, self._last_exchange_ts_ns)
            elif status.excessive_forward_gap:
                logger.error("[TEMPORAL_VETO] Excessive Forward Gap: %s", incoming_exchange_ts_ns)
        return status.valid

    # ------------------------------------------------------------------
    # Forensics / observability
    # ------------------------------------------------------------------

    def get_forensic_snapshot(self) -> Dict[str, Any]:
        """
        Provides a high-fidelity state-space snapshot for truth / replay tooling.
        """
        if not self._is_full and self._ptr < self.config.min_samples:
            return {
                "status": "WARMING_UP",
                "symbol": self.symbol,
                "samples": self._ptr,
                "window_size": self.config.window_size,
            }

        active = self._active_view()
        stats = self._compute_statistics(active)
        drifts = active[:, 0]

        mean_drift = float(np.mean(drifts)) if len(drifts) else 0.0
        std_drift = float(stats["std_drift"])

        return {
            "symbol": self.symbol,
            "status": "READY",
            "kinematics": {
                "current_drift_ns": int(self._last_drift),
                "velocity_ns_s": float(self._last_velocity),
                "z_score": float(stats["z_score"]),
                "sigma_ns": std_drift,
                "entropy": float(stats["entropy"]),
                "skewness": float(stats["skewness"]),
            },
            "integrity_metrics": {
                "micro_stalls_detected": int(stats["micro_stalls"]),
                "uptime_ns": int(stats["uptime_ns"]),
                "sample_density": float(len(active) / self.config.window_size),
                "mean_drift_ns": mean_drift,
            },
            "thresholds": {
                "hard_limit_ns": int(self.max_drift_ns),
                "dynamic_sigma_limit": float(mean_drift + (self.sigma_limit * std_drift)),
                "future_skew_tolerance_ns": int(self.config.future_skew_tolerance_ms * NS_PER_MS),
                "critical_velocity_ns_per_s": float(self.config.critical_velocity_ns_per_s),
            },
            "state": {
                "last_arrival_ts_ns": int(self._last_arrival_ts_ns),
                "last_exchange_ts_ns": int(self._last_exchange_ts_ns),
                "last_assessment_ts_ns": int(self._last_assessment_ts_ns),
                "buffer_ptr": int(self._ptr),
                "buffer_full": bool(self._is_full),
            },
        }

    # ------------------------------------------------------------------
    # Internal mechanics
    # ------------------------------------------------------------------

    def _push_sample(
        self,
        *,
        drift_ns: int,
        interval_ns: int,
        arrival_ts_ns: int,
        exchange_ts_ns: int,
    ) -> None:
        self._buffer[self._ptr] = [drift_ns, interval_ns, arrival_ts_ns, exchange_ts_ns]
        self._ptr = (self._ptr + 1) % self.config.window_size
        if self._ptr == 0:
            self._is_full = True

    def _active_view(self) -> np.ndarray:
        return self._buffer if self._is_full else self._buffer[:self._ptr]

    def _compute_statistics(
        self,
        active: np.ndarray,
        *,
        current_drift_ns: Optional[int] = None,
    ) -> Dict[str, float]:
        if len(active) == 0:
            return {
                "std_drift": 0.0,
                "mean_drift": 0.0,
                "z_score": 0.0,
                "entropy": 0.0,
                "skewness": 0.0,
                "micro_stalls": 0.0,
                "uptime_ns": 0.0,
            }

        drifts = active[:, 0]
        intervals = active[:, 1]
        arrivals = active[:, 2]

        mean_drift = float(np.mean(drifts))
        std_drift = float(np.std(drifts)) if len(active) >= self.config.min_samples else 0.0

        if std_drift > 0:
            observed_drift = (
                self._last_drift
                if current_drift_ns is None
                else int(current_drift_ns)
            )
            z_score = float((observed_drift - mean_drift) / std_drift)
        else:
            z_score = 0.0

        micro_stalls = int(np.sum(intervals <= self.config.micro_stall_interval_ns))
        uptime_ns = int(arrivals[-1] - arrivals[0]) if len(arrivals) > 1 else 0

        return {
            "std_drift": std_drift,
            "mean_drift": mean_drift,
            "z_score": z_score,
            "entropy": self._calculate_shannon_entropy(intervals),
            "skewness": self._calculate_skewness(drifts),
            "micro_stalls": micro_stalls,
            "uptime_ns": uptime_ns,
        }

    def _resolve_hazard(
        self,
        *,
        drift_ns: int,
        velocity_ns_s: float,
        acceleration_ns_s2: float,
        sigma_ns: float,
        z_score: float,
        invariant_status: TemporalInvariantStatus,
        warm: bool,
    ) -> tuple[RiskLevel, InvariantViolationSeverity, RiskAction, AuthorityTier, PriorityClass]:
        """
        Canonical temporal hazard decision logic.
        """
        # Hard invariant failures
        if not invariant_status.valid:
            return (
                RiskLevel.VETO,
                InvariantViolationSeverity.HARD_FLAT,
                RiskAction.BLOCK_ALL_NEW,
                AuthorityTier.HARD_BLOCK,
                PriorityClass.REALTIME,
            )

        # Absolute drift breach
        if abs(drift_ns) > self.max_drift_ns:
            return (
                RiskLevel.VETO,
                InvariantViolationSeverity.HARD_FLAT,
                RiskAction.BLOCK_ALL_NEW,
                AuthorityTier.HARD_BLOCK,
                PriorityClass.REALTIME,
            )

        # Critical drift acceleration/velocity
        if abs(velocity_ns_s) > self.config.critical_velocity_ns_per_s:
            return (
                RiskLevel.CRITICAL,
                InvariantViolationSeverity.SAFE_MODE,
                RiskAction.SAFE_MODE,
                AuthorityTier.SOFT_BLOCK,
                PriorityClass.URGENT,
            )

        # Statistical instability
        if warm and sigma_ns > (self.max_drift_ns * 0.30):
            return (
                RiskLevel.HIGH,
                InvariantViolationSeverity.WARNING,
                RiskAction.THROTTLE,
                AuthorityTier.ADVISORY,
                PriorityClass.URGENT,
            )

        if warm and abs(z_score) >= self.config.zscore_high:
            return (
                RiskLevel.HIGH,
                InvariantViolationSeverity.WARNING,
                RiskAction.THROTTLE,
                AuthorityTier.ADVISORY,
                PriorityClass.NORMAL,
            )

        if warm and abs(z_score) >= self.config.zscore_warning:
            return (
                RiskLevel.MEDIUM,
                InvariantViolationSeverity.WARNING,
                RiskAction.ADVISE,
                AuthorityTier.ADVISORY,
                PriorityClass.NORMAL,
            )

        if abs(acceleration_ns_s2) > (self.config.critical_velocity_ns_per_s * 2):
            return (
                RiskLevel.MEDIUM,
                InvariantViolationSeverity.WARNING,
                RiskAction.ADVISE,
                AuthorityTier.ADVISORY,
                PriorityClass.NORMAL,
            )

        return (
            RiskLevel.NONE,
            InvariantViolationSeverity.ADVISORY,
            RiskAction.ALLOW,
            AuthorityTier.ADVISORY,
            PriorityClass.DEFERRED,
        )

    def _classify_hazard_velocity(
        self,
        *,
        velocity_ns_s: float,
        acceleration_ns_s2: float,
    ) -> HazardVelocity:
        if abs(velocity_ns_s) > self.config.critical_velocity_ns_per_s:
            return HazardVelocity.DECAPITATING
        if abs(velocity_ns_s) > (self.config.critical_velocity_ns_per_s * 0.25) or abs(acceleration_ns_s2) > 1e8:
            return HazardVelocity.ACCELERATING
        return HazardVelocity.STABLE

    def _validate_invariant_status(
        self,
        *,
        incoming_exchange_ts_ns: int,
        current_ts_ns: int,
        local_received_ts_ns: int,
    ) -> TemporalInvariantStatus:
        """
        Hard invariant:
        - exchange time cannot be impossibly future-dated
        - exchange time cannot regress
        - exchange time cannot leap forward by absurd discontinuity
        """
        tolerance_ns = self.config.future_skew_tolerance_ms * NS_PER_MS
        max_forward_gap_ns = self.config.max_forward_gap_ms * NS_PER_MS

        future_dated = incoming_exchange_ts_ns > (local_received_ts_ns + tolerance_ns)
        regressed = self._last_exchange_ts_ns > 0 and incoming_exchange_ts_ns < self._last_exchange_ts_ns
        excessive_forward_gap = (
            self._last_exchange_ts_ns > 0 and
            (incoming_exchange_ts_ns - self._last_exchange_ts_ns) > max_forward_gap_ns
        )
        local_clock_regressed = (
            (self._last_arrival_ts_ns > 0 and local_received_ts_ns < self._last_arrival_ts_ns)
            or (self._last_assessment_ts_ns > 0 and current_ts_ns < self._last_assessment_ts_ns)
        )
        receipt_after_assessment = local_received_ts_ns > current_ts_ns

        if receipt_after_assessment:
            return TemporalInvariantStatus(
                valid=False,
                future_dated=False,
                regressed=False,
                excessive_forward_gap=False,
                local_clock_regressed=False,
                receipt_after_assessment=True,
                reason="local_receive_after_assessment_timestamp",
                veto_reason=RiskVetoReason.CLOCK_SKEW,
            )

        if local_clock_regressed:
            return TemporalInvariantStatus(
                valid=False,
                future_dated=False,
                regressed=False,
                excessive_forward_gap=False,
                local_clock_regressed=True,
                receipt_after_assessment=False,
                reason="local_clock_timestamp_regression",
                veto_reason=RiskVetoReason.CLOCK_SKEW,
            )

        if future_dated:
            return TemporalInvariantStatus(
                valid=False,
                future_dated=True,
                regressed=False,
                excessive_forward_gap=False,
                local_clock_regressed=False,
                receipt_after_assessment=False,
                reason="future_dated_exchange_timestamp",
                veto_reason=RiskVetoReason.CLOCK_SKEW,
            )

        if regressed:
            return TemporalInvariantStatus(
                valid=False,
                future_dated=False,
                regressed=True,
                excessive_forward_gap=False,
                local_clock_regressed=False,
                receipt_after_assessment=False,
                reason="exchange_timestamp_regression",
                veto_reason=RiskVetoReason.STALE_MARKET_DATA,
            )

        if excessive_forward_gap:
            return TemporalInvariantStatus(
                valid=False,
                future_dated=False,
                regressed=False,
                excessive_forward_gap=True,
                local_clock_regressed=False,
                receipt_after_assessment=False,
                reason="excessive_exchange_forward_gap",
                veto_reason=RiskVetoReason.STALE_MARKET_DATA,
            )

        return TemporalInvariantStatus(
            valid=True,
            future_dated=False,
            regressed=False,
            excessive_forward_gap=False,
            local_clock_regressed=False,
            receipt_after_assessment=False,
            reason=None,
            veto_reason=None,
        )

    def _calculate_shannon_entropy(self, deltas: np.ndarray) -> float:
        """
        Measures structural disorder of arrival intervals.
        """
        if len(deltas) < 15:
            return 0.0

        counts, _ = np.histogram(deltas, bins=10)
        total = np.sum(counts)
        if total <= 0:
            return 0.0

        probs = counts / total
        probs = probs[probs > 0]
        return float(-np.sum(probs * np.log2(probs)))

    def _calculate_skewness(self, data: np.ndarray) -> float:
        """
        Measures fat-tail asymmetry in drift distribution.
        """
        if len(data) < 20:
            return 0.0

        mu = np.mean(data)
        sigma = np.std(data)
        if sigma < 1e-9:
            return 0.0

        return float(np.mean(((data - mu) / sigma) ** 3))


__all__ = [
    "TemporalGuardConfig",
    "TemporalInput",
    "TemporalKinematics",
    "TemporalInvariantStatus",
    "TemporalRiskAssessment",
    "StaleDataGuard",
]
