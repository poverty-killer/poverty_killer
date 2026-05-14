"""
Narrow reservation lifecycle coordinator contract.

This module is not runtime-wired. It translates direct lifecycle facts into
ExposureManager guarded helper calls and leaves durable persistence ownership
with StateStore.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple


ZERO = Decimal("0")


class ReservationLifecycleCoordinator:
    """Coordinator-only seam for future active reservation lifecycle wiring."""

    state_store_authority = "durable_fact_owner"

    def __init__(self, *, exposure_manager: Any, state_store: Any, now_ns_provider: Optional[Any] = None):
        self.exposure_manager = exposure_manager
        self.state_store = state_store
        self._now_ns_provider = now_ns_provider

    def on_order_acknowledged(
        self,
        *,
        client_order_id: str,
        symbol: str,
        side: Any,
        sleeve: Any,
        qty: Any,
        price_basis: Any,
        order_type: Any,
        decision_uuid: Optional[str] = None,
        reservation_id: Optional[str] = None,
        reservation_dedupe_key: Optional[str] = None,
        source_lifecycle_phase: str = "order_acknowledged",
        source_idempotency_key: Optional[str] = None,
        price_basis_source_proven: bool = False,
        mutation_authority_source: str = "direct_lifecycle",
    ) -> Dict[str, Any]:
        result = self._result(action="order_acknowledged", client_order_id=client_order_id)
        if self._telemetry_authority_used(mutation_authority_source):
            return self._failed(result, "telemetry_not_mutation_authority")

        order_type_value = self._value(order_type).lower()
        if order_type_value != "limit" and not price_basis_source_proven:
            return self._failed(result, "price_basis_not_source_proven")

        try:
            self._positive_decimal(price_basis, "price_basis")
        except ValueError as exc:
            return self._failed(result, str(exc))

        dedupe_key = reservation_dedupe_key or self._dedupe_key(decision_uuid, client_order_id)
        resolved_reservation_id = reservation_id or client_order_id
        guard = self.exposure_manager.guarded_open_reservation(
            state_store=self.state_store,
            reservation_id=resolved_reservation_id,
            client_order_id=client_order_id,
            decision_uuid=decision_uuid,
            reservation_dedupe_key=dedupe_key,
            symbol=symbol,
            side=side,
            sleeve=sleeve,
            qty=qty,
            price_basis=price_basis,
            order_type=order_type_value,
            source_lifecycle_phase=source_lifecycle_phase,
            source_idempotency_key=source_idempotency_key or f"{dedupe_key}:{source_lifecycle_phase}",
        )
        return self._from_guard(result, guard)

    def on_partial_fill(
        self,
        *,
        client_order_id: str,
        cumulative_filled_qty: Any,
        fill_idempotency_key: Optional[str] = None,
        fill_delta_qty: Optional[Any] = None,
        status_source: str = "direct_fill_observation",
        source_event_id: Optional[str] = None,
        reservation_id: Optional[str] = None,
        reservation_dedupe_key: Optional[str] = None,
        mutation_authority_source: str = "direct_lifecycle",
    ) -> Dict[str, Any]:
        result = self._result(action="partial_fill", client_order_id=client_order_id)
        if self._telemetry_authority_used(mutation_authority_source):
            return self._failed(result, "telemetry_not_mutation_authority")

        row, failed_reason = self._resolve_active_reservation(
            reservation_id=reservation_id,
            client_order_id=client_order_id,
            reservation_dedupe_key=reservation_dedupe_key,
        )
        if row is None:
            return self._failed(result, failed_reason or "active_reservation_not_found")

        fill_key = fill_idempotency_key or self._fill_key(
            row["reservation_id"],
            status_source,
            cumulative_filled_qty,
            source_event_id,
        )
        guard = self.exposure_manager.guarded_apply_fill_to_reservation(
            state_store=self.state_store,
            reservation_id=row["reservation_id"],
            client_order_id=row["client_order_id"],
            fill_idempotency_key=fill_key,
            cumulative_filled_qty=cumulative_filled_qty,
            fill_delta_qty=fill_delta_qty,
            status_source=status_source,
            source_event_id=source_event_id,
        )
        return self._from_guard(result, guard)

    def on_full_fill(
        self,
        *,
        client_order_id: str,
        release_idempotency_key: str,
        cumulative_filled_qty: Optional[Any] = None,
        fill_idempotency_key: Optional[str] = None,
        fill_delta_qty: Optional[Any] = None,
        status_source: str = "direct_full_fill_observation",
        source_event_id: Optional[str] = None,
        reservation_id: Optional[str] = None,
        reservation_dedupe_key: Optional[str] = None,
        terminal_source: str = "direct_full_fill_observation",
        mutation_authority_source: str = "direct_lifecycle",
    ) -> Dict[str, Any]:
        result = self._result(action="full_fill", client_order_id=client_order_id)
        if self._telemetry_authority_used(mutation_authority_source):
            return self._failed(result, "telemetry_not_mutation_authority")

        existing_release = self.state_store.get_reservation_release_tombstone(
            release_idempotency_key=release_idempotency_key,
        )
        if existing_release is not None:
            if existing_release.get("client_order_id") == client_order_id:
                result["idempotent"] = True
                result["skipped"] = False
                result["failed_reason"] = "release_key_already_recorded"
                result["reservation_id"] = existing_release.get("reservation_id")
                return result
            return self._failed(result, "release_key_conflict")

        row, failed_reason = self._resolve_active_reservation(
            reservation_id=reservation_id,
            client_order_id=client_order_id,
            reservation_dedupe_key=reservation_dedupe_key,
        )
        if row is None:
            return self._failed(result, failed_reason or "active_reservation_not_found")

        if cumulative_filled_qty is not None and self._should_apply_pre_release_fill(row, cumulative_filled_qty):
            fill_result = self.on_partial_fill(
                client_order_id=client_order_id,
                cumulative_filled_qty=cumulative_filled_qty,
                fill_idempotency_key=fill_idempotency_key,
                fill_delta_qty=fill_delta_qty,
                status_source=status_source,
                source_event_id=source_event_id,
                reservation_id=row["reservation_id"],
                reservation_dedupe_key=row["reservation_dedupe_key"],
                mutation_authority_source=mutation_authority_source,
            )
            if not fill_result["applied"] and not fill_result["idempotent"]:
                return self._failed(result, f"pre_release_fill_failed:{fill_result['failed_reason']}")
            row = self.state_store.get_reservation_ledger(row["reservation_id"]) or row

        return self._release_from_row(
            result,
            row,
            release_idempotency_key=release_idempotency_key,
            release_reason="full_fill_observed",
            terminal_status="filled",
            terminal_source=terminal_source,
            source_event_id=source_event_id,
        )

    def on_terminal_mapping_proof(
        self,
        *,
        client_order_id: str,
        terminal_status: str,
        terminal_reason: str,
        terminal_source: str,
        release_idempotency_key: Optional[str] = None,
        reservation_id: Optional[str] = None,
        reservation_dedupe_key: Optional[str] = None,
        source_event_id: Optional[str] = None,
        mutation_authority_source: str = "direct_lifecycle",
    ) -> Dict[str, Any]:
        result = self._result(action="terminal_mapping_proof", client_order_id=client_order_id)
        if self._telemetry_authority_used(mutation_authority_source):
            return self._failed(result, "telemetry_not_mutation_authority")

        row, failed_reason = self._resolve_active_reservation(
            reservation_id=reservation_id,
            client_order_id=client_order_id,
            reservation_dedupe_key=reservation_dedupe_key,
        )
        if row is None:
            result["skipped"] = True
            result["failed_reason"] = failed_reason or "active_reservation_not_found"
            return result

        release_key = release_idempotency_key or (
            f"{row['reservation_id']}:terminal_mapping_proof:{terminal_status}:{source_event_id or client_order_id}"
        )
        return self._release_from_row(
            result,
            row,
            release_idempotency_key=release_key,
            release_reason=terminal_reason,
            terminal_status=terminal_status,
            terminal_source=terminal_source,
            source_event_id=source_event_id,
        )

    def on_cancel_requested(self, *, client_order_id: str, reason: str = "cancel_requested") -> Dict[str, Any]:
        return self._no_release(action="cancel_requested", client_order_id=client_order_id, reason=reason)

    def on_cancel_rejected(self, *, client_order_id: str, reason: str = "cancel_rejected") -> Dict[str, Any]:
        return self._no_release(action="cancel_rejected", client_order_id=client_order_id, reason=reason)

    def on_rejected_before_ack(self, *, client_order_id: str, reason: str = "rejected_before_ack") -> Dict[str, Any]:
        return self._no_release(action="rejected_before_ack", client_order_id=client_order_id, reason=reason)

    def on_orphan_or_drift(self, *, client_order_id: Optional[str] = None, reason: str = "orphan_or_drift") -> Dict[str, Any]:
        return self._no_release(action="orphan_or_drift", client_order_id=client_order_id, reason=reason)

    def on_status_failure(self, *, client_order_id: Optional[str] = None, reason: str = "status_failure") -> Dict[str, Any]:
        return self._no_release(action="status_failure", client_order_id=client_order_id, reason=reason)

    def on_open_order_absence(self, *, client_order_id: Optional[str] = None, reason: str = "open_order_absence") -> Dict[str, Any]:
        return self._no_release(action="open_order_absence", client_order_id=client_order_id, reason=reason)

    def _release_from_row(
        self,
        result: Dict[str, Any],
        row: Dict[str, Any],
        *,
        release_idempotency_key: str,
        release_reason: str,
        terminal_status: str,
        terminal_source: str,
        source_event_id: Optional[str],
    ) -> Dict[str, Any]:
        guard = self.exposure_manager.guarded_release_reservation(
            state_store=self.state_store,
            reservation_id=row["reservation_id"],
            client_order_id=row["client_order_id"],
            reservation_dedupe_key=row["reservation_dedupe_key"],
            release_idempotency_key=release_idempotency_key,
            release_reason=release_reason,
            terminal_status=terminal_status,
            terminal_source=terminal_source,
            released_qty=row.get("open_qty") or row.get("original_qty"),
            released_notional=row.get("notional_basis"),
            source_event_id=source_event_id,
        )
        return self._from_guard(result, guard)

    def _resolve_active_reservation(
        self,
        *,
        reservation_id: Optional[str],
        client_order_id: Optional[str],
        reservation_dedupe_key: Optional[str],
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        if reservation_id:
            row = self.state_store.get_reservation_ledger(reservation_id)
            if row is None:
                return None, "active_reservation_not_found"
            if not row.get("is_active") or row.get("is_terminal"):
                return None, "reservation_not_active"
            if client_order_id and row.get("client_order_id") != client_order_id:
                return None, "client_order_id_conflict"
            if reservation_dedupe_key and row.get("reservation_dedupe_key") != reservation_dedupe_key:
                return None, "reservation_dedupe_conflict"
            return row, None

        rows = self.state_store.list_reservation_ledger(active_only=True, include_terminal=False)
        matches: List[Dict[str, Any]] = []
        for row in rows:
            if reservation_dedupe_key and row.get("reservation_dedupe_key") == reservation_dedupe_key:
                matches.append(row)
            elif not reservation_dedupe_key and client_order_id and row.get("client_order_id") == client_order_id:
                matches.append(row)

        if not matches:
            return None, "active_reservation_not_found"
        unique = {row.get("reservation_id") for row in matches}
        if len(unique) != 1:
            return None, "active_reservation_conflict"
        return matches[0], None

    def _should_apply_pre_release_fill(self, row: Dict[str, Any], cumulative_filled_qty: Any) -> bool:
        try:
            cumulative = self._non_negative_decimal(cumulative_filled_qty, "cumulative_filled_qty")
            filled = self._non_negative_decimal(row.get("filled_qty") or "0", "filled_qty")
            original = self._positive_decimal(row.get("original_qty"), "original_qty")
        except ValueError:
            return False
        return filled < cumulative < original

    def _from_guard(self, result: Dict[str, Any], guard: Dict[str, Any]) -> Dict[str, Any]:
        result.update({
            "applied": bool(guard.get("applied")),
            "idempotent": bool(guard.get("idempotent")),
            "skipped": not bool(guard.get("applied")) and not bool(guard.get("idempotent")),
            "failed_reason": guard.get("failed_reason"),
            "reservation_id": guard.get("reservation_id"),
            "client_order_id": guard.get("client_order_id"),
            "mutation_attempted": bool(guard.get("mutation_applied")),
            "exposure_manager_called": True,
            "guard_result": dict(guard),
        })
        return result

    def _no_release(self, *, action: str, client_order_id: Optional[str], reason: str) -> Dict[str, Any]:
        result = self._result(action=action, client_order_id=client_order_id)
        result.update({
            "skipped": True,
            "failed_reason": reason,
            "mutation_attempted": False,
            "exposure_manager_called": False,
        })
        return result

    def _result(self, *, action: str, client_order_id: Optional[str]) -> Dict[str, Any]:
        return {
            "action": action,
            "applied": False,
            "idempotent": False,
            "skipped": False,
            "failed_reason": None,
            "reservation_id": None,
            "client_order_id": client_order_id,
            "mutation_attempted": False,
            "broker_command_performed": False,
            "telemetry_authority_used": False,
            "exposure_manager_called": False,
            "state_store_authority": self.state_store_authority,
        }

    @staticmethod
    def _failed(result: Dict[str, Any], reason: str) -> Dict[str, Any]:
        result["skipped"] = True
        result["failed_reason"] = reason
        return result

    @staticmethod
    def _telemetry_authority_used(source: str) -> bool:
        return str(source).strip().lower() in {"telemetry", "telemetry_event", "fill_recorder"}

    @staticmethod
    def _dedupe_key(decision_uuid: Optional[str], client_order_id: str) -> str:
        return f"{decision_uuid}:{client_order_id}" if decision_uuid else str(client_order_id)

    @staticmethod
    def _fill_key(reservation_id: str, status_source: str, cumulative_filled_qty: Any, source_event_id: Optional[str]) -> str:
        suffix = source_event_id if source_event_id is not None else str(cumulative_filled_qty)
        return f"{reservation_id}:{status_source}:cumulative:{cumulative_filled_qty}:{suffix}"

    @staticmethod
    def _value(value: Any) -> str:
        return str(value.value) if hasattr(value, "value") else str(value)

    @staticmethod
    def _positive_decimal(value: Any, field_name: str) -> Decimal:
        dec = ReservationLifecycleCoordinator._decimal(value, field_name)
        if dec <= ZERO:
            raise ValueError(f"{field_name} must be > 0, got {value}")
        return dec

    @staticmethod
    def _non_negative_decimal(value: Any, field_name: str) -> Decimal:
        dec = ReservationLifecycleCoordinator._decimal(value, field_name)
        if dec < ZERO:
            raise ValueError(f"{field_name} must be >= 0, got {value}")
        return dec

    @staticmethod
    def _decimal(value: Any, field_name: str) -> Decimal:
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ValueError(f"invalid decimal for {field_name}: {value!r}") from exc


__all__ = ["ReservationLifecycleCoordinator"]
