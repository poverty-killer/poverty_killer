"""Governed operator API skeleton for the Operator Control Panel.

This module deliberately does not import or call broker, execution, OMS, or
strategy code. It exposes contract-shaped status/readiness data plus governed
PAPER process intents so the UI can be wired without becoming a second trading
engine or direct broker control surface.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, FastAPI

from app.api.operator_paper_supervisor import OperatorPaperSupervisor


API_VERSION = "operator-backend-v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


READ_ONLY_CONTRACTS: dict[str, Any] = {
    "version": API_VERSION,
    "read_only": True,
    "control_policy": {
        "ui_is_trading_engine": False,
        "manual_trading_available": False,
        "force_trade_available": False,
        "live_operation_available": False,
        "operator_actions_are_intents": True,
        "server_authority_required": True,
    },
    "endpoints": {
        "/operator/status": "read_only_runtime_status",
        "/operator/runtime": "read_only_runtime_session_summary",
        "/operator/profile": "read_only_profile_summary",
        "/operator/universe": "read_only_universe_summary",
        "/operator/readiness/live": "read_only_live_readiness_gate",
        "/operator/diagnostics": "read_only_environment_diagnostics",
        "/operator/contracts": "read_only_contract_document",
        "/operator/orders-summary": "read_only_oms_order_summary",
        "/operator/fills-summary": "read_only_fill_ledger_summary",
        "/operator/tca-summary": "read_only_tca_summary",
        "/operator/audit-summary": "read_only_audit_summary",
        "/operator/latest-run": "read_only_supervisor_session_summary",
    },
    "disabled_intents": {
        "/operator/intent/paper/start": "SERVER_AUTHORIZED_PAPER_SUPERVISOR",
        "/operator/intent/paper/stop": "SERVER_AUTHORIZED_PAPER_SUPERVISOR",
        "/operator/intent/snapshot/export": "PAPER_INTENT_NOT_IMPLEMENTED",
        "/operator/intent/live/request-enable": "LIVE_NOT_APPROVED",
        "/operator/intent/live/start": "LIVE_NOT_APPROVED",
        "/operator/intent/emergency-stop": "EMERGENCY_STOP_INTENT_NOT_IMPLEMENTED",
    },
    "truth_labels": {
        "broker_confirmed": "Canonical only after broker acknowledgement/reconciliation.",
        "local_diagnostic": "Diagnostic evidence only; not broker authority.",
        "estimated": "Non-authoritative estimate and visually labeled as such.",
        "unknown": "Truth unavailable; UI must not invent it.",
    },
}


class OperatorSnapshotProvider:
    """Contract-shaped, safe-default provider for the operator API.

    Future seams can replace these safe defaults with a read-only runtime
    snapshot reader. This class intentionally has no broker, engine, or OMS
    dependency. If a supervisor is supplied, it can start/track governed bounded
    PAPER processes through the existing launch script only.
    """

    def __init__(self, supervisor: OperatorPaperSupervisor | None = None) -> None:
        self.supervisor = supervisor or OperatorPaperSupervisor()

    def status(self) -> dict[str, Any]:
        supervisor = self.supervisor.status_snapshot()
        active = supervisor.get("active_session") or {}
        session_status = active.get("status")
        active_profile = active.get("profile") or "UNKNOWN_NO_ACTIVE_RUNTIME"
        watchlist = active.get("watchlist") or []
        process_state = session_status or "NO_ACTIVE_RUNTIME_ATTACHED"
        return {
            "api_version": API_VERSION,
            "data_source": "OPERATOR_BACKEND",
            "bot_status": process_state,
            "runtime_mode": "PAPER",
            "mode_state": "PAPER_ENABLED",
            "capability_state": "PAPER_ENABLED",
            "active_profile": active_profile,
            "broker": "alpaca_paper" if watchlist else "UNKNOWN_NO_ACTIVE_RUNTIME",
            "endpoint": "https://paper-api.alpaca.markets" if watchlist else "UNKNOWN_NO_ACTIVE_RUNTIME",
            "market_data": "UNKNOWN_NO_ACTIVE_RUNTIME",
            "universe": watchlist,
            "asset_classes": ["crypto"] if watchlist else [],
            "last_heartbeat_ts": None,
            "dominant_blocker": "NO_ACTIVE_RUNTIME_ATTACHED" if not watchlist else "SUPERVISOR_PROCESS_RUNNING_OR_RECENT",
            "safety_verdict": "OPERATOR_SUPERVISOR_READY",
            "live_blocked": True,
            "real_money_blocked": True,
            "broker_post_count": 0,
            "broker_delete_count": 0,
            "mutation_authorized_count": 0,
            "manual_trading_available": False,
            "force_trade_available": False,
            "supervisor": supervisor,
            "updated_at": _utc_now(),
        }

    def runtime(self) -> dict[str, Any]:
        supervisor = self.supervisor.status_snapshot()
        latest = supervisor.get("latest_session") or {}
        return {
            "process_state": latest.get("status") or "NO_ACTIVE_RUNTIME_ATTACHED",
            "launch_command": latest.get("command_summary"),
            "duration_seconds": latest.get("duration_seconds"),
            "started_at": latest.get("started_at"),
            "shutdown_reason": latest.get("stop_reason"),
            "bounded_timer_started": bool(latest),
            "bounded_duration_elapsed": latest.get("status") in {"EXITED", "STOPPED"},
            "runtime_commit": None,
            "session_id": latest.get("session_id"),
            "pid": latest.get("pid"),
            "stdout_path": latest.get("stdout_path"),
            "stderr_path": latest.get("stderr_path"),
            "exit_code": latest.get("exit_code"),
            "supervisor_state": supervisor["state"],
            "duplicate_run_prevention": "ACTIVE",
            "paper_start_allowed": supervisor["paper_start_allowed"],
            "paper_stop_allowed": supervisor["paper_stop_allowed"],
            "paper_start_refusal_reason": supervisor["paper_start_refusal_reason"],
            "paper_stop_refusal_reason": supervisor["paper_stop_refusal_reason"],
        }

    def profile(self) -> dict[str, Any]:
        supervisor = self.supervisor.status_snapshot()
        latest = supervisor.get("latest_session") or {}
        profile = latest.get("profile") or "UNKNOWN_NO_ACTIVE_RUNTIME"
        return {
            "active_threshold_profile": profile,
            "paper_exploration_alpha_active": profile == "PAPER_EXPLORATION_ALPHA",
            "paper_only": True,
            "activation_status": latest.get("status") or "NO_ACTIVE_RUNTIME_ATTACHED",
            "activation_refusal_reason": None,
        }

    def universe(self) -> dict[str, Any]:
        supervisor = self.supervisor.status_snapshot()
        active = supervisor.get("active_session") or {}
        symbols = active.get("watchlist") or []
        return {
            "symbols": symbols,
            "asset_classes": ["crypto"] if symbols else [],
            "venues": ["alpaca"] if symbols else [],
            "runtime_watchlist": symbols,
            "universe_source": "OPERATOR_SUPERVISOR_SESSION" if symbols else "NO_ACTIVE_RUNTIME_ATTACHED",
            "excluded_symbols": [],
            "exclusion_reason_codes": [],
        }

    def diagnostics(self) -> dict[str, Any]:
        return {
            "api_version": API_VERSION,
            "data_source": "OPERATOR_BACKEND",
            "git_commit": "UNKNOWN_NOT_INSPECTED",
            "dirty_worktree": "UNKNOWN_NOT_INSPECTED",
            "python_version": "UNKNOWN_NOT_INSPECTED",
            "credentials_present": "NOT_INSPECTED_NO_SECRET_ACCESS",
            "logs": "NOT_READ_BY_OPERATOR_BACKEND_V1",
            "db": "NOT_READ_BY_OPERATOR_BACKEND_V1",
            "legacy_dashboard_command_routes_present": True,
            "legacy_dashboard_reuse_allowed": False,
            "supervisor_version": self.supervisor.status_snapshot().get("supervisor_version"),
        }

    def live_readiness(self) -> dict[str, Any]:
        return {
            "live_status": "LIVE_LOCKED",
            "refusal_reason": "LIVE_NOT_APPROVED",
            "broker_endpoint_authority": "PAPER_ONLY_FOR_CURRENT_OPERATOR_API",
            "credential_authority": "NOT_INSPECTED_NO_SECRET_ACCESS",
            "real_money_authority": "BLOCKED",
            "physical_fuse": "REQUIRED_BEFORE_LIVE",
            "risk_governor_status": "REQUIRED_BEFORE_LIVE",
            "account_status": "REQUIRED_BEFORE_LIVE",
            "position_reconciliation": "REQUIRED_BEFORE_LIVE",
            "order_reconciliation": "REQUIRED_BEFORE_LIVE",
            "fill_ledger_health": "REQUIRED_BEFORE_LIVE",
            "tca_status": "REQUIRED_BEFORE_LIVE",
            "market_truth_health": "REQUIRED_BEFORE_LIVE",
            "kill_switch_status": "REQUIRED_BEFORE_LIVE",
            "audit_logging_status": "REQUIRED_BEFORE_LIVE",
            "operator_approval_status": "NOT_APPROVED",
            "dirty_worktree_warning": "UNKNOWN_NOT_INSPECTED",
            "current_git_commit": "UNKNOWN_NOT_INSPECTED",
            "pushed_commit_match": "UNKNOWN_NOT_INSPECTED",
            "missing_prerequisites": [
                "separate_live_governance_packet",
                "server_side_live_authority",
                "live_endpoint_authority",
                "real_money_authority",
                "risk_governor_live_approval",
                "operator_approval",
                "live_readiness_audit",
            ],
            "passed_prerequisites": [],
            "authority_chain": [
                "UI intent only",
                "operator backend authority",
                "supervisor authority",
                "engine authority",
                "broker boundary authority",
            ],
            "last_live_readiness_audit": None,
        }

    def orders_summary(self) -> dict[str, Any]:
        return {
            "source": "NO_ACTIVE_RUNTIME_ATTACHED",
            "broker_confirmed_open_orders": 0,
            "local_open_without_broker_match_count": 0,
            "terminal_orders": 0,
            "reconciliation_conflicts": 0,
            "broker_truth_canonical": True,
        }

    def fills_summary(self) -> dict[str, Any]:
        return {
            "source": "NO_ACTIVE_RUNTIME_ATTACHED",
            "local_fills": 0,
            "broker_fill_ledger_rows": 0,
            "fill_hydration_count": 0,
            "fill_hydration_missing_count": 0,
            "fill_hydration_conflict_count": 0,
            "fake_fills_allowed": False,
        }

    def tca_summary(self) -> dict[str, Any]:
        return {
            "source": "NO_ACTIVE_RUNTIME_ATTACHED",
            "tca_records_count": 0,
            "tca_unknown_count": 0,
            "execution_quality_verdict": "UNKNOWN_NO_ACTIVE_RUNTIME",
            "fake_fees_allowed": False,
            "fake_tca_allowed": False,
        }

    def audit_summary(self) -> dict[str, Any]:
        supervisor = self.supervisor.status_snapshot()
        last_event = supervisor.get("last_audit_event")
        return {
            "source": "OPERATOR_SUPERVISOR_MEMORY",
            "operator_action_count": supervisor.get("audit_event_count", 0),
            "broker_mutation_count": 0,
            "live_refusal_count": 1 if last_event and last_event.get("reason_code") == "LIVE_NOT_APPROVED" else 0,
            "last_event": last_event,
        }

    def contracts(self) -> dict[str, Any]:
        return deepcopy(READ_ONLY_CONTRACTS)

    def latest_run(self) -> dict[str, Any]:
        return self.supervisor.status_snapshot()

    def refused_intent(self, intent_name: str, reason: str) -> dict[str, Any]:
        return self.supervisor.generic_refusal(intent_name, reason)

    def paper_start_intent(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.supervisor.start_paper(payload or {})

    def paper_stop_intent(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.supervisor.stop_paper(payload or {})

    def live_refusal_intent(self, intent_name: str) -> dict[str, Any]:
        return self.supervisor.live_refusal(intent_name)


def get_operator_router(provider: OperatorSnapshotProvider | None = None) -> APIRouter:
    provider = provider or OperatorSnapshotProvider()
    router = APIRouter(prefix="/operator", tags=["operator-readonly"])

    @router.get("/status")
    def status() -> dict[str, Any]:
        return provider.status()

    @router.get("/runtime")
    def runtime() -> dict[str, Any]:
        return provider.runtime()

    @router.get("/profile")
    def profile() -> dict[str, Any]:
        return provider.profile()

    @router.get("/universe")
    def universe() -> dict[str, Any]:
        return provider.universe()

    @router.get("/readiness/live")
    def live_readiness() -> dict[str, Any]:
        return provider.live_readiness()

    @router.get("/diagnostics")
    def diagnostics() -> dict[str, Any]:
        return provider.diagnostics()

    @router.get("/contracts")
    def contracts() -> dict[str, Any]:
        return provider.contracts()

    @router.get("/orders-summary")
    def orders_summary() -> dict[str, Any]:
        return provider.orders_summary()

    @router.get("/fills-summary")
    def fills_summary() -> dict[str, Any]:
        return provider.fills_summary()

    @router.get("/tca-summary")
    def tca_summary() -> dict[str, Any]:
        return provider.tca_summary()

    @router.get("/audit-summary")
    def audit_summary() -> dict[str, Any]:
        return provider.audit_summary()

    @router.get("/latest-run")
    def latest_run() -> dict[str, Any]:
        return provider.latest_run()

    @router.post("/intent/paper/start")
    def paper_start_intent(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return provider.paper_start_intent(payload)

    @router.post("/intent/paper/stop")
    def paper_stop_intent(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return provider.paper_stop_intent(payload)

    @router.post("/intent/snapshot/export")
    def snapshot_export_intent() -> dict[str, Any]:
        return provider.refused_intent("snapshot_export", "PAPER_INTENT_NOT_IMPLEMENTED")

    @router.post("/intent/live/request-enable")
    def live_request_enable_intent() -> dict[str, Any]:
        return provider.live_refusal_intent("live_request_enable")

    @router.post("/intent/live/start")
    def live_start_intent() -> dict[str, Any]:
        return provider.live_refusal_intent("live_start")

    @router.post("/intent/emergency-stop")
    def emergency_stop_intent() -> dict[str, Any]:
        return provider.refused_intent("emergency_stop", "EMERGENCY_STOP_INTENT_NOT_IMPLEMENTED")

    return router


def create_operator_app(provider: OperatorSnapshotProvider | None = None) -> FastAPI:
    app = FastAPI(title="Poverty Killer Operator Read-Only API", version=API_VERSION)
    app.include_router(get_operator_router(provider))
    return app


__all__ = [
    "API_VERSION",
    "OperatorSnapshotProvider",
    "READ_ONLY_CONTRACTS",
    "create_operator_app",
    "get_operator_router",
]
