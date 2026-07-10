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


def test_supervisor_rejects_account_pin_mismatch_before_runner_launch() -> None:
    runner = FakeRunner()
    checker = lambda env: build_alpaca_paper_account_identity_assertion(env, client=FakeAccountClient("104e2a"))
    supervisor = OperatorPaperSupervisor(
        config=PaperSupervisorConfig(repo_root=runner.repo_root, process_env=_paper_env()),
        runner=runner,
        account_identity_checker=checker,
    )

    snapshot = supervisor.status_snapshot()
    result = supervisor.start_paper(_valid_start_request())

    assert snapshot["paper_start_allowed"] is False
    assert snapshot["paper_account_pin_refusal_reason"] == ACCOUNT_PIN_MISMATCH
    assert result["allowed"] is False
    assert result["reason_code"] == ACCOUNT_PIN_MISMATCH
    assert result["paper_account_identity_assertion"]["actual_suffix"] == "104e2a"
    assert runner.started_specs == []


def test_supervisor_passes_pinned_account_to_child_env_when_identity_matches() -> None:
    runner = FakeRunner()
    checker = lambda env: build_alpaca_paper_account_identity_assertion(env, client=FakeAccountClient("045ded"))
    supervisor = OperatorPaperSupervisor(
        config=PaperSupervisorConfig(repo_root=runner.repo_root, process_env=_paper_env()),
        runner=runner,
        account_identity_checker=checker,
    )

    result = supervisor.start_paper(_valid_start_request())

    assert result["allowed"] is True
    assert result["paper_account_pinned"] is True
    assert runner.started_specs[0].env[ALPACA_PAPER_ACCOUNT_PIN_ENV_KEY] == "045ded"


def test_launch_readiness_surfaces_exact_account_pin_blocker(monkeypatch, tmp_path) -> None:
    env_path = tmp_path / "canonical_alpaca_paper.env"
    _write_canonical_paper_env(env_path)
    monkeypatch.setenv(ALPACA_PAPER_ENV_PATH_ENV_KEY, str(env_path))
    checker = lambda env: build_alpaca_paper_account_identity_assertion(env, client=FakeAccountClient("104e2a"))
    provider = OperatorSnapshotProvider(
        runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
        provider_env=dict(BROKER_READ_AUTH),
        credential_store=LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json"),
        account_identity_checker=checker,
    )
    app = create_operator_app(provider=provider)

    payload = _endpoint(app, "/operator/launch-readiness")()

    assert payload["final_launch_readiness"] == "BLOCKED"
    assert payload["paper_account_pinned"] is False
    assert payload["paper_account_expected_suffix"] == "045ded"
    assert payload["paper_account_actual_suffix"] == "104e2a"
    assert "alpaca_paper_account_pin" in payload["reason_codes"]
    assert payload["run_paper_operator_state"]["can_run_paper"]["reason"] == (
        "Expected Alpaca PAPER account suffix 045ded, got 104e2a."
    )
