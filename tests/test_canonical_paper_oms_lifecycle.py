from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from urllib.parse import urlparse
from unittest.mock import MagicMock

import app.execution.engine as engine_module
from app.commander import Commander
from app.execution.alpaca_paper_adapter import (
    EXPECTED_ALPACA_PAPER_BASE_URL,
    AlpacaPaperBrokerAdapter,
    AlpacaPaperCredentials,
)
from app.execution.broker_read_policy import PAPER_TCA_EXTENDED_READS
from app.execution.engine import ExecutionEngine
from app.execution.oms_lifecycle import OmsOrderState, OmsReasonCode
from app.execution.order_router import OrderRouter
from app.models import OrderRequest
from app.models.enums import OrderSide, OrderType, SleeveType
from app.risk.guard import HybridRiskGuard
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
    return AlpacaPaperBrokerAdapter(_creds(), transport=transport, read_profile=PAPER_TCA_EXTENDED_READS), transport


def _persist_mapping(
    state_store: StateStore,
    *,
    client_order_id: str = "old-open-client",
    broker_order_id: str = "broker-old",
    status: str = "acknowledged",
    is_terminal: bool = False,
    symbol: str = "BTC/USD",
) -> None:
    state_store.upsert_order_id_mapping(
        {
            "client_order_id": client_order_id,
            "broker": "alpaca",
            "symbol": symbol,
            "side": "buy",
            "order_type": "limit",
            "venue_order_id": broker_order_id,
            "broker_order_id": broker_order_id,
            "exchange_txid": None,
            "command_id_namespace": "venue_order_id",
            "command_order_id": broker_order_id,
            "id_mapping_source": "test",
            "submit_ts_ns": T0_NS,
            "ack_ts_ns": T0_NS,
            "status": status,
            "is_terminal": is_terminal,
            "terminal_reason": "test_terminal" if is_terminal else None,
        }
    )


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
    assert accounting["order_post_attempted"] == 1
    assert accounting["order_post_acknowledged"] == 1
    assert accounting["cancel_acknowledged"] == 0
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
    assert accounting["cancel_attempted"] == 1
    assert accounting["cancel_acknowledged"] == 1
    assert accounting["active_pending_orders"] == 0
    assert accounting["pending_terminal_leak_count"] == 0
    assert accounting["mutation_method_counts"]["DELETE"] == 1


def test_zombie_sweeper_handles_ns_datetime_and_iso_order_timestamps_without_error():
    router = MagicMock()
    router.cancel_order.return_value = False
    router.is_order_terminal.return_value = False
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
    timestamp_cases = {
        "ns-order": T0_NS,
        "dt-order": datetime.fromtimestamp(1, tz=timezone.utc),
        "iso-order": "1970-01-01T00:00:01+00:00",
    }
    for order_id, timestamp in timestamp_cases.items():
        engine._state.pending_orders[order_id] = SimpleNamespace(
            exchange_ts_ns=timestamp,
            receive_ts_ns=timestamp,
            quantity=Decimal("1"),
            limit_price=Decimal("1"),
        )

    engine._sweep_zombie_orders()

    assert {call.args[0] for call in router.cancel_order.call_args_list} == set(timestamp_cases)
    assert engine.get_oms_shutdown_accounting()["zombie_sweeper_errors"] == 0


def test_zombie_sweeper_ages_pending_orders_from_receive_timestamp_not_signal_candle(monkeypatch):
    current_ns = T0_NS + 70_000_000_000
    fresh_submit_ns = current_ns - 2_000_000_000
    stale_signal_candle_ns = current_ns - 65_000_000_000
    router = MagicMock()
    router.cancel_order.return_value = False
    router.is_order_terminal.return_value = False
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
        max_pending_age_sec=5.0,
    )
    engine._state.pending_orders["fresh-submit-stale-candle"] = SimpleNamespace(
        exchange_ts_ns=stale_signal_candle_ns,
        receive_ts_ns=fresh_submit_ns,
        quantity=Decimal("1"),
        limit_price=Decimal("1"),
    )
    monkeypatch.setattr(engine_module, "now_ns", lambda: current_ns)

    engine._sweep_zombie_orders()

    router.cancel_order.assert_not_called()
    risk_guard.update_pending_orders.assert_called_once()
    assert risk_guard.update_pending_orders.call_args.kwargs["oldest_timestamp"] == datetime.fromtimestamp(
        fresh_submit_ns / 1_000_000_000,
        tz=timezone.utc,
    )


