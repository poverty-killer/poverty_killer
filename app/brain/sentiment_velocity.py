"""
Sentiment Velocity Engine - Macro-Overlay for Institutional Context
CITADEL GRADE — DETERMINISTIC · REPLAY-SAFE · NO WALL-CLOCK

ANALYTICAL/NON-MONETARY BOUNDARY:
This file performs analytical signal processing using float64 for performance.
It tracks velocity and acceleration of sentiment state as analytical inputs.
These are NOT monetary truth or trade execution signals.
All monetary calculations must use Decimal (see DECIMAL_ONLY constraint).

DETERMINISTIC BEHAVIOR:
- No wall-clock time (datetime.utcnow, timedelta)
- No random number generation
- All timing uses integer nanoseconds from authoritative external sources
- Outputs are deterministic given identical sentiment/timestamp sequences
- State transitions are fully replay-safe
- Monotonic timestamp enforcement prevents temporal inconsistencies

PURE ANALYTICAL ENGINE:
This engine measures CHANGE in sentiment state over time:
- First derivative (velocity) - rate of sentiment change
- Second derivative (acceleration) - rate of velocity change
- Impulse detection - sudden sentiment shocks
- Divergence - level vs momentum dislocations
- Reversion pressure - mean reversion tendency
- Stability score - consistency of sentiment state
"""

import threading
import numpy as np
import logging
from typing import Dict, Optional, Tuple, Any
from dataclasses import dataclass
from collections import deque

logger = logging.getLogger(__name__)

# Numerical stability epsilon
EPS = np.finfo(float).eps


@dataclass
class SentimentPoint:
    """Single sentiment observation with authoritative timestamp."""
    value: float  # Sentiment value, typically -1.0 to 1.0
    timestamp_ns: int  # Authoritative nanosecond timestamp


@dataclass
class SentimentVector:
    """
    Complete sentiment state vector with derivatives.
    
    All values are analytical estimates, not monetary truth.
    """
    level: float  # Current sentiment level (-1 to 1)
    velocity: float  # First derivative (change per second)
    acceleration: float  # Second derivative (velocity change per second)
    impulse: float  # Recent shock magnitude (0-1)
    divergence: float  # Level-velocity dislocation (0-1)
    reversion_pressure: float  # Mean reversion tendency (0-1)
    stability: float  # Consistency of recent sentiment (0-1)
    confidence: float  # Analytical confidence in estimates (0-1)
    timestamp_ns: int  # Authoritative timestamp for this vector


@dataclass
class MacroSignal:
    """
    Macro-overlay safety signal derived from sentiment velocity.
    
    Used to override microstructure signals during extreme sentiment events.
    """
    macro_pause: bool  # Increase confidence threshold temporarily
    macro_kill: bool  # Halt new entries temporarily
    bull_trap_detected: bool  # Public sentiment bullish but velocity collapsing
    divergence_score: float  # 0-1, higher = more level-velocity divergence
    confidence_boost: float  # 0-0.15, additive to min_confidence
    halt_seconds: int  # Seconds to halt if macro_kill
    reason: str


