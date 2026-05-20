"""
app/strategies/moving_floor.py
POVERTY_KILLER — TOPOLOGICAL MOVING FLOOR ENGINE

ARCHITECTURAL ROLE
------------------
- Subordinate strategy/differentiator engine.
- NOT a standalone live authority. NOT a parallel execution system.
- Not yet integrated into the live spine (Pending upstream wiring).
- Designed strictly to protect profits via dynamic, topology-aware support levels.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum, unique
from typing import Any, Optional

# Canonical enums imported from models layer
from app.models.enums import (
    AuthorityTier,
    BookIntegrity,
    ExecutionMode,
    LiquidityRegime,
    OrderSide,
    PriorityClass,
    RegimeType,
    ReplayMode,
    RiskAction,
    RiskLevel,
    SignalDirection,
    ToxicityLevel,
    is_crisis_regime
)

# Helper predicate imported from current lawful seam until canonicalized
from app.utils.enums import is_blocking_risk_action

from app.utils.ids import generate_correlation_id, generate_event_id, generate_signal_id

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS / HELPERS
# ============================================================================

ZERO = Decimal("0")
ONE = Decimal("1")
EPS = Decimal("0.0000000001")
BPS_DIVISOR = Decimal("10000")

def _d(value: Any, *, field_name: str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"invalid decimal for {field_name}: {value!r}") from exc

def _ensure_positive(value: Decimal, field_name: str) -> Decimal:
    if value <= ZERO:
        raise ValueError(f"{field_name} must be strictly positive, got {value}")
    return value

def _ensure_non_negative(value: Decimal, field_name: str) -> Decimal:
    if value < ZERO:
        raise ValueError(f"{field_name} must be non-negative, got {value}")
    return value

def _clamp(value: Decimal, lower: Decimal, upper: Decimal) -> Decimal:
    if value < lower:
        return lower
    if value > upper:
        return upper
    return value

def _local_now_ms() -> int:
    """Monotonic clock used EXCLUSIVELY for local metadata, never for market logic."""
    return time.monotonic_ns() // 1_000_000

# ============================================================================
# ENUMS
# ============================================================================

@unique
class FloorPhase(str, Enum):
    UNINITIALIZED = "UNINITIALIZED"
    ARMED = "ARMED"
    BREACHED = "BREACHED"

@unique
class FloorEventType(str, Enum):
    INITIALIZED = "INITIALIZED"
    RATCHET_UP = "RATCHET_UP"
    TOPOLOGICAL_BREACH = "TOPOLOGICAL_BREACH"
    SUPPRESSED = "SUPPRESSED"

@unique
class FloorSignalQuality(str, Enum):
    UNKNOWN = "UNKNOWN"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    INSTITUTIONAL = "INSTITUTIONAL"

# ============================================================================
# CONFIG / INPUT MODELS
# ============================================================================

@dataclass(frozen=True, slots=True)
class FloorPolicyConfig:
    base_buffer: Decimal = Decimal("0.0200")
    min_buffer: Decimal = Decimal("0.0050")
    max_buffer: Decimal = Decimal("0.0400")

    # Hysteresis & Debounce
    min_signal_interval_ns: int = 1_000_000_000  # 1 second
    ratchet_cooldown_ns: int = 250_000_000       # 250ms

    # Thresholds
    high_quality_obi_threshold: Decimal = Decimal("-0.50")

    # Slippage Simulator (BPS)
    slippage_bps_normal: Decimal = Decimal("5.0")
    slippage_bps_toxic: Decimal = Decimal("25.0")
    slippage_bps_crisis: Decimal = Decimal("100.0")

    suppress_on_book_failure: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_buffer", _ensure_positive(_d(self.base_buffer, field_name="base_buffer"), "base_buffer"))
        object.__setattr__(self, "min_buffer", _ensure_positive(_d(self.min_buffer, field_name="min_buffer"), "min_buffer"))
        object.__setattr__(self, "max_buffer", _ensure_positive(_d(self.max_buffer, field_name="max_buffer"), "max_buffer"))

        if self.min_buffer > self.max_buffer:
            raise ValueError("min_buffer cannot exceed max_buffer")
        if self.base_buffer < self.min_buffer or self.base_buffer > self.max_buffer:
            raise ValueError("base_buffer must lie within [min_buffer, max_buffer]")
        if self.min_signal_interval_ns < 0 or self.ratchet_cooldown_ns < 0:
            raise ValueError("Timing intervals must be non-negative")

@dataclass(frozen=True, slots=True)
class FloorMarketTick:
    symbol: str
    price: Decimal
    timestamp_ns: int
    bid_volume: Decimal
    ask_volume: Decimal
    regime: RegimeType = RegimeType.UNKNOWN
    liquidity_regime: LiquidityRegime = LiquidityRegime.UNKNOWN
    toxicity_level: ToxicityLevel = ToxicityLevel.UNKNOWN
    book_integrity: BookIntegrity = BookIntegrity.UNKNOWN
    replay_mode: ReplayMode = ReplayMode.LIVE
    execution_mode: ExecutionMode = ExecutionMode.LIVE

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("symbol cannot be blank")
        object.__setattr__(self, "price", _ensure_positive(_d(self.price, field_name="price"), "price"))
        object.__setattr__(self, "bid_volume", _ensure_non_negative(_d(self.bid_volume, field_name="bid_volume"), "bid_volume"))
        object.__setattr__(self, "ask_volume", _ensure_non_negative(_d(self.ask_volume, field_name="ask_volume"), "ask_volume"))
        if self.timestamp_ns <= 0:
            raise ValueError("timestamp_ns must be strictly positive")

@dataclass(frozen=True, slots=True)
class FloorRiskContext:
    risk_level: RiskLevel = RiskLevel.NONE
    risk_action: RiskAction = RiskAction.ALLOW
    kill_switch_active: bool = False

# ============================================================================
# STATE / OUTPUT MODELS
# ============================================================================

@dataclass(frozen=True, slots=True)
class FloorEngineState:
    symbol: Optional[str]
    phase: FloorPhase
    current_floor: Decimal
    highest_price_seen: Decimal
    last_obi: Decimal
    last_buffer_pct: Decimal
    last_tick_ts_ns: Optional[int]
    last_ratchet_ts_ns: Optional[int]
    last_signal_ts_ns: Optional[int]
    event_count: int

    def __post_init__(self) -> None:
        if self.current_floor < ZERO: raise ValueError("current_floor cannot be negative")
        if self.highest_price_seen < ZERO: raise ValueError("highest_price_seen cannot be negative")
        if self.event_count < 0: raise ValueError("event_count cannot be negative")
        if self.last_buffer_pct < ZERO: raise ValueError("last_buffer_pct cannot be negative")

        if self.last_obi < Decimal("-1.0") or self.last_obi > Decimal("1.0"):
            raise ValueError(f"last_obi must be bounded [-1.0, 1.0], got {self.last_obi}")

        if self.last_tick_ts_ns is not None and self.last_tick_ts_ns <= 0:
            raise ValueError("last_tick_ts_ns must be strictly positive")
        if self.last_ratchet_ts_ns is not None and self.last_ratchet_ts_ns <= 0:
            raise ValueError("last_ratchet_ts_ns must be strictly positive")
        if self.last_signal_ts_ns is not None and self.last_signal_ts_ns <= 0:
            raise ValueError("last_signal_ts_ns must be strictly positive")

        # Coherence invariants
        if self.symbol is None and self.phase != FloorPhase.UNINITIALIZED:
            raise ValueError("symbol cannot be None if phase is not UNINITIALIZED")

        if self.phase == FloorPhase.UNINITIALIZED:
            if self.current_floor > ZERO:
                raise ValueError("current_floor must be 0 when phase is UNINITIALIZED")
            if self.highest_price_seen > ZERO:
                raise ValueError("highest_price_seen must be 0 when phase is UNINITIALIZED")

        if self.phase == FloorPhase.ARMED and self.current_floor >= self.highest_price_seen and self.highest_price_seen > ZERO:
            raise ValueError("State corruption: Armed floor cannot be >= highest price seen.")

@dataclass(frozen=True, slots=True)
class FloorEvent:
    event_id: int
    correlation_id: int
    event_type: FloorEventType
    symbol: str
    timestamp_ns: int
    local_timestamp_ms: int

    phase: FloorPhase
    price: Decimal
    current_floor: Decimal
    obi: Decimal
    dynamic_buffer_pct: Decimal

    regime: RegimeType
    toxicity_level: ToxicityLevel
    book_integrity: BookIntegrity

    suppressed: bool = False
    suppress_reason: Optional[str] = None
    rationale: tuple[str, ...] = field(default_factory=tuple)

@dataclass(frozen=True, slots=True)
class FloorSignalAssessment:
    assessment_id: int
    correlation_id: int

    symbol: str
    signal_direction: SignalDirection
    event_type: FloorEventType

    signal_emittable: bool
    suppress_reason: Optional[str]

    confidence: Decimal
    quality: FloorSignalQuality
    priority: PriorityClass
    authority_tier: AuthorityTier

    worst_case_fill_price: Decimal
    risk_action: RiskAction
    rationale: tuple[str, ...] = field(default_factory=tuple)

@dataclass(frozen=True, slots=True)
class FloorSignalRecommendation:
    recommendation_id: int
    correlation_id: int
    assessment_id: int

    symbol: str
    signal_direction: SignalDirection
    confidence: Decimal
    quality: FloorSignalQuality

    event_type: FloorEventType
    priority: PriorityClass
    authority_tier: AuthorityTier

    worst_case_fill_price: Decimal

    source_module: str = "app.strategies.moving_floor"
    replay_mode: ReplayMode = ReplayMode.LIVE
    rationale: tuple[str, ...] = field(default_factory=tuple)

    def to_legacy_order_side(self) -> Optional[OrderSide]:
        """
        COMPATIBILITY SHIM ONLY.
        This translates intent to exchange-side syntax. It does NOT authorize
        opening short exposure or imply independent execution authority.
        """
        if self.signal_direction == SignalDirection.SHORT:
            return OrderSide.SELL
        if self.signal_direction == SignalDirection.LONG:
            return OrderSide.BUY
        return None

# ============================================================================
# ENGINE
# ============================================================================

class TopologicalMovingFloor:
    """
    Canonical Adaptive Exit Engine using Order Book Imbalance (OBI).
    Complies strictly with the `process_tick` -> `detect` -> `assess` -> `recommend` pipeline.
    """

    __slots__ = (
        'policy', '_symbol', '_phase', '_current_floor', '_highest_price_seen',
        '_last_obi', '_last_buffer_pct', '_last_tick_ts_ns', '_last_ratchet_ts_ns',
        '_last_signal_ts_ns', '_event_count', 'logger'
    )

    def __init__(self, base_buffer: Decimal = Decimal("0.0200")) -> None:
        self.policy = FloorPolicyConfig(base_buffer=_d(base_buffer, field_name="base_buffer"))
        self.logger = logging.getLogger(__name__)

        self._symbol: Optional[str] = None
        self._phase = FloorPhase.UNINITIALIZED
        self._current_floor = ZERO
        self._highest_price_seen = ZERO
        self._last_obi = ZERO
        self._last_buffer_pct = self.policy.base_buffer
        self._last_tick_ts_ns: Optional[int] = None
        self._last_ratchet_ts_ns: Optional[int] = None
        self._last_signal_ts_ns: Optional[int] = None
        self._event_count: int = 0

    # ------------------------------------------------------------------
    # Canonical API / Observability
    # ------------------------------------------------------------------

    def snapshot_state(self) -> FloorEngineState:
        """Constant-time local state extraction, no I/O."""
        return FloorEngineState(
            symbol=self._symbol,
            phase=self._phase,
            current_floor=self._current_floor,
            highest_price_seen=self._highest_price_seen,
            last_obi=self._last_obi,
            last_buffer_pct=self._last_buffer_pct,
            last_tick_ts_ns=self._last_tick_ts_ns,
            last_ratchet_ts_ns=self._last_ratchet_ts_ns,
            last_signal_ts_ns=self._last_signal_ts_ns,
            event_count=self._event_count,
        )

    def restore_state(self, state: FloorEngineState) -> None:
        """
        Bounded local state restoration with strict trust and coherence boundaries.
        Protects existing engine instances from foreign or corrupted state injection.
        """
        if self._symbol is not None and state.symbol is not None and self._symbol != state.symbol:
            raise ValueError(f"State hijacking blocked. Cannot restore {state.symbol} state into {self._symbol} engine.")

        self._symbol = state.symbol
        self._phase = state.phase
        self._current_floor = state.current_floor
        self._highest_price_seen = state.highest_price_seen
        self._last_obi = state.last_obi
        self._last_buffer_pct = state.last_buffer_pct
        self._last_tick_ts_ns = state.last_tick_ts_ns
        self._last_ratchet_ts_ns = state.last_ratchet_ts_ns
        self._last_signal_ts_ns = state.last_signal_ts_ns
        self._event_count = state.event_count

    # ------------------------------------------------------------------
    # Pipeline Execution
    # ------------------------------------------------------------------

    def process_tick(
        self,
        tick: FloorMarketTick,
        risk: Optional[FloorRiskContext] = None,
    ) -> tuple[Optional[FloorEvent], Optional[FloorSignalAssessment], Optional[FloorSignalRecommendation]]:
        """
        Constant-time deterministic single-tick processing pipeline.
        """
        risk = risk or FloorRiskContext()

        event = self.detect_event(tick=tick)
        if event is None:
            return None, None, None

        assessment = self.assess_event(event=event, tick=tick, risk=risk)
        recommendation = self.recommend(assessment=assessment, tick=tick)

        return event, assessment, recommendation

    def detect_event(self, tick: FloorMarketTick) -> Optional[FloorEvent]:
        """
        Bounded deterministic structural floor event detection.
        """
        # STRICT SYMBOL ENFORCEMENT
        if self._symbol is not None and self._symbol != tick.symbol:
            raise ValueError(f"Foreign symbol rejected. Expected {self._symbol}, got {tick.symbol}")

        # STRICT OUT-OF-ORDER ENFORCEMENT
        if self._last_tick_ts_ns is not None and tick.timestamp_ns < self._last_tick_ts_ns:
            raise ValueError(f"Out-of-order tick sequence. Current {tick.timestamp_ns} < Last {self._last_tick_ts_ns}")

        self._symbol = tick.symbol
        self._last_tick_ts_ns = tick.timestamp_ns
        local_ms = _local_now_ms()

        # SUPPRESSION CONTRACT: Emit typed suppressed event rather than failing silently
        if self.policy.suppress_on_book_failure and tick.book_integrity in {BookIntegrity.CROSSED, BookIntegrity.UNTRUSTWORTHY}:
            self.logger.debug(f"Tick suppressed: Book Integrity Failure ({tick.book_integrity.value})")
            return FloorEvent(
                event_id=generate_event_id(), correlation_id=generate_correlation_id(),
                event_type=FloorEventType.SUPPRESSED, symbol=tick.symbol, timestamp_ns=tick.timestamp_ns,
                local_timestamp_ms=local_ms, phase=self._phase, price=tick.price, current_floor=self._current_floor,
                obi=self._last_obi, dynamic_buffer_pct=self._last_buffer_pct, regime=tick.regime,
                toxicity_level=tick.toxicity_level, book_integrity=tick.book_integrity,
                suppressed=True, suppress_reason=f"book_integrity_failure:{tick.book_integrity.value}",
                rationale=("suppressed_due_to_untrustworthy_book",)
            )

        # Topology Calculation (OBI)
        total_vol = tick.bid_volume + tick.ask_volume
        obi = (tick.bid_volume - tick.ask_volume) / total_vol if total_vol > ZERO else ZERO
        self._last_obi = obi

        # Dynamic Buffer Math & Strict Clamping
        if obi < ZERO:
            calculated_buffer = self.policy.base_buffer + ((self.policy.base_buffer - self.policy.min_buffer) * obi)
        else:
            calculated_buffer = self.policy.base_buffer + ((self.policy.max_buffer - self.policy.base_buffer) * obi)

        dynamic_buffer = _clamp(calculated_buffer, self.policy.min_buffer, self.policy.max_buffer)
        self._last_buffer_pct = dynamic_buffer

        # 1. Initialization
        if self._phase == FloorPhase.UNINITIALIZED:
            self._phase = FloorPhase.ARMED
            self._highest_price_seen = tick.price
            self._current_floor = tick.price * (ONE - dynamic_buffer)
            self._last_ratchet_ts_ns = tick.timestamp_ns
            self._event_count += 1

            if self._current_floor >= tick.price:
                raise ValueError(f"Catastrophic Invariant: Init floor {self._current_floor} >= price {tick.price}")

            return FloorEvent(
                event_id=generate_event_id(), correlation_id=generate_correlation_id(),
                event_type=FloorEventType.INITIALIZED, symbol=tick.symbol, timestamp_ns=tick.timestamp_ns,
                local_timestamp_ms=local_ms, phase=self._phase, price=tick.price,
                current_floor=self._current_floor, obi=obi, dynamic_buffer_pct=dynamic_buffer,
                regime=tick.regime, toxicity_level=tick.toxicity_level, book_integrity=tick.book_integrity,
                rationale=("floor_armed",)
            )

        # Update observability metric (Not used for ratchet math)
        if tick.price > self._highest_price_seen:
            self._highest_price_seen = tick.price

        # 2. Trailing Current-Price Ratchet Logic with Hysteresis
        new_candidate = tick.price * (ONE - dynamic_buffer)

        if new_candidate >= tick.price:
            raise ValueError(f"Catastrophic Invariant: Candidate floor {new_candidate} >= price {tick.price}")

        if new_candidate > self._current_floor:
            time_since_ratchet = tick.timestamp_ns - (self._last_ratchet_ts_ns or 0)

            if time_since_ratchet >= self.policy.ratchet_cooldown_ns:
                self._current_floor = new_candidate
                self._last_ratchet_ts_ns = tick.timestamp_ns
                self._event_count += 1
                return FloorEvent(
                    event_id=generate_event_id(), correlation_id=generate_correlation_id(),
                    event_type=FloorEventType.RATCHET_UP, symbol=tick.symbol, timestamp_ns=tick.timestamp_ns,
                    local_timestamp_ms=local_ms, phase=self._phase, price=tick.price,
                    current_floor=self._current_floor, obi=obi, dynamic_buffer_pct=dynamic_buffer,
                    regime=tick.regime, toxicity_level=tick.toxicity_level, book_integrity=tick.book_integrity,
                    rationale=("floor_ratchet_up",)
                )

        # 3. Breach Logic
        if tick.price <= self._current_floor and self._phase == FloorPhase.ARMED:
            self._phase = FloorPhase.BREACHED
            self._event_count += 1
            return FloorEvent(
                event_id=generate_event_id(), correlation_id=generate_correlation_id(),
                event_type=FloorEventType.TOPOLOGICAL_BREACH, symbol=tick.symbol, timestamp_ns=tick.timestamp_ns,
                local_timestamp_ms=local_ms, phase=self._phase, price=tick.price,
                current_floor=self._current_floor, obi=obi, dynamic_buffer_pct=dynamic_buffer,
                regime=tick.regime, toxicity_level=tick.toxicity_level, book_integrity=tick.book_integrity,
                rationale=("price_crossed_topological_support",)
            )

        return None

    def assess_event(self, event: FloorEvent, tick: FloorMarketTick, risk: FloorRiskContext) -> FloorSignalAssessment:
        """
        Constant-time structural event viability and worst-case fill simulation.
        """
        signal_emittable = False
        suppress_reason = None
        direction = SignalDirection.NEUTRAL
        rationale_list = list(event.rationale)

        confidence = ZERO
        quality = FloorSignalQuality.LOW

        if event.event_type == FloorEventType.SUPPRESSED:
            signal_emittable = False
            suppress_reason = event.suppress_reason

        elif event.event_type == FloorEventType.TOPOLOGICAL_BREACH:
            # SEMANTICS: SHORT explicitly denotes structural exit/protection here, NOT autonomous short-entry
            direction = SignalDirection.SHORT
            signal_emittable = True

            if risk.kill_switch_active or is_blocking_risk_action(risk.risk_action):
                signal_emittable = False
                suppress_reason = "risk_suppressed"
                rationale_list.append("blocked_by_governance")

            # Breach Signal Debounce
            if self._last_signal_ts_ns is not None and (event.timestamp_ns - self._last_signal_ts_ns) < self.policy.min_signal_interval_ns:
                signal_emittable = False
                suppress_reason = "debounce"
                rationale_list.append("signal_debounce_active")

            # Dynamic Confidence & Quality Scoring
            if signal_emittable:
                raw_confidence = Decimal("0.80")
                if event.obi <= self.policy.high_quality_obi_threshold:
                    raw_confidence += Decimal("0.10")
                    quality = FloorSignalQuality.HIGH
                if is_crisis_regime(tick.regime):
                    raw_confidence += Decimal("0.05")
                    quality = FloorSignalQuality.INSTITUTIONAL

                confidence = _clamp(raw_confidence, ZERO, ONE)

        # Worst Case Execution Price Simulator
        wc_slippage_bps = self.policy.slippage_bps_normal
        if tick.toxicity_level in {ToxicityLevel.TOXIC, ToxicityLevel.EXTREME}:
            wc_slippage_bps = self.policy.slippage_bps_toxic
        if is_crisis_regime(tick.regime):
            wc_slippage_bps = self.policy.slippage_bps_crisis

        simulated_fill_price = tick.price * (ONE - (wc_slippage_bps / BPS_DIVISOR))

        return FloorSignalAssessment(
            assessment_id=generate_signal_id(), correlation_id=event.correlation_id,
            symbol=event.symbol, signal_direction=direction,
            event_type=event.event_type, signal_emittable=signal_emittable,
            suppress_reason=suppress_reason, confidence=confidence, quality=quality,
            priority=PriorityClass.URGENT, authority_tier=AuthorityTier.SOFT_BLOCK,
            worst_case_fill_price=simulated_fill_price, risk_action=risk.risk_action,
            rationale=tuple(rationale_list)
        )

    def recommend(self, assessment: FloorSignalAssessment, tick: FloorMarketTick) -> Optional[FloorSignalRecommendation]:
        """
        Constant-time canonical signal recommendation conversion.
        """
        if not assessment.signal_emittable:
            return None

        self._last_signal_ts_ns = tick.timestamp_ns
        return FloorSignalRecommendation(
            recommendation_id=generate_signal_id(), correlation_id=assessment.correlation_id,
            assessment_id=assessment.assessment_id, symbol=assessment.symbol,
            signal_direction=assessment.signal_direction, confidence=assessment.confidence,
            quality=assessment.quality, event_type=assessment.event_type,
            priority=assessment.priority, authority_tier=assessment.authority_tier,
            worst_case_fill_price=assessment.worst_case_fill_price,
            replay_mode=tick.replay_mode, rationale=assessment.rationale
        )