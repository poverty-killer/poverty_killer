from __future__ import annotations

import inspect
import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.execution.live_read_only_adapter import LiveReadOnlyBrokerAdapter
from app.execution.order_router import OrderRouter
from app.risk.net_edge_governor import NetEdgeGovernor
from app.risk.trade_efficiency_governor import TradeEfficiencyGovernor


EXPECTED_PAPER_BASE_URL = "https://paper-api.alpaca.markets"
FORBIDDEN_LIVE_BASE_URL = "https://api.alpaca.markets"
ALLOWED_GET_PATHS = frozenset({"/v2/account", "/v2/positions", "/v2/orders", "/v2/clock"})
T0_NS = 1_777_948_800_000_000_000


@dataclass(frozen=True)
class TinyOrderPlan:
    broker: str = "alpaca"
    environment: str = "paper"
    base_url: str = EXPECTED_PAPER_BASE_URL
    symbol: str = "AAPL"
    side: str = "buy"
    order_type: str = "limit"
    time_in_force: str = "day"
    max_notional_usd: Decimal | None = Decimal("5.00")
    quantity_rule: str = "derive_from_read_only_quote_in_future_execution_packet"
    limit_price_rule: str = "derive_bounded_limit_from_fresh_read_only_quote_in_future_execution_packet"
    extended_hours: bool = False
    short_selling: bool = False
    bracket_oco_oto: bool = False
    margin_or_leverage: bool = False
    order_count: int = 1
    symbols: tuple[str, ...] = ("AAPL",)
    retry_policy: str = "no_retry_no_auto_resubmit"
    future_endpoint: str = "/v2/orders"
    client_order_id_prefix: str = "pk25z-paper-aapl-buy-limit-day"


@dataclass(frozen=True)
class BrokerPreflight:
    endpoint_exact_paper: bool = True
    credentials_present: bool = True
    account_reachable: bool = True
    account_status: str = "ACTIVE"
    trading_blocked: bool = False
    currency: str | None = "USD"
    cash: Decimal | None = Decimal("1000.00")
    buying_power: Decimal | None = Decimal("1000.00")
    open_orders: tuple[dict[str, Any], ...] = ()
    positions: tuple[dict[str, Any], ...] = ()
    read_only_methods: tuple[str, ...] = ("GET",)


@dataclass(frozen=True)
class LocalArmingState:
    board_approval_id: str | None = "BOARD-25Y-PLAN-ONLY"
    operator_approval_id: str | None = "OPERATOR-25Y-PLAN-ONLY"
    kill_switch_clear: bool = True
    local_reservations: tuple[dict[str, Any], ...] = ()
    broker_adapter_activated: bool = False
    live_broker_activated: bool = False
    live_mode: bool = False
    live_reservation_lifecycle_enabled: bool = False
    pending_runtime_order_intent: bool = False
    paper_broker_durable_state_clean_or_isolated: bool = True


@dataclass(frozen=True)
class TelemetryPlan:
    decision_intent_id_format: str | None = "pk25z:{symbol}:{side}:{tif}:{ts_ns}"
    client_order_id_format: str | None = "pk25z-paper-aapl-buy-limit-day-{ts_ns}"
    fill_recorder_fields: tuple[str, ...] = (
        "client_order_id",
        "broker_order_id",
        "symbol",
        "side",
        "quantity",
        "fill_price",
        "fill_ts_ns",
        "commission",
        "source",
    )
    reservation_candidate_fields: tuple[str, ...] = (
        "decision_uuid",
        "client_order_id",
        "symbol",
        "side",
        "quantity",
        "price_basis",
        "notional_basis",
    )
    recovery_snapshot_fields: tuple[str, ...] = (
        "read_only_broker_snapshot",
        "local_reservation_ledger",
        "order_lifecycle_replay_context",
    )
    post_order_reconciliation_steps: tuple[str, ...] = (
        "GET /v2/orders?status=open",
        "GET /v2/positions",
        "GET /v2/account",
    )


@dataclass(frozen=True)
class ArmingDecision:
    armed_for_future_packet: bool
    order_placed: bool
    cancel_sent: bool
    replace_sent: bool
    mutation_attempted: bool
    live_mode_used: bool
    reason_codes: tuple[str, ...]
    future_endpoint: str
    preflight_gets_required: tuple[str, ...]


