import inspect
import json
from decimal import Decimal

from app.execution.order_router import OrderRouter
from app.execution.paper_broker import PaperMarketContext, PriceLevel
from app.models import OrderRequest
from app.models.enums import OrderSide, OrderType, SleeveType
from app.risk.exposure_manager import ExposureManager
from app.risk.reservation_lifecycle_coordinator import ReservationLifecycleCoordinator
from app.state.state_store import StateStore
from app.utils.time_utils import now_ns


class _MockResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self) -> dict:
        return self._payload


class _SpyCoordinator:
    def __init__(self):
        self.ack_calls = []
        self.partial_calls = []
        self.full_calls = []
        self.terminal_calls = []
        self.release_calls = []

    def on_order_acknowledged(self, **kwargs):
        self.ack_calls.append(kwargs)
        return {
            "action": "order_acknowledged",
            "applied": True,
            "idempotent": False,
            "skipped": False,
            "failed_reason": None,
            "reservation_id": kwargs.get("reservation_id"),
            "client_order_id": kwargs.get("client_order_id"),
            "mutation_attempted": True,
            "broker_command_performed": False,
            "telemetry_authority_used": False,
            "exposure_manager_called": True,
        }

    def on_partial_fill(self, **kwargs):
        self.partial_calls.append(kwargs)

    def on_full_fill(self, **kwargs):
        self.full_calls.append(kwargs)

    def on_terminal_mapping_proof(self, **kwargs):
        self.terminal_calls.append(kwargs)

    def on_cancel_requested(self, **kwargs):
        self.release_calls.append(("cancel_requested", kwargs))

    def on_cancel_rejected(self, **kwargs):
        self.release_calls.append(("cancel_rejected", kwargs))

    def on_orphan_or_drift(self, **kwargs):
        self.release_calls.append(("orphan_or_drift", kwargs))

    def on_status_failure(self, **kwargs):
        self.release_calls.append(("status_failure", kwargs))

    def on_open_order_absence(self, **kwargs):
        self.release_calls.append(("open_order_absence", kwargs))


def _order(
    *,
    order_id: str = "router-reservation-client-001",
    decision_uuid: str = "router-reservation-decision-001",
    order_type=OrderType.LIMIT,
    limit_price=Decimal("2900.00"),
    quantity=Decimal("1.0"),
):
    ts_ns = now_ns()
    return OrderRequest(
        id=order_id,
        symbol="ETH/USD",
        side=OrderSide.BUY,
        order_type=order_type,
        quantity=quantity,
        limit_price=limit_price,
        strategy=SleeveType.SECTOR_ROTATION,
        confidence=0.9,
        decision_uuid=decision_uuid,
        exchange_ts_ns=ts_ns,
        receive_ts_ns=ts_ns,
    )


def _enabled_router(coordinator, **kwargs):
    return OrderRouter(
        reservation_lifecycle_coordinator=coordinator,
        reservation_lifecycle_enabled=True,
        **kwargs,
    )


def _assert_ack_call(call, order):
    assert call["client_order_id"] == order.id
    assert call["reservation_id"] == order.id
    assert call["decision_uuid"] == order.decision_uuid
    assert call["reservation_dedupe_key"] == f"{order.decision_uuid}:{order.id}"
    assert call["symbol"] == order.symbol
    assert call["side"] == order.side
    assert call["sleeve"] == order.strategy
    assert call["qty"] == order.quantity
    assert call["price_basis"] == order.limit_price
    assert call["order_type"] == "limit"
    assert call["source_lifecycle_phase"] == "order_acknowledged"
    assert call["price_basis_source_proven"] is True
    assert call["mutation_authority_source"] == "direct_lifecycle"


def test_default_order_router_reservation_lifecycle_disabled():
    router = OrderRouter(paper_mode=True)

    assert router._reservation_lifecycle_enabled is False
    assert router._reservation_lifecycle_coordinator is None


