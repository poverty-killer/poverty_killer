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
from typing import Dict, List, Optional

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

class EfficiencyPolicyConfig:
    __slots__ = (
        'short_window', 'medium_window', 'long_window', 'min_recovery_samples',
        'ceiling_normal', 'ceiling_throttled', 'ceiling_dehydrated',
        'ceiling_quarantined', 'ceiling_recovery',
        'deg_ncr_throttle', 'deg_fbr_throttle', 'deg_fpbr_throttle',
        'deg_ncr_dehydrated', 'deg_fbr_dehydrated', 'deg_fpbr_dehydrated',
        'deg_ncr_quarantined', 'deg_fbr_quarantined', 'deg_fpbr_quarantined',
        'rec_ncr_med', 'rec_fbr_med', 'rec_fpbr_med',
        'rec_ncr_full', 'rec_fbr_full', 'rec_fpbr_full'
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

@dataclass(frozen=True, slots=True)
class EfficiencyTransition:
    sleeve_id: str
    old_state: SleeveEfficiencyState
    new_state: SleeveEfficiencyState
    reason_code: str
    timestamp_ns: int

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

    __slots__ = ('policy', '_matrices')

    def __init__(self, policy: Optional[EfficiencyPolicyConfig] = None):
        self.policy = policy or EfficiencyPolicyConfig()
        self._matrices: Dict[str, SleeveStateMatrix] = {}

    def get_sleeve_state(self, sleeve_id: str) -> SleeveEfficiencyState:
        matrix = self._matrices.get(sleeve_id)
        return matrix.current_state if matrix else SleeveEfficiencyState.NORMAL

    def get_sizing_multiplier(self, sleeve_id: str) -> Decimal:
        state = self.get_sleeve_state(sleeve_id)
        if state == SleeveEfficiencyState.NORMAL: return self.policy.ceiling_normal
        if state == SleeveEfficiencyState.THROTTLED: return self.policy.ceiling_throttled
        if state == SleeveEfficiencyState.DEHYDRATED: return self.policy.ceiling_dehydrated
        if state == SleeveEfficiencyState.QUARANTINED: return self.policy.ceiling_quarantined
        return self.policy.ceiling_recovery

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
        carry_drag: Decimal, capital_committed: Decimal
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
        matrix.samples_since_transition += 1

        return self._evaluate_state_transitions(sleeve_id, matrix, timestamp_ns)

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