from decimal import Decimal
from unittest.mock import MagicMock

from app.models.contracts import StrategyVote
from app.models.enums import (
    AuthorityTier,
    BookIntegrity,
    ExecutionMode,
    ReplayMode,
    SignalDirection,
    SignalType,
    StrategyID,
    ToxicityLevel,
)
from app.strategies.council_metadata import (
    MODULE_MOVING_FLOOR,
    ROLE_PROTECTIVE_EXIT,
    SOURCE_FLOOR_SIGNAL_RECOMMENDATION,
)
from app.strategies.moving_floor import (
    FloorEventType,
    FloorMarketTick,
    TopologicalMovingFloor,
)
from app.strategies.strategy_vote_adapters import adapt_moving_floor_to_vote


T0_NS = 1_777_948_800_000_000_000


def _moving_floor_breach_recommendation():
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


def test_moving_floor_breach_recommendation_adapts_to_protective_vote():
    recommendation = _moving_floor_breach_recommendation()

    vote = adapt_moving_floor_to_vote(
        recommendation,
        exchange_ts_ns=T0_NS + 2_000_000_000,
        decision_uuid="moving-floor-adapter-decision",
    )

    assert isinstance(vote, StrategyVote)
    assert vote.decision_uuid == "moving-floor-adapter-decision"
    assert vote.strategy_id == StrategyID.MOVING_FLOOR.value
    assert vote.timestamp_ns == T0_NS + 2_000_000_000
    assert vote.signal == SignalType.SELL.value
    assert vote.confidence == recommendation.confidence
    assert vote.expected_move_bps == Decimal("0.000000")
    assert vote.expected_duration_ns == 1
    assert vote.risk_appetite == Decimal("0.000000")

    metadata = vote.metadata
    assert metadata["source_module"] == MODULE_MOVING_FLOOR
    assert metadata["source_strategy_id"] == StrategyID.MOVING_FLOOR.value
    assert metadata["source_output_type"] == SOURCE_FLOOR_SIGNAL_RECOMMENDATION
    assert metadata["adapter_name"] == "adapt_moving_floor_to_vote"
    assert metadata["contribution_role"] == ROLE_PROTECTIVE_EXIT
    assert metadata["protective_only"] is True
    assert metadata["fresh_entry_authorized"] is False
    assert metadata["requires_existing_position"] is True
    assert metadata["execution_candidate"] is False
    assert metadata["directional_bias"] == "short"
    assert metadata["feed_status"] == "real"
    assert metadata["raw_confidence"] == float(recommendation.confidence)
    assert metadata["normalized_confidence"] == float(recommendation.confidence)
    assert metadata["symbol"] == "ETH/USD"
    assert metadata["authority_tier"] == AuthorityTier.SOFT_BLOCK.value
    assert metadata["event_type"] == FloorEventType.TOPOLOGICAL_BREACH.value
    assert metadata["protective_semantics"] == "exit_existing_position_only"
    assert "price_crossed_topological_support" in metadata["reason"]


def test_moving_floor_adapter_is_pure_and_does_not_route_or_execute():
    recommendation = _moving_floor_breach_recommendation()
    router = MagicMock()
    engine = MagicMock()

    vote = adapt_moving_floor_to_vote(
        recommendation,
        exchange_ts_ns=T0_NS + 2_000_000_000,
        decision_uuid="moving-floor-purity-decision",
    )

    assert isinstance(vote, StrategyVote)
    assert vote.metadata["protective_only"] is True
    assert vote.metadata["fresh_entry_authorized"] is False
    assert vote.metadata["requires_existing_position"] is True
    assert vote.metadata["execution_candidate"] is False
    router.submit_order.assert_not_called()
    engine.submit_signal.assert_not_called()
