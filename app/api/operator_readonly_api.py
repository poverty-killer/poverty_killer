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
from app.ai_chief_operator.model_router import HIGH_REASONING_API, LIGHT_API, LOCAL_GUIDE, LOCAL_MODEL_MODE, SUPREME_BOARD_PACKET_MODE
from app.ai_chief_operator.router_settings import (
    AIRouterSettingsStore,
    default_ai_router_settings,
    default_ai_router_settings_path,
    router_mode_for_gateway,
)
from app.ai_chief_operator.quant_persona import (
    draft_codex_packet,
    build_quant_review_recommendation,
    classify_quant_prompt,
    quant_persona_summary,
)
from app.operator_activation.launch_readiness import build_launch_readiness
from app.api.operator_paper_supervisor import OperatorPaperSupervisor, PaperSupervisorConfig
from app.api.operator_runtime_config import OperatorRuntimeConfig
from app.operator_credentials.store import (
    DEFAULT_RELATIVE_STORE_PATH,
    PROVIDER_CREDENTIAL_FIELDS,
    LocalCredentialStore,
    alpaca_endpoint_authority,
    default_credential_store_path,
    normalize_provider_id,
)
from app.operator_intelligence.action_center import build_action_center
from app.operator_intelligence.archive import RunArchive
from app.operator_intelligence.decision_explainer import DecisionExplainer
from app.operator_intelligence.pnl_tca import build_pnl_summary, build_tca_dashboard
from app.operator_intelligence.reports import RunReportGenerator
from app.operator_intelligence.system_map import SYSTEM_MAP_SUMMARY, render_system_map_markdown
from app.operator_intelligence.watchdog import AlertQueue, build_watchdog_alerts
from app.operator_historical_tests.service import HistoricalTestService
from app.operator_portfolio.snapshot import ReadOnlyBrokerClient, build_portfolio_snapshot
from app.operator_providers.readiness import provider_readiness_summary, validate_provider_readonly
from app.operator_research.evidence_graph import build_evidence_graph
from app.operator_research.registry import ResearchRegistry
from app.world_awareness.config import WorldAwarenessConfig
from app.world_awareness.feed_spine import WorldAwarenessEventCache
from app.world_awareness.persistent_cache import PersistentWorldAwarenessEventCache
from app.world_awareness.scheduler import WorldAwarenessProviderRuntime


API_VERSION = "operator-backend-v1"
OPERATOR_ACTIVATION_VERSION = "operator-activation-e2e-truth6-20260602"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


