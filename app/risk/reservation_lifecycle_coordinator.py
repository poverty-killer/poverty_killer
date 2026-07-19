"""Reservation lifecycle and broker-inventory reconciliation coordinator.

This runtime-wired coordinator translates direct OMS lifecycle facts into
ExposureManager guarded helper calls. It also builds deterministic lot
projections from broker snapshots and immutable StateStore facts. StateStore
remains the durable fact owner; ExposureManager remains portfolio-risk owner.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from app.operator_activation.paper_baseline import normalize_baseline_symbol
from app.operator_credentials.store import normalize_alpaca_account_suffix


ZERO = Decimal("0")

ADOPTED_BASELINE = "ADOPTED_BASELINE"
BOT_ACQUIRED = "BOT_ACQUIRED"
PENDING_BUY = "PENDING_BUY"
PENDING_SELL = "PENDING_SELL"
SOLD = "SOLD"
UNKNOWN_ATTRIBUTION = "UNKNOWN_ATTRIBUTION"

_INVENTORY_EVENT_TYPES = {
    "FILL",
    "TRADE_CORRECT",
    "TRADE_BUST",
    "REJECTED",
    "EXPIRED",
    "CANCELED",
    "CANCELLED",
    "REPLACED",
}


class ReservationLifecycleCoordinator:
    """Coordinate durable lifecycle facts without taking Risk/broker authority."""

    state_store_authority = "durable_fact_owner"

    def __init__(
        self,
        *,
        exposure_manager: Any,
        state_store: Any,
        now_ns_provider: Optional[Any] = None,
        baseline_context: Optional[Dict[str, Any]] = None,
    ):
        self.exposure_manager = exposure_manager
        self.state_store = state_store
        self._now_ns_provider = now_ns_provider
        self._baseline_context: Dict[str, Any] = dict(baseline_context or {})

    def configure_baseline_context(self, baseline_context: Optional[Dict[str, Any]]) -> None:
        """Attach the already-governed opening baseline to this reconciliation lane."""
        self._baseline_context = dict(baseline_context or {})

    def record_broker_inventory_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Persist one broker lifecycle event with the active baseline lineage."""
        payload = dict(event or {})
        payload.setdefault("baseline_snapshot_id", self._baseline_context.get("baseline_snapshot_id"))
        event_type = str(payload.get("event_type") or "").strip().upper()
        result = {
            "event_id": payload.get("event_id"),
            "event_type": event_type,
            "status": "FAILED",
            "persisted": False,
            "idempotent": False,
            "conflict": False,
            "broker_command_performed": False,
            "broker_mutation_occurred": False,
        }
        if event_type not in _INVENTORY_EVENT_TYPES:
            result["reason_code"] = "UNSUPPORTED_INVENTORY_EVENT_TYPE"
            return result
        status = self.state_store.record_broker_inventory_event(payload)
        result.update(
            {
                "status": status.upper(),
                "persisted": status in {"inserted", "updated", "duplicate"},
                "idempotent": status == "duplicate",
                "conflict": status == "conflict",
                "reason_code": None if status in {"inserted", "updated", "duplicate"} else f"INVENTORY_EVENT_{status.upper()}",
            }
        )
        return result

    def record_broker_fill_event(self, fill: Dict[str, Any]) -> Dict[str, Any]:
        """Translate a canonical broker fill-ledger row into inventory semantics."""
        metadata = fill.get("metadata") if isinstance(fill.get("metadata"), dict) else {}
        inventory_fact = (
            metadata.get("broker_inventory_event")
            if isinstance(metadata.get("broker_inventory_event"), dict)
            else {}
        )
        source = str(fill.get("source") or "").strip().lower()
        quantity_semantics = str(
            inventory_fact.get("quantity_semantics")
            or ("DELTA" if source == "broker_activity" else "CUMULATIVE_ORDER")
        ).upper()
        sleeve = (
            metadata.get("sleeve")
            or metadata.get("strategy")
            or (metadata.get("order_metadata_capture") or {}).get("strategy")
        )
        return self.record_broker_inventory_event(
            {
                "event_id": fill.get("fill_id"),
                "event_type": "FILL",
                "broker_order_id": fill.get("broker_order_id"),
                "client_order_id": fill.get("client_order_id"),
                "fill_id": fill.get("fill_id"),
                "symbol": fill.get("symbol"),
                "side": fill.get("side"),
                "action": fill.get("action"),
                "quantity": inventory_fact.get("quantity", fill.get("quantity")),
                "price": inventory_fact.get("price", fill.get("price")),
                "fee": inventory_fact.get("fee", fill.get("fee")),
                "fee_currency": inventory_fact.get("fee_currency", fill.get("fee_currency")),
                "quantity_semantics": quantity_semantics,
                "sleeve": sleeve,
                "event_ts_ns": fill.get("fill_ts_ns"),
                "observed_at_ns": fill.get("observed_at_ns"),
                "source": fill.get("source") or "broker_fill_ledger",
                "metadata": {"hydration_status": fill.get("hydration_status")},
            }
        )

    def reconcile_broker_inventory(self, broker_snapshot: Dict[str, Any]) -> Dict[str, Any]:
        """Build and ingest one complete broker-canonical inventory projection.

        This method performs no broker call. The caller must supply a fresh
        GET-only snapshot from the existing OrderRouter/broker adapter boundary.
        """
        snapshot = dict(broker_snapshot or {})
        reasons: List[str] = []
        observed_at_ns = self._int_or_zero(snapshot.get("observed_at_ns"))
        reconciliation_now_ns = self._now_ns()
        broker = str(snapshot.get("broker") or "alpaca").strip().lower()
        environment = str(snapshot.get("environment") or "").strip().lower()
        endpoint_family = str(snapshot.get("endpoint_family") or "").strip().lower()
        fresh = snapshot.get("fresh") is True
        broker_read_occurred = snapshot.get("broker_read_occurred") is True
        read_methods_get_only = snapshot.get("read_methods_get_only") is True
        response_contract_valid = snapshot.get("response_contract_valid") is True
        mutation_occurred = snapshot.get("mutation_occurred") is True
        account = snapshot.get("account") if isinstance(snapshot.get("account"), dict) else {}
        pin = snapshot.get("account_pin_assertion") if isinstance(snapshot.get("account_pin_assertion"), dict) else {}
        positions_input = snapshot.get("positions") if isinstance(snapshot.get("positions"), list) else None
        open_orders = snapshot.get("open_orders") if isinstance(snapshot.get("open_orders"), list) else None

        if environment != "paper":
            reasons.append("BROKER_INVENTORY_PAPER_ENVIRONMENT_REQUIRED")
        if endpoint_family != "paper":
            reasons.append("BROKER_INVENTORY_PAPER_ENDPOINT_REQUIRED")
        if not fresh or observed_at_ns <= 0:
            reasons.append("BROKER_INVENTORY_FRESH_SNAPSHOT_REQUIRED")
        if observed_at_ns > reconciliation_now_ns:
            reasons.append("BROKER_INVENTORY_OBSERVATION_FROM_FUTURE")
        if not broker_read_occurred:
            reasons.append("BROKER_INVENTORY_BROKER_READ_REQUIRED")
        if not read_methods_get_only:
            reasons.append("BROKER_INVENTORY_GET_ONLY_READ_REQUIRED")
        if not response_contract_valid:
            reasons.append("BROKER_INVENTORY_RESPONSE_CONTRACT_INVALID")
        if mutation_occurred:
            reasons.append("BROKER_INVENTORY_READ_CONTAINED_MUTATION")
        if positions_input is None:
            reasons.append("BROKER_POSITIONS_SNAPSHOT_MISSING")
            positions_input = []
        if open_orders is None:
            reasons.append("BROKER_OPEN_ORDERS_SNAPSHOT_MISSING")
            open_orders = []
        if pin.get("account_pin_verified") is not True:
            reasons.append("BROKER_ACCOUNT_PIN_NOT_VERIFIED")

        actual_suffix = normalize_alpaca_account_suffix(
            account.get("id") or account.get("account_id") or pin.get("actual_suffix")
        )
        expected_suffix = normalize_alpaca_account_suffix(pin.get("expected_suffix"))
        asserted_actual_suffix = normalize_alpaca_account_suffix(pin.get("actual_suffix"))
        if not actual_suffix or not expected_suffix or actual_suffix != expected_suffix:
            reasons.append("BROKER_ACCOUNT_PIN_MISMATCH")
        if not asserted_actual_suffix or asserted_actual_suffix != actual_suffix:
            reasons.append("BROKER_ACCOUNT_PIN_ASSERTION_CONFLICT")
        account_status = str(account.get("status") or "").strip().upper()
        if account_status != "ACTIVE":
            reasons.append("BROKER_ACCOUNT_NOT_ACTIVE")
        for flag in ("trading_blocked", "account_blocked", "trade_suspended_by_user"):
            flag_value = account.get(flag)
            if flag_value is True:
                reasons.append(f"BROKER_ACCOUNT_{flag.upper()}")
            elif flag_value is not False:
                reasons.append(f"BROKER_ACCOUNT_{flag.upper()}_TRUTH_MISSING")

        baseline_id = str(self._baseline_context.get("baseline_snapshot_id") or "").strip() or None
        protected_positions = self._baseline_context.get("protected_positions")
        protected_positions = protected_positions if isinstance(protected_positions, dict) else {}
        baseline_loaded = self._baseline_context.get("baseline_loaded") is True
        if baseline_loaded and not baseline_id:
            reasons.append("BROKER_BASELINE_SNAPSHOT_ID_REQUIRED")
        baseline_account_suffix = normalize_alpaca_account_suffix(
            self._baseline_context.get("account_suffix")
        )
        if baseline_loaded and (
            not baseline_account_suffix
            or not actual_suffix
            or baseline_account_suffix != actual_suffix
        ):
            reasons.append("BROKER_BASELINE_ACCOUNT_MISMATCH")

        broker_positions = self._normalize_broker_positions(positions_input, reasons)
        if broker_positions and not baseline_loaded:
            reasons.append("BROKER_BASELINE_CONTEXT_REQUIRED_FOR_EXISTING_POSITIONS")

        try:
            events = (
                self.state_store.list_broker_inventory_events(
                    baseline_snapshot_id=baseline_id,
                    strict=True,
                )
                if baseline_id
                else []
            )
        except RuntimeError:
            events = []
            reasons.append("BROKER_INVENTORY_STATE_READ_FAILED")
        for event in events:
            event_id = str(event.get("event_id") or "missing")
            event_ts_ns = self._int_or_zero(event.get("event_ts_ns"))
            event_observed_at_ns = self._int_or_zero(event.get("observed_at_ns"))
            if event_ts_ns > observed_at_ns or event_observed_at_ns > observed_at_ns:
                reasons.append(f"INVENTORY_EVENT_AFTER_BROKER_SNAPSHOT:{event_id}")
        active_events = self._active_inventory_events(events, reasons)
        effective_fills = self._effective_fill_events(active_events, reasons)
        lots = self._opening_baseline_lots(
            protected_positions=protected_positions,
            broker_positions=broker_positions,
            baseline_snapshot_id=baseline_id,
            reasons=reasons,
        )
        sold_rows: List[Dict[str, Any]] = []
        self._apply_effective_fill_events(lots, sold_rows, effective_fills, baseline_id, reasons)

        try:
            reservation_rows = self.state_store.list_reservation_ledger(
                active_only=True,
                include_terminal=False,
                strict=True,
            )
        except RuntimeError:
            reservation_rows = []
            reasons.append("BROKER_INVENTORY_STATE_READ_FAILED")
        try:
            mappings = self.state_store.list_order_id_mappings(
                broker=broker,
                include_terminal=False,
                strict=True,
            )
        except RuntimeError:
            mappings = []
            reasons.append("BROKER_INVENTORY_STATE_READ_FAILED")
        pending_rows = self._pending_reservation_rows(
            reservation_rows=reservation_rows,
            mappings=mappings,
            broker_open_orders=open_orders,
            baseline_snapshot_id=baseline_id,
            reasons=reasons,
        )
        lots.extend(sold_rows)
        lots.extend(pending_rows)

        projected_positions = self._project_symbol_balances(
            broker_positions=broker_positions,
            lots=lots,
            reasons=reasons,
        )
        self._validate_cash_and_owned_reservations(
            account,
            projected_positions,
            reservation_rows,
            reasons,
        )
        cash_available = self._broker_available_cash(account)
        if cash_available is None:
            reasons.append("BROKER_CASH_TRUTH_MISSING_OR_INVALID")

        snapshot_id = str(snapshot.get("snapshot_id") or "").strip() or self._snapshot_id(
            broker=broker,
            account_suffix=actual_suffix,
            observed_at_ns=observed_at_ns,
            positions=projected_positions,
            open_orders=open_orders,
        )
        try:
            parent = self.state_store.get_latest_broker_inventory_reconciliation(
                account_suffix=actual_suffix,
                strict=True,
            )
        except RuntimeError:
            parent = None
            reasons.append("BROKER_INVENTORY_STATE_READ_FAILED")
        parent_snapshot_id = parent.get("snapshot_id") if isinstance(parent, dict) else None
        parent_observed_at_ns = (
            self._int_or_zero(parent.get("observed_at_ns"))
            if isinstance(parent, dict)
            else 0
        )
        if parent_observed_at_ns > observed_at_ns:
            reasons.append("BROKER_INVENTORY_OBSERVATION_REGRESSION")
        elif (
            parent_observed_at_ns == observed_at_ns
            and parent_snapshot_id
            and parent_snapshot_id != snapshot_id
        ):
            reasons.append("BROKER_INVENTORY_OBSERVATION_CONFLICT")
        if parent_snapshot_id == snapshot_id:
            parent_snapshot_id = parent.get("parent_snapshot_id")
        reasons = list(dict.fromkeys(reasons))
        status = "RECONCILED" if not reasons else "BLOCKED"
        for position in projected_positions:
            metadata = position.setdefault("metadata", {})
            metadata["reconciliation_snapshot_id"] = snapshot_id
        for lot in lots:
            metadata = lot.setdefault("metadata", {})
            metadata["reconciliation_snapshot_id"] = snapshot_id

        projection_metadata = {
            "account_status": account_status or "UNKNOWN",
            "fresh": fresh,
            "mutation_occurred": mutation_occurred,
            "baseline_loaded": baseline_loaded,
            "event_count": len(events),
            "effective_fill_count": len(effective_fills),
            "active_reservation_count": len(reservation_rows),
            "opening_baseline_preserved": True,
            "cash_available": None if cash_available is None else str(cash_available),
            "realized_pnl_basis": "GROSS_EX_FEES",
            "fee_truth_status": "NOT_ATTRIBUTED_STAGE_2",
            "fee_truth_complete": False,
            "net_realized_pnl_claimed": False,
        }
        persisted = self.state_store.persist_broker_inventory_reconciliation(
            {
                "snapshot_id": snapshot_id,
                "broker": broker,
                "environment": environment or "unknown",
                "endpoint_family": endpoint_family or "unknown",
                "account_suffix": actual_suffix or "unknown",
                "baseline_snapshot_id": baseline_id,
                "parent_snapshot_id": parent_snapshot_id,
                "observed_at_ns": observed_at_ns or self._now_ns(),
                "open_order_count": len(open_orders),
                "status": status,
                "reason_codes": tuple(reasons),
                "metadata": projection_metadata,
            },
            positions=projected_positions,
            lots=lots,
        )
        if persisted not in {"inserted", "duplicate"}:
            reasons.append(f"BROKER_INVENTORY_PERSIST_{persisted.upper()}")
            status = "BLOCKED"

        ingest_result: Dict[str, Any] = {
            "applied": False,
            "reason_code": "BROKER_INVENTORY_NOT_RECONCILED",
        }
        if status == "RECONCILED":
            try:
                durable = self.state_store.get_broker_inventory_reconciliation(
                    snapshot_id,
                    strict=True,
                )
            except RuntimeError:
                durable = None
                reasons.append("BROKER_INVENTORY_STATE_READ_FAILED")
            if durable is None:
                reasons.append("BROKER_INVENTORY_DURABLE_READBACK_FAILED")
                status = "BLOCKED"
            else:
                ingest_result = self.exposure_manager.ingest_reconciled_broker_inventory(durable)
                if ingest_result.get("applied") is not True:
                    reasons.append(str(ingest_result.get("reason_code") or "EXPOSURE_MANAGER_INVENTORY_INGEST_FAILED"))
                    status = "BLOCKED"

        if status != "RECONCILED" or ingest_result.get("applied") is not True:
            self.exposure_manager.mark_broker_inventory_unreconciled(*tuple(dict.fromkeys(reasons)))

        result = {
            "status": status,
            "authorized": status == "RECONCILED" and ingest_result.get("applied") is True,
            "reason_codes": tuple(dict.fromkeys(reasons)),
            "snapshot_id": snapshot_id,
            "parent_snapshot_id": parent_snapshot_id,
            "baseline_snapshot_id": baseline_id,
            "account_suffix": actual_suffix,
            "position_count": len(projected_positions),
            "position_symbols": tuple(row["symbol"] for row in projected_positions),
            "open_order_count": len(open_orders),
            "event_count": len(events),
            "effective_fill_count": len(effective_fills),
            "lot_count": len(lots),
            "persist_status": persisted,
            "exposure_ingest": ingest_result,
            "positions": tuple(projected_positions),
            "lots": tuple(lots),
            "broker_read_occurred": bool(snapshot.get("broker_read_occurred")),
            "broker_command_performed": False,
            "broker_mutation_occurred": False,
            "opening_baseline_preserved": True,
            "metadata": projection_metadata,
        }
        return result

    def _normalize_broker_positions(self, rows: List[Dict[str, Any]], reasons: List[str]) -> Dict[str, Dict[str, Any]]:
        positions: Dict[str, Dict[str, Any]] = {}
        for raw in rows:
            if not isinstance(raw, dict):
                reasons.append("BROKER_POSITION_ROW_INVALID")
                continue
            symbol = normalize_baseline_symbol(raw.get("symbol"))
            if not symbol or symbol in positions:
                reasons.append("BROKER_POSITION_SYMBOL_DUPLICATE_OR_MISSING")
                continue
            qty = self._decimal_or_none(raw.get("qty", raw.get("quantity")))
            if qty is None or qty < ZERO:
                reasons.append(f"BROKER_POSITION_QUANTITY_INVALID:{symbol}")
                continue
            avg_entry = self._positive_decimal_or_none(raw.get("avg_entry_price", raw.get("average_entry_price")))
            mark = self._positive_decimal_or_none(raw.get("current_price", raw.get("market_price"))) or avg_entry
            side = str(raw.get("side") or "").strip().lower()
            if side != "long":
                reasons.append(f"BROKER_POSITION_LONG_SIDE_REQUIRED:{symbol}")
            if qty > ZERO and (avg_entry is None or mark is None):
                reasons.append(f"BROKER_POSITION_PRICE_MISSING:{symbol}")
            step = self._positive_decimal_or_none(raw.get("quantity_step", raw.get("min_trade_increment")))
            if step is not None and qty % step != ZERO:
                reasons.append(f"BROKER_POSITION_QUANTITY_STEP_MISMATCH:{symbol}")
            positions[symbol] = {
                "symbol": symbol,
                "broker_qty": qty,
                "avg_entry_price": avg_entry,
                "mark_price": mark,
                "quantity_step": step,
            }
        return positions

    def _active_inventory_events(self, events: List[Dict[str, Any]], reasons: List[str]) -> List[Dict[str, Any]]:
        by_id = {str(row.get("event_id")): row for row in events if str(row.get("event_id") or "").strip()}
        superseded: set[str] = set()
        replacements_by_target: Dict[str, List[str]] = {}
        for row in events:
            event_type = str(row.get("event_type") or "").upper()
            if event_type not in {"TRADE_CORRECT", "TRADE_BUST"}:
                continue
            event_id = str(row.get("event_id") or "").strip()
            target = str(row.get("replaces_event_id") or "").strip()
            if not target or target not in by_id:
                reasons.append(f"INVENTORY_EVENT_REPLACEMENT_TARGET_MISSING:{row.get('event_id')}")
                continue
            if target == event_id:
                reasons.append(f"INVENTORY_EVENT_SELF_REPLACEMENT:{target}")
                continue
            target_type = str(by_id[target].get("event_type") or "").upper()
            if target_type not in {"FILL", "TRADE_CORRECT"}:
                reasons.append(f"INVENTORY_EVENT_REPLACEMENT_TARGET_INVALID:{event_id}")
                continue
            target_row = by_id[target]
            identity_pairs = (
                (
                    "broker_order_id",
                    str(target_row.get("broker_order_id") or "").strip(),
                    str(row.get("broker_order_id") or "").strip(),
                ),
                (
                    "client_order_id",
                    str(target_row.get("client_order_id") or "").strip(),
                    str(row.get("client_order_id") or "").strip(),
                ),
                (
                    "symbol",
                    normalize_baseline_symbol(target_row.get("symbol")),
                    normalize_baseline_symbol(row.get("symbol")),
                ),
                (
                    "side",
                    str(target_row.get("side") or "").strip().lower(),
                    str(row.get("side") or "").strip().lower(),
                ),
            )
            identity_conflicts = tuple(
                field
                for field, target_value, replacement_value in identity_pairs
                if (
                    replacement_value != target_value
                    if event_type == "TRADE_CORRECT"
                    else bool(replacement_value) and replacement_value != target_value
                )
            )
            if identity_conflicts:
                reasons.append(
                    f"INVENTORY_EVENT_REPLACEMENT_IDENTITY_CONFLICT:{event_id}:"
                    f"{','.join(identity_conflicts)}"
                )
                continue
            replacements_by_target.setdefault(target, []).append(event_id)
            superseded.add(target)
        for target, replacements in replacements_by_target.items():
            if len(replacements) > 1:
                reasons.append(f"INVENTORY_EVENT_REPLACEMENT_AMBIGUOUS:{target}")
        for event_id in by_id:
            seen: set[str] = set()
            current = event_id
            while current in by_id:
                if current in seen:
                    reasons.append(f"INVENTORY_EVENT_REPLACEMENT_CYCLE:{event_id}")
                    break
                seen.add(current)
                current = str(by_id[current].get("replaces_event_id") or "").strip()
                if not current:
                    break
        return [row for row in events if str(row.get("event_id")) not in superseded]

    def _effective_fill_events(self, events: List[Dict[str, Any]], reasons: List[str]) -> List[Dict[str, Any]]:
        fill_events = [row for row in events if str(row.get("event_type") or "").upper() in {"FILL", "TRADE_CORRECT"}]
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for row in fill_events:
            key = str(row.get("client_order_id") or row.get("broker_order_id") or row.get("event_id"))
            grouped.setdefault(key, []).append(row)
        effective: List[Dict[str, Any]] = []
        for order_key, order_events in grouped.items():
            identities = {
                (
                    normalize_baseline_symbol(row.get("symbol")),
                    str(row.get("side") or "").strip().lower(),
                    str(row.get("broker_order_id") or "").strip(),
                )
                for row in order_events
            }
            if len(identities) != 1:
                reasons.append(f"INVENTORY_FILL_ORDER_IDENTITY_CONFLICT:{order_key}")
            delta_events = [row for row in order_events if str(row.get("quantity_semantics") or "").upper() == "DELTA"]
            cumulative_events = [row for row in order_events if str(row.get("quantity_semantics") or "").upper() == "CUMULATIVE_ORDER"]
            unsupported = [row for row in order_events if row not in delta_events and row not in cumulative_events]
            if unsupported:
                reasons.append(f"INVENTORY_FILL_QUANTITY_SEMANTICS_INVALID:{order_key}")
            cumulative_max = ZERO
            cumulative_choice: Optional[Dict[str, Any]] = None
            if cumulative_events:
                causal_rows = sorted(cumulative_events, key=self._event_sort_key)
                causal_high_water = ZERO
                prices_by_quantity: Dict[Decimal, Decimal] = {}
                for row in causal_rows:
                    quantity = self._decimal_or_none(row.get("quantity"))
                    if quantity is None or quantity <= ZERO:
                        reasons.append(f"INVENTORY_FILL_CUMULATIVE_QUANTITY_INVALID:{order_key}")
                        continue
                    price = self._positive_decimal_or_none(row.get("price"))
                    if price is None:
                        reasons.append(f"INVENTORY_FILL_CUMULATIVE_PRICE_INVALID:{order_key}")
                    elif quantity in prices_by_quantity and prices_by_quantity[quantity] != price:
                        reasons.append(f"INVENTORY_FILL_CUMULATIVE_PRICE_CONFLICT:{order_key}")
                    else:
                        prices_by_quantity[quantity] = price
                    if quantity < causal_high_water:
                        reasons.append(f"INVENTORY_FILL_CUMULATIVE_REGRESSION:{order_key}")
                    causal_high_water = max(causal_high_water, quantity)
                    if quantity > cumulative_max or (
                        quantity == cumulative_max
                        and (
                            cumulative_choice is None
                            or self._event_sort_key(row) > self._event_sort_key(cumulative_choice)
                        )
                    ):
                        cumulative_max = quantity
                        cumulative_choice = row
            if delta_events:
                delta_total = sum(
                    (self._decimal_or_none(row.get("quantity")) or ZERO)
                    for row in delta_events
                )
                if cumulative_events:
                    if delta_total != cumulative_max:
                        reasons.append(f"INVENTORY_FILL_DELTA_CUMULATIVE_MISMATCH:{order_key}")
                effective.extend(delta_events)
            elif cumulative_choice is not None:
                effective.append(cumulative_choice)
        return sorted(effective, key=self._event_sort_key)

    def _opening_baseline_lots(
        self,
        *,
        protected_positions: Dict[str, Any],
        broker_positions: Dict[str, Dict[str, Any]],
        baseline_snapshot_id: Optional[str],
        reasons: List[str],
    ) -> List[Dict[str, Any]]:
        lots: List[Dict[str, Any]] = []
        for raw_symbol, raw in sorted(protected_positions.items()):
            row = raw if isinstance(raw, dict) else {}
            symbol = normalize_baseline_symbol(row.get("symbol") or raw_symbol)
            qty = self._decimal_or_none(row.get("qty", row.get("quantity")))
            side = str(row.get("side") or "").strip().lower()
            if not symbol or qty is None or qty < ZERO or side != "long":
                reasons.append(f"BASELINE_POSITION_INVALID:{raw_symbol}")
                continue
            broker_position = broker_positions.get(symbol, {})
            price = (
                self._positive_decimal_or_none(row.get("avg_entry_price", row.get("average_entry_price")))
                or broker_position.get("avg_entry_price")
            )
            if qty > ZERO and price is None:
                reasons.append(f"BASELINE_POSITION_PRICE_MISSING:{symbol}")
            lots.append(
                {
                    "lot_id": f"baseline:{baseline_snapshot_id or 'missing'}:{symbol}",
                    "symbol": symbol,
                    "sleeve": "POVERTY_KILLER_AGGREGATE",
                    "provenance": ADOPTED_BASELINE,
                    "original_qty": str(qty),
                    "remaining_qty": str(qty),
                    "sold_qty": "0",
                    "avg_entry_price": None if price is None else str(price),
                    "source_event_id": None,
                    "baseline_snapshot_id": baseline_snapshot_id,
                    "acquired_at_ns": 0,
                    "metadata": {"opening_snapshot_immutable": True},
                }
            )
        return lots

    def _apply_effective_fill_events(
        self,
        lots: List[Dict[str, Any]],
        sold_rows: List[Dict[str, Any]],
        events: List[Dict[str, Any]],
        baseline_snapshot_id: Optional[str],
        reasons: List[str],
    ) -> None:
        for event in events:
            event_id = str(event.get("event_id") or "")
            symbol = normalize_baseline_symbol(event.get("symbol"))
            side = str(event.get("side") or "").strip().lower()
            qty = self._positive_decimal_or_none(event.get("quantity"))
            price = self._positive_decimal_or_none(event.get("price"))
            if not event_id or not symbol or side not in {"buy", "sell"} or qty is None or price is None:
                reasons.append(f"INVENTORY_FILL_EVENT_INVALID:{event_id or 'missing'}")
                continue
            if side == "buy":
                lots.append(
                    {
                        "lot_id": f"bot:{event_id}",
                        "symbol": symbol,
                        "sleeve": str(event.get("sleeve") or "POVERTY_KILLER_AGGREGATE"),
                        "provenance": BOT_ACQUIRED,
                        "original_qty": str(qty),
                        "remaining_qty": str(qty),
                        "sold_qty": "0",
                        "avg_entry_price": str(price),
                        "source_event_id": event_id,
                        "baseline_snapshot_id": baseline_snapshot_id,
                        "acquired_at_ns": self._int_or_zero(event.get("event_ts_ns")) or self._int_or_zero(event.get("observed_at_ns")),
                        "metadata": {"quantity_semantics": event.get("quantity_semantics")},
                    }
                )
                continue

            remaining = qty
            allocations: List[Dict[str, str]] = []
            candidates = sorted(
                (
                    lot
                    for lot in lots
                    if lot.get("symbol") == symbol
                    and lot.get("provenance") == BOT_ACQUIRED
                    and self._decimal_or_none(lot.get("remaining_qty")) not in {None, ZERO}
                ),
                key=lambda row: (self._int_or_zero(row.get("acquired_at_ns")), str(row.get("lot_id"))),
            )
            realized_pnl = ZERO
            for lot in candidates:
                available = self._decimal_or_none(lot.get("remaining_qty")) or ZERO
                allocation = min(available, remaining)
                if allocation <= ZERO:
                    continue
                entry_price = self._positive_decimal_or_none(lot.get("avg_entry_price"))
                if entry_price is None:
                    reasons.append(f"INVENTORY_SELL_ENTRY_PRICE_MISSING:{lot.get('lot_id')}")
                    continue
                lot["remaining_qty"] = str(available - allocation)
                lot["sold_qty"] = str((self._decimal_or_none(lot.get("sold_qty")) or ZERO) + allocation)
                allocation_realized_pnl = (price - entry_price) * allocation
                realized_pnl += allocation_realized_pnl
                allocations.append(
                    {
                        "lot_id": str(lot.get("lot_id")),
                        "quantity": str(allocation),
                        "sleeve": str(lot.get("sleeve") or ""),
                        "entry_price": str(entry_price),
                        "exit_price": str(price),
                        "realized_pnl_ex_fees": str(allocation_realized_pnl),
                    }
                )
                remaining -= allocation
                if remaining == ZERO:
                    break
            allocated = qty - remaining
            sold_rows.append(
                {
                    "lot_id": f"sold:{event_id}",
                    "symbol": symbol,
                    "sleeve": str(event.get("sleeve") or "POVERTY_KILLER_AGGREGATE"),
                    "provenance": SOLD,
                    "original_qty": str(allocated),
                    "remaining_qty": "0",
                    "sold_qty": str(allocated),
                    "avg_entry_price": str(price),
                    "source_event_id": event_id,
                    "baseline_snapshot_id": baseline_snapshot_id,
                    "acquired_at_ns": self._int_or_zero(event.get("event_ts_ns")) or self._int_or_zero(event.get("observed_at_ns")),
                    "metadata": {
                        "allocations": allocations,
                        "unallocated_sell_qty": str(remaining),
                        "realized_pnl_ex_fees": str(realized_pnl),
                    },
                }
            )
            if remaining > ZERO:
                reasons.append(f"SELL_FILL_EXCEEDS_BOT_ACQUIRED_QUANTITY:{symbol}")

    def _pending_reservation_rows(
        self,
        *,
        reservation_rows: List[Dict[str, Any]],
        mappings: List[Dict[str, Any]],
        broker_open_orders: List[Dict[str, Any]],
        baseline_snapshot_id: Optional[str],
        reasons: List[str],
    ) -> List[Dict[str, Any]]:
        reservations: Dict[str, Dict[str, Any]] = {}
        for row in reservation_rows:
            client_id = str(row.get("client_order_id") or "").strip()
            if not client_id:
                reasons.append("RESERVATION_CLIENT_ID_MISSING")
                continue
            if client_id in reservations:
                reasons.append(f"RESERVATION_CLIENT_ID_DUPLICATE:{client_id}")
                continue
            reservations[client_id] = row

        mapping_by_client: Dict[str, Dict[str, Any]] = {}
        for row in mappings:
            client_id = str(row.get("client_order_id") or "").strip()
            if not client_id:
                reasons.append("ORDER_MAPPING_CLIENT_ID_MISSING")
                continue
            if client_id in mapping_by_client:
                reasons.append(f"ORDER_MAPPING_CLIENT_ID_DUPLICATE:{client_id}")
                continue
            mapping_by_client[client_id] = row

        broker_by_client: Dict[str, Dict[str, Any]] = {}
        for row in broker_open_orders:
            if not isinstance(row, dict):
                reasons.append("BROKER_OPEN_ORDER_ROW_INVALID")
                continue
            client_id = str(row.get("client_order_id") or row.get("client_id") or "").strip()
            if not client_id:
                reasons.append("BROKER_OPEN_ORDER_CLIENT_ID_MISSING")
                continue
            if client_id in broker_by_client:
                reasons.append(f"BROKER_OPEN_ORDER_CLIENT_ID_DUPLICATE:{client_id}")
                continue
            broker_by_client[client_id] = row
            if client_id not in reservations or client_id not in mapping_by_client:
                reasons.append(f"BROKER_OPEN_ORDER_ATTRIBUTION_UNKNOWN:{client_id}")

        for client_id in mapping_by_client:
            if client_id not in reservations:
                reasons.append(f"ORDER_MAPPING_ACTIVE_RESERVATION_MISSING:{client_id}")
            if client_id not in broker_by_client:
                reasons.append(f"ORDER_MAPPING_BROKER_OPEN_ORDER_MISSING:{client_id}")

        pending: List[Dict[str, Any]] = []
        for client_id, row in reservations.items():
            broker_order = broker_by_client.get(client_id)
            if broker_order is None:
                reasons.append(f"RESERVATION_BROKER_OPEN_ORDER_MISSING:{client_id}")
                continue
            mapping = mapping_by_client.get(client_id)
            if mapping is None:
                reasons.append(f"RESERVATION_ORDER_MAPPING_MISSING:{client_id}")
                continue
            broker_order_id = str(broker_order.get("id") or broker_order.get("order_id") or "").strip()
            mapped_order_id = str(
                mapping.get("broker_order_id")
                or mapping.get("venue_order_id")
                or mapping.get("command_order_id")
                or ""
            ).strip()
            if not broker_order_id or not mapped_order_id:
                reasons.append(f"RESERVATION_BROKER_ORDER_ID_MISSING:{client_id}")
                continue
            if broker_order_id != mapped_order_id:
                reasons.append(f"RESERVATION_BROKER_ORDER_ID_CONFLICT:{client_id}")
                continue
            symbol = normalize_baseline_symbol(row.get("symbol"))
            broker_symbol = normalize_baseline_symbol(broker_order.get("symbol"))
            mapped_symbol = normalize_baseline_symbol(mapping.get("symbol"))
            side = str(row.get("side") or "").strip().lower()
            broker_side = str(broker_order.get("side") or "").strip().lower()
            mapped_side = str(mapping.get("side") or "").strip().lower()
            qty = self._positive_decimal_or_none(row.get("open_qty"))
            price = self._positive_decimal_or_none(row.get("price_basis"))
            if not symbol or symbol != broker_symbol or side != broker_side or side not in {"buy", "sell"}:
                reasons.append(f"RESERVATION_BROKER_ORDER_CONFLICT:{client_id}")
                continue
            if mapped_symbol != symbol or mapped_side != side:
                reasons.append(f"RESERVATION_ORDER_MAPPING_CONFLICT:{client_id}")
                continue
            if qty is None or price is None:
                reasons.append(f"RESERVATION_QUANTITY_OR_PRICE_INVALID:{client_id}")
                continue
            original_qty = self._positive_decimal_or_none(row.get("original_qty"))
            filled_qty = self._non_negative_decimal_or_none(row.get("filled_qty"))
            cancelled_qty = self._non_negative_decimal_or_none(row.get("cancelled_qty"))
            if (
                original_qty is None
                or filled_qty is None
                or cancelled_qty is None
                or qty + filled_qty + cancelled_qty != original_qty
            ):
                reasons.append(f"RESERVATION_QUANTITY_IDENTITY_CONFLICT:{client_id}")
                continue
            broker_original = self._positive_decimal_or_none(
                broker_order.get("qty", broker_order.get("quantity"))
            )
            broker_filled_raw = broker_order.get("filled_qty")
            if broker_filled_raw is None:
                broker_filled_raw = broker_order.get("filled_quantity")
            broker_filled = self._non_negative_decimal_or_none(broker_filled_raw)
            broker_remaining_explicit = self._non_negative_decimal_or_none(
                broker_order.get("remaining_qty")
            )
            if (
                broker_original is None
                or broker_filled is None
                or broker_filled > broker_original
            ):
                reasons.append(f"RESERVATION_BROKER_QUANTITY_TRUTH_MISSING_OR_INVALID:{client_id}")
                continue
            broker_remaining = broker_original - broker_filled
            if (
                broker_original != original_qty
                or broker_filled != filled_qty
                or broker_remaining != qty
                or (
                    broker_remaining_explicit is not None
                    and broker_remaining_explicit != broker_remaining
                )
            ):
                reasons.append(f"RESERVATION_BROKER_REMAINING_QUANTITY_CONFLICT:{client_id}")
                continue
            broker_price = self._positive_decimal_or_none(
                broker_order.get("limit_price", broker_order.get("price"))
            )
            if broker_price is None:
                reasons.append(f"RESERVATION_BROKER_PRICE_TRUTH_MISSING:{client_id}")
                continue
            if broker_price != price:
                reasons.append(f"RESERVATION_BROKER_PRICE_CONFLICT:{client_id}")
                continue
            pending.append(
                {
                    "lot_id": f"pending:{client_id}",
                    "symbol": symbol,
                    "sleeve": str(row.get("sleeve") or "POVERTY_KILLER_AGGREGATE"),
                    "provenance": PENDING_BUY if side == "buy" else PENDING_SELL,
                    "original_qty": str(qty),
                    "remaining_qty": str(qty),
                    "sold_qty": "0",
                    "avg_entry_price": str(price),
                    "source_event_id": None,
                    "baseline_snapshot_id": baseline_snapshot_id,
                    "acquired_at_ns": self._int_or_zero(row.get("created_at_ns")),
                    "metadata": {"client_order_id": client_id, "reservation_id": row.get("reservation_id")},
                }
            )
        return pending

    def _project_symbol_balances(
        self,
        *,
        broker_positions: Dict[str, Dict[str, Any]],
        lots: List[Dict[str, Any]],
        reasons: List[str],
    ) -> List[Dict[str, Any]]:
        symbols = set(broker_positions)
        symbols.update(str(lot.get("symbol")) for lot in lots if lot.get("symbol"))
        positions: List[Dict[str, Any]] = []
        for symbol in sorted(symbols):
            symbol_lots = [lot for lot in lots if lot.get("symbol") == symbol]
            baseline_qty = sum(
                (self._decimal_or_none(row.get("remaining_qty")) or ZERO)
                for row in symbol_lots
                if row.get("provenance") == ADOPTED_BASELINE
            )
            bot_acquired_qty = sum(
                (self._decimal_or_none(row.get("original_qty")) or ZERO)
                for row in symbol_lots
                if row.get("provenance") == BOT_ACQUIRED
            )
            bot_owned_qty = sum(
                (self._decimal_or_none(row.get("remaining_qty")) or ZERO)
                for row in symbol_lots
                if row.get("provenance") == BOT_ACQUIRED
            )
            sold_qty = sum(
                (self._decimal_or_none(row.get("sold_qty")) or ZERO)
                for row in symbol_lots
                if row.get("provenance") == SOLD
            )
            pending_buy = sum(
                (self._decimal_or_none(row.get("remaining_qty")) or ZERO)
                for row in symbol_lots
                if row.get("provenance") == PENDING_BUY
            )
            pending_sell = sum(
                (self._decimal_or_none(row.get("remaining_qty")) or ZERO)
                for row in symbol_lots
                if row.get("provenance") == PENDING_SELL
            )
            broker_row = broker_positions.get(symbol, {})
            broker_qty = broker_row.get("broker_qty") or ZERO
            if bot_acquired_qty - sold_qty != bot_owned_qty:
                reasons.append(f"BOT_INVENTORY_LOT_IDENTITY_MISMATCH:{symbol}")
            known_qty = baseline_qty + bot_owned_qty
            unknown_delta = broker_qty - known_qty
            if unknown_delta != ZERO:
                reasons.append(f"UNKNOWN_INVENTORY_ATTRIBUTION:{symbol}")
                symbol_lots.append(
                    {
                        "lot_id": f"unknown:{symbol}",
                        "symbol": symbol,
                        "sleeve": "POVERTY_KILLER_AGGREGATE",
                        "provenance": UNKNOWN_ATTRIBUTION,
                        "original_qty": str(abs(unknown_delta)),
                        "remaining_qty": str(abs(unknown_delta)),
                        "sold_qty": "0",
                        "avg_entry_price": None,
                        "source_event_id": None,
                        "baseline_snapshot_id": self._baseline_context.get("baseline_snapshot_id"),
                        "acquired_at_ns": 0,
                        "metadata": {"signed_delta_qty": str(unknown_delta)},
                    }
                )
                lots.append(symbol_lots[-1])
            available_qty = broker_qty - pending_sell
            if available_qty < ZERO:
                reasons.append(f"PENDING_SELL_EXCEEDS_BROKER_QUANTITY:{symbol}")
            positions.append(
                {
                    "symbol": symbol,
                    "broker_qty": str(broker_qty),
                    "avg_entry_price": None if broker_row.get("avg_entry_price") is None else str(broker_row.get("avg_entry_price")),
                    "mark_price": None if broker_row.get("mark_price") is None else str(broker_row.get("mark_price")),
                    "quantity_step": None if broker_row.get("quantity_step") is None else str(broker_row.get("quantity_step")),
                    "metadata": {
                        "baseline_qty": str(baseline_qty),
                        "bot_acquired_qty": str(bot_acquired_qty),
                        "bot_owned_qty": str(bot_owned_qty),
                        "sold_qty": str(sold_qty),
                        "unknown_attribution_qty": str(unknown_delta),
                        "pending_buy_qty": str(pending_buy),
                        "pending_sell_qty": str(pending_sell),
                        "available_qty": str(max(ZERO, available_qty)),
                        "attribution_status": "KNOWN" if unknown_delta == ZERO else UNKNOWN_ATTRIBUTION,
                    },
                }
            )
        return positions

    def _validate_cash_and_owned_reservations(
        self,
        account: Dict[str, Any],
        positions: List[Dict[str, Any]],
        reservation_rows: List[Dict[str, Any]],
        reasons: List[str],
    ) -> None:
        cash_value = self._broker_available_cash(account)
        pending_buy_notional = ZERO
        # Pending rows are persisted with the projection; calculate from the
        # active reservation ledger so price and quantity retain exact Decimal.
        for row in reservation_rows:
            if str(row.get("side") or "").strip().lower() != "buy":
                continue
            qty = self._positive_decimal_or_none(row.get("open_qty"))
            price = self._positive_decimal_or_none(row.get("price_basis"))
            if qty is not None and price is not None:
                pending_buy_notional += qty * price
        if pending_buy_notional > ZERO and cash_value is None:
            reasons.append("BROKER_CASH_TRUTH_MISSING_FOR_PENDING_BUY")
        elif cash_value is not None and pending_buy_notional > cash_value:
            reasons.append("PENDING_BUY_RESERVATIONS_EXCEED_BROKER_CASH")
        for position in positions:
            metadata = position.get("metadata") if isinstance(position.get("metadata"), dict) else {}
            pending_sell = self._decimal_or_none(metadata.get("pending_sell_qty")) or ZERO
            broker_qty = self._decimal_or_none(position.get("broker_qty")) or ZERO
            if pending_sell > broker_qty:
                reasons.append(f"PENDING_SELL_EXCEEDS_BROKER_QUANTITY:{position.get('symbol')}")

    def _broker_available_cash(self, account: Dict[str, Any]) -> Optional[Decimal]:
        cash_value = self._non_negative_decimal_or_none(account.get("cash"))
        if cash_value is None:
            cash_value = self._non_negative_decimal_or_none(account.get("non_marginable_buying_power"))
        if cash_value is None:
            cash_value = self._non_negative_decimal_or_none(account.get("buying_power"))
        return cash_value

    def _snapshot_id(
        self,
        *,
        broker: str,
        account_suffix: Optional[str],
        observed_at_ns: int,
        positions: List[Dict[str, Any]],
        open_orders: List[Dict[str, Any]],
    ) -> str:
        payload = {
            "broker": broker,
            "account_suffix": account_suffix,
            "observed_at_ns": observed_at_ns,
            "positions": positions,
            "open_orders": open_orders,
            "baseline_snapshot_id": self._baseline_context.get("baseline_snapshot_id"),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        return f"broker-inventory-{hashlib.sha256(encoded).hexdigest()[:16]}"

    def _now_ns(self) -> int:
        if callable(self._now_ns_provider):
            return int(self._now_ns_provider())
        import time

        return time.time_ns()

    @staticmethod
    def _event_sort_key(row: Dict[str, Any]) -> Tuple[int, int, str]:
        return (
            ReservationLifecycleCoordinator._int_or_zero(row.get("event_ts_ns")),
            ReservationLifecycleCoordinator._int_or_zero(row.get("observed_at_ns")),
            str(row.get("event_id") or ""),
        )

    @staticmethod
    def _int_or_zero(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError, OverflowError):
            return 0

    @staticmethod
    def _decimal_or_none(value: Any) -> Optional[Decimal]:
        if value is None or str(value).strip() == "":
            return None
        try:
            result = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return None
        return result if result.is_finite() else None

    @classmethod
    def _positive_decimal_or_none(cls, value: Any) -> Optional[Decimal]:
        result = cls._decimal_or_none(value)
        return result if result is not None and result > ZERO else None

    @classmethod
    def _non_negative_decimal_or_none(cls, value: Any) -> Optional[Decimal]:
        result = cls._decimal_or_none(value)
        return result if result is not None and result >= ZERO else None

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

    def on_terminal_non_fill(
        self,
        *,
        client_order_id: str,
        release_idempotency_key: str,
        terminal_status: str,
        terminal_source: str,
        terminal_reason: str,
        decision_uuid: Optional[str] = None,
        reservation_id: Optional[str] = None,
        reservation_dedupe_key: Optional[str] = None,
        source_event_id: Optional[str] = None,
        released_qty: Optional[Any] = None,
        released_notional: Optional[Any] = None,
        mutation_authority_source: str = "direct_lifecycle",
    ) -> Dict[str, Any]:
        result = self._result(action="terminal_non_fill", client_order_id=client_order_id)
        if self._telemetry_authority_used(mutation_authority_source):
            return self._failed(result, "telemetry_not_mutation_authority")

        normalized_status = str(terminal_status or "").strip().lower()
        if normalized_status == "canceled":
            normalized_status = "cancelled"
        allowed_statuses = {"cancelled", "expired", "rejected"}
        if normalized_status not in allowed_statuses:
            return self._failed(result, "unsupported_terminal_non_fill_status")

        source = str(terminal_source or "").strip().lower()
        reason = str(terminal_reason or "").strip().lower()
        forbidden = {
            "cancel_requested",
            "cancel_rejected",
            "rejected_before_ack",
            "submit_failure",
            "terminal_mapping_proof",
            "orphan_or_drift",
            "status_failure",
            "open_order_absence",
        }
        if source in forbidden or reason in forbidden or source == "mark_terminal_from_status_evidence":
            return self._failed(result, "forbidden_terminal_non_fill_event")

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

        dedupe_key = reservation_dedupe_key or self._dedupe_key(decision_uuid, client_order_id)
        row, failed_reason = self._resolve_active_reservation(
            reservation_id=reservation_id,
            client_order_id=client_order_id,
            reservation_dedupe_key=dedupe_key,
        )
        if row is None:
            return self._failed(result, failed_reason or "active_reservation_not_found")

        return self._release_from_row(
            result,
            row,
            release_idempotency_key=release_idempotency_key,
            release_reason=terminal_reason,
            terminal_status=normalized_status,
            terminal_source=terminal_source,
            source_event_id=source_event_id,
            released_qty=released_qty,
            released_notional=released_notional,
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
        released_qty: Optional[Any] = None,
        released_notional: Optional[Any] = None,
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
            released_qty=released_qty if released_qty is not None else (row.get("open_qty") or row.get("original_qty")),
            released_notional=released_notional if released_notional is not None else row.get("notional_basis"),
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
