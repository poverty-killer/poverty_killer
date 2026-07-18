from __future__ import annotations

import ast
import asyncio
import hashlib
import inspect
import types
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import main as main_module
from app.brain.signal_fusion import FUSION_HISTORY_LIMIT, QuantMath, SignalFusion
from app.config import Config
from app.data.polling_client import PollingClient
from app.data.websocket_client import KrakenWebSocketClient
from app.main_loop import MainLoop, _classify_candle_execution_truth, _pre_trade_stale_data_assessment
from app.models import Candle, OrderBookSnapshot
from app.models.enums import RegimeType, SleeveType
from app.risk.stale_data_guard import StaleDataGuard, TemporalInput
from app.symbol_runtime import SymbolRuntime
from app.utils.enums import RiskAction, is_blocking_risk_action


REPO_ROOT = Path(__file__).resolve().parents[1]
T0_NS = 1_800_000_000_000_000_000


def _direction(value: int):
    return types.SimpleNamespace(value=value)


def _whale(direction: int = 1, confidence: float = 0.75):
    return types.SimpleNamespace(direction=_direction(direction), confidence=confidence)


def _shans(*, bias: float = 0.30, confidence: float = 0.70, superfluid: float = 0.20):
    return types.SimpleNamespace(
        shans_superfluid_score=superfluid,
        shans_bias=bias,
        shans_confidence=confidence,
    )


def _toxicity(score: float = 0.10):
    return types.SimpleNamespace(
        toxicity_score=score,
        regime=types.SimpleNamespace(value=0),
    )


def _entropy(value: float = 0.20):
    return types.SimpleNamespace(entropy=Decimal(str(value)))


def _insider(*, urgency: float = 0.0, active: bool = False):
    return types.SimpleNamespace(active=active, invalidated=False, urgency=urgency)


def _fusion() -> SignalFusion:
    return SignalFusion(
        types.SimpleNamespace(
            symbol="BTC/USD",
            strategies=types.SimpleNamespace(sector_rotation_ranging_eligible=False),
        )
    )


def _payload(channel: str, *, symbol: str, direction: int = 1, regime=RegimeType.RANGING):
    return {
        "whale_flow": _whale(direction=direction),
        "shans_curve": _shans(bias=0.4 * direction),
        "toxicity": _toxicity(),
        "entropy": _entropy(),
        "physical": {"health_score": 0.90, "symbol": symbol},
        "insider": _insider(),
        "regime": (regime, 0.90),
    }[channel]


def _update(
    fusion: SignalFusion,
    channel: str,
    *,
    symbol: str,
    event_ts_ns: int,
    received_ts_ns: int,
    direction: int = 1,
    regime=RegimeType.RANGING,
) -> None:
    method_name = {
        "whale_flow": "update_whale",
        "shans_curve": "update_shans",
    }.get(channel, f"update_{channel}")
    updater = getattr(fusion, method_name)
    updater(
        _payload(channel, symbol=symbol, direction=direction, regime=regime),
        event_ts_ns,
        symbol=symbol,
        source=f"stage1_{channel}",
        received_ts_ns=received_ts_ns,
    )


def _inject_all(
    fusion: SignalFusion,
    *,
    symbol: str,
    ts_ns: int,
    direction: int = 1,
    regime=RegimeType.RANGING,
    omit: str | None = None,
) -> None:
    for channel in (
        "whale_flow",
        "shans_curve",
        "toxicity",
        "entropy",
        "physical",
        "insider",
        "regime",
    ):
        if channel != omit:
            _update(
                fusion,
                channel,
                symbol=symbol,
                event_ts_ns=ts_ns,
                received_ts_ns=ts_ns,
                direction=direction,
                regime=regime,
            )


def _sha256(relative_path: str) -> str:
    return hashlib.sha256((REPO_ROOT / relative_path).read_bytes()).hexdigest()


