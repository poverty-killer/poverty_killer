"""
Sentiment Engine - Institutional Sentiment State Aggregator
CITADEL GRADE — DETERMINISTIC · REPLAY-SAFE · NO SPLIT-BRAIN

ANALYTICAL/NON-MONETARY BOUNDARY:
This file performs analytical signal processing using float64 for performance.
It aggregates sentiment from multiple analytical sources and produces normalized
sentiment state for downstream consumption (particularly by SentimentVelocityEngine).
These are NOT monetary truth or trade execution signals.

ARCHITECTURAL ROLE:
This engine is the SENTIMENT STATE AGGREGATOR. It does NOT compute velocity/acceleration.
Velocity, acceleration, impulse, divergence, and macro safety signals are owned by:
app/brain/sentiment_velocity.py

Division of labor:
- sentiment_engine.py = source fusion, normalization, weighting, sentiment level, breadth, agreement
- sentiment_velocity.py = change-of-state (velocity, acceleration, impulse, divergence, macro overlay)

DETERMINISTIC BEHAVIOR:
- No wall-clock time (datetime.utcnow, timedelta)
- No random number generation
- All timing uses integer nanoseconds from authoritative external sources
- Outputs are deterministic given identical input sequences
"""

import numpy as np
import logging
from typing import Dict, Optional, List, Any, Tuple
from dataclasses import dataclass, field
from collections import deque

logger = logging.getLogger(__name__)

# Numerical stability epsilon
EPS = np.finfo(float).eps


@dataclass
class SourceSentiment:
    """Individual sentiment source reading with metadata."""
    source: str
    polarity: float  # -1.0 to 1.0, analytical only
    weight: float  # Source credibility weight (0-1)
    timestamp_ns: int
    confidence: float  # 0-1 confidence in this specific reading


@dataclass
class AggregateSentiment:
    """
    Aggregated sentiment state for a symbol.
    
    This is the ANALYTICAL SENTIMENT LEVEL only.
    For velocity/acceleration/divergence, use SentimentVelocityEngine.
    """
    symbol: str
    level: float  # Aggregated sentiment level (-1 to 1)
    source_count: int  # Number of sources that contributed
    source_breadth: float  # 0-1, ratio of active sources to expected sources
    agreement_score: float  # 0-1, how well sources agree (higher = more agreement)
    max_disagreement: float  # Maximum pairwise disagreement magnitude
    primary_source: str  # Highest-weight source that contributed
    timestamp_ns: int
    confidence: float  # 0-1 analytical confidence in aggregation


