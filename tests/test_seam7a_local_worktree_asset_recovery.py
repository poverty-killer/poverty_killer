from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.models.enums import (
    AuthorityTier,
    BookIntegrity,
    ExecutionMode,
    ReplayMode,
    SignalDirection,
    ToxicityLevel,
)
from app.risk.net_edge_governor import (
    AdversarialBurdens,
    CandidateContext,
    CandidateType,
    EconomicDecision,
    ExecutionEconomics,
    NetEdgeGovernor,
)
from app.risk.trade_efficiency_governor import (
    KellyOverlayStatus,
    LeadershipStatus,
    SleeveEfficiencyState,
    TradeEfficiencyGovernor,
)
from app.strategies.moving_floor import (
    FloorEventType,
    FloorMarketTick,
    TopologicalMovingFloor,
)


T0_NS = 1_777_948_800_000_000_000


def _tick(
    *,
    price: str,
    timestamp_ns: int,
    bid: str = "10",
    ask: str = "10",
    book_integrity: BookIntegrity = BookIntegrity.HEALTHY,
) -> FloorMarketTick:
    return FloorMarketTick(
        symbol="ETH/USD",
        price=Decimal(price),
        timestamp_ns=timestamp_ns,
        bid_volume=Decimal(bid),
        ask_volume=Decimal(ask),
        book_integrity=book_integrity,
        toxicity_level=ToxicityLevel.BENIGN,
        replay_mode=ReplayMode.REPLAY,
        execution_mode=ExecutionMode.REPLAY,
    )


def test_moving_floor_protects_price_floor_and_emits_protective_exit_only():
    router = MagicMock()
    execution_engine = MagicMock()
    floor = TopologicalMovingFloor(base_buffer=Decimal("0.0200"))

    event_0, assessment_0, recommendation_0 = floor.process_tick(
        _tick(price="100", timestamp_ns=T0_NS)
    )
    assert event_0 is not None
    assert event_0.event_type == FloorEventType.INITIALIZED
    assert event_0.current_floor == Decimal("98.0000")
    assert assessment_0 is not None
    assert recommendation_0 is None

    event_1, _, recommendation_1 = floor.process_tick(
        _tick(price="105", timestamp_ns=T0_NS + 1_000_000_000)
    )
    assert event_1 is not None
    assert event_1.event_type == FloorEventType.RATCHET_UP
    assert event_1.current_floor > event_0.current_floor
    assert recommendation_1 is None

    event_2, assessment_2, recommendation_2 = floor.process_tick(
        _tick(
            price="102",
            timestamp_ns=T0_NS + 2_000_000_000,
            bid="5",
            ask="15",
        )
    )
    assert event_2 is not None
    assert event_2.event_type == FloorEventType.TOPOLOGICAL_BREACH
    assert assessment_2 is not None
    assert assessment_2.signal_direction == SignalDirection.SHORT
    assert assessment_2.authority_tier == AuthorityTier.SOFT_BLOCK
    assert recommendation_2 is not None
    assert recommendation_2.signal_direction == SignalDirection.SHORT
    assert recommendation_2.source_module == "app.strategies.moving_floor"
    assert "price_crossed_topological_support" in recommendation_2.rationale

    router.submit_order.assert_not_called()
    execution_engine.submit_signal.assert_not_called()
    assert not hasattr(floor, "order_router")
    assert not hasattr(floor, "execution_engine")


def test_moving_floor_handles_untrustworthy_book_as_suppressed_no_effect():
    floor = TopologicalMovingFloor()
    event, assessment, recommendation = floor.process_tick(
        _tick(
            price="100",
            timestamp_ns=T0_NS,
            book_integrity=BookIntegrity.UNTRUSTWORTHY,
        )
    )

    assert event is not None
    assert event.event_type == FloorEventType.SUPPRESSED
    assert event.suppressed is True
    assert event.suppress_reason == "book_integrity_failure:UNTRUSTWORTHY"
    assert assessment is not None
    assert assessment.signal_emittable is False
    assert recommendation is None


