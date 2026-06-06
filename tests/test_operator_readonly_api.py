from __future__ import annotations

import time

from app.api.operator_readonly_api import API_VERSION, OPERATOR_ACTIVATION_VERSION, OperatorSnapshotProvider, create_operator_app
from app.api.operator_paper_supervisor import OperatorPaperSupervisor, PaperSupervisorConfig
from app.api.operator_runtime_config import OperatorRuntimeConfig
from app.api.operator_session_store import OperatorSessionStore
from app.operator_credentials.store import LocalCredentialStore
from tests.test_operator_paper_supervisor import FakeRunner


PAPER_ENV = {
    "APCA_API_KEY_ID": "test-paper-key",
    "APCA_API_SECRET_KEY": "test-paper-secret",
    "APCA_API_BASE_URL": "https://paper-api.alpaca.markets",
}


def _endpoint(app, path: str, method: str = "GET"):
    for route in app.routes:
        if route.path == path and method in (route.methods or set()):
            return route.endpoint
    raise AssertionError(f"route not found: {method} {path}")


def _app(tmp_path):
    runtime_config = OperatorRuntimeConfig.from_env({}, repo_root=tmp_path)
    return create_operator_app(provider=OperatorSnapshotProvider(runtime_config=runtime_config))


def test_operator_readonly_status_contract_is_safe_default(tmp_path):
    app = _app(tmp_path)

    payload = _endpoint(app, "/operator/status")()

    assert payload["api_version"] == API_VERSION
    assert payload["data_source"] == "OPERATOR_BACKEND"
    assert payload["bot_status"] == "NO_ACTIVE_RUNTIME_ATTACHED"
    assert payload["live_blocked"] is True
    assert payload["real_money_blocked"] is True
    assert payload["manual_trading_available"] is False
    assert payload["force_trade_available"] is False
    assert payload["broker_post_count"] == 0
    assert payload["broker_delete_count"] == 0
    assert payload["git_commit_short"]
    assert payload["git_branch"]
    assert payload["process_start_time"]
    assert isinstance(payload["backend_pid"], int)
    assert payload["app_version"] == OPERATOR_ACTIVATION_VERSION
    assert payload["source_commit"] == payload["git_commit_short"]
    assert payload["secrets_values_exposed"] is False
    assert "sk-" not in str(payload)
    assert "APCA_API_SECRET_KEY" not in str(payload)


def test_operator_live_readiness_is_locked_and_refused(tmp_path):
    app = _app(tmp_path)

    payload = _endpoint(app, "/operator/readiness/live")()

    assert payload["live_status"] == "LIVE_LOCKED"
    assert payload["refusal_reason"] == "LIVE_NOT_APPROVED"
    assert payload["real_money_authority"] == "BLOCKED"
    assert "separate_live_governance_packet" in payload["missing_prerequisites"]


def test_operator_contracts_distinguish_truth_authorities(tmp_path):
    app = _app(tmp_path)

    payload = _endpoint(app, "/operator/contracts")()

    assert payload["read_only"] is True
    assert payload["control_policy"]["ui_is_trading_engine"] is False
    assert payload["control_policy"]["manual_trading_available"] is False
    assert payload["control_policy"]["live_operation_available"] is False
    assert payload["truth_labels"]["broker_confirmed"].startswith("Canonical")
    assert payload["truth_labels"]["unknown"].startswith("Truth unavailable")


def test_operator_app_does_not_include_legacy_mutating_dashboard_routes(tmp_path):
    app = _app(tmp_path)
    routes = {(route.path, ",".join(sorted(getattr(route, "methods", set()) or []))) for route in app.routes}
    paths = {path for path, _methods in routes}

    assert "/api/mode/{mode}" not in paths
    assert "/api/flatten" not in paths
    assert "/operator/status" in paths
    assert "/operator/readiness/live" in paths
    assert "/operator/providers" in paths
    assert "/operator/credentials/providers" in paths
    assert "/operator/portfolio" in paths
    assert "/operator/positions" in paths
    assert "/operator/orders/open" in paths
    assert "/operator/positions/intelligence" in paths
    assert "/operator/launch-readiness" in paths
    assert "/operator/research" in paths
    assert "/operator/research/evidence-graph" in paths
    assert "/operator/ai/ask" in paths
    assert "/operator/historical-tests" in paths
    assert "/operator/historical-tests/run" in paths
    assert "/operator/historical-tests/{test_id}" in paths
    assert "/operator/historical-tests/{test_id}/report" in paths


