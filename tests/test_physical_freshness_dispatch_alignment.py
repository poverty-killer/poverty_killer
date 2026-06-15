from __future__ import annotations

import inspect
import types
from decimal import Decimal
from unittest.mock import MagicMock

import app.main_loop as main_loop_module
from app.brain.physical_validator import PhysicalValidator
from app.brain.signal_fusion import SignalFusion
from app.brain.toxicity_engine import ToxicityAlert, ToxicityRegime
from app.commander import Commander
from app.config import Config
from app.main_loop import MainLoop
from app.models.enums import RegimeType, SleeveType


T0_NS = 1_778_823_480_000_000_000


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
        reason="physical_freshness_dispatch_alignment_test",
    )


def _dispatch_loop() -> types.SimpleNamespace:
    loop = types.SimpleNamespace()
    loop.config = types.SimpleNamespace(broker_mode="paper")
    loop.commander = Commander()
    loop.strategy_router = MagicMock()
    loop.strategy_router.update_macro_state = MagicMock()
    loop.strategy_router.get_preferred_strategy = MagicMock(
        return_value=SleeveType.SECTOR_ROTATION
    )
    loop.strategy_router.get_eligible_strategies = MagicMock(
        return_value=[SleeveType.SECTOR_ROTATION]
    )
    loop.decision_compiler = MagicMock()
    loop.decision_compiler.compile = MagicMock(
        return_value=types.SimpleNamespace(
            decision_uuid="physical-freshness-dispatch-decision",
            decision_type="STRATEGY_VOTE",
        )
    )
    loop.execution_engine = MagicMock()
    loop.execution_engine.submit_signal = MagicMock(return_value=True)
    loop.execution_engine.get_status.return_value = {"last_latency_truth": {}}
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
    loop.signal_fusion = MagicMock()
    loop.signal_fusion._telemetry = {}
    loop._active_threshold_profile = MainLoop._active_threshold_profile.__get__(
        loop, MainLoop
    )
    loop._consume_observed_pair_sector_rotation = (
        MainLoop._consume_observed_pair_sector_rotation.__get__(loop, MainLoop)
    )
    loop._consume_observed_pair_liquidity_void = (
        MainLoop._consume_observed_pair_liquidity_void.__get__(loop, MainLoop)
    )
    loop._consume_observed_pair_moving_floor = (
        MainLoop._consume_observed_pair_moving_floor.__get__(loop, MainLoop)
    )
    loop._classify_shadow_front_decline = (
        MainLoop._classify_shadow_front_decline.__get__(loop, MainLoop)
    )
    loop._classify_sector_rotation_observed_pair = (
        MainLoop._classify_sector_rotation_observed_pair.__get__(loop, MainLoop)
    )
    loop._clear_stale_sector_rotation_observed_pair = (
        MainLoop._clear_stale_sector_rotation_observed_pair.__get__(loop, MainLoop)
    )
    loop._runtime_module_frame_evidence = (
        MainLoop._runtime_module_frame_evidence.__get__(loop, MainLoop)
    )
    loop._apply_signal_economic_metadata = (
        MainLoop._apply_signal_economic_metadata.__get__(loop, MainLoop)
    )
    loop._net_edge_frame_evidence = MainLoop._net_edge_frame_evidence
    loop._compile_scorecard_frame_no_submit = (
        MainLoop._compile_scorecard_frame_no_submit.__get__(loop, MainLoop)
    )
    loop._primary_no_submit_reason_code = MainLoop._primary_no_submit_reason_code
    return loop


def _assert_no_submit_truth_compile(loop) -> None:
    loop.execution_engine.submit_signal.assert_not_called()
    assert loop.decision_compiler.compile.call_count == 1
    _, compile_kwargs = loop.decision_compiler.compile.call_args
    assert compile_kwargs.get("strategy_votes") == []
    additional_inputs = compile_kwargs.get("additional_inputs") or {}
    assert additional_inputs.get("no_submit_reason_code")
    decision_frame = additional_inputs.get("decision_frame") or {}
    assert decision_frame.get("frame_output") == "NO_TRADE"
    assert decision_frame.get("frame_status") == "BLOCK"


