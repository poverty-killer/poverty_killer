from __future__ import annotations

from pathlib import Path

from app.api.operator_paper_supervisor import (
    OperatorPaperSupervisor,
    PaperSupervisorConfig,
    ProcessStartSpec,
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
        self.repo_root = Path("/tmp/pk-operator-supervisor-test")
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


def test_supervisor_accepts_valid_paper_start_and_builds_safe_command():
    runner = FakeRunner()
    supervisor = OperatorPaperSupervisor(config=PaperSupervisorConfig(repo_root=runner.repo_root), runner=runner)

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


def test_supervisor_rejects_duplicate_active_run():
    runner = FakeRunner()
    supervisor = OperatorPaperSupervisor(config=PaperSupervisorConfig(repo_root=runner.repo_root), runner=runner)
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


def test_supervisor_rejects_missing_approval_and_unsupported_duration():
    runner = FakeRunner()
    supervisor = OperatorPaperSupervisor(config=PaperSupervisorConfig(repo_root=runner.repo_root), runner=runner)

    missing_approval = dict(_valid_request(), approve_autonomous_paper=False)
    duration = dict(_valid_request(), duration_seconds=999)

    assert supervisor.start_paper(missing_approval)["reason_code"] == "AUTONOMOUS_PAPER_APPROVAL_REQUIRED"
    assert supervisor.start_paper(duration)["reason_code"] == "UNSUPPORTED_DURATION_SECONDS"
    assert runner.started_specs == []


def test_supervisor_tracks_exit_code_and_status():
    runner = FakeRunner()
    supervisor = OperatorPaperSupervisor(config=PaperSupervisorConfig(repo_root=runner.repo_root), runner=runner)
    supervisor.start_paper(_valid_request())
    runner.process.exit_code = 0

    snapshot = supervisor.status_snapshot()

    assert snapshot["state"] == "IDLE"
    assert snapshot["latest_session"]["status"] == "EXITED"
    assert snapshot["latest_session"]["exit_code"] == 0
    assert snapshot["paper_start_allowed"] is True


def test_supervisor_stop_requests_graceful_process_stop_without_broker_call():
    runner = FakeRunner()
    supervisor = OperatorPaperSupervisor(config=PaperSupervisorConfig(repo_root=runner.repo_root), runner=runner)
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
    supervisor = OperatorPaperSupervisor(config=PaperSupervisorConfig(repo_root=runner.repo_root), runner=runner)

    result = supervisor.start_paper(_valid_request())

    assert result["allowed"] is False
    assert result["reason_code"] == "WINDOWS_POWERSHELL_REQUIRED"
    assert result["runtime_mutation_occurred"] is False
    assert runner.started_specs == []
