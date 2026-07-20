from __future__ import annotations

from pathlib import Path

import pytest

from app.api.operator_readonly_api import OperatorSnapshotProvider, create_operator_app
from app.api.operator_runtime_config import OperatorRuntimeConfig
from app.operator_activation.paper_baseline import BASELINE_POLICY_PROTECTED
from app.operator_credentials.store import ALPACA_PAPER_ENV_PATH_ENV_KEY, LocalCredentialStore
from tests.paper_capability_test_support import install_mock_broker_crypto_capability_evidence
from tests.test_operator_paper_supervisor import FakeRunner
from app.api.operator_paper_supervisor import OperatorPaperSupervisor, PaperSupervisorConfig

PAPER_ENDPOINT = "https://paper-api.alpaca.markets"


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
def _offline_account_pin_for_legacy_readiness_tests(monkeypatch):
    monkeypatch.setattr(
        OperatorPaperSupervisor,
        "_paper_account_identity_assertion",
        lambda self, *, force=False: _account_pin_ok_assertion(),
    )


def _endpoint(app, path: str, method: str = "GET"):
    for route in app.routes:
        if route.path == path and method in (route.methods or set()):
            return route.endpoint
    raise AssertionError(f"route not found: {method} {path}")


def _verified_position_snapshot() -> dict[str, object]:
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


class _PaperReadClient:
    def __init__(self, snapshot: dict[str, object]) -> None:
        self.snapshot = snapshot
        self.calls: list[tuple[str, str]] = []

    def get_json(self, path, headers):
        assert headers["APCA-API-KEY-ID"] == "id"
        self.calls.append(("GET", path))
        if path == "/v2/account":
            return dict(self.snapshot["account"])
        if path == "/v2/positions":
            return list(self.snapshot["positions"])
        if path.startswith("/v2/orders?"):
            return []
        raise AssertionError(f"unexpected broker path: {path}")


def _paper_read_confirmations() -> dict[str, object]:
    return {
        "mode": "PAPER",
        "live": False,
        "real_money": False,
        "confirm_paper_read_only": True,
        "confirm_account_positions_orders_get_only": True,
        "confirm_no_broker_mutation": True,
        "confirm_process_scoped_authorization": True,
    }


@pytest.fixture(autouse=True)
def _isolated_canonical_paper_env(monkeypatch, tmp_path) -> Path:
    path = tmp_path / "canonical_alpaca_paper.env"
    monkeypatch.setenv(ALPACA_PAPER_ENV_PATH_ENV_KEY, str(path))
    return path


def _write_canonical_paper_env(
    path: Path,
    *,
    key_id: str | None = "id",
    secret_key: str | None = "secret",
    base_url: str | None = None,
) -> None:
    lines: list[str] = []
    if base_url is not None:
        lines.append(f"APCA_API_BASE_URL={base_url}")
    if key_id is not None:
        lines.append(f"APCA_API_KEY_ID={key_id}")
    if secret_key is not None:
        lines.append(f"APCA_API_SECRET_KEY={secret_key}")
    path.write_text("\n".join(lines), encoding="utf-8")


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
    setup = state["paper_credential_setup"]
    assert setup["overall_status"]["code"] == "MISSING"
    assert setup["overall_status"]["severity"] == "blocked"
    assert setup["required_credentials"] == [
        {
            "name": "APCA_API_KEY_ID",
            "present": False,
            "display_value": "missing",
            "source": "NOT_CONFIGURED",
            "raw_value_exposed": False,
        },
        {
            "name": "APCA_API_SECRET_KEY",
            "present": False,
            "display_value": "missing",
            "source": "NOT_CONFIGURED",
            "raw_value_exposed": False,
        },
    ]
    assert setup["approved_secret_path"]["relative_path"] == "~/.poverty_killer_alpaca_paper_env"
    assert setup["approved_secret_path"]["label"] == "Canonical Alpaca PAPER env file"
    assert setup["approved_secret_path"]["credential_precedence"] == "ALPACA_PAPER_ENV_FILE_ONLY"
    assert "chat" in setup["approved_secret_path"]["forbidden_instruction"]
    assert "commit" in setup["approved_secret_path"]["forbidden_instruction"]
    assert setup["preflight_gate"]["read_only_preflight_authorized"] is False
    assert setup["preflight_gate"]["account_check_status"] == "blocked"
    assert setup["preflight_gate"]["open_orders_check_status"] == "blocked"
    assert setup["preflight_gate"]["positions_check_status"] == "blocked"
    assert setup["preflight_gate"]["alpaca_network_call_occurred"] is False
    assert setup["preflight_gate"]["broker_mutation_occurred"] is False
    assert setup["safety"]["secrets_values_exposed"] is False
    assert state["broker_truth"]["broker_read_occurred"] is False
    assert state["broker_truth"]["broker_mutation_occurred"] is False
    assert state["safety_locks"]["live"]["enabled"] is False
    assert state["safety_locks"]["real_money"]["enabled"] is False
    assert state["advanced"]["secrets_values_exposed"] is False


