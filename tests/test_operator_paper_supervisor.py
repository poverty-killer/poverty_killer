from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

from app.api.operator_paper_supervisor import (
    BOUNDED_RUNTIME_COMPLETED,
    DURATION_BOUND_EXCEEDED,
    OperatorPaperSupervisor,
    PaperSupervisorConfig,
    ProcessStartSpec,
    SubprocessPaperRunner,
    classify_bounded_runtime_monitor_state,
)
from app.api.operator_session_store import OperatorSessionStore
from app.execution.broker_read_policy import (
    ACCOUNT_ACTIVITY_READS_ALLOWED_ENV,
    BROKER_READ_ALLOWLIST_ENV,
    BROKER_READ_DENY_ACCOUNT_ACTIVITIES_ENV,
    BROKER_READ_PROFILE_ENV,
    FEE_HYDRATION_ALLOWED_ENV,
    PAPER_SMOKE_STRICT_READS,
)
from app.market.capability_registry import build_alpaca_crypto_universe, normalize_alpaca_crypto_catalog
from app.operator_activation.paper_baseline import (
    BASELINE_POLICY_PROTECTED,
    PAPER_BASELINE_ENV_PATH,
    PAPER_BASELINE_ENV_POLICY,
    PAPER_BASELINE_ENV_PROTECTED_SYMBOLS,
    PAPER_BASELINE_ENV_REQUIRED,
    PAPER_BASELINE_ENV_SNAPSHOT_HASH,
    PAPER_BASELINE_ENV_SNAPSHOT_ID,
    PAPER_BASELINE_RUNTIME_CONTEXT_REQUIRED,
    accept_existing_position_baseline,
)
from app.state.state_store import StateStore


class FakeProcess:
    def __init__(self, pid: int = 43210) -> None:
        self.pid = pid
        self.exit_code: int | None = None

    def poll(self) -> int | None:
        return self.exit_code


class FakeRunner:
    def __init__(self, *, available: bool = True, unavailable_reason: str | None = None) -> None:
        self.available = available
        self.unavailable_reason = unavailable_reason
        self.repo_root = Path(tempfile.mkdtemp(prefix="pk-operator-supervisor-test-"))
        self.started_specs: list[ProcessStartSpec] = []
        self.stop_requests = 0
        self.wait_requests = 0
        self.shutdown_requests = 0
        self.stop_request_pids: list[int] = []
        self.process = FakeProcess()
        self.on_stop = None

    def is_available(self, repo_root: Path):
        assert repo_root == self.repo_root
        return self.available, self.unavailable_reason

    def start(self, spec: ProcessStartSpec):
        self.started_specs.append(spec)
        return self.process

    def request_graceful_stop(self, handle: FakeProcess):
        self.stop_requests += 1
        self.stop_request_pids.append(int(handle.pid))
        if callable(self.on_stop):
            self.on_stop()
        if hasattr(handle, "exit_code"):
            handle.exit_code = 0
        return True, "CTRL_BREAK_EVENT_SENT"

    def wait_for_exit(self, handle: FakeProcess, *, timeout_seconds: float):
        del timeout_seconds
        self.wait_requests += 1
        return handle.poll() is not None

    def shutdown_process_group(self, handle: FakeProcess, *, timeout_seconds: float = 5.0):
        del timeout_seconds
        self.shutdown_requests += 1
        self.stop_request_pids.append(int(handle.pid))
        return True, "PROCESS_GROUP_SHUTDOWN_SENT"


def _account_pin_ok_assertion() -> dict:
    return {
        "source": "TEST_ACCOUNT_PIN",
        "status": "PASS",
        "reason_code": "ALPACA_PAPER_ACCOUNT_PIN_OK",
        "detail": "offline unit test account pin is pre-proven",
        "expected_suffix": "045ded",
        "actual_suffix": "045ded",
        "paper_account_pinned": True,
        "broker_read_attempted": True,
        "broker_read_occurred": True,
        "account_request_occurred": True,
        "broker_mutation_occurred": False,
        "order_submission_occurred": False,
        "cancel_occurred": False,
        "liquidation_occurred": False,
        "live_enabled": False,
        "real_money_enabled": False,
        "secrets_values_exposed": False,
    }


@pytest.fixture(autouse=True)
def _offline_account_pin_for_legacy_supervisor_tests(monkeypatch):
    monkeypatch.setattr(
        OperatorPaperSupervisor,
        "_paper_account_identity_assertion",
        lambda self, *, force=False: _account_pin_ok_assertion(),
    )


def _valid_request() -> dict:
    return {
        "mode": "PAPER",
        "profile": "PAPER_EXPLORATION_ALPHA",
        "duration_seconds": 300,
        "watchlist": ["BTC/USD", "ETH/USD", "SOL/USD", "LTC/USD", "AVAX/USD", "LINK/USD"],
        "approve_autonomous_paper": True,
    }


def _paper_env() -> dict[str, str]:
    return {
        "APCA_API_KEY_ID": "test-paper-key",
        "APCA_API_SECRET_KEY": "test-paper-secret",
        "APCA_API_BASE_URL": "https://paper-api.alpaca.markets",
    }


