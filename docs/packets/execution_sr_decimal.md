# EXECUTION_SR_DECIMAL - Execution Signal Routing Decimal Discipline Packet

Bundle: EXECUTION_SR_DECIMAL
Domain: Execution layer - signal routing + Decimal precision
Prerequisite: G0 COMPLETE, F4A COMPLETE, Post-F4C Paper Proof PASS

---

## Objective

Verify and repair the full signal-to-fill execution path within the execution layer.
Confirm SIGNAL_SUBMITTED, PAPERBROKER_REACH_COUNT, and PAPER_FILL_COUNT are
reachable and correctly wired. Extend Decimal discipline enforcement into any
remaining execution-layer seams not covered by F4A.

---

## Files in scope

- app/execution/engine.py
- app/execution/order_router.py
- app/execution/paper_broker.py
- tests/ (new and existing execution path tests)

## Files out of scope

All other files. If a violation or disconnection is found in an out-of-scope file,
report as OUT_OF_SCOPE_BLOCKER and escalate to Board before touching it.

Explicitly excluded:
- app/main_loop.py
- app/brain/signal_fusion.py
- app/strategies/strategy_router.py
- app/core/decision_compiler.py
- app/risk/
- app/models/
- Any file outside app/execution/ and tests/

---

## Invariants

- SIGNAL_SUBMITTED path must be reachable from the execution engine
- PAPERBROKER_REACH_COUNT counter must be instrumented and reachable
- PAPER_FILL_COUNT counter must be instrumented and reachable
- No float in order payload at broker boundary (extends F4A)
- No Decimal-from-float anywhere in execution path (extends F4A)
- All fill amounts stored as Decimal
- Paper broker must not silently succeed without a state transition

---

## Acceptance criteria

Paper proof run shows SIGNAL_SUBMITTED, PAPERBROKER_REACH_COUNT > 0,
PAPER_FILL_COUNT > 0 in log evidence after a full signal cycle.
New tests cover the signal-to-fill path through execution layer.
/decimal-scan returns CLEAN on all EXECUTION_SR_DECIMAL files.
No regressions in existing execution tests.

---

## No-silent-degradation requirements

- Decimal precision discipline must be equivalent or stronger after patch
- Paper broker reachability must be proven by log counters, not boot success
- Emergency and fallback paths in execution layer must preserve current behavior
- No simplification of order routing logic
