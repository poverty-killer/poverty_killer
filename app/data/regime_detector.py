"""
Regime Detector for Sovereign Trading System

This module detects market regime based on topological features, entropy,
and market structure. It provides deterministic regime detection for alpha
generation and risk scaling.

Boundaries:
- Owns: Regime detection, regime state management
- Does NOT own: Decision compilation (DecisionCompiler), truth reconciliation
- Does NOT own: Invariant enforcement (InvariantChecker)
- Consumes: FeatureVector (requires topological_coherence, entropy, entropy_collapsed,
  void_depth, momentum_sign)
- Produces: RegimeType, confidence score, regime history

Stage 3 Implementation Status:
- Fully implemented: Heuristic regime detection based on topological coherence,
  entropy collapse, and momentum direction
- Directional detection uses momentum_sign from FeatureVector (bull/bear classification)
- Deferred to Stage 5: Full GMM-based regime classification, persistent homology
- Deferred to Stage 6: Novel alpha evaluation gates for regime detection

Architectural Constraints:
- No look-ahead bias: all calculations use only past data
- Deterministic under replay: state evolves deterministically from inputs
- Safe enum handling: no direct .value assumptions
- Clean boundaries: no blurring with strategy or truth layers
- Timestamp monotonicity enforced: stale/out-of-order updates are rejected
- Confidence updates are only applied to the active regime
"""

import logging
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass
from collections import deque

from app.models.contracts import FeatureVector
from app.models.enums import RegimeType
from app.utils.time_utils import is_monotonic

logger = logging.getLogger(__name__)


class RegimeDetectorError(Exception):
    """Base exception for regime detector errors."""
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
class RegimeState:
    """Current regime state."""
    regime: RegimeType = RegimeType.UNKNOWN
    confidence: float = 0.0
    timestamp_ns: int = 0
    transition_count: int = 0
    stability_score: float = 0.0
    last_update_ns: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "regime": _safe_str(self.regime),
            "confidence": self.confidence,
            "timestamp_ns": self.timestamp_ns,
            "transition_count": self.transition_count,
            "stability_score": self.stability_score
        }


@dataclass
class RegimeHistoryEntry:
    """Single entry in regime history."""
    timestamp_ns: int
    regime: RegimeType
    confidence: float
    features: Dict[str, float]


