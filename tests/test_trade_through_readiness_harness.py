"""
Deterministic trade-through readiness harness.

This is a tests-only proof that a lawful synthetic candidate can traverse the
active paper money path without live mode, fake fills, or threshold changes.
"""

from __future__ import annotations

import json
import queue
import types
from decimal import Decimal
from unittest.mock import MagicMock

from app.commander import Commander
from app.execution.engine import ExecutionEngine
from app.execution.order_router import OrderRouter
from app.execution.paper_broker import PaperMarketContext, PriceLevel
from app.main_loop import MainLoop
from app.models import OrderFill, OrderRequest, StrategySignal
from app.models.enums import (
    AuthorityTier,
    BookIntegrity,
    ExecutionMode,
    OrderSide,
    OrderType,
    ReplayMode,
    SignalDirection,
    SleeveType,
    ToxicityLevel,
)
from app.models.market_data import Candle, OrderBookSnapshot
from app.risk.exposure_manager import ExposureManager
from app.risk.reservation_lifecycle_coordinator import ReservationLifecycleCoordinator
from app.state.state_store import StateStore
from app.strategies.moving_floor import (
    FloorEventType,
    FloorMarketTick,
    TopologicalMovingFloor,
)
from app.strategies.strategy_vote_adapters import adapt_sector_rotation_to_vote
from app.symbol_runtime import SymbolRuntime
from app.telemetry.event_store import TelemetryEventStore
from app.utils.time_utils import ReplayTimeContext, now_ns


T0_NS = 1_777_948_800_000_000_000
DECISION_UUID = "trade-through-readiness-decision-uuid"


def _build_candle(t0_ns: int) -> Candle:
    return Candle(
        symbol="ETH/USD",
        exchange_ts_ns=t0_ns,
        open=2495.0,
        high=2505.0,
        low=2492.5,
        close=2500.0,
        volume=125.0,
        timeframe="1m",
    )


def _build_book(t0_ns: int) -> OrderBookSnapshot:
    return OrderBookSnapshot(
        symbol="ETH/USD",
        exchange_ts_ns=t0_ns,
        bids=[(2499.50, 4.0), (2499.00, 8.0)],
        asks=[(2500.50, 4.0), (2501.00, 8.0)],
    )


def _build_strategy_signal(t0_ns: int) -> StrategySignal:
    return StrategySignal(
        strategy="sector_rotation",
        symbol="ETH/USD",
        side="buy",
        confidence=0.9,
        quantity=0.5,
        price=None,
        exchange_ts_ns=t0_ns,
        reason="trade_through_readiness_harness",
        metadata={},
        regime=None,
    )


def _build_vote(signal: StrategySignal, t0_ns: int):
    return adapt_sector_rotation_to_vote(
        signal,
        exchange_ts_ns=t0_ns,
        decision_uuid=DECISION_UUID,
    )


def _build_runtime(t0_ns: int):
    runtime = SymbolRuntime(symbol="ETH/USD")
    runtime.shadow_front_strategy = MagicMock()
    runtime.sector_rotation_strategy = MagicMock()
    runtime.toxicity_engine = MagicMock()
    runtime.sentiment_velocity_engine = MagicMock()
    runtime.update_candle(_build_candle(t0_ns))
    runtime.update_order_book(_build_book(t0_ns))
    signal = _build_strategy_signal(t0_ns)
    vote = _build_vote(signal, t0_ns)
    runtime.record_observed_signal("sector_rotation", signal)
    runtime.record_observed_vote("sector_rotation", vote)
    return runtime, signal, vote


