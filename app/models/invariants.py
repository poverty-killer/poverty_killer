"""
System Invariant Registry and Contracts for Sovereign Trading System

This file defines:
- Invariant registry (predefined invariant definitions)
- Invariant violation event contracts
- Invariant check result contracts

This file does NOT implement invariant checking logic.
The TruthKernel and invariant checker components use these contracts.

Invariant Categories:
- Normal Invariants (I-01 through I-09): Always enforced
- Kill-Switch Invariants (KS-01 through KS-10): Trigger mode changes
- Recovery Invariants (R-01 through R-05): Crash recovery requirements
- Replay Purity Invariants (RP-01 through RP-05): Deterministic replay requirements
"""

from decimal import Decimal
from typing import Optional, List, Dict, Any
from uuid import uuid4

from pydantic import BaseModel, Field, validator, root_validator

from app.models.enums import (
    InvariantViolationSeverity, RiskMode, ResolutionType
)
from app.utils.time_utils import now_ns


# ============================================
# NORMAL INVARIANTS (I-01 through I-09)
# ============================================

class NormalInvariant(BaseModel):
    """
    Registry entry for a normal invariant.
    Actual evaluation semantics are implemented by invariant checker components.
    """
    
    id: str = Field(..., description="Invariant ID (e.g., 'I-01')")
    name: str = Field(..., description="Human-readable name")
    description: str = Field(..., description="Detailed description")
    severity: InvariantViolationSeverity = Field(
        default=InvariantViolationSeverity.WARNING,
        description="Severity when violated"
    )
    enabled: bool = Field(default=True, description="Whether this invariant is enforced")
    schema_version: int = Field(default=1)

    @validator('id')
    def validate_id_format(cls, v):
        if not v.startswith('I-'):
            raise ValueError(f"Normal invariant ID must start with 'I-', got {v}")
        return v

    @validator('schema_version')
    def validate_version(cls, v):
        if v <= 0:
            raise ValueError(f"schema_version must be positive: {v}")
        return v


# Predefined Normal Invariants
# I-01 updated to reflect action-specific truth status matrix

NORMAL_INVARIANTS = [
    NormalInvariant(
        id='I-01',
        name='Truth status per action type',
        description='New orders: require RECONCILED or DRIFTING (<5s). Cancel: allowed in RECONCILED, DRIFTING, and SAFE_MODE. Blocked in BROKEN.',
        severity=InvariantViolationSeverity.SAFE_MODE
    ),
    NormalInvariant(
        id='I-02',
        name='RiskDecision approval required',
        description='No order submission without RiskDecision approved',
        severity=InvariantViolationSeverity.SAFE_MODE
    ),
    NormalInvariant(
        id='I-03',
        name='Fill idempotence',
        description='Every fill event must be idempotent on replay',
        severity=InvariantViolationSeverity.SAFE_MODE
    ),
    NormalInvariant(
        id='I-04',
        name='No conflicting order intents',
        description='One decision_uuid may not emit multiple conflicting OrderIntents',
        severity=InvariantViolationSeverity.WARNING
    ),
    NormalInvariant(
        id='I-05',
        name='Portfolio equity consistency',
        description='Portfolio equity must equal cash + marked position value within 0.01%',
        severity=InvariantViolationSeverity.SAFE_MODE
    ),
    NormalInvariant(
        id='I-06',
        name='No stale market data',
        description='No stale market data older than max_stale_age_sec for execution',
        severity=InvariantViolationSeverity.SAFE_MODE
    ),
    NormalInvariant(
        id='I-07',
        name='Monotonic timestamps',
        description='All timestamps must be monotonic within each module',
        severity=InvariantViolationSeverity.WARNING
    ),
    NormalInvariant(
        id='I-08',
        name='Decimal precision',
        description='All monetary values must use Decimal with fixed precision (no float)',
        severity=InvariantViolationSeverity.SAFE_MODE
    ),
    NormalInvariant(
        id='I-09',
        name='Unique DecisionRecord UUID',
        description='Every DecisionRecord must have unique decision_uuid',
        severity=InvariantViolationSeverity.WARNING
    ),
]


# ============================================
# KILL-SWITCH INVARIANTS (KS-01 through KS-10)
# ============================================

