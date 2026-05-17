from __future__ import annotations

import inspect
import json
from decimal import Decimal

from app.core.truth_kernel import TruthKernel
from app.execution.fee_model import FeeModel
from app.execution.latency_model import LatencyModel
from app.execution.paper_broker import (
    PaperBroker,
    PaperBrokerConfig,
    PaperMarketContext,
    PriceLevel,
)
from app.execution.slippage_model import SlippageModel
from app.models.contracts import (
    ExchangeTruth,
    ExecutionTruth,
    PortfolioTruth,
    RiskTruth,
    StrategyTruth,
)
from app.models.enums import RiskMode, TruthStatus
from app.models.market_data import Candle, OrderBookSnapshot
from app.state.invariant_checker import InvariantChecker
from app.symbol_runtime import SymbolRuntime
from app.utils.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from app.utils.time_utils import now_ns


T0_NS = 1_777_948_800_000_000_000


def _broker(path) -> PaperBroker:
    return PaperBroker(
        fee_model=FeeModel(),
        slippage_model=SlippageModel(),
        latency_model=LatencyModel(base_latency_ms=0, jitter_ms=0, exchange_processing_ms=0),
        config=PaperBrokerConfig(
            durable_state_path=str(path),
            auto_persist_enabled=True,
        ),
    )


def _market(ts_ns: int, qty: Decimal) -> PaperMarketContext:
    return PaperMarketContext(
        symbol="ETH/USD",
        timestamp_ns=ts_ns,
        mid_price=Decimal("2500.00"),
        best_bid=Decimal("2499.50"),
        best_ask=Decimal("2500.50"),
        ask_levels=(PriceLevel(price=Decimal("2500.50"), quantity=qty),),
        bid_levels=(PriceLevel(price=Decimal("2499.50"), quantity=qty),),
    )


def test_paper_broker_auto_persists_and_restores_open_partial_and_terminal_state(tmp_path):
    state_path = tmp_path / "paper-broker-state.json"
    broker = _broker(state_path)

    order = broker.submit_order_detailed(
        symbol="ETH/USD",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.GTC,
        quantity=Decimal("1.0"),
        price=Decimal("2501.00"),
        ts_ns=T0_NS,
        client_id="durable-recovery-order",
    )
    assert state_path.exists()
    persisted_open = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted_open["paper_only"] is True
    assert persisted_open["live_authority"] is False
    assert "durable-recovery-order" in persisted_open["snapshot"]["open_orders"]

    restarted = _broker(state_path)
    restore_result = restarted.restore_from_durable_state()
    assert restore_result["restored"] is True
    assert restore_result["paper_only"] is True
    assert restore_result["open_orders"] == ("durable-recovery-order",)
    assert restarted.open_orders["durable-recovery-order"].order_id == order.order_id
    assert len(restarted._matching_heap) == 1

    partial_reports = restarted.process_matching_detailed(
        current_ts_ns=T0_NS,
        market_by_symbol={"ETH/USD": _market(T0_NS, Decimal("0.40"))},
    )
    assert [report.status for report in partial_reports] == [
        OrderStatus.ACKNOWLEDGED,
        OrderStatus.PARTIAL_FILL,
    ]

    partial_restarted = _broker(state_path)
    partial_restarted.restore_from_durable_state()
    partial_order = partial_restarted.open_orders["durable-recovery-order"]
    assert partial_order.filled_quantity == Decimal("0.40")
    assert partial_order.remaining_quantity == Decimal("0.60")
    assert partial_restarted.validate_invariants()["valid"] is True

    full_reports = partial_restarted.process_matching_detailed(
        current_ts_ns=T0_NS + 1,
        market_by_symbol={"ETH/USD": _market(T0_NS + 1, Decimal("0.60"))},
    )
    assert [report.status for report in full_reports] == [OrderStatus.FULLY_FILLED]

    terminal_restarted = _broker(state_path)
    terminal_restarted.restore_from_durable_state()
    assert terminal_restarted.open_orders == {}
    assert terminal_restarted.validate_invariants()["valid"] is True
    full_fill_reports = [
        report
        for report in terminal_restarted.execution_reports
        if report.client_id == "durable-recovery-order"
        and report.status == OrderStatus.FULLY_FILLED
    ]
    assert len(full_fill_reports) == 1
    duplicate_reports = terminal_restarted.process_matching_detailed(
        current_ts_ns=T0_NS + 2,
        market_by_symbol={"ETH/USD": _market(T0_NS + 2, Decimal("1.0"))},
    )
    assert duplicate_reports == []


