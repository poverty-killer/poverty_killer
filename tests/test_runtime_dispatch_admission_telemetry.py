from __future__ import annotations

import inspect
import logging
import types
from decimal import Decimal
from unittest.mock import MagicMock

import app.main_loop as main_loop_module
from app.commander import Commander
from app.main_loop import MainLoop, _log_dispatch_diag
from app.models.enums import SleeveType


LOGGER_NAME = "app.main_loop"
T0_NS = 1_777_948_800_000_000_000


def _signal(
    *,
    exchange_ts_ns: int = T0_NS,
    symbol: str = "ETH/USD",
) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        strategy="sector_rotation",
        symbol=symbol,
        side="buy",
        confidence=0.9,
        quantity=0.5,
        price=None,
        exchange_ts_ns=exchange_ts_ns,
        reason="dispatch_admission_diag_test",
        metadata={},
    )


def _vote(
    *,
    timestamp_ns: int = T0_NS,
    decision_uuid: str = "dispatch-diag-vote",
) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        decision_uuid=decision_uuid,
        timestamp_ns=timestamp_ns,
        confidence=Decimal("0.9"),
        risk_appetite=Decimal("0.5"),
        signal="buy",
        metadata={},
    )


def _fusion() -> types.SimpleNamespace:
    return types.SimpleNamespace(
        exchange_ts_ns=T0_NS,
        attack_mode=False,
        preferred_sleeve="shadow_front",
        sector_rotation_eligible=True,
        shadow_front_eligible=True,
    )


def _runtime(
    *,
    sector_signal: types.SimpleNamespace | None = None,
    sector_vote: types.SimpleNamespace | None = None,
) -> types.SimpleNamespace:
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