def _build_loop(execution_engine) -> types.SimpleNamespace:
    loop = types.SimpleNamespace()
    loop.config = types.SimpleNamespace(broker_mode="paper")
    loop.commander = Commander()

    loop.strategy_router = MagicMock()
    loop.strategy_router.update_macro_state = MagicMock()
    loop.strategy_router.get_preferred_strategy = MagicMock(
        return_value=SleeveType.SHADOW_FRONT
    )
    loop.strategy_router.get_eligible_strategies = MagicMock(
        return_value=[SleeveType.SHADOW_FRONT, SleeveType.SECTOR_ROTATION]
    )

    loop.decision_compiler = MagicMock()
    loop.decision_compiler.compile = MagicMock(
        return_value=types.SimpleNamespace(
            decision_uuid=DECISION_UUID,
            decision_type="STRATEGY_VOTE",
        )
    )
    loop.execution_engine = execution_engine

    loop._build_truth_frame = MagicMock(return_value="truth-frame-stub")
    loop._update_shadow_front_overlays = MagicMock()
    loop._generate_signal_and_vote = MagicMock(return_value=(None, None))
    loop._generate_signal_and_vote_gamma_front = MagicMock(return_value=(None, None))
    loop._metrics = types.SimpleNamespace(
        orders_submitted=0,
        orders_rejected=0,
        compilation_cycles=0,
    )
    loop.insider_engine = MagicMock()

    loop._consume_observed_pair_sector_rotation = (
        MainLoop._consume_observed_pair_sector_rotation.__get__(loop, MainLoop)
    )
    loop._consume_observed_pair_liquidity_void = (
        MainLoop._consume_observed_pair_liquidity_void.__get__(loop, MainLoop)
    )
    loop._classify_shadow_front_decline = MainLoop._classify_shadow_front_decline.__get__(
        loop, MainLoop
    )
    loop._classify_sector_rotation_observed_pair = (
        MainLoop._classify_sector_rotation_observed_pair.__get__(loop, MainLoop)
    )
    loop._clear_stale_sector_rotation_observed_pair = (
        MainLoop._clear_stale_sector_rotation_observed_pair.__get__(loop, MainLoop)
    )
    return loop


def _risk_guard():
    risk_guard = MagicMock()
    risk_guard.can_trade.return_value = True
    risk_guard.is_vol_fuse_triggered.return_value = False
    risk_guard.register_recalibrate_callback = MagicMock()
    risk_guard.register_emergency_callback = MagicMock()
    risk_guard.register_zombie_callback = MagicMock()
    risk_guard.register_lag_callback = MagicMock()
    risk_guard.register_vol_fuse_callback = MagicMock()
    risk_guard.record_fees = MagicMock()
    return risk_guard


def _masking_layer():
    masked = MagicMock()
    masked.masked_size = Decimal("0.5")
    masking_layer = MagicMock()
    masking_layer.mask_order.return_value = masked
    return masking_layer


def _limit_order_from_signal(signal: StrategySignal) -> OrderRequest:
    return OrderRequest(
        id=f"{signal.strategy}_{signal.symbol}_{signal.exchange_ts_ns}_limit",
        symbol=signal.symbol,
        side=OrderSide.BUY,
        quantity=Decimal(str(signal.quantity)),
        order_type=OrderType.LIMIT,
        limit_price=Decimal("2501.00"),
        strategy=SleeveType.SECTOR_ROTATION,
        confidence=signal.confidence,
        decision_uuid=DECISION_UUID,
        exchange_ts_ns=signal.exchange_ts_ns,
        receive_ts_ns=signal.exchange_ts_ns,
        metadata={"harness": "trade_through_readiness_reservation"},
    )