def test_symbol_indexed_fusion_produces_independent_decisions_telemetry_and_hysteresis():
    fusion = _fusion()
    _inject_all(
        fusion,
        symbol="BTC/USD",
        ts_ns=T0_NS,
        direction=1,
        regime=RegimeType.TRENDING_BULL,
    )
    _inject_all(
        fusion,
        symbol="ETH/USD",
        ts_ns=T0_NS,
        direction=-1,
        regime=RegimeType.RANGING,
    )

    btc = fusion.fuse(T0_NS, symbol="BTC/USD", output_ts_ns=T0_NS - 60_000_000_000)
    eth = fusion.fuse(T0_NS, symbol="ETH/USD", output_ts_ns=T0_NS - 60_000_000_000)

    assert btc.preferred_sleeve == SleeveType.SECTOR_ROTATION.value
    assert eth.preferred_sleeve == SleeveType.SHADOW_FRONT.value
    assert "DIR:1" in btc.reason
    assert "DIR:-1" in eth.reason
    assert btc.exchange_ts_ns == eth.exchange_ts_ns == T0_NS - 60_000_000_000
    assert fusion.get_last_fusion("BTC/USD") is btc
    assert fusion.get_last_fusion("ETH/USD") is eth
    assert fusion.get_fusion_telemetry("BTC/USD")["symbol"] == "BTC/USD"
    assert fusion.get_fusion_telemetry("ETH/USD")["symbol"] == "ETH/USD"
    assert fusion._lanes["BTC/USD"].state is not fusion._lanes["ETH/USD"].state


@pytest.mark.parametrize(
    "channel",
    ["whale_flow", "shans_curve", "toxicity", "entropy", "physical", "insider", "regime"],
)
def test_every_future_native_channel_is_refused_with_signed_causal_evidence(channel: str):
    fusion = _fusion()
    _inject_all(fusion, symbol="BTC/USD", ts_ns=T0_NS, omit=channel)
    _update(
        fusion,
        channel,
        symbol="BTC/USD",
        event_ts_ns=T0_NS + 1,
        received_ts_ns=T0_NS,
    )

    decision = fusion.fuse(T0_NS, symbol="BTC/USD")
    telemetry = fusion.get_fusion_telemetry("BTC/USD")
    refusal = telemetry["causal_integrity_rejections"][channel][-1]

    assert refusal["reason_code"] == "FUSION_CAUSAL_FUTURE_EVENT"
    assert refusal["event_age_ns"] == -1
    assert channel not in telemetry["fusion_input_provenance"]
    if channel in {"physical", "toxicity"}:
        assert "FUSION_CAUSAL_FUTURE_EVENT" in decision.reason
    else:
        assert channel in telemetry["missing_inputs"]


def test_received_after_decision_is_not_yet_available_and_never_fresh():
    fusion = _fusion()
    _inject_all(fusion, symbol="BTC/USD", ts_ns=T0_NS, omit="shans_curve")
    _update(
        fusion,
        "shans_curve",
        symbol="BTC/USD",
        event_ts_ns=T0_NS - 1,
        received_ts_ns=T0_NS + 1,
    )

    fusion.fuse(T0_NS, symbol="BTC/USD")
    telemetry = fusion.get_fusion_telemetry("BTC/USD")
    refusal = telemetry["causal_integrity_rejections"]["shans_curve"][-1]

    assert refusal["reason_code"] == "FUSION_CAUSAL_NOT_YET_AVAILABLE"
    assert refusal["availability_age_ns"] == -1
    assert "shans_curve" in telemetry["missing_inputs"]


def test_symbol_lane_refuses_decision_clock_regression_before_state_mutation():
    fusion = _fusion()
    _inject_all(fusion, symbol="BTC/USD", ts_ns=T0_NS)
    original = fusion.fuse(T0_NS, symbol="BTC/USD")

    with pytest.raises(ValueError, match="FUSION_DECISION_TIMESTAMP_REGRESSION"):
        fusion.fuse(T0_NS - 1, symbol="BTC/USD")

    assert fusion.get_last_fusion("BTC/USD") is original
    assert fusion._lanes["BTC/USD"].last_decision_ts_ns == T0_NS


