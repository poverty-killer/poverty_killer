"""
test_f4c_risk_state_persistence.py

F4C — Risk State Persistence Counter Reachability Tests

Verifies:
- ATOMIC_WRITE_FAILED is reachable and incremented on write failure
- ATOMIC_WRITE_TRANSIENT is reachable and incremented on transient/rename errors
- RESTORED_FROM_BACKUP is reachable and incremented when backup restore fires
- Atomic write success path leaves no counter increments
- Counters are exposed in get_status()

All tests use tmp_path fixture — no live state files are touched.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from app.risk.guard import HybridRiskGuard


def _make_valid_state_dict(equity: float = 10000.0) -> dict:
    return {
        "initial_equity": equity,
        "current_equity": equity,
        "high_water_mark": equity,
        "daily_peak": equity,
        "last_reset_date": datetime.utcnow().isoformat(),
        "physical_fuse_triggered": False,
        "adaptive_floor_breached": False,
        "last_breach_time": None,
        "equity_history": [],
        "vol_fuse_triggered": False,
        "last_vol_check_time": None,
        "total_fees_paid": 0.0,
        "total_withdrawal_fees": 0.0,
        "estimated_tax_liability": 0.0,
        "tax_rate": 0.25,
        "tradeable_equity": equity,
        "max_latency_ms": 200.0,
    }


@pytest.fixture
def fresh_guard(tmp_path):
    state_file = str(tmp_path / "risk_state.json")
    backup_file = str(tmp_path / "risk_state.backup")
    guard = HybridRiskGuard(
        initial_equity=10000.0,
        state_file=state_file,
        backup_file=backup_file,
    )
    return guard, tmp_path


class TestAtomicWriteSuccess:
    def test_write_success_no_counter_increments(self, fresh_guard):
        guard, tmp_path = fresh_guard
        guard._save_state()
        state_path = tmp_path / "risk_state.json"
        assert state_path.exists(), "state file must exist after save"
        data = json.loads(state_path.read_text(encoding="utf-8"))
        assert "high_water_mark" in data
        assert guard._counters["ATOMIC_WRITE_FAILED"] == 0
        assert guard._counters["ATOMIC_WRITE_TRANSIENT"] == 0
        assert guard._counters["RESTORED_FROM_BACKUP"] == 0


class TestAtomicWriteTransientCounter:
    def test_rename_failure_increments_transient(self, fresh_guard):
        """
        Simulate OneDrive file-lock: os.replace always raises PermissionError.
        The code retries (retries=3) then falls back to direct write on last attempt.
        Each rename failure → ATOMIC_WRITE_TRANSIENT += 1.
        Direct write fallback succeeds → ATOMIC_WRITE_FAILED stays 0.
        """
        guard, tmp_path = fresh_guard

        with patch("app.risk.guard.os.replace", side_effect=PermissionError("OneDrive lock")):
            guard._save_state()

        # 3 rename failures (retries=3 default)
        assert guard._counters["ATOMIC_WRITE_TRANSIENT"] == 3
        # Direct write fallback returned True → no FAILED increment
        assert guard._counters["ATOMIC_WRITE_FAILED"] == 0
        # File must still be written by the direct-write fallback
        assert (tmp_path / "risk_state.json").exists()
        data = json.loads((tmp_path / "risk_state.json").read_text(encoding="utf-8"))
        assert "high_water_mark" in data


class TestAtomicWriteFailedCounter:
    def test_write_to_nonexistent_parent_increments_failed(self, fresh_guard):
        """
        Writing to a path whose parent directory doesn't exist forces FileNotFoundError
        on open(tmp_path, 'w'), exercising the outer except (PermissionError,
        FileNotFoundError) path. All 3 retries exhaust → ATOMIC_WRITE_FAILED == 1.
        """
        guard, tmp_path = fresh_guard
        # Nonexistent deep path — parent dirs do not exist
        bad_path = tmp_path / "nosuchdir" / "deep" / "state.json"
        data = _make_valid_state_dict()

        result = guard._atomic_write_json(data, bad_path, retries=3)

        assert result is False
        assert guard._counters["ATOMIC_WRITE_FAILED"] == 1
        # Each of the 3 attempts triggers a transient increment before the last-attempt check
        assert guard._counters["ATOMIC_WRITE_TRANSIENT"] == 3


class TestRestoredFromBackupCounter:
    def test_corrupt_primary_loads_backup_increments_counter(self, tmp_path):
        """
        Write valid JSON to backup, corrupt JSON to primary.
        When HybridRiskGuard is constructed, _load_state fails on primary and
        succeeds on backup → RESTORED_FROM_BACKUP == 1.
        """
        state_file = str(tmp_path / "risk_state.json")
        backup_file = str(tmp_path / "risk_state.backup")
        valid_equity = 15000.0

        # Write valid backup
        valid_state = _make_valid_state_dict(equity=valid_equity)
        Path(backup_file).write_text(
            json.dumps(valid_state), encoding="utf-8"
        )

        # Write corrupt primary
        Path(state_file).write_text("NOT_VALID_JSON{{{", encoding="utf-8")

        guard = HybridRiskGuard(
            initial_equity=10000.0,
            state_file=state_file,
            backup_file=backup_file,
        )

        assert guard._counters["RESTORED_FROM_BACKUP"] == 1
        assert guard._state.high_water_mark == valid_equity

    def test_missing_primary_loads_backup_increments_counter(self, tmp_path):
        """
        No primary file at all, valid backup present.
        _load_state skips primary (doesn't exist) and loads backup →
        RESTORED_FROM_BACKUP == 1.
        """
        state_file = str(tmp_path / "risk_state.json")
        backup_file = str(tmp_path / "risk_state.backup")
        valid_equity = 12000.0

        valid_state = _make_valid_state_dict(equity=valid_equity)
        Path(backup_file).write_text(
            json.dumps(valid_state), encoding="utf-8"
        )
        # Primary does not exist

        guard = HybridRiskGuard(
            initial_equity=10000.0,
            state_file=state_file,
            backup_file=backup_file,
        )

        assert guard._counters["RESTORED_FROM_BACKUP"] == 1
        assert guard._state.high_water_mark == valid_equity


class TestCountersInGetStatus:
    def test_get_status_exposes_persistence_counters(self, fresh_guard):
        guard, tmp_path = fresh_guard
        status = guard.get_status()
        assert "persistence_counters" in status
        counters = status["persistence_counters"]
        assert "ATOMIC_WRITE_FAILED" in counters
        assert "ATOMIC_WRITE_TRANSIENT" in counters
        assert "RESTORED_FROM_BACKUP" in counters

    def test_get_status_reflects_transient_after_rename_failure(self, fresh_guard):
        guard, tmp_path = fresh_guard
        with patch("app.risk.guard.os.replace", side_effect=PermissionError("lock")):
            guard._save_state()
        status = guard.get_status()
        assert status["persistence_counters"]["ATOMIC_WRITE_TRANSIENT"] >= 1
        assert status["persistence_counters"]["ATOMIC_WRITE_FAILED"] == 0