def test_known_good_candidate_reaches_real_paper_fill_and_fill_telemetry(tmp_path):
    telemetry_store = TelemetryEventStore(str(tmp_path / "trade-through-telemetry.db"))
    router = OrderRouter(paper_mode=True, telemetry_store=telemetry_store)
    router.update_market_mid("ETH/USD", 2500.0, T0_NS)

    risk_guard = _risk_guard()
    masking_layer = _masking_layer()
    engine = ExecutionEngine(
        commander=Commander(),
        risk_guard=risk_guard,
        order_router=router,
        masking_layer=masking_layer,
    )
    engine._state.is_running = True
    engine._state.last_regime = "neutral"

    with ReplayTimeContext(T0_NS):
        runtime, signal, vote = _build_runtime(T0_NS)
        loop = _build_loop(engine)

        MainLoop._dispatch_fusion.__get__(loop, MainLoop)(
            "ETH/USD",
            runtime,
            fusion=types.SimpleNamespace(
                exchange_ts_ns=T0_NS,
                attack_mode=False,
                preferred_sleeve=SleeveType.SHADOW_FRONT,
                sector_rotation_eligible=True,
                shadow_front_eligible=True,
            ),
            exchange_ts_ns=T0_NS,
        )

        loop.decision_compiler.compile.assert_called_once()
        assert loop.decision_compiler.compile.call_args.kwargs["strategy_votes"] == [vote]
        assert signal.metadata["decision_uuid"] == DECISION_UUID
        assert loop._metrics.orders_submitted == 1

        queued = engine._execution_queue.get_nowait()
        assert queued.signal is signal
        assert queued.decision_uuid == DECISION_UUID
        assert queued.is_attack is False

        engine._execute_signal(queued)

    with engine._lock:
        fills = list(engine._state.filled_orders)
    assert len(fills) == 1
    fill = fills[0]
    assert isinstance(fill, OrderFill)
    assert fill.order_id == f"sector_rotation_ETH/USD_{T0_NS}"
    assert fill.symbol == "ETH/USD"
    assert fill.side == OrderSide.BUY
    assert fill.quantity == Decimal("0.5")
    assert fill.price > Decimal("0")
    assert fill.fee >= Decimal("0")
    assert fill.fee_currency == "USD"
    assert fill.exchange_ts_ns >= T0_NS
    assert fill.receive_ts_ns >= T0_NS

    risk_guard.record_fees.assert_called_once_with(fill.fee)
    masking_layer.mask_order.assert_called_once_with(0.5)
    assert router._paper_broker is not None
    assert any(
        report.client_id == fill.order_id and report.filled_quantity == Decimal("0.5")
        for report in router._paper_broker.execution_reports
    )

    events = telemetry_store.get_events_by_type("fill", limit=10)
    assert events, "real FillRecorder telemetry event should be persisted"
    fill_event = next(
        event for event in events if event["decision_uuid"] == DECISION_UUID
    )
    payload = json.loads(fill_event["payload_json"])
    assert payload["decision_uuid"] == DECISION_UUID
    assert payload["order_intent_id"] == fill.order_id
    assert payload["execution_event_id"] == fill.order_id
    assert payload["symbol"] == "ETH/USD"
    assert payload["side"] == "buy"
    assert isinstance(payload["quantity"], str)
    assert Decimal(payload["quantity"]) == Decimal("0.5")
    assert Decimal(payload["price"]) == fill.price
    assert Decimal(payload["fee"]) == fill.fee
    assert payload["fee_currency"] == "USD"
    assert payload["venue_fill_id"] == fill.order_id
    assert int(payload["exchange_ts_ns"]) == fill.exchange_ts_ns
    assert int(fill_event["receive_ts_ns"]) == fill.receive_ts_ns
    assert payload["strategy"] == "sector_rotation"
    assert payload["sleeve"] == "sector_rotation"
    assert payload["paper_mode"] is True
    assert Decimal(payload["requested_qty"]) == Decimal("0.5")

    context = payload["order_lifecycle_replay_context"]
    assert context["client_order_id"] == fill.order_id
    assert context["decision_uuid"] == DECISION_UUID
    assert Decimal(context["original_qty"]) == Decimal("0.5")
    assert Decimal(context["cumulative_filled_qty"]) == Decimal("0.5")
    assert context["remaining_qty"] == "0"
    assert context["avg_fill_price"] == payload["price"]
    assert context["cumulative_fee"] == payload["fee"]
    assert context["terminal_state"] == "filled"
    assert context["status_source"] == "order_router.fill_observation"
    assert context["id_mapping_source"] == "paper_broker.execution_report"


