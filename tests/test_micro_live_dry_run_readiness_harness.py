from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import main as runtime_main
from app.state.state_store import StateStore


T0_NS = 1_777_948_800_000_000_000
MAX_SNAPSHOT_AGE_NS = 5_000_000_000
BOARD_TINY_NOTIONAL_CAP = Decimal("25.00")

FINAL_DRY_RUN_SAFE = "DRY_RUN_SAFE_BUT_NOT_LIVE_APPROVED"
FINAL_BLOCKED = "BLOCKED_WITH_REASONS"
FINAL_FAIL_CLOSED = "FAIL_CLOSED"


@dataclass(frozen=True)
class DryRunDecision:
    outcome: str
    reason_codes: tuple[str, ...] = ()
    dry_run_submit_allowed: bool = False
    real_submit_allowed: bool = False
    real_cancel_allowed: bool = False
    live_approved: bool = False
    live_reservation_lifecycle_allowed: bool = False
    side_effects: tuple[str, ...] = ()
    operator_inspection: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DryRunArmingEvidence:
    broker_mode: str = "paper"
    board_approved_dry_run: bool | None = False
    operator_armed: bool | None = False
    kill_switch_clear: bool | None = True
    live_adapter_contract_proven: bool | None = False
    broker_sandbox_read_only_proven: bool | None = False
    reconciliation_proven: bool | None = False
    cancel_terminal_proven: bool | None = False
    fill_telemetry_proven: bool | None = False
    account_position_balance_proven: bool | None = False
    operator_escape_proven: bool | None = False
    bounded_notional: Decimal | None = None
    single_order: bool | None = False
    single_symbol: str | None = None
    market_order_allowed: bool | None = False
    instrument_mapping_known: bool | None = False
    live_reservation_lifecycle_enabled: bool | None = False
    concrete_live_adapter_implemented: bool | None = False


@dataclass
class FakeDryRunSubmitter:
    calls: list[dict[str, Any]] = field(default_factory=list)

    def submit(self, evidence: DryRunArmingEvidence, *, timestamp_ns: int) -> DryRunDecision:
        decision = evaluate_dry_run_arming(evidence, timestamp_ns=timestamp_ns)
        if decision.dry_run_submit_allowed:
            self.calls.append({"symbol": evidence.single_symbol, "timestamp_ns": timestamp_ns})
        return decision


REQUIRED_ARMING_FIELDS = {
    "board_approved_dry_run": "missing_board_dry_run_approval",
    "operator_armed": "operator_not_armed",
    "live_adapter_contract_proven": "live_adapter_contract_not_proven",
    "broker_sandbox_read_only_proven": "broker_sandbox_read_only_proof_missing",
    "reconciliation_proven": "reconciliation_not_proven",
    "cancel_terminal_proven": "cancel_terminal_not_proven",
    "fill_telemetry_proven": "fill_telemetry_not_proven",
    "account_position_balance_proven": "account_position_balance_not_proven",
    "operator_escape_proven": "operator_escape_not_proven",
    "single_order": "single_order_required",
    "instrument_mapping_known": "instrument_mapping_unknown",
}


def _unique(reasons: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(reasons))


def _decision_from_reasons(reasons: list[str], *, inspection: dict[str, Any] | None = None) -> DryRunDecision:
    unique = _unique(reasons)
    return DryRunDecision(
        outcome=FINAL_DRY_RUN_SAFE if not unique else FINAL_BLOCKED,
        reason_codes=unique,
        dry_run_submit_allowed=not unique,
        real_submit_allowed=False,
        real_cancel_allowed=False,
        live_approved=False,
        live_reservation_lifecycle_allowed=False,
        operator_inspection=inspection or {"reason_codes": unique},
    )


