import json
from decimal import Decimal

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
