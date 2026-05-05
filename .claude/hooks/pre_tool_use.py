#!/usr/bin/env python3
"""
G0 PreToolUse hook for POVERTY_KILLER Claude Terminal.

Reads Claude Code hook JSON from stdin, decides allow/block based on:
- packet-scoped allowlists (POVERTY_KILLER_PACKET=G0|F4A|F4B|F4C|STRATEGY_ADMISSION|EXECUTION_SR_DECIMAL|REGIME_AWARE_SR_ADMISSION)
- locked-authority file blocklist
- override authorization (POVERTY_KILLER_OVERRIDE=true with valid REASON)
- dangerous Bash command patterns (live mode, dependency mods, dangerous git/delete)
- safe Bash command shapes (read-only allowlist)

Hard rules:
- BLOCK BY DEFAULT on parse failure or empty stdin.
- Dangerous Bash patterns checked BEFORE safe patterns.
- Safe-substring is not enough; the whole command must match a safe shape.

Override events log to state/override_log.jsonl. Hook never modifies bot source.

Exit code 0 with stdout JSON {"decision": "block"|"approve", "reason": "..."} is
how Claude Code consumes the hook decision. The hook also exits non-zero on
block when feasible, but emits valid JSON either way so Claude Code doesn't
fail-open silently.

Test mode:
- evaluate_event(event_dict, env=None) -> dict can be called from
  tests/test_g0_hook_verification.py without spawning a subprocess.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


# ---------------------------------------------------------------------------
# Repo root resolution
# ---------------------------------------------------------------------------

_THIS = Path(__file__).resolve()
REPO_ROOT = _THIS.parent.parent.parent  # .claude/hooks/pre_tool_use.py -> repo root


# ---------------------------------------------------------------------------
# Allowlists / blocklists (paths use forward slashes, lowercase, repo-relative)
# ---------------------------------------------------------------------------

LOCKED_AUTHORITY_FILES = frozenset(
    p.lower() for p in [
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
)

G0_ALLOWLIST = frozenset(
    p.lower() for p in [
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
        "docs/execution_plan.md",
        "docs/cross_asset_reference_scan.md",
        "docs/packets/f4a_decimal.md",
        "docs/packets/f4b_sentiment.md",
        "docs/packets/f4c_risk_state.md",
        "docs/packets/execution_sr_decimal.md",
        "docs/packets/regime_aware_sr_admission.md",
        "tests/test_g0_hook_verification.py",
        "state/override_log.jsonl",
        "state/session_journal.jsonl",
    ]
)

# F4A allowlist — exact files + tests/ prefix.
F4A_ALLOWED_FILES = frozenset(
    p.lower() for p in [
        "app/execution/engine.py",
        "app/execution/order_router.py",
        "app/execution/paper_broker.py",
        "app/utils/decimal_utils.py",
    ]
)
F4A_ALLOWED_PREFIXES = ("tests/",)

# F4B allowlist.
F4B_ALLOWED_FILES = frozenset(
    p.lower() for p in [
        "app/brain/sentiment_velocity.py",
        "app/symbol_runtime.py",
    ]
)
F4B_ALLOWED_PREFIXES = ("tests/",)

# F4C allowlist.
F4C_ALLOWED_FILES = frozenset(
    p.lower() for p in [
        "app/risk/guard.py",
        "app/risk/unified_risk.py",
    ]
)
F4C_ALLOWED_PREFIXES = ("tests/",)

# STRATEGY_ADMISSION allowlist.
STRATEGY_ADMISSION_ALLOWED_FILES = frozenset(
    p.lower() for p in [
        "app/strategies/shadow_front.py",
        "app/strategies/sector_rotation.py",
        "app/config.py",
        "app/models/signals.py",
    ]
)
STRATEGY_ADMISSION_ALLOWED_PREFIXES = ("tests/",)

# EXECUTION_SR_DECIMAL allowlist — signal-routing Decimal discipline, execution layer only.
EXECUTION_SR_DECIMAL_ALLOWED_FILES = frozenset(
    p.lower() for p in [
        "app/execution/order_router.py",
        "app/execution/paper_broker.py",
    ]
)
EXECUTION_SR_DECIMAL_LOCKED_ALLOWED_FILES = frozenset(
    p.lower() for p in [
        "app/execution/engine.py",
    ]
)
EXECUTION_SR_DECIMAL_ALLOWED_PREFIXES = ("tests/",)

# REGIME_AWARE_SR_ADMISSION allowlist — regime-conditioned SR eligibility, opt-in proof-only.
REGIME_AWARE_SR_ADMISSION_ALLOWED_FILES = frozenset(
    p.lower() for p in [
        "app/config.py",
    ]
)
REGIME_AWARE_SR_ADMISSION_LOCKED_ALLOWED_FILES = frozenset(
    p.lower() for p in [
        "app/brain/signal_fusion.py",
    ]
)
REGIME_AWARE_SR_ADMISSION_ALLOWED_PREFIXES = ("tests/",)


# ---------------------------------------------------------------------------
# Path normalization
# ---------------------------------------------------------------------------

def normalize_path(raw: str) -> str:
    """
    Windows-aware path normalization. Returns repo-relative lowercase
    forward-slash path when possible; otherwise returns the lowercased
    forward-slash form of the input.
    """
    if not isinstance(raw, str) or not raw:
        return ""
    s = raw.replace("\\", "/").strip()
    s_lower = s.lower()
    repo_root_lower = str(REPO_ROOT).replace("\\", "/").lower().rstrip("/")
    if repo_root_lower and s_lower.startswith(repo_root_lower + "/"):
        return s_lower[len(repo_root_lower) + 1:]
    # Drop leading "./"
    if s_lower.startswith("./"):
        return s_lower[2:]
    return s_lower


# ---------------------------------------------------------------------------
# Override-reason validation
# ---------------------------------------------------------------------------

_OVERRIDE_REASON_TEST_PATTERN = re.compile(r"^test", re.IGNORECASE)


def is_valid_override_reason(reason: Optional[str]) -> Tuple[bool, str]:
    """Returns (ok, reason_for_failure_if_not_ok)."""
    if reason is None:
        return False, "missing"
    if not isinstance(reason, str):
        return False, "not_string"
    stripped = reason.strip()
    if not stripped:
        return False, "blank_or_whitespace_only"
    non_ws_count = len(re.sub(r"\s", "", reason))
    if non_ws_count < 20:
        return False, f"too_short_non_whitespace_{non_ws_count}"
    if _OVERRIDE_REASON_TEST_PATTERN.match(stripped):
        return False, "starts_with_test"
    return True, ""


def log_override_attempt(env: Dict[str, str], event: Dict[str, Any], decision: str, detail: str) -> None:
    """Append override decision (success or failure) to state/override_log.jsonl."""
    record = {
        "ts": int(time.time()),
        "event_tool": event.get("tool_name", "<unknown>"),
        "decision": decision,
        "detail": detail,
        "override_flag": env.get("POVERTY_KILLER_OVERRIDE", ""),
        "packet": env.get("POVERTY_KILLER_PACKET", ""),
        "reason_present": bool(env.get("POVERTY_KILLER_OVERRIDE_REASON", "").strip()),
    }
    log_path = REPO_ROOT / "state" / "override_log.jsonl"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        # Hook must never crash on logging issues; fail open on the log step
        # but the decision itself stands.
        pass


# ---------------------------------------------------------------------------
# Bash command rules
# ---------------------------------------------------------------------------

_DANGEROUS_BASH_PATTERNS = [
    # Live-mode patterns (all word/CLI-style)
    re.compile(r"--live\b", re.IGNORECASE),
    re.compile(r"--broker[-_]mode\s+live\b", re.IGNORECASE),
    re.compile(r"\bbroker[_-]mode\s*=\s*live\b", re.IGNORECASE),
    re.compile(r"\bBROKER_MODE\s*=\s*live\b"),
    re.compile(r"\bPOVERTY_KILLER_LIVE\b"),
    re.compile(r"\bkraken[-_]live\b", re.IGNORECASE),
    re.compile(r"\balpaca[-_]live\b", re.IGNORECASE),
    # Dependency modification
    re.compile(r"\bpip\s+install\b", re.IGNORECASE),
    re.compile(r"\bpip\s+uninstall\b", re.IGNORECASE),
    re.compile(r"\bpip3\s+install\b", re.IGNORECASE),
    re.compile(r"\bpoetry\s+add\b", re.IGNORECASE),
    re.compile(r"\bpoetry\s+remove\b", re.IGNORECASE),
    re.compile(r"\bconda\s+install\b", re.IGNORECASE),
    re.compile(r"\bconda\s+remove\b", re.IGNORECASE),
    # Dangerous git
    re.compile(r"\bgit\s+push\s+(--force|-f)\b", re.IGNORECASE),
    re.compile(r"\bgit\s+reset\s+--hard\b", re.IGNORECASE),
    # Destructive deletes
    re.compile(r"\brm\s+-rf\b"),
    re.compile(r"\bRemove-Item\b.*-Recurse\b.*-Force\b", re.IGNORECASE),
    re.compile(r"\bdel\s+/s\b", re.IGNORECASE),
    re.compile(r"\bRemove-Item\b.*-Force\b.*-Recurse\b", re.IGNORECASE),
]

_DANGEROUS_FILE_TARGETS = [
    re.compile(r"\brequirements\.txt\b", re.IGNORECASE),
    re.compile(r"\bpyproject\.toml\b", re.IGNORECASE),
]

# Safe Bash shapes (anchored).
_SAFE_BASH_SHAPES = [
    re.compile(r"^\s*git\s+status(\s+--short)?\s*$"),
    re.compile(r"^\s*git\s+diff(\s+[^&;|`$]+)?\s*$"),
    re.compile(r"^\s*git\s+log(\s+[^&;|`$]+)?\s*$"),
    re.compile(r"^\s*rg\s+[^;|&`$]+\s*$"),
    re.compile(r"^\s*grep\s+[^;|&`$]+\s*$"),
    re.compile(r"^\s*Select-String\s+[^;|&`$]+\s*$"),
    re.compile(r"^\s*Get-Content\s+[^;|&`$]+\s*$"),
    re.compile(r"^\s*Get-ChildItem(\s+[^;|&`$]+)?\s*$"),
    re.compile(r"^\s*python\s+-m\s+py_compile\s+[^;|&`$]+\s*$"),
    re.compile(r"^\s*python\s+-m\s+pytest\s+tests/[A-Za-z0-9_./-]+\.py(\s+-q)?\s*$"),
    re.compile(r"^\s*pytest\s+tests/[A-Za-z0-9_./-]+\.py(\s+-q)?\s*$"),
    re.compile(r"^\s*echo\s+[^;|&`$]+\s*$"),
]

# Compound separators that must trip an unsafe-shape rejection unless the
# entire compound is itself proven safe (we don't try to prove that here;
# any compound with a separator is treated as not matching a safe shape).
_COMPOUND_SEPARATOR_RE = re.compile(r"[;&|`$]|\$\(")


def is_dangerous_bash(command: str) -> Tuple[bool, str]:
    if not isinstance(command, str):
        return True, "non_string_command"
    for pat in _DANGEROUS_BASH_PATTERNS:
        if pat.search(command):
            return True, f"dangerous_pattern:{pat.pattern}"
    # Block edits to dependency manifests via shell shell-out (cat/echo > requirements.txt etc.)
    for pat in _DANGEROUS_FILE_TARGETS:
        if pat.search(command):
            # Only block if combined with a write-redirect or modification verb;
            # plain reads (cat requirements.txt) are not blocked here.
            if re.search(r"(>|>>|sed\s+-i|tee\s+|awk\s+.*>)", command):
                return True, f"dependency_manifest_write:{pat.pattern}"
    return False, ""


def is_safe_bash_shape(command: str) -> bool:
    if not isinstance(command, str):
        return False
    if _COMPOUND_SEPARATOR_RE.search(command):
        return False
    for pat in _SAFE_BASH_SHAPES:
        if pat.match(command):
            return True
    return False


# ---------------------------------------------------------------------------
# Packet allowlist routing
# ---------------------------------------------------------------------------

def packet_allows_path(packet: str, normalized_path: str) -> Tuple[bool, str]:
    """Returns (allowed, reason_if_blocked)."""
    if not normalized_path:
        return False, "empty_path"
    if normalized_path in LOCKED_AUTHORITY_FILES:
        # Locked files require packet-scoped exception.
        if packet == "F4A" and normalized_path in F4A_ALLOWED_FILES:
            return True, ""
        if packet == "F4B" and normalized_path in F4B_ALLOWED_FILES:
            return True, ""
        if packet == "F4C" and normalized_path in F4C_ALLOWED_FILES:
            return True, ""
        if packet == "EXECUTION_SR_DECIMAL" and normalized_path in EXECUTION_SR_DECIMAL_LOCKED_ALLOWED_FILES:
            return True, ""
        if packet == "REGIME_AWARE_SR_ADMISSION" and normalized_path in REGIME_AWARE_SR_ADMISSION_LOCKED_ALLOWED_FILES:
            return True, ""
        return False, f"locked_authority_file_outside_packet_exception:{normalized_path}"
    if packet == "G0":
        if normalized_path in G0_ALLOWLIST:
            return True, ""
        return False, f"g0_outside_allowlist:{normalized_path}"
    if packet == "F4A":
        if normalized_path in F4A_ALLOWED_FILES:
            return True, ""
        if any(normalized_path.startswith(pre) for pre in F4A_ALLOWED_PREFIXES):
            return True, ""
        return False, f"f4a_outside_allowlist:{normalized_path}"
    if packet == "F4B":
        if normalized_path in F4B_ALLOWED_FILES:
            return True, ""
        if any(normalized_path.startswith(pre) for pre in F4B_ALLOWED_PREFIXES):
            return True, ""
        return False, f"f4b_outside_allowlist:{normalized_path}"
    if packet == "F4C":
        if normalized_path in F4C_ALLOWED_FILES:
            return True, ""
        if any(normalized_path.startswith(pre) for pre in F4C_ALLOWED_PREFIXES):
            return True, ""
        return False, f"f4c_outside_allowlist:{normalized_path}"
    if packet == "STRATEGY_ADMISSION":
        if normalized_path in STRATEGY_ADMISSION_ALLOWED_FILES:
            return True, ""
        if any(normalized_path.startswith(pre) for pre in STRATEGY_ADMISSION_ALLOWED_PREFIXES):
            return True, ""
        return False, f"strategy_admission_outside_allowlist:{normalized_path}"
    if packet == "EXECUTION_SR_DECIMAL":
        if normalized_path in EXECUTION_SR_DECIMAL_ALLOWED_FILES:
            return True, ""
        if any(normalized_path.startswith(pre) for pre in EXECUTION_SR_DECIMAL_ALLOWED_PREFIXES):
            return True, ""
        return False, f"execution_sr_decimal_outside_allowlist:{normalized_path}"
    if packet == "REGIME_AWARE_SR_ADMISSION":
        if normalized_path in REGIME_AWARE_SR_ADMISSION_ALLOWED_FILES:
            return True, ""
        if any(normalized_path.startswith(pre) for pre in REGIME_AWARE_SR_ADMISSION_ALLOWED_PREFIXES):
            return True, ""
        return False, f"regime_aware_sr_admission_outside_allowlist:{normalized_path}"
    return False, f"no_active_packet_or_unknown_packet:{packet!r}"


# ---------------------------------------------------------------------------
# Decision core
# ---------------------------------------------------------------------------

def make_decision(decision: str, reason: str) -> Dict[str, Any]:
    return {"decision": decision, "reason": reason}


def evaluate_event(event: Dict[str, Any], env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """
    Pure function: takes the parsed Claude Code hook event JSON + env dict and
    returns a decision dict. Used by tests to drive the hook without subprocess.
    """
    if env is None:
        env = dict(os.environ)
    if not isinstance(event, dict):
        log_override_attempt(env, {}, "block", "HOOK_PARSE_FAILURE:event_not_dict")
        return make_decision("block", "HOOK_PARSE_FAILURE:event_not_dict")

    tool_name = event.get("tool_name") or event.get("tool") or ""
    tool_input = event.get("tool_input") or event.get("toolInput") or {}
    if not isinstance(tool_input, dict):
        return make_decision("block", "HOOK_PARSE_FAILURE:tool_input_not_dict")

    packet = (env.get("POVERTY_KILLER_PACKET") or "").strip()
    override_flag = (env.get("POVERTY_KILLER_OVERRIDE") or "").strip().lower() == "true"
    override_reason = env.get("POVERTY_KILLER_OVERRIDE_REASON") or ""

    # Override evaluated first; if invalid override is requested, reject hard.
    override_active = False
    if override_flag:
        ok, fail_reason = is_valid_override_reason(override_reason)
        if not ok:
            log_override_attempt(env, event, "block", f"override_rejected:{fail_reason}")
            return make_decision("block", f"override_rejected:{fail_reason}")
        log_override_attempt(env, event, "approve", "override_accepted")
        override_active = True

    if tool_name in ("Edit", "Write", "MultiEdit"):
        # Extract path
        raw_path = tool_input.get("file_path") or tool_input.get("filePath") or ""
        normalized = normalize_path(raw_path)
        if override_active:
            return make_decision("approve", f"override_active:{normalized}")
        ok, why = packet_allows_path(packet, normalized)
        if ok:
            return make_decision("approve", f"packet_allows:{packet}:{normalized}")
        return make_decision("block", why)

    if tool_name == "Bash":
        cmd = tool_input.get("command") or ""
        # Dangerous patterns FIRST, even with override (live mode and dependency
        # mods are not unlockable via override per packet doctrine).
        dangerous, why = is_dangerous_bash(cmd)
        if dangerous:
            return make_decision("block", f"dangerous_bash:{why}")
        if override_active:
            return make_decision("approve", "override_active:bash")
        if is_safe_bash_shape(cmd):
            return make_decision("approve", f"safe_bash_shape:{cmd[:80]}")
        return make_decision("block", "bash_not_in_safe_shape_allowlist")

    # Unknown tool: default-block to be safe. PostToolUse hook is registered
    # separately; PreToolUse should not see it.
    return make_decision("block", f"unknown_tool:{tool_name!r}")


def main(argv: Optional[list] = None) -> int:
    raw = sys.stdin.read()
    if not raw or not raw.strip():
        log_override_attempt(dict(os.environ), {}, "block", "HOOK_PARSE_FAILURE:empty_stdin")
        decision = make_decision("block", "HOOK_PARSE_FAILURE:empty_stdin")
        print(json.dumps(decision))
        return 2
    try:
        event = json.loads(raw)
    except Exception as exc:
        log_override_attempt(dict(os.environ), {}, "block", f"HOOK_PARSE_FAILURE:{type(exc).__name__}")
        decision = make_decision("block", f"HOOK_PARSE_FAILURE:{type(exc).__name__}")
        print(json.dumps(decision))
        return 2
    decision = evaluate_event(event, dict(os.environ))
    print(json.dumps(decision))
    if decision.get("decision") == "block":
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
