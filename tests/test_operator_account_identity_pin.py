from __future__ import annotations

from pathlib import Path

from app.api.operator_paper_supervisor import OperatorPaperSupervisor, PaperSupervisorConfig
from app.api.operator_readonly_api import OperatorSnapshotProvider, create_operator_app
from app.api.operator_runtime_config import OperatorRuntimeConfig
from app.operator_activation.account_identity import (
    ACCOUNT_PIN_MISMATCH,
    ACCOUNT_PIN_OK,
    build_alpaca_paper_account_identity_assertion,
)
from app.operator_activation.paper_baseline import BASELINE_POLICY_PROTECTED
from app.operator_credentials.store import (
    ALPACA_PAPER_ACCOUNT_PIN_ENV_KEY,
    ALPACA_PAPER_ENV_PATH_ENV_KEY,
    ALPACA_PAPER_EXPECTED_ACCOUNT_SUFFIX,
    LocalCredentialStore,
)
from tests.test_operator_paper_supervisor import FakeRunner


PAPER_ENDPOINT = "https://paper-api.alpaca.markets"
BROKER_READ_AUTH = {"PK_BOARD_AUTHORIZED_PAPER_BROKER_READ": "YES_D4_BOARD_AUTHORIZED"}


class FakeAccountClient:
    def __init__(self, account_suffix: str) -> None:
        self.account_suffix = account_suffix
        self.calls: list[tuple[str, str]] = []

    def get_json(self, path, headers):
        self.calls.append(("GET", path))
        assert path == "/v2/account"
        assert headers["APCA-API-KEY-ID"]
        assert headers["APCA-API-SECRET-KEY"]
        return {
            "id": f"paper-account-{self.account_suffix}",
            "status": "ACTIVE",
            "currency": "USD",
            "cash": "990112.68",
            "buying_power": "3960450.72",
            "portfolio_value": "1000325.77",
            "trading_blocked": False,
            "account_blocked": False,
        }


class FakePortfolioClient:
    def __init__(self, account_suffix: str) -> None:
        self.account_suffix = account_suffix
        self.calls: list[tuple[str, str]] = []

    def get_json(self, path, headers):
        self.calls.append(("GET", path))
        assert headers["APCA-API-KEY-ID"]
        assert headers["APCA-API-SECRET-KEY"]
        if path == "/v2/account":
            return {
                "id": f"paper-account-{self.account_suffix}",
                "status": "ACTIVE",
                "currency": "USD",
                "cash": "990112.68",
                "buying_power": "3960450.72",
                "portfolio_value": "1000325.77",
                "trading_blocked": False,
                "account_blocked": False,
            }
        if path == "/v2/positions":
            return [
                {
                    "symbol": "AVAXUSD",
                    "asset_class": "crypto",
                    "qty": "10",
                    "side": "long",
                    "avg_entry_price": "20",
                    "current_price": "21",
                    "cost_basis": "200",
                    "market_value": "210",
                    "unrealized_pl": "10",
                    "unrealized_plpc": "0.05",
                }
            ]
        if path.startswith("/v2/orders?"):
            return []
        raise AssertionError(f"unexpected broker path: {path}")


def _endpoint(app, path: str, method: str = "GET"):
    for route in app.routes:
        if route.path == path and method in (route.methods or set()):
            return route.endpoint
    raise AssertionError(f"route not found: {method} {path}")


def _paper_env(*, suffix: str = ALPACA_PAPER_EXPECTED_ACCOUNT_SUFFIX) -> dict[str, str]:
    del suffix
    return {
        **BROKER_READ_AUTH,
        "APCA_API_KEY_ID": "canonical-paper-key",
        "APCA_API_SECRET_KEY": "canonical-paper-secret",
        "APCA_API_BASE_URL": PAPER_ENDPOINT,
    }


