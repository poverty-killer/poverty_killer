from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import main as runtime_main
from app.state.state_store import StateStore


T0_NS = 1_777_948_800_000_000_000
LIVE_DECISION_UUID = "live-fill-truth-decision"


@dataclass(frozen=True)
class FillDecision:
    accepted: bool = False
    fail_closed: bool = False
    reason_code: str = ""
    partial_fill: bool = False
    full_fill: bool = False
    duplicate: bool = False
    telemetry_payload: dict[str, Any] | None = None
    reservation_candidate: dict[str, Any] | None = None
    needs_reconciliation: bool = False
    side_effects: tuple[str, ...] = ()


@dataclass(frozen=True)
class LiveFillEvidence:
    client_order_id: str | None
    broker_order_id: str | None
    exchange_order_id: str | None
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
    source: str | None
    liquidity: str | None = None
    quantity_semantics: str | None = "incremental"
    decision_uuid: str | None = LIVE_DECISION_UUID
    order_intent_id: str | None = "live-fill-client-order"
    strategy: str | None = "sector_rotation"
    sleeve: str | None = "sector_rotation"


@dataclass(frozen=True)
class BrokerTradeSnapshot:
    recent_fills: tuple[LiveFillEvidence, ...]
    source: str | None
    snapshot_ts_ns: int | None


@dataclass
class FillLedger:
    client_order_id: str = "live-fill-client-order"
    broker_order_id: str = "broker-order-1"
    symbol: str = "ETH/USD"
    side: str = "buy"
    requested_qty: Decimal = Decimal("1.00")
    prior_cumulative_qty: Decimal = Decimal("0")
    latest_exchange_ts_ns: int = 0
    terminal_full_fill: bool = False
    fill_keys: set[str] = field(default_factory=set)
    telemetry_event_ids: set[str] = field(default_factory=set)
    reservation_candidate_keys: set[str] = field(default_factory=set)


def _fill(
    *,
    venue_fill_id: str | None = "venue-fill-1",
    fill_qty: Decimal | None = Decimal("0.25"),
    cumulative_filled_qty: Decimal | None = Decimal("0.25"),
    remaining_qty: Decimal | None = Decimal("0.75"),
    fill_price: Decimal | None = Decimal("2500.50"),
    avg_fill_price: Decimal | None = Decimal("2500.50"),
    fee: Decimal | None = Decimal("0.10"),
    fee_currency: str | None = "USD",
    exchange_ts_ns: int | None = T0_NS,
    receive_ts_ns: int | None = T0_NS + 1,
    status: str = "partially_filled",
    client_order_id: str | None = "live-fill-client-order",
    broker_order_id: str | None = "broker-order-1",
    exchange_order_id: str | None = "exchange-order-1",
    symbol: str = "ETH/USD",
    side: str = "buy",
    requested_qty: Decimal | None = Decimal("1.00"),
    source: str | None = "mock_live_fill",
    quantity_semantics: str | None = "incremental",
    liquidity: str | None = "maker",
    decision_uuid: str | None = LIVE_DECISION_UUID,
    order_intent_id: str | None = "live-fill-client-order",
) -> LiveFillEvidence:
    return LiveFillEvidence(
        client_order_id=client_order_id,
        broker_order_id=broker_order_id,
        exchange_order_id=exchange_order_id,
        venue_fill_id=venue_fill_id,
        symbol=symbol,
        side=side,
        requested_qty=requested_qty,
        fill_qty=fill_qty,
        cumulative_filled_qty=cumulative_filled_qty,
        remaining_qty=remaining_qty,
        fill_price=fill_price,
        avg_fill_price=avg_fill_price,
        fee=fee,
        fee_currency=fee_currency,
        exchange_ts_ns=exchange_ts_ns,
        receive_ts_ns=receive_ts_ns,
        status=status,
        source=source,
        liquidity=liquidity,
        quantity_semantics=quantity_semantics,
        decision_uuid=decision_uuid,
        order_intent_id=order_intent_id,
    )