class SentimentEngine:
    """
    Institutional sentiment state aggregator.
    
    This engine fuses sentiment from multiple analytical sources, normalizes,
    weights, and produces a clean sentiment level for downstream consumption.
    
    TIMING AUTHORITY:
    - All timestamps must be provided by external authoritative source
    - No internal time generation
    - Timestamps must be monotonic per source
    
    INPUT HONESTY:
    - Receives pre-computed sentiment values from external analyzers
    - Does NOT ingest raw text, social media, or news feeds
    - Does NOT pretend to have live API connections
    
    DOWNSTREAM INTEGRATION:
    - Produces AggregateSentiment that can feed SentimentVelocityEngine
    - Does NOT compute velocity/acceleration (see sentiment_velocity.py)
    """
    
    def __init__(
        self,
        history_maxlen: int = 1000,
        source_weights: Optional[Dict[str, float]] = None,
        min_sources: int = 1,
        decay_half_life_ns: int = 300_000_000_000,  # 5 minutes
        max_source_age_ns: int = 600_000_000_000,  # 10 minutes
        agreement_threshold: float = 0.7,
        confidence_scaling: bool = True
    ):
        """
        Initialize sentiment engine with deterministic parameters.
        
        Args:
            history_maxlen: Maximum historical points per source
            source_weights: Source name -> credibility weight (0-1)
            min_sources: Minimum sources required for aggregation
            decay_half_life_ns: Half-life for exponential decay of source freshness
            max_source_age_ns: Maximum age before source considered stale
            agreement_threshold: Score threshold for "good agreement"
            confidence_scaling: Whether to scale confidence by agreement
        """
        self.history_maxlen = history_maxlen
        self.min_sources = min_sources
        self.decay_half_life_ns = decay_half_life_ns
        self.max_source_age_ns = max_source_age_ns
        self.agreement_threshold = agreement_threshold
        self.confidence_scaling = confidence_scaling
        
        # Default source weights (credibility, not trading weight)
        self.source_weights = source_weights or {
            "onchain": 0.9,      # High credibility
            "institutional": 0.85,
            "regulatory": 0.8,
            "macro": 0.75,
            "technical": 0.6,
            "social": 0.4,
            "news": 0.5
        }
        
        # Per-symbol, per-source historical data
        # Structure: {symbol: {source: deque[SourceSentiment]}}
        self._history: Dict[str, Dict[str, deque]] = {}
        
        # Last aggregated output per symbol
        self._last_aggregate: Dict[str, AggregateSentiment] = {}
        
        logger.info(f"SentimentEngine initialized: min_sources={min_sources}, "
                   f"decay_half_life_ns={decay_half_life_ns}, max_source_age_ns={max_source_age_ns}")
        logger.info("  ARCHITECTURAL ROLE: Sentiment state aggregator only")
        logger.info("  Velocity/acceleration/divergence handled by sentiment_velocity.py")
    
    def _init_symbol_sources(self, symbol: str) -> None:
        """Initialize per-symbol source history containers."""
        if symbol not in self._history:
            self._history[symbol] = {}
    
    def _get_source_weight(self, source: str) -> float:
        """Get credibility weight for a source, with bounded default."""
        return self.source_weights.get(source, 0.5)
    
    def _freshness_weight(self, age_ns: int) -> float:
        """
        Compute freshness weight based on age using exponential decay.
        
        Args:
            age_ns: Age in nanoseconds
            
        Returns:
            Weight in [0, 1]
        """
        if age_ns < 0:
            return 0.0
        if age_ns >= self.max_source_age_ns:
            return 0.0
        
        decay_factor = np.log(2) / self.decay_half_life_ns
        weight = np.exp(-decay_factor * age_ns)
        return max(0.0, min(1.0, weight))
    
    def _compute_agreement(self, values: List[float], weights: List[float]) -> Tuple[float, float]:
        """
        Compute agreement score and maximum disagreement among sources.
        
        Args:
            values: List of sentiment polarities
            weights: List of source weights
            
        Returns:
            Tuple of (agreement_score, max_disagreement)
        """
        if len(values) < 2:
            return 1.0, 0.0
        
        # Normalize weights
        total_weight = sum(weights)
        if total_weight < EPS:
            return 0.0, 0.0
        
        norm_weights = [w / total_weight for w in weights]
        
        # Weighted mean
        weighted_mean = sum(v * w for v, w in zip(values, norm_weights))
        
        # Weighted standard deviation as disagreement metric
        variance = sum(w * (v - weighted_mean) ** 2 for v, w in zip(values, norm_weights))
        std_dev = np.sqrt(variance)
        
        # Agreement: 1 - normalized std (typical sentiment range is 2)
        max_std = 1.0  # Maximum reasonable std for sentiment in [-1,1]
        agreement = max(0.0, min(1.0, 1.0 - (std_dev / max_std)))
        
        # Maximum pairwise disagreement
        max_disagreement = 0.0
        for i in range(len(values)):
            for j in range(i + 1, len(values)):
                disagreement = abs(values[i] - values[j]) * min(weights[i], weights[j])
                max_disagreement = max(max_disagreement, disagreement)
        
        return agreement, min(1.0, max_disagreement)
    
    def update_source(
        self,
        symbol: str,
        source: str,
        polarity: float,
        timestamp_ns: int,
        confidence: float = 1.0
    ) -> None:
        """
        Update a single sentiment source for a symbol.
        
        Args:
            symbol: Trading symbol
            source: Source name (must match source_weights keys)
            polarity: Sentiment polarity (-1 to 1)
            timestamp_ns: Authoritative nanosecond timestamp
            confidence: Confidence in this specific reading (0-1)
        """
        # Validate inputs
        if not symbol or not source:
            logger.warning("Missing symbol or source — skipping update")
            return
        
        if not isinstance(timestamp_ns, int) or timestamp_ns <= 0:
            logger.warning(f"Invalid timestamp for {symbol}/{source} — skipping")
            return
        
        if not isinstance(polarity, (int, float)) or not np.isfinite(polarity):
            logger.warning(f"Invalid polarity for {symbol}/{source} — skipping")
            return
        
        # Clamp polarity
        clamped_polarity = max(-1.0, min(1.0, float(polarity)))
        clamped_confidence = max(0.0, min(1.0, confidence))
        
        # Initialize
        self._init_symbol_sources(symbol)
        
        if source not in self._history[symbol]:
            self._history[symbol][source] = deque(maxlen=self.history_maxlen)
        
        # Get source weight
        source_weight = self._get_source_weight(source)
        
        # Create sentiment point
        point = SourceSentiment(
            source=source,
            polarity=clamped_polarity,
            weight=source_weight,
            timestamp_ns=timestamp_ns,
            confidence=clamped_confidence
        )
        
        # Enforce monotonic timestamps per source
        if self._history[symbol][source]:
            last_ts = self._history[symbol][source][-1].timestamp_ns
            if timestamp_ns <= last_ts:
                logger.warning(f"Non-monotonic timestamp for {symbol}/{source} — rejecting update")
                return
        
        self._history[symbol][source].append(point)
    
    def aggregate(self, symbol: str, current_ts_ns: int) -> Optional[AggregateSentiment]:
        """
        Aggregate all sources for a symbol into a single sentiment state.
        
        Args:
            symbol: Trading symbol
            current_ts_ns: Current authoritative timestamp for freshness calculation
            
        Returns:
            AggregateSentiment or None if insufficient sources
        """
        if symbol not in self._history:
            return None
        
        # Collect fresh sources (within max age)
        fresh_points = []
        for source, points in self._history[symbol].items():
            if not points:
                continue
            
            latest = points[-1]
            age_ns = current_ts_ns - latest.timestamp_ns
            if age_ns < 0:
                continue
            
            freshness = self._freshness_weight(age_ns)
            if freshness > 0:
                fresh_points.append((source, latest, freshness))
        
        if len(fresh_points) < self.min_sources:
            return None
        
        # Prepare for aggregation
        sources = []
        polarities = []
        weights = []
        confidences = []
        freshnesses = []
        
        for source, point, freshness in fresh_points:
            sources.append(source)
            polarities.append(point.polarity)
            weights.append(point.weight)
            confidences.append(point.confidence)
            freshnesses.append(freshness)
        
        # Combined weight = source_credibility * freshness * reading_confidence
        combined_weights = [
            w * f * c for w, f, c in zip(weights, freshnesses, confidences)
        ]
        total_weight = sum(combined_weights)
        
        if total_weight < EPS:
            return None
        
        # Normalize weights
        norm_weights = [w / total_weight for w in combined_weights]
        
        # Weighted sentiment level
        level = sum(p * nw for p, nw in zip(polarities, norm_weights))
        level = max(-1.0, min(1.0, level))
        
        # Compute agreement and disagreement
        agreement, max_disagreement = self._compute_agreement(polarities, combined_weights)
        
        # Source breadth: ratio of active sources to possible sources
        expected_sources = len(self.source_weights)
        source_breadth = min(1.0, len(fresh_points) / max(expected_sources, 1))
        
        # Determine primary source (highest combined weight)
        primary_idx = max(range(len(combined_weights)), key=lambda i: combined_weights[i])
        primary_source = sources[primary_idx]
        
        # Aggregate confidence
        base_confidence = min(1.0, total_weight / len(fresh_points))
        
        if self.confidence_scaling:
            # Scale confidence by agreement and breadth
            confidence = base_confidence * agreement * (0.5 + 0.5 * source_breadth)
        else:
            confidence = base_confidence
        
        confidence = max(0.0, min(1.0, confidence))
        
        result = AggregateSentiment(
            symbol=symbol,
            level=level,
            source_count=len(fresh_points),
            source_breadth=source_breadth,
            agreement_score=agreement,
            max_disagreement=max_disagreement,
            primary_source=primary_source,
            timestamp_ns=current_ts_ns,
            confidence=confidence
        )
        
        self._last_aggregate[symbol] = result
        return result
    
    def get_sentiment_level(self, symbol: str, current_ts_ns: int) -> Optional[float]:
        """
        Get current sentiment level for a symbol (convenience method).
        
        Args:
            symbol: Trading symbol
            current_ts_ns: Current authoritative timestamp
            
        Returns:
            Sentiment level in [-1, 1] or None if unavailable
        """
        agg = self.aggregate(symbol, current_ts_ns)
        return agg.level if agg else None
    
    def get_aggregate(self, symbol: str) -> Optional[AggregateSentiment]:
        """Return most recent aggregate for symbol, or None."""
        return self._last_aggregate.get(symbol)
    
    def get_source_count(self, symbol: str) -> int:
        """Get number of active sources for a symbol."""
        if symbol not in self._history:
            return 0
        return len([s for s, pts in self._history[symbol].items() if pts])
    
    def get_source_recent(self, symbol: str, source: str, count: int = 5) -> List[SourceSentiment]:
        """
        Get recent readings from a specific source.
        
        Args:
            symbol: Trading symbol
            source: Source name
            count: Number of recent readings to return
            
        Returns:
            List of recent SourceSentiment points
        """
        if symbol not in self._history or source not in self._history[symbol]:
            return []
        points = list(self._history[symbol][source])
        return points[-count:]
    
    def get_stats(self, symbol: str, current_ts_ns: int) -> Dict[str, Any]:
        """Get current statistics for a symbol."""
        agg = self.aggregate(symbol, current_ts_ns)
        return {
            "symbol": symbol,
            "has_aggregate": agg is not None,
            "sentiment_level": agg.level if agg else None,
            "sentiment_confidence": agg.confidence if agg else None,
            "source_count": agg.source_count if agg else 0,
            "source_breadth": agg.source_breadth if agg else 0.0,
            "agreement_score": agg.agreement_score if agg else 0.0,
            "primary_source": agg.primary_source if agg else None,
            "total_sources_configured": len(self.source_weights),
            "active_sources": self.get_source_count(symbol)
        }
    
    def reset(self, symbol: Optional[str] = None) -> None:
        """
        Reset state for a symbol or all symbols.
        
        Args:
            symbol: Symbol to reset, or None for all symbols
        """
        if symbol is None:
            self._history.clear()
            self._last_aggregate.clear()
            logger.info("SentimentEngine reset (all symbols)")
        else:
            if symbol in self._history:
                del self._history[symbol]
            if symbol in self._last_aggregate:
                del self._last_aggregate[symbol]
            logger.info(f"SentimentEngine reset for {symbol}")