def _runtime(
    *,
    signal_ts: int = T0_NS,
    vote_ts: int = T0_NS,
) -> types.SimpleNamespace:
    signal = types.SimpleNamespace(
        strategy="sector_rotation",
        symbol="ETH/USD",
        side="buy",
        confidence=0.8,
        quantity=0.5,
        price=None,
        exchange_ts_ns=signal_ts,
        reason="physical_freshness_dispatch_alignment_test",
        metadata={},
    )
    vote = types.SimpleNamespace(
        decision_uuid="physical-freshness-vote",
        timestamp_ns=vote_ts,
        confidence=Decimal("0.8"),
        risk_appetite=Decimal("0.5"),
        signal="buy",
        metadata={},
    )
    return types.SimpleNamespace(
        last_price=2500.0,
        shadow_front_strategy=MagicMock(),
        gamma_front_strategy=None,
        sector_rotation_strategy=MagicMock(),
        liquidity_void_strategy=None,
        last_sector_rotation_observed_signal=signal,
        last_sector_rotation_observed_vote=vote,
        last_liquidity_void_observed_signal=None,
        last_liquidity_void_observed_vote=None,
        last_liquidity_void_consumed_decision_uuid=None,
        toxicity_engine=MagicMock(),
        sentiment_velocity_engine=MagicMock(),
        last_tpe_signal=None,
    )


def _fusion_decision(ts_ns: int):
    return types.SimpleNamespace(
        exchange_ts_ns=ts_ns,
        attack_mode=False,
        preferred_sleeve="sector_rotation",
        sector_rotation_eligible=True,
        shadow_front_eligible=False,
    )


def test_admitted_market_event_physical_timestamp_is_fresh_for_same_clock_fusion():
    config = Config()
    fusion = SignalFusion(config=config)
    loop = types.SimpleNamespace(
        exchange="kraken",
        physical_validator=PhysicalValidator(),
        signal_fusion=fusion,
    )

    MainLoop._update_physical_freshness.__get__(loop, MainLoop)("ETH/USD", T0_NS)
    fusion.update_toxicity(_toxicity(T0_NS), T0_NS)

    decision = fusion.fuse(T0_NS)

    assert "Stale critical signal [physical]" not in decision.reason
    assert decision.preferred_sleeve is not None


def test_true_stale_physical_still_hard_vetoes_fusion():
    config = Config()
    fusion = SignalFusion(config=config)
    fusion.update_physical({"health_score": 0.80}, T0_NS - 31_000_000_000)
    fusion.update_toxicity(_toxicity(T0_NS), T0_NS)

    decision = fusion.fuse(T0_NS)

    assert decision.preferred_sleeve is None
    assert "VETO: Stale critical signal [physical]" in decision.reason


def test_sector_rotation_same_candle_pair_reaches_submit_when_fusion_not_vetoed():
    loop = _dispatch_loop()
    runtime = _runtime(signal_ts=T0_NS, vote_ts=T0_NS)

    MainLoop._dispatch_fusion.__get__(loop, MainLoop)(
        "ETH/USD",
        runtime,
        fusion=_fusion_decision(T0_NS),
        exchange_ts_ns=T0_NS,
    )

    loop.decision_compiler.compile.assert_called_once()
    loop.execution_engine.submit_signal.assert_called_once()
    assert loop._metrics.orders_submitted == 1


def test_same_candle_observed_pair_rule_remains_strict():
    loop = _dispatch_loop()
    runtime = _runtime(signal_ts=T0_NS - 1, vote_ts=T0_NS - 1)

    MainLoop._dispatch_fusion.__get__(loop, MainLoop)(
        "ETH/USD",
        runtime,
        fusion=_fusion_decision(T0_NS),
        exchange_ts_ns=T0_NS,
    )

    _assert_no_submit_truth_compile(loop)
    assert loop._metrics.orders_submitted == 0


def test_per_symbol_shadow_front_dispatch_uses_symbol_owned_regime():
    captured = {}

    class CapturingShadowFront:
        def update_price(
            self,
            *,
            price,
            timestamp_ns,
            capital_usd,
            kelly_multiplier,
            volatility,
            regime,
        ):
            captured["regime"] = regime
            return None

    runtime = types.SimpleNamespace(
        last_price=2500.0,
        current_volatility=0.05,
        shadow_front_strategy=CapturingShadowFront(),
        regime_detector=types.SimpleNamespace(
            get_current_regime=lambda: RegimeType.TRENDING_BEAR
        ),
    )
    loop = types.SimpleNamespace(
        _last_equity=20000.0,
        _current_regime=RegimeType.RANGING,
        commander=types.SimpleNamespace(get_kelly_multiplier=lambda: 0.4),
        position_sizing_engine=MagicMock(),
        decision_compiler=MagicMock(),
    )
    loop._get_dispatch_regime = MainLoop._get_dispatch_regime.__get__(loop, MainLoop)

    signal, vote = MainLoop._generate_signal_and_vote.__get__(loop, MainLoop)(
        "ETH/USD",
        runtime,
        T0_NS,
    )

    assert signal is None and vote is None
    assert captured["regime"] == RegimeType.TRENDING_BEAR


def test_main_loop_does_not_import_broker_adapter():
    assert "broker_adapter" not in inspect.getsource(main_loop_module)
