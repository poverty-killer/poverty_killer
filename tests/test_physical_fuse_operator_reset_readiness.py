from dataclasses import replace

from app.execution.alpaca_paper_adapter import AlpacaPaperReadOnlyReconciliationProof
from app.monitoring.health import evaluate_physical_fuse_readiness
from app.risk.guard import (
    HybridRiskGuard,
    PhysicalFuseOperatorResetEvidence,
)


def _guard(tmp_path):
    return HybridRiskGuard(
        initial_equity=10000.0,
        state_file=str(tmp_path / "risk_state.json"),
        backup_file=str(tmp_path / "risk_state.backup"),
    )


def _stale_fuse_guard(tmp_path):
    guard = _guard(tmp_path)
    assert guard.check_physical_fuse(7000.0) is True
    assert guard.check_physical_fuse(9000.0) is False
    assert guard.classify_physical_fuse_state() == "PHYSICAL_FUSE_STALE"
    return guard


def _active_fuse_guard(tmp_path):
    guard = _guard(tmp_path)
    assert guard.check_physical_fuse(7000.0) is True
    assert guard.classify_physical_fuse_state() == "PHYSICAL_FUSE_ACTIVE"
    return guard


def _good_evidence(**overrides):
    evidence = PhysicalFuseOperatorResetEvidence(
        operator_acknowledged=True,
        broker_read_only_reconciled=True,
        broker_environment="paper",
        live_endpoint_used=False,
        mutation_occurred=False,
        request_counts={"GET": 3, "POST": 0, "PATCH": 0, "DELETE": 0},
        shadow_read_only=True,
        broker_local_conflict=False,
        source="deterministic safety fixture",
        note="deterministic safety fixture; no broker/network calls",
    )
    return replace(evidence, **overrides)


def test_physical_fuse_active_blocks_autonomous_paper_readiness(tmp_path):
    guard = _active_fuse_guard(tmp_path)

    result = guard.reset_stale_physical_fuse_with_evidence(_good_evidence())

    assert result.status == "FAILED_CLOSED"
    assert result.reset_applied is False
    assert "PHYSICAL_FUSE_ACTIVE" in result.reason_codes
    assert "PHYSICAL_FUSE_BLOCKS_AUTONOMOUS_PAPER" in result.reason_codes
    assert guard.get_status()["can_trade"] is False


def test_stale_physical_fuse_is_classified_distinctly_from_active_fuse(tmp_path):
    active = _active_fuse_guard(tmp_path / "active")
    stale = _stale_fuse_guard(tmp_path / "stale")

    assert active.classify_physical_fuse_state() == "PHYSICAL_FUSE_ACTIVE"
    assert stale.classify_physical_fuse_state() == "PHYSICAL_FUSE_STALE"


def test_stale_fuse_cannot_clear_without_required_current_safe_evidence(tmp_path):
    guard = _stale_fuse_guard(tmp_path)

    result = guard.reset_stale_physical_fuse_with_evidence(
        _good_evidence(operator_acknowledged=False)
    )

    assert result.status == "FAILED_CLOSED"
    assert result.reset_applied is False
    assert "PHYSICAL_FUSE_REQUIRES_OPERATOR_ACTION" in result.reason_codes
    assert guard.classify_physical_fuse_state() == "PHYSICAL_FUSE_STALE"


def test_owner_can_reset_stale_fuse_only_when_required_evidence_is_present(tmp_path):
    guard = _stale_fuse_guard(tmp_path)

    result = guard.reset_stale_physical_fuse_with_evidence(_good_evidence())

    assert result.status == "PHYSICAL_FUSE_CLEARED"
    assert result.reset_applied is True
    assert result.audit_event["event"] == "PHYSICAL_FUSE_OPERATOR_RESET_APPLIED"
    assert result.audit_event["classification_before"] == "PHYSICAL_FUSE_STALE"
    assert result.audit_event["classification_after"] == "PHYSICAL_FUSE_CLEARED"
    status = guard.get_status()
    assert status["physical_fuse_triggered"] is False
    assert status["physical_fuse_status"] == "PHYSICAL_FUSE_CLEARED"
    assert status["last_operator_reset_audit"]["event"] == "PHYSICAL_FUSE_OPERATOR_RESET_APPLIED"


