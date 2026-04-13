"""
app/brain/entropy_decoder.py

Entropy decoder for Poverty Killer.
Deterministic, replay-safe, role-pure structural coherence analyzer.

Role: Unlock / suppress / veto / confidence modulation.
NOT a direction engine.

Distinguishes six state families with operational consequences:
- STRUCTURAL_COMPRESSION: high-quality unlock potential
- DEAD_DRIFT: true inertness / informational emptiness (low entropy, low energy, stale)
- FAKE_CALM: deceptive stillness / unstable calm / hidden fragility
- ORDERLY_REORGANIZATION: constructive transition with evidence of structure recovery
- HOSTILE_CHAOS: high entropy with incoherence
- EXHAUSTED_SUFFOCATION: decayed prior structure

All outputs are deterministic and replay-safe given identical input sequences.
No wall-clock dependence. No random number generation.
"""

from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Deque, List, Optional, Tuple

import numpy as np

from app.models.entropy_score import EntropyScore
from app.models.enums import CollapseQuality


@dataclass
class EntropyState:
    """Internal state for deterministic replay safety."""
    entropy_history: Deque[float] = field(default_factory=lambda: deque(maxlen=100))
    velocity_history: Deque[float] = field(default_factory=lambda: deque(maxlen=10))
    collapse_history: Deque[CollapseQuality] = field(default_factory=lambda: deque(maxlen=5))
    persistence_counter: int = 0
    last_collapse: CollapseQuality = CollapseQuality.NONE


