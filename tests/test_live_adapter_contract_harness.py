from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import main as runtime_main
from app.config import Config
from app.risk.kill_switch import KillSwitch, KillSwitchType
from app.state.state_store import StateStore


T0_NS = 1_777_948_800_000_000_000
TERMINAL_STATUSES = {"filled", "canceled", "cancelled", "rejected", "expired"}
OPEN_STATUSES = {"accepted", "acknowledged", "open", "new", "pending", "partially_filled"}


@dataclass(frozen=True)
class ContractResult:
    accepted: bool = False
    fail_closed: bool = False
    reason: str = ""
    is_ack: bool = False
    opens_reservation: bool = False
    records_fill: bool = False
    terminal_truth: bool = False
    needs_reconciliation: bool = False
    mutation_allowed: bool = False
    route_to: str = "none"
    side_effects: tuple[str, ...] = ()


@dataclass(frozen=True)
class SubmitAck:
    client_order_id: str | None
    broker_order_id: str | None
    exchange_order_id: str | None
    symbol: str
    side: str
    requested_quantity: Decimal | None
    order_type: str
    limit_price: Decimal | None
    venue_status: str
    exchange_ts_ns: int | None
    receive_ts_ns: int | None
    mapping_source: str | None
    response_kind: str = "ack"


@dataclass(frozen=True)
class RejectFact:
    client_order_id: str | None
    broker_order_id: str | None
    reject_reason: str | None
    after_ack: bool
    venue_status: str
    exchange_ts_ns: int | None
    receive_ts_ns: int | None


@dataclass(frozen=True)
class CancelFact:
    client_order_id: str | None
    broker_order_id: str | None
    cancel_status: str
    exchange_ts_ns: int | None
    receive_ts_ns: int | None


@dataclass(frozen=True)
class StatusFact:
    client_order_id: str | None
    broker_order_id: str | None
    status: str
    source: str
    exchange_ts_ns: int | None
    receive_ts_ns: int | None


@dataclass(frozen=True)
class FillFact:
    client_order_id: str | None
    broker_order_id: str | None
    venue_fill_id: str | None
    symbol: str
    side: str
    fill_quantity: Decimal | None
    cumulative_filled_quantity: Decimal | None
    remaining_quantity: Decimal | None
    fill_price: Decimal | None
    average_fill_price: Decimal | None
    fee: Decimal | None
    fee_currency: str | None
    exchange_ts_ns: int | None
    receive_ts_ns: int | None
    liquidity: str | None = None
    raw_source: str = "mock_live_adapter"


@dataclass(frozen=True)
class ReconciliationSnapshot:
    open_orders: tuple[StatusFact, ...]
    positions: tuple[dict[str, Any], ...]
    balances: tuple[dict[str, Any], ...]
    recent_fills: tuple[FillFact, ...]
    account_id: str | None
    source: str
    snapshot_ts_ns: int


@dataclass
class ContractLedger:
    fill_ids: set[str] = field(default_factory=set)
    latest_status_ts_ns: int = 0
    terminal_status: str | None = None
    commands: list[str] = field(default_factory=list)
    reservation_mutations: list[str] = field(default_factory=list)


def validate_submit_ack(ack: SubmitAck) -> ContractResult:
    if ack.response_kind in {"timeout", "exception"}:
        return ContractResult(fail_closed=True, reason=f"submit_{ack.response_kind}_is_not_ack")
    if ack.response_kind != "ack" or ack.venue_status not in OPEN_STATUSES:
        return ContractResult(fail_closed=True, reason="ambiguous_submit_is_not_ack")
    if not ack.client_order_id:
        return ContractResult(fail_closed=True, reason="missing_client_order_id")
    if not (ack.broker_order_id or ack.exchange_order_id):
        return ContractResult(fail_closed=True, reason="missing_broker_order_identity")
    if ack.requested_quantity is None or ack.requested_quantity <= Decimal("0"):
        return ContractResult(fail_closed=True, reason="missing_or_invalid_requested_quantity")
    if not ack.exchange_ts_ns or not ack.receive_ts_ns:
        return ContractResult(fail_closed=True, reason="missing_timestamp_evidence")
    if not ack.mapping_source:
        return ContractResult(fail_closed=True, reason="missing_mapping_source")
    return ContractResult(
        accepted=True,
        is_ack=True,
        opens_reservation=False,
        records_fill=False,
        terminal_truth=False,
        needs_reconciliation=True,
        route_to="order_router_mapping_only",
    )


