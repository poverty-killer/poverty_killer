"""
Whale Flow Engine - Institutional Accumulation Proxy (Candle-Level)
CITADEL GRADE — DETERMINISTIC · REPLAY-SAFE · NO FAKE TRADES

ANALYTICAL/NON-MONETARY BOUNDARY:
This file performs analytical signal processing using float64 for performance.
It produces whale accumulation PROXY scores based on candle-level evidence.
These are NOT trade-level truth or monetary truth.
All monetary calculations must use Decimal (see DECIMAL_ONLY constraint).

DETERMINISTIC BEHAVIOR:
- No random number generation
- No wall-clock time (datetime.utcnow, timedelta)
- No simulated trade data
- All timing uses integer nanoseconds from exchange_ts_ns
- Outputs are deterministic given identical candle sequences

INSTITUTIONAL ACCUMULATION PROXY:
This engine uses strong candle-derived analytical proxies:
- Volume anomaly (z-score based)
- Range compression (price stability under volume)
- Absorption behavior (volume without directional displacement)
- Persistence (repeated evidence across candles)
- Acceptance bias (close position within candle range)
- Zone memory with deterministic TTL expiry

TRUTHFUL TERMINOLOGY:
- "whale accumulation proxy" not "whale detection"
- "institutional accumulation proxy" not "trade-level truth"
- "whale-presence zone" not "whale zone"
- "absorption proxy" not "trade absorption"
- "volume anomaly proxy" not "whale volume"

NO FAKE PRODUCTION COMPATIBILITY:
- No simulated trades
- No synthetic data generation
- No np.random
- No datetime.utcnow()
- No timedelta in governed logic
"""

import logging
import numpy as np
from typing import Optional, Dict, List, Tuple, Any
from collections import deque
from dataclasses import dataclass
from enum import IntEnum

# Preserved legacy model import for compatibility with the current repo contract surface.
from app.models import WhaleFlowScore, Candle

logger = logging.getLogger(__name__)


class DirectionBias(IntEnum):
    """Bounded directional metadata for zone bias."""
    NEUTRAL = 0
    BULLISH = 1
    BEARISH = 2


@dataclass
class WhalePresenceZone:
    """
    Whale presence zone — deterministic, replay-safe.
    
    Stores evidence of institutional accumulation proxy patterns.
    Zone lifecycle uses integer nanoseconds from exchange_ts_ns only.
    """
    symbol: str
    low: float
    high: float
    score: float
    volume: float
    created_ts_ns: int
    updated_ts_ns: int
    evidence_count: int
    direction_bias: DirectionBias
    avg_volume_anomaly: float
    avg_compression: float
    avg_absorption: float