class KillSwitchInvariant(BaseModel):
    """
    Registry entry for a kill-switch invariant.
    These define thresholds that trigger mode changes.
    
    Actual evaluation semantics (threshold interpretation, cooldown tracking,
    recovery logic) are implemented by invariant checker components.
    """
    
    id: str = Field(..., description="Invariant ID (e.g., 'KS-01')")
    name: str = Field(..., description="Human-readable name")
    description: str = Field(..., description="Detailed description")
    threshold_ns: Optional[int] = Field(None, description="Time threshold in nanoseconds")
    threshold_value: Optional[Decimal] = Field(None, description="Numeric threshold")
    threshold_count: Optional[int] = Field(None, description="Count threshold")
    action: RiskMode = Field(..., description="Action to take when triggered")
    auto_recover_after_ns: Optional[int] = Field(None, description="Auto-recovery time if applicable")
    requires_manual_reset: bool = Field(default=False, description="Whether manual reset is required")
    schema_version: int = Field(default=1)

    @validator('id')
    def validate_id_format(cls, v):
        if not v.startswith('KS-'):
            raise ValueError(f"Kill-switch invariant ID must start with 'KS-', got {v}")
        return v

    @validator('threshold_ns')
    def validate_threshold_ns(cls, v):
        if v is not None and v <= 0:
            raise ValueError(f"threshold_ns must be positive: {v}")
        return v

    @validator('threshold_value')
    def validate_threshold_value(cls, v):
        if v is not None and v <= 0:
            raise ValueError(f"threshold_value must be positive: {v}")
        return v

    @validator('threshold_count')
    def validate_threshold_count(cls, v):
        if v is not None and v <= 0:
            raise ValueError(f"threshold_count must be positive: {v}")
        return v

    @validator('auto_recover_after_ns')
    def validate_auto_recover(cls, v):
        if v is not None and v <= 0:
            raise ValueError(f"auto_recover_after_ns must be positive: {v}")
        return v

    @validator('schema_version')
    def validate_version(cls, v):
        if v <= 0:
            raise ValueError(f"schema_version must be positive: {v}")
        return v

    @root_validator
    def validate_auto_recover_consistency(cls, values):
        """Ensure auto_recover_after_ns and requires_manual_reset are mutually exclusive."""
        auto_recover = values.get('auto_recover_after_ns')
        requires_manual = values.get('requires_manual_reset')
        if auto_recover is not None and requires_manual:
            raise ValueError("auto_recover_after_ns cannot be set when requires_manual_reset=True")
        return values


# Predefined Kill-Switch Invariants

KILL_SWITCH_INVARIANTS = [
    KillSwitchInvariant(
        id='KS-01',
        name='Truth divergence duration',
        description='Truth divergence duration exceeds threshold',
        threshold_ns=5_000_000_000,  # 5 seconds
        action=RiskMode.SAFE_MODE,
        auto_recover_after_ns=None,
        requires_manual_reset=False
    ),
    KillSwitchInvariant(
        id='KS-02',
        name='Unmatched fill count',
        description='Unmatched fills in time window exceed threshold',
        threshold_count=3,
        threshold_ns=10_000_000_000,  # 10 seconds
        action=RiskMode.SAFE_MODE,
        auto_recover_after_ns=60_000_000_000,  # 60 seconds
        requires_manual_reset=False
    ),
    KillSwitchInvariant(
        id='KS-03',
        name='Repeated rejections',
        description='Repeated order rejections per symbol',
        threshold_count=5,
        threshold_ns=60_000_000_000,  # 60 seconds
        action=RiskMode.SAFE_MODE,
        auto_recover_after_ns=300_000_000_000,  # 300 seconds
        requires_manual_reset=False
    ),
    KillSwitchInvariant(
        id='KS-04',
        name='Clock skew',
        description='Clock skew between receive and exchange timestamps',
        threshold_ns=30_000_000_000,  # 30 seconds
        action=RiskMode.HARD_FLAT,
        requires_manual_reset=True
    ),
    KillSwitchInvariant(
        id='KS-05',
        name='Stale market data',
        description='No market data update on critical symbol',
        threshold_ns=10_000_000_000,  # 10 seconds
        action=RiskMode.SAFE_MODE,
        auto_recover_after_ns=None,
        requires_manual_reset=False
    ),
    KillSwitchInvariant(
        id='KS-06',
        name='Portfolio reconciliation mismatch',
        description='Portfolio equity vs computed equity mismatch',
        threshold_value=Decimal('0.005'),  # 0.5%
        action=RiskMode.HARD_FLAT,
        requires_manual_reset=True
    ),
    KillSwitchInvariant(
        id='KS-07',
        name='Duplicate sequence detection',
        description='Same decision_uuid + sequence processed twice',
        threshold_count=1,
        action=RiskMode.SAFE_MODE,
        auto_recover_after_ns=None,
        requires_manual_reset=False
    ),
    KillSwitchInvariant(
        id='KS-08',
        name='Write-ahead log corruption',
        description='WAL checksum mismatch',
        action=RiskMode.HARD_FLAT,
        requires_manual_reset=True
    ),
    KillSwitchInvariant(
        id='KS-09',
        name='Recovery checksum failure',
        description='Snapshot checksum mismatch',
        action=RiskMode.REPLAY_ONLY,
        requires_manual_reset=True
    ),
    KillSwitchInvariant(
        id='KS-10',
        name='Hard flat override',
        description='Manual or automatic hard flat trigger',
        action=RiskMode.HARD_FLAT,
        requires_manual_reset=True
    ),
]


