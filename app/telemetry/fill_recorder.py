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


def _safe_decimal_product(left: Optional[Any], right: Optional[Any]) -> Optional[str]:
    if left is None or right is None:
        return None
    try:
        from decimal import Decimal

        return str(Decimal(str(left)) * Decimal(str(right)))
    except Exception:
        return None


def build_passive_reservation_candidate_delta(
    *,
    lifecycle_phase: str,
    client_order_id: str,
    decision_uuid: Optional[str] = None,
    symbol: Optional[str] = None,
    side: Optional[Any] = None,
    quantity: Optional[Any] = None,
    price_basis: Optional[Any] = None,
    fill_delta_qty: Optional[Any] = None,
    cumulative_filled_qty: Optional[Any] = None,
    remaining_qty: Optional[Any] = None,
    terminal_state: Optional[str] = None,
    terminal_reason: Optional[str] = None,
    status_source: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Build passive reservation evidence without creating reservation authority."""
    phase = str(lifecycle_phase)
    open_candidate = phase == "order_submitted"
    adjust_candidate = phase == "order_partially_filled"
    release_candidate = phase in {"full_fill", "fill", "terminal_mapping_proof"}
    if not (open_candidate or adjust_candidate or release_candidate):
        return None

    dedupe_key = f"{decision_uuid}:{client_order_id}" if decision_uuid else str(client_order_id)
    candidate_quantity = quantity
    if candidate_quantity is None:
        candidate_quantity = fill_delta_qty if fill_delta_qty is not None else remaining_qty

    return {
        "candidate_type": "open" if open_candidate else ("adjust" if adjust_candidate else "release"),
        "open_candidate_only": open_candidate,
        "adjust_candidate_only": adjust_candidate,
        "release_candidate_only": release_candidate,
        "reservation_authority": False,
        "exposure_reservation_mutated": False,
        "reservation_mutation_performed": False,
        "exposure_release_performed": False,
        "reservation_release_performed": False,
        "active_reservation_ledger_created": False,
        "client_order_id": str(client_order_id),
        "decision_uuid": str(decision_uuid) if decision_uuid is not None else None,
        "symbol": str(symbol) if symbol is not None else None,
        "side": _safe_side_value(side) if side is not None else None,
        "quantity": str(candidate_quantity) if candidate_quantity is not None else None,
        "price_basis": str(price_basis) if price_basis is not None else None,
        "notional": _safe_decimal_product(candidate_quantity, price_basis),
        "fill_delta_qty": str(fill_delta_qty) if fill_delta_qty is not None else None,
        "cumulative_filled_qty": str(cumulative_filled_qty) if cumulative_filled_qty is not None else None,
        "remaining_qty": str(remaining_qty) if remaining_qty is not None else None,
        "terminal_state": terminal_state,
        "terminal_reason": terminal_reason,
        "status_source": status_source,
        "reservation_dedupe_key": dedupe_key,
        "idempotency_key": idempotency_key,
        "source": "passive_order_lifecycle_telemetry",
    }


_REPLAY_METADATA_KEYS = (
    "canonical_aggression_contract",
    "aggression_replay_proof",
    "execution_is_attack_source",
    "execution_is_attack_matches_contract",
    "is_attack",
    "portfolio_replay_context",
    "exposure_snapshot_replay_context",
    "order_lifecycle_replay_context",
    "order_id_namespace",
    "passive_mapping_namespace",
    "passive_mapping_id_namespaces",
    "mapping_authoritative",
    "active_cancel_status_mapping_ready",
    "router_cache_authoritative",
    "reservation_mapping_ready",
    "reservation_delta_authoritative",
    "reservation_candidate_delta",
    "reservation_candidate_authoritative",
    "exposure_reservation_authority",
    "exposure_reservation_mutated",
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


def _passive_order_lifecycle_context(
    *,
    lifecycle_source: str,
    client_order_id: str,
    decision_uuid: str,
    lifecycle_phase: str,
    submit_seen: bool,
    symbol: Optional[str] = None,
    side: Optional[Any] = None,
    ack_seen: Optional[bool] = None,
    reject_seen: Optional[bool] = None,
    partial_fill_seen: Optional[bool] = None,
    full_fill_seen: Optional[bool] = None,
    cancel_seen: Optional[bool] = None,
    terminal_state: Optional[str] = None,
    terminal_reason: Optional[str] = None,
    venue_order_id: Optional[str] = None,
    broker_order_id: Optional[str] = None,
    exchange_txid: Optional[str] = None,
    venue_fill_id: Optional[str] = None,
    original_qty: Optional[Any] = None,
    fill_delta_qty: Optional[Any] = None,
    cumulative_filled_qty: Optional[Any] = None,
    remaining_qty: Optional[Any] = None,
    avg_fill_price: Optional[Any] = None,
    price_basis: Optional[Any] = None,
    cumulative_fee: Optional[Any] = None,
    is_terminal: Optional[bool] = None,
    status_source: Optional[str] = None,
    id_mapping_source: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Build passive lifecycle replay metadata without claiming authority."""
    passive_mapping_id_namespaces = ["client_order_id"]
    if venue_order_id is not None:
        passive_mapping_id_namespaces.append("venue_order_id")
    if broker_order_id is not None:
        passive_mapping_id_namespaces.append("broker_order_id")
    if exchange_txid is not None:
        passive_mapping_id_namespaces.append("exchange_txid")
    passive_mapping_namespace = (
        "client_order_id"
        if passive_mapping_id_namespaces == ["client_order_id"]
        else "mixed/passive"
    )

    resolved_idempotency_key = idempotency_key or f"{decision_uuid}:{client_order_id}:{lifecycle_phase}"
    reservation_candidate_delta = build_passive_reservation_candidate_delta(
        lifecycle_phase=lifecycle_phase,
        client_order_id=client_order_id,
        decision_uuid=decision_uuid,
        symbol=symbol,
        side=side,
        quantity=original_qty,
        price_basis=price_basis if price_basis is not None else avg_fill_price,
        fill_delta_qty=fill_delta_qty,
        cumulative_filled_qty=cumulative_filled_qty,
        remaining_qty=remaining_qty,
        terminal_state=terminal_state,
        terminal_reason=terminal_reason,
        status_source=status_source,
        idempotency_key=resolved_idempotency_key,
    )

    return {
        "lifecycle_context_version": 1,
        "lifecycle_source": lifecycle_source,
        "client_order_id": str(client_order_id),
        "venue_order_id": str(venue_order_id) if venue_order_id is not None else None,
        "decision_uuid": str(decision_uuid),
        "event_family": "order_lifecycle",
        "lifecycle_phase": lifecycle_phase,
        "order_id_namespace": "client_order_id",
        "passive_mapping_namespace": passive_mapping_namespace,
        "passive_mapping_id_namespaces": passive_mapping_id_namespaces,
        "submit_seen": bool(submit_seen),
        "ack_seen": ack_seen,
        "reject_seen": reject_seen,
        "partial_fill_seen": partial_fill_seen,
        "full_fill_seen": full_fill_seen,
        "cancel_seen": cancel_seen,
        "is_terminal": is_terminal,
        "terminal_state": terminal_state,
        "terminal_reason": terminal_reason,
        "broker_order_id": str(broker_order_id) if broker_order_id is not None else None,
        "exchange_txid": str(exchange_txid) if exchange_txid is not None else None,
        "venue_fill_id": str(venue_fill_id) if venue_fill_id is not None else None,
        "original_qty": str(original_qty) if original_qty is not None else None,
        "fill_delta_qty": str(fill_delta_qty) if fill_delta_qty is not None else None,
        "cumulative_filled_qty": (
            str(cumulative_filled_qty) if cumulative_filled_qty is not None else None
        ),
        "remaining_qty": str(remaining_qty) if remaining_qty is not None else None,
        "avg_fill_price": str(avg_fill_price) if avg_fill_price is not None else None,
        "cumulative_fee": str(cumulative_fee) if cumulative_fee is not None else None,
        "status_source": status_source,
        "id_mapping_source": id_mapping_source,
        "idempotency_key": resolved_idempotency_key,
        "mapping_authoritative": False,
        "active_cancel_status_mapping_ready": False,
        "router_cache_authoritative": False,
        "exposure_reservation_authority": False,
        "exposure_reservation_mutated": False,
        "reservation_mapping_ready": False,
        "reservation_delta_authoritative": False,
        "reservation_candidate_delta": reservation_candidate_delta,
        "reservation_candidate_authoritative": False,
    }


def _metadata_with_lifecycle_context(
    metadata: Optional[Dict[str, Any]],
    lifecycle_context: Dict[str, Any],
) -> Dict[str, Any]:
    """Attach fallback passive lifecycle metadata without mutating caller input."""
    result = dict(metadata) if isinstance(metadata, dict) else {}
    result.setdefault("order_lifecycle_replay_context", lifecycle_context)
    result.setdefault("order_id_namespace", lifecycle_context.get("order_id_namespace"))
    result.setdefault("passive_mapping_namespace", lifecycle_context.get("passive_mapping_namespace"))
    result.setdefault("passive_mapping_id_namespaces", lifecycle_context.get("passive_mapping_id_namespaces"))
    result.setdefault("mapping_authoritative", False)
    result.setdefault("active_cancel_status_mapping_ready", False)
    result.setdefault("router_cache_authoritative", False)
    result.setdefault("reservation_mapping_ready", False)
    result.setdefault("reservation_delta_authoritative", False)
    result.setdefault("reservation_candidate_delta", lifecycle_context.get("reservation_candidate_delta"))
    result.setdefault("reservation_candidate_authoritative", False)
    result.setdefault("exposure_reservation_authority", False)
    result.setdefault("exposure_reservation_mutated", False)
    return result


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
        metadata = _metadata_with_lifecycle_context(
            metadata,
            _passive_order_lifecycle_context(
                lifecycle_source="fill_recorder.fill_event",
                client_order_id=fill_event.order_intent_id,
                decision_uuid=fill_event.decision_uuid,
                lifecycle_phase="fill",
                submit_seen=True,
                symbol=fill_event.symbol,
                side=fill_event.side,
                venue_fill_id=fill_event.venue_fill_id,
                original_qty=fill_event.quantity,
                cumulative_filled_qty=fill_event.quantity,
                avg_fill_price=fill_event.price,
                price_basis=fill_event.price,
                cumulative_fee=fill_event.fee,
                status_source="fill_recorder.fill_event",
                id_mapping_source="fill_event.order_intent_id",
            ),
        )

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
        broker_order_id: Optional[str] = None,
        exchange_txid: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Record first-class order submission telemetry for replay chains."""
        metadata = _metadata_with_lifecycle_context(
            metadata,
            _passive_order_lifecycle_context(
                lifecycle_source="fill_recorder.order_submitted",
                client_order_id=client_order_id,
                decision_uuid=decision_uuid,
                lifecycle_phase="order_submitted",
                submit_seen=True,
                symbol=symbol,
                side=side,
                venue_order_id=venue_order_id,
                broker_order_id=broker_order_id,
                exchange_txid=exchange_txid,
                original_qty=quantity,
                cumulative_filled_qty="0",
                remaining_qty=quantity,
                cumulative_fee="0",
                is_terminal=False,
                price_basis=limit_price,
                status_source="fill_recorder.order_submitted",
                id_mapping_source="fill_recorder.client_order_id",
            ),
        )

        payload = {
            "telemetry_event": "order_submitted",
            "event_family": "order_lifecycle",
            "lifecycle_phase": "order_submitted",
            "client_order_id": client_order_id,
            "decision_uuid": decision_uuid,
            "symbol": str(symbol),
            "side": _safe_side_value(side),
            "quantity": str(quantity),
            "order_type": str(order_type.value) if hasattr(order_type, "value") else str(order_type),
            "limit_price": str(limit_price) if limit_price is not None else None,
            "venue_order_id": str(venue_order_id) if venue_order_id is not None else None,
            "broker_order_id": str(broker_order_id) if broker_order_id is not None else None,
            "exchange_txid": str(exchange_txid) if exchange_txid is not None else None,
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

    def record_order_lifecycle_event(
        self,
        *,
        lifecycle_phase: str,
        client_order_id: str,
        decision_uuid: str,
        event_ts_ns: int,
        lifecycle_source: str,
        symbol: Optional[str] = None,
        side: Optional[Any] = None,
        order_type: Optional[Any] = None,
        limit_price: Optional[Any] = None,
        submit_seen: bool = True,
        ack_seen: Optional[bool] = None,
        reject_seen: Optional[bool] = None,
        partial_fill_seen: Optional[bool] = None,
        full_fill_seen: Optional[bool] = None,
        cancel_seen: Optional[bool] = None,
        terminal_state: Optional[str] = None,
        terminal_reason: Optional[str] = None,
        venue_order_id: Optional[str] = None,
        broker_order_id: Optional[str] = None,
        exchange_txid: Optional[str] = None,
        venue_fill_id: Optional[str] = None,
        original_qty: Optional[Any] = None,
        fill_delta_qty: Optional[Any] = None,
        cumulative_filled_qty: Optional[Any] = None,
        remaining_qty: Optional[Any] = None,
        avg_fill_price: Optional[Any] = None,
        cumulative_fee: Optional[Any] = None,
        is_terminal: Optional[bool] = None,
        status_source: Optional[str] = None,
        id_mapping_source: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Record passive order-lifecycle observations without creating authority.

        These events are replay/audit facts only. They do not mutate router,
        broker, risk, reservation, or cache state.
        """
        lifecycle_context = _passive_order_lifecycle_context(
            lifecycle_source=lifecycle_source,
            client_order_id=client_order_id,
            decision_uuid=decision_uuid,
            lifecycle_phase=lifecycle_phase,
            submit_seen=submit_seen,
            symbol=symbol,
            side=side,
            ack_seen=ack_seen,
            reject_seen=reject_seen,
            partial_fill_seen=partial_fill_seen,
            full_fill_seen=full_fill_seen,
            cancel_seen=cancel_seen,
            terminal_state=terminal_state,
            terminal_reason=terminal_reason,
            venue_order_id=venue_order_id,
            broker_order_id=broker_order_id,
            exchange_txid=exchange_txid,
            venue_fill_id=venue_fill_id,
            original_qty=original_qty,
            fill_delta_qty=fill_delta_qty,
            cumulative_filled_qty=cumulative_filled_qty,
            remaining_qty=remaining_qty,
            avg_fill_price=avg_fill_price,
            price_basis=limit_price if limit_price is not None else avg_fill_price,
            cumulative_fee=cumulative_fee,
            is_terminal=is_terminal,
            status_source=status_source,
            id_mapping_source=id_mapping_source,
            idempotency_key=idempotency_key,
        )
        metadata = _metadata_with_lifecycle_context(metadata, lifecycle_context)

        payload = {
            "telemetry_event": lifecycle_phase,
            "event_family": "order_lifecycle",
            "lifecycle_phase": lifecycle_phase,
            "client_order_id": str(client_order_id),
            "decision_uuid": str(decision_uuid),
            "venue_order_id": str(venue_order_id) if venue_order_id is not None else None,
            "broker_order_id": str(broker_order_id) if broker_order_id is not None else None,
            "exchange_txid": str(exchange_txid) if exchange_txid is not None else None,
            "venue_fill_id": str(venue_fill_id) if venue_fill_id is not None else None,
            "original_qty": str(original_qty) if original_qty is not None else None,
            "fill_delta_qty": str(fill_delta_qty) if fill_delta_qty is not None else None,
            "cumulative_filled_qty": (
                str(cumulative_filled_qty) if cumulative_filled_qty is not None else None
            ),
            "remaining_qty": str(remaining_qty) if remaining_qty is not None else None,
            "avg_fill_price": str(avg_fill_price) if avg_fill_price is not None else None,
            "cumulative_fee": str(cumulative_fee) if cumulative_fee is not None else None,
            "status_source": status_source,
            "id_mapping_source": id_mapping_source,
            "order_id_namespace": "client_order_id",
            "passive_mapping_namespace": lifecycle_context["passive_mapping_namespace"],
            "passive_mapping_id_namespaces": lifecycle_context["passive_mapping_id_namespaces"],
            "is_terminal": is_terminal,
            "terminal_state": terminal_state,
            "terminal_reason": terminal_reason,
            "idempotency_key": lifecycle_context["idempotency_key"],
            "mapping_authoritative": False,
            "active_cancel_status_mapping_ready": False,
            "router_cache_authoritative": False,
            "exposure_reservation_authority": False,
            "exposure_reservation_mutated": False,
            "reservation_mapping_ready": False,
            "reservation_delta_authoritative": False,
            "reservation_candidate_delta": None,
            "reservation_candidate_authoritative": False,
            "exchange_ts_ns": int(event_ts_ns),
        }
        if symbol is not None:
            payload["symbol"] = str(symbol)
        if side is not None:
            payload["side"] = _safe_side_value(side)
        if order_type is not None:
            payload["order_type"] = str(order_type.value) if hasattr(order_type, "value") else str(order_type)
        if limit_price is not None:
            payload["limit_price"] = str(limit_price)
        _attach_replay_metadata(payload, metadata)

        receive_ts_ns = max(now_ns(), int(event_ts_ns))
        event = EventEnvelope(
            event_id=str(uuid4()),
            decision_uuid=decision_uuid,
            parent_uuid=client_order_id,
            event_type=EventType.ORDER,
            source_module="order_router",
            exchange_ts_ns=int(event_ts_ns),
            receive_ts_ns=receive_ts_ns,
            decision_ts_ns=int(event_ts_ns),
            sequence=self._next_sequence(decision_uuid),
            payload=payload,
            schema_version=1,
        )

        self._store.record_event(event)
        logger.info("Order lifecycle recorded: %s order=%s decision=%s", lifecycle_phase, client_order_id, decision_uuid)
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
        broker_order_id: Optional[str] = None,
        exchange_txid: Optional[str] = None,
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
        if broker_order_id is not None:
            payload["broker_order_id"] = str(broker_order_id)
        if exchange_txid is not None:
            payload["exchange_txid"] = str(exchange_txid)
        metadata = _metadata_with_lifecycle_context(
            metadata,
            _passive_order_lifecycle_context(
                lifecycle_source="fill_recorder.rejection",
                client_order_id=client_order_id,
                decision_uuid=decision_uuid,
                lifecycle_phase="rejected",
                submit_seen=True,
                symbol=symbol,
                side=side,
                reject_seen=True,
                terminal_state="rejected",
                terminal_reason=reason,
                venue_order_id=venue_order_id,
                broker_order_id=broker_order_id,
                exchange_txid=exchange_txid,
                original_qty=quantity,
                cumulative_filled_qty="0",
                remaining_qty=quantity,
                cumulative_fee="0",
                is_terminal=True,
                price_basis=limit_price,
                status_source="fill_recorder.rejection",
                id_mapping_source="fill_recorder.client_order_id",
            ),
        )
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
