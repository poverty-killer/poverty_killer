from decimal import Decimal
from types import SimpleNamespace

from app.core.truth_reconciler import TruthReconciler
from app.execution.order_router import OrderRouter
from app.main_loop import MainLoop
from app.models.contracts import (
    ExchangeOpenOrder,
    ExchangeTruth,
    ExecutionTruth,
    PortfolioTruth,
    RiskTruth,
    StrategyTruth,
    SubmittedOrder,
)
from app.models.enums import InternalOrderStatus, OrderSide, OrderType, RiskMode, SleeveType
from app.models.orders import OrderRequest
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


def _submitted(client_order_id: str) -> SubmittedOrder:
    return SubmittedOrder(
        client_order_id=client_order_id,
        status=InternalOrderStatus.SUBMITTED,
        submitted_ts_ns=now_ns(),
    )


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


def _exchange(open_orders) -> ExchangeTruth:
    return ExchangeTruth(venue="kraken", open_orders=open_orders, exchange_ts_ns=now_ns())


def _execution(submitted_orders) -> ExecutionTruth:
    return ExecutionTruth(
        submitted_orders=submitted_orders,
        last_reconciliation_ts_ns=now_ns(),
    )


def _open_order(**overrides) -> ExchangeOpenOrder:
    fields = {
        "order_id": "KRAKEN-TXID",
        "order_id_namespace": "exchange_txid",
        "symbol": "ETHUSD",
        "side": OrderSide.BUY,
        "quantity": Decimal("1.0"),
        "limit_price": Decimal("2900"),
        "mapping_status": "broker_orphan",
    }
    fields.update(overrides)
    return ExchangeOpenOrder(**fields)


def _alerts(open_orders, submitted_orders, status_refresh=None):
    return TruthReconciler().build_alert_evidence(
        exchange_truth=_exchange(open_orders),
        execution_truth=_execution(submitted_orders),
        portfolio_truth=PortfolioTruth(),
        strategy_truth=StrategyTruth(),
        risk_truth=RiskTruth(mode=RiskMode.NORMAL),
        status_refresh=status_refresh,
    )


def _reason(alerts, reason_code):
    return [alert for alert in alerts if alert["reason_code"] == reason_code]


def test_broker_orphan_alert_is_evidence_only_no_command():
    commands = []

    alerts = _alerts([_open_order(order_id="UNMAPPED-TXID")], [], status_refresh=lambda _: commands.append("status"))

    orphan = _reason(alerts, "broker_orphan_unresolved")
    assert orphan
    assert orphan[0]["severity"] == "warning"
    assert "auto_cancel" in orphan[0]["prohibited_actions"]
    assert commands == []


def test_local_pending_alert_does_not_terminalize_without_status_refresh():
    submitted = _submitted("local-client-only")

    alerts = _alerts([], [submitted])

    local = _reason(alerts, "local_pending_unresolved")
    assert local
    assert submitted.status == InternalOrderStatus.SUBMITTED
    assert not _reason(alerts, "broker_terminal_local_pending_requires_status_proof")


def test_terminal_local_broker_open_is_critical_and_no_cancel():
    cancel_calls = []
    order = _open_order(
        order_id="TERMINAL-OPEN-TXID",
        client_order_id="terminal-client",
        mapping_status="terminal_local_broker_open",
        command_id_namespace="exchange_txid",
        command_order_id="TERMINAL-OPEN-TXID",
    )

    alerts = _alerts([order], [_submitted("terminal-client")], status_refresh=lambda _: cancel_calls.append("status"))

    terminal = _reason(alerts, "terminal_local_broker_open")
    assert terminal
    assert terminal[0]["severity"] == "critical"
    assert "auto_cancel" in terminal[0]["prohibited_actions"]
    assert cancel_calls == []


def test_missing_and_conflicting_mapping_statuses_are_alertable_fail_closed():
    alerts = _alerts(
        [
            _open_order(order_id="MISSING", mapping_status="missing_mapping_unresolved"),
            _open_order(order_id="DUP", mapping_status="duplicate_mapping_conflict", client_order_id="dup-client"),
            _open_order(order_id="SAME", mapping_status="same_client_mapping_conflict", client_order_id="same-client"),
        ],
        [],
    )

    assert _reason(alerts, "missing_mapping_unresolved")[0]["requires_board_decision"] is True
    assert _reason(alerts, "duplicate_mapping_conflict")[0]["severity"] == "critical"
    assert _reason(alerts, "same_client_mapping_conflict")[0]["severity"] == "critical"
    for code in ("missing_mapping_unresolved", "duplicate_mapping_conflict", "same_client_mapping_conflict"):
        assert "live_command" in _reason(alerts, code)[0]["prohibited_actions"]


def test_paper_internal_client_mismatch_alert_preserves_client_command_namespace():
    order = _open_order(
        order_id="PAPER-INTERNAL-ID",
        order_id_namespace="paper_broker_internal_order_id",
        client_order_id="paper-client",
        command_id_namespace="client_order_id",
        command_order_id="different-client",
        mapping_status="mapped",
    )

    alerts = _alerts([order], [_submitted("paper-client")])

    mismatch = _reason(alerts, "paper_internal_client_mismatch")[0]
    assert mismatch["severity"] == "warning"
    assert mismatch["command_id_namespace"] == "client_order_id"
    assert mismatch["command_order_id"] == "different-client"
    assert "namespace_collapse" in mismatch["prohibited_actions"]


