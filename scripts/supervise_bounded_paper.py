#!/usr/bin/env python
"""External liveness supervisor for bounded Alpaca PAPER runs.

The supervisor is visibility-only. It starts the existing governed bounded
PAPER launcher, records child/log/heartbeat state, and never restarts a run.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Sequence

from app.run_visibility import (
    DEFAULT_HEARTBEAT_PATH,
    DEFAULT_STATUS_STALE_AFTER_SECONDS,
    DEFAULT_SUPERVISOR_STATUS_PATH,
    atomic_write_json,
    build_supervisor_status_payload,
    utc_now_iso,
)


CHILD_LOG_RE = re.compile(r"(?im)^\s*(stdout|stderr)\s*:\s*(?P<path>.+?\.(?:out|err)\.log)\s*$")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _relative_or_absolute(repo_root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else repo_root / path


def _parse_child_log_paths(wrapper_stdout_path: Path) -> tuple[str | None, str | None]:
    try:
        text = wrapper_stdout_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, None
    stdout_path: str | None = None
    stderr_path: str | None = None
    for match in CHILD_LOG_RE.finditer(text):
        label = match.group(1).lower()
        path = match.group("path").strip().strip('"')
        if label == "stdout":
            stdout_path = path
        elif label == "stderr":
            stderr_path = path
    return stdout_path, stderr_path


def _write_status(
    *,
    process: subprocess.Popen,
    status_path: Path,
    started_at: str,
    started_monotonic: float,
    wrapper_stdout_path: Path,
    wrapper_stderr_path: Path,
    heartbeat_path: Path,
    stale_after_seconds: float,
    state: str | None = None,
) -> dict:
    child_stdout_path, child_stderr_path = _parse_child_log_paths(wrapper_stdout_path)
    exit_code = process.poll()
    child_running = exit_code is None
    resolved_state = state or ("RUNNING" if child_running else "EXITED")
    payload = build_supervisor_status_payload(
        state=resolved_state,
        pid=int(process.pid),
        started_at=started_at,
        uptime_seconds=time.monotonic() - started_monotonic,
        child_running=child_running,
        exit_code=exit_code,
        stdout_path=child_stdout_path or str(wrapper_stdout_path),
        stderr_path=child_stderr_path or str(wrapper_stderr_path),
        wrapper_stdout_path=str(wrapper_stdout_path),
        wrapper_stderr_path=str(wrapper_stderr_path),
        stale_after_seconds=stale_after_seconds,
        heartbeat_path=str(heartbeat_path),
        extra={
            "launch_vector": "native_windows_powershell_when_run_from_windows_python",
            "auto_restart_reason": "DISABLED_BY_P3F_GOVERNANCE",
        },
    )
    atomic_write_json(status_path, payload)
    return payload


def build_launch_command(args: argparse.Namespace, repo_root: Path) -> tuple[str, ...]:
    script_path = _relative_or_absolute(repo_root, args.launcher_script)
    command: list[str] = [
        args.powershell_executable,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script_path),
        "-Run",
        "-ApproveAutonomousPaper",
        "-DurationSeconds",
        str(args.duration_seconds),
        "-Watchlist",
        args.watchlist,
        "-PythonPath",
        args.python_path,
        "-LogDirectory",
        args.child_log_directory,
    ]
    if args.paper_exploration_alpha:
        command.append("-PaperExplorationAlpha")
    if args.tca_extended_reads:
        command.append("-TcaExtendedReads")
    if args.credential_file:
        command.extend(["-CredentialFile", args.credential_file])
    return tuple(command)


def supervise(command: Sequence[str], args: argparse.Namespace, repo_root: Path) -> int:
    status_path = _relative_or_absolute(repo_root, args.status_path)
    heartbeat_path = _relative_or_absolute(repo_root, args.heartbeat_path)
    wrapper_dir = _relative_or_absolute(repo_root, args.wrapper_log_directory)
    wrapper_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    wrapper_stdout_path = wrapper_dir / f"paper_supervisor_wrapper_{stamp}.out.log"
    wrapper_stderr_path = wrapper_dir / f"paper_supervisor_wrapper_{stamp}.err.log"
    env = os.environ.copy()
    env["POVERTY_KILLER_HEARTBEAT_PATH"] = str(heartbeat_path)
    env["POVERTY_KILLER_SUPERVISOR_STATUS_PATH"] = str(status_path)
    started_at = utc_now_iso()
    started_monotonic = time.monotonic()
    with wrapper_stdout_path.open("a", encoding="utf-8") as stdout_file, wrapper_stderr_path.open("a", encoding="utf-8") as stderr_file:
        process = subprocess.Popen(
            list(command),
            cwd=str(repo_root),
            stdin=subprocess.DEVNULL,
            stdout=stdout_file,
            stderr=stderr_file,
            env=env,
        )
        _write_status(
            process=process,
            status_path=status_path,
            started_at=started_at,
            started_monotonic=started_monotonic,
            wrapper_stdout_path=wrapper_stdout_path,
            wrapper_stderr_path=wrapper_stderr_path,
            heartbeat_path=heartbeat_path,
            stale_after_seconds=float(args.stale_after_seconds),
            state="RUNNING",
        )
        while process.poll() is None:
            time.sleep(float(args.poll_interval_seconds))
            payload = _write_status(
                process=process,
                status_path=status_path,
                started_at=started_at,
                started_monotonic=started_monotonic,
                wrapper_stdout_path=wrapper_stdout_path,
                wrapper_stderr_path=wrapper_stderr_path,
                heartbeat_path=heartbeat_path,
                stale_after_seconds=float(args.stale_after_seconds),
            )
            if payload.get("log_progress_stale") or payload.get("heartbeat_stale"):
                payload["state"] = "STALE"
                atomic_write_json(status_path, payload)
        final_payload = _write_status(
            process=process,
            status_path=status_path,
            started_at=started_at,
            started_monotonic=started_monotonic,
            wrapper_stdout_path=wrapper_stdout_path,
            wrapper_stderr_path=wrapper_stderr_path,
            heartbeat_path=heartbeat_path,
            stale_after_seconds=float(args.stale_after_seconds),
            state="EXITED" if int(process.returncode or 0) == 0 else "FAILED",
        )
        final_payload["manual_restart_required"] = True
        atomic_write_json(status_path, final_payload)
        return int(process.returncode or 0)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Supervise a governed bounded Alpaca PAPER run without auto-restart.")
    parser.add_argument("--duration-seconds", type=int, required=True)
    parser.add_argument("--watchlist", default="BTC/USD,ETH/USD,SOL/USD,LTC/USD,AVAX/USD,LINK/USD")
    parser.add_argument("--paper-exploration-alpha", action="store_true", default=True)
    parser.add_argument("--tca-extended-reads", action="store_true")
    parser.add_argument("--credential-file", default="")
    parser.add_argument("--powershell-executable", default="powershell.exe")
    parser.add_argument("--python-path", default="venv\\Scripts\\python.exe")
    parser.add_argument("--launcher-script", default="scripts/run_bounded_paper.ps1")
    parser.add_argument("--child-log-directory", default="logs\\paper_runs")
    parser.add_argument("--wrapper-log-directory", default="logs/paper_runs")
    parser.add_argument("--status-path", default=str(DEFAULT_SUPERVISOR_STATUS_PATH))
    parser.add_argument("--heartbeat-path", default=str(DEFAULT_HEARTBEAT_PATH))
    parser.add_argument("--poll-interval-seconds", type=float, default=2.0)
    parser.add_argument("--stale-after-seconds", type=float, default=DEFAULT_STATUS_STALE_AFTER_SECONDS)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.duration_seconds < 1 or args.duration_seconds > 432000:
        raise SystemExit("duration seconds must be between 1 and 432000")
    repo_root = _repo_root()
    command = build_launch_command(args, repo_root)
    return supervise(command, args, repo_root)


if __name__ == "__main__":
    raise SystemExit(main())