def test_risk_guard_accepts_pending_order_ns_timestamp_without_datetime_math_error(tmp_path):
    guard = HybridRiskGuard(
        state_file=str(tmp_path / "risk_state.json"),
        backup_file=str(tmp_path / "risk_state.backup"),
        zombie_order_timeout_sec=999999,
    )

    assert guard.update_pending_orders(
        count=0,
        total_value=1.0,
        oldest_timestamp=T0_NS,
    ) is False
    assert guard._state.oldest_pending_order_ts == datetime.fromtimestamp(T0_NS / 1_000_000_000, tz=timezone.utc)


def test_cancel_ack_terminal_order_is_removed_from_engine_pending_orders(tmp_path):
    adapter, _transport = _adapter_with_ack()
    router = OrderRouter(
        primary_exchange="alpaca",
        paper_mode=True,
        execution_broker="alpaca_paper",
        broker_gateway_adapter=adapter,
        state_store=_state_store(tmp_path),
    )
    order = _order()
    router.submit_order(order)
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
    engine._state.pending_orders[order.id] = order

    assert engine._cancel_pending_order_with_pcv(order.id) is True

    assert order.id not in engine._state.pending_orders
    accounting = engine.get_oms_shutdown_accounting()
    assert accounting["engine_pending_orders"] == 0
    assert accounting["active_pending_orders"] == 0
    assert accounting["pending_terminal_leak_count"] == 0


def test_cancel_already_attempted_logs_once_and_does_not_repeat(caplog):
    router = MagicMock()
    router.cancel_order.return_value = False
    router.is_order_terminal.return_value = False
    risk_guard = MagicMock()
    risk_guard.register_recalibrate_callback = MagicMock()
    risk_guard.register_emergency_callback = MagicMock()
    risk_guard.register_zombie_callback = MagicMock()
    risk_guard.register_lag_callback = MagicMock()
    risk_guard.register_vol_fuse_callback = MagicMock()
    engine = ExecutionEngine(
        commander=MagicMock(spec=Commander),
        risk_guard=risk_guard,
        order_router=router,
        masking_layer=MagicMock(),
        max_pending_age_sec=1.0,
    )

    with caplog.at_level(logging.INFO):
        assert engine._cancel_pending_order_with_pcv("order-1") is False
        assert engine._cancel_pending_order_with_pcv("order-1") is False
        assert engine._cancel_pending_order_with_pcv("order-1") is False

    assert caplog.text.count(OmsReasonCode.CANCEL_ALREADY_ATTEMPTED.value) == 1
    assert router.cancel_order.call_count == 1


