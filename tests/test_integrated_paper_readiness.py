from __future__ import annotations

import inspect
import json
import types
from dataclasses import dataclass, field
from decimal import Decimal
from unittest.mock import MagicMock

from app.brain.recalibrator import Recalibrator
from app.brain.signal_fusion import SignalFusion
from app.brain.toxicity_engine import ToxicityAlert, ToxicityRegime
from app.brain.topological_engine import TopologicalSignal
from app.commander import Commander
from app.execution.engine import ExecutionEngine
from app.execution.order_router import OrderRouter
from app.execution.paper_broker import PaperMarketContext, PriceLevel
from app.models import OrderFill, OrderRequest, StrategySignal
from app.models.enums import (
    BookIntegrity,
    ExecutionMode,
    OrderSide,
    OrderType,
    ReplayMode,
    SignalDirection,
    SleeveType,
    ToxicityLevel,
)
from app.models.instrument_profile import AssetClass, InstrumentProfile, InstrumentType
from app.models.market_data import Candle, OrderBookSnapshot
from app.portfolio.opportunity_ranking import OpportunityRanker
from app.risk.exposure_manager import ExposureManager
from app.risk.reservation_lifecycle_coordinator import ReservationLifecycleCoordinator
from app.state.state_store import StateStore
from app.strategies.council_metadata import (
    BIAS_SHORT,
    FEED_REAL,
    MODULE_HEDGING_FLOW,
    MODULE_MOVING_FLOOR,
    MODULE_RECALIBRATOR,
    ROLE_HEDGE,
    ROLE_OBSERVE_ONLY,
    ROLE_PROTECTIVE_EXIT,
    SOURCE_HEDGE_RECOMMENDATION,
    SOURCE_RECALIBRATION_STATE,
    build_council_metadata,
)
from app.strategies.hedging_flow import (
    HedgeMarketContext,
    HedgingFlow,
    PortfolioExposureSnapshot,
)
from app.strategies.moving_floor import FloorMarketTick, TopologicalMovingFloor
from app.strategies.strategy_vote_adapters import (
    adapt_moving_floor_to_vote,
    adapt_sector_rotation_to_vote,
)
from app.symbol_runtime import SymbolRuntime
from app.telemetry.event_store import TelemetryEventStore
from app.utils.time_utils import ReplayTimeContext


T0_NS = 1_777_948_800_000_000_000
DECISION_UUID = "integrated-paper-readiness-decision"


@dataclass
class ReadinessCouncilHarness:
    consumed: list[dict] = field(default_factory=list)
    execution_state: dict = field(
        default_factory=lambda: {"submitted_orders": 0, "submitted_signals": 0}
    )

    def consume(self, *, module: str, output: object, metadata: dict) -> None:
        assert metadata["fresh_entry_authorized"] is False
        assert metadata["execution_candidate"] is False
        assert metadata["contribution_role"] in {
            ROLE_PROTECTIVE_EXIT,
            ROLE_HEDGE,
            ROLE_OBSERVE_ONLY,
        }
        assert metadata.get("requires_existing_position") is True or metadata.get(
            "requires_existing_exposure"
        ) is True
        self.consumed.append({"module": module, "output": output, "metadata": metadata})


def _book(t0_ns: int) -> OrderBookSnapshot:
    return OrderBookSnapshot(
        symbol="ETH/USD",
        exchange_ts_ns=t0_ns,
        bids=[(2499.50, 4.0), (2499.00, 8.0)],
        asks=[(2500.50, 4.0), (2501.00, 8.0)],
    )


def _candle(t0_ns: int) -> Candle:
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


def _sector_signal(t0_ns: int) -> StrategySignal:
    return StrategySignal(
        strategy="sector_rotation",
        symbol="ETH/USD",
        side="buy",
        confidence=0.9,
        quantity=0.5,
        price=None,
        exchange_ts_ns=t0_ns,
        reason="integrated_paper_readiness",
        metadata={},
    )


def _runtime_with_entry_vote(t0_ns: int):
    runtime = SymbolRuntime(symbol="ETH/USD")
    runtime.shadow_front_strategy = MagicMock()
    runtime.sector_rotation_strategy = MagicMock()
    runtime.toxicity_engine = MagicMock()
    runtime.sentiment_velocity_engine = MagicMock()
    runtime.update_candle(_candle(t0_ns))
    runtime.update_order_book(_book(t0_ns))

    signal = _sector_signal(t0_ns)
    vote = adapt_sector_rotation_to_vote(
        signal,
        exchange_ts_ns=t0_ns,
        decision_uuid=DECISION_UUID,
    )
    runtime.record_observed_signal("sector_rotation", signal)
    runtime.record_observed_vote("sector_rotation", vote)
    return runtime, signal, vote


