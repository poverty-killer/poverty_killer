from __future__ import annotations

import logging
import types
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.config import Config
from app.core.decision_compiler import DecisionCompiler
from app.core.decision_frame import (
    BLOCK,
    CONTRIBUTED,
    DECLINED,
    FRAME_BLOCK,
    FRAME_OUTPUT_BUY,
    FRAME_OUTPUT_NO_TRADE,
    FRAME_OUTPUT_SELL,
    MISSING_TRUTH,
    ModuleEvidence,
    SIGNAL_BUY,
    build_decision_frame,
    build_decision_frame_from_runtime,
    decision_frame_timeout_ns,
    resolve_active_threshold_profile,
)
from app.main_loop import MainLoop, _classify_candle_execution_truth
from app.models import (
    ExchangeTruth,
    ExecutionTruth,
    PortfolioTruth,
    RiskTruth,
    StrategyTruth,
    TruthFrame,
)
from app.models.enums import SignalType, SleeveType, StrategyID, TruthStatus
from app.models.market_data import Candle
from app.models.signals import StrategySignal
from app.risk.exposure_manager import ExposureManager


LOGGER_NAME = "app.main_loop"
T0_NS = 1_777_948_800_000_000_000
NS_PER_SECOND = 1_000_000_000


def _snapshot() -> dict:
    return {
        "snapshot_id": "mts_decision_frame_test",
        "symbol": "ETH/USD",
        "book_ts_ns": T0_NS + 59 * NS_PER_SECOND,
        "candle_id": T0_NS,
        "candle_close_ts_ns": T0_NS + 60 * NS_PER_SECOND,
        "provider_id": "coinbase_public",
        "receive_ts_ns": T0_NS + 61 * NS_PER_SECOND,
        "book_fresh": True,
        "candle_fresh": True,
        "executable_market_truth": True,
        "source_type": "runtime",
        "snapshot_status": "PASS",
        "snapshot_reason_codes": (),
        "snapshot_authority": "candidate_market_truth_snapshot",
        "snapshot_created_ns": T0_NS + 61 * NS_PER_SECOND,
        "candle_freshness_policy_ms": 60_000.0,
    }


def _signal(side: str = "buy", confidence: float = 0.70) -> StrategySignal:
    return StrategySignal(
        strategy="sector_rotation",
        symbol="ETH/USD",
        side=side,
        confidence=confidence,
        quantity=0.10,
        price=2500.0,
        exchange_ts_ns=T0_NS,
        reason="decision_frame_test",
        metadata={
            "stale_data_observation": {
                "current_ts_ns": T0_NS + 61 * NS_PER_SECOND,
                "exchange_ts_ns": T0_NS + 61 * NS_PER_SECOND,
                "local_received_ts_ns": T0_NS + 61 * NS_PER_SECOND,
            }
        },
    )


def _vote(signal: SignalType = SignalType.BUY, confidence: Decimal = Decimal("0.70")):
    return types.SimpleNamespace(
        vote_id="decision-frame-vote",
        decision_uuid="decision-frame-decision",
        strategy_id=StrategyID.SECTOR_ROTATION,
        timestamp_ns=T0_NS,
        signal=signal,
        confidence=confidence,
        risk_appetite=Decimal("0.25"),
        metadata={"symbol": "ETH/USD"},
    )


def _truth_frame() -> TruthFrame:
    return TruthFrame(
        truth_frame_id="decision-frame-truth-frame",
        timestamp_ns=T0_NS,
        exchange_truth=ExchangeTruth(venue="alpaca", exchange_ts_ns=T0_NS),
        execution_truth=ExecutionTruth(last_reconciliation_ts_ns=T0_NS),
        portfolio_truth=PortfolioTruth(last_update_ts_ns=T0_NS),
        strategy_truth=StrategyTruth(last_update_ts_ns=T0_NS),
        risk_truth=RiskTruth(),
        status=TruthStatus.RECONCILED,
    )


