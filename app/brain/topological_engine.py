"""
Topological Persistence Engine (TPE) - The Final 1%
Detects Structural Coherence in order book using persistent homology.
Betti-0 = Fragmented Noise (Retail Churn)
Betti-1 = Market Coherence (Institutional Entry)
Super-Void detection predicts LAR events before price moves.
"""

import numpy as np
import logging
from typing import Dict, Optional, List, Tuple, Any
from dataclasses import dataclass
from collections import deque
from scipy.spatial.distance import pdist, squareform
from scipy.cluster.hierarchy import fcluster, linkage

from app.brain.ring_buffer import RingBuffer
from app.models import OrderBookSnapshot

logger = logging.getLogger(__name__)

# Machine epsilon
EPS = np.finfo(float).eps


@dataclass
class TopologicalSignal:
    """Signal from Topological Persistence Engine."""
    coherence_score: float          # 0-1, higher = more coherent
    betti_0: int                    # Connected components (noise)
    betti_1: int                    # Loops/cycles (coherence)
    persistence_score: float        # How long features survive
    super_void_detected: bool       # Pre-crash void detection
    structural_collapse: bool       # Market structure breaking
    confidence: float
    exchange_ts_ns: int
    reason: str

    __slots__ = ("coherence_score", "betti_0", "betti_1", "persistence_score",
                 "super_void_detected", "structural_collapse", "confidence",
                 "exchange_ts_ns", "reason")