def classify_reject(fact: RejectFact) -> ContractResult:
    if not fact.client_order_id or not fact.reject_reason:
        return ContractResult(fail_closed=True, reason="unknown_reject_semantics")
    if not fact.after_ack:
        return ContractResult(
            accepted=True,
            terminal_truth=True,
            opens_reservation=False,
            route_to="telemetry_rejection_only",
        )
    return ContractResult(
        fail_closed=True,
        reason="post_ack_reject_requires_terminal_reconciliation",
        needs_reconciliation=True,
    )


def classify_cancel(fact: CancelFact) -> ContractResult:
    if not fact.client_order_id or not fact.broker_order_id:
        return ContractResult(fail_closed=True, reason="missing_cancel_identity")
    if fact.cancel_status == "accepted":
        return ContractResult(
            accepted=True,
            terminal_truth=False,
            needs_reconciliation=True,
            route_to="status_reconciliation_required",
        )
    if fact.cancel_status == "already_filled":
        return ContractResult(
            accepted=True,
            terminal_truth=False,
            needs_reconciliation=True,
            route_to="fill_truth",
        )
    return ContractResult(fail_closed=True, reason=f"cancel_{fact.cancel_status}_not_terminal_truth")


def classify_status(fact: StatusFact, ledger: ContractLedger) -> ContractResult:
    if not fact.client_order_id or not fact.broker_order_id:
        return ContractResult(fail_closed=True, reason="missing_status_identity")
    if not fact.exchange_ts_ns or not fact.receive_ts_ns:
        return ContractResult(fail_closed=True, reason="missing_status_timestamp")
    if fact.exchange_ts_ns < ledger.latest_status_ts_ns:
        return ContractResult(fail_closed=True, reason="stale_status_cannot_overwrite_newer_truth")
    if ledger.terminal_status and fact.status not in TERMINAL_STATUSES:
        return ContractResult(fail_closed=True, reason="non_terminal_status_cannot_overwrite_terminal_truth")
    if fact.status in {"unknown", "not_found", "stale"}:
        return ContractResult(fail_closed=True, reason=f"{fact.status}_is_not_terminal_success")

    ledger.latest_status_ts_ns = fact.exchange_ts_ns
    if fact.status in TERMINAL_STATUSES:
        ledger.terminal_status = fact.status
        return ContractResult(
            accepted=True,
            terminal_truth=True,
            mutation_allowed=False,
            route_to="terminal_mapping_policy_review",
        )
    return ContractResult(accepted=True, terminal_truth=False, route_to="open_status_evidence")


def fill_idempotency_key(fill: FillFact) -> str | None:
    if fill.venue_fill_id:
        return f"{fill.client_order_id}:{fill.broker_order_id}:{fill.venue_fill_id}"
    if fill.client_order_id and fill.broker_order_id and fill.exchange_ts_ns and fill.fill_quantity and fill.fill_price:
        return (
            f"{fill.client_order_id}:{fill.broker_order_id}:"
            f"{fill.exchange_ts_ns}:{fill.fill_quantity}:{fill.fill_price}"
        )
    return None


def validate_fill(fill: FillFact, ledger: ContractLedger) -> ContractResult:
    if not fill.client_order_id or not fill.broker_order_id:
        return ContractResult(fail_closed=True, reason="missing_fill_order_identity")
    key = fill_idempotency_key(fill)
    if not key:
        return ContractResult(fail_closed=True, reason="missing_fill_identity")
    if fill.fill_quantity is None or fill.fill_quantity <= Decimal("0"):
        return ContractResult(fail_closed=True, reason="missing_or_invalid_fill_quantity")
    if fill.fill_price is None or fill.fill_price <= Decimal("0"):
        return ContractResult(fail_closed=True, reason="missing_or_invalid_fill_price")
    if fill.fee is None or fill.fee_currency is None:
        return ContractResult(fail_closed=True, reason="missing_fee_evidence")
    if not fill.exchange_ts_ns or not fill.receive_ts_ns:
        return ContractResult(fail_closed=True, reason="missing_fill_timestamp")
    if fill.cumulative_filled_quantity is None and fill.remaining_quantity is None:
        return ContractResult(fail_closed=True, reason="cumulative_vs_incremental_ambiguous")
    if key in ledger.fill_ids:
        return ContractResult(accepted=True, reason="duplicate_fill_idempotent", records_fill=False)

    ledger.fill_ids.add(key)
    terminal = fill.remaining_quantity == Decimal("0")
    return ContractResult(
        accepted=True,
        records_fill=True,
        terminal_truth=terminal,
        route_to="fill_recorder_passive_evidence",
    )


