"""
app/risk/net_edge_governor.py
POVERTY_KILLER — NET EDGE GOVERNOR (KERNEL)

ARCHITECTURAL ROLE
------------------
- Canonical authority for per-trade economic admissibility.
- Kernel-level evaluation ONLY.
- Not the full live enforcement subsystem. Upstream layers MUST enforce
  component non-overlap and bind this to the active execution veto path.
- Implements strict valid-until bounds, source tracking, and malformed input rejection.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum, unique
from typing import Tuple

from app.risk.trade_efficiency_governor import SleeveEfficiencyState, TradeEfficiencyGovernor

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS & REASON CODES
# ============================================================================

ZERO = Decimal("0")
ONE = Decimal("1")

# Explicit, mutually exclusive reason codes required by spec
REASON_PROTECTIVE_EXIT = "PROTECTIVE_EXIT_CARVEOUT"
REASON_PROTECTIVE_HEDGE = "PROTECTIVE_HEDGE_CARVEOUT"
REASON_KILL_SWITCH = "GLOBAL_KILL_SWITCH_ACTIVE"
REASON_QUARANTINED = "SLEEVE_QUARANTINED"
REASON_STALE_ECONOMICS = "ECONOMICS_STALE_BEYOND_VALIDITY"
REASON_LOW_CONFIDENCE = "ESTIMATE_CONFIDENCE_BELOW_THRESHOLD"
REASON_NEGATIVE_EDGE = "NON_POSITIVE_NET_EDGE"
REASON_THROTTLED = "POSITIVE_EDGE_BUT_SLEEVE_IMPAIRED"
REASON_ADMISSIBLE = "ECONOMICALLY_ADMISSIBLE"

@unique
class CandidateType(str, Enum):
    FRESH_ENTRY = "FRESH_ENTRY"
    ADD = "ADD"
    HEDGE = "HEDGE"
    REDUCE = "REDUCE"
    CLOSE = "CLOSE"

@unique
class EconomicDecision(str, Enum):
    DENY = "DENY"
    ALLOW_REDUCED = "ALLOW_REDUCED"
    ALLOW = "ALLOW"
    HEDGE_ONLY = "HEDGE_ONLY"
    REDUCE_ONLY = "REDUCE_ONLY"

# ============================================================================
# CONTRACT MODELS
# ============================================================================

@dataclass(frozen=True, slots=True)
class ExecutionEconomics:
    """Direct execution friction. Upstream caller MUST ensure no burden overlap."""
    fee_cost: Decimal = ZERO
    spread_cost: Decimal = ZERO
    slippage_cost: Decimal = ZERO
    latency_drag: Decimal = ZERO
    partial_fill_drag: Decimal = ZERO
    exit_execution_cost: Decimal = ZERO

    @property
    def total_cost(self) -> Decimal:
        return (self.fee_cost + self.spread_cost + self.slippage_cost +
                self.latency_drag + self.partial_fill_drag + self.exit_execution_cost)

@dataclass(frozen=True, slots=True)
class AdversarialBurdens:
    """Systemic burdens. Upstream caller MUST ensure no execution cost overlap."""
    borrow_burden: Decimal = ZERO
    funding_burden: Decimal = ZERO
    carry_burden: Decimal = ZERO
    capital_burden: Decimal = ZERO
    margin_burden: Decimal = ZERO
    regime_burden: Decimal = ZERO
    adverse_exit_allowance: Decimal = ZERO

    @property
    def total_burden(self) -> Decimal:
        return (self.borrow_burden + self.funding_burden + self.carry_burden +
                self.capital_burden + self.margin_burden +
                self.regime_burden + self.adverse_exit_allowance)

@dataclass(frozen=True, slots=True)
class CandidateContext:
    symbol: str
    sleeve_id: str
    candidate_type: CandidateType
    gross_edge: Decimal
    gross_edge_source: str
    estimate_confidence: Decimal
    timestamp_ns: int
    valid_until_ns: int
    costs: ExecutionEconomics
    burdens: AdversarialBurdens

    def __post_init__(self) -> None:
        if not self.symbol: raise ValueError("symbol cannot be empty")
        if not self.sleeve_id: raise ValueError("sleeve_id cannot be empty")
        if not self.gross_edge_source: raise ValueError("gross_edge_source cannot be empty")

        if self.timestamp_ns <= 0: raise ValueError("timestamp_ns must be strictly positive")
        if self.valid_until_ns <= 0: raise ValueError("valid_until_ns must be strictly positive")
        if self.valid_until_ns < self.timestamp_ns: raise ValueError("valid_until_ns cannot precede timestamp_ns")

        if self.estimate_confidence < ZERO or self.estimate_confidence > ONE:
            raise ValueError(f"estimate_confidence must be in [0, 1], got {self.estimate_confidence}")

@dataclass(frozen=True, slots=True)
class NetEdgeEvaluation:
    """Fully traceable evaluation record suitable for replay, audit, and execution veto."""
    timestamp_ns: int
    symbol: str
    sleeve_id: str
    candidate_type: CandidateType
    gross_edge_source: str
    gross_edge: Decimal
    total_modeled_cost: Decimal
    total_modeled_burden: Decimal
    net_adversarial_edge: Decimal
    estimate_confidence: Decimal
    decision: EconomicDecision
    sizing_multiplier: Decimal
    sleeve_efficiency_state: SleeveEfficiencyState
    reason_code: str
    reevaluation_conditions: Tuple[str, ...] = field(default_factory=tuple)

# ============================================================================
# GOVERNOR ENGINE
# ============================================================================

class NetEdgeGovernor:
    """
    Kernel authority for per-trade economic admissibility.
    Enforces Net Profit Dominance, tracks edge provenance, and ensures bounded expiration.
    """

    __slots__ = ('_efficiency_governor',)

    def __init__(self, efficiency_governor: TradeEfficiencyGovernor):
        self._efficiency_governor = efficiency_governor

    def evaluate(
        self, current_time_ns: int, candidate: CandidateContext, kill_switch_active: bool
    ) -> NetEdgeEvaluation:
        """
        Deterministic evaluation pipeline.
        Requires mathematically pure input; malformed Contexts raise ValueError at __post_init__.
        """
        total_cost = candidate.costs.total_cost
        total_burden = candidate.burdens.total_burden
        net_edge = candidate.gross_edge - total_cost - total_burden

        sleeve_state = self._efficiency_governor.get_sleeve_state(candidate.sleeve_id)
        efficiency_multiplier = self._efficiency_governor.get_sizing_multiplier(candidate.sleeve_id)

        # ---------------------------------------------------------
        # PHASE 1: PROTECTIVE EXIT SUPREMACY
        # ---------------------------------------------------------
        if candidate.candidate_type in {CandidateType.CLOSE, CandidateType.REDUCE}:
            return self._build_eval(
                current_time_ns, candidate, net_edge, EconomicDecision.REDUCE_ONLY,
                ONE, sleeve_state, REASON_PROTECTIVE_EXIT
            )

        if candidate.candidate_type == CandidateType.HEDGE:
            # Governance Note: This kernel grants the constitutional HEDGE carve-out.
            # Upstream execution MUST mathematically verify this candidate actually reduces portfolio delta.
            return self._build_eval(
                current_time_ns, candidate, net_edge, EconomicDecision.HEDGE_ONLY,
                ONE, sleeve_state, REASON_PROTECTIVE_HEDGE
            )

        # ---------------------------------------------------------
        # PHASE 2: FRESH DEPLOYMENT ECONOMIC ADMISSIBILITY
        # ---------------------------------------------------------

        if kill_switch_active:
            return self._build_eval(
                current_time_ns, candidate, net_edge, EconomicDecision.DENY,
                ZERO, sleeve_state, REASON_KILL_SWITCH
            )

        if sleeve_state == SleeveEfficiencyState.QUARANTINED:
            return self._build_eval(
                current_time_ns, candidate, net_edge, EconomicDecision.DENY,
                ZERO, sleeve_state, REASON_QUARANTINED
            )

        # Temporal and Quality Guards
        if current_time_ns > candidate.valid_until_ns:
            return self._build_eval(
                current_time_ns, candidate, net_edge, EconomicDecision.DENY,
                ZERO, sleeve_state, REASON_STALE_ECONOMICS
            )

        if candidate.estimate_confidence < Decimal("0.30"):
            return self._build_eval(
                current_time_ns, candidate, net_edge, EconomicDecision.DENY,
                ZERO, sleeve_state, REASON_LOW_CONFIDENCE
            )

        # Core Economic Check
        if net_edge <= ZERO:
            return self._build_eval(
                current_time_ns, candidate, net_edge, EconomicDecision.DENY,
                ZERO, sleeve_state, REASON_NEGATIVE_EDGE, reevaluation_conditions=("EDGE_IMPROVES",)
            )

        # Throttle Adjustments
        if sleeve_state in {SleeveEfficiencyState.THROTTLED, SleeveEfficiencyState.DEHYDRATED, SleeveEfficiencyState.RECOVERY_OBSERVATION}:
            return self._build_eval(
                current_time_ns, candidate, net_edge, EconomicDecision.ALLOW_REDUCED,
                efficiency_multiplier, sleeve_state, REASON_THROTTLED, reevaluation_conditions=("STATE_IMPROVES",)
            )

        # Canonical Allowance
        return self._build_eval(
            current_time_ns, candidate, net_edge, EconomicDecision.ALLOW,
            ONE, sleeve_state, REASON_ADMISSIBLE
        )

    def _build_eval(
        self, ts_ns: int, ctx: CandidateContext, net: Decimal, dec: EconomicDecision,
        sz: Decimal, st: SleeveEfficiencyState, rsn: str, reevaluation_conditions: Tuple[str, ...] = ()
    ) -> NetEdgeEvaluation:
        return NetEdgeEvaluation(
            timestamp_ns=ts_ns,
            symbol=ctx.symbol,
            sleeve_id=ctx.sleeve_id,
            candidate_type=ctx.candidate_type,
            gross_edge_source=ctx.gross_edge_source,
            gross_edge=ctx.gross_edge,
            total_modeled_cost=ctx.costs.total_cost,
            total_modeled_burden=ctx.burdens.total_burden,
            net_adversarial_edge=net,
            estimate_confidence=ctx.estimate_confidence,
            decision=dec,
            sizing_multiplier=sz,
            sleeve_efficiency_state=st,
            reason_code=rsn,
            reevaluation_conditions=reevaluation_conditions
        )