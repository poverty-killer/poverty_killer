from __future__ import annotations

from pathlib import Path
from urllib.error import HTTPError

import pytest

from app.api.operator_readonly_api import OperatorSnapshotProvider, create_operator_app
from app.api.operator_runtime_config import OperatorRuntimeConfig
from app.execution.broker_read_policy import BROKER_READ_PROFILE_ENV, PAPER_TCA_EXTENDED_READS
from app.operator_credentials.store import ALPACA_PAPER_ENV_PATH_ENV_KEY, LocalCredentialStore
from app.operator_portfolio.snapshot import build_portfolio_snapshot

PAPER_ENDPOINT = "https://paper-api.alpaca.markets"
TEST_BROKER_READ_AUTH = {"PK_BOARD_AUTHORIZED_PAPER_BROKER_READ": "YES_D4_BOARD_AUTHORIZED"}


class FakeReadOnlyClient:
    def __init__(self, payloads):
        self.payloads = payloads
        self.calls = []

    def get_json(self, path, headers):
        self.calls.append(("GET", path))
        for key, value in sorted(self.payloads.items(), key=lambda item: len(item[0]), reverse=True):
            if path.startswith(key):
                return value
        raise RuntimeError("unexpected_path")


def _endpoint(app, path: str, method: str = "GET"):
    for route in app.routes:
        if route.path == path and method in (route.methods or set()):
            return route.endpoint
    raise AssertionError(f"route not found: {method} {path}")


@pytest.fixture(autouse=True)
def _isolated_canonical_paper_env(monkeypatch, tmp_path) -> Path:
    path = tmp_path / "canonical_alpaca_paper.env"
    monkeypatch.setenv(ALPACA_PAPER_ENV_PATH_ENV_KEY, str(path))
    return path


