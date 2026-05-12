import json
from decimal import Decimal

from app.execution.order_router import OrderRouter
from app.execution.paper_broker import PaperBrokerConfig, PaperMarketContext, PriceLevel
from app.models import OrderRequest
from app.models.enums import OrderSide, OrderType, SleeveType
from app.telemetry.event_store import TelemetryEventStore
from app.utils.enums import OrderSide as PbOrderSide
from app.utils.enums import OrderType as PbOrderType
from app.utils.enums import TimeInForce
from app.utils.time_utils import now_ns


def _order(
    *,
    order_id: str,
    decision_uuid: str,
    quantity: Decimal = Decimal("1.0"),
    limit_price: Decimal = Decimal("2900.00"),
) -> OrderRequest:
    ts_ns = now_ns()
    return OrderRequest(
        id=order_id,
        symbol="ETH/USD",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=quantity,
        limit_price=limit_price,
        strategy=SleeveType.SECTOR_ROTATION,
        confidence=0.9,
        decision_uuid=decision_uuid,
        exchange_ts_ns=ts_ns,
        receive_ts_ns=ts_ns,
    )


def _payloads(store: TelemetryEventStore, decision_uuid: str, phase: str) -> list[dict]:
    payloads = []
    for event in store.get_decision_chain(decision_uuid):
        payload = json.loads(event["payload_json"])
        if payload.get("telemetry_event") == phase:
            payloads.append(payload)
    return payloads


def _assert_passive_lifecycle(payload: dict, phase: str) -> None:
    context = payload["order_lifecycle_replay_context"]
    assert payload["event_family"] == "order_lifecycle"
    assert payload["lifecycle_phase"] == phase
    assert context["event_family"] == "order_lifecycle"
    assert context["lifecycle_phase"] == phase
    assert payload["mapping_authoritative"] is False
    assert payload["router_cache_authoritative"] is False
    assert payload["exposure_reservation_authority"] is False
    assert payload["exposure_reservation_mutated"] is False
    assert payload["reservation_delta_authoritative"] is False
    assert payload["reservation_candidate_delta"] is None
    assert payload["reservation_candidate_authoritative"] is False
    assert context["mapping_authoritative"] is False
    assert context["router_cache_authoritative"] is False
    assert context["exposure_reservation_authority"] is False
    assert context["exposure_reservation_mutated"] is False
    assert context["reservation_delta_authoritative"] is False
    assert context["reservation_candidate_delta"] is None
    assert context["reservation_candidate_authoritative"] is False


def test_paper_ack_observation_is_passive_non_terminal(tmp_path):
    store = TelemetryEventStore(str(tmp_path / "ack.db"))
    router = OrderRouter(paper_mode=True, telemetry_store=store)
    order = _order(order_id="ack-client-order-001", decision_uuid="ack-decision-001")

    fill = router.submit_order(order)

    assert fill is None
    payloads = _payloads(store, order.decision_uuid, "order_acknowledged")
    assert len(payloads) == 1
    payload = payloads[0]
    _assert_passive_lifecycle(payload, "order_acknowledged")
    assert payload["client_order_id"] == order.id
    assert payload["order_id_namespace"] == "client_order_id"
    assert payload["broker_order_id"] is not None
    assert payload["venue_order_id"] == payload["broker_order_id"]
    assert payload["is_terminal"] is False
    assert payload["terminal_state"] is None
    assert payload["order_lifecycle_replay_context"]["ack_seen"] is True


