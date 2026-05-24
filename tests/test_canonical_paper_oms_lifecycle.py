from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from urllib.parse import urlparse
from unittest.mock import MagicMock

from app.commander import Commander
from app.execution.alpaca_paper_adapter import (
    EXPECTED_ALPACA_PAPER_BASE_URL,
    AlpacaPaperBrokerAdapter,
    AlpacaPaperCredentials,
)
from app.execution.engine import ExecutionEngine
from app.execution.oms_lifecycle import OmsOrderState, OmsReasonCode
from app.execution.order_router import OrderRouter
from app.models import OrderRequest
from app.models.enums import OrderSide, OrderType, SleeveType
from app.state.state_store import StateStore


T0_NS = 1_779_600_000_000_000_000


class RoutingTransport:
    def __init__(self, responses: dict[tuple[str, str], tuple[int, object]] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[dict[str, object]] = []

    def request(self, *, method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: float):
        path = urlparse(url).path
        parsed_body = json.loads(body.decode("utf-8")) if body else None
        self.calls.append({"method": method, "path": path, "body": parsed_body, "timeout": timeout})
        return self.responses.get((method, path), (200, {}))


class NoCancelAdapter:
    def __init__(self) -> None:
        self.request_counts = {"GET": 0, "POST": 0}
        self.identity = SimpleNamespace(
            adapter_id="alpaca_paper_rest",
            venue_id="alpaca",
            portal_id="alpaca_paper",
            environment="paper",
            base_url=EXPECTED_ALPACA_PAPER_BASE_URL,
            credential_status="configured",
            supported_methods=frozenset({"GET", "POST"}),
            supported_asset_classes=frozenset({"crypto"}),
            live_blocked=True,
        )


def _creds() -> AlpacaPaperCredentials:
    return AlpacaPaperCredentials(
        base_url=EXPECTED_ALPACA_PAPER_BASE_URL,
        key_id="paper-key",
        secret_key="paper-secret",
    )


def _state_store(tmp_path) -> StateStore:
    return StateStore(str(tmp_path / "state.db"))


def _order(order_id: str = "client-1", symbol: str = "BTC/USD") -> OrderRequest:
    return OrderRequest(
        id=order_id,
        symbol=symbol,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.01"),
        limit_price=Decimal("75000"),
        strategy=SleeveType.SECTOR_ROTATION,
        confidence=0.9,
        decision_uuid=f"decision-{order_id}",
        exchange_ts_ns=T0_NS,
        receive_ts_ns=T0_NS,
        metadata={
            "venue_id": "alpaca",
            "portal_name": "alpaca_paper",
            "environment": "paper",
            "asset_class": "crypto",
            "execution_adapter": "alpaca_paper_rest",
            "time_in_force": "gtc",
        },
    )


def _adapter_with_ack(status_payload: dict | None = None, *, delete_status: int = 204) -> tuple[AlpacaPaperBrokerAdapter, RoutingTransport]:
    status_payload = status_payload or {
        "id": "broker-1",
        "client_order_id": "client-1",
        "status": "open",
        "symbol": "BTCUSD",
    }
    transport = RoutingTransport(
        {
            ("POST", "/v2/orders"): (
                200,
                {
                    "id": "broker-1",
                    "client_order_id": "client-1",
                    "status": "accepted",
                    "symbol": "BTCUSD",
                },
            ),
            ("GET", "/v2/orders/broker-1"): (200, status_payload),
            ("GET", "/v2/orders"): (200, [status_payload]),
            ("GET", "/v2/positions"): (200, [{"symbol": "BTCUSD", "qty": "0.01"}]),
            ("GET", "/v2/account"): (200, {"status": "ACTIVE"}),
            ("DELETE", "/v2/orders/broker-1"): (delete_status, {}),
        }
    )
    return AlpacaPaperBrokerAdapter(_creds(), transport=transport), transport


def test_broker_ack_maps_cleanly_and_telemetry_is_honest(tmp_path):
    adapter, transport = _adapter_with_ack()
    router = OrderRouter(
        primary_exchange="alpaca",
        paper_mode=True,
        execution_broker="alpaca_paper",
        broker_gateway_adapter=adapter,
        state_store=_state_store(tmp_path),
    )
    order = _order()

    fill = router.submit_order(order)
    response = router.get_gateway_response(order.id)
    reconciliation = router.get_gateway_reconciliation(order.id)
    mapping = router._state_store.get_order_id_mapping(order.id, "alpaca")
    accounting = router.get_oms_shutdown_accounting()

    assert fill is None
    assert response is not None
    assert response.broker_order_id == "broker-1"
    assert mapping["broker_order_id"] == "broker-1"
    assert reconciliation["status"] == OmsOrderState.OPEN.value
    boundary = accounting["broker_boundary_events"][-1]
    assert boundary["broker_post_attempted"] is True
    assert boundary["broker_post_authorized"] is True
    assert boundary["broker_post_acknowledged"] is True
    assert boundary["broker_order_id"] == "broker-1"
    assert accounting["mutation_method_counts"]["POST"] == 1
    assert [call["method"] for call in transport.calls].count("POST") == 1


def test_unauthorized_cancel_denied_once_without_spam():
    router = OrderRouter(
        primary_exchange="alpaca",
        paper_mode=True,
        execution_broker="alpaca_paper",
        broker_gateway_adapter=NoCancelAdapter(),
    )

    assert router.cancel_order("client-no-cancel") is False
    assert router.cancel_order("client-no-cancel") is False

    accounting = router.get_oms_shutdown_accounting()
    assert accounting["cancel_denied_count"] == 1
    assert accounting["cancel_denials"]["client-no-cancel"] == OmsReasonCode.CAPABILITY_UNAUTHORIZED.value


def test_authorized_paper_cancel_uses_gateway_delete_and_terminalizes_mapping(tmp_path):
    adapter, transport = _adapter_with_ack()
    router = OrderRouter(
        primary_exchange="alpaca",
        paper_mode=True,
        execution_broker="alpaca_paper",
        broker_gateway_adapter=adapter,
        state_store=_state_store(tmp_path),
    )
    order = _order()
    router.submit_order(order)

    assert router.cancel_order(order.id) is True

    mapping = router._state_store.get_order_id_mapping(order.id, "alpaca")
    accounting = router.get_oms_shutdown_accounting()
    assert mapping["is_terminal"] is True
    assert mapping["status"] == "canceled"
    assert order.id not in router._pending_orders
    assert any(call["method"] == "DELETE" and call["path"] == "/v2/orders/broker-1" for call in transport.calls)
    assert accounting["cancel_authorized_count"] == 1
    assert accounting["mutation_method_counts"]["DELETE"] == 1


def test_zombie_sweeper_handles_timezone_datetime_order_timestamps_without_error():
    router = MagicMock()
    router.cancel_order.return_value = False
    risk_guard = MagicMock()
    risk_guard.register_recalibrate_callback = MagicMock()
    risk_guard.register_emergency_callback = MagicMock()
    risk_guard.register_zombie_callback = MagicMock()
    risk_guard.register_lag_callback = MagicMock()
    risk_guard.register_vol_fuse_callback = MagicMock()
    risk_guard.update_pending_orders = MagicMock()
    engine = ExecutionEngine(
        commander=MagicMock(spec=Commander),
        risk_guard=risk_guard,
        order_router=router,
        masking_layer=MagicMock(),
        max_pending_age_sec=1.0,
    )
    engine._state.pending_orders["dt-order"] = SimpleNamespace(
        exchange_ts_ns=datetime.fromtimestamp(1, tz=timezone.utc),
        receive_ts_ns=datetime.fromtimestamp(1, tz=timezone.utc),
        quantity=Decimal("1"),
        limit_price=Decimal("1"),
    )

    engine._sweep_zombie_orders()

    router.cancel_order.assert_called_once_with("dt-order")
    assert engine.get_oms_shutdown_accounting()["zombie_sweeper_errors"] == 0


def test_stale_terminal_mapping_does_not_trigger_unsafe_cancel_mutation(tmp_path):
    adapter, transport = _adapter_with_ack()
    state_store = _state_store(tmp_path)
    state_store.upsert_order_id_mapping(
        {
            "client_order_id": "old-client",
            "broker": "alpaca",
            "symbol": "BTC/USD",
            "side": "buy",
            "order_type": "limit",
            "venue_order_id": "broker-old",
            "broker_order_id": "broker-old",
            "exchange_txid": None,
            "command_id_namespace": "venue_order_id",
            "command_order_id": "broker-old",
            "id_mapping_source": "test",
            "submit_ts_ns": T0_NS,
            "ack_ts_ns": T0_NS,
            "status": "canceled",
            "is_terminal": True,
            "terminal_reason": "already_terminal",
        }
    )
    router = OrderRouter(
        primary_exchange="alpaca",
        paper_mode=True,
        execution_broker="alpaca_paper",
        broker_gateway_adapter=adapter,
        state_store=state_store,
    )

    assert router.cancel_order("old-client") is False

    assert not any(call["method"] == "DELETE" for call in transport.calls)
    assert router.get_oms_shutdown_accounting()["cancel_denials"]["old-client"] == OmsReasonCode.CANCEL_ALREADY_ATTEMPTED.value


def test_startup_reconciles_persisted_ack_mapping_with_broker_truth_without_mutation(tmp_path):
    state_store = _state_store(tmp_path)
    state_store.upsert_order_id_mapping(
        {
            "client_order_id": "old-open-client",
            "broker": "alpaca",
            "symbol": "BTC/USD",
            "side": "buy",
            "order_type": "limit",
            "venue_order_id": "broker-missing",
            "broker_order_id": "broker-missing",
            "exchange_txid": None,
            "command_id_namespace": "venue_order_id",
            "command_order_id": "broker-missing",
            "id_mapping_source": "prior_runtime_ack",
            "submit_ts_ns": T0_NS,
            "ack_ts_ns": T0_NS,
            "status": "acknowledged",
            "is_terminal": False,
            "terminal_reason": None,
        }
    )
    transport = RoutingTransport(
        {
            ("GET", "/v2/orders/broker-missing"): (404, {"message": "order not found"}),
            ("GET", "/v2/orders"): (200, []),
            ("GET", "/v2/positions"): (200, [{"symbol": "BTCUSD", "qty": "0.01"}]),
            ("GET", "/v2/account"): (200, {"status": "ACTIVE"}),
        }
    )
    adapter = AlpacaPaperBrokerAdapter(_creds(), transport=transport)

    router = OrderRouter(
        primary_exchange="alpaca",
        paper_mode=True,
        execution_broker="alpaca_paper",
        broker_gateway_adapter=adapter,
        state_store=state_store,
    )

    mapping = state_store.get_order_id_mapping("old-open-client", "alpaca")
    reconciliation = router.get_gateway_reconciliation("old-open-client")
    methods = [call["method"] for call in transport.calls]

    assert mapping["is_terminal"] is True
    assert mapping["status"] == "reconciliation_conflict"
    assert reconciliation["status"] == OmsOrderState.RECONCILIATION_CONFLICT.value
    assert OmsReasonCode.BROKER_STATE_UNKNOWN.value in reconciliation["reason_codes"]
    assert methods.count("GET") == 4
    assert "POST" not in methods
    assert "DELETE" not in methods
    assert router.get_oms_shutdown_accounting()["reconciliation_conflicts"] >= 1


def test_post_ack_reconciliation_conflict_fails_closed(tmp_path):
    adapter, _transport = _adapter_with_ack(
        {
            "id": "broker-1",
            "client_order_id": "client-1",
            "status": "open",
            "symbol": "ETHUSD",
        }
    )
    router = OrderRouter(
        primary_exchange="alpaca",
        paper_mode=True,
        execution_broker="alpaca_paper",
        broker_gateway_adapter=adapter,
        state_store=_state_store(tmp_path),
    )
    order = _order()

    router.submit_order(order)

    reconciliation = router.get_gateway_reconciliation(order.id)
    mapping = router._state_store.get_order_id_mapping(order.id, "alpaca")
    assert reconciliation["status"] == OmsOrderState.RECONCILIATION_CONFLICT.value
    assert OmsReasonCode.RECONCILIATION_CONFLICT.value in reconciliation["reason_codes"]
    assert mapping["is_terminal"] is True
    assert mapping["status"] == "reconciliation_conflict"
    assert order.id not in router._pending_orders
