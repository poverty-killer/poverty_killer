from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.commander import Commander
from app.config import Config
from app.core.decision_frame import (
    AUTHORITY_ALPHA,
    AUTHORITY_RISK,
    BLOCK,
    FRAME_OUTPUT_BUY,
    FRAME_OUTPUT_NO_TRADE,
    MISSING_TRUTH,
    ModuleEvidence,
    SIGNAL_BUY,
    build_decision_frame,
    resolve_active_threshold_profile,
)
from app.execution.engine import ExecutionEngine
from app.main_loop import MainLoop, _build_pre_trade_guardrail_verdict
from app.models.signals import StrategySignal
from app.risk.guard import HybridRiskGuard
from app.strategies.moving_floor import TopologicalMovingFloor


T0_NS = 1_777_948_800_000_000_000


def _risk_guard() -> MagicMock:
    risk_guard = MagicMock(spec=HybridRiskGuard)
    risk_guard.can_trade.return_value = True
    risk_guard.is_vol_fuse_triggered.return_value = False
    risk_guard.register_recalibrate_callback = MagicMock()
    risk_guard.register_emergency_callback = MagicMock()
    risk_guard.register_zombie_callback = MagicMock()
    risk_guard.register_lag_callback = MagicMock()
    risk_guard.register_vol_fuse_callback = MagicMock()
    risk_guard.record_fees = MagicMock()
    return risk_guard


def _engine() -> ExecutionEngine:
    masking = MagicMock()
    masking.mask_order.return_value = SimpleNamespace(masked_size=Decimal("0.10"))
    engine = ExecutionEngine(
        commander=Commander(),
        risk_guard=_risk_guard(),
        order_router=MagicMock(),
        masking_layer=masking,
        signal_ttl_ms=300_000.0,
    )
    engine._state.is_running = True
    engine._state.last_regime = "neutral"
    return engine


def _signal(*, expected_move_bps: str | None, confidence: float = 0.80) -> StrategySignal:
    metadata = {
        "spread_bps": "4.0",
        "fee_bps": "6.0",
        "slippage_bps": "8.0",
        "latency_drag_bps": "4.0",
        "partial_fill_drag_bps": "4.0",
        "exit_execution_cost_bps": "4.0",
    }
    if expected_move_bps is not None:
        metadata["expected_move_bps"] = expected_move_bps
    return StrategySignal(
        strategy="sector_rotation",
        symbol="ETH/USD",
        side="buy",
        confidence=confidence,
        quantity=0.10,
        price=2500.0,
        exchange_ts_ns=T0_NS,
        reason="full_opportunity_engine_unlock_test",
        metadata=metadata,
    )


def _snapshot() -> dict:
    return {
        "snapshot_id": "mts_full_unlock",
        "symbol": "ETH/USD",
        "candle_id": T0_NS,
        "snapshot_status": "PASS",
        "executable_market_truth": True,
        "source_type": "runtime",
    }


class _Book:
    spread = 1.0

    def __init__(self, bid_depth: str = "40", ask_depth: str = "160") -> None:
        self._bid_depth = Decimal(bid_depth)
        self._ask_depth = Decimal(ask_depth)

    def depth_at_levels(self, levels: int):
        return self._bid_depth, self._ask_depth


def _candle(price: str, ts: int, *, high: str | None = None, low: str | None = None) -> SimpleNamespace:
    close = Decimal(price)
    return SimpleNamespace(
        symbol="ETH/USD",
        open=float(close),
        high=float(Decimal(high) if high is not None else close),
        low=float(Decimal(low) if low is not None else close),
        close=float(close),
        volume=100.0,
        exchange_ts_ns=ts,
    )


def _moving_floor_loop(position: dict | None) -> SimpleNamespace:
    loop = SimpleNamespace()
    loop._last_risk_state = {}
    loop._current_regime = "neutral"
    loop.decision_compiler = SimpleNamespace(reserve_decision_uuid=lambda: "moving-floor-decision")
    loop._get_dispatch_regime = MainLoop._get_dispatch_regime.__get__(loop, MainLoop)
    loop._broker_position_truth = MagicMock(
        return_value=(
            position,
            {
                "status": "PASS",
                "reason_code": "BROKER_POSITION_TRUTH_READ_ONLY",
                "source": "unit_test_broker_truth",
                "read_only": True,
            },
        )
    )
    loop._moving_floor_toxicity_level = MainLoop._moving_floor_toxicity_level
    loop._moving_floor_book_integrity = MainLoop._moving_floor_book_integrity
    loop._moving_floor_risk_action = MainLoop._moving_floor_risk_action.__get__(loop, MainLoop)
    loop._build_moving_floor_signal = MainLoop._build_moving_floor_signal.__get__(loop, MainLoop)
    loop._observe_moving_floor = MainLoop._observe_moving_floor.__get__(loop, MainLoop)
    return loop