def _candidate(
    *,
    gross_edge: str,
    confidence: str = "0.80",
    costs: ExecutionEconomics | None = None,
    burdens: AdversarialBurdens | None = None,
    valid_until_ns: int = T0_NS + 10_000,
    candidate_type: CandidateType = CandidateType.FRESH_ENTRY,
) -> CandidateContext:
    return CandidateContext(
        symbol="ETH/USD",
        sleeve_id="shadow_front",
        candidate_type=candidate_type,
        gross_edge=Decimal(gross_edge),
        gross_edge_source="deterministic_test_input",
        estimate_confidence=Decimal(confidence),
        timestamp_ns=T0_NS,
        valid_until_ns=valid_until_ns,
        costs=costs or ExecutionEconomics(),
        burdens=burdens or AdversarialBurdens(),
    )


def test_net_edge_governor_uses_supplied_economic_truth_and_blocks_negative_edge():
    efficiency = TradeEfficiencyGovernor()
    governor = NetEdgeGovernor(efficiency)
    costs = ExecutionEconomics(
        fee_cost=Decimal("1.00"),
        spread_cost=Decimal("0.25"),
        slippage_cost=Decimal("0.50"),
    )
    burdens = AdversarialBurdens(regime_burden=Decimal("0.25"))

    allow = governor.evaluate(
        T0_NS,
        _candidate(gross_edge="5.00", costs=costs, burdens=burdens),
        kill_switch_active=False,
    )
    assert allow.decision == EconomicDecision.ALLOW
    assert allow.total_modeled_cost == Decimal("1.75")
    assert allow.total_modeled_burden == Decimal("0.25")
    assert allow.net_adversarial_edge == Decimal("3.00")
    assert allow.reason_code == "ECONOMICALLY_ADMISSIBLE"

    denied = governor.evaluate(
        T0_NS,
        _candidate(gross_edge="1.00", costs=costs, burdens=burdens),
        kill_switch_active=False,
    )
    assert denied.decision == EconomicDecision.DENY
    assert denied.sizing_multiplier == Decimal("0")
    assert denied.net_adversarial_edge == Decimal("-1.00")
    assert denied.reason_code == "NON_POSITIVE_NET_EDGE"


def test_net_edge_governor_fails_closed_on_stale_or_low_confidence_economics():
    governor = NetEdgeGovernor(TradeEfficiencyGovernor())

    stale = governor.evaluate(
        T0_NS + 2,
        _candidate(gross_edge="5.00", valid_until_ns=T0_NS + 1),
        kill_switch_active=False,
    )
    assert stale.decision == EconomicDecision.DENY
    assert stale.reason_code == "ECONOMICS_STALE_BEYOND_VALIDITY"

    low_confidence = governor.evaluate(
        T0_NS,
        _candidate(gross_edge="5.00", confidence="0.29"),
        kill_switch_active=False,
    )
    assert low_confidence.decision == EconomicDecision.DENY
    assert low_confidence.reason_code == "ESTIMATE_CONFIDENCE_BELOW_THRESHOLD"

    with pytest.raises(ValueError, match="gross_edge_source cannot be empty"):
        CandidateContext(
            symbol="ETH/USD",
            sleeve_id="shadow_front",
            candidate_type=CandidateType.FRESH_ENTRY,
            gross_edge=Decimal("1"),
            gross_edge_source="",
            estimate_confidence=Decimal("0.80"),
            timestamp_ns=T0_NS,
            valid_until_ns=T0_NS + 1,
            costs=ExecutionEconomics(),
            burdens=AdversarialBurdens(),
        )


