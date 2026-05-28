"""Persistent run report generation from archive records."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REPORT_VERSION = "operator-run-report-v1"


def _line(value: Any) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value) or "none"
    return str(value)


class RunReportGenerator:
    def __init__(self, *, report_dir: Path) -> None:
        self.report_dir = Path(report_dir)

    def markdown(self, run: dict[str, Any]) -> str:
        reason_codes = run.get("reason_codes") or ()
        safety = run.get("safety_markers") or {}
        fills = run.get("fills") or {}
        orders = run.get("orders") or {}
        tca = run.get("tca") or {}
        oms = run.get("oms_shutdown_accounting") or {}
        return "\n".join(
            [
                f"# Operator Run Report: {_line(run.get('run_id'))}",
                "",
                "## Runtime Completion",
                f"- Status: {_line(run.get('status'))}",
                f"- Exit code: {_line(run.get('exit_code'))}",
                f"- Started: {_line(run.get('start_time'))}",
                f"- Ended: {_line(run.get('end_time'))}",
                f"- Duration seconds: {_line(run.get('duration_seconds'))}",
                f"- Profile: {_line(run.get('profile'))}",
                f"- Watchlist: {_line(run.get('watchlist'))}",
                "",
                "## Paper Safety",
                f"- Live marker: {_line(safety.get('live_marker'))}",
                f"- Real-money marker: {_line(safety.get('real_money_marker'))}",
                f"- Unauthorized mutation marker: {_line(safety.get('unauthorized_mutation_marker'))}",
                f"- Naked SELL marker: {_line(safety.get('naked_sell_marker'))}",
                "",
                "## Decisions / Orders",
                f"- Orders submitted: {_line(orders.get('submitted'))}",
                f"- Orders acknowledged: {_line(orders.get('acknowledged'))}",
                f"- Orders canceled: {_line(orders.get('canceled'))}",
                "",
                "## OMS Reconciliation",
                f"- OMS shutdown accounting: {_line(oms.get('status'))}",
                f"- Conflict observed: {_line((run.get('log_evidence') or {}).get('reconciliation_conflict_observed'))}",
                "",
                "## Fills / TCA / Fees",
                f"- Fills observed: {_line(fills.get('observed'))}",
                f"- Fill hydration observed: {_line(fills.get('fill_hydration_observed'))}",
                f"- Broker fee hydration observed: {_line(fills.get('broker_fee_hydration_observed'))}",
                f"- TCA status: {_line(tca.get('status'))}",
                "",
                "## World Awareness",
                "- Advisory-only summary is available from `/operator/world-awareness`; no feed has trade authority.",
                "",
                "## Alerts / Watchdog",
                "- Watchdog alerts are derived from archive, readiness, runtime, storage, and safety markers.",
                "",
                "## Final Plain-English Summary",
                f"- Verdict: {_line(run.get('final_verdict'))}",
                f"- Reason codes: {_line(reason_codes)}",
                "- Missing evidence remains unknown; this report does not invent broker, fee, fill, P&L, or TCA truth.",
                "",
            ]
        )

    def generate(self, run: dict[str, Any], *, write_files: bool = True) -> dict[str, Any]:
        run_id = str(run.get("run_id") or "unknown_run")
        markdown = self.markdown(run)
        payload = {
            "report_version": REPORT_VERSION,
            "run_id": run_id,
            "run": run,
            "markdown": markdown,
            "logs_mutated": False,
            "secrets_values_exposed": False,
        }
        if not write_files:
            return payload
        self.report_dir.mkdir(parents=True, exist_ok=True)
        md_path = self.report_dir / f"{run_id}.md"
        json_path = self.report_dir / f"{run_id}.json"
        md_path.write_text(markdown, encoding="utf-8", newline="\n")
        json_path.write_text(
            json.dumps(payload, sort_keys=True, indent=2, default=str),
            encoding="utf-8",
            newline="\n",
        )
        payload["report_path"] = str(md_path)
        payload["json_report_path"] = str(json_path)
        return payload
