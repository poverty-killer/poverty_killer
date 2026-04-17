"""
app/execution/slippage_model.py
POVERTY_KILLER — SOVEREIGN EXECUTION IMPACT AUTHORITY (FINAL-FORM CITADEL-GRADE)

This module is the canonical execution-impact authority for pre-trade impact
estimation, impact-safe sizing, and post-trade calibration. It extends a simple
slippage heuristic into a calibrated, multi-depth, execution-style-aware model.

CAPABILITIES
------------
- multi-depth impact estimation
- spread / impact / adverse-selection decomposition
- execution-style-aware pricing assumptions
- regime / toxicity / liquidity / integrity-aware multipliers
- degraded fallback paths with explicit confidence
- impact-safe size estimation
- calibration from realized fills
- symbol/venue override profiles
- journaling and aggregate telemetry
- preserve-aware compatibility API

ARCHITECTURAL ROLE
------------------
Owns locally:
- pre-trade impact/slippage estimation
- execution-style-aware impact sizing
- local calibration state
- structured impact outputs
- impact journals and aggregate telemetry

Does NOT own:
- order routing
- order execution authority
- market data generation
- toxicity generation
- regime generation
- post-trade accounting authority

DESIGN PRINCIPLES
-----------------
1. Explicit Units
   All impact costs are modeled in basis points explicitly.

2. Conservative Degradation
   Missing depth, stale book context, or weak integrity lowers confidence and
   pushes the model toward safer outputs.

3. Calibration Without Overreach
   Calibration adjusts bounded local coefficients using realized slippage error
   without pretending to be a full learning system.

4. Preserve-Aware Compatibility
   Legacy estimate_slippage(...) and get_max_executable_size(...) are preserved.

5. Risk Mitigation First
   If the market surface is unreliable, the authority becomes more conservative.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field, replace
from decimal import Decimal, InvalidOperation, ROUND_DOWN, getcontext
from enum import Enum, unique
from typing import Any, Dict, List, Optional, Tuple

from app.utils.enums import (
    BookIntegrity,
    LiquidityRegime,
    Marketability,
    OrderSide,
    RegimeType,
    SlippageClass,
    ToxicityLevel,
)
from app.utils.ids import generate_correlation_id, generate_request_id

getcontext().prec = 28
logger = logging.getLogger(__name__)


# ============================================================================
# HELPERS
# ============================================================================

ZERO = Decimal("0")
ONE = Decimal("1")
BPS_DIVISOR = Decimal("10000")


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


def _quantize_price(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)


def _quantize_bps(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"), rounding=ROUND_DOWN)


# ============================================================================
# ENUMS
# ============================================================================

@unique
class SlippageQuality(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    DEGRADED = "DEGRADED"
    INVALID = "INVALID"


@unique
class ExecutionStyle(str, Enum):
    PASSIVE = "PASSIVE"
    PASSIVE_NEAR_TOUCH = "PASSIVE_NEAR_TOUCH"
    MARKETABLE_LIMIT = "MARKETABLE_LIMIT"
    IOC = "IOC"
    SWEEP = "SWEEP"
    TWAP_SLICE = "TWAP_SLICE"


# ============================================================================
# MODELS
# ============================================================================

@dataclass(frozen=True, slots=True)
class SlippagePolicyConfig:
    """
    Core impact policy.

    Units:
    - base_impact_bps is in basis points
    """
    base_impact_bps: Decimal = Decimal("5.0")
    size_convexity: Decimal = Decimal("2.0")
    crisis_regime_multiplier: Decimal = Decimal("2.0")
    toxicity_exponent: Decimal = Decimal("2.0")

    min_depth_floor: Decimal = Decimal("1.0")
    fallback_depth_units: Decimal = Decimal("1.0")

    degraded_confidence: Decimal = Decimal("0.50")
    invalid_confidence: Decimal = Decimal("0.10")

    calibration_learning_rate: Decimal = Decimal("0.05")
    min_symbol_adjustment: Decimal = Decimal("0.50")
    max_symbol_adjustment: Decimal = Decimal("3.00")

    adverse_selection_bps_cap: Decimal = Decimal("25.0")
    journal_capacity: int = 50000

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_impact_bps", _ensure_non_negative(_d(self.base_impact_bps, field_name="base_impact_bps"), "base_impact_bps"))
        object.__setattr__(self, "size_convexity", _ensure_positive(_d(self.size_convexity, field_name="size_convexity"), "size_convexity"))
        object.__setattr__(self, "crisis_regime_multiplier", _ensure_positive(_d(self.crisis_regime_multiplier, field_name="crisis_regime_multiplier"), "crisis_regime_multiplier"))
        object.__setattr__(self, "toxicity_exponent", _ensure_non_negative(_d(self.toxicity_exponent, field_name="toxicity_exponent"), "toxicity_exponent"))
        object.__setattr__(self, "min_depth_floor", _ensure_positive(_d(self.min_depth_floor, field_name="min_depth_floor"), "min_depth_floor"))
        object.__setattr__(self, "fallback_depth_units", _ensure_positive(_d(self.fallback_depth_units, field_name="fallback_depth_units"), "fallback_depth_units"))
        object.__setattr__(self, "degraded_confidence", _ensure_non_negative(_d(self.degraded_confidence, field_name="degraded_confidence"), "degraded_confidence"))
        object.__setattr__(self, "invalid_confidence", _ensure_non_negative(_d(self.invalid_confidence, field_name="invalid_confidence"), "invalid_confidence"))
        object.__setattr__(self, "calibration_learning_rate", _ensure_non_negative(_d(self.calibration_learning_rate, field_name="calibration_learning_rate"), "calibration_learning_rate"))
        object.__setattr__(self, "min_symbol_adjustment", _ensure_positive(_d(self.min_symbol_adjustment, field_name="min_symbol_adjustment"), "min_symbol_adjustment"))
        object.__setattr__(self, "max_symbol_adjustment", _ensure_positive(_d(self.max_symbol_adjustment, field_name="max_symbol_adjustment"), "max_symbol_adjustment"))
        object.__setattr__(self, "adverse_selection_bps_cap", _ensure_non_negative(_d(self.adverse_selection_bps_cap, field_name="adverse_selection_bps_cap"), "adverse_selection_bps_cap"))

        for field_name in ["degraded_confidence", "invalid_confidence", "calibration_learning_rate"]:
            if getattr(self, field_name) > ONE:
                raise ValueError(f"{field_name} cannot exceed 1")

        if self.min_symbol_adjustment > self.max_symbol_adjustment:
            raise ValueError("min_symbol_adjustment cannot exceed max_symbol_adjustment")
        if self.journal_capacity < 100:
            raise ValueError("journal_capacity must be >= 100")


@dataclass(frozen=True, slots=True)
class DepthProfile:
    """
    Structured depth context.
    """
    bid_depth_l1: Optional[Decimal] = None
    ask_depth_l1: Optional[Decimal] = None
    bid_depth_n: Optional[Decimal] = None
    ask_depth_n: Optional[Decimal] = None
    depth_slope: Optional[Decimal] = None
    gap_bps: Optional[Decimal] = None

    def __post_init__(self) -> None:
        for field_name in ["bid_depth_l1", "ask_depth_l1", "bid_depth_n", "ask_depth_n", "depth_slope", "gap_bps"]:
            val = getattr(self, field_name)
            if val is not None:
                dec = _ensure_non_negative(_d(val, field_name=field_name), field_name)
                object.__setattr__(self, field_name, dec)


@dataclass(frozen=True, slots=True)
class MarketImpactContext:
    symbol: str
    side: OrderSide
    quantity: Decimal
    current_price: Decimal

    depth: DepthProfile = field(default_factory=DepthProfile)
    spread_bps: Decimal = Decimal("0")
    book_imbalance: Decimal = Decimal("0")
    regime: RegimeType = RegimeType.UNKNOWN
    toxicity_score: Decimal = Decimal("0")

    liquidity_regime: LiquidityRegime = LiquidityRegime.UNKNOWN
    toxicity_level: ToxicityLevel = ToxicityLevel.UNKNOWN
    book_integrity: BookIntegrity = BookIntegrity.UNKNOWN
    marketability: Marketability = Marketability.MARKETABLE
    execution_style: ExecutionStyle = ExecutionStyle.MARKETABLE_LIMIT
    venue: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("symbol must be non-empty")
        if self.side not in {OrderSide.BUY, OrderSide.SELL}:
            raise ValueError("side must be BUY or SELL")
        object.__setattr__(self, "quantity", _ensure_non_negative(_d(self.quantity, field_name="quantity"), "quantity"))
        object.__setattr__(self, "current_price", _ensure_positive(_d(self.current_price, field_name="current_price"), "current_price"))
        object.__setattr__(self, "spread_bps", _ensure_non_negative(_d(self.spread_bps, field_name="spread_bps"), "spread_bps"))
        object.__setattr__(self, "book_imbalance", _d(self.book_imbalance, field_name="book_imbalance"))
        object.__setattr__(self, "toxicity_score", _ensure_non_negative(_d(self.toxicity_score, field_name="toxicity_score"), "toxicity_score"))


@dataclass(frozen=True, slots=True)
class SlippageEstimate:
    estimate_id: int
    correlation_id: int

    symbol: str
    side: OrderSide
    quantity: Decimal
    current_price: Decimal
    venue: Optional[str]

    spread_cost_bps: Decimal
    impact_cost_bps: Decimal
    adverse_selection_bps: Decimal
    total_slippage_bps: Decimal

    slippage_amount: Decimal
    expected_execution_price: Decimal

    normalized_size_l1: Decimal
    normalized_size_n: Decimal
    regime_multiplier: Decimal
    toxicity_multiplier: Decimal
    imbalance_multiplier: Decimal
    calibration_multiplier: Decimal

    confidence: Decimal
    quality: SlippageQuality
    slippage_class: SlippageClass
    execution_style: ExecutionStyle
    completeness_notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CalibrationFeedback:
    estimate_id: int
    symbol: str
    venue: Optional[str]
    estimated_slippage_bps: Decimal
    realized_slippage_bps: Decimal
    estimation_error_bps: Decimal
    applied_adjustment: Decimal


@dataclass(frozen=True, slots=True)
class SlippageJournalRecord:
    sequence: int
    estimate_id: int
    symbol: str
    side: str
    quantity: Decimal
    venue: Optional[str]
    total_slippage_bps: Decimal
    confidence: Decimal
    quality: SlippageQuality


@dataclass(frozen=True, slots=True)
class SlippageTelemetrySnapshot:
    estimates_count: int
    avg_total_slippage_bps: Decimal
    avg_confidence: Decimal
    degraded_estimate_count: int
    symbol_adjustments: Dict[str, Decimal]


# ============================================================================
# ENGINE
# ============================================================================

class SlippageModel:
    """
    Sovereign impact authority with:
    - multi-depth modeling
    - execution-style awareness
    - realized-fill calibration
    """

    def __init__(
        self,
        base_impact_bps: Decimal = Decimal("5.0"),
        size_convexity: Decimal = Decimal("2.0"),
        volatility_scalar: Decimal = Decimal("2.0")
    ):
        self.policy = SlippagePolicyConfig(
            base_impact_bps=base_impact_bps,
            size_convexity=size_convexity,
            crisis_regime_multiplier=volatility_scalar,
        )

        # Preserve legacy names
        self.base_impact = self.policy.base_impact_bps
        self.size_convexity = self.policy.size_convexity
        self.v_scalar = self.policy.crisis_regime_multiplier

        self._journal: List[SlippageJournalRecord] = []
        self._journal_seq = 0

        # Local bounded calibration state
        self._symbol_adjustments: Dict[str, Decimal] = {}
        self._venue_symbol_adjustments: Dict[Tuple[str, str], Decimal] = {}

    # ------------------------------------------------------------------
    # Legacy compatibility API
    # ------------------------------------------------------------------

    def estimate_slippage(
        self,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        current_price: Decimal,
        book_imbalance: float,
        regime: RegimeType,
        toxicity_score: float
    ) -> Decimal:
        """
        Legacy compatibility path.

        Returns expected execution price for compatibility.

        This path is intentionally degraded because it lacks explicit depth,
        spread, integrity, liquidity regime, and execution-style truth.
        """
        result = self.estimate_slippage_detailed(
            MarketImpactContext(
                symbol=symbol,
                side=side,
                quantity=_d(quantity, field_name="quantity"),
                current_price=_d(current_price, field_name="current_price"),
                depth=DepthProfile(),
                spread_bps=Decimal("0"),
                book_imbalance=Decimal(str(book_imbalance)),
                regime=regime,
                toxicity_score=Decimal(str(toxicity_score)),
                liquidity_regime=LiquidityRegime.UNKNOWN,
                toxicity_level=ToxicityLevel.UNKNOWN,
                book_integrity=BookIntegrity.UNKNOWN,
                marketability=Marketability.MARKETABLE,
                execution_style=ExecutionStyle.MARKETABLE_LIMIT,
                venue=None,
            ),
            compatibility_mode=True,
        )
        return result.expected_execution_price

    def get_max_executable_size(self, target_slippage_bps: Decimal, current_price: Decimal) -> Decimal:
        """
        Legacy compatibility inverse path.
        """
        return self.estimate_max_executable_size(
            target_slippage_bps=_d(target_slippage_bps, field_name="target_slippage_bps"),
            market=MarketImpactContext(
                symbol="UNKNOWN",
                side=OrderSide.BUY,
                quantity=Decimal("1"),
                current_price=_d(current_price, field_name="current_price"),
                depth=DepthProfile(),
                spread_bps=Decimal("0"),
                book_imbalance=ZERO,
                regime=RegimeType.UNKNOWN,
                toxicity_score=ZERO,
                liquidity_regime=LiquidityRegime.UNKNOWN,
                toxicity_level=ToxicityLevel.UNKNOWN,
                book_integrity=BookIntegrity.UNKNOWN,
                marketability=Marketability.MARKETABLE,
                execution_style=ExecutionStyle.MARKETABLE_LIMIT,
                venue=None,
            ),
            compatibility_mode=True,
        )

    # ------------------------------------------------------------------
    # Canonical API
    # ------------------------------------------------------------------

    def estimate_slippage_detailed(
        self,
        market: MarketImpactContext,
        *,
        compatibility_mode: bool = False,
    ) -> SlippageEstimate:
        notes: List[str] = []
        quality = SlippageQuality.COMPLETE
        confidence = ONE

        if market.quantity == ZERO:
            return SlippageEstimate(
                estimate_id=generate_request_id(),
                correlation_id=generate_correlation_id(),
                symbol=market.symbol,
                side=market.side,
                quantity=market.quantity,
                current_price=market.current_price,
                venue=market.venue,
                spread_cost_bps=ZERO,
                impact_cost_bps=ZERO,
                adverse_selection_bps=ZERO,
                total_slippage_bps=ZERO,
                slippage_amount=ZERO,
                expected_execution_price=market.current_price,
                normalized_size_l1=ZERO,
                normalized_size_n=ZERO,
                regime_multiplier=ONE,
                toxicity_multiplier=ONE,
                imbalance_multiplier=ONE,
                calibration_multiplier=ONE,
                confidence=ONE,
                quality=SlippageQuality.PARTIAL,
                slippage_class=SlippageClass.LOW,
                execution_style=market.execution_style,
                completeness_notes=("zero_quantity",),
            )

        if market.book_integrity in {BookIntegrity.CROSSED, BookIntegrity.UNTRUSTWORTHY, BookIntegrity.STALE}:
            quality = SlippageQuality.INVALID
            confidence = self.policy.invalid_confidence
            notes.append(f"book_integrity={market.book_integrity.value}")

        if compatibility_mode:
            quality = SlippageQuality.DEGRADED if quality != SlippageQuality.INVALID else quality
            confidence = min(confidence, self.policy.degraded_confidence)
            notes.append("legacy_compatibility_projection")

        bid_l1 = self._depth_or_none(market.depth.bid_depth_l1)
        ask_l1 = self._depth_or_none(market.depth.ask_depth_l1)
        bid_n = self._depth_or_none(market.depth.bid_depth_n)
        ask_n = self._depth_or_none(market.depth.ask_depth_n)

        side_depth_l1 = ask_l1 if market.side == OrderSide.BUY else bid_l1
        side_depth_n = ask_n if market.side == OrderSide.BUY else bid_n

        if side_depth_l1 is None:
            quality = SlippageQuality.DEGRADED if quality != SlippageQuality.INVALID else quality
            confidence = min(confidence, self.policy.degraded_confidence)
            notes.append("side_depth_l1_missing_fallback_used")
            side_depth_l1 = self.policy.fallback_depth_units

        if side_depth_n is None:
            quality = SlippageQuality.DEGRADED if quality != SlippageQuality.INVALID else quality
            confidence = min(confidence, self.policy.degraded_confidence)
            notes.append("side_depth_n_missing_fallback_used")
            side_depth_n = side_depth_l1

        side_depth_l1 = max(self.policy.min_depth_floor, side_depth_l1)
        side_depth_n = max(self.policy.min_depth_floor, side_depth_n)

        normalized_size_l1 = market.quantity / side_depth_l1
        normalized_size_n = market.quantity / side_depth_n

        regime_multiplier = self._regime_multiplier(market.regime)
        toxicity_multiplier = self._toxicity_multiplier(market.toxicity_score, market.toxicity_level)
        imbalance_multiplier = self._imbalance_multiplier(side=market.side, imbalance=market.book_imbalance)
        calibration_multiplier = self._calibration_multiplier(market.symbol, market.venue)

        spread_cost_bps = self._spread_cost_bps(market)
        impact_cost_bps = self._impact_cost_bps(
            normalized_size_l1=normalized_size_l1,
            normalized_size_n=normalized_size_n,
            regime_multiplier=regime_multiplier,
            toxicity_multiplier=toxicity_multiplier,
            imbalance_multiplier=imbalance_multiplier,
            calibration_multiplier=calibration_multiplier,
            liquidity_regime=market.liquidity_regime,
        )
        adverse_selection_bps = self._adverse_selection_bps(market)

        total_slippage_bps = spread_cost_bps + impact_cost_bps + adverse_selection_bps
        slippage_amount = market.current_price * (total_slippage_bps / BPS_DIVISOR)

        if market.side == OrderSide.BUY:
            expected_execution_price = market.current_price + slippage_amount
        else:
            expected_execution_price = market.current_price - slippage_amount

        slippage_class = self._classify_slippage(total_slippage_bps)

        estimate = SlippageEstimate(
            estimate_id=generate_request_id(),
            correlation_id=generate_correlation_id(),
            symbol=market.symbol,
            side=market.side,
            quantity=market.quantity,
            current_price=market.current_price,
            venue=market.venue,
            spread_cost_bps=_quantize_bps(spread_cost_bps),
            impact_cost_bps=_quantize_bps(impact_cost_bps),
            adverse_selection_bps=_quantize_bps(adverse_selection_bps),
            total_slippage_bps=_quantize_bps(total_slippage_bps),
            slippage_amount=_quantize_price(slippage_amount),
            expected_execution_price=_quantize_price(expected_execution_price),
            normalized_size_l1=_quantize_bps(normalized_size_l1),
            normalized_size_n=_quantize_bps(normalized_size_n),
            regime_multiplier=_quantize_bps(regime_multiplier),
            toxicity_multiplier=_quantize_bps(toxicity_multiplier),
            imbalance_multiplier=_quantize_bps(imbalance_multiplier),
            calibration_multiplier=_quantize_bps(calibration_multiplier),
            confidence=_quantize_bps(confidence),
            quality=quality,
            slippage_class=slippage_class,
            execution_style=market.execution_style,
            completeness_notes=tuple(notes),
        )

        self._append_journal(estimate)

        logger.info(
            "[SLIPPAGE] symbol=%s venue=%s side=%s qty=%s total_bps=%s px=%s quality=%s",
            estimate.symbol,
            estimate.venue,
            estimate.side.value,
            estimate.quantity,
            estimate.total_slippage_bps,
            estimate.expected_execution_price,
            estimate.quality.value,
        )

        return estimate

    def estimate_max_executable_size(
        self,
        *,
        target_slippage_bps: Decimal,
        market: MarketImpactContext,
        compatibility_mode: bool = False,
    ) -> Decimal:
        target_slippage_bps = _ensure_non_negative(_d(target_slippage_bps, field_name="target_slippage_bps"), "target_slippage_bps")

        side_depth_l1 = self._side_depth_l1(market)
        side_depth_n = self._side_depth_n(market)

        if side_depth_l1 is None:
            side_depth_l1 = self.policy.fallback_depth_units
        if side_depth_n is None:
            side_depth_n = side_depth_l1

        side_depth_l1 = max(self.policy.min_depth_floor, side_depth_l1)
        side_depth_n = max(self.policy.min_depth_floor, side_depth_n)

        spread_cost_bps = self._spread_cost_bps(market)
        adverse_selection_bps = self._adverse_selection_bps(market)
        fixed_cost = spread_cost_bps + adverse_selection_bps

        if target_slippage_bps <= fixed_cost:
            return ZERO

        regime_multiplier = self._regime_multiplier(market.regime)
        toxicity_multiplier = self._toxicity_multiplier(market.toxicity_score, market.toxicity_level)
        imbalance_multiplier = self._imbalance_multiplier(side=market.side, imbalance=market.book_imbalance)
        calibration_multiplier = self._calibration_multiplier(market.symbol, market.venue)
        liquidity_multiplier = self._liquidity_multiplier(market.liquidity_regime)

        scalar = regime_multiplier * toxicity_multiplier * imbalance_multiplier * calibration_multiplier * liquidity_multiplier
        if scalar <= ZERO:
            return ZERO

        # Solve approximately against N-depth normalized term for conservative sizing.
        remaining_bps = target_slippage_bps - fixed_cost - self.policy.base_impact_bps
        if remaining_bps <= ZERO:
            return ZERO

        normalized_size = (remaining_bps / scalar) ** (ONE / self.policy.size_convexity)
        executable_qty = normalized_size * side_depth_n
        return _quantize_price(executable_qty)

    def calibrate_from_realized_fill(
        self,
        *,
        estimate: SlippageEstimate,
        realized_execution_price: Decimal,
    ) -> CalibrationFeedback:
        realized_execution_price = _ensure_positive(_d(realized_execution_price, field_name="realized_execution_price"), "realized_execution_price")

        if estimate.side == OrderSide.BUY:
            realized_slippage_bps = ((realized_execution_price - estimate.current_price) / estimate.current_price) * BPS_DIVISOR
        else:
            realized_slippage_bps = ((estimate.current_price - realized_execution_price) / estimate.current_price) * BPS_DIVISOR

        estimation_error_bps = realized_slippage_bps - estimate.total_slippage_bps

        old_adj = self._calibration_multiplier(estimate.symbol, estimate.venue)
        adjustment_ratio = ONE + (self.policy.calibration_learning_rate * (estimation_error_bps / max(estimate.total_slippage_bps, Decimal("1"))))
        new_adj = old_adj * adjustment_ratio

        if new_adj < self.policy.min_symbol_adjustment:
            new_adj = self.policy.min_symbol_adjustment
        if new_adj > self.policy.max_symbol_adjustment:
            new_adj = self.policy.max_symbol_adjustment

        self._symbol_adjustments[estimate.symbol] = new_adj
        if estimate.venue:
            self._venue_symbol_adjustments[(estimate.venue, estimate.symbol)] = new_adj

        feedback = CalibrationFeedback(
            estimate_id=estimate.estimate_id,
            symbol=estimate.symbol,
            venue=estimate.venue,
            estimated_slippage_bps=estimate.total_slippage_bps,
            realized_slippage_bps=_quantize_bps(realized_slippage_bps),
            estimation_error_bps=_quantize_bps(estimation_error_bps),
            applied_adjustment=_quantize_bps(new_adj),
        )

        logger.info(
            "[SLIPPAGE_CAL] symbol=%s venue=%s estimated_bps=%s realized_bps=%s new_adj=%s",
            feedback.symbol,
            feedback.venue,
            feedback.estimated_slippage_bps,
            feedback.realized_slippage_bps,
            feedback.applied_adjustment,
        )

        return feedback

    def telemetry_snapshot(self) -> SlippageTelemetrySnapshot:
        if not self._journal:
            return SlippageTelemetrySnapshot(
                estimates_count=0,
                avg_total_slippage_bps=ZERO,
                avg_confidence=ZERO,
                degraded_estimate_count=0,
                symbol_adjustments={k: v for k, v in self._symbol_adjustments.items()},
            )

        total_bps = ZERO
        total_conf = ZERO
        degraded = 0

        for j in self._journal:
            total_bps += j.total_slippage_bps

        # confidence isn't in journal; summarize from current journal quality conservatively
        for j in self._journal:
            if j.quality != SlippageQuality.COMPLETE:
                degraded += 1

        avg_bps = total_bps / Decimal(str(len(self._journal)))
        avg_conf = Decimal("1.0") - (Decimal(str(degraded)) / Decimal(str(len(self._journal)))) * Decimal("0.5")

        return SlippageTelemetrySnapshot(
            estimates_count=len(self._journal),
            avg_total_slippage_bps=_quantize_bps(avg_bps),
            avg_confidence=_quantize_bps(avg_conf),
            degraded_estimate_count=degraded,
            symbol_adjustments={k: _quantize_bps(v) for k, v in self._symbol_adjustments.items()},
        )

    def journal(self, limit: Optional[int] = None) -> List[SlippageJournalRecord]:
        if limit is None or limit >= len(self._journal):
            return list(self._journal)
        return self._journal[-limit:]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _depth_or_none(self, value: Optional[Decimal]) -> Optional[Decimal]:
        return None if value is None else _d(value, field_name="depth")

    def _side_depth_l1(self, market: MarketImpactContext) -> Optional[Decimal]:
        if market.side == OrderSide.BUY:
            return market.depth.ask_depth_l1
        return market.depth.bid_depth_l1

    def _side_depth_n(self, market: MarketImpactContext) -> Optional[Decimal]:
        if market.side == OrderSide.BUY:
            return market.depth.ask_depth_n
        return market.depth.bid_depth_n

    def _regime_multiplier(self, regime: RegimeType) -> Decimal:
        regime_name = getattr(regime, "name", str(regime))

        if regime_name in {
            "CRISIS_LIQUIDITY_VOID",
            "CRISIS_VOLATILITY_SPIKE",
        }:
            return self.policy.crisis_regime_multiplier

        if regime_name == "CRISIS_INFRA_FAILURE":
            return Decimal("10.0")

        if regime_name in {
            "TRENDING_LONG_EXHAUSTING",
            "TRENDING_SHORT_EXHAUSTING",
            "REGIME_BREAK_DETECTED",
        }:
            return Decimal("1.5")

        if regime_name == "RANGING_EXPANDING":
            return Decimal("1.3")

        if regime_name == "UNKNOWN":
            return Decimal("2.0")

        return ONE

    def _toxicity_multiplier(self, toxicity_score: Decimal, toxicity_level: ToxicityLevel) -> Decimal:
        toxicity_score = max(ZERO, toxicity_score)
        base = Decimal(str(float((ONE + toxicity_score) ** self.policy.toxicity_exponent)))

        if toxicity_level == ToxicityLevel.EXTREME:
            return base * Decimal("1.5")
        if toxicity_level == ToxicityLevel.TOXIC:
            return base * Decimal("1.2")
        return base

    def _imbalance_multiplier(self, *, side: OrderSide, imbalance: Decimal) -> Decimal:
        imbalance = max(Decimal("-1.0"), min(Decimal("1.0"), imbalance))
        if side == OrderSide.BUY:
            return Decimal("1.0") + max(ZERO, imbalance)
        return Decimal("1.0") + max(ZERO, -imbalance)

    def _liquidity_multiplier(self, regime: LiquidityRegime) -> Decimal:
        if regime == LiquidityRegime.THICK:
            return Decimal("0.8")
        if regime == LiquidityRegime.THIN:
            return Decimal("1.2")
        if regime in {LiquidityRegime.HOLLOW, LiquidityRegime.FRAGMENTED, LiquidityRegime.TOXIC}:
            return Decimal("1.6")
        return ONE

    def _calibration_multiplier(self, symbol: str, venue: Optional[str]) -> Decimal:
        if venue is not None and (venue, symbol) in self._venue_symbol_adjustments:
            return self._venue_symbol_adjustments[(venue, symbol)]
        return self._symbol_adjustments.get(symbol, ONE)

    def _spread_cost_bps(self, market: MarketImpactContext) -> Decimal:
        spread = market.spread_bps

        if market.execution_style == ExecutionStyle.PASSIVE:
            return spread * Decimal("0.05")
        if market.execution_style == ExecutionStyle.PASSIVE_NEAR_TOUCH:
            return spread * Decimal("0.25")
        if market.execution_style == ExecutionStyle.TWAP_SLICE:
            return spread * Decimal("0.60")
        if market.execution_style == ExecutionStyle.MARKETABLE_LIMIT:
            return spread * Decimal("1.00")
        if market.execution_style in {ExecutionStyle.IOC, ExecutionStyle.SWEEP}:
            return spread * Decimal("1.50")

        # Fallback to marketability semantics
        if market.marketability == Marketability.PASSIVE:
            return spread * Decimal("0.10")
        if market.marketability == Marketability.NEAR_TOUCH:
            return spread * Decimal("0.50")
        if market.marketability == Marketability.MARKETABLE:
            return spread * Decimal("1.00")
        if market.marketability in {Marketability.CROSSING, Marketability.SWEEPING}:
            return spread * Decimal("1.50")
        return spread

    def _impact_cost_bps(
        self,
        *,
        normalized_size_l1: Decimal,
        normalized_size_n: Decimal,
        regime_multiplier: Decimal,
        toxicity_multiplier: Decimal,
        imbalance_multiplier: Decimal,
        calibration_multiplier: Decimal,
        liquidity_regime: LiquidityRegime,
    ) -> Decimal:
        liquidity_multiplier = self._liquidity_multiplier(liquidity_regime)

        # Blend L1 and deeper-book normalization for a more stable impact curve
        blended_size = (normalized_size_l1 * Decimal("0.60")) + (normalized_size_n * Decimal("0.40"))
        convex_size_term = blended_size ** self.policy.size_convexity

        return self.policy.base_impact_bps + (
            convex_size_term
            * regime_multiplier
            * toxicity_multiplier
            * imbalance_multiplier
            * liquidity_multiplier
            * calibration_multiplier
        )

    def _adverse_selection_bps(self, market: MarketImpactContext) -> Decimal:
        score = market.toxicity_score

        base = ZERO
        if market.execution_style in {ExecutionStyle.IOC, ExecutionStyle.SWEEP, ExecutionStyle.MARKETABLE_LIMIT}:
            base += score * Decimal("5.0")

        if market.book_integrity in {BookIntegrity.THIN, BookIntegrity.HOLLOW, BookIntegrity.FRAGMENTED}:
            base += Decimal("2.0")
        elif market.book_integrity in {BookIntegrity.CROSSED, BookIntegrity.STALE, BookIntegrity.UNTRUSTWORTHY}:
            base += Decimal("10.0")

        if base > self.policy.adverse_selection_bps_cap:
            base = self.policy.adverse_selection_bps_cap
        return base

    def _classify_slippage(self, total_slippage_bps: Decimal) -> SlippageClass:
        if total_slippage_bps >= Decimal("50"):
            return SlippageClass.EXTREME
        if total_slippage_bps >= Decimal("20"):
            return SlippageClass.HIGH
        if total_slippage_bps >= Decimal("8"):
            return SlippageClass.MODERATE
        return SlippageClass.LOW

    def _append_journal(self, estimate: SlippageEstimate) -> None:
        self._journal_seq += 1
        self._journal.append(
            SlippageJournalRecord(
                sequence=self._journal_seq,
                estimate_id=estimate.estimate_id,
                symbol=estimate.symbol,
                side=estimate.side.value,
                quantity=estimate.quantity,
                venue=estimate.venue,
                total_slippage_bps=estimate.total_slippage_bps,
                confidence=estimate.confidence,
                quality=estimate.quality,
            )
        )
        if len(self._journal) > self.policy.journal_capacity:
            self._journal = self._journal[-self.policy.journal_capacity:]


__all__ = [
    "SlippageQuality",
    "ExecutionStyle",
    "SlippagePolicyConfig",
    "DepthProfile",
    "MarketImpactContext",
    "SlippageEstimate",
    "CalibrationFeedback",
    "SlippageJournalRecord",
    "SlippageTelemetrySnapshot",
    "SlippageModel",
]
