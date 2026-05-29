"""Lightweight operator evidence graph.

This is a structured summary, not a graph database. It links operator-safe
evidence surfaces so AI and the UI can explain what exists, what is missing,
and what blocks promotion without ingesting raw logs or secrets.
"""

from __future__ import annotations

from typing import Any


def _first_run(run_archive: dict[str, Any]) -> dict[str, Any]:
    runs = run_archive.get("runs") or []
    return dict(runs[0]) if runs else {}


def _reason_codes(run: dict[str, Any]) -> list[str]:
    values = run.get("reason_codes") or run.get("reasonCodes") or []
    if isinstance(values, (list, tuple)):
        return [str(item) for item in values]
    if values:
        return [str(values)]
    return []


def _missing_evidence(
    *,
    run: dict[str, Any],
    decision_explainer: dict[str, Any],
    pnl: dict[str, Any],
    tca: dict[str, Any],
    action_center: dict[str, Any],
    provider_readiness: dict[str, Any],
) -> list[str]:
    missing: list[str] = []
    if not run:
        missing.append("NO_RUN_ARCHIVE_ENTRY")
    if decision_explainer.get("source") == "NO_ACTIVE_RUNTIME_ATTACHED" or not decision_explainer.get("frame_id"):
        missing.append("NO_ACTIVE_DECISIONFRAME_SUMMARY")
    if (pnl.get("realized_pnl") or {}).get("broker_confirmed") is not True:
        missing.append("BROKER_CONFIRMED_REALIZED_PNL_UNAVAILABLE")
    if tca.get("status") in {None, "UNKNOWN", "UNKNOWN_NO_ACTIVE_RUNTIME"}:
        missing.append("TCA_COMPLETE_EVIDENCE_UNAVAILABLE")
    if (action_center.get("counts") or {}).get("BLOCKER", 0):
        missing.append("ACTION_CENTER_BLOCKERS_PRESENT")
    if (provider_readiness.get("counts") or {}).get("MISSING_CREDENTIALS", 0):
        missing.append("PROVIDER_CREDENTIALS_MISSING")
    return missing


def build_evidence_graph(
    *,
    run_archive: dict[str, Any],
    decision_explainer: dict[str, Any],
    market_truth: dict[str, Any],
    netedge: dict[str, Any],
    pnl: dict[str, Any],
    orders: dict[str, Any],
    fills: dict[str, Any],
    tca: dict[str, Any],
    oms: dict[str, Any],
    action_center: dict[str, Any],
    watchdog: dict[str, Any],
    provider_readiness: dict[str, Any],
) -> dict[str, Any]:
    run = _first_run(run_archive)
    nodes = [
        {
            "node_id": "latest_run",
            "label": "Latest Run",
            "truth_label": "operator_archive",
            "summary": run.get("final_verdict") or "UNKNOWN",
            "run_id": run.get("run_id") or run.get("runId"),
            "report_path": run.get("report_path") or run.get("reportPath"),
        },
        {
            "node_id": "decision_explainer",
            "label": "Decision Explainer",
            "truth_label": "decisionframe_summary",
            "summary": decision_explainer.get("headline") or "No DecisionFrame summary loaded.",
        },
        {
            "node_id": "market_truth",
            "label": "MarketTruthSnapshot",
            "truth_label": "market_truth_summary",
            "summary": market_truth.get("summary") or market_truth.get("source") or "summary unavailable",
        },
        {
            "node_id": "netedge",
            "label": "NetEdge",
            "truth_label": "economic_gate_summary",
            "summary": netedge.get("net_edge") or netedge.get("status") or "UNKNOWN",
        },
        {
            "node_id": "fills_tca_fees",
            "label": "Fills / TCA / Fees",
            "truth_label": "broker_confirmed_when_available",
            "summary": f"fills={fills.get('local_fills', 0)} fee_status={fills.get('fee_status', 'UNKNOWN')} tca={tca.get('status') or tca.get('execution_quality_verdict', 'UNKNOWN')}",
        },
        {
            "node_id": "oms",
            "label": "OMS / Reconciliation",
            "truth_label": "order_lifecycle_summary",
            "summary": f"open={orders.get('broker_confirmed_open_orders', 0)} conflicts={orders.get('reconciliation_conflicts', 0)} shutdown={oms.get('status', 'UNKNOWN')}",
        },
        {
            "node_id": "watchdog_action_center",
            "label": "Watchdog / Action Center",
            "truth_label": "operator_safety_summary",
            "summary": f"alerts={watchdog.get('alert_count', 0)} blockers={(action_center.get('counts') or {}).get('BLOCKER', 0)}",
        },
        {
            "node_id": "provider_readiness",
            "label": "Provider Readiness",
            "truth_label": "config_presence_only",
            "summary": f"providers={provider_readiness.get('provider_count', 0)} missing={(provider_readiness.get('counts') or {}).get('MISSING_CREDENTIALS', 0)}",
        },
    ]
    edges = [
        {"from": "latest_run", "to": "decision_explainer", "relationship": "run_decision_context"},
        {"from": "decision_explainer", "to": "market_truth", "relationship": "decision_requires_market_truth"},
        {"from": "decision_explainer", "to": "netedge", "relationship": "decision_requires_economic_gate"},
        {"from": "latest_run", "to": "fills_tca_fees", "relationship": "run_execution_evidence"},
        {"from": "fills_tca_fees", "to": "oms", "relationship": "fill_order_reconciliation"},
        {"from": "watchdog_action_center", "to": "provider_readiness", "relationship": "operator_blocker_context"},
    ]
    missing = _missing_evidence(
        run=run,
        decision_explainer=decision_explainer,
        pnl=pnl,
        tca=tca,
        action_center=action_center,
        provider_readiness=provider_readiness,
    )
    return {
        "source": "OPERATOR_RESEARCH_EVIDENCE_GRAPH",
        "graph_version": "operator-evidence-graph-v1",
        "nodes": nodes,
        "edges": edges,
        "latest_run_id": run.get("run_id") or run.get("runId"),
        "report_path": run.get("report_path") or run.get("reportPath"),
        "reason_codes": _reason_codes(run),
        "missing_evidence": missing,
        "promotion_blockers": missing + _reason_codes(run),
        "broker_confirmed": {
            "orders": orders.get("broker_truth_canonical") is True,
            "realized_pnl": (pnl.get("realized_pnl") or {}).get("broker_confirmed") is True,
        },
        "unknowns": missing,
        "paper_only": True,
        "raw_logs_included": False,
        "secrets_values_exposed": False,
        "can_execute": False,
        "broker_call_occurred": False,
        "trading_mutation_occurred": False,
        "live_enabled": False,
        "real_money_enabled": False,
    }
