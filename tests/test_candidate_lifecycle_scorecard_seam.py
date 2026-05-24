from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.commander import Commander
from app.core.candidate_lifecycle import (
    BROKER_AUTHORITY_BLOCKER,
    GOOD_CANDIDATE_NOT_EXECUTABLE,
    build_candidate_lifecycle,
    lifecycle_to_dict,
    opportunity_scorecard_from_lifecycle,
    record_decision_compiler_result,
    record_execution_result,
)
from app.core.decision_compiler import DecisionCompiler
from app.execution.engine import ExecutionEngine
from app.main_loop import _classify_candle_execution_truth
from app.models.contracts import (
    ExchangeTruth,
    ExecutionTruth,
    PortfolioTruth,
    RiskTruth,
    StrategyTruth,
    StrategyVote,
    TruthFrame,
)
from app.models.enums import SignalType, StrategyID, TruthStatus
from app.models.market_data import Candle
from app.models.signals import StrategySignal
from app.risk.guard import HybridRiskGuard


T0_NS = 1_777_948_800_000_000_000
NS_PER_MS = 1_000_000
NS_PER_SECOND = 1_000_000_000


def _truth_frame() -> TruthFrame:
    return TruthFrame(
        truth_frame_id="candidate-scorecard-truth-frame",
        timestamp_ns=T0_NS,
        exchange_truth=ExchangeTruth(venue="alpaca", exchange_ts_ns=T0_NS),
        execution_truth=ExecutionTruth(last_reconciliation_ts_ns=T0_NS),
        portfolio_truth=PortfolioTruth(last_update_ts_ns=T0_NS),
        strategy_truth=StrategyTruth(last_update_ts_ns=T0_NS),
        risk_truth=RiskTruth(),
        status=TruthStatus.RECONCILED,
    )


def _vote(*, side: SignalType = SignalType.BUY, confidence: Decimal = Decimal("0.90")) -> StrategyVote:
    return StrategyVote(
        vote_id="candidate-scorecard-vote",
        decision_uuid="candidate-scorecard-decision",
        strategy_id=StrategyID.SECTOR_ROTATION,
        timestamp_ns=T0_NS,
        signal=side,
        confidence=confidence,
        expected_move_bps=Decimal("50"),
        expected_duration_ns=60 * NS_PER_SECOND,
        risk_appetite=Decimal("0.40"),
    )


def _signal(
    *,
    side: str = "buy",
    confidence: float = 0.90,
    metadata: dict | None = None,
) -> StrategySignal:
    return StrategySignal(
        strategy="sector_rotation",
        symbol="SOL/USD",
        side=side,
        confidence=confidence,
        quantity=0.10,
        price=150.0,
        exchange_ts_ns=T0_NS,
        reason="candidate_scorecard_test",
        metadata={
            "expected_move": "0.02",
            "asset_class": "crypto",
            "execution_adapter": "alpaca_paper_rest",
            "order_type": "limit",
            "time_in_force": "gtc",
            **(metadata or {}),
        },
    )


def _guardrail(*, permitted: bool = True, reason_codes: tuple[str, ...] | None = None, side: str = "buy") -> dict:
    reasons = reason_codes or (("PRE_TRADE_GUARDRAILS_ALLOW",) if permitted else ("QUOTE_SESSION_TRUTH_MISSING",))
    return {
        "verdict": "ALLOW" if permitted else "BLOCK",
        "route_permitted": permitted,
        "mutation_permitted": permitted,
        "reason_codes": reasons,
        "symbol": "SOL/USD",
        "side": side,
        "order_type": "limit",
        "time_in_force": "GTC",
        "requested_notional": "15.00",
        "internal_max_notional": "20.00",
        "capability_identity": {
            "venue_id": "alpaca",
            "portal_name": "alpaca_paper",
            "environment": "paper",
            "asset_class": "crypto",
            "symbol": "SOL/USD",
            "execution_adapter": "alpaca_paper_rest",
        },
        "module_evidence": (),
    }


def _market_truth() -> dict:
    return {
        "symbol": "SOL/USD",
        "latest_book_ts_ns": T0_NS,
        "latest_candle_ts_ns": T0_NS,
        "data_source_type": "runtime",
        "data_health_reason_code": "DATA_HEALTHY",
        "candle_freshness_reason_code": "CANDLE_RUNTIME_FRESH",
        "executable_market_truth": True,
    }


