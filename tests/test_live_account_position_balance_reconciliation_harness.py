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


@dataclass(frozen=True)
class ReconciliationDecision:
    ready: bool
    reason_codes: tuple[str, ...] = ()
    blocks_submit: bool = True
    operator_review_required: bool = False
    side_effects: tuple[str, ...] = ()
    canonical_source: str = "broker_truth"
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BalanceFact:
    currency: str | None
    total: Decimal | None
    available: Decimal | None
    held: Decimal | None = None
    source: str | None = "mock_balance"
    snapshot_ts_ns: int | None = T0_NS


@dataclass(frozen=True)
class PositionFact:
    symbol: str | None
    instrument_id: str | None
    quantity: Decimal | None
    source: str | None = "mock_position"
    snapshot_ts_ns: int | None = T0_NS


@dataclass(frozen=True)
class OpenOrderFact:
    client_order_id: str | None
    broker_order_id: str | None
    symbol: str | None
    remaining_qty: Decimal | None
    status: str
    mapping_status: str = "mapped"
    source: str | None = "mock_open_orders"
    snapshot_ts_ns: int | None = T0_NS


@dataclass(frozen=True)
class FillFact:
    fill_idempotency_key: str | None
    client_order_id: str | None
    broker_order_id: str | None
    symbol: str | None
    quantity: Decimal | None
    fee: Decimal | None
    exchange_ts_ns: int | None
    source: str | None = "mock_recent_fills"


@dataclass(frozen=True)
class LocalReservationFact:
    reservation_id: str
    client_order_id: str
    symbol: str
    open_qty: Decimal
    filled_qty: Decimal = Decimal("0")
    is_terminal: bool = False
    tombstoned: bool = False


@dataclass(frozen=True)
class LocalState:
    exposures: dict[str, Decimal] = field(default_factory=dict)
    local_open_orders: tuple[str, ...] = ()
    reservations: tuple[LocalReservationFact, ...] = ()
    fill_telemetry: dict[str, FillFact] = field(default_factory=dict)
    reserved_cash: dict[str, Decimal] = field(default_factory=dict)
    latest_event_ts_ns: int = T0_NS
    operator_review_clear: bool = True


@dataclass(frozen=True)
class AccountSnapshot:
    account_id: str | None
    source: str | None
    receive_ts_ns: int | None
    asof_ts_ns: int | None
    environment: str | None
    base_currency: str | None
    balances: tuple[BalanceFact, ...]
    positions: tuple[PositionFact, ...]
    open_orders: tuple[OpenOrderFact, ...] = ()
    recent_fills: tuple[FillFact, ...] = ()


def _decision(reasons: list[str], details: dict[str, Any] | None = None) -> ReconciliationDecision:
    unique = tuple(dict.fromkeys(reasons))
    return ReconciliationDecision(
        ready=not unique,
        reason_codes=unique,
        blocks_submit=bool(unique),
        operator_review_required=bool(unique),
        side_effects=(),
        details=details or {},
    )


def _is_stale(ts_ns: int | None, current_ts_ns: int) -> bool:
    return ts_ns is None or ts_ns <= 0 or current_ts_ns - ts_ns > MAX_SNAPSHOT_AGE_NS


def validate_account_snapshot(snapshot: AccountSnapshot, *, current_ts_ns: int) -> ReconciliationDecision:
    reasons: list[str] = []
    if not snapshot.source or snapshot.receive_ts_ns is None:
        reasons.append("account_snapshot_missing")
    if _is_stale(snapshot.receive_ts_ns, current_ts_ns):
        reasons.append("account_snapshot_stale")
    if not snapshot.account_id:
        reasons.append("account_identity_ambiguous")
    if not snapshot.environment:
        reasons.append("broker_environment_missing")
    if not snapshot.base_currency:
        reasons.append("base_currency_missing")
    return _decision(reasons)


