"""
Feature Builder - Technical Features for Alpha Models
Builds features: volatility z-score, ATR, volume anomaly, return bursts,
spread expansion, depth contraction, refill velocity, whale zone proximity.
Point-in-time only - no look-ahead bias.
"""

import logging
import numpy as np
from typing import List, Dict, Optional, Tuple, Any
from datetime import datetime
from collections import deque

from app.models import Candle, OrderBookSnapshot, LiquidityMetrics

logger = logging.getLogger(__name__)


class FeatureBuilder:
    """
    Builds technical features from candles and order book data.
    All features are point-in-time - using only data available at calculation time.
    """

    def __init__(self, slow_window: int = 50, fast_window: int = 10):
        """
        Initialize feature builder.

        Args:
            slow_window: Window size for slow features (e.g., ATR, volatility)
            fast_window: Window size for fast features (e.g., volume spike)
        """
        self.slow_window = slow_window
        self.fast_window = fast_window
        self.last_depth_contraction_status = "NOT_EVALUATED"
        self.last_depth_contraction_reason = "NOT_EVALUATED"
        logger.info(f"FeatureBuilder initialized: slow={slow_window}, fast={fast_window}")

    def calculate_volatility_zscore(self, candles: List[Candle], current_idx: int) -> float:
        """
        Calculate volatility z-score using point-in-time data.
        Only uses candles up to current_idx.

        Args:
            candles: Full candle list
            current_idx: Current index (exclusive)

        Returns:
            Volatility z-score
        """
        if current_idx < self.slow_window + 1:
            return 0.0

        # Use only historical candles (up to current_idx)
        historical = candles[:current_idx]
        if len(historical) < self.slow_window + 1:
            return 0.0

        # Calculate returns
        closes = [c.close for c in historical[-self.slow_window-1:]]
        returns = [0.0]
        for i in range(1, len(closes)):
            if closes[i-1] > 0:
                returns.append((closes[i] - closes[i-1]) / closes[i-1])

        # Recent returns (last fast_window)
        recent_returns = returns[-self.fast_window:] if len(returns) >= self.fast_window else returns

        # Rolling volatility
        hist_vol = np.std(returns[-self.slow_window:]) if len(returns) >= self.slow_window else 0.01
        recent_vol = np.std(recent_returns) if len(recent_returns) > 1 else 0.01

        if hist_vol == 0:
            return 0.0

        return (recent_vol - hist_vol) / hist_vol

    def calculate_atr_normalized(self, candles: List[Candle], current_idx: int) -> float:
        """
        Calculate ATR normalized by price.

        Args:
            candles: Full candle list
            current_idx: Current index

        Returns:
            ATR / price ratio
        """
        if current_idx < self.slow_window + 1:
            return 0.0

        historical = candles[:current_idx]
        if len(historical) < self.slow_window + 1:
            return 0.0

        # Calculate true ranges
        true_ranges = []
        for i in range(1, len(historical)):
            high = historical[i].high
            low = historical[i].low
            prev_close = historical[i-1].close
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            true_ranges.append(tr)

        if len(true_ranges) < self.slow_window:
            return 0.0

        # ATR = average true range
        atr = np.mean(true_ranges[-self.slow_window:])
        current_price = historical[-1].close

        if current_price == 0:
            return 0.0

        return atr / current_price

    def calculate_volume_anomaly_zscore(self, candles: List[Candle], current_idx: int) -> float:
        """
        Calculate volume anomaly z-score.

        Args:
            candles: Full candle list
            current_idx: Current index

        Returns:
            Volume z-score
        """
        if current_idx < self.slow_window + 1:
            return 0.0

        historical = candles[:current_idx]
        if len(historical) < self.slow_window + 1:
            return 0.0

        volumes = [c.volume for c in historical[-self.slow_window-1:]]
        recent_volume = volumes[-1]
        hist_volumes = volumes[:-1]

        if len(hist_volumes) < self.slow_window:
            return 0.0

        mean_vol = np.mean(hist_volumes)
        std_vol = np.std(hist_volumes)

        if std_vol == 0:
            return 0.0

        return (recent_volume - mean_vol) / std_vol

    def calculate_return_burst(self, candles: List[Candle], current_idx: int) -> float:
        """
        Calculate return burst magnitude (max return in recent window).

        Args:
            candles: Full candle list
            current_idx: Current index

        Returns:
            Absolute return burst magnitude
        """
        if current_idx < self.fast_window + 1:
            return 0.0

        historical = candles[:current_idx]
        if len(historical) < self.fast_window + 1:
            return 0.0

        closes = [c.close for c in historical[-self.fast_window-1:]]
        returns = []
        for i in range(1, len(closes)):
            if closes[i-1] > 0:
                returns.append(abs((closes[i] - closes[i-1]) / closes[i-1]))

        if not returns:
            return 0.0

        return max(returns)

    def calculate_spread_expansion(self, order_book: OrderBookSnapshot, historical_spreads: List[float]) -> float:
        """
        Calculate spread expansion multiple.

        Args:
            order_book: Current order book
            historical_spreads: List of recent spreads

        Returns:
            Spread expansion multiple (current / average)
        """
        current_spread = order_book.spread_bps
        if not historical_spreads:
            return 1.0

        avg_spread = np.mean(historical_spreads)
        if avg_spread == 0:
            return 1.0

        return current_spread / avg_spread

    def _derive_market_depth(self, order_book: OrderBookSnapshot, levels: int = 10) -> Optional[float]:
        """
        Derive two-sided market depth from the canonical OrderBookSnapshot fields.

        The canonical model exposes bids/asks plus depth_at_levels(...), not a
        market_depth attribute. Missing or non-finite depth is treated as absent
        truth instead of being converted to zero.
        """
        if order_book is None or not order_book.bids or not order_book.asks:
            return None

        if hasattr(order_book, "depth_at_levels"):
            bid_depth, ask_depth = order_book.depth_at_levels(levels)
        else:
            bid_depth = sum(size for _, size in order_book.bids[:levels])
            ask_depth = sum(size for _, size in order_book.asks[:levels])

        depths = np.array([bid_depth, ask_depth], dtype=float)
        if not np.all(np.isfinite(depths)):
            return None

        total_depth = float(bid_depth + ask_depth)
        if total_depth <= 0:
            return None
        return total_depth

    def calculate_depth_contraction(self, order_book: OrderBookSnapshot, historical_depths: List[float]) -> float:
        """
        Calculate depth contraction ratio.

        Args:
            order_book: Current order book
            historical_depths: List of recent depths

        Returns:
            Depth contraction ratio (current / average)
        """
        current_depth = self._derive_market_depth(order_book)
        if current_depth is None:
            self.last_depth_contraction_status = "MISSING_DEPTH_TRUTH"
            self.last_depth_contraction_reason = "ORDER_BOOK_DEPTH_UNAVAILABLE"
            return 1.0

        if not historical_depths or len(historical_depths) < 2:
            self.last_depth_contraction_status = "NOT_READY_DATA_WARMUP"
            self.last_depth_contraction_reason = "INSUFFICIENT_DEPTH_HISTORY"
            return 1.0

        finite_depths = np.array(historical_depths, dtype=float)
        if not np.all(np.isfinite(finite_depths)):
            self.last_depth_contraction_status = "MISSING_DEPTH_TRUTH"
            self.last_depth_contraction_reason = "NON_FINITE_DEPTH_HISTORY"
            return 1.0

        avg_depth = float(np.mean(finite_depths))
        if avg_depth <= 0:
            self.last_depth_contraction_status = "MISSING_DEPTH_TRUTH"
            self.last_depth_contraction_reason = "NON_POSITIVE_DEPTH_BASELINE"
            return 1.0

        self.last_depth_contraction_status = "ACTIVE_DEPTH_TRUTH"
        self.last_depth_contraction_reason = "CANONICAL_BID_ASK_DEPTH"
        return current_depth / avg_depth

    def calculate_refill_velocity(self, depth_history: List[float], time_delta: float) -> float:
        """
        Calculate liquidity refill velocity (volume per second).

        Args:
            depth_history: List of depths over time
            time_delta: Time span in seconds

        Returns:
            Refill velocity in volume per second
        """
        if len(depth_history) < 2 or time_delta <= 0:
            return 0.0

        min_depth = min(depth_history)
        max_depth = max(depth_history)
        refill = max_depth - min_depth

        return refill / time_delta

    def calculate_whale_zone_proximity(self, current_price: float, whale_zone_low: float, whale_zone_high: float) -> float:
        """
        Calculate distance from whale zone as percentage.

        Args:
            current_price: Current price
            whale_zone_low: Whale zone lower bound
            whale_zone_high: Whale zone upper bound

        Returns:
            Proximity score (0 = inside zone, higher = farther)
        """
        if whale_zone_low is None or whale_zone_high is None:
            return 1.0

        if whale_zone_low <= current_price <= whale_zone_high:
            return 0.0

        if current_price < whale_zone_low:
            return (whale_zone_low - current_price) / whale_zone_low
        else:
            return (current_price - whale_zone_high) / whale_zone_high

    def build_all_features(self, candles: List[Candle], current_idx: int,
                          order_book: Optional[OrderBookSnapshot] = None,
                          depth_history: Optional[List[float]] = None,
                          historical_spreads: Optional[List[float]] = None,
                          whale_zone: Optional[Tuple[float, float]] = None) -> Dict[str, float]:
        """
        Build all features at once.

        Args:
            candles: Full candle list
            current_idx: Current index
            order_book: Current order book (optional)
            depth_history: Historical depths (optional)
            historical_spreads: Historical spreads (optional)
            whale_zone: Whale zone (low, high) (optional)

        Returns:
            Dictionary of feature name -> value
        """
        features = {}

        # Candle-based features
        features["volatility_zscore"] = self.calculate_volatility_zscore(candles, current_idx)
        features["atr_normalized"] = self.calculate_atr_normalized(candles, current_idx)
        features["volume_anomaly_zscore"] = self.calculate_volume_anomaly_zscore(candles, current_idx)
        features["return_burst"] = self.calculate_return_burst(candles, current_idx)

        # Order book features
        if order_book:
            if historical_spreads:
                features["spread_expansion"] = self.calculate_spread_expansion(order_book, historical_spreads)
            else:
                features["spread_expansion"] = 1.0

            if depth_history:
                features["depth_contraction"] = self.calculate_depth_contraction(order_book, depth_history)
            else:
                features["depth_contraction"] = 1.0

            features["order_book_imbalance"] = order_book.imbalance
            features["spread_bps"] = order_book.spread_bps

        # Refill velocity
        if depth_history and len(depth_history) >= 2:
            # Assume 1 second per depth sample
            features["refill_velocity"] = self.calculate_refill_velocity(depth_history, len(depth_history))
        else:
            features["refill_velocity"] = 0.0

        # Whale zone proximity
        if whale_zone:
            low, high = whale_zone
            current_price = candles[current_idx - 1].close if current_idx > 0 else 0
            features["whale_zone_proximity"] = self.calculate_whale_zone_proximity(current_price, low, high)
        else:
            features["whale_zone_proximity"] = 1.0

        return features

    def build_features_batch(self, candles: List[Candle], start_idx: int, end_idx: int,
                            order_books: Optional[Dict[int, OrderBookSnapshot]] = None) -> List[Dict[str, Any]]:
        """
        Build features for a range of candles (for backtesting).

        Args:
            candles: Full candle list
            start_idx: Start index
            end_idx: End index (exclusive)
            order_books: Optional dict of index -> order book

        Returns:
            List of feature dictionaries with timestamps
        """
        features_list = []

        for idx in range(start_idx, end_idx):
            if idx < self.slow_window:
                continue

            order_book = order_books.get(idx) if order_books else None
            features = self.build_all_features(candles, idx, order_book)

            features_list.append({
                "timestamp": candles[idx].timestamp,
                "symbol": candles[idx].symbol,
                "price": candles[idx].close,
                "volume": candles[idx].volume,
                **features
            })

        return features_list
