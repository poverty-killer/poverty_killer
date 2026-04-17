"""
Physical Validator - Exchange Latency and Price Impact Verification
RESTORED: Deterministic, replay-safe, with fusion compatibility bridge.

Tracks exchange latency, network RTT, and price impact correlation.
Identifies toxic flow where latency exceeds expected impact thresholds.
Used to validate execution quality and detect market manipulation.

PRESERVE-FIRST RESTORATION:
- Baseline shape preserved with deterministic physical-data repair
- Random simulation replaced with fixed deterministic exchange constants
- Added to_fusion_dict() for signal_fusion.py compatibility
- Original record_latency signature preserved (optional timestamp_ns)
"""

import logging
from typing import Optional, Dict, List, Any
from datetime import datetime
from collections import deque

import numpy as np

from app.models import PhysicalVerification
from app.utils.time_utils import now_ns

logger = logging.getLogger(__name__)


class PhysicalValidator:
    """
    Tracks exchange latency and price impact.
    Identifies toxic flow where latency is high relative to expected impact.
    Used for execution quality monitoring and regime detection.
    """

    def __init__(
        self,
        latency_threshold_ms: float = 100.0,
        impact_threshold_bps: float = 10.0,
        toxicity_window: int = 20,
        baseline_window: int = 100
    ):
        """
        Initialize physical validator.

        Args:
            latency_threshold_ms: Latency threshold for toxicity detection (ms)
            impact_threshold_bps: Impact threshold for toxicity detection (bps)
            toxicity_window: Window for toxicity detection
            baseline_window: Window for baseline calculations
        """
        self.latency_threshold_ms = latency_threshold_ms
        self.impact_threshold_bps = impact_threshold_bps
        self.toxicity_window = toxicity_window
        self.baseline_window = baseline_window

        # Historical data per exchange
        self._latency_history: Dict[str, deque] = {}
        self._impact_history: Dict[str, deque] = {}
        self._order_size_history: Dict[str, deque] = {}
        self._toxicity_history: Dict[str, deque] = {}

        # Physical infrastructure data (deterministic exchange metadata placeholders)
        self._mining_hashrate: Dict[str, float] = {}
        self._datacenter_power: Dict[str, float] = {}
        self._cable_latency: Dict[str, float] = {}

        # Last verification results
        self._last_verification: Dict[str, PhysicalVerification] = {}

        logger.info(f"PhysicalValidator initialized: latency_threshold={latency_threshold_ms}ms (deterministic mode)")

    # =========================================================================
    # CORE RECORDING METHODS (Preserved baseline shape with deterministic repair)
    # =========================================================================

    def record_latency(
        self,
        symbol: str,
        exchange: str,
        latency_ms: float,
        order_size: float,
        price_impact_bps: float,
        timestamp_ns: Optional[int] = None,
    ) -> PhysicalVerification:
        """
        Record a latency measurement.

        Args:
            symbol: Trading symbol
            exchange: Exchange name
            latency_ms: Order-to-fill latency in milliseconds
            order_size: Order size in USD
            price_impact_bps: Actual price impact in basis points
            timestamp_ns: Optional authoritative timestamp for deterministic replay

        Returns:
            PhysicalVerification object (primary return type)
            
        Note: Fusion consumers needing dict format should use to_fusion_dict(exchange)
        """
        # If timestamp_ns provided, use deterministic path
        if timestamp_ns is not None:
            return self._record_latency_deterministic(
                symbol, exchange, latency_ms, order_size, price_impact_bps, timestamp_ns
            )
        
        # Original path (preserved baseline shape)
        return self._record_latency_original(
            symbol, exchange, latency_ms, order_size, price_impact_bps
        )
    
    def _record_latency_original(
        self,
        symbol: str,
        exchange: str,
        latency_ms: float,
        order_size: float,
        price_impact_bps: float,
    ) -> PhysicalVerification:
        """
        Original record_latency implementation.
        Baseline shape preserved. Physical-data behavior repaired to deterministic.
        """
        # Initialize history for this exchange
        self._init_exchange_history(exchange)

        # Add to history
        self._latency_history[exchange].append(latency_ms)
        self._impact_history[exchange].append(price_impact_bps)
        self._order_size_history[exchange].append(order_size)

        # Calculate expected impact based on order size and liquidity
        expected_impact = self._calculate_expected_impact(exchange, order_size)

        # Calculate latency-impact ratio
        latency_impact_ratio = latency_ms / (abs(price_impact_bps) + 1.0)

        # Determine toxicity
        is_toxic = self._detect_toxicity(exchange, latency_ms, price_impact_bps)

        # Update toxicity history
        self._toxicity_history[exchange].append(1 if is_toxic else 0)

        # Get deterministic physical infrastructure data (fixed constants, no random)
        physical_data = self._get_deterministic_physical_data(exchange)

        # Create verification record
        verification = PhysicalVerification(
            symbol=symbol,
            exchange_ts_ns=now_ns(),
            exchange=exchange,
            exchange_latency_ns=int(latency_ms * 1_000_000),
            network_rtt_ns=int(latency_ms * 0.6 * 1_000_000),
            order_size_usd=order_size,
            price_impact_bps=price_impact_bps,
            expected_impact_bps=expected_impact,
            latency_impact_ratio=latency_impact_ratio,
            is_toxic=is_toxic,
            mining_hashrate_th=physical_data["mining_hashrate"],
            datacenter_power_mw=physical_data["datacenter_power_mw"],
            undersea_cable_latency_ms=physical_data["cable_latency_ms"]
        )

        self._last_verification[exchange] = verification
        return verification
    
    def _record_latency_deterministic(
        self,
        symbol: str,
        exchange: str,
        latency_ms: float,
        order_size: float,
        price_impact_bps: float,
        timestamp_ns: int,
    ) -> PhysicalVerification:
        """
        Deterministic record_latency path for replay safety.
        Same as original but with integer-arithmetic timestamp conversion.
        """
        # Initialize history for this exchange
        self._init_exchange_history(exchange)

        # Add to history
        self._latency_history[exchange].append(latency_ms)
        self._impact_history[exchange].append(price_impact_bps)
        self._order_size_history[exchange].append(order_size)

        # Calculate expected impact based on order size and liquidity
        expected_impact = self._calculate_expected_impact(exchange, order_size)

        # Calculate latency-impact ratio
        latency_impact_ratio = latency_ms / (abs(price_impact_bps) + 1.0)

        # Determine toxicity
        is_toxic = self._detect_toxicity(exchange, latency_ms, price_impact_bps)

        # Update toxicity history
        self._toxicity_history[exchange].append(1 if is_toxic else 0)

        # Get deterministic physical infrastructure data (fixed constants, no random)
        physical_data = self._get_deterministic_physical_data(exchange)

        verification = PhysicalVerification(
            symbol=symbol,
            exchange_ts_ns=timestamp_ns,
            exchange=exchange,
            exchange_latency_ns=int(latency_ms * 1_000_000),
            network_rtt_ns=int(latency_ms * 0.6 * 1_000_000),
            order_size_usd=order_size,
            price_impact_bps=price_impact_bps,
            expected_impact_bps=expected_impact,
            latency_impact_ratio=latency_impact_ratio,
            is_toxic=is_toxic,
            mining_hashrate_th=physical_data["mining_hashrate"],
            datacenter_power_mw=physical_data["datacenter_power_mw"],
            undersea_cable_latency_ms=physical_data["cable_latency_ms"]
        )

        self._last_verification[exchange] = verification
        return verification

    def _init_exchange_history(self, exchange: str) -> None:
        """Initialize history containers for an exchange."""
        if exchange not in self._latency_history:
            self._latency_history[exchange] = deque(maxlen=1000)
        if exchange not in self._impact_history:
            self._impact_history[exchange] = deque(maxlen=1000)
        if exchange not in self._order_size_history:
            self._order_size_history[exchange] = deque(maxlen=1000)
        if exchange not in self._toxicity_history:
            self._toxicity_history[exchange] = deque(maxlen=1000)

    def _calculate_expected_impact(self, exchange: str, order_size: float) -> float:
        """
        Calculate expected price impact based on historical data.

        Args:
            exchange: Exchange name
            order_size: Order size in USD

        Returns:
            Expected impact in basis points
        """
        if exchange not in self._impact_history or len(self._impact_history[exchange]) < self.baseline_window:
            # Default impact estimation
            return min(50.0, order_size / 1000000 * 100)

        # Use historical impact for similar order sizes
        historical_impacts = list(self._impact_history[exchange])
        historical_sizes = list(self._order_size_history[exchange])

        if not historical_impacts:
            return 10.0

        # Find similar orders
        similar_impacts = []
        for size, impact in zip(historical_sizes[-self.baseline_window:], historical_impacts[-self.baseline_window:]):
            if 0.5 * order_size <= size <= 2 * order_size:
                similar_impacts.append(impact)

        if similar_impacts:
            return np.mean(similar_impacts)
        else:
            return np.mean(historical_impacts)

    def _detect_toxicity(self, exchange: str, latency_ms: float, price_impact_bps: float) -> bool:
        """
        Detect if trade was toxic (adverse selection).

        Args:
            exchange: Exchange name
            latency_ms: Trade latency in ms
            price_impact_bps: Price impact in bps

        Returns:
            True if trade was toxic
        """
        # Get baseline for this exchange
        if exchange not in self._latency_history or len(self._latency_history[exchange]) < self.toxicity_window:
            # Not enough data, use thresholds
            return latency_ms > self.latency_threshold_ms and abs(price_impact_bps) > self.impact_threshold_bps

        # Calculate recent averages
        recent_latency = list(self._latency_history[exchange])[-self.toxicity_window:]
        recent_impact = list(self._impact_history[exchange])[-self.toxicity_window:]

        avg_latency = np.mean(recent_latency)
        avg_impact = np.mean(recent_impact)

        # Detect toxicity: significantly worse than recent average
        latency_toxic = latency_ms > avg_latency * 1.5
        impact_toxic = abs(price_impact_bps) > abs(avg_impact) * 2.0

        return latency_toxic and impact_toxic

    def _get_deterministic_physical_data(self, exchange: str) -> Dict[str, Any]:
        """
        Get deterministic physical infrastructure data.
        
        Deterministic exchange metadata placeholders preserved for compatibility.
        Fixed constants per exchange. No randomness. Replay-safe.
        
        Args:
            exchange: Exchange name
            
        Returns:
            Physical data dictionary with deterministic values
        """
        # Exchange-specific baseline data (fixed constants, no randomness)
        exchange_data = {
            "kraken": {"mining": 15.0, "power": 120.0, "cable": 85.0},
            "alpaca": {"mining": 0.0, "power": 50.0, "cable": 45.0},
            "ibkr": {"mining": 0.0, "power": 80.0, "cable": 55.0},
        }

        base = exchange_data.get(exchange.lower(), {"mining": 10.0, "power": 100.0, "cable": 70.0})
        
        return {
            "mining_hashrate": base["mining"],
            "datacenter_power_mw": base["power"],
            "cable_latency_ms": base["cable"],
        }

    # =========================================================================
    # FUSION COMPATIBILITY BRIDGE (Preserve-first addition)
    # =========================================================================
    
    def to_fusion_dict(self, exchange: str) -> Dict[str, float]:
        """
        Convert exchange health to FusionDecision-compatible dict.
        
        signal_fusion.py expects dict with "health_score" key.
        This is a compatibility bridge for fusion consumers.
        Primary return type remains PhysicalVerification via record_latency().
        
        Args:
            exchange: Exchange name
            
        Returns:
            Dict with "health_score" key (0-1 scale)
        """
        health = self.get_exchange_health(exchange)
        return {"health_score": health.get("health_score", 0.5)}
    
    def get_fusion_health_score(self, exchange: str) -> float:
        """
        Get health score for fusion consumption.
        
        Args:
            exchange: Exchange name
            
        Returns:
            Float health score in [0, 1]
        """
        health = self.get_exchange_health(exchange)
        return health.get("health_score", 0.5)

    # =========================================================================
    # PRESERVED ANALYTICS METHODS (Unchanged from baseline)
    # =========================================================================

    def get_current(self, exchange: str) -> Optional[PhysicalVerification]:
        """
        Get current verification for an exchange.

        Args:
            exchange: Exchange name

        Returns:
            Current PhysicalVerification or None
        """
        return self._last_verification.get(exchange)

    def get_latency_stats(self, exchange: str) -> Dict[str, float]:
        """
        Get latency statistics for an exchange.

        Args:
            exchange: Exchange name

        Returns:
            Dictionary with latency stats
        """
        if exchange not in self._latency_history or not self._latency_history[exchange]:
            return {"avg_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0, "std_ms": 0.0}

        latencies = list(self._latency_history[exchange])
        return {
            "avg_ms": np.mean(latencies),
            "p95_ms": np.percentile(latencies, 95),
            "p99_ms": np.percentile(latencies, 99),
            "std_ms": np.std(latencies),
            "samples": len(latencies)
        }

    def get_toxicity_rate(self, exchange: str, window: int = 100) -> float:
        """
        Get toxicity rate for an exchange.

        Args:
            exchange: Exchange name
            window: Number of trades to consider

        Returns:
            Toxicity rate (0-1)
        """
        if exchange not in self._toxicity_history or not self._toxicity_history[exchange]:
            return 0.0

        toxic_trades = list(self._toxicity_history[exchange])[-window:]
        if not toxic_trades:
            return 0.0

        return sum(toxic_trades) / len(toxic_trades)

    def get_impact_analysis(self, exchange: str) -> Dict[str, float]:
        """
        Get price impact analysis.

        Args:
            exchange: Exchange name

        Returns:
            Dictionary with impact analysis
        """
        if exchange not in self._impact_history or not self._impact_history[exchange]:
            return {"avg_impact_bps": 0.0, "expected_impact_bps": 0.0, "slippage_ratio": 0.0}

        impacts = list(self._impact_history[exchange])
        expected_impacts = []

        for i, size in enumerate(list(self._order_size_history[exchange])[-len(impacts):]):
            expected_impacts.append(self._calculate_expected_impact(exchange, size))

        avg_impact = np.mean(impacts)
        avg_expected = np.mean(expected_impacts) if expected_impacts else 0.0

        return {
            "avg_impact_bps": avg_impact,
            "expected_impact_bps": avg_expected,
            "slippage_ratio": avg_impact / (avg_expected + 1.0) if avg_expected > 0 else 1.0,
            "samples": len(impacts)
        }

    def get_exchange_health(self, exchange: str) -> Dict[str, Any]:
        """
        Get overall exchange health score.

        Args:
            exchange: Exchange name

        Returns:
            Dictionary with health metrics
        """
        latency_stats = self.get_latency_stats(exchange)
        toxicity_rate = self.get_toxicity_rate(exchange)
        impact_analysis = self.get_impact_analysis(exchange)

        # Calculate health score (0-1, higher is better)
        latency_score = 1.0 - min(1.0, latency_stats.get("avg_ms", 0) / 200.0)
        toxicity_score = 1.0 - toxicity_rate
        slippage_score = 1.0 - min(1.0, impact_analysis.get("slippage_ratio", 1.0) - 1.0)

        health_score = (latency_score * 0.4 + toxicity_score * 0.4 + slippage_score * 0.2)

        return {
            "exchange": exchange,
            "health_score": health_score,
            "latency_score": latency_score,
            "toxicity_score": toxicity_score,
            "slippage_score": slippage_score,
            "avg_latency_ms": latency_stats.get("avg_ms", 0),
            "toxicity_rate": toxicity_rate,
            "slippage_ratio": impact_analysis.get("slippage_ratio", 1.0),
            "is_healthy": health_score > 0.7
        }

    def get_best_exchange(self, symbols: List[str]) -> str:
        """
        Get best exchange for trading based on health scores.

        Args:
            symbols: List of symbols (used to determine exchanges)

        Returns:
            Best exchange name
        """
        # Determine exchanges from symbols (simplified)
        exchanges = ["kraken", "alpaca", "ibkr"]
        best_score = -1.0
        best_exchange = exchanges[0]

        for exchange in exchanges:
            health = self.get_exchange_health(exchange)
            if health["health_score"] > best_score:
                best_score = health["health_score"]
                best_exchange = exchange

        return best_exchange

    def reset(self, exchange: str) -> None:
        """
        Reset history for an exchange.

        Args:
            exchange: Exchange name
        """
        if exchange in self._latency_history:
            self._latency_history[exchange].clear()
        if exchange in self._impact_history:
            self._impact_history[exchange].clear()
        if exchange in self._order_size_history:
            self._order_size_history[exchange].clear()
        if exchange in self._toxicity_history:
            self._toxicity_history[exchange].clear()
        if exchange in self._last_verification:
            del self._last_verification[exchange]

    def get_stats(self, exchange: str) -> Dict[str, Any]:
        """
        Get comprehensive statistics for an exchange.

        Args:
            exchange: Exchange name

        Returns:
            Dictionary with all stats
        """
        return {
            "exchange": exchange,
            "latency_stats": self.get_latency_stats(exchange),
            "toxicity_rate": self.get_toxicity_rate(exchange),
            "impact_analysis": self.get_impact_analysis(exchange),
            "health": self.get_exchange_health(exchange),
            "has_data": exchange in self._latency_history and len(self._latency_history.get(exchange, [])) > 0
        }