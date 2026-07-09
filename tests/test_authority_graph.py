from __future__ import annotations

from collections import Counter
from pathlib import Path

from app.api.operator_readonly_api import OperatorSnapshotProvider, create_operator_app
from app.api.operator_runtime_config import OperatorRuntimeConfig
from app.core.authority_graph import (
    EXPECTED_PHASE_B_CONFLICT_IDS,
    ORDERED_AUTHORITIES,
    assert_authority_graph_integrity,
    authority_graph_summary,
    owner_for,
)


EXPECTED_OWNERS = {
    "market_truth": "app.core.market_snapshot.MarketTruthSnapshot",
    "risk_gates": "app.risk.pre_trade_guardrails.evaluate_pre_trade_guardrails",
    "sizing": "app.risk.position_sizing.PositionSizingEngine",
    "broker_order_lifecycle": "app.execution.order_router.OrderRouter",
    "portfolio_position_truth": "app.risk.exposure_manager.ExposureManager",
    "ai_advisory": "app.ai_chief_operator.provider_gateway.AIProviderGateway",
    "ui_display": "ui/operator-control-panel/app.js",
}

PRE_FLAGGED_RUNTIME_MODULES = {
    "app.api.operator_readonly_api",
    "app.execution.order_router",
    "app.main_loop",
    "app.strategies.moving_floor",
    "app.world_awareness.config",
}


def _endpoint(app, path: str, method: str = "GET"):
    for route in app.routes:
        if route.path == path and method in (route.methods or set()):
            return route.endpoint
    raise AssertionError(f"route not found: {method} {path}")


def _truth_map_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    path = Path("reports/completion/PHASE_B_MODULE_TRUTH_MAP.md")
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| ") or line.startswith("| ---") or "| # | name | path |" in line:
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 17:
            continue
        try:
            int(parts[1])
        except ValueError:
            continue
        rows.append(
            {
                "name": parts[2],
                "path": parts[3],
                "runtime_status": parts[6],
                "classification": parts[7],
                "blockers": parts[14] if len(parts) > 14 else "",
            }
        )
    return rows


def test_authority_graph_names_exactly_one_owner_for_each_authority():
    assert_authority_graph_integrity()
    summary = authority_graph_summary()

    assert summary["integrity"]["ok"] is True
    assert summary["authority_count"] == 7
    assert tuple(entry["authority"] for entry in summary["authorities"]) == ORDERED_AUTHORITIES
    assert {authority: owner_for(authority).module for authority in ORDERED_AUTHORITIES} == EXPECTED_OWNERS
    assert len({entry["owner"]["module"] for entry in summary["authorities"]}) == 7


def test_authority_graph_contributors_cannot_override_owner():
    summary = authority_graph_summary()

    for entry in summary["authorities"]:
        assert entry["owner"]["final_decision_owner"] is True
        assert entry["contributors"], entry["authority"]
        for contributor in entry["contributors"]:
            assert contributor["can_override_owner"] is False
            if contributor["status"] in {"BLOCKED", "REJECTED_PRESERVED", "PRESERVED_DEAD"}:
                assert contributor["blocked_reason"]
            else:
                assert contributor["status"] == "WIRED"
                assert contributor["blocked_reason"] is None


def test_authority_graph_resolves_all_phase_b_conflicts_without_extra_authorities():
    summary = authority_graph_summary()
    conflict_ids: set[int] = set()
    modules_by_status: dict[str, set[str]] = {}

    for entry in summary["authorities"]:
        conflict_ids.update(entry["owner"]["phase_b_conflict_ids"])
        for contributor in entry["contributors"]:
            conflict_ids.update(contributor["phase_b_conflict_ids"])
            modules_by_status.setdefault(contributor["status"], set()).add(contributor["module"])

    for item in summary["non_authority_conflict_resolutions"]:
        conflict_ids.add(item["conflict_id"])
        modules_by_status.setdefault(item["status"], set()).add(item["reference_module"])

    assert conflict_ids == EXPECTED_PHASE_B_CONFLICT_IDS
    assert "app.execution.orchestrator" in modules_by_status["REJECTED_PRESERVED"]
    assert "app.models.py_tombstone" in modules_by_status["PRESERVED_DEAD"]


def test_operator_system_map_exposes_read_only_authority_graph(tmp_path):
    app = create_operator_app(
        provider=OperatorSnapshotProvider(
            runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path)
        )
    )

    payload = _endpoint(app, "/operator/system-map")()

    assert payload["authority_graph"]["source"] == "AUTHORITY_GRAPH"
    assert payload["authority_graph"]["integrity"]["ok"] is True
    assert payload["authority_graph"]["broker_mutation_occurred"] is False
    assert payload["authority_graph"]["trading_mutation_occurred"] is False
    assert payload["authority_graph"]["live_enabled"] is False
    assert payload["authority_graph"]["real_money_enabled"] is False
    assert payload["secrets_values_exposed"] is False
    assert "Authority Graph" in payload["markdown"]


def test_phase_b_map_corrections_are_applied_without_counting_pycache_rows():
    rows = _truth_map_rows()
    countable = [
        row for row in rows if "__pycache__" not in row["name"] and "__pycache__" not in row["path"]
    ]
    classifications = Counter(row["classification"] for row in countable)
    by_name = {row["name"]: row for row in rows}

    assert len(countable) == 397
    assert classifications == {
        "WIRED": 297,
        "BLOCKED": 89,
        "PRESERVED-DEAD": 10,
        "REJECTED-PRESERVED": 1,
    }
    for module in PRE_FLAGGED_RUNTIME_MODULES:
        assert by_name[module]["classification"] == "WIRED"
        assert "Phase C runtime/import verified" in by_name[module]["blockers"]