def test_gateway_terminal_post_ack_status_never_enters_pending_orders(tmp_path):
    for status in ("filled", "canceled", "rejected", "expired"):
        adapter, _transport = _adapter_with_ack(
            {
                "id": "broker-1",
                "client_order_id": "client-1",
                "status": status,
                "symbol": "BTCUSD",
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

        assert order.id not in router._pending_orders
        assert router.get_oms_shutdown_accounting()["pending_terminal_leak_count"] == 0


def test_shutdown_final_reconciliation_explains_broker_open_order_truth(tmp_path):
    status_payload = {
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
            ("GET", "/v2/orders"): (200, [status_payload, {"id": "external-open", "symbol": "ETHUSD"}]),
            ("GET", "/v2/positions"): (200, [{"symbol": "BTCUSD", "qty": "0.01"}]),
            ("GET", "/v2/account"): (200, {"status": "ACTIVE"}),
        }
    )
    adapter = AlpacaPaperBrokerAdapter(_creds(), transport=transport, read_profile=PAPER_TCA_EXTENDED_READS)
    router = OrderRouter(
        primary_exchange="alpaca",
        paper_mode=True,
        execution_broker="alpaca_paper",
        broker_gateway_adapter=adapter,
        state_store=_state_store(tmp_path),
    )
    router.submit_order(_order())

    reconciliation = router.finalize_oms_shutdown_reconciliation()
    accounting = router.get_oms_shutdown_accounting()

    assert reconciliation["performed"] is True
    assert accounting["last_broker_open_orders_count"] == 2
    assert accounting["open_orders"] == accounting["broker_confirmed_open_orders"] == 2
    assert accounting["local_open_orders_after_final_reconcile"] == 1
    assert accounting["local_open_without_broker_match_count"] == 0
    assert accounting["broker_open_orders_unmatched_count"] == 1
    assert accounting["shutdown_reconciliation"]["account_status"] == "ACTIVE"


def test_shutdown_reconciliation_terminalizes_filled_local_open_without_broker_open_match(tmp_path):
    state_store = _state_store(tmp_path)
    filled_payload = {
        "id": "broker-filled",
        "client_order_id": "filled-client",
        "status": "filled",
        "symbol": "BTCUSD",
        "filled_qty": "0.01",
        "filled_avg_price": "75001.25",
        "fee": "0.11",
        "fee_currency": "USD",
        "filled_at": "2026-05-25T08:00:00Z",
    }
    transport = RoutingTransport(
        {
            ("GET", "/v2/orders/broker-filled"): (200, filled_payload),
            ("GET", "/v2/orders"): (200, []),
            ("GET", "/v2/positions"): (200, [{"symbol": "BTCUSD", "qty": "0.01"}]),
            ("GET", "/v2/account"): (200, {"status": "ACTIVE"}),
        }
    )
    router = OrderRouter(
        primary_exchange="alpaca",
        paper_mode=True,
        execution_broker="alpaca_paper",
        broker_gateway_adapter=AlpacaPaperBrokerAdapter(_creds(), transport=transport, read_profile=PAPER_TCA_EXTENDED_READS),
        state_store=state_store,
    )
    _persist_mapping(state_store, client_order_id="filled-client", broker_order_id="broker-filled")

    reconciliation = router.finalize_oms_shutdown_reconciliation()
    accounting = router.get_oms_shutdown_accounting()
    mapping = state_store.get_order_id_mapping("filled-client", "alpaca")

    assert mapping["is_terminal"] is True
    assert mapping["status"] == "filled"
    assert accounting["open_orders"] == accounting["broker_confirmed_open_orders"] == 0
    assert accounting["local_open_orders_after_final_reconcile"] == 0
    assert accounting["local_open_without_broker_match_count"] == 0
    assert accounting["filled_orders"] == 1
    assert accounting["local_fills"] == 1
    assert accounting["fill_hydration_count"] == 1
    assert accounting["fill_hydration_missing_count"] == 0
    assert reconciliation["final_nonterminal_resolutions"][0]["status"] == OmsOrderState.FILLED.value
    assert not any(call["method"] in {"POST", "DELETE"} for call in transport.calls)


def test_shutdown_hydrates_existing_terminal_filled_mapping_without_local_fill(tmp_path):
    state_store = _state_store(tmp_path)
    _persist_mapping(
        state_store,
        client_order_id="old-filled-client",
        broker_order_id="old-broker-filled",
        status="filled",
        is_terminal=True,
    )
    filled_payload = {
        "id": "old-broker-filled",
        "client_order_id": "old-filled-client",
        "status": "filled",
        "symbol": "BTCUSD",
        "filled_qty": "0.02",
        "filled_avg_price": "75002.50",
        "fee": "0.12",
        "fee_currency": "USD",
        "filled_at": "2026-05-25T08:10:00Z",
    }
    transport = RoutingTransport(
        {
            ("GET", "/v2/orders/old-broker-filled"): (200, filled_payload),
            ("GET", "/v2/orders"): (200, []),
            ("GET", "/v2/positions"): (200, [{"symbol": "BTCUSD", "qty": "0.02"}]),
            ("GET", "/v2/account"): (200, {"status": "ACTIVE"}),
        }
    )
    router = OrderRouter(
        primary_exchange="alpaca",
        paper_mode=True,
        execution_broker="alpaca_paper",
        broker_gateway_adapter=AlpacaPaperBrokerAdapter(_creds(), transport=transport, read_profile=PAPER_TCA_EXTENDED_READS),
        state_store=state_store,
    )

    router.finalize_oms_shutdown_reconciliation()
    accounting = router.get_oms_shutdown_accounting()

    assert accounting["filled_orders"] == 1
    assert accounting["local_fills"] == 1
    assert accounting["fill_hydration_count"] == 1
    assert accounting["fill_hydration_missing_count"] == 0
    assert not any(call["method"] in {"POST", "DELETE"} for call in transport.calls)


def test_shutdown_reconciliation_terminalizes_canceled_local_open_without_broker_open_match(tmp_path):
    state_store = _state_store(tmp_path)
    transport = RoutingTransport(
        {
            ("GET", "/v2/orders/broker-canceled"): (
                200,
                {
                    "id": "broker-canceled",
                    "client_order_id": "canceled-client",
                    "status": "canceled",
                    "symbol": "BTCUSD",
                },
            ),
            ("GET", "/v2/orders"): (200, []),
            ("GET", "/v2/positions"): (200, []),
            ("GET", "/v2/account"): (200, {"status": "ACTIVE"}),
        }
    )
    router = OrderRouter(
        primary_exchange="alpaca",
        paper_mode=True,
        execution_broker="alpaca_paper",
        broker_gateway_adapter=AlpacaPaperBrokerAdapter(_creds(), transport=transport, read_profile=PAPER_TCA_EXTENDED_READS),
        state_store=state_store,
    )
    _persist_mapping(state_store, client_order_id="canceled-client", broker_order_id="broker-canceled")

    router.finalize_oms_shutdown_reconciliation()
    accounting = router.get_oms_shutdown_accounting()
    mapping = state_store.get_order_id_mapping("canceled-client", "alpaca")

    assert mapping["is_terminal"] is True
    assert mapping["status"] == "canceled"
    assert accounting["open_orders"] == 0
    assert accounting["canceled_orders"] == 1
    assert accounting["local_open_without_broker_match_count"] == 0
    assert not any(call["method"] in {"POST", "DELETE"} for call in transport.calls)


def test_shutdown_reconciliation_conflicts_unexplained_local_open(tmp_path):
    state_store = _state_store(tmp_path)
    transport = RoutingTransport(
        {
            ("GET", "/v2/orders/broker-unknown"): (
                200,
                {
                    "id": "broker-unknown",
                    "client_order_id": "unknown-client",
                    "status": "accepted",
                    "symbol": "BTCUSD",
                },
            ),
            ("GET", "/v2/orders"): (200, []),
            ("GET", "/v2/positions"): (200, []),
            ("GET", "/v2/account"): (200, {"status": "ACTIVE"}),
        }
    )
    router = OrderRouter(
        primary_exchange="alpaca",
        paper_mode=True,
        execution_broker="alpaca_paper",
        broker_gateway_adapter=AlpacaPaperBrokerAdapter(_creds(), transport=transport, read_profile=PAPER_TCA_EXTENDED_READS),
        state_store=state_store,
    )
    _persist_mapping(state_store, client_order_id="unknown-client", broker_order_id="broker-unknown")

    reconciliation = router.finalize_oms_shutdown_reconciliation()
    accounting = router.get_oms_shutdown_accounting()
    mapping = state_store.get_order_id_mapping("unknown-client", "alpaca")

    assert mapping["is_terminal"] is True
    assert mapping["status"] == "reconciliation_conflict"
    assert accounting["open_orders"] == accounting["broker_confirmed_open_orders"] == 0
    assert accounting["local_open_orders_after_final_reconcile"] == 0
    assert accounting["local_open_without_broker_match_count"] == 0
    assert accounting["final_state_unknown_count"] == 1
    assert accounting["reconciliation_conflicts"] >= 1
    assert reconciliation["final_nonterminal_resolutions"][0]["reason_codes"] == (
        OmsReasonCode.BROKER_FINAL_STATE_UNKNOWN.value,
    )
    assert not any(call["method"] in {"POST", "DELETE"} for call in transport.calls)


def test_missing_broker_fill_details_reports_unavailable_without_fake_fill(tmp_path):
    state_store = _state_store(tmp_path)
    _persist_mapping(
        state_store,
        client_order_id="filled-client",
        broker_order_id="broker-filled",
        status="filled",
        is_terminal=True,
    )
    transport = RoutingTransport(
        {
            ("GET", "/v2/orders/broker-filled"): (
                200,
                {
                    "id": "broker-filled",
                    "client_order_id": "filled-client",
                    "status": "filled",
                    "symbol": "BTCUSD",
                },
            ),
            ("GET", "/v2/orders"): (200, []),
            ("GET", "/v2/positions"): (200, [{"symbol": "BTCUSD", "qty": "0.01"}]),
            ("GET", "/v2/account"): (200, {"status": "ACTIVE"}),
        }
    )
    router = OrderRouter(
        primary_exchange="alpaca",
        paper_mode=True,
        execution_broker="alpaca_paper",
        broker_gateway_adapter=AlpacaPaperBrokerAdapter(_creds(), transport=transport, read_profile=PAPER_TCA_EXTENDED_READS),
        state_store=state_store,
    )

    router.finalize_oms_shutdown_reconciliation()
    accounting = router.get_oms_shutdown_accounting()

    assert accounting["filled_orders"] == 1
    assert accounting["local_fills"] == 0
    assert accounting["fill_hydration_count"] == 0
    assert accounting["fill_hydration_missing_count"] == 1


def test_order_status_fill_without_fee_hydrates_partial_broker_ledger_without_fake_fee(tmp_path):
    state_store = _state_store(tmp_path)
    _persist_mapping(
        state_store,
        client_order_id="partial-fee-client",
        broker_order_id="broker-partial-fee",
        status="filled",
        is_terminal=True,
    )
    transport = RoutingTransport(
        {
            ("GET", "/v2/orders/broker-partial-fee"): (
                200,
                {
                    "id": "broker-partial-fee",
                    "client_order_id": "partial-fee-client",
                    "status": "filled",
                    "symbol": "BTCUSD",
                    "filled_qty": "0.01",
                    "filled_avg_price": "75010.00",
                    "filled_at": "2026-05-25T08:20:00Z",
                },
            ),
            ("GET", "/v2/account/activities"): (200, []),
            ("GET", "/v2/orders"): (200, []),
            ("GET", "/v2/positions"): (200, [{"symbol": "BTCUSD", "qty": "0.01"}]),
            ("GET", "/v2/account"): (200, {"status": "ACTIVE"}),
        }
    )
    router = OrderRouter(
        primary_exchange="alpaca",
        paper_mode=True,
        execution_broker="alpaca_paper",
        broker_gateway_adapter=AlpacaPaperBrokerAdapter(_creds(), transport=transport, read_profile=PAPER_TCA_EXTENDED_READS),
        state_store=state_store,
    )

    router.finalize_oms_shutdown_reconciliation()
    accounting = router.get_oms_shutdown_accounting()

    assert accounting["filled_orders"] == 1
    assert accounting["local_fills"] == 1
    assert accounting["legacy_local_fills"] == 0
    assert accounting["fill_hydration_count"] == 1
    assert accounting["fill_hydration_partial_count"] == 1
    assert accounting["fill_hydration_missing_count"] == 0
    assert accounting["tca_records_count"] == 1
    assert accounting["tca_unknown_count"] == 1
    assert not any(call["method"] in {"POST", "DELETE"} for call in transport.calls)


def test_account_activity_hydrates_fee_and_realized_netedge_tca(tmp_path):
    state_store = _state_store(tmp_path)
    filled_payload = {
        "id": "broker-1",
        "client_order_id": "client-1",
        "status": "filled",
        "symbol": "BTCUSD",
        "filled_qty": "0.01",
        "filled_avg_price": "75005.00",
        "filled_at": "2026-05-25T08:30:00Z",
    }
    activity_payload = {
        "id": "activity-1",
        "order_id": "broker-1",
        "client_order_id": "client-1",
        "symbol": "BTCUSD",
        "side": "buy",
        "qty": "0.01",
        "price": "75005.00",
        "commission": "0.15",
        "commission_currency": "USD",
        "transaction_time": "2026-05-25T08:30:01Z",
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
            ("GET", "/v2/orders/broker-1"): (200, filled_payload),
            ("GET", "/v2/account/activities"): (200, [activity_payload]),
            ("GET", "/v2/orders"): (200, []),
            ("GET", "/v2/positions"): (200, [{"symbol": "BTCUSD", "qty": "0.01"}]),
            ("GET", "/v2/account"): (200, {"status": "ACTIVE"}),
        }
    )
    router = OrderRouter(
        primary_exchange="alpaca",
        paper_mode=True,
        execution_broker="alpaca_paper",
        broker_gateway_adapter=AlpacaPaperBrokerAdapter(_creds(), transport=transport, read_profile=PAPER_TCA_EXTENDED_READS),
        state_store=state_store,
    )
    order = _order().model_copy(
        update={
            "metadata": {
                **_order().metadata,
                "net_edge_evaluation": {"net_adversarial_edge": "0.01"},
                "net_edge_context": {"expected_move": "0.02"},
            }
        }
    )

    router.submit_order(order)
    accounting = router.get_oms_shutdown_accounting()

    assert accounting["filled_orders"] == 1
    assert accounting["local_fills"] == 1
    assert accounting["legacy_local_fills"] == 1
    assert accounting["fill_hydration_count"] == 1
    assert accounting["fill_hydration_partial_count"] == 0
    assert accounting["fill_hydration_missing_count"] == 0
    assert accounting["tca_records_count"] == 1
    assert accounting["tca_unknown_count"] == 0
    assert accounting["realized_vs_modeled_netedge_available_count"] == 1
    assert any(call["method"] == "GET" and call["path"] == "/v2/account/activities" for call in transport.calls)


