from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np

from app.brain.convexity_switch import ConvexitySwitch
from app.brain.data_validator import DataContinuityValidator
from app.brain.recalibrator import Recalibrator
from app.brain.ring_buffer import RingBuffer
from app.brain.rolling_stats import RollingStats
from app.brain.shadow_front_state import ShadowFrontStateMachine, WhaleContext
from app.brain.shans_curve import ShansCurve, ShansCurveSignal, _savitzky_golay
from app.brain.topological_engine import TopologicalEngine
from app.models import OrderBookSnapshot


T0_NS = 1_779_000_000_000_000_000


class _AlwaysHealthyValidator:
    def validate(self, **kwargs):
        return True, "ok"


class _NeutralEntropy:
    state = SimpleNamespace(entropy_history=[0.25])


def _shans_curve(window: int = 12) -> ShansCurve:
    return ShansCurve(
        risk_guard=object(),
        safety_gate=object(),
        data_validator=_AlwaysHealthyValidator(),
        entropy_decoder=_NeutralEntropy(),
        curvature_window=window,
        enable_topological=True,
        enable_denoising=True,
    )


def test_shans_curve_savitzky_golay_nopython_path_runs_on_numeric_arrays():
    y = np.array([1.0, 1.4, 2.1, 2.9, 4.2, 5.1, 6.0, 7.4, 8.9], dtype=np.float64)

    smoothed = _savitzky_golay(y, 7, 2)

    assert smoothed.shape == y.shape
    assert np.all(np.isfinite(smoothed))
    assert _savitzky_golay.signatures


def test_shans_curve_preserves_not_ready_warmup_without_fake_signal():
    curve = _shans_curve(window=8)

    for offset in range(7):
        signal = curve.update_order_book(
            symbol="BTC/USD",
            mid_price=100.0 + offset,
            cum_bid_vol=50.0 + offset,
            cum_ask_vol=45.0,
            depth_velocity=0.0,
            timestamp=T0_NS + offset,
            sequence_id=offset + 1,
        )
        assert signal is None

    assert curve.is_ready() is False
    assert curve.get_last_computation() is None


def test_shans_curve_produces_finite_native_signal_with_sufficient_data():
    curve = _shans_curve(window=12)
    signal = None

    for offset in range(12):
        signal = curve.update_order_book(
            symbol="BTC/USD",
            mid_price=100.0 + (offset * 0.35) + (0.05 * np.sin(offset)),
            cum_bid_vol=80.0 + (offset % 5) * 3.0 + offset,
            cum_ask_vol=70.0 + (offset % 3) * 2.0,
            depth_velocity=0.0,
            timestamp=T0_NS + offset,
            sequence_id=offset + 1,
        )

    assert isinstance(signal, ShansCurveSignal)
    assert curve.is_ready() is True
    assert np.isfinite(signal.shans_superfluid_score)
    assert np.isfinite(signal.shans_confidence)
    assert signal.shans_bias in {-1, 0, 1}
    computation = curve.get_last_computation()
    assert computation is not None
    assert computation.reason in {"ok", "degenerate_low_variance"}
    assert np.isfinite(computation.projected_confidence)
    assert "broker_order_id" not in computation.__dict__
    assert "pnl" not in curve.get_stats()


def test_topological_engine_emits_truthful_insufficient_or_native_shape_evidence():
    engine = TopologicalEngine(symbol="BTC/USD", min_liquidity_usd=1.0)
    thin_book = OrderBookSnapshot(
        symbol="BTC/USD",
        exchange_ts_ns=T0_NS,
        bids=[(99.9, 1.0), (99.8, 1.2)],
        asks=[(100.1, 1.1), (100.2, 1.0)],
    )

    thin_signal = engine.analyze(thin_book)
    assert thin_signal.reason == "insufficient_points"
    assert thin_signal.confidence == 0.0

    rich_book = OrderBookSnapshot(
        symbol="BTC/USD",
        exchange_ts_ns=T0_NS + 1,
        bids=[(100.0 - i * 0.1, 5.0 + i) for i in range(15)],
        asks=[(100.2 + i * 0.1, 4.5 + i) for i in range(15)],
    )
    rich_signal = engine.analyze(rich_book)
    assert 0.0 <= rich_signal.coherence_score <= 1.0
    assert 0.0 <= rich_signal.persistence_score <= 1.0
    assert np.isfinite(rich_signal.confidence)