def test_operator_intents_are_refused_without_mutation(tmp_path):
    app = _app(tmp_path)

    paper = _endpoint(app, "/operator/intent/paper/start", "POST")()
    live = _endpoint(app, "/operator/intent/live/start", "POST")()
    emergency = _endpoint(app, "/operator/intent/emergency-stop", "POST")()

    for payload in (paper, live, emergency):
        assert payload["status"] == "REFUSED"
        assert payload["mutation_occurred"] is False
        assert payload["broker_call_occurred"] is False
        assert payload["runtime_mutation_occurred"] is False

    assert paper["reason_code"] == "AUTONOMOUS_PAPER_APPROVAL_REQUIRED"
    assert live["reason_code"] == "LIVE_NOT_APPROVED"
    assert emergency["reason_code"] == "EMERGENCY_STOP_INTENT_NOT_IMPLEMENTED"


def test_operator_api_starts_and_tracks_paper_with_injected_supervisor():
    runner = FakeRunner()
    supervisor = OperatorPaperSupervisor(
        config=PaperSupervisorConfig(repo_root=runner.repo_root, process_env=dict(PAPER_ENV)),
        runner=runner,
    )
    app = create_operator_app(provider=OperatorSnapshotProvider(supervisor=supervisor, provider_env=dict(PAPER_ENV)))
    start = _endpoint(app, "/operator/intent/paper/start", "POST")
    runtime = _endpoint(app, "/operator/runtime")

    result = start(
        {
            "mode": "PAPER",
            "profile": "PAPER_EXPLORATION_ALPHA",
            "duration_seconds": 300,
            "watchlist": ["BTC/USD", "ETH/USD", "SOL/USD"],
            "approve_autonomous_paper": True,
        }
    )

    assert result["allowed"] is True
    assert result["reason_code"] == "PAPER_RUN_STARTED"
    assert result["broker_call_occurred"] is False
    assert result["runtime_mutation_occurred"] is True
    runtime_payload = runtime()
    assert runtime_payload["process_state"] == "RUNNING"
    assert runtime_payload["paper_start_allowed"] is False
    assert runtime_payload["paper_stop_allowed"] is True


def test_historical_duplicate_refusal_is_not_current_runtime_blocker(tmp_path):
    runner = FakeRunner()
    store_path = tmp_path / "state" / "operator" / "sessions.jsonl"
    store = OperatorSessionStore(path=store_path)
    supervisor = OperatorPaperSupervisor(
        config=PaperSupervisorConfig(
            repo_root=runner.repo_root,
            process_env=dict(PAPER_ENV),
            session_store_path=str(store_path),
        ),
        runner=runner,
        session_store=store,
    )
    first = supervisor.start_paper(
        {
            "mode": "PAPER",
            "profile": "PAPER_EXPLORATION_ALPHA",
            "duration_seconds": 300,
            "watchlist": ["BTC/USD", "ETH/USD", "SOL/USD"],
            "approve_autonomous_paper": True,
        }
    )
    duplicate = supervisor.start_paper(
        {
            "mode": "PAPER",
            "profile": "PAPER_EXPLORATION_ALPHA",
            "duration_seconds": 300,
            "watchlist": ["BTC/USD", "ETH/USD", "SOL/USD"],
            "approve_autonomous_paper": True,
        }
    )
    runner.process.exit_code = 0
    supervisor.status_snapshot()
    reloaded = OperatorPaperSupervisor(
        config=PaperSupervisorConfig(
            repo_root=runner.repo_root,
            process_env=dict(PAPER_ENV),
            session_store_path=str(store_path),
        ),
        runner=runner,
        session_store=OperatorSessionStore(path=store_path),
    )
    app = create_operator_app(provider=OperatorSnapshotProvider(supervisor=reloaded, provider_env=dict(PAPER_ENV)))

    status = _endpoint(app, "/operator/status")()
    runtime = _endpoint(app, "/operator/runtime")()
    launch = _endpoint(app, "/operator/launch-readiness")()

    assert first["allowed"] is True
    assert duplicate["allowed"] is False
    assert duplicate["reason_code"] == "DUPLICATE_ACTIVE_RUN"
    assert status["dominant_blocker"] == "READY_IDLE_NO_ACTIVE_RUNTIME"
    assert status["runtime_attachment_detail"] == "Ready. No PAPER run currently attached."
    assert status["last_historical_refusal_reason"] == "DUPLICATE_ACTIVE_RUN"
    assert runtime["process_state"] == "NO_ACTIVE_RUNTIME_ATTACHED"
    assert runtime["current_runtime_attached"] is False
    assert runtime["historical_refusal_reason"] == "DUPLICATE_ACTIVE_RUN"
    assert runtime["paper_start_allowed"] is True
    assert launch["final_launch_readiness"] == "READY_FOR_BOUNDED_PAPER"


