from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import main as runtime_main
from app.state.state_store import StateStore


T0_NS = 1_777_948_800_000_000_000
TERMINAL_NON_FILL_STATUSES = {"canceled", "cancelled", "rejected", "expired"}
TERMINAL_STATUSES = TERMINAL_NON_FILL_STATUSES | {"filled"}
OPEN_STATUSES = {"open", "accepted", "acknowledged", "pending", "partially_filled"}


@dataclass(frozen=True)
class TerminalDecision:
    classification: str
    reason_code: str
    terminal_truth: bool = False
    fill_truth: bool = False
    fail_closed: bool = False
    release_candidate: bool = False
    route_to: str = "none"
    side_effects: tuple[str, ...] = ()
    audit: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CancelEvidence:
    client_order_id: str | None
    broker_order_id: str | None
    cancel_state: str
    source: str | None
    exchange_ts_ns: int | None
    receive_ts_ns: int | None


@dataclass(frozen=True)
class RejectEvidence:
    client_order_id: str | None
    broker_order_id: str | None
    reason: str | None
    after_ack: bool
    source: str | None
    exchange_ts_ns: int | None
    receive_ts_ns: int | None


@dataclass(frozen=True)
class StatusEvidence:
    client_order_id: str | None
    broker_order_id: str | None
    status: str
    source: str | None
    exchange_ts_ns: int | None
    receive_ts_ns: int | None
    cumulative_filled_qty: Decimal | None = None
    remaining_qty: Decimal | None = None


@dataclass(frozen=True)
class FillEvidence:
    client_order_id: str | None
    broker_order_id: str | None
    venue_fill_id: str | None
    fill_qty: Decimal | None
    cumulative_filled_qty: Decimal | None
    remaining_qty: Decimal | None
    fill_price: Decimal | None
    fee: Decimal | None
    fee_currency: str | None
    source: str | None
    exchange_ts_ns: int | None
    receive_ts_ns: int | None


@dataclass(frozen=True)
class ReconciliationSnapshot:
    client_order_id: str
    broker_order_id: str
    open_order_present: bool
    recent_fills: tuple[FillEvidence, ...]
    status: StatusEvidence | None
    positions: tuple[dict[str, Any], ...] = ()
    source: str | None = "mock_terminal_reconciliation"
    snapshot_ts_ns: int | None = T0_NS


@dataclass
class TerminalLedger:
    latest_ts_ns: int = 0
    terminal_status: str | None = None
    fill_keys: set[str] = field(default_factory=set)
    release_keys: set[str] = field(default_factory=set)


def _audit(kind: str, evidence: Any, reason_code: str) -> dict[str, Any]:
    return {
        "evidence_kind": kind,
        "client_order_id": getattr(evidence, "client_order_id", None),
        "broker_order_id": getattr(evidence, "broker_order_id", None),
        "source": getattr(evidence, "source", None),
        "exchange_ts_ns": getattr(evidence, "exchange_ts_ns", None),
        "receive_ts_ns": getattr(evidence, "receive_ts_ns", None),
        "reason_code": reason_code,
        "submit_command_performed": False,
        "cancel_command_performed": False,
        "reservation_mutated": False,
        "live_fill_recorded": False,
        "pnl_or_edge_invented": False,
    }


def _has_identity_and_time(evidence: Any) -> bool:
    return bool(
        getattr(evidence, "client_order_id", None)
        and getattr(evidence, "broker_order_id", None)
        and getattr(evidence, "source", None)
        and getattr(evidence, "exchange_ts_ns", None)
        and getattr(evidence, "receive_ts_ns", None)
    )


