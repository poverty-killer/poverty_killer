from dataclasses import replace

from app.monitoring.health import evaluate_physical_fuse_readiness
from app.risk.guard import HybridRiskGuard, PhysicalFuseOperatorResetEvidence


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


def _safe_evidence(**overrides):
    evidence = PhysicalFuseOperatorResetEvidence(
        operator_acknowledged=True,
        broker_read_only_reconciled=True,
        broker_environment="paper",
        live_endpoint_used=False,
        mutation_occurred=False,
        request_counts={"GET": 3, "POST": 0, "PATCH": 0, "DELETE": 0},
        shadow_read_only=True,
        broker_local_conflict=False,
        source="deterministic reset fixture",
        note="fixture only; no broker/network calls",
    )
    return replace(evidence, **overrides)


def _readiness_verdict(
    *,
    physical_fuse_status,
    broker_reconciled=True,
    shadow_read_only=True,
    broker_mutation_count=0,
    live_endpoint_used=False,
    lag_abort_active=False,
    critical_feed_blocker=False,
):
    reasons = []
    if physical_fuse_status != "PHYSICAL_FUSE_CLEARED":
        reasons.append("PHYSICAL_FUSE_REQUIRES_OPERATOR_ACTION")
    if not broker_reconciled:
        reasons.append("BROKER_READ_ONLY_RECONCILIATION_REQUIRED")
    if not shadow_read_only:
        reasons.append("SHADOW_READ_ONLY_REQUIRED")
    if broker_mutation_count:
        reasons.append("BROKER_MUTATION_IN_SHADOW")
    if live_endpoint_used:
        reasons.append("LIVE_ENDPOINT_USED")
    if lag_abort_active:
        reasons.append("LAG_ABORT_ACTIVE")
    if critical_feed_blocker:
        reasons.append("CRITICAL_FEED_TRUTH_BLOCKER")
    return ("READY_FOR_AUTONOMOUS_PAPER" if not reasons else "NOT_READY_FOR_AUTONOMOUS_PAPER", reasons)


def test_operator_reset_applies_only_through_hybrid_risk_guard_owner_path(tmp_path):
    guard = _stale_fuse_guard(tmp_path)

    result = guard.reset_stale_physical_fuse_with_evidence(_safe_evidence())

    assert result.status == "PHYSICAL_FUSE_CLEARED"
    assert result.reset_applied is True
    status = guard.get_status()
    assert status["physical_fuse_status"] == "PHYSICAL_FUSE_CLEARED"
    assert status["physical_fuse_triggered"] is False
    assert status["last_operator_reset_audit"]["event"] == "PHYSICAL_FUSE_OPERATOR_RESET_APPLIED"
    assert status["last_operator_reset_audit"]["evidence"]["request_counts"]["POST"] == 0


def test_operator_reset_refuses_live_endpoint_or_mutation_evidence(tmp_path):
    guard = _stale_fuse_guard(tmp_path)

    result = guard.reset_stale_physical_fuse_with_evidence(
        _safe_evidence(
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


def test_physical_fuse_readiness_changes_only_after_owner_reset(tmp_path):
    guard = _stale_fuse_guard(tmp_path)

    before = evaluate_physical_fuse_readiness(guard.get_status())
    assert before.status == "PHYSICAL_FUSE_STALE"
    assert before.blocks_autonomous_paper is True

    guard.reset_stale_physical_fuse_with_evidence(_safe_evidence())
    after = evaluate_physical_fuse_readiness(guard.get_status())

    assert after.status == "PHYSICAL_FUSE_CLEARED"
    assert after.blocks_autonomous_paper is False


def test_clean_shadow_and_broker_truth_can_be_ready_after_fuse_cleared(tmp_path):
    guard = _stale_fuse_guard(tmp_path)
    guard.reset_stale_physical_fuse_with_evidence(_safe_evidence())

    verdict, reasons = _readiness_verdict(
        physical_fuse_status=guard.get_status()["physical_fuse_status"],
        broker_reconciled=True,
        shadow_read_only=True,
        broker_mutation_count=0,
        live_endpoint_used=False,
    )

    assert verdict == "READY_FOR_AUTONOMOUS_PAPER"
    assert reasons == []


def test_fresh_shadow_latency_abort_still_blocks_readiness_after_fuse_reset(tmp_path):
    guard = _stale_fuse_guard(tmp_path)
    guard.reset_stale_physical_fuse_with_evidence(_safe_evidence())

    verdict, reasons = _readiness_verdict(
        physical_fuse_status=guard.get_status()["physical_fuse_status"],
        broker_reconciled=True,
        shadow_read_only=True,
        broker_mutation_count=0,
        live_endpoint_used=False,
        lag_abort_active=True,
    )

    assert verdict == "NOT_READY_FOR_AUTONOMOUS_PAPER"
    assert reasons == ["LAG_ABORT_ACTIVE"]


def test_shadow_readiness_fails_closed_on_mutation_or_live_endpoint_markers(tmp_path):
    guard = _stale_fuse_guard(tmp_path)
    guard.reset_stale_physical_fuse_with_evidence(_safe_evidence())

    verdict, reasons = _readiness_verdict(
        physical_fuse_status=guard.get_status()["physical_fuse_status"],
        broker_reconciled=True,
        shadow_read_only=True,
        broker_mutation_count=1,
        live_endpoint_used=True,
    )

    assert verdict == "NOT_READY_FOR_AUTONOMOUS_PAPER"
    assert "BROKER_MUTATION_IN_SHADOW" in reasons
    assert "LIVE_ENDPOINT_USED" in reasons


def test_missing_broker_truth_remains_blocking_even_after_fuse_reset(tmp_path):
    guard = _stale_fuse_guard(tmp_path)
    guard.reset_stale_physical_fuse_with_evidence(_safe_evidence())

    verdict, reasons = _readiness_verdict(
        physical_fuse_status=guard.get_status()["physical_fuse_status"],
        broker_reconciled=False,
        shadow_read_only=True,
        broker_mutation_count=0,
        live_endpoint_used=False,
    )

    assert verdict == "NOT_READY_FOR_AUTONOMOUS_PAPER"
    assert reasons == ["BROKER_READ_ONLY_RECONCILIATION_REQUIRED"]
