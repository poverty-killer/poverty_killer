"""
app/brain/whale_zone_engine.py

Deterministic, replay-safe whale zone detection for Poverty Killer.
Preserves old candle-level institutional accumulation / zone intelligence
as a role-pure zone engine, separate from directional whale flow.

Role: Zone presence / accumulation structure / price-in-zone context / zone confidence.
NOT: directional alpha source, regime detector, toxicity engine, fusion direction.

This file owns:
- zone presence and bounds
- zone confidence and bias
- price-in-zone proximity
- candle-level accumulation proxy behavior
- structure-aware accumulation context

Split doctrine:
- whale_flow_engine.py = directional whale alpha only
- whale_zone_engine.py = zone / accumulation structure context

Time semantics (v3 - truthful):
- creation_time_ns = timestamp when zone was first detected (immutable)
- last_update_ns = timestamp when zone was last refreshed by evidence (NOT proximity)
- age_ns = current_ts - creation_time_ns (true zone age) - computed via get_age_ns()
- time_since_refresh = current_ts - last_update_ns (for TTL/decay) - computed via get_time_since_refresh()

last_update_ns doctrine:
- Refreshed ONLY on evidence-based events: creation, detection, overlap update
- NOT refreshed on passive proximity checks (price-in-zone queries)
- Continuous exponential decay applies to confidence based on starvation of new evidence
"""

import math
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Deque, Union, Any
from collections import deque
from enum import IntEnum
import numpy as np

logger = logging.getLogger(__name__)

# Numerical stability epsilon
EPS = np.finfo(float).eps


class ZoneBias(IntEnum):
    """Zone bias based on accumulation pattern."""
    BEARISH = -1
    NEUTRAL = 0
    BULLISH = 1


@dataclass
class WhalePresenceZone:
    """
    Whale presence zone with bounds, confidence, and contextual bias.
    
    This represents an institutional accumulation/absorption zone
    detected from candle-level patterns.
    
    Time semantics:
    - creation_time_ns: When zone was first detected (immutable)
    - last_update_ns: When zone was last refreshed by evidence (NOT proximity)
    - Use get_age_ns() and get_time_since_refresh() with current timestamp
    """
    lower_bound: float
    upper_bound: float
    confidence: float           # 0-1, how confident we are this is a real zone
    bias: ZoneBias              # Bullish if accumulation near lower, bearish if distribution near upper
    presence: bool              # True if price is currently in or near the zone
    proximity: float            # 0-1, how close price is to zone (1 = inside, decreasing outside)
    center: float               # Zone center (midpoint of bounds)
    width: float                # Zone width (upper - lower)
    creation_time_ns: int       # When zone was first detected (immutable)
    last_update_ns: int         # When zone was last refreshed by evidence
    stability_count: int        # Number of confirmations (persistence)
    accumulation_score: float   # 0-1, how strong the accumulation signature is


@dataclass
class CandleEvidence:
    """Raw evidence from candle for zone detection."""
    close: float
    high: float
    low: float
    volume: float
    vwap: float
    exchange_ts_ns: int
    compression: float          # (high-low)/close normalized [0,1]
    absorption: float           # Volume concentration near edges [0,1] (1 at edges, 0 at center)
    volume_anomaly: float       # Volume z-score from baseline [0,1]
    anomalous_bar: bool         # True if volume or range is anomalous


@dataclass
class CachedZoneState:
    """Internal state for deterministic zone tracking."""
    zone: Optional[WhalePresenceZone]
    detection_queue: Deque[Tuple[int, float, float, float, float, float, float]]  # (ts, vwap, close, high, low, volume, accumulation_score)
    accumulation_history: Deque[float]
    volume_history: Deque[float]
    last_update_ns: int


