from decimal import Decimal

from app.core.truth_reconciler import TruthReconciler
from app.execution.order_router import OrderRouter
from app.models import OrderRequest
from app.models.contracts import ExchangeOpenOrder, ExchangeTruth, ExecutionTruth, SubmittedOrder
from app.models.enums import InternalOrderStatus, OrderSide, OrderType, SleeveType
from app.state.state_store import StateStore
from app.utils.time_utils import now_ns


class _MockResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def _store(tmp_path) -> StateStore:
    return StateStore(str(tmp_path / "state.db"))


def _order(order_id: str) -> OrderRequest:
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


def _submitted(client_order_id: str) -> SubmittedOrder:
    return SubmittedOrder(
        client_order_id=client_order_id,
        status=InternalOrderStatus.SUBMITTED,
        submitted_ts_ns=now_ns(),
    )


def _compare_exchange_execution(open_orders, submitted_orders):
    exchange = ExchangeTruth(
        venue="test",
        open_orders=open_orders,
        exchange_ts_ns=now_ns(),
    )
    execution = ExecutionTruth(
        submitted_orders=submitted_orders,
        last_reconciliation_ts_ns=now_ns(),
    )
    return TruthReconciler()._compare_exchange_execution(exchange, execution)


def _open_order_from_fact(fact: dict) -> ExchangeOpenOrder:
    fields = {
        "order_id",
        "symbol",
        "side",
        "quantity",
        "limit_price",
        "order_id_namespace",
        "client_order_id",
        "venue_order_id",
        "broker_order_id",
        "exchange_txid",
        "command_id_namespace",
        "command_order_id",
        "mapping_status",
        "is_terminal_mapping",
        "terminal_reason",
    }
    return ExchangeOpenOrder(**{key: value for key, value in fact.items() if key in fields})


def test_kraken_mapped_open_order_reconciles_by_client_id_not_raw_txid(tmp_path):
    state_store = _store(tmp_path)
    router = OrderRouter(primary_exchange="kraken", paper_mode=False, state_store=state_store)
    order = _order("kraken-client-reconcile")
    assert router._register_active_order_id_mapping(
        order,
        broker="kraken",
        venue_order_id="KRAKEN-OPEN-TXID",
        broker_order_id=None,
        exchange_txid="KRAKEN-OPEN-TXID",
        id_mapping_source="test",
        ack_ts_ns=now_ns(),
    )
    router._call_kraken_private = lambda *args, **kwargs: {
        "open": {
            "KRAKEN-OPEN-TXID": {
                "descr": {"pair": "ETHUSD", "type": "buy", "ordertype": "limit", "price": "2900"},
                "vol": "1.0",
                "vol_exec": "0",
                "status": "open",
                "opentm": 1,
            }
        }
    }

    facts = router.fetch_normalized_open_orders()
    assert facts[0]["order_id_namespace"] == "exchange_txid"
    assert facts[0]["order_id"] == "KRAKEN-OPEN-TXID"
    assert facts[0]["client_order_id"] == order.id

    open_order = _open_order_from_fact(facts[0])
    divergences = _compare_exchange_execution([open_order], [_submitted(order.id)])
    assert divergences == []


def test_alpaca_mapped_open_order_reconciles_by_client_id_not_raw_venue_id(tmp_path):
    state_store = _store(tmp_path)
    router = OrderRouter(primary_exchange="alpaca", paper_mode=False, state_store=state_store)
    order = _order("alpaca-client-reconcile")
    assert router._register_active_order_id_mapping(
        order,
        broker="alpaca",
        venue_order_id="ALPACA-OPEN-ID",
        broker_order_id="ALPACA-OPEN-ID",
        exchange_txid=None,
        id_mapping_source="test",
        ack_ts_ns=now_ns(),
    )
    router._session.get = lambda *args, **kwargs: _MockResponse(
        200,
        [
            {
                "id": "ALPACA-OPEN-ID",
                "symbol": "ETH/USD",
                "side": "buy",
                "type": "limit",
                "qty": "1.0",
                "filled_qty": "0",
                "limit_price": "2900",
                "status": "open",
            }
        ],
    )

    facts = router.fetch_normalized_open_orders()
    assert facts[0]["order_id_namespace"] == "venue_order_id"
    assert facts[0]["order_id"] == "ALPACA-OPEN-ID"
    assert facts[0]["client_order_id"] == order.id

    open_order = _open_order_from_fact(facts[0])
    divergences = _compare_exchange_execution([open_order], [_submitted(order.id)])
    assert divergences == []


