"""Governed operator API skeleton for the Operator Control Panel.

This module deliberately does not import or call broker, execution, OMS, or
strategy code. It exposes contract-shaped status/readiness data plus governed
PAPER process intents so the UI can be wired without becoming a second trading
engine or direct broker control surface.
"""

from __future__ import annotations

import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.staticfiles import StaticFiles

from app.ai_chief_operator.config import AIChiefConfig
from app.ai_chief_operator.context_builder import build_ai_context, redact_secrets
from app.ai_chief_operator.governance_queue import GovernanceQueue
from app.ai_chief_operator.models import normalize_recommendation
from app.ai_chief_operator.provider_gateway import AIProviderGateway
from app.ai_chief_operator.quant_persona import draft_codex_packet, build_quant_review_recommendation, quant_persona_summary
from app.operator_activation.launch_readiness import build_launch_readiness
from app.api.operator_paper_supervisor import OperatorPaperSupervisor, PaperSupervisorConfig
from app.api.operator_runtime_config import OperatorRuntimeConfig
from app.operator_credentials.store import LocalCredentialStore, default_credential_store_path
from app.operator_intelligence.action_center import build_action_center
from app.operator_intelligence.archive import RunArchive
from app.operator_intelligence.decision_explainer import DecisionExplainer
from app.operator_intelligence.pnl_tca import build_pnl_summary, build_tca_dashboard
from app.operator_intelligence.reports import RunReportGenerator
from app.operator_intelligence.system_map import SYSTEM_MAP_SUMMARY, render_system_map_markdown
from app.operator_intelligence.watchdog import AlertQueue, build_watchdog_alerts
from app.operator_portfolio.snapshot import ReadOnlyBrokerClient, build_portfolio_snapshot
from app.operator_providers.readiness import provider_readiness_summary, validate_provider_readonly
from app.operator_research.evidence_graph import build_evidence_graph
from app.operator_research.registry import ResearchRegistry
from app.world_awareness.config import WorldAwarenessConfig
from app.world_awareness.feed_spine import WorldAwarenessEventCache
from app.world_awareness.persistent_cache import PersistentWorldAwarenessEventCache
from app.world_awareness.scheduler import WorldAwarenessProviderRuntime


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
        "/operator/health": "read_only_operator_health",
        "/operator/readiness": "read_only_operator_readiness",
        "/operator/storage": "read_only_operator_storage_status",
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
        "/operator/world-awareness": "read_only_external_intelligence_advisory_summary",
        "/operator/world-awareness/providers": "read_only_external_intelligence_provider_health",
        "/operator/world-awareness/events": "read_only_external_intelligence_events",
        "/operator/world-awareness/runtime": "read_only_external_intelligence_provider_runtime",
        "/operator/latest-run": "read_only_supervisor_session_summary",
        "/operator/runs": "read_only_run_archive",
        "/operator/runs/{run_id}": "read_only_run_archive_detail",
        "/operator/runs/{run_id}/report": "read_only_or_generate_operator_run_report",
        "/operator/explain/latest": "read_only_decision_explainer",
        "/operator/explain/decision/{frame_id}": "read_only_decision_explainer_by_frame",
        "/operator/action-center": "read_only_operator_action_center",
        "/operator/pnl": "read_only_pnl_truth_summary",
        "/operator/tca": "read_only_tca_execution_quality_dashboard",
        "/operator/alerts": "read_only_watchdog_alerts",
        "/operator/system-map": "read_only_system_map_summary",
        "/operator/ai/status": "read_only_ai_chief_status",
        "/operator/ai/recommendations": "read_only_ai_governance_queue",
        "/operator/ai/analyze": "advisory_ai_analysis_governance_queue_only",
        "/operator/providers": "read_only_provider_setup_and_credential_readiness",
        "/operator/providers/readiness": "read_only_provider_readiness_summary",
        "/operator/providers/validate-readonly": "read_only_env_presence_validation_only",
        "/operator/credentials/providers": "read_only_local_credential_provider_status",
        "/operator/credentials/save": "local_secret_store_update_only",
        "/operator/credentials/validate-readonly": "read_only_local_credential_validation_only",
        "/operator/credentials/provider/{provider_id}": "local_secret_store_delete_only",
        "/operator/portfolio": "read_only_paper_portfolio_summary",
        "/operator/positions": "read_only_paper_positions",
        "/operator/orders/open": "read_only_open_orders",
        "/operator/positions/intelligence": "read_only_position_intelligence",
        "/operator/launch-readiness": "read_only_bounded_paper_launch_readiness",
        "/operator/research": "advisory_research_registry",
        "/operator/research/hypotheses": "advisory_research_hypothesis_queue_only",
        "/operator/research/experiments": "advisory_research_experiment_queue_only",
        "/operator/research/evidence-graph": "read_only_research_evidence_graph",
        "/operator/ai/quant-review": "advisory_ai_quant_research_review",
        "/operator/ai/draft-codex-packet": "advisory_ai_codex_packet_draft",
        "/operator/ai/recommendations/{id}/approve-paper-research": "governance_queue_paper_research_approval_only",
        "/operator/ai/recommendations/{id}/reject": "governance_queue_reject_only",
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

    def __init__(
        self,
        supervisor: OperatorPaperSupervisor | None = None,
        *,
        runtime_config: OperatorRuntimeConfig | None = None,
        world_awareness_cache: WorldAwarenessEventCache | None = None,
        world_awareness_config: WorldAwarenessConfig | None = None,
        world_awareness_env: dict[str, str] | None = None,
        world_awareness_runtime: WorldAwarenessProviderRuntime | None = None,
        decision_frames: list[dict[str, Any]] | None = None,
        ai_config: AIChiefConfig | None = None,
        ai_queue: GovernanceQueue | None = None,
        research_registry: ResearchRegistry | None = None,
        provider_env: dict[str, str] | None = None,
        credential_store: LocalCredentialStore | None = None,
        portfolio_client: ReadOnlyBrokerClient | None = None,
    ) -> None:
        self.runtime_config = runtime_config or OperatorRuntimeConfig.from_env()
        self.process_env = provider_env if provider_env is not None else dict(os.environ)
        self.credential_store = credential_store or LocalCredentialStore(
            default_credential_store_path(self.runtime_config.repo_root)
        )
        self.provider_env = self.credential_store.effective_env(self.process_env)
        self.portfolio_client = portfolio_client
        supervisor_config = PaperSupervisorConfig.from_runtime_config(self.runtime_config)
        supervisor_config.process_env = self._paper_process_env()
        self.supervisor = supervisor or OperatorPaperSupervisor(config=supervisor_config)
        self.supervisor.config.process_env = self._paper_process_env()
        self.world_awareness_env = world_awareness_env if world_awareness_env is not None else dict(self.provider_env)
        if world_awareness_runtime is not None:
            self.world_awareness_runtime = world_awareness_runtime
            self.world_awareness_cache = world_awareness_runtime.cache
            self.world_awareness_config = world_awareness_runtime.config
            self.world_awareness_env = dict(world_awareness_runtime.env)
        else:
            self.world_awareness_cache = world_awareness_cache or PersistentWorldAwarenessEventCache(
                max_events=self.runtime_config.max_event_cache,
                path=self.runtime_config.world_awareness_cache_path,
            )
            self.world_awareness_config = world_awareness_config or WorldAwarenessConfig()
            self.world_awareness_runtime = WorldAwarenessProviderRuntime(
                config=self.world_awareness_config,
                cache=self.world_awareness_cache,
                env=self.world_awareness_env,
            )
        self.report_dir = self.runtime_config.operator_state_dir / "reports"
        self.run_archive = RunArchive(
            session_store=self.supervisor.session_store,
            repo_root=self.runtime_config.repo_root,
            report_dir=self.report_dir,
        )
        self.report_generator = RunReportGenerator(report_dir=self.report_dir)
        self.decision_explainer = DecisionExplainer(decision_frames)
        self.alert_queue = AlertQueue()
        self.ai_gateway = AIProviderGateway(ai_config or AIChiefConfig.from_env(self.provider_env))
        self.ai_queue = ai_queue or GovernanceQueue(
            path=self.runtime_config.operator_state_dir / "ai_governance_queue.jsonl"
        )
        self.research_registry = research_registry or ResearchRegistry()

    def _paper_process_env(self) -> dict[str, str]:
        return {
            key: str(value)
            for key, value in self.provider_env.items()
            if key in {"APCA_API_KEY_ID", "APCA_API_SECRET_KEY", "APCA_API_BASE_URL"} and str(value).strip()
        }

    def _alpaca_paper_configured(self) -> bool:
        summary = self.credential_store.provider_summary("alpaca_paper", self.process_env)
        return bool(summary["configured"])

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

    def health(self) -> dict[str, Any]:
        supervisor = self.supervisor.status_snapshot()
        storage = self.storage()
        config_status = self.runtime_config.status()
        world_runtime = self.world_awareness_runtime.status_snapshot()
        degraded_reasons: list[str] = []
        if storage["session_store"]["status"] != "READY":
            degraded_reasons.append("SESSION_STORE_DEGRADED")
        if storage["world_awareness_cache"]["status"] != "READY":
            degraded_reasons.append("WORLD_AWARENESS_CACHE_DEGRADED")
        if config_status["warnings"]:
            degraded_reasons.extend(str(item) for item in config_status["warnings"])
        return {
            "api_status": "DEGRADED" if degraded_reasons else "OK",
            "supervisor_status": supervisor["state"],
            "session_store_status": storage["session_store"]["status"],
            "world_awareness_cache_status": storage["world_awareness_cache"]["status"],
            "config_status": config_status["status"],
            "log_dir_status": storage["log_dir"]["status"],
            "data_dir_status": storage["data_dir"]["status"],
            "runtime_profile": self.runtime_config.runtime_profile,
            "hosted_mode": self.runtime_config.hosted_mode,
            "live_status": "LIVE_LOCKED",
            "real_money_status": "BLOCKED",
            "broker_call_occurred": False,
            "secrets_values_exposed": False,
            "degraded_reasons": degraded_reasons,
            "world_awareness_runtime": {
                "manual_poll_only": world_runtime.get("manual_poll_only"),
                "provider_polling_active": world_runtime.get("provider_polling_active"),
                "provider_count": world_runtime.get("provider_count"),
            },
            "updated_at": _utc_now(),
        }

    def readiness(self) -> dict[str, Any]:
        health = self.health()
        missing: list[str] = []
        warnings: list[str] = list(health.get("degraded_reasons") or [])
        if not self._alpaca_paper_configured():
            missing.append("APCA_PAPER_CREDENTIALS_NOT_CONFIGURED")
        if health["session_store_status"] != "READY":
            missing.append("SESSION_STORE_NOT_READY")
        if health["world_awareness_cache_status"] != "READY":
            missing.append("WORLD_AWARENESS_CACHE_NOT_READY")
        local_paper_ready = not missing and health["api_status"] in {"OK", "DEGRADED"}
        cloud_missing = [
            "CLOUD_SECRET_MANAGER_NOT_CONFIGURED",
            "HOSTED_PROCESS_SUPERVISOR_NOT_DEPLOYED",
            "BACKUP_ROTATION_NOT_DEPLOYED",
        ]
        return {
            "local_paper_ready": local_paper_ready,
            "cloud_paper_ready": False,
            "hosted_mode_ready": bool(self.runtime_config.hosted_mode and not missing),
            "live_ready": False,
            "live_status": "LIVE_LOCKED",
            "live_refusal_reason": "LIVE_NOT_APPROVED",
            "runtime_profile": self.runtime_config.runtime_profile,
            "missing_prerequisites": missing,
            "cloud_missing_prerequisites": cloud_missing,
            "warnings": warnings,
            "broker_call_occurred": False,
            "real_money_blocked": True,
            "updated_at": _utc_now(),
        }

    def storage(self) -> dict[str, Any]:
        session_store = self.supervisor.session_store.status()
        cache_status = (
            self.world_awareness_cache.status()
            if hasattr(self.world_awareness_cache, "status")
            else {
                "cache_type": "memory_only",
                "status": "READY",
                "event_count": len(self.world_awareness_cache.events(limit=self.world_awareness_cache.max_events)),
            }
        )

        def path_status(path) -> dict[str, Any]:
            exists = path.exists()
            parent = path if path.suffix == "" else path.parent
            return {
                "path": str(path),
                "exists": exists,
                "parent_exists": parent.exists(),
                "status": "READY" if parent.exists() else "MISSING_PARENT",
            }

        return {
            "runtime_profile": self.runtime_config.runtime_profile,
            "hosted_mode": self.runtime_config.hosted_mode,
            "session_store": session_store,
            "world_awareness_cache": cache_status,
            "operator_state_dir": path_status(self.runtime_config.operator_state_dir),
            "log_dir": path_status(self.runtime_config.log_dir),
            "data_dir": path_status(self.runtime_config.data_dir),
            "logs_operator_runs": path_status(self.runtime_config.log_dir / "operator_runs"),
            "logs_paper_runs": path_status(self.runtime_config.log_dir / "paper_runs"),
            "archives_runs": path_status(self.runtime_config.repo_root / "archives" / "runs"),
            "stores_log_contents": False,
            "secrets_values_exposed": False,
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
            "wrapper_stdout_path": latest.get("wrapper_stdout_path"),
            "wrapper_stderr_path": latest.get("wrapper_stderr_path"),
            "child_stdout_path": latest.get("child_stdout_path"),
            "child_stderr_path": latest.get("child_stderr_path"),
            "exit_code": latest.get("exit_code"),
            "runtime_profile": latest.get("runtime_profile") or self.runtime_config.runtime_profile,
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
            "alpaca_credentials_present": self._alpaca_paper_configured(),
            "world_awareness_credentials_present": self._alpaca_paper_configured(),
            "logs": str(self.runtime_config.log_dir),
            "db": "NO_DB_RUNTIME_FILE_STAGED_JSONL_METADATA_ONLY",
            "runtime_profile": self.runtime_config.runtime_profile,
            "hosted_mode": self.runtime_config.hosted_mode,
            "operator_config": self.runtime_config.safe_summary(),
            "storage": self.storage(),
            "legacy_dashboard_command_routes_present": False,
            "legacy_dashboard_status": "QUARANTINED_FROM_OPERATOR_PATH",
            "legacy_dashboard_reuse_allowed": False,
            "supervisor_version": self.supervisor.status_snapshot().get("supervisor_version"),
        }

    def live_readiness(self) -> dict[str, Any]:
        return {
            "live_status": "LIVE_LOCKED",
            "refusal_reason": "LIVE_NOT_APPROVED",
            "broker_endpoint_authority": "PAPER_ONLY_FOR_CURRENT_OPERATOR_API",
            "credential_authority": "CONFIGURED_OR_MISSING_STATUS_ONLY_NO_SECRET_VALUES",
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
            "broker_fee_hydration_attempted_count": 0,
            "broker_fee_hydration_count": 0,
            "broker_fee_hydration_pending_count": 0,
            "broker_fee_hydration_unmatched_count": 0,
            "broker_fee_hydration_conflict_count": 0,
            "broker_fee_activity_records_seen_count": 0,
            "broker_fee_activity_records_matched_count": 0,
            "fee_status": "FEE_PENDING_BROKER_ACTIVITY",
            "fee_source": "UNAVAILABLE",
            "fake_fills_allowed": False,
        }

    def tca_summary(self) -> dict[str, Any]:
        return {
            "source": "NO_ACTIVE_RUNTIME_ATTACHED",
            "tca_records_count": 0,
            "tca_unknown_count": 0,
            "tca_complete_count": 0,
            "tca_estimated_count": 0,
            "tca_fee_pending_count": 0,
            "realized_vs_modeled_netedge_available_count": 0,
            "realized_vs_modeled_netedge_unknown_count": 0,
            "execution_quality_verdict": "UNKNOWN_NO_ACTIVE_RUNTIME",
            "fake_fees_allowed": False,
            "fake_tca_allowed": False,
        }

    def pnl(self) -> dict[str, Any]:
        return build_pnl_summary(fills_summary=self.fills_summary(), tca_summary=self.tca_summary())

    def tca_dashboard(self) -> dict[str, Any]:
        return build_tca_dashboard(fills_summary=self.fills_summary(), tca_summary=self.tca_summary())

    def providers(self) -> dict[str, Any]:
        return provider_readiness_summary(self.process_env, credential_store=self.credential_store)

    def providers_readiness(self) -> dict[str, Any]:
        summary = self.providers()
        return {
            "source": "OPERATOR_PROVIDER_READINESS",
            "provider_registry_version": summary["provider_registry_version"],
            "provider_count": summary["provider_count"],
            "counts": summary["counts"],
            "ready_or_configured_count": int(summary["counts"].get("READY", 0)) + int(summary["counts"].get("CONFIGURED", 0)),
            "missing_credentials_count": int(summary["counts"].get("MISSING_CREDENTIALS", 0)),
            "not_implemented_count": int(summary["counts"].get("NOT_IMPLEMENTED", 0)),
            "secrets_values_exposed": False,
            "raw_secret_values_included": False,
            "broker_call_occurred": False,
            "external_mutation_occurred": False,
            "can_execute": False,
        }

    def validate_provider_readonly(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        provider_id = str((payload or {}).get("provider_id") or "alpaca_paper")
        return validate_provider_readonly(provider_id, self.process_env, credential_store=self.credential_store)

    def credentials_providers(self) -> dict[str, Any]:
        return self.credential_store.providers_summary(self.process_env)

    def credentials_save(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = payload or {}
        provider_id = str(body.get("provider_id") or "").strip().lower()
        credentials = body.get("credentials") if isinstance(body.get("credentials"), dict) else {}
        result = self.credential_store.save_provider(provider_id, credentials)
        self.provider_env = self.credential_store.effective_env(self.process_env)
        self.supervisor.config.process_env = self._paper_process_env()
        self.ai_gateway = AIProviderGateway(AIChiefConfig.from_env(self.provider_env))
        return result

    def credentials_validate_readonly(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        provider_id = str((payload or {}).get("provider_id") or "alpaca_paper")
        return self.credential_store.validate_readonly(provider_id, self.process_env)

    def credentials_delete_provider(self, provider_id: str) -> dict[str, Any]:
        result = self.credential_store.delete_provider(provider_id)
        self.provider_env = self.credential_store.effective_env(self.process_env)
        self.supervisor.config.process_env = self._paper_process_env()
        self.ai_gateway = AIProviderGateway(AIChiefConfig.from_env(self.provider_env))
        return result

    def portfolio(self) -> dict[str, Any]:
        return build_portfolio_snapshot(self.provider_env, client=self.portfolio_client)

    def positions(self) -> dict[str, Any]:
        portfolio = self.portfolio()
        return {
            "source": portfolio["source"],
            "data_source": portfolio["data_source"],
            "status": portfolio["status"],
            "positions": portfolio["positions"],
            "position_count": len(portfolio["positions"]),
            "message": portfolio["message"],
            "data_freshness_ts": portfolio["data_freshness_ts"],
            "broker_read_occurred": portfolio["broker_read_occurred"],
            "broker_mutation_occurred": False,
            "order_submission_occurred": False,
            "cancel_occurred": False,
            "liquidation_occurred": False,
            "secrets_values_exposed": False,
        }

    def orders_open(self) -> dict[str, Any]:
        portfolio = self.portfolio()
        return {
            "source": portfolio["source"],
            "data_source": portfolio["data_source"],
            "status": portfolio["status"],
            "open_orders": portfolio["open_orders"],
            "open_order_count": len(portfolio["open_orders"]),
            "read_only": True,
            "can_cancel": False,
            "can_replace": False,
            "can_liquidate": False,
            "broker_mutation_occurred": False,
            "order_submission_occurred": False,
            "cancel_occurred": False,
            "liquidation_occurred": False,
            "secrets_values_exposed": False,
        }

    def positions_intelligence(self) -> dict[str, Any]:
        portfolio = self.portfolio()
        return {
            "source": "OPERATOR_POSITION_INTELLIGENCE",
            "data_source": portfolio["data_source"],
            "status": portfolio["status"],
            "position_intelligence": portfolio["position_intelligence"],
            "position_count": len(portfolio["position_intelligence"]),
            "raw_logs_included": False,
            "secrets_values_exposed": False,
            "can_execute": False,
            "broker_mutation_occurred": False,
            "trading_mutation_occurred": False,
        }

    def launch_readiness(self) -> dict[str, Any]:
        supervisor = self.supervisor.status_snapshot()
        return build_launch_readiness(
            provider_readiness=self.providers(),
            credentials=self.credentials_providers(),
            health=self.health(),
            storage=self.storage(),
            runtime=self.runtime(),
            supervisor=supervisor,
            ai_status=self.ai_status(),
            effective_env=self.provider_env,
        )

    def research(self) -> dict[str, Any]:
        return self.research_registry.snapshot()

    def research_hypothesis(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.research_registry.create_hypothesis(payload or {})

    def research_experiment(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.research_registry.create_experiment(payload or {})

    def research_evidence_graph(self) -> dict[str, Any]:
        pnl_summary = self.pnl()
        tca_dashboard = self.tca_dashboard()
        return build_evidence_graph(
            run_archive=self.runs(),
            decision_explainer=self.explain_latest(),
            market_truth={
                "source": "OPERATOR_BACKEND_STATUS_SUMMARY",
                "summary": self.status().get("market_data", "UNKNOWN_NO_ACTIVE_RUNTIME"),
            },
            netedge={
                "status": tca_dashboard.get("status", "UNKNOWN"),
                "net_edge": "UNKNOWN_NO_ACTIVE_RUNTIME",
            },
            pnl=pnl_summary,
            orders=self.orders_summary(),
            fills=self.fills_summary(),
            tca=tca_dashboard,
            oms={"status": "UNKNOWN_NO_ACTIVE_RUNTIME"},
            action_center=self.action_center(),
            watchdog=self.alerts(),
            provider_readiness=self.providers(),
        )

    def audit_summary(self) -> dict[str, Any]:
        supervisor = self.supervisor.status_snapshot()
        persisted_events = self.supervisor.session_store.audit_events(limit=1)
        last_event = supervisor.get("last_audit_event") or (persisted_events[-1] if persisted_events else None)
        return {
            "source": "OPERATOR_SESSION_STORE",
            "operator_action_count": max(
                int(supervisor.get("audit_event_count", 0)),
                int(self.supervisor.session_store.status().get("audit_event_count", 0)),
            ),
            "broker_mutation_count": 0,
            "live_refusal_count": 1 if last_event and last_event.get("reason_code") == "LIVE_NOT_APPROVED" else 0,
            "last_event": last_event,
        }

    def world_awareness(self) -> dict[str, Any]:
        summary = self.world_awareness_cache.summary(
            self.world_awareness_config,
            env=self.world_awareness_env,
        )
        summary.update(
            {
                "source": "OPERATOR_BACKEND_WORLD_AWARENESS_CACHE",
                "credential_status": "CONFIG_GATED_NO_SECRET_VALUES",
                "provider_polling_active": False,
                "feed_can_trade": False,
                "market_truth_bypass_allowed": False,
                "netedge_bypass_allowed": False,
                "guardrail_bypass_allowed": False,
            }
        )
        return summary

    def world_awareness_providers(self) -> dict[str, Any]:
        summary = self.world_awareness()
        return {
            "source": summary["source"],
            "authority_class": "ADVISORY",
            "advisory_only": True,
            "providers": summary["providers"],
            "provider_count": len(summary["providers"]),
            "feed_can_trade": False,
            "reason_codes": ("ADVISORY_ONLY_NO_TRADE_AUTHORITY",),
        }

    def world_awareness_events(self) -> dict[str, Any]:
        summary = self.world_awareness()
        return {
            "source": summary["source"],
            "authority_class": "ADVISORY",
            "advisory_only": True,
            "events": summary["events"],
            "event_count": summary["event_count"],
            "stale_event_count": summary["stale_event_count"],
            "decisionframe_eligible_count": summary["decisionframe_eligible_count"],
            "feed_can_trade": False,
            "reason_codes": ("ADVISORY_ONLY_NO_TRADE_AUTHORITY",),
        }

    def world_awareness_runtime_status(self) -> dict[str, Any]:
        snapshot = self.world_awareness_runtime.status_snapshot()
        snapshot.update(
            {
                "source": "OPERATOR_BACKEND_WORLD_AWARENESS_RUNTIME",
                "authority_class": "ADVISORY",
                "advisory_only": True,
                "feed_can_trade": False,
                "market_truth_bypass_allowed": False,
                "netedge_bypass_allowed": False,
                "guardrail_bypass_allowed": False,
            }
        )
        return snapshot

    def world_awareness_poll_intent(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = payload or {}
        provider_name = str(body.get("provider") or "alpaca_news")
        result = self.world_awareness_runtime.poll_provider(
            provider_name,
            force=bool(body.get("force", False)),
            symbols=body.get("symbols") if isinstance(body.get("symbols"), list) else None,
            limit=body.get("limit") if body.get("limit") is not None else None,
        )
        result.update(
            {
                "intent_id": f"world_awareness_poll:{provider_name}",
                "broker_call_occurred": False,
                "runtime_mutation_occurred": False,
                "trading_mutation_occurred": False,
                "world_awareness_cache_mutation_occurred": result.get("allowed") is True,
                "live_endpoint_touched": False,
                "real_money_touched": False,
            }
        )
        return result

    def contracts(self) -> dict[str, Any]:
        return deepcopy(READ_ONLY_CONTRACTS)

    def latest_run(self) -> dict[str, Any]:
        return self.supervisor.status_snapshot()

    def runs(self) -> dict[str, Any]:
        return self.run_archive.list_runs()

    def run_detail(self, run_id: str) -> dict[str, Any]:
        run = self.run_archive.get_run(run_id)
        if run is None:
            return {
                "source": "OPERATOR_SESSION_STORE",
                "status": "NOT_FOUND",
                "run_id": run_id,
                "final_verdict": "UNKNOWN",
                "reason_codes": ("RUN_ID_NOT_FOUND",),
                "secrets_values_exposed": False,
            }
        return run

    def run_report(self, run_id: str) -> dict[str, Any]:
        run = self.run_archive.get_run(run_id)
        if run is None:
            return {
                "status": "NOT_FOUND",
                "run_id": run_id,
                "reason_code": "RUN_ID_NOT_FOUND",
                "logs_mutated": False,
                "secrets_values_exposed": False,
            }
        return self.report_generator.generate(run, write_files=True)

    def explain_latest(self) -> dict[str, Any]:
        return self.decision_explainer.explain_latest()

    def explain_decision(self, frame_id: str) -> dict[str, Any]:
        return self.decision_explainer.explain_by_id(frame_id)

    def alerts(self) -> dict[str, Any]:
        alerts = build_watchdog_alerts(
            status=self.status(),
            runtime=self.runtime(),
            health=self.health(),
            readiness=self.readiness(),
            storage=self.storage(),
            orders=self.orders_summary(),
            fills=self.fills_summary(),
            tca=self.tca_summary(),
            world_runtime=self.world_awareness_runtime_status(),
            archive=self.runs(),
        )
        queued_alerts = self.alert_queue.sync(alerts)
        return {
            "source": "OPERATOR_WATCHDOG",
            "alerts": queued_alerts,
            "alert_count": len(queued_alerts),
            "local_queue_only": True,
            "external_delivery_enabled": False,
            "broker_call_occurred": False,
            "trading_mutation_occurred": False,
            "secrets_values_exposed": False,
        }

    def action_center(self) -> dict[str, Any]:
        alerts = self.alerts()["alerts"]
        return build_action_center(
            status=self.status(),
            readiness=self.readiness(),
            health=self.health(),
            storage=self.storage(),
            fills=self.fills_summary(),
            world_runtime=self.world_awareness_runtime_status(),
            archive=self.runs(),
            alerts=alerts,
            ai_recommendations=self.ai_queue.list(),
        )

    def system_map(self) -> dict[str, Any]:
        return {
            "source": "OPERATOR_SYSTEM_MAP",
            "summary": dict(SYSTEM_MAP_SUMMARY),
            "markdown": render_system_map_markdown(),
            "report_path": SYSTEM_MAP_SUMMARY["report_path"],
            "secrets_values_exposed": False,
        }

    def ai_status(self) -> dict[str, Any]:
        recs = self.ai_queue.list()
        return {
            "source": "AI_CHIEF_OPERATOR",
            "persona": quant_persona_summary(),
            "gateway": self.ai_gateway.status(),
            "recommendation_count": len(recs),
            "pending_review_count": sum(1 for rec in recs if rec.get("status") == "PENDING_REVIEW"),
            "advisory_only": True,
            "can_execute": False,
            "broker_call_occurred": False,
            "trading_mutation_occurred": False,
            "live_enabled": False,
            "real_money_enabled": False,
            "secrets_values_exposed": False,
        }

    def ai_recommendations(self) -> dict[str, Any]:
        return {
            "source": "AI_CHIEF_GOVERNANCE_QUEUE",
            "recommendations": self.ai_queue.list(),
            "advisory_only": True,
            "can_execute": False,
            "broker_call_occurred": False,
            "trading_mutation_occurred": False,
            "secrets_values_exposed": False,
        }

    def _ai_context(self) -> dict[str, Any]:
        archive = self.runs()
        alerts = self.alerts()["alerts"]
        action_center = build_action_center(
            status=self.status(),
            readiness=self.readiness(),
            health=self.health(),
            storage=self.storage(),
            fills=self.fills_summary(),
            world_runtime=self.world_awareness_runtime_status(),
            archive=archive,
            alerts=alerts,
            ai_recommendations=self.ai_queue.list(),
        )
        context = build_ai_context(
            run_archive=archive,
            action_center=action_center,
            decision_explainer=self.explain_latest(),
            pnl=self.pnl(),
            tca=self.tca_dashboard(),
            world_awareness=self.world_awareness(),
            readiness=self.readiness(),
            alerts=alerts,
        )
        context["provider_readiness"] = self.providers()
        context["research_registry"] = self.research()
        context["evidence_graph"] = self.research_evidence_graph()
        context["persona"] = quant_persona_summary()
        context["can_execute"] = False
        context["broker_call_occurred"] = False
        context["trading_mutation_occurred"] = False
        return redact_secrets(context)

    def ai_analyze(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        context = self._ai_context()
        recommendation = self.ai_gateway.analyze(context, payload)
        queued = self.ai_queue.add(recommendation)
        return {
            "source": "AI_CHIEF_OPERATOR",
            "status": queued.get("status"),
            "recommendation": queued,
            "context": {
                "context_version": context["context_version"],
                "raw_logs_included": context["raw_logs_included"],
                "secrets_values_exposed": context["secrets_values_exposed"],
                "advisory_only": context["advisory_only"],
            },
            "advisory_only": True,
            "can_execute": False,
            "broker_call_occurred": False,
            "trading_mutation_occurred": False,
            "live_enabled": False,
            "real_money_enabled": False,
        }

    def ai_quant_review(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = payload or {}
        prompt = str(body.get("prompt") or body.get("question") or "Review current operator state as Quant Research Chief.")
        context = self._ai_context()
        raw = build_quant_review_recommendation(prompt, context)
        recommendation = normalize_recommendation(raw, provider="operator_quant_persona", role="AI_QUANT_RESEARCH_CHIEF")
        queued = self.ai_queue.add(recommendation)
        return {
            "source": "AI_QUANT_RESEARCH_CHIEF",
            "status": queued.get("status"),
            "recommendation": queued,
            "persona": quant_persona_summary(),
            "context": {
                "context_version": context["context_version"],
                "scope": context.get("scope"),
                "raw_logs_included": context["raw_logs_included"],
                "secrets_values_exposed": context["secrets_values_exposed"],
                "advisory_only": context["advisory_only"],
                "provider_count": context["provider_readiness"]["provider_count"],
            },
            "advisory_only": True,
            "can_execute": False,
            "broker_call_occurred": False,
            "trading_mutation_occurred": False,
            "live_enabled": False,
            "real_money_enabled": False,
        }

    def ai_draft_codex_packet(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = payload or {}
        prompt = str(body.get("prompt") or body.get("question") or "Draft a governed quant research Codex packet.")
        context = self._ai_context()
        raw = draft_codex_packet(prompt, context)
        draft_packet = raw.pop("draft_packet", "")
        recommendation = normalize_recommendation(raw, provider="operator_quant_persona", role="CODEX_PACKET_DRAFTER")
        queued = self.ai_queue.add(recommendation)
        return {
            "source": "AI_QUANT_RESEARCH_CHIEF",
            "status": queued.get("status"),
            "recommendation": queued,
            "draft_packet": draft_packet,
            "advisory_only": True,
            "can_execute": False,
            "broker_call_occurred": False,
            "trading_mutation_occurred": False,
            "live_enabled": False,
            "real_money_enabled": False,
            "raw_logs_included": False,
            "secrets_values_exposed": False,
        }

    def ai_approve_paper_research(self, recommendation_id: str) -> dict[str, Any]:
        return self.ai_queue.approve_paper_research(recommendation_id)

    def ai_reject(self, recommendation_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        reason = (payload or {}).get("reason") if isinstance(payload, dict) else None
        return self.ai_queue.reject(recommendation_id, reason=str(reason) if reason else None)

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

    @router.get("/health")
    def health() -> dict[str, Any]:
        return provider.health()

    @router.get("/readiness")
    def readiness() -> dict[str, Any]:
        return provider.readiness()

    @router.get("/storage")
    def storage() -> dict[str, Any]:
        return provider.storage()

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

    @router.get("/world-awareness")
    def world_awareness() -> dict[str, Any]:
        return provider.world_awareness()

    @router.get("/world-awareness/providers")
    def world_awareness_providers() -> dict[str, Any]:
        return provider.world_awareness_providers()

    @router.get("/world-awareness/events")
    def world_awareness_events() -> dict[str, Any]:
        return provider.world_awareness_events()

    @router.get("/world-awareness/runtime")
    def world_awareness_runtime_status() -> dict[str, Any]:
        return provider.world_awareness_runtime_status()

    @router.get("/latest-run")
    def latest_run() -> dict[str, Any]:
        return provider.latest_run()

    @router.get("/runs")
    def runs() -> dict[str, Any]:
        return provider.runs()

    @router.get("/runs/{run_id}/report")
    def run_report(run_id: str) -> dict[str, Any]:
        return provider.run_report(run_id)

    @router.get("/runs/{run_id}")
    def run_detail(run_id: str) -> dict[str, Any]:
        return provider.run_detail(run_id)

    @router.get("/explain/latest")
    def explain_latest() -> dict[str, Any]:
        return provider.explain_latest()

    @router.get("/explain/decision/{frame_id}")
    def explain_decision(frame_id: str) -> dict[str, Any]:
        return provider.explain_decision(frame_id)

    @router.get("/action-center")
    def action_center() -> dict[str, Any]:
        return provider.action_center()

    @router.get("/pnl")
    def pnl() -> dict[str, Any]:
        return provider.pnl()

    @router.get("/tca")
    def tca_dashboard() -> dict[str, Any]:
        return provider.tca_dashboard()

    @router.get("/providers")
    def providers() -> dict[str, Any]:
        return provider.providers()

    @router.get("/providers/readiness")
    def providers_readiness() -> dict[str, Any]:
        return provider.providers_readiness()

    @router.post("/providers/validate-readonly")
    def validate_provider_readonly_intent(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return provider.validate_provider_readonly(payload)

    @router.get("/credentials/providers")
    def credentials_providers() -> dict[str, Any]:
        return provider.credentials_providers()

    @router.post("/credentials/save")
    def credentials_save(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return provider.credentials_save(payload)

    @router.post("/credentials/validate-readonly")
    def credentials_validate_readonly(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return provider.credentials_validate_readonly(payload)

    @router.delete("/credentials/provider/{provider_id}")
    def credentials_delete_provider(provider_id: str) -> dict[str, Any]:
        return provider.credentials_delete_provider(provider_id)

    @router.get("/portfolio")
    def portfolio() -> dict[str, Any]:
        return provider.portfolio()

    @router.get("/positions")
    def positions() -> dict[str, Any]:
        return provider.positions()

    @router.get("/orders/open")
    def orders_open() -> dict[str, Any]:
        return provider.orders_open()

    @router.get("/positions/intelligence")
    def positions_intelligence() -> dict[str, Any]:
        return provider.positions_intelligence()

    @router.get("/launch-readiness")
    def launch_readiness() -> dict[str, Any]:
        return provider.launch_readiness()

    @router.get("/research")
    def research() -> dict[str, Any]:
        return provider.research()

    @router.post("/research/hypotheses")
    def research_hypothesis(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return provider.research_hypothesis(payload)

    @router.post("/research/experiments")
    def research_experiment(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return provider.research_experiment(payload)

    @router.get("/research/evidence-graph")
    def research_evidence_graph() -> dict[str, Any]:
        return provider.research_evidence_graph()

    @router.get("/alerts")
    def alerts() -> dict[str, Any]:
        return provider.alerts()

    @router.get("/system-map")
    def system_map() -> dict[str, Any]:
        return provider.system_map()

    @router.get("/ai/status")
    def ai_status() -> dict[str, Any]:
        return provider.ai_status()

    @router.get("/ai/recommendations")
    def ai_recommendations() -> dict[str, Any]:
        return provider.ai_recommendations()

    @router.post("/ai/analyze")
    def ai_analyze(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return provider.ai_analyze(payload)

    @router.post("/ai/quant-review")
    def ai_quant_review(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return provider.ai_quant_review(payload)

    @router.post("/ai/draft-codex-packet")
    def ai_draft_codex_packet(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return provider.ai_draft_codex_packet(payload)

    @router.post("/ai/recommendations/{recommendation_id}/approve-paper-research")
    def ai_approve_paper_research(recommendation_id: str) -> dict[str, Any]:
        return provider.ai_approve_paper_research(recommendation_id)

    @router.post("/ai/recommendations/{recommendation_id}/reject")
    def ai_reject(recommendation_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return provider.ai_reject(recommendation_id, payload)

    @router.post("/intent/paper/start")
    def paper_start_intent(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return provider.paper_start_intent(payload)

    @router.post("/intent/paper/stop")
    def paper_stop_intent(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return provider.paper_stop_intent(payload)

    @router.post("/intent/snapshot/export")
    def snapshot_export_intent() -> dict[str, Any]:
        return provider.refused_intent("snapshot_export", "PAPER_INTENT_NOT_IMPLEMENTED")

    @router.post("/intent/world-awareness/poll")
    def world_awareness_poll_intent(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return provider.world_awareness_poll_intent(payload)

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
    ui_dir = Path(__file__).resolve().parents[2] / "ui" / "operator-control-panel"
    if ui_dir.exists():
        app.mount("/operator-ui", StaticFiles(directory=str(ui_dir), html=True), name="operator-ui")
    return app


__all__ = [
    "API_VERSION",
    "OperatorSnapshotProvider",
    "READ_ONLY_CONTRACTS",
    "create_operator_app",
    "get_operator_router",
]