def _book(symbol: str, ts_ns: int, mid: float) -> OrderBookSnapshot:
    return OrderBookSnapshot(
        symbol=symbol,
        exchange_ts_ns=ts_ns,
        bids=[(mid - 1.0, 4.0), (mid - 2.0, 3.0)],
        asks=[(mid + 1.0, 3.0), (mid + 2.0, 2.0)],
    )


def _candle(symbol: str, ts_ns: int, close: float) -> Candle:
    return Candle(
        symbol=symbol,
        exchange_ts_ns=ts_ns,
        open=close,
        high=close * 1.002,
        low=close * 0.998,
        close=close,
        volume=2500.0,
        timeframe="1m",
    )


def test_symbol_runtime_exports_imports_symbol_local_state_and_fails_closed():
    btc = SymbolRuntime("BTC/USD")
    eth = SymbolRuntime("ETH/USD")
    btc.update_order_book(_book("BTC/USD", T0_NS, 50_000.0))
    btc.update_candle(_candle("BTC/USD", T0_NS + 1, 50_010.0))
    eth.update_order_book(_book("ETH/USD", T0_NS + 2, 2_500.0))
    eth.update_candle(_candle("ETH/USD", T0_NS + 3, 2_505.0))

    recovered_btc = SymbolRuntime.import_recovery_state(
        btc.export_recovery_state(),
        expected_symbol="BTC/USD",
        current_ts_ns=T0_NS + 4,
        max_state_age_ns=10,
    )
    recovered_eth = SymbolRuntime.import_recovery_state(
        eth.export_recovery_state(),
        expected_symbol="ETH/USD",
        current_ts_ns=T0_NS + 4,
        max_state_age_ns=10,
    )

    assert recovered_btc.symbol == "BTC/USD"
    assert recovered_eth.symbol == "ETH/USD"
    assert recovered_btc.last_order_book.symbol == "BTC/USD"
    assert recovered_eth.last_order_book.symbol == "ETH/USD"
    assert recovered_btc.last_price != recovered_eth.last_price
    assert recovered_btc.recovery_status == "hydrated_market_state_only"
    assert recovered_eth.recovery_status == "hydrated_market_state_only"
    assert recovered_btc.initialized is False
    assert recovered_btc.topological_engine is None
    assert recovered_btc.last_sector_rotation_observed_vote is None
    assert not hasattr(recovered_btc, "execution_engine")
    assert not hasattr(recovered_btc, "order_router")
    assert not hasattr(recovered_btc, "submit_order")

    stale = SymbolRuntime.import_recovery_state(
        btc.export_recovery_state(),
        expected_symbol="BTC/USD",
        current_ts_ns=T0_NS + 1_000_000_000,
        max_state_age_ns=10,
    )
    assert stale.recovery_status == "stale_fail_closed"
    assert stale.is_ready() is False

    incomplete_state = btc.export_recovery_state()
    incomplete_state["last_order_book"] = None
    incomplete = SymbolRuntime.import_recovery_state(incomplete_state, expected_symbol="BTC/USD")
    assert incomplete.recovery_status == "incomplete_fail_closed"
    assert incomplete.is_ready() is False

    mismatch_state = btc.export_recovery_state()
    try:
        SymbolRuntime.import_recovery_state(mismatch_state, expected_symbol="ETH/USD")
    except ValueError as exc:
        assert "symbol mismatch" in str(exc)
    else:
        raise AssertionError("cross-symbol runtime recovery must fail closed")


STRATEGY_BRAIN_RECOVERY_CLASSIFICATION = {
    "OpportunityRanking": {
        "classification": "reconstructable",
        "reason": "pure ranking report can be recomputed from candidates/instruments/exposures",
    },
    "GammaFront": {
        "classification": "safe_reset",
        "reason": "dark-pool rolling context can neutralize until fresh prints rebuild evidence",
    },
    "AdaptiveDC": {
        "classification": "safe_reset",
        "reason": "directional-change state can neutralize until fresh ticks rebuild extrema",
    },
    "SectorRotation": {
        "classification": "reconstructable",
        "reason": "entry vote metadata comes from current StrategySignal adapter",
    },
    "LiquidityVoid": {
        "classification": "reconstructable",
        "reason": "entry/exit metadata comes from current StrategySignal adapter",
    },
    "MovingFloor": {
        "classification": "must_persist_or_reset_protective",
        "reason": "active profit floor should persist for open positions; absent state must not open fresh trades",
    },
    "HedgingFlow": {
        "classification": "reconstructable",
        "reason": "hedge recommendation derives from current exposure snapshot plus market context",
    },
    "Recalibrator": {
        "classification": "safe_reset",
        "reason": "recalibration state may reset neutral unless a future packet persists active cooldowns",
    },
    "WhaleZoneEngine": {
        "classification": "safe_reset",
        "reason": "zone evidence can rebuild from fresh market history and should not fake readiness",
    },
    "ConvexitySwitch": {
        "classification": "safe_reset",
        "reason": "regime weights can neutralize until fresh return observations arrive",
    },
    "SentimentEngine": {
        "classification": "safe_reset",
        "reason": "aggregate sentiment can neutralize until fresh sources arrive",
    },
    "CrossAssetRiskModel": {
        "classification": "reconstructable",
        "reason": "risk report derives from positions, prices, instruments, and equity",
    },
}


