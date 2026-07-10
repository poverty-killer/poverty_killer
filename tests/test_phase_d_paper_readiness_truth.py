from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path

from app.api.operator_readonly_api import OperatorSnapshotProvider, create_operator_app
from app.api.operator_runtime_config import OperatorRuntimeConfig
from app.execution.alpaca_paper_adapter import AlpacaPaperBrokerAdapter
from app.execution.alpaca_paper_adapter import (
    EXPECTED_ALPACA_PAPER_BASE_URL,
    FORBIDDEN_ALPACA_LIVE_BASE_URL,
    validate_alpaca_paper_credential_authority,
)
from app.execution.paper_broker import PaperBroker
from app.operator_credentials.store import LocalCredentialStore
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


def _write_canonical_paper_env(path: Path, *, base_url: str = EXPECTED_ALPACA_PAPER_BASE_URL) -> None:
    path.write_text(
        "\n".join(
            (
                f"APCA_API_BASE_URL={base_url}",
                "APCA_API_KEY_ID=canonical-paper-key",
                "APCA_API_SECRET_KEY=canonical-paper-secret",
            )
        ),
        encoding="utf-8",
    )


def _endpoint(app, path: str, method: str = "GET"):
    for route in app.routes:
        if route.path == path and method in (route.methods or set()):
            return route.endpoint
    raise AssertionError(f"route not found: {method} {path}")


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


def test_d1_stale_data_guard_fires_and_sovereign_guard_stays_lawfully_dormant() -> None:
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
            stale_data_observation={
                "current_ts_ns": 1_777_948_801_000_000_000,
                "exchange_ts_ns": 1_777_948_800_000_000_000,
                "local_received_ts_ns": 1_777_948_800_900_000_000,
            },
            source="phase_d_guard_liveness_probe",
        )
    )
    evidence = {item.module: item for item in verdict.module_evidence}

    assert verdict.route_permitted is False
    assert "STALE_DATA_GUARD_ABSOLUTE_DRIFT_LIMIT_BREACH" in verdict.reason_codes
    assert evidence["StaleDataGuard"].status == "CONTRIBUTED_BLOCK"
    assert evidence["StaleDataGuard"].details["risk_action"] == "BLOCK_ALL_NEW"
    assert evidence["StaleDataGuard"].details["mutation_authority"] is False
    assert evidence["SovereignExecutionGuard"].status == DORMANT_BY_POLICY
    assert evidence["SovereignExecutionGuard"].reason_code == "SOVEREIGN_EXECUTION_GUARD_DORMANT_PENDING_PHASE_HI_ARM"

    main_loop_source = (REPO_ROOT / "app" / "main_loop.py").read_text(encoding="utf-8")
    assert "evaluate_pre_trade_guardrails(" in main_loop_source
    assert "_pre_trade_stale_data_observation(signal, metadata)" in main_loop_source
    assert "StaleDataGuard(" not in main_loop_source
    assert "SovereignExecutionGuard(" not in main_loop_source


def test_d2_alpaca_paper_backend_paths_resolve_only_canonical_env_file(monkeypatch, tmp_path) -> None:
    env_path = tmp_path / "canonical_paper.env"
    _write_canonical_paper_env(env_path)
    monkeypatch.setenv("POVERTY_KILLER_ALPACA_PAPER_ENV_PATH", str(env_path))

    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    store.save_provider(
        "alpaca_paper",
        {
            "APCA_API_BASE_URL": FORBIDDEN_ALPACA_LIVE_BASE_URL,
            "APCA_API_KEY_ID": "demoted-local-key",
            "APCA_API_SECRET_KEY": "demoted-local-secret",
        },
    )
    effective = store.effective_provider_values(
        "alpaca_paper",
        {
            "APCA_API_BASE_URL": FORBIDDEN_ALPACA_LIVE_BASE_URL,
            "APCA_API_KEY_ID": "stale-process-key",
            "APCA_API_SECRET_KEY": "stale-process-secret",
        },
    )
    summary = store.provider_summary("alpaca_paper", {})
    proof = validate_alpaca_paper_credential_authority(env_path)

    assert effective == {
        "APCA_API_BASE_URL": EXPECTED_ALPACA_PAPER_BASE_URL,
        "APCA_API_KEY_ID": "canonical-paper-key",
        "APCA_API_SECRET_KEY": "canonical-paper-secret",
    }
    assert summary["configured"] is True
    assert summary["source"] == "CANONICAL_PAPER_ENV_FILE"
    assert proof.status == "CREDENTIAL_AUTHORITY_OK"
    assert proof.credential_source == "canonical_paper_env_file"


def test_d3_live_endpoint_is_blocked_even_from_canonical_env_file(monkeypatch, tmp_path) -> None:
    env_path = tmp_path / "canonical_live.env"
    _write_canonical_paper_env(env_path, base_url=FORBIDDEN_ALPACA_LIVE_BASE_URL)
    monkeypatch.setenv("POVERTY_KILLER_ALPACA_PAPER_ENV_PATH", str(env_path))

    proof = validate_alpaca_paper_credential_authority(env_path)

    assert proof.status == "FAILED_CLOSED"
    assert "LIVE_ENDPOINT_BLOCKED" in proof.reason_codes
    assert proof.live_endpoint_used is True


def test_d5_d6_d7_readiness_blocks_without_board_broker_read_and_requires_final_reconciliation(monkeypatch, tmp_path) -> None:
    class BrokerReadWouldFail:
        def get_json(self, path, headers):  # pragma: no cover - must not be called
            raise AssertionError(f"broker read was not authorized: {path}")

    env_path = tmp_path / "canonical_paper.env"
    _write_canonical_paper_env(env_path)
    monkeypatch.setenv("POVERTY_KILLER_ALPACA_PAPER_ENV_PATH", str(env_path))
    provider = OperatorSnapshotProvider(
        runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
        provider_env={},
        credential_store=LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json"),
        portfolio_client=BrokerReadWouldFail(),
    )
    app = create_operator_app(provider=provider)

    portfolio = _endpoint(app, "/operator/portfolio")()
    launch = _endpoint(app, "/operator/launch-readiness")()

    assert portfolio["status"] == "BACKEND_DEGRADED"
    assert portfolio["unavailable_reason"] == "BROKER_READ_NOT_AUTHORIZED"
    assert portfolio["broker_read_attempted"] is False
    assert portfolio["broker_read_occurred"] is False
    assert launch["final_launch_readiness"] == "BLOCKED"
    assert launch["paper_start_allowed"] is False
    assert launch["run_paper_operator_state"]["can_run_paper"]["allowed"] is False
    assert launch["final_reconciliation_required"] is True
    assert launch["final_reconciliation_contract"]["owner"] == "OrderRouter.finalize_oms_shutdown_reconciliation"


def test_d6_no_degraded_or_governed_alias_remains_in_runtime_contracts() -> None:
    checked_paths = [
        REPO_ROOT / "app" / "operator_activation" / "launch_readiness.py",
        REPO_ROOT / "app" / "api" / "operator_readonly_api.py",
        REPO_ROOT / "ui" / "operator-control-panel" / "app.js",
        REPO_ROOT / "ui" / "operator-control-panel" / "contracts.json",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in checked_paths)

    assert "DEGRADED_BUT_RUNNABLE" not in combined
    assert "READY_FOR_GOVERNED_PAPER" not in combined
    assert "READY_FOR_BOUNDED_PAPER" in combined
