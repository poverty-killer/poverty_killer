import json
from decimal import Decimal
from pathlib import Path

from app.execution.order_router import OrderRouter
from app.models import OrderRequest
from app.models.enums import OrderSide, OrderType, SleeveType
from app.state.state_store import StateStore
from app.utils.time_utils import now_ns


class _MockResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self) -> dict:
        return self._payload


def _order(order_id: str = "client-order-001") -> OrderRequest:
    ts_ns = now_ns()
    return OrderRequest(
        id=order_id,
        symbol="ETH/USD",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("1.0"),
        limit_price=Decimal("2900.00"),
        strategy=SleeveType.SECTOR_ROTATION,
        confidence=0.9,
        decision_uuid=f"{order_id}-decision",
        exchange_ts_ns=ts_ns,
        receive_ts_ns=ts_ns,
    )


def _store(tmp_path) -> StateStore:
    return StateStore(str(tmp_path / "state.db"))


def test_kraken_ack_persists_exchange_txid_mapping(tmp_path):
    state_store = _store(tmp_path)
    router = OrderRouter(
        primary_exchange="kraken",
        paper_mode=False,
        rest_fallback_enabled=False,
        state_store=state_store,
    )
    router._websocket_connected = True

    router._session.post = lambda *args, **kwargs: _MockResponse(
        200, {"error": [], "result": {"txid": ["KRAKEN-TXID-001"]}}
    )
    order = _order("kraken-client-001")

    assert router.submit_order(order) is None

    mapping = state_store.get_order_id_mapping(order.id, "kraken")
    assert mapping["client_order_id"] == order.id
    assert mapping["venue_order_id"] == "KRAKEN-TXID-001"
    assert mapping["exchange_txid"] == "KRAKEN-TXID-001"
    assert mapping["broker_order_id"] is None
    assert mapping["command_id_namespace"] == "exchange_txid"
    assert mapping["command_order_id"] == "KRAKEN-TXID-001"
    assert mapping["is_terminal"] is False


def test_alpaca_ack_persists_venue_and_broker_mapping(tmp_path):
    state_store = _store(tmp_path)
    router = OrderRouter(
        primary_exchange="alpaca",
        paper_mode=False,
        rest_fallback_enabled=False,
        state_store=state_store,
    )
    router._websocket_connected = True
    router._session.post = lambda *args, **kwargs: _MockResponse(200, {"id": "ALPACA-ID-001"})
    order = _order("alpaca-client-001")

    assert router.submit_order(order) is None

    mapping = state_store.get_order_id_mapping(order.id, "alpaca")
    assert mapping["venue_order_id"] == "ALPACA-ID-001"
    assert mapping["broker_order_id"] == "ALPACA-ID-001"
    assert mapping["exchange_txid"] is None
    assert mapping["command_id_namespace"] == "venue_order_id"
    assert mapping["command_order_id"] == "ALPACA-ID-001"


def test_paper_mapping_uses_client_order_id_command_namespace(tmp_path):
    state_store = _store(tmp_path)
    router = OrderRouter(paper_mode=True, state_store=state_store)
    order = _order("paper-client-001")

    assert router.submit_order(order) is None

    mapping = state_store.get_order_id_mapping(order.id, "paper")
    assert mapping["command_id_namespace"] == "client_order_id"
    assert mapping["command_order_id"] == order.id
    assert mapping["broker_order_id"] is not None
    assert mapping["broker_order_id"] != order.id
    assert mapping["venue_order_id"] == mapping["broker_order_id"]


def test_kraken_cancel_and_status_resolve_to_exchange_txid(tmp_path):
    state_store = _store(tmp_path)
    router = OrderRouter(
        primary_exchange="kraken",
        paper_mode=False,
        rest_fallback_enabled=False,
        state_store=state_store,
    )
    router._websocket_connected = True
    order = _order("kraken-client-command")
    assert router._register_active_order_id_mapping(
        order,
        broker="kraken",
        venue_order_id="KRAKEN-TXID-CMD",
        broker_order_id=None,
        exchange_txid="KRAKEN-TXID-CMD",
        id_mapping_source="test",
        ack_ts_ns=now_ns(),
    )
    calls = []

    def post(url, data=None, headers=None, timeout=None):
        calls.append({"url": url, "data": data})
        if "CancelOrder" in url:
            return _MockResponse(200, {"error": [], "result": {"count": 1}})
        return _MockResponse(200, {"error": [], "result": {"KRAKEN-TXID-CMD": {"status": "open"}}})

    router._session.post = post

    assert router.get_order_status(order.id) == "pending"
    assert router.cancel_order(order.id) is True
    assert calls[0]["data"]["txid"] == "KRAKEN-TXID-CMD"
    assert calls[1]["data"]["txid"] == "KRAKEN-TXID-CMD"
    assert calls[1]["data"]["txid"] != order.id


