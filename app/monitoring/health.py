"""
app/monitoring/health.py
POVERTY_KILLER — SOVEREIGN SYSTEM HEALTH AUTHORITY (CITADEL-GRADE)

This module is the canonical systemic health and heartbeat authority for the
runtime spine. It detects silent failures, heartbeat degradation, stale
components, dead components, and recovery transitions, and emits typed health
advisories suitable for unified risk, reporting, and board forensics.

ARCHITECTURAL ROLE
------------------
Owns locally:
- component registration
- heartbeat tracking
- heartbeat/error state transitions
- health evaluation
- typed health violations / advisories
- health snapshots
- mutation journaling

Does NOT own:
- execution authority
- upstream component business logic
- stale-data generation
- kill switch implementation

DESIGN PRINCIPLES
-----------------
1. Canonical and Typed
   Health outputs are structured, immutable, and schema-stable.

2. Explicit Time Preferred
   Canonical APIs use caller-supplied timestamps.

3. Compatibility Without False Truth
   If local generation time must be used in compatibility paths, snapshot quality
   is degraded explicitly rather than pretending canonical time.

4. Graduated Escalation
   Health state is not binary. Components can be healthy, degraded, stale, dead,
   recovering, disabled, or quarantined.

5. Risk Mitigation First
   Missing or stale critical components are surfaced explicitly and escalated
   conservatively.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field, replace
from decimal import Decimal
from enum import Enum, unique
from typing import Any, Dict, List, Optional, Tuple

from app.utils.enums import (
    AuthorityTier,
    InvariantViolationSeverity,
    PriorityClass,
    RiskAction,
    RiskLevel,
)

logger = logging.getLogger(__name__)


# ============================================================================
# HELPERS
# ============================================================================

def _now_ns() -> int:
    return time.time_ns()


# ============================================================================
# ENUMS
# ============================================================================

@unique
class ComponentHealthState(str, Enum):
    UNKNOWN = "UNKNOWN"
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    DEAD = "DEAD"
    RECOVERING = "RECOVERING"
    DISABLED = "DISABLED"
    QUARANTINED = "QUARANTINED"


@unique
class ComponentCriticality(str, Enum):
    CRITICAL = "CRITICAL"
    IMPORTANT = "IMPORTANT"
    OPTIONAL = "OPTIONAL"


@unique
class TimestampSource(str, Enum):
    EXPLICIT_INPUT = "EXPLICIT_INPUT"
    LOCAL_GENERATION_TIME = "LOCAL_GENERATION_TIME"


@unique
class HealthReasonCode(str, Enum):
    MISSING_COMPONENT = "MISSING_COMPONENT"
    HEARTBEAT_DEGRADED = "HEARTBEAT_DEGRADED"
    HEARTBEAT_STALE = "HEARTBEAT_STALE"
    HEARTBEAT_DEAD = "HEARTBEAT_DEAD"
    ERROR_COUNT_ELEVATED = "ERROR_COUNT_ELEVATED"
    COMPONENT_RECOVERED = "COMPONENT_RECOVERED"
    COMPONENT_DISABLED = "COMPONENT_DISABLED"
    COMPONENT_QUARANTINED = "COMPONENT_QUARANTINED"
    NOMINAL = "NOMINAL"
    DEGRADED_MARKET_DATA = "DEGRADED_MARKET_DATA"
    REST_DNS_FAILURE = "REST_DNS_FAILURE"
    MARKET_DATA_PARTIAL_TRUTH = "MARKET_DATA_PARTIAL_TRUTH"


@unique
class HealthTransitionType(str, Enum):
    INITIAL = "INITIAL"
    ESCALATION = "ESCALATION"
    RELAXATION = "RELAXATION"
    LATERAL = "LATERAL"


# ============================================================================
# LEGACY MODEL (PRESERVED)
# ============================================================================

@dataclass
class ComponentStatus:
    """
    Legacy-compatible mutable component state record.
    """
    name: str
    last_heartbeat_ns: int
    is_active: bool
    error_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


# ============================================================================
# CANONICAL MODELS
# ============================================================================

@dataclass(frozen=True, slots=True)
class HealthPolicyConfig:
    default_stale_threshold_ms: int = 2000
    dead_multiplier: int = 3
    degraded_ratio: Decimal = Decimal("0.5")
    elevated_error_count: int = 5
    journal_capacity: int = 50000

    def __post_init__(self) -> None:
        if self.default_stale_threshold_ms <= 0:
            raise ValueError("default_stale_threshold_ms must be > 0")
        if self.dead_multiplier < 1:
            raise ValueError("dead_multiplier must be >= 1")
        if self.degraded_ratio <= 0 or self.degraded_ratio >= 1:
            raise ValueError("degraded_ratio must be in (0,1)")
        if self.elevated_error_count < 0:
            raise ValueError("elevated_error_count must be >= 0")
        if self.journal_capacity < 100:
            raise ValueError("journal_capacity must be >= 100")


@dataclass(frozen=True, slots=True)
class RegisteredComponent:
    name: str
    criticality: ComponentCriticality
    stale_threshold_ns: int
    enabled: bool = True
    expected: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ComponentHealthRecord:
    name: str
    criticality: ComponentCriticality
    state: ComponentHealthState
    last_heartbeat_ns: int
    last_transition_ns: int
    error_count: int
    metadata: Dict[str, Any]
    stale_threshold_ns: int
    heartbeat_count: int
    missed_evaluations: int
    timestamp_source: TimestampSource
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class HealthViolation:
    component: str
    hazard_level: RiskLevel
    severity: InvariantViolationSeverity
    risk_action: RiskAction
    authority_tier: AuthorityTier
    priority: PriorityClass
    reason: str
    reason_code: HealthReasonCode
    timestamp_ns: int
    state: ComponentHealthState
    criticality: ComponentCriticality
    drift_ns: int
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_legacy_dict(self) -> Dict[str, Any]:
        return {
            "component": self.component,
            "severity": self.severity,
            "issue": self.reason,
            "timestamp_ns": self.timestamp_ns,
        }


@dataclass(frozen=True, slots=True)
class HealthSnapshot:
    timestamp_ns: int
    timestamp_source: TimestampSource
    healthy: bool
    quality: str
    registered_components: int
    active_components: int
    violations_count: int
    components: Dict[str, Dict[str, Any]]


@dataclass(frozen=True, slots=True)
class HealthJournalRecord:
    sequence: int
    timestamp_ns: int
    component: Optional[str]
    event: str
    state: Optional[ComponentHealthState]
    payload: Dict[str, Any] = field(default_factory=dict)


# ============================================================================
# ENGINE
# ============================================================================

class HealthMonitor:
    """
    Sovereign Health Authority.
    """

    def __init__(self, stale_threshold_ms: int = 2000):
        self.policy = HealthPolicyConfig(default_stale_threshold_ms=stale_threshold_ms)
        self.stale_threshold_ns = self.policy.default_stale_threshold_ms * 1_000_000

        self._registry: Dict[str, RegisteredComponent] = {}
        self._components: Dict[str, ComponentHealthRecord] = {}

        self._journal: List[HealthJournalRecord] = []
        self._journal_seq = 0
        self._version = 0

    # ------------------------------------------------------------------
    # Registration / state management
    # ------------------------------------------------------------------

    def register_component(
        self,
        component_name: str,
        *,
        criticality: ComponentCriticality = ComponentCriticality.IMPORTANT,
        stale_threshold_ms: Optional[int] = None,
        enabled: bool = True,
        expected: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not component_name:
            raise ValueError("component_name must be non-empty")

        stale_ns = (stale_threshold_ms if stale_threshold_ms is not None else self.policy.default_stale_threshold_ms) * 1_000_000
        registry_entry = RegisteredComponent(
            name=component_name,
            criticality=criticality,
            stale_threshold_ns=stale_ns,
            enabled=enabled,
            expected=expected,
            metadata=dict(metadata or {}),
        )
        self._registry[component_name] = registry_entry

        if component_name not in self._components:
            self._components[component_name] = ComponentHealthRecord(
                name=component_name,
                criticality=criticality,
                state=ComponentHealthState.UNKNOWN if enabled else ComponentHealthState.DISABLED,
                last_heartbeat_ns=0,
                last_transition_ns=0,
                error_count=0,
                metadata=dict(metadata or {}),
                stale_threshold_ns=stale_ns,
                heartbeat_count=0,
                missed_evaluations=0,
                timestamp_source=TimestampSource.EXPLICIT_INPUT,
                enabled=enabled,
            )

        self._bump_version()
        self._append_journal(
            component=component_name,
            event="REGISTERED",
            state=self._components[component_name].state,
            payload={"criticality": criticality.value, "enabled": enabled, "expected": expected},
        )

    def set_component_enabled(self, component_name: str, enabled: bool, *, ts_ns: Optional[int] = None) -> None:
        if component_name not in self._components:
            self.register_component(component_name, enabled=enabled)

        ts_ns = _now_ns() if ts_ns is None else ts_ns
        comp = self._components[component_name]
        new_state = ComponentHealthState.DISABLED if not enabled else ComponentHealthState.UNKNOWN
        self._components[component_name] = replace(
            comp,
            enabled=enabled,
            state=new_state,
            last_transition_ns=ts_ns,
        )
        if component_name in self._registry:
            reg = self._registry[component_name]
            self._registry[component_name] = replace(reg, enabled=enabled)

        self._bump_version()
        self._append_journal(
            component=component_name,
            event="ENABLED_STATE_CHANGED",
            state=new_state,
            payload={"enabled": enabled},
        )

    def quarantine_component(self, component_name: str, *, ts_ns: Optional[int] = None, reason: str = "QUARANTINED") -> None:
        if component_name not in self._components:
            self.register_component(component_name)

        ts_ns = _now_ns() if ts_ns is None else ts_ns
        comp = self._components[component_name]
        self._components[component_name] = replace(
            comp,
            state=ComponentHealthState.QUARANTINED,
            last_transition_ns=ts_ns,
        )
        self._bump_version()
        self._append_journal(
            component=component_name,
            event="QUARANTINED",
            state=ComponentHealthState.QUARANTINED,
            payload={"reason": reason},
        )

    # ------------------------------------------------------------------
    # Heartbeat / error APIs
    # ------------------------------------------------------------------

    def pulse(self, component_name: str, ts_ns: int, metadata: Optional[Dict[str, Any]] = None):
        """
        Legacy-compatible heartbeat path.
        """
        self.pulse_canonical(
            component_name=component_name,
            ts_ns=ts_ns,
            metadata=metadata,
            timestamp_source=TimestampSource.EXPLICIT_INPUT,
        )

    def pulse_canonical(
        self,
        *,
        component_name: str,
        ts_ns: int,
        metadata: Optional[Dict[str, Any]] = None,
        timestamp_source: TimestampSource = TimestampSource.EXPLICIT_INPUT,
    ) -> None:
        if ts_ns <= 0:
            raise ValueError("ts_ns must be positive")

        if component_name not in self._components:
            self.register_component(component_name)

        comp = self._components[component_name]
        prior_state = comp.state

        if comp.state in {ComponentHealthState.STALE, ComponentHealthState.DEAD, ComponentHealthState.QUARANTINED, ComponentHealthState.UNKNOWN}:
            next_state = ComponentHealthState.RECOVERING if comp.enabled else ComponentHealthState.DISABLED
        else:
            next_state = ComponentHealthState.HEALTHY if comp.enabled else ComponentHealthState.DISABLED

        merged_metadata = dict(comp.metadata)
        if metadata:
            merged_metadata.update(metadata)

        self._components[component_name] = replace(
            comp,
            last_heartbeat_ns=ts_ns,
            state=next_state,
            last_transition_ns=ts_ns if next_state != prior_state else comp.last_transition_ns,
            metadata=merged_metadata,
            heartbeat_count=comp.heartbeat_count + 1,
            missed_evaluations=0,
            timestamp_source=timestamp_source,
        )

        self._bump_version()
        self._append_journal(
            component=component_name,
            event="PULSE",
            state=next_state,
            payload={"timestamp_source": timestamp_source.value},
        )

    def record_error(
        self,
        component_name: str,
        *,
        ts_ns: int,
        error_message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        if ts_ns <= 0:
            raise ValueError("ts_ns must be positive")

        if component_name not in self._components:
            self.register_component(component_name)

        comp = self._components[component_name]
        merged_metadata = dict(comp.metadata)
        if metadata:
            merged_metadata.update(metadata)
        if error_message:
            merged_metadata["last_error"] = error_message
            merged_metadata["last_error_ts_ns"] = ts_ns

        self._components[component_name] = replace(
            comp,
            error_count=comp.error_count + 1,
            metadata=merged_metadata,
        )

        self._bump_version()
        self._append_journal(
            component=component_name,
            event="ERROR_RECORDED",
            state=comp.state,
            payload={"error_message": error_message},
        )

    def record_market_data_truth(
        self,
        *,
        component_name: str,
        ts_ns: int,
        feed_truth: Dict[str, Any],
        criticality: ComponentCriticality = ComponentCriticality.IMPORTANT,
    ) -> None:
        """Record structured market-data truth without generating market data."""
        if ts_ns <= 0:
            raise ValueError("ts_ns must be positive")
        if component_name not in self._components:
            self.register_component(component_name, criticality=criticality)

        status = str(feed_truth.get("status", "UNKNOWN"))
        metadata = {
            "feed_truth_status": status,
            "market_truth": feed_truth.get("market_truth"),
            "missing_truth": tuple(feed_truth.get("missing_truth", ())),
        }
        self.pulse_canonical(
            component_name=component_name,
            ts_ns=ts_ns,
            metadata=metadata,
            timestamp_source=TimestampSource.EXPLICIT_INPUT,
        )
        if status in {"WEBSOCKET_ACTIVE_REST_DNS_FAILED", "REST_POLLING_DEGRADED"}:
            self.record_error(
                component_name,
                ts_ns=ts_ns,
                error_message=status,
                metadata={
                    "reason_code": (
                        HealthReasonCode.REST_DNS_FAILURE.value
                        if status == "WEBSOCKET_ACTIVE_REST_DNS_FAILED"
                        else HealthReasonCode.DEGRADED_MARKET_DATA.value
                    ),
                    **metadata,
                },
            )

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def evaluate_system_health(self, current_ts_ns: int) -> List[Dict[str, Any]]:
        """
        Legacy-compatible violation projection.
        """
        return [v.to_legacy_dict() for v in self.evaluate_system_health_canonical(current_ts_ns=current_ts_ns)]

    def evaluate_system_health_canonical(self, *, current_ts_ns: int) -> List[HealthViolation]:
        if current_ts_ns <= 0:
            raise ValueError("current_ts_ns must be positive")

        violations: List[HealthViolation] = []

        for name, comp in list(self._components.items()):
            reg = self._registry.get(name)

            if reg is None:
                reg = RegisteredComponent(
                    name=name,
                    criticality=ComponentCriticality.IMPORTANT,
                    stale_threshold_ns=self.stale_threshold_ns,
                )

            if not comp.enabled:
                continue

            if comp.last_heartbeat_ns <= 0:
                if reg.expected:
                    violation = self._build_violation(
                        component=comp,
                        current_ts_ns=current_ts_ns,
                        drift_ns=0,
                        state=ComponentHealthState.UNKNOWN,
                        reason="expected_component_missing_heartbeat",
                        reason_code=HealthReasonCode.MISSING_COMPONENT,
                    )
                    violations.append(violation)
                continue

            drift = current_ts_ns - comp.last_heartbeat_ns
            degraded_threshold = int(reg.stale_threshold_ns * float(self.policy.degraded_ratio))
            dead_threshold = reg.stale_threshold_ns * self.policy.dead_multiplier

            new_state = comp.state
            violation: Optional[HealthViolation] = None

            if comp.state == ComponentHealthState.QUARANTINED:
                violation = self._build_violation(
                    component=comp,
                    current_ts_ns=current_ts_ns,
                    drift_ns=drift,
                    state=ComponentHealthState.QUARANTINED,
                    reason="component_quarantined",
                    reason_code=HealthReasonCode.COMPONENT_QUARANTINED,
                )

            elif drift >= dead_threshold:
                new_state = ComponentHealthState.DEAD
                violation = self._build_violation(
                    component=comp,
                    current_ts_ns=current_ts_ns,
                    drift_ns=drift,
                    state=new_state,
                    reason=f"heartbeat_dead:{drift/1e6:.2f}ms_drift",
                    reason_code=HealthReasonCode.HEARTBEAT_DEAD,
                )

            elif drift >= reg.stale_threshold_ns:
                new_state = ComponentHealthState.STALE
                violation = self._build_violation(
                    component=comp,
                    current_ts_ns=current_ts_ns,
                    drift_ns=drift,
                    state=new_state,
                    reason=f"heartbeat_stale:{drift/1e6:.2f}ms_drift",
                    reason_code=HealthReasonCode.HEARTBEAT_STALE,
                )

            elif drift >= degraded_threshold:
                new_state = ComponentHealthState.DEGRADED
                violation = self._build_violation(
                    component=comp,
                    current_ts_ns=current_ts_ns,
                    drift_ns=drift,
                    state=new_state,
                    reason=f"heartbeat_degraded:{drift/1e6:.2f}ms_drift",
                    reason_code=HealthReasonCode.HEARTBEAT_DEGRADED,
                )

            elif comp.error_count >= self.policy.elevated_error_count:
                new_state = ComponentHealthState.DEGRADED
                violation = self._build_violation(
                    component=comp,
                    current_ts_ns=current_ts_ns,
                    drift_ns=drift,
                    state=new_state,
                    reason=f"error_count_elevated:{comp.error_count}",
                    reason_code=HealthReasonCode.ERROR_COUNT_ELEVATED,
                )

            else:
                if comp.state == ComponentHealthState.RECOVERING:
                    new_state = ComponentHealthState.HEALTHY
                elif comp.state in {ComponentHealthState.UNKNOWN, ComponentHealthState.DEGRADED}:
                    new_state = ComponentHealthState.HEALTHY

            if new_state != comp.state:
                self._components[name] = replace(
                    comp,
                    state=new_state,
                    last_transition_ns=current_ts_ns,
                    missed_evaluations=(comp.missed_evaluations + 1) if new_state in {ComponentHealthState.DEGRADED, ComponentHealthState.STALE, ComponentHealthState.DEAD} else 0,
                )
                self._append_journal(
                    component=name,
                    event="STATE_TRANSITION",
                    state=new_state,
                    payload={"prior_state": comp.state.value, "drift_ns": drift},
                )
                self._bump_version()
            else:
                if new_state in {ComponentHealthState.DEGRADED, ComponentHealthState.STALE, ComponentHealthState.DEAD}:
                    self._components[name] = replace(
                        comp,
                        missed_evaluations=comp.missed_evaluations + 1,
                    )

            if violation is not None:
                violations.append(violation)

        return violations

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    def get_snapshot(self) -> Dict[str, Any]:
        """
        Legacy-compatible snapshot.

        Uses local generation time because legacy signature does not accept an
        explicit timestamp. The returned quality is therefore degraded.
        """
        snap = self.get_snapshot_canonical(
            current_ts_ns=_now_ns(),
            timestamp_source=TimestampSource.LOCAL_GENERATION_TIME,
        )
        return asdict(snap)

    def get_snapshot_canonical(
        self,
        *,
        current_ts_ns: int,
        timestamp_source: TimestampSource = TimestampSource.EXPLICIT_INPUT,
    ) -> HealthSnapshot:
        if current_ts_ns <= 0:
            raise ValueError("current_ts_ns must be positive")

        violations = self.evaluate_system_health_canonical(current_ts_ns=current_ts_ns)
        active_components = sum(
            1 for c in self._components.values()
            if c.enabled and c.state in {ComponentHealthState.HEALTHY, ComponentHealthState.RECOVERING}
        )

        quality = "LIVE" if timestamp_source == TimestampSource.EXPLICIT_INPUT else "DEGRADED"

        components_blob = {
            name: {
                "name": comp.name,
                "criticality": comp.criticality.value,
                "state": comp.state.value,
                "last_heartbeat_ns": comp.last_heartbeat_ns,
                "last_transition_ns": comp.last_transition_ns,
                "error_count": comp.error_count,
                "metadata": comp.metadata,
                "stale_threshold_ns": comp.stale_threshold_ns,
                "heartbeat_count": comp.heartbeat_count,
                "missed_evaluations": comp.missed_evaluations,
                "timestamp_source": comp.timestamp_source.value,
                "enabled": comp.enabled,
            }
            for name, comp in self._components.items()
        }

        healthy = not any(
            v.severity in {
                InvariantViolationSeverity.HARD_FLAT,
                InvariantViolationSeverity.SAFE_MODE,
            }
            for v in violations
        )

        return HealthSnapshot(
            timestamp_ns=current_ts_ns,
            timestamp_source=timestamp_source,
            healthy=healthy,
            quality=quality,
            registered_components=len(self._registry),
            active_components=active_components,
            violations_count=len(violations),
            components=components_blob,
        )

    # ------------------------------------------------------------------
    # Journaling / helpers
    # ------------------------------------------------------------------

    def journal(self, limit: Optional[int] = None) -> List[HealthJournalRecord]:
        if limit is None or limit >= len(self._journal):
            return list(self._journal)
        return self._journal[-limit:]

    def _build_violation(
        self,
        *,
        component: ComponentHealthRecord,
        current_ts_ns: int,
        drift_ns: int,
        state: ComponentHealthState,
        reason: str,
        reason_code: HealthReasonCode,
    ) -> HealthViolation:
        if component.criticality == ComponentCriticality.CRITICAL:
            if state == ComponentHealthState.DEAD:
                return HealthViolation(
                    component=component.name,
                    hazard_level=RiskLevel.VETO,
                    severity=InvariantViolationSeverity.HARD_FLAT,
                    risk_action=RiskAction.BLOCK_ALL_NEW,
                    authority_tier=AuthorityTier.HARD_BLOCK,
                    priority=PriorityClass.REALTIME,
                    reason=reason,
                    reason_code=reason_code,
                    timestamp_ns=current_ts_ns,
                    state=state,
                    criticality=component.criticality,
                    drift_ns=drift_ns,
                    metadata=component.metadata,
                )
            if state == ComponentHealthState.STALE:
                return HealthViolation(
                    component=component.name,
                    hazard_level=RiskLevel.CRITICAL,
                    severity=InvariantViolationSeverity.SAFE_MODE,
                    risk_action=RiskAction.SAFE_MODE,
                    authority_tier=AuthorityTier.SOFT_BLOCK,
                    priority=PriorityClass.URGENT,
                    reason=reason,
                    reason_code=reason_code,
                    timestamp_ns=current_ts_ns,
                    state=state,
                    criticality=component.criticality,
                    drift_ns=drift_ns,
                    metadata=component.metadata,
                )

        if state in {ComponentHealthState.DEGRADED, ComponentHealthState.STALE, ComponentHealthState.DEAD}:
            return HealthViolation(
                component=component.name,
                hazard_level=RiskLevel.HIGH,
                severity=InvariantViolationSeverity.WARNING,
                risk_action=RiskAction.THROTTLE,
                authority_tier=AuthorityTier.ADVISORY,
                priority=PriorityClass.NORMAL,
                reason=reason,
                reason_code=reason_code,
                timestamp_ns=current_ts_ns,
                state=state,
                criticality=component.criticality,
                drift_ns=drift_ns,
                metadata=component.metadata,
            )

        return HealthViolation(
            component=component.name,
            hazard_level=RiskLevel.NONE,
            severity=InvariantViolationSeverity.ADVISORY,
            risk_action=RiskAction.ADVISE,
            authority_tier=AuthorityTier.ADVISORY,
            priority=PriorityClass.DEFERRED,
            reason=reason,
            reason_code=reason_code,
            timestamp_ns=current_ts_ns,
            state=state,
            criticality=component.criticality,
            drift_ns=drift_ns,
            metadata=component.metadata,
        )

    def _append_journal(
        self,
        *,
        component: Optional[str],
        event: str,
        state: Optional[ComponentHealthState],
        payload: Dict[str, Any],
    ) -> None:
        self._journal_seq += 1
        self._journal.append(
            HealthJournalRecord(
                sequence=self._journal_seq,
                timestamp_ns=_now_ns(),
                component=component,
                event=event,
                state=state,
                payload=payload,
            )
        )
        if len(self._journal) > self.policy.journal_capacity:
            self._journal = self._journal[-self.policy.journal_capacity:]

    def _bump_version(self) -> None:
        self._version += 1


__all__ = [
    "ComponentHealthState",
    "ComponentCriticality",
    "TimestampSource",
    "HealthReasonCode",
    "HealthTransitionType",
    "ComponentStatus",
    "HealthPolicyConfig",
    "RegisteredComponent",
    "ComponentHealthRecord",
    "HealthViolation",
    "HealthSnapshot",
    "HealthJournalRecord",
    "HealthMonitor",
]
