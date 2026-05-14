import inspect
from decimal import Decimal

from app.models.enums import OrderSide, SleeveType
from app.risk.exposure_manager import (
    EXPOSURE_AUTHORITY_STATUS,
    ExposureManager,
    exposure_authority_seam_metadata,
)
from app.state.state_store import StateStore


def _store(tmp_path):
    return StateStore(str(tmp_path / "state.db"))


def _manager():
    return ExposureManager(initial_equity=Decimal("20000"))


def _open_kwargs(**overrides):
    data = {
        "reservation_id": "reservation-001",
        "client_order_id": "client-order-001",
        "decision_uuid": "decision-001",
        "reservation_dedupe_key": "decision-001:client-order-001",
        "symbol": "ETH/USD",
        "side": OrderSide.BUY,
        "sleeve": SleeveType.SECTOR_ROTATION,
        "qty": Decimal("1.0"),
        "price_basis": Decimal("2500.00"),
        "order_type": "limit",
        "source_lifecycle_phase": "guarded_open_test",
        "source_idempotency_key": "decision-001:client-order-001:open",
    }
    data.update(overrides)
    return data


def _open(manager, store, **overrides):
    return manager.guarded_open_reservation(state_store=store, **_open_kwargs(**overrides))


def _fill_kwargs(**overrides):
    data = {
        "reservation_id": "reservation-001",
        "client_order_id": "client-order-001",
        "fill_idempotency_key": "venue-fill-001",
        "cumulative_filled_qty": Decimal("0.25"),
        "fill_delta_qty": Decimal("0.25"),
        "status_source": "paper_broker.execution_report",
        "source_event_id": "paper-report-001",
    }
    data.update(overrides)
    return data


def _release_kwargs(**overrides):
    data = {
        "reservation_id": "reservation-001",
        "client_order_id": "client-order-001",
        "reservation_dedupe_key": "decision-001:client-order-001",
        "release_idempotency_key": "reservation-001:terminal_mapping_proof:filled:proof-001",
        "release_reason": "terminal_mapping_proof",
        "terminal_status": "filled",
        "terminal_source": "mark_terminal_from_status_evidence",
        "released_qty": Decimal("1.0"),
        "released_notional": Decimal("2500.00"),
        "source_event_id": "proof-001",
    }
    data.update(overrides)
    return data


class FailingLedgerStore:
    def __init__(self, inner, *, fail_upsert=False):
        self.inner = inner
        self.fail_upsert = fail_upsert

    def get_reservation_release_tombstone(self, **kwargs):
        return self.inner.get_reservation_release_tombstone(**kwargs)

    def list_reservation_ledger(self, **kwargs):
        return self.inner.list_reservation_ledger(**kwargs)

    def get_reservation_ledger(self, reservation_id):
        return self.inner.get_reservation_ledger(reservation_id)

    def record_reservation_fill_progress(self, progress):
        return self.inner.record_reservation_fill_progress(progress)

    def list_reservation_fill_progress(self, reservation_id):
        return self.inner.list_reservation_fill_progress(reservation_id)

    def record_reservation_release_tombstone(self, tombstone):
        return self.inner.record_reservation_release_tombstone(tombstone)

    def upsert_reservation_ledger(self, row):
        if self.fail_upsert:
            return False
        return self.inner.upsert_reservation_ledger(row)


def test_guarded_open_success_persists_ledger_row(tmp_path):
    store = _store(tmp_path)
    manager = _manager()

    result = _open(manager, store)

    assert result["applied"] is True
    assert result["persistence_applied"] is True
    assert result["mutation_applied"] is True
    row = store.get_reservation_ledger("reservation-001")
    assert row["reservation_id"] == "reservation-001"
    assert row["reservation_dedupe_key"] == "decision-001:client-order-001"
    assert row["price_basis"] == "2500.00"
    assert len(manager.reservations_for()) == 1


def test_guarded_open_same_dedupe_is_idempotent(tmp_path):
    store = _store(tmp_path)
    manager = _manager()
    assert _open(manager, store)["applied"] is True

    result = _open(manager, store)

    assert result["idempotent"] is True
    assert result["failed_reason"] == "active_reservation_already_persisted"
    assert len(manager.reservations_for()) == 1