def test_trade_efficiency_governor_throttles_and_quarantines_sleeve_without_execution_authority():
    governor = TradeEfficiencyGovernor()
    transitions = []
    for offset in range(38):
        transition = governor.register_trade_result(
            sleeve_id="shadow_front",
            timestamp_ns=T0_NS + offset,
            gross_pnl=Decimal("100"),
            net_pnl=Decimal("0"),
            fee_cost=Decimal("30"),
            spread_tax=Decimal("20"),
            slippage_drag=Decimal("20"),
            carry_drag=Decimal("0"),
            capital_committed=Decimal("1000"),
        )
        if transition is not None:
            transitions.append(transition)

    assert len(transitions) == 1
    assert transitions[0].new_state == SleeveEfficiencyState.THROTTLED
    assert transitions[0].reason_code == "ROLLING_EFFICIENCY_THROTTLED"
    assert governor.get_sleeve_state("shadow_front") == SleeveEfficiencyState.THROTTLED
    assert governor.get_sizing_multiplier("shadow_front") == Decimal("0.60")

    hard_stop = governor.force_quarantine("shadow_front", T0_NS + 100, "seam7a_test")
    assert hard_stop.new_state == SleeveEfficiencyState.QUARANTINED
    assert governor.get_sizing_multiplier("shadow_front") == Decimal("0.00")
    assert not hasattr(governor, "order_router")
    assert not hasattr(governor, "execution_engine")


def test_trade_efficiency_governor_imports_confirmed_at_close_rows_only():
    governor = TradeEfficiencyGovernor()
    advisory = {
        "fill_id": "entry-1",
        "metadata": {
            "net_edge_realization": {
                "measurement_label": "ENTRY_MODELED_ADVISORY",
                "true_net_profit_status": "MODELED_ONLY",
            },
            "net_edge_context": {"sleeve_id": "sector_rotation", "regime": "trending_bull"},
        },
    }
    assert governor.register_confirmed_round_trip_realization(advisory)["status"] == "SKIPPED"

    confirmed = {
        "fill_id": "entry-2",
        "fill_ts_ns": T0_NS,
        "metadata": {
            "net_edge_context": {"sleeve_id": "sector_rotation", "regime": "trending_bull"},
            "net_edge_realization": {
                "measurement_label": "AT_CLOSE_ACTUAL_ROUND_TRIP",
                "true_net_profit_status": "BROKER_CONFIRMED_AFTER_POSITION_CLOSE",
                "at_close_actual_round_trip": {
                    "broker_truth_authority": True,
                    "actual_net_profit": "7.50",
                    "gross_pnl": "10.00",
                    "entry_fee": "1.00",
                    "close_fee": "1.50",
                    "matched_quantity": "2",
                    "entry_price": "100",
                },
            },
        },
    }
    result = governor.register_confirmed_round_trip_realization(confirmed)
    assert result["status"] == "IMPORTED"
    snapshot = governor.get_leadership_snapshot("sector_rotation", "trending_bull")
    assert snapshot.sample_count == 1
    assert snapshot.status == LeadershipStatus.NEUTRAL_INSUFFICIENT_SAMPLE


