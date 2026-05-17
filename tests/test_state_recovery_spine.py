from __future__ import annotations

import inspect
import json
from decimal import Decimal

from app.execution.fee_model import FeeModel
from app.execution.latency_model import LatencyModel
from app.execution.order_router import OrderRouter
from app.execution.paper_broker import PaperBroker, PaperMarketContext, PriceLevel
from app.execution.slippage_model import SlippageModel
from app.models import OrderRequest
from app.models.enums import OrderSide as ModelOrderSide
from app.models.enums import OrderType as ModelOrderType
from app.models.enums import SleeveType
from app.risk.exposure_manager import ExposureManager
from app.state.state_store import StateStore
from app.symbol_runtime import SymbolRuntime
from app.telemetry.event_store import TelemetryEventStore
from app.utils.enums import OrderSide, OrderStatus, OrderType, TimeInForce


T0_NS = 1_777_948_800_000_000_000


def _store(path) -> StateStore:
    return StateStore(str(path))


def _manager() -> ExposureManager:
    return ExposureManager(initial_equity=Decimal("20000"))


def _open_reservation(manager: ExposureManager, store: StateStore, **overrides):
    data = {
        "reservation_id": "reservation-active",
        "client_order_id": "client-active",
        "decision_uuid": "decision-active",
        "reservation_dedupe_key": "decision-active:client-active",
        "symbol": "ETH/USD",
        "side": ModelOrderSide.BUY,
        "sleeve": SleeveType.SECTOR_ROTATION,
        "qty": Decimal("1.0"),
        "price_basis": Decimal("2500.00"),
        "order_type": "limit",
        "source_lifecycle_phase": "state_recovery_open",
        "source_idempotency_key": "decision-active:client-active:open",
    }
    data.update(overrides)
    return manager.guarded_open_reservation(state_store=store, **data)


def _fill_reservation(manager: ExposureManager, store: StateStore, **overrides):
    data = {
        "reservation_id": "reservation-active",
        "client_order_id": "client-active",
        "fill_idempotency_key": "fill-active-001",
        "cumulative_filled_qty": Decimal("0.25"),
        "fill_delta_qty": Decimal("0.25"),
        "status_source": "paper_broker.execution_report",
        "source_event_id": "paper-report-active-001",
    }
    data.update(overrides)
    return manager.guarded_apply_fill_to_reservation(state_store=store, **data)


def _release_reservation(manager: ExposureManager, store: StateStore, **overrides):
    data = {
        "reservation_id": "reservation-terminal",
        "client_order_id": "client-terminal",
        "reservation_dedupe_key": "decision-terminal:client-terminal",
        "release_idempotency_key": "reservation-terminal:terminal_mapping_proof:filled:proof-001",
        "release_reason": "terminal_mapping_proof",
        "terminal_status": "filled",
        "terminal_source": "mark_terminal_from_status_evidence",
        "released_qty": Decimal("1.0"),
        "released_notional": Decimal("3000.00"),
        "source_event_id": "proof-terminal-001",
    }
    data.update(overrides)
    return manager.guarded_release_reservation(state_store=store, **data)


def _paper_broker() -> PaperBroker:
    return PaperBroker(
        fee_model=FeeModel(),
        slippage_model=SlippageModel(),
        latency_model=LatencyModel(base_latency_ms=0, jitter_ms=0, exchange_processing_ms=0),
    )


def _market(ts_ns: int) -> PaperMarketContext:
    return PaperMarketContext(
        symbol="ETH/USD",
        timestamp_ns=ts_ns,
        mid_price=Decimal("2500.00"),
        best_bid=Decimal("2499.50"),
        best_ask=Decimal("2500.50"),
        ask_levels=(PriceLevel(price=Decimal("2500.50"), quantity=Decimal("1.0")),),
        bid_levels=(PriceLevel(price=Decimal("2499.50"), quantity=Decimal("1.0")),),
    )