class SentimentVelocityEngine:
    """
    Deterministic sentiment velocity engine.
    
    Tracks sentiment state and its derivatives over time.
    Detects sentiment shocks, divergences, and regime changes.
    
    TIMING AUTHORITY:
    - All timestamps must be provided by external authoritative source
    - No internal time generation
    - If timestamp is missing or invalid, degrade honestly
    - Monotonic timestamps required: incoming timestamp must be > last timestamp
    
    INPUT HONESTY:
    - This engine receives pre-computed sentiment values
    - Does NOT ingest raw text or social media
    - Does NOT pretend to have live news feeds
    - Sentiment values are analytical inputs only
    """
    
    def __init__(
        self,
        history_maxlen: int = 1000,
        velocity_window_ns: int = 60_000_000_000,  # 60 seconds in nanoseconds
        acceleration_window_ns: int = 120_000_000_000,  # 120 seconds
        impulse_threshold: float = 0.5,  # Sentiment change threshold for impulse detection
        divergence_threshold: float = 0.7,  # Level-velocity divergence threshold
        velocity_z_threshold: float = 2.0,  # Standard deviations for macro-pause
        kill_z_threshold: float = 3.0,  # Standard deviations for macro-kill
        macro_pause_boost: float = 0.15,  # Confidence boost on macro-pause
        macro_kill_seconds: int = 30,  # Seconds to halt on macro-kill
        min_history_points: int = 5,  # Minimum points for derivative calculation
        decay_half_life_ns: int = 300_000_000_000,  # 5 minutes decay half-life
        stability_window_ns: int = 300_000_000_000  # 5 minutes for stability calc
    ):
        """
        Initialize sentiment velocity engine with deterministic parameters.
        
        Args:
            history_maxlen: Maximum number of historical points to retain
            velocity_window_ns: Window for velocity calculation in nanoseconds
            acceleration_window_ns: Window for acceleration calculation
            impulse_threshold: Sentiment change threshold for impulse detection
            divergence_threshold: Score threshold for level-velocity divergence
            velocity_z_threshold: Z-score threshold for macro-pause
            kill_z_threshold: Z-score threshold for macro-kill
            macro_pause_boost: Confidence boost when macro-pause triggered
            macro_kill_seconds: Seconds to halt trading on macro-kill
            min_history_points: Minimum points for derivative calculation
            decay_half_life_ns: Half-life for exponential decay of historical weights
            stability_window_ns: Window for stability score calculation
        """
        self.history_maxlen = history_maxlen
        self.velocity_window_ns = velocity_window_ns
        self.acceleration_window_ns = acceleration_window_ns
        self.impulse_threshold = impulse_threshold
        self.divergence_threshold = divergence_threshold
        self.velocity_z_threshold = velocity_z_threshold
        self.kill_z_threshold = kill_z_threshold
        self.macro_pause_boost = macro_pause_boost
        self.macro_kill_seconds = macro_kill_seconds
        self.min_history_points = min_history_points
        self.decay_half_life_ns = decay_half_life_ns
        self.stability_window_ns = stability_window_ns
        
        # Historical sentiment points (deterministic, replay-safe)
        self._history: deque = deque(maxlen=history_maxlen)
        
        # Rolling statistics for velocity z-score
        self._velocity_history: deque = deque(maxlen=100)
        
        # Last computed outputs
        self._last_vector: Optional[SentimentVector] = None
        self._last_macro_signal: Optional[MacroSignal] = None
        self._last_macro_kill_time_ns: Optional[int] = None
        self._lock = threading.Lock()

        logger.info(f"SentimentVelocityEngine initialized: velocity_window={velocity_window_ns//1_000_000_000}s, "
                   f"impulse_threshold={impulse_threshold}, divergence_threshold={divergence_threshold}")
        logger.info("  Timing authority: external nanosecond timestamps only")
        logger.info("  No wall-clock time, no fake news feeds, no stochastic behavior")
    
    def update_sentiment(self, value: float, timestamp_ns: int) -> Optional[SentimentVector]:
        """
        Update engine with new sentiment observation.
        
        Args:
            value: Sentiment value (typically -1 to 1, analytical only)
            timestamp_ns: Authoritative nanosecond timestamp (must be monotonic)
            
        Returns:
            Updated SentimentVector or None if insufficient history
        """
        # Validate inputs
        if not isinstance(timestamp_ns, int) or timestamp_ns <= 0:
            logger.warning(f"Invalid timestamp: {timestamp_ns} — skipping update")
            return None
        
        if not isinstance(value, (int, float)) or not np.isfinite(value):
            logger.warning(f"Invalid sentiment value: {value} — skipping update")
            return None
        
        with self._lock:
            # Enforce timestamp monotonicity
            if self._history:
                last_ts = self._history[-1].timestamp_ns
                if timestamp_ns <= last_ts:
                    logger.warning(f"Non-monotonic timestamp: {timestamp_ns} <= last {last_ts} — rejecting update")
                    return None

            # Clamp value to reasonable range for analytical stability
            clamped_value = max(-1.0, min(1.0, float(value)))

            # Add to history
            self._history.append(SentimentPoint(value=clamped_value, timestamp_ns=timestamp_ns))

            # Need minimum history for calculations
            if len(self._history) < self.min_history_points:
                return None

            # Compute all analytical components
            level = self._compute_current_level()
            velocity = self._compute_velocity()
            acceleration = self._compute_acceleration()
            impulse = self._compute_impulse()
            divergence = self._compute_divergence(level, velocity)
            reversion_pressure = self._compute_reversion_pressure(level)
            stability = self._compute_stability()
            confidence = self._compute_confidence(timestamp_ns)

            vector = SentimentVector(
                level=level,
                velocity=velocity,
                acceleration=acceleration,
                impulse=impulse,
                divergence=divergence,
                reversion_pressure=reversion_pressure,
                stability=stability,
                confidence=confidence,
                timestamp_ns=timestamp_ns
            )

            # Store velocity for z-score calculation
            self._velocity_history.append(velocity)

            self._last_vector = vector
        return vector
    
    def _compute_current_level(self) -> float:
        """
        Compute current sentiment level with exponential decay weighting.
        
        Recent observations weighted more heavily using deterministic half-life.
        Returns value in [-1, 1].
        """
        if not self._history:
            return 0.0
        
        current_ts = self._history[-1].timestamp_ns
        total_weight = 0.0
        weighted_sum = 0.0
        
        decay_factor = np.log(2) / self.decay_half_life_ns
        
        for point in self._history:
            age_ns = current_ts - point.timestamp_ns
            if age_ns < 0:
                age_ns = 0
            weight = np.exp(-decay_factor * age_ns)
            weighted_sum += point.value * weight
            total_weight += weight
        
        if total_weight < EPS:
            return 0.0
        
        level = weighted_sum / total_weight
        return max(-1.0, min(1.0, level))
    
    def _compute_velocity(self) -> float:
        """
        Compute sentiment velocity (first derivative) using weighted linear regression.
        
        Velocity = change in sentiment per second (units: sentiment/sec)
        Returns bounded value for analytical stability.
        """
        if len(self._history) < self.min_history_points:
            return 0.0
        
        current_ts = self._history[-1].timestamp_ns
        cutoff_ts = current_ts - self.velocity_window_ns
        
        # Collect points within window
        points = [(p.timestamp_ns, p.value) for p in self._history if p.timestamp_ns >= cutoff_ts]
        
        if len(points) < 2:
            return 0.0
        
        # Convert to seconds for velocity calculation
        timestamps_sec = [(ts - current_ts) / 1_000_000_000.0 for ts, _ in points]
        values = [v for _, v in points]
        
        # Simple linear regression for slope
        n = len(timestamps_sec)
        sum_t = sum(timestamps_sec)
        sum_v = sum(values)
        sum_tt = sum(t * t for t in timestamps_sec)
        sum_tv = sum(t * v for t, v in zip(timestamps_sec, values))
        
        denominator = n * sum_tt - sum_t * sum_t
        if abs(denominator) < EPS:
            return 0.0
        
        velocity = (n * sum_tv - sum_t * sum_v) / denominator
        
        # Bound for analytical stability (reasonable velocity range)
        max_velocity = 0.1  # 0.1 sentiment change per second max
        return max(-max_velocity, min(max_velocity, velocity))
    
    def _compute_acceleration(self) -> float:
        """
        Compute sentiment acceleration (second derivative) using recent velocity changes.
        
        Acceleration = change in velocity per second (units: sentiment/sec²)
        """
        if len(self._history) < self.min_history_points + 2:
            return 0.0
        
        current_ts = self._history[-1].timestamp_ns
        cutoff_ts = current_ts - self.acceleration_window_ns
        
        # Need to compute velocity at multiple points
        points = [(p.timestamp_ns, p.value) for p in self._history if p.timestamp_ns >= cutoff_ts]
        
        if len(points) < 3:
            return 0.0
        
        # Compute approximate velocity at each point
        velocities = []
        timestamps = []
        
        for i in range(1, len(points) - 1):
            t_prev, v_prev = points[i-1]
            t_next, v_next = points[i+1]
            
            dt_sec = (t_next - t_prev) / 1_000_000_000.0
            if dt_sec > EPS:
                vel = (v_next - v_prev) / dt_sec
                velocities.append(vel)
                timestamps.append((t_prev + t_next) // 2)
        
        if len(velocities) < 2:
            return 0.0
        
        # Linear regression on velocities to get acceleration
        current_ts = self._history[-1].timestamp_ns
        timestamps_sec = [(ts - current_ts) / 1_000_000_000.0 for ts in timestamps]
        
        n = len(timestamps_sec)
        sum_t = sum(timestamps_sec)
        sum_v = sum(velocities)
        sum_tt = sum(t * t for t in timestamps_sec)
        sum_tv = sum(t * v for t, v in zip(timestamps_sec, velocities))
        
        denominator = n * sum_tt - sum_t * sum_t
        if abs(denominator) < EPS:
            return 0.0
        
        acceleration = (n * sum_tv - sum_t * sum_v) / denominator
        
        # Bound for analytical stability
        max_accel = 0.01  # 0.01 sentiment/sec² max
        return max(-max_accel, min(max_accel, acceleration))
    
    def _compute_impulse(self) -> float:
        """
        Detect sentiment impulse/shock (sudden large change).
        
        Returns score 0-1 where:
        - 1.0 = major shock detected
        - 0.0 = no shock
        """
        if len(self._history) < 2:
            return 0.0
        
        # Look at most recent change
        latest = self._history[-1]
        previous = self._history[-2]
        
        dt_ns = latest.timestamp_ns - previous.timestamp_ns
        if dt_ns <= 0:
            return 0.0
        
        dt_sec = dt_ns / 1_000_000_000.0
        if dt_sec < EPS:
            return 0.0
        
        rate = abs(latest.value - previous.value) / dt_sec
        
        # Normalize: 0.1 sentiment/sec = 0.5, 0.2 sentiment/sec = 0.75, etc.
        impulse = min(1.0, rate / self.impulse_threshold)
        
        return impulse
    
    def _compute_divergence(self, level: float, velocity: float) -> float:
        """
        Compute divergence between sentiment level and velocity.
        
        High level with negative velocity = bullish sentiment rolling over
        Low level with positive velocity = bearish sentiment improving
        
        Returns score 0-1 where higher = more divergence.
        """
        # Normalize level to 0-1 scale for divergence calculation
        normalized_level = abs(level)  # 0 to 1
        
        # Normalize velocity: typical max velocity ~0.05 sentiment/sec
        max_expected_velocity = 0.05
        normalized_velocity = min(1.0, abs(velocity) / max_expected_velocity)
        
        # Divergence when level and velocity have opposite signs (for directional divergence)
        directional_divergence = 0.0
        if level > 0.3 and velocity < -0.01:
            directional_divergence = min(1.0, level * abs(velocity) * 20)
        elif level < -0.3 and velocity > 0.01:
            directional_divergence = min(1.0, abs(level) * velocity * 20)
        
        # Also consider magnitude divergence (high level, low velocity)
        magnitude_divergence = normalized_level * (1.0 - normalized_velocity)
        
        # Combine
        divergence = max(directional_divergence, magnitude_divergence * 0.5)
        
        return min(1.0, max(0.0, divergence))
    
    def _compute_reversion_pressure(self, level: float) -> float:
        """
        Compute mean reversion pressure based on sentiment extremity.
        
        Returns score 0-1 where higher = stronger reversion tendency.
        """
        # Extreme sentiment = higher reversion pressure
        extremity = abs(level)
        
        # Exponential: 0.5 extremity -> 0.25, 0.8 -> 0.64, 1.0 -> 1.0
        pressure = extremity ** 2
        
        return min(1.0, pressure)
    
    def _compute_stability(self) -> float:
        """
        Compute sentiment stability over recent window.
        
        Returns score 0-1 where:
        - 1.0 = very stable (low variance)
        - 0.0 = highly volatile
        """
        if len(self._history) < self.min_history_points:
            return 0.5
        
        current_ts = self._history[-1].timestamp_ns
        cutoff_ts = current_ts - self.stability_window_ns
        
        points = [p.value for p in self._history if p.timestamp_ns >= cutoff_ts]
        
        if len(points) < 2:
            return 0.5
        
        std_dev = np.std(points)
        
        # Normalize: 0.2 std = 0.5, 0.4 std = 0.25, 0.05 std = 0.8
        # Typical sentiment range is -1 to 1, so max std ~ 0.5
        stability = 1.0 - min(1.0, std_dev / 0.3)
        
        return max(0.0, min(1.0, stability))
    
    def _compute_confidence(self, current_ts_ns: int) -> float:
        """
        Compute analytical confidence in current state estimates.
        
        Based on:
        - Number of observations in history
        - Stability of recent sentiment
        - Recency of last observation (using deterministic timestamps)
        
        Args:
            current_ts_ns: Current authoritative timestamp for recency calculation
            
        Returns:
            Confidence score in [0, 1]
        """
        if not self._history:
            return 0.0
        
        # History length confidence
        history_conf = min(1.0, len(self._history) / 100.0)
        
        # Stability confidence
        stability_conf = self._compute_stability()
        
        # Recency confidence using deterministic timestamps
        # If last observation is older than decay half-life, confidence decays
        last_ts = self._history[-1].timestamp_ns
        age_ns = current_ts_ns - last_ts
        if age_ns < 0:
            age_ns = 0
        
        # Linear decay: 0 age = 1.0, at half-life = 0.5, at 2*half-life = 0.0
        recency_conf = max(0.0, 1.0 - (age_ns / self.decay_half_life_ns))
        
        confidence = history_conf * 0.4 + stability_conf * 0.4 + recency_conf * 0.2
        
        return max(0.0, min(1.0, confidence))
    
    def _compute_velocity_z_score(self) -> float:
        """
        Compute z-score of current velocity relative to history.
        
        Returns z-score (0-4 range typically, unbounded but clipped for stability).
        """
        if len(self._velocity_history) < 5:
            return 0.0
        
        vel_list = list(self._velocity_history)
        mean_vel = np.mean(vel_list)
        std_vel = np.std(vel_list)
        
        if std_vel < EPS:
            return 0.0
        
        current_vel = self._velocity_history[-1] if self._velocity_history else 0.0
        
        z_score = abs(current_vel - mean_vel) / std_vel
        
        # Clip for analytical stability
        return min(10.0, z_score)
    
    def analyze(
        self,
        current_ts_ns: int,
        whale_divergence: Optional[float] = None
    ) -> MacroSignal:
        """
        Analyze current sentiment state and produce macro safety signal.
        
        Args:
            current_ts_ns: Current authoritative timestamp in nanoseconds (must be positive int)
            whale_divergence: Optional external divergence score (0-1)
            
        Returns:
            MacroSignal with safety recommendations
        """
        # Validate current_ts_ns
        if not isinstance(current_ts_ns, int) or current_ts_ns <= 0:
            logger.warning(f"Invalid current_ts_ns: {current_ts_ns} — returning neutral signal")
            return MacroSignal(
                macro_pause=False,
                macro_kill=False,
                bull_trap_detected=False,
                divergence_score=0.0,
                confidence_boost=0.0,
                halt_seconds=0,
                reason="invalid_timestamp"
            )
        
        # Ensure we have a current vector
        if self._last_vector is None:
            return MacroSignal(
                macro_pause=False,
                macro_kill=False,
                bull_trap_detected=False,
                divergence_score=0.0,
                confidence_boost=0.0,
                halt_seconds=0,
                reason="insufficient_data"
            )
        
        vector = self._last_vector
        velocity_z = self._compute_velocity_z_score()
        
        # Determine macro-pause (sentiment velocity spike)
        macro_pause = velocity_z > self.velocity_z_threshold
        
        # Determine macro-kill (extreme sentiment velocity)
        macro_kill = velocity_z > self.kill_z_threshold
        
        # Bull trap detection: high sentiment level + negative velocity + high divergence
        bull_trap = (
            vector.level > 0.5 and
            vector.velocity < -0.02 and
            vector.divergence > self.divergence_threshold
        )
        
        # Combined divergence score
        divergence_score = vector.divergence
        if whale_divergence is not None:
            divergence_score = max(divergence_score, whale_divergence)
        
        # Confidence boost during macro-pause
        confidence_boost = self.macro_pause_boost if macro_pause else 0.0
        
        # Build reason string
        reasons = []
        if macro_kill:
            reasons.append(f"macro_kill:vel_z={velocity_z:.2f}")
        elif macro_pause:
            reasons.append(f"macro_pause:vel_z={velocity_z:.2f}")
        if bull_trap:
            reasons.append(f"bull_trap:div={divergence_score:.2f}")
        
        # Macro-kill cooldown logic
        # Always refresh cooldown on new kill event, extend from most recent kill
        if macro_kill:
            self._last_macro_kill_time_ns = current_ts_ns
        elif self._last_macro_kill_time_ns is not None:
            elapsed_ns = current_ts_ns - self._last_macro_kill_time_ns
            elapsed_sec = elapsed_ns / 1_000_000_000.0
            if elapsed_sec < self.macro_kill_seconds:
                macro_kill = True
                macro_pause = True
                if not reasons:
                    reasons.append("macro_kill_cooldown")
            else:
                self._last_macro_kill_time_ns = None
        
        signal = MacroSignal(
            macro_pause=macro_pause,
            macro_kill=macro_kill,
            bull_trap_detected=bull_trap,
            divergence_score=divergence_score,
            confidence_boost=confidence_boost,
            halt_seconds=self.macro_kill_seconds if macro_kill else 0,
            reason=" | ".join(reasons) if reasons else "normal"
        )
        
        self._last_macro_signal = signal
        return signal
    
    def get_current_vector(self) -> Optional[SentimentVector]:
        """Return most recent sentiment vector, or None if unavailable."""
        return self._last_vector
    
    def get_macro_signal(self) -> Optional[MacroSignal]:
        """Return most recent macro signal, or None if unavailable."""
        return self._last_macro_signal
    
    def get_stats(self) -> Dict[str, Any]:
        """Return current engine statistics for monitoring."""
        return {
            "history_size": len(self._history),
            "velocity_history_size": len(self._velocity_history),
            "last_level": self._last_vector.level if self._last_vector else None,
            "last_velocity": self._last_vector.velocity if self._last_vector else None,
            "last_acceleration": self._last_vector.acceleration if self._last_vector else None,
            "last_confidence": self._last_vector.confidence if self._last_vector else None,
            "last_macro_signal": self._last_macro_signal.reason if self._last_macro_signal else None,
            "macro_kill_active": self._last_macro_kill_time_ns is not None
        }
    
    def reset(self) -> None:
        """Reset all internal state."""
        with self._lock:
            self._history.clear()
            self._velocity_history.clear()
            self._last_vector = None
            self._last_macro_signal = None
            self._last_macro_kill_time_ns = None
        logger.info("SentimentVelocityEngine reset")