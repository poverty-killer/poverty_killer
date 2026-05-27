from __future__ import annotations

from app.api.operator_readonly_api import API_VERSION, OperatorSnapshotProvider, create_operator_app
from app.api.operator_paper_supervisor import OperatorPaperSupervisor, PaperSupervisorConfig
from app.api.operator_runtime_config import OperatorRuntimeConfig
from tests.test_operator_paper_supervisor import FakeRunner


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
    supervisor = OperatorPaperSupervisor(config=PaperSupervisorConfig(repo_root=runner.repo_root), runner=runner)
    app = create_operator_app(provider=OperatorSnapshotProvider(supervisor=supervisor))
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


def test_operator_health_readiness_and_storage_are_safe(tmp_path):
    app = _app(tmp_path)

    health = _endpoint(app, "/operator/health")()
    readiness = _endpoint(app, "/operator/readiness")()
    storage = _endpoint(app, "/operator/storage")()
    diagnostics = _endpoint(app, "/operator/diagnostics")()

    assert health["live_status"] == "LIVE_LOCKED"
    assert health["real_money_status"] == "BLOCKED"
    assert health["broker_call_occurred"] is False
    assert readiness["live_ready"] is False
    assert readiness["live_refusal_reason"] == "LIVE_NOT_APPROVED"
    assert storage["session_store"]["store_type"] == "jsonl_append_only"
    assert storage["world_awareness_cache"]["cache_type"] == "jsonl_append_only"
    assert storage["stores_log_contents"] is False
    assert diagnostics["operator_config"]["live_enabled"] is False
    assert diagnostics["operator_config"]["real_money_enabled"] is False
    assert diagnostics["storage"]["secrets_values_exposed"] is False
