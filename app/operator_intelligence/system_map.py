"""Plain-English codebase/system map for the operator surface."""

from __future__ import annotations

from pathlib import Path

from app.core.authority_graph import authority_graph_summary


SYSTEM_MAP_SUMMARY = {
    "report_path": "reports/poverty_killer_system_map_operator_explainer.md",
    "sections": [
        "runtime launcher",
        "MarketTruthSnapshot",
        "DecisionFrame",
        "NetEdge",
        "ExecutionEngine",
        "BrokerBoundary",
        "OMS",
        "Fill/TCA/Fee hydration",
        "Operator API",
        "Supervisor",
        "UI",
        "World Awareness",
        "AI Chief Operator",
        "live readiness gates",
        "safe touch zones",
        "do-not-touch zones",
        "authority graph",
    ],
    "live_status": "LIVE_LOCKED",
    "real_money_status": "BLOCKED",
    "advisory_ai_only": True,
    "authority_graph_version": authority_graph_summary()["version"],
}


def _render_authority_graph_markdown() -> str:
    graph = authority_graph_summary()
    lines = [
        "## Authority Graph",
        "The authority graph names exactly one final-decision owner for each",
        "commercial PAPER-readiness authority. Contributors are visible evidence,",
        "diagnostic, gate-input, adapter, or display providers; they cannot",
        "override the owner.",
        "",
    ]
    for entry in graph["authorities"]:
        owner = entry["owner"]
        lines.append(f"### {entry['authority']}")
        lines.append(f"Owner: `{owner['module']}`")
        lines.append(f"Final decision: {owner['final_decision']}")
        lines.append("Contributors:")
        for contributor in entry["contributors"]:
            status = contributor["status"]
            reason = contributor.get("blocked_reason")
            suffix = f" ({status}: {reason})" if reason else f" ({status})"
            lines.append(
                f"- `{contributor['module']}` - {contributor['role']}; "
                f"{contributor['boundary']}{suffix}"
            )
        lines.append("")
    lines.append("### Non-Authority Conflict Resolutions")
    for item in graph["non_authority_conflict_resolutions"]:
        lines.append(
            f"- Conflict {item['conflict_id']} `{item['seam']}`: "
            f"{item['final_owner']} owns; `{item['reference_module']}` remains "
            f"{item['status']}."
        )
    return "\n".join(lines)


def render_system_map_markdown() -> str:
    return (
        """# Poverty Killer System Map - Operator Explainer

## Runtime Launcher
The governed local launcher starts only the operator API/UI. Bounded PAPER runs
are started by server-side operator intents through the PAPER supervisor.

## MarketTruthSnapshot
MarketTruthSnapshot is the executable market-data authority. Stale, synthetic,
backfill, replay, mismatched, or missing truth must remain non-executable.

## DecisionFrame
DecisionFrame records why a BUY, SELL, or NO_TRADE decision emerged from the
current evidence. Operator explainers may summarize it, but must not change
scores, thresholds, or routing behavior.

## NetEdge
NetEdge is an economic gate. Operator dashboards can report whether realized vs
modeled evidence is available, but cannot relax economic thresholds.

## ExecutionEngine
ExecutionEngine is not an operator UI dependency. This seam does not import or
modify it; broker mutation remains outside read-only operator intelligence.

## BrokerBoundary
BrokerBoundary is the broker authority layer. AI, UI, reports, and explainers
cannot call it directly or submit/cancel/liquidate orders.

## OMS
OMS owns order lifecycle truth and shutdown reconciliation. The operator surface
may display summaries and conflicts, never rewrite OMS state.

## Fill / TCA / Fee Hydration
Fill, TCA, and broker fee hydration are evidence streams. Unknown fee, P&L, and
TCA values stay unknown until broker-confirmed or existing runtime evidence is
available.

## Operator API
The supported API path is `/operator/*`. It is read-only except bounded PAPER
process intents and advisory queues explicitly modeled as safe local state.

## Supervisor
The PAPER supervisor tracks bounded local PAPER processes, duplicate-run
prevention, log paths, session metadata, and audit events.

## UI
The operator control panel displays source labels, truth labels, run archive,
action center, watchdog alerts, AI recommendations, and live lock status. It has
no manual trade, force trade, or live start controls.

## World Awareness
World Awareness is advisory only. It cannot bypass MarketTruthSnapshot, NetEdge,
risk guardrails, BrokerBoundary, OMS, or hard gates.

## AI Chief Operator
AI Chief is advisory only. Providers are disabled by default or mock-only in
tests. Recommendations require Shan review and cannot execute trading actions.

## Live Readiness Gates
Live is locked. Real-money mode is blocked. Any future live readiness requires a
separate governance packet and evidence bundle.

## Safe To Touch
Read-only operator summaries, UI display contracts, reports, tests, local alert
queues, advisory AI context, and governance queue metadata are safe touch zones
when governed.

## Must Not Touch
Do not touch broker adapters, execution mutation paths, OMS internals, strategy
or alpha behavior, thresholds, live endpoints, real-money controls, secrets,
runtime logs/state/DB files, or quarantined dashboard code without explicit
Board authorization.
"""
        + "\n"
        + _render_authority_graph_markdown()
        + "\n"
    )


def ensure_system_map_report(path: Path | None = None) -> dict[str, object]:
    target = Path(path or SYSTEM_MAP_SUMMARY["report_path"])
    target.parent.mkdir(parents=True, exist_ok=True)
    markdown = render_system_map_markdown()
    target.write_text(markdown, encoding="utf-8", newline="\n")
    return {
        "source": "OPERATOR_SYSTEM_MAP",
        "report_path": str(target),
        "summary": dict(SYSTEM_MAP_SUMMARY),
        "markdown": markdown,
        "secrets_values_exposed": False,
    }