def clean_arming_evidence() -> DryRunArmingEvidence:
    return DryRunArmingEvidence(
        broker_mode="live",
        board_approved_dry_run=True,
        operator_armed=True,
        kill_switch_clear=True,
        live_adapter_contract_proven=True,
        broker_sandbox_read_only_proven=True,
        reconciliation_proven=True,
        cancel_terminal_proven=True,
        fill_telemetry_proven=True,
        account_position_balance_proven=True,
        operator_escape_proven=True,
        bounded_notional=Decimal("5.00"),
        single_order=True,
        single_symbol="ETH/USD",
        market_order_allowed=False,
        instrument_mapping_known=True,
        live_reservation_lifecycle_enabled=False,
        concrete_live_adapter_implemented=False,
    )


def evaluate_dry_run_arming(evidence: DryRunArmingEvidence, *, timestamp_ns: int) -> DryRunDecision:
    reasons: list[str] = []
    if evidence.broker_mode != "live":
        reasons.append("broker_mode_not_live")
    for field_name, reason in REQUIRED_ARMING_FIELDS.items():
        if getattr(evidence, field_name) is not True:
            reasons.append(reason)
    if evidence.kill_switch_clear is not True:
        reasons.append("kill_switch_blocks_submit")
    if evidence.live_reservation_lifecycle_enabled is not False:
        reasons.append("live_reservation_lifecycle_must_remain_blocked")
    if evidence.market_order_allowed is not False:
        reasons.append("market_orders_not_allowed")
    if evidence.concrete_live_adapter_implemented is not False:
        reasons.append("concrete_live_adapter_must_not_be_implemented_in_dry_run")
    if evidence.bounded_notional is None:
        reasons.append("bounded_notional_missing")
    else:
        try:
            notional = Decimal(str(evidence.bounded_notional))
        except Exception:
            reasons.append("bounded_notional_invalid")
        else:
            if notional <= Decimal("0"):
                reasons.append("bounded_notional_invalid")
            if notional > BOARD_TINY_NOTIONAL_CAP:
                reasons.append("bounded_notional_exceeds_board_cap")
    if not evidence.single_symbol:
        reasons.append("single_symbol_required")

    return _decision_from_reasons(
        reasons,
        inspection={
            "timestamp_ns": timestamp_ns,
            "dry_run_only": True,
            "real_submit_allowed": False,
            "real_cancel_allowed": False,
            "live_approved": False,
        },
    )


@dataclass(frozen=True)
class AckFact:
    client_order_id: str | None
    broker_order_id: str | None
    exchange_order_id: str | None
    symbol: str
    side: str
    requested_qty: Decimal | None
    status: str
    exchange_ts_ns: int | None
    receive_ts_ns: int | None
    mapping_source: str | None
    response_kind: str = "ack"


@dataclass(frozen=True)
class FactDecision:
    accepted: bool = False
    fail_closed: bool = False
    reason_code: str = ""
    terminal_truth: bool = False
    needs_reconciliation: bool = False
    telemetry_payload: dict[str, Any] | None = None
    side_effects: tuple[str, ...] = ()


OPEN_ACK_STATUSES = {"accepted", "acknowledged", "open", "new", "pending"}
TERMINAL_STATUSES = {"filled", "canceled", "cancelled", "rejected", "expired"}


def validate_ack(ack: AckFact) -> FactDecision:
    if ack.response_kind in {"timeout", "exception"}:
        return FactDecision(fail_closed=True, reason_code=f"submit_{ack.response_kind}_is_not_ack")
    if ack.response_kind != "ack" or ack.status not in OPEN_ACK_STATUSES:
        return FactDecision(fail_closed=True, reason_code="ambiguous_submit_is_not_ack")
    if not ack.client_order_id:
        return FactDecision(fail_closed=True, reason_code="missing_client_order_id")
    if not (ack.broker_order_id or ack.exchange_order_id):
        return FactDecision(fail_closed=True, reason_code="missing_broker_order_identity")
    if ack.requested_qty is None or ack.requested_qty <= Decimal("0"):
        return FactDecision(fail_closed=True, reason_code="invalid_requested_quantity")
    if not ack.exchange_ts_ns or not ack.receive_ts_ns:
        return FactDecision(fail_closed=True, reason_code="missing_ack_timestamp")
    if not ack.mapping_source:
        return FactDecision(fail_closed=True, reason_code="missing_mapping_source")
    return FactDecision(accepted=True, needs_reconciliation=True)