def test_lawful_prior_survives_future_update_and_selected_ages_are_nonnegative():
    fusion = _fusion()
    prior_ts = T0_NS - 10
    _inject_all(fusion, symbol="BTC/USD", ts_ns=prior_ts, direction=1)
    _update(
        fusion,
        "whale_flow",
        symbol="BTC/USD",
        event_ts_ns=T0_NS + 5,
        received_ts_ns=T0_NS,
        direction=-1,
    )

    decision = fusion.fuse(T0_NS, symbol="BTC/USD")
    telemetry = fusion.get_fusion_telemetry("BTC/USD")

    assert "DIR:1" in decision.reason
    assert telemetry["fusion_input_provenance"]["whale_flow"]["event_ts_ns"] == prior_ts
    assert telemetry["causal_integrity_rejections"]["whale_flow"][-1]["event_ts_ns"] == T0_NS + 5
    assert all(
        item["event_age_ns"] >= 0 and item["availability_age_ns"] >= 0
        for item in telemetry["fusion_input_provenance"].values()
    )


def test_future_event_flood_cannot_evict_last_lawful_as_of_anchor():
    fusion = _fusion()
    _inject_all(fusion, symbol="BTC/USD", ts_ns=T0_NS, direction=1)
    fusion.fuse(T0_NS, symbol="BTC/USD")

    for offset in range(FUSION_HISTORY_LIMIT + 17):
        _update(
            fusion,
            "whale_flow",
            symbol="BTC/USD",
            event_ts_ns=T0_NS + 1 + offset,
            received_ts_ns=T0_NS,
            direction=-1,
        )

    decision = fusion.fuse(T0_NS, symbol="BTC/USD")
    telemetry = fusion.get_fusion_telemetry("BTC/USD")
    history = fusion._lanes["BTC/USD"].histories["whale_flow"]

    assert len(history) == FUSION_HISTORY_LIMIT
    assert "DIR:1" in decision.reason
    assert telemetry["fusion_input_provenance"]["whale_flow"]["event_ts_ns"] == T0_NS
    assert telemetry["causal_integrity_rejections"]["whale_flow"]


def test_future_external_evidence_is_refused_from_fusion_telemetry():
    fusion = _fusion()
    _inject_all(fusion, symbol="BTC/USD", ts_ns=T0_NS)
    fusion.update_strategy_evidence(
        (
            {
                "symbol": "BTC/USD",
                "module_name": "Stage1FutureProbe",
                "event_ts_ns": T0_NS + 1,
                "received_ts_ns": T0_NS,
                "status": "ACTIVE_NATIVE_SIGNAL",
            },
        ),
        T0_NS,
        symbol="BTC/USD",
        source="stage1_external_probe",
        received_ts_ns=T0_NS,
    )

    fusion.fuse(T0_NS, symbol="BTC/USD")
    telemetry = fusion.get_fusion_telemetry("BTC/USD")

    assert "strategy_attribution" not in telemetry
    refusal = telemetry["causal_integrity_rejections"]["strategy_attribution"][-1]
    assert refusal["reason_code"] == "FUSION_CAUSAL_FUTURE_EVENT"


def test_negative_temporal_age_is_an_error_not_full_weight():
    with pytest.raises(ValueError, match="FUSION_CAUSAL_NEGATIVE_AGE"):
        QuantMath.temporal_discount(-1, 5_000_000_000)
    assert QuantMath.temporal_discount(0, 5_000_000_000) == 1.0


def test_grouped_and_interleaved_cross_symbol_replay_are_decision_equivalent():
    def run(interleaved: bool):
        fusion = _fusion()
        symbols = ("BTC/USD", "ETH/USD")
        channels = (
            "whale_flow",
            "shans_curve",
            "toxicity",
            "entropy",
            "physical",
            "insider",
            "regime",
        )
        pairs = (
            [(symbol, channel) for symbol in symbols for channel in channels]
            if not interleaved
            else [(symbol, channel) for channel in channels for symbol in symbols]
        )
        for symbol, channel in pairs:
            _update(
                fusion,
                channel,
                symbol=symbol,
                event_ts_ns=T0_NS,
                received_ts_ns=T0_NS,
                direction=1 if symbol == "BTC/USD" else -1,
                regime=(
                    RegimeType.TRENDING_BULL
                    if symbol == "BTC/USD"
                    else RegimeType.RANGING
                ),
            )
        return {
            symbol: fusion.fuse(T0_NS, symbol=symbol).model_dump(mode="json")
            for symbol in symbols
        }

    assert run(interleaved=False) == run(interleaved=True)