def _with_proven_broker_preflight(supervisor: OperatorPaperSupervisor) -> OperatorPaperSupervisor:
    """Place lifecycle-focused tests after the separately tested GET-only gate."""
    symbols = tuple(_valid_request()["watchlist"])
    now_ns = time.time_ns()
    catalog = normalize_alpaca_crypto_catalog(
        [
            {
                "id": f"asset-{symbol.replace('/', '').lower()}",
                "class": "crypto",
                "exchange": "CRYPTO",
                "symbol": symbol,
                "status": "active",
                "tradable": True,
                "fractionable": True,
                "marginable": False,
                "shortable": False,
                "min_order_size": "0.000000001",
                "min_trade_increment": "0.000000001",
                "price_increment": "0.000000001",
            }
            for symbol in symbols
        ],
        observed_at_ns=now_ns - 1_000_000,
        valid_until_ns=now_ns + 3_600_000_000_000,
        expected_account_suffix="045ded",
        actual_account_suffix="045ded",
    )
    universe = build_alpaca_crypto_universe(
        catalog,
        as_of_ns=now_ns,
        expected_account_suffix="045ded",
        actual_account_suffix="045ded",
        account_status="ACTIVE",
        crypto_status="ACTIVE",
        trading_blocked=False,
        account_blocked=False,
        trade_suspended_by_user=False,
        execution_adapter="alpaca_paper_rest",
        execution_adapter_available=True,
        funded_quote_currencies=("USD",),
        market_data_symbols=symbols,
        priority_symbols=symbols,
    )
    state_path = supervisor._state_store_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_store = StateStore(str(state_path))
    try:
        assert state_store.persist_broker_crypto_catalog_universe(catalog, universe) in {"persisted", "duplicate"}
    finally:
        state_store.close()
    supervisor.config.catalog_snapshot_id = catalog.catalog_snapshot_id
    supervisor.config.universe_snapshot_id = universe.universe_snapshot_id
    supervisor._process_paper_broker_read_authorized = True
    supervisor._paper_broker_preflight = {
        "source": "TEST_PROVEN_PAPER_BROKER_PREFLIGHT",
        "status": "PASS",
        "reason_code": "PAPER_BROKER_PREFLIGHT_PASS",
        "verified_at": "2026-07-13T00:00:00+00:00",
        "account_identity_assertion": _account_pin_ok_assertion(),
        "broker_call_occurred": True,
        "broker_read_occurred": True,
        "account_request_occurred": True,
        "positions_request_occurred": True,
        "open_orders_request_occurred": True,
        "broker_mutation_occurred": False,
        "order_submission_occurred": False,
        "cancel_occurred": False,
        "replace_occurred": False,
        "liquidation_occurred": False,
        "close_position_occurred": False,
        "live_endpoint_touched": False,
        "real_money_touched": False,
        "secrets_values_exposed": False,
    }
    return supervisor


def _baseline_snapshot() -> dict:
    return {
        "endpoint_family": "paper",
        "account": {
            "id": "acct-123456",
            "status": "ACTIVE",
            "equity": "50000",
            "buying_power": "70000",
            "trading_blocked": False,
            "account_blocked": False,
        },
        "open_order_count": 0,
        "open_orders": [],
        "position_count": 3,
        "positions": [
            {"symbol": "BTCUSD", "asset_class": "crypto", "qty": "0.5", "side": "long"},
            {"symbol": "ETHUSD", "asset_class": "crypto", "qty": "2", "side": "long"},
            {"symbol": "SOLUSD", "asset_class": "crypto", "qty": "10", "side": "long"},
        ],
    }


def _write_accepted_baseline(repo_root: Path) -> dict:
    accepted = accept_existing_position_baseline(_baseline_snapshot(), accepted_by="Shan/local operator")
    path = repo_root / "state" / "operator" / "paper_baseline.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(accepted), encoding="utf-8")
    return accepted


def _supervisor_config(runner: FakeRunner, **overrides) -> PaperSupervisorConfig:
    return PaperSupervisorConfig(repo_root=runner.repo_root, process_env=_paper_env(), **overrides)


def test_supervisor_accepts_valid_paper_start_and_builds_safe_command():
    runner = FakeRunner()
    supervisor = _with_proven_broker_preflight(
        OperatorPaperSupervisor(config=_supervisor_config(runner), runner=runner)
    )

    result = supervisor.start_paper(_valid_request())

    assert result["allowed"] is True
    assert result["reason_code"] == "PAPER_RUN_STARTED"
    assert result["broker_call_occurred"] is False
    assert result["runtime_mutation_occurred"] is True
    assert result["session"]["status"] == "RUNNING"
    assert result["session"]["pid"] == 43210
    assert runner.started_specs
    command = runner.started_specs[0].command
    assert "-Run" in command
    assert "-ApproveAutonomousPaper" in command
    assert "-PaperExplorationAlpha" in command
    assert "-DurationSeconds" in command
    assert "300" in command
    assert "BTC/USD,ETH/USD,SOL/USD,LTC/USD,AVAX/USD,LINK/USD" in command
    assert "APCA_API_SECRET_KEY" not in " ".join(command)
    assert result["session"]["wrapper_stdout_path"] == result["session"]["stdout_path"]
    assert result["session"]["runtime_profile"] == "LOCAL_PAPER"
    env = runner.started_specs[0].env
    assert env[BROKER_READ_PROFILE_ENV] == PAPER_SMOKE_STRICT_READS
    assert env[BROKER_READ_ALLOWLIST_ENV] == "account,orders,positions"
    assert env[BROKER_READ_DENY_ACCOUNT_ACTIVITIES_ENV] == "1"
    assert env[FEE_HYDRATION_ALLOWED_ENV] == "0"
    assert env[ACCOUNT_ACTIVITY_READS_ALLOWED_ENV] == "0"
    assert result["broker_read_permission_profile"]["profile"] == PAPER_SMOKE_STRICT_READS


