from __future__ import annotations

import numpy as np

from app.data.feature_builder import FeatureBuilder
from app.data.ghost_tick_detector import FastGhostTickDetector
from app.models.market_data import Candle, OrderBookSnapshot


T0_NS = 1_777_948_800_000_000_000


def _candles(count: int) -> list[Candle]:
    return [
        Candle(
            symbol="AAPL",
            exchange_ts_ns=T0_NS + i,
            open=100.0 + i,
            high=101.0 + i,
            low=99.0 + i,
            close=100.5 + i,
            volume=1000.0 + i * 10.0,
        )
        for i in range(count)
    ]


def _book(
    *,
    bids: list[tuple[float, float]] | None = None,
    asks: list[tuple[float, float]] | None = None,
) -> OrderBookSnapshot:
    return OrderBookSnapshot(
        symbol="AAPL",
        exchange_ts_ns=T0_NS,
        bids=bids if bids is not None else [(99.9, 100.0), (99.8, 50.0)],
        asks=asks if asks is not None else [(100.1, 80.0), (100.2, 40.0)],
    )


def _prime_detector(detector: FastGhostTickDetector, histories: dict[int, list[float]]) -> None:
    for idx in range(detector.window):
        for instrument_id, prices in histories.items():
            detector.update(instrument_id, prices[idx])


def test_feature_builder_derives_depth_contraction_from_canonical_bid_ask_levels():
    builder = FeatureBuilder(slow_window=3, fast_window=2)
    contraction = builder.calculate_depth_contraction(_book(), [200.0, 250.0, 300.0])

    assert np.isfinite(contraction)
    assert contraction == (100.0 + 50.0 + 80.0 + 40.0) / 250.0
    assert builder.last_depth_contraction_status == "ACTIVE_DEPTH_TRUTH"
    assert builder.last_depth_contraction_reason == "CANONICAL_BID_ASK_DEPTH"


def test_feature_builder_does_not_require_nonexistent_market_depth_attribute():
    book = _book()
    assert not hasattr(book, "market_depth")

    builder = FeatureBuilder(slow_window=3, fast_window=2)
    contraction = builder.calculate_depth_contraction(book, [250.0, 260.0])

    assert np.isfinite(contraction)
    assert builder.last_depth_contraction_status == "ACTIVE_DEPTH_TRUTH"


def test_feature_builder_reports_missing_or_warmup_depth_truth_without_fake_depth():
    builder = FeatureBuilder(slow_window=3, fast_window=2)

    missing = builder.calculate_depth_contraction(_book(bids=[], asks=[]), [100.0, 100.0])
    assert missing == 1.0
    assert builder.last_depth_contraction_status == "MISSING_DEPTH_TRUTH"
    assert builder.last_depth_contraction_reason == "ORDER_BOOK_DEPTH_UNAVAILABLE"

    warmup = builder.calculate_depth_contraction(_book(), [100.0])
    assert warmup == 1.0
    assert builder.last_depth_contraction_status == "NOT_READY_DATA_WARMUP"
    assert builder.last_depth_contraction_reason == "INSUFFICIENT_DEPTH_HISTORY"


def test_build_all_features_includes_depth_contraction_from_canonical_book():
    builder = FeatureBuilder(slow_window=3, fast_window=2)
    features = builder.build_all_features(
        _candles(6),
        current_idx=6,
        order_book=_book(),
        depth_history=[200.0, 250.0, 300.0],
        historical_spreads=[1.0, 1.1, 1.2],
    )

    assert "depth_contraction" in features
    assert np.isfinite(features["depth_contraction"])
    assert builder.last_depth_contraction_status == "ACTIVE_DEPTH_TRUTH"
    assert all(np.isfinite(value) for value in features.values())


def test_fast_ghost_tick_detector_multi_instrument_normal_path_returns_false_flags():
    detector = FastGhostTickDetector(window=4, threshold=10.0)
    _prime_detector(detector, {1: [100.0, 101.0, 102.0, 103.0], 2: [200.0, 201.0, 202.0, 203.0]})

    flags = detector.detect_vector([1, 2], np.array([103.1, 203.1]))

    assert flags.shape == (2,)
    assert flags.tolist() == [False, False]
    assert detector.last_vector_status == "ACTIVE_COVARIANCE_TRUTH"
    assert detector.last_vector_reason == "BASKET_MAHALANOBIS_DISTANCE"
    assert np.isfinite(detector.last_vector_distance)


def test_fast_ghost_tick_detector_multi_instrument_anomaly_path_returns_basket_flags():
    detector = FastGhostTickDetector(window=4, threshold=1.0)
    _prime_detector(detector, {1: [100.0, 101.0, 102.0, 103.0], 2: [200.0, 201.0, 202.0, 203.0]})

    flags = detector.detect_vector([1, 2], np.array([120.0, 220.0]))

    assert flags.shape == (2,)
    assert flags.tolist() == [True, True]
    assert detector.last_vector_status == "ACTIVE_COVARIANCE_TRUTH"


def test_fast_ghost_tick_detector_missing_or_insufficient_history_fails_closed():
    detector = FastGhostTickDetector(window=4, threshold=1.0)
    detector.update(1, 100.0)

    missing = detector.detect_vector([1, 2], np.array([100.0, 200.0]))
    assert missing.tolist() == [False, False]
    assert detector.last_vector_status == "NOT_READY_DATA_WARMUP"
    assert detector.last_vector_reason == "INSUFFICIENT_PRICE_HISTORY:1"

    detector = FastGhostTickDetector(window=4, threshold=1.0)
    _prime_detector(detector, {1: [100.0, 101.0, 102.0, 103.0]})
    missing_buffer = detector.detect_vector([1, 2], np.array([103.0, 203.0]))
    assert missing_buffer.tolist() == [False, False]
    assert detector.last_vector_status == "NOT_READY_DATA_WARMUP"
    assert detector.last_vector_reason == "MISSING_PRICE_BUFFER:2"


def test_fast_ghost_tick_detector_singular_covariance_does_not_crash():
    detector = FastGhostTickDetector(window=4, threshold=1.0)
    _prime_detector(detector, {1: [100.0, 100.0, 100.0, 100.0], 2: [200.0, 200.0, 200.0, 200.0]})

    flags = detector.detect_vector([1, 2], np.array([100.0, 200.0]))

    assert flags.shape == (2,)
    assert flags.tolist() == [False, False]
    assert detector.last_vector_status in {"ACTIVE_COVARIANCE_TRUTH", "ACTIVE_COVARIANCE_TRUTH_PINV"}
    assert np.isfinite(detector.last_vector_distance)


def test_fast_ghost_tick_detector_single_instrument_path_remains_safe_false():
    detector = FastGhostTickDetector(window=4, threshold=1.0)

    flags = detector.detect_vector([1], np.array([100.0]))

    assert flags.shape == (1,)
    assert flags.tolist() == [False]
    assert detector.last_vector_status == "NOT_READY_DATA_WARMUP"
    assert detector.last_vector_reason == "SINGLE_INSTRUMENT_VECTOR"


def test_residual_repair_modules_have_no_broker_or_live_endpoint_authority():
    forbidden = {
        "submit_order",
        "cancel_order",
        "replace_order",
        "rebalance",
        "liquidate",
        "broker_gateway",
        "order_router",
        "execution_engine",
        "live_endpoint",
    }

    assert forbidden.isdisjoint(set(dir(FeatureBuilder())))
    assert forbidden.isdisjoint(set(dir(FastGhostTickDetector())))