def test_guarded_open_conflicting_dedupe_fails_closed(tmp_path):
    store = _store(tmp_path)
    manager = _manager()
    assert _open(manager, store, reservation_id="reservation-a")["applied"] is True

    result = _open(manager, store, reservation_id="reservation-b", client_order_id="client-order-b")

    assert result["applied"] is False
    assert result["failed_reason"] == "duplicate_active_dedupe_conflict"
    assert [r.reservation_id for r in manager.reservations_for()] == ["reservation-a"]


def test_guarded_open_missing_or_non_positive_price_basis_fails_closed(tmp_path):
    store = _store(tmp_path)
    manager = _manager()

    missing = _open(manager, store, price_basis=None)
    non_positive = _open(manager, store, reservation_id="reservation-002", price_basis=Decimal("0"))

    assert missing["applied"] is False
    assert "price_basis" in missing["failed_reason"]
    assert non_positive["applied"] is False
    assert "price_basis" in non_positive["failed_reason"]
    assert manager.reservations_for() == []


def test_guarded_fill_advancing_cumulative_applies_once(tmp_path):
    store = _store(tmp_path)
    manager = _manager()
    assert _open(manager, store)["applied"] is True

    result = manager.guarded_apply_fill_to_reservation(state_store=store, **_fill_kwargs())

    assert result["applied"] is True
    reservation = manager.reservations_for()[0]
    assert reservation.filled_qty == Decimal("0.25")
    progress = store.list_reservation_fill_progress("reservation-001")
    assert [item["fill_idempotency_key"] for item in progress] == ["venue-fill-001"]
    assert store.get_reservation_ledger("reservation-001")["filled_qty"] == "0.25"


def test_guarded_fill_duplicate_key_is_idempotent_noop(tmp_path):
    store = _store(tmp_path)
    manager = _manager()
    assert _open(manager, store)["applied"] is True
    assert manager.guarded_apply_fill_to_reservation(state_store=store, **_fill_kwargs())["applied"] is True

    result = manager.guarded_apply_fill_to_reservation(state_store=store, **_fill_kwargs())

    assert result["idempotent"] is True
    assert result["failed_reason"] == "fill_key_already_recorded"
    assert manager.reservations_for()[0].filled_qty == Decimal("0.25")


def test_guarded_fill_non_advancing_cumulative_does_not_double_apply(tmp_path):
    store = _store(tmp_path)
    manager = _manager()
    assert _open(manager, store)["applied"] is True
    assert manager.guarded_apply_fill_to_reservation(state_store=store, **_fill_kwargs())["applied"] is True

    result = manager.guarded_apply_fill_to_reservation(
        state_store=store,
        **_fill_kwargs(fill_idempotency_key="venue-fill-002", source_event_id="paper-report-002"),
    )

    assert result["applied"] is False
    assert result["failed_reason"] == "non_advancing_cumulative_fill"
    assert manager.reservations_for()[0].filled_qty == Decimal("0.25")


def test_guarded_release_writes_tombstone_and_release_proof(tmp_path):
    store = _store(tmp_path)
    manager = _manager()
    assert _open(manager, store)["applied"] is True

    result = manager.guarded_release_reservation(state_store=store, **_release_kwargs())

    assert result["applied"] is True
    assert result["persistence_applied"] is True
    assert result["mutation_applied"] is True
    assert manager.reservations_for() == []
    tombstone = store.get_reservation_release_tombstone(reservation_id="reservation-001")
    assert tombstone["release_idempotency_key"] == "reservation-001:terminal_mapping_proof:filled:proof-001"
    row = store.get_reservation_ledger("reservation-001")
    assert row["is_active"] is False
    assert row["is_terminal"] is True
    assert row["terminal_source"] == "mark_terminal_from_status_evidence"


def test_guarded_release_same_key_is_idempotent_noop(tmp_path):
    store = _store(tmp_path)
    manager = _manager()
    assert _open(manager, store)["applied"] is True
    assert manager.guarded_release_reservation(state_store=store, **_release_kwargs())["applied"] is True

    result = manager.guarded_release_reservation(state_store=store, **_release_kwargs())

    assert result["idempotent"] is True
    assert result["failed_reason"] == "release_key_already_recorded"