def _rest_latency_degraded() -> dict:
    return {
        "status": "MARKET_DATA_LATENCY_DEGRADED",
        "reason_code": "REST_LATENCY_THRESHOLD_EXCEEDED",
        "latency_ms": 437.0,
        "threshold_ms": 200.0,
        "source": "market_data.rest_polling_rtt",
        "source_scope": "market_data_candle_rtt",
        "safe_mode_required": False,
    }


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
    masking_layer = MagicMock()
    masking_layer.mask_order.return_value = SimpleNamespace(masked_size=Decimal("0.10"))
    return masking_layer


def _engine(router, *, risk_guard=None) -> ExecutionEngine:
    engine = ExecutionEngine(
        commander=Commander(),
        risk_guard=risk_guard or _risk_guard(),
        order_router=router,
        masking_layer=_masking_layer(),
        signal_ttl_ms=1000.0,
    )
    engine._state.is_running = True
    engine._state.last_regime = "neutral"
    return engine


def _build_lifecycle(
    *,
    signal: StrategySignal | None = None,
    guardrail: dict | None = None,
    market_truth: dict | None = None,
    latency_truth: dict | None = None,
    active_threshold_profile: dict | None = None,
    decision_frame: dict | None = None,
    dispatch_evidence=(),
):
    signal = signal or _signal()
    vote = _vote(side=SignalType.SELL if signal.side == "sell" else SignalType.BUY)
    return build_candidate_lifecycle(
        candidate_id=vote.decision_uuid,
        symbol=signal.symbol,
        side=signal.side,
        source_sleeve="SleeveType.SECTOR_ROTATION",
        timestamp_ns=T0_NS,
        signal=signal,
        strategy_vote=vote,
        fusion=SimpleNamespace(confidence=0.90, preferred_sleeve="sector_rotation"),
        market_truth=market_truth or _market_truth(),
        guardrail_verdict=guardrail or _guardrail(side=signal.side),
        latency_truth=latency_truth or {},
        active_threshold_profile=active_threshold_profile,
        decision_frame=decision_frame,
        dispatch_evidence=tuple(dispatch_evidence),
    )


def _attach_lifecycle(signal: StrategySignal, lifecycle) -> StrategySignal:
    lifecycle_dict = lifecycle_to_dict(lifecycle)
    signal.metadata["candidate_lifecycle"] = lifecycle_dict
    signal.metadata["opportunity_scorecard"] = {
        "candidate_id": lifecycle_dict["candidate_id"],
        "symbol": lifecycle_dict["symbol"],
        "side": lifecycle_dict["side"],
        "raw_opportunity_score": lifecycle_dict["raw_opportunity_score"],
        "module_contributions": lifecycle_dict["module_contributions"],
        "module_declines": lifecycle_dict["module_declines"],
        "penalties": lifecycle_dict["penalties"],
        "final_opportunity_score": lifecycle_dict["final_opportunity_score"],
        "opportunity_verdict": lifecycle_dict["opportunity_verdict"],
    }
    signal.metadata["pre_trade_guardrail_verdict"] = lifecycle_dict["gates"][5]["evidence"]
    return signal


def _decision(guardrail: dict, lifecycle) -> object:
    lifecycle = record_decision_compiler_result(lifecycle, decision_record=SimpleNamespace(decision_uuid="pre-compile"))
    lifecycle_dict = lifecycle_to_dict(lifecycle)
    return DecisionCompiler().compile(
        truth_frame=_truth_frame(),
        strategy_votes=[_vote()],
        additional_inputs={
            "pre_trade_guardrail_verdict": guardrail,
            "candidate_lifecycle": lifecycle_dict,
            "opportunity_scorecard": {
                "candidate_id": lifecycle_dict["candidate_id"],
                "raw_opportunity_score": lifecycle_dict["raw_opportunity_score"],
                "final_opportunity_score": lifecycle_dict["final_opportunity_score"],
                "opportunity_verdict": lifecycle_dict["opportunity_verdict"],
            },
        },
    )