def test_limit_paper_path_opens_fills_and_releases_reservation(tmp_path):
    state_store = StateStore(str(tmp_path / "trade-through-reservations.db"))
    exposure_manager = ExposureManager(initial_equity=Decimal("20000"))
    coordinator = ReservationLifecycleCoordinator(
        exposure_manager=exposure_manager,
        state_store=state_store,
    )
    router = OrderRouter(
        paper_mode=True,
        state_store=state_store,
        reservation_lifecycle_coordinator=coordinator,
        reservation_lifecycle_enabled=True,
    )

    with ReplayTimeContext(T0_NS):
        _, signal, _ = _build_runtime(T0_NS)
        order = _limit_order_from_signal(signal)

        assert router.submit_order(order) is None
        ack_result = router._reservation_lifecycle_ack_open_results[-1]
        assert ack_result["applied"] is True
        assert ack_result["broker_command_performed"] is False
        assert ack_result["telemetry_authority_used"] is False

        ledger_after_ack = state_store.get_reservation_ledger(order.id)
        assert ledger_after_ack is not None
        assert ledger_after_ack["is_active"] is True
        assert ledger_after_ack["is_terminal"] is False
        assert Decimal(ledger_after_ack["price_basis"]) == Decimal("2501.00")

        paper_order = router._paper_broker.open_orders[order.id]
        first_ts_ns = paper_order.eligible_at_ns + 2
        first_ctx = PaperMarketContext(
            symbol=order.symbol,
            timestamp_ns=first_ts_ns,
            mid_price=Decimal("2500.50"),
            best_bid=Decimal("2500.00"),
            best_ask=Decimal("2500.50"),
            ask_levels=(
                PriceLevel(price=Decimal("2500.50"), quantity=Decimal("0.25")),
            ),
        )
        first_reports = router._paper_broker.process_matching_detailed(
            current_ts_ns=first_ts_ns,
            market_by_symbol={order.symbol: first_ctx},
        )
        assert any(report.status.value == "PARTIAL_FILL" for report in first_reports)
        router._sync_paper_reports()

        partial_result = router._reservation_lifecycle_partial_fill_results[-1]
        assert partial_result["applied"] is True
        progress = state_store.list_reservation_fill_progress(order.id)
        assert len(progress) == 1
        assert progress[0]["cumulative_filled_qty"] == "0.25"

        paper_order = router._paper_broker.open_orders[order.id]
        second_ts_ns = paper_order.eligible_at_ns + 4
        second_ctx = PaperMarketContext(
            symbol=order.symbol,
            timestamp_ns=second_ts_ns,
            mid_price=Decimal("2500.50"),
            best_bid=Decimal("2500.00"),
            best_ask=Decimal("2500.50"),
            ask_levels=(
                PriceLevel(price=Decimal("2500.50"), quantity=Decimal("0.25")),
            ),
        )
        second_reports = router._paper_broker.process_matching_detailed(
            current_ts_ns=second_ts_ns,
            market_by_symbol={order.symbol: second_ctx},
        )
        assert any(report.status.value == "FULLY_FILLED" for report in second_reports)
        router._sync_paper_reports()

        full_result = router._reservation_lifecycle_full_fill_results[-1]
        assert full_result["applied"] is True
        assert exposure_manager.reservations_for() == []

        tombstone = state_store.get_reservation_release_tombstone(
            reservation_id=order.id,
        )
        assert tombstone is not None
        assert tombstone["terminal_status"] == "filled"
        assert tombstone["terminal_source"] == "paper_broker.execution_report"
        assert tombstone["release_applied"] is True

        duplicate_release = router._record_reservation_full_fill(
            order,
            release_idempotency_key=tombstone["release_idempotency_key"],
            cumulative_filled_qty=order.quantity,
            fill_delta_qty=Decimal("0.25"),
            status_source="paper_broker.execution_report",
            terminal_source="paper_broker.execution_report",
            source_event_id=tombstone["source_event_id"],
        )
        assert duplicate_release["idempotent"] is True
        assert len(state_store.list_reservation_fill_progress(order.id)) == 1