def classify_cancel(evidence: CancelEvidence) -> TerminalDecision:
    if not _has_identity_and_time(evidence):
        return TerminalDecision(
            "fail_closed",
            "missing_cancel_identity_source_or_timestamp",
            fail_closed=True,
            audit=_audit("cancel", evidence, "missing_cancel_identity_source_or_timestamp"),
        )
    if evidence.cancel_state in {"accepted", "pending"}:
        return TerminalDecision(
            "cancel_nonterminal",
            "cancel_acceptance_is_not_terminal_truth",
            terminal_truth=False,
            route_to="await_status_or_reconciliation",
            audit=_audit("cancel", evidence, "cancel_acceptance_is_not_terminal_truth"),
        )
    if evidence.cancel_state == "already_filled":
        return TerminalDecision(
            "fill_truth_required",
            "already_filled_routes_to_fill_truth",
            terminal_truth=False,
            fill_truth=True,
            route_to="fill_truth",
            audit=_audit("cancel", evidence, "already_filled_routes_to_fill_truth"),
        )
    if evidence.cancel_state == "not_found":
        return TerminalDecision(
            "fail_closed",
            "not_found_requires_reconciliation",
            fail_closed=True,
            route_to="terminal_reconciliation_required",
            audit=_audit("cancel", evidence, "not_found_requires_reconciliation"),
        )
    return TerminalDecision(
        "fail_closed",
        f"cancel_{evidence.cancel_state}_fails_closed",
        fail_closed=True,
        audit=_audit("cancel", evidence, f"cancel_{evidence.cancel_state}_fails_closed"),
    )


def classify_reject(evidence: RejectEvidence) -> TerminalDecision:
    if not evidence.client_order_id or not evidence.reason or not evidence.source or not evidence.receive_ts_ns:
        return TerminalDecision(
            "fail_closed",
            "ambiguous_reject_fails_closed",
            fail_closed=True,
            audit=_audit("reject", evidence, "ambiguous_reject_fails_closed"),
        )
    if not evidence.after_ack:
        return TerminalDecision(
            "pre_ack_reject",
            "pre_ack_reject_telemetry_only",
            terminal_truth=True,
            release_candidate=False,
            route_to="telemetry_error_only",
            audit=_audit("reject", evidence, "pre_ack_reject_telemetry_only"),
        )
    if not evidence.broker_order_id or not evidence.exchange_ts_ns:
        return TerminalDecision(
            "fail_closed",
            "post_ack_reject_requires_terminal_proof",
            fail_closed=True,
            route_to="terminal_reconciliation_required",
            audit=_audit("reject", evidence, "post_ack_reject_requires_terminal_proof"),
        )
    return TerminalDecision(
        "post_ack_reject_terminal_candidate",
        "post_ack_reject_requires_reconciliation_before_release",
        terminal_truth=True,
        release_candidate=False,
        route_to="terminal_reconciliation_required",
        audit=_audit("reject", evidence, "post_ack_reject_requires_reconciliation_before_release"),
    )


def fill_key(fill: FillEvidence) -> str | None:
    if fill.client_order_id and fill.broker_order_id and fill.venue_fill_id:
        return f"{fill.client_order_id}:{fill.broker_order_id}:{fill.venue_fill_id}"
    return None


def classify_fill(fill: FillEvidence, ledger: TerminalLedger) -> TerminalDecision:
    if not _has_identity_and_time(fill) or not fill.venue_fill_id:
        return TerminalDecision(
            "fail_closed",
            "missing_fill_identity_source_or_timestamp",
            fail_closed=True,
            audit=_audit("fill", fill, "missing_fill_identity_source_or_timestamp"),
        )
    if fill.fill_qty is None or fill.fill_qty <= Decimal("0") or fill.fill_price is None:
        return TerminalDecision(
            "fail_closed",
            "missing_fill_qty_or_price",
            fail_closed=True,
            audit=_audit("fill", fill, "missing_fill_qty_or_price"),
        )
    if fill.fee is None or fill.fee_currency is None:
        return TerminalDecision(
            "fail_closed",
            "missing_fill_fee_evidence",
            fail_closed=True,
            audit=_audit("fill", fill, "missing_fill_fee_evidence"),
        )
    key = fill_key(fill)
    if key in ledger.fill_keys:
        return TerminalDecision(
            "duplicate_fill_idempotent",
            "duplicate_fill_idempotent",
            fill_truth=True,
            terminal_truth=fill.remaining_qty == Decimal("0"),
            route_to="no_new_record",
            audit=_audit("fill", fill, "duplicate_fill_idempotent"),
        )
    ledger.fill_keys.add(str(key))
    terminal = fill.remaining_qty == Decimal("0")
    if terminal:
        ledger.terminal_status = "filled"
        ledger.latest_ts_ns = max(ledger.latest_ts_ns, int(fill.exchange_ts_ns or 0))
    return TerminalDecision(
        "full_fill" if terminal else "partial_fill",
        "full_fill_routes_to_fill_truth" if terminal else "partial_fill_preserves_remaining_truth",
        terminal_truth=terminal,
        fill_truth=True,
        release_candidate=False,
        route_to="fill_truth",
        audit=_audit(
            "fill",
            fill,
            "full_fill_routes_to_fill_truth" if terminal else "partial_fill_preserves_remaining_truth",
        ),
    )


