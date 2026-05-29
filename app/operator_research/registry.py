"""In-memory advisory research registry for operator research OS v1."""

from __future__ import annotations

from typing import Any

from app.operator_research.models import (
    PromotionGate,
    ResearchExperiment,
    ResearchHypothesis,
    ResearchRecommendation,
    research_id,
    utc_now_iso,
)


def default_promotion_gates() -> list[PromotionGate]:
    return [
        PromotionGate(
            gate_id="idea_to_offline_research",
            stage="IDEA",
            required_evidence=[
                "clear thesis",
                "falsifiable invalidation condition",
                "known data requirements",
            ],
            current_status="NEEDS_REVIEW",
        ),
        PromotionGate(
            gate_id="offline_to_backtest_review",
            stage="OFFLINE_RESEARCH",
            required_evidence=[
                "clean dataset provenance",
                "no lookahead/leakage proof",
                "cost/slippage assumptions labeled",
            ],
            current_status="NEEDS_REVIEW",
        ),
        PromotionGate(
            gate_id="backtest_to_replay_review",
            stage="BACKTEST_REVIEW",
            required_evidence=[
                "walk-forward/out-of-sample review",
                "parameter fragility review",
                "overfit risk review",
            ],
            current_status="NEEDS_REVIEW",
        ),
        PromotionGate(
            gate_id="replay_to_bounded_paper",
            stage="REPLAY_REVIEW",
            required_evidence=[
                "DecisionFrame evidence",
                "MarketTruthSnapshot freshness",
                "NetEdge/TCA/fee evidence",
                "OMS/fill reconciliation",
            ],
            current_status="NEEDS_REVIEW",
        ),
        PromotionGate(
            gate_id="paper_to_longer_paper",
            stage="BOUNDED_PAPER",
            required_evidence=[
                "flight recorder PASS or conditional reason codes",
                "broker-confirmed fills/orders where claimed",
                "no fake P&L/TCA/fees",
            ],
            current_status="NEEDS_REVIEW",
        ),
        PromotionGate(
            gate_id="any_live_transition",
            stage="LIVE_REQUIRES_SEPARATE_APPROVAL",
            required_evidence=[
                "separate live governance packet",
                "real-money authority approval",
                "broker/risk/OMS/live readiness audit",
            ],
            current_status="BLOCKED",
            blocks_promotion=True,
            live_requires_separate_approval=True,
        ),
    ]


class ResearchRegistry:
    """Small advisory registry.

    The default registry is process-local. It deliberately avoids repository
    state files in this seam.
    """

    def __init__(self) -> None:
        self._hypotheses: dict[str, ResearchHypothesis] = {}
        self._experiments: dict[str, ResearchExperiment] = {}
        self._recommendations: dict[str, ResearchRecommendation] = {}
        self._seed()

    def _seed(self) -> None:
        rec = ResearchRecommendation(
            id=research_id("research_rec"),
            title="Review latest run evidence before expanding PAPER experiments",
            summary="Use run archive, DecisionFrame, NetEdge, fee/TCA, OMS, and watchdog evidence before proposing the next bounded PAPER experiment.",
            evidence=["operator_run_archive", "decision_explainer", "pnl_tca_dashboard", "watchdog_alerts"],
            risks=["Overfit risk remains unknown until offline/replay validation exists.", "Broker fee detail may be unavailable."],
            status="NEEDS_REVIEW",
            promotion_stage="IDEA",
        )
        self._recommendations[rec.id] = rec

    def create_hypothesis(self, payload: dict[str, Any]) -> dict[str, Any]:
        hypothesis = ResearchHypothesis.from_payload(payload or {})
        self._hypotheses[hypothesis.id] = hypothesis
        return {
            "source": "OPERATOR_RESEARCH_REGISTRY",
            "status": hypothesis.status,
            "hypothesis": hypothesis.to_dict(),
            "can_execute": False,
            "broker_call_occurred": False,
            "trading_mutation_occurred": False,
            "paper_started": False,
            "created_at": utc_now_iso(),
        }

    def create_experiment(self, payload: dict[str, Any]) -> dict[str, Any]:
        experiment = ResearchExperiment.from_payload(payload or {})
        self._experiments[experiment.id] = experiment
        return {
            "source": "OPERATOR_RESEARCH_REGISTRY",
            "status": experiment.status,
            "experiment": experiment.to_dict(),
            "can_execute": False,
            "requires_shan_approval": True,
            "broker_call_occurred": False,
            "trading_mutation_occurred": False,
            "paper_started": False,
            "reason_code": "RESEARCH_ONLY_NO_RUNTIME_STARTED",
            "created_at": utc_now_iso(),
        }

    def snapshot(self) -> dict[str, Any]:
        hypotheses = [item.to_dict() for item in self._hypotheses.values()]
        experiments = [item.to_dict() for item in self._experiments.values()]
        recommendations = [item.to_dict() for item in self._recommendations.values()]
        gates = [gate.to_dict() for gate in default_promotion_gates()]
        return {
            "source": "OPERATOR_RESEARCH_REGISTRY",
            "registry_version": "operator-research-registry-v1",
            "hypotheses": hypotheses,
            "experiments": experiments,
            "promotion_gates": gates,
            "recommendations": recommendations,
            "counts": {
                "hypotheses": len(hypotheses),
                "experiments": len(experiments),
                "recommendations": len(recommendations),
                "promotion_gates": len(gates),
            },
            "advisory_only": True,
            "can_execute": False,
            "requires_shan_approval_for_paper": True,
            "paper_started": False,
            "broker_call_occurred": False,
            "trading_mutation_occurred": False,
            "live_enabled": False,
            "real_money_enabled": False,
            "secrets_values_exposed": False,
            "raw_logs_included": False,
        }