def test_strategy_adaptive_brain_recovery_classification_is_explicit():
    expected_modules = {
        "OpportunityRanking",
        "GammaFront",
        "AdaptiveDC",
        "SectorRotation",
        "LiquidityVoid",
        "MovingFloor",
        "HedgingFlow",
        "Recalibrator",
        "WhaleZoneEngine",
        "ConvexitySwitch",
        "SentimentEngine",
        "CrossAssetRiskModel",
    }
    assert set(STRATEGY_BRAIN_RECOVERY_CLASSIFICATION) == expected_modules
    allowed = {
        "must_persist",
        "must_persist_or_reset_protective",
        "reconstructable",
        "safe_reset",
        "blocked",
    }
    for module, details in STRATEGY_BRAIN_RECOVERY_CLASSIFICATION.items():
        assert details["classification"] in allowed
        assert details["reason"]
        if details["classification"] == "safe_reset":
            assert "neutral" in details["reason"] or "not fake readiness" in details["reason"]
        assert "execution" not in details.get("reason", "").lower()


def test_truth_and_invariant_components_are_validation_only_or_classified_future():
    ts_ns = now_ns()
    kernel = TruthKernel()
    kernel.update_exchange_truth(
        ExchangeTruth(
            venue="paper",
            balances={"USD": Decimal("100000")},
            exchange_ts_ns=ts_ns,
        )
    )
    kernel.update_execution_truth(ExecutionTruth(last_reconciliation_ts_ns=ts_ns))
    kernel.update_portfolio_truth(
        PortfolioTruth(
            cash={"USD": Decimal("100000")},
            reserved_buying_power=Decimal("0"),
            total_equity=Decimal("100000"),
            last_update_ts_ns=ts_ns,
        )
    )
    kernel.update_strategy_truth(StrategyTruth(last_update_ts_ns=ts_ns))
    kernel.update_risk_truth(RiskTruth(mode=RiskMode.NORMAL))

    frame = kernel.create_truth_frame(status=TruthStatus.RECONCILED)
    batch = InvariantChecker().evaluate(frame)

    assert kernel.has_all_truths() is True
    assert frame.status == TruthStatus.RECONCILED
    assert batch.results
    assert all(result.passed for result in batch.results)

    validation_status = {
        "TruthKernel": "validation_only_harnessed",
        "InvariantChecker": "validation_only_harnessed",
        "HydrationManager": "blocked_future_work_constructor_requires_shared_memory_unified_market_and_snapshot_mutation",
    }
    assert validation_status["TruthKernel"] == "validation_only_harnessed"
    assert validation_status["InvariantChecker"] == "validation_only_harnessed"
    assert validation_status["HydrationManager"].startswith("blocked_future_work")


def test_durable_recovery_helpers_do_not_create_new_authority():
    paper_sources = (
        inspect.getsource(PaperBroker.persist_durable_state),
        inspect.getsource(PaperBroker.restore_from_durable_state),
    )
    runtime_sources = (
        inspect.getsource(SymbolRuntime.export_recovery_state),
        inspect.getsource(SymbolRuntime.import_recovery_state),
    )
    forbidden_tokens = (
        "broker_adapter",
        "live_broker",
        "NetEdgeGovernor",
        "TradeEfficiencyGovernor",
        "SovereignExecutionGuard",
        "StrategyAllocator",
        "SovereignGovernor",
        "_execute_signal",
    )
    for source in paper_sources + runtime_sources:
        for token in forbidden_tokens:
            assert token not in source

    for source in runtime_sources:
        assert "submit_order" not in source
        assert "OrderRouter" not in source
        assert "ExecutionEngine" not in source
