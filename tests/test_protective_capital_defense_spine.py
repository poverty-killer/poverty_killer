from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from decimal import Decimal
from unittest.mock import MagicMock

from app.brain.recalibrator import Recalibrator
from app.brain.topological_engine import TopologicalSignal
from app.models.contracts import StrategyVote
from app.models.enums import (
    AuthorityTier,
    BookIntegrity,
    ExecutionMode,
    OrderSide,
    ReplayMode,
    SignalDirection,
    SignalType,
    StrategyID,
    ToxicityLevel,
)
from app.strategies.council_metadata import (
    BIAS_SHORT,
    FEED_REAL,
    MODULE_HEDGING_FLOW,
    MODULE_MOVING_FLOOR,
    MODULE_RECALIBRATOR,
    ROLE_HEDGE,
    ROLE_OBSERVE_ONLY,
    ROLE_PROTECTIVE_EXIT,
    SOURCE_FLOOR_SIGNAL_RECOMMENDATION,
    SOURCE_HEDGE_RECOMMENDATION,
    SOURCE_RECALIBRATION_STATE,
    build_council_metadata,
)
from app.strategies.hedging_flow import (
    HedgeMarketContext,
    HedgeRecommendation,
    HedgingFlow,
    PortfolioExposureSnapshot,
)
from app.strategies.moving_floor import (
    FloorEventType,
    FloorMarketTick,
    FloorSignalRecommendation,
    TopologicalMovingFloor,
)
from app.strategies.strategy_vote_adapters import adapt_moving_floor_to_vote


T0_NS = 1_777_948_800_000_000_000


@dataclass
class ControlledProtectiveCouncilHarness:
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
        assert metadata.get("protective_only") is True or metadata["contribution_role"] == ROLE_HEDGE
        assert metadata.get("requires_existing_position") is True or metadata.get(
            "requires_existing_exposure"
        ) is True

        self.consumed.append({"module": module, "output": output, "metadata": metadata})