def test_default_disabled_order_router_makes_zero_coordinator_calls_on_paper_ack():
    coordinator = _SpyCoordinator()
    router = OrderRouter(
        paper_mode=True,
        reservation_lifecycle_coordinator=coordinator,
    )
    order = _order()

    assert router.submit_order(order) is None

    assert coordinator.ack_calls == []
    assert router._reservation_lifecycle_ack_open_results[-1]["failed_reason"] == "reservation_lifecycle_disabled"


def test_enabled_paper_limit_ack_calls_coordinator_once():
    coordinator = _SpyCoordinator()
    router = _enabled_router(coordinator, paper_mode=True)
    order = _order()

    assert router.submit_order(order) is None

    assert len(coordinator.ack_calls) == 1
    _assert_ack_call(coordinator.ack_calls[0], order)


def test_enabled_mocked_kraken_limit_ack_calls_coordinator_once():
    coordinator = _SpyCoordinator()
    router = _enabled_router(
        coordinator,
        primary_exchange="kraken",
        paper_mode=False,
        rest_fallback_enabled=False,
    )
    router._websocket_connected = True

    def post(url, data=None, headers=None, timeout=None):
        return _MockResponse(200, {"error": [], "result": {"txid": ["KRAKEN-TXID-23L"]}})

    router._session.post = post
    order = _order(order_id="kraken-router-reservation-client-001", decision_uuid="kraken-router-reservation-decision-001")

    assert router.submit_order(order) is None

    assert len(coordinator.ack_calls) == 1
    _assert_ack_call(coordinator.ack_calls[0], order)


def test_enabled_mocked_alpaca_limit_ack_calls_coordinator_once():
    coordinator = _SpyCoordinator()
    router = _enabled_router(
        coordinator,
        primary_exchange="alpaca",
        paper_mode=False,
        rest_fallback_enabled=False,
    )
    router._websocket_connected = True

    def post(url, json=None, timeout=None):
        return _MockResponse(200, {"id": "ALPACA-ID-23L"})

    router._session.post = post
    order = _order(order_id="alpaca-router-reservation-client-001", decision_uuid="alpaca-router-reservation-decision-001")

    assert router.submit_order(order) is None

    assert len(coordinator.ack_calls) == 1
    _assert_ack_call(coordinator.ack_calls[0], order)


def test_duplicate_ack_dedupe_is_idempotent_without_double_reserve(tmp_path):
    store = StateStore(str(tmp_path / "reservation.db"))
    manager = ExposureManager(initial_equity=Decimal("20000"))
    coordinator = ReservationLifecycleCoordinator(exposure_manager=manager, state_store=store)
    router = _enabled_router(coordinator, paper_mode=True, state_store=store)
    order = _order()

    first = router._record_reservation_ack_open(
        order,
        ack_source="test.ack",
        source_event_id="same-proof",
    )
    second = router._record_reservation_ack_open(
        order,
        ack_source="test.ack",
        source_event_id="same-proof",
    )

    assert first["applied"] is True
    assert second["idempotent"] is True
    assert len(manager.reservations_for()) == 1
    assert len(store.list_reservation_ledger(active_only=True)) == 1


def test_pre_submit_order_submitted_telemetry_does_not_call_coordinator():
    coordinator = _SpyCoordinator()
    router = _enabled_router(coordinator, paper_mode=True)
    order = _order()

    router._record_order_submission_telemetry(order)

    assert coordinator.ack_calls == []
    assert router._reservation_lifecycle_ack_open_results == []


def test_reject_before_ack_does_not_call_coordinator():
    coordinator = _SpyCoordinator()
    router = _enabled_router(
        coordinator,
        primary_exchange="kraken",
        paper_mode=False,
        rest_fallback_enabled=False,
    )
    router._websocket_connected = True

    def post(url, data=None, headers=None, timeout=None):
        return _MockResponse(200, {"error": ["EOrder:Rejected"], "result": {}})

    router._session.post = post

    assert router.submit_order(_order()) is None
    assert coordinator.ack_calls == []
    assert router._reservation_lifecycle_ack_open_results == []


