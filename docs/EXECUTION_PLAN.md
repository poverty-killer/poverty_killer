# EXECUTION_PLAN - poverty_killer Bundle Sequence

## Status key

COMPLETE / ACTIVE / PENDING / BLOCKED / BOARD_ESCALATED

---

## G0 - Governance Layer

Status: ACTIVE

Objective:
Install hook governance, packet allowlist enforcement, slash-command templates,
docs skeleton, and mandatory hook verification test. No runtime bot edits.

Deliverables:
- .claude/hooks/pre_tool_use.py
- .claude/hooks/post_tool_use.py
- .claude/settings.json
- .claude/commands/paper-proof.md
- .claude/commands/packet.md
- .claude/commands/check-spine.md
- .claude/commands/decimal-scan.md
- .claude/commands/audit.md
- docs/EXECUTION_PLAN.md
- docs/cross_asset_reference_scan.md
- docs/packets/f4a_decimal.md
- docs/packets/f4b_sentiment.md
- docs/packets/f4c_risk_state.md
- tests/test_g0_hook_verification.py
- claude.md governance addendum
- state/override_log.jsonl
- state/session_journal.jsonl

Acceptance: test_g0_hook_verification.py passes with zero failures.

---

## F4A - Execution Decimal Discipline

Status: PENDING (requires G0 COMPLETE)

Objective:
Eliminate float usage in execution, order routing, and paper broker paths.
All price, quantity, notional, and fee fields must use Decimal with string
construction. No Decimal-from-float.

Files in scope:
- app/execution/engine.py
- app/execution/order_router.py
- app/execution/paper_broker.py
- app/utils/decimal_utils.py
- tests/ (new decimal discipline tests)

Acceptance: /decimal-scan returns CLEAN on all F4A files.

---

## F4B - Sentiment Velocity Concurrency

Status: PENDING (requires F4A COMPLETE)

Objective:
Repair or verify thread-safety and concurrency discipline in sentiment
velocity and symbol runtime. Confirm no shared mutable state races.

Files in scope:
- app/brain/sentiment_velocity.py
- app/symbol_runtime.py
- tests/ (new concurrency tests)

Acceptance: no concurrency violations found; liveness confirmed REAL.

---

## F4C - Risk State Persistence

Status: PENDING (requires F4B COMPLETE)

Objective:
Verify atomic write path for risk state. Confirm backup/restore logic.
Confirm ATOMIC_WRITE_FAILED and RESTORED_FROM_BACKUP counters are reachable
and correctly logged.

Files in scope:
- app/risk/guard.py
- app/risk/unified_risk.py
- tests/ (new persistence tests)

Acceptance: atomic write and restore paths exercised in test; counters observed.

---

## Post-F4C

Status: PENDING

To be defined by Board after F4C acceptance.
Candidates: signal fusion wiring verification, strategy router liveness audit,
sizing authority confirmation, telemetry completeness.
