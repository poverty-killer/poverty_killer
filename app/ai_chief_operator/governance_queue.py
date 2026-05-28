"""Append-only governance queue for advisory AI recommendations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.ai_chief_operator.models import AIRecommendation


class GovernanceQueue:
    def __init__(self, *, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._items: dict[str, dict[str, Any]] = {}
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
                    row = json.loads(text)
                    item = row.get("recommendation") or {}
                    rec_id = str(item.get("recommendation_id") or "")
                    if rec_id:
                        self._items[rec_id] = item
        except (OSError, json.JSONDecodeError):
            return

    def _append(self, recommendation: dict[str, Any]) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        row = {"record_type": "ai_recommendation", "recommendation": recommendation}
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, sort_keys=True, default=str, separators=(",", ":")))
            handle.write("\n")

    def add(self, recommendation: AIRecommendation | dict[str, Any]) -> dict[str, Any]:
        item = recommendation.to_dict() if isinstance(recommendation, AIRecommendation) else dict(recommendation)
        item["can_execute"] = False
        item["requires_shan_approval"] = True
        rec_id = str(item.get("recommendation_id") or "")
        if not rec_id:
            return item
        self._items[rec_id] = item
        self._append(item)
        return item

    def list(self) -> list[dict[str, Any]]:
        rows = list(self._items.values())
        rows.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        return [dict(row) for row in rows]

    def get(self, recommendation_id: str) -> dict[str, Any] | None:
        item = self._items.get(str(recommendation_id))
        return dict(item) if item else None

    def approve_paper_research(self, recommendation_id: str) -> dict[str, Any]:
        item = self._items.get(str(recommendation_id))
        if not item:
            return {
                "status": "REJECTED",
                "reason_code": "RECOMMENDATION_NOT_FOUND",
                "paper_started": False,
                "broker_call_occurred": False,
                "trading_mutation_occurred": False,
            }
        item = dict(item)
        item["status"] = "APPROVED_FOR_PAPER_RESEARCH"
        item["can_execute"] = False
        item["requires_shan_approval"] = True
        self._items[str(recommendation_id)] = item
        self._append(item)
        return {
            "status": item["status"],
            "recommendation": dict(item),
            "paper_started": False,
            "broker_call_occurred": False,
            "trading_mutation_occurred": False,
            "live_enabled": False,
            "real_money_enabled": False,
            "reason_code": "APPROVED_FOR_RESEARCH_ONLY_NO_RUNTIME_STARTED",
        }

    def reject(self, recommendation_id: str, reason: str | None = None) -> dict[str, Any]:
        item = self._items.get(str(recommendation_id))
        if not item:
            return {"status": "REJECTED", "reason_code": "RECOMMENDATION_NOT_FOUND"}
        item = dict(item)
        item["status"] = "REJECTED"
        item["refusal_reason"] = reason or "REJECTED_BY_OPERATOR"
        item["can_execute"] = False
        self._items[str(recommendation_id)] = item
        self._append(item)
        return {
            "status": "REJECTED",
            "recommendation": dict(item),
            "broker_call_occurred": False,
            "trading_mutation_occurred": False,
        }
