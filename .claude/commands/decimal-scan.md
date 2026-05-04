# /decimal-scan - Decimal Discipline Scan

Scans repo for float usage in execution, risk, and sizing paths where Decimal
is required. Does not edit files.

Scan targets (read-only):
- app/execution/engine.py
- app/execution/order_router.py
- app/execution/paper_broker.py
- app/risk/guard.py
- app/risk/unified_risk.py
- app/core/decision_compiler.py

Patterns to flag:
- float() calls on price, quantity, notional, or fee fields
- arithmetic on raw float literals in order construction
- division or multiplication producing float where Decimal is expected
- Decimal constructed from float (Decimal(0.1) instead of Decimal("0.1"))

Required report:

DECIMAL_SCAN_REPORT
files_scanned: <count>
float_violations_found: <count>

For each violation:
  file: <path>
  line: <number>
  pattern: <matched text>
  severity: CRITICAL / WARNING
  note: <why Decimal is required here>

verdict: CLEAN / VIOLATIONS_FOUND
board_escalation_required: yes / no