def test_alpaca_cancel_and_status_resolve_to_venue_order_id(tmp_path):
    state_store = _store(tmp_path)
    router = OrderRouter(
        primary_exchange="alpaca",
        paper_mode=False,
        rest_fallback_enabled=False,
        state_store=state_store,
    )
    router._websocket_connected = True
    order = _order("alpaca-client-command")
    assert router._register_active_order_id_mapping(
        order,
        broker="alpaca",
        venue_order_id="ALPACA-CMD-ID",
        broker_order_id="ALPACA-CMD-ID",
        exchange_txid=None,
        id_mapping_source="test",
        ack_ts_ns=now_ns(),
    )
    calls = []

    def get(url, timeout=None):
        calls.append(("get", url))
        return _MockResponse(200, {"status": "open"})

    def delete(url, timeout=None):
        calls.append(("delete", url))
        return _MockResponse(204, {})

    router._session.get = get
    router._session.delete = delete

    assert router.get_order_status(order.id) == "open"
    assert router.cancel_order(order.id) is True
    assert calls[0] == ("get", "https://paper-api.alpaca.markets/v2/orders/ALPACA-CMD-ID")
    assert calls[1] == ("delete", "https://paper-api.alpaca.markets/v2/orders/ALPACA-CMD-ID")


def test_kraken_cancel_and_status_resolve_from_state_store_after_memory_loss(tmp_path):
    state_store = _store(tmp_path)
    submit_router = OrderRouter(
        primary_exchange="kraken",
        paper_mode=False,
        rest_fallback_enabled=False,
        state_store=state_store,
    )
    submit_router._websocket_connected = True
    order = _order("kraken-reload-client")
    submit_router._session.post = lambda *args, **kwargs: _MockResponse(
        200, {"error": [], "result": {"txid": ["KRAKEN-RELOAD-TXID"]}}
    )

    assert submit_router.submit_order(order) is None

    reloaded = OrderRouter(
        primary_exchange="kraken",
        paper_mode=False,
        rest_fallback_enabled=False,
        state_store=state_store,
    )
    reloaded._websocket_connected = True
    calls = []

    def post(url, data=None, headers=None, timeout=None):
        calls.append({"url": url, "data": data})
        if "QueryOrders" in url:
            return _MockResponse(
                200,
                {"error": [], "result": {"KRAKEN-RELOAD-TXID": {"status": "open"}}},
            )
        return _MockResponse(200, {"error": [], "result": {"count": 1}})

    reloaded._session.post = post

    assert reloaded.get_order_status(order.id) == "pending"
    assert reloaded.cancel_order(order.id) is True
    assert calls[0]["data"]["txid"] == "KRAKEN-RELOAD-TXID"
    assert calls[1]["data"]["txid"] == "KRAKEN-RELOAD-TXID"
    assert calls[0]["data"]["txid"] != order.id
    assert calls[1]["data"]["txid"] != order.id


def test_alpaca_cancel_and_status_resolve_from_state_store_after_memory_loss(tmp_path):
    state_store = _store(tmp_path)
    submit_router = OrderRouter(
        primary_exchange="alpaca",
        paper_mode=False,
        rest_fallback_enabled=False,
        state_store=state_store,
    )
    submit_router._websocket_connected = True
    order = _order("alpaca-reload-client")
    submit_router._session.post = lambda *args, **kwargs: _MockResponse(
        200, {"id": "ALPACA-RELOAD-ID"}
    )

    assert submit_router.submit_order(order) is None

    reloaded = OrderRouter(
        primary_exchange="alpaca",
        paper_mode=False,
        rest_fallback_enabled=False,
        state_store=state_store,
    )
    reloaded._websocket_connected = True
    calls = []

    def get(url, timeout=None):
        calls.append(("get", url))
        return _MockResponse(200, {"status": "open"})

    def delete(url, timeout=None):
        calls.append(("delete", url))
        return _MockResponse(204, {})

    reloaded._session.get = get
    reloaded._session.delete = delete

    assert reloaded.get_order_status(order.id) == "open"
    assert reloaded.cancel_order(order.id) is True
    assert calls[0] == ("get", "https://paper-api.alpaca.markets/v2/orders/ALPACA-RELOAD-ID")
    assert calls[1] == ("delete", "https://paper-api.alpaca.markets/v2/orders/ALPACA-RELOAD-ID")
    assert order.id not in calls[0][1]
    assert order.id not in calls[1][1]


