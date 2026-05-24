"""
app/brain/regime_detector.py

Deterministic, replay-safe regime detection for Poverty Killer.
Classifies market structure into operationally meaningful regimes that drive
sleeve authorization, risk modification, and transition discipline.

Role: Sleeve authorization system + risk modifier.
NOT: decorative labeler, entropy duplicate, direction engine.

Upgrades:
- Replaced np.polyfit with deterministic, warning-free least-squares math.
- Integrated Market Efficiency Ratio (MER) to distinguish true trend from noisy chop.
- Evidence-backed authorization (evaluates continuous stress, not just categorical buckets).
- Honest L1 degraded fallback for update_candles().
"""

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Deque, Union, Any
from collections import deque
import numpy as np

from app.models.enums import RegimeType

# Bounded local defaults
DEFAULT_HYSTERESIS_BARS = 3
DEFAULT_MIN_HISTORY_BARS = 20

EPS = np.finfo(float).eps


@dataclass
class RegimeEvidence:
    """Raw evidence for regime classification."""
    price_trend: float          # Normalized trend slope [-1, 1]
    market_efficiency: float    # Kaufman's Efficiency Ratio [0, 1] (Trend vs Noise)
    volatility: float           # Normalized volatility [0, 1]
    volume_trend: float         # Normalized volume trend [-1, 1]
    spread_widening: float      # Normalized spread change [0, 1]
    liquidity_depth: float      # Normalized liquidity [0, 1]
    exchange_ts_ns: int         # Timestamp of evidence


@dataclass
class CachedRegimeState:
    """Internal state for deterministic regime tracking."""
    regime: RegimeType
    confidence: float
    exchange_ts_ns: int
    persistence_count: int
    trend_strength: float
    volatility_level: float
    market_efficiency: float
    spread_stress: float


