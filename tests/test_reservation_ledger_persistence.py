import inspect

from app.state.state_store import StateStore


def _store(tmp_path):
    return StateStore(str(tmp_path / "state.db"))


def _reservation_row(
    reservation_id="reservation-001",
    client_order_id="client-order-001",
    decision_uuid="decision-001",
    dedupe_key="decision-001:client-order-001",
    *,
    price_basis="2500.00",
    notional_basis="2500.00",
    status="CREATED",
    open_qty="1.0",
    filled_qty="0",
    cancelled_qty="0",
    is_active=True,
    is_terminal=False,
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
        "original_qty": "1.0",
        "open_qty": open_qty,
        "filled_qty": filled_qty,
        "cancelled_qty": cancelled_qty,
        "price_basis": price_basis,
        "notional_basis": notional_basis,
        "status": status,
        "confidence_weight": "0.40",
        "created_at_ns": 1_700_000_000_000_000_000,
        "updated_at_ns": 1_700_000_000_000_000_001,
        "terminal_status": None,
        "terminal_reason": None,
        "terminal_source": None,
        "source_lifecycle_phase": "order_submitted",
        "source_idempotency_key": "decision-001:client-order-001:order_submitted",
        "is_active": is_active,
        "is_terminal": is_terminal,
    }


def _release_tombstone(
    reservation_id="reservation-001",
    client_order_id="client-order-001",
    decision_uuid="decision-001",
    dedupe_key="decision-001:client-order-001",
    release_key="reservation-001:terminal_mapping_proof:filled:proof-001",
):
    return {
        "release_idempotency_key": release_key,
        "reservation_id": reservation_id,
        "client_order_id": client_order_id,
        "decision_uuid": decision_uuid,
        "reservation_dedupe_key": dedupe_key,
        "release_reason": "terminal_mapping_proof",
        "terminal_status": "filled",
        "terminal_source": "mark_terminal_from_status_evidence",
        "released_qty": "1.0",
        "released_notional": "2500.00",
        "released_at_ns": 1_700_000_000_000_000_050,
        "source_event_id": "proof-001",
        "exposure_release_scope": "reservation_only",
    }


def test_create_update_get_and_list_reservation_ledger_row(tmp_path):
    store = _store(tmp_path)
    row = _reservation_row()

    assert store.upsert_reservation_ledger(row) is True
    persisted = store.get_reservation_ledger("reservation-001")
    assert persisted["reservation_id"] == "reservation-001"
    assert persisted["reservation_dedupe_key"] == "decision-001:client-order-001"
    assert persisted["price_basis"] == "2500.00"
    assert persisted["notional_basis"] == "2500.00"
    assert persisted["is_active"] is True
    assert persisted["is_terminal"] is False

    updated = dict(row)
    updated["open_qty"] = "0.75"
    updated["filled_qty"] = "0.25"
    updated["status"] = "PARTIALLY_FILLED"
    updated["updated_at_ns"] = 1_700_000_000_000_000_100
    assert store.upsert_reservation_ledger(updated) is True

    persisted = store.get_reservation_ledger("reservation-001")
    assert persisted["open_qty"] == "0.75"
    assert persisted["filled_qty"] == "0.25"
    assert persisted["status"] == "PARTIALLY_FILLED"
    active = store.list_reservation_ledger(active_only=True, include_terminal=False)
    assert [item["reservation_id"] for item in active] == ["reservation-001"]


def test_unique_active_dedupe_prevents_duplicate_open_reservation(tmp_path):
    store = _store(tmp_path)
    first = _reservation_row(reservation_id="reservation-a")
    duplicate = _reservation_row(
        reservation_id="reservation-b",
        client_order_id="client-order-b",
        dedupe_key=first["reservation_dedupe_key"],
    )

    assert store.upsert_reservation_ledger(first) is True
    assert store.upsert_reservation_ledger(duplicate) is False
    active = store.list_reservation_ledger(active_only=True)
    assert [item["reservation_id"] for item in active] == ["reservation-a"]


