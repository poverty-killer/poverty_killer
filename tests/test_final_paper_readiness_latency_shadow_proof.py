import asyncio
from decimal import Decimal

from app.data.websocket_client import KrakenWebSocketClient
from app.execution.engine import ExecutionEngine
from app.execution.order_router import OrderRouter
from app.risk.guard import HybridRiskGuard
from app.utils.time_utils import now_ns


NS_PER_MS = 1_000_000
NS_PER_SECOND = 1_000_000_000


def _risk_guard(tmp_path):
    return HybridRiskGuard(
        initial_equity=10000.0,
        state_file=str(tmp_path / "risk_state.json"),
        backup_file=str(tmp_path / "risk_state.backup"),
        max_latency_ms=200.0,
    )


def _engine(tmp_path, router):
    return ExecutionEngine(
        commander=object(),
        risk_guard=_risk_guard(tmp_path),
        order_router=router,
        masking_layer=object(),
        lag_threshold_ms=200.0,
        recalibration_pause_sec=0.0,
    )


def _readiness_verdict(
    *,
    physical_fuse_status="PHYSICAL_FUSE_CLEARED",
    alpaca_reconciliation=True,
    alpaca_endpoint="https://paper-api.alpaca.markets",
    feed_truth_status="WEBSOCKET_ACTIVE_REST_DNS_FAILED",
    latency_truth=None,
    shadow_no_mutation=True,
    live_endpoint_used=False,
):
    reasons = []
    latency_truth = dict(latency_truth or {})

    if physical_fuse_status != "PHYSICAL_FUSE_CLEARED":
        reasons.append("PHYSICAL_FUSE_NOT_CLEARED")
    if not alpaca_reconciliation:
        reasons.append("MISSING_ALPACA_RECONCILIATION_TRUTH")
    if alpaca_endpoint != "https://paper-api.alpaca.markets":
        reasons.append("ALPACA_PAPER_ENDPOINT_NOT_PROVEN")
    if feed_truth_status not in {
        "WEBSOCKET_ACTIVE",
        "WEBSOCKET_ACTIVE_REST_DNS_FAILED",
        "MARKET_DATA_PARTIAL_TRUTH",
    }:
        reasons.append("MARKET_DATA_TRUTH_NOT_PROVEN")
    if latency_truth.get("status") != "LATENCY_OK" or latency_truth.get("latency_ms") is None:
        reasons.append("FINITE_LATENCY_OK_NOT_PROVEN")
    if not shadow_no_mutation:
        reasons.append("SHADOW_BROKER_MUTATION_MARKER")
    if live_endpoint_used:
        reasons.append("LIVE_ENDPOINT_USED")

    return {
        "verdict": "READY_FOR_AUTONOMOUS_PAPER" if not reasons else "NOT_READY_FOR_AUTONOMOUS_PAPER",
        "reason_codes": reasons,
    }


def test_missing_rtt_is_latency_not_ready_not_fake_latency(tmp_path):
    router = OrderRouter(paper_mode=True)
    engine = _engine(tmp_path, router)

    truth = engine._classify_latency_truth(router.measure_latency(), current_ns=100 * NS_PER_SECOND)

    assert truth.status == "MISSING_LATENCY_TRUTH"
    assert truth.reason_code == "WEBSOCKET_RTT_NOT_READY"
    assert truth.latency_ms is None
    assert truth.missing_source == "websocket_ping_or_pong_timestamp"


def test_kraken_pong_wires_first_finite_rtt_into_order_router(tmp_path):
    router = OrderRouter(paper_mode=True)
    client = KrakenWebSocketClient(
        symbols=["BTC/USD"],
        on_health=router.update_websocket_health,
    )
    sent_ns = now_ns()
    receive_ns = sent_ns + 7 * NS_PER_MS
    client._last_heartbeat_sent_ns = sent_ns

    asyncio.run(client._process_message('{"method":"pong"}', receive_ns))

    assert router.measure_latency() == 7.0
    assert router.is_websocket_connected() is True
    engine = _engine(tmp_path, router)
    truth = engine._classify_latency_truth(router.measure_latency(), current_ns=receive_ns)
    assert truth.status == "LATENCY_OK"
    assert truth.latency_ms == 7.0


def test_non_pong_message_does_not_fabricate_zero_rtt(tmp_path):
    router = OrderRouter(paper_mode=True)
    client = KrakenWebSocketClient(
        symbols=["BTC/USD"],
        on_health=router.update_websocket_health,
    )
    client._last_heartbeat_sent_ns = 100 * NS_PER_SECOND

    asyncio.run(client._process_message('{"method":"subscribe","params":{"status":"subscribed"}}', 101 * NS_PER_SECOND))

    engine = _engine(tmp_path, router)
    truth = engine._classify_latency_truth(router.measure_latency(), current_ns=101 * NS_PER_SECOND)
    assert truth.status == "MISSING_LATENCY_TRUTH"