def reconcile_balances(
    snapshot: AccountSnapshot,
    local: LocalState,
    *,
    expected_currency: str = "USD",
    current_ts_ns: int = T0_NS,
) -> ReconciliationDecision:
    reasons = list(validate_account_snapshot(snapshot, current_ts_ns=current_ts_ns).reason_codes)
    balance = next((item for item in snapshot.balances if item.currency == expected_currency), None)
    if balance is None:
        reasons.append("balance_currency_mismatch")
        return _decision(reasons)
    if _is_stale(balance.snapshot_ts_ns, current_ts_ns):
        reasons.append("balance_snapshot_stale")
    if balance.currency != snapshot.base_currency:
        reasons.append("balance_currency_mismatch")
    if balance.total is None or balance.total < Decimal("0"):
        reasons.append("balance_negative_or_impossible")
    if balance.available is None:
        reasons.append("balance_available_missing")
    elif balance.available < Decimal("0"):
        reasons.append("balance_negative_or_impossible")
    elif balance.total is not None and balance.available > balance.total:
        reasons.append("balance_negative_or_impossible")

    local_reserved = local.reserved_cash.get(expected_currency, Decimal("0"))
    if balance.available is not None and local_reserved > Decimal("0") and balance.held is None:
        reasons.append("local_reservation_supporting_constraint_only")
    if balance.held is not None and local_reserved > Decimal("0"):
        effective_buying_power = balance.available
        double_counted = False
    else:
        effective_buying_power = (
            min(balance.available, max(Decimal("0"), balance.total - local_reserved))
            if balance.available is not None and balance.total is not None
            else None
        )
        double_counted = False

    return _decision(
        reasons,
        {
            "broker_available_balance_canonical": str(balance.available) if balance.available is not None else None,
            "local_reserved_cash_supporting": str(local_reserved),
            "effective_buying_power_not_invented": str(effective_buying_power) if effective_buying_power is not None else None,
            "double_counted_reserved_cash": double_counted,
        },
    )


def reconcile_positions(
    snapshot: AccountSnapshot,
    local: LocalState,
    *,
    current_ts_ns: int = T0_NS,
) -> ReconciliationDecision:
    reasons = list(validate_account_snapshot(snapshot, current_ts_ns=current_ts_ns).reason_codes)
    broker_symbols = set()
    for position in snapshot.positions:
        if _is_stale(position.snapshot_ts_ns, current_ts_ns):
            reasons.append("position_snapshot_stale")
        if not position.symbol or not position.instrument_id:
            reasons.append("instrument_mapping_unknown")
            continue
        if position.quantity is None:
            reasons.append("broker_position_unknown")
            continue
        broker_symbols.add(position.symbol)
        local_qty = local.exposures.get(position.symbol, Decimal("0"))
        if local_qty != position.quantity:
            reasons.append("position_mismatch")

    for symbol, local_qty in local.exposures.items():
        if symbol not in broker_symbols and local_qty != Decimal("0"):
            reasons.append("position_mismatch")

    return _decision(reasons, {"broker_position_truth_canonical": True})


def reconcile_open_orders(snapshot: AccountSnapshot, local: LocalState, *, current_ts_ns: int = T0_NS) -> ReconciliationDecision:
    reasons = list(validate_account_snapshot(snapshot, current_ts_ns=current_ts_ns).reason_codes)
    broker_client_ids = set()
    for order in snapshot.open_orders:
        if _is_stale(order.snapshot_ts_ns, current_ts_ns):
            reasons.append("open_order_snapshot_stale")
        if order.mapping_status != "mapped" or not order.client_order_id or not order.broker_order_id:
            reasons.append("open_order_orphan_broker")
            continue
        broker_client_ids.add(order.client_order_id)
        if order.client_order_id not in local.local_open_orders:
            reasons.append("open_order_orphan_broker")
        if order.status in {"open", "accepted", "partially_filled"}:
            terminal_reservation = next(
                (
                    reservation
                    for reservation in local.reservations
                    if reservation.client_order_id == order.client_order_id
                    and (reservation.is_terminal or reservation.tombstoned)
                ),
                None,
            )
            if terminal_reservation is not None:
                reasons.append("reservation_open_order_conflict")

    for local_order_id in local.local_open_orders:
        if local_order_id not in broker_client_ids:
            reasons.append("open_order_orphan_local")
    return _decision(reasons)


def reconcile_recent_fills(snapshot: AccountSnapshot, local: LocalState, *, current_ts_ns: int = T0_NS) -> ReconciliationDecision:
    reasons = list(validate_account_snapshot(snapshot, current_ts_ns=current_ts_ns).reason_codes)
    broker_fill_keys = set()
    for fill in snapshot.recent_fills:
        if not fill.fill_idempotency_key:
            reasons.append("fill_identity_missing")
            continue
        if _is_stale(fill.exchange_ts_ns, current_ts_ns):
            reasons.append("fill_snapshot_stale")
        broker_fill_keys.add(fill.fill_idempotency_key)
        local_fill = local.fill_telemetry.get(fill.fill_idempotency_key)
        if local_fill is None:
            reasons.append("broker_recent_fill_missing_local_telemetry")
            continue
        if local_fill.quantity != fill.quantity or local_fill.fee != fill.fee:
            reasons.append("fill_telemetry_mismatch")
        if local_fill.exchange_ts_ns != fill.exchange_ts_ns:
            reasons.append("fill_telemetry_mismatch")

    for local_key in local.fill_telemetry:
        if local_key not in broker_fill_keys:
            reasons.append("local_fill_missing_from_broker_snapshot")
    return _decision(reasons)


