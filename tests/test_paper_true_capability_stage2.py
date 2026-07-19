from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal
import sqlite3
from types import SimpleNamespace
from typing import Any

import pytest

from app.api.operator_paper_supervisor import OperatorPaperSupervisor, PaperSupervisorConfig
from app.execution.broker_gateway import (
    BrokerAdapterIdentity,
    BrokerGatewayResponse,
    NormalizedBrokerStatus,
)
from app.execution.order_router import OrderRouter
from app.main_loop import (
    _apply_portfolio_risk_gate_to_signal,
    _build_pre_trade_guardrail_verdict,
)
from app.models import OrderRequest
from app.models.enums import OrderSide, OrderType, SleeveType
from app.operator_activation.paper_baseline import (
    PAPER_BASELINE_DRIFT_REQUIRES_REFRESH,
    PREFLIGHT_READY_WITH_ACCEPTED_EXISTING_POSITIONS,
    PaperBaselineStore,
    accept_existing_position_baseline,
    build_baseline_adoption_state,
    build_paper_baseline_runtime_context,
)
from app.risk.exposure_manager import ExposureManager
from app.risk.reservation_lifecycle_coordinator import ReservationLifecycleCoordinator
from app.risk.stale_data_guard import StaleDataGuard, TemporalInput
from app.state.state_store import StateStore


ACCOUNT_ID = "paper-account-045ded"
ACCOUNT_SUFFIX = "045ded"
BASELINE_ID = "paper-baseline-stage2"
FOUR_POSITIONS = (
    ("AVAXUSD", "10.125", "20.50", "21.00"),
    ("ETHUSD", "2.250000000000000001", "3100.25", "3120.50"),
    ("LINKUSD", "25.75", "14.10", "14.30"),
    ("SOLUSD", "8.875", "142.40", "144.20"),
)


def _baseline_context(rows=FOUR_POSITIONS, *, baseline_id: str = BASELINE_ID) -> dict[str, Any]:
    return {
        "baseline_required": True,
        "baseline_loaded": True,
        "baseline_snapshot_id": baseline_id,
        "account_suffix": ACCOUNT_SUFFIX,
        "policy": "ADOPT_EXISTING_POSITIONS_PROTECTED",
        "protected_symbols_normalized": [row[0] for row in rows],
        "protected_positions": {
            row[0]: {
                "symbol": row[0],
                "normalized_symbol": row[0],
                "qty": row[1],
                "side": "long",
                "asset_class": "crypto",
                "avg_entry_price": row[2],
                "baseline_position": True,
            }
            for row in rows
        },
    }


def _broker_positions(rows=FOUR_POSITIONS) -> list[dict[str, str]]:
    return [
        {
            "symbol": symbol,
            "qty": qty,
            "avg_entry_price": avg_entry_price,
            "current_price": current_price,
            "asset_class": "crypto",
            "side": "long",
        }
        for symbol, qty, avg_entry_price, current_price in rows
    ]


def _account(*, account_id: str = ACCOUNT_ID, cash: str = "990000") -> dict[str, Any]:
    return {
        "id": account_id,
        "status": "ACTIVE",
        "cash": cash,
        "non_marginable_buying_power": cash,
        "buying_power": cash,
        "trading_blocked": False,
        "account_blocked": False,
        "trade_suspended_by_user": False,
    }


def _pin(*, actual_suffix: str = ACCOUNT_SUFFIX) -> dict[str, Any]:
    return {
        "status": "PASS" if actual_suffix == ACCOUNT_SUFFIX else "BLOCKED",
        "expected_suffix": ACCOUNT_SUFFIX,
        "actual_suffix": actual_suffix,
        "account_pin_verified": actual_suffix == ACCOUNT_SUFFIX,
        "broker_read_occurred": True,
        "broker_mutation_occurred": False,
    }


def _snapshot(
    *,
    positions: list[dict[str, Any]],
    open_orders: list[dict[str, Any]] | None = None,
    account: dict[str, Any] | None = None,
    pin: dict[str, Any] | None = None,
    observed_at_ns: int = 1_000_000_000,
    fresh: bool = True,
) -> dict[str, Any]:
    return {
        "broker": "alpaca",
        "environment": "paper",
        "endpoint_family": "paper",
        "account": account or _account(),
        "positions": positions,
        "open_orders": list(open_orders or []),
        "account_pin_assertion": pin or _pin(),
        "observed_at_ns": observed_at_ns,
        "fresh": fresh,
        "broker_read_occurred": True,
        "read_methods_get_only": True,
        "response_contract_valid": True,
        "mutation_occurred": False,
    }


def _stack(tmp_path, *, context: dict[str, Any] | None = None):
    store = StateStore(db_path=str(tmp_path / "state.db"))
    manager = ExposureManager(
        initial_equity=Decimal("1000000"),
        require_broker_inventory_reconciliation=True,
    )
    coordinator = ReservationLifecycleCoordinator(
        exposure_manager=manager,
        state_store=store,
        baseline_context=context or _baseline_context(),
        now_ns_provider=lambda: 2_000_000_000_000_000_000,
    )
    return store, manager, coordinator


def _response(
    path: str,
    payload: Any,
    *,
    normalized_status: str = NormalizedBrokerStatus.UNKNOWN.value,
) -> BrokerGatewayResponse:
    return BrokerGatewayResponse(
        adapter_id="alpaca_paper",
        venue_id="alpaca",
        portal_id="alpaca_paper",
        environment="paper",
        request_method="GET",
        endpoint_path=path,
        ok=True,
        mutation_occurred=False,
        live_blocked=True,
        normalized_status=normalized_status,
        payload=payload,
    )


class _ReadOnlyAdapter:
    identity = BrokerAdapterIdentity(
        adapter_id="alpaca_paper",
        venue_id="alpaca",
        portal_id="alpaca_paper",
        environment="paper",
        base_url="https://paper-api.alpaca.markets",
        credential_status="configured",
        supported_methods=frozenset({"GET", "POST", "DELETE"}),
        supported_asset_classes=frozenset({"crypto"}),
        live_blocked=True,
    )

    def __init__(
        self,
        *,
        positions: list[dict[str, Any]],
        open_orders: list[dict[str, Any]] | None = None,
        account: dict[str, Any] | None = None,
        pin: dict[str, Any] | None = None,
        order_statuses: dict[str, BrokerGatewayResponse] | None = None,
    ) -> None:
        self.positions = list(positions)
        self.open_orders = list(open_orders or [])
        self.account = dict(account or _account())
        self.account_pin_assertion = dict(pin or _pin())
        self.order_statuses = dict(order_statuses or {})
        self.calls: list[tuple[str, str]] = []

    @property
    def request_counts(self) -> dict[str, int]:
        return {
            "GET": sum(1 for method, _path in self.calls if method == "GET"),
            "POST": 0,
            "DELETE": 0,
        }

    def get_account(self) -> BrokerGatewayResponse:
        self.calls.append(("GET", "/v2/account"))
        return _response("/v2/account", dict(self.account))

    def get_positions(self) -> BrokerGatewayResponse:
        self.calls.append(("GET", "/v2/positions"))
        return _response("/v2/positions", list(self.positions))

    def get_open_orders(self) -> BrokerGatewayResponse:
        self.calls.append(("GET", "/v2/orders"))
        return _response("/v2/orders", list(self.open_orders))

    def get_order_status(self, order_id: str) -> BrokerGatewayResponse:
        self.calls.append(("GET", f"/v2/orders/{order_id}"))
        return self.order_statuses[order_id]

    def submit_order(self, _order):
        raise AssertionError("Stage 2 tests must not submit an order")

    def cancel_order(self, _order_id):
        raise AssertionError("Stage 2 tests must not cancel an order")


def test_cold_start_reconciles_all_four_baseline_positions_without_mutation(tmp_path) -> None:
    store, manager, coordinator = _stack(tmp_path)
    adapter = _ReadOnlyAdapter(positions=_broker_positions())
    router = OrderRouter(
        primary_exchange="alpaca",
        paper_mode=True,
        state_store=store,
        execution_broker="alpaca_paper",
        broker_gateway_adapter=adapter,
        reservation_lifecycle_coordinator=coordinator,
        reservation_lifecycle_enabled=True,
        broker_inventory_reconciliation_required=True,
    )

    result = router.reconcile_startup_broker_inventory()

    assert result["status"] == "RECONCILED"
    assert result["authorized"] is True
    assert result["position_symbols"] == ("AVAXUSD", "ETHUSD", "LINKUSD", "SOLUSD")
    assert result["broker_mutation_occurred"] is False
    assert adapter.request_counts == {"GET": 3, "POST": 0, "DELETE": 0}
    durable = store.get_broker_inventory_reconciliation(result["snapshot_id"])
    assert durable is not None
    assert {lot["provenance"] for lot in durable["lots"]} == {"ADOPTED_BASELINE"}
    for symbol, qty, _avg, _mark in FOUR_POSITIONS:
        evidence = manager.broker_inventory_authority_evidence(symbol)
        assert evidence["authorized"] is True, evidence
        assert evidence["broker_qty"] == qty
        assert evidence["baseline_qty"] == qty
        assert evidence["bot_acquired_qty"] == "0"
        assert evidence["bot_owned_qty"] == "0"
        position = manager.position_for(SleeveType.POVERTY_KILLER_AGGREGATE, symbol)
        assert position is not None and position.qty == Decimal(qty)


@pytest.mark.parametrize(
    "quantity",
    (
        "0.000000000000000001",
        "0.123456789123456789",
        "1.000000000000000001",
        "999999.999999999999999999",
    ),
)
def test_generated_decimal_inventory_identities_remain_exact(tmp_path, quantity: str) -> None:
    context = _baseline_context((), baseline_id=f"decimal-{quantity}")
    store, manager, coordinator = _stack(tmp_path, context=context)
    event = _inventory_fill("decimal-fill", quantity)

    assert coordinator.record_broker_inventory_event(event)["status"] == "INSERTED"
    result = coordinator.reconcile_broker_inventory(
        _snapshot(
            positions=_broker_positions((("BTCUSD", quantity, "50000", "50100"),)),
            observed_at_ns=4_000_000_000,
        )
    )

    assert result["authorized"] is True, result
    evidence = manager.broker_inventory_authority_evidence("BTC/USD")
    assert Decimal(evidence["broker_qty"]) == Decimal(quantity)
    assert Decimal(evidence["bot_acquired_qty"]) == Decimal(quantity)
    assert Decimal(evidence["bot_owned_qty"]) == Decimal(quantity)
    assert Decimal(evidence["unknown_attribution_qty"]) == Decimal("0")
    durable = store.get_broker_inventory_reconciliation(result["snapshot_id"])
    assert durable is not None
    assert sum(
        Decimal(row["remaining_qty"])
        for row in durable["lots"]
        if row["provenance"] == "BOT_ACQUIRED"
    ) == Decimal(quantity)


@pytest.mark.parametrize(
    ("positions", "account", "pin", "fresh", "reason"),
    [
        (
            _broker_positions() + [{"symbol": "DOGEUSD", "qty": "100", "avg_entry_price": "0.10", "current_price": "0.11"}],
            _account(),
            _pin(),
            True,
            "UNKNOWN_INVENTORY_ATTRIBUTION:DOGEUSD",
        ),
        (_broker_positions(), _account(account_id="paper-account-bad999"), _pin(actual_suffix="bad999"), True, "BROKER_ACCOUNT_PIN_MISMATCH"),
        (_broker_positions(), _account(), _pin(), False, "BROKER_INVENTORY_FRESH_SNAPSHOT_REQUIRED"),
    ],
)
def test_unknown_account_mismatch_and_stale_books_fail_closed(
    tmp_path,
    positions,
    account,
    pin,
    fresh,
    reason,
) -> None:
    _store, manager, coordinator = _stack(tmp_path)

    result = coordinator.reconcile_broker_inventory(
        _snapshot(positions=positions, account=account, pin=pin, fresh=fresh)
    )

    assert result["status"] == "BLOCKED"
    assert result["authorized"] is False
    assert reason in result["reason_codes"]
    evidence = manager.broker_inventory_authority_evidence("AVAXUSD")
    assert evidence["authorized"] is False
    assert evidence["broker_inventory_reconciled"] is False


def _inventory_fill(
    event_id: str,
    quantity: str,
    *,
    event_type: str = "FILL",
    replaces_event_id: str | None = None,
    semantics: str = "DELTA",
) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "event_type": event_type,
        "replaces_event_id": replaces_event_id,
        "broker_order_id": "broker-buy-1",
        "client_order_id": "client-buy-1",
        "fill_id": event_id,
        "symbol": "BTCUSD",
        "side": "buy",
        "action": "buy_to_open",
        "quantity": quantity,
        "price": "50000.123456789123456789",
        "quantity_semantics": semantics,
        "sleeve": "shadow_front",
        "event_ts_ns": 2_000_000_000 + len(event_id),
        "observed_at_ns": 3_000_000_000 + len(event_id),
        "source": "broker_activity" if semantics == "DELTA" else "broker_order_status",
    }