class AlpacaPlanningReadOnlyClient:
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
            raise AssertionError(f"alpaca_read_only_http_error:{exc.code}:{path}") from None
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            pytest.skip(f"Alpaca PAPER read-only preflight unavailable: {type(exc).__name__}")

    def _validate_get(self, path: str, query: dict[str, str] | None) -> None:
        assert self.base_url == EXPECTED_PAPER_BASE_URL
        assert self.base_url != FORBIDDEN_LIVE_BASE_URL
        assert path in ALLOWED_GET_PATHS
        assert path != "/v2/orders" or (query or {}).get("status") == "open"
        blocked_fragments = ("submit", "cancel", "replace", "close", "liquidate")
        assert not any(fragment in path.lower() for fragment in blocked_fragments)


class MutationTrap:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def post(self, url: str, **_kwargs: Any) -> None:
        self.calls.append(("POST", url))
        raise AssertionError("mutation_attempted_in_25y")

    def delete(self, url: str, **_kwargs: Any) -> None:
        self.calls.append(("DELETE", url))
        raise AssertionError("mutation_attempted_in_25y")

    def patch(self, url: str, **_kwargs: Any) -> None:
        self.calls.append(("PATCH", url))
        raise AssertionError("mutation_attempted_in_25y")


def _decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    return Decimal(str(value))


def _env_or_skip() -> tuple[str, str, str]:
    base_url = (os.environ.get("APCA_API_BASE_URL") or "").rstrip("/")
    key_id = os.environ.get("APCA_API_KEY_ID") or ""
    secret_key = os.environ.get("APCA_API_SECRET_KEY") or ""
    if not base_url or not key_id or not secret_key:
        pytest.skip("Alpaca PAPER read-only env missing")
    if base_url != EXPECTED_PAPER_BASE_URL:
        pytest.fail(f"APCA_API_BASE_URL is not exact paper endpoint: {base_url!r}")
    return base_url, key_id, secret_key


def _unique(reasons: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(reasons))


def _symbol_order_conflict(plan: TinyOrderPlan, orders: tuple[dict[str, Any], ...]) -> bool:
    return any((order.get("symbol") or "").upper() == plan.symbol for order in orders)


def _symbol_position_conflict(plan: TinyOrderPlan, positions: tuple[dict[str, Any], ...]) -> bool:
    for position in positions:
        if (position.get("symbol") or "").upper() != plan.symbol:
            continue
        qty = _decimal_or_none(position.get("quantity") or position.get("qty"))
        if qty and qty != Decimal("0"):
            return True
    return False


