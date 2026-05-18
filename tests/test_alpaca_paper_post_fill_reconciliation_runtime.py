from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest

from app.telemetry.event_store import TelemetryEventStore
from app.telemetry.fill_recorder import FillRecorder
from app.utils.time_utils import now_ns


EXPECTED_PAPER_BASE_URL = "https://paper-api.alpaca.markets"
APPROVAL_ENV = "POVERTY_KILLER_APPROVE_ALPACA_PAPER_TINY_ORDER_25Z"
BROKER_ORDER_ID = "b47cdef4-a913-4517-9cac-5d96f319de91"
CLIENT_ORDER_ID = "pk25z-paper-aapl-buy-limit-day-1777948800000000100"
LOCAL_DECISION_ID = "manual-alpaca-paper-25z-b-no-decision-compiler"
ORDER_INTENT_ID = f"external-alpaca-paper-intent:{CLIENT_ORDER_ID}"
EXECUTION_EVENT_ID = f"alpaca-paper-execution:{BROKER_ORDER_ID}"
ALLOWED_GET_PATHS = frozenset(
    {
        "/v2/account",
        "/v2/positions",
        "/v2/orders",
        "/v2/account/activities",
        "/v2/clock",
    }
)
TERMINAL_STATUSES = frozenset({"filled"})
ACTIVE_ORDER_STATUSES = frozenset({"accepted", "new", "pending_new", "open", "accepted_for_bidding"})


@dataclass(frozen=True)
class RecordedAlpacaOrder:
    broker_order_id: str = BROKER_ORDER_ID
    client_order_id: str = CLIENT_ORDER_ID
    symbol: str = "AAPL"
    side: str = "buy"
    order_type: str = "limit"
    time_in_force: str = "day"
    qty: Decimal = Decimal("0.016903")
    filled_qty: Decimal = Decimal("0.016903")
    limit_price: Decimal = Decimal("295.79")
    status: str = "filled"
    submitted_at: str = "2026-05-18T17:10:54.81619546Z"
    created_at: str = "2026-05-18T17:10:54.81619546Z"
    updated_at: str = "2026-05-18T17:10:54.832884729Z"
    actual_fill_price: Decimal | None = None
    average_fill_price: Decimal | None = None
    fee: Decimal | None = None
    fee_currency: str | None = None
    venue_fill_id: str | None = None


@dataclass(frozen=True)
class RuntimeProjection:
    processed_keys: frozenset[str] = frozenset()
    telemetry_candidates: tuple[dict[str, Any], ...] = ()
    open_reservations: tuple[dict[str, Any], ...] = ()
    exposure_mutated: bool = False
    live_reservation_lifecycle_activated: bool = False

    def ingest(self, evidence: dict[str, Any]) -> tuple["RuntimeProjection", dict[str, Any]]:
        key = evidence["idempotency_key"]
        if key in self.processed_keys:
            return self, {"applied": False, "idempotent": True, "idempotency_key": key}
        next_projection = replace(
            self,
            processed_keys=self.processed_keys | {key},
            telemetry_candidates=self.telemetry_candidates + (evidence,),
        )
        return next_projection, {"applied": True, "idempotent": False, "idempotency_key": key}


class AlpacaReadOnlyClient:
    def __init__(self, base_url: str, key_id: str, secret_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._key_id = key_id
        self._secret_key = secret_key
        self.calls: list[tuple[str, str]] = []

    def get_json(self, path: str, query: dict[str, str] | None = None) -> Any:
        self._validate_get(path, query)
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "APCA-API-KEY-ID": self._key_id,
                "APCA-API-SECRET-KEY": self._secret_key,
                "Accept": "application/json",
            },
        )
        self.calls.append(("GET", path))
        try:
            with urllib.request.urlopen(request, timeout=10.0) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            pytest.skip(f"Alpaca PAPER read-only lookup unavailable: HTTP {exc.code}: {body[:120]}")
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            pytest.skip(f"Alpaca PAPER read-only network unavailable: {type(exc).__name__}")

    def _validate_get(self, path: str, query: dict[str, str] | None) -> None:
        assert self.base_url == EXPECTED_PAPER_BASE_URL
        if path.startswith("/v2/orders/"):
            suffix = path.removeprefix("/v2/orders/")
            assert suffix and "/" not in suffix
            assert query is None
            return
        assert path in ALLOWED_GET_PATHS
        assert path != "/v2/orders" or (query or {}).get("status") == "open"
        blocked = ("submit", "cancel", "replace", "close", "liquidate")
        assert not any(fragment in path.lower() for fragment in blocked)