def classify_status(status: StatusEvidence, ledger: TerminalLedger) -> TerminalDecision:
    if not _has_identity_and_time(status):
        return TerminalDecision(
            "fail_closed",
            "missing_status_identity_source_or_timestamp",
            fail_closed=True,
            audit=_audit("status", status, "missing_status_identity_source_or_timestamp"),
        )
    if int(status.exchange_ts_ns or 0) < ledger.latest_ts_ns:
        return TerminalDecision(
            "fail_closed",
            "stale_status_cannot_overwrite_newer_truth",
            fail_closed=True,
            audit=_audit("status", status, "stale_status_cannot_overwrite_newer_truth"),
        )
    if ledger.terminal_status == "filled" and status.status in TERMINAL_NON_FILL_STATUSES:
        return TerminalDecision(
            "fail_closed",
            "non_fill_terminal_cannot_overwrite_fill_truth",
            fail_closed=True,
            route_to="terminal_reconciliation_required",
            audit=_audit("status", status, "non_fill_terminal_cannot_overwrite_fill_truth"),
        )
    if status.status in {"unknown", "not_found"}:
        return TerminalDecision(
            "fail_closed",
            f"{status.status}_requires_reconciliation",
            fail_closed=True,
            route_to="terminal_reconciliation_required",
            audit=_audit("status", status, f"{status.status}_requires_reconciliation"),
        )
    if status.status == "partially_filled":
        return TerminalDecision(
            "partial_fill_open",
            "partial_fill_is_not_terminal",
            terminal_truth=False,
            route_to="fill_or_status_reconciliation",
            audit=_audit("status", status, "partial_fill_is_not_terminal"),
        )
    if status.status == "filled":
        return TerminalDecision(
            "full_fill_status",
            "full_fill_status_routes_to_fill_truth",
            terminal_truth=True,
            fill_truth=True,
            release_candidate=False,
            route_to="fill_truth",
            audit=_audit("status", status, "full_fill_status_routes_to_fill_truth"),
        )
    if status.status in TERMINAL_NON_FILL_STATUSES:
        if ledger.terminal_status == status.status:
            return TerminalDecision(
                "duplicate_terminal_idempotent",
                "duplicate_terminal_idempotent",
                terminal_truth=True,
                release_candidate=False,
                route_to="no_new_release",
                audit=_audit("status", status, "duplicate_terminal_idempotent"),
            )
        ledger.terminal_status = status.status
        ledger.latest_ts_ns = int(status.exchange_ts_ns or 0)
        return TerminalDecision(
            "terminal_non_fill_candidate",
            f"{status.status}_requires_reconciliation_before_release",
            terminal_truth=True,
            release_candidate=False,
            route_to="terminal_reconciliation_required",
            audit=_audit("status", status, f"{status.status}_requires_reconciliation_before_release"),
        )
    if status.status in OPEN_STATUSES:
        ledger.latest_ts_ns = int(status.exchange_ts_ns or 0)
        return TerminalDecision(
            "open_status",
            "open_status_preserves_pending_truth",
            route_to="open_order_monitoring",
            audit=_audit("status", status, "open_status_preserves_pending_truth"),
        )
    return TerminalDecision(
        "fail_closed",
        "unsupported_status_fails_closed",
        fail_closed=True,
        audit=_audit("status", status, "unsupported_status_fails_closed"),
    )