def _write_canonical_paper_env(
    path: Path,
    *,
    key_id: str = "id",
    secret_key: str = "secret",
    base_url: str | None = None,
) -> None:
    lines: list[str] = []
    if base_url is not None:
        lines.append(f"APCA_API_BASE_URL={base_url}")
    lines.extend(
        [
            f"APCA_API_KEY_ID={key_id}",
            f"APCA_API_SECRET_KEY={secret_key}",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _broker_payloads():
    return {
        "/v2/account": {
            "equity": "10000",
            "portfolio_value": "10000",
            "cash": "7500",
            "buying_power": "15000",
            "long_market_value": "2500",
        },
        "/v2/positions": [
            {
                "symbol": "BTCUSD",
                "asset_class": "crypto",
                "qty": "0.05",
                "side": "long",
                "avg_entry_price": "50000",
                "current_price": "52000",
                "cost_basis": "2500",
                "market_value": "2600",
                "unrealized_pl": "100",
                "unrealized_plpc": "0.04",
                "lastday_price": "51000",
                "change_today": "0.0196",
            }
        ],
        "/v2/orders": [
            {
                "id": "order-1",
                "client_order_id": "client-1",
                "symbol": "BTCUSD",
                "asset_class": "crypto",
                "qty": "0.01",
                "filled_qty": "0",
                "side": "buy",
                "type": "limit",
                "time_in_force": "gtc",
                "limit_price": "50000",
                "status": "new",
                "submitted_at": "2026-05-29T00:00:00Z",
            }
        ],
        "/v2/account/activities/FILL": [
            {
                "symbol": "BTCUSD",
                "transaction_time": "2026-05-28T23:59:00Z",
                "price": "50000",
                "qty": "0.05",
                "side": "buy",
            }
        ],
    }


def test_portfolio_missing_credentials_is_unavailable_without_fake_positions():
    payload = build_portfolio_snapshot({})

    assert payload["status"] == "MISSING_CREDENTIALS"
    assert payload["unavailable_reason"] == "MISSING_ALPACA_PAPER_CREDENTIALS"
    assert payload["positions"] == []
    assert payload["broker_read_attempted"] is False
    assert payload["broker_read_occurred"] is False
    assert payload["broker_mutation_occurred"] is False


def test_broker_confirmed_positions_are_labeled_and_read_only():
    client = FakeReadOnlyClient(_broker_payloads())
    payload = build_portfolio_snapshot(
        {
            "APCA_API_KEY_ID": "id",
            "APCA_API_SECRET_KEY": "secret",
            "APCA_API_BASE_URL": "https://paper-api.alpaca.markets",
        },
        client=client,
        now="2026-05-29T00:00:00+00:00",
    )

    assert payload["status"] == "BROKER_CONFIRMED"
    assert payload["summary"]["position_count"] == 1
    assert payload["positions"][0]["source"] == "BROKER_CONFIRMED"
    assert payload["positions"][0]["broker_confirmed"] is True
    assert payload["positions"][0]["latest_fill_price"] is None
    assert payload["summary"]["activities_status"] == "SKIPPED_NOT_AUTHORIZED"
    assert payload["summary"]["activities_skip_reason"] == "BROKER_READ_NOT_AUTHORIZED"
    assert payload["summary"]["account_activity_read_authorized"] is False
    assert payload["open_orders"][0]["read_only"] is True
    assert payload["open_orders"][0]["can_cancel"] is False
    assert payload["summary"]["broker_local_reconciliation_status"] == "BROKER_CONFIRMED_NO_LOCAL_TRUTH_PROMOTED"
    assert all(method == "GET" for method, _path in client.calls)
    assert payload["broker_mutation_occurred"] is False
    assert payload["cancel_occurred"] is False
    assert payload["liquidation_occurred"] is False


def test_extended_profile_can_attach_activity_fill_context_when_explicitly_authorized():
    client = FakeReadOnlyClient(_broker_payloads())
    payload = build_portfolio_snapshot(
        {
            "APCA_API_KEY_ID": "id",
            "APCA_API_SECRET_KEY": "secret",
            "APCA_API_BASE_URL": "https://paper-api.alpaca.markets",
            BROKER_READ_PROFILE_ENV: PAPER_TCA_EXTENDED_READS,
        },
        client=client,
        now="2026-05-29T00:00:00+00:00",
    )

    assert payload["positions"][0]["latest_fill_price"] == "50000"
    assert payload["summary"]["activities_status"] == "AVAILABLE"
    assert payload["summary"]["account_activity_read_authorized"] is True
    assert ("GET", "/v2/account/activities/FILL?direction=desc&page_size=100") in client.calls


def test_empty_broker_portfolio_is_honest():
    client = FakeReadOnlyClient(
        {
            "/v2/account": {"equity": "10000", "cash": "10000", "buying_power": "20000"},
            "/v2/positions": [],
            "/v2/orders": [],
            "/v2/account/activities/FILL": [],
        }
    )

    payload = build_portfolio_snapshot(
        {"APCA_API_KEY_ID": "id", "APCA_API_SECRET_KEY": "secret"},
        client=client,
    )

    assert payload["status"] == "BROKER_CONFIRMED_EMPTY"
    assert payload["paper_endpoint_only"] is True
    assert payload["paper_endpoint_status"] == "PAPER_ENDPOINT_CONFIRMED"
    assert payload["empty"] is True
    assert payload["message"] == "No current PAPER positions."
    assert payload["positions"] == []


def test_portfolio_blocks_non_trading_endpoint_before_broker_read():
    class ExplodingReadOnlyClient:
        def __init__(self) -> None:
            self.calls = []

        def get_json(self, path, headers):
            self.calls.append(("GET", path))
            raise AssertionError("broker read should not occur for invalid trading endpoint")

    client = ExplodingReadOnlyClient()
    payload = build_portfolio_snapshot(
        {
            "APCA_API_KEY_ID": "id",
            "APCA_API_SECRET_KEY": "secret",
            "APCA_API_BASE_URL": "https://data.alpaca.markets",
        },
        client=client,
    )

    assert payload["status"] == "BACKEND_DEGRADED"
    assert payload["unavailable_reason"] == "ALPACA_DATA_ENDPOINT_NOT_TRADING"
    assert payload["paper_endpoint_only"] is False
    assert payload["paper_endpoint_authority"]["alpaca_trading_endpoint_family"] == "data"
    assert payload["broker_read_attempted"] is False
    assert payload["broker_mutation_occurred"] is False
    assert client.calls == []


def test_operator_portfolio_endpoints_are_read_only(tmp_path, _isolated_canonical_paper_env):
    _write_canonical_paper_env(_isolated_canonical_paper_env)
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    store.save_provider("alpaca_paper", {"APCA_API_KEY_ID": "id", "APCA_API_SECRET_KEY": "secret"})
    client = FakeReadOnlyClient(_broker_payloads())
    app = create_operator_app(
        provider=OperatorSnapshotProvider(
            runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
            provider_env=dict(TEST_BROKER_READ_AUTH),
            credential_store=store,
            portfolio_client=client,
        )
    )

    portfolio = _endpoint(app, "/operator/portfolio")()
    positions = _endpoint(app, "/operator/positions")()
    orders = _endpoint(app, "/operator/orders/open")()
    intelligence = _endpoint(app, "/operator/positions/intelligence")()

    assert portfolio["broker_mutation_occurred"] is False
    assert positions["broker_mutation_occurred"] is False
    assert orders["can_cancel"] is False
    assert intelligence["can_execute"] is False
    assert intelligence["position_intelligence"][0]["source"] == "BROKER_CONFIRMED"
    assert all(method == "GET" for method, _path in client.calls)


def test_operator_portfolio_refreshes_canonical_env_after_backend_start(tmp_path, _isolated_canonical_paper_env):
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    client = FakeReadOnlyClient(_broker_payloads())
    provider = OperatorSnapshotProvider(
        runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
        provider_env=dict(TEST_BROKER_READ_AUTH),
        credential_store=store,
        portfolio_client=client,
    )
    app = create_operator_app(provider=provider)

    before = _endpoint(app, "/operator/portfolio")()
    store.save_provider("alpaca_paper", {"APCA_API_KEY_ID": "id", "APCA_API_SECRET_KEY": "secret"})
    after_local_save = _endpoint(app, "/operator/portfolio")()
    _write_canonical_paper_env(_isolated_canonical_paper_env)
    after = _endpoint(app, "/operator/portfolio")()

    assert before["unavailable_reason"] == "MISSING_ALPACA_PAPER_CREDENTIALS"
    assert after_local_save["unavailable_reason"] == "MISSING_ALPACA_PAPER_CREDENTIALS"
    assert after["status"] == "BROKER_CONFIRMED"
    assert after["broker_read_occurred"] is True
    assert all(method == "GET" for method, _path in client.calls)


def test_broker_confirmed_portfolio_and_launch_readiness_share_alpaca_truth(tmp_path, _isolated_canonical_paper_env):
    _write_canonical_paper_env(_isolated_canonical_paper_env)
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    store.save_provider("alpaca_news", {"APCA_API_KEY_ID": "id", "APCA_API_SECRET_KEY": "secret"})
    client = FakeReadOnlyClient(_broker_payloads())
    app = create_operator_app(
        provider=OperatorSnapshotProvider(
            runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
            provider_env=dict(TEST_BROKER_READ_AUTH),
            credential_store=store,
            portfolio_client=client,
        )
    )

    portfolio = _endpoint(app, "/operator/portfolio")()
    launch = _endpoint(app, "/operator/launch-readiness")()

    assert portfolio["status"] == "BROKER_CONFIRMED"
    assert portfolio["broker_read_occurred"] is True
    assert launch["alpaca_paper_credentials_configured"] is True
    assert "alpaca_paper_credentials" not in launch["reason_codes"]


def test_alpaca_canonical_credentials_are_single_truth_for_cards_providers_launch_portfolio_and_supervisor(
    tmp_path,
    _isolated_canonical_paper_env,
):
    _write_canonical_paper_env(_isolated_canonical_paper_env, base_url=PAPER_ENDPOINT)
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    store.save_provider(
        "alpaca_paper",
        {
            "APCA_API_KEY_ID": "id",
            "APCA_API_SECRET_KEY": "secret",
            "APCA_API_BASE_URL": "https://paper-api.alpaca.markets",
        },
    )
    client = FakeReadOnlyClient(_broker_payloads())
    provider = OperatorSnapshotProvider(
        runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
        provider_env=dict(TEST_BROKER_READ_AUTH),
        credential_store=store,
        portfolio_client=client,
    )
    app = create_operator_app(provider=provider)

    credentials = _endpoint(app, "/operator/credentials/providers")()
    providers = _endpoint(app, "/operator/providers")()
    provider_readiness = _endpoint(app, "/operator/providers/readiness")()
    launch = _endpoint(app, "/operator/launch-readiness")()
    portfolio = _endpoint(app, "/operator/portfolio")()
    diagnostics = _endpoint(app, "/operator/credentials/diagnostics")()

    credential_row = next(row for row in credentials["providers"] if row["provider_id"] == "alpaca_paper")
    provider_row = next(row for row in providers["providers"] if row["provider_id"] == "alpaca_paper")
    source_map = {
        field["name"]: field["source"]
        for field in credential_row["fields"]
    }

    assert credential_row["configured"] is True
    assert provider_row["status"] in {"CONFIGURED", "READY"}
    assert provider_readiness["ready_or_configured_count"] >= 1
    assert source_map["APCA_API_KEY_ID"] == "CANONICAL_PAPER_ENV_FILE"
    assert source_map["APCA_API_SECRET_KEY"] == "CANONICAL_PAPER_ENV_FILE"
    assert source_map["APCA_API_BASE_URL"] == "CANONICAL_PAPER_ENV_FILE"
    assert launch["alpaca_paper_credentials_configured"] is True
    assert "alpaca_paper_credentials" not in launch["reason_codes"]
    assert portfolio["status"] == "BROKER_CONFIRMED"
    assert diagnostics["source_used_by_credential_cards"] == "CANONICAL_PAPER_ENV_FILE"
    assert diagnostics["source_used_by_provider_table"] == "CANONICAL_PAPER_ENV_FILE"
    assert diagnostics["source_used_by_launch_readiness"] == "CANONICAL_PAPER_ENV_FILE"
    assert diagnostics["source_used_by_portfolio"] == "CANONICAL_PAPER_ENV_FILE"
    assert diagnostics["source_used_by_paper_supervisor"] == "CANONICAL_PAPER_ENV_FILE"
    assert all(diagnostics["paper_supervisor_required_field_names_present"].values())
    assert provider.supervisor.config.process_env["APCA_API_BASE_URL"] == "https://paper-api.alpaca.markets"


def test_operator_portfolio_uses_canonical_env_and_reports_broker_failure_not_missing_credentials(
    tmp_path,
    _isolated_canonical_paper_env,
):
    _write_canonical_paper_env(_isolated_canonical_paper_env)
    class FailingReadOnlyClient:
        def __init__(self) -> None:
            self.calls = []

        def get_json(self, path, headers):
            self.calls.append(("GET", path))
            raise RuntimeError("broker unavailable")

    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    store.save_provider("alpaca_paper", {"APCA_API_KEY_ID": "id", "APCA_API_SECRET_KEY": "secret"})
    client = FailingReadOnlyClient()
    app = create_operator_app(
        provider=OperatorSnapshotProvider(
            runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
            provider_env=dict(TEST_BROKER_READ_AUTH),
            credential_store=store,
            portfolio_client=client,
        )
    )

    payload = _endpoint(app, "/operator/portfolio")()

    assert payload["status"] == "BROKER_READ_FAILED"
    assert payload["unavailable_reason"] == "BROKER_READ_FAILED"
    assert payload["detail"] == "RuntimeError"
    assert payload["broker_read_attempted"] is True
    assert client.calls == [("GET", "/v2/account")]
    assert payload["broker_mutation_occurred"] is False


def test_operator_portfolio_reports_auth_failure_not_missing_credentials(tmp_path, _isolated_canonical_paper_env):
    _write_canonical_paper_env(_isolated_canonical_paper_env)
    class AuthFailingReadOnlyClient:
        def __init__(self) -> None:
            self.calls = []

        def get_json(self, path, headers):
            self.calls.append(("GET", path))
            raise HTTPError("https://paper-api.alpaca.markets/v2/account", 401, "Unauthorized", {}, None)

    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    store.save_provider("alpaca_paper", {"APCA_API_KEY_ID": "id", "APCA_API_SECRET_KEY": "secret"})
    client = AuthFailingReadOnlyClient()
    app = create_operator_app(
        provider=OperatorSnapshotProvider(
            runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
            provider_env=dict(TEST_BROKER_READ_AUTH),
            credential_store=store,
            portfolio_client=client,
        )
    )

    payload = _endpoint(app, "/operator/portfolio")()

    assert payload["status"] == "AUTH_FAILED"
    assert payload["unavailable_reason"] == "AUTH_FAILED"
    assert payload["broker_read_attempted"] is True
    assert client.calls == [("GET", "/v2/account")]
    assert payload["broker_mutation_occurred"] is False
