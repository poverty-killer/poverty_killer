from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from app.execution.alpaca_paper_adapter import (
    EXPECTED_ALPACA_PAPER_BASE_URL,
    AlpacaPaperBrokerAdapter,
    AlpacaPaperCredentials,
)
from app.execution.broker_gateway import BrokerGatewayResponse
from app.execution.broker_read_policy import (
    BROKER_READ_NOT_AUTHORIZED,
    PAPER_SMOKE_STRICT_READS,
    PAPER_TCA_EXTENDED_READS,
    broker_read_profile_for_name,
)
from app.execution.order_router import ActiveOrderIdMapping, OrderRouter
from app.models import OrderRequest
from app.models.enums import OrderSide, OrderType, SleeveType
from app.state.state_store import StateStore


T0 = "2026-05-25T18:10:00Z"
T0_NS = 1_779_729_000_000_000_000


class FeeActivityAdapter:
    def __init__(self, activities: list[dict]) -> None:
        self.activities = activities
        self.request_counts = {"GET": 0, "POST": 0, "DELETE": 0}
        self.identity = SimpleNamespace(
            adapter_id="alpaca_paper_rest",
            venue_id="alpaca",
            portal_id="alpaca_paper",
            environment="paper",
            base_url=EXPECTED_ALPACA_PAPER_BASE_URL,
            credential_status="configured",
            supported_methods=frozenset({"GET", "POST", "DELETE"}),
            supported_asset_classes=frozenset({"crypto"}),
            live_blocked=True,
        )
        self.activity_type_requests: list[str] = []
        self.broker_read_permission_profile = broker_read_profile_for_name(PAPER_TCA_EXTENDED_READS)

    def get_account_activities(self, *, activity_types: str = "FILL", page_size: int = 100, **_kwargs):
        self.request_counts["GET"] += 1
        self.activity_type_requests.append(activity_types)
        return BrokerGatewayResponse(
            adapter_id="alpaca_paper_rest",
            venue_id="alpaca",
            portal_id="alpaca_paper",
            environment="paper",
            request_method="GET",
            endpoint_path="/v2/account/activities",
            ok=True,
            mutation_occurred=False,
            live_blocked=True,
            payload=list(self.activities),
        )


class CaptureTransport:
    def __init__(self, payload=None) -> None:
        self.payload = payload if payload is not None else []
        self.calls: list[dict] = []

    def request(self, *, method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: float):
        parsed = urlparse(url)
        self.calls.append(
            {
                "method": method,
                "path": parsed.path,
                "query": parse_qs(parsed.query),
                "body": json.loads(body.decode("utf-8")) if body else None,
            }
        )
        return 200, self.payload


def _store(tmp_path) -> StateStore:
    return StateStore(str(tmp_path / "state.db"))


def _partial_fill(store: StateStore, *, fill_id: str = "fill-1", broker_order_id: str = "broker-1") -> None:
    status = store.upsert_broker_fill_ledger(
        {
            "fill_id": fill_id,
            "broker_order_id": broker_order_id,
            "client_order_id": f"client-{broker_order_id}",
            "decision_uuid": "decision-1",
            "frame_id": "frame-1",
            "candidate_id": "candidate-1",
            "snapshot_id": "snapshot-1",
            "symbol": "BTC/USD",
            "side": "buy",
            "action": "buy_to_open",
            "quantity": "0.01",
            "price": "10000",
            "notional": "100",
            "fill_timestamp": T0,
            "fill_ts_ns": T0_NS,
            "broker_activity_id": f"fill-activity-{broker_order_id}",
            "fee": None,
            "fee_currency": None,
            "source": "broker_activity",
            "hydration_status": "PARTIAL",
            "hydration_reason_code": "BROKER_FILL_FEE_DETAIL_UNAVAILABLE",
            "tca_status": "UNKNOWN",
            "execution_quality_verdict": "UNKNOWN_INSUFFICIENT_BROKER_DETAIL",
            "modeled_entry_price": "9999.5",
            "modeled_net_edge": "0.01",
            "slippage": "0.5",
            "slippage_bps": "0.5",
            "metadata": {"fee_status": "FEE_PENDING_BROKER_ACTIVITY"},
            "created_at_ns": T0_NS,
            "observed_at_ns": T0_NS,
        }
    )
    assert status == "inserted"