def _economic_order() -> OrderRequest:
    return OrderRequest(
        id="state-recovery-client-order",
        symbol="ETH/USD",
        side=ModelOrderSide.BUY,
        order_type=ModelOrderType.MARKET,
        quantity=Decimal("0.5"),
        limit_price=None,
        strategy=SleeveType.SECTOR_ROTATION,
        confidence=0.90,
        decision_uuid="state-recovery-decision",
        exchange_ts_ns=T0_NS,
        receive_ts_ns=T0_NS,
        metadata={"harness": "state_recovery_spine"},
    )


def test_reservation_state_survives_restart_without_duplicate_risk_state(tmp_path):
    db_path = tmp_path / "state.db"
    store = _store(db_path)
    manager = _manager()

    assert _open_reservation(manager, store)["applied"] is True
    assert _fill_reservation(manager, store)["applied"] is True
    assert _open_reservation(
        manager,
        store,
        reservation_id="reservation-terminal",
        client_order_id="client-terminal",
        decision_uuid="decision-terminal",
        reservation_dedupe_key="decision-terminal:client-terminal",
        source_idempotency_key="decision-terminal:client-terminal:open",
        price_basis=Decimal("3000.00"),
    )["applied"] is True
    assert _release_reservation(manager, store)["applied"] is True
    store.close()

    restarted_store = _store(db_path)
    restarted_manager = _manager()
    active_rows = restarted_store.list_reservation_ledger(active_only=True, include_terminal=False)
    all_rows = restarted_store.list_reservation_ledger(active_only=False, include_terminal=True)
    tombstones = [
        restarted_store.get_reservation_release_tombstone(reservation_id="reservation-terminal")
    ]
    progress = restarted_store.list_reservation_fill_progress("reservation-active")

    result = restarted_manager.hydrate_reservations_from_ledger(
        all_rows,
        release_tombstones=tombstones,
        fill_progress=progress,
    )

    assert [row["reservation_id"] for row in active_rows] == ["reservation-active"]
    assert result["valid"] is True
    assert result["hydrated"] == ("reservation-active",)
    skipped = {item["reservation_id"]: item["reason"] for item in result["skipped"]}
    assert skipped["reservation-terminal"] in {"terminal_ledger_row", "release_tombstone_present"}

    hydrated = restarted_manager.reservations_for(symbol="ETH/USD")
    assert len(hydrated) == 1
    assert hydrated[0].reservation_id == "reservation-active"
    assert hydrated[0].filled_qty == Decimal("0.25")
    assert hydrated[0].open_qty == Decimal("0.75")

    duplicate_release = _release_reservation(
        restarted_manager,
        restarted_store,
        release_idempotency_key="reservation-terminal:terminal_mapping_proof:filled:proof-002",
    )
    assert duplicate_release["applied"] is False
    assert duplicate_release["failed_reason"] == "reservation_already_released"
    assert [r.reservation_id for r in restarted_manager.reservations_for()] == [
        "reservation-active"
    ]


def test_paper_broker_snapshot_restore_rebuilds_open_order_state_without_duplicate_fill():
    broker = _paper_broker()
    order = broker.submit_order_detailed(
        symbol="ETH/USD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.GTC,
        quantity=Decimal("0.5"),
        price=None,
        ts_ns=T0_NS,
        client_id="state-recovery-broker-order",
    )
    snapshot = broker.get_snapshot(current_prices={"ETH/USD": Decimal("2500.00")}, ts_ns=T0_NS)

    recovered = _paper_broker()
    recovered.restore_from_snapshot(snapshot)

    assert recovered.validate_invariants()["valid"] is True
    assert recovered.open_orders["state-recovery-broker-order"].order_id == order.order_id
    assert len(recovered._matching_heap) == 1

    reports = recovered.process_matching_detailed(
        current_ts_ns=T0_NS,
        market_by_symbol={"ETH/USD": _market(T0_NS)},
    )
    assert [report.status for report in reports] == [
        OrderStatus.ACKNOWLEDGED,
        OrderStatus.FULLY_FILLED,
    ]
    assert "state-recovery-broker-order" not in recovered.open_orders
    assert recovered.validate_invariants()["valid"] is True

    duplicate_reports = recovered.process_matching_detailed(
        current_ts_ns=T0_NS + 1,
        market_by_symbol={"ETH/USD": _market(T0_NS + 1)},
    )
    assert duplicate_reports == []
    terminal_reports = [
        report
        for report in recovered.execution_reports
        if report.client_id == "state-recovery-broker-order"
        and report.status == OrderStatus.FULLY_FILLED
    ]
    assert len(terminal_reports) == 1


