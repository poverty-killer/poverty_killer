"""Diagnostic-only stall watchdog for runtime thread-dump capture."""

from __future__ import annotations

import faulthandler
import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

logger = logging.getLogger(__name__)

DEFAULT_STALL_WATCHDOG_SECONDS = 60.0
DEFAULT_STALL_WATCHDOG_PATH = Path("logs/runtime/stall_watchdog_traces.log")


def _truthy_env(value: str | None, *, default: bool = True) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() not in {"0", "false", "no", "off", "disabled"}


def _float_env(value: str | None, default: float) -> float:
    if value is None:
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if not result or result <= 0:
        return default
    return result


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class StallWatchdog:
    """
    Passive watchdog that dumps all Python thread stacks after a stalled phase.

    This class never interrupts, kills, retries, aborts, routes, or mutates a
    trading decision. It only emits diagnostic stack traces from a daemon timer.
    """

    def __init__(
        self,
        *,
        component: str,
        timeout_seconds: float = DEFAULT_STALL_WATCHDOG_SECONDS,
        path: str | Path = DEFAULT_STALL_WATCHDOG_PATH,
        enabled: bool = True,
    ) -> None:
        self.component = str(component or "runtime")
        self.timeout_seconds = float(timeout_seconds)
        self.path = Path(path)
        self.enabled = bool(enabled) and self.timeout_seconds > 0
        self._lock = threading.RLock()
        self._timer: Optional[threading.Timer] = None
        self._token = 0

    @classmethod
    def from_env(
        cls,
        *,
        component: str,
        default_timeout_seconds: float = DEFAULT_STALL_WATCHDOG_SECONDS,
        default_path: str | Path = DEFAULT_STALL_WATCHDOG_PATH,
    ) -> "StallWatchdog":
        return cls(
            component=component,
            timeout_seconds=_float_env(
                os.environ.get("POVERTY_KILLER_STALL_WATCHDOG_SECONDS"),
                default_timeout_seconds,
            ),
            path=os.environ.get("POVERTY_KILLER_STALL_WATCHDOG_PATH") or default_path,
            enabled=_truthy_env(os.environ.get("POVERTY_KILLER_STALL_WATCHDOG_ENABLED")),
        )

    def arm(self, label: str, *, metadata: Mapping[str, Any] | None = None) -> int:
        """Arm the watchdog and return a token that can cancel this arm only."""
        if not self.enabled:
            return 0
        with self._lock:
            self._cancel_locked()
            self._token += 1
            token = self._token
            timer = threading.Timer(
                self.timeout_seconds,
                self._fire,
                kwargs={
                    "token": token,
                    "label": str(label or "runtime_phase"),
                    "metadata": dict(metadata or {}),
                    "armed_at": _utc_now(),
                    "armed_monotonic": time.monotonic(),
                },
            )
            timer.daemon = True
            self._timer = timer
            timer.start()
            return token

    def cancel(self, token: int | None = None) -> None:
        """Cancel the current watchdog arm if the token still matches."""
        if not self.enabled:
            return
        with self._lock:
            if token is not None and token != self._token:
                return
            self._cancel_locked()
            self._token += 1

    def _cancel_locked(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _fire(
        self,
        *,
        token: int,
        label: str,
        metadata: Mapping[str, Any],
        armed_at: str,
        armed_monotonic: float,
    ) -> None:
        with self._lock:
            if token != self._token:
                return
            self._timer = None

        elapsed = max(0.0, time.monotonic() - float(armed_monotonic))
        header = {
            "event": "STALL_WATCHDOG_FIRED",
            "component": self.component,
            "label": label,
            "armed_at": armed_at,
            "fired_at": _utc_now(),
            "timeout_seconds": self.timeout_seconds,
            "elapsed_seconds": round(elapsed, 6),
            "metadata": dict(metadata),
            "diagnostic_only": True,
            "trading_control_flow_changed": False,
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write("\n=== POVERTY_KILLER STALL WATCHDOG FIRED ===\n")
                handle.write(json.dumps(header, sort_keys=True, default=str))
                handle.write("\n")
                faulthandler.dump_traceback(file=handle, all_threads=True)
                handle.flush()
        except Exception as exc:
            logger.warning("Stall watchdog file dump failed: %s", exc)

        try:
            sys.stderr.write("\n=== POVERTY_KILLER STALL WATCHDOG FIRED ===\n")
            sys.stderr.write(json.dumps(header, sort_keys=True, default=str))
            sys.stderr.write("\n")
            faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
            sys.stderr.flush()
        except Exception as exc:
            logger.warning("Stall watchdog stderr dump failed: %s", exc)
