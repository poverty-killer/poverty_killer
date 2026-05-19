from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any

import pytest

from app.utils.time_utils import now_ns


EXPECTED_PAPER_BASE_URL = "https://paper-api.alpaca.markets"
FORBIDDEN_LIVE_BASE_URL = "https://api.alpaca.markets"
EXPECTED_POSITION_SYMBOLS = ("AAPL", "NVDA", "AMZN", "GOOGL", "TSLA", "SPY", "QQQ")
SUBMITTED_26B_SYMBOLS = ("NVDA", "AMZN", "GOOGL", "TSLA", "SPY", "QQQ")
SKIPPED_26B = {
    "AAPL": "existing_position_present",
    "MSFT": "quote_wide_spread",
    "META": "quote_wide_spread",
    "AMD": "reason_not_emitted_by_existing_26b_harness",
}
ACTIVE_ORDER_STATUSES = frozenset({"accepted", "new", "pending_new", "open", "accepted_for_bidding"})
TERMINAL_FILLED_STATUSES = frozenset({"filled"})
ALLOWED_GET_PATHS = frozenset({"/v2/account", "/v2/positions", "/v2/orders", "/v2/account/activities", "/v2/clock"})
KNOWN_ORDER_IDS = frozenset(
    {
        "b47cdef4-a913-4517-9cac-5d96f319de91",
        "9f7a4b8f-5f46-4657-9fc9-64a39126e61f",
        "fcc9b06f-6e6c-4bba-b73f-c77258a39c68",
        "e636c120-9948-4732-b7c8-a38fa3fbe9c7",
        "3a3e04f9-69d4-4ff4-a153-a4e898d763e7",
        "f78c7c5c-6ce3-41f0-977d-8238558488c1",
        "18ad682e-16f6-44fa-b3d5-ac3875399bcd",
    }
)


@dataclass(frozen=True)
class KnownFill:
    symbol: str
    broker_order_id: str
    client_order_id: str
    filled_qty: Decimal
    avg_fill_price: Decimal
    source_packet: str
    fee: Decimal | None = None
    fee_currency: str | None = None

    @property
    def gross_filled_notional(self) -> Decimal:
        return (self.filled_qty * self.avg_fill_price).quantize(Decimal("0.00000001"))


@dataclass(frozen=True)
class PortfolioOwnership:
    account: dict[str, Any]
    positions: tuple[dict[str, Any], ...]
    open_orders: tuple[dict[str, Any], ...]
    known_orders: tuple[dict[str, Any], ...]
    fill_activities: tuple[dict[str, Any], ...]
    receive_ts_ns: int
    local_runtime_flat_assumption: bool = False
    live_reservation_lifecycle_activated: bool = False
    production_exposure_mutated: bool = False
    economics_veto_activated: bool = False


KNOWN_FILLS: tuple[KnownFill, ...] = (
    KnownFill(
        symbol="AAPL",
        broker_order_id="b47cdef4-a913-4517-9cac-5d96f319de91",
        client_order_id="pk25z-paper-aapl-buy-limit-day-1777948800000000100",
        filled_qty=Decimal("0.016903"),
        avg_fill_price=Decimal("295.78"),
        source_packet="25Z-B",
    ),
    KnownFill(
        symbol="NVDA",
        broker_order_id="9f7a4b8f-5f46-4657-9fc9-64a39126e61f",
        client_order_id="pk26b-paper-batch-nvda-buy-limit-day-1779133016649129759",
        filled_qty=Decimal("0.022593"),
        avg_fill_price=Decimal("221.284"),
        source_packet="26B",
    ),
    KnownFill(
        symbol="AMZN",
        broker_order_id="fcc9b06f-6e6c-4bba-b73f-c77258a39c68",
        client_order_id="pk26b-paper-batch-amzn-buy-limit-day-1779133016649129760",
        filled_qty=Decimal("0.018912"),
        avg_fill_price=Decimal("264.372"),
        source_packet="26B",
    ),
    KnownFill(
        symbol="GOOGL",
        broker_order_id="e636c120-9948-4732-b7c8-a38fa3fbe9c7",
        client_order_id="pk26b-paper-batch-googl-buy-limit-day-1779133016649129762",
        filled_qty=Decimal("0.012572"),
        avg_fill_price=Decimal("397.628"),
        source_packet="26B",
    ),
    KnownFill(
        symbol="TSLA",
        broker_order_id="3a3e04f9-69d4-4ff4-a153-a4e898d763e7",
        client_order_id="pk26b-paper-batch-tsla-buy-limit-day-1779133016649129763",
        filled_qty=Decimal("0.012195"),
        avg_fill_price=Decimal("409.966"),
        source_packet="26B",
    ),
    KnownFill(
        symbol="SPY",
        broker_order_id="f78c7c5c-6ce3-41f0-977d-8238558488c1",
        client_order_id="pk26b-paper-batch-spy-buy-limit-day-1779133016649129765",
        filled_qty=Decimal("0.006787"),
        avg_fill_price=Decimal("736.628"),
        source_packet="26B",
    ),
    KnownFill(
        symbol="QQQ",
        broker_order_id="18ad682e-16f6-44fa-b3d5-ac3875399bcd",
        client_order_id="pk26b-paper-batch-qqq-buy-limit-day-1779133016649129766",
        filled_qty=Decimal("0.007111"),
        avg_fill_price=Decimal("703.048"),
        source_packet="26B",
    ),
)


