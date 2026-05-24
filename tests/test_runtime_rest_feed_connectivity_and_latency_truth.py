import asyncio
import math

import aiohttp

from app.data.polling_client import PollingClient
from app.execution.engine import ExecutionEngine
from app.execution.order_router import OrderRouter
from app.risk.guard import HybridRiskGuard


NS_PER_SECOND = 1_000_000_000
NS_PER_MS = 1_000_000


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


def test_polling_client_uses_threaded_socket_resolver_for_runtime_dns():
    async def run_client():
        client = PollingClient(symbols=[], exchange="coinbase")
        await client.start()
        try:
            resolver = client._session.connector._resolver
            assert isinstance(resolver, aiohttp.ThreadedResolver)
        finally:
            await client.stop()

    asyncio.run(run_client())


def test_polling_success_emits_rest_latency_truth_without_fabrication():
    emitted = []
    client = PollingClient(
        symbols=["BTC/USD"],
        exchange="coinbase",
        on_rest_latency=emitted.append,
    )

    client._record_polling_success(
        "BTC/USD",
        "candle",
        "https://api.exchange.coinbase.com/products/BTC-USD/candles",
        request_start_ns=10 * NS_PER_SECOND,
        response_received_ns=10 * NS_PER_SECOND + 12 * NS_PER_MS,
    )

    assert len(emitted) == 1
    assert emitted[0]["status"] == "REST_LATENCY_OK"
    assert emitted[0]["symbol"] == "BTC/USD"
    assert emitted[0]["feed_type"] == "candle"
    assert emitted[0]["exchange"] == "coinbase"
    assert emitted[0]["endpoint_domain"] == "api.exchange.coinbase.com"
    assert emitted[0]["request_start_ns"] == 10 * NS_PER_SECOND
    assert emitted[0]["response_received_ns"] == 10 * NS_PER_SECOND + 12 * NS_PER_MS
    assert emitted[0]["latency_ms"] == 12.0
    assert emitted[0]["source"] == "market_data.rest_polling_rtt"
    assert emitted[0]["timestamp_ns"] > 0
    assert client.get_stats()["last_rest_latency_status"]["latency_ms"] == 12.0


def test_order_router_rest_latency_source_uses_rest_truth_not_websocket():
    router = OrderRouter(paper_mode=True)
    router.set_market_data_latency_source("rest_polling")
    router.update_rest_market_data_latency(
        request_start_ns=20 * NS_PER_SECOND,
        response_received_ns=20 * NS_PER_SECOND + 9 * NS_PER_MS,
        exchange="coinbase",
        provider_id="coinbase_public",
        symbol="BTC/USD",
        feed_type="candle",
    )

    measurement = router.get_latency_measurement()

    assert measurement["source"] == "market_data.rest_polling_rtt"
    assert measurement["latency_ms"] == 9.0
    assert router.measure_latency() == 9.0
    assert math.isinf(router.get_websocket_rtt_ms())
    assert router.get_ghost_status()["market_data_latency_source"] == "rest_polling"


def test_rest_latency_ok_does_not_create_websocket_rtt_blocker(tmp_path):
    router = OrderRouter(paper_mode=True)
    router.set_market_data_latency_source("rest_polling")
    router.update_rest_market_data_latency(
        request_start_ns=30 * NS_PER_SECOND,
        response_received_ns=30 * NS_PER_SECOND + 11 * NS_PER_MS,
        exchange="coinbase",
        provider_id="coinbase_public",
        symbol="ETH/USD",
        feed_type="order_book",
    )
    engine = _engine(tmp_path, router)

    truth = engine._classify_latency_truth(
        router.get_latency_measurement(),
        current_ns=31 * NS_PER_SECOND,
    )

    assert truth.status == "LATENCY_OK"
    assert truth.reason_code == "REST_LATENCY_WITHIN_THRESHOLD"
    assert truth.source == "market_data.rest_polling_rtt"
    assert truth.source_scope == "market_data_book_rtt"
    assert truth.latency_ms == 11.0
    assert truth.safe_mode_required is False


def test_websocket_latency_measurement_dict_still_classifies_normally(tmp_path):
    router = OrderRouter(paper_mode=True)
    router.update_websocket_health(
        ping_ns=35 * NS_PER_SECOND,
        pong_ns=35 * NS_PER_SECOND + 8 * NS_PER_MS,
    )
    engine = _engine(tmp_path, router)

    truth = engine._classify_latency_truth(
        router.get_latency_measurement(),
        current_ns=36 * NS_PER_SECOND,
    )

    assert truth.status == "LATENCY_OK"
    assert truth.reason_code == "LATENCY_WITHIN_THRESHOLD"
    assert truth.source == "order_router.websocket_rtt"
    assert truth.latency_ms == 8.0
    assert truth.safe_mode_required is False


def test_missing_rest_latency_truth_is_truthful_without_websocket_reason(tmp_path):
    router = OrderRouter(paper_mode=True)
    router.set_market_data_latency_source("rest_polling")
    engine = _engine(tmp_path, router)

    truth = engine._classify_latency_truth(
        router.get_latency_measurement(),
        current_ns=40 * NS_PER_SECOND,
    )

    assert truth.status == "MISSING_LATENCY_TRUTH"
    assert truth.reason_code == "REST_RTT_NOT_READY"
    assert truth.source == "market_data.rest_polling_rtt"
    assert truth.missing_source == "rest_request_or_response_timestamp"
    assert truth.safe_mode_required is False


def test_slow_rest_candle_latency_is_evidence_not_global_safe_mode(tmp_path):
    router = OrderRouter(paper_mode=True)
    router.set_market_data_latency_source("rest_polling")
    router.update_rest_market_data_latency(
        request_start_ns=45 * NS_PER_SECOND,
        response_received_ns=45 * NS_PER_SECOND + 437 * NS_PER_MS,
        exchange="coinbase",
        provider_id="coinbase_public",
        symbol="SOL/USD",
        feed_type="candle",
    )
    engine = _engine(tmp_path, router)

    truth = engine._classify_latency_truth(
        router.get_latency_measurement(),
        current_ns=46 * NS_PER_SECOND,
    )
    engine._apply_latency_truth(truth)

    assert truth.status == "MARKET_DATA_LATENCY_DEGRADED"
    assert truth.reason_code == "REST_LATENCY_THRESHOLD_EXCEEDED"
    assert truth.source_scope == "market_data_candle_rtt"
    assert truth.safe_mode_required is False
    assert engine.get_status()["is_in_safe_mode"] is False


def test_stale_rest_latency_is_market_data_evidence_not_global_safe_mode(tmp_path):
    router = OrderRouter(paper_mode=True)
    router.set_market_data_latency_source("rest_polling")
    router.update_rest_market_data_latency(
        request_start_ns=50 * NS_PER_SECOND,
        response_received_ns=50 * NS_PER_SECOND + 5 * NS_PER_MS,
        exchange="coinbase",
        provider_id="coinbase_public",
        symbol="SOL/USD",
        feed_type="candle",
    )
    engine = _engine(tmp_path, router)

    truth = engine._classify_latency_truth(
        router.get_latency_measurement(),
        current_ns=81 * NS_PER_SECOND,
    )

    assert truth.status == "STALE_MARKET_DATA_LATENCY_TRUTH"
    assert truth.reason_code == "REST_RTT_STALE"
    assert truth.source_scope == "market_data_candle_rtt"
    assert truth.safe_mode_required is False
