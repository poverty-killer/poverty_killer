"""
Regime Detector - Deterministic Market State Classification
CITADEL GRADE — CONTRACT-COMPLIANT · REPLAY-SAFE · DETERMINISTIC

ANALYTICAL/NON-MONETARY BOUNDARY:
This file performs analytical regime detection using float64 for performance.
It is NOT used for monetary truth, risk, or accounting calculations.

CORE INNOVATIONS (NONE EXIST IN STANDARD LIBRARIES):
1. Multi-timescale trend persistence fingerprinting
2. Volatility regime with structural breakdown detection
3. Range-bound with micro-structure confirmation
4. Hysteresis-based transition gating (prevents flip-flop)
5. Confidence-weighted output with stability scoring
"""

import logging
import math
from typing import Optional, Dict, Any, Tuple, List
from dataclasses import dataclass
from collections import deque
from enum import Enum

logger = logging.getLogger(__name__)


class MacroRegime(Enum):
    """Market regime classification."""
    TRENDING_BULL = "trending_bull"
    TRENDING_BEAR = "trending_bear"
    RANGING = "ranging"
    CRISIS = "crisis"
    UNKNOWN = "unknown"


@dataclass
class RegimeState:
    """Internal state container."""
    regime: MacroRegime
    confidence: float
    timestamp_ns: int
    transition_count: int
    stability_score: float
    persistence_bars: int


