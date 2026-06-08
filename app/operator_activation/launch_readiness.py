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


def _check_by_id(checks: list[dict[str, Any]], check_id: str) -> dict[str, Any]:
    for check in checks:
        if check.get("check_id") == check_id:
            return check
    return {}


def _missing_required_fields(provider: dict[str, Any]) -> list[str]:
    required = [str(name) for name in provider.get("required_env_vars") or []]
    rows = provider.get("env_status") if isinstance(provider.get("env_status"), list) else []
    if not required:
        return []
    configured = {
        str(row.get("name"))
        for row in rows
        if isinstance(row, dict) and row.get("configured") is True
    }
    missing = [name for name in required if name not in configured]
    return missing or ([] if provider.get("configured") is True else required)


def _first_blocker_detail(checks: list[dict[str, Any]]) -> str | None:
    for check in checks:
        if check.get("blocker") is True:
            return _plain_check_detail(check)
    return None


def _plain_check_detail(check: dict[str, Any]) -> str:
    check_id = str(check.get("check_id") or "")
    if check_id == "alpaca_paper_credentials":
        return "Alpaca PAPER key ID and secret are missing."
    if check_id == "paper_endpoint_only":
        return str(check.get("detail") or "Only the Alpaca PAPER trading endpoint is accepted.")
    if check_id == "no_active_runtime":
        return "A PAPER runtime is already active or cannot be proven stopped."
    if check_id == "audit_session_storage":
        return "Audit/session storage is not ready."
    if check_id == "paper_start_authority":
        return "Supervisor start authority is blocked."
    return str(check.get("detail") or check.get("title") or check_id or "Start authority is blocked.")


def _operator_status(
    *,
    final: str,
    blockers: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    supervisor: dict[str, Any],
    paper_start_allowed: bool,
) -> dict[str, Any]:
    state = str(supervisor.get("state") or "UNKNOWN").upper()
    if state == "RUNNING":
        return {
            "code": "ACTIVE",
            "label": "PAPER run active",
            "severity": "yellow",
            "detail": "A PAPER runtime is already attached; duplicate start is blocked.",
        }
    if state == "STALE_ACTIVE_SESSION":
        return {
            "code": "STALE",
            "label": "Previous PAPER state needs review",
            "severity": "red",
            "detail": "The supervisor found a prior active session after restart and cannot prove it is stopped.",
        }
    if blockers or final == "BLOCKED" or not paper_start_allowed:
        return {
            "code": "BLOCKED",
            "label": "PAPER start blocked",
            "severity": "red",
            "detail": _first_blocker_detail(blockers) or str(supervisor.get("paper_start_refusal_reason") or "Start authority is blocked."),
        }
    if warnings or final == "DEGRADED_BUT_RUNNABLE":
        return {
            "code": "READY",
            "label": "PAPER start allowed with warnings",
            "severity": "yellow",
            "detail": "Backend start authority is available, but warnings remain in advanced readiness.",
        }
    return {
        "code": "READY",
        "label": "Ready for bounded PAPER",
        "severity": "green",
        "detail": "Backend start authority is available and required launch checks passed.",
    }


def _plain_endpoint_label(endpoint_authority: dict[str, Any]) -> str:
    family = str(endpoint_authority.get("alpaca_trading_endpoint_family") or "unknown")
    source = str(endpoint_authority.get("endpoint_source") or "UNKNOWN")
    display = str(endpoint_authority.get("alpaca_endpoint_display") or "unavailable")
    if endpoint_authority.get("paper_endpoint_only") is True:
        if source == "SAFE_DEFAULT_PAPER_ENDPOINT":
            return f"Safe default PAPER endpoint in use: {display}"
        return f"PAPER endpoint confirmed: {display}"
    if family == "live":
        return "Live Alpaca endpoint is blocked for PAPER readiness."
    if family == "data":
        return "Alpaca data endpoint is not a trading endpoint."
    if family == "broker":
        return "Alpaca Broker API endpoint is unsupported for this PAPER seam."
    return "A valid Alpaca PAPER trading endpoint is required."