def test_convexity_switch_emits_advisory_posture_without_execution_authority():
    switch = ConvexitySwitch(correlation_window=5, momentum_threshold=0.7, carry_threshold=0.3)

    regime = "MIXED"
    for idx in range(12):
        returns = 0.001 * (idx + 1)
        regime = switch.update("BTC/USD", returns=returns, benchmark_returns=returns * 1.01)

    assert regime == "MOMENTUM"
    weights = switch.get_strategy_weight("BTC/USD")
    assert weights["regime"] == "MOMENTUM"
    assert 0.0 <= weights["momentum_weight"] <= 1.0
    assert not hasattr(switch, "submit_order")
    assert not hasattr(switch, "cancel_order")


def test_shadow_front_state_handles_deterministic_context_without_broker_truth():
    machine = ShadowFrontStateMachine(symbol="BTC/USD")
    context = WhaleContext(
        is_active=True,
        zone_low=99.0,
        zone_high=101.0,
        volume=1000.0,
        score=0.8,
        confidence=0.75,
        evidence_count=3,
        direction_bias=1,
        timestamp_ns=T0_NS,
    )

    machine.update_whale_context(context, current_ts_ns=T0_NS)
    status = machine.get_status(current_ts_ns=T0_NS)

    assert status["symbol"] == "BTC/USD"
    assert status["state"] in {"IDLE", "STALKING", "ARMED", "IGNITION", "ACTIVE", "COOLDOWN"}
    assert machine.get_whale_confidence() == 0.75
    assert not hasattr(machine, "broker_gateway")
    assert not hasattr(machine, "order_router")


def test_ring_buffer_and_rolling_stats_handle_finite_and_insufficient_data():
    buffer = RingBuffer(max_size=3)
    assert buffer.get_window(2).size == 0
    buffer.append(1.0)
    buffer.append(2.0)
    buffer.append(3.0)
    buffer.append(4.0)
    assert np.array_equal(buffer.get_window(3), np.array([2.0, 3.0, 4.0]))

    stats = RollingStats(window_size=3)
    assert stats.std() == 0.0
    for value in [1.0, 2.0, 3.0, 4.0]:
        stats.update(value)
    assert stats.count() == 3
    assert np.isfinite(stats.mean())
    assert np.isfinite(stats.std())


def test_data_validator_and_recalibrator_fail_closed_without_fake_repair():
    validator = DataContinuityValidator()
    assert validator.validate_price_volume(price=-1.0, volume=10.0) == (
        False,
        "price (-1.0) < minimum (0.0)",
    )
    assert validator.validate_numeric(float("nan"), name="ofi") == (False, "ofi is NaN")

    recalibrator = Recalibrator(recovery_required_good=2)
    assert recalibrator.evaluate_regime(0.10, None, drop_duration_sec=30.0) == "NEUTRAL"
    assert recalibrator.evaluate_regime(0.10, None, drop_duration_sec=30.0) == "CRISIS_ABORT"
    status = recalibrator.get_status()
    assert status["last_betti_1_count"] == 0
    assert status["last_persistence_score"] == 0.0


def test_target_brain_modules_do_not_expose_broker_mutation_authority():
    modules = [
        _shans_curve(),
        TopologicalEngine(symbol="BTC/USD"),
        ConvexitySwitch(),
        ShadowFrontStateMachine(symbol="BTC/USD"),
        RingBuffer(max_size=3),
        RollingStats(window_size=3),
        DataContinuityValidator(),
        Recalibrator(),
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
