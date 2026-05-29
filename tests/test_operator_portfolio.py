from __future__ import annotations

from app.api.operator_readonly_api import OperatorSnapshotProvider, create_operator_app
from app.api.operator_runtime_config import OperatorRuntimeConfig
from app.operator_credentials.store import LocalCredentialStore
from app.operator_portfolio.snapshot import build_portfolio_snapshot


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

    assert payload["status"] == "BROKER_DATA_UNAVAILABLE"
    assert payload["unavailable_reason"] == "MISSING_ALPACA_PAPER_CREDENTIALS"
    assert payload["positions"] == []
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
    assert payload["positions"][0]["latest_fill_price"] == "50000"
    assert payload["open_orders"][0]["read_only"] is True
    assert payload["open_orders"][0]["can_cancel"] is False
    assert payload["summary"]["broker_local_reconciliation_status"] == "BROKER_CONFIRMED_NO_LOCAL_TRUTH_PROMOTED"
    assert all(method == "GET" for method, _path in client.calls)
    assert payload["broker_mutation_occurred"] is False
    assert payload["cancel_occurred"] is False
    assert payload["liquidation_occurred"] is False


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
    assert payload["empty"] is True
    assert payload["message"] == "No current PAPER positions."
    assert payload["positions"] == []


def test_operator_portfolio_endpoints_are_read_only(tmp_path):
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    store.save_provider("alpaca_paper", {"APCA_API_KEY_ID": "id", "APCA_API_SECRET_KEY": "secret"})
    client = FakeReadOnlyClient(_broker_payloads())
    app = create_operator_app(
        provider=OperatorSnapshotProvider(
            runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
            provider_env={},
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