def test_fill_telemetry_remains_readable_after_restart_without_replay_duplication(tmp_path):
    db_path = tmp_path / "telemetry.db"
    store = TelemetryEventStore(str(db_path))
    router = OrderRouter(paper_mode=True, telemetry_store=store)
    router.update_market_mid("ETH/USD", 2500.00, T0_NS)

    fill = router.submit_order(_economic_order())
    assert fill is not None
    assert len(store.get_events_by_type("fill", limit=20)) == 1

    restarted_store = TelemetryEventStore(str(db_path))
    restarted_events = restarted_store.get_events_by_type("fill", limit=20)
    assert len(restarted_events) == 1
    payload = json.loads(restarted_events[0]["payload_json"])
    assert payload["decision_uuid"] == "state-recovery-decision"
    assert payload["order_intent_id"] == "state-recovery-client-order"
    assert Decimal(payload["requested_qty"]) == Decimal("0.5")
    assert Decimal(payload["quantity"]) == fill.quantity
    assert Decimal(payload["fee"]) == fill.fee
    assert payload["paper_mode"] is True

    OrderRouter(paper_mode=True, telemetry_store=restarted_store)
    assert len(restarted_store.get_events_by_type("fill", limit=20)) == 1


def test_symbol_runtime_reconstruction_is_symbol_local_and_fails_closed():
    active_btc = SymbolRuntime("BTC/USD")
    active_eth = SymbolRuntime("ETH/USD")
    active_btc.update_trade(price=65000.0, timestamp_ns=T0_NS)
    active_eth.update_trade(price=3500.0, timestamp_ns=T0_NS + 1)

    recovered_btc = SymbolRuntime("BTC/USD")
    recovered_eth = SymbolRuntime("ETH/USD")

    assert active_btc.symbol == "BTC/USD"
    assert active_eth.symbol == "ETH/USD"
    assert recovered_btc.symbol == "BTC/USD"
    assert recovered_eth.symbol == "ETH/USD"
    assert recovered_btc.is_ready() is False
    assert recovered_eth.is_ready() is False

    btc_status = recovered_btc.get_status()
    eth_status = recovered_eth.get_status()
    assert btc_status["has_order_book"] is False
    assert eth_status["has_order_book"] is False
    assert btc_status["last_price"] == 0.0
    assert eth_status["last_price"] == 0.0
    assert recovered_btc.last_liquidity_void_observed_vote is None
    assert recovered_eth.last_sector_rotation_observed_vote is None

    for runtime in (recovered_btc, recovered_eth):
        assert not hasattr(runtime, "execution_engine")
        assert not hasattr(runtime, "order_router")
        assert not hasattr(runtime, "paper_broker")
        assert not hasattr(runtime, "submit_order")


def test_recovery_helpers_preserve_authority_boundaries():
    recovery_sources = (
        inspect.getsource(ExposureManager.hydrate_reservations_from_ledger),
        inspect.getsource(PaperBroker.restore_from_snapshot),
        inspect.getsource(SymbolRuntime.get_status),
    )
    forbidden_tokens = (
        "ExecutionEngine",
        "OrderRouter",
        "broker_adapter",
        "live_broker",
        "NetEdgeGovernor",
        "TradeEfficiencyGovernor",
        "SovereignExecutionGuard",
        "StrategyAllocator",
        "submit_order(",
        "_execute_signal",
    )

    for source in recovery_sources:
        for token in forbidden_tokens:
            assert token not in source
