"""Persistent run report generation from archive records."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REPORT_VERSION = "operator-run-report-v2"


def _line(value: Any) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value) or "none"
    return str(value)


def _field(row: dict[str, Any], key: str, default: Any = "unknown") -> Any:
    return row.get(key, default) if isinstance(row, dict) else default


def _kv_lines(row: dict[str, Any], keys: list[str]) -> list[str]:
    return [f"- {key}: {_line(_field(row, key))}" for key in keys]


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
        runtime_new = run.get("runtime_new_activity") or {}
        historical = run.get("historical_broker_local_activity") or {}
        baseline = run.get("baseline_positions") or {}
        methods = run.get("broker_method_counts") or {}
        controls = run.get("shutdown_controls") or {}
        open_orders = run.get("shutdown_open_orders") or {}
        fee_tca = run.get("fee_tca") or {}
        latency = run.get("market_data_latency") or {}
        per_symbol = run.get("per_symbol_decisions") or {}
        readiness_72h = run.get("readiness_72h") or {}
        artifacts = run.get("artifact_paths") or {}
        symbol_lines = []
        for symbol, summary in sorted((per_symbol.get("symbols") or {}).items()):
            symbol_lines.append(
                "- "
                f"{symbol}: attempts={_line(summary.get('decision_attempts'))}, "
                f"submitted={_line(summary.get('submitted_count'))}, "
                f"outputs={_line(summary.get('outputs'))}, "
                f"no_submit={_line(summary.get('no_submit_reasons'))}"
            )
        if not symbol_lines:
            symbol_lines = ["- No per-symbol decision compile attempts observed in scanned log excerpt."]
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
                "## Runtime-New Orders / Fills / Cancels",
                *_kv_lines(
                    runtime_new,
                    [
                        "order_post_attempted",
                        "order_post_authorized",
                        "order_post_acknowledged",
                        "submitted_count",
                        "cancel_attempted",
                        "cancel_authorized",
                        "cancel_acknowledged",
                        "fill_hydration_attempted_count",
                        "fill_hydration_count",
                        "source",
                    ],
                ),
                f"- Compatibility submitted/ack/canceled: {_line(orders.get('submitted'))}/{_line(orders.get('acknowledged'))}/{_line(orders.get('canceled'))}",
                "",
                "## Historical Broker / Local Orders / Fills",
                *_kv_lines(
                    historical,
                    [
                        "terminal_orders",
                        "filled_orders",
                        "canceled_orders",
                        "broker_filled_orders",
                        "broker_partially_filled_orders",
                        "broker_canceled_with_fill_count",
                        "local_fills",
                        "legacy_local_fills",
                        "local_order_id_mappings",
                        "source",
                    ],
                ),
                "",
                "## Baseline Positions",
                *_kv_lines(
                    baseline,
                    [
                        "positions_count",
                        "last_broker_positions_count",
                        "protected_baseline_context_observed",
                        "protected_symbols_count",
                        "broker_positions_preserved",
                        "source",
                    ],
                ),
                "",
                "## Broker Method Counts",
                *_kv_lines(methods, ["GET", "POST", "DELETE", "preflight_GET", "preflight_POST", "preflight_DELETE", "shutdown_GET", "shutdown_POST", "shutdown_DELETE"]),
                "",
                "## Shutdown Controls",
                *_kv_lines(
                    controls,
                    [
                        "broker_flatten_called",
                        "broker_positions_preserved",
                        "mutation_performed",
                        "cancel_attempted",
                        "cancel_authorized",
                        "cancel_acknowledged",
                        "close_attempted",
                        "liquidation_attempted",
                        "source",
                    ],
                ),
                "",
                "## Open Orders At Shutdown",
                *_kv_lines(
                    open_orders,
                    [
                        "open_orders_count",
                        "last_broker_open_orders_count",
                        "local_open_orders_before_final_reconcile",
                        "broker_confirmed_open_orders",
                        "local_open_orders_after_final_reconcile",
                        "source",
                    ],
                ),
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
                *_kv_lines(
                    fee_tca,
                    [
                        "status",
                        "fee_hydration_skipped",
                        "fee_hydration_skip_reason",
                        "account_activity_read_authorized",
                        "broker_read_profile",
                        "tca_records_count",
                        "tca_complete_count",
                        "tca_estimated_count",
                        "tca_fee_pending_count",
                        "tca_unknown_count",
                        "realized_vs_modeled_netedge_available_count",
                        "realized_vs_modeled_netedge_unknown_count",
                        "source",
                    ],
                ),
                "",
                "## Market Data Latency",
                *_kv_lines(latency, ["status", "warning_count_in_scanned_excerpt", "max_latency_ms", "latest_latency_ms", "threshold_ms", "source"]),
                "",
                "## Per-Symbol Decision Summary",
                f"- Status: {_line(per_symbol.get('status'))}",
                f"- Total attempts in scanned excerpt: {_line(per_symbol.get('total_decision_attempts_in_scanned_excerpt'))}",
                *symbol_lines,
                "",
                "## Artifact Paths",
                *_kv_lines(artifacts, ["wrapper_stdout", "wrapper_stderr", "child_stdout", "child_stderr", "report", "json_report"]),
                "",
                "## 72-Hour Readiness Recommendation",
                f"- Recommendation: {_line(readiness_72h.get('recommendation'))}",
                f"- Blockers: {_line(readiness_72h.get('blockers'))}",
                f"- Warnings: {_line(readiness_72h.get('warnings'))}",
                f"- Next safe action: {_line(readiness_72h.get('next_safe_action'))}",
                f"- Live trading authorized: {_line(readiness_72h.get('live_trading_authorized'))}",
                f"- Real money authorized: {_line(readiness_72h.get('real_money_authorized'))}",
                f"- Manual controls authorized: {_line(readiness_72h.get('manual_controls_authorized'))}",
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
