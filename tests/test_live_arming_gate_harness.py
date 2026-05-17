from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import main as runtime_main
from app.config import Config
from app.risk.kill_switch import KillSwitch, KillSwitchState, KillSwitchType
from app.state.state_store import StateStore


T0_NS = 1_777_948_800_000_000_000
BOARD_TINY_NOTIONAL_CAP = Decimal("25.00")


@dataclass(frozen=True)
class LiveArmingEvidence:
    broker_mode: str = "paper"
    board_approved_live_arming: bool | None = False
    operator_armed: bool | None = False
    live_adapter_contract_verified: bool | None = False
    broker_contract_verified: bool | None = False
    broker_sandbox_proof: bool | None = False
    reconciliation_ready: bool | None = False
    live_cancel_terminal_reconciliation_proven: bool | None = False
    live_fill_ingestion_proven: bool | None = False
    live_account_position_balance_reconciliation_proven: bool | None = False
    live_operator_escape_dry_run_proven: bool | None = False
    unknown_broker_state_fails_closed: bool | None = True
    cancel_acceptance_is_terminal_truth: bool | None = False
    live_reservation_lifecycle_allowed: bool | None = False
    max_notional: Decimal | None = None
    single_order_mode: bool | None = False
    single_symbol: str | None = None
    operator_present: bool | None = False
    sandbox_read_only_check_complete: bool | None = False
    allow_market_order: bool | None = False
    concrete_live_adapter_implemented: bool | None = False


@dataclass(frozen=True)
class LiveReadinessDecision:
    ready: bool
    reason_codes: tuple[str, ...]
    live_submit_allowed: bool = False
    live_reservation_lifecycle_allowed: bool = False
    side_effects: tuple[str, ...] = ()
    route_to: str = "blocked"


@dataclass
class FakeLiveSubmitter:
    calls: list[dict[str, Any]] = field(default_factory=list)

    def submit(self, evidence: LiveArmingEvidence, kill_switch: KillSwitch, timestamp_ns: int) -> LiveReadinessDecision:
        decision = evaluate_live_arming(evidence, kill_switch, timestamp_ns)
        if decision.ready:
            self.calls.append({"evidence": evidence, "timestamp_ns": timestamp_ns})
        return decision


REQUIRED_TRUE_FIELDS = {
    "board_approved_live_arming": "missing_board_live_approval",
    "operator_armed": "operator_not_armed",
    "live_adapter_contract_verified": "live_adapter_contract_not_verified",
    "broker_contract_verified": "broker_contract_not_verified",
    "broker_sandbox_proof": "broker_sandbox_proof_missing",
    "reconciliation_ready": "reconciliation_not_ready",
    "live_cancel_terminal_reconciliation_proven": "live_cancel_terminal_reconciliation_not_proven",
    "live_fill_ingestion_proven": "live_fill_ingestion_not_proven",
    "live_account_position_balance_reconciliation_proven": "live_account_position_balance_reconciliation_not_proven",
    "live_operator_escape_dry_run_proven": "live_operator_escape_dry_run_not_proven",
    "unknown_broker_state_fails_closed": "unknown_broker_state_policy_missing",
    "single_order_mode": "single_order_mode_required",
    "operator_present": "operator_presence_required",
    "sandbox_read_only_check_complete": "sandbox_read_only_check_missing",
}


def evaluate_live_arming(
    evidence: LiveArmingEvidence,
    kill_switch: KillSwitch,
    timestamp_ns: int,
) -> LiveReadinessDecision:
    reasons: list[str] = []

    if evidence.broker_mode != "live":
        reasons.append("broker_mode_not_live")

    for field_name, reason in REQUIRED_TRUE_FIELDS.items():
        if getattr(evidence, field_name) is not True:
            reasons.append(reason)

    if evidence.cancel_acceptance_is_terminal_truth is not False:
        reasons.append("cancel_acceptance_cannot_be_terminal_truth")

    if evidence.live_reservation_lifecycle_allowed is not False:
        reasons.append("live_reservation_lifecycle_must_remain_blocked")

    if evidence.allow_market_order is not False:
        reasons.append("market_orders_not_allowed_for_tiny_live_prereq")

    if evidence.concrete_live_adapter_implemented is not True:
        reasons.append("concrete_live_adapter_missing")

    if evidence.max_notional is None:
        reasons.append("max_notional_missing")
    else:
        try:
            max_notional = Decimal(str(evidence.max_notional))
        except Exception:
            reasons.append("max_notional_invalid")
        else:
            if max_notional <= Decimal("0"):
                reasons.append("max_notional_invalid")
            if max_notional > BOARD_TINY_NOTIONAL_CAP:
                reasons.append("max_notional_exceeds_board_cap")

    if not evidence.single_symbol:
        reasons.append("single_symbol_required")

    if not kill_switch.can_trade(timestamp_ns):
        reasons.append("kill_switch_blocks_live_submit")

    ready = not reasons
    return LiveReadinessDecision(
        ready=ready,
        reason_codes=tuple(reasons),
        live_submit_allowed=ready,
        live_reservation_lifecycle_allowed=False,
        side_effects=(),
        route_to="future_execution_engine_order_router_only" if ready else "blocked",
    )


