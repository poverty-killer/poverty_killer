# EXECUTION_PLAN - poverty_killer Bundle Sequence

## Status key

COMPLETE / ACTIVE / PENDING / BLOCKED / BOARD_ESCALATED

---

## G0 - Governance Layer

Status: COMPLETE

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
Commit: b9579e2 — Add G0 Claude governance guardrails
Result: Hook verification test passing.

---

## G0.1 — Bounded Read-Only Evidence Extraction Rule

Status: ACTIVE (installed post-F4 paper proof)

Problem observed:
During post-F4 paper-proof evidence extraction, safe read-only evidence gathering
caused excessive repeated approval prompts. This slowed execution without improving
safety because the commands were only reading explicit proof logs and counting known
acceptance patterns.

Rule:
For bounded post-run evidence extraction, Claude may proceed without repeated Board
stops when ALL of the following conditions are true:

- The packet or Board instruction explicitly lists the allowed file paths.
- Commands are read-only.
- Commands only use: Get-Content, Get-Item, Select-String, simple counts, summary printing.
- Commands only read approved proof/report/log files.
- Commands do not patch source files.
- Commands do not patch docs.
- Commands do not patch tests.
- Commands do not run main.py.
- Commands do not start paper mode again.
- Commands do not start live mode.
- Commands do not modify state files.
- Commands do not delete files.
- Commands do not use git write commands.
- Commands do not alter acceptance criteria.

Stop conditions (Claude must still stop for Board review if any command):
- Edits files.
- Writes files other than a pre-authorized summary artifact.
- Runs the bot.
- Runs live mode.
- Starts another paper proof.
- Touches state files.
- Uses git add, commit, reset, checkout, clean, restore, or other git write commands.
- Deletes files.
- Changes acceptance criteria.
- Reads outside the explicitly authorized evidence files.

Purpose:
Preserves strict governance while eliminating low-value repeated approvals for safe,
bounded, read-only evidence extraction.

---

## F4A - Execution Decimal Discipline

Status: COMPLETE

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
Commit: 5bc4f08 — Fix F4A Decimal discipline in execution path
Result: Decimal conversion blocker closed.

---

## F4B - Sentiment Velocity Concurrency

Status: COMPLETE

Objective:
Repair or verify thread-safety and concurrency discipline in sentiment
velocity and symbol runtime. Confirm no shared mutable state races.

Files in scope:
- app/brain/sentiment_velocity.py
- app/symbol_runtime.py
- tests/ (new concurrency tests)

Acceptance: no concurrency violations found; liveness confirmed REAL.
Commit: beeb2a8 — Fix F4B sentiment velocity concurrency
Result: SentimentVelocity/deque mutation blocker closed.

---

## F4C - Risk State Persistence

Status: COMPLETE

Objective:
Verify atomic write path for risk state. Confirm backup/restore logic.
Confirm ATOMIC_WRITE_FAILED and RESTORED_FROM_BACKUP counters are reachable
and correctly logged.

Files in scope:
- app/risk/guard.py
- app/risk/unified_risk.py
- tests/ (new persistence tests)

Acceptance: atomic write and restore paths exercised in test; counters observed.
Commit: 398a859 — Fix F4C risk state persistence counters
Result: risk-state persistence counters instrumented and tested.

---

## Post-F4C — Controlled Paper Proof

Status: PASS

Proof files:
- reports/paper_run_f4c_20260504_140312.stdout.log
- reports/paper_run_f4c_20260504_140312.summary.txt

Acceptance result: PASS — 7/7 criteria met

Evidence counters:
- DECIMAL_CONVERSION_ERRORS=0
- DEQUE_MUTATION_ERRORS=0
- TRACEBACK_COUNT=0
- ATOMIC_WRITE_FAILED_LINES=0
- ATOMIC_WRITE_TRANSIENT_LINES=0
- RESTORED_FROM_BACKUP_LINES=0
- PRICE_MOVED_REJECT_LINES=0
- CACHE_WARNING_LINES=0

Runtime evidence:
- Paper mode confirmed.
- Live keys not detected.
- Shans spine produced ETH/USD signal within the controlled run.
- ETH/USD: SIGNAL_PRODUCED / SHANS_RESULT / FUSION_UPDATE_CALLED confirmed.
- Duration: approximately 113 seconds.

Next packet candidates (to be defined by Board):
- Signal fusion wiring verification (SIGNAL_SUBMITTED, PAPERBROKER_REACH_COUNT,
  PAPER_FILL_COUNT, strategy router admission, decision compiler handoff,
  paper broker reachability).
- Strategy router liveness audit.
- Sizing authority confirmation.
- Telemetry completeness.

---

## Deferred Items

### ORPHANED_TMP_FILES

Status: DEFERRED — future packet

Finding:
Three orphaned .tmp files remain in state/ from prior crashed processes.

Scope needed:
app/risk/guard.py startup cleanup only, with tests.

Do not patch until a dedicated packet is authorized.

---

### SIGNAL FUSION WIRING VERIFICATION

Status: DEFERRED — recommended next packet

Finding:
Post-F4 paper proof confirmed Shans signal production and fusion update call.
Next proof target is the full signal-to-order path.

Scope needed:
Verify SIGNAL_SUBMITTED, PAPERBROKER_REACH_COUNT, PAPER_FILL_COUNT,
strategy router admission, decision compiler handoff, and paper broker reachability.

Do not patch until a dedicated packet is authorized.

---

### TELEMETRY COMPLETENESS

Status: DEFERRED — future proof

Finding:
Future proof should confirm telemetry coverage across the full decision path.

Do not patch until a dedicated packet is authorized.
