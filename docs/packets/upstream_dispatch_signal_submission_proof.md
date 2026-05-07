# UPSTREAM_DISPATCH_SIGNAL_SUBMISSION_PROOF_BUNDLE

## Status

ACTIVE — governance registration complete, production patch phase pending Board approval.

## Mission

Diagnose and, only if a wiring/state/timing/contract bug is proven, repair the
upstream strategy/fusion/dispatch path so that a real executable candidate
reaches ExecutionEngine.submit_signal. Legitimate gating must remain intact.

The goal is not "make it trade." The goal is:
- When a real executable candidate exists, it reaches ExecutionEngine.
- When gates legitimately decline, it does not.

## Repo-truth basis

Latest pushed execution-layer closeout: 429b187 — Fix paper fill completion path.

Paper fill path is unit-proven:
- tests/test_paper_fill_completion.py = 13/13 passed.
- tests/test_paper_fill_completion.py + tests/test_g0_hook_verification.py = 150/150 passed.

Paper fill path is NOT runtime-proven because no signal reached ExecutionEngine
in the latest paper-mode run.

PAPER_FILL_COMPLETION_PROOF_BUNDLE proof run counters
(reports/paper_run_fill_proof_20260506_183834.summary.txt):
- BROKER_MODE_PAPER=2
- LIVE_MODE_LEAK=0
- SIGNAL_SUBMITTED=0
- PAPERBROKER_REACH_COUNT=0
- PAPER_FILL_COUNT=0
- ORDER_REJECT_COUNT=0
- TRACEBACK_COUNT=0
- TYPEERROR_COUNT=0
- DECIMAL_FLOAT_ERROR_COUNT=0
- ATOMIC_WRITE_FAILED=0

Runtime evidence (reports/paper_run_fill_proof_20260506_183834.stdout.log):
- ETH/USD: early SHANS_NOT_READY, then LIVE_GATE pass; SHADOW_FRONT declined
  whale_condition (score=0.1950 < threshold=0.2000); SECTOR_ROTATION blocked
  because observed pair was missing (signal=None vote=None).
- SOL/USD: SECTOR_ROTATION dispatch freshness fail
  (vote_ts=1778073300000000000, signal_ts=1778073300000000000,
  exchange_ts_ns=1778110800000000000, ~10.4 h delta).
- BTC/USD: fusion preferred_sleeve=None on live-gate-pass candle.
- Zero [EXEC_DIAG] markers across the run.
- ExecutionEngine.submit_signal was never invoked.

Important interpretation:
PaperBroker and OrderRouter are not the current blocker. Execution fill path
is unit-proven. Runtime path is blocked upstream before execution. The next
problem is upstream dispatch / signal submission truth.

## Packet name

POVERTY_KILLER_PACKET=UPSTREAM_DISPATCH_SIGNAL_SUBMISSION_PROOF_BUNDLE

## Governance registration scope (this phase)

Allowed to edit:
- .claude/hooks/pre_tool_use.py
- tests/test_g0_hook_verification.py
- docs/EXECUTION_PLAN.md
- docs/packets/upstream_dispatch_signal_submission_proof.md

## Production patch scope (next phase, pending Board approval)

Non-locked:
- app/main_loop.py
- tests/ (prefix)

Locked authority files with packet-scoped exceptions:
- app/brain/signal_fusion.py
- app/core/decision_compiler.py

Explicitly blocked (all phases):
- app/execution/* (engine.py, order_router.py, paper_broker.py)
- app/risk/* (guard.py, unified_risk.py, position_sizing.py, etc.)
- app/strategies/* (shadow_front.py, sector_rotation.py, etc.)
- app/brain/shans_curve.py
- app/brain/regime_detector.py
- main.py
- docs/CURRENT_STATUS.md (until closeout only)
- reports/*, state/*, dependency files, secrets/.env

## Acceptance invariants

Before closing UPSTREAM_DISPATCH_SIGNAL_SUBMISSION_PROOF_BUNDLE:
1. Root cause classified as legitimate gating OR wiring/state/timing/contract
   bug, with proof from live repo source truth.
2. If a bug is proven, smallest-boundary patch applied within the production
   patch scope above. No threshold relaxation. No fake signals. No bypass.
3. Targeted unit tests under tests/ proving:
   - OBSERVE_ONLY remains non-executing if architecture defines it as
     observation-only.
   - Valid executable candidate reaches DecisionCompiler.
   - Valid candidate can reach ExecutionEngine submission boundary through
     main_loop or a tested dispatch seam.
   - ShadowFront decline correctly falls back to SectorRotation.
   - SectorRotation missing observed pair still blocks.
   - SectorRotation stale observed pair still blocks.
   - SectorRotation fresh same-candle observed pair passes.
   - all_sleeves_declined remains correct when all sleeves truly decline.
   - No threshold relaxation, no fake signal, no bypass of SignalFusion or
     DecisionCompiler, no live-mode path.
4. tests/test_g0_hook_verification.py passes with zero failures.
5. TRACEBACK_COUNT=0, DECIMAL_FLOAT_ERROR_COUNT=0, LIVE_MODE_LEAK=0 in any
   targeted runtime evidence Board authorizes separately.

## Forbidden always

- Live mode.
- --attack mode.
- Override mode unless Board explicitly authorizes.
- git add . / git add --all / git add -A.
- Destructive git (reset, clean, restore, push --force).
- Threshold relaxation.
- Fake signals.
- Fake fills.
- Forced signal submission.
- Bypassing SignalFusion, StrategyRouter, Shans Curve, RegimeDetector,
  RiskGuard, or DecisionCompiler.
- Direct strategy-to-execution shortcut.
- Bypassing ExecutionEngine, OrderRouter, or PaperBroker.
- Second proof run without Board approval.
- Editing app/strategies/*, app/risk/*, app/execution/*, app/brain/shans_curve.py,
  app/brain/regime_detector.py, app/models/*, app/data/*, app/monitoring/*,
  main.py, docs/CURRENT_STATUS.md (until closeout), reports/*, state/*,
  dependency files, or secrets/.env.

## Hook tests proving registration (tests/test_g0_hook_verification.py)

Class TestUpstreamDispatchSignalSubmissionProofBundle covers:
1. Allows app/main_loop.py.
2. Allows app/brain/signal_fusion.py as locked exception.
3. Allows app/core/decision_compiler.py as locked exception.
4. Allows tests/ prefix.
5. Blocks app/execution/order_router.py.
6. Blocks app/execution/paper_broker.py.
7. Blocks app/risk/guard.py.
8. Blocks app/strategies/sector_rotation.py.
9. Blocks app/brain/shans_curve.py.
10. Blocks main.py.
11. Dangerous Bash rules remain unchanged.
12. Unknown packets still block.
Plus extras: blocks app/brain/regime_detector.py, app/execution/engine.py,
and docs/CURRENT_STATUS.md while the packet is active.