class WhaleZoneEngine:
    """
    Deterministic whale zone detector for accumulation structure.
    
    Features (Preserved & Activated):
    - VWAP-centric structural clustering for zone bounds
    - Gaussian proximity representing continuous gravitational pull
    - Exponential confidence decay (no brittle TTL drop-offs)
    - Price-position weighted accumulation scoring (activating dormant capability)
    - Overlap merging with smooth RECENCY_ALPHA interpolation
    - Truthful time semantics (creation_time_ns, last_update_ns)
    
    Zone types:
    - Accumulation zone: bullish bias, price near lower bound
    - Distribution zone: bearish bias, price near upper bound
    
    This engine is role-pure and does NOT replace directional whale_flow_engine.
    """

    # Zone detection thresholds
    MIN_ZONE_WIDTH_PCT = 0.005   # 0.5% minimum zone width
    MAX_ZONE_WIDTH_PCT = 0.05    # 5% maximum zone width
    ZONE_CONFIDENCE_THRESHOLD = 0.6
    ZONE_STABILITY_REQUIRED = 2  # Confirmations needed
    
    # Continuous Decay Half-Life
    ZONE_HALF_LIFE_NS = 60 * 1_000_000_000  # 60 seconds
    ZONE_DEATH_THRESHOLD = 0.15             # Confidence below this prunes the zone
    
    # Accumulation detection weights (Original values, now fully activated)
    COMPRESSION_WEIGHT = 0.35
    ABSORPTION_WEIGHT = 0.30
    VOLUME_ANOMALY_WEIGHT = 0.25
    PRICE_POSITION_WEIGHT = 0.10
    
    # Recency weighting alpha for bound merging
    RECENCY_ALPHA = 0.7
    
    # Volume baseline window
    VOLUME_BASELINE_WINDOW = 20

    def __init__(self, config: Optional[Union[Dict[str, Any], Any]] = None):
        """
        Initialize whale zone engine with optional configuration.
        
        Args:
            config: Either a dict with configuration keys or an object with
                    attribute-style configuration. Supports both calling patterns.
        """
        # Configuration with bounded defaults
        self.min_zone_width_pct = self.MIN_ZONE_WIDTH_PCT
        self.max_zone_width_pct = self.MAX_ZONE_WIDTH_PCT
        self.zone_confidence_threshold = self.ZONE_CONFIDENCE_THRESHOLD
        self.zone_stability_required = self.ZONE_STABILITY_REQUIRED
        self.zone_half_life_ns = self.ZONE_HALF_LIFE_NS
        
        if config is not None:
            if isinstance(config, dict):
                self.min_zone_width_pct = config.get('min_zone_width_pct', self.MIN_ZONE_WIDTH_PCT)
                self.max_zone_width_pct = config.get('max_zone_width_pct', self.MAX_ZONE_WIDTH_PCT)
                self.zone_confidence_threshold = config.get('zone_confidence_threshold', self.ZONE_CONFIDENCE_THRESHOLD)
                self.zone_stability_required = config.get('zone_stability_required', self.ZONE_STABILITY_REQUIRED)
                self.zone_half_life_ns = config.get('zone_half_life_ns', self.ZONE_HALF_LIFE_NS)
            else:
                if hasattr(config, 'min_zone_width_pct'):
                    self.min_zone_width_pct = getattr(config, 'min_zone_width_pct', self.MIN_ZONE_WIDTH_PCT)
                if hasattr(config, 'max_zone_width_pct'):
                    self.max_zone_width_pct = getattr(config, 'max_zone_width_pct', self.MAX_ZONE_WIDTH_PCT)
                if hasattr(config, 'zone_confidence_threshold'):
                    self.zone_confidence_threshold = getattr(config, 'zone_confidence_threshold', self.ZONE_CONFIDENCE_THRESHOLD)
                if hasattr(config, 'zone_stability_required'):
                    self.zone_stability_required = getattr(config, 'zone_stability_required', self.ZONE_STABILITY_REQUIRED)
                if hasattr(config, 'zone_half_life_ns'):
                    self.zone_half_life_ns = getattr(config, 'zone_half_life_ns', self.ZONE_HALF_LIFE_NS)
        
        # Per-symbol state
        self._states: Dict[str, CachedZoneState] = {}
        
        # Rolling volume baseline per symbol
        self._volume_baselines: Dict[str, Tuple[float, float]] = {}  # (mean, std)

    # ========================================================================
    # Public API
    # ========================================================================

    def update(
        self,
        symbol: str,
        close: float,
        high: float,
        low: float,
        volume: float,
        vwap: float,
        exchange_ts_ns: int,
    ) -> Optional[WhalePresenceZone]:
        """
        Update whale zone engine with new candle data.
        
        Args:
            symbol: Trading pair symbol
            close: Candle close price
            high: Candle high price
            low: Candle low price
            volume: Candle volume
            vwap: Volume-weighted average price (if available, else close)
            exchange_ts_ns: Exchange timestamp in nanoseconds
        
        Returns:
            Current WhalePresenceZone for the symbol, or None if insufficient data
        """
        state = self._get_state(symbol)
        
        # Compute compression (range relative to price)
        price_range = high - low
        compression = price_range / close if close > 0 else 0.0
        compression = min(1.0, compression / 0.05)  # Normalize: 5% range = 1.0
        
        # Compute absorption (volume concentration near edges)
        # Edge-heavy: 1 at price extremes (accumulation at edges), 0 at center
        price_position = (close - low) / price_range if price_range > EPS else 0.5
        absorption = abs(price_position - 0.5) * 2.0
        absorption = absorption * min(1.0, volume / 1000.0)  # Scale by volume proxy
        
        # Update volume baseline
        self._update_volume_baseline(symbol, volume)
        volume_mean, volume_std = self._volume_baselines.get(symbol, (volume, 1.0))
        
        # Compute volume anomaly (z-score normalized to [0,1])
        volume_anomaly = 0.0
        if volume_std > EPS:
            zscore = (volume - volume_mean) / volume_std
            volume_anomaly = min(1.0, max(0.0, zscore / 3.0))
        
        # Detect anomalous bar (unusual volume or range)
        range_normal = price_range / close if close > 0 else 0.0
        anomalous_bar = volume_anomaly > 0.7 or range_normal > 0.03
        
        # Create evidence
        evidence = CandleEvidence(
            close=close,
            high=high,
            low=low,
            volume=volume,
            vwap=vwap if vwap > 0 else close,
            exchange_ts_ns=exchange_ts_ns,
            compression=compression,
            absorption=absorption,
            volume_anomaly=volume_anomaly,
            anomalous_bar=anomalous_bar,
        )
        
        # Detect or update zone
        zone = self._detect_or_update_zone(state, evidence, exchange_ts_ns)
        
        if zone is None:
            state.zone = None
            return None
        
        # Update zone with current price for proximity (does NOT refresh last_update_ns)
        zone = self._update_zone_proximity(zone, close)
        
        # Store updated zone
        state.zone = zone
        return zone

    def get_zone(self, symbol: str) -> Optional[WhalePresenceZone]:
        """Get the current whale presence zone for a symbol."""
        state = self._states.get(symbol)
        if state is None or state.zone is None:
            return None
        return state.zone

    def get_age_ns(self, symbol: str, current_ts_ns: int) -> int:
        """
        Get true zone age in nanoseconds since creation.
        Returns 0 if no zone exists.
        """
        state = self._states.get(symbol)
        if state is None or state.zone is None:
            return 0
        return max(0, current_ts_ns - state.zone.creation_time_ns)

    def get_time_since_refresh(self, symbol: str, current_ts_ns: int) -> int:
        """
        Get time in nanoseconds since last evidence-based refresh.
        Returns 0 if no zone exists.
        """
        state = self._states.get(symbol)
        if state is None or state.zone is None:
            return 0
        return max(0, current_ts_ns - state.zone.last_update_ns)

    def is_in_zone(self, symbol: str, price: float) -> Tuple[bool, float]:
        """
        Check if price is within the current zone bounds.
        
        Returns:
            Tuple of (in_zone, proximity) where proximity is 0-1
        """
        state = self._states.get(symbol)
        if state is None or state.zone is None:
            return False, 0.0
        
        zone = state.zone
        if zone.lower_bound <= price <= zone.upper_bound:
            return True, 1.0
        
        # Gaussian proximity calculation outside bounds
        distance_to_lower = abs(price - zone.lower_bound)
        distance_to_upper = abs(price - zone.upper_bound)
        min_distance = min(distance_to_lower, distance_to_upper)
        
        sigma = max(zone.width * 0.5, price * 0.001)
        proximity = math.exp(-0.5 * (min_distance / sigma) ** 2)
        
        return False, proximity

    def get_zone_bias(self, symbol: str) -> ZoneBias:
        """Get zone bias (bullish/bearish/neutral) for a symbol."""
        state = self._states.get(symbol)
        if state is None or state.zone is None:
            return ZoneBias.NEUTRAL
        return state.zone.bias

    def get_zone_confidence(self, symbol: str) -> float:
        """Get zone confidence (0-1) for a symbol."""
        state = self._states.get(symbol)
        if state is None or state.zone is None:
            return 0.0
        return state.zone.confidence

    def get_zone_bounds(self, symbol: str) -> Tuple[Optional[float], Optional[float]]:
        """Get zone bounds (lower, upper) for a symbol."""
        state = self._states.get(symbol)
        if state is None or state.zone is None:
            return None, None
        return state.zone.lower_bound, state.zone.upper_bound

    def reset(self, symbol: Optional[str] = None) -> None:
        """Reset internal state for deterministic replay safety."""
        if symbol is not None:
            self._states.pop(symbol, None)
            self._volume_baselines.pop(symbol, None)
        else:
            self._states.clear()
            self._volume_baselines.clear()

    # ========================================================================
    # Internal Methods
    # ========================================================================

    def _get_state(self, symbol: str) -> CachedZoneState:
        """Get or create state for a symbol."""
        if symbol not in self._states:
            self._states[symbol] = CachedZoneState(
                zone=None,
                detection_queue=deque(maxlen=20),
                accumulation_history=deque(maxlen=20),
                volume_history=deque(maxlen=self.VOLUME_BASELINE_WINDOW),
                last_update_ns=0,
            )
        return self._states[symbol]

    def _update_volume_baseline(self, symbol: str, volume: float) -> None:
        """Update rolling volume baseline for a symbol."""
        state = self._get_state(symbol)
        state.volume_history.append(volume)
        
        if len(state.volume_history) >= self.VOLUME_BASELINE_WINDOW:
            volumes = list(state.volume_history)
            mean = float(np.mean(volumes))
            std = float(np.std(volumes))
            self._volume_baselines[symbol] = (mean, max(std, EPS))

    def _compute_accumulation_score(self, evidence: CandleEvidence) -> float:
        """
        Compute accumulation score from evidence.
        High score indicates institutional accumulation/absorption.
        Now explicitly utilizes the original PRICE_POSITION_WEIGHT.
        """
        price_range = max(evidence.high - evidence.low, EPS)
        # Position of close relative to the bar's range
        position = (evidence.close - evidence.low) / price_range
        # Favorable structural price position (e.g. strong rejection wicks leaving close near one end)
        price_pos_score = abs(position - 0.5) * 2.0
        
        score = (
            evidence.compression * self.COMPRESSION_WEIGHT +
            evidence.absorption * self.ABSORPTION_WEIGHT +
            evidence.volume_anomaly * self.VOLUME_ANOMALY_WEIGHT +
            price_pos_score * self.PRICE_POSITION_WEIGHT
        )
        
        # Anomalous bar boosts score, preserving original engine intelligence
        if evidence.anomalous_bar:
            score = min(1.0, score * 1.3)
        
        return score

    def _detect_zone_clusters(self, state: CachedZoneState) -> Optional[Tuple[float, float, float, int, ZoneBias]]:
        """
        Detect zone boundaries using VWAP-centric variance (math-upgraded replacement 
        for original wick-hunting bounds).
        Returns (lower, upper, confidence, creation_ts, bias) or None.
        """
        if len(state.detection_queue) < self.zone_stability_required:
            return None
            
        recent = list(state.detection_queue)[-self.zone_stability_required:]
        
        total_weight = 0.0
        weighted_vwap_sum = 0.0
        weighted_bias_sum = 0.0
        
        for ts, vwap, close, high, low, vol, acc_score in recent:
            weight = vol * acc_score
            total_weight += weight
            weighted_vwap_sum += vwap * weight
            
            midpoint = (high + low) / 2.0
            range_len = max(high - low, EPS)
            pos = (close - midpoint) / (range_len / 2.0)
            weighted_bias_sum += pos * weight
            
        if total_weight < EPS:
            return None
            
        center = weighted_vwap_sum / total_weight
        avg_bias_score = weighted_bias_sum / total_weight
        
        if avg_bias_score > 0.15:
            bias = ZoneBias.BULLISH
        elif avg_bias_score < -0.15:
            bias = ZoneBias.BEARISH
        else:
            bias = ZoneBias.NEUTRAL

        variance_sum = sum((vol * acc_score) * ((vwap - center) ** 2) 
                           for _, vwap, _, _, _, vol, acc_score in recent)
        std_dev = math.sqrt(variance_sum / total_weight)
        
        calculated_width = std_dev * 4.0
        min_width = center * self.min_zone_width_pct
        max_width = center * self.max_zone_width_pct
        
        final_width = max(min_width, min(calculated_width, max_width))
        
        lower_bound = center - (final_width / 2.0)
        upper_bound = center + (final_width / 2.0)
        
        avg_score = float(np.mean([item[-1] for item in recent]))
        stability_ratio = min(1.0, len(recent) / self.zone_stability_required)
        confidence = min(1.0, avg_score * stability_ratio)
        
        if confidence < self.zone_confidence_threshold:
            return None
            
        creation_time = min(item[0] for item in recent)
        
        return lower_bound, upper_bound, confidence, creation_time, bias

    def _apply_confidence_decay(self, zone: WhalePresenceZone, exchange_ts_ns: int) -> Optional[WhalePresenceZone]:
        """
        Applies continuous exponential decay to zone confidence.
        Replaces hard TTL thresholds.
        """
        time_since_refresh = max(0, exchange_ts_ns - zone.last_update_ns)
        
        if time_since_refresh == 0:
            return zone
            
        decay_factor = 0.5 ** (time_since_refresh / self.zone_half_life_ns)
        new_confidence = zone.confidence * decay_factor
        
        if new_confidence < self.ZONE_DEATH_THRESHOLD:
            return None
            
        zone.confidence = new_confidence
        zone.accumulation_score = zone.accumulation_score * decay_factor
        return zone

    def _detect_or_update_zone(
        self,
        state: CachedZoneState,
        evidence: CandleEvidence,
        exchange_ts_ns: int,
    ) -> Optional[WhalePresenceZone]:
        """
        Detect new zone or update existing zone.
        """
        accumulation_score = self._compute_accumulation_score(evidence)
        
        # Queue significant structural footprints
        if accumulation_score > 0.4:
            state.detection_queue.append((
                evidence.exchange_ts_ns, evidence.vwap, evidence.close, 
                evidence.high, evidence.low, evidence.volume, accumulation_score
            ))
            state.accumulation_history.append(accumulation_score)
        elif len(state.detection_queue) > 0 and accumulation_score < 0.2:
            state.detection_queue.clear()
        
        # Try to detect new zone from clusters
        cluster_data = self._detect_zone_clusters(state)
        
        if cluster_data is not None:
            lower_bound, upper_bound, confidence, creation_time, bias = cluster_data
            
            # Check for structural overlap with existing zone
            if state.zone is not None:
                existing = state.zone
                overlap_lower = max(lower_bound, existing.lower_bound)
                overlap_upper = min(upper_bound, existing.upper_bound)
                
                if overlap_lower < overlap_upper:
                    # Update existing zone bounds with smooth RECENCY_ALPHA (reinstated original logic)
                    alpha = self.RECENCY_ALPHA
                    new_lower = alpha * lower_bound + (1.0 - alpha) * existing.lower_bound
                    new_upper = alpha * upper_bound + (1.0 - alpha) * existing.upper_bound
                    
                    new_confidence = min(1.0, (existing.confidence + confidence) / 2.0)
                    merged_bias = bias if confidence > existing.confidence * 1.5 else existing.bias
                    
                    return WhalePresenceZone(
                        lower_bound=new_lower,
                        upper_bound=new_upper,
                        confidence=new_confidence,
                        bias=merged_bias,
                        presence=False,
                        proximity=0.0,
                        center=(new_lower + new_upper) / 2.0,
                        width=new_upper - new_lower,
                        creation_time_ns=existing.creation_time_ns,
                        last_update_ns=exchange_ts_ns,
                        stability_count=existing.stability_count + 1,
                        accumulation_score=accumulation_score
                    )
            
            # Create completely new zone
            return WhalePresenceZone(
                lower_bound=lower_bound,
                upper_bound=upper_bound,
                confidence=confidence,
                bias=bias,
                presence=False,
                proximity=0.0,
                center=(lower_bound + upper_bound) / 2.0,
                width=upper_bound - lower_bound,
                creation_time_ns=creation_time,
                last_update_ns=exchange_ts_ns,
                stability_count=1,
                accumulation_score=accumulation_score,
            )
        
        # No new evidence detected, continuously decay existing zone
        if state.zone is not None:
            return self._apply_confidence_decay(state.zone, exchange_ts_ns)
            
        return None

    def _update_zone_proximity(
        self,
        zone: WhalePresenceZone,
        price: float,
    ) -> WhalePresenceZone:
        """
        Update zone with current price proximity.
        Does NOT refresh last_update_ns - only evidence refreshes zone life.
        """
        presence = zone.lower_bound <= price <= zone.upper_bound
        
        if presence:
            proximity = 1.0
        else:
            # Gaussian continuous distance modeling
            distance_to_lower = abs(price - zone.lower_bound)
            distance_to_upper = abs(price - zone.upper_bound)
            min_distance = min(distance_to_lower, distance_to_upper)
            
            sigma = max(zone.width * 0.5, price * 0.001)
            proximity = math.exp(-0.5 * (min_distance / sigma) ** 2)
            
        # last_update_ns unchanged - only accumulation evidence refreshes zone life
        zone.presence = presence
        zone.proximity = proximity
        return zone