def test_supervisor_passes_protected_baseline_context_to_bounded_run_spec():
    runner = FakeRunner()
    accepted = _write_accepted_baseline(runner.repo_root)
    supervisor = _with_proven_broker_preflight(
        OperatorPaperSupervisor(config=_supervisor_config(runner), runner=runner)
    )

    snapshot = supervisor.status_snapshot()
    result = supervisor.start_paper(_valid_request())

    assert snapshot["paper_baseline_runtime_context"]["baseline_loaded"] is True
    assert snapshot["paper_baseline_runtime_context"]["same_symbol_baseline_guard_active"] is True
    assert result["allowed"] is True
    assert result["paper_baseline_runtime_context"]["baseline_snapshot_id"] == accepted["baseline_snapshot_id"]
    env = runner.started_specs[0].env
    assert env[PAPER_BASELINE_ENV_REQUIRED] == "1"
    assert env[PAPER_BASELINE_ENV_PATH].replace("\\", "/").endswith("state/operator/paper_baseline.json")
    assert env[PAPER_BASELINE_ENV_SNAPSHOT_ID] == accepted["baseline_snapshot_id"]
    assert env[PAPER_BASELINE_ENV_SNAPSHOT_HASH] == accepted["snapshot_hash"]
    assert env[PAPER_BASELINE_ENV_POLICY] == BASELINE_POLICY_PROTECTED
    assert env[PAPER_BASELINE_ENV_PROTECTED_SYMBOLS] == "BTCUSD,ETHUSD,SOLUSD"
    assert env[BROKER_READ_PROFILE_ENV] == PAPER_SMOKE_STRICT_READS
    assert env[ACCOUNT_ACTIVITY_READS_ALLOWED_ENV] == "0"
    assert env[FEE_HYDRATION_ALLOWED_ENV] == "0"
    assert result["broker_call_occurred"] is False


def test_monitor_prefers_idle_completion_before_duration_overrun():
    decision = classify_bounded_runtime_monitor_state(
        supervisor_state="IDLE",
        active_session_id=None,
        elapsed_seconds=660,
        duration_seconds=600,
        grace_seconds=30,
    )

    assert decision.reason_code == BOUNDED_RUNTIME_COMPLETED
    assert decision.safe_stop_required is False
    assert decision.runtime_active is False


def test_monitor_still_flags_active_duration_overrun():
    decision = classify_bounded_runtime_monitor_state(
        supervisor_state="RUNNING",
        active_session_id="paper_123",
        elapsed_seconds=660,
        duration_seconds=600,
        grace_seconds=30,
    )

    assert decision.reason_code == DURATION_BOUND_EXCEEDED
    assert decision.safe_stop_required is True
    assert decision.runtime_active is True


def test_supervisor_fails_closed_when_required_baseline_artifact_missing():
    runner = FakeRunner()
    missing_path = runner.repo_root / "state" / "operator" / "paper_baseline.json"
    env = dict(_paper_env())
    env[PAPER_BASELINE_ENV_REQUIRED] = "1"
    env[PAPER_BASELINE_ENV_PATH] = str(missing_path)
    supervisor = _with_proven_broker_preflight(
        OperatorPaperSupervisor(
            config=PaperSupervisorConfig(repo_root=runner.repo_root, process_env=env),
            runner=runner,
        )
    )

    snapshot = supervisor.status_snapshot()
    result = supervisor.start_paper(_valid_request())

    assert snapshot["paper_baseline_runtime_context"]["baseline_loaded"] is False
    assert result["allowed"] is False
    assert result["reason_code"] == PAPER_BASELINE_RUNTIME_CONTEXT_REQUIRED
    assert runner.started_specs == []


def test_watchlist_overlap_can_start_only_when_baseline_guard_context_is_active():
    runner = FakeRunner()
    _write_accepted_baseline(runner.repo_root)
    supervisor = _with_proven_broker_preflight(
        OperatorPaperSupervisor(config=_supervisor_config(runner), runner=runner)
    )

    result = supervisor.start_paper(_valid_request())

    assert result["allowed"] is True
    assert result["paper_baseline_runtime_context"]["protected_symbols_normalized"] == ["BTCUSD", "ETHUSD", "SOLUSD"]
    assert result["paper_baseline_runtime_context"]["same_symbol_baseline_guard_active"] is True
    assert runner.started_specs[0].env[PAPER_BASELINE_ENV_PROTECTED_SYMBOLS] == "BTCUSD,ETHUSD,SOLUSD"