def test_duplicate_late_corrected_and_busted_fill_lineage_is_exact_and_idempotent(tmp_path) -> None:
    baseline_rows = (("BTCUSD", "1", "49000", "50000"),)
    store, manager, coordinator = _stack(tmp_path, context=_baseline_context(baseline_rows))
    first = _inventory_fill("fill-1", "0.123456789123456789")
    second = _inventory_fill("fill-2", "0.300000000000000001")

    assert coordinator.record_broker_inventory_event(first)["status"] == "INSERTED"
    assert coordinator.record_broker_inventory_event(first)["status"] == "DUPLICATE"
    assert coordinator.record_broker_inventory_event(second)["status"] == "INSERTED"
    total = Decimal("1") + Decimal(first["quantity"]) + Decimal(second["quantity"])
    result = coordinator.reconcile_broker_inventory(
        _snapshot(
            positions=_broker_positions((("BTCUSD", str(total), "49200", "50100"),)),
            observed_at_ns=4_000_000_000,
        )
    )
    assert result["authorized"] is True
    evidence = manager.broker_inventory_authority_evidence("BTC/USD")
    assert evidence["bot_acquired_qty"] == str(Decimal(first["quantity"]) + Decimal(second["quantity"]))
    assert len(store.list_broker_inventory_events(baseline_snapshot_id=BASELINE_ID)) == 2

    correction = _inventory_fill(
        "correct-2",
        "0.250000000000000001",
        event_type="TRADE_CORRECT",
        replaces_event_id="fill-2",
    )
    assert coordinator.record_broker_inventory_event(correction)["status"] == "INSERTED"
    corrected_total = Decimal("1") + Decimal(first["quantity"]) + Decimal(correction["quantity"])
    corrected = coordinator.reconcile_broker_inventory(
        _snapshot(
            positions=_broker_positions((("BTCUSD", str(corrected_total), "49200", "50100"),)),
            observed_at_ns=5_000_000_000,
        )
    )
    assert corrected["authorized"] is True

    bust = {
        **_inventory_fill("bust-2", "0.1", event_type="TRADE_BUST", replaces_event_id="correct-2"),
        "quantity": None,
        "price": None,
        "quantity_semantics": "NONE",
        "source": "broker_trade_bust",
    }
    assert coordinator.record_broker_inventory_event(bust)["status"] == "INSERTED"
    busted_total = Decimal("1") + Decimal(first["quantity"])
    busted = coordinator.reconcile_broker_inventory(
        _snapshot(
            positions=_broker_positions((("BTCUSD", str(busted_total), "49200", "50100"),)),
            observed_at_ns=6_000_000_000,
        )
    )
    assert busted["authorized"] is True
    assert manager.broker_inventory_authority_evidence("BTCUSD")["bot_owned_qty"] == first["quantity"]


@pytest.mark.parametrize(
    "identity_override",
    (
        {"broker_order_id": "broker-wrong"},
        {"client_order_id": "client-wrong"},
        {"symbol": "ETHUSD"},
        {"side": "sell"},
    ),
)
def test_trade_correction_cannot_change_target_fill_identity(
    tmp_path,
    identity_override: dict[str, str],
) -> None:
    context = _baseline_context((), baseline_id="correction-identity")
    _store, manager, coordinator = _stack(tmp_path, context=context)
    original = _inventory_fill("identity-original", "0.1")
    correction = {
        **_inventory_fill(
            "identity-correction",
            "0.2",
            event_type="TRADE_CORRECT",
            replaces_event_id="identity-original",
        ),
        **identity_override,
    }
    assert coordinator.record_broker_inventory_event(original)["persisted"] is True
    assert coordinator.record_broker_inventory_event(correction)["persisted"] is True

    result = coordinator.reconcile_broker_inventory(
        _snapshot(
            positions=_broker_positions((("BTCUSD", "0.1", "50000", "50100"),)),
            observed_at_ns=4_000_000_000,
        )
    )

    assert result["authorized"] is False
    assert any(
        reason.startswith("INVENTORY_EVENT_REPLACEMENT_IDENTITY_CONFLICT:identity-correction:")
        for reason in result["reason_codes"]
    )
    assert manager.broker_inventory_authority_evidence("BTCUSD")["authorized"] is False


def test_event_insertion_permutations_produce_the_same_causal_lot_book(tmp_path) -> None:
    baseline_rows = (("BTCUSD", "1", "49000", "50000"),)
    context = _baseline_context(baseline_rows)
    buy_replaced = {
        **_inventory_fill("perm-buy-replaced", "0.2"),
        "client_order_id": "perm-buy-a",
        "broker_order_id": "broker-perm-buy-a",
        "event_ts_ns": 2_000_000_000,
    }
    buy_correction = {
        **_inventory_fill(
            "perm-buy-correction",
            "0.25",
            event_type="TRADE_CORRECT",
            replaces_event_id="perm-buy-replaced",
        ),
        "client_order_id": "perm-buy-a",
        "broker_order_id": "broker-perm-buy-a",
        "event_ts_ns": 3_000_000_000,
    }
    buy_second = {
        **_inventory_fill("perm-buy-b", "0.3"),
        "client_order_id": "perm-buy-b",
        "broker_order_id": "broker-perm-buy-b",
        "event_ts_ns": 4_000_000_000,
    }
    sell = {
        **_inventory_fill("perm-sell", "0.1"),
        "client_order_id": "perm-sell",
        "broker_order_id": "broker-perm-sell",
        "side": "sell",
        "action": "sell_to_close",
        "event_ts_ns": 5_000_000_000,
    }
    events = (buy_replaced, buy_correction, buy_second, sell)

    projections = []
    for name, ordering in (("forward", events), ("reverse", tuple(reversed(events)))):
        store, manager, coordinator = _stack(tmp_path / name, context=context)
        for event in ordering:
            assert coordinator.record_broker_inventory_event(event)["persisted"] is True
        result = coordinator.reconcile_broker_inventory(
            _snapshot(
                positions=_broker_positions((("BTCUSD", "1.45", "49200", "50100"),)),
                observed_at_ns=7_000_000_000,
            )
        )
        assert result["authorized"] is True, result
        durable = store.get_broker_inventory_reconciliation(result["snapshot_id"])
        assert durable is not None
        projections.append(
            {
                "positions": durable["positions"],
                "lots": durable["lots"],
                "evidence": manager.broker_inventory_authority_evidence("BTCUSD"),
            }
        )

    assert projections[0] == projections[1]


def test_restart_after_correction_reprojects_once_and_schema_reopen_is_idempotent(tmp_path) -> None:
    database = tmp_path / "state.db"
    context = _baseline_context((), baseline_id="restart-correction")
    store1 = StateStore(db_path=str(database))
    manager1 = ExposureManager(Decimal("1000000"), require_broker_inventory_reconciliation=True)
    coordinator1 = ReservationLifecycleCoordinator(
        exposure_manager=manager1,
        state_store=store1,
        baseline_context=context,
    )
    assert coordinator1.record_broker_inventory_event(_inventory_fill("restart-original", "0.4"))["persisted"] is True
    assert coordinator1.record_broker_inventory_event(
        _inventory_fill(
            "restart-correction",
            "0.35",
            event_type="TRADE_CORRECT",
            replaces_event_id="restart-original",
        )
    )["persisted"] is True

    store2 = StateStore(db_path=str(database))
    manager2 = ExposureManager(Decimal("1000000"), require_broker_inventory_reconciliation=True)
    coordinator2 = ReservationLifecycleCoordinator(
        exposure_manager=manager2,
        state_store=store2,
        baseline_context=context,
    )
    snapshot = _snapshot(
        positions=_broker_positions((("BTCUSD", "0.35", "50000", "50100"),)),
        observed_at_ns=6_000_000_000,
    )
    first = coordinator2.reconcile_broker_inventory(snapshot)
    second = coordinator2.reconcile_broker_inventory(snapshot)

    assert first["authorized"] is True, first
    assert second["authorized"] is True, second
    assert second["persist_status"] == "duplicate"
    assert store2.count_table_rows("broker_inventory_events") == 2
    assert store2.count_table_rows("broker_inventory_snapshots") == 1
    evidence = manager2.broker_inventory_authority_evidence("BTCUSD")
    assert evidence["bot_acquired_qty"] == "0.35"
    assert Decimal(evidence["unknown_attribution_qty"]) == Decimal("0")


def test_delta_and_cumulative_fill_disagreement_blocks_instead_of_double_counting(tmp_path) -> None:
    baseline_rows = (("BTCUSD", "1", "49000", "50000"),)
    _store, _manager, coordinator = _stack(tmp_path, context=_baseline_context(baseline_rows))
    coordinator.record_broker_inventory_event(_inventory_fill("delta-1", "0.2"))
    coordinator.record_broker_inventory_event(
        _inventory_fill("cumulative-1", "0.3", semantics="CUMULATIVE_ORDER")
    )

    result = coordinator.reconcile_broker_inventory(
        _snapshot(
            positions=_broker_positions((("BTCUSD", "1.2", "49000", "50000"),)),
            observed_at_ns=4_000_000_000,
        )
    )

    assert result["authorized"] is False
    assert "INVENTORY_FILL_DELTA_CUMULATIVE_MISMATCH:client-buy-1" in result["reason_codes"]


def test_activity_delta_and_status_cumulative_paths_converge_without_double_inventory(tmp_path) -> None:
    context = _baseline_context((), baseline_id="activity-status-parity")
    totals = []
    for name, events in (
        (
            "activity",
            (
                {**_inventory_fill("activity-a", "0.4"), "client_order_id": "parity-order"},
                {**_inventory_fill("activity-b", "0.6"), "client_order_id": "parity-order"},
            ),
        ),
        (
            "status",
            (
                {
                    **_inventory_fill("status-partial", "0.4", semantics="CUMULATIVE_ORDER"),
                    "client_order_id": "parity-order",
                    "event_ts_ns": 2_000_000_000,
                },
                {
                    **_inventory_fill("status-final", "1", semantics="CUMULATIVE_ORDER"),
                    "client_order_id": "parity-order",
                    "event_ts_ns": 3_000_000_000,
                },
            ),
        ),
    ):
        _store, manager, coordinator = _stack(tmp_path / name, context=context)
        for event in events:
            assert coordinator.record_broker_inventory_event(event)["persisted"] is True
        result = coordinator.reconcile_broker_inventory(
            _snapshot(
                positions=_broker_positions((("BTCUSD", "1", "50000", "50100"),)),
                observed_at_ns=5_000_000_000,
            )
        )
        assert result["authorized"] is True, result
        evidence = manager.broker_inventory_authority_evidence("BTCUSD")
        totals.append(
            (
                Decimal(evidence["broker_qty"]),
                Decimal(evidence["bot_acquired_qty"]),
                Decimal(evidence["bot_owned_qty"]),
                Decimal(evidence["unknown_attribution_qty"]),
            )
        )

    assert totals == [
        (Decimal("1"), Decimal("1.0"), Decimal("1.0"), Decimal("0")),
        (Decimal("1"), Decimal("1"), Decimal("1"), Decimal("0")),
    ]


@pytest.mark.parametrize("event_type", ("REJECTED", "EXPIRED", "CANCELED", "CANCELLED", "REPLACED"))
def test_non_fill_terminal_events_never_change_inventory(tmp_path, event_type: str) -> None:
    baseline_rows = (("BTCUSD", "1", "49000", "50000"),)
    store, manager, coordinator = _stack(tmp_path, context=_baseline_context(baseline_rows))
    persisted = coordinator.record_broker_inventory_event(
        {
            "event_id": f"terminal-{event_type.lower()}",
            "event_type": event_type,
            "broker_order_id": f"broker-{event_type.lower()}",
            "client_order_id": f"client-{event_type.lower()}",
            "symbol": "BTCUSD",
            "side": "buy",
            "action": "buy_to_open",
            "quantity": None,
            "price": None,
            "quantity_semantics": "NONE",
            "event_ts_ns": 2_000_000_000,
            "observed_at_ns": 3_000_000_000,
            "source": "offline_terminal_lifecycle",
        }
    )
    assert persisted["status"] == "INSERTED"

    result = coordinator.reconcile_broker_inventory(
        _snapshot(
            positions=_broker_positions(baseline_rows),
            observed_at_ns=4_000_000_000,
        )
    )

    assert result["authorized"] is True, result
    assert result["effective_fill_count"] == 0
    evidence = manager.broker_inventory_authority_evidence("BTCUSD")
    assert Decimal(evidence["broker_qty"]) == Decimal("1")
    assert Decimal(evidence["bot_acquired_qty"]) == Decimal("0")
    assert Decimal(evidence["unknown_attribution_qty"]) == Decimal("0")
    assert store.count_table_rows("broker_inventory_events") == 1


def test_late_cumulative_fill_uses_high_water_and_causal_regression_blocks(tmp_path) -> None:
    context = _baseline_context((("BTCUSD", "1", "49000", "50000"),))
    _store, manager, coordinator = _stack(tmp_path, context=context)
    partial = _inventory_fill("cumulative-partial", "0.4", semantics="CUMULATIVE_ORDER")
    partial["event_ts_ns"] = 2_000_000_000
    final = _inventory_fill("cumulative-final", "1", semantics="CUMULATIVE_ORDER")
    final["event_ts_ns"] = 4_000_000_000
    late = _inventory_fill("cumulative-late", "0.4", semantics="CUMULATIVE_ORDER")
    late["event_ts_ns"] = 3_000_000_000
    for event in (final, partial, late):
        assert coordinator.record_broker_inventory_event(event)["persisted"] is True
    reconciled = coordinator.reconcile_broker_inventory(
        _snapshot(
            positions=_broker_positions((("BTCUSD", "2", "50000", "50100"),)),
            observed_at_ns=5_000_000_000,
        )
    )
    assert reconciled["authorized"] is True
    assert manager.broker_inventory_authority_evidence("BTCUSD")["bot_owned_qty"] == "1"

    regressed = _inventory_fill("cumulative-regressed", "0.8", semantics="CUMULATIVE_ORDER")
    regressed["event_ts_ns"] = 6_000_000_000
    assert coordinator.record_broker_inventory_event(regressed)["persisted"] is True
    blocked = coordinator.reconcile_broker_inventory(
        _snapshot(
            positions=_broker_positions((("BTCUSD", "2", "50000", "50100"),)),
            observed_at_ns=7_000_000_000,
        )
    )
    assert blocked["authorized"] is False
    assert "INVENTORY_FILL_CUMULATIVE_REGRESSION:client-buy-1" in blocked["reason_codes"]


