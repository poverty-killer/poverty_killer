from __future__ import annotations

from app.api.operator_readonly_api import OperatorSnapshotProvider, create_operator_app
from app.api.operator_runtime_config import OperatorRuntimeConfig
from app.operator_credentials.store import LocalCredentialStore
from tests.test_operator_paper_supervisor import FakeRunner
from app.api.operator_paper_supervisor import OperatorPaperSupervisor, PaperSupervisorConfig


def _endpoint(app, path: str, method: str = "GET"):
    for route in app.routes:
        if route.path == path and method in (route.methods or set()):
            return route.endpoint
    raise AssertionError(f"route not found: {method} {path}")


def test_launch_readiness_blocks_when_alpaca_credentials_missing(tmp_path):
    app = create_operator_app(
        provider=OperatorSnapshotProvider(
            runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
            provider_env={},
            credential_store=LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json"),
        )
    )

    payload = _endpoint(app, "/operator/launch-readiness")()

    assert payload["final_launch_readiness"] == "BLOCKED"
    assert payload["alpaca_paper_credentials_configured"] is False
    assert "alpaca_paper_credentials" in payload["reason_codes"]
    assert payload["live_blocked"] is True
    assert payload["real_money_blocked"] is True
    state = payload["run_paper_operator_state"]
    assert state["overall_status"]["code"] == "BLOCKED"
    assert state["can_run_paper"]["allowed"] is False
    assert state["can_run_paper"]["reason"] == "Alpaca PAPER key ID and secret are missing."
    assert state["endpoint"]["display"] == "https://paper-api.alpaca.markets"
    assert state["endpoint"]["source"] == "SAFE_DEFAULT_PAPER_ENDPOINT"
    assert state["credentials"]["configured"] is False
    assert state["credentials"]["missing_fields"] == ["APCA_API_KEY_ID", "APCA_API_SECRET_KEY"]
    assert state["broker_truth"]["broker_read_occurred"] is False
    assert state["broker_truth"]["broker_mutation_occurred"] is False
    assert state["safety_locks"]["live"]["enabled"] is False
    assert state["safety_locks"]["real_money"]["enabled"] is False
    assert state["advanced"]["secrets_values_exposed"] is False


def test_launch_readiness_allows_bounded_paper_when_required_checks_pass(tmp_path):
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    store.save_provider("alpaca_paper", {"APCA_API_KEY_ID": "id", "APCA_API_SECRET_KEY": "secret"})
    app = create_operator_app(
        provider=OperatorSnapshotProvider(
            runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
            provider_env={},
            credential_store=store,
        )
    )

    payload = _endpoint(app, "/operator/launch-readiness")()

    assert payload["final_launch_readiness"] == "READY_FOR_BOUNDED_PAPER"
    assert payload["paper_endpoint_only"] is True
    assert payload["paper_endpoint_status"] == "PAPER_ENDPOINT_CONFIRMED"
    assert payload["paper_endpoint_source"] == "SAFE_DEFAULT_PAPER_ENDPOINT"
    assert payload["alpaca_endpoint_configured"] is False
    assert payload["paper_endpoint_display"] == "https://paper-api.alpaca.markets"
    assert payload["paper_start_allowed"] is True
    assert payload["portfolio_read_availability"] == "BROKER_READ_READY"
    assert payload["can_execute"] is False
    state = payload["run_paper_operator_state"]
    assert state["overall_status"]["code"] == "READY"
    assert state["can_run_paper"]["allowed"] is True
    assert state["can_run_paper"]["uses_existing_governed_start_intent"] == "/operator/intent/paper/start"
    assert state["endpoint"]["label"] == "Safe default PAPER endpoint in use: https://paper-api.alpaca.markets"
    assert state["credentials"]["configured"] is True
    assert state["broker_truth"]["status"] == "BROKER_READ_READY_NOT_IN_THIS_VIEW"
    assert state["broker_truth"]["broker_confirmed"] is False
    assert state["safety_locks"]["manual_trading"]["available"] is False
    assert state["safety_locks"]["force_trade"]["available"] is False


def test_launch_readiness_refreshes_local_vault_saved_after_backend_start(tmp_path):
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    provider = OperatorSnapshotProvider(
        runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
        provider_env={},
        credential_store=store,
    )
    app = create_operator_app(provider=provider)

    before = _endpoint(app, "/operator/launch-readiness")()
    store.save_provider("alpaca_paper", {"APCA_API_KEY_ID": "id", "APCA_API_SECRET_KEY": "secret"})
    after = _endpoint(app, "/operator/launch-readiness")()

    assert before["alpaca_paper_credentials_configured"] is False
    assert after["alpaca_paper_credentials_configured"] is True
    assert "alpaca_paper_credentials" not in after["reason_codes"]


def test_launch_readiness_uses_same_shared_alpaca_truth_as_portfolio(tmp_path):
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    store.save_provider("alpaca_news", {"APCA_API_KEY_ID": "id", "APCA_API_SECRET_KEY": "secret"})
    app = create_operator_app(
        provider=OperatorSnapshotProvider(
            runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
            provider_env={},
            credential_store=store,
        )
    )

    payload = _endpoint(app, "/operator/launch-readiness")()

    assert payload["alpaca_paper_credentials_configured"] is True
    assert "alpaca_paper_credentials" not in payload["reason_codes"]
    assert payload["portfolio_read_availability"] == "BROKER_READ_READY"