@dataclass(frozen=True)
class CancelFact:
    client_order_id: str | None
    broker_order_id: str | None
    status: str
    exchange_ts_ns: int | None
    receive_ts_ns: int | None


@dataclass
class OrderTruthLedger:
    latest_exchange_ts_ns: int = 0
    terminal_status: str | None = None
    full_fill_terminal: bool = False


def classify_cancel_or_status(fact: CancelFact, ledger: OrderTruthLedger) -> FactDecision:
    if not fact.client_order_id or not fact.broker_order_id:
        return FactDecision(fail_closed=True, reason_code="missing_cancel_identity")
    if not fact.exchange_ts_ns or not fact.receive_ts_ns:
        return FactDecision(fail_closed=True, reason_code="missing_cancel_timestamp")
    if fact.exchange_ts_ns < ledger.latest_exchange_ts_ns:
        return FactDecision(fail_closed=True, reason_code="stale_status_cannot_overwrite_newer_truth")
    if fact.status == "cancel_accepted":
        ledger.latest_exchange_ts_ns = fact.exchange_ts_ns
        return FactDecision(accepted=True, terminal_truth=False, needs_reconciliation=True)
    if fact.status == "already_filled":
        return FactDecision(accepted=True, terminal_truth=False, needs_reconciliation=True)
    if fact.status == "not_found":
        return FactDecision(fail_closed=True, reason_code="not_found_requires_reconciliation")
    if fact.status in TERMINAL_STATUSES:
        ledger.latest_exchange_ts_ns = fact.exchange_ts_ns
        ledger.terminal_status = fact.status
        return FactDecision(accepted=True, terminal_truth=True)
    return FactDecision(fail_closed=True, reason_code="unknown_cancel_or_status_truth")


@dataclass(frozen=True)
class FillFact:
    client_order_id: str | None
    broker_order_id: str | None
    venue_fill_id: str | None
    symbol: str
    side: str
    requested_qty: Decimal | None
    fill_qty: Decimal | None
    cumulative_filled_qty: Decimal | None
    remaining_qty: Decimal | None
    fill_price: Decimal | None
    avg_fill_price: Decimal | None
    fee: Decimal | None
    fee_currency: str | None
    exchange_ts_ns: int | None
    receive_ts_ns: int | None
    status: str
    source: str | None = "fake_live_adapter"


@dataclass
class FillLedger:
    client_order_id: str = "client-1"
    broker_order_id: str = "broker-1"
    symbol: str = "ETH/USD"
    side: str = "buy"
    requested_qty: Decimal = Decimal("1.00")
    prior_cumulative_qty: Decimal = Decimal("0")
    latest_exchange_ts_ns: int = 0
    terminal_full_fill: bool = False
    fill_keys: set[str] = field(default_factory=set)


def make_fill(
    *,
    venue_fill_id: str = "fill-1",
    fill_qty: Decimal | None = Decimal("0.25"),
    cumulative_filled_qty: Decimal | None = Decimal("0.25"),
    remaining_qty: Decimal | None = Decimal("0.75"),
    fee: Decimal | None = Decimal("0.10"),
    fee_currency: str | None = "USD",
    exchange_ts_ns: int | None = T0_NS,
) -> FillFact:
    return FillFact(
        client_order_id="client-1",
        broker_order_id="broker-1",
        venue_fill_id=venue_fill_id,
        symbol="ETH/USD",
        side="buy",
        requested_qty=Decimal("1.00"),
        fill_qty=fill_qty,
        cumulative_filled_qty=cumulative_filled_qty,
        remaining_qty=remaining_qty,
        fill_price=Decimal("2500.50"),
        avg_fill_price=Decimal("2500.50"),
        fee=fee,
        fee_currency=fee_currency,
        exchange_ts_ns=exchange_ts_ns,
        receive_ts_ns=None if exchange_ts_ns is None else exchange_ts_ns + 1,
        status="filled" if remaining_qty == Decimal("0") else "partially_filled",
    )