def _all_prereqs() -> LiveArmingEvidence:
    return LiveArmingEvidence(
        broker_mode="live",
        board_approved_live_arming=True,
        operator_armed=True,
        live_adapter_contract_verified=True,
        broker_contract_verified=True,
        broker_sandbox_proof=True,
        reconciliation_ready=True,
        live_cancel_terminal_reconciliation_proven=True,
        live_fill_ingestion_proven=True,
        live_account_position_balance_reconciliation_proven=True,
        live_operator_escape_dry_run_proven=True,
        unknown_broker_state_fails_closed=True,
        cancel_acceptance_is_terminal_truth=False,
        live_reservation_lifecycle_allowed=False,
        max_notional=Decimal("5.00"),
        single_order_mode=True,
        single_symbol="ETH/USD",
        operator_present=True,
        sandbox_read_only_check_complete=True,
        allow_market_order=False,
        concrete_live_adapter_implemented=True,
    )


def test_default_disarmed_and_missing_or_ambiguous_arming_fail_closed():
    kill_switch = KillSwitch()

    default_decision = evaluate_live_arming(LiveArmingEvidence(), kill_switch, T0_NS)
    ambiguous_decision = evaluate_live_arming(
        LiveArmingEvidence(
            broker_mode="live",
            board_approved_live_arming=None,
            operator_armed=None,
            live_adapter_contract_verified=None,
            broker_contract_verified=None,
            reconciliation_ready=None,
            max_notional=None,
            single_symbol=None,
        ),
        kill_switch,
        T0_NS,
    )

    assert default_decision.ready is False
    assert default_decision.live_submit_allowed is False
    assert "broker_mode_not_live" in default_decision.reason_codes
    assert "missing_board_live_approval" in default_decision.reason_codes
    assert "max_notional_missing" in default_decision.reason_codes
    assert ambiguous_decision.ready is False
    assert "missing_board_live_approval" in ambiguous_decision.reason_codes
    assert "operator_not_armed" in ambiguous_decision.reason_codes
    assert "live_adapter_contract_not_verified" in ambiguous_decision.reason_codes
    assert ambiguous_decision.side_effects == ()


def test_each_25l_25m_no_go_blocker_prevents_live_readiness():
    kill_switch = KillSwitch()
    baseline = _all_prereqs()

    blocker_cases = {
        "concrete_live_adapter_missing": {"concrete_live_adapter_implemented": False},
        "broker_sandbox_proof_missing": {"broker_sandbox_proof": False},
        "live_cancel_terminal_reconciliation_not_proven": {
            "live_cancel_terminal_reconciliation_proven": False
        },
        "live_fill_ingestion_not_proven": {"live_fill_ingestion_proven": False},
        "live_account_position_balance_reconciliation_not_proven": {
            "live_account_position_balance_reconciliation_proven": False
        },
        "live_operator_escape_dry_run_not_proven": {
            "live_operator_escape_dry_run_proven": False
        },
        "live_reservation_lifecycle_must_remain_blocked": {
            "live_reservation_lifecycle_allowed": True
        },
        "cancel_acceptance_cannot_be_terminal_truth": {
            "cancel_acceptance_is_terminal_truth": True
        },
        "unknown_broker_state_policy_missing": {
            "unknown_broker_state_fails_closed": False
        },
        "missing_board_live_approval": {"board_approved_live_arming": False},
    }

    for expected_reason, overrides in blocker_cases.items():
        decision = evaluate_live_arming(
            baseline.__class__(**{**baseline.__dict__, **overrides}),
            kill_switch,
            T0_NS,
        )
        assert decision.ready is False
        assert decision.live_submit_allowed is False
        assert expected_reason in decision.reason_codes
        assert decision.side_effects == ()


def test_submit_blocking_contract_never_calls_fake_submit_when_blocked():
    kill_switch = KillSwitch()
    submitter = FakeLiveSubmitter()

    disarmed = submitter.submit(LiveArmingEvidence(broker_mode="live"), kill_switch, T0_NS)
    no_adapter = submitter.submit(
        _all_prereqs().__class__(
            **{**_all_prereqs().__dict__, "live_adapter_contract_verified": False}
        ),
        kill_switch,
        T0_NS,
    )
    no_reconcile = submitter.submit(
        _all_prereqs().__class__(
            **{**_all_prereqs().__dict__, "reconciliation_ready": False}
        ),
        kill_switch,
        T0_NS,
    )
    invalid_size = submitter.submit(
        _all_prereqs().__class__(
            **{**_all_prereqs().__dict__, "max_notional": Decimal("0")}
        ),
        kill_switch,
        T0_NS,
    )
    paper_mode = submitter.submit(
        _all_prereqs().__class__(**{**_all_prereqs().__dict__, "broker_mode": "paper"}),
        kill_switch,
        T0_NS,
    )

    assert disarmed.reason_codes
    assert "live_adapter_contract_not_verified" in no_adapter.reason_codes
    assert "reconciliation_not_ready" in no_reconcile.reason_codes
    assert "max_notional_invalid" in invalid_size.reason_codes
    assert "broker_mode_not_live" in paper_mode.reason_codes
    assert submitter.calls == []