def test_launch_readiness_blocks_live_endpoint_even_with_local_credentials(tmp_path):
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    store.save_provider("alpaca_paper", {"APCA_API_KEY_ID": "id", "APCA_API_SECRET_KEY": "secret"})
    app = create_operator_app(
        provider=OperatorSnapshotProvider(
            runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
            provider_env={"APCA_API_BASE_URL": "https://api.alpaca.markets"},
            credential_store=store,
        )
    )

    payload = _endpoint(app, "/operator/launch-readiness")()

    assert payload["final_launch_readiness"] == "BLOCKED"
    assert payload["alpaca_paper_credentials_configured"] is True
    assert payload["paper_endpoint_only"] is False
    assert payload["paper_endpoint_status"] == "LIVE_ENDPOINT_BLOCKED"
    assert payload["paper_endpoint_family"] == "live"
    assert payload["paper_endpoint_blocker_code"] == "LIVE_ENDPOINT_BLOCKED"
    assert "paper_endpoint_only" in payload["reason_codes"]
    assert payload["live_enabled"] is False
    assert payload["real_money_enabled"] is False
    state = payload["run_paper_operator_state"]
    assert state["overall_status"]["code"] == "BLOCKED"
    assert state["endpoint"]["family"] == "live"
    assert state["endpoint"]["blocker_code"] == "LIVE_ENDPOINT_BLOCKED"
    assert state["can_run_paper"]["allowed"] is False
    assert "Live Alpaca endpoint is blocked" in state["can_run_paper"]["reason"]
    assert state["broker_truth"]["broker_read_occurred"] is False
    assert state["advanced"]["live_enabled"] is False


def test_launch_readiness_accepts_normalized_paper_endpoint_variant(tmp_path):
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    store.save_provider(
        "alpaca_paper",
        {
            "APCA_API_KEY_ID": "id",
            "APCA_API_SECRET_KEY": "secret",
            "APCA_API_BASE_URL": " HTTPS://PAPER-API.ALPACA.MARKETS/v2 ",
        },
    )
    app = create_operator_app(
        provider=OperatorSnapshotProvider(
            runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
            provider_env={},
            credential_store=store,
        )
    )

    payload = _endpoint(app, "/operator/launch-readiness")()

    assert payload["final_launch_readiness"] == "READY_FOR_BOUNDED_PAPER"
    assert payload["paper_endpoint_only"] is True
    assert payload["paper_endpoint_status"] == "PAPER_ENDPOINT_CONFIRMED"
    assert payload["paper_endpoint_display"] == "https://paper-api.alpaca.markets"
    assert payload["paper_endpoint_family"] == "paper"
    assert payload["paper_endpoint_host"] == "paper-api.alpaca.markets"
    assert payload["paper_endpoint_blocker_code"] is None
    assert payload["paper_start_allowed"] is True
    state = payload["run_paper_operator_state"]
    assert state["endpoint"]["display"] == "https://paper-api.alpaca.markets"
    assert state["endpoint"]["family"] == "paper"
    assert state["endpoint"]["valid"] is True
    assert state["can_run_paper"]["allowed"] is True


def test_launch_readiness_rejects_data_endpoint_as_trading_endpoint(tmp_path):
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    store.save_provider(
        "alpaca_paper",
        {
            "APCA_API_KEY_ID": "id",
            "APCA_API_SECRET_KEY": "secret",
            "APCA_API_BASE_URL": "https://data.alpaca.markets",
        },
    )
    app = create_operator_app(
        provider=OperatorSnapshotProvider(
            runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
            provider_env={},
            credential_store=store,
        )
    )

    payload = _endpoint(app, "/operator/launch-readiness")()
    paper_endpoint_check = next(check for check in payload["checks"] if check["check_id"] == "paper_endpoint_only")

    assert payload["final_launch_readiness"] == "BLOCKED"
    assert payload["paper_endpoint_only"] is False
    assert payload["paper_endpoint_status"] == "ALPACA_DATA_ENDPOINT_NOT_TRADING"
    assert payload["paper_endpoint_family"] == "data"
    assert payload["paper_start_allowed"] is False
    assert "data.alpaca.markets is a market data endpoint" in paper_endpoint_check["detail"]
    assert payload["broker_mutation_occurred"] is False
    state = payload["run_paper_operator_state"]
    assert state["endpoint"]["family"] == "data"
    assert state["endpoint"]["blocker_code"] == "ALPACA_DATA_ENDPOINT_NOT_TRADING"
    assert state["can_run_paper"]["allowed"] is False
    assert state["broker_truth"]["broker_read_occurred"] is False


def test_governed_paper_start_uses_existing_intent_and_local_credentials_without_exposing_them(tmp_path):
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    store.save_provider("alpaca_paper", {"APCA_API_KEY_ID": "id", "APCA_API_SECRET_KEY": "super-secret"})
    runner = FakeRunner()
    supervisor = OperatorPaperSupervisor(config=PaperSupervisorConfig(repo_root=runner.repo_root), runner=runner)
    provider = OperatorSnapshotProvider(
        supervisor=supervisor,
        runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
        provider_env={},
        credential_store=store,
    )
    supervisor.config.process_env = provider._paper_process_env()
    app = create_operator_app(provider=provider)

    result = _endpoint(app, "/operator/intent/paper/start", "POST")(
        {
            "mode": "PAPER",
            "profile": "PAPER_EXPLORATION_ALPHA",
            "duration_seconds": 900,
            "watchlist": ["BTC/USD", "ETH/USD", "SOL/USD"],
            "approve_autonomous_paper": True,
            "real_money": False,
            "live": False,
        }
    )

    assert result["allowed"] is True
    assert result["reason_code"] == "PAPER_RUN_STARTED"
    assert result["broker_call_occurred"] is False
    assert result["session"]["duration_seconds"] == 900
    assert "super-secret" not in str(result)
    assert "super-secret" not in " ".join(runner.started_specs[0].command)
    assert runner.started_specs[0].env["APCA_API_SECRET_KEY"] == "super-secret"