def test_launch_readiness_names_partial_alpaca_credentials_without_exposing_values(
    tmp_path,
    _isolated_canonical_paper_env,
):
    _write_canonical_paper_env(
        _isolated_canonical_paper_env,
        key_id="placeholder-paper-key",
        secret_key=None,
    )
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    provider = OperatorSnapshotProvider(
        runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
        provider_env={},
        credential_store=store,
    )
    app = create_operator_app(provider=provider)

    payload = _endpoint(app, "/operator/launch-readiness")()
    setup = payload["run_paper_operator_state"]["paper_credential_setup"]
    text = str(payload)

    assert payload["final_launch_readiness"] == "BLOCKED"
    assert payload["run_paper_operator_state"]["can_run_paper"]["reason"] == (
        "Missing required Alpaca PAPER credential field: APCA_API_SECRET_KEY."
    )
    assert setup["overall_status"]["code"] == "PARTIAL"
    assert setup["missing_fields"] == ["APCA_API_SECRET_KEY"]
    assert setup["required_credentials"][0]["name"] == "APCA_API_KEY_ID"
    assert setup["required_credentials"][0]["present"] is True
    assert setup["required_credentials"][1]["name"] == "APCA_API_SECRET_KEY"
    assert setup["required_credentials"][1]["present"] is False
    assert setup["preflight_gate"]["read_only_preflight_authorized"] is False
    assert setup["preflight_gate"]["alpaca_network_call_occurred"] is False
    assert "placeholder-paper-key" not in text
    assert setup["safety"]["secrets_values_exposed"] is False