def reconcile_reservations(snapshot: AccountSnapshot, local: LocalState, *, current_ts_ns: int = T0_NS) -> ReconciliationDecision:
    reasons = list(validate_account_snapshot(snapshot, current_ts_ns=current_ts_ns).reason_codes)
    broker_open_ids = {order.client_order_id for order in snapshot.open_orders if order.client_order_id}
    active_reservation_ids = {
        reservation.client_order_id
        for reservation in local.reservations
        if not reservation.is_terminal and not reservation.tombstoned and reservation.open_qty > Decimal("0")
    }
    for reservation in local.reservations:
        if reservation.client_order_id in broker_open_ids and (reservation.is_terminal or reservation.tombstoned):
            reasons.append("reservation_open_order_conflict")
        if reservation.client_order_id not in broker_open_ids and reservation.client_order_id in active_reservation_ids:
            reasons.append("local_reservation_without_broker_support")
    for broker_order_id in broker_open_ids:
        if broker_order_id not in active_reservation_ids:
            reasons.append("broker_open_order_without_local_reservation")
    return _decision(reasons, {"live_reservation_lifecycle_enabled": False})


def evaluate_tiny_live_reconciliation_readiness(
    snapshot: AccountSnapshot,
    local: LocalState,
    *,
    current_ts_ns: int = T0_NS,
) -> ReconciliationDecision:
    reasons: list[str] = []
    for decision in (
        validate_account_snapshot(snapshot, current_ts_ns=current_ts_ns),
        reconcile_balances(snapshot, local, current_ts_ns=current_ts_ns),
        reconcile_positions(snapshot, local, current_ts_ns=current_ts_ns),
        reconcile_open_orders(snapshot, local, current_ts_ns=current_ts_ns),
        reconcile_recent_fills(snapshot, local, current_ts_ns=current_ts_ns),
        reconcile_reservations(snapshot, local, current_ts_ns=current_ts_ns),
    ):
        reasons.extend(decision.reason_codes)
    if not local.operator_review_clear:
        reasons.append("operator_review_required")
    return _decision(reasons, {"micro_live_reconciliation_prereq_clear": not reasons})


def _clean_snapshot() -> AccountSnapshot:
    return AccountSnapshot(
        account_id="mock-account-1",
        source="mock_broker_snapshot",
        receive_ts_ns=T0_NS,
        asof_ts_ns=T0_NS,
        environment="sandbox",
        base_currency="USD",
        balances=(
            BalanceFact("USD", Decimal("1000.00"), Decimal("950.00"), Decimal("50.00")),
        ),
        positions=(
            PositionFact("ETH/USD", "eth-usd", Decimal("0.25")),
        ),
        open_orders=(),
        recent_fills=(),
    )


def _clean_local() -> LocalState:
    return LocalState(
        exposures={"ETH/USD": Decimal("0.25")},
        local_open_orders=(),
        reservations=(),
        fill_telemetry={},
        reserved_cash={"USD": Decimal("0")},
        latest_event_ts_ns=T0_NS,
        operator_review_clear=True,
    )


def _fill(key: str = "fill-1", *, qty: Decimal = Decimal("0.25"), fee: Decimal = Decimal("0.10")) -> FillFact:
    return FillFact(
        fill_idempotency_key=key,
        client_order_id="client-1",
        broker_order_id="broker-1",
        symbol="ETH/USD",
        quantity=qty,
        fee=fee,
        exchange_ts_ns=T0_NS,
    )


def test_account_snapshot_identity_requires_source_timestamp_and_account_id():
    clean = validate_account_snapshot(_clean_snapshot(), current_ts_ns=T0_NS + 1)
    missing = validate_account_snapshot(
        _clean_snapshot().__class__(
            **{**_clean_snapshot().__dict__, "account_id": None, "source": None, "receive_ts_ns": None}
        ),
        current_ts_ns=T0_NS + 1,
    )
    stale = validate_account_snapshot(_clean_snapshot(), current_ts_ns=T0_NS + MAX_SNAPSHOT_AGE_NS + 1)

    assert clean.ready is True
    assert missing.ready is False
    assert "account_snapshot_missing" in missing.reason_codes
    assert "account_identity_ambiguous" in missing.reason_codes
    assert "account_snapshot_stale" in missing.reason_codes
    assert stale.reason_codes == ("account_snapshot_stale",)
    assert missing.side_effects == ()