def reconcile_terminal(snapshot: ReconciliationSnapshot) -> TerminalDecision:
    synthetic = StatusEvidence(
        snapshot.client_order_id,
        snapshot.broker_order_id,
        snapshot.status.status if snapshot.status else "missing",
        snapshot.source,
        snapshot.snapshot_ts_ns,
        snapshot.snapshot_ts_ns,
    )
    if not snapshot.source or not snapshot.snapshot_ts_ns:
        return TerminalDecision(
            "fail_closed",
            "missing_reconciliation_source_or_timestamp",
            fail_closed=True,
            audit=_audit("reconciliation", synthetic, "missing_reconciliation_source_or_timestamp"),
        )
    if snapshot.open_order_present:
        return TerminalDecision(
            "fail_closed",
            "broker_open_order_conflicts_with_terminal_release",
            fail_closed=True,
            audit=_audit("reconciliation", synthetic, "broker_open_order_conflicts_with_terminal_release"),
        )
    if snapshot.recent_fills:
        return TerminalDecision(
            "fill_truth_required",
            "recent_fill_truth_wins_terminal_release",
            fill_truth=True,
            route_to="fill_truth",
            audit=_audit("reconciliation", synthetic, "recent_fill_truth_wins_terminal_release"),
        )
    if snapshot.status and snapshot.status.status in TERMINAL_NON_FILL_STATUSES:
        return TerminalDecision(
            "terminal_release_candidate",
            "terminal_release_candidate_reconciliation_supported",
            terminal_truth=True,
            release_candidate=True,
            route_to="future_release_candidate_only",
            audit=_audit("reconciliation", synthetic, "terminal_release_candidate_reconciliation_supported"),
        )
    return TerminalDecision(
        "fail_closed",
        "unresolved_terminal_conflict_fails_closed",
        fail_closed=True,
        audit=_audit("reconciliation", synthetic, "unresolved_terminal_conflict_fails_closed"),
    )


def test_cancel_acceptance_is_nonterminal_and_fill_after_cancel_wins():
    accepted = classify_cancel(
        CancelEvidence("client-1", "broker-1", "accepted", "mock_cancel", T0_NS, T0_NS + 1)
    )
    pending = classify_cancel(
        CancelEvidence("client-1", "broker-1", "pending", "mock_cancel", T0_NS, T0_NS + 1)
    )
    filled_after = classify_cancel(
        CancelEvidence("client-1", "broker-1", "already_filled", "mock_cancel", T0_NS + 2, T0_NS + 3)
    )

    assert accepted.terminal_truth is False
    assert accepted.release_candidate is False
    assert accepted.reason_code == "cancel_acceptance_is_not_terminal_truth"
    assert pending.reason_code == "cancel_acceptance_is_not_terminal_truth"
    assert filled_after.fill_truth is True
    assert filled_after.route_to == "fill_truth"
    assert accepted.side_effects == ()


def test_cancel_rejected_unknown_timeout_and_not_found_fail_closed_without_release():
    rejected = classify_cancel(
        CancelEvidence("client-1", "broker-1", "rejected", "mock_cancel", T0_NS, T0_NS + 1)
    )
    timeout = classify_cancel(
        CancelEvidence("client-1", "broker-1", "timeout", "mock_cancel", T0_NS, T0_NS + 1)
    )
    not_found = classify_cancel(
        CancelEvidence("client-1", "broker-1", "not_found", "mock_cancel", T0_NS, T0_NS + 1)
    )
    missing = classify_cancel(
        CancelEvidence("client-1", None, "accepted", "mock_cancel", T0_NS, T0_NS + 1)
    )

    for decision in (rejected, timeout, not_found, missing):
        assert decision.fail_closed is True
        assert decision.release_candidate is False
        assert decision.side_effects == ()
        assert decision.audit["reservation_mutated"] is False
    assert not_found.route_to == "terminal_reconciliation_required"
    assert missing.reason_code == "missing_cancel_identity_source_or_timestamp"