def fill_key(fill: FillFact) -> str | None:
    if fill.client_order_id and fill.broker_order_id and fill.venue_fill_id:
        return f"{fill.client_order_id}:{fill.broker_order_id}:{fill.venue_fill_id}"
    return None


def classify_fill(fill: FillFact, ledger: FillLedger) -> FactDecision:
    key = fill_key(fill)
    if not fill.client_order_id or not fill.broker_order_id:
        return FactDecision(fail_closed=True, reason_code="missing_fill_order_identity")
    if not key:
        return FactDecision(fail_closed=True, reason_code="missing_fill_identity")
    if key in ledger.fill_keys:
        return FactDecision(accepted=True, reason_code="duplicate_fill_idempotent")
    if fill.fill_qty is None or fill.fill_qty <= Decimal("0"):
        return FactDecision(fail_closed=True, reason_code="invalid_fill_quantity")
    if fill.fill_price is None or fill.fill_price <= Decimal("0"):
        return FactDecision(fail_closed=True, reason_code="invalid_fill_price")
    if fill.fee is None:
        return FactDecision(fail_closed=True, reason_code="missing_fee")
    if not fill.fee_currency:
        return FactDecision(fail_closed=True, reason_code="missing_fee_currency")
    if fill.exchange_ts_ns is None or fill.receive_ts_ns is None:
        return FactDecision(fail_closed=True, reason_code="missing_fill_timestamp")
    if fill.cumulative_filled_qty is None or fill.remaining_qty is None:
        return FactDecision(fail_closed=True, reason_code="cumulative_remaining_ambiguity")
    if fill.cumulative_filled_qty < ledger.prior_cumulative_qty:
        return FactDecision(fail_closed=True, reason_code="cumulative_regression")
    if fill.cumulative_filled_qty > ledger.requested_qty:
        return FactDecision(fail_closed=True, reason_code="overfill")
    if fill.cumulative_filled_qty + fill.remaining_qty != ledger.requested_qty:
        return FactDecision(fail_closed=True, reason_code="quantity_balance_mismatch")
    if fill.exchange_ts_ns < ledger.latest_exchange_ts_ns:
        return FactDecision(fail_closed=True, reason_code="stale_fill_requires_reconciliation")
    if ledger.terminal_full_fill:
        return FactDecision(fail_closed=True, reason_code="fill_after_terminal_requires_reconciliation")

    ledger.fill_keys.add(key)
    ledger.prior_cumulative_qty = fill.cumulative_filled_qty
    ledger.latest_exchange_ts_ns = fill.exchange_ts_ns
    full_fill = fill.remaining_qty == Decimal("0")
    ledger.terminal_full_fill = full_fill
    return FactDecision(
        accepted=True,
        terminal_truth=full_fill,
        telemetry_payload={
            "client_order_id": fill.client_order_id,
            "broker_order_id": fill.broker_order_id,
            "venue_fill_id": fill.venue_fill_id,
            "symbol": fill.symbol,
            "side": fill.side,
            "requested_qty": str(fill.requested_qty),
            "filled_qty": str(fill.fill_qty),
            "cumulative_filled_qty": str(fill.cumulative_filled_qty),
            "remaining_qty": str(fill.remaining_qty),
            "fill_price": str(fill.fill_price),
            "avg_fill_price": str(fill.avg_fill_price),
            "fee": str(fill.fee),
            "fee_currency": fill.fee_currency,
            "exchange_timestamp_ns": fill.exchange_ts_ns,
            "receive_timestamp_ns": fill.receive_ts_ns,
            "paper_mode": False,
            "slippage_bps": None,
            "net_edge": None,
            "net_pnl": None,
            "profitability": None,
            "production_record_written": False,
        },
    )


@dataclass(frozen=True)
class BalanceFact:
    currency: str | None
    total: Decimal | None
    available: Decimal | None
    snapshot_ts_ns: int | None = T0_NS


@dataclass(frozen=True)
class PositionFact:
    symbol: str | None
    instrument_id: str | None
    quantity: Decimal | None
    snapshot_ts_ns: int | None = T0_NS