def fill_idempotency_key(fill: LiveFillEvidence) -> str | None:
    if fill.client_order_id and fill.broker_order_id and fill.venue_fill_id:
        return f"{fill.client_order_id}:{fill.broker_order_id}:{fill.venue_fill_id}"
    if (
        fill.client_order_id
        and fill.broker_order_id
        and fill.exchange_ts_ns
        and fill.fill_qty
        and fill.fill_price
        and fill.fee is not None
        and fill.source
    ):
        return (
            f"{fill.client_order_id}:{fill.broker_order_id}:{fill.exchange_ts_ns}:"
            f"{fill.fill_qty}:{fill.fill_price}:{fill.fee}:{fill.source}"
        )
    return None


def _validate_identity(fill: LiveFillEvidence, ledger: FillLedger) -> str | None:
    if not fill.client_order_id or not fill.broker_order_id:
        return "missing_order_identity"
    if not fill.exchange_order_id:
        return "missing_exchange_order_identity"
    if fill.client_order_id != ledger.client_order_id or fill.broker_order_id != ledger.broker_order_id:
        return "order_mapping_mismatch"
    if fill.symbol != ledger.symbol or fill.side != ledger.side:
        return "symbol_or_side_mapping_mismatch"
    if fill.requested_qty != ledger.requested_qty:
        return "requested_quantity_mapping_mismatch"
    if not fill_idempotency_key(fill):
        return "missing_fill_identity"
    return None


def _validate_quantity(fill: LiveFillEvidence, ledger: FillLedger) -> str | None:
    if fill.quantity_semantics not in {"incremental", "cumulative"}:
        return "quantity_semantics_ambiguous"
    if fill.fill_qty is None or fill.fill_qty <= Decimal("0"):
        return "invalid_fill_quantity"
    if fill.cumulative_filled_qty is None and fill.remaining_qty is None:
        return "cumulative_remaining_ambiguity"
    cumulative = fill.cumulative_filled_qty
    remaining = fill.remaining_qty
    if cumulative is not None:
        if cumulative < ledger.prior_cumulative_qty:
            return "cumulative_regression"
        if cumulative > ledger.requested_qty:
            return "overfill"
    if remaining is not None and remaining < Decimal("0"):
        return "negative_remaining_quantity"
    if cumulative is not None and remaining is not None:
        if cumulative + remaining != ledger.requested_qty:
            return "quantity_balance_mismatch"
    return None


def _validate_price_fee_time(fill: LiveFillEvidence, ledger: FillLedger) -> str | None:
    if fill.fill_price is None or fill.fill_price <= Decimal("0"):
        return "invalid_fill_price"
    if fill.fee is None:
        return "missing_fee_gap"
    if fill.fee_currency is None:
        return "missing_fee_currency_gap"
    if fill.fee < Decimal("0"):
        return "negative_fee"
    if fill.receive_ts_ns is None:
        return "missing_receive_timestamp"
    if fill.exchange_ts_ns is None:
        return "missing_exchange_timestamp_gap"
    if fill.receive_ts_ns < fill.exchange_ts_ns:
        return "receive_before_exchange_timestamp"
    if fill.exchange_ts_ns < ledger.latest_exchange_ts_ns:
        return "stale_fill_requires_reconciliation"
    if (
        ledger.terminal_full_fill
        and fill_idempotency_key(fill) not in ledger.fill_keys
        and fill.exchange_ts_ns >= ledger.latest_exchange_ts_ns
    ):
        return "fill_after_terminal_requires_reconciliation"
    return None


