"""
app/strategies/hedging_flow.py
POVERTY_KILLER — CANONICAL HEDGING FLOW AUTHORITY (CITADEL-GRADE)

This module provides a preserve-aware, institution-grade hedging analysis layer
for portfolio delta stabilization. It is designed to remain subordinate to the
canonical execution authority (orchestrator), while supplying deterministic,
typed hedge assessments and executable recommendations.

ARCHITECTURAL ROLE
------------------
- This module does NOT possess final execution authority.
- It analyzes portfolio delta imbalance and proposes canonical hedge intent.
- Orchestrator / risk / router remain the final arbiters of execution.

DESIGN PRINCIPLES
-----------------
1. Analysis / Recommendation Split
   Hedge need assessment is separated from execution recommendation.

2. Canonical Structured Output
   Loose dicts are replaced internally by typed models. A legacy adapter can
   still emit compatibility dicts when needed.

3. State-Aware Hedging
   Outstanding/pending hedge exposure is included to avoid over-hedging.

4. Stability Over Churn
   Cooldown, hysteresis, residual bands, and urgency grading reduce hedge
   oscillation and microstructural self-harm.

5. Risk / Regime / Liquidity Integration
   Hedge recommendations are shaped by market structure, risk authority,
   liquidity conditions, and operational mode.

6. Replay-Friendly Determinism
   Inputs and outputs are explicit and serializable for audit and reconstruction.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Any, Dict, List, Optional, Sequence

from app.utils.enums import (
    AuthorityTier,
    BookIntegrity,
    CancelReason,
    DegradationMode,
    EventSource,
    ExecutionConstraint,
    ExecutionMode,
    HazardVelocity,
    LiquidityRegime,
    Marketability,
    OrderSide,
    OrderType,
    PriorityClass,
    RegimeType,
    ReplayMode,
    RiskAction,
    RiskLevel,
    RiskVetoReason,
    SignalDirection,
    SlippageClass,
    TimeInForce,
    ToxicityLevel,
    TradeIntent,
    is_blocking_risk_action,
    is_crisis_regime,
    is_high_risk_level,
)
from app.utils.ids import generate_correlation_id, generate_request_id

logger = logging.getLogger(__name__)


# ============================================================================
# CONSTANTS
# ============================================================================

ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")


# ============================================================================
# HELPERS
# ============================================================================

def _d(value: Any, *, field_name: str) -> Decimal:
    """
    Safe Decimal conversion with field-specific error context.
    """
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


def _clamp(value: Decimal, lower: Decimal, upper: Decimal) -> Decimal:
    if value < lower:
        return lower
    if value > upper:
        return upper
    return value


def _quantize_down(value: Decimal, step: Decimal) -> Decimal:
    """
    Round down to executable step.
    """
    if step <= ZERO:
        return value
    units = (value / step).to_integral_value(rounding=ROUND_DOWN)
    return units * step


def _now_ms() -> int:
    return int(time.time() * 1000)


def _safe_str(obj: Any) -> str:
    return "" if obj is None else str(obj)


# ============================================================================
# MODELS
# ============================================================================

@dataclass(frozen=True, slots=True)
class HedgePolicyConfig:
    """
    Canonical hedge policy.

    threshold_enter:
        absolute delta_pct required to enter hedge mode

    threshold_exit:
        lower band below threshold_enter required to stop hedge pressure
        (hysteresis control)

    target_residual_delta_pct:
        intentional neutrality band after hedging; prevents over-precision churn

    min_rebalance_delta_pct:
        minimum absolute remaining imbalance required to justify another hedge

    cooldown_ms:
        minimum interval between non-urgent hedge recommendations

    max_hedge_notional:
        hard cap on any single recommendation notional

    max_hedge_ratio:
        cap on proportional hedge application (e.g. 1.0 = 100%)

    min_order_notional:
        don't emit dust hedges below executable economic threshold

    quantity_step:
        quantity rounding increment

    minimum_price:
        rejects invalid/stale/zero-ish price basis
    """
    threshold_enter: Decimal = Decimal("0.0500")
    threshold_exit: Decimal = Decimal("0.0300")
    target_residual_delta_pct: Decimal = Decimal("0.0100")
    min_rebalance_delta_pct: Decimal = Decimal("0.0050")
    cooldown_ms: int = 1_500
    max_hedge_notional: Decimal = Decimal("50000")
    max_hedge_ratio: Decimal = Decimal("1.0000")
    min_order_notional: Decimal = Decimal("25")
    quantity_step: Decimal = Decimal("0.0001")
    minimum_price: Decimal = Decimal("0.00000001")
    prefer_passive_in_benign_regimes: bool = True
    allow_crossing_in_urgent_mode: bool = True
    allow_hedging_in_safe_mode: bool = True
    emergency_force_ioc: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "threshold_enter", _ensure_non_negative(_d(self.threshold_enter, field_name="threshold_enter"), "threshold_enter"))
        object.__setattr__(self, "threshold_exit", _ensure_non_negative(_d(self.threshold_exit, field_name="threshold_exit"), "threshold_exit"))
        object.__setattr__(self, "target_residual_delta_pct", _ensure_non_negative(_d(self.target_residual_delta_pct, field_name="target_residual_delta_pct"), "target_residual_delta_pct"))
        object.__setattr__(self, "min_rebalance_delta_pct", _ensure_non_negative(_d(self.min_rebalance_delta_pct, field_name="min_rebalance_delta_pct"), "min_rebalance_delta_pct"))
        object.__setattr__(self, "max_hedge_notional", _ensure_positive(_d(self.max_hedge_notional, field_name="max_hedge_notional"), "max_hedge_notional"))
        object.__setattr__(self, "max_hedge_ratio", _clamp(_d(self.max_hedge_ratio, field_name="max_hedge_ratio"), ZERO, ONE))
        object.__setattr__(self, "min_order_notional", _ensure_non_negative(_d(self.min_order_notional, field_name="min_order_notional"), "min_order_notional"))
        object.__setattr__(self, "quantity_step", _ensure_positive(_d(self.quantity_step, field_name="quantity_step"), "quantity_step"))
        object.__setattr__(self, "minimum_price", _ensure_positive(_d(self.minimum_price, field_name="minimum_price"), "minimum_price"))

        if self.threshold_exit > self.threshold_enter:
            raise ValueError("threshold_exit cannot exceed threshold_enter")
        if self.target_residual_delta_pct > self.threshold_enter:
            raise ValueError("target_residual_delta_pct cannot exceed threshold_enter")
        if self.cooldown_ms < 0:
            raise ValueError("cooldown_ms must be >= 0")


@dataclass(frozen=True, slots=True)
class HedgeMarketContext:
    symbol: str
    price: Decimal
    bid: Optional[Decimal] = None
    ask: Optional[Decimal] = None
    mid: Optional[Decimal] = None
    mark_price: Optional[Decimal] = None
    market_data_age_ms: Optional[int] = None
    liquidity_regime: LiquidityRegime = LiquidityRegime.UNKNOWN
    toxicity_level: ToxicityLevel = ToxicityLevel.UNKNOWN
    book_integrity: BookIntegrity = BookIntegrity.UNKNOWN
    slippage_class: SlippageClass = SlippageClass.UNKNOWN
    regime: RegimeType = RegimeType.UNKNOWN
    execution_mode: ExecutionMode = ExecutionMode.LIVE
    degradation_mode: DegradationMode = DegradationMode.NORMAL
    replay_mode: ReplayMode = ReplayMode.LIVE

    def __post_init__(self) -> None:
        object.__setattr__(self, "price", _ensure_positive(_d(self.price, field_name="price"), "price"))
        if self.bid is not None:
            object.__setattr__(self, "bid", _ensure_positive(_d(self.bid, field_name="bid"), "bid"))
        if self.ask is not None:
            object.__setattr__(self, "ask", _ensure_positive(_d(self.ask, field_name="ask"), "ask"))
        if self.mid is not None:
            object.__setattr__(self, "mid", _ensure_positive(_d(self.mid, field_name="mid"), "mid"))
        if self.mark_price is not None:
            object.__setattr__(self, "mark_price", _ensure_positive(_d(self.mark_price, field_name="mark_price"), "mark_price"))
        if self.market_data_age_ms is not None and self.market_data_age_ms < 0:
            raise ValueError("market_data_age_ms must be >= 0")


@dataclass(frozen=True, slots=True)
class HedgeRiskContext:
    risk_level: RiskLevel = RiskLevel.NONE
    risk_action: RiskAction = RiskAction.ALLOW
    hazard_velocity: HazardVelocity = HazardVelocity.STABLE
    veto_reason: Optional[RiskVetoReason] = None
    blocked_buy: bool = False
    blocked_sell: bool = False
    safe_mode_active: bool = False
    kill_switch_active: bool = False


@dataclass(frozen=True, slots=True)
class PortfolioExposureSnapshot:
    """
    Canonical portfolio exposure state for hedge analysis.
    """
    net_delta: Decimal
    gross_delta: Optional[Decimal] = None
    effective_delta: Optional[Decimal] = None
    hedge_inventory_qty: Decimal = ZERO
    pending_hedge_buy_qty: Decimal = ZERO
    pending_hedge_sell_qty: Decimal = ZERO
    total_equity: Decimal = Decimal("1")
    contract_multiplier: Decimal = ONE
    hedge_beta: Decimal = ONE
    target_symbol: Optional[str] = None
    snapshot_age_ms: Optional[int] = None
    source: EventSource = EventSource.STRATEGY
    sleeve: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "net_delta", _d(self.net_delta, field_name="net_delta"))
        object.__setattr__(self, "gross_delta", None if self.gross_delta is None else _ensure_non_negative(_d(self.gross_delta, field_name="gross_delta"), "gross_delta"))
        object.__setattr__(self, "effective_delta", None if self.effective_delta is None else _d(self.effective_delta, field_name="effective_delta"))
        object.__setattr__(self, "hedge_inventory_qty", _d(self.hedge_inventory_qty, field_name="hedge_inventory_qty"))
        object.__setattr__(self, "pending_hedge_buy_qty", _ensure_non_negative(_d(self.pending_hedge_buy_qty, field_name="pending_hedge_buy_qty"), "pending_hedge_buy_qty"))
        object.__setattr__(self, "pending_hedge_sell_qty", _ensure_non_negative(_d(self.pending_hedge_sell_qty, field_name="pending_hedge_sell_qty"), "pending_hedge_sell_qty"))
        object.__setattr__(self, "total_equity", _ensure_positive(_d(self.total_equity, field_name="total_equity"), "total_equity"))
        object.__setattr__(self, "contract_multiplier", _ensure_positive(_d(self.contract_multiplier, field_name="contract_multiplier"), "contract_multiplier"))
        object.__setattr__(self, "hedge_beta", _ensure_positive(_d(self.hedge_beta, field_name="hedge_beta"), "hedge_beta"))

        if self.snapshot_age_ms is not None and self.snapshot_age_ms < 0:
            raise ValueError("snapshot_age_ms must be >= 0")


@dataclass(frozen=True, slots=True)
class HedgeUrgencyProfile:
    """
    Urgency ladder mapped from normalized imbalance.
    """
    name: str
    priority: PriorityClass
    authority_tier: AuthorityTier
    order_type: OrderType
    tif: TimeInForce
    marketability: Marketability
    constraints: tuple[ExecutionConstraint, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class HedgeAssessment:
    """
    Canonical analysis output. No execution authority implied.
    """
    assessment_id: int
    correlation_id: int
    timestamp_ms: int

    symbol: str
    sleeve: Optional[str]

    hedge_required: bool
    hedge_permitted: bool
    suppress_reason: Optional[str]

    source_net_delta: Decimal
    effective_delta: Decimal
    total_equity: Decimal

    raw_delta_pct: Decimal
    effective_delta_pct: Decimal
    target_residual_delta_pct: Decimal

    pending_hedge_net_qty: Decimal
    existing_hedge_inventory_qty: Decimal

    required_offset_qty_raw: Decimal
    required_offset_qty_after_pending: Decimal
    capped_offset_qty: Decimal
    final_offset_qty: Decimal
    expected_post_hedge_delta: Decimal
    expected_post_hedge_delta_pct: Decimal

    side: Optional[OrderSide]
    urgency: str
    priority: PriorityClass
    authority_tier: AuthorityTier

    regime: RegimeType
    liquidity_regime: LiquidityRegime
    toxicity_level: ToxicityLevel
    book_integrity: BookIntegrity
    risk_level: RiskLevel
    risk_action: RiskAction
    hazard_velocity: HazardVelocity

    rationale: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class HedgeRecommendation:
    """
    Canonical hedge recommendation for orchestrator/risk/router review.
    """
    recommendation_id: int
    correlation_id: int
    assessment_id: int
    created_at_ms: int

    symbol: str
    side: OrderSide
    quantity: Decimal
    estimated_notional: Decimal

    order_type: OrderType
    time_in_force: TimeInForce
    execution_constraints: tuple[ExecutionConstraint, ...]

    trade_intent: TradeIntent
    signal_direction: SignalDirection
    marketability: Marketability

    urgency: str
    priority: PriorityClass
    authority_tier: AuthorityTier

    regime: RegimeType
    liquidity_regime: LiquidityRegime
    toxicity_level: ToxicityLevel
    risk_level: RiskLevel
    risk_action: RiskAction

    is_hedge: bool = True
    source_module: str = "app.strategies.hedging_flow"
    replay_mode: ReplayMode = ReplayMode.LIVE
    execution_mode: ExecutionMode = ExecutionMode.LIVE
    rationale: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_legacy_dict(self) -> Dict[str, Any]:
        """
        Compatibility adapter for legacy callers expecting the old dict shape.
        """
        return {
            "side": self.side,
            "quantity": self.quantity,
            "order_type": self.order_type,
            "time_in_force": self.time_in_force,
            "is_hedge": self.is_hedge,

            # safe additive metadata
            "symbol": self.symbol,
            "estimated_notional": self.estimated_notional,
            "trade_intent": self.trade_intent,
            "signal_direction": self.signal_direction,
            "urgency": self.urgency,
            "priority": self.priority,
            "authority_tier": self.authority_tier,
            "execution_constraints": list(self.execution_constraints),
            "correlation_id": self.correlation_id,
            "recommendation_id": self.recommendation_id,
        }


# ============================================================================
# HEDGING FLOW ENGINE
# ============================================================================

class HedgingFlow:
    """
    Sovereign Neutrality Analysis Authority.

    Backward-aware:
    - preserves the legacy evaluate_hedging_need(...) entrypoint
    - adds canonical assess(...) and recommend(...) stages
    """

    def __init__(
        self,
        delta_threshold: Decimal = Decimal("0.05"),
        hedge_ratio: Decimal = Decimal("1.0"),
        max_hedge_notional: Decimal = Decimal("50000.0"),
        *,
        policy: Optional[HedgePolicyConfig] = None,
    ) -> None:
        if policy is None:
            policy = HedgePolicyConfig(
                threshold_enter=_d(delta_threshold, field_name="delta_threshold"),
                threshold_exit=min(
                    _d(delta_threshold, field_name="delta_threshold"),
                    Decimal("0.03"),
                ),
                max_hedge_notional=_d(max_hedge_notional, field_name="max_hedge_notional"),
                max_hedge_ratio=_d(hedge_ratio, field_name="hedge_ratio"),
            )

        self.policy = policy
        self._last_hedge_ms: Optional[int] = None
        self._last_hedge_side: Optional[OrderSide] = None
        self._last_effective_delta_pct: Optional[Decimal] = None
        self._in_hedge_mode: bool = False

    # ------------------------------------------------------------------
    # Public canonical API
    # ------------------------------------------------------------------

    def assess(
        self,
        exposure: PortfolioExposureSnapshot,
        market: HedgeMarketContext,
        risk: Optional[HedgeRiskContext] = None,
    ) -> HedgeAssessment:
        """
        Analyze hedge need and return canonical hedge assessment.
        """
        risk = risk or HedgeRiskContext()
        ts_ms = _now_ms()
        assessment_id = generate_request_id()
        correlation_id = generate_correlation_id()

        rationale: List[str] = []
        warnings: List[str] = []

        symbol = exposure.target_symbol or market.symbol
        price = market.mark_price or market.mid or market.price

        if price < self.policy.minimum_price:
            return self._blocked_assessment(
                assessment_id=assessment_id,
                correlation_id=correlation_id,
                timestamp_ms=ts_ms,
                exposure=exposure,
                market=market,
                risk=risk,
                symbol=symbol,
                suppress_reason=f"invalid_price_basis<{self.policy.minimum_price}",
            )

        if market.market_data_age_ms is not None and market.market_data_age_ms > 10_000:
            warnings.append(f"stale_market_data:{market.market_data_age_ms}ms")

        if exposure.snapshot_age_ms is not None and exposure.snapshot_age_ms > 10_000:
            warnings.append(f"stale_exposure_snapshot:{exposure.snapshot_age_ms}ms")

        if market.book_integrity in {BookIntegrity.STALE, BookIntegrity.UNTRUSTWORTHY, BookIntegrity.CROSSED}:
            warnings.append(f"book_integrity={market.book_integrity.value}")

        raw_effective_delta = exposure.effective_delta if exposure.effective_delta is not None else exposure.net_delta
        raw_delta_pct = exposure.net_delta / exposure.total_equity
        effective_delta_pct = raw_effective_delta / exposure.total_equity

        pending_hedge_net_qty = exposure.pending_hedge_buy_qty - exposure.pending_hedge_sell_qty
        pending_hedge_delta_offset = pending_hedge_net_qty * price * exposure.contract_multiplier * exposure.hedge_beta
        hedge_inventory_delta_offset = exposure.hedge_inventory_qty * price * exposure.contract_multiplier * exposure.hedge_beta

        # Effective delta after existing hedge inventory + pending hedge flows
        adjusted_effective_delta = raw_effective_delta + hedge_inventory_delta_offset + pending_hedge_delta_offset
        adjusted_effective_delta_pct = adjusted_effective_delta / exposure.total_equity

        rationale.append(f"raw_delta_pct={raw_delta_pct}")
        rationale.append(f"adjusted_effective_delta_pct={adjusted_effective_delta_pct}")

        # Hedge mode with hysteresis
        abs_delta_pct = abs(adjusted_effective_delta_pct)

        if self._in_hedge_mode:
            if abs_delta_pct <= self.policy.threshold_exit:
                self._in_hedge_mode = False
                rationale.append("hedge_mode_exit:hysteresis")
        else:
            if abs_delta_pct >= self.policy.threshold_enter:
                self._in_hedge_mode = True
                rationale.append("hedge_mode_enter:threshold")

        if not self._in_hedge_mode:
            return HedgeAssessment(
                assessment_id=assessment_id,
                correlation_id=correlation_id,
                timestamp_ms=ts_ms,
                symbol=symbol,
                sleeve=exposure.sleeve,
                hedge_required=False,
                hedge_permitted=True,
                suppress_reason="below_hysteresis_band",
                source_net_delta=exposure.net_delta,
                effective_delta=adjusted_effective_delta,
                total_equity=exposure.total_equity,
                raw_delta_pct=raw_delta_pct,
                effective_delta_pct=adjusted_effective_delta_pct,
                target_residual_delta_pct=self.policy.target_residual_delta_pct,
                pending_hedge_net_qty=pending_hedge_net_qty,
                existing_hedge_inventory_qty=exposure.hedge_inventory_qty,
                required_offset_qty_raw=ZERO,
                required_offset_qty_after_pending=ZERO,
                capped_offset_qty=ZERO,
                final_offset_qty=ZERO,
                expected_post_hedge_delta=adjusted_effective_delta,
                expected_post_hedge_delta_pct=adjusted_effective_delta_pct,
                side=None,
                urgency="NONE",
                priority=PriorityClass.DEFERRED,
                authority_tier=AuthorityTier.ADVISORY,
                regime=market.regime,
                liquidity_regime=market.liquidity_regime,
                toxicity_level=market.toxicity_level,
                book_integrity=market.book_integrity,
                risk_level=risk.risk_level,
                risk_action=risk.risk_action,
                hazard_velocity=risk.hazard_velocity,
                rationale=tuple(rationale),
                warnings=tuple(warnings),
            )

        if self._is_risk_blocked(risk):
            return self._blocked_assessment(
                assessment_id=assessment_id,
                correlation_id=correlation_id,
                timestamp_ms=ts_ms,
                exposure=exposure,
                market=market,
                risk=risk,
                symbol=symbol,
                suppress_reason=self._risk_block_reason(risk),
                effective_delta=adjusted_effective_delta,
                effective_delta_pct=adjusted_effective_delta_pct,
                pending_hedge_net_qty=pending_hedge_net_qty,
                rationale=rationale,
                warnings=warnings,
            )

        urgency_profile = self._classify_urgency(
            abs_delta_pct=abs_delta_pct,
            market=market,
            risk=risk,
        )

        target_residual_delta = exposure.total_equity * self.policy.target_residual_delta_pct
        signed_target_residual = target_residual_delta if adjusted_effective_delta >= ZERO else -target_residual_delta

        delta_to_neutralize = adjusted_effective_delta - signed_target_residual
        hedgeable_delta = delta_to_neutralize * self.policy.max_hedge_ratio

        denom = price * exposure.contract_multiplier * exposure.hedge_beta
        required_offset_qty_raw = -(hedgeable_delta / denom)

        required_offset_notional = abs(required_offset_qty_raw) * price * exposure.contract_multiplier
        max_qty_by_notional = self.policy.max_hedge_notional / (price * exposure.contract_multiplier)
        capped_qty_abs = min(abs(required_offset_qty_raw), max_qty_by_notional)
        capped_offset_qty = capped_qty_abs if required_offset_qty_raw >= ZERO else -capped_qty_abs

        final_offset_qty = _quantize_down(abs(capped_offset_qty), self.policy.quantity_step)
        if capped_offset_qty < ZERO:
            final_offset_qty = -final_offset_qty

        expected_post_hedge_delta = adjusted_effective_delta + (
            final_offset_qty * price * exposure.contract_multiplier * exposure.hedge_beta
        )
        expected_post_hedge_delta_pct = expected_post_hedge_delta / exposure.total_equity

        if abs(expected_post_hedge_delta_pct) < self.policy.min_rebalance_delta_pct:
            rationale.append("residual_within_min_rebalance_band")

        side: Optional[OrderSide]
        if final_offset_qty > ZERO:
            side = OrderSide.BUY
        elif final_offset_qty < ZERO:
            side = OrderSide.SELL
        else:
            side = None

        if side == OrderSide.BUY and risk.blocked_buy:
            return self._blocked_assessment(
                assessment_id=assessment_id,
                correlation_id=correlation_id,
                timestamp_ms=ts_ms,
                exposure=exposure,
                market=market,
                risk=risk,
                symbol=symbol,
                suppress_reason="risk_blocked_buy",
                effective_delta=adjusted_effective_delta,
                effective_delta_pct=adjusted_effective_delta_pct,
                pending_hedge_net_qty=pending_hedge_net_qty,
                rationale=rationale,
                warnings=warnings,
            )

        if side == OrderSide.SELL and risk.blocked_sell:
            return self._blocked_assessment(
                assessment_id=assessment_id,
                correlation_id=correlation_id,
                timestamp_ms=ts_ms,
                exposure=exposure,
                market=market,
                risk=risk,
                symbol=symbol,
                suppress_reason="risk_blocked_sell",
                effective_delta=adjusted_effective_delta,
                effective_delta_pct=adjusted_effective_delta_pct,
                pending_hedge_net_qty=pending_hedge_net_qty,
                rationale=rationale,
                warnings=warnings,
            )

        return HedgeAssessment(
            assessment_id=assessment_id,
            correlation_id=correlation_id,
            timestamp_ms=ts_ms,
            symbol=symbol,
            sleeve=exposure.sleeve,
            hedge_required=side is not None and abs(final_offset_qty) > ZERO,
            hedge_permitted=True,
            suppress_reason=None,
            source_net_delta=exposure.net_delta,
            effective_delta=adjusted_effective_delta,
            total_equity=exposure.total_equity,
            raw_delta_pct=raw_delta_pct,
            effective_delta_pct=adjusted_effective_delta_pct,
            target_residual_delta_pct=self.policy.target_residual_delta_pct,
            pending_hedge_net_qty=pending_hedge_net_qty,
            existing_hedge_inventory_qty=exposure.hedge_inventory_qty,
            required_offset_qty_raw=required_offset_qty_raw,
            required_offset_qty_after_pending=required_offset_qty_raw,
            capped_offset_qty=capped_offset_qty,
            final_offset_qty=final_offset_qty,
            expected_post_hedge_delta=expected_post_hedge_delta,
            expected_post_hedge_delta_pct=expected_post_hedge_delta_pct,
            side=side,
            urgency=urgency_profile.name,
            priority=urgency_profile.priority,
            authority_tier=urgency_profile.authority_tier,
            regime=market.regime,
            liquidity_regime=market.liquidity_regime,
            toxicity_level=market.toxicity_level,
            book_integrity=market.book_integrity,
            risk_level=risk.risk_level,
            risk_action=risk.risk_action,
            hazard_velocity=risk.hazard_velocity,
            rationale=tuple(rationale),
            warnings=tuple(warnings),
        )

    def recommend(
        self,
        assessment: HedgeAssessment,
        market: HedgeMarketContext,
    ) -> Optional[HedgeRecommendation]:
        """
        Convert a hedge assessment into canonical execution recommendation.
        """
        if not assessment.hedge_required or not assessment.hedge_permitted:
            return None

        if assessment.side is None or assessment.final_offset_qty == ZERO:
            return None

        now_ms = _now_ms()

        if self._is_cooldown_active(now_ms, assessment.urgency):
            logger.info(
                "[HEDGE_FLOW] suppressed_by_cooldown symbol=%s urgency=%s qty=%s",
                assessment.symbol,
                assessment.urgency,
                assessment.final_offset_qty,
            )
            return None

        urgency_profile = self._profile_from_assessment(assessment, market)
        quantity = abs(assessment.final_offset_qty)
        estimated_notional = quantity * market.price

        if estimated_notional < self.policy.min_order_notional:
            logger.info(
                "[HEDGE_FLOW] suppressed_below_min_notional symbol=%s notional=%s threshold=%s",
                assessment.symbol,
                estimated_notional,
                self.policy.min_order_notional,
            )
            return None

        signal_direction = (
            SignalDirection.LONG if assessment.side == OrderSide.BUY else SignalDirection.SHORT
        )

        recommendation = HedgeRecommendation(
            recommendation_id=generate_request_id(),
            correlation_id=assessment.correlation_id,
            assessment_id=assessment.assessment_id,
            created_at_ms=now_ms,

            symbol=assessment.symbol,
            side=assessment.side,
            quantity=quantity,
            estimated_notional=estimated_notional,

            order_type=urgency_profile.order_type,
            time_in_force=urgency_profile.tif,
            execution_constraints=urgency_profile.constraints,

            trade_intent=TradeIntent.HEDGE,
            signal_direction=signal_direction,
            marketability=urgency_profile.marketability,

            urgency=assessment.urgency,
            priority=assessment.priority,
            authority_tier=assessment.authority_tier,

            regime=assessment.regime,
            liquidity_regime=assessment.liquidity_regime,
            toxicity_level=assessment.toxicity_level,
            risk_level=assessment.risk_level,
            risk_action=assessment.risk_action,

            replay_mode=market.replay_mode,
            execution_mode=market.execution_mode,
            rationale=assessment.rationale,
            warnings=assessment.warnings,
        )

        self._last_hedge_ms = now_ms
        self._last_hedge_side = assessment.side
        self._last_effective_delta_pct = assessment.effective_delta_pct

        logger.info(
            "[HEDGE_FLOW] recommendation symbol=%s side=%s qty=%s notional=%s urgency=%s "
            "order_type=%s tif=%s regime=%s liquidity=%s risk=%s/%s",
            recommendation.symbol,
            recommendation.side.value,
            recommendation.quantity,
            recommendation.estimated_notional,
            recommendation.urgency,
            recommendation.order_type.value,
            recommendation.time_in_force.value,
            recommendation.regime.name,
            recommendation.liquidity_regime.value,
            recommendation.risk_level.name,
            recommendation.risk_action.value,
        )

        return recommendation

    # ------------------------------------------------------------------
    # Legacy compatibility API
    # ------------------------------------------------------------------

    def evaluate_hedging_need(
        self,
        net_delta: Decimal,
        total_equity: Decimal,
        current_price: Decimal,
    ) -> Optional[Dict[str, Any]]:
        """
        Legacy compatibility facade.

        Preserves the old public method signature while delegating to the
        canonical assessment/recommendation pipeline.
        """
        exposure = PortfolioExposureSnapshot(
            net_delta=_d(net_delta, field_name="net_delta"),
            total_equity=_d(total_equity, field_name="total_equity"),
        )
        market = HedgeMarketContext(
            symbol="UNKNOWN",
            price=_d(current_price, field_name="current_price"),
        )
        risk = HedgeRiskContext()

        assessment = self.assess(exposure=exposure, market=market, risk=risk)
        recommendation = self.recommend(assessment=assessment, market=market)

        if recommendation is None:
            return None

        return recommendation.to_legacy_dict()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _blocked_assessment(
        self,
        *,
        assessment_id: int,
        correlation_id: int,
        timestamp_ms: int,
        exposure: PortfolioExposureSnapshot,
        market: HedgeMarketContext,
        risk: HedgeRiskContext,
        symbol: str,
        suppress_reason: str,
        effective_delta: Optional[Decimal] = None,
        effective_delta_pct: Optional[Decimal] = None,
        pending_hedge_net_qty: Decimal = ZERO,
        rationale: Optional[List[str]] = None,
        warnings: Optional[List[str]] = None,
    ) -> HedgeAssessment:
        rationale = rationale or []
        warnings = warnings or []
        rationale.append(f"suppressed:{suppress_reason}")

        source_effective_delta = effective_delta if effective_delta is not None else exposure.net_delta
        source_effective_delta_pct = (
            effective_delta_pct if effective_delta_pct is not None else (source_effective_delta / exposure.total_equity)
        )

        return HedgeAssessment(
            assessment_id=assessment_id,
            correlation_id=correlation_id,
            timestamp_ms=timestamp_ms,
            symbol=symbol,
            sleeve=exposure.sleeve,
            hedge_required=False,
            hedge_permitted=False,
            suppress_reason=suppress_reason,
            source_net_delta=exposure.net_delta,
            effective_delta=source_effective_delta,
            total_equity=exposure.total_equity,
            raw_delta_pct=exposure.net_delta / exposure.total_equity,
            effective_delta_pct=source_effective_delta_pct,
            target_residual_delta_pct=self.policy.target_residual_delta_pct,
            pending_hedge_net_qty=pending_hedge_net_qty,
            existing_hedge_inventory_qty=exposure.hedge_inventory_qty,
            required_offset_qty_raw=ZERO,
            required_offset_qty_after_pending=ZERO,
            capped_offset_qty=ZERO,
            final_offset_qty=ZERO,
            expected_post_hedge_delta=source_effective_delta,
            expected_post_hedge_delta_pct=source_effective_delta_pct,
            side=None,
            urgency="BLOCKED",
            priority=PriorityClass.URGENT,
            authority_tier=AuthorityTier.HARD_BLOCK,
            regime=market.regime,
            liquidity_regime=market.liquidity_regime,
            toxicity_level=market.toxicity_level,
            book_integrity=market.book_integrity,
            risk_level=risk.risk_level,
            risk_action=risk.risk_action,
            hazard_velocity=risk.hazard_velocity,
            rationale=tuple(rationale),
            warnings=tuple(warnings),
        )

    def _is_cooldown_active(self, now_ms: int, urgency: str) -> bool:
        """
        Cooldown applies only to non-urgent / non-critical hedge emissions.
        """
        if self._last_hedge_ms is None:
            return False

        if urgency in {"CRITICAL", "EMERGENCY"}:
            return False

        return (now_ms - self._last_hedge_ms) < self.policy.cooldown_ms

    def _is_risk_blocked(self, risk: HedgeRiskContext) -> bool:
        if risk.kill_switch_active:
            return True
        if risk.risk_action == RiskAction.KILL_SWITCH:
            return True
        if risk.risk_action == RiskAction.BLOCK_ALL_NEW:
            return True
        if risk.safe_mode_active and not self.policy.allow_hedging_in_safe_mode:
            return True
        return False

    def _risk_block_reason(self, risk: HedgeRiskContext) -> str:
        if risk.kill_switch_active or risk.risk_action == RiskAction.KILL_SWITCH:
            return "kill_switch_active"
        if risk.risk_action == RiskAction.BLOCK_ALL_NEW:
            return "risk_block_all_new"
        if risk.safe_mode_active and not self.policy.allow_hedging_in_safe_mode:
            return "safe_mode_disallows_hedging"
        if risk.veto_reason is not None:
            return f"risk_veto:{risk.veto_reason.value}"
        return "risk_blocked"

    def _classify_urgency(
        self,
        *,
        abs_delta_pct: Decimal,
        market: HedgeMarketContext,
        risk: HedgeRiskContext,
    ) -> HedgeUrgencyProfile:
        """
        Urgency ladder:
        - ELEVATED
        - HIGH
        - CRITICAL
        - EMERGENCY
        """
        crisis = is_crisis_regime(market.regime)
        high_risk = is_high_risk_level(risk.risk_level)
        toxic = market.toxicity_level in {ToxicityLevel.TOXIC, ToxicityLevel.EXTREME}
        fragile_book = market.book_integrity in {
            BookIntegrity.THIN,
            BookIntegrity.HOLLOW,
            BookIntegrity.FRAGMENTED,
            BookIntegrity.CROSSED,
            BookIntegrity.UNTRUSTWORTHY,
        }

        if (
            abs_delta_pct >= (self.policy.threshold_enter * Decimal("2.5"))
            or risk.hazard_velocity == HazardVelocity.DECAPITATING
            or risk.risk_action == RiskAction.FORCE_FLAT
        ):
            return HedgeUrgencyProfile(
                name="EMERGENCY",
                priority=PriorityClass.REALTIME,
                authority_tier=AuthorityTier.TERMINAL,
                order_type=OrderType.IOC if self.policy.emergency_force_ioc else OrderType.MARKET,
                tif=TimeInForce.IOC if self.policy.emergency_force_ioc else TimeInForce.DAY,
                marketability=Marketability.SWEEPING,
                constraints=(ExecutionConstraint.TAKER_ALLOWED,),
            )

        if abs_delta_pct >= (self.policy.threshold_enter * Decimal("1.75")) or crisis or high_risk:
            return HedgeUrgencyProfile(
                name="CRITICAL",
                priority=PriorityClass.REALTIME,
                authority_tier=AuthorityTier.HARD_BLOCK,
                order_type=OrderType.IOC if self.policy.allow_crossing_in_urgent_mode else OrderType.LIMIT,
                tif=TimeInForce.IOC if self.policy.allow_crossing_in_urgent_mode else TimeInForce.DAY,
                marketability=Marketability.CROSSING,
                constraints=(ExecutionConstraint.TAKER_ALLOWED,),
            )

        if abs_delta_pct >= (self.policy.threshold_enter * Decimal("1.25")) or toxic or fragile_book:
            return HedgeUrgencyProfile(
                name="HIGH",
                priority=PriorityClass.URGENT,
                authority_tier=AuthorityTier.SOFT_BLOCK,
                order_type=OrderType.LIMIT,
                tif=TimeInForce.IOC if self.policy.allow_crossing_in_urgent_mode else TimeInForce.DAY,
                marketability=Marketability.MARKETABLE,
                constraints=(ExecutionConstraint.TAKER_ALLOWED,),
            )

        if self.policy.prefer_passive_in_benign_regimes:
            return HedgeUrgencyProfile(
                name="ELEVATED",
                priority=PriorityClass.NORMAL,
                authority_tier=AuthorityTier.ADVISORY,
                order_type=OrderType.LIMIT,
                tif=TimeInForce.GTC,
                marketability=Marketability.PASSIVE,
                constraints=(ExecutionConstraint.POST_ONLY,),
            )

        return HedgeUrgencyProfile(
            name="ELEVATED",
            priority=PriorityClass.NORMAL,
            authority_tier=AuthorityTier.ADVISORY,
            order_type=OrderType.LIMIT,
            tif=TimeInForce.DAY,
            marketability=Marketability.NEAR_TOUCH,
            constraints=tuple(),
        )

    def _profile_from_assessment(
        self,
        assessment: HedgeAssessment,
        market: HedgeMarketContext,
    ) -> HedgeUrgencyProfile:
        """
        Stable derivation of recommendation style from assessment urgency.
        """
        abs_delta_pct = abs(assessment.effective_delta_pct)
        return self._classify_urgency(
            abs_delta_pct=abs_delta_pct,
            market=market,
            risk=HedgeRiskContext(
                risk_level=assessment.risk_level,
                risk_action=assessment.risk_action,
                hazard_velocity=assessment.hazard_velocity,
            ),
        )


__all__ = [
    "HedgePolicyConfig",
    "HedgeMarketContext",
    "HedgeRiskContext",
    "PortfolioExposureSnapshot",
    "HedgeUrgencyProfile",
    "HedgeAssessment",
    "HedgeRecommendation",
    "HedgingFlow",
]
