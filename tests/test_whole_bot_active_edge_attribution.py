from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.brain.signal_fusion import SignalFusion
from app.commander import Commander
from app.core.decision_compiler import DecisionCompiler
from app.core.whole_bot_attribution import (
    build_runtime_edge_attribution,
    degraded_market_fallback_signature,
)
from app.execution.engine import ExecutionEngine
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
from app.models.signals import StrategySignal


T0_NS = 1_777_948_800_000_000_000


def _truth_frame() -> TruthFrame:
    return TruthFrame(
        truth_frame_id="whole-bot-attribution-truth-frame",
        timestamp_ns=T0_NS,
        exchange_truth=ExchangeTruth(venue="alpaca", exchange_ts_ns=T0_NS),
        execution_truth=ExecutionTruth(last_reconciliation_ts_ns=T0_NS),
        portfolio_truth=PortfolioTruth(last_update_ts_ns=T0_NS),
        strategy_truth=StrategyTruth(last_update_ts_ns=T0_NS),
        risk_truth=RiskTruth(),
        status=TruthStatus.RECONCILED,
    )


def _vote() -> StrategyVote:
    return StrategyVote(
        vote_id="whole-bot-attribution-vote",
        decision_uuid="whole-bot-attribution-decision",
        strategy_id=StrategyID.SHADOW_FRONT,
        timestamp_ns=T0_NS,
        signal=SignalType.BUY,
        confidence=Decimal("0.80"),
        expected_move_bps=Decimal("25"),
        expected_duration_ns=60_000_000_000,
        risk_appetite=Decimal("0.40"),
    )


def _guardrail(route_permitted: bool = True) -> dict:
    return {
        "verdict": "ALLOW" if route_permitted else "BLOCK",
        "route_permitted": route_permitted,
        "mutation_permitted": route_permitted,
        "reason_codes": ("PRE_TRADE_GUARDRAILS_ALLOW",) if route_permitted else ("QUOTE_SESSION_TRUTH_MISSING",),
        "symbol": "AAPL",
        "asset_class": "equity",
        "side": "buy",
        "order_type": "limit",
        "time_in_force": "DAY",
        "requested_notional": "15.00",
        "capability_identity": {
            "venue_id": "alpaca",
            "portal_name": "alpaca_paper",
            "environment": "paper",
            "asset_class": "equity",
            "symbol": "AAPL",
            "execution_adapter": "alpaca_paper_rest",
        },
        "module_evidence": [
            {
                "module": "NetEdgeGovernor",
                "status": "advisory",
                "reason_code": "NET_EDGE_MISSING_TRUTH",
                "summary": "Net edge inputs unavailable; no profitability invented.",
            },
            {
                "module": "TradeEfficiencyGovernor",
                "status": "advisory",
                "reason_code": "TRADE_EFFICIENCY_MISSING_TRUTH",
                "summary": "Efficiency inputs unavailable; no slippage invented.",
            },
        ],
    }


def _signal(edge_attribution: dict | None = None) -> StrategySignal:
    metadata = {
        "expected_move": "0.02",
        "asset_class": "equity",
        "venue_id": "alpaca",
        "portal_name": "alpaca_paper",
        "environment": "paper",
        "execution_adapter": "alpaca_paper_rest",
        "order_type": "limit",
        "time_in_force": "DAY",
        "requested_notional": "15.00",
        "pre_trade_guardrail_verdict": _guardrail(True),
    }
    if edge_attribution is not None:
        metadata["edge_attribution"] = edge_attribution
    return StrategySignal(
        strategy="shadow_front",
        symbol="AAPL",
        side="buy",
        confidence=0.80,
        quantity=0.10,
        price=150.00,
        exchange_ts_ns=T0_NS,
        reason="whole_bot_attribution_test",
        metadata=metadata,
    )


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


def test_signal_fusion_carries_missing_feed_truth_instead_of_silent_drop():
    fusion = SignalFusion(SimpleNamespace(
        symbol="ETH/USD",
        strategies=SimpleNamespace(sector_rotation_ranging_eligible=False),
    ))
    fusion.update_physical({"health_score": 0.90}, T0_NS)
    fusion.update_toxicity(
        SimpleNamespace(toxicity_score=0.10, regime=SimpleNamespace(value=0)),
        T0_NS,
    )

    decision = fusion.fuse(T0_NS)
    attribution = fusion.get_fusion_telemetry()["edge_attribution"]

    assert decision is not None
    assert attribution["WhaleFlow"]["status"] == "MISSING_FEED_TRUTH"
    assert attribution["RegimeDetector"]["status"] == "MISSING_FEED_TRUTH"
    assert attribution["InsiderSignalEngine"]["reason"].startswith("MISSING_NONCRITICAL_SIGNAL")
    assert attribution["PhysicalValidator"]["status"] == "ACTIVE_TRUTH_CHECK"
    assert attribution["Toxicity"]["status"] == "ACTIVE_TRUTH_CHECK"


def test_degraded_fallback_uses_only_lawful_live_market_truth_without_fake_economics():
    signature = degraded_market_fallback_signature(
        module_name="MovingFloor",
        category="strategy_alpha",
        live_market_truth={"current_price": "150.00", "bid": "149.99", "ask": "150.01", "spread_bps": "1.3"},
        timestamp=T0_NS,
    )
    encoded = json.dumps(signature).lower()

    assert signature["status"] == "DEGRADED_FALLBACK"
    assert signature["effect"] == "ADVISORY"
    assert "lawful_live_market_truth" in signature["input_source"]
    assert "fake" not in encoded
    assert "pnl" not in encoded
    assert "profitability" not in encoded


