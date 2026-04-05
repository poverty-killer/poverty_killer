"""
Entropy Decoder v5 - Structural Predictability Collapse Detector
CITADEL GRADE — CONTRACT-COMPLIANT · REPLAY-SAFE · DETERMINISTIC · PREDATORY

UNIQUE SIGNATURE:
This decoder distinguishes STRUCTURAL predictability (informed flow) from
BRITTLE monotonicity, OSCILLATORY artifacts, and NOISE collapses.

THREE-PILLAR DISCRIMINATION:
1. Transition Concentration Quality — how concentrated is predictive power?
2. Dominant State Reliability — is predictability from genuine information?
3. Alternation Penalty — penalizes trivial oscillatory patterns

CORE INNOVATIONS:
1. Structural Collapse Score — separates informed flow from brittle/monotonic
2. Transition Concentration — high concentration = genuine predictability
3. Dominant State Reliability — low reliability = spurious collapse
4. Alternation Penalty — oscillatory sequences get downgraded
5. Fragility Score — penalizes collapses with low stability reserve
6. Persistence-Weighted Confidence — bars matter more than raw score
"""

import logging
import math
from decimal import Decimal
from typing import Optional, Dict, List, Any
from collections import deque
from enum import IntEnum

from app.models.entropy_score import EntropyScore
from app.constants import RegimeType

logger = logging.getLogger(__name__)


class CollapseQuality(IntEnum):
    """Graded collapse quality - stored internally only."""
    NONE = 0
    WEAK = 1
    STRUCTURAL = 2
    EXTREME = 3