def _open_reservation(
    coordinator: ReservationLifecycleCoordinator,
    *,
    client_order_id: str,
    side: str,
    qty: str,
    price: str,
) -> dict[str, Any]:
    return coordinator.on_order_acknowledged(
        client_order_id=client_order_id,
        reservation_id=client_order_id,
        decision_uuid=f"decision-{client_order_id}",
        reservation_dedupe_key=f"decision-{client_order_id}:{client_order_id}",
        symbol="BTCUSD",
        side=side,
        sleeve="shadow_front",
        qty=qty,
        price_basis=price,
        order_type="limit",
        source_idempotency_key=f"ack:{client_order_id}",
        price_basis_source_proven=True,
    )


def _mapping(store: StateStore, client_order_id: str, *, side: str = "buy") -> None:
    assert store.upsert_order_id_mapping(
        {
            "client_order_id": client_order_id,
            "broker": "alpaca",
            "symbol": "BTCUSD",
            "side": side,
            "order_type": "limit",
            "venue_order_id": f"broker-{client_order_id}",
            "broker_order_id": f"broker-{client_order_id}",
            "command_id_namespace": "venue_order_id",
            "command_order_id": f"broker-{client_order_id}",
            "id_mapping_source": "test_broker_ack",
            "submit_ts_ns": 1_000_000_000,
            "ack_ts_ns": 1_100_000_000,
            "status": "open",
            "is_terminal": False,
        }
    )


def test_concurrent_reservations_cannot_exceed_cash_or_owned_quantity(tmp_path) -> None:
    baseline_rows = (("BTCUSD", "1", "49000", "50000"),)
    store, manager, coordinator = _stack(tmp_path, context=_baseline_context(baseline_rows))
    initial = coordinator.reconcile_broker_inventory(
        _snapshot(
            positions=_broker_positions(baseline_rows),
            account=_account(cash="100"),
            observed_at_ns=4_000_000_000,
        )
    )
    assert initial["authorized"] is True

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda client_id: _open_reservation(
                    coordinator,
                    client_order_id=client_id,
                    side="buy",
                    qty="0.6",
                    price="100",
                ),
                ("buy-a", "buy-b"),
            )
        )
    assert sum(item["applied"] is True for item in results) == 1
    assert sum(item["applied"] is False for item in results) == 1
    accepted_client = next(
        client_id
        for client_id, result in zip(("buy-a", "buy-b"), results)
        if result["applied"] is True
    )
    rejected_result = next(result for result in results if result["applied"] is False)
    assert "BUY reservations exceed broker cash" in str(rejected_result["failed_reason"])
    for client_id in (accepted_client,):
        _mapping(store, client_id)
    open_orders = [
        {
            "id": f"broker-{client_id}",
            "client_order_id": client_id,
            "symbol": "BTCUSD",
            "side": "buy",
            "qty": "0.6",
            "filled_qty": "0",
            "limit_price": "100",
        }
        for client_id in (accepted_client,)
    ]
    within_cash = coordinator.reconcile_broker_inventory(
        _snapshot(
            positions=_broker_positions(baseline_rows),
            open_orders=open_orders,
            account=_account(cash="100"),
            observed_at_ns=5_000_000_000,
        )
    )
    assert within_cash["authorized"] is True
    assert manager.broker_inventory_authority_evidence("BTCUSD")["pending_buy_qty"] == "0.6"

    sell = _open_reservation(
        coordinator,
        client_order_id="sell-too-large",
        side="sell",
        qty="1.1",
        price="50000",
    )
    assert sell["applied"] is False
    assert sell["failed_reason"] is not None
    assert manager.reservations_for(symbol="BTCUSD")


def test_pending_sell_reservations_are_broker_matched_and_cannot_cross_owned_bot_lot(tmp_path) -> None:
    baseline_rows = (("BTCUSD", "1", "49000", "50000"),)
    store, manager, coordinator = _stack(tmp_path, context=_baseline_context(baseline_rows))
    coordinator.record_broker_inventory_event(_inventory_fill("owned-fill", "0.4"))
    initial = coordinator.reconcile_broker_inventory(
        _snapshot(
            positions=_broker_positions((("BTCUSD", "1.4", "49200", "50000"),)),
            observed_at_ns=4_000_000_000,
        )
    )
    assert initial["authorized"] is True
    opened = _open_reservation(
        coordinator,
        client_order_id="sell-owned",
        side="sell",
        qty="0.3",
        price="50000",
    )
    assert opened["applied"] is True
    _mapping(store, "sell-owned", side="sell")
    broker_order = {
        "id": "broker-sell-owned",
        "client_order_id": "sell-owned",
        "symbol": "BTCUSD",
        "side": "sell",
        "qty": "0.3",
        "filled_qty": "0",
        "limit_price": "50000",
    }
    reconciled = coordinator.reconcile_broker_inventory(
        _snapshot(
            positions=_broker_positions((("BTCUSD", "1.4", "49200", "50000"),)),
            open_orders=[broker_order],
            observed_at_ns=5_000_000_000,
        )
    )
    assert reconciled["authorized"] is True
    evidence = manager.broker_inventory_authority_evidence("BTCUSD")
    assert evidence["pending_sell_qty"] == "0.3"
    assert evidence["available_qty"] == "1.1"

    crossing = _open_reservation(
        coordinator,
        client_order_id="sell-crossing",
        side="sell",
        qty="0.2",
        price="50000",
    )
    assert crossing["applied"] is False
    assert "REDUCE_ONLY_VIOLATION" in crossing["failed_reason"]

    broker_order["filled_qty"] = "0.1"
    quantity_conflict = coordinator.reconcile_broker_inventory(
        _snapshot(
            positions=_broker_positions((("BTCUSD", "1.4", "49200", "50000"),)),
            open_orders=[broker_order],
            observed_at_ns=6_000_000_000,
        )
    )
    assert quantity_conflict["authorized"] is False
    assert "RESERVATION_BROKER_REMAINING_QUANTITY_CONFLICT:sell-owned" in quantity_conflict["reason_codes"]


@pytest.mark.parametrize(
    ("broker_override", "expected_reason"),
    (
        ({"limit_price": None}, "RESERVATION_BROKER_PRICE_TRUTH_MISSING:strict-open-order"),
        ({"qty": None}, "RESERVATION_BROKER_QUANTITY_TRUTH_MISSING_OR_INVALID:strict-open-order"),
        ({"filled_qty": None}, "RESERVATION_BROKER_QUANTITY_TRUTH_MISSING_OR_INVALID:strict-open-order"),
        ({"remaining_qty": "0.5"}, "RESERVATION_BROKER_REMAINING_QUANTITY_CONFLICT:strict-open-order"),
    ),
)
def test_open_order_reservation_requires_complete_matching_broker_quantity_and_price_truth(
    tmp_path,
    broker_override: dict[str, Any],
    expected_reason: str,
) -> None:
    baseline_rows = (("BTCUSD", "1", "49000", "50000"),)
    store, manager, coordinator = _stack(tmp_path, context=_baseline_context(baseline_rows))
    assert coordinator.reconcile_broker_inventory(
        _snapshot(
            positions=_broker_positions(baseline_rows),
            account=_account(cash="1000"),
            observed_at_ns=4_000_000_000,
        )
    )["authorized"] is True
    assert _open_reservation(
        coordinator,
        client_order_id="strict-open-order",
        side="buy",
        qty="0.6",
        price="100",
    )["applied"] is True
    _mapping(store, "strict-open-order")
    broker_order = {
        "id": "broker-strict-open-order",
        "client_order_id": "strict-open-order",
        "symbol": "BTCUSD",
        "side": "buy",
        "qty": "0.6",
        "filled_qty": "0",
        "remaining_qty": "0.6",
        "limit_price": "100",
        **broker_override,
    }

    result = coordinator.reconcile_broker_inventory(
        _snapshot(
            positions=_broker_positions(baseline_rows),
            open_orders=[broker_order],
            account=_account(cash="1000"),
            observed_at_ns=5_000_000_000,
        )
    )

    assert result["authorized"] is False
    assert expected_reason in result["reason_codes"]
    assert manager.broker_inventory_authority_evidence("BTCUSD")["authorized"] is False


def test_restart_between_ack_partial_and_final_fill_recovers_once(tmp_path) -> None:
    clean_context = _baseline_context((), baseline_id="paper-baseline-clean")
    store, _manager1, coordinator1 = _stack(tmp_path, context=clean_context)
    opening = coordinator1.reconcile_broker_inventory(
        _snapshot(positions=[], observed_at_ns=1_000_000_000)
    )
    assert opening["authorized"] is True
    opened = _open_reservation(
        coordinator1,
        client_order_id="restart-order",
        side="buy",
        qty="1.0",
        price="50000",
    )
    assert opened["applied"] is True
    _mapping(store, "restart-order")

    manager2 = ExposureManager(Decimal("1000000"), require_broker_inventory_reconciliation=True)
    hydrated2 = manager2.hydrate_reservations_from_ledger(
        store.list_reservation_ledger(active_only=True, include_terminal=False),
        release_tombstones=[],
        fill_progress=store.list_reservation_fill_progress("restart-order"),
    )
    assert hydrated2["valid"] is True
    coordinator2 = ReservationLifecycleCoordinator(
        exposure_manager=manager2,
        state_store=store,
        baseline_context=clean_context,
    )
    partial = coordinator2.on_partial_fill(
        client_order_id="restart-order",
        reservation_id="restart-order",
        reservation_dedupe_key="decision-restart-order:restart-order",
        cumulative_filled_qty="0.4",
        fill_delta_qty="0.4",
        fill_idempotency_key="restart-fill-1",
        status_source="broker_activity",
        source_event_id="restart-fill-1",
    )
    assert partial["applied"] is True
    coordinator2.record_broker_inventory_event(
        {
            **_inventory_fill("restart-fill-1", "0.4"),
            "client_order_id": "restart-order",
            "broker_order_id": "broker-restart-order",
            "baseline_snapshot_id": "paper-baseline-clean",
        }
    )

    manager3 = ExposureManager(Decimal("1000000"), require_broker_inventory_reconciliation=True)
    hydrated3 = manager3.hydrate_reservations_from_ledger(
        store.list_reservation_ledger(active_only=True, include_terminal=False),
        release_tombstones=[],
        fill_progress=store.list_reservation_fill_progress("restart-order"),
    )
    assert hydrated3["valid"] is True
    coordinator3 = ReservationLifecycleCoordinator(
        exposure_manager=manager3,
        state_store=store,
        baseline_context=clean_context,
    )
    final = coordinator3.on_full_fill(
        client_order_id="restart-order",
        reservation_id="restart-order",
        reservation_dedupe_key="decision-restart-order:restart-order",
        cumulative_filled_qty="1.0",
        fill_delta_qty="0.6",
        fill_idempotency_key="restart-fill-2",
        release_idempotency_key="restart-release",
        status_source="broker_activity",
        source_event_id="restart-fill-2",
        terminal_source="broker_order_status",
    )
    assert final["applied"] is True
    coordinator3.record_broker_inventory_event(
        {
            **_inventory_fill("restart-fill-2", "0.6"),
            "client_order_id": "restart-order",
            "broker_order_id": "broker-restart-order",
            "baseline_snapshot_id": "paper-baseline-clean",
        }
    )
    assert store.mark_order_id_mapping_terminal(
        "restart-order",
        "alpaca",
        status="filled",
        terminal_reason="test_broker_terminal_truth",
    ) is True
    reconciled = coordinator3.reconcile_broker_inventory(
        _snapshot(
            positions=_broker_positions((("BTCUSD", "1.0", "50000", "50100"),)),
            observed_at_ns=7_000_000_000,
        )
    )
    assert reconciled["authorized"] is True
    assert manager3.broker_inventory_authority_evidence("BTCUSD")["bot_acquired_qty"] == "1.0"
    assert store.list_reservation_ledger(active_only=True, include_terminal=False) == []
    repeated = coordinator3.on_full_fill(
        client_order_id="restart-order",
        release_idempotency_key="restart-release",
        cumulative_filled_qty="1.0",
    )
    assert repeated["idempotent"] is True


def _preflight(qty: str) -> dict[str, Any]:
    return {
        "endpoint_family": "paper",
        "account": {
            "id": ACCOUNT_ID,
            "status": "ACTIVE",
            "equity": "1000000",
            "buying_power": "900000",
            "trading_blocked": False,
            "account_blocked": False,
        },
        "open_order_count": 0,
        "open_orders": [],
        "position_count": 1,
        "positions": [
            {
                "symbol": "BTCUSD",
                "asset_class": "crypto",
                "qty": qty,
                "side": "long",
                "avg_entry_price": "50000",
                "current_price": "50100",
            }
        ],
    }