def test_symbol_channel_history_is_bounded_without_cross_symbol_eviction():
    fusion = _fusion()
    for offset in range(FUSION_HISTORY_LIMIT + 17):
        _update(
            fusion,
            "whale_flow",
            symbol="BTC/USD",
            event_ts_ns=T0_NS + offset,
            received_ts_ns=T0_NS + offset,
        )
    _update(
        fusion,
        "whale_flow",
        symbol="ETH/USD",
        event_ts_ns=T0_NS,
        received_ts_ns=T0_NS,
        direction=-1,
    )

    btc_history = fusion._lanes["BTC/USD"].histories["whale_flow"]
    eth_history = fusion._lanes["ETH/USD"].histories["whale_flow"]
    assert len(btc_history) == FUSION_HISTORY_LIMIT
    assert len(eth_history) == 1
    assert {item.symbol for item in btc_history} == {"BTC/USD"}
    assert eth_history[0].symbol == "ETH/USD"


def _stable_guard_sequence(symbol: str = "BTC/USD"):
    guard = StaleDataGuard(symbol)
    result = None
    for index in range(50):
        receipt = T0_NS + index * 100_000_000
        result = guard.assess(
            TemporalInput(
                current_ts_ns=receipt,
                exchange_ts_ns=receipt - 10_000_000,
                local_received_ts_ns=receipt,
            )
        )
    assert result is not None
    return guard, result


def test_persistent_guard_warms_to_50_samples_and_replay_serializes_identically():
    guard_a, assessment_a = _stable_guard_sequence()
    guard_b, assessment_b = _stable_guard_sequence()

    assert assessment_a.warm is True
    assert assessment_a.kinematics.sample_count == 50
    assert assessment_a.kinematics.drift_ns == 10_000_000
    assert assessment_a.risk_action is RiskAction.ALLOW
    assert assessment_a.to_dict() == assessment_b.to_dict()
    assert guard_a.get_forensic_snapshot() == guard_b.get_forensic_snapshot()


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("drift", "absolute_drift_limit_breach"),
        ("future", "future_dated_exchange_timestamp"),
        ("regression", "exchange_timestamp_regression"),
        ("forward_gap", "excessive_exchange_forward_gap"),
        ("receipt_after", "local_receive_after_assessment_timestamp"),
        ("local_regression", "local_clock_timestamp_regression"),
    ],
)
def test_temporal_guard_names_and_blocks_broken_clock_cases(case: str, reason: str):
    guard = StaleDataGuard("BTC/USD")
    if case in {"regression", "forward_gap", "local_regression"}:
        guard.assess(
            TemporalInput(
                current_ts_ns=T0_NS,
                exchange_ts_ns=T0_NS - 10_000_000,
                local_received_ts_ns=T0_NS,
            )
        )

    if case == "drift":
        observation = TemporalInput(T0_NS, T0_NS - 600_000_000, T0_NS)
    elif case == "future":
        observation = TemporalInput(T0_NS, T0_NS + 60_000_000, T0_NS)
    elif case == "regression":
        observation = TemporalInput(T0_NS + 100_000_000, T0_NS - 20_000_000, T0_NS + 100_000_000)
    elif case == "forward_gap":
        observation = TemporalInput(T0_NS + 5_200_000_000, T0_NS + 5_100_000_000, T0_NS + 5_200_000_000)
    elif case == "receipt_after":
        observation = TemporalInput(T0_NS, T0_NS, T0_NS + 1)
    else:
        observation = TemporalInput(T0_NS - 1, T0_NS - 10_000_001, T0_NS - 1)

    assessment = guard.assess(observation)

    assert is_blocking_risk_action(assessment.risk_action)
    if case == "drift":
        assert reason in assessment.rationale
    else:
        assert assessment.invariant_status.reason == reason
        assert assessment.invariant_status.valid is False


