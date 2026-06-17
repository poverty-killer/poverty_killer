import inspect
import json
from decimal import Decimal

from app.execution.order_router import OrderRouter
from app.execution.paper_broker import PaperMarketContext, PriceLevel
from app.models import OrderRequest
from app.models.enums import OrderSide, OrderStatus, OrderType, SleeveType
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
        self.terminal_non_fill_calls = []
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
        return {
            "action": "partial_fill",
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

    def on_full_fill(self, **kwargs):
        self.full_calls.append(kwargs)
        return {
            "action": "full_fill",
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

    def on_terminal_mapping_proof(self, **kwargs):
        self.terminal_calls.append(kwargs)

    def on_terminal_non_fill(self, **kwargs):
        self.terminal_non_fill_calls.append(kwargs)
        return {
            "action": "terminal_non_fill",
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


def _drive_paper_partial(router, order, *, quantity=Decimal("0.25"), offset=2):
    paper_order = router._paper_broker.open_orders[order.id]
    ctx = PaperMarketContext(
        symbol=order.symbol,
        timestamp_ns=paper_order.eligible_at_ns + offset,
        mid_price=Decimal("2899.00"),
        best_bid=Decimal("2898.50"),
        best_ask=Decimal("2899.00"),
        ask_levels=(PriceLevel(price=Decimal("2899.00"), quantity=quantity),),
    )
    router._paper_broker.process_matching_detailed(
        current_ts_ns=paper_order.eligible_at_ns + offset,
        market_by_symbol={order.symbol: ctx},
    )
    router._sync_paper_reports()
    return router._paper_broker.execution_reports[-1]


class _PaperReport:
    def __init__(
        self,
        *,
        client_id: str,
        order_id: str,
        status,
        timestamp_ns: int,
        filled_quantity=Decimal("0"),
        fill_price=None,
        fee=Decimal("0"),
    ):
        self.client_id = client_id
        self.order_id = order_id
        self.status = status
        self.timestamp_ns = timestamp_ns
        self.filled_quantity = filled_quantity
        self.fill_price = fill_price
        self.fee = fee


def _paper_terminal_report(order, status, *, source_event_id="paper_report_terminal", offset=10):
    return _PaperReport(
        client_id=order.id,
        order_id=f"paper-{order.id}",
        status=status,
        timestamp_ns=order.exchange_ts_ns + offset,
    ), source_event_id


def test_default_order_router_reservation_lifecycle_disabled():
    router = OrderRouter(paper_mode=True)

    assert router._reservation_lifecycle_enabled is False
    assert router._reservation_lifecycle_coordinator is None


def test_order_router_blocks_required_portfolio_risk_gate_without_evidence_before_paper_broker():
    router = OrderRouter(paper_mode=True)
    order = _order()
    order.metadata.update(
        {
            "portfolio_risk_gate_required": True,
            "portfolio_risk_gate_policy_version": "P3B_B1_V1",
        }
    )

    assert router.submit_order(order) is None
    assert router._paper_broker is not None
    assert router._paper_broker.open_orders == {}
    assert router._paper_broker.execution_reports == []
    source = inspect.getsource(OrderRouter.submit_order)
    assert "evaluate_pre_trade_portfolio_gate" not in source


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


def test_enabled_mocked_kraken_limit_ack_is_hard_blocked_from_coordinator():
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

    assert coordinator.ack_calls == []
    assert router._reservation_lifecycle_ack_open_results[-1]["failed_reason"] == (
        "reservation_lifecycle_non_paper_blocked"
    )


def test_enabled_mocked_alpaca_limit_ack_is_hard_blocked_from_coordinator():
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

    assert coordinator.ack_calls == []
    assert router._reservation_lifecycle_ack_open_results[-1]["failed_reason"] == (
        "reservation_lifecycle_non_paper_blocked"
    )


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
    assert coordinator.terminal_non_fill_calls == []
    assert router._reservation_lifecycle_ack_open_results == []


def test_market_order_missing_price_basis_fails_closed_without_coordinator_call():
    coordinator = _SpyCoordinator()
    router = _enabled_router(coordinator, paper_mode=True)
    order = _order(order_type=OrderType.MARKET, limit_price=None)

    router.submit_order(order)

    assert coordinator.ack_calls == []
    assert router._reservation_lifecycle_ack_open_results[-1]["failed_reason"] == "unsupported_order_type_for_reservation_open"


def test_default_disabled_paper_partial_fill_makes_zero_coordinator_calls_and_zero_progress(tmp_path):
    coordinator = _SpyCoordinator()
    store = StateStore(str(tmp_path / "disabled-partial.db"))
    router = OrderRouter(
        paper_mode=True,
        state_store=store,
        reservation_lifecycle_coordinator=coordinator,
    )
    order = _order(quantity=Decimal("1.0"), limit_price=Decimal("2900.00"))

    assert router.submit_order(order) is None
    _drive_paper_partial(router, order)

    assert coordinator.ack_calls == []
    assert coordinator.partial_calls == []
    assert store.list_reservation_fill_progress(order.id) == []
    assert router._reservation_lifecycle_partial_fill_results[-1]["failed_reason"] == "reservation_lifecycle_disabled"


def test_enabled_paper_partial_fill_calls_coordinator_once_after_ack_open():
    coordinator = _SpyCoordinator()
    router = _enabled_router(coordinator, paper_mode=True)
    order = _order(quantity=Decimal("1.0"), limit_price=Decimal("2900.00"))

    assert router.submit_order(order) is None
    assert len(coordinator.ack_calls) == 1

    report = _drive_paper_partial(router, order)
    call = coordinator.partial_calls[0]
    expected_key = router._paper_lifecycle_idempotency_key(
        order,
        lifecycle_phase="order_partially_filled",
        broker_order_id=str(report.order_id),
        event_ts_ns=int(report.timestamp_ns),
        source_event_id="paper_report_1",
    )

    assert len(coordinator.partial_calls) == 1
    assert call["client_order_id"] == order.id
    assert call["reservation_id"] == order.id
    assert call["reservation_dedupe_key"] == f"{order.decision_uuid}:{order.id}"
    assert call["fill_idempotency_key"] == expected_key
    assert call["cumulative_filled_qty"] == Decimal("0.25")
    assert call["fill_delta_qty"] == Decimal("0.25")
    assert call["status_source"] == "paper_broker.execution_report"
    assert call["source_event_id"] == "paper_report_1"
    assert call["mutation_authority_source"] == "direct_lifecycle"


def test_enabled_paper_partial_fill_duplicate_and_advancing_progress(tmp_path):
    store = StateStore(str(tmp_path / "partial-progress.db"))
    manager = ExposureManager(initial_equity=Decimal("20000"))
    coordinator = ReservationLifecycleCoordinator(exposure_manager=manager, state_store=store)
    router = _enabled_router(coordinator, paper_mode=True, state_store=store)
    order = _order(quantity=Decimal("1.0"), limit_price=Decimal("2900.00"))

    assert router.submit_order(order) is None
    first_report = _drive_paper_partial(router, order, quantity=Decimal("0.25"), offset=2)
    first_key = router._paper_lifecycle_idempotency_key(
        order,
        lifecycle_phase="order_partially_filled",
        broker_order_id=str(first_report.order_id),
        event_ts_ns=int(first_report.timestamp_ns),
        source_event_id="paper_report_1",
    )

    first_result = router._reservation_lifecycle_partial_fill_results[-1]
    assert first_result["applied"] is True
    assert store.get_reservation_ledger(order.id)["filled_qty"] == "0.25"
    assert len(store.list_reservation_fill_progress(order.id)) == 1

    duplicate = router._record_reservation_partial_fill(
        order,
        fill_idempotency_key=first_key,
        cumulative_filled_qty=Decimal("0.25"),
        fill_delta_qty=Decimal("0.25"),
        status_source="paper_broker.execution_report",
        source_event_id="paper_report_1",
    )
    assert duplicate["idempotent"] is True
    assert len(store.list_reservation_fill_progress(order.id)) == 1

    second_report = _drive_paper_partial(router, order, quantity=Decimal("0.25"), offset=4)
    assert second_report.filled_quantity == Decimal("0.25")
    second_result = router._reservation_lifecycle_partial_fill_results[-1]
    assert second_result["applied"] is True
    assert store.get_reservation_ledger(order.id)["filled_qty"] == "0.50"
    assert len(store.list_reservation_fill_progress(order.id)) == 2

    non_advancing = router._record_reservation_partial_fill(
        order,
        fill_idempotency_key=f"{first_key}:non_advancing",
        cumulative_filled_qty=Decimal("0.50"),
        fill_delta_qty=Decimal("0.25"),
        status_source="paper_broker.execution_report",
        source_event_id="paper_report_non_advancing",
    )
    assert non_advancing["applied"] is False
    assert non_advancing["failed_reason"] == "non_advancing_cumulative_fill"
    assert len(store.list_reservation_fill_progress(order.id)) == 2


def test_partial_fill_without_active_reservation_fails_closed(tmp_path):
    store = StateStore(str(tmp_path / "missing-active.db"))
    manager = ExposureManager(initial_equity=Decimal("20000"))
    coordinator = ReservationLifecycleCoordinator(exposure_manager=manager, state_store=store)
    router = _enabled_router(coordinator, paper_mode=True, state_store=store)
    order = _order(quantity=Decimal("1.0"), limit_price=Decimal("2900.00"))

    result = router._record_reservation_partial_fill(
        order,
        fill_idempotency_key="missing-active-partial-key",
        cumulative_filled_qty=Decimal("0.25"),
        fill_delta_qty=Decimal("0.25"),
        status_source="paper_broker.execution_report",
        source_event_id="paper_report_missing_active",
    )

    assert result["applied"] is False
    assert result["failed_reason"] == "active_reservation_not_found"
    assert store.list_reservation_ledger(active_only=True) == []
    assert store.list_reservation_fill_progress(order.id) == []
    assert manager.reservations_for() == []


def test_default_disabled_paper_full_fill_makes_zero_coordinator_calls_and_zero_release(tmp_path):
    coordinator = _SpyCoordinator()
    store = StateStore(str(tmp_path / "disabled-full.db"))
    router = OrderRouter(
        paper_mode=True,
        state_store=store,
        reservation_lifecycle_coordinator=coordinator,
    )
    order = _order(quantity=Decimal("1.0"), limit_price=Decimal("2900.00"))

    assert router.submit_order(order) is None
    _drive_paper_partial(router, order, quantity=Decimal("1.0"), offset=2)

    assert coordinator.ack_calls == []
    assert coordinator.full_calls == []
    assert store.get_reservation_release_tombstone(reservation_id=order.id) is None
    assert router._reservation_lifecycle_full_fill_results[-1]["failed_reason"] == "reservation_lifecycle_disabled"


def test_enabled_paper_full_fill_calls_coordinator_once_after_ack_open():
    coordinator = _SpyCoordinator()
    router = _enabled_router(coordinator, paper_mode=True)
    order = _order(quantity=Decimal("1.0"), limit_price=Decimal("2900.00"))

    assert router.submit_order(order) is None
    assert len(coordinator.ack_calls) == 1
    report = _drive_paper_partial(router, order, quantity=Decimal("1.0"), offset=2)
    call = coordinator.full_calls[0]
    expected_key = router._paper_lifecycle_idempotency_key(
        order,
        lifecycle_phase="order_fully_filled",
        broker_order_id=str(report.order_id),
        event_ts_ns=int(report.timestamp_ns),
        source_event_id="paper_report_1",
    )

    assert len(coordinator.full_calls) == 1
    assert call["client_order_id"] == order.id
    assert call["reservation_id"] == order.id
    assert call["reservation_dedupe_key"] == f"{order.decision_uuid}:{order.id}"
    assert call["release_idempotency_key"] == f"{expected_key}:release"
    assert call["cumulative_filled_qty"] == order.quantity
    assert call["fill_delta_qty"] == Decimal("1.0")
    assert call["status_source"] == "paper_broker.execution_report"
    assert call["terminal_source"] == "paper_broker.execution_report"
    assert call["source_event_id"] == "paper_report_1"
    assert call["mutation_authority_source"] == "direct_lifecycle"
    assert coordinator.terminal_calls == []
    assert coordinator.release_calls == []


def test_enabled_paper_full_fill_duplicate_release_is_idempotent(tmp_path):
    store = StateStore(str(tmp_path / "full-release.db"))
    manager = ExposureManager(initial_equity=Decimal("20000"))
    coordinator = ReservationLifecycleCoordinator(exposure_manager=manager, state_store=store)
    router = _enabled_router(coordinator, paper_mode=True, state_store=store)
    order = _order(quantity=Decimal("1.0"), limit_price=Decimal("2900.00"))

    assert router.submit_order(order) is None
    report = _drive_paper_partial(router, order, quantity=Decimal("1.0"), offset=2)
    release_key = router._paper_lifecycle_idempotency_key(
        order,
        lifecycle_phase="order_fully_filled",
        broker_order_id=str(report.order_id),
        event_ts_ns=int(report.timestamp_ns),
        source_event_id="paper_report_1",
    ) + ":release"
    first_result = router._reservation_lifecycle_full_fill_results[-1]

    assert first_result["applied"] is True
    assert manager.reservations_for() == []
    tombstone = store.get_reservation_release_tombstone(reservation_id=order.id)
    assert tombstone["release_idempotency_key"] == release_key

    duplicate = router._record_reservation_full_fill(
        order,
        release_idempotency_key=release_key,
        cumulative_filled_qty=order.quantity,
        fill_delta_qty=Decimal("1.0"),
        status_source="paper_broker.execution_report",
        terminal_source="paper_broker.execution_report",
        source_event_id="paper_report_1",
    )
    assert duplicate["idempotent"] is True
    assert store.get_reservation_release_tombstone(reservation_id=order.id)["release_idempotency_key"] == release_key


def test_enabled_paper_full_fill_after_prior_partials_releases_remaining_once(tmp_path):
    store = StateStore(str(tmp_path / "partial-then-full.db"))
    manager = ExposureManager(initial_equity=Decimal("20000"))
    coordinator = ReservationLifecycleCoordinator(exposure_manager=manager, state_store=store)
    router = _enabled_router(coordinator, paper_mode=True, state_store=store)
    order = _order(quantity=Decimal("1.0"), limit_price=Decimal("2900.00"))

    assert router.submit_order(order) is None
    _drive_paper_partial(router, order, quantity=Decimal("0.25"), offset=2)
    assert store.get_reservation_ledger(order.id)["filled_qty"] == "0.25"

    _drive_paper_partial(router, order, quantity=Decimal("0.75"), offset=4)
    result = router._reservation_lifecycle_full_fill_results[-1]

    assert result["applied"] is True
    assert manager.reservations_for() == []
    row = store.get_reservation_ledger(order.id)
    assert row["is_active"] is False
    assert row["is_terminal"] is True
    assert str(row["terminal_status"]).lower() == "filled"
    assert store.get_reservation_release_tombstone(reservation_id=order.id) is not None


def test_full_fill_without_active_reservation_fails_closed(tmp_path):
    store = StateStore(str(tmp_path / "missing-full-active.db"))
    manager = ExposureManager(initial_equity=Decimal("20000"))
    coordinator = ReservationLifecycleCoordinator(exposure_manager=manager, state_store=store)
    router = _enabled_router(coordinator, paper_mode=True, state_store=store)
    order = _order(quantity=Decimal("1.0"), limit_price=Decimal("2900.00"))

    result = router._record_reservation_full_fill(
        order,
        release_idempotency_key="missing-active-full-release-key",
        cumulative_filled_qty=order.quantity,
        fill_delta_qty=Decimal("1.0"),
        status_source="paper_broker.execution_report",
        terminal_source="paper_broker.execution_report",
        source_event_id="paper_report_missing_full_active",
    )

    assert result["applied"] is False
    assert result["failed_reason"] == "active_reservation_not_found"
    assert store.list_reservation_ledger(active_only=True) == []
    assert store.get_reservation_release_tombstone(reservation_id=order.id) is None
    assert manager.reservations_for() == []


def test_full_fill_path_still_does_not_call_terminal_or_cancel_release():
    coordinator = _SpyCoordinator()
    router = _enabled_router(coordinator, paper_mode=True)
    order = _order(quantity=Decimal("1.0"), limit_price=Decimal("2900.00"))

    assert router.submit_order(order) is None
    _drive_paper_partial(router, order, quantity=Decimal("1.0"), offset=2)

    assert len(coordinator.full_calls) == 1
    assert coordinator.terminal_calls == []
    assert coordinator.release_calls == []
    assert len(coordinator.ack_calls) == 1


def test_default_disabled_paper_terminal_non_fill_makes_zero_coordinator_calls_and_zero_release(tmp_path):
    coordinator = _SpyCoordinator()
    store = StateStore(str(tmp_path / "disabled-terminal-non-fill.db"))
    router = OrderRouter(
        paper_mode=True,
        state_store=store,
        reservation_lifecycle_coordinator=coordinator,
    )
    order = _order(quantity=Decimal("1.0"), limit_price=Decimal("2900.00"))

    assert router.submit_order(order) is None
    for status in (OrderStatus.CANCELLED, OrderStatus.EXPIRED, OrderStatus.REJECTED):
        report, source_event_id = _paper_terminal_report(order, status, source_event_id=f"paper_report_{status.value}")
        router._record_paper_report_lifecycle(order, report, source_event_id=source_event_id)

    assert coordinator.ack_calls == []
    assert coordinator.terminal_non_fill_calls == []
    assert store.get_reservation_release_tombstone(reservation_id=order.id) is None
    assert all(
        result["failed_reason"] == "reservation_lifecycle_disabled"
        for result in router._reservation_lifecycle_terminal_non_fill_results
    )


def test_enabled_paper_canceled_releases_once_with_stable_key(tmp_path):
    store = StateStore(str(tmp_path / "paper-cancel-release.db"))
    manager = ExposureManager(initial_equity=Decimal("20000"))
    coordinator = ReservationLifecycleCoordinator(exposure_manager=manager, state_store=store)
    router = _enabled_router(coordinator, paper_mode=True, state_store=store)
    order = _order(quantity=Decimal("1.0"), limit_price=Decimal("2900.00"))

    assert router.submit_order(order) is None
    report, source_event_id = _paper_terminal_report(order, OrderStatus.CANCELLED, source_event_id="paper_report_cancelled")
    router._record_paper_report_lifecycle(order, report, source_event_id=source_event_id)
    expected_key = router._paper_lifecycle_idempotency_key(
        order,
        lifecycle_phase="order_canceled",
        broker_order_id=str(report.order_id),
        event_ts_ns=int(report.timestamp_ns),
        source_event_id=source_event_id,
    ) + ":release"

    result = router._reservation_lifecycle_terminal_non_fill_results[-1]
    assert result["applied"] is True
    assert manager.reservations_for() == []
    tombstone = store.get_reservation_release_tombstone(reservation_id=order.id)
    assert tombstone["release_idempotency_key"] == expected_key
    assert tombstone["terminal_status"] == "cancelled"

    duplicate = router._record_reservation_terminal_non_fill(
        order,
        release_idempotency_key=expected_key,
        terminal_status="cancelled",
        terminal_source="paper_broker.execution_report",
        terminal_reason="paper_broker_cancelled",
        source_event_id=source_event_id,
    )
    assert duplicate["idempotent"] is True


def test_enabled_paper_expired_and_rejected_release_once(tmp_path):
    for idx, (status, phase, terminal_status, reason) in enumerate(
        (
            (OrderStatus.EXPIRED, "order_expired", "expired", "paper_broker_expired"),
            (OrderStatus.REJECTED, "order_rejected", "rejected", "paper_broker_rejected"),
        )
    ):
        store = StateStore(str(tmp_path / f"paper-{terminal_status}-release.db"))
        manager = ExposureManager(initial_equity=Decimal("20000"))
        coordinator = ReservationLifecycleCoordinator(exposure_manager=manager, state_store=store)
        router = _enabled_router(coordinator, paper_mode=True, state_store=store)
        order = _order(
            order_id=f"terminal-non-fill-{idx}",
            decision_uuid=f"terminal-non-fill-decision-{idx}",
            quantity=Decimal("1.0"),
            limit_price=Decimal("2900.00"),
        )

        assert router.submit_order(order) is None
        report, source_event_id = _paper_terminal_report(order, status, source_event_id=f"paper_report_{terminal_status}")
        router._record_paper_report_lifecycle(order, report, source_event_id=source_event_id)
        expected_key = router._paper_lifecycle_idempotency_key(
            order,
            lifecycle_phase=phase,
            broker_order_id=str(report.order_id),
            event_ts_ns=int(report.timestamp_ns),
            source_event_id=source_event_id,
        ) + ":release"

        result = router._reservation_lifecycle_terminal_non_fill_results[-1]
        assert result["applied"] is True
        assert manager.reservations_for() == []
        tombstone = store.get_reservation_release_tombstone(reservation_id=order.id)
        assert tombstone["release_idempotency_key"] == expected_key
        assert tombstone["terminal_status"] == terminal_status
        assert tombstone["release_reason"] == reason


def test_partial_fill_then_terminal_non_fill_releases_remaining_once(tmp_path):
    for idx, (status, terminal_status) in enumerate(
        ((OrderStatus.CANCELLED, "cancelled"), (OrderStatus.EXPIRED, "expired"))
    ):
        store = StateStore(str(tmp_path / f"partial-then-{terminal_status}.db"))
        manager = ExposureManager(initial_equity=Decimal("20000"))
        coordinator = ReservationLifecycleCoordinator(exposure_manager=manager, state_store=store)
        router = _enabled_router(coordinator, paper_mode=True, state_store=store)
        order = _order(
            order_id=f"partial-terminal-{idx}",
            decision_uuid=f"partial-terminal-decision-{idx}",
            quantity=Decimal("1.0"),
            limit_price=Decimal("2900.00"),
        )

        assert router.submit_order(order) is None
        _drive_paper_partial(router, order, quantity=Decimal("0.25"), offset=2)
        assert store.get_reservation_ledger(order.id)["filled_qty"] == "0.25"

        report, source_event_id = _paper_terminal_report(order, status, source_event_id=f"paper_report_{terminal_status}")
        router._record_paper_report_lifecycle(order, report, source_event_id=source_event_id)

        result = router._reservation_lifecycle_terminal_non_fill_results[-1]
        assert result["applied"] is True
        assert manager.reservations_for() == []
        row = store.get_reservation_ledger(order.id)
        assert row["is_active"] is False
        assert row["is_terminal"] is True
        assert str(row["terminal_status"]).lower() == terminal_status
        assert store.get_reservation_release_tombstone(reservation_id=order.id) is not None


def test_cancel_request_and_cancel_rejected_still_do_not_release():
    coordinator = _SpyCoordinator()
    router = _enabled_router(coordinator, paper_mode=True)
    order = _order(quantity=Decimal("1.0"), limit_price=Decimal("2900.00"))

    assert router.submit_order(order) is None

    def reject_cancel(order_id, ts_ns):
        return _PaperReport(
            client_id=order_id,
            order_id=f"paper-{order_id}",
            status=OrderStatus.REJECTED,
            timestamp_ns=ts_ns,
        )

    router._paper_broker.cancel_order = reject_cancel

    assert router.cancel_order(order.id) is True
    assert coordinator.terminal_non_fill_calls == []
    assert coordinator.release_calls == []


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
    assert "guarded_release_reservation(" not in source
    assert "on_terminal_mapping_proof(" not in source
    assert "on_cancel_requested(" not in source
    assert "on_cancel_rejected(" not in source
    assert "on_orphan_or_drift(" not in source
    assert "on_status_failure(" not in source
    assert "on_open_order_absence(" not in source
    assert "on_partial_fill(" not in inspect.getsource(OrderRouter._submit_order_kraken)
    assert "on_partial_fill(" not in inspect.getsource(OrderRouter._submit_order_alpaca)
    assert "on_partial_fill(" not in inspect.getsource(OrderRouter._get_kraken_order_fill)
    assert "on_partial_fill(" not in inspect.getsource(OrderRouter._get_alpaca_order_fill)
    assert "on_partial_fill(" not in inspect.getsource(OrderRouter._query_kraken_order_status)
    assert "on_partial_fill(" not in inspect.getsource(OrderRouter._query_alpaca_order_status)
    assert "on_full_fill(" not in inspect.getsource(OrderRouter._submit_order_kraken)
    assert "on_full_fill(" not in inspect.getsource(OrderRouter._submit_order_alpaca)
    assert "on_full_fill(" not in inspect.getsource(OrderRouter._get_kraken_order_fill)
    assert "on_full_fill(" not in inspect.getsource(OrderRouter._get_alpaca_order_fill)
    assert "on_full_fill(" not in inspect.getsource(OrderRouter._query_kraken_order_status)
    assert "on_full_fill(" not in inspect.getsource(OrderRouter._query_alpaca_order_status)
    assert "on_terminal_non_fill(" not in inspect.getsource(OrderRouter._submit_order_kraken)
    assert "on_terminal_non_fill(" not in inspect.getsource(OrderRouter._submit_order_alpaca)
    assert "on_terminal_non_fill(" not in inspect.getsource(OrderRouter._get_kraken_order_fill)
    assert "on_terminal_non_fill(" not in inspect.getsource(OrderRouter._get_alpaca_order_fill)
    assert "on_terminal_non_fill(" not in inspect.getsource(OrderRouter._query_kraken_order_status)
    assert "on_terminal_non_fill(" not in inspect.getsource(OrderRouter._query_alpaca_order_status)
    assert "broker_adapter" not in source
