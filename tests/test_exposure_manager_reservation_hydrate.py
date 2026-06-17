import inspect
from decimal import Decimal

from app.models.enums import EventSource, OrderSide, ReplayMode, SleeveType, TradeIntent
from app.risk.exposure_manager import (
    EXPOSURE_AUTHORITY_STATUS,
    ExposureManager,
    PendingReservation,
    ReservationStatus,
    exposure_authority_seam_metadata,
)


def _manager():
    return ExposureManager(initial_equity=Decimal("20000"))


def _reservation(
    *,
    reservation_id="reservation-001",
    client_order_id="client-order-001",
    dedupe_key="decision-001:client-order-001",
    status=ReservationStatus.ACKNOWLEDGED,
    filled_qty=Decimal("0"),
    cancelled_qty=Decimal("0"),
):
    return PendingReservation(
        reservation_id=reservation_id,
        sleeve=SleeveType.SECTOR_ROTATION,
        symbol="ETH/USD",
        side=OrderSide.BUY,
        qty=Decimal("1.0"),
        price=Decimal("2500.00"),
        trade_intent=TradeIntent.UNKNOWN,
        status=status,
        confidence_weight=Decimal("1.00"),
        replay_mode=ReplayMode.RECOVERY,
        created_at_ns=1_700_000_000_000_000_000,
        last_update_ns=1_700_000_000_000_000_100,
        filled_qty=filled_qty,
        cancelled_qty=cancelled_qty,
        client_order_id=client_order_id,
        dedupe_key=dedupe_key,
        source=EventSource.HYDRATION,
    )


def _ledger_row(
    *,
    reservation_id="reservation-001",
    client_order_id="client-order-001",
    decision_uuid="decision-001",
    dedupe_key="decision-001:client-order-001",
    price_basis="2500.00",
    status="ACKNOWLEDGED",
    original_qty="1.0",
    open_qty="1.0",
    filled_qty="0",
    cancelled_qty="0",
    is_active=True,
    is_terminal=False,
    terminal_status=None,
):
    return {
        "reservation_id": reservation_id,
        "client_order_id": client_order_id,
        "decision_uuid": decision_uuid,
        "reservation_dedupe_key": dedupe_key,
        "symbol": "ETH/USD",
        "side": "buy",
        "sleeve": "sector_rotation",
        "order_type": "limit",
        "original_qty": original_qty,
        "open_qty": open_qty,
        "filled_qty": filled_qty,
        "cancelled_qty": cancelled_qty,
        "price_basis": price_basis,
        "notional_basis": "2500.00",
        "status": status,
        "confidence_weight": "1.00",
        "created_at_ns": 1_700_000_000_000_000_000,
        "updated_at_ns": 1_700_000_000_000_000_100,
        "terminal_status": terminal_status,
        "terminal_reason": terminal_status,
        "terminal_source": None,
        "source_lifecycle_phase": "order_submitted",
        "source_idempotency_key": dedupe_key,
        "is_active": is_active,
        "is_terminal": is_terminal,
    }


def _tombstone(reservation_id="reservation-001", dedupe_key="decision-001:client-order-001"):
    return {
        "release_idempotency_key": f"{reservation_id}:terminal_mapping_proof:filled:proof-001",
        "reservation_id": reservation_id,
        "client_order_id": "client-order-001",
        "reservation_dedupe_key": dedupe_key,
        "release_reason": "terminal_mapping_proof",
        "terminal_status": "filled",
        "terminal_source": "mark_terminal_from_status_evidence",
        "released_qty": "1.0",
        "released_notional": "2500.00",
        "released_at_ns": 1_700_000_000_000_000_200,
        "source_event_id": "proof-001",
        "release_applied": True,
        "exposure_release_scope": "reservation_only",
    }


def _fill_progress(
    reservation_id="reservation-001",
    client_order_id="client-order-001",
    *,
    fill_key="fill-progress-001",
    cumulative="0.25",
    delta="0.25",
    applied_at_ns=1_700_000_000_000_000_150,
):
    return {
        "fill_idempotency_key": fill_key,
        "reservation_id": reservation_id,
        "client_order_id": client_order_id,
        "cumulative_filled_qty": cumulative,
        "fill_delta_qty": delta,
        "status_source": "paper_broker.execution_report",
        "source_event_id": fill_key,
        "applied_at_ns": applied_at_ns,
    }


