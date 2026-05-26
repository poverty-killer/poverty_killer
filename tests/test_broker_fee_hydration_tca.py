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
from app.execution.order_router import OrderRouter
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


def _router(tmp_path, activities: list[dict]) -> tuple[OrderRouter, StateStore, FeeActivityAdapter]:
    store = _store(tmp_path)
    adapter = FeeActivityAdapter(activities)
    router = OrderRouter(
        primary_exchange="alpaca",
        paper_mode=True,
        execution_broker="alpaca_paper",
        broker_gateway_adapter=adapter,
        state_store=store,
    )
    return router, store, adapter


def test_alpaca_fee_activity_query_uses_read_only_cfee_fee_endpoint():
    transport = CaptureTransport(payload=[])
    adapter = AlpacaPaperBrokerAdapter(
        AlpacaPaperCredentials(
            base_url=EXPECTED_ALPACA_PAPER_BASE_URL,
            key_id="paper-key",
            secret_key="paper-secret",
        ),
        transport=transport,
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
    assert rows[0]["fee_bps"] == str((Decimal("0.12") / Decimal("100")) * Decimal("10000"))
    assert rows[0]["tca_status"] == "HYDRATED"
    assert store.count_table_rows("fills") == 1
    summary = router._broker_fee_hydration_summary()
    assert summary["broker_fee_hydration_count"] == 1
    assert summary["broker_fee_hydration_conflict_count"] == 0
    assert summary["tca_complete_count"] == 1
    assert adapter.activity_type_requests == ["CFEE,FEE"]


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
