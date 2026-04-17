"""
app/execution/fee_model.py
POVERTY_KILLER — SOVEREIGN FRICTION AUTHORITY (CITADEL-GRADE)

This module is the canonical fee and friction authority for execution-cost
estimation and realized fee decomposition. It supports maker/taker schedules,
tiered volume scaling, symbol surcharges, fee drift inspection, and canonical
typed outputs.

ARCHITECTURAL ROLE
------------------
Owns locally:
- expected fee estimation
- realized fee decomposition
- fee schedule state
- tier/surcharge governance
- fee journaling
- aggregate fee snapshots

Does NOT own:
- execution truth generation
- venue account truth generation
- FX conversion authority
- portfolio attribution authority

DESIGN PRINCIPLES
-----------------
1. Exact Monetary Representation
   All fee math remains Decimal-native.

2. Liquidity-Role Awareness
   Fee estimation can use explicit maker/taker role when known.

3. Bounded Truth
   Unknown or incomplete fee context degrades quality rather than fabricating
   canonical certainty.

4. Preserve-Aware Compatibility
   calculate_expected_fee(...) and decompose_fill_fee(...) are preserved while
   richer canonical APIs are introduced.

5. Risk Mitigation First
   Fee drift and abnormal realized bps are surfaced explicitly.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_DOWN, getcontext
from enum import Enum, unique
from typing import Any, Dict, List, Optional

from app.utils.enums import FillLiquidity, OrderType
from app.utils.ids import generate_correlation_id, generate_request_id

getcontext().prec = 28
logger = logging.getLogger(__name__)


# ============================================================================
# HELPERS
# ============================================================================

ZERO = Decimal("0")
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


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)


def _quantize_bps(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"), rounding=ROUND_DOWN)


# ============================================================================
# ENUMS
# ============================================================================

@unique
class FeeQuality(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    DEGRADED = "DEGRADED"


# ============================================================================
# MODELS
# ============================================================================

@dataclass(frozen=True, slots=True)
class FeePolicyConfig:
    maker_base_bps: Decimal = Decimal("16")
    taker_base_bps: Decimal = Decimal("26")
    abnormal_fee_multiplier: Decimal = Decimal("1.5")
    journal_capacity: int = 50000

    def __post_init__(self) -> None:
        object.__setattr__(self, "maker_base_bps", _ensure_non_negative(_d(self.maker_base_bps, field_name="maker_base_bps"), "maker_base_bps"))
        object.__setattr__(self, "taker_base_bps", _ensure_non_negative(_d(self.taker_base_bps, field_name="taker_base_bps"), "taker_base_bps"))
        object.__setattr__(self, "abnormal_fee_multiplier", _ensure_positive(_d(self.abnormal_fee_multiplier, field_name="abnormal_fee_multiplier"), "abnormal_fee_multiplier"))
        if self.journal_capacity < 100:
            raise ValueError("journal_capacity must be >= 100")


@dataclass(frozen=True, slots=True)
class FeeEstimate:
    estimate_id: int
    correlation_id: int

    symbol: str
    notional_value: Decimal
    liquidity_role: FillLiquidity
    maker_rate_bps: Decimal
    taker_rate_bps: Decimal
    effective_rate_bps: Decimal
    tier_multiplier: Decimal
    surcharge_bps: Decimal
    expected_fee: Decimal

    quality: FeeQuality
    completeness_notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class FeeRealization:
    symbol: str
    gross_notional: Decimal
    net_notional: Decimal
    reported_fee: Decimal
    fee_currency: str

    expected_rate_bps: Decimal
    realized_bps: Decimal
    drift_from_model_bps: Decimal

    liquidity_role: FillLiquidity
    quality: FeeQuality
    completeness_notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class FeeScheduleSnapshot:
    maker_base_bps: Decimal
    taker_base_bps: Decimal
    tier_multiplier: Decimal
    effective_maker_bps: Decimal
    effective_taker_bps: Decimal
    surcharges: Dict[str, Decimal]


@dataclass(frozen=True, slots=True)
class FeeAggregateSnapshot:
    estimate_count: int
    realized_count: int
    total_expected_fees: Decimal
    total_reported_fees: Decimal
    total_drift_bps: Decimal
    quality: FeeQuality


@dataclass(frozen=True, slots=True)
class FeeJournalRecord:
    sequence: int
    event: str
    payload: Dict[str, Any] = field(default_factory=dict)


# ============================================================================
# ENGINE
# ============================================================================

class FeeModel:
    """
    Sovereign friction authority.
    """

    def __init__(
        self,
        maker_base_bps: Decimal = Decimal("16"),
        taker_base_bps: Decimal = Decimal("26"),
    ):
        self.policy = FeePolicyConfig(
            maker_base_bps=maker_base_bps,
            taker_base_bps=taker_base_bps,
        )

        # Preserve legacy attributes
        self.maker_bps = self.policy.maker_base_bps
        self.taker_bps = self.policy.taker_base_bps

        self._tier_multiplier = Decimal("1.0")
        self._surcharges: Dict[str, Decimal] = {}

        self._estimates: List[FeeEstimate] = []
        self._realizations: List[FeeRealization] = []
        self._journal: List[FeeJournalRecord] = []
        self._journal_seq = 0

    # ------------------------------------------------------------------
    # Legacy compatibility API
    # ------------------------------------------------------------------

    def calculate_expected_fee(
        self,
        symbol: str,
        order_type: OrderType,
        notional_value: Decimal
    ) -> Decimal:
        """
        Legacy compatibility fee estimate.

        Uses order_type-based inference for maker/taker role when explicit
        liquidity role is unavailable.
        """
        estimate = self.estimate_fees(
            symbol=symbol,
            notional_value=notional_value,
            order_type=order_type,
            liquidity_role=None,
            compatibility_mode=True,
        )
        return estimate.expected_fee

    def decompose_fill_fee(
        self,
        fill_qty: Decimal,
        fill_price: Decimal,
        reported_fee: Decimal,
        fee_currency: str
    ) -> Dict[str, Any]:
        """
        Legacy compatibility decomposition.

        Because legacy signature lacks explicit symbol and liquidity role,
        the realization is degraded rather than pretending full fee truth.
        """
        realization = self.decompose_fill_fee_detailed(
            symbol="UNKNOWN",
            fill_qty=fill_qty,
            fill_price=fill_price,
            reported_fee=reported_fee,
            fee_currency=fee_currency,
            liquidity_role=FillLiquidity.UNKNOWN,
            order_type=None,
            compatibility_mode=True,
        )
        return {
            "gross_notional": realization.gross_notional,
            "net_notional": realization.net_notional,
            "realized_bps": realization.realized_bps,
            "fee_currency": realization.fee_currency,
            "drift_from_model": realization.drift_from_model_bps,
        }

    def update_volume_tier(self, rolling_30d_volume: Decimal):
        """
        Legacy-compatible tier update path.
        """
        self.update_volume_tier_detailed(rolling_30d_volume=rolling_30d_volume)

    # ------------------------------------------------------------------
    # Canonical API
    # ------------------------------------------------------------------

    def estimate_fees(
        self,
        *,
        symbol: str,
        notional_value: Decimal,
        order_type: Optional[OrderType] = None,
        liquidity_role: Optional[FillLiquidity] = None,
        compatibility_mode: bool = False,
    ) -> FeeEstimate:
        if not symbol:
            raise ValueError("symbol must be non-empty")
        notional_value = _ensure_non_negative(_d(notional_value, field_name="notional_value"), "notional_value")

        notes: List[str] = []
        quality = FeeQuality.COMPLETE

        if liquidity_role is None:
            if order_type is None:
                liquidity_role = FillLiquidity.UNKNOWN
                quality = FeeQuality.DEGRADED
                notes.append("liquidity_role_unknown")
            else:
                liquidity_role = self._infer_liquidity_role_from_order_type(order_type)
                quality = FeeQuality.PARTIAL
                notes.append("liquidity_role_inferred_from_order_type")

        if compatibility_mode:
            quality = FeeQuality.DEGRADED
            notes.append("legacy_compatibility_projection")

        surcharge_bps = self._surcharges.get(symbol, ZERO)
        maker_rate_bps = self.maker_bps * self._tier_multiplier
        taker_rate_bps = self.taker_bps * self._tier_multiplier

        if liquidity_role == FillLiquidity.MAKER:
            effective_rate_bps = maker_rate_bps + surcharge_bps
        elif liquidity_role == FillLiquidity.TAKER:
            effective_rate_bps = taker_rate_bps + surcharge_bps
        else:
            effective_rate_bps = taker_rate_bps + surcharge_bps
            if quality == FeeQuality.COMPLETE:
                quality = FeeQuality.PARTIAL
            notes.append("unknown_role_defaulted_to_taker")

        expected_fee = notional_value * (effective_rate_bps / BPS_DIVISOR)
        expected_fee = _quantize_money(expected_fee)

        estimate = FeeEstimate(
            estimate_id=generate_request_id(),
            correlation_id=generate_correlation_id(),
            symbol=symbol,
            notional_value=notional_value,
            liquidity_role=liquidity_role,
            maker_rate_bps=_quantize_bps(maker_rate_bps),
            taker_rate_bps=_quantize_bps(taker_rate_bps),
            effective_rate_bps=_quantize_bps(effective_rate_bps),
            tier_multiplier=_quantize_bps(self._tier_multiplier),
            surcharge_bps=_quantize_bps(surcharge_bps),
            expected_fee=expected_fee,
            quality=quality,
            completeness_notes=tuple(notes),
        )

        self._estimates.append(estimate)
        self._append_journal(
            event="FEE_ESTIMATED",
            payload={
                "symbol": symbol,
                "liquidity_role": liquidity_role.value,
                "expected_fee": str(expected_fee),
                "effective_rate_bps": str(effective_rate_bps),
                "quality": quality.value,
            },
        )

        return estimate

    def decompose_fill_fee_detailed(
        self,
        *,
        symbol: str,
        fill_qty: Decimal,
        fill_price: Decimal,
        reported_fee: Decimal,
        fee_currency: str,
        liquidity_role: FillLiquidity = FillLiquidity.UNKNOWN,
        order_type: Optional[OrderType] = None,
        compatibility_mode: bool = False,
    ) -> FeeRealization:
        fill_qty = _ensure_non_negative(_d(fill_qty, field_name="fill_qty"), "fill_qty")
        fill_price = _ensure_positive(_d(fill_price, field_name="fill_price"), "fill_price")
        reported_fee = _ensure_non_negative(_d(reported_fee, field_name="reported_fee"), "reported_fee")

        notes: List[str] = []
        quality = FeeQuality.COMPLETE

        gross_notional = fill_qty * fill_price
        if gross_notional <= ZERO:
            raise ValueError("gross_notional must be > 0 for fee decomposition")

        if liquidity_role == FillLiquidity.UNKNOWN:
            if order_type is not None:
                liquidity_role = self._infer_liquidity_role_from_order_type(order_type)
                quality = FeeQuality.PARTIAL
                notes.append("liquidity_role_inferred_from_order_type")
            else:
                quality = FeeQuality.DEGRADED
                notes.append("liquidity_role_unknown")

        expected_estimate = self.estimate_fees(
            symbol=symbol,
            notional_value=gross_notional,
            order_type=order_type,
            liquidity_role=liquidity_role,
            compatibility_mode=compatibility_mode,
        )

        realized_bps = (reported_fee / gross_notional) * BPS_DIVISOR
        drift_bps = realized_bps - expected_estimate.effective_rate_bps

        if realized_bps > (self.taker_bps * self.policy.abnormal_fee_multiplier):
            logger.critical("[FEE_INVARIANT] abnormal_fee_detected symbol=%s realized_bps=%s", symbol, realized_bps)
            quality = FeeQuality.DEGRADED
            notes.append("abnormal_fee_detected")

        if compatibility_mode:
            quality = FeeQuality.DEGRADED
            notes.append("legacy_compatibility_projection")

        realization = FeeRealization(
            symbol=symbol,
            gross_notional=_quantize_money(gross_notional),
            net_notional=_quantize_money(gross_notional - reported_fee),
            reported_fee=_quantize_money(reported_fee),
            fee_currency=fee_currency,
            expected_rate_bps=expected_estimate.effective_rate_bps,
            realized_bps=_quantize_bps(realized_bps),
            drift_from_model_bps=_quantize_bps(drift_bps),
            liquidity_role=liquidity_role,
            quality=quality,
            completeness_notes=tuple(notes),
        )

        self._realizations.append(realization)
        self._append_journal(
            event="FEE_REALIZED",
            payload={
                "symbol": symbol,
                "realized_bps": str(realized_bps),
                "drift_bps": str(drift_bps),
                "quality": quality.value,
            },
        )

        return realization

    def update_volume_tier_detailed(self, *, rolling_30d_volume: Decimal) -> Decimal:
        rolling_30d_volume = _ensure_non_negative(_d(rolling_30d_volume, field_name="rolling_30d_volume"), "rolling_30d_volume")

        if rolling_30d_volume > Decimal("10000000"):
            self._tier_multiplier = Decimal("0.5")
        elif rolling_30d_volume > Decimal("1000000"):
            self._tier_multiplier = Decimal("0.8")
        else:
            self._tier_multiplier = Decimal("1.0")

        self._append_journal(
            event="TIER_UPDATED",
            payload={
                "rolling_30d_volume": str(rolling_30d_volume),
                "tier_multiplier": str(self._tier_multiplier),
            },
        )

        logger.info("[FEE_GOVERNANCE] tier_updated multiplier=%s", self._tier_multiplier)
        return self._tier_multiplier

    def set_symbol_surcharge(self, symbol: str, surcharge_bps: Decimal) -> None:
        if not symbol:
            raise ValueError("symbol must be non-empty")
        surcharge_bps = _d(surcharge_bps, field_name="surcharge_bps")
        self._surcharges[symbol] = surcharge_bps
        self._append_journal(
            event="SURCHARGE_SET",
            payload={"symbol": symbol, "surcharge_bps": str(surcharge_bps)},
        )

    def clear_symbol_surcharge(self, symbol: str) -> None:
        self._surcharges.pop(symbol, None)
        self._append_journal(
            event="SURCHARGE_CLEARED",
            payload={"symbol": symbol},
        )

    def get_schedule_snapshot(self) -> FeeScheduleSnapshot:
        maker_effective = (self.maker_bps * self._tier_multiplier)
        taker_effective = (self.taker_bps * self._tier_multiplier)
        return FeeScheduleSnapshot(
            maker_base_bps=_quantize_bps(self.maker_bps),
            taker_base_bps=_quantize_bps(self.taker_bps),
            tier_multiplier=_quantize_bps(self._tier_multiplier),
            effective_maker_bps=_quantize_bps(maker_effective),
            effective_taker_bps=_quantize_bps(taker_effective),
            surcharges={k: _quantize_bps(v) for k, v in self._surcharges.items()},
        )

    def get_aggregate_snapshot(self) -> FeeAggregateSnapshot:
        total_expected = sum((e.expected_fee for e in self._estimates), start=ZERO)
        total_realized = sum((r.reported_fee for r in self._realizations), start=ZERO)
        total_drift = sum((r.drift_from_model_bps for r in self._realizations), start=ZERO)

        quality = FeeQuality.COMPLETE
        if any(e.quality == FeeQuality.DEGRADED for e in self._estimates) or any(r.quality == FeeQuality.DEGRADED for r in self._realizations):
            quality = FeeQuality.DEGRADED
        elif any(e.quality == FeeQuality.PARTIAL for e in self._estimates) or any(r.quality == FeeQuality.PARTIAL for r in self._realizations):
            quality = FeeQuality.PARTIAL

        return FeeAggregateSnapshot(
            estimate_count=len(self._estimates),
            realized_count=len(self._realizations),
            total_expected_fees=_quantize_money(total_expected),
            total_reported_fees=_quantize_money(total_realized),
            total_drift_bps=_quantize_bps(total_drift),
            quality=quality,
        )

    def journal(self, limit: Optional[int] = None) -> List[FeeJournalRecord]:
        if limit is None or limit >= len(self._journal):
            return list(self._journal)
        return self._journal[-limit:]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _infer_liquidity_role_from_order_type(self, order_type: OrderType) -> FillLiquidity:
        if order_type in {OrderType.POST_ONLY, OrderType.LIMIT_MAKER}:
            return FillLiquidity.MAKER
        return FillLiquidity.TAKER

    def _append_journal(self, *, event: str, payload: Dict[str, Any]) -> None:
        self._journal_seq += 1
        self._journal.append(
            FeeJournalRecord(
                sequence=self._journal_seq,
                event=event,
                payload=payload,
            )
        )
        if len(self._journal) > self.policy.journal_capacity:
            self._journal = self._journal[-self.policy.journal_capacity:]


__all__ = [
    "FeeQuality",
    "FeePolicyConfig",
    "FeeEstimate",
    "FeeRealization",
    "FeeScheduleSnapshot",
    "FeeAggregateSnapshot",
    "FeeJournalRecord",
    "FeeModel",
]