def _loop_stub(execution_engine: ExecutionEngine) -> types.SimpleNamespace:
    loop = types.SimpleNamespace()
    loop.config = types.SimpleNamespace(broker_mode="paper")
    loop.commander = Commander()
    loop.strategy_router = MagicMock()
    loop.strategy_router.update_macro_state = MagicMock()
    loop.strategy_router.get_preferred_strategy = MagicMock(return_value=SleeveType.SHADOW_FRONT)
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

    from app.main_loop import MainLoop

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
    loop._dispatch_fusion = MainLoop._dispatch_fusion.__get__(loop, MainLoop)
    return loop


def _risk_guard():
    guard = MagicMock()
    guard.can_trade.return_value = True
    guard.is_vol_fuse_triggered.return_value = False
    guard.register_recalibrate_callback = MagicMock()
    guard.register_emergency_callback = MagicMock()
    guard.register_zombie_callback = MagicMock()
    guard.register_lag_callback = MagicMock()
    guard.register_vol_fuse_callback = MagicMock()
    guard.record_fees = MagicMock()
    return guard


def _masking_layer():
    masked = MagicMock()
    masked.masked_size = Decimal("0.5")
    layer = MagicMock()
    layer.mask_order.return_value = masked
    return layer


def _toxicity(ts_ns: int) -> ToxicityAlert:
    return ToxicityAlert(
        toxicity_score=0.20,
        regime=ToxicityRegime.NORMAL,
        direction_bias="neutral",
        vpin_proxy=0.10,
        burst_pressure=0.10,
        instability_score=0.10,
        volume_anomaly=0.0,
        persistence=0.0,
        confidence=0.80,
        timestamp_ns=ts_ns,
        reason="integrated_paper_readiness",
    )


def _entry_ranking_metadata() -> dict:
    instrument = InstrumentProfile(
        instrument_id="eth-usd",
        symbol="ETH/USD",
        canonical_symbol="ETH/USD",
        venue_symbol="ETHUSD",
        display_symbol="ETH/USD",
        root_symbol="ETH",
        asset_class=AssetClass.CRYPTO,
        instrument_type=InstrumentType.SPOT,
        venue="KRAKEN",
        primary_exchange="KRAKEN",
        currency="USD",
        quote_currency="USD",
        base_currency="ETH",
        country="US",
        region="North America",
        timezone="UTC",
        enabled=True,
        paper_tradable=True,
        live_tradable=False,
        fractional_allowed=True,
    )
    report = OpportunityRanker().rank(
        candidates=[("eth-usd", "sector_rotation", Decimal("35.0"), Decimal("0.80"), Decimal("3000"))],
        instruments={"eth-usd": instrument},
        existing_exposures={},
        total_equity=Decimal("20000"),
        available_capital=Decimal("10000"),
        timestamp_ns=T0_NS,
    )
    assert report.total_ranked == 1
    assert report.top_opportunity == "ETH/USD"
    return {
        "source_module": "opportunity_ranking",
        "contribution_role": "passive_entry_ranking",
        "fresh_entry_authorized": False,
        "execution_candidate": False,
        "ranking_authority": False,
        "allocation_authority": False,
        "execution_authority": False,
        "top_opportunity": report.top_opportunity,
    }


