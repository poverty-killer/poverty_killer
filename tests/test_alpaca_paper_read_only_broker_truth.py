from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import pytest

from app.execution.live_read_only_adapter import (
    LiveReadOnlyBrokerAdapter,
    ReadOnlyAdapterConfig,
)
from app.utils.time_utils import now_ns


EXPECTED_PAPER_BASE_URL = "https://paper-api.alpaca.markets"
ALLOWED_GET_PATHS = frozenset(
    {
        "/v2/account",
        "/v2/positions",
        "/v2/orders",
        "/v2/account/activities",
        "/v2/clock",
    }
)


@dataclass(frozen=True)
class AlpacaEnv:
    base_url: str
    key_id: str
    secret_key: str


class AlpacaReadOnlyHttpClient:
    def __init__(self, env: AlpacaEnv) -> None:
        self._env = env
        self.calls: list[tuple[str, str]] = []

    @property
    def base_url(self) -> str:
        return self._env.base_url

    def get_json(self, path: str, query: dict[str, str] | None = None) -> Any:
        self._validate_get(path, query)
        url = f"{self._env.base_url}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "APCA-API-KEY-ID": self._env.key_id,
                "APCA-API-SECRET-KEY": self._env.secret_key,
                "Accept": "application/json",
            },
        )
        self.calls.append(("GET", path))
        try:
            with urllib.request.urlopen(request, timeout=10.0) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise AssertionError(f"alpaca_read_only_http_error:{exc.code}:{path}:{body[:180]}") from exc

    def _validate_get(self, path: str, query: dict[str, str] | None) -> None:
        assert self._env.base_url == EXPECTED_PAPER_BASE_URL
        assert self._env.base_url.startswith("https://paper-api.alpaca.markets")
        assert "api.alpaca.markets" not in self._env.base_url.replace("paper-api.alpaca.markets", "")
        assert path in ALLOWED_GET_PATHS
        assert path.startswith("/v2/")
        assert path != "/v2/orders" or (query or {}).get("status") == "open"
        blocked_fragments = ("submit", "cancel", "replace", "close", "liquidate")
        assert not any(fragment in path.lower() for fragment in blocked_fragments)


class AlpacaReadOnlySource:
    def __init__(self, client: AlpacaReadOnlyHttpClient, account: dict[str, Any], clock: dict[str, Any] | None = None) -> None:
        self._client = client
        self._account = account
        self._clock = clock or {}

    def fetch_balances(self):
        return (
            {
                "currency": self._account.get("currency") or "USD",
                "cash": _decimal_or_none(self._account.get("cash")),
                "buying_power": _decimal_or_none(self._account.get("buying_power")),
                "equity": _decimal_or_none(self._account.get("equity")),
                "portfolio_value": _decimal_or_none(self._account.get("portfolio_value")),
                "long_market_value": _decimal_or_none(self._account.get("long_market_value")),
                "short_market_value": _decimal_or_none(self._account.get("short_market_value")),
                "source": "alpaca_paper_account",
            },
        )

    def fetch_positions(self):
        positions = self._client.get_json("/v2/positions")
        _validate_positions_payload(positions)
        return tuple(
            {
                "symbol": item.get("symbol"),
                "instrument_id": item.get("asset_id"),
                "quantity": _decimal_or_none(item.get("qty")),
                "side": item.get("side"),
                "market_value": _decimal_or_none(item.get("market_value")),
                "average_entry_price": _decimal_or_none(item.get("avg_entry_price")),
                "source": "alpaca_paper_positions",
            }
            for item in (positions or ())
        )

    def fetch_normalized_open_orders(self):
        orders = self._client.get_json("/v2/orders", {"status": "open", "limit": "50", "nested": "false"})
        return tuple(
            {
                "client_order_id": item.get("client_order_id"),
                "broker_order_id": item.get("id"),
                "symbol": item.get("symbol"),
                "side": item.get("side"),
                "quantity": _decimal_or_none(item.get("qty")),
                "filled_qty": _decimal_or_none(item.get("filled_qty")),
                "order_type": item.get("type"),
                "status": item.get("status"),
                "submitted_at": item.get("submitted_at"),
                "updated_at": item.get("updated_at"),
                "source": "alpaca_paper_open_orders",
            }
            for item in (orders or ())
        )

    def fetch_fills(self, limit: int = 100):
        activities = self._client.get_json("/v2/account/activities", {"activity_types": "FILL", "page_size": str(min(limit, 100))})
        if isinstance(activities, dict):
            items = activities.get("activities", ())
        else:
            items = activities or ()
        return tuple(
            {
                "venue_fill_id": item.get("id"),
                "client_order_id": item.get("client_order_id"),
                "broker_order_id": item.get("order_id"),
                "symbol": item.get("symbol"),
                "side": item.get("side"),
                "quantity": _decimal_or_none(item.get("qty")),
                "price": _decimal_or_none(item.get("price")),
                "fee": _decimal_or_none(item.get("commission") or "0"),
                "fee_currency": self._account.get("currency") or "USD",
                "transaction_time": item.get("transaction_time"),
                "source": "alpaca_paper_account_activities",
            }
            for item in items
        )