def _candle() -> Candle:
    return Candle(
        symbol="ETH/USD",
        exchange_ts_ns=T0_NS,
        open=2500.0,
        high=2501.0,
        low=2499.0,
        close=2500.0,
        volume=100.0,
        timeframe="1m",
        latest_batch_candle=True,
        candle_freshness_policy_ms=60_000.0,
        data_source_type="runtime",
    )


def _runtime(sector_signal=None, sector_vote=None):
    return types.SimpleNamespace(
        last_price=2500.0,
        shadow_front_strategy=MagicMock(),
        gamma_front_strategy=None,
        sector_rotation_strategy=MagicMock(),
        liquidity_void_strategy=None,
        last_sector_rotation_observed_signal=sector_signal,
        last_sector_rotation_observed_vote=sector_vote,
        last_liquidity_void_observed_signal=None,
        last_liquidity_void_observed_vote=None,
        last_liquidity_void_consumed_decision_uuid=None,
        toxicity_engine=MagicMock(),
        sentiment_velocity_engine=MagicMock(),
        last_tpe_signal=None,
    )


def _loop(*, config=None, submit_result=False):
    loop = types.SimpleNamespace()
    loop.config = config or Config(broker_mode="paper")
    loop.commander = MagicMock()
    loop.commander.get_aggression_contract.return_value = types.SimpleNamespace(
        execution_is_attack=False,
        as_metadata=lambda: {
            "authority_owner": "Commander",
            "authority_version": "test",
            "execution_is_attack": False,
            "risk_guard_final_veto_preserved": True,
            "economic_admissibility_final_veto_preserved": True,
            "stale_gate_final_veto_preserved": True,
            "moving_floor_active": False,
            "dormant_governors_active": False,
            "mode": "SAFE",
            "veto_reasons": ("safe_mode",),
        },
    )
    loop.strategy_router = MagicMock()
    loop.strategy_router.update_macro_state = MagicMock()
    loop.strategy_router.get_preferred_strategy = MagicMock(return_value=SleeveType.SECTOR_ROTATION)
    loop.strategy_router.get_eligible_strategies = MagicMock(return_value=[SleeveType.SECTOR_ROTATION])
    loop.decision_compiler = MagicMock()
    loop.decision_compiler.compile = MagicMock(
        return_value=types.SimpleNamespace(
            decision_uuid="decision-frame-runtime-decision",
            decision_type="STRATEGY_VOTE",
            outputs={"additional": {}},
            metadata={},
        )
    )
    loop.execution_engine = MagicMock()
    loop.execution_engine.submit_signal = MagicMock(return_value=submit_result)
    loop.execution_engine.get_status.return_value = {"last_latency_truth": {}}
    loop.execution_engine.get_last_admission_block_result.return_value = types.SimpleNamespace(
        normalized_status="blocked",
        route="execution_engine",
        reason_code="QUOTE_SESSION_TRUTH_MISSING",
        message="hard blocker for non-mutating test",
    )
    loop.exposure_manager = ExposureManager(initial_equity=Decimal("20000"))
    loop._build_truth_frame = MagicMock(return_value=_truth_frame())
    loop._update_shadow_front_overlays = MagicMock()
    loop._generate_signal_and_vote = MagicMock(return_value=(None, None))
    loop._generate_signal_and_vote_gamma_front = MagicMock(return_value=(None, None))
    loop._metrics = types.SimpleNamespace(compilation_cycles=0, orders_submitted=0, orders_rejected=0)
    loop.insider_engine = MagicMock()
    loop._last_equity = 1000.0
    loop._current_regime = "neutral"
    loop.position_sizing_engine = MagicMock()
    loop.signal_fusion = MagicMock()
    loop._active_threshold_profile = MainLoop._active_threshold_profile.__get__(loop, MainLoop)
    loop._classify_shadow_front_decline = MainLoop._classify_shadow_front_decline.__get__(loop, MainLoop)
    loop._consume_observed_pair_sector_rotation = MainLoop._consume_observed_pair_sector_rotation.__get__(loop, MainLoop)
    loop._consume_observed_pair_moving_floor = MainLoop._consume_observed_pair_moving_floor.__get__(loop, MainLoop)
    loop._classify_sector_rotation_observed_pair = MainLoop._classify_sector_rotation_observed_pair.__get__(loop, MainLoop)
    loop._clear_stale_sector_rotation_observed_pair = MainLoop._clear_stale_sector_rotation_observed_pair.__get__(loop, MainLoop)
    loop._runtime_module_frame_evidence = MainLoop._runtime_module_frame_evidence.__get__(loop, MainLoop)
    loop._apply_signal_economic_metadata = MainLoop._apply_signal_economic_metadata.__get__(loop, MainLoop)
    loop._net_edge_frame_evidence = MainLoop._net_edge_frame_evidence
    loop._compile_scorecard_frame_no_submit = MainLoop._compile_scorecard_frame_no_submit.__get__(loop, MainLoop)
    return loop