class EntropyDecoder:
    """
    Structural predictability collapse detector.
    
    UNIQUE METRICS (via get_stats / getters):
    - structural_collapse_score: [0,1] - distinguishes informed from brittle
    - transition_concentration: [0,1] - entropy distribution concentration
    - dominant_state_reliability: [0,1] - probability of most likely transition
    - alternation_penalty: [0,1] - penalty for oscillatory patterns
    - collapse_fragility: [0,1] - how fragile the collapse is
    - persistence_weighted_confidence: [0,1] - confidence × persistence
    """
    
    COLLAPSE_PCT_WEAK = 25.0
    COLLAPSE_PCT_STRUCTURAL = 10.0
    COLLAPSE_PCT_EXTREME = 3.0
    
    SLOPE_COLLAPSE_THRESHOLD = -0.04
    
    PERSISTENCE_WEAK = 3
    PERSISTENCE_STRUCTURAL = 2
    PERSISTENCE_EXTREME = 1
    
    DECAY_HALF_LIFE_NS = 30_000_000_000
    
    SHOCK_ZSCORE_THRESHOLD = 2.5
    
    MIN_TRANSITION_CONCENTRATION = 0.6
    MIN_DOMINANT_RELIABILITY = 0.65
    MAX_ALTERNATION_RATE = 0.4
    
    STABILITY_WINDOW = 20
    
    MIN_SAMPLES_BASE = 50
    MIN_SAMPLES_HIGH_CONF = 200
    
    def __init__(
        self,
        window_seconds: int = 60,
        min_samples: int = 100,
        state_depth: int = 2,
        enable_shock_filter: bool = True,
        enable_persistence: bool = True,
        enable_structural_filter: bool = True
    ):
        self.window_seconds = window_seconds
        self.window_ns = window_seconds * 1_000_000_000
        self.min_samples = min_samples
        self.state_depth = state_depth
        self.enable_shock_filter = enable_shock_filter
        self.enable_persistence = enable_persistence
        self.enable_structural_filter = enable_structural_filter
        
        self.n_states = 2 ** state_depth
        
        self._trade_seq: Dict[str, List[int]] = {}
        self._time_ns_seq: Dict[str, List[int]] = {}
        self._entropy_history: Dict[str, deque] = {}
        self._entropy_timestamps: Dict[str, deque] = {}
        self._magnitude_history: Dict[str, deque] = {}
        
        self._collapse_quality: Dict[str, CollapseQuality] = {}
        self._collapse_persistence: Dict[str, int] = {}
        self._last_quality_change_ns: Dict[str, int] = {}
        
        self._transitions: Dict[str, List[List[int]]] = {}
        self._state_counts: Dict[str, List[int]] = {}
        
        self._last_score: Dict[str, EntropyScore] = {}
        
        self._last_structural_score: Dict[str, float] = {}
        self._last_transition_concentration: Dict[str, float] = {}
        self._last_dominant_reliability: Dict[str, float] = {}
        self._last_alternation_penalty: Dict[str, float] = {}
        self._last_collapse_fragility: Dict[str, float] = {}
        self._last_persistence_weighted_confidence: Dict[str, float] = {}
        self._last_persistence_bars: Dict[str, int] = {}
        self._last_freshness: Dict[str, float] = {}
        self._last_sample_sufficiency: Dict[str, float] = {}
        self._last_is_shock: Dict[str, bool] = {}
        self._last_entropy_slope: Dict[str, float] = {}
        
        logger.info(f"EntropyDecoder v5 initialized")
    
    def update(
        self,
        symbol: str,
        trade_side: int,
        timestamp_ns: int,
        regime: RegimeType = RegimeType.UNKNOWN
    ) -> Optional[EntropyScore]:
        if timestamp_ns <= 0:
            raise ValueError(f"timestamp_ns must be positive, got {timestamp_ns}")
        
        self._init_symbol(symbol)
        
        if trade_side == 0:
            return self._last_score.get(symbol)
        
        binary = 1 if trade_side > 0 else 0
        
        self._trade_seq[symbol].append(binary)
        self._time_ns_seq[symbol].append(timestamp_ns)
        
        self._prune(symbol, timestamp_ns)
        
        if len(self._trade_seq[symbol]) < self.min_samples:
            return None
        
        entropy_float = self._calculate_conditional_entropy(symbol)
        
        self._entropy_history[symbol].append(entropy_float)
        self._entropy_timestamps[symbol].append(timestamp_ns)
        
        transition_concentration = self._calculate_transition_concentration(symbol)
        dominant_reliability = self._calculate_dominant_state_reliability(symbol)
        alternation_penalty = self._calculate_alternation_penalty(symbol)
        entropy_slope = self._calculate_entropy_slope(symbol)
        
        structural_score = self._calculate_structural_score(
            entropy_float, transition_concentration, dominant_reliability, alternation_penalty
        )
        
        base_quality = self._get_base_collapse_quality(symbol, entropy_float)
        
        if self.enable_structural_filter and base_quality != CollapseQuality.NONE:
            if structural_score < 0.4:
                base_quality = CollapseQuality.NONE
            elif structural_score < 0.6 and base_quality == CollapseQuality.STRUCTURAL:
                base_quality = CollapseQuality.WEAK
            elif structural_score >= 0.8 and base_quality == CollapseQuality.WEAK:
                base_quality = CollapseQuality.STRUCTURAL
        
        if entropy_slope < self.SLOPE_COLLAPSE_THRESHOLD and base_quality != CollapseQuality.NONE:
            if base_quality == CollapseQuality.WEAK:
                base_quality = CollapseQuality.STRUCTURAL
            elif base_quality == CollapseQuality.STRUCTURAL:
                base_quality = CollapseQuality.EXTREME
        
        is_shock = False
        if self.enable_shock_filter:
            is_shock = self._detect_shock_volatility_normalized(symbol, entropy_float)
        
        collapse_quality = self._apply_persistence(symbol, base_quality, timestamp_ns)
        
        if is_shock and collapse_quality != CollapseQuality.NONE:
            collapse_quality = CollapseQuality.NONE
        
        collapse_fragility = self._calculate_fragility(
            symbol, collapse_quality, transition_concentration, dominant_reliability, entropy_slope
        )
        
        persistence_bars = self._collapse_persistence.get(symbol, 0)
        persistence_weight = min(1.0, persistence_bars / 5.0)
        
        quality_score = self._quality_to_score(collapse_quality)
        collapse_score = quality_score * (0.5 + 0.3 * persistence_weight) * (1.0 - collapse_fragility * 0.3)
        collapse_score = min(1.0, max(0.0, collapse_score))
        
        magnitude_float = self._predict_magnitude_enhanced(
            entropy_float, collapse_score, entropy_slope, collapse_fragility, regime
        )
        
        base_confidence = self._calculate_base_confidence(
            symbol, entropy_float, collapse_quality, structural_score,
            transition_concentration, dominant_reliability, entropy_slope, regime
        )
        persistence_weighted_confidence = base_confidence * (0.6 + 0.4 * persistence_weight)
        confidence_float = min(0.95, max(0.05, persistence_weighted_confidence))
        
        self._magnitude_history[symbol].append(magnitude_float)
        
        entropy_decimal = Decimal(str(round(entropy_float, 10)))
        magnitude_decimal = Decimal(str(round(magnitude_float, 10)))
        confidence_decimal = Decimal(str(round(confidence_float, 10)))
        
        result = EntropyScore(
            symbol=symbol,
            timestamp=timestamp_ns,
            entropy=entropy_decimal,
            is_collapsed=(collapse_quality != CollapseQuality.NONE),
            predicted_magnitude=magnitude_decimal,
            confidence=confidence_decimal,
            samples_used=len(self._trade_seq[symbol])
        )
        
        self._last_score[symbol] = result
        
        freshness = self._calculate_freshness(symbol, timestamp_ns)
        sample_sufficiency = min(1.0, len(self._trade_seq[symbol]) / self.MIN_SAMPLES_HIGH_CONF)
        
        self._last_structural_score[symbol] = structural_score
        self._last_transition_concentration[symbol] = transition_concentration
        self._last_dominant_reliability[symbol] = dominant_reliability
        self._last_alternation_penalty[symbol] = alternation_penalty
        self._last_collapse_fragility[symbol] = collapse_fragility
        self._last_persistence_weighted_confidence[symbol] = persistence_weighted_confidence
        self._last_persistence_bars[symbol] = persistence_bars
        self._last_freshness[symbol] = freshness
        self._last_sample_sufficiency[symbol] = sample_sufficiency
        self._last_is_shock[symbol] = is_shock
        self._last_entropy_slope[symbol] = entropy_slope
        
        return result
    
    def get_current(self, symbol: str) -> Optional[EntropyScore]:
        return self._last_score.get(symbol)
    
    def get_collapse_quality(self, symbol: str) -> CollapseQuality:
        return self._collapse_quality.get(symbol, CollapseQuality.NONE)
    
    def get_structural_score(self, symbol: str) -> float:
        return self._last_structural_score.get(symbol, 0.0)
    
    def get_transition_concentration(self, symbol: str) -> float:
        return self._last_transition_concentration.get(symbol, 0.0)
    
    def get_dominant_reliability(self, symbol: str) -> float:
        return self._last_dominant_reliability.get(symbol, 0.0)
    
    def get_alternation_penalty(self, symbol: str) -> float:
        return self._last_alternation_penalty.get(symbol, 0.0)
    
    def get_collapse_fragility(self, symbol: str) -> float:
        return self._last_collapse_fragility.get(symbol, 0.0)
    
    def get_persistence_weighted_confidence(self, symbol: str) -> float:
        return self._last_persistence_weighted_confidence.get(symbol, 0.0)
    
    def get_persistence_bars(self, symbol: str) -> int:
        return self._last_persistence_bars.get(symbol, 0)
    
    def get_signal_freshness(self, symbol: str) -> float:
        return self._last_freshness.get(symbol, 0.0)
    
    def get_sample_sufficiency(self, symbol: str) -> float:
        return self._last_sample_sufficiency.get(symbol, 0.0)
    
    def get_is_shock(self, symbol: str) -> bool:
        return self._last_is_shock.get(symbol, False)
    
    def get_entropy_slope(self, symbol: str) -> float:
        return self._last_entropy_slope.get(symbol, 0.0)
    
    def get_stats(self, symbol: str) -> Dict[str, Any]:
        current = self.get_current(symbol)
        if not current:
            return {"symbol": symbol, "has_data": False}
        
        entropy_history = list(self._entropy_history.get(symbol, []))
        
        return {
            "symbol": symbol,
            "has_data": True,
            "current_entropy": float(current.entropy),
            "is_collapsed": current.is_collapsed,
            "predicted_magnitude": float(current.predicted_magnitude),
            "confidence": float(current.confidence),
            "collapse_quality": self.get_collapse_quality(symbol).value,
            "structural_score": self.get_structural_score(symbol),
            "transition_concentration": self.get_transition_concentration(symbol),
            "dominant_reliability": self.get_dominant_reliability(symbol),
            "alternation_penalty": self.get_alternation_penalty(symbol),
            "collapse_fragility": self.get_collapse_fragility(symbol),
            "persistence_weighted_confidence": self.get_persistence_weighted_confidence(symbol),
            "persistence_bars": self.get_persistence_bars(symbol),
            "signal_freshness": self.get_signal_freshness(symbol),
            "sample_sufficiency": self.get_sample_sufficiency(symbol),
            "is_shock": self.get_is_shock(symbol),
            "entropy_slope": self.get_entropy_slope(symbol),
            "samples_used": current.samples_used,
            "entropy_trend": entropy_history[-10:] if len(entropy_history) >= 10 else entropy_history,
        }
    
    def get_market_entropy(self, symbols: List[str], regime: RegimeType) -> Dict[str, Any]:
        if not symbols:
            return {"avg_entropy": 0.0, "structural_ratio": 0.0, "avg_confidence": 0.0}
        
        entropies = []
        structural_scores = []
        confidences = []
        
        for symbol in symbols:
            score = self.get_current(symbol)
            if score:
                entropies.append(float(score.entropy))
                structural_scores.append(self.get_structural_score(symbol))
                confidences.append(float(score.confidence))
        
        if not entropies:
            return {"avg_entropy": 0.0, "structural_ratio": 0.0, "avg_confidence": 0.0}
        
        return {
            "avg_entropy": sum(entropies) / len(entropies),
            "structural_ratio": sum(1 for ss in structural_scores if ss > 0.6) / len(structural_scores),
            "avg_structural_score": sum(structural_scores) / len(structural_scores),
            "avg_confidence": sum(confidences) / len(confidences),
            "symbols_with_data": len(entropies),
            "total_symbols": len(symbols)
        }
    
    def get_entropy_history(self, symbol: str, window: int = 100) -> List[float]:
        if symbol not in self._entropy_history:
            return []
        return list(self._entropy_history[symbol])[-window:]
    
    def reset(self, symbol: str) -> None:
        stores = [
            self._trade_seq, self._time_ns_seq, self._entropy_history,
            self._entropy_timestamps, self._magnitude_history,
            self._transitions, self._state_counts,
            self._collapse_quality, self._collapse_persistence,
            self._last_quality_change_ns, self._last_score,
            self._last_structural_score, self._last_transition_concentration,
            self._last_dominant_reliability, self._last_alternation_penalty,
            self._last_collapse_fragility, self._last_persistence_weighted_confidence,
            self._last_persistence_bars, self._last_freshness,
            self._last_sample_sufficiency, self._last_is_shock,
            self._last_entropy_slope
        ]
        for store in stores:
            if symbol in store:
                if isinstance(store[symbol], deque):
                    store[symbol].clear()
                elif isinstance(store[symbol], list):
                    store[symbol] = []
                elif isinstance(store[symbol], dict):
                    store[symbol] = {}
                else:
                    del store[symbol]
    
    def _calculate_conditional_entropy(self, symbol: str) -> float:
        seq = self._trade_seq[symbol]
        if len(seq) < self.state_depth + 1:
            return 1.0
        
        self._transitions[symbol] = [[0, 0] for _ in range(self.n_states)]
        self._state_counts[symbol] = [0] * self.n_states
        
        for i in range(self.state_depth, len(seq) - 1):
            state = self._encode_state(symbol, i)
            next_trade = seq[i + 1]
            self._transitions[symbol][state][next_trade] += 1
            self._state_counts[symbol][state] += 1
        
        weighted_entropy = 0.0
        total_weight = 0
        
        for state in range(self.n_states):
            count = self._state_counts[symbol][state]
            if count == 0:
                continue
            
            p0 = self._transitions[symbol][state][0] / count
            p1 = self._transitions[symbol][state][1] / count
            
            state_entropy = 0.0
            if p0 > 0:
                state_entropy -= p0 * math.log2(p0)
            if p1 > 0:
                state_entropy -= p1 * math.log2(p1)
            
            weighted_entropy += state_entropy * count
            total_weight += count
        
        if total_weight == 0:
            return 1.0
        
        return max(0.0, min(1.0, weighted_entropy / total_weight))
    
    def _encode_state(self, symbol: str, idx: int) -> int:
        seq = self._trade_seq[symbol]
        if idx < self.state_depth:
            return 0
        
        state = 0
        for i in range(self.state_depth):
            if seq[idx - self.state_depth + i]:
                state |= (1 << i)
        return state
    
    def _calculate_transition_concentration(self, symbol: str) -> float:
        transitions = self._transitions.get(symbol)
        if not transitions:
            return 0.5
        
        total_transitions = 0
        for state in range(self.n_states):
            total_transitions += sum(transitions[state])
        
        if total_transitions == 0:
            return 0.5
        
        probs = []
        for state in range(self.n_states):
            state_total = sum(transitions[state])
            if state_total > 0:
                for t in range(2):
                    if transitions[state][t] > 0:
                        probs.append(transitions[state][t] / total_transitions)
        
        if not probs:
            return 0.5
        
        concentration_entropy = 0.0
        for p in probs:
            if p > 0:
                concentration_entropy -= p * math.log2(p)
        
        max_entropy = math.log2(len(probs)) if len(probs) > 1 else 1.0
        if max_entropy == 0:
            return 1.0
        
        concentration = 1.0 - (concentration_entropy / max_entropy)
        return max(0.0, min(1.0, concentration))
    
    def _calculate_dominant_state_reliability(self, symbol: str) -> float:
        transitions = self._transitions.get(symbol)
        if not transitions:
            return 0.5
        
        max_prob = 0.0
        total = 0
        for state in range(self.n_states):
            state_total = sum(transitions[state])
            if state_total > 0:
                total += state_total
                max_prob = max(max_prob, max(transitions[state]) / state_total)
        
        if total == 0:
            return 0.5
        
        return max_prob
    
    def _calculate_alternation_penalty(self, symbol: str) -> float:
        seq = self._trade_seq[symbol]
        if len(seq) < 10:
            return 0.0
        
        alternations = 0
        for i in range(len(seq) - 1):
            if seq[i] != seq[i + 1]:
                alternations += 1
        
        alternation_rate = alternations / (len(seq) - 1)
        
        if alternation_rate > self.MAX_ALTERNATION_RATE:
            penalty = min(1.0, (alternation_rate - self.MAX_ALTERNATION_RATE) / 0.3)
            return penalty
        
        return 0.0
    
    def _calculate_structural_score(
        self,
        entropy: float,
        concentration: float,
        reliability: float,
        alternation_penalty: float
    ) -> float:
        entropy_component = 1.0 - entropy
        structural_component = (concentration * 0.5 + reliability * 0.5)
        raw_score = entropy_component * structural_component
        score = raw_score * (1.0 - alternation_penalty * 0.7)
        return max(0.0, min(1.0, score))
    
    def _get_base_collapse_quality(self, symbol: str, current_entropy: float) -> CollapseQuality:
        history = list(self._entropy_history.get(symbol, []))
        if len(history) < self.MIN_SAMPLES_BASE:
            return CollapseQuality.NONE
        
        temp_history = history + [current_entropy]
        sorted_history = sorted(temp_history)
        n = len(sorted_history)
        
        def percentile(pct: float) -> float:
            idx = (pct / 100.0) * (n - 1)
            idx_floor = int(idx)
            idx_ceil = min(idx_floor + 1, n - 1)
            if idx_floor == idx_ceil:
                return sorted_history[idx_floor]
            weight = idx - idx_floor
            return sorted_history[idx_floor] * (1 - weight) + sorted_history[idx_ceil] * weight
        
        if current_entropy <= percentile(self.COLLAPSE_PCT_EXTREME):
            return CollapseQuality.EXTREME
        elif current_entropy <= percentile(self.COLLAPSE_PCT_STRUCTURAL):
            return CollapseQuality.STRUCTURAL
        elif current_entropy <= percentile(self.COLLAPSE_PCT_WEAK):
            return CollapseQuality.WEAK
        return CollapseQuality.NONE
    
    def _detect_shock_volatility_normalized(self, symbol: str, current_entropy: float) -> bool:
        history = list(self._entropy_history.get(symbol, []))
        if len(history) < 10:
            return False
        
        recent = history[-10:]
        mean = sum(recent) / len(recent)
        variance = sum((x - mean) ** 2 for x in recent) / len(recent)
        std = math.sqrt(variance)
        
        if std < 1e-6:
            return False
        
        z_score = abs(current_entropy - mean) / std
        return z_score > self.SHOCK_ZSCORE_THRESHOLD
    
    def _apply_persistence(self, symbol: str, raw_quality: CollapseQuality, timestamp_ns: int) -> CollapseQuality:
        if not self.enable_persistence:
            self._collapse_quality[symbol] = raw_quality
            self._collapse_persistence[symbol] = 1 if raw_quality != CollapseQuality.NONE else 0
            return raw_quality
        
        prev_quality = self._collapse_quality.get(symbol, CollapseQuality.NONE)
        persistence = self._collapse_persistence.get(symbol, 0)
        
        if raw_quality == prev_quality:
            self._collapse_persistence[symbol] = persistence + 1
            self._collapse_quality[symbol] = prev_quality
            return prev_quality
        
        required_bars_for_target = {
            CollapseQuality.WEAK: self.PERSISTENCE_WEAK,
            CollapseQuality.STRUCTURAL: self.PERSISTENCE_STRUCTURAL,
            CollapseQuality.EXTREME: self.PERSISTENCE_EXTREME,
        }
        
        if raw_quality.value > prev_quality.value:
            target_threshold = required_bars_for_target.get(raw_quality, 1)
            if persistence + 1 >= target_threshold:
                self._collapse_quality[symbol] = raw_quality
                self._collapse_persistence[symbol] = 1
                self._last_quality_change_ns[symbol] = timestamp_ns
                return raw_quality
            else:
                self._collapse_persistence[symbol] = persistence + 1
                return prev_quality
        
        self._collapse_quality[symbol] = raw_quality
        self._collapse_persistence[symbol] = 1 if raw_quality != CollapseQuality.NONE else 0
        self._last_quality_change_ns[symbol] = timestamp_ns
        return raw_quality
    
    def _calculate_fragility(
        self,
        symbol: str,
        quality: CollapseQuality,
        concentration: float,
        reliability: float,
        slope: float
    ) -> float:
        if quality == CollapseQuality.NONE:
            return 0.0
        
        concentration_penalty = max(0.0, 1.0 - concentration / self.MIN_TRANSITION_CONCENTRATION)
        reliability_penalty = max(0.0, 1.0 - reliability / self.MIN_DOMINANT_RELIABILITY)
        slope_penalty = max(0.0, slope * 2.0)
        
        quality_fragility = {
            CollapseQuality.WEAK: 0.6,
            CollapseQuality.STRUCTURAL: 0.3,
            CollapseQuality.EXTREME: 0.1
        }.get(quality, 0.5)
        
        fragility = (concentration_penalty * 0.35 +
                     reliability_penalty * 0.35 +
                     slope_penalty * 0.2 +
                     quality_fragility * 0.1)
        
        return min(1.0, fragility)
    
    def _calculate_entropy_slope(self, symbol: str) -> float:
        history = list(self._entropy_history.get(symbol, []))
        if len(history) < 5:
            return 0.0
        
        recent = history[-5:]
        if len(recent) < 2:
            return 0.0
        
        x = list(range(len(recent)))
        n = len(recent)
        sum_x = sum(x)
        sum_y = sum(recent)
        sum_xy = sum(x[i] * recent[i] for i in range(n))
        sum_x2 = sum(xi * xi for xi in x)
        
        if n * sum_x2 - sum_x * sum_x == 0:
            return 0.0
        
        slope = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x * sum_x)
        return max(-1.0, min(1.0, slope))
    
    def _quality_to_score(self, quality: CollapseQuality) -> float:
        return {
            CollapseQuality.NONE: 0.0,
            CollapseQuality.WEAK: 0.35,
            CollapseQuality.STRUCTURAL: 0.7,
            CollapseQuality.EXTREME: 1.0
        }[quality]
    
    def _predict_magnitude_enhanced(
        self,
        entropy: float,
        collapse_score: float,
        slope: float,
        fragility: float,
        regime: RegimeType
    ) -> float:
        base = (1.0 - entropy) * 4.5 + 0.5
        collapse_multiplier = 1.0 + (collapse_score * 2.5)
        slope_boost = 1.0 + max(0.0, -slope * 0.6)
        fragility_penalty = 1.0 - (fragility * 0.5)
        
        regime_multiplier = {
            RegimeType.CRISIS: 1.5,
            RegimeType.TRENDING: 1.2,
            RegimeType.RANGING: 0.7,
            RegimeType.UNKNOWN: 1.0
        }.get(regime, 1.0)
        
        magnitude = base * collapse_multiplier * slope_boost * fragility_penalty * regime_multiplier
        return max(0.5, min(15.0, magnitude))
    
    def _calculate_base_confidence(
        self,
        symbol: str,
        entropy: float,
        quality: CollapseQuality,
        structural_score: float,
        concentration: float,
        reliability: float,
        slope: float,
        regime: RegimeType
    ) -> float:
        structural_factor = structural_score * 0.35
        concentration_factor = concentration * 0.15
        reliability_factor = reliability * 0.15
        
        sample_count = len(self._trade_seq.get(symbol, []))
        sample_factor = min(0.15, (sample_count / self.MIN_SAMPLES_HIGH_CONF) * 0.15)
        
        slope_factor = max(0.0, min(0.1, -slope * 0.2))
        
        regime_factor = {
            RegimeType.TRENDING: 0.08,
            RegimeType.CRISIS: 0.04,
            RegimeType.RANGING: 0.06,
            RegimeType.UNKNOWN: 0.03
        }.get(regime, 0.05)
        
        confidence = (structural_factor + concentration_factor + reliability_factor +
                      sample_factor + slope_factor + regime_factor)
        
        if quality == CollapseQuality.NONE:
            confidence *= 0.3
        
        return min(0.9, max(0.05, confidence))
    
    def _calculate_freshness(self, symbol: str, current_time_ns: int) -> float:
        last_score = self._last_score.get(symbol)
        if not last_score:
            return 0.0
        
        delta_ns = current_time_ns - last_score.timestamp
        if delta_ns <= 0:
            return 1.0
        
        freshness = math.pow(0.5, delta_ns / self.DECAY_HALF_LIFE_NS)
        return max(0.0, min(1.0, freshness))
    
    def _init_symbol(self, symbol: str) -> None:
        if symbol not in self._trade_seq:
            self._trade_seq[symbol] = []
            self._time_ns_seq[symbol] = []
            self._entropy_history[symbol] = deque(maxlen=500)
            self._entropy_timestamps[symbol] = deque(maxlen=500)
            self._magnitude_history[symbol] = deque(maxlen=500)
            self._transitions[symbol] = [[0, 0] for _ in range(self.n_states)]
            self._state_counts[symbol] = [0] * self.n_states
            self._collapse_quality[symbol] = CollapseQuality.NONE
            self._collapse_persistence[symbol] = 0
    
    def _prune(self, symbol: str, current_time_ns: int) -> None:
        if symbol not in self._time_ns_seq:
            return
        
        cutoff_ns = current_time_ns - self.window_ns
        time_seq = self._time_ns_seq[symbol]
        trade_seq = self._trade_seq[symbol]
        
        keep_idx = 0
        for i, ts_ns in enumerate(time_seq):
            if ts_ns >= cutoff_ns:
                keep_idx = i
                break
        else:
            keep_idx = len(time_seq)
        
        if keep_idx > 0:
            self._trade_seq[symbol] = trade_seq[keep_idx:]
            self._time_ns_seq[symbol] = time_seq[keep_idx:]