def test_missing_mapping_fails_closed_without_live_command(tmp_path):
    router = OrderRouter(
        primary_exchange="kraken",
        paper_mode=False,
        rest_fallback_enabled=False,
        state_store=_store(tmp_path),
    )
    router._websocket_connected = True
    calls = []
    router._session.post = lambda *args, **kwargs: calls.append((args, kwargs))

    assert router.cancel_order("missing-client-id") is False
    assert router.get_order_status("missing-client-id") == "unknown"
    assert calls == []


def test_conflicting_mapping_fails_closed(tmp_path):
    state_store = _store(tmp_path)
    first = _order("first-client")
    second = _order("second-client")
    router = OrderRouter(
        primary_exchange="kraken",
        paper_mode=False,
        rest_fallback_enabled=False,
        state_store=state_store,
    )
    router._websocket_connected = True
    assert router._register_active_order_id_mapping(
        first,
        broker="kraken",
        venue_order_id="DUP-TXID",
        broker_order_id=None,
        exchange_txid="DUP-TXID",
        id_mapping_source="test",
        ack_ts_ns=now_ns(),
    )
    assert not router._register_active_order_id_mapping(
        second,
        broker="kraken",
        venue_order_id="DUP-TXID",
        broker_order_id=None,
        exchange_txid="DUP-TXID",
        id_mapping_source="test",
        ack_ts_ns=now_ns(),
    )
    calls = []
    router._session.post = lambda *args, **kwargs: calls.append((args, kwargs))

    assert router.cancel_order(second.id) is False
    assert calls == []


def test_terminal_mapping_prevents_cancel_and_survives_reload(tmp_path):
    state_store = _store(tmp_path)
    order = _order("terminal-client")
    router = OrderRouter(
        primary_exchange="kraken",
        paper_mode=False,
        rest_fallback_enabled=False,
        state_store=state_store,
    )
    router._websocket_connected = True
    assert router._register_active_order_id_mapping(
        order,
        broker="kraken",
        venue_order_id="TERMINAL-TXID",
        broker_order_id=None,
        exchange_txid="TERMINAL-TXID",
        id_mapping_source="test",
        ack_ts_ns=now_ns(),
        status="filled",
        is_terminal=True,
        terminal_reason="test_terminal",
    )

    reloaded = OrderRouter(
        primary_exchange="kraken",
        paper_mode=False,
        rest_fallback_enabled=False,
        state_store=state_store,
    )
    reloaded._websocket_connected = True
    calls = []
    reloaded._session.post = lambda *args, **kwargs: calls.append((args, kwargs))

    assert reloaded.get_order_status(order.id) == "filled"
    assert reloaded.cancel_order(order.id) is False
    assert calls == []


def _mutation_snapshot(router: OrderRouter, state_store: StateStore, order_id: str, broker: str):
    return {
        "cache": dict(router._order_status_cache),
        "pending": dict(router._pending_orders),
        "mapping": state_store.get_order_id_mapping(order_id, broker),
    }


def _assert_mutation_snapshot_unchanged(router: OrderRouter, state_store: StateStore, order_id: str, broker: str, snapshot):
    assert dict(router._order_status_cache) == snapshot["cache"]
    assert dict(router._pending_orders) == snapshot["pending"]
    assert state_store.get_order_id_mapping(order_id, broker) == snapshot["mapping"]


def test_kraken_status_evidence_open_is_read_only_and_namespace_guarded(tmp_path):
    state_store = _store(tmp_path)
    router = OrderRouter(
        primary_exchange="kraken",
        paper_mode=False,
        rest_fallback_enabled=False,
        state_store=state_store,
    )
    order = _order("kraken-evidence-open")
    assert router._register_active_order_id_mapping(
        order,
        broker="kraken",
        venue_order_id="KRAKEN-EVIDENCE-OPEN",
        broker_order_id=None,
        exchange_txid="KRAKEN-EVIDENCE-OPEN",
        id_mapping_source="test",
        ack_ts_ns=now_ns(),
    )
    router._pending_orders[order.id] = order
    calls = []
    cancel_calls = []
    submit_calls = []
    router.cancel_order = lambda *args, **kwargs: cancel_calls.append((args, kwargs))
    router.submit_order = lambda *args, **kwargs: submit_calls.append((args, kwargs))

    def post(url, data=None, headers=None, timeout=None):
        calls.append({"url": url, "data": data})
        return _MockResponse(200, {"error": [], "result": {"KRAKEN-EVIDENCE-OPEN": {"status": "open"}}})

    router._session.post = post
    snapshot = _mutation_snapshot(router, state_store, order.id, "kraken")

    evidence = router.get_order_status_evidence(order.id)

    assert evidence["status_classification"] == "open_or_pending"
    assert evidence["terminal_observed"] is False
    assert evidence["status_refresh_succeeded"] is True
    assert evidence["command_id_namespace"] == "exchange_txid"
    assert evidence["command_order_id"] == "KRAKEN-EVIDENCE-OPEN"
    assert evidence["mutation_performed"] is False
    assert evidence["command_performed"] is False
    assert calls[0]["data"]["txid"] == "KRAKEN-EVIDENCE-OPEN"
    assert cancel_calls == []
    assert submit_calls == []
    _assert_mutation_snapshot_unchanged(router, state_store, order.id, "kraken", snapshot)


