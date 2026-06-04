"""Consolidated read-only operator action center."""

from __future__ import annotations

from typing import Any


ACTION_TYPES = {"INFO", "WARNING", "BLOCKER", "NEEDS_APPROVAL", "SAFETY_CRITICAL"}


def _item(action_id: str, action_type: str, title: str, detail: str, *, source: str) -> dict[str, Any]:
    if action_type not in ACTION_TYPES:
        action_type = "INFO"
    return {
        "action_id": action_id,
        "type": action_type,
        "title": title,
        "detail": detail,
        "source": source,
        "requires_shan_approval": action_type in {"NEEDS_APPROVAL", "SAFETY_CRITICAL"},
        "can_execute": False,
    }


def build_action_center(
    *,
    status: dict[str, Any],
    readiness: dict[str, Any],
    health: dict[str, Any],
    storage: dict[str, Any],
    fills: dict[str, Any],
    world_runtime: dict[str, Any],
    archive: dict[str, Any],
    alerts: list[dict[str, Any]],
    ai_recommendations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = [
        _item("live_locked", "BLOCKER", "Live trading is locked", "LIVE_NOT_APPROVED remains the active live state.", source="readiness"),
        _item("real_money_blocked", "BLOCKER", "Real-money mode is blocked", "Real-money authority is not available to operator UI or AI.", source="readiness"),
    ]
    supervisor = status.get("supervisor", {})
    if not supervisor.get("active_session"):
        detail = (
            "Ready. No PAPER run currently attached."
            if supervisor.get("paper_start_allowed") is True
            else "No active PAPER supervisor process is attached."
        )
        items.append(_item("no_active_runtime", "INFO", "No active runtime", detail, source="status"))
    for code in readiness.get("cloud_missing_prerequisites") or ():
        items.append(_item(f"cloud_missing:{code}", "WARNING", "Cloud prerequisite missing", str(code), source="readiness"))
    for code in readiness.get("missing_prerequisites") or ():
        items.append(_item(f"paper_missing:{code}", "BLOCKER", "Local PAPER prerequisite missing", str(code), source="readiness"))
    if int(fills.get("broker_fee_hydration_pending_count") or 0) > 0 or "PENDING" in str(fills.get("fee_status") or "").upper():
        items.append(_item("fee_detail_pending", "WARNING", "Broker fee detail pending", "Fee/TCA economics must remain unknown until broker detail arrives.", source="fills-summary"))
    if world_runtime.get("manual_poll_only") is True:
        items.append(_item("world_awareness_manual_poll", "INFO", "World Awareness is manual-poll only", "Provider polling has no trade authority.", source="world-awareness/runtime"))
    if storage.get("session_store", {}).get("status") != "READY":
        items.append(_item("session_store_health", "WARNING", "Session store degraded", str(storage.get("session_store", {}).get("status")), source="storage"))
    for key in ("operator_state_dir", "log_dir", "data_dir", "archives_runs"):
        entry = storage.get(key) or {}
        if entry.get("status") == "MISSING_PARENT":
            items.append(_item(f"storage:{key}", "WARNING", f"{key} parent missing", str(entry.get("path")), source="storage"))
    if archive.get("run_count", 0) == 0:
        items.append(_item("archive_empty", "INFO", "Run archive has no records", "No session metadata is available yet.", source="runs"))
    for alert in alerts:
        action_type = "SAFETY_CRITICAL" if str(alert.get("severity")) == "SAFETY_CRITICAL" else "WARNING"
        items.append(_item(f"alert:{alert.get('alert_id')}", action_type, str(alert.get("title")), str(alert.get("detail")), source="watchdog"))
    for rec in ai_recommendations or ():
        if str(rec.get("status")) == "PENDING_REVIEW":
            items.append(_item(f"ai:{rec.get('recommendation_id')}", "NEEDS_APPROVAL", "AI recommendation needs review", str(rec.get("summary")), source="ai-chief"))
    counts: dict[str, int] = {item_type: 0 for item_type in sorted(ACTION_TYPES)}
    for item in items:
        counts[item["type"]] += 1
    return {
        "source": "OPERATOR_ACTION_CENTER",
        "items": items,
        "counts": counts,
        "safe_mutation_flags": {
            "broker_call_occurred": False,
            "trading_mutation_occurred": False,
            "live_enabled": False,
            "real_money_enabled": False,
            "can_execute": False,
        },
        "secrets_values_exposed": False,
    }