def _moving_floor_runtime() -> SimpleNamespace:
    runtime = SimpleNamespace(
        last_order_book=_Book(),
        moving_floor_strategy=TopologicalMovingFloor(),
        last_moving_floor_observed_signal=None,
        last_moving_floor_observed_vote=None,
        last_moving_floor_evidence=None,
        regime_detector=None,
        toxicity_engine=None,
    )
    runtime.record_observed_signal = (
        lambda sleeve, signal: setattr(runtime, "last_moving_floor_observed_signal", signal)
    )
    runtime.record_observed_vote = (
        lambda sleeve, vote: setattr(runtime, "last_moving_floor_observed_vote", vote)
    )

    def reset(reason: str = "MOVING_FLOOR_RESET") -> None:
        runtime.moving_floor_strategy = TopologicalMovingFloor()
        runtime.last_moving_floor_observed_signal = None
        runtime.last_moving_floor_observed_vote = None
        runtime.last_moving_floor_evidence = {
            "module": "MovingFloor",
            "status": "NOT_APPLICABLE",
            "reason_code": reason,
        }

    runtime.reset_moving_floor = reset
    return runtime


def test_config_env_explicitly_activates_paper_exploration_profile(monkeypatch):
    monkeypatch.setenv("POVERTY_KILLER_PAPER_EXPLORATION_ALPHA", "1")
    config = Config.from_env()
    config.broker_mode = "paper"
    config.alpaca_paper = True

    profile = resolve_active_threshold_profile(config)

    assert profile["profile_name"] == "PAPER_EXPLORATION_ALPHA"
    assert profile["enabled"] is True
    assert profile["paper_only"] is True


def test_decision_frame_alpha_gaps_are_evidence_not_candidate_erasers():
    frame = build_decision_frame(
        symbol="ETH/USD",
        snapshot=_snapshot(),
        created_at_ns=T0_NS,
        timeout_ns=60_000_000_000,
        active_threshold_profile=resolve_active_threshold_profile(Config()),
        module_evidence=(
            ModuleEvidence(
                module_name="SectorRotation",
                authority_class=AUTHORITY_ALPHA,
                status="CONTRIBUTED",
                signal=SIGNAL_BUY,
                confidence=Decimal("0.72"),
                snapshot_id="mts_full_unlock",
                candle_id=T0_NS,
            ),
            ModuleEvidence(
                module_name="ShansCurve",
                authority_class=AUTHORITY_ALPHA,
                status=MISSING_TRUTH,
                reason_codes=("shans_not_ready",),
                snapshot_id="mts_full_unlock",
                candle_id=T0_NS,
            ),
            ModuleEvidence(
                module_name="ShadowFront",
                authority_class=AUTHORITY_ALPHA,
                status="DECLINED",
                reason_codes=("shadowfront_declined_whale_condition",),
                snapshot_id="mts_full_unlock",
                candle_id=T0_NS,
            ),
        ),
    ).to_dict()

    assert frame["frame_status"] == "PASS"
    assert frame["frame_output"] == FRAME_OUTPUT_BUY
    assert frame["module_evidence"]["ShansCurve"]["status"] == MISSING_TRUTH
    assert frame["module_evidence"]["ShadowFront"]["status"] == "DECLINED"


def test_decision_frame_netedge_risk_block_prevents_buy_output():
    frame = build_decision_frame(
        symbol="ETH/USD",
        snapshot=_snapshot(),
        created_at_ns=T0_NS,
        timeout_ns=60_000_000_000,
        active_threshold_profile=resolve_active_threshold_profile(Config()),
        module_evidence=(
            ModuleEvidence(
                module_name="SectorRotation",
                authority_class=AUTHORITY_ALPHA,
                status="CONTRIBUTED",
                signal=SIGNAL_BUY,
                confidence=Decimal("0.90"),
                snapshot_id="mts_full_unlock",
                candle_id=T0_NS,
            ),
            ModuleEvidence(
                module_name="NetEdgeGovernor",
                authority_class=AUTHORITY_RISK,
                status=BLOCK,
                reason_codes=("NON_POSITIVE_NET_EDGE",),
                snapshot_id="mts_full_unlock",
                candle_id=T0_NS,
            ),
        ),
    ).to_dict()

    assert frame["frame_status"] == "BLOCK"
    assert frame["frame_output"] == FRAME_OUTPUT_NO_TRADE
    assert "NON_POSITIVE_NET_EDGE" in frame["frame_reason_codes"]


def test_execution_engine_netedge_allows_positive_modeled_edge():
    engine = _engine()
    signal = _signal(expected_move_bps="200", confidence=0.90)

    evaluation = engine.evaluate_signal_net_edge(signal, current_ns=T0_NS)

    assert evaluation["admissible"] is True
    assert evaluation["decision"] == "ALLOW"
    assert evaluation["reason_code"] == "ECONOMICALLY_ADMISSIBLE"
    assert Decimal(evaluation["net_adversarial_edge"]) > Decimal("0")


