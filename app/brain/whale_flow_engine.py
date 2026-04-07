"""
app/brain/whale_flow_engine.py

Deterministic, replay-safe whale flow detection for Poverty Killer.
Detects large-flow directional pressure as a directional alpha source.
Must contribute lawful directional edge, not decorative scoring.

Role: Directional alpha source / large-flow pressure detector / conviction input.
NOT: regime classifier, entropy substitute, insider urgency, toxicity detector.

CLOSED v4 - FINAL:
- Multi-tier whale detection (small/medium/mega)
- Recency-weighted persistence (exponential decay, alpha=0.7)
- Multi-factor abnormality detection (volume, size, concentration, imbalance)
- Gap-aware persistence degradation with sigmoid-like smooth transition
- Stale-state neutralization for conviction helpers
- Truthful time semantics via get_age_ns() and get_time_since_refresh()
- last_update_ns refreshes only on evidence (not on getters)
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Deque, Union, Any
from collections import deque
from enum import IntEnum
import numpy as np


class WhaleDirection(IntEnum):
    """Direction of whale flow."""
    NEUTRAL = 0
    BUY = 1
    SELL = -1


class AbnormalityLevel(IntEnum):
    """Level of flow abnormality."""
    LOW = 0
    MEDIUM = 1
    HIGH = 2
    EXTREME = 3


@dataclass
class WhaleFlowAlert:
    """
    Consumer-facing whale flow alert payload.
    Expected by downstream fusion.
    
    Fields:
    - direction: BUY/SELL/NEUTRAL
    - confidence: 0-1 conviction in direction
    - exchange_ts_ns: timestamp of last update
    - flow_imbalance: signed buy-sell imbalance [-1, 1]
    - avg_trade_size: normalized average trade size [0, 1]
    - concentration: trade size concentration [0, 1]
    - tier: 0=none, 1=small whale, 2=medium whale, 3=mega whale
    - absorption_score: 0-1 (high = passive absorption, low = aggressive directional)
    - abnormality_score: 0-1 continuous abnormality measure
    - abnormality_level: LOW/MEDIUM/HIGH/EXTREME
    - is_stale: True if last update is beyond staleness threshold
    - is_extremely_stale: True if last update is beyond 2x staleness threshold
    - last_update_ns: timestamp of last evidence-based refresh
    """
    direction: WhaleDirection
    confidence: float
    exchange_ts_ns: int
    flow_imbalance: float
    avg_trade_size: float
    concentration: float
    tier: int
    absorption_score: float
    abnormality_score: float
    abnormality_level: AbnormalityLevel
    is_stale: bool
    is_extremely_stale: bool
    last_update_ns: int


@dataclass
class WhaleEvidence:
    """Raw evidence for whale flow classification."""
    flow_imbalance: float          # Signed buy-sell imbalance [-1, 1]
    avg_trade_size: float          # Normalized average trade size [0, 1]
    concentration: float           # Trade size concentration [0, 1]
    persistence: float             # Recency-weighted persistent directional pressure [0, 1]
    recency_weighted_concentration: float  # Time-weighted concentration [0, 1]
    volume_zscore: float           # Deviation from rolling volume baseline
    acceleration: float            # Change in flow imbalance [-1, 1]
    abnormality_score: float       # Multi-factor abnormality [0, 1]
    exchange_ts_ns: int            # Timestamp of evidence
    gap_since_last_ns: int         # Time gap from previous event


@dataclass
class CachedWhaleState:
    """Internal state for deterministic whale tracking."""
    direction: WhaleDirection
    confidence: float
    flow_imbalance: float
    avg_trade_size: float
    concentration: float
    tier: int
    absorption_score: float
    abnormality_score: float
    exchange_ts_ns: int
    persistence_count: int
    is_stale: bool
    is_extremely_stale: bool
    last_update_ns: int


class WhaleFlowEngine:
    """
    Deterministic whale flow detector for directional alpha.
    
    Features (all operational):
    - Multi-tier detection (small/medium/mega whale)
    - Recency-weighted persistence (exponential decay, alpha=0.7)
    - Timestamp-aware freshness/staleness (configurable threshold, default 30s)
    - Multi-factor abnormality detection (volume, size, concentration, imbalance)
    - Gap-aware persistence degradation (sigmoid-like smooth transition)
    - Rolling baseline comparison (z-score detection)
    - Flow acceleration/deceleration
    - Stale-state neutralization for conviction helpers
    - Persistence requirements (2 consecutive for direction changes)
    - Exponential confidence decay for smooth transitions
    - Truthful time semantics via get_age_ns() and get_time_since_refresh()
    
    Direction states:
    - BUY: Persistent buy-side large-flow pressure
    - SELL: Persistent sell-side large-flow pressure
    - NEUTRAL: No dominant whale pressure or insufficient evidence
    
    Staleness behavior:
    - Events beyond stale_threshold_ns (default 30s) trigger conviction decay
    - Complete neutralization after 2x stale_threshold_ns
    - Gap-aware persistence reduction for irregular event spacing
    - last_update_ns refreshes only on evidence (not on getters)
    """

    # Default staleness threshold: 30 seconds in nanoseconds
    DEFAULT_STALENESS_THRESHOLD_NS = 30 * 1_000_000_000
    # Gap threshold for persistence degradation: 10 seconds
    DEFAULT_GAP_THRESHOLD_NS = 10 * 1_000_000_000
    # Recency weighting alpha (exponential decay factor)
    RECENCY_ALPHA = 0.7
    # Maximum gap factor (minimum persistence even with extreme gaps)
    MAX_GAP_FACTOR = 0.3

    def __init__(self, config: Optional[Union[Dict[str, Any], Any]] = None):
        """
        Initialize whale flow engine with optional configuration.
        
        Args:
            config: Either a dict with configuration keys or an object with
                    attribute-style configuration. Supports both calling patterns.
        """
        # Configuration with bounded defaults
        self.imbalance_threshold = 0.6
        self.size_threshold_small = 0.5
        self.size_threshold_medium = 0.7
        self.size_threshold_mega = 0.85
        self.concentration_threshold = 0.6
        self.persistence_required = 2
        self.decay_factor = 0.7
        self.min_history = 20
        self.volume_zscore_threshold = 1.5
        self.acceleration_threshold = 0.3
        self.stale_threshold_ns = self.DEFAULT_STALENESS_THRESHOLD_NS
        self.gap_threshold_ns = self.DEFAULT_GAP_THRESHOLD_NS
        
        if config is not None:
            if isinstance(config, dict):
                self.imbalance_threshold = config.get('imbalance_threshold', 0.6)
                self.size_threshold_small = config.get('size_threshold_small', 0.5)
                self.size_threshold_medium = config.get('size_threshold_medium', 0.7)
                self.size_threshold_mega = config.get('size_threshold_mega', 0.85)
                self.concentration_threshold = config.get('concentration_threshold', 0.6)
                self.persistence_required = config.get('persistence_required', 2)
                self.decay_factor = config.get('decay_factor', 0.7)
                self.min_history = config.get('min_history', 20)
                self.volume_zscore_threshold = config.get('volume_zscore_threshold', 1.5)
                self.acceleration_threshold = config.get('acceleration_threshold', 0.3)
                self.stale_threshold_ns = config.get('stale_threshold_ns', self.DEFAULT_STALENESS_THRESHOLD_NS)
                self.gap_threshold_ns = config.get('gap_threshold_ns', self.DEFAULT_GAP_THRESHOLD_NS)
            else:
                if hasattr(config, 'imbalance_threshold'):
                    self.imbalance_threshold = getattr(config, 'imbalance_threshold', 0.6)
                if hasattr(config, 'size_threshold_small'):
                    self.size_threshold_small = getattr(config, 'size_threshold_small', 0.5)
                if hasattr(config, 'size_threshold_medium'):
                    self.size_threshold_medium = getattr(config, 'size_threshold_medium', 0.7)
                if hasattr(config, 'size_threshold_mega'):
                    self.size_threshold_mega = getattr(config, 'size_threshold_mega', 0.85)
                if hasattr(config, 'concentration_threshold'):
                    self.concentration_threshold = getattr(config, 'concentration_threshold', 0.6)
                if hasattr(config, 'persistence_required'):
                    self.persistence_required = getattr(config, 'persistence_required', 2)
                if hasattr(config, 'decay_factor'):
                    self.decay_factor = getattr(config, 'decay_factor', 0.7)
                if hasattr(config, 'min_history'):
                    self.min_history = getattr(config, 'min_history', 20)
                if hasattr(config, 'volume_zscore_threshold'):
                    self.volume_zscore_threshold = getattr(config, 'volume_zscore_threshold', 1.5)
                if hasattr(config, 'acceleration_threshold'):
                    self.acceleration_threshold = getattr(config, 'acceleration_threshold', 0.3)
                if hasattr(config, 'stale_threshold_ns'):
                    self.stale_threshold_ns = getattr(config, 'stale_threshold_ns', self.DEFAULT_STALENESS_THRESHOLD_NS)
                if hasattr(config, 'gap_threshold_ns'):
                    self.gap_threshold_ns = getattr(config, 'gap_threshold_ns', self.DEFAULT_GAP_THRESHOLD_NS)
        
        # Rolling history for evidence
        # Store signed imbalance to preserve directional information for persistence
        self._signed_imbalance_history: Deque[float] = deque(maxlen=100)
        self._size_history: Deque[float] = deque(maxlen=100)
        self._concentration_history: Deque[float] = deque(maxlen=100)
        self._volume_history: Deque[float] = deque(maxlen=100)
        self._timestamp_history: Deque[int] = deque(maxlen=100)
        
        # Rolling baseline for volume normalization
        self._rolling_volume_mean: float = 0.0
        self._rolling_volume_std: float = 1.0
        
        # Current whale state
        self._current_state: Optional[CachedWhaleState] = None
        self._pending_direction: Optional[WhaleDirection] = None
        self._pending_count: int = 0
        
        # Decayed conviction for smooth transitions
        self._decayed_confidence: float = 0.0
        
        # Timestamp tracking for staleness and gap awareness
        self._last_event_ts_ns: int = 0
        self._event_gap_ns: int = 0
        
        # Last output cache
        self._last_alert: Optional[WhaleFlowAlert] = None
        self._last_direction: WhaleDirection = WhaleDirection.NEUTRAL
        self._last_confidence: float = 0.0
        self._last_timestamp_ns: int = 0

    # ========================================================================
    # Public API
    # ========================================================================

    def update(
        self,
        buy_volume: float,
        sell_volume: float,
        trade_sizes: List[float],
        exchange_ts_ns: int,
    ) -> WhaleFlowAlert:
        """
        Update whale flow engine with new trade data.
        
        Args:
            buy_volume: Total buy volume in period
            sell_volume: Total sell volume in period
            trade_sizes: List of trade sizes in period
            exchange_ts_ns: Exchange timestamp in nanoseconds
        
        Returns:
            WhaleFlowAlert with direction, confidence, and all derived metrics
        """
        # Track event gap for persistence degradation
        if self._last_event_ts_ns > 0:
            self._event_gap_ns = exchange_ts_ns - self._last_event_ts_ns
        else:
            self._event_gap_ns = 0
        self._last_event_ts_ns = exchange_ts_ns
        
        # Compute core evidence
        total_volume = buy_volume + sell_volume
        flow_imbalance = (buy_volume - sell_volume) / (total_volume + 1e-8)
        
        avg_trade_size = 0.0
        concentration = 0.0
        
        if trade_sizes:
            avg_trade_size = np.mean(trade_sizes)
            # Normalize average trade size (assuming 100k as "whale" threshold)
            normalized_avg = min(1.0, avg_trade_size / 100_000.0)
            
            # Concentration: how much of volume comes from largest trades
            sorted_sizes = sorted(trade_sizes, reverse=True)
            top_3_volume = sum(sorted_sizes[:3]) if len(sorted_sizes) >= 3 else sum(sorted_sizes)
            concentration = min(1.0, top_3_volume / (total_volume + 1e-8))
        else:
            normalized_avg = 0.0
            concentration = 0.0
        
        # Update volume history and rolling baseline
        self._volume_history.append(total_volume)
        self._update_rolling_baseline()
        
        # Compute volume z-score (deviation from baseline)
        volume_zscore = 0.0
        if self._rolling_volume_std > 0 and len(self._volume_history) >= self.min_history:
            volume_zscore = (total_volume - self._rolling_volume_mean) / self._rolling_volume_std
        
        # Update histories with signed imbalance (preserves direction)
        self._signed_imbalance_history.append(flow_imbalance)
        self._size_history.append(normalized_avg)
        self._concentration_history.append(concentration)
        self._timestamp_history.append(exchange_ts_ns)
        
        # Compute recency-weighted persistence
        persistence = self._compute_recency_weighted_persistence()
        
        # Compute recency-weighted concentration
        recency_weighted_concentration = self._compute_recency_weighted_concentration()
        
        # Compute acceleration (change in flow imbalance)
        acceleration = self._compute_acceleration()
        
        # Determine whale tier based on size and concentration
        tier = self._determine_tier(normalized_avg, concentration)
        
        # Compute absorption score (aggressive vs passive flow)
        absorption_score = self._compute_absorption_score(flow_imbalance, concentration, volume_zscore)
        
        # Compute multi-factor abnormality score
        abnormality_score, abnormality_level = self._compute_abnormality(
            volume_zscore, normalized_avg, concentration, abs(flow_imbalance), tier
        )
        
        # Compute gap-aware persistence degradation (sigmoid-like smooth transition)
        gap_degraded_persistence = self._apply_gap_aware_decay(persistence)
        
        # Compute staleness metrics
        latest_ts = self._get_latest_timestamp()
        staleness_ratio = self._get_staleness_ratio(exchange_ts_ns, latest_ts)
        is_stale = staleness_ratio > 0.0
        is_extremely_stale = staleness_ratio >= 2.0
        
        # Compute evidence
        evidence = WhaleEvidence(
            flow_imbalance=flow_imbalance,
            avg_trade_size=normalized_avg,
            concentration=concentration,
            persistence=gap_degraded_persistence,
            recency_weighted_concentration=recency_weighted_concentration,
            volume_zscore=volume_zscore,
            acceleration=acceleration,
            abnormality_score=abnormality_score,
            exchange_ts_ns=exchange_ts_ns,
            gap_since_last_ns=self._event_gap_ns,
        )
        
        # Classify whale direction from evidence
        raw_direction, raw_confidence = self._classify_from_evidence(evidence, tier)
        
        # Apply persistence requirement and decay
        final_direction, final_confidence = self._apply_persistence_decay(raw_direction, raw_confidence)
        
        # Apply freshness gating (timestamp-aware confidence reduction)
        final_confidence = self._apply_freshness_gating(final_confidence, exchange_ts_ns, latest_ts, staleness_ratio)
        
        # If stale, direction may be neutralized
        if is_extremely_stale:
            final_direction = WhaleDirection.NEUTRAL
            final_confidence = 0.0
        elif is_stale and final_confidence < 0.1:
            final_direction = WhaleDirection.NEUTRAL
        
        # Build consumer-facing alert
        alert = WhaleFlowAlert(
            direction=final_direction,
            confidence=final_confidence,
            exchange_ts_ns=exchange_ts_ns,
            flow_imbalance=flow_imbalance,
            avg_trade_size=normalized_avg,
            concentration=concentration,
            tier=tier,
            absorption_score=absorption_score,
            abnormality_score=abnormality_score,
            abnormality_level=abnormality_level,
            is_stale=is_stale,
            is_extremely_stale=is_extremely_stale,
            last_update_ns=exchange_ts_ns,
        )
        
        # Store state
        self._current_state = CachedWhaleState(
            direction=final_direction,
            confidence=final_confidence,
            flow_imbalance=flow_imbalance,
            avg_trade_size=normalized_avg,
            concentration=concentration,
            tier=tier,
            absorption_score=absorption_score,
            abnormality_score=abnormality_score,
            exchange_ts_ns=exchange_ts_ns,
            persistence_count=self._pending_count,
            is_stale=is_stale,
            is_extremely_stale=is_extremely_stale,
            last_update_ns=exchange_ts_ns,
        )
        
        self._last_alert = alert
        self._last_direction = final_direction
        self._last_confidence = final_confidence
        self._last_timestamp_ns = exchange_ts_ns
        
        return alert

    def get_current_alert(self) -> Optional[WhaleFlowAlert]:
        """Get the most recent whale flow alert."""
        return self._last_alert

    def get_current_direction(self) -> WhaleDirection:
        """Get the most recent whale direction."""
        return self._last_direction

    def get_current_confidence(self) -> float:
        """Get the most recent whale confidence."""
        return self._last_confidence

    def get_age_ns(self, current_ts_ns: int) -> int:
        """
        Get time since last update in nanoseconds.
        Returns 0 if no alert exists.
        """
        if self._last_alert is None:
            return 0
        return current_ts_ns - self._last_alert.last_update_ns

    def get_time_since_refresh(self, current_ts_ns: int) -> int:
        """
        Get time since last evidence-based refresh.
        Returns 0 if no alert exists.
        """
        if self._last_alert is None:
            return 0
        return current_ts_ns - self._last_alert.last_update_ns

    def get_directional_bias(self) -> float:
        """
        Get directional bias for fusion.
        
        Returns:
            float: -1.0 (bearish), 0.0 (neutral), 1.0 (bullish)
            Returns 0.0 if state is stale or extremely stale.
        """
        # Neutralize if stale (no fresh whale signal)
        if self._last_alert is None:
            return 0.0
        
        if self._last_alert.is_extremely_stale:
            return 0.0
        if self._last_alert.is_stale and self._last_alert.confidence < 0.1:
            return 0.0
        
        if self._last_direction == WhaleDirection.BUY:
            return 1.0
        elif self._last_direction == WhaleDirection.SELL:
            return -1.0
        return 0.0

    def get_conviction_multiplier(self) -> float:
        """
        Get conviction multiplier for confidence scaling.
        
        Returns:
            float: Multiplier in [0.5, 1.5], where >1.0 increases conviction
            Returns 0.5 (minimum) if state is extremely stale.
        """
        if self._last_alert is None:
            return 0.5
        
        # Stale state reduces conviction to minimum
        if self._last_alert.is_extremely_stale:
            return 0.5
        
        confidence = self._last_confidence
        
        # Map confidence [0,1] to multiplier [0.5, 1.5]
        multiplier = 0.5 + confidence
        
        return min(1.5, max(0.5, multiplier))

    # ========================================================================
    # Internal Methods
    # ========================================================================

    def _update_rolling_baseline(self) -> None:
        """Update rolling mean and std for volume baseline."""
        if len(self._volume_history) >= self.min_history:
            recent_volumes = list(self._volume_history)[-self.min_history:]
            self._rolling_volume_mean = np.mean(recent_volumes)
            self._rolling_volume_std = max(np.std(recent_volumes), 1e-8)

    def _get_latest_timestamp(self) -> int:
        """Get the latest timestamp from history. Returns 0 if no history."""
        if not self._timestamp_history:
            return 0
        return max(self._timestamp_history)

    def _get_staleness_ratio(self, timestamp_ns: int, latest_ts: int) -> float:
        """
        Compute staleness ratio: (latest_ts - timestamp_ns) / stale_threshold_ns.
        Returns > 0 for stale events, >= 2.0 for extremely stale.
        Uncapped for threshold comparisons.
        """
        if latest_ts == 0 or timestamp_ns == 0:
            return 0.0
        staleness_duration = latest_ts - timestamp_ns
        if staleness_duration <= 0:
            return 0.0
        return staleness_duration / self.stale_threshold_ns

    def _compute_recency_weighted_persistence(self) -> float:
        """
        Compute recency-weighted persistence of directional pressure.
        Uses exponential decay weighting: recent imbalances have higher weight.
        Alpha = 0.7, so weight = alpha^(position_from_end)
        Handles both buy and sell persistence symmetrically.
        """
        if len(self._signed_imbalance_history) < self.min_history:
            return 0.0
        
        imbalances = list(self._signed_imbalance_history)[-self.min_history:]
        
        # Determine current directional sign from most recent imbalance
        current_imbalance = imbalances[-1]
        if abs(current_imbalance) < 0.1:
            return 0.0
        
        current_sign = 1 if current_imbalance > 0 else -1
        
        # Compute recency-weighted persistence
        total_weight = 0.0
        same_sign_weight = 0.0
        
        for i, imb in enumerate(imbalances):
            # Position from end (0 = most recent)
            pos_from_end = len(imbalances) - 1 - i
            weight = self.RECENCY_ALPHA ** pos_from_end
            
            imb_sign = 1 if imb > 0 else -1 if imb < 0 else 0
            if imb_sign == current_sign:
                same_sign_weight += weight
            total_weight += weight
        
        persistence = same_sign_weight / (total_weight + 1e-8)
        return persistence

    def _compute_recency_weighted_concentration(self) -> float:
        """
        Compute recency-weighted concentration score.
        Recent concentration values have higher weight.
        """
        if len(self._concentration_history) < self.min_history:
            return 0.0
        
        concentrations = list(self._concentration_history)[-self.min_history:]
        
        total_weight = 0.0
        weighted_sum = 0.0
        
        for i, conc in enumerate(concentrations):
            pos_from_end = len(concentrations) - 1 - i
            weight = self.RECENCY_ALPHA ** pos_from_end
            weighted_sum += conc * weight
            total_weight += weight
        
        return weighted_sum / (total_weight + 1e-8)

    def _compute_acceleration(self) -> float:
        """
        Compute acceleration/deceleration of flow imbalance.
        Positive acceleration = increasing buy pressure.
        Negative acceleration = increasing sell pressure.
        """
        if len(self._signed_imbalance_history) < 3:
            return 0.0
        
        recent = list(self._signed_imbalance_history)[-3:]
        diff1 = recent[-1] - recent[-2]
        diff2 = recent[-2] - recent[-3]
        
        acceleration = diff1 - diff2
        return np.clip(acceleration, -1.0, 1.0)

    def _determine_tier(self, normalized_avg: float, concentration: float) -> int:
        """
        Determine whale tier based on trade size and concentration.
        1 = small whale, 2 = medium whale, 3 = mega whale.
        """
        # Combined score from size and concentration
        combined_score = (normalized_avg * 0.6 + concentration * 0.4)
        
        if combined_score >= self.size_threshold_mega:
            return 3
        elif combined_score >= self.size_threshold_medium:
            return 2
        elif combined_score >= self.size_threshold_small:
            return 1
        return 0

    def _compute_absorption_score(self, flow_imbalance: float, concentration: float, volume_zscore: float) -> float:
        """
        Compute absorption vs aggressive flow score.
        High absorption_score = passive absorption (market making, not directional).
        Low absorption_score = aggressive directional flow.
        """
        # Aggressive flow has high imbalance, high concentration, high volume z-score
        aggressive_indicators = (
            (abs(flow_imbalance) * 0.4) +
            (concentration * 0.3) +
            (min(1.0, volume_zscore / 3.0) * 0.3)
        )
        
        # Absorption is the inverse
        absorption_score = 1.0 - min(1.0, aggressive_indicators)
        
        return absorption_score

    def _compute_abnormality(
        self,
        volume_zscore: float,
        avg_trade_size: float,
        concentration: float,
        imbalance_strength: float,
        tier: int,
    ) -> Tuple[float, AbnormalityLevel]:
        """
        Compute multi-factor abnormality score and level.
        
        Factors:
        - Volume z-score (deviation from baseline)
        - Size abnormality (how large are trades)
        - Concentration abnormality (how concentrated is volume)
        - Imbalance intensity (how strong is directional pressure)
        
        Returns (abnormality_score, abnormality_level)
        """
        # Normalize volume z-score to [0, 1] (cap at 3 sigma)
        volume_abnormality = min(1.0, volume_zscore / 3.0)
        
        # Size abnormality: larger than typical whale threshold
        size_abnormality = min(1.0, avg_trade_size / self.size_threshold_mega)
        
        # Concentration abnormality: high concentration is abnormal
        concentration_abnormality = concentration
        
        # Imbalance intensity: high imbalance is abnormal
        imbalance_abnormality = imbalance_strength
        
        # Weighted combination
        abnormality_score = (
            volume_abnormality * 0.40 +
            size_abnormality * 0.30 +
            concentration_abnormality * 0.20 +
            imbalance_abnormality * 0.10
        )
        
        # Tier amplification: mega whales are more abnormal
        if tier == 3:
            abnormality_score = min(1.0, abnormality_score * 1.5)
        elif tier == 2:
            abnormality_score = min(1.0, abnormality_score * 1.2)
        
        # Determine level
        if abnormality_score >= 0.8:
            level = AbnormalityLevel.EXTREME
        elif abnormality_score >= 0.6:
            level = AbnormalityLevel.HIGH
        elif abnormality_score >= 0.3:
            level = AbnormalityLevel.MEDIUM
        else:
            level = AbnormalityLevel.LOW
        
        return abnormality_score, level

    def _apply_gap_aware_decay(self, persistence: float) -> float:
        """
        Apply gap-aware decay to persistence using sigmoid-like smooth transition.
        gap_factor = 1 / (1 + gap/gap_threshold), ranging from 1.0 (gap=0) to 0.0 (gap=infinity)
        Minimum persistence floor = MAX_GAP_FACTOR to preserve some signal.
        """
        if self._event_gap_ns <= 0:
            return persistence
        
        # Sigmoid-like smooth decay: factor = 1 / (1 + ratio)
        ratio = self._event_gap_ns / self.gap_threshold_ns
        gap_factor = 1.0 / (1.0 + ratio)
        
        # Ensure minimum persistence even with extreme gaps
        gap_factor = max(gap_factor, self.MAX_GAP_FACTOR)
        
        # Apply decay
        decayed_persistence = persistence * gap_factor
        
        return decayed_persistence

    def _apply_freshness_gating(self, confidence: float, timestamp_ns: int, latest_ts: int, staleness_ratio: float) -> float:
        """
        Apply timestamp-aware freshness gating to confidence.
        
        Uses uncapped staleness_ratio for threshold decisions (2x = full neutralization).
        Uses capped factor for partial degradation math.
        """
        if staleness_ratio <= 0.0:
            return confidence
        
        # Capped staleness factor for partial degradation (max 1.0)
        capped_factor = min(1.0, staleness_ratio)
        
        # Reduce confidence based on staleness
        gated_confidence = confidence * (1.0 - capped_factor * 0.7)
        
        # Complete neutralization if extremely stale (2x threshold)
        if staleness_ratio >= 2.0:
            gated_confidence = 0.0
        
        return max(0.0, min(1.0, gated_confidence))

    def _classify_from_evidence(self, evidence: WhaleEvidence, tier: int) -> Tuple[WhaleDirection, float]:
        """
        Classify whale direction from evidence with confidence.
        Returns (direction, confidence).
        """
        # Check if we have sufficient evidence
        if (evidence.avg_trade_size < self.size_threshold_small and 
            evidence.concentration < self.concentration_threshold):
            return WhaleDirection.NEUTRAL, 0.2
        
        # Volume z-score boost: abnormal volume increases confidence
        volume_boost = min(0.3, max(0.0, (evidence.volume_zscore - 1.0) / 5.0))
        
        # Acceleration boost: increasing pressure increases confidence
        accel_boost = max(0.0, evidence.acceleration * 0.2) if evidence.flow_imbalance > 0 else max(0.0, -evidence.acceleration * 0.2)
        
        # Abnormality boost: higher abnormality increases confidence
        abnormality_boost = evidence.abnormality_score * 0.15
        
        # Tier boost: larger whales get higher confidence
        tier_boost = 0.0
        if tier == 3:
            tier_boost = 0.15
        elif tier == 2:
            tier_boost = 0.08
        elif tier == 1:
            tier_boost = 0.03
        
        # Calculate directional strength from signed imbalance
        imbalance_strength = abs(evidence.flow_imbalance)
        
        # Direction is determined by signed flow_imbalance
        if evidence.flow_imbalance > self.imbalance_threshold:
            raw_direction = WhaleDirection.BUY
        elif evidence.flow_imbalance < -self.imbalance_threshold:
            raw_direction = WhaleDirection.SELL
        else:
            return WhaleDirection.NEUTRAL, max(0.1, imbalance_strength * 0.5)
        
        # Compute confidence based on evidence quality
        size_contrib = min(0.35, evidence.avg_trade_size * 0.35)
        concentration_contrib = min(0.25, evidence.recency_weighted_concentration * 0.25)
        persistence_contrib = min(0.3, evidence.persistence * 0.3)
        
        confidence = min(0.95, 0.15 + size_contrib + concentration_contrib + persistence_contrib + volume_boost + accel_boost + abnormality_boost + tier_boost)
        
        return raw_direction, confidence

    def _apply_persistence_decay(self, raw_direction: WhaleDirection, raw_confidence: float) -> Tuple[WhaleDirection, float]:
        """
        Apply persistence requirement and exponential decay.
        Prevents single-print whale signals and smooths transitions.
        """
        # Apply decay to previous confidence
        self._decayed_confidence = self._decayed_confidence * self.decay_factor
        
        # Neutral direction is always accepted immediately
        if raw_direction == WhaleDirection.NEUTRAL:
            self._pending_direction = None
            self._pending_count = 0
            self._decayed_confidence = max(self._decayed_confidence, raw_confidence * 0.3)
            return WhaleDirection.NEUTRAL, max(0.0, min(1.0, self._decayed_confidence))
        
        # For directional signals, require persistence
        if self._pending_direction == raw_direction:
            self._pending_count += 1
        else:
            self._pending_direction = raw_direction
            self._pending_count = 1
        
        if self._pending_count >= self.persistence_required:
            self._decayed_confidence = max(self._decayed_confidence, raw_confidence)
            self._pending_count = 0
            return raw_direction, min(1.0, self._decayed_confidence)
        
        # Not enough persistence yet: return previous direction with decayed confidence
        return self._last_direction, max(0.0, min(1.0, self._decayed_confidence * 0.5))

    def reset(self) -> None:
        """Reset all internal state for deterministic replay safety."""
        self._signed_imbalance_history.clear()
        self._size_history.clear()
        self._concentration_history.clear()
        self._volume_history.clear()
        self._timestamp_history.clear()
        self._rolling_volume_mean = 0.0
        self._rolling_volume_std = 1.0
        self._current_state = None
        self._pending_direction = None
        self._pending_count = 0
        self._decayed_confidence = 0.0
        self._last_event_ts_ns = 0
        self._event_gap_ns = 0
        self._last_alert = None
        self._last_direction = WhaleDirection.NEUTRAL
        self._last_confidence = 0.0
        self._last_timestamp_ns = 0