def _next_safe_action(
    *,
    blockers: list[dict[str, Any]],
    endpoint_ok: bool,
    alpaca_configured: bool,
    supervisor: dict[str, Any],
    paper_start_allowed: bool,
) -> str:
    state = str(supervisor.get("state") or "UNKNOWN").upper()
    if state == "RUNNING":
        return "Monitor the active PAPER run from Bot Runtime; do not request another start."
    if state == "STALE_ACTIVE_SESSION":
        return "Review Bot Runtime and reconcile the stale supervisor session before any new PAPER start."
    if not endpoint_ok:
        return "Fix the Alpaca endpoint in Keys & Providers; only https://paper-api.alpaca.markets is accepted."
    if not alpaca_configured:
        return "Add Alpaca PAPER key ID and secret in Keys & Providers; raw values stay hidden."
    if blockers:
        first = blockers[0]
        title = str(first.get("title") or first.get("check_id") or "the current blocker")
        return f"Resolve {title} before requesting a bounded PAPER start."
    if paper_start_allowed:
        return "Confirm PAPER-only, live locked, real-money blocked, and no manual trades before requesting Start."
    return "Review the supervisor refusal reason before trying to start PAPER."


def _broker_truth_summary(*, alpaca_configured: bool, endpoint_ok: bool, endpoint_authority: dict[str, Any]) -> dict[str, Any]:
    if not alpaca_configured:
        status = "UNAVAILABLE_MISSING_CREDENTIALS"
        label = "Broker portfolio truth unavailable"
        detail = "No broker portfolio read is attempted because Alpaca PAPER credentials are missing."
    elif not endpoint_ok:
        status = str(endpoint_authority.get("reason_code") or "PAPER_ENDPOINT_BLOCKED")
        label = "Broker portfolio truth blocked"
        detail = "No broker portfolio read is attempted until the PAPER trading endpoint is valid."
    else:
        status = "BROKER_READ_READY_NOT_IN_THIS_VIEW"
        label = "Read-only portfolio check available"
        detail = "The Portfolio Snapshot loads broker-confirmed truth separately; this readiness view does not invent positions."
    return {
        "status": status,
        "label": label,
        "detail": detail,
        "broker_confirmed": False,
        "broker_read_occurred": False,
        "broker_read_attempted": False,
        "broker_mutation_occurred": False,
        "order_submission_occurred": False,
        "cancel_occurred": False,
        "liquidation_occurred": False,
    }


