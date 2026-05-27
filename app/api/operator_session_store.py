"""Persistent operator session metadata store.

The store uses append-only JSONL so it is easy to inspect, replace with a DB
later, and keep out of git as runtime state. It stores metadata and log paths,
not log contents and never secrets.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class OperatorSessionStore:
    path: Path
    max_sessions: int = 250
    corrupt_line_count: int = 0
    last_error: str | None = None
    _sessions: dict[str, dict[str, Any]] = field(default_factory=dict)
    _audit_events: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        self._load()

    def _load(self) -> None:
        self.corrupt_line_count = 0
        self.last_error = None
        if not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    text = line.strip()
                    if not text:
                        continue
                    try:
                        row = json.loads(text)
                    except json.JSONDecodeError:
                        self.corrupt_line_count += 1
                        continue
                    record_type = row.get("record_type")
                    if record_type == "session":
                        session = row.get("session") or {}
                        session_id = str(session.get("session_id") or "").strip()
                        if session_id:
                            self._sessions[session_id] = session
                    elif record_type == "audit_event":
                        event = row.get("event") or {}
                        if event:
                            self._audit_events.append(event)
        except OSError as exc:
            self.last_error = type(exc).__name__

    def _append(self, row: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, sort_keys=True, default=str, separators=(",", ":")))
            handle.write("\n")

    def write_session(self, session: dict[str, Any]) -> None:
        session_id = str(session.get("session_id") or "").strip()
        if not session_id:
            return
        row = {
            "record_type": "session",
            "recorded_at": utc_now_iso(),
            "session": dict(session),
        }
        self._sessions[session_id] = dict(session)
        self._append(row)
        self._trim_memory()

    def write_audit_event(self, event: dict[str, Any]) -> None:
        row = {
            "record_type": "audit_event",
            "recorded_at": utc_now_iso(),
            "event": dict(event),
        }
        self._audit_events.append(dict(event))
        self._append(row)

    def latest_session(self) -> dict[str, Any] | None:
        if not self._sessions:
            return None
        rows = list(self._sessions.values())
        rows.sort(key=lambda item: str(item.get("requested_at") or item.get("started_at") or ""), reverse=True)
        return dict(rows[0])

    def sessions(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        rows = [dict(row) for row in self._sessions.values()]
        rows.sort(key=lambda item: str(item.get("requested_at") or item.get("started_at") or ""), reverse=True)
        return rows[: max(int(limit), 0)] if limit is not None else rows

    def audit_events(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        rows = list(self._audit_events)
        return rows[-limit:] if limit else rows

    def _trim_memory(self) -> None:
        rows = self.sessions()
        keep_ids = {str(row.get("session_id")) for row in rows[: self.max_sessions]}
        self._sessions = {
            session_id: session
            for session_id, session in self._sessions.items()
            if session_id in keep_ids
        }

    def status(self) -> dict[str, Any]:
        writable = False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            writable = self.path.parent.exists()
        except OSError:
            writable = False
        degraded = self.last_error is not None or self.corrupt_line_count > 0 or not writable
        return {
            "store_type": "jsonl_append_only",
            "path": str(self.path),
            "status": "DEGRADED" if degraded else "READY",
            "exists": self.path.exists(),
            "parent_exists": self.path.parent.exists(),
            "parent_writable": writable,
            "session_count": len(self._sessions),
            "audit_event_count": len(self._audit_events),
            "corrupt_line_count": self.corrupt_line_count,
            "last_error": self.last_error,
            "secrets_values_exposed": False,
        }


def load_sessions(path: Path, *, max_sessions: int = 250) -> Iterable[dict[str, Any]]:
    return OperatorSessionStore(path=path, max_sessions=max_sessions).sessions()