def test_execution_engine_netedge_blocks_negative_and_unknown_edge():
    engine = _engine()

    negative = engine.evaluate_signal_net_edge(
        _signal(expected_move_bps="10", confidence=0.50),
        current_ns=T0_NS,
    )
    unknown = engine.evaluate_signal_net_edge(
        _signal(expected_move_bps=None, confidence=0.90),
        current_ns=T0_NS,
    )

    assert negative["admissible"] is False
    assert negative["reason_code"] == "NON_POSITIVE_NET_EDGE"
    assert unknown["admissible"] is False
    assert unknown["reason_code"] == "NET_EDGE_MISSING_TRUTH"


def test_moving_floor_flat_runtime_is_not_broker_intent():
    loop = _moving_floor_loop(position=None)
    runtime = _moving_floor_runtime()

    loop._observe_moving_floor(
        "ETH/USD",
        runtime,
        _candle("100", T0_NS),
        _snapshot(),
    )

    assert runtime.last_moving_floor_observed_signal is None
    assert runtime.last_moving_floor_observed_vote is None
    assert runtime.last_moving_floor_evidence["status"] == "NOT_APPLICABLE"
    assert runtime.last_moving_floor_evidence["reason_code"] == "MOVING_FLOOR_FLAT_NO_POSITION"


def test_moving_floor_breach_builds_broker_position_backed_sell_to_close_candidate():
    position = {
        "symbol": "ETHUSD",
        "quantity": "0.25",
        "average_entry_price": "80",
        "broker_position_backed": True,
    }
    loop = _moving_floor_loop(position=position)
    runtime = _moving_floor_runtime()
    snapshot = _snapshot()

    loop._observe_moving_floor(
        "ETH/USD",
        runtime,
        _candle("100", T0_NS, high="100.20", low="100.00"),
        snapshot,
    )
    loop._observe_moving_floor(
        "ETH/USD",
        runtime,
        _candle("110", T0_NS + 60_000_000_000, high="112.00", low="111.80"),
        snapshot,
    )
    loop._observe_moving_floor(
        "ETH/USD",
        runtime,
        _candle("107", T0_NS + 120_000_000_000, high="107.00", low="106.80"),
        snapshot,
    )

    signal = runtime.last_moving_floor_observed_signal
    vote = runtime.last_moving_floor_observed_vote
    assert signal is not None
    assert vote is not None
    assert signal.side == "sell"
    assert signal.metadata["protective_only"] is True
    assert signal.metadata["requires_existing_position"] is True
    assert signal.metadata["broker_position_backed"] is True
    assert signal.metadata["fresh_entry_authorized"] is False
    assert signal.metadata["action"] == "sell_to_close"
    assert signal.metadata["execution_action"] == "sell_to_close"
    assert signal.metadata["order_action"] == "sell_to_close"
    assert signal.metadata["position_lifecycle_transition"]["target_state"] == "FLAT"
    assert signal.metadata["position_lifecycle_transition"]["cooldown_state"] == "PENDING_FILL"
    assert (
        signal.metadata["position_lifecycle_transition"]["round_trip_realization"]
        == "AT_CLOSE_ON_SELL_TO_CLOSE_FILL"
    )
    assert signal.metadata["moving_floor_exit_context"]["at_close_realization_expected"] is True
    assert (
        signal.metadata["moving_floor_exit_context"]["net_edge_realization_label"]
        == "AT_CLOSE_ACTUAL_ROUND_TRIP"
    )
    floor_evidence = signal.metadata["moving_floor_exit_context"]["volatility_floor"]
    assert floor_evidence["method"] == "ATR_CHANDELIER_AUGMENT"
    assert floor_evidence["topological_obi_preserved"] is True
    assert floor_evidence["one_directional_ratchet"] is True
    assert floor_evidence["atr_source"] == "tick_atr"
    assert Decimal(floor_evidence["chandelier_floor"]) > Decimal("0")
    assert Decimal(signal.metadata["expected_move_bps"]) > Decimal("0")
    assert (
        runtime.last_moving_floor_evidence["evidence"]["position_lifecycle_transition"]
        == "BROKER_POSITION_BACKED_SELL_TO_CLOSE_PENDING_FLAT_COOLDOWN"
    )
    assert runtime.last_moving_floor_evidence["evidence"]["round_trip_realization"] == "AT_CLOSE_ON_BROKER_ACK"

    runtime_for_guardrail = SimpleNamespace(last_price=107.0)
    verdict = _build_pre_trade_guardrail_verdict(
        config=Config(
            broker_mode="paper",
            active_markets=["crypto"],
            symbol_universe=["ETH/USD"],
            portal_selection_policy="explicit_preferred_venue",
            preferred_trading_portal="alpaca_paper",
        ),
        symbol="ETH/USD",
        signal=signal,
        runtime=runtime_for_guardrail,
        is_attack=False,
    )

    assert signal.metadata["sell_intent_classification"] == "SELL_EXIT_EXISTING_BROKER_POSITION"
    assert signal.metadata["execution_action"] == "sell_to_close"
    assert verdict["action"] == "sell_to_close"
    assert "SELL_AUTHORITY_MISSING" not in verdict["reason_codes"]