def test_market_order_missing_price_basis_fails_closed_without_coordinator_call():
    coordinator = _SpyCoordinator()
    router = _enabled_router(coordinator, paper_mode=True)
    order = _order(order_type=OrderType.MARKET, limit_price=None)

    router.submit_order(order)

    assert coordinator.ack_calls == []
    assert router._reservation_lifecycle_ack_open_results[-1]["failed_reason"] == "unsupported_order_type_for_reservation_open"


def test_partial_and_full_fill_paths_do_not_call_coordinator_in_23l():
    coordinator = _SpyCoordinator()
    router = _enabled_router(coordinator, paper_mode=True)
    order = _order(quantity=Decimal("1.0"), limit_price=Decimal("2900.00"))

    assert router.submit_order(order) is None
    paper_order = router._paper_broker.open_orders[order.id]
    assert len(coordinator.ack_calls) == 1

    first_ctx = PaperMarketContext(
        symbol=order.symbol,
        timestamp_ns=paper_order.eligible_at_ns + 2,
        mid_price=Decimal("2899.00"),
        best_bid=Decimal("2898.50"),
        best_ask=Decimal("2899.00"),
        ask_levels=(PriceLevel(price=Decimal("2899.00"), quantity=Decimal("0.25")),),
    )
    router._paper_broker.process_matching_detailed(
        current_ts_ns=paper_order.eligible_at_ns + 2,
        market_by_symbol={order.symbol: first_ctx},
    )
    router._sync_paper_reports()

    second_ctx = PaperMarketContext(
        symbol=order.symbol,
        timestamp_ns=paper_order.eligible_at_ns + 4,
        mid_price=Decimal("2898.00"),
        best_bid=Decimal("2897.50"),
        best_ask=Decimal("2898.00"),
        ask_levels=(PriceLevel(price=Decimal("2898.00"), quantity=Decimal("0.75")),),
    )
    router._paper_broker.process_matching_detailed(
        current_ts_ns=paper_order.eligible_at_ns + 4,
        market_by_symbol={order.symbol: second_ctx},
    )
    router._sync_paper_reports()

    assert coordinator.partial_calls == []
    assert coordinator.full_calls == []
    assert len(coordinator.ack_calls) == 1


def test_terminal_mapping_proof_and_cancel_paths_do_not_call_release(tmp_path):
    coordinator = _SpyCoordinator()
    state_store = StateStore(str(tmp_path / "terminal.db"))
    router = _enabled_router(
        coordinator,
        primary_exchange="kraken",
        paper_mode=False,
        state_store=state_store,
        rest_fallback_enabled=False,
    )
    router._websocket_connected = True

    def post(url, data=None, headers=None, timeout=None):
        return _MockResponse(200, {"error": [], "result": {"txid": ["KRAKEN-TXID-TERM-23L"]}})

    router._session.post = post
    order = _order(order_id="terminal-router-reservation-client-001", decision_uuid="terminal-router-reservation-decision-001")

    assert router.submit_order(order) is None
    assert router.mark_terminal_from_status_evidence(
        {
            "client_order_id": order.id,
            "broker": "kraken",
            "venue": "kraken",
            "command_id_namespace": "exchange_txid",
            "command_order_id": "KRAKEN-TXID-TERM-23L",
            "status_classification": "terminal_observed",
            "terminal_observed": True,
            "status_raw": "filled",
        }
    )["applied"] is True

    paper_coordinator = _SpyCoordinator()
    paper_router = _enabled_router(paper_coordinator, paper_mode=True)
    paper_order = _order(order_id="cancel-router-reservation-client-001", decision_uuid="cancel-router-reservation-decision-001")
    assert paper_router.submit_order(paper_order) is None
    assert paper_router.cancel_order(paper_order.id) is True

    assert coordinator.terminal_calls == []
    assert coordinator.release_calls == []
    assert paper_coordinator.release_calls == []


def test_no_telemetry_authority_or_broker_adapter_use_in_order_router_wiring():
    source = inspect.getsource(OrderRouter)

    assert "mutation_authority_source=\"direct_lifecycle\"" in source
    assert "mutation_authority_source=\"telemetry\"" not in source
    assert "broker_adapter" not in source