def test_kraken_status_evidence_terminal_is_not_terminal_mutation(tmp_path):
    state_store = _store(tmp_path)
    router = OrderRouter(
        primary_exchange="kraken",
        paper_mode=False,
        rest_fallback_enabled=False,
        state_store=state_store,
    )
    order = _order("kraken-evidence-terminal")
    assert router._register_active_order_id_mapping(
        order,
        broker="kraken",
        venue_order_id="KRAKEN-EVIDENCE-CLOSED",
        broker_order_id=None,
        exchange_txid="KRAKEN-EVIDENCE-CLOSED",
        id_mapping_source="test",
        ack_ts_ns=now_ns(),
    )
    router._pending_orders[order.id] = order
    router._session.post = lambda *args, **kwargs: _MockResponse(
        200,
        {"error": [], "result": {"KRAKEN-EVIDENCE-CLOSED": {"status": "closed"}}},
    )
    snapshot = _mutation_snapshot(router, state_store, order.id, "kraken")

    evidence = router.get_order_status_evidence(order.id)

    assert evidence["status_classification"] == "terminal_observed"
    assert evidence["terminal_observed"] is True
    assert evidence["status_raw"] == "closed"
    _assert_mutation_snapshot_unchanged(router, state_store, order.id, "kraken", snapshot)
    assert state_store.get_order_id_mapping(order.id, "kraken")["is_terminal"] is False


def test_alpaca_status_evidence_open_and_terminal_are_read_only(tmp_path):
    state_store = _store(tmp_path)
    router = OrderRouter(
        primary_exchange="alpaca",
        paper_mode=False,
        rest_fallback_enabled=False,
        state_store=state_store,
    )
    open_order = _order("alpaca-evidence-open")
    terminal_order = _order("alpaca-evidence-terminal")
    for order, venue_id in (
        (open_order, "ALPACA-EVIDENCE-OPEN"),
        (terminal_order, "ALPACA-EVIDENCE-FILLED"),
    ):
        assert router._register_active_order_id_mapping(
            order,
            broker="alpaca",
            venue_order_id=venue_id,
            broker_order_id=venue_id,
            exchange_txid=None,
            id_mapping_source="test",
            ack_ts_ns=now_ns(),
        )
        router._pending_orders[order.id] = order

    calls = []

    def get(url, timeout=None):
        calls.append(url)
        if url.endswith("ALPACA-EVIDENCE-FILLED"):
            return _MockResponse(200, {"status": "filled"})
        return _MockResponse(200, {"status": "accepted"})

    router._session.get = get
    open_snapshot = _mutation_snapshot(router, state_store, open_order.id, "alpaca")
    terminal_snapshot = _mutation_snapshot(router, state_store, terminal_order.id, "alpaca")

    open_evidence = router.get_order_status_evidence(open_order.id)
    terminal_evidence = router.get_order_status_evidence(terminal_order.id)

    assert open_evidence["status_classification"] == "open_or_pending"
    assert open_evidence["command_id_namespace"] == "venue_order_id"
    assert terminal_evidence["status_classification"] == "terminal_observed"
    assert terminal_evidence["terminal_observed"] is True
    assert calls == [
        "https://paper-api.alpaca.markets/v2/orders/ALPACA-EVIDENCE-OPEN",
        "https://paper-api.alpaca.markets/v2/orders/ALPACA-EVIDENCE-FILLED",
    ]
    _assert_mutation_snapshot_unchanged(router, state_store, open_order.id, "alpaca", open_snapshot)
    _assert_mutation_snapshot_unchanged(router, state_store, terminal_order.id, "alpaca", terminal_snapshot)


