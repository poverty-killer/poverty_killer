"""
Snapshot Exporter - 60-Second JSON Snapshots for AI Review
Exports system state, portfolio, positions, and risk metrics for external analysis.
Used for Gemini/Claude review and performance monitoring.
HARDENED: Added previous_regime, signal metadata, atomic writing with temp-rename pattern.
"""

import json
import threading
import time
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict

from app.models import (
    PortfolioSnapshot, RiskSnapshot, HealthSnapshot,
    PositionRecord, OrderRequest, OrderFill, StrategySignal
)
from app.constants import ControlMode, SleeveType, RegimeType

logger = logging.getLogger(__name__)


@dataclass
class ExportSnapshot:
    """Complete snapshot data structure for export."""
    timestamp: str
    version: str = "1.0"
    system: Dict[str, Any] = None
    portfolio: Dict[str, Any] = None
    risk: Dict[str, Any] = None
    positions: List[Dict[str, Any]] = None
    active_strategies: List[Dict[str, Any]] = None
    recent_signals: List[Dict[str, Any]] = None
    recent_orders: List[Dict[str, Any]] = None
    recent_fills: List[Dict[str, Any]] = None
    market_regime: Dict[str, Any] = None
    strategy_allocation: Dict[str, Any] = None
    physical_verification: Dict[str, Any] = None
    previous_regime: Optional[str] = None