@dataclass(frozen=True)
class OpenOrderFact:
    client_order_id: str | None
    broker_order_id: str | None
    symbol: str | None
    status: str
    snapshot_ts_ns: int | None = T0_NS


@dataclass(frozen=True)
class AccountSnapshot:
    account_id: str | None
    source: str | None
    receive_ts_ns: int | None
    base_currency: str | None
    balances: tuple[BalanceFact, ...]
    positions: tuple[PositionFact, ...]
    open_orders: tuple[OpenOrderFact, ...] = ()


@dataclass(frozen=True)
class LocalReservation:
    client_order_id: str
    symbol: str
    open_qty: Decimal
    terminal: bool = False
    tombstoned: bool = False


@dataclass(frozen=True)
class LocalReconciliationState:
    exposures: dict[str, Decimal] = field(default_factory=dict)
    local_open_orders: tuple[str, ...] = ()
    reservations: tuple[LocalReservation, ...] = ()


def clean_snapshot() -> AccountSnapshot:
    return AccountSnapshot(
        account_id="sandbox-account",
        source="fake_read_only_snapshot",
        receive_ts_ns=T0_NS,
        base_currency="USD",
        balances=(BalanceFact("USD", Decimal("1000.00"), Decimal("950.00")),),
        positions=(PositionFact("ETH/USD", "eth-usd", Decimal("0.25")),),
        open_orders=(),
    )


def clean_local_state() -> LocalReconciliationState:
    return LocalReconciliationState(exposures={"ETH/USD": Decimal("0.25")})


def reconcile_account(snapshot: AccountSnapshot, local: LocalReconciliationState, *, now_ns: int) -> DryRunDecision:
    reasons: list[str] = []
    if not snapshot.account_id or not snapshot.source or snapshot.receive_ts_ns is None:
        reasons.append("account_snapshot_missing_or_ambiguous")
    if snapshot.receive_ts_ns is None or now_ns - snapshot.receive_ts_ns > MAX_SNAPSHOT_AGE_NS:
        reasons.append("account_snapshot_stale")
    balance = next((item for item in snapshot.balances if item.currency == "USD"), None)
    if balance is None or balance.currency != snapshot.base_currency:
        reasons.append("balance_currency_mismatch")
    elif balance.available is None:
        reasons.append("balance_available_missing")
    elif balance.total is None or balance.available < Decimal("0") or balance.available > balance.total:
        reasons.append("balance_negative_or_impossible")
    elif balance.snapshot_ts_ns is None or now_ns - balance.snapshot_ts_ns > MAX_SNAPSHOT_AGE_NS:
        reasons.append("balance_snapshot_stale")

    broker_positions: dict[str, Decimal] = {}
    for position in snapshot.positions:
        if not position.symbol or not position.instrument_id:
            reasons.append("instrument_mapping_unknown")
            continue
        if position.quantity is None:
            reasons.append("broker_position_unknown")
            continue
        if position.snapshot_ts_ns is None or now_ns - position.snapshot_ts_ns > MAX_SNAPSHOT_AGE_NS:
            reasons.append("position_snapshot_stale")
        broker_positions[position.symbol] = position.quantity
        if local.exposures.get(position.symbol, Decimal("0")) != position.quantity:
            reasons.append("position_mismatch")

    for symbol, local_qty in local.exposures.items():
        if symbol not in broker_positions and local_qty != Decimal("0"):
            reasons.append("position_mismatch")

    broker_open_ids = {order.client_order_id for order in snapshot.open_orders if order.client_order_id}
    for order in snapshot.open_orders:
        if not order.client_order_id or not order.broker_order_id:
            reasons.append("open_order_orphan")
        if order.snapshot_ts_ns is None or now_ns - order.snapshot_ts_ns > MAX_SNAPSHOT_AGE_NS:
            reasons.append("open_order_snapshot_stale")
        if order.client_order_id and order.client_order_id not in local.local_open_orders:
            reasons.append("broker_open_order_missing_locally")
    for local_order_id in local.local_open_orders:
        if local_order_id not in broker_open_ids:
            reasons.append("local_open_order_missing_at_broker")
    for reservation in local.reservations:
        if not reservation.terminal and not reservation.tombstoned and reservation.client_order_id not in broker_open_ids:
            reasons.append("local_reservation_without_broker_open_order")

    return _decision_from_reasons(reasons, inspection={"broker_truth_canonical": True})


