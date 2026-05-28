from __future__ import annotations

from pathlib import Path

from app.api.operator_session_store import OperatorSessionStore
from app.operator_intelligence.action_center import build_action_center
from app.operator_intelligence.archive import RunArchive
from app.operator_intelligence.decision_explainer import DecisionExplainer
from app.operator_intelligence.pnl_tca import build_pnl_summary, build_tca_dashboard
from app.operator_intelligence.reports import RunReportGenerator
from app.operator_intelligence.system_map import render_system_map_markdown
from app.operator_intelligence.watchdog import build_watchdog_alerts


def _session(
    tmp_path: Path,
    log_text: str,
    *,
    exit_code: int | None = 0,
    duration_seconds: int = 300,
    started_at: str = "2026-05-27T12:00:01+00:00",
    ended_at: str = "2026-05-27T12:05:01+00:00",
) -> dict:
    log_path = tmp_path / "logs" / "operator_runs" / "paper.out.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(log_text, encoding="utf-8")
    return {
        "session_id": "paper_fixture",
        "requested_at": "2026-05-27T12:00:00+00:00",
        "started_at": started_at,
        "ended_at": ended_at,
        "status": "EXITED",
        "profile": "PAPER_EXPLORATION_ALPHA",
        "watchlist": ["BTC/USD", "ETH/USD", "SOL/USD"],
        "duration_seconds": duration_seconds,
        "exit_code": exit_code,
        "wrapper_stdout_path": str(log_path),
    }


def test_run_archive_parses_session_and_log_evidence(tmp_path):
    store = OperatorSessionStore(path=tmp_path / "state" / "operator" / "sessions.jsonl")
    store.write_session(
        _session(
            tmp_path,
            "\n".join(
                [
                    "ORDER_SUBMITTED",
                    "ORDER_ACKNOWLEDGED",
                    "CANCEL_ACKNOWLEDGED",
                    "FILL_LEDGER_HYDRATION",
                    "BROKER_FEE_HYDRATION",
                    "TCA",
                    "SHUTDOWN_RECONCILIATION",
                ]
            ),
        )
    )

    archive = RunArchive(session_store=store, repo_root=tmp_path).list_runs()

    run = archive["runs"][0]
    assert archive["stores_log_contents"] is False
    assert run["run_id"] == "paper_fixture"
    assert run["orders"]["submitted"] == 1
    assert run["fills"]["fill_hydration_observed"] is True
    assert run["fills"]["broker_fee_hydration_observed"] is True
    assert run["tca"]["status"] == "OBSERVED"
    assert run["oms_shutdown_accounting"]["status"] == "OBSERVED"
    assert run["final_verdict"] == "PASS"


def test_run_archive_does_not_flag_live_policy_and_refusal_text_as_live_marker(tmp_path):
    session = _session(
        tmp_path,
        "\n".join(
            [
                "live_endpoint_used=false",
                "live_endpoint_touched=false",
                "LIVE_LOCKED",
                "LIVE_NOT_APPROVED",
                "policy text mentioning live endpoint is not evidence",
                "real_money_touched=false",
                "ORDER_SUBMITTED",
                "BROKER_FEE_HYDRATION",
                "TCA",
                "SHUTDOWN_RECONCILIATION",
            ]
        ),
    )

    run = RunArchive(sessions=[session], repo_root=tmp_path).list_runs()["runs"][0]

    assert run["safety_markers"]["live_marker"] is False
    assert run["safety_markers"]["real_money_marker"] is False
    assert "LIVE_MARKER" not in run["reason_codes"]
    assert run["final_verdict"] == "PASS"


def test_run_archive_flags_only_explicit_true_live_or_real_money_evidence(tmp_path):
    live_session = _session(
        tmp_path,
        "\n".join(
            [
                "live_endpoint_used=true",
                "BROKER_FEE_HYDRATION",
                "TCA",
                "SHUTDOWN_RECONCILIATION",
            ]
        ),
    )

    run = RunArchive(sessions=[live_session], repo_root=tmp_path).list_runs()["runs"][0]

    assert run["safety_markers"]["live_marker"] is True
    assert "LIVE_MARKER" in run["reason_codes"]
    assert run["final_verdict"] == "FAIL"

    real_money_path = tmp_path / "logs" / "operator_runs" / "real_money.out.log"
    real_money_path.write_text(
        "real_money_touched=true\nBROKER_FEE_HYDRATION\nTCA\nSHUTDOWN_RECONCILIATION\n",
        encoding="utf-8",
    )
    real_money_session = dict(live_session, session_id="paper_real_money", wrapper_stdout_path=str(real_money_path))
    real_money_run = RunArchive(sessions=[real_money_session], repo_root=tmp_path).list_runs()["runs"][0]

    assert real_money_run["safety_markers"]["live_marker"] is True
    assert real_money_run["safety_markers"]["real_money_marker"] is True
    assert "LIVE_MARKER" in real_money_run["reason_codes"]
    assert "REAL_MONEY_MARKER" in real_money_run["reason_codes"]


