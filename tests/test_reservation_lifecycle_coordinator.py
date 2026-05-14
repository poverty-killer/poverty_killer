import inspect
from decimal import Decimal

from app.models.enums import OrderSide, SleeveType
from app.risk.exposure_manager import ExposureManager
from app.risk.reservation_lifecycle_coordinator import ReservationLifecycleCoordinator
from app.state.state_store import StateStore


def _store(tmp_path):
    return StateStore(str(tmp_path / "state.db"))


def _manager():
    return ExposureManager(initial_equity=Decimal("20000"))


def _coordinator(tmp_path):
    manager = _manager()
    store = _store(tmp_path)
    return ReservationLifecycleCoordinator(exposure_manager=manager, state_store=store), manager, store


def _ack_kwargs(**overrides):
    data = {
        "client_order_id": "client-order-001",
        "decision_uuid": "decision-001",
        "reservation_dedupe_key": "decision-001:client-order-001",
        "symbol": "ETH/USD",
        "side": OrderSide.BUY,
        "sleeve": SleeveType.SECTOR_ROTATION,
        "qty": Decimal("1.0"),
        "price_basis": Decimal("2500.00"),
        "order_type": "limit",
        "source_idempotency_key": "decision-001:client-order-001:ack",
    }
    data.update(overrides)
    return data


def _open(coordinator, **overrides):
    return coordinator.on_order_acknowledged(**_ack_kwargs(**overrides))


def _partial_kwargs(**overrides):
    data = {
        "client_order_id": "client-order-001",
        "fill_idempotency_key": "fill-001",
        "cumulative_filled_qty": Decimal("0.25"),
        "fill_delta_qty": Decimal("0.25"),
        "status_source": "direct_fill_observation",
        "source_event_id": "fill-event-001",
    }
    data.update(overrides)
    return data


def _full_kwargs(**overrides):
    data = {
        "client_order_id": "client-order-001",
        "release_idempotency_key": "reservation-001:full_fill:proof-001",
        "cumulative_filled_qty": Decimal("1.0"),
        "status_source": "direct_full_fill_observation",
        "source_event_id": "full-fill-001",
    }
    data.update(overrides)
    return data


def test_coordinator_has_no_broker_or_command_surface():
    source = inspect.getsource(ReservationLifecycleCoordinator)

    assert "broker_adapter" not in source
    assert "requests" not in source
    assert "submit_order(" not in source
    assert "cancel_order(" not in source
    assert "record_event(" not in source


def test_acked_limit_order_with_positive_price_opens_reservation(tmp_path):
    coordinator, manager, store = _coordinator(tmp_path)

    result = _open(coordinator, reservation_id="reservation-001")

    assert result["applied"] is True
    assert result["action"] == "order_acknowledged"
    assert result["exposure_manager_called"] is True
    assert result["broker_command_performed"] is False
    assert store.get_reservation_ledger("reservation-001")["price_basis"] == "2500.00"
    assert len(manager.reservations_for()) == 1


def test_duplicate_ack_dedupe_does_not_double_reserve(tmp_path):
    coordinator, manager, _store_obj = _coordinator(tmp_path)
    assert _open(coordinator, reservation_id="reservation-001")["applied"] is True

    result = _open(coordinator, reservation_id="reservation-001")

    assert result["idempotent"] is True
    assert len(manager.reservations_for()) == 1


def test_rejected_before_ack_creates_no_reservation(tmp_path):
    coordinator, manager, store = _coordinator(tmp_path)

    result = coordinator.on_rejected_before_ack(client_order_id="client-order-001")

    assert result["skipped"] is True
    assert result["exposure_manager_called"] is False
    assert manager.reservations_for() == []
    assert store.list_reservation_ledger(active_only=True) == []


def test_market_or_missing_price_basis_does_not_open_active_reservation(tmp_path):
    coordinator, manager, store = _coordinator(tmp_path)

    missing = _open(coordinator, reservation_id="reservation-missing", price_basis=None)
    market = _open(
        coordinator,
        reservation_id="reservation-market",
        order_type="market",
        price_basis=Decimal("2500.00"),
        price_basis_source_proven=False,
    )

    assert missing["applied"] is False
    assert "price_basis" in missing["failed_reason"]
    assert market["applied"] is False
    assert market["failed_reason"] == "price_basis_not_source_proven"
    assert manager.reservations_for() == []
    assert store.list_reservation_ledger(active_only=True) == []


def test_partial_fill_advancing_cumulative_applies_once(tmp_path):
    coordinator, manager, store = _coordinator(tmp_path)
    assert _open(coordinator, reservation_id="reservation-001")["applied"] is True

    result = coordinator.on_partial_fill(**_partial_kwargs())

    assert result["applied"] is True
    assert manager.reservations_for()[0].filled_qty == Decimal("0.25")
    assert store.get_reservation_ledger("reservation-001")["filled_qty"] == "0.25"


def test_duplicate_fill_key_noops_idempotent(tmp_path):
    coordinator, manager, _store_obj = _coordinator(tmp_path)
    assert _open(coordinator, reservation_id="reservation-001")["applied"] is True
    assert coordinator.on_partial_fill(**_partial_kwargs())["applied"] is True

    result = coordinator.on_partial_fill(**_partial_kwargs())

    assert result["idempotent"] is True
    assert manager.reservations_for()[0].filled_qty == Decimal("0.25")


