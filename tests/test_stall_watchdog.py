import time

from app.monitoring.stall_watchdog import StallWatchdog


def test_stall_watchdog_writes_thread_dump(tmp_path):
    path = tmp_path / "stall.log"
    watchdog = StallWatchdog(
        component="unit-test",
        timeout_seconds=0.05,
        path=path,
        enabled=True,
    )

    watchdog.arm("unit_phase", metadata={"symbol": "LINK/USD"})
    time.sleep(0.2)

    text = path.read_text(encoding="utf-8")
    assert "STALL WATCHDOG FIRED" in text
    assert "unit-test" in text
    assert "unit_phase" in text
    assert "LINK/USD" in text
    assert "trading_control_flow_changed" in text


def test_stall_watchdog_cancel_prevents_dump(tmp_path):
    path = tmp_path / "stall.log"
    watchdog = StallWatchdog(
        component="unit-test",
        timeout_seconds=0.2,
        path=path,
        enabled=True,
    )

    token = watchdog.arm("cancelled_phase")
    watchdog.cancel(token)
    time.sleep(0.35)

    assert not path.exists()
