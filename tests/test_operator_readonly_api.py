from __future__ import annotations

import inspect
import asyncio
import time
import os
from pathlib import Path

import pytest

from app.api.operator_readonly_api import API_VERSION, OPERATOR_ACTIVATION_VERSION, OperatorSnapshotProvider, create_operator_app
from app.api.operator_paper_supervisor import OperatorPaperSupervisor, PaperSupervisorConfig
from app.api.operator_runtime_config import OperatorRuntimeConfig
from app.api.operator_session_store import OperatorSessionStore
from app.operator_activation.paper_baseline import BASELINE_POLICY_PROTECTED
from app.operator_credentials.store import ALPACA_PAPER_ENV_PATH_ENV_KEY, LocalCredentialStore
from tests.test_operator_paper_supervisor import FakeRunner


PAPER_ENV = {
    "APCA_API_KEY_ID": "test-paper-key",
    "APCA_API_SECRET_KEY": "test-paper-secret",
    "APCA_API_BASE_URL": "https://paper-api.alpaca.markets",
}


def _account_pin_ok_assertion() -> dict:
    return {
        "source": "TEST_ACCOUNT_PIN",
        "status": "PASS",
        "reason_code": "ALPACA_PAPER_ACCOUNT_PIN_OK",
        "detail": "offline unit test account pin is pre-proven",
        "expected_suffix": "045ded",
        "actual_suffix": "045ded",
        "paper_account_pinned": True,
        "broker_read_attempted": True,
        "broker_read_occurred": True,
        "account_request_occurred": True,
        "broker_mutation_occurred": False,
        "order_submission_occurred": False,
        "cancel_occurred": False,
        "liquidation_occurred": False,
        "live_enabled": False,
        "real_money_enabled": False,
        "secrets_values_exposed": False,
    }


@pytest.fixture(autouse=True)
def _offline_account_pin_for_legacy_api_tests(monkeypatch):
    monkeypatch.setattr(
        OperatorPaperSupervisor,
        "_paper_account_identity_assertion",
        lambda self, *, force=False: _account_pin_ok_assertion(),
    )


@pytest.fixture(autouse=True)
def _isolated_canonical_paper_env(monkeypatch, tmp_path) -> Path:
    path = tmp_path / "canonical_alpaca_paper.env"
    monkeypatch.setenv(ALPACA_PAPER_ENV_PATH_ENV_KEY, str(path))
    return path


