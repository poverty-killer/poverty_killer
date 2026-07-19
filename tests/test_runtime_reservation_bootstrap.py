import inspect
from types import SimpleNamespace

import main as runtime_main
from app.config import Config
from app.execution.engine import ExecutionEngine
from app.execution.order_router import OrderRouter
from app.main_loop import MainLoop
from app.risk.exposure_manager import ExposureManager
from app.risk.reservation_lifecycle_coordinator import ReservationLifecycleCoordinator
from app.state.state_store import StateStore
from app.telemetry.fill_recorder import FillRecorder


def _store(tmp_path):
    return StateStore(str(tmp_path / "state.db"))


def _config(**overrides):
    data = {
        "initial_capital": 20_000.0,
        "broker_mode": "paper",
        "reservation_lifecycle_paper_enabled": False,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _root_with_store(store):
    root = runtime_main.SovereignHeartbeat.__new__(runtime_main.SovereignHeartbeat)
    root.state_store = store
    return root


def _reservation_row(
    *,
    reservation_id="reservation-001",
    client_order_id="client-order-001",
    decision_uuid="decision-001",
    dedupe_key="decision-001:client-order-001",
    price_basis="2500.00",
    status="ACKNOWLEDGED",
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
        "original_qty": "1.0",
        "open_qty": "1.0" if is_active else "0",
        "filled_qty": "0",
        "cancelled_qty": "0",
        "price_basis": price_basis,
        "notional_basis": "2500.00" if price_basis is not None else None,
        "status": status,
        "confidence_weight": "1.00",
        "created_at_ns": 1_700_000_000_000_000_000,
        "updated_at_ns": 1_700_000_000_000_000_100,
        "terminal_status": terminal_status,
        "terminal_reason": terminal_status,
        "terminal_source": "test" if terminal_status else None,
        "source_lifecycle_phase": "bootstrap_test",
        "source_idempotency_key": dedupe_key,
        "is_active": is_active,
        "is_terminal": is_terminal,
    }


def _release_tombstone():
    return {
        "release_idempotency_key": "reservation-001:terminal_mapping_proof:filled:proof-001",
        "reservation_id": "reservation-001",
        "client_order_id": "client-order-001",
        "decision_uuid": "decision-001",
        "reservation_dedupe_key": "decision-001:client-order-001",
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


def _fill_progress():
    return {
        "fill_idempotency_key": "paper-fill-001",
        "reservation_id": "reservation-001",
        "client_order_id": "client-order-001",
        "cumulative_filled_qty": "0.25",
        "fill_delta_qty": "0.25",
        "status_source": "paper_broker.execution_report",
        "source_event_id": "paper-report-001",
        "applied_at_ns": 1_700_000_000_000_000_150,
    }


def test_root_bootstrap_creates_exposure_manager_and_disabled_coordinator(tmp_path):
    store = _store(tmp_path)
    root = _root_with_store(store)

    root._bootstrap_reservation_lifecycle_disabled(_config())

    assert isinstance(root.exposure_manager, ExposureManager)
    assert isinstance(root.reservation_lifecycle_coordinator, ReservationLifecycleCoordinator)
    assert root.reservation_lifecycle_enabled is False
    assert root.reservation_lifecycle_bootstrap_status["exposure_manager_created"] is True
    assert root.reservation_lifecycle_bootstrap_status["coordinator_created"] is True
    assert root.reservation_lifecycle_bootstrap_status["reservation_lifecycle_paper_requested"] is False
    assert root.reservation_lifecycle_bootstrap_status["reservation_lifecycle_enabled"] is False
    assert root.reservation_lifecycle_bootstrap_status["reservation_lifecycle_scope"] == "disabled"
    assert root.reservation_lifecycle_bootstrap_status["reservation_lifecycle_live_blocked"] is False
    assert root.reservation_lifecycle_bootstrap_status["portfolio_risk_gate_paper_enabled"] is False
    assert root.reservation_lifecycle_bootstrap_status["portfolio_risk_gate_policy_version"] == "P3B_B1_V1"


def test_config_default_reservation_lifecycle_paper_enabled_false():
    config = Config()

    assert config.reservation_lifecycle_paper_enabled is False
    assert config.portfolio_risk_gate_paper_enabled is True
    assert config.portfolio_risk_gate_policy_version == "P3B_B1_V1"


def test_paper_requested_enables_effective_reservation_lifecycle(tmp_path):
    store = _store(tmp_path)
    root = _root_with_store(store)

    root._bootstrap_reservation_lifecycle_disabled(
        _config(reservation_lifecycle_paper_enabled=True)
    )

    assert root.reservation_lifecycle_enabled is True
    assert root.reservation_lifecycle_bootstrap_status["reservation_lifecycle_paper_requested"] is True
    assert root.reservation_lifecycle_bootstrap_status["reservation_lifecycle_enabled"] is True
    assert root.reservation_lifecycle_bootstrap_status["reservation_lifecycle_scope"] == "paper"
    assert root.reservation_lifecycle_bootstrap_status["reservation_lifecycle_live_blocked"] is False


def test_portfolio_risk_gate_paper_enables_effective_reservation_lifecycle(tmp_path):
    store = _store(tmp_path)
    root = _root_with_store(store)

    root._bootstrap_reservation_lifecycle_disabled(
        _config(portfolio_risk_gate_paper_enabled=True)
    )

    assert root.reservation_lifecycle_enabled is True
    assert root.reservation_lifecycle_bootstrap_status["reservation_lifecycle_paper_requested"] is True
    assert root.reservation_lifecycle_bootstrap_status["reservation_lifecycle_enabled"] is True
    assert root.reservation_lifecycle_bootstrap_status["reservation_lifecycle_scope"] == "paper"
    assert root.reservation_lifecycle_bootstrap_status["portfolio_risk_gate_paper_enabled"] is True
    assert root.reservation_lifecycle_bootstrap_status["portfolio_risk_gate_policy_version"] == "P3B_B1_V1"


def test_external_paper_bootstrap_requires_complete_broker_inventory_before_admission(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv(
        runtime_main.EXECUTION_BROKER_ENV_VAR,
        runtime_main.ALPACA_PAPER_EXECUTION_BROKER,
    )
    root = _root_with_store(_store(tmp_path))

    root._bootstrap_reservation_lifecycle_disabled(
        _config(portfolio_risk_gate_paper_enabled=True)
    )

    assert root.reservation_lifecycle_enabled is True
    assert root._broker_inventory_reconciliation_required is True
    assert root.exposure_manager.broker_inventory_authority_evidence("BTCUSD") == {
        "source": "ExposureManager",
        "authority_class": "PORTFOLIO_RISK",
        "snapshot_id": None,
        "account_suffix": None,
        "broker_cash_available": None,
        "broker_inventory_required": True,
        "broker_inventory_reconciled": False,
        "reason_codes": (),
        "realized_pnl_basis": "NOT_APPLICABLE",
        "fee_truth_status": "NOT_ESTABLISHED",
        "fee_truth_complete": False,
        "net_realized_pnl_claimed": False,
        "symbol": "BTCUSD",
        "broker_mutation_occurred": False,
        "known_attribution": False,
        "lot_tracking_available": False,
        "authorized": False,
        "reason_code": "BROKER_INVENTORY_RECONCILIATION_REQUIRED",
    }
    assert root.reservation_lifecycle_bootstrap_status["broker_command_performed"] is False


def test_live_requested_keeps_effective_reservation_lifecycle_disabled(tmp_path):
    store = _store(tmp_path)
    root = _root_with_store(store)

    root._bootstrap_reservation_lifecycle_disabled(
        _config(broker_mode="live", reservation_lifecycle_paper_enabled=True)
    )

    assert root.reservation_lifecycle_enabled is False
    assert root.reservation_lifecycle_bootstrap_status["reservation_lifecycle_paper_requested"] is True
    assert root.reservation_lifecycle_bootstrap_status["reservation_lifecycle_enabled"] is False
    assert root.reservation_lifecycle_bootstrap_status["reservation_lifecycle_scope"] == "disabled"
    assert root.reservation_lifecycle_bootstrap_status["reservation_lifecycle_live_blocked"] is True


def test_open_active_ledger_rows_hydrate_into_exposure_manager(tmp_path):
    store = _store(tmp_path)
    assert store.upsert_reservation_ledger(_reservation_row()) is True
    root = _root_with_store(store)

    root._bootstrap_reservation_lifecycle_disabled(_config())

    assert root.reservation_lifecycle_bootstrap_status["hydrated_reservation_count"] == 1
    assert [item.reservation_id for item in root.exposure_manager.reservations_for()] == ["reservation-001"]


def test_tombstoned_rows_do_not_hydrate_active_reservations(tmp_path):
    store = _store(tmp_path)
    assert store.upsert_reservation_ledger(_reservation_row()) is True
    assert store.record_reservation_release_tombstone(_release_tombstone()) is True
    root = _root_with_store(store)

    root._bootstrap_reservation_lifecycle_disabled(_config())

    assert root.reservation_lifecycle_bootstrap_status["release_tombstone_count"] == 1
    assert root.reservation_lifecycle_bootstrap_status["skipped_reservation_count"] == 1
    assert root.exposure_manager.reservations_for() == []


def test_bootstrap_recovers_fill_progress_ahead_of_active_ledger(tmp_path):
    store = _store(tmp_path)
    assert store.upsert_reservation_ledger(_reservation_row()) is True
    assert store.record_reservation_fill_progress(_fill_progress()) is True
    root = _root_with_store(store)

    root._bootstrap_reservation_lifecycle_disabled(_config())

    assert root.reservation_lifecycle_enabled is False
    assert root.reservation_lifecycle_bootstrap_status["fill_progress_row_count"] == 1
    assert root.reservation_lifecycle_bootstrap_status["hydrated_reservation_count"] == 1
    restored = root.exposure_manager.reservations_for()[0]
    assert str(restored.filled_qty) == "0.25"
    assert str(restored.open_qty) == "0.75"


def test_terminal_rows_do_not_hydrate_active_reservations(tmp_path):
    store = _store(tmp_path)
    assert store.upsert_reservation_ledger(
        _reservation_row(
            status="FILLED",
            is_active=False,
            is_terminal=True,
            terminal_status="FILLED",
        )
    ) is True
    root = _root_with_store(store)

    root._bootstrap_reservation_lifecycle_disabled(_config())

    assert root.reservation_lifecycle_bootstrap_status["active_ledger_row_count"] == 0
    assert root.exposure_manager.reservations_for() == []


def test_missing_or_non_positive_price_basis_rows_do_not_hydrate(tmp_path):
    store = _store(tmp_path)
    assert store.upsert_reservation_ledger(
        _reservation_row(reservation_id="missing-price", price_basis=None)
    ) is True
    assert store.upsert_reservation_ledger(
        _reservation_row(
            reservation_id="zero-price",
            client_order_id="client-order-002",
            decision_uuid="decision-002",
            dedupe_key="decision-002:client-order-002",
            price_basis="0",
        )
    ) is True
    root = _root_with_store(store)

    root._bootstrap_reservation_lifecycle_disabled(_config())

    assert root.reservation_lifecycle_bootstrap_status["hydrated_reservation_count"] == 0
    assert root.reservation_lifecycle_bootstrap_status["skipped_reservation_count"] == 2
    assert root.exposure_manager.reservations_for() == []


def test_hydrate_failure_keeps_coordinator_disabled_and_fail_closed(monkeypatch):
    class FailingExposureManager:
        guarded_open_called = False
        guarded_fill_called = False
        guarded_release_called = False

        def __init__(self, initial_equity, **_kwargs):
            self.initial_equity = initial_equity

        def hydrate_reservations_from_ledger(self, rows, *, release_tombstones=None, fill_progress=None):
            raise RuntimeError("forced hydrate failure")

        def guarded_open_reservation(self, *args, **kwargs):
            self.guarded_open_called = True

        def guarded_apply_fill_to_reservation(self, *args, **kwargs):
            self.guarded_fill_called = True

        def guarded_release_reservation(self, *args, **kwargs):
            self.guarded_release_called = True

    class EmptyStore:
        def list_reservation_ledger(self, **kwargs):
            return []

        def get_reservation_release_tombstone(self, **kwargs):
            return None

    monkeypatch.setattr(runtime_main, "ExposureManager", FailingExposureManager)
    root = _root_with_store(EmptyStore())

    root._bootstrap_reservation_lifecycle_disabled(_config())

    assert root.reservation_lifecycle_enabled is False
    assert root.reservation_lifecycle_bootstrap_status["hydrate_failed"] is True
    assert "forced hydrate failure" in root.reservation_lifecycle_bootstrap_status["failed_reason"]
    assert root.reservation_lifecycle_coordinator is not None
    assert root.exposure_manager.guarded_open_called is False
    assert root.exposure_manager.guarded_fill_called is False
    assert root.exposure_manager.guarded_release_called is False


def test_bootstrap_passes_disabled_coordinator_only_to_order_router():
    heartbeat_init = inspect.getsource(runtime_main.SovereignHeartbeat.__init__)
    order_router_init = inspect.signature(OrderRouter.__init__)
    execution_engine_init = inspect.signature(ExecutionEngine.__init__)
    main_loop_init = inspect.signature(MainLoop.__init__)
    fill_recorder_init = inspect.signature(FillRecorder.__init__)

    assert "self._bootstrap_reservation_lifecycle_disabled(config)" in heartbeat_init
    assert "reservation_lifecycle_coordinator=self.reservation_lifecycle_coordinator" in heartbeat_init
    assert "reservation_lifecycle_enabled=self.reservation_lifecycle_enabled" in heartbeat_init
    assert "broker_inventory_reconciliation_required=self._broker_inventory_reconciliation_required" in heartbeat_init
    assert "self.order_router.reconcile_startup_broker_inventory()" in heartbeat_init
    assert "exposure_manager=self.exposure_manager" in heartbeat_init
    assert "reservation_lifecycle_coordinator" in order_router_init.parameters
    assert "reservation_lifecycle_enabled" in order_router_init.parameters
    assert "broker_inventory_reconciliation_required" in order_router_init.parameters
    assert "reservation_lifecycle_coordinator" not in execution_engine_init.parameters
    assert "reservation_lifecycle_coordinator" not in main_loop_init.parameters
    assert "exposure_manager" in main_loop_init.parameters
    assert "reservation_lifecycle_coordinator" not in fill_recorder_init.parameters


def test_bootstrap_uses_no_broker_command_or_telemetry_authority():
    source = inspect.getsource(runtime_main.SovereignHeartbeat._bootstrap_reservation_lifecycle_disabled)

    assert "submit_order(" not in source
    assert "cancel_order(" not in source
    assert "record_event(" not in source
    assert "guarded_open_reservation(" not in source
    assert "guarded_apply_fill_to_reservation(" not in source
    assert "guarded_release_reservation(" not in source
    assert "telemetry_authority_used" in source
    assert "broker_command_performed" in source


def test_broker_adapter_remains_untouched_and_inactive():
    source = inspect.getsource(runtime_main)

    assert "broker_adapter" not in source