def test_supervisor_allows_missing_base_url_by_safe_paper_default():
    runner = FakeRunner()
    config = PaperSupervisorConfig(
        repo_root=runner.repo_root,
        process_env={
            "APCA_API_KEY_ID": "test-paper-key",
            "APCA_API_SECRET_KEY": "test-paper-secret",
        },
    )
    supervisor = _with_proven_broker_preflight(OperatorPaperSupervisor(config=config, runner=runner))

    snapshot = supervisor.status_snapshot()
    result = supervisor.start_paper(_valid_request())

    assert snapshot["paper_credentials_configured"] is True
    assert snapshot["paper_endpoint_only"] is True
    assert snapshot["paper_endpoint_status"] == "PAPER_ENDPOINT_CONFIRMED"
    assert snapshot["paper_endpoint_source"] == "SAFE_DEFAULT_PAPER_ENDPOINT"
    assert snapshot["paper_start_allowed"] is True
    assert result["allowed"] is True
    assert result["reason_code"] == "PAPER_RUN_STARTED"


def test_supervisor_normalizes_paper_endpoint_variant_before_start_authority():
    runner = FakeRunner()
    config = PaperSupervisorConfig(
        repo_root=runner.repo_root,
        process_env={
            "APCA_API_KEY_ID": "test-paper-key",
            "APCA_API_SECRET_KEY": "test-paper-secret",
            "APCA_API_BASE_URL": " HTTPS://PAPER-API.ALPACA.MARKETS/v2 ",
        },
    )
    supervisor = _with_proven_broker_preflight(OperatorPaperSupervisor(config=config, runner=runner))

    snapshot = supervisor.status_snapshot()
    result = supervisor.start_paper(_valid_request())

    assert snapshot["paper_endpoint_only"] is True
    assert snapshot["paper_endpoint_status"] == "PAPER_ENDPOINT_CONFIRMED"
    assert snapshot["paper_endpoint_authority"]["alpaca_endpoint_display"] == "https://paper-api.alpaca.markets"
    assert result["allowed"] is True
    assert result["reason_code"] == "PAPER_RUN_STARTED"
    assert runner.started_specs[0].env["APCA_API_BASE_URL"] == "https://paper-api.alpaca.markets"


def test_supervisor_splits_live_endpoint_block_from_key_presence():
    runner = FakeRunner()
    config = PaperSupervisorConfig(
        repo_root=runner.repo_root,
        process_env={
            "APCA_API_KEY_ID": "test-paper-key",
            "APCA_API_SECRET_KEY": "test-paper-secret",
            "APCA_API_BASE_URL": "https://api.alpaca.markets",
        },
    )
    supervisor = OperatorPaperSupervisor(config=config, runner=runner)

    snapshot = supervisor.status_snapshot()
    result = supervisor.start_paper(_valid_request())

    assert snapshot["paper_credentials_configured"] is True
    assert snapshot["paper_credential_refusal_reason"] is None
    assert snapshot["paper_endpoint_only"] is False
    assert snapshot["paper_endpoint_status"] == "LIVE_ENDPOINT_BLOCKED"
    assert snapshot["paper_endpoint_refusal_reason"] == "LIVE_ENDPOINT_BLOCKED"
    assert snapshot["paper_start_allowed"] is False
    assert result["allowed"] is False
    assert result["reason_code"] == "LIVE_ENDPOINT_BLOCKED"
    assert runner.started_specs == []


def test_supervisor_rejects_duplicate_active_run():
    runner = FakeRunner()
    supervisor = _with_proven_broker_preflight(
        OperatorPaperSupervisor(config=_supervisor_config(runner), runner=runner)
    )
    first = supervisor.start_paper(_valid_request())
    second = supervisor.start_paper(_valid_request())

    assert first["allowed"] is True
    assert second["allowed"] is False
    assert second["reason_code"] == "DUPLICATE_ACTIVE_RUN"
    assert len(runner.started_specs) == 1


def test_supervisor_rejects_live_real_money_unknown_profile_and_ineligible_priority_symbol():
    runner = FakeRunner()
    supervisor = OperatorPaperSupervisor(config=PaperSupervisorConfig(repo_root=runner.repo_root), runner=runner)

    live = dict(_valid_request(), mode="LIVE")
    real_money = dict(_valid_request(), real_money=True)
    profile = dict(_valid_request(), profile="DEFAULT")

    assert supervisor.start_paper(live)["reason_code"] == "LIVE_NOT_APPROVED"
    assert supervisor.start_paper(real_money)["reason_code"] == "REAL_MONEY_NOT_APPROVED"
    assert supervisor.start_paper(profile)["reason_code"] == "UNSUPPORTED_PAPER_PROFILE"

    capability_supervisor = _with_proven_broker_preflight(
        OperatorPaperSupervisor(config=_supervisor_config(runner), runner=runner)
    )
    watchlist = dict(_valid_request(), watchlist=["AAPL"])
    assert capability_supervisor.start_paper(watchlist)["reason_code"] == "PRIORITY_SYMBOL_NOT_ENTRY_ELIGIBLE"
    assert runner.started_specs == []


