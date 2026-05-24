"""
Market Sentiment Proxy - Deterministic Sentiment Derivation from Market Data
CITADEL GRADE — DETERMINISTIC · REPLAY-SAFE · NO WALL-CLOCK

ANALYTICAL/NON-MONETARY BOUNDARY:
This module derives a sentiment proxy from lawful market data already flowing
through the system. It does NOT ingest news, social media, or external sentiment.
All outputs are analytical proxies, not true sentiment.

INPUT SOURCES (all source-proven from runtime):
- Order book imbalance (bid depth vs ask depth)
- Trade flow imbalance (buy volume vs sell volume over rolling window)
- Price momentum (short-term rate of change)
- Volatility regime (damping factor)
- Toxicity level (suppression factor)

OUTPUT:
- sentiment: float in [-1, 1] where positive = bullish, negative = bearish
- Designed to feed SentimentVelocityEngine.update_sentiment()

DETERMINISTIC BEHAVIOR:
- No wall-clock time
- No random number generation
- All timing uses integer nanoseconds from authoritative external sources
- Replay-safe given identical input sequences
"""

import logging
import math
from typing import Optional, Deque, Tuple
from collections import deque
from dataclasses import dataclass

from app.models.enums import RegimeType
from app.brain.toxicity_engine import ToxicityRegime

logger = logging.getLogger(__name__)

EPS = 1e-8


@dataclass
class SentimentProxyState:
    """Snapshot of sentiment proxy state for diagnostics."""
    composite_sentiment: float
    imbalance_component: float
    flow_component: float
    momentum_component: float
    regime_multiplier: float
    toxicity_multiplier: float
    timestamp_ns: int
    samples_used: int