class RegimeDetector:
    """
    Deterministic market regime detector.
    
    UNIQUE FEATURES:
    - Multi-timescale trend persistence (short + medium + long)
    - Volatility regime with structural breakdown flags
    - Range-bound with micro-structure confirmation
    - Hysteresis gating (requires sustained evidence)
    - Confidence degradation under ambiguity
    """
    
    # ========== TREND PARAMETERS ==========
    TREND_WINDOW_SHORT = 20
    TREND_WINDOW_MEDIUM = 50
    TREND_WINDOW_LONG = 100
    
    TREND_STRONG_THRESHOLD = 0.65
    TREND_WEAK_THRESHOLD = 0.45
    
    # ========== VOLATILITY PARAMETERS ==========
    VOL_HIGH_THRESHOLD = 0.35
    VOL_LOW_THRESHOLD = 0.12
    VOL_SPIKE_FACTOR = 2.5
    
    # ========== CRISIS PARAMETERS ==========
    CRISIS_DRAWDOWN_THRESHOLD = -0.08
    CRISIS_CONSECUTIVE_DOWN = 4
    CRISIS_VOL_EXPANSION = 1.8
    
    # ========== RANGE PARAMETERS ==========
    RANGE_WIDTH_MAX = 0.08
    RANGE_POSITION_IDEAL = 0.3
    RANGE_BOUNCE_CONSISTENCY = 0.6
    
    # ========== HYSTERESIS ==========
    TRANSITION_PERSISTENCE = 3
    STABILITY_WINDOW = 10
    
    # ========== CONFIDENCE ==========
    MIN_SAMPLES = 30
    HIGH_CONF_SAMPLES = 100
    
    # ========== HISTORY MANAGEMENT ==========
    MAX_HISTORY_SECONDS = 600
    PRICE_HISTORY_MAXLEN = 2000
    
    def __init__(self):
        """Initialize deterministic regime detector."""
        self._price_history: Dict[str, deque] = {}
        self._return_history: Dict[str, deque] = {}
        self._timestamp_history: Dict[str, deque] = {}
        self._high_history: Dict[str, deque] = {}
        self._low_history: Dict[str, deque] = {}
        
        self._current_state: Dict[str, Optional[RegimeState]] = {}
        self._state_history: Dict[str, deque] = {}
        self._signal_buffer: Dict[str, List[MacroRegime]] = {}
        
        logger.info("RegimeDetector v3 initialized")
    
    def update(
        self,
        symbol: str,
        price: float,
        high: Optional[float],
        low: Optional[float],
        timestamp_ns: int
    ) -> RegimeState:
        """
        Update regime detection with new price data.
        
        Args:
            symbol: Trading symbol
            price: Current price
            high: High price for period (optional, for range detection)
            low: Low price for period (optional, for range detection)
            timestamp_ns: Nanosecond timestamp (replay-safe)
        """
        self._init_symbol(symbol)
        
        # Store price data with aligned timestamps
        self._price_history[symbol].append(price)
        self._timestamp_history[symbol].append(timestamp_ns)
        
        if high is not None:
            self._high_history[symbol].append(high)
        if low is not None:
            self._low_history[symbol].append(low)
        
        # Calculate return using aligned price sequence
        if len(self._price_history[symbol]) >= 2:
            prev_price = self._price_history[symbol][-2]
            ret = (price - prev_price) / prev_price if prev_price > 0 else 0.0
            self._return_history[symbol].append(ret)
        
        # Prune old data (aligned across all sequences)
        self._prune_history(symbol, timestamp_ns)
        
        n_prices = len(self._price_history[symbol])
        
        if n_prices < self.MIN_SAMPLES:
            confidence = max(0.0, min(0.4, n_prices / self.MIN_SAMPLES))
            regime = MacroRegime.UNKNOWN
        else:
            # Compute evidence components
            trend_scores = self._compute_multi_timescale_trend(symbol)
            vol_regime = self._compute_volatility_regime(symbol)
            range_score = self._compute_enhanced_range_score(symbol)
            crisis_evidence = self._compute_crisis_evidence(symbol)
            
            # Classify
            regime, confidence = self._classify_regime_enhanced(
                symbol, trend_scores, vol_regime, range_score, crisis_evidence
            )
        
        # Apply hysteresis with signal buffer
        regime, persistence_bars = self._apply_hysteresis_buffered(symbol, regime)
        
        # Compute stability
        stability_score = self._compute_stability_score(symbol)
        
        # Track transitions
        transition_count = 0
        current = self._current_state.get(symbol)
        if current and current.regime != regime:
            transition_count = current.transition_count + 1
            logger.info(f"Regime transition for {symbol}: {current.regime.value} -> {regime.value}")
        
        state = RegimeState(
            regime=regime,
            confidence=confidence,
            timestamp_ns=timestamp_ns,
            transition_count=transition_count,
            stability_score=stability_score,
            persistence_bars=persistence_bars
        )
        
        self._current_state[symbol] = state
        self._state_history[symbol].append(state)
        
        return state
    
    def _init_symbol(self, symbol: str) -> None:
        """Initialize history containers for a symbol."""
        if symbol not in self._price_history:
            self._price_history[symbol] = deque(maxlen=self.PRICE_HISTORY_MAXLEN)
            self._return_history[symbol] = deque(maxlen=self.PRICE_HISTORY_MAXLEN)
            self._timestamp_history[symbol] = deque(maxlen=self.PRICE_HISTORY_MAXLEN)
            self._high_history[symbol] = deque(maxlen=500)
            self._low_history[symbol] = deque(maxlen=500)
            self._signal_buffer[symbol] = []
            self._state_history[symbol] = deque(maxlen=100)
            self._current_state[symbol] = None
    
    def _prune_history(self, symbol: str, current_time_ns: int) -> None:
        """
        Prune old data outside lookback window.
        Maintains alignment across price, return, and timestamp sequences.
        """
        cutoff_ns = current_time_ns - (self.MAX_HISTORY_SECONDS * 1_000_000_000)
        timestamps = self._timestamp_history[symbol]
        
        # Find first index to keep
        keep_idx = 0
        for i, ts in enumerate(timestamps):
            if ts >= cutoff_ns:
                keep_idx = i
                break
        else:
            keep_idx = len(timestamps)
        
        # Prune all aligned sequences simultaneously
        if keep_idx > 0:
            # Convert deques to lists for slicing, then back to deques
            price_list = list(self._price_history[symbol])
            return_list = list(self._return_history[symbol])
            timestamp_list = list(self._timestamp_history[symbol])
            high_list = list(self._high_history[symbol]) if self._high_history[symbol] else None
            low_list = list(self._low_history[symbol]) if self._low_history[symbol] else None
            
            # Slice keeping only recent data
            self._price_history[symbol] = deque(price_list[keep_idx:], maxlen=self.PRICE_HISTORY_MAXLEN)
            self._timestamp_history[symbol] = deque(timestamp_list[keep_idx:], maxlen=self.PRICE_HISTORY_MAXLEN)
            
            # Returns are one shorter than prices, adjust offset
            return_keep_idx = max(0, keep_idx - 1)
            if return_list and return_keep_idx < len(return_list):
                self._return_history[symbol] = deque(return_list[return_keep_idx:], maxlen=self.PRICE_HISTORY_MAXLEN)
            else:
                self._return_history[symbol] = deque(maxlen=self.PRICE_HISTORY_MAXLEN)
            
            if high_list:
                self._high_history[symbol] = deque(high_list[keep_idx:], maxlen=500)
            if low_list:
                self._low_history[symbol] = deque(low_list[keep_idx:], maxlen=500)
    
    def _compute_multi_timescale_trend(self, symbol: str) -> Dict[str, float]:
        """
        Multi-timescale trend fingerprinting.
        Returns scores for short, medium, long term trends.
        """
        prices = list(self._price_history[symbol])
        
        def trend_at_window(window: int) -> float:
            if len(prices) < window:
                return 0.5
            
            recent = prices[-window:]
            x = list(range(len(recent)))
            n = len(recent)
            
            sum_x = sum(x)
            sum_y = sum(recent)
            sum_xy = sum(x[i] * recent[i] for i in range(n))
            sum_x2 = sum(xi * xi for xi in x)
            
            denominator = n * sum_x2 - sum_x * sum_x
            if denominator == 0:
                return 0.5
            
            slope = (n * sum_xy - sum_x * sum_y) / denominator
            slope_normalized = slope / (sum(recent) / n + 1e-10)
            
            # Directional consistency
            returns = [recent[i] - recent[i-1] for i in range(1, len(recent))]
            if not returns:
                return 0.5
            
            positive = sum(1 for r in returns if r > 0)
            consistency = max(positive, len(returns) - positive) / len(returns)
            
            trend = (abs(slope_normalized) * 0.5 + consistency * 0.5)
            return min(1.0, max(0.0, trend))
        
        return {
            "short": trend_at_window(self.TREND_WINDOW_SHORT),
            "medium": trend_at_window(self.TREND_WINDOW_MEDIUM),
            "long": trend_at_window(self.TREND_WINDOW_LONG)
        }
    
    def _compute_volatility_regime(self, symbol: str) -> Dict[str, float]:
        """
        Compute volatility regime with structural breakdown detection.
        """
        returns = list(self._return_history[symbol])
        if len(returns) < 20:
            return {"level": 0.5, "spiking": 0.0, "expanding": 0.0}
        
        recent = returns[-20:]
        mean_ret = sum(recent) / len(recent)
        variance = sum((r - mean_ret) ** 2 for r in recent) / len(recent)
        std = math.sqrt(variance)
        
        # Annualized volatility (252 trading days)
        annualized_vol = std * math.sqrt(252)
        vol_level = min(1.0, annualized_vol / 0.4)
        
        # Volatility spike detection
        spiking = 0.0
        if len(returns) >= 40:
            prev = returns[-40:-20]
            if prev:
                prev_mean = sum(prev) / len(prev)
                prev_variance = sum((r - prev_mean) ** 2 for r in prev) / len(prev)
                prev_std = math.sqrt(prev_variance)
                if prev_std > 0:
                    spike_ratio = std / prev_std
                    spiking = min(1.0, max(0.0, (spike_ratio - 1.0) / 2.0))
        
        # Volatility expansion
        expanding = 0.0
        if len(returns) >= 30:
            first = returns[-30:-15]
            second = returns[-15:]
            if first and second:
                first_variance = sum((r - sum(first)/len(first)) ** 2 for r in first) / len(first)
                second_variance = sum((r - sum(second)/len(second)) ** 2 for r in second) / len(second)
                if first_variance > 0:
                    expanding = min(1.0, max(0.0, (second_variance - first_variance) / (first_variance + 1e-10) / 2.0))
        
        return {"level": vol_level, "spiking": spiking, "expanding": expanding}
    
    def _compute_enhanced_range_score(self, symbol: str) -> float:
        """
        Enhanced range-bound detection with micro-structure confirmation.
        """
        prices = list(self._price_history[symbol])
        highs = list(self._high_history.get(symbol, []))
        lows = list(self._low_history.get(symbol, []))
        
        if len(prices) < 40:
            return 0.5
        
        recent_prices = prices[-40:]
        recent_highs = highs[-40:] if len(highs) >= 40 else None
        recent_lows = lows[-40:] if len(lows) >= 40 else None
        
        high = max(recent_prices)
        low = min(recent_prices)
        range_width = (high - low) / ((high + low) / 2 + 1e-10)
        
        # Width penalty
        if range_width > self.RANGE_WIDTH_MAX:
            width_score = 0.0
        else:
            width_score = 1.0 - (range_width / self.RANGE_WIDTH_MAX)
        
        # Position score (price near middle = good for ranging)
        current = recent_prices[-1]
        position = (current - low) / (high - low + 1e-10)
        position_score = 1.0 - abs(position - 0.5) * 2.0
        
        # Bounce consistency
        bounce_score = 0.5
        if recent_highs and recent_lows and len(recent_highs) >= 20:
            bounces = 0
            for i in range(1, len(recent_highs) - 1):
                if recent_highs[i] > recent_highs[i-1] and recent_highs[i] > recent_highs[i+1]:
                    bounces += 1
                if recent_lows[i] < recent_lows[i-1] and recent_lows[i] < recent_lows[i+1]:
                    bounces += 1
            bounce_score = min(1.0, bounces / 20)
        
        combined = (width_score * 0.4 + position_score * 0.3 + bounce_score * 0.3)
        return min(1.0, max(0.0, combined))
    
    def _compute_crisis_evidence(self, symbol: str) -> Dict[str, float]:
        """
        Compute crisis-specific evidence.
        """
        prices = list(self._price_history[symbol])
        returns = list(self._return_history[symbol])
        
        if len(prices) < 30:
            return {"drawdown": 0.0, "momentum_break": 0.0, "vol_expansion": 0.0}
        
        # Drawdown severity
        peak = max(prices[-30:])
        current = prices[-1]
        drawdown = (current - peak) / peak if peak > 0 else 0
        drawdown_score = min(1.0, max(0.0, -drawdown / self.CRISIS_DRAWDOWN_THRESHOLD))
        
        # Momentum breakdown
        breakdown_score = 0.0
        if len(returns) >= 10:
            recent_returns = returns[-10:]
            consecutive_down = 0
            for r in reversed(recent_returns):
                if r < 0:
                    consecutive_down += 1
                else:
                    break
            breakdown_score = min(1.0, consecutive_down / self.CRISIS_CONSECUTIVE_DOWN)
        
        # Volatility expansion
        vol_regime = self._compute_volatility_regime(symbol)
        vol_expansion = vol_regime.get("expanding", 0.0)
        
        return {
            "drawdown": drawdown_score,
            "momentum_break": breakdown_score,
            "vol_expansion": vol_expansion
        }
    
    def _classify_regime_enhanced(
        self,
        symbol: str,
        trend_scores: Dict[str, float],
        vol_regime: Dict[str, float],
        range_score: float,
        crisis_evidence: Dict[str, float]
    ) -> Tuple[MacroRegime, float]:
        """
        Enhanced regime classification with weighted evidence.
        """
        # Crisis detection (highest priority)
        crisis_severity = (
            crisis_evidence["drawdown"] * 0.4 +
            crisis_evidence["momentum_break"] * 0.3 +
            crisis_evidence["vol_expansion"] * 0.3
        )
        
        if crisis_severity > 0.6:
            confidence = 0.7 + crisis_severity * 0.25
            return MacroRegime.CRISIS, min(0.95, confidence)
        
        # Multi-timescale trend consensus
        trend_consensus = (
            trend_scores["short"] * 0.4 +
            trend_scores["medium"] * 0.35 +
            trend_scores["long"] * 0.25
        )
        
        # Volatility adjustment
        vol_penalty = vol_regime["level"] * 0.3
        trend_adjusted = trend_consensus * (1.0 - vol_penalty)
        
        if trend_adjusted > self.TREND_STRONG_THRESHOLD:
            # Determine direction using symbol-local price data
            prices = list(self._price_history.get(symbol, []))
            if len(prices) >= 10:
                recent_prices = prices[-10:]
                if recent_prices[-1] > recent_prices[0]:
                    regime = MacroRegime.TRENDING_BULL
                else:
                    regime = MacroRegime.TRENDING_BEAR
            else:
                regime = MacroRegime.TRENDING_BULL
            
            confidence = 0.65 + trend_adjusted * 0.25
            return regime, min(0.9, confidence)
        
        # Ranging detection
        vol_acceptable = vol_regime["level"] < 0.25
        if range_score > 0.65 and vol_acceptable:
            confidence = 0.55 + range_score * 0.25
            return MacroRegime.RANGING, min(0.85, confidence)
        
        # Unknown / weak evidence
        if trend_adjusted > self.TREND_WEAK_THRESHOLD:
            confidence = 0.4
            return MacroRegime.UNKNOWN, confidence
        
        # Very weak - return unknown with low confidence
        confidence = max(0.2, trend_adjusted * 0.5)
        return MacroRegime.UNKNOWN, min(0.5, confidence)
    
    def _apply_hysteresis_buffered(
        self, 
        symbol: str, 
        proposed_regime: MacroRegime
    ) -> Tuple[MacroRegime, int]:
        """
        Hysteresis with signal buffer. Prevents flip-flop.
        """
        buffer = self._signal_buffer.get(symbol, [])
        buffer.append(proposed_regime)
        
        # Keep last N signals
        if len(buffer) > self.TRANSITION_PERSISTENCE:
            buffer = buffer[-self.TRANSITION_PERSISTENCE:]
        
        self._signal_buffer[symbol] = buffer
        
        if len(buffer) < self.TRANSITION_PERSISTENCE:
            current = self._current_state.get(symbol)
            if current:
                return current.regime, len(buffer)
            return MacroRegime.UNKNOWN, len(buffer)
        
        # Check consensus
        unique_regimes = set(buffer)
        if len(unique_regimes) == 1:
            return proposed_regime, self.TRANSITION_PERSISTENCE
        
        # Most frequent regime in buffer
        from collections import Counter
        counts = Counter(buffer)
        most_common = counts.most_common(1)[0][0]
        
        current = self._current_state.get(symbol)
        if current and most_common == current.regime:
            return current.regime, self.TRANSITION_PERSISTENCE
        
        return most_common, self.TRANSITION_PERSISTENCE
    
    def _compute_stability_score(self, symbol: str) -> float:
        """
        Compute stability score based on recent transition rate.
        """
        history = self._state_history.get(symbol)
        if not history or len(history) < self.STABILITY_WINDOW:
            return 1.0
        
        recent = list(history)[-self.STABILITY_WINDOW:]
        transitions = sum(1 for i in range(1, len(recent)) if recent[i].regime != recent[i-1].regime)
        
        stability = 1.0 - (transitions / self.STABILITY_WINDOW)
        return max(0.0, min(1.0, stability))
    
    def get_current_regime(self, symbol: str) -> MacroRegime:
        """Get current regime for symbol."""
        state = self._current_state.get(symbol)
        return state.regime if state else MacroRegime.UNKNOWN
    
    def get_confidence(self, symbol: str) -> float:
        """Get current confidence for symbol."""
        state = self._current_state.get(symbol)
        return state.confidence if state else 0.0
    
    def get_stability_score(self, symbol: str) -> float:
        """Get current stability score for symbol."""
        state = self._current_state.get(symbol)
        return state.stability_score if state else 1.0
    
    def get_stats(self, symbol: str) -> Dict[str, Any]:
        """Get detailed statistics for symbol."""
        state = self._current_state.get(symbol)
        if not state:
            return {"symbol": symbol, "has_data": False}
        
        return {
            "symbol": symbol,
            "has_data": True,
            "current_regime": state.regime.value,
            "confidence": state.confidence,
            "stability_score": state.stability_score,
            "transition_count": state.transition_count,
            "persistence_bars": state.persistence_bars,
            "state_history_length": len(self._state_history.get(symbol, [])),
            "timestamp_ns": state.timestamp_ns
        }
    
    def reset(self, symbol: str) -> None:
        """Reset all data for a symbol."""
        keys_to_reset = [
            self._price_history, self._return_history, self._timestamp_history,
            self._high_history, self._low_history, self._signal_buffer,
            self._state_history, self._current_state
        ]
        for store in keys_to_reset:
            if symbol in store:
                del store[symbol]