# ============================================
# RECOVERY INVARIANTS (R-01 through R-05)
# ============================================

class RecoveryInvariant(BaseModel):
    """
    Registry entry for a recovery invariant.
    These define requirements for crash recovery.
    """
    
    id: str = Field(..., description="Invariant ID (e.g., 'R-01')")
    name: str = Field(..., description="Human-readable name")
    description: str = Field(..., description="Detailed description")
    required: bool = Field(default=True, description="Whether this is required")
    schema_version: int = Field(default=1)

    @validator('id')
    def validate_id_format(cls, v):
        if not v.startswith('R-'):
            raise ValueError(f"Recovery invariant ID must start with 'R-', got {v}")
        return v

    @validator('schema_version')
    def validate_version(cls, v):
        if v <= 0:
            raise ValueError(f"schema_version must be positive: {v}")
        return v


# Predefined Recovery Invariants

RECOVERY_INVARIANTS = [
    RecoveryInvariant(
        id='R-01',
        name='Restart from checkpoint',
        description='Restart after crash must load last valid RecoveryCheckpoint'
    ),
    RecoveryInvariant(
        id='R-02',
        name='WAL replay determinism',
        description='WAL replay must produce identical DecisionRecord sequence'
    ),
    RecoveryInvariant(
        id='R-03',
        name='Fill replay idempotence',
        description='Fill replay must not duplicate fills; venue_fill_id dedup required'
    ),
    RecoveryInvariant(
        id='R-04',
        name='Strategy state restoration',
        description='Strategy state machines must restore to last persisted state'
    ),
    RecoveryInvariant(
        id='R-05',
        name='Truth restoration',
        description='Last TruthFrame must be restored; divergence state preserved'
    ),
]


# ============================================
# REPLAY PURITY INVARIANTS (RP-01 through RP-05)
# ============================================

class ReplayPurityInvariant(BaseModel):
    """
    Registry entry for a replay purity invariant.
    These define requirements for deterministic replay.
    """
    
    id: str = Field(..., description="Invariant ID (e.g., 'RP-01')")
    name: str = Field(..., description="Human-readable name")
    description: str = Field(..., description="Detailed description")
    required: bool = Field(default=True, description="Whether this is required")
    schema_version: int = Field(default=1)

    @validator('id')
    def validate_id_format(cls, v):
        if not v.startswith('RP-'):
            raise ValueError(f"Replay purity invariant ID must start with 'RP-', got {v}")
        return v

    @validator('schema_version')
    def validate_version(cls, v):
        if v <= 0:
            raise ValueError(f"schema_version must be positive: {v}")
        return v


# Predefined Replay Purity Invariants

REPLAY_PURITY_INVARIANTS = [
    ReplayPurityInvariant(
        id='RP-01',
        name='No wall clock reads',
        description='now_ns() must be overridden in replay mode; no time.time_ns() calls'
    ),
    ReplayPurityInvariant(
        id='RP-02',
        name='No live network calls',
        description='All external calls must be mocked or bypassed in replay mode'
    ),
    ReplayPurityInvariant(
        id='RP-03',
        name='Deterministic randomness',
        description='All random calls must use seeded RNG in replay mode'
    ),
    ReplayPurityInvariant(
        id='RP-04',
        name='No external mutable state',
        description='No file writes except audit logs in replay mode'
    ),
    ReplayPurityInvariant(
        id='RP-05',
        name='No live price substitution',
        description='Fill prices must come from recorded data, not current market'
    ),
]


# ============================================
# VIOLATION EVENTS
# ============================================

