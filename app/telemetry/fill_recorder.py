"""
Fill Recorder Ã¢â‚¬â€ captures FillEvent and rejection events.

Seams:
- OrderRouter: on fill detection (paper and live)
- OrderRouter: on rejection detection
"""

import logging
from typing import Optional, Dict, Any, List
from uuid import uuid4

from app.models.contracts import FillEvent, EventEnvelope
from app.models.enums import EventType
from app.telemetry.event_store import TelemetryEventStore
from app.utils.time_utils import now_ns

logger = logging.getLogger(__name__)


def _safe_side_value(value: Any) -> str:
    """Safely serialize side as string for telemetry payloads."""
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def _supports_order_rejected_event_type() -> bool:
    """Check whether EventType authority exposes ORDER_REJECTED."""
    return hasattr(EventType, "ORDER_REJECTED")


_REPLAY_METADATA_KEYS = (
    "canonical_aggression_contract",
    "aggression_replay_proof",
    "execution_is_attack_source",
    "execution_is_attack_matches_contract",
    "is_attack",
    "portfolio_replay_context",
    "exposure_snapshot_replay_context",
    "advisory_aggression_metadata_present",
    "advisory_aggression_snapshot_id",
)


def _attach_replay_metadata(payload: Dict[str, Any], metadata: Optional[Dict[str, Any]]) -> None:
    """Copy replay/audit metadata into telemetry without creating authority."""
    if not isinstance(metadata, dict):
        return

    payload["order_metadata"] = metadata
    for key in _REPLAY_METADATA_KEYS:
        if key in metadata:
            payload[key] = metadata[key]