def test_supervisor_rejects_missing_approval_and_out_of_range_duration():
    runner = FakeRunner()
    supervisor = OperatorPaperSupervisor(config=PaperSupervisorConfig(repo_root=runner.repo_root), runner=runner)

    missing_approval = dict(_valid_request(), approve_autonomous_paper=False)
    duration = dict(_valid_request(), duration_seconds=432001)

    assert supervisor.start_paper(missing_approval)["reason_code"] == "AUTONOMOUS_PAPER_APPROVAL_REQUIRED"
    assert supervisor.start_paper(duration)["reason_code"] == "DURATION_ABOVE_MAXIMUM_SECONDS"
    assert runner.started_specs == []


def test_supervisor_accepts_custom_duration_up_to_five_days():
    runner = FakeRunner()
    supervisor = _with_proven_broker_preflight(
        OperatorPaperSupervisor(config=_supervisor_config(runner), runner=runner)
    )

    result = supervisor.start_paper(dict(_valid_request(), duration_seconds=432000))
    snapshot = supervisor.status_snapshot()

    assert result["allowed"] is True
    assert result["session"]["duration_seconds"] == 432000
    assert "432000" in runner.started_specs[0].command
    assert snapshot["max_paper_duration_seconds"] == 432000
    assert snapshot["runner_max_paper_duration_seconds"] == 432000
    assert snapshot["duration_authority"] == "scripts/run_bounded_paper.ps1"


def test_supervisor_rejects_duration_above_five_day_runner_authority():
    runner = FakeRunner()
    supervisor = OperatorPaperSupervisor(config=_supervisor_config(runner), runner=runner)

    result = supervisor.start_paper(dict(_valid_request(), duration_seconds=604800))

    assert result["allowed"] is False
    assert result["reason_code"] == "DURATION_ABOVE_MAXIMUM_SECONDS"
    assert runner.started_specs == []


def test_supervisor_tracks_exit_code_and_status():
    runner = FakeRunner()
    supervisor = _with_proven_broker_preflight(
        OperatorPaperSupervisor(config=_supervisor_config(runner), runner=runner)
    )
    supervisor.start_paper(_valid_request())
    runner.process.exit_code = 0

    snapshot = supervisor.status_snapshot()

    assert snapshot["state"] == "IDLE"
    assert snapshot["latest_session"]["status"] == "EXITED"
    assert snapshot["latest_session"]["exit_code"] == 0
    assert snapshot["paper_start_allowed"] is True


def test_supervisor_persists_session_and_parses_child_log_paths(tmp_path):
    runner = FakeRunner()
    store = OperatorSessionStore(path=tmp_path / "state" / "operator" / "sessions.jsonl")
    supervisor = _with_proven_broker_preflight(
        OperatorPaperSupervisor(
            config=_supervisor_config(
                runner,
                session_store_path=str(tmp_path / "state" / "operator" / "sessions.jsonl"),
            ),
            runner=runner,
            session_store=store,
        )
    )
    result = supervisor.start_paper(_valid_request())
    wrapper_stdout = Path(result["session"]["stdout_path"])
    wrapper_stdout.parent.mkdir(parents=True, exist_ok=True)
    wrapper_stdout.write_text(
        "stdout: logs\\paper_runs\\bounded_paper_20260527_120000.out.log\n"
        "stderr: logs\\paper_runs\\bounded_paper_20260527_120000.err.log\n"
        "BOUNDED_RUNTIME_TIMER_STARTED\n"
        "BOUNDED_RUNTIME_DURATION_ELAPSED\n",
        encoding="utf-8",
    )
    runner.process.exit_code = 0

    snapshot = supervisor.status_snapshot()
    reloaded_store = OperatorSessionStore(path=tmp_path / "state" / "operator" / "sessions.jsonl")
    reloaded = OperatorPaperSupervisor(
        config=PaperSupervisorConfig(
            repo_root=runner.repo_root,
            session_store_path=str(tmp_path / "state" / "operator" / "sessions.jsonl"),
        ),
        runner=runner,
        session_store=reloaded_store,
    )

    assert snapshot["latest_session"]["status"] == "EXITED"
    assert snapshot["latest_session"]["child_stdout_path"].endswith(".out.log")
    assert snapshot["latest_session"]["child_stderr_path"].endswith(".err.log")
    assert snapshot["latest_session"]["bounded_timer_started"] is True
    assert snapshot["latest_session"]["bounded_duration_elapsed"] is True
    assert reloaded.status_snapshot()["latest_session"]["session_id"] == result["session_id"]