def test_symbol_runtime_owns_distinct_entropy_physical_guard_and_cold_restart_state():
    config = Config()
    btc = SymbolRuntime("BTC/USD")
    eth = SymbolRuntime("ETH/USD")
    btc.initialize_engines(config=config, safety_gate=None)
    eth.initialize_engines(config=config, safety_gate=None)

    btc.entropy_decoder.update("BTC/USD", T0_NS, 0.20)
    btc.physical_validator.record_latency(
        symbol="BTC/USD",
        exchange="kraken",
        latency_ms=10.0,
        order_size=0.0,
        price_impact_bps=0.0,
        timestamp_ns=T0_NS,
    )
    btc.observe_transport(
        exchange_ts_ns=T0_NS - 10_000_000,
        receive_ts_ns=T0_NS,
    )

    assert btc.entropy_decoder is not eth.entropy_decoder
    assert btc.physical_validator is not eth.physical_validator
    assert btc.stale_data_guard is not eth.stale_data_guard
    assert len(btc.entropy_decoder.state.entropy_history) == 1
    assert len(eth.entropy_decoder.state.entropy_history) == 0
    assert btc.physical_validator.get_current("kraken") is not None
    assert eth.physical_validator.get_current("kraken") is None
    assert btc.last_stale_data_assessment is not None
    assert eth.last_stale_data_assessment is None

    btc.update_order_book(
        OrderBookSnapshot(
            symbol="BTC/USD",
            exchange_ts_ns=T0_NS,
            receive_ts_ns=T0_NS,
            bids=[(100.0, 1.0)],
            asks=[(101.0, 1.0)],
        )
    )
    recovered = SymbolRuntime.import_recovery_state(
        btc.export_recovery_state(),
        expected_symbol="BTC/USD",
        current_ts_ns=T0_NS + 1,
        max_state_age_ns=1_000_000_000,
    )
    assert recovered.recovery_status == "hydrated_market_state_only"
    assert recovered.last_stale_data_assessment is None
    assert recovered.stale_data_guard.get_forensic_snapshot()["samples"] == 0
    assert recovered.entropy_decoder is None
    assert recovered.physical_validator is None


def test_one_minute_candle_freshness_and_transport_drift_use_separate_clocks():
    start_ns = T0_NS
    close_ns = start_ns + 60_000_000_000
    receive_ns = close_ns + 100_000_000
    candle = Candle(
        symbol="ETH/USD",
        exchange_ts_ns=start_ns,
        open=2500.0,
        high=2510.0,
        low=2490.0,
        close=2505.0,
        volume=100.0,
        timeframe="1m",
        candle_close_ts_ns=close_ns,
        candle_closed_at_receive=True,
        candle_batch_received_ns=receive_ns,
        latest_batch_candle=True,
        candle_freshness_policy_ms=60_000.0,
    )
    runtime = types.SimpleNamespace(
        last_candle=candle,
        last_order_book=types.SimpleNamespace(exchange_ts_ns=close_ns),
    )
    candle_truth = _classify_candle_execution_truth(
        symbol="ETH/USD",
        runtime=runtime,
        candle=candle,
        exchange_ts_ns=start_ns,
        current_ns=receive_ns,
    )
    assessment = StaleDataGuard("ETH/USD").assess(
        TemporalInput(
            current_ts_ns=receive_ns,
            exchange_ts_ns=receive_ns - 10_000_000,
            local_received_ts_ns=receive_ns,
        )
    )
    runtime.last_stale_data_assessment = assessment

    selected = _pre_trade_stale_data_assessment(
        runtime,
        {
            "stale_data_observation": {
                "current_ts_ns": receive_ns,
                "exchange_ts_ns": start_ns,
                "local_received_ts_ns": receive_ns,
            }
        },
    )

    assert candle_truth["executable_market_truth"] is True
    assert selected is assessment
    assert selected.kinematics.drift_ns == 10_000_000
    assert selected.risk_action is RiskAction.ALLOW


def test_signal_metadata_cannot_spoof_missing_runtime_freshness_authority():
    forged = StaleDataGuard("ETH/USD").assess(
        TemporalInput(
            current_ts_ns=T0_NS,
            exchange_ts_ns=T0_NS,
            local_received_ts_ns=T0_NS,
        )
    ).to_dict()
    runtime = types.SimpleNamespace(last_stale_data_assessment=None)

    selected = _pre_trade_stale_data_assessment(
        runtime,
        {"stale_data_assessment": forged},
    )

    assert selected is None