def test_repeated_fill_hydration_is_idempotent(tmp_path):
    state_store = _state_store(tmp_path)
    _persist_mapping(
        state_store,
        client_order_id="idempotent-client",
        broker_order_id="broker-idempotent",
        status="filled",
        is_terminal=True,
    )
    filled_payload = {
        "id": "broker-idempotent",
        "client_order_id": "idempotent-client",
        "status": "filled",
        "symbol": "BTCUSD",
        "filled_qty": "0.01",
        "filled_avg_price": "75001.00",
        "fee": "0.10",
        "fee_currency": "USD",
        "filled_at": "2026-05-25T08:40:00Z",
    }
    transport = RoutingTransport(
        {
            ("GET", "/v2/orders/broker-idempotent"): (200, filled_payload),
            ("GET", "/v2/account/activities"): (200, []),
            ("GET", "/v2/orders"): (200, []),
            ("GET", "/v2/positions"): (200, [{"symbol": "BTCUSD", "qty": "0.01"}]),
            ("GET", "/v2/account"): (200, {"status": "ACTIVE"}),
        }
    )
    router = OrderRouter(
        primary_exchange="alpaca",
        paper_mode=True,
        execution_broker="alpaca_paper",
        broker_gateway_adapter=AlpacaPaperBrokerAdapter(_creds(), transport=transport, read_profile=PAPER_TCA_EXTENDED_READS),
        state_store=state_store,
    )

    router.finalize_oms_shutdown_reconciliation()
    router.finalize_oms_shutdown_reconciliation()
    accounting = router.get_oms_shutdown_accounting()

    assert accounting["local_fills"] == 1
    assert accounting["legacy_local_fills"] == 1
    assert accounting["fill_hydration_count"] == 1


