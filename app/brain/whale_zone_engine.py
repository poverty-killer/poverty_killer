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
- TTL expires zones not supported by new accumulation evidence
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Deque, Union, Any
from collections import deque
from enum import IntEnum
import numpy as np


class ZoneBias(IntEnum):
    """Zone bias based on accumulation pattern."""
    NEUTRAL = 0
    BULLISH = 1
    BEARISH = -1


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
    detection_queue: Deque[Tuple[int, float, float, float]]  # (timestamp, low, high, accumulation_score)
    accumulation_history: Deque[float]
    volume_history: Deque[float]
    last_update_ns: int


class WhaleZoneEngine:
    """
    Deterministic whale zone detector for accumulation structure.
    
    Features (preserved and strengthened from original):
    - Zone detection from candle-level patterns
    - Zone persistence (requires multiple confirmations)
    - Zone TTL with timestamp-based decay
    - Price-in-zone detection with proximity scoring
    - Multi-factor accumulation detection (compression, absorption, volume anomaly)
    - Recency-weighted zone memory
    - Per-symbol deterministic state
    - Truthful time semantics (creation_time_ns, last_update_ns)
    - Truthful absorption: 1 at price edges (accumulation), 0 at center
    
    Zone types:
    - Accumulation zone: bullish bias, price near lower bound
    - Distribution zone: bearish bias, price near upper bound
    
    This engine is role-pure and does NOT replace directional whale_flow_engine.
    """

    # Zone detection thresholds
    MIN_ZONE_WIDTH_PCT = 0.005   # 0.5% minimum zone width
    MAX_ZONE_WIDTH_PCT = 0.05    # 5% maximum zone width
    ZONE_CONFIDENCE_THRESHOLD = 0.6
    ZONE_STABILITY_REQUIRED = 2   # Confirmations needed
    ZONE_TTL_NS = 60 * 1_000_000_000  # 60 seconds TTL
    
    # Accumulation detection weights
    COMPRESSION_WEIGHT = 0.35
    ABSORPTION_WEIGHT = 0.30
    VOLUME_ANOMALY_WEIGHT = 0.25
    PRICE_POSITION_WEIGHT = 0.10
    
    # Recency weighting alpha
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
        self.zone_ttl_ns = self.ZONE_TTL_NS
        
        if config is not None:
            if isinstance(config, dict):
                self.min_zone_width_pct = config.get('min_zone_width_pct', self.MIN_ZONE_WIDTH_PCT)
                self.max_zone_width_pct = config.get('max_zone_width_pct', self.MAX_ZONE_WIDTH_PCT)
                self.zone_confidence_threshold = config.get('zone_confidence_threshold', self.ZONE_CONFIDENCE_THRESHOLD)
                self.zone_stability_required = config.get('zone_stability_required', self.ZONE_STABILITY_REQUIRED)
                self.zone_ttl_ns = config.get('zone_ttl_ns', self.ZONE_TTL_NS)
            else:
                if hasattr(config, 'min_zone_width_pct'):
                    self.min_zone_width_pct = getattr(config, 'min_zone_width_pct', self.MIN_ZONE_WIDTH_PCT)
                if hasattr(config, 'max_zone_width_pct'):
                    self.max_zone_width_pct = getattr(config, 'max_zone_width_pct', self.MAX_ZONE_WIDTH_PCT)
                if hasattr(config, 'zone_confidence_threshold'):
                    self.zone_confidence_threshold = getattr(config, 'zone_confidence_threshold', self.ZONE_CONFIDENCE_THRESHOLD)
                if hasattr(config, 'zone_stability_required'):
                    self.zone_stability_required = getattr(config, 'zone_stability_required', self.ZONE_STABILITY_REQUIRED)
                if hasattr(config, 'zone_ttl_ns'):
                    self.zone_ttl_ns = getattr(config, 'zone_ttl_ns', self.ZONE_TTL_NS)
        
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
        price_position = (close - low) / price_range if price_range > 0 else 0.5
        # Formula: distance from center (0.5) doubled -> 0 at center, 1 at edges
        absorption = abs(price_position - 0.5) * 2
        absorption = absorption * min(1.0, volume / 1000.0)  # Scale by volume
        
        # Update volume baseline
        self._update_volume_baseline(symbol, volume)
        volume_mean, volume_std = self._volume_baselines.get(symbol, (volume, 1.0))
        
        # Compute volume anomaly (z-score normalized to [0,1])
        volume_anomaly = 0.0
        if volume_std > 0:
            zscore = (volume - volume_mean) / volume_std
            volume_anomaly = min(1.0, max(0.0, zscore / 3.0))
        
        # Detect anomalous bar (unusual volume or range)
        range_normal = price_range / close if close > 0 else 0
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
        zone = self._detect_or_update_zone(state, evidence, symbol, exchange_ts_ns)
        
        if zone is None:
            return None
        
        # Update zone with current price for proximity (does NOT refresh last_update_ns)
        zone = self._update_zone_proximity(zone, close)
        
        # Store updated zone
        state.zone = zone
        state.last_update_ns = exchange_ts_ns
        
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
        return current_ts_ns - state.zone.creation_time_ns

    def get_time_since_refresh(self, symbol: str, current_ts_ns: int) -> int:
        """
        Get time in nanoseconds since last evidence-based refresh.
        Returns 0 if no zone exists.
        """
        state = self._states.get(symbol)
        if state is None or state.zone is None:
            return 0
        return current_ts_ns - state.zone.last_update_ns

    def is_in_zone(self, symbol: str, price: float) -> Tuple[bool, float]:
        """
        Check if price is within the current zone.
        
        Returns:
            Tuple of (in_zone, proximity) where proximity is 0-1
        """
        state = self._states.get(symbol)
        if state is None or state.zone is None:
            return False, 0.0
        
        zone = state.zone
        if zone.lower_bound <= price <= zone.upper_bound:
            return True, 1.0
        
        # Calculate proximity: distance to nearest bound normalized by zone width
        distance_to_lower = abs(price - zone.lower_bound)
        distance_to_upper = abs(price - zone.upper_bound)
        min_distance = min(distance_to_lower, distance_to_upper)
        proximity = 1.0 - min(1.0, min_distance / zone.width)
        
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
            volumes = list(state.volume_history)[-self.VOLUME_BASELINE_WINDOW:]
            mean = np.mean(volumes)
            std = np.std(volumes)
            self._volume_baselines[symbol] = (mean, max(std, 1e-8))

    def _compute_accumulation_score(self, evidence: CandleEvidence) -> float:
        """
        Compute accumulation score from evidence.
        High score indicates institutional accumulation/absorption.
        """
        score = (
            evidence.compression * self.COMPRESSION_WEIGHT +
            evidence.absorption * self.ABSORPTION_WEIGHT +
            evidence.volume_anomaly * self.VOLUME_ANOMALY_WEIGHT
        )
        
        # Anomalous bar boosts score
        if evidence.anomalous_bar:
            score = min(1.0, score * 1.3)
        
        return score

    def _detect_zone_bounds(
        self,
        state: CachedZoneState,
        evidence: CandleEvidence,
        accumulation_score: float,
    ) -> Optional[Tuple[float, float, float, int]]:
        """
        Detect zone bounds from detection queue.
        Returns (lower_bound, upper_bound, confidence, creation_time) or None.
        """
        if len(state.detection_queue) < self.zone_stability_required:
            return None
        
        # Get recent detection points
        recent = list(state.detection_queue)[-self.zone_stability_required:]
        
        # Extract lows, highs, scores, timestamps
        lows = [item[1] for item in recent]
        highs = [item[2] for item in recent]
        scores = [item[3] for item in recent]
        timestamps = [item[0] for item in recent]
        
        # Zone bounds are the min low and max high of detection points
        lower_bound = min(lows)
        upper_bound = max(highs)
        
        # Check width constraints
        width_pct = (upper_bound - lower_bound) / lower_bound if lower_bound > 0 else 0
        if width_pct < self.min_zone_width_pct or width_pct > self.max_zone_width_pct:
            return None
        
        # Confidence based on stability and accumulation scores
        stability_ratio = len(recent) / self.zone_stability_required
        avg_score = np.mean(scores)
        confidence = min(1.0, avg_score * stability_ratio)
        
        if confidence < self.zone_confidence_threshold:
            return None
        
        # Creation time is earliest detection timestamp
        creation_time = min(timestamps)
        
        return lower_bound, upper_bound, confidence, creation_time

    def _determine_zone_bias(
        self,
        lower_bound: float,
        upper_bound: float,
        evidence: CandleEvidence,
    ) -> ZoneBias:
        """
        Determine zone bias based on price position and accumulation pattern.
        Bullish: accumulation near lower bound (buying pressure)
        Bearish: distribution near upper bound (selling pressure)
        """
        price_position = (evidence.close - lower_bound) / (upper_bound - lower_bound) if upper_bound > lower_bound else 0.5
        
        # Strong bullish: price near lower bound with good compression
        if price_position < 0.3 and evidence.compression > 0.5:
            return ZoneBias.BULLISH
        
        # Strong bearish: price near upper bound with good compression
        if price_position > 0.7 and evidence.compression > 0.5:
            return ZoneBias.BEARISH
        
        # Weak bias based on price position
        if price_position < 0.4:
            return ZoneBias.BULLISH
        elif price_position > 0.6:
            return ZoneBias.BEARISH
        
        return ZoneBias.NEUTRAL

    def _detect_or_update_zone(
        self,
        state: CachedZoneState,
        evidence: CandleEvidence,
        symbol: str,
        exchange_ts_ns: int,
    ) -> Optional[WhalePresenceZone]:
        """
        Detect new zone or update existing zone.
        """
        # Compute accumulation score
        accumulation_score = self._compute_accumulation_score(evidence)
        
        # Add to detection queue if accumulation is significant
        if accumulation_score > 0.4:
            state.detection_queue.append((
                evidence.exchange_ts_ns,
                evidence.low,
                evidence.high,
                accumulation_score,
            ))
            state.accumulation_history.append(accumulation_score)
        else:
            # Clear detection queue if accumulation weak (prevents false zones)
            if len(state.detection_queue) > 0 and accumulation_score < 0.2:
                state.detection_queue.clear()
        
        # Try to detect new zone
        bounds = self._detect_zone_bounds(state, evidence, accumulation_score)
        
        if bounds is not None:
            lower_bound, upper_bound, confidence, creation_time = bounds
            bias = self._determine_zone_bias(lower_bound, upper_bound, evidence)
            
            # Check if this matches existing zone
            if state.zone is not None:
                # Check if bounds overlap significantly
                existing = state.zone
                overlap_lower = max(lower_bound, existing.lower_bound)
                overlap_upper = min(upper_bound, existing.upper_bound)
                if overlap_lower < overlap_upper:
                    # Update existing zone with weighted average
                    new_confidence = (existing.confidence + confidence) / 2
                    new_confidence = min(1.0, new_confidence)
                    
                    # Update bounds with recency weighting
                    alpha = self.RECENCY_ALPHA
                    new_lower = alpha * lower_bound + (1 - alpha) * existing.lower_bound
                    new_upper = alpha * upper_bound + (1 - alpha) * existing.upper_bound
                    
                    # Preserve original creation time, refresh last_update_ns on evidence
                    return WhalePresenceZone(
                        lower_bound=new_lower,
                        upper_bound=new_upper,
                        confidence=new_confidence,
                        bias=bias,
                        presence=False,
                        proximity=0.0,
                        center=(new_lower + new_upper) / 2,
                        width=new_upper - new_lower,
                        creation_time_ns=existing.creation_time_ns,
                        last_update_ns=exchange_ts_ns,
                        stability_count=existing.stability_count + 1,
                        accumulation_score=accumulation_score,
                    )
            
            # Create new zone
            center = (lower_bound + upper_bound) / 2
            width = upper_bound - lower_bound
            
            return WhalePresenceZone(
                lower_bound=lower_bound,
                upper_bound=upper_bound,
                confidence=confidence,
                bias=bias,
                presence=False,
                proximity=0.0,
                center=center,
                width=width,
                creation_time_ns=creation_time,
                last_update_ns=exchange_ts_ns,
                stability_count=1,
                accumulation_score=accumulation_score,
            )
        
        # No new zone detected, return existing if still valid
        if state.zone is not None:
            # Check TTL based on last_update_ns (evidence-based refresh only)
            time_since_refresh = exchange_ts_ns - state.zone.last_update_ns
            if time_since_refresh > self.zone_ttl_ns:
                # Zone expired
                return None
            
            # Decay confidence over time since last refresh
            if time_since_refresh > 0:
                decay_factor = 1.0 - min(0.5, time_since_refresh / self.zone_ttl_ns)
                updated_confidence = state.zone.confidence * decay_factor
                
                # Return updated zone with decayed confidence, preserving creation_time
                return WhalePresenceZone(
                    lower_bound=state.zone.lower_bound,
                    upper_bound=state.zone.upper_bound,
                    confidence=updated_confidence,
                    bias=state.zone.bias,
                    presence=False,
                    proximity=0.0,
                    center=state.zone.center,
                    width=state.zone.width,
                    creation_time_ns=state.zone.creation_time_ns,
                    last_update_ns=state.zone.last_update_ns,
                    stability_count=state.zone.stability_count,
                    accumulation_score=state.zone.accumulation_score * decay_factor,
                )
            
            return state.zone
        
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
            distance_to_lower = abs(price - zone.lower_bound)
            distance_to_upper = abs(price - zone.upper_bound)
            min_distance = min(distance_to_lower, distance_to_upper)
            proximity = 1.0 - min(1.0, min_distance / zone.width)
        
        # last_update_ns unchanged - only evidence refreshes zone life
        return WhalePresenceZone(
            lower_bound=zone.lower_bound,
            upper_bound=zone.upper_bound,
            confidence=zone.confidence,
            bias=zone.bias,
            presence=presence,
            proximity=proximity,
            center=zone.center,
            width=zone.width,
            creation_time_ns=zone.creation_time_ns,
            last_update_ns=zone.last_update_ns,
            stability_count=zone.stability_count,
            accumulation_score=zone.accumulation_score,
        )