def test_complete_frame_includes_relevant_module_statuses():
    profile = resolve_active_threshold_profile(Config(broker_mode="paper"))
    frame = build_decision_frame_from_runtime(
        symbol="ETH/USD",
        snapshot=_snapshot(),
        created_at_ns=T0_NS,
        timeout_ns=decision_frame_timeout_ns(Config(), _snapshot()),
        active_threshold_profile=profile,
        signal=_signal(),
        strategy_vote=_vote(),
        fusion=types.SimpleNamespace(confidence=0.22, preferred_sleeve="sector_rotation"),
        dispatch_evidence=(
            {"module": "ShansCurve", "status": "BLOCK", "reason_code": "shans_not_ready"},
            {"module": "SectorRotation", "status": "DECLINED", "reason_code": "OBSERVED_SIGNAL_MISSING"},
            {"module": "ShadowFront", "status": "DECLINED", "reason_code": "shadowfront_declined_whale_condition"},
        ),
        edge_attribution={
            "WhaleFlow": {"status": "MISSING_FEED_TRUTH", "effect": "ADVISORY", "reason": "MISSING_NONCRITICAL_SIGNAL:whale_flow"},
            "StateStore": {"status": "PASSED", "effect": "ADVISORY", "reason": "LOCAL_STATE_SUPPORTING_EVIDENCE_ONLY"},
        },
    )

    evidence = frame["module_evidence"]
    assert evidence["StrategySignal"]["status"] == CONTRIBUTED
    assert evidence["StrategyVote"]["signal"] == SIGNAL_BUY
    assert evidence["ShansCurve"]["status"] == MISSING_TRUTH
    assert evidence["SectorRotation"]["status"] == MISSING_TRUTH
    assert evidence["ShadowFront"]["status"] == DECLINED
    assert evidence["WhaleFlow"]["status"] == MISSING_TRUTH
    assert evidence["StateStore"]["status"] == CONTRIBUTED
    assert frame["frame_output"] == FRAME_OUTPUT_BUY


def test_stale_or_mismatched_module_snapshot_blocks_frame_without_erasing_evidence():
    frame = build_decision_frame(
        symbol="ETH/USD",
        snapshot=_snapshot(),
        created_at_ns=T0_NS,
        timeout_ns=60 * NS_PER_SECOND,
        active_threshold_profile=resolve_active_threshold_profile(Config()),
        module_evidence=(
            ModuleEvidence(
                module_name="SectorRotation",
                authority_class="ALPHA",
                status=CONTRIBUTED,
                signal=SIGNAL_BUY,
                confidence=Decimal("0.9"),
                snapshot_id="mts_other",
                candle_id=T0_NS,
            ),
        ),
    ).to_dict()

    assert frame["frame_status"] == FRAME_BLOCK
    assert frame["frame_output"] == FRAME_OUTPUT_NO_TRADE
    assert "MODULE_EVIDENCE_SNAPSHOT_MISMATCH" in frame["frame_reason_codes"]
    assert frame["module_evidence"]["SectorRotation"]["status"] == CONTRIBUTED