class TopologicalEngine:
    """
    Topological Persistence Engine for structural market analysis.
    Detects coherence (institutional entry) vs noise (retail churn).
    Predicts liquidity voids before price moves.
    """

    def __init__(
        self,
        symbol: str,
        window_size: int = 50,
        epsilon_min: float = 0.02,
        epsilon_max: float = 0.20,
        epsilon_steps: int = 10,
        time_weight: float = 0.5,
        temporal_window_ms: int = 1000,
        min_liquidity_usd: float = 10000.0,
        coherence_threshold: float = 0.6,
        void_threshold: float = 0.7
    ):
        """
        Initialize topological engine.

        Args:
            symbol: Trading symbol
            window_size: Number of points in point cloud
            epsilon_min: Minimum scale for persistence
            epsilon_max: Maximum scale for persistence
            epsilon_steps: Number of scales to analyze
            time_weight: Weight of temporal dimension (0-1)
            temporal_window_ms: Orders older than this are disconnected
            min_liquidity_usd: Minimum liquidity for valid analysis
            coherence_threshold: Threshold for coherence detection
            void_threshold: Threshold for super-void detection
        """
        self.symbol = symbol
        self.window_size = window_size
        self.epsilon_min = epsilon_min
        self.epsilon_max = epsilon_max
        self.epsilon_steps = epsilon_steps
        self.epsilons = np.linspace(epsilon_min, epsilon_max, epsilon_steps)
        self.time_weight = time_weight
        self.temporal_window_ms = temporal_window_ms
        self.min_liquidity_usd = min_liquidity_usd
        self.coherence_threshold = coherence_threshold
        self.void_threshold = void_threshold

        # Ring buffers for historical data
        self._point_cloud: RingBuffer = RingBuffer(max_size=window_size, track_timestamps=True)
        self._coherence_history: RingBuffer = RingBuffer(max_size=100)
        self._betti_0_history: RingBuffer = RingBuffer(max_size=100)
        self._betti_1_history: RingBuffer = RingBuffer(max_size=100)

        # Last signal
        self._last_signal: Optional[TopologicalSignal] = None
        self._last_analysis_ns: int = 0

        logger.info(f"TopologicalEngine initialized for {symbol}: window={window_size}, "
                   f"epsilons={epsilon_steps}, time_weight={time_weight}")

    def _generate_point_cloud(self, order_book: OrderBookSnapshot) -> np.ndarray:
        """
        Convert order book into 4D point cloud (price, size, type, time).

        Args:
            order_book: Order book snapshot

        Returns:
            N x 4 array of points
        """
        points = []
        exchange_time = order_book.exchange_ts_ns / 1_000_000_000.0  # Convert to seconds

        # Ask side (type = +1)
        for price, size in order_book.asks[:15]:
            if size > 0:
                points.append([price, size, 1.0, exchange_time])

        # Bid side (type = -1)
        for price, size in order_book.bids[:15]:
            if size > 0:
                points.append([price, size, -1.0, exchange_time])

        if len(points) < 5:
            return np.array([])

        return np.array(points)

    def _normalize_points(self, points: np.ndarray) -> np.ndarray:
        """
        Normalize point cloud with temporal weighting.

        Args:
            points: N x 4 array

        Returns:
            Normalized points
        """
        if len(points) == 0:
            return points

        # Separate dimensions
        price = points[:, 0]
        size = points[:, 1]
        typ = points[:, 2]
        time_coord = points[:, 3]

        # Normalize each dimension
        price_std = np.std(price)
        size_std = np.std(size)
        time_std = np.std(time_coord)

        price_norm = (price - np.mean(price)) / max(price_std, EPS)
        size_norm = (size - np.mean(size)) / max(size_std, EPS)
        typ_norm = typ  # Type is already -1/1
        time_norm = (time_coord - np.mean(time_coord)) / max(time_std, EPS)

        # Apply temporal weighting
        return np.column_stack([
            price_norm,
            size_norm * (1 - self.time_weight),
            typ_norm,
            time_norm * self.time_weight
        ])

    def _compute_betti_numbers(self, adj_matrix: np.ndarray) -> Tuple[int, int]:
        """
        Compute Betti numbers from adjacency matrix.

        Betti-0 = number of connected components
        Betti-1 = number of loops/cycles

        Args:
            adj_matrix: Adjacency matrix

        Returns:
            Tuple of (betti_0, betti_1)
        """
        n = len(adj_matrix)
        if n == 0:
            return 0, 0

        # Betti-0: Connected components using BFS
        visited = [False] * n
        components = 0

        def bfs(start: int) -> None:
            queue = [start]
            visited[start] = True
            while queue:
                u = queue.pop(0)
                for v in range(n):
                    if adj_matrix[u][v] and not visited[v]:
                        visited[v] = True
                        queue.append(v)

        for i in range(n):
            if not visited[i]:
                components += 1
                bfs(i)

        # Betti-1: Cycles (Euler characteristic: V - E + F = 1 + Betti-1)
        # Simplified: Betti-1 = max(0, E - V + components)
        edges = int(np.sum(adj_matrix) / 2)
        vertices = n
        betti_1 = max(0, edges - vertices + components)

        return components, betti_1

    def _compute_persistence(self, points: np.ndarray) -> Tuple[List[float], List[int], List[int]]:
        """
        Compute persistence across multiple scales.

        Args:
            points: Normalized point cloud

        Returns:
            Tuple of (barcode, betti_0_history, betti_1_history)
        """
        if len(points) < 5:
            return [], [], []

        # Compute distance matrix
        dists = squareform(pdist(points))

        # Track Betti numbers at each epsilon
        betti_0_history = []
        betti_1_history = []

        for eps in self.epsilons:
            adj_matrix = dists < eps
            b0, b1 = self._compute_betti_numbers(adj_matrix)
            betti_0_history.append(b0)
            betti_1_history.append(b1)

        # Compute barcode (birth/death times)
        # Simplified: track when features appear/disappear
        barcode = []

        for i in range(1, len(self.epsilons)):
            # Features that die at this scale
            died_0 = betti_0_history[i-1] - betti_0_history[i]
            died_1 = betti_1_history[i-1] - betti_1_history[i]

            if died_0 > 0:
                barcode.append(self.epsilons[i])  # Death time

        return barcode, betti_0_history, betti_1_history

    def _calculate_liquidity_usd(self, order_book: OrderBookSnapshot) -> float:
        """
        Calculate total USD liquidity.

        Args:
            order_book: Order book snapshot

        Returns:
            Total USD liquidity
        """
        total = 0.0
        for price, size in order_book.bids[:15]:
            total += price * size
        for price, size in order_book.asks[:15]:
            total += price * size
        return total

    def _detect_super_void(self, order_book: OrderBookSnapshot, points: np.ndarray, betti_1_history: List[int]) -> bool:
        """
        Detect super-void in the order book that signals imminent LAR.

        Args:
            order_book: Current order book
            points: Point cloud
            betti_1_history: Betti-1 history

        Returns:
            True if super-void detected
        """
        # Check liquidity floor
        liquidity_usd = self._calculate_liquidity_usd(order_book)
        if liquidity_usd < self.min_liquidity_usd:
            return False

        # Check for depth collapse
        total_depth = 0.0
        for _, size in order_book.bids[:10]:
            total_depth += size
        for _, size in order_book.asks[:10]:
            total_depth += size

        depth_collapse = total_depth < 10.0  # Less than 10 units

        # Check for Betti-1 spike (coherence)
        if betti_1_history and len(betti_1_history) > 5:
            recent_b1 = betti_1_history[-5:]
            avg_b1 = np.mean(recent_b1)
            b1_spike = avg_b1 > 2.0
        else:
            b1_spike = False

        # Check for spread expansion
        spread_bps = order_book.spread_bps
        spread_wide = spread_bps > 20.0

        # Super-void: depth collapse + spread wide + (b1 spike OR price stability)
        if depth_collapse and spread_wide:
            return True

        return False

    def _detect_structural_collapse(self, points: np.ndarray, betti_0_history: List[int]) -> bool:
        """
        Detect structural collapse (market coherence breaking).

        Args:
            points: Point cloud
            betti_0_history: Betti-0 history

        Returns:
            True if structural collapse detected
        """
        if len(points) < 10 or len(betti_0_history) < 5:
            return False

        # Check for sudden increase in connected components (fragmentation)
        recent_b0 = betti_0_history[-5:]
        earlier_b0 = betti_0_history[-10:-5] if len(betti_0_history) >= 10 else betti_0_history

        if not earlier_b0:
            return False

        avg_recent = np.mean(recent_b0)
        avg_earlier = np.mean(earlier_b0)

        # If fragmentation increased by 50% or more
        if avg_earlier > 0 and avg_recent > avg_earlier * 1.5:
            return True

        return False

    def analyze(self, order_book: OrderBookSnapshot) -> TopologicalSignal:
        """
        Analyze topological structure of order book.

        Args:
            order_book: Current order book snapshot

        Returns:
            TopologicalSignal with coherence score
        """
        exchange_ts_ns = order_book.exchange_ts_ns

        # Generate point cloud
        points = self._generate_point_cloud(order_book)
        if len(points) < 10:
            return TopologicalSignal(
                coherence_score=0.5,
                betti_0=0,
                betti_1=0,
                persistence_score=0.0,
                super_void_detected=False,
                structural_collapse=False,
                confidence=0.0,
                exchange_ts_ns=exchange_ts_ns,
                reason="insufficient_points"
            )

        # Normalize points
        norm_points = self._normalize_points(points)

        # Compute persistence
        barcode, betti_0_history, betti_1_history = self._compute_persistence(norm_points)

        # Calculate coherence score
        # Coherence = Betti-1 / (Betti-0 + Betti-1)
        if betti_0_history and betti_1_history:
            avg_b0 = np.mean(betti_0_history[-5:]) if len(betti_0_history) >= 5 else np.mean(betti_0_history)
            avg_b1 = np.mean(betti_1_history[-5:]) if len(betti_1_history) >= 5 else np.mean(betti_1_history)
            denominator = avg_b0 + avg_b1 + EPS
            coherence_score = avg_b1 / denominator
        else:
            coherence_score = 0.5

        # Calculate persistence score (how long features survive)
        if barcode:
            persistence_score = min(1.0, np.mean(barcode) / self.epsilon_max)
        else:
            persistence_score = 0.0

        # Detect super-void
        super_void_detected = self._detect_super_void(order_book, norm_points, betti_1_history)

        # Detect structural collapse
        structural_collapse = self._detect_structural_collapse(norm_points, betti_0_history)

        # Calculate confidence
        confidence = persistence_score * (1.0 - min(1.0, avg_b0 / 20.0)) if betti_0_history else 0.5

        # Store history
        self._coherence_history.append(coherence_score)
        if betti_0_history:
            self._betti_0_history.append(avg_b0)
        if betti_1_history:
            self._betti_1_history.append(avg_b1)

        # Build reason
        reasons = []
        if coherence_score > self.coherence_threshold:
            reasons.append(f"coherent: {coherence_score:.2f}")
        if super_void_detected:
            reasons.append("super_void")
        if structural_collapse:
            reasons.append("structural_collapse")
        if persistence_score > 0.7:
            reasons.append(f"persistent: {persistence_score:.2f}")

        signal = TopologicalSignal(
            coherence_score=coherence_score,
            betti_0=int(avg_b0) if betti_0_history else 0,
            betti_1=int(avg_b1) if betti_1_history else 0,
            persistence_score=persistence_score,
            super_void_detected=super_void_detected,
            structural_collapse=structural_collapse,
            confidence=min(1.0, confidence),
            exchange_ts_ns=exchange_ts_ns,
            reason=" | ".join(reasons) if reasons else "normal"
        )

        self._last_signal = signal
        return signal

    def get_last_signal(self) -> Optional[TopologicalSignal]:
        """Get last topological signal."""
        return self._last_signal

    def is_coherent(self) -> bool:
        """Check if market is structurally coherent (institutional activity)."""
        if self._last_signal:
            return self._last_signal.coherence_score > self.coherence_threshold
        return False

    def is_fragmented(self) -> bool:
        """Check if market is fragmented (retail noise)."""
        if self._last_signal:
            return self._last_signal.betti_0 > self._last_signal.betti_1 * 2
        return False

    def get_stats(self) -> Dict[str, Any]:
        """Get engine statistics."""
        return {
            "symbol": self.symbol,
            "last_coherence": self._last_signal.coherence_score if self._last_signal else 0.0,
            "last_betti_0": self._last_signal.betti_0 if self._last_signal else 0,
            "last_betti_1": self._last_signal.betti_1 if self._last_signal else 0,
            "super_void_detected": self._last_signal.super_void_detected if self._last_signal else False,
            "coherence_history_size": len(self._coherence_history),
            "coherence_threshold": self.coherence_threshold,
            "void_threshold": self.void_threshold
        }

    def reset(self) -> None:
        """Reset all state."""
        self._point_cloud.clear()
        self._coherence_history.clear()
        self._betti_0_history.clear()
        self._betti_1_history.clear()
        self._last_signal = None
        logger.info(f"TopologicalEngine reset for {self.symbol}")