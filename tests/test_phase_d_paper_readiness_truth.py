from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path

from app.execution.alpaca_paper_adapter import AlpacaPaperBrokerAdapter
from app.execution.paper_broker import PaperBroker
from app.risk.pre_trade_guardrails import (
    DORMANT_BY_POLICY,
    PreTradeGuardrailRequest,
    evaluate_pre_trade_guardrails,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _active_runtime_files() -> list[Path]:
    roots = [REPO_ROOT / "app", REPO_ROOT / "scripts"]
    files = [REPO_ROOT / "main.py"]
    for root in roots:
        files.extend(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)
    return sorted(path for path in files if path.exists())


def _repo_path(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def test_d0_active_broker_submit_path_is_order_router_only() -> None:
    """Phase D D0: no active runtime submit path may bypass OrderRouter."""

    allowed_outside_router = {
        ("app/execution/engine.py", "self.order_router.submit_order(order)"),
    }
    bypasses: list[str] = []

    for path in _active_runtime_files():
        repo_path = _repo_path(path)
        if repo_path in {
            "app/execution/order_router.py",
            "app/execution/orchestrator.py",
        }:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "submit_order":
                continue
            call_source = ast.unparse(node)
            if (repo_path, call_source) not in allowed_outside_router:
                bypasses.append(f"{repo_path}:{node.lineno}:{call_source}")

    assert bypasses == []


def test_d0_rejected_orchestrator_is_not_imported_by_active_runtime() -> None:
    rejected_imports: list[str] = []
    forbidden_patterns = (
        "app.execution.orchestrator",
        "from app.execution import orchestrator",
        "PaperTradingOrchestrator",
        "MasterOrchestrator",
    )

    for path in _active_runtime_files():
        repo_path = _repo_path(path)
        if repo_path in {
            "app/core/authority_graph.py",
            "app/execution/orchestrator.py",
        }:
            continue
        text = path.read_text(encoding="utf-8-sig")
        for pattern in forbidden_patterns:
            if pattern in text:
                rejected_imports.append(f"{repo_path}:{pattern}")

    assert rejected_imports == []


def test_d0_lower_layer_broker_methods_are_preserved_not_authorities() -> None:
    assert callable(getattr(PaperBroker, "submit_order"))
    assert callable(getattr(AlpacaPaperBrokerAdapter, "submit_order"))


def test_d1_guard_liveness_is_real_blocker_not_static_false_positive() -> None:
    verdict = evaluate_pre_trade_guardrails(
        PreTradeGuardrailRequest(
            symbol="BTC/USD",
            side="buy",
            order_type="limit",
            time_in_force="GTC",
            quantity=Decimal("0.001"),
            limit_price=Decimal("100.00"),
            current_price=Decimal("100.00"),
            internal_max_notional=Decimal("1.00"),
            source="phase_d_guard_liveness_probe",
        )
    )
    evidence = {item.module: item for item in verdict.module_evidence}

    assert "StaleDataGuard" not in evidence
    assert evidence["SovereignExecutionGuard"].status == DORMANT_BY_POLICY
    assert evidence["SovereignExecutionGuard"].reason_code == "SOVEREIGN_EXECUTION_GUARD_NOT_AUTHORIZED_FOR_MUTATION"

    main_loop_source = (REPO_ROOT / "app" / "main_loop.py").read_text(encoding="utf-8")
    assert "evaluate_pre_trade_guardrails(" in main_loop_source
    assert "StaleDataGuard(" not in main_loop_source
    assert "SovereignExecutionGuard(" not in main_loop_source