def test_partial_fill_idempotency_prevents_duplicate_or_non_advancing_progress(tmp_path):
    store = _store(tmp_path)
    assert store.upsert_reservation_ledger(_reservation_row()) is True

    first = {
        "fill_idempotency_key": "venue-fill-001",
        "reservation_id": "reservation-001",
        "client_order_id": "client-order-001",
        "cumulative_filled_qty": "0.25",
        "fill_delta_qty": "0.25",
        "status_source": "paper_broker.execution_report",
        "source_event_id": "paper_report_1",
        "applied_at_ns": 1_700_000_000_000_000_010,
    }
    assert store.record_reservation_fill_progress(first) is True
    assert store.record_reservation_fill_progress(first) is True

    non_advancing = dict(first)
    non_advancing["fill_idempotency_key"] = "venue-fill-002"
    non_advancing["source_event_id"] = "paper_report_2"
    assert store.record_reservation_fill_progress(non_advancing) is False

    advancing = dict(first)
    advancing["fill_idempotency_key"] = "venue-fill-003"
    advancing["cumulative_filled_qty"] = "0.50"
    advancing["fill_delta_qty"] = "0.25"
    advancing["source_event_id"] = "paper_report_3"
    assert store.record_reservation_fill_progress(advancing) is True

    progress = store.list_reservation_fill_progress("reservation-001")
    assert [item["fill_idempotency_key"] for item in progress] == [
        "venue-fill-001",
        "venue-fill-003",
    ]


def test_release_tombstone_is_idempotent_and_release_once(tmp_path):
    store = _store(tmp_path)
    assert store.upsert_reservation_ledger(_reservation_row()) is True
    tombstone = _release_tombstone()

    assert store.record_reservation_release_tombstone(tombstone) is True
    assert store.record_reservation_release_tombstone(tombstone) is True
    stored = store.get_reservation_release_tombstone(reservation_id="reservation-001")
    assert stored["release_idempotency_key"] == tombstone["release_idempotency_key"]
    assert stored["release_applied"] is True
    assert stored["exposure_release_scope"] == "reservation_only"

    conflicting = dict(tombstone)
    conflicting["release_idempotency_key"] = "reservation-001:terminal_mapping_proof:filled:proof-002"
    assert store.record_reservation_release_tombstone(conflicting) is False


def test_released_reservation_cannot_reopen_under_same_dedupe_key(tmp_path):
    store = _store(tmp_path)
    tombstone = _release_tombstone()
    assert store.record_reservation_release_tombstone(tombstone) is True

    assert store.upsert_reservation_ledger(_reservation_row()) is False
    assert store.get_reservation_ledger("reservation-001") is None


def test_restart_readback_restores_open_reservations_and_tombstones(tmp_path):
    db_path = tmp_path / "state.db"
    first = StateStore(str(db_path))
    assert first.upsert_reservation_ledger(_reservation_row(reservation_id="open-reservation")) is True
    assert first.record_reservation_release_tombstone(
        _release_tombstone(reservation_id="closed-reservation", release_key="closed-release-key")
    ) is True
    first.close()

    restarted = StateStore(str(db_path))
    open_rows = restarted.list_reservation_ledger(active_only=True, include_terminal=False)
    assert [row["reservation_id"] for row in open_rows] == ["open-reservation"]
    tombstone = restarted.get_reservation_release_tombstone(reservation_id="closed-reservation")
    assert tombstone["release_idempotency_key"] == "closed-release-key"


def test_terminal_release_key_cannot_release_twice(tmp_path):
    store = _store(tmp_path)
    assert store.upsert_reservation_ledger(_reservation_row()) is True
    first = _release_tombstone(release_key="reservation-001:terminal_mapping_proof:filled:proof-001")
    second = _release_tombstone(release_key="reservation-001:terminal_mapping_proof:filled:proof-002")

    assert store.record_reservation_release_tombstone(first) is True
    assert store.record_reservation_release_tombstone(second) is False


def test_market_order_missing_price_basis_is_stored_unresolved_passive(tmp_path):
    store = _store(tmp_path)
    unresolved = _reservation_row(
        reservation_id="market-unresolved",
        client_order_id="market-client-001",
        decision_uuid="market-decision-001",
        dedupe_key="market-decision-001:market-client-001",
        price_basis=None,
        notional_basis=None,
        status="UNRESOLVED_PRICE_BASIS",
        is_active=False,
    )
    unresolved["order_type"] = "market"

    assert store.upsert_reservation_ledger(unresolved) is True
    persisted = store.get_reservation_ledger("market-unresolved")
    assert persisted["order_type"] == "market"
    assert persisted["price_basis"] is None
    assert persisted["notional_basis"] is None
    assert persisted["status"] == "UNRESOLVED_PRICE_BASIS"
    assert persisted["is_active"] is False


def test_state_store_reservation_persistence_does_not_activate_authority_or_broker_adapter():
    source = inspect.getsource(StateStore)
    assert "ExposureManager" not in source
    assert "reserve_intent" not in source
    assert "release_reservation" not in source
    assert "apply_fill_to_reservation" not in source
    assert "broker_adapter" not in source