def _net_edge_order(
    *,
    order_id: str = "client-broker-1",
    broker_order_id: str = "broker-1",
    side: OrderSide = OrderSide.BUY,
    action: str = "buy_to_open",
    price: str = "9999.50",
) -> OrderRequest:
    return OrderRequest(
        id=order_id,
        symbol="BTC/USD",
        side=side,
        quantity=Decimal("0.01"),
        order_type=OrderType.LIMIT,
        limit_price=Decimal(price),
        strategy=SleeveType.SECTOR_ROTATION,
        confidence=0.82,
        decision_uuid=f"decision-{broker_order_id}",
        exchange_ts_ns=T0_NS,
        receive_ts_ns=T0_NS,
        metadata={
            "action": action,
            "modeled_entry_price": price,
            "frame_id": f"frame-{broker_order_id}",
            "snapshot_id": f"snapshot-{broker_order_id}",
            "candidate_lifecycle": {"candidate_id": f"candidate-{broker_order_id}"},
            "net_edge_context": {
                "fee_bps": "6.0",
                "spread_bps": "10.0",
                "slippage_bps": "8.0",
                "latency_drag_bps": "4.0",
                "partial_fill_drag_bps": "4.0",
                "exit_execution_cost_bps": "4.0",
            },
            "net_edge_evaluation": {
                "net_adversarial_edge": "0.0125",
                "reason_code": "ECONOMICALLY_ADMISSIBLE",
                "admissible": True,
            },
        },
    )


def _mapping_for_order(router: OrderRouter, order: OrderRequest, *, broker_order_id: str) -> ActiveOrderIdMapping:
    return ActiveOrderIdMapping(
        client_order_id=order.id,
        broker="alpaca",
        symbol=order.symbol,
        side=str(getattr(order.side, "value", order.side)),
        order_type=str(getattr(order.order_type, "value", order.order_type)),
        venue_order_id=broker_order_id,
        broker_order_id=broker_order_id,
        exchange_txid=None,
        command_id_namespace="venue_order_id",
        command_order_id=broker_order_id,
        id_mapping_source="test",
        submit_ts_ns=order.exchange_ts_ns,
        ack_ts_ns=order.exchange_ts_ns + 1_000_000,
        order_metadata=router._order_metadata_snapshot(order),
    )


def _router(tmp_path, activities: list[dict]) -> tuple[OrderRouter, StateStore, FeeActivityAdapter]:
    store = _store(tmp_path)
    adapter = FeeActivityAdapter(activities)
    router = OrderRouter(
        primary_exchange="alpaca",
        paper_mode=True,
        execution_broker="alpaca_paper",
        broker_gateway_adapter=adapter,
        state_store=store,
        broker_read_profile=PAPER_TCA_EXTENDED_READS,
    )
    return router, store, adapter


def test_fresh_reconciled_fill_without_order_preserves_expected_edge_metadata(tmp_path):
    store = _store(tmp_path)
    router = OrderRouter(
        primary_exchange="alpaca",
        paper_mode=True,
        execution_broker="alpaca_paper",
        broker_gateway_adapter=FeeActivityAdapter([]),
        state_store=store,
        broker_read_profile=PAPER_TCA_EXTENDED_READS,
    )
    order = _net_edge_order()
    mapping = _mapping_for_order(router, order, broker_order_id="broker-1")

    result = router._hydrate_fill_ledger_from_broker_payload(
        mapping,
        {
            "id": "broker-1",
            "symbol": "BTCUSD",
            "side": "buy",
            "status": "filled",
            "filled_qty": "0.01",
            "filled_avg_price": "10000",
            "filled_at": T0,
        },
        source_event="test_shutdown_final_reconciliation",
    )

    assert result["status"] == "PARTIAL"
    assert result["net_edge_realization_status"] == "PASS"
    row = store.list_broker_fill_ledger()[0]
    assert row["decision_uuid"] == "decision-broker-1"
    assert row["modeled_entry_price"] == "9999.50"
    assert row["modeled_net_edge"] == "0.0125"
    assert row["metadata"]["net_edge_context"]["fee_bps"] == "6.0"
    assert row["metadata"]["net_edge_evaluation"]["net_adversarial_edge"] == "0.0125"
    assert row["metadata"]["order_metadata_capture"]["source"] == "durable_order_id_mapping"
    realization = row["metadata"]["net_edge_realization"]
    assert realization["record_type"] == "NET_EDGE_REALIZATION"
    assert realization["expected_edge"] == "0.0125"
    assert realization["decision_reference_price"] == "9999.50"
    assert realization["fee_source"] == "MODELED_ADVISORY"
    assert realization["modeled_values_are_advisory"] is True
    assert realization["broker_truth_authority"]["net_profit"] is False
    assert realization["round_trip_truth_status"] == "UNKNOWN_UNTIL_POSITION_CLOSE"