def test_operator_status_runtime_launch_and_diagnostics_share_safe_paper_endpoint_truth(tmp_path):
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    provider = OperatorSnapshotProvider(
        runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
        provider_env={},
        credential_store=store,
    )
    app = create_operator_app(provider=provider)
    _endpoint(app, "/operator/credentials/save", "POST")(
        {
            "provider_id": "alpaca_paper",
            "credentials": {
                "APCA_API_KEY_ID": "paper-key",
                "APCA_API_SECRET_KEY": "paper-secret",
            },
        }
    )

    status = _endpoint(app, "/operator/status")()
    runtime = _endpoint(app, "/operator/runtime")()
    launch = _endpoint(app, "/operator/launch-readiness")()
    diagnostics = _endpoint(app, "/operator/credentials/diagnostics")()
    text = str((status, runtime, launch, diagnostics))

    assert status["supervisor"]["paper_credentials_configured"] is True
    assert status["supervisor"]["paper_endpoint_only"] is True
    assert status["supervisor"]["paper_endpoint_status"] == "PAPER_ENDPOINT_CONFIRMED"
    assert status["supervisor"]["paper_start_allowed"] is True
    assert runtime["paper_credentials_configured"] is True
    assert runtime["paper_endpoint_only"] is True
    assert runtime["paper_endpoint_status"] == "PAPER_ENDPOINT_CONFIRMED"
    assert runtime["paper_start_allowed"] is True
    assert launch["final_launch_readiness"] == "READY_FOR_BOUNDED_PAPER"
    assert launch["paper_endpoint_status"] == "PAPER_ENDPOINT_CONFIRMED"
    assert diagnostics["paper_endpoint_status"] == "PAPER_ENDPOINT_CONFIRMED"
    assert diagnostics["paper_endpoint_source"] == "CONFIGURED"
    assert "paper-secret" not in text
    assert status["manual_trading_available"] is False
    assert status["force_trade_available"] is False
    assert launch["broker_mutation_occurred"] is False


def test_operator_health_readiness_and_storage_are_safe(tmp_path):
    app = _app(tmp_path)

    health = _endpoint(app, "/operator/health")()
    readiness = _endpoint(app, "/operator/readiness")()
    storage = _endpoint(app, "/operator/storage")()
    diagnostics = _endpoint(app, "/operator/diagnostics")()

    assert health["live_status"] == "LIVE_LOCKED"
    assert health["api_version"] == API_VERSION
    assert health["operator_activation_version"] == OPERATOR_ACTIVATION_VERSION
    assert health["git_commit_short"]
    assert health["git_branch"]
    assert health["process_start_time"]
    assert isinstance(health["backend_pid"], int)
    assert health["real_money_status"] == "BLOCKED"
    assert health["broker_call_occurred"] is False
    assert readiness["live_ready"] is False
    assert readiness["live_refusal_reason"] == "LIVE_NOT_APPROVED"
    assert storage["session_store"]["store_type"] == "jsonl_append_only"
    assert storage["world_awareness_cache"]["cache_type"] == "jsonl_append_only"
    assert storage["stores_log_contents"] is False
    assert diagnostics["operator_config"]["live_enabled"] is False
    assert diagnostics["operator_activation_version"] == OPERATOR_ACTIVATION_VERSION
    assert diagnostics["operator_config"]["real_money_enabled"] is False
    assert diagnostics["storage"]["secrets_values_exposed"] is False


