"""Advisory research registry contracts."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


RESEARCH_STATUSES = {
    "DRAFT",
    "NEEDS_REVIEW",
    "APPROVED_FOR_PAPER_RESEARCH",
    "RUNNING_PAPER",
    "COMPLETED",
    "REJECTED",
    "EXPIRED",
}

PROMOTION_STAGES = {
    "IDEA",
    "OFFLINE_RESEARCH",
    "BACKTEST_REVIEW",
    "REPLAY_REVIEW",
    "BOUNDED_PAPER",
    "LONGER_PAPER",
    "LIVE_REQUIRES_SEPARATE_APPROVAL",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def research_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return [str(value)]


@dataclass
class EvidenceLink:
    evidence_id: str
    evidence_type: str
    summary: str
    source: str = "operator_research"
    truth_label: str = "advisory"
    path: str | None = None
    run_id: str | None = None
    broker_confirmed: bool = False
    raw_logs_included: bool = False
    secrets_values_exposed: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["raw_logs_included"] = False
        payload["secrets_values_exposed"] = False
        return payload


@dataclass
class PromotionGate:
    gate_id: str
    stage: str
    required_evidence: list[str]
    current_status: str = "NEEDS_REVIEW"
    blocks_promotion: bool = True
    live_requires_separate_approval: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["can_execute"] = False
        return payload


@dataclass
class ResearchHypothesis:
    id: str
    title: str
    thesis: str
    symbols_assets: list[str] = field(default_factory=list)
    strategy_area: str = "UNKNOWN"
    expected_edge: str = "UNKNOWN_UNPROVEN"
    evidence_required: list[str] = field(default_factory=list)
    current_evidence: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    status: str = "NEEDS_REVIEW"
    promotion_stage: str = "IDEA"
    can_execute: bool = False
    requires_shan_approval: bool = True
    created_at: str = field(default_factory=utc_now_iso)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ResearchHypothesis":
        status = str(payload.get("status") or "NEEDS_REVIEW").upper()
        stage = str(payload.get("promotion_stage") or "IDEA").upper()
        if status not in RESEARCH_STATUSES:
            status = "NEEDS_REVIEW"
        if stage not in PROMOTION_STAGES:
            stage = "IDEA"
        return cls(
            id=str(payload.get("id") or research_id("hyp")),
            title=str(payload.get("title") or "Untitled research hypothesis"),
            thesis=str(payload.get("thesis") or "No thesis supplied."),
            symbols_assets=_string_list(payload.get("symbols_assets") or payload.get("symbols")),
            strategy_area=str(payload.get("strategy_area") or "UNKNOWN"),
            expected_edge=str(payload.get("expected_edge") or "UNKNOWN_UNPROVEN"),
            evidence_required=_string_list(payload.get("evidence_required")),
            current_evidence=_string_list(payload.get("current_evidence")),
            risks=_string_list(payload.get("risks")),
            status=status,
            promotion_stage=stage,
            can_execute=False,
            requires_shan_approval=True,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["can_execute"] = False
        payload["requires_shan_approval"] = True
        return payload


@dataclass
class ResearchExperiment:
    id: str
    title: str
    thesis: str
    symbols_assets: list[str] = field(default_factory=list)
    strategy_area: str = "UNKNOWN"
    expected_edge: str = "UNKNOWN_UNPROVEN"
    evidence_required: list[str] = field(default_factory=list)
    current_evidence: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    status: str = "NEEDS_REVIEW"
    promotion_stage: str = "OFFLINE_RESEARCH"
    linked_hypothesis_id: str | None = None
    paper_duration_seconds: int | None = None
    can_execute: bool = False
    requires_shan_approval: bool = True
    paper_started: bool = False
    broker_call_occurred: bool = False
    trading_mutation_occurred: bool = False
    created_at: str = field(default_factory=utc_now_iso)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ResearchExperiment":
        status = str(payload.get("status") or "NEEDS_REVIEW").upper()
        stage = str(payload.get("promotion_stage") or "OFFLINE_RESEARCH").upper()
        if status not in RESEARCH_STATUSES:
            status = "NEEDS_REVIEW"
        if stage not in PROMOTION_STAGES:
            stage = "OFFLINE_RESEARCH"
        duration = payload.get("paper_duration_seconds")
        try:
            parsed_duration = int(duration) if duration is not None else None
        except (TypeError, ValueError):
            parsed_duration = None
        return cls(
            id=str(payload.get("id") or research_id("exp")),
            title=str(payload.get("title") or "Untitled research experiment"),
            thesis=str(payload.get("thesis") or "No thesis supplied."),
            symbols_assets=_string_list(payload.get("symbols_assets") or payload.get("symbols")),
            strategy_area=str(payload.get("strategy_area") or "UNKNOWN"),
            expected_edge=str(payload.get("expected_edge") or "UNKNOWN_UNPROVEN"),
            evidence_required=_string_list(payload.get("evidence_required")),
            current_evidence=_string_list(payload.get("current_evidence")),
            risks=_string_list(payload.get("risks")),
            status=status,
            promotion_stage=stage,
            linked_hypothesis_id=str(payload.get("linked_hypothesis_id")) if payload.get("linked_hypothesis_id") else None,
            paper_duration_seconds=parsed_duration,
            can_execute=False,
            requires_shan_approval=True,
            paper_started=False,
            broker_call_occurred=False,
            trading_mutation_occurred=False,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["can_execute"] = False
        payload["requires_shan_approval"] = True
        payload["paper_started"] = False
        payload["broker_call_occurred"] = False
        payload["trading_mutation_occurred"] = False
        return payload


@dataclass
class ResearchRecommendation:
    id: str
    title: str
    summary: str
    recommendation_type: str = "PAPER_EXPERIMENT_PROPOSAL"
    evidence: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    status: str = "NEEDS_REVIEW"
    promotion_stage: str = "IDEA"
    can_execute: bool = False
    requires_shan_approval: bool = True
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["can_execute"] = False
        payload["requires_shan_approval"] = True
        return payload
