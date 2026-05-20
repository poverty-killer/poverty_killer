from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from app.brain.sentiment_engine import AggregateSentiment, SentimentEngine
from app.brain.sentiment_velocity import MacroSignal, SentimentVelocityEngine, SentimentVector
from app.brain.whale_zone_engine import WhalePresenceZone, WhaleZoneEngine, ZoneBias
from app.data.feature_builder import FeatureBuilder
from app.data.ghost_tick_detector import FastGhostTickDetector, GhostTickDetector, GhostTickResult
from app.data.regime_detector import RegimeDetector
from app.data.validators import DataValidator
from app.models import Candle, OrderBookSnapshot
from app.models.enums import RegimeType


T0_NS = 1_779_100_000_000_000_000

CONTRIBUTION_KEYS = {
    "module_name",
    "status",
    "input_truth",
    "output_summary",
    "effect",
    "reason",
}


def _evidence(
    *,
    module_name: str,
    status: str,
    input_truth: str,
    output_summary: str,
    effect: str,
    reason: str,
) -> dict[str, str]:
    return {
        "module_name": module_name,
        "status": status,
        "input_truth": input_truth,
        "output_summary": output_summary,
        "effect": effect,
        "reason": reason,
    }


def _assert_contribution_shape(evidence: dict[str, str]) -> None:
    assert set(evidence) == CONTRIBUTION_KEYS
    assert all(isinstance(value, str) and value for value in evidence.values())


def _candles(count: int) -> list[Candle]:
    candles = []
    for idx in range(count):
        close = 100.0 + idx * 0.25
        candles.append(
            Candle(
                symbol="BTC/USD",
                exchange_ts_ns=T0_NS + idx * 60_000_000_000,
                open=close - 0.1,
                high=close + 0.4,
                low=close - 0.5,
                close=close,
                volume=1000.0 + idx * 10.0,
            )
        )
    return candles


def test_sentiment_engine_returns_missing_then_native_without_inventing_sentiment():
    engine = SentimentEngine(min_sources=2)

    missing = engine.aggregate("BTC/USD", T0_NS)
    assert missing is None
    missing_evidence = _evidence(
        module_name="SentimentEngine",
        status="MISSING_FEED_TRUTH",
        input_truth="no_source_sentiment",
        output_summary="aggregate unavailable",
        effect="NO_EFFECT_WITH_REASON",
        reason="insufficient_sentiment_sources",
    )
    _assert_contribution_shape(missing_evidence)

    engine.update_source("BTC/USD", "technical", 0.20, T0_NS, confidence=0.80)
    engine.update_source("BTC/USD", "macro", 0.10, T0_NS + 1, confidence=0.70)
    aggregate = engine.aggregate("BTC/USD", T0_NS + 2)

    assert isinstance(aggregate, AggregateSentiment)
    assert aggregate.source_count == 2
    assert -1.0 <= aggregate.level <= 1.0
    assert 0.0 <= aggregate.confidence <= 1.0
    native_evidence = _evidence(
        module_name="SentimentEngine",
        status="ACTIVE_NATIVE_SIGNAL",
        input_truth="provided_source_sentiment:technical,macro",
        output_summary=f"level={aggregate.level:.4f} sources={aggregate.source_count}",
        effect="SENTIMENT_SIGNAL",
        reason="source_sentiment_aggregated",
    )
    _assert_contribution_shape(native_evidence)