def test_export_pending_reservation_to_ledger_compatible_dict():
    manager = _manager()
    reservation = _reservation()
    manager._reservations[reservation.reservation_id] = reservation
    manager._reservation_dedupe[reservation.dedupe_key] = reservation.reservation_id

    rows = manager.export_reservation_ledger_rows()

    assert len(rows) == 1
    row = rows[0]
    assert row["reservation_id"] == "reservation-001"
    assert row["client_order_id"] == "client-order-001"
    assert row["decision_uuid"] == "decision-001"
    assert row["reservation_dedupe_key"] == "decision-001:client-order-001"
    assert row["side"] == "buy"
    assert row["sleeve"] == "sector_rotation"
    assert row["original_qty"] == "1.0"
    assert row["open_qty"] == "1.0"
    assert row["price_basis"] == "2500.00"
    assert row["notional_basis"] == "2500.000"
    assert row["is_active"] is True
    assert row["is_terminal"] is False


def test_hydrate_open_ledger_row_into_reservations_and_dedupe():
    manager = _manager()

    result = manager.hydrate_reservations_from_ledger([_ledger_row()])

    assert result["hydrated"] == ("reservation-001",)
    assert result["valid"] is True
    reservations = manager.reservations_for(SleeveType.SECTOR_ROTATION, "ETH/USD")
    assert len(reservations) == 1
    restored = reservations[0]
    assert restored.reservation_id == "reservation-001"
    assert restored.price == Decimal("2500.00")
    assert restored.replay_mode == ReplayMode.RECOVERY
    assert restored.source == EventSource.HYDRATION
    assert manager._reservation_dedupe["decision-001:client-order-001"] == "reservation-001"


def test_terminal_ledger_row_is_skipped_fail_closed():
    manager = _manager()
    row = _ledger_row(status="FILLED", is_active=False, is_terminal=True, terminal_status="FILLED")

    result = manager.hydrate_reservations_from_ledger([row])

    assert result["hydrated"] == ()
    assert result["skipped"][0]["reason"] == "terminal_ledger_row"
    assert manager.reservations_for() == []


def test_tombstoned_reservation_row_is_skipped_fail_closed():
    manager = _manager()

    result = manager.hydrate_reservations_from_ledger([_ledger_row()], release_tombstones=[_tombstone()])

    assert result["hydrated"] == ()
    assert result["skipped"][0]["reason"] == "release_tombstone_present"
    assert manager.reservations_for() == []


def test_missing_price_basis_does_not_hydrate_active_reservation():
    manager = _manager()
    row = _ledger_row(price_basis=None)

    result = manager.hydrate_reservations_from_ledger([row])

    assert result["hydrated"] == ()
    assert result["skipped"][0]["reason"] == "missing_price_basis"
    assert manager.reservations_for() == []


def test_duplicate_dedupe_key_conflict_fails_closed():
    manager = _manager()
    first = _ledger_row(reservation_id="reservation-a")
    second = _ledger_row(reservation_id="reservation-b", client_order_id="client-order-b")

    first_result = manager.hydrate_reservations_from_ledger([first])
    second_result = manager.hydrate_reservations_from_ledger([second])

    assert first_result["hydrated"] == ("reservation-a",)
    assert second_result["hydrated"] == ()
    assert second_result["skipped"][0]["reason"] == "duplicate_dedupe_conflict"
    assert [item.reservation_id for item in manager.reservations_for()] == ["reservation-a"]


def test_duplicate_dedupe_same_reservation_id_is_idempotent():
    manager = _manager()
    row = _ledger_row()

    manager.hydrate_reservations_from_ledger([row])
    result = manager.hydrate_reservations_from_ledger([row])

    assert result["hydrated"] == ("reservation-001",)
    assert [item.reservation_id for item in manager.reservations_for()] == ["reservation-001"]
    assert manager._reservation_dedupe["decision-001:client-order-001"] == "reservation-001"


