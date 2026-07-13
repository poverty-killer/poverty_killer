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

from app.utils.time_utils import now_ns


EXPECTED_PAPER_BASE_URL = "https://paper-api.alpaca.markets"
FORBIDDEN_LIVE_BASE_URL = "https://api.alpaca.markets"
ALPACA_DATA_BASE_URL = "https://data.alpaca.markets"
APPROVAL_ENV_26G = "POVERTY_KILLER_APPROVE_ALPACA_PAPER_10_SYMBOL_EXPANSION_26G"
APPROVAL_VALUE_26G = "YES_I_APPROVE_10_MORE_ALPACA_PAPER_BUY_LIMIT_DAY_ORDERS_26G"
BROKER_READ_AUTH_ENV = "PK_BOARD_AUTHORIZED_PAPER_BROKER_READ"
BROKER_READ_AUTH_VALUE = "YES_D4_BOARD_AUTHORIZED"
OLD_APPROVAL_VALUES = {
    "POVERTY_KILLER_APPROVE_ALPACA_PAPER_TINY_ORDER_25Z": "YES_I_APPROVE_ONE_PAPER_LIMIT_ORDER",
    "POVERTY_KILLER_APPROVE_ALPACA_PAPER_10_SYMBOL_BATCH_26B": "YES_I_APPROVE_10_PAPER_LIMIT_ORDERS",
}
CANDIDATE_SYMBOLS = ("JPM", "V", "MA", "UNH", "HD", "COST", "AVGO", "CRM", "NFLX", "XOM", "JNJ", "PG", "KO", "PEP", "WMT")
CURRENT_KNOWN_EXPOSURE = ("AAPL", "NVDA", "AMZN", "GOOGL", "TSLA", "SPY", "QQQ")
MAX_SUBMITTED_SYMBOLS = 10
MAX_NOTIONAL_PER_SYMBOL = Decimal("5.00")
MAX_TOTAL_INTENDED_NOTIONAL = Decimal("50.00")
MAX_SPREAD_BPS = Decimal("50")
MAX_QUOTE_AGE_NS = 10_000_000_000
ACTIVE_ORDER_STATUSES = frozenset({"accepted", "new", "pending_new", "open", "accepted_for_bidding"})
TERMINAL_STATUSES = frozenset({"filled", "partially_filled", "rejected", "expired", "canceled", "cancelled"})
ALLOWED_TRADING_GET_PATHS = frozenset({"/v2/account", "/v2/positions", "/v2/orders", "/v2/account/activities", "/v2/clock"})
FORBIDDEN_MACHINE_VERDICTS = frozenset(
    {
        "LIVE_READY",
        "LIVE_APPROVED",
        "SUBMIT_REAL_ORDER",
        "CANCEL_REAL_ORDER",
        "SELL_REAL_ORDER",
        "REBALANCE_REAL_ORDER",
        "MUTATE_BROKER",
        "PROFITABLE",
        "NET_EDGE_POSITIVE",
        "EXIT_APPROVED",
    }
)


@dataclass(frozen=True)
class QuoteTruth:
    bid: Decimal | None
    ask: Decimal | None
    receive_ts_ns: int
    now_ts_ns: int
    source: str

    @property
    def mid(self) -> Decimal | None:
        if self.bid is None or self.ask is None:
            return None
        return (self.bid + self.ask) / Decimal("2")

    @property
    def spread_bps(self) -> Decimal | None:
        if self.bid is None or self.ask is None or self.mid is None or self.mid <= Decimal("0"):
            return None
        return ((self.ask - self.bid) / self.mid) * Decimal("10000")


@dataclass(frozen=True)
class LedgerRow:
    symbol: str
    existing_exposure: bool
    quote_status: str
    spread_status: str
    broker_constraints_status: str
    approval_status: str
    final_action: str
    reason_codes: tuple[str, ...]
    limit_price: Decimal | None = None
    qty: Decimal | None = None
    intended_notional: Decimal | None = None
    payload: dict[str, Any] | None = None