def test_operator_provider_and_research_endpoints_are_safe(tmp_path):
    app = _app(tmp_path)

    providers = _endpoint(app, "/operator/providers")()
    readiness = _endpoint(app, "/operator/providers/readiness")()
    validation = _endpoint(app, "/operator/providers/validate-readonly", "POST")({"provider_id": "alpaca_paper"})
    research = _endpoint(app, "/operator/research")()
    hypothesis = _endpoint(app, "/operator/research/hypotheses", "POST")({"title": "test", "thesis": "edge review"})
    experiment = _endpoint(app, "/operator/research/experiments", "POST")({"title": "paper", "thesis": "paper review"})
    graph = _endpoint(app, "/operator/research/evidence-graph")()

    assert providers["secrets_values_exposed"] is False
    assert providers["raw_secret_values_included"] is False
    assert readiness["can_execute"] is False
    assert validation["broker_call_occurred"] is False
    assert validation["external_mutation_occurred"] is False
    assert research["can_execute"] is False
    assert hypothesis["hypothesis"]["can_execute"] is False
    assert experiment["paper_started"] is False
    assert experiment["broker_call_occurred"] is False
    assert graph["raw_logs_included"] is False
    assert graph["secrets_values_exposed"] is False
    assert graph["can_execute"] is False


def test_provider_launch_readiness_endpoints_return_from_local_truth_under_timeout(tmp_path):
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    store.save_provider("alpaca_paper", {"APCA_API_KEY_ID": "id", "APCA_API_SECRET_KEY": "secret"})
    app = create_operator_app(
        provider=OperatorSnapshotProvider(
            runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
            provider_env={},
            credential_store=store,
        )
    )

    for path in ("/operator/providers", "/operator/providers/readiness", "/operator/launch-readiness"):
        start = time.perf_counter()
        payload = _endpoint(app, path)()
        elapsed = time.perf_counter() - start
        assert elapsed < 1.0, path
        assert payload.get("secrets_values_exposed") is not True


def test_operator_endpoint_smoke_matrix_is_safe(tmp_path):
    app = _app(tmp_path)

    get_paths = [
        "/operator/status",
        "/operator/runtime",
        "/operator/latest-run",
        "/operator/action-center",
        "/operator/providers/readiness",
        "/operator/credentials/providers",
        "/operator/launch-readiness",
        "/operator/portfolio",
        "/operator/positions",
        "/operator/orders/open",
        "/operator/positions/intelligence",
        "/operator/research",
        "/operator/research/evidence-graph",
        "/operator/ai/status",
        "/operator/world-awareness",
        "/operator/world-awareness/providers",
        "/operator/world-awareness/events",
        "/operator/world-awareness/runtime",
        "/operator/readiness/live",
        "/operator/health",
        "/operator/readiness",
        "/operator/storage",
        "/operator/runs",
        "/operator/pnl",
        "/operator/tca",
        "/operator/alerts",
        "/operator/system-map",
        "/operator/historical-tests",
    ]
    for path in get_paths:
        payload = _endpoint(app, path)()
        assert isinstance(payload, dict), path
        assert payload.get("secrets_values_exposed") is not True

    credential_save = _endpoint(app, "/operator/credentials/save", "POST")(
        {"provider_id": "openai", "credentials": {"OPENAI_API_KEY": "sk-smoke-secret-1234567890"}}
    )
    credential_validate = _endpoint(app, "/operator/credentials/validate-readonly", "POST")({"provider_id": "openai"})
    paper_start = _endpoint(app, "/operator/intent/paper/start", "POST")({})
    ai_ask = _endpoint(app, "/operator/ai/ask", "POST")({"question": "Review provider/data readiness."})
    historical = _endpoint(app, "/operator/historical-tests/run", "POST")({"date_range_preset": "last_4_months"})
    text = str((credential_save, credential_validate, paper_start, ai_ask, historical))

    assert "sk-smoke-secret" not in text
    assert credential_save["broker_call_occurred"] is False
    assert credential_validate["broker_call_occurred"] is False
    assert paper_start["broker_call_occurred"] is False
    assert paper_start["runtime_mutation_occurred"] is False
    assert ai_ask["can_execute"] is False
    assert historical["broker_trading_call_occurred"] is False
    assert historical["paper_started"] is False