def test_managed_reconciliation_advances_current_truth_without_rewriting_opening_baseline() -> None:
    accepted = accept_existing_position_baseline(_preflight("0.5"), accepted_by="Shan/local operator")
    opening_id = accepted["baseline_snapshot_id"]
    managed = {
        "status": "RECONCILED",
        "authorized": True,
        "exposure_ingest": {"applied": True},
        "snapshot_id": "broker-inventory-managed-1",
        "baseline_snapshot_id": opening_id,
        "account_suffix": ACCOUNT_SUFFIX,
        "metadata": {"opening_baseline_preserved": True},
        "positions": [
            {
                "symbol": "BTCUSD",
                "broker_qty": "0.7",
                "avg_entry_price": "50000",
                "metadata": {"attribution_status": "KNOWN", "unknown_attribution_qty": "0"},
            }
        ],
    }

    state = build_baseline_adoption_state(
        current_snapshot=_preflight("0.7"),
        accepted_baseline=accepted,
        managed_reconciliation=managed,
    )

    assert state["status"] == PREFLIGHT_READY_WITH_ACCEPTED_EXISTING_POSITIONS
    assert state["start_ready"] is True
    assert state["baseline_snapshot_id"] == opening_id
    assert state["managed_reconciliation_snapshot_id"] == "broker-inventory-managed-1"
    assert accepted["baseline_snapshot"]["positions"][0]["qty"] == "0.5"

    durable_projection_only = dict(managed)
    durable_projection_only.pop("authorized")
    durable_projection_only.pop("exposure_ingest")
    blocked_projection = build_baseline_adoption_state(
        current_snapshot=_preflight("0.7"),
        accepted_baseline=accepted,
        managed_reconciliation=durable_projection_only,
    )
    assert blocked_projection["status"] == PAPER_BASELINE_DRIFT_REQUIRES_REFRESH
    assert blocked_projection["start_ready"] is False
    assert (
        blocked_projection["managed_reconciliation_status"]
        == "MANAGED_RECONCILIATION_RUNTIME_APPLICATION_REQUIRED"
    )

    durable_verified = build_baseline_adoption_state(
        current_snapshot=_preflight("0.7"),
        accepted_baseline=accepted,
        managed_reconciliation=durable_projection_only,
        managed_reconciliation_durable_verified=True,
    )
    assert durable_verified["status"] == PREFLIGHT_READY_WITH_ACCEPTED_EXISTING_POSITIONS
    assert durable_verified["start_ready"] is True
    assert durable_verified["managed_reconciliation_durable_verified"] is True
    assert durable_verified["runtime_reingest_required"] is True

    cost_basis_conflict = dict(durable_projection_only)
    cost_basis_conflict["positions"] = [
        {
            **durable_projection_only["positions"][0],
            "avg_entry_price": "50001",
        }
    ]
    blocked_cost_basis = build_baseline_adoption_state(
        current_snapshot=_preflight("0.7"),
        accepted_baseline=accepted,
        managed_reconciliation=cost_basis_conflict,
        managed_reconciliation_durable_verified=True,
    )
    assert blocked_cost_basis["start_ready"] is False
    assert (
        blocked_cost_basis["managed_reconciliation_status"]
        == "MANAGED_RECONCILIATION_CURRENT_COST_BASIS_MISMATCH"
    )

    managed["positions"][0]["metadata"]["attribution_status"] = "UNKNOWN_ATTRIBUTION"
    blocked = build_baseline_adoption_state(
        current_snapshot=_preflight("0.7"),
        accepted_baseline=accepted,
        managed_reconciliation=managed,
    )
    assert blocked["status"] == PAPER_BASELINE_DRIFT_REQUIRES_REFRESH
    assert blocked["start_ready"] is False


def test_candidate_metadata_cannot_supply_inventory_authority(tmp_path) -> None:
    _store, manager, _coordinator = _stack(tmp_path)
    config = SimpleNamespace(
        broker_mode="paper",
        portfolio_risk_gate_paper_enabled=True,
        portfolio_risk_gate_policy_version="P3B_B1_V1",
        portfolio_risk_max_utilization=None,
        portfolio_risk_max_asset_concentration=None,
        portfolio_risk_cash_reserve_pct=None,
        portfolio_risk_correlation_threshold=None,
        portfolio_risk_correlation_slash_factor=None,
    )
    signal = SimpleNamespace(
        side="buy",
        quantity=Decimal("0.1"),
        strategy="shadow_front",
        metadata={
            "existing_positions": [{"symbol": "BTCUSD", "qty": "999"}],
            "open_orders": [{"symbol": "BTCUSD", "qty": "999"}],
            "reservations": [{"symbol": "BTCUSD", "qty": "999"}],
            "run_acquired_qty": "999",
            "paper_baseline_lot_tracking_available": True,
            "broker_position_backed": True,
            "broker_inventory_evidence": {"authorized": True, "broker_qty": "999"},
        },
    )
    runtime = SimpleNamespace(last_price=Decimal("50000"))

    evidence = _apply_portfolio_risk_gate_to_signal(
        config=config,
        symbol="BTCUSD",
        signal=signal,
        runtime=runtime,
        exposure_manager=manager,
    )

    assert evidence["authorized"] is False
    assert evidence["reason_code"] == "BROKER_INVENTORY_RECONCILIATION_REQUIRED"
    for field in (
        "existing_positions",
        "open_orders",
        "reservations",
        "run_acquired_qty",
        "paper_baseline_lot_tracking_available",
        "broker_position_backed",
        "broker_inventory_evidence",
    ):
        assert field not in signal.metadata


def test_external_paper_inventory_requirement_cannot_be_disabled_by_legacy_risk_flag(
    tmp_path,
) -> None:
    _store, manager, coordinator = _stack(tmp_path)
    config = SimpleNamespace(
        broker_mode="paper",
        portfolio_risk_gate_paper_enabled=False,
        portfolio_risk_gate_policy_version="P3B_B1_V1",
        portfolio_risk_max_utilization=None,
        portfolio_risk_max_asset_concentration=None,
        portfolio_risk_cash_reserve_pct=None,
        portfolio_risk_correlation_threshold=None,
        portfolio_risk_correlation_slash_factor=None,
    )

    def _signal() -> SimpleNamespace:
        return SimpleNamespace(
            side="buy",
            quantity=Decimal("0.1"),
            strategy="shadow_front",
            metadata={
                "correlation_truth_status": "FRESH",
                "correlation_pairs": {
                    ("AVAXUSD", "ETHUSD"): Decimal("0.10"),
                    ("AVAXUSD", "LINKUSD"): Decimal("0.12"),
                    ("AVAXUSD", "SOLUSD"): Decimal("0.14"),
                },
            },
        )

    runtime = SimpleNamespace(last_price=Decimal("21"))
    blocked_signal = _signal()
    blocked = _apply_portfolio_risk_gate_to_signal(
        config=config,
        symbol="AVAXUSD",
        signal=blocked_signal,
        runtime=runtime,
        exposure_manager=manager,
    )

    assert blocked_signal.metadata["portfolio_risk_gate_required"] is True
    assert blocked["authorized"] is False
    assert blocked["reason_code"] == "BROKER_INVENTORY_RECONCILIATION_REQUIRED"

    reconciled = coordinator.reconcile_broker_inventory(
        _snapshot(positions=_broker_positions(), observed_at_ns=2_000_000_000)
    )
    assert reconciled["authorized"] is True
    admitted_signal = _signal()
    admitted = _apply_portfolio_risk_gate_to_signal(
        config=config,
        symbol="AVAXUSD",
        signal=admitted_signal,
        runtime=runtime,
        exposure_manager=manager,
    )

    assert admitted_signal.metadata["portfolio_risk_gate_required"] is True
    assert admitted["authorized"] is True
    assert admitted["route_permitted"] is True


def test_correlation_pair_aliases_preserve_slash_symbols_and_conflicts_fail_closed() -> None:
    manager = ExposureManager(
        initial_equity=Decimal("10000"),
        max_utilization=Decimal("0.50"),
        max_asset_concentration=Decimal("0.15"),
    )
    manager.force_inventory_sync("BTC/USD", Decimal("1"), Decimal("1000"))
    common = {
        "policy_version": "P3B_B1_V1",
        "sleeve": SleeveType.SHADOW_FRONT,
        "symbol": "ETH/USD",
        "side": "buy",
        "qty": Decimal("0.25"),
        "price": Decimal("100"),
        "correlation_truth_status": "FRESH",
        "correlation_threshold": Decimal("0.80"),
        "correlation_slash_factor": Decimal("0.50"),
    }

    admitted = manager.evaluate_pre_trade_portfolio_gate(
        **common,
        correlation_pairs={("ETH/USD", "BTC/USD"): Decimal("0.90")},
    )

    assert admitted["authorized"] is True
    assert admitted["reason_code"] == "CORRELATION_SLASH_APPLIED"
    assert admitted["adjusted_quantity"] == "0.1250"

    blocked = manager.evaluate_pre_trade_portfolio_gate(
        **common,
        correlation_pairs={
            ("ETH/USD", "BTC/USD"): Decimal("0.90"),
            "ETHUSD|BTCUSD": Decimal("0.10"),
        },
    )

    assert blocked["authorized"] is False
    assert blocked["reason_code"] == "CORRELATION_TRUTH_CONFLICT"
    assert blocked["route_permitted"] is False


def test_same_symbol_buy_is_not_blocked_by_opening_baseline_after_complete_reconciliation(tmp_path) -> None:
    context = _baseline_context()
    _store, manager, coordinator = _stack(tmp_path, context=context)
    reconciled = coordinator.reconcile_broker_inventory(
        _snapshot(positions=_broker_positions(), observed_at_ns=2_000_000_000)
    )
    assert reconciled["authorized"] is True
    signal = SimpleNamespace(
        side="buy",
        quantity=Decimal("1"),
        strategy="shadow_front",
        metadata={
            "quote_fresh": True,
            "correlation_truth_status": "FRESH",
            "correlation_pairs": {
                ("AVAXUSD", "ETHUSD"): Decimal("0.10"),
                ("AVAXUSD", "LINKUSD"): Decimal("0.12"),
                ("AVAXUSD", "SOLUSD"): Decimal("0.14"),
            },
        },
    )
    decision_ns = 1_777_948_800_000_000_000
    runtime = SimpleNamespace(
        last_price=Decimal("21"),
        last_stale_data_assessment=StaleDataGuard("AVAX/USD").assess(
            TemporalInput(decision_ns, decision_ns, decision_ns)
        ),
    )
    config = SimpleNamespace(
        broker_mode="paper",
        preferred_trading_portal="alpaca_paper",
        allow_portal_fallback=False,
        paper_baseline_runtime_context=context,
        portfolio_risk_gate_paper_enabled=True,
        portfolio_risk_gate_policy_version="P3B_B1_V1",
        portfolio_risk_max_utilization=None,
        portfolio_risk_max_asset_concentration=None,
        portfolio_risk_cash_reserve_pct=None,
        portfolio_risk_correlation_threshold=None,
        portfolio_risk_correlation_slash_factor=None,
    )

    verdict = _build_pre_trade_guardrail_verdict(
        config=config,
        symbol="AVAX/USD",
        signal=signal,
        runtime=runtime,
        is_attack=False,
        exposure_manager=manager,
    )

    assert "PAPER_BASELINE_SYMBOL_PROTECTED" not in verdict["reason_codes"]
    assert verdict["verdict"] == "ALLOW", verdict["reason_codes"]
    assert verdict["route_permitted"] is True
    assert signal.metadata["broker_inventory_snapshot_id"] == reconciled["snapshot_id"]
    assert "paper_baseline_lot_tracking_available" not in signal.metadata
    assert "run_acquired_qty" not in signal.metadata


def test_startup_reconciliation_invokes_no_order_cancel_or_close_surface(tmp_path, monkeypatch) -> None:
    store, _manager, coordinator = _stack(tmp_path)
    adapter = _ReadOnlyAdapter(positions=_broker_positions())
    router = OrderRouter(
        primary_exchange="alpaca",
        paper_mode=True,
        state_store=store,
        execution_broker="alpaca_paper",
        broker_gateway_adapter=adapter,
        reservation_lifecycle_coordinator=coordinator,
        reservation_lifecycle_enabled=True,
        broker_inventory_reconciliation_required=True,
    )
    mutation_calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def _unexpected_mutation(name: str):
        def _record(*args, **kwargs):
            mutation_calls.append((name, args, kwargs))
            raise AssertionError(f"unexpected mutation surface: {name}")

        return _record

    monkeypatch.setattr(router, "submit_order", _unexpected_mutation("submit_order"))
    monkeypatch.setattr(router, "cancel_order", _unexpected_mutation("cancel_order"))
    monkeypatch.setattr(router, "close_all_positions", _unexpected_mutation("close_all_positions"))

    result = router.reconcile_startup_broker_inventory()

    assert result["authorized"] is True
    assert mutation_calls == []
    assert adapter.request_counts == {"GET": 3, "POST": 0, "DELETE": 0}