def build_telemetry_payload(fill: LiveFillEvidence, key: str) -> dict[str, Any]:
    return {
        "decision_uuid": fill.decision_uuid,
        "order_intent_id": fill.order_intent_id,
        "client_order_id": fill.client_order_id,
        "broker_order_id": fill.broker_order_id,
        "exchange_order_id": fill.exchange_order_id,
        "execution_event_id": f"live_fill:{key}",
        "symbol": fill.symbol,
        "side": fill.side,
        "requested_qty": str(fill.requested_qty),
        "filled_qty": str(fill.fill_qty),
        "cumulative_filled_qty": str(fill.cumulative_filled_qty),
        "remaining_qty": str(fill.remaining_qty),
        "fill_price": str(fill.fill_price),
        "avg_fill_price": str(fill.avg_fill_price) if fill.avg_fill_price is not None else None,
        "fee": str(fill.fee),
        "fee_currency": fill.fee_currency,
        "venue_fill_id": fill.venue_fill_id,
        "exchange_timestamp_ns": fill.exchange_ts_ns,
        "receive_timestamp_ns": fill.receive_ts_ns,
        "liquidity": fill.liquidity,
        "status_source": fill.source,
        "mapping_source": "live_fill_contract_mapping",
        "paper_mode": False,
        "slippage_bps": None,
        "net_edge": None,
        "net_pnl": None,
        "profitability": None,
        "production_record_written": False,
    }


def build_reservation_candidate(fill: LiveFillEvidence, key: str, *, full_fill: bool) -> dict[str, Any]:
    return {
        "candidate_type": "release" if full_fill else "fill_progress",
        "client_order_id": fill.client_order_id,
        "broker_order_id": fill.broker_order_id,
        "fill_idempotency_key": key,
        "release_idempotency_key": f"{key}:release" if full_fill else None,
        "fill_delta_qty": str(fill.fill_qty),
        "cumulative_filled_qty": str(fill.cumulative_filled_qty),
        "remaining_qty": str(fill.remaining_qty),
        "price_basis": str(fill.fill_price),
        "status_source": fill.source,
        "terminal_state": "filled" if full_fill else None,
        "reservation_authority": False,
        "reservation_mutation_performed": False,
        "reservation_release_performed": False,
        "live_reservation_lifecycle_enabled": False,
    }


def classify_fill(fill: LiveFillEvidence, ledger: FillLedger) -> FillDecision:
    for validator in (_validate_identity, _validate_quantity, _validate_price_fee_time):
        reason = validator(fill, ledger)
        if reason:
            return FillDecision(fail_closed=True, reason_code=reason)

    key = str(fill_idempotency_key(fill))
    if key in ledger.fill_keys:
        return FillDecision(accepted=True, duplicate=True, reason_code="duplicate_fill_idempotent")

    complete_full_quantity = (
        fill.cumulative_filled_qty == ledger.requested_qty and fill.remaining_qty == Decimal("0")
    )
    if complete_full_quantity and fill.status not in {"filled", "closed"}:
        payload = build_telemetry_payload(fill, key)
        candidate = build_reservation_candidate(fill, key, full_fill=False)
        ledger.fill_keys.add(key)
        ledger.telemetry_event_ids.add(payload["execution_event_id"])
        return FillDecision(
            accepted=True,
            reason_code="complete_quantity_status_unknown_requires_reconciliation",
            telemetry_payload=payload,
            reservation_candidate=candidate,
            needs_reconciliation=True,
        )

    full_fill = complete_full_quantity and fill.status in {"filled", "closed"}
    payload = build_telemetry_payload(fill, key)
    candidate = build_reservation_candidate(fill, key, full_fill=full_fill)
    ledger.fill_keys.add(key)
    ledger.telemetry_event_ids.add(payload["execution_event_id"])
    ledger.reservation_candidate_keys.add(candidate["release_idempotency_key"] or candidate["fill_idempotency_key"])
    ledger.prior_cumulative_qty = fill.cumulative_filled_qty or ledger.prior_cumulative_qty
    ledger.latest_exchange_ts_ns = int(fill.exchange_ts_ns or ledger.latest_exchange_ts_ns)
    ledger.terminal_full_fill = full_fill
    return FillDecision(
        accepted=True,
        reason_code="full_fill_truth" if full_fill else "partial_fill_truth",
        partial_fill=not full_fill,
        full_fill=full_fill,
        telemetry_payload=payload,
        reservation_candidate=candidate,
    )


