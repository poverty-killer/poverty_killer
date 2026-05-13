import json
from decimal import Decimal

from app.execution.order_router import OrderRouter
from app.execution.paper_broker import PaperBrokerConfig, PaperMarketContext, PriceLevel
from app.models import OrderRequest
from app.models.enums import OrderSide, OrderType, SleeveType
from app.state.state_store import StateStore
from app.telemetry.event_store import TelemetryEventStore
from app.utils.enums import OrderSide as PbOrderSide
from app.utils.enums import OrderType as PbOrderType
from app.utils.enums import TimeInForce
from app.utils.time_utils import now_ns


class _MockResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self) -> dict:
        return self._payload


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
    candidate = context["reservation_candidate_delta"]
    assert payload["event_family"] == "order_lifecycle"
    assert payload["lifecycle_phase"] == phase
    assert context["event_family"] == "order_lifecycle"
    assert context["lifecycle_phase"] == phase
    assert payload["mapping_authoritative"] is False
    assert payload["active_cancel_status_mapping_ready"] is False
    assert payload["router_cache_authoritative"] is False
    assert payload["exposure_reservation_authority"] is False
    assert payload["exposure_reservation_mutated"] is False
    assert payload["reservation_mapping_ready"] is False
    assert payload["reservation_delta_authoritative"] is False
    assert payload["reservation_candidate_delta"] == candidate
    assert payload["reservation_candidate_authoritative"] is False
    assert context["mapping_authoritative"] is False
    assert context["active_cancel_status_mapping_ready"] is False
    assert context["router_cache_authoritative"] is False
    assert context["exposure_reservation_authority"] is False
    assert context["exposure_reservation_mutated"] is False
    assert context["reservation_mapping_ready"] is False
    assert context["reservation_delta_authoritative"] is False
    assert context["reservation_candidate_authoritative"] is False
    assert context["order_id_namespace"] == "client_order_id"
    assert context["passive_mapping_namespace"] in {"client_order_id", "mixed/passive"}
    assert context["passive_mapping_id_namespaces"][0] == "client_order_id"
    if candidate is not None:
        assert candidate["reservation_authority"] is False
        assert candidate["exposure_reservation_mutated"] is False
        assert candidate["reservation_mutation_performed"] is False
        assert candidate["exposure_release_performed"] is False
        assert candidate["reservation_release_performed"] is False
        assert candidate["active_reservation_ledger_created"] is False
        assert candidate["client_order_id"] == payload["client_order_id"]


def _assert_candidate_flags(
    candidate: dict,
    *,
    open_candidate: bool = False,
    adjust_candidate: bool = False,
    release_candidate: bool = False,
) -> None:
    assert candidate["open_candidate_only"] is open_candidate
    assert candidate["adjust_candidate_only"] is adjust_candidate
    assert candidate["release_candidate_only"] is release_candidate
    assert [open_candidate, adjust_candidate, release_candidate].count(True) == 1


def test_passive_open_reservation_candidate_emitted_at_submit_boundary(tmp_path):
    store = TelemetryEventStore(str(tmp_path / "open_candidate.db"))
    router = OrderRouter(paper_mode=True, telemetry_store=store)
    order = _order(order_id="open-candidate-client-001", decision_uuid="open-candidate-decision-001")

    assert router.submit_order(order) is None
    router._record_order_submission_telemetry(order)

    submitted = _payloads(store, order.decision_uuid, "order_submitted")
    assert len(submitted) == 2
    dedupe_keys = set()
    for payload in submitted:
        _assert_passive_lifecycle(payload, "order_submitted")
        candidate = payload["reservation_candidate_delta"]
        assert candidate is not None
        _assert_candidate_flags(candidate, open_candidate=True)
        assert candidate["symbol"] == order.symbol
        assert candidate["side"] == "buy"
        assert candidate["quantity"] == str(order.quantity)
        assert candidate["price_basis"] == str(order.limit_price)
        assert candidate["notional"] == str(order.quantity * order.limit_price)
        assert candidate["decision_uuid"] == order.decision_uuid
        assert candidate["reservation_dedupe_key"] == f"{order.decision_uuid}:{order.id}"
        dedupe_keys.add(candidate["reservation_dedupe_key"])
    assert dedupe_keys == {f"{order.decision_uuid}:{order.id}"}


