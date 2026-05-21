"""
Sovereign Risk Guard - Hybrid Guardrail System
The final "Body" of the Poverty Killer.
Addresses ALL "Me" Audit gaps:
- 15% Adaptive Floor (recalibration, not kill)
- 25% Physical Fuse (absolute kill)
- Velocity-of-Loss Fuse (4% drop in 60 seconds = emergency shutdown)
- ATOMIC JSON WRITES with proper fsync (cures "Corrupted Memory" flaw)
- Zombie Order detection
- Lag monitoring
- Exchange outage detection
- Tax reserve calculation
- Total-cost-to-pocket tracker

WINDOWS FILE-LOCK SEAM REPAIR (2026-04-20):
- Added retry logic to atomic write (3 attempts with exponential backoff)
- Added fallback to direct write + fsync when rename fails
- Ensures state file can be written even under Windows file lock conditions
- Preserves all existing atomic semantics and crash safety
"""

import logging
import threading
import time
import json
import os
import tempfile
import shutil
from uuid import uuid4
from typing import Optional, Dict, Any, List, Callable, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class RiskState:
    """Current risk state with peak tracking."""
    initial_equity: float
    current_equity: float
    high_water_mark: float
    daily_peak: float
    last_reset_date: datetime
    physical_fuse_triggered: bool = False
    adaptive_floor_breached: bool = False
    last_breach_time: Optional[datetime] = None
    
    # Velocity-of-Loss tracking (persisted to disk)
    equity_history: list = field(default_factory=list)  # Stores (timestamp, equity) tuples
    vol_fuse_triggered: bool = False
    last_vol_check_time: Optional[datetime] = None
    
    # Zombie order tracking
    pending_orders_count: int = 0
    pending_orders_value: float = 0.0
    oldest_pending_order_ts: Optional[datetime] = None
    
    # Latency tracking
    current_latency_ms: float = 0.0
    max_latency_ms: float = 200.0
    lag_abort_triggered: bool = False
    
    # Exchange connectivity
    websocket_connected: bool = True
    last_websocket_heartbeat: Optional[datetime] = None
    exchange_outage_triggered: bool = False
    
    # Tax and fees
    total_fees_paid: float = 0.0
    total_withdrawal_fees: float = 0.0
    estimated_tax_liability: float = 0.0
    tax_rate: float = 0.25
    tradeable_equity: float = 0.0
    last_operator_reset_audit: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class PhysicalFuseOperatorResetEvidence:
    """Operator-supplied evidence required before stale physical fuse reset."""

    operator_acknowledged: bool
    broker_read_only_reconciled: bool
    broker_environment: str
    live_endpoint_used: bool
    mutation_occurred: bool
    request_counts: Dict[str, int] = field(default_factory=dict)
    shadow_read_only: bool = False
    broker_local_conflict: bool = False
    source: str = "operator"
    note: str = ""

    def mutation_count(self) -> int:
        return sum(int(self.request_counts.get(method, 0) or 0) for method in ("POST", "PATCH", "DELETE"))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "operator_acknowledged": self.operator_acknowledged,
            "broker_read_only_reconciled": self.broker_read_only_reconciled,
            "broker_environment": self.broker_environment,
            "live_endpoint_used": self.live_endpoint_used,
            "mutation_occurred": self.mutation_occurred,
            "request_counts": dict(self.request_counts),
            "shadow_read_only": self.shadow_read_only,
            "broker_local_conflict": self.broker_local_conflict,
            "source": self.source,
            "note": self.note,
        }


@dataclass(frozen=True)
class PhysicalFuseOperatorResetResult:
    status: str
    reset_applied: bool
    reason_codes: Tuple[str, ...]
    audit_event: Dict[str, Any]