class EntropyDecoder:
    """
    Entropy decoder with sharp structural discrimination.
    
    Distinguishes six state families with operational consequences:
    - STRUCTURAL_COMPRESSION: high-quality unlock potential
    - DEAD_DRIFT: true inertness / informational emptiness
    - FAKE_CALM: deceptive stillness / unstable calm
    - ORDERLY_REORGANIZATION: constructive transition with structure recovery
    - HOSTILE_CHAOS: high entropy with incoherence
    - EXHAUSTED_SUFFOCATION: decayed prior structure
    """

    # Scoring thresholds (calibrated, not arbitrary)
    _STRUCTURAL_ENTROPY_CAP: float = 0.35
    _DEAD_ENTROPY_CAP: float = 0.25
    _FAKE_CALM_ENTROPY_CAP: float = 0.25
    _CHAOS_ENTROPY_FLOOR: float = 0.50
    _VELOCITY_DEAD_ZONE: float = 0.003      # Near-zero for dead drift
    _VELOCITY_DEAD_THRESHOLD: float = 0.01
    _VELOCITY_REORG_THRESHOLD: float = 0.025  # Raised from 0.02
    _VELOCITY_FAKE_CALM_INSTABILITY: float = 0.015
    _PERSISTENCE_REQUIRED_UPGRADE: int = 1
    _PERSISTENCE_REQUIRED_DOWNGRADE: int = 2
    _PERSISTENCE_REQUIRED_EXTREME_ENTER: int = 2
    _PERSISTENCE_REQUIRED_EXTREME_EXIT: int = 3
    _DEAD_PERSISTENCE_REQUIRED: int = 5      # Raised from 3
    _COHERENCE_TREND_WINDOW: int = 5

    def __init__(self):
        self.state = EntropyState()

    def update(
        self,
        symbol: str,
        exchange_ts_ns: int,
        raw_entropy: float,
    ) -> EntropyScore:
        """
        Core update method. Produces deterministic EntropyScore with sharp discrimination.
        
        Args:
            symbol: Trading pair symbol (e.g., "BTC-USD")
            exchange_ts_ns: Exchange timestamp in nanoseconds
            raw_entropy: Raw entropy value from market data (expected in [0, 1])
        """
        # Clamp input to valid range
        clamped_entropy = max(0.0, min(1.0, raw_entropy))
        
        # Update history
        self.state.entropy_history.append(clamped_entropy)
        
        # Compute core metrics
        velocity = self._velocity()
        curvature = self._curvature()
        self.state.velocity_history.append(velocity)
        
        # Compute state family scores (each in [0,1], interpretable)
        structural = self._structural_score(clamped_entropy, velocity, curvature)
        dead = self._dead_score(clamped_entropy, velocity, curvature)
        fake_calm = self._fake_calm_score(clamped_entropy, velocity, curvature)
        reorg = self._reorg_score(velocity, curvature)
        chaos = self._chaos_score(clamped_entropy, velocity, curvature)
        exhausted = self._exhausted_score(velocity, curvature)
        
        # Determine collapse quality via sharp discrimination
        collapse_quality = self._classify(
            structural, dead, fake_calm, reorg, chaos, exhausted
        )
        
        # Apply hysteresis (clean, semantically appropriate)
        collapse_quality = self._hysteresis(collapse_quality)
        
        # Compute confidence (causal, not cosmetic)
        confidence = self._confidence(
            collapse_quality, structural, dead, fake_calm, reorg, chaos, exhausted
        )
        
        # Compute magnitude/usefulness (structural significance, not synthetic)
        magnitude = self._magnitude(
            collapse_quality, structural, dead, fake_calm, reorg, chaos, exhausted, velocity, curvature
        )
        
        return EntropyScore(
            symbol=symbol,
            timestamp=exchange_ts_ns,
            entropy=Decimal(str(round(clamped_entropy, 6))),
            is_collapsed=collapse_quality in (CollapseQuality.STRUCTURAL, CollapseQuality.WEAK),
            predicted_magnitude=Decimal(str(round(magnitude, 6))),
            confidence=Decimal(str(round(confidence, 6))),
            samples_used=len(self.state.entropy_history),
        )

    # -------------------------------------------------------------------------
    # Core metrics (deterministic, bounded)
    # -------------------------------------------------------------------------

    def _velocity(self) -> float:
        """Smoothed entropy velocity using exponential weighting."""
        if len(self.state.entropy_history) < 2:
            return 0.0
        n = min(5, len(self.state.entropy_history))
        weights = np.exp(np.linspace(-1, 0, n))
        weights /= weights.sum()
        diffs = np.diff(list(self.state.entropy_history)[-n:])
        return float(np.dot(diffs, weights[-len(diffs):]))

    def _curvature(self) -> float:
        """Second derivative of entropy (acceleration/deceleration)."""
        if len(self.state.velocity_history) < 2:
            return 0.0
        return self.state.velocity_history[-1] - self.state.velocity_history[-2]

    # -------------------------------------------------------------------------
    # State family scores (each bounded [0,1], causally grounded)
    # -------------------------------------------------------------------------

    def _structural_score(
        self,
        entropy: float,
        velocity: float,
        curvature: float,
    ) -> float:
        """
        Score for genuine structural compression with unlock value.
        High score requires: low entropy, non-dead, non-fake, coherence.
        """
        if entropy > self._STRUCTURAL_ENTROPY_CAP:
            return 0.0
        
        coherence = self._coherence()
        
        # Continuous dead penalty: increases from 0.0 at |v|=0 to 1.0 at |v|=0.01
        dead_penalty = min(1.0, abs(velocity) / self._VELOCITY_DEAD_THRESHOLD)
        
        raw_score = (1.0 - entropy / self._STRUCTURAL_ENTROPY_CAP) * coherence * dead_penalty
        return float(np.clip(raw_score, 0.0, 1.0))

    def _dead_score(
        self,
        entropy: float,
        velocity: float,
        curvature: float,
    ) -> float:
        """
        Score for DEAD_DRIFT: true inertness / informational emptiness.
        
        Characteristics:
        - Low entropy (≤0.25)
        - Near-zero velocity (informational emptiness)
        - Low coherence
        - Must be sustained (persistence requirement)
        """
        if entropy > self._DEAD_ENTROPY_CAP:
            return 0.0
        
        coherence = self._coherence()
        
        # Dead requires near-zero velocity
        if abs(velocity) > self._VELOCITY_DEAD_ZONE:
            return 0.0
        
        dead_raw = (1.0 - entropy / self._DEAD_ENTROPY_CAP) * (1.0 - coherence)
        
        # Sustained dead bonus: if dead condition has persisted
        if self._is_sustained_dead(entropy, velocity):
            dead_raw = min(1.0, dead_raw * 1.3)
        
        return float(np.clip(dead_raw, 0.0, 1.0))

    def _fake_calm_score(
        self,
        entropy: float,
        velocity: float,
        curvature: float,
    ) -> float:
        """
        Score for FAKE_CALM: deceptive stillness / unstable calm.
        
        Characteristics:
        - Low apparent entropy (≤0.25)
        - Hidden instability (velocity sign changes, churn)
        - Low coherence despite low entropy
        - Persistence makes it more suspicious
        """
        if entropy > self._FAKE_CALM_ENTROPY_CAP:
            return 0.0
        
        coherence = self._coherence()
        
        # Base: low entropy + low coherence = suspicious
        fake_raw = (1.0 - entropy / self._FAKE_CALM_ENTROPY_CAP) * (1.0 - coherence)
        
        # Instability detection: hidden fragility via velocity sign changes
        instability = self._instability(velocity, curvature)
        if instability > self._VELOCITY_FAKE_CALM_INSTABILITY:
            fake_raw = min(1.0, fake_raw + min(0.3, instability * 10))
        
        # Persistence penalty: longer calm with instability = more fake
        if len(self.state.entropy_history) >= 10:
            recent_entropy = list(self.state.entropy_history)[-10:]
            if all(e < self._FAKE_CALM_ENTROPY_CAP for e in recent_entropy):
                fake_raw = min(1.0, fake_raw * 1.2)
        
        return float(np.clip(fake_raw, 0.0, 1.0))

    def _reorg_score(
        self,
        velocity: float,
        curvature: float,
    ) -> float:
        """
        Score for ORDERLY_REORGANIZATION: constructive transition.
        
        Characteristics:
        - Meaningful velocity (≥0.025)
        - Coherence improving (structure recovery)
        - Acceleration into transition (positive curvature)
        - Not chaotic
        """
        # Must have meaningful velocity
        if abs(velocity) < self._VELOCITY_REORG_THRESHOLD:
            return 0.0
        
        # Coherence must be improving (constructive reorganization)
        coherence_trend = self._coherence_trend()
        if coherence_trend <= 0:
            return 0.0  # Not reorganizing — just noisy motion
        
        velocity_magnitude = min(1.0, abs(velocity) / 0.10)
        
        # Curvature quality: acceleration into transition
        curvature_quality = max(0.0, 1.0 - min(1.0, abs(curvature) / 0.04))
        
        # Stabilization factor: recent coherence stability
        stabilization = self._stabilization()
        
        reorg_raw = velocity_magnitude * curvature_quality * coherence_trend * (0.7 + 0.3 * stabilization)
        return float(np.clip(reorg_raw, 0.0, 1.0))

    def _chaos_score(
        self,
        entropy: float,
        velocity: float,
        curvature: float,
    ) -> float:
        """
        Score for hostile chaos (high entropy, incoherence).
        High score indicates untradeable conditions.
        """
        if entropy < self._CHAOS_ENTROPY_FLOOR:
            return 0.0
        
        coherence = self._coherence()
        
        # Churn penalty from velocity sign changes
        churn = 0.0
        if len(self.state.velocity_history) >= 4:
            recent = list(self.state.velocity_history)[-4:]
            sign_flips = sum(1 for i in range(1, len(recent)) if recent[i] * recent[i-1] < 0)
            churn = min(1.0, sign_flips / 3.0)
        
        chaos_raw = ((entropy - self._CHAOS_ENTROPY_FLOOR) / (1.0 - self._CHAOS_ENTROPY_FLOOR)) * (1.0 - coherence) * (0.5 + 0.5 * churn)
        
        return float(np.clip(chaos_raw, 0.0, 1.0))

    def _exhausted_score(self, velocity: float, curvature: float) -> float:
        """
        Score for exhausted post-move suffocation.
        High score indicates spent structure with reduced usefulness.
        
        NOTE: This is a real but underutilized differentiator.
        It detects when prior movement has exhausted itself.
        Preserved for future activation.
        """
        if abs(velocity) > 0.01:
            return 0.0
        
        # Check for deceleration from prior movement
        deceleration = 0.0
        if len(self.state.velocity_history) >= 5:
            recent = list(self.state.velocity_history)[-5:]
            if all(abs(v) < 0.01 for v in recent[-3:]):
                prior = recent[:-3]
                if any(abs(v) > 0.03 for v in prior):
                    deceleration = 0.8
        
        return float(np.clip(deceleration, 0.0, 1.0))

    def _coherence(self) -> float:
        """
        Evaluate whether recent entropy evolution is causally interpretable.
        Returns in [0,1] where 1 = highly coherent.
        """
        if len(self.state.entropy_history) < 5:
            return 0.8
        
        recent = list(self.state.entropy_history)[-20:]
        diffs = np.diff(recent)
        
        # Monotonicity: fewer sign changes = higher coherence
        sign_changes = sum(1 for i in range(1, len(diffs)) if diffs[i] * diffs[i-1] < 0)
        monotonicity = 1.0 - min(1.0, sign_changes / (len(diffs) / 2))
        
        # Smoothness: low variance of differences = higher coherence
        smoothness = 1.0 - min(1.0, np.std(diffs) / 0.1) if len(diffs) > 0 else 1.0
        
        # Trend persistence: consistent velocity direction
        if len(self.state.velocity_history) >= 3:
            recent_vel = list(self.state.velocity_history)[-3:]
            persistence = 1.0 - min(1.0, np.std(recent_vel) / 0.05)
        else:
            persistence = 0.5
        
        return float(np.clip(0.4 * monotonicity + 0.3 * smoothness + 0.3 * persistence, 0.0, 1.0))

    def _coherence_trend(self) -> float:
        """
        Compute whether coherence is improving.
        Returns in [-1, 1] where positive = improving.
        
        NOTE: This is a real but previously underutilized differentiator.
        Now activated for ORDERLY_REORGANIZATION detection.
        """
        if len(self.state.entropy_history) < self._COHERENCE_TREND_WINDOW + 5:
            return 0.0
        
        coherence_values = []
        for i in range(self._COHERENCE_TREND_WINDOW):
            idx = -self._COHERENCE_TREND_WINDOW + i
            if idx >= -len(self.state.entropy_history):
                window = list(self.state.entropy_history)[idx-10:idx] if idx-10 >= -len(self.state.entropy_history) else list(self.state.entropy_history)[:idx]
                if len(window) >= 5:
                    diffs = np.diff(window)
                    if len(diffs) > 0:
                        sign_changes = sum(1 for j in range(1, len(diffs)) if diffs[j] * diffs[j-1] < 0)
                        monotonicity = 1.0 - min(1.0, sign_changes / (len(diffs) / 2))
                        smoothness = 1.0 - min(1.0, np.std(diffs) / 0.1) if len(diffs) > 0 else 1.0
                        coherence_values.append(0.5 * monotonicity + 0.5 * smoothness)
                    else:
                        coherence_values.append(0.5)
                else:
                    coherence_values.append(0.5)
            else:
                coherence_values.append(0.5)
        
        if len(coherence_values) < 2:
            return 0.0
        
        trend = coherence_values[-1] - coherence_values[0]
        return float(np.clip(trend, -1.0, 1.0))

    def _stabilization(self) -> float:
        """
        Measure recent stabilization in coherence.
        Returns in [0, 1] where higher = more stable.
        
        NOTE: Real differentiator preserved for future activation.
        Currently used in ORDERLY_REORGANIZATION as a minor factor.
        """
        if len(self.state.entropy_history) < 10:
            return 0.5
        
        recent = list(self.state.entropy_history)[-10:]
        diffs = np.diff(recent)
        if len(diffs) < 2:
            return 0.5
        
        # Lower variance in recent differences = more stable
        variance = np.var(diffs)
        stability = 1.0 - min(1.0, variance / 0.001)
        
        return float(stability)

    def _instability(self, velocity: float, curvature: float) -> float:
        """
        Measure hidden instability for fake calm detection.
        Returns in [0, 1] where higher = more unstable.
        
        NOTE: Real differentiator preserved. Now activated for FAKE_CALM.
        """
        # Curvature variance indicates instability
        curvature_instability = 0.0
        if len(self.state.velocity_history) >= 5:
            recent_curvature = []
            for i in range(1, min(5, len(self.state.velocity_history))):
                recent_curvature.append(self.state.velocity_history[-i] - self.state.velocity_history[-i-1])
            if recent_curvature:
                curvature_instability = min(1.0, np.std(recent_curvature) / 0.02)
        
        # Velocity sign changes indicate churn
        sign_changes = 0.0
        if len(self.state.velocity_history) >= 4:
            recent_vel = list(self.state.velocity_history)[-4:]
            sign_changes = sum(1 for i in range(1, len(recent_vel)) if recent_vel[i] * recent_vel[i-1] < 0) / 3.0
        
        return float(np.clip(0.5 * curvature_instability + 0.5 * sign_changes, 0.0, 1.0))

    def _is_sustained_dead(self, entropy: float, velocity: float) -> bool:
        """
        Check if dead condition has persisted for required window.
        
        NOTE: Real differentiator preserved. Now activated for DEAD_DRIFT.
        """
        if len(self.state.entropy_history) < self._DEAD_PERSISTENCE_REQUIRED:
            return False
        
        recent_entropy = list(self.state.entropy_history)[-self._DEAD_PERSISTENCE_REQUIRED:]
        recent_velocities = list(self.state.velocity_history)[-self._DEAD_PERSISTENCE_REQUIRED:] if len(self.state.velocity_history) >= self._DEAD_PERSISTENCE_REQUIRED else []
        
        entropy_condition = all(e <= self._DEAD_ENTROPY_CAP for e in recent_entropy)
        velocity_condition = all(abs(v) < self._VELOCITY_DEAD_ZONE for v in recent_velocities) if recent_velocities else True
        
        return entropy_condition and velocity_condition

    # -------------------------------------------------------------------------
    # Classification (sharp, deterministic)
    # -------------------------------------------------------------------------

    def _classify(
        self,
        structural: float,
        dead: float,
        fake_calm: float,
        reorg: float,
        chaos: float,
        exhausted: float,
    ) -> CollapseQuality:
        """
        Deterministic classification with sharp separation.
        Order matters: most specific / most actionable first.
        """
        # Structural compression (highest trust)
        if structural > 0.65 and dead < 0.25 and fake_calm < 0.3:
            return CollapseQuality.STRUCTURAL
        
        # Hostile chaos (extreme hostility)
        if chaos > 0.75:
            return CollapseQuality.EXTREME
        
        # Weak but potentially useful (caution)
        if structural > 0.4 and dead < 0.5 and fake_calm < 0.55:
            return CollapseQuality.WEAK
        
        # Orderly reorganization is operationally distinct from NONE
        if reorg > 0.65 and dead < 0.4 and chaos < 0.4:
            return CollapseQuality.WEAK
        
        # Everything else is NONE (includes dead, fake_calm, exhausted, low-confidence)
        return CollapseQuality.NONE

    def _hysteresis(self, new: CollapseQuality) -> CollapseQuality:
        """
        Clean hysteresis with semantically appropriate transition semantics.
        Upgrades accepted immediately. Downgrades require persistence.
        EXTREME is treated as a hostile state with its own persistence rules.
        """
        current = self.state.last_collapse
        
        if current == new:
            self.state.persistence_counter += 1
            return new
        
        # Entering EXTREME (hostile state) requires strong evidence
        if new == CollapseQuality.EXTREME:
            self.state.collapse_history.append(new)
            if len(self.state.collapse_history) >= self._PERSISTENCE_REQUIRED_EXTREME_ENTER:
                if all(q == new for q in list(self.state.collapse_history)[-self._PERSISTENCE_REQUIRED_EXTREME_ENTER:]):
                    self.state.last_collapse = new
                    self.state.collapse_history.clear()
                    self.state.persistence_counter = 0
                    return new
            return current
        
        # Exiting EXTREME requires persistence (hostile states clear slowly)
        if current == CollapseQuality.EXTREME and new != CollapseQuality.EXTREME:
            self.state.collapse_history.append(new)
            if len(self.state.collapse_history) >= self._PERSISTENCE_REQUIRED_EXTREME_EXIT:
                if all(q == new for q in list(self.state.collapse_history)[-self._PERSISTENCE_REQUIRED_EXTREME_EXIT:]):
                    self.state.last_collapse = new
                    self.state.collapse_history.clear()
                    self.state.persistence_counter = 0
                    return new
            return current
        
        # For non-EXTREME transitions: upgrade immediately, downgrade with persistence
        if self._rank(new) > self._rank(current):
            # Upgrade: accept immediately
            self.state.last_collapse = new
            self.state.collapse_history.clear()
            self.state.persistence_counter = 0
            return new
        
        # Downgrade: require persistence
        self.state.collapse_history.append(new)
        if len(self.state.collapse_history) >= self._PERSISTENCE_REQUIRED_DOWNGRADE:
            if all(q == new for q in list(self.state.collapse_history)[-self._PERSISTENCE_REQUIRED_DOWNGRADE:]):
                self.state.last_collapse = new
                self.state.collapse_history.clear()
                self.state.persistence_counter = 0
                return new
        
        return current

    @staticmethod
    def _rank(q: CollapseQuality) -> int:
        """
        Ordinal ranking for non-EXTREME transitions only.
        EXTREME is handled separately in hysteresis.
        """
        mapping = {
            CollapseQuality.STRUCTURAL: 3,
            CollapseQuality.WEAK: 2,
            CollapseQuality.NONE: 0,
        }
        return mapping.get(q, 0)

    # -------------------------------------------------------------------------
    # Confidence (causal, not decorative)
    # -------------------------------------------------------------------------

    def _confidence(
        self,
        quality: CollapseQuality,
        structural: float,
        dead: float,
        fake_calm: float,
        reorg: float,
        chaos: float,
        exhausted: float,
    ) -> float:
        """Confidence reflects structural trustworthiness."""
        base = {
            CollapseQuality.STRUCTURAL: 0.92,
            CollapseQuality.WEAK: 0.70,
            CollapseQuality.EXTREME: 0.10,
            CollapseQuality.NONE: 0.30,
        }.get(quality, 0.30)
        
        # Modulate by state family scores
        confidence = base
        confidence *= (0.7 + 0.3 * structural)
        confidence *= (1.0 - dead)
        confidence *= (1.0 - fake_calm)
        confidence *= (1.0 - chaos)
        confidence *= (1.0 - exhausted)
        
        # Reorganization gets moderate confidence (distinct from dead NONE)
        if quality == CollapseQuality.NONE and reorg > 0.6:
            confidence = max(confidence, 0.50)
        elif quality == CollapseQuality.WEAK and reorg > 0.65:
            confidence = max(confidence, 0.65)
        
        # Persistence boosts confidence slightly
        if self.state.persistence_counter >= 3:
            confidence = min(1.0, confidence * 1.05)
        
        return float(np.clip(confidence, 0.0, 1.0))

    # -------------------------------------------------------------------------
    # Magnitude / Usefulness (structural significance, not synthetic)
    # -------------------------------------------------------------------------

    def _magnitude(
        self,
        quality: CollapseQuality,
        structural: float,
        dead: float,
        fake_calm: float,
        reorg: float,
        chaos: float,
        exhausted: float,
        velocity: float,
        curvature: float,
    ) -> float:
        """
        Magnitude reflects structural significance and downstream relevance.
        Each state family has distinct semantic meaning.
        """
        if quality == CollapseQuality.STRUCTURAL:
            # High-quality compression: significant unlock potential
            mag = 8.0 + 4.0 * structural
            mag *= (1.0 + min(1.0, abs(velocity) * 10.0))
            
        elif quality == CollapseQuality.WEAK:
            # Moderate, cautious; reorganization gets meaningful magnitude
            mag = 3.0 + 3.0 * structural
            if reorg > 0.65:
                mag = max(mag, 4.5)
            mag *= (1.0 - dead) * (1.0 - fake_calm)
            
        elif quality == CollapseQuality.EXTREME:
            # Hostile chaos: high magnitude but negative (veto signal)
            mag = 10.0 + 5.0 * chaos
            
        else:  # NONE
            # Low significance; reorganization gets moderate boost
            mag = 1.0 + 3.0 * reorg
            mag *= (1.0 - exhausted) * (1.0 - dead)
        
        # Apply universal caps
        return float(np.clip(mag, 0.5, 15.0))

    def reset(self) -> None:
        """Reset internal state for deterministic replay safety."""
        self.state = EntropyState()