def test_guarded_status_refresh_uses_order_router_mapping_path_without_cancel(tmp_path):
    state_store = _store(tmp_path)
    router = OrderRouter(
        primary_exchange="kraken",
        paper_mode=False,
        rest_fallback_enabled=False,
        state_store=state_store,
    )
    router._websocket_connected = True
    order = _order("refresh-client")
    assert router._register_active_order_id_mapping(
        order,
        broker="kraken",
        venue_order_id="REFRESH-TXID",
        broker_order_id=None,
        exchange_txid="REFRESH-TXID",
        id_mapping_source="test",
        ack_ts_ns=now_ns(),
    )
    calls = []

    def post(url, data=None, headers=None, timeout=None):
        calls.append({"url": url, "data": data})
        return _MockResponse(200, {"error": [], "result": {"REFRESH-TXID": {"status": "open"}}})

    router._session.post = post

    alerts = _alerts([], [_submitted(order.id)], status_refresh=router.get_order_status_evidence)

    assert _reason(alerts, "local_pending_unresolved")
    assert not _reason(alerts, "status_refresh_failed")
    assert not _reason(alerts, "broker_terminal_local_pending_requires_status_proof")
    assert len(calls) == 1
    assert "QueryOrders" in calls[0]["url"]
    assert calls[0]["data"]["txid"] == "REFRESH-TXID"


def test_broker_terminal_status_refresh_is_evidence_not_reconciler_terminalization(tmp_path):
    state_store = _store(tmp_path)
    router = OrderRouter(
        primary_exchange="kraken",
        paper_mode=False,
        rest_fallback_enabled=False,
        state_store=state_store,
    )
    router._websocket_connected = True
    order = _order("terminal-refresh-client")
    assert router._register_active_order_id_mapping(
        order,
        broker="kraken",
        venue_order_id="TERMINAL-REFRESH-TXID",
        broker_order_id=None,
        exchange_txid="TERMINAL-REFRESH-TXID",
        id_mapping_source="test",
        ack_ts_ns=now_ns(),
    )
    router._session.post = lambda *args, **kwargs: _MockResponse(
        200,
        {"error": [], "result": {"TERMINAL-REFRESH-TXID": {"status": "closed"}}},
    )
    submitted = _submitted(order.id)

    before_mapping = state_store.get_order_id_mapping(order.id, "kraken")

    alerts = _alerts([], [submitted], status_refresh=router.get_order_status_evidence)

    assert _reason(alerts, "broker_terminal_local_pending_requires_status_proof")
    assert submitted.status == InternalOrderStatus.SUBMITTED
    assert state_store.get_order_id_mapping(order.id, "kraken") == before_mapping


def test_status_refresh_timeout_or_malformed_emits_failed_alert_and_preserves_pending():
    submitted = _submitted("timeout-client")

    def timeout(_client_order_id):
        raise TimeoutError("status timeout")

    alerts = _alerts([], [submitted], status_refresh=timeout)

    failed = _reason(alerts, "status_refresh_failed")
    assert failed
    assert "auto_terminalize" in failed[0]["prohibited_actions"]
    assert submitted.status == InternalOrderStatus.SUBMITTED

    for status in ("malformed", "rate_limited"):
        pending = _submitted(f"{status}-client")
        status_alerts = _alerts([], [pending], status_refresh=lambda _client_order_id, value=status: value)
        assert _reason(status_alerts, "status_refresh_failed")
        assert pending.status == InternalOrderStatus.SUBMITTED


def test_restart_recovery_needed_alert_only_for_mapped_broker_order_empty_pending():
    order = _open_order(
        order_id="RESTART-TXID",
        client_order_id="restart-client",
        mapping_status="mapped",
        command_id_namespace="exchange_txid",
        command_order_id="RESTART-TXID",
    )

    alerts = _alerts([order], [])

    recovery = _reason(alerts, "restart_recovery_needed")
    assert recovery
    assert "pending_rebuild" in recovery[0]["prohibited_actions"]
    assert not _reason(alerts, "local_pending_unresolved")


def test_main_loop_surfaces_reconcile_alerts_without_execution_side_effects():
    class FakeOrderRouter:
        def __init__(self):
            self.cancel_calls = 0
            self.submit_calls = 0
            self.status_calls = 0

        def get_exchange_truth_snapshot(self, symbol):
            return {
                "balances": {},
                "positions": [],
                "open_orders": [
                    {
                        "order_id": "UNMAPPED-TXID",
                        "order_id_namespace": "exchange_txid",
                        "symbol": symbol,
                        "side": "buy",
                        "quantity": "1.0",
                        "limit_price": "2900",
                        "mapping_status": "broker_orphan",
                    }
                ],
                "fills_since_last_call": [],
            }

        def get_order_status(self, *_args, **_kwargs):
            self.status_calls += 1
            return "unknown"

        def cancel_order(self, *_args, **_kwargs):
            self.cancel_calls += 1
            return False

        def submit_order(self, *_args, **_kwargs):
            self.submit_calls += 1

    router = FakeOrderRouter()
    loop = MainLoop.__new__(MainLoop)
    loop.symbol = "ETHUSD"
    loop.exchange = "kraken"
    loop.execution_engine = SimpleNamespace(
        order_router=router,
        _state=SimpleNamespace(pending_orders={}, filled_orders=[]),
    )
    loop._last_price = 2900.0
    loop._last_equity = 0.0
    loop._last_risk_state = None
    loop._primary_runtime = SimpleNamespace(shadow_front_strategy=None)
    loop.strategy_router = SimpleNamespace()

    frame = loop._build_truth_frame(now_ns())

    assert _reason(frame.reconcile_alerts, "broker_orphan_unresolved")
    assert frame.status == "drifting"
    assert router.cancel_calls == 0
    assert router.submit_calls == 0
    assert router.status_calls == 0