def test_reject_before_ack_differs_from_reject_after_ack():
    pre_ack = classify_reject(
        RejectEvidence("client-1", None, "min_notional", False, "mock_submit", None, T0_NS + 1)
    )
    post_ack_missing_terminal = classify_reject(
        RejectEvidence("client-1", "broker-1", "exchange_reject", True, "mock_status", None, T0_NS + 2)
    )
    post_ack_with_proof = classify_reject(
        RejectEvidence("client-1", "broker-1", "exchange_reject", True, "mock_status", T0_NS + 3, T0_NS + 4)
    )

    assert pre_ack.reason_code == "pre_ack_reject_telemetry_only"
    assert pre_ack.release_candidate is False
    assert pre_ack.route_to == "telemetry_error_only"
    assert post_ack_missing_terminal.fail_closed is True
    assert post_ack_missing_terminal.reason_code == "post_ack_reject_requires_terminal_proof"
    assert post_ack_with_proof.terminal_truth is True
    assert post_ack_with_proof.release_candidate is False
    assert post_ack_with_proof.route_to == "terminal_reconciliation_required"


def test_terminal_status_classification_requires_identity_timestamp_and_fill_truth_boundary():
    ledger = TerminalLedger()
    canceled = classify_status(
        StatusEvidence("client-1", "broker-1", "canceled", "mock_status", T0_NS, T0_NS + 1),
        ledger,
    )
    duplicate = classify_status(
        StatusEvidence("client-1", "broker-1", "canceled", "mock_status", T0_NS, T0_NS + 2),
        ledger,
    )
    partial = classify_status(
        StatusEvidence(
            "client-2",
            "broker-2",
            "partially_filled",
            "mock_status",
            T0_NS + 10,
            T0_NS + 11,
            cumulative_filled_qty=Decimal("0.25"),
            remaining_qty=Decimal("0.75"),
        ),
        TerminalLedger(),
    )
    full = classify_status(
        StatusEvidence(
            "client-3",
            "broker-3",
            "filled",
            "mock_status",
            T0_NS + 20,
            T0_NS + 21,
            cumulative_filled_qty=Decimal("1"),
            remaining_qty=Decimal("0"),
        ),
        TerminalLedger(),
    )
    unknown = classify_status(
        StatusEvidence("client-4", "broker-4", "unknown", "mock_status", T0_NS + 30, T0_NS + 31),
        TerminalLedger(),
    )
    not_found = classify_status(
        StatusEvidence("client-4", "broker-4", "not_found", "mock_status", T0_NS + 30, T0_NS + 31),
        TerminalLedger(),
    )

    assert canceled.terminal_truth is True
    assert canceled.release_candidate is False
    assert canceled.route_to == "terminal_reconciliation_required"
    assert duplicate.reason_code == "duplicate_terminal_idempotent"
    assert partial.reason_code == "partial_fill_is_not_terminal"
    assert partial.terminal_truth is False
    assert full.fill_truth is True
    assert full.route_to == "fill_truth"
    assert unknown.fail_closed is True
    assert not_found.reason_code == "not_found_requires_reconciliation"