READ_ONLY_CONTRACTS: dict[str, Any] = {
    "version": API_VERSION,
    "operator_activation_version": OPERATOR_ACTIVATION_VERSION,
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
        "/operator/ai/ask": "advisory_ai_question_answer_no_execution",
        "/operator/ai/router/settings": "persistent_local_ai_router_settings_no_secret_storage",
        "/operator/ai/routing/settings": "local_ai_routing_settings_no_secret_storage",
        "/operator/ai/providers/validate": "safe_ai_provider_validation_no_paid_call_without_approval",
        "/operator/ai/supreme-board-packet": "safe_manual_supreme_board_packet_bridge",
        "/operator/ai/analyze": "advisory_ai_analysis_governance_queue_only",
        "/operator/providers": "read_only_provider_setup_and_credential_readiness",
        "/operator/providers/readiness": "read_only_provider_readiness_summary",
        "/operator/providers/validate-readonly": "read_only_env_presence_validation_only",
        "/operator/credentials/providers": "read_only_local_credential_provider_status",
        "/operator/credentials/diagnostics": "debug_safe_credential_path_and_source_status",
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
        "/operator/historical-tests": "read_only_historical_test_registry",
        "/operator/historical-tests/run": "advisory_historical_test_request_no_trading",
        "/operator/historical-tests/{test_id}": "read_only_historical_test_detail",
        "/operator/historical-tests/{test_id}/report": "read_only_historical_test_report",
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
        historical_tests: HistoricalTestService | None = None,
    ) -> None:
        self.runtime_config = runtime_config or OperatorRuntimeConfig.from_env()
        self.process_env = provider_env if provider_env is not None else dict(os.environ)
        self.credential_store = credential_store or LocalCredentialStore(
            default_credential_store_path(self.runtime_config.repo_root)
        )
        self.provider_env = self.credential_store.effective_env(self.process_env)
        self.provider_env.update(self.credential_store.effective_provider_values("alpaca_paper", self.process_env))
        self.portfolio_client = portfolio_client
        supervisor_config = PaperSupervisorConfig.from_runtime_config(self.runtime_config)
        supervisor_config.process_env = self._paper_process_env(self.provider_env)
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
        self.ai_gateway = AIProviderGateway(
            ai_config or AIChiefConfig.from_env(self.provider_env),
            credential_env=self.provider_env,
        )
        gateway_summary = self.ai_gateway.status().get("router") or {}
        self.ai_router_settings_store = AIRouterSettingsStore(
            default_ai_router_settings_path(self.runtime_config.repo_root)
        )
        ai_settings_loaded = self.ai_router_settings_store.load(
            defaults=self._default_ai_router_settings(gateway_summary)
        )
        self.ai_routing_settings = dict(ai_settings_loaded["settings"])
        self.ai_routing_settings_source = str(ai_settings_loaded.get("settings_source") or "DEFAULT_SETTINGS")
        self.ai_routing_settings_last_result = ai_settings_loaded
        self.ai_queue = ai_queue or GovernanceQueue(
            path=self.runtime_config.operator_state_dir / "ai_governance_queue.jsonl"
        )
        self.research_registry = research_registry or ResearchRegistry()
        self.historical_tests_service = historical_tests or HistoricalTestService()
        self.last_credential_save_diagnostic: dict[str, Any] | None = None

    def _default_ai_router_settings(self, gateway_summary: dict[str, Any] | None = None) -> dict[str, Any]:
        summary = gateway_summary or self.ai_gateway.status().get("router") or {}
        settings = default_ai_router_settings()
        settings.update(
            {
                "default_mode": summary.get("default_route_mode") or settings["default_mode"],
                "light_provider": summary.get("light_provider") or settings["light_provider"],
                "light_model": summary.get("light_model") or settings["light_model"],
                "high_reasoning_provider": summary.get("high_reasoning_provider") or settings["high_reasoning_provider"],
                "high_reasoning_model": summary.get("high_reasoning_model") or settings["high_reasoning_model"],
                "local_provider": "local_openai_compatible",
                "local_base_url": self.provider_env.get("LOCAL_AI_BASE_URL") or settings["local_base_url"],
                "local_model": self.provider_env.get("LOCAL_AI_MODEL") or settings["local_model"],
                "supreme_board_packet_default": bool(summary.get("supreme_board_packet_default")),
            }
        )
        return settings

    def _paper_process_env(self, env: dict[str, str] | None = None) -> dict[str, str]:
        effective_env = dict(env if env is not None else self.provider_env)
        if env is None:
            effective_env.update(self.credential_store.effective_provider_values("alpaca_paper", self.process_env))
        return {
            key: str(value)
            for key, value in effective_env.items()
            if key in {"APCA_API_KEY_ID", "APCA_API_SECRET_KEY", "APCA_API_BASE_URL"} and str(value).strip()
        }

    def _refresh_provider_env(self) -> dict[str, str]:
        refreshed = self.credential_store.effective_env(self.process_env)
        refreshed.update(self.credential_store.effective_provider_values("alpaca_paper", self.process_env))
        if refreshed != self.provider_env:
            self.provider_env = refreshed
            self.ai_gateway = AIProviderGateway(
                AIChiefConfig.from_env(refreshed),
                credential_env=refreshed,
                http_post=self.ai_gateway.http_post,
            )
        self.supervisor.config.process_env = self._paper_process_env(refreshed)
        return self.provider_env

    def _supervisor_snapshot(self) -> dict[str, Any]:
        self._refresh_provider_env()
        return self.supervisor.status_snapshot()

    def _alpaca_paper_configured(self) -> bool:
        summary = self.credential_store.provider_summary("alpaca_paper", self.process_env)
        return bool(summary["configured"])

    def _active_router_api_selection(self) -> tuple[str, str]:
        provider_id = str(self.ai_routing_settings.get("active_provider") or "").strip().lower()
        model_name = str(self.ai_routing_settings.get("active_model") or "").strip()
        if provider_id in {"", "deterministic_local", "supreme_board_packet", "local_openai_compatible"}:
            return "", ""
        return provider_id, model_name

    def status(self) -> dict[str, Any]:
        supervisor = self._supervisor_snapshot()
        active = supervisor.get("active_session") or {}
        latest = supervisor.get("latest_session") or {}
        session_status = active.get("status")
        active_profile = active.get("profile") or "UNKNOWN_NO_ACTIVE_RUNTIME"
        watchlist = active.get("watchlist") or []
        process_state = session_status or "NO_ACTIVE_RUNTIME_ATTACHED"
        paper_start_allowed = supervisor.get("paper_start_allowed") is True
        ready_idle = not watchlist and paper_start_allowed and supervisor.get("state") == "IDLE"
        historical_refusal = latest if latest.get("status") == "REFUSED" else None
        runtime_attachment_state = "READY_IDLE_NO_ACTIVE_RUNTIME" if ready_idle else process_state
        runtime_attachment_detail = (
            "Ready. No PAPER run currently attached."
            if ready_idle
            else (
                f"No PAPER run currently attached; start blocked by {supervisor.get('paper_start_refusal_reason') or 'supervisor authority'}."
                if not watchlist
                else "PAPER supervisor process is attached."
            )
        )
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
            "dominant_blocker": runtime_attachment_state if not watchlist else "SUPERVISOR_PROCESS_RUNNING_OR_RECENT",
            "runtime_attachment_state": runtime_attachment_state,
            "runtime_attachment_detail": runtime_attachment_detail,
            "last_historical_refusal": historical_refusal,
            "last_historical_refusal_reason": historical_refusal.get("refusal_reason") if historical_refusal else None,
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
        supervisor = self._supervisor_snapshot()
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
            "api_version": API_VERSION,
            "operator_activation_version": OPERATOR_ACTIVATION_VERSION,
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
        supervisor = self._supervisor_snapshot()
        active = supervisor.get("active_session") or {}
        latest = supervisor.get("latest_session") or {}
        historical_refusal = latest if latest.get("status") == "REFUSED" else None
        current_attached = bool(active)
        runtime_attachment_state = active.get("status") or "NO_ACTIVE_RUNTIME_ATTACHED"
        return {
            "process_state": runtime_attachment_state,
            "current_runtime_attached": current_attached,
            "runtime_attachment_state": runtime_attachment_state,
            "runtime_attachment_detail": (
                "PAPER supervisor process is attached."
                if current_attached
                else "Ready. No PAPER run currently attached."
                if supervisor.get("paper_start_allowed") is True and supervisor.get("state") == "IDLE"
                else "No PAPER run currently attached."
            ),
            "launch_command": active.get("command_summary"),
            "duration_seconds": active.get("duration_seconds"),
            "started_at": active.get("started_at"),
            "shutdown_reason": active.get("stop_reason"),
            "bounded_timer_started": bool(active.get("bounded_timer_started")) if active else False,
            "bounded_duration_elapsed": active.get("status") in {"EXITED", "STOPPED"} if active else False,
            "runtime_commit": None,
            "session_id": active.get("session_id"),
            "pid": active.get("pid"),
            "stdout_path": active.get("stdout_path"),
            "stderr_path": active.get("stderr_path"),
            "wrapper_stdout_path": active.get("wrapper_stdout_path"),
            "wrapper_stderr_path": active.get("wrapper_stderr_path"),
            "child_stdout_path": active.get("child_stdout_path"),
            "child_stderr_path": active.get("child_stderr_path"),
            "exit_code": active.get("exit_code"),
            "runtime_profile": active.get("runtime_profile") or self.runtime_config.runtime_profile,
            "latest_session": latest,
            "historical_latest_session": latest,
            "historical_refusal_reason": historical_refusal.get("refusal_reason") if historical_refusal else None,
            "historical_refusal_session_id": historical_refusal.get("session_id") if historical_refusal else None,
            "supervisor_state": supervisor["state"],
            "duplicate_run_prevention": "ACTIVE",
            "paper_start_allowed": supervisor["paper_start_allowed"],
            "paper_stop_allowed": supervisor["paper_stop_allowed"],
            "paper_start_refusal_reason": supervisor["paper_start_refusal_reason"],
            "paper_stop_refusal_reason": supervisor["paper_stop_refusal_reason"],
            "paper_credentials_configured": supervisor.get("paper_credentials_configured"),
            "paper_credential_refusal_reason": supervisor.get("paper_credential_refusal_reason"),
            "paper_credential_source": supervisor.get("paper_credential_source"),
            "paper_endpoint_only": supervisor.get("paper_endpoint_only"),
            "paper_endpoint_status": supervisor.get("paper_endpoint_status"),
            "paper_endpoint_source": supervisor.get("paper_endpoint_source"),
            "paper_endpoint_refusal_reason": supervisor.get("paper_endpoint_refusal_reason"),
            "paper_endpoint_operator_action": supervisor.get("paper_endpoint_operator_action"),
            "min_paper_duration_seconds": supervisor.get("min_paper_duration_seconds"),
            "max_paper_duration_seconds": supervisor.get("max_paper_duration_seconds"),
            "runner_max_paper_duration_seconds": supervisor.get("runner_max_paper_duration_seconds"),
            "duration_authority": supervisor.get("duration_authority"),
        }

    def profile(self) -> dict[str, Any]:
        supervisor = self._supervisor_snapshot()
        active = supervisor.get("active_session") or {}
        profile = active.get("profile") or "UNKNOWN_NO_ACTIVE_RUNTIME"
        return {
            "active_threshold_profile": profile,
            "paper_exploration_alpha_active": profile == "PAPER_EXPLORATION_ALPHA",
            "paper_only": True,
            "activation_status": active.get("status") or "NO_ACTIVE_RUNTIME_ATTACHED",
            "activation_refusal_reason": None,
        }

    def universe(self) -> dict[str, Any]:
        supervisor = self._supervisor_snapshot()
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
        operator_config_summary = self.runtime_config.safe_summary()
        operator_config_summary["alpaca_credentials_present"] = self._alpaca_paper_configured()
        operator_config_summary["world_awareness_credentials_present"] = self._alpaca_paper_configured()
        return {
            "api_version": API_VERSION,
            "operator_activation_version": OPERATOR_ACTIVATION_VERSION,
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
            "operator_config": operator_config_summary,
            "storage": self.storage(),
            "legacy_dashboard_command_routes_present": False,
            "legacy_dashboard_status": "QUARANTINED_FROM_OPERATOR_PATH",
            "legacy_dashboard_reuse_allowed": False,
            "supervisor_version": self._supervisor_snapshot().get("supervisor_version"),
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
        self._refresh_provider_env()
        return provider_readiness_summary(self.process_env, credential_store=self.credential_store)

    def providers_readiness(self) -> dict[str, Any]:
        summary = self.providers()
        return {
            "source": "OPERATOR_PROVIDER_READINESS",
            "provider_registry_version": summary["provider_registry_version"],
            "providers": summary["providers"],
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
        self._refresh_provider_env()
        return self.credential_store.providers_summary(self.process_env)

    def credentials_diagnostics(self) -> dict[str, Any]:
        effective_env = self._refresh_provider_env()
        raw = self.credential_store.load_raw()
        raw_providers = raw.get("providers") if isinstance(raw.get("providers"), dict) else {}
        provider_ids_present = sorted(str(provider_id) for provider_id in raw_providers)
        vault_status = self.credential_store.vault_status()
        last_save = self.last_credential_save_diagnostic or {}
        diagnostics: dict[str, Any] = {
            "source": "OPERATOR_CREDENTIAL_DIAGNOSTICS",
            "api_version": API_VERSION,
            "operator_activation_version": OPERATOR_ACTIVATION_VERSION,
            "backend_cwd": os.getcwd(),
            "backend_repo_root": str(self.runtime_config.repo_root),
            "credential_vault_relative_path": DEFAULT_RELATIVE_STORE_PATH,
            "vault_file_exists": vault_status["vault_file_exists"],
            "vault_writable": vault_status["vault_parent_writable"],
            "vault_parent_exists": vault_status["vault_parent_exists"],
            "vault_parent_writable": vault_status["vault_parent_writable"],
            "provider_ids_present": provider_ids_present,
            "accepted_provider_ids": sorted(PROVIDER_CREDENTIAL_FIELDS),
            "received_provider_id_last_save": last_save.get("received_provider_id"),
            "normalized_provider_id_last_save": last_save.get("provider_id"),
            "last_save_status": last_save.get("status"),
            "last_save_refusal_reason": last_save.get("reason_code"),
            "last_save_missing_fields": last_save.get("missing_fields") or [],
            "last_save_received_field_names": last_save.get("received_field_names") or [],
            "last_save_received_field_presence": last_save.get("received_field_presence") or {},
            "providers": {},
            "secrets_values_exposed": False,
            "raw_secret_values_included": False,
            "broker_call_occurred": False,
            "trading_mutation_occurred": False,
            "live_enabled": False,
            "real_money_enabled": False,
        }
        readiness = self.providers()
        readiness_by_id = {
            str(provider.get("provider_id")): provider
            for provider in readiness.get("providers") or []
            if isinstance(provider, dict)
        }
        for provider_id, schema in PROVIDER_CREDENTIAL_FIELDS.items():
            summary = self.credential_store.provider_summary(provider_id, self.process_env)
            fields = summary.get("fields") if isinstance(summary.get("fields"), list) else []
            field_map = {str(field.get("name")): field for field in fields if isinstance(field, dict)}
            required = tuple(str(name) for name in schema.get("required", ()))
            required_present = {
                name: bool(field_map.get(name, {}).get("configured"))
                for name in required
            }
            configured_sources = sorted(
                {
                    str(field.get("source"))
                    for field in fields
                    if isinstance(field, dict) and field.get("configured") is True
                }
            ) or ["NOT_CONFIGURED"]
            readiness_row = readiness_by_id.get(provider_id, {})
            diagnostics["providers"][provider_id] = {
                "configured": summary.get("configured") is True,
                "required_field_names_present": required_present,
                "summary_source": summary.get("source") or "NOT_CONFIGURED",
                "source_used_by_provider_readiness": "+".join(configured_sources),
                "provider_readiness_status": readiness_row.get("status") or "UNKNOWN",
            }
        alpaca_sources = diagnostics["providers"]["alpaca_paper"]["source_used_by_provider_readiness"]
        supervisor_env = self.supervisor.config.process_env
        endpoint_authority = alpaca_endpoint_authority(supervisor_env)
        supervisor_present = {
            "APCA_API_KEY_ID": bool(str(supervisor_env.get("APCA_API_KEY_ID") or "").strip()),
            "APCA_API_SECRET_KEY": bool(str(supervisor_env.get("APCA_API_SECRET_KEY") or "").strip()),
            "APCA_API_BASE_URL": bool(str(supervisor_env.get("APCA_API_BASE_URL") or "").strip()),
        }
        supervisor_keys_present = supervisor_present["APCA_API_KEY_ID"] and supervisor_present["APCA_API_SECRET_KEY"]
        diagnostics["source_used_by_credential_cards"] = alpaca_sources
        diagnostics["source_used_by_provider_table"] = alpaca_sources
        diagnostics["source_used_by_provider_readiness"] = alpaca_sources
        diagnostics["source_used_by_launch_readiness"] = alpaca_sources
        diagnostics["source_used_by_portfolio"] = alpaca_sources if (
            str(effective_env.get("APCA_API_KEY_ID") or "").strip()
            and str(effective_env.get("APCA_API_SECRET_KEY") or "").strip()
        ) else "NOT_CONFIGURED"
        diagnostics["source_used_by_portfolio_broker_read"] = alpaca_sources if (
            str(effective_env.get("APCA_API_KEY_ID") or "").strip()
            and str(effective_env.get("APCA_API_SECRET_KEY") or "").strip()
        ) else "NOT_CONFIGURED"
        diagnostics["source_used_by_paper_supervisor"] = alpaca_sources if supervisor_keys_present else "NOT_CONFIGURED"
        diagnostics["paper_endpoint_authority"] = endpoint_authority
        diagnostics["paper_endpoint_only"] = endpoint_authority["paper_endpoint_only"]
        diagnostics["paper_endpoint_status"] = endpoint_authority["status"]
        diagnostics["paper_endpoint_source"] = endpoint_authority["endpoint_source"]
        diagnostics["paper_endpoint_operator_action"] = endpoint_authority["operator_action"]
        diagnostics["portfolio_required_field_names_present"] = {
            "APCA_API_KEY_ID": bool(str(effective_env.get("APCA_API_KEY_ID") or "").strip()),
            "APCA_API_SECRET_KEY": bool(str(effective_env.get("APCA_API_SECRET_KEY") or "").strip()),
            "APCA_API_BASE_URL": bool(str(effective_env.get("APCA_API_BASE_URL") or "").strip()),
        }
        diagnostics["paper_supervisor_required_field_names_present"] = supervisor_present
        return diagnostics

    def credentials_save(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = payload or {}
        received_provider_id = str(body.get("provider_id") or "").strip()
        provider_id = normalize_provider_id(received_provider_id)
        credentials = body.get("credentials") if isinstance(body.get("credentials"), dict) else {}
        result = self.credential_store.save_provider(received_provider_id, credentials)
        self._refresh_provider_env()
        result.update(
            {
                "broker_call_occurred": False,
                "trading_mutation_occurred": False,
                "live_enabled": False,
                "real_money_enabled": False,
            }
        )
        self.last_credential_save_diagnostic = {
            "received_provider_id": received_provider_id,
            "provider_id": result.get("provider_id") or provider_id,
            "status": result.get("status"),
            "reason_code": result.get("reason_code"),
            "missing_fields": result.get("missing_fields") or [],
            "received_field_names": result.get("received_field_names") or [],
            "received_field_presence": result.get("received_field_presence") or {},
            "vault_writable": result.get("vault_parent_writable"),
            "accepted_provider_ids": result.get("accepted_provider_ids") or sorted(PROVIDER_CREDENTIAL_FIELDS),
        }
        return result

    def credentials_validate_readonly(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        provider_id = str((payload or {}).get("provider_id") or "alpaca_paper")
        result = self.credential_store.validate_readonly(provider_id, self.process_env)
        result.update(
            {
                "broker_call_occurred": False,
                "trading_mutation_occurred": False,
                "live_enabled": False,
                "real_money_enabled": False,
            }
        )
        return result

    def credentials_delete_provider(self, provider_id: str) -> dict[str, Any]:
        result = self.credential_store.delete_provider(provider_id)
        self._refresh_provider_env()
        result.update(
            {
                "broker_call_occurred": False,
                "trading_mutation_occurred": False,
                "live_enabled": False,
                "real_money_enabled": False,
            }
        )
        return result

    def portfolio(self) -> dict[str, Any]:
        return build_portfolio_snapshot(self._refresh_provider_env(), client=self.portfolio_client)

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
        effective_env = self._refresh_provider_env()
        supervisor = self.supervisor.status_snapshot()
        return build_launch_readiness(
            provider_readiness=self.providers(),
            credentials=self.credentials_providers(),
            health=self.health(),
            storage=self.storage(),
            runtime=self.runtime(),
            supervisor=supervisor,
            ai_status=self.ai_status(),
            effective_env=effective_env,
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

    def historical_tests(self) -> dict[str, Any]:
        return self.historical_tests_service.summary()

    def historical_test_run(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.historical_tests_service.run(payload or {})

    def historical_test_detail(self, test_id: str) -> dict[str, Any]:
        return self.historical_tests_service.detail(test_id)

    def historical_test_report(self, test_id: str) -> dict[str, Any]:
        return self.historical_tests_service.report(test_id)

    def audit_summary(self) -> dict[str, Any]:
        supervisor = self._supervisor_snapshot()
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
        return self._supervisor_snapshot()

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
            "routing_settings": dict(self.ai_routing_settings),
            "routing_settings_source": self.ai_routing_settings_source,
            "routing_settings_status": self.ai_routing_settings_last_result.get("status"),
            "routing_settings_path_relative": self.ai_routing_settings_last_result.get("settings_path_relative"),
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

    def ai_ask(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = payload or {}
        question = str(body.get("question") or body.get("prompt") or "").strip()
        page_context = redact_secrets(body.get("page_context") if isinstance(body.get("page_context"), dict) else {})
        page_id = str(body.get("page_id") or page_context.get("page_id") or "")
        gateway_status = self.ai_gateway.status()
        provider = gateway_status.get("provider") or {}
        model_policy = gateway_status.get("model_policy") or {}
        provider_state = str(provider.get("provider_state") or "AI_DISABLED")
        classification = classify_quant_prompt(question, page_id=page_id)
        mode = str(classification.get("mode") or "OPERATOR_GUIDE")
        evidence_level = str(classification.get("evidence_level") or "UNKNOWN")
        simple_health_question = self._ai_is_simple_health_question(question)
        local_runtime_truth_question = self._ai_should_answer_from_runtime_truth(mode, question)
        if not classification["allowed"]:
            context = self._ai_light_context()
            response = (
                "Refused or redirected. The Chief Quant Advisor cannot trade, call broker, enable live, "
                "handle secrets, bypass safety gates, submit/cancel/liquidate orders, or mutate strategy. "
                "Safe path: use governed PAPER readiness, Provider Setup, Portfolio Home, or ask for a Codex packet."
            )
            status = "REFUSED"
            refusal_reason = classification["reason_code"]
            gateway_answer: dict[str, Any] = {}
        else:
            route_mode = router_mode_for_gateway(body.get("route_mode") or body.get("mode") or self.ai_routing_settings.get("default_mode") or LOCAL_GUIDE)
            context = self._ai_light_context() if route_mode == LOCAL_GUIDE or simple_health_question or local_runtime_truth_question else self._ai_context()
            route_provider = str(body.get("provider_id") or "").strip()
            route_model = str(body.get("model_name") or "").strip()
            if not route_provider:
                active_provider, active_model = self._active_router_api_selection()
                if route_mode == HIGH_REASONING_API:
                    route_provider = active_provider or str(self.ai_routing_settings.get("high_reasoning_provider") or "openai")
                    route_model = route_model or active_model or str(self.ai_routing_settings.get("high_reasoning_model") or "")
                elif route_mode == LIGHT_API:
                    route_provider = active_provider or str(self.ai_routing_settings.get("light_provider") or "openai")
                    route_model = route_model or active_model or str(self.ai_routing_settings.get("light_model") or "")
                elif route_mode == LOCAL_MODEL_MODE:
                    route_provider = "local_openai_compatible"
                    route_model = route_model or str(self.ai_routing_settings.get("local_model") or "")
            if simple_health_question or local_runtime_truth_question:
                route_reason = "SIMPLE_HEALTH_LOCAL_TRUTH" if simple_health_question else "RUN_PLANNER_LOCAL_RUNTIME_TRUTH"
                gateway_answer = {
                    "status": "ANSWERED_LOCAL_GUIDE",
                    "provider": "deterministic_local",
                    "provider_id": "deterministic_local",
                    "provider_state": "LOCAL_GUIDE",
                    "response_source": "LOCAL_DETERMINISTIC",
                    "answer_source": "LOCAL_DETERMINISTIC",
                    "response": self._ai_health_answer(context) if simple_health_question else self._ai_paper_readiness_answer(question, context),
                    "model_call_occurred": False,
                    "provider_mode": "DETERMINISTIC_FALLBACK",
                    "model_name": "deterministic-local-guide",
                    "model_quality": "FALLBACK_ONLY",
                    "reasoning_policy": "FALLBACK_ONLY_LIMITED",
                    "model_suitable_for_governance": False,
                    "cost_mode": "FREE_LOCAL",
                    "persona_enforced": True,
                    "expert_roles_applied": ["Chief Quant Advisor", "Operator Guide"],
                    "route_decision": {
                        "reason_code": route_reason,
                        "provider_id": "deterministic_local",
                        "model_name": "deterministic-local-guide",
                    },
                }
            else:
                gateway_answer = self.ai_gateway.ask(
                    question,
                    context,
                    page_context,
                    routing={
                        "route_mode": route_mode,
                        "provider_id": route_provider,
                        "model_name": route_model,
                        "approved_paid_call": body.get("approved_paid_call") is True,
                        "max_output_tokens": body.get("max_output_tokens"),
                        "reasoning_effort": body.get("reasoning_effort"),
                    },
                )
            response = str(gateway_answer.get("response") or "")
            status = str(gateway_answer.get("status") or "ANSWERED_FALLBACK")
            provider_state = str(gateway_answer.get("provider_state") or provider_state)
            provider = dict(provider)
            provider["provider"] = gateway_answer.get("provider") or provider.get("provider")
            provider["response_source"] = gateway_answer.get("response_source")
            provider["model"] = gateway_answer.get("model")
            provider["provider_mode"] = gateway_answer.get("provider_mode") or provider.get("provider_mode")
            provider["model_name"] = gateway_answer.get("model_name") or gateway_answer.get("model") or provider.get("model_name")
            provider["model_quality"] = gateway_answer.get("model_quality") or provider.get("model_quality")
            provider["reasoning_policy"] = gateway_answer.get("reasoning_policy") or provider.get("reasoning_policy")
            provider["model_suitable_for_governance"] = gateway_answer.get("model_suitable_for_governance")
            provider["model_quality_warning"] = gateway_answer.get("model_quality_warning") or provider.get("model_quality_warning")
            provider["provider_id"] = gateway_answer.get("provider_id") or provider.get("provider_id")
            provider["cost_mode"] = gateway_answer.get("cost_mode")
            provider["answer_source"] = gateway_answer.get("answer_source")
            provider["persona_enforced"] = gateway_answer.get("persona_enforced")
            provider["expert_roles_applied"] = gateway_answer.get("expert_roles_applied")
            provider["provider_error_category"] = gateway_answer.get("provider_error_category")
            provider["provider_error_message_safe"] = gateway_answer.get("provider_error_message_safe")
            if not response.strip():
                evidence_graph = context.get("evidence_graph") or {}
                providers = context.get("provider_readiness") or {}
                action_center = context.get("action_center") or {}
                items = action_center.get("items") or []
                missing = evidence_graph.get("missing_evidence") or []
                response = "\n".join(
                    [
                        "No external model answer was available; this is a deterministic advisory fallback.",
                        f"Question: {question or 'No question supplied.'}",
                        f"Provider state: {provider_state}.",
                        f"Operator blockers loaded: {len(items)}.",
                        f"Provider count: {providers.get('provider_count', 0)}; missing credentials: {providers.get('missing_credentials_count', 0)}.",
                        f"Missing evidence: {', '.join(str(item) for item in missing[:6]) or 'none loaded'}.",
                        "Next safest action: review blockers and evidence labels before any bounded PAPER experiment. Unknown P&L, fees, fills, TCA, and market truth remain unknown.",
                    ]
                )
            refusal_reason = None
        provider_mode = str(provider.get("provider_mode") or model_policy.get("provider_mode") or "DETERMINISTIC_FALLBACK")
        if status == "REFUSED":
            provider_mode = "DETERMINISTIC_FALLBACK"
        model_name = provider.get("model_name") or provider.get("model") or model_policy.get("model_name")
        model_quality = str(provider.get("model_quality") or model_policy.get("model_quality") or "FALLBACK_ONLY")
        reasoning_policy = str(provider.get("reasoning_policy") or model_policy.get("reasoning_policy") or "FALLBACK_ONLY_LIMITED")
        model_suitable = provider.get("model_suitable_for_governance")
        if model_suitable is None:
            model_suitable = model_policy.get("model_suitable_for_governance") is True
        if model_quality != "HIGH_REASONING" and classification.get("allowed") is True:
            limited = "I can give a limited operational answer, but final quant/risk/governance judgment requires the high-reasoning model."
            if limited not in response:
                response = f"{limited}\n{response}".strip()
        known_facts, unknowns = self._ai_answer_facts(mode, context)
        next_step = self._ai_next_step(mode, context, page_id)
        route_decision = gateway_answer.get("route_decision") if isinstance(gateway_answer, dict) else {}
        route_decision = route_decision if isinstance(route_decision, dict) else {}
        route_reason = str(route_decision.get("reason_code") or "")
        answer_source_for_truth = str(provider.get("answer_source") or provider.get("response_source") or "")
        local_truth_fallback = (
            (mode in {"RUN_PLANNER", "TRADING_SYSTEMS_AUDITOR"} or simple_health_question)
            and answer_source_for_truth in {"LOCAL_DETERMINISTIC", "DETERMINISTIC_FALLBACK_NO_MODEL_CALL", "DETERMINISTIC_FALLBACK_MODEL_POLICY"}
        )
        if classification.get("allowed") is True and (local_truth_fallback or route_reason in {
            "HIGH_REASONING_API_APPROVAL_REQUIRED",
            "SERIOUS_PROMPT_REQUIRES_HIGH_REASONING_OR_PACKET",
            "NO_SILENT_DOWNGRADE_TO_LOWER_REASONING_MODEL",
        }):
            response = self._ai_current_truth_operational_answer(mode, question, known_facts, unknowns, next_step, context)
        empty_model_answer = response.strip() == "Provider returned an empty advisory response."
        if empty_model_answer:
            status = "PROVIDER_ERROR"
            provider_state = "PROVIDER_ERROR"
            provider_mode = "PROVIDER_ERROR"
            model_quality = "UNKNOWN"
            reasoning_policy = "FALLBACK_ONLY_LIMITED"
            model_suitable = False
            provider["response_source"] = "PROVIDER_ERROR_EMPTY_MODEL_RESPONSE"
            response = self._ai_limited_operational_answer(mode, question, known_facts, unknowns, next_step)
        needs_codex = mode in {"CODEX_PACKET_ADVISOR", "QUANT_ENGINEER", "TRADING_SYSTEMS_AUDITOR"} or "codex" in question.lower()
        codex_summary = (
            "Draft a scoped Codex packet preserving no-live/no-broker-mutation rules and asking for evidence-backed operator/quant repair."
            if needs_codex else None
        )
        return {
            "source": "AI_QUANT_RESEARCH_CHIEF_ASK",
            "status": status,
            "provider_state": provider_state,
            "provider": provider.get("provider") or "disabled",
            "provider_id": provider.get("provider_id") or provider.get("provider") or "disabled",
            "provider_mode": provider_mode,
            "response_source": provider.get("response_source") or (
                "DETERMINISTIC_FALLBACK_NO_MODEL_CALL" if provider_state != "MOCK_MODE" else "MOCK_MODE_DETERMINISTIC"
            ),
            "answer_source": provider.get("answer_source") or provider.get("response_source") or "LOCAL_DETERMINISTIC",
            "cost_mode": provider.get("cost_mode") or "FREE_LOCAL",
            "model": provider.get("model") or model_name,
            "model_name": model_name,
            "model_quality": model_quality,
            "reasoning_policy": reasoning_policy,
            "model_suitable_for_governance": bool(model_suitable),
            "governance_suitable": bool(model_suitable),
            "persona_enforced": provider.get("persona_enforced") is not False,
            "expert_roles_applied": provider.get("expert_roles_applied") or [],
            "provider_error_category": provider.get("provider_error_category"),
            "provider_error_message_safe": provider.get("provider_error_message_safe"),
            "route_decision": gateway_answer.get("route_decision") if isinstance(gateway_answer, dict) else {},
            "question": question,
            "answer": response,
            "response": response,
            "mode": mode,
            "evidence_level": evidence_level,
            "known_facts": known_facts,
            "unknowns": unknowns,
            "next_step_label": next_step["label"],
            "next_step_page": next_step["page"],
            "next_step_control_id": next_step["control_id"],
            "needs_codex_packet": needs_codex,
            "suggested_codex_packet_summary": codex_summary,
            "classification": classification,
            "refusal_reason": refusal_reason,
            "page_context": {
                "page_id": page_context.get("page_id"),
                "page_title": page_context.get("page_title"),
                "data_source": page_context.get("data_source"),
                "raw_logs_included": False,
                "secrets_values_exposed": False,
            },
            "context": {
                "context_version": context["context_version"],
                "scope": context.get("scope"),
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
            "raw_logs_included": False,
            "secrets_values_exposed": False,
            "secrets_exposed": False,
        }

    def ai_routing_settings_save(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        result = self.ai_router_settings_store.save(
            payload or {},
            defaults=self._default_ai_router_settings(),
        )
        if result.get("status") == "SAVED":
            self.ai_routing_settings = dict(result["settings"])
            self.ai_routing_settings_source = str(result.get("settings_source") or "PERSISTED_LOCAL_SETTINGS")
        else:
            self.ai_routing_settings_source = "IN_MEMORY_UNSAVED"
        self.ai_routing_settings_last_result = result
        return {
            "source": "AI_ROUTER_SETTINGS",
            "status": result.get("status"),
            "settings": dict(self.ai_routing_settings),
            "settings_source": self.ai_routing_settings_source,
            "settings_path_relative": result.get("settings_path_relative"),
            "validation_errors": result.get("validation_errors") or [],
            "error_category": result.get("error_category"),
            "safe_error_message": result.get("safe_error_message"),
            "high_reasoning_api_requires_approval": True,
            "no_paid_call_occurred": True,
            "broker_call_occurred": False,
            "trading_mutation_occurred": False,
            "live_enabled": False,
            "real_money_enabled": False,
            "secrets_values_exposed": False,
        }

    def ai_router_settings(self) -> dict[str, Any]:
        provider_registry = self.ai_gateway.status().get("provider_registry") or {}
        providers = {
            str(row.get("provider_id")): {
                "provider_id": row.get("provider_id"),
                "status": row.get("status"),
                "configured": row.get("configured") is True,
                "credential_source": row.get("credential_source") or "NOT_CONFIGURED",
                "implemented": row.get("implemented") is True,
                "model_name": row.get("model_name"),
                "last_error_category": row.get("last_error_category"),
            }
            for row in provider_registry.get("providers") or []
            if isinstance(row, dict)
        }
        selected_ids = {
            str(self.ai_routing_settings.get("active_provider") or ""),
            str(self.ai_routing_settings.get("light_provider") or ""),
            str(self.ai_routing_settings.get("high_reasoning_provider") or ""),
            "local_openai_compatible",
            "deterministic_local",
            "supreme_board_packet",
        }
        return {
            **self.ai_routing_settings_last_result,
            "settings": dict(self.ai_routing_settings),
            "settings_source": self.ai_routing_settings_source,
            "provider_availability": {
                provider_id: providers.get(provider_id, {"provider_id": provider_id, "status": "UNKNOWN", "configured": False})
                for provider_id in sorted(provider_id for provider_id in selected_ids if provider_id)
            },
            "no_paid_call_occurred": True,
            "broker_call_occurred": False,
            "trading_mutation_occurred": False,
            "live_enabled": False,
            "real_money_enabled": False,
            "secrets_values_exposed": False,
        }

    def ai_providers_validate(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = payload or {}
        provider_id = str(body.get("provider_id") or "").strip().lower().replace("-", "_")
        model_name = str(body.get("model_name") or "").strip() or None
        validation_mode = str(body.get("validation_mode") or "credential_presence").strip()
        approved_paid_call = body.get("approved_paid_call") is True
        registry = self.ai_gateway.status().get("provider_registry") or {}
        providers = {row.get("provider_id"): row for row in registry.get("providers") or []}
        profile = providers.get(provider_id)
        if not profile:
            return {
                "source": "AI_PROVIDER_VALIDATION",
                "provider_id": provider_id,
                "configured": False,
                "credential_source": "UNKNOWN_PROVIDER",
                "model_name": model_name,
                "validation_status": "VALIDATION_FAILED",
                "error_category": "UNKNOWN_PROVIDER",
                "safe_error_message": "Unknown AI provider id.",
                "secrets_exposed": False,
                "secrets_values_exposed": False,
                "persona_enforced_possible": False,
                "broker_call_occurred": False,
                "trading_mutation_occurred": False,
                "live_enabled": False,
                "real_money_enabled": False,
            }
        configured = profile.get("configured") is True
        credential_source = str(profile.get("credential_source") or "NOT_CONFIGURED")
        if validation_mode == "minimal_test_call_with_approval" and not approved_paid_call:
            validation_status = "REFUSED_APPROVAL_REQUIRED"
            error_category = "APPROVAL_REQUIRED"
            safe_error = "Minimal provider test call may cost money and requires explicit one-call approval."
        elif not configured:
            validation_status = "MISSING_CREDENTIALS"
            error_category = "MISSING_CREDENTIALS"
            safe_error = "Required provider credential is missing from env/local credential vault."
        elif validation_mode == "minimal_test_call_with_approval":
            validation_status = "NOT_IMPLEMENTED"
            error_category = "SAFE_TEST_CALL_NOT_IMPLEMENTED"
            safe_error = "Credential is present, but this endpoint does not fake a paid provider test call."
        elif profile.get("implemented") is not True:
            validation_status = "NOT_IMPLEMENTED"
            error_category = "ADAPTER_NOT_IMPLEMENTED"
            safe_error = "Provider registry is scaffolded; live call adapter is not implemented."
        else:
            validation_status = "CONFIGURED"
            error_category = None
            safe_error = "Credential presence and metadata check passed without provider call."
        return {
            "source": "AI_PROVIDER_VALIDATION",
            "provider_id": provider_id,
            "configured": configured,
            "credential_source": credential_source,
            "model_name": model_name or profile.get("model_name") or profile.get("default_model"),
            "validation_mode": validation_mode,
            "validation_status": validation_status,
            "error_category": error_category,
            "safe_error_message": safe_error,
            "paid_call_occurred": False,
            "secrets_exposed": False,
            "secrets_values_exposed": False,
            "persona_enforced_possible": True,
            "broker_call_occurred": False,
            "trading_mutation_occurred": False,
            "live_enabled": False,
            "real_money_enabled": False,
        }

    def ai_supreme_board_packet(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = payload or {}
        question = str(body.get("question") or body.get("prompt") or "Review POVERTY_KILLER operator state.").strip()
        page_context = redact_secrets(body.get("page_context") if isinstance(body.get("page_context"), dict) else {})
        context = self._ai_context()
        result = self.ai_gateway.ask(
            question,
            context,
            page_context,
            routing={
                "route_mode": SUPREME_BOARD_PACKET_MODE,
                "provider_id": "supreme_board_packet",
                "model_name": "chatgpt-pro-manual",
                "approved_paid_call": False,
            },
        )
        return {
            "source": "SUPREME_BOARD_PACKET_BRIDGE",
            "status": "PACKET_READY",
            "packet": result.get("response") or result.get("answer") or "",
            "answer": result.get("response") or result.get("answer") or "",
            "provider_id": "supreme_board_packet",
            "answer_source": "SUPREME_BOARD_PACKET",
            "cost_mode": "CHATGPT_PRO_MANUAL",
            "persona_enforced": result.get("persona_enforced") is not False,
            "expert_roles_applied": result.get("expert_roles_applied") or [],
            "can_execute": False,
            "broker_call_occurred": False,
            "trading_mutation_occurred": False,
            "live_enabled": False,
            "real_money_enabled": False,
            "secrets_exposed": False,
            "secrets_values_exposed": False,
            "raw_logs_included": False,
        }

    def _ai_answer_facts(self, mode: str, context: dict[str, Any]) -> tuple[list[str], list[str]]:
        readiness = context.get("launch_readiness") or {}
        runtime = context.get("runtime") or {}
        portfolio = context.get("portfolio") or {}
        providers = context.get("provider_readiness") or {}
        facts = [
            "AI is advisory-only and can_execute=false.",
            f"Live status is {context.get('live_status') or 'LIVE_LOCKED'}; real-money remains blocked.",
            f"Provider readiness loaded: {providers.get('provider_count', 0)} providers, {providers.get('missing_credentials_count', 0)} missing credentials.",
        ]
        unknowns = [
            "Future profit is unknown and cannot be inferred from PAPER or historical tests alone.",
            "Unknown broker-confirmed fees, slippage, and TCA must stay unknown until evidence exists.",
        ]
        if mode == "PORTFOLIO_REVIEW":
            summary = portfolio.get("summary") if isinstance(portfolio.get("summary"), dict) else {}
            facts.append(f"Portfolio status: {portfolio.get('status') or 'UNKNOWN'}; positions={summary.get('position_count', 0)}; open_orders={summary.get('open_order_count', 0)}.")
            if portfolio.get("status") not in {"BROKER_CONFIRMED", "BROKER_CONFIRMED_EMPTY"}:
                unknowns.append(f"Broker portfolio truth unavailable: {portfolio.get('unavailable_reason') or 'UNKNOWN'}.")
        if mode in {"RUN_PLANNER", "TRADING_SYSTEMS_AUDITOR", "OPERATOR_GUIDE"}:
            facts.append(f"Launch readiness: {readiness.get('final_launch_readiness') or 'UNKNOWN'}.")
            if self._ai_ready_idle_no_active_runtime(context):
                facts.append("Current state: READY_IDLE_NO_ACTIVE_RUNTIME (ready/idle; no active PAPER run attached).")
            if runtime.get("supervisor_state"):
                facts.append(f"Supervisor: {runtime.get('supervisor_state')}.")
            if runtime.get("paper_start_allowed") is not None or readiness.get("paper_start_allowed") is not None:
                facts.append(f"Paper start allowed: {str(runtime.get('paper_start_allowed') is True or readiness.get('paper_start_allowed') is True).lower()}.")
            max_duration = runtime.get("max_paper_duration_seconds") or runtime.get("runner_max_paper_duration_seconds")
            if max_duration:
                facts.append(f"Max duration: {max_duration} seconds / {int(max_duration) // 86400 if int(max_duration) >= 86400 else 'less than 1'} day.")
            if readiness.get("reason_codes"):
                unknowns.append(f"Run blockers/warnings: {', '.join(str(item) for item in readiness.get('reason_codes') or [])}.")
            else:
                facts.append("Launch readiness reports no current blocker reason codes.")
            if self._ai_historical_duplicate_refusal(context):
                facts.append("Historical duplicate refusal exists as audit context, but it is not current start authority.")
            if self._ai_ready_idle_no_active_runtime(context):
                unknowns.append("No active DecisionFrame, NetEdge, fills, fees, or TCA evidence exists because no PAPER run is active.")
        return facts[:8], unknowns[:8]

    def _ai_current_truth_operational_answer(
        self,
        mode: str,
        question: str,
        known_facts: list[str],
        unknowns: list[str],
        next_step: dict[str, str | None],
        context: dict[str, Any],
    ) -> str:
        if self._ai_is_simple_health_question(question) and not self._ai_wants_detailed_answer(question):
            return self._ai_health_answer(context)
        if mode == "RUN_PLANNER":
            return self._ai_paper_readiness_answer(question, context)
        if not self._ai_wants_detailed_answer(question):
            return "\n".join(
                [
                    "Current backend truth:",
                    *[f"- {item}" for item in known_facts[:4]],
                    *([f"- {unknowns[0]}"] if unknowns else []),
                    f"Next step: {next_step.get('label') or 'Review the current page.'}",
                    "Safety: advisory-only; no broker calls; no live or real-money enablement.",
                ]
            )
        return "\n".join(
            [
                "I can answer from current backend truth. Final quant/risk/governance judgment still requires the high-reasoning model or a Supreme Board packet.",
                f"Question: {question or 'No question supplied.'}",
                f"Mode: {mode}.",
                "Current truth:",
                *[f"- {item}" for item in known_facts[:5]],
                "Missing or limited evidence:",
                *[f"- {item}" for item in unknowns[:4]],
                f"Next step: {next_step.get('label') or 'Review the current page.'}",
                "Safety: advisory-only, can_execute=false, no broker calls, no live or real-money enablement, no strategy or threshold mutation.",
            ]
        )

    def _ai_wants_detailed_answer(self, question: str) -> bool:
        lowered = str(question or "").lower()
        return any(term in lowered for term in ("full report", "details", "diagnostics", "audit", "deep dive", "explain fully"))

    def _ai_is_simple_health_question(self, question: str) -> bool:
        lowered = str(question or "").strip().lower()
        if not lowered:
            return False
        health_terms = ("are you alive", "you alive", "are we alive", "is the backend alive", "status check")
        return any(term in lowered for term in health_terms) and not self._ai_wants_detailed_answer(lowered)

    def _ai_should_answer_from_runtime_truth(self, mode: str, question: str) -> bool:
        if mode != "RUN_PLANNER" or self._ai_wants_detailed_answer(question):
            return False
        lowered = str(question or "").strip().lower()
        runtime_terms = (
            "can i do paper",
            "can i start paper",
            "can i run paper",
            "do paper run",
            "start paper",
            "paper ready",
            "ready for paper",
            "paper run",
        )
        return any(term in lowered for term in runtime_terms)

    def _ai_ready_idle_no_active_runtime(self, context: dict[str, Any]) -> bool:
        readiness = context.get("launch_readiness") or {}
        runtime = context.get("runtime") or {}
        return (
            readiness.get("final_launch_readiness") == "READY_FOR_BOUNDED_PAPER"
            and (readiness.get("paper_start_allowed") is True or runtime.get("paper_start_allowed") is True)
            and str(runtime.get("supervisor_state") or "").upper() == "IDLE"
            and bool(runtime.get("current_runtime_attached")) is False
        )

    def _ai_historical_duplicate_refusal(self, context: dict[str, Any]) -> bool:
        runtime = context.get("runtime") or {}
        return runtime.get("historical_refusal_reason") == "DUPLICATE_ACTIVE_RUN"

    def _ai_runtime_truth(self, context: dict[str, Any]) -> dict[str, Any]:
        readiness = context.get("launch_readiness") or {}
        runtime = context.get("runtime") or {}
        max_duration = runtime.get("max_paper_duration_seconds") or runtime.get("runner_max_paper_duration_seconds") or 86400
        try:
            max_duration_int = int(max_duration)
        except (TypeError, ValueError):
            max_duration_int = 86400
        blocking_codes = list(readiness.get("reason_codes") or []) if readiness.get("final_launch_readiness") == "BLOCKED" else []
        return {
            "launch": readiness.get("final_launch_readiness") or "UNKNOWN",
            "supervisor": runtime.get("supervisor_state") or "UNKNOWN",
            "paper_start_allowed": readiness.get("paper_start_allowed") is True or runtime.get("paper_start_allowed") is True,
            "live": "locked" if readiness.get("live_blocked") is not False else "UNKNOWN",
            "real_money": "blocked" if readiness.get("real_money_blocked") is not False else "UNKNOWN",
            "max_duration": max_duration_int,
            "blocking_codes": blocking_codes,
            "ready_idle": self._ai_ready_idle_no_active_runtime(context),
            "historical_duplicate": self._ai_historical_duplicate_refusal(context),
        }

    def _ai_next_action_for_blocker(self, reason_code: str) -> str:
        if reason_code == "alpaca_paper_credentials":
            return "Open Keys & Providers, save Alpaca PAPER credentials, then validate read-only."
        if reason_code == "paper_endpoint_only":
            return "Set APCA_API_BASE_URL to https://paper-api.alpaca.markets, then recheck launch readiness."
        if reason_code == "paper_start_authority":
            return "Open the Run PAPER page and review the current supervisor refusal reason."
        if reason_code == "audit_session_storage":
            return "Fix audit/session storage readiness before any PAPER start."
        return f"Review launch readiness reason code {reason_code} in the operator UI."

    def _ai_paper_readiness_answer(self, question: str, context: dict[str, Any]) -> str:
        truth = self._ai_runtime_truth(context)
        if truth["launch"] == "READY_FOR_BOUNDED_PAPER" and truth["paper_start_allowed"] is True:
            lines = [
                "Yes - our bot is ready for a bounded PAPER run based on current backend truth.",
                "",
                "Current backend truth:",
                f"- Launch readiness: {truth['launch']}",
                f"- Supervisor: {truth['supervisor']}",
                f"- Paper start allowed: {str(truth['paper_start_allowed']).lower()}",
                f"- Live: {truth['live']}",
                f"- Real money: {truth['real_money']}",
                f"- Max duration: {truth['max_duration']} seconds / 1 day",
                "",
                "Recommended first run: 10-20 minutes only.",
                "I cannot start it for you. Shan must click Start PAPER on the Run PAPER page.",
            ]
            if truth["ready_idle"]:
                lines.append("Current state: READY_IDLE_NO_ACTIVE_RUNTIME means ready/idle with no active PAPER run attached; it is not a blocker.")
            if truth["historical_duplicate"]:
                lines.append("Historical duplicate refusal exists as audit context, but it is not current start authority.")
            return "\n".join(lines)
        reason = str((truth["blocking_codes"] or ["UNKNOWN_BLOCKER"])[0])
        return "\n".join(
            [
                f"No - current blocker is {reason}.",
                f"Launch readiness: {truth['launch']}.",
                f"Paper start allowed: {str(truth['paper_start_allowed']).lower()}.",
                f"Next action: {self._ai_next_action_for_blocker(reason)}",
                "I cannot start PAPER, mutate state, call broker, enable live, or enable real money.",
            ]
        )

    def _ai_health_answer(self, context: dict[str, Any]) -> str:
        truth = self._ai_runtime_truth(context)
        ready_phrase = "and our bot is idle-ready" if truth["ready_idle"] else "but PAPER readiness is not fully ready"
        lines = [
            f"Yes. The backend is connected {ready_phrase}.",
            "",
            f"- Runtime: {truth['supervisor']} / no active PAPER run",
            f"- Launch readiness: {truth['launch']}",
            "- AI: advisory only",
            f"- Live: {truth['live']}",
            f"- Real money: {truth['real_money']}",
            "",
            "No PAPER run is currently active.",
        ]
        if truth["historical_duplicate"]:
            lines.append("Historical duplicate refusal exists as audit context, but it is not current start authority.")
        return "\n".join(lines)

    def _ai_limited_operational_answer(
        self,
        mode: str,
        question: str,
        known_facts: list[str],
        unknowns: list[str],
        next_step: dict[str, str | None],
    ) -> str:
        return "\n".join(
            [
                "PROVIDER ERROR - the configured high-reasoning model returned no usable text, so this is a limited operational fallback.",
                "I can give a limited operational answer, but final quant/risk/governance judgment requires the high-reasoning model.",
                f"Question: {question or 'No question supplied.'}",
                f"Mode: {mode}.",
                "Known facts:",
                *[f"- {item}" for item in known_facts[:6]],
                "Unknowns / missing evidence:",
                *[f"- {item}" for item in unknowns[:6]],
                f"Next step: {next_step.get('label') or 'Review the current page.'}",
                f"Go to: {next_step.get('page') or 'current page'} / control: {next_step.get('control_id') or 'unknown'}.",
                "Do not treat this as final quant/risk/live-readiness judgment.",
            ]
        )

    def _ai_next_step(self, mode: str, context: dict[str, Any], page_id: str) -> dict[str, str | None]:
        readiness = context.get("launch_readiness") or {}
        provider_setup = context.get("provider_setup") if isinstance(context.get("provider_setup"), dict) else {}
        alpaca_missing = "alpaca_paper_credentials" in set(readiness.get("reason_codes") or [])
        if mode == "SETUP_HELP" or alpaca_missing:
            return {"label": "Open Keys & Providers and save/validate Alpaca PAPER credentials.", "page": "providers", "control_id": "credential_save_alpaca_paper"}
        if mode == "PORTFOLIO_REVIEW":
            return {"label": "Review Portfolio Home positions, exposure, open orders, and unavailable broker truth.", "page": "positions", "control_id": "positions_preview_table"}
        if mode == "RUN_PLANNER":
            if readiness.get("final_launch_readiness") == "READY_FOR_BOUNDED_PAPER" and readiness.get("paper_start_allowed") is True:
                return {"label": "Recommended first run: 10-20 minutes. I cannot start it; Shan must click Start PAPER.", "page": "command", "control_id": "paper_start"}
            reason = str((readiness.get("reason_codes") or ["UNKNOWN_BLOCKER"])[0])
            return {"label": f"Do not start PAPER until {reason} is resolved.", "page": "command", "control_id": "paper_start"}
        if mode == "CODEX_PACKET_ADVISOR":
            return {"label": "Draft a scoped Codex packet with exact blocker, file area, tests, and safety limits.", "page": "ai", "control_id": "ai_ask"}
        if mode == "TRADING_SYSTEMS_AUDITOR":
            return {"label": "Audit readiness, provider status, portfolio truth, P&L/TCA, and blocked controls before any run.", "page": page_id or "diagnostics", "control_id": "ai_ask"}
        if provider_setup.get("configured_count") == 0:
            return {"label": "Configure required providers before relying on model or broker answers.", "page": "providers", "control_id": "credential_save_alpaca_paper"}
        return {"label": "Review the current page summary and ask a narrower follow-up if evidence is missing.", "page": page_id or "positions", "control_id": "ai_ask"}

    def _ai_light_context(self) -> dict[str, Any]:
        launch = self.launch_readiness()
        providers = self.providers_readiness()
        return redact_secrets(
            {
                "context_version": "ai-chief-light-context-v1",
                "scope": "operator_status_and_local_guide",
                "readiness": self.readiness(),
                "launch_readiness": launch,
                "provider_readiness": providers,
                "provider_setup": self.credentials_providers(),
                "health": self.health(),
                "runtime": self.runtime(),
                "portfolio": {
                    "status": "PAGE_CONTEXT_OR_PORTFOLIO_ENDPOINT_REQUIRED",
                    "detail": "Light AI context does not call broker. Use Portfolio Home or /operator/portfolio for broker-confirmed holdings.",
                    "broker_read_occurred": False,
                    "broker_mutation_occurred": False,
                },
                "live_status": "LIVE_LOCKED",
                "real_money_blocked": True,
                "raw_logs_included": False,
                "secrets_values_exposed": False,
                "advisory_only": True,
                "can_execute": False,
                "broker_call_occurred": False,
                "trading_mutation_occurred": False,
            }
        )

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
        context["provider_setup"] = self.credentials_providers()
        context["launch_readiness"] = self.launch_readiness()
        context["runtime"] = self.runtime()
        context["portfolio"] = {
            "status": "PAGE_CONTEXT_OR_PORTFOLIO_ENDPOINT_REQUIRED",
            "detail": "AI context does not call broker. Use existing UI page context or /operator/portfolio endpoint output.",
            "broker_read_occurred": False,
            "broker_mutation_occurred": False,
        }
        context["model_policy"] = self.ai_gateway.status().get("model_policy")
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

    @router.get("/credentials/diagnostics")
    def credentials_diagnostics() -> dict[str, Any]:
        return provider.credentials_diagnostics()

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

    @router.get("/historical-tests")
    def historical_tests() -> dict[str, Any]:
        return provider.historical_tests()

    @router.post("/historical-tests/run")
    def historical_test_run(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return provider.historical_test_run(payload)

    @router.get("/historical-tests/{test_id}/report")
    def historical_test_report(test_id: str) -> dict[str, Any]:
        return provider.historical_test_report(test_id)

    @router.get("/historical-tests/{test_id}")
    def historical_test_detail(test_id: str) -> dict[str, Any]:
        return provider.historical_test_detail(test_id)

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

    @router.post("/ai/ask")
    def ai_ask(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return provider.ai_ask(payload)

    @router.get("/ai/router/settings")
    def ai_router_settings() -> dict[str, Any]:
        return provider.ai_router_settings()

    @router.post("/ai/router/settings")
    def ai_router_settings_save(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return provider.ai_routing_settings_save(payload)

    @router.get("/ai/routing/settings")
    def ai_routing_settings() -> dict[str, Any]:
        return provider.ai_router_settings()

    @router.post("/ai/routing/settings")
    def ai_routing_settings_save(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return provider.ai_routing_settings_save(payload)

    @router.post("/ai/providers/validate")
    def ai_providers_validate(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return provider.ai_providers_validate(payload)

    @router.post("/ai/supreme-board-packet")
    def ai_supreme_board_packet(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return provider.ai_supreme_board_packet(payload)

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
    "OPERATOR_ACTIVATION_VERSION",
    "OperatorSnapshotProvider",
    "READ_ONLY_CONTRACTS",
    "create_operator_app",
    "get_operator_router",
]
