from __future__ import annotations

import inspect
import subprocess
import sys
import time
from pathlib import Path

from app.api.operator_readonly_api import OperatorSnapshotProvider, create_operator_app
from app.api.operator_runtime_config import OperatorRuntimeConfig
from app.run_visibility import (
    DEFAULT_HEARTBEAT_PATH,
    DEFAULT_SUPERVISOR_STATUS_PATH,
    atomic_write_json,
    build_runtime_heartbeat_payload,
    build_supervisor_status_payload,
    read_reconciled_fill_ledger_visibility,
    read_run_visibility_snapshot,
    utc_now_iso,
)
from app.state.state_store import StateStore


def _endpoint(app, path: str, method: str = "GET"):
    for route in app.routes:
        if route.path == path and method in (route.methods or set()):
            def call(*args, _endpoint=route.endpoint, **kwargs):
                result = _endpoint(*args, **kwargs)
                if inspect.isawaitable(result):
                    raise AssertionError("unexpected async endpoint in run visibility test")
                return result

            return call
    raise AssertionError(f"route not found: {method} {path}")


def _write_running_artifacts(repo_root: Path) -> None:
    heartbeat_path = repo_root / DEFAULT_HEARTBEAT_PATH
    supervisor_path = repo_root / DEFAULT_SUPERVISOR_STATUS_PATH
    stdout_path = repo_root / "logs" / "paper_runs" / "bounded_paper_test.out.log"
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_path.write_text("2026-06-18 00:00:01.000 | INFO | started\n", encoding="utf-8")
    heartbeat = build_runtime_heartbeat_payload(
        {
            "running": True,
            "active_symbols": ["BTC/USD", "ETH/USD", "SOL/USD"],
            "execution": {
                "is_running": True,
                "pending_orders_count": 1,
                "filled_orders_count": 2,
                "latency_degraded_count": 3,
                "last_signal": {"symbol": "SOL/USD"},
                "last_order_submit_attempt": {"client_order_id": "order-1"},
                "last_fill": {"client_order_id": "order-1", "symbol": "SOL/USD"},
                "broker_mutation_counts": {"GET": 5, "POST": 1, "DELETE": 0},
            },
            "risk": {"can_trade": True},
            "main_loop": {"broker_position_cache_count": 4, "broker_position_cache_source": "runtime_cache"},
            "order_router": {"pending_orders_count": 1},
        },
        pid=12345,
        started_at=utc_now_iso(),
        started_monotonic=time.monotonic(),
        run_state="RUNNING",
        last_loop_ts=utc_now_iso(),
        last_error=None,
    )
    supervisor = build_supervisor_status_payload(
        state="RUNNING",
        pid=12345,
        started_at=utc_now_iso(),
        uptime_seconds=1.0,
        child_running=True,
        exit_code=None,
        stdout_path=str(stdout_path),
        stderr_path=str(stdout_path.with_suffix(".err.log")),
        heartbeat_path=str(heartbeat_path),
    )
    atomic_write_json(heartbeat_path, heartbeat)
    atomic_write_json(supervisor_path, supervisor)


def test_runtime_heartbeat_payload_is_read_only_and_operator_compact():
    payload = build_runtime_heartbeat_payload(
        {
            "running": True,
            "active_symbols": ["BTC/USD"],
            "execution": {
                "is_running": True,
                "pending_orders_count": 1,
                "filled_orders_count": 1,
                "latency_degraded_count": 7,
                "last_signal": {"symbol": "BTC/USD", "side": "buy"},
                "last_order_submit_attempt": {"client_order_id": "order-1"},
                "last_fill": {"client_order_id": "order-1"},
                "broker_mutation_counts": {"GET": 2, "POST": 1, "DELETE": 0},
            },
            "main_loop": {"broker_position_cache_count": 2},
            "risk": {"can_trade": True},
            "order_router": {},
            "APCA_API_SECRET_KEY": "must-not-leak",
        },
        pid=100,
        started_at=utc_now_iso(),
        started_monotonic=time.monotonic(),
        run_state="RUNNING",
        last_loop_ts=utc_now_iso(),
        last_error=None,
    )

    text = str(payload)
    assert payload["read_only"] is True
    assert payload["broker_call_occurred"] is False
    assert payload["broker_mutation_occurred"] is False
    assert payload["open_orders"]["count"] == 1
    assert payload["positions"]["count"] == 2
    assert payload["latency_degraded_count"] == 7
    assert "must-not-leak" not in text
    assert "APCA_API_SECRET_KEY" not in text


def test_run_visibility_snapshot_combines_fresh_heartbeat_and_supervisor(tmp_path):
    _write_running_artifacts(tmp_path)

    snapshot = read_run_visibility_snapshot(tmp_path)

    assert snapshot["status"] == "RUNNING"
    assert snapshot["controls_available"] is False
    assert snapshot["open_orders"]["count"] == 1
    assert snapshot["positions"]["count"] == 4
    assert snapshot["fills"]["count"] == 2
    assert snapshot["fills"]["source"] == "execution_heartbeat"
    assert snapshot["latency_degraded_count"] == 3
    assert snapshot["broker_mutation_occurred"] is False
    assert snapshot["secrets_values_exposed"] is False


