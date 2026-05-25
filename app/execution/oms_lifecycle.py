from __future__ import annotations

from enum import Enum
from typing import Any


class OmsOrderState(str, Enum):
    INTENT_CREATED = "INTENT_CREATED"
    PRE_TRADE_ALLOWED = "PRE_TRADE_ALLOWED"
    ROUTER_SUBMITTED = "ROUTER_SUBMITTED"
    BROKER_ACKNOWLEDGED = "BROKER_ACKNOWLEDGED"
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    RECONCILIATION_CONFLICT = "RECONCILIATION_CONFLICT"


class OmsReasonCode(str, Enum):
    CAPABILITY_UNAUTHORIZED = "CAPABILITY_UNAUTHORIZED"
    CANCEL_UNAUTHORIZED_BY_POLICY = "CANCEL_UNAUTHORIZED_BY_POLICY"
    CANCEL_NOT_FOUND = "CANCEL_NOT_FOUND"
    CANCEL_ALREADY_ATTEMPTED = "CANCEL_ALREADY_ATTEMPTED"
    BROKER_STATE_UNKNOWN = "BROKER_STATE_UNKNOWN"
    BROKER_FINAL_STATE_UNKNOWN = "BROKER_FINAL_STATE_UNKNOWN"
    FILL_LEDGER_UNAVAILABLE = "FILL_LEDGER_UNAVAILABLE"
    RECONCILIATION_CONFLICT = "RECONCILIATION_CONFLICT"
    ZOMBIE_SWEEP_FAILED = "ZOMBIE_SWEEP_FAILED"
    LIVE_OR_REAL_MONEY_BLOCKED = "LIVE_OR_REAL_MONEY_BLOCKED"


TERMINAL_OMS_STATES = frozenset(
    {
        OmsOrderState.FILLED.value,
        OmsOrderState.CANCELED.value,
        OmsOrderState.REJECTED.value,
        OmsOrderState.EXPIRED.value,
        OmsOrderState.RECONCILIATION_CONFLICT.value,
    }
)


def canonical_state_from_broker_status(status: Any) -> str:
    normalized = str(status or "").strip().lower()
    if normalized in {"accepted", "new", "pending_new", "pending", "acknowledged"}:
        return OmsOrderState.BROKER_ACKNOWLEDGED.value
    if normalized in {"open", "accepted_for_bidding"}:
        return OmsOrderState.OPEN.value
    if normalized in {"partially_filled", "partial_fill", "partial"}:
        return OmsOrderState.PARTIALLY_FILLED.value
    if normalized in {"filled", "closed"}:
        return OmsOrderState.FILLED.value
    if normalized in {"canceled", "cancelled"}:
        return OmsOrderState.CANCELED.value
    if normalized == "expired":
        return OmsOrderState.EXPIRED.value
    if normalized == "rejected":
        return OmsOrderState.REJECTED.value
    return OmsOrderState.RECONCILIATION_CONFLICT.value


def is_terminal_oms_state(state: Any) -> bool:
    return str(state or "") in TERMINAL_OMS_STATES