class RegimeDetector:
    """
    Deterministic regime classifier for sleeve authorization and risk modification.
    
    Regime types:
    - TRENDING_BULL: Sustained upward movement with high efficiency
    - TRENDING_BEAR: Sustained downward movement with high efficiency
    - RANGING: Low efficiency market, bounded volatility
    - CRISIS: Extreme volatility, spread widening, liquidity collapse
    - UNKNOWN: Insufficient evidence or ambiguous conditions
    
    Transition discipline:
    - Hysteresis prevents twitchy one-tick flapping
    - Persistence requirements for regime changes
    - Confidence is truthfully degraded when established regimes are threatened
    """

    def __init__(
        self,
        config: Optional[Union[Dict[str, Any], Any]] = None,
        symbol: Optional[str] = None,
    ):
        """
        Initialize regime detector with optional configuration.
        """
        self.symbol = symbol

        # Configuration with bounded defaults
        self.hysteresis_bars = DEFAULT_HYSTERESIS_BARS
        self.min_history_bars = DEFAULT_MIN_HISTORY_BARS
        
        # Strengthened thresholds
        self.mer_threshold = 0.35             # Market Efficiency required for trend
        self.crisis_volatility_threshold = 0.70
        self.ranging_volatility_cap = 0.45
        self.crisis_spread_threshold = 0.60
        self.crisis_liquidity_threshold = 0.25
        
        if config is not None:
            if isinstance(config, dict):
                self.hysteresis_bars = config.get('hysteresis_bars', DEFAULT_HYSTERESIS_BARS)
                self.min_history_bars = config.get('min_history_bars', DEFAULT_MIN_HISTORY_BARS)
                self.mer_threshold = config.get('mer_threshold', 0.35)
                self.crisis_volatility_threshold = config.get('crisis_volatility_threshold', 0.70)
                self.ranging_volatility_cap = config.get('ranging_volatility_cap', 0.45)
                self.crisis_spread_threshold = config.get('crisis_spread_threshold', 0.60)
                self.crisis_liquidity_threshold = config.get('crisis_liquidity_threshold', 0.25)
            else:
                self.hysteresis_bars = getattr(config, 'hysteresis_bars', DEFAULT_HYSTERESIS_BARS)
                self.min_history_bars = getattr(config, 'min_history_bars', DEFAULT_MIN_HISTORY_BARS)
                self.mer_threshold = getattr(config, 'mer_threshold', 0.35)
                self.crisis_volatility_threshold = getattr(config, 'crisis_volatility_threshold', 0.70)
                self.ranging_volatility_cap = getattr(config, 'ranging_volatility_cap', 0.45)
                self.crisis_spread_threshold = getattr(config, 'crisis_spread_threshold', 0.60)
                self.crisis_liquidity_threshold = getattr(config, 'crisis_liquidity_threshold', 0.25)
        
        # Rolling history for evidence
        self._price_history: Deque[float] = deque(maxlen=self.min_history_bars * 2)
        self._volatility_history: Deque[float] = deque(maxlen=self.min_history_bars * 2)
        self._volume_history: Deque[float] = deque(maxlen=self.min_history_bars * 2)
        self._spread_history: Deque[float] = deque(maxlen=self.min_history_bars * 2)
        self._liquidity_history: Deque[float] = deque(maxlen=self.min_history_bars * 2)
        self._timestamp_history: Deque[int] = deque(maxlen=self.min_history_bars * 2)
        
        # Current regime state
        self._current_state: Optional[CachedRegimeState] = None
        self._pending_regime: Optional[RegimeType] = None
        self._pending_count: int = 0
        
        # Transition tracking
        self._regime_history: Deque[RegimeType] = deque(maxlen=self.hysteresis_bars)
        
        # Last output cache
        self._last_regime: RegimeType = RegimeType.UNKNOWN
        self._last_confidence: float = 0.0
        self._last_timestamp_ns: int = 0
        self._last_evidence: Optional[RegimeEvidence] = None

    # ========================================================================
    # Public API
    # ========================================================================

    def update(
        self,
        price: float,
        volume: float,
        bid_price: float,
        ask_price: float,
        bid_depth: float,
        ask_depth: float,
        exchange_ts_ns: int,
    ) -> Tuple[RegimeType, float]:
        """
        Update regime detector with new market data.
        """
        # Update histories
        self._price_history.append(price)
        self._volume_history.append(volume)
        self._timestamp_history.append(exchange_ts_ns)
        
        # Compute spread and liquidity
        spread = (ask_price - bid_price) / max(price, EPS)
        total_depth = bid_depth + ask_depth
        liquidity = min(1.0, total_depth / 1_000_000.0)  # Normalize, 1M as full
        
        self._spread_history.append(spread)
        self._liquidity_history.append(liquidity)
        
        # Compute rolling volatility if enough history
        volatility = 0.0
        if len(self._price_history) >= 10:
            prices = list(self._price_history)[-10:]
            returns = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices)) if prices[i-1] > 0]
            if returns:
                volatility = min(1.0, float(np.std(returns)) * 100.0)
        self._volatility_history.append(volatility)
        
        # Compute evidence
        evidence = self._compute_evidence(volatility)
        self._last_evidence = evidence
        
        # Classify regime from evidence
        raw_regime, raw_confidence = self._classify_from_evidence(evidence)
        
        # Apply hysteresis and persistence
        final_regime, final_confidence = self._apply_transition_discipline(raw_regime, raw_confidence)
        
        # Store state
        self._current_state = CachedRegimeState(
            regime=final_regime,
            confidence=final_confidence,
            exchange_ts_ns=exchange_ts_ns,
            persistence_count=self._pending_count,
            trend_strength=evidence.price_trend,
            volatility_level=evidence.volatility,
            market_efficiency=evidence.market_efficiency,
            spread_stress=evidence.spread_widening,
        )
        
        self._last_regime = final_regime
        self._last_confidence = final_confidence
        self._last_timestamp_ns = exchange_ts_ns
        
        return final_regime, final_confidence

    def update_candles(
        self,
        candles: List[Dict[str, Any]],
        exchange_ts_ns: int,
    ) -> Tuple[RegimeType, float]:
        """
        Alternative update method for candle-based callers.
        Provides a strictly degraded L1 fallback without hallucinating L2 microstructure truth.
        """
        if not candles:
            return self._last_regime, self._last_confidence
        
        latest = candles[-1]
        price = float(latest.get('close', 0.0))
        volume = float(latest.get('volume', 0.0))
        
        # Degraded L1 Fallback:
        # We do not guess spread or depth splits. Spread strictly defaults to 0.0
        # and total volume serves as the sole liquidity proxy.
        bid_price = price
        ask_price = price
        bid_depth = volume
        ask_depth = 0.0
        
        return self.update(price, volume, bid_price, ask_price, bid_depth, ask_depth, exchange_ts_ns)

    def get_current_regime(self) -> RegimeType:
        """Get the most recent regime classification."""
        return self._last_regime

    def get_current_confidence(self) -> float:
        """Get the confidence of the most recent classification."""
        return self._last_confidence

    def get_regime_state(self) -> Optional[CachedRegimeState]:
        """Get full cached regime state."""
        return self._current_state

    def should_authorize_sleeve(self, sleeve_name: str, regime: Optional[RegimeType] = None) -> bool:
        """
        Determine if a sleeve should be authorized.
        
        Upgraded Authorization:
        Evaluates both the hard categorical regime and the continuous underlying evidence.
        Suppresses strategies safely before a full CRISIS confirmation if conditions are severely degraded.
        """
        effective_regime = regime if regime is not None else self._last_regime
        ev = self._last_evidence
        
        # If we have continuous evidence, we can apply smarter safety bounds
        if ev is not None:
            is_high_stress = ev.volatility > self.crisis_volatility_threshold * 0.9 or ev.spread_widening > 0.8
            is_highly_efficient = ev.market_efficiency > 0.5
        else:
            is_high_stress = effective_regime == RegimeType.CRISIS
            is_highly_efficient = effective_regime in (RegimeType.TRENDING_BULL, RegimeType.TRENDING_BEAR)

        if sleeve_name == "shadow_front":
            # Shadow front requires normal market mechanics (not high stress)
            return effective_regime != RegimeType.CRISIS and not is_high_stress
            
        elif sleeve_name == "liquidity_void":
            # Liquidity void thrives in range expansions and actual crises
            return effective_regime in (RegimeType.RANGING, RegimeType.CRISIS) or is_high_stress
            
        elif sleeve_name == "gamma_front":
            # Gamma front thrives on expansion/momentum
            return effective_regime in (RegimeType.TRENDING_BULL, RegimeType.TRENDING_BEAR) or (is_highly_efficient and not is_high_stress)
            
        elif sleeve_name == "sector_rotation":
            # Sector rotation demands stable trends
            return effective_regime in (RegimeType.TRENDING_BULL, RegimeType.TRENDING_BEAR)
        
        return False

    def get_risk_modifier(self, regime: Optional[RegimeType] = None) -> float:
        """
        Get risk multiplier based on current regime and underlying evidence.
        
        Returns:
            Risk modifier in [0, 1], where 1 = full risk, 0 = no risk.
        """
        effective_regime = regime if regime is not None else self._last_regime
        ev = self._last_evidence
        
        base_modifier = 0.3
        
        if effective_regime == RegimeType.CRISIS:
            base_modifier = 0.1
        elif effective_regime == RegimeType.RANGING:
            base_modifier = 0.5
        elif effective_regime in (RegimeType.TRENDING_BULL, RegimeType.TRENDING_BEAR):
            base_modifier = 1.0

        # Continuous penalty application if evidence exists
        if ev is not None:
            # Penalize risk smoothly as spread widens or volatility approaches crisis
            stress_penalty = max(0.0, min(0.5, ev.spread_widening * 0.5))
            vol_penalty = max(0.0, min(0.5, (ev.volatility / max(self.crisis_volatility_threshold, EPS)) * 0.3))
            
            modified_risk = base_modifier * (1.0 - stress_penalty - vol_penalty)
            return max(0.05, min(1.0, modified_risk))
            
        return base_modifier

    # ========================================================================
    # Internal Methods (Deterministic Math & Evidence)
    # ========================================================================

    def _calc_safe_slope(self, data: List[float]) -> float:
        """
        Deterministic, safe linear regression slope calculation.
        Avoids np.polyfit RankWarnings on flat arrays.
        """
        n = len(data)
        if n < 2:
            return 0.0
        x_mean = (n - 1) / 2.0
        y_mean = sum(data) / n
        num = sum((i - x_mean) * (data[i] - y_mean) for i in range(n))
        den = sum((i - x_mean) ** 2 for i in range(n))
        if den == 0:
            return 0.0
        return num / den

    def _calc_market_efficiency(self, data: List[float]) -> float:
        """
        Kaufman's Efficiency Ratio (Direction / Volatility).
        Distinguishes true structural trend from highly volatile chop.
        """
        if len(data) < 2:
            return 0.0
        direction = abs(data[-1] - data[0])
        volatility = sum(abs(data[i] - data[i-1]) for i in range(1, len(data)))
        if volatility == 0:
            return 0.0
        return direction / volatility

    def _compute_evidence(self, current_volatility: float) -> RegimeEvidence:
        """Compute structural regime evidence from historical data."""
        n = len(self._price_history)
        
        price_trend = 0.0
        market_efficiency = 0.0
        
        if n >= self.min_history_bars:
            prices = list(self._price_history)[-self.min_history_bars:]
            
            # Safe slope
            slope = self._calc_safe_slope(prices)
            price_range = max(prices) - min(prices)
            if price_range > 0:
                price_trend = max(-1.0, min(1.0, (slope / price_range) * 10.0))
                
            # Market Efficiency Ratio (Trend vs Noise)
            market_efficiency = self._calc_market_efficiency(prices)
        
        # Volume trend
        volume_trend = 0.0
        if len(self._volume_history) >= self.min_history_bars:
            volumes = list(self._volume_history)[-self.min_history_bars:]
            slope = self._calc_safe_slope(volumes)
            vol_mean = sum(volumes) / len(volumes) if volumes else 1.0
            if vol_mean > 0:
                volume_trend = max(-1.0, min(1.0, (slope / vol_mean) * 5.0))
        
        # Spread widening trend
        spread_widening = 0.0
        if len(self._spread_history) >= self.min_history_bars:
            spreads = list(self._spread_history)[-self.min_history_bars:]
            if len(spreads) > 1 and spreads[0] > 0:
                spread_widening = max(0.0, min(1.0, (spreads[-1] - spreads[0]) / spreads[0]))
        
        # Current liquidity depth
        liquidity_depth = self._liquidity_history[-1] if self._liquidity_history else 0.5
        
        return RegimeEvidence(
            price_trend=price_trend,
            market_efficiency=market_efficiency,
            volatility=current_volatility,
            volume_trend=volume_trend,
            spread_widening=spread_widening,
            liquidity_depth=liquidity_depth,
            exchange_ts_ns=self._timestamp_history[-1] if self._timestamp_history else 0,
        )

    def _classify_from_evidence(self, evidence: RegimeEvidence) -> Tuple[RegimeType, float]:
        """
        Classify regime from evidence with confidence scoring.
        Upgraded to utilize Market Efficiency to distinguish ranging from trending.
        """
        # Crisis detection (highest priority)
        crisis_score = 0.0
        if evidence.volatility > self.crisis_volatility_threshold:
            crisis_score += 0.5
        if evidence.spread_widening > self.crisis_spread_threshold:
            crisis_score += 0.3
        if evidence.liquidity_depth < self.crisis_liquidity_threshold:
            crisis_score += 0.2
        
        if crisis_score > 0.6:
            confidence = min(0.9, 0.5 + crisis_score * 0.4)
            return RegimeType.CRISIS, confidence
        
        # Trending detection (requires Market Efficiency + Direction)
        volume_confirmation = evidence.volume_trend * np.sign(evidence.price_trend) if evidence.price_trend != 0 else 0
        
        if evidence.market_efficiency >= self.mer_threshold and evidence.volatility < self.crisis_volatility_threshold:
            trend_confidence = 0.5 + evidence.market_efficiency * 0.3 + max(0.0, float(volume_confirmation)) * 0.2
            trend_confidence = min(0.9, trend_confidence)
            
            if evidence.price_trend > 0:
                return RegimeType.TRENDING_BULL, trend_confidence
            else:
                return RegimeType.TRENDING_BEAR, trend_confidence
        
        # Ranging detection (Low efficiency, bounded volatility)
        if evidence.market_efficiency < self.mer_threshold and evidence.volatility <= self.ranging_volatility_cap:
            ranging_confidence = 0.4 + (1.0 - evidence.volatility / max(self.ranging_volatility_cap, EPS)) * 0.3
            ranging_confidence = min(0.7, ranging_confidence)
            return RegimeType.RANGING, ranging_confidence
        
        # Unknown / ambiguous transition zone
        unknown_confidence = 0.3
        return RegimeType.UNKNOWN, unknown_confidence

    def _apply_transition_discipline(self, new_regime: RegimeType, new_confidence: float) -> Tuple[RegimeType, float]:
        """
        Apply hysteresis and persistence to prevent regime flapping.
        While pending, the current regime's confidence is truthfully degraded.
        """
        current_regime = self._last_regime
        
        # No previous state
        if current_regime == RegimeType.UNKNOWN and self._current_state is None:
            self._regime_history.append(new_regime)
            self._pending_regime = new_regime
            self._pending_count = 1
            return new_regime, new_confidence
        
        # Same regime: accumulate persistence, restore confidence
        if new_regime == current_regime:
            self._regime_history.append(new_regime)
            self._pending_regime = None
            self._pending_count = 0
            return new_regime, new_confidence
        
        # Regime change: require hysteresis
        self._regime_history.append(new_regime)
        
        if self._pending_regime == new_regime:
            self._pending_count += 1
        else:
            self._pending_regime = new_regime
            self._pending_count = 1
        
        # Require persistence before switching
        if self._pending_count >= self.hysteresis_bars:
            recent_hist = list(self._regime_history)[-self.hysteresis_bars:]
            agreement = sum(1 for r in recent_hist if r == new_regime) / len(recent_hist)
            
            if agreement >= 0.6:
                self._pending_count = 0
                self._pending_regime = None
                return new_regime, new_confidence
        
        # Not enough evidence yet: stay in current regime, but structurally degrade its confidence
        # because a new regime is actively challenging it. Max penalty is -20% just before threshold.
        penalty_factor = 1.0 - (0.2 * (self._pending_count / max(1, self.hysteresis_bars)))
        threatened_confidence = self._last_confidence * penalty_factor
        
        return current_regime, max(0.0, threatened_confidence)

    def reset(self) -> None:
        """Reset all internal state for deterministic replay safety."""
        self._price_history.clear()
        self._volatility_history.clear()
        self._volume_history.clear()
        self._spread_history.clear()
        self._liquidity_history.clear()
        self._timestamp_history.clear()
        self._regime_history.clear()
        self._current_state = None
        self._pending_regime = None
        self._pending_count = 0
        self._last_regime = RegimeType.UNKNOWN
        self._last_confidence = 0.0
        self._last_timestamp_ns = 0
        self._last_evidence = None
