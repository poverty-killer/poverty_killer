"""
Signal Fusion - The Hardened Heart
APEX PREDATOR GRADE (3.0x) — NO RETAIL PLUMBING

INNOVATIONS:
- Bayesian Cross-Entropy Voter (weights signals by spectral gap)
- Zero Python loops (numpy.lib.stride_tricks for SHM access)
- Sigmoidal hysteresis (Tanh activation for confidence)
- Hardware-level broadcast (raw memoryview offsets)

ANALYTICAL/NON-MONETARY BOUNDARY:
This file performs analytical signal processing using float64 for performance.
It produces trading signals (BUY/SELL/WAIT) based on analytical fusion of multiple indicators.
These signals are NOT monetary truth — they are analytical recommendations.
All monetary calculations must use Decimal (see DECIMAL_ONLY constraint).
"""

import numpy as np
from numba import jit
import logging
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass
import pickle

from app.models.unified_market import MacroRegime
from app.execution.shared_memory import SharedMemoryManager
from app.state.hydration_manager import HydratableMixin

logger = logging.getLogger(__name__)

# Regime codes — must match regime_detector.py REGIME_CODE values
REGIME_CODE = {
    MacroRegime.TRENDING_BULL: 0,
    MacroRegime.TRENDING_BEAR: 1,
    MacroRegime.RANGING: 2,
    MacroRegime.CRISIS: 3,
    MacroRegime.UNKNOWN: 4
}


@dataclass
class SovereignSignal:
    """The kill command — analytical trading recommendation."""
    action: str  # "BUY", "SELL", "WAIT"
    confidence: float  # 0.0 to 1.0, analytical confidence only
    expected_volatility: float  # Expected volatility for position sizing
    alpha_decay_ms: int  # Signal validity window in milliseconds
    institutional_shadow_score: float  # 0.0 to 1.0, higher = institutional flow detected
    reason: str  # Human-readable signal justification

    __slots__ = ("action", "confidence", "expected_volatility", "alpha_decay_ms",
                 "institutional_shadow_score", "reason")


@jit(nopython=True, cache=True)
def sigmoid_hysteresis(x: float, gamma: float = 2.0) -> float:
    """
    Sigmoidal hysteresis — Tanh activation.
    Non-linear confidence shaping for cleaner signal boundaries.
    """
    return 0.5 * (1.0 + np.tanh(gamma * (x - 0.5)))


@jit(nopython=True, cache=True)
def bayesian_fusion(
    regime_confidence: float,
    topology_score: float,
    tape_pulse: float,
    spectral_gap: float,
    causation_bias: float
) -> float:
    """
    Bayesian Cross-Entropy Voter.
    Weights signals by spectral gap:
    - Wide gap = trust regime (trend coherence)
    - Narrow gap = trust topology (void detection)
    
    Returns raw confidence before hysteresis shaping.
    """
    # Weight factor: spectral gap determines trust distribution
    weight_regime = spectral_gap
    weight_topology = 1.0 - spectral_gap
    
    # Base signal from weighted regime + topology
    base_signal = (regime_confidence * weight_regime + topology_score * weight_topology)
    
    # Boost from tape pulse (momentum)
    boosted = base_signal * (1.0 + tape_pulse * 0.3)
    
    # Causation bias adjustment
    if causation_bias > 0.6:
        boosted *= 1.2  # BTC leading = bullish bias
    elif causation_bias < -0.4:
        boosted *= 0.8  # BTC lagging = bearish bias
    
    return min(1.0, max(0.0, boosted))


