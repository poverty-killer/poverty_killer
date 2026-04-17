"""
app/risk/position_unwind.py
POVERTY_KILLER — CANONICAL POSITION UNWIND CAMPAIGN AUTHORITY (CITADEL-GRADE)

This module provides a stateful, replay-aware, campaign-based liquidation
controller for tactical and emergency flattening. It upgrades stateless unwind
planning into a deterministic liquidation campaign engine with:

- per-position liquidation assessment
- campaign lifecycle state
- symbol prioritization
- staged tranche planning
- retry / escalation logic
- execution feedback ingestion
- dust-aware completion logic
- backward-aware legacy compatibility

ARCHITECTURAL ROLE
------------------
- This module is a liquidation planning and campaign control authority.
- It does NOT directly execute orders.
- Orchestrator / router / execution engine remain sovereign over actual order flow.

DESIGN PRINCIPLES
-----------------
1. Campaign-State Over One-Shot Planning
   Unwinding is modeled as a persistent mission, not a single recommendation pass.

2. Replay and Recovery Safety
   Campaigns, attempts, statuses, and progress snapshots are explicit and
   serializable.

3. Controlled Escalation
   Failed or stalled liquidations move through deterministic aggression ladders.

4. Economic Flatness
   Completion is defined with quantity and notional dust tolerances, not naive zero.

5. Preserve-Aware Compatibility
   Legacy generate_unwind_intents(...) and evaluate_unwind_progress(...) are
   retained as compatibility facades over canonical campaign logic.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from enum import Enum, unique
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.utils.enums import (
    AuthorityTier,
    BookIntegrity,
    EventSource,
    ExecutionConstraint,
    ExecutionMode,
    FillLiquidity,
    LiquidityRegime,
    Marketability,
    OrderSide,
    OrderStatus,
    OrderType,
    PriorityClass,
    RegimeType,
    ReplayMode,
    RiskAction,
    RiskLevel,
    ToxicityLevel,
    TradeIntent,
    is_crisis_regime,
    is_high_risk_level,
)
from app.utils.ids import (
    generate_correlation_id,
    generate_order_cid,
    generate_order_id,
    generate_request_id,
)

logger = logging.getLogger(__name__)


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


def _quantize_down(value: Decimal, step: Decimal) -> Decimal:
    if step <= ZERO:
        return value
    units = (value / step).to_integral_value(rounding=ROUND_DOWN)
    return units * step


def _now_ms() -> int:
    return int(time.time() * 1000)


def _sign_side(quantity: Decimal) -> Optional[OrderSide]:
    if quantity > ZERO:
        return OrderSide.SELL
    if quantity < ZERO:
        return OrderSide.BUY
    return None


# ============================================================================
# CAMPAIGN ENUMS
# ============================================================================

@unique
class UnwindCampaignStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    PARTIAL_PROGRESS = "PARTIAL_PROGRESS"
    STALLED = "STALLED"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    ESCALATED = "ESCALATED"


@unique
class UnwindAttemptStatus(str, Enum):
    CREATED = "CREATED"
    DISPATCHED = "DISPATCHED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIAL_FILL = "PARTIAL_FILL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    STALE = "STALE"


@unique
class UnwindEscalationLevel(str, Enum):
    NONE = "NONE"
    TACTICAL = "TACTICAL"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
    EMERGENCY = "EMERGENCY"
    TERMINAL = "TERMINAL"


@unique
class UnwindProgressState(str, Enum):
    UNKNOWN = "UNKNOWN"
    COMPLETE = "COMPLETE"
    PARTIAL_PROGRESS = "PARTIAL_PROGRESS"
    STALLED = "STALLED"
    REGRESSED = "REGRESSED"
    AWAITING_ACK = "AWAITING_ACK"
    AWAITING_RECONCILIATION = "AWAITING_RECONCILIATION"


# ============================================================================
# CONFIG / INPUT MODELS
# ============================================================================

@dataclass(frozen=True, slots=True)
class UnwindPolicyConfig:
    """
    Canonical campaign policy.
    """
    max_retries: int = 3
    min_order_quantity: Decimal = Decimal("0.0001")
    quantity_step: Decimal = Decimal("0.0001")
    min_notional: Decimal = Decimal("25")
    economic_flat_qty: Decimal = Decimal("0.0001")
    economic_flat_notional: Decimal = Decimal("10")
    max_single_order_notional: Optional[Decimal] = Decimal("25000")
    allow_order_splitting: bool = True
    stale_position_threshold_ms: Optional[int] = 5_000
    stale_attempt_threshold_ms: int = 2_500
    suppress_on_untrustworthy_book: bool = False
    use_reduce_only_when_possible: bool = True
    emergency_force_ioc: bool = True
    commander_escalation_after_failures: int = 2
    allow_retry_after_partial_fill: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "min_order_quantity", _ensure_positive(_d(self.min_order_quantity, field_name="min_order_quantity"), "min_order_quantity"))
        object.__setattr__(self, "quantity_step", _ensure_positive(_d(self.quantity_step, field_name="quantity_step"), "quantity_step"))
        object.__setattr__(self, "min_notional", _ensure_non_negative(_d(self.min_notional, field_name="min_notional"), "min_notional"))
        object.__setattr__(self, "economic_flat_qty", _ensure_non_negative(_d(self.economic_flat_qty, field_name="economic_flat_qty"), "economic_flat_qty"))
        object.__setattr__(self, "economic_flat_notional", _ensure_non_negative(_d(self.economic_flat_notional, field_name="economic_flat_notional"), "economic_flat_notional"))
        if self.max_single_order_notional is not None:
            object.__setattr__(self, "max_single_order_notional", _ensure_positive(_d(self.max_single_order_notional, field_name="max_single_order_notional"), "max_single_order_notional"))
        if self.max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if self.stale_position_threshold_ms is not None and self.stale_position_threshold_ms < 0:
            raise ValueError("stale_position_threshold_ms must be >= 0")
        if self.stale_attempt_threshold_ms < 0:
            raise ValueError("stale_attempt_threshold_ms must be >= 0")
        if self.commander_escalation_after_failures < 0:
            raise ValueError("commander_escalation_after_failures must be >= 0")


@dataclass(frozen=True, slots=True)
class PositionSnapshot:
    symbol: str
    quantity: Decimal
    mark_price: Optional[Decimal] = None
    snapshot_age_ms: Optional[int] = None
    venue: Optional[str] = None
    source: EventSource = EventSource.RISK

    def __post_init__(self) -> None:
        object.__setattr__(self, "quantity", _d(self.quantity, field_name="quantity"))
        if self.mark_price is not None:
            object.__setattr__(self, "mark_price", _ensure_positive(_d(self.mark_price, field_name="mark_price"), "mark_price"))
        if self.snapshot_age_ms is not None and self.snapshot_age_ms < 0:
            raise ValueError("snapshot_age_ms must be >= 0")
        if not self.symbol:
            raise ValueError("symbol must be non-empty")


@dataclass(frozen=True, slots=True)
class UnwindMarketContext:
    regime: RegimeType = RegimeType.UNKNOWN
    liquidity_regime: LiquidityRegime = LiquidityRegime.UNKNOWN
    toxicity_level: ToxicityLevel = ToxicityLevel.UNKNOWN
    book_integrity: BookIntegrity = BookIntegrity.UNKNOWN
    execution_mode: ExecutionMode = ExecutionMode.LIVE
    replay_mode: ReplayMode = ReplayMode.LIVE


@dataclass(frozen=True, slots=True)
class UnwindRiskContext:
    risk_level: RiskLevel = RiskLevel.NONE
    risk_action: RiskAction = RiskAction.ALLOW
    hard_flat: bool = False
    kill_switch_active: bool = False
    safe_mode_active: bool = False


@dataclass(frozen=True, slots=True)
class UnwindOrderFeedback:
    """
    Canonical execution feedback consumed by the campaign controller.
    """
    symbol: str
    cid: str
    status: OrderStatus
    filled_qty: Decimal = ZERO
    remaining_qty: Optional[Decimal] = None
    average_fill_price: Optional[Decimal] = None
    fill_liquidity: FillLiquidity = FillLiquidity.UNKNOWN
    exchange_ts_ns: Optional[int] = None
    received_at_ms: int = field(default_factory=_now_ms)

    def __post_init__(self) -> None:
        object.__setattr__(self, "filled_qty", _ensure_non_negative(_d(self.filled_qty, field_name="filled_qty"), "filled_qty"))
        if self.remaining_qty is not None:
            object.__setattr__(self, "remaining_qty", _ensure_non_negative(_d(self.remaining_qty, field_name="remaining_qty"), "remaining_qty"))
        if self.average_fill_price is not None:
            object.__setattr__(self, "average_fill_price", _ensure_positive(_d(self.average_fill_price, field_name="average_fill_price"), "average_fill_price"))


# ============================================================================
# STATE / OUTPUT MODELS
# ============================================================================

@dataclass(frozen=True, slots=True)
class UnwindAssessment:
    assessment_id: int
    correlation_id: int
    created_at_ms: int

    symbol: str
    original_quantity: Decimal
    estimated_notional: Optional[Decimal]
    urgency: str
    priority: PriorityClass
    authority_tier: AuthorityTier
    marketability: Marketability

    regime: RegimeType
    liquidity_regime: LiquidityRegime
    toxicity_level: ToxicityLevel
    risk_level: RiskLevel
    risk_action: RiskAction

    rationale: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class UnwindAttempt:
    attempt_id: int
    campaign_id: int
    correlation_id: int
    symbol: str
    cid: str

    side: OrderSide
    quantity: Decimal
    order_type: OrderType
    time_in_force: TimeInForce
    execution_constraints: tuple[ExecutionConstraint, ...]
    marketability: Marketability

    created_at_ms: int
    retry_index: int
    escalation_level: UnwindEscalationLevel

    status: UnwindAttemptStatus = UnwindAttemptStatus.CREATED
    filled_qty: Decimal = ZERO
    remaining_qty: Optional[Decimal] = None
    average_fill_price: Optional[Decimal] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "quantity", _ensure_positive(_d(self.quantity, field_name="quantity"), "quantity"))
        object.__setattr__(self, "filled_qty", _ensure_non_negative(_d(self.filled_qty, field_name="filled_qty"), "filled_qty"))
        if self.remaining_qty is not None:
            object.__setattr__(self, "remaining_qty", _ensure_non_negative(_d(self.remaining_qty, field_name="remaining_qty"), "remaining_qty"))
        if self.average_fill_price is not None:
            object.__setattr__(self, "average_fill_price", _ensure_positive(_d(self.average_fill_price, field_name="average_fill_price"), "average_fill_price"))


@dataclass(frozen=True, slots=True)
class SymbolUnwindState:
    symbol: str
    target_flat_qty: Decimal
    original_quantity: Decimal
    remaining_quantity: Decimal
    estimated_notional: Optional[Decimal]

    assessment: UnwindAssessment
    attempts: tuple[UnwindAttempt, ...] = field(default_factory=tuple)

    completed: bool = False
    blocked: bool = False
    last_progress_ms: Optional[int] = None
    failure_count: int = 0
    stale: bool = False

    @property
    def side(self) -> Optional[OrderSide]:
        return _sign_side(self.remaining_quantity)

    @property
    def abs_remaining_qty(self) -> Decimal:
        return abs(self.remaining_quantity)


@dataclass(frozen=True, slots=True)
class UnwindRecommendation:
    recommendation_id: int
    campaign_id: int
    correlation_id: int
    attempt_id: int
    assessment_id: int
    created_at_ms: int

    symbol: str
    side: OrderSide
    quantity: Decimal
    order_type: OrderType
    time_in_force: TimeInForce
    execution_constraints: tuple[ExecutionConstraint, ...]
    marketability: Marketability
    trade_intent: TradeIntent
    estimated_notional: Optional[Decimal]
    cid: str

    urgency: str
    priority: PriorityClass
    authority_tier: AuthorityTier
    escalation_level: UnwindEscalationLevel
    retry_index: int

    regime: RegimeType
    liquidity_regime: LiquidityRegime
    toxicity_level: ToxicityLevel
    risk_level: RiskLevel
    risk_action: RiskAction

    is_emergency: bool = True
    source_module: str = "app.risk.position_unwind"
    replay_mode: ReplayMode = ReplayMode.LIVE
    execution_mode: ExecutionMode = ExecutionMode.LIVE
    rationale: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_legacy_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "order_type": self.order_type,
            "time_in_force": self.time_in_force,
            "cid": self.cid,
            "is_emergency": self.is_emergency,

            # additive metadata
            "trade_intent": self.trade_intent,
            "marketability": self.marketability,
            "priority": self.priority,
            "authority_tier": self.authority_tier,
            "retry_index": self.retry_index,
            "escalation_level": self.escalation_level,
            "execution_constraints": list(self.execution_constraints),
            "estimated_notional": self.estimated_notional,
            "campaign_id": self.campaign_id,
            "attempt_id": self.attempt_id,
            "correlation_id": self.correlation_id,
            "recommendation_id": self.recommendation_id,
        }


@dataclass(frozen=True, slots=True)
class UnwindProgressSnapshot:
    campaign_id: int
    timestamp_ms: int
    status: UnwindCampaignStatus
    progress_state: UnwindProgressState

    total_symbols: int
    completed_symbols: int
    active_symbols: int
    blocked_symbols: int

    gross_remaining_qty: Decimal
    gross_remaining_notional: Optional[Decimal]

    attempts_total: int
    attempts_open: int
    attempts_failed: int
    attempts_filled: int

    rationale: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class UnwindCampaign:
    campaign_id: int
    correlation_id: int
    created_at_ms: int
    started_at_ms: int

    status: UnwindCampaignStatus
    escalation_level: UnwindEscalationLevel

    symbols: tuple[SymbolUnwindState, ...]
    risk_context: UnwindRiskContext
    market_context_by_symbol: tuple[tuple[str, UnwindMarketContext], ...] = field(default_factory=tuple)

    rationale: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def symbol_state_map(self) -> Dict[str, SymbolUnwindState]:
        return {s.symbol: s for s in self.symbols}

    def market_context_map(self) -> Dict[str, UnwindMarketContext]:
        return dict(self.market_context_by_symbol)


# ============================================================================
# CONTROLLER
# ============================================================================

class PositionUnwindManager:
    """
    Stateful liquidation campaign controller.
    """

    def __init__(self, max_retries: int = 3):
        self.policy = UnwindPolicyConfig(max_retries=max_retries)

    # ------------------------------------------------------------------
    # Campaign lifecycle
    # ------------------------------------------------------------------

    def start_campaign(
        self,
        positions: Iterable[PositionSnapshot],
        market_by_symbol: Optional[Dict[str, UnwindMarketContext]] = None,
        risk: Optional[UnwindRiskContext] = None,
    ) -> UnwindCampaign:
        market_by_symbol = market_by_symbol or {}
        risk = risk or UnwindRiskContext()

        created_at_ms = _now_ms()
        campaign_id = generate_request_id()
        correlation_id = generate_correlation_id()

        symbol_states: List[SymbolUnwindState] = []

        for position in self._prioritize_positions(positions):
            market = market_by_symbol.get(position.symbol, UnwindMarketContext())
            assessment = self._assess_position(position=position, market=market, risk=risk)

            symbol_states.append(
                SymbolUnwindState(
                    symbol=position.symbol,
                    target_flat_qty=ZERO,
                    original_quantity=position.quantity,
                    remaining_quantity=position.quantity,
                    estimated_notional=(abs(position.quantity) * position.mark_price) if position.mark_price is not None else None,
                    assessment=assessment,
                    attempts=tuple(),
                    completed=self._is_economically_flat(
                        quantity=position.quantity,
                        notional=(abs(position.quantity) * position.mark_price) if position.mark_price is not None else None,
                    ),
                    blocked=False,
                    last_progress_ms=None,
                    failure_count=0,
                    stale=False,
                )
            )

        campaign = UnwindCampaign(
            campaign_id=campaign_id,
            correlation_id=correlation_id,
            created_at_ms=created_at_ms,
            started_at_ms=created_at_ms,
            status=UnwindCampaignStatus.PENDING,
            escalation_level=self._derive_campaign_escalation_level(risk=risk),
            symbols=tuple(symbol_states),
            risk_context=risk,
            market_context_by_symbol=tuple(sorted(market_by_symbol.items(), key=lambda kv: kv[0])),
            rationale=("campaign_initialized",),
            warnings=tuple(),
        )

        return self._refresh_campaign_status(campaign)

    def plan_next_actions(
        self,
        campaign: UnwindCampaign,
    ) -> tuple[UnwindCampaign, List[UnwindRecommendation]]:
        """
        Generate next-wave unwind recommendations based on campaign state.
        """
        campaign = self._refresh_campaign_status(campaign)
        if campaign.status in {
            UnwindCampaignStatus.COMPLETE,
            UnwindCampaignStatus.CANCELLED,
            UnwindCampaignStatus.FAILED,
        }:
            return campaign, []

        market_map = campaign.market_context_map()
        symbol_map = campaign.symbol_state_map()

        updated_states: List[SymbolUnwindState] = []
        recommendations: List[UnwindRecommendation] = []

        for symbol in self._ordered_symbol_keys(symbol_map):
            state = symbol_map[symbol]
            market = market_map.get(symbol, UnwindMarketContext())

            if state.completed or state.blocked:
                updated_states.append(state)
                continue

            if self._has_open_attempt(state):
                updated_states.append(state)
                continue

            next_attempts = self._build_next_attempts(
                campaign=campaign,
                state=state,
                market=market,
            )

            new_state = state
            for attempt in next_attempts:
                new_state = replace(
                    new_state,
                    attempts=tuple(list(new_state.attempts) + [attempt]),
                )
                recommendations.append(
                    self._attempt_to_recommendation(
                        campaign=campaign,
                        state=new_state,
                        attempt=attempt,
                        market=market,
                    )
                )

            updated_states.append(new_state)

        updated_campaign = replace(campaign, symbols=tuple(updated_states))
        updated_campaign = self._refresh_campaign_status(updated_campaign)
        return updated_campaign, recommendations

    def ingest_feedback(
        self,
        campaign: UnwindCampaign,
        feedback: UnwindOrderFeedback,
    ) -> UnwindCampaign:
        """
        Consume execution feedback and update campaign state.
        """
        updated_states: List[SymbolUnwindState] = []
        matched = False

        for state in campaign.symbols:
            if state.symbol != feedback.symbol:
                updated_states.append(state)
                continue

            attempts = list(state.attempts)
            new_attempts: List[UnwindAttempt] = []
            delta_filled = ZERO

            for attempt in attempts:
                if attempt.cid != feedback.cid:
                    new_attempts.append(attempt)
                    continue

                matched = True
                status = self._map_order_status_to_attempt_status(feedback.status)
                prev_filled = attempt.filled_qty
                new_filled = max(prev_filled, feedback.filled_qty)
                delta_filled = max(ZERO, new_filled - prev_filled)

                updated_attempt = replace(
                    attempt,
                    status=status,
                    filled_qty=new_filled,
                    remaining_qty=feedback.remaining_qty,
                    average_fill_price=feedback.average_fill_price or attempt.average_fill_price,
                )
                new_attempts.append(updated_attempt)

            if matched:
                new_remaining_qty = self._apply_fill_to_remaining(
                    remaining_quantity=state.remaining_quantity,
                    filled_qty=delta_filled,
                )

                failure_count = state.failure_count
                if any(a.status in {UnwindAttemptStatus.REJECTED, UnwindAttemptStatus.FAILED, UnwindAttemptStatus.EXPIRED} for a in new_attempts):
                    failure_count += 1

                completed = self._is_economically_flat(
                    quantity=new_remaining_qty,
                    notional=(abs(new_remaining_qty) * state.assessment.estimated_notional / abs(state.original_quantity))
                    if state.assessment.estimated_notional is not None and state.original_quantity != ZERO
                    else None,
                )

                updated_states.append(
                    replace(
                        state,
                        attempts=tuple(new_attempts),
                        remaining_quantity=new_remaining_qty,
                        completed=completed,
                        last_progress_ms=feedback.received_at_ms if delta_filled > ZERO else state.last_progress_ms,
                        failure_count=failure_count,
                    )
                )
            else:
                updated_states.append(state)

        if not matched:
            logger.warning(
                "[UNWIND] feedback_unmatched campaign_id=%s symbol=%s cid=%s status=%s",
                campaign.campaign_id,
                feedback.symbol,
                feedback.cid,
                feedback.status.value,
            )

        updated_campaign = replace(campaign, symbols=tuple(updated_states))
        return self._refresh_campaign_status(updated_campaign)

    def evaluate_campaign_progress(self, campaign: UnwindCampaign) -> UnwindProgressSnapshot:
        """
        Canonical progress evaluation.
        """
        now_ms = _now_ms()
        symbol_states = list(campaign.symbols)

        total_symbols = len(symbol_states)
        completed_symbols = sum(1 for s in symbol_states if s.completed)
        blocked_symbols = sum(1 for s in symbol_states if s.blocked)
        active_symbols = total_symbols - completed_symbols - blocked_symbols

        gross_remaining_qty = sum((abs(s.remaining_quantity) for s in symbol_states), start=ZERO)

        gross_remaining_notional: Optional[Decimal] = ZERO
        for s in symbol_states:
            if s.estimated_notional is None or s.original_quantity == ZERO:
                gross_remaining_notional = None
                break
            gross_remaining_notional += abs(s.remaining_quantity) * (s.estimated_notional / abs(s.original_quantity))

        all_attempts = [a for s in symbol_states for a in s.attempts]
        attempts_total = len(all_attempts)
        attempts_open = sum(1 for a in all_attempts if a.status in {
            UnwindAttemptStatus.CREATED,
            UnwindAttemptStatus.DISPATCHED,
            UnwindAttemptStatus.ACKNOWLEDGED,
            UnwindAttemptStatus.PARTIAL_FILL,
        })
        attempts_failed = sum(1 for a in all_attempts if a.status in {
            UnwindAttemptStatus.REJECTED,
            UnwindAttemptStatus.FAILED,
            UnwindAttemptStatus.EXPIRED,
            UnwindAttemptStatus.STALE,
        })
        attempts_filled = sum(1 for a in all_attempts if a.status == UnwindAttemptStatus.FILLED)

        rationale: List[str] = []
        warnings: List[str] = []

        if campaign.status == UnwindCampaignStatus.COMPLETE:
            progress_state = UnwindProgressState.COMPLETE
            rationale.append("campaign_complete")
        elif attempts_open > 0:
            progress_state = UnwindProgressState.AWAITING_ACK
            rationale.append("attempts_open")
        elif attempts_failed > 0 and completed_symbols < total_symbols:
            progress_state = UnwindProgressState.STALLED
            warnings.append("failed_attempts_present")
        elif completed_symbols > 0:
            progress_state = UnwindProgressState.PARTIAL_PROGRESS
            rationale.append("partial_symbol_completion")
        else:
            progress_state = UnwindProgressState.UNKNOWN

        return UnwindProgressSnapshot(
            campaign_id=campaign.campaign_id,
            timestamp_ms=now_ms,
            status=campaign.status,
            progress_state=progress_state,
            total_symbols=total_symbols,
            completed_symbols=completed_symbols,
            active_symbols=active_symbols,
            blocked_symbols=blocked_symbols,
            gross_remaining_qty=gross_remaining_qty,
            gross_remaining_notional=gross_remaining_notional,
            attempts_total=attempts_total,
            attempts_open=attempts_open,
            attempts_failed=attempts_failed,
            attempts_filled=attempts_filled,
            rationale=tuple(rationale),
            warnings=tuple(warnings),
        )

    # ------------------------------------------------------------------
    # Backward-aware legacy facades
    # ------------------------------------------------------------------

    def generate_unwind_intents(self, active_positions: Dict[str, Decimal]) -> List[Dict]:
        """
        Legacy compatibility facade.
        """
        positions = [
            PositionSnapshot(symbol=symbol, quantity=_d(quantity, field_name=f"quantity[{symbol}]"))
            for symbol, quantity in active_positions.items()
        ]
        campaign = self.start_campaign(positions=positions)
        campaign, recs = self.plan_next_actions(campaign)
        return [r.to_legacy_dict() for r in recs]

    def evaluate_unwind_progress(self, remaining_positions: Dict[str, Decimal]) -> bool:
        """
        Legacy-compatible flatness check with dust-aware semantics.
        """
        normalized = {
            symbol: _d(qty, field_name=f"remaining_positions[{symbol}]")
            for symbol, qty in remaining_positions.items()
        }
        is_flat = all(abs(qty) <= self.policy.economic_flat_qty for qty in normalized.values())
        if not is_flat:
            logger.error("[UNWIND_STALLED] Positions still active: %s", normalized)
        return is_flat

    # ------------------------------------------------------------------
    # Internal planning helpers
    # ------------------------------------------------------------------

    def _assess_position(
        self,
        *,
        position: PositionSnapshot,
        market: UnwindMarketContext,
        risk: UnwindRiskContext,
    ) -> UnwindAssessment:
        urgency, priority, authority_tier, marketability = self._classify_unwind_style(
            market=market,
            risk=risk,
        )

        warnings: List[str] = []
        if position.snapshot_age_ms is not None and self.policy.stale_position_threshold_ms is not None:
            if position.snapshot_age_ms > self.policy.stale_position_threshold_ms:
                warnings.append(f"stale_position_snapshot:{position.snapshot_age_ms}ms")

        estimated_notional = (
            abs(position.quantity) * position.mark_price
            if position.mark_price is not None else None
        )

        return UnwindAssessment(
            assessment_id=generate_request_id(),
            correlation_id=generate_correlation_id(),
            created_at_ms=_now_ms(),
            symbol=position.symbol,
            original_quantity=position.quantity,
            estimated_notional=estimated_notional,
            urgency=urgency,
            priority=priority,
            authority_tier=authority_tier,
            marketability=marketability,
            regime=market.regime,
            liquidity_regime=market.liquidity_regime,
            toxicity_level=market.toxicity_level,
            risk_level=risk.risk_level,
            risk_action=risk.risk_action,
            rationale=(f"position_qty={position.quantity}",),
            warnings=tuple(warnings),
        )

    def _prioritize_positions(self, positions: Iterable[PositionSnapshot]) -> List[PositionSnapshot]:
        """
        Deterministic symbol ordering prioritized by available notional, then symbol.
        """
        pos_list = list(positions)

        def sort_key(p: PositionSnapshot) -> tuple[int, Decimal, str]:
            est_notional = abs(p.quantity) * p.mark_price if p.mark_price is not None else ZERO
            no_mark_penalty = 1 if p.mark_price is None else 0
            return (no_mark_penalty, -est_notional, p.symbol)

        return sorted(pos_list, key=sort_key)

    def _ordered_symbol_keys(self, symbol_map: Dict[str, SymbolUnwindState]) -> List[str]:
        return sorted(symbol_map.keys())

    def _build_next_attempts(
        self,
        *,
        campaign: UnwindCampaign,
        state: SymbolUnwindState,
        market: UnwindMarketContext,
    ) -> List[UnwindAttempt]:
        if self._is_economically_flat(
            quantity=state.remaining_quantity,
            notional=self._estimate_remaining_notional(state),
        ):
            return []

        side = _sign_side(state.remaining_quantity)
        if side is None:
            return []

        prior_failures = state.failure_count
        retry_index = len(state.attempts)
        if retry_index > self.policy.max_retries:
            return []

        escalation_level = self._derive_symbol_escalation(
            campaign=campaign,
            state=state,
            market=market,
        )

        abs_remaining = abs(state.remaining_quantity)
        tranches = self._split_quantity_into_tranches(
            quantity=abs_remaining,
            estimated_notional=self._estimate_remaining_notional(state),
        )

        attempts: List[UnwindAttempt] = []
        for tranche_qty in tranches:
            if tranche_qty < self.policy.min_order_quantity:
                continue

            order_type, tif, constraints = self._select_execution_style(
                market=market,
                assessment=state.assessment,
                escalation_level=escalation_level,
                retry_index=retry_index,
            )

            attempts.append(
                UnwindAttempt(
                    attempt_id=generate_order_id(),
                    campaign_id=campaign.campaign_id,
                    correlation_id=campaign.correlation_id,
                    symbol=state.symbol,
                    cid=generate_order_cid(strategy="UNWIND", sleeve="RISK"),
                    side=side,
                    quantity=tranche_qty,
                    order_type=order_type,
                    time_in_force=tif,
                    execution_constraints=constraints,
                    marketability=state.assessment.marketability,
                    created_at_ms=_now_ms(),
                    retry_index=prior_failures,
                    escalation_level=escalation_level,
                )
            )

        return attempts

    def _attempt_to_recommendation(
        self,
        *,
        campaign: UnwindCampaign,
        state: SymbolUnwindState,
        attempt: UnwindAttempt,
        market: UnwindMarketContext,
    ) -> UnwindRecommendation:
        est_notional = None
        remaining_est = self._estimate_remaining_notional(state)
        if remaining_est is not None and state.abs_remaining_qty > ZERO:
            est_notional = attempt.quantity * (remaining_est / state.abs_remaining_qty)

        return UnwindRecommendation(
            recommendation_id=generate_order_id(),
            campaign_id=campaign.campaign_id,
            correlation_id=campaign.correlation_id,
            attempt_id=attempt.attempt_id,
            assessment_id=state.assessment.assessment_id,
            created_at_ms=_now_ms(),
            symbol=state.symbol,
            side=attempt.side,
            quantity=attempt.quantity,
            order_type=attempt.order_type,
            time_in_force=attempt.time_in_force,
            execution_constraints=attempt.execution_constraints,
            marketability=attempt.marketability,
            trade_intent=TradeIntent.FLATTEN,
            estimated_notional=est_notional,
            cid=attempt.cid,
            urgency=state.assessment.urgency,
            priority=state.assessment.priority,
            authority_tier=state.assessment.authority_tier,
            escalation_level=attempt.escalation_level,
            retry_index=attempt.retry_index,
            regime=state.assessment.regime,
            liquidity_regime=state.assessment.liquidity_regime,
            toxicity_level=state.assessment.toxicity_level,
            risk_level=state.assessment.risk_level,
            risk_action=state.assessment.risk_action,
            replay_mode=market.replay_mode,
            execution_mode=market.execution_mode,
            rationale=state.assessment.rationale,
            warnings=state.assessment.warnings,
        )

    def _refresh_campaign_status(self, campaign: UnwindCampaign) -> UnwindCampaign:
        states = list(campaign.symbols)

        if not states:
            return replace(campaign, status=UnwindCampaignStatus.COMPLETE)

        if all(s.completed for s in states):
            return replace(campaign, status=UnwindCampaignStatus.COMPLETE)

        if any(s.failure_count >= self.policy.commander_escalation_after_failures for s in states):
            return replace(
                campaign,
                status=UnwindCampaignStatus.ESCALATED,
                escalation_level=UnwindEscalationLevel.TERMINAL,
            )

        if any(self._has_open_attempt(s) for s in states):
            if any(s.completed for s in states):
                return replace(campaign, status=UnwindCampaignStatus.PARTIAL_PROGRESS)
            return replace(campaign, status=UnwindCampaignStatus.ACTIVE)

        if any(s.failure_count > 0 for s in states):
            return replace(campaign, status=UnwindCampaignStatus.STALLED)

        return replace(campaign, status=UnwindCampaignStatus.PENDING)

    def _map_order_status_to_attempt_status(self, status: OrderStatus) -> UnwindAttemptStatus:
        mapping = {
            OrderStatus.CREATED: UnwindAttemptStatus.CREATED,
            OrderStatus.ROUTING: UnwindAttemptStatus.DISPATCHED,
            OrderStatus.ROUTED: UnwindAttemptStatus.DISPATCHED,
            OrderStatus.SENT: UnwindAttemptStatus.DISPATCHED,
            OrderStatus.PENDING_NEW: UnwindAttemptStatus.DISPATCHED,
            OrderStatus.PENDING_ACK: UnwindAttemptStatus.DISPATCHED,
            OrderStatus.ACKNOWLEDGED: UnwindAttemptStatus.ACKNOWLEDGED,
            OrderStatus.PARTIAL_FILL: UnwindAttemptStatus.PARTIAL_FILL,
            OrderStatus.FULLY_FILLED: UnwindAttemptStatus.FILLED,
            OrderStatus.CANCELLED: UnwindAttemptStatus.CANCELLED,
            OrderStatus.EXPIRED: UnwindAttemptStatus.EXPIRED,
            OrderStatus.REJECTED: UnwindAttemptStatus.REJECTED,
            OrderStatus.STALE: UnwindAttemptStatus.STALE,
        }
        return mapping.get(status, UnwindAttemptStatus.FAILED)

    def _apply_fill_to_remaining(
        self,
        *,
        remaining_quantity: Decimal,
        filled_qty: Decimal,
    ) -> Decimal:
        if remaining_quantity > ZERO:
            new_qty = remaining_quantity - filled_qty
            return new_qty if new_qty > ZERO else ZERO
        if remaining_quantity < ZERO:
            new_qty = remaining_quantity + filled_qty
            return new_qty if new_qty < ZERO else ZERO
        return ZERO

    def _estimate_remaining_notional(self, state: SymbolUnwindState) -> Optional[Decimal]:
        if state.estimated_notional is None or state.original_quantity == ZERO:
            return None
        return abs(state.remaining_quantity) * (state.estimated_notional / abs(state.original_quantity))

    def _is_economically_flat(
        self,
        *,
        quantity: Decimal,
        notional: Optional[Decimal],
    ) -> bool:
        if abs(quantity) <= self.policy.economic_flat_qty:
            return True
        if notional is not None and notional <= self.policy.economic_flat_notional:
            return True
        return False

    def _has_open_attempt(self, state: SymbolUnwindState) -> bool:
        now_ms = _now_ms()
        for attempt in state.attempts:
            if attempt.status in {
                UnwindAttemptStatus.CREATED,
                UnwindAttemptStatus.DISPATCHED,
                UnwindAttemptStatus.ACKNOWLEDGED,
                UnwindAttemptStatus.PARTIAL_FILL,
            }:
                if (now_ms - attempt.created_at_ms) <= self.policy.stale_attempt_threshold_ms:
                    return True
        return False

    def _split_quantity_into_tranches(
        self,
        *,
        quantity: Decimal,
        estimated_notional: Optional[Decimal],
    ) -> List[Decimal]:
        quantity = _quantize_down(quantity, self.policy.quantity_step)
        if quantity < self.policy.min_order_quantity:
            return []

        if not self.policy.allow_order_splitting or self.policy.max_single_order_notional is None or estimated_notional is None:
            return [quantity]

        if estimated_notional <= self.policy.max_single_order_notional:
            return [quantity]

        per_unit_notional = estimated_notional / quantity if quantity > ZERO else None
        if per_unit_notional is None or per_unit_notional <= ZERO:
            return [quantity]

        max_qty = _quantize_down(
            self.policy.max_single_order_notional / per_unit_notional,
            self.policy.quantity_step,
        )
        if max_qty < self.policy.min_order_quantity:
            return [quantity]

        remaining = quantity
        tranches: List[Decimal] = []
        while remaining > ZERO:
            tranche = min(remaining, max_qty)
            tranche = _quantize_down(tranche, self.policy.quantity_step)
            if tranche < self.policy.min_order_quantity:
                break
            tranches.append(tranche)
            remaining -= tranche

        if remaining >= self.policy.min_order_quantity:
            tranches.append(_quantize_down(remaining, self.policy.quantity_step))

        return tranches if tranches else [quantity]

    def _derive_campaign_escalation_level(self, risk: UnwindRiskContext) -> UnwindEscalationLevel:
        if risk.kill_switch_active:
            return UnwindEscalationLevel.TERMINAL
        if risk.hard_flat or risk.risk_action == RiskAction.FORCE_FLAT:
            return UnwindEscalationLevel.EMERGENCY
        if is_high_risk_level(risk.risk_level):
            return UnwindEscalationLevel.CRITICAL
        return UnwindEscalationLevel.TACTICAL

    def _derive_symbol_escalation(
        self,
        *,
        campaign: UnwindCampaign,
        state: SymbolUnwindState,
        market: UnwindMarketContext,
    ) -> UnwindEscalationLevel:
        if campaign.escalation_level == UnwindEscalationLevel.TERMINAL:
            return UnwindEscalationLevel.TERMINAL
        if state.failure_count >= self.policy.commander_escalation_after_failures:
            return UnwindEscalationLevel.TERMINAL
        if state.failure_count >= 2 or is_crisis_regime(market.regime):
            return UnwindEscalationLevel.EMERGENCY
        if state.failure_count >= 1 or market.toxicity_level in {ToxicityLevel.TOXIC, ToxicityLevel.EXTREME}:
            return UnwindEscalationLevel.CRITICAL
        return campaign.escalation_level

    def _classify_unwind_style(
        self,
        *,
        market: UnwindMarketContext,
        risk: UnwindRiskContext,
    ) -> tuple[str, PriorityClass, AuthorityTier, Marketability]:
        if risk.kill_switch_active or risk.hard_flat or risk.risk_action == RiskAction.FORCE_FLAT:
            return "EMERGENCY", PriorityClass.REALTIME, AuthorityTier.TERMINAL, Marketability.SWEEPING

        if is_crisis_regime(market.regime) or is_high_risk_level(risk.risk_level):
            return "CRITICAL", PriorityClass.URGENT, AuthorityTier.HARD_BLOCK, Marketability.CROSSING

        if market.toxicity_level in {ToxicityLevel.TOXIC, ToxicityLevel.EXTREME}:
            return "HIGH", PriorityClass.URGENT, AuthorityTier.SOFT_BLOCK, Marketability.MARKETABLE

        return "TACTICAL", PriorityClass.NORMAL, AuthorityTier.ADVISORY, Marketability.NEAR_TOUCH

    def _select_execution_style(
        self,
        *,
        market: UnwindMarketContext,
        assessment: UnwindAssessment,
        escalation_level: UnwindEscalationLevel,
        retry_index: int,
    ) -> tuple[OrderType, TimeInForce, tuple[ExecutionConstraint, ...]]:
        constraints: List[ExecutionConstraint] = []

        if self.policy.use_reduce_only_when_possible:
            constraints.append(ExecutionConstraint.REDUCE_ONLY)

        if escalation_level in {UnwindEscalationLevel.TERMINAL, UnwindEscalationLevel.EMERGENCY}:
            constraints.append(ExecutionConstraint.TAKER_ALLOWED)
            if self.policy.emergency_force_ioc:
                return OrderType.IOC, TimeInForce.IOC, tuple(constraints)
            return OrderType.MARKET, TimeInForce.FOK, tuple(constraints)

        if escalation_level == UnwindEscalationLevel.CRITICAL or retry_index >= 2:
            constraints.append(ExecutionConstraint.TAKER_ALLOWED)
            return OrderType.IOC, TimeInForce.IOC, tuple(constraints)

        if assessment.urgency == "HIGH" or retry_index >= 1:
            constraints.append(ExecutionConstraint.TAKER_ALLOWED)
            return OrderType.LIMIT, TimeInForce.IOC, tuple(constraints)

        if market.liquidity_regime in {LiquidityRegime.THICK, LiquidityRegime.UNKNOWN}:
            return OrderType.LIMIT, TimeInForce.DAY, tuple(constraints)

        constraints.append(ExecutionConstraint.TAKER_ALLOWED)
        return OrderType.LIMIT, TimeInForce.IOC, tuple(constraints)


__all__ = [
    "UnwindCampaignStatus",
    "UnwindAttemptStatus",
    "UnwindEscalationLevel",
    "UnwindProgressState",
    "UnwindPolicyConfig",
    "PositionSnapshot",
    "UnwindMarketContext",
    "UnwindRiskContext",
    "UnwindOrderFeedback",
    "UnwindAssessment",
    "UnwindAttempt",
    "SymbolUnwindState",
    "UnwindRecommendation",
    "UnwindProgressSnapshot",
    "UnwindCampaign",
    "PositionUnwindManager",
]