def _d(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    return Decimal(str(value))


def _event_ts_ns(timestamp: str) -> int:
    return int(datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp() * 1_000_000_000)


def _recorded_order_from_broker_payload(payload: dict[str, Any]) -> RecordedAlpacaOrder:
    return RecordedAlpacaOrder(
        broker_order_id=str(payload.get("id") or payload.get("broker_order_id") or ""),
        client_order_id=str(payload.get("client_order_id") or ""),
        symbol=str(payload.get("symbol") or ""),
        side=str(payload.get("side") or ""),
        order_type=str(payload.get("type") or ""),
        time_in_force=str(payload.get("time_in_force") or ""),
        qty=_d(payload.get("qty")) or Decimal("0"),
        filled_qty=_d(payload.get("filled_qty")) or Decimal("0"),
        limit_price=_d(payload.get("limit_price")) or Decimal("0"),
        status=str(payload.get("status") or ""),
        submitted_at=str(payload.get("submitted_at") or payload.get("created_at") or ""),
        created_at=str(payload.get("created_at") or ""),
        updated_at=str(payload.get("updated_at") or ""),
        actual_fill_price=_d(payload.get("filled_avg_price") or payload.get("avg_fill_price")),
        average_fill_price=_d(payload.get("filled_avg_price") or payload.get("avg_fill_price")),
    )


def _assert_recorded_order_identity(order: RecordedAlpacaOrder) -> None:
    assert order.broker_order_id == BROKER_ORDER_ID
    assert order.client_order_id == CLIENT_ORDER_ID
    assert order.symbol == "AAPL"
    assert order.side == "buy"
    assert order.order_type == "limit"
    assert order.time_in_force == "day"
    assert order.qty == Decimal("0.016903")
    assert order.filled_qty == Decimal("0.016903")
    assert order.limit_price == Decimal("295.79")
    assert order.status in TERMINAL_STATUSES


def _order_mapping(order: RecordedAlpacaOrder) -> dict[str, Any]:
    _assert_recorded_order_identity(order)
    return {
        "broker_order_id": order.broker_order_id,
        "client_order_id": order.client_order_id,
        "order_intent_id": ORDER_INTENT_ID,
        "decision_uuid": LOCAL_DECISION_ID,
        "decision_uuid_gap": "manual broker-paper order outside DecisionCompiler",
        "execution_event_id": EXECUTION_EVENT_ID,
        "execution_event_id_candidate": EXECUTION_EVENT_ID,
        "symbol": order.symbol,
        "side": order.side,
        "requested_qty": str(order.qty),
        "filled_qty": str(order.filled_qty),
        "price_basis": str(order.limit_price),
        "source": "alpaca paper",
        "status_source": "broker read-only truth",
        "submitted_at": order.submitted_at,
        "updated_at": order.updated_at,
        "mapping_cardinality": "one_to_one",
        "idempotency_key": f"alpaca-paper-fill:{order.broker_order_id}:{order.client_order_id}:filled:{order.filled_qty}",
    }


def _fill_evidence(order: RecordedAlpacaOrder, *, receive_ts_ns: int) -> dict[str, Any]:
    mapping = _order_mapping(order)
    deterministic_fill_id = f"deterministic-no-venue-fill-id:{order.broker_order_id}:{order.filled_qty}"
    actual_price = order.actual_fill_price or order.average_fill_price
    return {
        **mapping,
        "fill_event_id": f"fill-candidate:{mapping['idempotency_key']}",
        "venue_fill_id": order.venue_fill_id or deterministic_fill_id,
        "venue_fill_id_gap": order.venue_fill_id is None,
        "venue_fill_id_label": "deterministic idempotency candidate; broker venue fill id absent",
        "requested_qty": str(order.qty),
        "filled_qty": str(order.filled_qty),
        "cumulative_filled_qty": str(order.filled_qty),
        "remaining_qty": "0",
        "limit_price": str(order.limit_price),
        "actual_fill_price": str(actual_price) if actual_price is not None else None,
        "average_fill_price": str(order.average_fill_price) if order.average_fill_price is not None else None,
        "price_basis": str(actual_price if actual_price is not None else order.limit_price),
        "price_basis_label": "actual_fill_price" if actual_price is not None else "limit_price_only_not_actual_execution_price",
        "fee": str(order.fee) if order.fee is not None else None,
        "fee_currency": order.fee_currency,
        "exchange_ts_ns": _event_ts_ns(order.updated_at or order.submitted_at),
        "receive_ts_ns": receive_ts_ns,
        "status": order.status,
        "source": "alpaca paper read-only",
        "missing_actual_fill_price_gap": actual_price is None,
        "missing_fee_gap": order.fee is None,
        "missing_fee_currency_gap": order.fee_currency is None,
        "missing_slippage_gap": True,
        "missing_net_edge_gap": True,
        "pnl_claimed": False,
        "profitability_claimed": False,
    }


def _economic_truth(order: RecordedAlpacaOrder) -> dict[str, Any]:
    _assert_recorded_order_identity(order)
    limit_price_notional = (order.filled_qty * order.limit_price).quantize(Decimal("0.00000001"))
    return {
        "economics_truth_status": "partial/passive",
        "limit_price_notional_estimate": str(limit_price_notional),
        "notional_label": "limit-price notional estimate",
        "planned_max_notional": "5.00",
        "within_planned_cap": limit_price_notional <= Decimal("5.00"),
        "missing_fee_gap": order.fee is None,
        "missing_actual_fill_price_gap": order.actual_fill_price is None and order.average_fill_price is None,
        "missing_slippage_gap": True,
        "missing_net_edge_gap": True,
        "pnl_computed": False,
        "slippage_computed": False,
        "net_edge_computed": False,
        "profitability_claimed": False,
    }


def _release_candidate(evidence: dict[str, Any]) -> dict[str, Any]:
    assert evidence["broker_order_id"]
    assert evidence["client_order_id"]
    assert evidence["status"] == "filled"
    assert Decimal(evidence["filled_qty"]) > Decimal("0")
    assert evidence["remaining_qty"] == "0"
    return {
        "candidate_type": "release",
        "release_candidate_only": True,
        "open_candidate_only": False,
        "adjust_candidate_only": False,
        "reservation_authority": False,
        "exposure_reservation_mutated": False,
        "reservation_mutation_performed": False,
        "exposure_release_performed": False,
        "reservation_release_performed": False,
        "active_reservation_ledger_created": False,
        "client_order_id": evidence["client_order_id"],
        "broker_order_id": evidence["broker_order_id"],
        "terminal_state": "filled",
        "terminal_truth_required": True,
        "filled_qty": evidence["filled_qty"],
        "reservation_dedupe_key": f"{LOCAL_DECISION_ID}:{ORDER_INTENT_ID}",
        "release_idempotency_key": f"{evidence['idempotency_key']}:release-candidate",
        "local_reservation_status": "absent_expected_external_manual_paper_order",
    }


def _reconcile_runtime_state(
    *,
    order: RecordedAlpacaOrder,
    open_orders: list[dict[str, Any]],
    positions: list[dict[str, Any]],
    account: dict[str, Any] | None,
) -> dict[str, Any]:
    active_matches = [
        item
        for item in open_orders
        if (item.get("client_order_id") == order.client_order_id or item.get("id") == order.broker_order_id)
        and str(item.get("status") or "").lower() in ACTIVE_ORDER_STATUSES
    ]
    aapl_positions = [item for item in positions if str(item.get("symbol") or "").upper() == "AAPL" and (_d(item.get("qty")) or Decimal("0")) != 0]
    return {
        "terminal_filled_order_truth_wins": order.status == "filled",
        "matching_active_open_order_count": len(active_matches),
        "open_order_resurrected": bool(active_matches),
        "position_current": "present" if aapl_positions else "not_reconfirmed",
        "position_qty": str(_d(aapl_positions[0].get("qty"))) if aapl_positions else None,
        "flat_assumed": False,
        "broker_position_truth_canonical_if_present": True,
        "account_truth_available": bool(account),
        "local_bot_state_position_gap": "expected_external_paper_order_not_decision_compiler_path",
        "readiness_after_fill": "no_go_until_broker_position_and_local_runtime_reconciled",
    }


def _env_or_skip() -> tuple[str, str, str]:
    base_url = (os.environ.get("APCA_API_BASE_URL") or "").rstrip("/")
    key_id = os.environ.get("APCA_API_KEY_ID") or ""
    secret_key = os.environ.get("APCA_API_SECRET_KEY") or ""
    if not base_url or not key_id or not secret_key:
        pytest.skip("Alpaca PAPER read-only credentials unavailable")
    if base_url != EXPECTED_PAPER_BASE_URL:
        pytest.fail(f"APCA_API_BASE_URL is not exact paper endpoint: {base_url!r}")
    return base_url, key_id, secret_key


def test_recorded_order_mapping_is_one_to_one_and_fails_closed_on_identity_gaps():
    order = RecordedAlpacaOrder()
    mapping = _order_mapping(order)

    assert mapping["broker_order_id"] == BROKER_ORDER_ID
    assert mapping["client_order_id"] == CLIENT_ORDER_ID
    assert mapping["order_intent_id"] == ORDER_INTENT_ID
    assert mapping["execution_event_id_candidate"] == EXECUTION_EVENT_ID
    assert mapping["mapping_cardinality"] == "one_to_one"
    assert mapping["decision_uuid_gap"] == "manual broker-paper order outside DecisionCompiler"

    bad_cases = [
        replace(order, broker_order_id=""),
        replace(order, client_order_id=""),
        replace(order, symbol="MSFT"),
        replace(order, side="sell"),
        replace(order, qty=Decimal("0.016904")),
        replace(order, filled_qty=Decimal("0")),
    ]
    for bad_order in bad_cases:
        with pytest.raises(AssertionError):
            _order_mapping(bad_order)


def test_fill_recorder_lifecycle_evidence_keeps_external_order_gaps_explicit(tmp_path):
    order = RecordedAlpacaOrder()
    evidence = _fill_evidence(order, receive_ts_ns=now_ns())
    store = TelemetryEventStore(str(tmp_path / "post_fill_runtime.db"))
    recorder = FillRecorder(store)

    event_id = recorder.record_order_lifecycle_event(
        lifecycle_phase="fill",
        client_order_id=order.client_order_id,
        decision_uuid=LOCAL_DECISION_ID,
        event_ts_ns=evidence["exchange_ts_ns"],
        lifecycle_source="alpaca_paper_post_fill_reconciliation",
        symbol=order.symbol,
        side=order.side,
        order_type=order.order_type,
        limit_price=order.limit_price,
        submit_seen=True,
        full_fill_seen=True,
        terminal_state="filled",
        terminal_reason="alpaca_paper_order_status_filled",
        broker_order_id=order.broker_order_id,
        venue_order_id=order.broker_order_id,
        venue_fill_id=evidence["venue_fill_id"],
        original_qty=order.qty,
        fill_delta_qty=order.filled_qty,
        cumulative_filled_qty=order.filled_qty,
        remaining_qty=Decimal("0"),
        avg_fill_price=None,
        cumulative_fee=None,
        is_terminal=True,
        status_source="alpaca_paper_read_only_order_lookup",
        id_mapping_source="alpaca_paper_client_and_broker_order_id",
        idempotency_key=evidence["idempotency_key"],
        metadata={
            "decision_uuid_gap": "manual broker-paper order outside DecisionCompiler",
            "order_intent_id": ORDER_INTENT_ID,
            "execution_event_id_candidate": EXECUTION_EVENT_ID,
            "actual_fill_price_gap": "broker order payload did not provide actual fill price in recorded truth",
            "fee_gap": "broker order payload did not provide fee in recorded truth",
            "fee_currency_gap": "broker order payload did not provide fee currency in recorded truth",
            "pnl_claimed": False,
            "slippage_claimed": False,
            "net_edge_claimed": False,
            "profitability_claimed": False,
        },
    )

    events = store.get_decision_chain(LOCAL_DECISION_ID)
    payload = json.loads(next(event["payload_json"] for event in events if event["event_id"] == event_id))
    context = payload["order_lifecycle_replay_context"]
    candidate = payload["reservation_candidate_delta"]

    assert payload["client_order_id"] == CLIENT_ORDER_ID
    assert payload["broker_order_id"] == BROKER_ORDER_ID
    assert payload["venue_order_id"] == BROKER_ORDER_ID
    assert payload["avg_fill_price"] is None
    assert payload["cumulative_fee"] is None
    assert payload["limit_price"] == "295.79"
    assert payload["order_metadata"]["decision_uuid_gap"] == "manual broker-paper order outside DecisionCompiler"
    assert payload["order_metadata"]["actual_fill_price_gap"]
    assert payload["order_metadata"]["fee_gap"]
    assert payload["order_metadata"]["fee_currency_gap"]
    assert payload["order_metadata"]["pnl_claimed"] is False
    assert payload["order_metadata"]["slippage_claimed"] is False
    assert payload["order_metadata"]["net_edge_claimed"] is False
    assert payload["order_metadata"]["profitability_claimed"] is False
    assert context["is_terminal"] is True
    assert context["terminal_state"] == "filled"
    assert context["remaining_qty"] == "0"
    assert context["cumulative_filled_qty"] == "0.016903"
    assert context["mapping_authoritative"] is False
    assert context["exposure_reservation_authority"] is False
    assert context["exposure_reservation_mutated"] is False
    assert candidate["release_candidate_only"] is True
    assert candidate["reservation_authority"] is False
    assert candidate["reservation_release_performed"] is False
    assert candidate["active_reservation_ledger_created"] is False


def test_economic_truth_is_partial_passive_and_never_claims_profitability():
    economics = _economic_truth(RecordedAlpacaOrder())

    assert economics["economics_truth_status"] == "partial/passive"
    assert economics["limit_price_notional_estimate"] == "4.99973837"
    assert economics["notional_label"] == "limit-price notional estimate"
    assert economics["within_planned_cap"] is True
    assert economics["missing_fee_gap"] is True
    assert economics["missing_actual_fill_price_gap"] is True
    assert economics["missing_slippage_gap"] is True
    assert economics["missing_net_edge_gap"] is True
    assert economics["pnl_computed"] is False
    assert economics["profitability_claimed"] is False


def test_release_candidate_and_replay_projection_are_idempotent_without_mutation():
    evidence = _fill_evidence(RecordedAlpacaOrder(), receive_ts_ns=now_ns())
    candidate = _release_candidate(evidence)
    projection = RuntimeProjection()

    projection, first = projection.ingest({**evidence, "reservation_candidate_delta": candidate})
    projection, duplicate = projection.ingest({**evidence, "reservation_candidate_delta": candidate})

    assert first["applied"] is True
    assert duplicate["idempotent"] is True
    assert len(projection.telemetry_candidates) == 1
    assert projection.open_reservations == ()
    assert projection.exposure_mutated is False
    assert projection.live_reservation_lifecycle_activated is False
    assert candidate["local_reservation_status"] == "absent_expected_external_manual_paper_order"
    assert candidate["release_candidate_only"] is True
    assert candidate["open_candidate_only"] is False
    assert candidate["reservation_release_performed"] is False
    assert os.environ.get(APPROVAL_ENV) is None


def test_position_account_open_order_reconciliation_blocks_flat_assumptions_offline():
    reconciliation = _reconcile_runtime_state(
        order=RecordedAlpacaOrder(),
        open_orders=[],
        positions=[],
        account={"status": "ACTIVE", "cash": "1000.00"},
    )

    assert reconciliation["terminal_filled_order_truth_wins"] is True
    assert reconciliation["matching_active_open_order_count"] == 0
    assert reconciliation["open_order_resurrected"] is False
    assert reconciliation["position_current"] == "not_reconfirmed"
    assert reconciliation["flat_assumed"] is False
    assert reconciliation["broker_position_truth_canonical_if_present"] is True
    assert reconciliation["local_bot_state_position_gap"] == "expected_external_paper_order_not_decision_compiler_path"
    assert reconciliation["readiness_after_fill"] == "no_go_until_broker_position_and_local_runtime_reconciled"


def test_real_alpaca_paper_read_only_reconfirmation_if_env_network_available():
    base_url, key_id, secret_key = _env_or_skip()
    client = AlpacaReadOnlyClient(base_url, key_id, secret_key)

    order_payload = client.get_json(f"/v2/orders/{BROKER_ORDER_ID}")
    open_orders = client.get_json("/v2/orders", {"status": "open", "limit": "50", "nested": "false"})
    positions = client.get_json("/v2/positions")
    account = client.get_json("/v2/account")
    activities = client.get_json("/v2/account/activities", {"activity_types": "FILL", "page_size": "100"})

    order = _recorded_order_from_broker_payload(order_payload)
    _assert_recorded_order_identity(order)
    reconciliation = _reconcile_runtime_state(
        order=order,
        open_orders=open_orders if isinstance(open_orders, list) else [],
        positions=positions if isinstance(positions, list) else [],
        account=account if isinstance(account, dict) else {},
    )
    activity_items = activities.get("activities", activities) if isinstance(activities, dict) else activities
    matching_activities = [
        item
        for item in (activity_items or ())
        if isinstance(item, dict)
        and (item.get("order_id") == BROKER_ORDER_ID or item.get("client_order_id") == CLIENT_ORDER_ID)
    ]

    assert all(method == "GET" for method, _path in client.calls)
    assert ("GET", f"/v2/orders/{BROKER_ORDER_ID}") in client.calls
    assert ("GET", "/v2/orders") in client.calls
    assert reconciliation["matching_active_open_order_count"] == 0
    assert reconciliation["terminal_filled_order_truth_wins"] is True
    assert reconciliation["flat_assumed"] is False

    summary = {
        "broker_order_id": order.broker_order_id,
        "client_order_id": order.client_order_id,
        "status": order.status,
        "open_matching_active_orders": reconciliation["matching_active_open_order_count"],
        "position_current": reconciliation["position_current"],
        "position_qty": reconciliation["position_qty"],
        "activity_fill_found": bool(matching_activities),
        "activity_fill_price": str(_d(matching_activities[0].get("price"))) if matching_activities else None,
        "activity_fee": str(_d(matching_activities[0].get("commission"))) if matching_activities else None,
        "activity_fee_currency": account.get("currency") if matching_activities and isinstance(account, dict) else None,
    }
    print("ALPACA_26A_READ_ONLY_SUMMARY=" + json.dumps(summary, sort_keys=True))