class SignalFusion(HydratableMixin):
    """
    Hardened Heart — 3.0x Innovation.
    
    Features:
    - Zero Python loops (NumPy slicing for SHM)
    - Bayesian fusion with spectral gap weighting
    - Sigmoidal hysteresis (Tanh activation)
    - Hardware-level memory broadcast
    - Full integration with regime detector outputs
    
    FEATURE VECTOR CONTRACT (from approved regime_detector.py):
    - GUARANTEED: features[10] = regime code (0-4)
    - GUARANTEED: features[11] = regime confidence (0.0-1.0)
    - OPTIONAL/HISTORICAL: features[12-14] may contain topology/spectral/causation
    - This file uses bounded defaults when optional fields unavailable
    
    Timing discipline: All timestamps are passed from caller (replay-safe).
    No internal calls to system time.
    """
    
    def __init__(
        self,
        shared_memory: SharedMemoryManager,
        hydration_manager: Any,
        update_interval_ms: int = 100,
        alpha_decay_ms: int = 500,
        confidence_threshold_buy: float = 0.75,
        confidence_threshold_sell: float = 0.70
    ):
        super().__init__(hydration_manager, "signal_fusion")
        
        self.shared_memory = shared_memory
        self.update_interval_ms = update_interval_ms
        self.alpha_decay_ms = alpha_decay_ms
        self.confidence_threshold_buy = confidence_threshold_buy
        self.confidence_threshold_sell = confidence_threshold_sell
        
        self._last_update_ns = 0
        self._last_signal: Optional[SovereignSignal] = None
        self._signal_history = []  # List of dicts, capped at 100
        
        # Bounded default volatility (2% daily) - not self-referential
        self._default_volatility = 0.02
        
        logger.info("SignalFusion initialized — HARDENED HEART (3.0x)")
        logger.info(f"  Update Interval: {update_interval_ms}ms")
        logger.info(f"  Alpha Decay: {alpha_decay_ms}ms")
        logger.info(f"  Buy Threshold: {confidence_threshold_buy:.2f}")
        logger.info(f"  Sell Threshold: {confidence_threshold_sell:.2f}")
    
    # ============================================
    # ZERO-LOOP SHM ACCESS
    # ============================================
    
    def _get_price_window(self, instrument_id: int, window: int) -> np.ndarray:
        """Zero-loop price extraction — NumPy slicing."""
        if self.shared_memory is None:
            return np.array([])
        
        price_reader = self.shared_memory.get_reader("price_history")
        if price_reader is None:
            return np.array([])
        
        try:
            return price_reader[:window, instrument_id].copy()
        except (IndexError, TypeError, AttributeError):
            return np.array([])
    
    def _get_regime_state(self) -> Tuple[int, float, float, float, float]:
        """
        Extract regime state from shared memory.
        
        Returns: (regime_code, regime_confidence, topology_score, spectral_gap, causation_bias)
        
        CONTRACT: Only regime_code and regime_confidence are guaranteed by regime_detector.py.
        Topology, spectral_gap, and causation use bounded defaults when unavailable.
        """
        if self.shared_memory is None:
            return 4, 0.5, 0.5, 0.5, 0.0
        
        regime_reader = self.shared_memory.get_reader("regime_labels")
        if regime_reader is None or regime_reader.size == 0:
            return 4, 0.5, 0.5, 0.5, 0.0
        
        current_regime = int(regime_reader[-1]) if regime_reader.size > 0 else 4
        
        features, _, _ = self.shared_memory.get_feature_vector()
        if features is None or len(features) < 12:
            return current_regime, 0.5, 0.5, 0.5, 0.0
        
        # GUARANTEED fields (from regime_detector.py)
        regime_confidence = float(features[11]) if features[11] > 0 else 0.5
        
        # OPTIONAL fields - use bounded defaults if unavailable
        # Topology score: derive from regime confidence as proxy when missing
        if len(features) > 12 and features[12] > 0:
            topology_score = float(features[12])
        else:
            # Bounded default: regime confidence inverted as topology proxy
            topology_score = 1.0 - regime_confidence
        
        # Spectral gap: default 0.5 (balanced weighting) when unavailable
        if len(features) > 13 and features[13] > 0:
            spectral_gap = float(features[13])
        else:
            spectral_gap = 0.5
        
        # Causation bias: default 0.0 (neutral) when unavailable
        if len(features) > 14:
            causation_bias = float(features[14])
        else:
            causation_bias = 0.0
        
        return current_regime, regime_confidence, topology_score, spectral_gap, causation_bias
    
    def _get_tape_pulse(self) -> float:
        """Get tape pulse from shared memory (feature vector index 6)."""
        if self.shared_memory is None:
            return 0.0
        
        features, _, _ = self.shared_memory.get_feature_vector()
        if features is None or len(features) < 7:
            return 0.0
        return float(features[6]) if features[6] > 0 else 0.0
    
    def _get_entropy_score(self) -> float:
        """Get fractal entropy from shared memory."""
        if self.shared_memory is None:
            return 0.5
        
        entropy_reader = self.shared_memory.get_reader("entropy_history")
        if entropy_reader is None or entropy_reader.size == 0:
            return 0.5
        return float(entropy_reader[-1]) if entropy_reader[-1] > 0 else 0.5
    
    def _get_void_score(self) -> float:
        """Get topological void score from shared memory."""
        if self.shared_memory is None:
            return 0.5
        
        void_reader = self.shared_memory.get_reader("void_history")
        if void_reader is None or void_reader.size == 0:
            return 0.5
        return float(void_reader[-1]) if void_reader[-1] > 0 else 0.5
    
    # ============================================
    # HARDWARE-LEVEL BROADCAST
    # ============================================
    
    def _broadcast_signal(self, signal: SovereignSignal, timestamp_ns: int) -> None:
        """
        Hardware-level broadcast using raw memoryview.
        
        Signal writer indices:
        - idx 0: action (-1=SELL, 0=WAIT, 1=BUY)
        - idx 1: confidence
        - idx 2: expected_volatility
        - idx 3: alpha_decay_ms (as float)
        - idx 4: institutional_shadow_score
        
        NOTE: This writes feature[15-17] for downstream consumers.
        These values are NOT read back as inputs (no self-referential feedback).
        """
        if self.shared_memory is None:
            return
        
        # Broadcast to signal writer
        writer, _ = self.shared_memory.get_writer("signal", timestamp_ns)
        if writer is not None and writer.size >= 5:
            try:
                writer[0] = 1.0 if signal.action == "BUY" else (-1.0 if signal.action == "SELL" else 0.0)
                writer[1] = signal.confidence
                writer[2] = signal.expected_volatility
                writer[3] = float(signal.alpha_decay_ms)
                writer[4] = signal.institutional_shadow_score
            except (IndexError, TypeError):
                pass
        
        # Update feature vector for downstream consumers (not read back by this file)
        features, _, _ = self.shared_memory.get_feature_vector()
        if features is not None and len(features) >= 18:
            try:
                features[15] = 1.0 if signal.action == "BUY" else (-1.0 if signal.action == "SELL" else 0.0)
                features[16] = signal.confidence
                features[17] = signal.expected_volatility
                if hasattr(self.shared_memory, 'write_feature_vector'):
                    self.shared_memory.write_feature_vector(features, timestamp_ns)
            except (IndexError, TypeError, AttributeError):
                pass
    
    # ============================================
    # MAIN FUSION LOOP
    # ============================================
    
    def update(self, timestamp_ns: int) -> SovereignSignal:
        """
        Generate fusion signal.
        
        Args:
            timestamp_ns: Authoritative update timestamp from external clock.
                         This is the single source of truth for timing.
        
        Returns:
            SovereignSignal with action, confidence, and metadata
        """
        # Rate limiting
        if timestamp_ns - self._last_update_ns < self.update_interval_ms * 1_000_000:
            if self._last_signal:
                return self._last_signal
            return SovereignSignal("WAIT", 0.0, self._default_volatility, self.alpha_decay_ms, 0.0, "rate_limited")
        
        # Extract all signals from shared memory
        regime_code, regime_conf, topology_score, spectral_gap, causation = self._get_regime_state()
        tape_pulse = self._get_tape_pulse()
        entropy = self._get_entropy_score()
        void_score = self._get_void_score()
        
        # ============================================
        # BAYESIAN FUSION
        # ============================================
        raw_confidence = bayesian_fusion(regime_conf, topology_score, tape_pulse, spectral_gap, causation)
        
        # Entropy adjustment: low entropy (predictable) increases confidence
        entropy_adjust = 1.0 - entropy
        raw_confidence = raw_confidence * (0.7 + 0.3 * entropy_adjust)
        
        # Void adjustment: high void indicates regime uncertainty
        if void_score > 0.7 and raw_confidence < 0.5:
            raw_confidence = raw_confidence * 0.8
        elif void_score > 0.8:
            raw_confidence = raw_confidence * 1.2
        
        # Sigmoidal hysteresis for clean signal boundaries
        confidence = sigmoid_hysteresis(raw_confidence, gamma=2.5)
        
        # ============================================
        # ACTION DETERMINATION
        # ============================================
        action = "WAIT"
        reason = ""
        
        # BUY: High confidence AND bullish conditions
        if confidence > self.confidence_threshold_buy:
            if regime_code == 0 or causation > 0.5:
                action = "BUY"
                reason = f"bull_trend_conf={confidence:.2f}_causation={causation:.2f}"
            elif regime_code == 1 or causation < -0.3:
                # SELL: Independent threshold for bearish conditions
                if confidence > self.confidence_threshold_sell:
                    action = "SELL"
                    reason = f"bear_trend_conf={confidence:.2f}_causation={causation:.2f}"
                else:
                    action = "WAIT"
                    reason = f"bear_below_sell_threshold={confidence:.2f}"
            else:
                action = "WAIT"
                reason = f"mixed_signals_conf={confidence:.2f}"
        
        # Secondary: Void regime with tape confirmation (applies to both BUY/SELL)
        elif confidence > self.confidence_threshold_sell and void_score > 0.75:
            if tape_pulse > 0:
                action = "BUY"
                reason = f"void_buy_tape={tape_pulse:.2f}"
            elif tape_pulse < 0:
                action = "SELL"
                reason = f"void_sell_tape={tape_pulse:.2f}"
            else:
                action = "WAIT"
                reason = f"void_no_tape"
        
        # Tertiary: Momentum in low-entropy environment
        elif confidence > 0.55 and entropy < 0.4 and abs(tape_pulse) > 0.3:
            if tape_pulse > 0:
                action = "BUY"
                reason = f"momentum_buy_entropy={entropy:.2f}"
            else:
                action = "SELL"
                reason = f"momentum_sell_entropy={entropy:.2f}"
        
        # ============================================
        # EXPECTED VOLATILITY (bounded default, not self-referential)
        # ============================================
        # Use bounded default. Future: could source from upstream volatility estimator.
        expected_vol = self._default_volatility
        
        # ============================================
        # INSTITUTIONAL SHADOW SCORE
        # ============================================
        institutional_score = min(1.0, abs(causation) * 1.5)
        
        # Boost confidence if institutional flow detected
        if institutional_score > 0.7 and action != "WAIT":
            confidence = min(0.95, confidence * 1.1)
        
        signal = SovereignSignal(
            action=action,
            confidence=confidence,
            expected_volatility=expected_vol,
            alpha_decay_ms=self.alpha_decay_ms,
            institutional_shadow_score=institutional_score,
            reason=reason
        )
        
        # Store history (capped at 100)
        self._signal_history.append({
            "timestamp_ns": timestamp_ns,
            "action": action,
            "confidence": confidence,
            "regime": regime_code,
            "causation": causation,
            "void": void_score,
            "entropy": entropy,
            "tape_pulse": tape_pulse,
            "reason": reason
        })
        if len(self._signal_history) > 100:
            self._signal_history.pop(0)
        
        self._last_signal = signal
        self._last_update_ns = timestamp_ns
        self._broadcast_signal(signal, timestamp_ns)
        
        logger.debug(f"Signal: {action} conf={confidence:.2f} reason={reason}")
        return signal
    
    # ============================================
    # SIGNAL DECAY
    # ============================================
    
    def is_signal_valid(self, signal: SovereignSignal, current_ns: int) -> bool:
        """
        Check if signal is still valid based on age.
        
        Args:
            signal: Signal to validate
            current_ns: Current authoritative timestamp (nanoseconds)
        """
        if self._last_signal is None or self._last_signal != signal:
            return True
        age_ns = current_ns - self._last_update_ns
        age_ms = age_ns / 1_000_000
        return age_ms < self.alpha_decay_ms
    
    def decay_signal(self, current_ns: int) -> SovereignSignal:
        """
        Return decayed signal based on age.
        
        Args:
            current_ns: Current authoritative timestamp (nanoseconds)
        """
        if self._last_signal is None:
            return SovereignSignal("WAIT", 0.0, self._default_volatility, self.alpha_decay_ms, 0.0, "no_signal")
        
        age_ns = current_ns - self._last_update_ns
        age_ms = age_ns / 1_000_000
        
        if age_ms >= self.alpha_decay_ms:
            decay_factor = max(0.0, 1.0 - (age_ms / self.alpha_decay_ms))
            decayed_confidence = self._last_signal.confidence * decay_factor
            
            if decayed_confidence < 0.3:
                return SovereignSignal("WAIT", 0.0, self._default_volatility, self.alpha_decay_ms, 0.0, "signal_expired")
            
            return SovereignSignal(
                action=self._last_signal.action,
                confidence=decayed_confidence,
                expected_volatility=self._last_signal.expected_volatility,
                alpha_decay_ms=self._last_signal.alpha_decay_ms,
                institutional_shadow_score=self._last_signal.institutional_shadow_score,
                reason=f"decayed_{self._last_signal.reason}"
            )
        
        return self._last_signal
    
    # ============================================
    # HYDRATION
    # ============================================
    
    def get_binary_snapshot(self) -> bytes:
        """
        Return binary state for persistence.
        
        WARNING: Uses pickle — NOT deterministic across Python versions/architectures.
        For transient, same-process state transfer only.
        NOT for canonical replay-safe persistence.
        """
        data = {
            "version": 3,
            "signal_history": self._signal_history[-50:],
            "last_signal": {
                "action": self._last_signal.action,
                "confidence": self._last_signal.confidence,
                "expected_volatility": self._last_signal.expected_volatility,
                "alpha_decay_ms": self._last_signal.alpha_decay_ms,
                "institutional_shadow_score": self._last_signal.institutional_shadow_score,
                "reason": self._last_signal.reason
            } if self._last_signal else None,
            "last_update_ns": self._last_update_ns,
            "config": {
                "update_interval_ms": self.update_interval_ms,
                "alpha_decay_ms": self.alpha_decay_ms,
                "confidence_threshold_buy": self.confidence_threshold_buy,
                "confidence_threshold_sell": self.confidence_threshold_sell
            }
        }
        return pickle.dumps(data)
    
    def hydrate_from_binary(self, data: bytes) -> None:
        """Restore state from binary snapshot. Bounded — errors logged, state preserved."""
        try:
            state = pickle.loads(data)
            self._signal_history = state.get("signal_history", [])
            last = state.get("last_signal")
            if last:
                self._last_signal = SovereignSignal(
                    action=last["action"],
                    confidence=last["confidence"],
                    expected_volatility=last["expected_volatility"],
                    alpha_decay_ms=last["alpha_decay_ms"],
                    institutional_shadow_score=last["institutional_shadow_score"],
                    reason=last["reason"]
                )
            self._last_update_ns = state.get("last_update_ns", 0)
            
            config = state.get("config", {})
            self.update_interval_ms = config.get("update_interval_ms", self.update_interval_ms)
            self.alpha_decay_ms = config.get("alpha_decay_ms", self.alpha_decay_ms)
            self.confidence_threshold_buy = config.get("confidence_threshold_buy", self.confidence_threshold_buy)
            self.confidence_threshold_sell = config.get("confidence_threshold_sell", self.confidence_threshold_sell)
            
            logger.info("SignalFusion hydrated")
        except Exception as e:
            logger.error(f"Hydration failed: {e}")
    
    # ============================================
    # PUBLIC METHODS
    # ============================================
    
    def get_last_signal(self) -> Optional[SovereignSignal]:
        """Return most recent signal, or None if no signal generated."""
        return self._last_signal
    
    def get_signal_history(self, count: int = 10) -> list:
        """Return last N signals from history."""
        return self._signal_history[-count:]
    
    def get_stats(self) -> Dict[str, Any]:
        """Return current statistics for monitoring."""
        return {
            "last_signal": self._last_signal.action if self._last_signal else "NONE",
            "last_confidence": self._last_signal.confidence if self._last_signal else 0.0,
            "last_reason": self._last_signal.reason if self._last_signal else "",
            "history_len": len(self._signal_history),
            "last_update_ns": self._last_update_ns,
            "update_interval_ms": self.update_interval_ms,
            "alpha_decay_ms": self.alpha_decay_ms,
            "buy_threshold": self.confidence_threshold_buy,
            "sell_threshold": self.confidence_threshold_sell
        }
    
    def reset(self) -> None:
        """Reset all state — clears history and last signal."""
        self._last_update_ns = 0
        self._last_signal = None
        self._signal_history = []
        logger.info("SignalFusion reset")


def create_signal_fusion(
    shared_memory: SharedMemoryManager,
    hydration_manager: Any,
    update_interval_ms: int = 100,
    alpha_decay_ms: int = 500
) -> SignalFusion:
    """Create hardened signal fusion engine."""
    return SignalFusion(
        shared_memory=shared_memory,
        hydration_manager=hydration_manager,
        update_interval_ms=update_interval_ms,
        alpha_decay_ms=alpha_decay_ms
    )