def test_moving_floor_recommendation_is_protective_only_and_does_not_route():
    router = MagicMock()
    engine = MagicMock()
    floor = TopologicalMovingFloor(base_buffer=Decimal("0.0200"))

    tick_0 = FloorMarketTick(
        symbol="ETH/USD",
        price=Decimal("100"),
        timestamp_ns=T0_NS,
        bid_volume=Decimal("10"),
        ask_volume=Decimal("10"),
        book_integrity=BookIntegrity.HEALTHY,
        toxicity_level=ToxicityLevel.BENIGN,
        replay_mode=ReplayMode.REPLAY,
        execution_mode=ExecutionMode.REPLAY,
    )
    event_0, assessment_0, recommendation_0 = floor.process_tick(tick_0)
    assert event_0 is not None
    assert event_0.event_type == FloorEventType.INITIALIZED
    assert assessment_0 is not None
    assert recommendation_0 is None

    tick_1 = FloorMarketTick(
        symbol="ETH/USD",
        price=Decimal("105"),
        timestamp_ns=T0_NS + 1_000_000_000,
        bid_volume=Decimal("10"),
        ask_volume=Decimal("10"),
        book_integrity=BookIntegrity.HEALTHY,
        toxicity_level=ToxicityLevel.BENIGN,
        replay_mode=ReplayMode.REPLAY,
        execution_mode=ExecutionMode.REPLAY,
    )
    event_1, _, recommendation_1 = floor.process_tick(tick_1)
    assert event_1 is not None
    assert event_1.event_type == FloorEventType.RATCHET_UP
    assert recommendation_1 is None

    tick_2 = FloorMarketTick(
        symbol="ETH/USD",
        price=Decimal("102"),
        timestamp_ns=T0_NS + 2_000_000_000,
        bid_volume=Decimal("5"),
        ask_volume=Decimal("15"),
        book_integrity=BookIntegrity.HEALTHY,
        toxicity_level=ToxicityLevel.BENIGN,
        replay_mode=ReplayMode.REPLAY,
        execution_mode=ExecutionMode.REPLAY,
    )
    event_2, assessment_2, recommendation_2 = floor.process_tick(tick_2)

    assert event_2 is not None
    assert event_2.event_type == FloorEventType.TOPOLOGICAL_BREACH
    assert assessment_2 is not None
    assert assessment_2.signal_direction == SignalDirection.SHORT
    assert assessment_2.authority_tier == AuthorityTier.SOFT_BLOCK
    assert recommendation_2 is not None
    assert recommendation_2.signal_direction == SignalDirection.SHORT
    assert recommendation_2.event_type == FloorEventType.TOPOLOGICAL_BREACH
    assert recommendation_2.authority_tier == AuthorityTier.SOFT_BLOCK
    assert recommendation_2.source_module == "app.strategies.moving_floor"
    assert "price_crossed_topological_support" in recommendation_2.rationale

    router.submit_order.assert_not_called()
    engine.submit_signal.assert_not_called()
    assert not hasattr(floor, "order_router")
    assert not hasattr(floor, "execution_engine")


def test_no_trade_when_same_clock_pair_is_missing():
    router = OrderRouter(paper_mode=True)
    risk_guard = _risk_guard()
    engine = ExecutionEngine(
        commander=Commander(),
        risk_guard=risk_guard,
        order_router=router,
        masking_layer=_masking_layer(),
    )
    engine._state.is_running = True

    with ReplayTimeContext(T0_NS):
        runtime = SymbolRuntime(symbol="ETH/USD")
        runtime.shadow_front_strategy = MagicMock()
        runtime.sector_rotation_strategy = MagicMock()
        runtime.update_candle(_build_candle(T0_NS))
        runtime.update_order_book(_build_book(T0_NS))

        loop = _build_loop(engine)
        MainLoop._dispatch_fusion.__get__(loop, MainLoop)(
            "ETH/USD",
            runtime,
            fusion=types.SimpleNamespace(
                exchange_ts_ns=T0_NS,
                attack_mode=False,
                preferred_sleeve=SleeveType.SHADOW_FRONT,
                sector_rotation_eligible=True,
                shadow_front_eligible=True,
            ),
            exchange_ts_ns=T0_NS,
        )

    loop.decision_compiler.compile.assert_not_called()
    assert engine._execution_queue.empty()
    try:
        engine._execution_queue.get_nowait()
    except queue.Empty:
        pass
    assert router._paper_broker is not None
    assert router._paper_broker.execution_reports == []