def test_broker_fee_hydration_conflict_is_conditional_not_reconciliation_failure(tmp_path):
    session = _session(
        tmp_path,
        "\n".join(
            [
                "broker_fee_hydration_conflict_count=1",
                "BROKER_FEE_HYDRATION",
                "TCA",
                "SHUTDOWN_RECONCILIATION",
            ]
        ),
    )

    run = RunArchive(sessions=[session], repo_root=tmp_path).list_runs()["runs"][0]

    assert run["log_evidence"]["broker_fee_hydration_conflict_observed"] is True
    assert run["log_evidence"]["reconciliation_conflict_observed"] is False
    assert "BROKER_FEE_HYDRATION_CONFLICT" in run["reason_codes"]
    assert "RECONCILIATION_OR_LEDGER_CONFLICT" not in run["reason_codes"]
    assert run["final_verdict"] == "CONDITIONAL_PASS"


def test_explicit_reconciliation_conflict_still_fails_run_archive(tmp_path):
    session = _session(
        tmp_path,
        "\n".join(
            [
                "reconciliation_conflict_count=1",
                "BROKER_FEE_HYDRATION",
                "TCA",
                "SHUTDOWN_RECONCILIATION",
            ]
        ),
    )

    run = RunArchive(sessions=[session], repo_root=tmp_path).list_runs()["runs"][0]

    assert run["log_evidence"]["reconciliation_conflict_observed"] is True
    assert "RECONCILIATION_OR_LEDGER_CONFLICT" in run["reason_codes"]
    assert run["final_verdict"] == "FAIL"


def test_run_archive_splits_requested_duration_from_observed_wall_clock(tmp_path):
    session = _session(
        tmp_path,
        "BROKER_FEE_HYDRATION\nTCA\nSHUTDOWN_RECONCILIATION\n",
        duration_seconds=300,
        started_at="2026-05-27T12:00:00+00:00",
        ended_at="2026-05-27T12:09:24+00:00",
    )

    run = RunArchive(sessions=[session], repo_root=tmp_path).list_runs()["runs"][0]

    assert run["duration_seconds"] == 300
    assert run["requested_duration_seconds"] == 300
    assert run["observed_wall_clock_seconds"] == 564
    assert run["archive_updated_at"]


def test_report_generator_writes_markdown_and_json_without_mutating_logs(tmp_path):
    log_text = "ORDER_SUBMITTED\nSHUTDOWN_RECONCILIATION\nFEE_PENDING_BROKER_ACTIVITY\n"
    session = _session(tmp_path, log_text)
    archive = RunArchive(sessions=[session], repo_root=tmp_path).list_runs()
    log_path = Path(session["wrapper_stdout_path"])
    before = log_path.read_text(encoding="utf-8")

    report = RunReportGenerator(report_dir=tmp_path / "reports").generate(archive["runs"][0])

    assert Path(report["report_path"]).exists()
    assert Path(report["json_report_path"]).exists()
    assert "Final Plain-English Summary" in report["markdown"]
    assert log_path.read_text(encoding="utf-8") == before
    assert report["logs_mutated"] is False


def test_decision_explainer_handles_no_runtime_and_fixture_frame():
    empty = DecisionExplainer().explain_latest()
    assert empty["source"] == "NO_ACTIVE_RUNTIME_ATTACHED"
    assert "NO_DECISIONFRAME_EVIDENCE" in empty["blockers"]

    frame = {
        "frame_id": "df_fixture",
        "symbol": "BTC/USD",
        "frame_output": "NO_TRADE",
        "frame_status": "BLOCK",
        "module_evidence": {
            "MarketTruthSnapshot": {
                "module_name": "MarketTruthSnapshot",
                "authority_class": "MARKET_TRUTH",
                "status": "MISSING_TRUTH",
                "signal": "NONE",
                "reason_codes": ["SNAPSHOT_STALE"],
            },
            "NetEdgeGovernor": {
                "module_name": "NetEdgeGovernor",
                "authority_class": "RISK",
                "status": "CONTRIBUTED",
                "signal": "NO_ACTION",
                "reason_codes": ["NET_EDGE_UNKNOWN"],
            },
        },
    }
    explained = DecisionExplainer([frame]).explain_latest()
    assert explained["frame_id"] == "df_fixture"
    assert explained["output"] == "NO_TRADE"
    assert explained["scoring_changed"] is False
    assert explained["missing_truth"] == ("MarketTruthSnapshot",)


