"""Run archive and flight-recorder summaries for operator-visible PAPER runs.

The archive reads session metadata and referenced log files as evidence. It
never writes logs, never calls brokers, and never invents missing truth.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


RUN_ARCHIVE_VERSION = "operator-run-archive-v2"
MAX_LOG_BYTES = 1_000_000

PASS = "PASS"
CONDITIONAL_PASS = "CONDITIONAL_PASS"
FAIL = "FAIL"
UNKNOWN = "UNKNOWN"

_ORDER_SUBMITTED = ("ORDER_SUBMITTED", "SUBMITTED_TO_EXECUTION", "BROKER_POST", "POST acknowledged")
_ORDER_ACK = ("ORDER_ACKNOWLEDGED", "ACKNOWLEDGED", "accepted", "filled")
_ORDER_CANCEL = ("CANCEL_ACKNOWLEDGED", "CANCELED", "CANCELLED", "DELETE acknowledged")
_FILL = ("FILL_LEDGER_HYDRATION", "fill_hydration_count", "broker_fill_ledger")
_FEE = ("BROKER_FEE_HYDRATION", "broker_fee_hydration", "FEE_ACTIVITY_MATCHED", "BROKER_CFEE")
_TCA = ("TCA", "tca_records_count", "realized_vs_modeled_netedge")
_OMS = ("SHUTDOWN_RECONCILIATION", "OMS shutdown", "shutdown reconciliation")
_RECONCILIATION_CONFLICT_MARKERS = (
    "RECONCILIATION_CONFLICT",
    "OMS_RECONCILIATION_CONFLICT",
    "OPEN_ORDER_CONFLICT",
    "PENDING_TERMINAL_ORDER",
    "ZOMBIE_ORDER",
)
_RECONCILIATION_CONFLICT_FIELDS = (
    "reconciliation_conflict_count",
    "reconciliation_conflicts",
    "oms_reconciliation_conflict_count",
    "oms_conflict_count",
    "open_order_conflict_count",
    "pending_terminal_order_count",
    "pending_terminal_count",
    "zombie_order_count",
    "zombie_orders",
    "local_open_without_broker_match_count",
)
_RECONCILIATION_CONFLICT_TRUE_FIELDS = (
    "reconciliation_conflict",
    "oms_reconciliation_conflict",
    "oms_conflict",
    "open_order_conflict",
    "pending_terminal_order",
    "zombie_order_detected",
)
_BROKER_FEE_CONFLICT_MARKERS = ("BROKER_FEE_HYDRATION_CONFLICT", "FEE_ACTIVITY_CONFLICT")
_BROKER_FEE_CONFLICT_FIELDS = (
    "broker_fee_hydration_conflict_count",
    "broker_fee_activity_conflict_count",
    "fee_hydration_conflict_count",
)
_BROKER_FEE_CONFLICT_TRUE_FIELDS = (
    "broker_fee_hydration_conflict",
    "broker_fee_activity_conflict",
    "fee_hydration_conflict",
)
_LIVE_TRUE_MARKERS = (
    "LIVE_ENDPOINT_USED_TRUE",
    "LIVE_ENDPOINT_TOUCHED_TRUE",
    "LIVE_ENDPOINT_MUTATION_TRUE",
    "LIVE_MONEY_USED_TRUE",
)
_LIVE_TRUE_FIELDS = (
    "live_endpoint_used",
    "live_endpoint_touched",
    "live_endpoint_mutation",
    "live_money_used",
    "live_money_touched",
)
_REAL_MONEY_TRUE_MARKERS = ("REAL_MONEY_USED_TRUE", "REAL_MONEY_TOUCHED_TRUE")
_REAL_MONEY_TRUE_FIELDS = ("real_money_used", "real_money_touched", "real_money_enabled")
_UNAUTHORIZED = ("UNAUTHORIZED_MUTATION", "unauthorized mutation", "guardrail bypass")
_NAKED_SELL = ("NAKED_SELL", "naked SELL", "SELL_WITHOUT_POSITION_TRUTH")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _duration_seconds(start: Any, end: Any) -> int | None:
    start_dt = _parse_dt(start)
    end_dt = _parse_dt(end)
    if not start_dt or not end_dt:
        return None
    return max(int((end_dt - start_dt).total_seconds()), 0)


def _count_markers(text: str, markers: tuple[str, ...]) -> int:
    upper = text.upper()
    count = 0
    for marker in markers:
        count += upper.count(marker.upper())
    return count


def _has_marker(text: str, markers: tuple[str, ...]) -> bool:
    upper = text.upper()
    return any(marker.upper() in upper for marker in markers)


def _has_exact_marker(text: str, markers: tuple[str, ...]) -> bool:
    upper = text.upper()
    return any(
        re.search(rf"(?<![A-Z0-9_]){re.escape(marker.upper())}(?![A-Z0-9_])", upper)
        for marker in markers
    )


def _field_true(text: str, fields: tuple[str, ...]) -> bool:
    for field_name in fields:
        pattern = rf"(?<![A-Za-z0-9_])['\"]?{re.escape(field_name)}['\"]?\s*[:=]\s*(?:true|1|yes)\b"
        if re.search(pattern, text, flags=re.IGNORECASE):
            return True
    return False


def _field_positive_count(text: str, fields: tuple[str, ...]) -> bool:
    for field_name in fields:
        pattern = rf"(?<![A-Za-z0-9_])['\"]?{re.escape(field_name)}['\"]?\s*[:=]\s*([0-9]+)\b"
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            try:
                if int(match.group(1)) > 0:
                    return True
            except ValueError:
                continue
    return False


def _safe_read_tail(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            try:
                size = path.stat().st_size
                if size > MAX_LOG_BYTES:
                    handle.seek(size - MAX_LOG_BYTES)
            except OSError:
                pass
            return handle.read(MAX_LOG_BYTES).decode("utf-8", errors="replace")
    except OSError:
        return ""


def _resolve_log_path(repo_root: Path, raw: Any) -> Path | None:
    if not raw:
        return None
    text = str(raw).strip().strip('"')
    if not text:
        return None
    candidates = [Path(text)]
    drive_match = re.match(r"^([A-Za-z]):[\\/](.*)$", text)
    if drive_match:
        drive = drive_match.group(1).lower()
        rest = drive_match.group(2).replace("\\", "/")
        candidates.append(Path("/mnt") / drive / rest)
    if "\\" in text:
        candidates.append(Path(text.replace("\\", "/")))
    for candidate in list(candidates):
        if not candidate.is_absolute():
            candidates.append(repo_root / candidate)
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return candidates[-1] if candidates else None


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "on"}


def _extract_diag_fields(text: str, event_name: str) -> dict[str, Any] | None:
    marker = f"[OMS_DIAG] {event_name} fields="
    latest: dict[str, Any] | None = None
    for line in text.splitlines():
        if marker not in line:
            continue
        payload = line.split(marker, 1)[1].strip()
        try:
            parsed = ast.literal_eval(payload)
        except (SyntaxError, ValueError):
            continue
        if isinstance(parsed, dict):
            latest = parsed
    return latest


def _extract_dispatch_fields(text: str, reason_code: str) -> list[dict[str, Any]]:
    marker = f"[DISPATCH_DIAG] reason_code={reason_code} fields="
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        if marker not in line:
            continue
        payload = line.split(marker, 1)[1].strip()
        try:
            parsed = ast.literal_eval(payload)
        except (SyntaxError, ValueError):
            continue
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows


def _extract_first_json_object(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            parsed, _ = decoder.raw_decode(text[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _first_field(*sources: dict[str, Any] | None, names: str | tuple[str, ...], default: Any = None) -> Any:
    wanted = (names,) if isinstance(names, str) else names
    for source in sources:
        if not isinstance(source, dict):
            continue
        for name in wanted:
            if name in source and source.get(name) is not None:
                return source.get(name)
    return default


def _as_counts(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {"GET": 0, "POST": 0, "DELETE": 0}
    return {
        "GET": _as_int(value.get("GET", value.get("get", 0))),
        "POST": _as_int(value.get("POST", value.get("post", 0))),
        "DELETE": _as_int(value.get("DELETE", value.get("delete", 0))),
    }


def _extract_market_latency_summary(text: str) -> dict[str, Any]:
    latencies = [float(match.group(1)) for match in re.finditer(r"latency_ms=([0-9]+(?:\.[0-9]+)?)", text)]
    threshold_match = None
    for threshold_match in re.finditer(r"threshold=([0-9]+(?:\.[0-9]+)?)ms", text):
        pass
    return {
        "status": "WARNINGS_PRESENT" if "MARKET_DATA_LATENCY_DEGRADED" in text else "NONE_OBSERVED",
        "warning_count_in_scanned_excerpt": text.count("MARKET_DATA_LATENCY_DEGRADED"),
        "max_latency_ms": max(latencies) if latencies else None,
        "latest_latency_ms": latencies[-1] if latencies else None,
        "threshold_ms": float(threshold_match.group(1)) if threshold_match else None,
        "source": "SCANNED_LOG_EXCERPT",
    }


def _decision_symbol_summary(text: str, watchlist: Iterable[Any]) -> dict[str, Any]:
    symbols: dict[str, dict[str, Any]] = {}
    for symbol in watchlist:
        text_symbol = str(symbol or "").strip()
        if text_symbol:
            symbols[text_symbol] = {
                "decision_attempts": 0,
                "submitted_count": 0,
                "submit_signal_called_count": 0,
                "outputs": {},
                "frame_statuses": {},
                "no_submit_reasons": {},
                "last_frame_id": None,
                "last_output": None,
                "last_status": None,
            }

    total = 0
    for row in _extract_dispatch_fields(text, "decision_compile_attempted"):
        frame = row.get("decision_frame") if isinstance(row.get("decision_frame"), dict) else {}
        symbol = str(row.get("symbol") or frame.get("symbol") or "UNKNOWN")
        bucket = symbols.setdefault(
            symbol,
            {
                "decision_attempts": 0,
                "submitted_count": 0,
                "submit_signal_called_count": 0,
                "outputs": {},
                "frame_statuses": {},
                "no_submit_reasons": {},
                "last_frame_id": None,
                "last_output": None,
                "last_status": None,
            },
        )
        total += 1
        bucket["decision_attempts"] += 1
        if _as_bool(row.get("submitted")):
            bucket["submitted_count"] += 1
        if _as_bool(row.get("submit_signal_called")):
            bucket["submit_signal_called_count"] += 1
        output = str(row.get("frame_output") or frame.get("frame_output") or "UNKNOWN")
        status = str(row.get("frame_status") or frame.get("frame_status") or "UNKNOWN")
        reason = str(row.get("no_submit_reason_code") or "NONE")
        bucket["outputs"][output] = int(bucket["outputs"].get(output, 0)) + 1
        bucket["frame_statuses"][status] = int(bucket["frame_statuses"].get(status, 0)) + 1
        if reason != "NONE":
            bucket["no_submit_reasons"][reason] = int(bucket["no_submit_reasons"].get(reason, 0)) + 1
        bucket["last_frame_id"] = row.get("frame_id") or frame.get("frame_id") or bucket["last_frame_id"]
        bucket["last_output"] = output
        bucket["last_status"] = status

    return {
        "status": "OBSERVED" if total else "NO_DECISION_COMPILE_ATTEMPTS_IN_SCANNED_EXCERPT",
        "total_decision_attempts_in_scanned_excerpt": total,
        "symbols": symbols,
        "source": "DISPATCH_DIAG_DECISION_COMPILE_ATTEMPTED",
    }


def _session_sort_key(session: dict[str, Any]) -> str:
    return str(session.get("requested_at") or session.get("started_at") or session.get("ended_at") or "")


@dataclass
class RunLogEvidence:
    log_paths: list[str] = field(default_factory=list)
    readable_log_paths: list[str] = field(default_factory=list)
    log_excerpt_bytes_scanned: int = 0
    orders_submitted: int = 0
    orders_acknowledged: int = 0
    orders_canceled: int = 0
    fills_observed: int = 0
    fill_hydration_observed: bool = False
    broker_fee_hydration_observed: bool = False
    broker_fee_hydration_conflict_observed: bool = False
    broker_fee_hydration_skipped: bool = False
    broker_fee_hydration_skip_reason: str | None = None
    account_activity_read_authorized: bool | None = None
    broker_read_profile: str | None = None
    tca_observed: bool = False
    oms_shutdown_accounting_observed: bool = False
    reconciliation_conflict_observed: bool = False
    fee_detail_pending_observed: bool = False
    runtime_order_activity: dict[str, Any] = field(default_factory=dict)
    historical_order_activity: dict[str, Any] = field(default_factory=dict)
    baseline_positions: dict[str, Any] = field(default_factory=dict)
    broker_method_counts: dict[str, int] = field(default_factory=dict)
    shutdown_controls: dict[str, Any] = field(default_factory=dict)
    shutdown_open_orders: dict[str, Any] = field(default_factory=dict)
    fee_tca_status: dict[str, Any] = field(default_factory=dict)
    market_data_latency: dict[str, Any] = field(default_factory=dict)
    per_symbol_decisions: dict[str, Any] = field(default_factory=dict)
    preflight: dict[str, Any] = field(default_factory=dict)
    safety_markers: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "log_paths": list(dict.fromkeys(self.log_paths)),
            "readable_log_paths": list(dict.fromkeys(self.readable_log_paths)),
            "log_excerpt_bytes_scanned": self.log_excerpt_bytes_scanned,
            "orders_submitted": self.orders_submitted,
            "orders_acknowledged": self.orders_acknowledged,
            "orders_canceled": self.orders_canceled,
            "fills_observed": self.fills_observed,
            "fill_hydration_observed": self.fill_hydration_observed,
            "broker_fee_hydration_observed": self.broker_fee_hydration_observed,
            "broker_fee_hydration_conflict_observed": self.broker_fee_hydration_conflict_observed,
            "broker_fee_hydration_skipped": self.broker_fee_hydration_skipped,
            "broker_fee_hydration_skip_reason": self.broker_fee_hydration_skip_reason,
            "account_activity_read_authorized": self.account_activity_read_authorized,
            "broker_read_profile": self.broker_read_profile,
            "tca_observed": self.tca_observed,
            "oms_shutdown_accounting_observed": self.oms_shutdown_accounting_observed,
            "reconciliation_conflict_observed": self.reconciliation_conflict_observed,
            "fee_detail_pending_observed": self.fee_detail_pending_observed,
            "runtime_order_activity": dict(self.runtime_order_activity),
            "historical_order_activity": dict(self.historical_order_activity),
            "baseline_positions": dict(self.baseline_positions),
            "broker_method_counts": dict(self.broker_method_counts),
            "shutdown_controls": dict(self.shutdown_controls),
            "shutdown_open_orders": dict(self.shutdown_open_orders),
            "fee_tca_status": dict(self.fee_tca_status),
            "market_data_latency": dict(self.market_data_latency),
            "per_symbol_decisions": dict(self.per_symbol_decisions),
            "preflight": dict(self.preflight),
            "safety_markers": dict(self.safety_markers),
        }


def scan_run_logs(session: dict[str, Any], *, repo_root: Path) -> RunLogEvidence:
    evidence = RunLogEvidence()
    raw_paths = [
        session.get("stdout_path"),
        session.get("stderr_path"),
        session.get("wrapper_stdout_path"),
        session.get("wrapper_stderr_path"),
        session.get("child_stdout_path"),
        session.get("child_stderr_path"),
    ]
    texts: list[str] = []
    for raw in raw_paths:
        path = _resolve_log_path(repo_root, raw)
        if path is None:
            continue
        path_text = str(path)
        evidence.log_paths.append(path_text)
        if not path.exists() or not path.is_file():
            continue
        text = _safe_read_tail(path)
        if not text:
            continue
        evidence.readable_log_paths.append(path_text)
        evidence.log_excerpt_bytes_scanned += len(text.encode("utf-8", errors="replace"))
        texts.append(text)

    joined = "\n".join(texts)
    shutdown = _extract_diag_fields(joined, "SHUTDOWN_ACCOUNTING")
    reconciliation = _extract_diag_fields(joined, "SHUTDOWN_RECONCILIATION")
    preflight = _extract_first_json_object(joined) or {}
    structured_available = bool(shutdown or reconciliation)
    structured = shutdown or reconciliation or {}

    if structured_available:
        method_counts = _as_counts(_first_field(shutdown, reconciliation, names="mutation_method_counts", default={}))
        preflight_method_counts = {
            "GET": _as_int(preflight.get("GET_count", 0)),
            "POST": _as_int(preflight.get("POST_count", 0)),
            "DELETE": _as_int(preflight.get("DELETE_count", 0)),
        }
        evidence.orders_submitted = _as_int(
            structured.get("order_post_acknowledged", structured.get("order_post_attempted", 0))
        )
        evidence.orders_acknowledged = _as_int(_first_field(shutdown, reconciliation, names="order_post_acknowledged", default=0))
        evidence.orders_canceled = _as_int(
            _first_field(shutdown, reconciliation, names="cancel_acknowledged", default=_first_field(shutdown, reconciliation, names="cancel_attempted", default=0))
        )
        evidence.fills_observed = _as_int(_first_field(shutdown, reconciliation, names="fill_hydration_count", default=0))
        evidence.fill_hydration_observed = (
            _as_int(_first_field(shutdown, reconciliation, names="fill_hydration_attempted_count", default=0)) > 0
            or _as_int(_first_field(shutdown, reconciliation, names="fill_hydration_count", default=0)) > 0
        )
        evidence.broker_fee_hydration_observed = (
            _as_int(_first_field(shutdown, reconciliation, names="broker_fee_hydration_attempted_count", default=0)) > 0
            or _as_int(_first_field(shutdown, reconciliation, names="broker_fee_hydration_count", default=0)) > 0
            or _as_int(_first_field(shutdown, reconciliation, names="broker_fee_activity_records_seen_count", default=0)) > 0
        )
        evidence.broker_fee_hydration_skipped = _as_bool(_first_field(shutdown, reconciliation, names="fee_hydration_skipped", default=False))
        skip_reason = _first_field(shutdown, reconciliation, names="fee_hydration_skip_reason")
        evidence.broker_fee_hydration_skip_reason = str(skip_reason) if skip_reason else None
        account_activity = _first_field(shutdown, reconciliation, names="account_activity_read_authorized")
        evidence.account_activity_read_authorized = _as_bool(account_activity) if account_activity is not None else None
        read_profile = _first_field(shutdown, reconciliation, names="broker_read_profile")
        evidence.broker_read_profile = str(read_profile) if read_profile else None
        evidence.tca_observed = (
            _as_int(_first_field(shutdown, reconciliation, names="tca_records_count", default=0)) > 0
            or _as_int(_first_field(shutdown, reconciliation, names="tca_complete_count", default=0)) > 0
        )
        evidence.oms_shutdown_accounting_observed = True
        evidence.fee_detail_pending_observed = _as_int(_first_field(shutdown, reconciliation, names="tca_fee_pending_count", default=0)) > 0
        evidence.runtime_order_activity = {
            "order_post_attempted": _as_int(_first_field(shutdown, reconciliation, names="order_post_attempted", default=0)),
            "order_post_authorized": _as_int(_first_field(shutdown, reconciliation, names="order_post_authorized", default=0)),
            "order_post_acknowledged": _as_int(_first_field(shutdown, reconciliation, names="order_post_acknowledged", default=0)),
            "submitted_count": _as_int(_first_field(shutdown, reconciliation, names="submitted_count", default=0)),
            "cancel_attempted": _as_int(_first_field(shutdown, reconciliation, names="cancel_attempted", default=0)),
            "cancel_authorized": _as_int(_first_field(shutdown, reconciliation, names="cancel_authorized", default=0)),
            "cancel_acknowledged": _as_int(_first_field(shutdown, reconciliation, names="cancel_acknowledged", default=0)),
            "fill_hydration_attempted_count": _as_int(_first_field(shutdown, reconciliation, names="fill_hydration_attempted_count", default=0)),
            "fill_hydration_count": _as_int(_first_field(shutdown, reconciliation, names="fill_hydration_count", default=0)),
            "source": "OMS_SHUTDOWN_ACCOUNTING",
        }
        evidence.historical_order_activity = {
            "terminal_orders": _as_int(_first_field(shutdown, reconciliation, names="terminal_orders", default=0)),
            "filled_orders": _as_int(_first_field(shutdown, reconciliation, names="filled_orders", default=0)),
            "canceled_orders": _as_int(_first_field(shutdown, reconciliation, names="canceled_orders", default=0)),
            "broker_filled_orders": _as_int(_first_field(shutdown, reconciliation, names="broker_filled_orders", default=0)),
            "broker_partially_filled_orders": _as_int(_first_field(shutdown, reconciliation, names="broker_partially_filled_orders", default=0)),
            "broker_canceled_with_fill_count": _as_int(_first_field(shutdown, reconciliation, names="broker_canceled_with_fill_count", default=0)),
            "local_fills": _as_int(_first_field(shutdown, reconciliation, names="local_fills", default=0)),
            "legacy_local_fills": _as_int(_first_field(shutdown, reconciliation, names="legacy_local_fills", default=0)),
            "local_order_id_mappings": _as_int(_first_field(shutdown, reconciliation, names="local_order_id_mappings", default=0)),
            "source": "BROKER_AND_LOCAL_HISTORY_AT_SHUTDOWN",
        }
        positions_count = _first_field(
            reconciliation,
            shutdown,
            preflight,
            names=("positions_count", "last_broker_positions_count"),
        )
        protected_match = re.search(r"protected_symbols=([0-9]+)", joined)
        evidence.baseline_positions = {
            "positions_count": _as_int(positions_count) if positions_count is not None else None,
            "last_broker_positions_count": _as_int(_first_field(shutdown, reconciliation, names="last_broker_positions_count", default=0)),
            "protected_baseline_context_observed": "PAPER baseline runtime context loaded" in joined
            or "Protected PAPER baseline context present" in joined,
            "protected_symbols_count": _as_int(protected_match.group(1)) if protected_match else None,
            "broker_positions_preserved": _as_bool(_first_field(shutdown, reconciliation, names="broker_positions_preserved", default=False))
            or "broker_positions_preserved=true" in joined.lower(),
            "source": "BROKER_CONFIRMED_SHUTDOWN_OR_PREFLIGHT",
        }
        evidence.broker_method_counts = {
            "GET": max(method_counts["GET"], preflight_method_counts["GET"]),
            "POST": max(method_counts["POST"], preflight_method_counts["POST"]),
            "DELETE": max(method_counts["DELETE"], preflight_method_counts["DELETE"]),
            "preflight_GET": preflight_method_counts["GET"],
            "preflight_POST": preflight_method_counts["POST"],
            "preflight_DELETE": preflight_method_counts["DELETE"],
            "shutdown_GET": method_counts["GET"],
            "shutdown_POST": method_counts["POST"],
            "shutdown_DELETE": method_counts["DELETE"],
        }
        evidence.shutdown_controls = {
            "broker_flatten_called": _as_bool(_first_field(shutdown, reconciliation, names="broker_flatten_called", default=False)),
            "broker_positions_preserved": evidence.baseline_positions["broker_positions_preserved"],
            "mutation_performed": _as_bool(_first_field(shutdown, reconciliation, names="mutation_performed", default=False)),
            "cancel_attempted": evidence.runtime_order_activity["cancel_attempted"],
            "cancel_authorized": evidence.runtime_order_activity["cancel_authorized"],
            "cancel_acknowledged": evidence.runtime_order_activity["cancel_acknowledged"],
            "close_attempted": _field_true(joined, ("close_attempted", "broker_close_called")),
            "liquidation_attempted": _field_true(joined, ("liquidation_attempted", "broker_liquidation_called")),
            "source": "OMS_SHUTDOWN_ACCOUNTING_AND_RECONCILIATION",
        }
        evidence.shutdown_open_orders = {
            "open_orders_count": _as_int(_first_field(reconciliation, shutdown, preflight, names=("open_orders_count", "last_broker_open_orders_count"), default=0)),
            "last_broker_open_orders_count": _as_int(_first_field(shutdown, reconciliation, names="last_broker_open_orders_count", default=0)),
            "local_open_orders_before_final_reconcile": _as_int(_first_field(reconciliation, shutdown, names="local_open_orders_before_final_reconcile", default=0)),
            "broker_confirmed_open_orders": _as_int(_first_field(reconciliation, shutdown, names="broker_confirmed_open_orders", default=0)),
            "local_open_orders_after_final_reconcile": _as_int(_first_field(reconciliation, shutdown, names="local_open_orders_after_final_reconcile", default=0)),
            "source": "SHUTDOWN_RECONCILIATION",
        }
        tca_pending = _as_int(_first_field(shutdown, reconciliation, names="tca_fee_pending_count", default=0))
        tca_complete = _as_int(_first_field(shutdown, reconciliation, names="tca_complete_count", default=0))
        tca_unknown = _as_int(_first_field(shutdown, reconciliation, names="tca_unknown_count", default=0))
        tca_records = _as_int(_first_field(shutdown, reconciliation, names="tca_records_count", default=0))
        if evidence.broker_fee_hydration_skipped:
            fee_tca_status = "SKIPPED"
        elif tca_pending > 0:
            fee_tca_status = "PENDING_FEE_DETAIL"
        elif tca_complete > 0 and tca_pending == 0 and tca_unknown == 0:
            fee_tca_status = "COMPLETE"
        elif tca_records > 0:
            fee_tca_status = "PARTIAL"
        else:
            fee_tca_status = "UNKNOWN"
        evidence.fee_tca_status = {
            "status": fee_tca_status,
            "fee_hydration_skipped": evidence.broker_fee_hydration_skipped,
            "fee_hydration_skip_reason": evidence.broker_fee_hydration_skip_reason,
            "account_activity_read_authorized": evidence.account_activity_read_authorized,
            "broker_read_profile": evidence.broker_read_profile,
            "tca_records_count": tca_records,
            "tca_complete_count": tca_complete,
            "tca_estimated_count": _as_int(_first_field(shutdown, reconciliation, names="tca_estimated_count", default=0)),
            "tca_fee_pending_count": tca_pending,
            "tca_unknown_count": tca_unknown,
            "realized_vs_modeled_netedge_available_count": _as_int(_first_field(shutdown, reconciliation, names="realized_vs_modeled_netedge_available_count", default=0)),
            "realized_vs_modeled_netedge_unknown_count": _as_int(_first_field(shutdown, reconciliation, names="realized_vs_modeled_netedge_unknown_count", default=0)),
            "source": "OMS_SHUTDOWN_ACCOUNTING_AND_RECONCILIATION",
        }
        evidence.preflight = {
            "account_status": preflight.get("account_status"),
            "endpoint": preflight.get("endpoint"),
            "execution_broker": preflight.get("execution_broker"),
            "adapter_id": preflight.get("adapter_id"),
            "live_endpoint_used": preflight.get("live_endpoint_used"),
            "mutation_occurred": preflight.get("mutation_occurred"),
            "open_orders_count": preflight.get("open_orders_count"),
            "positions_count": preflight.get("positions_count"),
            "method_counts": preflight_method_counts,
        }
    else:
        evidence.orders_submitted = _count_markers(joined, _ORDER_SUBMITTED)
        evidence.orders_acknowledged = _count_markers(joined, _ORDER_ACK)
        evidence.orders_canceled = _count_markers(joined, _ORDER_CANCEL)
        evidence.fills_observed = _count_markers(joined, _FILL)
        evidence.fill_hydration_observed = _has_marker(joined, _FILL)
        evidence.broker_fee_hydration_observed = _has_marker(joined, _FEE)
        evidence.tca_observed = _has_marker(joined, _TCA)
        evidence.oms_shutdown_accounting_observed = _has_marker(joined, _OMS)
        evidence.fee_detail_pending_observed = (
            "FEE_PENDING" in joined.upper()
            or "BROKER_FILL_FEE_DETAIL_UNAVAILABLE" in joined.upper()
        )
        evidence.runtime_order_activity = {
            "order_post_attempted": evidence.orders_submitted,
            "order_post_authorized": 0,
            "order_post_acknowledged": evidence.orders_acknowledged,
            "submitted_count": evidence.orders_submitted,
            "cancel_attempted": evidence.orders_canceled,
            "cancel_authorized": 0,
            "cancel_acknowledged": evidence.orders_canceled,
            "fill_hydration_attempted_count": evidence.fills_observed,
            "fill_hydration_count": evidence.fills_observed,
            "source": "FREE_TEXT_MARKER_SCAN",
        }
        evidence.historical_order_activity = {"source": "UNAVAILABLE_WITHOUT_STRUCTURED_SHUTDOWN_ACCOUNTING"}
        evidence.baseline_positions = {"positions_count": None, "source": "UNAVAILABLE_WITHOUT_STRUCTURED_SHUTDOWN_ACCOUNTING"}
        evidence.broker_method_counts = {"GET": 0, "POST": 0, "DELETE": 0, "preflight_GET": 0, "preflight_POST": 0, "preflight_DELETE": 0, "shutdown_GET": 0, "shutdown_POST": 0, "shutdown_DELETE": 0}
        evidence.shutdown_controls = {
            "broker_flatten_called": _field_true(joined, ("broker_flatten_called",)),
            "broker_positions_preserved": "broker_positions_preserved=true" in joined.lower(),
            "mutation_performed": _field_true(joined, ("mutation_performed",)),
            "cancel_attempted": evidence.orders_canceled,
            "cancel_authorized": 0,
            "cancel_acknowledged": evidence.orders_canceled,
            "close_attempted": _field_true(joined, ("close_attempted", "broker_close_called")),
            "liquidation_attempted": _field_true(joined, ("liquidation_attempted", "broker_liquidation_called")),
            "source": "FREE_TEXT_MARKER_SCAN",
        }
        evidence.shutdown_open_orders = {"open_orders_count": None, "source": "UNAVAILABLE_WITHOUT_STRUCTURED_SHUTDOWN_RECONCILIATION"}
        evidence.fee_tca_status = {
            "status": "PENDING_FEE_DETAIL" if evidence.fee_detail_pending_observed else ("COMPLETE" if evidence.tca_observed and evidence.broker_fee_hydration_observed else "UNKNOWN"),
            "fee_hydration_skipped": evidence.broker_fee_hydration_skipped,
            "fee_hydration_skip_reason": evidence.broker_fee_hydration_skip_reason,
            "source": "FREE_TEXT_MARKER_SCAN",
        }

    evidence.market_data_latency = _extract_market_latency_summary(joined)
    evidence.per_symbol_decisions = _decision_symbol_summary(joined, session.get("watchlist") or [])
    evidence.broker_fee_hydration_conflict_observed = (
        _field_positive_count(joined, _BROKER_FEE_CONFLICT_FIELDS)
        or _field_true(joined, _BROKER_FEE_CONFLICT_TRUE_FIELDS)
        or _has_exact_marker(joined, _BROKER_FEE_CONFLICT_MARKERS)
    )
    evidence.reconciliation_conflict_observed = (
        _field_positive_count(joined, _RECONCILIATION_CONFLICT_FIELDS)
        or _field_true(joined, _RECONCILIATION_CONFLICT_TRUE_FIELDS)
        or _has_exact_marker(joined, _RECONCILIATION_CONFLICT_MARKERS)
    )
    live_true = _field_true(joined, _LIVE_TRUE_FIELDS) or _has_exact_marker(joined, _LIVE_TRUE_MARKERS)
    real_money_true = _field_true(joined, _REAL_MONEY_TRUE_FIELDS) or _has_exact_marker(joined, _REAL_MONEY_TRUE_MARKERS)
    evidence.safety_markers = {
        "live_marker": live_true or real_money_true,
        "real_money_marker": real_money_true,
        "unauthorized_mutation_marker": _has_marker(joined, _UNAUTHORIZED),
        "naked_sell_marker": _has_marker(joined, _NAKED_SELL),
    }
    return evidence


def _verdict(session: dict[str, Any], evidence: RunLogEvidence) -> tuple[str, list[str]]:
    reason_codes: list[str] = []
    status = str(session.get("status") or "UNKNOWN")
    exit_code = session.get("exit_code")
    safety_failures = [key for key, value in evidence.safety_markers.items() if value]

    if status in {"STARTING", "RUNNING", "STOP_REQUESTED", "PROCESS_STATE_UNKNOWN_AFTER_RESTART"}:
        reason_codes.append("RUN_STILL_ACTIVE_OR_PROCESS_STATE_UNKNOWN")
        return UNKNOWN, reason_codes
    if exit_code is None and status not in {"REFUSED"}:
        reason_codes.append("MISSING_EXIT_CODE")
    elif exit_code not in (0, "0", None):
        reason_codes.append("NONZERO_EXIT_CODE")

    if not evidence.readable_log_paths:
        reason_codes.append("LOG_EVIDENCE_UNAVAILABLE")
    if evidence.reconciliation_conflict_observed:
        reason_codes.append("RECONCILIATION_OR_LEDGER_CONFLICT")
    for marker in safety_failures:
        reason_codes.append(marker.upper())

    if any(code in reason_codes for code in ("NONZERO_EXIT_CODE", "RECONCILIATION_OR_LEDGER_CONFLICT")) or safety_failures:
        return FAIL, reason_codes
    if exit_code is None and status not in {"REFUSED"}:
        return UNKNOWN, reason_codes
    if status == "REFUSED":
        reason_codes.append(str(session.get("refusal_reason") or "RUN_REFUSED"))
        return UNKNOWN, reason_codes

    conditional = False
    if not evidence.oms_shutdown_accounting_observed:
        reason_codes.append("OMS_SHUTDOWN_ACCOUNTING_NOT_OBSERVED")
        conditional = True
    if evidence.broker_fee_hydration_conflict_observed:
        reason_codes.append("BROKER_FEE_HYDRATION_CONFLICT")
        conditional = True
    fee_hydration_not_authorized = (
        evidence.broker_fee_hydration_skipped
        and evidence.broker_fee_hydration_skip_reason == "BROKER_READ_NOT_AUTHORIZED"
    )
    if not fee_hydration_not_authorized and (evidence.fee_detail_pending_observed or not evidence.broker_fee_hydration_observed):
        reason_codes.append("BROKER_FEE_DETAIL_PENDING_OR_UNOBSERVED")
        conditional = True
    if not evidence.tca_observed:
        reason_codes.append("TCA_EVIDENCE_UNAVAILABLE")
        conditional = True
    if not evidence.readable_log_paths:
        conditional = True
    if conditional:
        return CONDITIONAL_PASS, reason_codes
    reason_codes.append("EXITED_ZERO_WITH_REQUIRED_OPERATOR_EVIDENCE")
    return PASS, reason_codes


def _recommend_72h(verdict: str, evidence: RunLogEvidence) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []
    if verdict != PASS:
        blockers.append("RUN_VERDICT_NOT_FULL_PASS")
    if _as_int(evidence.runtime_order_activity.get("order_post_acknowledged", 0)) <= 0:
        blockers.append("NO_RUNTIME_NEW_ORDER_ACKNOWLEDGEMENTS")
    fee_tca_status = str(evidence.fee_tca_status.get("status") or "UNKNOWN")
    if fee_tca_status in {"SKIPPED", "PENDING_FEE_DETAIL", "UNKNOWN", "PARTIAL"}:
        blockers.append(f"FEE_TCA_STATUS_{fee_tca_status}")
    if _as_int(evidence.fee_tca_status.get("realized_vs_modeled_netedge_available_count", 0)) <= 0:
        blockers.append("REALIZED_VS_MODELED_NETEDGE_UNAVAILABLE")
    if not evidence.oms_shutdown_accounting_observed:
        blockers.append("OMS_SHUTDOWN_ACCOUNTING_NOT_OBSERVED")
    if any(evidence.safety_markers.values()):
        blockers.append("SAFETY_MARKER_PRESENT")
    if _as_int(evidence.broker_method_counts.get("DELETE", 0)) > 0:
        warnings.append("DELETE_METHOD_COUNT_NONZERO_REVIEW_CANCEL_CONTEXT")
    if _as_int(evidence.market_data_latency.get("warning_count_in_scanned_excerpt", 0)) > 0:
        warnings.append("MARKET_DATA_LATENCY_WARNINGS_PRESENT")
    if not evidence.baseline_positions.get("broker_positions_preserved"):
        warnings.append("BROKER_POSITIONS_PRESERVED_NOT_CONFIRMED")

    if blockers:
        recommendation = "NOT_APPROVED_NEEDS_SMALLER_PROOF"
        next_safe_action = (
            "Run a smaller Board-approved proof with complete run reporting and, if approved, "
            "read-only fee/account-activity hydration before any 72-hour PAPER run."
        )
    else:
        recommendation = "READY_FOR_72H_BOARD_REVIEW"
        next_safe_action = "Board may review this run for 72-hour PAPER approval; this is not live or real-money authority."
    return {
        "recommendation": recommendation,
        "blockers": tuple(dict.fromkeys(blockers)),
        "warnings": tuple(dict.fromkeys(warnings)),
        "next_safe_action": next_safe_action,
        "live_trading_authorized": False,
        "real_money_authorized": False,
        "manual_controls_authorized": False,
    }


def build_run_record(
    session: dict[str, Any],
    *,
    repo_root: Path,
    report_dir: Path | None = None,
) -> dict[str, Any]:
    session_id = str(session.get("session_id") or session.get("run_id") or "unknown_run")
    evidence = scan_run_logs(session, repo_root=repo_root)
    verdict, reason_codes = _verdict(session, evidence)
    observed_wall_clock_seconds = _duration_seconds(session.get("started_at") or session.get("requested_at"), session.get("ended_at"))
    requested_duration_seconds = session.get("duration_seconds")
    archive_updated_at = utc_now_iso()
    report_path = None
    json_report_path = None
    if report_dir is not None:
        candidate = Path(report_dir) / f"{session_id}.md"
        if candidate.exists():
            report_path = str(candidate)
        json_candidate = Path(report_dir) / f"{session_id}.json"
        if json_candidate.exists():
            json_report_path = str(json_candidate)
    readiness_72h = _recommend_72h(verdict, evidence)
    record = {
        "archive_version": RUN_ARCHIVE_VERSION,
        "run_id": session_id,
        "session_id": session_id,
        "start_time": session.get("started_at") or session.get("requested_at"),
        "end_time": session.get("ended_at"),
        "duration_seconds": requested_duration_seconds if requested_duration_seconds is not None else observed_wall_clock_seconds,
        "requested_duration_seconds": requested_duration_seconds,
        "observed_wall_clock_seconds": observed_wall_clock_seconds,
        "mode": "PAPER",
        "profile": session.get("profile"),
        "watchlist": list(session.get("watchlist") or []),
        "git_commit": session.get("git_commit"),
        "wrapper_log_paths": {
            "stdout": session.get("wrapper_stdout_path") or session.get("stdout_path"),
            "stderr": session.get("wrapper_stderr_path") or session.get("stderr_path"),
        },
        "child_log_paths": {
            "stdout": session.get("child_stdout_path"),
            "stderr": session.get("child_stderr_path"),
        },
        "exit_code": session.get("exit_code"),
        "status": session.get("status") or "UNKNOWN",
        "orders": {
            "submitted": evidence.orders_submitted,
            "acknowledged": evidence.orders_acknowledged,
            "canceled": evidence.orders_canceled,
        },
        "runtime_new_activity": evidence.runtime_order_activity,
        "historical_broker_local_activity": evidence.historical_order_activity,
        "baseline_positions": evidence.baseline_positions,
        "broker_method_counts": evidence.broker_method_counts,
        "shutdown_controls": evidence.shutdown_controls,
        "shutdown_open_orders": evidence.shutdown_open_orders,
        "fills": {
            "observed": evidence.fills_observed,
            "fill_hydration_observed": evidence.fill_hydration_observed,
            "broker_fee_hydration_observed": evidence.broker_fee_hydration_observed,
            "broker_fee_hydration_conflict_observed": evidence.broker_fee_hydration_conflict_observed,
            "broker_fee_hydration_skipped": evidence.broker_fee_hydration_skipped,
            "broker_fee_hydration_skip_reason": evidence.broker_fee_hydration_skip_reason,
            "account_activity_read_authorized": evidence.account_activity_read_authorized,
            "broker_read_profile": evidence.broker_read_profile,
        },
        "tca": {
            "status": "OBSERVED" if evidence.tca_observed else "UNKNOWN",
            "observed": evidence.tca_observed,
            "fee_tca_status": evidence.fee_tca_status,
        },
        "fee_tca": evidence.fee_tca_status,
        "market_data_latency": evidence.market_data_latency,
        "per_symbol_decisions": evidence.per_symbol_decisions,
        "oms_shutdown_accounting": {
            "status": "OBSERVED" if evidence.oms_shutdown_accounting_observed else "UNKNOWN",
            "observed": evidence.oms_shutdown_accounting_observed,
        },
        "safety_markers": evidence.safety_markers,
        "final_verdict": verdict,
        "reason_codes": tuple(dict.fromkeys(reason_codes)),
        "readiness_72h": readiness_72h,
        "report_path": report_path,
        "json_report_path": json_report_path,
        "artifact_paths": {
            "wrapper_stdout": session.get("wrapper_stdout_path") or session.get("stdout_path"),
            "wrapper_stderr": session.get("wrapper_stderr_path") or session.get("stderr_path"),
            "child_stdout": session.get("child_stdout_path"),
            "child_stderr": session.get("child_stderr_path"),
            "report": report_path,
            "json_report": json_report_path,
        },
        "log_evidence": evidence.to_dict(),
        "truth_policy": {
            "broker_truth_faked": False,
            "pnl_faked": False,
            "fees_faked": False,
            "tca_faked": False,
            "logs_mutated": False,
        },
        "archive_updated_at": archive_updated_at,
        "updated_at": archive_updated_at,
    }
    return record


class RunArchive:
    def __init__(
        self,
        *,
        session_store: Any | None = None,
        sessions: Iterable[dict[str, Any]] | None = None,
        repo_root: Path,
        report_dir: Path | None = None,
    ) -> None:
        self.session_store = session_store
        self._sessions = list(sessions) if sessions is not None else None
        self.repo_root = Path(repo_root)
        self.report_dir = Path(report_dir) if report_dir is not None else None

    def _load_sessions(self) -> list[dict[str, Any]]:
        if self._sessions is not None:
            rows = [dict(row) for row in self._sessions]
        elif self.session_store is not None and hasattr(self.session_store, "sessions"):
            rows = [dict(row) for row in self.session_store.sessions()]
        else:
            rows = []
        rows.sort(key=_session_sort_key, reverse=True)
        return rows

    def list_runs(self, *, limit: int = 50) -> dict[str, Any]:
        records = [
            build_run_record(session, repo_root=self.repo_root, report_dir=self.report_dir)
            for session in self._load_sessions()[: max(int(limit), 0)]
        ]
        return {
            "source": "OPERATOR_SESSION_STORE",
            "archive_version": RUN_ARCHIVE_VERSION,
            "run_count": len(records),
            "runs": records,
            "stores_log_contents": False,
            "secrets_values_exposed": False,
        }

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        wanted = str(run_id)
        for session in self._load_sessions():
            session_id = str(session.get("session_id") or session.get("run_id") or "")
            if session_id == wanted:
                return build_run_record(session, repo_root=self.repo_root, report_dir=self.report_dir)
        return None
