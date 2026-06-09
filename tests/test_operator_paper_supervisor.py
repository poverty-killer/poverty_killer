from __future__ import annotations

import json
import tempfile
from pathlib import Path

from app.api.operator_paper_supervisor import (
    BOUNDED_RUNTIME_COMPLETED,
    DURATION_BOUND_EXCEEDED,
    OperatorPaperSupervisor,
    PaperSupervisorConfig,
    ProcessStartSpec,
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
        self.process = FakeProcess()

    def is_available(self, repo_root: Path):
        assert repo_root == self.repo_root
        return self.available, self.unavailable_reason

    def start(self, spec: ProcessStartSpec):
        self.started_specs.append(spec)
        return self.process

    def request_graceful_stop(self, handle: FakeProcess):
        assert handle is self.process
        self.stop_requests += 1
        return True, "CTRL_BREAK_EVENT_SENT"


def _valid_request() -> dict:
    return {
        "mode": "PAPER",
        "profile": "PAPER_EXPLORATION_ALPHA",
        "duration_seconds": 300,
        "watchlist": ["BTC/USD", "ETH/USD", "SOL/USD"],
        "approve_autonomous_paper": True,
    }


def _paper_env() -> dict[str, str]:
    return {
        "APCA_API_KEY_ID": "test-paper-key",
        "APCA_API_SECRET_KEY": "test-paper-secret",
        "APCA_API_BASE_URL": "https://paper-api.alpaca.markets",
    }


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
    supervisor = OperatorPaperSupervisor(config=_supervisor_config(runner), runner=runner)

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
    assert "BTC/USD,ETH/USD,SOL/USD" in command
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
    supervisor = OperatorPaperSupervisor(config=_supervisor_config(runner), runner=runner)

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
    supervisor = OperatorPaperSupervisor(
        config=PaperSupervisorConfig(repo_root=runner.repo_root, process_env=env),
        runner=runner,
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
    supervisor = OperatorPaperSupervisor(config=_supervisor_config(runner), runner=runner)

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
    supervisor = OperatorPaperSupervisor(config=config, runner=runner)

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
    supervisor = OperatorPaperSupervisor(config=config, runner=runner)

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
    supervisor = OperatorPaperSupervisor(config=_supervisor_config(runner), runner=runner)
    first = supervisor.start_paper(_valid_request())
    second = supervisor.start_paper(_valid_request())

    assert first["allowed"] is True
    assert second["allowed"] is False
    assert second["reason_code"] == "DUPLICATE_ACTIVE_RUN"
    assert len(runner.started_specs) == 1


def test_supervisor_rejects_live_real_money_unknown_profile_and_watchlist():
    runner = FakeRunner()
    supervisor = OperatorPaperSupervisor(config=PaperSupervisorConfig(repo_root=runner.repo_root), runner=runner)

    live = dict(_valid_request(), mode="LIVE")
    real_money = dict(_valid_request(), real_money=True)
    profile = dict(_valid_request(), profile="DEFAULT")
    watchlist = dict(_valid_request(), watchlist=["AAPL"])

    assert supervisor.start_paper(live)["reason_code"] == "LIVE_NOT_APPROVED"
    assert supervisor.start_paper(real_money)["reason_code"] == "REAL_MONEY_NOT_APPROVED"
    assert supervisor.start_paper(profile)["reason_code"] == "UNSUPPORTED_PAPER_PROFILE"
    assert supervisor.start_paper(watchlist)["reason_code"] == "UNSUPPORTED_WATCHLIST_SYMBOL"
    assert runner.started_specs == []


def test_supervisor_rejects_missing_approval_and_out_of_range_duration():
    runner = FakeRunner()
    supervisor = OperatorPaperSupervisor(config=PaperSupervisorConfig(repo_root=runner.repo_root), runner=runner)

    missing_approval = dict(_valid_request(), approve_autonomous_paper=False)
    duration = dict(_valid_request(), duration_seconds=86401)

    assert supervisor.start_paper(missing_approval)["reason_code"] == "AUTONOMOUS_PAPER_APPROVAL_REQUIRED"
    assert supervisor.start_paper(duration)["reason_code"] == "DURATION_ABOVE_MAXIMUM_SECONDS"
    assert runner.started_specs == []


def test_supervisor_accepts_custom_duration_up_to_one_day():
    runner = FakeRunner()
    supervisor = OperatorPaperSupervisor(config=_supervisor_config(runner), runner=runner)

    result = supervisor.start_paper(dict(_valid_request(), duration_seconds=86400))
    snapshot = supervisor.status_snapshot()

    assert result["allowed"] is True
    assert result["session"]["duration_seconds"] == 86400
    assert "86400" in runner.started_specs[0].command
    assert snapshot["max_paper_duration_seconds"] == 86400
    assert snapshot["runner_max_paper_duration_seconds"] == 86400
    assert snapshot["duration_authority"] == "scripts/run_bounded_paper.ps1"


def test_supervisor_rejects_multi_day_duration_that_runner_would_fail_close():
    runner = FakeRunner()
    supervisor = OperatorPaperSupervisor(config=_supervisor_config(runner), runner=runner)

    result = supervisor.start_paper(dict(_valid_request(), duration_seconds=604800))

    assert result["allowed"] is False
    assert result["reason_code"] == "DURATION_ABOVE_MAXIMUM_SECONDS"
    assert runner.started_specs == []


def test_supervisor_tracks_exit_code_and_status():
    runner = FakeRunner()
    supervisor = OperatorPaperSupervisor(config=_supervisor_config(runner), runner=runner)
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
    supervisor = OperatorPaperSupervisor(
        config=_supervisor_config(
            runner,
            session_store_path=str(tmp_path / "state" / "operator" / "sessions.jsonl"),
        ),
        runner=runner,
        session_store=store,
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


def test_supervisor_stop_requests_graceful_process_stop_without_broker_call():
    runner = FakeRunner()
    supervisor = OperatorPaperSupervisor(config=_supervisor_config(runner), runner=runner)
    supervisor.start_paper(_valid_request())

    stopped = supervisor.stop_paper({})

    assert stopped["allowed"] is True
    assert stopped["reason_code"] == "CTRL_BREAK_EVENT_SENT"
    assert stopped["broker_call_occurred"] is False
    assert stopped["runtime_mutation_occurred"] is True
    assert runner.stop_requests == 1


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
    supervisor = OperatorPaperSupervisor(config=_supervisor_config(runner), runner=runner)

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