def test_plausible_buy_gets_full_scorecard_when_safe_mode_blocks_execution():
    signal = _signal(confidence=0.90)
    guardrail = _guardrail(permitted=True)
    lifecycle = _build_lifecycle(
        signal=signal,
        guardrail=guardrail,
        latency_truth=_rest_latency_degraded(),
    )
    signal = _attach_lifecycle(signal, lifecycle)
    router = MagicMock()
    engine = _engine(router)
    engine._state.is_in_safe_mode = True
    engine._state.last_latency_truth = _rest_latency_degraded()

    admitted = engine.submit_signal(signal, Decimal("150.00"), is_attack=True)
    block = engine.get_last_admission_block_result()
    final_lifecycle = record_execution_result(lifecycle, submitted=admitted, execution_result=block)
    final_payload = lifecycle_to_dict(final_lifecycle)

    assert admitted is False
    assert block.reason_code == "SAFE_MODE_ACTIVE"
    assert block.candidate_lifecycle["raw_opportunity_score"] == 0.9
    assert final_payload["opportunity_verdict"] == GOOD_CANDIDATE_NOT_EXECUTABLE
    assert final_payload["execution_verdict"] == "BLOCKED"
    assert "SAFE_MODE_ACTIVE" in final_payload["execution_blocker_reason_codes"]
    assert final_payload["broker_post"] is False
    router.submit_order.assert_not_called()


def test_broker_order_latency_still_blocks_submission(tmp_path):
    router = MagicMock()
    risk_guard = HybridRiskGuard(
        initial_equity=10000.0,
        state_file=str(tmp_path / "risk_state.json"),
        backup_file=str(tmp_path / "risk_state.backup"),
        max_latency_ms=200.0,
    )
    engine = _engine(router, risk_guard=risk_guard)
    truth = engine._classify_latency_truth(
        {
            "source": "order_router.websocket_rtt",
            "latency_ms": 250.0,
            "ping_ns": T0_NS,
            "pong_ns": T0_NS + 250 * NS_PER_MS,
        },
        current_ns=T0_NS + NS_PER_SECOND,
    )
    engine._apply_latency_truth(truth)

    signal = _attach_lifecycle(_signal(), _build_lifecycle())
    admitted = engine.submit_signal(signal, Decimal("150.00"), is_attack=True)

    assert truth.status == "LAG_ABORT_ACTIVE"
    assert truth.source_scope == "websocket_rtt"
    assert engine.get_status()["is_in_safe_mode"] is True
    assert admitted is False
    assert engine.get_last_admission_block_result().reason_code == "SAFE_MODE_ACTIVE"
    router.submit_order.assert_not_called()


def test_backfill_candle_truth_is_observe_only_and_penalized_not_executable():
    candle = Candle(
        symbol="SOL/USD",
        exchange_ts_ns=T0_NS,
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=10.0,
        timeframe="1m",
        data_source_type="backfill",
        latest_batch_candle=True,
        candle_freshness_policy_ms=2000.0,
    )
    runtime = SimpleNamespace(last_order_book=None, last_candle=candle)
    truth = _classify_candle_execution_truth(
        symbol="SOL/USD",
        runtime=runtime,
        candle=candle,
        exchange_ts_ns=T0_NS,
        current_ns=T0_NS + 61 * NS_PER_SECOND,
    )
    lifecycle = _build_lifecycle(market_truth=truth)
    payload = lifecycle_to_dict(lifecycle)

    assert truth["executable_market_truth"] is False
    assert truth["data_health_reason_code"] == "DATA_BACKFILL_OBSERVE_ONLY"
    assert truth["candle_freshness_reason_code"] == "CANDLE_BATCH_BACKFILL_OBSERVE_ONLY"
    assert "freshness_penalty" in payload["penalties"]
    assert payload["gates"][1]["status"] == "PENALTY"


def test_module_declines_do_not_erase_other_strategy_score():
    lifecycle = _build_lifecycle(
        dispatch_evidence=(
            {
                "module": "SectorRotation",
                "status": "DECLINED",
                "reason_code": "OBSERVED_PAIR_STALE",
            },
            {
                "module": "ShadowFront",
                "status": "DECLINED",
                "reason_code": "WHALE_CONDITION_MISSING",
            },
            {
                "module": "GammaFront",
                "status": "PASS",
                "reason_code": "STRATEGY_SIGNAL_PRESENT",
            },
        )
    )
    payload = lifecycle_to_dict(lifecycle)

    assert payload["raw_opportunity_score"] == 0.9
    assert payload["module_declines"]["SectorRotation"]["reason_code"] == "OBSERVED_PAIR_STALE"
    assert payload["module_declines"]["ShadowFront"]["reason_code"] == "WHALE_CONDITION_MISSING"
    assert payload["module_contributions"]["GammaFront"]["status"] == "PASS"


