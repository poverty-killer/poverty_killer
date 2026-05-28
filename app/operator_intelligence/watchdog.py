"""Safe local watchdog alert derivation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _alert(alert_id: str, severity: str, title: str, detail: str, *, source: str) -> dict[str, Any]:
    return {
        "alert_id": alert_id,
        "severity": severity,
        "title": title,
        "detail": detail,
        "source": source,
        "acknowledged": False,
        "can_execute": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


class AlertQueue:
    """Small in-memory queue for local operator alerts."""

    def __init__(self) -> None:
        self._items: dict[str, dict[str, Any]] = {}

    def sync(self, alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for alert in alerts:
            alert_id = str(alert.get("alert_id") or "")
            if not alert_id:
                continue
            previous = self._items.get(alert_id) or {}
            queued = dict(alert)
            queued["acknowledged"] = bool(previous.get("acknowledged", queued.get("acknowledged", False)))
            self._items[alert_id] = queued
        active_ids = {str(alert.get("alert_id")) for alert in alerts}
        self._items = {key: value for key, value in self._items.items() if key in active_ids}
        return self.list()

    def list(self) -> list[dict[str, Any]]:
        rows = list(self._items.values())
        rows.sort(key=lambda item: (str(item.get("severity")), str(item.get("alert_id"))))
        return [dict(row) for row in rows]


def build_watchdog_alerts(
    *,
    status: dict[str, Any],
    runtime: dict[str, Any],
    health: dict[str, Any],
    readiness: dict[str, Any],
    storage: dict[str, Any],
    orders: dict[str, Any],
    fills: dict[str, Any],
    tca: dict[str, Any],
    world_runtime: dict[str, Any],
    archive: dict[str, Any],
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    if not status.get("supervisor", {}).get("active_session"):
        alerts.append(_alert("no_active_runtime", "WARNING", "No active runtime", "No active PAPER process is attached.", source="status"))
    if runtime.get("process_state") in {"FAILED"} or runtime.get("exit_code") not in (None, 0, "0"):
        alerts.append(_alert("session_nonzero_exit", "SAFETY_CRITICAL", "Runtime exited nonzero", f"exit_code={runtime.get('exit_code')}", source="runtime"))
    if status.get("supervisor", {}).get("active_session") and not (runtime.get("child_stdout_path") or runtime.get("stdout_path")):
        alerts.append(_alert("log_silence", "WARNING", "Runtime log path unavailable", "Active runtime has no readable child/wrapper log path in metadata.", source="runtime"))
    if int(orders.get("reconciliation_conflicts") or 0) > 0:
        alerts.append(_alert("oms_conflict", "SAFETY_CRITICAL", "OMS reconciliation conflict", "Order reconciliation conflict count is nonzero.", source="orders-summary"))
    if int(fills.get("fill_hydration_conflict_count") or 0) > 0:
        alerts.append(_alert("fill_conflict", "SAFETY_CRITICAL", "Fill hydration conflict", "Fill ledger conflict count is nonzero.", source="fills-summary"))
    if int(fills.get("broker_fee_hydration_conflict_count") or 0) > 0:
        alerts.append(_alert("fee_conflict", "SAFETY_CRITICAL", "Broker fee hydration conflict", "Fee hydration conflict count is nonzero.", source="fills-summary"))
    if storage.get("session_store", {}).get("status") != "READY" or storage.get("world_awareness_cache", {}).get("status") != "READY":
        alerts.append(_alert("storage_degraded", "WARNING", "Storage degraded", "Session store or World Awareness cache is degraded.", source="storage"))
    for code in readiness.get("cloud_missing_prerequisites") or ():
        alerts.append(_alert(f"cloud_missing:{code}", "INFO", "Cloud prerequisite missing", str(code), source="readiness"))
    if world_runtime.get("provider_polling_active") is False and world_runtime.get("manual_poll_only") is not True:
        alerts.append(_alert("world_awareness_provider_inactive", "WARNING", "World Awareness provider inactive", "Provider runtime is not active.", source="world-awareness/runtime"))
    if "STALE" in str(tca.get("execution_quality_verdict") or "").upper():
        alerts.append(_alert("market_truth_stale", "WARNING", "Market truth or TCA stale", str(tca.get("execution_quality_verdict")), source="tca-summary"))
    for run in archive.get("runs") or ():
        markers = run.get("safety_markers") or {}
        if any(markers.values()):
            alerts.append(_alert(f"run_safety_marker:{run.get('run_id')}", "SAFETY_CRITICAL", "Run safety marker observed", str(markers), source="runs"))
        if run.get("final_verdict") == "FAIL":
            alerts.append(_alert(f"run_failed:{run.get('run_id')}", "SAFETY_CRITICAL", "Run archive verdict failed", ",".join(run.get("reason_codes") or ()), source="runs"))
    if health.get("live_status") != "LIVE_LOCKED":
        alerts.append(_alert("live_lock_missing", "SAFETY_CRITICAL", "Live lock status unexpected", str(health.get("live_status")), source="health"))
    if health.get("real_money_status") != "BLOCKED":
        alerts.append(_alert("real_money_not_blocked", "SAFETY_CRITICAL", "Real-money block status unexpected", str(health.get("real_money_status")), source="health"))
    return alerts
