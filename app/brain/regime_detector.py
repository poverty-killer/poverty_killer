"""
app/brain/regime_detector.py

Deterministic, replay-safe regime detection for Poverty Killer.
Classifies market structure into operationally meaningful regimes that drive
sleeve authorization, risk modification, and transition discipline.

Role: Sleeve authorization system + risk modifier.
NOT: decorative labeler, entropy duplicate, direction engine.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Deque, Union
from collections import deque
import numpy as np

from app.models.enums import RegimeType


# Bounded local defaults (not dependent on unproven constants)
DEFAULT_HYSTERESIS_BARS = 3
DEFAULT_MIN_HISTORY_BARS = 20


@dataclass
class RegimeEvidence:
    """Raw evidence for regime classification."""
    price_trend: float          # Normalized trend strength [-1, 1]
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


class RegimeDetector:
    """
    Deterministic regime classifier for sleeve authorization and risk modification.
    
    Regime types:
    - TRENDING_BULL: Sustained upward movement with volume confirmation
    - TRENDING_BEAR: Sustained downward movement with volume confirmation
    - RANGING: Sideways market with bounded volatility
    - CRISIS: Extreme volatility, spread widening, liquidity collapse
    - UNKNOWN: Insufficient evidence or ambiguous conditions
    
    Transition discipline:
    - Hysteresis prevents twitchy one-tick flapping
    - Persistence requirements for regime changes
    - Confidence reflects evidence quality and stability
    """

    def __init__(self, config: Optional[Union[Dict[str, any], any]] = None):
        """
        Initialize regime detector with optional configuration.
        
        Args:
            config: Either a dict with configuration keys or an object with
                    attribute-style configuration. Supports both calling patterns.
        """
        # Configuration with bounded defaults
        self.hysteresis_bars = DEFAULT_HYSTERESIS_BARS
        self.min_history_bars = DEFAULT_MIN_HISTORY_BARS
        self.trend_threshold = 0.3
        self.crisis_volatility_threshold = 0.7
        self.ranging_volatility_cap = 0.4
        self.crisis_spread_threshold = 0.6
        self.crisis_liquidity_threshold = 0.3
        
        if config is not None:
            if isinstance(config, dict):
                self.hysteresis_bars = config.get('hysteresis_bars', DEFAULT_HYSTERESIS_BARS)
                self.min_history_bars = config.get('min_history_bars', DEFAULT_MIN_HISTORY_BARS)
                self.trend_threshold = config.get('trend_threshold', 0.3)
                self.crisis_volatility_threshold = config.get('crisis_volatility_threshold', 0.7)
                self.ranging_volatility_cap = config.get('ranging_volatility_cap', 0.4)
                self.crisis_spread_threshold = config.get('crisis_spread_threshold', 0.6)
                self.crisis_liquidity_threshold = config.get('crisis_liquidity_threshold', 0.3)
            else:
                if hasattr(config, 'hysteresis_bars'):
                    self.hysteresis_bars = getattr(config, 'hysteresis_bars', DEFAULT_HYSTERESIS_BARS)
                if hasattr(config, 'min_history_bars'):
                    self.min_history_bars = getattr(config, 'min_history_bars', DEFAULT_MIN_HISTORY_BARS)
                if hasattr(config, 'trend_threshold'):
                    self.trend_threshold = getattr(config, 'trend_threshold', 0.3)
                if hasattr(config, 'crisis_volatility_threshold'):
                    self.crisis_volatility_threshold = getattr(config, 'crisis_volatility_threshold', 0.7)
                if hasattr(config, 'ranging_volatility_cap'):
                    self.ranging_volatility_cap = getattr(config, 'ranging_volatility_cap', 0.4)
                if hasattr(config, 'crisis_spread_threshold'):
                    self.crisis_spread_threshold = getattr(config, 'crisis_spread_threshold', 0.6)
                if hasattr(config, 'crisis_liquidity_threshold'):
                    self.crisis_liquidity_threshold = getattr(config, 'crisis_liquidity_threshold', 0.3)
        
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
        
        Args:
            price: Current mid price or last price
            volume: Current volume (or volume profile)
            bid_price: Best bid price
            ask_price: Best ask price
            bid_depth: Cumulative bid depth at best
            ask_depth: Cumulative ask depth at best
            exchange_ts_ns: Exchange timestamp in nanoseconds
        
        Returns:
            Tuple of (regime, confidence)
        """
        # Update histories
        self._price_history.append(price)
        self._volume_history.append(volume)
        self._timestamp_history.append(exchange_ts_ns)
        
        # Compute spread and liquidity
        spread = (ask_price - bid_price) / price if price > 0 else 0.0
        total_depth = bid_depth + ask_depth
        liquidity = min(1.0, total_depth / 1_000_000.0)  # Normalize, 1M as full
        
        self._spread_history.append(spread)
        self._liquidity_history.append(liquidity)
        
        # Compute rolling volatility if enough history
        volatility = 0.0
        if len(self._price_history) >= 10:
            prices = list(self._price_history)[-10:]
            if len(prices) > 1:
                returns = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices)) if prices[i-1] > 0]
                returns = [r for r in returns if not np.isnan(r)]
                if returns:
                    volatility = min(1.0, np.std(returns) * 100.0)
        self._volatility_history.append(volatility)
        
        # Compute evidence
        evidence = self._compute_evidence(volatility)
        
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
        )
        
        self._last_regime = final_regime
        self._last_confidence = final_confidence
        self._last_timestamp_ns = exchange_ts_ns
        
        return final_regime, final_confidence

    def update_candles(
        self,
        candles: List[Dict[str, any]],
        exchange_ts_ns: int,
    ) -> Tuple[RegimeType, float]:
        """
        Alternative update method for candle-based callers.
        
        Args:
            candles: List of candle dicts with 'close', 'volume' keys
            exchange_ts_ns: Exchange timestamp in nanoseconds
        
        Returns:
            Tuple of (regime, confidence)
        """
        if not candles:
            return self._last_regime, self._last_confidence
        
        # Use latest candle data
        latest = candles[-1]
        price = latest.get('close', 0.0)
        volume = latest.get('volume', 0.0)
        
        # Estimate bid/ask from price (simple spread estimate)
        spread_estimate = 0.001  # 10bps default spread
        bid_price = price * (1 - spread_estimate / 2)
        ask_price = price * (1 + spread_estimate / 2)
        
        # Estimate depth from volume
        bid_depth = volume * 0.5
        ask_depth = volume * 0.5
        
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
        Determine if a sleeve should be authorized based on current regime.
        
        Sleeve authorization rules:
        - shadow_front: Authorized in all non-crisis regimes (requires entropy unlock separately)
        - liquidity_void: Authorized in ranging and crisis regimes
        - gamma_front: Authorized in trending regimes
        - sector_rotation: Authorized in trending regimes
        """
        effective_regime = regime if regime is not None else self._last_regime
        
        if sleeve_name == "shadow_front":
            return effective_regime != RegimeType.CRISIS
        elif sleeve_name == "liquidity_void":
            return effective_regime in (RegimeType.RANGING, RegimeType.CRISIS)
        elif sleeve_name == "gamma_front":
            return effective_regime in (RegimeType.TRENDING_BULL, RegimeType.TRENDING_BEAR)
        elif sleeve_name == "sector_rotation":
            return effective_regime in (RegimeType.TRENDING_BULL, RegimeType.TRENDING_BEAR)
        
        return False

    def get_risk_modifier(self, regime: Optional[RegimeType] = None) -> float:
        """
        Get risk multiplier based on current regime.
        
        Returns:
            Risk modifier in [0, 1], where 1 = full risk, 0 = no risk.
        """
        effective_regime = regime if regime is not None else self._last_regime
        
        if effective_regime == RegimeType.CRISIS:
            return 0.1
        elif effective_regime == RegimeType.RANGING:
            return 0.5
        elif effective_regime in (RegimeType.TRENDING_BULL, RegimeType.TRENDING_BEAR):
            return 1.0
        else:
            return 0.3

    # ========================================================================
    # Internal Methods
    # ========================================================================

    def _compute_evidence(self, current_volatility: float) -> RegimeEvidence:
        """Compute regime evidence from historical data."""
        n = len(self._price_history)
        
        # Price trend using linear regression on last N points
        price_trend = 0.0
        if n >= self.min_history_bars:
            prices = list(self._price_history)[-self.min_history_bars:]
            x = np.arange(len(prices))
            slope = np.polyfit(x, prices, 1)[0]
            price_range = max(prices) - min(prices)
            if price_range > 0:
                price_trend = np.clip(slope / price_range * 10.0, -1.0, 1.0)
        
        # Volume trend
        volume_trend = 0.0
        if len(self._volume_history) >= self.min_history_bars:
            volumes = list(self._volume_history)[-self.min_history_bars:]
            x = np.arange(len(volumes))
            slope = np.polyfit(x, volumes, 1)[0]
            vol_mean = np.mean(volumes) if volumes else 1.0
            if vol_mean > 0:
                volume_trend = np.clip(slope / vol_mean * 5.0, -1.0, 1.0)
        
        # Spread widening trend
        spread_widening = 0.0
        if len(self._spread_history) >= self.min_history_bars:
            spreads = list(self._spread_history)[-self.min_history_bars:]
            if len(spreads) > 1 and spreads[0] > 0:
                spread_widening = np.clip((spreads[-1] - spreads[0]) / spreads[0], 0.0, 1.0)
        
        # Current liquidity depth
        liquidity_depth = self._liquidity_history[-1] if self._liquidity_history else 0.5
        
        return RegimeEvidence(
            price_trend=price_trend,
            volatility=current_volatility,
            volume_trend=volume_trend,
            spread_widening=spread_widening,
            liquidity_depth=liquidity_depth,
            exchange_ts_ns=self._timestamp_history[-1] if self._timestamp_history else 0,
        )

    def _classify_from_evidence(self, evidence: RegimeEvidence) -> Tuple[RegimeType, float]:
        """
        Classify regime from evidence with confidence scoring.
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
        
        # Trending detection
        trend_abs = abs(evidence.price_trend)
        volume_confirmation = evidence.volume_trend * np.sign(evidence.price_trend) if evidence.price_trend != 0 else 0
        
        if trend_abs > self.trend_threshold and evidence.volatility < self.crisis_volatility_threshold:
            trend_confidence = 0.5 + trend_abs * 0.4 + max(0, volume_confirmation) * 0.1
            trend_confidence = min(0.9, trend_confidence)
            
            if evidence.price_trend > 0:
                return RegimeType.TRENDING_BULL, trend_confidence
            else:
                return RegimeType.TRENDING_BEAR, trend_confidence
        
        # Ranging detection
        if evidence.volatility <= self.ranging_volatility_cap and trend_abs < self.trend_threshold:
            ranging_confidence = 0.4 + (1.0 - evidence.volatility / self.ranging_volatility_cap) * 0.3
            ranging_confidence = min(0.7, ranging_confidence)
            return RegimeType.RANGING, ranging_confidence
        
        # Unknown / insufficient evidence
        unknown_confidence = 0.3
        return RegimeType.UNKNOWN, unknown_confidence

    def _apply_transition_discipline(self, new_regime: RegimeType, new_confidence: float) -> Tuple[RegimeType, float]:
        """
        Apply hysteresis and persistence to prevent regime flapping.
        During pending transitions, confidence is truthfully reduced.
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
        
        # Check if we have enough consecutive evidence for the new regime
        if self._pending_regime == new_regime:
            self._pending_count += 1
        else:
            self._pending_regime = new_regime
            self._pending_count = 1
        
        # During pending transition, confidence is truthfully reduced
        # This prevents stale certainty while regime is ambiguous
        pending_confidence = new_confidence * (self._pending_count / self.hysteresis_bars)
        
        # Require persistence before switching
        if self._pending_count >= self.hysteresis_bars:
            # Also verify the majority of recent history agrees
            recent_hist = list(self._regime_history)[-self.hysteresis_bars:]
            agreement = sum(1 for r in recent_hist if r == new_regime) / len(recent_hist)
            
            if agreement >= 0.6:
                self._pending_count = 0
                self._pending_regime = None
                return new_regime, new_confidence
        
        # Not enough evidence yet: stay in current regime with pending confidence
        return current_regime, self._last_confidence * 0.8 if self._pending_count > 0 else self._last_confidence

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