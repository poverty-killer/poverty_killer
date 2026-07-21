"""
State Store - SQLite-based Durable State Persistence
Single Source of Truth with WAL mode and atomic commits.
Ensures crash recovery and data integrity.
HARDENED: Added PRAGMA integrity_check on startup and backup() method for 24-hour redundancy.
"""

import sqlite3
import json
import hashlib
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

    def __init__(self, db_path: str, *, read_only: bool = False):
        """
        Initialize state store with SQLite database.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self._read_only = bool(read_only)
        if self._read_only:
            if not self.db_path.is_file():
                raise FileNotFoundError(self.db_path)
        else:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Thread-local connections for thread safety
        self._local = threading.local()

        # Read-only consumers inspect the existing authority without running
        # schema creation or transaction recovery against the runtime database.
        if not self._read_only:
            self._init_database()

        # Run integrity check on startup
        integrity_ok = self.integrity_check()
        if not integrity_ok:
            logger.critical("Database integrity check FAILED on startup!")
            raise RuntimeError("Database corruption detected. Cannot start engine.")

        # Recover any uncommitted transactions only in the writable owner.
        if not self._read_only:
            self._recover_uncommitted()

        logger.info(f"StateStore initialized: {self.db_path}")

    @contextmanager
    def _get_connection(self):
        """
        Get thread-local database connection with WAL enabled.
        Yields connection, ensures proper cleanup.
        """
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            if self._read_only:
                database_uri = f"{self.db_path.resolve().as_uri()}?mode=ro"
                self._local.conn = sqlite3.connect(
                    database_uri,
                    timeout=DB_TIMEOUT_SECONDS,
                    isolation_level=None,
                    uri=True,
                )
                self._local.conn.execute("PRAGMA query_only=ON")
            else:
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
                    order_metadata TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (client_order_id, broker)
                )
            """)
            cursor.execute("PRAGMA table_info(order_id_mappings)")
            order_mapping_columns = {str(row[1]) for row in cursor.fetchall()}
            if "order_metadata" not in order_mapping_columns:
                cursor.execute("ALTER TABLE order_id_mappings ADD COLUMN order_metadata TEXT")

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

            # Immutable broker inventory facts and reconciliation projections.
            # Executable quantities are TEXT-backed Decimals. The legacy REAL
            # positions/fills tables remain compatibility surfaces only.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS broker_inventory_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    replaces_event_id TEXT,
                    broker_order_id TEXT,
                    client_order_id TEXT,
                    fill_id TEXT,
                    baseline_snapshot_id TEXT,
                    symbol TEXT,
                    side TEXT,
                    action TEXT,
                    quantity TEXT,
                    price TEXT,
                    fee TEXT,
                    fee_currency TEXT,
                    quantity_semantics TEXT NOT NULL,
                    sleeve TEXT,
                    event_ts_ns INTEGER,
                    observed_at_ns INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    metadata TEXT
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS broker_inventory_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    broker TEXT NOT NULL,
                    environment TEXT NOT NULL,
                    endpoint_family TEXT NOT NULL,
                    account_suffix TEXT NOT NULL,
                    baseline_snapshot_id TEXT,
                    parent_snapshot_id TEXT,
                    observed_at_ns INTEGER NOT NULL,
                    position_count INTEGER NOT NULL,
                    open_order_count INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    book_hash TEXT NOT NULL,
                    reason_codes TEXT NOT NULL,
                    metadata TEXT,
                    created_at_ns INTEGER NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS broker_inventory_snapshot_positions (
                    snapshot_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    broker_qty TEXT NOT NULL,
                    avg_entry_price TEXT,
                    mark_price TEXT,
                    quantity_step TEXT,
                    metadata TEXT,
                    PRIMARY KEY (snapshot_id, symbol)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS broker_inventory_lot_projections (
                    snapshot_id TEXT NOT NULL,
                    lot_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    sleeve TEXT,
                    provenance TEXT NOT NULL,
                    original_qty TEXT NOT NULL,
                    remaining_qty TEXT NOT NULL,
                    sold_qty TEXT NOT NULL,
                    avg_entry_price TEXT,
                    source_event_id TEXT,
                    baseline_snapshot_id TEXT,
                    acquired_at_ns INTEGER,
                    metadata TEXT,
                    PRIMARY KEY (snapshot_id, lot_id)
                )
            """)

            # Immutable Alpaca crypto catalog and derived-universe evidence.
            # StateStore persists and integrity-checks facts; capability_registry
            # remains the sole owner of normalization and entry eligibility.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS broker_asset_catalog_snapshots (
                    catalog_snapshot_id TEXT PRIMARY KEY,
                    schema_version TEXT NOT NULL,
                    broker TEXT NOT NULL,
                    environment TEXT NOT NULL,
                    endpoint_family TEXT NOT NULL,
                    expected_account_suffix TEXT NOT NULL,
                    actual_account_suffix TEXT NOT NULL,
                    observed_at_ns INTEGER NOT NULL,
                    valid_until_ns INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    source_hash TEXT NOT NULL,
                    snapshot_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reason_codes TEXT NOT NULL,
                    item_count INTEGER NOT NULL,
                    created_at_ns INTEGER NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS broker_asset_catalog_items (
                    catalog_snapshot_id TEXT NOT NULL,
                    record_key TEXT NOT NULL,
                    asset_id TEXT NOT NULL,
                    raw_symbol TEXT NOT NULL,
                    normalized_symbol TEXT NOT NULL,
                    aliases TEXT NOT NULL,
                    status TEXT NOT NULL,
                    tradable INTEGER,
                    fractionable INTEGER,
                    marginable INTEGER,
                    shortable INTEGER,
                    min_order_size TEXT,
                    min_trade_increment TEXT,
                    price_increment TEXT,
                    exchange TEXT NOT NULL,
                    asset_class TEXT NOT NULL,
                    observed_at_ns INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    capability_valid INTEGER NOT NULL,
                    reason_codes TEXT NOT NULL,
                    PRIMARY KEY (catalog_snapshot_id, record_key)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS broker_crypto_universe_snapshots (
                    universe_snapshot_id TEXT PRIMARY KEY,
                    schema_version TEXT NOT NULL,
                    catalog_snapshot_id TEXT NOT NULL,
                    broker TEXT NOT NULL,
                    environment TEXT NOT NULL,
                    endpoint_family TEXT NOT NULL,
                    account_suffix TEXT NOT NULL,
                    account_status TEXT NOT NULL,
                    crypto_status TEXT NOT NULL,
                    trading_blocked INTEGER,
                    account_blocked INTEGER,
                    trade_suspended_by_user INTEGER,
                    execution_adapter TEXT NOT NULL,
                    execution_adapter_available INTEGER,
                    funded_quote_currencies TEXT NOT NULL,
                    market_data_symbols TEXT NOT NULL,
                    priority_symbols TEXT NOT NULL,
                    held_symbols TEXT NOT NULL,
                    open_order_symbols TEXT NOT NULL,
                    observed_at_ns INTEGER NOT NULL,
                    valid_until_ns INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    reason_codes TEXT NOT NULL,
                    universe_hash TEXT NOT NULL,
                    membership_count INTEGER NOT NULL,
                    created_at_ns INTEGER NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS broker_crypto_universe_memberships (
                    universe_snapshot_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    record_key TEXT,
                    asset_id TEXT,
                    included_for_entry INTEGER NOT NULL,
                    monitor_required INTEGER NOT NULL,
                    priority_rank INTEGER,
                    reason_codes TEXT NOT NULL,
                    PRIMARY KEY (universe_snapshot_id, symbol)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS market_data_universe_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    schema_version TEXT NOT NULL,
                    catalog_snapshot_id TEXT NOT NULL,
                    broker_universe_snapshot_id TEXT NOT NULL,
                    as_of_ns INTEGER NOT NULL,
                    observation_cutoff_ns INTEGER NOT NULL,
                    created_at_ns INTEGER NOT NULL,
                    activation_mode TEXT NOT NULL,
                    execution_authorized INTEGER NOT NULL,
                    provider_id TEXT NOT NULL,
                    execution_location TEXT NOT NULL,
                    snapshot_hash TEXT NOT NULL,
                    membership_count INTEGER NOT NULL,
                    payload TEXT NOT NULL
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
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_inventory_events_baseline ON broker_inventory_events(baseline_snapshot_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_inventory_events_client ON broker_inventory_events(client_order_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_inventory_events_symbol ON broker_inventory_events(symbol)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_inventory_snapshots_account ON broker_inventory_snapshots(account_suffix, observed_at_ns)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_inventory_positions_symbol ON broker_inventory_snapshot_positions(symbol)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_inventory_lots_symbol ON broker_inventory_lot_projections(symbol)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_asset_catalog_account ON broker_asset_catalog_snapshots(actual_account_suffix, observed_at_ns)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_asset_catalog_symbol ON broker_asset_catalog_items(normalized_symbol)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_crypto_universe_account ON broker_crypto_universe_snapshots(account_suffix, observed_at_ns)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_crypto_universe_catalog ON broker_crypto_universe_snapshots(catalog_snapshot_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_crypto_universe_symbol ON broker_crypto_universe_memberships(symbol)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_market_data_universe_lineage ON market_data_universe_snapshots(catalog_snapshot_id, broker_universe_snapshot_id, as_of_ns)")
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
                    "order_metadata": (
                        json.dumps(mapping.get("order_metadata"), sort_keys=True, default=str)
                        if isinstance(mapping.get("order_metadata"), (dict, list, tuple))
                        else mapping.get("order_metadata")
                    ),
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
                result["order_metadata"] = self._json_dict_or_empty(result.get("order_metadata"))
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
                result["order_metadata"] = self._json_dict_or_empty(result.get("order_metadata"))
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
        strict: bool = False,
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
                    result["order_metadata"] = self._json_dict_or_empty(result.get("order_metadata"))
                    results.append(result)
                return results
        except Exception as e:
            logger.error("Failed to list order ID mappings: %s", e)
            if strict:
                raise RuntimeError("order_id_mapping_read_failed") from e
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
            "broker_inventory_events",
            "broker_inventory_snapshots",
            "broker_inventory_snapshot_positions",
            "broker_inventory_lot_projections",
            "broker_asset_catalog_snapshots",
            "broker_asset_catalog_items",
            "broker_crypto_universe_snapshots",
            "broker_crypto_universe_memberships",
            "market_data_universe_snapshots",
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

    def update_broker_fill_metadata(self, fill_id: str, metadata_updates: Dict[str, Any]) -> str:
        """Idempotently enrich broker fill metadata without inventing broker facts."""
        safe_fill_id = str(fill_id or "").strip()
        if not safe_fill_id or not isinstance(metadata_updates, dict):
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
                metadata = self._json_dict_or_empty(existing_dict.get("metadata"))
                metadata.update(metadata_updates)
                cursor.execute(
                    """
                    UPDATE broker_fill_ledger
                    SET metadata = ?, observed_at_ns = ?
                    WHERE fill_id = ?
                    """,
                    (json.dumps(metadata, sort_keys=True, default=str), now_ns(), safe_fill_id),
                )
                conn.commit()
                return "updated"
        except Exception as e:
            logger.error("Failed to update broker fill metadata %s: %s", fill_id, e)
            return "failed"

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

    @staticmethod
    def _text_or_none(value: Any, *, lower: bool = False) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        return text.lower() if lower else text

    @staticmethod
    def _int_or_none(value: Any) -> Optional[int]:
        if value is None or isinstance(value, bool):
            return None
        try:
            return int(value)
        except (TypeError, ValueError, OverflowError):
            return None

    @staticmethod
    def _stable_hash(value: Any) -> str:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _json_list_or_empty(value: Any) -> List[Any]:
        if isinstance(value, (list, tuple)):
            return list(value)
        if not value:
            return []
        try:
            parsed = json.loads(str(value))
        except (TypeError, json.JSONDecodeError):
            return []
        return list(parsed) if isinstance(parsed, list) else []

    @staticmethod
    def _nullable_bool_to_sql(value: Any) -> Optional[int]:
        if type(value) is bool:
            return 1 if value else 0
        return None

    @staticmethod
    def _nullable_bool_from_sql(value: Any) -> Optional[bool]:
        if value is None:
            return None
        return bool(value)

    @staticmethod
    def _capability_decimal_text(value: Any, *, field_name: str) -> Optional[str]:
        if value is None or str(value).strip() == "":
            return None
        if isinstance(value, bool) or isinstance(value, float):
            raise ValueError(f"crypto_catalog_{field_name}_invalid")
        try:
            parsed = Decimal(str(value).strip())
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ValueError(f"crypto_catalog_{field_name}_invalid") from exc
        if not parsed.is_finite() or parsed <= Decimal("0"):
            raise ValueError(f"crypto_catalog_{field_name}_invalid")
        return format(parsed, "f")

    @classmethod
    def _broker_asset_catalog_hash(cls, snapshot: Dict[str, Any], assets: List[Dict[str, Any]]) -> str:
        stable = {
            "schema_version": snapshot.get("schema_version"),
            "broker": snapshot.get("broker"),
            "environment": snapshot.get("environment"),
            "endpoint_family": snapshot.get("endpoint_family"),
            "expected_account_suffix": snapshot.get("expected_account_suffix"),
            "actual_account_suffix": snapshot.get("actual_account_suffix"),
            "observed_at_ns": int(snapshot.get("observed_at_ns") or 0),
            "valid_until_ns": int(snapshot.get("valid_until_ns") or 0),
            "source": snapshot.get("source"),
            "source_hash": snapshot.get("source_hash"),
            "assets": assets,
        }
        return cls._stable_hash(stable)

    @classmethod
    def _broker_crypto_universe_hash(
        cls,
        snapshot: Dict[str, Any],
        memberships: List[Dict[str, Any]],
    ) -> str:
        stable = {
            "schema_version": snapshot.get("schema_version"),
            "catalog_snapshot_id": snapshot.get("catalog_snapshot_id"),
            "broker": snapshot.get("broker"),
            "environment": snapshot.get("environment"),
            "endpoint_family": snapshot.get("endpoint_family"),
            "account_suffix": snapshot.get("account_suffix"),
            "account_status": snapshot.get("account_status"),
            "crypto_status": snapshot.get("crypto_status"),
            "trading_blocked": snapshot.get("trading_blocked"),
            "account_blocked": snapshot.get("account_blocked"),
            "trade_suspended_by_user": snapshot.get("trade_suspended_by_user"),
            "execution_adapter": snapshot.get("execution_adapter"),
            "execution_adapter_available": snapshot.get("execution_adapter_available"),
            "funded_quote_currencies": cls._json_list_or_empty(snapshot.get("funded_quote_currencies")),
            "market_data_symbols": cls._json_list_or_empty(snapshot.get("market_data_symbols")),
            "priority_symbols": cls._json_list_or_empty(snapshot.get("priority_symbols")),
            "held_symbols": cls._json_list_or_empty(snapshot.get("held_symbols")),
            "open_order_symbols": cls._json_list_or_empty(snapshot.get("open_order_symbols")),
            "observed_at_ns": int(snapshot.get("observed_at_ns") or 0),
            "valid_until_ns": int(snapshot.get("valid_until_ns") or 0),
            "status": snapshot.get("status"),
            "reason_codes": cls._json_list_or_empty(snapshot.get("reason_codes")),
            "memberships": memberships,
        }
        return cls._stable_hash(stable)

    @classmethod
    def _broker_inventory_book_hash(
        cls,
        snapshot: Dict[str, Any],
        positions: List[Dict[str, Any]],
        lots: List[Dict[str, Any]],
    ) -> str:
        """Hash the semantic projection, independent of SQLite JSON encoding."""
        snapshot_payload = {
            key: snapshot.get(key)
            for key in (
                "snapshot_id",
                "broker",
                "environment",
                "endpoint_family",
                "account_suffix",
                "baseline_snapshot_id",
                "parent_snapshot_id",
                "observed_at_ns",
                "status",
            )
        }
        snapshot_payload["position_count"] = int(
            snapshot.get("position_count")
            if snapshot.get("position_count") is not None
            else len(positions)
        )
        snapshot_payload["open_order_count"] = int(snapshot.get("open_order_count") or 0)
        raw_reasons = snapshot.get("reason_codes") or ()
        if isinstance(raw_reasons, str):
            try:
                raw_reasons = json.loads(raw_reasons)
            except json.JSONDecodeError:
                raw_reasons = (raw_reasons,)
        snapshot_payload["reason_codes"] = tuple(str(item) for item in raw_reasons)
        snapshot_payload["metadata"] = cls._json_dict_or_empty(snapshot.get("metadata"))

        position_payload = []
        for row in positions:
            position_payload.append(
                {
                    key: row.get(key)
                    for key in (
                        "snapshot_id",
                        "symbol",
                        "broker_qty",
                        "avg_entry_price",
                        "mark_price",
                        "quantity_step",
                    )
                }
                | {"metadata": cls._json_dict_or_empty(row.get("metadata"))}
            )
        position_payload.sort(key=lambda row: row["symbol"])

        lot_payload = []
        for row in lots:
            lot_payload.append(
                {
                    key: row.get(key)
                    for key in (
                        "snapshot_id",
                        "lot_id",
                        "symbol",
                        "sleeve",
                        "provenance",
                        "original_qty",
                        "remaining_qty",
                        "sold_qty",
                        "avg_entry_price",
                        "source_event_id",
                        "baseline_snapshot_id",
                        "acquired_at_ns",
                    )
                }
                | {"metadata": cls._json_dict_or_empty(row.get("metadata"))}
            )
        lot_payload.sort(key=lambda row: (row["symbol"], row["acquired_at_ns"] or 0, row["lot_id"]))
        return cls._stable_hash(
            {
                "snapshot": snapshot_payload,
                "positions": position_payload,
                "lots": lot_payload,
            }
        )

    @staticmethod
    def _inventory_decimal_text(
        value: Any,
        *,
        field_name: str,
        required: bool,
        positive: bool = False,
        non_negative: bool = False,
    ) -> Any:
        if value is None or str(value).strip() == "":
            return False if required else None
        try:
            decimal_value = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            logger.error("Invalid Decimal inventory field %s", field_name)
            return False
        if not decimal_value.is_finite():
            logger.error("Non-finite Decimal inventory field %s", field_name)
            return False
        if positive and decimal_value <= Decimal("0"):
            return False
        if non_negative and decimal_value < Decimal("0"):
            return False
        return str(decimal_value)

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
        strict: bool = False,
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
            if strict:
                raise RuntimeError("reservation_ledger_read_failed") from e
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

    def list_reservation_fill_progress(
        self,
        reservation_id: str,
        *,
        strict: bool = False,
    ) -> List[Dict[str, Any]]:
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
            if strict:
                raise RuntimeError("reservation_fill_progress_read_failed") from e
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
        strict: bool = False,
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
            if strict:
                raise RuntimeError("reservation_release_tombstone_read_failed") from e
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

    def persist_broker_crypto_catalog_universe(self, catalog: Any, universe: Any) -> str:
        """Atomically persist immutable catalog and derived-universe evidence."""
        if self._read_only:
            raise RuntimeError("state_store_read_only")
        catalog_value = catalog.to_dict() if callable(getattr(catalog, "to_dict", None)) else catalog
        universe_value = universe.to_dict() if callable(getattr(universe, "to_dict", None)) else universe
        if not isinstance(catalog_value, dict) or not isinstance(universe_value, dict):
            raise ValueError("crypto_catalog_universe_mapping_required")

        catalog_header = {
            key: catalog_value.get(key)
            for key in (
                "catalog_snapshot_id",
                "schema_version",
                "broker",
                "environment",
                "endpoint_family",
                "expected_account_suffix",
                "actual_account_suffix",
                "observed_at_ns",
                "valid_until_ns",
                "source",
                "source_hash",
                "snapshot_hash",
                "status",
            )
        }
        for field_name in (
            "catalog_snapshot_id",
            "schema_version",
            "broker",
            "environment",
            "endpoint_family",
            "expected_account_suffix",
            "actual_account_suffix",
            "source",
            "source_hash",
            "snapshot_hash",
            "status",
        ):
            if type(catalog_header.get(field_name)) is not str:
                raise ValueError(f"crypto_catalog_{field_name}_invalid")
        if not isinstance(catalog_value.get("reason_codes") or (), (list, tuple)):
            raise ValueError("crypto_catalog_reason_codes_invalid")
        if not all(type(item) is str for item in catalog_value.get("reason_codes") or ()):
            raise ValueError("crypto_catalog_reason_code_invalid")
        catalog_header["reason_codes"] = list(catalog_value.get("reason_codes") or ())
        assets: List[Dict[str, Any]] = []
        record_keys: set[str] = set()
        for raw in catalog_value.get("assets") or ():
            if not isinstance(raw, dict):
                raise ValueError("crypto_catalog_asset_mapping_required")
            for field_name in (
                "record_key",
                "asset_id",
                "raw_symbol",
                "normalized_symbol",
                "status",
                "exchange",
                "asset_class",
                "source",
            ):
                if type(raw.get(field_name)) is not str:
                    raise ValueError(f"crypto_catalog_{field_name}_invalid")
            record_key = raw["record_key"].strip()
            if not record_key or record_key in record_keys:
                raise ValueError("crypto_catalog_record_key_invalid_or_duplicate")
            record_keys.add(record_key)
            decimal_values: Dict[str, Optional[str]] = {}
            for field_name in ("min_order_size", "min_trade_increment", "price_increment"):
                decimal_values[field_name] = self._capability_decimal_text(
                    raw.get(field_name),
                    field_name=field_name,
                )
            for field_name in ("tradable", "fractionable", "marginable", "shortable"):
                if raw.get(field_name) is not None and type(raw.get(field_name)) is not bool:
                    raise ValueError(f"crypto_catalog_{field_name}_invalid")
            if type(raw.get("capability_valid")) is not bool:
                raise ValueError("crypto_catalog_capability_valid_invalid")
            if not isinstance(raw.get("aliases") or (), (list, tuple)):
                raise ValueError("crypto_catalog_aliases_invalid")
            if not all(type(item) is str for item in raw.get("aliases") or ()):
                raise ValueError("crypto_catalog_alias_invalid")
            if not isinstance(raw.get("reason_codes") or (), (list, tuple)):
                raise ValueError("crypto_catalog_asset_reason_codes_invalid")
            if not all(type(item) is str for item in raw.get("reason_codes") or ()):
                raise ValueError("crypto_catalog_asset_reason_code_invalid")
            if type(raw.get("observed_at_ns")) is not int:
                raise ValueError("crypto_catalog_observed_at_ns_invalid")
            assets.append(
                {
                    "record_key": record_key,
                    "asset_id": raw["asset_id"],
                    "raw_symbol": raw["raw_symbol"],
                    "normalized_symbol": raw["normalized_symbol"],
                    "aliases": list(raw.get("aliases") or ()),
                    "status": raw["status"],
                    "tradable": raw.get("tradable"),
                    "fractionable": raw.get("fractionable"),
                    "marginable": raw.get("marginable"),
                    "shortable": raw.get("shortable"),
                    **decimal_values,
                    "exchange": raw["exchange"],
                    "asset_class": raw["asset_class"],
                    "observed_at_ns": raw["observed_at_ns"],
                    "source": raw["source"],
                    "capability_valid": raw.get("capability_valid") is True,
                    "reason_codes": list(raw.get("reason_codes") or ()),
                }
            )
        assets.sort(key=lambda row: (row["normalized_symbol"], row["record_key"]))
        catalog_header["observed_at_ns"] = int(catalog_header.get("observed_at_ns") or 0)
        catalog_header["valid_until_ns"] = int(catalog_header.get("valid_until_ns") or 0)
        expected_catalog_hash = self._broker_asset_catalog_hash(catalog_header, assets)
        if str(catalog_header.get("snapshot_hash") or "") != expected_catalog_hash:
            raise ValueError("broker_asset_catalog_hash_invalid")
        if str(catalog_header.get("catalog_snapshot_id") or "") != f"catalog-{expected_catalog_hash[:24]}":
            raise ValueError("broker_asset_catalog_id_invalid")

        universe_header = {
            key: universe_value.get(key)
            for key in (
                "universe_snapshot_id",
                "schema_version",
                "catalog_snapshot_id",
                "broker",
                "environment",
                "endpoint_family",
                "account_suffix",
                "account_status",
                "crypto_status",
                "trading_blocked",
                "account_blocked",
                "trade_suspended_by_user",
                "execution_adapter",
                "execution_adapter_available",
                "funded_quote_currencies",
                "market_data_symbols",
                "priority_symbols",
                "held_symbols",
                "open_order_symbols",
                "observed_at_ns",
                "valid_until_ns",
                "status",
                "universe_hash",
            )
        }
        for field_name in (
            "universe_snapshot_id",
            "schema_version",
            "catalog_snapshot_id",
            "broker",
            "environment",
            "endpoint_family",
            "account_suffix",
            "account_status",
            "crypto_status",
            "execution_adapter",
            "status",
            "universe_hash",
        ):
            if type(universe_header.get(field_name)) is not str:
                raise ValueError(f"crypto_universe_{field_name}_invalid")
        if not isinstance(universe_value.get("reason_codes") or (), (list, tuple)):
            raise ValueError("crypto_universe_reason_codes_invalid")
        if not all(type(item) is str for item in universe_value.get("reason_codes") or ()):
            raise ValueError("crypto_universe_reason_code_invalid")
        universe_header["reason_codes"] = list(universe_value.get("reason_codes") or ())
        for field_name in (
            "trading_blocked",
            "account_blocked",
            "trade_suspended_by_user",
            "execution_adapter_available",
        ):
            if universe_header.get(field_name) is not None and type(universe_header.get(field_name)) is not bool:
                raise ValueError(f"crypto_universe_{field_name}_invalid")
        for field_name in (
            "funded_quote_currencies",
            "market_data_symbols",
            "priority_symbols",
            "held_symbols",
            "open_order_symbols",
        ):
            raw_values = universe_header.get(field_name)
            if not isinstance(raw_values, (list, tuple)):
                raise ValueError(f"crypto_universe_{field_name}_invalid")
            if not all(type(item) is str for item in raw_values):
                raise ValueError(f"crypto_universe_{field_name}_item_invalid")
            universe_header[field_name] = list(raw_values)
        memberships: List[Dict[str, Any]] = []
        symbols: set[str] = set()
        for raw in universe_value.get("memberships") or ():
            if not isinstance(raw, dict):
                raise ValueError("crypto_universe_membership_mapping_required")
            if type(raw.get("symbol")) is not str:
                raise ValueError("crypto_universe_symbol_invalid_or_duplicate")
            symbol = raw["symbol"].strip().upper()
            if not symbol or symbol in symbols:
                raise ValueError("crypto_universe_symbol_invalid_or_duplicate")
            symbols.add(symbol)
            if type(raw.get("included_for_entry")) is not bool or type(raw.get("monitor_required")) is not bool:
                raise ValueError("crypto_universe_membership_boolean_invalid")
            priority_rank = raw.get("priority_rank")
            if priority_rank is not None and (type(priority_rank) is not int or priority_rank < 0):
                raise ValueError("crypto_universe_priority_rank_invalid")
            if not isinstance(raw.get("reason_codes") or (), (list, tuple)):
                raise ValueError("crypto_universe_membership_reason_codes_invalid")
            if not all(type(item) is str for item in raw.get("reason_codes") or ()):
                raise ValueError("crypto_universe_membership_reason_code_invalid")
            for field_name in ("record_key", "asset_id"):
                if raw.get(field_name) is not None and type(raw.get(field_name)) is not str:
                    raise ValueError(f"crypto_universe_membership_{field_name}_invalid")
            memberships.append(
                {
                    "record_key": raw.get("record_key"),
                    "asset_id": raw.get("asset_id"),
                    "symbol": symbol,
                    "included_for_entry": raw.get("included_for_entry") is True,
                    "monitor_required": raw.get("monitor_required") is True,
                    "priority_rank": int(priority_rank) if priority_rank is not None else None,
                    "reason_codes": list(raw.get("reason_codes") or ()),
                }
            )
        memberships.sort(key=lambda row: row["symbol"])
        universe_header["observed_at_ns"] = int(universe_header.get("observed_at_ns") or 0)
        universe_header["valid_until_ns"] = int(universe_header.get("valid_until_ns") or 0)
        if universe_header.get("catalog_snapshot_id") != catalog_header.get("catalog_snapshot_id"):
            raise ValueError("crypto_universe_catalog_lineage_mismatch")
        if universe_header.get("account_suffix") != catalog_header.get("actual_account_suffix"):
            raise ValueError("crypto_universe_account_lineage_mismatch")
        if universe_header.get("endpoint_family") != catalog_header.get("endpoint_family"):
            raise ValueError("crypto_universe_endpoint_lineage_mismatch")
        expected_universe_hash = self._broker_crypto_universe_hash(universe_header, memberships)
        if str(universe_header.get("universe_hash") or "") != expected_universe_hash:
            raise ValueError("broker_crypto_universe_hash_invalid")
        if str(universe_header.get("universe_snapshot_id") or "") != f"universe-{expected_universe_hash[:24]}":
            raise ValueError("broker_crypto_universe_id_invalid")

        created_at_ns = now_ns()
        catalog_id = str(catalog_header["catalog_snapshot_id"])
        universe_id = str(universe_header["universe_snapshot_id"])
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("BEGIN IMMEDIATE")
                cursor.execute(
                    "SELECT snapshot_hash FROM broker_asset_catalog_snapshots WHERE catalog_snapshot_id = ?",
                    (catalog_id,),
                )
                existing_catalog = cursor.fetchone()
                if existing_catalog is not None and str(existing_catalog[0]) != expected_catalog_hash:
                    conn.rollback()
                    return "conflict"
                if existing_catalog is None:
                    cursor.execute(
                        """
                        INSERT INTO broker_asset_catalog_snapshots (
                            catalog_snapshot_id, schema_version, broker, environment, endpoint_family,
                            expected_account_suffix, actual_account_suffix, observed_at_ns, valid_until_ns,
                            source, source_hash, snapshot_hash, status, reason_codes, item_count, created_at_ns
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            catalog_id,
                            catalog_header["schema_version"],
                            catalog_header["broker"],
                            catalog_header["environment"],
                            catalog_header["endpoint_family"],
                            catalog_header["expected_account_suffix"],
                            catalog_header["actual_account_suffix"],
                            catalog_header["observed_at_ns"],
                            catalog_header["valid_until_ns"],
                            catalog_header["source"],
                            catalog_header["source_hash"],
                            expected_catalog_hash,
                            catalog_header["status"],
                            json.dumps(catalog_header["reason_codes"], separators=(",", ":")),
                            len(assets),
                            created_at_ns,
                        ),
                    )
                    for asset in assets:
                        cursor.execute(
                            """
                            INSERT INTO broker_asset_catalog_items (
                                catalog_snapshot_id, record_key, asset_id, raw_symbol, normalized_symbol,
                                aliases, status, tradable, fractionable, marginable, shortable,
                                min_order_size, min_trade_increment, price_increment, exchange, asset_class,
                                observed_at_ns, source, capability_valid, reason_codes
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                catalog_id,
                                asset["record_key"],
                                asset["asset_id"],
                                asset["raw_symbol"],
                                asset["normalized_symbol"],
                                json.dumps(asset["aliases"], separators=(",", ":")),
                                asset["status"],
                                self._nullable_bool_to_sql(asset["tradable"]),
                                self._nullable_bool_to_sql(asset["fractionable"]),
                                self._nullable_bool_to_sql(asset["marginable"]),
                                self._nullable_bool_to_sql(asset["shortable"]),
                                asset["min_order_size"],
                                asset["min_trade_increment"],
                                asset["price_increment"],
                                asset["exchange"],
                                asset["asset_class"],
                                asset["observed_at_ns"],
                                asset["source"],
                                1 if asset["capability_valid"] else 0,
                                json.dumps(asset["reason_codes"], separators=(",", ":")),
                            ),
                        )

                cursor.execute(
                    "SELECT universe_hash FROM broker_crypto_universe_snapshots WHERE universe_snapshot_id = ?",
                    (universe_id,),
                )
                existing_universe = cursor.fetchone()
                if existing_universe is not None:
                    if str(existing_universe[0]) != expected_universe_hash:
                        conn.rollback()
                        return "conflict"
                    conn.commit()
                    return "duplicate"
                cursor.execute(
                    """
                    INSERT INTO broker_crypto_universe_snapshots (
                        universe_snapshot_id, schema_version, catalog_snapshot_id, broker, environment,
                        endpoint_family, account_suffix, account_status, crypto_status,
                        trading_blocked, account_blocked, trade_suspended_by_user,
                        execution_adapter, execution_adapter_available, funded_quote_currencies,
                        market_data_symbols, priority_symbols, held_symbols, open_order_symbols,
                        observed_at_ns, valid_until_ns, status, reason_codes, universe_hash,
                        membership_count, created_at_ns
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        universe_id,
                        universe_header["schema_version"],
                        catalog_id,
                        universe_header["broker"],
                        universe_header["environment"],
                        universe_header["endpoint_family"],
                        universe_header["account_suffix"],
                        universe_header["account_status"],
                        universe_header["crypto_status"],
                        self._nullable_bool_to_sql(universe_header["trading_blocked"]),
                        self._nullable_bool_to_sql(universe_header["account_blocked"]),
                        self._nullable_bool_to_sql(universe_header["trade_suspended_by_user"]),
                        universe_header["execution_adapter"],
                        self._nullable_bool_to_sql(universe_header["execution_adapter_available"]),
                        json.dumps(universe_header["funded_quote_currencies"], separators=(",", ":")),
                        json.dumps(universe_header["market_data_symbols"], separators=(",", ":")),
                        json.dumps(universe_header["priority_symbols"], separators=(",", ":")),
                        json.dumps(universe_header["held_symbols"], separators=(",", ":")),
                        json.dumps(universe_header["open_order_symbols"], separators=(",", ":")),
                        universe_header["observed_at_ns"],
                        universe_header["valid_until_ns"],
                        universe_header["status"],
                        json.dumps(universe_header["reason_codes"], separators=(",", ":")),
                        expected_universe_hash,
                        len(memberships),
                        created_at_ns,
                    ),
                )
                for membership in memberships:
                    cursor.execute(
                        """
                        INSERT INTO broker_crypto_universe_memberships (
                            universe_snapshot_id, symbol, record_key, asset_id, included_for_entry,
                            monitor_required, priority_rank, reason_codes
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            universe_id,
                            membership["symbol"],
                            membership["record_key"],
                            membership["asset_id"],
                            1 if membership["included_for_entry"] else 0,
                            1 if membership["monitor_required"] else 0,
                            membership["priority_rank"],
                            json.dumps(membership["reason_codes"], separators=(",", ":")),
                        ),
                    )
                conn.commit()
                return "persisted"
        except Exception as exc:
            logger.error("Failed to persist broker crypto catalog/universe %s: %s", universe_id, exc)
            raise RuntimeError("broker_crypto_catalog_universe_persist_failed") from exc

    def get_broker_asset_catalog_snapshot(
        self,
        catalog_snapshot_id: str,
        *,
        strict: bool = False,
    ) -> Optional[Dict[str, Any]]:
        safe_id = str(catalog_snapshot_id or "").strip()
        if not safe_id:
            if strict:
                raise RuntimeError("broker_asset_catalog_id_required")
            return None
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM broker_asset_catalog_snapshots WHERE catalog_snapshot_id = ?", (safe_id,))
                header_row = cursor.fetchone()
                if header_row is None:
                    return None
                result = dict(header_row)
                result["reason_codes"] = self._json_list_or_empty(result.get("reason_codes"))
                cursor.execute(
                    """
                    SELECT * FROM broker_asset_catalog_items
                    WHERE catalog_snapshot_id = ?
                    ORDER BY normalized_symbol, record_key
                    """,
                    (safe_id,),
                )
                assets: List[Dict[str, Any]] = []
                for row in cursor.fetchall():
                    asset = dict(row)
                    asset.pop("catalog_snapshot_id", None)
                    asset["aliases"] = self._json_list_or_empty(asset.get("aliases"))
                    asset["reason_codes"] = self._json_list_or_empty(asset.get("reason_codes"))
                    for field_name in ("tradable", "fractionable", "marginable", "shortable"):
                        asset[field_name] = self._nullable_bool_from_sql(asset.get(field_name))
                    asset["capability_valid"] = bool(asset.get("capability_valid"))
                    assets.append(asset)
                result["assets"] = assets
                result["asset_count"] = len(assets)
                if strict:
                    if int(result.get("item_count") or 0) != len(assets):
                        raise RuntimeError("broker_asset_catalog_item_count_integrity_failed")
                    actual_hash = self._broker_asset_catalog_hash(result, assets)
                    expected_hash = str(result.get("snapshot_hash") or "")
                    if actual_hash != expected_hash or safe_id != f"catalog-{actual_hash[:24]}":
                        raise RuntimeError("broker_asset_catalog_hash_integrity_failed")
                return result
        except RuntimeError:
            raise
        except Exception as exc:
            logger.error("Failed to get broker asset catalog %s: %s", safe_id, exc)
            if strict:
                raise RuntimeError("broker_asset_catalog_read_failed") from exc
            return None

    def get_broker_crypto_universe_snapshot(
        self,
        universe_snapshot_id: str,
        *,
        strict: bool = False,
    ) -> Optional[Dict[str, Any]]:
        safe_id = str(universe_snapshot_id or "").strip()
        if not safe_id:
            if strict:
                raise RuntimeError("broker_crypto_universe_id_required")
            return None
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM broker_crypto_universe_snapshots WHERE universe_snapshot_id = ?",
                    (safe_id,),
                )
                header_row = cursor.fetchone()
                if header_row is None:
                    return None
                result = dict(header_row)
                result["reason_codes"] = self._json_list_or_empty(result.get("reason_codes"))
                for field_name in (
                    "trading_blocked",
                    "account_blocked",
                    "trade_suspended_by_user",
                    "execution_adapter_available",
                ):
                    result[field_name] = self._nullable_bool_from_sql(result.get(field_name))
                for field_name in (
                    "funded_quote_currencies",
                    "market_data_symbols",
                    "priority_symbols",
                    "held_symbols",
                    "open_order_symbols",
                ):
                    result[field_name] = self._json_list_or_empty(result.get(field_name))
                cursor.execute(
                    """
                    SELECT * FROM broker_crypto_universe_memberships
                    WHERE universe_snapshot_id = ? ORDER BY symbol
                    """,
                    (safe_id,),
                )
                memberships: List[Dict[str, Any]] = []
                for row in cursor.fetchall():
                    membership = dict(row)
                    membership.pop("universe_snapshot_id", None)
                    membership["included_for_entry"] = bool(membership.get("included_for_entry"))
                    membership["monitor_required"] = bool(membership.get("monitor_required"))
                    membership["reason_codes"] = self._json_list_or_empty(membership.get("reason_codes"))
                    memberships.append(membership)
                result["memberships"] = memberships
                result["entry_symbols"] = [row["symbol"] for row in sorted(
                    (row for row in memberships if row["included_for_entry"]),
                    key=lambda row: (row["priority_rank"] is None, row["priority_rank"] or 0, row["symbol"]),
                )]
                result["monitor_symbols"] = sorted(row["symbol"] for row in memberships if row["monitor_required"])
                result["runtime_symbols"] = list(dict.fromkeys([*result["entry_symbols"], *result["monitor_symbols"]]))
                if strict:
                    if int(result.get("membership_count") or 0) != len(memberships):
                        raise RuntimeError("broker_crypto_universe_membership_count_integrity_failed")
                    actual_hash = self._broker_crypto_universe_hash(result, memberships)
                    expected_hash = str(result.get("universe_hash") or "")
                    if actual_hash != expected_hash or safe_id != f"universe-{actual_hash[:24]}":
                        raise RuntimeError("broker_crypto_universe_hash_integrity_failed")
                return result
        except RuntimeError:
            raise
        except Exception as exc:
            logger.error("Failed to get broker crypto universe %s: %s", safe_id, exc)
            if strict:
                raise RuntimeError("broker_crypto_universe_read_failed") from exc
            return None

    def get_broker_crypto_capability_evidence(
        self,
        *,
        catalog_snapshot_id: str,
        universe_snapshot_id: str,
        strict: bool = False,
    ) -> Optional[Dict[str, Any]]:
        catalog = self.get_broker_asset_catalog_snapshot(catalog_snapshot_id, strict=strict)
        universe = self.get_broker_crypto_universe_snapshot(universe_snapshot_id, strict=strict)
        if catalog is None or universe is None:
            return None
        if universe.get("catalog_snapshot_id") != catalog.get("catalog_snapshot_id"):
            if strict:
                raise RuntimeError("broker_crypto_capability_lineage_integrity_failed")
            return None
        if universe.get("account_suffix") != catalog.get("actual_account_suffix"):
            if strict:
                raise RuntimeError("broker_crypto_capability_account_integrity_failed")
            return None
        if universe.get("endpoint_family") != catalog.get("endpoint_family"):
            if strict:
                raise RuntimeError("broker_crypto_capability_endpoint_integrity_failed")
            return None
        return {"catalog": catalog, "universe": universe}

    @staticmethod
    def _validate_market_data_universe_columns(stored: Dict[str, Any], normalized: Any) -> None:
        memberships = normalized.memberships
        expected = {
            "snapshot_id": normalized.snapshot_id,
            "schema_version": normalized.schema_version,
            "catalog_snapshot_id": normalized.catalog_snapshot_id,
            "broker_universe_snapshot_id": normalized.broker_universe_snapshot_id,
            "as_of_ns": normalized.as_of_ns,
            "observation_cutoff_ns": normalized.observation_cutoff_ns,
            "created_at_ns": normalized.created_at_ns,
            "activation_mode": normalized.activation_mode,
            "execution_authorized": 0,
            "provider_id": normalized.provider_id,
            "execution_location": normalized.execution_location,
            "snapshot_hash": normalized.snapshot_hash,
            "membership_count": len(memberships),
        }
        integer_fields = {
            "as_of_ns",
            "observation_cutoff_ns",
            "created_at_ns",
            "execution_authorized",
            "membership_count",
        }
        for field_name, expected_value in expected.items():
            stored_value = stored.get(field_name)
            if field_name in integer_fields:
                try:
                    stored_value = int(stored_value)
                except (TypeError, ValueError) as exc:
                    raise RuntimeError(
                        f"market_data_universe_column_integrity_failed:{field_name}"
                    ) from exc
            else:
                stored_value = str(stored_value or "")
            if stored_value != expected_value:
                raise RuntimeError(f"market_data_universe_column_integrity_failed:{field_name}")

    def persist_market_data_universe_snapshot(self, snapshot: Any) -> str:
        """Persist one immutable observe-only market-data universe snapshot."""
        if self._read_only:
            raise RuntimeError("state_store_read_only")
        value = snapshot.to_dict() if callable(getattr(snapshot, "to_dict", None)) else snapshot
        if not isinstance(value, dict):
            raise ValueError("market_data_universe_mapping_required")
        from app.market.capability_registry import MarketDataUniverseSnapshot

        normalized = MarketDataUniverseSnapshot.from_dict(value)
        value = normalized.to_dict()
        memberships = value["memberships"]
        snapshot_id = normalized.snapshot_id
        snapshot_hash = normalized.snapshot_hash
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("BEGIN IMMEDIATE")
                cursor.execute(
                    "SELECT * FROM market_data_universe_snapshots WHERE snapshot_id = ?",
                    (snapshot_id,),
                )
                existing = cursor.fetchone()
                if existing is not None:
                    stored = dict(existing)
                    if str(stored.get("snapshot_hash") or "") != snapshot_hash or str(stored.get("payload") or "") != payload:
                        conn.rollback()
                        raise RuntimeError("market_data_universe_snapshot_conflict")
                    self._validate_market_data_universe_columns(stored, normalized)
                    conn.rollback()
                    return "duplicate"
                cursor.execute(
                    """
                    INSERT INTO market_data_universe_snapshots (
                        snapshot_id, schema_version, catalog_snapshot_id,
                        broker_universe_snapshot_id, as_of_ns, observation_cutoff_ns,
                        created_at_ns, activation_mode, execution_authorized,
                        provider_id, execution_location, snapshot_hash,
                        membership_count, payload
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot_id,
                        value["schema_version"],
                        value["catalog_snapshot_id"],
                        value["broker_universe_snapshot_id"],
                        value["as_of_ns"],
                        value["observation_cutoff_ns"],
                        value["created_at_ns"],
                        value["activation_mode"],
                        0,
                        value["provider_id"],
                        value["execution_location"],
                        snapshot_hash,
                        len(memberships),
                        payload,
                    ),
                )
                conn.commit()
                return "persisted"
        except RuntimeError:
            raise
        except Exception as exc:
            logger.error("Failed to persist market-data universe %s: %s", snapshot_id, exc)
            raise RuntimeError("market_data_universe_persist_failed") from exc

    def get_market_data_universe_snapshot(
        self,
        snapshot_id: str,
        *,
        strict: bool = False,
    ) -> Optional[Dict[str, Any]]:
        safe_id = str(snapshot_id or "").strip()
        if not safe_id:
            if strict:
                raise RuntimeError("market_data_universe_snapshot_id_required")
            return None
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM market_data_universe_snapshots WHERE snapshot_id = ?",
                    (safe_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    return None
                stored = dict(row)
                try:
                    value = json.loads(str(stored.get("payload") or ""))
                except json.JSONDecodeError as exc:
                    raise RuntimeError("market_data_universe_payload_invalid") from exc
                if not isinstance(value, dict):
                    raise RuntimeError("market_data_universe_payload_invalid")
                if strict:
                    memberships = value.get("memberships")
                    if not isinstance(memberships, list) or len(memberships) != int(stored.get("membership_count") or 0):
                        raise RuntimeError("market_data_universe_membership_count_integrity_failed")
                    from app.market.capability_registry import MarketDataUniverseSnapshot

                    try:
                        normalized = MarketDataUniverseSnapshot.from_dict(value)
                    except ValueError as exc:
                        raise RuntimeError("market_data_universe_semantic_integrity_failed") from exc
                    if normalized.snapshot_id != safe_id or str(stored.get("snapshot_hash") or "") != normalized.snapshot_hash:
                        raise RuntimeError("market_data_universe_hash_integrity_failed")
                    self._validate_market_data_universe_columns(stored, normalized)
                return value
        except RuntimeError:
            raise
        except Exception as exc:
            logger.error("Failed to get market-data universe %s: %s", safe_id, exc)
            if strict:
                raise RuntimeError("market_data_universe_read_failed") from exc
            return None

    def get_latest_market_data_universe_snapshot(
        self,
        *,
        catalog_snapshot_id: str,
        broker_universe_snapshot_id: str,
        strict: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Return the newest immutable ranking snapshot for exact broker lineage."""
        catalog_id = str(catalog_snapshot_id or "").strip()
        universe_id = str(broker_universe_snapshot_id or "").strip()
        if not catalog_id or not universe_id:
            if strict:
                raise RuntimeError("market_data_universe_lineage_required")
            return None
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT snapshot_id
                    FROM market_data_universe_snapshots
                    WHERE catalog_snapshot_id = ? AND broker_universe_snapshot_id = ?
                    ORDER BY as_of_ns DESC, created_at_ns DESC, snapshot_id DESC
                    LIMIT 1
                    """,
                    (catalog_id, universe_id),
                )
                row = cursor.fetchone()
            if row is None:
                return None
            value = self.get_market_data_universe_snapshot(str(row[0]), strict=strict)
            if strict and value is not None and (
                value.get("catalog_snapshot_id") != catalog_id
                or value.get("broker_universe_snapshot_id") != universe_id
            ):
                raise RuntimeError("market_data_universe_lineage_integrity_failed")
            return value
        except RuntimeError:
            raise
        except Exception as exc:
            logger.error("Failed to get latest market-data universe snapshot: %s", exc)
            if strict:
                raise RuntimeError("market_data_universe_latest_read_failed") from exc
            return None

    def record_broker_inventory_event(self, event: Dict[str, Any]) -> str:
        """Persist one immutable inventory-affecting lifecycle fact.

        Returns one of: inserted, updated, duplicate, conflict, failed.
        Re-observation may enrich a previously missing fee, but changing any
        quantity/identity field under the same event ID is a conflict.
        """
        event_id = str(event.get("event_id") or "").strip()
        event_type = str(event.get("event_type") or "").strip().upper()
        source = str(event.get("source") or "").strip()
        semantics = str(event.get("quantity_semantics") or "NONE").strip().upper()
        allowed_types = {
            "FILL",
            "TRADE_CORRECT",
            "TRADE_BUST",
            "REJECTED",
            "EXPIRED",
            "CANCELED",
            "CANCELLED",
            "REPLACED",
        }
        if not event_id or event_type not in allowed_types or not source:
            return "failed"
        if semantics not in {"DELTA", "CUMULATIVE_ORDER", "NONE"}:
            return "failed"

        quantity = self._inventory_decimal_text(
            event.get("quantity"),
            field_name="quantity",
            required=event_type in {"FILL", "TRADE_CORRECT"},
            positive=event_type in {"FILL", "TRADE_CORRECT"},
        )
        price = self._inventory_decimal_text(
            event.get("price"),
            field_name="price",
            required=event_type in {"FILL", "TRADE_CORRECT"},
            positive=event_type in {"FILL", "TRADE_CORRECT"},
        )
        fee = self._inventory_decimal_text(
            event.get("fee"),
            field_name="fee",
            required=False,
            non_negative=True,
        )
        if quantity is False or price is False or fee is False:
            return "failed"
        if event_type in {"FILL", "TRADE_CORRECT"}:
            if semantics == "NONE":
                return "failed"
            required_identity = ("broker_order_id", "client_order_id", "fill_id")
            if any(not str(event.get(field) or "").strip() for field in required_identity):
                return "failed"
            if not str(event.get("symbol") or "").strip() or str(event.get("side") or "").strip().lower() not in {"buy", "sell"}:
                return "failed"
        if event_type in {"TRADE_CORRECT", "TRADE_BUST"} and not str(event.get("replaces_event_id") or "").strip():
            return "failed"

        raw_event_ts_ns = event.get("event_ts_ns")
        event_ts_ns = self._int_or_none(raw_event_ts_ns)
        if raw_event_ts_ns not in (None, "") and (event_ts_ns is None or event_ts_ns <= 0):
            return "failed"
        raw_observed_at_ns = event.get("observed_at_ns")
        observed_at_ns = self._int_or_none(raw_observed_at_ns)
        if raw_observed_at_ns in (None, ""):
            observed_at_ns = now_ns()
        elif observed_at_ns is None or observed_at_ns <= 0:
            return "failed"

        stable = {
            "event_id": event_id,
            "event_type": event_type,
            "replaces_event_id": self._text_or_none(event.get("replaces_event_id")),
            "broker_order_id": self._text_or_none(event.get("broker_order_id")),
            "client_order_id": self._text_or_none(event.get("client_order_id")),
            "fill_id": self._text_or_none(event.get("fill_id")),
            "baseline_snapshot_id": self._text_or_none(event.get("baseline_snapshot_id")),
            "symbol": self._text_or_none(event.get("symbol")),
            "side": self._text_or_none(event.get("side"), lower=True),
            "action": self._text_or_none(event.get("action"), lower=True),
            "quantity": quantity if isinstance(quantity, str) else None,
            "price": price if isinstance(price, str) else None,
            "quantity_semantics": semantics,
            "sleeve": self._text_or_none(event.get("sleeve")),
            "event_ts_ns": event_ts_ns,
            "source": source,
        }
        payload_hash = self._stable_hash(stable)
        metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
        record = {
            **stable,
            "fee": fee if isinstance(fee, str) else None,
            "fee_currency": self._text_or_none(event.get("fee_currency")),
            "observed_at_ns": observed_at_ns,
            "payload_hash": payload_hash,
            "status": str(event.get("status") or "OBSERVED").strip().upper(),
            "metadata": json.dumps(metadata, sort_keys=True, separators=(",", ":"), default=str),
        }

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("BEGIN IMMEDIATE")
                cursor.execute("SELECT * FROM broker_inventory_events WHERE event_id = ?", (event_id,))
                existing = cursor.fetchone()
                if existing is not None:
                    existing_row = dict(existing)
                    if str(existing_row.get("payload_hash") or "") != payload_hash:
                        conn.rollback()
                        return "conflict"
                    existing_fee = self._decimal_or_none(existing_row.get("fee"))
                    incoming_fee = self._decimal_or_none(record.get("fee"))
                    existing_currency = str(existing_row.get("fee_currency") or "")
                    incoming_currency = str(record.get("fee_currency") or "")
                    if existing_fee is None and incoming_fee is not None and incoming_currency:
                        cursor.execute(
                            """
                            UPDATE broker_inventory_events
                            SET fee = ?, fee_currency = ?, observed_at_ns = ?, metadata = ?
                            WHERE event_id = ?
                            """,
                            (str(incoming_fee), incoming_currency, observed_at_ns, record["metadata"], event_id),
                        )
                        conn.commit()
                        return "updated"
                    if incoming_fee is not None and (existing_fee != incoming_fee or existing_currency != incoming_currency):
                        conn.rollback()
                        return "conflict"
                    conn.rollback()
                    return "duplicate"

                columns = tuple(record)
                cursor.execute(
                    f"INSERT INTO broker_inventory_events ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                    [record[column] for column in columns],
                )
                conn.commit()
                return "inserted"
        except Exception as exc:
            logger.error("Failed to record broker inventory event %s: %s", event_id, exc)
            return "failed"

    def list_broker_inventory_events(
        self,
        *,
        baseline_snapshot_id: Optional[str] = None,
        strict: bool = False,
    ) -> List[Dict[str, Any]]:
        """Return immutable inventory events in deterministic causal order."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if baseline_snapshot_id is None:
                    cursor.execute(
                        """
                        SELECT * FROM broker_inventory_events
                        ORDER BY COALESCE(event_ts_ns, observed_at_ns), observed_at_ns, event_id
                        """
                    )
                else:
                    cursor.execute(
                        """
                        SELECT * FROM broker_inventory_events
                        WHERE baseline_snapshot_id = ?
                        ORDER BY COALESCE(event_ts_ns, observed_at_ns), observed_at_ns, event_id
                        """,
                        (str(baseline_snapshot_id),),
                    )
                rows: List[Dict[str, Any]] = []
                integrity_error = False
                for row in cursor.fetchall():
                    record = dict(row)
                    stable = {
                        "event_id": self._text_or_none(record.get("event_id")),
                        "event_type": self._text_or_none(record.get("event_type")),
                        "replaces_event_id": self._text_or_none(record.get("replaces_event_id")),
                        "broker_order_id": self._text_or_none(record.get("broker_order_id")),
                        "client_order_id": self._text_or_none(record.get("client_order_id")),
                        "fill_id": self._text_or_none(record.get("fill_id")),
                        "baseline_snapshot_id": self._text_or_none(record.get("baseline_snapshot_id")),
                        "symbol": self._text_or_none(record.get("symbol")),
                        "side": self._text_or_none(record.get("side"), lower=True),
                        "action": self._text_or_none(record.get("action"), lower=True),
                        "quantity": self._text_or_none(record.get("quantity")),
                        "price": self._text_or_none(record.get("price")),
                        "quantity_semantics": self._text_or_none(record.get("quantity_semantics")),
                        "sleeve": self._text_or_none(record.get("sleeve")),
                        "event_ts_ns": self._int_or_none(record.get("event_ts_ns")),
                        "source": self._text_or_none(record.get("source")),
                    }
                    if self._stable_hash(stable) != str(record.get("payload_hash") or ""):
                        integrity_error = True
                        logger.error(
                            "Broker inventory event integrity check failed for %s",
                            record.get("event_id"),
                        )
                        break
                    record["metadata"] = self._json_dict_or_empty(record.get("metadata"))
                    rows.append(record)
                if integrity_error:
                    if strict:
                        raise RuntimeError("broker_inventory_event_integrity_failed")
                    return []
                return rows
        except Exception as exc:
            logger.error("Failed to list broker inventory events: %s", exc)
            if strict:
                raise RuntimeError("broker_inventory_event_read_failed") from exc
            return []

    def persist_broker_inventory_reconciliation(
        self,
        snapshot: Dict[str, Any],
        *,
        positions: List[Dict[str, Any]],
        lots: List[Dict[str, Any]],
    ) -> str:
        """Atomically persist one immutable broker book and lot projection.

        Returns one of: inserted, duplicate, conflict, failed.
        """
        snapshot_id = str(snapshot.get("snapshot_id") or "").strip()
        required_text = ("broker", "environment", "endpoint_family", "account_suffix", "status")
        if not snapshot_id or any(not str(snapshot.get(field) or "").strip() for field in required_text):
            return "failed"
        observed_at_ns = self._int_or_none(snapshot.get("observed_at_ns"))
        if observed_at_ns is None or observed_at_ns <= 0:
            return "failed"

        normalized_positions: List[Dict[str, Any]] = []
        seen_symbols: set[str] = set()
        for row in positions:
            symbol = str(row.get("symbol") or "").strip().upper()
            if not symbol or symbol in seen_symbols:
                return "failed"
            seen_symbols.add(symbol)
            broker_qty = self._inventory_decimal_text(row.get("broker_qty"), field_name="broker_qty", required=True, non_negative=True)
            avg_entry_price = self._inventory_decimal_text(row.get("avg_entry_price"), field_name="avg_entry_price", required=False, positive=True)
            mark_price = self._inventory_decimal_text(row.get("mark_price"), field_name="mark_price", required=False, positive=True)
            quantity_step = self._inventory_decimal_text(row.get("quantity_step"), field_name="quantity_step", required=False, positive=True)
            if any(value is False for value in (broker_qty, avg_entry_price, mark_price, quantity_step)):
                return "failed"
            normalized_positions.append({
                "snapshot_id": snapshot_id,
                "symbol": symbol,
                "broker_qty": broker_qty,
                "avg_entry_price": avg_entry_price if isinstance(avg_entry_price, str) else None,
                "mark_price": mark_price if isinstance(mark_price, str) else None,
                "quantity_step": quantity_step if isinstance(quantity_step, str) else None,
                "metadata": json.dumps(row.get("metadata") or {}, sort_keys=True, separators=(",", ":"), default=str),
            })

        normalized_lots: List[Dict[str, Any]] = []
        seen_lots: set[str] = set()
        allowed_provenance = {
            "ADOPTED_BASELINE",
            "BOT_ACQUIRED",
            "PENDING_BUY",
            "PENDING_SELL",
            "SOLD",
            "UNKNOWN_ATTRIBUTION",
        }
        for row in lots:
            lot_id = str(row.get("lot_id") or "").strip()
            symbol = str(row.get("symbol") or "").strip().upper()
            provenance = str(row.get("provenance") or "").strip().upper()
            if not lot_id or not symbol or lot_id in seen_lots or provenance not in allowed_provenance:
                return "failed"
            seen_lots.add(lot_id)
            original_qty = self._inventory_decimal_text(row.get("original_qty"), field_name="original_qty", required=True, non_negative=True)
            remaining_qty = self._inventory_decimal_text(row.get("remaining_qty"), field_name="remaining_qty", required=True, non_negative=True)
            sold_qty = self._inventory_decimal_text(row.get("sold_qty"), field_name="sold_qty", required=True, non_negative=True)
            avg_entry_price = self._inventory_decimal_text(row.get("avg_entry_price"), field_name="avg_entry_price", required=False, positive=True)
            if any(value is False for value in (original_qty, remaining_qty, sold_qty, avg_entry_price)):
                return "failed"
            original_decimal = Decimal(str(original_qty))
            remaining_decimal = Decimal(str(remaining_qty))
            sold_decimal = Decimal(str(sold_qty))
            if provenance in {"ADOPTED_BASELINE", "BOT_ACQUIRED"}:
                if remaining_decimal + sold_decimal != original_decimal:
                    return "failed"
            elif provenance in {"PENDING_BUY", "PENDING_SELL", "UNKNOWN_ATTRIBUTION"}:
                if remaining_decimal != original_decimal or sold_decimal != Decimal("0"):
                    return "failed"
            elif provenance == "SOLD":
                if remaining_decimal != Decimal("0") or sold_decimal != original_decimal:
                    return "failed"
            normalized_lots.append({
                "snapshot_id": snapshot_id,
                "lot_id": lot_id,
                "symbol": symbol,
                "sleeve": self._text_or_none(row.get("sleeve")),
                "provenance": provenance,
                "original_qty": original_qty,
                "remaining_qty": remaining_qty,
                "sold_qty": sold_qty,
                "avg_entry_price": avg_entry_price if isinstance(avg_entry_price, str) else None,
                "source_event_id": self._text_or_none(row.get("source_event_id")),
                "baseline_snapshot_id": self._text_or_none(row.get("baseline_snapshot_id")),
                "acquired_at_ns": self._int_or_none(row.get("acquired_at_ns")),
                "metadata": json.dumps(row.get("metadata") or {}, sort_keys=True, separators=(",", ":"), default=str),
            })

        normalized_positions.sort(key=lambda row: row["symbol"])
        normalized_lots.sort(key=lambda row: (row["symbol"], row["acquired_at_ns"] or 0, row["lot_id"]))
        book_hash = self._broker_inventory_book_hash(
            snapshot,
            normalized_positions,
            normalized_lots,
        )
        reason_codes = tuple(str(item) for item in (snapshot.get("reason_codes") or ()))
        header = {
            "snapshot_id": snapshot_id,
            "broker": str(snapshot["broker"]),
            "environment": str(snapshot["environment"]),
            "endpoint_family": str(snapshot["endpoint_family"]),
            "account_suffix": str(snapshot["account_suffix"]),
            "baseline_snapshot_id": self._text_or_none(snapshot.get("baseline_snapshot_id")),
            "parent_snapshot_id": self._text_or_none(snapshot.get("parent_snapshot_id")),
            "observed_at_ns": observed_at_ns,
            "position_count": len(normalized_positions),
            "open_order_count": int(snapshot.get("open_order_count") or 0),
            "status": str(snapshot["status"]),
            "book_hash": book_hash,
            "reason_codes": json.dumps(reason_codes),
            "metadata": json.dumps(snapshot.get("metadata") or {}, sort_keys=True, separators=(",", ":"), default=str),
            "created_at_ns": self._int_or_none(snapshot.get("created_at_ns")) or now_ns(),
        }

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("BEGIN IMMEDIATE")
                cursor.execute("SELECT book_hash FROM broker_inventory_snapshots WHERE snapshot_id = ?", (snapshot_id,))
                existing = cursor.fetchone()
                if existing is not None:
                    conn.rollback()
                    return "duplicate" if str(existing[0]) == book_hash else "conflict"

                header_columns = tuple(header)
                cursor.execute(
                    f"INSERT INTO broker_inventory_snapshots ({', '.join(header_columns)}) VALUES ({', '.join('?' for _ in header_columns)})",
                    [header[column] for column in header_columns],
                )
                for row in normalized_positions:
                    columns = tuple(row)
                    cursor.execute(
                        f"INSERT INTO broker_inventory_snapshot_positions ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                        [row[column] for column in columns],
                    )
                for row in normalized_lots:
                    columns = tuple(row)
                    cursor.execute(
                        f"INSERT INTO broker_inventory_lot_projections ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                        [row[column] for column in columns],
                    )
                conn.commit()
                return "inserted"
        except Exception as exc:
            logger.error("Failed to persist broker inventory reconciliation %s: %s", snapshot_id, exc)
            return "failed"

    def get_broker_inventory_reconciliation(
        self,
        snapshot_id: str,
        *,
        strict: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Read one immutable broker inventory snapshot with its projection."""
        safe_id = str(snapshot_id or "").strip()
        if not safe_id:
            return None
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM broker_inventory_snapshots WHERE snapshot_id = ?", (safe_id,))
                header = cursor.fetchone()
                if header is None:
                    return None
                result = dict(header)
                result["reason_codes"] = tuple(json.loads(result.get("reason_codes") or "[]"))
                result["metadata"] = self._json_dict_or_empty(result.get("metadata"))
                cursor.execute(
                    "SELECT * FROM broker_inventory_snapshot_positions WHERE snapshot_id = ? ORDER BY symbol",
                    (safe_id,),
                )
                positions = []
                for row in cursor.fetchall():
                    item = dict(row)
                    item["metadata"] = self._json_dict_or_empty(item.get("metadata"))
                    positions.append(item)
                cursor.execute(
                    "SELECT * FROM broker_inventory_lot_projections WHERE snapshot_id = ? ORDER BY symbol, acquired_at_ns, lot_id",
                    (safe_id,),
                )
                lots = []
                for row in cursor.fetchall():
                    item = dict(row)
                    item["metadata"] = self._json_dict_or_empty(item.get("metadata"))
                    lots.append(item)
                result["positions"] = positions
                result["lots"] = lots
                if int(result.get("position_count") or 0) != len(positions):
                    raise RuntimeError("broker_inventory_position_count_integrity_failed")
                expected_hash = str(result.get("book_hash") or "")
                actual_hash = self._broker_inventory_book_hash(result, positions, lots)
                if not expected_hash or actual_hash != expected_hash:
                    raise RuntimeError("broker_inventory_book_hash_integrity_failed")
                return result
        except Exception as exc:
            logger.error("Failed to get broker inventory reconciliation %s: %s", safe_id, exc)
            if strict:
                raise RuntimeError("broker_inventory_reconciliation_read_failed") from exc
            return None

    def get_latest_broker_inventory_reconciliation(
        self,
        *,
        account_suffix: Optional[str] = None,
        strict: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Return the newest persisted projection, never treating it as fresh by itself."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if account_suffix is None:
                    cursor.execute(
                        "SELECT snapshot_id FROM broker_inventory_snapshots ORDER BY observed_at_ns DESC, created_at_ns DESC LIMIT 1"
                    )
                else:
                    cursor.execute(
                        """
                        SELECT snapshot_id FROM broker_inventory_snapshots
                        WHERE account_suffix = ?
                        ORDER BY observed_at_ns DESC, created_at_ns DESC LIMIT 1
                        """,
                        (str(account_suffix),),
                    )
                row = cursor.fetchone()
                return (
                    None
                    if row is None
                    else self.get_broker_inventory_reconciliation(str(row[0]), strict=strict)
                )
        except Exception as exc:
            logger.error("Failed to get latest broker inventory reconciliation: %s", exc)
            if strict:
                raise RuntimeError("latest_broker_inventory_reconciliation_read_failed") from exc
            return None

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
