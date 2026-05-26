"""Governed local PAPER process supervisor for the Operator API.

The supervisor starts only bounded Alpaca PAPER runs through the existing
PowerShell launch authority. It does not import broker adapters, execution
engine code, OMS internals, or strategy modules.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol


SUPERVISOR_VERSION = "operator-paper-supervisor-v1"
PAPER_PROFILE = "PAPER_EXPLORATION_ALPHA"
DEFAULT_WATCHLIST = ("BTC/USD", "ETH/USD", "SOL/USD")
DEFAULT_ALLOWED_DURATIONS = frozenset({180, 300, 1200, 7200, 10800, 14400})


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def repo_root_from_here() -> Path:
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ProcessStartSpec:
    command: tuple[str, ...]
    cwd: str
    stdout_path: str
    stderr_path: str
    command_summary: str


class PaperProcessHandle(Protocol):
    pid: int

    def poll(self) -> int | None:
        ...


class PaperProcessRunner(Protocol):
    def is_available(self, repo_root: Path) -> tuple[bool, str | None]:
        ...

    def start(self, spec: ProcessStartSpec) -> PaperProcessHandle:
        ...

    def request_graceful_stop(self, handle: PaperProcessHandle) -> tuple[bool, str]:
        ...


class SubprocessPaperRunner:
    """Default runner used outside tests.

    It launches the existing Windows PowerShell bounded PAPER script. Safe stop
    is only advertised on native Windows because `main.py` treats SIGTERM as a
    termination path that can flatten positions; this runner avoids generic
    terminate/kill for operator stop requests.
    """

    def is_available(self, repo_root: Path) -> tuple[bool, str | None]:
        script = repo_root / "scripts" / "run_bounded_paper.ps1"
        python_path = repo_root / "venv" / "Scripts" / "python.exe"
        if not script.exists():
            return False, "PAPER_RUN_SCRIPT_MISSING"
        if not python_path.exists():
            return False, "WINDOWS_VENV_PYTHON_NOT_FOUND"
        if os.name != "nt":
            return False, "WINDOWS_POWERSHELL_REQUIRED"
        if shutil.which("powershell.exe") is None and shutil.which("pwsh") is None:
            return False, "POWERSHELL_NOT_FOUND"
        return True, None

    def start(self, spec: ProcessStartSpec) -> PaperProcessHandle:
        stdout_file = open(spec.stdout_path, "a", encoding="utf-8")
        stderr_file = open(spec.stderr_path, "a", encoding="utf-8")
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        try:
            return subprocess.Popen(
                list(spec.command),
                cwd=spec.cwd,
                stdout=stdout_file,
                stderr=stderr_file,
                stdin=subprocess.DEVNULL,
                creationflags=creationflags,
            )
        finally:
            stdout_file.close()
            stderr_file.close()

    def request_graceful_stop(self, handle: PaperProcessHandle) -> tuple[bool, str]:
        if handle.poll() is not None:
            return True, "PROCESS_ALREADY_EXITED"
        if os.name != "nt" or not hasattr(signal, "CTRL_BREAK_EVENT"):
            return False, "SAFE_STOP_UNAVAILABLE_NON_WINDOWS"
        try:
            process = handle  # subprocess.Popen at runtime
            process.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
            return True, "CTRL_BREAK_EVENT_SENT"
        except Exception:
            return False, "GRACEFUL_STOP_SIGNAL_FAILED"


@dataclass
class PaperRunSession:
    session_id: str
    requested_at: str
    status: str
    profile: str
    watchlist: tuple[str, ...]
    duration_seconds: int
    command_summary: str | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    pid: int | None = None
    started_at: str | None = None
    ended_at: str | None = None
    exit_code: int | None = None
    refusal_reason: str | None = None
    last_status_check_at: str | None = None
    stop_requested_at: str | None = None
    stop_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["watchlist"] = list(self.watchlist)
        return data


@dataclass
class AuditEvent:
    audit_event_id: str
    timestamp: str
    intent: str
    allowed: bool
    reason_code: str
    session_id: str | None
    runtime_mutation_occurred: bool
    broker_call_occurred: bool = False
    live_endpoint_touched: bool = False
    real_money_touched: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PaperSupervisorConfig:
    repo_root: Path = field(default_factory=repo_root_from_here)
    allowed_profile: str = PAPER_PROFILE
    allowed_watchlist: tuple[str, ...] = DEFAULT_WATCHLIST
    allowed_durations: frozenset[int] = DEFAULT_ALLOWED_DURATIONS
    log_directory: str = "logs/operator_runs"
    script_path: str = "scripts/run_bounded_paper.ps1"
    powershell_executable: str = "powershell.exe"


class OperatorPaperSupervisor:
    def __init__(
        self,
        *,
        config: PaperSupervisorConfig | None = None,
        runner: PaperProcessRunner | None = None,
    ) -> None:
        self.config = config or PaperSupervisorConfig()
        self.runner = runner or SubprocessPaperRunner()
        self._session: PaperRunSession | None = None
        self._process: PaperProcessHandle | None = None
        self._audit_events: list[AuditEvent] = []

    def status_snapshot(self) -> dict[str, Any]:
        self._refresh_process_state()
        is_active = bool(self._session and self._session.status in {"STARTING", "RUNNING", "STOP_REQUESTED"})
        latest_session = self._session.as_dict() if self._session else None
        active_session = latest_session if is_active else None
        return {
            "supervisor_version": SUPERVISOR_VERSION,
            "state": "RUNNING" if is_active else "IDLE",
            "active_session": active_session,
            "latest_session": latest_session,
            "active_session_id": self._session.session_id if is_active and self._session else None,
            "paper_start_allowed": not is_active,
            "paper_stop_allowed": is_active,
            "paper_start_refusal_reason": None if not is_active else "DUPLICATE_ACTIVE_RUN",
            "paper_stop_refusal_reason": None if is_active else "NO_ACTIVE_RUN",
            "allowed_profile": self.config.allowed_profile,
            "allowed_watchlist": list(self.config.allowed_watchlist),
            "allowed_durations": sorted(self.config.allowed_durations),
            "audit_event_count": len(self._audit_events),
            "last_audit_event": self._audit_events[-1].as_dict() if self._audit_events else None,
        }

    def start_paper(self, payload: dict[str, Any] | None) -> dict[str, Any]:
        request = payload or {}
        refusal = self._validate_start_request(request)
        if refusal:
            session = self._build_refused_session(request, refusal)
            event = self._record_event("paper_start", False, refusal, session.session_id, False)
            return self._intent_response(
                intent="paper_start",
                allowed=False,
                reason_code=refusal,
                audit_event=event,
                session=session,
                runtime_mutation_occurred=False,
            )

        assert self._session is None or self._session.status not in {"STARTING", "RUNNING", "STOP_REQUESTED"}
        available, unavailable_reason = self.runner.is_available(self.config.repo_root)
        if not available:
            session = self._build_refused_session(request, unavailable_reason or "PAPER_RUNNER_UNAVAILABLE")
            event = self._record_event("paper_start", False, session.refusal_reason or "PAPER_RUNNER_UNAVAILABLE", session.session_id, False)
            return self._intent_response(
                intent="paper_start",
                allowed=False,
                reason_code=session.refusal_reason or "PAPER_RUNNER_UNAVAILABLE",
                audit_event=event,
                session=session,
                runtime_mutation_occurred=False,
            )

        watchlist = self._normalize_watchlist(request.get("watchlist")) or self.config.allowed_watchlist
        duration = int(request.get("duration_seconds") or 300)
        session_id = self._new_session_id()
        spec = self._build_start_spec(session_id=session_id, duration_seconds=duration, watchlist=watchlist)
        session = PaperRunSession(
            session_id=session_id,
            requested_at=utc_now_iso(),
            status="STARTING",
            profile=self.config.allowed_profile,
            watchlist=watchlist,
            duration_seconds=duration,
            command_summary=spec.command_summary,
            stdout_path=spec.stdout_path,
            stderr_path=spec.stderr_path,
        )

        try:
            process = self.runner.start(spec)
        except Exception:
            session.status = "FAILED"
            session.refusal_reason = "PAPER_PROCESS_START_FAILED"
            event = self._record_event("paper_start", False, "PAPER_PROCESS_START_FAILED", session.session_id, False)
            self._session = session
            self._process = None
            return self._intent_response(
                intent="paper_start",
                allowed=False,
                reason_code="PAPER_PROCESS_START_FAILED",
                audit_event=event,
                session=session,
                runtime_mutation_occurred=False,
            )

        session.pid = int(process.pid)
        session.started_at = utc_now_iso()
        session.status = "RUNNING"
        self._session = session
        self._process = process
        event = self._record_event("paper_start", True, "PAPER_RUN_STARTED", session.session_id, True)
        return self._intent_response(
            intent="paper_start",
            allowed=True,
            reason_code="PAPER_RUN_STARTED",
            audit_event=event,
            session=session,
            runtime_mutation_occurred=True,
        )

    def stop_paper(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        del payload
        self._refresh_process_state()
        if self._session is None or self._process is None or self._session.status not in {"STARTING", "RUNNING", "STOP_REQUESTED"}:
            event = self._record_event("paper_stop", False, "NO_ACTIVE_RUN", self._session.session_id if self._session else None, False)
            return self._intent_response(
                intent="paper_stop",
                allowed=False,
                reason_code="NO_ACTIVE_RUN",
                audit_event=event,
                session=self._session,
                runtime_mutation_occurred=False,
            )

        ok, reason = self.runner.request_graceful_stop(self._process)
        if not ok:
            event = self._record_event("paper_stop", False, reason, self._session.session_id, False)
            return self._intent_response(
                intent="paper_stop",
                allowed=False,
                reason_code=reason,
                audit_event=event,
                session=self._session,
                runtime_mutation_occurred=False,
            )

        self._session.status = "STOP_REQUESTED"
        self._session.stop_requested_at = utc_now_iso()
        self._session.stop_reason = reason
        event = self._record_event("paper_stop", True, reason, self._session.session_id, True)
        return self._intent_response(
            intent="paper_stop",
            allowed=True,
            reason_code=reason,
            audit_event=event,
            session=self._session,
            runtime_mutation_occurred=True,
        )

    def live_refusal(self, intent_name: str) -> dict[str, Any]:
        event = self._record_event(intent_name, False, "LIVE_NOT_APPROVED", None, False)
        return self._intent_response(
            intent=intent_name,
            allowed=False,
            reason_code="LIVE_NOT_APPROVED",
            audit_event=event,
            session=self._session,
            runtime_mutation_occurred=False,
        )

    def generic_refusal(self, intent_name: str, reason_code: str) -> dict[str, Any]:
        event = self._record_event(intent_name, False, reason_code, self._session.session_id if self._session else None, False)
        return self._intent_response(
            intent=intent_name,
            allowed=False,
            reason_code=reason_code,
            audit_event=event,
            session=self._session,
            runtime_mutation_occurred=False,
        )

    def _validate_start_request(self, request: dict[str, Any]) -> str | None:
        self._refresh_process_state()
        if self._session and self._session.status in {"STARTING", "RUNNING", "STOP_REQUESTED"}:
            return "DUPLICATE_ACTIVE_RUN"

        mode = str(request.get("mode") or "PAPER").strip().upper()
        if mode in {"LIVE", "REAL", "REAL_MONEY"}:
            return "LIVE_NOT_APPROVED"
        if mode != "PAPER":
            return "PAPER_MODE_REQUIRED"
        if bool(request.get("real_money")):
            return "REAL_MONEY_NOT_APPROVED"
        if bool(request.get("live")):
            return "LIVE_NOT_APPROVED"
        if bool(request.get("approve_autonomous_paper")) is not True:
            return "AUTONOMOUS_PAPER_APPROVAL_REQUIRED"

        profile = str(request.get("profile") or self.config.allowed_profile).strip().upper()
        if profile != self.config.allowed_profile:
            return "UNSUPPORTED_PAPER_PROFILE"

        duration = request.get("duration_seconds", 300)
        try:
            duration_int = int(duration)
        except (TypeError, ValueError):
            return "INVALID_DURATION_SECONDS"
        if duration_int not in self.config.allowed_durations:
            return "UNSUPPORTED_DURATION_SECONDS"

        watchlist = self._normalize_watchlist(request.get("watchlist")) or self.config.allowed_watchlist
        if not watchlist:
            return "MISSING_WATCHLIST"
        allowed = set(self.config.allowed_watchlist)
        if any(symbol not in allowed for symbol in watchlist):
            return "UNSUPPORTED_WATCHLIST_SYMBOL"
        return None

    def _normalize_watchlist(self, raw: Any) -> tuple[str, ...]:
        if raw is None:
            return ()
        if isinstance(raw, str):
            parts = raw.split(",")
        elif isinstance(raw, (list, tuple)):
            parts = [str(item) for item in raw]
        else:
            return ()
        normalized = tuple(dict.fromkeys(str(part).strip().upper() for part in parts if str(part).strip()))
        return normalized

    def _build_start_spec(self, *, session_id: str, duration_seconds: int, watchlist: tuple[str, ...]) -> ProcessStartSpec:
        repo_root = self.config.repo_root
        log_dir = repo_root / self.config.log_directory
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        stdout_path = log_dir / f"operator_paper_{stamp}_{session_id}.out.log"
        stderr_path = log_dir / f"operator_paper_{stamp}_{session_id}.err.log"
        script_path = repo_root / self.config.script_path
        watchlist_arg = ",".join(watchlist)
        command = (
            self.config.powershell_executable,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            "-Run",
            "-ApproveAutonomousPaper",
            "-PaperExplorationAlpha",
            "-DurationSeconds",
            str(duration_seconds),
            "-Watchlist",
            watchlist_arg,
        )
        command_summary = (
            "powershell -NoProfile -ExecutionPolicy Bypass "
            "scripts/run_bounded_paper.ps1 -Run -ApproveAutonomousPaper "
            f"-PaperExplorationAlpha -DurationSeconds {duration_seconds} -Watchlist {watchlist_arg}"
        )
        return ProcessStartSpec(
            command=command,
            cwd=str(repo_root),
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            command_summary=command_summary,
        )

    def _build_refused_session(self, request: dict[str, Any], reason: str) -> PaperRunSession:
        watchlist = self._normalize_watchlist(request.get("watchlist")) or self.config.allowed_watchlist
        try:
            duration = int(request.get("duration_seconds") or 300)
        except (TypeError, ValueError):
            duration = 0
        return PaperRunSession(
            session_id=self._new_session_id(),
            requested_at=utc_now_iso(),
            status="REFUSED",
            profile=str(request.get("profile") or self.config.allowed_profile).strip().upper(),
            watchlist=watchlist,
            duration_seconds=duration,
            refusal_reason=reason,
        )

    def _refresh_process_state(self) -> None:
        if self._session is None or self._process is None:
            return
        self._session.last_status_check_at = utc_now_iso()
        exit_code = self._process.poll()
        if exit_code is None:
            if self._session.status not in {"STOP_REQUESTED", "STARTING"}:
                self._session.status = "RUNNING"
            return
        self._session.exit_code = int(exit_code)
        if self._session.ended_at is None:
            self._session.ended_at = utc_now_iso()
        if self._session.status == "STOP_REQUESTED":
            self._session.status = "STOPPED" if exit_code == 0 else "FAILED"
        elif self._session.status in {"STARTING", "RUNNING"}:
            self._session.status = "EXITED" if exit_code == 0 else "FAILED"

    def _record_event(
        self,
        intent: str,
        allowed: bool,
        reason_code: str,
        session_id: str | None,
        runtime_mutation_occurred: bool,
    ) -> AuditEvent:
        event = AuditEvent(
            audit_event_id=f"audit_{uuid.uuid4().hex[:16]}",
            timestamp=utc_now_iso(),
            intent=intent,
            allowed=allowed,
            reason_code=reason_code,
            session_id=session_id,
            runtime_mutation_occurred=runtime_mutation_occurred,
        )
        self._audit_events.append(event)
        return event

    def _intent_response(
        self,
        *,
        intent: str,
        allowed: bool,
        reason_code: str,
        audit_event: AuditEvent,
        session: PaperRunSession | None,
        runtime_mutation_occurred: bool,
    ) -> dict[str, Any]:
        return {
            "intent": intent,
            "intent_id": f"intent_{uuid.uuid4().hex[:16]}",
            "allowed": allowed,
            "status": "ALLOWED" if allowed else "REFUSED",
            "reason_code": reason_code,
            "audit_event_id": audit_event.audit_event_id,
            "audit_event_written": True,
            "session_id": session.session_id if session else None,
            "session": session.as_dict() if session else None,
            "mutation_occurred": runtime_mutation_occurred,
            "runtime_mutation_occurred": runtime_mutation_occurred,
            "broker_call_occurred": False,
            "live_endpoint_touched": False,
            "real_money_touched": False,
        }

    def _new_session_id(self) -> str:
        return f"paper_{uuid.uuid4().hex[:16]}"