@dataclass(frozen=True)
class CanonicalMachineTruth:
    account: dict[str, Any]
    positions: tuple[dict[str, Any], ...]
    open_orders: tuple[dict[str, Any], ...]
    receive_ts_ns: int
    base_url: str = EXPECTED_PAPER_BASE_URL
    read_only: bool = True
    mutation_allowed: bool = False

    @property
    def position_symbols(self) -> tuple[str, ...]:
        return tuple(sorted(symbol for symbol, position in _positions_by_symbol(self.positions).items() if _position_qty(position) != Decimal("0")))

    @property
    def active_open_order_count(self) -> int:
        return len(_active_open_orders(self.open_orders))

    def fingerprint(self) -> dict[str, Any]:
        return {
            "account_status": self.account.get("status"),
            "position_symbols": self.position_symbols,
            "active_open_order_count": self.active_open_order_count,
            "read_only": self.read_only,
            "mutation_allowed": self.mutation_allowed,
            "receive_ts_ns": self.receive_ts_ns,
        }


@dataclass
class AlpacaPaperTradingClient:
    base_url: str
    key_id: str
    secret_key: str
    approval_present: bool = False
    calls: list[tuple[str, str]] = field(default_factory=list)
    posted_symbols: set[str] = field(default_factory=set)
    submitted_order_ids: set[str] = field(default_factory=set)

    def get_json(self, path: str, query: dict[str, str] | None = None) -> Any:
        self._validate_get(path, query)
        return self._request_json("GET", path, query=query)

    def post_order(self, payload: dict[str, Any]) -> Any:
        self._validate_post_order(payload)
        ack = self._request_json("POST", "/v2/orders", payload=payload)
        if isinstance(ack, dict) and ack.get("id"):
            self.submitted_order_ids.add(str(ack["id"]))
        self.posted_symbols.add(str(payload["symbol"]))
        return ack

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self.base_url.rstrip('/')}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "APCA-API-KEY-ID": self.key_id,
                "APCA-API-SECRET-KEY": self.secret_key,
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
            pytest.fail(f"Alpaca PAPER read-only network unavailable: {type(exc).__name__}")

    def _validate_get(self, path: str, query: dict[str, str] | None) -> None:
        assert self.base_url.rstrip("/") == EXPECTED_PAPER_BASE_URL
        if path.startswith("/v2/orders/"):
            suffix = path.removeprefix("/v2/orders/")
            assert suffix and "/" not in suffix
            assert suffix in self.submitted_order_ids
            assert query is None
            return
        assert path in ALLOWED_TRADING_GET_PATHS
        if path == "/v2/orders":
            assert (query or {}).get("status") == "open"

    def _validate_post_order(self, payload: dict[str, Any]) -> None:
        assert self.approval_present is True
        assert self.base_url.rstrip("/") == EXPECTED_PAPER_BASE_URL
        assert payload["symbol"] in CANDIDATE_SYMBOLS
        assert payload["symbol"] not in self.posted_symbols
        assert len(self.posted_symbols) < MAX_SUBMITTED_SYMBOLS
        assert payload["side"] == "buy"
        assert payload["type"] == "limit"
        assert payload["time_in_force"] == "day"
        assert payload.get("extended_hours") is False
        assert Decimal(str(payload["qty"])) > Decimal("0")
        assert Decimal(str(payload["qty"])) * Decimal(str(payload["limit_price"])) <= MAX_NOTIONAL_PER_SYMBOL
        assert str(payload["client_order_id"]).startswith(f"pk26g-paper-expansion-{payload['symbol'].lower()}-buy-limit-day-")
        forbidden = {"order_class", "take_profit", "stop_loss", "trail_price", "trail_percent"}
        assert not (forbidden & set(payload))


