"""
Telemetry Event Store — SQLite-backed, thread-safe, replay-capable.

Stores EventEnvelope objects with full queryability.
No business logic — pure storage and retrieval.
"""

import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import List, Optional, Dict, Any
from uuid import uuid4

from app.models.contracts import EventEnvelope
from app.models.enums import EventType

logger = logging.getLogger(__name__)


def _safe_event_type(value: Any) -> str:
    """
    Safely convert event_type to string.
    
    Handles both enum members and pre-stringified values.
    """
    if hasattr(value, "value"):
        return value.value
    return str(value)


class TelemetryEventStore:
    """
    Thread-safe SQLite event store for telemetry events.
    
    Schema:
        telemetry_events (
            event_id TEXT PRIMARY KEY,
            decision_uuid TEXT,
            parent_uuid TEXT,
            event_type TEXT NOT NULL,
            source_module TEXT NOT NULL,
            exchange_ts_ns INTEGER NOT NULL,
            receive_ts_ns INTEGER NOT NULL,
            decision_ts_ns INTEGER DEFAULT 0,
            sequence INTEGER DEFAULT 0,
            payload_json TEXT NOT NULL,
            created_at INTEGER DEFAULT (strftime('%s', 'now'))
        )
    
    Indexes:
        idx_decision_uuid, idx_event_type, idx_exchange_ts, idx_parent
    """
    
    def __init__(self, db_path: str = "data/telemetry.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._lock = threading.Lock()
        self._init_db()
        logger.info(f"TelemetryEventStore initialized: {self.db_path}")
    
    def _get_conn(self) -> sqlite3.Connection:
        """Get thread-local connection."""
        if not hasattr(self._local, 'conn'):
            self._local.conn = sqlite3.connect(str(self.db_path), timeout=5.0)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
        return self._local.conn
    
    def _init_db(self) -> None:
        """Initialize database schema if not exists."""
        with self._lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS telemetry_events (
                    event_id TEXT PRIMARY KEY,
                    decision_uuid TEXT,
                    parent_uuid TEXT,
                    event_type TEXT NOT NULL,
                    source_module TEXT NOT NULL,
                    exchange_ts_ns INTEGER NOT NULL,
                    receive_ts_ns INTEGER NOT NULL,
                    decision_ts_ns INTEGER DEFAULT 0,
                    sequence INTEGER DEFAULT 0,
                    payload_json TEXT NOT NULL,
                    created_at INTEGER DEFAULT (strftime('%s', 'now'))
                )
            """)
            
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_decision_uuid ON telemetry_events(decision_uuid)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_event_type ON telemetry_events(event_type)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_exchange_ts ON telemetry_events(exchange_ts_ns)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_parent ON telemetry_events(parent_uuid)")
            
            conn.commit()
    
    def record_event(self, event: EventEnvelope) -> str:
        """
        Record an event envelope.
        
        Args:
            event: Validated EventEnvelope
            
        Returns:
            event_id
        """
        event_type_str = _safe_event_type(event.event_type)
        
        with self._lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO telemetry_events (
                    event_id, decision_uuid, parent_uuid, event_type,
                    source_module, exchange_ts_ns, receive_ts_ns,
                    decision_ts_ns, sequence, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event.event_id,
                event.decision_uuid,
                event.parent_uuid,
                event_type_str,
                event.source_module,
                event.exchange_ts_ns,
                event.receive_ts_ns,
                event.decision_ts_ns,
                event.sequence,
                json.dumps(event.payload, default=str)
            ))
            
            conn.commit()
            logger.debug(f"Event recorded: {event.event_id} type={event_type_str}")
            return event.event_id
    
    def get_decision_chain(self, decision_uuid: str) -> List[Dict[str, Any]]:
        """
        Get all events for a decision, ordered by exchange timestamp.
        
        Returns:
            List of event dicts in chronological order
        """
        with self._lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT * FROM telemetry_events
                WHERE decision_uuid = ?
                ORDER BY exchange_ts_ns ASC, sequence ASC
            """, (decision_uuid,))
            
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    
    def get_events_by_type(self, event_type: str, limit: int = 1000) -> List[Dict[str, Any]]:
        """Get events by type, most recent first."""
        with self._lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT * FROM telemetry_events
                WHERE event_type = ?
                ORDER BY exchange_ts_ns DESC
                LIMIT ?
            """, (event_type, limit))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_events_by_timerange(self, start_ns: int, end_ns: int) -> List[Dict[str, Any]]:
        """Get events within timestamp range."""
        with self._lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT * FROM telemetry_events
                WHERE exchange_ts_ns BETWEEN ? AND ?
                ORDER BY exchange_ts_ns ASC
            """, (start_ns, end_ns))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_decision_outcome(self, decision_uuid: str) -> Dict[str, Any]:
        """
        Aggregate decision outcome: fill, rejection, or pending.
        
        Returns:
            {
                "decision_uuid": str,
                "has_fill": bool,
                "has_rejection": bool,
                "fill_event_id": str | None,
                "rejection_reason": str | None,
                "first_order_ts_ns": int | None,
                "last_event_ts_ns": int | None
            }
        """
        events = self.get_decision_chain(decision_uuid)
        
        result = {
            "decision_uuid": decision_uuid,
            "has_fill": False,
            "has_rejection": False,
            "fill_event_id": None,
            "rejection_reason": None,
            "first_order_ts_ns": None,
            "last_event_ts_ns": None,
        }
        
        for event in events:
            ts = event.get("exchange_ts_ns", 0)
            if result["first_order_ts_ns"] is None or ts < result["first_order_ts_ns"]:
                result["first_order_ts_ns"] = ts
            if result["last_event_ts_ns"] is None or ts > result["last_event_ts_ns"]:
                result["last_event_ts_ns"] = ts
            
            if event["event_type"] == "fill":
                result["has_fill"] = True
                try:
                    payload = json.loads(event["payload_json"])
                    result["fill_event_id"] = payload.get("fill_event_id")
                except:
                    pass
            
            if event["event_type"] == "order_rejected":
                result["has_rejection"] = True
                try:
                    payload = json.loads(event["payload_json"])
                    result["rejection_reason"] = payload.get("reason")
                except:
                    pass
        
        return result