def test_governed_stop_halts_loop_releases_lease_without_broker_mutation_and_preserves_positions(monkeypatch):
    runner = FakeRunner()
    accepted = accept_existing_position_baseline(
        {
            **_baseline_snapshot(),
            "position_count": 4,
            "positions": [
                {"symbol": "AVAXUSD", "asset_class": "crypto", "qty": "10", "side": "long"},
                {"symbol": "ETHUSD", "asset_class": "crypto", "qty": "2", "side": "long"},
                {"symbol": "LINKUSD", "asset_class": "crypto", "qty": "25", "side": "long"},
                {"symbol": "SOLUSD", "asset_class": "crypto", "qty": "8", "side": "long"},
            ],
        },
        accepted_by="Shan/local operator",
    )
    state_dir = runner.repo_root / "durable_operator_state"
    state_dir.mkdir(parents=True)
    baseline_path = state_dir / "paper_baseline.json"
    baseline_path.write_text(json.dumps(accepted), encoding="utf-8")
    supervisor = _with_proven_broker_preflight(
        OperatorPaperSupervisor(
            config=_supervisor_config(runner, operator_state_dir=str(state_dir)),
            runner=runner,
        )
    )
    mutation_calls: list[str] = []
    monkeypatch.setattr(
        "app.execution.alpaca_paper_adapter.AlpacaPaperBrokerAdapter.submit_order",
        lambda *args, **kwargs: mutation_calls.append("submit_order"),
    )
    monkeypatch.setattr(
        "app.execution.alpaca_paper_adapter.AlpacaPaperBrokerAdapter.cancel_order",
        lambda *args, **kwargs: mutation_calls.append("cancel_order"),
    )
    monkeypatch.setattr(
        "app.execution.order_router.OrderRouter.close_all_positions",
        lambda *args, **kwargs: mutation_calls.append("close_all_positions"),
    )
    supervisor.start_paper(_valid_request())

    stopped = supervisor.stop_paper({})
    snapshot = supervisor.status_snapshot()
    persisted = json.loads(baseline_path.read_text(encoding="utf-8"))

    assert stopped["allowed"] is True
    assert stopped["reason_code"] == "GOVERNED_STOP_COMPLETED_NO_BROKER_MUTATION"
    assert stopped["stop_signal_reason"] == "CTRL_BREAK_EVENT_SENT"
    assert stopped["run_loop_halted"] is True
    assert stopped["new_entries_ceased"] is True
    assert stopped["lease_released"] is True
    assert stopped["child_process_terminated"] is True
    assert stopped["broker_position_mutation_requested"] is False
    assert stopped["broker_positions_reconciled_after_stop"] is False
    assert stopped["broker_positions_preservation_status"] == "UNKNOWN_PENDING_FINAL_BROKER_RECONCILIATION"
    assert stopped["governed_position_lifecycle_authority_unchanged"] is True
    assert stopped["governed_position_lifecycle_active_after_stop"] is False
    assert stopped["final_reconciliation_required"] is True
    assert stopped["broker_call_occurred"] is False
    assert stopped["broker_mutation_occurred"] is False
    assert stopped["order_submission_occurred"] is False
    assert stopped["cancel_occurred"] is False
    assert stopped["liquidation_occurred"] is False
    assert stopped["close_position_occurred"] is False
    assert stopped["runtime_mutation_occurred"] is True
    assert runner.stop_requests == 1
    assert runner.wait_requests == 1
    assert snapshot["state"] == "IDLE"
    assert snapshot["latest_session"]["status"] == "STOPPED"
    assert snapshot["active_session"] is None
    assert snapshot["paper_stop_allowed"] is False
    assert mutation_calls == []
    assert persisted == accepted
    assert stopped["paper_baseline_runtime_context"]["same_symbol_baseline_guard_active"] is True
    assert stopped["paper_baseline_runtime_context"]["protected_symbols_normalized"] == [
        "AVAXUSD",
        "ETHUSD",
        "LINKUSD",
        "SOLUSD",
    ]


def test_supervisor_refuses_stop_without_active_run():
    runner = FakeRunner()
    supervisor = OperatorPaperSupervisor(config=PaperSupervisorConfig(repo_root=runner.repo_root), runner=runner)

    stopped = supervisor.stop_paper({})

    assert stopped["allowed"] is False
    assert stopped["reason_code"] == "NO_ACTIVE_RUN"
    assert stopped["broker_call_occurred"] is False
    assert stopped["runtime_mutation_occurred"] is False


def test_supervisor_refuses_when_runner_unavailable():
    runner = FakeRunner(available=False, unavailable_reason="WINDOWS_POWERSHELL_REQUIRED")
    supervisor = _with_proven_broker_preflight(
        OperatorPaperSupervisor(config=_supervisor_config(runner), runner=runner)
    )

    result = supervisor.start_paper(_valid_request())

    assert result["allowed"] is False
    assert result["reason_code"] == "WINDOWS_POWERSHELL_REQUIRED"
    assert result["runtime_mutation_occurred"] is False
    assert runner.started_specs == []


def test_supervisor_refuses_paper_start_before_runner_when_credentials_missing():
    runner = FakeRunner()
    supervisor = OperatorPaperSupervisor(config=PaperSupervisorConfig(repo_root=runner.repo_root), runner=runner)

    result = supervisor.start_paper(_valid_request())
    snapshot = supervisor.status_snapshot()

    assert result["allowed"] is False
    assert result["reason_code"] == "ALPACA_PAPER_CREDENTIALS_NOT_CONFIGURED"
    assert snapshot["paper_credentials_configured"] is False
    assert snapshot["paper_start_allowed"] is False
    assert runner.started_specs == []