def test_live_kraken_submit_ack_mapping_is_passive_and_client_cache_keyed(tmp_path):
    store = TelemetryEventStore(str(tmp_path / "kraken_ack.db"))
    router = OrderRouter(
        primary_exchange="kraken",
        paper_mode=False,
        telemetry_store=store,
        rest_fallback_enabled=False,
    )
    router._websocket_connected = True
    posts = []

    def post(url, data=None, headers=None, timeout=None):
        posts.append({"url": url, "data": data, "headers": headers, "timeout": timeout})
        return _MockResponse(200, {"error": [], "result": {"txid": ["KRAKEN-TXID-001"]}})

    router._session.post = post
    order = _order(order_id="kraken-client-order-001", decision_uuid="kraken-decision-001")

    assert router.submit_order(order) is None

    payloads = _payloads(store, order.decision_uuid, "order_acknowledged")
    assert len(payloads) == 1
    payload = payloads[0]
    context = payload["order_lifecycle_replay_context"]
    _assert_passive_lifecycle(payload, "order_acknowledged")
    assert payload["client_order_id"] == order.id
    assert payload["venue_order_id"] == "KRAKEN-TXID-001"
    assert payload["broker_order_id"] is None
    assert payload["exchange_txid"] == "KRAKEN-TXID-001"
    assert payload["id_mapping_source"] == "order_router.kraken_submit_response"
    assert context["client_order_id"] == order.id
    assert context["venue_order_id"] == "KRAKEN-TXID-001"
    assert context["broker_order_id"] is None
    assert context["exchange_txid"] == "KRAKEN-TXID-001"
    assert context["id_mapping_source"] == "order_router.kraken_submit_response"
    assert context["passive_mapping_namespace"] == "mixed/passive"
    assert context["passive_mapping_id_namespaces"] == [
        "client_order_id",
        "venue_order_id",
        "exchange_txid",
    ]
    assert router._pending_orders == {order.id: order}
    assert "KRAKEN-TXID-001" not in router._pending_orders
    assert len(posts) == 1