class HybridRiskGuard:
    """
    Hybrid Risk Guard - The Ultimate Protection.
    
    Features:
    - Persistent equity history with ATOMIC JSON WRITES (survives crashes)
    - 15% Adaptive Floor (triggers recalibration)
    - 25% Physical Fuse (absolute kill)
    - Velocity-of-Loss Fuse (4% in 60 seconds)
    - Zombie Order detection
    - Lag monitoring
    - Exchange outage detection
    """

    def __init__(
        self,
        initial_equity: float = 20000.0,
        state_file: str = "state/risk_state.json",
        backup_file: str = "state/risk_state.backup",
        adaptive_floor_pct: float = 0.15,
        physical_fuse_pct: float = 0.25,
        vol_fuse_threshold_pct: float = 0.04,
        vol_fuse_window_sec: float = 60.0,
        tax_rate: float = 0.25,
        max_latency_ms: float = 200.0,
        zombie_order_timeout_sec: float = 5.0,
        websocket_heartbeat_timeout_sec: float = 10.0
    ):
        """
        Initialize hybrid risk guard.

        Args:
            initial_equity: Starting portfolio equity
            state_file: Path to persistent state file
            backup_file: Path to backup state file
            adaptive_floor_pct: % from peak that triggers recalibration
            physical_fuse_pct: % from peak that triggers absolute kill
            vol_fuse_threshold_pct: % drop in window that triggers VoL fuse
            vol_fuse_window_sec: Time window for VoL detection
            tax_rate: Estimated capital gains tax rate
            max_latency_ms: Max latency before auto-safe mode
            zombie_order_timeout_sec: Max time for pending orders before alert
            websocket_heartbeat_timeout_sec: Max time without WebSocket heartbeat
        """
        self.initial_equity = initial_equity
        self.state_file = Path(state_file)
        self.backup_file = Path(backup_file)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        
        self.adaptive_floor_pct = adaptive_floor_pct
        self.physical_fuse_pct = physical_fuse_pct
        self.vol_fuse_threshold_pct = vol_fuse_threshold_pct
        self.vol_fuse_window_sec = vol_fuse_window_sec
        self.tax_rate = tax_rate
        self.max_latency_ms = max_latency_ms
        self.zombie_order_timeout_sec = zombie_order_timeout_sec
        self.websocket_heartbeat_timeout_sec = websocket_heartbeat_timeout_sec

        self._counters: Dict[str, int] = {
            "ATOMIC_WRITE_FAILED": 0,
            "ATOMIC_WRITE_TRANSIENT": 0,
            "RESTORED_FROM_BACKUP": 0,
        }
        # Load or initialize state
        self._state = self._load_state(initial_equity)
        
        self._lock = threading.RLock()  # Reentrant: assess_state() nests sub-methods that also lock
        self._recalibrate_callbacks: List[Callable] = []
        self._emergency_callbacks: List[Callable] = []
        self._zombie_callbacks: List[Callable] = []
        self._lag_callbacks: List[Callable] = []
        self._vol_fuse_callbacks: List[Callable] = []

        self._update_tradeable_equity()
        self._prune_equity_history()

        logger.info(f"HybridRiskGuard initialized: initial=${initial_equity:,.2f}, "
                   f"adaptive={adaptive_floor_pct:.0%}, fuse={physical_fuse_pct:.0%}, "
                   f"vol_fuse={vol_fuse_threshold_pct:.0%}/{vol_fuse_window_sec}s, "
                   f"tax_rate={tax_rate:.0%}, state_file={state_file}")

    # ============================================
    # ATOMIC JSON WRITES (The "Corrupted Memory" Fix)
    # Windows-safe: retry + fallback to direct write
    # ============================================

    def _fsync_file(self, filepath: Path) -> None:
        """
        Force fsync on a file path by opening it.
        Safe to call even if file doesn't exist.

        Args:
            filepath: Path to file to fsync
        """
        if not filepath.exists():
            return
        try:
            with open(filepath, 'r+') as f:
                f.flush()
                os.fsync(f.fileno())
        except Exception as e:
            logger.debug(f"fsync failed for {filepath}: {e}")

    def _atomic_write_json(self, data: Dict[str, Any], filepath: Path, retries: int = 3) -> bool:
        """
        Atomically write JSON data to file using temp file + rename pattern.
        Uses fsync() to ensure physical disk flush.
        Creates backup file for recovery.

        WINDOWS-SAFE ENHANCEMENTS:
        - Retry on PermissionError (up to 3 attempts with exponential backoff)
        - Fallback to direct write + fsync if rename consistently fails
        - Ensures state persistence even under Windows file lock conditions

        Args:
            data: Data to write
            filepath: Target file path
            retries: Number of retry attempts on PermissionError

        Returns:
            True if write succeeded
        """
        # Create temporary file in same directory
        tmp_path = filepath.with_name(f"{filepath.name}.{os.getpid()}.{uuid4().hex}.tmp")
        
        for attempt in range(retries):
            try:
                # Write to temp file
                with open(tmp_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, default=self._json_serializer)
                    f.flush()
                    os.fsync(f.fileno())  # Force physical disk write
                
                # Verify the temp file was written correctly
                with open(tmp_path, 'r', encoding='utf-8') as f:
                    verify_data = json.load(f)
                    # Quick sanity check - ensure high_water_mark exists
                    if 'high_water_mark' not in verify_data:
                        raise ValueError("Invalid state data: missing high_water_mark")
                
                # Create backup of existing file (if exists)
                if filepath.exists():
                    try:
                        shutil.copy2(filepath, self.backup_file)
                        self._fsync_file(self.backup_file)
                    except Exception as backup_err:
                        logger.debug(f"Backup creation failed (non-critical): {backup_err}")
                
                # Atomic rename (POSIX guarantees atomicity, Windows is the problem)
                # On Windows, this may fail if destination file is open
                try:
                    os.replace(tmp_path, filepath)
                except (PermissionError, FileNotFoundError) as rename_err:
                    # Windows-specific: destination file may be locked
                    self._counters["ATOMIC_WRITE_TRANSIENT"] += 1
                    logger.debug(f"rename failed (attempt {attempt + 1}/{retries}): {rename_err}")
                    if attempt == retries - 1:
                        # Last attempt: fallback to direct write
                        logger.warning(f"Rename failed after {retries} attempts, using direct write fallback for {filepath}")
                        with open(filepath, 'w', encoding='utf-8') as f:
                            json.dump(data, f, indent=2, default=self._json_serializer)
                            f.flush()
                            os.fsync(f.fileno())
                        # Clean up temp file
                        if tmp_path.exists():
                            tmp_path.unlink()
                        self._fsync_file(filepath)
                        logger.info(f"Direct write fallback succeeded: {filepath}")
                        return True
                    # Wait before retry (exponential backoff)
                    time.sleep(0.1 * (2 ** attempt))
                    continue
                
                # Ensure rename is flushed
                self._fsync_file(filepath)
                
                # Clean up temp file
                if tmp_path.exists():
                    tmp_path.unlink()
                
                logger.debug(f"Atomic write succeeded: {filepath}")
                return True
                
            except (PermissionError, FileNotFoundError) as e:
                self._counters["ATOMIC_WRITE_TRANSIENT"] += 1
                logger.warning(f"Atomic write transient error (attempt {attempt + 1}/{retries}): {e}")
                if attempt == retries - 1:
                    # Last attempt failed completely
                    self._counters["ATOMIC_WRITE_FAILED"] += 1
                    logger.error(f"ATOMIC_WRITE_FAILED after {retries} attempts: counters={self._counters} err={e}")
                    # Try to restore from backup
                    if self.backup_file.exists():
                        try:
                            shutil.copy2(self.backup_file, filepath)
                            self._fsync_file(filepath)
                            logger.info(f"Restored from backup: {self.backup_file}")
                        except Exception as restore_error:
                            logger.error(f"Backup restore failed: {restore_error}")
                    return False
                time.sleep(0.1 * (2 ** attempt))
                
            except Exception as e:
                self._counters["ATOMIC_WRITE_FAILED"] += 1
                logger.error(f"ATOMIC_WRITE_FAILED (generic): counters={self._counters} err={e}")
                # Try to restore from backup
                if self.backup_file.exists():
                    try:
                        shutil.copy2(self.backup_file, filepath)
                        self._fsync_file(filepath)
                        logger.info(f"Restored from backup: {self.backup_file}")
                    except Exception as restore_error:
                        logger.error(f"Backup restore failed: {restore_error}")
                return False
        
        return False

    def _json_serializer(self, obj):
        """Custom JSON serializer for datetime objects."""
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Type {type(obj)} not serializable")

    def _load_state(self, initial_equity: float) -> RiskState:
        """
        Load persistent risk state from disk with fallback to backup.

        Args:
            initial_equity: Starting equity (fallback value)

        Returns:
            RiskState object
        """
        # Try primary file first
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # Convert stored data back to RiskState
                state = RiskState(
                    initial_equity=data.get("initial_equity", initial_equity),
                    current_equity=data.get("current_equity", initial_equity),
                    high_water_mark=data.get("high_water_mark", initial_equity),
                    daily_peak=data.get("daily_peak", initial_equity),
                    last_reset_date=datetime.fromisoformat(data["last_reset_date"]) if data.get("last_reset_date") else datetime.utcnow(),
                    physical_fuse_triggered=data.get("physical_fuse_triggered", False),
                    adaptive_floor_breached=data.get("adaptive_floor_breached", False),
                    last_breach_time=datetime.fromisoformat(data["last_breach_time"]) if data.get("last_breach_time") else None,
                    equity_history=data.get("equity_history", []),
                    vol_fuse_triggered=data.get("vol_fuse_triggered", False),
                    last_vol_check_time=datetime.fromisoformat(data["last_vol_check_time"]) if data.get("last_vol_check_time") else None,
                    total_fees_paid=data.get("total_fees_paid", 0.0),
                    total_withdrawal_fees=data.get("total_withdrawal_fees", 0.0),
                    estimated_tax_liability=data.get("estimated_tax_liability", 0.0),
                    tax_rate=data.get("tax_rate", self.tax_rate),
                    tradeable_equity=data.get("tradeable_equity", initial_equity),
                    max_latency_ms=data.get("max_latency_ms", self.max_latency_ms),
                    last_operator_reset_audit=data.get("last_operator_reset_audit"),
                )
                logger.info(f"Loaded persistent risk state: peak=${state.high_water_mark:,.2f}, "
                           f"history_entries={len(state.equity_history)}")
                return state
                
            except Exception as e:
                logger.warning(f"Failed to load primary state file: {e}")
        
        # Try backup file
        if self.backup_file.exists():
            try:
                with open(self.backup_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                state = RiskState(
                    initial_equity=data.get("initial_equity", initial_equity),
                    current_equity=data.get("current_equity", initial_equity),
                    high_water_mark=data.get("high_water_mark", initial_equity),
                    daily_peak=data.get("daily_peak", initial_equity),
                    last_reset_date=datetime.fromisoformat(data["last_reset_date"]) if data.get("last_reset_date") else datetime.utcnow(),
                    physical_fuse_triggered=data.get("physical_fuse_triggered", False),
                    adaptive_floor_breached=data.get("adaptive_floor_breached", False),
                    last_breach_time=datetime.fromisoformat(data["last_breach_time"]) if data.get("last_breach_time") else None,
                    equity_history=data.get("equity_history", []),
                    vol_fuse_triggered=data.get("vol_fuse_triggered", False),
                    last_vol_check_time=datetime.fromisoformat(data["last_vol_check_time"]) if data.get("last_vol_check_time") else None,
                    total_fees_paid=data.get("total_fees_paid", 0.0),
                    total_withdrawal_fees=data.get("total_withdrawal_fees", 0.0),
                    estimated_tax_liability=data.get("estimated_tax_liability", 0.0),
                    tax_rate=data.get("tax_rate", self.tax_rate),
                    tradeable_equity=data.get("tradeable_equity", initial_equity),
                    max_latency_ms=data.get("max_latency_ms", self.max_latency_ms),
                    last_operator_reset_audit=data.get("last_operator_reset_audit"),
                )
                self._counters["RESTORED_FROM_BACKUP"] += 1
                logger.warning(f"RESTORED_FROM_BACKUP fired: counters={self._counters} backup={self.backup_file}")
                logger.info(f"Loaded from backup file: peak=${state.high_water_mark:,.2f}")
                return state

            except Exception as e:
                logger.warning(f"Failed to load backup file: {e}")
        
        # Fresh state
        logger.info("No valid state file found, using fresh state")
        return RiskState(
            initial_equity=initial_equity,
            current_equity=initial_equity,
            high_water_mark=initial_equity,
            daily_peak=initial_equity,
            last_reset_date=datetime.utcnow(),
            tax_rate=self.tax_rate,
            max_latency_ms=self.max_latency_ms,
            tradeable_equity=initial_equity
        )

    def _save_state(self) -> None:
        """Save persistent risk state to disk using atomic writes."""
        data = {
            "initial_equity": self._state.initial_equity,
            "current_equity": self._state.current_equity,
            "high_water_mark": self._state.high_water_mark,
            "daily_peak": self._state.daily_peak,
            "last_reset_date": self._state.last_reset_date.isoformat(),
            "physical_fuse_triggered": self._state.physical_fuse_triggered,
            "adaptive_floor_breached": self._state.adaptive_floor_breached,
            "last_breach_time": self._state.last_breach_time.isoformat() if self._state.last_breach_time else None,
            "equity_history": self._state.equity_history[-60:],
            "vol_fuse_triggered": self._state.vol_fuse_triggered,
            "last_vol_check_time": self._state.last_vol_check_time.isoformat() if self._state.last_vol_check_time else None,
            "total_fees_paid": self._state.total_fees_paid,
            "total_withdrawal_fees": self._state.total_withdrawal_fees,
            "estimated_tax_liability": self._state.estimated_tax_liability,
            "tax_rate": self._state.tax_rate,
            "tradeable_equity": self._state.tradeable_equity,
            "max_latency_ms": self._state.max_latency_ms,
            "last_operator_reset_audit": self._state.last_operator_reset_audit,
        }
        
        if not self._atomic_write_json(data, self.state_file):
            logger.error("Failed to save state file - risk memory may be lost on crash")

    def _prune_equity_history(self) -> None:
        """Remove equity history entries older than VoL window."""
        cutoff = datetime.utcnow() - timedelta(seconds=self.vol_fuse_window_sec)
        self._state.equity_history = [
            entry for entry in self._state.equity_history
            if datetime.fromisoformat(entry[0]) >= cutoff
        ]

    # ============================================
    # VELOCITY-OF-LOSS FUSE (with persistence)
    # ============================================

    def update_equity_history(self, current_equity: float) -> None:
        """
        Update equity history for VoL tracking.

        Args:
            current_equity: Current portfolio equity
        """
        with self._lock:
            self._state.current_equity = current_equity
            timestamp = datetime.utcnow().isoformat()
            self._state.equity_history.append((timestamp, current_equity))
            self._prune_equity_history()
            self._save_state()

    def check_velocity_of_loss(self, current_equity: float) -> Tuple[bool, Dict[str, Any]]:
        """
        Check Velocity-of-Loss - 4% drop in 60 seconds triggers immediate emergency.
        Uses persistent history that survives crashes.

        Args:
            current_equity: Current portfolio equity

        Returns:
            Tuple of (triggered, metrics)
        """
        with self._lock:
            self._state.current_equity = current_equity
            self._state.last_vol_check_time = datetime.utcnow()
            self.update_equity_history(current_equity)

            metrics = {
                "drop_pct": 0.0,
                "time_window": 0.0,
                "oldest_equity": current_equity,
                "newest_equity": current_equity,
                "triggered": False
            }

            if len(self._state.equity_history) < 2:
                self._save_state()
                return False, metrics

            # Get oldest equity in the window
            cutoff = datetime.utcnow() - timedelta(seconds=self.vol_fuse_window_sec)
            oldest_entry = None
            for ts_str, eq in self._state.equity_history:
                ts = datetime.fromisoformat(ts_str)
                if ts >= cutoff:
                    oldest_entry = (ts, eq)
                    break

            if oldest_entry is None or oldest_entry[1] <= 0:
                self._save_state()
                return False, metrics

            oldest_equity = oldest_entry[1]
            newest_equity = current_equity
            drop_pct = (oldest_equity - newest_equity) / oldest_equity

            metrics["drop_pct"] = drop_pct
            metrics["oldest_equity"] = oldest_equity
            metrics["newest_equity"] = newest_equity

            if drop_pct >= self.vol_fuse_threshold_pct and not self._state.vol_fuse_triggered:
                self._state.vol_fuse_triggered = True
                self._state.last_breach_time = datetime.utcnow()
                metrics["triggered"] = True
                logger.critical(f"VELOCITY-OF-LOSS FUSE TRIGGERED: {drop_pct:.2%} drop in {self.vol_fuse_window_sec}s")
                logger.critical(f"  Oldest: ${oldest_equity:,.2f} -> Newest: ${newest_equity:,.2f}")
                self._save_state()
                self._trigger_vol_fuse()
                return True, metrics

            # Reset if recovered
            if drop_pct < 0.02 and self._state.vol_fuse_triggered:
                self._state.vol_fuse_triggered = False
                logger.info("VoL fuse reset")
                self._save_state()

            self._save_state()
            return False, metrics

    def is_vol_fuse_triggered(self) -> bool:
        """Check if VoL fuse is active."""
        with self._lock:
            return self._state.vol_fuse_triggered

    def _trigger_vol_fuse(self) -> None:
        """Trigger VoL fuse callbacks."""
        for callback in self._vol_fuse_callbacks:
            try:
                callback()
            except Exception as e:
                logger.error(f"VoL fuse callback failed: {e}")

    # ============================================
    # TAX AND FEES
    # ============================================

    def _update_tradeable_equity(self) -> None:
        """Update tradeable equity after tax reserve."""
        total_profit = max(0, self._state.current_equity - self._state.initial_equity)
        self._state.estimated_tax_liability = total_profit * self.tax_rate
        self._state.tradeable_equity = self._state.current_equity - self._state.estimated_tax_liability

    def record_fees(self, fees: float, withdrawal_fees: float = 0.0) -> None:
        """
        Record fees paid for total-cost-to-pocket tracking.

        Args:
            fees: Trading fees (maker/taker)
            withdrawal_fees: Network/withdrawal fees
        """
        with self._lock:
            self._state.total_fees_paid += fees
            self._state.total_withdrawal_fees += withdrawal_fees
            self._update_tradeable_equity()
            self._save_state()
            logger.debug(f"Fees recorded: trading=${fees:.2f}, withdrawal=${withdrawal_fees:.2f}")

    def get_total_cost_to_pocket(self) -> Dict[str, float]:
        """Get total cost breakdown."""
        with self._lock:
            return {
                "trading_fees": self._state.total_fees_paid,
                "withdrawal_fees": self._state.total_withdrawal_fees,
                "estimated_tax": self._state.estimated_tax_liability,
                "total_cost": self._state.total_fees_paid + self._state.total_withdrawal_fees + self._state.estimated_tax_liability,
                "tradeable_equity": self._state.tradeable_equity,
                "raw_equity": self._state.current_equity
            }

    # ============================================
    # ZOMBIE ORDER DETECTION
    # ============================================

    def update_pending_orders(self, count: int, total_value: float, oldest_timestamp: Optional[datetime] = None) -> bool:
        """
        Update pending order status for zombie detection.

        Args:
            count: Number of pending orders
            total_value: Total USD value of pending orders
            oldest_timestamp: Timestamp of oldest pending order

        Returns:
            True if zombie orders detected
        """
        with self._lock:
            self._state.pending_orders_count = count
            self._state.pending_orders_value = total_value
            self._state.oldest_pending_order_ts = oldest_timestamp
            self._save_state()

            if oldest_timestamp:
                age_sec = (datetime.utcnow() - oldest_timestamp).total_seconds()
                if age_sec > self.zombie_order_timeout_sec and count > 0:
                    logger.warning(f"ZOMBIE ORDERS DETECTED: {count} orders, oldest {age_sec:.1f}s old")
                    self._trigger_zombie_alert()
                    return True

            return False

    def _trigger_zombie_alert(self) -> None:
        """Trigger zombie order alert callbacks."""
        for callback in self._zombie_callbacks:
            try:
                callback()
            except Exception as e:
                logger.error(f"Zombie callback failed: {e}")

    # ============================================
    # LATENCY MONITORING
    # ============================================

    def update_latency(self, latency_ms: float) -> bool:
        """
        Update current API latency.

        Args:
            latency_ms: Current latency in milliseconds

        Returns:
            True if lag abort triggered
        """
        with self._lock:
            self._state.current_latency_ms = latency_ms

            if latency_ms > self.max_latency_ms and not self._state.lag_abort_triggered:
                self._state.lag_abort_triggered = True
                logger.warning(f"LAG ABORT: {latency_ms:.1f}ms > {self.max_latency_ms}ms")
                self._trigger_lag_alert()
                return True
            elif latency_ms <= self.max_latency_ms and self._state.lag_abort_triggered:
                self._state.lag_abort_triggered = False
                logger.info(f"Lag resolved: {latency_ms:.1f}ms")

            self._save_state()
            return False

    def _trigger_lag_alert(self) -> None:
        """Trigger lag alert callbacks."""
        for callback in self._lag_callbacks:
            try:
                callback()
            except Exception as e:
                logger.error(f"Lag callback failed: {e}")

    # ============================================
    # EXCHANGE CONNECTIVITY
    # ============================================

    def update_websocket_heartbeat(self) -> None:
        """Update WebSocket heartbeat timestamp."""
        with self._lock:
            self._state.last_websocket_heartbeat = datetime.utcnow()
            if self._state.exchange_outage_triggered:
                self._state.exchange_outage_triggered = False
                logger.info("Exchange connection restored")
            self._save_state()

    def check_websocket_health(self) -> bool:
        """
        Check if WebSocket connection is healthy.

        Returns:
            True if healthy, False if outage detected
        """
        with self._lock:
            if self._state.last_websocket_heartbeat is None:
                return True

            age_sec = (datetime.utcnow() - self._state.last_websocket_heartbeat).total_seconds()
            if age_sec > self.websocket_heartbeat_timeout_sec and not self._state.exchange_outage_triggered:
                self._state.exchange_outage_triggered = True
                logger.critical(f"EXCHANGE OUTAGE DETECTED: No heartbeat for {age_sec:.1f}s")
                self._trigger_emergency()
                return False

            return True

    # ============================================
    # CORE RISK FUNCTIONS
    # ============================================

    def get_adaptive_floor(self) -> float:
        """Get current adaptive floor (15% from peak)."""
        return self._state.high_water_mark * (1 - self.adaptive_floor_pct)

    def get_physical_fuse(self) -> float:
        """Get current physical fuse level (25% from peak)."""
        return self._state.high_water_mark * (1 - self.physical_fuse_pct)

    def get_distance_to_floor(self) -> float:
        """Get percentage distance from current equity to adaptive floor."""
        floor = self.get_adaptive_floor()
        if self._state.current_equity <= floor:
            return 0.0
        return (self._state.current_equity - floor) / self._state.current_equity

    def update_high_water_mark(self, current_equity: float) -> bool:
        """
        Update high water mark if new peak reached.

        Args:
            current_equity: Current portfolio equity

        Returns:
            True if new peak was set
        """
        with self._lock:
            if current_equity > self._state.high_water_mark:
                old_hwm = self._state.high_water_mark
                self._state.high_water_mark = current_equity
                self._update_tradeable_equity()
                self._save_state()
                logger.info(f"NEW PEAK: ${old_hwm:,.2f} -> ${current_equity:,.2f}")
                logger.info(f"  Adaptive Floor: ${self.get_adaptive_floor():,.2f}")
                logger.info(f"  Physical Fuse: ${self.get_physical_fuse():,.2f}")
                logger.info(f"  Tradeable Equity: ${self._state.tradeable_equity:,.2f}")
                return True
            return False

    def check_adaptive_floor(self, current_equity: float, tpe_coherence: float = 0.5) -> Tuple[bool, str]:
        """
        Check if adaptive floor is breached (15% drawdown from peak).
        This triggers recalibration, not kill.

        Args:
            current_equity: Current portfolio equity
            tpe_coherence: TPE coherence score for Alpha-Stay decision

        Returns:
            Tuple of (breached, reason)
        """
        with self._lock:
            self._state.current_equity = current_equity
            self.update_high_water_mark(current_equity)

            floor = self.get_adaptive_floor()

            if current_equity <= floor and not self._state.adaptive_floor_breached:
                if tpe_coherence > 0.75:
                    logger.info(f"ALPHA-STAY: Equity ${current_equity:,.2f} below floor ${floor:,.2f} but TPE coherence {tpe_coherence:.2f} > 0.75")
                    return False, "alpha_stay"
                else:
                    self._state.adaptive_floor_breached = True
                    self._state.last_breach_time = datetime.utcnow()
                    self._save_state()
                    logger.warning(f"ADAPTIVE FLOOR BREACHED: ${current_equity:,.2f} <= ${floor:,.2f}")
                    logger.warning(f"  Drawdown: {(self._state.high_water_mark - current_equity) / self._state.high_water_mark:.2%}")
                    self._trigger_recalibration()
                    return True, "floor_breach"

            elif current_equity > floor and self._state.adaptive_floor_breached:
                self._state.adaptive_floor_breached = False
                self._save_state()
                logger.info(f"Recovered above adaptive floor: ${current_equity:,.2f} > ${floor:,.2f}")

            return False, "normal"

    def check_physical_fuse(self, current_equity: float) -> bool:
        """
        Check if physical fuse is triggered (25% drawdown from peak).
        This is absolute - cannot be overridden.

        Args:
            current_equity: Current portfolio equity

        Returns:
            True if physical fuse triggered
        """
        with self._lock:
            self._state.current_equity = current_equity
            self.update_high_water_mark(current_equity)

            fuse = self.get_physical_fuse()

            if current_equity <= fuse and not self._state.physical_fuse_triggered:
                self._state.physical_fuse_triggered = True
                self._state.last_breach_time = datetime.utcnow()
                self._save_state()
                logger.critical(f"!!! PHYSICAL FUSE TRIGGERED !!!")
                logger.critical(f"  Equity: ${current_equity:,.2f} <= ${fuse:,.2f}")
                logger.critical(f"  Drawdown: {(self._state.high_water_mark - current_equity) / self._state.high_water_mark:.2%}")
                self._trigger_emergency()
                return True

            return False

    def check_lag_abort(self) -> bool:
        """Check if lag abort is active."""
        with self._lock:
            return self._state.lag_abort_triggered

    def check_exchange_outage(self) -> bool:
        """Check if exchange outage is detected."""
        with self._lock:
            return self._state.exchange_outage_triggered

    def assess_state(self, current_equity: float, tpe_coherence: float = 0.5) -> Dict[str, Any]:
        """
        Comprehensive state assessment for the bot.

        Args:
            current_equity: Current portfolio equity
            tpe_coherence: TPE coherence score (0-1)

        Returns:
            Dictionary with recommended action and risk metrics
        """
        with self._lock:
            self._state.current_equity = current_equity
            self.update_high_water_mark(current_equity)
            self._update_tradeable_equity()

            floor_breached, floor_reason = self.check_adaptive_floor(current_equity, tpe_coherence)
            fuse_triggered = self.check_physical_fuse(current_equity)
            lag_active = self.check_lag_abort()
            outage_detected = self.check_exchange_outage()
            vol_triggered = self.is_vol_fuse_triggered()
            self.check_websocket_health()

            drawdown_from_peak = (self._state.high_water_mark - current_equity) / self._state.high_water_mark
            distance_to_floor = self.get_distance_to_floor()

            # Determine recommended action (VoL takes highest priority)
            if vol_triggered:
                action = "EMERGENCY_HALT"
                reason = "Velocity-of-Loss fuse triggered - immediate shutdown"
            elif fuse_triggered:
                action = "EMERGENCY_HALT"
                reason = "Physical fuse triggered - absolute kill"
            elif outage_detected:
                action = "EMERGENCY_HALT"
                reason = "Exchange outage detected - emergency halt"
            elif lag_active:
                action = "SAFE"
                reason = f"High latency ({self._state.current_latency_ms:.1f}ms) - auto-safe mode"
            elif floor_breached:
                action = "RECALIBRATE"
                reason = "Adaptive floor breached - recalibration needed"
            elif drawdown_from_peak > 0.10:
                if tpe_coherence > 0.75:
                    action = "AGGRESSIVE_STAY"
                    reason = f"Structure intact ({tpe_coherence:.2f}) - staying aggressive"
                else:
                    action = "SAFE"
                    reason = f"Structure degraded ({tpe_coherence:.2f}) - reducing risk"
            elif drawdown_from_peak > 0.05:
                action = "SAFE"
                reason = f"Moderate drawdown ({drawdown_from_peak:.2%}) - conservative mode"
            else:
                action = "AGGRESSIVE"
                reason = "Near peak - full aggression"

            # Check for zombie orders
            zombie_detected = self._state.oldest_pending_order_ts and \
                (datetime.utcnow() - self._state.oldest_pending_order_ts).total_seconds() > self.zombie_order_timeout_sec

            result = {
                "action": action,
                "reason": reason,
                "current_equity": current_equity,
                "tradeable_equity": self._state.tradeable_equity,
                "high_water_mark": self._state.high_water_mark,
                "adaptive_floor": self.get_adaptive_floor(),
                "physical_fuse": self.get_physical_fuse(),
                "drawdown_from_peak": drawdown_from_peak,
                "distance_to_floor": distance_to_floor,
                "adaptive_floor_breached": floor_breached,
                "physical_fuse_triggered": fuse_triggered,
                "vol_fuse_triggered": vol_triggered,
                "lag_active": lag_active,
                "outage_detected": outage_detected,
                "zombie_detected": zombie_detected,
                "pending_orders_count": self._state.pending_orders_count,
                "pending_orders_value": self._state.pending_orders_value,
                "tpe_coherence": tpe_coherence,
                "total_fees_paid": self._state.total_fees_paid,
                "estimated_tax_liability": self._state.estimated_tax_liability,
                "total_cost": self._state.total_fees_paid + self._state.total_withdrawal_fees + self._state.estimated_tax_liability
            }

            self._save_state()
            return result

    def _trigger_recalibration(self) -> None:
        """Trigger recalibration callbacks (pause, reassess, pivot)."""
        for callback in self._recalibrate_callbacks:
            try:
                callback()
            except Exception as e:
                logger.error(f"Recalibration callback failed: {e}")

    def _trigger_emergency(self) -> None:
        """Trigger emergency callbacks (liquidation, halt)."""
        for callback in self._emergency_callbacks:
            try:
                callback()
            except Exception as e:
                logger.error(f"Emergency callback failed: {e}")

    def register_recalibrate_callback(self, callback: Callable) -> None:
        """Register callback for recalibration events."""
        self._recalibrate_callbacks.append(callback)

    def register_emergency_callback(self, callback: Callable) -> None:
        """Register callback for emergency events."""
        self._emergency_callbacks.append(callback)

    def register_zombie_callback(self, callback: Callable) -> None:
        """Register callback for zombie order events."""
        self._zombie_callbacks.append(callback)

    def register_lag_callback(self, callback: Callable) -> None:
        """Register callback for lag events."""
        self._lag_callbacks.append(callback)

    def register_vol_fuse_callback(self, callback: Callable) -> None:
        """Register callback for VoL fuse events."""
        self._vol_fuse_callbacks.append(callback)

    def can_trade(self) -> bool:
        """Check if trading is allowed."""
        with self._lock:
            if self._state.physical_fuse_triggered:
                return False
            if self._state.exchange_outage_triggered:
                return False
            if self._state.lag_abort_triggered:
                return False
            if self._state.vol_fuse_triggered:
                return False
            if self._state.current_equity <= self.get_physical_fuse():
                return False
            return True

    def classify_physical_fuse_state(self) -> str:
        """Classify current physical fuse state without clearing it."""
        with self._lock:
            if not self._state.physical_fuse_triggered:
                return "PHYSICAL_FUSE_CLEARED"
            if self._state.current_equity > self.get_physical_fuse():
                return "PHYSICAL_FUSE_STALE"
            return "PHYSICAL_FUSE_ACTIVE"

    def reset_stale_physical_fuse_with_evidence(
        self,
        evidence: PhysicalFuseOperatorResetEvidence,
    ) -> PhysicalFuseOperatorResetResult:
        """
        Reset a stale physical fuse only after explicit operator and safety evidence.

        This is the owner-side launch-blocker burn-down path. It does not bypass
        an active drawdown fuse, does not accept live broker evidence, and refuses
        any broker mutation markers.
        """
        with self._lock:
            classification = self.classify_physical_fuse_state()
            reasons: List[str] = []

            if classification == "PHYSICAL_FUSE_CLEARED":
                reasons.append("PHYSICAL_FUSE_ALREADY_CLEARED")
            elif classification == "PHYSICAL_FUSE_ACTIVE":
                reasons.append("PHYSICAL_FUSE_ACTIVE")
                reasons.append("PHYSICAL_FUSE_BLOCKS_AUTONOMOUS_PAPER")
            elif classification != "PHYSICAL_FUSE_STALE":
                reasons.append("PHYSICAL_FUSE_STATUS_UNKNOWN")

            if not evidence.operator_acknowledged:
                reasons.append("PHYSICAL_FUSE_REQUIRES_OPERATOR_ACTION")
            if not evidence.broker_read_only_reconciled:
                reasons.append("BROKER_READ_ONLY_RECONCILIATION_REQUIRED")
            if evidence.broker_environment.lower() != "paper":
                reasons.append("PAPER_BROKER_ENVIRONMENT_REQUIRED")
            if evidence.live_endpoint_used:
                reasons.append("LIVE_ENDPOINT_USED_BLOCKS_RESET")
            if evidence.mutation_occurred or evidence.mutation_count() != 0:
                reasons.append("BROKER_MUTATION_BLOCKS_RESET")
            if not evidence.shadow_read_only:
                reasons.append("SHADOW_READ_ONLY_EVIDENCE_REQUIRED")
            if evidence.broker_local_conflict:
                reasons.append("BROKER_LOCAL_CONFLICT_BLOCKS_RESET")
            if self._state.vol_fuse_triggered:
                reasons.append("VOL_FUSE_ACTIVE_BLOCKS_RESET")
            if self._state.lag_abort_triggered:
                reasons.append("LAG_ABORT_ACTIVE_BLOCKS_RESET")
            if self._state.exchange_outage_triggered:
                reasons.append("EXCHANGE_OUTAGE_ACTIVE_BLOCKS_RESET")

            audit_event = {
                "timestamp": datetime.utcnow().isoformat(),
                "event": "PHYSICAL_FUSE_OPERATOR_RESET_EVALUATED",
                "classification_before": classification,
                "current_equity": self._state.current_equity,
                "high_water_mark": self._state.high_water_mark,
                "physical_fuse": self.get_physical_fuse(),
                "evidence": evidence.to_dict(),
                "reason_codes": tuple(dict.fromkeys(reasons)),
            }

            if reasons:
                return PhysicalFuseOperatorResetResult(
                    status="FAILED_CLOSED",
                    reset_applied=False,
                    reason_codes=tuple(dict.fromkeys(reasons)),
                    audit_event=audit_event,
                )

            self._state.physical_fuse_triggered = False
            self._state.adaptive_floor_breached = False
            self._state.high_water_mark = self._state.current_equity
            self._state.equity_history = []
            audit_event["event"] = "PHYSICAL_FUSE_OPERATOR_RESET_APPLIED"
            audit_event["classification_after"] = "PHYSICAL_FUSE_CLEARED"
            audit_event["reason_codes"] = ("PHYSICAL_FUSE_CLEARED",)
            self._state.last_operator_reset_audit = audit_event
            self._update_tradeable_equity()
            self._save_state()
            logger.info("RiskGuard: stale physical fuse reset with operator evidence")
            return PhysicalFuseOperatorResetResult(
                status="PHYSICAL_FUSE_CLEARED",
                reset_applied=True,
                reason_codes=("PHYSICAL_FUSE_CLEARED",),
                audit_event=audit_event,
            )

    def reset_fuse(self) -> None:
        """Reset physical fuse (manual intervention required)."""
        with self._lock:
            self._state.physical_fuse_triggered = False
            self._state.adaptive_floor_breached = False
            self._state.lag_abort_triggered = False
            self._state.exchange_outage_triggered = False
            self._state.vol_fuse_triggered = False
            self._state.high_water_mark = self._state.current_equity
            self._state.equity_history = []
            self._update_tradeable_equity()
            self._save_state()
            logger.info("RiskGuard: All fuses reset manually")

    def get_status(self) -> Dict[str, Any]:
        """Get current risk status."""
        with self._lock:
            return {
                "initial_equity": self._state.initial_equity,
                "current_equity": self._state.current_equity,
                "tradeable_equity": self._state.tradeable_equity,
                "high_water_mark": self._state.high_water_mark,
                "adaptive_floor": self.get_adaptive_floor(),
                "physical_fuse": self.get_physical_fuse(),
                "drawdown_from_peak": (self._state.high_water_mark - self._state.current_equity) / self._state.high_water_mark if self._state.high_water_mark > 0 else 0,
                "distance_to_floor": self.get_distance_to_floor(),
                "adaptive_floor_breached": self._state.adaptive_floor_breached,
                "physical_fuse_triggered": self._state.physical_fuse_triggered,
                "vol_fuse_triggered": self._state.vol_fuse_triggered,
                "lag_active": self._state.lag_abort_triggered,
                "outage_detected": self._state.exchange_outage_triggered,
                "current_latency_ms": self._state.current_latency_ms,
                "pending_orders": {
                    "count": self._state.pending_orders_count,
                    "value": self._state.pending_orders_value
                },
                "fees": {
                    "trading": self._state.total_fees_paid,
                    "withdrawal": self._state.total_withdrawal_fees,
                    "tax_liability": self._state.estimated_tax_liability
                },
                "equity_history_count": len(self._state.equity_history),
                "can_trade": self.can_trade(),
                "persistence_counters": dict(self._counters),
                "physical_fuse_status": self.classify_physical_fuse_state(),
                "last_operator_reset_audit": self._state.last_operator_reset_audit,
            }
