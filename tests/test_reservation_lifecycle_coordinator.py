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


def _terminal_non_fill_kwargs(**overrides):
    data = {
        "client_order_id": "client-order-001",
        "reservation_id": "reservation-001",
        "reservation_dedupe_key": "decision-001:client-order-001",
        "release_idempotency_key": "reservation-001:terminal_non_fill:cancelled:proof-001",
        "terminal_status": "cancelled",
        "terminal_source": "paper_broker.execution_report",
        "terminal_reason": "paper_broker_cancelled",
        "source_event_id": "terminal-non-fill-001",
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


def test_terminal_non_fill_accepts_cancelled_statuses(tmp_path):
    for idx, status in enumerate(("cancelled", "canceled")):
        coordinator, manager, store = _coordinator(tmp_path)
        client_order_id = f"client-order-{idx}"
        dedupe_key = f"decision-001:{client_order_id}"
        reservation_id = f"reservation-{status}"
        assert _open(
            coordinator,
            reservation_id=reservation_id,
            client_order_id=client_order_id,
            reservation_dedupe_key=dedupe_key,
        )["applied"] is True

        result = coordinator.on_terminal_non_fill(
            **_terminal_non_fill_kwargs(
                client_order_id=client_order_id,
                reservation_id=reservation_id,
                reservation_dedupe_key=dedupe_key,
                release_idempotency_key=f"{reservation_id}:terminal_non_fill:{status}:proof-001",
                terminal_status=status,
            )
        )

        assert result["applied"] is True
        assert manager.reservations_for() == []
        tombstone = store.get_reservation_release_tombstone(reservation_id=reservation_id)
        assert tombstone["terminal_status"] == "cancelled"


def test_terminal_non_fill_accepts_expired_and_rejected_statuses(tmp_path):
    for idx, (status, reason) in enumerate((("expired", "paper_broker_expired"), ("rejected", "paper_broker_rejected"))):
        coordinator, manager, store = _coordinator(tmp_path)
        client_order_id = f"client-order-terminal-{idx}"
        dedupe_key = f"decision-001:{client_order_id}"
        reservation_id = f"reservation-{status}"
        assert _open(
            coordinator,
            reservation_id=reservation_id,
            client_order_id=client_order_id,
            reservation_dedupe_key=dedupe_key,
        )["applied"] is True

        result = coordinator.on_terminal_non_fill(
            **_terminal_non_fill_kwargs(
                client_order_id=client_order_id,
                reservation_id=reservation_id,
                reservation_dedupe_key=dedupe_key,
                release_idempotency_key=f"{reservation_id}:terminal_non_fill:{status}:proof-001",
                terminal_status=status,
                terminal_reason=reason,
            )
        )

        assert result["applied"] is True
        assert manager.reservations_for() == []
        assert store.get_reservation_release_tombstone(reservation_id=reservation_id)["terminal_status"] == status


def test_terminal_non_fill_duplicate_release_key_is_idempotent(tmp_path):
    coordinator, manager, store = _coordinator(tmp_path)
    assert _open(coordinator, reservation_id="reservation-001")["applied"] is True

    first = coordinator.on_terminal_non_fill(**_terminal_non_fill_kwargs())
    duplicate = coordinator.on_terminal_non_fill(**_terminal_non_fill_kwargs())

    assert first["applied"] is True
    assert duplicate["idempotent"] is True
    assert manager.reservations_for() == []
    assert store.get_reservation_release_tombstone(reservation_id="reservation-001") is not None


def test_terminal_non_fill_rejects_forbidden_statuses_sources_and_reasons(tmp_path):
    coordinator, manager, store = _coordinator(tmp_path)
    assert _open(coordinator, reservation_id="reservation-001")["applied"] is True

    unsupported = coordinator.on_terminal_non_fill(
        **_terminal_non_fill_kwargs(
            release_idempotency_key="reservation-001:bad-status",
            terminal_status="cancel_requested",
            terminal_reason="paper_broker_cancelled",
        )
    )
    cancel_rejected = coordinator.on_terminal_non_fill(
        **_terminal_non_fill_kwargs(
            release_idempotency_key="reservation-001:cancel-rejected",
            terminal_status="cancelled",
            terminal_reason="cancel_rejected",
        )
    )
    rejected_before_ack = coordinator.on_terminal_non_fill(
        **_terminal_non_fill_kwargs(
            release_idempotency_key="reservation-001:rejected-before-ack",
            terminal_status="rejected",
            terminal_reason="rejected_before_ack",
        )
    )
    submit_failure = coordinator.on_terminal_non_fill(
        **_terminal_non_fill_kwargs(
            release_idempotency_key="reservation-001:submit-failure",
            terminal_status="rejected",
            terminal_reason="submit_failure",
        )
    )
    terminal_mapping = coordinator.on_terminal_non_fill(
        **_terminal_non_fill_kwargs(
            release_idempotency_key="reservation-001:terminal-mapping",
            terminal_status="cancelled",
            terminal_source="terminal_mapping_proof",
        )
    )

    assert unsupported["failed_reason"] == "unsupported_terminal_non_fill_status"
    for result in (cancel_rejected, rejected_before_ack, submit_failure, terminal_mapping):
        assert result["failed_reason"] == "forbidden_terminal_non_fill_event"
    assert len(manager.reservations_for()) == 1
    assert store.get_reservation_release_tombstone(reservation_id="reservation-001") is None


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
    heartbeat_init = inspect.getsource(app_main.SovereignHeartbeat.__init__)
    assert "reservation_lifecycle_coordinator=self.reservation_lifecycle_coordinator" in heartbeat_init
    assert "reservation_lifecycle_enabled=self.reservation_lifecycle_enabled" in heartbeat_init
    assert "broker_adapter" not in inspect.getsource(ReservationLifecycleCoordinator)