def reconcile_broker_trades(
    snapshot: BrokerTradeSnapshot,
    ledger: FillLedger,
    *,
    local_fill_keys: set[str],
) -> FillDecision:
    if not snapshot.source or not snapshot.snapshot_ts_ns:
        return FillDecision(fail_closed=True, reason_code="missing_reconciliation_source_or_timestamp")
    broker_keys = {str(fill_idempotency_key(fill)) for fill in snapshot.recent_fills if fill_idempotency_key(fill)}
    if broker_keys - local_fill_keys:
        return FillDecision(accepted=True, reason_code="broker_trade_truth_supports_fill_ingestion", needs_reconciliation=True)
    if local_fill_keys - broker_keys:
        return FillDecision(fail_closed=True, reason_code="local_fill_missing_from_broker_trade_snapshot")
    return FillDecision(accepted=True, reason_code="broker_trade_snapshot_reconciled")


def test_fill_identity_mapping_and_duplicate_idempotency():
    ledger = FillLedger()
    fill = _fill()
    deterministic_fill = _fill(venue_fill_id=None, source="mock_fill_history")

    result = classify_fill(fill, ledger)
    duplicate = classify_fill(fill, ledger)
    deterministic_key = fill_idempotency_key(deterministic_fill)

    assert result.accepted is True
    assert result.partial_fill is True
    assert fill_idempotency_key(fill) == "live-fill-client-order:broker-order-1:venue-fill-1"
    assert duplicate.duplicate is True
    assert duplicate.telemetry_payload is None
    assert deterministic_key == (
        "live-fill-client-order:broker-order-1:"
        f"{T0_NS}:0.25:2500.50:0.10:mock_fill_history"
    )
    assert classify_fill(_fill(client_order_id=None), FillLedger()).reason_code == "missing_order_identity"
    assert classify_fill(_fill(broker_order_id="broker-other"), FillLedger()).reason_code == "order_mapping_mismatch"
    assert classify_fill(_fill(symbol="BTC/USD"), FillLedger()).reason_code == "symbol_or_side_mapping_mismatch"


def test_quantity_semantics_partial_full_and_fail_closed_cases():
    ledger = FillLedger()
    partial = classify_fill(_fill(), ledger)
    full = classify_fill(
        _fill(
            venue_fill_id="venue-fill-2",
            fill_qty=Decimal("0.75"),
            cumulative_filled_qty=Decimal("1.00"),
            remaining_qty=Decimal("0"),
            status="filled",
            exchange_ts_ns=T0_NS + 10,
            receive_ts_ns=T0_NS + 11,
        ),
        ledger,
    )

    assert partial.partial_fill is True
    assert partial.full_fill is False
    assert full.full_fill is True
    assert full.reservation_candidate["candidate_type"] == "release"
    assert classify_fill(_fill(fill_qty=Decimal("0")), FillLedger()).reason_code == "invalid_fill_quantity"
    assert classify_fill(_fill(fill_qty=Decimal("-1")), FillLedger()).reason_code == "invalid_fill_quantity"
    assert classify_fill(_fill(cumulative_filled_qty=Decimal("1.01")), FillLedger()).reason_code == "overfill"
    assert classify_fill(
        _fill(cumulative_filled_qty=Decimal("0.20")),
        FillLedger(prior_cumulative_qty=Decimal("0.25")),
    ).reason_code == "cumulative_regression"
    assert classify_fill(_fill(cumulative_filled_qty=None, remaining_qty=None), FillLedger()).reason_code == (
        "cumulative_remaining_ambiguity"
    )
    assert classify_fill(_fill(quantity_semantics=None), FillLedger()).reason_code == "quantity_semantics_ambiguous"


def test_price_average_price_and_fee_truth_are_preserved_not_invented():
    with_avg = classify_fill(_fill(avg_fill_price=Decimal("2500.75")), FillLedger())
    without_avg = classify_fill(_fill(avg_fill_price=None), FillLedger())
    zero_fee = classify_fill(_fill(fee=Decimal("0")), FillLedger())

    assert with_avg.telemetry_payload["avg_fill_price"] == "2500.75"
    assert without_avg.telemetry_payload["avg_fill_price"] is None
    assert zero_fee.telemetry_payload["fee"] == "0"
    assert classify_fill(_fill(fill_price=None), FillLedger()).reason_code == "invalid_fill_price"
    assert classify_fill(_fill(fill_price=Decimal("0")), FillLedger()).reason_code == "invalid_fill_price"
    assert classify_fill(_fill(fee=None), FillLedger()).reason_code == "missing_fee_gap"
    assert classify_fill(_fill(fee_currency=None), FillLedger()).reason_code == "missing_fee_currency_gap"
    assert classify_fill(_fill(fee=Decimal("-0.01")), FillLedger()).reason_code == "negative_fee"
    for forbidden in ("slippage_bps", "net_edge", "net_pnl", "profitability"):
        assert with_avg.telemetry_payload[forbidden] is None


