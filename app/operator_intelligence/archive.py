"""Run archive and flight-recorder summaries for operator-visible PAPER runs.

The archive reads session metadata and referenced log files as evidence. It
never writes logs, never calls brokers, and never invents missing truth.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


RUN_ARCHIVE_VERSION = "operator-run-archive-v1"
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
_CONFLICT = ("RECONCILIATION_CONFLICT", "FILL_LEDGER_CONFLICT", "FEE_ACTIVITY_CONFLICT", "CONFLICT")
_LIVE = ("LIVE_ENDPOINT", "live_endpoint_touched", "LIVE_NOT_APPROVED_BYPASS")
_REAL_MONEY = ("REAL_MONEY", "real_money_touched")
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
    if "\\" in text:
        candidates.append(Path(text.replace("\\", "/")))
    for candidate in list(candidates):
        if not candidate.is_absolute():
            candidates.append(repo_root / candidate)
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return candidates[-1] if candidates else None


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
    tca_observed: bool = False
    oms_shutdown_accounting_observed: bool = False
    reconciliation_conflict_observed: bool = False
    fee_detail_pending_observed: bool = False
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
            "tca_observed": self.tca_observed,
            "oms_shutdown_accounting_observed": self.oms_shutdown_accounting_observed,
            "reconciliation_conflict_observed": self.reconciliation_conflict_observed,
            "fee_detail_pending_observed": self.fee_detail_pending_observed,
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
    evidence.orders_submitted = _count_markers(joined, _ORDER_SUBMITTED)
    evidence.orders_acknowledged = _count_markers(joined, _ORDER_ACK)
    evidence.orders_canceled = _count_markers(joined, _ORDER_CANCEL)
    evidence.fills_observed = _count_markers(joined, _FILL)
    evidence.fill_hydration_observed = _has_marker(joined, _FILL)
    evidence.broker_fee_hydration_observed = _has_marker(joined, _FEE)
    evidence.tca_observed = _has_marker(joined, _TCA)
    evidence.oms_shutdown_accounting_observed = _has_marker(joined, _OMS)
    evidence.reconciliation_conflict_observed = _has_marker(joined, _CONFLICT)
    evidence.fee_detail_pending_observed = "FEE_PENDING" in joined.upper() or "BROKER_FILL_FEE_DETAIL_UNAVAILABLE" in joined.upper()
    evidence.safety_markers = {
        "live_marker": _has_marker(joined, _LIVE),
        "real_money_marker": _has_marker(joined, _REAL_MONEY),
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
    if evidence.fee_detail_pending_observed or not evidence.broker_fee_hydration_observed:
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


def build_run_record(
    session: dict[str, Any],
    *,
    repo_root: Path,
    report_dir: Path | None = None,
) -> dict[str, Any]:
    session_id = str(session.get("session_id") or session.get("run_id") or "unknown_run")
    evidence = scan_run_logs(session, repo_root=repo_root)
    verdict, reason_codes = _verdict(session, evidence)
    duration = _duration_seconds(session.get("started_at") or session.get("requested_at"), session.get("ended_at"))
    report_path = None
    if report_dir is not None:
        candidate = Path(report_dir) / f"{session_id}.md"
        if candidate.exists():
            report_path = str(candidate)
    record = {
        "archive_version": RUN_ARCHIVE_VERSION,
        "run_id": session_id,
        "session_id": session_id,
        "start_time": session.get("started_at") or session.get("requested_at"),
        "end_time": session.get("ended_at"),
        "duration_seconds": duration if duration is not None else session.get("duration_seconds"),
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
        "fills": {
            "observed": evidence.fills_observed,
            "fill_hydration_observed": evidence.fill_hydration_observed,
            "broker_fee_hydration_observed": evidence.broker_fee_hydration_observed,
        },
        "tca": {
            "status": "OBSERVED" if evidence.tca_observed else "UNKNOWN",
            "observed": evidence.tca_observed,
        },
        "oms_shutdown_accounting": {
            "status": "OBSERVED" if evidence.oms_shutdown_accounting_observed else "UNKNOWN",
            "observed": evidence.oms_shutdown_accounting_observed,
        },
        "safety_markers": evidence.safety_markers,
        "final_verdict": verdict,
        "reason_codes": tuple(dict.fromkeys(reason_codes)),
        "report_path": report_path,
        "log_evidence": evidence.to_dict(),
        "truth_policy": {
            "broker_truth_faked": False,
            "pnl_faked": False,
            "fees_faked": False,
            "tca_faked": False,
            "logs_mutated": False,
        },
        "updated_at": utc_now_iso(),
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