def test_balance_reconciliation_uses_broker_available_without_double_counting_local_reserve():
    local = LocalState(reserved_cash={"USD": Decimal("100")})
    with_held = _clean_snapshot().__class__(
        **{
            **_clean_snapshot().__dict__,
            "balances": (BalanceFact("USD", Decimal("1000"), Decimal("900"), Decimal("100")),),
        }
    )
    no_held = _clean_snapshot().__class__(
        **{
            **_clean_snapshot().__dict__,
            "balances": (BalanceFact("USD", Decimal("1000"), Decimal("950"), None),),
        }
    )

    held_result = reconcile_balances(with_held, local, current_ts_ns=T0_NS + 1)
    no_held_result = reconcile_balances(no_held, local, current_ts_ns=T0_NS + 1)
    missing_available = reconcile_balances(
        _clean_snapshot().__class__(
            **{**_clean_snapshot().__dict__, "balances": (BalanceFact("USD", Decimal("1000"), None),)}
        ),
        local,
        current_ts_ns=T0_NS + 1,
    )
    impossible = reconcile_balances(
        _clean_snapshot().__class__(
            **{**_clean_snapshot().__dict__, "balances": (BalanceFact("USD", Decimal("100"), Decimal("101")),)}
        ),
        local,
        current_ts_ns=T0_NS + 1,
    )
    mismatch = reconcile_balances(
        _clean_snapshot().__class__(
            **{**_clean_snapshot().__dict__, "balances": (BalanceFact("EUR", Decimal("100"), Decimal("100")),)}
        ),
        local,
        current_ts_ns=T0_NS + 1,
    )

    assert held_result.ready is True
    assert held_result.details["double_counted_reserved_cash"] is False
    assert no_held_result.ready is False
    assert "local_reservation_supporting_constraint_only" in no_held_result.reason_codes
    assert missing_available.reason_codes == ("balance_available_missing",)
    assert "balance_negative_or_impossible" in impossible.reason_codes
    assert "balance_currency_mismatch" in mismatch.reason_codes


def test_position_reconciliation_treats_broker_position_as_canonical():
    clean = reconcile_positions(_clean_snapshot(), _clean_local(), current_ts_ns=T0_NS + 1)
    broker_position_local_flat = reconcile_positions(_clean_snapshot(), LocalState(), current_ts_ns=T0_NS + 1)
    broker_flat_local_position = reconcile_positions(
        _clean_snapshot().__class__(
            **{**_clean_snapshot().__dict__, "positions": (PositionFact("ETH/USD", "eth-usd", Decimal("0")),)}
        ),
        _clean_local(),
        current_ts_ns=T0_NS + 1,
    )
    unknown_instrument = reconcile_positions(
        _clean_snapshot().__class__(
            **{**_clean_snapshot().__dict__, "positions": (PositionFact("ETH/USD", None, Decimal("0.25")),)}
        ),
        _clean_local(),
        current_ts_ns=T0_NS + 1,
    )
    unknown_qty = reconcile_positions(
        _clean_snapshot().__class__(
            **{**_clean_snapshot().__dict__, "positions": (PositionFact("ETH/USD", "eth-usd", None),)}
        ),
        _clean_local(),
        current_ts_ns=T0_NS + 1,
    )

    assert clean.ready is True
    assert clean.details["broker_position_truth_canonical"] is True
    assert "position_mismatch" in broker_position_local_flat.reason_codes
    assert "position_mismatch" in broker_flat_local_position.reason_codes
    assert "instrument_mapping_unknown" in unknown_instrument.reason_codes
    assert "broker_position_unknown" in unknown_qty.reason_codes