def test_non_advancing_cumulative_fill_fails_closed(tmp_path):
    coordinator, manager, _store_obj = _coordinator(tmp_path)
    assert _open(coordinator, reservation_id="reservation-001")["applied"] is True
    assert coordinator.on_partial_fill(**_partial_kwargs())["applied"] is True

    result = coordinator.on_partial_fill(
        **_partial_kwargs(fill_idempotency_key="fill-002", source_event_id="fill-event-002")
    )

    assert result["applied"] is False
    assert result["failed_reason"] == "non_advancing_cumulative_fill"
    assert manager.reservations_for()[0].filled_qty == Decimal("0.25")


def test_full_fill_releases_once(tmp_path):
    coordinator, manager, store = _coordinator(tmp_path)
    assert _open(coordinator, reservation_id="reservation-001")["applied"] is True

    result = coordinator.on_full_fill(**_full_kwargs())
    duplicate = coordinator.on_full_fill(**_full_kwargs())

    assert result["applied"] is True
    assert duplicate["idempotent"] is True
    assert manager.reservations_for() == []
    tombstone = store.get_reservation_release_tombstone(reservation_id="reservation-001")
    assert tombstone["release_idempotency_key"] == "reservation-001:full_fill:proof-001"


def test_terminal_mapping_proof_releases_only_after_unique_active_ledger_lookup(tmp_path):
    coordinator, manager, store = _coordinator(tmp_path)
    assert _open(coordinator, reservation_id="reservation-001")["applied"] is True

    result = coordinator.on_terminal_mapping_proof(
        client_order_id="client-order-001",
        terminal_status="filled",
        terminal_reason="status_evidence_filled",
        terminal_source="mark_terminal_from_status_evidence",
        source_event_id="proof-001",
    )

    assert result["applied"] is True
    assert manager.reservations_for() == []
    assert store.get_reservation_release_tombstone(reservation_id="reservation-001") is not None


def test_terminal_mapping_proof_without_ledger_match_does_not_release(tmp_path):
    coordinator, manager, _store_obj = _coordinator(tmp_path)

    result = coordinator.on_terminal_mapping_proof(
        client_order_id="missing-client-order",
        terminal_status="filled",
        terminal_reason="status_evidence_filled",
        terminal_source="mark_terminal_from_status_evidence",
    )

    assert result["applied"] is False
    assert result["skipped"] is True
    assert result["failed_reason"] == "active_reservation_not_found"
    assert manager.reservations_for() == []


def test_terminal_mapping_proof_with_conflicting_ledger_match_fails_closed(tmp_path):
    coordinator, manager, _store_obj = _coordinator(tmp_path)
    assert _open(
        coordinator,
        reservation_id="reservation-a",
        client_order_id="shared-client-order",
        decision_uuid="decision-a",
        reservation_dedupe_key="decision-a:shared-client-order",
    )["applied"] is True
    assert _open(
        coordinator,
        reservation_id="reservation-b",
        client_order_id="shared-client-order",
        decision_uuid="decision-b",
        reservation_dedupe_key="decision-b:shared-client-order",
    )["applied"] is True

    result = coordinator.on_terminal_mapping_proof(
        client_order_id="shared-client-order",
        terminal_status="filled",
        terminal_reason="status_evidence_filled",
        terminal_source="mark_terminal_from_status_evidence",
    )

    assert result["applied"] is False
    assert result["failed_reason"] == "active_reservation_conflict"
    assert len(manager.reservations_for()) == 2


def test_no_release_events_never_mutate(tmp_path):
    coordinator, manager, store = _coordinator(tmp_path)
    assert _open(coordinator, reservation_id="reservation-001")["applied"] is True

    results = [
        coordinator.on_cancel_requested(client_order_id="client-order-001"),
        coordinator.on_cancel_rejected(client_order_id="client-order-001"),
        coordinator.on_orphan_or_drift(client_order_id="client-order-001"),
        coordinator.on_status_failure(client_order_id="client-order-001"),
        coordinator.on_open_order_absence(client_order_id="client-order-001"),
    ]

    assert all(item["skipped"] is True for item in results)
    assert all(item["mutation_attempted"] is False for item in results)
    assert all(item["exposure_manager_called"] is False for item in results)
    assert len(manager.reservations_for()) == 1
    assert store.get_reservation_release_tombstone(reservation_id="reservation-001") is None


def test_telemetry_is_not_accepted_as_mutation_authority(tmp_path):
    coordinator, manager, _store_obj = _coordinator(tmp_path)

    result = _open(
        coordinator,
        reservation_id="reservation-001",
        mutation_authority_source="telemetry",
    )

    assert result["applied"] is False
    assert result["failed_reason"] == "telemetry_not_mutation_authority"
    assert result["telemetry_authority_used"] is False
    assert manager.reservations_for() == []


def test_no_runtime_wiring_and_broker_adapter_inactive():
    import app.execution.engine as execution_engine_module
    import app.execution.order_router as order_router_module
    import app.main_loop as main_loop_module
    import app.telemetry.fill_recorder as fill_recorder_module
    import main as app_main

    assert "ReservationLifecycleCoordinator" not in inspect.getsource(execution_engine_module)
    assert "ReservationLifecycleCoordinator" not in inspect.getsource(order_router_module)
    assert "ReservationLifecycleCoordinator" not in inspect.getsource(fill_recorder_module)
    assert "ReservationLifecycleCoordinator" not in inspect.getsource(main_loop_module)
    assert "ReservationLifecycleCoordinator" not in inspect.getsource(app_main)
    assert "broker_adapter" not in inspect.getsource(ReservationLifecycleCoordinator)
