from __future__ import annotations

import threading

from main import SovereignHeartbeat


class _StopRecorder:
    def __init__(self) -> None:
        self.stop_calls = 0
        self.close_calls = 0

    def stop(self) -> None:
        self.stop_calls += 1

    def close(self) -> None:
        self.close_calls += 1

    def get_oms_shutdown_accounting(self) -> dict:
        return {"test": "accounting"}


class _RouterRecorder:
    def __init__(self) -> None:
        self.close_all_positions_calls = 0

    def close_all_positions(self) -> bool:
        self.close_all_positions_calls += 1
        return True


def _runtime_shell() -> tuple[SovereignHeartbeat, _RouterRecorder, _StopRecorder, _StopRecorder, _StopRecorder]:
    runtime = object.__new__(SovereignHeartbeat)
    router = _RouterRecorder()
    main_loop = _StopRecorder()
    execution_engine = _StopRecorder()
    state_store = _StopRecorder()
    runtime._running = True
    runtime._stopping = False
    runtime._shutdown_complete = False
    runtime._shutdown_reason_code = None
    runtime._broker_flatten_performed_on_shutdown = False
    runtime._threads = []
    runtime._stop_event = threading.Event()
    runtime.order_router = router
    runtime.main_loop = main_loop
    runtime.execution_engine = execution_engine
    runtime.state_store = state_store
    return runtime, router, main_loop, execution_engine, state_store


def test_signal_shutdown_preserves_broker_positions_and_flushes_runtime():
    runtime, router, main_loop, execution_engine, state_store = _runtime_shell()

    runtime._handle_termination_signal(2)

    assert runtime._shutdown_reason_code == "SIGNAL_2_NO_FLATTEN"
    assert runtime._shutdown_complete is True
    assert runtime._stop_event.is_set() is True
    assert main_loop.stop_calls == 1
    assert execution_engine.stop_calls == 1
    assert state_store.close_calls == 1
    assert router.close_all_positions_calls == 0
    assert runtime._broker_flatten_performed_on_shutdown is False


def test_operator_stop_path_does_not_flatten_or_liquidate_positions():
    runtime, router, main_loop, execution_engine, state_store = _runtime_shell()

    runtime.stop(reason_code="SUPERVISOR_STOP_NO_FLATTEN")

    assert runtime._shutdown_reason_code == "SUPERVISOR_STOP_NO_FLATTEN"
    assert main_loop.stop_calls == 1
    assert execution_engine.stop_calls == 1
    assert state_store.close_calls == 1
    assert router.close_all_positions_calls == 0


def test_bounded_expiry_records_no_flatten_reason_without_broker_command():
    runtime, router, _main_loop, _execution_engine, _state_store = _runtime_shell()
    runtime.bounded_duration_seconds = 0.01

    runtime._start_bounded_duration_timer()
    for thread in runtime._threads:
        thread.join(timeout=1.0)

    assert runtime._shutdown_reason_code == "BOUNDED_DURATION_EXPIRED_NO_FLATTEN"
    assert runtime._running is False
    assert runtime._stop_event.is_set() is True
    assert router.close_all_positions_calls == 0