def test_stale_out_of_order_and_conflicting_status_fail_closed():
    ledger = TerminalLedger()
    full_fill = FillEvidence(
        "client-1",
        "broker-1",
        "fill-1",
        Decimal("1"),
        Decimal("1"),
        Decimal("0"),
        Decimal("2500.00"),
        Decimal("0.10"),
        "USD",
        "mock_fill",
        T0_NS + 10,
        T0_NS + 11,
    )
    assert classify_fill(full_fill, ledger).terminal_truth is True
    stale_open = classify_status(
        StatusEvidence("client-1", "broker-1", "open", "mock_status", T0_NS + 1, T0_NS + 12),
        ledger,
    )
    stale_not_found = classify_status(
        StatusEvidence("client-1", "broker-1", "not_found", "mock_status", T0_NS + 2, T0_NS + 13),
        ledger,
    )
    stale_canceled_after_fill = classify_status(
        StatusEvidence("client-1", "broker-1", "canceled", "mock_status", T0_NS + 20, T0_NS + 21),
        ledger,
    )
    duplicate_fill = classify_fill(full_fill, ledger)

    assert stale_open.reason_code == "stale_status_cannot_overwrite_newer_truth"
    assert stale_not_found.reason_code == "stale_status_cannot_overwrite_newer_truth"
    assert stale_canceled_after_fill.reason_code == "non_fill_terminal_cannot_overwrite_fill_truth"
    assert stale_canceled_after_fill.route_to == "terminal_reconciliation_required"
    assert duplicate_fill.reason_code == "duplicate_fill_idempotent"
    assert duplicate_fill.route_to == "no_new_record"


def test_reconciliation_snapshot_is_read_only_and_controls_release_candidate():
    terminal_status = StatusEvidence(
        "client-1", "broker-1", "canceled", "mock_status", T0_NS, T0_NS + 1
    )
    fill = FillEvidence(
        "client-1",
        "broker-1",
        "fill-1",
        Decimal("0.50"),
        Decimal("0.50"),
        Decimal("0.50"),
        Decimal("2500.00"),
        Decimal("0.05"),
        "USD",
        "mock_fill",
        T0_NS + 2,
        T0_NS + 3,
    )

    release_candidate = reconcile_terminal(
        ReconciliationSnapshot("client-1", "broker-1", False, (), terminal_status)
    )
    open_conflict = reconcile_terminal(
        ReconciliationSnapshot("client-1", "broker-1", True, (), terminal_status)
    )
    fill_conflict = reconcile_terminal(
        ReconciliationSnapshot("client-1", "broker-1", False, (fill,), terminal_status)
    )
    unresolved = reconcile_terminal(
        ReconciliationSnapshot("client-1", "broker-1", False, (), None)
    )

    assert release_candidate.release_candidate is True
    assert release_candidate.route_to == "future_release_candidate_only"
    assert release_candidate.side_effects == ()
    assert release_candidate.audit["cancel_command_performed"] is False
    assert open_conflict.fail_closed is True
    assert open_conflict.reason_code == "broker_open_order_conflicts_with_terminal_release"
    assert fill_conflict.fill_truth is True
    assert fill_conflict.reason_code == "recent_fill_truth_wins_terminal_release"
    assert unresolved.fail_closed is True


def test_live_reservation_lifecycle_remains_disabled_and_audit_exposes_reason_codes(tmp_path):
    root = runtime_main.SovereignHeartbeat.__new__(runtime_main.SovereignHeartbeat)
    root.state_store = StateStore(str(tmp_path / "state.db"))
    root._bootstrap_reservation_lifecycle_disabled(
        SimpleNamespace(
            initial_capital=20_000.0,
            broker_mode="live",
            reservation_lifecycle_paper_enabled=True,
        )
    )
    decision = classify_status(
        StatusEvidence("client-1", "broker-1", "expired", "mock_status", T0_NS, T0_NS + 1),
        TerminalLedger(),
    )

    assert root.reservation_lifecycle_enabled is False
    assert root.reservation_lifecycle_bootstrap_status["reservation_lifecycle_live_blocked"] is True
    assert decision.release_candidate is False
    assert decision.audit["reason_code"] == "expired_requires_reconciliation_before_release"
    assert decision.audit["reservation_mutated"] is False
    assert decision.audit["live_fill_recorded"] is False
    assert decision.audit["pnl_or_edge_invented"] is False

    broker_adapter_source = Path("app/execution/broker_adapter.py").read_text(encoding="utf-8-sig")
    live_broker_source = Path("app/execution/live_broker.py").read_text(encoding="utf-8-sig")
    assert "PRE-INTEGRATION" in broker_adapter_source
    assert "Under construction" in live_broker_source
    assert "submit_order" not in live_broker_source
