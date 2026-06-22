"""Launch-readiness summary for governed bounded PAPER runs."""

from __future__ import annotations

from typing import Any

from app.operator_credentials.store import DEFAULT_RELATIVE_STORE_PATH, alpaca_endpoint_authority
from app.operator_activation.paper_baseline import (
    BASELINE_POLICY_PROTECTED,
    PREFLIGHT_READY_WITH_ACCEPTED_EXISTING_POSITIONS,
    build_baseline_adoption_state,
)


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


def _credential_field_setup_rows(provider: dict[str, Any]) -> list[dict[str, Any]]:
    required = [str(name) for name in provider.get("required_env_vars") or ["APCA_API_KEY_ID", "APCA_API_SECRET_KEY"]]
    rows = provider.get("env_status") if isinstance(provider.get("env_status"), list) else []
    by_name = {
        str(row.get("name")): row
        for row in rows
        if isinstance(row, dict) and str(row.get("name") or "").strip()
    }
    return [
        {
            "name": name,
            "present": by_name.get(name, {}).get("configured") is True,
            "display_value": "present" if by_name.get(name, {}).get("configured") is True else "missing",
            "source": str(by_name.get(name, {}).get("source") or "NOT_CONFIGURED"),
            "raw_value_exposed": False,
        }
        for name in required
    ]


def _paper_credential_setup_status(
    *,
    field_rows: list[dict[str, Any]],
    endpoint_ok: bool,
    endpoint_authority: dict[str, Any],
) -> dict[str, str]:
    present_count = sum(1 for row in field_rows if row.get("present") is True)
    required_count = len(field_rows)
    if not endpoint_ok:
        return {
            "code": "ERROR",
            "label": "PAPER endpoint blocked",
            "severity": "blocked",
            "detail": str(endpoint_authority.get("safe_detail") or "A valid Alpaca PAPER endpoint is required."),
        }
    if present_count == 0:
        return {
            "code": "MISSING",
            "label": "PAPER credentials missing",
            "severity": "blocked",
            "detail": "PAPER credentials missing - add Alpaca PAPER credentials through the approved local secret path.",
        }
    if present_count < required_count:
        missing = [str(row.get("name")) for row in field_rows if row.get("present") is not True]
        return {
            "code": "PARTIAL",
            "label": "PAPER credentials incomplete",
            "severity": "blocked",
            "detail": f"Missing required PAPER credential field: {', '.join(missing)}.",
        }
    return {
        "code": "PRESENT_NOT_PREFLIGHTED",
        "label": "PAPER credentials present; preflight not run",
        "severity": "warning",
        "detail": "Credential presence is confirmed locally, but read-only Alpaca PAPER preflight has not run.",
    }


def _preflight_gate_status(*, alpaca_configured: bool, endpoint_ok: bool) -> str:
    if not alpaca_configured or not endpoint_ok:
        return "blocked"
    return "ready_to_run_after_approval"


def _first_blocker_detail(checks: list[dict[str, Any]]) -> str | None:
    for check in checks:
        if check.get("blocker") is True:
            return _plain_check_detail(check)
    return None


def _plain_check_detail(check: dict[str, Any]) -> str:
    check_id = str(check.get("check_id") or "")
    if check_id == "alpaca_paper_credentials":
        detail = str(check.get("detail") or "")
        if detail.startswith("Missing required Alpaca PAPER credential field"):
            return detail
        return "Alpaca PAPER key ID and secret are missing."
    if check_id == "paper_endpoint_only":
        return str(check.get("detail") or "Only the Alpaca PAPER trading endpoint is accepted.")
    if check_id == "paper_read_only_preflight_gate":
        return "Read-only Alpaca PAPER preflight has not run and requires explicit Shan approval before Alpaca is called."
    if check_id == "paper_existing_position_baseline":
        return "Existing PAPER positions require protected baseline adoption before PAPER can start."
    if check_id == "paper_baseline_position_aware_policy":
        return "Position-aware PAPER baseline is accepted; this is short-smoke readiness, not 72-hour readiness."
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
        return "Open Keys & Providers and save Alpaca PAPER key ID and secret to the local credential vault; do not paste secrets into chat or commit them."
    if any(str(check.get("check_id") or "") == "paper_read_only_preflight_gate" for check in blockers):
        return "Do not start PAPER; request explicit Shan approval for read-only Alpaca account, open-orders, and positions preflight first."
    if any(str(check.get("check_id") or "") == "paper_existing_position_baseline" for check in blockers):
        return "Accept current PAPER positions as the protected starting baseline before a short position-aware PAPER smoke packet."
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