def test_report_readiness_consumes_fuse_status_truthfully(tmp_path):
    guard = _stale_fuse_guard(tmp_path)
    status = guard.get_status()

    readiness = evaluate_physical_fuse_readiness(status)

    assert status["physical_fuse_status"] == "PHYSICAL_FUSE_STALE"
    assert readiness.status == "PHYSICAL_FUSE_STALE"
    assert readiness.blocks_autonomous_paper is True
    assert "PHYSICAL_FUSE_REQUIRES_OPERATOR_ACTION" in readiness.reason_codes


def test_kraken_partial_market_truth_does_not_masquerade_as_physical_fuse():
    readiness = evaluate_physical_fuse_readiness(
        {
            "physical_fuse_triggered": False,
            "current_equity": 10000,
            "high_water_mark": 10000,
            "physical_fuse": 7500,
            "market_truth_status": "MARKET_DATA_PARTIAL_TRUTH",
            "feed_reason": "REST_DNS_FAILURE",
        }
    )

    assert readiness.status == "PHYSICAL_FUSE_CLEARED"
    assert "REST_DNS_FAILURE" not in readiness.reason_codes


def test_alpaca_read_only_reconciliation_proof_can_be_used_only_after_get_only_truth(tmp_path):
    proof = AlpacaPaperReadOnlyReconciliationProof(
        status="BROKER_READ_ONLY_RECONCILED",
        reason_codes=("BROKER_READ_ONLY_GETS_SUCCEEDED",),
        endpoint="https://paper-api.alpaca.markets",
        environment="paper",
        account_status="read",
        positions_count=7,
        open_orders_count=0,
        request_counts={"GET": 3, "POST": 0},
        broker_truth={
            "account": {"fixture": "deterministic broker-shaped fixture"},
            "positions": [],
            "open_orders": [],
        },
        mutation_occurred=False,
        live_endpoint_used=False,
    )
    guard = _stale_fuse_guard(tmp_path)

    result = guard.reset_stale_physical_fuse_with_evidence(
        PhysicalFuseOperatorResetEvidence(
            operator_acknowledged=True,
            broker_read_only_reconciled=proof.status == "BROKER_READ_ONLY_RECONCILED",
            broker_environment=proof.environment,
            live_endpoint_used=proof.live_endpoint_used,
            mutation_occurred=proof.mutation_occurred,
            request_counts=proof.request_counts,
            shadow_read_only=True,
            broker_local_conflict=False,
            source="deterministic safety fixture",
        )
    )

    assert result.reset_applied is True
    assert proof.request_counts["POST"] == 0


def test_live_endpoint_or_broker_mutation_blocks_stale_fuse_reset(tmp_path):
    guard = _stale_fuse_guard(tmp_path)

    result = guard.reset_stale_physical_fuse_with_evidence(
        _good_evidence(
            broker_environment="live",
            live_endpoint_used=True,
            mutation_occurred=True,
            request_counts={"GET": 3, "POST": 1, "PATCH": 0, "DELETE": 0},
        )
    )

    assert result.status == "FAILED_CLOSED"
    assert result.reset_applied is False
    assert "PAPER_BROKER_ENVIRONMENT_REQUIRED" in result.reason_codes
    assert "LIVE_ENDPOINT_USED_BLOCKS_RESET" in result.reason_codes
    assert "BROKER_MUTATION_BLOCKS_RESET" in result.reason_codes
    assert guard.classify_physical_fuse_state() == "PHYSICAL_FUSE_STALE"


def test_broker_local_conflict_or_missing_shadow_blocks_reset(tmp_path):
    guard = _stale_fuse_guard(tmp_path)

    result = guard.reset_stale_physical_fuse_with_evidence(
        _good_evidence(shadow_read_only=False, broker_local_conflict=True)
    )

    assert result.reset_applied is False
    assert "SHADOW_READ_ONLY_EVIDENCE_REQUIRED" in result.reason_codes
    assert "BROKER_LOCAL_CONFLICT_BLOCKS_RESET" in result.reason_codes
