"""Governed operator API skeleton for the Operator Control Panel.

This module deliberately does not import or call broker, execution, OMS, or
strategy code. It exposes contract-shaped status/readiness data plus governed
PAPER process intents so the UI can be wired without becoming a second trading
engine or direct broker control surface.
"""

from __future__ import annotations

import atexit
import asyncio
import json
import os
import re
import secrets
import signal
import subprocess
import threading
import time
import uuid
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import anyio.to_thread
from fastapi import APIRouter, FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
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
)
from app.ai_chief_operator.quant_persona import (
    MODEL_IDENTITY_TERMS,
    draft_codex_packet,
    build_quant_review_recommendation,
    classify_quant_prompt,
    quant_persona_summary,
)
from app.operator_activation.launch_readiness import build_launch_readiness
from app.operator_activation.paper_baseline import (
    BASELINE_POLICY_PROTECTED,
    PaperBaselineStore,
    build_baseline_adoption_state,
)
from app.api.operator_paper_supervisor import OperatorPaperSupervisor, PaperSupervisorConfig
from app.api.operator_runtime_config import OperatorRuntimeConfig
from app.api.operator_snapshot_store import OperatorPerfRecorder, OperatorSnapshotStore
from app.operator_credentials.store import (
    ALPACA_ENDPOINT_SOURCE_ENV_KEY,
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
from app.operator_intelligence.system_map import (
    SYSTEM_MAP_SUMMARY,
    authority_graph_summary,
    render_system_map_markdown,
)
from app.operator_intelligence.watchdog import AlertQueue, build_watchdog_alerts
from app.run_visibility import read_run_visibility_snapshot, render_run_visibility_html


ANSWER_MODE_DETERMINISTIC = "DETERMINISTIC"
ANSWER_MODE_AI_CHAT_MODEL = "AI_CHAT_MODEL"
ANSWER_MODE_AI_REASONING_STRATEGY = "AI_REASONING_STRATEGY"
ANSWER_MODES = {
    ANSWER_MODE_DETERMINISTIC,
    ANSWER_MODE_AI_CHAT_MODEL,
    ANSWER_MODE_AI_REASONING_STRATEGY,
}
AI_UNKNOWN_EVIDENCE_MESSAGE = "Unknown because this evidence is missing."
AI_EVIDENCE_CONTRACT_SCHEMA = "ai-chief-evidence-contract-v1"


def normalize_ai_answer_mode(value: Any) -> tuple[str, str]:
    raw = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
    if not raw:
        return ANSWER_MODE_DETERMINISTIC, "DEFAULTED_DETERMINISTIC"
    aliases = {
        "LOCAL": ANSWER_MODE_DETERMINISTIC,
        "LOCAL_GUIDE": ANSWER_MODE_DETERMINISTIC,
        "DETERMINISTIC_LOCAL": ANSWER_MODE_DETERMINISTIC,
        "CHAT": ANSWER_MODE_AI_CHAT_MODEL,
        "AI_CHAT": ANSWER_MODE_AI_CHAT_MODEL,
        "MODEL": ANSWER_MODE_AI_CHAT_MODEL,
        "AI_MODEL": ANSWER_MODE_AI_CHAT_MODEL,
        "LIGHT_API": ANSWER_MODE_AI_CHAT_MODEL,
        "REASONING": ANSWER_MODE_AI_REASONING_STRATEGY,
        "AI_REASONING": ANSWER_MODE_AI_REASONING_STRATEGY,
        "AI_STRATEGY": ANSWER_MODE_AI_REASONING_STRATEGY,
        "STRATEGY": ANSWER_MODE_AI_REASONING_STRATEGY,
        "HIGH_REASONING": ANSWER_MODE_AI_REASONING_STRATEGY,
        "HIGH_REASONING_API": ANSWER_MODE_AI_REASONING_STRATEGY,
        "HIGH_REASONING_API_WITH_APPROVAL": ANSWER_MODE_AI_REASONING_STRATEGY,
    }
    normalized = aliases.get(raw, raw)
    if normalized in ANSWER_MODES:
        return normalized, "VALID"
    return ANSWER_MODE_DETERMINISTIC, "UNKNOWN_FELL_BACK_TO_DETERMINISTIC"
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
OPERATOR_UI_ASSET_VERSION = "ui4-enforce-unblock"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_git_output(repo_root: Path, args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            text=True,
            timeout=1.5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "UNKNOWN_NOT_AVAILABLE"
    if result.returncode != 0:
        return "UNKNOWN_NOT_AVAILABLE"
    return result.stdout.strip() or "UNKNOWN_NOT_AVAILABLE"


class NoStoreStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store, max-age=0, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response


def _with_no_store_headers(response: HTMLResponse) -> HTMLResponse:
    response.headers["Cache-Control"] = "no-store, max-age=0, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


def _render_operator_ui_index(ui_dir: Path, version: str) -> str:
    html = (ui_dir / "index.html").read_text(encoding="utf-8")
    safe_build_version = re.sub(r"[^A-Za-z0-9._-]", "", version or "") or "UNKNOWN_NOT_AVAILABLE"
    safe_asset_version = f"{safe_build_version}-{OPERATOR_UI_ASSET_VERSION}"
    for asset in ("styles.css", "mock-data.js", "app.js"):
        html = re.sub(rf'{re.escape(asset)}\?v=[^"]+', f"{asset}?v={safe_asset_version}", html)
        html = html.replace(f'{asset}"', f'{asset}?v={safe_asset_version}"')
    build_script = (
        f'<script>window.PK_OPERATOR_UI_BUILD_COMMIT = "{safe_build_version}";'
        f'window.PK_OPERATOR_UI_ASSET_VERSION = "{safe_asset_version}";</script>'
    )
    if "window.PK_OPERATOR_UI_BUILD_COMMIT" not in html:
        html = html.replace("    <script src=", f"    {build_script}\n    <script src=", 1)
    return html


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
    "view_models": {
        "run_paper_operator_state": {
            "source": "OPERATOR_PAPER_CONTROL_STATE_DERIVED_VIEW",
            "canonical_authority": "OPERATOR_PAPER_CONTROL_STATE",
            "endpoint": "/operator/paper-control-state",
            "schema_version": "run-paper-command-center-v1",
            "main_answer_plain_english": True,
            "raw_codes_in_advanced_details": True,
            "uses_existing_governed_start_intent": "/operator/intent/paper/start",
            "can_execute": False,
            "broker_mutation_occurred": False,
            "trading_mutation_occurred": False,
            "live_enabled": False,
            "real_money_enabled": False,
            "secrets_values_exposed": False,
            "paper_credential_setup": {
                "schema_version": "paper-credential-setup-v1",
                "canonical_credential_authority": "ALPACA_PAPER_ENV_FILE_ONLY",
                "approved_secret_path": "~/.poverty_killer_alpaca_paper_env",
                "credential_precedence": "ALPACA_PAPER_ENV_FILE_ONLY",
                "read_only_preflight_authorized": False,
                "read_only_preflight_checks": ["GET /v2/account", "GET /v2/orders?status=open", "GET /v2/positions"],
                "alpaca_network_call_occurred": False,
                "broker_mutation_occurred": False,
                "secrets_values_exposed": False,
            },
            "paper_baseline": {
                "schema_version": "paper-baseline-view-v1",
                "canonical_authority": "OPERATOR_PAPER_BASELINE",
                "default_policy": BASELINE_POLICY_PROTECTED,
                "endpoint": "/operator/paper-baseline",
                "accept_endpoint": "/operator/paper-baseline/accept",
                "local_acceptance_only": True,
                "alpaca_network_call_occurred": False,
                "broker_mutation_occurred": False,
                "secrets_values_exposed": False,
            },
        }
    },
    "endpoints": {
        "/operator/status": "read_only_runtime_status",
        "/operator/health": "read_only_operator_health",
        "/operator/launcher-status": "read_only_fast_launcher_status",
        "/operator/version": "read_only_backend_ui_version",
        "/operator/runtime-minimal": "read_only_fast_runtime_minimal",
        "/operator/perf/recent": "read_only_operator_perf_recent",
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
        "/operator/cockpit/capabilities": "read_only_operator_cockpit_feature_gates",
        "/operator/cockpit/asset-mandate": "local_operator_mandate_view_gate_no_trading_mutation",
        "/operator/cockpit/day-trader-mode": "local_operator_day_trader_gate_no_strategy_mutation",
        "/operator/paper-control-state": "canonical_run_paper_control_state",
        "/operator/run-visibility": "read_only_local_paper_run_visibility_page",
        "/operator/run-visibility/status": "read_only_local_paper_run_visibility_status",
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
        "/operator/paper-baseline": "read_only_local_paper_baseline_adoption_state",
        "/operator/paper-baseline/accept": "local_operator_baseline_acceptance_no_broker_call",
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
        "/operator/intent/stack/shutdown": "server_authorized_process_only_stack_shutdown",
    },
    "disabled_intents": {
        "/operator/intent/paper/start": "SERVER_AUTHORIZED_PAPER_SUPERVISOR",
        "/operator/intent/paper/stop": "SERVER_AUTHORIZED_PAPER_SUPERVISOR",
        "/operator/intent/paper/reconcile-stale": "SERVER_AUTHORIZED_STALE_SESSION_RECONCILIATION",
        "/operator/intent/stack/shutdown": "SERVER_AUTHORIZED_PROCESS_ONLY_STACK_SHUTDOWN",
        "/operator/intent/snapshot/export": "SNAPSHOT_EXPORT_NOT_EXPOSED_IN_OPERATOR_UI",
        "/operator/intent/live/request-enable": "LIVE_NOT_APPROVED",
        "/operator/intent/live/start": "LIVE_NOT_APPROVED",
        "/operator/intent/emergency-stop": "EMERGENCY_STOP_NOT_EXPOSED_IN_OPERATOR_UI",
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
        stack_exit_callback: Callable[[], None] | None = None,
    ) -> None:
        if runtime_config is not None:
            self.runtime_config = runtime_config
        elif supervisor is not None:
            self.runtime_config = OperatorRuntimeConfig.from_env(provider_env or {}, repo_root=supervisor.config.repo_root)
        else:
            self.runtime_config = OperatorRuntimeConfig.from_env()
        self.process_start_time = _utc_now()
        self.process_start_monotonic = time.monotonic()
        self.loaded_git_commit_short = _safe_git_output(self.runtime_config.repo_root, ["rev-parse", "--short", "HEAD"])
        self.loaded_git_branch = _safe_git_output(self.runtime_config.repo_root, ["branch", "--show-current"])
        self.snapshot_store = OperatorSnapshotStore()
        self.perf_recorder = OperatorPerfRecorder()
        self._paper_control_state_lock = threading.Lock()
        self.process_env = provider_env if provider_env is not None else dict(os.environ)
        self.credential_store = credential_store or LocalCredentialStore(
            default_credential_store_path(self.runtime_config.repo_root)
        )
        self.provider_env = self.credential_store.effective_env(self.process_env)
        self.provider_env.update(self.credential_store.effective_provider_values("alpaca_paper", self.process_env))
        self.portfolio_client = portfolio_client
        self._latest_portfolio_snapshot: dict[str, Any] | None = None
        self._latest_portfolio_snapshot_at_monotonic: float | None = None
        self.paper_baseline_store = PaperBaselineStore(self.runtime_config.operator_state_dir / "paper_baseline.json")
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
        self._shutdown_lock = threading.Lock()
        self._shutdown_requested = False
        self._shutdown_hook_installed = False
        self._previous_signal_handlers: dict[int, Any] = {}
        self._stack_exit_callback = stack_exit_callback or self._default_stack_exit_callback

    def _backend_process_identity(self) -> dict[str, Any]:
        return {
            "git_commit_short": self.loaded_git_commit_short,
            "git_branch": self.loaded_git_branch,
            "process_start_time": self.process_start_time,
            "backend_pid": os.getpid(),
            "app_version": OPERATOR_ACTIVATION_VERSION,
            "source_commit": self.loaded_git_commit_short,
            "backend_repo_root": str(self.runtime_config.repo_root),
            "secrets_values_exposed": False,
        }

    def install_process_shutdown_hooks(self) -> dict[str, Any]:
        if self._shutdown_hook_installed:
            return {
                "status": "ALREADY_INSTALLED",
                "signals": sorted(self._previous_signal_handlers.keys()),
                "atexit_registered": True,
            }
        atexit.register(self.shutdown_runtime, "ATEXIT")
        installed_signals: list[int] = []
        for sig in (getattr(signal, "SIGTERM", None), getattr(signal, "SIGINT", None)):
            if sig is None:
                continue
            try:
                previous = signal.getsignal(sig)
                self._previous_signal_handlers[int(sig)] = previous

                def _handler(signum, frame, _previous=previous):
                    self.shutdown_runtime(f"SIGNAL_{signal.Signals(signum).name}")
                    if callable(_previous):
                        return _previous(signum, frame)
                    if _previous == signal.SIG_DFL:
                        raise SystemExit(128 + int(signum))
                    return None

                signal.signal(sig, _handler)
                installed_signals.append(int(sig))
            except (ValueError, OSError, RuntimeError):
                continue
        self._shutdown_hook_installed = True
        return {
            "status": "INSTALLED",
            "signals": installed_signals,
            "atexit_registered": True,
        }

    def shutdown_runtime(self, reason: str = "API_SHUTDOWN") -> dict[str, Any]:
        with self._shutdown_lock:
            if self._shutdown_requested:
                return {
                    "intent": "process_lifecycle_shutdown",
                    "allowed": True,
                    "status": "ALREADY_REQUESTED",
                    "reason_code": "SHUTDOWN_ALREADY_REQUESTED",
                    "broker_call_occurred": False,
                    "broker_mutation_occurred": False,
                    "live_endpoint_touched": False,
                    "real_money_touched": False,
                    "secrets_values_exposed": False,
                }
            self._shutdown_requested = True
        return self.supervisor.shutdown_active_processes(reason)

    def _default_stack_exit_callback(self) -> None:
        def _exit_after_response() -> None:
            time.sleep(0.35)
            os._exit(0)

        threading.Thread(target=_exit_after_response, name="operator-stack-shutdown", daemon=True).start()

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
        paper_env = {
            key: str(value)
            for key, value in effective_env.items()
            if key in {"APCA_API_KEY_ID", "APCA_API_SECRET_KEY", "APCA_API_BASE_URL", ALPACA_ENDPOINT_SOURCE_ENV_KEY} and str(value).strip()
        }
        endpoint_authority = alpaca_endpoint_authority(paper_env)
        if endpoint_authority["paper_endpoint_only"] is True:
            paper_env["APCA_API_BASE_URL"] = str(endpoint_authority["alpaca_endpoint_display"])
            if endpoint_authority["alpaca_endpoint_configured"] is False:
                paper_env[ALPACA_ENDPOINT_SOURCE_ENV_KEY] = "SAFE_DEFAULT_PAPER_ENDPOINT"
        return paper_env

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

    def _supervisor_health_state(self) -> str:
        session = getattr(self.supervisor, "_session", None)
        status = str(getattr(session, "status", "") or "").strip().upper()
        if status in {"STARTING", "RUNNING", "STOP_REQUESTED"}:
            return "RUNNING"
        if status == "PROCESS_STATE_UNKNOWN_AFTER_RESTART":
            return "STALE_ACTIVE_SESSION"
        return "IDLE"

    def _local_supervisor_summary(self) -> dict[str, Any]:
        session = getattr(self.supervisor, "_session", None)
        session_dict = session.as_dict() if session else None
        raw_status = str(getattr(session, "status", "") or "").strip().upper()
        is_active = raw_status in {"STARTING", "RUNNING", "STOP_REQUESTED"}
        stale_after_restart = raw_status == "PROCESS_STATE_UNKNOWN_AFTER_RESTART"
        state = "RUNNING" if is_active else ("STALE_ACTIVE_SESSION" if stale_after_restart else "IDLE")
        paper_key_refusal = self.supervisor._paper_key_refusal()
        endpoint_authority = self.supervisor._paper_endpoint_authority()
        return {
            "supervisor_version": getattr(self.supervisor, "__class__", type("Unknown", (), {})).__name__,
            "state": state,
            "active_session": session_dict if is_active else None,
            "latest_session": session_dict,
            "active_session_id": getattr(session, "session_id", None) if is_active and session else None,
            "paper_start_allowed": state == "IDLE",
            "paper_stop_allowed": is_active,
            "paper_start_refusal_reason": (
                "DUPLICATE_ACTIVE_RUN" if is_active else (
                    "PREVIOUS_SESSION_STATE_UNKNOWN_AFTER_RESTART" if stale_after_restart else None
                )
            ),
            "paper_stop_refusal_reason": None if is_active else "NO_ACTIVE_RUN",
            "paper_credentials_configured": paper_key_refusal is None,
            "paper_credential_refusal_reason": paper_key_refusal,
            "paper_credential_source": "CANONICAL_PAPER_ENV_FILE" if paper_key_refusal is None else "MISSING_OR_INVALID",
            "paper_endpoint_only": endpoint_authority["paper_endpoint_only"],
            "paper_endpoint_status": endpoint_authority["status"],
            "paper_endpoint_source": endpoint_authority["endpoint_source"],
            "paper_endpoint_refusal_reason": endpoint_authority["reason_code"],
            "paper_endpoint_operator_action": endpoint_authority["operator_action"],
            "paper_endpoint_authority": endpoint_authority,
            "broker_read_permission_profile": self.supervisor._broker_read_profile().to_dict(),
            "paper_baseline_runtime_context": {
                "source": "NOT_ON_STATUS_FAST_PATH",
                "baseline_required": None,
                "baseline_loaded": None,
                "same_symbol_baseline_guard_active": None,
            },
            "allowed_profile": self.supervisor.config.allowed_profile,
            "allowed_watchlist": list(self.supervisor.config.allowed_watchlist),
            "allowed_durations": sorted(self.supervisor.config.allowed_durations),
            "min_paper_duration_seconds": self.supervisor.config.min_paper_duration_seconds,
            "max_paper_duration_seconds": self.supervisor.config.max_paper_duration_seconds,
            "runner_max_paper_duration_seconds": self.supervisor.config.max_paper_duration_seconds,
            "duration_authority": "scripts/run_bounded_paper.ps1",
            "session_store": {"status": "NOT_ON_FAST_LOCAL_STATUS_PATH"},
            "local_only": True,
            "broker_call_occurred": False,
            "broker_mutation_occurred": False,
        }

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
        supervisor = self._local_supervisor_summary()
        active = supervisor.get("active_session") or {}
        latest = supervisor.get("latest_session") or {}
        session_status = active.get("status")
        active_profile = active.get("profile") or "PAPER_IDLE"
        watchlist = active.get("watchlist") or []
        process_state = session_status or "IDLE_NO_ACTIVE_PAPER_RUN"
        paper_start_allowed = supervisor.get("paper_start_allowed") is True
        ready_idle = not watchlist and paper_start_allowed and supervisor.get("state") == "IDLE"
        historical_refusal = self._latest_historical_refusal(supervisor)
        runtime_attachment_state = "READY_IDLE_NO_ACTIVE_PAPER_RUN" if ready_idle else process_state
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
            **self._backend_process_identity(),
            "bot_status": process_state,
            "runtime_mode": "PAPER",
            "mode_state": "PAPER_ENABLED",
            "capability_state": "PAPER_ENABLED",
            "active_profile": active_profile,
            "broker": "alpaca_paper",
            "endpoint": "https://paper-api.alpaca.markets",
            "market_data": "IDLE_NO_ACTIVE_MARKET_DATA_RUNTIME",
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
        started_ns = time.perf_counter_ns()
        supervisor_state = self._supervisor_health_state()
        elapsed_ms = round((time.perf_counter_ns() - started_ns) / 1_000_000, 3)
        timestamp_utc = _utc_now()
        identity = self._backend_process_identity()
        return {
            "ok": True,
            "api_status": "OK",
            "api_version": API_VERSION,
            "operator_activation_version": OPERATOR_ACTIVATION_VERSION,
            **identity,
            "repo_head": self.loaded_git_commit_short,
            "branch": self.loaded_git_branch,
            "loaded_commit": self.loaded_git_commit_short,
            "loaded_branch": self.loaded_git_branch,
            "pid": os.getpid(),
            "uptime": self.process_start_time,
            "paper_only": True,
            "supervisor_status": supervisor_state,
            "session_store_status": "NOT_ON_HEALTH_FAST_PATH",
            "world_awareness_cache_status": "NOT_ON_HEALTH_FAST_PATH",
            "config_status": "NOT_ON_HEALTH_FAST_PATH",
            "log_dir_status": "NOT_ON_HEALTH_FAST_PATH",
            "data_dir_status": "NOT_ON_HEALTH_FAST_PATH",
            "runtime_profile": self.runtime_config.runtime_profile,
            "hosted_mode": self.runtime_config.hosted_mode,
            "live_status": "LIVE_LOCKED",
            "real_money_status": "BLOCKED",
            "broker_call_occurred": False,
            "secrets_values_exposed": False,
            "degraded_reasons": [],
            "world_awareness_runtime": {
                "manual_poll_only": True,
                "provider_polling_active": False,
                "provider_count": 0,
                "status": "NOT_ON_HEALTH_FAST_PATH",
            },
            "timestamp_utc": timestamp_utc,
            "updated_at": timestamp_utc,
            "elapsed_ms": elapsed_ms,
        }

    def launcher_status(self) -> dict[str, Any]:
        started_ns = time.perf_counter_ns()
        supervisor = self._local_supervisor_summary()
        identity = self._backend_process_identity()
        degraded_reasons: list[str] = []
        if self.loaded_git_commit_short == "UNKNOWN_NOT_AVAILABLE":
            degraded_reasons.append("GIT_HEAD_READ_FAILED")
        if self.loaded_git_branch == "UNKNOWN_NOT_AVAILABLE":
            degraded_reasons.append("GIT_BRANCH_READ_FAILED")
        elapsed_ms = round((time.perf_counter_ns() - started_ns) / 1_000_000, 3)
        return {
            "ok": not degraded_reasons,
            "api_status": "OK" if not degraded_reasons else "DEGRADED",
            **identity,
            "pid": os.getpid(),
            "repo_head": self.loaded_git_commit_short,
            "branch": self.loaded_git_branch,
            "loaded_commit": self.loaded_git_commit_short,
            "loaded_branch": self.loaded_git_branch,
            "process_start_time": self.process_start_time,
            "uptime_seconds": round(time.monotonic() - self.process_start_monotonic, 3),
            "paper_only": True,
            "live_locked": True,
            "real_money_blocked": True,
            "live_status": "LIVE_LOCKED",
            "real_money_status": "BLOCKED",
            "backend_mode": "PAPER_OPERATOR_API",
            "supervisor_state": supervisor.get("state") or "UNKNOWN",
            "active_run_id": supervisor.get("active_session_id"),
            "timestamp_utc": _utc_now(),
            "elapsed_ms": elapsed_ms,
            "degraded_reason_codes": degraded_reasons,
            "control_lane": True,
            "broker_call_occurred": False,
            "broker_mutation_occurred": False,
            "secrets_values_exposed": False,
        }

    def version(self) -> dict[str, Any]:
        return {
            "source": "OPERATOR_VERSION",
            "backend_commit": self.loaded_git_commit_short,
            "ui_build_commit": self.loaded_git_commit_short,
            "branch": self.loaded_git_branch,
            "api_version": API_VERSION,
            "operator_activation_version": OPERATOR_ACTIVATION_VERSION,
            "started_at_utc": self.process_start_time,
            "timestamp_utc": _utc_now(),
            "paper_only": True,
            "live_locked": True,
            "real_money_blocked": True,
            "secrets_values_exposed": False,
        }

    def runtime_minimal(self) -> dict[str, Any]:
        supervisor = self._local_supervisor_summary()
        return {
            "source": "OPERATOR_RUNTIME_MINIMAL",
            "supervisor_state": supervisor.get("state"),
            "active_run_id": supervisor.get("active_session_id"),
            "paper_stop_allowed": supervisor.get("paper_stop_allowed") is True,
            "paper_only": True,
            "live_locked": True,
            "real_money_blocked": True,
            "timestamp_utc": _utc_now(),
            "secrets_values_exposed": False,
            "broker_call_occurred": False,
            "broker_mutation_occurred": False,
        }

    def perf_recent(self) -> dict[str, Any]:
        return self.perf_recorder.recent()

    def snapshot_store_summary(self) -> dict[str, Any]:
        return self.snapshot_store.summary()

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
            "paper_baseline_store": self.paper_baseline_store.status(),
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
        historical_refusal = self._latest_historical_refusal(supervisor)
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

    def _latest_historical_refusal(self, supervisor: dict[str, Any]) -> dict[str, Any] | None:
        latest = supervisor.get("latest_session") if isinstance(supervisor.get("latest_session"), dict) else {}
        if latest and latest.get("status") == "REFUSED":
            return dict(latest)
        for session in self.supervisor.session_store.sessions():
            if session.get("status") == "REFUSED":
                return dict(session)
        for event in reversed(self.supervisor.session_store.audit_events()):
            if event.get("allowed") is False and event.get("reason_code"):
                return {
                    "status": "REFUSED",
                    "session_id": event.get("session_id"),
                    "requested_at": event.get("timestamp"),
                    "refusal_reason": event.get("reason_code"),
                    "source": "AUDIT_EVENT",
                }
        return None

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
            **self._backend_process_identity(),
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

    def cockpit_capabilities(self) -> dict[str, Any]:
        endpoint_authority = alpaca_endpoint_authority(self._paper_process_env(self._refresh_provider_env()))
        return {
            "source": "OPERATOR_COCKPIT_CAPABILITIES",
            "schema_version": "operator-cockpit-capabilities-v1",
            "active_asset_class": "crypto",
            "mandate_policy": {
                "switch_semantics": "NEXT_CAPITAL_ONLY_EXISTING_POSITIONS_RIDE",
                "existing_positions_liquidated": False,
                "manual_trade_controls_available": False,
                "server_authority_required": True,
                "detail": "Changing the cockpit mandate can only affect future capital allocation after a server-side feature gate allows it. Existing positions ride under governed exits; no liquidation, close, cancel, flatten, or manual order path is exposed.",
            },
            "asset_classes": [
                {
                    "id": "crypto",
                    "label": "Crypto",
                    "enabled": True,
                    "status": "ACTIVE",
                    "reason_code": "CRYPTO_MANDATE_ACTIVE",
                    "server_rejected": False,
                },
                {
                    "id": "equities",
                    "label": "Equities",
                    "enabled": False,
                    "status": "GATED",
                    "reason_code": "EQUITIES_FEATURE_FLAG_OFF",
                    "server_rejected": True,
                },
                {
                    "id": "auto",
                    "label": "Auto",
                    "enabled": False,
                    "status": "GATED",
                    "reason_code": "AUTO_MANDATE_FEATURE_FLAG_OFF",
                    "server_rejected": True,
                },
            ],
            "day_trader_mode": {
                "enabled": False,
                "status": "GATED",
                "reason_code": "DAY_TRADER_MODE_FEATURE_FLAG_OFF",
                "server_rejected": True,
                "strategy_wiring_active": False,
                "detail": "Day-trader mode is visible for operator planning only. The server rejects activation until a future Board packet turns on the feature flag and strategy authority.",
            },
            "control_policy": {
                "ui_is_trading_engine": False,
                "manual_trading_available": False,
                "force_trade_available": False,
                "live_operation_available": False,
                "broker_mutation_available": False,
                "strategy_mutation_available": False,
            },
            "endpoint": {
                "paper_endpoint_only": endpoint_authority["paper_endpoint_only"],
                "paper_endpoint_status": endpoint_authority["status"],
                "paper_endpoint_display": endpoint_authority["alpaca_endpoint_display"],
                "paper_endpoint_family": endpoint_authority["alpaca_trading_endpoint_family"],
                "paper_endpoint_host": endpoint_authority["alpaca_trading_endpoint_host"],
                "alpaca_live_endpoint_blocked": endpoint_authority["alpaca_live_endpoint_blocked"],
            },
            "broker_call_occurred": False,
            "broker_mutation_occurred": False,
            "runtime_mutation_occurred": False,
            "strategy_mutation_occurred": False,
            "live_enabled": False,
            "real_money_enabled": False,
            "secrets_values_exposed": False,
        }

    def cockpit_asset_mandate(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        raw_asset_class = str((payload or {}).get("asset_class") or "").strip().lower().replace("-", "_")
        aliases = {
            "crypto": "crypto",
            "cryptocurrency": "crypto",
            "equity": "equities",
            "equities": "equities",
            "stocks": "equities",
            "auto": "auto",
            "automatic": "auto",
        }
        asset_class = aliases.get(raw_asset_class, raw_asset_class or "unknown")
        common = {
            "source": "OPERATOR_COCKPIT_MANDATE_GATE",
            "schema_version": "operator-cockpit-mandate-result-v1",
            "requested_asset_class": asset_class,
            "active_asset_class": "crypto",
            "switch_semantics": "NEXT_CAPITAL_ONLY_EXISTING_POSITIONS_RIDE",
            "existing_positions_liquidated": False,
            "broker_call_occurred": False,
            "broker_mutation_occurred": False,
            "runtime_mutation_occurred": False,
            "strategy_mutation_occurred": False,
            "order_submission_occurred": False,
            "cancel_occurred": False,
            "liquidation_occurred": False,
            "live_enabled": False,
            "real_money_enabled": False,
            "secrets_values_exposed": False,
        }
        if asset_class == "crypto":
            return {
                **common,
                "status": "ACCEPTED",
                "accepted": True,
                "reason_code": "CRYPTO_MANDATE_ALREADY_ACTIVE",
                "detail": "Crypto is the only active cockpit mandate. No broker, runtime, or strategy mutation was needed.",
            }
        if asset_class in {"equities", "auto"}:
            return {
                **common,
                "status": "REFUSED",
                "accepted": False,
                "reason_code": f"{asset_class.upper()}_FEATURE_FLAG_OFF",
                "detail": "This asset-class mandate is visible but server-gated. Existing positions remain untouched and future capital stays on the active crypto mandate.",
            }
        return {
            **common,
            "status": "REFUSED",
            "accepted": False,
            "reason_code": "UNKNOWN_ASSET_CLASS",
            "detail": "Unknown cockpit mandate. Allowed visible values are crypto, equities, and auto; only crypto is active.",
        }

    def cockpit_day_trader_mode(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        requested = bool((payload or {}).get("enabled"))
        return {
            "source": "OPERATOR_COCKPIT_DAY_TRADER_GATE",
            "schema_version": "operator-cockpit-day-trader-result-v1",
            "requested_enabled": requested,
            "enabled": False,
            "status": "REFUSED",
            "accepted": False,
            "reason_code": "DAY_TRADER_MODE_FEATURE_FLAG_OFF",
            "detail": "Day-trader mode is not wired to strategy authority. The server rejects activation until a future Board packet explicitly enables it.",
            "broker_call_occurred": False,
            "broker_mutation_occurred": False,
            "runtime_mutation_occurred": False,
            "strategy_mutation_occurred": False,
            "order_submission_occurred": False,
            "cancel_occurred": False,
            "liquidation_occurred": False,
            "live_enabled": False,
            "real_money_enabled": False,
            "secrets_values_exposed": False,
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
            "fee_hydration_skipped": False,
            "fee_hydration_skip_reason": None,
            "fee_hydration_status": "UNKNOWN_NO_ACTIVE_RUNTIME",
            "account_activity_read_authorized": False,
            "broker_read_profile": "UNKNOWN_NO_ACTIVE_RUNTIME",
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
        diagnostics["paper_endpoint_display"] = endpoint_authority["alpaca_endpoint_display"]
        diagnostics["paper_endpoint_family"] = endpoint_authority["alpaca_trading_endpoint_family"]
        diagnostics["paper_endpoint_host"] = endpoint_authority["alpaca_trading_endpoint_host"]
        diagnostics["paper_endpoint_blocker_code"] = endpoint_authority["alpaca_endpoint_blocker_code"]
        diagnostics["alpaca_endpoint_configured"] = endpoint_authority["alpaca_endpoint_configured"]
        diagnostics["alpaca_paper_endpoint_valid"] = endpoint_authority["alpaca_paper_endpoint_valid"]
        diagnostics["alpaca_live_endpoint_blocked"] = endpoint_authority["alpaca_live_endpoint_blocked"]
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
        env = self._refresh_provider_env()
        broker_read_authorized = (
            str(env.get("PK_BOARD_AUTHORIZED_PAPER_BROKER_READ") or "").strip().upper()
            == "YES_D4_BOARD_AUTHORIZED"
        )
        snapshot = build_portfolio_snapshot(
            env,
            client=self.portfolio_client,
            broker_read_authorized=broker_read_authorized,
        )
        self._latest_portfolio_snapshot = snapshot
        self._latest_portfolio_snapshot_at_monotonic = time.perf_counter()
        return snapshot

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

    def paper_baseline(self) -> dict[str, Any]:
        accepted = self.paper_baseline_store.current()
        state = build_baseline_adoption_state(accepted_baseline=accepted if accepted.get("accepted") is True else None)
        state.update(
            {
                "store": self.paper_baseline_store.status(),
                "accept_endpoint": "/operator/paper-baseline/accept",
                "acceptance_requires_preflight_snapshot": True,
                "local_acceptance_only": True,
                "paper_start_occurred": False,
                "order_submission_occurred": False,
                "cancel_occurred": False,
                "replace_occurred": False,
                "liquidation_occurred": False,
                "close_position_occurred": False,
                "live_enabled": False,
                "real_money_enabled": False,
            }
        )
        return state

    def paper_baseline_accept(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = payload or {}
        snapshot = body.get("preflight_snapshot") if isinstance(body.get("preflight_snapshot"), dict) else body
        accepted_by = str(body.get("accepted_by_operator") or "Shan/local operator")
        policy = str(body.get("policy") or BASELINE_POLICY_PROTECTED)
        result = self.paper_baseline_store.accept(snapshot, accepted_by=accepted_by, policy=policy)
        result.update(
            {
                "local_acceptance_only": True,
                "paper_start_occurred": False,
                "order_submission_occurred": False,
                "cancel_occurred": False,
                "replace_occurred": False,
                "liquidation_occurred": False,
                "close_position_occurred": False,
                "live_enabled": False,
                "real_money_enabled": False,
            }
        )
        return result

    def launch_readiness(self) -> dict[str, Any]:
        effective_env = self._refresh_provider_env()
        supervisor = self.supervisor.status_snapshot()
        baseline = self.paper_baseline_store.current()
        return build_launch_readiness(
            provider_readiness=self.providers(),
            credentials=self.credentials_providers(),
            health=self.health(),
            storage=self.storage(),
            runtime=self.runtime(),
            supervisor=supervisor,
            ai_status=self.ai_status(),
            effective_env=effective_env,
            paper_baseline=baseline if baseline.get("accepted") is True else None,
        )

    def paper_control_state(self) -> dict[str, Any]:
        started_ns = time.perf_counter_ns()
        cached = self.snapshot_store.get("paper_control_snapshot")
        if cached and cached.get("fresh") is True:
            payload = deepcopy(cached.get("payload") or {})
            payload["snapshot_cache_status"] = "FRESH"
            payload["snapshot_cache_age_ms"] = cached.get("age_ms")
            payload["total_elapsed_ms"] = round((time.perf_counter_ns() - started_ns) / 1_000_000, 3)
            return payload

        subchecks: list[dict[str, Any]] = []

        def elapsed_ms_since(start_ns: int) -> float:
            return round((time.perf_counter_ns() - start_ns) / 1_000_000, 3)

        def record_subcheck(
            name: str,
            start_ns: int,
            status: str = "OK",
            *,
            reason_code: str | None = None,
            exception: BaseException | None = None,
        ) -> None:
            subchecks.append(
                {
                    "name": name,
                    "elapsed_ms": elapsed_ms_since(start_ns),
                    "status": status,
                    "reason_code": reason_code,
                    "exception_class": exception.__class__.__name__ if exception else None,
                }
            )

        def run_subcheck(name: str, fn, *, reason_code: str | None = None):
            subcheck_start = time.perf_counter_ns()
            try:
                result = fn()
            except Exception as exc:
                record_subcheck(name, subcheck_start, "FAILED", reason_code=reason_code or f"{name.upper()}_FAILED", exception=exc)
                return None
            record_subcheck(name, subcheck_start)
            return result

        def skip_subcheck(name: str, reason_code: str) -> None:
            skip_started = time.perf_counter_ns()
            record_subcheck(name, skip_started, "SKIPPED", reason_code=reason_code)

        effective_env = run_subcheck("provider_env_refresh", self._refresh_provider_env, reason_code="PROVIDER_ENV_REFRESH_FAILED") or self.provider_env
        supervisor = run_subcheck("supervisor_snapshot", self.supervisor.status_snapshot, reason_code="SUPERVISOR_SNAPSHOT_FAILED") or {}
        credentials = run_subcheck("credential_summary", lambda: self.credential_store.providers_summary(self.process_env), reason_code="CREDENTIAL_SUMMARY_FAILED") or {}
        endpoint_authority = run_subcheck("endpoint_authority", lambda: alpaca_endpoint_authority(self._paper_process_env(effective_env)), reason_code="ENDPOINT_AUTHORITY_FAILED") or {}
        baseline = run_subcheck("baseline_state", self.paper_baseline, reason_code="BASELINE_STATE_FAILED") or {}
        git_identity = {
            "repo_head": self.loaded_git_commit_short,
            "loaded_commit": self.loaded_git_commit_short,
            "git_branch": self.loaded_git_branch,
        }
        subcheck_start = time.perf_counter_ns()
        record_subcheck("git_identity", subcheck_start)

        # These components are intentionally not on the control-state critical
        # path. They have dedicated endpoints and can involve broker reads,
        # archive scans, provider calls, or broader health checks.
        skip_subcheck("launch_readiness", "LAUNCH_READINESS_NOT_ON_FAST_PATH")
        skip_subcheck("portfolio_snapshot", "PORTFOLIO_SNAPSHOT_NOT_ON_FAST_PATH")
        skip_subcheck("run_archive_lookup", "RUN_ARCHIVE_NOT_ON_FAST_PATH")
        skip_subcheck("watchdog_alerts", "WATCHDOG_ALERTS_NOT_ON_FAST_PATH")
        skip_subcheck("broker_read", "BROKER_READ_NOT_ON_CONTROL_STATE_FAST_PATH")

        active = supervisor.get("active_session") or {}
        latest = supervisor.get("latest_session") or {}
        session = active or latest or {}
        providers = credentials.get("providers") if isinstance(credentials.get("providers"), list) else []
        alpaca = next(
            (
                provider
                for provider in providers
                if str(provider.get("provider_id") or "") == "alpaca_paper"
            ),
            {},
        )
        fields = alpaca.get("fields") if isinstance(alpaca.get("fields"), list) else []
        missing_fields = [
            str(field.get("name"))
            for field in fields
            if field.get("configured") is not True and str(field.get("name") or "") in {"APCA_API_KEY_ID", "APCA_API_SECRET_KEY"}
        ]
        if not fields and alpaca.get("configured") is not True:
            missing_fields = ["APCA_API_KEY_ID", "APCA_API_SECRET_KEY"]

        active_session_id = active.get("session_id") or supervisor.get("active_session_id")
        supervisor_state = str(supervisor.get("state") or "UNKNOWN")
        supervisor_running = supervisor_state.upper() in {"RUNNING", "STARTING", "STOP_REQUESTED"} or bool(active_session_id)
        required_failures = [
            str(check.get("reason_code"))
            for check in subchecks
            if check.get("status") == "FAILED"
            and check.get("name") in {"provider_env_refresh", "supervisor_snapshot", "credential_summary", "endpoint_authority", "baseline_state"}
            and check.get("reason_code")
        ]
        endpoint_family = str(endpoint_authority.get("alpaca_trading_endpoint_family") or "unknown")
        endpoint_host = str(endpoint_authority.get("alpaca_trading_endpoint_host") or "")
        endpoint_display = str(endpoint_authority.get("alpaca_endpoint_display") or endpoint_host)
        endpoint_valid = endpoint_authority.get("paper_endpoint_only") is True
        baseline_accepted = baseline.get("accepted") is True
        baseline_adoption_required = str(baseline.get("decision") or baseline.get("status") or "") in {
            "PAPER_BASELINE_ADOPTION_REQUIRED",
            "PREFLIGHT_BLOCKED_BASELINE_ADOPTION_REQUIRED",
        }
        baseline_preflight_required = str(baseline.get("decision") or baseline.get("status") or "") in {
            "READ_ONLY_PREFLIGHT_REQUIRED",
            "NOT_ACCEPTED",
        }
        try:
            baseline_position_count_for_policy = int(baseline.get("position_count") or 0)
        except (TypeError, ValueError):
            baseline_position_count_for_policy = 0
        baseline_position_aware_policy_blocked = (
            baseline_accepted
            and baseline_position_count_for_policy > 0
            and str(baseline.get("policy") or "") == BASELINE_POLICY_PROTECTED
        )
        baseline_runtime_context = supervisor.get("paper_baseline_runtime_context") or {}
        credential_configured = alpaca.get("configured") is True
        supervisor_allows_start = supervisor.get("paper_start_allowed") is True
        local_start_ready = (
            supervisor_allows_start
            and credential_configured
            and endpoint_valid
            and baseline_accepted
            and not baseline_position_aware_policy_blocked
            and not supervisor_running
            and not required_failures
        )
        if supervisor_running:
            dominant_blocker = "SUPERVISOR_PROCESS_RUNNING_OR_RECENT"
        elif required_failures:
            dominant_blocker = "PAPER_CONTROL_STATE_DEGRADED"
        elif not credential_configured:
            dominant_blocker = "PAPER_CREDENTIALS_MISSING"
        elif not endpoint_valid:
            dominant_blocker = str(endpoint_authority.get("reason_code") or "PAPER_ENDPOINT_NOT_VERIFIED")
        elif baseline_adoption_required:
            dominant_blocker = "BASELINE_ADOPTION_REQUIRED"
        elif baseline_preflight_required:
            dominant_blocker = "paper_read_only_preflight_gate"
        elif baseline_position_aware_policy_blocked:
            dominant_blocker = "paper_baseline_position_aware_policy"
        elif local_start_ready:
            dominant_blocker = "READY_FOR_BOUNDED_PAPER"
        else:
            dominant_blocker = str(supervisor.get("paper_start_refusal_reason") or "PAPER_START_BLOCKED")
        reason_codes = list(dict.fromkeys([dominant_blocker, *required_failures, str(supervisor.get("paper_start_refusal_reason") or "")]))
        reason_codes = [code for code in reason_codes if code]

        cached_portfolio = self._latest_portfolio_snapshot if isinstance(self._latest_portfolio_snapshot, dict) else {}
        cached_summary = cached_portfolio.get("summary") if isinstance(cached_portfolio.get("summary"), dict) else {}
        cached_age_ms = None
        if self._latest_portfolio_snapshot_at_monotonic is not None:
            cached_age_ms = round((time.perf_counter() - self._latest_portfolio_snapshot_at_monotonic) * 1000, 3)
        portfolio_truth_status = cached_portfolio.get("status") or "PORTFOLIO_READ_AVAILABLE_SEPARATELY"
        portfolio_data_source = cached_portfolio.get("data_source") or "CONTROL_STATE_FAST_PATH_NO_BROKER_READ"
        positions_count = (
            cached_summary.get("position_count")
            if cached_summary.get("position_count") is not None
            else baseline.get("position_count") or 0
        )
        open_orders_count = (
            cached_summary.get("open_order_count")
            if cached_summary.get("open_order_count") is not None
            else baseline.get("open_order_count") or 0
        )
        artifact_paths = {
            "stdout_path": session.get("stdout_path"),
            "stderr_path": session.get("stderr_path"),
            "wrapper_stdout_path": session.get("wrapper_stdout_path"),
            "wrapper_stderr_path": session.get("wrapper_stderr_path"),
            "child_stdout_path": session.get("child_stdout_path"),
            "child_stderr_path": session.get("child_stderr_path"),
            "session_store_path": (supervisor.get("session_store") or {}).get("path"),
        }
        next_safe_action = (
            "Monitor the attached PAPER supervisor. Do not start a second run."
            if supervisor_running
            else "Start governed PAPER from the Run PAPER cockpit."
            if local_start_ready
            else "Resolve the listed blocker before starting PAPER."
        )
        total_elapsed_ms = elapsed_ms_since(started_ns)
        payload = {
            "source": "OPERATOR_PAPER_CONTROL_STATE",
            "schema_version": "paper-control-state-v1",
            "backend_status": "DEGRADED" if required_failures else "OK",
            **git_identity,
            "data_source": "OPERATOR_BACKEND",
            "total_elapsed_ms": total_elapsed_ms,
            "subchecks": subchecks,
            "response_budget_ms": 3000,
            "paper_only": True,
            "live_locked": True,
            "real_money_blocked": True,
            "credential_source": alpaca.get("source") or credentials.get("source") or "NOT_CONFIGURED",
            "credential_status": "CONFIGURED" if credential_configured else "MISSING",
            "alpaca_paper_configured": credential_configured,
            "missing_credential_fields": missing_fields,
            "endpoint_family": endpoint_family,
            "endpoint_host": endpoint_host,
            "endpoint_display": endpoint_display,
            "endpoint_source": endpoint_authority.get("alpaca_endpoint_source") or endpoint_authority.get("endpoint_source") or "UNKNOWN",
            "endpoint_status": endpoint_authority.get("status") or "UNKNOWN",
            "baseline_status": baseline.get("status") or "UNKNOWN",
            "baseline_accepted": baseline_accepted,
            "baseline_snapshot_id": baseline.get("baseline_snapshot_id"),
            "baseline_policy": baseline.get("policy"),
            "baseline_position_count": baseline.get("position_count") or 0,
            "baseline_position_aware_policy_blocked": baseline_position_aware_policy_blocked,
            "baseline_runtime_context": baseline_runtime_context,
            "protected_symbols": baseline_runtime_context.get("protected_symbols_normalized") or baseline.get("protected_symbols") or [],
            "portfolio_truth_status": portfolio_truth_status,
            "portfolio_data_source": portfolio_data_source,
            "portfolio_snapshot_age_ms": cached_age_ms,
            "account_status": cached_summary.get("account_status"),
            "cash": cached_summary.get("cash"),
            "equity": cached_summary.get("total_equity"),
            "buying_power": cached_summary.get("buying_power"),
            "positions_count": positions_count,
            "open_orders_count": open_orders_count,
            "supervisor_state": supervisor_state,
            "active_run_id": active_session_id,
            "active_pid": active.get("pid") or session.get("pid"),
            "paper_start_allowed": local_start_ready,
            "paper_stop_allowed": supervisor.get("paper_stop_allowed") is True,
            "stale_reconciliation": supervisor.get("stale_reconciliation") or {},
            "dominant_blocker": dominant_blocker,
            "reason_codes": reason_codes,
            "max_lease_seconds": supervisor.get("max_paper_duration_seconds") or 432000,
            "allowed_durations": supervisor.get("allowed_durations") or [],
            "watchlist": active.get("watchlist") or supervisor.get("allowed_watchlist") or [],
            "artifact_paths": artifact_paths,
            "last_heartbeat": session.get("last_status_check_at"),
            "next_safe_action": next_safe_action,
            "launch_readiness": {
                "source": "NOT_ON_CONTROL_STATE_FAST_PATH",
                "reason_code": "LAUNCH_READINESS_NOT_ON_FAST_PATH",
                "paper_start_allowed": None,
            },
            "latest_run": {
                "source": "SUPERVISOR_STATUS_SNAPSHOT",
                "state": supervisor.get("state"),
                "active_session_id": supervisor.get("active_session_id"),
                "paper_start_allowed": supervisor.get("paper_start_allowed"),
                "paper_stop_allowed": supervisor.get("paper_stop_allowed"),
                "latest_session": latest,
            },
            "paper_baseline": baseline,
            "portfolio_summary": {
                "source": portfolio_data_source,
                "status": portfolio_truth_status,
                "cache_age_ms": cached_age_ms,
                "account_status": cached_summary.get("account_status"),
                "cash": cached_summary.get("cash"),
                "total_equity": cached_summary.get("total_equity"),
                "buying_power": cached_summary.get("buying_power"),
                "position_count": positions_count,
                "open_order_count": open_orders_count,
            },
            "runtime_attachment_detail": "PAPER supervisor process is attached." if supervisor_running else "Ready. No PAPER run currently attached.",
            "secrets_values_exposed": False,
            "raw_secret_values_included": False,
            "broker_call_occurred": False,
            "broker_mutation_occurred": False,
            "order_submission_occurred": False,
            "cancel_occurred": False,
            "replace_occurred": False,
            "liquidation_occurred": False,
            "close_position_occurred": False,
            "live_enabled": False,
            "real_money_enabled": False,
        }
        payload["snapshot_cache_status"] = "MISS"
        self.snapshot_store.set(
            "paper_control_snapshot",
            payload,
            ttl_seconds=0.75,
            source="OPERATOR_PAPER_CONTROL_STATE",
            elapsed_ms=total_elapsed_ms,
        )
        return payload

    def paper_control_state_synchronized(self) -> dict[str, Any]:
        cached = self.snapshot_store.get("paper_control_snapshot")
        if cached and cached.get("fresh") is True:
            return self.paper_control_state()
        with self._paper_control_state_lock:
            return self.paper_control_state()

    def run_visibility_status(self) -> dict[str, Any]:
        snapshot = read_run_visibility_snapshot(
            self.runtime_config.repo_root,
            state_db_path=self.runtime_config.data_dir / "state.db",
        )
        supervisor = self.supervisor.status_snapshot()
        active_session = supervisor.get("active_session") if isinstance(supervisor.get("active_session"), dict) else None
        latest_session = supervisor.get("latest_session") if isinstance(supervisor.get("latest_session"), dict) else None
        session = active_session or latest_session or {}
        session_pid = session.get("pid")
        artifact_pid = snapshot.get("pid")
        artifact_session_match = bool(session_pid and artifact_pid and str(session_pid) == str(artifact_pid))
        supervisor_overlay = {
            "state": supervisor.get("state"),
            "active_session_id": supervisor.get("active_session_id"),
            "latest_session_id": session.get("session_id"),
            "latest_status": session.get("status"),
            "pid": session_pid,
            "artifact_session_match": artifact_session_match,
            "paper_start_allowed": supervisor.get("paper_start_allowed") is True,
            "paper_stop_allowed": supervisor.get("paper_stop_allowed") is True,
            "paper_start_refusal_reason": supervisor.get("paper_start_refusal_reason"),
            "paper_stop_refusal_reason": supervisor.get("paper_stop_refusal_reason"),
            "broker_call_occurred": False,
            "broker_mutation_occurred": False,
            "secrets_values_exposed": False,
        }
        if active_session:
            snapshot.update(
                {
                    "status": "RUNNING",
                    "prominent_state": "RUNNING",
                    "pid": session_pid or artifact_pid,
                    "data_source": "OPERATOR_SUPERVISOR_AND_LOCAL_RUNTIME_ARTIFACTS",
                    "runtime_artifact_note": (
                        "Operator supervisor has an attached PAPER session. Heartbeat, fills, positions, and open-order "
                        "counts remain local/runtime artifact evidence unless separately broker-confirmed."
                    ),
                }
            )
        elif latest_session and not artifact_session_match:
            snapshot["runtime_artifact_note"] = (
                "Latest supervisor session and local heartbeat artifact do not have the same PID; use broker portfolio "
                "and supervisor session state for final truth."
            )
        snapshot.update(
            {
                "operator_endpoint": "/operator/run-visibility/status",
                "operator_page": "/operator/run-visibility",
                "data_source": snapshot.get("data_source") or "LOCAL_RUNTIME_ARTIFACTS",
                "operator_supervisor": supervisor_overlay,
                "broker_call_occurred": False,
                "broker_mutation_occurred": False,
                "order_submission_occurred": False,
                "cancel_occurred": False,
                "liquidation_occurred": False,
                "live_enabled": False,
                "real_money_enabled": False,
                "secrets_values_exposed": False,
            }
        )
        return snapshot

    def run_visibility_page(self) -> HTMLResponse:
        return _with_no_store_headers(HTMLResponse(render_run_visibility_html(self.run_visibility_status())))

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
        return self.run_archive.list_runs(limit=10)

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
            "authority_graph": authority_graph_summary(),
            "markdown": render_system_map_markdown(),
            "report_path": SYSTEM_MAP_SUMMARY["report_path"],
            "secrets_values_exposed": False,
        }

    def ai_status(self) -> dict[str, Any]:
        recs = self.ai_queue.list()
        gateway_status = self.ai_gateway.status()
        gateway_provider = gateway_status.get("provider") if isinstance(gateway_status.get("provider"), dict) else {}
        gateway_policy = gateway_status.get("model_policy") if isinstance(gateway_status.get("model_policy"), dict) else {}
        return {
            "source": "AI_CHIEF_OPERATOR",
            "persona": quant_persona_summary(),
            "gateway": gateway_status,
            "route_truth_owner": "app.ai_chief_operator.provider_gateway.AIProviderGateway",
            "active_provider": gateway_provider.get("provider_id") or gateway_provider.get("provider") or "disabled",
            "active_model": gateway_provider.get("model_name") or gateway_provider.get("model") or gateway_policy.get("model_name"),
            "response_mode": gateway_provider.get("provider_mode") or gateway_policy.get("provider_mode") or "NOT_CONFIGURED",
            "fallback_state": gateway_provider.get("fallback_reason") or gateway_provider.get("provider_state") or "UNKNOWN",
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
        request_id = f"ai-{uuid.uuid4().hex[:12]}"
        question = str(body.get("question") or body.get("prompt") or "").strip()
        page_context = redact_secrets(body.get("page_context") if isinstance(body.get("page_context"), dict) else {})
        page_id = str(body.get("page_id") or page_context.get("page_id") or "")
        requested_answer_mode_raw = body.get("answer_mode", body.get("answerMode"))
        effective_answer_mode, answer_mode_status = normalize_ai_answer_mode(requested_answer_mode_raw)
        gateway_status = self.ai_gateway.status()
        provider = gateway_status.get("provider") or {}
        model_policy = gateway_status.get("model_policy") or {}
        provider_state = str(provider.get("provider_state") or "AI_DISABLED")
        classification = classify_quant_prompt(question, page_id=page_id)
        mode = str(classification.get("mode") or "OPERATOR_GUIDE")
        evidence_level = str(classification.get("evidence_level") or "UNKNOWN")
        health_intent = self._ai_contains_health_question(question)
        provider_self_test_question = self._ai_is_provider_self_test_question(question)
        model_identity_question = self._ai_is_model_identity_question(question)
        local_runtime_truth_question = self._ai_should_answer_from_runtime_truth(mode, question)
        pure_local_health_question = self._ai_is_simple_health_question(question)
        pure_local_runtime_truth_question = local_runtime_truth_question and not (model_identity_question or provider_self_test_question)
        ai_intent = self._ai_intent_label(
            mode,
            question,
            health_intent=health_intent,
            paper_readiness_intent=local_runtime_truth_question,
            model_identity_intent=model_identity_question,
            provider_self_test_intent=provider_self_test_question,
        )
        challenge_nonce: str | None = None
        challenge_echoed = False
        safety_filter = {"triggered": False, "blocked_terms": []}
        if not classification["allowed"]:
            context = self._ai_light_context()
            context = self._ai_context_for_mode(context, mode)
            response = (
                "Refused or redirected. The Chief Quant Advisor cannot trade, call broker, enable live, "
                "handle secrets, bypass safety gates, submit/cancel/liquidate orders, or mutate strategy. "
                "Safe path: use governed PAPER readiness, Provider Setup, Portfolio Home, or ask for a Codex packet."
            )
            status = "REFUSED"
            refusal_reason = classification["reason_code"]
            gateway_answer: dict[str, Any] = {}
        else:
            active_provider, active_model = self._active_router_api_selection()
            route_provider = str(body.get("provider_id") or "").strip()
            route_model = str(body.get("model_name") or "").strip()
            route_mode = LOCAL_GUIDE
            if effective_answer_mode == ANSWER_MODE_AI_CHAT_MODEL:
                route_mode = LIGHT_API
                route_provider = (
                    route_provider
                    or active_provider
                    or str(self.ai_routing_settings.get("light_provider") or "openai")
                )
                route_model = (
                    route_model
                    or active_model
                    or str(self.ai_routing_settings.get("light_model") or "")
                )
            elif effective_answer_mode == ANSWER_MODE_AI_REASONING_STRATEGY:
                route_mode = HIGH_REASONING_API
                route_provider = route_provider or str(self.ai_routing_settings.get("high_reasoning_provider") or active_provider or "openai")
                route_model = route_model or str(self.ai_routing_settings.get("high_reasoning_model") or active_model or "")

            context = self._ai_light_context() if (
                effective_answer_mode == ANSWER_MODE_DETERMINISTIC
                or health_intent
                or local_runtime_truth_question
                or model_identity_question
                or provider_self_test_question
            ) else self._ai_context()
            context = self._ai_context_for_mode(context, mode)
            if effective_answer_mode == ANSWER_MODE_DETERMINISTIC:
                route_reason = "DETERMINISTIC_MODE_LOCAL_TRUTH"
                if provider_self_test_question:
                    route_reason = "DETERMINISTIC_MODE_NO_PROVIDER_SELF_TEST"
                    local_response = self._ai_deterministic_provider_self_test_answer()
                elif model_identity_question and health_intent:
                    route_reason = "DETERMINISTIC_COMPOUND_LOCAL_TRUTH"
                    local_response = f"{self._ai_health_answer(context)}\n\n{self._ai_deterministic_model_route_answer(active_provider, active_model)}"
                elif model_identity_question:
                    route_reason = "DETERMINISTIC_MODEL_ROUTE_TRUTH"
                    local_response = self._ai_deterministic_model_route_answer(active_provider, active_model)
                elif pure_local_health_question:
                    route_reason = "SIMPLE_HEALTH_LOCAL_TRUTH"
                    local_response = self._ai_health_answer(context)
                elif pure_local_runtime_truth_question:
                    route_reason = "RUN_PLANNER_LOCAL_RUNTIME_TRUTH"
                    local_response = self._ai_paper_readiness_answer(question, context)
                else:
                    known, missing = self._ai_answer_facts(mode, context)
                    local_response = self._ai_current_truth_operational_answer(
                        mode,
                        question,
                        known,
                        missing,
                        self._ai_next_step(mode, context, page_id),
                        context,
                    )
                gateway_answer = {
                    "status": "ANSWERED_LOCAL_GUIDE",
                    "provider": "deterministic_local",
                    "provider_id": "deterministic_local",
                    "provider_state": "LOCAL_GUIDE",
                    "response_source": "LOCAL_DETERMINISTIC",
                    "answer_source": "LOCAL_DETERMINISTIC",
                    "response": local_response,
                    "model_call_occurred": False,
                    "model_call_attempted": False,
                    "provider_response_received": False,
                    "fallback_reason": route_reason,
                    "provider_mode": "DETERMINISTIC_FALLBACK",
                    "model_name": "deterministic-local-guide",
                    "model_quality": "FALLBACK_ONLY",
                    "reasoning_policy": "FALLBACK_ONLY_LIMITED",
                    "model_suitable_for_governance": False,
                    "cost_mode": "FREE_LOCAL",
                    "persona_enforced": True,
                    "expert_roles_applied": ["Chief Quant Advisor", "Operator Guide"],
                    "route_decision": {
                        "route_mode": LOCAL_GUIDE,
                        "reason_code": route_reason,
                        "provider_id": "deterministic_local",
                        "model_name": "deterministic-local-guide",
                        "answer_source": "LOCAL_DETERMINISTIC",
                        "allowed_provider_call": False,
                    },
                }
            elif provider_self_test_question and effective_answer_mode == ANSWER_MODE_AI_REASONING_STRATEGY:
                route_reason = "SELF_TEST_REQUIRES_AI_CHAT_MODEL_MODE"
                gateway_answer = {
                    "status": "ANSWERED_LOCAL_GUIDE",
                    "provider": "deterministic_local",
                    "provider_id": "deterministic_local",
                    "provider_state": "LOCAL_GUIDE",
                    "response_source": "LOCAL_DETERMINISTIC",
                    "answer_source": "LOCAL_DETERMINISTIC",
                    "response": self._ai_reasoning_not_self_test_answer(),
                    "model_call_occurred": False,
                    "model_call_attempted": False,
                    "provider_response_received": False,
                    "fallback_reason": route_reason,
                    "provider_mode": "DETERMINISTIC_FALLBACK",
                    "model_name": "deterministic-local-guide",
                    "model_quality": "FALLBACK_ONLY",
                    "reasoning_policy": "FALLBACK_ONLY_LIMITED",
                    "model_suitable_for_governance": False,
                    "cost_mode": "FREE_LOCAL",
                    "persona_enforced": True,
                    "expert_roles_applied": ["Chief Quant Advisor", "Operator Guide"],
                    "route_decision": {
                        "route_mode": LOCAL_GUIDE,
                        "reason_code": route_reason,
                        "provider_id": "deterministic_local",
                        "model_name": "deterministic-local-guide",
                        "answer_source": "LOCAL_DETERMINISTIC",
                        "allowed_provider_call": False,
                    },
                }
            else:
                gateway_question = question
                if provider_self_test_question and effective_answer_mode == ANSWER_MODE_AI_CHAT_MODEL:
                    challenge_nonce = self._ai_provider_self_test_nonce()
                    gateway_question = self._ai_provider_self_test_prompt(challenge_nonce)
                gateway_answer = self.ai_gateway.ask(
                    gateway_question,
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
                gateway_answer["requested_question"] = question
                gateway_answer["provider_question"] = gateway_question
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
            provider["model_call_attempted"] = gateway_answer.get("model_call_attempted")
            provider["model_call_occurred"] = gateway_answer.get("model_call_occurred")
            provider["provider_response_received"] = gateway_answer.get("provider_response_received")
            provider["fallback_reason"] = gateway_answer.get("fallback_reason")
            provider["actual_model_name"] = gateway_answer.get("actual_model_name") or provider.get("model_name")
            provider["provider_request_id"] = gateway_answer.get("provider_request_id")
            provider["endpoint_family"] = gateway_answer.get("endpoint_family")
            provider["latency_ms"] = gateway_answer.get("latency_ms")
            provider["http_status_code"] = gateway_answer.get("http_status_code")
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
        if status == "REFUSED":
            provider = {
                "provider": "deterministic_local",
                "provider_id": "deterministic_local",
                "provider_mode": "DETERMINISTIC_FALLBACK",
                "provider_state": "LOCAL_GUIDE",
                "model_name": "deterministic-local-guide",
                "model_quality": "FALLBACK_ONLY",
                "reasoning_policy": "FALLBACK_ONLY_LIMITED",
                "model_suitable_for_governance": False,
                "response_source": "LOCAL_DETERMINISTIC",
                "answer_source": "LOCAL_DETERMINISTIC",
                "cost_mode": "FREE_LOCAL",
                "persona_enforced": True,
                "expert_roles_applied": ["Chief Quant Advisor", "Operator Guide"],
                "model_call_attempted": False,
                "model_call_occurred": False,
                "provider_response_received": False,
                "fallback_reason": refusal_reason,
            }
            gateway_answer = {
                "route_decision": {
                    "route_mode": LOCAL_GUIDE,
                    "provider_id": "deterministic_local",
                    "model_name": "deterministic-local-guide",
                    "reason_code": refusal_reason or "UNSAFE_REQUEST_REFUSED_LOCALLY",
                    "answer_source": "LOCAL_DETERMINISTIC",
                    "allowed_provider_call": False,
                }
            }
        provider_mode = str(provider.get("provider_mode") or model_policy.get("provider_mode") or "DETERMINISTIC_FALLBACK")
        if status == "REFUSED":
            provider_mode = "DETERMINISTIC_FALLBACK"
        model_name = provider.get("model_name") or provider.get("model") or model_policy.get("model_name")
        model_quality = str(provider.get("model_quality") or model_policy.get("model_quality") or "FALLBACK_ONLY")
        reasoning_policy = str(provider.get("reasoning_policy") or model_policy.get("reasoning_policy") or "FALLBACK_ONLY_LIMITED")
        model_suitable = provider.get("model_suitable_for_governance")
        if model_suitable is None:
            model_suitable = model_policy.get("model_suitable_for_governance") is True
        route_decision = gateway_answer.get("route_decision") if isinstance(gateway_answer, dict) else {}
        route_decision = route_decision if isinstance(route_decision, dict) else {}
        route_reason = str(route_decision.get("reason_code") or "")
        answer_source_for_truth = str(provider.get("answer_source") or provider.get("response_source") or "")
        raw_model_response = str(gateway_answer.get("response") or gateway_answer.get("answer") or "")
        if provider.get("model_call_occurred") is True:
            safety_filter = self._ai_live_output_safety_filter(raw_model_response, question=question, mode=mode, context=context)
        if provider_self_test_question and challenge_nonce:
            challenge_echoed = challenge_nonce in raw_model_response
        if safety_filter.get("triggered"):
            response = self._ai_safety_filtered_live_answer(provider, safety_filter, question=question, context=context)
            status = "ANSWERED_MODEL_SAFETY_FILTERED"
            provider["safety_filter_triggered"] = True
            provider["blocked_terms"] = safety_filter.get("blocked_terms") or []
        elif provider_self_test_question and effective_answer_mode == ANSWER_MODE_AI_CHAT_MODEL:
            if provider.get("model_call_occurred") is True and provider.get("provider_response_received") is True and challenge_echoed:
                response = self._ai_provider_self_test_success_answer(provider, route_decision, challenge_nonce)
            elif provider.get("model_call_attempted") is True and provider.get("provider_response_received") is True:
                response = self._ai_provider_self_test_unverified_answer(provider, route_decision, challenge_nonce)
            else:
                response = self._ai_provider_self_test_failed_answer(provider, route_decision)
                provider["answer_source"] = "LOCAL_DETERMINISTIC"
                provider["response_source"] = "LOCAL_DETERMINISTIC"
                provider["provider_mode"] = "DETERMINISTIC_FALLBACK"
                provider["cost_mode"] = "FREE_LOCAL"
                provider["model_quality"] = "FALLBACK_ONLY"
                provider["reasoning_policy"] = "FALLBACK_ONLY_LIMITED"
                provider["model_suitable_for_governance"] = False
                provider_mode = "DETERMINISTIC_FALLBACK"
                answer_source_for_truth = "LOCAL_DETERMINISTIC"
        elif (
            model_identity_question
            and effective_answer_mode == ANSWER_MODE_AI_CHAT_MODEL
            and classification.get("allowed") is True
            and answer_source_for_truth not in {"API_LIGHT_MODEL", "API_HIGH_REASONING_APPROVED", "LOCAL_MODEL"}
        ):
            response = self._ai_model_identity_fallback_answer(provider, route_decision)
            status = "ANSWERED_FALLBACK"
            provider_state = "DETERMINISTIC_FALLBACK"
            provider["provider_mode"] = "DETERMINISTIC_FALLBACK"
            provider["answer_source"] = "LOCAL_DETERMINISTIC"
            provider["response_source"] = "LOCAL_DETERMINISTIC"
            provider["cost_mode"] = "FREE_LOCAL"
            provider["model_quality"] = "FALLBACK_ONLY"
            provider["reasoning_policy"] = "FALLBACK_ONLY_LIMITED"
            provider["model_suitable_for_governance"] = False
            provider["fallback_reason"] = provider.get("fallback_reason") or route_reason or provider.get("provider_error_category") or "provider unavailable"
            provider_mode = "DETERMINISTIC_FALLBACK"
            model_quality = "FALLBACK_ONLY"
            reasoning_policy = "FALLBACK_ONLY_LIMITED"
            model_suitable = False
            answer_source_for_truth = "LOCAL_DETERMINISTIC"
        known_facts, unknowns = self._ai_answer_facts(mode, context)
        next_step = self._ai_next_step(mode, context, page_id)
        reasoning_blocked = (
            effective_answer_mode == ANSWER_MODE_AI_REASONING_STRATEGY
            and provider.get("model_call_occurred") is not True
            and route_reason in {
                "HIGH_REASONING_API_APPROVAL_REQUIRED",
                "PROVIDER_CREDENTIALS_MISSING",
                "PROVIDER_ADAPTER_NOT_IMPLEMENTED",
                "NO_SILENT_DOWNGRADE_TO_LOWER_REASONING_MODEL",
            }
        )
        if classification.get("allowed") is True and reasoning_blocked:
            response = self._ai_reasoning_unavailable_answer(route_decision, known_facts, unknowns, next_step)
            status = "ANSWERED_LOCAL_GUIDE"
            provider_state = "DETERMINISTIC_FALLBACK"
            provider["answer_source"] = "LOCAL_DETERMINISTIC"
            provider["response_source"] = "LOCAL_DETERMINISTIC"
            provider["provider_mode"] = "DETERMINISTIC_FALLBACK"
            provider["cost_mode"] = "FREE_LOCAL"
            provider["model_quality"] = "FALLBACK_ONLY"
            provider["reasoning_policy"] = "FALLBACK_ONLY_LIMITED"
            provider["model_suitable_for_governance"] = False
            provider["fallback_reason"] = provider.get("fallback_reason") or route_reason
            provider_mode = "DETERMINISTIC_FALLBACK"
            model_quality = "FALLBACK_ONLY"
            reasoning_policy = "FALLBACK_ONLY_LIMITED"
            model_suitable = False
            answer_source_for_truth = "LOCAL_DETERMINISTIC"
        local_truth_fallback = (
            (mode in {"RUN_PLANNER", "TRADING_SYSTEMS_AUDITOR"} or pure_local_health_question)
            and answer_source_for_truth in {"LOCAL_DETERMINISTIC", "DETERMINISTIC_FALLBACK_NO_MODEL_CALL", "DETERMINISTIC_FALLBACK_MODEL_POLICY"}
        )
        if not reasoning_blocked and not provider_self_test_question and not model_identity_question and classification.get("allowed") is True and (local_truth_fallback or route_reason in {
            "HIGH_REASONING_API_APPROVAL_REQUIRED",
            "SERIOUS_PROMPT_REQUIRES_HIGH_REASONING_OR_PACKET",
            "NO_SILENT_DOWNGRADE_TO_LOWER_REASONING_MODEL",
        }):
            response = self._ai_current_truth_operational_answer(mode, question, known_facts, unknowns, next_step, context)
        evidence_contract = context.get("evidence_contract") if isinstance(context.get("evidence_contract"), dict) else self._ai_evidence_contract(context, mode)
        canonical_readiness = evidence_contract.get("canonical_readiness") if isinstance(evidence_contract.get("canonical_readiness"), dict) else self._ai_canonical_readiness_contract(context)
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
        ai_call_trace = self._ai_call_trace(
            request_id=request_id,
            intent=ai_intent,
            route_mode=str(route_decision.get("route_mode") or route_mode if "route_mode" in locals() else LOCAL_GUIDE),
            route_decision=route_decision,
            provider=provider,
            fallback_reason=provider.get("fallback_reason"),
            safety_filter=safety_filter,
            challenge_nonce=challenge_nonce,
            challenge_echoed=challenge_echoed,
        )
        display_source_label = self._ai_display_source_label(
            provider,
            answer_mode=effective_answer_mode,
            safety_filter=safety_filter,
        )
        ai_call_trace.update(
            {
                "requested_answer_mode": str(requested_answer_mode_raw or ""),
                "effective_answer_mode": effective_answer_mode,
                "answer_mode_status": answer_mode_status,
                "display_source_label": display_source_label,
            }
        )
        return {
            "source": "AI_QUANT_RESEARCH_CHIEF_ASK",
            "status": status,
            "request_id": request_id,
            "intent": ai_intent,
            "requested_answer_mode": str(requested_answer_mode_raw or ""),
            "effective_answer_mode": effective_answer_mode,
            "answer_mode": effective_answer_mode,
            "answer_mode_status": answer_mode_status,
            "display_source_label": display_source_label,
            "provider_state": provider_state,
            "provider": provider.get("provider") or "disabled",
            "provider_id": provider.get("provider_id") or provider.get("provider") or "disabled",
            "selected_provider": ai_call_trace["selected_provider"],
            "selected_model": ai_call_trace["selected_model"],
            "actual_provider": ai_call_trace["actual_provider_id"],
            "actual_model": ai_call_trace["actual_model_name"],
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
            "model_call_attempted": provider.get("model_call_attempted") is True,
            "provider_call_attempted": provider.get("model_call_attempted") is True,
            "model_call_occurred": provider.get("model_call_occurred") is True,
            "provider_response_received": provider.get("provider_response_received") is True,
            "fallback_used": ai_call_trace["fallback_used"],
            "fallback_reason": provider.get("fallback_reason"),
            "safety_filter_triggered": safety_filter.get("triggered") is True,
            "safety_filter_applied": safety_filter.get("triggered") is True,
            "safety_filter_reason": ", ".join(str(item) for item in (safety_filter.get("blocked_terms") or [])) or None,
            "blocked_terms": safety_filter.get("blocked_terms") or [],
            "challenge_nonce": challenge_nonce,
            "challenge_nonce_present": challenge_nonce is not None,
            "challenge_echoed": challenge_echoed,
            "actual_model_name": provider.get("actual_model_name"),
            "provider_request_id": provider.get("provider_request_id"),
            "endpoint_family": provider.get("endpoint_family") or ai_call_trace["endpoint_family"],
            "latency_ms": provider.get("latency_ms"),
            "http_status_code": provider.get("http_status_code"),
            "ai_call_trace": ai_call_trace,
            "route_decision": gateway_answer.get("route_decision") if isinstance(gateway_answer, dict) else {},
            "evidence_bound": True,
            "evidence_contract": evidence_contract,
            "canonical_readiness": canonical_readiness,
            "canonical_readiness_blockers": canonical_readiness.get("current_blockers") or [],
            "unknown_evidence_message": AI_UNKNOWN_EVIDENCE_MESSAGE,
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
            validation_status = "CREDENTIAL_PRESENCE_CONFIRMED"
            error_category = None
            safe_error = "Credential presence confirmed locally. No live AI API call was made."
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
            "credential_presence_status": "PRESENT" if configured else "MISSING",
            "local_validation_status": "KEYS_PRESENT_RAW_SECRETS_HIDDEN" if configured else "MISSING_CREDENTIALS",
            "live_api_test_status": "NOT_TESTED",
            "last_live_ai_call": None,
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
        evidence_contract = context.get("evidence_contract") if isinstance(context.get("evidence_contract"), dict) else {}
        canonical_readiness = (
            evidence_contract.get("canonical_readiness")
            if isinstance(evidence_contract.get("canonical_readiness"), dict)
            else self._ai_canonical_readiness_contract(context)
        )
        current_blockers = [str(item) for item in (canonical_readiness.get("current_blockers") or []) if str(item)]
        facts = [
            "AI is advisory-only and can_execute=false.",
            f"Live status is {context.get('live_status') or 'LIVE_LOCKED'}; real-money remains blocked.",
            f"Launch readiness: {canonical_readiness.get('final_launch_readiness') or readiness.get('final_launch_readiness') or 'UNKNOWN'}.",
            f"Provider readiness loaded: {providers.get('provider_count', 0)} providers, {providers.get('missing_credentials_count', 0)} missing credentials.",
            f"Evidence contract: {evidence_contract.get('schema_version') or AI_EVIDENCE_CONTRACT_SCHEMA}; evidence_bound=true.",
        ]
        unknowns = [
            "Future profit is unknown and cannot be inferred from PAPER or historical tests alone.",
            f"{AI_UNKNOWN_EVIDENCE_MESSAGE}: broker-confirmed fees, slippage, and TCA evidence is not present in this AI answer packet.",
        ]
        unknowns.extend(str(item) for item in (evidence_contract.get("missing_required_evidence") or []) if str(item))
        if mode == "PORTFOLIO_REVIEW":
            summary = portfolio.get("summary") if isinstance(portfolio.get("summary"), dict) else {}
            facts.append(f"Portfolio status: {portfolio.get('status') or 'UNKNOWN'}; positions={summary.get('position_count', 0)}; open_orders={summary.get('open_order_count', 0)}.")
            if portfolio.get("status") not in {"BROKER_CONFIRMED", "BROKER_CONFIRMED_EMPTY"}:
                unknowns.append(f"{AI_UNKNOWN_EVIDENCE_MESSAGE}: broker portfolio truth unavailable: {portfolio.get('unavailable_reason') or 'portfolio packet not loaded'}.")
        if mode in {"RUN_PLANNER", "TRADING_SYSTEMS_AUDITOR", "OPERATOR_GUIDE"}:
            if self._ai_ready_idle_no_active_runtime(context):
                facts.append("Current state: READY_IDLE_NO_ACTIVE_RUNTIME (ready/idle; no active PAPER run attached).")
            if runtime.get("supervisor_state"):
                facts.append(f"Supervisor: {runtime.get('supervisor_state')}.")
            facts.append(f"Paper start allowed: {str(canonical_readiness.get('paper_start_allowed') is True).lower()}.")
            max_duration = runtime.get("max_paper_duration_seconds") or runtime.get("runner_max_paper_duration_seconds")
            if max_duration:
                facts.append(f"Max duration: {max_duration} seconds / {self._duration_days_label(max_duration)}.")
            if current_blockers:
                unknowns.append(f"Canonical readiness blockers: {', '.join(current_blockers)}.")
            else:
                facts.append("Launch readiness reports no current blocker reason codes.")
            if self._ai_historical_duplicate_refusal(context):
                facts.append("Historical duplicate refusal exists as audit context, but it is not current start authority.")
            if self._ai_ready_idle_no_active_runtime(context):
                unknowns.append(f"{AI_UNKNOWN_EVIDENCE_MESSAGE}: no active DecisionFrame, NetEdge, fills, fees, or TCA evidence exists because no PAPER run is active.")
        return facts[:10], unknowns[:8]

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
                    "Short answer:",
                    *[f"- {item}" for item in known_facts[:4]],
                    *([f"- {unknowns[0]}"] if unknowns else []),
                    f"Next step: {next_step.get('label') or 'Review the current page.'}",
                ]
            )
        return "\n".join(
            [
                "Detailed backend state:",
                f"Question: {question or 'No question supplied.'}",
                f"Mode: {mode}.",
                "Known facts:",
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

    def _ai_contains_health_question(self, question: str) -> bool:
        lowered = str(question or "").strip().lower()
        if not lowered:
            return False
        health_terms = ("are you alive", "you alive", "are we alive", "is the backend alive", "status check")
        return any(term in lowered for term in health_terms)

    def _ai_is_simple_health_question(self, question: str) -> bool:
        lowered = str(question or "").strip().lower()
        if not lowered:
            return False
        return (
            self._ai_contains_health_question(lowered)
            and not self._ai_is_model_identity_question(lowered)
            and not self._ai_is_provider_self_test_question(lowered)
            and not self._ai_wants_detailed_answer(lowered)
        )

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

    def _ai_should_try_live_provider(
        self,
        mode: str,
        question: str,
        simple_health_question: bool,
        local_runtime_truth_question: bool,
    ) -> bool:
        if simple_health_question or local_runtime_truth_question:
            return False
        if self._ai_is_model_identity_question(question):
            return True
        if mode in {"OPERATOR_GUIDE", "SETUP_HELP", "QUANT_ADVISOR", "TRADING_SYSTEMS_AUDITOR", "PORTFOLIO_REVIEW"}:
            return True
        lowered = str(question or "").strip().lower()
        live_terms = (
            "plain english",
            "explain",
            "assessment",
            "quant",
            "advisor",
            "analyze",
            "summarize",
            "what should i know",
        )
        return any(term in lowered for term in live_terms)

    def _ai_is_model_identity_question(self, question: str) -> bool:
        lowered = str(question or "").strip().lower()
        if not lowered:
            return False
        return any(term in lowered for term in MODEL_IDENTITY_TERMS)

    def _ai_is_provider_self_test_question(self, question: str) -> bool:
        lowered = str(question or "").strip().lower()
        if not lowered:
            return False
        self_test_terms = (
            "make a api call",
            "make an api call",
            "make the api call",
            "call the ai api",
            "test live ai",
            "test ai provider",
            "test provider connection",
            "test provider api",
            "provider self-test",
            "api call so i know it works",
            "api call so i know it is working",
            "prove deepseek works",
            "prove openai works",
            "verify ai api",
            "verify provider api",
            "check the model api",
            "connectivity test",
        )
        return any(term in lowered for term in self_test_terms)

    def _ai_intent_label(
        self,
        mode: str,
        question: str,
        *,
        health_intent: bool,
        paper_readiness_intent: bool,
        model_identity_intent: bool,
        provider_self_test_intent: bool,
    ) -> str:
        provider_intent = provider_self_test_intent or model_identity_intent
        local_intent = health_intent or paper_readiness_intent
        if provider_intent and local_intent:
            return "COMPOUND_LOCAL_AND_PROVIDER"
        if provider_self_test_intent:
            return "AI_PROVIDER_SELF_TEST"
        if model_identity_intent:
            return "AI_PROVIDER_IDENTITY"
        if health_intent:
            return "LOCAL_HEALTH"
        if paper_readiness_intent:
            return "LOCAL_PAPER_READINESS"
        if self._ai_should_try_live_provider(mode, question, False, False):
            return "AI_PROVIDER_ADVISORY"
        return "LOCAL_HEALTH" if mode == "OPERATOR_GUIDE" else "AI_PROVIDER_ADVISORY"

    def _ai_deterministic_model_route_answer(self, active_provider: str, active_model: str) -> str:
        configured_provider = active_provider or str(self.ai_routing_settings.get("active_provider") or "deterministic_local")
        configured_model = active_model or str(self.ai_routing_settings.get("active_model") or "deterministic-local-guide")
        display_provider = self._ai_provider_display_name(configured_provider)
        return "\n".join(
            [
                "Deterministic mode is our bot/local backend; no AI provider answered this question.",
                f"- Configured AI route: {display_provider} / {configured_model or 'not selected'}",
                "- To ask the configured provider/model itself, use AI Chat Model mode.",
                "- Advisory only; broker actions blocked.",
            ]
        )

    def _ai_deterministic_provider_self_test_answer(self) -> str:
        return "\n".join(
            [
                "Deterministic mode does not call the AI provider.",
                "- Use AI Chat Model mode for an AI API proof/nonce self-test.",
                "- This did not call broker, start PAPER, enable live, enable real money, clean state, or mutate strategy/risk/OMS.",
            ]
        )

    def _ai_reasoning_not_self_test_answer(self) -> str:
        return "\n".join(
            [
                "AI Reasoning / Strategy mode is for advisory quant, risk, edge, and operator assessment.",
                "- AI API proof belongs in AI Chat Model mode.",
                "- No provider self-test, broker call, PAPER start, live enablement, cleanup, or state mutation occurred.",
            ]
        )

    def _ai_reasoning_unavailable_answer(
        self,
        route_decision: dict[str, Any],
        known_facts: list[str],
        unknowns: list[str],
        next_step: dict[str, str | None],
    ) -> str:
        reason = str(route_decision.get("reason_code") or "HIGH_REASONING_UNAVAILABLE")
        selected_provider = self._ai_provider_display_name(str(route_decision.get("provider_id") or "unknown"))
        selected_model = str(route_decision.get("model_name") or "model not selected")
        warning = str(route_decision.get("warning") or "High-reasoning provider path is unavailable or approval is required.")
        return "\n".join(
            [
                "AI Reasoning / Strategy did not run a deep provider call.",
                f"- Reason: {reason}",
                f"- Selected high-reasoning route: {selected_provider} / {selected_model}",
                f"- Truthful status: {warning}",
                *[f"- Local fact: {item}" for item in known_facts[:3]],
                *([f"- Missing evidence: {unknowns[0]}"] if unknowns else []),
                f"Next step: {next_step.get('label') or 'Review high-reasoning provider setup or approval.'}",
                "- No light-model fallback was treated as deep reasoning; no broker/PAPER/live/state mutation occurred.",
            ]
        )

    def _ai_provider_self_test_nonce(self) -> str:
        return f"PK-AI-{secrets.token_hex(3).upper()}"

    def _ai_provider_self_test_prompt(self, nonce: str) -> str:
        return (
            "This is an AI provider connectivity test for POVERTY_KILLER. "
            "Reply with the exact nonce and one short sentence saying which provider/model answered. "
            "Do not discuss broker, market data, PAPER runs, orders, trading, cleanup, live trading, or state mutation. "
            f"Nonce: {nonce}."
        )

    def _ai_live_output_safety_filter(self, text: str, *, question: str, mode: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        del mode
        lowered = str(text or "").lower()
        lowered_question = str(question or "").lower()
        blocked_terms: list[str] = []
        checks = (
            "/operator/intent/paper/start",
            "/operator/intent/paper/stop",
            "force stop",
            "clean stale",
            "clear stale",
            "cleaned up",
            "clean up",
            "cleanup",
            "delete state",
            "reset state",
            "prune",
            "cleanup stale registration",
            "clean up stale registration",
            "duplicate session",
            "duplicate active run",
            "duplicate prevention",
            "stale-lock",
            "stale lock",
            "orphaned session",
            "you need to clear",
            "must resolve two historical issues before starting",
            "would block a fresh start",
            "blocker #",
            "start a fresh paper run",
            "start a fresh bounded paper run",
            "cleared to start",
            "cleared for",
            "start a 10-minute paper smoke run right now",
            "submit test orders",
            "submit orders",
            "place orders",
            "manual buy",
            "manual sell",
            "buy/sell",
            "broker api call",
            "call broker",
            "enable live",
            "turn on live",
            "live alpaca account",
            "live account",
            "enable real money",
            "real-money enablement",
            "no portfolio exposure risk",
            "will not touch",
            "broker-confirmed truth",
            "open positions",
            "total market value",
            "buying power",
            "net unrealized",
            "previous run",
            "newer run",
            "archived run",
            "submitted 19 orders",
            "conditional_pass",
            "raw secrets",
            "change thresholds",
            "mutate strategy",
            "mutate risk",
            "mutate oms",
        )
        for term in checks:
            if term in lowered:
                blocked_terms.append(term)
        if re.search(r"\b(buy|sell)\b.+\border", lowered):
            blocked_terms.append("buy/sell order")
        if re.search(r"\bpaper_[a-f0-9]{8,}\b", lowered):
            blocked_terms.append("archived paper run id")
        if context is not None:
            truth = self._ai_runtime_truth(context)
            paper_readiness_question = (
                ("paper" in lowered_question or "smoke run" in lowered_question)
                and any(term in lowered_question for term in ("ready", "assessment", "can i", "run", "start"))
            )
            if paper_readiness_question and self._ai_paper_runnable_truth(truth):
                for term in (
                    "not ready",
                    "not cleared",
                    "do not start",
                    "should not start",
                    "cannot recommend",
                    "missing the evidence to justify",
                    "blind robot",
                ):
                    if term in lowered:
                        blocked_terms.append(term)
        unique = list(dict.fromkeys(blocked_terms))
        return {"triggered": bool(unique), "blocked_terms": unique}

    def _ai_safety_filtered_live_answer(
        self,
        provider: dict[str, Any],
        safety_filter: dict[str, Any],
        *,
        question: str,
        context: dict[str, Any],
    ) -> str:
        display_provider = self._ai_provider_display_name(str(provider.get("provider_id") or provider.get("provider") or "unknown"))
        model = str(provider.get("model_name") or provider.get("model") or "model unknown")
        truth = self._ai_runtime_truth(context)
        lower_question = str(question or "").lower()
        if "paper" in lower_question or "smoke run" in lower_question or "bot state" in lower_question or "current state" in lower_question:
            answer = [
                "Live AI answered, but its wording was replaced with grounded backend truth.",
                f"- Provider/model call: {display_provider} / {model}",
                f"- Launch readiness: {truth['launch']}",
                f"- Supervisor: {truth['supervisor']}; no active PAPER run attached.",
                f"- Paper start allowed: {str(truth['paper_start_allowed']).lower()}; max duration: {truth['max_duration']} seconds / {self._duration_days_label(truth['max_duration'])}.",
                f"- Live {truth['live']}; real money {truth['real_money']}.",
            ]
            if truth["historical_duplicate"]:
                answer.append("- Historical duplicate refusal exists as audit context only; it is not current start authority.")
            if self._ai_paper_runnable_truth(truth):
                answer.append("Next step: Shan may use the Start PAPER button for a governed PAPER run. AI cannot start it.")
            else:
                reason = str((truth["blocking_codes"] or ["UNKNOWN_BLOCKER"])[0])
                answer.append(f"Next step: resolve current blocker {reason}.")
            return "\n".join(answer)
        return "\n".join(
            [
                "Live AI API call succeeded, but the model's raw answer was blocked by safety policy.",
                f"- Provider/model: {display_provider} / {model}",
                f"- Blocked wording: {', '.join(str(item) for item in (safety_filter.get('blocked_terms') or [])) or 'unsafe operational claim'}",
                "- No broker, PAPER, live, real-money, cleanup, or state mutation occurred.",
            ]
        )

    def _ai_provider_self_test_success_answer(self, provider: dict[str, Any], route_decision: dict[str, Any], nonce: str) -> str:
        selected_provider = str(route_decision.get("provider_id") or provider.get("provider_id") or provider.get("provider") or "unknown")
        selected_model = str(route_decision.get("model_name") or provider.get("model_name") or provider.get("model") or "model unknown")
        display_provider = self._ai_provider_display_name(selected_provider)
        return "\n".join(
            [
                f"Live AI API call succeeded. {display_provider} / {selected_model} answered and echoed the challenge nonce.",
                f"- Challenge nonce: {nonce}",
                f"- Actual answer source: {provider.get('answer_source') or provider.get('response_source') or 'UNKNOWN'}",
                "- Broker actions blocked; no PAPER, live, real-money, order, cleanup, or state mutation occurred.",
            ]
        )

    def _ai_provider_self_test_unverified_answer(self, provider: dict[str, Any], route_decision: dict[str, Any], nonce: str) -> str:
        selected_provider = str(route_decision.get("provider_id") or provider.get("provider_id") or provider.get("provider") or "unknown")
        selected_model = str(route_decision.get("model_name") or provider.get("model_name") or provider.get("model") or "model unknown")
        display_provider = self._ai_provider_display_name(selected_provider)
        return "\n".join(
            [
                "Live AI API call did not verify. Provider call returned, but the challenge nonce was not confirmed.",
                f"- Selected provider/model: {display_provider} / {selected_model}",
                f"- Challenge nonce expected: {nonce}",
                "- No broker, PAPER, live, real-money, order, cleanup, or state mutation occurred.",
            ]
        )

    def _ai_provider_self_test_failed_answer(self, provider: dict[str, Any], route_decision: dict[str, Any]) -> str:
        selected_provider = str(route_decision.get("provider_id") or provider.get("provider_id") or provider.get("provider") or "unknown")
        selected_model = str(route_decision.get("model_name") or provider.get("model_name") or provider.get("model") or "model unknown")
        reason = str(provider.get("fallback_reason") or provider.get("provider_error_message_safe") or provider.get("provider_error_category") or "provider unavailable")
        display_provider = self._ai_provider_display_name(selected_provider)
        return "\n".join(
            [
                "Live AI API call did not verify. Provider call was unavailable or failed.",
                f"- Selected provider/model: {display_provider} / {selected_model}",
                f"- Failure reason: {reason}",
                "- No broker, PAPER, live, real-money, order, cleanup, or state mutation occurred.",
            ]
        )

    def _ai_display_source_label(self, provider: dict[str, Any], *, answer_mode: str, safety_filter: dict[str, Any]) -> str:
        if safety_filter.get("triggered") is True:
            return "Backend safety replacement; provider proof retained"
        if answer_mode == ANSWER_MODE_DETERMINISTIC:
            return "Deterministic local backend"
        if provider.get("model_call_occurred") is True:
            display_provider = self._ai_provider_display_name(str(provider.get("provider_id") or provider.get("provider") or "unknown"))
            model = str(provider.get("actual_model_name") or provider.get("model_name") or provider.get("model") or "model unknown")
            return f"{display_provider} model answer / {model}"
        if provider.get("model_call_attempted") is True:
            return "Provider unavailable; safe local fallback"
        return "Safe local fallback; no provider call"

    def _ai_call_trace(
        self,
        *,
        request_id: str,
        intent: str,
        route_mode: str,
        route_decision: dict[str, Any],
        provider: dict[str, Any],
        fallback_reason: Any,
        safety_filter: dict[str, Any],
        challenge_nonce: str | None,
        challenge_echoed: bool,
    ) -> dict[str, Any]:
        selected_provider = str(route_decision.get("provider_id") or provider.get("provider_id") or provider.get("provider") or "deterministic_local")
        selected_model = str(route_decision.get("model_name") or provider.get("model_name") or provider.get("model") or "deterministic-local-guide")
        answer_source = str(provider.get("answer_source") or provider.get("response_source") or "LOCAL_DETERMINISTIC")
        attempted = provider.get("model_call_attempted") is True
        occurred = provider.get("model_call_occurred") is True
        response_received = provider.get("provider_response_received") is True
        endpoint_family = str(provider.get("endpoint_family") or "")
        if not endpoint_family:
            endpoint_family = {
                "openai": "openai_responses",
                "deepseek": "deepseek_chat_completions",
                "local_openai_compatible": "openai_chat_completions",
                "xai_grok": "openai_chat_completions",
                "kimi_moonshot": "openai_chat_completions",
                "anthropic": "anthropic_messages",
            }.get(selected_provider, "local_deterministic" if not attempted else "unknown")
        return {
            "request_id": request_id,
            "intent": intent,
            "selected_provider": selected_provider,
            "selected_model": selected_model,
            "actual_provider_id": str(provider.get("provider_id") or provider.get("provider") or selected_provider),
            "actual_model_name": str(provider.get("actual_model_name") or provider.get("model_name") or provider.get("model") or selected_model),
            "route_mode": str(route_decision.get("route_mode") or route_mode or LOCAL_GUIDE),
            "provider_call_attempted": attempted,
            "provider_response_received": response_received,
            "model_call_occurred": occurred,
            "actual_answer_source": answer_source,
            "fallback_used": answer_source == "LOCAL_DETERMINISTIC" or (attempted and not occurred),
            "fallback_reason": str(fallback_reason or "") or None,
            "safety_filter_triggered": safety_filter.get("triggered") is True,
            "blocked_terms": safety_filter.get("blocked_terms") or [],
            "challenge_nonce_present": challenge_nonce is not None,
            "challenge_nonce": challenge_nonce,
            "challenge_echoed": challenge_echoed,
            "http_status_code": provider.get("http_status_code"),
            "provider_request_id": provider.get("provider_request_id"),
            "latency_ms": provider.get("latency_ms"),
            "endpoint_family": endpoint_family,
            "secrets_values_exposed": False,
        }

    def _ai_ready_idle_no_active_runtime(self, context: dict[str, Any]) -> bool:
        canonical_readiness = self._ai_canonical_readiness_contract(context)
        runtime = context.get("runtime") or {}
        return (
            canonical_readiness.get("paper_start_allowed") is True
            and canonical_readiness.get("final_launch_readiness") == "READY_FOR_BOUNDED_PAPER"
            and str(runtime.get("supervisor_state") or "").upper() == "IDLE"
            and bool(runtime.get("current_runtime_attached")) is False
        )

    def _ai_paper_runnable_readiness(self, readiness: Mapping[str, Any], runtime: Mapping[str, Any] | None = None) -> bool:
        launch = str(readiness.get("final_launch_readiness") or "")
        paper_start_allowed = readiness.get("paper_start_allowed") is True
        return paper_start_allowed and launch == "READY_FOR_BOUNDED_PAPER"

    def _ai_paper_runnable_truth(self, truth: Mapping[str, Any]) -> bool:
        return truth.get("paper_start_allowed") is True and str(truth.get("launch") or "") == "READY_FOR_BOUNDED_PAPER"

    def _ai_historical_duplicate_refusal(self, context: dict[str, Any]) -> bool:
        runtime = context.get("runtime") or {}
        return runtime.get("historical_refusal_reason") == "DUPLICATE_ACTIVE_RUN"

    def _ai_runtime_truth(self, context: dict[str, Any]) -> dict[str, Any]:
        canonical_readiness = self._ai_canonical_readiness_contract(context)
        readiness = context.get("launch_readiness") or {}
        runtime = context.get("runtime") or {}
        max_duration = runtime.get("max_paper_duration_seconds") or runtime.get("runner_max_paper_duration_seconds") or 432000
        try:
            max_duration_int = int(max_duration)
        except (TypeError, ValueError):
            max_duration_int = 432000
        blocking_codes = [str(item) for item in (canonical_readiness.get("current_blockers") or []) if str(item)]
        return {
            "launch": canonical_readiness.get("final_launch_readiness") or readiness.get("final_launch_readiness") or "UNKNOWN",
            "supervisor": runtime.get("supervisor_state") or "UNKNOWN",
            "paper_start_allowed": canonical_readiness.get("paper_start_allowed") is True,
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
            return "Configure the Alpaca PAPER trading endpoint as https://paper-api.alpaca.markets; live and market-data endpoints stay blocked for PAPER launch readiness."
        if reason_code == "paper_start_authority":
            return "Open the Run PAPER page and review the current supervisor refusal reason."
        if reason_code == "audit_session_storage":
            return "Fix audit/session storage readiness before any PAPER start."
        return f"Review launch readiness reason code {reason_code} in the operator UI."

    def _duration_days_label(self, seconds: Any) -> str:
        try:
            value = int(seconds)
        except (TypeError, ValueError):
            return "unknown duration"
        if value < 86400:
            return "less than 1 day"
        days = value / 86400
        if days.is_integer():
            days_text = str(int(days))
        else:
            days_text = f"{days:.2f}".rstrip("0").rstrip(".")
        return f"{days_text} day{'s' if days != 1 else ''}"

    def _ai_paper_readiness_answer(self, question: str, context: dict[str, Any]) -> str:
        truth = self._ai_runtime_truth(context)
        if self._ai_paper_runnable_truth(truth):
            return "\n".join(
                [
                    "Yes - governed PAPER is ready and start is allowed.",
                    f"- Launch readiness: {truth['launch']}",
                    f"- Supervisor: {truth['supervisor']}; no active PAPER run attached.",
                    f"- Paper start allowed: {str(truth['paper_start_allowed']).lower()}",
                    f"- Max duration: {truth['max_duration']} seconds / {self._duration_days_label(truth['max_duration'])}",
                    f"- Live {truth['live']}; real money {truth['real_money']}.",
                    "Next step: Shan must click Start PAPER on the Run PAPER page. Use a short proof first; long PAPER leases are available only through the same governed controls.",
                ]
            )
        reason = str((truth["blocking_codes"] or ["UNKNOWN_BLOCKER"])[0])
        return "\n".join(
            [
                f"No - current blocker is {reason}.",
                f"Launch readiness: {truth['launch']}.",
                f"Paper start allowed: {str(truth['paper_start_allowed']).lower()}.",
                f"Next action: {self._ai_next_action_for_blocker(reason)}",
            ]
        )

    def _ai_health_answer(self, context: dict[str, Any]) -> str:
        truth = self._ai_runtime_truth(context)
        ready_phrase = "backend connected and our bot is idle-ready" if truth["ready_idle"] else "backend connected, but PAPER readiness is not fully ready"
        return "\n".join(
            [
                f"Yes - {ready_phrase}.",
                f"- Runtime: {truth['supervisor']} / no active PAPER run",
                f"- Launch readiness: {truth['launch']}",
                f"- Live {truth['live']}; real money {truth['real_money']}",
                "- AI is advisory-only.",
            ]
        )

    def _ai_model_identity_fallback_answer(self, provider: dict[str, Any], route_decision: dict[str, Any]) -> str:
        selected_provider = str(route_decision.get("provider_id") or provider.get("provider_id") or provider.get("provider") or "unknown")
        selected_model = str(route_decision.get("model_name") or provider.get("model_name") or provider.get("model") or "not selected")
        reason = str(route_decision.get("reason_code") or provider.get("provider_error_category") or "provider unavailable")
        provider_error = str(provider.get("provider_error_message_safe") or "").strip()
        display_provider = self._ai_provider_display_name(selected_provider)
        lines = [
            f"{display_provider} is selected, but no provider model answered this question.",
            f"- Selected provider/model: {display_provider} / {selected_model}",
            "- Actual answer source: LOCAL_DETERMINISTIC",
            f"- Provider call did not answer: {reason}",
            "- Broker actions blocked; no secrets exposed.",
        ]
        if provider_error:
            lines.insert(4, f"- Safe provider error: {provider_error}")
        return "\n".join(lines)

    def _ai_provider_display_name(self, provider_id: str) -> str:
        labels = {
            "openai": "OpenAI",
            "anthropic": "Claude",
            "deepseek": "DeepSeek",
            "gemini": "Gemini",
            "xai_grok": "Grok",
            "kimi_moonshot": "Kimi",
            "local_openai_compatible": "Local OpenAI-compatible",
            "deterministic_local": "Safe local fallback",
            "supreme_board_packet": "Supreme Board packet",
        }
        return labels.get(str(provider_id or "").strip().lower(), str(provider_id or "Unknown provider"))

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
                "The configured model returned no usable text, so this is a safe local fallback.",
                *[f"- {item}" for item in known_facts[:4]],
                *[f"- Missing: {item}" for item in unknowns[:2]],
                f"Next step: {next_step.get('label') or 'Review the current page.'}",
            ]
        )

    def _ai_next_step(self, mode: str, context: dict[str, Any], page_id: str) -> dict[str, str | None]:
        readiness = context.get("launch_readiness") or {}
        canonical_readiness = self._ai_canonical_readiness_contract(context)
        provider_setup = context.get("provider_setup") if isinstance(context.get("provider_setup"), dict) else {}
        current_blockers = [str(item) for item in (canonical_readiness.get("current_blockers") or []) if str(item)]
        alpaca_missing = "alpaca_paper_credentials" in set(current_blockers) or "alpaca_paper_credentials" in set(readiness.get("reason_codes") or [])
        if mode == "SETUP_HELP" or alpaca_missing:
            return {"label": "Open Keys & Providers and save/validate Alpaca PAPER credentials.", "page": "providers", "control_id": "credential_save_alpaca_paper"}
        if mode == "PORTFOLIO_REVIEW":
            return {"label": "Review Portfolio Home positions, exposure, open orders, and unavailable broker truth.", "page": "positions", "control_id": "positions_preview_table"}
        if mode == "RUN_PLANNER":
            if canonical_readiness.get("paper_start_allowed") is True and canonical_readiness.get("final_launch_readiness") == "READY_FOR_BOUNDED_PAPER":
                return {"label": "Start through the governed Run PAPER control. I cannot start it; Shan must click Start PAPER.", "page": "command", "control_id": "paper_start"}
            reason = str((current_blockers or ["UNKNOWN_BLOCKER"])[0])
            return {"label": f"Do not start PAPER until {reason} is resolved.", "page": "command", "control_id": "paper_start"}
        if mode == "CODEX_PACKET_ADVISOR":
            return {"label": "Draft a scoped Codex packet with exact blocker, file area, tests, and safety limits.", "page": "ai", "control_id": "ai_ask"}
        if mode == "TRADING_SYSTEMS_AUDITOR":
            return {"label": "Audit readiness, provider status, portfolio truth, P&L/TCA, and blocked controls before any run.", "page": page_id or "diagnostics", "control_id": "ai_ask"}
        if provider_setup.get("configured_count") == 0:
            return {"label": "Configure required providers before relying on model or broker answers.", "page": "providers", "control_id": "credential_save_alpaca_paper"}
        return {"label": "Review the current page summary and ask a narrower follow-up if evidence is missing.", "page": page_id or "positions", "control_id": "ai_ask"}

    def _ai_canonical_readiness_contract(self, context: Mapping[str, Any]) -> dict[str, Any]:
        launch = context.get("launch_readiness") if isinstance(context.get("launch_readiness"), Mapping) else {}
        control = context.get("paper_control_state") if isinstance(context.get("paper_control_state"), Mapping) else {}
        final = str(launch.get("final_launch_readiness") or "UNKNOWN")
        control_blocker = str(control.get("dominant_blocker") or "")
        launch_reason_codes = [str(item) for item in (launch.get("reason_codes") or []) if str(item)]
        control_reason_codes = [str(item) for item in (control.get("reason_codes") or []) if str(item)]
        if final == "READY_FOR_BOUNDED_PAPER":
            current_blockers: list[str] = []
        elif launch_reason_codes:
            current_blockers = launch_reason_codes
        elif control_blocker and control_blocker != "READY_FOR_BOUNDED_PAPER":
            current_blockers = [control_blocker]
        else:
            current_blockers = [code for code in control_reason_codes if code != "READY_FOR_BOUNDED_PAPER"]
        current_blockers = list(dict.fromkeys(current_blockers))
        paper_start_allowed = launch.get("paper_start_allowed") is True and final == "READY_FOR_BOUNDED_PAPER"
        return {
            "source": "OPERATOR_LAUNCH_READINESS_D6_CONTRACT",
            "control_state_source": control.get("source") or "OPERATOR_PAPER_CONTROL_STATE",
            "final_launch_readiness": final,
            "paper_start_allowed": paper_start_allowed,
            "current_blockers": current_blockers,
            "launch_reason_codes": launch_reason_codes,
            "paper_control_dominant_blocker": control_blocker or None,
            "paper_control_reason_codes": control_reason_codes,
            "ready_state": final == "READY_FOR_BOUNDED_PAPER" and paper_start_allowed,
            "unknown_reason": None if final != "UNKNOWN" else f"{AI_UNKNOWN_EVIDENCE_MESSAGE}: launch_readiness.",
        }

    def _ai_evidence_contract(self, context: Mapping[str, Any], mode: str) -> dict[str, Any]:
        canonical_readiness = self._ai_canonical_readiness_contract(context)

        def packet(name: str, key: str, *, required: bool = True, present: bool | None = None, reason: str | None = None) -> dict[str, Any]:
            value = context.get(key)
            if present is None:
                present = isinstance(value, Mapping) and bool(value)
            return {
                "name": name,
                "context_key": key,
                "required": required,
                "present": bool(present),
                "reason": None if present else (reason or f"{AI_UNKNOWN_EVIDENCE_MESSAGE}: {name}."),
            }

        portfolio = context.get("portfolio") if isinstance(context.get("portfolio"), Mapping) else {}
        portfolio_status = str(portfolio.get("status") or "")
        portfolio_present = portfolio_status in {"BROKER_CONFIRMED", "BROKER_CONFIRMED_EMPTY", "BACKEND_DEGRADED", "MISSING_CREDENTIALS", "AUTH_FAILED", "BROKER_READ_FAILED"}
        evidence_graph = context.get("evidence_graph") if isinstance(context.get("evidence_graph"), Mapping) else {}
        decision_explainer = context.get("decision_explainer") if isinstance(context.get("decision_explainer"), Mapping) else {}
        action_center = context.get("action_center") if isinstance(context.get("action_center"), Mapping) else {}
        packets = [
            packet("readiness_state", "launch_readiness", reason=f"{AI_UNKNOWN_EVIDENCE_MESSAGE}: launch readiness packet."),
            packet("paper_control_state", "paper_control_state", required=False, reason=f"{AI_UNKNOWN_EVIDENCE_MESSAGE}: paper control-state packet."),
            packet("provider_readiness", "provider_readiness", reason=f"{AI_UNKNOWN_EVIDENCE_MESSAGE}: provider readiness packet."),
            packet("runtime_state", "runtime", reason=f"{AI_UNKNOWN_EVIDENCE_MESSAGE}: runtime state packet."),
            packet(
                "portfolio_truth",
                "portfolio",
                required=mode == "PORTFOLIO_REVIEW",
                present=portfolio_present,
                reason=f"{AI_UNKNOWN_EVIDENCE_MESSAGE}: broker-confirmed portfolio packet was not loaded for this AI answer.",
            ),
            packet(
                "decision_records",
                "decision_explainer",
                required=mode in {"TRADING_SYSTEMS_AUDITOR", "QUANT_ADVISOR", "RUN_PLANNER"},
                present=bool(decision_explainer) and decision_explainer.get("status") != "NO_DECISIONFRAME_EVIDENCE",
                reason=f"{AI_UNKNOWN_EVIDENCE_MESSAGE}: DecisionFrame/decision record evidence is missing.",
            ),
            packet(
                "market_truth",
                "evidence_graph",
                required=mode in {"TRADING_SYSTEMS_AUDITOR", "QUANT_ADVISOR"},
                present=bool(evidence_graph),
                reason=f"{AI_UNKNOWN_EVIDENCE_MESSAGE}: market truth evidence graph is missing.",
            ),
            packet(
                "risk_results",
                "action_center",
                required=mode in {"TRADING_SYSTEMS_AUDITOR", "RUN_PLANNER"},
                present=bool(action_center),
                reason=f"{AI_UNKNOWN_EVIDENCE_MESSAGE}: risk/action-center evidence packet is missing.",
            ),
            {
                "name": "module_contributions",
                "context_key": "system_map",
                "required": False,
                "present": False,
                "reason": f"{AI_UNKNOWN_EVIDENCE_MESSAGE}: module contribution map is not included in the compact AI ask packet.",
            },
        ]
        missing = [str(item["reason"]) for item in packets if item.get("required") and item.get("present") is not True]
        return {
            "schema_version": AI_EVIDENCE_CONTRACT_SCHEMA,
            "evidence_bound": True,
            "answer_policy": (
                "AI Chief may answer only from the listed structured evidence packets. "
                f"Missing evidence must be stated as: {AI_UNKNOWN_EVIDENCE_MESSAGE}."
            ),
            "mode": mode,
            "canonical_readiness": canonical_readiness,
            "packets": packets,
            "missing_required_evidence": list(dict.fromkeys(missing)),
            "broker_call_occurred": False,
            "trading_mutation_occurred": False,
            "secrets_values_exposed": False,
        }

    def _ai_light_context(self) -> dict[str, Any]:
        launch = self.launch_readiness()
        paper_control = self.paper_control_state_synchronized()
        providers = self.providers_readiness()
        context = {
            "context_version": "ai-chief-light-context-v1",
            "scope": "operator_status_and_local_guide",
            "readiness": self.readiness(),
            "launch_readiness": launch,
            "paper_control_state": paper_control,
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
        context["evidence_contract"] = self._ai_evidence_contract(context, "OPERATOR_GUIDE")
        return redact_secrets(context)

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
        context["paper_control_state"] = self.paper_control_state_synchronized()
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
        context["evidence_contract"] = self._ai_evidence_contract(context, "OPERATOR_GUIDE")
        return redact_secrets(context)

    def _ai_context_for_mode(self, context: dict[str, Any], mode: str) -> dict[str, Any]:
        updated = dict(context)
        updated["evidence_contract"] = self._ai_evidence_contract(updated, mode)
        return redact_secrets(updated)

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

    def paper_reconcile_stale_intent(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        result = self.supervisor.reconcile_stale_session(payload or {})
        self.snapshot_store.set(
            "paper_control_snapshot",
            {},
            ttl_seconds=-1,
            source="PAPER_STALE_RECONCILIATION_INVALIDATED_CONTROL_STATE",
        )
        return result

    def stack_shutdown_intent(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = payload or {}
        required_confirmations = {
            "confirm_shutdown_stack": "MISSING_STACK_SHUTDOWN_CONFIRMATION",
            "confirm_api_process_exit": "MISSING_API_PROCESS_EXIT_CONFIRMATION",
            "confirm_preserve_broker_positions": "MISSING_PRESERVE_BROKER_POSITIONS_CONFIRMATION",
            "confirm_no_broker_cleanup_requested": "MISSING_NO_BROKER_CLEANUP_CONFIRMATION",
        }
        for field, reason in required_confirmations.items():
            if body.get(field) is not True:
                response = self.refused_intent("stack_shutdown", reason)
                response["missing_confirmation"] = field
                response["api_exit_scheduled"] = False
                response["process_only_shutdown"] = True
                return response
        shutdown = self.shutdown_runtime("STACK_SHUTDOWN_INTENT")
        api_exit_scheduled = shutdown.get("allowed") is True
        if api_exit_scheduled and body.get("dry_run") is not True:
            self._stack_exit_callback()
        shutdown.update(
            {
                "intent": "stack_shutdown",
                "stack_shutdown_requested": True,
                "api_exit_scheduled": api_exit_scheduled and body.get("dry_run") is not True,
                "process_only_shutdown": True,
                "broker_call_occurred": False,
                "broker_mutation_occurred": False,
                "order_submission_occurred": False,
                "cancel_occurred": False,
                "replace_occurred": False,
                "liquidation_occurred": False,
                "close_position_occurred": False,
                "live_endpoint_touched": False,
                "real_money_touched": False,
                "secrets_values_exposed": False,
            }
        )
        return shutdown

    def live_refusal_intent(self, intent_name: str) -> dict[str, Any]:
        return self.supervisor.live_refusal(intent_name)


def get_operator_router(provider: OperatorSnapshotProvider | None = None) -> APIRouter:
    provider = provider or OperatorSnapshotProvider()
    router = APIRouter(prefix="/operator", tags=["operator-readonly"])

    async def run_local(fn):
        return await anyio.to_thread.run_sync(fn)

    @router.get("/status")
    async def status() -> dict[str, Any]:
        return await run_local(provider.status)

    @router.get("/health")
    async def health() -> dict[str, Any]:
        return provider.health()

    @router.get("/launcher-status")
    async def launcher_status() -> dict[str, Any]:
        return provider.launcher_status()

    @router.get("/version")
    async def version() -> dict[str, Any]:
        return provider.version()

    @router.get("/runtime-minimal")
    async def runtime_minimal() -> dict[str, Any]:
        return provider.runtime_minimal()

    @router.get("/perf/recent")
    async def perf_recent() -> dict[str, Any]:
        return provider.perf_recent()

    @router.get("/snapshot-store")
    async def snapshot_store() -> dict[str, Any]:
        return provider.snapshot_store_summary()

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

    @router.get("/cockpit/capabilities")
    def cockpit_capabilities() -> dict[str, Any]:
        return provider.cockpit_capabilities()

    @router.post("/cockpit/asset-mandate")
    def cockpit_asset_mandate(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return provider.cockpit_asset_mandate(payload)

    @router.post("/cockpit/day-trader-mode")
    def cockpit_day_trader_mode(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return provider.cockpit_day_trader_mode(payload)

    @router.get("/paper-control-state")
    async def paper_control_state() -> dict[str, Any]:
        cached = provider.snapshot_store.get("paper_control_snapshot")
        if cached and cached.get("fresh") is True:
            return provider.paper_control_state()
        return await run_local(provider.paper_control_state_synchronized)

    @router.get("/run-visibility/status")
    def run_visibility_status() -> dict[str, Any]:
        return provider.run_visibility_status()

    @router.get("/run-visibility", include_in_schema=False)
    def run_visibility_page() -> HTMLResponse:
        return provider.run_visibility_page()

    @router.get("/events")
    async def events():
        async def stream():
            while True:
                payloads = [
                    ("backend_status", await run_local(provider.health)),
                    ("launcher_status", await run_local(provider.launcher_status)),
                    ("runtime_minimal", await run_local(provider.runtime_minimal)),
                ]
                for event_name, payload in payloads:
                    safe_payload = dict(payload)
                    safe_payload["secrets_values_exposed"] = False
                    yield f"event: {event_name}\ndata: {json.dumps(safe_payload, default=str)}\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-store, max-age=0, must-revalidate",
                "Pragma": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )


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

    @router.get("/paper-baseline")
    def paper_baseline() -> dict[str, Any]:
        return provider.paper_baseline()

    @router.post("/paper-baseline/accept")
    def paper_baseline_accept(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return provider.paper_baseline_accept(payload)

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

    @router.post("/intent/paper/reconcile-stale")
    def paper_reconcile_stale_intent(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return provider.paper_reconcile_stale_intent(payload)

    @router.post("/intent/stack/shutdown")
    def stack_shutdown_intent(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return provider.stack_shutdown_intent(payload)

    @router.post("/intent/snapshot/export")
    def snapshot_export_intent() -> dict[str, Any]:
        return provider.refused_intent("snapshot_export", "SNAPSHOT_EXPORT_NOT_EXPOSED_IN_OPERATOR_UI")

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
        return provider.refused_intent("emergency_stop", "EMERGENCY_STOP_NOT_EXPOSED_IN_OPERATOR_UI")

    return router


def create_operator_app(provider: OperatorSnapshotProvider | None = None) -> FastAPI:
    provider = provider or OperatorSnapshotProvider()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        provider.install_process_shutdown_hooks()
        limiter = anyio.to_thread.current_default_thread_limiter()
        if limiter.total_tokens < 120:
            limiter.total_tokens = 120
        try:
            yield
        finally:
            await anyio.to_thread.run_sync(lambda: provider.shutdown_runtime("FASTAPI_LIFESPAN_SHUTDOWN"))

    app = FastAPI(title="Poverty Killer Operator Read-Only API", version=API_VERSION, lifespan=lifespan)

    @app.middleware("http")
    async def operator_timing_middleware(request, call_next):
        started_ns = time.perf_counter_ns()
        in_flight = provider.perf_recorder.begin()
        status_code = 500
        error_marker = None
        try:
            response = await call_next(request)
            status_code = int(getattr(response, "status_code", 200))
            return response
        except Exception as exc:
            error_marker = exc.__class__.__name__
            raise
        finally:
            elapsed_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
            provider.perf_recorder.finish(
                path=str(request.url.path),
                method=str(request.method),
                status_code=status_code,
                elapsed_ms=elapsed_ms,
                in_flight_count=in_flight,
                error_marker=error_marker,
            )

    app.include_router(get_operator_router(provider))
    ui_dir = Path(__file__).resolve().parents[2] / "ui" / "operator-control-panel"
    if ui_dir.exists():
        @app.get("/operator-ui", include_in_schema=False)
        def operator_ui_index_no_slash() -> HTMLResponse:
            html = _render_operator_ui_index(ui_dir, provider.loaded_git_commit_short)
            return _with_no_store_headers(HTMLResponse(html))

        @app.get("/operator-ui/", include_in_schema=False)
        def operator_ui_index() -> HTMLResponse:
            html = _render_operator_ui_index(ui_dir, provider.loaded_git_commit_short)
            return _with_no_store_headers(HTMLResponse(html))

        @app.get("/operator-ui/index.html", include_in_schema=False)
        def operator_ui_index_html() -> HTMLResponse:
            html = _render_operator_ui_index(ui_dir, provider.loaded_git_commit_short)
            return _with_no_store_headers(HTMLResponse(html))

        app.mount("/operator-ui", NoStoreStaticFiles(directory=str(ui_dir), html=True), name="operator-ui")
    return app


__all__ = [
    "API_VERSION",
    "OPERATOR_ACTIVATION_VERSION",
    "OperatorSnapshotProvider",
    "READ_ONLY_CONTRACTS",
    "create_operator_app",
    "get_operator_router",
]