def test_polling_book_preserves_source_event_and_local_receipt_or_fails_closed():
    client = PollingClient(symbols=["BTC/USD"], exchange="kraken")
    source_sec = Decimal("1800000000.125")
    receive_ns = int(source_sec * Decimal(1_000_000_000)) + 10_000_000
    snapshot = client._parse_order_book(
        {
            "result": {
                "XXBTZUSD": {
                    "bids": [["100.0", "1.0", str(source_sec)]],
                    "asks": [["101.0", "1.0", str(source_sec)]],
                }
            }
        },
        "BTC/USD",
        receive_ts_ns=receive_ns,
    )

    assert snapshot is not None
    assert snapshot.exchange_ts_ns == int(source_sec * Decimal(1_000_000_000))
    assert snapshot.receive_ts_ns == receive_ns
    assert client._parse_order_book(
        {"result": {"XXBTZUSD": {"bids": [["100", "1"]], "asks": [["101", "1"]]}}},
        "BTC/USD",
        receive_ts_ns=receive_ns,
    ) is None


def test_websocket_book_and_candle_retain_transport_receipt_timestamp():
    books = []
    candles = []
    client = KrakenWebSocketClient(
        symbols=["BTC/USD"],
        on_order_book=books.append,
        on_candle=candles.append,
    )
    receive_ns = 1_705_320_000_010_000_000
    asyncio.run(
        client._parse_order_book(
            {
                "channel": "book",
                "data": [
                    {
                        "symbol": "BTC/USD",
                        "timestamp": "2024-01-15T12:00:00.000Z",
                        "bids": [{"price": "100", "qty": "1"}],
                        "asks": [{"price": "101", "qty": "1"}],
                    }
                ],
            },
            receive_ns,
        )
    )
    asyncio.run(
        client._parse_candle(
            {
                "channel": "ohlc",
                "data": [
                    {
                        "symbol": "BTC/USD",
                        "interval_begin": "2024-01-15T12:01:00.000Z",
                        "open": "100",
                        "high": "102",
                        "low": "99",
                        "close": "101",
                        "volume": "2",
                    }
                ],
            },
            receive_ns + 1,
        )
    )

    assert books[0].receive_ts_ns == receive_ns
    assert candles[0].candle_batch_received_ns == receive_ns + 1


def test_trade_callback_has_one_symbol_runtime_writer_and_no_global_fusion_or_broker_mutation():
    alert = types.SimpleNamespace(
        confidence=0.70,
        avg_trade_size=0.25,
        direction=types.SimpleNamespace(value=1),
    )
    runtime = types.SimpleNamespace(
        toxicity_engine=types.SimpleNamespace(get_suppression_factor=lambda: 0.90)
    )
    heartbeat = types.SimpleNamespace(
        _primary_symbol="BTC/USD",
        main_loop=types.SimpleNamespace(
            on_trade=MagicMock(),
            on_trade_with_whale=MagicMock(return_value=alert),
            get_runtime=MagicMock(return_value=runtime),
        ),
        whale_engine=types.SimpleNamespace(update=MagicMock()),
        signal_fusion=types.SimpleNamespace(update_whale=MagicMock()),
        insider_engine=types.SimpleNamespace(ingest_observation=MagicMock()),
        _mark_loop_event=MagicMock(),
        _mark_runtime_error=MagicMock(),
    )

    main_module.SovereignHeartbeat._on_trade(
        heartbeat,
        {
            "symbol": "BTC/USD",
            "price": 100.0,
            "volume": 2.0,
            "side": 1,
            "exchange_ts_ns": T0_NS,
            "receive_ts_ns": T0_NS + 10_000_000,
        },
    )

    heartbeat.main_loop.on_trade_with_whale.assert_called_once_with(
        "BTC/USD",
        100.0,
        1,
        2.0,
        T0_NS,
        receive_ts_ns=T0_NS + 10_000_000,
    )
    heartbeat.main_loop.on_trade.assert_not_called()
    heartbeat.whale_engine.update.assert_not_called()
    heartbeat.signal_fusion.update_whale.assert_not_called()
    heartbeat.insider_engine.ingest_observation.assert_called_once()