def validate_reconciliation_snapshot(snapshot: ReconciliationSnapshot) -> ContractResult:
    if not snapshot.source or not snapshot.snapshot_ts_ns:
        return ContractResult(fail_closed=True, reason="missing_reconciliation_source_or_timestamp")
    if not snapshot.account_id:
        return ContractResult(fail_closed=True, reason="missing_account_identity")
    return ContractResult(
        accepted=True,
        needs_reconciliation=True,
        route_to="read_only_reconciliation_contract",
        side_effects=(),
    )


def economics_payload(fill: FillFact, *, strategy: str, sleeve: str) -> dict[str, Any]:
    return {
        "actual_fill_price": fill.fill_price,
        "actual_fill_quantity": fill.fill_quantity,
        "actual_fee": fill.fee,
        "fee_currency": fill.fee_currency,
        "venue_fill_id": fill.venue_fill_id,
        "exchange_ts_ns": fill.exchange_ts_ns,
        "receive_ts_ns": fill.receive_ts_ns,
        "client_order_id": fill.client_order_id,
        "strategy": strategy,
        "sleeve": sleeve,
        "paper_mode": False,
        "liquidity": fill.liquidity,
        "slippage_bps": None,
        "net_edge": None,
        "net_pnl": None,
    }


def live_submit_gate(*, armed: bool | None, kill_switch: KillSwitch, timestamp_ns: int) -> ContractResult:
    if armed is not True:
        return ContractResult(fail_closed=True, reason="live_adapter_disarmed")
    if not kill_switch.can_trade(timestamp_ns):
        return ContractResult(fail_closed=True, reason="kill_switch_blocks_submit")
    return ContractResult(accepted=True, route_to="future_order_router_only")


def test_submit_ack_contract_accepts_only_identity_complete_open_ack():
    valid_ack = SubmitAck(
        client_order_id="client-1",
        broker_order_id="broker-1",
        exchange_order_id="venue-1",
        symbol="ETH/USD",
        side="buy",
        requested_quantity=Decimal("0.01"),
        order_type="limit",
        limit_price=Decimal("2500.00"),
        venue_status="accepted",
        exchange_ts_ns=T0_NS,
        receive_ts_ns=T0_NS + 10,
        mapping_source="mock_adapter.ack",
    )

    result = validate_submit_ack(valid_ack)

    assert result.accepted is True
    assert result.is_ack is True
    assert result.opens_reservation is False
    assert result.records_fill is False
    assert result.terminal_truth is False
    assert result.needs_reconciliation is True
    assert validate_submit_ack(valid_ack.__class__(**{**valid_ack.__dict__, "broker_order_id": None, "exchange_order_id": None})).reason == "missing_broker_order_identity"
    assert validate_submit_ack(valid_ack.__class__(**{**valid_ack.__dict__, "client_order_id": None})).reason == "missing_client_order_id"
    assert validate_submit_ack(valid_ack.__class__(**{**valid_ack.__dict__, "response_kind": "timeout"})).reason == "submit_timeout_is_not_ack"
    assert validate_submit_ack(valid_ack.__class__(**{**valid_ack.__dict__, "response_kind": "exception"})).reason == "submit_exception_is_not_ack"
    assert validate_submit_ack(valid_ack.__class__(**{**valid_ack.__dict__, "venue_status": "unknown"})).reason == "ambiguous_submit_is_not_ack"


def test_reject_contract_separates_pre_ack_from_post_ack_reconciliation():
    pre_ack = classify_reject(
        RejectFact(
            client_order_id="client-1",
            broker_order_id=None,
            reject_reason="min_notional",
            after_ack=False,
            venue_status="rejected",
            exchange_ts_ns=T0_NS,
            receive_ts_ns=T0_NS + 10,
        )
    )
    post_ack = classify_reject(
        RejectFact(
            client_order_id="client-1",
            broker_order_id="broker-1",
            reject_reason="exchange_reject_after_ack",
            after_ack=True,
            venue_status="rejected",
            exchange_ts_ns=T0_NS + 20,
            receive_ts_ns=T0_NS + 30,
        )
    )

    assert pre_ack.accepted is True
    assert pre_ack.opens_reservation is False
    assert pre_ack.route_to == "telemetry_rejection_only"
    assert post_ack.fail_closed is True
    assert post_ack.needs_reconciliation is True
    assert post_ack.reason == "post_ack_reject_requires_terminal_reconciliation"
    assert classify_reject(
        RejectFact(None, None, None, False, "rejected", T0_NS, T0_NS + 1)
    ).reason == "unknown_reject_semantics"


