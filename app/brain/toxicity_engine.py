"""
Toxicity Engine - Market Toxicity / Adverse Flow Detection
CITADEL GRADE — DETERMINISTIC · REPLAY-SAFE · NO WALL-CLOCK

ANALYTICAL/NON-MONETARY BOUNDARY:
This file performs analytical signal processing using float64 for performance.
It estimates market toxicity / adverse selection pressure using bounded analytical proxies.
These are NOT monetary truth or execution guarantees.

DETERMINISTIC BEHAVIOR:
- No wall-clock time (datetime.utcnow, timedelta)
- No random number generation
- All timing uses integer nanoseconds from authoritative external sources
- All toxicity calculations are deterministic given identical inputs
- Strict timestamp monotonicity enforced on update methods only
- Read/query methods are pure (do not mutate state)
- Honest degradation when microstructure inputs are unavailable
- Deterministic binary serialization with explicit schema version (no pickle)
- Adaptive calibration is optional, label-driven, bounded, and replay-safe

STATE MANAGEMENT:
- update_toxicity() advances state and returns current ToxicityAlert
- update_outcome() provides realized labels for calibration (optional)
- get_last_alert() returns last computed alert (read-only)
- is_toxic() and get_suppression_factor() operate on last computed state
- get_stats() returns statistics without advancing state
- get_calibration_weights() returns current calibrated weights (read-only)

OPTIONAL ENHANCEMENTS (HONEST DEGRADATION):
- L2 order book imbalance: when real L2 inputs provided via update_order_book()
- Cross-exchange fragmentation: when multiple venue snapshots provided via update_venue_snapshot()
- Adaptive calibration: when realized labels provided via update_outcome()
- If richer inputs absent, engine continues in approved proxy mode
- No fake connectors or hallucinated data
"""

import logging
import numpy as np
import struct
import hashlib
from typing import Optional, Dict, List, Tuple, Any
from dataclasses import dataclass
from collections import deque
from enum import IntEnum

logger = logging.getLogger(__name__)

# Numerical stability epsilon
EPS = np.finfo(float).eps


class ToxicityRegime(IntEnum):
    """Deterministic toxicity regime states."""
    NORMAL = 0       # Low toxicity, normal conditions
    ELEVATED = 1     # Elevated toxicity, caution advised
    TOXIC = 2        # High toxicity, suppress aggressive strategies
    EXTREME = 3      # Extreme toxicity, halt new entries


@dataclass
class ToxicityAlert:
    """
    Toxicity alert from engine.
    
    All values are analytical estimates, not monetary truth.
    """
    toxicity_score: float          # 0-1, higher = more toxic
    regime: ToxicityRegime         # Current toxicity regime
    direction_bias: str            # "buy", "sell", or "neutral"
    vpin_proxy: float              # Volume imbalance proxy (0-1)
    burst_pressure: float          # Trade clustering pressure (0-1)
    instability_score: float       # Quote/range instability (0-1)
    volume_anomaly: float          # Volume vs rolling average (z-score)
    persistence: float             # How long toxicity has persisted (0-1)
    confidence: float              # Analytical confidence (0-1)
    timestamp_ns: int
    reason: str


@dataclass
class L2Snapshot:
    """L2 order book snapshot for imbalance calculation."""
    bid_volume: float
    ask_volume: float
    best_bid: float
    best_ask: float
    timestamp_ns: int
    depth_weighted_bid: Optional[float] = None
    depth_weighted_ask: Optional[float] = None


@dataclass
class VenueSnapshot:
    """Multi-venue snapshot for fragmentation detection."""
    venue: str
    price: float
    spread: float
    volume_proxy: float
    timestamp_ns: int
    best_bid: Optional[float] = None
    best_ask: Optional[float] = None


@dataclass
class RealizedOutcome:
    """
    Realized toxicity outcome for calibration.
    
    This is the explicit label that enables adaptive calibration.
    No label = baseline behavior preserved.
    """
    timestamp_ns: int
    realized_regime: ToxicityRegime
    realized_toxicity_score: float
    adverse_event_occurred: bool = False
    suppression_effectiveness: float = 0.5  # 0-1, higher = more effective