def test_original_order_quantity_is_never_hydrated_as_filled_quantity(tmp_path) -> None:
    store = StateStore(db_path=str(tmp_path / "state.db"))
    assert store.upsert_order_id_mapping(
        {
            "client_order_id": "open-order",
            "broker": "alpaca",
            "symbol": "BTCUSD",
            "side": "buy",
            "order_type": "limit",
            "venue_order_id": "broker-open-order",
            "broker_order_id": "broker-open-order",
            "command_id_namespace": "venue_order_id",
            "command_order_id": "broker-open-order",
            "id_mapping_source": "test",
            "submit_ts_ns": 1_000_000_000,
            "ack_ts_ns": 1_100_000_000,
            "status": "open",
            "is_terminal": False,
        }
    )
    status = _response(
        "/v2/orders/broker-open-order",
        {
            "id": "broker-open-order",
            "client_order_id": "open-order",
            "symbol": "BTCUSD",
            "side": "buy",
            "status": "accepted",
            "qty": "0.75",
            "limit_price": "50000",
            "updated_at": "2026-07-18T12:00:00Z",
        },
        normalized_status=NormalizedBrokerStatus.ACCEPTED.value,
    )
    adapter = _ReadOnlyAdapter(
        positions=_broker_positions((("BTCUSD", "1", "49000", "50000"),)),
        open_orders=[{"client_order_id": "open-order", "symbol": "BTCUSD", "side": "buy", "qty": "0.75"}],
        order_statuses={"broker-open-order": status},
    )

    OrderRouter(
        primary_exchange="alpaca",
        paper_mode=True,
        state_store=store,
        execution_broker="alpaca_paper",
        broker_gateway_adapter=adapter,
    )

    assert store.count_table_rows("broker_fill_ledger") == 0
    assert adapter.request_counts["POST"] == 0
    assert adapter.request_counts["DELETE"] == 0


def test_get_only_post_ack_partial_and_final_states_advance_reservation_and_inventory_once(tmp_path) -> None:
    clean_context = _baseline_context((), baseline_id="paper-baseline-get-only")
    store, manager, coordinator = _stack(tmp_path, context=clean_context)
    adapter = _ReadOnlyAdapter(positions=[])
    router = OrderRouter(
        primary_exchange="alpaca",
        paper_mode=True,
        state_store=store,
        execution_broker="alpaca_paper",
        broker_gateway_adapter=adapter,
        reservation_lifecycle_coordinator=coordinator,
        reservation_lifecycle_enabled=True,
        broker_inventory_reconciliation_required=True,
    )
    assert router.reconcile_startup_broker_inventory()["authorized"] is True
    order = OrderRequest(
        id="get-only-order",
        symbol="BTCUSD",
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        order_type=OrderType.LIMIT,
        limit_price=Decimal("50000"),
        strategy=SleeveType.SHADOW_FRONT,
        confidence=0.8,
        decision_uuid="decision-get-only-order",
        exchange_ts_ns=1_000_000_000,
        receive_ts_ns=1_000_000_100,
        metadata={"action": "buy_to_open"},
    )
    assert _open_reservation(
        coordinator,
        client_order_id=order.id,
        side="buy",
        qty="1",
        price="50000",
    )["applied"] is True
    assert router._register_active_order_id_mapping(
        order,
        broker="alpaca",
        venue_order_id="broker-get-only-order",
        broker_order_id="broker-get-only-order",
        exchange_txid=None,
        id_mapping_source="offline_broker_ack_evidence",
        ack_ts_ns=1_100_000_000,
    ) is True
    ack = BrokerGatewayResponse(
        adapter_id="alpaca_paper",
        venue_id="alpaca",
        portal_id="alpaca_paper",
        environment="paper",
        request_method="POST",
        endpoint_path="/v2/orders",
        ok=True,
        mutation_occurred=False,
        live_blocked=True,
        broker_order_id="broker-get-only-order",
        client_order_id=order.id,
        normalized_status=NormalizedBrokerStatus.ACCEPTED.value,
    )

    adapter.positions = _broker_positions((("BTCUSD", "0.4", "50000", "50100"),))
    adapter.open_orders = [
        {
            "id": "broker-get-only-order",
            "client_order_id": order.id,
            "symbol": "BTCUSD",
            "side": "buy",
            "qty": "1",
            "filled_qty": "0.4",
            "limit_price": "50000",
        }
    ]
    adapter.order_statuses["broker-get-only-order"] = _response(
        "/v2/orders/broker-get-only-order",
        {
            "id": "broker-get-only-order",
            "client_order_id": order.id,
            "symbol": "BTCUSD",
            "side": "buy",
            "status": "partially_filled",
            "filled_qty": "0.4",
            "filled_avg_price": "50000",
            "filled_at": "2026-07-18T12:00:00Z",
        },
        normalized_status=NormalizedBrokerStatus.PARTIALLY_FILLED.value,
    )
    partial = router._post_ack_gateway_reconciliation(order, ack)
    assert partial["status"] == "PARTIALLY_FILLED"
    assert partial["broker_inventory_reconciliation"]["authorized"] is True
    active = store.list_reservation_ledger(active_only=True, include_terminal=False)
    assert len(active) == 1 and active[0]["open_qty"] == "0.6"
    assert manager.broker_inventory_authority_evidence("BTCUSD")["bot_owned_qty"] == "0.4"

    adapter.positions = _broker_positions((("BTCUSD", "1", "50000", "50200"),))
    adapter.open_orders = []
    adapter.order_statuses["broker-get-only-order"] = _response(
        "/v2/orders/broker-get-only-order",
        {
            "id": "broker-get-only-order",
            "client_order_id": order.id,
            "symbol": "BTCUSD",
            "side": "buy",
            "status": "filled",
            "filled_qty": "1",
            "filled_avg_price": "50000",
            "filled_at": "2026-07-18T12:01:00Z",
        },
        normalized_status=NormalizedBrokerStatus.FILLED.value,
    )
    filled = router._post_ack_gateway_reconciliation(order, ack)
    assert filled["status"] == "FILLED"
    assert filled["broker_inventory_reconciliation"]["authorized"] is True
    assert store.list_reservation_ledger(active_only=True, include_terminal=False) == []
    evidence = manager.broker_inventory_authority_evidence("BTCUSD")
    assert evidence["bot_acquired_qty"] == "1"
    assert evidence["bot_owned_qty"] == "1"
    ledger_rows = store.list_broker_fill_ledger()
    assert len(ledger_rows) == 2
    assert sum((Decimal(row["quantity"]) for row in ledger_rows), start=Decimal("0")) == Decimal("1")
    assert adapter.request_counts["POST"] == 0
    assert adapter.request_counts["DELETE"] == 0


def test_required_external_inventory_cannot_start_without_existing_coordinator() -> None:
    adapter = _ReadOnlyAdapter(positions=[])
    with pytest.raises(ValueError, match="external_paper_broker_inventory_coordinator_required"):
        OrderRouter(
            primary_exchange="alpaca",
            paper_mode=True,
            execution_broker="alpaca_paper",
            broker_gateway_adapter=adapter,
            broker_inventory_reconciliation_required=True,
        )
    assert adapter.calls == []


def test_authoritative_state_read_failure_blocks_inventory_reconciliation(
    tmp_path,
    monkeypatch,
) -> None:
    store, manager, coordinator = _stack(tmp_path)

    def _failed_event_read(**_kwargs):
        raise RuntimeError("broker_inventory_event_read_failed")

    monkeypatch.setattr(store, "list_broker_inventory_events", _failed_event_read)
    result = coordinator.reconcile_broker_inventory(
        _snapshot(positions=_broker_positions(), observed_at_ns=2_000_000_000)
    )

    assert result["authorized"] is False
    assert "BROKER_INVENTORY_STATE_READ_FAILED" in result["reason_codes"]
    assert manager.broker_inventory_authority_evidence("AVAXUSD")["authorized"] is False


@pytest.mark.parametrize(
    ("case", "account", "observed_at_ns", "reason_code"),
    (
        (
            "missing-account-status",
            {
                "id": ACCOUNT_ID,
                "cash": "990000",
                "trading_blocked": False,
                "account_blocked": False,
                "trade_suspended_by_user": False,
            },
            2_000_000_000,
            "BROKER_ACCOUNT_NOT_ACTIVE",
        ),
        (
            "future-observation",
            _account(),
            2_100_000_000_000_000_000,
            "BROKER_INVENTORY_OBSERVATION_FROM_FUTURE",
        ),
        (
            "missing-account-block-flag",
            {
                key: value
                for key, value in _account().items()
                if key != "trade_suspended_by_user"
            },
            2_000_000_000,
            "BROKER_ACCOUNT_TRADE_SUSPENDED_BY_USER_TRUTH_MISSING",
        ),
        (
            "missing-cash-truth",
            {
                key: value
                for key, value in _account().items()
                if key not in {"cash", "non_marginable_buying_power", "buying_power"}
            },
            2_000_000_000,
            "BROKER_CASH_TRUTH_MISSING_OR_INVALID",
        ),
    ),
)
def test_missing_account_status_and_future_observation_fail_closed(
    tmp_path,
    case,
    account,
    observed_at_ns,
    reason_code,
) -> None:
    case_path = tmp_path / case
    case_path.mkdir()
    _store, manager, coordinator = _stack(case_path)

    result = coordinator.reconcile_broker_inventory(
        _snapshot(
            positions=_broker_positions(),
            account=account,
            observed_at_ns=observed_at_ns,
        )
    )

    assert result["authorized"] is False
    assert reason_code in result["reason_codes"]
    assert manager.broker_inventory_authority_evidence("AVAXUSD")["authorized"] is False


def test_broker_short_position_snapshot_fails_closed(tmp_path) -> None:
    _store, manager, coordinator = _stack(tmp_path)
    positions = _broker_positions()
    positions[0]["side"] = "short"

    result = coordinator.reconcile_broker_inventory(
        _snapshot(positions=positions, observed_at_ns=2_000_000_000)
    )

    assert result["authorized"] is False
    assert "BROKER_POSITION_LONG_SIDE_REQUIRED:AVAXUSD" in result["reason_codes"]
    assert manager.broker_inventory_authority_evidence("AVAXUSD")["authorized"] is False


def test_opening_baseline_account_must_match_pinned_broker_account(tmp_path) -> None:
    context = _baseline_context()
    context["account_suffix"] = "bad999"
    _store, manager, coordinator = _stack(tmp_path, context=context)

    result = coordinator.reconcile_broker_inventory(
        _snapshot(positions=_broker_positions(), observed_at_ns=2_000_000_000)
    )

    assert result["authorized"] is False
    assert "BROKER_BASELINE_ACCOUNT_MISMATCH" in result["reason_codes"]
    assert manager.broker_inventory_authority_evidence("AVAXUSD")["authorized"] is False


def test_broker_snapshot_observation_regression_fails_closed(tmp_path) -> None:
    _store, manager, coordinator = _stack(tmp_path)
    first = coordinator.reconcile_broker_inventory(
        _snapshot(positions=_broker_positions(), observed_at_ns=4_000_000_000)
    )
    assert first["authorized"] is True

    regressed = coordinator.reconcile_broker_inventory(
        _snapshot(positions=_broker_positions(), observed_at_ns=3_000_000_000)
    )

    assert regressed["authorized"] is False
    assert "BROKER_INVENTORY_OBSERVATION_REGRESSION" in regressed["reason_codes"]
    assert manager.broker_inventory_authority_evidence("AVAXUSD")["authorized"] is False


def test_duplicate_active_reservation_identity_blocks_reconciliation(
    tmp_path,
    monkeypatch,
) -> None:
    store, _manager, coordinator = _stack(tmp_path)
    assert coordinator.reconcile_broker_inventory(
        _snapshot(positions=_broker_positions(), observed_at_ns=1_000_000_000)
    )["authorized"] is True
    assert _open_reservation(
        coordinator,
        client_order_id="duplicate-reservation",
        side="buy",
        qty="0.2",
        price="20",
    )["applied"] is True
    _mapping(store, "duplicate-reservation")
    rows = store.list_reservation_ledger(active_only=True, include_terminal=False)
    duplicate = dict(rows[0])
    duplicate["reservation_id"] = "reservation-duplicate-evidence"

    def _duplicate_rows(**_kwargs):
        return [rows[0], duplicate]

    monkeypatch.setattr(store, "list_reservation_ledger", _duplicate_rows)
    result = coordinator.reconcile_broker_inventory(
        _snapshot(
            positions=_broker_positions(),
            open_orders=[
                {
                    "id": "broker-duplicate-reservation",
                    "client_order_id": "duplicate-reservation",
                    "symbol": "BTCUSD",
                    "side": "buy",
                    "qty": "0.2",
                    "filled_qty": "0",
                    "limit_price": "20",
                }
            ],
            observed_at_ns=2_000_000_000,
        )
    )

    assert result["authorized"] is False
    assert (
        "RESERVATION_CLIENT_ID_DUPLICATE:duplicate-reservation"
        in result["reason_codes"]
    )