def test_cancel_contract_does_not_treat_cancel_acceptance_as_terminal_truth():
    accepted = classify_cancel(CancelFact("client-1", "broker-1", "accepted", T0_NS, T0_NS + 1))
    rejected = classify_cancel(CancelFact("client-1", "broker-1", "rejected", T0_NS, T0_NS + 1))
    already_filled = classify_cancel(
        CancelFact("client-1", "broker-1", "already_filled", T0_NS, T0_NS + 1)
    )
    unknown = classify_cancel(CancelFact("client-1", "broker-1", "unknown", T0_NS, T0_NS + 1))

    assert accepted.accepted is True
    assert accepted.terminal_truth is False
    assert accepted.needs_reconciliation is True
    assert accepted.route_to == "status_reconciliation_required"
    assert rejected.fail_closed is True
    assert unknown.fail_closed is True
    assert already_filled.route_to == "fill_truth"
    assert already_filled.terminal_truth is False


def test_status_contract_preserves_identity_timestamp_and_refuses_stale_overwrite():
    ledger = ContractLedger()

    open_result = classify_status(
        StatusFact("client-1", "broker-1", "open", "mock_status", T0_NS, T0_NS + 1),
        ledger,
    )
    terminal_result = classify_status(
        StatusFact("client-1", "broker-1", "filled", "mock_status", T0_NS + 20, T0_NS + 30),
        ledger,
    )
    stale_result = classify_status(
        StatusFact("client-1", "broker-1", "open", "mock_status", T0_NS + 10, T0_NS + 40),
        ledger,
    )
    unknown_result = classify_status(
        StatusFact("client-2", "broker-2", "not_found", "mock_status", T0_NS + 50, T0_NS + 60),
        ContractLedger(),
    )

    assert open_result.route_to == "open_status_evidence"
    assert terminal_result.terminal_truth is True
    assert terminal_result.mutation_allowed is False
    assert stale_result.fail_closed is True
    assert stale_result.reason == "stale_status_cannot_overwrite_newer_truth"
    assert unknown_result.reason == "not_found_is_not_terminal_success"


def test_fill_contract_requires_identity_money_fields_and_is_idempotent():
    ledger = ContractLedger()
    partial = FillFact(
        client_order_id="client-1",
        broker_order_id="broker-1",
        venue_fill_id="fill-1",
        symbol="ETH/USD",
        side="buy",
        fill_quantity=Decimal("0.25"),
        cumulative_filled_quantity=Decimal("0.25"),
        remaining_quantity=Decimal("0.75"),
        fill_price=Decimal("2500.50"),
        average_fill_price=Decimal("2500.50"),
        fee=Decimal("0.10"),
        fee_currency="USD",
        exchange_ts_ns=T0_NS,
        receive_ts_ns=T0_NS + 1,
        liquidity="maker",
    )
    full = partial.__class__(
        **{
            **partial.__dict__,
            "venue_fill_id": "fill-2",
            "fill_quantity": Decimal("0.75"),
            "cumulative_filled_quantity": Decimal("1.00"),
            "remaining_quantity": Decimal("0"),
        }
    )

    partial_result = validate_fill(partial, ledger)
    duplicate_result = validate_fill(partial, ledger)
    full_result = validate_fill(full, ledger)
    missing_identity = validate_fill(partial.__class__(**{**partial.__dict__, "venue_fill_id": None, "exchange_ts_ns": None}), ContractLedger())
    missing_price = validate_fill(partial.__class__(**{**partial.__dict__, "fill_price": None}), ContractLedger())
    ambiguous = validate_fill(
        partial.__class__(
            **{
                **partial.__dict__,
                "venue_fill_id": "fill-ambiguous",
                "cumulative_filled_quantity": None,
                "remaining_quantity": None,
            }
        ),
        ContractLedger(),
    )

    assert fill_idempotency_key(partial) == "client-1:broker-1:fill-1"
    assert partial_result.records_fill is True
    assert partial_result.terminal_truth is False
    assert duplicate_result.reason == "duplicate_fill_idempotent"
    assert duplicate_result.records_fill is False
    assert full_result.records_fill is True
    assert full_result.terminal_truth is True
    assert missing_identity.reason == "missing_fill_identity"
    assert missing_price.reason == "missing_or_invalid_fill_price"
    assert ambiguous.reason == "cumulative_vs_incremental_ambiguous"