def test_open_order_reconciliation_classifies_broker_and_local_orphans_without_canceling():
    mapped = OpenOrderFact("client-1", "broker-1", "ETH/USD", Decimal("1"), "open")
    broker_orphan = OpenOrderFact(None, "broker-orphan", "ETH/USD", Decimal("1"), "open", "broker_orphan")
    local = LocalState(local_open_orders=("client-1",), reservations=(LocalReservationFact("r1", "client-1", "ETH/USD", Decimal("1")),))
    clean = reconcile_open_orders(
        _clean_snapshot().__class__(**{**_clean_snapshot().__dict__, "open_orders": (mapped,)}),
        local,
        current_ts_ns=T0_NS + 1,
    )
    broker_orphan_result = reconcile_open_orders(
        _clean_snapshot().__class__(**{**_clean_snapshot().__dict__, "open_orders": (broker_orphan,)}),
        LocalState(),
        current_ts_ns=T0_NS + 1,
    )
    local_orphan_result = reconcile_open_orders(_clean_snapshot(), local, current_ts_ns=T0_NS + 1)
    terminal_conflict = reconcile_open_orders(
        _clean_snapshot().__class__(**{**_clean_snapshot().__dict__, "open_orders": (mapped,)}),
        LocalState(local_open_orders=("client-1",), reservations=(LocalReservationFact("r1", "client-1", "ETH/USD", Decimal("0"), is_terminal=True),)),
        current_ts_ns=T0_NS + 1,
    )

    assert clean.ready is True
    assert "open_order_orphan_broker" in broker_orphan_result.reason_codes
    assert "open_order_orphan_local" in local_orphan_result.reason_codes
    assert "reservation_open_order_conflict" in terminal_conflict.reason_codes
    assert terminal_conflict.side_effects == ()


def test_recent_fill_telemetry_reconciliation_detects_missing_and_mismatched_truth():
    fill = _fill()
    clean = reconcile_recent_fills(
        _clean_snapshot().__class__(**{**_clean_snapshot().__dict__, "recent_fills": (fill,)}),
        LocalState(fill_telemetry={"fill-1": fill}),
        current_ts_ns=T0_NS + 1,
    )
    missing_local = reconcile_recent_fills(
        _clean_snapshot().__class__(**{**_clean_snapshot().__dict__, "recent_fills": (fill,)}),
        LocalState(),
        current_ts_ns=T0_NS + 1,
    )
    mismatched = reconcile_recent_fills(
        _clean_snapshot().__class__(**{**_clean_snapshot().__dict__, "recent_fills": (fill,)}),
        LocalState(fill_telemetry={"fill-1": _fill(qty=Decimal("0.20"))}),
        current_ts_ns=T0_NS + 1,
    )
    local_missing_broker = reconcile_recent_fills(
        _clean_snapshot(),
        LocalState(fill_telemetry={"fill-1": fill}),
        current_ts_ns=T0_NS + 1,
    )

    assert clean.ready is True
    assert "broker_recent_fill_missing_local_telemetry" in missing_local.reason_codes
    assert "fill_telemetry_mismatch" in mismatched.reason_codes
    assert "local_fill_missing_from_broker_snapshot" in local_missing_broker.reason_codes


def test_exposure_reservation_reconciliation_keeps_live_lifecycle_disabled(tmp_path):
    root = runtime_main.SovereignHeartbeat.__new__(runtime_main.SovereignHeartbeat)
    root.state_store = StateStore(str(tmp_path / "state.db"))
    root._bootstrap_reservation_lifecycle_disabled(
        SimpleNamespace(
            initial_capital=20_000.0,
            broker_mode="live",
            reservation_lifecycle_paper_enabled=True,
        )
    )
    mapped_open = OpenOrderFact("client-1", "broker-1", "ETH/USD", Decimal("1"), "open")
    active_reservation = LocalReservationFact("r1", "client-1", "ETH/USD", Decimal("1"))
    terminal_reservation = LocalReservationFact("r2", "client-1", "ETH/USD", Decimal("0"), is_terminal=True, tombstoned=True)

    clean = reconcile_reservations(
        _clean_snapshot().__class__(**{**_clean_snapshot().__dict__, "open_orders": (mapped_open,)}),
        LocalState(reservations=(active_reservation,)),
        current_ts_ns=T0_NS + 1,
    )
    local_without_broker = reconcile_reservations(_clean_snapshot(), LocalState(reservations=(active_reservation,)), current_ts_ns=T0_NS + 1)
    broker_without_local = reconcile_reservations(
        _clean_snapshot().__class__(**{**_clean_snapshot().__dict__, "open_orders": (mapped_open,)}),
        LocalState(),
        current_ts_ns=T0_NS + 1,
    )
    tombstone_conflict = reconcile_reservations(
        _clean_snapshot().__class__(**{**_clean_snapshot().__dict__, "open_orders": (mapped_open,)}),
        LocalState(reservations=(terminal_reservation,)),
        current_ts_ns=T0_NS + 1,
    )

    assert root.reservation_lifecycle_enabled is False
    assert root.reservation_lifecycle_bootstrap_status["reservation_lifecycle_live_blocked"] is True
    assert clean.ready is True
    assert clean.details["live_reservation_lifecycle_enabled"] is False
    assert "local_reservation_without_broker_support" in local_without_broker.reason_codes
    assert "broker_open_order_without_local_reservation" in broker_without_local.reason_codes
    assert "reservation_open_order_conflict" in tombstone_conflict.reason_codes