def test_sell_to_close_updates_entry_realization_with_at_close_truth_label(tmp_path):
    store = _store(tmp_path)
    router = OrderRouter(
        primary_exchange="alpaca",
        paper_mode=True,
        execution_broker="alpaca_paper",
        broker_gateway_adapter=FeeActivityAdapter([]),
        state_store=store,
        broker_read_profile=PAPER_TCA_EXTENDED_READS,
    )
    entry_order = _net_edge_order(order_id="entry-client", broker_order_id="entry-broker", price="10000")
    entry_mapping = _mapping_for_order(router, entry_order, broker_order_id="entry-broker")
    router._hydrate_fill_ledger_from_broker_payload(
        entry_mapping,
        {
            "id": "entry-broker",
            "symbol": "BTCUSD",
            "side": "buy",
            "status": "filled",
            "filled_qty": "0.01",
            "filled_avg_price": "10000",
            "filled_at": T0,
            "fee": "0.10",
            "fee_currency": "USD",
        },
        source_event="test_entry_fill",
    )
    close_order = _net_edge_order(
        order_id="close-client",
        broker_order_id="close-broker",
        side=OrderSide.SELL,
        action="sell_to_close",
        price="10100",
    )
    close_mapping = _mapping_for_order(router, close_order, broker_order_id="close-broker")

    result = router._hydrate_fill_ledger_from_broker_payload(
        close_mapping,
        {
            "id": "close-broker",
            "symbol": "BTCUSD",
            "side": "sell",
            "status": "filled",
            "filled_qty": "0.01",
            "filled_avg_price": "10100",
            "filled_at": "2026-05-25T18:15:00Z",
            "fee": "0.10",
            "fee_currency": "USD",
        },
        source_event="test_close_fill",
    )

    assert result["round_trip_entry_updates"][0]["true_net_profit_status"] == "BROKER_CONFIRMED_AFTER_POSITION_CLOSE"
    rows = {row["client_order_id"]: row for row in store.list_broker_fill_ledger()}
    entry_realization = rows["entry-client"]["metadata"]["net_edge_realization"]
    assert entry_realization["measurement_label"] == "AT_CLOSE_ACTUAL_ROUND_TRIP"
    assert entry_realization["round_trip_truth_status"] == "AT_CLOSE_ACTUAL_NET_PROFIT_CONFIRMED"
    assert entry_realization["true_net_profit_status"] == "BROKER_CONFIRMED_AFTER_POSITION_CLOSE"
    assert entry_realization["at_close_actual_round_trip"]["close_fill_id"] == rows["close-client"]["fill_id"]
    assert entry_realization["at_close_actual_round_trip"]["actual_net_profit"] == "0.80"


def test_alpaca_fee_activity_query_uses_read_only_cfee_fee_endpoint():
    transport = CaptureTransport(payload=[])
    adapter = AlpacaPaperBrokerAdapter(
        AlpacaPaperCredentials(
            base_url=EXPECTED_ALPACA_PAPER_BASE_URL,
            key_id="paper-key",
            secret_key="paper-secret",
        ),
        transport=transport,
        read_profile=PAPER_TCA_EXTENDED_READS,
    )

    response = adapter.get_fee_activities(after="2026-05-25T00:00:00Z", until="2026-05-26T00:00:00Z")

    assert response.ok is True
    assert response.mutation_occurred is False
    assert transport.calls == [
        {
            "method": "GET",
            "path": "/v2/account/activities",
            "query": {
                "activity_types": ["CFEE,FEE"],
                "page_size": ["100"],
                "after": ["2026-05-25T00:00:00Z"],
                "until": ["2026-05-26T00:00:00Z"],
            },
            "body": None,
        }
    ]


def test_cfee_activity_exact_order_match_updates_broker_fee_and_tca(tmp_path):
    router, store, adapter = _router(
        tmp_path,
        [
            {
                "id": "fee-activity-1",
                "activity_type": "CFEE",
                "order_id": "broker-1",
                "symbol": "BTCUSD",
                "net_amount": "-0.12",
                "currency": "USD",
                "transaction_time": T0,
            }
        ],
    )
    _partial_fill(store)

    router._hydrate_deferred_broker_fees(source_event="test_fee_hydration")

    rows = store.list_broker_fill_ledger()
    assert rows[0]["fee"] == "0.12"
    assert rows[0]["fee_currency"] == "USD"
    assert rows[0]["hydration_status"] == "HYDRATED"
    assert rows[0]["metadata"]["fee_status"] == "FEE_ACTIVITY_MATCHED"
    assert rows[0]["metadata"]["fee_source"] == "BROKER_CFEE"
    assert rows[0]["metadata"]["net_edge_realization"]["fee_source"] == "BROKER_CONFIRMED"
    assert rows[0]["metadata"]["net_edge_realization"]["broker_fee"] == "0.12"
    assert rows[0]["fee_bps"] == str((Decimal("0.12") / Decimal("100")) * Decimal("10000"))
    assert rows[0]["tca_status"] == "HYDRATED"
    assert store.count_table_rows("fills") == 1
    summary = router._broker_fee_hydration_summary()
    assert summary["broker_fee_hydration_count"] == 1
    assert summary["broker_fee_hydration_conflict_count"] == 0
    assert summary["tca_complete_count"] == 1
    assert adapter.activity_type_requests == ["CFEE,FEE"]


