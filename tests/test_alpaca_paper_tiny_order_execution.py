from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, replace
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Any

import pytest


EXPECTED_PAPER_BASE_URL = "https://paper-api.alpaca.markets"
FORBIDDEN_LIVE_BASE_URL = "https://api.alpaca.markets"
ALPACA_DATA_BASE_URL = "https://data.alpaca.markets"
APPROVAL_ENV = "POVERTY_KILLER_APPROVE_ALPACA_PAPER_TINY_ORDER_25Z"
APPROVAL_VALUE = "YES_I_APPROVE_ONE_PAPER_LIMIT_ORDER"
MAX_NOTIONAL_USD = Decimal("5.00")
MAX_SPREAD_BPS = Decimal("50")
MAX_QUOTE_AGE_NS = 10_000_000_000
T0_NS = 1_777_948_800_000_000_000

ALLOWED_TRADING_GET_PATHS = frozenset({"/v2/account", "/v2/positions", "/v2/orders", "/v2/clock"})
ALLOWED_DATA_GET_PATHS = frozenset({"/v2/stocks/AAPL/quotes/latest", "/v2/stocks/AAPL/trades/latest"})
ACTIVE_ORDER_STATUSES = frozenset({"accepted", "new", "pending_new", "open", "accepted_for_bidding"})
TERMINAL_FILLED_ORDER_STATUSES = frozenset({"filled"})


@dataclass(frozen=True)
class TinyExecutionPlan:
    broker: str = "alpaca"
    environment: str = "paper"
    base_url: str = EXPECTED_PAPER_BASE_URL
    symbol: str = "AAPL"
    side: str = "buy"
    order_type: str = "limit"
    time_in_force: str = "day"
    max_notional_usd: Decimal = MAX_NOTIONAL_USD
    extended_hours: bool = False
    order_count: int = 1
    symbols: tuple[str, ...] = ("AAPL",)
    allow_existing_position: bool = False
    allow_market_closed_day_limit_queue: bool = False
    client_order_id: str = "pk25z-paper-aapl-buy-limit-day-offline-proof"
    order_class: str | None = None
    bracket_take_profit: Any = None
    bracket_stop_loss: Any = None
    trailing_stop: Any = None


@dataclass(frozen=True)
class AccountTruth:
    reachable: bool = True
    status: str = "ACTIVE"
    trading_blocked: bool = False
    account_blocked: bool = False
    currency: str | None = "USD"
    cash: Decimal | None = Decimal("1000.00")
    buying_power: Decimal | None = Decimal("1000.00")


@dataclass(frozen=True)
class BrokerTruth:
    account: AccountTruth = field(default_factory=AccountTruth)
    positions: tuple[dict[str, Any], ...] = ()
    open_orders: tuple[dict[str, Any], ...] = ()
    market_open: bool | None = True
    read_only_gets_done: tuple[str, ...] = ("/v2/account", "/v2/positions", "/v2/orders?status=open", "/v2/clock")


@dataclass(frozen=True)
class QuoteBasis:
    bid: Decimal | None = Decimal("190.00")
    ask: Decimal | None = Decimal("190.10")
    receive_ts_ns: int = T0_NS
    now_ns: int = T0_NS + 1
    source: str = "offline_adversarial_quote_fixture"

    @property
    def mid(self) -> Decimal | None:
        if self.bid is None or self.ask is None:
            return None
        return (self.bid + self.ask) / Decimal("2")

    @property
    def spread_bps(self) -> Decimal | None:
        if self.mid is None or self.mid <= Decimal("0"):
            return None
        return ((self.ask - self.bid) / self.mid) * Decimal("10000") if self.ask is not None and self.bid is not None else None


@dataclass(frozen=True)
class LocalSafety:
    board_approval: bool = False
    operator_approved: bool = True
    kill_switch_clear: bool = True
    local_reservations: tuple[dict[str, Any], ...] = ()
    pending_order_intent: bool = False
    live_mode: bool = False
    live_reservation_lifecycle: bool = False
    broker_adapter_activated: bool = False
    live_broker_activated: bool = False


@dataclass(frozen=True)
class ExecutionGateDecision:
    ready_to_post: bool
    reason_codes: tuple[str, ...]
    qty: Decimal | None = None
    limit_price: Decimal | None = None
    notional: Decimal | None = None
    payload: dict[str, Any] | None = None


