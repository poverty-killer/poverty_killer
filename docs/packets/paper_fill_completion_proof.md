# PAPER_FILL_COMPLETION_PROOF_BUNDLE

## Status

ACTIVE — governance registration complete, production patch phase pending Board approval.

## Mission

Diagnose and repair the paper fill completion gap.

PaperBroker was reached (PAPERBROKER_REACH_COUNT=2) but paper fill was not recorded
(PAPER_FILL_COUNT=0) in the SECTOR_ROTATION_FRESH_OBSERVED_PAIR_PROOF_BUNDLE proof run.

The full signal-to-fill path must be traced, the break located, and the wiring repaired
so that a paper fill is recorded when PaperBroker is reached with a valid order.

## Repo-truth basis

Latest closed bundle: c6be162 — Close SECTOR_ROTATION_FRESH_OBSERVED_PAIR_PROOF_BUNDLE as PASS

Observed counters from prior proof run:
- SIGNAL_SUBMITTED=1
- PAPERBROKER_REACH_COUNT=2
- PAPER_FILL_COUNT=0
- TRACEBACK_COUNT=0
- TYPEERROR_COUNT=0
- DECIMAL_FLOAT_ERROR_COUNT=0
- LIVE_MODE_LEAK=0

## Packet name

POVERTY_KILLER_PACKET=PAPER_FILL_COMPLETION_PROOF_BUNDLE

## Governance registration scope (this phase)

Allowed to edit:
- .claude/hooks/pre_tool_use.py
- tests/test_g0_hook_verification.py
- docs/EXECUTION_PLAN.md
- docs/packets/paper_fill_completion_proof.md
- docs/CURRENT_STATUS.md (continuity only)

## Production patch scope (next phase, pending Board approval)

Non-locked:
- app/execution/paper_broker.py
- app/execution/order_router.py
- tests/ (prefix)

Locked authority with packet-scoped exception:
- app/execution/engine.py

Explicitly blocked (all phases):
- app/brain/*
- app/strategies/*
- app/risk/*
- app/core/*
- app/models/*
- app/data/*
- app/monitoring/*
- main.py
- app/main_loop.py
- state/* (except session_journal.jsonl via post_tool_use hook)

## Acceptance invariants

Before closing PAPER_FILL_COMPLETION_PROOF_BUNDLE:
1. PAPER_FILL_COUNT >= 1 in a controlled paper proof run.
2. PAPERBROKER_REACH_COUNT >= 1.
3. TRACEBACK_COUNT=0.
4. DECIMAL_FLOAT_ERROR_COUNT=0.
5. LIVE_MODE_LEAK=0.
6. No fake fills injected. Fill must result from real order path.
7. No risk weakening. No threshold relaxation.

## Forbidden always

- Live mode.
- git add . / git add --all / git add -A.
- Destructive git (reset, clean, restore, push --force).
- Override mode.
- Fake fills.
- Fake signals.
- Risk weakening.
- Threshold relaxation.
- Second proof run without Board approval.
