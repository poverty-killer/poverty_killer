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
BROKER_READ_AUTH_ENV = "PK_BOARD_AUTHORIZED_PAPER_BROKER_READ"
BROKER_READ_AUTH_VALUE = "YES_D4_BOARD_AUTHORIZED"
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
class CanonicalBrokerTruth:
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

    @property
    def position_symbols(self) -> tuple[str, ...]:
        return tuple(sorted(symbol for symbol, position in _positions_by_symbol(self.positions).items() if _position_qty(position) != Decimal("0")))

    @property
    def active_open_order_count(self) -> int:
        return len(_active_open_orders(self.open_orders))

    def machine_fingerprint(self) -> dict[str, Any]:
        return {
            "account_id_known": self.account_id_known,
            "account_status": self.account.get("status"),
            "environment": self.environment,
            "position_symbols": self.position_symbols,
            "open_orders_count": len(self.open_orders),
            "active_open_orders_count": self.active_open_order_count,
            "receive_ts_ns": self.receive_ts_ns,
            "read_only": self.read_only,
            "mutation_allowed": self.mutation_allowed,
        }


@dataclass(frozen=True)
class LocalMachineState:
    positions: dict[str, Decimal]
    open_order_client_ids: tuple[str, ...] = ()
    active_reservation_client_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class IntegratedMachineVerdict:
    verdict: str
    reason_codes: tuple[str, ...]
    canonical_fingerprint: dict[str, Any]
    subsystem_fingerprints: dict[str, dict[str, Any]]
    ownership: dict[str, Any]
    exposure: dict[str, Any]
    lifecycle: dict[str, Any]
    protective: dict[str, Any]
    economics: dict[str, Any]
    readiness: dict[str, Any]
    mutation_guard: dict[str, Any]
    ready_non_mutating: bool


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
        assert method == "GET", "alpaca_26f_mutating_method_forbidden"
        assert payload is None, "alpaca_26f_payload_forbidden"
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


def _subsystem_fingerprint(truth: CanonicalBrokerTruth) -> dict[str, Any]:
    fingerprint = truth.machine_fingerprint()
    return {
        "account_id_known": fingerprint["account_id_known"],
        "account_status": fingerprint["account_status"],
        "position_symbols": fingerprint["position_symbols"],
        "active_open_orders_count": fingerprint["active_open_orders_count"],
        "receive_ts_ns": fingerprint["receive_ts_ns"],
        "read_only": fingerprint["read_only"],
        "mutation_allowed": fingerprint["mutation_allowed"],
    }