def _build_paper_credential_setup(
    *,
    alpaca: dict[str, Any],
    alpaca_configured: bool,
    endpoint_authority: dict[str, Any],
    endpoint_ok: bool,
    paper_start_allowed: bool,
    paper_baseline_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    field_rows = _credential_field_setup_rows(alpaca)
    missing = [str(row.get("name")) for row in field_rows if row.get("present") is not True]
    setup_status = _paper_credential_setup_status(
        field_rows=field_rows,
        endpoint_ok=endpoint_ok,
        endpoint_authority=endpoint_authority,
    )
    preflight_status = _preflight_gate_status(alpaca_configured=alpaca_configured, endpoint_ok=endpoint_ok)
    preflight_detail = (
        "Read-only preflight is blocked until Alpaca PAPER credentials and a PAPER trading endpoint are present."
        if preflight_status == "blocked"
        else "Read-only preflight is ready to request after explicit Shan approval; no Alpaca call has occurred in this view."
    )
    baseline_state = paper_baseline_state or {}
    baseline_ready = baseline_state.get("status") == PREFLIGHT_READY_WITH_ACCEPTED_EXISTING_POSITIONS
    if baseline_ready:
        preflight_status = "accepted_existing_positions"
        preflight_detail = "Read-only PAPER preflight is represented by an accepted protected existing-position baseline."
        setup_status = {
            "code": "PREFLIGHT_READY",
            "label": "Position-aware PAPER baseline accepted",
            "severity": "warning",
            "detail": "Credential presence and protected existing-position baseline are confirmed; this is short-smoke readiness, not 72-hour readiness.",
        }
    return {
        "source": "OPERATOR_LAUNCH_READINESS_DERIVED_VIEW",
        "schema_version": "paper-credential-setup-v1",
        "overall_status": setup_status,
        "required_credentials": field_rows,
        "missing_fields": missing,
        "values_hidden": True,
        "endpoint": {
            "display": endpoint_authority.get("alpaca_endpoint_display"),
            "family": endpoint_authority.get("alpaca_trading_endpoint_family"),
            "host": endpoint_authority.get("alpaca_trading_endpoint_host"),
            "source": "safe_default" if endpoint_authority.get("endpoint_source") == "SAFE_DEFAULT_PAPER_ENDPOINT" else "configured",
            "configured": endpoint_authority.get("alpaca_endpoint_configured") is True,
            "paper_endpoint_valid": endpoint_ok,
            "live_endpoint_blocked": endpoint_authority.get("alpaca_live_endpoint_blocked") is True,
            "blocker_code": endpoint_authority.get("alpaca_endpoint_blocker_code"),
        },
        "approved_secret_path": {
            "label": "Keys & Providers -> Alpaca PAPER Broker/Data -> Save local credentials",
            "storage_type": "operator_secret_file",
            "relative_path": DEFAULT_RELATIVE_STORE_PATH,
            "credential_precedence": "ENV_PRESENT_OVERRIDES_LOCAL_SECRET",
            "gitignored": True,
            "safe_instruction": (
                "Open Keys & Providers, enter APCA_API_KEY_ID and APCA_API_SECRET_KEY for Alpaca PAPER Broker/Data, "
                "then save local credentials. Values stay local and hidden."
            ),
            "forbidden_instruction": (
                "Do not paste credentials into chat, do not commit .env files, and do not put raw secrets in tracked files."
            ),
        },
        "preflight_gate": {
            "read_only_preflight_authorized": baseline_ready,
            "read_only_preflight_available": baseline_ready or preflight_status == "ready_to_run_after_approval",
            "account_check_status": preflight_status,
            "open_orders_check_status": preflight_status,
            "positions_check_status": preflight_status,
            "last_preflight_at": baseline_state.get("accepted_at") if baseline_ready else None,
            "last_preflight_result": baseline_state.get("status") if baseline_ready else None,
            "status_label": "Position-aware PAPER baseline accepted" if baseline_ready else "Read-only PAPER preflight not run",
            "detail": preflight_detail,
            "explicit_approval_required": not baseline_ready,
            "future_checks": ["GET /v2/account", "GET /v2/orders?status=open", "GET /v2/positions"],
            "alpaca_network_call_occurred": False,
            "account_request_occurred": False,
            "open_orders_request_occurred": False,
            "positions_request_occurred": False,
            "broker_mutation_occurred": False,
            "order_submission_occurred": False,
            "cancel_occurred": False,
            "replace_occurred": False,
            "liquidation_occurred": False,
        },
        "baseline_adoption": baseline_state or {
            "source": "OPERATOR_PAPER_BASELINE",
            "status": "NOT_ACCEPTED",
            "accepted": False,
            "policy": BASELINE_POLICY_PROTECTED,
            "broker_mutation_occurred": False,
            "alpaca_network_call_occurred": False,
            "secrets_values_exposed": False,
        },
        "next_safe_action": (
            "Open Keys & Providers and save Alpaca PAPER credentials locally; never paste secrets into chat or tracked files."
            if not alpaca_configured
            else (
                str(baseline_state.get("next_safe_action"))
                if baseline_ready and baseline_state.get("next_safe_action")
                else "Request explicit Shan approval for read-only Alpaca PAPER preflight before any account, open-orders, or positions request."
            )
        ),
        "safety": {
            "paper_start_allowed": paper_start_allowed,
            "live_enabled": False,
            "real_money_enabled": False,
            "broker_mutation_occurred": False,
            "secrets_values_exposed": False,
            "raw_secret_values_included": False,
        },
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
    paper_baseline_state: dict[str, Any] | None = None,
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
    credential_setup = _build_paper_credential_setup(
        alpaca=alpaca,
        alpaca_configured=alpaca_configured,
        endpoint_authority=endpoint_authority,
        endpoint_ok=endpoint_ok,
        paper_start_allowed=paper_start_allowed and not blockers,
        paper_baseline_state=paper_baseline_state,
    )
    baseline_runtime_context = (
        supervisor.get("paper_baseline_runtime_context")
        if isinstance(supervisor.get("paper_baseline_runtime_context"), dict)
        else {}
    )
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
        "paper_credential_setup": credential_setup,
        "paper_baseline": paper_baseline_state or credential_setup["baseline_adoption"],
        "stale_reconciliation": supervisor.get("stale_reconciliation") or {},
        "paper_baseline_runtime_context": baseline_runtime_context,
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
            "launch_readiness_start_allowed": paper_start_allowed and not blockers,
            "paper_credential_setup": credential_setup,
            "paper_baseline": paper_baseline_state or credential_setup["baseline_adoption"],
            "paper_baseline_runtime_context": baseline_runtime_context,
            "baseline_context_required": baseline_runtime_context.get("baseline_required") is True,
            "baseline_context_will_be_loaded": baseline_runtime_context.get("baseline_loaded") is True,
            "protected_same_symbol_guard_active": baseline_runtime_context.get("same_symbol_baseline_guard_active") is True,
            "protected_symbols_count": int(baseline_runtime_context.get("protected_symbols_count") or 0),
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
    paper_baseline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    alpaca = _find_provider(provider_readiness, "alpaca_paper")
    alpaca_configured = bool(alpaca.get("configured"))
    alpaca_missing_fields = _missing_required_fields(alpaca)
    if len(alpaca_missing_fields) == 1:
        alpaca_detail = f"Missing required Alpaca PAPER credential field: {alpaca_missing_fields[0]}."
    else:
        alpaca_detail = "Alpaca PAPER key ID and secret are missing."
    checks.append(
        _check(
            "alpaca_paper_credentials",
            "Alpaca PAPER credentials",
            "PASS" if alpaca_configured else "BLOCKED",
            "configured through env/local secret store" if alpaca_configured else alpaca_detail,
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

    paper_baseline_state = build_baseline_adoption_state(accepted_baseline=paper_baseline)
    baseline_ready = paper_baseline_state.get("status") == PREFLIGHT_READY_WITH_ACCEPTED_EXISTING_POSITIONS
    preflight_gate_open = alpaca_configured and endpoint_ok
    if baseline_ready:
        checks.append(
            _check(
                "paper_existing_position_baseline",
                "Existing-position PAPER baseline",
                "PASS",
                "Protected existing-position baseline accepted; existing inventory remains visible and protected.",
            )
        )
        checks.append(
            _check(
                "paper_baseline_position_aware_policy",
                "Position-aware baseline policy",
                "DEGRADED",
                "Short PAPER smoke readiness only. Existing-position symbols are protected until run lot tracking is available.",
                warning=True,
            )
        )
    else:
        checks.append(
            _check(
                "paper_read_only_preflight_gate",
                "Read-only PAPER preflight",
                "BLOCKED",
                (
                    "Read-only Alpaca PAPER account, open-orders, and positions preflight has not run. "
                    "It requires explicit Shan approval before Alpaca is called."
                ) if preflight_gate_open else (
                    "Read-only Alpaca PAPER preflight is blocked until credentials and the PAPER trading endpoint are present."
                ),
                blocker=preflight_gate_open,
                warning=not preflight_gate_open,
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
    launch_paper_start_allowed = paper_start_allowed and not blockers
    run_paper_operator_state = _build_run_paper_operator_state(
        checks=checks,
        blockers=blockers,
        warnings=warnings,
        final=final,
        alpaca=alpaca,
        alpaca_configured=alpaca_configured,
        endpoint_authority=endpoint_authority,
        endpoint_ok=endpoint_ok,
        paper_start_allowed=launch_paper_start_allowed,
        safe_stop_status=safe_stop_status,
        supervisor=supervisor,
        runtime=runtime,
        credentials=credentials,
        health=health,
        paper_baseline_state=paper_baseline_state,
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
        "paper_start_allowed": launch_paper_start_allowed,
        "run_paper_operator_state": run_paper_operator_state,
        "paper_credential_setup": run_paper_operator_state["paper_credential_setup"],
        "paper_baseline_runtime_context": run_paper_operator_state.get("paper_baseline_runtime_context") or {},
        "baseline_context_required": (run_paper_operator_state.get("paper_baseline_runtime_context") or {}).get("baseline_required") is True,
        "baseline_context_will_be_loaded": (run_paper_operator_state.get("paper_baseline_runtime_context") or {}).get("baseline_loaded") is True,
        "protected_same_symbol_guard_active": (run_paper_operator_state.get("paper_baseline_runtime_context") or {}).get("same_symbol_baseline_guard_active") is True,
        "protected_symbols_count": int((run_paper_operator_state.get("paper_baseline_runtime_context") or {}).get("protected_symbols_count") or 0),
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