def test_timestamp_authority_and_stale_out_of_order_protection():
    assert classify_fill(_fill(receive_ts_ns=None), FillLedger()).reason_code == "missing_receive_timestamp"
    assert classify_fill(_fill(exchange_ts_ns=None), FillLedger()).reason_code == "missing_exchange_timestamp_gap"
    assert classify_fill(_fill(receive_ts_ns=T0_NS - 1), FillLedger()).reason_code == (
        "receive_before_exchange_timestamp"
    )
    assert classify_fill(_fill(exchange_ts_ns=T0_NS - 10, receive_ts_ns=T0_NS + 1), FillLedger(latest_exchange_ts_ns=T0_NS)).reason_code == (
        "stale_fill_requires_reconciliation"
    )
    assert classify_fill(
        _fill(venue_fill_id="venue-fill-after-terminal", exchange_ts_ns=T0_NS + 10, receive_ts_ns=T0_NS + 11),
        FillLedger(latest_exchange_ts_ns=T0_NS, terminal_full_fill=True),
    ).reason_code == "fill_after_terminal_requires_reconciliation"
    first = classify_fill(_fill(venue_fill_id="same-ts-fill-1"), FillLedger())
    second = classify_fill(_fill(venue_fill_id="same-ts-fill-2"), FillLedger())
    assert first.accepted is True
    assert second.accepted is True
    assert first.telemetry_payload["venue_fill_id"] != second.telemetry_payload["venue_fill_id"]


def test_fill_terminal_classification_over_cancel_and_incomplete_full_status():
    ledger = FillLedger()
    fill_after_cancel = classify_fill(
        _fill(
            status="filled",
            fill_qty=Decimal("1.00"),
            cumulative_filled_qty=Decimal("1.00"),
            remaining_qty=Decimal("0"),
        ),
        ledger,
    )
    duplicate_full = classify_fill(_fill(status="filled", fill_qty=Decimal("1.00"), cumulative_filled_qty=Decimal("1.00"), remaining_qty=Decimal("0")), ledger)
    incomplete_status = classify_fill(
        _fill(status="filled", cumulative_filled_qty=None, remaining_qty=None),
        FillLedger(),
    )
    complete_unknown_status = classify_fill(
        _fill(
            status="unknown",
            fill_qty=Decimal("1.00"),
            cumulative_filled_qty=Decimal("1.00"),
            remaining_qty=Decimal("0"),
        ),
        FillLedger(),
    )

    assert fill_after_cancel.full_fill is True
    assert fill_after_cancel.reason_code == "full_fill_truth"
    assert duplicate_full.duplicate is True
    assert incomplete_status.reason_code == "cumulative_remaining_ambiguity"
    assert complete_unknown_status.accepted is True
    assert complete_unknown_status.full_fill is False
    assert complete_unknown_status.needs_reconciliation is True
    assert complete_unknown_status.reason_code == "complete_quantity_status_unknown_requires_reconciliation"


def test_telemetry_contract_fields_and_duplicate_suppression():
    ledger = FillLedger()
    result = classify_fill(_fill(), ledger)
    duplicate = classify_fill(_fill(), ledger)
    payload = result.telemetry_payload

    required_fields = {
        "decision_uuid",
        "order_intent_id",
        "client_order_id",
        "broker_order_id",
        "exchange_order_id",
        "execution_event_id",
        "symbol",
        "side",
        "requested_qty",
        "filled_qty",
        "cumulative_filled_qty",
        "remaining_qty",
        "fill_price",
        "avg_fill_price",
        "fee",
        "fee_currency",
        "venue_fill_id",
        "exchange_timestamp_ns",
        "receive_timestamp_ns",
        "liquidity",
        "status_source",
        "mapping_source",
        "paper_mode",
    }
    assert required_fields.issubset(payload.keys())
    assert payload["paper_mode"] is False
    assert payload["production_record_written"] is False
    assert duplicate.telemetry_payload is None
    assert len(ledger.telemetry_event_ids) == 1
    assert classify_fill(_fill(decision_uuid=None), FillLedger()).telemetry_payload["decision_uuid"] is None


