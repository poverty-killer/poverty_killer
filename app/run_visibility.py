"""Read-only PAPER run heartbeat and supervisor visibility helpers.

This module writes and reads local runtime artifacts only. It does not import
broker adapters, execution routers, strategy modules, or credential stores.
"""

from __future__ import annotations

import html
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RUN_VISIBILITY_SCHEMA_VERSION = "paper-run-visibility-v1"
DEFAULT_RUNTIME_DIR = Path("logs") / "runtime"
DEFAULT_HEARTBEAT_PATH = DEFAULT_RUNTIME_DIR / "paper_heartbeat.json"
DEFAULT_SUPERVISOR_STATUS_PATH = DEFAULT_RUNTIME_DIR / "paper_supervisor_status.json"
DEFAULT_STATUS_STALE_AFTER_SECONDS = 15.0
LOG_TIMESTAMP_RE = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d{3,6})?(?:Z|[+-]\d{2}:?\d{2})?)"
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _coerce_path(repo_root: Path, value: str | Path | None, default: Path) -> Path:
    path = Path(value) if value is not None and str(value).strip() else default
    return path if path.is_absolute() else repo_root / path


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(path)


def read_json_file(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _parse_timestamp_seconds(value: Any) -> float | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    if " " in text and "T" not in text:
        text = text.replace(" ", "T", 1)
    if "," in text:
        text = text.replace(",", ".", 1)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _age_seconds(value: Any, now_seconds: float | None = None) -> float | None:
    parsed = _parse_timestamp_seconds(value)
    if parsed is None:
        return None
    now = time.time() if now_seconds is None else now_seconds
    return max(0.0, round(now - parsed, 3))


def _tail_text(path: Path, max_bytes: int = 131_072) -> str:
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > max_bytes:
                handle.seek(size - max_bytes)
            data = handle.read()
    except OSError:
        return ""
    return data.decode("utf-8", errors="replace")


def latest_log_timestamp(path: str | Path | None) -> str | None:
    if path is None or not str(path).strip():
        return None
    text = _tail_text(Path(path))
    matches = list(LOG_TIMESTAMP_RE.finditer(text))
    if not matches:
        return None
    return matches[-1].group("ts")


def _safe_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _safe_sequence(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _safe_count(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def build_runtime_heartbeat_payload(
    status: dict[str, Any],
    *,
    pid: int,
    started_at: str,
    started_monotonic: float,
    run_state: str,
    last_loop_ts: str | None,
    last_error: str | None,
) -> dict[str, Any]:
    execution = _safe_mapping(status.get("execution"))
    risk = _safe_mapping(status.get("risk"))
    main_loop = _safe_mapping(status.get("main_loop"))
    order_router = _safe_mapping(status.get("order_router"))
    runtime_position_count = _safe_count(main_loop.get("broker_position_cache_count"))
    active_symbols = _safe_sequence(status.get("active_symbols"))
    now_ts = utc_now_iso()
    return {
        "source": "POVERTY_KILLER_RUNTIME_HEARTBEAT",
        "schema_version": RUN_VISIBILITY_SCHEMA_VERSION,
        "heartbeat_ts": now_ts,
        "run_state": str(run_state or ("RUNNING" if status.get("running") else "STOPPED")).upper(),
        "pid": int(pid),
        "started_at": started_at,
        "uptime_seconds": round(max(0.0, time.monotonic() - float(started_monotonic)), 3),
        "last_loop_ts": last_loop_ts,
        "last_signal": execution.get("last_signal"),
        "last_post": execution.get("last_order_submit_attempt"),
        "last_fill": execution.get("last_fill"),
        "open_orders": {
            "count": _safe_count(execution.get("pending_orders_count")),
            "source": "execution_engine_pending_orders",
            "broker_confirmed": False,
        },
        "positions": {
            "count": runtime_position_count,
            "source": main_loop.get("broker_position_cache_source") or "main_loop_runtime_cache",
            "broker_confirmed": False,
            "note": "Heartbeat does not perform broker reads; portfolio endpoint remains broker-truth authority.",
        },
        "latency_degraded_count": _safe_count(execution.get("latency_degraded_count")),
        "last_latency_truth": execution.get("last_latency_truth"),
        "last_error": last_error,
        "watchlist": [str(symbol) for symbol in active_symbols],
        "runtime": {
            "running": bool(status.get("running")),
            "execution_running": bool(execution.get("is_running")),
            "safe_mode": bool(execution.get("is_in_safe_mode")),
            "risk_can_trade": bool(risk.get("can_trade")),
            "pending_orders_count": _safe_count(execution.get("pending_orders_count")),
            "filled_orders_count": _safe_count(execution.get("filled_orders_count")),
            "main_loop_iteration_count": _safe_count(main_loop.get("iteration_count")),
            "book_processed_count": _safe_mapping(main_loop.get("book_processed_count")),
            "order_router_pending_orders_count": _safe_count(order_router.get("pending_orders_count")),
            "broker_mutation_counts": _safe_mapping(execution.get("broker_mutation_counts")),
        },
        "secrets_values_exposed": False,
        "read_only": True,
        "broker_call_occurred": False,
        "broker_mutation_occurred": False,
        "live_enabled": False,
        "real_money_enabled": False,
    }


class RunHeartbeatWriter:
    def __init__(self, path: str | Path | None = None, *, repo_root: str | Path | None = None) -> None:
        root = Path(repo_root) if repo_root is not None else Path.cwd()
        self.path = _coerce_path(root, path, DEFAULT_HEARTBEAT_PATH)

    def write(self, payload: dict[str, Any]) -> None:
        atomic_write_json(self.path, payload)


def build_supervisor_status_payload(
    *,
    state: str,
    pid: int | None,
    started_at: str,
    uptime_seconds: float,
    child_running: bool,
    exit_code: int | None,
    stdout_path: str | None,
    stderr_path: str | None,
    wrapper_stdout_path: str | None = None,
    wrapper_stderr_path: str | None = None,
    stale_after_seconds: float = DEFAULT_STATUS_STALE_AFTER_SECONDS,
    heartbeat_path: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stdout = Path(stdout_path) if stdout_path else None
    stdout_mtime = stdout.stat().st_mtime if stdout and stdout.exists() else None
    stdout_size = stdout.stat().st_size if stdout and stdout.exists() else None
    latest_ts = latest_log_timestamp(stdout) if stdout else None
    now = time.time()
    log_age = round(now - stdout_mtime, 3) if stdout_mtime is not None else None
    log_progress_stale = bool(child_running and (log_age is None or log_age > stale_after_seconds))
    heartbeat = read_json_file(Path(heartbeat_path)) if heartbeat_path else None
    heartbeat_age = _age_seconds(heartbeat.get("heartbeat_ts"), now) if heartbeat else None
    heartbeat_stale = bool(child_running and (heartbeat_age is None or heartbeat_age > stale_after_seconds))
    payload = {
        "source": "POVERTY_KILLER_EXTERNAL_SUPERVISOR",
        "schema_version": RUN_VISIBILITY_SCHEMA_VERSION,
        "supervisor_ts": utc_now_iso(),
        "state": str(state or "UNKNOWN").upper(),
        "pid": pid,
        "started_at": started_at,
        "uptime_seconds": round(max(0.0, float(uptime_seconds)), 3),
        "child_running": bool(child_running),
        "exit_code": exit_code,
        "stdout_path": stdout_path,
        "stderr_path": stderr_path,
        "wrapper_stdout_path": wrapper_stdout_path,
        "wrapper_stderr_path": wrapper_stderr_path,
        "latest_log_timestamp": latest_ts,
        "stdout_size": stdout_size,
        "stdout_mtime": datetime.fromtimestamp(stdout_mtime, timezone.utc).isoformat().replace("+00:00", "Z")
        if stdout_mtime is not None
        else None,
        "log_age_seconds": log_age,
        "stale_after_seconds": float(stale_after_seconds),
        "log_progress_stale": log_progress_stale,
        "heartbeat_path": heartbeat_path,
        "heartbeat_age_seconds": heartbeat_age,
        "heartbeat_stale": heartbeat_stale,
        "auto_restart_enabled": False,
        "manual_restart_required": not bool(child_running),
        "read_only": True,
        "broker_mutation_occurred": False,
        "live_enabled": False,
        "real_money_enabled": False,
        "secrets_values_exposed": False,
    }
    if extra:
        payload.update(extra)
    return payload


def read_run_visibility_snapshot(
    repo_root: str | Path,
    *,
    heartbeat_path: str | Path | None = None,
    supervisor_status_path: str | Path | None = None,
    stale_after_seconds: float = DEFAULT_STATUS_STALE_AFTER_SECONDS,
) -> dict[str, Any]:
    root = Path(repo_root)
    heartbeat_file = _coerce_path(root, heartbeat_path, DEFAULT_HEARTBEAT_PATH)
    supervisor_file = _coerce_path(root, supervisor_status_path, DEFAULT_SUPERVISOR_STATUS_PATH)
    heartbeat = read_json_file(heartbeat_file)
    supervisor = read_json_file(supervisor_file)
    now = time.time()
    heartbeat_age = _age_seconds(heartbeat.get("heartbeat_ts"), now) if heartbeat else None
    supervisor_age = _age_seconds(supervisor.get("supervisor_ts"), now) if supervisor else None
    child_running = bool(supervisor and supervisor.get("child_running") is True)
    external_state = str((supervisor or {}).get("state") or "").upper()
    heartbeat_stale = bool(child_running and (heartbeat_age is None or heartbeat_age > stale_after_seconds))
    supervisor_stale = bool(child_running and (supervisor_age is None or supervisor_age > stale_after_seconds))
    log_stale = bool((supervisor or {}).get("log_progress_stale"))
    if child_running and not heartbeat_stale and not supervisor_stale and not log_stale:
        status = "RUNNING"
    elif child_running:
        status = "STALE"
    elif external_state in {"EXITED", "FAILED", "STOPPED", "STALE", "NO_PROGRESS"}:
        status = "STOPPED" if external_state in {"EXITED", "STOPPED"} else external_state
    elif heartbeat and heartbeat_age is not None and heartbeat_age <= stale_after_seconds:
        status = str(heartbeat.get("run_state") or "RUNNING").upper()
    else:
        status = "NO_STATUS"

    heartbeat_open_orders = _safe_mapping((heartbeat or {}).get("open_orders"))
    heartbeat_positions = _safe_mapping((heartbeat or {}).get("positions"))
    return {
        "source": "POVERTY_KILLER_RUN_VISIBILITY",
        "schema_version": RUN_VISIBILITY_SCHEMA_VERSION,
        "status": status,
        "prominent_state": status,
        "status_ts": utc_now_iso(),
        "read_only": True,
        "controls_available": False,
        "manual_trading_available": False,
        "force_trade_available": False,
        "auto_restart_enabled": False,
        "heartbeat_path": str(heartbeat_file),
        "supervisor_status_path": str(supervisor_file),
        "heartbeat_present": heartbeat is not None,
        "supervisor_present": supervisor is not None,
        "heartbeat_age_seconds": heartbeat_age,
        "supervisor_age_seconds": supervisor_age,
        "heartbeat_stale": heartbeat_stale,
        "supervisor_stale": supervisor_stale,
        "log_progress_stale": log_stale,
        "pid": (supervisor or {}).get("pid") or (heartbeat or {}).get("pid"),
        "uptime_seconds": (heartbeat or {}).get("uptime_seconds") or (supervisor or {}).get("uptime_seconds"),
        "last_fill": (heartbeat or {}).get("last_fill"),
        "last_signal": (heartbeat or {}).get("last_signal"),
        "last_post": (heartbeat or {}).get("last_post"),
        "open_orders": heartbeat_open_orders,
        "positions": heartbeat_positions,
        "latency_degraded_count": _safe_count((heartbeat or {}).get("latency_degraded_count")),
        "last_error": (heartbeat or {}).get("last_error") or (supervisor or {}).get("last_error"),
        "watchlist": _safe_sequence((heartbeat or {}).get("watchlist")),
        "heartbeat": heartbeat,
        "supervisor": supervisor,
        "broker_call_occurred": False,
        "broker_mutation_occurred": False,
        "order_submission_occurred": False,
        "cancel_occurred": False,
        "liquidation_occurred": False,
        "live_enabled": False,
        "real_money_enabled": False,
        "secrets_values_exposed": False,
    }


def render_run_visibility_html(snapshot: dict[str, Any]) -> str:
    status = html.escape(str(snapshot.get("status") or "NO_STATUS"))
    payload = html.escape(json.dumps(snapshot, indent=2, sort_keys=True, default=str))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PAPER Run Visibility</title>
  <style>
    :root {{ color-scheme: light dark; font-family: Inter, Segoe UI, Arial, sans-serif; }}
    body {{ margin: 0; background: #0f1318; color: #eef3f8; }}
    main {{ max-width: 1120px; margin: 0 auto; padding: 24px; }}
    .banner {{ border-left: 8px solid #8aa4ff; background: #171d25; padding: 18px 20px; }}
    .banner.RUNNING {{ border-color: #27c46b; }}
    .banner.STALE, .banner.NO_PROGRESS {{ border-color: #ffb020; }}
    .banner.STOPPED, .banner.FAILED, .banner.NO_STATUS {{ border-color: #ff5f57; }}
    h1 {{ margin: 0; font-size: 28px; letter-spacing: 0; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px; margin-top: 16px; }}
    .metric {{ background: #171d25; border: 1px solid #273241; padding: 14px; border-radius: 6px; min-height: 78px; }}
    .label {{ color: #9aa8b7; font-size: 12px; text-transform: uppercase; letter-spacing: .06em; }}
    .value {{ margin-top: 8px; font-size: 20px; overflow-wrap: anywhere; }}
    pre {{ background: #090d12; border: 1px solid #273241; padding: 16px; overflow: auto; border-radius: 6px; }}
    @media (max-width: 560px) {{ main {{ padding: 14px; }} h1 {{ font-size: 22px; }} }}
  </style>
</head>
<body>
  <main>
    <section id="banner" class="banner {status}">
      <div class="label">PAPER Run State</div>
      <h1 id="state">{status}</h1>
    </section>
    <section class="grid" aria-live="polite">
      <div class="metric"><div class="label">PID</div><div class="value" id="pid">{html.escape(str(snapshot.get("pid")))} </div></div>
      <div class="metric"><div class="label">Uptime</div><div class="value" id="uptime">{html.escape(str(snapshot.get("uptime_seconds")))}s</div></div>
      <div class="metric"><div class="label">Open Orders</div><div class="value" id="openOrders">{html.escape(str(_safe_mapping(snapshot.get("open_orders")).get("count")))}</div></div>
      <div class="metric"><div class="label">Positions</div><div class="value" id="positions">{html.escape(str(_safe_mapping(snapshot.get("positions")).get("count")))}</div></div>
      <div class="metric"><div class="label">Latency Degraded</div><div class="value" id="latency">{html.escape(str(snapshot.get("latency_degraded_count")))}</div></div>
      <div class="metric"><div class="label">Last Error</div><div class="value" id="lastError">{html.escape(str(snapshot.get("last_error") or "none"))}</div></div>
    </section>
    <pre id="payload">{payload}</pre>
  </main>
  <script>
    async function refresh() {{
      const response = await fetch('/operator/run-visibility/status', {{ cache: 'no-store' }});
      const data = await response.json();
      const state = String(data.status || 'NO_STATUS');
      document.getElementById('state').textContent = state;
      const banner = document.getElementById('banner');
      banner.className = 'banner ' + state;
      document.getElementById('pid').textContent = data.pid ?? 'none';
      document.getElementById('uptime').textContent = (data.uptime_seconds ?? 'none') + 's';
      document.getElementById('openOrders').textContent = (data.open_orders || {{}}).count ?? 0;
      document.getElementById('positions').textContent = (data.positions || {{}}).count ?? 0;
      document.getElementById('latency').textContent = data.latency_degraded_count ?? 0;
      document.getElementById('lastError').textContent = data.last_error || 'none';
      document.getElementById('payload').textContent = JSON.stringify(data, null, 2);
    }}
    setInterval(refresh, 2000);
    refresh();
  </script>
</body>
</html>"""
