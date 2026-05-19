from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, replace
from decimal import Decimal, ROUND_DOWN
from typing import Any

import pytest

from app.utils.time_utils import now_ns


EXPECTED_PAPER_BASE_URL = "https://paper-api.alpaca.markets"
FORBIDDEN_LIVE_BASE_URL = "https://api.alpaca.markets"
ALPACA_DATA_BASE_URL = "https://data.alpaca.markets"
APPROVAL_ENV = "POVERTY_KILLER_APPROVE_ALPACA_PAPER_10_SYMBOL_BATCH_26B"
APPROVAL_VALUE = "YES_I_APPROVE_10_PAPER_LIMIT_ORDERS"
SYMBOLS = ("AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AMD", "SPY", "QQQ")
MAX_NOTIONAL_PER_SYMBOL = Decimal("5.00")
MAX_SPREAD_BPS = Decimal("50")
MAX_QUOTE_AGE_NS = 10_000_000_000
T0_NS = 1_777_948_800_000_000_000
ACTIVE_ORDER_STATUSES = frozenset({"accepted", "new", "pending_new", "open", "accepted_for_bidding"})
TERMINAL_STATUSES = frozenset({"filled", "canceled", "expired", "rejected"})
ALLOWED_TRADING_GET_PATHS = frozenset({"/v2/account", "/v2/positions", "/v2/orders", "/v2/clock", "/v2/account/activities"})


@dataclass(frozen=True)
class AccountTruth:
    reachable: bool = True
    status: str = "ACTIVE"
    trading_blocked: bool = False
    account_blocked: bool = False
    cash: Decimal | None = Decimal("1000.00")
    buying_power: Decimal | None = Decimal("1000.00")


@dataclass(frozen=True)
class BrokerTruth:
    account: AccountTruth = field(default_factory=AccountTruth)
    positions: tuple[dict[str, Any], ...] = ()
    open_orders: tuple[dict[str, Any], ...] = ()
    market_open: bool | None = True


@dataclass(frozen=True)
class QuoteBasis:
    bid: Decimal | None = Decimal("100.00")
    ask: Decimal | None = Decimal("100.05")
    receive_ts_ns: int = T0_NS
    now_ns: int = T0_NS + 1
    source: str = "offline_batch_quote_fixture"

    @property
    def mid(self) -> Decimal | None:
        if self.bid is None or self.ask is None:
            return None
        return (self.bid + self.ask) / Decimal("2")

    @property
    def spread_bps(self) -> Decimal | None:
        if self.mid is None or self.mid <= Decimal("0") or self.bid is None or self.ask is None:
            return None
        return ((self.ask - self.bid) / self.mid) * Decimal("10000")


@dataclass(frozen=True)
class BatchPlan:
    base_url: str = EXPECTED_PAPER_BASE_URL
    environment: str = "paper"
    symbols: tuple[str, ...] = SYMBOLS
    side: str = "buy"
    order_type: str = "limit"
    time_in_force: str = "day"
    max_notional_usd_per_symbol: Decimal = MAX_NOTIONAL_PER_SYMBOL
    extended_hours: bool = False
    allow_existing_positions: bool = False
    retry_enabled: bool = False
    auto_resubmit_enabled: bool = False
    cancel_attempted: bool = False
    replace_attempted: bool = False
    economics_veto_activated: bool = False
    broker_adapter_activated: bool = False
    live_broker_activated: bool = False
    live_mode: bool = False
    live_reservation_lifecycle: bool = False


@dataclass(frozen=True)
class SymbolPlanResult:
    symbol: str
    classification: str
    reason_codes: tuple[str, ...] = ()
    payload: dict[str, Any] | None = None
    qty: Decimal | None = None
    limit_price: Decimal | None = None
    estimated_notional: Decimal | None = None


@dataclass(frozen=True)
class BatchPlanResult:
    ready_to_submit: bool
    batch_reason_codes: tuple[str, ...]
    symbol_results: tuple[SymbolPlanResult, ...]

    @property
    def eligible_payloads(self) -> tuple[dict[str, Any], ...]:
        return tuple(result.payload for result in self.symbol_results if result.payload is not None)