def test_stale_rtt_blocks_readiness_as_stale_market_truth(tmp_path):
    router = OrderRouter(paper_mode=True)
    pong_ns = 100 * NS_PER_SECOND
    router.update_websocket_health(pong_ns - 8 * NS_PER_MS, pong_ns)
    engine = _engine(tmp_path, router)

    truth = engine._classify_latency_truth(router.measure_latency(), current_ns=pong_ns + 31 * NS_PER_SECOND)

    assert truth.status == "STALE_MARKET_TRUTH"
    assert truth.reason_code == "WEBSOCKET_RTT_STALE"
    assert truth.staleness_ms == 31_000.0


def test_finite_rtt_above_threshold_still_triggers_lag_abort(tmp_path):
    router = OrderRouter(paper_mode=True)
    current_ns = 100 * NS_PER_SECOND
    router.update_websocket_health(current_ns - 250 * NS_PER_MS, current_ns)
    engine = _engine(tmp_path, router)

    truth = engine._classify_latency_truth(router.measure_latency(), current_ns=current_ns)

    assert truth.status == "LAG_ABORT_ACTIVE"
    assert truth.reason_code == "LATENCY_THRESHOLD_EXCEEDED"
    assert truth.latency_ms == 250.0
    assert truth.threshold_ms == 200.0


def test_safe_mode_remains_until_finite_latency_ok(tmp_path):
    router = OrderRouter(paper_mode=True)
    engine = _engine(tmp_path, router)

    missing = engine._classify_latency_truth(router.measure_latency(), current_ns=100 * NS_PER_SECOND)
    engine._apply_latency_truth(missing)
    assert engine.get_status()["is_in_safe_mode"] is True

    router.update_websocket_health(101 * NS_PER_SECOND, 101 * NS_PER_SECOND + 9 * NS_PER_MS)
    ok = engine._classify_latency_truth(router.measure_latency(), current_ns=101 * NS_PER_SECOND + 9 * NS_PER_MS)
    engine._apply_latency_truth(ok)

    status = engine.get_status()
    assert ok.status == "LATENCY_OK"
    assert status["is_in_safe_mode"] is False
    assert status["last_latency_truth"]["latency_ms"] == 9.0


def test_paper_readiness_cannot_be_ready_with_missing_latency_truth(tmp_path):
    router = OrderRouter(paper_mode=True)
    engine = _engine(tmp_path, router)
    truth = engine._classify_latency_truth(router.measure_latency(), current_ns=100 * NS_PER_SECOND)

    readiness = _readiness_verdict(latency_truth=truth.to_dict())

    assert readiness["verdict"] == "NOT_READY_FOR_AUTONOMOUS_PAPER"
    assert "FINITE_LATENCY_OK_NOT_PROVEN" in readiness["reason_codes"]


def test_paper_readiness_requires_all_clean_truth_and_shadow_no_mutation(tmp_path):
    router = OrderRouter(paper_mode=True)
    current_ns = 100 * NS_PER_SECOND
    router.update_websocket_health(current_ns - 12 * NS_PER_MS, current_ns)
    engine = _engine(tmp_path, router)
    truth = engine._classify_latency_truth(router.measure_latency(), current_ns=current_ns)

    readiness = _readiness_verdict(
        latency_truth=truth.to_dict(),
        shadow_no_mutation=True,
        live_endpoint_used=False,
    )

    assert truth.status == "LATENCY_OK"
    assert readiness["verdict"] == "READY_FOR_AUTONOMOUS_PAPER"
    assert readiness["reason_codes"] == []
    assert Decimal(str(engine.risk_guard.max_latency_ms)) == Decimal("200.0")


def test_paper_readiness_fails_closed_on_mutation_or_live_endpoint_even_with_latency_ok(tmp_path):
    router = OrderRouter(paper_mode=True)
    current_ns = 100 * NS_PER_SECOND
    router.update_websocket_health(current_ns - 12 * NS_PER_MS, current_ns)
    engine = _engine(tmp_path, router)
    truth = engine._classify_latency_truth(router.measure_latency(), current_ns=current_ns)

    readiness = _readiness_verdict(
        latency_truth=truth.to_dict(),
        shadow_no_mutation=False,
        live_endpoint_used=True,
    )

    assert readiness["verdict"] == "NOT_READY_FOR_AUTONOMOUS_PAPER"
    assert "SHADOW_BROKER_MUTATION_MARKER" in readiness["reason_codes"]
    assert "LIVE_ENDPOINT_USED" in readiness["reason_codes"]