def test_unmatched_mapping_and_missing_broker_fill_quantity_block_reconciliation(
    tmp_path,
) -> None:
    unmatched_path = tmp_path / "unmatched"
    unmatched_path.mkdir()
    store, _manager, coordinator = _stack(unmatched_path)
    assert coordinator.reconcile_broker_inventory(
        _snapshot(positions=_broker_positions(), observed_at_ns=1_000_000_000)
    )["authorized"] is True
    _mapping(store, "unmatched-mapping")
    unmatched = coordinator.reconcile_broker_inventory(
        _snapshot(positions=_broker_positions(), observed_at_ns=2_000_000_000)
    )
    assert unmatched["authorized"] is False
    assert (
        "ORDER_MAPPING_ACTIVE_RESERVATION_MISSING:unmatched-mapping"
        in unmatched["reason_codes"]
    )
    assert (
        "ORDER_MAPPING_BROKER_OPEN_ORDER_MISSING:unmatched-mapping"
        in unmatched["reason_codes"]
    )

    incomplete_path = tmp_path / "incomplete"
    incomplete_path.mkdir()
    store, _manager, coordinator = _stack(incomplete_path)
    assert coordinator.reconcile_broker_inventory(
        _snapshot(positions=_broker_positions(), observed_at_ns=1_000_000_000)
    )["authorized"] is True
    assert _open_reservation(
        coordinator,
        client_order_id="missing-filled-quantity",
        side="buy",
        qty="0.2",
        price="20",
    )["applied"] is True
    _mapping(store, "missing-filled-quantity")
    incomplete = coordinator.reconcile_broker_inventory(
        _snapshot(
            positions=_broker_positions(),
            open_orders=[
                {
                    "id": "broker-missing-filled-quantity",
                    "client_order_id": "missing-filled-quantity",
                    "symbol": "BTCUSD",
                    "side": "buy",
                    "qty": "0.2",
                    "limit_price": "20",
                }
            ],
            observed_at_ns=2_000_000_000,
        )
    )
    assert incomplete["authorized"] is False
    assert (
        "RESERVATION_BROKER_QUANTITY_TRUTH_MISSING_OR_INVALID:missing-filled-quantity"
        in incomplete["reason_codes"]
    )


def test_non_get_inventory_response_and_unexpected_adapter_error_fail_closed(
    tmp_path,
) -> None:
    store, _manager, coordinator = _stack(tmp_path)
    adapter = _ReadOnlyAdapter(positions=_broker_positions())
    router = OrderRouter(
        primary_exchange="alpaca",
        paper_mode=True,
        state_store=store,
        execution_broker="alpaca_paper",
        broker_gateway_adapter=adapter,
        reservation_lifecycle_coordinator=coordinator,
        broker_inventory_reconciliation_required=True,
    )
    non_get_account = replace(
        _response("/v2/account", _account()),
        request_method="POST",
    )
    result = router._gateway_inventory_reconciliation_from_responses(
        account_response=non_get_account,
        positions_response=_response("/v2/positions", _broker_positions()),
        open_orders_response=_response("/v2/orders", []),
        source_event="offline_non_get_contract_test",
    )
    assert result["authorized"] is False
    assert "BROKER_INVENTORY_GET_ONLY_READ_REQUIRED" in result["reason_codes"]
    assert "BROKER_INVENTORY_RESPONSE_CONTRACT_INVALID" in result["reason_codes"]
    assert adapter.request_counts["POST"] == 0
    assert adapter.request_counts["DELETE"] == 0

    class _UnexpectedReadFailureAdapter(_ReadOnlyAdapter):
        def get_account(self):
            raise ValueError("unsanitized adapter detail must not escape")

    failed_adapter = _UnexpectedReadFailureAdapter(positions=_broker_positions())
    failed_router = OrderRouter(
        primary_exchange="alpaca",
        paper_mode=True,
        state_store=StateStore(db_path=str(tmp_path / "failed-state.db")),
        execution_broker="alpaca_paper",
        broker_gateway_adapter=failed_adapter,
        reservation_lifecycle_coordinator=coordinator,
        broker_inventory_reconciliation_required=True,
    )
    failed = failed_router.reconcile_startup_broker_inventory()
    assert failed == {
        "status": "BLOCKED",
        "authorized": False,
        "reason_codes": ("BROKER_INVENTORY_READ_FAILED",),
        "broker_read_occurred": True,
        "broker_mutation_occurred": False,
    }


def test_post_ack_invalid_read_contract_revokes_previously_reconciled_inventory(
    tmp_path,
) -> None:
    context = _baseline_context((), baseline_id="post-ack-stale-authority")
    store, manager, coordinator = _stack(tmp_path, context=context)
    adapter = _ReadOnlyAdapter(positions=[])
    router = OrderRouter(
        primary_exchange="alpaca",
        paper_mode=True,
        state_store=store,
        execution_broker="alpaca_paper",
        broker_gateway_adapter=adapter,
        reservation_lifecycle_coordinator=coordinator,
        reservation_lifecycle_enabled=True,
        broker_inventory_reconciliation_required=True,
    )
    assert router.reconcile_startup_broker_inventory()["authorized"] is True
    assert manager.broker_inventory_authority_evidence("BTCUSD")["authorized"] is True

    order = OrderRequest(
        id="post-ack-contract-order",
        symbol="BTCUSD",
        side=OrderSide.BUY,
        quantity=Decimal("0.1"),
        order_type=OrderType.LIMIT,
        limit_price=Decimal("50000"),
        strategy=SleeveType.SHADOW_FRONT,
        confidence=0.8,
        decision_uuid="decision-post-ack-contract-order",
        exchange_ts_ns=1_000_000_000,
        receive_ts_ns=1_000_000_100,
        metadata={"action": "buy_to_open"},
    )
    broker_order_id = "broker-post-ack-contract-order"
    assert router._register_active_order_id_mapping(
        order,
        broker="alpaca",
        venue_order_id=broker_order_id,
        broker_order_id=broker_order_id,
        exchange_txid=None,
        id_mapping_source="offline_ack_contract_test",
        ack_ts_ns=1_100_000_000,
    ) is True
    adapter.order_statuses[broker_order_id] = _response(
        "/v2/orders/wrong-order",
        {
            "id": broker_order_id,
            "client_order_id": order.id,
            "symbol": "BTCUSD",
            "side": "buy",
            "status": "accepted",
            "filled_qty": "0",
        },
        normalized_status=NormalizedBrokerStatus.ACCEPTED.value,
    )
    ack = BrokerGatewayResponse(
        adapter_id="alpaca_paper",
        venue_id="alpaca",
        portal_id="alpaca_paper",
        environment="paper",
        request_method="POST",
        endpoint_path="/v2/orders",
        ok=True,
        mutation_occurred=True,
        live_blocked=True,
        broker_order_id=broker_order_id,
        client_order_id=order.id,
        normalized_status=NormalizedBrokerStatus.ACCEPTED.value,
    )

    result = router._post_ack_gateway_reconciliation(order, ack)

    assert result["status"] == "RECONCILIATION_CONFLICT"
    stale = manager.broker_inventory_authority_evidence("BTCUSD")
    assert stale["authorized"] is False
    assert stale["reason_codes"] == ("POST_ACK_BROKER_CONTRACT_INVALID",)
    assert adapter.request_counts["POST"] == 0
    assert adapter.request_counts["DELETE"] == 0


def _fill_hydration_stack(tmp_path, *, client_order_id: str):
    context = _baseline_context((), baseline_id=f"baseline-{client_order_id}")
    store, _manager, coordinator = _stack(tmp_path, context=context)
    adapter = _ReadOnlyAdapter(positions=[])
    router = OrderRouter(
        primary_exchange="alpaca",
        paper_mode=True,
        state_store=store,
        execution_broker="alpaca_paper",
        broker_gateway_adapter=adapter,
        reservation_lifecycle_coordinator=coordinator,
        broker_inventory_reconciliation_required=True,
    )
    order = OrderRequest(
        id=client_order_id,
        symbol="BTCUSD",
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        order_type=OrderType.LIMIT,
        limit_price=Decimal("50000"),
        strategy=SleeveType.SHADOW_FRONT,
        confidence=0.8,
        decision_uuid=f"decision-{client_order_id}",
        exchange_ts_ns=1_000_000_000,
        receive_ts_ns=1_000_000_100,
        metadata={"action": "buy_to_open"},
    )
    assert router._register_active_order_id_mapping(
        order,
        broker="alpaca",
        venue_order_id=f"broker-{client_order_id}",
        broker_order_id=f"broker-{client_order_id}",
        exchange_txid=None,
        id_mapping_source="offline_fill_truth_test",
        ack_ts_ns=1_100_000_000,
    ) is True
    mapping = router._get_active_order_id_mapping(client_order_id, "alpaca")
    assert mapping is not None
    return store, router, order, mapping


def test_equal_cumulative_quantity_with_different_price_is_a_conflict(tmp_path) -> None:
    store, router, order, mapping = _fill_hydration_stack(
        tmp_path,
        client_order_id="cumulative-price-conflict",
    )
    router._broker_fill_activity_cache = []
    first = router._hydrate_fill_ledger_from_broker_payload(
        mapping,
        {
            "filled_qty": "0.4",
            "filled_avg_price": "50000",
            "filled_at": "2026-07-18T12:00:00Z",
            "status": "partially_filled",
        },
        source_event="offline_cumulative_price_test",
        order=order,
    )
    assert first["status"] == "PARTIAL"

    conflicting = router._hydrate_fill_ledger_from_broker_payload(
        mapping,
        {
            "filled_qty": "0.4",
            "filled_avg_price": "50001",
            "filled_at": "2026-07-18T12:00:01Z",
            "status": "partially_filled",
        },
        source_event="offline_cumulative_price_test",
        order=order,
    )
    assert conflicting["status"] == "CONFLICT"
    assert conflicting["conflict_field"] == "cumulative_filled_avg_price_conflict"
    assert len(store.list_broker_fill_ledger()) == 1


def test_fill_activity_without_broker_activity_id_is_not_accepted(tmp_path) -> None:
    store, router, order, mapping = _fill_hydration_stack(
        tmp_path,
        client_order_id="missing-activity-id",
    )
    router._broker_fill_activity_cache = [
        {
            "order_id": "broker-missing-activity-id",
            "client_order_id": "missing-activity-id",
            "symbol": "BTCUSD",
            "side": "buy",
            "qty": "0.4",
            "price": "50000",
            "transaction_time": "2026-07-18T12:00:00Z",
        }
    ]

    result = router._hydrate_fill_ledger_from_broker_payload(
        mapping,
        {
            "filled_qty": "0.4",
            "filled_avg_price": "50000",
            "filled_at": "2026-07-18T12:00:00Z",
            "status": "partially_filled",
        },
        source_event="offline_missing_activity_id_test",
        order=order,
    )

    assert result["status"] == "MISSING_TRUTH"
    assert result["missing_fields"] == ("broker_activity_id",)
    assert store.list_broker_fill_ledger() == []


@pytest.mark.parametrize(
    ("missing_field", "expected_missing"),
    (
        ("qty", "filled_qty"),
        ("price", "filled_avg_price"),
        ("transaction_time", "timestamp"),
    ),
)
def test_incomplete_fill_activity_never_borrows_cumulative_order_truth(
    tmp_path,
    missing_field: str,
    expected_missing: str,
) -> None:
    client_order_id = f"activity-missing-{missing_field}"
    store, router, order, mapping = _fill_hydration_stack(
        tmp_path,
        client_order_id=client_order_id,
    )
    activity = {
        "id": f"broker-activity-{missing_field}",
        "order_id": f"broker-{client_order_id}",
        "client_order_id": client_order_id,
        "symbol": "BTCUSD",
        "side": "buy",
        "qty": "0.4",
        "price": "50000",
        "transaction_time": "2026-07-18T12:00:00Z",
    }
    activity.pop(missing_field)
    router._broker_fill_activity_cache = [activity]

    result = router._hydrate_fill_ledger_from_broker_payload(
        mapping,
        {
            "filled_qty": "0.4",
            "filled_avg_price": "50000",
            "filled_at": "2026-07-18T12:00:00Z",
            "status": "partially_filled",
        },
        source_event="offline_incomplete_activity_truth_test",
        order=order,
    )

    assert result["status"] == "MISSING_TRUTH"
    assert expected_missing in result["missing_fields"]
    assert store.list_broker_fill_ledger() == []
    assert store.list_broker_inventory_events(strict=True) == []


def test_all_partial_fill_activities_hydrate_once_and_reconcile_complete_quantity(
    tmp_path,
) -> None:
    client_order_id = "multi-activity-partial-fills"
    store, router, order, mapping = _fill_hydration_stack(
        tmp_path,
        client_order_id=client_order_id,
    )
    broker_order_id = f"broker-{client_order_id}"
    router._broker_fill_activity_cache = [
        {
            "id": "activity-partial-a",
            "order_id": broker_order_id,
            "client_order_id": client_order_id,
            "symbol": "BTCUSD",
            "side": "buy",
            "qty": "0.4",
            "price": "50000",
            "transaction_time": "2026-07-18T12:00:00Z",
        },
        {
            "id": "activity-partial-b",
            "order_id": broker_order_id,
            "client_order_id": client_order_id,
            "symbol": "BTCUSD",
            "side": "buy",
            "qty": "0.6",
            "price": "50100",
            "transaction_time": "2026-07-18T12:00:01Z",
        },
    ]

    hydrated = router._hydrate_fill_ledger_from_broker_payload(
        mapping,
        {
            "filled_qty": "1",
            "filled_avg_price": "50060",
            "filled_at": "2026-07-18T12:00:01Z",
            "status": "filled",
        },
        source_event="offline_multi_activity_partial_fill_test",
        order=order,
    )

    assert hydrated["status"] == "PARTIAL"
    assert hydrated["activity_count"] == 2
    assert hydrated["inserted_count"] == 2
    assert hydrated["broker_activity_ids"] == (
        "activity-partial-a",
        "activity-partial-b",
    )
    assert router._broker_fill_activity_cache is None
    events = store.list_broker_inventory_events(
        baseline_snapshot_id=f"baseline-{client_order_id}",
        strict=True,
    )
    assert [row["fill_id"] for row in events] == [
        "broker_activity:alpaca:activity-partial-a",
        "broker_activity:alpaca:activity-partial-b",
    ]
    assert sum(Decimal(row["quantity"]) for row in events) == Decimal("1")
    assert store.mark_order_id_mapping_terminal(
        client_order_id,
        "alpaca",
        status="filled",
        terminal_reason="offline_multi_activity_complete",
    ) is True

    reconciled = router._reservation_lifecycle_coordinator.reconcile_broker_inventory(
        _snapshot(
            positions=_broker_positions(
                (("BTCUSD", "1", "50060", "50100"),)
            ),
            observed_at_ns=2_000_000_000_000_000_000,
        )
    )

    assert reconciled["authorized"] is True, reconciled
    assert reconciled["effective_fill_count"] == 2


