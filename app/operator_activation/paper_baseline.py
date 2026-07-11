"""Local PAPER baseline adoption authority.

This module stores operator acceptance of an existing PAPER portfolio baseline.
It never calls Alpaca and never mutates broker state. The stored artifact is a
redacted local proof used by launch readiness and the operator UI.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

from app.operator_credentials.store import normalize_alpaca_account_suffix


BASELINE_POLICY_CLEAN_ONLY = "CLEAN_ONLY"
BASELINE_POLICY_PROTECTED = "ADOPT_EXISTING_POSITIONS_PROTECTED"
BASELINE_POLICY_MANAGE_EXISTING = "ADOPT_AND_MANAGE_EXISTING_POSITIONS"
BASELINE_SCHEMA_VERSION = "paper-existing-position-baseline-v1"
PAPER_BASELINE_ENV_REQUIRED = "PK_PAPER_BASELINE_REQUIRED"
PAPER_BASELINE_ENV_PATH = "PK_PAPER_BASELINE_PATH"
PAPER_BASELINE_ENV_SNAPSHOT_ID = "PK_PAPER_BASELINE_SNAPSHOT_ID"
PAPER_BASELINE_ENV_SNAPSHOT_HASH = "PK_PAPER_BASELINE_SNAPSHOT_HASH"
PAPER_BASELINE_ENV_POLICY = "PK_PAPER_BASELINE_POLICY"
PAPER_BASELINE_ENV_PROTECTED_SYMBOLS = "PK_PAPER_BASELINE_PROTECTED_SYMBOLS"
PAPER_BASELINE_ENV_SAME_SYMBOL_POLICY = "PK_PAPER_BASELINE_SAME_SYMBOL_POLICY"
PAPER_BASELINE_ENV_RUN_LOT_TRACKING = "PK_PAPER_BASELINE_RUN_LOT_TRACKING_AVAILABLE"

SAME_SYMBOL_POLICY_BLOCK = "BLOCK_BASELINE_SYMBOL_TRADES_UNTIL_RUN_LOT_TRACKING"
PAPER_BASELINE_RUNTIME_CONTEXT_REQUIRED = "PAPER_BASELINE_RUNTIME_CONTEXT_REQUIRED"
PAPER_BASELINE_SYMBOL_PROTECTED = "PAPER_BASELINE_SYMBOL_PROTECTED"

PREFLIGHT_BLOCKED_BASELINE_ADOPTION_REQUIRED = "PREFLIGHT_BLOCKED_BASELINE_ADOPTION_REQUIRED"
PREFLIGHT_READY_WITH_ACCEPTED_EXISTING_POSITIONS = "PREFLIGHT_READY_WITH_ACCEPTED_EXISTING_POSITIONS"
PAPER_BASELINE_DRIFT_REQUIRES_REFRESH = "PAPER_BASELINE_DRIFT_REQUIRES_REFRESH"
PREFLIGHT_BLOCKED_OPEN_ORDERS = "PREFLIGHT_BLOCKED_OPEN_ORDERS"
PREFLIGHT_CLEAN_BASELINE_READY = "PREFLIGHT_CLEAN_BASELINE_READY"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redact_identifier(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    suffix = text[-6:] if len(text) > 6 else text
    return f"redacted_suffix:{suffix}"


def _clean_decimal_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return str(Decimal(text))
    except (InvalidOperation, ValueError):
        return text


def _decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    text = _clean_decimal_text(value)
    if text is None:
        return default
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return default


def normalize_baseline_symbol(symbol: Any) -> str:
    return str(symbol or "").upper().replace("/", "").replace("-", "").replace("_", "").strip()


def _as_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [dict(row) for row in value if isinstance(row, Mapping)]
    return []


def _open_orders(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    orders = snapshot.get("open_orders")
    if orders is None:
        orders = snapshot.get("orders")
    return _as_list(orders)


def _positions(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    return _as_list(snapshot.get("positions"))


def _count_or_len(snapshot: Mapping[str, Any], key: str, rows: list[dict[str, Any]]) -> int:
    value = snapshot.get(key)
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return len(rows)


def _endpoint_family(snapshot: Mapping[str, Any]) -> str:
    endpoint = snapshot.get("endpoint") if isinstance(snapshot.get("endpoint"), Mapping) else {}
    return str(
        snapshot.get("endpoint_family")
        or snapshot.get("paper_endpoint_family")
        or endpoint.get("family")
        or ""
    ).strip().lower()


def _account(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    account = snapshot.get("account")
    if isinstance(account, Mapping):
        return dict(account)
    summary = snapshot.get("summary")
    if isinstance(summary, Mapping):
        return dict(summary)
    return {}


def _safe_account(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    account = _account(snapshot)
    return {
        "endpoint_family": _endpoint_family(snapshot) or "paper",
        "account_id": _redact_identifier(account.get("id") or account.get("account_id")),
        "status": str(account.get("status") or snapshot.get("account_status") or "UNKNOWN"),
        "equity": _clean_decimal_text(account.get("equity") or account.get("total_equity")),
        "buying_power": _clean_decimal_text(account.get("buying_power")),
        "currency": account.get("currency"),
        "trading_blocked": bool(account.get("trading_blocked")),
        "account_blocked": bool(account.get("account_blocked")),
        "transfers_blocked": bool(account.get("transfers_blocked")),
        "pattern_day_trader": bool(account.get("pattern_day_trader")),
    }


def _safe_order(order: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "order_id": _redact_identifier(order.get("id") or order.get("order_id")),
        "symbol": str(order.get("symbol") or "UNKNOWN").upper(),
        "side": str(order.get("side") or "unknown").lower(),
        "qty": _clean_decimal_text(order.get("qty") or order.get("quantity")),
        "notional": _clean_decimal_text(order.get("notional")),
        "type": order.get("type"),
        "status": order.get("status"),
        "submitted_at": order.get("submitted_at"),
    }


def _safe_position(position: Mapping[str, Any]) -> dict[str, Any]:
    symbol = str(position.get("symbol") or "UNKNOWN").upper()
    return {
        "symbol": symbol,
        "asset_class": position.get("asset_class"),
        "qty": _clean_decimal_text(position.get("qty") or position.get("quantity")),
        "side": position.get("side"),
        "avg_entry_price": _clean_decimal_text(position.get("avg_entry_price") or position.get("average_entry_price")),
        "cost_basis": _clean_decimal_text(position.get("cost_basis")),
        "market_value": _clean_decimal_text(position.get("market_value")),
        "current_price": _clean_decimal_text(position.get("current_price") or position.get("current_market_price")),
        "unrealized_pl": _clean_decimal_text(position.get("unrealized_pl") or position.get("unrealized_pnl")),
        "unrealized_plpc": _clean_decimal_text(position.get("unrealized_plpc") or position.get("unrealized_pnl_percent")),
        "exchange": position.get("exchange"),
        "position_id": _redact_identifier(position.get("asset_id") or position.get("id") or position.get("position_id")),
        "baseline_position": True,
    }


def _position_signature(positions: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for position in positions:
        rows.append(
            {
                "symbol": normalize_baseline_symbol(position.get("symbol")),
                "qty": str(_decimal(position.get("qty") or position.get("quantity"))),
                "side": str(position.get("side") or "").lower(),
                "asset_class": str(position.get("asset_class") or "").lower(),
            }
        )
    rows.sort(key=lambda row: (row["symbol"], row["qty"], row["side"], row["asset_class"]))
    return rows


def _baseline_positions_value(positions: list[dict[str, Any]]) -> str | None:
    total = Decimal("0")
    seen = False
    for position in positions:
        value = _clean_decimal_text(position.get("market_value"))
        if value is None:
            continue
        total += _decimal(value)
        seen = True
    return str(total) if seen else None


def _snapshot_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class PaperBaselineRuntimeContext:
    baseline_required: bool
    baseline_loaded: bool
    baseline_snapshot_id: str | None = None
    snapshot_hash: str | None = None
    policy: str | None = None
    protected_symbols_normalized: tuple[str, ...] = ()
    protected_positions: dict[str, dict[str, Any]] = field(default_factory=dict)
    accepted_at: str | None = None
    source_path: str | None = None
    same_symbol_trading_policy: str = SAME_SYMBOL_POLICY_BLOCK
    run_lot_tracking_available: bool = False
    baseline_context_error: str | None = None

    @property
    def protected_symbols_count(self) -> int:
        return len(self.protected_symbols_normalized)

    @property
    def same_symbol_baseline_guard_active(self) -> bool:
        return (
            self.baseline_loaded
            and self.policy == BASELINE_POLICY_PROTECTED
            and self.protected_symbols_count > 0
            and not self.run_lot_tracking_available
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": "OPERATOR_PAPER_BASELINE_RUNTIME_CONTEXT",
            "baseline_required": self.baseline_required,
            "baseline_loaded": self.baseline_loaded,
            "baseline_snapshot_id": self.baseline_snapshot_id,
            "snapshot_hash": self.snapshot_hash,
            "policy": self.policy,
            "protected_symbols_normalized": list(self.protected_symbols_normalized),
            "protected_symbols_count": self.protected_symbols_count,
            "protected_positions": dict(self.protected_positions),
            "accepted_at": self.accepted_at,
            "source_path": self.source_path,
            "same_symbol_trading_policy": self.same_symbol_trading_policy,
            "run_lot_tracking_available": self.run_lot_tracking_available,
            "same_symbol_baseline_guard_active": self.same_symbol_baseline_guard_active,
            "baseline_context_error": self.baseline_context_error,
            "alpaca_network_call_occurred": False,
            "broker_mutation_occurred": False,
            "secrets_values_exposed": False,
        }

    def to_env(self) -> dict[str, str]:
        if not self.baseline_loaded:
            return {}
        return {
            PAPER_BASELINE_ENV_REQUIRED: "1",
            PAPER_BASELINE_ENV_PATH: str(self.source_path or ""),
            PAPER_BASELINE_ENV_SNAPSHOT_ID: str(self.baseline_snapshot_id or ""),
            PAPER_BASELINE_ENV_SNAPSHOT_HASH: str(self.snapshot_hash or ""),
            PAPER_BASELINE_ENV_POLICY: str(self.policy or BASELINE_POLICY_PROTECTED),
            PAPER_BASELINE_ENV_PROTECTED_SYMBOLS: ",".join(self.protected_symbols_normalized),
            PAPER_BASELINE_ENV_SAME_SYMBOL_POLICY: self.same_symbol_trading_policy,
            PAPER_BASELINE_ENV_RUN_LOT_TRACKING: "1" if self.run_lot_tracking_available else "0",
        }


def _runtime_context_error(reason: str, *, required: bool = True, source_path: Path | str | None = None) -> PaperBaselineRuntimeContext:
    return PaperBaselineRuntimeContext(
        baseline_required=required,
        baseline_loaded=False,
        source_path=str(source_path) if source_path else None,
        baseline_context_error=reason,
    )


def build_paper_baseline_runtime_context(
    accepted_baseline: Mapping[str, Any] | None,
    *,
    source_path: Path | str | None = None,
    required: bool = True,
    expected_snapshot_id: str | None = None,
    expected_snapshot_hash: str | None = None,
    expected_policy: str = BASELINE_POLICY_PROTECTED,
) -> PaperBaselineRuntimeContext:
    if not isinstance(accepted_baseline, Mapping) or accepted_baseline.get("accepted") is not True:
        return _runtime_context_error(PAPER_BASELINE_RUNTIME_CONTEXT_REQUIRED, required=required, source_path=source_path)

    accepted_snapshot = _accepted_snapshot(accepted_baseline)
    if accepted_snapshot is None:
        return _runtime_context_error("PAPER_BASELINE_SNAPSHOT_MISSING", required=required, source_path=source_path)

    policy = str(accepted_baseline.get("policy") or (accepted_snapshot.get("proof") or {}).get("policy") or "")
    if policy != expected_policy:
        clean_baseline_allowed = (
            policy == BASELINE_POLICY_CLEAN_ONLY
            and expected_policy == BASELINE_POLICY_PROTECTED
            and not _as_list(accepted_snapshot.get("positions"))
        )
        if not clean_baseline_allowed:
            return _runtime_context_error("PAPER_BASELINE_POLICY_MISMATCH", required=required, source_path=source_path)

    open_order_count = int(((accepted_snapshot.get("orders") or {}).get("open_order_count") or 0))
    if open_order_count != 0:
        return _runtime_context_error("PAPER_BASELINE_OPEN_ORDERS_PRESENT", required=required, source_path=source_path)

    proof = accepted_snapshot.get("proof") if isinstance(accepted_snapshot.get("proof"), Mapping) else {}
    baseline_snapshot_id = str(accepted_baseline.get("baseline_snapshot_id") or proof.get("baseline_snapshot_id") or "")
    snapshot_hash = str(accepted_baseline.get("snapshot_hash") or proof.get("snapshot_hash") or "")
    if not baseline_snapshot_id or not snapshot_hash:
        return _runtime_context_error("PAPER_BASELINE_PROOF_MISSING", required=required, source_path=source_path)
    if expected_snapshot_id and baseline_snapshot_id != expected_snapshot_id:
        return _runtime_context_error("PAPER_BASELINE_SNAPSHOT_ID_MISMATCH", required=required, source_path=source_path)
    if expected_snapshot_hash and snapshot_hash != expected_snapshot_hash:
        return _runtime_context_error("PAPER_BASELINE_SNAPSHOT_HASH_MISMATCH", required=required, source_path=source_path)

    positions = _as_list(accepted_snapshot.get("positions"))
    protected_positions: dict[str, dict[str, Any]] = {}
    for position in positions:
        normalized = normalize_baseline_symbol(position.get("symbol"))
        if not normalized:
            continue
        protected_positions[normalized] = {
            "symbol": str(position.get("symbol") or normalized).upper(),
            "normalized_symbol": normalized,
            "qty": _clean_decimal_text(position.get("qty") or position.get("quantity")),
            "side": position.get("side"),
            "asset_class": position.get("asset_class"),
            "baseline_position": True,
        }
    protected_symbols = tuple(sorted(protected_positions))
    if not protected_symbols:
        if policy == BASELINE_POLICY_CLEAN_ONLY and not positions:
            return PaperBaselineRuntimeContext(
                baseline_required=required,
                baseline_loaded=True,
                baseline_snapshot_id=baseline_snapshot_id,
                snapshot_hash=snapshot_hash,
                policy=policy,
                protected_symbols_normalized=(),
                protected_positions={},
                accepted_at=str(accepted_baseline.get("accepted_at") or proof.get("accepted_at") or ""),
                source_path=str(source_path) if source_path else None,
                same_symbol_trading_policy=SAME_SYMBOL_POLICY_BLOCK,
                run_lot_tracking_available=False,
                baseline_context_error=None,
            )
        return _runtime_context_error("PAPER_BASELINE_PROTECTED_SYMBOLS_MISSING", required=required, source_path=source_path)

    return PaperBaselineRuntimeContext(
        baseline_required=required,
        baseline_loaded=True,
        baseline_snapshot_id=baseline_snapshot_id,
        snapshot_hash=snapshot_hash,
        policy=policy,
        protected_symbols_normalized=protected_symbols,
        protected_positions=protected_positions,
        accepted_at=str(accepted_baseline.get("accepted_at") or proof.get("accepted_at") or ""),
        source_path=str(source_path) if source_path else None,
        same_symbol_trading_policy=SAME_SYMBOL_POLICY_BLOCK,
        run_lot_tracking_available=False,
        baseline_context_error=None,
    )


def load_paper_baseline_runtime_context_from_path(
    path: Path | str,
    *,
    required: bool = True,
    expected_snapshot_id: str | None = None,
    expected_snapshot_hash: str | None = None,
    expected_policy: str = BASELINE_POLICY_PROTECTED,
) -> PaperBaselineRuntimeContext:
    baseline_path = Path(path)
    if not baseline_path.exists():
        return _runtime_context_error(PAPER_BASELINE_RUNTIME_CONTEXT_REQUIRED, required=required, source_path=baseline_path)
    try:
        with baseline_path.open("r", encoding="utf-8") as handle:
            accepted = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return _runtime_context_error("PAPER_BASELINE_CONTEXT_UNREADABLE", required=required, source_path=baseline_path)
    return build_paper_baseline_runtime_context(
        accepted,
        source_path=baseline_path,
        required=required,
        expected_snapshot_id=expected_snapshot_id,
        expected_snapshot_hash=expected_snapshot_hash,
        expected_policy=expected_policy,
    )


def load_paper_baseline_runtime_context_from_env(env: Mapping[str, str]) -> PaperBaselineRuntimeContext:
    required = _truthy(env.get(PAPER_BASELINE_ENV_REQUIRED))
    path = str(env.get(PAPER_BASELINE_ENV_PATH) or "").strip()
    if not required and not path:
        return PaperBaselineRuntimeContext(baseline_required=False, baseline_loaded=False)
    if not path:
        return _runtime_context_error(PAPER_BASELINE_RUNTIME_CONTEXT_REQUIRED, required=True)
    return load_paper_baseline_runtime_context_from_path(
        path,
        required=required or True,
        expected_snapshot_id=str(env.get(PAPER_BASELINE_ENV_SNAPSHOT_ID) or "").strip() or None,
        expected_snapshot_hash=str(env.get(PAPER_BASELINE_ENV_SNAPSHOT_HASH) or "").strip() or None,
        expected_policy=str(env.get(PAPER_BASELINE_ENV_POLICY) or BASELINE_POLICY_PROTECTED),
    )


def build_safe_preflight_snapshot(snapshot: Mapping[str, Any], *, accepted_by: str = "Shan/local operator", accepted_at: str | None = None, policy: str = BASELINE_POLICY_PROTECTED) -> dict[str, Any]:
    orders = [_safe_order(order) for order in _open_orders(snapshot)]
    positions = [_safe_position(position) for position in _positions(snapshot)]
    account = _safe_account(snapshot)
    safe = {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "account": account,
        "orders": {
            "open_order_count": _count_or_len(snapshot, "open_order_count", orders),
            "open_orders": orders,
        },
        "positions": positions,
        "position_count": _count_or_len(snapshot, "position_count", positions),
        "position_symbols": [position["symbol"] for position in positions],
        "position_signature": _position_signature(positions),
        "proof": {
            "accepted_at": accepted_at or utc_now_iso(),
            "accepted_by_operator": accepted_by,
            "policy": policy,
            "alpaca_network_call_occurred": False,
            "broker_mutation_occurred": False,
            "secrets_values_exposed": False,
        },
    }
    digest = _snapshot_hash(safe)
    safe["proof"]["snapshot_hash"] = digest
    safe["proof"]["baseline_snapshot_id"] = f"paper-baseline-{digest[:12]}"
    return safe


def accept_existing_position_baseline(
    snapshot: Mapping[str, Any],
    *,
    accepted_by: str = "Shan/local operator",
    accepted_at: str | None = None,
    policy: str = BASELINE_POLICY_PROTECTED,
) -> dict[str, Any]:
    if policy not in {BASELINE_POLICY_PROTECTED, BASELINE_POLICY_CLEAN_ONLY, BASELINE_POLICY_MANAGE_EXISTING}:
        policy = BASELINE_POLICY_PROTECTED
    safe = build_safe_preflight_snapshot(
        snapshot,
        accepted_by=accepted_by,
        accepted_at=accepted_at,
        policy=policy,
    )
    endpoint_family = str(safe["account"].get("endpoint_family") or "").lower()
    if endpoint_family != "paper":
        return _blocked_acceptance("PAPER_ENDPOINT_REQUIRED", "Baseline acceptance requires the Alpaca PAPER endpoint.", safe)
    if safe["orders"]["open_order_count"] != 0:
        return _blocked_acceptance("OPEN_ORDERS_PRESENT", "Open orders must be zero before accepting a baseline.", safe)
    if int(safe.get("position_count") or 0) <= 0 and policy == BASELINE_POLICY_PROTECTED:
        return _blocked_acceptance("NO_EXISTING_POSITIONS", "Protected adoption is only needed when existing positions are present.", safe)
    account = safe["account"]
    if account.get("trading_blocked") or account.get("account_blocked"):
        return _blocked_acceptance("ACCOUNT_BLOCKED", "Account restrictions block baseline adoption.", safe)
    return {
        "source": "OPERATOR_PAPER_BASELINE",
        "status": "ACCEPTED",
        "accepted": True,
        "policy": policy,
        "baseline_snapshot": safe,
        "baseline_snapshot_id": safe["proof"]["baseline_snapshot_id"],
        "snapshot_hash": safe["proof"]["snapshot_hash"],
        "accepted_at": safe["proof"]["accepted_at"],
        "accepted_by_operator": accepted_by,
        "broker_mutation_occurred": False,
        "trading_mutation_occurred": False,
        "alpaca_network_call_occurred": False,
        "secrets_values_exposed": False,
    }


def _blocked_acceptance(reason_code: str, message: str, safe_snapshot: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source": "OPERATOR_PAPER_BASELINE",
        "status": "BLOCKED",
        "accepted": False,
        "reason_code": reason_code,
        "message": message,
        "safe_snapshot": dict(safe_snapshot),
        "broker_mutation_occurred": False,
        "trading_mutation_occurred": False,
        "alpaca_network_call_occurred": False,
        "secrets_values_exposed": False,
    }


def _accepted_snapshot(accepted_baseline: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(accepted_baseline, Mapping):
        return None
    snapshot = accepted_baseline.get("baseline_snapshot")
    if isinstance(snapshot, Mapping):
        return dict(snapshot)
    if str(accepted_baseline.get("schema_version") or "") == BASELINE_SCHEMA_VERSION:
        return dict(accepted_baseline)
    return None


def accepted_baseline_account_suffix(accepted_baseline: Mapping[str, Any] | None) -> str | None:
    accepted_snapshot = _accepted_snapshot(accepted_baseline)
    if not accepted_snapshot:
        return None
    account = accepted_snapshot.get("account")
    if not isinstance(account, Mapping):
        return None
    return normalize_alpaca_account_suffix(account.get("account_id") or account.get("id"))


def _positions_drift(current_positions: list[dict[str, Any]], accepted_snapshot: Mapping[str, Any]) -> bool:
    accepted_signature = accepted_snapshot.get("position_signature")
    if not isinstance(accepted_signature, list):
        accepted_signature = _position_signature(_as_list(accepted_snapshot.get("positions")))
    return _position_signature(current_positions) != accepted_signature


def build_baseline_adoption_state(
    *,
    current_snapshot: Mapping[str, Any] | None = None,
    accepted_baseline: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    accepted_snapshot = _accepted_snapshot(accepted_baseline)
    current = dict(current_snapshot or {})
    if not current and accepted_snapshot is None:
        return {
            "source": "OPERATOR_PAPER_BASELINE",
            "schema_version": "paper-baseline-view-v1",
            "status": "NOT_ACCEPTED",
            "decision": "READ_ONLY_PREFLIGHT_REQUIRED",
            "accepted": False,
            "policy": BASELINE_POLICY_PROTECTED,
            "position_count": 0,
            "position_symbols": [],
            "open_order_count": 0,
            "endpoint_family": "paper",
            "live_locked": True,
            "real_money_blocked": True,
            "start_ready": False,
            "reason": "No local baseline acceptance is stored.",
            "next_safe_action": "Run an explicitly approved read-only PAPER preflight before baseline adoption.",
            "protected_symbols": [],
            "same_symbol_trading_policy": "BLOCK_BASELINE_SYMBOL_TRADES_UNTIL_RUN_LOT_TRACKING",
            "pnl_attribution": build_pnl_attribution(current_snapshot=None, accepted_snapshot=None),
            "broker_mutation_occurred": False,
            "trading_mutation_occurred": False,
            "alpaca_network_call_occurred": False,
            "secrets_values_exposed": False,
        }
    current_positions = _positions(current)
    current_orders = _open_orders(current)
    position_count = _count_or_len(current, "position_count", current_positions) if current else int((accepted_snapshot or {}).get("position_count") or 0)
    open_order_count = _count_or_len(current, "open_order_count", current_orders) if current else int(((accepted_snapshot or {}).get("orders") or {}).get("open_order_count") or 0)
    symbols = [str(row.get("symbol") or "UNKNOWN").upper() for row in (current_positions or _as_list((accepted_snapshot or {}).get("positions")))]

    base = {
        "source": "OPERATOR_PAPER_BASELINE",
        "schema_version": "paper-baseline-view-v1",
        "policy": BASELINE_POLICY_PROTECTED,
        "accepted": accepted_snapshot is not None,
        "position_count": position_count,
        "position_symbols": symbols,
        "open_order_count": open_order_count,
        "endpoint_family": (_endpoint_family(current) or str(((accepted_snapshot or {}).get("account") or {}).get("endpoint_family") or "paper")),
        "live_locked": True,
        "real_money_blocked": True,
        "broker_mutation_occurred": False,
        "trading_mutation_occurred": False,
        "alpaca_network_call_occurred": False,
        "secrets_values_exposed": False,
        "protected_symbols": [str(row.get("symbol") or "UNKNOWN").upper() for row in _as_list((accepted_snapshot or {}).get("positions"))],
        "same_symbol_trading_policy": "BLOCK_BASELINE_SYMBOL_TRADES_UNTIL_RUN_LOT_TRACKING",
        "pnl_attribution": build_pnl_attribution(current_snapshot=current, accepted_snapshot=accepted_snapshot),
    }
    if open_order_count > 0:
        base.update(
            {
                "status": PREFLIGHT_BLOCKED_OPEN_ORDERS,
                "decision": "PREFLIGHT_BLOCKED",
                "start_ready": False,
                "reason": "Open orders exist; baseline acceptance and PAPER start remain blocked. No cancellation is authorized.",
                "next_safe_action": "Review open orders through read-only broker truth; do not cancel or modify without a separate Board packet.",
            }
        )
        return base
    if accepted_snapshot is None and position_count > 0:
        base.update(
            {
                "status": PREFLIGHT_BLOCKED_BASELINE_ADOPTION_REQUIRED,
                "decision": "PAPER_BASELINE_ADOPTION_REQUIRED",
                "start_ready": False,
                "reason": "Existing PAPER positions require explicit baseline adoption.",
                "next_safe_action": "Accept current positions as the protected PAPER baseline, then prepare a short position-aware PAPER smoke packet.",
            }
        )
        return base
    if accepted_snapshot is not None:
        if current and _positions_drift(current_positions, accepted_snapshot):
            base.update(
                {
                    "status": PAPER_BASELINE_DRIFT_REQUIRES_REFRESH,
                    "decision": "PREFLIGHT_BLOCKED",
                    "start_ready": False,
                    "baseline_snapshot_id": ((accepted_snapshot.get("proof") or {}).get("baseline_snapshot_id")),
                    "accepted_at": ((accepted_snapshot.get("proof") or {}).get("accepted_at")),
                    "reason": "Current positions differ from the accepted baseline; refresh read-only preflight and accept a new baseline.",
                    "next_safe_action": "Request explicit read-only PAPER preflight refresh before any PAPER run discussion.",
                }
            )
            return base
        base.update(
            {
                "status": PREFLIGHT_READY_WITH_ACCEPTED_EXISTING_POSITIONS,
                "decision": "PREFLIGHT_READY_FOR_SHORT_PAPER_SMOKE",
                "start_ready": True,
                "baseline_snapshot_id": ((accepted_snapshot.get("proof") or {}).get("baseline_snapshot_id")),
                "snapshot_hash": ((accepted_snapshot.get("proof") or {}).get("snapshot_hash")),
                "accepted_at": ((accepted_snapshot.get("proof") or {}).get("accepted_at")),
                "reason": "Existing positions are accepted as protected starting inventory.",
                "next_safe_action": "Prepare a 10-20 minute position-aware PAPER smoke packet; do not treat this as 72-hour readiness.",
            }
        )
        return base
    base.update(
        {
            "status": PREFLIGHT_CLEAN_BASELINE_READY,
            "decision": "PREFLIGHT_READY_CLEAN_BASELINE",
            "start_ready": True,
            "reason": "No existing positions are present in the supplied preflight snapshot.",
            "next_safe_action": "Proceed only under the separately approved bounded PAPER run packet.",
        }
    )
    return base


def build_pnl_attribution(*, current_snapshot: Mapping[str, Any] | None, accepted_snapshot: Mapping[str, Any] | None) -> dict[str, Any]:
    accepted_account = dict((accepted_snapshot or {}).get("account") or {}) if accepted_snapshot else {}
    current_account = _account(current_snapshot or {})
    baseline_equity = _clean_decimal_text(accepted_account.get("equity"))
    current_equity = _clean_decimal_text(current_account.get("equity") or current_account.get("total_equity"))
    incremental = None
    if baseline_equity is not None and current_equity is not None:
        incremental = str(_decimal(current_equity) - _decimal(baseline_equity))
    return {
        "baseline_account_equity": baseline_equity,
        "baseline_positions_value": _baseline_positions_value(_as_list((accepted_snapshot or {}).get("positions"))) if accepted_snapshot else None,
        "run_incremental_equity_pnl": incremental,
        "run_incremental_equity_pnl_label": "current account equity - baseline account equity; deposits/withdrawals not adjusted unless transfer data is added",
        "baseline_carry_pnl_label": "baseline carry P&L from mark-to-market movement in pre-existing positions; shown separately from bot run fills where available",
        "run_trade_pnl_label": "pending flight-recorder/fill attribution until a bounded PAPER run is approved and reconciled",
        "clean_baseline_claimed": False,
    }


def evaluate_protected_baseline_trade(
    *,
    symbol: str,
    side: str,
    requested_qty: Any,
    accepted_baseline: Mapping[str, Any] | None,
    run_acquired_qty: Any = None,
    lot_tracking_available: bool = False,
) -> dict[str, Any]:
    accepted_snapshot = _accepted_snapshot(accepted_baseline)
    runtime_symbols: set[str] = set()
    runtime_loaded = isinstance(accepted_baseline, Mapping) and accepted_baseline.get("baseline_loaded") is True
    if runtime_loaded:
        runtime_symbols = {
            normalize_baseline_symbol(symbol)
            for symbol in accepted_baseline.get("protected_symbols_normalized", ())
            if normalize_baseline_symbol(symbol)
        }
    if accepted_snapshot is None and not runtime_loaded:
        return {"allowed": True, "reason_code": "NO_ACCEPTED_BASELINE", "broker_mutation_occurred": False}
    policy = str(
        (accepted_baseline or {}).get("policy")
        or (((accepted_snapshot or {}).get("proof") or {}).get("policy"))
        or BASELINE_POLICY_PROTECTED
    )
    if policy != BASELINE_POLICY_PROTECTED:
        return {"allowed": policy == BASELINE_POLICY_MANAGE_EXISTING, "reason_code": policy, "broker_mutation_occurred": False}
    normalized = normalize_baseline_symbol(symbol)
    baseline_positions = _as_list((accepted_snapshot or {}).get("positions"))
    baseline_symbols = runtime_symbols or {normalize_baseline_symbol(position.get("symbol")) for position in baseline_positions}
    if normalized not in baseline_symbols:
        return {"allowed": True, "reason_code": "SYMBOL_NOT_IN_PROTECTED_BASELINE", "broker_mutation_occurred": False}
    if not lot_tracking_available:
        return {
            "allowed": False,
            "reason_code": PAPER_BASELINE_SYMBOL_PROTECTED,
            "detail": (
                f"{symbol} is blocked because {normalized} is in the accepted protected PAPER baseline. "
                "Same-symbol baseline trading is blocked until run lot tracking is available."
            ),
            "normalized_symbol": normalized,
            "broker_mutation_occurred": False,
        }
    if str(side or "").lower() == "sell":
        requested = _decimal(requested_qty)
        run_acquired = _decimal(run_acquired_qty)
        if requested > run_acquired:
            return {
                "allowed": False,
                "reason_code": "PAPER_BASELINE_SELL_EXCEEDS_RUN_ACQUIRED_QTY",
                "detail": "Sell would reduce protected baseline quantity or exceed run-acquired quantity.",
                "normalized_symbol": normalized,
                "broker_mutation_occurred": False,
            }
    return {"allowed": True, "reason_code": "RUN_LOT_TRACKED_BASELINE_SYMBOL_ALLOWED", "broker_mutation_occurred": False}


@dataclass
class PaperBaselineStore:
    path: Path
    last_error: str | None = None
    _record: dict[str, Any] | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        self._load()

    def _load(self) -> None:
        self.last_error = None
        self._record = None
        if not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                row = json.load(handle)
            if isinstance(row, dict):
                self._record = row
        except (OSError, json.JSONDecodeError) as exc:
            self.last_error = type(exc).__name__

    def current(self) -> dict[str, Any]:
        if self._record is None:
            return {
                "source": "OPERATOR_PAPER_BASELINE",
                "status": "NOT_ACCEPTED",
                "accepted": False,
                "policy": BASELINE_POLICY_PROTECTED,
                "store_path": str(self.path),
                "broker_mutation_occurred": False,
                "trading_mutation_occurred": False,
                "alpaca_network_call_occurred": False,
                "secrets_values_exposed": False,
                "last_error": self.last_error,
            }
        return dict(self._record)

    def accept(self, snapshot: Mapping[str, Any], *, accepted_by: str = "Shan/local operator", policy: str = BASELINE_POLICY_PROTECTED) -> dict[str, Any]:
        result = accept_existing_position_baseline(snapshot, accepted_by=accepted_by, policy=policy)
        if result.get("accepted") is not True:
            return result
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(result, handle, sort_keys=True, indent=2)
            handle.write("\n")
        self._record = dict(result)
        return dict(result)

    def status(self) -> dict[str, Any]:
        return {
            "store_type": "json_single_current_baseline",
            "path": str(self.path),
            "status": "DEGRADED" if self.last_error else "READY",
            "exists": self.path.exists(),
            "parent_exists": self.path.parent.exists(),
            "accepted": self._record is not None and self._record.get("accepted") is True,
            "last_error": self.last_error,
            "secrets_values_exposed": False,
        }