class MarketSentimentProxy:
    """
    Derives sentiment proxy from market data.

    COMPONENTS (weighted average):
        - Order book imbalance (40%): bids vs asks depth
        - Trade flow imbalance (35%): buy vs sell volume over rolling window
        - Price momentum (25%): short-term rate of change

    MODULATORS (multiplied after weighted average):
        - Regime multiplier: trending=1.0, ranging=0.7, crisis=0.3
        - Toxicity multiplier: NORMAL=1.0, ELEVATED=0.8, TOXIC=0.5, EXTREME=0.0

    OUTPUT bounds: [-1, 1]
    """

    # Component weights
    IMBALANCE_WEIGHT = 0.40
    FLOW_WEIGHT = 0.35
    MOMENTUM_WEIGHT = 0.25

    # Rolling window sizes
    FLOW_WINDOW_SIZE = 20
    PRICE_WINDOW_SIZE = 10

    # Momentum normalization: max expected price change % per second
    MAX_MOMENTUM_PCT_PER_SEC = 0.02  # 2% per second = extreme

    def __init__(self, symbol: str):
        """
        Initialize sentiment proxy for a symbol.

        Args:
            symbol: Trading symbol
        """
        self.symbol = symbol

        # Rolling windows for flow imbalance
        self._flow_history: Deque[float] = deque(maxlen=self.FLOW_WINDOW_SIZE)
        self._buy_volume_history: Deque[float] = deque(maxlen=self.FLOW_WINDOW_SIZE)
        self._sell_volume_history: Deque[float] = deque(maxlen=self.FLOW_WINDOW_SIZE)

        # Rolling window for price momentum
        self._price_history: Deque[Tuple[float, int]] = deque(maxlen=self.PRICE_WINDOW_SIZE)

        # Current state
        self._last_order_book_imbalance: float = 0.0
        self._last_regime_multiplier: float = 1.0
        self._last_toxicity_multiplier: float = 1.0
        self._last_composite_sentiment: float = 0.0
        self._last_update_ts_ns: int = 0
        self._update_count: int = 0

        logger.info(f"MarketSentimentProxy initialized for {symbol}")

    def update_from_order_book(self, bid_depth: float, ask_depth: float, exchange_ts_ns: int) -> None:
        """
        Update order book imbalance component.

        Args:
            bid_depth: Cumulative bid depth (e.g., from depth_at_levels)
            ask_depth: Cumulative ask depth
            exchange_ts_ns: Exchange timestamp
        """
        total = bid_depth + ask_depth
        if total > EPS:
            self._last_order_book_imbalance = (bid_depth - ask_depth) / total
        else:
            self._last_order_book_imbalance = 0.0

        # Clamp to [-1, 1]
        self._last_order_book_imbalance = max(-1.0, min(1.0, self._last_order_book_imbalance))
        self._last_update_ts_ns = exchange_ts_ns

    def update_from_trade(self, buy_volume: float, sell_volume: float, exchange_ts_ns: int) -> None:
        """
        Update trade flow imbalance component.

        Args:
            buy_volume: Buy volume in this update
            sell_volume: Sell volume in this update
            exchange_ts_ns: Exchange timestamp
        """
        self._buy_volume_history.append(buy_volume)
        self._sell_volume_history.append(sell_volume)

        total_buy = sum(self._buy_volume_history)
        total_sell = sum(self._sell_volume_history)
        total = total_buy + total_sell

        if total > EPS:
            flow_imbalance = (total_buy - total_sell) / total
        else:
            flow_imbalance = 0.0

        self._flow_history.append(flow_imbalance)
        self._last_update_ts_ns = exchange_ts_ns

    def update_from_price(self, price: float, exchange_ts_ns: int) -> None:
        """
        Update price momentum component.

        Args:
            price: Current price
            exchange_ts_ns: Exchange timestamp
        """
        self._price_history.append((price, exchange_ts_ns))
        self._last_update_ts_ns = exchange_ts_ns

    def update_regime_multiplier(self, regime: RegimeType) -> None:
        """
        Update regime multiplier based on market regime.

        Args:
            regime: Current market regime
        """
        if regime in (RegimeType.TRENDING_BULL, RegimeType.TRENDING_BEAR):
            self._last_regime_multiplier = 1.0
        elif regime == RegimeType.RANGING:
            self._last_regime_multiplier = 0.7
        elif regime in (RegimeType.CRISIS, RegimeType.CRISIS_LIQUIDITY_VOID,
                        RegimeType.CRISIS_VOLATILITY_SPIKE):
            self._last_regime_multiplier = 0.3
        elif regime == RegimeType.UNKNOWN:
            self._last_regime_multiplier = 0.5
        else:
            self._last_regime_multiplier = 0.8

    def update_toxicity_multiplier(self, toxicity_regime: Optional[ToxicityRegime]) -> None:
        """
        Update toxicity multiplier based on toxicity level.

        Args:
            toxicity_regime: Current toxicity regime from ToxicityEngine
        """
        if toxicity_regime is None:
            self._last_toxicity_multiplier = 1.0
        elif toxicity_regime == ToxicityRegime.EXTREME:
            self._last_toxicity_multiplier = 0.0
        elif toxicity_regime == ToxicityRegime.TOXIC:
            self._last_toxicity_multiplier = 0.5
        elif toxicity_regime == ToxicityRegime.ELEVATED:
            self._last_toxicity_multiplier = 0.8
        else:  # NORMAL
            self._last_toxicity_multiplier = 1.0

    def _compute_imbalance_component(self) -> float:
        """Return current order book imbalance (already computed)."""
        return self._last_order_book_imbalance

    def _compute_flow_component(self) -> float:
        """Compute average flow imbalance over rolling window."""
        if not self._flow_history:
            return 0.0

        return sum(self._flow_history) / len(self._flow_history)

    def _compute_momentum_component(self) -> float:
        """
        Compute price momentum as rate of change normalized to [-1, 1].

        Momentum = (price_now - price_old) / price_old / time_delta_sec
        Normalized: 2% per second = 1.0, 0% = 0.0, -2% per second = -1.0
        """
        if len(self._price_history) < 2:
            return 0.0

        # Get earliest and latest prices with timestamps
        first_price, first_ts = self._price_history[0]
        last_price, last_ts = self._price_history[-1]

        if first_price <= EPS or last_ts <= first_ts:
            return 0.0

        # Price change percentage
        price_change_pct = (last_price - first_price) / first_price

        # Time delta in seconds
        delta_sec = (last_ts - first_ts) / 1_000_000_000.0
        if delta_sec <= EPS:
            return 0.0

        # Rate of change per second
        momentum_raw = price_change_pct / delta_sec

        # Normalize to [-1, 1] with max 2% per second
        momentum = momentum_raw / self.MAX_MOMENTUM_PCT_PER_SEC
        return max(-1.0, min(1.0, momentum))

    def _compute_composite(self) -> float:
        """
        Compute weighted composite sentiment.

        Returns:
            Raw sentiment in [-1, 1] before modulation
        """
        imbalance = self._compute_imbalance_component()
        flow = self._compute_flow_component()
        momentum = self._compute_momentum_component()

        composite = (
            imbalance * self.IMBALANCE_WEIGHT +
            flow * self.FLOW_WEIGHT +
            momentum * self.MOMENTUM_WEIGHT
        )

        # Clamp to [-1, 1]
        return max(-1.0, min(1.0, composite))

    def get_sentiment(self) -> float:
        """
        Get current sentiment proxy value.

        Returns:
            Sentiment in [-1, 1] where:
            - Positive = bullish bias from market structure
            - Negative = bearish bias from market structure
            - Zero = neutral or insufficient data
        """
        raw_sentiment = self._compute_composite()

        # Apply regime and toxicity multipliers
        modulated = raw_sentiment * self._last_regime_multiplier * self._last_toxicity_multiplier

        # Track for diagnostics
        self._last_composite_sentiment = max(-1.0, min(1.0, modulated))
        self._update_count += 1

        return self._last_composite_sentiment

    def get_state(self) -> SentimentProxyState:
        """Get current state for diagnostics."""
        return SentimentProxyState(
            composite_sentiment=self._last_composite_sentiment,
            imbalance_component=self._compute_imbalance_component(),
            flow_component=self._compute_flow_component(),
            momentum_component=self._compute_momentum_component(),
            regime_multiplier=self._last_regime_multiplier,
            toxicity_multiplier=self._last_toxicity_multiplier,
            timestamp_ns=self._last_update_ts_ns,
            samples_used=self._update_count
        )

    def reset(self) -> None:
        """Reset all state for deterministic replay."""
        self._flow_history.clear()
        self._buy_volume_history.clear()
        self._sell_volume_history.clear()
        self._price_history.clear()
        self._last_order_book_imbalance = 0.0
        self._last_regime_multiplier = 1.0
        self._last_toxicity_multiplier = 1.0
        self._last_composite_sentiment = 0.0
        self._last_update_ts_ns = 0
        self._update_count = 0
        logger.info(f"MarketSentimentProxy reset for {self.symbol}")