def test_status_evidence_missing_terminal_and_failed_mapping_no_request_no_mutation(tmp_path):
    state_store = _store(tmp_path)
    router = OrderRouter(
        primary_exchange="kraken",
        paper_mode=False,
        rest_fallback_enabled=False,
        state_store=state_store,
    )
    calls = []
    router._session.post = lambda *args, **kwargs: calls.append((args, kwargs))

    missing = router.get_order_status_evidence("missing-evidence-client")

    assert missing["status_classification"] == "mapping_missing_or_unsafe"
    assert missing["failure_reason"] == "missing_mapping"
    assert calls == []

    terminal_order = _order("terminal-evidence-client")
    assert router._register_active_order_id_mapping(
        terminal_order,
        broker="kraken",
        venue_order_id="TERMINAL-EVIDENCE-TXID",
        broker_order_id=None,
        exchange_txid="TERMINAL-EVIDENCE-TXID",
        id_mapping_source="test",
        ack_ts_ns=now_ns(),
        status="filled",
        is_terminal=True,
        terminal_reason="test_terminal",
    )
    terminal_snapshot = _mutation_snapshot(router, state_store, terminal_order.id, "kraken")

    terminal = router.get_order_status_evidence(terminal_order.id)

    assert terminal["status_classification"] == "mapping_missing_or_unsafe"
    assert terminal["failure_reason"] == "terminal_mapping"
    assert calls == []
    _assert_mutation_snapshot_unchanged(router, state_store, terminal_order.id, "kraken", terminal_snapshot)


def test_status_evidence_timeout_and_broker_orphan_are_fail_closed(tmp_path):
    state_store = _store(tmp_path)
    router = OrderRouter(
        primary_exchange="kraken",
        paper_mode=False,
        rest_fallback_enabled=False,
        state_store=state_store,
    )
    order = _order("timeout-evidence-client")
    assert router._register_active_order_id_mapping(
        order,
        broker="kraken",
        venue_order_id="TIMEOUT-EVIDENCE-TXID",
        broker_order_id=None,
        exchange_txid="TIMEOUT-EVIDENCE-TXID",
        id_mapping_source="test",
        ack_ts_ns=now_ns(),
    )

    def timeout(*args, **kwargs):
        raise TimeoutError("status timeout")

    router._session.post = timeout
    snapshot = _mutation_snapshot(router, state_store, order.id, "kraken")

    failed = router.get_order_status_evidence(order.id)
    orphan = router.get_order_status_evidence("")

    assert failed["status_classification"] == "unknown_or_failed"
    assert failed["failure_reason"] == "malformed_or_unavailable_response"
    assert orphan["status_classification"] == "broker_orphan_no_mapping"
    assert orphan["failure_reason"] == "missing_client_order_id"
    _assert_mutation_snapshot_unchanged(router, state_store, order.id, "kraken", snapshot)

    router._session.post = lambda *args, **kwargs: _MockResponse(429, {})
    assert router.get_order_status_evidence(order.id)["failure_reason"] == "rate_limited"
    router._session.post = lambda *args, **kwargs: _MockResponse(401, {})
    assert router.get_order_status_evidence(order.id)["failure_reason"] == "auth_failed"
    _assert_mutation_snapshot_unchanged(router, state_store, order.id, "kraken", snapshot)


def test_paper_status_evidence_absence_is_not_terminal_proof(tmp_path):
    state_store = _store(tmp_path)
    router = OrderRouter(paper_mode=True, state_store=state_store)
    order = _order("paper-absence-evidence")
    assert router._register_active_order_id_mapping(
        order,
        broker="paper",
        venue_order_id="PAPER-INTERNAL-PROOF",
        broker_order_id="PAPER-INTERNAL-PROOF",
        exchange_txid=None,
        id_mapping_source="test",
        ack_ts_ns=now_ns(),
    )
    router._pending_orders[order.id] = order
    snapshot = _mutation_snapshot(router, state_store, order.id, "paper")

    evidence = router.get_order_status_evidence(order.id)

    assert evidence["command_id_namespace"] == "client_order_id"
    assert evidence["command_order_id"] == order.id
    assert evidence["status_classification"] == "unknown_or_failed"
    assert evidence["terminal_observed"] is False
    assert evidence["failure_reason"] == "paper_order_absent_not_terminal_proof"
    _assert_mutation_snapshot_unchanged(router, state_store, order.id, "paper", snapshot)


def test_main_bootstrap_injects_state_store_into_order_router():
    source = Path("main.py").read_text(encoding="utf-8")

    assert "from app.state.state_store import StateStore" in source
    assert 'self.state_store = StateStore(db_path="data/state.db")' in source
    assert "state_store=self.state_store" in source