@pytest.mark.parametrize(
    ("current_qty", "managed_qty", "unknown_qty", "expected_reason"),
    (
        ("not-a-number", "0.7", "0", "CURRENT_BROKER_POSITION_QUANTITY_INVALID:BTCUSD"),
        ("NaN", "0.7", "0", "CURRENT_BROKER_POSITION_QUANTITY_INVALID:BTCUSD"),
        ("Infinity", "0.7", "0", "CURRENT_BROKER_POSITION_QUANTITY_INVALID:BTCUSD"),
        ("-0.7", "0.7", "0", "CURRENT_BROKER_POSITION_QUANTITY_INVALID:BTCUSD"),
        ("0.7", "NaN", "0", "MANAGED_RECONCILIATION_QUANTITY_INVALID:BTCUSD"),
        ("0.7", "0.7", "not-a-number", "MANAGED_RECONCILIATION_ATTRIBUTION_INVALID:BTCUSD"),
        ("0.7", "0.7", "NaN", "MANAGED_RECONCILIATION_ATTRIBUTION_INVALID:BTCUSD"),
    ),
)
def test_malformed_managed_baseline_quantities_fail_closed(
    current_qty,
    managed_qty,
    unknown_qty,
    expected_reason,
) -> None:
    accepted = accept_existing_position_baseline(
        _preflight("0.5"),
        accepted_by="Shan/local operator",
    )
    managed = {
        "status": "RECONCILED",
        "authorized": True,
        "exposure_ingest": {"applied": True},
        "snapshot_id": "broker-inventory-malformed-test",
        "baseline_snapshot_id": accepted["baseline_snapshot_id"],
        "account_suffix": ACCOUNT_SUFFIX,
        "metadata": {"opening_baseline_preserved": True},
        "positions": [
            {
                "symbol": "BTCUSD",
                "broker_qty": managed_qty,
                "avg_entry_price": "50000",
                "metadata": {
                    "attribution_status": "KNOWN",
                    "unknown_attribution_qty": unknown_qty,
                },
            }
        ],
    }
    current = _preflight(current_qty)

    state = build_baseline_adoption_state(
        current_snapshot=current,
        accepted_baseline=accepted,
        managed_reconciliation=managed,
    )

    assert state["status"] == PAPER_BASELINE_DRIFT_REQUIRES_REFRESH
    assert state["start_ready"] is False
    assert state["managed_reconciliation_status"] == expected_reason


def test_pending_reservations_must_be_hydrated_into_runtime_before_reconciliation(
    tmp_path,
) -> None:
    context = _baseline_context((), baseline_id="baseline-runtime-reservation-parity")
    store, _manager1, coordinator1 = _stack(tmp_path, context=context)
    assert coordinator1.reconcile_broker_inventory(
        _snapshot(positions=[], observed_at_ns=1_000_000_000)
    )["authorized"] is True
    assert _open_reservation(
        coordinator1,
        client_order_id="runtime-parity-order",
        side="buy",
        qty="0.2",
        price="50000",
    )["applied"] is True
    _mapping(store, "runtime-parity-order")

    manager2 = ExposureManager(
        Decimal("1000000"),
        require_broker_inventory_reconciliation=True,
    )
    coordinator2 = ReservationLifecycleCoordinator(
        exposure_manager=manager2,
        state_store=store,
        baseline_context=context,
        now_ns_provider=lambda: 2_000_000_000_000_000_000,
    )
    result = coordinator2.reconcile_broker_inventory(
        _snapshot(
            positions=[],
            open_orders=[
                {
                    "id": "broker-runtime-parity-order",
                    "client_order_id": "runtime-parity-order",
                    "symbol": "BTCUSD",
                    "side": "buy",
                    "qty": "0.2",
                    "filled_qty": "0",
                    "limit_price": "50000",
                }
            ],
            observed_at_ns=2_000_000_000,
        )
    )

    assert result["authorized"] is False
    assert "BROKER_PENDING_RESERVATION_RUNTIME_MISMATCH" in result["reason_codes"]
    assert manager2.broker_inventory_authority_evidence("BTCUSD")["authorized"] is False


def test_realized_pnl_follows_acquired_lot_sleeves_not_exit_sleeve(tmp_path) -> None:
    context = _baseline_context((), baseline_id="baseline-sleeve-realization")
    _store, manager, coordinator = _stack(tmp_path, context=context)
    events = (
        {
            **_inventory_fill("sleeve-buy-shadow", "1"),
            "client_order_id": "sleeve-buy-shadow",
            "broker_order_id": "broker-sleeve-buy-shadow",
            "price": "100",
            "sleeve": SleeveType.SHADOW_FRONT.value,
            "event_ts_ns": 1_000_000_000,
        },
        {
            **_inventory_fill("sleeve-buy-flv", "1"),
            "client_order_id": "sleeve-buy-flv",
            "broker_order_id": "broker-sleeve-buy-flv",
            "price": "200",
            "sleeve": SleeveType.FLV.value,
            "event_ts_ns": 2_000_000_000,
        },
        {
            **_inventory_fill("sleeve-sell-gamma", "1.5"),
            "client_order_id": "sleeve-sell-gamma",
            "broker_order_id": "broker-sleeve-sell-gamma",
            "side": "sell",
            "action": "sell_to_close",
            "price": "300",
            "sleeve": SleeveType.GAMMA_FRONT.value,
            "event_ts_ns": 3_000_000_000,
        },
    )
    for event in events:
        assert coordinator.record_broker_inventory_event(event)["persisted"] is True

    result = coordinator.reconcile_broker_inventory(
        _snapshot(
            positions=_broker_positions((('BTCUSD', '0.5', '200', '300'),)),
            observed_at_ns=4_000_000_000,
        )
    )

    assert result["authorized"] is True
    shadow = manager.position_for(SleeveType.SHADOW_FRONT, "BTCUSD")
    flv = manager.position_for(SleeveType.FLV, "BTCUSD")
    gamma = manager.position_for(SleeveType.GAMMA_FRONT, "BTCUSD")
    assert shadow is not None and shadow.qty == Decimal("0")
    assert shadow.realized_pnl == Decimal("200")
    assert flv is not None and flv.qty == Decimal("0.5")
    assert flv.realized_pnl == Decimal("50.0")
    assert gamma is None
    evidence = manager.broker_inventory_authority_evidence("BTCUSD")
    assert evidence["realized_pnl_basis"] == "GROSS_EX_FEES"
    assert evidence["fee_truth_status"] == "NOT_ATTRIBUTED_STAGE_2"
    assert evidence["fee_truth_complete"] is False
    assert evidence["net_realized_pnl_claimed"] is False
    risk_snapshot = manager.get_risk_snapshot({})
    assert risk_snapshot["broker_inventory_pnl_truth"] == {
        "realized_pnl_basis": "GROSS_EX_FEES",
        "fee_truth_status": "NOT_ATTRIBUTED_STAGE_2",
        "fee_truth_complete": False,
        "net_realized_pnl_claimed": False,
    }


def test_mapping_hydration_read_failure_blocks_startup_before_broker_read(
    tmp_path,
    monkeypatch,
) -> None:
    store, _manager, coordinator = _stack(tmp_path)
    adapter = _ReadOnlyAdapter(positions=_broker_positions())

    def _mapping_read_failure(**_kwargs):
        raise RuntimeError("order_id_mapping_read_failed")

    monkeypatch.setattr(store, "list_order_id_mappings", _mapping_read_failure)
    router = OrderRouter(
        primary_exchange="alpaca",
        paper_mode=True,
        state_store=store,
        execution_broker="alpaca_paper",
        broker_gateway_adapter=adapter,
        reservation_lifecycle_coordinator=coordinator,
        broker_inventory_reconciliation_required=True,
    )

    result = router.reconcile_startup_broker_inventory()

    assert result["authorized"] is False
    assert result["reason_codes"] == ("ORDER_MAPPING_STATE_READ_FAILED",)
    assert result["broker_read_occurred"] is False
    assert adapter.calls == []


def test_invalid_fill_timestamp_and_invalid_status_read_contract_do_not_create_fill(
    tmp_path,
) -> None:
    timestamp_path = tmp_path / "timestamp"
    timestamp_path.mkdir()
    store, router, order, mapping = _fill_hydration_stack(
        timestamp_path,
        client_order_id="invalid-fill-timestamp",
    )
    router._broker_fill_activity_cache = []
    invalid_timestamp = router._hydrate_fill_ledger_from_broker_payload(
        mapping,
        {
            "filled_qty": "0.4",
            "filled_avg_price": "50000",
            "filled_at": "not-an-iso-timestamp",
            "status": "partially_filled",
        },
        source_event="offline_invalid_fill_timestamp_test",
        order=order,
    )
    assert invalid_timestamp["status"] == "MISSING_TRUTH"
    assert invalid_timestamp["missing_fields"] == ("valid_fill_timestamp",)
    assert store.list_broker_fill_ledger() == []

    contract_path = tmp_path / "status-contract"
    contract_path.mkdir()
    store = StateStore(db_path=str(contract_path / "state.db"))
    _mapping(store, "invalid-status-contract")
    bad_status = replace(
        _response(
            "/v2/orders/broker-invalid-status-contract",
            {
                "id": "broker-invalid-status-contract",
                "client_order_id": "invalid-status-contract",
                "symbol": "BTCUSD",
                "side": "buy",
                "status": "partially_filled",
                "filled_qty": "0.4",
                "filled_avg_price": "50000",
                "filled_at": "2026-07-18T12:00:00Z",
            },
            normalized_status=NormalizedBrokerStatus.PARTIALLY_FILLED.value,
        ),
        request_method="POST",
    )
    adapter = _ReadOnlyAdapter(
        positions=[],
        order_statuses={"broker-invalid-status-contract": bad_status},
    )
    contract_router = OrderRouter(
        primary_exchange="alpaca",
        paper_mode=True,
        state_store=store,
        execution_broker="alpaca_paper",
        broker_gateway_adapter=adapter,
    )
    evidence = contract_router.get_gateway_reconciliation("invalid-status-contract")
    mapping_row = store.get_order_id_mapping("invalid-status-contract", "alpaca")
    assert evidence["status"] == "RECONCILIATION_CONFLICT"
    assert evidence["preserve_mapping_active"] is True
    assert mapping_row["is_terminal"] is False
    assert store.list_broker_fill_ledger() == []


def test_cumulative_price_conflict_and_corrupt_reservation_identity_fail_closed(
    tmp_path,
    monkeypatch,
) -> None:
    cumulative_path = tmp_path / "cumulative"
    cumulative_path.mkdir()
    store, _manager, coordinator = _stack(
        cumulative_path,
        context=_baseline_context((), baseline_id="baseline-cumulative-price"),
    )
    for event_id, price, observed in (
        ("cumulative-price-a", "50000", 2_000_000_000),
        ("cumulative-price-b", "50001", 3_000_000_000),
    ):
        event = {
            **_inventory_fill(event_id, "0.4", semantics="CUMULATIVE_ORDER"),
            "client_order_id": "cumulative-price-order",
            "broker_order_id": "broker-cumulative-price-order",
            "price": price,
            "observed_at_ns": observed,
        }
        assert coordinator.record_broker_inventory_event(event)["persisted"] is True
    cumulative = coordinator.reconcile_broker_inventory(
        _snapshot(
            positions=_broker_positions((('BTCUSD', '0.4', '50001', '50001'),)),
            observed_at_ns=4_000_000_000,
        )
    )
    assert cumulative["authorized"] is False
    assert (
        "INVENTORY_FILL_CUMULATIVE_PRICE_CONFLICT:cumulative-price-order"
        in cumulative["reason_codes"]
    )

    reservation_path = tmp_path / "reservation"
    reservation_path.mkdir()
    store, _manager, coordinator = _stack(reservation_path)
    assert coordinator.reconcile_broker_inventory(
        _snapshot(positions=_broker_positions(), observed_at_ns=1_000_000_000)
    )["authorized"] is True
    assert _open_reservation(
        coordinator,
        client_order_id="corrupt-reservation",
        side="buy",
        qty="0.2",
        price="20",
    )["applied"] is True
    _mapping(store, "corrupt-reservation")
    rows = store.list_reservation_ledger(active_only=True, include_terminal=False)
    corrupt = dict(rows[0])
    corrupt["filled_qty"] = "0.1"

    def _corrupt_rows(**_kwargs):
        return [corrupt]

    monkeypatch.setattr(store, "list_reservation_ledger", _corrupt_rows)
    result = coordinator.reconcile_broker_inventory(
        _snapshot(
            positions=_broker_positions(),
            open_orders=[
                {
                    "id": "broker-corrupt-reservation",
                    "client_order_id": "corrupt-reservation",
                    "symbol": "BTCUSD",
                    "side": "buy",
                    "qty": "0.2",
                    "filled_qty": "0",
                    "limit_price": "20",
                }
            ],
            observed_at_ns=2_000_000_000,
        )
    )
    assert result["authorized"] is False
    assert (
        "RESERVATION_QUANTITY_IDENTITY_CONFLICT:corrupt-reservation"
        in result["reason_codes"]
    )