def test_supervisor_auto_reconciles_dead_prior_pid_on_startup_without_broker_call():
    runner = FakeRunner()
    store = OperatorSessionStore(runner.repo_root / "state" / "operator" / "sessions.jsonl")
    store.write_session(
        {
            "session_id": "paper_dead_on_startup",
            "requested_at": "2026-06-14T04:17:12+00:00",
            "status": "RUNNING",
            "profile": "PAPER_EXPLORATION_ALPHA",
            "watchlist": ["BTC/USD", "ETH/USD", "SOL/USD"],
            "duration_seconds": 300,
            "pid": 987654,
            "started_at": "2026-06-14T04:17:12+00:00",
        }
    )

    supervisor = _with_proven_broker_preflight(
        OperatorPaperSupervisor(
            config=_supervisor_config(runner, session_store_path=str(store.path)),
            runner=runner,
            session_store=store,
            pid_liveness_probe=lambda pid: (False, "STALE_SESSION_PROCESS_NOT_RUNNING"),
        )
    )
    snapshot = supervisor.status_snapshot()
    start = supervisor.start_paper(_valid_request())

    assert snapshot["state"] == "IDLE"
    assert snapshot["latest_session"]["status"] == "STALE_RECONCILED"
    assert snapshot["latest_session"]["stop_reason"] == "AUTO_RECONCILED_ON_API_STARTUP_PID_NOT_RUNNING"
    assert snapshot["startup_lifecycle_reconciliation"]["status"] == "AUTO_RECONCILED_DEAD_PID"
    assert snapshot["startup_lifecycle_reconciliation"]["broker_call_occurred"] is False
    assert snapshot["paper_start_allowed"] is True
    assert start["allowed"] is True


def test_supervisor_adopts_running_prior_pid_on_startup_and_allows_governed_stop():
    runner = FakeRunner()
    process_running = True

    def liveness(_pid):
        return (
            process_running,
            "STALE_SESSION_PROCESS_STILL_RUNNING" if process_running else "STALE_SESSION_PROCESS_NOT_RUNNING",
        )

    def mark_stopped():
        nonlocal process_running
        process_running = False

    runner.on_stop = mark_stopped
    store = OperatorSessionStore(runner.repo_root / "state" / "operator" / "sessions.jsonl")
    store.write_session(
        {
            "session_id": "paper_running_on_startup",
            "requested_at": "2026-06-14T04:17:12+00:00",
            "status": "RUNNING",
            "profile": "PAPER_EXPLORATION_ALPHA",
            "watchlist": ["BTC/USD", "ETH/USD", "SOL/USD"],
            "duration_seconds": 300,
            "pid": 24680,
            "started_at": "2026-06-14T04:17:12+00:00",
        }
    )

    supervisor = OperatorPaperSupervisor(
        config=_supervisor_config(runner, session_store_path=str(store.path)),
        runner=runner,
        session_store=store,
        pid_liveness_probe=liveness,
    )
    snapshot = supervisor.status_snapshot()
    stopped = supervisor.stop_paper({})

    assert snapshot["state"] == "RUNNING"
    assert snapshot["active_session_id"] == "paper_running_on_startup"
    assert snapshot["paper_start_allowed"] is False
    assert snapshot["paper_stop_allowed"] is True
    assert snapshot["startup_lifecycle_reconciliation"]["status"] == "ADOPTED_RUNNING_PID"
    assert stopped["allowed"] is True
    assert runner.stop_requests == 1
    assert runner.wait_requests == 1
    assert runner.stop_request_pids[-1] == 24680
    assert stopped["broker_call_occurred"] is False


def test_supervisor_fails_closed_when_prior_pid_liveness_is_ambiguous():
    runner = FakeRunner()
    store = OperatorSessionStore(runner.repo_root / "state" / "operator" / "sessions.jsonl")
    store.write_session(
        {
            "session_id": "paper_ambiguous_on_startup",
            "requested_at": "2026-06-14T04:17:12+00:00",
            "status": "RUNNING",
            "profile": "PAPER_EXPLORATION_ALPHA",
            "watchlist": ["BTC/USD", "ETH/USD", "SOL/USD"],
            "duration_seconds": 300,
            "pid": 13579,
            "started_at": "2026-06-14T04:17:12+00:00",
        }
    )

    supervisor = OperatorPaperSupervisor(
        config=_supervisor_config(runner, session_store_path=str(store.path)),
        runner=runner,
        session_store=store,
        pid_liveness_probe=lambda pid: (None, "STALE_SESSION_PID_CHECK_FAILED"),
    )
    snapshot = supervisor.status_snapshot()
    start = supervisor.start_paper(_valid_request())

    assert snapshot["state"] == "STALE_ACTIVE_SESSION"
    assert snapshot["paper_start_allowed"] is False
    assert snapshot["paper_start_refusal_reason"] == "PREVIOUS_SESSION_STATE_UNKNOWN_AFTER_RESTART"
    assert snapshot["startup_lifecycle_reconciliation"]["status"] == "FAILED_CLOSED_AMBIGUOUS_PID"
    assert snapshot["stale_reconciliation"]["available"] is False
    assert start["allowed"] is False
    assert start["reason_code"] == "PREVIOUS_SESSION_STATE_UNKNOWN_AFTER_RESTART"


