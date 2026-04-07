"""
app/brain/entropy_decoder.py

Entropy decoder for Poverty Killer.
Deterministic, replay-safe, role-pure structural coherence analyzer.

Role: Unlock / suppress / veto / confidence modulation.
NOT a direction engine.
"""

from collections import deque
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Deque, Dict, List, Optional, Tuple

import numpy as np

from app.models.market_data import EntropyScore


class CollapseQuality(IntEnum):
    """Local CollapseQuality enum - source of truth for this file."""
    NONE = 0
    WEAK = 1
    STRUCTURAL = 2
    EXTREME = 3


@dataclass
class SymbolState:
    """Per-symbol internal state for deterministic replay safety."""
    entropy_history: Deque[float] = field(default_factory=lambda: deque(maxlen=100))
    velocity_history: Deque[float] = field(default_factory=lambda: deque(maxlen=10))
    collapse_history: Deque[CollapseQuality] = field(default_factory=lambda: deque(maxlen=3))
    persistence_counter: int = 0
    last_collapse: CollapseQuality = CollapseQuality.NONE
    last_score: Optional[EntropyScore] = None


class EntropyDecoder:
    """
    Entropy decoder with sharp structural discrimination.
    
    Distinguishes six state families with operational consequences:
    - STRUCTURAL_COMPRESSION: high-quality unlock potential
    - DEAD_DRIFT: low entropy without value
    - FAKE_CALM: apparent calm masking poor quality
    - ORDERLY_REORGANIZATION: transition with reduced confidence
    - HOSTILE_CHAOS: high entropy with incoherence
    - EXHAUSTED_SUFFOCATION: decayed prior structure
    """

    def __init__(self):
        self._states: Dict[str, SymbolState] = {}

    def _get_state(self, symbol: str) -> SymbolState:
        """Get or create per-symbol state."""
        if symbol not in self._states:
            self._states[symbol] = SymbolState()
        return self._states[symbol]

    def update(
        self,
        symbol: str,
        exchange_ts_ns: int,
        raw_entropy: float,
        volume_profile: Optional[List[float]] = None,
        tick_imbalance: Optional[float] = None,
    ) -> EntropyScore:
        """
        Core update method. Produces deterministic EntropyScore with sharp discrimination.
        
        Args:
            symbol: Trading pair symbol (e.g., "BTC-USD")
            exchange_ts_ns: Exchange timestamp in nanoseconds
            raw_entropy: Raw entropy value from market data
            volume_profile: Optional volume profile for ancillary discrimination
            tick_imbalance: Optional tick imbalance for ancillary discrimination
        """
        state = self._get_state(symbol)
        
        # Update history
        state.entropy_history.append(raw_entropy)
        
        # Compute core metrics
        velocity = self._velocity(state)
        curvature = self._curvature(state)
        state.velocity_history.append(velocity)
        
        # Compute state family scores (each in [0,1], interpretable)
        structural = self._structural_score(state, raw_entropy, velocity, curvature, volume_profile)
        dead = self._dead_score(state, raw_entropy, velocity, curvature, volume_profile)
        fake_calm = self._fake_calm_score(state, raw_entropy, velocity, curvature, tick_imbalance, volume_profile)
        reorg = self._reorg_score(state, velocity, curvature, volume_profile)
        chaos = self._chaos_score(state, raw_entropy, velocity, curvature, volume_profile)
        exhausted = self._exhausted_score(state, velocity, curvature)
        
        # Determine collapse quality via sharp discrimination
        collapse_quality = self._classify(
            structural, dead, fake_calm, reorg, chaos, exhausted
        )
        
        # Apply hysteresis (clean, semantically appropriate)
        collapse_quality = self._hysteresis(state, collapse_quality)
        
        # Compute confidence (causal, not cosmetic)
        confidence = self._confidence(
            state, collapse_quality, structural, dead, fake_calm, reorg, chaos, exhausted
        )
        
        # Compute magnitude/usefulness (structural significance, not synthetic)
        magnitude = self._magnitude(
            state, collapse_quality, structural, dead, fake_calm, reorg, chaos, exhausted, velocity, curvature
        )
        
        score = EntropyScore(
            symbol=symbol,
            exchange_ts_ns=exchange_ts_ns,
            entropy=raw_entropy,
            is_collapsed=collapse_quality in (CollapseQuality.STRUCTURAL, CollapseQuality.WEAK),
            predicted_magnitude=magnitude,
            confidence=confidence,
            samples_used=len(state.entropy_history),
        )
        
        state.last_score = score
        return score

    def get_current(self, symbol: str) -> Optional[EntropyScore]:
        """
        Get the most recent EntropyScore for a symbol.
        Returns None if no update has been performed for this symbol.
        
        This method exists for compatibility with consumers like shans_curve.py
        that need to read the current state without performing an update.
        """
        state = self._states.get(symbol)
        return state.last_score if state else None

    # -------------------------------------------------------------------------
    # Core metrics (deterministic, bounded)
    # -------------------------------------------------------------------------

    def _velocity(self, state: SymbolState) -> float:
        """Smoothed entropy velocity using exponential weighting."""
        if len(state.entropy_history) < 2:
            return 0.0
        n = min(5, len(state.entropy_history))
        weights = np.exp(np.linspace(-1, 0, n))
        weights /= weights.sum()
        diffs = np.diff(list(state.entropy_history)[-n:])
        return float(np.dot(diffs, weights[-len(diffs):]))

    def _curvature(self, state: SymbolState) -> float:
        """Second derivative of entropy (acceleration/deceleration)."""
        if len(state.velocity_history) < 2:
            return 0.0
        return state.velocity_history[-1] - state.velocity_history[-2]

    def _sequence_coherence(self, state: SymbolState) -> float:
        """
        Evaluate whether recent entropy evolution is causally interpretable.
        Returns in [0,1] where 1 = highly coherent.
        """
        if len(state.entropy_history) < 5:
            return 0.8
        
        recent = list(state.entropy_history)[-20:]
        diffs = np.diff(recent)
        
        # Monotonicity: fewer sign changes = higher coherence
        sign_changes = sum(1 for i in range(1, len(diffs)) if diffs[i] * diffs[i-1] < 0)
        monotonicity = 1.0 - min(1.0, sign_changes / (len(diffs) / 2))
        
        # Smoothness: low variance of differences = higher coherence
        smoothness = 1.0 - min(1.0, np.std(diffs) / 0.1) if len(diffs) > 0 else 1.0
        
        # Trend persistence: consistent velocity direction
        if len(state.velocity_history) >= 3:
            recent_vel = list(state.velocity_history)[-3:]
            persistence = 1.0 - min(1.0, np.std(recent_vel) / 0.05)
        else:
            persistence = 0.5
        
        return float(np.clip(0.4 * monotonicity + 0.3 * smoothness + 0.3 * persistence, 0.0, 1.0))

    # -------------------------------------------------------------------------
    # State family scores (each bounded [0,1], causally grounded)
    # -------------------------------------------------------------------------

    def _structural_score(
        self,
        state: SymbolState,
        entropy: float,
        velocity: float,
        curvature: float,
        volume_profile: Optional[List[float]],
    ) -> float:
        """
        Score for genuine structural compression with unlock value.
        High score requires: low entropy, coherence, non-dead, non-fake.
        """
        if entropy > 0.35:
            return 0.0
        
        coherence = self._sequence_coherence(state)
        
        # Continuous dead penalty: increases from 0.0 at |v|=0 to 1.0 at |v|=0.01
        # Penalizes dead/flat conditions; higher velocity removes the penalty
        dead_penalty = min(1.0, abs(velocity) / 0.01)
        
        # Volume concentration supports structural interpretation
        volume_factor = 1.0
        if volume_profile and len(volume_profile) >= 3:
            concentration = np.std(volume_profile[-3:]) / (np.mean(volume_profile[-3:]) + 1e-6)
            volume_factor = 0.7 + min(0.3, concentration / 2.0)
        
        raw_score = (1.0 - entropy / 0.35) * coherence * dead_penalty * volume_factor
        return float(np.clip(raw_score, 0.0, 1.0))

    def _dead_score(
        self,
        state: SymbolState,
        entropy: float,
        velocity: float,
        curvature: float,
        volume_profile: Optional[List[float]],
    ) -> float:
        """
        Score for dead drift / stale calm (low entropy, no value).
        High score indicates informational emptiness.
        """
        if entropy > 0.3:
            return 0.0
        
        # Dead indicators: low entropy, near-zero velocity, low coherence
        coherence = self._sequence_coherence(state)
        dead_raw = (1.0 - entropy / 0.3) * (1.0 - min(1.0, abs(velocity) / 0.02)) * (1.0 - coherence)
        
        # Flat volume confirms deadness
        volume_factor = 1.0
        if volume_profile and len(volume_profile) >= 3:
            volume_std = np.std(volume_profile[-3:])
            volume_mean = np.mean(volume_profile[-3:]) + 1e-6
            volume_factor = 1.0 - min(1.0, volume_std / volume_mean)
        
        return float(np.clip(dead_raw * volume_factor, 0.0, 1.0))

    def _fake_calm_score(
        self,
        state: SymbolState,
        entropy: float,
        velocity: float,
        curvature: float,
        tick_imbalance: Optional[float],
        volume_profile: Optional[List[float]],
    ) -> float:
        """
        Score for fake calm: low apparent entropy masking poor quality.
        High score indicates calm is deceptive.
        """
        if entropy > 0.3:
            return 0.0
        
        coherence = self._sequence_coherence(state)
        # Low coherence + low entropy = suspicious
        fake_raw = (1.0 - entropy / 0.3) * (1.0 - coherence)
        
        # Tick imbalance exposes hidden pressure
        if tick_imbalance is not None and abs(tick_imbalance) > 0.25:
            fake_raw = min(1.0, fake_raw + 0.3)
        
        # Erratic volume under calm = fake
        if volume_profile and len(volume_profile) >= 3:
            volume_cv = np.std(volume_profile[-3:]) / (np.mean(volume_profile[-3:]) + 1e-6)
            if volume_cv > 0.8:
                fake_raw = min(1.0, fake_raw + 0.25)
        
        return float(np.clip(fake_raw, 0.0, 1.0))

    def _reorg_score(
        self,
        state: SymbolState,
        velocity: float,
        curvature: float,
        volume_profile: Optional[List[float]],
    ) -> float:
        """
        Score for orderly reorganization (constructive transition state).
        High score indicates meaningful transition with reduced but non-zero trust.
        """
        if abs(velocity) < 0.015:
            return 0.0
        
        velocity_magnitude = min(1.0, abs(velocity) / 0.08)
        # Positive curvature indicates acceleration into transition
        curvature_quality = max(0.0, 1.0 - min(1.0, abs(curvature) / 0.04))
        
        # Volume participation supports reorganization interpretation
        volume_factor = 1.0
        if volume_profile and len(volume_profile) >= 3:
            volume_mean = np.mean(volume_profile[-3:])
            volume_factor = min(1.0, volume_mean / 0.5) if volume_mean > 0 else 0.5
        
        reorg_raw = velocity_magnitude * curvature_quality * volume_factor
        return float(np.clip(reorg_raw, 0.0, 1.0))

    def _chaos_score(
        self,
        state: SymbolState,
        entropy: float,
        velocity: float,
        curvature: float,
        volume_profile: Optional[List[float]],
    ) -> float:
        """
        Score for hostile chaos (high entropy, incoherence).
        High score indicates untradeable conditions.
        """
        if entropy < 0.5:
            return 0.0
        
        coherence = self._sequence_coherence(state)
        # Churn penalty from velocity sign changes
        churn = 0.0
        if len(state.velocity_history) >= 4:
            recent = list(state.velocity_history)[-4:]
            sign_flips = sum(1 for i in range(1, len(recent)) if recent[i] * recent[i-1] < 0)
            churn = min(1.0, sign_flips / 3.0)
        
        chaos_raw = ((entropy - 0.5) / 0.5) * (1.0 - coherence) * (0.5 + 0.5 * churn)
        
        # Erratic volume amplifies chaos
        if volume_profile and len(volume_profile) >= 3:
            volume_cv = np.std(volume_profile[-3:]) / (np.mean(volume_profile[-3:]) + 1e-6)
            chaos_raw = chaos_raw * (0.8 + min(0.4, volume_cv / 2.0))
        
        return float(np.clip(chaos_raw, 0.0, 1.0))

    def _exhausted_score(self, state: SymbolState, velocity: float, curvature: float) -> float:
        """
        Score for exhausted post-move suffocation.
        High score indicates spent structure with reduced usefulness.
        """
        if abs(velocity) > 0.01:
            return 0.0
        
        # Check for deceleration from prior movement
        deceleration = 0.0
        if len(state.velocity_history) >= 5:
            recent = list(state.velocity_history)[-5:]
            if all(abs(v) < 0.01 for v in recent[-3:]):
                prior = recent[:-3]
                if any(abs(v) > 0.03 for v in prior):
                    deceleration = 0.8
        
        return float(np.clip(deceleration, 0.0, 1.0))

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
        # It receives WEAK classification when reorg is high enough
        if reorg > 0.65 and dead < 0.4 and chaos < 0.4:
            return CollapseQuality.WEAK
        
        # Everything else is NONE (includes dead, fake_calm, exhausted, low-confidence)
        return CollapseQuality.NONE

    def _hysteresis(self, state: SymbolState, new: CollapseQuality) -> CollapseQuality:
        """
        Clean hysteresis with semantically appropriate transition semantics.
        Upgrades accepted immediately. Downgrades require persistence.
        EXTREME is treated as a hostile state with its own persistence rules.
        """
        current = state.last_collapse
        
        if current == new:
            state.persistence_counter += 1
            return new
        
        # Entering EXTREME (hostile state) requires strong evidence
        if new == CollapseQuality.EXTREME:
            # Require 2 consecutive observations to enter extreme
            state.collapse_history.append(new)
            if len(state.collapse_history) >= 2:
                if all(q == new for q in list(state.collapse_history)[-2:]):
                    state.last_collapse = new
                    state.collapse_history.clear()
                    state.persistence_counter = 0
                    return new
            return current
        
        # Exiting EXTREME requires persistence (hostile states clear slowly)
        if current == CollapseQuality.EXTREME and new != CollapseQuality.EXTREME:
            state.collapse_history.append(new)
            if len(state.collapse_history) >= 3:
                if all(q == new for q in list(state.collapse_history)[-3:]):
                    state.last_collapse = new
                    state.collapse_history.clear()
                    state.persistence_counter = 0
                    return new
            return current
        
        # For non-EXTREME transitions: upgrade immediately, downgrade with persistence
        if self._rank(new) > self._rank(current):
            # Upgrade: accept immediately
            state.last_collapse = new
            state.collapse_history.clear()
            state.persistence_counter = 0
            return new
        
        # Downgrade: require 2 consecutive observations
        state.collapse_history.append(new)
        if len(state.collapse_history) >= 2:
            if all(q == new for q in list(state.collapse_history)[-2:]):
                state.last_collapse = new
                state.collapse_history.clear()
                state.persistence_counter = 0
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
            CollapseQuality.EXTREME: 0,  # Not used in ordinal comparison
        }
        return mapping.get(q, 0)

    # -------------------------------------------------------------------------
    # Confidence (causal, not decorative)
    # -------------------------------------------------------------------------

    def _confidence(
        self,
        state: SymbolState,
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
        if state.persistence_counter >= 3:
            confidence = min(1.0, confidence * 1.05)
        
        return float(np.clip(confidence, 0.0, 1.0))

    # -------------------------------------------------------------------------
    # Magnitude / Usefulness (structural significance, not synthetic)
    # -------------------------------------------------------------------------

    def _magnitude(
        self,
        state: SymbolState,
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
                mag = max(mag, 4.5)  # Reorganization has moderate significance
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

    def reset(self, symbol: Optional[str] = None) -> None:
        """
        Reset internal state for deterministic replay safety.
        
        Args:
            symbol: If provided, reset only that symbol's state.
                   If None, reset all states.
        """
        if symbol is not None:
            self._states.pop(symbol, None)
        else:
            self._states.clear()