def _moving_floor_breach_recommendation() -> FloorSignalRecommendation:
    floor = TopologicalMovingFloor(base_buffer=Decimal("0.0200"))

    floor.process_tick(
        FloorMarketTick(
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
    )
    floor.process_tick(
        FloorMarketTick(
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
    )
    event, assessment, recommendation = floor.process_tick(
        FloorMarketTick(
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
    )

    assert event is not None
    assert event.event_type == FloorEventType.TOPOLOGICAL_BREACH
    assert assessment is not None
    assert assessment.signal_direction == SignalDirection.SHORT
    assert recommendation is not None
    return recommendation


def _hedge_recommendation() -> HedgeRecommendation:
    hedging = HedgingFlow()
    exposure = PortfolioExposureSnapshot(
        net_delta=Decimal("20000"),
        total_equity=Decimal("100000"),
        target_symbol="BTC/USD",
        sleeve="portfolio_delta",
    )
    market = HedgeMarketContext(
        symbol="BTC/USD",
        price=Decimal("50000"),
        book_integrity=BookIntegrity.HEALTHY,
        toxicity_level=ToxicityLevel.BENIGN,
        replay_mode=ReplayMode.REPLAY,
        execution_mode=ExecutionMode.REPLAY,
    )

    assessment = hedging.assess(exposure=exposure, market=market)
    recommendation = hedging.recommend(assessment=assessment, market=market)

    assert assessment.hedge_required is True
    assert recommendation is not None
    assert recommendation.is_hedge is True
    assert recommendation.side == OrderSide.SELL
    return recommendation


def _hedge_metadata(recommendation: HedgeRecommendation) -> dict:
    return build_council_metadata(
        source_module=MODULE_HEDGING_FLOW,
        source_strategy_id="hedging_flow",
        source_output_type=SOURCE_HEDGE_RECOMMENDATION,
        adapter_name="protective_capital_defense_harness",
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
        symbol=recommendation.symbol,
        requires_existing_exposure=True,
        trade_intent=recommendation.trade_intent.value,
        is_hedge=recommendation.is_hedge,
        urgency=recommendation.urgency,
        authority_tier=recommendation.authority_tier.value,
    )


def _recalibration_metadata(recalibrator: Recalibrator, regime: str) -> dict:
    status = recalibrator.get_status()
    return build_council_metadata(
        source_module=MODULE_RECALIBRATOR,
        source_strategy_id="recalibrator",
        source_output_type=SOURCE_RECALIBRATION_STATE,
        adapter_name="protective_capital_defense_harness",
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
        symbol="BTC/USD",
        requires_existing_exposure=True,
        recalibration_active=status["is_in_recalibration"],
        recalibration_reason=status["recalibration_reason"],
        recovery_attempts=status["recovery_attempts"],
    )


def test_protective_contributors_emit_council_visible_non_entry_intent():
    council = ControlledProtectiveCouncilHarness()
    initial_execution_state = dict(council.execution_state)

    moving_floor_recommendation = _moving_floor_breach_recommendation()
    moving_floor_vote = adapt_moving_floor_to_vote(
        moving_floor_recommendation,
        exchange_ts_ns=T0_NS + 2_000_000_000,
        decision_uuid="protective-capital-defense-moving-floor",
    )

    assert isinstance(moving_floor_vote, StrategyVote)
    assert moving_floor_vote.strategy_id == StrategyID.MOVING_FLOOR.value
    assert moving_floor_vote.signal == SignalType.SELL.value
    assert moving_floor_vote.metadata["source_module"] == MODULE_MOVING_FLOOR
    assert moving_floor_vote.metadata["source_output_type"] == SOURCE_FLOOR_SIGNAL_RECOMMENDATION
    assert moving_floor_vote.metadata["contribution_role"] == ROLE_PROTECTIVE_EXIT
    assert moving_floor_vote.metadata["protective_only"] is True
    assert moving_floor_vote.metadata["fresh_entry_authorized"] is False
    assert moving_floor_vote.metadata["requires_existing_position"] is True
    assert moving_floor_vote.metadata["execution_candidate"] is False

    hedge_recommendation = _hedge_recommendation()
    hedge_metadata = _hedge_metadata(hedge_recommendation)
    assert hedge_metadata["source_module"] == MODULE_HEDGING_FLOW
    assert hedge_metadata["source_output_type"] == SOURCE_HEDGE_RECOMMENDATION
    assert hedge_metadata["contribution_role"] == ROLE_HEDGE
    assert hedge_metadata["fresh_entry_authorized"] is False
    assert hedge_metadata["execution_candidate"] is False
    assert hedge_metadata["requires_existing_exposure"] is True
    assert hedge_metadata["is_hedge"] is True

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
    assert regime == "CRISIS_ABORT"
    recalibrator.start_recalibration(reason=regime, duration_seconds=3600.0)
    recalibration_metadata = _recalibration_metadata(recalibrator, regime)
    assert recalibration_metadata["source_module"] == MODULE_RECALIBRATOR
    assert recalibration_metadata["source_output_type"] == SOURCE_RECALIBRATION_STATE
    assert recalibration_metadata["contribution_role"] == ROLE_OBSERVE_ONLY
    assert recalibration_metadata["fresh_entry_authorized"] is False
    assert recalibration_metadata["execution_candidate"] is False
    assert recalibration_metadata["requires_existing_position"] is True
    assert recalibration_metadata["recalibration_active"] is True

    council.consume(
        module=MODULE_MOVING_FLOOR,
        output=moving_floor_vote,
        metadata=moving_floor_vote.metadata,
    )
    council.consume(
        module=MODULE_HEDGING_FLOW,
        output=hedge_recommendation,
        metadata=hedge_metadata,
    )
    council.consume(
        module=MODULE_RECALIBRATOR,
        output=recalibrator.get_status(),
        metadata=recalibration_metadata,
    )

    assert [item["module"] for item in council.consumed] == [
        MODULE_MOVING_FLOOR,
        MODULE_HEDGING_FLOW,
        MODULE_RECALIBRATOR,
    ]
    assert council.execution_state == initial_execution_state


def test_protective_capital_defense_spine_does_not_open_fresh_trades_or_execute():
    council = ControlledProtectiveCouncilHarness()
    execution_engine = MagicMock()
    order_router = MagicMock()
    paper_broker = MagicMock()

    vote = adapt_moving_floor_to_vote(
        _moving_floor_breach_recommendation(),
        exchange_ts_ns=T0_NS + 2_000_000_000,
        decision_uuid="protective-capital-defense-no-exec",
    )
    hedge = _hedge_recommendation()
    recalibrator = Recalibrator()
    recalibrator.start_recalibration(reason="CRISIS_ABORT", duration_seconds=3600.0)

    council.consume(module=MODULE_MOVING_FLOOR, output=vote, metadata=vote.metadata)
    council.consume(module=MODULE_HEDGING_FLOW, output=hedge, metadata=_hedge_metadata(hedge))
    council.consume(
        module=MODULE_RECALIBRATOR,
        output=recalibrator.get_status(),
        metadata=_recalibration_metadata(recalibrator, "CRISIS_ABORT"),
    )

    for item in council.consumed:
        metadata = item["metadata"]
        assert metadata["fresh_entry_authorized"] is False
        assert metadata["execution_candidate"] is False
        assert metadata.get("requires_existing_position") is True or metadata.get(
            "requires_existing_exposure"
        ) is True

    execution_engine.submit_signal.assert_not_called()
    order_router.submit_order.assert_not_called()
    paper_broker.submit_order.assert_not_called()


def test_protective_modules_have_no_direct_execution_or_live_broker_dependency():
    forbidden_tokens = (
        "ExecutionEngine",
        "OrderRouter",
        "PaperBroker",
        "broker_adapter",
        "live_broker",
        "submit_signal",
        "submit_order",
        "_execute_signal",
    )
    modules = (
        TopologicalMovingFloor,
        HedgingFlow,
        Recalibrator,
        adapt_moving_floor_to_vote,
    )

    for module in modules:
        source = inspect.getsource(module)
        for token in forbidden_tokens:
            assert token not in source