def validate_tiny_order_arming(
    plan: TinyOrderPlan,
    broker: BrokerPreflight,
    local: LocalArmingState,
    telemetry: TelemetryPlan,
) -> ArmingDecision:
    reasons: list[str] = []

    if plan.broker != "alpaca":
        reasons.append("broker_must_be_alpaca")
    if plan.environment != "paper" or plan.base_url != EXPECTED_PAPER_BASE_URL:
        reasons.append("paper_endpoint_required")
    if plan.base_url == FORBIDDEN_LIVE_BASE_URL:
        reasons.append("live_endpoint_forbidden")
    if plan.symbol != "AAPL" or plan.symbols != ("AAPL",):
        reasons.append("single_explicit_aapl_symbol_required")
    if plan.side != "buy":
        reasons.append("short_order_forbidden")
    if plan.order_type != "limit":
        reasons.append("market_order_forbidden")
    if plan.time_in_force != "day":
        reasons.append("time_in_force_day_required")
    if plan.max_notional_usd is None:
        reasons.append("max_notional_missing")
    else:
        if plan.max_notional_usd <= Decimal("0"):
            reasons.append("max_notional_invalid")
        if plan.max_notional_usd > Decimal("5.00"):
            reasons.append("max_notional_too_high")
    if plan.order_count != 1:
        reasons.append("single_order_required")
    if len(set(plan.symbols)) != 1:
        reasons.append("single_symbol_required")
    if plan.extended_hours:
        reasons.append("extended_hours_forbidden")
    if plan.bracket_oco_oto:
        reasons.append("bracket_oco_oto_forbidden")
    if plan.margin_or_leverage:
        reasons.append("margin_leverage_forbidden")
    if plan.retry_policy != "no_retry_no_auto_resubmit":
        reasons.append("retry_auto_resubmit_forbidden")
    if plan.limit_price_rule != "derive_bounded_limit_from_fresh_read_only_quote_in_future_execution_packet":
        reasons.append("bounded_limit_price_rule_required")
    if plan.quantity_rule != "derive_from_read_only_quote_in_future_execution_packet":
        reasons.append("quantity_rule_must_defer_to_future_quote")
    if plan.future_endpoint != "/v2/orders":
        reasons.append("future_endpoint_must_be_v2_orders")

    if local.board_approval_id is None:
        reasons.append("missing_board_approval")
    if local.operator_approval_id is None:
        reasons.append("missing_operator_approval")
    if not local.kill_switch_clear:
        reasons.append("kill_switch_active")
    if local.live_mode:
        reasons.append("live_mode_forbidden")
    if local.live_reservation_lifecycle_enabled:
        reasons.append("live_reservation_lifecycle_enabled")
    if local.broker_adapter_activated:
        reasons.append("broker_adapter_activation_forbidden")
    if local.live_broker_activated:
        reasons.append("live_broker_activation_forbidden")
    if local.pending_runtime_order_intent:
        reasons.append("pending_runtime_order_intent_forbidden")
    if not local.paper_broker_durable_state_clean_or_isolated:
        reasons.append("paper_broker_durable_state_not_clean_or_isolated")
    if any((reservation.get("symbol") or "").upper() == plan.symbol for reservation in local.local_reservations):
        reasons.append("local_reservation_without_broker_order")

    if not broker.endpoint_exact_paper:
        reasons.append("paper_endpoint_required")
    if not broker.credentials_present:
        reasons.append("alpaca_paper_credentials_missing")
    if not broker.account_reachable:
        reasons.append("account_endpoint_unavailable")
    if broker.account_status and broker.account_status.upper() not in {"ACTIVE", "ACCOUNT_ACTIVE"}:
        reasons.append("account_status_blocked")
    if broker.trading_blocked:
        reasons.append("account_trading_blocked")
    if not broker.currency:
        reasons.append("broker_currency_missing")
    if broker.cash is None and broker.buying_power is None:
        reasons.append("cash_or_buying_power_missing")
    if not set(broker.read_only_methods).issubset({"GET"}):
        reasons.append("read_only_preflight_get_only_required")
    if _symbol_order_conflict(plan, broker.open_orders):
        reasons.append("open_broker_order_for_planned_symbol")
    if _symbol_position_conflict(plan, broker.positions):
        reasons.append("broker_position_exists_but_plan_assumes_flat")

    if not telemetry.decision_intent_id_format:
        reasons.append("missing_decision_intent_id_plan")
    if not telemetry.client_order_id_format:
        reasons.append("missing_client_order_id_plan")
    required_fill_fields = {"client_order_id", "broker_order_id", "symbol", "side", "quantity", "fill_price", "fill_ts_ns"}
    if not required_fill_fields.issubset(set(telemetry.fill_recorder_fields)):
        reasons.append("missing_fill_recorder_fields_plan")
    if not telemetry.reservation_candidate_fields:
        reasons.append("missing_reservation_candidate_plan")
    if not telemetry.recovery_snapshot_fields:
        reasons.append("missing_recovery_snapshot_plan")
    if not telemetry.post_order_reconciliation_steps:
        reasons.append("missing_post_order_reconciliation_plan")

    unique = _unique(reasons)
    return ArmingDecision(
        armed_for_future_packet=not unique,
        order_placed=False,
        cancel_sent=False,
        replace_sent=False,
        mutation_attempted=False,
        live_mode_used=False,
        reason_codes=unique,
        future_endpoint=plan.future_endpoint,
        preflight_gets_required=("/v2/account", "/v2/positions", "/v2/orders?status=open", "/v2/clock"),
    )


def _clean_decision() -> ArmingDecision:
    decision = validate_tiny_order_arming(TinyOrderPlan(), BrokerPreflight(), LocalArmingState(), TelemetryPlan())
    assert decision.armed_for_future_packet is True
    assert decision.order_placed is False
    assert decision.mutation_attempted is False
    return decision