class AlpacaDataReadOnlyClient:
    def __init__(self, key_id: str, secret_key: str) -> None:
        self.base_url = ALPACA_DATA_BASE_URL
        self.key_id = key_id
        self.secret_key = secret_key
        self.calls: list[tuple[str, str]] = []

    def get_latest_quote(self, symbol: str) -> Any:
        assert symbol in CANDIDATE_SYMBOLS
        path = f"/v2/stocks/{symbol}/quotes/latest"
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            method="GET",
            headers={
                "APCA-API-KEY-ID": self.key_id,
                "APCA-API-SECRET-KEY": self.secret_key,
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
            pytest.fail(f"Alpaca PAPER quote read-only network unavailable: {type(exc).__name__}")


def _d(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    return Decimal(str(value))


def _unique(reasons: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(reasons))


def _load_env_file_values(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip().strip("'").strip('"')
        if key in {"APCA_API_BASE_URL", "APCA_API_KEY_ID", "APCA_API_SECRET_KEY"}:
            values[key] = value
    return values


def _alpaca_env_or_skip() -> tuple[str, str, str]:
    file_values = _load_env_file_values(Path.home() / ".poverty_killer_alpaca_paper_env")
    base_url = (os.environ.get("APCA_API_BASE_URL") or file_values.get("APCA_API_BASE_URL") or "").rstrip("/")
    key_id = os.environ.get("APCA_API_KEY_ID") or file_values.get("APCA_API_KEY_ID") or ""
    secret_key = os.environ.get("APCA_API_SECRET_KEY") or file_values.get("APCA_API_SECRET_KEY") or ""
    missing = [
        name
        for name, value in (
            ("APCA_API_BASE_URL", base_url),
            ("APCA_API_KEY_ID", key_id),
            ("APCA_API_SECRET_KEY", secret_key),
        )
        if not value
    ]
    if missing:
        pytest.skip(f"Alpaca PAPER env missing: {', '.join(missing)}")
    if base_url != EXPECTED_PAPER_BASE_URL:
        pytest.fail(f"APCA_API_BASE_URL is not exact paper endpoint: {base_url!r}")
    return base_url, key_id, secret_key


def _approval_26g_present() -> bool:
    return os.environ.get(APPROVAL_ENV_26G) == APPROVAL_VALUE_26G


def _old_approval_flags_present() -> dict[str, bool]:
    return {name: os.environ.get(name) == value for name, value in OLD_APPROVAL_VALUES.items()}


def _positions_by_symbol(positions: tuple[dict[str, Any], ...]) -> dict[str, dict[str, Any]]:
    return {str(position.get("symbol") or "").upper(): position for position in positions}


def _position_qty(position: dict[str, Any]) -> Decimal:
    return _d(position.get("qty") or position.get("quantity")) or Decimal("0")


def _active_open_orders(open_orders: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
    return tuple(order for order in open_orders if str(order.get("status") or "").lower() in ACTIVE_ORDER_STATUSES)


def _quote_from_payload(payload: dict[str, Any], *, receive_ts_ns: int, now_ts_ns: int) -> QuoteTruth:
    quote = payload.get("quote") or {}
    return QuoteTruth(
        bid=_d(quote.get("bp") or quote.get("bid_price")),
        ask=_d(quote.get("ap") or quote.get("ask_price")),
        receive_ts_ns=receive_ts_ns,
        now_ts_ns=now_ts_ns,
        source="alpaca_data_latest_quote",
    )


def _client_order_id(symbol: str, ts_ns: int) -> str:
    return f"pk26g-paper-expansion-{symbol.lower()}-buy-limit-day-{ts_ns}"


def _payload_for_quote(symbol: str, quote: QuoteTruth, ts_ns: int) -> tuple[dict[str, Any] | None, Decimal | None, Decimal | None, Decimal | None, list[str]]:
    reasons: list[str] = []
    if quote.bid is None or quote.ask is None or quote.mid is None:
        return None, None, None, None, ["quote_missing"]
    if quote.now_ts_ns - quote.receive_ts_ns > MAX_QUOTE_AGE_NS:
        reasons.append("quote_stale")
    if quote.spread_bps is None or quote.spread_bps > MAX_SPREAD_BPS:
        reasons.append("quote_wide_spread")
    if quote.ask <= Decimal("0"):
        reasons.append("limit_price_missing")
        return None, None, None, None, reasons
    limit_price = quote.ask.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    qty = (MAX_NOTIONAL_PER_SYMBOL / limit_price).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)
    intended_notional = (qty * limit_price).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    if qty <= Decimal("0"):
        reasons.append("quantity_missing_or_non_positive")
    if intended_notional <= Decimal("0") or intended_notional > MAX_NOTIONAL_PER_SYMBOL:
        reasons.append("notional_cap")
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
    return payload, qty, limit_price, intended_notional, reasons


def build_action_ledger(
    *,
    positions: tuple[dict[str, Any], ...],
    open_orders: tuple[dict[str, Any], ...],
    quotes: dict[str, QuoteTruth],
    approval_present: bool,
    ts_ns: int,
) -> tuple[LedgerRow, ...]:
    exposed_symbols = set(_positions_by_symbol(positions))
    active_open_order_symbols = {str(order.get("symbol") or "").upper() for order in _active_open_orders(open_orders)}
    rows: list[LedgerRow] = []
    submitted_so_far = 0
    total_intended = Decimal("0")

    for index, symbol in enumerate(CANDIDATE_SYMBOLS):
        reasons: list[str] = []
        existing_exposure = symbol in exposed_symbols
        quote = quotes.get(symbol)
        if existing_exposure:
            reasons.append("existing_exposure")
        if symbol in active_open_order_symbols:
            reasons.append("existing_open_order")
        if quote is None:
            quote_status = "missing"
            spread_status = "not_evaluated"
            payload = None
            qty = None
            limit_price = None
            intended_notional = None
            reasons.append("quote_missing")
        else:
            quote_status = "fresh" if quote.now_ts_ns - quote.receive_ts_ns <= MAX_QUOTE_AGE_NS and quote.bid is not None and quote.ask is not None else "stale_or_missing"
            spread_status = "acceptable" if quote.spread_bps is not None and quote.spread_bps <= MAX_SPREAD_BPS else "wide_or_missing"
            payload, qty, limit_price, intended_notional, quote_reasons = _payload_for_quote(symbol, quote, ts_ns + index)
            reasons.extend(quote_reasons)
        broker_constraints_status = "pass"
        if symbol not in CANDIDATE_SYMBOLS:
            broker_constraints_status = "fail"
            reasons.append("symbol_unsupported")
        if intended_notional is not None and total_intended + intended_notional > MAX_TOTAL_INTENDED_NOTIONAL:
            reasons.append("total_notional_cap")
        approval_status = "approved" if approval_present else "absent"

        if reasons:
            if "existing_exposure" in reasons:
                final_action = "SKIP_EXISTING_EXPOSURE"
            elif "existing_open_order" in reasons:
                final_action = "SKIP_BROKER_CONSTRAINT"
            elif "quote_missing" in reasons:
                final_action = "SKIP_STALE_QUOTE"
            elif "quote_stale" in reasons:
                final_action = "SKIP_STALE_QUOTE"
            elif "quote_wide_spread" in reasons:
                final_action = "SKIP_WIDE_SPREAD"
            elif "notional_cap" in reasons or "total_notional_cap" in reasons:
                final_action = "SKIP_NOTIONAL_CAP"
            elif "symbol_unsupported" in reasons:
                final_action = "SKIP_SYMBOL_UNSUPPORTED"
            else:
                final_action = "SKIP_OTHER_EXPLICIT_REASON"
            payload = None
        elif not approval_present:
            reasons.append("approval_absent")
            final_action = "SKIP_APPROVAL_ABSENT"
            payload = None
        elif submitted_so_far >= MAX_SUBMITTED_SYMBOLS:
            reasons.append("max_submitted_symbols")
            final_action = "SKIP_OTHER_EXPLICIT_REASON"
            payload = None
        else:
            final_action = "SUBMIT_BUY_LIMIT_DAY"
            submitted_so_far += 1
            if intended_notional is not None:
                total_intended += intended_notional
        rows.append(
            LedgerRow(
                symbol=symbol,
                existing_exposure=existing_exposure,
                quote_status=quote_status,
                spread_status=spread_status,
                broker_constraints_status=broker_constraints_status,
                approval_status=approval_status,
                final_action=final_action,
                reason_codes=_unique(reasons),
                limit_price=limit_price,
                qty=qty,
                intended_notional=intended_notional,
                payload=payload,
            )
        )
    return tuple(rows)


def summarize_machine(truth: CanonicalMachineTruth, ledger: tuple[LedgerRow, ...]) -> dict[str, Any]:
    fingerprint = truth.fingerprint()
    subsystem_fingerprints = {name: fingerprint for name in ("ownership", "exposure", "lifecycle", "protective", "economics", "readiness", "mutation_guard")}
    forbidden = {
        "post_called_without_approval": False,
        "delete_called": False,
        "patch_called": False,
        "cancel_called": False,
        "replace_called": False,
        "live_mode": False,
        "profitability_claimed": False,
    }
    if all(row.final_action != "SUBMIT_BUY_LIMIT_DAY" for row in ledger):
        approval_present = any(row.approval_status == "approved" for row in ledger)
        verdict = "PAPER_EXPANSION_MACHINE_BLOCKED_BY_GATES" if approval_present else "PAPER_EXPANSION_MACHINE_BLOCKED_BY_APPROVAL"
    else:
        verdict = "PAPER_EXPANSION_MACHINE_READY"
    assert verdict not in FORBIDDEN_MACHINE_VERDICTS
    return {
        "verdict": verdict,
        "fingerprint": fingerprint,
        "subsystem_fingerprints_match": all(value == fingerprint for value in subsystem_fingerprints.values()),
        "owned_symbols": truth.position_symbols,
        "open_orders_count": len(truth.open_orders),
        "active_open_orders_count": truth.active_open_order_count,
        "ledger_actions": {row.symbol: row.final_action for row in ledger},
        "ledger_skip_reasons": {row.symbol: row.reason_codes for row in ledger if row.final_action != "SUBMIT_BUY_LIMIT_DAY"},
        "protective_verdict": "PROTECTIVE_INTENT_METADATA_ONLY",
        "economics_verdict": "ECONOMICS_ADVISORY_MISSING_TRUTH",
        "readiness": {
            "live_ready": False,
            "new_orders_require_26g_approval": True,
            "post_execution_reconciliation_required": True,
        },
        "mutation_guard": forbidden,
    }


def _fixture_positions(symbols: tuple[str, ...] = CURRENT_KNOWN_EXPOSURE) -> tuple[dict[str, Any], ...]:
    return tuple({"symbol": symbol, "qty": "0.01"} for symbol in symbols)


def _fresh_quote() -> QuoteTruth:
    return QuoteTruth(bid=Decimal("100.00"), ask=Decimal("100.05"), receive_ts_ns=1_779_230_000_000_000_000, now_ts_ns=1_779_230_000_000_000_001, source="fixture")


def test_26g_approval_gate_blocks_without_exact_new_flag_and_old_flags_do_not_authorize(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(APPROVAL_ENV_26G, raising=False)
    for name in OLD_APPROVAL_VALUES:
        monkeypatch.delenv(name, raising=False)
    quotes = {symbol: _fresh_quote() for symbol in CANDIDATE_SYMBOLS}
    ledger_without_approval = build_action_ledger(
        positions=_fixture_positions(),
        open_orders=(),
        quotes=quotes,
        approval_present=False,
        ts_ns=1_779_230_000_000_000_000,
    )
    ledger_with_approval = build_action_ledger(
        positions=_fixture_positions(),
        open_orders=(),
        quotes=quotes,
        approval_present=True,
        ts_ns=1_779_230_000_000_000_000,
    )
    client = AlpacaPaperTradingClient(EXPECTED_PAPER_BASE_URL, "key", "secret", approval_present=False)

    assert all(row.final_action == "SKIP_APPROVAL_ABSENT" for row in ledger_without_approval)
    assert sum(1 for row in ledger_with_approval if row.final_action == "SUBMIT_BUY_LIMIT_DAY") == MAX_SUBMITTED_SYMBOLS
    assert _approval_26g_present() is False
    assert all(value is False for value in _old_approval_flags_present().values())
    with pytest.raises(AssertionError):
        client.post_order(ledger_with_approval[0].payload or {})


def test_26g_fixture_action_ledger_fail_closed_cases_have_explicit_reasons():
    fresh_quotes = {symbol: _fresh_quote() for symbol in CANDIDATE_SYMBOLS}
    stale_quote = replace(_fresh_quote(), now_ts_ns=_fresh_quote().receive_ts_ns + MAX_QUOTE_AGE_NS + 1)
    wide_quote = QuoteTruth(bid=Decimal("100.00"), ask=Decimal("110.00"), receive_ts_ns=1_779_230_000_000_000_000, now_ts_ns=1_779_230_000_000_000_001, source="fixture")
    case_quotes = {
        **fresh_quotes,
        "JPM": stale_quote,
        "V": wide_quote,
    }
    case_quotes.pop("MA")
    ledger = build_action_ledger(
        positions=_fixture_positions(("AAPL", "NVDA", "XOM")),
        open_orders=({"symbol": "UNH", "status": "new", "client_order_id": "open-unh"},),
        quotes=case_quotes,
        approval_present=True,
        ts_ns=1_779_230_000_000_000_000,
    )
    by_symbol = {row.symbol: row for row in ledger}

    assert by_symbol["XOM"].final_action == "SKIP_EXISTING_EXPOSURE"
    assert by_symbol["JPM"].final_action == "SKIP_STALE_QUOTE"
    assert by_symbol["MA"].final_action == "SKIP_STALE_QUOTE"
    assert by_symbol["V"].final_action == "SKIP_WIDE_SPREAD"
    assert by_symbol["UNH"].final_action == "SKIP_BROKER_CONSTRAINT"
    assert all(row.reason_codes for row in ledger if row.final_action != "SUBMIT_BUY_LIMIT_DAY")
    assert sum(1 for row in ledger if row.final_action == "SUBMIT_BUY_LIMIT_DAY") <= MAX_SUBMITTED_SYMBOLS


def test_26g_post_guard_rejects_live_market_duplicate_overcap_and_mutating_requests_without_network():
    payload = {
        "symbol": "JPM",
        "side": "buy",
        "type": "limit",
        "time_in_force": "day",
        "qty": "0.049975",
        "limit_price": "100.05",
        "extended_hours": False,
        "client_order_id": "pk26g-paper-expansion-jpm-buy-limit-day-1779230000000000000",
    }
    client = AlpacaPaperTradingClient(EXPECTED_PAPER_BASE_URL, "key", "secret", approval_present=True)
    client._validate_post_order(payload)
    client.posted_symbols.add("JPM")
    with pytest.raises(AssertionError):
        client._validate_post_order(payload)
    with pytest.raises(AssertionError):
        client._validate_post_order({**payload, "type": "market"})
    with pytest.raises(AssertionError):
        client._validate_post_order({**payload, "qty": "1"})
    with pytest.raises(AssertionError):
        client._validate_post_order({**payload, "extended_hours": True})
    with pytest.raises(AssertionError):
        client._validate_post_order({**payload, "order_class": "bracket"})
    with pytest.raises(AssertionError):
        AlpacaPaperTradingClient(FORBIDDEN_LIVE_BASE_URL, "key", "secret", approval_present=True)._validate_get("/v2/account", None)


def test_26g_machine_summary_requires_post_submit_reconciliation_and_consistent_truth_without_network():
    ledger = build_action_ledger(
        positions=_fixture_positions(),
        open_orders=(),
        quotes={symbol: _fresh_quote() for symbol in CANDIDATE_SYMBOLS},
        approval_present=False,
        ts_ns=1_779_230_000_000_000_000,
    )
    truth = CanonicalMachineTruth(
        account={"status": "ACTIVE", "id": "paper-account"},
        positions=_fixture_positions(),
        open_orders=(),
        receive_ts_ns=1_779_230_000_000_000_000,
    )
    summary = summarize_machine(truth, ledger)

    assert summary["verdict"] == "PAPER_EXPANSION_MACHINE_BLOCKED_BY_APPROVAL"
    assert summary["subsystem_fingerprints_match"] is True
    assert summary["mutation_guard"]["post_called_without_approval"] is False
    assert summary["readiness"]["post_execution_reconciliation_required"] is True
    assert summary["economics_verdict"] == "ECONOMICS_ADVISORY_MISSING_TRUTH"


def _classify_order_status(order: dict[str, Any]) -> str:
    status = str(order.get("status") or "").lower()
    if status == "filled":
        return "filled"
    if status == "partially_filled":
        return "partially_filled"
    if status in ACTIVE_ORDER_STATUSES:
        return "accepted_open"
    if status in {"rejected", "expired", "canceled", "cancelled"}:
        return status
    return "unknown_requires_followup"


@pytest.mark.broker_access
def test_real_26g_alpaca_paper_expansion_machine_blocks_without_approval_or_executes_when_approved():
    if os.environ.get(BROKER_READ_AUTH_ENV) != BROKER_READ_AUTH_VALUE:
        pytest.skip(f"broker access deferred; requires {BROKER_READ_AUTH_ENV}={BROKER_READ_AUTH_VALUE}")
    base_url, key_id, secret_key = _alpaca_env_or_skip()
    approval_present = _approval_26g_present()
    trading = AlpacaPaperTradingClient(base_url, key_id, secret_key, approval_present=approval_present)
    data = AlpacaDataReadOnlyClient(key_id, secret_key)

    account = trading.get_json("/v2/account")
    clock = trading.get_json("/v2/clock")
    positions = trading.get_json("/v2/positions")
    open_orders = trading.get_json("/v2/orders", {"status": "open", "limit": "100", "nested": "false"})
    assert isinstance(account, dict), "alpaca_account_invalid_shape"
    assert str(account.get("status") or "").upper() == "ACTIVE"
    assert clock.get("timestamp") or "is_open" in clock
    assert isinstance(positions, list), "alpaca_positions_invalid_shape"
    assert isinstance(open_orders, list), "alpaca_open_orders_invalid_shape"
    if _active_open_orders(tuple(open_orders)):
        pytest.fail("26G pre-execution open orders are nonzero; mutation blocked")

    quote_receive_ts_ns = now_ns()
    quote_payloads = {symbol: data.get_latest_quote(symbol) for symbol in CANDIDATE_SYMBOLS}
    quotes = {
        symbol: _quote_from_payload(payload, receive_ts_ns=quote_receive_ts_ns + index, now_ts_ns=now_ns())
        for index, (symbol, payload) in enumerate(quote_payloads.items())
        if not payload.get("_quote_error")
    }
    ledger = build_action_ledger(
        positions=tuple(positions),
        open_orders=tuple(open_orders),
        quotes=quotes,
        approval_present=approval_present,
        ts_ns=quote_receive_ts_ns,
    )
    pre_truth = CanonicalMachineTruth(account=account, positions=tuple(positions), open_orders=tuple(open_orders), receive_ts_ns=quote_receive_ts_ns)
    pre_machine = summarize_machine(pre_truth, ledger)

    if not approval_present:
        assert [call for call in trading.calls if call[0] == "POST"] == []
        assert all(row.final_action != "SUBMIT_BUY_LIMIT_DAY" for row in ledger)
        print(
            "ALPACA_26G_EXPANSION_SUMMARY="
            + json.dumps(
                _summary_payload(
                    account=account,
                    positions=tuple(positions),
                    open_orders=tuple(open_orders),
                    ledger=ledger,
                    pre_machine=pre_machine,
                    submitted_orders=(),
                    reconciled_orders=(),
                    approval_present=approval_present,
                    trading_calls=trading.calls,
                    data_calls=data.calls,
                ),
                sort_keys=True,
            )
        )
        pytest.skip("BLOCKED_BY_APPROVAL: exact 26G expansion approval flag missing; no POST allowed")

    submit_rows = tuple(row for row in ledger if row.final_action == "SUBMIT_BUY_LIMIT_DAY" and row.payload is not None)
    if not submit_rows:
        assert [call for call in trading.calls if call[0] == "POST"] == []
        print(
            "ALPACA_26G_EXPANSION_SUMMARY="
            + json.dumps(
                _summary_payload(
                    account=account,
                    positions=tuple(positions),
                    open_orders=tuple(open_orders),
                    ledger=ledger,
                    pre_machine=pre_machine,
                    submitted_orders=(),
                    reconciled_orders=(),
                    approval_present=approval_present,
                    trading_calls=trading.calls,
                    data_calls=data.calls,
                ),
                sort_keys=True,
            )
        )
        pytest.skip("BLOCKED_BY_GATES: exact 26G approval present but no safe candidates after quote/spread/broker gates; no POST sent")

    submitted_acks = []
    for row in submit_rows[:MAX_SUBMITTED_SYMBOLS]:
        submitted_acks.append(trading.post_order(row.payload or {}))
    assert len([call for call in trading.calls if call[0] == "POST"]) == len(submitted_acks)
    assert len(submitted_acks) <= MAX_SUBMITTED_SYMBOLS

    open_orders_after = trading.get_json("/v2/orders", {"status": "open", "limit": "100", "nested": "false"})
    positions_after = trading.get_json("/v2/positions")
    account_after = trading.get_json("/v2/account")
    activities_after = trading.get_json("/v2/account/activities", {"activity_types": "FILL", "page_size": "100"})
    submitted_order_ids = [str(ack.get("id")) for ack in submitted_acks if isinstance(ack, dict) and ack.get("id")]
    direct_orders = tuple(trading.get_json(f"/v2/orders/{order_id}") for order_id in submitted_order_ids)
    reconciled = tuple({"symbol": order.get("symbol"), "id": order.get("id"), "client_order_id": order.get("client_order_id"), "status": order.get("status"), "classification": _classify_order_status(order)} for order in direct_orders)
    post_truth = CanonicalMachineTruth(account=account_after, positions=tuple(positions_after), open_orders=tuple(open_orders_after), receive_ts_ns=now_ns())
    post_machine = summarize_machine(post_truth, ledger)

    assert all(item["classification"] != "unknown_requires_followup" for item in reconciled)
    assert post_machine["subsystem_fingerprints_match"] is True
    print(
        "ALPACA_26G_EXPANSION_SUMMARY="
        + json.dumps(
            _summary_payload(
                account=account_after,
                positions=tuple(positions_after),
                open_orders=tuple(open_orders_after),
                ledger=ledger,
                pre_machine=post_machine,
                submitted_orders=tuple(submitted_acks),
                reconciled_orders=reconciled,
                approval_present=approval_present,
                trading_calls=trading.calls,
                data_calls=data.calls,
                activities=activities_after,
            ),
            sort_keys=True,
        )
    )


def _ledger_to_summary(ledger: tuple[LedgerRow, ...]) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "symbol": row.symbol,
            "existing_exposure": row.existing_exposure,
            "quote_status": row.quote_status,
            "spread_status": row.spread_status,
            "broker_constraints_status": row.broker_constraints_status,
            "approval_status": row.approval_status,
            "final_action": row.final_action,
            "reason_codes": row.reason_codes,
            "limit_price": str(row.limit_price) if row.limit_price is not None else None,
            "qty": str(row.qty) if row.qty is not None else None,
            "intended_notional": str(row.intended_notional) if row.intended_notional is not None else None,
        }
        for row in ledger
    )


def _summary_payload(
    *,
    account: dict[str, Any],
    positions: tuple[dict[str, Any], ...],
    open_orders: tuple[dict[str, Any], ...],
    ledger: tuple[LedgerRow, ...],
    pre_machine: dict[str, Any],
    submitted_orders: tuple[Any, ...],
    reconciled_orders: tuple[Any, ...],
    approval_present: bool,
    trading_calls: list[tuple[str, str]],
    data_calls: list[tuple[str, str]],
    activities: Any = None,
) -> dict[str, Any]:
    positions_by_symbol = _positions_by_symbol(positions)
    return {
        "approval_26g_present": approval_present,
        "old_approval_flags_present": _old_approval_flags_present(),
        "account_status": account.get("status"),
        "cash": account.get("cash"),
        "buying_power": account.get("buying_power"),
        "equity": account.get("equity"),
        "portfolio_value": account.get("portfolio_value"),
        "positions_count": len(positions),
        "position_symbols": sorted(positions_by_symbol),
        "current_known_exposure_present": [symbol for symbol in CURRENT_KNOWN_EXPOSURE if symbol in positions_by_symbol],
        "open_orders_count": len(open_orders),
        "active_open_orders_count": len(_active_open_orders(open_orders)),
        "candidate_universe": CANDIDATE_SYMBOLS,
        "ledger": _ledger_to_summary(ledger),
        "submitted_orders_count": len(submitted_orders),
        "submitted_symbols": [item.get("symbol") for item in submitted_orders if isinstance(item, dict)],
        "reconciled_orders": reconciled_orders,
        "machine": pre_machine,
        "trading_http_methods": sorted({method for method, _path in trading_calls}),
        "data_http_methods": sorted({method for method, _path in data_calls}),
        "activities_shape": "dict" if isinstance(activities, dict) else "list" if isinstance(activities, list) else None,
    }