def _valid_start_request() -> dict:
    return {
        "mode": "PAPER",
        "profile": "PAPER_EXPLORATION_ALPHA",
        "duration_seconds": 300,
        "watchlist": ["BTC/USD", "ETH/USD", "SOL/USD"],
        "approve_autonomous_paper": True,
    }


def _read_only_confirmations() -> dict[str, object]:
    return {
        "mode": "PAPER",
        "live": False,
        "real_money": False,
        "confirm_paper_read_only": True,
        "confirm_account_positions_orders_get_only": True,
        "confirm_no_broker_mutation": True,
        "confirm_process_scoped_authorization": True,
    }


def _protected_baseline_snapshot() -> dict[str, object]:
    return {
        "endpoint_family": "paper",
        "account": {
            "id": "paper-account-045ded",
            "status": "ACTIVE",
            "portfolio_value": "1000325.77",
            "cash": "990112.68",
            "buying_power": "3960450.72",
            "trading_blocked": False,
            "account_blocked": False,
        },
        "positions": [
            {
                "symbol": "AVAXUSD",
                "asset_class": "crypto",
                "qty": "10",
                "side": "long",
                "avg_entry_price": "20",
                "current_price": "21",
                "cost_basis": "200",
                "market_value": "210",
                "unrealized_pl": "10",
                "unrealized_plpc": "0.05",
            }
        ],
        "position_count": 1,
        "open_orders": [],
        "open_order_count": 0,
    }


def _provider_with_accepted_baseline(tmp_path, *, account_suffix: str):
    runtime = OperatorRuntimeConfig.from_env(
        {"PK_OPERATOR_STATE_DIR": str(tmp_path / "durable_operator_state")},
        repo_root=tmp_path,
    )
    runner = FakeRunner()
    checker = lambda env: build_alpaca_paper_account_identity_assertion(
        env,
        client=FakeAccountClient(account_suffix),
    )
    supervisor = OperatorPaperSupervisor(
        config=PaperSupervisorConfig(
            repo_root=runner.repo_root,
            process_env=_paper_env(),
            operator_state_dir=str(runtime.operator_state_dir),
            session_store_path=str(runtime.operator_session_store_path),
        ),
        runner=runner,
        account_identity_checker=checker,
    )
    provider = OperatorSnapshotProvider(
        supervisor=supervisor,
        runtime_config=runtime,
        provider_env=_paper_env(),
        credential_store=LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json"),
        portfolio_client=FakePortfolioClient(account_suffix),
        account_identity_checker=checker,
    )
    accepted = provider.paper_baseline_accept(
        {
            "preflight_snapshot": _protected_baseline_snapshot(),
            "policy": BASELINE_POLICY_PROTECTED,
            "accepted_by_operator": "account pin test operator",
        }
    )
    assert accepted["accepted"] is True
    return provider, supervisor, runner


def _write_canonical_paper_env(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                f"APCA_API_BASE_URL={PAPER_ENDPOINT}",
                "APCA_API_KEY_ID=canonical-paper-key",
                "APCA_API_SECRET_KEY=canonical-paper-secret",
            ]
        ),
        encoding="utf-8",
    )


def test_account_identity_assertion_passes_only_for_funded_045ded() -> None:
    client = FakeAccountClient("045ded")

    assertion = build_alpaca_paper_account_identity_assertion(_paper_env(), client=client)

    assert assertion["status"] == "PASS"
    assert assertion["reason_code"] == ACCOUNT_PIN_OK
    assert assertion["expected_suffix"] == "045ded"
    assert assertion["actual_suffix"] == "045ded"
    assert assertion["paper_account_pinned"] is True
    assert assertion["broker_read_occurred"] is True
    assert assertion["broker_mutation_occurred"] is False
    assert client.calls == [("GET", "/v2/account")]