def test_trade_efficiency_leadership_is_sample_gated_then_active_by_regime():
    governor = TradeEfficiencyGovernor()
    transition = governor.register_trade_result(
        sleeve_id="sector_rotation",
        timestamp_ns=T0_NS,
        gross_pnl=Decimal("10"),
        net_pnl=Decimal("8"),
        fee_cost=Decimal("1"),
        spread_tax=Decimal("0.5"),
        slippage_drag=Decimal("0.5"),
        carry_drag=Decimal("0"),
        capital_committed=Decimal("100"),
        regime="trending_bull",
    )
    assert transition is None
    thin = governor.get_leadership_snapshot("sector_rotation", "trending_bull")
    assert thin.status == LeadershipStatus.NEUTRAL_INSUFFICIENT_SAMPLE
    assert thin.multiplier == Decimal("1.00")

    for offset in range(49):
        governor.register_trade_result(
            sleeve_id="sector_rotation",
            timestamp_ns=T0_NS + offset + 1,
            gross_pnl=Decimal("10"),
            net_pnl=Decimal("8"),
            fee_cost=Decimal("1"),
            spread_tax=Decimal("0.5"),
            slippage_drag=Decimal("0.5"),
            carry_drag=Decimal("0"),
            capital_committed=Decimal("100"),
            regime="trending_bull",
        )
        governor.register_trade_result(
            sleeve_id="liquidity_void",
            timestamp_ns=T0_NS + offset + 1,
            gross_pnl=Decimal("10"),
            net_pnl=Decimal("2"),
            fee_cost=Decimal("1"),
            spread_tax=Decimal("0.5"),
            slippage_drag=Decimal("0.5"),
            carry_drag=Decimal("0"),
            capital_committed=Decimal("100"),
            regime="trending_bull",
        )
    governor.register_trade_result(
        sleeve_id="liquidity_void",
        timestamp_ns=T0_NS + 50,
        gross_pnl=Decimal("10"),
        net_pnl=Decimal("2"),
        fee_cost=Decimal("1"),
        spread_tax=Decimal("0.5"),
        slippage_drag=Decimal("0.5"),
        carry_drag=Decimal("0"),
        capital_committed=Decimal("100"),
        regime="trending_bull",
    )

    leader = governor.get_leadership_snapshot("sector_rotation", "trending_bull")
    laggard = governor.get_leadership_snapshot("liquidity_void", "trending_bull")
    assert leader.status == LeadershipStatus.ACTIVE
    assert laggard.status == LeadershipStatus.ACTIVE
    assert leader.multiplier > Decimal("1.00")
    assert laggard.multiplier < Decimal("1.00")
    assert governor.get_sizing_multiplier("sector_rotation", "trending_bull") == leader.multiplier


def test_kelly_overlay_dormant_until_sample_then_risk_of_ruin_fail_closed():
    governor = TradeEfficiencyGovernor()
    for offset in range(49):
        governor.register_trade_result(
            sleeve_id="shadow_front",
            timestamp_ns=T0_NS + offset,
            gross_pnl=Decimal("10"),
            net_pnl=Decimal("8"),
            fee_cost=Decimal("1"),
            spread_tax=Decimal("0.5"),
            slippage_drag=Decimal("0.5"),
            carry_drag=Decimal("0"),
            capital_committed=Decimal("100"),
            regime="ranging",
        )
    dormant = governor.get_kelly_overlay("shadow_front", "ranging")
    assert dormant.status == KellyOverlayStatus.DORMANT_INSUFFICIENT_REALIZED_SAMPLE
    assert dormant.effective_kelly_cap == Decimal("0.25")

    governor.register_trade_result(
        sleeve_id="shadow_front",
        timestamp_ns=T0_NS + 49,
        gross_pnl=Decimal("10"),
        net_pnl=Decimal("8"),
        fee_cost=Decimal("1"),
        spread_tax=Decimal("0.5"),
        slippage_drag=Decimal("0.5"),
        carry_drag=Decimal("0"),
        capital_committed=Decimal("100"),
        regime="ranging",
    )
    active = governor.get_kelly_overlay("shadow_front", "ranging")
    assert active.status == KellyOverlayStatus.ACTIVE_RISK_OF_RUIN_CONFIRMED
    assert active.effective_kelly_cap == Decimal("0.50")
    assert active.risk_of_ruin_estimate == Decimal("0.000000")

    for offset in range(50):
        governor.register_trade_result(
            sleeve_id="gamma_front",
            timestamp_ns=T0_NS + offset,
            gross_pnl=Decimal("10"),
            net_pnl=Decimal("-2"),
            fee_cost=Decimal("1"),
            spread_tax=Decimal("0.5"),
            slippage_drag=Decimal("0.5"),
            carry_drag=Decimal("0"),
            capital_committed=Decimal("100"),
            regime="ranging",
        )
    blocked = governor.get_kelly_overlay("gamma_front", "ranging")
    assert blocked.status == KellyOverlayStatus.ACTIVE_RISK_OF_RUIN_BLOCKED
    assert blocked.effective_kelly_cap == Decimal("0.25")