def test_strict_smoke_skips_deferred_fee_hydration_without_account_activity_read(tmp_path):
    store = _store(tmp_path)
    adapter = FeeActivityAdapter(
        [
            {
                "id": "fee-activity-1",
                "activity_type": "CFEE",
                "order_id": "broker-1",
                "symbol": "BTCUSD",
                "net_amount": "-0.12",
                "currency": "USD",
                "transaction_time": T0,
            }
        ]
    )
    router = OrderRouter(
        primary_exchange="alpaca",
        paper_mode=True,
        execution_broker="alpaca_paper",
        broker_gateway_adapter=adapter,
        state_store=store,
        broker_read_profile=PAPER_SMOKE_STRICT_READS,
    )
    _partial_fill(store)

    router._hydrate_deferred_broker_fees(source_event="strict_smoke_shutdown")

    summary = router._broker_fee_hydration_summary()
    row = store.list_broker_fill_ledger()[0]
    assert adapter.activity_type_requests == []
    assert summary["fee_hydration_skipped"] is True
    assert summary["fee_hydration_skip_reason"] == BROKER_READ_NOT_AUTHORIZED
    assert summary["fee_hydration_status"] == "SKIPPED_NOT_AUTHORIZED"
    assert summary["account_activity_read_authorized"] is False
    assert summary["broker_fee_hydration_attempted_count"] == 0
    assert summary["broker_fee_activity_records_seen_count"] == 0
    assert row["fee"] is None
    assert row["fee_currency"] is None


def test_fee_activity_missing_currency_keeps_tca_unknown_without_fake_fee(tmp_path):
    router, store, _adapter = _router(
        tmp_path,
        [
            {
                "id": "fee-activity-1",
                "activity_type": "CFEE",
                "order_id": "broker-1",
                "symbol": "BTCUSD",
                "net_amount": "-0.12",
                "transaction_time": T0,
            }
        ],
    )
    _partial_fill(store)

    router._hydrate_deferred_broker_fees(source_event="test_fee_hydration")

    row = store.list_broker_fill_ledger()[0]
    assert row["fee"] is None
    assert row["fee_currency"] is None
    assert row["tca_status"] == "UNKNOWN"
    assert store.count_table_rows("fills") == 0
    summary = router._broker_fee_hydration_summary()
    assert summary["broker_fee_hydration_count"] == 0
    assert summary["broker_fee_hydration_unmatched_count"] == 1
    assert summary["tca_fee_pending_count"] == 1


def test_ambiguous_composite_fee_activity_remains_conflict_not_attached(tmp_path):
    router, store, _adapter = _router(
        tmp_path,
        [
            {
                "id": "fee-activity-ambiguous",
                "activity_type": "FEE",
                "symbol": "BTCUSD",
                "net_amount": "-0.03",
                "currency": "USD",
                "transaction_time": T0,
            }
        ],
    )
    _partial_fill(store, fill_id="fill-1", broker_order_id="broker-1")
    _partial_fill(store, fill_id="fill-2", broker_order_id="broker-2")

    router._hydrate_deferred_broker_fees(source_event="test_fee_hydration")

    rows = store.list_broker_fill_ledger()
    assert {row["fee"] for row in rows} == {None}
    summary = router._broker_fee_hydration_summary()
    assert summary["broker_fee_hydration_count"] == 0
    assert summary["broker_fee_hydration_conflict_count"] == 2


def test_repeated_fee_hydration_does_not_duplicate_ledger_or_legacy_fills(tmp_path):
    router, store, _adapter = _router(
        tmp_path,
        [
            {
                "id": "fee-activity-1",
                "activity_type": "CFEE",
                "order_id": "broker-1",
                "symbol": "BTCUSD",
                "net_amount": "-0.12",
                "currency": "USD",
                "transaction_time": T0,
            }
        ],
    )
    _partial_fill(store)

    router._hydrate_deferred_broker_fees(source_event="first_pass")
    router._hydrate_deferred_broker_fees(source_event="second_pass")

    assert store.count_table_rows("broker_fill_ledger") == 1
    assert store.count_table_rows("fills") == 1
    summary = router._broker_fee_hydration_summary()
    assert summary["broker_fee_hydration_count"] == 1
    assert summary["broker_fee_hydration_conflict_count"] == 0
