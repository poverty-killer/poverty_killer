"""Launch-readiness summary for governed bounded PAPER runs."""

from __future__ import annotations

from typing import Any

from app.operator_credentials.store import alpaca_endpoint_authority


def _find_provider(provider_readiness: dict[str, Any], provider_id: str) -> dict[str, Any]:
    for provider in provider_readiness.get("providers") or []:
        if provider.get("provider_id") == provider_id:
            return provider
    return {}


def _check(check_id: str, title: str, status: str, detail: str, *, blocker: bool = False, warning: bool = False) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "title": title,
        "status": status,
        "detail": detail,
        "blocker": blocker,
        "warning": warning,
        "can_execute": False,
    }


def build_launch_readiness(
    *,
    provider_readiness: dict[str, Any],
    credentials: dict[str, Any],
    health: dict[str, Any],
    storage: dict[str, Any],
    runtime: dict[str, Any],
    supervisor: dict[str, Any],
    ai_status: dict[str, Any],
    effective_env: dict[str, str],
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    alpaca = _find_provider(provider_readiness, "alpaca_paper")
    alpaca_configured = bool(alpaca.get("configured"))
    checks.append(
        _check(
            "alpaca_paper_credentials",
            "Alpaca PAPER credentials",
            "PASS" if alpaca_configured else "BLOCKED",
            "configured through env/local secret store" if alpaca_configured else "APCA_API_KEY_ID and APCA_API_SECRET_KEY are missing",
            blocker=not alpaca_configured,
        )
    )

    endpoint_authority = alpaca_endpoint_authority(effective_env)
    endpoint_ok = endpoint_authority["paper_endpoint_only"] is True
    checks.append(
        _check(
            "paper_endpoint_only",
            "PAPER endpoint only",
            "PASS" if endpoint_ok else "BLOCKED",
            str(endpoint_authority["safe_detail"] if endpoint_ok else endpoint_authority["operator_action"]),
            blocker=not endpoint_ok,
        )
    )

    checks.append(_check("live_blocked", "Live blocked", "PASS", "LIVE_LOCKED remains active"))
    checks.append(_check("real_money_blocked", "Real money blocked", "PASS", "real-money mode remains blocked"))

    no_active = str(runtime.get("process_state") or "").upper() not in {"RUNNING", "STARTING", "STOP_REQUESTED"}
    checks.append(
        _check(
            "no_active_runtime",
            "No active runtime",
            "PASS" if no_active else "BLOCKED",
            "no active PAPER run attached" if no_active else "duplicate-run prevention blocks another start",
            blocker=not no_active,
        )
    )

    market_ready = any(
        provider.get("category") == "market_data" and provider.get("status") in {"READY", "CONFIGURED"}
        for provider in provider_readiness.get("providers") or []
    )
    checks.append(
        _check(
            "market_data_provider",
            "Market-data provider",
            "PASS" if market_ready else "DEGRADED",
            "at least one read provider is ready/configured" if market_ready else "market-data readiness is not confirmed",
            warning=not market_ready,
        )
    )

    ai_provider_state = ((ai_status.get("gateway") or {}).get("provider") or {}).get("provider_state") or "AI_DISABLED"
    checks.append(
        _check(
            "ai_provider",
            "AI provider",
            "PASS" if ai_provider_state in {"AI_DISABLED", "MOCK_MODE", "PROVIDER_READY"} else "DEGRADED",
            str(ai_provider_state),
            warning=ai_provider_state not in {"AI_DISABLED", "MOCK_MODE", "PROVIDER_READY"},
        )
    )

    session_ready = (storage.get("session_store") or {}).get("status") == "READY"
    checks.append(
        _check(
            "audit_session_storage",
            "Audit/session storage",
            "PASS" if session_ready else "BLOCKED",
            str((storage.get("session_store") or {}).get("status") or "UNKNOWN"),
            blocker=not session_ready,
        )
    )

    paper_start_allowed = supervisor.get("paper_start_allowed") is True or runtime.get("paper_start_allowed") is True
    checks.append(
        _check(
            "paper_start_authority",
            "Governed PAPER start",
            "PASS" if paper_start_allowed else "BLOCKED",
            "existing /operator/intent/paper/start is available" if paper_start_allowed else str(supervisor.get("paper_start_refusal_reason") or runtime.get("paper_start_refusal_reason") or "not allowed"),
            blocker=not paper_start_allowed,
        )
    )

    if supervisor.get("paper_stop_allowed") is True or runtime.get("paper_stop_allowed") is True:
        safe_stop_status = "SAFE_STOP_AVAILABLE"
        safe_stop_detail = "graceful supervisor stop is available for the active PAPER runtime"
    elif no_active:
        safe_stop_status = "NO_ACTIVE_RUNTIME"
        safe_stop_detail = "no runtime needs stopping"
    else:
        safe_stop_status = "SAFE_STOP_UNAVAILABLE"
        safe_stop_detail = str(supervisor.get("paper_stop_refusal_reason") or runtime.get("paper_stop_refusal_reason") or "unknown")
    checks.append(
        _check(
            "safe_stop_status",
            "Safe stop status",
            "PASS" if safe_stop_status in {"SAFE_STOP_AVAILABLE", "NO_ACTIVE_RUNTIME"} else "DEGRADED",
            safe_stop_detail,
            warning=safe_stop_status == "SAFE_STOP_UNAVAILABLE",
        )
    )

    checks.append(
        _check(
            "portfolio_read_availability",
            "Portfolio read availability",
            "PASS" if alpaca_configured else "DEGRADED",
            "broker-confirmed read endpoint can be attempted" if alpaca_configured else "portfolio page will show broker data unavailable",
            warning=not alpaca_configured,
        )
    )

    blockers = [check for check in checks if check["blocker"]]
    warnings = [check for check in checks if check["warning"]]
    if blockers:
        final = "BLOCKED"
    elif warnings:
        final = "DEGRADED_BUT_RUNNABLE"
    else:
        final = "READY_FOR_BOUNDED_PAPER"
    return {
        "source": "OPERATOR_LAUNCH_READINESS",
        "final_launch_readiness": final,
        "checks": checks,
        "reason_codes": [check["check_id"] for check in blockers + warnings],
        "alpaca_paper_credentials_configured": alpaca_configured,
        "credential_precedence": credentials.get("precedence") or "ENV_PRESENT_OVERRIDES_LOCAL_SECRET",
        "paper_endpoint_only": endpoint_ok,
        "paper_endpoint_authority": endpoint_authority,
        "paper_endpoint_status": endpoint_authority["status"],
        "paper_endpoint_source": endpoint_authority["endpoint_source"],
        "paper_endpoint_operator_action": endpoint_authority["operator_action"],
        "live_blocked": True,
        "real_money_blocked": True,
        "paper_start_allowed": paper_start_allowed,
        "safe_stop_status": safe_stop_status,
        "portfolio_read_availability": "BROKER_READ_READY" if alpaca_configured else "UNAVAILABLE_MISSING_CREDENTIALS",
        "backend_degraded_reasons": list(health.get("degraded_reasons") or []),
        "can_execute": False,
        "broker_call_occurred": False,
        "broker_mutation_occurred": False,
        "trading_mutation_occurred": False,
        "live_enabled": False,
        "real_money_enabled": False,
        "secrets_values_exposed": False,
    }