def test_tiny_alpaca_paper_order_plan_is_complete_and_non_mutating():
    plan = TinyOrderPlan()
    decision = _clean_decision()

    assert plan.broker == "alpaca"
    assert plan.environment == "paper"
    assert plan.base_url == EXPECTED_PAPER_BASE_URL
    assert plan.symbol == "AAPL"
    assert plan.side == "buy"
    assert plan.order_type == "limit"
    assert plan.time_in_force == "day"
    assert plan.max_notional_usd == Decimal("5.00")
    assert plan.quantity_rule == "derive_from_read_only_quote_in_future_execution_packet"
    assert plan.limit_price_rule == "derive_bounded_limit_from_fresh_read_only_quote_in_future_execution_packet"
    assert plan.extended_hours is False
    assert plan.short_selling is False
    assert plan.bracket_oco_oto is False
    assert plan.margin_or_leverage is False
    assert plan.order_count == 1
    assert plan.retry_policy == "no_retry_no_auto_resubmit"
    assert decision.future_endpoint == "/v2/orders"
    assert decision.preflight_gets_required == ("/v2/account", "/v2/positions", "/v2/orders?status=open", "/v2/clock")
    assert decision.order_placed is False
    assert decision.cancel_sent is False
    assert decision.replace_sent is False
    assert decision.live_mode_used is False


def test_optional_real_alpaca_paper_read_only_preflight_can_feed_arming_without_mutation():
    base_url, key_id, secret_key = _env_or_skip()
    client = AlpacaPlanningReadOnlyClient(base_url, key_id, secret_key)

    account = client.get_json("/v2/account")
    client.get_json("/v2/clock")
    positions = client.get_json("/v2/positions")
    orders = client.get_json("/v2/orders", {"status": "open", "limit": "50", "nested": "false"})

    broker = BrokerPreflight(
        endpoint_exact_paper=client.base_url == EXPECTED_PAPER_BASE_URL,
        credentials_present=True,
        account_reachable=bool(account),
        account_status=str(account.get("status") or "ACTIVE"),
        trading_blocked=bool(account.get("trading_blocked") or account.get("account_blocked")),
        currency=account.get("currency") or "USD",
        cash=_decimal_or_none(account.get("cash")),
        buying_power=_decimal_or_none(account.get("buying_power")),
        open_orders=tuple({"symbol": item.get("symbol"), "client_order_id": item.get("client_order_id"), "broker_order_id": item.get("id")} for item in orders),
        positions=tuple({"symbol": item.get("symbol"), "quantity": _decimal_or_none(item.get("qty"))} for item in positions),
    )
    decision = validate_tiny_order_arming(TinyOrderPlan(), broker, LocalArmingState(), TelemetryPlan())

    assert all(method == "GET" for method, _path in client.calls)
    assert {path for _method, path in client.calls}.issubset(ALLOWED_GET_PATHS)
    assert ("GET", "/v2/orders") in client.calls
    assert decision.order_placed is False
    assert decision.cancel_sent is False
    assert decision.replace_sent is False
    assert decision.mutation_attempted is False
    if _symbol_order_conflict(TinyOrderPlan(), broker.open_orders) or _symbol_position_conflict(TinyOrderPlan(), broker.positions):
        assert decision.armed_for_future_packet is False
        assert set(decision.reason_codes) & {"open_broker_order_for_planned_symbol", "broker_position_exists_but_plan_assumes_flat"}


