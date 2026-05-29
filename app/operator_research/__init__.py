"""Operator research OS foundation.

This package stores advisory research objects and evidence summaries only. It
does not start runs, mutate strategies, call brokers, or change thresholds.
"""

from app.operator_research.evidence_graph import build_evidence_graph
from app.operator_research.registry import ResearchRegistry, default_promotion_gates

__all__ = ["ResearchRegistry", "build_evidence_graph", "default_promotion_gates"]