def _decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    return Decimal(str(value))


def _validate_positions_payload(positions: Any) -> None:
    assert isinstance(positions, list), "alpaca_positions_invalid_shape"
    for item in positions:
        assert isinstance(item, dict), "alpaca_position_item_invalid_shape"
        symbol = item.get("symbol")
        qty = item.get("qty")
        assert isinstance(symbol, str) and symbol.strip(), "alpaca_position_missing_symbol"
        assert qty not in (None, ""), "alpaca_position_missing_qty"
        Decimal(str(qty))


def _alpaca_env_or_skip() -> AlpacaEnv:
    base_url = (os.environ.get("APCA_API_BASE_URL") or "").rstrip("/")
    key_id = os.environ.get("APCA_API_KEY_ID") or ""
    secret_key = os.environ.get("APCA_API_SECRET_KEY") or ""
    missing = []
    if not base_url:
        missing.append("APCA_API_BASE_URL")
    if not key_id:
        missing.append("APCA_API_KEY_ID")
    if not secret_key:
        missing.append("APCA_API_SECRET_KEY")
    if missing:
        pytest.skip(f"Alpaca paper read-only env missing: {', '.join(missing)}")
    if base_url != EXPECTED_PAPER_BASE_URL:
        pytest.fail(f"APCA_API_BASE_URL is not exact paper endpoint: {base_url!r}")
    return AlpacaEnv(base_url=base_url, key_id=key_id, secret_key=secret_key)


def _mask(value: str | None) -> str:
    if not value:
        return "missing"
    if len(value) <= 8:
        return "present_masked"
    return f"{value[:4]}...{value[-4:]}"


def test_alpaca_paper_read_only_gets_map_into_25t_snapshot_without_mutation():
    env = _alpaca_env_or_skip()
    client = AlpacaReadOnlyHttpClient(env)

    account = client.get_json("/v2/account")
    clock = client.get_json("/v2/clock")
    source = AlpacaReadOnlySource(client, account, clock)
    receive_ts_ns = now_ns()
    adapter = LiveReadOnlyBrokerAdapter(
        source,
        ReadOnlyAdapterConfig(
            read_only_enabled=True,
            environment="paper",
            source="alpaca",
            allow_mutation=False,
            board_authorized_production_read=False,
            account_id=account.get("id"),
            credentials_present=True,
            credentials_required_for_call=True,
        ),
    )

    snapshot = adapter.get_exchange_truth_snapshot(
        receive_ts_ns=receive_ts_ns,
        asof_ts_ns=receive_ts_ns,
        require_credentials=True,
        require_account_identity=True,
    )
    mapping = snapshot.contract_mapping()

    assert client.base_url == EXPECTED_PAPER_BASE_URL
    assert all(method == "GET" for method, _path in client.calls)
    assert {path for _method, path in client.calls}.issubset(ALLOWED_GET_PATHS)
    assert ("GET", "/v2/positions") in client.calls
    assert ("GET", "/v2/orders") in client.calls
    assert snapshot.source == "alpaca"
    assert snapshot.environment == "paper"
    assert snapshot.read_only is True
    assert snapshot.mutation_allowed is False
    assert snapshot.account_identity_status == "known"
    assert mapping["account_identity_source_environment_timestamp_25q"] is True
    assert mapping["balances_25q"] is True
    assert mapping["positions_25q"] is bool(snapshot.positions)
    assert mapping["open_orders_25o_25q"] is True
    assert mapping["recent_fills_25p_25q"] is True
    assert mapping["read_only_no_submit_cancel_25m_25r"] is True
    assert snapshot.balances[0]["cash"] == _decimal_or_none(account.get("cash"))
    assert _mask(account.get("id")) != "missing"
    for mutation_name in ("submit_order", "cancel_order", "replace_order", "place_order"):
        assert not hasattr(adapter, mutation_name)


def test_alpaca_read_only_client_rejects_non_paper_or_mutating_paths_without_network():
    client = AlpacaReadOnlyHttpClient(AlpacaEnv(EXPECTED_PAPER_BASE_URL, "key", "secret"))

    with pytest.raises(AssertionError):
        client._validate_get("/v2/orders", {"status": "all"})
    with pytest.raises(AssertionError):
        client._validate_get("/v2/orders/abc/cancel", None)
    with pytest.raises(AssertionError):
        client._validate_get("/v2/account/configurations", None)

    live_client = AlpacaReadOnlyHttpClient(AlpacaEnv("https://api.alpaca.markets", "key", "secret"))
    with pytest.raises(AssertionError):
        live_client._validate_get("/v2/account", None)

    _validate_positions_payload([])
    _validate_positions_payload([{"symbol": "AAPL", "qty": "0"}])
    with pytest.raises(AssertionError):
        _validate_positions_payload({})
    with pytest.raises(AssertionError):
        _validate_positions_payload([{"symbol": "", "qty": "1"}])
    with pytest.raises(AssertionError):
        _validate_positions_payload([{"symbol": "AAPL"}])
    with pytest.raises(InvalidOperation):
        _validate_positions_payload([{"symbol": "AAPL", "qty": "not-a-decimal"}])