def test_snapshot_freshness_and_ordering_block_readiness():
    stale_balance = reconcile_balances(
        _clean_snapshot().__class__(
            **{
                **_clean_snapshot().__dict__,
                "balances": (BalanceFact("USD", Decimal("100"), Decimal("90"), snapshot_ts_ns=T0_NS - MAX_SNAPSHOT_AGE_NS - 1),),
            }
        ),
        _clean_local(),
        current_ts_ns=T0_NS,
    )
    stale_position = reconcile_positions(
        _clean_snapshot().__class__(
            **{
                **_clean_snapshot().__dict__,
                "positions": (PositionFact("ETH/USD", "eth-usd", Decimal("0.25"), snapshot_ts_ns=T0_NS - MAX_SNAPSHOT_AGE_NS - 1),),
            }
        ),
        _clean_local(),
        current_ts_ns=T0_NS,
    )
    stale_order = reconcile_open_orders(
        _clean_snapshot().__class__(
            **{
                **_clean_snapshot().__dict__,
                "open_orders": (OpenOrderFact("client-1", "broker-1", "ETH/USD", Decimal("1"), "open", snapshot_ts_ns=T0_NS - MAX_SNAPSHOT_AGE_NS - 1),),
            }
        ),
        LocalState(local_open_orders=("client-1",), reservations=(LocalReservationFact("r1", "client-1", "ETH/USD", Decimal("1")),)),
        current_ts_ns=T0_NS,
    )

    assert "balance_snapshot_stale" in stale_balance.reason_codes
    assert "position_snapshot_stale" in stale_position.reason_codes
    assert "open_order_snapshot_stale" in stale_order.reason_codes


def test_operator_no_go_reason_codes_and_tiny_live_readiness_implication():
    clean = evaluate_tiny_live_reconciliation_readiness(_clean_snapshot(), _clean_local(), current_ts_ns=T0_NS + 1)
    operator_blocked = evaluate_tiny_live_reconciliation_readiness(
        _clean_snapshot(),
        LocalState(exposures={"ETH/USD": Decimal("0.25")}, operator_review_clear=False),
        current_ts_ns=T0_NS + 1,
    )
    compound_blocked = evaluate_tiny_live_reconciliation_readiness(
        _clean_snapshot().__class__(
            **{
                **_clean_snapshot().__dict__,
                "account_id": None,
                "balances": (BalanceFact("USD", Decimal("100"), None),),
                "positions": (PositionFact("ETH/USD", None, Decimal("0.25")),),
                "open_orders": (OpenOrderFact(None, "broker-orphan", "ETH/USD", Decimal("1"), "open", "broker_orphan"),),
                "recent_fills": (_fill(),),
            }
        ),
        LocalState(exposures={"ETH/USD": Decimal("0.10")}),
        current_ts_ns=T0_NS + 1,
    )

    assert clean.ready is True
    assert clean.details["micro_live_reconciliation_prereq_clear"] is True
    assert operator_blocked.reason_codes == ("operator_review_required",)
    expected = {
        "account_identity_ambiguous",
        "balance_available_missing",
        "instrument_mapping_unknown",
        "position_mismatch",
        "open_order_orphan_broker",
        "broker_recent_fill_missing_local_telemetry",
    }
    assert expected.issubset(set(compound_blocked.reason_codes))
    assert compound_blocked.blocks_submit is True
    assert compound_blocked.side_effects == ()


def test_broker_adapter_live_broker_remain_inactive_contract_evidence_only():
    broker_adapter_source = Path("app/execution/broker_adapter.py").read_text(encoding="utf-8-sig")
    live_broker_source = Path("app/execution/live_broker.py").read_text(encoding="utf-8-sig")

    assert "PRE-INTEGRATION" in broker_adapter_source
    assert "NO IMPLEMENTATION" in broker_adapter_source
    assert "Under construction" in live_broker_source
    assert "submit_order" not in live_broker_source
    assert "cancel_order" not in live_broker_source
