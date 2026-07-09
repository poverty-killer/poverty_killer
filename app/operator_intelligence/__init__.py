"""Read-only operator intelligence helpers.

These modules summarize existing operator/session evidence. They do not import
or mutate broker, execution, OMS, alpha, threshold, or strategy code.
"""

from app.operator_intelligence.action_center import build_action_center
from app.operator_intelligence.archive import RunArchive, build_run_record
from app.operator_intelligence.decision_explainer import DecisionExplainer
from app.operator_intelligence.pnl_tca import build_pnl_summary, build_tca_dashboard
from app.operator_intelligence.reports import RunReportGenerator
from app.operator_intelligence.system_map import (
    SYSTEM_MAP_SUMMARY,
    authority_graph_summary,
    render_system_map_markdown,
)
from app.operator_intelligence.watchdog import AlertQueue, build_watchdog_alerts


__all__ = [
    "DecisionExplainer",
    "AlertQueue",
    "RunArchive",
    "RunReportGenerator",
    "SYSTEM_MAP_SUMMARY",
    "authority_graph_summary",
    "build_action_center",
    "build_pnl_summary",
    "build_run_record",
    "build_tca_dashboard",
    "build_watchdog_alerts",
    "render_system_map_markdown",
]