def test_active_main_loop_fusion_calls_require_symbol_source_and_availability():
    tree = ast.parse((REPO_ROOT / "app/main_loop.py").read_text(encoding="utf-8-sig"))
    missing = []
    checked = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if not isinstance(node.func.value, ast.Attribute):
            continue
        if not (
            isinstance(node.func.value.value, ast.Name)
            and node.func.value.value.id == "self"
            and node.func.value.attr == "signal_fusion"
        ):
            continue
        if node.func.attr not in {
            "update_whale",
            "update_shans",
            "update_regime",
            "update_entropy",
            "update_insider",
            "update_toxicity",
            "update_physical",
            "fuse",
        }:
            continue
        checked += 1
        keywords = {keyword.arg for keyword in node.keywords}
        required = {"symbol"} if node.func.attr == "fuse" else {"symbol", "source", "received_ts_ns"}
        if not required.issubset(keywords):
            missing.append((node.lineno, node.func.attr, sorted(required - keywords)))

    assert checked == 8
    assert missing == []
    callback_source = inspect.getsource(main_module.SovereignHeartbeat._on_trade)
    assert "self.signal_fusion.update_whale" not in callback_source
    assert "self.whale_engine.update" not in callback_source
    assert "self.main_loop.on_trade(" not in callback_source

    order_book_source = inspect.getsource(MainLoop.on_order_book)
    assert "self.regime_detector.update" not in order_book_source
    assert "using global fallback" not in order_book_source
    assert "regime_tuple = (RegimeType.UNKNOWN, 0.0)" in order_book_source


def test_stage1_thresholds_and_untouched_quant_sources_match_entry_fingerprints():
    fusion = _fusion()
    stale = StaleDataGuard("BTC/USD")

    assert fusion._ttl_ns == {
        "whale_flow": 15_000_000_000,
        "shans_curve": 15_000_000_000,
        "physical": 30_000_000_000,
        "toxicity": 30_000_000_000,
        "entropy": 60_000_000_000,
        "insider": 120_000_000_000,
        "regime": 300_000_000_000,
    }
    assert fusion._half_life_ns == {
        "whale_flow": 5_000_000_000,
        "shans_curve": 7_000_000_000,
        "insider": 60_000_000_000,
    }
    assert stale.max_drift_ns == 500_000_000
    assert stale.config.window_size == 1000
    assert stale.config.min_samples == 50
    assert stale.config.future_skew_tolerance_ms == 50
    assert stale.config.max_forward_gap_ms == 5000
    assert stale.config.critical_velocity_ns_per_s == 100_000_000
    assert _sha256("app/brain/physical_validator.py") == "0d404f7e85a38f3a10a768b2b6a37a3e6f7a6ccd0bf28ace4f60a0c39f5956b9"
    assert _sha256("app/brain/entropy_decoder.py") == "ee0b904316cf24a86d990df8f3a8c3b31acac0bc2dab28f6b9ee6c565f6d1eb1"
    assert _sha256("app/brain/insider_signal_engine.py") == "9665a2bf23f7402ef014013dda102dc2478c13ca2a9d478ab8c6ca94f7d708ff"


def test_stage1_sources_add_no_broker_mutation_or_sovereign_guard_authority():
    scoped = (
        "app/brain/signal_fusion.py",
        "app/data/polling_client.py",
        "app/data/websocket_client.py",
        "app/models/market_data.py",
        "app/risk/pre_trade_guardrails.py",
        "app/risk/stale_data_guard.py",
        "app/symbol_runtime.py",
    )
    forbidden_calls = []
    for relative_path in scoped:
        tree = ast.parse((REPO_ROOT / relative_path).read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in {"submit_order", "post_order", "cancel_order", "liquidate", "close_all"}:
                    forbidden_calls.append((relative_path, node.lineno, node.func.attr))

    main_source = (REPO_ROOT / "main.py").read_text(encoding="utf-8-sig")
    loop_source = (REPO_ROOT / "app/main_loop.py").read_text(encoding="utf-8-sig")
    assert forbidden_calls == []
    assert "SovereignExecutionGuard(" not in main_source
    assert "SovereignExecutionGuard(" not in loop_source