class ToxicityEngine:
    """
    Market toxicity / adverse flow detection engine.
    
    This engine estimates adverse selection pressure and flow toxicity
    using bounded analytical proxies. It does NOT require L2 order book
    or full trade feed — degrades gracefully with candle data.
    
    ADAPTIVE CALIBRATION (OPTIONAL, LABEL-DRIVEN):
    - When realized outcomes are provided via update_outcome(), weights are
      adjusted using deterministic online gradient-style updates
    - No labels = baseline weights preserved (approved behavior unchanged)
    - Adaptation is bounded, replay-safe, and auditable
    - No randomness, no ML black box, no hidden channels
    
    TOXICITY COMPONENTS:
    - VPIN proxy: volume imbalance / directional pressure
    - Burst pressure: trade clustering / event clustering
    - Instability score: range/volatility stress
    - Volume anomaly: unexpected volume spikes
    - Persistence: sustained toxicity over time
    - L2 imbalance (optional): order book asymmetry when available
    - Fragmentation (optional): cross-venue divergence when available
    
    TIMING AUTHORITY:
    - All timestamps must be provided by external authoritative source
    - No internal time generation
    - Strict per‑channel timestamp monotonicity enforced on all update methods:
      * trade channel (update_trade)
      * candle channel (update_candle)
      * L2 channel (update_order_book)
      * venue channel (update_venue_snapshot) – per‑venue monotonic
      * outcome channel (update_outcome)
      * toxicity channel (update_toxicity)
    - Each channel enforces its own monotonic ordering, allowing heterogeneous feeds
    
    STATE MANAGEMENT:
    - Call update_toxicity() to advance state and get current toxicity
    - Query methods (get_last_alert, is_toxic, get_suppression_factor, get_stats)
      are read-only and do not mutate state
    - Serialization methods (serialize_state, deserialize_state) are deterministic
    - Calibration state is serialized with the rest of the engine
    
    INPUT HONESTY:
    - This engine can operate in different modes based on available inputs
    - Trade-level data (size, side) is preferred but not required
    - Candle-level proxy mode uses volume, price, and range data
    - L2 mode is optional and only used when real L2 inputs are provided
    - Cross-exchange fragmentation mode is optional and only used when multiple venue snapshots are present
    - Adaptive calibration is optional and only used when realized outcomes are provided
    - Never invents missing microstructure fields
    """
    
    # Default parameters
    DEFAULT_VPIN_THRESHOLD = 0.75
    DEFAULT_BURST_THRESHOLD = 0.7
    DEFAULT_INSTABILITY_THRESHOLD = 0.7
    DEFAULT_VOLUME_ANOMALY_THRESHOLD = 2.0
    DEFAULT_PERSISTENCE_WINDOW = 10
    DEFAULT_TOXIC_DECAY_NS = 30_000_000_000  # 30 seconds
    DEFAULT_HISTORY_MAXLEN = 1000
    DEFAULT_L2_WEIGHT = 0.15
    DEFAULT_FRAGMENTATION_WEIGHT = 0.10
    
    # Calibration parameters
    DEFAULT_CALIBRATION_LEARNING_RATE = 0.05
    DEFAULT_CALIBRATION_SMOOTHING = 0.8
    DEFAULT_MIN_WEIGHT = 0.01
    DEFAULT_MAX_WEIGHT = 0.60
    DEFAULT_MIN_CALIBRATION_SAMPLES = 10
    
    # Serialization schema version
    SERIALIZATION_VERSION = 3  # Version 3: per‑channel monotonic timestamps + full history continuity
    
    def __init__(
        self,
        symbol: str,
        toxicity_threshold: float = 0.75,
        volume_bucket_units: float = 1_000_000.0,  # 1M units per bucket (proxy)
        lookback_buckets: int = 20,
        persistence_window: int = 10,
        toxic_decay_ns: int = 30_000_000_000,
        vpin_weight: float = 0.35,
        burst_weight: float = 0.25,
        instability_weight: float = 0.20,
        volume_anomaly_weight: float = 0.20,
        enable_candle_proxy_mode: bool = True,
        l2_weight: float = 0.15,
        fragmentation_weight: float = 0.10,
        max_venues: int = 5,
        enable_calibration: bool = True,
        calibration_learning_rate: float = 0.05,
        calibration_smoothing: float = 0.8,
        min_calibration_samples: int = 10
    ):
        """
        Initialize toxicity engine.
        
        Args:
            symbol: Trading symbol
            toxicity_threshold: Threshold for TOXIC regime (0-1)
            volume_bucket_units: Volume units per VPIN bucket (proxy)
            lookback_buckets: Number of buckets for baseline
            persistence_window: Window for persistence calculation
            toxic_decay_ns: Decay time for toxicity state (nanoseconds)
            vpin_weight: Weight for VPIN component
            burst_weight: Weight for burst pressure component
            instability_weight: Weight for instability component
            volume_anomaly_weight: Weight for volume anomaly component
            enable_candle_proxy_mode: Allow proxy mode with candle-only data
            l2_weight: Weight for L2 imbalance component (when available)
            fragmentation_weight: Weight for fragmentation component (when available)
            max_venues: Maximum venues to track for fragmentation
            enable_calibration: Enable adaptive weight calibration
            calibration_learning_rate: Learning rate for online weight updates
            calibration_smoothing: Smoothing factor for weight updates (0-1)
            min_calibration_samples: Minimum samples before calibration active
        """
        self.symbol = symbol
        self.toxicity_threshold = toxicity_threshold
        self.volume_bucket_units = volume_bucket_units
        self.lookback_buckets = lookback_buckets
        self.persistence_window = persistence_window
        self.toxic_decay_ns = toxic_decay_ns
        self.enable_candle_proxy_mode = enable_candle_proxy_mode
        self.l2_weight = l2_weight
        self.fragmentation_weight = fragmentation_weight
        self.max_venues = max_venues
        self.enable_calibration = enable_calibration
        self.calibration_learning_rate = calibration_learning_rate
        self.calibration_smoothing = calibration_smoothing
        self.min_calibration_samples = min_calibration_samples
        
        # Base component weights
        self._base_weights = {
            'vpin': vpin_weight,
            'burst': burst_weight,
            'instability': instability_weight,
            'volume_anomaly': volume_anomaly_weight,
            'l2': l2_weight,
            'fragmentation': fragmentation_weight
        }
        
        # Current calibrated weights (starts as base weights)
        self._calibrated_weights = self._base_weights.copy()
        
        # Calibration state
        self._calibration_samples: int = 0
        self._calibration_active: bool = False
        self._last_predicted_score: Optional[float] = None
        self._last_predicted_regime: Optional[ToxicityRegime] = None
        self._last_prediction_timestamp_ns: Optional[int] = None
        self._last_component_scores: Dict[str, float] = {}
        self._calibration_error_history: deque = deque(maxlen=persistence_window)
        
        # Current bucket state (for VPIN proxy)
        self._current_volume: float = 0.0
        self._current_buy_volume: float = 0.0
        self._current_sell_volume: float = 0.0
        self._current_trade_count: int = 0
        
        # Historical buckets (circular buffers)
        self._bucket_volumes: deque = deque(maxlen=lookback_buckets)
        self._bucket_buy_volumes: deque = deque(maxlen=lookback_buckets)
        self._bucket_sell_volumes: deque = deque(maxlen=lookback_buckets)
        self._bucket_vpin: deque = deque(maxlen=lookback_buckets)
        
        # Trade history for burst detection (if trade data available)
        self._trade_timestamps_ns: deque = deque(maxlen=self.DEFAULT_HISTORY_MAXLEN)
        self._trade_sizes: deque = deque(maxlen=self.DEFAULT_HISTORY_MAXLEN)
        self._trade_sides: deque = deque(maxlen=self.DEFAULT_HISTORY_MAXLEN)  # +1 buy, -1 sell
        
        # Candle history for proxy mode
        self._candle_volumes: deque = deque(maxlen=lookback_buckets * 2)
        self._candle_ranges: deque = deque(maxlen=lookback_buckets * 2)  # high-low
        self._candle_closes: deque = deque(maxlen=lookback_buckets * 2)
        
        # L2 order book history (optional)
        self._l2_snapshots: deque = deque(maxlen=lookback_buckets)
        self._l2_imbalance_history: deque = deque(maxlen=persistence_window)
        
        # Cross-venue fragmentation history (optional)
        self._venue_snapshots: Dict[str, deque] = {}
        self._fragmentation_history: deque = deque(maxlen=persistence_window)
        
        # Toxicity history for persistence
        self._toxicity_history: deque = deque(maxlen=persistence_window)
        
        # Rolling statistics for volume anomaly
        self._volume_history: deque = deque(maxlen=lookback_buckets * 2)
        
        # State
        self._last_alert: Optional[ToxicityAlert] = None
        self._toxic_start_ns: Optional[int] = None
        
        # Mode flags
        self._has_trade_data: bool = False
        self._has_l2_data: bool = False
        self._has_multi_venue: bool = False
        
        # Per‑channel monotonic timestamp enforcement
        self._last_channel_ts_ns: Dict[str, Optional[int]] = {
            'trade': None,
            'candle': None,
            'l2': None,
            'venue': None,          # global venue channel (across all venues)
            'outcome': None,
            'toxicity': None,
        }
        # Per‑venue monotonic timestamps
        self._last_venue_ts_ns: Dict[str, Optional[int]] = {}
        
        logger.info(f"ToxicityEngine initialized for {symbol}")
        logger.info(f"  Toxicity threshold: {toxicity_threshold}, lookback_buckets: {lookback_buckets}")
        logger.info(f"  Base weights: VPIN={vpin_weight:.2f}, Burst={burst_weight:.2f}, "
                   f"Instability={instability_weight:.2f}, VolAnomaly={volume_anomaly_weight:.2f}, "
                   f"L2={l2_weight:.2f}, Frag={fragmentation_weight:.2f}")
        if enable_candle_proxy_mode:
            logger.info("  Candle proxy mode: ENABLED (degrades gracefully without trade data)")
        if enable_calibration:
            logger.info(f"  Adaptive calibration: ENABLED (lr={calibration_learning_rate}, "
                       f"smoothing={calibration_smoothing}, min_samples={min_calibration_samples})")
    
    # ============================================
    # TIMESTAMP VALIDATION (WRITE PATHS ONLY)
    # ============================================
    
    def _validate_timestamp(self, timestamp_ns: int, context: str) -> bool:
        """Validate timestamp is positive int."""
        if not isinstance(timestamp_ns, int) or timestamp_ns <= 0:
            logger.warning(f"Invalid timestamp for {context}: {timestamp_ns}")
            return False
        return True
    
    def _check_channel_monotonicity(self, channel: str, new_ts_ns: int, per_venue_key: Optional[str] = None, commit: bool = True) -> bool:
        """
        Enforce per‑channel timestamp monotonicity.
        
        Args:
            channel: One of 'trade', 'candle', 'l2', 'venue', 'outcome', 'toxicity'
            new_ts_ns: New timestamp for this channel
            per_venue_key: If channel is 'venue', the specific venue identifier
            commit: If True, update the channel timestamp after validation.
                    If False, only check monotonicity without updating state.
        
        Returns:
            True if monotonicity holds (or no previous timestamp), False otherwise.
        """
        if channel == 'venue' and per_venue_key is not None:
            # Per‑venue monotonic enforcement
            last_ts = self._last_venue_ts_ns.get(per_venue_key)
            if last_ts is not None and new_ts_ns <= last_ts:
                logger.warning(f"Non‑monotonic venue update for {per_venue_key}: {new_ts_ns} <= {last_ts}")
                return False
            if commit:
                self._last_venue_ts_ns[per_venue_key] = new_ts_ns
                # Also update global venue channel timestamp
                last_global = self._last_channel_ts_ns['venue']
                self._last_channel_ts_ns['venue'] = max(last_global or 0, new_ts_ns)
            return True
        else:
            # Simple channel monotonic enforcement
            last_ts = self._last_channel_ts_ns[channel]
            if last_ts is not None and new_ts_ns <= last_ts:
                logger.warning(f"Non‑monotonic {channel} update: {new_ts_ns} <= {last_ts}")
                return False
            if commit:
                self._last_channel_ts_ns[channel] = new_ts_ns
            return True
    
    # ============================================
    # TRADE UPDATE (RICH MODE) — MUTATES STATE
    # ============================================
    
    def update_trade(self, size: float, price: float, side: int, timestamp_ns: int) -> None:
        """
        Update with new trade (preferred mode). MUTATES STATE.
        
        Args:
            size: Trade size in units
            price: Trade price (for reference, not used in toxicity)
            side: +1 for buy, -1 for sell
            timestamp_ns: Authoritative exchange timestamp
        
        Enforces monotonic timestamp ordering on the trade channel.
        """
        if not self._validate_timestamp(timestamp_ns, "trade_update"):
            return
        
        if not self._check_channel_monotonicity('trade', timestamp_ns):
            return
        
        self._has_trade_data = True
        
        # Store trade for burst detection
        self._trade_timestamps_ns.append(timestamp_ns)
        self._trade_sizes.append(size)
        self._trade_sides.append(side)
        
        # Add to current bucket
        self._current_volume += size
        self._current_trade_count += 1
        
        if side > 0:
            self._current_buy_volume += size
        else:
            self._current_sell_volume += size
        
        # Check if bucket is full
        if self._current_volume >= self.volume_bucket_units:
            self._finalize_bucket(timestamp_ns)
    
    def _finalize_bucket(self, timestamp_ns: int) -> None:
        """Finalize current VPIN proxy bucket."""
        if self._current_volume < EPS:
            return
        
        total_volume = self._current_volume
        buy_volume = self._current_buy_volume
        sell_volume = self._current_sell_volume
        
        # Volume imbalance (normalized to 0-1)
        imbalance = abs(buy_volume - sell_volume) / max(total_volume, EPS)
        
        # VPIN proxy = imbalance * (total_volume / bucket_units), capped at 1
        vpin = min(1.0, imbalance * (total_volume / self.volume_bucket_units))
        
        # Store bucket data
        self._bucket_volumes.append(total_volume)
        self._bucket_buy_volumes.append(buy_volume)
        self._bucket_sell_volumes.append(sell_volume)
        self._bucket_vpin.append(vpin)
        
        # Update volume history for anomaly detection
        self._volume_history.append(total_volume)
        
        # Reset bucket
        self._current_volume = 0.0
        self._current_buy_volume = 0.0
        self._current_sell_volume = 0.0
        self._current_trade_count = 0
    
    # ============================================
    # CANDLE UPDATE (PROXY MODE) — MUTATES STATE
    # ============================================
    
    def update_candle(self, volume: float, high: float, low: float, close: float, timestamp_ns: int) -> None:
        """
        Update with candle data (proxy mode when trade data unavailable). MUTATES STATE.
        
        Args:
            volume: Candle volume
            high: Candle high price
            low: Candle low price
            close: Candle close price
            timestamp_ns: Authoritative exchange timestamp
        
        Enforces monotonic timestamp ordering on the candle channel.
        """
        if not self._validate_timestamp(timestamp_ns, "candle_update"):
            return
        
        if not self._check_channel_monotonicity('candle', timestamp_ns):
            return
        
        if not self.enable_candle_proxy_mode:
            return
        
        # Store candle data
        self._candle_volumes.append(volume)
        candle_range = high - low
        self._candle_ranges.append(candle_range)
        self._candle_closes.append(close)
        
        # Update volume history
        self._volume_history.append(volume)
        
        # Create synthetic bucket for VPIN proxy using volume
        # This is a PROXY — not true trade-level VPIN
        if len(self._candle_volumes) >= 2:
            # Use recent volume as bucket
            recent_volumes = list(self._candle_volumes)[-self.lookback_buckets:]
            if recent_volumes:
                avg_volume = np.mean(recent_volumes)
                if avg_volume > EPS:
                    # Proxy imbalance from range expansion/contraction
                    # Not directional — neutral proxy
                    vpin = min(1.0, volume / avg_volume)
                    self._bucket_vpin.append(vpin)
                    self._bucket_volumes.append(volume)
                    # No directional info in proxy mode
                    self._bucket_buy_volumes.append(volume / 2)
                    self._bucket_sell_volumes.append(volume / 2)
    
    # ============================================
    # L2 ORDER BOOK UPDATE (OPTIONAL) — MUTATES STATE
    # ============================================
    
    def update_order_book(self, snapshot: L2Snapshot) -> None:
        """
        Update with L2 order book snapshot (optional). MUTATES STATE.
        
        When real L2 data is available, this improves toxicity estimation.
        If L2 data is absent, engine continues in proxy mode.
        
        Args:
            snapshot: L2Snapshot with bid/ask volumes and prices
        
        Enforces monotonic timestamp ordering on the L2 channel.
        """
        if not self._validate_timestamp(snapshot.timestamp_ns, "l2_update"):
            return
        
        if not self._check_channel_monotonicity('l2', snapshot.timestamp_ns):
            return
        
        self._has_l2_data = True
        self._l2_snapshots.append(snapshot)
        
        # Calculate imbalance
        total_volume = snapshot.bid_volume + snapshot.ask_volume
        if total_volume > EPS:
            imbalance = abs(snapshot.bid_volume - snapshot.ask_volume) / total_volume
        else:
            imbalance = 0.0
        
        # Directional bias from L2
        if snapshot.bid_volume > snapshot.ask_volume * 1.5:
            direction_score = 1.0  # buy pressure
        elif snapshot.ask_volume > snapshot.bid_volume * 1.5:
            direction_score = -1.0  # sell pressure
        else:
            direction_score = 0.0
        
        # Spread stress
        if snapshot.best_ask > snapshot.best_bid + EPS:
            spread_pct = (snapshot.best_ask - snapshot.best_bid) / snapshot.best_bid
            spread_stress = min(1.0, spread_pct / 0.01)  # 1% spread = 1.0
        else:
            spread_stress = 0.0
        
        # Combined L2 toxicity component
        l2_toxicity = imbalance * 0.5 + abs(direction_score) * 0.3 + spread_stress * 0.2
        self._l2_imbalance_history.append(l2_toxicity)
    
    # ============================================
    # CROSS-EXCHANGE VENUE UPDATE (OPTIONAL) — MUTATES STATE
    # ============================================
    
    def update_venue_snapshot(self, snapshot: VenueSnapshot) -> None:
        """
        Update with cross-venue snapshot (optional). MUTATES STATE.
        
        When multiple venue snapshots are available, this enables fragmentation
        detection. If only one venue is present, fragmentation signal remains neutral.
        
        Args:
            snapshot: VenueSnapshot with venue price/spread/volume data
        
        Enforces per‑venue monotonic timestamp ordering.
        """
        if not self._validate_timestamp(snapshot.timestamp_ns, "venue_update"):
            return
        
        # Per‑venue monotonic enforcement
        if not self._check_channel_monotonicity('venue', snapshot.timestamp_ns, per_venue_key=snapshot.venue):
            return
        
        # Initialize venue history if new
        if snapshot.venue not in self._venue_snapshots:
            self._venue_snapshots[snapshot.venue] = deque(maxlen=self.persistence_window)
        
        self._venue_snapshots[snapshot.venue].append(snapshot)
        
        # Check if we have multiple venues
        active_venues = [v for v, q in self._venue_snapshots.items() if len(q) > 0]
        if len(active_venues) >= 2:
            self._has_multi_venue = True
            self._calculate_fragmentation_score()
    
    def _calculate_fragmentation_score(self) -> float:
        """
        Calculate cross-venue fragmentation score.
        
        Uses:
        - Price dislocation across venues
        - Spread divergence
        - Volume/liquidity fragmentation
        - Unstable dominance rotation
        
        Returns score 0-1 where higher = more fragmented/toxic.
        """
        if not self._has_multi_venue:
            return 0.0
        
        venues = list(self._venue_snapshots.keys())
        if len(venues) < 2:
            return 0.0
        
        # Get most recent snapshot per venue
        recent_snapshots = []
        for venue in venues:
            if self._venue_snapshots[venue]:
                recent_snapshots.append(self._venue_snapshots[venue][-1])
        
        if len(recent_snapshots) < 2:
            return 0.0
        
        # Price dislocation: standard deviation of prices
        prices = [s.price for s in recent_snapshots if s.price > 0]
        if len(prices) >= 2:
            price_std = np.std(prices)
            price_mean = np.mean(prices)
            if price_mean > EPS:
                price_dislocation = min(1.0, price_std / price_mean * 10)  # 10% std = 1.0
            else:
                price_dislocation = 0.0
        else:
            price_dislocation = 0.0
        
        # Spread divergence: coefficient of variation of spreads
        spreads = [s.spread for s in recent_snapshots if s.spread > 0]
        if len(spreads) >= 2:
            spread_mean = np.mean(spreads)
            spread_std = np.std(spreads)
            if spread_mean > EPS:
                spread_divergence = min(1.0, spread_std / spread_mean)
            else:
                spread_divergence = 0.0
        else:
            spread_divergence = 0.0
        
        # Volume fragmentation: disparity in volume proxies
        volumes = [s.volume_proxy for s in recent_snapshots if s.volume_proxy > 0]
        if len(volumes) >= 2:
            volume_std = np.std(volumes)
            volume_mean = np.mean(volumes)
            if volume_mean > EPS:
                volume_frag = min(1.0, volume_std / volume_mean)
            else:
                volume_frag = 0.0
        else:
            volume_frag = 0.0
        
        # Combined fragmentation score
        fragmentation = (price_dislocation * 0.4 + spread_divergence * 0.3 + volume_frag * 0.3)
        
        self._fragmentation_history.append(fragmentation)
        
        return min(1.0, max(0.0, fragmentation))
    
    # ============================================
    # ADAPTIVE CALIBRATION — MUTATES STATE
    # ============================================
    
    def update_outcome(self, outcome: RealizedOutcome) -> None:
        """
        Update with realized outcome for adaptive calibration. MUTATES STATE.
        
        This enables deterministic online weight calibration based on prediction error.
        If no outcomes are provided, engine continues with baseline weights.
        
        IMPORTANT: Outcome channel timestamp is only committed after validating that
        this outcome corresponds to a prior prediction and maintains proper temporal
        ordering (outcome‑after‑prediction).
        
        Args:
            outcome: RealizedOutcome with realized regime/toxicity score
        
        Enforces monotonic timestamp ordering on the outcome channel and ensures
        outcome timestamps are not older than the prediction they are calibrating.
        """
        if not self.enable_calibration:
            return
        
        if not self._validate_timestamp(outcome.timestamp_ns, "calibration_outcome"):
            return
        
        # Step 1: Check calibration enabled (already checked by enable_calibration)
        
        # Step 2: Verify we have a prior prediction
        if self._last_predicted_score is None or self._last_prediction_timestamp_ns is None:
            logger.warning("Cannot update outcome without a prior prediction")
            return
        
        # Step 3: Verify outcome is not older than prediction (outcome‑after‑prediction ordering)
        if outcome.timestamp_ns < self._last_prediction_timestamp_ns:
            logger.warning(f"Outcome timestamp {outcome.timestamp_ns} older than prediction timestamp {self._last_prediction_timestamp_ns}")
            return
        
        # Step 4: Check outcome channel monotonicity WITHOUT committing yet
        if not self._check_channel_monotonicity('outcome', outcome.timestamp_ns, commit=False):
            return
        
        # Step 5: All checks passed — NOW commit the outcome channel timestamp
        self._last_channel_ts_ns['outcome'] = outcome.timestamp_ns
        
        # Step 6: Calculate prediction error
        predicted_score = self._last_predicted_score
        realized_score = outcome.realized_toxicity_score
        
        error = realized_score - predicted_score
        abs_error = abs(error)
        self._calibration_error_history.append(abs_error)
        
        # Update sample count
        self._calibration_samples += 1
        
        # Activate calibration only after minimum samples
        if self._calibration_samples >= self.min_calibration_samples:
            self._calibration_active = True
        
        # Perform weight update if calibration is active
        if self._calibration_active and self._last_component_scores:
            self._update_calibration_weights(error, realized_score)
        
        # Store for calibration statistics
        logger.debug(f"Calibration outcome for {self.symbol}: pred={predicted_score:.3f}, "
                    f"real={realized_score:.3f}, error={abs_error:.3f}")
    
    def _update_calibration_weights(self, error: float, realized_score: float) -> None:
        """
        Update calibrated weights using deterministic online gradient-style rule.
        
        Gradient: negative partial derivative of squared error with respect to weight.
        For squared error E = (realized - predicted)^2, with predicted = sum(w_i * c_i),
        gradient for weight i is -2 * error * component_i.
        
        Updates are bounded, smoothed, and renormalized.
        """
        if not self._last_component_scores:
            return
        
        # Get active components and their current weights
        active_components = [c for c in self._calibrated_weights.keys() 
                            if self._calibrated_weights[c] > 0]
        
        if not active_components:
            return
        
        # Calculate gradients
        gradients = {}
        for comp in active_components:
            component_score = self._last_component_scores.get(comp, 0.0)
            # Gradient for squared error with respect to weight
            # dE/dw = -2 * error * component_score
            grad = -2.0 * error * component_score
            gradients[comp] = grad
        
        # Apply gradient update with learning rate
        updated_weights = {}
        for comp in active_components:
            old_weight = self._calibrated_weights[comp]
            lr = self.calibration_learning_rate
            
            # Bound the gradient step
            grad_step = lr * gradients[comp]
            max_step = 0.1  # Prevent extreme changes
            grad_step = max(-max_step, min(max_step, grad_step))
            
            new_weight = old_weight + grad_step
            
            # Apply bounds
            new_weight = max(self.DEFAULT_MIN_WEIGHT, min(self.DEFAULT_MAX_WEIGHT, new_weight))
            updated_weights[comp] = new_weight
        
        # Renormalize active weights to sum to 1.0
        total = sum(updated_weights.values())
        if total > EPS:
            for comp in updated_weights:
                updated_weights[comp] = updated_weights[comp] / total
        
        # Apply smoothing with previous calibrated weights
        smoothing = self.calibration_smoothing
        for comp in active_components:
            if comp in updated_weights:
                self._calibrated_weights[comp] = (
                    smoothing * self._calibrated_weights[comp] +
                    (1.0 - smoothing) * updated_weights[comp]
                )
        
        # Ensure zero weights for inactive components
        all_comps = list(self._calibrated_weights.keys())
        for comp in all_comps:
            if comp not in active_components:
                self._calibrated_weights[comp] = 0.0
    
    # ============================================
    # TOXICITY COMPONENT CALCULATIONS (PURE)
    # ============================================
    
    def _calculate_vpin_score(self) -> float:
        """
        Calculate VPIN proxy score from completed buckets.
        
        Returns:
            Score 0-1, higher = more toxic directional pressure
        """
        if len(self._bucket_vpin) < self.lookback_buckets // 2:
            return 0.0
        
        recent_vpin = list(self._bucket_vpin)[-self.lookback_buckets:]
        if not recent_vpin:
            return 0.0
        
        avg_vpin = np.mean(recent_vpin)
        
        # Directional bias (if trade data available)
        if self._has_trade_data and len(self._bucket_buy_volumes) > 0 and len(self._bucket_sell_volumes) > 0:
            recent_buy = list(self._bucket_buy_volumes)[-self.lookback_buckets:]
            recent_sell = list(self._bucket_sell_volumes)[-self.lookback_buckets:]
            if recent_buy and recent_sell:
                total_buy = sum(recent_buy)
                total_sell = sum(recent_sell)
                if total_buy + total_sell > EPS:
                    direction_imbalance = abs(total_buy - total_sell) / (total_buy + total_sell)
                    # Boost VPIN if directional imbalance is strong
                    avg_vpin = avg_vpin * (0.7 + 0.3 * direction_imbalance)
        
        return min(1.0, avg_vpin)
    
    def _calculate_burst_pressure(self, current_ts_ns: int) -> float:
        """
        Calculate trade burst / clustering pressure.
        
        Higher burst = more concentrated/aggressive flow = more toxic.
        Proxy mode uses volume variance instead of trade clustering.
        """
        if self._has_trade_data and len(self._trade_timestamps_ns) >= 10:
            # Use trade timing for burst detection
            timestamps = list(self._trade_timestamps_ns)[-50:]
            if len(timestamps) >= 5:
                # Calculate inter-arrival times
                inter_arrival_ns = []
                for i in range(1, len(timestamps)):
                    dt = timestamps[i] - timestamps[i-1]
                    if dt > 0:
                        inter_arrival_ns.append(dt)
                
                if inter_arrival_ns:
                    mean_ia = np.mean(inter_arrival_ns)
                    std_ia = np.std(inter_arrival_ns)
                    if mean_ia > EPS:
                        # High variance in inter-arrival = clustering
                        cv = min(2.0, std_ia / mean_ia)  # Coefficient of variation
                        burst = min(1.0, cv / 1.5)
                        return burst
        
        # Proxy mode: use volume variance from candles
        if len(self._candle_volumes) >= 10:
            volumes = list(self._candle_volumes)[-20:]
            if volumes:
                mean_vol = np.mean(volumes)
                std_vol = np.std(volumes)
                if mean_vol > EPS:
                    cv = min(2.0, std_vol / mean_vol)
                    return min(1.0, cv / 1.5)
        
        return 0.0
    
    def _calculate_instability_score(self) -> float:
        """
        Calculate market instability / fragility score.
        
        Uses price range and range variance as proxy for quote fragility.
        """
        if len(self._candle_ranges) < 5:
            return 0.0
        
        recent_ranges = list(self._candle_ranges)[-10:]
        if not recent_ranges:
            return 0.0
        
        mean_range = np.mean(recent_ranges)
        if mean_range < EPS:
            return 0.0
        
        # Range expansion indicates instability
        max_range = max(recent_ranges)
        range_ratio = min(2.0, max_range / mean_range)
        instability = (range_ratio - 1.0) / 1.0  # 0 at stable, 1 at 2x expansion
        
        # Add range variance component
        std_range = np.std(recent_ranges)
        cv_range = min(1.5, std_range / mean_range) if mean_range > EPS else 0
        instability = instability * 0.6 + (cv_range / 1.5) * 0.4
        
        return min(1.0, max(0.0, instability))
    
    def _calculate_volume_anomaly_score(self) -> float:
        """
        Calculate volume anomaly score.
        
        Returns z-score normalized to 0-1, higher = more anomalous.
        """
        if len(self._volume_history) < 10:
            return 0.0
        
        volumes = list(self._volume_history)
        if len(volumes) < 5:
            return 0.0
        
        mean_vol = np.mean(volumes)
        std_vol = np.std(volumes)
        
        if std_vol < EPS:
            return 0.0
        
        current_vol = volumes[-1]
        z_score = (current_vol - mean_vol) / std_vol
        
        # Normalize: z=0 -> 0, z=2 -> 0.5, z=4 -> 0.75, asymptotically 1
        anomaly = 1.0 - (1.0 / (1.0 + z_score / 2.0))
        
        return min(1.0, max(0.0, anomaly))
    
    def _calculate_l2_toxicity(self) -> float:
        """
        Calculate L2-based toxicity component.
        
        Returns score 0-1, higher = more toxic based on order book.
        Returns 0.0 if no L2 data available (honest degradation).
        """
        if not self._has_l2_data or len(self._l2_imbalance_history) < 2:
            return 0.0
        
        recent_imbalance = list(self._l2_imbalance_history)[-self.persistence_window:]
        if not recent_imbalance:
            return 0.0
        
        # Average L2 toxicity over recent window
        avg_l2_toxicity = np.mean(recent_imbalance)
        
        # Boost if L2 imbalance is persistent
        if len(recent_imbalance) >= 3:
            increasing = recent_imbalance[-1] > recent_imbalance[-2] > recent_imbalance[-3]
            if increasing:
                avg_l2_toxicity = min(1.0, avg_l2_toxicity * 1.2)
        
        return min(1.0, avg_l2_toxicity)
    
    def _calculate_fragmentation_toxicity(self) -> float:
        """
        Calculate cross-venue fragmentation toxicity component.
        
        Returns score 0-1, higher = more toxic fragmentation.
        Returns 0.0 if no multi-venue data available (honest degradation).
        """
        if not self._has_multi_venue or len(self._fragmentation_history) < 2:
            return 0.0
        
        recent_frag = list(self._fragmentation_history)[-self.persistence_window:]
        if not recent_frag:
            return 0.0
        
        # Average fragmentation over recent window
        avg_fragmentation = np.mean(recent_frag)
        
        # Boost if fragmentation is increasing
        if len(recent_frag) >= 3:
            if recent_frag[-1] > recent_frag[-2] > recent_frag[-3]:
                avg_fragmentation = min(1.0, avg_fragmentation * 1.15)
        
        return min(1.0, avg_fragmentation)
    
    def _get_dynamic_weights(self) -> Dict[str, float]:
        """
        Get dynamic weights based on available data and calibration state.
        
        Uses calibrated weights if calibration is active, otherwise base weights.
        When optional components (L2, fragmentation) are unavailable,
        their weight is redistributed to available components.
        """
        # Choose weight source
        if self._calibration_active and self.enable_calibration:
            weights = self._calibrated_weights.copy()
        else:
            weights = self._base_weights.copy()
        
        # Determine which components are active
        active_components = ['vpin', 'burst', 'instability', 'volume_anomaly']
        if self._has_l2_data:
            active_components.append('l2')
        if self._has_multi_venue:
            active_components.append('fragmentation')
        
        # Calculate total active weight
        total_weight = sum(weights[c] for c in active_components)
        
        # Normalize weights
        if total_weight > 0:
            for c in active_components:
                weights[c] = weights[c] / total_weight
            for c in set(weights.keys()) - set(active_components):
                weights[c] = 0.0
        
        return weights
    
    def _calculate_persistence(self, current_toxicity: float, current_ts_ns: int) -> float:
        """
        Calculate toxicity persistence score.
        
        Higher persistence = toxicity has been sustained = more dangerous.
        """
        # Add current toxicity to history
        self._toxicity_history.append(current_toxicity)
        
        if len(self._toxicity_history) < self.persistence_window:
            return 0.0
        
        recent = list(self._toxicity_history)[-self.persistence_window:]
        if not recent:
            return 0.0
        
        # Persistence = average toxicity over window
        persistence = np.mean(recent)
        
        # Bonus if toxicity has been increasing
        if len(recent) >= 3:
            if recent[-1] > recent[-2] > recent[-3]:
                persistence = min(1.0, persistence * 1.2)
        
        # Track toxic start for decay
        if current_toxicity >= self.toxicity_threshold and self._toxic_start_ns is None:
            self._toxic_start_ns = current_ts_ns
        elif current_toxicity < self.toxicity_threshold * 0.5:
            self._toxic_start_ns = None
        
        return min(1.0, persistence)
    
    def _calculate_direction_bias(self) -> str:
        """
        Determine directional bias of toxicity.
        
        Returns "buy", "sell", or "neutral".
        """
        if self._has_trade_data and len(self._bucket_buy_volumes) > 0 and len(self._bucket_sell_volumes) > 0:
            recent_buy = list(self._bucket_buy_volumes)[-10:]
            recent_sell = list(self._bucket_sell_volumes)[-10:]
            
            if recent_buy and recent_sell:
                total_buy = sum(recent_buy)
                total_sell = sum(recent_sell)
                
                if total_buy + total_sell > EPS:
                    buy_ratio = total_buy / (total_buy + total_sell)
                    
                    if buy_ratio > 0.6:
                        return "buy"
                    elif buy_ratio < 0.4:
                        return "sell"
        
        # L2 directional bias if available
        if self._has_l2_data and len(self._l2_snapshots) > 0:
            recent_l2 = list(self._l2_snapshots)[-5:]
            if recent_l2:
                bid_sum = sum(s.bid_volume for s in recent_l2)
                ask_sum = sum(s.ask_volume for s in recent_l2)
                if bid_sum + ask_sum > EPS:
                    buy_ratio = bid_sum / (bid_sum + ask_sum)
                    if buy_ratio > 0.6:
                        return "buy"
                    elif buy_ratio < 0.4:
                        return "sell"
        
        return "neutral"
    
    # ============================================
    # MAIN TOXICITY UPDATE (MUTATES STATE)
    # ============================================
    
    def update_toxicity(self, current_ts_ns: int) -> ToxicityAlert:
        """
        Update toxicity state and return current alert. MUTATES STATE.
        
        This is the primary state-advancing method. Call this periodically
        to update toxicity calculations based on accumulated data.
        
        Args:
            current_ts_ns: Current authoritative timestamp
            
        Returns:
            ToxicityAlert with current toxicity state
        
        Enforces monotonic timestamp ordering on the toxicity channel.
        """
        if not self._validate_timestamp(current_ts_ns, "update_toxicity"):
            return ToxicityAlert(
                toxicity_score=0.0,
                regime=ToxicityRegime.NORMAL,
                direction_bias="neutral",
                vpin_proxy=0.0,
                burst_pressure=0.0,
                instability_score=0.0,
                volume_anomaly=0.0,
                persistence=0.0,
                confidence=0.0,
                timestamp_ns=current_ts_ns,
                reason="invalid_timestamp"
            )
        
        # Enforce monotonic ordering on toxicity channel
        if not self._check_channel_monotonicity('toxicity', current_ts_ns):
            # If monotonicity violation, return last alert (or neutral)
            if self._last_alert is not None:
                return self._last_alert
            else:
                return ToxicityAlert(
                    toxicity_score=0.0,
                    regime=ToxicityRegime.NORMAL,
                    direction_bias="neutral",
                    vpin_proxy=0.0,
                    burst_pressure=0.0,
                    instability_score=0.0,
                    volume_anomaly=0.0,
                    persistence=0.0,
                    confidence=0.0,
                    timestamp_ns=current_ts_ns,
                    reason="monotonicity_violation"
                )
        
        # Calculate component scores
        vpin_score = self._calculate_vpin_score()
        burst_pressure = self._calculate_burst_pressure(current_ts_ns)
        instability_score = self._calculate_instability_score()
        volume_anomaly = self._calculate_volume_anomaly_score()
        l2_toxicity = self._calculate_l2_toxicity()
        fragmentation_toxicity = self._calculate_fragmentation_toxicity()
        
        # Store component scores for calibration
        self._last_component_scores = {
            'vpin': vpin_score,
            'burst': burst_pressure,
            'instability': instability_score,
            'volume_anomaly': volume_anomaly,
            'l2': l2_toxicity,
            'fragmentation': fragmentation_toxicity
        }
        
        # Get dynamic weights based on available data and calibration
        weights = self._get_dynamic_weights()
        
        # Weighted composite toxicity score
        raw_toxicity = (
            vpin_score * weights['vpin'] +
            burst_pressure * weights['burst'] +
            instability_score * weights['instability'] +
            volume_anomaly * weights['volume_anomaly'] +
            l2_toxicity * weights['l2'] +
            fragmentation_toxicity * weights['fragmentation']
        )
        
        # Apply persistence boost
        persistence = self._calculate_persistence(raw_toxicity, current_ts_ns)
        toxicity_score = raw_toxicity * (0.7 + 0.3 * persistence)
        toxicity_score = min(1.0, max(0.0, toxicity_score))
        
        # Apply decay if toxicity was high and now decreasing
        if self._toxic_start_ns is not None and toxicity_score < self.toxicity_threshold * 0.6:
            decay_age_ns = current_ts_ns - self._toxic_start_ns
            if decay_age_ns > self.toxic_decay_ns:
                toxicity_score = toxicity_score * 0.8
        
        # Determine regime
        if toxicity_score >= self.toxicity_threshold * 1.2:
            regime = ToxicityRegime.EXTREME
        elif toxicity_score >= self.toxicity_threshold:
            regime = ToxicityRegime.TOXIC
        elif toxicity_score >= self.toxicity_threshold * 0.5:
            regime = ToxicityRegime.ELEVATED
        else:
            regime = ToxicityRegime.NORMAL
        
        # Direction bias
        direction_bias = self._calculate_direction_bias()
        
        # Confidence based on data availability and component agreement
        data_confidence = 0.7 if self._has_trade_data else 0.4
        if self._has_l2_data:
            data_confidence += 0.15
        if self._has_multi_venue:
            data_confidence += 0.1
        if len(self._bucket_vpin) >= self.lookback_buckets // 2:
            data_confidence += 0.2
        
        # Component agreement: if all core components point in same direction
        component_values = [vpin_score, burst_pressure, instability_score, volume_anomaly]
        high_components = sum(1 for v in component_values if v > 0.5)
        agreement = high_components / len(component_values) if component_values else 0.5
        
        confidence = data_confidence * 0.6 + agreement * 0.4
        confidence = min(1.0, max(0.0, confidence))
        
        # Build reason
        reasons = []
        if toxicity_score >= self.toxicity_threshold:
            reasons.append(f"toxicity={toxicity_score:.2f}")
        if vpin_score > 0.7:
            reasons.append(f"vpin={vpin_score:.2f}")
        if burst_pressure > 0.7:
            reasons.append(f"burst={burst_pressure:.2f}")
        if instability_score > 0.7:
            reasons.append(f"instability={instability_score:.2f}")
        if volume_anomaly > 0.7:
            reasons.append(f"vol_anomaly={volume_anomaly:.2f}")
        if l2_toxicity > 0.7:
            reasons.append(f"l2_toxicity={l2_toxicity:.2f}")
        if fragmentation_toxicity > 0.7:
            reasons.append(f"fragmentation={fragmentation_toxicity:.2f}")
        
        alert = ToxicityAlert(
            toxicity_score=toxicity_score,
            regime=regime,
            direction_bias=direction_bias,
            vpin_proxy=vpin_score,
            burst_pressure=burst_pressure,
            instability_score=instability_score,
            volume_anomaly=volume_anomaly,
            persistence=persistence,
            confidence=confidence,
            timestamp_ns=current_ts_ns,
            reason=" | ".join(reasons) if reasons else "normal"
        )
        
        self._last_alert = alert
        self._last_predicted_score = toxicity_score
        self._last_predicted_regime = regime
        self._last_prediction_timestamp_ns = current_ts_ns
        
        if regime in (ToxicityRegime.TOXIC, ToxicityRegime.EXTREME):
            logger.debug(f"TOXICITY [{self.symbol}]: {alert.reason} (regime={regime.name})")
        
        return alert
    
    # ============================================
    # READ-ONLY QUERY METHODS (DO NOT MUTATE STATE)
    # ============================================
    
    def get_last_alert(self) -> Optional[ToxicityAlert]:
        """
        Return last computed toxicity alert (read-only).
        
        Returns None if update_toxicity() has never been called.
        """
        return self._last_alert
    
    def is_toxic(self) -> bool:
        """
        Quick check if market is currently toxic (read-only).
        
        Returns False if no alert has been computed yet.
        """
        if self._last_alert is None:
            return False
        return self._last_alert.regime in (ToxicityRegime.TOXIC, ToxicityRegime.EXTREME)
    
    def get_suppression_factor(self) -> float:
        """
        Get suppression factor for strategy aggression (read-only).
        
        Returns 0-1 where:
        - 1.0 = no suppression (normal conditions)
        - 0.0 = full suppression (extreme toxicity)
        
        Returns 1.0 if no alert has been computed yet.
        """
        if self._last_alert is None:
            return 1.0
        
        if self._last_alert.regime == ToxicityRegime.EXTREME:
            return 0.0
        elif self._last_alert.regime == ToxicityRegime.TOXIC:
            return 0.5
        elif self._last_alert.regime == ToxicityRegime.ELEVATED:
            return 0.8
        else:
            return 1.0
    
    def get_calibration_weights(self) -> Dict[str, float]:
        """
        Get current calibrated weights (read-only).
        
        Returns base weights if calibration not active.
        """
        if self._calibration_active and self.enable_calibration:
            return self._calibrated_weights.copy()
        else:
            return self._base_weights.copy()
    
    def get_calibration_stats(self) -> Dict[str, Any]:
        """
        Get calibration statistics (read-only).
        
        Returns:
            Dictionary with calibration state information
        """
        avg_error = np.mean(self._calibration_error_history) if self._calibration_error_history else 0.0
        
        return {
            "calibration_enabled": self.enable_calibration,
            "calibration_active": self._calibration_active,
            "calibration_samples": self._calibration_samples,
            "min_samples_required": self.min_calibration_samples,
            "learning_rate": self.calibration_learning_rate,
            "smoothing": self.calibration_smoothing,
            "avg_prediction_error": avg_error,
            "current_weights": self.get_calibration_weights(),
            "base_weights": self._base_weights.copy()
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get engine statistics (read-only, does not advance state).
        
        Returns statistics based on last computed alert if available,
        otherwise returns neutral values.
        """
        if self._last_alert is None:
            return {
                "symbol": self.symbol,
                "toxicity_score": 0.0,
                "regime": "UNKNOWN",
                "direction_bias": "neutral",
                "vpin_proxy": 0.0,
                "burst_pressure": 0.0,
                "instability_score": 0.0,
                "volume_anomaly": 0.0,
                "persistence": 0.0,
                "confidence": 0.0,
                "has_trade_data": self._has_trade_data,
                "has_l2_data": self._has_l2_data,
                "has_multi_venue": self._has_multi_venue,
                "buckets_completed": len(self._bucket_vpin),
                "history_size": len(self._volume_history),
                "calibration_active": self._calibration_active,
                "calibration_samples": self._calibration_samples
            }
        
        return {
            "symbol": self.symbol,
            "toxicity_score": self._last_alert.toxicity_score,
            "regime": self._last_alert.regime.name,
            "direction_bias": self._last_alert.direction_bias,
            "vpin_proxy": self._last_alert.vpin_proxy,
            "burst_pressure": self._last_alert.burst_pressure,
            "instability_score": self._last_alert.instability_score,
            "volume_anomaly": self._last_alert.volume_anomaly,
            "persistence": self._last_alert.persistence,
            "confidence": self._last_alert.confidence,
            "has_trade_data": self._has_trade_data,
            "has_l2_data": self._has_l2_data,
            "has_multi_venue": self._has_multi_venue,
            "buckets_completed": len(self._bucket_vpin),
            "history_size": len(self._volume_history),
            "calibration_active": self._calibration_active,
            "calibration_samples": self._calibration_samples,
            "current_calibration_weights": self.get_calibration_weights()
        }
    
    # ============================================
    # DETERMINISTIC SERIALIZATION
    # ============================================
    
    def serialize_state(self) -> bytes:
        """
        Serialize toxicity engine state to deterministic binary format.
        
        Schema version 3 (per‑channel monotonic timestamps + full history continuity):
        - version: uint8 (3)
        - symbol_len: uint8
        - symbol: bytes (max 255)
        - toxic_start_ns: uint64 (0 = None sentinel)
        - has_trade_data: uint8 (0/1)
        - has_l2_data: uint8 (0/1)
        - has_multi_venue: uint8 (0/1)
        - current_volume: float64
        - current_buy_volume: float64
        - current_sell_volume: float64
        - current_trade_count: uint32
        - last_toxicity_score: float64
        - last_regime: uint8
        - last_timestamp_ns: uint64
        - calibration_active: uint8
        - calibration_samples: uint32
        - calibrated_weights: 6 * float64 (vpin, burst, instability, volume_anomaly, l2, fragmentation)
        - per‑channel monotonic timestamps: 6 * uint64 (trade, candle, l2, venue, outcome, toxicity)
        - per‑venue monotonic timestamp count: uint16
        - per‑venue timestamps: (venue_len: uint8, venue: bytes, timestamp: uint64)[] (max venues = 5)
        
        Bounded history arrays (recent window only):
        - bucket_vpin_count: uint16
        - bucket_vpin_values: float64[] (max 100)
        - bucket_volumes_count: uint16
        - bucket_volumes_values: float64[] (max 100)
        - volume_history_count: uint16
        - volume_history_values: float64[] (max 100)
        - toxicity_history_count: uint16
        - toxicity_history_values: float64[] (max persistence_window)
        - l2_imbalance_history_count: uint16
        - l2_imbalance_history_values: float64[] (max persistence_window)
        - fragmentation_history_count: uint16
        - fragmentation_history_values: float64[] (max persistence_window)
        - calibration_error_history_count: uint16
        - calibration_error_history_values: float64[] (max persistence_window)
        """
        # Prepare symbol bytes
        symbol_bytes = self.symbol.encode('utf-8')
        symbol_len = len(symbol_bytes)
        
        # Prepare bounded history arrays (last 100 entries max, or persistence_window)
        bucket_vpin_list = list(self._bucket_vpin)[-100:]
        bucket_volumes_list = list(self._bucket_volumes)[-100:]
        volume_history_list = list(self._volume_history)[-100:]
        toxicity_history_list = list(self._toxicity_history)[-self.persistence_window:]
        l2_imbalance_history_list = list(self._l2_imbalance_history)[-self.persistence_window:]
        fragmentation_history_list = list(self._fragmentation_history)[-self.persistence_window:]
        calibration_error_history_list = list(self._calibration_error_history)[-self.persistence_window:]
        
        # Calibrated weights in fixed order
        calibrated_weights_list = [
            self._calibrated_weights.get('vpin', 0.0),
            self._calibrated_weights.get('burst', 0.0),
            self._calibrated_weights.get('instability', 0.0),
            self._calibrated_weights.get('volume_anomaly', 0.0),
            self._calibrated_weights.get('l2', 0.0),
            self._calibrated_weights.get('fragmentation', 0.0)
        ]
        
        # Per‑channel monotonic timestamps (order: trade, candle, l2, venue, outcome, toxicity)
        channel_timestamps = [
            self._last_channel_ts_ns['trade'] or 0,
            self._last_channel_ts_ns['candle'] or 0,
            self._last_channel_ts_ns['l2'] or 0,
            self._last_channel_ts_ns['venue'] or 0,
            self._last_channel_ts_ns['outcome'] or 0,
            self._last_channel_ts_ns['toxicity'] or 0,
        ]
        
        # Per‑venue monotonic timestamps
        venue_timestamp_items = []
        for venue, ts in self._last_venue_ts_ns.items():
            if ts is not None:
                venue_bytes = venue.encode('utf-8')
                if len(venue_bytes) > 255:
                    continue  # skip unreasonably long venue names
                venue_timestamp_items.append((len(venue_bytes), venue_bytes, ts))
                if len(venue_timestamp_items) >= self.max_venues:
                    break
        
        venue_count = len(venue_timestamp_items)
        
        # Build struct format for header
        fmt_header = f'>B B {symbol_len}s Q B B B d d d I d B Q B I 6d 6Q'
        header_data = (
            self.SERIALIZATION_VERSION,
            symbol_len,
            symbol_bytes,
            self._toxic_start_ns or 0,
            1 if self._has_trade_data else 0,
            1 if self._has_l2_data else 0,
            1 if self._has_multi_venue else 0,
            self._current_volume,
            self._current_buy_volume,
            self._current_sell_volume,
            self._current_trade_count,
            self._last_alert.toxicity_score if self._last_alert else 0.0,
            self._last_alert.regime.value if self._last_alert else 0,
            self._last_alert.timestamp_ns if self._last_alert else 0,
            1 if self._calibration_active else 0,
            self._calibration_samples,
            *calibrated_weights_list,
            *channel_timestamps
        )
        
        header_bytes = struct.pack(fmt_header, *header_data)
        
        # Pack per‑venue timestamps
        venue_header = struct.pack('>H', venue_count)
        venue_bytes = b''
        for venue_len, venue_bs, ts in venue_timestamp_items:
            venue_bytes += struct.pack(f'>B {venue_len}s Q', venue_len, venue_bs, ts)
        
        # Pack bucket_vpin array
        vpin_count = len(bucket_vpin_list)
        vpin_fmt = f'>{vpin_count}d' if vpin_count > 0 else '>'
        vpin_bytes = struct.pack('>H', vpin_count) + (struct.pack(vpin_fmt, *bucket_vpin_list) if vpin_count > 0 else b'')
        
        # Pack bucket_volumes array
        vol_count = len(bucket_volumes_list)
        vol_fmt = f'>{vol_count}d' if vol_count > 0 else '>'
        vol_bytes = struct.pack('>H', vol_count) + (struct.pack(vol_fmt, *bucket_volumes_list) if vol_count > 0 else b'')
        
        # Pack volume_history array
        hist_count = len(volume_history_list)
        hist_fmt = f'>{hist_count}d' if hist_count > 0 else '>'
        hist_bytes = struct.pack('>H', hist_count) + (struct.pack(hist_fmt, *volume_history_list) if hist_count > 0 else b'')
        
        # Pack toxicity_history array
        tox_count = len(toxicity_history_list)
        tox_fmt = f'>{tox_count}d' if tox_count > 0 else '>'
        tox_bytes = struct.pack('>H', tox_count) + (struct.pack(tox_fmt, *toxicity_history_list) if tox_count > 0 else b'')
        
        # Pack L2 imbalance history array
        l2_count = len(l2_imbalance_history_list)
        l2_fmt = f'>{l2_count}d' if l2_count > 0 else '>'
        l2_bytes = struct.pack('>H', l2_count) + (struct.pack(l2_fmt, *l2_imbalance_history_list) if l2_count > 0 else b'')
        
        # Pack fragmentation history array
        frag_count = len(fragmentation_history_list)
        frag_fmt = f'>{frag_count}d' if frag_count > 0 else '>'
        frag_bytes = struct.pack('>H', frag_count) + (struct.pack(frag_fmt, *fragmentation_history_list) if frag_count > 0 else b'')
        
        # Pack calibration error history array
        err_count = len(calibration_error_history_list)
        err_fmt = f'>{err_count}d' if err_count > 0 else '>'
        err_bytes = struct.pack('>H', err_count) + (struct.pack(err_fmt, *calibration_error_history_list) if err_count > 0 else b'')
        
        return (header_bytes + venue_header + venue_bytes + vpin_bytes + vol_bytes +
                hist_bytes + tox_bytes + l2_bytes + frag_bytes + err_bytes)
    
    def deserialize_state(self, data: bytes) -> None:
        """
        Restore toxicity engine state from deterministic binary format.
        
        Args:
            data: Binary data from serialize_state()
        """
        if len(data) < 10:
            logger.error(f"Serialized data too short: {len(data)}")
            return
        
        # Read version
        version = data[0]
        if version != self.SERIALIZATION_VERSION:
            logger.warning(f"Serialization version mismatch: {version} != {self.SERIALIZATION_VERSION}")
            return
        
        symbol_len = data[1]
        fmt_header = f'>B B {symbol_len}s Q B B B d d d I d B Q B I 6d 6Q'
        header_size = struct.calcsize(fmt_header)
        
        if len(data) < header_size:
            logger.error(f"Data too short for header: {len(data)} < {header_size}")
            return
        
        header_bytes = data[:header_size]
        unpacked = struct.unpack(fmt_header, header_bytes)
        
        # Skip version and symbol_len (already read)
        idx = 2
        read_symbol = unpacked[idx].decode('utf-8'); idx += 1
        if read_symbol != self.symbol:
            logger.warning(f"Symbol mismatch: {read_symbol} != {self.symbol}")
        
        self._toxic_start_ns = unpacked[idx] if unpacked[idx] != 0 else None; idx += 1
        self._has_trade_data = bool(unpacked[idx]); idx += 1
        self._has_l2_data = bool(unpacked[idx]); idx += 1
        self._has_multi_venue = bool(unpacked[idx]); idx += 1
        self._current_volume = unpacked[idx]; idx += 1
        self._current_buy_volume = unpacked[idx]; idx += 1
        self._current_sell_volume = unpacked[idx]; idx += 1
        self._current_trade_count = int(unpacked[idx]); idx += 1
        last_score = unpacked[idx]; idx += 1
        last_regime_val = unpacked[idx]; idx += 1
        last_ts = unpacked[idx]; idx += 1
        self._calibration_active = bool(unpacked[idx]); idx += 1
        self._calibration_samples = unpacked[idx]; idx += 1
        
        # Restore calibrated weights
        self._calibrated_weights['vpin'] = unpacked[idx]; idx += 1
        self._calibrated_weights['burst'] = unpacked[idx]; idx += 1
        self._calibrated_weights['instability'] = unpacked[idx]; idx += 1
        self._calibrated_weights['volume_anomaly'] = unpacked[idx]; idx += 1
        self._calibrated_weights['l2'] = unpacked[idx]; idx += 1
        self._calibrated_weights['fragmentation'] = unpacked[idx]; idx += 1
        
        # Restore per‑channel monotonic timestamps
        self._last_channel_ts_ns['trade'] = unpacked[idx] if unpacked[idx] != 0 else None; idx += 1
        self._last_channel_ts_ns['candle'] = unpacked[idx] if unpacked[idx] != 0 else None; idx += 1
        self._last_channel_ts_ns['l2'] = unpacked[idx] if unpacked[idx] != 0 else None; idx += 1
        self._last_channel_ts_ns['venue'] = unpacked[idx] if unpacked[idx] != 0 else None; idx += 1
        self._last_channel_ts_ns['outcome'] = unpacked[idx] if unpacked[idx] != 0 else None; idx += 1
        self._last_channel_ts_ns['toxicity'] = unpacked[idx] if unpacked[idx] != 0 else None; idx += 1
        
        # Restore last alert if valid
        if last_ts != 0:
            self._last_alert = ToxicityAlert(
                toxicity_score=last_score,
                regime=ToxicityRegime(last_regime_val),
                direction_bias="neutral",
                vpin_proxy=0.0,
                burst_pressure=0.0,
                instability_score=0.0,
                volume_anomaly=0.0,
                persistence=0.0,
                confidence=0.0,
                timestamp_ns=last_ts,
                reason="deserialized"
            )
            self._last_predicted_score = last_score
            self._last_predicted_regime = ToxicityRegime(last_regime_val)
            self._last_prediction_timestamp_ns = last_ts
        else:
            self._last_alert = None
        
        # Parse per‑venue timestamps
        pos = header_size
        venue_count = struct.unpack_from('>H', data, pos)[0]
        pos += 2
        self._last_venue_ts_ns.clear()
        for _ in range(venue_count):
            venue_len = struct.unpack_from('>B', data, pos)[0]
            pos += 1
            venue_bytes = struct.unpack_from(f'{venue_len}s', data, pos)[0]
            pos += venue_len
            venue = venue_bytes.decode('utf-8')
            ts = struct.unpack_from('>Q', data, pos)[0]
            pos += 8
            self._last_venue_ts_ns[venue] = ts if ts != 0 else None
        
        # Parse arrays
        # bucket_vpin
        vpin_count = struct.unpack_from('>H', data, pos)[0]
        pos += 2
        if vpin_count > 0:
            vpin_fmt = f'>{vpin_count}d'
            vpin_values = struct.unpack_from(vpin_fmt, data, pos)
            self._bucket_vpin.clear()
            self._bucket_vpin.extend(vpin_values)
            pos += vpin_count * 8
        
        # bucket_volumes
        vol_count = struct.unpack_from('>H', data, pos)[0]
        pos += 2
        if vol_count > 0:
            vol_fmt = f'>{vol_count}d'
            vol_values = struct.unpack_from(vol_fmt, data, pos)
            self._bucket_volumes.clear()
            self._bucket_volumes.extend(vol_values)
            pos += vol_count * 8
        
        # volume_history
        hist_count = struct.unpack_from('>H', data, pos)[0]
        pos += 2
        if hist_count > 0:
            hist_fmt = f'>{hist_count}d'
            hist_values = struct.unpack_from(hist_fmt, data, pos)
            self._volume_history.clear()
            self._volume_history.extend(hist_values)
            pos += hist_count * 8
        
        # toxicity_history
        tox_count = struct.unpack_from('>H', data, pos)[0]
        pos += 2
        if tox_count > 0:
            tox_fmt = f'>{tox_count}d'
            tox_values = struct.unpack_from(tox_fmt, data, pos)
            self._toxicity_history.clear()
            self._toxicity_history.extend(tox_values)
            pos += tox_count * 8
        
        # l2_imbalance_history
        l2_count = struct.unpack_from('>H', data, pos)[0]
        pos += 2
        if l2_count > 0:
            l2_fmt = f'>{l2_count}d'
            l2_values = struct.unpack_from(l2_fmt, data, pos)
            self._l2_imbalance_history.clear()
            self._l2_imbalance_history.extend(l2_values)
            pos += l2_count * 8
        
        # fragmentation_history
        frag_count = struct.unpack_from('>H', data, pos)[0]
        pos += 2
        if frag_count > 0:
            frag_fmt = f'>{frag_count}d'
            frag_values = struct.unpack_from(frag_fmt, data, pos)
            self._fragmentation_history.clear()
            self._fragmentation_history.extend(frag_values)
            pos += frag_count * 8
        
        # calibration_error_history
        err_count = struct.unpack_from('>H', data, pos)[0]
        pos += 2
        if err_count > 0:
            err_fmt = f'>{err_count}d'
            err_values = struct.unpack_from(err_fmt, data, pos)
            self._calibration_error_history.clear()
            self._calibration_error_history.extend(err_values)
        
        logger.info(f"ToxicityEngine state deserialized for {self.symbol}")
    
    def compute_state_hash(self) -> bytes:
        """
        Compute deterministic SHA256 hash from serialized state bytes.
        
        Returns:
            32-byte SHA256 hash
        """
        serialized = self.serialize_state()
        return hashlib.sha256(serialized).digest()
    
    def state_hash_hex(self) -> str:
        """Return state hash as hex string for integrity verification."""
        return self.compute_state_hash().hex()
    
    # ============================================
    # RESET
    # ============================================
    
    def reset(self) -> None:
        """Reset all state."""
        self._current_volume = 0.0
        self._current_buy_volume = 0.0
        self._current_sell_volume = 0.0
        self._current_trade_count = 0
        
        self._bucket_volumes.clear()
        self._bucket_buy_volumes.clear()
        self._bucket_sell_volumes.clear()
        self._bucket_vpin.clear()
        
        self._trade_timestamps_ns.clear()
        self._trade_sizes.clear()
        self._trade_sides.clear()
        
        self._candle_volumes.clear()
        self._candle_ranges.clear()
        self._candle_closes.clear()
        
        self._l2_snapshots.clear()
        self._l2_imbalance_history.clear()
        
        self._venue_snapshots.clear()
        self._fragmentation_history.clear()
        
        self._toxicity_history.clear()
        self._volume_history.clear()
        
        self._last_alert = None
        self._toxic_start_ns = None
        self._last_predicted_score = None
        self._last_predicted_regime = None
        self._last_prediction_timestamp_ns = None
        self._last_component_scores.clear()
        self._calibration_error_history.clear()
        
        self._has_trade_data = False
        self._has_l2_data = False
        self._has_multi_venue = False
        
        # Reset per‑channel monotonic timestamps
        for channel in self._last_channel_ts_ns:
            self._last_channel_ts_ns[channel] = None
        self._last_venue_ts_ns.clear()
        
        # Reset calibration state
        self._calibrated_weights = self._base_weights.copy()
        self._calibration_samples = 0
        self._calibration_active = False
        
        logger.info(f"ToxicityEngine reset for {self.symbol}")