def _protective_evidence() -> tuple[ReadinessCouncilHarness, dict]:
    council = ReadinessCouncilHarness()
    initial_execution_state = dict(council.execution_state)
    floor = TopologicalMovingFloor(base_buffer=Decimal("0.0200"))
    for price, ts, bid_volume, ask_volume in (
        (Decimal("100"), T0_NS, Decimal("10"), Decimal("10")),
        (Decimal("105"), T0_NS + 1_000_000_000, Decimal("10"), Decimal("10")),
        (Decimal("102"), T0_NS + 2_000_000_000, Decimal("5"), Decimal("15")),
    ):
        event, assessment, recommendation = floor.process_tick(
            FloorMarketTick(
                symbol="ETH/USD",
                price=price,
                timestamp_ns=ts,
                bid_volume=bid_volume,
                ask_volume=ask_volume,
                book_integrity=BookIntegrity.HEALTHY,
                toxicity_level=ToxicityLevel.BENIGN,
                replay_mode=ReplayMode.REPLAY,
                execution_mode=ExecutionMode.REPLAY,
            )
        )
    assert recommendation is not None
    assert assessment.signal_direction == SignalDirection.SHORT
    moving_floor_vote = adapt_moving_floor_to_vote(
        recommendation,
        exchange_ts_ns=T0_NS + 2_000_000_000,
        decision_uuid="integrated-readiness-moving-floor",
    )
    council.consume(
        module=MODULE_MOVING_FLOOR,
        output=moving_floor_vote,
        metadata=moving_floor_vote.metadata,
    )

    hedge = HedgingFlow()
    exposure = PortfolioExposureSnapshot(
        net_delta=Decimal("20000"),
        total_equity=Decimal("100000"),
        target_symbol="ETH/USD",
        sleeve="portfolio_delta",
    )
    market = HedgeMarketContext(
        symbol="ETH/USD",
        price=Decimal("2500"),
        book_integrity=BookIntegrity.HEALTHY,
        toxicity_level=ToxicityLevel.BENIGN,
        replay_mode=ReplayMode.REPLAY,
        execution_mode=ExecutionMode.REPLAY,
    )
    hedge_recommendation = hedge.recommend(
        assessment=hedge.assess(exposure=exposure, market=market),
        market=market,
    )
    assert hedge_recommendation is not None
    hedge_metadata = build_council_metadata(
        source_module=MODULE_HEDGING_FLOW,
        source_strategy_id="hedging_flow",
        source_output_type=SOURCE_HEDGE_RECOMMENDATION,
        adapter_name="integrated_paper_readiness_harness",
        contribution_role=ROLE_HEDGE,
        fresh_entry_authorized=False,
        protective_only=True,
        requires_existing_position=False,
        execution_candidate=False,
        directional_bias=BIAS_SHORT,
        feed_status=FEED_REAL,
        raw_confidence=1.0,
        normalized_confidence=1.0,
        reason="portfolio_delta_protection",
        symbol=hedge_recommendation.symbol,
        requires_existing_exposure=True,
        trade_intent=hedge_recommendation.trade_intent.value,
        is_hedge=hedge_recommendation.is_hedge,
    )
    council.consume(module=MODULE_HEDGING_FLOW, output=hedge_recommendation, metadata=hedge_metadata)

    recalibrator = Recalibrator()
    regime = recalibrator.evaluate_regime(
        price_drop_pct=0.03,
        tpe_signal=TopologicalSignal(
            coherence_score=0.20,
            betti_0=4,
            betti_1=1,
            persistence_score=0.30,
            super_void_detected=True,
            structural_collapse=True,
            confidence=0.90,
            exchange_ts_ns=T0_NS,
            reason="super_void_with_drawdown",
        ),
        drop_duration_sec=60.0,
    )
    recalibrator.start_recalibration(reason=regime, duration_seconds=3600.0)
    recalibration_metadata = build_council_metadata(
        source_module=MODULE_RECALIBRATOR,
        source_strategy_id="recalibrator",
        source_output_type=SOURCE_RECALIBRATION_STATE,
        adapter_name="integrated_paper_readiness_harness",
        contribution_role=ROLE_OBSERVE_ONLY,
        fresh_entry_authorized=False,
        protective_only=True,
        requires_existing_position=True,
        execution_candidate=False,
        directional_bias=BIAS_SHORT,
        feed_status=FEED_REAL,
        raw_confidence=1.0,
        normalized_confidence=1.0,
        reason=regime,
        symbol="ETH/USD",
        requires_existing_exposure=True,
        recalibration_active=recalibrator.get_status()["is_in_recalibration"],
    )
    council.consume(
        module=MODULE_RECALIBRATOR,
        output=recalibrator.get_status(),
        metadata=recalibration_metadata,
    )

    assert council.execution_state == initial_execution_state
    return council, moving_floor_vote.metadata


def _limit_order(signal: StrategySignal) -> OrderRequest:
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
        metadata={"harness": "integrated_paper_readiness_reservation"},
    )


