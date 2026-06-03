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
    assert payload["paper_endpoint_source"] == "CONFIGURED"
    assert payload["paper_start_allowed"] is True
    assert payload["portfolio_read_availability"] == "BROKER_READ_READY"
    assert payload["can_execute"] is False


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
    assert "paper_endpoint_only" in payload["reason_codes"]
    assert payload["live_enabled"] is False
    assert payload["real_money_enabled"] is False


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