def test_kill_switch_operator_escape_persists_and_operator_arm_cannot_override():
    kill_switch = KillSwitch()
    kill_switch.trigger(
        KillSwitchType.MANUAL,
        reason="operator emergency stop before live arming",
        timestamp_ns=T0_NS,
        requires_manual_reset=True,
    )

    killed = evaluate_live_arming(_all_prereqs(), kill_switch, T0_NS + 1)
    exported = kill_switch.export_state()
    restarted = KillSwitch()
    restarted.import_state(exported, T0_NS + 2)
    restarted_killed = evaluate_live_arming(_all_prereqs(), restarted, T0_NS + 3)

    assert kill_switch.get_state() == KillSwitchState.MANUAL_RESET_REQUIRED
    assert killed.ready is False
    assert "kill_switch_blocks_live_submit" in killed.reason_codes
    assert restarted.get_state() == KillSwitchState.MANUAL_RESET_REQUIRED
    assert restarted_killed.ready is False
    assert "kill_switch_blocks_live_submit" in restarted_killed.reason_codes

    restarted.reset("manual reset after Board/operator review", T0_NS + 4)
    assert evaluate_live_arming(_all_prereqs(), restarted, T0_NS + 5).ready is True


def test_tiny_live_prerequisites_are_required_gates_not_permission_shortcuts():
    kill_switch = KillSwitch()
    baseline = _all_prereqs()

    missing_symbol = evaluate_live_arming(
        baseline.__class__(**{**baseline.__dict__, "single_symbol": None}),
        kill_switch,
        T0_NS,
    )
    missing_operator = evaluate_live_arming(
        baseline.__class__(**{**baseline.__dict__, "operator_present": False}),
        kill_switch,
        T0_NS,
    )
    missing_read_only_sandbox = evaluate_live_arming(
        baseline.__class__(**{**baseline.__dict__, "sandbox_read_only_check_complete": False}),
        kill_switch,
        T0_NS,
    )
    market_order_allowed = evaluate_live_arming(
        baseline.__class__(**{**baseline.__dict__, "allow_market_order": True}),
        kill_switch,
        T0_NS,
    )
    oversized = evaluate_live_arming(
        baseline.__class__(**{**baseline.__dict__, "max_notional": Decimal("25.01")}),
        kill_switch,
        T0_NS,
    )

    assert "single_symbol_required" in missing_symbol.reason_codes
    assert "operator_presence_required" in missing_operator.reason_codes
    assert "sandbox_read_only_check_missing" in missing_read_only_sandbox.reason_codes
    assert "market_orders_not_allowed_for_tiny_live_prereq" in market_order_allowed.reason_codes
    assert "max_notional_exceeds_board_cap" in oversized.reason_codes
    assert evaluate_live_arming(baseline, kill_switch, T0_NS).ready is True
    assert evaluate_live_arming(baseline, kill_switch, T0_NS).route_to == (
        "future_execution_engine_order_router_only"
    )


def test_config_live_gate_inspection_and_live_reservation_lifecycle_block(tmp_path):
    config = Config()
    assert config.broker_mode == "paper"
    assert config.reservation_lifecycle_paper_enabled is False
    assert config.risk.kill_switch_enabled is True
    assert not hasattr(config, "board_approved_live_arming")
    assert not hasattr(config, "operator_armed")

    root = runtime_main.SovereignHeartbeat.__new__(runtime_main.SovereignHeartbeat)
    root.state_store = StateStore(str(tmp_path / "state.db"))
    root._bootstrap_reservation_lifecycle_disabled(
        SimpleNamespace(
            initial_capital=20_000.0,
            broker_mode="live",
            reservation_lifecycle_paper_enabled=True,
        )
    )

    assert root.reservation_lifecycle_enabled is False
    assert root.reservation_lifecycle_bootstrap_status["reservation_lifecycle_live_blocked"] is True
    assert root.reservation_lifecycle_bootstrap_status["reservation_lifecycle_scope"] == "disabled"

    main_source = Path("main.py").read_text(encoding="utf-8-sig")
    main_loop_source = Path("app/main_loop.py").read_text(encoding="utf-8-sig")
    broker_adapter_source = Path("app/execution/broker_adapter.py").read_text(encoding="utf-8-sig")
    live_broker_source = Path("app/execution/live_broker.py").read_text(encoding="utf-8-sig")

    assert "--paper" in main_source
    assert "broker_mode == \"paper\"" in main_loop_source
    assert "paper-only gate" in main_loop_source
    assert "PRE-INTEGRATION" in broker_adapter_source
    assert "NO IMPLEMENTATION" in broker_adapter_source
    assert "Under construction" in live_broker_source
    assert "submit_order" not in live_broker_source