def _build_run_paper_operator_state(
    *,
    checks: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    final: str,
    alpaca: dict[str, Any],
    alpaca_configured: bool,
    endpoint_authority: dict[str, Any],
    endpoint_ok: bool,
    paper_start_allowed: bool,
    safe_stop_status: str,
    supervisor: dict[str, Any],
    runtime: dict[str, Any],
    credentials: dict[str, Any],
    health: dict[str, Any],
) -> dict[str, Any]:
    blocker_codes = [str(check.get("check_id") or "unknown") for check in blockers]
    warning_codes = [str(check.get("check_id") or "unknown") for check in warnings]
    first_blocker = blockers[0] if blockers else {}
    disabled_reason = (
        _plain_check_detail(first_blocker)
        if blockers else str(supervisor.get("paper_start_refusal_reason") or "")
    )
    overall = _operator_status(
        final=final,
        blockers=blockers,
        warnings=warnings,
        supervisor=supervisor,
        paper_start_allowed=paper_start_allowed,
    )
    endpoint_source = str(endpoint_authority.get("endpoint_source") or "UNKNOWN")
    runtime_state = str(supervisor.get("state") or runtime.get("process_state") or "UNKNOWN")
    return {
        "source": "OPERATOR_LAUNCH_READINESS_DERIVED_VIEW",
        "schema_version": "run-paper-command-center-v1",
        "overall_status": overall,
        "can_run_paper": {
            "allowed": paper_start_allowed and not blockers,
            "label": "Start allowed" if paper_start_allowed and not blockers else "Start blocked",
            "reason": disabled_reason or None,
            "reason_codes": blocker_codes,
            "warning_codes": warning_codes,
            "uses_existing_governed_start_intent": "/operator/intent/paper/start",
            "requires_operator_confirmations": True,
        },
        "next_safe_action": _next_safe_action(
            blockers=blockers,
            endpoint_ok=endpoint_ok,
            alpaca_configured=alpaca_configured,
            supervisor=supervisor,
            paper_start_allowed=paper_start_allowed,
        ),
        "endpoint": {
            "label": _plain_endpoint_label(endpoint_authority),
            "display": endpoint_authority.get("alpaca_endpoint_display"),
            "family": endpoint_authority.get("alpaca_trading_endpoint_family"),
            "host": endpoint_authority.get("alpaca_trading_endpoint_host"),
            "source": endpoint_source,
            "configured": endpoint_authority.get("alpaca_endpoint_configured") is True,
            "valid": endpoint_ok,
            "status": endpoint_authority.get("status"),
            "blocker_code": endpoint_authority.get("alpaca_endpoint_blocker_code"),
            "operator_action": endpoint_authority.get("operator_action"),
        },
        "credentials": {
            "label": "Alpaca PAPER credentials configured" if alpaca_configured else "Alpaca PAPER credentials missing",
            "configured": alpaca_configured,
            "missing_fields": _missing_required_fields(alpaca),
            "source": alpaca.get("credential_source") or "NOT_CONFIGURED",
            "precedence": credentials.get("precedence") or "ENV_PRESENT_OVERRIDES_LOCAL_SECRET",
            "raw_secret_values_included": False,
            "secrets_values_exposed": False,
        },
        "runtime": {
            "label": "No active PAPER run" if runtime_state == "IDLE" else runtime_state,
            "state": runtime_state,
            "process_state": runtime.get("process_state") or "UNKNOWN",
            "active_session_id": supervisor.get("active_session_id"),
            "paper_start_refusal_reason": supervisor.get("paper_start_refusal_reason") or runtime.get("paper_start_refusal_reason"),
            "paper_stop_allowed": supervisor.get("paper_stop_allowed") is True or runtime.get("paper_stop_allowed") is True,
            "safe_stop_status": safe_stop_status,
        },
        "broker_truth": _broker_truth_summary(
            alpaca_configured=alpaca_configured,
            endpoint_ok=endpoint_ok,
            endpoint_authority=endpoint_authority,
        ),
        "safety_locks": {
            "live": {"label": "Live locked", "locked": True, "enabled": False},
            "real_money": {"label": "Real money blocked", "blocked": True, "enabled": False},
            "manual_trading": {"label": "Manual trading unavailable", "available": False},
            "force_trade": {"label": "Force trade unavailable", "available": False},
            "broker_mutation": {"label": "No broker mutation from this readiness view", "occurred": False},
        },
        "advanced": {
            "final_launch_readiness": final,
            "reason_codes": blocker_codes + warning_codes,
            "checks": checks,
            "paper_endpoint_authority": endpoint_authority,
            "paper_endpoint_display": endpoint_authority.get("alpaca_endpoint_display"),
            "paper_endpoint_family": endpoint_authority.get("alpaca_trading_endpoint_family"),
            "paper_endpoint_host": endpoint_authority.get("alpaca_trading_endpoint_host"),
            "paper_endpoint_blocker_code": endpoint_authority.get("alpaca_endpoint_blocker_code"),
            "alpaca_endpoint_configured": endpoint_authority.get("alpaca_endpoint_configured") is True,
            "alpaca_endpoint_source": endpoint_source,
            "alpaca_paper_endpoint_valid": endpoint_authority.get("alpaca_paper_endpoint_valid") is True,
            "alpaca_live_endpoint_blocked": endpoint_authority.get("alpaca_live_endpoint_blocked") is True,
            "paper_start_allowed": paper_start_allowed,
            "broker_mutation_occurred": False,
            "trading_mutation_occurred": False,
            "live_enabled": False,
            "real_money_enabled": False,
            "secrets_values_exposed": False,
            "backend_degraded_reasons": list(health.get("degraded_reasons") or []),
            "paper_start_authority_detail": _check_by_id(checks, "paper_start_authority").get("detail"),
        },
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
            str(endpoint_authority["safe_detail"]),
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
    run_paper_operator_state = _build_run_paper_operator_state(
        checks=checks,
        blockers=blockers,
        warnings=warnings,
        final=final,
        alpaca=alpaca,
        alpaca_configured=alpaca_configured,
        endpoint_authority=endpoint_authority,
        endpoint_ok=endpoint_ok,
        paper_start_allowed=paper_start_allowed,
        safe_stop_status=safe_stop_status,
        supervisor=supervisor,
        runtime=runtime,
        credentials=credentials,
        health=health,
    )
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
        "paper_endpoint_display": endpoint_authority["alpaca_endpoint_display"],
        "paper_endpoint_family": endpoint_authority["alpaca_trading_endpoint_family"],
        "paper_endpoint_host": endpoint_authority["alpaca_trading_endpoint_host"],
        "paper_endpoint_blocker_code": endpoint_authority["alpaca_endpoint_blocker_code"],
        "alpaca_endpoint_configured": endpoint_authority["alpaca_endpoint_configured"],
        "alpaca_paper_endpoint_valid": endpoint_authority["alpaca_paper_endpoint_valid"],
        "alpaca_live_endpoint_blocked": endpoint_authority["alpaca_live_endpoint_blocked"],
        "live_blocked": True,
        "real_money_blocked": True,
        "paper_start_allowed": paper_start_allowed,
        "run_paper_operator_state": run_paper_operator_state,
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
