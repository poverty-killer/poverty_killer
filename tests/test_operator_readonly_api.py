from __future__ import annotations

from app.api.operator_readonly_api import API_VERSION, create_operator_app


def _endpoint(app, path: str, method: str = "GET"):
    for route in app.routes:
        if route.path == path and method in (route.methods or set()):
            return route.endpoint
    raise AssertionError(f"route not found: {method} {path}")


def test_operator_readonly_status_contract_is_safe_default():
    app = create_operator_app()

    payload = _endpoint(app, "/operator/status")()

    assert payload["api_version"] == API_VERSION
    assert payload["data_source"] == "READ_ONLY_BACKEND"
    assert payload["bot_status"] == "NO_ACTIVE_RUNTIME_ATTACHED"
    assert payload["live_blocked"] is True
    assert payload["real_money_blocked"] is True
    assert payload["manual_trading_available"] is False
    assert payload["force_trade_available"] is False
    assert payload["broker_post_count"] == 0
    assert payload["broker_delete_count"] == 0


def test_operator_live_readiness_is_locked_and_refused():
    app = create_operator_app()

    payload = _endpoint(app, "/operator/readiness/live")()

    assert payload["live_status"] == "LIVE_LOCKED"
    assert payload["refusal_reason"] == "LIVE_NOT_APPROVED"
    assert payload["real_money_authority"] == "BLOCKED"
    assert "separate_live_governance_packet" in payload["missing_prerequisites"]


def test_operator_contracts_distinguish_truth_authorities():
    app = create_operator_app()

    payload = _endpoint(app, "/operator/contracts")()

    assert payload["read_only"] is True
    assert payload["control_policy"]["ui_is_trading_engine"] is False
    assert payload["control_policy"]["manual_trading_available"] is False
    assert payload["control_policy"]["live_operation_available"] is False
    assert payload["truth_labels"]["broker_confirmed"].startswith("Canonical")
    assert payload["truth_labels"]["unknown"].startswith("Truth unavailable")


def test_operator_app_does_not_include_legacy_mutating_dashboard_routes():
    app = create_operator_app()
    routes = {(route.path, ",".join(sorted(route.methods or []))) for route in app.routes}
    paths = {path for path, _methods in routes}

    assert "/api/mode/{mode}" not in paths
    assert "/api/flatten" not in paths
    assert "/operator/status" in paths
    assert "/operator/readiness/live" in paths


def test_operator_intents_are_refused_without_mutation():
    app = create_operator_app()

    paper = _endpoint(app, "/operator/intent/paper/start", "POST")()
    live = _endpoint(app, "/operator/intent/live/start", "POST")()
    emergency = _endpoint(app, "/operator/intent/emergency-stop", "POST")()

    for payload in (paper, live, emergency):
        assert payload["status"] == "REFUSED"
        assert payload["mutation_occurred"] is False
        assert payload["broker_call_occurred"] is False
        assert payload["runtime_mutation_occurred"] is False

    assert paper["reason_code"] == "PAPER_INTENT_NOT_IMPLEMENTED"
    assert live["reason_code"] == "LIVE_NOT_APPROVED"
    assert emergency["reason_code"] == "EMERGENCY_STOP_INTENT_NOT_IMPLEMENTED"
