"""
Convexity Switch - Dynamic Momentum/Carry Strategy Switching
Dynamically switches between momentum and carry strategies based on volatility source.
When volatility is regime-transmitted (cross-asset correlation high), use momentum.
When volatility is asset-specific (correlation low), use carry/mean-reversion.
"""

import logging
import numpy as np
from typing import Optional, Dict, List, Tuple, Any
from datetime import datetime, timedelta
from collections import deque

logger = logging.getLogger(__name__)


class ConvexitySwitch:
    """
    Dynamically switches between momentum and carry strategies.
    Detects whether volatility is regime-driven (high correlation) or asset-specific (low correlation).
    """

    def __init__(
        self,
        momentum_threshold: float = 0.7,
        carry_threshold: float = 0.3,
        correlation_window: int = 20,
        lookback_days: int = 5,
        smoothing_window: int = 5
    ):
        """
        Initialize convexity switch.

        Args:
            momentum_threshold: Correlation threshold for momentum regime
            carry_threshold: Correlation threshold for carry regime
            correlation_window: Window for correlation calculation
            lookback_days: Days of data to consider
            smoothing_window: Window for regime smoothing
        """
        self.momentum_threshold = momentum_threshold
        self.carry_threshold = carry_threshold
        self.correlation_window = correlation_window
        self.lookback_days = lookback_days
        self.smoothing_window = smoothing_window

        # Historical data per symbol
        self._returns_history: Dict[str, deque] = {}
        self._volatility_history: Dict[str, deque] = {}
        self._cross_asset_corr: Dict[str, deque] = {}

        # Regime history
        self._regime_history: Dict[str, deque] = {}
        self._current_regime: Dict[str, str] = {}
        self._regime_confidence: Dict[str, float] = {}

        # Benchmark assets for correlation
        self._benchmark_returns: deque = deque(maxlen=1000)

        logger.info(f"ConvexitySwitch initialized: momentum_threshold={momentum_threshold}, carry={carry_threshold}")

    def update(self, symbol: str, returns: float, benchmark_returns: Optional[float] = None) -> str:
        """
        Update with new return data.

        Args:
            symbol: Trading symbol
            returns: Period return for the asset
            benchmark_returns: Period return for benchmark (e.g., SPY)

        Returns:
            Current regime: "MOMENTUM", "CARRY", or "MIXED"
        """
        # Initialize for new symbol
        self._init_symbol_history(symbol)

        # Add to history
        self._returns_history[symbol].append(returns)

        # Update benchmark returns if provided
        if benchmark_returns is not None:
            self._benchmark_returns.append(benchmark_returns)

        # Calculate rolling volatility
        if len(self._returns_history[symbol]) >= self.correlation_window:
            recent_returns = list(self._returns_history[symbol])[-self.correlation_window:]
            volatility = np.std(recent_returns)
            self._volatility_history[symbol].append(volatility)

        # Calculate cross-asset correlation
        if len(self._returns_history[symbol]) >= self.correlation_window and len(self._benchmark_returns) >= self.correlation_window:
            asset_returns = list(self._returns_history[symbol])[-self.correlation_window:]
            benchmark = list(self._benchmark_returns)[-self.correlation_window:]

            correlation = np.corrcoef(asset_returns, benchmark)[0, 1]
            if not np.isnan(correlation):
                self._cross_asset_corr[symbol].append(correlation)

        # Determine regime
        regime = self._determine_regime(symbol)
        confidence = self._calculate_confidence(symbol, regime)

        # Store
        self._regime_history[symbol].append(regime)
        self._current_regime[symbol] = regime
        self._regime_confidence[symbol] = confidence

        return regime

    def _init_symbol_history(self, symbol: str) -> None:
        """Initialize history containers for a symbol."""
        if symbol not in self._returns_history:
            self._returns_history[symbol] = deque(maxlen=1000)
        if symbol not in self._volatility_history:
            self._volatility_history[symbol] = deque(maxlen=1000)
        if symbol not in self._cross_asset_corr:
            self._cross_asset_corr[symbol] = deque(maxlen=1000)
        if symbol not in self._regime_history:
            self._regime_history[symbol] = deque(maxlen=self.smoothing_window * 2)

    def _determine_regime(self, symbol: str) -> str:
        """
        Determine current regime based on correlation.

        Args:
            symbol: Trading symbol

        Returns:
            "MOMENTUM", "CARRY", or "MIXED"
        """
        if symbol not in self._cross_asset_corr or len(self._cross_asset_corr[symbol]) < self.correlation_window:
            return "MIXED"

        # Get recent correlation
        recent_corr = list(self._cross_asset_corr[symbol])[-self.correlation_window:]
        avg_correlation = np.mean(recent_corr)

        if avg_correlation > self.momentum_threshold:
            return "MOMENTUM"
        elif avg_correlation < self.carry_threshold:
            return "CARRY"
        else:
            return "MIXED"

    def _calculate_confidence(self, symbol: str, regime: str) -> float:
        """
        Calculate confidence in regime detection.

        Args:
            symbol: Trading symbol
            regime: Current regime

        Returns:
            Confidence score (0-1)
        """
        if symbol not in self._cross_asset_corr or len(self._cross_asset_corr[symbol]) < self.correlation_window:
            return 0.5

        # Get recent correlation
        recent_corr = list(self._cross_asset_corr[symbol])[-self.correlation_window:]
        avg_correlation = np.mean(recent_corr)
        std_correlation = np.std(recent_corr)

        # Confidence based on distance from threshold
        if regime == "MOMENTUM":
            distance = (avg_correlation - self.momentum_threshold) / (1 - self.momentum_threshold)
        elif regime == "CARRY":
            distance = (self.carry_threshold - avg_correlation) / self.carry_threshold
        else:
            # For mixed, confidence is lower
            distance = 0.5 - abs(avg_correlation - 0.5) * 2

        # Factor in stability (low standard deviation)
        stability = 1.0 - min(1.0, std_correlation)

        confidence = (max(0.0, min(1.0, distance)) * 0.7 + stability * 0.3)
        return min(1.0, max(0.0, confidence))

    def get_current_regime(self, symbol: str) -> str:
        """
        Get current regime for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            "MOMENTUM", "CARRY", or "MIXED"
        """
        if symbol not in self._current_regime:
            return "MIXED"
        return self._current_regime[symbol]

    def get_confidence(self, symbol: str) -> float:
        """
        Get confidence in current regime.

        Args:
            symbol: Trading symbol

        Returns:
            Confidence score (0-1)
        """
        return self._regime_confidence.get(symbol, 0.0)

    def get_correlation_history(self, symbol: str, window: int = 50) -> List[float]:
        """
        Get correlation history.

        Args:
            symbol: Trading symbol
            window: Number of readings to return

        Returns:
            List of correlation values
        """
        if symbol not in self._cross_asset_corr:
            return []
        return list(self._cross_asset_corr[symbol])[-window:]

    def get_volatility_history(self, symbol: str, window: int = 50) -> List[float]:
        """
        Get volatility history.

        Args:
            symbol: Trading symbol
            window: Number of readings to return

        Returns:
            List of volatility values
        """
        if symbol not in self._volatility_history:
            return []
        return list(self._volatility_history[symbol])[-window:]

    def get_regime_history(self, symbol: str, window: int = 20) -> List[str]:
        """
        Get recent regime history.

        Args:
            symbol: Trading symbol
            window: Number of readings to return

        Returns:
            List of regimes
        """
        if symbol not in self._regime_history:
            return []
        return list(self._regime_history[symbol])[-window:]

    def get_smoothed_regime(self, symbol: str) -> str:
        """
        Get smoothed regime using majority vote.

        Args:
            symbol: Trading symbol

        Returns:
            Smoothed regime
        """
        if symbol not in self._regime_history or len(self._regime_history[symbol]) < self.smoothing_window:
            return self.get_current_regime(symbol)

        recent = list(self._regime_history[symbol])[-self.smoothing_window:]
        counts = {}
        for r in recent:
            counts[r] = counts.get(r, 0) + 1

        # Return most common
        return max(counts, key=counts.get)

    def get_strategy_weight(self, symbol: str) -> Dict[str, float]:
        """
        Get weight for momentum vs carry strategies.

        Args:
            symbol: Trading symbol

        Returns:
            Dictionary with momentum_weight and carry_weight
        """
        regime = self.get_current_regime(symbol)
        confidence = self.get_confidence(symbol)

        if regime == "MOMENTUM":
            return {
                "momentum_weight": 0.8 + (confidence * 0.2),
                "carry_weight": 0.2 - (confidence * 0.15),
                "regime": "MOMENTUM"
            }
        elif regime == "CARRY":
            return {
                "momentum_weight": 0.2 - (confidence * 0.15),
                "carry_weight": 0.8 + (confidence * 0.2),
                "regime": "CARRY"
            }
        else:
            return {
                "momentum_weight": 0.5,
                "carry_weight": 0.5,
                "regime": "MIXED"
            }

    def update_benchmark(self, returns: float) -> None:
        """
        Update benchmark returns (e.g., SPY).

        Args:
            returns: Period return for benchmark
        """
        self._benchmark_returns.append(returns)

    def get_market_regime(self) -> str:
        """
        Get overall market regime based on benchmark correlation.

        Returns:
            "MOMENTUM", "CARRY", or "MIXED"
        """
        if len(self._benchmark_returns) < self.correlation_window:
            return "MIXED"

        # Use autocorrelation of benchmark
        benchmark = list(self._benchmark_returns)[-self.correlation_window:]
        autocorr = np.corrcoef(benchmark[:-1], benchmark[1:])[0, 1] if len(benchmark) > 1 else 0.0

        if not np.isnan(autocorr):
            if autocorr > 0.3:
                return "MOMENTUM"
            elif autocorr < -0.1:
                return "CARRY"

        return "MIXED"

    def reset(self, symbol: str) -> None:
        """
        Reset history for a symbol.

        Args:
            symbol: Trading symbol
        """
        if symbol in self._returns_history:
            self._returns_history[symbol].clear()
        if symbol in self._volatility_history:
            self._volatility_history[symbol].clear()
        if symbol in self._cross_asset_corr:
            self._cross_asset_corr[symbol].clear()
        if symbol in self._regime_history:
            self._regime_history[symbol].clear()
        if symbol in self._current_regime:
            del self._current_regime[symbol]
        if symbol in self._regime_confidence:
            del self._regime_confidence[symbol]

    def get_stats(self, symbol: str) -> Dict[str, Any]:
        """
        Get comprehensive statistics for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Dictionary with all stats
        """
        regime = self.get_current_regime(symbol)
        weights = self.get_strategy_weight(symbol)

        return {
            "symbol": symbol,
            "current_regime": regime,
            "confidence": self.get_confidence(symbol),
            "smoothed_regime": self.get_smoothed_regime(symbol),
            "momentum_weight": weights["momentum_weight"],
            "carry_weight": weights["carry_weight"],
            "avg_correlation": np.mean(self.get_correlation_history(symbol, 20)) if self.get_correlation_history(symbol, 20) else None,
            "regime_history": self.get_regime_history(symbol, 10),
            "market_regime": self.get_market_regime()
        }