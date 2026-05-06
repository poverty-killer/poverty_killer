"""
G0 Hook Verification Test Suite — POVERTY_KILLER

Drives evaluate_event() directly (no subprocess) to verify hook governance
invariants are intact. All test cases must pass before G0 is considered
verified.

Import path: .claude/hooks/pre_tool_use.py loaded via importlib because
.claude is not a valid Python package identifier.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

# ---------------------------------------------------------------------------
# Load hook module
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
_HOOK_PATH = REPO_ROOT / ".claude" / "hooks" / "pre_tool_use.py"

assert _HOOK_PATH.exists(), f"Hook not found: {_HOOK_PATH}"

_spec = importlib.util.spec_from_file_location("pre_tool_use", _HOOK_PATH)
_hook = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_hook)

evaluate_event = _hook.evaluate_event


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _edit(path: str) -> Dict[str, Any]:
    return {"tool_name": "Edit", "tool_input": {"file_path": path}}


def _write(path: str) -> Dict[str, Any]:
    return {"tool_name": "Write", "tool_input": {"file_path": path}}


def _bash(cmd: str) -> Dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": cmd}}


def _g0_env() -> Dict[str, str]:
    return {"POVERTY_KILLER_PACKET": "G0"}


def _f4a_env() -> Dict[str, str]:
    return {"POVERTY_KILLER_PACKET": "F4A"}


def _f4b_env() -> Dict[str, str]:
    return {"POVERTY_KILLER_PACKET": "F4B"}


def _f4c_env() -> Dict[str, str]:
    return {"POVERTY_KILLER_PACKET": "F4C"}


def _strategy_admission_env() -> Dict[str, str]:
    return {"POVERTY_KILLER_PACKET": "STRATEGY_ADMISSION"}


def _execution_sr_decimal_env() -> Dict[str, str]:
    return {"POVERTY_KILLER_PACKET": "EXECUTION_SR_DECIMAL"}


def _regime_aware_sr_admission_env() -> Dict[str, str]:
    return {"POVERTY_KILLER_PACKET": "REGIME_AWARE_SR_ADMISSION"}


def _override_env(reason: str) -> Dict[str, str]:
    return {
        "POVERTY_KILLER_PACKET": "G0",
        "POVERTY_KILLER_OVERRIDE": "true",
        "POVERTY_KILLER_OVERRIDE_REASON": reason,
    }


# ---------------------------------------------------------------------------
# Parse-failure invariants
# ---------------------------------------------------------------------------

class TestParseFailure:
    def test_non_dict_event_blocked(self):
        result = evaluate_event("not a dict", {})
        assert result["decision"] == "block"
        assert "HOOK_PARSE_FAILURE" in result["reason"]

    def test_list_event_blocked(self):
        result = evaluate_event([], {})
        assert result["decision"] == "block"
        assert "HOOK_PARSE_FAILURE" in result["reason"]

    def test_tool_input_not_dict_blocked(self):
        event = {"tool_name": "Edit", "tool_input": "not_a_dict"}
        result = evaluate_event(event, _g0_env())
        assert result["decision"] == "block"
        assert "HOOK_PARSE_FAILURE" in result["reason"]


# ---------------------------------------------------------------------------
# Locked-authority file invariants
# ---------------------------------------------------------------------------

class TestLockedAuthorityFiles:
    LOCKED = [
        "app/brain/signal_fusion.py",
        "app/brain/regime_detector.py",
        "app/brain/shans_curve.py",
        "app/brain/entropy_decoder.py",
        "app/brain/whale_flow_engine.py",
        "app/brain/whale_zone_engine.py",
        "app/brain/sentiment_velocity.py",
        "app/strategies/strategy_router.py",
        "app/risk/guard.py",
        "app/risk/unified_risk.py",
        "app/execution/engine.py",
        "app/core/decision_compiler.py",
        "app/core/truth_kernel.py",
        "app/core/truth_reconciler.py",
    ]

    def test_locked_files_blocked_in_g0(self):
        for path in self.LOCKED:
            # engine.py is in F4A so skip it here — tested separately.
            if path == "app/execution/engine.py":
                continue
            result = evaluate_event(_edit(path), _g0_env())
            assert result["decision"] == "block", f"Expected block for locked file {path!r}"
            assert "locked_authority_file" in result["reason"]

    def test_locked_file_blocked_with_no_packet(self):
        for path in self.LOCKED:
            result = evaluate_event(_edit(path), {})
            assert result["decision"] == "block", f"Expected block with no packet for {path!r}"


# ---------------------------------------------------------------------------
# G0 allowlist invariants
# ---------------------------------------------------------------------------

class TestG0Allowlist:
    ALLOWED = [
        "claude.md",
        ".claude/settings.json",
        ".claude/settings.local.json",
        ".claude/hooks/pre_tool_use.py",
        ".claude/hooks/post_tool_use.py",
        ".claude/commands/paper-proof.md",
        ".claude/commands/packet.md",
        ".claude/commands/check-spine.md",
        ".claude/commands/decimal-scan.md",
        ".claude/commands/audit.md",
        "docs/EXECUTION_PLAN.md",
        "docs/cross_asset_reference_scan.md",
        "docs/packets/f4a_decimal.md",
        "docs/packets/f4b_sentiment.md",
        "docs/packets/f4c_risk_state.md",
        "docs/packets/execution_sr_decimal.md",
        "docs/packets/regime_aware_sr_admission.md",
        "tests/test_g0_hook_verification.py",
        "state/override_log.jsonl",
        "state/session_journal.jsonl",
        # G0.6 additions
        "docs/board_autopilot_protocol.md",
        "docs/current_status.md",
        ".claude/commands/board-execute.md",
        ".claude/commands/start-session.md",
        ".claude/commands/end-session.md",
    ]

    def test_g0_allowlist_files_approved(self):
        for path in self.ALLOWED:
            result = evaluate_event(_edit(path), _g0_env())
            assert result["decision"] == "approve", (
                f"Expected approve for G0 allowlist file {path!r}, got {result}"
            )

    def test_g0_write_allowed(self):
        result = evaluate_event(_write("tests/test_g0_hook_verification.py"), _g0_env())
        assert result["decision"] == "approve"

    def test_g0_outside_allowlist_blocked(self):
        outside = [
            "app/main_loop.py",
            "app/brain/shans_curve.py",
            "main.py",
            "app/strategies/shadow_front.py",
        ]
        for path in outside:
            # shans_curve is locked — blocked for different reason, still blocked.
            result = evaluate_event(_edit(path), _g0_env())
            assert result["decision"] == "block", f"Expected block for {path!r}"

    def test_windows_backslash_path_normalized(self):
        result = evaluate_event(
            _edit("tests\\test_g0_hook_verification.py"), _g0_env()
        )
        assert result["decision"] == "approve"

    def test_absolute_windows_path_normalized(self):
        abs_path = str(REPO_ROOT / "tests" / "test_g0_hook_verification.py")
        result = evaluate_event(_edit(abs_path), _g0_env())
        assert result["decision"] == "approve"

    def test_case_insensitive_path(self):
        result = evaluate_event(_edit("TESTS/TEST_G0_HOOK_VERIFICATION.PY"), _g0_env())
        assert result["decision"] == "approve"

    def test_no_packet_blocks_allowlist_file(self):
        result = evaluate_event(_edit("claude.md"), {})
        assert result["decision"] == "block"


# ---------------------------------------------------------------------------
# Packet-scoped allowlists: F4A / F4B / F4C
# ---------------------------------------------------------------------------

class TestPacketAllowlists:
    def test_f4a_allows_execution_engine(self):
        result = evaluate_event(_edit("app/execution/engine.py"), _f4a_env())
        assert result["decision"] == "approve"

    def test_f4a_allows_order_router(self):
        result = evaluate_event(_edit("app/execution/order_router.py"), _f4a_env())
        assert result["decision"] == "approve"

    def test_f4a_allows_tests_prefix(self):
        result = evaluate_event(_edit("tests/test_decimal.py"), _f4a_env())
        assert result["decision"] == "approve"

    def test_f4a_blocks_signal_fusion(self):
        result = evaluate_event(_edit("app/brain/signal_fusion.py"), _f4a_env())
        assert result["decision"] == "block"

    def test_f4b_allows_sentiment_velocity(self):
        result = evaluate_event(_edit("app/brain/sentiment_velocity.py"), _f4b_env())
        assert result["decision"] == "approve"

    def test_f4b_blocks_regime_detector(self):
        result = evaluate_event(_edit("app/brain/regime_detector.py"), _f4b_env())
        assert result["decision"] == "block"

    def test_f4c_allows_risk_guard(self):
        result = evaluate_event(_edit("app/risk/guard.py"), _f4c_env())
        assert result["decision"] == "approve"

    def test_f4c_allows_unified_risk(self):
        result = evaluate_event(_edit("app/risk/unified_risk.py"), _f4c_env())
        assert result["decision"] == "approve"

    def test_f4c_blocks_decision_compiler(self):
        # decision_compiler is locked and NOT in F4C allowlist
        result = evaluate_event(_edit("app/core/decision_compiler.py"), _f4c_env())
        assert result["decision"] == "block"

    def test_unknown_packet_blocked(self):
        result = evaluate_event(
            _edit("app/main_loop.py"),
            {"POVERTY_KILLER_PACKET": "UNKNOWN_PACKET"},
        )
        assert result["decision"] == "block"
        assert "no_active_packet" in result["reason"] or "unknown_packet" in result["reason"]

    def test_audit_packet_unknown_blocked(self):
        result = evaluate_event(
            _edit("app/main_loop.py"),
            {"POVERTY_KILLER_PACKET": "AUDIT"},
        )
        assert result["decision"] == "block"
        assert "no_active_packet" in result["reason"] or "unknown_packet" in result["reason"]


# ---------------------------------------------------------------------------
# STRATEGY_ADMISSION packet allowlist
# ---------------------------------------------------------------------------

class TestStrategyAdmissionPacket:
    # --- Allowed paths ---

    def test_sa_allows_shadow_front(self):
        result = evaluate_event(_edit("app/strategies/shadow_front.py"), _strategy_admission_env())
        assert result["decision"] == "approve"

    def test_sa_allows_sector_rotation(self):
        result = evaluate_event(_edit("app/strategies/sector_rotation.py"), _strategy_admission_env())
        assert result["decision"] == "approve"

    def test_sa_allows_config(self):
        result = evaluate_event(_edit("app/config.py"), _strategy_admission_env())
        assert result["decision"] == "approve"

    def test_sa_allows_signals(self):
        result = evaluate_event(_edit("app/models/signals.py"), _strategy_admission_env())
        assert result["decision"] == "approve"

    def test_sa_allows_tests_prefix(self):
        result = evaluate_event(
            _edit("tests/test_strategy_admission_calibration.py"),
            _strategy_admission_env(),
        )
        assert result["decision"] == "approve"

    def test_sa_write_allowed_for_allowlist_file(self):
        result = evaluate_event(
            _write("app/strategies/shadow_front.py"),
            _strategy_admission_env(),
        )
        assert result["decision"] == "approve"

    # --- Blocked paths: locked authority files ---

    def test_sa_blocks_execution_engine(self):
        result = evaluate_event(_edit("app/execution/engine.py"), _strategy_admission_env())
        assert result["decision"] == "block"

    def test_sa_blocks_risk_guard(self):
        result = evaluate_event(_edit("app/risk/guard.py"), _strategy_admission_env())
        assert result["decision"] == "block"

    def test_sa_blocks_unified_risk(self):
        result = evaluate_event(_edit("app/risk/unified_risk.py"), _strategy_admission_env())
        assert result["decision"] == "block"

    def test_sa_blocks_signal_fusion(self):
        result = evaluate_event(_edit("app/brain/signal_fusion.py"), _strategy_admission_env())
        assert result["decision"] == "block"

    def test_sa_blocks_shans_curve(self):
        result = evaluate_event(_edit("app/brain/shans_curve.py"), _strategy_admission_env())
        assert result["decision"] == "block"

    def test_sa_blocks_regime_detector(self):
        result = evaluate_event(_edit("app/brain/regime_detector.py"), _strategy_admission_env())
        assert result["decision"] == "block"

    def test_sa_blocks_whale_flow_engine(self):
        result = evaluate_event(_edit("app/brain/whale_flow_engine.py"), _strategy_admission_env())
        assert result["decision"] == "block"

    def test_sa_blocks_whale_zone_engine(self):
        result = evaluate_event(_edit("app/brain/whale_zone_engine.py"), _strategy_admission_env())
        assert result["decision"] == "block"

    def test_sa_blocks_strategy_router(self):
        result = evaluate_event(_edit("app/strategies/strategy_router.py"), _strategy_admission_env())
        assert result["decision"] == "block"

    # --- Blocked paths: outside allowlist, not locked ---

    def test_sa_blocks_order_router(self):
        result = evaluate_event(_edit("app/execution/order_router.py"), _strategy_admission_env())
        assert result["decision"] == "block"
        assert "strategy_admission_outside_allowlist" in result["reason"]

    def test_sa_blocks_paper_broker(self):
        result = evaluate_event(_edit("app/execution/paper_broker.py"), _strategy_admission_env())
        assert result["decision"] == "block"
        assert "strategy_admission_outside_allowlist" in result["reason"]

    def test_sa_blocks_risk_state_json(self):
        result = evaluate_event(_edit("state/risk_state.json"), _strategy_admission_env())
        assert result["decision"] == "block"
        assert "strategy_admission_outside_allowlist" in result["reason"]

    def test_sa_blocks_reports(self):
        result = evaluate_event(_edit("reports/anything.txt"), _strategy_admission_env())
        assert result["decision"] == "block"
        assert "strategy_admission_outside_allowlist" in result["reason"]


# ---------------------------------------------------------------------------
# EXECUTION_SR_DECIMAL packet allowlist
# ---------------------------------------------------------------------------

class TestExecutionSRDecimalPacket:
    # --- Non-locked allowed paths ---

    def test_esr_allows_order_router(self):
        result = evaluate_event(_edit("app/execution/order_router.py"), _execution_sr_decimal_env())
        assert result["decision"] == "approve"

    def test_esr_allows_paper_broker(self):
        result = evaluate_event(_edit("app/execution/paper_broker.py"), _execution_sr_decimal_env())
        assert result["decision"] == "approve"

    def test_esr_allows_tests_prefix(self):
        result = evaluate_event(
            _edit("tests/test_execution_sr_decimal.py"),
            _execution_sr_decimal_env(),
        )
        assert result["decision"] == "approve"

    def test_esr_write_allowed_for_order_router(self):
        result = evaluate_event(_write("app/execution/order_router.py"), _execution_sr_decimal_env())
        assert result["decision"] == "approve"

    # --- Locked authority file with packet-scoped exception ---

    def test_esr_allows_engine(self):
        result = evaluate_event(_edit("app/execution/engine.py"), _execution_sr_decimal_env())
        assert result["decision"] == "approve"

    def test_esr_write_allowed_for_engine(self):
        result = evaluate_event(_write("app/execution/engine.py"), _execution_sr_decimal_env())
        assert result["decision"] == "approve"

    # --- Locked authority files NOT in exception list ---

    def test_esr_blocks_signal_fusion(self):
        result = evaluate_event(_edit("app/brain/signal_fusion.py"), _execution_sr_decimal_env())
        assert result["decision"] == "block"
        assert "locked_authority_file" in result["reason"]

    def test_esr_blocks_strategy_router(self):
        result = evaluate_event(_edit("app/strategies/strategy_router.py"), _execution_sr_decimal_env())
        assert result["decision"] == "block"
        assert "locked_authority_file" in result["reason"]

    def test_esr_blocks_decision_compiler(self):
        result = evaluate_event(_edit("app/core/decision_compiler.py"), _execution_sr_decimal_env())
        assert result["decision"] == "block"
        assert "locked_authority_file" in result["reason"]

    def test_esr_blocks_risk_guard(self):
        result = evaluate_event(_edit("app/risk/guard.py"), _execution_sr_decimal_env())
        assert result["decision"] == "block"
        assert "locked_authority_file" in result["reason"]

    def test_esr_blocks_shans_curve(self):
        result = evaluate_event(_edit("app/brain/shans_curve.py"), _execution_sr_decimal_env())
        assert result["decision"] == "block"
        assert "locked_authority_file" in result["reason"]

    # --- Outside allowlist, not locked ---

    def test_esr_blocks_main_loop(self):
        result = evaluate_event(_edit("app/main_loop.py"), _execution_sr_decimal_env())
        assert result["decision"] == "block"
        assert "execution_sr_decimal_outside_allowlist" in result["reason"]

    def test_esr_blocks_config(self):
        result = evaluate_event(_edit("app/config.py"), _execution_sr_decimal_env())
        assert result["decision"] == "block"
        assert "execution_sr_decimal_outside_allowlist" in result["reason"]

    def test_esr_blocks_symbol_runtime(self):
        result = evaluate_event(_edit("app/symbol_runtime.py"), _execution_sr_decimal_env())
        assert result["decision"] == "block"
        assert "execution_sr_decimal_outside_allowlist" in result["reason"]

    def test_esr_blocks_risk_state_json(self):
        result = evaluate_event(_edit("state/risk_state.json"), _execution_sr_decimal_env())
        assert result["decision"] == "block"
        assert "execution_sr_decimal_outside_allowlist" in result["reason"]


# ---------------------------------------------------------------------------
# REGIME_AWARE_SR_ADMISSION packet allowlist
# ---------------------------------------------------------------------------

class TestRegimeAwareSRAdmissionPacket:
    # --- Non-locked allowed paths ---

    def test_rasa_allows_config(self):
        result = evaluate_event(_edit("app/config.py"), _regime_aware_sr_admission_env())
        assert result["decision"] == "approve"

    def test_rasa_allows_tests_prefix(self):
        result = evaluate_event(
            _edit("tests/test_regime_aware_sr_admission.py"),
            _regime_aware_sr_admission_env(),
        )
        assert result["decision"] == "approve"

    def test_rasa_write_allowed_for_config(self):
        result = evaluate_event(_write("app/config.py"), _regime_aware_sr_admission_env())
        assert result["decision"] == "approve"

    # --- Locked authority file with packet-scoped exception ---

    def test_rasa_allows_signal_fusion(self):
        result = evaluate_event(_edit("app/brain/signal_fusion.py"), _regime_aware_sr_admission_env())
        assert result["decision"] == "approve"

    def test_rasa_write_allowed_for_signal_fusion(self):
        result = evaluate_event(_write("app/brain/signal_fusion.py"), _regime_aware_sr_admission_env())
        assert result["decision"] == "approve"

    # --- Locked authority files NOT in exception list ---

    def test_rasa_blocks_regime_detector(self):
        result = evaluate_event(_edit("app/brain/regime_detector.py"), _regime_aware_sr_admission_env())
        assert result["decision"] == "block"
        assert "locked_authority_file" in result["reason"]

    def test_rasa_blocks_shans_curve(self):
        result = evaluate_event(_edit("app/brain/shans_curve.py"), _regime_aware_sr_admission_env())
        assert result["decision"] == "block"
        assert "locked_authority_file" in result["reason"]

    def test_rasa_blocks_strategy_router(self):
        result = evaluate_event(_edit("app/strategies/strategy_router.py"), _regime_aware_sr_admission_env())
        assert result["decision"] == "block"
        assert "locked_authority_file" in result["reason"]

    def test_rasa_blocks_execution_engine(self):
        result = evaluate_event(_edit("app/execution/engine.py"), _regime_aware_sr_admission_env())
        assert result["decision"] == "block"
        assert "locked_authority_file" in result["reason"]

    def test_rasa_blocks_risk_guard(self):
        result = evaluate_event(_edit("app/risk/guard.py"), _regime_aware_sr_admission_env())
        assert result["decision"] == "block"
        assert "locked_authority_file" in result["reason"]

    def test_rasa_blocks_unified_risk(self):
        result = evaluate_event(_edit("app/risk/unified_risk.py"), _regime_aware_sr_admission_env())
        assert result["decision"] == "block"
        assert "locked_authority_file" in result["reason"]

    def test_rasa_blocks_decision_compiler(self):
        result = evaluate_event(_edit("app/core/decision_compiler.py"), _regime_aware_sr_admission_env())
        assert result["decision"] == "block"
        assert "locked_authority_file" in result["reason"]

    # --- Outside allowlist, not locked (explicitly blocked per G0.4) ---

    def test_rasa_blocks_main_loop(self):
        result = evaluate_event(_edit("app/main_loop.py"), _regime_aware_sr_admission_env())
        assert result["decision"] == "block"
        assert "regime_aware_sr_admission_outside_allowlist" in result["reason"]

    def test_rasa_blocks_sector_rotation(self):
        result = evaluate_event(_edit("app/strategies/sector_rotation.py"), _regime_aware_sr_admission_env())
        assert result["decision"] == "block"
        assert "regime_aware_sr_admission_outside_allowlist" in result["reason"]

    def test_rasa_blocks_models_signals(self):
        result = evaluate_event(_edit("app/models/signals.py"), _regime_aware_sr_admission_env())
        assert result["decision"] == "block"
        assert "regime_aware_sr_admission_outside_allowlist" in result["reason"]

    def test_rasa_blocks_order_router(self):
        result = evaluate_event(_edit("app/execution/order_router.py"), _regime_aware_sr_admission_env())
        assert result["decision"] == "block"
        assert "regime_aware_sr_admission_outside_allowlist" in result["reason"]

    def test_rasa_blocks_risk_state_json(self):
        result = evaluate_event(_edit("state/risk_state.json"), _regime_aware_sr_admission_env())
        assert result["decision"] == "block"
        assert "regime_aware_sr_admission_outside_allowlist" in result["reason"]


# ---------------------------------------------------------------------------
# Bash safety invariants
# ---------------------------------------------------------------------------

class TestBashSafety:
    def test_git_status_approved(self):
        result = evaluate_event(_bash("git status"), _g0_env())
        assert result["decision"] == "approve"

    def test_git_status_short_approved(self):
        result = evaluate_event(_bash("git status --short"), _g0_env())
        assert result["decision"] == "approve"

    def test_git_diff_approved(self):
        result = evaluate_event(_bash("git diff"), _g0_env())
        assert result["decision"] == "approve"

    def test_git_log_approved(self):
        result = evaluate_event(_bash("git log --oneline -10"), _g0_env())
        assert result["decision"] == "approve"

    def test_pytest_single_file_approved(self):
        result = evaluate_event(
            _bash("python -m pytest tests/test_g0_hook_verification.py -q"),
            _g0_env(),
        )
        assert result["decision"] == "approve"

    def test_pytest_shortform_approved(self):
        result = evaluate_event(
            _bash("pytest tests/test_g0_hook_verification.py -q"),
            _g0_env(),
        )
        assert result["decision"] == "approve"

    def test_py_compile_approved(self):
        result = evaluate_event(
            _bash("python -m py_compile app/main_loop.py"),
            _g0_env(),
        )
        assert result["decision"] == "approve"

    def test_rg_approved(self):
        result = evaluate_event(_bash("rg 'Decimal' app/"), _g0_env())
        assert result["decision"] == "approve"

    def test_echo_approved(self):
        result = evaluate_event(_bash("echo hello"), _g0_env())
        assert result["decision"] == "approve"

    # Dangerous patterns — must block regardless of override
    def test_live_flag_blocked(self):
        result = evaluate_event(_bash("python main.py --live"), _g0_env())
        assert result["decision"] == "block"
        assert "dangerous_bash" in result["reason"]

    def test_pip_install_blocked(self):
        result = evaluate_event(_bash("pip install numpy"), _g0_env())
        assert result["decision"] == "block"

    def test_pip_uninstall_blocked(self):
        result = evaluate_event(_bash("pip uninstall numpy"), _g0_env())
        assert result["decision"] == "block"

    def test_git_push_force_blocked(self):
        result = evaluate_event(_bash("git push --force origin master"), _g0_env())
        assert result["decision"] == "block"

    def test_git_reset_hard_blocked(self):
        result = evaluate_event(_bash("git reset --hard HEAD~1"), _g0_env())
        assert result["decision"] == "block"

    def test_rm_rf_blocked(self):
        result = evaluate_event(_bash("rm -rf /tmp/foo"), _g0_env())
        assert result["decision"] == "block"

    def test_broker_mode_live_blocked(self):
        result = evaluate_event(_bash("python main.py --broker_mode live"), _g0_env())
        assert result["decision"] == "block"

    def test_poverty_killer_live_env_blocked(self):
        result = evaluate_event(_bash("POVERTY_KILLER_LIVE=1 python main.py"), _g0_env())
        assert result["decision"] == "block"

    # Compound commands — must block
    def test_compound_and_blocked(self):
        result = evaluate_event(_bash("git status && git diff"), _g0_env())
        assert result["decision"] == "block"

    def test_compound_semicolon_blocked(self):
        result = evaluate_event(_bash("git status; git diff"), _g0_env())
        assert result["decision"] == "block"

    def test_compound_pipe_blocked(self):
        result = evaluate_event(_bash("git log | head -5"), _g0_env())
        assert result["decision"] == "block"

    def test_subshell_blocked(self):
        result = evaluate_event(_bash("echo $(git rev-parse HEAD)"), _g0_env())
        assert result["decision"] == "block"

    # Dangerous live mode cannot be unlocked by override
    def test_live_mode_blocked_even_with_valid_override(self):
        env = {
            "POVERTY_KILLER_PACKET": "G0",
            "POVERTY_KILLER_OVERRIDE": "true",
            "POVERTY_KILLER_OVERRIDE_REASON": "Board authorized live mode test for production deployment verification",
        }
        result = evaluate_event(_bash("python main.py --live"), env)
        assert result["decision"] == "block"
        assert "dangerous_bash" in result["reason"]

    # Unsafe shape without dangerous pattern
    def test_unknown_bash_shape_blocked(self):
        result = evaluate_event(_bash("python main.py --paper"), _g0_env())
        assert result["decision"] == "block"
        assert "bash_not_in_safe_shape_allowlist" in result["reason"]


# ---------------------------------------------------------------------------
# Unknown tool
# ---------------------------------------------------------------------------

class TestUnknownTool:
    def test_unknown_tool_blocked(self):
        event = {"tool_name": "SomeFutureTool", "tool_input": {}}
        result = evaluate_event(event, _g0_env())
        assert result["decision"] == "block"
        assert "unknown_tool" in result["reason"]

    def test_read_tool_blocked(self):
        # Read is not in the approved tool set for PreToolUse.
        event = {"tool_name": "Read", "tool_input": {"file_path": "app/main_loop.py"}}
        result = evaluate_event(event, _g0_env())
        assert result["decision"] == "block"


# ---------------------------------------------------------------------------
# Override invariants
# ---------------------------------------------------------------------------

class TestOverride:
    def test_valid_override_approves_g0_outside_allowlist(self):
        env = _override_env(
            "Board authorized emergency patch for main_loop seam repair — ticket PK-0042"
        )
        result = evaluate_event(_edit("app/main_loop.py"), env)
        assert result["decision"] == "approve"
        assert "override_active" in result["reason"]

    def test_invalid_override_short_reason_blocked(self):
        env = {
            "POVERTY_KILLER_PACKET": "G0",
            "POVERTY_KILLER_OVERRIDE": "true",
            "POVERTY_KILLER_OVERRIDE_REASON": "fix it",
        }
        result = evaluate_event(_edit("app/main_loop.py"), env)
        assert result["decision"] == "block"
        assert "override_rejected" in result["reason"]

    def test_override_reason_starts_with_test_blocked(self):
        env = {
            "POVERTY_KILLER_PACKET": "G0",
            "POVERTY_KILLER_OVERRIDE": "true",
            "POVERTY_KILLER_OVERRIDE_REASON": "testing override mechanism bypass for verification",
        }
        result = evaluate_event(_edit("app/main_loop.py"), env)
        assert result["decision"] == "block"
        assert "starts_with_test" in result["reason"]

    def test_override_missing_reason_blocked(self):
        env = {
            "POVERTY_KILLER_PACKET": "G0",
            "POVERTY_KILLER_OVERRIDE": "true",
        }
        result = evaluate_event(_edit("app/main_loop.py"), env)
        assert result["decision"] == "block"

    def test_override_blank_reason_blocked(self):
        env = {
            "POVERTY_KILLER_PACKET": "G0",
            "POVERTY_KILLER_OVERRIDE": "true",
            "POVERTY_KILLER_OVERRIDE_REASON": "   ",
        }
        result = evaluate_event(_edit("app/main_loop.py"), env)
        assert result["decision"] == "block"

    def test_override_false_still_uses_packet_rules(self):
        env = {
            "POVERTY_KILLER_PACKET": "G0",
            "POVERTY_KILLER_OVERRIDE": "false",
            "POVERTY_KILLER_OVERRIDE_REASON": "Board authorized emergency patch for testing",
        }
        result = evaluate_event(_edit("app/main_loop.py"), env)
        assert result["decision"] == "block"


# ---------------------------------------------------------------------------
# G0.6 Board Autopilot — safe GREEN commands and new dangerous RED/BLACK
# ---------------------------------------------------------------------------

def _proof_only_env() -> Dict[str, str]:
    return {"POVERTY_KILLER_PACKET": "SECTOR_ROTATION_FRESH_OBSERVED_PAIR_PROOF_BUNDLE"}


class TestG06BoardAutopilot:
    # --- Safe GREEN commands (tests 1-10) ---

    def test_git_status_short_green(self):
        # test 1: safe git status
        result = evaluate_event(_bash("git status --short"), _g0_env())
        assert result["decision"] == "approve"

    def test_git_log_green(self):
        # test 2: safe git log
        result = evaluate_event(_bash("git log --oneline -10"), _g0_env())
        assert result["decision"] == "approve"

    def test_git_diff_green(self):
        # test 3: safe git diff
        result = evaluate_event(_bash("git diff"), _g0_env())
        assert result["decision"] == "approve"

    def test_git_diff_cached_stat_green(self):
        # test 4: git diff --cached --stat
        result = evaluate_event(_bash("git diff --cached --stat"), _g0_env())
        assert result["decision"] == "approve"

    def test_git_diff_cached_name_only_green(self):
        # test 5: git diff --cached --name-only
        result = evaluate_event(_bash("git diff --cached --name-only"), _g0_env())
        assert result["decision"] == "approve"

    def test_targeted_pytest_green(self):
        # test 6: targeted pytest
        result = evaluate_event(
            _bash("python -m pytest tests/test_g0_hook_verification.py -q"),
            _g0_env(),
        )
        assert result["decision"] == "approve"

    def test_select_string_reports_log_green(self):
        # test 7: Select-String for report/log files
        result = evaluate_event(
            _bash("Select-String 'SIGNAL_PRODUCED' reports/paper_run.log"),
            _g0_env(),
        )
        assert result["decision"] == "approve"

    def test_get_content_in_repo_non_secret_green(self):
        # test 8: Get-Content for non-secret in-repo file
        result = evaluate_event(
            _bash("Get-Content .claude/settings.json"),
            _g0_env(),
        )
        assert result["decision"] == "approve"

    def test_python_py_compile_syntax_green(self):
        # test 9: Python syntax check (py_compile)
        result = evaluate_event(
            _bash("python -m py_compile tests/test_g0_hook_verification.py"),
            _g0_env(),
        )
        assert result["decision"] == "approve"

    def test_python_c_safe_string_green(self):
        # test 10: python -c with safe single-line string (no compound separators)
        result = evaluate_event(
            _bash('python -c "print(True)"'),
            _g0_env(),
        )
        assert result["decision"] == "approve"

    # --- Dangerous RED/BLACK commands (tests 11-20) ---

    def test_git_add_dot_blocked(self):
        # test 11: git add . is BLACK — always blocked
        result = evaluate_event(_bash("git add ."), _g0_env())
        assert result["decision"] == "block"
        assert "dangerous_bash" in result["reason"]

    def test_git_push_blocked(self):
        # test 12: git push (all forms) is RED — always blocked
        result = evaluate_event(_bash("git push origin master"), _g0_env())
        assert result["decision"] == "block"
        assert "dangerous_bash" in result["reason"]

    def test_git_reset_blocked(self):
        # test 13: git reset (all forms) is RED — always blocked
        result = evaluate_event(_bash("git reset HEAD~1"), _g0_env())
        assert result["decision"] == "block"
        assert "dangerous_bash" in result["reason"]

    def test_git_clean_blocked(self):
        # test 14: git clean is RED — always blocked
        result = evaluate_event(_bash("git clean -fd"), _g0_env())
        assert result["decision"] == "block"
        assert "dangerous_bash" in result["reason"]

    def test_live_mode_flag_blocked(self):
        # test 15: live mode command blocked
        result = evaluate_event(_bash("python main.py --live"), _g0_env())
        assert result["decision"] == "block"
        assert "dangerous_bash" in result["reason"]

    def test_override_env_shell_command_blocked(self):
        # test 16: POVERTY_KILLER_OVERRIDE=true via shell is BLACK
        result = evaluate_event(
            _bash("POVERTY_KILLER_OVERRIDE=true python main.py"),
            _g0_env(),
        )
        assert result["decision"] == "block"
        assert "dangerous_bash" in result["reason"]

    def test_npm_install_blocked(self):
        # test 17: dependency install blocked
        result = evaluate_event(_bash("npm install"), _g0_env())
        assert result["decision"] == "block"
        assert "dangerous_bash" in result["reason"]

    def test_remove_item_blocked(self):
        # test 18: Remove-Item (any form) is RED — blocked
        result = evaluate_event(_bash("Remove-Item state/risk_state.json"), _g0_env())
        assert result["decision"] == "block"
        assert "dangerous_bash" in result["reason"]

    def test_get_content_env_blocked(self):
        # test 19: Get-Content .env must be blocked (secrets access)
        result = evaluate_event(_bash("Get-Content .env"), _g0_env())
        assert result["decision"] == "block"
        assert "dangerous_bash" in result["reason"]

    def test_mixed_safe_and_dangerous_blocked(self):
        # test 20: compound command containing safe + dangerous phrase — must block
        result = evaluate_event(_bash("git diff; git push"), _g0_env())
        assert result["decision"] == "block"

    # --- Packet boundary enforcement (tests 21-22) ---

    def test_production_file_blocked_under_proof_only_packet(self):
        # test 21: app/ production file still blocked under proof-only packet
        result = evaluate_event(_edit("app/main_loop.py"), _proof_only_env())
        assert result["decision"] == "block"

    def test_tests_prefix_allowed_under_proof_only_packet(self):
        # test 22: tests/ prefix still allowed under proof-only packet
        result = evaluate_event(
            _edit("tests/test_fresh_observed_pair.py"),
            _proof_only_env(),
        )
        assert result["decision"] == "approve"


# ---------------------------------------------------------------------------
# PAPER_FILL_COMPLETION_PROOF_BUNDLE packet allowlist
# ---------------------------------------------------------------------------

def _paper_fill_env() -> Dict[str, str]:
    return {"POVERTY_KILLER_PACKET": "PAPER_FILL_COMPLETION_PROOF_BUNDLE"}


class TestPaperFillCompletionProofBundle:
    # test 1: allows app/execution/paper_broker.py
    def test_pfcp_allows_paper_broker(self):
        result = evaluate_event(_edit("app/execution/paper_broker.py"), _paper_fill_env())
        assert result["decision"] == "approve"

    # test 2: allows app/execution/order_router.py
    def test_pfcp_allows_order_router(self):
        result = evaluate_event(_edit("app/execution/order_router.py"), _paper_fill_env())
        assert result["decision"] == "approve"

    # test 3: allows app/execution/engine.py (locked authority, packet-scoped exception)
    def test_pfcp_allows_engine_locked_exception(self):
        result = evaluate_event(_edit("app/execution/engine.py"), _paper_fill_env())
        assert result["decision"] == "approve"

    # test 4: allows tests/ prefix
    def test_pfcp_allows_tests_prefix(self):
        result = evaluate_event(
            _edit("tests/test_paper_fill_completion.py"),
            _paper_fill_env(),
        )
        assert result["decision"] == "approve"

    # test 5: blocks app/strategies/*
    def test_pfcp_blocks_strategies(self):
        result = evaluate_event(_edit("app/strategies/sector_rotation.py"), _paper_fill_env())
        assert result["decision"] == "block"
        assert "paper_fill_completion_proof_bundle_outside_allowlist" in result["reason"]

    # test 6: blocks app/brain/* (locked authority file)
    def test_pfcp_blocks_brain(self):
        result = evaluate_event(_edit("app/brain/signal_fusion.py"), _paper_fill_env())
        assert result["decision"] == "block"
        assert "locked_authority_file" in result["reason"]

    # test 7: blocks app/risk/* (locked authority file)
    def test_pfcp_blocks_risk(self):
        result = evaluate_event(_edit("app/risk/guard.py"), _paper_fill_env())
        assert result["decision"] == "block"
        assert "locked_authority_file" in result["reason"]

    # test 8: blocks app/core/* (locked authority file)
    def test_pfcp_blocks_core(self):
        result = evaluate_event(_edit("app/core/decision_compiler.py"), _paper_fill_env())
        assert result["decision"] == "block"
        assert "locked_authority_file" in result["reason"]

    # test 9: blocks docs/CURRENT_STATUS.md during active packet
    def test_pfcp_blocks_current_status(self):
        result = evaluate_event(_edit("docs/CURRENT_STATUS.md"), _paper_fill_env())
        assert result["decision"] == "block"
        assert "paper_fill_completion_proof_bundle_outside_allowlist" in result["reason"]

    # test 10: dangerous Bash rules unchanged under this packet
    def test_pfcp_dangerous_bash_still_blocked(self):
        result = evaluate_event(_bash("git push origin master"), _paper_fill_env())
        assert result["decision"] == "block"
        assert "dangerous_bash" in result["reason"]