def test_paper_partial_fill_observation_is_decimal_safe_and_idempotent(tmp_path):
    store = TelemetryEventStore(str(tmp_path / "partial.db"))
    router = OrderRouter(paper_mode=True, telemetry_store=store)
    order = _order(
        order_id="partial-client-order-001",
        decision_uuid="partial-decision-001",
        quantity=Decimal("1.0"),
        limit_price=Decimal("2900.00"),
    )

    assert router.submit_order(order) is None
    paper_order = router._paper_broker.open_orders[order.id]

    first_ctx = PaperMarketContext(
        symbol=order.symbol,
        timestamp_ns=paper_order.eligible_at_ns + 2,
        mid_price=Decimal("2899.00"),
        best_bid=Decimal("2898.50"),
        best_ask=Decimal("2899.00"),
        ask_levels=(PriceLevel(price=Decimal("2899.00"), quantity=Decimal("0.25")),),
    )
    router._paper_broker.process_matching_detailed(
        current_ts_ns=paper_order.eligible_at_ns + 2,
        market_by_symbol={order.symbol: first_ctx},
    )
    router._sync_paper_reports()

    second_ctx = PaperMarketContext(
        symbol=order.symbol,
        timestamp_ns=paper_order.eligible_at_ns + 4,
        mid_price=Decimal("2898.00"),
        best_bid=Decimal("2897.50"),
        best_ask=Decimal("2898.00"),
        ask_levels=(PriceLevel(price=Decimal("2898.00"), quantity=Decimal("0.25")),),
    )
    router._paper_broker.process_matching_detailed(
        current_ts_ns=paper_order.eligible_at_ns + 4,
        market_by_symbol={order.symbol: second_ctx},
    )
    router._sync_paper_reports()

    partials = _payloads(store, order.decision_uuid, "order_partially_filled")
    assert len(partials) == 2
    idempotency_keys = {payload["idempotency_key"] for payload in partials}
    assert len(idempotency_keys) == 2

    for payload in partials:
        _assert_passive_lifecycle(payload, "order_partially_filled")
        assert payload["is_terminal"] is False
        assert payload["terminal_state"] is None
        assert payload["fill_delta_qty"] == str(Decimal(payload["fill_delta_qty"]))
        assert payload["cumulative_filled_qty"] == str(Decimal(payload["cumulative_filled_qty"]))
        assert payload["remaining_qty"] == str(Decimal(payload["remaining_qty"]))
        assert Decimal(payload["cumulative_filled_qty"]) + Decimal(payload["remaining_qty"]) == Decimal(payload["original_qty"])
        assert payload["order_lifecycle_replay_context"]["partial_fill_seen"] is True


def test_paper_cancel_observation_is_passive_and_terminal_only_when_report_proves_it(tmp_path):
    store = TelemetryEventStore(str(tmp_path / "cancel.db"))
    router = OrderRouter(paper_mode=True, telemetry_store=store)
    order = _order(order_id="cancel-client-order-001", decision_uuid="cancel-decision-001")

    assert router.submit_order(order) is None
    assert router.cancel_order(order.id) is True

    requested = _payloads(store, order.decision_uuid, "cancel_requested")
    canceled = _payloads(store, order.decision_uuid, "order_canceled")
    assert len(requested) == 1
    assert len(canceled) == 1

    request_payload = requested[0]
    _assert_passive_lifecycle(request_payload, "cancel_requested")
    assert request_payload["client_order_id"] == order.id
    assert request_payload["broker_order_id"] is not None
    assert request_payload["is_terminal"] is False
    assert request_payload["terminal_state"] is None

    canceled_payload = canceled[0]
    _assert_passive_lifecycle(canceled_payload, "order_canceled")
    assert canceled_payload["client_order_id"] == order.id
    assert canceled_payload["broker_order_id"] == request_payload["broker_order_id"]
    assert canceled_payload["venue_order_id"] == request_payload["broker_order_id"]
    assert canceled_payload["is_terminal"] is True
    assert canceled_payload["terminal_state"] == "canceled"
    assert canceled_payload["terminal_reason"] == "paper_broker_cancelled"


def test_paper_expiry_observation_is_passive_terminal_when_broker_reports_it(tmp_path):
    store = TelemetryEventStore(str(tmp_path / "expiry.db"))
    router = OrderRouter(paper_mode=True, telemetry_store=store)
    router._paper_broker.config = PaperBrokerConfig(enable_day_gtd_expiry=True)
    order = _order(order_id="expiry-client-order-001", decision_uuid="expiry-decision-001")
    ts_ns = order.exchange_ts_ns

    paper_order = router._paper_broker.submit_order_detailed(
        symbol=order.symbol,
        side=PbOrderSide.BUY,
        order_type=PbOrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        quantity=order.quantity,
        price=order.limit_price,
        ts_ns=ts_ns,
        client_id=order.id,
    )
    router._pending_orders[order.id] = order

    market = PaperMarketContext(
        symbol=order.symbol,
        timestamp_ns=paper_order.eligible_at_ns + 1,
        mid_price=Decimal("3000.00"),
        best_bid=Decimal("2999.50"),
        best_ask=Decimal("3000.00"),
    )
    router._paper_broker.process_matching_detailed(
        current_ts_ns=paper_order.eligible_at_ns + 1,
        market_by_symbol={order.symbol: market},
    )
    router._sync_paper_reports()

    expired = _payloads(store, order.decision_uuid, "order_expired")
    assert len(expired) == 1
    payload = expired[0]
    _assert_passive_lifecycle(payload, "order_expired")
    assert payload["client_order_id"] == order.id
    assert payload["broker_order_id"] is not None
    assert payload["is_terminal"] is True
    assert payload["terminal_state"] == "expired"
    assert payload["terminal_reason"] == "paper_broker_expired"