def test_live_alpaca_submit_ack_mapping_is_passive_and_client_cache_keyed(tmp_path):
    store = TelemetryEventStore(str(tmp_path / "alpaca_ack.db"))
    router = OrderRouter(
        primary_exchange="alpaca",
        paper_mode=False,
        telemetry_store=store,
        rest_fallback_enabled=False,
    )
    router._websocket_connected = True
    posts = []

    def post(url, json=None, timeout=None):
        posts.append({"url": url, "json": json, "timeout": timeout})
        return _MockResponse(200, {"id": "ALPACA-ID-001"})

    router._session.post = post
    order = _order(order_id="alpaca-client-order-001", decision_uuid="alpaca-decision-001")

    assert router.submit_order(order) is None

    payloads = _payloads(store, order.decision_uuid, "order_acknowledged")
    assert len(payloads) == 1
    payload = payloads[0]
    context = payload["order_lifecycle_replay_context"]
    _assert_passive_lifecycle(payload, "order_acknowledged")
    assert payload["client_order_id"] == order.id
    assert payload["venue_order_id"] == "ALPACA-ID-001"
    assert payload["broker_order_id"] == "ALPACA-ID-001"
    assert payload["exchange_txid"] is None
    assert payload["id_mapping_source"] == "order_router.alpaca_submit_response"
    assert context["client_order_id"] == order.id
    assert context["venue_order_id"] == "ALPACA-ID-001"
    assert context["broker_order_id"] == "ALPACA-ID-001"
    assert context["exchange_txid"] is None
    assert context["id_mapping_source"] == "order_router.alpaca_submit_response"
    assert context["passive_mapping_namespace"] == "mixed/passive"
    assert context["passive_mapping_id_namespaces"] == [
        "client_order_id",
        "venue_order_id",
        "broker_order_id",
    ]
    assert router._pending_orders == {order.id: order}
    assert "ALPACA-ID-001" not in router._pending_orders
    assert len(posts) == 1


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
    assert payload["passive_mapping_namespace"] == "mixed/passive"
    assert payload["passive_mapping_id_namespaces"] == [
        "client_order_id",
        "venue_order_id",
        "broker_order_id",
    ]
    assert payload["broker_order_id"] is not None
    assert payload["broker_order_id"] != order.id
    assert payload["venue_order_id"] == payload["broker_order_id"]
    assert payload["id_mapping_source"] == "paper_broker.execution_report"
    assert payload["broker_order_id"] not in router._pending_orders
    assert order.id in router._pending_orders
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
        candidate = payload["reservation_candidate_delta"]
        assert candidate is not None
        _assert_candidate_flags(candidate, adjust_candidate=True)
        assert candidate["fill_delta_qty"] == payload["fill_delta_qty"]
        assert candidate["cumulative_filled_qty"] == payload["cumulative_filled_qty"]
        assert candidate["remaining_qty"] == payload["remaining_qty"]
        assert candidate["reservation_dedupe_key"] == f"{order.decision_uuid}:{order.id}"
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
    assert request_payload["reservation_candidate_delta"] is None
    assert request_payload["client_order_id"] == order.id
    assert request_payload["broker_order_id"] is not None
    assert request_payload["is_terminal"] is False
    assert request_payload["terminal_state"] is None

    canceled_payload = canceled[0]
    _assert_passive_lifecycle(canceled_payload, "order_canceled")
    assert canceled_payload["reservation_candidate_delta"] is None
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
    assert payload["reservation_candidate_delta"] is None
    assert payload["client_order_id"] == order.id
    assert payload["broker_order_id"] is not None
    assert payload["is_terminal"] is True
    assert payload["terminal_state"] == "expired"
    assert payload["terminal_reason"] == "paper_broker_expired"


def test_terminal_mapping_proof_emits_passive_release_candidate_only(tmp_path):
    store = TelemetryEventStore(str(tmp_path / "terminal_candidate_events.db"))
    state_store = StateStore(str(tmp_path / "terminal_candidate_state.db"))
    router = OrderRouter(
        primary_exchange="kraken",
        paper_mode=False,
        telemetry_store=store,
        state_store=state_store,
        rest_fallback_enabled=False,
    )
    router._websocket_connected = True

    def post(url, data=None, headers=None, timeout=None):
        return _MockResponse(200, {"error": [], "result": {"txid": ["KRAKEN-TXID-TERM-001"]}})

    router._session.post = post
    order = _order(order_id="terminal-candidate-client-001", decision_uuid="terminal-candidate-decision-001")
    assert router.submit_order(order) is None

    result = router.mark_terminal_from_status_evidence(
        {
            "client_order_id": order.id,
            "broker": "kraken",
            "venue": "kraken",
            "command_id_namespace": "exchange_txid",
            "command_order_id": "KRAKEN-TXID-TERM-001",
            "status_classification": "terminal_observed",
            "terminal_observed": True,
            "status_raw": "filled",
        }
    )
    assert result["applied"] is True
    proof = router.get_terminal_mapping_proofs()[-1]
    candidate = proof["reservation_candidate_delta"]
    assert candidate is not None
    _assert_candidate_flags(candidate, release_candidate=True)
    assert candidate["reservation_authority"] is False
    assert candidate["exposure_reservation_mutated"] is False
    assert candidate["reservation_release_performed"] is False
    assert candidate["exposure_release_performed"] is False
    assert candidate["active_reservation_ledger_created"] is False
    assert candidate["client_order_id"] == order.id
    assert candidate["terminal_state"] == "filled"
    assert candidate["terminal_reason"] == "status_evidence_filled"