def test_guarded_release_conflicting_tombstone_fails_closed(tmp_path):
    store = _store(tmp_path)
    manager = _manager()
    assert _open(manager, store)["applied"] is True
    assert manager.guarded_release_reservation(state_store=store, **_release_kwargs())["applied"] is True

    result = manager.guarded_release_reservation(
        state_store=store,
        **_release_kwargs(release_idempotency_key="reservation-001:terminal_mapping_proof:filled:proof-002"),
    )

    assert result["applied"] is False
    assert result["failed_reason"] == "reservation_already_released"


def test_tombstoned_reservation_cannot_be_released_again_after_restart_style_gap(tmp_path):
    store = _store(tmp_path)
    manager = _manager()
    assert _open(manager, store)["applied"] is True
    assert manager.guarded_release_reservation(state_store=store, **_release_kwargs())["applied"] is True

    restarted_manager = _manager()
    result = restarted_manager.guarded_release_reservation(
        state_store=store,
        **_release_kwargs(release_idempotency_key="reservation-001:terminal_mapping_proof:filled:proof-002"),
    )

    assert result["applied"] is False
    assert result["failed_reason"] == "reservation_already_released"


def test_store_succeeds_then_exposure_manager_fill_fails_returns_recovery_needed(tmp_path):
    store = _store(tmp_path)
    manager = _manager()
    assert _open(manager, store)["applied"] is True

    def fail_apply(*args, **kwargs):
        raise RuntimeError("forced mutation failure")

    manager.apply_fill_to_reservation = fail_apply
    result = manager.guarded_apply_fill_to_reservation(state_store=store, **_fill_kwargs())

    assert result["applied"] is False
    assert result["persistence_applied"] is True
    assert result["mutation_applied"] is False
    assert "fill_mutation_failed_recovery_needed" in result["failed_reason"]


def test_exposure_manager_succeeds_then_store_upsert_fails_reports_recovery_needed(tmp_path):
    inner = _store(tmp_path)
    manager = _manager()
    assert _open(manager, inner)["applied"] is True
    failing_store = FailingLedgerStore(inner, fail_upsert=True)

    result = manager.guarded_apply_fill_to_reservation(state_store=failing_store, **_fill_kwargs())

    assert result["applied"] is False
    assert result["persistence_applied"] is True
    assert result["mutation_applied"] is True
    assert result["failed_reason"] == "ledger_upsert_failed_recovery_needed"
    assert manager.reservations_for()[0].filled_qty == Decimal("0.25")


def test_open_ledger_upsert_failure_rolls_back_memory(tmp_path):
    inner = _store(tmp_path)
    manager = _manager()
    failing_store = FailingLedgerStore(inner, fail_upsert=True)

    result = _open(manager, failing_store)

    assert result["applied"] is False
    assert result["mutation_applied"] is True
    assert result["rollback_applied"] is True
    assert result["failed_reason"] == "ledger_upsert_failed_rollback_applied"
    assert manager.reservations_for() == []


def test_no_lifecycle_wiring_and_broker_adapter_inactive():
    import app.execution.engine as execution_engine_module
    import app.execution.order_router as order_router_module
    import app.main_loop as main_loop_module
    import app.telemetry.fill_recorder as fill_recorder_module

    metadata = exposure_authority_seam_metadata()
    assert metadata["status"] == EXPOSURE_AUTHORITY_STATUS
    assert metadata["live_wired"] is False
    assert metadata["active_veto_owner"] is False

    assert "guarded_open_reservation" not in inspect.getsource(execution_engine_module.ExecutionEngine)
    assert "guarded_apply_fill_to_reservation" not in inspect.getsource(fill_recorder_module)
    assert "guarded_release_reservation" not in inspect.getsource(order_router_module.OrderRouter)
    assert "ExposureManager" not in inspect.getsource(main_loop_module.create_main_loop)
    assert "broker_adapter" not in inspect.getsource(ExposureManager.guarded_open_reservation)