def test_demoted_or_drained_account_104e2a_is_rejected_by_pin(monkeypatch, tmp_path) -> None:
    env_path = tmp_path / "canonical_alpaca_paper.env"
    _write_canonical_paper_env(env_path)
    monkeypatch.setenv(ALPACA_PAPER_ENV_PATH_ENV_KEY, str(env_path))
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    store.save_provider(
        "alpaca_paper",
        {
            "APCA_API_BASE_URL": PAPER_ENDPOINT,
            "APCA_API_KEY_ID": "demoted-104e2a-key",
            "APCA_API_SECRET_KEY": "demoted-104e2a-secret",
        },
    )

    effective = store.effective_provider_values("alpaca_paper", {})
    assertion = build_alpaca_paper_account_identity_assertion(
        {**_paper_env(), **effective},
        client=FakeAccountClient("104e2a"),
    )

    assert effective["APCA_API_KEY_ID"] == "canonical-paper-key"
    assert assertion["status"] == "BLOCKED"
    assert assertion["reason_code"] == ACCOUNT_PIN_MISMATCH
    assert assertion["expected_suffix"] == "045ded"
    assert assertion["actual_suffix"] == "104e2a"
    assert assertion["detail"] == "Expected Alpaca PAPER account suffix 045ded, got 104e2a."
    assert assertion["broker_mutation_occurred"] is False


def test_supervisor_rejects_account_pin_mismatch_after_governed_verification_before_runner_launch(tmp_path) -> None:
    provider, supervisor, runner = _provider_with_accepted_baseline(tmp_path, account_suffix="104e2a")

    verification = provider.paper_broker_preflight_intent(_read_only_confirmations())
    snapshot = supervisor.status_snapshot()
    result = supervisor.start_paper(_valid_start_request())

    assert verification["allowed"] is False
    assert verification["reason_code"] == ACCOUNT_PIN_MISMATCH
    assert snapshot["paper_start_allowed"] is False
    assert snapshot["paper_account_pin_refusal_reason"] == ACCOUNT_PIN_MISMATCH
    assert result["allowed"] is False
    assert result["reason_code"] == ACCOUNT_PIN_MISMATCH
    assert result["paper_account_identity_assertion"]["actual_suffix"] == "104e2a"
    assert runner.started_specs == []


def test_supervisor_passes_verified_pinned_account_to_child_env_when_identity_matches(tmp_path) -> None:
    provider, supervisor, runner = _provider_with_accepted_baseline(tmp_path, account_suffix="045ded")

    verification = provider.paper_broker_preflight_intent(_read_only_confirmations())
    result = supervisor.start_paper(_valid_start_request())

    assert verification["allowed"] is True
    assert result["allowed"] is True
    assert result["paper_account_pinned"] is True
    assert runner.started_specs[0].env[ALPACA_PAPER_ACCOUNT_PIN_ENV_KEY] == "045ded"


def test_launch_readiness_surfaces_exact_account_pin_blocker(monkeypatch, tmp_path) -> None:
    env_path = tmp_path / "canonical_alpaca_paper.env"
    _write_canonical_paper_env(env_path)
    monkeypatch.setenv(ALPACA_PAPER_ENV_PATH_ENV_KEY, str(env_path))
    provider, _supervisor, _runner = _provider_with_accepted_baseline(tmp_path, account_suffix="104e2a")
    app = create_operator_app(provider=provider)

    verification = _endpoint(app, "/operator/intent/paper/verify-readonly", "POST")(_read_only_confirmations())
    payload = _endpoint(app, "/operator/launch-readiness")()

    assert verification["allowed"] is False
    assert verification["reason_code"] == ACCOUNT_PIN_MISMATCH
    assert payload["final_launch_readiness"] == "BLOCKED"
    assert payload["paper_account_pinned"] is False
    assert payload["paper_account_expected_suffix"] == "045ded"
    assert payload["paper_account_actual_suffix"] == "104e2a"
    assert "alpaca_paper_account_pin" in payload["reason_codes"]
    assert payload["run_paper_operator_state"]["can_run_paper"]["reason"] == (
        "Expected Alpaca PAPER account suffix 045ded, got 104e2a."
    )