class SnapshotExporter:
    """
    Exports system state snapshots every 60 seconds.
    Creates JSON files for AI review and historical analysis.
    Uses atomic write pattern (temp file + rename) to prevent corruption.
    """

    def __init__(
        self,
        export_dir: str = "reports/snapshots",
        interval_seconds: int = 60,
        max_snapshots: int = 1440  # 24 hours at 60s intervals
    ):
        """
        Initialize snapshot exporter.

        Args:
            export_dir: Directory to save snapshots
            interval_seconds: Seconds between snapshots
            max_snapshots: Maximum number of snapshots to keep
        """
        self.export_dir = Path(export_dir)
        self.export_dir.mkdir(parents=True, exist_ok=True)
        self.interval_seconds = interval_seconds
        self.max_snapshots = max_snapshots

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # State data to be populated by main loop
        self._current_portfolio: Optional[PortfolioSnapshot] = None
        self._current_risk: Optional[RiskSnapshot] = None
        self._current_health: Optional[HealthSnapshot] = None
        self._current_positions: List[PositionRecord] = []
        self._active_strategies: List[str] = []
        self._recent_signals: List[StrategySignal] = []
        self._recent_orders: List[OrderRequest] = []
        self._recent_fills: List[OrderFill] = []
        self._current_regime: Optional[RegimeType] = None
        self._previous_regime: Optional[RegimeType] = None
        self._strategy_allocation: Dict[str, float] = {}
        self._physical_verification: Dict[str, Any] = {}

        logger.info(f"SnapshotExporter initialized: {self.export_dir}, interval={interval_seconds}s")

    def start(self):
        """Start the snapshot exporter thread."""
        if self._running:
            logger.warning("SnapshotExporter already running")
            return

        self._running = True
        self._thread = threading.Thread(target=self._export_loop, daemon=True)
        self._thread.start()
        logger.info("SnapshotExporter started")

    def stop(self):
        """Stop the snapshot exporter thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
        logger.info("SnapshotExporter stopped")

    def update_state(
        self,
        portfolio: Optional[PortfolioSnapshot] = None,
        risk: Optional[RiskSnapshot] = None,
        health: Optional[HealthSnapshot] = None,
        positions: Optional[List[PositionRecord]] = None,
        active_strategies: Optional[List[str]] = None,
        recent_signals: Optional[List[StrategySignal]] = None,
        recent_orders: Optional[List[OrderRequest]] = None,
        recent_fills: Optional[List[OrderFill]] = None,
        regime: Optional[RegimeType] = None,
        strategy_allocation: Optional[Dict[str, float]] = None,
        physical_verification: Optional[Dict[str, Any]] = None
    ):
        """
        Update current state data from main loop.

        This is called periodically to refresh the data that will be exported.
        """
        with self._lock:
            if portfolio is not None:
                self._current_portfolio = portfolio
            if risk is not None:
                self._current_risk = risk
            if health is not None:
                self._current_health = health
            if positions is not None:
                self._current_positions = positions
            if active_strategies is not None:
                self._active_strategies = active_strategies
            if recent_signals is not None:
                self._recent_signals = recent_signals[-10:]  # Keep last 10
            if recent_orders is not None:
                self._recent_orders = recent_orders[-10:]  # Keep last 10
            if recent_fills is not None:
                self._recent_fills = recent_fills[-10:]  # Keep last 10
            if regime is not None:
                if self._current_regime != regime:
                    self._previous_regime = self._current_regime
                self._current_regime = regime
            if strategy_allocation is not None:
                self._strategy_allocation = strategy_allocation
            if physical_verification is not None:
                self._physical_verification = physical_verification

    def _export_loop(self):
        """Background loop that exports snapshots at regular intervals."""
        while self._running:
            try:
                time.sleep(self.interval_seconds)
                self._export_snapshot()
                self._cleanup_old_snapshots()
            except Exception as e:
                logger.error(f"Snapshot export failed: {e}")

    def _atomic_write(self, filepath: Path, content: str):
        """
        Write file atomically using temp file + rename pattern.
        Prevents corruption from partial writes.
        """
        # Create temp file in same directory
        temp_dir = filepath.parent
        with tempfile.NamedTemporaryFile(
            mode='w',
            dir=temp_dir,
            prefix=f'.{filepath.stem}_',
            suffix='.tmp',
            delete=False
        ) as tmp_file:
            tmp_file.write(content)
            tmp_path = Path(tmp_file.name)

        # Atomic rename (on POSIX systems, this is atomic)
        os.replace(tmp_path, filepath)

    def _export_snapshot(self):
        """Create and save a single snapshot using atomic write."""
        snapshot = self._build_snapshot()

        # Create filename with timestamp
        timestamp_str = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"snapshot_{timestamp_str}.json"
        filepath = self.export_dir / filename

        try:
            content = json.dumps(snapshot, indent=2, default=str)
            self._atomic_write(filepath, content)
            logger.debug(f"Snapshot exported: {filename}")
        except Exception as e:
            logger.error(f"Failed to write snapshot: {e}")

    def _build_snapshot(self) -> Dict[str, Any]:
        """Build complete snapshot dictionary from current state."""
        with self._lock:
            snapshot = ExportSnapshot(
                timestamp=datetime.utcnow().isoformat(),
                version="1.0"
            )

            # System info with health data
            snapshot.system = {
                "uptime_seconds": self._current_health.uptime_seconds if self._current_health else 0,
                "memory_usage_mb": self._current_health.memory_usage_mb if self._current_health else 0,
                "cpu_percent": self._current_health.cpu_percent if self._current_health else 0,
                "websocket_connected": self._current_health.websocket_connected if self._current_health else False,
                "active_strategies": self._active_strategies,
                "last_physical_verification": self._current_health.last_physical_verification.isoformat()
                if self._current_health and self._current_health.last_physical_verification else None,
            }

            # Portfolio
            if self._current_portfolio:
                snapshot.portfolio = self._current_portfolio.model_dump()
            else:
                snapshot.portfolio = {"error": "No portfolio data"}

            # Risk with previous regime
            if self._current_risk:
                snapshot.risk = self._current_risk.model_dump()
                # Add previous regime to risk snapshot
                snapshot.risk["previous_regime"] = self._previous_regime.value if self._previous_regime else None
            else:
                snapshot.risk = {"error": "No risk data"}

            # Positions with latency metadata
            snapshot.positions = [
                {
                    "id": p.id,
                    "symbol": p.symbol,
                    "side": p.side,
                    "quantity": p.quantity,
                    "entry_price": p.entry_price,
                    "current_price": p.current_price,
                    "unrealized_pnl": p.unrealized_pnl,
                    "pnl_percent": p.pnl_percent,
                    "strategy": p.strategy,
                    "opened_at": p.opened_at.isoformat(),
                    "entry_latency_ms": p.entry_latency_ms,
                }
                for p in self._current_positions
            ]

            # Active strategies with their allocation
            snapshot.active_strategies = []
            for strategy in self._active_strategies:
                snapshot.active_strategies.append({
                    "name": strategy,
                    "allocation_percent": self._strategy_allocation.get(strategy, 0) * 100,
                    "enabled": True,
                })

            # Recent signals with metadata and regime
            snapshot.recent_signals = [
                {
                    "strategy": s.strategy,
                    "symbol": s.symbol,
                    "side": s.side,
                    "confidence": s.confidence,
                    "quantity": s.quantity,
                    "timestamp": s.timestamp.isoformat(),
                    "reason": s.reason,
                    "regime": s.regime,
                    "metadata": s.metadata,
                }
                for s in self._recent_signals
            ]

            # Recent orders with latency
            snapshot.recent_orders = [
                {
                    "id": o.id,
                    "symbol": o.symbol,
                    "side": o.side,
                    "quantity": o.quantity,
                    "status": "submitted",
                    "timestamp": o.timestamp.isoformat(),
                    "strategy": o.strategy,
                    "latency_ms": o.metadata.get("latency_ms") if o.metadata else None,
                }
                for o in self._recent_orders
            ]

            # Recent fills with latency
            snapshot.recent_fills = [
                {
                    "order_id": f.order_id,
                    "symbol": f.symbol,
                    "side": f.side,
                    "quantity": f.quantity,
                    "price": f.price,
                    "fee": f.fee,
                    "timestamp": f.timestamp.isoformat(),
                    "latency_ms": f.latency_ms,
                }
                for f in self._recent_fills
            ]

            # Market regime with previous regime tracking
            snapshot.market_regime = {
                "current_regime": self._current_regime.value if self._current_regime else "unknown",
                "previous_regime": self._previous_regime.value if self._previous_regime else None,
                "confidence": 0.8,  # Would come from regime detector
                "regime_changed": self._previous_regime != self._current_regime,
            }

            # Strategy allocation summary
            snapshot.strategy_allocation = {
                "by_strategy": self._strategy_allocation,
                "total_allocated": sum(self._strategy_allocation.values()),
                "cash_reserve": 1.0 - sum(self._strategy_allocation.values()),
            }

            # Physical verification summary
            snapshot.physical_verification = {
                "last_check": self._physical_verification.get("timestamp"),
                "avg_latency_ms": self._physical_verification.get("avg_latency_ms"),
                "toxic_trades_count": self._physical_verification.get("toxic_trades_count", 0),
                "is_toxic": self._physical_verification.get("is_toxic", False),
            }

            # Performance summary
            if self._current_portfolio:
                snapshot.portfolio["performance"] = {
                    "total_pnl": self._current_portfolio.total_pnl,
                    "daily_pnl": self._current_risk.daily_pnl if self._current_risk else 0,
                    "current_drawdown": self._current_risk.current_drawdown if self._current_risk else 0,
                }

            return asdict(snapshot)

    def _cleanup_old_snapshots(self):
        """Remove old snapshots to prevent disk overflow."""
        try:
            snapshots = sorted(self.export_dir.glob("snapshot_*.json"))
            if len(snapshots) > self.max_snapshots:
                for old_file in snapshots[:-self.max_snapshots]:
                    old_file.unlink()
                    logger.debug(f"Removed old snapshot: {old_file.name}")
        except Exception as e:
            logger.error(f"Failed to cleanup old snapshots: {e}")

    def get_latest_snapshot(self) -> Optional[Dict[str, Any]]:
        """Get the most recent snapshot file."""
        try:
            snapshots = sorted(self.export_dir.glob("snapshot_*.json"))
            if not snapshots:
                return None

            latest = snapshots[-1]
            with open(latest, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load latest snapshot: {e}")
            return None

    def export_emergency_snapshot(self) -> bool:
        """
        Export an emergency snapshot immediately.
        Used before kill switch or shutdown.
        """
        try:
            self._export_snapshot()
            logger.info("Emergency snapshot exported")
            return True
        except Exception as e:
            logger.error(f"Emergency snapshot failed: {e}")
            return False

    def get_snapshot_summary(self) -> Dict[str, Any]:
        """Get a summary of the latest snapshot (lightweight)."""
        with self._lock:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "total_equity": self._current_portfolio.total_equity if self._current_portfolio else 0,
                "positions_count": len(self._current_positions),
                "active_strategies": len(self._active_strategies),
                "recent_signals_count": len(self._recent_signals),
                "risk_drawdown": self._current_risk.current_drawdown if self._current_risk else 0,
                "kill_switch_triggered": self._current_risk.is_kill_switch_triggered if self._current_risk else False,
                "current_regime": self._current_regime.value if self._current_regime else "unknown",
                "previous_regime": self._previous_regime.value if self._previous_regime else None,
            }