@dataclass(frozen=True)
class EmergencyState:
    operator_armed: bool
    kill_switch_active: bool
    open_simulated_order_ids: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()

    def export(self) -> dict[str, Any]:
        return {
            "operator_armed": self.operator_armed,
            "kill_switch_active": self.kill_switch_active,
            "open_simulated_order_ids": list(self.open_simulated_order_ids),
            "reason_codes": list(self.reason_codes),
        }

    @classmethod
    def restore(cls, payload: dict[str, Any]) -> "EmergencyState":
        return cls(
            operator_armed=False,
            kill_switch_active=bool(payload.get("kill_switch_active", True)),
            open_simulated_order_ids=tuple(payload.get("open_simulated_order_ids", ())),
            reason_codes=tuple(payload.get("reason_codes", ())),
        )


def test_default_no_go_blocks_submit_and_live_reservation_lifecycle(tmp_path):
    root = runtime_main.SovereignHeartbeat.__new__(runtime_main.SovereignHeartbeat)
    root.state_store = StateStore(str(tmp_path / "state.db"))
    root._bootstrap_reservation_lifecycle_disabled(
        SimpleNamespace(
            initial_capital=20_000.0,
            broker_mode="live",
            reservation_lifecycle_paper_enabled=True,
        )
    )
    submitter = FakeDryRunSubmitter()
    decision = submitter.submit(DryRunArmingEvidence(), timestamp_ns=T0_NS)

    assert decision.outcome == FINAL_BLOCKED
    assert decision.dry_run_submit_allowed is False
    assert decision.real_submit_allowed is False
    assert submitter.calls == []
    assert "broker_mode_not_live" in decision.reason_codes
    assert "missing_board_dry_run_approval" in decision.reason_codes
    assert "live_adapter_contract_not_proven" in decision.reason_codes
    assert root.reservation_lifecycle_enabled is False
    assert root.reservation_lifecycle_bootstrap_status["reservation_lifecycle_live_blocked"] is True


def test_fully_evidenced_dry_run_can_be_eligible_without_live_approval():
    submitter = FakeDryRunSubmitter()
    decision = submitter.submit(clean_arming_evidence(), timestamp_ns=T0_NS)

    assert decision.outcome == FINAL_DRY_RUN_SAFE
    assert decision.reason_codes == ()
    assert decision.dry_run_submit_allowed is True
    assert decision.real_submit_allowed is False
    assert decision.real_cancel_allowed is False
    assert decision.live_approved is False
    assert decision.live_reservation_lifecycle_allowed is False
    assert submitter.calls == [{"symbol": "ETH/USD", "timestamp_ns": T0_NS}]


def test_fake_submit_ack_contract_accepts_only_unambiguous_ack():
    valid = validate_ack(
        AckFact("client-1", "broker-1", "exchange-1", "ETH/USD", "buy", Decimal("1"), "accepted", T0_NS, T0_NS + 1, "fake_adapter")
    )
    timeout = validate_ack(
        AckFact("client-1", None, None, "ETH/USD", "buy", Decimal("1"), "accepted", T0_NS, T0_NS + 1, "fake_adapter", "timeout")
    )
    ambiguous = validate_ack(
        AckFact("client-1", None, None, "ETH/USD", "buy", Decimal("1"), "unknown", T0_NS, T0_NS + 1, None)
    )

    assert valid.accepted is True
    assert valid.needs_reconciliation is True
    assert valid.terminal_truth is False
    assert timeout.reason_code == "submit_timeout_is_not_ack"
    assert ambiguous.reason_code == "ambiguous_submit_is_not_ack"
    assert valid.side_effects == ()


