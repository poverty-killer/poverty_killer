"""
Sovereign Sentinel - Asynchronous Heartbeat Watchdog
Monitors main loop health from an independent thread.
Triggers external alerts (Telegram/Webhook) if bot heart stops beating.
HARDENED:
- Parallel dispatch (Webhook and Telegram on separate threads)
- I/O coalescing (state saves every 60 seconds, except emergencies)
- Non-blocking public API
- Visibility is Security.
"""

import logging
import threading
import time
import queue
import requests
from typing import Optional, Dict, Any, Callable, List
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import json

logger = logging.getLogger(__name__)


class AlertSeverity(Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


class AlertType(Enum):
    """Types of alerts."""
    HEARTBEAT_STOPPED = "heartbeat_stopped"
    LATENCY_SPIKE = "latency_spike"
    LAG_DETECTED = "lag_detected"
    KILL_SWITCH_TRIGGERED = "kill_switch_triggered"
    VOL_FUSE_TRIGGERED = "vol_fuse_triggered"
    EXCHANGE_OUTAGE = "exchange_outage"
    REST_DNS_FAILURE = "rest_dns_failure"
    ZOMBIE_ORDERS = "zombie_orders"
    POSITION_LIMIT = "position_limit"
    DRAWDOWN_LIMIT = "drawdown_limit"
    REGIME_CHANGE = "regime_change"
    STRATEGY_ERROR = "strategy_error"


@dataclass(slots=True)
class Alert:
    """Alert data structure."""
    alert_type: AlertType
    severity: AlertSeverity
    message: str
    timestamp: datetime
    data: Dict[str, Any] = field(default_factory=dict)


class SovereignSentinel:
    """
    Sovereign Sentinel - Independent heartbeat watchdog.
    
    Features:
    - Asynchronous monitoring from separate thread
    - Heartbeat tracking with configurable thresholds
    - PARALLEL DISPATCH: Webhook and Telegram on separate threads
    - I/O COALESCING: State saves every 60 seconds (except emergencies)
    - Non-blocking public API
    - Configurable alert cooldown to prevent spam
    """
    
    def __init__(
        self,
        webhook_url: Optional[str] = None,
        telegram_bot_token: Optional[str] = None,
        telegram_chat_id: Optional[str] = None,
        heartbeat_interval_sec: float = 1.0,
        latency_threshold_ms: float = 500.0,
        consecutive_failures_threshold: int = 3,
        alert_cooldown_sec: float = 60.0,
        state_file: str = "state/alert_state.json",
        state_flush_interval_sec: float = 60.0
    ):
        """
        Initialize sovereign sentinel.

        Args:
            webhook_url: Generic webhook URL for alerts
            telegram_bot_token: Telegram bot token
            telegram_chat_id: Telegram chat ID
            heartbeat_interval_sec: How often to expect heartbeat
            latency_threshold_ms: Max acceptable loop latency
            consecutive_failures_threshold: Failures before alert
            alert_cooldown_sec: Minimum time between same alert types
            state_file: Persistent state file for alert history
            state_flush_interval_sec: How often to flush state to disk
        """
        self.webhook_url = webhook_url
        self.telegram_bot_token = telegram_bot_token
        self.telegram_chat_id = telegram_chat_id
        self.heartbeat_interval_sec = heartbeat_interval_sec
        self.latency_threshold_ms = latency_threshold_ms
        self.consecutive_failures_threshold = consecutive_failures_threshold
        self.alert_cooldown_sec = alert_cooldown_sec
        self.state_flush_interval_sec = state_flush_interval_sec
        
        # Heartbeat tracking
        self._last_heartbeat: Optional[datetime] = None
        self._last_heartbeat_latency: float = 0.0
        self._consecutive_missed: int = 0
        self._is_healthy: bool = True
        
        # Alert tracking
        self._last_alert_time: Dict[str, datetime] = {}
        self._alert_history: List[Alert] = []
        self._pending_alerts: List[Alert] = []  # Alerts not yet saved
        self._lock = threading.Lock()
        self._state_dirty = False
        self._last_state_save = datetime.utcnow()
        
        # Thread control
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._alert_thread: Optional[threading.Thread] = None
        self._state_flusher_thread: Optional[threading.Thread] = None
        self._alert_queue: queue.Queue = queue.Queue()
        
        # State file
        self.state_file = Path(state_file)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self._load_state()
        
        logger.info(f"SovereignSentinel initialized: heartbeat_interval={heartbeat_interval_sec}s, "
                   f"latency_threshold={latency_threshold_ms}ms, "
                   f"consecutive_failures={consecutive_failures_threshold}, "
                   f"state_flush_interval={state_flush_interval_sec}s")
    
    # ============================================
    # HEARTBEAT MANAGEMENT
    # ============================================
    
    def heartbeat(self, latency_ms: float = 0.0) -> None:
        """
        Record a heartbeat from the main loop.

        Args:
            latency_ms: Current loop latency in milliseconds
        """
        with self._lock:
            self._last_heartbeat = datetime.utcnow()
            self._last_heartbeat_latency = latency_ms
            self._consecutive_missed = 0
            
            if not self._is_healthy:
                self._is_healthy = True
                self._queue_alert(
                    AlertType.HEARTBEAT_STOPPED,
                    AlertSeverity.INFO,
                    "Heartbeat restored - bot is healthy",
                    {"latency_ms": latency_ms}
                )
    
    def _check_heartbeat(self) -> None:
        """Check if heartbeat is still alive."""
        with self._lock:
            if self._last_heartbeat is None:
                return
            
            age_sec = (datetime.utcnow() - self._last_heartbeat).total_seconds()
            
            if age_sec > self.heartbeat_interval_sec:
                self._consecutive_missed += 1
                
                if self._consecutive_missed >= self.consecutive_failures_threshold and self._is_healthy:
                    self._is_healthy = False
                    self._queue_alert(
                        AlertType.HEARTBEAT_STOPPED,
                        AlertSeverity.CRITICAL,
                        f"HEARTBEAT STOPPED! No heartbeat for {age_sec:.1f}s "
                        f"({self._consecutive_missed} consecutive misses)",
                        {
                            "age_sec": age_sec,
                            "consecutive_misses": self._consecutive_missed,
                            "last_latency_ms": self._last_heartbeat_latency
                        }
                    )
                elif self._consecutive_missed >= 1:
                    logger.warning(f"Missed heartbeat {self._consecutive_missed}/{self.consecutive_failures_threshold}")
    
    # ============================================
    # ALERT QUEUE (Non-Blocking Public API)
    # ============================================
    
    def _can_send_alert(self, alert_type: AlertType) -> bool:
        """Check if alert can be sent (respects cooldown)."""
        key = alert_type.value
        last_time = self._last_alert_time.get(key)
        if last_time is None:
            return True
        
        elapsed = (datetime.utcnow() - last_time).total_seconds()
        return elapsed >= self.alert_cooldown_sec
    
    def _record_alert_sent(self, alert_type: AlertType) -> None:
        """Record that an alert was sent."""
        self._last_alert_time[alert_type.value] = datetime.utcnow()
    
    def _queue_alert(
        self,
        alert_type: AlertType,
        severity: AlertSeverity,
        message: str,
        data: Optional[Dict[str, Any]] = None
    ) -> None:
        """Queue alert for processing (non-blocking)."""
        if not self._can_send_alert(alert_type):
            return
        
        self._record_alert_sent(alert_type)
        
        alert = Alert(
            alert_type=alert_type,
            severity=severity,
            message=message,
            timestamp=datetime.utcnow(),
            data=data or {}
        )
        
        # Add to history immediately (in-memory)
        with self._lock:
            self._alert_history.append(alert)
            self._pending_alerts.append(alert)
            if len(self._alert_history) > 1000:
                self._alert_history = self._alert_history[-500:]
            self._state_dirty = True
        
        # Queue for external dispatch
        self._alert_queue.put(alert)
    
    def send_alert(
        self,
        alert_type: AlertType,
        severity: AlertSeverity,
        message: str,
        data: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Send an alert immediately (non-blocking public API).

        Args:
            alert_type: Type of alert
            severity: Severity level
            message: Alert message
            data: Additional data
        """
        self._queue_alert(alert_type, severity, message, data)
    
    # ============================================
    # PARALLEL DISPATCH (Fire-and-Forget)
    # ============================================
    
    def _dispatch_webhook(self, payload: Dict[str, Any]) -> None:
        """Dispatch webhook in background thread."""
        try:
            response = requests.post(
                self.webhook_url,
                json=payload,
                timeout=5.0
            )
            if response.status_code not in [200, 201, 202, 204]:
                logger.warning(f"Webhook failed: {response.status_code}")
        except Exception as e:
            logger.error(f"Webhook error: {e}")
    
    def _dispatch_telegram(self, payload: Dict[str, Any]) -> None:
        """Dispatch Telegram in background thread."""
        try:
            emoji = {
                "emergency": "🔴🔴🔴",
                "critical": "🔴",
                "warning": "🟡",
                "info": "🔵"
            }.get(payload["severity"], "⚪")
            
            message = f"{emoji} *POVERTY KILLER ALERT*\n\n"
            message += f"*Type:* {payload['alert_type']}\n"
            message += f"*Severity:* {payload['severity'].upper()}\n"
            message += f"*Message:* {payload['message']}\n"
            message += f"*Time:* {payload['timestamp']}\n"
            
            if payload.get("data"):
                message += f"\n*Data:* ```\n{json.dumps(payload['data'], indent=2)[:500]}\n```"
            
            url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
            response = requests.post(
                url,
                json={
                    "chat_id": self.telegram_chat_id,
                    "text": message,
                    "parse_mode": "Markdown"
                },
                timeout=5.0
            )
            if response.status_code != 200:
                logger.warning(f"Telegram failed: {response.status_code}")
        except Exception as e:
            logger.error(f"Telegram error: {e}")
    
    def _dispatch_alert(self, alert: Alert) -> None:
        """
        Dispatch alert to external services in parallel threads.
        One service's failure does NOT block the other.
        """
        payload = {
            "alert_type": alert.alert_type.value,
            "severity": alert.severity.value,
            "message": alert.message,
            "timestamp": alert.timestamp.isoformat(),
            "data": alert.data
        }
        
        # Fire webhook in background thread
        if self.webhook_url:
            t = threading.Thread(target=self._dispatch_webhook, args=(payload,), daemon=True)
            t.start()
        
        # Fire Telegram in background thread
        if self.telegram_bot_token and self.telegram_chat_id:
            t = threading.Thread(target=self._dispatch_telegram, args=(payload,), daemon=True)
            t.start()
        
        # Log based on severity
        if alert.severity == AlertSeverity.EMERGENCY:
            logger.critical(f"ALERT [{alert.alert_type.value}]: {alert.message}")
        elif alert.severity == AlertSeverity.CRITICAL:
            logger.critical(f"ALERT [{alert.alert_type.value}]: {alert.message}")
        elif alert.severity == AlertSeverity.WARNING:
            logger.warning(f"ALERT [{alert.alert_type.value}]: {alert.message}")
        else:
            logger.info(f"ALERT [{alert.alert_type.value}]: {alert.message}")
    
    # ============================================
    # I/O COALESCING (State Flusher)
    # ============================================
    
    def _flush_state_if_needed(self, force: bool = False) -> None:
        """
        Flush pending alerts to disk if needed.
        Coalesces writes to once every state_flush_interval_sec.
        
        Args:
            force: Force immediate flush (used for emergency alerts)
        """
        with self._lock:
            if not self._state_dirty:
                return
            
            now = datetime.utcnow()
            elapsed = (now - self._last_state_save).total_seconds()
            
            if not force and elapsed < self.state_flush_interval_sec:
                return
            
            # Save pending alerts
            if self._pending_alerts:
                self._save_state()
                self._pending_alerts = []
                self._state_dirty = False
                self._last_state_save = now
    
    def _save_state(self) -> None:
        """Save persistent alert state to disk."""
        try:
            with self._lock:
                data = {
                    "alert_history": [
                        {
                            "alert_type": a.alert_type.value,
                            "severity": a.severity.value,
                            "message": a.message,
                            "timestamp": a.timestamp.isoformat(),
                            "data": a.data
                        }
                        for a in self._alert_history[-500:]
                    ],
                    "last_alert_time": {
                        k: v.isoformat() for k, v in self._last_alert_time.items()
                    }
                }
            
            with open(self.state_file, 'w') as f:
                json.dump(data, f, indent=2)
            
            logger.debug(f"Alert state saved: {len(self._alert_history)} alerts")
        except Exception as e:
            logger.warning(f"Failed to save alert state: {e}")
    
    def _force_save_state(self) -> None:
        """Force immediate state save (for emergencies)."""
        self._flush_state_if_needed(force=True)
    
    # ============================================
    # ALERT GENERATORS (Called by other modules)
    # ============================================
    
    def alert_kill_switch_triggered(self, equity: float, floor: float) -> None:
        """Alert when kill switch triggers."""
        self.send_alert(
            AlertType.KILL_SWITCH_TRIGGERED,
            AlertSeverity.EMERGENCY,
            f"KILL SWITCH TRIGGERED! Equity ${equity:,.2f} fell below floor ${floor:,.2f}",
            {"equity": equity, "floor": floor}
        )
        self._force_save_state()  # Emergency triggers immediate save
    
    def alert_vol_fuse_triggered(self, drop_pct: float, oldest_equity: float, newest_equity: float) -> None:
        """Alert when VoL fuse triggers."""
        self.send_alert(
            AlertType.VOL_FUSE_TRIGGERED,
            AlertSeverity.EMERGENCY,
            f"VELOCITY-OF-LOSS FUSE! {drop_pct:.2%} drop in 60 seconds",
            {"drop_pct": drop_pct, "oldest_equity": oldest_equity, "newest_equity": newest_equity}
        )
        self._force_save_state()  # Emergency triggers immediate save
    
    def alert_latency_spike(self, latency_ms: float, threshold_ms: float) -> None:
        """Alert when latency spikes."""
        self.send_alert(
            AlertType.LATENCY_SPIKE,
            AlertSeverity.WARNING,
            f"LATENCY SPIKE: {latency_ms:.1f}ms > {threshold_ms}ms",
            {"latency_ms": latency_ms, "threshold_ms": threshold_ms}
        )
    
    def alert_exchange_outage(self, exchange: str, age_sec: float) -> None:
        """Alert when exchange outage detected."""
        self.send_alert(
            AlertType.EXCHANGE_OUTAGE,
            AlertSeverity.CRITICAL,
            f"EXCHANGE OUTAGE: {exchange} no heartbeat for {age_sec:.1f}s",
            {"exchange": exchange, "age_sec": age_sec}
        )

    def alert_rest_dns_failure(self, exchange: str, endpoint_domain: str, symbol: str, feed_type: str) -> None:
        """Record local alert when REST DNS fails while preserving feed truth."""
        self.send_alert(
            AlertType.REST_DNS_FAILURE,
            AlertSeverity.WARNING,
            f"REST DNS FAILURE: {exchange} {endpoint_domain} {symbol} {feed_type}",
            {
                "exchange": exchange,
                "endpoint_domain": endpoint_domain,
                "symbol": symbol,
                "feed_type": feed_type,
                "reason": "DNS_FAILURE_RECORDED",
                "market_truth": "MARKET_DATA_PARTIAL_TRUTH",
            },
        )
    
    def alert_zombie_orders(self, count: int, value: float, oldest_age_sec: float) -> None:
        """Alert when zombie orders detected."""
        self.send_alert(
            AlertType.ZOMBIE_ORDERS,
            AlertSeverity.WARNING,
            f"ZOMBIE ORDERS: {count} orders stuck for {oldest_age_sec:.1f}s (${value:,.2f})",
            {"count": count, "value": value, "oldest_age_sec": oldest_age_sec}
        )
    
    def alert_drawdown_limit(self, drawdown_pct: float, limit_pct: float) -> None:
        """Alert when drawdown limit reached."""
        self.send_alert(
            AlertType.DRAWDOWN_LIMIT,
            AlertSeverity.CRITICAL,
            f"DRAWDOWN LIMIT: {drawdown_pct:.2%} reached (limit {limit_pct:.0%})",
            {"drawdown_pct": drawdown_pct, "limit_pct": limit_pct}
        )
    
    def alert_position_limit(self, symbol: str, exposure: float, limit: float) -> None:
        """Alert when position limit approached."""
        self.send_alert(
            AlertType.POSITION_LIMIT,
            AlertSeverity.WARNING,
            f"POSITION LIMIT: {symbol} exposure {exposure:.2%} approaching limit {limit:.0%}",
            {"symbol": symbol, "exposure": exposure, "limit": limit}
        )
    
    def alert_strategy_error(self, strategy: str, error: str) -> None:
        """Alert when strategy error occurs."""
        self.send_alert(
            AlertType.STRATEGY_ERROR,
            AlertSeverity.WARNING,
            f"STRATEGY ERROR: {strategy} - {error[:200]}",
            {"strategy": strategy, "error": error[:500]}
        )
    
    # ============================================
    # STATE LOADING
    # ============================================
    
    def _load_state(self) -> None:
        """Load persistent alert state."""
        if not self.state_file.exists():
            return
        
        try:
            with open(self.state_file, 'r') as f:
                data = json.load(f)
            
            with self._lock:
                if data.get("alert_history"):
                    for alert_data in data["alert_history"][-500:]:
                        self._alert_history.append(Alert(
                            alert_type=AlertType(alert_data["alert_type"]),
                            severity=AlertSeverity(alert_data["severity"]),
                            message=alert_data["message"],
                            timestamp=datetime.fromisoformat(alert_data["timestamp"]),
                            data=alert_data.get("data", {})
                        ))
                
                if data.get("last_alert_time"):
                    for k, v in data["last_alert_time"].items():
                        self._last_alert_time[k] = datetime.fromisoformat(v)
            
            logger.info(f"Loaded alert state: {len(self._alert_history)} alerts")
        except Exception as e:
            logger.warning(f"Failed to load alert state: {e}")
    
    # ============================================
    # THREAD MANAGEMENT
    # ============================================
    
    def start(self) -> None:
        """Start sentinel monitoring threads."""
        if self._running:
            return
        
        self._running = True
        
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._alert_thread = threading.Thread(target=self._alert_loop, daemon=True)
        self._state_flusher_thread = threading.Thread(target=self._state_flusher_loop, daemon=True)
        
        self._monitor_thread.start()
        self._alert_thread.start()
        self._state_flusher_thread.start()
        
        logger.info("SovereignSentinel started")
    
    def stop(self) -> None:
        """Stop sentinel monitoring."""
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=2.0)
        if self._alert_thread:
            self._alert_thread.join(timeout=2.0)
        if self._state_flusher_thread:
            self._state_flusher_thread.join(timeout=2.0)
        
        # Final state flush
        self._flush_state_if_needed(force=True)
        logger.info("SovereignSentinel stopped")
    
    def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        while self._running:
            try:
                self._check_heartbeat()
                time.sleep(self.heartbeat_interval_sec / 2)
            except Exception as e:
                logger.error(f"Monitor loop error: {e}")
                time.sleep(5.0)
    
    def _alert_loop(self) -> None:
        """Alert processing loop."""
        while self._running:
            try:
                try:
                    alert = self._alert_queue.get(timeout=0.5)
                    self._dispatch_alert(alert)
                except queue.Empty:
                    pass
            except Exception as e:
                logger.error(f"Alert loop error: {e}")
    
    def _state_flusher_loop(self) -> None:
        """Background state flusher loop."""
        while self._running:
            try:
                time.sleep(self.state_flush_interval_sec)
                self._flush_state_if_needed()
            except Exception as e:
                logger.error(f"State flusher error: {e}")
    
    # ============================================
    # DIAGNOSTICS
    # ============================================
    
    def get_status(self) -> Dict[str, Any]:
        """Get sentinel status."""
        with self._lock:
            return {
                "running": self._running,
                "is_healthy": self._is_healthy,
                "last_heartbeat": self._last_heartbeat.isoformat() if self._last_heartbeat else None,
                "last_heartbeat_latency_ms": self._last_heartbeat_latency,
                "consecutive_missed": self._consecutive_missed,
                "alert_history_count": len(self._alert_history),
                "pending_alerts_count": len(self._pending_alerts),
                "alert_cooldown_sec": self.alert_cooldown_sec,
                "heartbeat_interval_sec": self.heartbeat_interval_sec,
                "latency_threshold_ms": self.latency_threshold_ms,
                "state_flush_interval_sec": self.state_flush_interval_sec,
                "last_state_save": self._last_state_save.isoformat() if self._last_state_save else None
            }
    
    def get_recent_alerts(self, count: int = 10) -> List[Dict[str, Any]]:
        """Get recent alerts."""
        with self._lock:
            return [
                {
                    "type": a.alert_type.value,
                    "severity": a.severity.value,
                    "message": a.message,
                    "timestamp": a.timestamp.isoformat(),
                    "data": a.data
                }
                for a in self._alert_history[-count:]
            ]