def test_lifecycle_scorecard_carries_threshold_profile_and_decision_frame():
    profile = {
        "profile_name": "PAPER_EXPLORATION_ALPHA",
        "paper_only": True,
        "thresholds_by_name": {
            "minimum_opportunity_score": {
                "default_value": 0.45,
                "exploration_value": 0.25,
            }
        },
    }
    frame = {
        "frame_id": "frame_SOLUSD_1777948800_mts",
        "frame_output": "NO_TRADE",
        "frame_status": "BLOCK",
        "frame_reason_codes": ("DECISION_FRAME_NO_TRADE",),
    }
    lifecycle = _build_lifecycle(
        active_threshold_profile=profile,
        decision_frame=frame,
        guardrail=_guardrail(permitted=False, reason_codes=("DECISION_FRAME_NO_TRADE",)),
    )
    final_lifecycle = record_execution_result(
        lifecycle,
        submitted=False,
        execution_result=SimpleNamespace(reason_code="DECISION_FRAME_NO_TRADE"),
    )
    payload = lifecycle_to_dict(final_lifecycle)
    scorecard = opportunity_scorecard_from_lifecycle(final_lifecycle)

    assert payload["active_threshold_profile"]["profile_name"] == "PAPER_EXPLORATION_ALPHA"
    assert payload["decision_frame"]["frame_id"] == frame["frame_id"]
    assert scorecard["active_threshold_profile"]["paper_only"] is True
    assert scorecard["frame_id"] == frame["frame_id"]
    assert scorecard["frame_output"] == "NO_TRADE"
    assert scorecard["frame_status"] == "BLOCK"
    assert scorecard["frame_reason_codes"] == ("DECISION_FRAME_NO_TRADE",)
    assert scorecard["execution_verdict"] == "BLOCKED"
    assert "DECISION_FRAME_NO_TRADE" in scorecard["execution_blocker_reason_codes"]
    assert scorecard["broker_post"] is False


def test_quote_and_pre_trade_blocks_preserve_scorecard_before_router():
    guardrail = _guardrail(permitted=False, reason_codes=("QUOTE_SESSION_TRUTH_MISSING",))
    signal = _signal()
    lifecycle = _build_lifecycle(signal=signal, guardrail=guardrail)
    signal = _attach_lifecycle(signal, lifecycle)
    router = MagicMock()
    engine = _engine(router)

    admitted = engine.submit_signal(signal, Decimal("150.00"), is_attack=True)
    final_payload = lifecycle_to_dict(
        record_execution_result(
            lifecycle,
            submitted=admitted,
            execution_result=engine.get_last_admission_block_result(),
        )
    )

    assert admitted is False
    assert final_payload["opportunity_verdict"] == GOOD_CANDIDATE_NOT_EXECUTABLE
    assert "QUOTE_SESSION_TRUTH_MISSING" in final_payload["execution_blocker_reason_codes"]
    assert final_payload["broker_post"] is False
    router.submit_order.assert_not_called()


def test_sell_without_broker_position_is_broker_authority_blocker():
    guardrail = _guardrail(
        permitted=False,
        reason_codes=("ACTION_UNSUPPORTED", "SELL_AUTHORITY_MISSING"),
        side="sell",
    )
    lifecycle = _build_lifecycle(signal=_signal(side="sell"), guardrail=guardrail)
    payload = lifecycle_to_dict(lifecycle)
    pre_trade_gate = next(gate for gate in payload["gates"] if gate["gate"] == "pre_trade_guardrail_result")

    assert pre_trade_gate["status"] == "BLOCK"
    assert pre_trade_gate["classification"] == BROKER_AUTHORITY_BLOCKER
    assert payload["opportunity_verdict"] == GOOD_CANDIDATE_NOT_EXECUTABLE


def test_fresh_lawful_candidate_reaches_mocked_order_router_boundary_without_broker_post():
    guardrail = _guardrail(permitted=True)
    signal = _signal()
    lifecycle = _build_lifecycle(signal=signal, guardrail=guardrail)
    signal = _attach_lifecycle(signal, lifecycle)
    decision = _decision(guardrail, lifecycle)
    router = MagicMock()
    router.get_mid_price.return_value = Decimal("150.00")
    router.submit_order.return_value = None
    router.get_gateway_response.return_value = None
    engine = _engine(router)

    result = engine.execute_compiled_decision(
        decision,
        signal,
        current_price=Decimal("150.00"),
        is_attack=True,
    )
    final_payload = lifecycle_to_dict(
        record_execution_result(lifecycle, submitted=True, execution_result=result)
    )

    assert result.normalized_status == "pending"
    router.submit_order.assert_called_once()
    assert final_payload["broker_boundary_result"] == "ORDER_ROUTER_REACHED"
    assert final_payload["broker_post"] is False