def test_cancel_terminal_branch_fails_closed_on_unresolved_truth():
    ledger = OrderTruthLedger(latest_exchange_ts_ns=T0_NS)
    accepted = classify_cancel_or_status(CancelFact("client-1", "broker-1", "cancel_accepted", T0_NS + 1, T0_NS + 2), ledger)
    already_filled = classify_cancel_or_status(CancelFact("client-1", "broker-1", "already_filled", T0_NS + 2, T0_NS + 3), ledger)
    not_found = classify_cancel_or_status(CancelFact("client-1", "broker-1", "not_found", T0_NS + 3, T0_NS + 4), ledger)
    ledger.latest_exchange_ts_ns = T0_NS + 10
    stale_canceled = classify_cancel_or_status(CancelFact("client-1", "broker-1", "canceled", T0_NS + 5, T0_NS + 11), ledger)

    assert accepted.accepted is True
    assert accepted.terminal_truth is False
    assert accepted.needs_reconciliation is True
    assert already_filled.accepted is True
    assert already_filled.needs_reconciliation is True
    assert not_found.reason_code == "not_found_requires_reconciliation"
    assert stale_canceled.reason_code == "stale_status_cannot_overwrite_newer_truth"
    assert accepted.side_effects == ()


def test_fill_telemetry_branch_handles_partial_full_duplicate_and_invalid_fills():
    ledger = FillLedger()
    partial = classify_fill(make_fill(venue_fill_id="fill-1"), ledger)
    full = classify_fill(
        make_fill(
            venue_fill_id="fill-2",
            fill_qty=Decimal("0.75"),
            cumulative_filled_qty=Decimal("1.00"),
            remaining_qty=Decimal("0"),
            exchange_ts_ns=T0_NS + 10,
        ),
        ledger,
    )
    duplicate = classify_fill(make_fill(venue_fill_id="fill-2", fill_qty=Decimal("0.75"), cumulative_filled_qty=Decimal("1.00"), remaining_qty=Decimal("0"), exchange_ts_ns=T0_NS + 10), ledger)

    assert partial.accepted is True
    assert partial.terminal_truth is False
    assert partial.telemetry_payload["production_record_written"] is False
    assert partial.telemetry_payload["net_pnl"] is None
    assert full.accepted is True
    assert full.terminal_truth is True
    assert duplicate.reason_code == "duplicate_fill_idempotent"

    overfill = classify_fill(make_fill(venue_fill_id="over", cumulative_filled_qty=Decimal("1.01"), remaining_qty=Decimal("0"), exchange_ts_ns=T0_NS), FillLedger())
    regression = classify_fill(make_fill(venue_fill_id="regress", cumulative_filled_qty=Decimal("0.10"), remaining_qty=Decimal("0.90"), exchange_ts_ns=T0_NS + 11), ledger)
    missing_fee = classify_fill(make_fill(venue_fill_id="fee", fee=None), FillLedger())
    missing_currency = classify_fill(make_fill(venue_fill_id="currency", fee_currency=None), FillLedger())

    assert overfill.reason_code == "overfill"
    assert regression.reason_code in {"cumulative_regression", "fill_after_terminal_requires_reconciliation"}
    assert missing_fee.reason_code == "missing_fee"
    assert missing_currency.reason_code == "missing_fee_currency"


