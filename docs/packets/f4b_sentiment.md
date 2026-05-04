# F4B - Sentiment Velocity Concurrency Packet

Bundle: F4B
Domain: Sentiment layer - concurrency and thread safety
Prerequisite: F4A COMPLETE

---

## Objective

Verify thread-safety and concurrency discipline in sentiment velocity and
symbol runtime. Confirm no shared mutable state races. Confirm liveness
classification as REAL (not REAL_BUT_DISCONNECTED or PARTIAL).

---

## Files in scope

- app/brain/sentiment_velocity.py
- app/symbol_runtime.py
- tests/ (new concurrency and liveness tests)

## Files out of scope

All other files. Cross-file wiring issues found during F4B must be reported
as OUT_OF_SCOPE_BLOCKER before any cross-file patch is attempted.

---

## Required checks

Concurrency:
- Identify all shared mutable state in sentiment_velocity.py and symbol_runtime.py
- Confirm locks, queues, or immutability protect each shared structure
- Confirm no lock inversion or deadlock risk between the two modules

Liveness:
- Confirm sentiment_velocity is called from a live path (trace caller chain)
- Confirm output is consumed by signal_fusion or an equivalent live consumer
- Classify: REAL / REAL_BUT_DISCONNECTED / PARTIAL / STUB

---

## Invariants

- No unprotected shared mutable state in sentiment path
- Sentiment output reaches signal_fusion (or escalate if disconnected)
- symbol_runtime state updates are atomic or lock-protected
- No silent data loss under concurrent symbol updates

---

## Acceptance criteria

New tests exercise concurrent update paths without race.
Liveness classification confirmed REAL with caller chain documented.
No regressions in existing sentiment or symbol tests.

---

## Board escalation triggers

- Sentiment output is not consumed by any live downstream: BOARD_ESCALATION: SENTIMENT_DISCONNECTED
- Lock inversion risk found: BOARD_ESCALATION: LOCK_INVERSION_RISK
- Shared state found with no protection: BOARD_ESCALATION: UNPROTECTED_SHARED_STATE
