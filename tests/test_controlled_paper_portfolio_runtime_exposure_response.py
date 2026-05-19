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
EXPECTED_EXPOSURE_SYMBOLS = ("AAPL", "NVDA", "AMZN", "GOOGL", "TSLA", "SPY", "QQQ")
KNOWN_26B_SKIPPED = {
    "AAPL": "existing_position_present",
    "MSFT": "quote_wide_spread",
    "META": "quote_wide_spread",
    "AMD": "reason_not_emitted_by_existing_26b_harness",
}
MAX_SNAPSHOT_AGE_NS = 5_000_000_000
ACTIVE_ORDER_STATUSES = frozenset({"accepted", "new", "pending_new", "open", "accepted_for_bidding"})
MUTATION_APPROVAL_FLAGS = (
    "POVERTY_KILLER_APPROVE_ALPACA_PAPER_TINY_ORDER_25Z",
    "POVERTY_KILLER_APPROVE_ALPACA_PAPER_10_SYMBOL_BATCH_26B",
)
MUTATION_APPROVAL_VALUES = {
    "POVERTY_KILLER_APPROVE_ALPACA_PAPER_TINY_ORDER_25Z": "YES_I_APPROVE_ONE_PAPER_LIMIT_ORDER",
    "POVERTY_KILLER_APPROVE_ALPACA_PAPER_10_SYMBOL_BATCH_26B": "YES_I_APPROVE_10_PAPER_LIMIT_ORDERS",
}
ALLOWED_GET_PATHS = frozenset({"/v2/account", "/v2/positions", "/v2/orders", "/v2/account/activities", "/v2/clock"})
FORBIDDEN_VERDICTS = frozenset(
    {
        "LIVE_READY",
        "LIVE_APPROVED",
        "SUBMIT_REAL_ORDER",
        "CANCEL_REAL_ORDER",
        "MUTATE_BROKER",
        "PROFITABLE",
        "NET_EDGE_POSITIVE",
    }
)


@dataclass(frozen=True)
class PaperBrokerSnapshot:
    base_url: str
    account: dict[str, Any]
    positions: tuple[dict[str, Any], ...]
    open_orders: tuple[dict[str, Any], ...]
    recent_fills: tuple[dict[str, Any], ...]
    receive_ts_ns: int
    account_id_known: bool = True
    source: str = "alpaca"
    environment: str = "paper"
    read_only: bool = True
    mutation_allowed: bool = False


@dataclass(frozen=True)
class LocalRuntimeState:
    positions: dict[str, Decimal]
    open_order_client_ids: tuple[str, ...] = ()
    active_reservation_client_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExposureResponse:
    verdict: str
    reason_codes: tuple[str, ...]
    entry_responses: tuple[dict[str, Any], ...]
    protective_response: dict[str, Any]
    economics_advisory: dict[str, Any]
    ready_for_paper_exposure_response: bool
    real_submit_allowed: bool = False
    real_cancel_allowed: bool = False
    real_replace_allowed: bool = False
    broker_mutation_allowed: bool = False
    live_ready: bool = False
    live_approved: bool = False


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
        assert method == "GET", "alpaca_26d_mutating_method_forbidden"
        assert payload is None, "alpaca_26d_payload_forbidden"
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


def _approval_flags_absent() -> dict[str, bool]:
    return {name: os.environ.get(name) == value for name, value in MUTATION_APPROVAL_VALUES.items()}


def _positions_by_symbol(positions: tuple[dict[str, Any], ...]) -> dict[str, dict[str, Any]]:
    return {str(position.get("symbol") or "").upper(): position for position in positions}


def _position_qty(position: dict[str, Any]) -> Decimal:
    return _d(position.get("qty") or position.get("quantity")) or Decimal("0")