class AlpacaBatchHttpClient:
    def __init__(self, base_url: str, key_id: str, secret_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._key_id = key_id
        self._secret_key = secret_key
        self.calls: list[tuple[str, str]] = []
        self._posted_symbols: set[str] = set()

    def get_json(self, path: str, query: dict[str, str] | None = None) -> Any:
        self._validate_get(path, query)
        return self._request_json("GET", path, query=query)

    def post_order(self, payload: dict[str, Any]) -> Any:
        self._validate_post_order(payload)
        symbol = payload["symbol"]
        assert symbol not in self._posted_symbols
        assert len(self._posted_symbols) < 10
        self._posted_symbols.add(symbol)
        return self._request_json("POST", "/v2/orders", payload=payload)

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Any:
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
            body = exc.read().decode("utf-8", errors="replace")
            return {"_broker_error": f"HTTP {exc.code}", "_broker_error_body": body[:180]}
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            if method == "POST":
                return {"_ambiguous_submit_error": type(exc).__name__}
            pytest.skip(f"Alpaca PAPER read-only network unavailable: {type(exc).__name__}")

    def _validate_get(self, path: str, query: dict[str, str] | None) -> None:
        assert self.base_url == EXPECTED_PAPER_BASE_URL
        if path.startswith("/v2/orders/"):
            suffix = path.removeprefix("/v2/orders/")
            assert suffix and "/" not in suffix
            assert query is None
            return
        assert path in ALLOWED_TRADING_GET_PATHS
        assert path != "/v2/orders" or (query or {}).get("status") == "open"

    def _validate_post_order(self, payload: dict[str, Any]) -> None:
        assert self.base_url == EXPECTED_PAPER_BASE_URL
        assert payload["symbol"] in SYMBOLS
        assert payload["side"] == "buy"
        assert payload["type"] == "limit"
        assert payload["time_in_force"] == "day"
        assert payload.get("extended_hours") is False
        assert Decimal(str(payload["qty"])) > Decimal("0")
        assert Decimal(str(payload["qty"])) * Decimal(str(payload["limit_price"])) <= MAX_NOTIONAL_PER_SYMBOL
        assert str(payload["client_order_id"]).startswith(f"pk26b-paper-batch-{payload['symbol'].lower()}-buy-limit-day-")
        forbidden = {"order_class", "take_profit", "stop_loss", "trail_price", "trail_percent"}
        assert not (forbidden & set(payload))


class AlpacaDataHttpClient:
    def __init__(self, key_id: str, secret_key: str) -> None:
        self.base_url = ALPACA_DATA_BASE_URL
        self._key_id = key_id
        self._secret_key = secret_key
        self.calls: list[tuple[str, str]] = []

    def get_latest_quote(self, symbol: str) -> Any:
        assert symbol in SYMBOLS
        path = f"/v2/stocks/{symbol}/quotes/latest"
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
            return {"_quote_error": f"HTTP {exc.code}"}
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            pytest.skip(f"Alpaca PAPER data read-only quote unavailable: {type(exc).__name__}")


def _d(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    return Decimal(str(value))


def _unique(reasons: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(reasons))


def _has_symbol_order(symbol: str, orders: tuple[dict[str, Any], ...]) -> bool:
    return any((order.get("symbol") or "").upper() == symbol and str(order.get("status") or "open").lower() in ACTIVE_ORDER_STATUSES for order in orders)


def _has_symbol_position(symbol: str, positions: tuple[dict[str, Any], ...]) -> bool:
    for position in positions:
        if (position.get("symbol") or "").upper() != symbol:
            continue
        qty = _d(position.get("quantity") or position.get("qty"))
        if qty and qty != Decimal("0"):
            return True
    return False


def _client_order_id(symbol: str, ts_ns: int) -> str:
    return f"pk26b-paper-batch-{symbol.lower()}-buy-limit-day-{ts_ns}"


def _symbol_payload(symbol: str, plan: BatchPlan, quote: QuoteBasis, *, ts_ns: int) -> tuple[dict[str, Any] | None, Decimal | None, Decimal | None, Decimal | None, list[str]]:
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
    qty = (plan.max_notional_usd_per_symbol / limit_price).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)
    estimated_notional = (qty * limit_price).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    if qty <= Decimal("0"):
        reasons.append("quantity_missing_or_non_positive")
    if estimated_notional <= Decimal("0") or estimated_notional > plan.max_notional_usd_per_symbol:
        reasons.append("notional_outside_cap")
    payload = {
        "symbol": symbol,
        "side": "buy",
        "type": "limit",
        "time_in_force": "day",
        "qty": str(qty),
        "limit_price": str(limit_price),
        "extended_hours": False,
        "client_order_id": _client_order_id(symbol, ts_ns),
    }
    return payload, qty, limit_price, estimated_notional, reasons


def evaluate_batch_plan(
    plan: BatchPlan,
    broker: BrokerTruth,
    quotes: dict[str, QuoteBasis],
    *,
    board_approval: bool,
    ts_ns: int = T0_NS,
) -> BatchPlanResult:
    batch_reasons: list[str] = []
    if not board_approval:
        batch_reasons.append("batch_approval_flag_missing")
    if plan.base_url != EXPECTED_PAPER_BASE_URL or plan.environment != "paper":
        batch_reasons.append("live_endpoint_forbidden")
    if len(plan.symbols) > 10:
        batch_reasons.append("more_than_ten_symbols_forbidden")
    if len(set(plan.symbols)) != len(plan.symbols):
        batch_reasons.append("multiple_orders_for_same_symbol_forbidden")
    if tuple(plan.symbols) != SYMBOLS:
        batch_reasons.append("symbol_replacement_or_override_forbidden")
    if plan.side != "buy":
        batch_reasons.append("short_sell_forbidden")
    if plan.order_type != "limit":
        batch_reasons.append("market_order_forbidden")
    if plan.time_in_force != "day":
        batch_reasons.append("time_in_force_forbidden")
    if plan.max_notional_usd_per_symbol > MAX_NOTIONAL_PER_SYMBOL:
        batch_reasons.append("notional_exceeds_5_usd_cap")
    if plan.extended_hours:
        batch_reasons.append("extended_hours_forbidden")
    if plan.retry_enabled:
        batch_reasons.append("retry_forbidden")
    if plan.auto_resubmit_enabled:
        batch_reasons.append("auto_resubmit_forbidden")
    if plan.cancel_attempted:
        batch_reasons.append("cancel_forbidden")
    if plan.replace_attempted:
        batch_reasons.append("replace_forbidden")
    if plan.economics_veto_activated:
        batch_reasons.append("economics_veto_activation_forbidden")
    if plan.broker_adapter_activated:
        batch_reasons.append("broker_adapter_activation_forbidden")
    if plan.live_broker_activated:
        batch_reasons.append("live_broker_activation_forbidden")
    if plan.live_mode:
        batch_reasons.append("live_mode_forbidden")
    if plan.live_reservation_lifecycle:
        batch_reasons.append("live_reservation_lifecycle_forbidden")
    if not broker.account.reachable:
        batch_reasons.append("account_truth_missing")
    if broker.account.status.upper() not in {"ACTIVE", "ACCOUNT_ACTIVE"}:
        batch_reasons.append("account_status_blocked")
    if broker.account.trading_blocked or broker.account.account_blocked:
        batch_reasons.append("account_trading_blocked")
    if broker.account.cash is None and broker.account.buying_power is None:
        batch_reasons.append("buying_power_missing")
    if broker.market_open is False:
        batch_reasons.append("market_closed_without_queue_approval")

    if batch_reasons:
        return BatchPlanResult(
            ready_to_submit=False,
            batch_reason_codes=_unique(batch_reasons),
            symbol_results=tuple(SymbolPlanResult(symbol=symbol, classification="submit_blocked", reason_codes=_unique(batch_reasons)) for symbol in plan.symbols),
        )

    symbol_results: list[SymbolPlanResult] = []
    for index, symbol in enumerate(plan.symbols):
        reasons: list[str] = []
        if _has_symbol_order(symbol, broker.open_orders):
            reasons.append("existing_open_order")
        if _has_symbol_position(symbol, broker.positions) and not plan.allow_existing_positions:
            reasons.append("existing_position_present")
        payload, qty, limit_price, estimated_notional, quantity_reasons = _symbol_payload(
            symbol,
            plan,
            quotes.get(symbol, QuoteBasis(bid=None, ask=None)),
            ts_ns=ts_ns + index,
        )
        reasons.extend(quantity_reasons)
        if reasons:
            if "existing_position_present" in reasons:
                classification = "skipped_existing_position"
            elif "existing_open_order" in reasons:
                classification = "skipped_existing_open_order"
            elif any(reason.startswith("quote_") or reason == "limit_price_missing" for reason in reasons):
                classification = "skipped_quote_unavailable"
            else:
                classification = "not_attempted_preflight_blocked"
            payload = None
        else:
            classification = "planned_eligible"
        symbol_results.append(
            SymbolPlanResult(
                symbol=symbol,
                classification=classification,
                reason_codes=_unique(reasons),
                payload=payload,
                qty=qty,
                limit_price=limit_price,
                estimated_notional=estimated_notional,
            )
        )

    return BatchPlanResult(
        ready_to_submit=any(result.payload is not None for result in symbol_results),
        batch_reason_codes=(),
        symbol_results=tuple(symbol_results),
    )


def _quote_from_payload(payload: dict[str, Any], *, receive_ts_ns: int) -> QuoteBasis:
    quote = payload.get("quote") or {}
    bid = _d(quote.get("bp") or quote.get("bid_price"))
    ask = _d(quote.get("ap") or quote.get("ask_price"))
    return QuoteBasis(bid=bid, ask=ask, receive_ts_ns=receive_ts_ns, now_ns=receive_ts_ns + 1, source="alpaca_data_latest_quote")


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
        pytest.skip("26B batch approval flag missing; no POST allowed")


def _classify_ack(ack: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    if ack.get("_ambiguous_submit_error"):
        return {"classification": "ambiguous_needs_reconciliation", "client_order_id": payload["client_order_id"], "symbol": payload["symbol"]}
    if ack.get("_broker_error"):
        return {"classification": "failed_broker_error", "client_order_id": payload["client_order_id"], "symbol": payload["symbol"], "broker_error": ack["_broker_error"]}
    status = str(ack.get("status") or "").lower()
    classification = "submitted_ack_open"
    if status == "filled":
        classification = "submitted_filled"
    elif status == "rejected":
        classification = "submitted_rejected"
    return {
        "classification": classification,
        "broker_order_id": ack.get("id"),
        "client_order_id": ack.get("client_order_id"),
        "symbol": ack.get("symbol"),
        "side": ack.get("side"),
        "qty": ack.get("qty"),
        "type": ack.get("type"),
        "limit_price": ack.get("limit_price"),
        "time_in_force": ack.get("time_in_force"),
        "status": ack.get("status"),
        "created_at": ack.get("created_at"),
        "submitted_at": ack.get("submitted_at"),
        "receive_ts_ns": now_ns(),
    }


def test_missing_26b_approval_blocks_entire_batch_before_any_post():
    result = evaluate_batch_plan(
        BatchPlan(),
        BrokerTruth(),
        {symbol: QuoteBasis() for symbol in SYMBOLS},
        board_approval=False,
    )

    assert result.ready_to_submit is False
    assert result.batch_reason_codes == ("batch_approval_flag_missing",)
    assert all(symbol_result.payload is None for symbol_result in result.symbol_results)


def test_offline_batch_plan_skips_existing_aapl_and_builds_bounded_payloads_for_remaining_symbols():
    broker = BrokerTruth(positions=({"symbol": "AAPL", "qty": "0.016903"},))
    result = evaluate_batch_plan(
        BatchPlan(),
        broker,
        {symbol: QuoteBasis(bid=Decimal("100.00"), ask=Decimal("100.05")) for symbol in SYMBOLS},
        board_approval=True,
    )

    by_symbol = {item.symbol: item for item in result.symbol_results}
    assert result.ready_to_submit is True
    assert by_symbol["AAPL"].classification == "skipped_existing_position"
    assert by_symbol["AAPL"].payload is None
    payloads = result.eligible_payloads
    assert len(payloads) == 9
    assert {payload["symbol"] for payload in payloads} == set(SYMBOLS) - {"AAPL"}
    for payload in payloads:
        assert payload["side"] == "buy"
        assert payload["type"] == "limit"
        assert payload["time_in_force"] == "day"
        assert payload["extended_hours"] is False
        assert Decimal(payload["qty"]) * Decimal(payload["limit_price"]) <= MAX_NOTIONAL_PER_SYMBOL
        assert payload["client_order_id"].startswith(f"pk26b-paper-batch-{payload['symbol'].lower()}-buy-limit-day-")
        assert not ({"order_class", "take_profit", "stop_loss", "trail_price", "trail_percent"} & set(payload))


def test_adversarial_batch_no_go_cases_fail_closed_before_post():
    plan = BatchPlan()
    broker = BrokerTruth()
    quotes = {symbol: QuoteBasis() for symbol in SYMBOLS}
    cases = [
        ("live_endpoint_forbidden", replace(plan, base_url=FORBIDDEN_LIVE_BASE_URL, environment="live"), broker, quotes),
        ("market_order_forbidden", replace(plan, order_type="market"), broker, quotes),
        ("notional_exceeds_5_usd_cap", replace(plan, max_notional_usd_per_symbol=Decimal("5.01")), broker, quotes),
        ("multiple_orders_for_same_symbol_forbidden", replace(plan, symbols=("AAPL", "AAPL") + SYMBOLS[2:]), broker, quotes),
        ("more_than_ten_symbols_forbidden", replace(plan, symbols=SYMBOLS + ("IBM",)), broker, quotes),
        ("retry_forbidden", replace(plan, retry_enabled=True), broker, quotes),
        ("auto_resubmit_forbidden", replace(plan, auto_resubmit_enabled=True), broker, quotes),
        ("cancel_forbidden", replace(plan, cancel_attempted=True), broker, quotes),
        ("replace_forbidden", replace(plan, replace_attempted=True), broker, quotes),
        ("economics_veto_activation_forbidden", replace(plan, economics_veto_activated=True), broker, quotes),
        ("broker_adapter_activation_forbidden", replace(plan, broker_adapter_activated=True), broker, quotes),
        ("live_broker_activation_forbidden", replace(plan, live_broker_activated=True), broker, quotes),
        ("live_mode_forbidden", replace(plan, live_mode=True), broker, quotes),
        ("live_reservation_lifecycle_forbidden", replace(plan, live_reservation_lifecycle=True), broker, quotes),
        ("existing_open_order", plan, replace(broker, open_orders=({"symbol": "MSFT", "status": "new"},)), quotes),
        ("existing_position_present", plan, replace(broker, positions=({"symbol": "NVDA", "qty": "1"},)), quotes),
        ("quote_missing", plan, broker, {**quotes, "AMZN": QuoteBasis(bid=None, ask=None)}),
        ("quote_stale", plan, broker, {**quotes, "META": QuoteBasis(now_ns=T0_NS + MAX_QUOTE_AGE_NS + 1)}),
        ("quantity_missing_or_non_positive", plan, broker, {**quotes, "GOOGL": QuoteBasis(bid=Decimal("0"), ask=Decimal("10000000"))}),
        ("limit_price_missing", plan, broker, {**quotes, "TSLA": QuoteBasis(bid=Decimal("0"), ask=Decimal("0"))}),
        ("quote_wide_spread", plan, broker, {**quotes, "AMD": QuoteBasis(bid=Decimal("100"), ask=Decimal("110"))}),
        ("market_closed_without_queue_approval", plan, replace(broker, market_open=False), quotes),
    ]

    for expected, case_plan, case_broker, case_quotes in cases:
        result = evaluate_batch_plan(case_plan, case_broker, case_quotes, board_approval=True)
        joined = set(result.batch_reason_codes)
        for symbol_result in result.symbol_results:
            joined.update(symbol_result.reason_codes)
        assert expected in joined, expected
        if expected in result.batch_reason_codes:
            assert all(symbol_result.payload is None for symbol_result in result.symbol_results)


def test_post_guard_rejects_duplicate_symbol_more_than_ten_live_endpoint_and_mutating_payloads():
    client = AlpacaBatchHttpClient(EXPECTED_PAPER_BASE_URL, "key", "secret")
    payload = {
        "symbol": "MSFT",
        "side": "buy",
        "type": "limit",
        "time_in_force": "day",
        "qty": "0.049975",
        "limit_price": "100.05",
        "extended_hours": False,
        "client_order_id": "pk26b-paper-batch-msft-buy-limit-day-1777948800000000000",
    }
    client._validate_post_order(payload)
    client._posted_symbols.add("MSFT")
    with pytest.raises(AssertionError):
        client.post_order(payload)
    with pytest.raises(AssertionError):
        AlpacaBatchHttpClient(FORBIDDEN_LIVE_BASE_URL, "key", "secret")._validate_get("/v2/account", None)
    with pytest.raises(AssertionError):
        client._validate_get("/v2/orders", {"status": "all"})
    with pytest.raises(AssertionError):
        client._validate_post_order({**payload, "symbol": "IBM"})
    with pytest.raises(AssertionError):
        client._validate_post_order({**payload, "order_class": "bracket"})
    with pytest.raises(AssertionError):
        client._validate_post_order({**payload, "qty": "1", "limit_price": "100.05"})


def test_real_alpaca_paper_10_symbol_batch_execution_skips_without_explicit_26b_approval():
    _approval_or_skip()
    base_url, key_id, secret_key = _env_or_skip()
    trading = AlpacaBatchHttpClient(base_url, key_id, secret_key)
    data = AlpacaDataHttpClient(key_id, secret_key)

    account_payload = trading.get_json("/v2/account")
    clock_payload = trading.get_json("/v2/clock")
    positions_payload = trading.get_json("/v2/positions")
    open_orders_payload = trading.get_json("/v2/orders", {"status": "open", "limit": "50", "nested": "false"})

    broker = BrokerTruth(
        account=AccountTruth(
            reachable=bool(account_payload),
            status=str(account_payload.get("status") or "ACTIVE"),
            trading_blocked=bool(account_payload.get("trading_blocked") or False),
            account_blocked=bool(account_payload.get("account_blocked") or False),
            cash=_d(account_payload.get("cash")),
            buying_power=_d(account_payload.get("buying_power")),
        ),
        positions=tuple({"symbol": item.get("symbol"), "qty": item.get("qty")} for item in positions_payload),
        open_orders=tuple({"symbol": item.get("symbol"), "status": item.get("status"), "client_order_id": item.get("client_order_id"), "id": item.get("id")} for item in open_orders_payload),
        market_open=bool(clock_payload.get("is_open")),
    )

    quote_receive_ts_ns = now_ns()
    quote_payloads = {symbol: data.get_latest_quote(symbol) for symbol in SYMBOLS}
    quotes = {
        symbol: _quote_from_payload(payload, receive_ts_ns=quote_receive_ts_ns + index)
        for index, (symbol, payload) in enumerate(quote_payloads.items())
        if not payload.get("_quote_error")
    }
    result = evaluate_batch_plan(BatchPlan(), broker, quotes, board_approval=True, ts_ns=quote_receive_ts_ns)
    if result.batch_reason_codes:
        assert [call for call in trading.calls if call[0] == "POST"] == []
        pytest.skip(f"26B batch blocked before POST: {result.batch_reason_codes}")
    if not result.ready_to_submit:
        assert [call for call in trading.calls if call[0] == "POST"] == []
        pytest.skip("26B batch has zero eligible symbols after preflight")

    acks = []
    for payload in result.eligible_payloads:
        ack = trading.post_order(payload)
        acks.append(_classify_ack(ack, payload))
    assert len([call for call in trading.calls if call[0] == "POST"]) == len(result.eligible_payloads)
    assert len({ack["client_order_id"] for ack in acks}) == len(acks)
    assert len({ack["symbol"] for ack in acks}) == len(acks)
    assert len(acks) <= 10

    open_orders_after = trading.get_json("/v2/orders", {"status": "open", "limit": "100", "nested": "false"})
    positions_after = trading.get_json("/v2/positions")
    account_after = trading.get_json("/v2/account")
    activities_after = trading.get_json("/v2/account/activities", {"activity_types": "FILL", "page_size": "100"})
    submitted_ids = [ack.get("broker_order_id") for ack in acks if ack.get("broker_order_id")]
    direct_orders = [trading.get_json(f"/v2/orders/{broker_order_id}") for broker_order_id in submitted_ids]

    summary = {
        "attempted_count": len(result.eligible_payloads),
        "submitted_count": len(acks),
        "filled_count": sum(1 for ack in acks if ack["classification"] == "submitted_filled"),
        "open_count": sum(1 for ack in acks if ack["classification"] == "submitted_ack_open"),
        "rejected_count": sum(1 for ack in acks if ack["classification"] == "submitted_rejected"),
        "ambiguous_count": sum(1 for ack in acks if ack["classification"] == "ambiguous_needs_reconciliation"),
        "skipped_count": sum(1 for item in result.symbol_results if item.payload is None),
        "open_orders_after": len(open_orders_after) if isinstance(open_orders_after, list) else None,
        "positions_after": len(positions_after) if isinstance(positions_after, list) else None,
        "activities_shape": "dict" if isinstance(activities_after, dict) else "list",
        "direct_order_lookups": len(direct_orders),
        "account_status_after": account_after.get("status") if isinstance(account_after, dict) else None,
    }
    print("ALPACA_26B_BATCH_SUMMARY=" + json.dumps(summary, sort_keys=True))