def test_account_position_balance_reconciliation_accepts_clean_snapshot_and_blocks_conflicts():
    clean = reconcile_account(clean_snapshot(), clean_local_state(), now_ns=T0_NS + 1)
    stale = reconcile_account(clean_snapshot().__class__(**{**clean_snapshot().__dict__, "receive_ts_ns": T0_NS - MAX_SNAPSHOT_AGE_NS - 1}), clean_local_state(), now_ns=T0_NS)
    broker_open_missing_locally = reconcile_account(
        clean_snapshot().__class__(
            **{
                **clean_snapshot().__dict__,
                "open_orders": (OpenOrderFact("client-1", "broker-1", "ETH/USD", "open"),),
            }
        ),
        clean_local_state(),
        now_ns=T0_NS + 1,
    )
    local_reservation_without_broker = reconcile_account(
        clean_snapshot(),
        LocalReconciliationState(reservations=(LocalReservation("client-1", "ETH/USD", Decimal("1")),)),
        now_ns=T0_NS + 1,
    )
    position_mismatch = reconcile_account(clean_snapshot(), LocalReconciliationState(exposures={"ETH/USD": Decimal("0.10")}), now_ns=T0_NS + 1)
    missing_available = reconcile_account(
        clean_snapshot().__class__(**{**clean_snapshot().__dict__, "balances": (BalanceFact("USD", Decimal("1000"), None),)}),
        clean_local_state(),
        now_ns=T0_NS + 1,
    )
    currency_mismatch = reconcile_account(
        clean_snapshot().__class__(**{**clean_snapshot().__dict__, "balances": (BalanceFact("EUR", Decimal("1000"), Decimal("900")),)}),
        clean_local_state(),
        now_ns=T0_NS + 1,
    )

    assert clean.outcome == FINAL_DRY_RUN_SAFE
    assert clean.operator_inspection["broker_truth_canonical"] is True
    assert "account_snapshot_stale" in stale.reason_codes
    assert "broker_open_order_missing_locally" in broker_open_missing_locally.reason_codes
    assert "local_reservation_without_broker_open_order" in local_reservation_without_broker.reason_codes
    assert "position_mismatch" in position_mismatch.reason_codes
    assert "balance_available_missing" in missing_available.reason_codes
    assert "balance_currency_mismatch" in currency_mismatch.reason_codes


def test_kill_switch_operator_escape_and_restart_do_not_auto_arm():
    kill_switch_blocked = evaluate_dry_run_arming(
        clean_arming_evidence().__class__(**{**clean_arming_evidence().__dict__, "kill_switch_clear": False}),
        timestamp_ns=T0_NS,
    )
    emergency = EmergencyState(
        operator_armed=True,
        kill_switch_active=True,
        open_simulated_order_ids=("client-1",),
        reason_codes=kill_switch_blocked.reason_codes,
    )
    restored = EmergencyState.restore(emergency.export())

    assert "kill_switch_blocks_submit" in kill_switch_blocked.reason_codes
    assert kill_switch_blocked.dry_run_submit_allowed is False
    assert restored.operator_armed is False
    assert restored.kill_switch_active is True
    assert restored.open_simulated_order_ids == ("client-1",)
    assert "kill_switch_blocks_submit" in restored.reason_codes


def test_end_to_end_adversarial_cases_all_fail_closed_without_real_actions():
    cases = {
        "missing_board_dry_run_approval": {"board_approved_dry_run": False},
        "kill_switch_blocks_submit": {"kill_switch_clear": False},
        "live_reservation_lifecycle_must_remain_blocked": {"live_reservation_lifecycle_enabled": True},
        "market_orders_not_allowed": {"market_order_allowed": True},
        "bounded_notional_exceeds_board_cap": {"bounded_notional": Decimal("26.00")},
        "instrument_mapping_unknown": {"instrument_mapping_known": False},
        "concrete_live_adapter_must_not_be_implemented_in_dry_run": {"concrete_live_adapter_implemented": True},
    }
    for expected_reason, overrides in cases.items():
        evidence = clean_arming_evidence().__class__(**{**clean_arming_evidence().__dict__, **overrides})
        decision = evaluate_dry_run_arming(evidence, timestamp_ns=T0_NS)

        assert decision.outcome == FINAL_BLOCKED
        assert expected_reason in decision.reason_codes
        assert decision.real_submit_allowed is False
        assert decision.real_cancel_allowed is False
        assert decision.live_approved is False
        assert decision.side_effects == ()


def test_broker_adapter_and_live_broker_remain_contract_or_stub_only():
    broker_adapter_source = Path("app/execution/broker_adapter.py").read_text(encoding="utf-8-sig")
    live_broker_source = Path("app/execution/live_broker.py").read_text(encoding="utf-8-sig")

    assert "PRE-INTEGRATION" in broker_adapter_source
    assert "NO IMPLEMENTATION" in broker_adapter_source
    assert "Under construction" in live_broker_source
    assert "submit_order" not in live_broker_source
    assert "cancel_order" not in live_broker_source