def test_integrated_paper_readiness_coexists_without_new_authority_or_recovery_automation(tmp_path):
    ranking_metadata = _entry_ranking_metadata()
    assert ranking_metadata["fresh_entry_authorized"] is False
    assert ranking_metadata["execution_authority"] is False

    fusion = SignalFusion(
        config=types.SimpleNamespace(
            strategies=types.SimpleNamespace(sector_rotation_ranging_eligible=False),
            symbol="ETH/USD",
        )
    )
    fusion.update_physical({"health_score": 0.80}, T0_NS)
    fusion.update_toxicity(_toxicity(T0_NS), T0_NS)
    fusion_decision = fusion.fuse(T0_NS)
    fusion_telemetry = fusion.get_fusion_telemetry()
    assert fusion_decision.has_valid_sleeve
    assert set(fusion_telemetry["missing_inputs"]) == {
        "whale_flow",
        "shans_curve",
        "entropy",
        "insider",
        "regime",
    }
    assert "veto_reason" not in fusion_telemetry

    missing_physical = SignalFusion(config=fusion.config)
    missing_physical.update_toxicity(_toxicity(T0_NS), T0_NS)
    veto = missing_physical.fuse(T0_NS)
    assert veto.preferred_sleeve is None
    assert "Missing critical signal [physical]" in veto.reason

    council, protective_metadata = _protective_evidence()
    assert [item["module"] for item in council.consumed] == [
        MODULE_MOVING_FLOOR,
        MODULE_HEDGING_FLOW,
        MODULE_RECALIBRATOR,
    ]
    assert protective_metadata["fresh_entry_authorized"] is False
    assert protective_metadata["execution_candidate"] is False

    telemetry_store = TelemetryEventStore(str(tmp_path / "integrated-telemetry.db"))
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
        runtime, signal, vote = _runtime_with_entry_vote(T0_NS)
        loop = _loop_stub(engine)
        loop._dispatch_fusion(
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
        queued = engine._execution_queue.get_nowait()
        assert queued.signal is signal
        assert queued.decision_uuid == DECISION_UUID
        engine._execute_signal(queued)

    with engine._lock:
        fills = list(engine._state.filled_orders)
    assert len(fills) == 1
    fill = fills[0]
    assert isinstance(fill, OrderFill)
    assert fill.symbol == "ETH/USD"
    assert fill.side == OrderSide.BUY
    assert fill.quantity == Decimal("0.5")
    assert fill.price > Decimal("0")
    assert fill.fee >= Decimal("0")
    assert fill.fee_currency == "USD"
    risk_guard.record_fees.assert_called_once_with(fill.fee)
    masking_layer.mask_order.assert_called_once_with(0.5)

    events = telemetry_store.get_events_by_type("fill", limit=10)
    assert len(events) == 1
    payload = json.loads(events[0]["payload_json"])
    assert payload["decision_uuid"] == DECISION_UUID
    assert payload["order_intent_id"] == fill.order_id
    assert payload["execution_event_id"] == fill.order_id
    assert Decimal(payload["requested_qty"]) == Decimal("0.5")
    assert Decimal(payload["quantity"]) == fill.quantity
    assert Decimal(payload["price"]) == fill.price
    assert Decimal(payload["fee"]) == fill.fee
    assert payload["fee_currency"] == "USD"
    assert payload["strategy"] == "sector_rotation"
    assert payload["sleeve"] == "sector_rotation"
    assert payload["paper_mode"] is True
    lifecycle = payload["order_lifecycle_replay_context"]
    assert Decimal(lifecycle["remaining_qty"]) == Decimal("0")
    assert Decimal(lifecycle["avg_fill_price"]) == fill.price
    assert Decimal(lifecycle["cumulative_fee"]) == fill.fee
    assert lifecycle["terminal_state"] == "filled"
    for invented_field in (
        "slippage_bps",
        "expected_fill_price",
        "arrival_price",
        "net_pnl",
        "net_edge",
        "profitability",
    ):
        assert invented_field not in payload
        assert invented_field not in lifecycle

    snapshot = router._paper_broker.get_snapshot(
        current_prices={"ETH/USD": Decimal("2500.00")},
        ts_ns=T0_NS + 1,
    )
    restored_broker = type(router._paper_broker)(
        fee_model=router._paper_broker.fees,
        slippage_model=router._paper_broker.slippage,
        latency_model=router._paper_broker.latency,
        config=router._paper_broker.config,
    )
    restored_broker.restore_from_snapshot(snapshot)
    assert restored_broker.validate_invariants()["valid"] is True
    assert restored_broker.open_orders == {}

    recovered_runtime = SymbolRuntime("ETH/USD")
    assert recovered_runtime.is_ready() is False
    assert recovered_runtime.get_status()["has_order_book"] is False
    assert not hasattr(recovered_runtime, "execution_engine")
    assert not hasattr(recovered_runtime, "order_router")
    assert not hasattr(recovered_runtime, "submit_order")


def test_integrated_reservation_lifecycle_remains_paper_scoped_and_idempotent(tmp_path):
    state_store = StateStore(str(tmp_path / "integrated-reservations.db"))
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
    _, signal, _ = _runtime_with_entry_vote(T0_NS)
    order = _limit_order(signal)

    with ReplayTimeContext(T0_NS):
        assert router.submit_order(order) is None
        ack_result = router._reservation_lifecycle_ack_open_results[-1]
        assert ack_result["applied"] is True
        assert ack_result["broker_command_performed"] is False
        assert ack_result["telemetry_authority_used"] is False

        ledger_after_ack = state_store.get_reservation_ledger(order.id)
        assert ledger_after_ack is not None
        assert ledger_after_ack["is_active"] is True
        assert ledger_after_ack["is_terminal"] is False

        paper_order = router._paper_broker.open_orders[order.id]
        first_ts_ns = paper_order.eligible_at_ns + 2
        first_reports = router._paper_broker.process_matching_detailed(
            current_ts_ns=first_ts_ns,
            market_by_symbol={
                order.symbol: PaperMarketContext(
                    symbol=order.symbol,
                    timestamp_ns=first_ts_ns,
                    mid_price=Decimal("2500.50"),
                    best_bid=Decimal("2500.00"),
                    best_ask=Decimal("2500.50"),
                    ask_levels=(PriceLevel(price=Decimal("2500.50"), quantity=Decimal("0.25")),),
                )
            },
        )
        assert any(report.status.value == "PARTIAL_FILL" for report in first_reports)
        router._sync_paper_reports()
        assert router._reservation_lifecycle_partial_fill_results[-1]["applied"] is True
        progress = state_store.list_reservation_fill_progress(order.id)
        assert len(progress) == 1
        assert progress[0]["cumulative_filled_qty"] == "0.25"

        paper_order = router._paper_broker.open_orders[order.id]
        second_ts_ns = paper_order.eligible_at_ns + 4
        second_reports = router._paper_broker.process_matching_detailed(
            current_ts_ns=second_ts_ns,
            market_by_symbol={
                order.symbol: PaperMarketContext(
                    symbol=order.symbol,
                    timestamp_ns=second_ts_ns,
                    mid_price=Decimal("2500.50"),
                    best_bid=Decimal("2500.00"),
                    best_ask=Decimal("2500.50"),
                    ask_levels=(PriceLevel(price=Decimal("2500.50"), quantity=Decimal("0.25")),),
                )
            },
        )
        assert any(report.status.value == "FULLY_FILLED" for report in second_reports)
        router._sync_paper_reports()

    full_result = router._reservation_lifecycle_full_fill_results[-1]
    assert full_result["applied"] is True
    assert exposure_manager.reservations_for() == []
    tombstone = state_store.get_reservation_release_tombstone(reservation_id=order.id)
    assert tombstone is not None
    assert tombstone["terminal_status"] == "filled"
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


def test_integrated_readiness_surfaces_do_not_activate_dormant_or_live_authority():
    from app.execution.paper_broker import PaperBroker
    from app.portfolio.opportunity_ranking import OpportunityRanker
    from app.strategies.adaptive_dc import AdaptiveDC
    from app.strategies.gamma_front import GammaFrontStrategy

    forbidden_for_contributors = (
        "ExecutionEngine",
        "OrderRouter",
        "PaperBroker",
        "broker_adapter",
        "live_broker",
        "submit_order",
        "_execute_signal",
        "NetEdgeGovernor",
        "TradeEfficiencyGovernor",
        "SovereignExecutionGuard",
        "StrategyAllocator",
        "SovereignGovernor",
    )
    contributor_surfaces = (
        OpportunityRanker,
        GammaFrontStrategy,
        AdaptiveDC,
        TopologicalMovingFloor,
        HedgingFlow,
        Recalibrator,
        adapt_sector_rotation_to_vote,
        adapt_moving_floor_to_vote,
        SignalFusion,
    )
    for surface in contributor_surfaces:
        source = inspect.getsource(surface)
        for token in forbidden_for_contributors:
            assert token not in source

    recovery_sources = (
        inspect.getsource(ExposureManager.hydrate_reservations_from_ledger),
        inspect.getsource(PaperBroker.restore_from_snapshot),
        inspect.getsource(SymbolRuntime.get_status),
    )
    for source in recovery_sources:
        assert "HydrationManager" not in source
        assert "TruthKernel" not in source
        assert "InvariantChecker" not in source
        assert "NetEdgeGovernor" not in source
        assert "TradeEfficiencyGovernor" not in source
        assert "SovereignExecutionGuard" not in source