def test_decision_compiler_emits_frame_action_from_decision_frame():
    frame = build_decision_frame_from_runtime(
        symbol="ETH/USD",
        snapshot=_snapshot(),
        created_at_ns=T0_NS,
        timeout_ns=60 * NS_PER_SECOND,
        active_threshold_profile=resolve_active_threshold_profile(Config()),
        signal=_signal(),
        strategy_vote=_vote(),
    )

    record = DecisionCompiler().compile(
        truth_frame=_truth_frame(),
        strategy_votes=[],
        additional_inputs={"decision_frame": frame},
    )

    assert record.outputs["frame_output"] == FRAME_OUTPUT_BUY
    assert record.outputs["frame_status"] == frame["frame_status"]
    assert record.outputs["frame_reason_codes"] == frame["frame_reason_codes"]
    assert record.outputs["compiled_action"] == FRAME_OUTPUT_BUY
    assert record.outputs["active_threshold_profile"] == frame["active_threshold_profile"]
    assert record.metadata["frame_id"] == frame["frame_id"]
    assert record.metadata["frame_output"] == FRAME_OUTPUT_BUY
    assert record.metadata["frame_status"] == frame["frame_status"]
    assert record.metadata["frame_reason_codes"] == frame["frame_reason_codes"]


def test_decision_compiler_emits_no_trade_from_empty_frame():
    frame = build_decision_frame_from_runtime(
        symbol="ETH/USD",
        snapshot=_snapshot(),
        created_at_ns=T0_NS,
        timeout_ns=60 * NS_PER_SECOND,
        active_threshold_profile=resolve_active_threshold_profile(Config()),
    )

    record = DecisionCompiler().compile(
        truth_frame=_truth_frame(),
        strategy_votes=[],
        additional_inputs={"decision_frame": frame},
    )

    assert record.outputs["frame_output"] == FRAME_OUTPUT_NO_TRADE
    assert record.outputs["compiled_action"] == FRAME_OUTPUT_NO_TRADE
    assert record.metadata["frame_output"] == FRAME_OUTPUT_NO_TRADE


def test_runtime_frame_blocks_advisory_direction_without_executable_intent():
    frame = build_decision_frame_from_runtime(
        symbol="ETH/USD",
        snapshot=_snapshot(),
        created_at_ns=T0_NS,
        timeout_ns=60 * NS_PER_SECOND,
        active_threshold_profile=resolve_active_threshold_profile(Config()),
        signal=None,
        strategy_vote=None,
        fusion=types.SimpleNamespace(confidence=0.60, preferred_sleeve="sector_rotation"),
        dispatch_evidence=(
            {
                "module": "ShansCurve",
                "authority_class": "ALPHA",
                "status": CONTRIBUTED,
                "reason_code": "SHANS_READY",
                "signal": "SELL",
                "confidence": Decimal("0.80"),
            },
        ),
    )

    assert frame["frame_status"] == FRAME_BLOCK
    assert frame["frame_output"] == FRAME_OUTPUT_NO_TRADE
    assert "EXECUTABLE_INTENT_MISSING" in frame["frame_reason_codes"]
    assert frame["module_evidence"]["ShansCurve"]["signal"] == "SELL"
    assert frame["module_evidence"]["ExecutableIntent"]["status"] == BLOCK


def test_paper_exploration_profile_relaxes_alpha_thresholds_and_logs_values():
    config = Config(broker_mode="paper", alpaca_paper=True, paper_exploration_alpha_enabled=True)
    profile = resolve_active_threshold_profile(config)

    assert profile["enabled"] is True
    assert profile["paper_only"] is True
    thresholds = profile["thresholds_by_name"]
    assert thresholds["sector_inflow_threshold"]["default_value"] == 1.5
    assert thresholds["sector_inflow_threshold"]["exploration_value"] == 0.75
    assert thresholds["minimum_opportunity_score"]["exploration_value"] == 0.25