def test_decision_record_carries_whole_bot_edge_attribution_metadata():
    attribution = build_runtime_edge_attribution(
        timestamp_ns=T0_NS,
        symbol="AAPL",
        signal=_signal(),
        signal_metadata={"current_price": "150.00", "spread_bps": "2.0", "quote_fresh": True},
        fusion_attribution={"WhaleFlow": {"module_name": "WhaleFlow", "status": "MISSING_FEED_TRUTH"}},
        guardrail_verdict=_guardrail(True),
        truth_frame=_truth_frame(),
        shadow_read_only=True,
        broker_mutation_counts={"POST": 0, "PATCH": 0, "DELETE": 0, "cancel": 0, "replace": 0, "sell": 0, "rebalance": 0},
    )

    record = DecisionCompiler().compile(
        truth_frame=_truth_frame(),
        strategy_votes=[_vote()],
        additional_inputs={"pre_trade_guardrail_verdict": _guardrail(True), "edge_attribution": attribution},
    )

    assert record.metadata["edge_attribution"] == attribution
    assert record.metadata["edge_attribution_module_count"] >= 10
    assert record.outputs["additional"]["edge_attribution"]["PreTradeGuardrails"]["status"] == "ACTIVE_GUARDRAIL"
    assert record.outputs["additional"]["edge_attribution"]["ShadowReadOnlyGate"]["effect"] == "NO_MUTATION_BOUNDARY"


def test_runtime_attribution_signs_strategy_intelligence_portal_governors_truth_and_shadow_gate():
    attribution = build_runtime_edge_attribution(
        timestamp_ns=T0_NS,
        symbol="AAPL",
        signal=_signal(),
        signal_metadata={"current_price": "150.00", "spread_bps": "2.0", "quote_fresh": True},
        fusion_attribution={
            "WhaleFlow": {
                "module_name": "WhaleFlow",
                "category": "intelligence_node",
                "status": "MISSING_FEED_TRUTH",
                "input_source": "fusion_cache",
                "output_summary": "missing",
                "effect": "ADVISORY",
                "reason": "MISSING_NONCRITICAL_SIGNAL:whale_flow",
                "timestamp": T0_NS,
            }
        },
        guardrail_verdict=_guardrail(True),
        truth_frame=_truth_frame(),
        shadow_read_only=True,
        broker_mutation_counts={"POST": 0, "PATCH": 0, "DELETE": 0, "cancel": 0, "replace": 0, "sell": 0, "rebalance": 0},
    )

    assert attribution["MovingFloor"]["status"] == "DEGRADED_FALLBACK"
    assert attribution["ShadowFront"]["status"] == "ACTIVE_NATIVE_SIGNAL"
    assert attribution["WhaleFlow"]["status"] == "MISSING_FEED_TRUTH"
    assert attribution["InsiderSignalEngine"]["reason"] == "MISSING_FEED_TRUTH"
    assert attribution["NetEdgeGovernor"]["reason"] == "NET_EDGE_MISSING_TRUTH"
    assert attribution["TradeEfficiencyGovernor"]["reason"] == "TRADE_EFFICIENCY_MISSING_TRUTH"
    assert attribution["PreTradeGuardrails"]["effect"] == "APPROVED"
    assert attribution["TruthKernel"]["status"] == "ACTIVE_TRUTH_CHECK"
    assert attribution["InvariantChecker"]["reason"] == "INVARIANT_SNAPSHOT_MISSING_IN_DISPATCH"
    assert attribution["ShadowReadOnlyGate"]["reason"] == "SHADOW_READ_ONLY_BLOCKED_BROKER_MUTATION"


def test_shadow_block_records_whole_bot_attribution_and_zero_mutation_counts():
    attribution = build_runtime_edge_attribution(
        timestamp_ns=T0_NS,
        symbol="AAPL",
        signal=_signal(),
        signal_metadata={"current_price": "150.00", "spread_bps": "2.0"},
        guardrail_verdict=_guardrail(True),
        truth_frame=_truth_frame(),
        shadow_read_only=True,
        broker_mutation_counts={"POST": 0, "PATCH": 0, "DELETE": 0, "cancel": 0, "replace": 0, "sell": 0, "rebalance": 0},
    )
    router = MagicMock()
    router.get_mid_price.return_value = Decimal("150.00")
    engine = ExecutionEngine(
        commander=Commander(),
        risk_guard=_risk_guard(),
        order_router=router,
        masking_layer=MagicMock(),
        signal_ttl_ms=1000.0,
        shadow_read_only=True,
    )
    engine._state.is_running = True
    engine._state.last_regime = "neutral"

    admitted = engine.submit_signal(
        _signal(edge_attribution=attribution),
        current_price=Decimal("150.00"),
        is_attack=True,
    )
    event = engine.get_shadow_read_only_events()[0]

    assert admitted is False
    assert event["edge_attribution"]["ShadowReadOnlyGate"]["effect"] == "NO_MUTATION_BOUNDARY"
    assert event["broker_mutation_counts"]["POST"] == 0
    assert event["broker_post_patch_delete_count"] == 0
    router.submit_order.assert_not_called()


def test_missing_truth_fails_closed_in_guardrail_signature():
    attribution = build_runtime_edge_attribution(
        timestamp_ns=T0_NS,
        symbol="AAPL",
        signal=_signal(),
        guardrail_verdict=_guardrail(False),
        truth_frame=None,
        shadow_read_only=True,
        broker_mutation_counts={"POST": 0},
    )

    assert attribution["PreTradeGuardrails"]["effect"] == "BLOCKED"
    assert attribution["TruthKernel"]["status"] == "MISSING_FEED_TRUTH"
    assert attribution["CapabilityRegistry"]["reason"] == "CAPABILITY_IDENTITY_ATTACHED"