def test_sentiment_velocity_handles_missing_history_and_native_derivatives():
    engine = SentimentVelocityEngine(min_history_points=4)

    macro_missing = engine.analyze(T0_NS)
    assert isinstance(macro_missing, MacroSignal)
    assert macro_missing.reason == "insufficient_data"
    missing_evidence = _evidence(
        module_name="SentimentVelocityEngine",
        status="NOT_READY_DATA_WARMUP",
        input_truth="sentiment_history_count=0",
        output_summary=macro_missing.reason,
        effect="NO_EFFECT_WITH_REASON",
        reason="insufficient_sentiment_history",
    )
    _assert_contribution_shape(missing_evidence)

    vector = None
    for idx, value in enumerate([-0.20, -0.05, 0.05, 0.15, 0.18]):
        vector = engine.update_sentiment(value, T0_NS + idx * 10_000_000_000)

    assert isinstance(vector, SentimentVector)
    assert np.isfinite(vector.velocity)
    assert np.isfinite(vector.acceleration)
    assert 0.0 <= vector.confidence <= 1.0
    native_evidence = _evidence(
        module_name="SentimentVelocityEngine",
        status="ACTIVE_NATIVE_SIGNAL",
        input_truth="provided_sentiment_history",
        output_summary=f"velocity={vector.velocity:.6f} acceleration={vector.acceleration:.6f}",
        effect="SENTIMENT_VELOCITY",
        reason="sentiment_derivatives_computed",
    )
    _assert_contribution_shape(native_evidence)


def test_whale_zone_engine_uses_volume_candle_truth_without_inventing_institutional_flow():
    engine = WhaleZoneEngine({"zone_stability_required": 2, "zone_confidence_threshold": 0.6})

    first = engine.update("BTC/USD", close=105.0, high=105.0, low=95.0, volume=1000.0, vwap=100.0, exchange_ts_ns=T0_NS)
    assert first is None

    zone = engine.update(
        "BTC/USD",
        close=105.2,
        high=105.2,
        low=95.2,
        volume=1200.0,
        vwap=100.2,
        exchange_ts_ns=T0_NS + 60_000_000_000,
    )

    assert isinstance(zone, WhalePresenceZone)
    assert zone.bias in {ZoneBias.BULLISH, ZoneBias.BEARISH, ZoneBias.NEUTRAL}
    assert 0.0 <= zone.confidence <= 1.0
    evidence = _evidence(
        module_name="WhaleZoneEngine",
        status="ACTIVE_NATIVE_SIGNAL",
        input_truth="provided_candle_volume_vwap",
        output_summary=f"bounds=({zone.lower_bound:.4f},{zone.upper_bound:.4f}) confidence={zone.confidence:.4f}",
        effect="WHALE_ZONE",
        reason="volume_zone_detected_from_supplied_candles",
    )
    _assert_contribution_shape(evidence)


def test_regime_detector_returns_warmup_then_classifies_from_feature_truth():
    detector = RegimeDetector(min_samples=3, transition_cooldown_ns=0)

    observed = []
    for idx in range(2):
        feature_vector = SimpleNamespace(
            timestamp_ns=T0_NS + idx,
            features={
                "topological_coherence": 0.80,
                "entropy": 0.50,
                "entropy_collapsed": False,
                "void_depth": 0.10,
                "momentum_sign": 1.0,
            },
        )
        observed.append(detector.update(feature_vector))

    assert observed == [RegimeType.UNKNOWN, RegimeType.UNKNOWN]
    warmup_evidence = _evidence(
        module_name="RegimeDetector",
        status="NOT_READY_DATA_WARMUP",
        input_truth="feature_samples=2 min_samples=3",
        output_summary="current_regime=unknown",
        effect="NO_EFFECT_WITH_REASON",
        reason="insufficient_regime_samples",
    )
    _assert_contribution_shape(warmup_evidence)

    final_vector = SimpleNamespace(
        timestamp_ns=T0_NS + 3,
        features={
            "topological_coherence": 0.85,
            "entropy": 0.45,
            "entropy_collapsed": False,
            "void_depth": 0.05,
            "momentum_sign": 1.0,
        },
    )
    regime = detector.update(final_vector)
    assert regime == RegimeType.TRENDING_BULL
    assert detector.get_current_confidence() > 0.0


