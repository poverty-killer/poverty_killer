"""Persistent advisory World Awareness cache.

This cache keeps the existing in-memory API but mirrors advisory events to an
append-only JSONL file when configured. It never grants trade authority and
never stores secrets.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .feed_spine import ProviderRuntimeSnapshot, WorldAwarenessEventCache
from .models import ExternalIntelligenceEvent


@dataclass
class PersistentWorldAwarenessEventCache(WorldAwarenessEventCache):
    path: Path | None = None
    corrupt_line_count: int = 0
    last_error: str | None = None

    def __post_init__(self) -> None:
        if self.path is not None:
            self.path = Path(self.path)
            self._load()

    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    text = line.strip()
                    if not text:
                        continue
                    try:
                        row = json.loads(text)
                        payload = row.get("event") if row.get("record_type") == "event" else row
                        event = ExternalIntelligenceEvent.model_validate(payload)
                    except Exception:
                        self.corrupt_line_count += 1
                        continue
                    key = self.event_key(event)
                    self._events[key] = event
            while len(self._events) > self.max_events:
                self._events.popitem(last=False)
        except OSError as exc:
            self.last_error = type(exc).__name__

    def _append_event(self, event: ExternalIntelligenceEvent) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "record_type": "event",
            "event": event.model_dump(mode="json"),
        }
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, sort_keys=True, default=str, separators=(",", ":")))
            handle.write("\n")

    def upsert(self, events: Iterable[ExternalIntelligenceEvent]) -> tuple[int, int]:
        added = 0
        duplicates = 0
        for event in events:
            key = self.event_key(event)
            if key in self._events:
                duplicates += 1
                self.duplicate_event_ignored_count += 1
                continue
            self._events[key] = event
            self._append_event(event)
            added += 1
        while len(self._events) > self.max_events:
            self._events.popitem(last=False)
        return added, duplicates

    def mark_provider(self, snapshot: ProviderRuntimeSnapshot) -> None:
        super().mark_provider(snapshot)

    def status(self) -> dict[str, Any]:
        path = Path(self.path) if self.path is not None else None
        writable = False
        if path is not None:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                writable = path.parent.exists()
            except OSError:
                writable = False
        degraded = self.last_error is not None or self.corrupt_line_count > 0 or (path is not None and not writable)
        return {
            "cache_type": "jsonl_append_only" if path is not None else "memory_only",
            "path": str(path) if path is not None else None,
            "status": "DEGRADED" if degraded else "READY",
            "exists": path.exists() if path is not None else False,
            "parent_exists": path.parent.exists() if path is not None else False,
            "parent_writable": writable if path is not None else False,
            "event_count": len(self.events(limit=self.max_events)),
            "duplicate_event_ignored_count": self.duplicate_event_ignored_count,
            "corrupt_line_count": self.corrupt_line_count,
            "last_error": self.last_error,
            "secrets_values_exposed": False,
        }
