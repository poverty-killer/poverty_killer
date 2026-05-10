from __future__ import annotations

from pathlib import Path
import json

from .config import PersistenceConfig
from .models import WorldAwarenessEvent


class WorldAwarenessRepository:
    """
    Simple pre-integration repository for subordinate world-awareness events.

    This repository intentionally stores external-context events without
    attaching them to live canonical consumers.
    """

    def __init__(self, config: PersistenceConfig):
        self.config = config
        self.root = Path(config.storage_root)

        if self.config.create_dirs_if_missing:
            self.root.mkdir(parents=True, exist_ok=True)

    @property
    def raw_event_store_path(self) -> Path:
        return self.root / self.config.raw_event_store_name

    @property
    def normalized_event_store_path(self) -> Path:
        return self.root / self.config.normalized_event_store_name

    @property
    def revision_store_path(self) -> Path:
        return self.root / self.config.revision_store_name

    def append_normalized_event(self, event: WorldAwarenessEvent) -> None:
        self._append_json_line(
            self.normalized_event_store_path,
            event.model_dump(mode="json"),
        )

    def append_raw_event(self, payload: dict) -> None:
        self._append_json_line(self.raw_event_store_path, payload)

    def append_revision_record(self, payload: dict) -> None:
        self._append_json_line(self.revision_store_path, payload)

    def load_normalized_events(self) -> list[dict]:
        return self._read_json_lines(self.normalized_event_store_path)

    def load_raw_events(self) -> list[dict]:
        return self._read_json_lines(self.raw_event_store_path)

    def load_revision_records(self) -> list[dict]:
        return self._read_json_lines(self.revision_store_path)

    def _append_json_line(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _read_json_lines(self, path: Path) -> list[dict]:
        if not path.exists():
            return []

        rows: list[dict] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                rows.append(json.loads(line))
        return rows