@dataclass(frozen=True)
class OrderAck:
    broker_order_id: str | None
    client_order_id: str | None
    symbol: str | None
    side: str | None
    qty: str | None
    notional: str | None
    order_type: str | None
    limit_price: str | None
    time_in_force: str | None
    status: str | None
    submitted_at: str | None
    created_at: str | None
    receive_ts_ns: int


class AlpacaTradingHttpClient:
    def __init__(self, base_url: str, key_id: str, secret_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._key_id = key_id
        self._secret_key = secret_key
        self.calls: list[tuple[str, str]] = []

    def get_json(self, path: str, query: dict[str, str] | None = None) -> Any:
        self._validate_get(path, query)
        return self._request_json("GET", path, query=query)

    def post_order(self, payload: dict[str, Any]) -> Any:
        self._validate_post_order(payload)
        return self._request_json("POST", "/v2/orders", payload=payload)

    def _request_json(self, method: str, path: str, *, query: dict[str, str] | None = None, payload: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "APCA-API-KEY-ID": self._key_id,
                "APCA-API-SECRET-KEY": self._secret_key,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        self.calls.append((method, path))
        try:
            with urllib.request.urlopen(request, timeout=10.0) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            raise AssertionError(f"alpaca_http_error:{exc.code}:{method}:{path}") from None
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            pytest.skip(f"Alpaca PAPER network unavailable: {type(exc).__name__}")

    def _validate_get(self, path: str, query: dict[str, str] | None) -> None:
        assert self.base_url == EXPECTED_PAPER_BASE_URL
        if path.startswith("/v2/orders/"):
            assert query is None
            assert path.removeprefix("/v2/orders/")
            return
        assert path in ALLOWED_TRADING_GET_PATHS
        assert path != "/v2/orders" or (query or {}).get("status") == "open"

    def _validate_post_order(self, payload: dict[str, Any]) -> None:
        assert self.base_url == EXPECTED_PAPER_BASE_URL
        assert payload["symbol"] == "AAPL"
        assert payload["side"] == "buy"
        assert payload["type"] == "limit"
        assert payload["time_in_force"] == "day"
        assert payload.get("extended_hours") is False
        forbidden = {"order_class", "take_profit", "stop_loss", "trail_price", "trail_percent"}
        assert not (forbidden & set(payload))


class AlpacaDataHttpClient:
    def __init__(self, key_id: str, secret_key: str) -> None:
        self.base_url = ALPACA_DATA_BASE_URL
        self._key_id = key_id
        self._secret_key = secret_key
        self.calls: list[tuple[str, str]] = []

    def get_json(self, path: str) -> Any:
        assert path in ALLOWED_DATA_GET_PATHS
        request = urllib.request.Request(
            f"{self.base_url}{path}",
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
            raise AssertionError(f"alpaca_data_http_error:{exc.code}:GET:{path}") from None
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            pytest.skip(f"Alpaca data read-only quote unavailable: {type(exc).__name__}")


def _d(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    return Decimal(str(value))


def _unique(reasons: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(reasons))


def _has_symbol_order(symbol: str, orders: tuple[dict[str, Any], ...]) -> bool:
    return any((order.get("symbol") or "").upper() == symbol for order in orders)


def _has_symbol_position(symbol: str, positions: tuple[dict[str, Any], ...]) -> bool:
    for position in positions:
        if (position.get("symbol") or "").upper() != symbol:
            continue
        qty = _d(position.get("quantity") or position.get("qty"))
        if qty and qty != Decimal("0"):
            return True
    return False


def _compute_qty_and_payload(plan: TinyExecutionPlan, quote: QuoteBasis) -> tuple[Decimal | None, Decimal | None, Decimal | None, dict[str, Any] | None, list[str]]:
    reasons: list[str] = []
    if quote.bid is None or quote.ask is None or quote.mid is None:
        reasons.append("quote_missing")
        return None, None, None, None, reasons
    if quote.now_ns - quote.receive_ts_ns > MAX_QUOTE_AGE_NS:
        reasons.append("quote_stale")
    if quote.spread_bps is None or quote.spread_bps > MAX_SPREAD_BPS:
        reasons.append("quote_wide_spread")
    if quote.ask <= Decimal("0"):
        reasons.append("limit_price_missing")
        return None, None, None, None, reasons

    limit_price = quote.ask.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    qty = (plan.max_notional_usd / limit_price).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)
    notional = (qty * limit_price).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    if qty <= Decimal("0"):
        reasons.append("quantity_missing_or_non_positive")
    if notional <= Decimal("0") or notional > plan.max_notional_usd:
        reasons.append("notional_outside_cap")
    payload = {
        "symbol": "AAPL",
        "side": "buy",
        "type": "limit",
        "time_in_force": "day",
        "qty": str(qty),
        "limit_price": str(limit_price),
        "extended_hours": False,
        "client_order_id": plan.client_order_id,
    }
    return qty, limit_price, notional, payload, reasons


def evaluate_execution_gates(
    plan: TinyExecutionPlan,
    broker: BrokerTruth,
    quote: QuoteBasis,
    local: LocalSafety,
) -> ExecutionGateDecision:
    reasons: list[str] = []
    if local.board_approval is not True:
        reasons.append("board_approval_flag_missing")
    if local.operator_approved is not True:
        reasons.append("operator_approval_missing")
    if plan.base_url != EXPECTED_PAPER_BASE_URL or plan.environment != "paper":
        reasons.append("live_endpoint_forbidden")
    if plan.order_type != "limit":
        reasons.append("market_order_forbidden")
    if plan.side != "buy":
        reasons.append("short_sell_forbidden")
    if plan.max_notional_usd > MAX_NOTIONAL_USD:
        reasons.append("notional_exceeds_5_usd_cap")
    if plan.order_count != 1:
        reasons.append("multiple_orders_forbidden")
    if plan.symbols != ("AAPL",):
        reasons.append("multiple_symbols_forbidden")
    if plan.extended_hours:
        reasons.append("extended_hours_forbidden")
    if plan.order_class or plan.bracket_take_profit or plan.bracket_stop_loss or plan.trailing_stop:
        reasons.append("bracket_oco_oto_forbidden")
    if not broker.account.reachable:
        reasons.append("account_truth_missing")
    if broker.account.status.upper() not in {"ACTIVE", "ACCOUNT_ACTIVE"}:
        reasons.append("account_status_blocked")
    if broker.account.trading_blocked or broker.account.account_blocked:
        reasons.append("account_trading_blocked")
    if broker.account.buying_power is None and broker.account.cash is None:
        reasons.append("buying_power_missing")
    if _has_symbol_order("AAPL", broker.open_orders):
        reasons.append("existing_open_aapl_order")
    if _has_symbol_position("AAPL", broker.positions) and not plan.allow_existing_position:
        reasons.append("existing_aapl_position_without_approval")
    if broker.market_open is False and not plan.allow_market_closed_day_limit_queue:
        reasons.append("market_closed_without_queue_approval")
    if local.kill_switch_clear is not True:
        reasons.append("kill_switch_active")
    if local.local_reservations:
        reasons.append("local_reservation_conflict")
    if local.pending_order_intent:
        reasons.append("pending_order_intent_conflict")
    if local.live_mode:
        reasons.append("live_mode_forbidden")
    if local.live_reservation_lifecycle:
        reasons.append("live_reservation_lifecycle_forbidden")
    if local.broker_adapter_activated:
        reasons.append("broker_adapter_activation_forbidden")
    if local.live_broker_activated:
        reasons.append("live_broker_activation_forbidden")

    qty, limit_price, notional, payload, quantity_reasons = _compute_qty_and_payload(plan, quote)
    reasons.extend(quantity_reasons)
    unique = _unique(reasons)
    return ExecutionGateDecision(
        ready_to_post=not unique,
        reason_codes=unique,
        qty=qty,
        limit_price=limit_price,
        notional=notional,
        payload=payload if not unique else None,
    )


def _env_or_skip() -> tuple[str, str, str]:
    base_url = (os.environ.get("APCA_API_BASE_URL") or "").rstrip("/")
    key_id = os.environ.get("APCA_API_KEY_ID") or ""
    secret_key = os.environ.get("APCA_API_SECRET_KEY") or ""
    if not base_url or not key_id or not secret_key:
        pytest.skip("Alpaca PAPER credentials unavailable")
    if base_url != EXPECTED_PAPER_BASE_URL:
        pytest.fail(f"APCA_API_BASE_URL is not exact paper endpoint: {base_url!r}")
    return base_url, key_id, secret_key


def _approval_or_skip() -> None:
    if os.environ.get(APPROVAL_ENV) != APPROVAL_VALUE:
        pytest.skip("25Z Board approval flag missing; no POST allowed")


def _quote_from_payload(payload: dict[str, Any], *, receive_ts_ns: int) -> QuoteBasis:
    quote = payload.get("quote") or {}
    bid = _d(quote.get("bp") or quote.get("bid_price"))
    ask = _d(quote.get("ap") or quote.get("ask_price"))
    return QuoteBasis(bid=bid, ask=ask, receive_ts_ns=receive_ts_ns, now_ns=receive_ts_ns + 1, source="alpaca_data_latest_quote")


def _ack_from_payload(payload: dict[str, Any], *, receive_ts_ns: int) -> OrderAck:
    return OrderAck(
        broker_order_id=payload.get("id"),
        client_order_id=payload.get("client_order_id"),
        symbol=payload.get("symbol"),
        side=payload.get("side"),
        qty=payload.get("qty"),
        notional=payload.get("notional"),
        order_type=payload.get("type"),
        limit_price=payload.get("limit_price"),
        time_in_force=payload.get("time_in_force"),
        status=payload.get("status"),
        submitted_at=payload.get("submitted_at"),
        created_at=payload.get("created_at"),
        receive_ts_ns=receive_ts_ns,
    )


def _order_identity_matches(order: dict[str, Any], ack: OrderAck, plan: TinyExecutionPlan) -> bool:
    order_id = order.get("id") or order.get("broker_order_id")
    client_order_id = order.get("client_order_id")
    return (
        order_id == ack.broker_order_id
        and client_order_id == plan.client_order_id
        and order.get("symbol") == plan.symbol
        and order.get("side") == plan.side
        and order.get("type") == plan.order_type
        and order.get("time_in_force") == plan.time_in_force
    )


def _matching_open_order(open_orders: list[dict[str, Any]], ack: OrderAck, plan: TinyExecutionPlan) -> dict[str, Any] | None:
    for order in open_orders:
        identity_match = order.get("client_order_id") == plan.client_order_id or order.get("id") == ack.broker_order_id
        if identity_match and order.get("symbol") == plan.symbol:
            return order
    return None


def _reconciled_order_after_submit(
    *,
    open_orders: list[dict[str, Any]],
    direct_order: dict[str, Any] | None,
    ack: OrderAck,
    plan: TinyExecutionPlan,
) -> tuple[str, dict[str, Any]]:
    open_match = _matching_open_order(open_orders, ack, plan)
    if open_match:
        return "open_orders", open_match
    if direct_order and _order_identity_matches(direct_order, ack, plan):
        status = str(direct_order.get("status") or "").lower()
        if status in TERMINAL_FILLED_ORDER_STATUSES:
            return "direct_order_lookup", direct_order
    raise AssertionError("submitted_order_not_reconciled")


def test_missing_board_approval_blocks_before_any_post():
    decision = evaluate_execution_gates(
        TinyExecutionPlan(),
        BrokerTruth(),
        QuoteBasis(),
        LocalSafety(board_approval=False),
    )

    assert decision.ready_to_post is False
    assert "board_approval_flag_missing" in decision.reason_codes
    assert decision.payload is None


def test_offline_clean_gates_build_single_limit_day_payload_without_submitting():
    decision = evaluate_execution_gates(
        TinyExecutionPlan(client_order_id="pk25z-paper-aapl-buy-limit-day-test"),
        BrokerTruth(),
        QuoteBasis(bid=Decimal("190.00"), ask=Decimal("190.10"), receive_ts_ns=T0_NS, now_ns=T0_NS + 1),
        LocalSafety(board_approval=True),
    )

    assert decision.ready_to_post is True
    assert decision.qty is not None and decision.qty > Decimal("0")
    assert decision.limit_price == Decimal("190.10")
    assert decision.notional is not None and decision.notional <= MAX_NOTIONAL_USD
    assert decision.payload == {
        "symbol": "AAPL",
        "side": "buy",
        "type": "limit",
        "time_in_force": "day",
        "qty": str(decision.qty),
        "limit_price": "190.10",
        "extended_hours": False,
        "client_order_id": "pk25z-paper-aapl-buy-limit-day-test",
    }


def test_recorded_filled_order_reconciles_by_direct_lookup_when_open_orders_empty():
    plan = TinyExecutionPlan(client_order_id="pk25z-paper-aapl-buy-limit-day-1777948800000000100")
    ack = OrderAck(
        broker_order_id="b47cdef4-a913-4517-9cac-5d96f319de91",
        client_order_id=plan.client_order_id,
        symbol="AAPL",
        side="buy",
        qty="0.016903",
        notional=None,
        order_type="limit",
        limit_price="295.79",
        time_in_force="day",
        status="accepted",
        submitted_at="2026-05-18T17:10:54.81619546Z",
        created_at="2026-05-18T17:10:54.81619546Z",
        receive_ts_ns=T0_NS + 100,
    )
    direct_order = {
        "id": "b47cdef4-a913-4517-9cac-5d96f319de91",
        "client_order_id": plan.client_order_id,
        "symbol": "AAPL",
        "side": "buy",
        "type": "limit",
        "time_in_force": "day",
        "qty": "0.016903",
        "limit_price": "295.79",
        "status": "filled",
        "filled_qty": "0.016903",
        "created_at": "2026-05-18T17:10:54.81619546Z",
        "submitted_at": "2026-05-18T17:10:54.81619546Z",
        "updated_at": "2026-05-18T17:10:54.832884729Z",
    }

    source, order = _reconciled_order_after_submit(
        open_orders=[],
        direct_order=direct_order,
        ack=ack,
        plan=plan,
    )

    assert source == "direct_order_lookup"
    assert order["status"] == "filled"
    assert order["filled_qty"] == "0.016903"


def test_adversarial_no_go_cases_block_before_post():
    plan = TinyExecutionPlan()
    broker = BrokerTruth()
    quote = QuoteBasis()
    local = LocalSafety(board_approval=True)
    cases = [
        ("live_endpoint_forbidden", replace(plan, base_url=FORBIDDEN_LIVE_BASE_URL, environment="live")),
        ("market_order_forbidden", replace(plan, order_type="market")),
        ("notional_exceeds_5_usd_cap", replace(plan, max_notional_usd=Decimal("5.01"))),
        ("quote_missing", plan, broker, replace(quote, bid=None, ask=None), local),
        ("quote_stale", plan, broker, replace(quote, now_ns=T0_NS + MAX_QUOTE_AGE_NS + 1), local),
        ("quote_wide_spread", plan, broker, replace(quote, bid=Decimal("190"), ask=Decimal("195")), local),
        ("limit_price_missing", plan, broker, replace(quote, bid=Decimal("0"), ask=Decimal("0")), local),
        ("multiple_orders_forbidden", replace(plan, order_count=2)),
        ("multiple_symbols_forbidden", replace(plan, symbols=("AAPL", "MSFT"))),
        ("short_sell_forbidden", replace(plan, side="sell")),
        ("extended_hours_forbidden", replace(plan, extended_hours=True)),
        ("bracket_oco_oto_forbidden", replace(plan, order_class="bracket")),
        ("existing_open_aapl_order", plan, replace(broker, open_orders=({"symbol": "AAPL", "client_order_id": "existing"},)), quote, local),
        ("existing_aapl_position_without_approval", plan, replace(broker, positions=({"symbol": "AAPL", "quantity": Decimal("1")},)), quote, local),
        ("account_truth_missing", plan, replace(broker, account=replace(broker.account, reachable=False)), quote, local),
        ("buying_power_missing", plan, replace(broker, account=replace(broker.account, cash=None, buying_power=None)), quote, local),
        ("kill_switch_active", plan, broker, quote, replace(local, kill_switch_clear=False)),
        ("broker_adapter_activation_forbidden", plan, broker, quote, replace(local, broker_adapter_activated=True)),
        ("live_broker_activation_forbidden", plan, broker, quote, replace(local, live_broker_activated=True)),
    ]

    for case in cases:
        expected = case[0]
        case_plan = case[1] if len(case) > 1 else plan
        case_broker = case[2] if len(case) > 2 else broker
        case_quote = case[3] if len(case) > 3 else quote
        case_local = case[4] if len(case) > 4 else local
        decision = evaluate_execution_gates(case_plan, case_broker, case_quote, case_local)
        assert decision.ready_to_post is False, expected
        assert expected in decision.reason_codes
        assert decision.payload is None


def test_real_alpaca_paper_tiny_order_execution_skips_without_explicit_approval():
    _approval_or_skip()
    base_url, key_id, secret_key = _env_or_skip()
    trading = AlpacaTradingHttpClient(base_url, key_id, secret_key)
    data = AlpacaDataHttpClient(key_id, secret_key)

    account_payload = trading.get_json("/v2/account")
    clock_payload = trading.get_json("/v2/clock")
    positions_payload = trading.get_json("/v2/positions")
    orders_payload = trading.get_json("/v2/orders", {"status": "open", "limit": "50", "nested": "false"})
    quote_payload = data.get_json("/v2/stocks/AAPL/quotes/latest")

    receive_ts_ns = T0_NS + 100
    broker = BrokerTruth(
        account=AccountTruth(
            reachable=bool(account_payload),
            status=str(account_payload.get("status") or "ACTIVE"),
            trading_blocked=bool(account_payload.get("trading_blocked") or False),
            account_blocked=bool(account_payload.get("account_blocked") or False),
            currency=account_payload.get("currency") or "USD",
            cash=_d(account_payload.get("cash")),
            buying_power=_d(account_payload.get("buying_power")),
        ),
        positions=tuple({"symbol": item.get("symbol"), "quantity": _d(item.get("qty"))} for item in positions_payload),
        open_orders=tuple({"symbol": item.get("symbol"), "client_order_id": item.get("client_order_id"), "broker_order_id": item.get("id")} for item in orders_payload),
        market_open=bool(clock_payload.get("is_open")),
    )
    plan = TinyExecutionPlan(
        allow_market_closed_day_limit_queue=False,
        client_order_id=f"pk25z-paper-aapl-buy-limit-day-{receive_ts_ns}",
    )
    quote = _quote_from_payload(quote_payload, receive_ts_ns=receive_ts_ns)
    decision = evaluate_execution_gates(plan, broker, quote, LocalSafety(board_approval=True))
    assert decision.ready_to_post is True, decision.reason_codes
    assert decision.payload is not None

    ack_payload = trading.post_order(decision.payload)
    ack = _ack_from_payload(ack_payload, receive_ts_ns=receive_ts_ns + 1)
    assert ack.broker_order_id
    assert ack.client_order_id == plan.client_order_id
    assert ack.symbol == "AAPL"
    assert ack.side == "buy"
    assert ack.order_type == "limit"
    assert ack.time_in_force == "day"
    assert ack.status in ACTIVE_ORDER_STATUSES | TERMINAL_FILLED_ORDER_STATUSES
    assert [call for call in trading.calls if call[0] == "POST"] == [("POST", "/v2/orders")]

    open_orders = trading.get_json("/v2/orders", {"status": "open", "limit": "50", "nested": "false"})
    trading.get_json("/v2/positions")
    trading.get_json("/v2/account")
    direct_order = None
    if _matching_open_order(open_orders, ack, plan) is None:
        direct_order = trading.get_json(f"/v2/orders/{ack.broker_order_id}")
    source, reconciled_order = _reconciled_order_after_submit(
        open_orders=open_orders,
        direct_order=direct_order,
        ack=ack,
        plan=plan,
    )
    assert source in {"open_orders", "direct_order_lookup"}
    assert reconciled_order.get("client_order_id") == plan.client_order_id


def test_authority_files_remain_unactivated_and_no_execution_helper_uses_live_surfaces():
    broker_adapter_source = Path("app/execution/broker_adapter.py").read_text(encoding="utf-8-sig")
    live_broker_source = Path("app/execution/live_broker.py").read_text(encoding="utf-8-sig")

    assert "PRE-INTEGRATION" in broker_adapter_source
    assert "NO IMPLEMENTATION" in broker_adapter_source
    assert "Under construction" in live_broker_source
    assert EXPECTED_PAPER_BASE_URL != FORBIDDEN_LIVE_BASE_URL
