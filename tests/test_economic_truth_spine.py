from __future__ import annotations

import inspect
import json
from decimal import Decimal

from app.execution.order_router import OrderRouter
from app.execution.paper_broker import PaperBroker
from app.models import OrderFill, OrderRequest
from app.models.enums import InternalOrderStatus, OrderSide, OrderType, SleeveType
from app.risk.net_edge_governor import NetEdgeGovernor
from app.risk.trade_efficiency_governor import TradeEfficiencyGovernor
from app.telemetry.event_store import TelemetryEventStore


T0_NS = 1_777_948_800_000_000_000
DECISION_UUID = "economic-truth-spine-decision"
ORDER_ID = "economic-truth-spine-client-order"


def _economic_order() -> OrderRequest:
    return OrderRequest(
        id=ORDER_ID,
        symbol="ETH/USD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.5"),
        limit_price=None,
        strategy=SleeveType.SECTOR_ROTATION,
        confidence=0.90,
        decision_uuid=DECISION_UUID,
        exchange_ts_ns=T0_NS,
        receive_ts_ns=T0_NS,
        metadata={"harness": "economic_truth_spine"},
    )


def _payloads(store: TelemetryEventStore, decision_uuid: str) -> list[dict]:
    payloads = []
    for event in store.get_decision_chain(decision_uuid):
        payloads.append(json.loads(event["payload_json"]))
    return payloads


def _fill_payload(store: TelemetryEventStore) -> dict:
    fill_events = store.get_events_by_type("fill", limit=20)
    assert len(fill_events) == 1
    event = fill_events[0]
    assert event["decision_uuid"] == DECISION_UUID
    return json.loads(event["payload_json"])


def test_paper_fill_preserves_passive_economic_truth_in_telemetry_and_broker_records(tmp_path):
    store = TelemetryEventStore(str(tmp_path / "economic-truth.db"))
    router = OrderRouter(paper_mode=True, telemetry_store=store)
    router.update_market_mid("ETH/USD", 2500.00, T0_NS)
    order = _economic_order()

    fill = router.submit_order(order)

    assert isinstance(fill, OrderFill)
    assert fill.order_id == ORDER_ID
    assert fill.symbol == "ETH/USD"
    assert fill.side == OrderSide.BUY
    assert fill.quantity == Decimal("0.5")
    assert fill.price > Decimal("0")
    assert fill.fee >= Decimal("0")
    assert fill.fee_currency == "USD"
    assert fill.status == InternalOrderStatus.FILLED
    assert fill.exchange_ts_ns >= T0_NS
    assert fill.receive_ts_ns >= T0_NS

    payload = _fill_payload(store)
    assert payload["fill_event_id"] == f"fill_{ORDER_ID}_{fill.exchange_ts_ns}"
    assert payload["execution_event_id"] == ORDER_ID
    assert payload["order_intent_id"] == ORDER_ID
    assert payload["decision_uuid"] == DECISION_UUID
    assert payload["venue_fill_id"] == ORDER_ID
    assert payload["symbol"] == "ETH/USD"
    assert payload["side"] == "buy"
    assert Decimal(payload["requested_qty"]) == Decimal("0.5")
    assert Decimal(payload["quantity"]) == fill.quantity
    assert Decimal(payload["price"]) == fill.price
    assert Decimal(payload["fee"]) == fill.fee
    assert payload["fee_currency"] == "USD"
    assert payload["paper_mode"] is True
    assert payload["strategy"] == "sector_rotation"
    assert payload["sleeve"] == "sector_rotation"

    context = payload["order_lifecycle_replay_context"]
    assert context["client_order_id"] == ORDER_ID
    assert context["decision_uuid"] == DECISION_UUID
    assert context["venue_order_id"] is not None
    assert context["broker_order_id"] is not None
    assert context["original_qty"] == "0.50000000"
    assert Decimal(context["fill_delta_qty"]) == fill.quantity
    assert Decimal(context["cumulative_filled_qty"]) == fill.quantity
    assert Decimal(context["remaining_qty"]) == Decimal("0")
    assert Decimal(context["avg_fill_price"]) == fill.price
    assert Decimal(context["cumulative_fee"]) == fill.fee
    assert context["is_terminal"] is True
    assert context["terminal_state"] == "filled"
    assert context["terminal_reason"] == "full_fill_observed"
    assert context["status_source"] == "order_router.fill_observation"
    assert context["id_mapping_source"] == "paper_broker.execution_report"
    assert context["mapping_authoritative"] is False
    assert context["exposure_reservation_authority"] is False
    assert context["reservation_delta_authoritative"] is False

    candidate = context["reservation_candidate_delta"]
    assert candidate is not None
    assert candidate["candidate_type"] == "release"
    assert candidate["reservation_authority"] is False
    assert candidate["reservation_mutation_performed"] is False
    assert candidate["reservation_release_performed"] is False
    assert candidate["client_order_id"] == ORDER_ID
    assert Decimal(candidate["fill_delta_qty"]) == fill.quantity
    assert Decimal(candidate["remaining_qty"]) == Decimal("0")
    assert candidate["terminal_state"] == "filled"

    assert router._paper_broker is not None
    broker_reports = [
        report
        for report in router._paper_broker.execution_reports
        if report.client_id == ORDER_ID
    ]
    assert [report.status.value for report in broker_reports] == [
        "ACKNOWLEDGED",
        "FULLY_FILLED",
    ]
    fill_report = broker_reports[-1]
    assert fill_report.filled_quantity == fill.quantity
    assert fill_report.fill_price == fill.price
    assert fill_report.fee == fill.fee
    assert fill_report.liquidity.value in {"TAKER", "MAKER", "UNKNOWN"}

    status = router._order_status_cache[ORDER_ID]
    assert status.status == "filled"
    assert status.filled_quantity == fill.quantity
    assert status.filled_price == fill.price
    assert status.remaining_quantity == Decimal("0")


