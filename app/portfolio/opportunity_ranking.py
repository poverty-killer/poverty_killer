"""
POVERTY KILLER — Opportunity Ranking

Pre-integration, passive model only.

This module models cross-asset opportunity scoring: given multiple
potential signals across instruments, rank them by expected net edge
after costs, capacity, correlation penalty, and drawdown penalty.

This is a pre-integration utility. It has no allocation authority,
no execution authority, and no impact on current bot behavior.

Design constraints:
- No imports from runtime modules (MainLoop, SignalFusion, Execution).
- No side effects.
- No live routing.
- Decimal for all monetary/sizing values.
- Deterministic given inputs.

Author: D / DeepSeek — Stage 2-G0B
Date: 2026-05-03
Status: PRE-INTEGRATION — PASSIVE MODEL — NO ALLOCATION AUTHORITY
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum, unique
from typing import Optional, Dict, List, Tuple, FrozenSet

from app.models.instrument_profile import InstrumentProfile


# ────────────────────────────────────────────────────────────────
# Opportunity Enums
# ────────────────────────────────────────────────────────────────

@unique
class OpportunityGrade(str, Enum):
    """Overall opportunity grade."""
    A = "A"              # Prime opportunity — all conditions favorable
    B = "B"              # Good opportunity — minor concerns
    C = "C"              # Marginal — elevated costs or reduced capacity
    D = "D"              # Weak — high friction, low edge
    F = "F"              # Skip — hard blocked or negative net edge


@unique
class SkipReason(str, Enum):
    """Reasons an opportunity is skipped entirely."""
    NEGATIVE_NET_EDGE = "negative_net_edge"
    BELOW_MIN_CONFIDENCE = "below_min_confidence"
    BELOW_MIN_CAPACITY = "below_min_capacity"
    HARD_BLOCKED_BY_RISK = "hard_blocked_by_risk"
    CORRELATION_COLLISION = "correlation_collision"
    DRAWDOWN_RESTRICTION = "drawdown_restriction"
    SESSION_CLOSED = "session_closed"
    INSTRUMENT_NOT_QUALIFIED = "instrument_not_qualified"
    CAPITAL_INSUFFICIENT = "capital_insufficient"


# ────────────────────────────────────────────────────────────────
# Opportunity Models
# ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class OpportunityCostBreakdown:
    """Full cost decomposition for an opportunity."""
    expected_gross_edge_bps: Decimal      # Gross edge before costs
    explicit_fee_bps: Decimal             # Maker/taker/commission
    spread_cost_bps: Decimal
    impact_cost_bps: Decimal
    borrow_cost_bps: Decimal
    funding_cost_bps: Decimal
    regulatory_cost_bps: Decimal
    total_cost_bps: Decimal               # Sum of all costs
    net_edge_bps: Decimal                 # Gross - Total cost

    @property
    def is_net_positive(self) -> bool:
        return self.net_edge_bps > Decimal("0")

    @property
    def edge_cost_ratio(self) -> Decimal:
        """Ratio of gross edge to total cost. >1 means edge exceeds cost."""
        if self.total_cost_bps > Decimal("0"):
            return self.expected_gross_edge_bps / self.total_cost_bps
        return self.expected_gross_edge_bps


@dataclass(frozen=True)
class OpportunityCapacity:
    """Capacity and sizing for an opportunity."""
    instrument_symbol: str
    max_position_notional: Decimal
    max_order_notional: Decimal
    available_capital: Decimal
    position_after_alloc: Decimal          # Notional if this opportunity is taken
    remaining_capacity_pct: Decimal        # How much capacity remains after
    is_capacity_constrained: bool          # True if capacity limits binding


@dataclass(frozen=True)
class OpportunityCorrelationPenalty:
    """Penalty from correlation with existing positions."""
    correlated_symbols: Tuple[str, ...]
    correlation_score: Decimal             # 0=uncorrelated, 1=fully correlated
    penalty_factor: Decimal                # 1.0=no penalty, 0.5=50% reduction
    diversification_bonus: Decimal         # Bonus for adding uncorrelated exposure


@dataclass(frozen=True)
class OpportunityRank:
    """
    Final ranked opportunity for a single instrument/signal.

    This is the output the Board can review before any allocation
    decisions are made. It carries no execution authority.
    """
    # Identity
    rank: int                             # 1 = best opportunity
    instrument_id: str
    symbol: str
    strategy_id: str

    # Edge
    expected_gross_edge_bps: Decimal
    cost_breakdown: OpportunityCostBreakdown

    # Confidence
    signal_confidence: Decimal            # 0-1 from signal source
    composite_confidence: Decimal         # After cost/capacity/correlation adjustments

    # Capacity
    capacity: OpportunityCapacity
    target_allocation_notional: Decimal
    target_allocation_pct: Decimal        # % of total equity

    # Final
    net_edge_after_all: Decimal           # Edge after costs, correlation, drawdown
    grade: OpportunityGrade = OpportunityGrade.C
    score: Decimal = Decimal("0")         # 0-1 composite score

    # Correlation
    correlation_penalty: Optional[OpportunityCorrelationPenalty] = None

    # Skip
    skip: bool = False
    skip_reasons: Tuple[str, ...] = field(default_factory=tuple)

    # Metadata
    timestamp_ns: int = 0
    assumptions: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class OpportunityRankingReport:
    """
    Complete cross-asset opportunity ranking for a decision cycle.

    This is a passive report. It does not route orders or allocate capital.
    It ranks opportunities for Board or downstream allocation review.
    """
    timestamp_ns: int
    total_equity_usd: Decimal
    available_capital_usd: Decimal
    opportunities: Tuple[OpportunityRank, ...]
    total_ranked: int
    total_skipped: int
    top_opportunity: Optional[str] = None
    top_opportunity_score: Decimal = Decimal("0")
    correlation_matrix_available: bool = False
    assumptions: Tuple[str, ...] = field(default_factory=tuple)


# ────────────────────────────────────────────────────────────────
# Opportunity Ranker (Passive)
# ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class OpportunityRanker:
    """
    Stateless opportunity ranking engine.

    Ranks potential signals by expected net edge after costs,
    capacity constraints, correlation penalties, and drawdown state.

    This is passive: it does not allocate, route, or execute.
    """
    min_net_edge_bps: Decimal = Decimal("5.0")       # Minimum net edge to consider
    min_confidence: Decimal = Decimal("0.50")         # Minimum signal confidence
    max_correlation_penalty: Decimal = Decimal("0.50")  # Max reduction from correlation
    max_single_position_pct: Decimal = Decimal("0.25")  # Max single position as % equity

    def rank(
        self,
        candidates: List[Tuple[str, str, Decimal, Decimal, Decimal]],
        # (instrument_id, strategy_id, gross_edge_bps, confidence, max_notional)
        instruments: Dict[str, InstrumentProfile],
        existing_exposures: Dict[str, Decimal],       # symbol -> notional_usd
        correlation_pairs: Optional[Dict[Tuple[str, str], Decimal]] = None,
        total_equity: Decimal = Decimal("20000"),
        available_capital: Decimal = Decimal("20000"),
        timestamp_ns: int = 0,
    ) -> OpportunityRankingReport:
        """
        Rank opportunities across instruments.

        Args:
            candidates: List of (instrument_id, strategy_id, gross_edge_bps, confidence, max_notional)
            instruments: Instrument profiles
            existing_exposures: Current positions
            correlation_pairs: Optional correlation matrix
            total_equity: Total portfolio equity
            available_capital: Capital available for new positions
            timestamp_ns: Report timestamp

        Returns:
            OpportunityRankingReport (passive, no authority)
        """
        rankings: List[OpportunityRank] = []
        skipped = 0

        for i, (inst_id, strat_id, gross_edge, conf, max_notional) in enumerate(candidates):
            instrument = instruments.get(inst_id)
            if not instrument:
                skipped += 1
                continue

            # Cost estimation (simplified for G0)
            fee_bps = Decimal("2.0")  # Placeholder
            spread_bps = instrument.constraints.max_spread_bps if hasattr(instrument, 'constraints') else Decimal("2.0")
            impact_bps = Decimal("2.0")
            total_cost_bps = fee_bps + spread_bps + impact_bps
            net_edge_bps = gross_edge - total_cost_bps

            cost_breakdown = OpportunityCostBreakdown(
                expected_gross_edge_bps=gross_edge,
                explicit_fee_bps=fee_bps,
                spread_cost_bps=spread_bps,
                impact_cost_bps=impact_bps,
                borrow_cost_bps=Decimal("0"),
                funding_cost_bps=Decimal("0"),
                regulatory_cost_bps=Decimal("0"),
                total_cost_bps=total_cost_bps,
                net_edge_bps=net_edge_bps,
            )

            # Check skip conditions
            skip_reasons: List[str] = []
            if net_edge_bps < self.min_net_edge_bps:
                skip_reasons.append(SkipReason.NEGATIVE_NET_EDGE.value)
            if conf < self.min_confidence:
                skip_reasons.append(SkipReason.BELOW_MIN_CONFIDENCE.value)

            # Capacity
            position_notional = min(max_notional, available_capital * self.max_single_position_pct)
            capacity = OpportunityCapacity(
                instrument_symbol=inst_id,
                max_position_notional=max_notional,
                max_order_notional=Decimal("0"),
                available_capital=available_capital,
                position_after_alloc=position_notional,
                remaining_capacity_pct=Decimal("100"),
                is_capacity_constrained=position_notional < max_notional,
            )

            # Correlation penalty
            corr_penalty: Optional[OpportunityCorrelationPenalty] = None
            correlation_score = Decimal("0")
            if correlation_pairs and existing_exposures:
                corr_scores = []
                for existing_sym in existing_exposures:
                    pair = (inst_id, existing_sym)
                    if pair in correlation_pairs:
                        corr_scores.append(correlation_pairs[pair])
                if corr_scores:
                    correlation_score = sum(corr_scores) / len(corr_scores)
                    penalty = Decimal("1.0") - abs(correlation_score) * self.max_correlation_penalty
                    corr_penalty = OpportunityCorrelationPenalty(
                        correlated_symbols=tuple(existing_exposures.keys()),
                        correlation_score=correlation_score,
                        penalty_factor=penalty,
                        diversification_bonus=Decimal("1.0") - abs(correlation_score),
                    )

            # Composite score
            confidence_factor = conf
            net_edge_score = max(Decimal("0"), min(Decimal("1"), net_edge_bps / Decimal("50")))
            diversification_score = Decimal("1.0") - abs(correlation_score) if correlation_score else Decimal("0.5")

            composite_conf = (
                confidence_factor * Decimal("0.4") +
                net_edge_score * Decimal("0.35") +
                diversification_score * Decimal("0.25")
            )

            # Grade
            grade = OpportunityGrade.F
            if not skip_reasons and composite_conf > Decimal("0.80"):
                grade = OpportunityGrade.A
            elif not skip_reasons and composite_conf > Decimal("0.60"):
                grade = OpportunityGrade.B
            elif not skip_reasons and composite_conf > Decimal("0.40"):
                grade = OpportunityGrade.C
            elif not skip_reasons:
                grade = OpportunityGrade.D

            if skip_reasons:
                grade = OpportunityGrade.F

            rank = OpportunityRank(
                rank=0,  # Assigned after sorting
                instrument_id=inst_id,
                symbol=instrument.symbol,
                strategy_id=strat_id,
                expected_gross_edge_bps=gross_edge,
                cost_breakdown=cost_breakdown,
                signal_confidence=conf,
                composite_confidence=composite_conf,
                capacity=capacity,
                target_allocation_notional=position_notional,
                target_allocation_pct=position_notional / total_equity if total_equity > 0 else Decimal("0"),
                correlation_penalty=corr_penalty,
                net_edge_after_all=net_edge_bps,
                grade=grade,
                score=composite_conf,
                skip=len(skip_reasons) > 0,
                skip_reasons=tuple(skip_reasons),
                timestamp_ns=timestamp_ns,
            )
            rankings.append(rank)

        # Sort: skip=False first, then descending by composite_confidence
        rankings.sort(key=lambda r: (r.skip, -float(r.composite_confidence)))
        for i, r in enumerate(rankings):
            object.__setattr__(r, 'rank', i + 1)

        skipped_count = sum(1 for r in rankings if r.skip)
        top = rankings[0] if rankings else None

        return OpportunityRankingReport(
            timestamp_ns=timestamp_ns,
            total_equity_usd=total_equity,
            available_capital_usd=available_capital,
            opportunities=tuple(rankings),
            total_ranked=len(rankings),
            total_skipped=skipped_count,
            top_opportunity=top.symbol if top else None,
            top_opportunity_score=top.score if top else Decimal("0"),
            assumptions=("pre_integration", "estimated_costs", "no_live_correlation_data"),
        )


def summarize_opportunity_ranking(report: OpportunityRankingReport) -> Dict[str, object]:
    """
    Build passive ranking telemetry for DecisionRecord metadata.

    This does not allocate, size orders, route, or execute. Cost fields remain
    the report's own assumptions and are not broker truth or profitability.
    """
    if report.top_opportunity is None:
        status = "ABSTAIN"
        reason = "NO_RANKABLE_OPPORTUNITY"
    elif report.total_ranked == report.total_skipped:
        status = "ABSTAIN"
        reason = "ALL_OPPORTUNITIES_SKIPPED"
    else:
        status = "RANKED"
        reason = "PASSIVE_OPPORTUNITY_RANKING_COMPLETE"

    return {
        "module_name": "opportunity_ranking",
        "category": "opportunity_ranking",
        "status": status,
        "effect": "RANK" if status == "RANKED" else "NO_EFFECT_WITH_REASON",
        "reason": reason,
        "top_opportunity": report.top_opportunity,
        "total_ranked": report.total_ranked,
        "total_skipped": report.total_skipped,
        "assumptions": report.assumptions,
        "execution_authority": "none",
    }


# ────────────────────────────────────────────────────────────────
# Module Exports
# ────────────────────────────────────────────────────────────────

__all__ = [
    "OpportunityGrade",
    "SkipReason",
    "OpportunityCostBreakdown",
    "OpportunityCapacity",
    "OpportunityCorrelationPenalty",
    "OpportunityRank",
    "OpportunityRankingReport",
    "OpportunityRanker",
    "summarize_opportunity_ranking",
]
