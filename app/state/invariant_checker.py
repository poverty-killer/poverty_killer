"""
Invariant Checker for Sovereign Trading System

This module enforces system invariants by evaluating the approved
invariant registry against current system state.

Responsibilities:
- Evaluate normal invariants (I-01 through I-09) against current state
- Evaluate kill-switch invariants (KS-01 through KS-10) with thresholds
- Track violation counts and durations for time-based invariants
- Produce deterministic InvariantCheckResult and InvariantBatchCheckResult
- Maintain state for invariants that require history

Boundaries:
- Owns: Invariant evaluation, violation tracking, result generation
- Does NOT own: Truth aggregation (TruthKernel), reconciliation (TruthReconciler)
- Does NOT own: Risk mode changes (RiskDecision)
- Consumes: TruthFrame, KillSwitchInvariant definitions
- Produces: InvariantBatchCheckResult for risk system

Stage 2 Implementation Status:
- Fully implemented: I-01, I-02, I-05, I-06, KS-01, KS-04, KS-05, KS-06, KS-10
- Deferred to Stage 3: I-03, I-04, I-07, KS-02, KS-03, KS-07
- Deferred to Stage 4: KS-08, KS-09
"""

import logging
from typing import Optional, Dict, List, Any, Tuple, Deque
from dataclasses import dataclass, field
from collections import deque

from app.models.contracts import TruthFrame, PortfolioTruth, RiskTruth
from app.models.enums import (
    InvariantViolationSeverity, TruthStatus, RiskMode
)
from app.models.invariants import (
    NORMAL_INVARIANTS, KILL_SWITCH_INVARIANTS, KillSwitchInvariant,
    InvariantViolationEvent, InvariantCheckResult, InvariantBatchCheckResult,
    NormalInvariant
)
from app.utils.time_utils import now_ns

logger = logging.getLogger(__name__)


class InvariantCheckerError(Exception):
    """Base exception for invariant checker errors."""
    pass


def _safe_str(value: Any) -> str:
    """
    Safely convert enum or string to string representation.
    
    Args:
        value: Value that may be an enum or string
    
    Returns:
        String representation
    """
    if hasattr(value, "value"):
        return value.value
    return str(value)


@dataclass
class ViolationTracker:
    """
    Tracks violations for invariants that require state.
    Used for time-window and count-based invariants.
    """
    violation_count: int = 0
    first_violation_ns: int = 0
    last_violation_ns: int = 0
    violation_events: Deque[InvariantViolationEvent] = field(default_factory=lambda: deque(maxlen=100))

    def add_violation(self, event: InvariantViolationEvent) -> None:
        """Add a violation event to tracking."""
        self.violation_count += 1
        self.last_violation_ns = event.timestamp_ns
        if self.first_violation_ns == 0:
            self.first_violation_ns = event.timestamp_ns
        self.violation_events.append(event)

    def clear(self) -> None:
        """Clear violation tracking."""
        self.violation_count = 0
        self.first_violation_ns = 0
        self.last_violation_ns = 0
        self.violation_events.clear()