def test_economic_truth_spine_exposes_existing_gaps_without_inventing_math(tmp_path):
    store = TelemetryEventStore(str(tmp_path / "economic-gaps.db"))
    router = OrderRouter(paper_mode=True, telemetry_store=store)
    router.update_market_mid("ETH/USD", 2500.00, T0_NS)

    fill = router.submit_order(_economic_order())
    assert fill is not None
    payload = _fill_payload(store)

    absent_or_gap_fields = {
        "slippage_bps",
        "expected_fill_price",
        "arrival_price",
        "net_pnl",
        "net_edge",
        "profitability",
    }
    assert absent_or_gap_fields.isdisjoint(payload.keys())
    assert absent_or_gap_fields.isdisjoint(payload["order_lifecycle_replay_context"].keys())

    fill_report = [
        report
        for report in router._paper_broker.execution_reports
        if report.client_id == ORDER_ID and report.status.value == "FULLY_FILLED"
    ][0]
    assert fill_report.liquidity.value in {"TAKER", "MAKER", "UNKNOWN"}
    assert isinstance(fill_report.notes, tuple)


def test_dormant_economics_governors_are_not_active_money_path_authorities(tmp_path):
    store = TelemetryEventStore(str(tmp_path / "economic-dormant.db"))
    router = OrderRouter(paper_mode=True, telemetry_store=store)
    router.update_market_mid("ETH/USD", 2500.00, T0_NS)

    fill = router.submit_order(_economic_order())
    assert fill is not None

    payloads = _payloads(store, DECISION_UUID)
    assert payloads
    serialized_payloads = json.dumps(payloads, sort_keys=True)
    assert "NetEdgeGovernor" not in serialized_payloads
    assert "TradeEfficiencyGovernor" not in serialized_payloads
    assert "economic_veto" not in serialized_payloads
    assert "net_edge_veto" not in serialized_payloads

    money_path_sources = (
        inspect.getsource(OrderRouter),
        inspect.getsource(PaperBroker),
    )
    for source in money_path_sources:
        assert "NetEdgeGovernor" not in source
        assert "TradeEfficiencyGovernor" not in source

    governor_sources = (
        inspect.getsource(NetEdgeGovernor),
        inspect.getsource(TradeEfficiencyGovernor),
    )
    forbidden_execution_tokens = (
        "OrderRouter",
        "PaperBroker",
        "broker_adapter",
        "live_broker",
        "submit_order",
        "_execute_signal",
    )
    for source in governor_sources:
        for token in forbidden_execution_tokens:
            assert token not in source
