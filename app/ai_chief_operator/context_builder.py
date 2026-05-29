"""Secret-safe context builder for advisory AI Chief analysis."""

from __future__ import annotations

import re
from typing import Any

from app.ai_chief_operator.quant_persona import quant_persona_summary


SECRET_KEY_PARTS = ("secret", "token", "password", "api_key", "apikey", "key_id", "private", "credential")
SECRET_VALUE_RE = re.compile(
    r"(sk-[A-Za-z0-9_\-]{8,}|AKIA[0-9A-Z]{12,}|xox[baprs]-[A-Za-z0-9\-]+|-----BEGIN [A-Z ]*PRIVATE KEY-----)"
)
HIGH_ENTROPY_VALUE_RE = re.compile(r"\b(?=[A-Za-z0-9_\-]{32,}\b)(?=.*[a-z])(?=.*[A-Z])(?=.*[0-9])[A-Za-z0-9_\-]+\b")
BOOLEAN_STATUS_KEYS = {
    "secrets_values_exposed",
    "raw_logs_included",
    "broker_call_occurred",
    "real_money_blocked",
    "live_ready",
    "local_paper_ready",
}


def redact_secrets(value: Any, *, key: str = "") -> Any:
    key_lower = key.lower()
    if key_lower in BOOLEAN_STATUS_KEYS and isinstance(value, bool):
        return value
    if any(part in key_lower for part in SECRET_KEY_PARTS):
        return "REDACTED"
    if isinstance(value, dict):
        return {str(k): redact_secrets(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_secrets(item) for item in value[:100]]
    if isinstance(value, tuple):
        return tuple(redact_secrets(item) for item in value[:100])
    if isinstance(value, str):
        text = SECRET_VALUE_RE.sub("REDACTED", value)
        return HIGH_ENTROPY_VALUE_RE.sub("REDACTED", text)
    return value


def _small(value: Any) -> Any:
    redacted = redact_secrets(value)
    if isinstance(redacted, list):
        return redacted[:25]
    if isinstance(redacted, dict):
        return {key: redacted[key] for key in list(redacted)[:50]}
    return redacted


def build_ai_context(
    *,
    run_archive: dict[str, Any],
    action_center: dict[str, Any],
    decision_explainer: dict[str, Any],
    pnl: dict[str, Any],
    tca: dict[str, Any],
    world_awareness: dict[str, Any],
    readiness: dict[str, Any],
    alerts: list[dict[str, Any]],
) -> dict[str, Any]:
    latest_runs = run_archive.get("runs") or []
    context = {
        "context_version": "ai-chief-context-v1",
        "persona": quant_persona_summary(),
        "scope": "trading_quant_operator_research_only",
        "latest_run_archive_summary": _small(latest_runs[:3]),
        "action_center": _small(action_center),
        "decision_explainer": _small(decision_explainer),
        "pnl": _small(pnl),
        "tca": _small(tca),
        "world_awareness": _small(world_awareness),
        "readiness": _small(readiness),
        "alerts": _small(alerts),
        "live_status": readiness.get("live_status") or "LIVE_LOCKED",
        "real_money_blocked": readiness.get("real_money_blocked") is not False,
        "raw_logs_included": False,
        "secrets_values_exposed": False,
        "advisory_only": True,
    }
    return redact_secrets(context)