def test_paper_reconcile_uses_client_id_and_preserves_internal_order_id_as_proof(tmp_path):
    router = OrderRouter(paper_mode=True, state_store=_store(tmp_path))
    order = _order("paper-client-reconcile")

    assert router.submit_order(order) is None

    facts = router.fetch_normalized_open_orders()
    assert facts[0]["client_order_id"] == order.id
    assert facts[0]["command_id_namespace"] == "client_order_id"
    assert facts[0]["command_order_id"] == order.id
    assert facts[0]["order_id_namespace"] == "paper_broker_internal_order_id"
    assert facts[0]["order_id"] != order.id

    open_order = _open_order_from_fact(facts[0])
    divergences = _compare_exchange_execution([open_order], [_submitted(order.id)])
    assert divergences == []


def test_broker_open_order_without_mapping_is_unresolved_orphan_not_raw_compare():
    open_order = ExchangeOpenOrder(
        order_id="KRAKEN-UNMAPPED-TXID",
        order_id_namespace="exchange_txid",
        symbol="ETHUSD",
        side=OrderSide.BUY,
        quantity=Decimal("1.0"),
        mapping_status="broker_orphan",
    )

    divergences = _compare_exchange_execution([open_order], [])

    assert len(divergences) == 1
    assert divergences[0].field == "broker_orphan_unresolved"
    assert "KRAKEN-UNMAPPED-TXID" in divergences[0].observed


def test_local_pending_without_broker_open_order_is_unresolved_not_terminal():
    divergences = _compare_exchange_execution([], [_submitted("local-client-only")])

    assert len(divergences) == 1
    assert divergences[0].field == "local_pending_unresolved"
    assert "local-client-only" in divergences[0].observed


def test_terminal_local_mapping_with_broker_open_order_is_critical_drift(tmp_path):
    state_store = _store(tmp_path)
    router = OrderRouter(primary_exchange="kraken", paper_mode=False, state_store=state_store)
    order = _order("terminal-client-reconcile")
    assert router._register_active_order_id_mapping(
        order,
        broker="kraken",
        venue_order_id="TERMINAL-OPEN-TXID",
        broker_order_id=None,
        exchange_txid="TERMINAL-OPEN-TXID",
        id_mapping_source="test",
        ack_ts_ns=now_ns(),
        status="filled",
        is_terminal=True,
        terminal_reason="test_terminal",
    )
    router._call_kraken_private = lambda *args, **kwargs: {
        "open": {
            "TERMINAL-OPEN-TXID": {
                "descr": {"pair": "ETHUSD", "type": "buy", "ordertype": "limit", "price": "2900"},
                "vol": "1.0",
                "vol_exec": "0",
                "status": "open",
            }
        }
    }

    facts = router.fetch_normalized_open_orders()
    assert facts[0]["mapping_status"] == "terminal_local_broker_open"

    open_order = _open_order_from_fact(facts[0])
    divergences = _compare_exchange_execution([open_order], [_submitted(order.id)])
    assert any(d.field == "terminal_local_broker_open" and d.severity == "critical" for d in divergences)


def test_reconcile_namespace_proof_does_not_issue_cancel_or_status_commands(tmp_path):
    router = OrderRouter(primary_exchange="kraken", paper_mode=False, state_store=_store(tmp_path))
    commands = []
    router._session.post = lambda *args, **kwargs: commands.append((args, kwargs))

    open_order = ExchangeOpenOrder(
        order_id="KRAKEN-UNMAPPED-TXID",
        order_id_namespace="exchange_txid",
        symbol="ETHUSD",
        side=OrderSide.BUY,
        quantity=Decimal("1.0"),
        mapping_status="broker_orphan",
    )
    _compare_exchange_execution([open_order], [_submitted("local-client-only")])

    assert commands == []