def test_paper_exploration_profile_cannot_activate_with_live_mode():
    with pytest.raises(ValueError):
        Config(broker_mode="live", alpaca_paper=False, paper_exploration_alpha_enabled=True)


def test_fresh_buy_frame_reaches_mocked_submit_with_broker_post_false_under_hard_blocker(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    config = Config(broker_mode="paper", alpaca_paper=True, paper_exploration_alpha_enabled=True)
    signal = _signal()
    vote = _vote()
    runtime = _runtime(sector_signal=signal, sector_vote=vote)
    candle = _candle()
    runtime.last_candle = candle
    runtime.last_order_book = types.SimpleNamespace(exchange_ts_ns=T0_NS)
    candle_truth = _classify_candle_execution_truth(
        symbol="ETH/USD",
        runtime=runtime,
        candle=candle,
        exchange_ts_ns=T0_NS,
        current_ns=T0_NS + 61 * NS_PER_SECOND,
    )
    loop = _loop(config=config, submit_result=False)

    MainLoop._dispatch_fusion.__get__(loop, MainLoop)(
        "ETH/USD",
        runtime,
        fusion=types.SimpleNamespace(confidence=0.30, preferred_sleeve="sector_rotation", attack_mode=False),
        exchange_ts_ns=T0_NS,
        candle_execution_truth=candle_truth,
    )

    loop.decision_compiler.compile.assert_called_once()
    loop.execution_engine.submit_signal.assert_called_once()
    additional_inputs = loop.decision_compiler.compile.call_args.kwargs["additional_inputs"]
    frame = additional_inputs["decision_frame"]
    assert frame["active_threshold_profile"]["profile_name"] == "PAPER_EXPLORATION_ALPHA"
    assert frame["frame_output"] == FRAME_OUTPUT_BUY
    assert "decision_frame" in signal.metadata
    assert "broker_post': False" in caplog.text
    assert "QUOTE_SESSION_TRUTH_MISSING" in caplog.text


def test_paper_exploration_router_ranking_does_not_suppress_sector_rotation_submit_path():
    config = Config(broker_mode="paper", alpaca_paper=True, paper_exploration_alpha_enabled=True)
    signal = _signal()
    vote = _vote()
    runtime = _runtime(sector_signal=signal, sector_vote=vote)
    runtime.last_candle = _candle()
    runtime.last_order_book = types.SimpleNamespace(exchange_ts_ns=T0_NS, spread_bps=4.0)
    candle_truth = _classify_candle_execution_truth(
        symbol="ETH/USD",
        runtime=runtime,
        candle=runtime.last_candle,
        exchange_ts_ns=T0_NS,
        current_ns=T0_NS + 61 * NS_PER_SECOND,
    )
    loop = _loop(config=config, submit_result=False)
    loop.strategy_router.get_preferred_strategy.return_value = SleeveType.SHADOW_FRONT
    loop.strategy_router.get_eligible_strategies.return_value = [SleeveType.SHADOW_FRONT]

    MainLoop._dispatch_fusion.__get__(loop, MainLoop)(
        "ETH/USD",
        runtime,
        fusion=types.SimpleNamespace(confidence=0.30, preferred_sleeve="shadow_front", attack_mode=False),
        exchange_ts_ns=T0_NS,
        candle_execution_truth=candle_truth,
    )

    loop.decision_compiler.compile.assert_called_once()
    loop.execution_engine.submit_signal.assert_called_once()
    submitted_signal = loop.execution_engine.submit_signal.call_args.kwargs["signal"]
    assert submitted_signal.strategy == "sector_rotation"
    frame = loop.decision_compiler.compile.call_args.kwargs["additional_inputs"]["decision_frame"]
    assert frame["module_evidence"]["StrategyRouter"]["metadata"]["router_authority"] == "ranking_only_no_execution"
    assert frame["frame_output"] == FRAME_OUTPUT_BUY


def test_moving_floor_protective_exit_reaches_mocked_submit_as_sell_to_close():
    config = Config(broker_mode="paper", alpaca_paper=True, paper_exploration_alpha_enabled=True)
    signal = _signal(side="sell", confidence=0.82)
    signal.strategy = "moving_floor"
    signal.metadata.update(
        {
            "protective_only": True,
            "requires_existing_position": True,
            "fresh_entry_authorized": False,
            "execution_candidate": True,
            "broker_position_backed": True,
            "existing_positions": (
                {"symbol": "ETHUSD", "quantity": "0.10", "average_entry_price": "2400"},
            ),
            "expected_move_bps": "120",
            "gross_edge_bps": "120",
            "action": "sell_to_close",
            "execution_action": "sell_to_close",
            "order_action": "sell_to_close",
        }
    )
    vote = _vote(signal=SignalType.SELL, confidence=Decimal("0.82"))
    vote.strategy_id = StrategyID.MOVING_FLOOR
    runtime = _runtime()
    runtime.last_candle = _candle()
    runtime.last_order_book = types.SimpleNamespace(exchange_ts_ns=T0_NS, spread_bps=4.0)
    runtime.last_moving_floor_observed_signal = signal
    runtime.last_moving_floor_observed_vote = vote
    runtime.last_moving_floor_evidence = {
        "module": "MovingFloor",
        "authority_class": "RISK",
        "status": "PASS",
        "reason_code": "MOVING_FLOOR_PROTECTIVE_EXIT_CANDIDATE",
        "signal": "SELL",
        "confidence": Decimal("0.82"),
        "evidence": {
            "protective_only": True,
            "requires_existing_position": True,
            "broker_position_backed": True,
            "candidate_side": "sell_to_close",
        },
    }
    candle_truth = _classify_candle_execution_truth(
        symbol="ETH/USD",
        runtime=runtime,
        candle=runtime.last_candle,
        exchange_ts_ns=T0_NS,
        current_ns=T0_NS + 61 * NS_PER_SECOND,
    )
    loop = _loop(config=config, submit_result=False)

    MainLoop._dispatch_fusion.__get__(loop, MainLoop)(
        "ETH/USD",
        runtime,
        fusion=types.SimpleNamespace(confidence=0.30, preferred_sleeve="sector_rotation", attack_mode=False),
        exchange_ts_ns=T0_NS,
        candle_execution_truth=candle_truth,
    )

    loop.decision_compiler.compile.assert_called_once()
    additional_inputs = loop.decision_compiler.compile.call_args.kwargs["additional_inputs"]
    frame = additional_inputs["decision_frame"]
    assert frame["frame_output"] == FRAME_OUTPUT_SELL, "|".join(frame["frame_reason_codes"])
    assert frame["frame_status"] == "PASS", frame["frame_reason_codes"]
    assert additional_inputs["pre_trade_guardrail_verdict"]["route_permitted"] is True, (
        additional_inputs["pre_trade_guardrail_verdict"]["reason_codes"]
    )
    loop.execution_engine.submit_signal.assert_called_once()
    submitted_signal = loop.execution_engine.submit_signal.call_args.kwargs["signal"]
    assert submitted_signal.strategy == "moving_floor"
    assert submitted_signal.side == "sell"
    assert submitted_signal.metadata["execution_action"] == "sell_to_close"
    assert submitted_signal.metadata["sell_intent_classification"] == "SELL_EXIT_EXISTING_BROKER_POSITION"
    assert frame["module_evidence"]["MovingFloor"]["reason_codes"] == (
        "MOVING_FLOOR_PROTECTIVE_EXIT_CANDIDATE",
    )
