from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.utils.time_utils import now_ns


EXPECTED_PAPER_BASE_URL = "https://paper-api.alpaca.markets"
FORBIDDEN_LIVE_BASE_URL = "https://api.alpaca.markets"
EXPECTED_POSITION_SYMBOLS = ("AAPL", "NVDA", "AMZN", "GOOGL", "TSLA", "SPY", "QQQ")
MAX_SNAPSHOT_AGE_NS = 5_000_000_000
ACTIVE_ORDER_STATUSES = frozenset({"accepted", "new", "pending_new", "open", "accepted_for_bidding"})
ALLOWED_GET_PATHS = frozenset({"/v2/account", "/v2/positions", "/v2/orders", "/v2/account/activities", "/v2/clock"})
MUTATION_APPROVAL_VALUES = {
    "POVERTY_KILLER_APPROVE_ALPACA_PAPER_TINY_ORDER_25Z": "YES_I_APPROVE_ONE_PAPER_LIMIT_ORDER",
    "POVERTY_KILLER_APPROVE_ALPACA_PAPER_10_SYMBOL_BATCH_26B": "YES_I_APPROVE_10_PAPER_LIMIT_ORDERS",
}
FORBIDDEN_VERDICTS = frozenset(
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
AMD_SKIP_GAP = "reason_not_emitted_by_existing_26b_harness"


@dataclass(frozen=True)
class PaperPortfolioSnapshot:
    base_url: str
    account: dict[str, Any]
    positions: tuple[dict[str, Any], ...]
    open_orders: tuple[dict[str, Any], ...]
    recent_fills: tuple[dict[str, Any], ...]
    receive_ts_ns: int
    account_id_known: bool = True
    environment: str = "paper"
    read_only: bool = True
    mutation_allowed: bool = False


@dataclass(frozen=True)
class LocalPortfolioState:
    positions: dict[str, Decimal]
    open_order_client_ids: tuple[str, ...] = ()
    active_reservation_client_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class LifecycleDecision:
    verdict: str
    reason_codes: tuple[str, ...]
    position_lifecycle: tuple[dict[str, Any], ...]
    entry_add_on_response: tuple[dict[str, Any], ...]
    protective_response: dict[str, Any]
    exit_defense: dict[str, Any]
    economics_advisory: dict[str, Any]
    ready_non_mutating: bool
    broker_mutation_allowed: bool = False
    live_ready: bool = False
    exit_approved: bool = False


class AlpacaPaperReadOnlyClient:
    def __init__(self, base_url: str, key_id: str, secret_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._key_id = key_id
        self._secret_key = secret_key
        self.calls: list[tuple[str, str]] = []

    def get_json(self, path: str, query: dict[str, str] | None = None) -> Any:
        self._validate_get(path, query)
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
            pytest.fail(f"Alpaca PAPER read-only lookup failed: HTTP {exc.code}: {body[:120]}")
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            pytest.fail(f"Alpaca PAPER read-only network unavailable: {type(exc).__name__}")

    def request_json(self, method: str, path: str, query: dict[str, str] | None = None, payload: dict[str, Any] | None = None) -> Any:
        assert method == "GET", "alpaca_26e_mutating_method_forbidden"
        assert payload is None, "alpaca_26e_payload_forbidden"
        return self.get_json(path, query)

    def _validate_get(self, path: str, query: dict[str, str] | None) -> None:
        assert self.base_url == EXPECTED_PAPER_BASE_URL
        assert path in ALLOWED_GET_PATHS
        if path == "/v2/orders":
            assert (query or {}).get("status") == "open"
        blocked_fragments = ("submit", "cancel", "replace", "close", "liquidate")
        assert not any(fragment in path.lower() for fragment in blocked_fragments)


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


def _alpaca_env_or_fail() -> tuple[str, str, str]:
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
        pytest.fail(f"Alpaca PAPER read-only env missing: {', '.join(missing)}")
    if base_url != EXPECTED_PAPER_BASE_URL:
        pytest.fail(f"APCA_API_BASE_URL is not exact paper endpoint: {base_url!r}")
    return base_url, key_id, secret_key


def _approval_flags_armed() -> dict[str, bool]:
    return {name: os.environ.get(name) == expected for name, expected in MUTATION_APPROVAL_VALUES.items()}


def _positions_by_symbol(positions: tuple[dict[str, Any], ...]) -> dict[str, dict[str, Any]]:
    return {str(position.get("symbol") or "").upper(): position for position in positions}


def _position_qty(position: dict[str, Any]) -> Decimal:
    return _d(position.get("qty") or position.get("quantity")) or Decimal("0")


def _active_open_orders(open_orders: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
    return tuple(order for order in open_orders if str(order.get("status") or "").lower() in ACTIVE_ORDER_STATUSES)


def _entry_response(symbol: str, owned_symbols: set[str], lifecycle_by_symbol: dict[str, str]) -> dict[str, Any]:
    if symbol in owned_symbols:
        return {
            "symbol": symbol,
            "classification": "duplicate_or_add_on_requires_board_approval",
            "lifecycle_state": lifecycle_by_symbol.get(symbol),
            "admitted": False,
            "submit_order_called": False,
            "route_order_called": False,
            "broker_mutation_called": False,
        }
    return {
        "symbol": symbol,
        "classification": "fresh_entry_blocked_by_26e_lifecycle_scope",
        "lifecycle_state": None,
        "admitted": False,
        "submit_order_called": False,
        "route_order_called": False,
        "broker_mutation_called": False,
    }


def classify_portfolio_lifecycle(
    snapshot: PaperPortfolioSnapshot,
    local: LocalPortfolioState,
    *,
    current_ts_ns: int,
    entry_candidate_symbols: tuple[str, ...],
    exit_pressure_symbols: frozenset[str] = frozenset(),
    missing_fill_basis_symbols: frozenset[str] = frozenset(),
    unavailable_market_evidence_symbols: frozenset[str] = frozenset(),
    protective_attempts_mutation: bool = False,
    exit_board_approved: bool = False,
) -> LifecycleDecision:
    reasons: list[str] = []
    if snapshot.base_url != EXPECTED_PAPER_BASE_URL or snapshot.environment != "paper":
        reasons.append("wrong_environment_or_live_like_endpoint")
    if not snapshot.read_only or snapshot.mutation_allowed:
        reasons.append("broker_mutation_capability_present")
    if not snapshot.account_id_known or not snapshot.account.get("id"):
        reasons.append("missing_account_identity")
    if str(snapshot.account.get("status") or "").upper() not in {"ACTIVE", "ACCOUNT_ACTIVE"}:
        reasons.append("account_not_active")
    if snapshot.receive_ts_ns <= 0 or current_ts_ns - snapshot.receive_ts_ns > MAX_SNAPSHOT_AGE_NS:
        reasons.append("stale_broker_snapshot")

    positions_by_symbol = _positions_by_symbol(snapshot.positions)
    if not positions_by_symbol:
        reasons.append("missing_broker_positions")
    active_orders = _active_open_orders(snapshot.open_orders)
    if active_orders:
        reasons.append("nonzero_unknown_open_orders")
        for order in active_orders:
            client_order_id = str(order.get("client_order_id") or "")
            if not client_order_id or client_order_id not in local.open_order_client_ids:
                reasons.append("orphan_broker_open_order")
    for symbol, local_qty in local.positions.items():
        broker_qty = _position_qty(positions_by_symbol[symbol]) if symbol in positions_by_symbol else Decimal("0")
        if local_qty != broker_qty:
            reasons.append("broker_local_position_conflict")
    for reservation_id in local.active_reservation_client_ids:
        if reservation_id not in local.open_order_client_ids:
            reasons.append("local_reservation_conflict")
    if protective_attempts_mutation:
        reasons.append("protective_intent_attempted_broker_mutation")

    lifecycle_rows: list[dict[str, Any]] = []
    owned_symbols: set[str] = set()
    for symbol, position in sorted(positions_by_symbol.items()):
        qty = _position_qty(position)
        if qty == Decimal("0"):
            continue
        owned_symbols.add(symbol)
        state = "HELD"
        row_reasons = ["broker_position_owned"]
        if symbol in unavailable_market_evidence_symbols:
            state = "PROTECTIVE_REVIEW"
            row_reasons.append("market_or_economic_evidence_unavailable")
            reasons.append("missing_market_or_economic_evidence")
        if symbol in missing_fill_basis_symbols:
            state = "PROTECTIVE_REVIEW"
            row_reasons.append("missing_fill_basis")
            reasons.append("missing_fill_basis_for_lifecycle")
        if symbol in exit_pressure_symbols:
            state = "EXIT_INTENT_REQUIRES_APPROVAL"
            row_reasons.append("exit_pressure_observed")
            row_reasons.append("board_exit_approval_required")
            reasons.append("exit_intent_requires_approval")
            assert exit_board_approved is False
        lifecycle_rows.append(
            {
                "symbol": symbol,
                "qty": str(qty),
                "state": state,
                "reason_codes": tuple(row_reasons),
                "sell_order_allowed": False,
                "cancel_order_allowed": False,
                "replace_order_allowed": False,
                "broker_mutation_called": False,
                "profitability_claimed": False,
            }
        )

    lifecycle_by_symbol = {row["symbol"]: row["state"] for row in lifecycle_rows}
    entry_rows = tuple(_entry_response(symbol, owned_symbols, lifecycle_by_symbol) for symbol in entry_candidate_symbols)
    protective_response = {
        "output_kind": "metadata_intent_only",
        "watch_symbols": tuple(row["symbol"] for row in lifecycle_rows if row["state"] == "WATCH"),
        "protective_review_symbols": tuple(row["symbol"] for row in lifecycle_rows if row["state"] == "PROTECTIVE_REVIEW"),
        "exit_pressure_symbols": tuple(row["symbol"] for row in lifecycle_rows if row["state"] == "EXIT_INTENT_REQUIRES_APPROVAL"),
        "authorizes_fresh_entry": False,
        "authorizes_sell": False,
        "authorizes_cancel": False,
        "authorizes_replace": False,
        "broker_mutation_called": False,
    }
    exit_defense = {
        "output_kind": "exit_pressure_evidence_only",
        "exit_intent_symbols": tuple(row["symbol"] for row in lifecycle_rows if row["state"] == "EXIT_INTENT_REQUIRES_APPROVAL"),
        "requires_board_operator_approval": True,
        "sell_order_submitted": False,
        "cancel_order_submitted": False,
        "replace_order_submitted": False,
        "live_reservation_lifecycle_opened": False,
        "exit_approved": False,
    }
    economics_advisory = {
        "output_kind": "advisory_missing_truth_only",
        "uses_lifecycle_context": True,
        "missing_truth": (
            "arrival_price",
            "slippage",
            "net_edge",
            "profitability_basis",
            "fee_if_not_returned",
        ),
        "pnl_claimed": False,
        "slippage_claimed": False,
        "arrival_price_invented": False,
        "net_edge_claimed": False,
        "profitability_claimed": False,
        "active_veto_authority": False,
        "active_approval_authority": False,
    }

    unique_reasons = _unique(reasons)
    if "exit_intent_requires_approval" in unique_reasons:
        verdict = "EXIT_INTENT_REQUIRES_APPROVAL"
    elif "stale_broker_snapshot" in unique_reasons:
        verdict = "BLOCKED_STALE_BROKER_TRUTH"
    elif "broker_local_position_conflict" in unique_reasons:
        verdict = "BLOCKED_CONFLICTING_POSITION_TRUTH"
    elif "nonzero_unknown_open_orders" in unique_reasons:
        verdict = "BLOCKED_UNKNOWN_OPEN_ORDER"
    elif "missing_fill_basis_for_lifecycle" in unique_reasons or "missing_market_or_economic_evidence" in unique_reasons:
        verdict = "BLOCKED_MISSING_ECONOMIC_TRUTH"
    elif unique_reasons:
        verdict = "BLOCKED_MISSING_BROKER_TRUTH"
    else:
        verdict = "PAPER_PORTFOLIO_LIFECYCLE_READY_NON_MUTATING"
    assert verdict not in FORBIDDEN_VERDICTS
    return LifecycleDecision(
        verdict=verdict,
        reason_codes=unique_reasons,
        position_lifecycle=tuple(lifecycle_rows),
        entry_add_on_response=entry_rows,
        protective_response=protective_response,
        exit_defense=exit_defense,
        economics_advisory=economics_advisory,
        ready_non_mutating=not unique_reasons,
    )


def _fixture_snapshot(**overrides: Any) -> PaperPortfolioSnapshot:
    fields = {
        "base_url": EXPECTED_PAPER_BASE_URL,
        "account": {"id": "paper-account", "status": "ACTIVE", "currency": "USD", "cash": "99965", "buying_power": "199964.98", "equity": "99999.98"},
        "positions": tuple({"symbol": symbol, "qty": "0.01"} for symbol in EXPECTED_POSITION_SYMBOLS),
        "open_orders": (),
        "recent_fills": (),
        "receive_ts_ns": 1_779_210_000_000_000_000,
    }
    fields.update(overrides)
    return PaperPortfolioSnapshot(**fields)


def test_fixture_owned_positions_classify_as_living_lifecycle_objects_without_mutation():
    snapshot = _fixture_snapshot()
    decision = classify_portfolio_lifecycle(
        snapshot,
        LocalPortfolioState(positions={}),
        current_ts_ns=snapshot.receive_ts_ns + 1,
        entry_candidate_symbols=("AAPL", "NVDA", "MSFT"),
    )

    states = {row["symbol"]: row["state"] for row in decision.position_lifecycle}
    entry = {row["symbol"]: row["classification"] for row in decision.entry_add_on_response}
    assert decision.verdict == "PAPER_PORTFOLIO_LIFECYCLE_READY_NON_MUTATING"
    assert set(states) == set(EXPECTED_POSITION_SYMBOLS)
    assert all(state == "HELD" for state in states.values())
    assert entry["AAPL"] == "duplicate_or_add_on_requires_board_approval"
    assert entry["NVDA"] == "duplicate_or_add_on_requires_board_approval"
    assert entry["MSFT"] == "fresh_entry_blocked_by_26e_lifecycle_scope"
    assert all(row["sell_order_allowed"] is False for row in decision.position_lifecycle)
    assert all(row["broker_mutation_called"] is False for row in decision.position_lifecycle)
    assert decision.protective_response["output_kind"] == "metadata_intent_only"
    assert decision.protective_response["authorizes_sell"] is False
    assert decision.exit_defense["output_kind"] == "exit_pressure_evidence_only"
    assert decision.exit_defense["sell_order_submitted"] is False
    assert decision.economics_advisory["output_kind"] == "advisory_missing_truth_only"
    assert decision.economics_advisory["pnl_claimed"] is False
    assert decision.economics_advisory["slippage_claimed"] is False
    assert decision.economics_advisory["arrival_price_invented"] is False
    assert decision.economics_advisory["net_edge_claimed"] is False
    assert decision.economics_advisory["profitability_claimed"] is False
    assert decision.broker_mutation_allowed is False
    assert decision.live_ready is False
    assert decision.exit_approved is False


def test_fixture_exit_pressure_is_non_mutating_and_requires_board_approval():
    snapshot = _fixture_snapshot()
    decision = classify_portfolio_lifecycle(
        snapshot,
        LocalPortfolioState(positions={}),
        current_ts_ns=snapshot.receive_ts_ns + 1,
        entry_candidate_symbols=("AAPL",),
        exit_pressure_symbols=frozenset({"AAPL"}),
    )

    aapl = next(row for row in decision.position_lifecycle if row["symbol"] == "AAPL")
    assert decision.verdict == "EXIT_INTENT_REQUIRES_APPROVAL"
    assert "exit_intent_requires_approval" in decision.reason_codes
    assert aapl["state"] == "EXIT_INTENT_REQUIRES_APPROVAL"
    assert aapl["sell_order_allowed"] is False
    assert decision.exit_defense["exit_intent_symbols"] == ("AAPL",)
    assert decision.exit_defense["requires_board_operator_approval"] is True
    assert decision.exit_defense["sell_order_submitted"] is False
    assert decision.exit_defense["exit_approved"] is False
    assert decision.protective_response["broker_mutation_called"] is False


def test_fixture_lifecycle_no_go_cases_fail_closed_without_network():
    clean = _fixture_snapshot()
    current_ts_ns = clean.receive_ts_ns + 1
    cases = {
        "stale_broker_snapshot": (
            replace(clean, receive_ts_ns=current_ts_ns - MAX_SNAPSHOT_AGE_NS - 1),
            LocalPortfolioState({}),
            {},
        ),
        "missing_broker_positions": (replace(clean, positions=()), LocalPortfolioState({}), {}),
        "broker_local_position_conflict": (clean, LocalPortfolioState({"AAPL": Decimal("0")}), {}),
        "nonzero_unknown_open_orders": (
            replace(clean, open_orders=({"id": "o1", "client_order_id": "unknown", "symbol": "AAPL", "status": "new"},)),
            LocalPortfolioState({}),
            {},
        ),
        "orphan_broker_open_order": (
            replace(clean, open_orders=({"id": "o1", "symbol": "AAPL", "status": "new"},)),
            LocalPortfolioState({}),
            {},
        ),
        "local_reservation_conflict": (clean, LocalPortfolioState({}, active_reservation_client_ids=("res-1",)), {}),
        "missing_account_identity": (replace(clean, account={**clean.account, "id": ""}, account_id_known=False), LocalPortfolioState({}), {}),
        "wrong_environment_or_live_like_endpoint": (replace(clean, base_url=FORBIDDEN_LIVE_BASE_URL, environment="live"), LocalPortfolioState({}), {}),
        "missing_fill_basis_for_lifecycle": (clean, LocalPortfolioState({}), {"missing_fill_basis_symbols": frozenset({"NVDA"})}),
        "missing_market_or_economic_evidence": (clean, LocalPortfolioState({}), {"unavailable_market_evidence_symbols": frozenset({"QQQ"})}),
        "protective_intent_attempted_broker_mutation": (clean, LocalPortfolioState({}), {"protective_attempts_mutation": True}),
    }

    for expected_reason, (snapshot, local, kwargs) in cases.items():
        decision = classify_portfolio_lifecycle(
            snapshot,
            local,
            current_ts_ns=current_ts_ns,
            entry_candidate_symbols=("AAPL",),
            **kwargs,
        )
        assert expected_reason in decision.reason_codes
        assert decision.verdict != "PAPER_PORTFOLIO_LIFECYCLE_READY_NON_MUTATING"
        assert decision.verdict not in FORBIDDEN_VERDICTS
        assert decision.broker_mutation_allowed is False
        assert decision.live_ready is False
        assert decision.exit_approved is False
        assert decision.exit_defense["sell_order_submitted"] is False
        assert decision.protective_response["broker_mutation_called"] is False


def test_read_only_client_approval_and_mutation_guards_hold_without_network():
    client = AlpacaPaperReadOnlyClient(EXPECTED_PAPER_BASE_URL, "key", "secret")

    client._validate_get("/v2/account", None)
    client._validate_get("/v2/orders", {"status": "open"})
    assert all(is_armed is False for is_armed in _approval_flags_armed().values())
    with pytest.raises(AssertionError):
        client.request_json("POST", "/v2/orders", payload={"symbol": "AAPL"})
    with pytest.raises(AssertionError):
        client.request_json("PATCH", "/v2/orders")
    with pytest.raises(AssertionError):
        client.request_json("DELETE", "/v2/orders")
    with pytest.raises(AssertionError):
        client._validate_get("/v2/orders", {"status": "closed"})
    with pytest.raises(AssertionError):
        client._validate_get("/v2/orders/abc/cancel", None)
    with pytest.raises(AssertionError):
        AlpacaPaperReadOnlyClient(FORBIDDEN_LIVE_BASE_URL, "key", "secret")._validate_get("/v2/account", None)


def test_real_alpaca_paper_portfolio_lifecycle_exit_defense_get_only():
    assert all(is_armed is False for is_armed in _approval_flags_armed().values())
    base_url, key_id, secret_key = _alpaca_env_or_fail()
    client = AlpacaPaperReadOnlyClient(base_url, key_id, secret_key)

    account = client.get_json("/v2/account")
    clock = client.get_json("/v2/clock")
    positions = client.get_json("/v2/positions")
    open_orders = client.get_json("/v2/orders", {"status": "open", "limit": "100", "nested": "false"})
    activities = client.get_json("/v2/account/activities", {"activity_types": "FILL", "page_size": "100"})

    assert isinstance(account, dict), "alpaca_account_invalid_shape"
    assert isinstance(positions, list), "alpaca_positions_invalid_shape"
    assert isinstance(open_orders, list), "alpaca_open_orders_invalid_shape"
    assert clock.get("timestamp") or "is_open" in clock
    activity_items = activities.get("activities", ()) if isinstance(activities, dict) else activities or ()
    snapshot = PaperPortfolioSnapshot(
        base_url=base_url,
        account=account,
        positions=tuple(positions),
        open_orders=tuple(open_orders),
        recent_fills=tuple(item for item in activity_items if isinstance(item, dict)),
        receive_ts_ns=now_ns(),
        account_id_known=bool(account.get("id")),
    )
    decision = classify_portfolio_lifecycle(
        snapshot,
        LocalPortfolioState(positions={}),
        current_ts_ns=snapshot.receive_ts_ns + 1,
        entry_candidate_symbols=("AAPL", "NVDA", "AMD"),
    )
    positions_by_symbol = _positions_by_symbol(snapshot.positions)
    expected_present = tuple(symbol for symbol in EXPECTED_POSITION_SYMBOLS if symbol in positions_by_symbol)

    assert client.base_url == EXPECTED_PAPER_BASE_URL
    assert all(method == "GET" for method, _path in client.calls)
    assert {path for _method, path in client.calls}.issubset(ALLOWED_GET_PATHS)
    assert str(account.get("status") or "").upper() == "ACTIVE"
    assert set(expected_present) == set(EXPECTED_POSITION_SYMBOLS)
    assert len(_active_open_orders(snapshot.open_orders)) == 0
    assert decision.verdict == "PAPER_PORTFOLIO_LIFECYCLE_READY_NON_MUTATING"
    assert all(row["state"] == "HELD" for row in decision.position_lifecycle)
    assert decision.protective_response["output_kind"] == "metadata_intent_only"
    assert decision.exit_defense["output_kind"] == "exit_pressure_evidence_only"
    assert decision.exit_defense["sell_order_submitted"] is False
    assert decision.economics_advisory["output_kind"] == "advisory_missing_truth_only"
    assert decision.economics_advisory["profitability_claimed"] is False
    assert decision.broker_mutation_allowed is False
    assert decision.live_ready is False
    assert decision.exit_approved is False

    lifecycle_summary = {row["symbol"]: row["state"] for row in decision.position_lifecycle}
    entry_summary = {row["symbol"]: row["classification"] for row in decision.entry_add_on_response}
    positions_summary = {
        symbol: {
            "qty": position.get("qty"),
            "market_value": position.get("market_value"),
            "avg_entry_price": position.get("avg_entry_price"),
            "side": position.get("side"),
            "current_price": position.get("current_price"),
        }
        for symbol, position in positions_by_symbol.items()
        if symbol in EXPECTED_POSITION_SYMBOLS
    }
    print(
        "ALPACA_26E_LIFECYCLE_EXIT_DEFENSE_SUMMARY="
        + json.dumps(
            {
                "account_status": account.get("status"),
                "cash": account.get("cash"),
                "buying_power": account.get("buying_power"),
                "equity": account.get("equity"),
                "portfolio_value": account.get("portfolio_value"),
                "open_orders_count": len(snapshot.open_orders),
                "active_open_orders_count": len(_active_open_orders(snapshot.open_orders)),
                "positions_count": len(snapshot.positions),
                "expected_positions_present": expected_present,
                "positions": positions_summary,
                "lifecycle": lifecycle_summary,
                "entry_add_on": entry_summary,
                "protective_output_kind": decision.protective_response["output_kind"],
                "exit_defense_output_kind": decision.exit_defense["output_kind"],
                "economics_output_kind": decision.economics_advisory["output_kind"],
                "verdict": decision.verdict,
                "reason_codes": decision.reason_codes,
                "approval_flags_armed": _approval_flags_armed(),
                "amd_gap": AMD_SKIP_GAP,
                "http_methods": sorted({method for method, _path in client.calls}),
            },
            sort_keys=True,
        )
    )
