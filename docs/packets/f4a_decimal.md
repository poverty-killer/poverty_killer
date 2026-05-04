# F4A - Execution Decimal Discipline Packet

Bundle: F4A
Domain: Execution layer - Decimal precision
Prerequisite: G0 COMPLETE

---

## Objective

Eliminate float usage in execution, order routing, and paper broker paths.
Enforce Decimal with string construction for all price, quantity, notional,
and fee fields. Confirm no Decimal-from-float construction.

---

## Files in scope

- app/execution/engine.py
- app/execution/order_router.py
- app/execution/paper_broker.py
- app/utils/decimal_utils.py
- tests/ (new and existing decimal discipline tests)

## Files out of scope

All other files. If a violation is found in an out-of-scope file, report as
OUT_OF_SCOPE_BLOCKER and escalate to Board before touching it.

---

## Forbidden patterns

- float() applied to price, quantity, notional, or fee
- raw float literal in order construction (e.g. 0.001 instead of Decimal("0.001"))
- Decimal constructed from float (Decimal(0.1))
- division or multiplication that silently produces float in order fields

## Required patterns

- Decimal("0.001") for string-constructed literals
- decimal_utils helpers for unit conversions if they exist
- explicit Decimal arithmetic in order size and fill calculations

---

## Invariants

- No float in order payload at broker boundary
- No Decimal-from-float anywhere in execution path
- All fill amounts stored as Decimal
- Precision loss is not acceptable at any execution seam

---

## Acceptance criteria

/decimal-scan on all F4A files returns CLEAN.
New tests cover Decimal construction and arithmetic in order path.
No regressions in existing execution tests.

---

## No-silent-degradation requirements

- Decimal precision discipline must be equivalent or stronger after patch
- No simplification of order math for convenience
- Emergency and fallback paths must also use Decimal
