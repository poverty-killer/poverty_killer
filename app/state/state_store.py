"""
State Store - SQLite-based Durable State Persistence
Single Source of Truth with WAL mode and atomic commits.
Ensures crash recovery and data integrity.
HARDENED: Added PRAGMA integrity_check on startup and backup() method for 24-hour redundancy.
"""

import sqlite3
import json
import threading
import logging
import shutil
from decimal import Decimal, InvalidOperation
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from contextlib import contextmanager
from pathlib import Path

from app.constants import DB_WAL_AUTOCHECKPOINT, DB_TIMEOUT_SECONDS, DB_JOURNAL_MODE, DB_SYNC_MODE
from app.utils.time_utils import now_ns

logger = logging.getLogger(__name__)


class StateStore:
    """
    SQLite-based state store with WAL mode for crash resilience.
    Provides atomic operations and transaction recovery.
    All state transitions are persisted before memory updates.
    """

    def __init__(self, db_path: str):
        """
        Initialize state store with SQLite database.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Thread-local connections for thread safety
        self._local = threading.local()

        # Initialize database schema
        self._init_database()

        # Run integrity check on startup
        integrity_ok = self.integrity_check()
        if not integrity_ok:
            logger.critical("Database integrity check FAILED on startup!")
            raise RuntimeError("Database corruption detected. Cannot start engine.")

        # Recover any uncommitted transactions
        self._recover_uncommitted()

        logger.info(f"StateStore initialized: {self.db_path}")

    @contextmanager
    def _get_connection(self):
        """
        Get thread-local database connection with WAL enabled.
        Yields connection, ensures proper cleanup.
        """
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(
                str(self.db_path),
                timeout=DB_TIMEOUT_SECONDS,
                isolation_level=None  # Autocommit mode, we manage transactions
            )
            self._local.conn.execute(f"PRAGMA journal_mode={DB_JOURNAL_MODE}")
            self._local.conn.execute(f"PRAGMA synchronous={DB_SYNC_MODE}")
            self._local.conn.execute(f"PRAGMA wal_autocheckpoint={DB_WAL_AUTOCHECKPOINT}")
            self._local.conn.row_factory = sqlite3.Row

        try:
            yield self._local.conn
        except Exception as e:
            logger.error(f"Database error: {e}")
            raise

    def _init_database(self):
        """Create all required tables if they don't exist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Positions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS positions (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    current_price REAL NOT NULL,
                    unrealized_pnl REAL NOT NULL,
                    realized_pnl REAL NOT NULL,
                    strategy TEXT NOT NULL,
                    opened_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_strategy_heartbeat TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    entry_latency_ms REAL
                )
            """)

            # Orders table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    price REAL,
                    status TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    exchange_order_id TEXT,
                    metadata TEXT,
                    latency_ms REAL
                )
            """)

            # Active order ID mapping table.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS order_id_mappings (
                    client_order_id TEXT NOT NULL,
                    broker TEXT NOT NULL,
                    symbol TEXT,
                    side TEXT,
                    order_type TEXT,
                    venue_order_id TEXT,
                    broker_order_id TEXT,
                    exchange_txid TEXT,
                    command_id_namespace TEXT NOT NULL,
                    command_order_id TEXT NOT NULL,
                    id_mapping_source TEXT,
                    submit_ts_ns INTEGER,
                    ack_ts_ns INTEGER,
                    status TEXT NOT NULL,
                    is_terminal INTEGER NOT NULL DEFAULT 0,
                    terminal_reason TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (client_order_id, broker)
                )
            """)

            # Passive reservation ledger persistence. This is durable fact
            # storage only; StateStore does not own exposure authority.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS reservation_ledger (
                    reservation_id TEXT PRIMARY KEY,
                    client_order_id TEXT NOT NULL,
                    decision_uuid TEXT,
                    reservation_dedupe_key TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    sleeve TEXT,
                    order_type TEXT,
                    original_qty TEXT NOT NULL,
                    open_qty TEXT NOT NULL,
                    filled_qty TEXT NOT NULL,
                    cancelled_qty TEXT NOT NULL,
                    price_basis TEXT,
                    notional_basis TEXT,
                    status TEXT NOT NULL,
                    confidence_weight TEXT,
                    created_at_ns INTEGER NOT NULL,
                    updated_at_ns INTEGER NOT NULL,
                    terminal_status TEXT,
                    terminal_reason TEXT,
                    terminal_source TEXT,
                    source_lifecycle_phase TEXT,
                    source_idempotency_key TEXT,
                    is_active INTEGER NOT NULL DEFAULT 0,
                    is_terminal INTEGER NOT NULL DEFAULT 0
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS reservation_release_tombstones (
                    release_idempotency_key TEXT PRIMARY KEY,
                    reservation_id TEXT NOT NULL,
                    client_order_id TEXT NOT NULL,
                    decision_uuid TEXT,
                    reservation_dedupe_key TEXT NOT NULL,
                    release_reason TEXT NOT NULL,
                    terminal_status TEXT,
                    terminal_source TEXT NOT NULL,
                    released_qty TEXT NOT NULL,
                    released_notional TEXT,
                    released_at_ns INTEGER NOT NULL,
                    source_event_id TEXT,
                    release_applied INTEGER NOT NULL DEFAULT 1,
                    exposure_release_scope TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS reservation_fill_progress (
                    fill_idempotency_key TEXT PRIMARY KEY,
                    reservation_id TEXT NOT NULL,
                    client_order_id TEXT NOT NULL,
                    cumulative_filled_qty TEXT NOT NULL,
                    fill_delta_qty TEXT,
                    status_source TEXT NOT NULL,
                    source_event_id TEXT,
                    applied_at_ns INTEGER NOT NULL
                )
            """)

            # Fills table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS fills (
                    id TEXT PRIMARY KEY,
                    order_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    price REAL NOT NULL,
                    fee REAL NOT NULL,
                    fee_currency TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    exchange_order_id TEXT,
                    latency_ms REAL
                )
            """)

            # Canonical broker-backed fill ledger. This table permits partial
            # hydration when broker truth supplies fill quantity/price/time but
            # fee or TCA detail is unavailable. The legacy fills table remains
            # stricter and is populated only when complete fee truth exists.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS broker_fill_ledger (
                    fill_id TEXT PRIMARY KEY,
                    broker_order_id TEXT NOT NULL,
                    client_order_id TEXT NOT NULL,
                    decision_uuid TEXT,
                    frame_id TEXT,
                    candidate_id TEXT,
                    snapshot_id TEXT,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    action TEXT,
                    quantity TEXT,
                    price TEXT,
                    notional TEXT,
                    fill_timestamp TEXT,
                    fill_ts_ns INTEGER,
                    broker_activity_id TEXT,
                    fee TEXT,
                    fee_currency TEXT,
                    liquidity_flag TEXT,
                    source TEXT NOT NULL,
                    hydration_status TEXT NOT NULL,
                    hydration_reason_code TEXT,
                    tca_status TEXT,
                    execution_quality_verdict TEXT,
                    modeled_entry_price TEXT,
                    modeled_net_edge TEXT,
                    realized_vs_modeled_netedge TEXT,
                    slippage TEXT,
                    slippage_bps TEXT,
                    fee_bps TEXT,
                    latency_decision_to_ack_ms TEXT,
                    latency_ack_to_fill_ms TEXT,
                    metadata TEXT,
                    created_at_ns INTEGER NOT NULL,
                    observed_at_ns INTEGER NOT NULL
                )
            """)

            # Portfolio snapshots table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    total_equity REAL NOT NULL,
                    cash REAL NOT NULL,
                    positions_value REAL NOT NULL,
                    unrealized_pnl REAL NOT NULL,
                    realized_pnl REAL NOT NULL,
                    exposure REAL NOT NULL,
                    leverage REAL NOT NULL,
                    buying_power REAL,
                    data TEXT
                )
            """)

            # Risk snapshots table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS risk_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    current_drawdown REAL NOT NULL,
                    max_drawdown REAL NOT NULL,
                    daily_pnl REAL NOT NULL,
                    weekly_pnl REAL NOT NULL,
                    positions_count INTEGER NOT NULL,
                    is_kill_switch_triggered INTEGER NOT NULL,
                    is_stale_data INTEGER NOT NULL,
                    current_risk_profile TEXT NOT NULL,
                    regime_at_snapshot TEXT,
                    data TEXT
                )
            """)

            # Strategy state table (for Shadow-Front, FLV, etc.)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS strategy_state (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    state TEXT NOT NULL,
                    data TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    transition_complete INTEGER DEFAULT 0,
                    previous_regime TEXT
                )
            """)

            # Events table (audit log)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    data TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
            """)

            # Control plane table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS control_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # Physical verification table (NEW)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS physical_verification (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    exchange_latency_ms REAL NOT NULL,
                    network_rtt_ms REAL NOT NULL,
                    order_size REAL NOT NULL,
                    price_impact_bps REAL NOT NULL,
                    expected_impact_bps REAL NOT NULL,
                    latency_impact_ratio REAL NOT NULL,
                    is_toxic INTEGER NOT NULL,
                    data TEXT
                )
            """)

            # Create indexes for performance
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_positions_symbol ON positions(symbol)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_positions_strategy ON positions(strategy)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_order_id_mappings_client ON order_id_mappings(client_order_id)")
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_order_id_mappings_venue ON order_id_mappings(broker, venue_order_id) WHERE venue_order_id IS NOT NULL")
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_order_id_mappings_broker ON order_id_mappings(broker, broker_order_id) WHERE broker_order_id IS NOT NULL")
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_order_id_mappings_txid ON order_id_mappings(broker, exchange_txid) WHERE exchange_txid IS NOT NULL")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_broker_fill_ledger_client ON broker_fill_ledger(client_order_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_broker_fill_ledger_broker_order ON broker_fill_ledger(broker_order_id)")
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_broker_fill_ledger_activity ON broker_fill_ledger(broker_activity_id) WHERE broker_activity_id IS NOT NULL")
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_reservation_ledger_active_dedupe ON reservation_ledger(reservation_dedupe_key) WHERE is_active = 1")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_reservation_ledger_client ON reservation_ledger(client_order_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_reservation_ledger_active ON reservation_ledger(is_active)")
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_reservation_release_once ON reservation_release_tombstones(reservation_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_reservation_release_dedupe ON reservation_release_tombstones(reservation_dedupe_key)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_reservation_fill_progress_reservation ON reservation_fill_progress(reservation_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_strategy_state_strategy ON strategy_state(strategy)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_physical_verification_timestamp ON physical_verification(timestamp)")

            conn.commit()

    def integrity_check(self) -> bool:
        """
        Run PRAGMA integrity_check on the database.
        
        Returns:
            True if database is intact, False otherwise
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("PRAGMA integrity_check")
                result = cursor.fetchone()
                if result and result[0] == "ok":
                    logger.info("Database integrity check passed")
                    return True
                else:
                    logger.error(f"Database integrity check failed: {result}")
                    return False
        except Exception as e:
            logger.error(f"Integrity check error: {e}")
            return False

    def backup(self, backup_path: Optional[str] = None) -> bool:
        """
        Create a backup of the database for 24-hour redundancy.
        
        Args:
            backup_path: Optional custom backup path
            
        Returns:
            True if backup successful
        """
        try:
            if backup_path is None:
                timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                backup_path = self.db_path.parent / f"{self.db_path.stem}_backup_{timestamp}.db"
            else:
                backup_path = Path(backup_path)
            
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Force WAL checkpoint to ensure all changes are written
            with self._get_connection() as conn:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            
            # Copy the database file
            shutil.copy2(self.db_path, backup_path)
            
            # Also copy WAL file if it exists
            wal_path = Path(str(self.db_path) + "-wal")
            if wal_path.exists():
                shutil.copy2(wal_path, Path(str(backup_path) + "-wal"))
            
            logger.info(f"Database backup created: {backup_path}")
            return True
            
        except Exception as e:
            logger.error(f"Backup failed: {e}")
            return False

    def _recover_uncommitted(self):
        """Recover any uncommitted transactions on startup."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Find incomplete state transitions
            cursor.execute("""
                SELECT * FROM strategy_state
                WHERE transition_complete = 0
                ORDER BY timestamp DESC LIMIT 100
            """)
            incomplete = cursor.fetchall()

            if incomplete:
                logger.warning(f"Found {len(incomplete)} incomplete state transitions. Marking as recovered.")
                for row in incomplete:
                    logger.info(f"Recovered: strategy={row['strategy']}, state={row['state']}, symbol={row['symbol']}")

                # Mark them as recovered (but not complete)
                cursor.execute("""
                    UPDATE strategy_state
                    SET transition_complete = 1
                    WHERE transition_complete = 0
                """)
                conn.commit()

            # Check WAL checkpoint
            cursor.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            result = cursor.fetchone()
            if result and result[0] > 0:
                logger.info(f"WAL checkpoint: {result[0]} frames written")

    def atomic_insert(self, table: str, data: Dict[str, Any]) -> bool:
        """
        Perform atomic insert with rollback on failure.

        Args:
            table: Target table name
            data: Dictionary of column -> value

        Returns:
            True if successful, False otherwise
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("BEGIN IMMEDIATE")

                columns = ', '.join(data.keys())
                placeholders = ', '.join(['?' for _ in data])
                values = list(data.values())

                cursor.execute(
                    f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
                    values
                )

                conn.commit()
                return True

        except Exception as e:
            logger.error(f"Atomic insert failed for {table}: {e}")
            return False

    def begin_transaction(self, tx_id: str, intent: Dict[str, Any]) -> bool:
        """
        Begin a transaction by writing intent to WAL.

        Args:
            tx_id: Unique transaction ID
            intent: Transaction intent data

        Returns:
            True if transaction started
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("BEGIN IMMEDIATE")

                cursor.execute("""
                    INSERT INTO events (event_type, source, data, timestamp)
                    VALUES (?, ?, ?, ?)
                """, ("TRANSACTION_START", tx_id, json.dumps(intent), datetime.utcnow().isoformat()))

                conn.commit()
                return True

        except Exception as e:
            logger.error(f"Failed to begin transaction {tx_id}: {e}")
            return False

    def commit_transaction(self, tx_id: str, result: Dict[str, Any]) -> bool:
        """
        Commit a transaction with result.

        Args:
            tx_id: Transaction ID
            result: Transaction result

        Returns:
            True if committed
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("BEGIN IMMEDIATE")

                cursor.execute("""
                    INSERT INTO events (event_type, source, data, timestamp)
                    VALUES (?, ?, ?, ?)
                """, ("TRANSACTION_COMMIT", tx_id, json.dumps(result), datetime.utcnow().isoformat()))

                conn.commit()
                return True

        except Exception as e:
            logger.error(f"Failed to commit transaction {tx_id}: {e}")
            return False

    def rollback_transaction(self, tx_id: str, error: str) -> bool:
        """
        Rollback a transaction with error reason.

        Args:
            tx_id: Transaction ID
            error: Error message

        Returns:
            True if rolled back
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("BEGIN IMMEDIATE")

                cursor.execute("""
                    INSERT INTO events (event_type, source, data, timestamp)
                    VALUES (?, ?, ?, ?)
                """, ("TRANSACTION_ROLLBACK", tx_id, json.dumps({"error": error}), datetime.utcnow().isoformat()))

                conn.commit()
                return True

        except Exception as e:
            logger.error(f"Failed to rollback transaction {tx_id}: {e}")
            return False

    def insert_position(self, position: Dict[str, Any]) -> bool:
        """Insert or replace a position."""
        return self.atomic_insert("positions", position)

    def update_position(self, position_id: str, updates: Dict[str, Any]) -> bool:
        """Update an existing position."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("BEGIN IMMEDIATE")

                updates["updated_at"] = datetime.utcnow().isoformat()
                set_clause = ', '.join([f"{k} = ?" for k in updates.keys()])
                values = list(updates.values()) + [position_id]

                cursor.execute(f"UPDATE positions SET {set_clause} WHERE id = ?", values)
                conn.commit()
                return True

        except Exception as e:
            logger.error(f"Failed to update position {position_id}: {e}")
            return False

    def delete_position(self, position_id: str) -> bool:
        """Delete a closed position."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("BEGIN IMMEDIATE")
                cursor.execute("DELETE FROM positions WHERE id = ?", (position_id,))
                conn.commit()
                return True

        except Exception as e:
            logger.error(f"Failed to delete position {position_id}: {e}")
            return False

    def get_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all open positions, optionally filtered by symbol."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if symbol:
                    cursor.execute("SELECT * FROM positions WHERE symbol = ?", (symbol,))
                else:
                    cursor.execute("SELECT * FROM positions")
                return [dict(row) for row in cursor.fetchall()]

        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
            return []

    def insert_order(self, order: Dict[str, Any]) -> bool:
        """Insert a new order."""
        return self.atomic_insert("orders", order)

    def update_order(self, order_id: str, updates: Dict[str, Any]) -> bool:
        """Update an existing order."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("BEGIN IMMEDIATE")

                updates["updated_at"] = datetime.utcnow().isoformat()
                set_clause = ', '.join([f"{k} = ?" for k in updates.keys()])
                values = list(updates.values()) + [order_id]

                cursor.execute(f"UPDATE orders SET {set_clause} WHERE id = ?", values)
                conn.commit()
                return True

        except Exception as e:
            logger.error(f"Failed to update order {order_id}: {e}")
            return False

    def upsert_order_id_mapping(self, mapping: Dict[str, Any]) -> bool:
        """Idempotently persist active client-to-venue order ID mapping."""
        required = ("client_order_id", "broker", "command_id_namespace", "command_order_id", "status")
        if any(not str(mapping.get(field) or "").strip() for field in required):
            logger.error("Order ID mapping missing required field")
            return False

        client_order_id = str(mapping["client_order_id"])
        broker = str(mapping["broker"])
        now = datetime.utcnow().isoformat()
        is_terminal = 1 if bool(mapping.get("is_terminal")) else 0

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("BEGIN IMMEDIATE")

                cursor.execute("""
                    SELECT * FROM order_id_mappings
                    WHERE client_order_id = ? AND broker = ?
                """, (client_order_id, broker))
                existing = cursor.fetchone()
                if existing and existing["is_terminal"] and not is_terminal:
                    logger.error("Refusing to reopen terminal order mapping: %s/%s", broker, client_order_id)
                    conn.rollback()
                    return False

                for column in ("venue_order_id", "broker_order_id", "exchange_txid"):
                    value = mapping.get(column)
                    if value is None:
                        continue
                    cursor.execute(
                        f"""
                        SELECT client_order_id FROM order_id_mappings
                        WHERE broker = ? AND {column} = ? AND client_order_id != ?
                        LIMIT 1
                        """,
                        (broker, str(value), client_order_id),
                    )
                    duplicate = cursor.fetchone()
                    if duplicate:
                        logger.error(
                            "Conflicting order ID mapping for %s %s=%s: existing client=%s new client=%s",
                            broker,
                            column,
                            value,
                            duplicate["client_order_id"],
                            client_order_id,
                        )
                        conn.rollback()
                        return False

                created_at = existing["created_at"] if existing else now
                record = {
                    "client_order_id": client_order_id,
                    "broker": broker,
                    "symbol": mapping.get("symbol"),
                    "side": mapping.get("side"),
                    "order_type": mapping.get("order_type"),
                    "venue_order_id": mapping.get("venue_order_id"),
                    "broker_order_id": mapping.get("broker_order_id"),
                    "exchange_txid": mapping.get("exchange_txid"),
                    "command_id_namespace": mapping["command_id_namespace"],
                    "command_order_id": mapping["command_order_id"],
                    "id_mapping_source": mapping.get("id_mapping_source"),
                    "submit_ts_ns": mapping.get("submit_ts_ns"),
                    "ack_ts_ns": mapping.get("ack_ts_ns"),
                    "status": mapping["status"],
                    "is_terminal": is_terminal,
                    "terminal_reason": mapping.get("terminal_reason"),
                    "created_at": created_at,
                    "updated_at": now,
                }

                columns = list(record.keys())
                placeholders = ", ".join(["?" for _ in columns])
                update_clause = ", ".join([
                    f"{column}=excluded.{column}"
                    for column in columns
                    if column not in {"client_order_id", "broker", "created_at"}
                ])
                cursor.execute(
                    f"""
                    INSERT INTO order_id_mappings ({", ".join(columns)})
                    VALUES ({placeholders})
                    ON CONFLICT(client_order_id, broker) DO UPDATE SET {update_clause}
                    """,
                    [record[column] for column in columns],
                )
                conn.commit()
                return True
        except Exception as e:
            logger.error("Failed to upsert order ID mapping %s/%s: %s", broker, client_order_id, e)
            return False

    def get_order_id_mapping(self, client_order_id: str, broker: str) -> Optional[Dict[str, Any]]:
        """Resolve active order ID mapping by client order ID and broker."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM order_id_mappings
                    WHERE client_order_id = ? AND broker = ?
                """, (client_order_id, broker))
                row = cursor.fetchone()
                if row is None:
                    return None
                result = dict(row)
                result["is_terminal"] = bool(result.get("is_terminal"))
                return result
        except Exception as e:
            logger.error("Failed to get order ID mapping %s/%s: %s", broker, client_order_id, e)
            return None

    def get_order_id_mapping_by_namespace(
        self,
        broker: str,
        id_namespace: str,
        order_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Resolve an order ID mapping by an explicit broker ID namespace."""
        column_by_namespace = {
            "client_order_id": "client_order_id",
            "venue_order_id": "venue_order_id",
            "broker_order_id": "broker_order_id",
            "exchange_txid": "exchange_txid",
            "command_order_id": "command_order_id",
        }
        column = column_by_namespace.get(id_namespace)
        if column is None:
            logger.error("Unsupported order ID mapping namespace: %s", id_namespace)
            return None

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    f"""
                    SELECT * FROM order_id_mappings
                    WHERE broker = ? AND {column} = ?
                    """,
                    (str(broker), str(order_id)),
                )
                rows = cursor.fetchall()
                if len(rows) != 1:
                    if len(rows) > 1:
                        logger.error(
                            "Ambiguous order ID mapping for %s %s=%s",
                            broker,
                            id_namespace,
                            order_id,
                        )
                    return None
                result = dict(rows[0])
                result["is_terminal"] = bool(result.get("is_terminal"))
                return result
        except Exception as e:
            logger.error(
                "Failed to resolve order ID mapping by %s/%s %s=%s: %s",
                broker,
                id_namespace,
                id_namespace,
                order_id,
                e,
            )
            return None

    def list_order_id_mappings(
        self,
        broker: Optional[str] = None,
        *,
        include_terminal: bool = True,
    ) -> List[Dict[str, Any]]:
        """List persisted order ID mappings for read-only reconcile scans."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                clauses = []
                values: List[Any] = []
                if broker is not None:
                    clauses.append("broker = ?")
                    values.append(str(broker))
                if not include_terminal:
                    clauses.append("is_terminal = 0")
                where_clause = f" WHERE {' AND '.join(clauses)}" if clauses else ""
                cursor.execute(
                    f"""
                    SELECT * FROM order_id_mappings
                    {where_clause}
                    ORDER BY updated_at DESC
                    """,
                    values,
                )
                results = []
                for row in cursor.fetchall():
                    result = dict(row)
                    result["is_terminal"] = bool(result.get("is_terminal"))
                    results.append(result)
                return results
        except Exception as e:
            logger.error("Failed to list order ID mappings: %s", e)
            return []

    def count_table_rows(self, table: str) -> int:
        """Count rows in known state tables for shutdown accounting."""
        allowed = {
            "orders",
            "fills",
            "broker_fill_ledger",
            "order_id_mappings",
            "reservation_ledger",
            "reservation_fill_progress",
            "reservation_release_tombstones",
        }
        if table not in allowed:
            raise ValueError(f"unsupported_state_table:{table}")
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                row = cursor.fetchone()
                return int(row[0]) if row is not None else 0
        except Exception as e:
            logger.error("Failed to count rows for %s: %s", table, e)
            return 0

    def mark_order_id_mapping_terminal(
        self,
        client_order_id: str,
        broker: str,
        *,
        status: str,
        terminal_reason: Optional[str] = None,
    ) -> bool:
        """Idempotently mark an order ID mapping terminal."""
        existing = self.get_order_id_mapping(client_order_id, broker)
        if existing is None:
            return False
        updated = dict(existing)
        updated["status"] = status
        updated["is_terminal"] = True
        updated["terminal_reason"] = terminal_reason
        return self.upsert_order_id_mapping(updated)

    @staticmethod
    def _reservation_bool(value: Any) -> int:
        return 1 if bool(value) else 0

    @staticmethod
    def _reservation_row(row: sqlite3.Row) -> Dict[str, Any]:
        result = dict(row)
        result["is_active"] = bool(result.get("is_active"))
        result["is_terminal"] = bool(result.get("is_terminal"))
        return result

    @staticmethod
    def _release_tombstone_row(row: sqlite3.Row) -> Dict[str, Any]:
        result = dict(row)
        result["release_applied"] = bool(result.get("release_applied"))
        return result

    @staticmethod
    def _decimal_or_none(value: Any) -> Optional[Decimal]:
        if value is None:
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None

    @staticmethod
    def _json_dict_or_empty(value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        if not value:
            return {}
        try:
            parsed = json.loads(str(value))
        except (TypeError, json.JSONDecodeError):
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}

    def upsert_reservation_ledger(self, reservation: Dict[str, Any]) -> bool:
        """
        Persist a reservation ledger fact without creating reservation authority.

        The active reservation dedupe key is unique while open, and release
        tombstones prevent accidental reopen after terminal release.
        """
        required = (
            "reservation_id",
            "client_order_id",
            "reservation_dedupe_key",
            "symbol",
            "side",
            "original_qty",
            "open_qty",
            "filled_qty",
            "cancelled_qty",
            "status",
        )
        if any(not str(reservation.get(field) or "").strip() for field in required):
            logger.error("Reservation ledger row missing required field")
            return False

        reservation_id = str(reservation["reservation_id"])
        dedupe_key = str(reservation["reservation_dedupe_key"])
        is_active = self._reservation_bool(reservation.get("is_active"))
        is_terminal = self._reservation_bool(reservation.get("is_terminal"))
        now = now_ns()

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("BEGIN IMMEDIATE")

                cursor.execute(
                    "SELECT * FROM reservation_ledger WHERE reservation_id = ?",
                    (reservation_id,),
                )
                existing = cursor.fetchone()
                if existing and existing["is_terminal"] and not is_terminal:
                    logger.error("Refusing to reopen terminal reservation: %s", reservation_id)
                    conn.rollback()
                    return False

                if is_active and not is_terminal:
                    cursor.execute(
                        """
                        SELECT reservation_id FROM reservation_release_tombstones
                        WHERE reservation_id = ? OR reservation_dedupe_key = ?
                        LIMIT 1
                        """,
                        (reservation_id, dedupe_key),
                    )
                    if cursor.fetchone() is not None:
                        logger.error("Refusing to reopen released reservation: %s", reservation_id)
                        conn.rollback()
                        return False

                    cursor.execute(
                        """
                        SELECT reservation_id FROM reservation_ledger
                        WHERE reservation_dedupe_key = ? AND is_active = 1 AND reservation_id != ?
                        LIMIT 1
                        """,
                        (dedupe_key, reservation_id),
                    )
                    duplicate = cursor.fetchone()
                    if duplicate is not None:
                        logger.error(
                            "Duplicate active reservation dedupe key %s existing=%s new=%s",
                            dedupe_key,
                            duplicate["reservation_id"],
                            reservation_id,
                        )
                        conn.rollback()
                        return False

                created_at_ns = (
                    int(existing["created_at_ns"])
                    if existing is not None
                    else int(reservation.get("created_at_ns") or now)
                )
                updated_at_ns = int(reservation.get("updated_at_ns") or now)
                record = {
                    "reservation_id": reservation_id,
                    "client_order_id": str(reservation["client_order_id"]),
                    "decision_uuid": reservation.get("decision_uuid"),
                    "reservation_dedupe_key": dedupe_key,
                    "symbol": str(reservation["symbol"]),
                    "side": str(reservation["side"]),
                    "sleeve": reservation.get("sleeve"),
                    "order_type": reservation.get("order_type"),
                    "original_qty": str(reservation["original_qty"]),
                    "open_qty": str(reservation["open_qty"]),
                    "filled_qty": str(reservation["filled_qty"]),
                    "cancelled_qty": str(reservation["cancelled_qty"]),
                    "price_basis": None if reservation.get("price_basis") is None else str(reservation.get("price_basis")),
                    "notional_basis": None if reservation.get("notional_basis") is None else str(reservation.get("notional_basis")),
                    "status": str(reservation["status"]),
                    "confidence_weight": None if reservation.get("confidence_weight") is None else str(reservation.get("confidence_weight")),
                    "created_at_ns": created_at_ns,
                    "updated_at_ns": updated_at_ns,
                    "terminal_status": reservation.get("terminal_status"),
                    "terminal_reason": reservation.get("terminal_reason"),
                    "terminal_source": reservation.get("terminal_source"),
                    "source_lifecycle_phase": reservation.get("source_lifecycle_phase"),
                    "source_idempotency_key": reservation.get("source_idempotency_key"),
                    "is_active": is_active,
                    "is_terminal": is_terminal,
                }
                columns = list(record.keys())
                placeholders = ", ".join(["?" for _ in columns])
                update_clause = ", ".join([
                    f"{column}=excluded.{column}"
                    for column in columns
                    if column not in {"reservation_id", "created_at_ns"}
                ])
                cursor.execute(
                    f"""
                    INSERT INTO reservation_ledger ({", ".join(columns)})
                    VALUES ({placeholders})
                    ON CONFLICT(reservation_id) DO UPDATE SET {update_clause}
                    """,
                    [record[column] for column in columns],
                )
                conn.commit()
                return True
        except Exception as e:
            logger.error("Failed to upsert reservation ledger %s: %s", reservation_id, e)
            return False

    def get_reservation_ledger(self, reservation_id: str) -> Optional[Dict[str, Any]]:
        """Read a persisted reservation ledger fact by reservation ID."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM reservation_ledger WHERE reservation_id = ?",
                    (str(reservation_id),),
                )
                row = cursor.fetchone()
                return None if row is None else self._reservation_row(row)
        except Exception as e:
            logger.error("Failed to get reservation ledger %s: %s", reservation_id, e)
            return None

    def list_reservation_ledger(
        self,
        *,
        active_only: bool = False,
        include_terminal: bool = True,
    ) -> List[Dict[str, Any]]:
        """List persisted reservation ledger facts for future recovery."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                clauses = []
                if active_only:
                    clauses.append("is_active = 1")
                if not include_terminal:
                    clauses.append("is_terminal = 0")
                where_clause = f" WHERE {' AND '.join(clauses)}" if clauses else ""
                cursor.execute(
                    f"""
                    SELECT * FROM reservation_ledger
                    {where_clause}
                    ORDER BY updated_at_ns DESC
                    """
                )
                return [self._reservation_row(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error("Failed to list reservation ledger: %s", e)
            return []

    def record_reservation_fill_progress(self, progress: Dict[str, Any]) -> bool:
        """Persist fill idempotency/progress without applying exposure mutation."""
        required = (
            "fill_idempotency_key",
            "reservation_id",
            "client_order_id",
            "cumulative_filled_qty",
            "status_source",
        )
        if any(not str(progress.get(field) or "").strip() for field in required):
            logger.error("Reservation fill progress missing required field")
            return False

        fill_key = str(progress["fill_idempotency_key"])
        reservation_id = str(progress["reservation_id"])
        cumulative = self._decimal_or_none(progress.get("cumulative_filled_qty"))
        if cumulative is None:
            logger.error("Reservation fill progress has invalid cumulative quantity")
            return False

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("BEGIN IMMEDIATE")
                cursor.execute(
                    "SELECT fill_idempotency_key FROM reservation_fill_progress WHERE fill_idempotency_key = ?",
                    (fill_key,),
                )
                if cursor.fetchone() is not None:
                    conn.commit()
                    return True

                cursor.execute(
                    """
                    SELECT cumulative_filled_qty FROM reservation_fill_progress
                    WHERE reservation_id = ?
                    """,
                    (reservation_id,),
                )
                max_seen: Optional[Decimal] = None
                for row in cursor.fetchall():
                    seen = self._decimal_or_none(row["cumulative_filled_qty"])
                    if seen is not None and (max_seen is None or seen > max_seen):
                        max_seen = seen
                if max_seen is not None and cumulative <= max_seen:
                    logger.error(
                        "Refusing non-advancing reservation fill progress: %s cumulative=%s max_seen=%s",
                        reservation_id,
                        cumulative,
                        max_seen,
                    )
                    conn.rollback()
                    return False

                cursor.execute(
                    """
                    INSERT INTO reservation_fill_progress (
                        fill_idempotency_key,
                        reservation_id,
                        client_order_id,
                        cumulative_filled_qty,
                        fill_delta_qty,
                        status_source,
                        source_event_id,
                        applied_at_ns
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        fill_key,
                        reservation_id,
                        str(progress["client_order_id"]),
                        str(progress["cumulative_filled_qty"]),
                        None if progress.get("fill_delta_qty") is None else str(progress.get("fill_delta_qty")),
                        str(progress["status_source"]),
                        progress.get("source_event_id"),
                        int(progress.get("applied_at_ns") or now_ns()),
                    ),
                )
                conn.commit()
                return True
        except Exception as e:
            logger.error("Failed to record reservation fill progress %s: %s", fill_key, e)
            return False

    def list_reservation_fill_progress(self, reservation_id: str) -> List[Dict[str, Any]]:
        """List persisted fill progress facts for one reservation."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT * FROM reservation_fill_progress
                    WHERE reservation_id = ?
                    ORDER BY applied_at_ns ASC
                    """,
                    (str(reservation_id),),
                )
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error("Failed to list reservation fill progress %s: %s", reservation_id, e)
            return []

    def record_reservation_release_tombstone(self, tombstone: Dict[str, Any]) -> bool:
        """Persist a release-once tombstone without releasing exposure."""
        required = (
            "release_idempotency_key",
            "reservation_id",
            "client_order_id",
            "reservation_dedupe_key",
            "release_reason",
            "terminal_source",
            "released_qty",
        )
        if any(not str(tombstone.get(field) or "").strip() for field in required):
            logger.error("Reservation release tombstone missing required field")
            return False
        if tombstone.get("exposure_release_scope", "reservation_only") != "reservation_only":
            logger.error("Reservation release tombstone has unsupported exposure release scope")
            return False

        release_key = str(tombstone["release_idempotency_key"])
        reservation_id = str(tombstone["reservation_id"])
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("BEGIN IMMEDIATE")
                cursor.execute(
                    "SELECT reservation_id FROM reservation_release_tombstones WHERE release_idempotency_key = ?",
                    (release_key,),
                )
                existing_key = cursor.fetchone()
                if existing_key is not None:
                    conn.commit()
                    return existing_key["reservation_id"] == reservation_id

                cursor.execute(
                    "SELECT release_idempotency_key FROM reservation_release_tombstones WHERE reservation_id = ?",
                    (reservation_id,),
                )
                if cursor.fetchone() is not None:
                    logger.error("Refusing duplicate reservation release tombstone: %s", reservation_id)
                    conn.rollback()
                    return False

                cursor.execute(
                    """
                    INSERT INTO reservation_release_tombstones (
                        release_idempotency_key,
                        reservation_id,
                        client_order_id,
                        decision_uuid,
                        reservation_dedupe_key,
                        release_reason,
                        terminal_status,
                        terminal_source,
                        released_qty,
                        released_notional,
                        released_at_ns,
                        source_event_id,
                        release_applied,
                        exposure_release_scope
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        release_key,
                        reservation_id,
                        str(tombstone["client_order_id"]),
                        tombstone.get("decision_uuid"),
                        str(tombstone["reservation_dedupe_key"]),
                        str(tombstone["release_reason"]),
                        tombstone.get("terminal_status"),
                        str(tombstone["terminal_source"]),
                        str(tombstone["released_qty"]),
                        None if tombstone.get("released_notional") is None else str(tombstone.get("released_notional")),
                        int(tombstone.get("released_at_ns") or now_ns()),
                        tombstone.get("source_event_id"),
                        1,
                        "reservation_only",
                    ),
                )
                conn.commit()
                return True
        except Exception as e:
            logger.error("Failed to record reservation release tombstone %s: %s", release_key, e)
            return False

    def get_reservation_release_tombstone(
        self,
        *,
        reservation_id: Optional[str] = None,
        release_idempotency_key: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Read a release-once tombstone by reservation ID or release key."""
        if not reservation_id and not release_idempotency_key:
            return None
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if release_idempotency_key:
                    cursor.execute(
                        "SELECT * FROM reservation_release_tombstones WHERE release_idempotency_key = ?",
                        (str(release_idempotency_key),),
                    )
                else:
                    cursor.execute(
                        "SELECT * FROM reservation_release_tombstones WHERE reservation_id = ?",
                        (str(reservation_id),),
                    )
                row = cursor.fetchone()
                return None if row is None else self._release_tombstone_row(row)
        except Exception as e:
            logger.error("Failed to get reservation release tombstone: %s", e)
            return None

    def insert_fill(self, fill: Dict[str, Any]) -> bool:
        """Insert a fill record."""
        return self.atomic_insert("fills", fill)

    def list_broker_fill_ledger(self, *, missing_fee_only: bool = False) -> List[Dict[str, Any]]:
        """List canonical broker-backed fill rows for reconciliation/accounting."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                where_clause = ""
                if missing_fee_only:
                    where_clause = "WHERE fee IS NULL OR fee = '' OR fee_currency IS NULL OR fee_currency = ''"
                cursor.execute(
                    f"""
                    SELECT * FROM broker_fill_ledger
                    {where_clause}
                    ORDER BY COALESCE(fill_ts_ns, observed_at_ns, created_at_ns, 0) DESC
                    """
                )
                rows = []
                for row in cursor.fetchall():
                    record = dict(row)
                    record["metadata"] = self._json_dict_or_empty(record.get("metadata"))
                    rows.append(record)
                return rows
        except Exception as e:
            logger.error("Failed to list broker fill ledger rows: %s", e)
            return []

    def update_broker_fill_fee_hydration(
        self,
        fill_id: str,
        *,
        fee: Any,
        fee_currency: str,
        fee_bps: Any = None,
        tca_status: Optional[str] = None,
        execution_quality_verdict: Optional[str] = None,
        realized_vs_modeled_netedge: Any = None,
        hydration_reason_code: str = "BROKER_CFEE_FEE_HYDRATED",
        metadata_updates: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Idempotently enrich an existing broker fill row with broker-confirmed fee truth."""
        safe_fill_id = str(fill_id or "").strip()
        safe_currency = str(fee_currency or "").strip()
        incoming_fee = self._decimal_or_none(fee)
        if not safe_fill_id or incoming_fee is None or not safe_currency:
            return "failed"

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("BEGIN IMMEDIATE")
                cursor.execute("SELECT * FROM broker_fill_ledger WHERE fill_id = ?", (safe_fill_id,))
                existing = cursor.fetchone()
                if existing is None:
                    conn.rollback()
                    return "missing"

                existing_dict = dict(existing)
                existing_fee = self._decimal_or_none(existing_dict.get("fee"))
                existing_currency = str(existing_dict.get("fee_currency") or "").strip()
                if existing_fee is not None or existing_currency:
                    if existing_fee == incoming_fee and existing_currency == safe_currency:
                        conn.rollback()
                        return "duplicate"
                    logger.error(
                        "Broker fill ledger fee conflict for %s existing=%s/%s incoming=%s/%s",
                        safe_fill_id,
                        existing_dict.get("fee"),
                        existing_currency,
                        str(incoming_fee),
                        safe_currency,
                    )
                    conn.rollback()
                    return "conflict"

                metadata = self._json_dict_or_empty(existing_dict.get("metadata"))
                metadata.update(metadata_updates or {})
                updates = {
                    "fee": str(incoming_fee),
                    "fee_currency": safe_currency,
                    "fee_bps": None if fee_bps is None else str(fee_bps),
                    "tca_status": tca_status or existing_dict.get("tca_status"),
                    "execution_quality_verdict": execution_quality_verdict or existing_dict.get("execution_quality_verdict"),
                    "realized_vs_modeled_netedge": (
                        existing_dict.get("realized_vs_modeled_netedge")
                        if realized_vs_modeled_netedge is None
                        else str(realized_vs_modeled_netedge)
                    ),
                    "hydration_status": "HYDRATED",
                    "hydration_reason_code": hydration_reason_code,
                    "metadata": json.dumps(metadata, sort_keys=True, default=str),
                    "observed_at_ns": now_ns(),
                }
                set_clause = ", ".join([f"{column} = ?" for column in updates])
                cursor.execute(
                    f"UPDATE broker_fill_ledger SET {set_clause} WHERE fill_id = ?",
                    [updates[column] for column in updates] + [safe_fill_id],
                )
                conn.commit()
                return "updated"
        except Exception as e:
            logger.error("Failed to update broker fill fee hydration %s: %s", fill_id, e)
            return "failed"

    def upsert_broker_fill_ledger(self, fill: Dict[str, Any]) -> str:
        """Insert a broker-backed fill ledger row idempotently.

        Returns one of: inserted, duplicate, conflict, failed.
        """
        required = ("fill_id", "broker_order_id", "client_order_id", "symbol", "side", "source", "hydration_status")
        if any(not str(fill.get(field) or "").strip() for field in required):
            logger.error("Broker fill ledger row missing required field")
            return "failed"
        now = now_ns()
        record = dict(fill)
        record.setdefault("created_at_ns", now)
        record.setdefault("observed_at_ns", now)
        if isinstance(record.get("metadata"), (dict, list, tuple)):
            record["metadata"] = json.dumps(record["metadata"], sort_keys=True, default=str)

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("BEGIN IMMEDIATE")
                cursor.execute("SELECT * FROM broker_fill_ledger WHERE fill_id = ?", (str(record["fill_id"]),))
                existing = cursor.fetchone()
                if existing is not None:
                    existing_dict = dict(existing)
                    for field in ("broker_order_id", "client_order_id", "symbol", "side", "quantity", "price"):
                        current = "" if existing_dict.get(field) is None else str(existing_dict.get(field))
                        incoming = "" if record.get(field) is None else str(record.get(field))
                        if current != incoming:
                            logger.error(
                                "Broker fill ledger conflict for %s field=%s existing=%s incoming=%s",
                                record["fill_id"],
                                field,
                                current,
                                incoming,
                            )
                            conn.rollback()
                            return "conflict"
                    conn.rollback()
                    return "duplicate"

                columns = list(record.keys())
                placeholders = ", ".join(["?" for _ in columns])
                cursor.execute(
                    f"""
                    INSERT INTO broker_fill_ledger ({", ".join(columns)})
                    VALUES ({placeholders})
                    """,
                    [record[column] for column in columns],
                )
                conn.commit()
                return "inserted"
        except Exception as e:
            logger.error("Failed to upsert broker fill ledger %s: %s", fill.get("fill_id"), e)
            return "failed"

    def count_fills_for_order(self, order_id: str) -> int:
        """Count local fill ledger rows for one client order ID."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                legacy_count = 0
                cursor.execute("SELECT COUNT(*) FROM fills WHERE order_id = ?", (str(order_id),))
                row = cursor.fetchone()
                if row is not None:
                    legacy_count = int(row[0])
                broker_count = 0
                cursor.execute("SELECT COUNT(*) FROM broker_fill_ledger WHERE client_order_id = ?", (str(order_id),))
                row = cursor.fetchone()
                if row is not None:
                    broker_count = int(row[0])
                return max(legacy_count, broker_count)
        except Exception as e:
            logger.error("Failed to count fills for order %s: %s", order_id, e)
            return 0

    def save_strategy_state(
        self,
        strategy: str,
        symbol: str,
        state: str,
        data: Dict[str, Any],
        transition_complete: bool = True,
        previous_regime: Optional[str] = None
    ) -> bool:
        """
        Save strategy state with atomic persistence.

        This is the core method for state machine persistence.
        Called BEFORE memory state is updated.

        Args:
            strategy: Strategy name (e.g., "shadow_front")
            symbol: Trading symbol
            state: Current state enum value
            data: Additional state data
            transition_complete: Whether transition is complete
            previous_regime: Previous market regime

        Returns:
            True if saved successfully
        """
        record = {
            "strategy": strategy,
            "symbol": symbol,
            "state": state,
            "data": json.dumps(data),
            "timestamp": datetime.utcnow().isoformat(),
            "transition_complete": 1 if transition_complete else 0,
            "previous_regime": previous_regime,
        }
        return self.atomic_insert("strategy_state", record)

    def get_last_strategy_state(self, strategy: str, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get the most recent state for a strategy.

        Used for crash recovery to restore state machine.

        Args:
            strategy: Strategy name
            symbol: Trading symbol

        Returns:
            State dict or None
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM strategy_state
                    WHERE strategy = ? AND symbol = ?
                    ORDER BY timestamp DESC LIMIT 1
                """, (strategy, symbol))

                row = cursor.fetchone()
                if row:
                    result = dict(row)
                    result["data"] = json.loads(result["data"])
                    return result
                return None

        except Exception as e:
            logger.error(f"Failed to get last state for {strategy}/{symbol}: {e}")
            return None

    def save_portfolio_snapshot(self, snapshot: Dict[str, Any]) -> bool:
        """Save a portfolio snapshot."""
        data_copy = snapshot.copy()
        data_copy["data"] = json.dumps(snapshot)
        return self.atomic_insert("portfolio_snapshots", data_copy)

    def save_risk_snapshot(self, snapshot: Dict[str, Any]) -> bool:
        """Save a risk snapshot."""
        data_copy = snapshot.copy()
        data_copy["data"] = json.dumps(snapshot)
        return self.atomic_insert("risk_snapshots", data_copy)

    def save_physical_verification(self, verification: Dict[str, Any]) -> bool:
        """Save a physical verification record."""
        data_copy = verification.copy()
        data_copy["data"] = json.dumps(verification)
        return self.atomic_insert("physical_verification", data_copy)

    def log_event(self, event_type: str, source: str, data: Dict[str, Any]) -> bool:
        """Log an event to the audit log."""
        record = {
            "event_type": event_type,
            "source": source,
            "data": json.dumps(data),
            "timestamp": datetime.utcnow().isoformat()
        }
        return self.atomic_insert("events", record)

    def list_events(
        self,
        *,
        event_type: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """List structured audit events without mutating state."""
        safe_limit = max(1, min(int(limit), 1000))
        clauses: List[str] = []
        params: List[Any] = []
        if event_type is not None:
            clauses.append("event_type = ?")
            params.append(str(event_type))
        if source is not None:
            clauses.append("source = ?")
            params.append(str(source))
        where_clause = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    f"""
                    SELECT * FROM events
                    {where_clause}
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    [*params, safe_limit],
                )
                rows = []
                for row in cursor.fetchall():
                    event = dict(row)
                    try:
                        event["data"] = json.loads(event.get("data") or "{}")
                    except Exception:
                        event["data_parse_error"] = True
                    rows.append(event)
                return rows
        except Exception as e:
            logger.error("Failed to list events: %s", e)
            return []

    def get_control_state(self, key: str) -> Optional[str]:
        """Get control state value."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT value FROM control_state WHERE key = ?", (key,))
                row = cursor.fetchone()
                return row["value"] if row else None

        except Exception as e:
            logger.error(f"Failed to get control state {key}: {e}")
            return None

    def set_control_state(self, key: str, value: str) -> bool:
        """Set control state value."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("BEGIN IMMEDIATE")
                cursor.execute("""
                    INSERT OR REPLACE INTO control_state (key, value, updated_at)
                    VALUES (?, ?, ?)
                """, (key, value, datetime.utcnow().isoformat()))
                conn.commit()
                return True

        except Exception as e:
            logger.error(f"Failed to set control state {key}: {e}")
            return False

    def checkpoint(self) -> bool:
        """Force WAL checkpoint."""
        try:
            with self._get_connection() as conn:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                return True
        except Exception as e:
            logger.error(f"Checkpoint failed: {e}")
            return False

    def vacuum(self) -> bool:
        """Vacuum database to reclaim space."""
        try:
            with self._get_connection() as conn:
                conn.execute("VACUUM")
                return True
        except Exception as e:
            logger.error(f"Vacuum failed: {e}")
            return False

    def close(self):
        """Close all database connections."""
        if hasattr(self._local, 'conn') and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
        logger.info("StateStore closed")