def test_reservation_candidate_evidence_is_candidate_only_and_idempotent(tmp_path):
    root = runtime_main.SovereignHeartbeat.__new__(runtime_main.SovereignHeartbeat)
    root.state_store = StateStore(str(tmp_path / "state.db"))
    root._bootstrap_reservation_lifecycle_disabled(
        SimpleNamespace(
            initial_capital=20_000.0,
            broker_mode="live",
            reservation_lifecycle_paper_enabled=True,
        )
    )
    ledger = FillLedger()
    partial = classify_fill(_fill(), ledger)
    full = classify_fill(
        _fill(
            venue_fill_id="venue-fill-2",
            fill_qty=Decimal("0.75"),
            cumulative_filled_qty=Decimal("1.00"),
            remaining_qty=Decimal("0"),
            status="filled",
            exchange_ts_ns=T0_NS + 10,
            receive_ts_ns=T0_NS + 11,
        ),
        ledger,
    )

    assert root.reservation_lifecycle_enabled is False
    assert root.reservation_lifecycle_bootstrap_status["reservation_lifecycle_live_blocked"] is True
    assert partial.reservation_candidate["candidate_type"] == "fill_progress"
    assert partial.reservation_candidate["reservation_mutation_performed"] is False
    assert partial.reservation_candidate["live_reservation_lifecycle_enabled"] is False
    assert full.reservation_candidate["candidate_type"] == "release"
    assert full.reservation_candidate["reservation_release_performed"] is False
    assert full.reservation_candidate["release_idempotency_key"].endswith(":release")


def test_reconciliation_interaction_is_read_only_and_conflicts_fail_closed():
    ledger = FillLedger()
    fill = _fill()
    key = str(fill_idempotency_key(fill))

    broker_supports_missing_local = reconcile_broker_trades(
        BrokerTradeSnapshot((fill,), "mock_recent_trades", T0_NS + 5),
        ledger,
        local_fill_keys=set(),
    )
    local_missing_from_broker = reconcile_broker_trades(
        BrokerTradeSnapshot((), "mock_recent_trades", T0_NS + 5),
        ledger,
        local_fill_keys={key},
    )
    reconciled = reconcile_broker_trades(
        BrokerTradeSnapshot((fill,), "mock_recent_trades", T0_NS + 5),
        ledger,
        local_fill_keys={key},
    )
    missing_source = reconcile_broker_trades(
        BrokerTradeSnapshot((fill,), None, T0_NS + 5),
        ledger,
        local_fill_keys={key},
    )

    assert broker_supports_missing_local.reason_code == "broker_trade_truth_supports_fill_ingestion"
    assert broker_supports_missing_local.needs_reconciliation is True
    assert local_missing_from_broker.fail_closed is True
    assert local_missing_from_broker.reason_code == "local_fill_missing_from_broker_trade_snapshot"
    assert reconciled.reason_code == "broker_trade_snapshot_reconciled"
    assert missing_source.reason_code == "missing_reconciliation_source_or_timestamp"
    assert broker_supports_missing_local.side_effects == ()


def test_broker_adapter_live_broker_remain_inactive_contract_evidence_only():
    broker_adapter_source = Path("app/execution/broker_adapter.py").read_text(encoding="utf-8-sig")
    live_broker_source = Path("app/execution/live_broker.py").read_text(encoding="utf-8-sig")

    assert "PRE-INTEGRATION" in broker_adapter_source
    assert "NO IMPLEMENTATION" in broker_adapter_source
    assert "Under construction" in live_broker_source
    assert "submit_order" not in live_broker_source
    assert "cancel_order" not in live_broker_source