def test_supervisor_shutdown_active_process_group_without_broker_call():
    runner = FakeRunner()
    supervisor = _with_proven_broker_preflight(
        OperatorPaperSupervisor(config=_supervisor_config(runner), runner=runner)
    )
    supervisor.start_paper(_valid_request())

    shutdown = supervisor.shutdown_active_processes("TEST_API_SHUTDOWN")
    snapshot = supervisor.status_snapshot()

    assert shutdown["allowed"] is True
    assert shutdown["reason_code"] == "PROCESS_GROUP_SHUTDOWN_SENT"
    assert shutdown["broker_call_occurred"] is False
    assert shutdown["broker_mutation_occurred"] is False
    assert runner.shutdown_requests == 1
    assert snapshot["latest_session"]["stop_reason"] == "TEST_API_SHUTDOWN"


def test_subprocess_runner_declares_parent_death_lifecycle_on_linux():
    runner = SubprocessPaperRunner()
    kwargs = runner._popen_lifecycle_kwargs()

    if sys.platform.startswith("linux"):
        assert kwargs["preexec_fn"].__name__ == "_linux_child_preexec"
    elif os.name == "nt":
        assert "creationflags" in kwargs
    else:
        assert kwargs["start_new_session"] is True


def test_supervisor_reconciles_stale_session_after_pid_proof_and_confirmations():
    runner = FakeRunner()
    store = OperatorSessionStore(runner.repo_root / "state" / "operator" / "sessions.jsonl")
    store.write_session(
        {
            "session_id": "paper_stale_for_reconcile",
            "requested_at": "2026-06-14T04:17:12+00:00",
            "status": "RUNNING",
            "profile": "PAPER_EXPLORATION_ALPHA",
            "watchlist": ["BTC/USD", "ETH/USD", "SOL/USD"],
            "duration_seconds": 300,
            "pid": 987654,
            "started_at": "2026-06-14T04:17:12+00:00",
        }
    )
    supervisor = _with_proven_broker_preflight(
        OperatorPaperSupervisor(
            config=_supervisor_config(runner, session_store_path=str(store.path), startup_lifecycle_reconcile=False),
            runner=runner,
            session_store=store,
        )
    )
    supervisor._is_pid_running = lambda pid: (False, "STALE_SESSION_PROCESS_NOT_RUNNING")  # type: ignore[method-assign]

    missing = supervisor.reconcile_stale_session({})
    reconciled = supervisor.reconcile_stale_session(
        {
            "confirm_stale_session_reviewed": True,
            "confirm_previous_process_not_running": True,
            "confirm_runtime_visibility_stopped": True,
            "confirm_no_broker_cleanup_requested": True,
        }
    )
    snapshot = supervisor.status_snapshot()
    start = supervisor.start_paper(_valid_request())

    assert missing["allowed"] is False
    assert missing["reason_code"] == "MISSING_STALE_SESSION_REVIEW_CONFIRMATION"
    assert reconciled["allowed"] is True
    assert reconciled["reason_code"] == "STALE_SESSION_RECONCILED_PID_NOT_RUNNING"
    assert reconciled["broker_call_occurred"] is False
    assert reconciled["runtime_mutation_occurred"] is True
    assert reconciled["session"]["status"] == "STALE_RECONCILED"
    assert snapshot["state"] == "IDLE"
    assert snapshot["paper_start_allowed"] is True
    assert start["allowed"] is True
    assert start["reason_code"] == "PAPER_RUN_STARTED"


def test_supervisor_refuses_stale_reconcile_when_previous_pid_is_running():
    runner = FakeRunner()
    store = OperatorSessionStore(runner.repo_root / "state" / "operator" / "sessions.jsonl")
    store.write_session(
        {
            "session_id": "paper_stale_pid_running",
            "requested_at": "2026-06-14T04:17:12+00:00",
            "status": "RUNNING",
            "profile": "PAPER_EXPLORATION_ALPHA",
            "watchlist": ["BTC/USD", "ETH/USD", "SOL/USD"],
            "duration_seconds": 300,
            "pid": 12345,
            "started_at": "2026-06-14T04:17:12+00:00",
        }
    )
    supervisor = OperatorPaperSupervisor(
        config=_supervisor_config(runner, session_store_path=str(store.path), startup_lifecycle_reconcile=False),
        runner=runner,
        session_store=store,
    )
    supervisor._is_pid_running = lambda pid: (True, "STALE_SESSION_PROCESS_STILL_RUNNING")  # type: ignore[method-assign]

    result = supervisor.reconcile_stale_session(
        {
            "confirm_stale_session_reviewed": True,
            "confirm_previous_process_not_running": True,
            "confirm_runtime_visibility_stopped": True,
            "confirm_no_broker_cleanup_requested": True,
        }
    )
    snapshot = supervisor.status_snapshot()

    assert result["allowed"] is False
    assert result["reason_code"] == "STALE_SESSION_PROCESS_STILL_RUNNING"
    assert result["broker_call_occurred"] is False
    assert result["runtime_mutation_occurred"] is False
    assert snapshot["state"] == "STALE_ACTIVE_SESSION"
    assert snapshot["paper_start_allowed"] is False