def test_opening_baseline_cost_basis_remains_immutable_after_same_symbol_buy(
    tmp_path,
) -> None:
    accepted = accept_existing_position_baseline(
        _preflight("1"),
        accepted_by="Shan/local operator",
    )
    context = build_paper_baseline_runtime_context(
        accepted,
        source_path="durable/operator/paper_baseline.json",
    ).to_dict()
    assert context["protected_positions"]["BTCUSD"]["avg_entry_price"] == "50000"
    _store, manager, coordinator = _stack(tmp_path, context=context)
    buy = {
        **_inventory_fill("immutable-baseline-cost-buy", "0.5"),
        "price": "60000",
    }
    assert coordinator.record_broker_inventory_event(buy)["persisted"] is True

    result = coordinator.reconcile_broker_inventory(
        _snapshot(
            positions=_broker_positions(
                (("BTCUSD", "1.5", "53333.33333333333333333333333", "55000"),)
            ),
            observed_at_ns=4_000_000_000,
        )
    )

    assert result["authorized"] is True, result
    adopted = manager.position_for(SleeveType.POVERTY_KILLER_AGGREGATE, "BTCUSD")
    acquired = manager.position_for(SleeveType.SHADOW_FRONT, "BTCUSD")
    assert adopted is not None and adopted.qty == Decimal("1")
    assert adopted.wap == Decimal("50000")
    assert acquired is not None and acquired.qty == Decimal("0.5")
    assert acquired.wap == Decimal("60000")


def test_future_inventory_event_is_refused_against_broker_snapshot(tmp_path) -> None:
    context = _baseline_context((), baseline_id="baseline-future-inventory-event")
    _store, manager, coordinator = _stack(tmp_path, context=context)
    event = {
        **_inventory_fill("future-inventory-event", "0.1"),
        "event_ts_ns": 5_000_000_000,
        "observed_at_ns": 3_000_000_000,
    }
    assert coordinator.record_broker_inventory_event(event)["persisted"] is True

    result = coordinator.reconcile_broker_inventory(
        _snapshot(
            positions=_broker_positions((("BTCUSD", "0.1", "50000", "50100"),)),
            observed_at_ns=4_000_000_000,
        )
    )

    assert result["authorized"] is False
    assert (
        "INVENTORY_EVENT_AFTER_BROKER_SNAPSHOT:future-inventory-event"
        in result["reason_codes"]
    )
    assert manager.broker_inventory_authority_evidence("BTCUSD")["authorized"] is False


def test_fill_events_for_one_order_cannot_change_symbol_or_side(tmp_path) -> None:
    context = _baseline_context((), baseline_id="baseline-order-identity-conflict")
    _store, _manager, coordinator = _stack(tmp_path, context=context)
    first = _inventory_fill("identity-fill-a", "0.1")
    conflicting = {
        **_inventory_fill("identity-fill-b", "0.2"),
        "symbol": "ETHUSD",
    }
    assert coordinator.record_broker_inventory_event(first)["persisted"] is True
    assert coordinator.record_broker_inventory_event(conflicting)["persisted"] is True

    result = coordinator.reconcile_broker_inventory(
        _snapshot(
            positions=_broker_positions(
                (
                    ("BTCUSD", "0.1", "50000", "50100"),
                    ("ETHUSD", "0.2", "3000", "3010"),
                )
            ),
            observed_at_ns=4_000_000_000,
        )
    )

    assert result["authorized"] is False
    assert "INVENTORY_FILL_ORDER_IDENTITY_CONFLICT:client-buy-1" in result["reason_codes"]


def test_durable_inventory_hash_corruption_fails_strict_read_and_admission(
    tmp_path,
) -> None:
    store, manager, coordinator = _stack(tmp_path)
    reconciled = coordinator.reconcile_broker_inventory(
        _snapshot(positions=_broker_positions(), observed_at_ns=4_000_000_000)
    )
    assert reconciled["authorized"] is True
    snapshot_id = reconciled["snapshot_id"]
    with store._get_connection() as conn:
        conn.execute(
            "UPDATE broker_inventory_snapshot_positions SET broker_qty = ? WHERE snapshot_id = ? AND symbol = ?",
            ("999", snapshot_id, "AVAXUSD"),
        )
        conn.commit()

    with pytest.raises(RuntimeError, match="broker_inventory_reconciliation_read_failed"):
        store.get_broker_inventory_reconciliation(snapshot_id, strict=True)
    manager.mark_broker_inventory_unreconciled("DURABLE_INVENTORY_CORRUPT")
    assert manager.broker_inventory_authority_evidence("AVAXUSD")["authorized"] is False


def test_durable_event_hash_corruption_blocks_reconciliation(tmp_path) -> None:
    context = _baseline_context((), baseline_id="baseline-event-hash-corruption")
    store, manager, coordinator = _stack(tmp_path, context=context)
    event = _inventory_fill("event-hash-corruption", "0.1")
    assert coordinator.record_broker_inventory_event(event)["persisted"] is True
    with store._get_connection() as conn:
        conn.execute(
            "UPDATE broker_inventory_events SET quantity = ? WHERE event_id = ?",
            ("9.9", "event-hash-corruption"),
        )
        conn.commit()

    result = coordinator.reconcile_broker_inventory(
        _snapshot(
            positions=_broker_positions((("BTCUSD", "0.1", "50000", "50100"),)),
            observed_at_ns=4_000_000_000,
        )
    )

    assert result["authorized"] is False
    assert "BROKER_INVENTORY_STATE_READ_FAILED" in result["reason_codes"]
    assert manager.broker_inventory_authority_evidence("BTCUSD")["authorized"] is False


def test_malformed_lot_quantity_identity_is_not_persisted(tmp_path) -> None:
    store = StateStore(db_path=str(tmp_path / "state.db"))
    status = store.persist_broker_inventory_reconciliation(
        {
            "snapshot_id": "malformed-lot-identity",
            "broker": "alpaca",
            "environment": "paper",
            "endpoint_family": "paper",
            "account_suffix": ACCOUNT_SUFFIX,
            "observed_at_ns": 4_000_000_000,
            "status": "RECONCILED",
            "reason_codes": (),
            "metadata": {},
        },
        positions=[
            {
                "symbol": "BTCUSD",
                "broker_qty": "1",
                "avg_entry_price": "50000",
                "mark_price": "50100",
                "metadata": {},
            }
        ],
        lots=[
            {
                "lot_id": "malformed-bot-lot",
                "symbol": "BTCUSD",
                "sleeve": SleeveType.SHADOW_FRONT.value,
                "provenance": "BOT_ACQUIRED",
                "original_qty": "1",
                "remaining_qty": "0.8",
                "sold_qty": "0.1",
                "avg_entry_price": "50000",
                "source_event_id": "fill-malformed",
                "acquired_at_ns": 1_000_000_000,
                "metadata": {},
            }
        ],
    )

    assert status == "failed"
    assert store.get_broker_inventory_reconciliation("malformed-lot-identity") is None


def test_unexpected_hydrated_mapping_adapter_failure_blocks_startup_without_crash(
    tmp_path,
) -> None:
    store, manager, coordinator = _stack(tmp_path)
    _mapping(store, "unexpected-recovery-failure")

    class _UnexpectedStatusFailureAdapter(_ReadOnlyAdapter):
        def get_order_status(self, _order_id: str):
            raise ValueError("untrusted adapter detail")

    router = OrderRouter(
        primary_exchange="alpaca",
        paper_mode=True,
        state_store=store,
        execution_broker="alpaca_paper",
        broker_gateway_adapter=_UnexpectedStatusFailureAdapter(
            positions=_broker_positions()
        ),
        reservation_lifecycle_coordinator=coordinator,
        broker_inventory_reconciliation_required=True,
    )

    result = router.reconcile_startup_broker_inventory()

    assert result["authorized"] is False
    assert result["reason_codes"] == ("ORDER_MAPPING_BROKER_RECOVERY_FAILED",)
    assert result["broker_mutation_occurred"] is False
    assert manager.broker_inventory_authority_evidence("AVAXUSD")["authorized"] is False


def test_supervisor_cold_boot_uses_only_integrity_verified_managed_lineage(
    tmp_path,
) -> None:
    operator_state = tmp_path / "operator"
    baseline_store = PaperBaselineStore(operator_state / "paper_baseline.json")
    accepted = baseline_store.accept(
        _preflight("0.5"),
        accepted_by="Shan/local operator",
    )
    assert accepted["accepted"] is True
    context = build_paper_baseline_runtime_context(
        accepted,
        source_path=baseline_store.path,
    ).to_dict()

    state_path = tmp_path / "data" / "state.db"
    store = StateStore(str(state_path))
    manager = ExposureManager(
        Decimal("1000000"),
        require_broker_inventory_reconciliation=True,
    )
    coordinator = ReservationLifecycleCoordinator(
        exposure_manager=manager,
        state_store=store,
        baseline_context=context,
        now_ns_provider=lambda: 2_000_000_000_000_000_000,
    )
    assert coordinator.record_broker_inventory_event(
        _inventory_fill("cold-boot-managed-fill", "0.2")
    )["persisted"] is True
    managed = coordinator.reconcile_broker_inventory(
        _snapshot(
            positions=_broker_positions(
                (("BTCUSD", "0.7", "50000.035273368320987654", "50100"),)
            ),
            observed_at_ns=4_000_000_000,
        )
    )
    assert managed["authorized"] is True
    store.close()
    database_before_read = state_path.read_bytes()

    account_pin = {
        "status": "PASS",
        "reason_code": "ALPACA_PAPER_ACCOUNT_PIN_OK",
        "expected_suffix": ACCOUNT_SUFFIX,
        "actual_suffix": ACCOUNT_SUFFIX,
        "paper_account_pinned": True,
        "broker_read_occurred": True,
        "broker_mutation_occurred": False,
    }
    supervisor = OperatorPaperSupervisor(
        config=PaperSupervisorConfig(
            repo_root=tmp_path,
            operator_state_dir=str(operator_state),
            state_store_path=str(state_path),
            session_store_path=str(operator_state / "sessions.jsonl"),
            process_env={
                "APCA_API_KEY_ID": "offline-test-paper-key",
                "APCA_API_SECRET_KEY": "offline-test-paper-secret",
                "APCA_API_BASE_URL": "https://paper-api.alpaca.markets",
            },
        ),
        runner=SimpleNamespace(),
        account_identity_checker=lambda _env: dict(account_pin),
    )
    supervisor._process_paper_broker_read_authorized = True
    current_portfolio = {
        "data_source": "BROKER_CONFIRMED",
        "broker_read_occurred": True,
        "broker_mutation_occurred": False,
        "summary": {
            "account_id": ACCOUNT_ID,
            "account_status": "ACTIVE",
            "status": "ACTIVE",
            "trading_blocked": False,
            "account_blocked": False,
        },
        "positions": [
            {
                **_preflight("0.7")["positions"][0],
                "avg_entry_price": "50000.035273368320987654",
            }
        ],
        "open_orders": [],
    }

    preflight = supervisor.record_paper_broker_preflight(current_portfolio)

    assert preflight["status"] == "PASS", (
        preflight.get("reason_code"),
        preflight.get("baseline_state"),
    )
    baseline_state = preflight["baseline_state"]
    assert baseline_state["start_ready"] is True
    assert baseline_state["managed_reconciliation_durable_verified"] is True
    assert baseline_state["runtime_reingest_required"] is True
    assert baseline_state["managed_reconciliation_state_read"]["status"] == "VERIFIED"
    assert preflight["broker_mutation_occurred"] is False
    assert state_path.read_bytes() == database_before_read

    with sqlite3.connect(str(state_path)) as connection:
        connection.execute(
            "UPDATE broker_inventory_snapshots SET open_order_count = 1 WHERE snapshot_id = ?",
            (managed["snapshot_id"],),
        )
        connection.commit()

    refused = supervisor.record_paper_broker_preflight(current_portfolio)

    assert refused["status"] == "BLOCKED"
    assert refused["baseline_state"]["start_ready"] is False
    assert refused["baseline_state"]["managed_reconciliation_state_read"]["status"] == "BLOCKED"
    assert (
        refused["baseline_state"]["managed_reconciliation_state_read"]["reason_code"]
        == "MANAGED_RECONCILIATION_STATE_READ_FAILED"
    )
    assert refused["broker_mutation_occurred"] is False