def test_launch_readiness_blocks_bounded_paper_until_read_only_preflight_is_approved(
    tmp_path,
    _isolated_canonical_paper_env,
):
    _write_canonical_paper_env(_isolated_canonical_paper_env)
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    app = create_operator_app(
        provider=OperatorSnapshotProvider(
            runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
            provider_env={},
            credential_store=store,
        )
    )

    payload = _endpoint(app, "/operator/launch-readiness")()

    assert payload["final_launch_readiness"] == "BLOCKED"
    assert payload["paper_endpoint_only"] is True
    assert payload["paper_endpoint_status"] == "PAPER_ENDPOINT_CONFIRMED"
    assert payload["paper_endpoint_source"] == "SAFE_DEFAULT_PAPER_ENDPOINT"
    assert payload["alpaca_endpoint_configured"] is False
    assert payload["paper_endpoint_display"] == "https://paper-api.alpaca.markets"
    assert payload["paper_start_allowed"] is False
    assert payload["portfolio_read_availability"] == "BROKER_READ_READY"
    assert payload["can_execute"] is False
    state = payload["run_paper_operator_state"]
    assert state["overall_status"]["code"] == "BLOCKED"
    assert state["can_run_paper"]["allowed"] is False
    assert state["can_run_paper"]["reason"] == (
        "Read-only Alpaca PAPER preflight has not run and requires explicit Shan approval before Alpaca is called."
    )
    assert "paper_read_only_preflight_gate" in state["can_run_paper"]["reason_codes"]
    assert state["can_run_paper"]["uses_existing_governed_start_intent"] == "/operator/intent/paper/start"
    assert state["endpoint"]["label"] == "Safe default PAPER endpoint in use: https://paper-api.alpaca.markets"
    assert state["credentials"]["configured"] is True
    setup = state["paper_credential_setup"]
    assert setup["overall_status"]["code"] == "PRESENT_NOT_PREFLIGHTED"
    assert setup["preflight_gate"]["read_only_preflight_available"] is True
    assert setup["preflight_gate"]["read_only_preflight_authorized"] is False
    assert setup["preflight_gate"]["account_check_status"] == "ready_to_run_after_approval"
    assert setup["preflight_gate"]["open_orders_check_status"] == "ready_to_run_after_approval"
    assert setup["preflight_gate"]["positions_check_status"] == "ready_to_run_after_approval"
    assert setup["preflight_gate"]["account_request_occurred"] is False
    assert setup["preflight_gate"]["open_orders_request_occurred"] is False
    assert setup["preflight_gate"]["positions_request_occurred"] is False
    assert setup["preflight_gate"]["alpaca_network_call_occurred"] is False
    assert setup["safety"]["paper_start_allowed"] is False
    assert setup["safety"]["live_enabled"] is False
    assert setup["safety"]["real_money_enabled"] is False
    assert state["broker_truth"]["status"] == "BROKER_READ_READY_NOT_IN_THIS_VIEW"
    assert state["broker_truth"]["broker_confirmed"] is False
    assert state["safety_locks"]["manual_trading"]["available"] is False
    assert state["safety_locks"]["force_trade"]["available"] is False


def test_launch_readiness_refreshes_canonical_env_file_after_backend_start(
    tmp_path,
    _isolated_canonical_paper_env,
):
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    provider = OperatorSnapshotProvider(
        runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
        provider_env={},
        credential_store=store,
    )
    app = create_operator_app(provider=provider)

    before = _endpoint(app, "/operator/launch-readiness")()
    store.save_provider("alpaca_paper", {"APCA_API_KEY_ID": "id", "APCA_API_SECRET_KEY": "secret"})
    after_local_save = _endpoint(app, "/operator/launch-readiness")()
    _write_canonical_paper_env(_isolated_canonical_paper_env)
    after_canonical_file = _endpoint(app, "/operator/launch-readiness")()

    assert before["alpaca_paper_credentials_configured"] is False
    assert after_local_save["alpaca_paper_credentials_configured"] is False
    assert "alpaca_paper_credentials" in after_local_save["reason_codes"]
    assert after_canonical_file["alpaca_paper_credentials_configured"] is True
    assert "alpaca_paper_credentials" not in after_canonical_file["reason_codes"]
    assert "paper_read_only_preflight_gate" in after_canonical_file["reason_codes"]


def test_launch_readiness_uses_same_canonical_alpaca_truth_as_portfolio(
    tmp_path,
    _isolated_canonical_paper_env,
):
    _write_canonical_paper_env(_isolated_canonical_paper_env)
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
    assert "paper_read_only_preflight_gate" in payload["reason_codes"]
    assert payload["portfolio_read_availability"] == "BROKER_READ_READY"


