from __future__ import annotations

import inspect

from app.operator_research.evidence_graph import build_evidence_graph
from app.operator_research.registry import ResearchRegistry


def test_research_hypotheses_are_advisory_only():
    registry = ResearchRegistry()

    result = registry.create_hypothesis(
        {
            "title": "Fee-aware crypto momentum",
            "thesis": "Momentum only has edge when fees and spread remain below modeled edge.",
            "symbols": ["BTC/USD"],
            "strategy_area": "momentum",
        }
    )

    assert result["hypothesis"]["can_execute"] is False
    assert result["hypothesis"]["requires_shan_approval"] is True
    assert result["broker_call_occurred"] is False
    assert result["trading_mutation_occurred"] is False


def test_research_experiment_does_not_start_paper():
    registry = ResearchRegistry()

    result = registry.create_experiment(
        {
            "title": "Bounded PAPER fee/TCA review",
            "thesis": "Review if fees/slippage dominate modeled NetEdge.",
            "promotion_stage": "BOUNDED_PAPER",
            "paper_duration_seconds": 300,
        }
    )

    assert result["experiment"]["can_execute"] is False
    assert result["experiment"]["requires_shan_approval"] is True
    assert result["paper_started"] is False
    assert result["broker_call_occurred"] is False
    assert result["trading_mutation_occurred"] is False


def test_evidence_graph_excludes_raw_logs_and_secrets():
    graph = build_evidence_graph(
        run_archive={
            "runs": [
                {
                    "run_id": "paper_x",
                    "final_verdict": "CONDITIONAL_PASS",
                    "report_path": "state/operator/reports/paper_x.md",
                    "reason_codes": ["BROKER_FEE_DETAIL_PENDING"],
                }
            ]
        },
        decision_explainer={"headline": "BUY blocked by missing fee detail", "frame_id": "df_1"},
        market_truth={"summary": "PASS"},
        netedge={"net_edge": "UNKNOWN"},
        pnl={"realized_pnl": {"broker_confirmed": False}},
        orders={"broker_truth_canonical": True, "reconciliation_conflicts": 0},
        fills={"local_fills": 1, "fee_status": "FEE_PENDING_BROKER_ACTIVITY"},
        tca={"status": "UNKNOWN"},
        oms={"status": "OBSERVED"},
        action_center={"counts": {"BLOCKER": 0}},
        watchdog={"alert_count": 0},
        provider_readiness={"provider_count": 2, "counts": {"MISSING_CREDENTIALS": 1}},
    )
    text = str(graph)

    assert graph["raw_logs_included"] is False
    assert graph["secrets_values_exposed"] is False
    assert "state/operator/reports/paper_x.md" in text
    assert "raw log" not in text.lower()
    assert "PROVIDER_CREDENTIALS_MISSING" in graph["missing_evidence"]
    assert graph["can_execute"] is False


def test_operator_research_modules_do_not_import_execution_or_broker():
    from app.operator_research import evidence_graph, registry

    source = inspect.getsource(evidence_graph) + inspect.getsource(registry)

    assert "from app.execution" not in source
    assert "import app.execution" not in source
    assert "from app.broker" not in source
    assert "import app.broker" not in source