def _loop(
    *,
    preferred: SleeveType | None = SleeveType.SHADOW_FRONT,
    eligible: list[SleeveType] | None = None,
    broker_mode: str = "paper",
) -> types.SimpleNamespace:
    loop = types.SimpleNamespace()
    loop.config = types.SimpleNamespace(broker_mode=broker_mode)
    loop.commander = Commander()

    loop.strategy_router = MagicMock()
    loop.strategy_router.update_macro_state = MagicMock()
    loop.strategy_router.get_preferred_strategy = MagicMock(return_value=preferred)
    loop.strategy_router.get_eligible_strategies = MagicMock(
        return_value=eligible
        if eligible is not None
        else [SleeveType.SHADOW_FRONT, SleeveType.SECTOR_ROTATION]
    )

    loop.decision_compiler = MagicMock()
    loop.decision_compiler.compile = MagicMock(
        return_value=types.SimpleNamespace(
            decision_uuid="dispatch-diag-decision",
            decision_type="STRATEGY_VOTE",
        )
    )

    loop.execution_engine = MagicMock()
    loop.execution_engine.submit_signal = MagicMock(return_value=True)

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

    loop._consume_observed_pair_sector_rotation = (
        MainLoop._consume_observed_pair_sector_rotation.__get__(loop, MainLoop)
    )
    loop._consume_observed_pair_liquidity_void = (
        MainLoop._consume_observed_pair_liquidity_void.__get__(loop, MainLoop)
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
    return loop


def _dispatch(loop: types.SimpleNamespace, runtime: types.SimpleNamespace) -> None:
    MainLoop._dispatch_fusion.__get__(loop, MainLoop)(
        "ETH/USD",
        runtime,
        fusion=_fusion(),
        exchange_ts_ns=T0_NS,
    )


def test_dispatch_diag_helper_emits_shans_not_ready_reason(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)

    _log_dispatch_diag(
        "shans_not_ready",
        symbol="ETH/USD",
        exchange_ts_ns=T0_NS,
        submit_signal_called=False,
    )

    assert "reason_code=shans_not_ready" in caplog.text
    assert "submit_signal_called" in caplog.text


def test_preferred_sleeve_missing_diag_does_not_submit(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    loop = _loop(preferred=None)

    _dispatch(loop, _runtime())

    loop.execution_engine.submit_signal.assert_not_called()
    loop.decision_compiler.compile.assert_not_called()
    assert "reason_code=preferred_sleeve_missing" in caplog.text
    assert "submit_signal_called': False" in caplog.text


def test_observed_pair_missing_diag_does_not_submit(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    loop = _loop(
        preferred=SleeveType.SECTOR_ROTATION,
        eligible=[SleeveType.SECTOR_ROTATION],
    )

    _dispatch(loop, _runtime())

    loop.execution_engine.submit_signal.assert_not_called()
    loop.decision_compiler.compile.assert_not_called()
    assert "reason_code=observed_pair_missing" in caplog.text
    assert "reason_code=strategy_signal_missing" not in caplog.text


def test_observed_pair_stale_diag_does_not_submit(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    loop = _loop(
        preferred=SleeveType.SECTOR_ROTATION,
        eligible=[SleeveType.SECTOR_ROTATION],
    )
    runtime = _runtime(
        sector_signal=_signal(exchange_ts_ns=T0_NS - 60_000_000_000),
        sector_vote=_vote(timestamp_ns=T0_NS - 60_000_000_000),
    )

    _dispatch(loop, runtime)

    loop.execution_engine.submit_signal.assert_not_called()
    loop.decision_compiler.compile.assert_not_called()
    assert "reason_code=observed_pair_stale" in caplog.text
    assert "stale_cleared': True" in caplog.text
    assert runtime.last_sector_rotation_observed_signal is None
    assert runtime.last_sector_rotation_observed_vote is None
    assert "reason_code=strategy_signal_missing" not in caplog.text


def test_shadowfront_whale_decline_diag_does_not_submit(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    loop = _loop(
        preferred=SleeveType.SHADOW_FRONT,
        eligible=[SleeveType.SHADOW_FRONT],
    )
    runtime = _runtime()
    runtime.shadow_front_strategy._cooldown_until_ns = 0
    runtime.shadow_front_strategy._is_eligible = True
    runtime.shadow_front_strategy._toxicity_high = False
    runtime.shadow_front_strategy._last_whale_score = 0.10
    runtime.shadow_front_strategy.whale_threshold = 0.20
    runtime.shadow_front_strategy._last_whale_accumulating = False
    runtime.shadow_front_strategy._last_sentiment_velocity = 1.0
    runtime.shadow_front_strategy.sentiment_threshold = 0.1

    _dispatch(loop, runtime)

    loop.execution_engine.submit_signal.assert_not_called()
    loop.decision_compiler.compile.assert_not_called()
    assert "reason_code=shadowfront_declined_whale_condition" in caplog.text
    assert "eligibility_only': True" in caplog.text
    assert "reason_code=strategy_signal_missing" not in caplog.text


def test_shadowfront_sentiment_decline_diag_does_not_submit(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    loop = _loop(
        preferred=SleeveType.SHADOW_FRONT,
        eligible=[SleeveType.SHADOW_FRONT],
    )
    runtime = _runtime()
    runtime.shadow_front_strategy._cooldown_until_ns = 0
    runtime.shadow_front_strategy._is_eligible = True
    runtime.shadow_front_strategy._toxicity_high = False
    runtime.shadow_front_strategy._last_whale_score = 0.30
    runtime.shadow_front_strategy.whale_threshold = 0.20
    runtime.shadow_front_strategy._last_whale_accumulating = False
    runtime.shadow_front_strategy._last_sentiment_velocity = 0.05
    runtime.shadow_front_strategy.sentiment_threshold = 0.10

    _dispatch(loop, runtime)

    loop.execution_engine.submit_signal.assert_not_called()
    loop.decision_compiler.compile.assert_not_called()
    assert "reason_code=shadowfront_declined_sentiment_condition" in caplog.text
    assert "executable_signal_present': False" in caplog.text
    assert "reason_code=strategy_signal_missing" not in caplog.text


def test_submit_signal_called_diag_preserves_success_behavior(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    loop = _loop()
    signal = _signal()
    vote = _vote()

    _dispatch(loop, _runtime(sector_signal=signal, sector_vote=vote))

    loop.decision_compiler.compile.assert_called_once()
    loop.execution_engine.submit_signal.assert_called_once()
    assert loop._metrics.compilation_cycles == 1
    assert loop._metrics.orders_submitted == 1
    assert signal.metadata["decision_uuid"] == "dispatch-diag-decision"
    assert "reason_code=decision_compile_attempted" in caplog.text
    assert "reason_code=submit_signal_called" in caplog.text
    assert "submitted': True" in caplog.text


def test_main_loop_does_not_import_broker_adapter():
    assert "broker_adapter" not in inspect.getsource(main_loop_module)