def test_run_visibility_prefers_reconciled_broker_fill_ledger(tmp_path):
    _write_running_artifacts(tmp_path)
    store = StateStore(str(tmp_path / "data" / "state.db"))
    try:
        for index, symbol in enumerate(("BTC/USD", "ETH/USD", "SOL/USD"), start=1):
            status = store.upsert_broker_fill_ledger(
                {
                    "fill_id": f"fill-{index}",
                    "broker_order_id": f"broker-{index}",
                    "client_order_id": f"client-{index}",
                    "broker_activity_id": f"activity-{index}",
                    "decision_uuid": f"decision-{index}",
                    "symbol": symbol,
                    "side": "buy",
                    "quantity": "0.01",
                    "price": "100.00",
                    "notional": "1.00",
                    "fill_timestamp": f"2026-06-18T00:00:0{index}Z",
                    "fill_ts_ns": 1_779_600_000_000_000_000 + index,
                    "fee": "0.01",
                    "fee_currency": "USD",
                    "source": "broker_activity_reconciliation",
                    "hydration_status": "COMPLETE",
                    "tca_status": "COMPLETE",
                    "execution_quality_verdict": "KNOWN",
                }
            )
            assert status == "inserted"
    finally:
        store.close()

    ledger = read_reconciled_fill_ledger_visibility(tmp_path)
    snapshot = read_run_visibility_snapshot(tmp_path)

    assert ledger["available"] is True
    assert ledger["broker_fill_ledger_rows"] == 3
    assert snapshot["fills"]["source"] == "broker_fill_ledger"
    assert snapshot["fills"]["count"] == 3
    assert snapshot["fills"]["heartbeat_filled_orders_count"] == 2
    assert snapshot["last_fill"]["client_order_id"] == "client-3"
    assert snapshot["last_fill"]["symbol"] == "SOL/USD"
    assert snapshot["reconciled_fills"]["read_only"] is True


def test_supervisor_status_flips_after_process_death(tmp_path):
    stdout_path = tmp_path / "logs" / "paper_runs" / "child.out.log"
    stderr_path = tmp_path / "logs" / "paper_runs" / "child.err.log"
    heartbeat_path = tmp_path / DEFAULT_HEARTBEAT_PATH
    supervisor_path = tmp_path / DEFAULT_SUPERVISOR_STATUS_PATH
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_path.write_text("2026-06-18 00:00:01.000 | INFO | alive\n", encoding="utf-8")
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    started = time.monotonic()
    try:
        running = build_supervisor_status_payload(
            state="RUNNING",
            pid=process.pid,
            started_at=utc_now_iso(),
            uptime_seconds=0.1,
            child_running=process.poll() is None,
            exit_code=process.poll(),
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            heartbeat_path=str(heartbeat_path),
        )
        atomic_write_json(supervisor_path, running)
        assert read_run_visibility_snapshot(tmp_path)["status"] in {"RUNNING", "STALE"}

        process.terminate()
        process.wait(timeout=5)
        stopped = build_supervisor_status_payload(
            state="FAILED" if process.returncode else "EXITED",
            pid=process.pid,
            started_at=utc_now_iso(),
            uptime_seconds=time.monotonic() - started,
            child_running=process.poll() is None,
            exit_code=process.returncode,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            heartbeat_path=str(heartbeat_path),
        )
        atomic_write_json(supervisor_path, stopped)
    finally:
        if process.poll() is None:
            process.kill()

    snapshot = read_run_visibility_snapshot(tmp_path)
    assert snapshot["status"] in {"FAILED", "STOPPED"}
    assert snapshot["supervisor"]["child_running"] is False
    assert snapshot["supervisor"]["manual_restart_required"] is True


def test_operator_run_visibility_endpoint_and_page_are_read_only(tmp_path):
    _write_running_artifacts(tmp_path)
    runtime_config = OperatorRuntimeConfig.from_env({}, repo_root=tmp_path)
    app = create_operator_app(provider=OperatorSnapshotProvider(runtime_config=runtime_config))

    status = _endpoint(app, "/operator/run-visibility/status")()
    page = _endpoint(app, "/operator/run-visibility")()
    html = page.body.decode("utf-8")

    assert status["status"] == "RUNNING"
    assert status["controls_available"] is False
    assert status["broker_mutation_occurred"] is False
    assert status["live_enabled"] is False
    assert page.headers["Cache-Control"] == "no-store, max-age=0, must-revalidate"
    assert "PAPER Run State" in html
    assert "/operator/run-visibility/status" in html
    assert "<button" not in html.lower()
