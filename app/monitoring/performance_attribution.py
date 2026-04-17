"""
app/monitoring/performance_attribution.py
POVERTY_KILLER — SOVEREIGN PERFORMANCE ATTRIBUTION ENGINE (CITADEL-GRADE)

This module is the canonical trade and portfolio attribution authority for
realized performance decomposition. It explains realized PnL through a bounded,
auditable decomposition into:

- gross realized pnl
- beta contribution
- alpha contribution
- execution friction
- net realized pnl
- residual / invariant check

ARCHITECTURAL ROLE
------------------
Owns locally:
- attribution record construction
- alpha/beta/friction decomposition
- aggregate attribution snapshots
- journaled attribution history
- invariant validation

Does NOT own:
- execution ledger truth generation
- benchmark generation
- exposure accounting authority
- reporting authority

DESIGN PRINCIPLES
-----------------
1. Exact Monetary Representation
   All financial fields remain Decimal-native.

2. Methodology Explicitness
   Gross/net and alpha/beta/friction decomposition identities are documented
   and validated.

3. Replay and Audit Friendliness
   Records are immutable, timestamped, and serializable.

4. Bounded Attribution Role
   This module attributes provided realized trade outcomes; it does not invent
   live execution truth.

5. Risk Mitigation First
   Ambiguous inputs degrade confidence rather than silently pretending accuracy.

6. Compatibility Without False Canonicality
   Legacy adapter paths are preserved, but where canonical fields such as
   timestamp/sleeve/strategy are absent, output quality is explicitly degraded
   instead of inventing false deterministic truth.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation, getcontext
from enum import Enum, unique
from typing import Any, Dict, List, Optional

from app.utils.ids import generate_correlation_id, generate_request_id
from app.utils.enums import SleeveType

getcontext().prec = 28
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


def _ensure_positive(value: Decimal, field_name: str) -> Decimal:
    if value <= ZERO:
        raise ValueError(f"{field_name} must be > 0, got {value}")
    return value


def _ensure_non_negative(value: Decimal, field_name: str) -> Decimal:
    if value < ZERO:
        raise ValueError(f"{field_name} must be >= 0, got {value}")
    return value


def _now_ns() -> int:
    return time.time_ns()


# ============================================================================
# ENUMS
# ============================================================================

@unique
class AttributionQuality(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    DEGRADED = "DEGRADED"


@unique
class TimestampSource(str, Enum):
    EXPLICIT_INPUT = "EXPLICIT_INPUT"
    LOCAL_GENERATION_TIME = "LOCAL_GENERATION_TIME"


# ============================================================================
# MODELS
# ============================================================================

@dataclass(frozen=True, slots=True)
class AttributionPolicyConfig:
    """
    Canonical attribution policy.

    Methodology identity:
        gross_realized_pnl = alpha_contribution + beta_contribution
        net_realized_pnl   = gross_realized_pnl - friction_cost
        residual_check     = gross_realized_pnl - (alpha + beta)

    Where:
        beta_contribution = entry_notional * market_move_pct * beta_coefficient * signed_quantity
        alpha_contribution = gross_realized_pnl - beta_contribution
    """
    default_beta_coefficient: Decimal = Decimal("1.0")
    residual_tolerance: Decimal = Decimal("0.0001")
    journal_capacity: int = 100000

    def __post_init__(self) -> None:
        object.__setattr__(self, "default_beta_coefficient", _d(self.default_beta_coefficient, field_name="default_beta_coefficient"))
        object.__setattr__(self, "residual_tolerance", _ensure_non_negative(_d(self.residual_tolerance, field_name="residual_tolerance"), "residual_tolerance"))
        if self.journal_capacity < 100:
            raise ValueError("journal_capacity must be >= 100")


@dataclass(frozen=True, slots=True)
class AttributionRecord:
    attribution_id: int
    correlation_id: int
    timestamp_ns: int
    timestamp_source: TimestampSource

    symbol: str
    sleeve: Optional[SleeveType]
    strategy_tag: Optional[str]

    quantity: Decimal
    signed_quantity: Decimal
    entry_price: Decimal
    exit_price: Decimal

    market_move_pct: Decimal
    beta_coefficient: Decimal

    gross_realized_pnl: Decimal
    alpha_contribution: Decimal
    beta_contribution: Decimal

    fees: Decimal
    slippage: Decimal
    friction_cost: Decimal
    net_realized_pnl: Decimal

    residual_check: Decimal
    quality: AttributionQuality
    completeness_notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AttributionAggregateSnapshot:
    timestamp_ns: int
    record_count: int

    total_gross_pnl: Decimal
    total_net_pnl: Decimal
    total_alpha: Decimal
    total_beta: Decimal
    total_fees: Decimal
    total_slippage: Decimal
    total_friction: Decimal
    total_residual: Decimal

    by_symbol: Dict[str, Dict[str, Decimal]]
    by_sleeve: Dict[str, Dict[str, Decimal]]
    quality: AttributionQuality


@dataclass(frozen=True, slots=True)
class AttributionJournalRecord:
    sequence: int
    attribution_id: int
    timestamp_ns: int
    timestamp_source: TimestampSource
    symbol: str
    quality: AttributionQuality
    gross_realized_pnl: Decimal
    net_realized_pnl: Decimal


# ============================================================================
# ENGINE
# ============================================================================

class PerformanceAttributor:
    """
    Sovereign attribution authority.

    Legacy:
        attribute_trade(...)
        get_aggregate_stats(...)

    Canonical:
        attribute_trade_detailed(...)
        get_aggregate_snapshot(...)
        journal(...)
    """

    def __init__(self):
        self.policy = AttributionPolicyConfig()
        self._history: List[AttributionRecord] = []
        self._journal: List[AttributionJournalRecord] = []
        self._journal_seq = 0

    # ------------------------------------------------------------------
    # Legacy compatibility API
    # ------------------------------------------------------------------

    def attribute_trade(
        self,
        symbol: str,
        fill_price: Decimal,
        entry_price: Decimal,
        market_move_pct: Decimal,
        fees: Decimal,
        slippage: Decimal,
        quantity: Decimal
    ):
        """
        Legacy compatibility adapter.

        Assumptions:
        - fill_price is exit price
        - quantity may be signed if short attribution is desired
        - fees/slippage are positive cost magnitudes

        Because the legacy signature does not carry canonical attribution
        metadata such as explicit timestamp, sleeve, or strategy tag, the
        generated attribution record is marked as degraded via:
        - timestamp_source=LOCAL_GENERATION_TIME
        - quality/completeness notes
        """
        self.attribute_trade_detailed(
            symbol=symbol,
            exit_price=fill_price,
            entry_price=entry_price,
            market_move_pct=market_move_pct,
            fees=fees,
            slippage=slippage,
            quantity=quantity,
            sleeve=None,
            strategy_tag=None,
            timestamp_ns=_now_ns(),
            timestamp_source=TimestampSource.LOCAL_GENERATION_TIME,
            beta_coefficient=self.policy.default_beta_coefficient,
            compatibility_mode=True,
        )

    def get_aggregate_stats(self) -> Dict[str, Decimal]:
        """
        Legacy-compatible aggregate summary.
        """
        if not self._history:
            return {}

        snapshot = self.get_aggregate_snapshot(timestamp_ns=_now_ns())
        return {
            "total_pnl": snapshot.total_net_pnl,
            "total_alpha": snapshot.total_alpha,
            "total_beta": snapshot.total_beta,
            "total_friction": snapshot.total_friction,
        }

    # ------------------------------------------------------------------
    # Canonical API
    # ------------------------------------------------------------------

    def attribute_trade_detailed(
        self,
        *,
        symbol: str,
        exit_price: Decimal,
        entry_price: Decimal,
        market_move_pct: Decimal,
        fees: Decimal,
        slippage: Decimal,
        quantity: Decimal,
        sleeve: Optional[SleeveType],
        strategy_tag: Optional[str],
        timestamp_ns: int,
        timestamp_source: TimestampSource = TimestampSource.EXPLICIT_INPUT,
        beta_coefficient: Optional[Decimal] = None,
        compatibility_mode: bool = False,
    ) -> AttributionRecord:
        """
        Canonical attribution path.

        Quantity may be signed:
        - positive quantity => long
        - negative quantity => short

        Decomposition:
            gross_realized_pnl = (exit_price - entry_price) * signed_quantity
            beta_contribution  = entry_price * market_move_pct * beta * signed_quantity
            alpha_contribution = gross_realized_pnl - beta_contribution
            friction_cost      = fees + slippage
            net_realized_pnl   = gross_realized_pnl - friction_cost
            residual_check     = gross_realized_pnl - (alpha + beta)
        """
        if not symbol:
            raise ValueError("symbol must be non-empty")
        if timestamp_ns <= 0:
            raise ValueError("timestamp_ns must be positive")

        entry_price = _ensure_positive(_d(entry_price, field_name="entry_price"), "entry_price")
        exit_price = _ensure_positive(_d(exit_price, field_name="exit_price"), "exit_price")
        market_move_pct = _d(market_move_pct, field_name="market_move_pct")
        fees = _ensure_non_negative(_d(fees, field_name="fees"), "fees")
        slippage = _ensure_non_negative(_d(slippage, field_name="slippage"), "slippage")
        quantity = _d(quantity, field_name="quantity")

        if quantity == ZERO:
            raise ValueError("quantity cannot be zero")

        beta = self.policy.default_beta_coefficient if beta_coefficient is None else _d(beta_coefficient, field_name="beta_coefficient")

        signed_quantity = quantity
        abs_quantity = abs(quantity)

        gross_realized_pnl = (exit_price - entry_price) * signed_quantity
        beta_contribution = (entry_price * market_move_pct * beta) * signed_quantity
        alpha_contribution = gross_realized_pnl - beta_contribution
        friction_cost = fees + slippage
        net_realized_pnl = gross_realized_pnl - friction_cost
        residual_check = gross_realized_pnl - (alpha_contribution + beta_contribution)

        notes: List[str] = []
        quality = AttributionQuality.COMPLETE

        if beta_coefficient is None:
            quality = AttributionQuality.PARTIAL
            notes.append("default_beta_coefficient_applied")

        if timestamp_source != TimestampSource.EXPLICIT_INPUT:
            quality = AttributionQuality.DEGRADED
            notes.append(f"timestamp_source={timestamp_source.value}")

        if compatibility_mode:
            quality = AttributionQuality.DEGRADED
            notes.append("legacy_compatibility_projection")
            if sleeve is None:
                notes.append("sleeve_unknown")
            if strategy_tag is None:
                notes.append("strategy_tag_unknown")

        if abs(residual_check) > self.policy.residual_tolerance:
            quality = AttributionQuality.DEGRADED
            notes.append("residual_exceeds_tolerance")

        record = AttributionRecord(
            attribution_id=generate_request_id(),
            correlation_id=generate_correlation_id(),
            timestamp_ns=timestamp_ns,
            timestamp_source=timestamp_source,
            symbol=symbol,
            sleeve=sleeve,
            strategy_tag=strategy_tag,
            quantity=abs_quantity,
            signed_quantity=signed_quantity,
            entry_price=entry_price,
            exit_price=exit_price,
            market_move_pct=market_move_pct,
            beta_coefficient=beta,
            gross_realized_pnl=gross_realized_pnl,
            alpha_contribution=alpha_contribution,
            beta_contribution=beta_contribution,
            fees=fees,
            slippage=slippage,
            friction_cost=friction_cost,
            net_realized_pnl=net_realized_pnl,
            residual_check=residual_check,
            quality=quality,
            completeness_notes=tuple(notes),
        )

        self._history.append(record)
        self._append_journal(record)

        logger.info(
            "[ATTRIBUTION] symbol=%s gross=%s alpha=%s beta=%s friction=%s net=%s quality=%s",
            record.symbol,
            record.gross_realized_pnl,
            record.alpha_contribution,
            record.beta_contribution,
            record.friction_cost,
            record.net_realized_pnl,
            record.quality.value,
        )

        return record

    def get_aggregate_snapshot(self, *, timestamp_ns: int) -> AttributionAggregateSnapshot:
        if timestamp_ns <= 0:
            raise ValueError("timestamp_ns must be positive")

        if not self._history:
            return AttributionAggregateSnapshot(
                timestamp_ns=timestamp_ns,
                record_count=0,
                total_gross_pnl=ZERO,
                total_net_pnl=ZERO,
                total_alpha=ZERO,
                total_beta=ZERO,
                total_fees=ZERO,
                total_slippage=ZERO,
                total_friction=ZERO,
                total_residual=ZERO,
                by_symbol={},
                by_sleeve={},
                quality=AttributionQuality.PARTIAL,
            )

        by_symbol: Dict[str, Dict[str, Decimal]] = {}
        by_sleeve: Dict[str, Dict[str, Decimal]] = {}

        total_gross = ZERO
        total_net = ZERO
        total_alpha = ZERO
        total_beta = ZERO
        total_fees = ZERO
        total_slippage = ZERO
        total_friction = ZERO
        total_residual = ZERO
        overall_quality = AttributionQuality.COMPLETE

        for r in self._history:
            total_gross += r.gross_realized_pnl
            total_net += r.net_realized_pnl
            total_alpha += r.alpha_contribution
            total_beta += r.beta_contribution
            total_fees += r.fees
            total_slippage += r.slippage
            total_friction += r.friction_cost
            total_residual += r.residual_check

            if r.quality == AttributionQuality.DEGRADED:
                overall_quality = AttributionQuality.DEGRADED
            elif r.quality == AttributionQuality.PARTIAL and overall_quality == AttributionQuality.COMPLETE:
                overall_quality = AttributionQuality.PARTIAL

            sym_bucket = by_symbol.setdefault(
                r.symbol,
                {
                    "gross_pnl": ZERO,
                    "net_pnl": ZERO,
                    "alpha": ZERO,
                    "beta": ZERO,
                    "friction": ZERO,
                },
            )
            sym_bucket["gross_pnl"] += r.gross_realized_pnl
            sym_bucket["net_pnl"] += r.net_realized_pnl
            sym_bucket["alpha"] += r.alpha_contribution
            sym_bucket["beta"] += r.beta_contribution
            sym_bucket["friction"] += r.friction_cost

            sleeve_key = r.sleeve.value if r.sleeve is not None else "UNASSIGNED"
            sleeve_bucket = by_sleeve.setdefault(
                sleeve_key,
                {
                    "gross_pnl": ZERO,
                    "net_pnl": ZERO,
                    "alpha": ZERO,
                    "beta": ZERO,
                    "friction": ZERO,
                },
            )
            sleeve_bucket["gross_pnl"] += r.gross_realized_pnl
            sleeve_bucket["net_pnl"] += r.net_realized_pnl
            sleeve_bucket["alpha"] += r.alpha_contribution
            sleeve_bucket["beta"] += r.beta_contribution
            sleeve_bucket["friction"] += r.friction_cost

        return AttributionAggregateSnapshot(
            timestamp_ns=timestamp_ns,
            record_count=len(self._history),
            total_gross_pnl=total_gross,
            total_net_pnl=total_net,
            total_alpha=total_alpha,
            total_beta=total_beta,
            total_fees=total_fees,
            total_slippage=total_slippage,
            total_friction=total_friction,
            total_residual=total_residual,
            by_symbol=by_symbol,
            by_sleeve=by_sleeve,
            quality=overall_quality,
        )

    def journal(self, limit: Optional[int] = None) -> List[AttributionJournalRecord]:
        if limit is None or limit >= len(self._journal):
            return list(self._journal)
        return self._journal[-limit:]

    def reset(self) -> None:
        """
        Governance reset for attribution history.
        Intended for explicit archival or session boundary handling.
        """
        logger.warning("[ATTRIBUTION_RESET] clearing attribution history and journal")
        self._history.clear()
        self._journal.clear()
        self._journal_seq = 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _append_journal(self, record: AttributionRecord) -> None:
        self._journal_seq += 1
        self._journal.append(
            AttributionJournalRecord(
                sequence=self._journal_seq,
                attribution_id=record.attribution_id,
                timestamp_ns=record.timestamp_ns,
                timestamp_source=record.timestamp_source,
                symbol=record.symbol,
                quality=record.quality,
                gross_realized_pnl=record.gross_realized_pnl,
                net_realized_pnl=record.net_realized_pnl,
            )
        )
        if len(self._journal) > self.policy.journal_capacity:
            self._journal = self._journal[-self.policy.journal_capacity:]


__all__ = [
    "AttributionQuality",
    "TimestampSource",
    "AttributionPolicyConfig",
    "AttributionRecord",
    "AttributionAggregateSnapshot",
    "AttributionJournalRecord",
    "PerformanceAttributor",
]