def _active_open_orders(open_orders: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
    return tuple(order for order in open_orders if str(order.get("status") or "").lower() in ACTIVE_ORDER_STATUSES)


def _build_entry_response(symbol: str, exposed_symbols: set[str]) -> dict[str, Any]:
    if symbol in exposed_symbols:
        classification = "existing_exposure_requires_board_approval"
        reason_codes = ("existing_broker_position", "duplicate_or_add_on_entry_not_blindly_admitted")
    else:
        classification = "blocked_pending_portfolio_aware_board_packet"
        reason_codes = ("new_entry_not_authorized_by_26d",)
    return {
        "symbol": symbol,
        "classification": classification,
        "reason_codes": reason_codes,
        "admitted": False,
        "submit_order_called": False,
        "router_called": False,
        "broker_mutation_called": False,
        "fresh_entry_authority": False,
    }


def evaluate_controlled_exposure_response(
    snapshot: PaperBrokerSnapshot,
    local: LocalRuntimeState,
    *,
    current_ts_ns: int,
    entry_candidate_symbols: tuple[str, ...],
) -> ExposureResponse:
    reasons: list[str] = []
    if snapshot.base_url != EXPECTED_PAPER_BASE_URL or snapshot.environment != "paper":
        reasons.append("wrong_environment_or_live_like_endpoint")
    if snapshot.source != "alpaca":
        reasons.append("broker_source_missing")
    if not snapshot.read_only or snapshot.mutation_allowed:
        reasons.append("broker_snapshot_not_read_only")
    if not snapshot.account_id_known or not snapshot.account.get("id"):
        reasons.append("missing_account_identity")
    if str(snapshot.account.get("status") or "").upper() not in {"ACTIVE", "ACCOUNT_ACTIVE"}:
        reasons.append("account_not_active")
    if snapshot.receive_ts_ns <= 0 or current_ts_ns - snapshot.receive_ts_ns > MAX_SNAPSHOT_AGE_NS:
        reasons.append("stale_broker_snapshot")

    broker_positions = _positions_by_symbol(snapshot.positions)
    if not broker_positions:
        reasons.append("missing_broker_positions")
    active_orders = _active_open_orders(snapshot.open_orders)
    if active_orders:
        reasons.append("unknown_or_nonzero_open_orders")
        for order in active_orders:
            if not order.get("client_order_id") or str(order.get("client_order_id")) not in local.open_order_client_ids:
                reasons.append("orphan_broker_open_order")

    for symbol, local_qty in local.positions.items():
        broker_qty = _position_qty(broker_positions[symbol]) if symbol in broker_positions else Decimal("0")
        if local_qty != broker_qty:
            reasons.append("local_broker_position_conflict")
    for reservation_id in local.active_reservation_client_ids:
        if reservation_id not in local.open_order_client_ids:
            reasons.append("local_reservation_conflict")

    exposed_symbols = {symbol for symbol, position in broker_positions.items() if _position_qty(position) != Decimal("0")}
    entry_responses = tuple(_build_entry_response(symbol, exposed_symbols) for symbol in entry_candidate_symbols)
    protective_response = {
        "references_broker_exposure": bool(exposed_symbols),
        "covered_symbols": tuple(sorted(exposed_symbols)),
        "output_kind": "metadata_intent_only",
        "fresh_entry_authority": False,
        "submit_order_called": False,
        "cancel_order_called": False,
        "replace_order_called": False,
        "broker_mutation_called": False,
    }
    economics_advisory = {
        "output_kind": "advisory_only",
        "missing_economic_truth": (
            "arrival_price",
            "slippage",
            "net_edge",
            "fee_if_not_returned",
            "profitability_basis",
        ),
        "pnl_claimed": False,
        "slippage_claimed": False,
        "arrival_price_invented": False,
        "net_edge_claimed": False,
        "profitability_claimed": False,
        "veto_authority_active": False,
        "entry_authority_active": False,
    }

    unique_reasons = _unique(reasons)
    verdict = "PAPER_EXPOSURE_RESPONSE_READY" if not unique_reasons else "BLOCKED_WITH_REASONS"
    assert verdict not in FORBIDDEN_VERDICTS
    return ExposureResponse(
        verdict=verdict,
        reason_codes=unique_reasons,
        entry_responses=entry_responses,
        protective_response=protective_response,
        economics_advisory=economics_advisory,
        ready_for_paper_exposure_response=not unique_reasons,
    )


def _fixture_snapshot(**overrides: Any) -> PaperBrokerSnapshot:
    positions = tuple({"symbol": symbol, "qty": "0.01"} for symbol in EXPECTED_EXPOSURE_SYMBOLS)
    fields = {
        "base_url": EXPECTED_PAPER_BASE_URL,
        "account": {"id": "paper-account", "status": "ACTIVE", "currency": "USD", "cash": "99965", "buying_power": "199964.93", "equity": "99999.93"},
        "positions": positions,
        "open_orders": (),
        "recent_fills": (),
        "receive_ts_ns": 1_779_200_000_000_000_000,
    }
    fields.update(overrides)
    return PaperBrokerSnapshot(**fields)


def test_fixture_exposure_response_blocks_duplicate_entries_and_keeps_protective_economics_non_executing():
    snapshot = _fixture_snapshot()
    response = evaluate_controlled_exposure_response(
        snapshot,
        LocalRuntimeState(positions={}),
        current_ts_ns=snapshot.receive_ts_ns + 1,
        entry_candidate_symbols=("AAPL", "NVDA", "MSFT"),
    )

    by_symbol = {item["symbol"]: item for item in response.entry_responses}
    assert response.verdict == "PAPER_EXPOSURE_RESPONSE_READY"
    assert response.ready_for_paper_exposure_response is True
    assert by_symbol["AAPL"]["classification"] == "existing_exposure_requires_board_approval"
    assert by_symbol["NVDA"]["classification"] == "existing_exposure_requires_board_approval"
    assert by_symbol["MSFT"]["classification"] == "blocked_pending_portfolio_aware_board_packet"
    assert all(item["admitted"] is False for item in response.entry_responses)
    assert all(item["submit_order_called"] is False for item in response.entry_responses)
    assert response.protective_response["references_broker_exposure"] is True
    assert response.protective_response["output_kind"] == "metadata_intent_only"
    assert response.protective_response["fresh_entry_authority"] is False
    assert response.protective_response["broker_mutation_called"] is False
    assert response.economics_advisory["output_kind"] == "advisory_only"
    assert response.economics_advisory["pnl_claimed"] is False
    assert response.economics_advisory["slippage_claimed"] is False
    assert response.economics_advisory["arrival_price_invented"] is False
    assert response.economics_advisory["net_edge_claimed"] is False
    assert response.economics_advisory["profitability_claimed"] is False
    assert response.economics_advisory["veto_authority_active"] is False
    assert response.real_submit_allowed is False
    assert response.real_cancel_allowed is False
    assert response.real_replace_allowed is False
    assert response.broker_mutation_allowed is False
    assert response.live_ready is False
    assert response.live_approved is False
    assert KNOWN_26B_SKIPPED["AMD"] == "reason_not_emitted_by_existing_26b_harness"


def test_fixture_broker_no_go_context_fails_closed_for_stale_missing_conflicting_and_live_like_truth():
    clean = _fixture_snapshot()
    current_ts_ns = clean.receive_ts_ns + 1
    cases = {
        "stale_broker_snapshot": replace(clean, receive_ts_ns=current_ts_ns - MAX_SNAPSHOT_AGE_NS - 1),
        "missing_broker_positions": replace(clean, positions=()),
        "local_broker_position_conflict": clean,
        "unknown_or_nonzero_open_orders": replace(clean, open_orders=({"id": "o1", "client_order_id": "unknown", "symbol": "AAPL", "status": "new"},)),
        "orphan_broker_open_order": replace(clean, open_orders=({"id": "o1", "symbol": "AAPL", "status": "new"},)),
        "local_reservation_conflict": clean,
        "missing_account_identity": replace(clean, account={**clean.account, "id": ""}, account_id_known=False),
        "wrong_environment_or_live_like_endpoint": replace(clean, base_url=FORBIDDEN_LIVE_BASE_URL, environment="live"),
    }

    decisions = {
        "stale_broker_snapshot": evaluate_controlled_exposure_response(cases["stale_broker_snapshot"], LocalRuntimeState({}), current_ts_ns=current_ts_ns, entry_candidate_symbols=("AAPL",)),
        "missing_broker_positions": evaluate_controlled_exposure_response(cases["missing_broker_positions"], LocalRuntimeState({}), current_ts_ns=current_ts_ns, entry_candidate_symbols=("AAPL",)),
        "local_broker_position_conflict": evaluate_controlled_exposure_response(cases["local_broker_position_conflict"], LocalRuntimeState({"AAPL": Decimal("0")}), current_ts_ns=current_ts_ns, entry_candidate_symbols=("AAPL",)),
        "unknown_or_nonzero_open_orders": evaluate_controlled_exposure_response(cases["unknown_or_nonzero_open_orders"], LocalRuntimeState({}), current_ts_ns=current_ts_ns, entry_candidate_symbols=("AAPL",)),
        "orphan_broker_open_order": evaluate_controlled_exposure_response(cases["orphan_broker_open_order"], LocalRuntimeState({}), current_ts_ns=current_ts_ns, entry_candidate_symbols=("AAPL",)),
        "local_reservation_conflict": evaluate_controlled_exposure_response(cases["local_reservation_conflict"], LocalRuntimeState({}, active_reservation_client_ids=("missing-reservation",)), current_ts_ns=current_ts_ns, entry_candidate_symbols=("AAPL",)),
        "missing_account_identity": evaluate_controlled_exposure_response(cases["missing_account_identity"], LocalRuntimeState({}), current_ts_ns=current_ts_ns, entry_candidate_symbols=("AAPL",)),
        "wrong_environment_or_live_like_endpoint": evaluate_controlled_exposure_response(cases["wrong_environment_or_live_like_endpoint"], LocalRuntimeState({}), current_ts_ns=current_ts_ns, entry_candidate_symbols=("AAPL",)),
    }

    for expected_reason, decision in decisions.items():
        assert decision.verdict == "BLOCKED_WITH_REASONS"
        assert expected_reason in decision.reason_codes
        assert decision.real_submit_allowed is False
        assert decision.real_cancel_allowed is False
        assert decision.broker_mutation_allowed is False
        assert decision.live_ready is False
        assert decision.live_approved is False
        assert decision.verdict not in FORBIDDEN_VERDICTS


def test_read_only_client_and_approval_guard_reject_mutation_without_network():
    client = AlpacaPaperReadOnlyClient(EXPECTED_PAPER_BASE_URL, "key", "secret")

    client._validate_get("/v2/account", None)
    client._validate_get("/v2/orders", {"status": "open"})
    assert all(is_set is False for is_set in _approval_flags_absent().values())
    with pytest.raises(AssertionError):
        client.request_json("POST", "/v2/orders", payload={"symbol": "AAPL"})
    with pytest.raises(AssertionError):
        client.request_json("PATCH", "/v2/orders")
    with pytest.raises(AssertionError):
        client.request_json("DELETE", "/v2/orders")
    with pytest.raises(AssertionError):
        client._validate_get("/v2/orders", {"status": "closed"})
    with pytest.raises(AssertionError):
        client._validate_get("/v2/account/configurations", None)
    with pytest.raises(AssertionError):
        AlpacaPaperReadOnlyClient(FORBIDDEN_LIVE_BASE_URL, "key", "secret")._validate_get("/v2/account", None)


def test_real_alpaca_paper_exposure_response_consumes_current_broker_truth_get_only():
    assert all(is_set is False for is_set in _approval_flags_absent().values())
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
    snapshot = PaperBrokerSnapshot(
        base_url=base_url,
        account=account,
        positions=tuple(positions),
        open_orders=tuple(open_orders),
        recent_fills=tuple(item for item in activity_items if isinstance(item, dict)),
        receive_ts_ns=now_ns(),
        account_id_known=bool(account.get("id")),
    )
    response = evaluate_controlled_exposure_response(
        snapshot,
        LocalRuntimeState(positions={}),
        current_ts_ns=snapshot.receive_ts_ns + 1,
        entry_candidate_symbols=("AAPL", "NVDA", "MSFT", "AMD"),
    )
    positions_by_symbol = _positions_by_symbol(snapshot.positions)
    expected_present = tuple(symbol for symbol in EXPECTED_EXPOSURE_SYMBOLS if symbol in positions_by_symbol)

    assert client.base_url == EXPECTED_PAPER_BASE_URL
    assert all(method == "GET" for method, _path in client.calls)
    assert {path for _method, path in client.calls}.issubset(ALLOWED_GET_PATHS)
    assert ("GET", "/v2/account") in client.calls
    assert ("GET", "/v2/positions") in client.calls
    assert ("GET", "/v2/orders") in client.calls
    assert ("GET", "/v2/account/activities") in client.calls
    assert str(account.get("status") or "").upper() == "ACTIVE"
    assert set(expected_present) == set(EXPECTED_EXPOSURE_SYMBOLS)
    assert len(_active_open_orders(snapshot.open_orders)) == 0
    assert response.verdict == "PAPER_EXPOSURE_RESPONSE_READY"
    assert response.ready_for_paper_exposure_response is True
    assert response.real_submit_allowed is False
    assert response.real_cancel_allowed is False
    assert response.broker_mutation_allowed is False
    assert response.live_ready is False
    assert response.live_approved is False
    assert response.protective_response["output_kind"] == "metadata_intent_only"
    assert response.economics_advisory["output_kind"] == "advisory_only"
    assert response.economics_advisory["profitability_claimed"] is False

    positions_summary = {
        symbol: {
            "qty": position.get("qty"),
            "market_value": position.get("market_value"),
            "avg_entry_price": position.get("avg_entry_price"),
            "side": position.get("side"),
            "current_price": position.get("current_price"),
        }
        for symbol, position in positions_by_symbol.items()
        if symbol in EXPECTED_EXPOSURE_SYMBOLS
    }
    entry_responses = {item["symbol"]: item["classification"] for item in response.entry_responses}
    print(
        "ALPACA_26D_EXPOSURE_RESPONSE_SUMMARY="
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
                "entry_responses": entry_responses,
                "protective_output_kind": response.protective_response["output_kind"],
                "economics_output_kind": response.economics_advisory["output_kind"],
                "verdict": response.verdict,
                "reason_codes": response.reason_codes,
                "approval_flags_set": _approval_flags_absent(),
                "amd_gap": KNOWN_26B_SKIPPED["AMD"],
                "http_methods": sorted({method for method, _path in client.calls}),
            },
            sort_keys=True,
        )
    )