def test_canceled_order_with_filled_qty_records_partial_fill_then_cancel(tmp_path):
    state_store = _state_store(tmp_path)
    _persist_mapping(state_store, client_order_id="partial-cancel-client", broker_order_id="broker-partial-cancel")
    transport = RoutingTransport(
        {
            ("GET", "/v2/orders/broker-partial-cancel"): (
                200,
                {
                    "id": "broker-partial-cancel",
                    "client_order_id": "partial-cancel-client",
                    "status": "canceled",
                    "symbol": "BTCUSD",
                    "filled_qty": "0.005",
                    "filled_avg_price": "74990.00",
                    "updated_at": "2026-05-25T08:50:00Z",
                },
            ),
            ("GET", "/v2/account/activities"): (200, []),
            ("GET", "/v2/orders"): (200, []),
            ("GET", "/v2/positions"): (200, [{"symbol": "BTCUSD", "qty": "0.005"}]),
            ("GET", "/v2/account"): (200, {"status": "ACTIVE"}),
        }
    )
    router = OrderRouter(
        primary_exchange="alpaca",
        paper_mode=True,
        execution_broker="alpaca_paper",
        broker_gateway_adapter=AlpacaPaperBrokerAdapter(_creds(), transport=transport, read_profile=PAPER_TCA_EXTENDED_READS),
        state_store=state_store,
    )

    router.finalize_oms_shutdown_reconciliation()
    accounting = router.get_oms_shutdown_accounting()
    mapping = state_store.get_order_id_mapping("partial-cancel-client", "alpaca")

    assert mapping["is_terminal"] is True
    assert mapping["status"] == "canceled"
    assert accounting["local_fills"] == 1
    assert accounting["broker_canceled_with_fill_count"] == 1
    assert accounting["fill_hydration_partial_count"] == 1
    assert accounting["fill_hydration_missing_count"] == 0
    assert not any(call["method"] in {"POST", "DELETE"} for call in transport.calls)


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
    adapter = AlpacaPaperBrokerAdapter(_creds(), transport=transport, read_profile=PAPER_TCA_EXTENDED_READS)

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