def test_reconciliation_snapshot_contract_is_read_only_and_broker_truth_canonical():
    snapshot = ReconciliationSnapshot(
        open_orders=(
            StatusFact("client-1", "broker-1", "open", "mock_open_orders", T0_NS, T0_NS + 1),
        ),
        positions=({"symbol": "ETH/USD", "quantity": Decimal("0.25"), "source": "mock_positions"},),
        balances=({"currency": "USD", "cash": Decimal("100.00"), "source": "mock_balances"},),
        recent_fills=(),
        account_id="mock-account",
        source="mock_reconciliation_snapshot",
        snapshot_ts_ns=T0_NS + 2,
    )

    result = validate_reconciliation_snapshot(snapshot)

    assert result.accepted is True
    assert result.needs_reconciliation is True
    assert result.side_effects == ()
    assert result.route_to == "read_only_reconciliation_contract"
    assert validate_reconciliation_snapshot(snapshot.__class__(**{**snapshot.__dict__, "account_id": None})).reason == "missing_account_identity"


def test_economics_contract_represents_real_cost_fields_without_inventing_pnl_or_edge():
    fill = FillFact(
        client_order_id="client-1",
        broker_order_id="broker-1",
        venue_fill_id="fill-1",
        symbol="ETH/USD",
        side="buy",
        fill_quantity=Decimal("0.25"),
        cumulative_filled_quantity=Decimal("0.25"),
        remaining_quantity=Decimal("0.75"),
        fill_price=Decimal("2500.50"),
        average_fill_price=Decimal("2500.50"),
        fee=Decimal("0.10"),
        fee_currency="USD",
        exchange_ts_ns=T0_NS,
        receive_ts_ns=T0_NS + 1,
        liquidity="taker",
    )

    payload = economics_payload(fill, strategy="sector_rotation", sleeve="sector_rotation")

    assert payload["actual_fill_price"] == Decimal("2500.50")
    assert payload["actual_fill_quantity"] == Decimal("0.25")
    assert payload["actual_fee"] == Decimal("0.10")
    assert payload["fee_currency"] == "USD"
    assert payload["paper_mode"] is False
    assert payload["slippage_bps"] is None
    assert payload["net_edge"] is None
    assert payload["net_pnl"] is None


def test_kill_switch_and_arming_contract_block_submit_without_side_effects():
    kill_switch = KillSwitch()
    disarmed = live_submit_gate(armed=False, kill_switch=kill_switch, timestamp_ns=T0_NS)
    ambiguous = live_submit_gate(armed=None, kill_switch=kill_switch, timestamp_ns=T0_NS)

    kill_switch.trigger_manual("operator stop before live adapter submit", T0_NS + 1)
    killed = live_submit_gate(armed=True, kill_switch=kill_switch, timestamp_ns=T0_NS + 2)

    assert disarmed.fail_closed is True
    assert disarmed.reason == "live_adapter_disarmed"
    assert ambiguous.reason == "live_adapter_disarmed"
    assert killed.fail_closed is True
    assert killed.reason == "kill_switch_blocks_submit"
    assert killed.side_effects == ()


def test_config_contract_keeps_live_adapter_and_live_reservation_lifecycle_disarmed(tmp_path):
    config = Config()
    assert config.broker_mode == "paper"
    assert config.reservation_lifecycle_paper_enabled is False

    root = runtime_main.SovereignHeartbeat.__new__(runtime_main.SovereignHeartbeat)
    root.state_store = StateStore(str(tmp_path / "state.db"))
    root._bootstrap_reservation_lifecycle_disabled(
        SimpleNamespace(
            initial_capital=20_000.0,
            broker_mode="live",
            reservation_lifecycle_paper_enabled=True,
        )
    )

    assert root.reservation_lifecycle_enabled is False
    assert root.reservation_lifecycle_bootstrap_status["reservation_lifecycle_live_blocked"] is True
    assert root.reservation_lifecycle_bootstrap_status["reservation_lifecycle_scope"] == "disabled"

    broker_adapter_source = Path("app/execution/broker_adapter.py").read_text(encoding="utf-8-sig")
    live_broker_source = Path("app/execution/live_broker.py").read_text(encoding="utf-8-sig")
    assert "PRE-INTEGRATION" in broker_adapter_source
    assert "NO IMPLEMENTATION" in broker_adapter_source
    assert "Under construction" in live_broker_source
    assert "submit_order" not in live_broker_source
