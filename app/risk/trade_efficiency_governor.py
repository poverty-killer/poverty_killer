"""
app/risk/trade_efficiency_governor.py
POVERTY_KILLER — TRADE EFFICIENCY GOVERNOR (KERNEL)

ARCHITECTURAL ROLE
------------------
- Canonical authority for rolling sleeve/system efficiency governance.
- Kernel-level state machine ONLY.
- Not the full telemetry/journaling/integration surface. Upstream integration
  is required to bind this to live execution paths.
- Bounded local computation. Uses O(1) running sums to prevent O(N) iteration in hot path.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum, unique
from typing import Any, Dict, List, Mapping, Optional

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS & PRIMITIVES
# ============================================================================

ZERO = Decimal("0")
EPSILON = Decimal("0.00000001")

@unique
class SleeveEfficiencyState(str, Enum):
    NORMAL = "NORMAL"
    THROTTLED = "THROTTLED"
    DEHYDRATED = "DEHYDRATED"
    QUARANTINED = "QUARANTINED"
    RECOVERY_OBSERVATION = "RECOVERY_OBSERVATION"

@unique
class LeadershipStatus(str, Enum):
    NEUTRAL_INSUFFICIENT_SAMPLE = "NEUTRAL_INSUFFICIENT_SAMPLE"
    NEUTRAL_NO_PEER_SAMPLE = "NEUTRAL_NO_PEER_SAMPLE"
    ACTIVE = "ACTIVE"

@unique
class KellyOverlayStatus(str, Enum):
    DORMANT_INSUFFICIENT_REALIZED_SAMPLE = "DORMANT_INSUFFICIENT_REALIZED_SAMPLE"
    ACTIVE_RISK_OF_RUIN_CONFIRMED = "ACTIVE_RISK_OF_RUIN_CONFIRMED"
    ACTIVE_RISK_OF_RUIN_BLOCKED = "ACTIVE_RISK_OF_RUIN_BLOCKED"

class EfficiencyPolicyConfig:
    __slots__ = (
        'short_window', 'medium_window', 'long_window', 'min_recovery_samples',
        'ceiling_normal', 'ceiling_throttled', 'ceiling_dehydrated',
        'ceiling_quarantined', 'ceiling_recovery',
        'deg_ncr_throttle', 'deg_fbr_throttle', 'deg_fpbr_throttle',
        'deg_ncr_dehydrated', 'deg_fbr_dehydrated', 'deg_fpbr_dehydrated',
        'deg_ncr_quarantined', 'deg_fbr_quarantined', 'deg_fpbr_quarantined',
        'rec_ncr_med', 'rec_fbr_med', 'rec_fpbr_med',
        'rec_ncr_full', 'rec_fbr_full', 'rec_fpbr_full',
        'leadership_min_samples', 'leadership_min_active_sleeves',
        'leadership_max_boost', 'leadership_max_cut',
        'kelly_min_samples', 'kelly_dormant_cap', 'kelly_active_cap',
        'risk_of_ruin_max'
    )

    def __init__(self):
        self.short_window: int = 25
        self.medium_window: int = 75
        self.long_window: int = 200
        self.min_recovery_samples: int = 15

        self.ceiling_normal: Decimal = Decimal("1.00")
        self.ceiling_throttled: Decimal = Decimal("0.60")
        self.ceiling_dehydrated: Decimal = Decimal("0.25")
        self.ceiling_quarantined: Decimal = Decimal("0.00")
        self.ceiling_recovery: Decimal = Decimal("0.35")

        self.deg_ncr_throttle = Decimal("0.35")
        self.deg_fbr_throttle = Decimal("0.65")
        self.deg_fpbr_throttle = Decimal("0.55")

        self.deg_ncr_dehydrated = Decimal("0.20")
        self.deg_fbr_dehydrated = Decimal("0.80")
        self.deg_fpbr_dehydrated = Decimal("0.62")

        self.deg_ncr_quarantined = Decimal("0.05")
        self.deg_fbr_quarantined = Decimal("0.95")
        self.deg_fpbr_quarantined = Decimal("0.68")

        self.rec_ncr_med = Decimal("0.45")
        self.rec_fbr_med = Decimal("0.55")
        self.rec_fpbr_med = Decimal("0.50")

        self.rec_ncr_full = Decimal("0.60")
        self.rec_fbr_full = Decimal("0.45")
        self.rec_fpbr_full = Decimal("0.45")

        self.leadership_min_samples: int = 50
        self.leadership_min_active_sleeves: int = 2
        self.leadership_max_boost: Decimal = Decimal("0.15")
        self.leadership_max_cut: Decimal = Decimal("0.15")

        self.kelly_min_samples: int = 50
        self.kelly_dormant_cap: Decimal = Decimal("0.25")
        self.kelly_active_cap: Decimal = Decimal("0.50")
        self.risk_of_ruin_max: Decimal = Decimal("0.01")

@dataclass(frozen=True, slots=True)
class EfficiencyTransition:
    sleeve_id: str
    old_state: SleeveEfficiencyState
    new_state: SleeveEfficiencyState
    reason_code: str
    timestamp_ns: int

@dataclass(frozen=True, slots=True)
class LeadershipSnapshot:
    sleeve_id: str
    regime: str
    status: LeadershipStatus
    multiplier: Decimal
    sample_count: int
    required_samples: int
    eligible_sleeves: int
    sleeve_edge: Decimal
    leader_sleeve_id: Optional[str]
    reason_code: str

@dataclass(frozen=True, slots=True)
class KellyOverlay:
    sleeve_id: str
    regime: str
    status: KellyOverlayStatus
    effective_kelly_cap: Decimal
    sample_count: int
    required_samples: int
    risk_of_ruin_estimate: Optional[Decimal]
    reason_code: str

# ============================================================================
# O(1) RING BUFFER KERNEL
# ============================================================================

class O1RollingMetrics:
    """
    Circular buffer maintaining running sums to prevent O(N) iteration in hot path.
    Bounded list mutations only.
    """
    __slots__ = (
        'capacity', 'count', 'idx',
        'arr_gross', 'arr_net', 'arr_friction', 'arr_fp', 'arr_cap',
        'sum_gross', 'sum_net', 'sum_friction', 'sum_fp', 'sum_cap'
    )

    def __init__(self, capacity: int):
        self.capacity = capacity
        self.count = 0
        self.idx = 0

        self.arr_gross: List[Decimal] = [ZERO] * capacity
        self.arr_net: List[Decimal] = [ZERO] * capacity
        self.arr_friction: List[Decimal] = [ZERO] * capacity
        self.arr_fp: List[int] = [0] * capacity
        self.arr_cap: List[Decimal] = [ZERO] * capacity

        self.sum_gross = ZERO
        self.sum_net = ZERO
        self.sum_friction = ZERO
        self.sum_fp = 0
        self.sum_cap = ZERO

    def insert(self, gross: Decimal, net: Decimal, friction: Decimal, is_fp: int, cap: Decimal) -> None:
        i = self.idx

        self.sum_gross -= self.arr_gross[i]
        self.sum_net -= self.arr_net[i]
        self.sum_friction -= self.arr_friction[i]
        self.sum_fp -= self.arr_fp[i]
        self.sum_cap -= self.arr_cap[i]

        self.arr_gross[i] = gross
        self.arr_net[i] = net
        self.arr_friction[i] = friction
        self.arr_fp[i] = is_fp
        self.arr_cap[i] = cap

        self.sum_gross += gross
        self.sum_net += net
        self.sum_friction += friction
        self.sum_fp += is_fp
        self.sum_cap += cap

        self.idx = (i + 1) % self.capacity
        if self.count < self.capacity:
            self.count += 1

    def calculate_ncr(self) -> Decimal:
        return self.sum_net / max(self.sum_gross, EPSILON)

    def calculate_fbr(self) -> Decimal:
        return self.sum_friction / max(abs(self.sum_gross), EPSILON)

    def calculate_fpbr(self) -> Decimal:
        return Decimal(self.sum_fp) / Decimal(max(self.count, 1))

    def calculate_nppt(self) -> Decimal:
        return self.sum_net / Decimal(max(self.count, 1))

    def calculate_cer(self) -> Decimal:
        return self.sum_net / max(self.sum_cap, EPSILON)


class SleeveStateMatrix:
    __slots__ = ('short_window', 'med_window', 'long_window', 'current_state', 'samples_since_transition')

    def __init__(self, p: EfficiencyPolicyConfig):
        self.short_window = O1RollingMetrics(p.short_window)
        self.med_window = O1RollingMetrics(p.medium_window)
        self.long_window = O1RollingMetrics(p.long_window)
        self.current_state = SleeveEfficiencyState.NORMAL
        self.samples_since_transition = 0

# ============================================================================
# GOVERNOR ENGINE
# ============================================================================

class TradeEfficiencyGovernor:
    """
    Rolling State Machine Kernel for Trade Efficiency.
    """

    __slots__ = ('policy', '_matrices', '_regime_metrics')

    def __init__(self, policy: Optional[EfficiencyPolicyConfig] = None):
        self.policy = policy or EfficiencyPolicyConfig()
        self._matrices: Dict[str, SleeveStateMatrix] = {}
        self._regime_metrics: Dict[str, Dict[str, O1RollingMetrics]] = {}

    @staticmethod
    def _normalize_regime(regime: Optional[Any]) -> str:
        if regime is None:
            return "UNKNOWN"
        value = getattr(regime, "value", regime)
        text = str(value).strip()
        return text.upper() if text else "UNKNOWN"

    @staticmethod
    def _to_decimal(value: Any, default: Decimal = ZERO) -> Decimal:
        if value is None:
            return default
        try:
            return Decimal(str(value))
        except Exception:
            return default

    @staticmethod
    def _mapping_get_path(source: Mapping[str, Any], *path: str) -> Any:
        node: Any = source
        for key in path:
            if not isinstance(node, Mapping):
                return None
            node = node.get(key)
        return node

    def _regime_window(self, regime: str, sleeve_id: str) -> O1RollingMetrics:
        sleeve_windows = self._regime_metrics.setdefault(regime, {})
        window = sleeve_windows.get(sleeve_id)
        if window is None:
            window = O1RollingMetrics(self.policy.long_window)
            sleeve_windows[sleeve_id] = window
        return window

    def _state_ceiling(self, state: SleeveEfficiencyState) -> Decimal:
        if state == SleeveEfficiencyState.NORMAL:
            return self.policy.ceiling_normal
        if state == SleeveEfficiencyState.THROTTLED:
            return self.policy.ceiling_throttled
        if state == SleeveEfficiencyState.DEHYDRATED:
            return self.policy.ceiling_dehydrated
        if state == SleeveEfficiencyState.QUARANTINED:
            return self.policy.ceiling_quarantined
        return self.policy.ceiling_recovery

    def get_sleeve_state(self, sleeve_id: str) -> SleeveEfficiencyState:
        matrix = self._matrices.get(sleeve_id)
        return matrix.current_state if matrix else SleeveEfficiencyState.NORMAL

    def get_leadership_snapshot(self, sleeve_id: str, regime: Optional[Any] = None) -> LeadershipSnapshot:
        regime_key = self._normalize_regime(regime)
        regime_map = self._regime_metrics.get(regime_key, {})
        sleeve_window = regime_map.get(sleeve_id)
        sample_count = sleeve_window.count if sleeve_window else 0
        required = self.policy.leadership_min_samples

        if sample_count < required:
            return LeadershipSnapshot(
                sleeve_id=sleeve_id,
                regime=regime_key,
                status=LeadershipStatus.NEUTRAL_INSUFFICIENT_SAMPLE,
                multiplier=Decimal("1.00"),
                sample_count=sample_count,
                required_samples=required,
                eligible_sleeves=0,
                sleeve_edge=ZERO,
                leader_sleeve_id=None,
                reason_code="LEADERSHIP_NEUTRAL_INSUFFICIENT_SAMPLE",
            )

        eligible = {
            peer_sleeve: metrics
            for peer_sleeve, metrics in regime_map.items()
            if metrics.count >= required
        }
        if len(eligible) < self.policy.leadership_min_active_sleeves:
            return LeadershipSnapshot(
                sleeve_id=sleeve_id,
                regime=regime_key,
                status=LeadershipStatus.NEUTRAL_NO_PEER_SAMPLE,
                multiplier=Decimal("1.00"),
                sample_count=sample_count,
                required_samples=required,
                eligible_sleeves=len(eligible),
                sleeve_edge=sleeve_window.calculate_cer(),
                leader_sleeve_id=None,
                reason_code="LEADERSHIP_NEUTRAL_NO_PEER_SAMPLE",
            )

        edges = {peer_sleeve: metrics.calculate_cer() for peer_sleeve, metrics in eligible.items()}
        sleeve_edge = edges.get(sleeve_id, ZERO)
        leader_sleeve_id = max(edges, key=edges.get)
        min_edge = min(edges.values())
        max_edge = max(edges.values())
        spread = max_edge - min_edge

        if abs(spread) <= EPSILON:
            multiplier = Decimal("1.00")
        else:
            rank = (sleeve_edge - min_edge) / spread
            centered = (rank * Decimal("2")) - Decimal("1")
            if centered >= ZERO:
                multiplier = Decimal("1.00") + (self.policy.leadership_max_boost * centered)
            else:
                multiplier = Decimal("1.00") + (self.policy.leadership_max_cut * centered)

        multiplier = max(Decimal("0.00"), multiplier).quantize(Decimal("0.0001"))
        return LeadershipSnapshot(
            sleeve_id=sleeve_id,
            regime=regime_key,
            status=LeadershipStatus.ACTIVE,
            multiplier=multiplier,
            sample_count=sample_count,
            required_samples=required,
            eligible_sleeves=len(eligible),
            sleeve_edge=sleeve_edge,
            leader_sleeve_id=leader_sleeve_id,
            reason_code="LEADERSHIP_ACTIVE_REALIZED_EDGE_RANK",
        )

    def get_kelly_overlay(self, sleeve_id: str, regime: Optional[Any] = None) -> KellyOverlay:
        regime_key = self._normalize_regime(regime)
        metrics = self._regime_metrics.get(regime_key, {}).get(sleeve_id)
        sample_count = metrics.count if metrics else 0
        required = self.policy.kelly_min_samples

        if sample_count < required:
            return KellyOverlay(
                sleeve_id=sleeve_id,
                regime=regime_key,
                status=KellyOverlayStatus.DORMANT_INSUFFICIENT_REALIZED_SAMPLE,
                effective_kelly_cap=self.policy.kelly_dormant_cap,
                sample_count=sample_count,
                required_samples=required,
                risk_of_ruin_estimate=None,
                reason_code="KELLY_DORMANT_INSUFFICIENT_REALIZED_SAMPLE",
            )

        false_positive_rate = metrics.calculate_fpbr()
        win_rate = Decimal("1.00") - false_positive_rate
        if false_positive_rate <= ZERO:
            risk_of_ruin = ZERO
        elif win_rate <= ZERO or false_positive_rate >= win_rate:
            risk_of_ruin = Decimal("1.00")
        else:
            risk_of_ruin = (false_positive_rate / max(win_rate, EPSILON)) ** sample_count
        risk_of_ruin = min(Decimal("1.00"), max(ZERO, risk_of_ruin)).quantize(Decimal("0.000001"))

        if risk_of_ruin < self.policy.risk_of_ruin_max:
            return KellyOverlay(
                sleeve_id=sleeve_id,
                regime=regime_key,
                status=KellyOverlayStatus.ACTIVE_RISK_OF_RUIN_CONFIRMED,
                effective_kelly_cap=self.policy.kelly_active_cap,
                sample_count=sample_count,
                required_samples=required,
                risk_of_ruin_estimate=risk_of_ruin,
                reason_code="KELLY_ACTIVE_RISK_OF_RUIN_LT_1PCT",
            )

        return KellyOverlay(
            sleeve_id=sleeve_id,
            regime=regime_key,
            status=KellyOverlayStatus.ACTIVE_RISK_OF_RUIN_BLOCKED,
            effective_kelly_cap=self.policy.kelly_dormant_cap,
            sample_count=sample_count,
            required_samples=required,
            risk_of_ruin_estimate=risk_of_ruin,
            reason_code="KELLY_FAIL_CLOSED_RISK_OF_RUIN_GE_1PCT",
        )

    def get_sizing_multiplier(self, sleeve_id: str, regime: Optional[Any] = None) -> Decimal:
        state_multiplier = self._state_ceiling(self.get_sleeve_state(sleeve_id))
        if state_multiplier <= ZERO:
            return state_multiplier
        leadership = self.get_leadership_snapshot(sleeve_id, regime).multiplier
        return (state_multiplier * leadership).quantize(Decimal("0.0001"))

    def force_quarantine(self, sleeve_id: str, timestamp_ns: int, reason: str) -> EfficiencyTransition:
        """Explicit hard-quarantine override seam for external intervention."""
        matrix = self._matrices.get(sleeve_id)
        if not matrix:
            matrix = SleeveStateMatrix(self.policy)
            self._matrices[sleeve_id] = matrix

        old_state = matrix.current_state
        matrix.current_state = SleeveEfficiencyState.QUARANTINED
        matrix.samples_since_transition = 0

        logger.critical(f"HARD QUARANTINE OVERRIDE: Sleeve {sleeve_id} | Reason: {reason}")
        return EfficiencyTransition(sleeve_id, old_state, SleeveEfficiencyState.QUARANTINED, f"HARD_OVERRIDE_{reason}", timestamp_ns)

    def register_trade_result(
        self, sleeve_id: str, timestamp_ns: int, gross_pnl: Decimal, net_pnl: Decimal,
        fee_cost: Decimal, spread_tax: Decimal, slippage_drag: Decimal,
        carry_drag: Decimal, capital_committed: Decimal, regime: Optional[Any] = None
    ) -> Optional[EfficiencyTransition]:
        """
        Ingests metrics and evaluates hysteresis. Returns an EfficiencyTransition object
        ONLY if the state mutated, otherwise returns None.
        """
        matrix = self._matrices.get(sleeve_id)
        if not matrix:
            matrix = SleeveStateMatrix(self.policy)
            self._matrices[sleeve_id] = matrix

        friction = fee_cost + spread_tax + slippage_drag + carry_drag
        is_fp = 1 if net_pnl < ZERO else 0

        matrix.short_window.insert(gross_pnl, net_pnl, friction, is_fp, capital_committed)
        matrix.med_window.insert(gross_pnl, net_pnl, friction, is_fp, capital_committed)
        matrix.long_window.insert(gross_pnl, net_pnl, friction, is_fp, capital_committed)
        self._regime_window(self._normalize_regime(regime), sleeve_id).insert(
            gross_pnl,
            net_pnl,
            friction,
            is_fp,
            capital_committed,
        )
        matrix.samples_since_transition += 1

        return self._evaluate_state_transitions(sleeve_id, matrix, timestamp_ns)

    def register_confirmed_round_trip_realization(
        self,
        ledger_row: Mapping[str, Any],
        timestamp_ns: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Imports broker-confirmed at-close round-trip truth from a fill ledger row.

        Advisory entry-time realizations and modeled estimates are explicitly rejected.
        """
        metadata = ledger_row.get("metadata")
        if not isinstance(metadata, Mapping):
            return {"status": "SKIPPED", "reason_code": "METADATA_MISSING"}

        realization = metadata.get("net_edge_realization")
        if not isinstance(realization, Mapping):
            return {"status": "SKIPPED", "reason_code": "NET_EDGE_REALIZATION_MISSING"}

        if realization.get("measurement_label") != "AT_CLOSE_ACTUAL_ROUND_TRIP":
            return {"status": "SKIPPED", "reason_code": "NOT_AT_CLOSE_ACTUAL_ROUND_TRIP"}
        if realization.get("true_net_profit_status") != "BROKER_CONFIRMED_AFTER_POSITION_CLOSE":
            return {"status": "SKIPPED", "reason_code": "NOT_BROKER_CONFIRMED_AFTER_POSITION_CLOSE"}

        actual_round_trip = realization.get("at_close_actual_round_trip")
        if not isinstance(actual_round_trip, Mapping):
            return {"status": "SKIPPED", "reason_code": "ACTUAL_ROUND_TRIP_MISSING"}
        if actual_round_trip.get("broker_truth_authority") is not True:
            return {"status": "SKIPPED", "reason_code": "BROKER_TRUTH_AUTHORITY_FALSE"}

        net_profit_raw = actual_round_trip.get("actual_net_profit")
        if net_profit_raw is None:
            return {"status": "SKIPPED", "reason_code": "ACTUAL_NET_PROFIT_MISSING"}

        sleeve_id = (
            self._mapping_get_path(metadata, "net_edge_context", "sleeve_id")
            or self._mapping_get_path(metadata, "net_edge_evaluation", "sleeve_id")
            or self._mapping_get_path(metadata, "order_metadata_capture", "metadata", "sleeve_id")
            or metadata.get("sleeve_id")
            or metadata.get("strategy")
            or ledger_row.get("sleeve_id")
            or ledger_row.get("strategy")
        )
        if not sleeve_id:
            return {"status": "SKIPPED", "reason_code": "SLEEVE_ID_MISSING"}

        regime = (
            self._mapping_get_path(metadata, "net_edge_context", "regime")
            or self._mapping_get_path(metadata, "net_edge_evaluation", "regime")
            or self._mapping_get_path(metadata, "order_metadata_capture", "metadata", "regime")
            or metadata.get("regime")
            or "UNKNOWN"
        )

        net_pnl = self._to_decimal(net_profit_raw)
        gross_pnl = self._to_decimal(actual_round_trip.get("gross_pnl"), net_pnl)
        entry_fee = self._to_decimal(actual_round_trip.get("entry_fee"))
        close_fee = self._to_decimal(actual_round_trip.get("close_fee"))
        fee_cost = entry_fee + close_fee
        spread_tax = self._to_decimal(actual_round_trip.get("spread_tax"))
        slippage_drag = self._to_decimal(actual_round_trip.get("slippage_drag"))
        carry_drag = self._to_decimal(actual_round_trip.get("carry_drag"))
        matched_quantity = abs(self._to_decimal(actual_round_trip.get("matched_quantity")))
        entry_price = self._to_decimal(actual_round_trip.get("entry_price"))
        capital_committed = abs(entry_price * matched_quantity)
        if capital_committed <= ZERO:
            capital_committed = abs(self._to_decimal(ledger_row.get("notional")))
        if capital_committed <= ZERO:
            return {"status": "SKIPPED", "reason_code": "CAPITAL_COMMITTED_MISSING"}

        self.register_trade_result(
            sleeve_id=str(sleeve_id),
            timestamp_ns=int(timestamp_ns or ledger_row.get("fill_ts_ns") or 0),
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
            fee_cost=fee_cost,
            spread_tax=spread_tax,
            slippage_drag=slippage_drag,
            carry_drag=carry_drag,
            capital_committed=capital_committed,
            regime=regime,
        )
        return {
            "status": "IMPORTED",
            "reason_code": "BROKER_CONFIRMED_AT_CLOSE_ROUND_TRIP_IMPORTED",
            "sleeve_id": str(sleeve_id),
            "regime": self._normalize_regime(regime),
        }

    def _evaluate_state_transitions(self, sleeve_id: str, matrix: SleeveStateMatrix, timestamp_ns: int) -> Optional[EfficiencyTransition]:
        """
        Bounded, sequential FSM evaluation.
        Evaluates degradation first. If no degradation occurs, evaluates recovery.
        """
        med = matrix.med_window
        if med.count < (self.policy.medium_window >> 1):
            return None

        old_state = matrix.current_state
        p = self.policy

        m_ncr = med.calculate_ncr()
        m_fbr = med.calculate_fbr()
        m_fpbr = med.calculate_fpbr()
        m_nppt = med.calculate_nppt()

        new_state = old_state
        reason = ""

        # --- 1. DEGRADATION EVALUATION ---
        if old_state in {SleeveEfficiencyState.NORMAL, SleeveEfficiencyState.THROTTLED, SleeveEfficiencyState.DEHYDRATED}:
            t_count = sum([
                1 if m_ncr < p.deg_ncr_throttle else 0,
                1 if m_fbr > p.deg_fbr_throttle else 0,
                1 if m_fpbr > p.deg_fpbr_throttle else 0,
                1 if m_nppt <= ZERO else 0,
                1 if med.calculate_cer() < ZERO else 0
            ])

            d_count = sum([
                1 if m_ncr < p.deg_ncr_dehydrated else 0,
                1 if m_fbr > p.deg_fbr_dehydrated else 0,
                1 if m_fpbr > p.deg_fpbr_dehydrated else 0,
                1 if m_nppt < ZERO else 0
            ])

            long_w = matrix.long_window
            q_count = sum([
                1 if long_w.calculate_ncr() < p.deg_ncr_quarantined else 0,
                1 if long_w.calculate_fbr() > p.deg_fbr_quarantined else 0,
                1 if long_w.calculate_fpbr() > p.deg_fpbr_quarantined else 0
            ])

            if old_state == SleeveEfficiencyState.DEHYDRATED and q_count >= 2:
                if long_w.sum_net < ZERO and long_w.sum_gross > ZERO:
                    new_state = SleeveEfficiencyState.QUARANTINED
                    reason = "CRITICAL_FRICTION_DESTRUCTION"

            elif old_state == SleeveEfficiencyState.THROTTLED and d_count >= 2:
                if matrix.short_window.calculate_ncr() < Decimal("0.25"):
                    new_state = SleeveEfficiencyState.DEHYDRATED
                    reason = "SEVERE_METRIC_DECAY"

            elif old_state == SleeveEfficiencyState.NORMAL and t_count >= 2:
                new_state = SleeveEfficiencyState.THROTTLED
                reason = "ROLLING_EFFICIENCY_THROTTLED"

        # --- 2. RECOVERY EVALUATION (Only if no degradation occurred) ---
        if new_state == old_state and old_state in {SleeveEfficiencyState.THROTTLED, SleeveEfficiencyState.DEHYDRATED, SleeveEfficiencyState.QUARANTINED, SleeveEfficiencyState.RECOVERY_OBSERVATION}:

            # GATING: Must have gathered sufficient new samples in current state to prove trend
            if matrix.samples_since_transition >= p.min_recovery_samples:
                sh_ncr = matrix.short_window.calculate_ncr()
                sh_fbr = matrix.short_window.calculate_fbr()
                sh_fpbr = matrix.short_window.calculate_fpbr()
                sh_nppt = matrix.short_window.calculate_nppt()

                if old_state == SleeveEfficiencyState.RECOVERY_OBSERVATION:
                    if (m_ncr >= p.rec_ncr_full and m_fbr <= p.rec_fbr_full and
                        m_fpbr <= p.rec_fpbr_full and m_nppt > ZERO and med.calculate_cer() > ZERO):
                        new_state = SleeveEfficiencyState.NORMAL
                        reason = "FULL_RECOVERY_METRICS_CLEARED"
                else:
                    if (m_ncr >= p.rec_ncr_med and sh_ncr >= p.rec_ncr_med and
                        m_fbr <= p.rec_fbr_med and sh_fbr <= p.rec_fbr_med and
                        m_fpbr <= p.rec_fpbr_med and sh_fpbr <= p.rec_fpbr_med and
                        m_nppt > ZERO and sh_nppt > ZERO):
                        new_state = SleeveEfficiencyState.RECOVERY_OBSERVATION
                        reason = "SHORT_MED_METRICS_STABILIZED"

        if new_state != old_state:
            matrix.current_state = new_state
            matrix.samples_since_transition = 0
            logger.info(f"Sleeve {sleeve_id} transition: {old_state.value} -> {new_state.value} ({reason})")
            return EfficiencyTransition(sleeve_id, old_state, new_state, reason, timestamp_ns)

        return None
