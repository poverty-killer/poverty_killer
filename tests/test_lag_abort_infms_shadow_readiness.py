from decimal import Decimal

from app.execution.engine import ExecutionEngine
from app.risk.guard import HybridRiskGuard


NS_PER_MS = 1_000_000
NS_PER_SECOND = 1_000_000_000


class DeterministicRouter:
    def __init__(self, latency_ms, *, ping_ns=0, pong_ns=0, connected=True):
        self.latency_ms = latency_ms
        self._last_websocket_ping_ns = ping_ns
        self._last_websocket_pong_ns = pong_ns
        self._websocket_connected = connected

    def measure_latency(self):
        return self.latency_ms

    def is_websocket_connected(self):
        return self._websocket_connected


def _engine(tmp_path, router):
    risk_guard = HybridRiskGuard(
        initial_equity=10000.0,
        state_file=str(tmp_path / "risk_state.json"),
        backup_file=str(tmp_path / "risk_state.backup"),
        max_latency_ms=200.0,
    )
    return ExecutionEngine(
        commander=object(),
        risk_guard=risk_guard,
        order_router=router,
        masking_layer=object(),
        lag_threshold_ms=200.0,
        recalibration_pause_sec=0.0,
    )


def test_missing_websocket_timestamps_are_missing_latency_truth_not_unqualified_infms(tmp_path):
    engine = _engine(tmp_path, DeterministicRouter(float("inf")))

    truth = engine._classify_latency_truth(float("inf"), current_ns=100 * NS_PER_SECOND)

    assert truth.status == "MISSING_LATENCY_TRUTH"
    assert truth.reason_code == "WEBSOCKET_RTT_NOT_READY"
    assert truth.latency_ms is None
    assert truth.missing_source == "websocket_ping_or_pong_timestamp"
    assert truth.safe_mode_required is True


def test_invalid_clock_delta_fails_closed(tmp_path):
    engine = _engine(
        tmp_path,
        DeterministicRouter(-10.0, ping_ns=20 * NS_PER_SECOND, pong_ns=19 * NS_PER_SECOND),
    )

    truth = engine._classify_latency_truth(-10.0, current_ns=21 * NS_PER_SECOND)

    assert truth.status == "CLOCK_DELTA_INVALID"
    assert truth.reason_code == "WEBSOCKET_PONG_BEFORE_PING"
    assert truth.safe_mode_required is True


def test_stale_websocket_rtt_reports_stale_market_truth(tmp_path):
    current_ns = 100 * NS_PER_SECOND
    stale_pong = current_ns - 31 * NS_PER_SECOND
    engine = _engine(
        tmp_path,
        DeterministicRouter(10.0, ping_ns=stale_pong, pong_ns=stale_pong),
    )

    truth = engine._classify_latency_truth(10.0, current_ns=current_ns)

    assert truth.status == "STALE_MARKET_TRUTH"
    assert truth.reason_code == "WEBSOCKET_RTT_STALE"
    assert truth.staleness_ms == 31_000.0
    assert truth.safe_mode_required is True


def test_finite_latency_above_threshold_is_real_lag_abort_with_measured_latency(tmp_path):
    current_ns = 100 * NS_PER_SECOND
    engine = _engine(
        tmp_path,
        DeterministicRouter(
            250.0,
            ping_ns=current_ns - int(250 * NS_PER_MS),
            pong_ns=current_ns,
        ),
    )

    truth = engine._classify_latency_truth(250.0, current_ns=current_ns)

    assert truth.status == "LAG_ABORT_ACTIVE"
    assert truth.reason_code == "LATENCY_THRESHOLD_EXCEEDED"
    assert truth.latency_ms == 250.0
    assert truth.threshold_ms == 200.0
    assert truth.safe_mode_required is True


def test_finite_latency_below_threshold_is_ok(tmp_path):
    current_ns = 100 * NS_PER_SECOND
    engine = _engine(
        tmp_path,
        DeterministicRouter(
            12.5,
            ping_ns=current_ns - int(12.5 * NS_PER_MS),
            pong_ns=current_ns,
        ),
    )

    truth = engine._classify_latency_truth(12.5, current_ns=current_ns)

    assert truth.status == "LATENCY_OK"
    assert truth.reason_code == "LATENCY_WITHIN_THRESHOLD"
    assert truth.latency_ms == 12.5
    assert truth.safe_mode_required is False


def test_execution_engine_safe_mode_remains_active_when_lag_abort_is_real(tmp_path):
    current_ns = 100 * NS_PER_SECOND
    engine = _engine(
        tmp_path,
        DeterministicRouter(
            250.0,
            ping_ns=current_ns - int(250 * NS_PER_MS),
            pong_ns=current_ns,
        ),
    )

    truth = engine._classify_latency_truth(250.0, current_ns=current_ns)
    assert truth.status == "LAG_ABORT_ACTIVE"

    engine.risk_guard.update_latency(truth.latency_ms or 0.0)

    assert engine.get_status()["is_in_safe_mode"] is True
    assert engine.risk_guard.get_status()["lag_active"] is True


def test_missing_latency_relabel_does_not_exit_existing_safe_mode(tmp_path):
    engine = _engine(tmp_path, DeterministicRouter(float("inf")))
    engine._state.is_in_safe_mode = True

    truth = engine._classify_latency_truth(float("inf"), current_ns=100 * NS_PER_SECOND)
    engine._apply_latency_truth(truth)

    assert truth.status == "MISSING_LATENCY_TRUTH"
    assert engine.get_status()["is_in_safe_mode"] is True


def test_latency_ok_after_warmup_exits_safe_mode_with_finite_truth(tmp_path):
    current_ns = 100 * NS_PER_SECOND
    engine = _engine(
        tmp_path,
        DeterministicRouter(
            8.0,
            ping_ns=current_ns - int(8 * NS_PER_MS),
            pong_ns=current_ns,
        ),
    )
    engine._state.is_in_safe_mode = True

    truth = engine._classify_latency_truth(8.0, current_ns=current_ns)
    engine._apply_latency_truth(truth)

    status = engine.get_status()
    assert truth.status == "LATENCY_OK"
    assert status["is_in_safe_mode"] is False
    assert status["last_latency_truth"]["latency_ms"] == 8.0


def test_status_carries_latency_source_and_truth_without_lowering_threshold(tmp_path):
    engine = _engine(tmp_path, DeterministicRouter(float("inf")))
    truth = engine._classify_latency_truth(float("inf"), current_ns=100 * NS_PER_SECOND)
    engine._apply_latency_truth(truth)

    status = engine.get_status()

    assert status["last_latency_truth"]["status"] == "MISSING_LATENCY_TRUTH"
    assert status["last_latency_truth"]["source"] == "order_router.websocket_rtt"
    assert status["last_latency_truth"]["threshold_ms"] == 200.0
    assert engine.lag_threshold_ms == 200.0
    assert Decimal(str(engine.risk_guard.max_latency_ms)) == Decimal("200.0")