class RegimeDetector:
    """
    Deterministic regime detector.
    
    Stage 3: Heuristic detection based on:
    - Topological coherence (Betti-1 / (Betti-0 + Betti-1))
    - Entropy collapse detection
    - Void depth for crisis detection
    - Momentum sign for directional classification
    
    Features:
    - No look-ahead bias (rolling windows only)
    - Deterministic under replay
    - Timestamp monotonicity enforced
    - Configurable thresholds
    - Regime history with confidence tracking
    - Exponential smoothing for confidence updates (applied only to active regime)
    - Transition cooldown prevents rapid oscillation
    """
    
    def __init__(
        self,
        window_size: int = 50,
        coherence_threshold_trending: float = 0.6,
        coherence_threshold_ranging_upper: float = 0.6,
        coherence_threshold_ranging_lower: float = 0.4,
        crisis_void_threshold: float = 0.7,
        min_samples: int = 20,
        transition_cooldown_ns: int = 60_000_000_000,  # 60 seconds
        confidence_smoothing_alpha: float = 0.3
    ):
        """
        Initialize regime detector.
        
        Args:
            window_size: Rolling window for feature aggregation
            coherence_threshold_trending: Coherence threshold for trending regime
            coherence_threshold_ranging_upper: Upper coherence bound for ranging
            coherence_threshold_ranging_lower: Lower coherence bound for ranging
            crisis_void_threshold: Void depth threshold for crisis classification
            min_samples: Minimum samples before making predictions
            transition_cooldown_ns: Minimum time between regime transitions
            confidence_smoothing_alpha: EMA alpha for confidence updates (0-1)
        """
        self.window_size = window_size
        self.coherence_threshold_trending = coherence_threshold_trending
        self.coherence_threshold_ranging_upper = coherence_threshold_ranging_upper
        self.coherence_threshold_ranging_lower = coherence_threshold_ranging_lower
        self.crisis_void_threshold = crisis_void_threshold
        self.min_samples = min_samples
        self.transition_cooldown_ns = transition_cooldown_ns
        self.confidence_smoothing_alpha = confidence_smoothing_alpha
        
        # Feature history (rolling window)
        self._coherence_history: deque = deque(maxlen=window_size)
        self._entropy_history: deque = deque(maxlen=window_size)
        self._void_score_history: deque = deque(maxlen=window_size)
        
        # Timestamp history for monotonicity validation
        self._last_timestamp_ns: Optional[int] = None
        
        # Regime state
        self._state = RegimeState()
        self._history: deque = deque(maxlen=1000)
        self._last_transition_ns: int = 0
        self._candidate_regime: Optional[RegimeType] = None
        self._candidate_confidence: float = 0.0
        
        logger.info(
            f"RegimeDetector initialized: window={window_size}, "
            f"trending_threshold={coherence_threshold_trending}, "
            f"crisis_void_threshold={crisis_void_threshold}, "
            f"smoothing_alpha={confidence_smoothing_alpha}"
        )
    
    # ============================================
    # Main Update Entry Point
    # ============================================
    
    def update(
        self,
        feature_vector: FeatureVector,
        exchange_ts_ns: Optional[int] = None
    ) -> RegimeType:
        """
        Update regime detector with new feature vector.
        
        Args:
            feature_vector: Current feature vector from brain
            exchange_ts_ns: Exchange timestamp (optional, uses feature timestamp)
        
        Returns:
            Current regime type
        
        Raises:
            RegimeDetectorError: On invalid input or stale timestamp
        """
        timestamp_ns = exchange_ts_ns or feature_vector.timestamp_ns
        
        # Validate timestamp monotonicity
        if self._last_timestamp_ns is not None:
            valid, reason = is_monotonic(self._last_timestamp_ns, timestamp_ns)
            if not valid:
                raise RegimeDetectorError(
                    f"Non-monotonic timestamp: {reason}. "
                    f"Last={self._last_timestamp_ns}, current={timestamp_ns}"
                )
        
        self._last_timestamp_ns = timestamp_ns
        
        # Extract features from FeatureVector
        features = feature_vector.features
        
        # Safely extract feature values (handle both dataclass and dict)
        if hasattr(features, '__dict__'):
            # Dataclass style
            coherence = getattr(features, 'topological_coherence', None)
            entropy = getattr(features, 'entropy', None)
            entropy_collapsed = getattr(features, 'entropy_collapsed', False)
            void_score = getattr(features, 'void_depth', None)
            momentum_sign = getattr(features, 'momentum_sign', None)
        else:
            # Dict style
            coherence = features.get('topological_coherence')
            entropy = features.get('entropy')
            entropy_collapsed = features.get('entropy_collapsed', False)
            void_score = features.get('void_depth')
            momentum_sign = features.get('momentum_sign')
        
        # Convert to float where possible
        coherence_val = float(coherence) if coherence is not None else 0.5
        entropy_val = float(entropy) if entropy is not None else 0.5
        void_val = float(void_score) if void_score is not None else 0.0
        momentum_val = float(momentum_sign) if momentum_sign is not None else 0.0
        
        # Store in rolling history
        self._coherence_history.append(coherence_val)
        self._entropy_history.append(entropy_val)
        self._void_score_history.append(void_val)
        
        # Need enough samples for reliable detection
        if len(self._coherence_history) < self.min_samples:
            return self._state.regime
        
        # Detect candidate regime based on features
        candidate_regime, raw_confidence = self._detect_regime(
            coherence_val=coherence_val,
            entropy_val=entropy_val,
            entropy_collapsed=entropy_collapsed,
            void_val=void_val,
            momentum_val=momentum_val
        )
        
        # Store candidate for potential transition
        self._candidate_regime = candidate_regime
        self._candidate_confidence = raw_confidence
        
        # Determine if transition is allowed
        transition_allowed = (candidate_regime != self._state.regime and
                              timestamp_ns - self._last_transition_ns >= self.transition_cooldown_ns)
        
        if transition_allowed:
            # Transition to new regime
            self._state.regime = candidate_regime
            self._state.confidence = raw_confidence
            self._state.transition_count += 1
            self._last_transition_ns = timestamp_ns
            logger.info(
                f"Regime transition: {_safe_str(self._state.regime)} -> "
                f"{_safe_str(candidate_regime)} (confidence={self._state.confidence:.2f})"
            )
        else:
            # No transition: update confidence for current regime
            if candidate_regime == self._state.regime:
                # Same regime: apply EMA smoothing
                alpha = self.confidence_smoothing_alpha
                self._state.confidence = (alpha * raw_confidence) + ((1 - alpha) * self._state.confidence)
                self._state.confidence = max(0.0, min(1.0, self._state.confidence))
            else:
                # Different regime but transition blocked by cooldown
                # Keep current regime, optionally decay confidence slightly
                # to reflect uncertainty from blocked transition
                if self._state.confidence > 0.5:
                    self._state.confidence = max(0.3, self._state.confidence * 0.95)
                logger.debug(
                    f"Regime transition blocked: {_safe_str(self._state.regime)} -> "
                    f"{_safe_str(candidate_regime)} blocked by cooldown "
                    f"(remaining={self.transition_cooldown_ns - (timestamp_ns - self._last_transition_ns)}ns)"
                )
        
        self._state.timestamp_ns = timestamp_ns
        self._state.last_update_ns = timestamp_ns
        self._state.stability_score = self._calculate_stability()
        
        # Store history with active regime and its confidence
        self._history.append(RegimeHistoryEntry(
            timestamp_ns=timestamp_ns,
            regime=self._state.regime,
            confidence=self._state.confidence,
            features={
                "coherence": coherence_val,
                "entropy": entropy_val,
                "void_score": void_val,
                "entropy_collapsed": entropy_collapsed,
                "momentum_sign": momentum_val,
                "candidate_regime": _safe_str(candidate_regime),
                "candidate_confidence": raw_confidence
            }
        ))
        
        return self._state.regime
    
    # ============================================
    # Regime Detection Logic
    # ============================================
    
    def _detect_regime(
        self,
        coherence_val: float,
        entropy_val: float,
        entropy_collapsed: bool,
        void_val: float,
        momentum_val: float
    ) -> Tuple[RegimeType, float]:
        """
        Detect regime based on current features.
        
        Stage 3: Heuristic detection rules:
        - CRISIS: high void score OR entropy collapsed with low coherence
        - TRENDING_BULL: high coherence AND positive momentum
        - TRENDING_BEAR: high coherence AND negative momentum
        - RANGING: moderate coherence
        - UNKNOWN: insufficient confidence
        
        Directional classification uses momentum_sign from FeatureVector.
        
        Args:
            coherence_val: Topological coherence score (0-1)
            entropy_val: Entropy score (0-1)
            entropy_collapsed: Whether entropy is collapsed
            void_val: Void depth score (0-1)
            momentum_val: Momentum sign (-1 to 1, positive = bullish)
        
        Returns:
            Tuple of (RegimeType, confidence)
        """
        # CRISIS detection (highest priority)
        if void_val > self.crisis_void_threshold:
            confidence = min(0.95, void_val + 0.2)
            return RegimeType.CRISIS, confidence
        
        if entropy_collapsed and coherence_val < 0.5:
            return RegimeType.CRISIS, 0.85
        
        # TRENDING detection (direction determined by momentum)
        if coherence_val > self.coherence_threshold_trending:
            confidence = min(0.9, coherence_val + 0.2)
            
            # Directional classification
            if momentum_val > 0.1:
                return RegimeType.TRENDING_BULL, confidence
            elif momentum_val < -0.1:
                return RegimeType.TRENDING_BEAR, confidence
            else:
                # Low momentum, trending structure but no clear direction
                # Default to UNKNOWN until momentum clarifies
                return RegimeType.UNKNOWN, confidence * 0.5
        
        # RANGING detection
        if (self.coherence_threshold_ranging_lower <= coherence_val <= self.coherence_threshold_ranging_upper and
            0.3 <= entropy_val <= 0.7):
            return RegimeType.RANGING, 0.6
        
        # Default to UNKNOWN
        return RegimeType.UNKNOWN, 0.3
    
    def _calculate_stability(self) -> float:
        """
        Calculate regime stability based on recent history.
        
        Returns:
            Stability score (0-1, higher = more stable)
        """
        if len(self._history) < self.min_samples:
            return 0.5
        
        # Count recent transitions
        recent_entries = list(self._history)[-self.window_size:]
        transitions = 0
        prev_regime = None
        
        for entry in recent_entries:
            if prev_regime is not None and entry.regime != prev_regime:
                transitions += 1
            prev_regime = entry.regime
        
        # Stability = 1 - (transitions / possible)
        max_transitions = len(recent_entries) - 1
        if max_transitions > 0:
            stability = 1.0 - (transitions / max_transitions)
        else:
            stability = 1.0
        
        return max(0.0, min(1.0, stability))
    
    # ============================================
    # Query Methods
    # ============================================
    
    def get_current_regime(self) -> RegimeType:
        """Get current regime."""
        return self._state.regime
    
    def get_current_confidence(self) -> float:
        """Get confidence in current regime."""
        return self._state.confidence
    
    def get_candidate_regime(self) -> Optional[RegimeType]:
        """Get candidate regime from most recent detection."""
        return self._candidate_regime
    
    def get_candidate_confidence(self) -> float:
        """Get confidence of candidate regime."""
        return self._candidate_confidence
    
    def get_regime_history(self, count: int = 100) -> List[Dict[str, Any]]:
        """
        Get recent regime history.
        
        Args:
            count: Number of entries to return
        
        Returns:
            List of regime history entries
        """
        entries = list(self._history)[-count:]
        return [
            {
                "timestamp_ns": e.timestamp_ns,
                "regime": _safe_str(e.regime),
                "confidence": e.confidence,
                "features": e.features
            }
            for e in entries
        ]
    
    def get_regime_stability(self) -> float:
        """Get current regime stability score."""
        return self._state.stability_score
    
    def get_stats(self) -> Dict[str, Any]:
        """Get detector statistics."""
        return {
            "current_regime": _safe_str(self._state.regime),
            "confidence": self._state.confidence,
            "candidate_regime": _safe_str(self._candidate_regime) if self._candidate_regime else None,
            "candidate_confidence": self._candidate_confidence,
            "stability": self._state.stability_score,
            "transition_count": self._state.transition_count,
            "history_length": len(self._history),
            "window_size": self.window_size,
            "samples_available": len(self._coherence_history),
            "min_samples": self.min_samples,
            "last_update_ns": self._state.last_update_ns
        }
    
    # ============================================
    # Reset
    # ============================================
    
    def reset(self) -> None:
        """Reset regime detector state."""
        self._coherence_history.clear()
        self._entropy_history.clear()
        self._void_score_history.clear()
        self._history.clear()
        self._state = RegimeState()
        self._last_transition_ns = 0
        self._last_timestamp_ns = None
        self._candidate_regime = None
        self._candidate_confidence = 0.0
        logger.info("RegimeDetector reset")


# ============================================
# Convenience Functions
# ============================================

def create_regime_detector(
    window_size: int = 50,
    coherence_threshold_trending: float = 0.6,
    crisis_void_threshold: float = 0.7
) -> RegimeDetector:
    """
    Create a configured regime detector.
    
    Args:
        window_size: Rolling window for feature aggregation
        coherence_threshold_trending: Coherence threshold for trending regime
        crisis_void_threshold: Void depth threshold for crisis classification
    
    Returns:
        RegimeDetector instance
    """
    return RegimeDetector(
        window_size=window_size,
        coherence_threshold_trending=coherence_threshold_trending,
        crisis_void_threshold=crisis_void_threshold
    )


__all__ = [
    'RegimeDetector',
    'RegimeDetectorError',
    'RegimeState',
    'RegimeHistoryEntry',
    'create_regime_detector',
]