class InvariantViolationEvent(BaseModel):
    """
    Event emitted when an invariant is violated.
    Used for monitoring, audit, and triggering mode changes.
    
    resolution_type uses the controlled ResolutionType enum.
    resolution_notes is free-form operator text for additional context.
    """
    
    violation_id: str = Field(default_factory=lambda: str(uuid4()))
    invariant_id: str = Field(..., description="Invariant ID violated")
    invariant_name: str = Field(..., description="Human-readable name")
    severity: InvariantViolationSeverity
    timestamp_ns: int = Field(default_factory=now_ns)
    observed_value: Optional[str] = Field(None, description="String representation of observed value")
    expected_value: Optional[str] = Field(None, description="String representation of expected value")
    threshold_ns: Optional[int] = Field(None, description="Threshold that was exceeded")
    threshold_value: Optional[Decimal] = Field(None, description="Numeric threshold that was exceeded")
    threshold_count: Optional[int] = Field(None, description="Count threshold that was exceeded")
    duration_ns: Optional[int] = Field(None, description="Duration of violation")
    context: Dict[str, Any] = Field(default_factory=dict, description="Additional context")
    resolution_type: ResolutionType = Field(default=ResolutionType.PENDING, description="Resolution status")
    resolution_notes: Optional[str] = Field(None, description="Free-form operator notes")
    resolved_at_ns: Optional[int] = Field(None, description="When violation was resolved")

    @validator('timestamp_ns', 'resolved_at_ns')
    def validate_timestamp(cls, v):
        if v is not None and v <= 0:
            raise ValueError(f"Timestamp must be positive: {v}")
        return v

    @validator('duration_ns')
    def validate_duration(cls, v):
        if v is not None and v < 0:
            raise ValueError(f"duration_ns cannot be negative: {v}")
        return v

    @root_validator
    def validate_resolved_after_timestamp(cls, values):
        """Ensure resolved_at_ns is after timestamp_ns when both are present."""
        timestamp_ns = values.get('timestamp_ns')
        resolved_at_ns = values.get('resolved_at_ns')
        if timestamp_ns is not None and resolved_at_ns is not None and resolved_at_ns <= timestamp_ns:
            raise ValueError("resolved_at_ns must be after timestamp_ns")
        return values

    class Config:
        use_enum_values = True


# ============================================
# INVARIANT CHECK RESULT
# ============================================

class InvariantCheckResult(BaseModel):
    """
    Result of checking a single invariant.
    Returned by invariant checker components.
    """
    
    invariant_id: str
    passed: bool
    severity: InvariantViolationSeverity
    violation: Optional[InvariantViolationEvent] = None
    message: Optional[str] = None
    timestamp_ns: int = Field(default_factory=now_ns)

    @validator('timestamp_ns')
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"timestamp_ns must be positive: {v}")
        return v

    @root_validator
    def validate_violation_consistency(cls, values):
        """Ensure violation presence matches passed flag."""
        passed = values.get('passed')
        violation = values.get('violation')
        if passed and violation is not None:
            raise ValueError("violation must be None when passed=True")
        if not passed and violation is None:
            raise ValueError("violation must be present when passed=False")
        return values


class InvariantBatchCheckResult(BaseModel):
    """
    Result of checking a batch of invariants.
    
    All fields are derived from the results list:
    - violations_count: number of results where passed=False
    - safe_mode_triggered: any violation with severity SAFE_MODE
    - hard_flat_triggered: any violation with severity HARD_FLAT
    
    These fields are computed at validation time and cannot be overridden.
    """
    
    check_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp_ns: int = Field(default_factory=now_ns)
    results: List[InvariantCheckResult] = Field(default_factory=list)
    violations_count: int = Field(default=0)
    safe_mode_triggered: bool = False
    hard_flat_triggered: bool = False

    @validator('timestamp_ns')
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError(f"timestamp_ns must be positive: {v}")
        return v

    @root_validator
    def compute_from_results(cls, values):
        """Compute violations_count and mode triggers from results."""
        results = values.get('results', [])
        
        # Count violations (passed=False)
        violations = [r for r in results if not r.passed]
        values['violations_count'] = len(violations)
        
        # Check severity for mode triggers
        values['safe_mode_triggered'] = any(
            r.severity == InvariantViolationSeverity.SAFE_MODE and not r.passed
            for r in violations
        )
        values['hard_flat_triggered'] = any(
            r.severity == InvariantViolationSeverity.HARD_FLAT and not r.passed
            for r in violations
        )
        
        return values


# ============================================
# EXPORTS
# ============================================

__all__ = [
    # Normal invariants
    'NormalInvariant',
    'NORMAL_INVARIANTS',
    # Kill-switch invariants
    'KillSwitchInvariant',
    'KILL_SWITCH_INVARIANTS',
    # Recovery invariants
    'RecoveryInvariant',
    'RECOVERY_INVARIANTS',
    # Replay purity invariants
    'ReplayPurityInvariant',
    'REPLAY_PURITY_INVARIANTS',
    # Violation events
    'InvariantViolationEvent',
    # Check results
    'InvariantCheckResult',
    'InvariantBatchCheckResult',
]
