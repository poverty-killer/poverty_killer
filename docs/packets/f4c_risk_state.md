# F4C - Risk State Persistence Packet

Bundle: F4C
Domain: Risk layer - state persistence and atomic writes
Prerequisite: F4B COMPLETE

---

## Objective

Verify atomic write path for risk state. Confirm backup and restore logic.
Confirm ATOMIC_WRITE_FAILED and RESTORED_FROM_BACKUP counters are reachable
and correctly logged. Confirm no silent state corruption on write failure.

---

## Files in scope

- app/risk/guard.py
- app/risk/unified_risk.py
- tests/ (new persistence and restore tests)

## Files out of scope

All other files. State file path constants or serialization helpers found in
out-of-scope modules must be reported as OUT_OF_SCOPE_BLOCKER.

---

## Required checks

Atomic write path:
- Confirm write uses temp file + rename (or equivalent atomic pattern)
- Confirm ATOMIC_WRITE_FAILED is incremented on failure
- Confirm ATOMIC_WRITE_TRANSIENT is incremented on transient error
- Confirm failure does not leave corrupt partial state file

Backup and restore:
- Confirm backup file is written before or alongside primary
- Confirm RESTORED_FROM_BACKUP is incremented when restore fires
- Confirm restored state is valid and usable

Counter reachability:
- Confirm each counter has at least one code path that increments it
- Confirm counters are logged or telemetered so they appear in output

---

## Invariants

- Atomic write must never leave partial or corrupt state
- Backup must exist before primary is overwritten
- RESTORED_FROM_BACKUP fires only when primary is missing or corrupt
- All three counters are reachable from tests

---

## Acceptance criteria

Tests exercise atomic write success, atomic write failure, and restore paths.
All three counters observed in test output.
No regressions in existing risk guard tests.
state/risk_state.json and state/risk_state.backup confirmed consistent after test.

---

## Board escalation triggers

- Atomic write uses non-atomic pattern: BOARD_ESCALATION: NON_ATOMIC_STATE_WRITE
- ATOMIC_WRITE_FAILED counter unreachable: BOARD_ESCALATION: COUNTER_UNREACHABLE
- Backup file absent or not written before primary: BOARD_ESCALATION: BACKUP_MISSING
