"""
app/strategies/adaptive_dc.py
POVERTY_KILLER — CANONICAL ADAPTIVE DIRECTIONAL CHANGE ENGINE (CITADEL-GRADE)

This module implements an intrinsic-time directional change (DC) strategy sleeve.
It detects structural market reversals relative to adaptive threshold theta,
tracks overshoot state, classifies event quality, and emits canonical signal
assessments and recommendations for orchestrator review.

ARCHITECTURAL ROLE
------------------
- This module is a strategy analysis authority, NOT a final execution authority.
- It emits structural DC events and signal recommendations.
- Orchestrator / risk / execution layers remain sovereign over execution.

DESIGN PRINCIPLES
-----------------
1. Intrinsic Time, Not Wall Time
   Structural market events are primary; clock-time is secondary metadata.

2. Event / Assessment Split
   Detection of DC events is separated from signal recommendation logic.

3. Adaptive Threshold Discipline
   Theta adaptation is bounded, smoothed, and volatility-aware.

4. Overshoot Awareness
   Structural overshoot continuation is tracked explicitly.

5. Stability Controls
   Cooldown, debounce, and stale/out-of-order guards reduce whipsaw noise.

6. Canonical Structured Output
   Dataclass models support deterministic replay, telemetry, and orchestration.

7. Backward-Aware Compatibility
   The legacy on_tick(...) -> Optional[OrderSide] entrypoint is preserved as a
   compatibility facade over the canonical pipeline.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum, unique
from typing import Any, Dict, List, Optional

from app.utils.enums import (
    AuthorityTier,
    BookIntegrity,
    DegradationMode,
    EventSource,
    ExecutionMode,
    LiquidityRegime,
    OrderSide,
    PriorityClass,
    RegimeType,
    ReplayMode,
    RiskAction,
    RiskLevel,
    RiskVetoReason,
    SignalDirection,
    ToxicityLevel,
    is_blocking_risk_action,
    is_crisis_regime,
    is_high_risk_level,
)
from app.utils.ids import generate_correlation_id, generate_event_id, generate_signal_id

logger = logging.getLogger(__name__)


# ============================================================================
# CONSTANTS / HELPERS
# ============================================================================

ZERO = Decimal("0")
ONE = Decimal("1")
EPS = Decimal("0.0000000001")


def _d(value: Any, *, field_name: str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"invalid decimal for {field_name}: {value!r}") from exc


def _ensure_positive(value: Decimal, field_name: str) -> Decimal:
    if value <= ZERO:
        raise ValueError(f"{field_name} must be > 0, got {value}")
    return value


def _ensure_non_negative(value: Decimal, field_name: str) -> Decimal:
    if value < ZERO:
        raise ValueError(f"{field_name} must be >= 0, got {value}")
    return value


def _clamp(value: Decimal, lower: Decimal, upper: Decimal) -> Decimal:
    if value < lower:
        return lower
    if value > upper:
        return upper
    return value


def _now_ms() -> int:
    return int(time.time() * 1000)


# ============================================================================
# ENUMS
# ============================================================================

@unique
class DCDirection(str, Enum):
    UNKNOWN = "UNKNOWN"
    UP = "UP"
    DOWN = "DOWN"


@unique
class DCPhase(str, Enum):
    UNINITIALIZED = "UNINITIALIZED"
    SEEKING_INITIAL_DIRECTION = "SEEKING_INITIAL_DIRECTION"
    OVERSHOOT_UP = "OVERSHOOT_UP"
    OVERSHOOT_DOWN = "OVERSHOOT_DOWN"


@unique
class DCEventType(str, Enum):
    NONE = "NONE"
    INITIALIZED = "INITIALIZED"
    DIRECTIONAL_CHANGE_UP = "DIRECTIONAL_CHANGE_UP"
    DIRECTIONAL_CHANGE_DOWN = "DIRECTIONAL_CHANGE_DOWN"
    OVERSHOOT_EXTREME_UPDATE = "OVERSHOOT_EXTREME_UPDATE"
    SUPPRESSED = "SUPPRESSED"


@unique
class DCSignalQuality(str, Enum):
    UNKNOWN = "UNKNOWN"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    INSTITUTIONAL = "INSTITUTIONAL"


# ============================================================================
# CONFIG / INPUT MODELS
# ============================================================================

@dataclass(frozen=True, slots=True)
class DCPolicyConfig:
    """
    Canonical policy for adaptive directional change behavior.
    """
    initial_theta: Decimal = Decimal("0.0050")
    min_theta: Decimal = Decimal("0.0010")
    max_theta: Decimal = Decimal("0.0500")
    theta_smoothing_alpha: Decimal = Decimal("0.2500")
    volatility_multiplier: Decimal = Decimal("2.0000")
    min_signal_interval_ns: int = 2_000_000
    cooldown_ms: int = 750
    max_tick_staleness_ms: int = 5_000
    min_price: Decimal = Decimal("0.00000001")
    min_event_move_multiple: Decimal = Decimal("1.0000")
    overshoot_confirmation_multiple: Decimal = Decimal("0.2500")
    suppress_on_book_failure: bool = True
    suppress_in_crisis_infra: bool = True
    allow_signals_in_safe_mode: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "initial_theta", _ensure_positive(_d(self.initial_theta, field_name="initial_theta"), "initial_theta"))
        object.__setattr__(self, "min_theta", _ensure_positive(_d(self.min_theta, field_name="min_theta"), "min_theta"))
        object.__setattr__(self, "max_theta", _ensure_positive(_d(self.max_theta, field_name="max_theta"), "max_theta"))
        object.__setattr__(self, "theta_smoothing_alpha", _clamp(_d(self.theta_smoothing_alpha, field_name="theta_smoothing_alpha"), ZERO, ONE))
        object.__setattr__(self, "volatility_multiplier", _ensure_non_negative(_d(self.volatility_multiplier, field_name="volatility_multiplier"), "volatility_multiplier"))
        object.__setattr__(self, "min_price", _ensure_positive(_d(self.min_price, field_name="min_price"), "min_price"))
        object.__setattr__(self, "min_event_move_multiple", _ensure_positive(_d(self.min_event_move_multiple, field_name="min_event_move_multiple"), "min_event_move_multiple"))
        object.__setattr__(self, "overshoot_confirmation_multiple", _ensure_non_negative(_d(self.overshoot_confirmation_multiple, field_name="overshoot_confirmation_multiple"), "overshoot_confirmation_multiple"))

        if self.min_theta > self.max_theta:
            raise ValueError("min_theta cannot exceed max_theta")
        if self.initial_theta < self.min_theta or self.initial_theta > self.max_theta:
            raise ValueError("initial_theta must lie within [min_theta, max_theta]")
        if self.min_signal_interval_ns < 0:
            raise ValueError("min_signal_interval_ns must be >= 0")
        if self.cooldown_ms < 0:
            raise ValueError("cooldown_ms must be >= 0")
        if self.max_tick_staleness_ms < 0:
            raise ValueError("max_tick_staleness_ms must be >= 0")


@dataclass(frozen=True, slots=True)
class DCMarketTick:
    symbol: str
    price: Decimal
    timestamp_ns: int
    local_received_ns: Optional[int] = None
    bid: Optional[Decimal] = None
    ask: Optional[Decimal] = None
    mid: Optional[Decimal] = None
    market_data_age_ms: Optional[int] = None
    regime: RegimeType = RegimeType.UNKNOWN
    liquidity_regime: LiquidityRegime = LiquidityRegime.UNKNOWN
    toxicity_level: ToxicityLevel = ToxicityLevel.UNKNOWN
    book_integrity: BookIntegrity = BookIntegrity.UNKNOWN
    execution_mode: ExecutionMode = ExecutionMode.LIVE
    degradation_mode: DegradationMode = DegradationMode.NORMAL
    replay_mode: ReplayMode = ReplayMode.LIVE
    source: EventSource = EventSource.MARKET_DATA

    def __post_init__(self) -> None:
        object.__setattr__(self, "price", _ensure_positive(_d(self.price, field_name="price"), "price"))
        if self.bid is not None:
            object.__setattr__(self, "bid", _ensure_positive(_d(self.bid, field_name="bid"), "bid"))
        if self.ask is not None:
            object.__setattr__(self, "ask", _ensure_positive(_d(self.ask, field_name="ask"), "ask"))
        if self.mid is not None:
            object.__setattr__(self, "mid", _ensure_positive(_d(self.mid, field_name="mid"), "mid"))
        if self.timestamp_ns < 0:
            raise ValueError("timestamp_ns must be >= 0")
        if self.local_received_ns is not None and self.local_received_ns < 0:
            raise ValueError("local_received_ns must be >= 0")
        if self.market_data_age_ms is not None and self.market_data_age_ms < 0:
            raise ValueError("market_data_age_ms must be >= 0")


@dataclass(frozen=True, slots=True)
class DCRiskContext:
    risk_level: RiskLevel = RiskLevel.NONE
    risk_action: RiskAction = RiskAction.ALLOW
    veto_reason: Optional[RiskVetoReason] = None
    safe_mode_active: bool = False
    kill_switch_active: bool = False


@dataclass(frozen=True, slots=True)
class ThetaUpdate:
    raw_volatility_score: Decimal
    previous_theta: Decimal
    target_theta: Decimal
    applied_theta: Decimal
    reason: str


# ============================================================================
# STATE / OUTPUT MODELS
# ============================================================================

@dataclass(frozen=True, slots=True)
class DCEngineState:
    symbol: Optional[str]
    theta: Decimal
    phase: DCPhase
    current_direction: DCDirection
    last_extreme_price: Optional[Decimal]
    last_extreme_ts_ns: Optional[int]
    last_dc_price: Optional[Decimal]
    last_dc_ts_ns: Optional[int]
    overshoot_anchor_price: Optional[Decimal]
    overshoot_anchor_ts_ns: Optional[int]
    event_count: int
    overshoot_count: int
    last_signal_ts_ns: Optional[int]
    last_signal_direction: SignalDirection
    last_tick_ts_ns: Optional[int]
    recovered: bool = False


@dataclass(frozen=True, slots=True)
class DCEvent:
    event_id: int
    correlation_id: int
    event_type: DCEventType
    symbol: str
    timestamp_ns: int
    local_timestamp_ms: int

    direction: DCDirection
    phase: DCPhase
    price: Decimal
    previous_extreme_price: Optional[Decimal]
    new_extreme_price: Decimal

    theta: Decimal
    move_pct_from_extreme: Decimal
    move_multiple_of_theta: Decimal

    overshoot_pct: Decimal
    overshoot_multiple: Decimal

    regime: RegimeType
    liquidity_regime: LiquidityRegime
    toxicity_level: ToxicityLevel
    book_integrity: BookIntegrity

    suppressed: bool = False
    suppress_reason: Optional[str] = None
    rationale: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class DCSignalAssessment:
    assessment_id: int
    correlation_id: int
    timestamp_ms: int

    symbol: str
    signal_direction: SignalDirection
    event_type: DCEventType
    event_direction: DCDirection

    signal_emittable: bool
    suppress_reason: Optional[str]

    theta: Decimal
    move_pct_from_extreme: Decimal
    move_multiple_of_theta: Decimal
    overshoot_pct: Decimal
    overshoot_multiple: Decimal

    confidence: Decimal
    quality: DCSignalQuality
    priority: PriorityClass
    authority_tier: AuthorityTier

    regime: RegimeType
    liquidity_regime: LiquidityRegime
    toxicity_level: ToxicityLevel
    book_integrity: BookIntegrity
    risk_level: RiskLevel
    risk_action: RiskAction

    rationale: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class DCSignalRecommendation:
    recommendation_id: int
    correlation_id: int
    assessment_id: int
    created_at_ms: int

    symbol: str
    signal_direction: SignalDirection
    confidence: Decimal
    quality: DCSignalQuality

    event_type: DCEventType
    event_direction: DCDirection
    theta: Decimal

    priority: PriorityClass
    authority_tier: AuthorityTier

    regime: RegimeType
    liquidity_regime: LiquidityRegime
    toxicity_level: ToxicityLevel
    risk_level: RiskLevel
    risk_action: RiskAction

    source_module: str = "app.strategies.adaptive_dc"
    replay_mode: ReplayMode = ReplayMode.LIVE
    execution_mode: ExecutionMode = ExecutionMode.LIVE
    rationale: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_legacy_order_side(self) -> Optional[OrderSide]:
        if self.signal_direction == SignalDirection.LONG:
            return OrderSide.BUY
        if self.signal_direction == SignalDirection.SHORT:
            return OrderSide.SELL
        return None


# ============================================================================
# ENGINE
# ============================================================================

class AdaptiveDC:
    """
    Canonical adaptive directional change strategy engine.

    Backward-aware:
    - preserves on_tick(price, ts_ns) -> Optional[OrderSide]
    - exposes canonical event/assessment/recommendation pipeline
    """

    def __init__(self, initial_theta: Decimal = Decimal("0.005")) -> None:
        self.policy = DCPolicyConfig(initial_theta=_d(initial_theta, field_name="initial_theta"))
        self.theta = self.policy.initial_theta

        self._symbol: Optional[str] = None
        self._phase = DCPhase.UNINITIALIZED
        self._current_direction = DCDirection.UNKNOWN
        self._last_extreme_price: Optional[Decimal] = None
        self._last_extreme_ts_ns: Optional[int] = None
        self._last_dc_price: Optional[Decimal] = None
        self._last_dc_ts_ns: Optional[int] = None
        self._overshoot_anchor_price: Optional[Decimal] = None
        self._overshoot_anchor_ts_ns: Optional[int] = None
        self._last_signal_ts_ns: Optional[int] = None
        self._last_signal_direction: SignalDirection = SignalDirection.NEUTRAL
        self._last_tick_ts_ns: Optional[int] = None
        self._event_count: int = 0
        self._overshoot_count: int = 0

    # ------------------------------------------------------------------
    # Canonical API
    # ------------------------------------------------------------------

    def snapshot_state(self) -> DCEngineState:
        return DCEngineState(
            symbol=self._symbol,
            theta=self.theta,
            phase=self._phase,
            current_direction=self._current_direction,
            last_extreme_price=self._last_extreme_price,
            last_extreme_ts_ns=self._last_extreme_ts_ns,
            last_dc_price=self._last_dc_price,
            last_dc_ts_ns=self._last_dc_ts_ns,
            overshoot_anchor_price=self._overshoot_anchor_price,
            overshoot_anchor_ts_ns=self._overshoot_anchor_ts_ns,
            event_count=self._event_count,
            overshoot_count=self._overshoot_count,
            last_signal_ts_ns=self._last_signal_ts_ns,
            last_signal_direction=self._last_signal_direction,
            last_tick_ts_ns=self._last_tick_ts_ns,
            recovered=False,
        )

    def restore_state(self, state: DCEngineState) -> None:
        self._symbol = state.symbol
        self.theta = state.theta
        self._phase = state.phase
        self._current_direction = state.current_direction
        self._last_extreme_price = state.last_extreme_price
        self._last_extreme_ts_ns = state.last_extreme_ts_ns
        self._last_dc_price = state.last_dc_price
        self._last_dc_ts_ns = state.last_dc_ts_ns
        self._overshoot_anchor_price = state.overshoot_anchor_price
        self._overshoot_anchor_ts_ns = state.overshoot_anchor_ts_ns
        self._event_count = state.event_count
        self._overshoot_count = state.overshoot_count
        self._last_signal_ts_ns = state.last_signal_ts_ns
        self._last_signal_direction = state.last_signal_direction
        self._last_tick_ts_ns = state.last_tick_ts_ns

    def update_theta(self, volatility_score: float) -> None:
        """
        Backward-aware public API retained.
        """
        self.apply_theta_update(raw_volatility_score=Decimal(str(volatility_score)))

    def apply_theta_update(self, raw_volatility_score: Decimal) -> ThetaUpdate:
        """
        Adaptive theta update with bounds and smoothing.
        """
        vol = _ensure_non_negative(_d(raw_volatility_score, field_name="raw_volatility_score"), "raw_volatility_score")
        previous_theta = self.theta

        target_theta = self.policy.initial_theta * (ONE + (vol * self.policy.volatility_multiplier))
        target_theta = _clamp(target_theta, self.policy.min_theta, self.policy.max_theta)

        alpha = self.policy.theta_smoothing_alpha
        applied_theta = (previous_theta * (ONE - alpha)) + (target_theta * alpha)
        applied_theta = _clamp(applied_theta, self.policy.min_theta, self.policy.max_theta)

        self.theta = applied_theta

        return ThetaUpdate(
            raw_volatility_score=vol,
            previous_theta=previous_theta,
            target_theta=target_theta,
            applied_theta=applied_theta,
            reason="bounded_smoothed_volatility_adaptation",
        )

    def process_tick(
        self,
        tick: DCMarketTick,
        risk: Optional[DCRiskContext] = None,
    ) -> tuple[Optional[DCEvent], Optional[DCSignalAssessment], Optional[DCSignalRecommendation]]:
        """
        Canonical entrypoint:
        1. Detect structural event
        2. Assess signal viability
        3. Build recommendation
        """
        risk = risk or DCRiskContext()

        event = self.detect_event(tick=tick)
        if event is None:
            return None, None, None

        assessment = self.assess_event(event=event, tick=tick, risk=risk)
        recommendation = self.recommend(assessment=assessment, tick=tick)

        return event, assessment, recommendation

    def detect_event(self, tick: DCMarketTick) -> Optional[DCEvent]:
        """
        Detect DC or overshoot event from incoming tick.
        """
        self._validate_tick_ordering(tick)
        self._symbol = self._symbol or tick.symbol

        local_ms = _now_ms()
        rationale: List[str] = []
        warnings: List[str] = []

        if tick.price < self.policy.min_price:
            return self._suppressed_event(
                tick=tick,
                local_ms=local_ms,
                reason=f"price_below_min<{self.policy.min_price}>",
                rationale=("invalid_price_basis",),
                warnings=tuple(warnings),
            )

        if tick.market_data_age_ms is not None and tick.market_data_age_ms > self.policy.max_tick_staleness_ms:
            warnings.append(f"stale_market_data:{tick.market_data_age_ms}ms")

        if self.policy.suppress_on_book_failure and tick.book_integrity in {
            BookIntegrity.STALE,
            BookIntegrity.UNTRUSTWORTHY,
            BookIntegrity.CROSSED,
        }:
            return self._suppressed_event(
                tick=tick,
                local_ms=local_ms,
                reason=f"book_integrity={tick.book_integrity.value}",
                rationale=("book_integrity_suppression",),
                warnings=tuple(warnings),
            )

        if self._last_extreme_price is None:
            self._last_extreme_price = tick.price
            self._last_extreme_ts_ns = tick.timestamp_ns
            self._last_tick_ts_ns = tick.timestamp_ns
            self._phase = DCPhase.SEEKING_INITIAL_DIRECTION
            self._current_direction = DCDirection.UNKNOWN

            return DCEvent(
                event_id=generate_event_id(),
                correlation_id=generate_correlation_id(),
                event_type=DCEventType.INITIALIZED,
                symbol=tick.symbol,
                timestamp_ns=tick.timestamp_ns,
                local_timestamp_ms=local_ms,
                direction=DCDirection.UNKNOWN,
                phase=self._phase,
                price=tick.price,
                previous_extreme_price=None,
                new_extreme_price=tick.price,
                theta=self.theta,
                move_pct_from_extreme=ZERO,
                move_multiple_of_theta=ZERO,
                overshoot_pct=ZERO,
                overshoot_multiple=ZERO,
                regime=tick.regime,
                liquidity_regime=tick.liquidity_regime,
                toxicity_level=tick.toxicity_level,
                book_integrity=tick.book_integrity,
                rationale=("engine_initialized",),
                warnings=tuple(warnings),
            )

        previous_extreme = self._last_extreme_price
        move_pct = (tick.price - previous_extreme) / previous_extreme
        move_multiple = abs(move_pct) / self.theta if self.theta > ZERO else ZERO

        event_type = DCEventType.NONE
        event_direction = self._current_direction
        overshoot_pct = ZERO
        overshoot_multiple = ZERO

        # Initial direction establishment
        if self._phase == DCPhase.SEEKING_INITIAL_DIRECTION:
            if move_pct >= self.theta:
                event_type = DCEventType.DIRECTIONAL_CHANGE_UP
                event_direction = DCDirection.UP
                self._phase = DCPhase.OVERSHOOT_UP
                self._current_direction = DCDirection.UP
                self._overshoot_anchor_price = tick.price
                self._overshoot_anchor_ts_ns = tick.timestamp_ns
                self._last_dc_price = tick.price
                self._last_dc_ts_ns = tick.timestamp_ns
                self._last_extreme_price = tick.price
                self._last_extreme_ts_ns = tick.timestamp_ns
                rationale.append("initial_direction_established:UP")

            elif move_pct <= -self.theta:
                event_type = DCEventType.DIRECTIONAL_CHANGE_DOWN
                event_direction = DCDirection.DOWN
                self._phase = DCPhase.OVERSHOOT_DOWN
                self._current_direction = DCDirection.DOWN
                self._overshoot_anchor_price = tick.price
                self._overshoot_anchor_ts_ns = tick.timestamp_ns
                self._last_dc_price = tick.price
                self._last_dc_ts_ns = tick.timestamp_ns
                self._last_extreme_price = tick.price
                self._last_extreme_ts_ns = tick.timestamp_ns
                rationale.append("initial_direction_established:DOWN")

            self._last_tick_ts_ns = tick.timestamp_ns

        # Ongoing state transitions
        elif self._phase == DCPhase.OVERSHOOT_UP:
            if tick.price > previous_extreme:
                event_type = DCEventType.OVERSHOOT_EXTREME_UPDATE
                event_direction = DCDirection.UP
                self._last_extreme_price = tick.price
                self._last_extreme_ts_ns = tick.timestamp_ns
                if self._overshoot_anchor_price is not None:
                    overshoot_pct = (tick.price - self._overshoot_anchor_price) / self._overshoot_anchor_price
                    overshoot_multiple = overshoot_pct / self.theta if self.theta > ZERO else ZERO
                self._overshoot_count += 1
                rationale.append("overshoot_up_extreme_update")

            elif move_pct <= -self.theta:
                event_type = DCEventType.DIRECTIONAL_CHANGE_DOWN
                event_direction = DCDirection.DOWN
                self._phase = DCPhase.OVERSHOOT_DOWN
                self._current_direction = DCDirection.DOWN
                self._overshoot_anchor_price = tick.price
                self._overshoot_anchor_ts_ns = tick.timestamp_ns
                self._last_dc_price = tick.price
                self._last_dc_ts_ns = tick.timestamp_ns
                self._last_extreme_price = tick.price
                self._last_extreme_ts_ns = tick.timestamp_ns
                rationale.append("dc_reversal:UP_to_DOWN")

            self._last_tick_ts_ns = tick.timestamp_ns

        elif self._phase == DCPhase.OVERSHOOT_DOWN:
            if tick.price < previous_extreme:
                event_type = DCEventType.OVERSHOOT_EXTREME_UPDATE
                event_direction = DCDirection.DOWN
                self._last_extreme_price = tick.price
                self._last_extreme_ts_ns = tick.timestamp_ns
                if self._overshoot_anchor_price is not None:
                    overshoot_pct = (self._overshoot_anchor_price - tick.price) / self._overshoot_anchor_price
                    overshoot_multiple = overshoot_pct / self.theta if self.theta > ZERO else ZERO
                self._overshoot_count += 1
                rationale.append("overshoot_down_extreme_update")

            elif move_pct >= self.theta:
                event_type = DCEventType.DIRECTIONAL_CHANGE_UP
                event_direction = DCDirection.UP
                self._phase = DCPhase.OVERSHOOT_UP
                self._current_direction = DCDirection.UP
                self._overshoot_anchor_price = tick.price
                self._overshoot_anchor_ts_ns = tick.timestamp_ns
                self._last_dc_price = tick.price
                self._last_dc_ts_ns = tick.timestamp_ns
                self._last_extreme_price = tick.price
                self._last_extreme_ts_ns = tick.timestamp_ns
                rationale.append("dc_reversal:DOWN_to_UP")

            self._last_tick_ts_ns = tick.timestamp_ns

        if event_type == DCEventType.NONE:
            return None

        self._event_count += 1

        event = DCEvent(
            event_id=generate_event_id(),
            correlation_id=generate_correlation_id(),
            event_type=event_type,
            symbol=tick.symbol,
            timestamp_ns=tick.timestamp_ns,
            local_timestamp_ms=local_ms,
            direction=event_direction,
            phase=self._phase,
            price=tick.price,
            previous_extreme_price=previous_extreme,
            new_extreme_price=self._last_extreme_price or tick.price,
            theta=self.theta,
            move_pct_from_extreme=move_pct,
            move_multiple_of_theta=move_multiple,
            overshoot_pct=overshoot_pct,
            overshoot_multiple=overshoot_multiple,
            regime=tick.regime,
            liquidity_regime=tick.liquidity_regime,
            toxicity_level=tick.toxicity_level,
            book_integrity=tick.book_integrity,
            rationale=tuple(rationale),
            warnings=tuple(warnings),
        )

        logger.info(
            "[ADAPTIVE_DC] event symbol=%s type=%s dir=%s price=%s theta=%s move_pct=%s phase=%s",
            event.symbol,
            event.event_type.value,
            event.direction.value,
            event.price,
            event.theta,
            event.move_pct_from_extreme,
            event.phase.value,
        )

        return event

    def assess_event(
        self,
        event: DCEvent,
        tick: DCMarketTick,
        risk: Optional[DCRiskContext] = None,
    ) -> DCSignalAssessment:
        """
        Assess event quality and signal emission viability.
        """
        risk = risk or DCRiskContext()
        rationale: List[str] = list(event.rationale)
        warnings: List[str] = list(event.warnings)

        signal_direction = SignalDirection.NEUTRAL
        confidence = Decimal("0.00")
        quality = DCSignalQuality.LOW
        priority = PriorityClass.DEFERRED
        authority_tier = AuthorityTier.ADVISORY
        suppress_reason: Optional[str] = None
        signal_emittable = False

        if event.event_type == DCEventType.INITIALIZED:
            suppress_reason = "initialization_event"
            rationale.append("no_trade_on_initialization")

        elif event.suppressed:
            suppress_reason = event.suppress_reason or "event_suppressed"
            rationale.append(f"event_suppressed:{suppress_reason}")

        elif event.event_type == DCEventType.OVERSHOOT_EXTREME_UPDATE:
            suppress_reason = "overshoot_update_only"
            confidence = Decimal("0.20")
            quality = DCSignalQuality.LOW
            rationale.append("overshoot_continuation_no_new_direction")

        elif event.event_type == DCEventType.DIRECTIONAL_CHANGE_UP:
            signal_direction = SignalDirection.LONG
            confidence = self._score_confidence(event=event, tick=tick, risk=risk)
            quality = self._classify_quality(confidence)
            priority, authority_tier = self._classify_priority(confidence, tick, risk)
            signal_emittable = True

        elif event.event_type == DCEventType.DIRECTIONAL_CHANGE_DOWN:
            signal_direction = SignalDirection.SHORT
            confidence = self._score_confidence(event=event, tick=tick, risk=risk)
            quality = self._classify_quality(confidence)
            priority, authority_tier = self._classify_priority(confidence, tick, risk)
            signal_emittable = True

        # Debounce / anti-churn
        if signal_emittable and self._last_signal_ts_ns is not None:
            delta_ns = event.timestamp_ns - self._last_signal_ts_ns
            if delta_ns < self.policy.min_signal_interval_ns:
                signal_emittable = False
                suppress_reason = f"signal_debounce<{self.policy.min_signal_interval_ns}ns"
                rationale.append("debounce_suppression")

        # Risk governance suppression
        if signal_emittable:
            blocked_reason = self._risk_suppress_reason(tick=tick, risk=risk)
            if blocked_reason is not None:
                signal_emittable = False
                suppress_reason = blocked_reason
                rationale.append(f"risk_suppressed:{blocked_reason}")

        return DCSignalAssessment(
            assessment_id=generate_signal_id(),
            correlation_id=event.correlation_id,
            timestamp_ms=_now_ms(),
            symbol=event.symbol,
            signal_direction=signal_direction,
            event_type=event.event_type,
            event_direction=event.direction,
            signal_emittable=signal_emittable,
            suppress_reason=suppress_reason,
            theta=event.theta,
            move_pct_from_extreme=event.move_pct_from_extreme,
            move_multiple_of_theta=event.move_multiple_of_theta,
            overshoot_pct=event.overshoot_pct,
            overshoot_multiple=event.overshoot_multiple,
            confidence=confidence,
            quality=quality,
            priority=priority,
            authority_tier=authority_tier,
            regime=event.regime,
            liquidity_regime=event.liquidity_regime,
            toxicity_level=event.toxicity_level,
            book_integrity=event.book_integrity,
            risk_level=risk.risk_level,
            risk_action=risk.risk_action,
            rationale=tuple(rationale),
            warnings=tuple(warnings),
        )

    def recommend(
        self,
        assessment: DCSignalAssessment,
        tick: DCMarketTick,
    ) -> Optional[DCSignalRecommendation]:
        """
        Build canonical recommendation if assessment is emittable and cooldown allows.
        """
        if not assessment.signal_emittable:
            return None

        now_ms = _now_ms()
        if self._is_cooldown_active(now_ms):
            logger.info(
                "[ADAPTIVE_DC] suppressed_by_cooldown symbol=%s direction=%s",
                assessment.symbol,
                assessment.signal_direction.value,
            )
            return None

        recommendation = DCSignalRecommendation(
            recommendation_id=generate_signal_id(),
            correlation_id=assessment.correlation_id,
            assessment_id=assessment.assessment_id,
            created_at_ms=now_ms,
            symbol=assessment.symbol,
            signal_direction=assessment.signal_direction,
            confidence=assessment.confidence,
            quality=assessment.quality,
            event_type=assessment.event_type,
            event_direction=assessment.event_direction,
            theta=assessment.theta,
            priority=assessment.priority,
            authority_tier=assessment.authority_tier,
            regime=assessment.regime,
            liquidity_regime=assessment.liquidity_regime,
            toxicity_level=assessment.toxicity_level,
            risk_level=assessment.risk_level,
            risk_action=assessment.risk_action,
            replay_mode=tick.replay_mode,
            execution_mode=tick.execution_mode,
            rationale=assessment.rationale,
            warnings=assessment.warnings,
        )

        self._last_signal_ts_ns = tick.timestamp_ns
        self._last_signal_direction = assessment.signal_direction

        logger.info(
            "[ADAPTIVE_DC] recommendation symbol=%s direction=%s confidence=%s quality=%s "
            "event=%s theta=%s regime=%s liquidity=%s risk=%s/%s",
            recommendation.symbol,
            recommendation.signal_direction.value,
            recommendation.confidence,
            recommendation.quality.value,
            recommendation.event_type.value,
            recommendation.theta,
            recommendation.regime.name,
            recommendation.liquidity_regime.value,
            recommendation.risk_level.name,
            recommendation.risk_action.value,
        )

        return recommendation

    # ------------------------------------------------------------------
    # Backward-aware compatibility entrypoint
    # ------------------------------------------------------------------

    def on_tick(self, price: Decimal, ts_ns: int) -> Optional[OrderSide]:
        """
        Legacy compatibility facade.

        Preserves:
            on_tick(price, ts_ns) -> Optional[OrderSide]

        Internally delegates to canonical DC event/assessment/recommendation flow.
        """
        tick = DCMarketTick(
            symbol="UNKNOWN",
            price=_d(price, field_name="price"),
            timestamp_ns=int(ts_ns),
        )
        risk = DCRiskContext()

        _, _, recommendation = self.process_tick(tick=tick, risk=risk)
        if recommendation is None:
            return None
        return recommendation.to_legacy_order_side()

    # ------------------------------------------------------------------
    # Internal mechanics
    # ------------------------------------------------------------------

    def _validate_tick_ordering(self, tick: DCMarketTick) -> None:
        if self._last_tick_ts_ns is not None and tick.timestamp_ns < self._last_tick_ts_ns:
            raise ValueError(
                f"out_of_order_tick timestamp_ns={tick.timestamp_ns} < last_tick_ts_ns={self._last_tick_ts_ns}"
            )

    def _suppressed_event(
        self,
        *,
        tick: DCMarketTick,
        local_ms: int,
        reason: str,
        rationale: tuple[str, ...],
        warnings: tuple[str, ...],
    ) -> DCEvent:
        return DCEvent(
            event_id=generate_event_id(),
            correlation_id=generate_correlation_id(),
            event_type=DCEventType.SUPPRESSED,
            symbol=tick.symbol,
            timestamp_ns=tick.timestamp_ns,
            local_timestamp_ms=local_ms,
            direction=self._current_direction,
            phase=self._phase,
            price=tick.price,
            previous_extreme_price=self._last_extreme_price,
            new_extreme_price=self._last_extreme_price or tick.price,
            theta=self.theta,
            move_pct_from_extreme=ZERO,
            move_multiple_of_theta=ZERO,
            overshoot_pct=ZERO,
            overshoot_multiple=ZERO,
            regime=tick.regime,
            liquidity_regime=tick.liquidity_regime,
            toxicity_level=tick.toxicity_level,
            book_integrity=tick.book_integrity,
            suppressed=True,
            suppress_reason=reason,
            rationale=rationale,
            warnings=warnings,
        )

    def _score_confidence(
        self,
        *,
        event: DCEvent,
        tick: DCMarketTick,
        risk: DCRiskContext,
    ) -> Decimal:
        """
        Conservative confidence scoring from structural event quality and context.
        Returns [0, 1].
        """
        score = Decimal("0.50")

        # structural magnitude
        score += _clamp(event.move_multiple_of_theta / Decimal("4.0"), ZERO, Decimal("0.20"))

        # overshoot context adds confidence only slightly
        score += _clamp(event.overshoot_multiple / Decimal("8.0"), ZERO, Decimal("0.10"))

        # toxicity/book damage reduce confidence
        if tick.toxicity_level in {ToxicityLevel.TOXIC, ToxicityLevel.EXTREME}:
            score -= Decimal("0.10")

        if tick.book_integrity in {BookIntegrity.THIN, BookIntegrity.HOLLOW, BookIntegrity.FRAGMENTED}:
            score -= Decimal("0.08")

        if tick.book_integrity in {BookIntegrity.CROSSED, BookIntegrity.UNTRUSTWORTHY, BookIntegrity.STALE}:
            score -= Decimal("0.20")

        # regime adjustments
        if is_crisis_regime(tick.regime):
            score -= Decimal("0.10")

        # risk adjustments
        if is_high_risk_level(risk.risk_level):
            score -= Decimal("0.10")

        if risk.risk_action in {
            RiskAction.THROTTLE,
            RiskAction.REDUCE_SIZE,
            RiskAction.REDUCE_FREQUENCY,
        }:
            score -= Decimal("0.05")

        return _clamp(score, ZERO, ONE)

    def _classify_quality(self, confidence: Decimal) -> DCSignalQuality:
        if confidence >= Decimal("0.90"):
            return DCSignalQuality.INSTITUTIONAL
        if confidence >= Decimal("0.75"):
            return DCSignalQuality.HIGH
        if confidence >= Decimal("0.55"):
            return DCSignalQuality.MEDIUM
        return DCSignalQuality.LOW

    def _classify_priority(
        self,
        confidence: Decimal,
        tick: DCMarketTick,
        risk: DCRiskContext,
    ) -> tuple[PriorityClass, AuthorityTier]:
        if (
            confidence >= Decimal("0.85")
            and not is_crisis_regime(tick.regime)
            and risk.risk_level <= RiskLevel.MEDIUM
        ):
            return PriorityClass.URGENT, AuthorityTier.SOFT_BLOCK

        if confidence >= Decimal("0.65"):
            return PriorityClass.NORMAL, AuthorityTier.ADVISORY

        return PriorityClass.DEFERRED, AuthorityTier.ADVISORY

    def _risk_suppress_reason(
        self,
        *,
        tick: DCMarketTick,
        risk: DCRiskContext,
    ) -> Optional[str]:
        if risk.kill_switch_active:
            return "kill_switch_active"

        if risk.risk_action == RiskAction.KILL_SWITCH:
            return "risk_action_kill_switch"

        if is_blocking_risk_action(risk.risk_action):
            if risk.risk_action == RiskAction.SAFE_MODE and self.policy.allow_signals_in_safe_mode:
                pass
            else:
                return f"blocking_risk_action:{risk.risk_action.value}"

        if risk.safe_mode_active and not self.policy.allow_signals_in_safe_mode:
            return "safe_mode_signal_suppression"

        if self.policy.suppress_in_crisis_infra and tick.regime == RegimeType.CRISIS_INFRA_FAILURE:
            return "crisis_infra_failure"

        return None

    def _is_cooldown_active(self, now_ms: int) -> bool:
        if self._last_signal_ts_ns is None:
            return False
        last_signal_ms = self._last_signal_ts_ns // 1_000_000
        return (now_ms - last_signal_ms) < self.policy.cooldown_ms


__all__ = [
    "DCDirection",
    "DCPhase",
    "DCEventType",
    "DCSignalQuality",
    "DCPolicyConfig",
    "DCMarketTick",
    "DCRiskContext",
    "ThetaUpdate",
    "DCEngineState",
    "DCEvent",
    "DCSignalAssessment",
    "DCSignalRecommendation",
    "AdaptiveDC",
]
