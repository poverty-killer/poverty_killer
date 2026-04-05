"""
Depth Book - High-Performance Order Book Manager
Maintains L2/L3 order book state with NumPy acceleration.
Calculates real-time spread, mid-price, micro-price, and liquidity metrics.
Sovereign Grade - Complete implementation.
"""

import logging
import numpy as np
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
from collections import deque

from app.models import OrderBookSnapshot, LiquidityMetrics

logger = logging.getLogger(__name__)

# Machine epsilon for precision
EPS = np.finfo(float).eps


class DepthBook:
    """
    High-performance order book manager.
    Tracks bid/ask levels with NumPy arrays for fast calculations.
    Used for FLV crisis detection, Shan's Curve, and order execution.
    
    Features:
    - Real-time spread, mid-price, micro-price
    - Depth-weighted average price
    - Liquidity void detection
    - Market impact estimation
    - Historical depth tracking
    """
    
    def __init__(self, symbol: str, max_depth_levels: int = 50):
        """
        Initialize depth book.

        Args:
            symbol: Trading symbol
            max_depth_levels: Maximum number of price levels to track
        """
        self.symbol = symbol
        self.max_depth_levels = max_depth_levels
        
        # Order book state as NumPy arrays for vectorized operations
        self._bids_prices: np.ndarray = np.zeros(max_depth_levels)
        self._bids_sizes: np.ndarray = np.zeros(max_depth_levels)
        self._asks_prices: np.ndarray = np.zeros(max_depth_levels)
        self._asks_sizes: np.ndarray = np.zeros(max_depth_levels)
        self._bid_count: int = 0
        self._ask_count: int = 0
        
        # Timestamp tracking
        self.timestamp: Optional[datetime] = None
        self.exchange_ts_ns: Optional[int] = None
        
        # Historical tracking for analytics
        self.depth_history: deque = deque(maxlen=100)
        self.spread_history: deque = deque(maxlen=100)
        self.imbalance_history: deque = deque(maxlen=100)
        self.mid_price_history: deque = deque(maxlen=100)
        
        # Micro-price calculation state
        self._micro_price: float = 0.0
        self._last_micro_price_update: Optional[datetime] = None
        
        logger.debug(f"DepthBook initialized for {symbol}")
    
    # ============================================
    # UPDATE METHODS
    # ============================================
    
    def update(self, snapshot: OrderBookSnapshot) -> None:
        """
        Update order book with new snapshot.
        Converts to NumPy arrays for fast calculations.

        Args:
            snapshot: Order book snapshot
        """
        # Update bids
        self._bid_count = min(len(snapshot.bids), self.max_depth_levels)
        for i in range(self._bid_count):
            self._bids_prices[i] = snapshot.bids[i][0]
            self._bids_sizes[i] = snapshot.bids[i][1]
        
        # Update asks
        self._ask_count = min(len(snapshot.asks), self.max_depth_levels)
        for i in range(self._ask_count):
            self._asks_prices[i] = snapshot.asks[i][0]
            self._asks_sizes[i] = snapshot.asks[i][1]
        
        # Update timestamps
        self.timestamp = snapshot.timestamp
        self.exchange_ts_ns = snapshot.exchange_ts_ns
        
        # Update micro-price
        self._update_micro_price()
        
        # Record history
        self.depth_history.append(self.market_depth)
        self.spread_history.append(self.spread_bps)
        self.imbalance_history.append(self.imbalance)
        self.mid_price_history.append(self.mid_price)
    
    def _update_micro_price(self) -> None:
        """
        Calculate micro-price (depth-weighted mid).
        More sophisticated than simple mid, accounts for imbalance.
        """
        if self._bid_count == 0 or self._ask_count == 0:
            self._micro_price = self.mid_price
            return
        
        # Get top levels
        best_bid = self.best_bid
        best_ask = self.best_ask
        bid_size = self._bids_sizes[0]
        ask_size = self._asks_sizes[0]
        
        # Depth-weighted micro-price
        total_size = bid_size + ask_size
        if total_size > EPS:
            self._micro_price = (best_bid * ask_size + best_ask * bid_size) / total_size
        else:
            self._micro_price = (best_bid + best_ask) / 2
    
    # ============================================
    # PROPERTIES
    # ============================================
    
    @property
    def best_bid(self) -> Optional[float]:
        """Best bid price."""
        return float(self._bids_prices[0]) if self._bid_count > 0 else None
    
    @property
    def best_ask(self) -> Optional[float]:
        """Best ask price."""
        return float(self._asks_prices[0]) if self._ask_count > 0 else None
    
    @property
    def mid_price(self) -> float:
        """Simple mid price = (best_bid + best_ask) / 2."""
        if self._bid_count == 0 or self._ask_count == 0:
            return 0.0
        return (self._bids_prices[0] + self._asks_prices[0]) / 2
    
    @property
    def micro_price(self) -> float:
        """Micro-price (depth-weighted) for better execution."""
        return self._micro_price
    
    @property
    def spread(self) -> float:
        """Bid-ask spread in absolute terms."""
        if self._bid_count == 0 or self._ask_count == 0:
            return float('inf')
        return self._asks_prices[0] - self._bids_prices[0]
    
    @property
    def spread_bps(self) -> float:
        """Bid-ask spread in basis points."""
        mid = self.mid_price
        if mid <= 0:
            return float('inf')
        return (self.spread / mid) * 10000
    
    @property
    def market_depth(self) -> float:
        """Total depth at top 10 levels."""
        bid_depth = self._bids_sizes[:min(10, self._bid_count)].sum()
        ask_depth = self._asks_sizes[:min(10, self._ask_count)].sum()
        return float(bid_depth + ask_depth)
    
    @property
    def bid_depth(self) -> float:
        """Total bid depth at top levels."""
        return float(self._bids_sizes[:min(10, self._bid_count)].sum())
    
    @property
    def ask_depth(self) -> float:
        """Total ask depth at top levels."""
        return float(self._asks_sizes[:min(10, self._ask_count)].sum())
    
    @property
    def imbalance(self) -> float:
        """
        Order book imbalance (-1 = all asks, 1 = all bids).
        Positive = more bids (bullish), negative = more asks (bearish).
        """
        bid_depth, ask_depth = self.get_depth_at_levels(10)
        total = bid_depth + ask_depth
        if total < EPS:
            return 0.0
        return (bid_depth - ask_depth) / total
    
    @property
    def is_liquid(self) -> bool:
        """Check if market is sufficiently liquid."""
        return self.spread_bps < 20 and self.market_depth > 1.0
    
    @property
    def max_safe_position_size(self) -> float:
        """
        Calculate maximum position size that can be entered safely.
        Based on consuming no more than 10% of top-level depth.
        """
        bid_depth, ask_depth = self.get_depth_at_levels(5)
        safe_size = min(bid_depth, ask_depth) * 0.1
        return max(float(safe_size), 0.0)
    
    # ============================================
    # ANALYTICS METHODS
    # ============================================
    
    def get_depth_at_levels(self, levels: int) -> Tuple[float, float]:
        """
        Get total bid and ask volume at top N levels.

        Args:
            levels: Number of levels to aggregate

        Returns:
            Tuple of (bid_depth, ask_depth)
        """
        levels = min(levels, self.max_depth_levels)
        bid_depth = self._bids_sizes[:min(levels, self._bid_count)].sum()
        ask_depth = self._asks_sizes[:min(levels, self._ask_count)].sum()
        return float(bid_depth), float(ask_depth)
    
    def get_price_at_depth(self, side: str, target_volume: float) -> Optional[float]:
        """
        Get price at which a given volume can be executed.

        Args:
            side: "buy" or "sell"
            target_volume: Volume to execute

        Returns:
            Price at which volume can be filled, or None if insufficient depth
        """
        if side == "buy":
            levels = self._asks_prices[:self._ask_count]
            sizes = self._asks_sizes[:self._ask_count]
        else:
            levels = self._bids_prices[:self._bid_count]
            sizes = self._bids_sizes[:self._bid_count]
        
        accumulated = 0.0
        for i in range(len(levels)):
            accumulated += sizes[i]
            if accumulated >= target_volume:
                return float(levels[i])
        
        return None
    
    def get_volume_weighted_price(self, side: str, volume: float) -> Optional[float]:
        """
        Calculate volume-weighted average price for a given volume.

        Args:
            side: "buy" or "sell"
            volume: Volume to execute

        Returns:
            VWAP or None if insufficient depth
        """
        if side == "buy":
            levels = self._asks_prices[:self._ask_count]
            sizes = self._asks_sizes[:self._ask_count]
        else:
            levels = self._bids_prices[:self._bid_count]
            sizes = self._bids_sizes[:self._bid_count]
        
        remaining = volume
        total_cost = 0.0
        filled = 0.0
        
        for i in range(len(levels)):
            fill = min(remaining, sizes[i])
            total_cost += fill * levels[i]
            filled += fill
            remaining -= fill
            if remaining <= 0:
                break
        
        if filled < volume - EPS:
            return None
        
        return total_cost / filled
    
    def get_price_impact(self, side: str, volume: float) -> Optional[float]:
        """
        Calculate price impact for a given volume in basis points.

        Args:
            side: "buy" or "sell"
            volume: Volume to execute

        Returns:
            Price impact in basis points, or None if insufficient depth
        """
        vwap = self.get_volume_weighted_price(side, volume)
        if vwap is None:
            return None
        
        mid = self.mid_price
        if mid < EPS:
            return None
        
        if side == "buy":
            impact = (vwap - mid) / mid * 10000
        else:
            impact = (mid - vwap) / mid * 10000
        
        return float(impact)
    
    def get_liquidity_void_score(self) -> float:
        """
        Calculate liquidity void score (0-1).
        Higher score = deeper void.

        Returns:
            Void score
        """
        # Check spread expansion
        if self.spread_history and len(self.spread_history) >= 10:
            avg_spread = np.mean(list(self.spread_history)[-10:])
            spread_ratio = self.spread_bps / max(avg_spread, 1.0)
        else:
            spread_ratio = 1.0
        
        # Check depth contraction
        if self.depth_history and len(self.depth_history) >= 10:
            avg_depth = np.mean(list(self.depth_history)[-10:])
            depth_ratio = self.market_depth / max(avg_depth, 1.0)
        else:
            depth_ratio = 1.0
        
        # Check imbalance extreme
        imbalance_extreme = abs(self.imbalance) > 0.8
        
        # Score: higher spread and lower depth = higher void
        void_score = max(0.0, min(1.0, (spread_ratio / 5.0) + (1.0 - depth_ratio) + (0.3 if imbalance_extreme else 0.0)))
        
        return float(void_score)
    
    def detect_liquidity_void(self) -> Tuple[bool, Dict[str, Any]]:
        """
        Detect if market is experiencing a liquidity void (crisis condition).

        Returns:
            Tuple of (is_void, void_metrics)
        """
        metrics = {
            "spread_expansion": 1.0,
            "depth_contraction": 1.0,
            "imbalance_extreme": False,
            "void_score": 0.0,
            "void_detected": False
        }
        
        # Calculate spread expansion
        if self.spread_history and len(self.spread_history) >= 10:
            avg_spread = np.mean(list(self.spread_history)[-10:])
            if avg_spread > 0:
                metrics["spread_expansion"] = self.spread_bps / avg_spread
        
        # Calculate depth contraction
        if self.depth_history and len(self.depth_history) >= 10:
            avg_depth = np.mean(list(self.depth_history)[-10:])
            if avg_depth > 0:
                metrics["depth_contraction"] = self.market_depth / avg_depth
        
        # Check imbalance extreme
        metrics["imbalance_extreme"] = abs(self.imbalance) > 0.8
        
        # Calculate void score
        metrics["void_score"] = self.get_liquidity_void_score()
        
        # Detect void: spread > 5x normal OR depth < 0.2x normal OR high void score
        is_void = (
            metrics["spread_expansion"] > 5.0 or
            metrics["depth_contraction"] < 0.2 or
            (metrics["spread_expansion"] > 3.0 and metrics["depth_contraction"] < 0.5) or
            metrics["void_score"] > 0.7
        )
        
        metrics["void_detected"] = is_void
        
        return is_void, metrics
    
    def calculate_refill_velocity(self) -> float:
        """
        Calculate liquidity refill velocity (volume per second).

        Returns:
            Refill velocity in volume per second
        """
        if len(self.depth_history) < 10:
            return 0.0
        
        depths = list(self.depth_history)
        min_depth = min(depths)
        max_depth = max(depths)
        refill = max_depth - min_depth
        
        # Assume 1 second per sample (simplified)
        return refill / len(depths)
    
    def get_liquidity_metrics(self) -> LiquidityMetrics:
        """
        Get current liquidity metrics as a model.

        Returns:
            LiquidityMetrics object
        """
        bid_depth, ask_depth = self.get_depth_at_levels(10)
        
        return LiquidityMetrics(
            symbol=self.symbol,
            timestamp=self.timestamp or datetime.utcnow(),
            spread_bps=self.spread_bps,
            bid_depth=bid_depth,
            ask_depth=ask_depth,
            market_depth=self.market_depth,
            imbalance=self.imbalance,
            is_liquid=self.is_liquid,
            depth_sufficient_for_size=self.max_safe_position_size,
            refill_velocity=self.calculate_refill_velocity()
        )
    
    def get_snapshot(self) -> Dict[str, Any]:
        """
        Get current order book snapshot for export.

        Returns:
            Dictionary with order book data
        """
        bids = [(float(self._bids_prices[i]), float(self._bids_sizes[i])) 
                for i in range(min(10, self._bid_count))]
        asks = [(float(self._asks_prices[i]), float(self._asks_sizes[i])) 
                for i in range(min(10, self._ask_count))]
        
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "exchange_ts_ns": self.exchange_ts_ns,
            "bids": bids,
            "asks": asks,
            "mid_price": self.mid_price,
            "micro_price": self.micro_price,
            "spread_bps": self.spread_bps,
            "market_depth": self.market_depth,
            "imbalance": self.imbalance,
            "is_liquid": self.is_liquid,
            "max_safe_position_size": self.max_safe_position_size,
            "liquidity_void_score": self.get_liquidity_void_score()
        }
    
    def clear(self) -> None:
        """Clear order book state."""
        self._bids_prices.fill(0)
        self._bids_sizes.fill(0)
        self._asks_prices.fill(0)
        self._asks_sizes.fill(0)
        self._bid_count = 0
        self._ask_count = 0
        self.timestamp = None
        self.exchange_ts_ns = None
        self.depth_history.clear()
        self.spread_history.clear()
        self.imbalance_history.clear()
        self.mid_price_history.clear()
        self._micro_price = 0.0
        
        logger.debug(f"DepthBook cleared for {self.symbol}")