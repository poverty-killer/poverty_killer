"""Small in-process snapshot and timing helpers for the operator API.

The control lane must stay local and deterministic.  These helpers are
process-local by design; they are not trading authority and they do not store
raw payloads, secrets, or broker mutation state.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class SnapshotEntry:
    name: str
    payload: dict[str, Any]
    generated_at_utc: str
    ttl_seconds: float
    status: str
    reason_code: str | None
    elapsed_ms: float
    source: str

    def is_fresh(self, now_monotonic: float, generated_at_monotonic: float) -> bool:
        return (now_monotonic - generated_at_monotonic) <= self.ttl_seconds

    def to_dict(self, *, now_monotonic: float, generated_at_monotonic: float) -> dict[str, Any]:
        age_ms = round((now_monotonic - generated_at_monotonic) * 1000, 3)
        fresh = self.is_fresh(now_monotonic, generated_at_monotonic)
        return {
            "name": self.name,
            "generated_at_utc": self.generated_at_utc,
            "ttl_seconds": self.ttl_seconds,
            "status": self.status if fresh else "STALE",
            "reason_code": self.reason_code if fresh else "SNAPSHOT_STALE",
            "elapsed_ms": self.elapsed_ms,
            "source": self.source,
            "age_ms": age_ms,
            "fresh": fresh,
            "payload": deepcopy(self.payload),
        }


class OperatorSnapshotStore:
    """TTL snapshot cache for dashboard reads.

    This is intentionally minimal: requests can read a bounded snapshot instead
    of recomputing full dashboard state.  Start authority must still use the
    canonical control-state endpoint and must not trust stale broker data.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[SnapshotEntry, float]] = {}

    def set(
        self,
        name: str,
        payload: dict[str, Any],
        *,
        ttl_seconds: float,
        status: str = "FRESH",
        reason_code: str | None = None,
        elapsed_ms: float = 0.0,
        source: str = "OPERATOR_SNAPSHOT_STORE",
    ) -> dict[str, Any]:
        entry = SnapshotEntry(
            name=name,
            payload=deepcopy(payload),
            generated_at_utc=utc_now_iso(),
            ttl_seconds=float(ttl_seconds),
            status=status,
            reason_code=reason_code,
            elapsed_ms=round(float(elapsed_ms), 3),
            source=source,
        )
        generated_at_monotonic = time.monotonic()
        with self._lock:
            self._entries[name] = (entry, generated_at_monotonic)
        return entry.to_dict(now_monotonic=generated_at_monotonic, generated_at_monotonic=generated_at_monotonic)

    def get(self, name: str) -> dict[str, Any] | None:
        with self._lock:
            stored = self._entries.get(name)
        if not stored:
            return None
        entry, generated_at_monotonic = stored
        return entry.to_dict(now_monotonic=time.monotonic(), generated_at_monotonic=generated_at_monotonic)

    def get_or_refresh(
        self,
        name: str,
        refresh: Callable[[], dict[str, Any]],
        *,
        ttl_seconds: float,
        source: str,
    ) -> dict[str, Any]:
        current = self.get(name)
        if current and current.get("fresh") is True:
            return current
        started_ns = time.perf_counter_ns()
        try:
            payload = refresh()
        except Exception as exc:
            elapsed_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
            return self.set(
                name,
                {"error_class": exc.__class__.__name__},
                ttl_seconds=ttl_seconds,
                status="ERROR",
                reason_code=f"{name.upper()}_REFRESH_FAILED",
                elapsed_ms=elapsed_ms,
                source=source,
            )
        elapsed_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
        return self.set(name, payload, ttl_seconds=ttl_seconds, elapsed_ms=elapsed_ms, source=source)

    def summary(self) -> dict[str, Any]:
        with self._lock:
            names = sorted(self._entries)
        snapshots = {name: self.get(name) for name in names}
        return {
            "source": "OPERATOR_SNAPSHOT_STORE",
            "snapshot_count": len(names),
            "snapshots": snapshots,
            "secrets_values_exposed": False,
            "broker_mutation_occurred": False,
        }


class OperatorPerfRecorder:
    """Bounded request timing recorder for local operator diagnostics."""

    def __init__(self, *, max_events: int = 300) -> None:
        self._lock = threading.Lock()
        self._events: deque[dict[str, Any]] = deque(maxlen=max_events)
        self._in_flight = 0

    def begin(self) -> int:
        with self._lock:
            self._in_flight += 1
            return self._in_flight

    def finish(
        self,
        *,
        path: str,
        method: str,
        status_code: int,
        elapsed_ms: float,
        in_flight_count: int,
        error_marker: str | None = None,
    ) -> None:
        event = {
            "timestamp_utc": utc_now_iso(),
            "path": path,
            "method": method,
            "status_code": int(status_code),
            "elapsed_ms": round(float(elapsed_ms), 3),
            "in_flight_count": int(in_flight_count),
            "error_marker": error_marker,
            "secrets_values_exposed": False,
        }
        with self._lock:
            self._events.append(event)
            self._in_flight = max(0, self._in_flight - 1)

    def recent(self, *, limit: int = 100) -> dict[str, Any]:
        with self._lock:
            events = list(self._events)[-max(1, min(limit, self._events.maxlen or limit)) :]
            in_flight = self._in_flight
        by_path: dict[str, list[float]] = {}
        for event in events:
            by_path.setdefault(str(event["path"]), []).append(float(event["elapsed_ms"]))
        summaries = {}
        for path, values in by_path.items():
            sorted_values = sorted(values)
            count = len(sorted_values)
            p50_index = min(count - 1, int((count - 1) * 0.50))
            p95_index = min(count - 1, int((count - 1) * 0.95))
            summaries[path] = {
                "count": count,
                "p50_ms": round(sorted_values[p50_index], 3),
                "p95_ms": round(sorted_values[p95_index], 3),
                "max_ms": round(max(sorted_values), 3),
            }
        return {
            "source": "OPERATOR_PERF_RECORDER",
            "in_flight_count": in_flight,
            "event_count": len(events),
            "events": events,
            "path_summaries": summaries,
            "secrets_values_exposed": False,
        }