class AlpacaPaperReadOnlyClient:
    def __init__(self, base_url: str, key_id: str, secret_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._key_id = key_id
        self._secret_key = secret_key
        self.calls: list[tuple[str, str]] = []

    def get_json(self, path: str, query: dict[str, str] | None = None) -> Any:
        self._validate_get(path, query)
        return self._request_json("GET", path, query=query)

    def request_json(self, method: str, path: str, query: dict[str, str] | None = None, payload: dict[str, Any] | None = None) -> Any:
        assert method == "GET", "alpaca_26c_mutating_method_forbidden"
        assert payload is None, "alpaca_26c_payload_forbidden"
        return self.get_json(path, query)

    def _request_json(self, method: str, path: str, *, query: dict[str, str] | None = None) -> Any:
        assert method == "GET"
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "APCA-API-KEY-ID": self._key_id,
                "APCA-API-SECRET-KEY": self._secret_key,
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
            pytest.skip(f"Alpaca PAPER read-only lookup unavailable: HTTP {exc.code}: {body[:120]}")
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            pytest.skip(f"Alpaca PAPER read-only network unavailable: {type(exc).__name__}")

    def _validate_get(self, path: str, query: dict[str, str] | None) -> None:
        assert self.base_url == EXPECTED_PAPER_BASE_URL
        if path.startswith("/v2/orders/"):
            suffix = path.removeprefix("/v2/orders/")
            assert suffix in KNOWN_ORDER_IDS
            assert query is None
            return
        assert path in ALLOWED_GET_PATHS
        if path == "/v2/orders":
            assert (query or {}).get("status") in {"open", "closed"}
        blocked_fragments = ("submit", "cancel", "replace", "close", "liquidate")
        assert not any(fragment in path.lower() for fragment in blocked_fragments)


def _d(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    return Decimal(str(value))


def _env_or_skip() -> tuple[str, str, str]:
    base_url = (os.environ.get("APCA_API_BASE_URL") or "").rstrip("/")
    key_id = os.environ.get("APCA_API_KEY_ID") or ""
    secret_key = os.environ.get("APCA_API_SECRET_KEY") or ""
    if not base_url or not key_id or not secret_key:
        pytest.skip("Alpaca PAPER read-only credentials unavailable")
    if base_url != EXPECTED_PAPER_BASE_URL:
        pytest.fail(f"APCA_API_BASE_URL is not exact paper endpoint: {base_url!r}")
    return base_url, key_id, secret_key


def _position_by_symbol(positions: tuple[dict[str, Any], ...]) -> dict[str, dict[str, Any]]:
    return {str(position.get("symbol") or "").upper(): position for position in positions}


def _orders_by_id(orders: tuple[dict[str, Any], ...]) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for order in orders:
        order_id = str(order.get("id") or order.get("broker_order_id") or "")
        assert order_id and order_id not in by_id, "duplicate_order_id"
        by_id[order_id] = order
    return by_id


def _activities_by_order_id(activities: tuple[dict[str, Any], ...]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for activity in activities:
        order_id = str(activity.get("order_id") or activity.get("broker_order_id") or "")
        if order_id:
            grouped.setdefault(order_id, []).append(activity)
    return grouped


def _normalize_activities(payload: Any) -> tuple[dict[str, Any], ...]:
    if isinstance(payload, dict):
        payload = payload.get("activities") or []
    assert isinstance(payload, list), "alpaca_activities_invalid_shape"
    return tuple(item for item in payload if isinstance(item, dict))


def reconcile_portfolio_ownership(snapshot: PortfolioOwnership) -> dict[str, Any]:
    assert not snapshot.local_runtime_flat_assumption, "local_flat_assumption_forbidden_with_broker_positions"
    assert not snapshot.live_reservation_lifecycle_activated
    assert not snapshot.production_exposure_mutated
    assert not snapshot.economics_veto_activated

    account_status = str(snapshot.account.get("status") or "").upper()
    if account_status:
        assert account_status in {"ACTIVE", "ACCOUNT_ACTIVE"}, "account_status_blocked"
    assert not bool(snapshot.account.get("trading_blocked") or False), "account_trading_blocked"
    assert not bool(snapshot.account.get("account_blocked") or False), "account_blocked"

    position_symbols = _position_by_symbol(snapshot.positions)
    open_active = [order for order in snapshot.open_orders if str(order.get("status") or "").lower() in ACTIVE_ORDER_STATUSES]
    orders_by_id = _orders_by_id(snapshot.known_orders)
    activities_by_order_id = _activities_by_order_id(snapshot.fill_activities)

    missing_positions = [fill.symbol for fill in KNOWN_FILLS if fill.symbol not in position_symbols]
    extra_positions = sorted(symbol for symbol in position_symbols if symbol and symbol not in EXPECTED_POSITION_SYMBOLS)
    assert not open_active, "unexpected_open_order"
    assert not missing_positions, f"missing_positions_for_known_fills:{missing_positions}"

    order_results = []
    for fill in KNOWN_FILLS:
        order = orders_by_id.get(fill.broker_order_id)
        if order is None:
            activity_matches = activities_by_order_id.get(fill.broker_order_id, [])
            assert activity_matches, f"missing_filled_order_activity:{fill.symbol}"
            status = "activity_only"
            client_order_id = fill.client_order_id
            filled_qty = fill.filled_qty
        else:
            status = str(order.get("status") or "").lower()
            client_order_id = str(order.get("client_order_id") or "")
            filled_qty = _d(order.get("filled_qty")) or Decimal("0")
        assert status in TERMINAL_FILLED_STATUSES or status == "activity_only", f"known_order_not_filled:{fill.symbol}:{status}"
        assert client_order_id == fill.client_order_id, f"mismatched_client_order_id:{fill.symbol}"
        assert filled_qty == fill.filled_qty, f"mismatched_filled_qty:{fill.symbol}"
        assert activities_by_order_id.get(fill.broker_order_id), f"missing_filled_order_activity:{fill.symbol}"
        order_results.append(
            {
                "symbol": fill.symbol,
                "broker_order_id": fill.broker_order_id,
                "client_order_id": fill.client_order_id,
                "filled_qty": str(fill.filled_qty),
                "avg_fill_price": str(fill.avg_fill_price),
                "gross_filled_notional": str(fill.gross_filled_notional),
                "fee": str(fill.fee) if fill.fee is not None else None,
                "fee_currency": fill.fee_currency,
                "fee_missing_gap": fill.fee is None,
                "fee_currency_missing_gap": fill.fee_currency is None,
            }
        )

    return {
        "account_status": snapshot.account.get("status"),
        "currency": snapshot.account.get("currency"),
        "cash": snapshot.account.get("cash"),
        "buying_power": snapshot.account.get("buying_power"),
        "equity": snapshot.account.get("equity"),
        "portfolio_value": snapshot.account.get("portfolio_value"),
        "open_orders_count": len(snapshot.open_orders),
        "positions_count": len(snapshot.positions),
        "expected_positions_present": tuple(symbol for symbol in EXPECTED_POSITION_SYMBOLS if symbol in position_symbols),
        "extra_positions": tuple(extra_positions),
        "known_order_results": tuple(order_results),
        "skipped_symbols": SKIPPED_26B,
        "gross_filled_notional_total": str(sum((fill.gross_filled_notional for fill in KNOWN_FILLS), Decimal("0"))),
        "gaps": (
            "amd_skip_reason_not_emitted_by_existing_26b_harness",
            "fee_missing_if_not_returned_by_broker_activity",
            "fee_currency_missing_if_not_returned_by_broker_activity",
            "arrival_price_gap",
            "slippage_gap",
            "net_edge_gap",
            "paper_vs_live_simulation_gap",
        ),
        "local_runtime_classification": {
            "broker_truth_canonical": True,
            "created_through_controlled_test_harness": True,
            "decision_compiler_runtime_path": False,
            "local_runtime_must_not_assume_flat": True,
            "local_reservations_mutated_retroactively": False,
            "paper_broker_internal_state_is_separate": True,
            "future_runtime_must_ingest_broker_state_before_entry": True,
        },
        "readiness": {
            "new_orders_blocked_without_portfolio_aware_preflight": True,
            "exits_cancels_blocked_without_board_approval": True,
            "live_mode_blocked": True,
            "economics_veto_activation_blocked": True,
            "profitability_claim_blocked": True,
        },
        "pnl_claimed": False,
        "slippage_claimed": False,
        "net_edge_claimed": False,
        "profitability_claimed": False,
        "receive_ts_ns": snapshot.receive_ts_ns,
    }


def _offline_snapshot(
    *,
    positions: tuple[dict[str, Any], ...] | None = None,
    open_orders: tuple[dict[str, Any], ...] = (),
    known_orders: tuple[dict[str, Any], ...] | None = None,
    fill_activities: tuple[dict[str, Any], ...] | None = None,
) -> PortfolioOwnership:
    orders = known_orders or tuple(
        {
            "id": fill.broker_order_id,
            "client_order_id": fill.client_order_id,
            "symbol": fill.symbol,
            "status": "filled",
            "filled_qty": str(fill.filled_qty),
        }
        for fill in KNOWN_FILLS
    )
    activities = fill_activities or tuple({"order_id": fill.broker_order_id, "symbol": fill.symbol, "qty": str(fill.filled_qty), "price": str(fill.avg_fill_price)} for fill in KNOWN_FILLS)
    return PortfolioOwnership(
        account={"status": "ACTIVE", "currency": "USD", "cash": "99965.00", "buying_power": "199965.88", "portfolio_value": "100000.08"},
        positions=positions or tuple({"symbol": symbol, "qty": "0.01"} for symbol in EXPECTED_POSITION_SYMBOLS),
        open_orders=open_orders,
        known_orders=orders,
        fill_activities=activities,
        receive_ts_ns=1_779_133_100_000_000_000,
    )


def test_offline_portfolio_ownership_maps_known_25z_and_26b_fills_to_positions_without_mutation():
    summary = reconcile_portfolio_ownership(_offline_snapshot())

    assert summary["account_status"] == "ACTIVE"
    assert summary["open_orders_count"] == 0
    assert summary["positions_count"] == 7
    assert summary["expected_positions_present"] == EXPECTED_POSITION_SYMBOLS
    assert len(summary["known_order_results"]) == 7
    assert {item["symbol"] for item in summary["known_order_results"]} == set(EXPECTED_POSITION_SYMBOLS)
    assert summary["skipped_symbols"]["AAPL"] == "existing_position_present"
    assert summary["skipped_symbols"]["MSFT"] == "quote_wide_spread"
    assert summary["skipped_symbols"]["META"] == "quote_wide_spread"
    assert summary["skipped_symbols"]["AMD"] == "reason_not_emitted_by_existing_26b_harness"
    assert summary["local_runtime_classification"]["local_runtime_must_not_assume_flat"] is True
    assert summary["readiness"]["new_orders_blocked_without_portfolio_aware_preflight"] is True
    assert summary["pnl_claimed"] is False
    assert summary["slippage_claimed"] is False
    assert summary["net_edge_claimed"] is False
    assert summary["profitability_claimed"] is False


def test_adversarial_portfolio_ownership_cases_fail_closed_without_network():
    clean = _offline_snapshot()
    duplicate_order = clean.known_orders + (clean.known_orders[0],)

    cases = [
        replace(clean, fill_activities=tuple(item for item in clean.fill_activities if item.get("symbol") != "NVDA")),
        replace(clean, positions=tuple(item for item in clean.positions if item.get("symbol") != "AMZN")),
        replace(clean, open_orders=({"id": "open-1", "symbol": "QQQ", "status": "new"},)),
        replace(clean, known_orders=duplicate_order),
        replace(clean, known_orders=tuple({**item, "client_order_id": "wrong"} if item.get("symbol") == "TSLA" else item for item in clean.known_orders)),
        replace(clean, known_orders=tuple({**item, "filled_qty": "0.000001"} if item.get("symbol") == "SPY" else item for item in clean.known_orders)),
        replace(clean, local_runtime_flat_assumption=True),
        replace(clean, live_reservation_lifecycle_activated=True),
        replace(clean, production_exposure_mutated=True),
        replace(clean, economics_veto_activated=True),
    ]

    for snapshot in cases:
        with pytest.raises(AssertionError):
            reconcile_portfolio_ownership(snapshot)

    summary = reconcile_portfolio_ownership(_offline_snapshot(positions=clean.positions + ({"symbol": "IBM", "qty": "1"},)))
    assert summary["extra_positions"] == ("IBM",)
    assert all(item["fee_missing_gap"] is True for item in summary["known_order_results"])


def test_alpaca_26c_client_rejects_mutation_live_endpoint_and_unknown_direct_orders_without_network():
    client = AlpacaPaperReadOnlyClient(EXPECTED_PAPER_BASE_URL, "key", "secret")

    client._validate_get("/v2/account", None)
    client._validate_get("/v2/orders", {"status": "open"})
    client._validate_get("/v2/orders/b47cdef4-a913-4517-9cac-5d96f319de91", None)
    with pytest.raises(AssertionError):
        client.request_json("POST", "/v2/orders", payload={"symbol": "AAPL"})
    with pytest.raises(AssertionError):
        client.request_json("DELETE", "/v2/orders/b47cdef4-a913-4517-9cac-5d96f319de91")
    with pytest.raises(AssertionError):
        client.request_json("PATCH", "/v2/orders/b47cdef4-a913-4517-9cac-5d96f319de91")
    with pytest.raises(AssertionError):
        client._validate_get("/v2/orders/not-allowlisted", None)
    with pytest.raises(AssertionError):
        client._validate_get("/v2/orders", {"status": "all"})
    with pytest.raises(AssertionError):
        AlpacaPaperReadOnlyClient(FORBIDDEN_LIVE_BASE_URL, "key", "secret")._validate_get("/v2/account", None)


def test_real_alpaca_paper_portfolio_ownership_reconciliation_get_only_if_env_network_available():
    base_url, key_id, secret_key = _env_or_skip()
    client = AlpacaPaperReadOnlyClient(base_url, key_id, secret_key)

    account = client.get_json("/v2/account")
    clock = client.get_json("/v2/clock")
    positions = client.get_json("/v2/positions")
    open_orders = client.get_json("/v2/orders", {"status": "open", "limit": "100", "nested": "false"})
    activities = _normalize_activities(client.get_json("/v2/account/activities", {"activity_types": "FILL", "page_size": "100"}))
    known_orders = tuple(client.get_json(f"/v2/orders/{fill.broker_order_id}") for fill in KNOWN_FILLS)

    assert clock.get("timestamp") or "is_open" in clock
    snapshot = PortfolioOwnership(
        account=account if isinstance(account, dict) else {},
        positions=tuple(positions if isinstance(positions, list) else ()),
        open_orders=tuple(open_orders if isinstance(open_orders, list) else ()),
        known_orders=known_orders,
        fill_activities=activities,
        receive_ts_ns=now_ns(),
    )
    summary = reconcile_portfolio_ownership(snapshot)

    assert all(method == "GET" for method, _path in client.calls)
    assert not any(path.lower().endswith("/cancel") or "replace" in path.lower() for _method, path in client.calls)
    assert summary["account_status"] == "ACTIVE"
    assert summary["open_orders_count"] == 0
    assert set(summary["expected_positions_present"]) >= set(EXPECTED_POSITION_SYMBOLS)
    assert len(summary["known_order_results"]) == 7
    assert {item["symbol"] for item in summary["known_order_results"]} == set(EXPECTED_POSITION_SYMBOLS)
    assert summary["skipped_symbols"]["AMD"] == "reason_not_emitted_by_existing_26b_harness"

    positions_summary = {
        symbol: {
            "qty": position.get("qty"),
            "market_value": position.get("market_value"),
            "avg_entry_price": position.get("avg_entry_price"),
            "side": position.get("side"),
            "current_price": position.get("current_price"),
        }
        for symbol, position in _position_by_symbol(snapshot.positions).items()
        if symbol in EXPECTED_POSITION_SYMBOLS
    }
    print(
        "ALPACA_26C_PORTFOLIO_SUMMARY="
        + json.dumps(
            {
                "account_status": summary["account_status"],
                "currency": summary["currency"],
                "cash": summary["cash"],
                "buying_power": summary["buying_power"],
                "equity": summary["equity"],
                "portfolio_value": summary["portfolio_value"],
                "open_orders_count": summary["open_orders_count"],
                "positions_count": summary["positions_count"],
                "positions": positions_summary,
                "extra_positions": summary["extra_positions"],
                "known_order_results": summary["known_order_results"],
                "skipped_symbols": summary["skipped_symbols"],
                "gross_filled_notional_total": summary["gross_filled_notional_total"],
                "gaps": summary["gaps"],
                "readiness": summary["readiness"],
            },
            sort_keys=True,
        )
    )