def _write_canonical_paper_env(path: Path | None = None, *, base_url: str | None = None) -> None:
    path = path or Path(os.environ[ALPACA_PAPER_ENV_PATH_ENV_KEY])
    lines: list[str] = []
    if base_url is not None:
        lines.append(f"APCA_API_BASE_URL={base_url}")
    lines.extend(
        [
            "APCA_API_KEY_ID=paper-key",
            "APCA_API_SECRET_KEY=paper-secret",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _verified_broker_snapshot() -> dict:
    return {
        "endpoint_family": "paper",
        "account": {
            "id": "paper-account-045ded",
            "status": "ACTIVE",
            "equity": "10000",
            "portfolio_value": "10000",
            "cash": "7500",
            "buying_power": "15000",
            "currency": "USD",
            "trading_blocked": False,
            "account_blocked": False,
            "transfers_blocked": False,
            "pattern_day_trader": False,
        },
        "positions": [
            {
                "symbol": "BTCUSD",
                "asset_class": "crypto",
                "qty": "0.1",
                "side": "long",
                "avg_entry_price": "50000",
                "current_price": "51000",
                "cost_basis": "5000",
                "market_value": "5100",
                "unrealized_pl": "100",
                "unrealized_plpc": "0.02",
            }
        ],
        "position_count": 1,
        "open_orders": [],
        "open_order_count": 0,
    }


class FakeReadOnlyClient:
    def __init__(self, snapshot: dict | None = None):
        self.calls = []
        self.snapshot = snapshot or {
            **_verified_broker_snapshot(),
            "positions": [],
            "position_count": 0,
        }

    def get_json(self, path, headers):
        self.calls.append(("GET", path))
        if path == "/v2/account":
            return dict(self.snapshot["account"])
        if path.startswith("/v2/positions"):
            return list(self.snapshot.get("positions") or [])
        if path.startswith("/v2/orders"):
            return list(self.snapshot.get("open_orders") or [])
        raise AssertionError(f"unexpected read-only path: {path}")


def _paper_read_confirmations() -> dict:
    return {
        "mode": "PAPER",
        "live": False,
        "real_money": False,
        "confirm_paper_read_only": True,
        "confirm_account_positions_orders_get_only": True,
        "confirm_no_broker_mutation": True,
        "confirm_process_scoped_authorization": True,
    }


def _verified_provider(
    supervisor: OperatorPaperSupervisor,
    *,
    stack_exit_callback=None,
    operator_ui_idle_shutdown_enabled: bool | None = None,
    operator_ui_disconnect_grace_seconds: float = 8.0,
) -> tuple[OperatorSnapshotProvider, dict]:
    _write_canonical_paper_env()
    snapshot = _verified_broker_snapshot()
    provider = OperatorSnapshotProvider(
        supervisor=supervisor,
        provider_env=dict(PAPER_ENV),
        portfolio_client=FakeReadOnlyClient(snapshot),
        stack_exit_callback=stack_exit_callback,
        operator_ui_idle_shutdown_enabled=operator_ui_idle_shutdown_enabled,
        operator_ui_disconnect_grace_seconds=operator_ui_disconnect_grace_seconds,
    )
    accepted = provider.paper_baseline_accept(
        {
            "preflight_snapshot": snapshot,
            "policy": BASELINE_POLICY_PROTECTED,
            "accepted_by_operator": "offline API test",
        }
    )
    assert accepted["accepted"] is True
    verified = provider.paper_broker_preflight_intent(_paper_read_confirmations())
    assert verified["allowed"] is True
    assert verified["broker_mutation_occurred"] is False
    return provider, verified


def _endpoint(app, path: str, method: str = "GET"):
    for route in app.routes:
        if route.path == path and method in (route.methods or set()):
            def call(*args, _endpoint=route.endpoint, **kwargs):
                result = _endpoint(*args, **kwargs)
                if inspect.isawaitable(result):
                    return asyncio.run(result)
                return result

            return call
    raise AssertionError(f"route not found: {method} {path}")


def _wait_until(predicate, *, timeout: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return bool(predicate())


def _app(tmp_path):
    runtime_config = OperatorRuntimeConfig.from_env({}, repo_root=tmp_path)
    return create_operator_app(provider=OperatorSnapshotProvider(runtime_config=runtime_config))


def test_operator_readonly_status_contract_is_safe_default(tmp_path):
    app = _app(tmp_path)

    payload = _endpoint(app, "/operator/status")()

    assert payload["api_version"] == API_VERSION
    assert payload["data_source"] == "OPERATOR_BACKEND"
    assert payload["bot_status"] == "IDLE_NO_ACTIVE_PAPER_RUN"
    assert payload["live_blocked"] is True
    assert payload["real_money_blocked"] is True
    assert payload["broker"] == "alpaca_paper"
    assert payload["endpoint"] == "https://paper-api.alpaca.markets"
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
    assert payload["view_models"]["run_paper_operator_state"]["canonical_authority"] == "OPERATOR_PAPER_CONTROL_STATE"
    assert payload["view_models"]["run_paper_operator_state"]["endpoint"] == "/operator/paper-control-state"
    assert payload["view_models"]["run_paper_operator_state"]["raw_codes_in_advanced_details"] is True
    assert payload["view_models"]["run_paper_operator_state"]["broker_mutation_occurred"] is False
    setup_contract = payload["view_models"]["run_paper_operator_state"]["paper_credential_setup"]
    assert setup_contract["schema_version"] == "paper-credential-setup-v1"
    assert setup_contract["approved_secret_path"] == "~/.poverty_killer_alpaca_paper_env"
    assert setup_contract["read_only_preflight_authorized"] is False
    assert "GET /v2/account" in setup_contract["read_only_preflight_checks"]
    assert setup_contract["alpaca_network_call_occurred"] is False
    assert setup_contract["secrets_values_exposed"] is False
    baseline_contract = payload["view_models"]["run_paper_operator_state"]["paper_baseline"]
    assert baseline_contract["canonical_authority"] == "OPERATOR_PAPER_BASELINE"
    assert baseline_contract["local_acceptance_only"] is True
    assert baseline_contract["broker_mutation_occurred"] is False
    assert payload["truth_labels"]["broker_confirmed"].startswith("Canonical")
    assert payload["truth_labels"]["unknown"].startswith("Truth unavailable")


def test_operator_app_does_not_include_legacy_mutating_dashboard_routes(tmp_path):
    app = _app(tmp_path)
    routes = {(route.path, ",".join(sorted(getattr(route, "methods", set()) or []))) for route in app.routes}
    paths = {path for path, _methods in routes}

    assert "/api/mode/{mode}" not in paths
    assert "/api/flatten" not in paths
    assert "/operator/status" in paths
    assert "/operator/launcher-status" in paths
    assert "/operator/version" in paths
    assert "/operator/runtime-minimal" in paths
    assert "/operator/perf/recent" in paths
    assert "/operator/events" in paths
    assert "/operator/readiness/live" in paths
    assert "/operator/providers" in paths
    assert "/operator/credentials/providers" in paths
    assert "/operator/portfolio" in paths
    assert "/operator/positions" in paths
    assert "/operator/orders/open" in paths
    assert "/operator/positions/intelligence" in paths
    assert "/operator/cockpit/capabilities" in paths
    assert "/operator/cockpit/asset-mandate" in paths
    assert "/operator/cockpit/day-trader-mode" in paths
    assert "/operator/paper-control-state" in paths
    assert "/operator/paper-baseline" in paths
    assert "/operator/paper-baseline/accept" in paths
    assert "/operator/intent/paper/verify-readonly" in paths
    assert "/operator/launch-readiness" in paths
    assert "/operator/research" in paths
    assert "/operator/research/evidence-graph" in paths
    assert "/operator/ai/ask" in paths
    assert "/operator/historical-tests" in paths
    assert "/operator/historical-tests/run" in paths
    assert "/operator/historical-tests/{test_id}" in paths
    assert "/operator/historical-tests/{test_id}/report" in paths


def test_operator_event_stream_emits_changes_not_idle_one_second_duplicates(tmp_path):
    provider = OperatorSnapshotProvider(runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path))
    app = create_operator_app(provider=provider)
    response = _endpoint(app, "/operator/events")()

    async def collect_initial_then_wait_for_duplicate():
        iterator = response.body_iterator.__aiter__()
        initial = [await iterator.__anext__() for _ in range(3)]
        assert provider.operator_ui_connection_status()["connected_clients"] == 1
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(iterator.__anext__(), timeout=2.2)
        await iterator.aclose()
        return initial

    initial = asyncio.run(collect_initial_then_wait_for_duplicate())
    event_names = [chunk.split("\n", 1)[0] for chunk in initial]

    assert event_names == [
        "event: backend_status",
        "event: launcher_status",
        "event: runtime_minimal",
    ]
    connection = provider.operator_ui_connection_status()
    assert connection["connected_clients"] == 0
    assert connection["last_disconnect_action"] == "IDLE_SHUTDOWN_DISABLED"


def test_operator_ui_last_disconnect_stops_only_after_all_clients_and_reconnect_grace(tmp_path):
    exit_calls: list[str] = []
    provider = OperatorSnapshotProvider(
        runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
        stack_exit_callback=lambda: exit_calls.append("scheduled"),
        operator_ui_idle_shutdown_enabled=True,
        operator_ui_disconnect_grace_seconds=0.04,
    )

    first = provider.operator_ui_connected()
    second = provider.operator_ui_connected()
    one_left = provider.operator_ui_disconnected()

    assert first["connected_clients"] == 1
    assert second["connected_clients"] == 2
    assert one_left["connected_clients"] == 1
    assert one_left["last_disconnect_action"] == "OTHER_COCKPIT_CLIENTS_REMAIN"
    time.sleep(0.06)
    assert exit_calls == []

    pending = provider.operator_ui_disconnected()
    assert pending["last_disconnect_action"] == "IDLE_SHUTDOWN_GRACE_PENDING"
    time.sleep(0.01)
    reconnected = provider.operator_ui_connected()
    assert reconnected["connected_clients"] == 1
    time.sleep(0.06)
    assert exit_calls == []

    provider.operator_ui_disconnected()
    assert _wait_until(lambda: exit_calls == ["scheduled"])
    status = provider.operator_ui_connection_status()
    assert status["connected_clients"] == 0
    assert status["last_disconnect_action"] == "NO_ACTIVE_RUN"
    assert status["broker_call_occurred"] is False
    assert status["broker_mutation_occurred"] is False


def test_operator_ui_disconnect_preserves_attached_paper_runtime(tmp_path):
    _write_canonical_paper_env()
    runner = FakeRunner()
    supervisor = OperatorPaperSupervisor(
        config=PaperSupervisorConfig(repo_root=runner.repo_root, process_env=dict(PAPER_ENV)),
        runner=runner,
    )
    exit_calls: list[str] = []
    provider, _verified = _verified_provider(
        supervisor,
        stack_exit_callback=lambda: exit_calls.append("scheduled"),
        operator_ui_idle_shutdown_enabled=True,
        operator_ui_disconnect_grace_seconds=0.01,
    )
    started = provider.paper_start_intent(
        {
            "mode": "PAPER",
            "profile": "PAPER_EXPLORATION_ALPHA",
            "duration_seconds": 300,
            "watchlist": ["BTC/USD"],
            "approve_autonomous_paper": True,
            "real_money": False,
            "live": False,
        }
    )
    assert started["allowed"] is True

    provider.operator_ui_connected()
    provider.operator_ui_disconnected()
    assert _wait_until(
        lambda: provider.operator_ui_connection_status()["last_disconnect_action"]
        == "ACTIVE_OR_UNCERTAIN_RUNTIME_PROTECTED_FROM_AUTOMATIC_SHUTDOWN"
    )

    assert exit_calls == []
    assert runner.shutdown_requests == 0
    assert supervisor.status_snapshot()["state"] == "RUNNING"
    assert supervisor.status_snapshot()["paper_stop_allowed"] is True

    refused = provider.stack_shutdown_intent(
        {
            "confirm_shutdown_stack": True,
            "confirm_api_process_exit": True,
            "confirm_preserve_broker_positions": True,
            "confirm_no_broker_cleanup_requested": True,
            "require_idle_supervisor": True,
            "requested_by": "active_runtime_race_test",
        }
    )
    assert refused["allowed"] is False
    assert refused["reason_code"] == "ACTIVE_OR_UNCERTAIN_RUNTIME_PROTECTED_FROM_AUTOMATIC_SHUTDOWN"
    assert refused["api_exit_scheduled"] is False
    assert refused["broker_call_occurred"] is False
    assert refused["broker_mutation_occurred"] is False
    assert runner.shutdown_requests == 0


def test_idle_stack_shutdown_blocks_later_start_without_broker_mutation(tmp_path):
    provider = OperatorSnapshotProvider(
        runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
        stack_exit_callback=lambda: None,
    )
    shutdown = provider.stack_shutdown_intent(
        {
            "confirm_shutdown_stack": True,
            "confirm_api_process_exit": True,
            "confirm_preserve_broker_positions": True,
            "confirm_no_broker_cleanup_requested": True,
            "require_idle_supervisor": True,
            "dry_run": True,
            "requested_by": "idle_shutdown_race_test",
        }
    )
    refused_start = provider.paper_start_intent(
        {
            "mode": "PAPER",
            "profile": "PAPER_EXPLORATION_ALPHA",
            "duration_seconds": 300,
            "watchlist": ["BTC/USD"],
            "approve_autonomous_paper": True,
            "real_money": False,
            "live": False,
        }
    )

    assert shutdown["allowed"] is True
    assert shutdown["idle_only_shutdown"] is True
    assert shutdown["supervisor_state"] == "IDLE"
    assert shutdown["api_exit_scheduled"] is False
    assert shutdown["broker_call_occurred"] is False
    assert shutdown["broker_mutation_occurred"] is False
    assert refused_start["allowed"] is False
    assert refused_start["reason_code"] == "STACK_SHUTDOWN_IN_PROGRESS"
    assert refused_start["broker_call_occurred"] is False
    assert refused_start["broker_mutation_occurred"] is False


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
    assert emergency["reason_code"] == "EMERGENCY_STOP_NOT_EXPOSED_IN_OPERATOR_UI"


def test_operator_cockpit_capabilities_gate_future_modes_without_mutation(tmp_path):
    app = _app(tmp_path)

    caps = _endpoint(app, "/operator/cockpit/capabilities")()
    crypto = _endpoint(app, "/operator/cockpit/asset-mandate", "POST")({"asset_class": "crypto"})
    equities = _endpoint(app, "/operator/cockpit/asset-mandate", "POST")({"asset_class": "equities"})
    auto = _endpoint(app, "/operator/cockpit/asset-mandate", "POST")({"asset_class": "auto"})
    day = _endpoint(app, "/operator/cockpit/day-trader-mode", "POST")({"enabled": True})

    assert caps["source"] == "OPERATOR_COCKPIT_CAPABILITIES"
    assert caps["active_asset_class"] == "crypto"
    assert caps["mandate_policy"]["switch_semantics"] == "NEXT_CAPITAL_ONLY_EXISTING_POSITIONS_RIDE"
    assert caps["mandate_policy"]["existing_positions_liquidated"] is False
    assert caps["control_policy"]["manual_trading_available"] is False
    assert caps["control_policy"]["broker_mutation_available"] is False
    assert caps["day_trader_mode"]["server_rejected"] is True

    assert crypto["status"] == "ACCEPTED"
    assert crypto["accepted"] is True
    assert crypto["broker_mutation_occurred"] is False
    assert crypto["strategy_mutation_occurred"] is False
    assert crypto["liquidation_occurred"] is False

    for result in (equities, auto, day):
        assert result["status"] == "REFUSED"
        assert result["accepted"] is False
        assert result["broker_call_occurred"] is False
        assert result["broker_mutation_occurred"] is False
        assert result["runtime_mutation_occurred"] is False
        assert result["strategy_mutation_occurred"] is False
        assert result["liquidation_occurred"] is False
        assert result["live_enabled"] is False
        assert result["real_money_enabled"] is False
        assert result["secrets_values_exposed"] is False


def test_operator_api_starts_and_tracks_paper_with_injected_supervisor():
    _write_canonical_paper_env()
    runner = FakeRunner()
    supervisor = OperatorPaperSupervisor(
        config=PaperSupervisorConfig(repo_root=runner.repo_root, process_env=dict(PAPER_ENV)),
        runner=runner,
    )
    provider, verified = _verified_provider(supervisor)
    app = create_operator_app(provider=provider)
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
    assert verified["broker_read_occurred"] is True
    assert result["broker_call_occurred"] is True
    assert result["broker_mutation_occurred"] is False
    assert result["runtime_mutation_occurred"] is True
    runtime_payload = runtime()
    assert runtime_payload["process_state"] == "RUNNING"
    assert runtime_payload["paper_start_allowed"] is False
    assert runtime_payload["paper_stop_allowed"] is True


def test_paper_control_state_is_canonical_safe_run_paper_payload(tmp_path):
    _write_canonical_paper_env()
    runner = FakeRunner()
    supervisor = OperatorPaperSupervisor(
        config=PaperSupervisorConfig(repo_root=runner.repo_root, process_env=dict(PAPER_ENV)),
        runner=runner,
    )
    app = create_operator_app(
        provider=OperatorSnapshotProvider(
            supervisor=supervisor,
            provider_env=dict(PAPER_ENV),
            portfolio_client=FakeReadOnlyClient(),
        )
    )

    payload = _endpoint(app, "/operator/paper-control-state")()

    assert payload["source"] == "OPERATOR_PAPER_CONTROL_STATE"
    assert payload["data_source"] == "OPERATOR_BACKEND"
    assert payload["paper_only"] is True
    assert payload["live_locked"] is True
    assert payload["real_money_blocked"] is True
    assert payload["endpoint_family"] == "paper"
    assert payload["endpoint_host"] == "paper-api.alpaca.markets"
    assert payload["credential_status"] == "CONFIGURED"
    assert payload["paper_account_pinned"] is False
    assert payload["paper_account_expected_suffix"] == "045ded"
    assert payload["paper_account_actual_suffix"] is None
    assert payload["paper_account_identity_assertion"]["reason_code"] == "PAPER_BROKER_PREFLIGHT_REQUIRED"
    assert payload["portfolio_truth_status"] == "PORTFOLIO_READ_AVAILABLE_SEPARATELY"
    assert payload["portfolio_data_source"] == "CONTROL_STATE_FAST_PATH_NO_BROKER_READ"
    assert payload["positions_count"] == 0
    assert payload["open_orders_count"] == 0
    assert payload["paper_start_allowed"] is False
    assert payload["dominant_blocker"] == "PAPER_BROKER_PREFLIGHT_REQUIRED"
    assert "PAPER_BROKER_PREFLIGHT_REQUIRED" in payload["reason_codes"]
    assert payload["max_lease_seconds"] == 432000
    assert 432000 in payload["allowed_durations"]
    assert isinstance(payload["total_elapsed_ms"], float)
    assert payload["total_elapsed_ms"] < 3000
    subchecks = {row["name"]: row for row in payload["subchecks"]}
    assert subchecks["provider_env_refresh"]["status"] == "OK"
    assert subchecks["credential_summary"]["status"] == "OK"
    assert subchecks["endpoint_authority"]["status"] == "OK"
    assert subchecks["launch_readiness"]["status"] == "SKIPPED"
    assert subchecks["launch_readiness"]["reason_code"] == "LAUNCH_READINESS_NOT_ON_FAST_PATH"
    assert subchecks["portfolio_snapshot"]["status"] == "SKIPPED"
    assert subchecks["portfolio_snapshot"]["reason_code"] == "PORTFOLIO_SNAPSHOT_NOT_ON_FAST_PATH"
    assert subchecks["broker_read"]["status"] == "SKIPPED"
    assert payload["broker_call_occurred"] is False
    assert payload["broker_mutation_occurred"] is False
    assert payload["secrets_values_exposed"] is False


def test_paper_control_state_avoids_slow_portfolio_and_launch_paths(tmp_path):
    class SlowForbiddenProvider(OperatorSnapshotProvider):
        def portfolio(self):
            time.sleep(1)
            raise AssertionError("paper_control_state must not call portfolio")

        def launch_readiness(self):
            time.sleep(1)
            raise AssertionError("paper_control_state must not call launch_readiness")

    runner = FakeRunner()
    supervisor = OperatorPaperSupervisor(
        config=PaperSupervisorConfig(repo_root=runner.repo_root, process_env=dict(PAPER_ENV)),
        runner=runner,
    )
    provider = SlowForbiddenProvider(
        supervisor=supervisor,
        provider_env=dict(PAPER_ENV),
        portfolio_client=FakeReadOnlyClient(),
    )
    app = create_operator_app(provider=provider)

    started = time.perf_counter()
    payload = _endpoint(app, "/operator/paper-control-state")()
    elapsed = time.perf_counter() - started

    assert elapsed < 0.5
    assert payload["total_elapsed_ms"] < 500
    assert payload["portfolio_truth_status"] == "PORTFOLIO_READ_AVAILABLE_SEPARATELY"
    assert payload["launch_readiness"]["reason_code"] == "LAUNCH_READINESS_NOT_ON_FAST_PATH"
    assert payload["broker_call_occurred"] is False


def test_paper_control_state_has_no_self_http_calls():
    source = inspect.getsource(OperatorSnapshotProvider.paper_control_state)

    assert "127.0.0.1" not in source
    assert "localhost" not in source
    assert "http://" not in source
    assert "/operator/portfolio" not in source
    assert "/operator/latest-run" not in source
    assert "/operator/launch-readiness" not in source


def test_paper_control_state_dominant_blocker_is_active_supervisor_when_running():
    runner = FakeRunner()
    supervisor = OperatorPaperSupervisor(
        config=PaperSupervisorConfig(repo_root=runner.repo_root, process_env=dict(PAPER_ENV)),
        runner=runner,
    )
    provider, _verified = _verified_provider(supervisor)
    started = supervisor.start_paper(
        {
            "mode": "PAPER",
            "profile": "PAPER_EXPLORATION_ALPHA",
            "duration_seconds": 300,
            "watchlist": ["BTC/USD", "ETH/USD", "SOL/USD"],
            "approve_autonomous_paper": True,
        }
    )
    app = create_operator_app(provider=provider)

    payload = _endpoint(app, "/operator/paper-control-state")()

    assert started["allowed"] is True
    assert payload["supervisor_state"] == "RUNNING"
    assert payload["active_run_id"] == started["session_id"]
    assert payload["paper_start_allowed"] is False
    assert payload["paper_stop_allowed"] is True
    assert payload["dominant_blocker"] == "SUPERVISOR_PROCESS_RUNNING_OR_RECENT"
    assert "SUPERVISOR_PROCESS_RUNNING_OR_RECENT" in payload["reason_codes"]


def test_historical_duplicate_refusal_is_not_current_blocker_but_restart_requires_fresh_preflight(tmp_path):
    _write_canonical_paper_env()
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
    _provider, _verified = _verified_provider(supervisor)
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
    assert status["dominant_blocker"] == "PAPER_BROKER_PREFLIGHT_REQUIRED"
    assert "start blocked by PAPER_BROKER_PREFLIGHT_REQUIRED" in status["runtime_attachment_detail"]
    assert status["last_historical_refusal_reason"] == "DUPLICATE_ACTIVE_RUN"
    assert runtime["process_state"] == "NO_ACTIVE_RUNTIME_ATTACHED"
    assert runtime["current_runtime_attached"] is False
    assert runtime["historical_refusal_reason"] == "DUPLICATE_ACTIVE_RUN"
    assert runtime["paper_start_allowed"] is False
    assert runtime["paper_start_refusal_reason"] == "PAPER_BROKER_PREFLIGHT_REQUIRED"
    assert launch["final_launch_readiness"] == "BLOCKED"
    assert "paper_read_only_preflight_gate" in launch["reason_codes"]


def test_operator_status_runtime_launch_and_diagnostics_share_safe_paper_endpoint_truth(
    tmp_path,
    _isolated_canonical_paper_env,
):
    _write_canonical_paper_env(_isolated_canonical_paper_env)
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
    assert status["supervisor"]["paper_start_allowed"] is False
    assert status["supervisor"]["paper_start_refusal_reason"] == "PAPER_BROKER_PREFLIGHT_REQUIRED"
    assert runtime["paper_credentials_configured"] is True
    assert runtime["paper_endpoint_only"] is True
    assert runtime["paper_endpoint_status"] == "PAPER_ENDPOINT_CONFIRMED"
    assert runtime["paper_start_allowed"] is False
    assert runtime["paper_start_refusal_reason"] == "PAPER_BROKER_PREFLIGHT_REQUIRED"
    assert launch["final_launch_readiness"] == "BLOCKED"
    assert launch["paper_start_allowed"] is False
    assert launch["paper_credential_setup"]["preflight_gate"]["read_only_preflight_authorized"] is False
    assert launch["paper_credential_setup"]["preflight_gate"]["alpaca_network_call_occurred"] is False
    assert launch["paper_endpoint_status"] == "PAPER_ENDPOINT_CONFIRMED"
    assert diagnostics["paper_endpoint_status"] == "PAPER_ENDPOINT_CONFIRMED"
    assert diagnostics["paper_endpoint_source"] == "SAFE_DEFAULT_PAPER_ENDPOINT"
    assert diagnostics["paper_endpoint_display"] == "https://paper-api.alpaca.markets"
    assert diagnostics["paper_endpoint_family"] == "paper"
    assert diagnostics["alpaca_endpoint_configured"] is False
    assert diagnostics["alpaca_paper_endpoint_valid"] is True
    assert diagnostics["alpaca_live_endpoint_blocked"] is True
    assert "paper-secret" not in text
    assert status["manual_trading_available"] is False
    assert status["force_trade_available"] is False
    assert launch["broker_mutation_occurred"] is False


def test_operator_api_exposes_stale_reconcile_intent_without_broker_call(tmp_path):
    _write_canonical_paper_env()
    runner = FakeRunner()
    store = OperatorSessionStore(runner.repo_root / "state" / "operator" / "sessions.jsonl")
    store.write_session(
        {
            "session_id": "paper_stale_route",
            "requested_at": "2026-06-14T04:17:12+00:00",
            "status": "RUNNING",
            "profile": "PAPER_EXPLORATION_ALPHA",
            "watchlist": ["BTC/USD", "ETH/USD", "SOL/USD"],
            "duration_seconds": 300,
            "pid": 987654,
            "started_at": "2026-06-14T04:17:12+00:00",
        }
    )
    supervisor = OperatorPaperSupervisor(
        config=PaperSupervisorConfig(
            repo_root=runner.repo_root,
            process_env=dict(PAPER_ENV),
            session_store_path=str(store.path),
            startup_lifecycle_reconcile=False,
        ),
        runner=runner,
        session_store=store,
    )
    supervisor._is_pid_running = lambda pid: (False, "STALE_SESSION_PROCESS_NOT_RUNNING")  # type: ignore[method-assign]
    app = create_operator_app(provider=OperatorSnapshotProvider(supervisor=supervisor, provider_env=dict(PAPER_ENV)))

    before = _endpoint(app, "/operator/paper-control-state")()
    result = _endpoint(app, "/operator/intent/paper/reconcile-stale", "POST")(
        {
            "confirm_stale_session_reviewed": True,
            "confirm_previous_process_not_running": True,
            "confirm_runtime_visibility_stopped": True,
            "confirm_no_broker_cleanup_requested": True,
        }
    )
    latest = _endpoint(app, "/operator/latest-run")()
    contracts = _endpoint(app, "/operator/contracts")()

    assert before["stale_reconciliation"]["available"] is True
    assert before["stale_reconciliation"]["broker_mutation_occurred"] is False
    assert result["allowed"] is True
    assert result["reason_code"] == "STALE_SESSION_RECONCILED_PID_NOT_RUNNING"
    assert result["broker_call_occurred"] is False
    assert result["broker_mutation_occurred"] is False
    assert result["runtime_mutation_occurred"] is True
    assert latest["state"] == "IDLE"
    assert latest["paper_start_allowed"] is False
    assert latest["paper_start_refusal_reason"] == "PAPER_BROKER_PREFLIGHT_REQUIRED"
    assert "/operator/intent/paper/reconcile-stale" in contracts["disabled_intents"]


def test_operator_api_stack_shutdown_is_confirmed_process_only_lifecycle_intent(tmp_path):
    _write_canonical_paper_env()
    runner = FakeRunner()
    supervisor = OperatorPaperSupervisor(
        config=PaperSupervisorConfig(repo_root=runner.repo_root, process_env=dict(PAPER_ENV)),
        runner=runner,
    )
    exit_calls = []
    provider, _verified = _verified_provider(
        supervisor,
        stack_exit_callback=lambda: exit_calls.append("scheduled"),
    )
    app = create_operator_app(provider=provider)
    started = _endpoint(app, "/operator/intent/paper/start", "POST")(
        {
            "mode": "PAPER",
            "profile": "PAPER_EXPLORATION_ALPHA",
            "duration_seconds": 300,
            "watchlist": ["BTC/USD"],
            "approve_autonomous_paper": True,
            "real_money": False,
            "live": False,
        }
    )

    refused = _endpoint(app, "/operator/intent/stack/shutdown", "POST")({})
    shutdown = _endpoint(app, "/operator/intent/stack/shutdown", "POST")(
        {
            "confirm_shutdown_stack": True,
            "confirm_api_process_exit": True,
            "confirm_preserve_broker_positions": True,
            "confirm_no_broker_cleanup_requested": True,
        }
    )
    latest = _endpoint(app, "/operator/latest-run")()
    contracts = _endpoint(app, "/operator/contracts")()

    assert started["allowed"] is True
    assert refused["allowed"] is False
    assert refused["reason_code"] == "MISSING_STACK_SHUTDOWN_CONFIRMATION"
    assert shutdown["allowed"] is True
    assert shutdown["intent"] == "stack_shutdown"
    assert shutdown["api_exit_scheduled"] is True
    assert shutdown["process_only_shutdown"] is True
    assert shutdown["broker_call_occurred"] is False
    assert shutdown["broker_mutation_occurred"] is False
    assert shutdown["order_submission_occurred"] is False
    assert shutdown["liquidation_occurred"] is False
    assert runner.shutdown_requests == 1
    assert exit_calls == ["scheduled"]
    assert latest["latest_session"]["status"] == "STOP_REQUESTED"
    assert "/operator/intent/stack/shutdown" in contracts["disabled_intents"]


def test_operator_run_visibility_uses_supervisor_overlay_for_active_session(tmp_path):
    _write_canonical_paper_env()
    runner = FakeRunner()
    supervisor = OperatorPaperSupervisor(
        config=PaperSupervisorConfig(repo_root=runner.repo_root, process_env=dict(PAPER_ENV)),
        runner=runner,
    )
    provider, _verified = _verified_provider(supervisor)
    app = create_operator_app(provider=provider)

    started = _endpoint(app, "/operator/intent/paper/start", "POST")(
        {
            "mode": "PAPER",
            "profile": "PAPER_EXPLORATION_ALPHA",
            "duration_seconds": 300,
            "watchlist": ["BTC/USD"],
            "approve_autonomous_paper": True,
            "real_money": False,
            "live": False,
        }
    )
    visibility = _endpoint(app, "/operator/run-visibility/status")()

    assert started["allowed"] is True
    assert visibility["status"] == "RUNNING"
    assert visibility["prominent_state"] == "RUNNING"
    assert visibility["data_source"] == "OPERATOR_SUPERVISOR_AND_LOCAL_RUNTIME_ARTIFACTS"
    assert visibility["operator_supervisor"]["active_session_id"] == started["session_id"]
    assert visibility["operator_supervisor"]["paper_stop_allowed"] is True
    assert visibility["bot_vital_status"] == "STALE"
    assert visibility["pulse_animation_allowed"] is False
    assert visibility["broker_call_occurred"] is False
    assert visibility["broker_mutation_occurred"] is False
    assert visibility["order_submission_occurred"] is False
    assert visibility["live_enabled"] is False
    assert visibility["real_money_enabled"] is False


def test_operator_health_readiness_and_storage_are_safe(tmp_path):
    app = _app(tmp_path)

    health = _endpoint(app, "/operator/health")()
    readiness = _endpoint(app, "/operator/readiness")()
    storage = _endpoint(app, "/operator/storage")()
    diagnostics = _endpoint(app, "/operator/diagnostics")()

    assert health["live_status"] == "LIVE_LOCKED"
    assert health["ok"] is True
    assert health["api_version"] == API_VERSION
    assert health["operator_activation_version"] == OPERATOR_ACTIVATION_VERSION
    assert health["git_commit_short"]
    assert health["git_branch"]
    assert health["loaded_commit"] == health["git_commit_short"]
    assert health["loaded_branch"] == health["git_branch"]
    assert health["repo_head"] == health["git_commit_short"]
    assert health["branch"] == health["git_branch"]
    assert health["process_start_time"]
    assert isinstance(health["backend_pid"], int)
    assert isinstance(health["pid"], int)
    assert health["paper_only"] is True
    assert health["real_money_status"] == "BLOCKED"
    assert health["broker_call_occurred"] is False
    assert health["elapsed_ms"] < 500
    assert health["session_store_status"] == "NOT_ON_HEALTH_FAST_PATH"
    assert health["world_awareness_cache_status"] == "NOT_ON_HEALTH_FAST_PATH"
    assert health["config_status"] == "NOT_ON_HEALTH_FAST_PATH"
    assert readiness["live_ready"] is False
    assert readiness["live_refusal_reason"] == "LIVE_NOT_APPROVED"
    assert storage["session_store"]["store_type"] == "jsonl_append_only"
    assert storage["world_awareness_cache"]["cache_type"] == "jsonl_append_only"
    assert storage["stores_log_contents"] is False
    assert diagnostics["operator_config"]["live_enabled"] is False
    assert diagnostics["operator_activation_version"] == OPERATOR_ACTIVATION_VERSION
    assert diagnostics["operator_config"]["real_money_enabled"] is False
    assert diagnostics["storage"]["secrets_values_exposed"] is False


def test_operator_ui_index_is_no_store_and_commit_cache_busted(tmp_path):
    app = _app(tmp_path)

    health = _endpoint(app, "/operator/health")()
    response = _endpoint(app, "/operator-ui/")()
    response_no_slash = _endpoint(app, "/operator-ui")()
    html = response.body.decode("utf-8")
    html_no_slash = response_no_slash.body.decode("utf-8")
    version = health["loaded_commit"]
    asset_version = f"{version}-ui4-enforce-unblock"

    assert response.headers["Cache-Control"] == "no-store, max-age=0, must-revalidate"
    assert response.headers["Pragma"] == "no-cache"
    assert response.headers["Expires"] == "0"
    assert f"/operator-ui/styles.css?v={asset_version}" in html
    assert f"/operator-ui/mock-data.js?v={asset_version}" in html
    assert f"/operator-ui/app.js?v={asset_version}" in html
    assert f"/operator-ui/styles.css?v={asset_version}" in html_no_slash
    assert f"/operator-ui/mock-data.js?v={asset_version}" in html_no_slash
    assert f"/operator-ui/app.js?v={asset_version}" in html_no_slash
    assert f'window.PK_OPERATOR_UI_BUILD_COMMIT = "{version}"' in html
    assert f'window.PK_OPERATOR_UI_ASSET_VERSION = "{asset_version}"' in html
    assert "operator-ui-build" not in html
    assert "operator-activation-e2e-truth6-20260602" not in html


def test_operator_health_does_not_call_heavy_supervisor_snapshot(tmp_path):
    class FastHealthProvider(OperatorSnapshotProvider):
        def _supervisor_snapshot(self):  # pragma: no cover - should never be called by health
            raise AssertionError("health must stay on the local-only fast path")

    runtime_config = OperatorRuntimeConfig.from_env({}, repo_root=tmp_path)
    app = create_operator_app(provider=FastHealthProvider(runtime_config=runtime_config))

    health = _endpoint(app, "/operator/health")()

    assert health["ok"] is True
    assert health["api_status"] == "OK"
    assert health["supervisor_status"] == "IDLE"
    assert health["elapsed_ms"] < 500


def test_operator_control_lane_endpoints_are_local_only(tmp_path):
    class FastControlProvider(OperatorSnapshotProvider):
        def _supervisor_snapshot(self):  # pragma: no cover - control lane must not call this
            raise AssertionError("control lane must not call heavy supervisor snapshot")

        def portfolio(self):  # pragma: no cover - control lane must not call this
            raise AssertionError("control lane must not call broker/portfolio snapshot")

        def launch_readiness(self):  # pragma: no cover - control lane must not call this
            raise AssertionError("control lane must not call launch readiness fan-out")

    runtime_config = OperatorRuntimeConfig.from_env({}, repo_root=tmp_path)
    app = create_operator_app(provider=FastControlProvider(runtime_config=runtime_config))

    for path in ("/operator/health", "/operator/launcher-status", "/operator/status", "/operator/version", "/operator/runtime-minimal"):
        started = time.perf_counter()
        payload = _endpoint(app, path)()
        elapsed = time.perf_counter() - started
        assert elapsed < 0.5, path
        assert payload.get("secrets_values_exposed") is not True

    launcher_status = _endpoint(app, "/operator/launcher-status")()
    assert launcher_status["control_lane"] is True
    assert launcher_status["paper_only"] is True
    assert launcher_status["live_locked"] is True
    assert launcher_status["real_money_blocked"] is True
    assert launcher_status["operator_ui_connection_count"] == 0
    assert launcher_status["operator_ui_idle_shutdown_enabled"] is False
    assert launcher_status["operator_ui_disconnect_grace_seconds"] == 8.0
    assert launcher_status["broker_call_occurred"] is False
    assert launcher_status["broker_mutation_occurred"] is False


def test_operator_perf_middleware_records_recent_timings(tmp_path):
    provider = OperatorSnapshotProvider(runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path))
    app = create_operator_app(provider=provider)

    in_flight = provider.perf_recorder.begin()
    provider.perf_recorder.finish(
        path="/operator/health",
        method="GET",
        status_code=200,
        elapsed_ms=12.5,
        in_flight_count=in_flight,
    )
    perf = _endpoint(app, "/operator/perf/recent")()

    assert perf["source"] == "OPERATOR_PERF_RECORDER"
    assert perf["event_count"] >= 1
    assert any(row["path"] == "/operator/health" for row in perf["events"])
    assert perf["secrets_values_exposed"] is False


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
        "/operator/launcher-status",
        "/operator/version",
        "/operator/runtime-minimal",
        "/operator/perf/recent",
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
        "/operator/paper-baseline",
        "/operator/research",
        "/operator/research/evidence-graph",
        "/operator/ai/status",
        "/operator/world-awareness",
        "/operator/world-awareness/providers",
        "/operator/world-awareness/events",
        "/operator/world-awareness/runtime",
        "/operator/cockpit/capabilities",
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
    cockpit_equities = _endpoint(app, "/operator/cockpit/asset-mandate", "POST")({"asset_class": "equities"})
    cockpit_day_trader = _endpoint(app, "/operator/cockpit/day-trader-mode", "POST")({"enabled": True})
    ai_ask = _endpoint(app, "/operator/ai/ask", "POST")({"question": "Review provider/data readiness."})
    historical = _endpoint(app, "/operator/historical-tests/run", "POST")({"date_range_preset": "last_4_months"})
    text = str((credential_save, credential_validate, paper_start, cockpit_equities, cockpit_day_trader, ai_ask, historical))

    assert "sk-smoke-secret" not in text
    assert credential_save["broker_call_occurred"] is False
    assert credential_validate["broker_call_occurred"] is False
    assert paper_start["broker_call_occurred"] is False
    assert paper_start["runtime_mutation_occurred"] is False
    assert cockpit_equities["broker_mutation_occurred"] is False
    assert cockpit_equities["strategy_mutation_occurred"] is False
    assert cockpit_day_trader["broker_mutation_occurred"] is False
    assert cockpit_day_trader["strategy_mutation_occurred"] is False
    assert ai_ask["can_execute"] is False
    assert historical["broker_trading_call_occurred"] is False
    assert historical["paper_started"] is False
