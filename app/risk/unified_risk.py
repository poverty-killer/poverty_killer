"""
app/risk/unified_risk.py
POVERTY_KILLER — SOVEREIGN RISK CONSTITUTION (FINAL-FORM CITADEL-GRADE)

This module is the canonical constitutional risk authority for the platform.
It unifies portfolio, symbol, sleeve, market-data, divergence, kill-switch,
system-health, and request-intent signals into deterministic, replay-safe,
auditable policy decisions.

This file is a bounded constitutional consolidation layer.
It does not regenerate upstream truths such as stale-data detection,
divergence generation, kill-switch implementation, or exposure accounting.
It consumes those already-produced truths and emits coherent constitutional
policy outputs.

CONSTITUTIONAL ROLE
-------------------
Owns locally:
- unified policy evaluation
- directive emission
- multi-scope constitutional result production
- decision validity horizon fields
- bounded hysteresis / transition tracking
- bounded override governance interpretation
- decision journaling / transition tracking

Does NOT own:
- kill switch implementation
- stale data generation
- divergence generation
- exposure accounting
- execution authority

MIGRATION SEAM
--------------
This module intentionally preserves two surfaces:

1. Legacy compatibility surface:
   - UnifiedRiskDecision
   - UnifiedRiskResult
   - evaluate(...)
   - evaluate_for_symbol(...)
   - quick_check(...)

2. Rich constitutional surface:
   - evaluate_constitution(...)
   - CanonicalUnifiedRiskResult
   - SovereignRiskConstitutionResult
   - supporting constitutional models

The legacy evaluate(...) path is a compatibility adapter / projection from the
constitutional evaluation path. It is NOT a second independent risk engine.

UPSTREAM BLOCK CONTRACT
-----------------------
This authority consumes already-active upstream block objects for stale-data and
divergence control. Upstream producers are responsible for determining whether a
block is active / expired / valid for use. This module does not rebuild stale or
divergence truth internally.

QUICK-CHECK CONTRACT
--------------------
quick_check(...) is intentionally narrow.
It is ONLY a preflight blocker shortcut for obvious deny conditions
(kill switch, hard-flat, symbol stale/divergence block when provided).
It is NOT the constitutional authority path and intentionally ignores many
degraded, scoped, and constitutional conditions. Callers that need a real risk
decision MUST use evaluate(...) or evaluate_constitution(...).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_DOWN, getcontext
from enum import Enum, IntEnum, unique
from typing import Any, Dict, List, Optional, Sequence, Tuple

getcontext().prec = 28

from app.models.enums import RiskMode, RegimeType
from app.models.contracts import DivergenceBlock, StaleDataBlock
from app.risk.kill_switch import KillSwitch

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


def _ensure_unit_interval(value: Decimal, field_name: str) -> Decimal:
    if value < ZERO or value > ONE:
        raise ValueError(f"{field_name} must be in [0,1], got {value}")
    return value


def _quantize_ratio(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"), rounding=ROUND_DOWN)


def _enum_value(x: Any) -> str:
    return x.value if hasattr(x, "value") else str(x)


def _min_nonzero(a: int, b: int) -> int:
    if a <= 0:
        return b
    if b <= 0:
        return a
    return min(a, b)


# ============================================================================
# LEGACY ENUMS / CONTRACTS (PRESERVED)
# ============================================================================

@unique
class UnifiedRiskDecision(str, Enum):
    HARD_DENY = "hard_deny"
    DEGRADED_ALLOW = "degraded_allow"
    FULL_ALLOW = "full_allow"


@dataclass(frozen=True)
class UnifiedRiskResult:
    decision: UnifiedRiskDecision
    allowed: bool
    sizing_multiplier: Decimal
    risk_mode: RiskMode
    reason: str
    provenance: Dict[str, Any] = field(default_factory=dict)
    timestamp_ns: int = 0

    def __post_init__(self):
        if isinstance(self.sizing_multiplier, Decimal):
            quantized = self.sizing_multiplier.quantize(Decimal("0.0001"))
            object.__setattr__(self, "sizing_multiplier", quantized)

        if self.sizing_multiplier < Decimal("0") or self.sizing_multiplier > Decimal("1"):
            raise ValueError(f"sizing_multiplier must be in [0,1], got {self.sizing_multiplier}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision.value,
            "allowed": self.allowed,
            "sizing_multiplier": str(self.sizing_multiplier),
            "risk_mode": self.risk_mode.value if hasattr(self.risk_mode, "value") else str(self.risk_mode),
            "reason": self.reason,
            "provenance": self.provenance,
            "timestamp_ns": self.timestamp_ns,
        }


# ============================================================================
# CONSTITUTIONAL ENUMS
# ============================================================================

@unique
class UnifiedRiskDirective(str, Enum):
    ALLOW = "ALLOW"
    ALLOW_REDUCED = "ALLOW_REDUCED"
    REDUCE_ONLY = "REDUCE_ONLY"
    HEDGE_ONLY = "HEDGE_ONLY"
    BLOCK_NEW_LONG = "BLOCK_NEW_LONG"
    BLOCK_NEW_SHORT = "BLOCK_NEW_SHORT"
    BLOCK_ALL_NEW = "BLOCK_ALL_NEW"
    FORCE_DELEVER = "FORCE_DELEVER"
    FORCE_FLAT = "FORCE_FLAT"
    TERMINAL_DENY = "TERMINAL_DENY"


@unique
class UnifiedRiskScope(str, Enum):
    GLOBAL = "GLOBAL"
    PORTFOLIO = "PORTFOLIO"
    SLEEVE = "SLEEVE"
    SYMBOL = "SYMBOL"
    REQUEST = "REQUEST"
    DIRECTION_LONG = "DIRECTION_LONG"
    DIRECTION_SHORT = "DIRECTION_SHORT"


@unique
class UnifiedRiskFactor(str, Enum):
    KILL_SWITCH = "KILL_SWITCH"
    HARD_FLAT = "HARD_FLAT"
    STALE_DATA = "STALE_DATA"
    DIVERGENCE = "DIVERGENCE"
    TOXICITY = "TOXICITY"
    EXPOSURE = "EXPOSURE"
    CONCENTRATION = "CONCENTRATION"
    REGIME = "REGIME"
    SYSTEM_HEALTH = "SYSTEM_HEALTH"
    RECOVERY = "RECOVERY"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"


@unique
class UnifiedRiskReasonCode(str, Enum):
    KILL_SWITCH_ACTIVE = "KILL_SWITCH_ACTIVE"
    HARD_FLAT_ACTIVE = "HARD_FLAT_ACTIVE"
    STALE_DATA_BLOCK = "STALE_DATA_BLOCK"
    DIVERGENCE_BLOCK = "DIVERGENCE_BLOCK"
    EXTREME_TOXICITY = "EXTREME_TOXICITY"
    ELEVATED_TOXICITY = "ELEVATED_TOXICITY"
    EXTREME_EXPOSURE = "EXTREME_EXPOSURE"
    ELEVATED_EXPOSURE = "ELEVATED_EXPOSURE"
    EXTREME_CONCENTRATION = "EXTREME_CONCENTRATION"
    ELEVATED_CONCENTRATION = "ELEVATED_CONCENTRATION"
    CRISIS_REGIME = "CRISIS_REGIME"
    UNKNOWN_REGIME = "UNKNOWN_REGIME"
    DEGRADED_SYSTEM_HEALTH = "DEGRADED_SYSTEM_HEALTH"
    RECOVERY_AMBIGUITY = "RECOVERY_AMBIGUITY"
    MANUAL_OVERRIDE_APPLIED = "MANUAL_OVERRIDE_APPLIED"
    NOMINAL = "NOMINAL"


@unique
class EvaluationCompleteness(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    DEGRADED = "DEGRADED"
    AMBIGUOUS = "AMBIGUOUS"


@unique
class SourceHealth(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


@unique
class RiskOverrideAction(str, Enum):
    NONE = "NONE"
    FORCE_ALLOW_REDUCED = "FORCE_ALLOW_REDUCED"
    FORCE_HEDGE_ONLY = "FORCE_HEDGE_ONLY"
    FORCE_REDUCE_ONLY = "FORCE_REDUCE_ONLY"
    FORCE_BLOCK_ALL_NEW = "FORCE_BLOCK_ALL_NEW"
    FORCE_TERMINAL_DENY = "FORCE_TERMINAL_DENY"


@unique
class RiskTransitionType(str, Enum):
    INITIAL = "INITIAL"
    ESCALATION = "ESCALATION"
    RELAXATION = "RELAXATION"
    LATERAL = "LATERAL"


class UnifiedRiskPrecedence(IntEnum):
    TERMINAL = 100
    HARD_FLAT = 90
    STALE_OR_DIVERGENCE = 80
    EXTREME_TOXICITY = 70
    EXTREME_EXPOSURE = 65
    EXTREME_CONCENTRATION = 60
    DEGRADED_SYSTEM_HEALTH = 55
    RECOVERY_AMBIGUITY = 52
    ELEVATED_TOXICITY = 40
    ELEVATED_EXPOSURE = 35
    ELEVATED_CONCENTRATION = 30
    UNFAVORABLE_REGIME = 20
    MANUAL_OVERRIDE = 15
    NOMINAL = 0


# ============================================================================
# STRUCTURED INPUTS
# ============================================================================

@dataclass(frozen=True, slots=True)
class UnifiedRiskPolicyConfig:
    toxicity_hard_deny_threshold: Decimal = Decimal("0.9")
    toxicity_degrade_threshold: Decimal = Decimal("0.7")
    exposure_hard_deny_threshold: Decimal = Decimal("0.95")
    exposure_degrade_threshold: Decimal = Decimal("0.8")
    concentration_hard_deny_threshold: Decimal = Decimal("0.35")
    concentration_degrade_threshold: Decimal = Decimal("0.25")

    crisis_multiplier: Decimal = Decimal("0.3")
    unknown_regime_multiplier: Decimal = Decimal("0.5")
    degraded_system_multiplier: Decimal = Decimal("0.5")
    ambiguous_recovery_multiplier: Decimal = Decimal("0.4")

    exposure_reduce_only_threshold: Decimal = Decimal("0.90")
    exposure_hedge_only_threshold: Decimal = Decimal("0.85")
    toxicity_reduce_only_threshold: Decimal = Decimal("0.85")

    use_hysteresis: bool = True
    hysteresis_improve_multiplier: Decimal = Decimal("1.15")
    min_reevaluate_interval_ns: int = 5_000_000
    journal_capacity: int = 50_000

    def __post_init__(self) -> None:
        unit_interval_fields = [
            "toxicity_hard_deny_threshold",
            "toxicity_degrade_threshold",
            "exposure_hard_deny_threshold",
            "exposure_degrade_threshold",
            "concentration_hard_deny_threshold",
            "concentration_degrade_threshold",
            "crisis_multiplier",
            "unknown_regime_multiplier",
            "degraded_system_multiplier",
            "ambiguous_recovery_multiplier",
            "exposure_reduce_only_threshold",
            "exposure_hedge_only_threshold",
            "toxicity_reduce_only_threshold",
        ]
        for name in unit_interval_fields:
            object.__setattr__(self, name, _ensure_unit_interval(_d(getattr(self, name), field_name=name), name))

        hysteresis_improve_multiplier = _d(
            self.hysteresis_improve_multiplier,
            field_name="hysteresis_improve_multiplier",
        )
        if hysteresis_improve_multiplier <= ZERO:
            raise ValueError("hysteresis_improve_multiplier must be > 0")
        object.__setattr__(self, "hysteresis_improve_multiplier", hysteresis_improve_multiplier)

        if self.journal_capacity < 100:
            raise ValueError("journal_capacity must be >= 100")
        if self.min_reevaluate_interval_ns < 0:
            raise ValueError("min_reevaluate_interval_ns must be >= 0")


@dataclass(frozen=True, slots=True)
class UnifiedRiskSourceStatus:
    stale_data_health: SourceHealth = SourceHealth.HEALTHY
    divergence_health: SourceHealth = SourceHealth.HEALTHY
    exposure_health: SourceHealth = SourceHealth.HEALTHY
    toxicity_health: SourceHealth = SourceHealth.HEALTHY
    orchestrator_health: SourceHealth = SourceHealth.HEALTHY
    persistence_health: SourceHealth = SourceHealth.HEALTHY


@dataclass(frozen=True, slots=True)
class UnifiedExposureContext:
    effective_utilization: Decimal = Decimal("0")
    raw_net_exposure: Decimal = Decimal("0")
    residual_net_exposure: Decimal = Decimal("0")
    hedge_overlay_exposure: Decimal = Decimal("0")
    concentration_pct: Decimal = Decimal("0")
    snapshot_quality: str = "LIVE"
    reconciliation_attribution_loss: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "effective_utilization", _ensure_unit_interval(_d(self.effective_utilization, field_name="effective_utilization"), "effective_utilization"))
        object.__setattr__(self, "concentration_pct", _ensure_unit_interval(_d(self.concentration_pct, field_name="concentration_pct"), "concentration_pct"))
        object.__setattr__(self, "raw_net_exposure", _d(self.raw_net_exposure, field_name="raw_net_exposure"))
        object.__setattr__(self, "residual_net_exposure", _d(self.residual_net_exposure, field_name="residual_net_exposure"))
        object.__setattr__(self, "hedge_overlay_exposure", _d(self.hedge_overlay_exposure, field_name="hedge_overlay_exposure"))


@dataclass(frozen=True, slots=True)
class UnifiedSleeveContext:
    sleeve_name: Optional[str] = None
    sleeve_utilization: Decimal = Decimal("0")
    sleeve_drawdown_pct: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        object.__setattr__(self, "sleeve_utilization", _ensure_unit_interval(_d(self.sleeve_utilization, field_name="sleeve_utilization"), "sleeve_utilization"))
        object.__setattr__(self, "sleeve_drawdown_pct", _ensure_unit_interval(_d(self.sleeve_drawdown_pct, field_name="sleeve_drawdown_pct"), "sleeve_drawdown_pct"))


@dataclass(frozen=True, slots=True)
class UnifiedRecoveryContext:
    recovering: bool = False
    ambiguity_active: bool = False
    ambiguity_reason: Optional[str] = None


@dataclass(frozen=True, slots=True)
class UnifiedSystemHealthContext:
    infra_degraded: bool = False
    router_degraded: bool = False
    persistence_degraded: bool = False


@dataclass(frozen=True, slots=True)
class UnifiedRiskOverride:
    """
    Bounded override contract.

    Scope is a constitutional semantic label. Whether that scope can be fully
    operationalized by all current downstream consumers depends on the live
    architecture. This module interprets and journals overrides; downstream
    consumers remain responsible for honoring scope semantics they support.
    """
    action: RiskOverrideAction = RiskOverrideAction.NONE
    scope: UnifiedRiskScope = UnifiedRiskScope.GLOBAL
    reason: str = ""
    issuer: str = "UNKNOWN"
    expires_at_ns: Optional[int] = None

    def is_active(self, timestamp_ns: int) -> bool:
        if self.action == RiskOverrideAction.NONE:
            return False
        if self.expires_at_ns is None:
            return True
        return timestamp_ns <= self.expires_at_ns


@dataclass(frozen=True, slots=True)
class UnifiedRiskContext:
    timestamp_ns: int
    kill_switch: KillSwitch
    stale_data_blocks: Sequence[StaleDataBlock]
    divergence_blocks: Sequence[DivergenceBlock]

    hard_flat_triggered: bool = False
    regime: RegimeType = RegimeType.UNKNOWN
    toxicity_score: Decimal = Decimal("0")
    symbol: Optional[str] = None

    source_status: UnifiedRiskSourceStatus = field(default_factory=UnifiedRiskSourceStatus)
    exposure: UnifiedExposureContext = field(default_factory=UnifiedExposureContext)
    sleeve: UnifiedSleeveContext = field(default_factory=UnifiedSleeveContext)
    recovery: UnifiedRecoveryContext = field(default_factory=UnifiedRecoveryContext)
    system_health: UnifiedSystemHealthContext = field(default_factory=UnifiedSystemHealthContext)

    is_hedge_request: bool = False
    is_reduce_only_request: bool = False
    requested_scope: UnifiedRiskScope = UnifiedRiskScope.REQUEST
    requested_side: Optional[str] = None

    manual_override: UnifiedRiskOverride = field(default_factory=UnifiedRiskOverride)

    def __post_init__(self) -> None:
        if self.timestamp_ns <= 0:
            raise ValueError("timestamp_ns must be positive")
        object.__setattr__(self, "toxicity_score", _ensure_unit_interval(_d(self.toxicity_score, field_name="toxicity_score"), "toxicity_score"))


# ============================================================================
# STRUCTURED OUTPUTS
# ============================================================================

@dataclass(frozen=True, slots=True)
class UnifiedRiskEvidence:
    factor: UnifiedRiskFactor
    code: UnifiedRiskReasonCode
    active: bool
    precedence: int
    message: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CanonicalUnifiedRiskResult:
    decision: UnifiedRiskDecision
    directive: UnifiedRiskDirective
    scope: UnifiedRiskScope

    allowed: bool
    sizing_multiplier: Decimal
    confidence: Decimal
    completeness: EvaluationCompleteness

    risk_mode: RiskMode
    reason: str
    primary_reason_code: UnifiedRiskReasonCode
    precedence: int

    valid_until_ns: int
    reevaluate_after_ns: int

    evidences: Tuple[UnifiedRiskEvidence, ...]
    provenance: Dict[str, Any] = field(default_factory=dict)
    timestamp_ns: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "sizing_multiplier", _quantize_ratio(_d(self.sizing_multiplier, field_name="sizing_multiplier")))
        object.__setattr__(self, "confidence", _quantize_ratio(_ensure_unit_interval(_d(self.confidence, field_name="confidence"), "confidence")))
        if self.sizing_multiplier < ZERO or self.sizing_multiplier > ONE:
            raise ValueError("sizing_multiplier must be in [0,1]")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision.value,
            "directive": self.directive.value,
            "scope": self.scope.value,
            "allowed": self.allowed,
            "sizing_multiplier": str(self.sizing_multiplier),
            "confidence": str(self.confidence),
            "completeness": self.completeness.value,
            "risk_mode": _enum_value(self.risk_mode),
            "reason": self.reason,
            "primary_reason_code": self.primary_reason_code.value,
            "precedence": self.precedence,
            "valid_until_ns": self.valid_until_ns,
            "reevaluate_after_ns": self.reevaluate_after_ns,
            "evidences": [
                {
                    "factor": e.factor.value,
                    "code": e.code.value,
                    "active": e.active,
                    "precedence": e.precedence,
                    "message": e.message,
                    "details": e.details,
                }
                for e in self.evidences
            ],
            "provenance": self.provenance,
            "timestamp_ns": self.timestamp_ns,
        }


@dataclass(frozen=True, slots=True)
class UnifiedRiskScopeDecision:
    scope: UnifiedRiskScope
    key: str
    result: CanonicalUnifiedRiskResult


@dataclass(frozen=True, slots=True)
class SovereignRiskConstitutionResult:
    timestamp_ns: int
    global_result: CanonicalUnifiedRiskResult
    scoped_results: Tuple[UnifiedRiskScopeDecision, ...]
    transition_type: RiskTransitionType
    decision_seq: int


@dataclass(frozen=True, slots=True)
class UnifiedRiskDecisionRecord:
    sequence: int
    timestamp_ns: int
    decision: UnifiedRiskDecision
    directive: UnifiedRiskDirective
    scope: UnifiedRiskScope
    reason: str
    primary_reason_code: UnifiedRiskReasonCode
    sizing_multiplier: Decimal
    confidence: Decimal
    precedence: int
    transition_type: RiskTransitionType


# ============================================================================
# AUTHORITY
# ============================================================================

class UnifiedRiskAuthority:
    DEFAULT_TOXICITY_HARD_DENY = Decimal("0.9")
    DEFAULT_TOXICITY_DEGRADE = Decimal("0.7")
    DEFAULT_EXPOSURE_HARD_DENY = Decimal("0.95")
    DEFAULT_EXPOSURE_DEGRADE = Decimal("0.8")
    DEFAULT_CRISIS_MULTIPLIER = Decimal("0.3")
    DEFAULT_UNKNOWN_REGIME_MULTIPLIER = Decimal("0.5")

    def __init__(
        self,
        toxicity_hard_deny_threshold: Decimal = DEFAULT_TOXICITY_HARD_DENY,
        toxicity_degrade_threshold: Decimal = DEFAULT_TOXICITY_DEGRADE,
        exposure_hard_deny_threshold: Decimal = DEFAULT_EXPOSURE_HARD_DENY,
        exposure_degrade_threshold: Decimal = DEFAULT_EXPOSURE_DEGRADE,
        crisis_multiplier: Decimal = DEFAULT_CRISIS_MULTIPLIER,
        unknown_regime_multiplier: Decimal = DEFAULT_UNKNOWN_REGIME_MULTIPLIER,
    ):
        self.policy = UnifiedRiskPolicyConfig(
            toxicity_hard_deny_threshold=toxicity_hard_deny_threshold,
            toxicity_degrade_threshold=toxicity_degrade_threshold,
            exposure_hard_deny_threshold=exposure_hard_deny_threshold,
            exposure_degrade_threshold=exposure_degrade_threshold,
            crisis_multiplier=crisis_multiplier,
            unknown_regime_multiplier=unknown_regime_multiplier,
        )

        # Preserve legacy compatibility attributes
        self.toxicity_hard_deny_threshold = self.policy.toxicity_hard_deny_threshold
        self.toxicity_degrade_threshold = self.policy.toxicity_degrade_threshold
        self.exposure_hard_deny_threshold = self.policy.exposure_hard_deny_threshold
        self.exposure_degrade_threshold = self.policy.exposure_degrade_threshold
        self.crisis_multiplier = self.policy.crisis_multiplier
        self.unknown_regime_multiplier = self.policy.unknown_regime_multiplier

        self._decision_seq = 0
        self._journal: List[UnifiedRiskDecisionRecord] = []
        self._last_result: Optional[CanonicalUnifiedRiskResult] = None

    # ------------------------------------------------------------------
    # Legacy compatibility API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        timestamp_ns: int,
        kill_switch: KillSwitch,
        stale_data_blocks: List[StaleDataBlock],
        divergence_blocks: List[DivergenceBlock],
        hard_flat_triggered: bool = False,
        regime: RegimeType = RegimeType.UNKNOWN,
        toxicity_score: Decimal = Decimal("0"),
        current_exposure_pct: Decimal = Decimal("0"),
        symbol: Optional[str] = None,
    ) -> UnifiedRiskResult:
        """
        Legacy compatibility adapter.

        This is NOT a second evaluator. It projects the richer constitutional
        result into the legacy UnifiedRiskResult contract.
        """
        constitution = self.evaluate_constitution(
            UnifiedRiskContext(
                timestamp_ns=timestamp_ns,
                kill_switch=kill_switch,
                stale_data_blocks=stale_data_blocks,
                divergence_blocks=divergence_blocks,
                hard_flat_triggered=hard_flat_triggered,
                regime=regime,
                toxicity_score=toxicity_score,
                symbol=symbol,
                exposure=UnifiedExposureContext(
                    effective_utilization=current_exposure_pct,
                ),
                requested_scope=UnifiedRiskScope.SYMBOL if symbol else UnifiedRiskScope.GLOBAL,
            )
        )
        projected = self._select_legacy_projection_result(constitution=constitution, symbol=symbol)
        return UnifiedRiskResult(
            decision=projected.decision,
            allowed=projected.allowed,
            sizing_multiplier=projected.sizing_multiplier,
            risk_mode=projected.risk_mode,
            reason=projected.reason,
            provenance=projected.provenance,
            timestamp_ns=projected.timestamp_ns,
        )

    def evaluate_for_symbol(
        self,
        timestamp_ns: int,
        kill_switch: KillSwitch,
        stale_data_blocks: List[StaleDataBlock],
        divergence_blocks: List[DivergenceBlock],
        symbol: str,
        hard_flat_triggered: bool = False,
        regime: RegimeType = RegimeType.UNKNOWN,
        toxicity_score: Decimal = Decimal("0"),
        current_exposure_pct: Decimal = Decimal("0"),
    ) -> UnifiedRiskResult:
        return self.evaluate(
            timestamp_ns=timestamp_ns,
            kill_switch=kill_switch,
            stale_data_blocks=stale_data_blocks,
            divergence_blocks=divergence_blocks,
            hard_flat_triggered=hard_flat_triggered,
            regime=regime,
            toxicity_score=toxicity_score,
            current_exposure_pct=current_exposure_pct,
            symbol=symbol,
        )

    def quick_check(
        self,
        timestamp_ns: int,
        kill_switch: KillSwitch,
        hard_flat_triggered: bool = False,
        symbol: Optional[str] = None,
        stale_data_blocks: Optional[List[StaleDataBlock]] = None,
        divergence_blocks: Optional[List[DivergenceBlock]] = None,
    ) -> Tuple[bool, str]:
        """
        Narrow preflight blocker shortcut.

        This method is intentionally bounded and only checks obvious blocker
        conditions:
        - kill switch active
        - hard flat active
        - symbol stale-data block present
        - symbol divergence block present

        It is NOT the sovereign constitutional authority path.
        It intentionally ignores many degraded, scoped, and constitutional
        conditions such as toxicity, exposure, concentration, system-health,
        recovery ambiguity, overrides, and sizing decisions.

        Callers requiring a real risk authority verdict MUST use:
        - evaluate(...)
        - evaluate_constitution(...)
        """
        if kill_switch.is_killed(timestamp_ns):
            state = kill_switch.get_state()
            return False, f"preflight_block: kill_switch_active:{_enum_value(state)}"

        if hard_flat_triggered:
            return False, "preflight_block: hard_flat_override_active"

        # Upstream contract assumption:
        # stale_data_blocks / divergence_blocks are already-active block objects.
        if symbol and stale_data_blocks:
            for block in stale_data_blocks:
                if getattr(block, "symbol", None) == symbol:
                    return False, f"preflight_block: stale_data_block:{symbol}"

        if symbol and divergence_blocks:
            for block in divergence_blocks:
                if getattr(block, "symbol", None) == symbol:
                    return False, f"preflight_block: divergence_block:{symbol}"

        return True, "preflight_pass"

    # ------------------------------------------------------------------
    # Final-form constitutional API
    # ------------------------------------------------------------------

    def evaluate_constitution(
        self,
        context: UnifiedRiskContext,
    ) -> SovereignRiskConstitutionResult:
        global_result = self._evaluate_single_scope(
            context=context,
            scope=UnifiedRiskScope.GLOBAL,
            scope_key="GLOBAL",
        )

        scoped: List[UnifiedRiskScopeDecision] = []

        if context.symbol:
            scoped.append(
                UnifiedRiskScopeDecision(
                    scope=UnifiedRiskScope.SYMBOL,
                    key=context.symbol,
                    result=self._evaluate_single_scope(
                        context=context,
                        scope=UnifiedRiskScope.SYMBOL,
                        scope_key=context.symbol,
                    ),
                )
            )

        if context.sleeve.sleeve_name:
            scoped.append(
                UnifiedRiskScopeDecision(
                    scope=UnifiedRiskScope.SLEEVE,
                    key=context.sleeve.sleeve_name,
                    result=self._evaluate_single_scope(
                        context=context,
                        scope=UnifiedRiskScope.SLEEVE,
                        scope_key=context.sleeve.sleeve_name,
                    ),
                )
            )

        transition_type = self._derive_transition_type(global_result)
        self._decision_seq += 1
        self._journal.append(
            UnifiedRiskDecisionRecord(
                sequence=self._decision_seq,
                timestamp_ns=context.timestamp_ns,
                decision=global_result.decision,
                directive=global_result.directive,
                scope=global_result.scope,
                reason=global_result.reason,
                primary_reason_code=global_result.primary_reason_code,
                sizing_multiplier=global_result.sizing_multiplier,
                confidence=global_result.confidence,
                precedence=global_result.precedence,
                transition_type=transition_type,
            )
        )
        if len(self._journal) > self.policy.journal_capacity:
            self._journal = self._journal[-self.policy.journal_capacity:]

        self._last_result = global_result

        return SovereignRiskConstitutionResult(
            timestamp_ns=context.timestamp_ns,
            global_result=global_result,
            scoped_results=tuple(scoped),
            transition_type=transition_type,
            decision_seq=self._decision_seq,
        )

    def decision_journal(self, limit: Optional[int] = None) -> List[UnifiedRiskDecisionRecord]:
        if limit is None or limit >= len(self._journal):
            return list(self._journal)
        return self._journal[-limit:]

    # ------------------------------------------------------------------
    # Internal evaluation engine
    # ------------------------------------------------------------------

    def _evaluate_single_scope(
        self,
        *,
        context: UnifiedRiskContext,
        scope: UnifiedRiskScope,
        scope_key: str,
    ) -> CanonicalUnifiedRiskResult:
        evidences: List[UnifiedRiskEvidence] = []
        reasons: List[str] = []
        sizing_multiplier = ONE
        confidence = ONE
        completeness = EvaluationCompleteness.COMPLETE
        directive = UnifiedRiskDirective.ALLOW
        decision = UnifiedRiskDecision.FULL_ALLOW
        risk_mode = RiskMode.NORMAL
        precedence = UnifiedRiskPrecedence.NOMINAL
        primary_reason = UnifiedRiskReasonCode.NOMINAL

        provenance: Dict[str, Any] = {
            "scope": scope.value,
            "scope_key": scope_key,
            "symbol": context.symbol,
            "sleeve_name": context.sleeve.sleeve_name,
            "requested_scope": context.requested_scope.value,
            "requested_side": context.requested_side,
            "is_hedge_request": context.is_hedge_request,
            "is_reduce_only_request": context.is_reduce_only_request,
            "timestamp_ns": context.timestamp_ns,
            "regime": _enum_value(context.regime),
            "toxicity_score": str(context.toxicity_score),
            "effective_utilization": str(context.exposure.effective_utilization),
            "concentration_pct": str(context.exposure.concentration_pct),
            "raw_net_exposure": str(context.exposure.raw_net_exposure),
            "residual_net_exposure": str(context.exposure.residual_net_exposure),
            "hedge_overlay_exposure": str(context.exposure.hedge_overlay_exposure),
            "snapshot_quality": context.exposure.snapshot_quality,
            "reconciliation_attribution_loss": context.exposure.reconciliation_attribution_loss,
        }

        # Kill switch
        kill_state = context.kill_switch.get_state()
        kill_active = context.kill_switch.is_killed(context.timestamp_ns)
        if kill_active:
            return self._finalize(
                context=context,
                scope=scope,
                scope_key=scope_key,
                decision=UnifiedRiskDecision.HARD_DENY,
                directive=UnifiedRiskDirective.TERMINAL_DENY,
                allowed=False,
                sizing_multiplier=ZERO,
                confidence=ONE,
                completeness=EvaluationCompleteness.COMPLETE,
                risk_mode=RiskMode.HARD_FLAT,
                precedence=UnifiedRiskPrecedence.TERMINAL,
                primary_reason_code=UnifiedRiskReasonCode.KILL_SWITCH_ACTIVE,
                reasons=[f"kill_switch_active: {_enum_value(kill_state)}"],
                evidences=[
                    UnifiedRiskEvidence(
                        factor=UnifiedRiskFactor.KILL_SWITCH,
                        code=UnifiedRiskReasonCode.KILL_SWITCH_ACTIVE,
                        active=True,
                        precedence=UnifiedRiskPrecedence.TERMINAL,
                        message=f"kill_switch_active: {_enum_value(kill_state)}",
                        details={"cooldown_remaining_ns": context.kill_switch.get_cooldown_remaining_ns(context.timestamp_ns)},
                    )
                ],
                provenance=provenance,
                valid_until_ns=0,
                reevaluate_after_ns=_min_nonzero(
                    context.kill_switch.get_cooldown_remaining_ns(context.timestamp_ns),
                    self.policy.min_reevaluate_interval_ns,
                ),
            )

        # Hard flat
        if context.hard_flat_triggered:
            return self._finalize(
                context=context,
                scope=scope,
                scope_key=scope_key,
                decision=UnifiedRiskDecision.HARD_DENY,
                directive=UnifiedRiskDirective.FORCE_FLAT,
                allowed=False,
                sizing_multiplier=ZERO,
                confidence=ONE,
                completeness=EvaluationCompleteness.COMPLETE,
                risk_mode=RiskMode.HARD_FLAT,
                precedence=UnifiedRiskPrecedence.HARD_FLAT,
                primary_reason_code=UnifiedRiskReasonCode.HARD_FLAT_ACTIVE,
                reasons=["hard_flat_override_active"],
                evidences=[
                    UnifiedRiskEvidence(
                        factor=UnifiedRiskFactor.HARD_FLAT,
                        code=UnifiedRiskReasonCode.HARD_FLAT_ACTIVE,
                        active=True,
                        precedence=UnifiedRiskPrecedence.HARD_FLAT,
                        message="hard_flat_override_active",
                        details={},
                    )
                ],
                provenance=provenance,
                valid_until_ns=0,
                reevaluate_after_ns=self.policy.min_reevaluate_interval_ns,
            )

        # Symbol-level stale / divergence blocks
        if scope in {UnifiedRiskScope.SYMBOL, UnifiedRiskScope.REQUEST} and context.symbol:
            # Upstream contract assumption:
            # these are already-active block objects supplied by upstream truth producers.
            for block in context.stale_data_blocks:
                if getattr(block, "symbol", None) == context.symbol:
                    blocked_until_ns = getattr(block, "blocked_until_ns", 0)
                    return self._finalize(
                        context=context,
                        scope=scope,
                        scope_key=scope_key,
                        decision=UnifiedRiskDecision.HARD_DENY,
                        directive=UnifiedRiskDirective.BLOCK_ALL_NEW,
                        allowed=False,
                        sizing_multiplier=ZERO,
                        confidence=ONE,
                        completeness=EvaluationCompleteness.COMPLETE,
                        risk_mode=RiskMode.SAFE_MODE,
                        precedence=UnifiedRiskPrecedence.STALE_OR_DIVERGENCE,
                        primary_reason_code=UnifiedRiskReasonCode.STALE_DATA_BLOCK,
                        reasons=[f"stale_data_block: {context.symbol} until {blocked_until_ns}"],
                        evidences=[
                            UnifiedRiskEvidence(
                                factor=UnifiedRiskFactor.STALE_DATA,
                                code=UnifiedRiskReasonCode.STALE_DATA_BLOCK,
                                active=True,
                                precedence=UnifiedRiskPrecedence.STALE_OR_DIVERGENCE,
                                message=f"stale_data_block: {context.symbol} until {blocked_until_ns}",
                                details={"blocked_until_ns": blocked_until_ns},
                            )
                        ],
                        provenance=provenance,
                        valid_until_ns=blocked_until_ns,
                        reevaluate_after_ns=max(self.policy.min_reevaluate_interval_ns, blocked_until_ns - context.timestamp_ns) if blocked_until_ns > context.timestamp_ns else self.policy.min_reevaluate_interval_ns,
                    )

            for block in context.divergence_blocks:
                if getattr(block, "symbol", None) == context.symbol:
                    blocked_until_ns = getattr(block, "blocked_until_ns", 0)
                    divergence_type = getattr(block, "divergence_type", "unknown")
                    return self._finalize(
                        context=context,
                        scope=scope,
                        scope_key=scope_key,
                        decision=UnifiedRiskDecision.HARD_DENY,
                        directive=UnifiedRiskDirective.BLOCK_ALL_NEW,
                        allowed=False,
                        sizing_multiplier=ZERO,
                        confidence=ONE,
                        completeness=EvaluationCompleteness.COMPLETE,
                        risk_mode=RiskMode.SAFE_MODE,
                        precedence=UnifiedRiskPrecedence.STALE_OR_DIVERGENCE,
                        primary_reason_code=UnifiedRiskReasonCode.DIVERGENCE_BLOCK,
                        reasons=[f"divergence_block: {context.symbol} ({divergence_type}) until {blocked_until_ns}"],
                        evidences=[
                            UnifiedRiskEvidence(
                                factor=UnifiedRiskFactor.DIVERGENCE,
                                code=UnifiedRiskReasonCode.DIVERGENCE_BLOCK,
                                active=True,
                                precedence=UnifiedRiskPrecedence.STALE_OR_DIVERGENCE,
                                message=f"divergence_block: {context.symbol} ({divergence_type}) until {blocked_until_ns}",
                                details={"divergence_type": divergence_type, "blocked_until_ns": blocked_until_ns},
                            )
                        ],
                        provenance=provenance,
                        valid_until_ns=blocked_until_ns,
                        reevaluate_after_ns=max(self.policy.min_reevaluate_interval_ns, blocked_until_ns - context.timestamp_ns) if blocked_until_ns > context.timestamp_ns else self.policy.min_reevaluate_interval_ns,
                    )

        # System health degradation
        degraded_sources = self._collect_degraded_sources(context)
        if degraded_sources:
            confidence = Decimal("0.7000")
            completeness = EvaluationCompleteness.DEGRADED if SourceHealth.UNAVAILABLE in degraded_sources else EvaluationCompleteness.PARTIAL
            evidences.append(
                UnifiedRiskEvidence(
                    factor=UnifiedRiskFactor.SYSTEM_HEALTH,
                    code=UnifiedRiskReasonCode.DEGRADED_SYSTEM_HEALTH,
                    active=True,
                    precedence=UnifiedRiskPrecedence.DEGRADED_SYSTEM_HEALTH,
                    message="degraded_system_health_detected",
                    details={"degraded_sources": [s.value for s in degraded_sources]},
                )
            )
            decision = UnifiedRiskDecision.DEGRADED_ALLOW
            directive = UnifiedRiskDirective.ALLOW_REDUCED
            risk_mode = RiskMode.SAFE_MODE
            precedence = max(precedence, UnifiedRiskPrecedence.DEGRADED_SYSTEM_HEALTH)
            primary_reason = UnifiedRiskReasonCode.DEGRADED_SYSTEM_HEALTH
            reasons.append("degraded_system_health_detected")
            sizing_multiplier = min(sizing_multiplier, self.policy.degraded_system_multiplier)

        # Recovery ambiguity
        if context.recovery.recovering or context.recovery.ambiguity_active or context.exposure.reconciliation_attribution_loss:
            confidence = min(confidence, Decimal("0.6000"))
            completeness = EvaluationCompleteness.AMBIGUOUS
            evidences.append(
                UnifiedRiskEvidence(
                    factor=UnifiedRiskFactor.RECOVERY,
                    code=UnifiedRiskReasonCode.RECOVERY_AMBIGUITY,
                    active=True,
                    precedence=UnifiedRiskPrecedence.RECOVERY_AMBIGUITY,
                    message="recovery_ambiguity_active",
                    details={"ambiguity_reason": context.recovery.ambiguity_reason},
                )
            )
            decision = UnifiedRiskDecision.DEGRADED_ALLOW
            directive = UnifiedRiskDirective.REDUCE_ONLY if not context.is_hedge_request else UnifiedRiskDirective.HEDGE_ONLY
            risk_mode = RiskMode.SAFE_MODE
            precedence = max(precedence, UnifiedRiskPrecedence.RECOVERY_AMBIGUITY)
            primary_reason = UnifiedRiskReasonCode.RECOVERY_AMBIGUITY
            reasons.append("recovery_ambiguity_active")
            sizing_multiplier = min(sizing_multiplier, self.policy.ambiguous_recovery_multiplier)

        # Toxicity
        if context.toxicity_score >= self.policy.toxicity_hard_deny_threshold:
            return self._finalize(
                context=context,
                scope=scope,
                scope_key=scope_key,
                decision=UnifiedRiskDecision.HARD_DENY,
                directive=UnifiedRiskDirective.BLOCK_ALL_NEW,
                allowed=False,
                sizing_multiplier=ZERO,
                confidence=confidence,
                completeness=completeness,
                risk_mode=RiskMode.SAFE_MODE,
                precedence=UnifiedRiskPrecedence.EXTREME_TOXICITY,
                primary_reason_code=UnifiedRiskReasonCode.EXTREME_TOXICITY,
                reasons=[f"extreme_toxicity: {context.toxicity_score} >= {self.policy.toxicity_hard_deny_threshold}"],
                evidences=evidences + [
                    UnifiedRiskEvidence(
                        factor=UnifiedRiskFactor.TOXICITY,
                        code=UnifiedRiskReasonCode.EXTREME_TOXICITY,
                        active=True,
                        precedence=UnifiedRiskPrecedence.EXTREME_TOXICITY,
                        message=f"extreme_toxicity: {context.toxicity_score} >= {self.policy.toxicity_hard_deny_threshold}",
                        details={},
                    )
                ],
                provenance=provenance,
                valid_until_ns=0,
                reevaluate_after_ns=self.policy.min_reevaluate_interval_ns,
            )

        if context.toxicity_score >= self.policy.toxicity_degrade_threshold:
            t_range = self.policy.toxicity_hard_deny_threshold - self.policy.toxicity_degrade_threshold
            t_factor = Decimal("0.5") if t_range <= ZERO else ONE - min(max((context.toxicity_score - self.policy.toxicity_degrade_threshold) / t_range, ZERO), ONE)
            decision = UnifiedRiskDecision.DEGRADED_ALLOW
            directive = UnifiedRiskDirective.ALLOW_REDUCED
            risk_mode = RiskMode.SAFE_MODE
            precedence = max(precedence, UnifiedRiskPrecedence.ELEVATED_TOXICITY)
            primary_reason = UnifiedRiskReasonCode.ELEVATED_TOXICITY
            reasons.append(f"elevated_toxicity: {context.toxicity_score} >= {self.policy.toxicity_degrade_threshold}")
            sizing_multiplier = min(sizing_multiplier, t_factor)
            evidences.append(
                UnifiedRiskEvidence(
                    factor=UnifiedRiskFactor.TOXICITY,
                    code=UnifiedRiskReasonCode.ELEVATED_TOXICITY,
                    active=True,
                    precedence=UnifiedRiskPrecedence.ELEVATED_TOXICITY,
                    message=f"elevated_toxicity: {context.toxicity_score} >= {self.policy.toxicity_degrade_threshold}",
                    details={"factor": str(_quantize_ratio(t_factor))},
                )
            )
            if context.toxicity_score >= self.policy.toxicity_reduce_only_threshold and not context.is_hedge_request:
                directive = UnifiedRiskDirective.REDUCE_ONLY
                sizing_multiplier = ZERO

        # Exposure
        util = context.exposure.effective_utilization
        if util >= self.policy.exposure_hard_deny_threshold:
            if context.is_reduce_only_request:
                decision = UnifiedRiskDecision.DEGRADED_ALLOW
                directive = UnifiedRiskDirective.REDUCE_ONLY
                sizing_multiplier = ZERO
                risk_mode = RiskMode.SAFE_MODE
                precedence = max(precedence, UnifiedRiskPrecedence.EXTREME_EXPOSURE)
                primary_reason = UnifiedRiskReasonCode.EXTREME_EXPOSURE
                reasons.append("extreme_exposure_reduce_only_exception")
            elif context.is_hedge_request:
                decision = UnifiedRiskDecision.DEGRADED_ALLOW
                directive = UnifiedRiskDirective.HEDGE_ONLY
                sizing_multiplier = Decimal("0.2500")
                risk_mode = RiskMode.SAFE_MODE
                precedence = max(precedence, UnifiedRiskPrecedence.EXTREME_EXPOSURE)
                primary_reason = UnifiedRiskReasonCode.EXTREME_EXPOSURE
                reasons.append("extreme_exposure_hedge_only_exception")
            else:
                return self._finalize(
                    context=context,
                    scope=scope,
                    scope_key=scope_key,
                    decision=UnifiedRiskDecision.HARD_DENY,
                    directive=UnifiedRiskDirective.BLOCK_ALL_NEW,
                    allowed=False,
                    sizing_multiplier=ZERO,
                    confidence=confidence,
                    completeness=completeness,
                    risk_mode=RiskMode.SAFE_MODE,
                    precedence=UnifiedRiskPrecedence.EXTREME_EXPOSURE,
                    primary_reason_code=UnifiedRiskReasonCode.EXTREME_EXPOSURE,
                    reasons=[f"extreme_exposure: {util} >= {self.policy.exposure_hard_deny_threshold}"],
                    evidences=evidences + [
                        UnifiedRiskEvidence(
                            factor=UnifiedRiskFactor.EXPOSURE,
                            code=UnifiedRiskReasonCode.EXTREME_EXPOSURE,
                            active=True,
                            precedence=UnifiedRiskPrecedence.EXTREME_EXPOSURE,
                            message=f"extreme_exposure: {util} >= {self.policy.exposure_hard_deny_threshold}",
                            details={},
                        )
                    ],
                    provenance=provenance,
                    valid_until_ns=0,
                    reevaluate_after_ns=self.policy.min_reevaluate_interval_ns,
                )

        elif util >= self.policy.exposure_degrade_threshold:
            e_range = self.policy.exposure_hard_deny_threshold - self.policy.exposure_degrade_threshold
            e_factor = Decimal("0.5") if e_range <= ZERO else ONE - (Decimal("0.8") * (min(max((util - self.policy.exposure_degrade_threshold) / e_range, ZERO), ONE) ** 2))
            decision = UnifiedRiskDecision.DEGRADED_ALLOW
            precedence = max(precedence, UnifiedRiskPrecedence.ELEVATED_EXPOSURE)
            primary_reason = UnifiedRiskReasonCode.ELEVATED_EXPOSURE
            reasons.append(f"elevated_exposure: {util} >= {self.policy.exposure_degrade_threshold}")
            risk_mode = RiskMode.SAFE_MODE
            sizing_multiplier = min(sizing_multiplier, e_factor)
            evidences.append(
                UnifiedRiskEvidence(
                    factor=UnifiedRiskFactor.EXPOSURE,
                    code=UnifiedRiskReasonCode.ELEVATED_EXPOSURE,
                    active=True,
                    precedence=UnifiedRiskPrecedence.ELEVATED_EXPOSURE,
                    message=f"elevated_exposure: {util} >= {self.policy.exposure_degrade_threshold}",
                    details={"factor": str(_quantize_ratio(e_factor))},
                )
            )

            if util >= self.policy.exposure_reduce_only_threshold and not context.is_hedge_request:
                directive = UnifiedRiskDirective.REDUCE_ONLY
                sizing_multiplier = ZERO
            elif util >= self.policy.exposure_hedge_only_threshold and context.is_hedge_request:
                directive = UnifiedRiskDirective.HEDGE_ONLY
                sizing_multiplier = min(sizing_multiplier, Decimal("0.3500"))
            elif directive == UnifiedRiskDirective.ALLOW:
                directive = UnifiedRiskDirective.ALLOW_REDUCED

        # Concentration
        conc = context.exposure.concentration_pct
        if conc >= self.policy.concentration_hard_deny_threshold:
            return self._finalize(
                context=context,
                scope=scope,
                scope_key=scope_key,
                decision=UnifiedRiskDecision.HARD_DENY,
                directive=UnifiedRiskDirective.BLOCK_ALL_NEW,
                allowed=False,
                sizing_multiplier=ZERO,
                confidence=confidence,
                completeness=completeness,
                risk_mode=RiskMode.SAFE_MODE,
                precedence=UnifiedRiskPrecedence.EXTREME_CONCENTRATION,
                primary_reason_code=UnifiedRiskReasonCode.EXTREME_CONCENTRATION,
                reasons=[f"extreme_concentration: {conc} >= {self.policy.concentration_hard_deny_threshold}"],
                evidences=evidences + [
                    UnifiedRiskEvidence(
                        factor=UnifiedRiskFactor.CONCENTRATION,
                        code=UnifiedRiskReasonCode.EXTREME_CONCENTRATION,
                        active=True,
                        precedence=UnifiedRiskPrecedence.EXTREME_CONCENTRATION,
                        message=f"extreme_concentration: {conc} >= {self.policy.concentration_hard_deny_threshold}",
                        details={},
                    )
                ],
                provenance=provenance,
                valid_until_ns=0,
                reevaluate_after_ns=self.policy.min_reevaluate_interval_ns,
            )

        elif conc >= self.policy.concentration_degrade_threshold:
            decision = UnifiedRiskDecision.DEGRADED_ALLOW
            directive = UnifiedRiskDirective.ALLOW_REDUCED if directive == UnifiedRiskDirective.ALLOW else directive
            risk_mode = RiskMode.SAFE_MODE
            precedence = max(precedence, UnifiedRiskPrecedence.ELEVATED_CONCENTRATION)
            primary_reason = UnifiedRiskReasonCode.ELEVATED_CONCENTRATION
            reasons.append(f"elevated_concentration: {conc} >= {self.policy.concentration_degrade_threshold}")
            sizing_multiplier = min(sizing_multiplier, Decimal("0.5000"))
            evidences.append(
                UnifiedRiskEvidence(
                    factor=UnifiedRiskFactor.CONCENTRATION,
                    code=UnifiedRiskReasonCode.ELEVATED_CONCENTRATION,
                    active=True,
                    precedence=UnifiedRiskPrecedence.ELEVATED_CONCENTRATION,
                    message=f"elevated_concentration: {conc} >= {self.policy.concentration_degrade_threshold}",
                    details={},
                )
            )

        # Regime
        if self._is_crisis_regime(context.regime):
            decision = UnifiedRiskDecision.DEGRADED_ALLOW
            if directive == UnifiedRiskDirective.ALLOW:
                directive = UnifiedRiskDirective.ALLOW_REDUCED
            risk_mode = RiskMode.SAFE_MODE
            precedence = max(precedence, UnifiedRiskPrecedence.UNFAVORABLE_REGIME)
            primary_reason = UnifiedRiskReasonCode.CRISIS_REGIME
            reasons.append("unfavorable_regime: CRISIS")
            sizing_multiplier = min(sizing_multiplier, self.policy.crisis_multiplier)
            evidences.append(
                UnifiedRiskEvidence(
                    factor=UnifiedRiskFactor.REGIME,
                    code=UnifiedRiskReasonCode.CRISIS_REGIME,
                    active=True,
                    precedence=UnifiedRiskPrecedence.UNFAVORABLE_REGIME,
                    message="unfavorable_regime: CRISIS",
                    details={"factor": str(self.policy.crisis_multiplier)},
                )
            )
        elif context.regime == RegimeType.UNKNOWN:
            decision = UnifiedRiskDecision.DEGRADED_ALLOW
            if directive == UnifiedRiskDirective.ALLOW:
                directive = UnifiedRiskDirective.ALLOW_REDUCED
            risk_mode = RiskMode.SAFE_MODE
            precedence = max(precedence, UnifiedRiskPrecedence.UNFAVORABLE_REGIME)
            primary_reason = UnifiedRiskReasonCode.UNKNOWN_REGIME
            reasons.append("unfavorable_regime: UNKNOWN")
            sizing_multiplier = min(sizing_multiplier, self.policy.unknown_regime_multiplier)
            evidences.append(
                UnifiedRiskEvidence(
                    factor=UnifiedRiskFactor.REGIME,
                    code=UnifiedRiskReasonCode.UNKNOWN_REGIME,
                    active=True,
                    precedence=UnifiedRiskPrecedence.UNFAVORABLE_REGIME,
                    message="unfavorable_regime: UNKNOWN",
                    details={"factor": str(self.policy.unknown_regime_multiplier)},
                )
            )

        # Manual override
        if context.manual_override.is_active(context.timestamp_ns):
            decision, directive, sizing_multiplier, primary_reason, precedence = self._apply_override(
                override=context.manual_override,
                current_decision=decision,
                current_directive=directive,
                current_sizing_multiplier=sizing_multiplier,
                current_precedence=precedence,
                current_primary_reason=primary_reason,
            )
            reasons.append(f"manual_override:{context.manual_override.action.value}")
            evidences.append(
                UnifiedRiskEvidence(
                    factor=UnifiedRiskFactor.MANUAL_OVERRIDE,
                    code=UnifiedRiskReasonCode.MANUAL_OVERRIDE_APPLIED,
                    active=True,
                    precedence=UnifiedRiskPrecedence.MANUAL_OVERRIDE,
                    message=f"manual_override:{context.manual_override.action.value}",
                    details={
                        "issuer": context.manual_override.issuer,
                        "reason": context.manual_override.reason,
                        "expires_at_ns": context.manual_override.expires_at_ns,
                        "scope": context.manual_override.scope.value,
                    },
                )
            )

        if not reasons:
            reasons = ["all_risk_factors_nominal"]
            primary_reason = UnifiedRiskReasonCode.NOMINAL
            evidences.append(
                UnifiedRiskEvidence(
                    factor=UnifiedRiskFactor.MANUAL_OVERRIDE,
                    code=UnifiedRiskReasonCode.NOMINAL,
                    active=False,
                    precedence=UnifiedRiskPrecedence.NOMINAL,
                    message="all_risk_factors_nominal",
                    details={},
                )
            )
            decision = UnifiedRiskDecision.FULL_ALLOW
            directive = UnifiedRiskDirective.ALLOW
            risk_mode = RiskMode.NORMAL
            precedence = UnifiedRiskPrecedence.NOMINAL

        valid_until_ns = 0
        reevaluate_after_ns = self.policy.min_reevaluate_interval_ns

        return self._finalize(
            context=context,
            scope=scope,
            scope_key=scope_key,
            decision=decision,
            directive=directive,
            allowed=(decision != UnifiedRiskDecision.HARD_DENY),
            sizing_multiplier=sizing_multiplier,
            confidence=self._apply_hysteresis_confidence(confidence, decision),
            completeness=completeness,
            risk_mode=risk_mode,
            precedence=precedence,
            primary_reason_code=primary_reason,
            reasons=reasons,
            evidences=evidences,
            provenance=provenance,
            valid_until_ns=valid_until_ns,
            reevaluate_after_ns=reevaluate_after_ns,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _select_legacy_projection_result(
        self,
        *,
        constitution: SovereignRiskConstitutionResult,
        symbol: Optional[str],
    ) -> CanonicalUnifiedRiskResult:
        """
        Select the correct constitutional result to project into the legacy
        UnifiedRiskResult compatibility surface.

        Rules:
        - no symbol requested -> global_result
        - symbol requested -> prefer matching SYMBOL scoped result
        - no match -> fallback to global_result
        """
        if not symbol:
            return constitution.global_result

        for scoped in constitution.scoped_results:
            if scoped.scope == UnifiedRiskScope.SYMBOL and scoped.key == symbol:
                return scoped.result

        return constitution.global_result

    def _collect_degraded_sources(self, context: UnifiedRiskContext) -> List[SourceHealth]:
        out: List[SourceHealth] = []

        source_values = [
            context.source_status.stale_data_health,
            context.source_status.divergence_health,
            context.source_status.exposure_health,
            context.source_status.toxicity_health,
            context.source_status.orchestrator_health,
            context.source_status.persistence_health,
        ]
        out.extend([s for s in source_values if s != SourceHealth.HEALTHY])

        if context.system_health.infra_degraded:
            out.append(SourceHealth.DEGRADED)
        if context.system_health.router_degraded:
            out.append(SourceHealth.DEGRADED)
        if context.system_health.persistence_degraded:
            out.append(SourceHealth.DEGRADED)

        return out

    def _is_crisis_regime(self, regime: RegimeType) -> bool:
        regime_name = getattr(regime, "name", str(regime))
        regime_value = _enum_value(regime).upper()
        return (
            regime_name == "CRISIS"
            or regime_value == "CRISIS"
            or regime_name.startswith("CRISIS_")
            or regime_value.startswith("CRISIS_")
        )

    def _apply_override(
        self,
        *,
        override: UnifiedRiskOverride,
        current_decision: UnifiedRiskDecision,
        current_directive: UnifiedRiskDirective,
        current_sizing_multiplier: Decimal,
        current_precedence: int,
        current_primary_reason: UnifiedRiskReasonCode,
    ) -> Tuple[UnifiedRiskDecision, UnifiedRiskDirective, Decimal, UnifiedRiskReasonCode, int]:
        if override.action == RiskOverrideAction.FORCE_TERMINAL_DENY:
            return (
                UnifiedRiskDecision.HARD_DENY,
                UnifiedRiskDirective.TERMINAL_DENY,
                ZERO,
                UnifiedRiskReasonCode.MANUAL_OVERRIDE_APPLIED,
                UnifiedRiskPrecedence.TERMINAL,
            )

        if override.action == RiskOverrideAction.FORCE_BLOCK_ALL_NEW:
            return (
                UnifiedRiskDecision.HARD_DENY,
                UnifiedRiskDirective.BLOCK_ALL_NEW,
                ZERO,
                UnifiedRiskReasonCode.MANUAL_OVERRIDE_APPLIED,
                max(current_precedence, UnifiedRiskPrecedence.MANUAL_OVERRIDE),
            )

        if override.action == RiskOverrideAction.FORCE_HEDGE_ONLY:
            return (
                UnifiedRiskDecision.DEGRADED_ALLOW,
                UnifiedRiskDirective.HEDGE_ONLY,
                min(current_sizing_multiplier, Decimal("0.5000")),
                UnifiedRiskReasonCode.MANUAL_OVERRIDE_APPLIED,
                max(current_precedence, UnifiedRiskPrecedence.MANUAL_OVERRIDE),
            )

        if override.action == RiskOverrideAction.FORCE_REDUCE_ONLY:
            return (
                UnifiedRiskDecision.DEGRADED_ALLOW,
                UnifiedRiskDirective.REDUCE_ONLY,
                ZERO,
                UnifiedRiskReasonCode.MANUAL_OVERRIDE_APPLIED,
                max(current_precedence, UnifiedRiskPrecedence.MANUAL_OVERRIDE),
            )

        if override.action == RiskOverrideAction.FORCE_ALLOW_REDUCED:
            return (
                UnifiedRiskDecision.DEGRADED_ALLOW,
                UnifiedRiskDirective.ALLOW_REDUCED,
                min(current_sizing_multiplier, Decimal("0.5000")),
                UnifiedRiskReasonCode.MANUAL_OVERRIDE_APPLIED,
                max(current_precedence, UnifiedRiskPrecedence.MANUAL_OVERRIDE),
            )

        return current_decision, current_directive, current_sizing_multiplier, current_primary_reason, current_precedence

    def _apply_hysteresis_confidence(
        self,
        confidence: Decimal,
        decision: UnifiedRiskDecision,
    ) -> Decimal:
        if not self.policy.use_hysteresis or self._last_result is None:
            return confidence

        if self._last_result.decision == UnifiedRiskDecision.HARD_DENY and decision != UnifiedRiskDecision.HARD_DENY:
            return min(confidence, Decimal("0.8500"))
        if self._last_result.decision == UnifiedRiskDecision.DEGRADED_ALLOW and decision == UnifiedRiskDecision.FULL_ALLOW:
            return min(confidence, Decimal("0.9000"))
        return confidence

    def _derive_transition_type(self, result: CanonicalUnifiedRiskResult) -> RiskTransitionType:
        if self._last_result is None:
            return RiskTransitionType.INITIAL

        rank = {
            UnifiedRiskDecision.FULL_ALLOW: 0,
            UnifiedRiskDecision.DEGRADED_ALLOW: 1,
            UnifiedRiskDecision.HARD_DENY: 2,
        }

        old_rank = rank[self._last_result.decision]
        new_rank = rank[result.decision]

        if new_rank > old_rank:
            return RiskTransitionType.ESCALATION
        if new_rank < old_rank:
            return RiskTransitionType.RELAXATION
        return RiskTransitionType.LATERAL

    def _finalize(
        self,
        *,
        context: UnifiedRiskContext,
        scope: UnifiedRiskScope,
        scope_key: str,
        decision: UnifiedRiskDecision,
        directive: UnifiedRiskDirective,
        allowed: bool,
        sizing_multiplier: Decimal,
        confidence: Decimal,
        completeness: EvaluationCompleteness,
        risk_mode: RiskMode,
        precedence: int,
        primary_reason_code: UnifiedRiskReasonCode,
        reasons: List[str],
        evidences: List[UnifiedRiskEvidence],
        provenance: Dict[str, Any],
        valid_until_ns: int,
        reevaluate_after_ns: int,
    ) -> CanonicalUnifiedRiskResult:
        provenance = dict(provenance)
        provenance.update({
            "scope": scope.value,
            "scope_key": scope_key,
            "directive": directive.value,
            "decision_precedence": precedence,
            "primary_reason_code": primary_reason_code.value,
            "evidence_count": len(evidences),
            "confidence": str(_quantize_ratio(confidence)),
            "completeness": completeness.value,
            "valid_until_ns": valid_until_ns,
            "reevaluate_after_ns": reevaluate_after_ns,
        })

        return CanonicalUnifiedRiskResult(
            decision=decision,
            directive=directive,
            scope=scope,
            allowed=allowed,
            sizing_multiplier=max(ZERO, sizing_multiplier),
            confidence=confidence,
            completeness=completeness,
            risk_mode=risk_mode,
            reason=" | ".join(reasons),
            primary_reason_code=primary_reason_code,
            precedence=precedence,
            valid_until_ns=valid_until_ns,
            reevaluate_after_ns=reevaluate_after_ns,
            evidences=tuple(evidences),
            provenance=provenance,
            timestamp_ns=context.timestamp_ns,
        )


# ============================================================================
# FACTORY
# ============================================================================

def create_unified_risk_authority(
    toxicity_hard_deny_threshold: Decimal = Decimal("0.9"),
    toxicity_degrade_threshold: Decimal = Decimal("0.7"),
    exposure_hard_deny_threshold: Decimal = Decimal("0.95"),
    exposure_degrade_threshold: Decimal = Decimal("0.8"),
    crisis_multiplier: Decimal = Decimal("0.3"),
    unknown_regime_multiplier: Decimal = Decimal("0.5"),
) -> UnifiedRiskAuthority:
    return UnifiedRiskAuthority(
        toxicity_hard_deny_threshold=toxicity_hard_deny_threshold,
        toxicity_degrade_threshold=toxicity_degrade_threshold,
        exposure_hard_deny_threshold=exposure_hard_deny_threshold,
        exposure_degrade_threshold=exposure_degrade_threshold,
        crisis_multiplier=crisis_multiplier,
        unknown_regime_multiplier=unknown_regime_multiplier,
    )


__all__ = [
    "UnifiedRiskDecision",
    "UnifiedRiskDirective",
    "UnifiedRiskScope",
    "UnifiedRiskFactor",
    "UnifiedRiskReasonCode",
    "EvaluationCompleteness",
    "SourceHealth",
    "RiskOverrideAction",
    "RiskTransitionType",
    "UnifiedRiskPrecedence",
    "UnifiedRiskPolicyConfig",
    "UnifiedRiskSourceStatus",
    "UnifiedExposureContext",
    "UnifiedSleeveContext",
    "UnifiedRecoveryContext",
    "UnifiedSystemHealthContext",
    "UnifiedRiskOverride",
    "UnifiedRiskContext",
    "UnifiedRiskEvidence",
    "CanonicalUnifiedRiskResult",
    "UnifiedRiskScopeDecision",
    "SovereignRiskConstitutionResult",
    "UnifiedRiskDecisionRecord",
    "UnifiedRiskResult",
    "UnifiedRiskAuthority",
    "create_unified_risk_authority",
]