def test_action_center_aggregates_readiness_storage_fee_world_and_ai_items():
    center = build_action_center(
        status={"supervisor": {"active_session": None}},
        readiness={
            "missing_prerequisites": ["SESSION_STORE_NOT_READY"],
            "cloud_missing_prerequisites": ["CLOUD_SECRET_MANAGER_NOT_CONFIGURED"],
        },
        health={},
        storage={
            "session_store": {"status": "DEGRADED"},
            "operator_state_dir": {"status": "READY"},
            "log_dir": {"status": "MISSING_PARENT", "path": "logs"},
        },
        fills={"fee_status": "FEE_PENDING_BROKER_ACTIVITY", "broker_fee_hydration_pending_count": 1},
        world_runtime={"manual_poll_only": True},
        archive={"run_count": 0},
        alerts=[],
        ai_recommendations=[{"recommendation_id": "ai_1", "status": "PENDING_REVIEW", "summary": "review"}],
    )

    assert center["safe_mutation_flags"]["can_execute"] is False
    assert center["counts"]["BLOCKER"] >= 2
    assert center["counts"]["WARNING"] >= 2
    assert center["counts"]["NEEDS_APPROVAL"] == 1


def test_pnl_tca_summary_does_not_fake_missing_broker_values():
    fills = {
        "local_fills": 1,
        "broker_fee_hydration_pending_count": 1,
        "broker_fee_hydration_count": 0,
        "broker_fee_hydration_conflict_count": 0,
        "fee_source": "UNAVAILABLE",
    }
    tca = {
        "tca_records_count": 0,
        "tca_unknown_count": 0,
        "tca_fee_pending_count": 1,
        "realized_vs_modeled_netedge_available_count": 0,
    }

    pnl = build_pnl_summary(fills_summary=fills, tca_summary=tca)
    dashboard = build_tca_dashboard(fills_summary=fills, tca_summary=tca)

    assert pnl["realized_pnl"]["truth_label"] == "unknown"
    assert pnl["realized_pnl"]["value"] is None
    assert pnl["fake_pnl_allowed"] is False
    assert dashboard["status"] == "PENDING_FEE_DETAIL"
    assert dashboard["fake_tca_allowed"] is False


def test_watchdog_creates_alerts_for_fixture_safety_issues():
    alerts = build_watchdog_alerts(
        status={"supervisor": {"active_session": None}},
        runtime={"process_state": "FAILED", "exit_code": 2},
        health={"live_status": "LIVE_LOCKED", "real_money_status": "BLOCKED"},
        readiness={"cloud_missing_prerequisites": ["HOSTED_PROCESS_SUPERVISOR_NOT_DEPLOYED"]},
        storage={"session_store": {"status": "READY"}, "world_awareness_cache": {"status": "READY"}},
        orders={"reconciliation_conflicts": 1},
        fills={"fill_hydration_conflict_count": 1, "broker_fee_hydration_conflict_count": 1},
        tca={},
        world_runtime={"manual_poll_only": True, "provider_polling_active": False},
        archive={"runs": [{"run_id": "paper_bad", "final_verdict": "FAIL", "reason_codes": ["LIVE_MARKER"], "safety_markers": {"live_marker": True}}]},
    )

    ids = {alert["alert_id"] for alert in alerts}
    assert "session_nonzero_exit" in ids
    assert "oms_conflict" in ids
    assert "fee_conflict" in ids
    assert any(alert["severity"] == "SAFETY_CRITICAL" for alert in alerts)


def test_system_map_report_text_exists_and_names_ai_chief():
    markdown = render_system_map_markdown()

    assert "AI Chief Operator" in markdown
    assert "MarketTruthSnapshot" in markdown
    assert "Must Not Touch" in markdown