def test_launch_readiness_blocks_live_endpoint_even_with_canonical_credentials(
    tmp_path,
    _isolated_canonical_paper_env,
):
    _write_canonical_paper_env(_isolated_canonical_paper_env, base_url="https://api.alpaca.markets")
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    app = create_operator_app(
        provider=OperatorSnapshotProvider(
            runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
            provider_env={},
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


def test_launch_readiness_accepts_normalized_paper_endpoint_variant(
    tmp_path,
    _isolated_canonical_paper_env,
):
    _write_canonical_paper_env(
        _isolated_canonical_paper_env,
        base_url=" HTTPS://PAPER-API.ALPACA.MARKETS/v2 ",
    )
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    app = create_operator_app(
        provider=OperatorSnapshotProvider(
            runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
            provider_env={},
            credential_store=store,
        )
    )

    payload = _endpoint(app, "/operator/launch-readiness")()

    assert payload["final_launch_readiness"] == "BLOCKED"
    assert payload["paper_endpoint_only"] is True
    assert payload["paper_endpoint_status"] == "PAPER_ENDPOINT_CONFIRMED"
    assert payload["paper_endpoint_display"] == "https://paper-api.alpaca.markets"
    assert payload["paper_endpoint_family"] == "paper"
    assert payload["paper_endpoint_host"] == "paper-api.alpaca.markets"
    assert payload["paper_endpoint_blocker_code"] is None
    assert payload["paper_start_allowed"] is False
    state = payload["run_paper_operator_state"]
    assert state["endpoint"]["display"] == "https://paper-api.alpaca.markets"
    assert state["endpoint"]["family"] == "paper"
    assert state["endpoint"]["valid"] is True
    assert state["can_run_paper"]["allowed"] is False
    assert state["paper_credential_setup"]["preflight_gate"]["read_only_preflight_available"] is True


def test_launch_readiness_rejects_data_endpoint_as_trading_endpoint(
    tmp_path,
    _isolated_canonical_paper_env,
):
    _write_canonical_paper_env(_isolated_canonical_paper_env, base_url="https://data.alpaca.markets")
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
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


def test_governed_paper_start_uses_existing_intent_and_canonical_credentials_without_exposing_them(
    tmp_path,
    _isolated_canonical_paper_env,
):
    _write_canonical_paper_env(_isolated_canonical_paper_env, secret_key="super-secret")
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    runner = FakeRunner()
    runtime = OperatorRuntimeConfig.from_env({}, repo_root=tmp_path)
    supervisor = OperatorPaperSupervisor(
        config=PaperSupervisorConfig(
            repo_root=runner.repo_root,
            operator_state_dir=str(runtime.operator_state_dir),
        ),
        runner=runner,
    )
    install_mock_broker_crypto_capability_evidence(supervisor)
    broker_snapshot = _verified_position_snapshot()
    provider = OperatorSnapshotProvider(
        supervisor=supervisor,
        runtime_config=runtime,
        provider_env={},
        credential_store=store,
        portfolio_client=_PaperReadClient(broker_snapshot),
    )
    supervisor.config.process_env = provider._paper_process_env()
    app = create_operator_app(provider=provider)
    accepted = provider.paper_baseline_accept(
        {
            "preflight_snapshot": broker_snapshot,
            "policy": BASELINE_POLICY_PROTECTED,
            "accepted_by_operator": "offline readiness test",
        }
    )
    verified = _endpoint(app, "/operator/intent/paper/verify-readonly", "POST")(_paper_read_confirmations())

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

    assert accepted["accepted"] is True
    assert verified["allowed"] is True
    assert verified["broker_read_occurred"] is True
    assert verified["broker_mutation_occurred"] is False
    assert result["allowed"] is True
    assert result["reason_code"] == "PAPER_RUN_STARTED"
    assert result["broker_call_occurred"] is True
    assert result["broker_read_occurred"] is True
    assert result["broker_mutation_occurred"] is False
    assert result["session"]["duration_seconds"] == 900
    assert "super-secret" not in str(result)
    assert "super-secret" not in " ".join(runner.started_specs[0].command)
    assert runner.started_specs[0].env["APCA_API_SECRET_KEY"] == "super-secret"
    assert runner.started_specs[0].env["APCA_API_BASE_URL"] == PAPER_ENDPOINT
