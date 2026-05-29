"""AI Chief recommendation and governance models."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


ALLOWED_RECOMMENDATION_TYPES = {
    "OBSERVATION",
    "RISK_WARNING",
    "STRATEGY_REVIEW",
    "EXECUTION_QUALITY_REVIEW",
    "WORLD_AWARENESS_SUMMARY",
    "PAPER_EXPERIMENT_PROPOSAL",
    "LIVE_READINESS_REVIEW",
    "DO_NOT_TRADE_WARNING",
    "SYSTEM_HEALTH_WARNING",
}

GOVERNANCE_STATES = {
    "DRAFT",
    "PENDING_REVIEW",
    "APPROVED_FOR_PAPER_RESEARCH",
    "REJECTED",
    "EXPIRED",
    "ESCALATED",
    "LIVE_REQUIRES_SEPARATE_APPROVAL",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_payload(payload: Any) -> str:
    text = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class AIRecommendation:
    recommendation_id: str
    provider: str
    role: str
    created_at: str
    recommendation_type: str
    summary: str
    evidence: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    uncertainty: list[str] = field(default_factory=list)
    proposed_action: str = "NO_ACTION"
    can_execute: bool = False
    requires_shan_approval: bool = True
    authority_level: str = "ADVISORY_ONLY"
    status: str = "PENDING_REVIEW"
    refusal_reason: str | None = None
    audit_event_id: str | None = None
    raw_response_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["can_execute"] = False
        data["requires_shan_approval"] = True
        data["authority_level"] = "ADVISORY_ONLY"
        return data


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return [str(value)]


def normalize_recommendation(raw: dict[str, Any], *, provider: str, role: str = "AI_CHIEF_OPERATOR") -> AIRecommendation:
    payload = dict(raw or {})
    rec_type = str(payload.get("recommendation_type") or "OBSERVATION").upper()
    status = str(payload.get("status") or "PENDING_REVIEW").upper()
    refusal_reason = payload.get("refusal_reason")
    proposed_action = str(payload.get("proposed_action") or "NO_ACTION")
    summary = str(payload.get("summary") or "No advisory summary was provided.")
    can_execute_requested = bool(payload.get("can_execute"))
    unsafe_live_action = any(
        token in proposed_action.upper()
        for token in (
            "LIVE",
            "REAL_MONEY",
            "REAL MONEY",
            "BROKER_ORDER",
            "SUBMIT_ORDER",
            "CANCEL",
            "LIQUIDATE",
            "START_PAPER",
            "START PAPER",
            "TRADE_NOW",
            "ENABLE_REAL_MONEY",
        )
    )

    if rec_type not in ALLOWED_RECOMMENDATION_TYPES:
        rec_type = "OBSERVATION"
        status = "REJECTED"
        refusal_reason = "UNSUPPORTED_RECOMMENDATION_TYPE"
    elif unsafe_live_action:
        status = "LIVE_REQUIRES_SEPARATE_APPROVAL"
        refusal_reason = "LIVE_OR_BROKER_ACTION_REQUIRES_SEPARATE_APPROVAL"
    elif can_execute_requested:
        status = "ESCALATED"
        refusal_reason = "CAN_EXECUTE_FORCED_FALSE"
    elif status not in GOVERNANCE_STATES:
        status = "PENDING_REVIEW"

    return AIRecommendation(
        recommendation_id=str(payload.get("recommendation_id") or f"ai_rec_{uuid.uuid4().hex[:16]}"),
        provider=provider,
        role=role,
        created_at=str(payload.get("created_at") or utc_now_iso()),
        recommendation_type=rec_type,
        summary=summary,
        evidence=_string_list(payload.get("evidence")),
        risks=_string_list(payload.get("risks")),
        uncertainty=_string_list(payload.get("uncertainty")),
        proposed_action=proposed_action,
        can_execute=False,
        requires_shan_approval=True,
        authority_level="ADVISORY_ONLY",
        status=status,
        refusal_reason=str(refusal_reason) if refusal_reason else None,
        audit_event_id=str(payload.get("audit_event_id") or f"ai_audit_{uuid.uuid4().hex[:16]}"),
        raw_response_hash=_hash_payload(payload),
    )