def test_filled_and_cancelled_progress_survive_hydrate():
    manager = _manager()
    row = _ledger_row(
        status="PARTIALLY_FILLED",
        original_qty="1.0",
        open_qty="0.65",
        filled_qty="0.25",
        cancelled_qty="0.10",
    )

    result = manager.hydrate_reservations_from_ledger([row])

    assert result["valid"] is True
    restored = manager.reservations_for()[0]
    assert restored.filled_qty == Decimal("0.25")
    assert restored.cancelled_qty == Decimal("0.10")
    assert restored.open_qty == Decimal("0.65")
    assert manager.validate_invariants().valid is True


def test_hydrate_catches_up_fill_progress_ahead_of_ledger():
    manager = _manager()

    result = manager.hydrate_reservations_from_ledger(
        [_ledger_row(filled_qty="0", open_qty="1.0")],
        fill_progress=[
            _fill_progress(fill_key="fill-progress-001", cumulative="0.25"),
            _fill_progress(fill_key="fill-progress-002", cumulative="0.50", delta="0.25"),
        ],
    )

    assert result["hydrated"] == ("reservation-001",)
    assert result["valid"] is True
    restored = manager.reservations_for()[0]
    assert restored.filled_qty == Decimal("0.50")
    assert restored.open_qty == Decimal("0.50")
    assert restored.status == ReservationStatus.PARTIALLY_FILLED


def test_hydrate_does_not_reduce_ledger_ahead_of_fill_progress():
    manager = _manager()

    result = manager.hydrate_reservations_from_ledger(
        [_ledger_row(status="PARTIALLY_FILLED", filled_qty="0.60", open_qty="0.40")],
        fill_progress=[_fill_progress(cumulative="0.25")],
    )

    assert result["hydrated"] == ("reservation-001",)
    restored = manager.reservations_for()[0]
    assert restored.filled_qty == Decimal("0.60")
    assert restored.open_qty == Decimal("0.40")


def test_hydrate_ignores_fill_progress_for_unknown_reservation():
    manager = _manager()

    result = manager.hydrate_reservations_from_ledger(
        [_ledger_row()],
        fill_progress=[_fill_progress(reservation_id="unknown-reservation", cumulative="0.75")],
    )

    assert result["hydrated"] == ("reservation-001",)
    assert [item.reservation_id for item in manager.reservations_for()] == ["reservation-001"]
    assert manager.reservations_for()[0].filled_qty == Decimal("0")


def test_hydrate_rejects_over_original_fill_progress_fail_closed():
    manager = _manager()

    result = manager.hydrate_reservations_from_ledger(
        [_ledger_row()],
        fill_progress=[_fill_progress(cumulative="1.25")],
    )

    assert result["hydrated"] == ()
    assert result["skipped"][0]["reason"] == "fill_progress_exceeds_original_qty"
    assert manager.reservations_for() == []


def test_exposure_manager_live_wired_without_broker_adapter_mutation_authority():
    import app.execution.engine as execution_engine_module
    import app.main_loop as main_loop_module

    metadata = exposure_authority_seam_metadata()
    assert metadata["status"] == EXPOSURE_AUTHORITY_STATUS
    assert metadata["status"] == "LIVE_RUNTIME"
    assert metadata["live_wired"] is True
    assert metadata["active_veto_owner"] is True

    create_main_loop_src = inspect.getsource(main_loop_module.create_main_loop)
    submit_signal_src = inspect.getsource(execution_engine_module.ExecutionEngine.submit_signal)
    hydrate_src = inspect.getsource(ExposureManager.hydrate_reservations_from_ledger)

    assert "exposure_manager" in create_main_loop_src
    assert "_portfolio_risk_gate_missing_evidence" in submit_signal_src
    assert "broker_adapter" not in hydrate_src
    assert "reserve_intent(" not in hydrate_src
    assert "release_reservation(" not in hydrate_src
    assert "apply_fill_to_reservation(" not in hydrate_src