class FillRecorder:
    """
    Records FillEvent fills and decision-linked rejections to telemetry.

    Authority boundary:
    - decision_uuid is the sequencing key for event chains.
    - FillRecorder does not own execution authority.
    - FillRecorder must not create orders or fills.

    Usage:
        recorder = FillRecorder(event_store)
        recorder.record_fill(fill_event)
        recorder.record_rejection(client_order_id, decision_uuid, reason)
    """

    def __init__(self, event_store: TelemetryEventStore):
        self._store = event_store
        self._sequence_map: Dict[str, int] = {}
        logger.info("FillRecorder initialized")

    def _next_sequence(self, decision_uuid: str) -> int:
        """Get next sequence number keyed by decision_uuid."""
        if decision_uuid not in self._sequence_map:
            self._sequence_map[decision_uuid] = 0
        seq = self._sequence_map[decision_uuid]
        self._sequence_map[decision_uuid] += 1
        return seq

    def record_fill(
        self,
        fill_event: FillEvent,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Record a fill as a telemetry event.

        Args:
            fill_event: FillEvent from order router

        Returns:
            event_id
        """
        payload = {
            "fill_event_id": fill_event.fill_event_id,
            "execution_event_id": fill_event.execution_event_id,
            "order_intent_id": fill_event.order_intent_id,
            "decision_uuid": fill_event.decision_uuid,
            "symbol": fill_event.symbol,
            "side": _safe_side_value(fill_event.side),
            "quantity": str(fill_event.quantity),
            "price": str(fill_event.price),
            "fee": str(fill_event.fee),
            "fee_currency": fill_event.fee_currency,
            "venue_fill_id": fill_event.venue_fill_id,
            "exchange_ts_ns": fill_event.exchange_ts_ns,
        }
        _attach_replay_metadata(payload, metadata)

        event = EventEnvelope(
            event_id=fill_event.fill_event_id,
            decision_uuid=fill_event.decision_uuid,
            parent_uuid=fill_event.execution_event_id,
            event_type=EventType.FILL,
            source_module="order_router",
            exchange_ts_ns=fill_event.exchange_ts_ns,
            receive_ts_ns=fill_event.receive_ts_ns,
            decision_ts_ns=fill_event.exchange_ts_ns,
            sequence=self._next_sequence(fill_event.decision_uuid),
            payload=payload,
            schema_version=1,
        )

        self._store.record_event(event)
        logger.info(f"Fill recorded: {fill_event.fill_event_id} for decision {fill_event.decision_uuid}")
        return event.event_id

    def record_order_submitted(
        self,
        client_order_id: str,
        decision_uuid: str,
        symbol: str,
        side: Any,
        quantity: Any,
        order_type: Any,
        *,
        exchange_ts_ns: int,
        receive_ts_ns: int,
        limit_price: Optional[Any] = None,
        venue_order_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Record first-class order submission telemetry for replay chains."""
        payload = {
            "telemetry_event": "order_submitted",
            "client_order_id": client_order_id,
            "decision_uuid": decision_uuid,
            "symbol": str(symbol),
            "side": _safe_side_value(side),
            "quantity": str(quantity),
            "order_type": str(order_type.value) if hasattr(order_type, "value") else str(order_type),
            "limit_price": str(limit_price) if limit_price is not None else None,
            "venue_order_id": str(venue_order_id) if venue_order_id is not None else None,
            "exchange_ts_ns": int(exchange_ts_ns),
            "receive_ts_ns": int(receive_ts_ns),
        }
        _attach_replay_metadata(payload, metadata)

        submit_ts_ns = int(receive_ts_ns)
        event = EventEnvelope(
            event_id=str(uuid4()),
            decision_uuid=decision_uuid,
            parent_uuid=None,
            event_type=EventType.ORDER,
            source_module="order_router",
            exchange_ts_ns=submit_ts_ns,
            receive_ts_ns=submit_ts_ns,
            decision_ts_ns=submit_ts_ns,
            sequence=self._next_sequence(decision_uuid),
            payload=payload,
            schema_version=1,
        )

        self._store.record_event(event)
        logger.info("Order submission recorded: %s decision=%s", client_order_id, decision_uuid)
        return event.event_id

    def record_rejection(
        self,
        client_order_id: str,
        decision_uuid: str,
        reason: str,
        reject_ts_ns: Optional[int] = None,
        symbol: Optional[str] = None,
        side: Optional[Any] = None,
        quantity: Optional[Any] = None,
        order_type: Optional[Any] = None,
        limit_price: Optional[Any] = None,
        venue_order_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Record an order rejection as a telemetry event.

        Args:
            client_order_id: Client order ID that was rejected
            decision_uuid: Decision UUID that generated the order
            reason: Rejection reason
            reject_ts_ns: Rejection timestamp (defaults to now)

        Returns:
            event_id
        """
        if reject_ts_ns is None:
            reject_ts_ns = now_ns()

        payload = {
            "client_order_id": client_order_id,
            "decision_uuid": decision_uuid,
            "reason": reason,
            "reject_ts_ns": reject_ts_ns,
        }
        if symbol is not None:
            payload["symbol"] = str(symbol)
        if side is not None:
            payload["side"] = _safe_side_value(side)
        if quantity is not None:
            payload["quantity"] = str(quantity)
        if order_type is not None:
            payload["order_type"] = str(order_type.value) if hasattr(order_type, "value") else str(order_type)
        if limit_price is not None:
            payload["limit_price"] = str(limit_price)
        if venue_order_id is not None:
            payload["venue_order_id"] = str(venue_order_id)
        _attach_replay_metadata(payload, metadata)

        event_id = str(uuid4())
        event_type = EventType.ORDER_REJECTED if _supports_order_rejected_event_type() else EventType.ERROR
        event = EventEnvelope(
            event_id=event_id,
            decision_uuid=decision_uuid,
            parent_uuid=None,
            event_type=event_type,
            source_module="order_router",
            exchange_ts_ns=reject_ts_ns,
            receive_ts_ns=now_ns(),
            decision_ts_ns=reject_ts_ns,
            sequence=self._next_sequence(decision_uuid),
            payload=payload,
            schema_version=1,
        )

        if not _supports_order_rejected_event_type():
            event.event_type = "order_rejected"

        self._store.record_event(event)
        logger.warning(f"Rejection recorded: {client_order_id} - {reason}")
        return event.event_id

    def get_fills_for_decision(self, decision_uuid: str) -> List[Dict[str, Any]]:
        """Get all fills for a decision."""
        events = self._store.get_decision_chain(decision_uuid)
        return [e for e in events if e["event_type"] == "fill"]

    def get_fill_latency_ms(self, fill_event_id: str) -> Optional[float]:
        """
        Calculate decision-to-fill latency in milliseconds.

        Requires fill event to have decision_uuid and exchange_ts_ns.
        """
        events = self._store.get_events_by_type("fill", limit=1000)
        for event in events:
            if event["event_id"] == fill_event_id:
                decision_uuid = event["decision_uuid"]
                if decision_uuid:
                    outcome = self._store.get_decision_outcome(decision_uuid)
                    if outcome["first_order_ts_ns"] and event["exchange_ts_ns"]:
                        return (event["exchange_ts_ns"] - outcome["first_order_ts_ns"]) / 1_000_000.0
        return None
