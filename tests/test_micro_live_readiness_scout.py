from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

import main as runtime_main
from app.config import Config
from app.execution.order_router import OrderRouter
from app.risk.kill_switch import KillSwitch, KillSwitchState, KillSwitchType
from app.state.state_store import StateStore
from app.utils.time_utils import now_ns


def _source(path: str) -> str:
    return Path(path).read_text(encoding="utf-8-sig")


def test_default_runtime_gates_are_paper_first_and_live_reservation_blocked(tmp_path):
    config = Config()
    assert config.broker_mode == "paper"
    assert config.reservation_lifecycle_paper_enabled is False
    assert config.risk.kill_switch_enabled is True

    root = runtime_main.SovereignHeartbeat.__new__(runtime_main.SovereignHeartbeat)
    root.state_store = StateStore(str(tmp_path / "state.db"))
    root._bootstrap_reservation_lifecycle_disabled(
        SimpleNamespace(
            initial_capital=20_000.0,
            broker_mode="live",
            reservation_lifecycle_paper_enabled=True,
        )
    )

    assert root.reservation_lifecycle_enabled is False
    assert root.reservation_lifecycle_bootstrap_status["reservation_lifecycle_live_blocked"] is True
    assert root.reservation_lifecycle_bootstrap_status["reservation_lifecycle_scope"] == "disabled"


def test_live_private_api_call_fails_closed_without_credentials_or_paper_mode():
    paper_router = OrderRouter(paper_mode=True)
    paper_router._session.post = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("paper mode must not call a live endpoint")
    )
    assert paper_router._call_kraken_private("/private/Balance") is None

    live_router = OrderRouter(paper_mode=False, primary_api_key="", primary_api_secret="")
    live_router._session.post = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("missing credentials must not call a live endpoint")
    )
    assert live_router._call_kraken_private("/private/Balance") is None


def test_broker_adapter_and_live_broker_are_not_micro_live_implementations():
    broker_adapter = _source("app/execution/broker_adapter.py")
    assert "class BrokerAdapter(Protocol)" in broker_adapter
    assert "NO IMPLEMENTATION" in broker_adapter
    assert "requests" not in broker_adapter
    assert ".post(" not in broker_adapter
    assert ".delete(" not in broker_adapter

    live_broker = _source("app/execution/live_broker.py")
    assert "Under construction" in live_broker
    assert "submit_order" not in live_broker
    assert "cancel_order" not in live_broker
    assert "get_order_status" not in live_broker


def test_live_command_paths_require_durable_mapping_before_network(tmp_path):
    router = OrderRouter(
        primary_exchange="kraken",
        paper_mode=False,
        rest_fallback_enabled=False,
        state_store=StateStore(str(tmp_path / "state.db")),
    )
    router._websocket_connected = True
    calls = []
    router._session.post = lambda *args, **kwargs: calls.append((args, kwargs))

    assert router.cancel_order("missing-client-order") is False
    assert router.get_order_status("missing-client-order") == "unknown"
    assert router.get_order_status_evidence("missing-client-order")[
        "status_classification"
    ] == "mapping_missing_or_unsafe"
    assert calls == []


def test_live_status_evidence_is_read_only_but_active_status_path_mutates_mapping():
    status_evidence_src = inspect.getsource(OrderRouter.get_order_status_evidence)
    assert "_query_kraken_status_evidence" in status_evidence_src
    assert "_mark_active_order_mapping_terminal" not in status_evidence_src
    assert "cancel_order(" not in status_evidence_src
    assert "submit_order(" not in status_evidence_src

    active_status_src = inspect.getsource(OrderRouter._query_order_status)
    assert "_query_kraken_order_status" in active_status_src
    assert "_mark_active_order_mapping_terminal" in active_status_src


def test_kill_switch_is_persistent_operator_reset_gate_not_live_execution_authority():
    switch = KillSwitch()
    ts_ns = now_ns()
    assert switch.trigger(
        KillSwitchType.MANUAL,
        reason="micro live scout manual stop",
        timestamp_ns=ts_ns,
        requires_manual_reset=True,
    )
    assert switch.get_state() == KillSwitchState.MANUAL_RESET_REQUIRED
    assert switch.can_trade(ts_ns + 1) is False

    exported = switch.export_state()
    restored = KillSwitch()
    restored.import_state(exported, ts_ns + 2)
    assert restored.get_state() == KillSwitchState.MANUAL_RESET_REQUIRED
    assert restored.can_trade(ts_ns + 2) is False

    kill_source = inspect.getsource(KillSwitch)
    assert "submit_order(" not in kill_source
    assert "cancel_order(" not in kill_source
    assert "close_all_positions(" not in kill_source


def test_micro_live_no_go_conditions_are_current_repo_truth():
    router_source = _source("app/execution/order_router.py")
    assert "def _submit_order_kraken" in router_source
    assert "def _cancel_order_kraken" in router_source
    assert "def fetch_normalized_open_orders" in router_source
    assert "def fetch_fills" in router_source
    assert "def get_order_status_evidence" in router_source
    assert "active_cancel_status_mapping_ready\": False" in router_source
    assert "reservation_mapping_ready\": False" in router_source

    main_loop_source = _source("app/main_loop.py")
    assert "broker_mode == \"paper\"" in main_loop_source
    assert "paper-only gate" in main_loop_source