class WhaleFlowEngine:
    """
    Institutional accumulation proxy engine — candle-level only.
    
    This engine does NOT have access to trade-level data.
    It uses strong analytical proxies from candle structure:
    - Volume anomaly detection
    - Range compression (price stability under volume)
    - Absorption behavior (volume without directional displacement)
    - Persistence scoring (repeated evidence)
    - Acceptance bias (close position within range)
    
    All outputs are analytical proxies, not trade-level truth.
    
    TIMING AUTHORITY:
    - ONLY exchange_ts_ns is authoritative for governed runtime state
    - candle.timestamp is preserved as metadata for legacy output fields ONLY
    - If exchange_ts_ns is missing, the engine returns None and degrades honestly
    """
    
    def __init__(
        self,
        threshold_z: float = 2.0,
        accumulation_window: int = 20,
        ttl_ns: int = 60_000_000_000,  # 60 seconds in nanoseconds
        volume_history_size: int = 1000,
        persistence_window: int = 5,
        min_evidence_count: int = 2,
        compression_threshold: float = 0.005,  # 0.5% range relative to price
        absorption_threshold: float = 0.3,  # Net displacement < 30% of range
        zone_expiry_grace_ns: int = 5_000_000_000  # 5 seconds grace period
    ):
        """
        Initialize whale flow engine with deterministic parameters.
        
        Args:
            threshold_z: Z-score threshold for volume anomaly
            accumulation_window: Number of candles for accumulation detection
            ttl_ns: Time-to-live for whale signals in nanoseconds
            volume_history_size: Maximum volume history per symbol
            persistence_window: Candles to consider for persistence scoring
            min_evidence_count: Minimum evidence count to establish zone
            compression_threshold: Range/price threshold for compression (0.5% = 0.005)
            absorption_threshold: Max net displacement/range for absorption (30% = 0.3)
            zone_expiry_grace_ns: Grace period before zone expiry
        """
        self.threshold_z = threshold_z
        self.accumulation_window = accumulation_window
        self.ttl_ns = ttl_ns
        self.volume_history_size = volume_history_size
        self.persistence_window = persistence_window
        self.min_evidence_count = min_evidence_count
        self.compression_threshold = compression_threshold
        self.absorption_threshold = absorption_threshold
        self.zone_expiry_grace_ns = zone_expiry_grace_ns
        
        # Per-symbol state
        self._volumes: Dict[str, deque] = {}  # Volume history
        self._closes: Dict[str, deque] = {}  # Close price history
        self._opens: Dict[str, deque] = {}  # Open price history (if available)
        self._highs: Dict[str, deque] = {}  # High price history (if available)
        self._lows: Dict[str, deque] = {}  # Low price history (if available)
        self._timestamps_ns: Dict[str, deque] = {}  # Nanosecond timestamps from exchange_ts_ns
        
        # Evidence tracking for persistence
        self._volume_anomaly_history: Dict[str, deque] = {}
        self._compression_history: Dict[str, deque] = {}
        self._absorption_history: Dict[str, deque] = {}
        
        # Active whale presence zones
        self._whale_zones: Dict[str, WhalePresenceZone] = {}
        
        logger.info(f"WhaleFlowEngine initialized: threshold_z={threshold_z}, "
                   f"window={accumulation_window}, ttl_ns={ttl_ns}, "
                   f"min_evidence_count={min_evidence_count}")
        logger.info("  Analytical proxy mode — NO trade simulation, NO wall-clock time")
        logger.info("  Timing authority: exchange_ts_ns only")
    
    def _init_symbol_state(self, symbol: str) -> None:
        """Initialize per-symbol state containers."""
        if symbol not in self._volumes:
            self._volumes[symbol] = deque(maxlen=self.volume_history_size)
            self._closes[symbol] = deque(maxlen=self.volume_history_size)
            self._opens[symbol] = deque(maxlen=self.volume_history_size)
            self._highs[symbol] = deque(maxlen=self.volume_history_size)
            self._lows[symbol] = deque(maxlen=self.volume_history_size)
            self._timestamps_ns[symbol] = deque(maxlen=self.volume_history_size)
            self._volume_anomaly_history[symbol] = deque(maxlen=self.persistence_window)
            self._compression_history[symbol] = deque(maxlen=self.persistence_window)
            self._absorption_history[symbol] = deque(maxlen=self.persistence_window)
    
    def _extract_timestamp_ns(self, candle: Candle) -> Optional[int]:
        """
        Extract authoritative nanosecond timestamp from candle.
        
        TIMING AUTHORITY RULE:
        - ONLY exchange_ts_ns is authoritative for governed runtime state
        - candle.timestamp is preserved ONLY as metadata for legacy output fields
        - If exchange_ts_ns is missing, return None and degrade honestly
        
        Returns:
            Authoritative timestamp in nanoseconds, or None if unavailable
        """
        # Check for authoritative exchange timestamp
        if hasattr(candle, 'exchange_ts_ns') and candle.exchange_ts_ns is not None:
            return int(candle.exchange_ts_ns)
        
        # exchange_ts_ns is missing — cannot determine authoritative timing
        # candle.timestamp is NOT used for lifecycle authority (metadata only)
        logger.warning(f"No exchange_ts_ns for {candle.symbol} — cannot process governed state")
        return None
    
    def _safe_get_ohlc(self, candle: Candle) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
        """
        Safely extract OHLC values.
        
        Returns:
            Tuple of (open, high, low, close) — missing values are None
        """
        open_val = getattr(candle, 'open', None)
        high_val = getattr(candle, 'high', None)
        low_val = getattr(candle, 'low', None)
        close_val = getattr(candle, 'close', None)
        
        return open_val, high_val, low_val, close_val
    
    def _compute_volume_anomaly(self, symbol: str, current_volume: float) -> Tuple[float, float]:
        """
        Compute volume anomaly z-score and normalized score.
        
        Returns:
            Tuple of (z_score, anomaly_score) where anomaly_score is 0-1 bounded
        """
        volumes = list(self._volumes[symbol])
        
        if len(volumes) < self.accumulation_window:
            return 0.0, 0.0
        
        # Exclude current volume from historical stats
        historical = volumes[:-1] if len(volumes) > 1 else volumes
        
        if len(historical) < 2:
            return 0.0, 0.0
        
        mean_vol = np.mean(historical)
        std_vol = np.std(historical)
        
        if std_vol == 0:
            return 0.0, 0.0
        
        z_score = (current_volume - mean_vol) / std_vol
        
        # Convert z-score to bounded anomaly score (0-1)
        # z=0 -> 0, z=threshold_z -> 0.5, z=2*threshold_z -> 0.75, asymptotically 1
        anomaly_score = 1.0 - (1.0 / (1.0 + z_score / self.threshold_z)) if z_score > 0 else 0.0
        anomaly_score = min(1.0, max(0.0, anomaly_score))
        
        return z_score, anomaly_score
    
    def _compute_range_compression(self, symbol: str) -> float:
        """
        Compute range compression proxy (price stability under volume).
        
        Returns compression score 0-1 where:
        - 1.0 = extremely compressed (very stable price)
        - 0.0 = no compression (high volatility)
        """
        closes = list(self._closes[symbol])
        highs = list(self._highs[symbol])
        lows = list(self._lows[symbol])
        
        if len(closes) < self.accumulation_window:
            return 0.5  # Neutral default with insufficient data
        
        # Use true ranges if high/low available
        if highs and lows and len(highs) >= self.accumulation_window and len(lows) >= self.accumulation_window:
            recent_highs = highs[-self.accumulation_window:]
            recent_lows = lows[-self.accumulation_window:]
            recent_closes = closes[-self.accumulation_window:]
            
            price_range = max(recent_highs) - min(recent_lows)
            avg_price = np.mean(recent_closes)
        else:
            # Fallback to close-to-close displacement proxy
            recent_closes = closes[-self.accumulation_window:]
            price_range = max(recent_closes) - min(recent_closes)
            avg_price = np.mean(recent_closes)
        
        if avg_price == 0:
            return 0.5
        
        # Normalize range relative to price
        range_ratio = price_range / avg_price
        
        # Compression score: lower range = higher compression
        # compression_threshold (0.5%) -> score 1.0
        # 2x threshold -> score 0.5, 4x -> 0.25
        if range_ratio <= self.compression_threshold:
            compression = 1.0
        else:
            compression = self.compression_threshold / range_ratio
            compression = min(1.0, max(0.0, compression))
        
        return compression
    
    def _compute_absorption_proxy(self, symbol: str) -> float:
        """
        Compute absorption proxy — volume without directional displacement.
        
        Returns absorption score 0-1 where:
        - 1.0 = strong absorption (high volume, minimal price movement)
        - 0.0 = no absorption (volume caused significant movement)
        """
        closes = list(self._closes[symbol])
        opens = list(self._opens[symbol])
        highs = list(self._highs[symbol])
        lows = list(self._lows[symbol])
        
        if len(closes) < 2:
            return 0.5
        
        # Get current and previous close
        current_close = closes[-1]
        prev_close = closes[-2]
        
        # Calculate net displacement
        net_displacement = abs(current_close - prev_close)
        
        # Calculate total range (if high/low available)
        if highs and lows and len(highs) >= 1 and len(lows) >= 1:
            candle_range = highs[-1] - lows[-1]
            if candle_range > 0:
                displacement_ratio = net_displacement / candle_range
            else:
                displacement_ratio = 1.0
        else:
            # Fallback: use close-to-close displacement relative to price level
            avg_price = (current_close + prev_close) / 2
            if avg_price > 0:
                displacement_ratio = net_displacement / avg_price
                # Normalize: 0.5% displacement = 0.5 ratio
                displacement_ratio = min(1.0, displacement_ratio / 0.01)
            else:
                displacement_ratio = 1.0
        
        # Absorption is inverse of displacement
        # Lower displacement = higher absorption
        if displacement_ratio <= self.absorption_threshold:
            absorption = 1.0
        else:
            absorption = self.absorption_threshold / displacement_ratio
            absorption = min(1.0, max(0.0, absorption))
        
        return absorption
    
    def _compute_persistence_score(self, symbol: str) -> float:
        """
        Compute persistence score — repeated evidence across recent candles.
        
        Returns persistence score 0-1 where:
        - 1.0 = strong persistent evidence across multiple candles
        - 0.0 = no persistent evidence
        """
        anomaly_history = list(self._volume_anomaly_history.get(symbol, []))
        compression_history = list(self._compression_history.get(symbol, []))
        absorption_history = list(self._absorption_history.get(symbol, []))
        
        if len(anomaly_history) < self.min_evidence_count:
            return 0.0
        
        # Take most recent N entries
        anomaly_recent = anomaly_history[-self.persistence_window:]
        compression_recent = compression_history[-self.persistence_window:]
        absorption_recent = absorption_history[-self.persistence_window:]
        
        # Calculate evidence strength (combined score)
        evidence_scores = []
        for i in range(len(anomaly_recent)):
            combined = (anomaly_recent[i] + compression_recent[i] + absorption_recent[i]) / 3
            evidence_scores.append(combined)
        
        # Persistence = average evidence across window
        persistence = np.mean(evidence_scores) if evidence_scores else 0.0
        
        # Bonus for consistency (low variance)
        if len(evidence_scores) > 1:
            variance = np.var(evidence_scores)
            consistency_bonus = 1.0 - min(1.0, variance)
            persistence = persistence * (0.7 + 0.3 * consistency_bonus)
        
        return min(1.0, max(0.0, persistence))
    
    def _compute_acceptance_bias(self, symbol: str) -> Tuple[DirectionBias, float]:
        """
        Compute acceptance bias — where close sits within candle range.
        
        Returns:
            Tuple of (direction_bias, bias_strength) where bias_strength is 0-1
        """
        closes = list(self._closes[symbol])
        highs = list(self._highs[symbol])
        lows = list(self._lows[symbol])
        
        if not highs or not lows or len(highs) == 0 or len(lows) == 0:
            return DirectionBias.NEUTRAL, 0.0
        
        current_high = highs[-1]
        current_low = lows[-1]
        current_close = closes[-1] if closes else None
        
        if current_close is None:
            return DirectionBias.NEUTRAL, 0.0
        
        candle_range = current_high - current_low
        if candle_range == 0:
            return DirectionBias.NEUTRAL, 0.0
        
        # Position within range: 0 = low, 1 = high
        position = (current_close - current_low) / candle_range
        
        # Bias based on position
        if position > 0.7:
            bias = DirectionBias.BULLISH
            strength = (position - 0.7) / 0.3  # 0-1 scale
        elif position < 0.3:
            bias = DirectionBias.BEARISH
            strength = (0.3 - position) / 0.3  # 0-1 scale
        else:
            bias = DirectionBias.NEUTRAL
            strength = 0.0
        
        return bias, min(1.0, strength)
    
    def _compute_zone_bounds(self, symbol: str) -> Tuple[float, float]:
        """
        Compute whale presence zone bounds based on recent price action.
        
        Returns:
            Tuple of (zone_low, zone_high)
        """
        closes = list(self._closes[symbol])
        highs = list(self._highs[symbol])
        lows = list(self._lows[symbol])
        
        # Use recent window for bounds
        window = min(self.accumulation_window, len(closes))
        if window < 2:
            # Fallback: close ± 0.5%
            current_close = closes[-1] if closes else 0
            return current_close * 0.995, current_close * 1.005
        
        recent_closes = closes[-window:]
        
        # Use high/low if available
        if highs and lows and len(highs) >= window and len(lows) >= window:
            recent_highs = highs[-window:]
            recent_lows = lows[-window:]
            zone_high = max(recent_highs)
            zone_low = min(recent_lows)
        else:
            # Use close range with 0.5% padding
            zone_high = max(recent_closes) * 1.005
            zone_low = min(recent_closes) * 0.995
        
        return zone_low, zone_high
    
    def _meets_evidence_threshold(self, symbol: str, composite_score: float) -> bool:
        """
        Determine if evidence meets minimum threshold for zone creation.
        
        Zone creation requires:
        1. Persistence evidence history length >= min_evidence_count
        2. AND (persistence score > 0.5 OR composite_score > 0.7)
        
        This prevents zone creation from single-candle noise.
        """
        persistence = self._compute_persistence_score(symbol)
        evidence_length = len(self._volume_anomaly_history.get(symbol, []))
        
        # Must have sufficient evidence history
        if evidence_length < self.min_evidence_count:
            return False
        
        # Must meet quality threshold
        return persistence > 0.5 or composite_score > 0.7
    
    def _merge_or_refresh_zone(self, symbol: str, current_ts_ns: int, score: float, 
                                volume: float, volume_anomaly: float, 
                                compression: float, absorption: float) -> Optional[WhalePresenceZone]:
        """
        Merge evidence into existing zone or create new zone.
        
        Zone creation is gated by _meets_evidence_threshold().
        
        Returns:
            Updated or new WhalePresenceZone, or None if insufficient evidence
        """
        zone_low, zone_high = self._compute_zone_bounds(symbol)
        bias, bias_strength = self._compute_acceptance_bias(symbol)
        
        # Get or create zone
        existing_zone = self._whale_zones.get(symbol)
        
        if existing_zone:
            # Merge: update bounds, scores, and evidence
            existing_zone.low = min(existing_zone.low, zone_low)
            existing_zone.high = max(existing_zone.high, zone_high)
            existing_zone.score = (existing_zone.score * existing_zone.evidence_count + score) / (existing_zone.evidence_count + 1)
            existing_zone.volume += volume
            existing_zone.updated_ts_ns = current_ts_ns
            existing_zone.evidence_count += 1
            existing_zone.avg_volume_anomaly = (existing_zone.avg_volume_anomaly * (existing_zone.evidence_count - 1) + volume_anomaly) / existing_zone.evidence_count
            existing_zone.avg_compression = (existing_zone.avg_compression * (existing_zone.evidence_count - 1) + compression) / existing_zone.evidence_count
            existing_zone.avg_absorption = (existing_zone.avg_absorption * (existing_zone.evidence_count - 1) + absorption) / existing_zone.evidence_count
            
            # Update direction bias if evidence is strong
            if bias_strength > 0.6:
                existing_zone.direction_bias = bias
            
            return existing_zone
        
        # Create new zone only if evidence threshold is met
        if self._meets_evidence_threshold(symbol, score):
            new_zone = WhalePresenceZone(
                symbol=symbol,
                low=zone_low,
                high=zone_high,
                score=score,
                volume=volume,
                created_ts_ns=current_ts_ns,
                updated_ts_ns=current_ts_ns,
                evidence_count=1,
                direction_bias=bias,
                avg_volume_anomaly=volume_anomaly,
                avg_compression=compression,
                avg_absorption=absorption
            )
            return new_zone
        
        return None
    
    def _clean_expired_signals(self, current_ts_ns: int) -> None:
        """
        Remove expired whale presence zones using deterministic nanosecond TTL.
        
        Args:
            current_ts_ns: Current timestamp in nanoseconds (authoritative)
        """
        expired = []
        for symbol, zone in self._whale_zones.items():
            age_ns = current_ts_ns - zone.updated_ts_ns
            if age_ns > (self.ttl_ns + self.zone_expiry_grace_ns):
                expired.append(symbol)
        
        for symbol in expired:
            del self._whale_zones[symbol]
            if expired:
                logger.debug(f"Expired whale presence zone for {symbol}")
    
    def update(self, candle: Candle) -> Optional[WhaleFlowScore]:
        """
        Update with new candle and return whale proxy score.
        
        Args:
            candle: New candle data (must have symbol and price/volume)
            
        Returns:
            WhaleFlowScore if detection, None otherwise
        """
        symbol = candle.symbol
        if not symbol:
            logger.warning("Candle missing symbol — skipping")
            return None
        
        # Extract authoritative timestamp from exchange_ts_ns only
        ts_ns = self._extract_timestamp_ns(candle)
        if ts_ns is None:
            # No authoritative timing — cannot process governed state
            logger.warning(f"No exchange_ts_ns for {symbol} — skipping update")
            return None
        
        # Initialize state for new symbol
        self._init_symbol_state(symbol)
        
        # Extract OHLC safely
        open_val, high_val, low_val, close_val = self._safe_get_ohlc(candle)
        
        # Must have close and volume
        if close_val is None or close_val <= 0:
            logger.warning(f"{symbol}: Missing close price — skipping")
            return None
        
        if not hasattr(candle, 'volume') or candle.volume is None or candle.volume <= 0:
            logger.warning(f"{symbol}: Missing volume — skipping")
            return None
        
        volume = float(candle.volume)
        close = float(close_val)
        
        # Store data with authoritative timestamp
        self._volumes[symbol].append(volume)
        self._closes[symbol].append(close)
        self._timestamps_ns[symbol].append(ts_ns)
        
        if open_val is not None:
            self._opens[symbol].append(float(open_val))
        if high_val is not None:
            self._highs[symbol].append(float(high_val))
        if low_val is not None:
            self._lows[symbol].append(float(low_val))
        
        # Need sufficient history
        if len(self._volumes[symbol]) < self.accumulation_window:
            return None
        
        # Compute analytical proxies
        z_score, volume_anomaly = self._compute_volume_anomaly(symbol, volume)
        compression = self._compute_range_compression(symbol)
        absorption = self._compute_absorption_proxy(symbol)
        
        # Store evidence for persistence
        self._volume_anomaly_history[symbol].append(volume_anomaly)
        self._compression_history[symbol].append(compression)
        self._absorption_history[symbol].append(absorption)
        
        # Compute composite whale presence score
        # Weighted combination of evidence
        evidence_components = [
            volume_anomaly * 0.35,   # Volume anomaly (strongest signal)
            compression * 0.25,       # Range compression
            absorption * 0.25,        # Absorption behavior
            self._compute_persistence_score(symbol) * 0.15  # Persistence (weights recent evidence)
        ]
        composite_score = sum(evidence_components)
        composite_score = min(1.0, max(0.0, composite_score))
        
        # Determine if accumulating (proxy detection)
        is_accumulating = (
            z_score > self.threshold_z and
            (compression > 0.5 or absorption > 0.5) and
            composite_score > 0.5
        )
        
        # Update zone if accumulating
        zone = None
        whale_zone_low = None
        whale_zone_high = None
        whale_zone_volume = 0.0
        
        if is_accumulating:
            zone = self._merge_or_refresh_zone(
                symbol, ts_ns, composite_score, volume,
                volume_anomaly, compression, absorption
            )
            
            if zone:
                whale_zone_low = zone.low
                whale_zone_high = zone.high
                whale_zone_volume = zone.volume
                self._whale_zones[symbol] = zone
        
        # Clean expired signals
        self._clean_expired_signals(ts_ns)
        
        # Build output (preserve WhaleFlowScore compatibility)
        # Note: These are ANALYTICAL ESTIMATES, not monetary truth
        # candle.timestamp is preserved as metadata for legacy compatibility only
        whale_usd_value = close * volume if close > 0 and volume > 0 else 0.0
        metadata_timestamp = getattr(candle, 'timestamp', None)
        
        return WhaleFlowScore(
            symbol=symbol,
            timestamp=metadata_timestamp,  # Metadata only, not timing authority
            score=composite_score,
            z_score=z_score,
            volume_anomaly=volume_anomaly,
            is_accumulating=is_accumulating,
            ttl_seconds=self.ttl_ns // 1_000_000_000,  # Convert ns to seconds for legacy contract
            whale_zone_low=whale_zone_low,
            whale_zone_high=whale_zone_high,
            whale_zone_volume=whale_zone_volume,
            whale_usd_value=whale_usd_value  # Analytical estimate only
        )
    
    def get_active_whale_zone(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get active whale presence zone for a symbol.
        
        Returns:
            Zone dict with deterministic fields or None
        """
        zone = self._whale_zones.get(symbol)
        if not zone:
            return None
        
        return {
            "low": zone.low,
            "high": zone.high,
            "score": zone.score,
            "volume": zone.volume,
            "created_ts_ns": zone.created_ts_ns,
            "updated_ts_ns": zone.updated_ts_ns,
            "evidence_count": zone.evidence_count,
            "direction_bias": zone.direction_bias.value,
            "avg_volume_anomaly": zone.avg_volume_anomaly,
            "avg_compression": zone.avg_compression,
            "avg_absorption": zone.avg_absorption
        }
    
    def get_whale_confidence(self, symbol: str, current_ts_ns: Optional[int] = None) -> float:
        """
        Get confidence of active whale presence signal.
        
        Args:
            symbol: Trading symbol
            current_ts_ns: Current authoritative timestamp in nanoseconds.
                          Required for recency calculation. If None, recency is skipped.
        
        Returns:
            Confidence score (0-1) or 0.0 if no active zone
        """
        zone = self._whale_zones.get(symbol)
        if not zone:
            return 0.0
        
        # Confidence based on score and evidence count
        evidence_factor = min(1.0, zone.evidence_count / 5.0)
        confidence = zone.score * 0.6 + evidence_factor * 0.4
        
        # Apply recency penalty if current timestamp provided
        if current_ts_ns is not None:
            age_ns = current_ts_ns - zone.updated_ts_ns
            if age_ns > 0:
                # Linear decay from 1.0 at creation to 0.0 at TTL
                recency_factor = max(0.0, 1.0 - (age_ns / self.ttl_ns))
                confidence = confidence * (0.5 + 0.5 * recency_factor)
        
        return min(1.0, max(0.0, confidence))
    
    def is_price_in_whale_zone(self, symbol: str, price: float, tolerance: float = 0.02) -> bool:
        """
        Check if price is within active whale presence zone.
        
        Args:
            symbol: Trading symbol
            price: Current price
            tolerance: Tolerance percentage (0.02 = 2%)
            
        Returns:
            True if price in whale zone
        """
        zone = self._whale_zones.get(symbol)
        if not zone:
            return False
        
        low = zone.low * (1 - tolerance)
        high = zone.high * (1 + tolerance)
        return low <= price <= high
    
    def reset(self, symbol: str) -> None:
        """
        Reset all state for a symbol.
        
        Args:
            symbol: Trading symbol
        """
        if symbol in self._volumes:
            self._volumes[symbol].clear()
        if symbol in self._closes:
            self._closes[symbol].clear()
        if symbol in self._opens:
            self._opens[symbol].clear()
        if symbol in self._highs:
            self._highs[symbol].clear()
        if symbol in self._lows:
            self._lows[symbol].clear()
        if symbol in self._timestamps_ns:
            self._timestamps_ns[symbol].clear()
        if symbol in self._volume_anomaly_history:
            self._volume_anomaly_history[symbol].clear()
        if symbol in self._compression_history:
            self._compression_history[symbol].clear()
        if symbol in self._absorption_history:
            self._absorption_history[symbol].clear()
        if symbol in self._whale_zones:
            del self._whale_zones[symbol]
    
    def get_stats(self, symbol: str) -> Dict[str, Any]:
        """
        Get statistics for a symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Dictionary with deterministic stats
        """
        zone = self._whale_zones.get(symbol)
        return {
            "symbol": symbol,
            "active_whale_zone": zone is not None,
            "whale_confidence": self.get_whale_confidence(symbol),  # Note: without recency
            "volume_history_size": len(self._volumes.get(symbol, [])),
            "persistence_window_size": len(self._volume_anomaly_history.get(symbol, [])),
            "zone_evidence_count": zone.evidence_count if zone else 0,
            "zone_score": zone.score if zone else 0.0,
            "zone_avg_volume_anomaly": zone.avg_volume_anomaly if zone else 0.0,
            "zone_avg_compression": zone.avg_compression if zone else 0.0,
            "zone_avg_absorption": zone.avg_absorption if zone else 0.0,
            "zone_direction_bias": zone.direction_bias.name if zone else "NONE"
        }