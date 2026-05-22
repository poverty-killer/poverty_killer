from __future__ import annotations

import inspect
import logging
import threading
import types
from decimal import Decimal
from unittest.mock import MagicMock

import app.main_loop as main_loop_module
from app.config import Config
from app.commander import Commander
from app.main_loop import MainLoop, _log_dispatch_diag
from app.brain.data_validator import DataContinuityValidator
from app.models import Candle
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
    symbol: str = "ETH/USD",
) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        decision_uuid=decision_uuid,
        timestamp_ns=timestamp_ns,
        confidence=Decimal("0.9"),
        risk_appetite=Decimal("0.5"),
        signal="buy",
        metadata={"symbol": symbol},
    )


def _fusion() -> types.SimpleNamespace:
    return types.SimpleNamespace(
        exchange_ts_ns=T0_NS,
        attack_mode=False,
        preferred_sleeve="shadow_front",
        sector_rotation_eligible=True,
        shadow_front_eligible=True,
    )


def _candle(
    *,
    exchange_ts_ns: int = T0_NS,
    symbol: str = "ETH/USD",
    close: float = 2500.0,
    volume: float = 100.0,
) -> Candle:
    return Candle(
        symbol=symbol,
        exchange_ts_ns=exchange_ts_ns,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=volume,
        timeframe="1m",
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


def _observe_loop() -> types.SimpleNamespace:
    loop = types.SimpleNamespace()
    loop._observe_sector_rotation = MainLoop._observe_sector_rotation.__get__(
        loop, MainLoop
    )
    loop._log_observed_signal = MainLoop._log_observed_signal.__get__(
        loop, MainLoop
    )
    loop._log_observed_vote = MainLoop._log_observed_vote.__get__(loop, MainLoop)
    loop.execution_engine = MagicMock()
    return loop


def _observe_runtime(sector_strategy) -> types.SimpleNamespace:
    runtime = _runtime()
    runtime.sector_rotation_strategy = sector_strategy
    runtime.sentiment_velocity_engine = None
    runtime.toxicity_engine = None

    def record_observed_signal(sleeve_name: str, signal) -> None:
        assert sleeve_name == "sector_rotation"
        runtime.last_sector_rotation_observed_signal = signal

    def record_observed_vote(sleeve_name: str, vote) -> None:
        assert sleeve_name == "sector_rotation"
        runtime.last_sector_rotation_observed_vote = vote

    runtime.record_observed_signal = record_observed_signal
    runtime.record_observed_vote = record_observed_vote
    return runtime


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


class _NoSignalSectorRotation:
    def update_macro_state(self, macro_signal) -> None:
        return None

    def update_toxicity(self, toxicity_alert) -> None:
        return None

    def update_candle(self, *, price: float, volume: float, timestamp_ns: int):
        return None

    def update_price(self, *, price: float, timestamp_ns: int):
        return None

    def get_last_decline_reason(self) -> str:
        return "volume_zscore_below_threshold"

    def get_last_decline_detail(self) -> dict:
        return {"volume_zscore": 0.25, "threshold": 1.5}


class _SignalSectorRotation:
    def __init__(self, signal) -> None:
        self.signal = signal

    def update_macro_state(self, macro_signal) -> None:
        return None

    def update_toxicity(self, toxicity_alert) -> None:
        return None

    def update_candle(self, *, price: float, volume: float, timestamp_ns: int):
        return self.signal

    def update_price(self, *, price: float, timestamp_ns: int):
        return None

    def get_last_decline_reason(self):
        return None

    def get_last_decline_detail(self) -> dict:
        return {}


def test_sector_rotation_no_signal_diag_does_not_submit(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    loop = _observe_loop()
    runtime = _observe_runtime(_NoSignalSectorRotation())

    loop._observe_sector_rotation("ETH/USD", runtime, _candle())

    loop.execution_engine.submit_signal.assert_not_called()
    assert runtime.last_sector_rotation_observed_signal is None
    assert runtime.last_sector_rotation_observed_vote is None
    assert "[SECTOR_ROTATION_DIAG]" in caplog.text
    assert "reason_code=volume_zscore_below_threshold" in caplog.text
    assert "candle_ts_ns=1777948800000000000" in caplog.text


def test_sector_rotation_observed_pair_storage_remains_unchanged(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    signal = _signal(exchange_ts_ns=T0_NS)
    loop = _observe_loop()
    runtime = _observe_runtime(_SignalSectorRotation(signal))

    loop._observe_sector_rotation("ETH/USD", runtime, _candle())

    loop.execution_engine.submit_signal.assert_not_called()
    assert runtime.last_sector_rotation_observed_signal is signal
    assert runtime.last_sector_rotation_observed_vote is not None
    assert runtime.last_sector_rotation_observed_vote.timestamp_ns == T0_NS
    assert "reason_code=observed_pair_stored" in caplog.text


def test_sector_rotation_vote_adapter_failure_does_not_create_half_pair(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    signal = _signal(exchange_ts_ns=T0_NS)
    loop = _observe_loop()
    runtime = _observe_runtime(_SignalSectorRotation(signal))

    def raise_adapter(*args, **kwargs):
        raise ValueError("adapter failed")

    monkeypatch.setattr(
        main_loop_module,
        "adapt_sector_rotation_to_vote",
        raise_adapter,
    )

    loop._observe_sector_rotation("ETH/USD", runtime, _candle())

    loop.execution_engine.submit_signal.assert_not_called()
    assert runtime.last_sector_rotation_observed_signal is None
    assert runtime.last_sector_rotation_observed_vote is None
    assert "reason_code=vote_adaptation_failed" in caplog.text


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
    assert "reason_code=OBSERVED_SIGNAL_MISSING" in caplog.text
    assert "observed_signal_present': False" in caplog.text
    assert "observed_vote_present': False" in caplog.text
    assert "reason_code=strategy_signal_missing" not in caplog.text


def test_observed_vote_missing_diag_does_not_submit(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    loop = _loop(
        preferred=SleeveType.SECTOR_ROTATION,
        eligible=[SleeveType.SECTOR_ROTATION],
    )
    runtime = _runtime(sector_signal=_signal(exchange_ts_ns=T0_NS))

    _dispatch(loop, runtime)

    loop.execution_engine.submit_signal.assert_not_called()
    loop.decision_compiler.compile.assert_not_called()
    assert "reason_code=OBSERVED_VOTE_MISSING" in caplog.text
    assert "observed_signal_present': True" in caplog.text
    assert "observed_vote_present': False" in caplog.text
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
    assert "reason_code=OBSERVED_PAIR_STALE" in caplog.text
    assert "stale_cleared': True" in caplog.text
    assert "stale_age_ns" in caplog.text
    assert runtime.last_sector_rotation_observed_signal is None
    assert runtime.last_sector_rotation_observed_vote is None
    assert "reason_code=strategy_signal_missing" not in caplog.text


def test_observed_pair_candle_mismatch_diag_does_not_submit(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    loop = _loop(
        preferred=SleeveType.SECTOR_ROTATION,
        eligible=[SleeveType.SECTOR_ROTATION],
    )
    runtime = _runtime(
        sector_signal=_signal(exchange_ts_ns=T0_NS),
        sector_vote=_vote(timestamp_ns=T0_NS - 1),
    )

    _dispatch(loop, runtime)

    loop.execution_engine.submit_signal.assert_not_called()
    loop.decision_compiler.compile.assert_not_called()
    assert "reason_code=OBSERVED_PAIR_CANDLE_MISMATCH" in caplog.text
    assert "signal_candle_id" in caplog.text
    assert "vote_candle_id" in caplog.text
    assert "reason_code=strategy_signal_missing" not in caplog.text


def test_observed_pair_symbol_mismatch_diag_does_not_submit(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    loop = _loop(
        preferred=SleeveType.SECTOR_ROTATION,
        eligible=[SleeveType.SECTOR_ROTATION],
    )
    runtime = _runtime(
        sector_signal=_signal(exchange_ts_ns=T0_NS, symbol="BTC/USD"),
        sector_vote=_vote(timestamp_ns=T0_NS, symbol="BTC/USD"),
    )

    _dispatch(loop, runtime)

    loop.execution_engine.submit_signal.assert_not_called()
    loop.decision_compiler.compile.assert_not_called()
    assert "reason_code=OBSERVED_PAIR_SYMBOL_MISMATCH" in caplog.text
    assert "consumer_symbol': 'ETH/USD'" in caplog.text
    assert "signal_symbol': 'BTC/USD'" in caplog.text
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
    assert "decision_compiler_status_code': 'SUBMITTED_TO_EXECUTION'" in caplog.text


def test_pre_trade_guardrail_uses_alpaca_crypto_default_limit_gtc_for_non_attack():
    config = Config(
        broker_mode="paper",
        active_markets=["crypto"],
        symbol_universe=["ETH/USD"],
        portal_selection_policy="explicit_preferred_venue",
        preferred_trading_portal="alpaca_paper",
    )
    signal = _signal(symbol="ETH/USD")
    runtime = _runtime()

    verdict = main_loop_module._build_pre_trade_guardrail_verdict(
        config=config,
        symbol="ETH/USD",
        signal=signal,
        runtime=runtime,
        is_attack=False,
    )

    assert verdict["route_permitted"] is True
    assert verdict["order_type"] == "limit"
    assert verdict["time_in_force"] == "GTC"
    assert verdict["capability_identity"]["execution_adapter"] == "alpaca_paper_rest"
    assert verdict["reason_codes"] == ("PRE_TRADE_GUARDRAILS_ALLOW",)


def test_submitted_false_diag_includes_status_code_and_execution_block(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    loop = _loop()
    loop.execution_engine.submit_signal.return_value = False
    loop.execution_engine.get_last_admission_block_result.return_value = types.SimpleNamespace(
        normalized_status="blocked",
        route="execution_engine",
        reason_code="SAFE_MODE_ACTIVE",
        message="ExecutionEngine safe-mode gate blocked signal admission.",
    )
    signal = _signal()
    vote = _vote()

    _dispatch(loop, _runtime(sector_signal=signal, sector_vote=vote))

    loop.decision_compiler.compile.assert_called_once()
    loop.execution_engine.submit_signal.assert_called_once()
    assert loop._metrics.orders_rejected == 1
    assert "reason_code=submit_signal_called" in caplog.text
    assert "submitted': False" in caplog.text
    assert "decision_compiler_status_code': 'EXECUTION_ADMISSION_BLOCKED'" in caplog.text
    assert "execution_admission_reason_code': 'SAFE_MODE_ACTIVE'" in caplog.text


def test_submitted_false_diag_includes_execution_block_evidence(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    loop = _loop()
    loop.execution_engine.submit_signal.return_value = False
    loop.execution_engine.get_last_admission_block_result.return_value = types.SimpleNamespace(
        normalized_status="blocked",
        route="execution_engine",
        reason_code="DATA_UNHEALTHY",
        message="Data validator blocked signal admission.",
        block_evidence={
            "symbol": "ETH/USD",
            "data_health_reason_code": "DATA_STALE",
            "latest_candle_ts_ns": T0_NS,
            "data_source_type": "runtime",
        },
    )
    signal = _signal()
    vote = _vote()

    _dispatch(loop, _runtime(sector_signal=signal, sector_vote=vote))

    assert "execution_admission_reason_code': 'DATA_UNHEALTHY'" in caplog.text
    assert "execution_admission_block_evidence" in caplog.text
    assert "data_health_reason_code': 'DATA_STALE'" in caplog.text


def test_stale_backfill_candle_does_not_reach_executable_dispatch(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    loop = types.SimpleNamespace()
    loop._running = True
    loop.active_symbols = {"ETH/USD"}
    loop._lock = threading.Lock()
    loop._last_admitted_candle_ts_ns = {}
    loop._metrics = types.SimpleNamespace(
        candle_duplicates_rejected=0,
        candle_stale_rejected=0,
        iteration_count=0,
        last_candle_exchange_ts_ns=0,
        last_risk_assessment_ns=0,
        last_health_log_iteration=0,
        consecutive_errors=0,
    )
    loop._last_equity = 1000.0
    loop.health_log_interval_iterations = 999
    loop.symbol = "ETH/USD"
    loop._primary_runtime = types.SimpleNamespace(last_tpe_signal=None)
    loop._shans_gate_last_log_ts = {}
    loop.data_validator = DataContinuityValidator(max_stale_age_sec=5.0)
    loop.signal_fusion = MagicMock()
    loop.signal_fusion.fuse = MagicMock(return_value=types.SimpleNamespace())
    loop.entropy_decoder = MagicMock()
    loop.entropy_decoder.update.return_value = 0.0
    loop.insider_engine = MagicMock()
    loop.insider_engine.get_or_default_snapshot.return_value = "insider"
    loop.commander = MagicMock()
    loop.risk_guard = MagicMock()
    loop.risk_guard.assess_state.return_value = "risk-state"
    loop.execution_engine = MagicMock()
    loop.execution_engine.process_events = MagicMock()
    loop._advance_recalibration = MagicMock()
    loop._log_health = MagicMock()
    loop._sync_legacy_references = MagicMock()
    loop._compute_volatility = MainLoop._compute_volatility.__get__(loop, MainLoop)
    loop._observe_sector_rotation = MagicMock()
    loop._update_physical_freshness = MagicMock()
    loop._dispatch_fusion = MagicMock()

    runtime = _runtime()
    runtime.update_candle = MagicMock()
    runtime.current_volatility = 0.20
    runtime.last_whale_alert = None
    runtime.toxicity_engine = MagicMock()
    runtime.toxicity_engine.update_toxicity.return_value = "tox"
    runtime.update_toxicity_multiplier_from_alert = MagicMock()
    runtime.shans_curve = MagicMock()
    runtime.shans_curve.is_ready.return_value = True
    runtime.update_sentiment_engine = MagicMock()
    loop._ensure_runtime = MagicMock(return_value=runtime)

    MainLoop.on_candle.__get__(loop, MainLoop)(_candle(exchange_ts_ns=T0_NS))

    loop._observe_sector_rotation.assert_called_once()
    loop.signal_fusion.fuse.assert_not_called()
    loop._dispatch_fusion.assert_not_called()
    loop._update_physical_freshness.assert_not_called()
    assert "reason_code=DATA_BACKFILL_OBSERVE_ONLY" in caplog.text
    assert "decision_compiler_called': False" in caplog.text
    assert "submit_signal_called': False" in caplog.text


def test_sell_without_broker_position_classifies_missing_authority():
    config = Config(
        broker_mode="paper",
        active_markets=["crypto"],
        symbol_universe=["SOL/USD"],
        portal_selection_policy="explicit_preferred_venue",
        preferred_trading_portal="alpaca_paper",
    )
    signal = _signal(symbol="SOL/USD")
    signal.side = "sell"
    runtime = _runtime()

    verdict = main_loop_module._build_pre_trade_guardrail_verdict(
        config=config,
        symbol="SOL/USD",
        signal=signal,
        runtime=runtime,
        is_attack=False,
    )

    assert signal.metadata["sell_intent_classification"] == "SELL_AUTHORITY_MISSING"
    assert "SELL_AUTHORITY_MISSING" in verdict["reason_codes"]
    assert "ACTION_UNSUPPORTED" in verdict["reason_codes"]
    assert verdict["route_permitted"] is False


def test_sell_with_broker_position_classifies_exit_without_enabling_sell():
    config = Config(
        broker_mode="paper",
        active_markets=["crypto"],
        symbol_universe=["SOL/USD"],
        portal_selection_policy="explicit_preferred_venue",
        preferred_trading_portal="alpaca_paper",
    )
    signal = _signal(symbol="SOL/USD")
    signal.side = "sell"
    signal.metadata["existing_positions"] = ({"symbol": "SOL/USD", "quantity": "1.0"},)
    runtime = _runtime()

    verdict = main_loop_module._build_pre_trade_guardrail_verdict(
        config=config,
        symbol="SOL/USD",
        signal=signal,
        runtime=runtime,
        is_attack=False,
    )

    assert signal.metadata["sell_intent_classification"] == "SELL_EXIT_EXISTING_BROKER_POSITION"
    assert "SELL_AUTHORITY_MISSING" not in verdict["reason_codes"]
    assert "ACTION_UNSUPPORTED" in verdict["reason_codes"]
    assert verdict["route_permitted"] is False


def test_main_loop_does_not_import_broker_adapter():
    assert "broker_adapter" not in inspect.getsource(main_loop_module)