def evaluate_integrated_machine(
    truth: CanonicalBrokerTruth,
    local: LocalMachineState,
    *,
    current_ts_ns: int,
    entry_candidate_symbols: tuple[str, ...],
    exit_pressure_symbols: frozenset[str] = frozenset(),
    missing_economic_basis_symbols: frozenset[str] = frozenset(),
    protective_attempts_mutation: bool = False,
    economics_invents_profitability: bool = False,
    force_conflicting_subsystem_verdict: bool = False,
) -> IntegratedMachineVerdict:
    reasons: list[str] = []
    if truth.base_url != EXPECTED_PAPER_BASE_URL or truth.environment != "paper":
        reasons.append("wrong_environment_or_live_like_endpoint")
    if not truth.account_id_known or not truth.account.get("id"):
        reasons.append("missing_account_identity")
    if str(truth.account.get("status") or "").upper() not in {"ACTIVE", "ACCOUNT_ACTIVE"}:
        reasons.append("account_not_active")
    if not truth.read_only or truth.mutation_allowed:
        reasons.append("mutation_authority_present")
    if truth.receive_ts_ns <= 0 or current_ts_ns - truth.receive_ts_ns > MAX_SNAPSHOT_AGE_NS:
        reasons.append("stale_broker_snapshot")

    positions_by_symbol = _positions_by_symbol(truth.positions)
    if not positions_by_symbol:
        reasons.append("missing_broker_positions")
    active_orders = _active_open_orders(truth.open_orders)
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
    if missing_economic_basis_symbols:
        reasons.append("missing_fill_or_economic_basis")
    if exit_pressure_symbols:
        reasons.append("exit_intent_requires_approval")
    if protective_attempts_mutation:
        reasons.append("protective_intent_attempted_broker_mutation")
    if economics_invents_profitability:
        reasons.append("economics_attempted_profitability_invention")

    owned_symbols = set(truth.position_symbols)
    lifecycle = {
        symbol: "EXIT_INTENT_REQUIRES_APPROVAL" if symbol in exit_pressure_symbols else "HELD"
        for symbol in truth.position_symbols
    }
    ownership = {
        "canonical_source": "alpaca_paper_broker_truth",
        "owned_symbols": truth.position_symbols,
        "expected_symbols_present": tuple(symbol for symbol in EXPECTED_POSITION_SYMBOLS if symbol in owned_symbols),
        "missing_expected_symbols": tuple(symbol for symbol in EXPECTED_POSITION_SYMBOLS if symbol not in owned_symbols),
        "extra_symbols": tuple(symbol for symbol in truth.position_symbols if symbol not in EXPECTED_POSITION_SYMBOLS),
        "local_state_supporting_only": True,
        "broker_truth_canonical": True,
    }
    exposure = {
        "entry_candidates": entry_candidate_symbols,
        "entry_results": {
            symbol: "EXISTING_EXPOSURE_REQUIRES_APPROVAL_FOR_ADDON"
            if symbol in owned_symbols
            else "NEW_ENTRY_BLOCKED_BY_26F_MACHINE_SCOPE"
            for symbol in entry_candidate_symbols
        },
        "admitted_symbols": (),
        "submit_called": False,
        "route_called": False,
        "broker_mutation_called": False,
    }
    protective = {
        "verdict": "PROTECTIVE_INTENT_METADATA_ONLY",
        "consumed_lifecycle": lifecycle,
        "authorizes_fresh_entry": False,
        "authorizes_sell": False,
        "authorizes_cancel": False,
        "authorizes_replace": False,
        "broker_mutation_called": False,
    }
    economics = {
        "verdict": "ECONOMICS_ADVISORY_MISSING_TRUTH",
        "consumed_symbols": truth.position_symbols,
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
    readiness = {
        "live_ready": False,
        "live_approved": False,
        "paper_machine_non_mutating": True,
        "new_orders_require_future_board_packet": True,
        "exits_require_future_board_packet": True,
        "reason_codes": (),
    }
    mutation_guard = {
        "post_called": False,
        "patch_called": False,
        "delete_called": False,
        "cancel_called": False,
        "replace_called": False,
        "sell_called": False,
        "rebalance_called": False,
        "approval_flags_required": False,
        "live_mode": False,
        "broker_adapter_active_authority": False,
        "live_broker_active_authority": False,
        "live_reservation_lifecycle_opened": False,
        "dormant_governors_authority_active": False,
    }

    canonical_fingerprint = truth.machine_fingerprint()
    subsystem_fingerprints = {
        name: _subsystem_fingerprint(truth)
        for name in (
            "ownership",
            "exposure",
            "lifecycle",
            "protective",
            "economics",
            "readiness",
            "mutation_guard",
        )
    }
    if force_conflicting_subsystem_verdict:
        subsystem_fingerprints["economics"] = {**subsystem_fingerprints["economics"], "position_symbols": ("FAKE",)}
    if any(fingerprint != _subsystem_fingerprint(truth) for fingerprint in subsystem_fingerprints.values()):
        reasons.append("conflicting_subsystem_verdicts")

    unique_reasons = _unique(reasons)
    readiness["reason_codes"] = unique_reasons
    if "exit_intent_requires_approval" in unique_reasons:
        verdict = "EXIT_DEFENSE_EVIDENCE_ONLY"
    elif "stale_broker_snapshot" in unique_reasons:
        verdict = "BLOCKED_STALE_BROKER_TRUTH"
    elif "broker_local_position_conflict" in unique_reasons:
        verdict = "BLOCKED_CONFLICTING_POSITION_TRUTH"
    elif "nonzero_unknown_open_orders" in unique_reasons:
        verdict = "BLOCKED_UNKNOWN_OPEN_ORDER"
    elif "mutation_authority_present" in unique_reasons or "protective_intent_attempted_broker_mutation" in unique_reasons:
        verdict = "BLOCKED_MUTATION_AUTHORITY_ABSENT"
    elif unique_reasons:
        verdict = "BLOCKED_MISSING_BROKER_TRUTH"
    else:
        verdict = "PAPER_PORTFOLIO_MACHINE_READY_NON_MUTATING"
    assert verdict not in FORBIDDEN_VERDICTS
    return IntegratedMachineVerdict(
        verdict=verdict,
        reason_codes=unique_reasons,
        canonical_fingerprint=canonical_fingerprint,
        subsystem_fingerprints=subsystem_fingerprints,
        ownership=ownership,
        exposure=exposure,
        lifecycle={"states": lifecycle, "exit_pressure_symbols": tuple(sorted(exit_pressure_symbols))},
        protective=protective,
        economics=economics,
        readiness=readiness,
        mutation_guard=mutation_guard,
        ready_non_mutating=not unique_reasons,
    )


def _fixture_truth(**overrides: Any) -> CanonicalBrokerTruth:
    fields = {
        "base_url": EXPECTED_PAPER_BASE_URL,
        "account": {"id": "paper-account", "status": "ACTIVE", "currency": "USD", "cash": "99965", "buying_power": "199965.03", "equity": "100000.03"},
        "positions": tuple({"symbol": symbol, "qty": "0.01"} for symbol in EXPECTED_POSITION_SYMBOLS),
        "open_orders": (),
        "recent_fills": (),
        "receive_ts_ns": 1_779_220_000_000_000_000,
    }
    fields.update(overrides)
    return CanonicalBrokerTruth(**fields)


def test_fixture_integrated_machine_consumes_one_canonical_truth_without_contradiction():
    truth = _fixture_truth()
    machine = evaluate_integrated_machine(
        truth,
        LocalMachineState(positions={}),
        current_ts_ns=truth.receive_ts_ns + 1,
        entry_candidate_symbols=("AAPL", "NVDA", "MSFT", "AMD"),
    )

    assert machine.verdict == "PAPER_PORTFOLIO_MACHINE_READY_NON_MUTATING"
    assert machine.ready_non_mutating is True
    assert set(machine.ownership["owned_symbols"]) == set(EXPECTED_POSITION_SYMBOLS)
    assert machine.exposure["entry_results"]["AAPL"] == "EXISTING_EXPOSURE_REQUIRES_APPROVAL_FOR_ADDON"
    assert machine.exposure["entry_results"]["NVDA"] == "EXISTING_EXPOSURE_REQUIRES_APPROVAL_FOR_ADDON"
    assert machine.exposure["entry_results"]["MSFT"] == "NEW_ENTRY_BLOCKED_BY_26F_MACHINE_SCOPE"
    assert machine.exposure["entry_results"]["AMD"] == "NEW_ENTRY_BLOCKED_BY_26F_MACHINE_SCOPE"
    assert set(machine.lifecycle["states"].values()) == {"HELD"}
    assert machine.protective["verdict"] == "PROTECTIVE_INTENT_METADATA_ONLY"
    assert machine.economics["verdict"] == "ECONOMICS_ADVISORY_MISSING_TRUTH"
    assert machine.readiness["paper_machine_non_mutating"] is True
    assert all(fingerprint == _subsystem_fingerprint(truth) for fingerprint in machine.subsystem_fingerprints.values())
    assert machine.mutation_guard["post_called"] is False
    assert machine.mutation_guard["sell_called"] is False
    assert machine.mutation_guard["live_mode"] is False
    assert machine.economics["profitability_claimed"] is False
    assert AMD_SKIP_GAP == "reason_not_emitted_by_existing_26b_harness"


def test_fixture_integrated_machine_fail_closed_cases_without_network():
    clean = _fixture_truth()
    current_ts_ns = clean.receive_ts_ns + 1
    cases = {
        "stale_broker_snapshot": (replace(clean, receive_ts_ns=current_ts_ns - MAX_SNAPSHOT_AGE_NS - 1), LocalMachineState({}), {}),
        "missing_broker_positions": (replace(clean, positions=()), LocalMachineState({}), {}),
        "broker_local_position_conflict": (clean, LocalMachineState({"AAPL": Decimal("0")}), {}),
        "nonzero_unknown_open_orders": (
            replace(clean, open_orders=({"id": "o1", "client_order_id": "unknown", "symbol": "AAPL", "status": "new"},)),
            LocalMachineState({}),
            {},
        ),
        "orphan_broker_open_order": (
            replace(clean, open_orders=({"id": "o1", "symbol": "AAPL", "status": "new"},)),
            LocalMachineState({}),
            {},
        ),
        "local_reservation_conflict": (clean, LocalMachineState({}, active_reservation_client_ids=("res-1",)), {}),
        "missing_account_identity": (replace(clean, account={**clean.account, "id": ""}, account_id_known=False), LocalMachineState({}), {}),
        "wrong_environment_or_live_like_endpoint": (replace(clean, base_url=FORBIDDEN_LIVE_BASE_URL, environment="live"), LocalMachineState({}), {}),
        "missing_fill_or_economic_basis": (clean, LocalMachineState({}), {"missing_economic_basis_symbols": frozenset({"NVDA"})}),
        "exit_intent_requires_approval": (clean, LocalMachineState({}), {"exit_pressure_symbols": frozenset({"AAPL"})}),
        "protective_intent_attempted_broker_mutation": (clean, LocalMachineState({}), {"protective_attempts_mutation": True}),
        "economics_attempted_profitability_invention": (clean, LocalMachineState({}), {"economics_invents_profitability": True}),
        "conflicting_subsystem_verdicts": (clean, LocalMachineState({}), {"force_conflicting_subsystem_verdict": True}),
    }

    for expected_reason, (truth, local, kwargs) in cases.items():
        machine = evaluate_integrated_machine(
            truth,
            local,
            current_ts_ns=current_ts_ns,
            entry_candidate_symbols=("AAPL",),
            **kwargs,
        )
        assert expected_reason in machine.reason_codes
        assert machine.verdict != "PAPER_PORTFOLIO_MACHINE_READY_NON_MUTATING"
        assert machine.verdict not in FORBIDDEN_VERDICTS
        assert machine.mutation_guard["post_called"] is False
        assert machine.mutation_guard["sell_called"] is False
        assert machine.readiness["live_ready"] is False
        assert machine.economics["profitability_claimed"] is False


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


@pytest.mark.broker_read
def test_real_alpaca_paper_integrated_machine_loop_get_only():
    if os.environ.get(BROKER_READ_AUTH_ENV) != BROKER_READ_AUTH_VALUE:
        pytest.skip(f"broker read deferred; requires {BROKER_READ_AUTH_ENV}={BROKER_READ_AUTH_VALUE}")
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
    truth = CanonicalBrokerTruth(
        base_url=base_url,
        account=account,
        positions=tuple(positions),
        open_orders=tuple(open_orders),
        recent_fills=tuple(item for item in activity_items if isinstance(item, dict)),
        receive_ts_ns=now_ns(),
        account_id_known=bool(account.get("id")),
    )
    machine = evaluate_integrated_machine(
        truth,
        LocalMachineState(positions={}),
        current_ts_ns=truth.receive_ts_ns + 1,
        entry_candidate_symbols=("AAPL", "NVDA", "MSFT", "AMD"),
    )
    positions_by_symbol = _positions_by_symbol(truth.positions)
    expected_present = tuple(symbol for symbol in EXPECTED_POSITION_SYMBOLS if symbol in positions_by_symbol)

    assert client.base_url == EXPECTED_PAPER_BASE_URL
    assert all(method == "GET" for method, _path in client.calls)
    assert {path for _method, path in client.calls}.issubset(ALLOWED_GET_PATHS)
    assert str(account.get("status") or "").upper() == "ACTIVE"
    assert set(expected_present) == set(EXPECTED_POSITION_SYMBOLS)
    assert len(_active_open_orders(truth.open_orders)) == 0
    assert machine.verdict == "PAPER_PORTFOLIO_MACHINE_READY_NON_MUTATING"
    assert machine.ready_non_mutating is True
    assert all(fingerprint == _subsystem_fingerprint(truth) for fingerprint in machine.subsystem_fingerprints.values())
    assert machine.exposure["entry_results"]["AAPL"] == "EXISTING_EXPOSURE_REQUIRES_APPROVAL_FOR_ADDON"
    assert set(machine.lifecycle["states"].values()) == {"HELD"}
    assert machine.protective["broker_mutation_called"] is False
    assert machine.economics["profitability_claimed"] is False
    assert machine.mutation_guard["post_called"] is False
    assert machine.mutation_guard["sell_called"] is False
    assert machine.readiness["live_ready"] is False

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
        "ALPACA_26F_INTEGRATED_MACHINE_SUMMARY="
        + json.dumps(
            {
                "account_status": account.get("status"),
                "cash": account.get("cash"),
                "buying_power": account.get("buying_power"),
                "equity": account.get("equity"),
                "portfolio_value": account.get("portfolio_value"),
                "open_orders_count": len(truth.open_orders),
                "active_open_orders_count": len(_active_open_orders(truth.open_orders)),
                "positions_count": len(truth.positions),
                "expected_positions_present": expected_present,
                "positions": positions_summary,
                "machine_fingerprint": truth.machine_fingerprint(),
                "subsystem_fingerprints_match": all(
                    fingerprint == _subsystem_fingerprint(truth) for fingerprint in machine.subsystem_fingerprints.values()
                ),
                "ownership": machine.ownership,
                "entry_results": machine.exposure["entry_results"],
                "lifecycle": machine.lifecycle["states"],
                "protective_verdict": machine.protective["verdict"],
                "economics_verdict": machine.economics["verdict"],
                "readiness": machine.readiness,
                "mutation_guard": machine.mutation_guard,
                "verdict": machine.verdict,
                "reason_codes": machine.reason_codes,
                "approval_flags_armed": _approval_flags_armed(),
                "amd_gap": AMD_SKIP_GAP,
                "http_methods": sorted({method for method, _path in client.calls}),
            },
            sort_keys=True,
        )
    )