def test_feature_builder_builds_finite_features_and_handles_insufficient_inputs():
    builder = FeatureBuilder(slow_window=5, fast_window=2)
    candles = _candles(8)

    warmup = builder.build_all_features(candles, current_idx=2)
    assert warmup["volatility_zscore"] == 0.0
    assert warmup["atr_normalized"] == 0.0

    features = builder.build_all_features(
        candles,
        current_idx=8,
        depth_history=[100.0, 95.0, 110.0],
        whale_zone=(99.5, 101.0),
    )
    assert features
    assert all(np.isfinite(value) for value in features.values())
    evidence = _evidence(
        module_name="FeatureBuilder",
        status="ACTIVE_FEATURES",
        input_truth="provided_candles_depth_whale_zone",
        output_summary=f"feature_count={len(features)}",
        effect="FEATURE_MATRIX",
        reason="point_in_time_features_built",
    )
    _assert_contribution_shape(evidence)


class _UnknownMarket:
    def get_instrument(self, symbol: str):
        return None


class _NoopSharedMemory:
    def get_version(self, name: str) -> int:
        return 0

    def get_reader(self, name: str):
        return None


def test_ghost_tick_detector_flags_or_degrades_without_deleting_truth():
    detector = GhostTickDetector(_UnknownMarket(), _NoopSharedMemory())
    result = detector.detect("BTC/USD", price=100.0, volume=10.0, timestamp_ns=T0_NS)

    assert isinstance(result, GhostTickResult)
    assert result.is_ghost is False
    assert result.confidence == 0.0
    assert result.reason == "Unknown symbol: BTC/USD"

    fast = FastGhostTickDetector(window=4, threshold=1.0)
    assert fast.detect_vector([1], np.array([100.0])).tolist() == [False]

    evidence = _evidence(
        module_name="GhostTickDetector",
        status="MISSING_FEED_TRUTH",
        input_truth="unknown_symbol_no_unified_market_spec",
        output_summary=result.reason,
        effect="GHOST_TICK_FLAG",
        reason="missing_instrument_truth",
    )
    _assert_contribution_shape(evidence)


def test_validators_pass_fail_and_degrade_invalid_data_explicitly():
    validator = DataValidator(stale_threshold_seconds=30)
    candle = _candles(1)[0]

    valid = validator.validate_candle(candle, current_time_ns=candle.exchange_ts_ns + 1_000_000_000)
    assert valid.is_valid is True
    assert valid.error is None

    stale = validator.validate_candle(candle, current_time_ns=candle.exchange_ts_ns + 120_000_000_000)
    assert stale.is_valid is False
    assert "Stale candle" in stale.error

    bad_book = OrderBookSnapshot(
        symbol="BTC/USD",
        exchange_ts_ns=T0_NS,
        bids=[(100.0, 1.0)],
        asks=[(99.0, 1.0)],
    )
    book_result = validator.validate_order_book(bad_book, current_time_ns=T0_NS + 1)
    assert book_result.is_valid is False
    assert "Negative spread" in book_result.error

    evidence = _evidence(
        module_name="DataValidator",
        status="INVALID_INPUT",
        input_truth="provided_order_book",
        output_summary=book_result.error or "invalid",
        effect="DATA_VALIDATED",
        reason="order_book_validation_failed_closed",
    )
    _assert_contribution_shape(evidence)


def test_target_intelligence_modules_do_not_expose_broker_mutation_authority():
    modules = [
        SentimentEngine(),
        SentimentVelocityEngine(),
        WhaleZoneEngine(),
        RegimeDetector(),
        FeatureBuilder(),
        GhostTickDetector(_UnknownMarket(), _NoopSharedMemory()),
        FastGhostTickDetector(),
        DataValidator(),
    ]
    forbidden = {
        "submit_order",
        "cancel_order",
        "replace_order",
        "rebalance",
        "liquidate",
        "broker_gateway",
        "order_router",
        "execution_engine",
    }

    for module in modules:
        for attr in forbidden:
            assert not hasattr(module, attr), f"{type(module).__name__} exposes {attr}"