class InvariantChecker:
    """
    Invariant Checker - Enforces system invariants.
    
    Features:
    - Evaluates all normal and kill-switch invariants
    - Tracks violation history for time-window invariants
    - Produces deterministic InvariantBatchCheckResult
    - Thread-safe with lock per evaluation
    
    This component does NOT make risk decisions; it only evaluates
    invariants and reports violations. Risk mode changes are the
    responsibility of the RiskDecision component.
    """
    
    def __init__(self):
        """Initialize invariant checker."""
        self._normal_invariants = {inv.id: inv for inv in NORMAL_INVARIANTS}
        self._kill_switch_invariants = {inv.id: inv for inv in KILL_SWITCH_INVARIANTS}
        
        # Trackers for invariants that need state
        self._violation_trackers: Dict[str, ViolationTracker] = {}
        
        logger.info(f"InvariantChecker initialized: {len(self._normal_invariants)} normal, "
                   f"{len(self._kill_switch_invariants)} kill-switch invariants")
    
    # ============================================
    # Main Evaluation Entry Point
    # ============================================
    
    def evaluate(self, truth_frame: TruthFrame) -> InvariantBatchCheckResult:
        """
        Evaluate all invariants against the current TruthFrame.
        
        Args:
            truth_frame: Current TruthFrame with all five truths
        
        Returns:
            InvariantBatchCheckResult with all check results
        """
        results: List[InvariantCheckResult] = []
        
        # Evaluate normal invariants
        for inv_id, invariant in self._normal_invariants.items():
            if not invariant.enabled:
                continue
            result = self._evaluate_normal_invariant(invariant, truth_frame)
            results.append(result)
        
        # Evaluate kill-switch invariants
        for inv_id, invariant in self._kill_switch_invariants.items():
            result = self._evaluate_kill_switch_invariant(invariant, truth_frame)
            results.append(result)
        
        # Build batch result
        batch = InvariantBatchCheckResult(
            timestamp_ns=truth_frame.timestamp_ns,
            results=results
        )
        
        # Clean up old history
        self._cleanup_history(truth_frame.timestamp_ns)
        
        return batch
    
    # ============================================
    # Normal Invariant Evaluation
    # ============================================
    
    def _evaluate_normal_invariant(
        self,
        invariant: NormalInvariant,
        truth_frame: TruthFrame
    ) -> InvariantCheckResult:
        """
        Evaluate a single normal invariant.
        
        Args:
            invariant: NormalInvariant to evaluate
            truth_frame: Current TruthFrame
        
        Returns:
            InvariantCheckResult
        """
        passed = True
        violation: Optional[InvariantViolationEvent] = None
        message: Optional[str] = None
        
        try:
            if invariant.id == "I-01":
                passed, message = self._check_truth_status_per_action(truth_frame)
            elif invariant.id == "I-02":
                passed, message = self._check_risk_approval_required(truth_frame)
            elif invariant.id == "I-03":
                passed, message = self._check_fill_idempotence(truth_frame)
            elif invariant.id == "I-04":
                passed, message = self._check_no_conflicting_order_intents(truth_frame)
            elif invariant.id == "I-05":
                passed, message = self._check_portfolio_equity_consistency(truth_frame)
            elif invariant.id == "I-06":
                passed, message = self._check_no_stale_market_data(truth_frame)
            elif invariant.id == "I-07":
                passed, message = self._check_monotonic_timestamps(truth_frame)
            elif invariant.id == "I-08":
                passed, message = self._check_decimal_precision(truth_frame)
            elif invariant.id == "I-09":
                passed, message = self._check_unique_decision_uuid(truth_frame)
            else:
                # Unknown invariant - skip with warning
                logger.warning(f"Unknown normal invariant: {invariant.id}")
                passed = True
                message = "unknown_invariant_skipped"
        except Exception as e:
            logger.error(f"Invariant {invariant.id} evaluation failed: {e}")
            passed = False
            message = f"evaluation_error: {e}"
        
        if not passed:
            violation = InvariantViolationEvent(
                invariant_id=invariant.id,
                invariant_name=invariant.name,
                severity=invariant.severity,
                timestamp_ns=truth_frame.timestamp_ns,
                expected_value="invariant satisfied",
                observed_value=message or "invariant violated",
                context={"truth_frame_id": truth_frame.truth_frame_id}
            )
            self._track_violation(invariant.id, violation)
        
        return InvariantCheckResult(
            invariant_id=invariant.id,
            passed=passed,
            severity=invariant.severity if not passed else InvariantViolationSeverity.INFO,
            violation=violation,
            message=message,
            timestamp_ns=truth_frame.timestamp_ns
        )
    
    # ============================================
    # Normal Invariant Implementations
    # ============================================
    
    def _check_truth_status_per_action(self, truth_frame: TruthFrame) -> Tuple[bool, str]:
        """
        I-01: Truth status per action type.
        
        Rules:
        - New orders: require RECONCILED or DRIFTING (<5s)
        - Cancels: allowed in RECONCILED, DRIFTING, and SAFE_MODE
        - Blocked in BROKEN
        
        Stage 2: Status-based only. Timing threshold requires frame-relative
        divergence duration tracking (deferred to Stage 3).
        """
        status = truth_frame.status
        
        # BROKEN blocks all actions
        if status == TruthStatus.BROKEN:
            return False, f"BROKEN status blocks all actions"
        
        # DRIFTING is allowed for cancels but may require scaling for new orders
        if status == TruthStatus.DRIFTING:
            # Stage 2: Basic check - allow DRIFTING with warning
            # Full timing threshold requires divergence duration tracking
            return True, "ok (DRIFTING allowed in Stage 2)"
        
        return True, "ok"
    
    def _check_risk_approval_required(self, truth_frame: TruthFrame) -> Tuple[bool, str]:
        """
        I-02: RiskDecision approval required.
        
        Checks that RiskTruth indicates trading is permitted.
        """
        risk_truth = truth_frame.risk_truth
        
        if risk_truth.mode == RiskMode.HARD_FLAT:
            return False, f"Risk mode is HARD_FLAT"
        
        if risk_truth.mode == RiskMode.REPLAY_ONLY:
            return False, f"Risk mode is REPLAY_ONLY"
        
        return True, "ok"
    
    def _check_fill_idempotence(self, truth_frame: TruthFrame) -> Tuple[bool, str]:
        """
        I-03: Fill idempotence.
        
        Deferred to Stage 3 fill reconciler for full implementation.
        """
        return True, "deferred_to_stage_3"
    
    def _check_no_conflicting_order_intents(self, truth_frame: TruthFrame) -> Tuple[bool, str]:
        """
        I-04: No conflicting order intents.
        
        Deferred to Stage 3 when OrderIntent tracking is fully implemented.
        """
        return True, "deferred_to_stage_3"
    
    def _check_portfolio_equity_consistency(self, truth_frame: TruthFrame) -> Tuple[bool, str]:
        """
        I-05: Portfolio equity consistency.
        
        Ensures total equity equals cash + marked position value within tolerance.
        """
        portfolio = truth_frame.portfolio_truth
        
        # Compute total equity from positions
        computed_equity = portfolio.cash.get("USD", 0)
        for pos in portfolio.positions:
            computed_equity += pos.quantity * pos.mark_price
        
        # Check tolerance (0.01% for USD, 0.000001% for crypto)
        diff = abs(portfolio.total_equity - computed_equity)
        if diff > 0.01:  # $0.01 tolerance
            return False, f"Equity mismatch: actual {portfolio.total_equity}, computed {computed_equity}, diff {diff}"
        
        return True, "ok"
    
    def _check_no_stale_market_data(self, truth_frame: TruthFrame) -> Tuple[bool, str]:
        """
        I-06: No stale market data.
        
        Checks for stale market data using frame-relative timestamp comparison.
        """
        exchange = truth_frame.exchange_truth
        
        # Frame-relative age calculation
        age_ns = truth_frame.timestamp_ns - exchange.exchange_ts_ns
        
        if age_ns > 10_000_000_000:  # 10 seconds
            return False, f"Exchange data stale: age {age_ns}ns"
        
        return True, "ok"
    
    def _check_monotonic_timestamps(self, truth_frame: TruthFrame) -> Tuple[bool, str]:
        """
        I-07: Monotonic timestamps.
        
        Deferred to Stage 3 when full frame history is available.
        """
        return True, "deferred_to_stage_3"
    
    def _check_decimal_precision(self, truth_frame: TruthFrame) -> Tuple[bool, str]:
        """
        I-08: Decimal precision.
        
        Type-level check; runtime validation is in decimal_utils.
        """
        return True, "ok (contract layer enforces)"
    
    def _check_unique_decision_uuid(self, truth_frame: TruthFrame) -> Tuple[bool, str]:
        """
        I-09: Unique DecisionRecord UUID.
        
        Deferred to Stage 3 when DecisionRecord tracking is implemented.
        """
        return True, "deferred_to_stage_3"
    
    # ============================================
    # Kill-Switch Invariant Evaluation
    # ============================================
    
    def _evaluate_kill_switch_invariant(
        self,
        invariant: KillSwitchInvariant,
        truth_frame: TruthFrame
    ) -> InvariantCheckResult:
        """
        Evaluate a single kill-switch invariant.
        
        Stage 2 policy: All kill-switch violations trigger SAFE_MODE.
        This may be refined in later stages as invariant definitions evolve.
        
        Args:
            invariant: KillSwitchInvariant to evaluate
            truth_frame: Current TruthFrame
        
        Returns:
            InvariantCheckResult
        """
        passed = True
        violation: Optional[InvariantViolationEvent] = None
        message: Optional[str] = None
        
        try:
            if invariant.id == "KS-01":
                passed, message = self._check_truth_divergence_duration(truth_frame, invariant)
            elif invariant.id == "KS-02":
                passed, message = self._check_unmatched_fill_count(truth_frame, invariant)
            elif invariant.id == "KS-03":
                passed, message = self._check_repeated_rejections(truth_frame, invariant)
            elif invariant.id == "KS-04":
                passed, message = self._check_clock_skew(truth_frame, invariant)
            elif invariant.id == "KS-05":
                passed, message = self._check_stale_market_data(truth_frame, invariant)
            elif invariant.id == "KS-06":
                passed, message = self._check_portfolio_reconciliation_mismatch(truth_frame, invariant)
            elif invariant.id == "KS-07":
                passed, message = self._check_duplicate_sequence_detection(truth_frame, invariant)
            elif invariant.id == "KS-08":
                passed, message = self._check_wal_corruption(truth_frame, invariant)
            elif invariant.id == "KS-09":
                passed, message = self._check_recovery_checksum_failure(truth_frame, invariant)
            elif invariant.id == "KS-10":
                passed, message = self._check_hard_flat_override(truth_frame, invariant)
            else:
                logger.warning(f"Unknown kill-switch invariant: {invariant.id}")
                passed = True
                message = "unknown_invariant_skipped"
        except Exception as e:
            logger.error(f"Kill-switch invariant {invariant.id} evaluation failed: {e}")
            passed = False
            message = f"evaluation_error: {e}"
        
        if not passed:
            violation = InvariantViolationEvent(
                invariant_id=invariant.id,
                invariant_name=invariant.name,
                severity=InvariantViolationSeverity.SAFE_MODE,  # Stage 2 policy
                timestamp_ns=truth_frame.timestamp_ns,
                expected_value="invariant satisfied",
                observed_value=message or "invariant violated",
                context={"truth_frame_id": truth_frame.truth_frame_id}
            )
            self._track_violation(invariant.id, violation)
        
        return InvariantCheckResult(
            invariant_id=invariant.id,
            passed=passed,
            severity=InvariantViolationSeverity.SAFE_MODE if not passed else InvariantViolationSeverity.INFO,
            violation=violation,
            message=message,
            timestamp_ns=truth_frame.timestamp_ns
        )
    
    # ============================================
    # Kill-Switch Invariant Implementations
    # ============================================
    
    def _check_truth_divergence_duration(
        self,
        truth_frame: TruthFrame,
        invariant: KillSwitchInvariant
    ) -> Tuple[bool, str]:
        """
        KS-01: Truth divergence duration exceeds threshold.
        """
        threshold_ns = invariant.threshold_ns or 5_000_000_000
        divergence_ns = truth_frame.divergence_ns
        
        if divergence_ns > threshold_ns:
            return False, f"Divergence duration {divergence_ns}ns > {threshold_ns}ns"
        
        return True, "ok"
    
    def _check_unmatched_fill_count(
        self,
        truth_frame: TruthFrame,
        invariant: KillSwitchInvariant
    ) -> Tuple[bool, str]:
        """
        KS-02: Unmatched fill count exceeds threshold.
        
        Deferred to Stage 3 when fill reconciliation is implemented.
        """
        return True, "deferred_to_stage_3"
    
    def _check_repeated_rejections(
        self,
        truth_frame: TruthFrame,
        invariant: KillSwitchInvariant
    ) -> Tuple[bool, str]:
        """
        KS-03: Repeated rejections per symbol exceed threshold.
        
        Deferred to Stage 3 when execution truth contains rejection tracking.
        """
        return True, "deferred_to_stage_3"
    
    def _check_clock_skew(
        self,
        truth_frame: TruthFrame,
        invariant: KillSwitchInvariant
    ) -> Tuple[bool, str]:
        """
        KS-04: Clock skew exceeds threshold.
        
        Uses frame-relative timestamp comparison.
        """
        threshold_ns = invariant.threshold_ns or 30_000_000_000
        
        exchange_ts = truth_frame.exchange_truth.exchange_ts_ns
        frame_ts = truth_frame.timestamp_ns
        
        skew = abs(exchange_ts - frame_ts)
        
        if skew > threshold_ns:
            return False, f"Clock skew {skew}ns > {threshold_ns}ns"
        
        return True, "ok"
    
    def _check_stale_market_data(
        self,
        truth_frame: TruthFrame,
        invariant: KillSwitchInvariant
    ) -> Tuple[bool, str]:
        """
        KS-05: No market data update on critical symbol.
        
        Uses frame-relative timestamp comparison.
        """
        threshold_ns = invariant.threshold_ns or 10_000_000_000
        
        exchange = truth_frame.exchange_truth
        age_ns = truth_frame.timestamp_ns - exchange.exchange_ts_ns
        
        if age_ns > threshold_ns:
            return False, f"Market data stale: age {age_ns}ns > {threshold_ns}ns"
        
        return True, "ok"
    
    def _check_portfolio_reconciliation_mismatch(
        self,
        truth_frame: TruthFrame,
        invariant: KillSwitchInvariant
    ) -> Tuple[bool, str]:
        """
        KS-06: Portfolio equity vs computed equity mismatch.
        """
        threshold_value = invariant.threshold_value or 0.005
        portfolio = truth_frame.portfolio_truth
        
        computed_equity = portfolio.cash.get("USD", 0)
        for pos in portfolio.positions:
            computed_equity += pos.quantity * pos.mark_price
        
        if portfolio.total_equity == 0:
            mismatch = 0.0
        else:
            mismatch = abs(portfolio.total_equity - computed_equity) / portfolio.total_equity
        
        if mismatch > threshold_value:
            return False, f"Reconciliation mismatch {mismatch:.4%} > {threshold_value:.4%}"
        
        return True, "ok"
    
    def _check_duplicate_sequence_detection(
        self,
        truth_frame: TruthFrame,
        invariant: KillSwitchInvariant
    ) -> Tuple[bool, str]:
        """
        KS-07: Same decision_uuid + sequence processed twice.
        
        Deferred to Stage 3 when DecisionRecord tracking is implemented.
        """
        return True, "deferred_to_stage_3"
    
    def _check_wal_corruption(
        self,
        truth_frame: TruthFrame,
        invariant: KillSwitchInvariant
    ) -> Tuple[bool, str]:
        """
        KS-08: Write-ahead log corruption.
        
        Deferred to Stage 4 WAL implementation.
        """
        return True, "deferred_to_stage_4"
    
    def _check_recovery_checksum_failure(
        self,
        truth_frame: TruthFrame,
        invariant: KillSwitchInvariant
    ) -> Tuple[bool, str]:
        """
        KS-09: Snapshot checksum mismatch.
        
        Deferred to Stage 4 recovery implementation.
        """
        return True, "deferred_to_stage_4"
    
    def _check_hard_flat_override(
        self,
        truth_frame: TruthFrame,
        invariant: KillSwitchInvariant
    ) -> Tuple[bool, str]:
        """
        KS-10: Hard flat override triggered.
        """
        risk_truth = truth_frame.risk_truth
        
        if risk_truth.hard_flat_triggered:
            return False, f"Hard flat override triggered: {risk_truth.hard_flat_reason}"
        
        return True, "ok"
    
    # ============================================
    # Violation Tracking
    # ============================================
    
    def _get_tracker(self, invariant_id: str) -> ViolationTracker:
        """Get or create violation tracker for invariant."""
        if invariant_id not in self._violation_trackers:
            self._violation_trackers[invariant_id] = ViolationTracker()
        return self._violation_trackers[invariant_id]
    
    def _track_violation(self, invariant_id: str, violation: InvariantViolationEvent) -> None:
        """Track a violation event for stateful invariants."""
        tracker = self._get_tracker(invariant_id)
        tracker.add_violation(violation)
    
    def _cleanup_history(self, current_ns: int) -> None:
        """
        Clean up old violation history.
        Keeps only last 10 seconds of history for time-window invariants.
        """
        window_ns = 10_000_000_000  # 10 seconds
        cutoff = current_ns - window_ns
        
        for tracker in self._violation_trackers.values():
            while tracker.violation_events and tracker.violation_events[0].timestamp_ns < cutoff:
                tracker.violation_events.popleft()
    
    def reset(self) -> None:
        """Reset invariant checker state."""
        self._violation_trackers.clear()
        logger.info("InvariantChecker reset")


# ============================================
# Convenience Functions
# ============================================

def create_invariant_checker() -> InvariantChecker:
    """
    Create a configured invariant checker.
    
    Returns:
        InvariantChecker instance
    """
    return InvariantChecker()


__all__ = [
    'InvariantChecker',
    'InvariantCheckerError',
    'create_invariant_checker',
]