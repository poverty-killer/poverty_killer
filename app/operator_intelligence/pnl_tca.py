"""Honest P&L, TCA, and execution-quality summaries."""

from __future__ import annotations

from typing import Any


def _truth(value: Any, *, source: str, label: str | None = None) -> dict[str, Any]:
    has_value = value is not None
    return {
        "value": value,
        "truth_label": label or ("broker_confirmed" if has_value else "unknown"),
        "source": source if has_value else "UNKNOWN_NOT_AVAILABLE",
        "broker_confirmed": bool(has_value and source.upper().startswith("BROKER")),
    }


def build_pnl_summary(*, fills_summary: dict[str, Any], tca_summary: dict[str, Any]) -> dict[str, Any]:
    realized = fills_summary.get("broker_confirmed_realized_pnl")
    unrealized = fills_summary.get("broker_confirmed_unrealized_pnl")
    return {
        "source": "OPERATOR_READ_ONLY_PNL_SUMMARY",
        "realized_pnl": _truth(realized, source="BROKER_CONFIRMED_REALIZED_PNL"),
        "unrealized_pnl": _truth(unrealized, source="BROKER_CONFIRMED_UNREALIZED_PNL"),
        "net_pnl": _truth(None if realized is None or unrealized is None else realized + unrealized, source="BROKER_CONFIRMED_NET_PNL"),
        "fill_count": int(fills_summary.get("broker_fill_ledger_rows") or fills_summary.get("local_fills") or 0),
        "fee_hydration": {
            "pending": int(fills_summary.get("broker_fee_hydration_pending_count") or 0),
            "matched": int(fills_summary.get("broker_fee_hydration_count") or 0),
            "conflict": int(fills_summary.get("broker_fee_hydration_conflict_count") or 0),
            "source": fills_summary.get("fee_source") or "UNKNOWN",
        },
        "tca_status": tca_summary.get("execution_quality_verdict") or "UNKNOWN",
        "expected_vs_realized_netedge_availability": {
            "available_count": int(tca_summary.get("realized_vs_modeled_netedge_available_count") or 0),
            "unknown_count": int(tca_summary.get("realized_vs_modeled_netedge_unknown_count") or 0),
        },
        "slippage": _truth(None, source="UNKNOWN_NOT_AVAILABLE"),
        "per_symbol_quality": [],
        "estimated_values_present": False,
        "fake_pnl_allowed": False,
        "fake_fees_allowed": False,
        "fake_tca_allowed": False,
    }


def build_tca_dashboard(*, fills_summary: dict[str, Any], tca_summary: dict[str, Any]) -> dict[str, Any]:
    complete = int(tca_summary.get("tca_complete_count") or 0)
    pending = int(tca_summary.get("tca_fee_pending_count") or fills_summary.get("broker_fee_hydration_pending_count") or 0)
    unknown = int(tca_summary.get("tca_unknown_count") or 0)
    if complete > 0 and pending == 0 and unknown == 0:
        status = "COMPLETE"
    elif pending > 0:
        status = "PENDING_FEE_DETAIL"
    else:
        status = "UNKNOWN"
    return {
        "source": "OPERATOR_READ_ONLY_TCA_DASHBOARD",
        "status": status,
        "records": {
            "total": int(tca_summary.get("tca_records_count") or 0),
            "complete": complete,
            "unknown": unknown,
            "estimated": int(tca_summary.get("tca_estimated_count") or 0),
            "fee_pending": pending,
        },
        "fee_hydration": {
            "matched": int(fills_summary.get("broker_fee_hydration_count") or 0),
            "pending": int(fills_summary.get("broker_fee_hydration_pending_count") or 0),
            "conflict": int(fills_summary.get("broker_fee_hydration_conflict_count") or 0),
            "unmatched": int(fills_summary.get("broker_fee_hydration_unmatched_count") or 0),
        },
        "slippage_available": complete > 0,
        "expected_vs_realized_netedge_available": int(tca_summary.get("realized_vs_modeled_netedge_available_count") or 0),
        "per_symbol_quality": [],
        "fake_fees_allowed": False,
        "fake_tca_allowed": False,
    }
