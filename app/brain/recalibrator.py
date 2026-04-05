"""
Recalibration Engine - Sovereign Topological Brain
Decides if a drawdown is "Fake-Out" (Buy the Dip) or "Structural Collapse" (Liquidate).
Uses Topological Data Analysis (Betti numbers and persistence) as the primary filter.
Standard technical indicators (RSI, MACD) are forbidden. This is pure order book geometry.
"""

import logging
import math
import threading
from typing import Dict, Any, Optional
from datetime import datetime
from dataclasses import dataclass

from app.brain.topological_engine import TopologicalSignal
from app.utils.time_utils import now_ns

logger = logging.getLogger(__name__)


@dataclass
class RecalibrationState:
    """Current recalibration state."""
    is_in_recalibration: bool = False
    recalibration_start_ns: Optional[int] = None          # nanoseconds
    recalibration_reason: str = ""
    requested_duration_ns: int = 0                         # nanoseconds
    last_assessment_ns: Optional[int] = None              # nanoseconds
    consecutive_fakeouts: int = 0
    consecutive_collapses: int = 0
    recovery_attempts: int = 0
    last_betti_1_count: int = 0
    last_persistence_score: float = 0.0



class Recalibrator:
    """
    Sovereign Topological Brain - Alpha-Stay Logic.
    
    Uses Topological Data Analysis (TPE) to decide:
    - "ALPHA_STAY" (Buy the Dip): Price drops but strong, persistent voids remain below.
      Whales are pulling liquidity to trigger retail stops, but haven't actually sold.
    - "CRISIS_ABORT" (Liquidate): Price drops AND voids disappear.
      Whales filled their orders and left. The floor is gone.
    - "NEUTRAL": Standard noise, no action needed.
    
    Standard technical indicators (RSI, MACD, moving averages) are FORBIDDEN.
    Only order book geometry (Betti numbers, persistence) is used.
    """

    def __init__(
        self,
        fakeout_price_threshold_pct: float = 0.05,      # 5% drop threshold for fake-out
        fakeout_betti_threshold: int = 2,               # Need at least 2 voids
        fakeout_persistence_threshold: float = 0.8,     # Need strong persistence
        collapse_price_threshold_pct: float = 0.05,     # 5% drop threshold for collapse
        collapse_betti_threshold: int = 0,              # Voids disappear (Betti-1 = 0)
        min_recalibration_seconds: float = 3600.0,      # 1 hour minimum recalibration
        max_recalibration_seconds: float = 14400.0,     # 4 hours maximum recalibration
        recovery_required_good: int = 3                 # Number of good signals after collapse
    ):
        """
        Initialize recalibrator with topological parameters.

        Args:
            fakeout_price_threshold_pct: Price drop % that qualifies as potential fake-out
            fakeout_betti_threshold: Minimum Betti-1 count for fake-out detection
            fakeout_persistence_threshold: Minimum persistence score for fake-out
            collapse_price_threshold_pct: Price drop % that qualifies as potential collapse
            collapse_betti_threshold: Betti-1 count threshold for collapse (0 = voids gone)
            min_recalibration_seconds: Minimum recalibration pause
            max_recalibration_seconds: Maximum recalibration pause
            recovery_required_good: Number of good signals needed after collapse
        """
        self.fakeout_price_threshold_pct = fakeout_price_threshold_pct
        self.fakeout_betti_threshold = fakeout_betti_threshold
        self.fakeout_persistence_threshold = fakeout_persistence_threshold
        self.collapse_price_threshold_pct = collapse_price_threshold_pct
        self.collapse_betti_threshold = collapse_betti_threshold
        self.min_recalibration_seconds = min_recalibration_seconds
        self.max_recalibration_seconds = max_recalibration_seconds
        self.recovery_required_good = recovery_required_good

        self._state = RecalibrationState()
        self._lock = threading.Lock()
        self._assessment_history: list = []

        logger.info(f"Recalibrator initialized: fakeout_price={fakeout_price_threshold_pct:.1%}, "
                   f"fakeout_betti={fakeout_betti_threshold}, "
                   f"collapse_price={collapse_price_threshold_pct:.1%}, "
                   f"min_recal={min_recalibration_seconds:.0f}s, "
                   f"max_recal={max_recalibration_seconds:.0f}s")

    # ============================================
    # SOVEREIGN TOPOLOGICAL REGIME MATRIX
    # ============================================

    def evaluate_regime(
        self,
        price_drop_pct: float,
        tpe_signal: Optional[TopologicalSignal],
        drop_duration_sec: float = 0.0
    ) -> str:
        """
        Sovereign Topological Regime Matrix.
        Evaluates physical order book geometry against price action.

        Args:
            price_drop_pct: Current price drop percentage from peak
            tpe_signal: Current topological signal from TPE engine
            drop_duration_sec: How long the drop has been occurring

        Returns:
            "ALPHA_STAY" - Buy the dip (fake-out, structure intact)
            "CRISIS_ABORT" - Liquidate (structural collapse)
            "NEUTRAL" - Standard noise, no action
        """
        with self._lock:
            self._state.last_assessment_ns = now_ns()

            # Extract topological metrics
            betti_1_count = tpe_signal.betti_1 if tpe_signal else 0
            persistence_score = tpe_signal.persistence_score if tpe_signal else 0.0
            super_void_detected = tpe_signal.super_void_detected if tpe_signal else False

            self._state.last_betti_1_count = betti_1_count
            self._state.last_persistence_score = persistence_score

            # ============================================
            # 1. Extreme Velocity Override
            # If drop is too fast, topology may be lagging
            # ============================================
            if price_drop_pct > 0.05 and drop_duration_sec < 10.0:
                logger.warning(f"EXTREME VELOCITY: {price_drop_pct:.2%} in {drop_duration_sec:.1f}s - topology may lag")
                return "NEUTRAL"

            # ============================================
            # 2. THE FAKE-OUT (Buy the Dip)
            # Price drops, but strong, persistent voids remain below.
            # Whales are pulling liquidity to trigger retail stops,
            # but haven't actually sold. The structure is intact.
            # ============================================
            if (price_drop_pct <= self.fakeout_price_threshold_pct and
                betti_1_count >= self.fakeout_betti_threshold and
                persistence_score >= self.fakeout_persistence_threshold):
                
                self._state.consecutive_fakeouts += 1
                self._state.consecutive_collapses = 0
                
                logger.info(f"FAKE-OUT DETECTED: price_drop={price_drop_pct:.2%}, "
                           f"betti_1={betti_1_count}, persistence={persistence_score:.2f}")
                
                if self._state.consecutive_fakeouts >= self.recovery_required_good:
                    self._state.consecutive_fakeouts = 0
                    return "ALPHA_STAY"
                return "NEUTRAL"

            # ============================================
            # 3. STRUCTURAL COLLAPSE (Liquidate)
            # Price drops AND voids disappear.
            # The whales actually filled their orders and left.
            # The floor is gone. GTFO.
            # ============================================
            if (price_drop_pct > self.collapse_price_threshold_pct and
                betti_1_count <= self.collapse_betti_threshold):
                
                self._state.consecutive_collapses += 1
                self._state.consecutive_fakeouts = 0
                
                logger.critical(f"STRUCTURAL COLLAPSE: price_drop={price_drop_pct:.2%}, "
                               f"betti_1={betti_1_count} <= {self.collapse_betti_threshold}")
                
                if self._state.consecutive_collapses >= self.recovery_required_good:
                    self._state.consecutive_collapses = 0
                    return "CRISIS_ABORT"
                return "NEUTRAL"

            # ============================================
            # 4. Super Void Detection (Pre-Crash Signal)
            # TPE detected a liquidity void forming
            # ============================================
            if super_void_detected and price_drop_pct > 0.02:
                logger.warning(f"SUPER VOID DETECTED with {price_drop_pct:.2%} drop")
                return "CRISIS_ABORT"

            # ============================================
            # 5. Standard Noise
            # No clear signal, stand by
            # ============================================
            self._state.consecutive_fakeouts = 0
            self._state.consecutive_collapses = 0
            return "NEUTRAL"

    # ============================================
    # RECALIBRATION STATE MANAGEMENT
    # ============================================

    def start_recalibration(self, reason: str, duration_seconds: float) -> None:
        """
        Start recalibration pause.

        Args:
            reason: Reason for recalibration
            duration_seconds: Duration of pause (will be clamped to min/max)
        
        Raises:
            ValueError: If duration_seconds is not finite or not positive
        """
        with self._lock:
            # Strong validation of duration input
            if not math.isfinite(duration_seconds):
                raise ValueError(f"Recalibration duration must be finite, got {duration_seconds}")
            if duration_seconds <= 0:
                raise ValueError(f"Recalibration duration must be positive, got {duration_seconds}")
            
            # Clamp duration to configured bounds
            clamped = max(self.min_recalibration_seconds,
                          min(duration_seconds, self.max_recalibration_seconds))
            if clamped != duration_seconds:
                logger.warning(f"Recalibration duration clamped from {duration_seconds:.0f}s "
                              f"to {clamped:.0f}s (min={self.min_recalibration_seconds:.0f}s, "
                              f"max={self.max_recalibration_seconds:.0f}s)")

            # Capture single authoritative timestamp for this start event
            start_ns = now_ns()
            
            self._state.is_in_recalibration = True
            self._state.recalibration_start_ns = start_ns
            self._state.recalibration_reason = reason
            self._state.requested_duration_ns = int(clamped * 1_000_000_000)  # seconds → nanoseconds
            self._state.recovery_attempts += 1

            logger.critical(f"RECALIBRATION STARTED: {reason} for {clamped:.0f}s")
            logger.critical(f"  Recovery attempt #{self._state.recovery_attempts}")

            self._assessment_history.append({
                "timestamp_ns": start_ns,
                "type": "recalibration_start",
                "reason": reason,
                "duration_seconds": clamped,
                "recovery_attempt": self._state.recovery_attempts
            })

    def end_recalibration(self) -> None:
        """End recalibration pause."""
        with self._lock:
            if self._state.is_in_recalibration:
                end_ns = now_ns()
                duration_ns = end_ns - self._state.recalibration_start_ns if self._state.recalibration_start_ns else 0
                duration_seconds = duration_ns / 1_000_000_000
                logger.info(f"RECALIBRATION ENDED: Duration {duration_seconds:.0f}s")
                self._state.is_in_recalibration = False
                self._state.recalibration_start_ns = None
                self._state.recalibration_reason = ""
                self._state.requested_duration_ns = 0
                self._state.consecutive_fakeouts = 0
                self._state.consecutive_collapses = 0

                self._assessment_history.append({
                    "timestamp_ns": end_ns,
                    "type": "recalibration_end",
                    "duration_seconds": duration_seconds
                })

    def is_in_recalibration(self) -> bool:
        """Check if currently in recalibration."""
        with self._lock:
            return self._state.is_in_recalibration

    def get_recalibration_remaining(self) -> float:
        """Get remaining recalibration time in seconds."""
        with self._lock:
            if not self._state.is_in_recalibration or not self._state.recalibration_start_ns:
                return 0.0

            elapsed_ns = now_ns() - self._state.recalibration_start_ns
            remaining_ns = max(0, self._state.requested_duration_ns - elapsed_ns)
            return remaining_ns / 1_000_000_000

    # ============================================
    # RECOVERY STRATEGY SELECTION
    # ============================================

    def get_recovery_strategy(self) -> Dict[str, Any]:
        """
        Get recovery strategy based on recalibration history.

        Returns:
            Dictionary with recovery strategy parameters
        """
        with self._lock:
            if self._state.recovery_attempts <= 1:
                return {
                    "kelly_multiplier": 0.3,
                    "min_confidence": 0.85,
                    "max_position_pct": 0.5,
                    "strategy_focus": "shadow_front",
                    "description": "Conservative recovery - first attempt"
                }
            elif self._state.recovery_attempts <= 3:
                return {
                    "kelly_multiplier": 0.5,
                    "min_confidence": 0.75,
                    "max_position_pct": 0.7,
                    "strategy_focus": "entropy_decoder",
                    "description": "Moderate recovery - rebuilding"
                }
            else:
                return {
                    "kelly_multiplier": 0.7,
                    "min_confidence": 0.65,
                    "max_position_pct": 0.9,
                    "strategy_focus": "hra_attack",
                    "description": "Aggressive recovery - final attempt"
                }

    def should_recover(self) -> bool:
        """
        Determine if bot should exit recalibration and attempt recovery.

        Returns:
            True if ready to recover
        """
        with self._lock:
            if not self._state.is_in_recalibration:
                return False

            if not self._state.recalibration_start_ns:
                return False

            elapsed_ns = now_ns() - self._state.recalibration_start_ns
            return elapsed_ns >= self._state.requested_duration_ns

    def reset_recovery_count(self) -> None:
        """Reset recovery attempt counter (after successful recovery)."""
        with self._lock:
            self._state.recovery_attempts = 0
            self._state.consecutive_fakeouts = 0
            self._state.consecutive_collapses = 0
            logger.info("Recovery counter reset - clean slate")

    # ============================================
    # TOPOLOGICAL METRICS ACCESS
    # ============================================

    def get_last_topological_metrics(self) -> Dict[str, Any]:
        """Get last topological metrics from the most recent assessment."""
        with self._lock:
            return {
                "last_betti_1_count": self._state.last_betti_1_count,
                "last_persistence_score": self._state.last_persistence_score,
                "consecutive_fakeouts": self._state.consecutive_fakeouts,
                "consecutive_collapses": self._state.consecutive_collapses
            }

    # ============================================
    # DIAGNOSTICS
    # ============================================

    def _ns_to_iso(self, ns: Optional[int]) -> Optional[str]:
        """Convert nanosecond timestamp to ISO string for output."""
        if ns is None:
            return None
        dt = datetime.utcfromtimestamp(ns / 1_000_000_000)
        return dt.isoformat() + "Z"

    def get_status(self) -> Dict[str, Any]:
        """Get recalibrator status."""
        with self._lock:
            # Convert assessment history timestamps for output
            history = []
            for entry in self._assessment_history[-10:]:
                copied = entry.copy()
                if "timestamp_ns" in copied:
                    copied["timestamp"] = self._ns_to_iso(copied.pop("timestamp_ns"))
                history.append(copied)

            return {
                "is_in_recalibration": self._state.is_in_recalibration,
                "recalibration_reason": self._state.recalibration_reason,
                "recalibration_start": self._ns_to_iso(self._state.recalibration_start_ns),
                "requested_duration_seconds": self._state.requested_duration_ns / 1_000_000_000,
                "recovery_attempts": self._state.recovery_attempts,
                "consecutive_fakeouts": self._state.consecutive_fakeouts,
                "consecutive_collapses": self._state.consecutive_collapses,
                "assessment_history": history,
                "fakeout_price_threshold_pct": self.fakeout_price_threshold_pct,
                "fakeout_betti_threshold": self.fakeout_betti_threshold,
                "fakeout_persistence_threshold": self.fakeout_persistence_threshold,
                "collapse_price_threshold_pct": self.collapse_price_threshold_pct,
                "collapse_betti_threshold": self.collapse_betti_threshold,
                "last_betti_1_count": self._state.last_betti_1_count,
                "last_persistence_score": self._state.last_persistence_score,
                "min_recalibration_seconds": self.min_recalibration_seconds,
                "max_recalibration_seconds": self.max_recalibration_seconds
            }

    def reset(self) -> None:
        """Reset recalibrator state."""
        with self._lock:
            self._state = RecalibrationState()
            self._assessment_history = []
            logger.info("Recalibrator reset")