def test_no_go_blockers_fail_closed_before_future_execution_packet():
    clean_plan = TinyOrderPlan()
    clean_broker = BrokerPreflight()
    clean_local = LocalArmingState()
    clean_telemetry = TelemetryPlan()

    cases = [
        ("market_order_forbidden", replace(clean_plan, order_type="market")),
        ("paper_endpoint_required", replace(clean_plan, base_url=FORBIDDEN_LIVE_BASE_URL, environment="live")),
        ("missing_board_approval", clean_plan, clean_broker, replace(clean_local, board_approval_id=None), clean_telemetry),
        ("missing_operator_approval", clean_plan, clean_broker, replace(clean_local, operator_approval_id=None), clean_telemetry),
        ("kill_switch_active", clean_plan, clean_broker, replace(clean_local, kill_switch_clear=False), clean_telemetry),
        ("max_notional_too_high", replace(clean_plan, max_notional_usd=Decimal("25.00"))),
        ("single_order_required", replace(clean_plan, order_count=2)),
        ("single_symbol_required", replace(clean_plan, symbols=("AAPL", "MSFT"))),
        ("open_broker_order_for_planned_symbol", clean_plan, replace(clean_broker, open_orders=({"symbol": "AAPL", "client_order_id": "broker-only", "broker_order_id": "order-1"},)), clean_local, clean_telemetry),
        ("broker_position_exists_but_plan_assumes_flat", clean_plan, replace(clean_broker, positions=({"symbol": "AAPL", "quantity": Decimal("1")},)), clean_local, clean_telemetry),
        ("missing_decision_intent_id_plan", clean_plan, clean_broker, clean_local, replace(clean_telemetry, decision_intent_id_format=None)),
        ("missing_client_order_id_plan", clean_plan, clean_broker, clean_local, replace(clean_telemetry, client_order_id_format=None)),
        ("live_reservation_lifecycle_enabled", clean_plan, clean_broker, replace(clean_local, live_reservation_lifecycle_enabled=True), clean_telemetry),
        ("broker_adapter_activation_forbidden", clean_plan, clean_broker, replace(clean_local, broker_adapter_activated=True), clean_telemetry),
        ("live_broker_activation_forbidden", clean_plan, clean_broker, replace(clean_local, live_broker_activated=True), clean_telemetry),
        ("local_reservation_without_broker_order", clean_plan, clean_broker, replace(clean_local, local_reservations=({"symbol": "AAPL", "client_order_id": "local-only"},)), clean_telemetry),
        ("alpaca_paper_credentials_missing", clean_plan, replace(clean_broker, credentials_present=False), clean_local, clean_telemetry),
        ("account_endpoint_unavailable", clean_plan, replace(clean_broker, account_reachable=False), clean_local, clean_telemetry),
        ("account_status_blocked", clean_plan, replace(clean_broker, account_status="BLOCKED"), clean_local, clean_telemetry),
        ("cash_or_buying_power_missing", clean_plan, replace(clean_broker, cash=None, buying_power=None), clean_local, clean_telemetry),
    ]

    for case in cases:
        expected = case[0]
        plan = case[1] if len(case) > 1 else clean_plan
        broker = case[2] if len(case) > 2 else clean_broker
        local = case[3] if len(case) > 3 else clean_local
        telemetry = case[4] if len(case) > 4 else clean_telemetry
        decision = validate_tiny_order_arming(plan, broker, local, telemetry)
        assert decision.armed_for_future_packet is False, expected
        assert expected in decision.reason_codes
        assert decision.order_placed is False
        assert decision.mutation_attempted is False


def test_attempted_mutation_is_trapped_and_never_part_of_25y_arming():
    trap = MutationTrap()

    with pytest.raises(AssertionError, match="mutation_attempted_in_25y"):
        trap.post(f"{EXPECTED_PAPER_BASE_URL}/v2/orders", json={"symbol": "AAPL"})
    with pytest.raises(AssertionError, match="mutation_attempted_in_25y"):
        trap.delete(f"{EXPECTED_PAPER_BASE_URL}/v2/orders/order-1")
    with pytest.raises(AssertionError, match="mutation_attempted_in_25y"):
        trap.patch(f"{EXPECTED_PAPER_BASE_URL}/v2/orders/order-1", json={"qty": "1"})

    assert trap.calls == [
        ("POST", f"{EXPECTED_PAPER_BASE_URL}/v2/orders"),
        ("DELETE", f"{EXPECTED_PAPER_BASE_URL}/v2/orders/order-1"),
        ("PATCH", f"{EXPECTED_PAPER_BASE_URL}/v2/orders/order-1"),
    ]
    decision = _clean_decision()
    assert decision.order_placed is False
    assert decision.cancel_sent is False
    assert decision.replace_sent is False


def test_authority_surfaces_remain_unactivated_for_planning_only_packet():
    protected_sources = (
        inspect.getsource(LiveReadOnlyBrokerAdapter),
        inspect.getsource(NetEdgeGovernor),
        inspect.getsource(TradeEfficiencyGovernor),
        Path("app/execution/broker_adapter.py").read_text(encoding="utf-8-sig"),
        Path("app/execution/live_broker.py").read_text(encoding="utf-8-sig"),
    )
    assert "PRE-INTEGRATION" in protected_sources[3]
    assert "NO IMPLEMENTATION" in protected_sources[3]
    assert "Under construction" in protected_sources[4]
    assert hasattr(OrderRouter, "submit_order")

    for source in protected_sources:
        assert "SovereignExecutionGuard" not in source
        assert "StrategyAllocator" not in source
        assert "SovereignGovernor" not in source

    plan_source = inspect.getsource(validate_tiny_order_arming)
    assert "urlopen" not in plan_source
    assert ".post(" not in plan_source
    assert ".delete(" not in plan_source
    assert ".patch(" not in plan_source
