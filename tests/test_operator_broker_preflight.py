from __future__ import annotations

import pytest

from app.api.operator_paper_supervisor import OperatorPaperSupervisor, PaperSupervisorConfig
from app.api.operator_readonly_api import OperatorSnapshotProvider, create_operator_app
from app.api.operator_runtime_config import OperatorRuntimeConfig
from app.operator_activation.paper_baseline import BASELINE_POLICY_PROTECTED
from app.operator_credentials.store import ALPACA_PAPER_ENV_PATH_ENV_KEY, LocalCredentialStore
from tests.paper_capability_test_support import install_mock_broker_crypto_capability_evidence
from tests.test_operator_paper_supervisor import FakeRunner


PAPER_ENV = {
    "APCA_API_KEY_ID": "test-paper-key",
    "APCA_API_SECRET_KEY": "test-paper-secret",
    "APCA_API_BASE_URL": "https://paper-api.alpaca.markets",
}


@pytest.fixture(autouse=True)
def _isolated_canonical_paper_env(monkeypatch, tmp_path):
    path = tmp_path / "canonical_alpaca_paper.env"
    path.write_text(
        "\n".join(
            [
                "APCA_API_KEY_ID=test-paper-key",
                "APCA_API_SECRET_KEY=test-paper-secret",
                "APCA_API_BASE_URL=https://paper-api.alpaca.markets",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(ALPACA_PAPER_ENV_PATH_ENV_KEY, str(path))
    return path


def _account_pin(actual_suffix: str = "045ded"):
    def check(_env=None):
        passed = actual_suffix == "045ded"
        return {
            "source": "TEST_ACCOUNT_PIN",
            "status": "PASS" if passed else "BLOCKED",
            "reason_code": "ALPACA_PAPER_ACCOUNT_PIN_OK" if passed else "ALPACA_PAPER_ACCOUNT_PIN_MISMATCH",
            "detail": "offline broker identity proof",
            "expected_suffix": "045ded",
            "actual_suffix": actual_suffix,
            "paper_account_pinned": passed,
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

    return check


def _positions(qty: str = "10") -> list[dict[str, object]]:
    return [
        {
            "symbol": "AVAXUSD",
            "asset_class": "crypto",
            "qty": qty,
            "side": "long",
            "avg_entry_price": "20",
            "current_price": "21",
            "cost_basis": "200",
            "market_value": "210",
            "unrealized_pl": "10",
            "unrealized_plpc": "0.05",
        }
    ]


def _baseline_snapshot(qty: str = "10") -> dict[str, object]:
    return {
        "endpoint_family": "paper",
        "account": {
            "id": "paper-account-045ded",
            "status": "ACTIVE",
            "equity": "10000",
            "buying_power": "15000",
            "trading_blocked": False,
            "account_blocked": False,
        },
        "positions": _positions(qty),
        "position_count": 1,
        "open_orders": [],
        "open_order_count": 0,
    }


class FakePaperReadClient:
    def __init__(
        self,
        *,
        account_suffix: str = "045ded",
        positions: list[dict[str, object]] | None = None,
        open_orders: list[dict[str, object]] | None = None,
    ) -> None:
        self.account_suffix = account_suffix
        self.positions = list(_positions() if positions is None else positions)
        self.open_orders = list(open_orders or [])
        self.calls: list[tuple[str, str]] = []

    def get_json(self, path, headers):
        assert headers["APCA-API-KEY-ID"] == "test-paper-key"
        self.calls.append(("GET", path))
        if path == "/v2/account":
            return {
                "id": f"paper-account-{self.account_suffix}",
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
            }
        if path == "/v2/positions":
            return list(self.positions)
        if path.startswith("/v2/orders?"):
            return list(self.open_orders)
        raise AssertionError(f"unexpected broker path: {path}")


def _endpoint(app, path: str, method: str = "GET"):
    for route in app.routes:
        if route.path == path and method in (route.methods or set()):
            return route.endpoint
    raise AssertionError(f"route not found: {method} {path}")


def _provider(tmp_path, client: FakePaperReadClient, *, account_suffix: str = "045ded"):
    runtime = OperatorRuntimeConfig.from_env(
        {"PK_OPERATOR_STATE_DIR": str(tmp_path / "durable_operator_state")},
        repo_root=tmp_path,
    )
    runner = FakeRunner()
    supervisor = OperatorPaperSupervisor(
        config=PaperSupervisorConfig(
            repo_root=runner.repo_root,
            process_env=dict(PAPER_ENV),
            operator_state_dir=str(runtime.operator_state_dir),
            session_store_path=str(runtime.operator_session_store_path),
        ),
        runner=runner,
        account_identity_checker=_account_pin(account_suffix),
    )
    install_mock_broker_crypto_capability_evidence(supervisor)
    provider = OperatorSnapshotProvider(
        supervisor=supervisor,
        runtime_config=runtime,
        provider_env=dict(PAPER_ENV),
        credential_store=LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json"),
        portfolio_client=client,
        account_identity_checker=_account_pin(account_suffix),
    )
    provider.paper_baseline_accept(
        {
            "preflight_snapshot": _baseline_snapshot(),
            "policy": BASELINE_POLICY_PROTECTED,
            "accepted_by_operator": "offline test operator",
        }
    )
    return provider, runner


def _confirmations() -> dict[str, object]:
    return {
        "mode": "PAPER",
        "live": False,
        "real_money": False,
        "confirm_paper_read_only": True,
        "confirm_account_positions_orders_get_only": True,
        "confirm_no_broker_mutation": True,
        "confirm_process_scoped_authorization": True,
    }


def _start_request(*, duration_seconds: int = 300) -> dict[str, object]:
    return {
        "mode": "PAPER",
        "profile": "PAPER_EXPLORATION_ALPHA",
        "duration_seconds": duration_seconds,
        "watchlist": ["BTC/USD", "ETH/USD", "SOL/USD"],
        "approve_autonomous_paper": True,
        "live": False,
        "real_money": False,
    }


def test_get_only_verification_requires_all_confirmations_and_makes_no_call_when_refused(tmp_path):
    client = FakePaperReadClient()
    provider, _runner = _provider(tmp_path, client)
    app = create_operator_app(provider=provider)

    result = _endpoint(app, "/operator/intent/paper/verify-readonly", "POST")({"mode": "PAPER"})

    assert result["allowed"] is False
    assert result["reason_code"] == "MISSING_PAPER_READ_ONLY_CONFIRMATION"
    assert client.calls == []
    assert result["broker_call_occurred"] is False
    assert result["broker_mutation_occurred"] is False


def test_get_only_verification_proves_account_positions_orders_and_resets_on_restart(tmp_path):
    client = FakePaperReadClient()
    provider, _runner = _provider(tmp_path, client)
    app = create_operator_app(provider=provider)

    result = _endpoint(app, "/operator/intent/paper/verify-readonly", "POST")(_confirmations())

    assert result["allowed"] is True
    assert result["status"] == "VERIFIED"
    assert [path for _method, path in client.calls] == [
        "/v2/account",
        "/v2/positions",
        "/v2/orders?status=open&limit=100&nested=false",
    ]
    assert result["preflight"]["status"] == "PASS"
    assert result["preflight"]["position_symbols"] == ["AVAXUSD"]
    assert result["preflight"]["open_order_count"] == 0
    assert result["authorization"]["scope"] == "CURRENT_OPERATOR_PROCESS_ONLY"
    assert result["authorization"]["persists_across_backend_restart"] is False
    assert result["broker_mutation_occurred"] is False
    restarted = OperatorPaperSupervisor(
        config=PaperSupervisorConfig(repo_root=tmp_path, process_env=dict(PAPER_ENV)),
        account_identity_checker=_account_pin(),
    )
    assert restarted.paper_broker_read_is_authorized() is False
    assert restarted.paper_broker_preflight_status()["status"] == "NOT_RUN"


def test_verification_refuses_pin_mismatch_open_orders_and_baseline_drift(tmp_path):
    scenarios = [
        ("pin", FakePaperReadClient(account_suffix="999999"), "ALPACA_PAPER_ACCOUNT_PIN_MISMATCH", "999999"),
        (
            "orders",
            FakePaperReadClient(open_orders=[{"id": "order-1", "symbol": "AVAXUSD", "side": "buy", "qty": "1", "status": "new"}]),
            "PREFLIGHT_BLOCKED_OPEN_ORDERS",
            "045ded",
        ),
        ("drift", FakePaperReadClient(positions=_positions("9")), "PAPER_BASELINE_DRIFT_REQUIRES_REFRESH", "045ded"),
    ]
    for name, client, expected_reason, identity_suffix in scenarios:
        case_dir = tmp_path / name
        provider, _runner = _provider(case_dir, client, account_suffix=identity_suffix)
        result = provider.paper_broker_preflight_intent(_confirmations())

        assert result["allowed"] is False
        assert result["reason_code"] == expected_reason
        assert result["broker_mutation_occurred"] is False
        assert result["order_submission_occurred"] is False
        assert result["cancel_occurred"] is False
        assert result["liquidation_occurred"] is False


def test_start_revalidates_fresh_broker_truth_before_launching_fake_runner(tmp_path):
    client = FakePaperReadClient()
    provider, runner = _provider(tmp_path, client)

    verified = provider.paper_broker_preflight_intent(_confirmations())
    client.calls.clear()
    started = provider.paper_start_intent(_start_request())

    assert verified["allowed"] is True
    assert started["allowed"] is True
    assert started["reason_code"] == "PAPER_RUN_STARTED"
    assert [path for _method, path in client.calls] == [
        "/v2/account",
        "/v2/positions",
        "/v2/orders?status=open&limit=100&nested=false",
    ]
    assert started["paper_broker_preflight"]["preflight"]["status"] == "PASS"
    assert runner.started_specs
    assert started["broker_mutation_occurred"] is False
    assert started["order_submission_occurred"] is False
    assert started["cancel_occurred"] is False
    assert started["liquidation_occurred"] is False


def test_four_hour_start_reaches_existing_fake_runner_after_fresh_preflight(tmp_path):
    client = FakePaperReadClient()
    provider, runner = _provider(tmp_path, client)

    verified = provider.paper_broker_preflight_intent(_confirmations())
    started = provider.paper_start_intent(_start_request(duration_seconds=14400))

    assert verified["allowed"] is True
    assert started["allowed"] is True
    assert started["reason_code"] == "PAPER_RUN_STARTED"
    assert started["session"]["duration_seconds"] == 14400
    assert "14400" in runner.started_specs[0].command
    assert started["broker_mutation_occurred"] is False
    assert started["order_submission_occurred"] is False


def test_unrelated_ai_credential_change_preserves_paper_proof_but_paper_credential_change_revokes_it(
    tmp_path,
    _isolated_canonical_paper_env,
):
    provider, _runner = _provider(tmp_path, FakePaperReadClient())
    verified = provider.paper_broker_preflight_intent(_confirmations())
    assert verified["allowed"] is True

    provider.credential_store.save_provider(
        "deepseek",
        {
            "DEEPSEEK_API_KEY": "offline-deepseek-test-key",
            "DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1",
        },
    )
    provider._refresh_provider_env()

    assert provider.supervisor.paper_broker_read_is_authorized() is True
    assert provider.supervisor.paper_broker_preflight_status()["status"] == "PASS"

    _isolated_canonical_paper_env.write_text(
        "\n".join(
            [
                "APCA_API_KEY_ID=changed-paper-key",
                "APCA_API_SECRET_KEY=test-paper-secret",
                "APCA_API_BASE_URL=https://paper-api.alpaca.markets",
            ]
        ),
        encoding="utf-8",
    )
    provider._refresh_provider_env()

    assert provider.supervisor.paper_broker_read_is_authorized() is False
    assert provider.supervisor.paper_broker_preflight_status()["status"] == "NOT_RUN"
    assert provider.supervisor.paper_broker_preflight_status()["reason_code"] == (
        "PAPER_BROKER_PREFLIGHT_INVALIDATED_CREDENTIAL_CHANGE"
    )
