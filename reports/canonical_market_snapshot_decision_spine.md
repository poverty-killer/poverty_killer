# Canonical Market Snapshot Decision Spine

## Verdict

Implemented. The candidate path now carries a canonical `MarketTruthSnapshot` from runtime strategy/advisory evidence through scorecard, DecisionCompiler metadata, submit_signal, ExecutionAdmission, and broker-boundary diagnostics.

No threshold was lowered. No fake market or broker truth was introduced. Tests remain non-mutating.

## Root Cause Fixed

The 2h PAPER observation proved fresh latest-closed candle flow could produce a same-candle `OBSERVED_PAIR_READY`, compile a `DecisionRecord`, and call `submit_signal`, but execution admission could still block with `DATA_UNHEALTHY / DATA_STALE` from an older global `DataContinuityValidator` side-cache.

That was an authority split:

- scorecard and DecisionCompiler saw fresh candidate-local runtime truth
- ExecutionEngine rebuilt data health from global validator state
- older monitor evidence could override newer candidate evidence

The fix makes candidate-local market truth canonical when present.

## Files Changed

- `app/core/market_snapshot.py`
- `app/main_loop.py`
- `app/core/decision_compiler.py`
- `app/execution/engine.py`
- `app/core/candidate_lifecycle.py`
- `tests/test_canonical_market_snapshot_decision_spine.py`
- `tests/test_runtime_dispatch_admission_telemetry.py`
- `reports/canonical_market_snapshot_decision_spine.md`

## Snapshot Propagation

Runtime now builds a canonical snapshot containing:

- `snapshot_id`
- `symbol`
- `book_ts_ns`
- `candle_id`
- `candle_close_ts_ns`
- `provider_id`
- `receive_ts_ns`
- `book_fresh`
- `candle_fresh`
- `executable_market_truth`
- `source_type`
- `snapshot_status`
- `snapshot_reason_codes`
- `snapshot_authority`

The snapshot is attached to:

- early candidate lifecycle / scorecard logs
- selected strategy signal metadata
- strategy vote metadata as evidence binding
- DecisionCompiler `additional_inputs`
- DecisionCompiler metadata diagnostics
- ExecutionEngine admission evidence
- broker-boundary order metadata if the path reaches routing

## Authority Rules

Execution admission now uses this ordering:

1. canonical candidate `MarketTruthSnapshot`
2. newer same-symbol contradictory execution truth
3. global validator / monitor evidence

Older validator evidence is preserved as monitor evidence and marked with `STALE_MONITOR_EVIDENCE_IGNORED`. It cannot kill a newer fresh candidate snapshot.

Newer contradictory same-symbol evidence blocks with `MARKET_TRUTH_CONFLICT`.

Missing canonical snapshot on a canonical path blocks with `MARKET_TRUTH_SNAPSHOT_MISSING`.

## What Still Blocks

The following remain fail-closed:

- missing canonical snapshot when the path requires one
- stale candidate snapshot
- backfill / replay / synthetic / observe-only snapshot source
- symbol mismatch
- candle timestamp mismatch
- newer same-symbol market-truth conflict
- final pre-trade guardrail blocks
- broker truth conflict
- quote/session truth missing
- safe mode, risk, volatility fuse, recalibration
- broker boundary safety gates

Backfill and historical data remain non-executable. Mismatched strategy evidence remains blocked.

## Tests Run

- `venv/Scripts/python.exe -m py_compile app/core/market_snapshot.py app/main_loop.py app/core/decision_compiler.py app/core/candidate_lifecycle.py app/execution/engine.py tests/test_canonical_market_snapshot_decision_spine.py tests/test_runtime_dispatch_admission_telemetry.py`
- `venv/Scripts/python.exe -m pytest tests/test_canonical_market_snapshot_decision_spine.py tests/test_runtime_dispatch_admission_telemetry.py::test_fresh_executable_sector_rotation_same_candle_reaches_compiler_with_scorecard -q`
  - `9 passed`
- `venv/Scripts/python.exe -m pytest tests/test_runtime_dispatch_admission_telemetry.py tests/test_candidate_lifecycle_scorecard_seam.py tests/test_pre_trade_guardrail_constraints.py -q`
  - `52 passed`
- `venv/Scripts/python.exe -m pytest tests/test_feed_provider_router_failover.py tests/test_runtime_rest_feed_connectivity_and_latency_truth.py -q`
  - `36 passed`

## Test Proof

Focused tests prove:

- fresh canonical snapshot reaches ExecutionEngine
- older stale global validator evidence does not override newer candidate truth
- stale candidate snapshot blocks before router submission
- newer contradictory same-symbol monitor truth blocks with `MARKET_TRUTH_CONFLICT`
- missing canonical snapshot fails closed
- symbol mismatch blocks
- candle timestamp mismatch blocks
- backfill / replay / synthetic snapshots block executable admission
- `OBSERVED_PAIR_READY` reaches DecisionCompiler and mocked `submit_signal` with snapshot intact
- router submission is not reached on hard blockers

## PAPER Recommendation

A 300s PAPER smoke is justified next. The next smoke should verify runtime log visibility for:

- `snapshot_id`
- `snapshot_status`
- `snapshot_reason_codes`
- `snapshot_authority`
- `STALE_MONITOR_EVIDENCE_IGNORED`
- `MARKET_TRUTH_CONFLICT` if naturally encountered
- DecisionCompiler and submit_signal snapshot fields
- zero live endpoint
- zero real-money mode
- zero broker POST unless a fully lawful PAPER path reaches final broker boundary

If the 300s smoke confirms snapshot propagation and safety remains clean, a 20m PAPER observation is justified to see whether the prior `DATA_STALE` blocker has been removed from fresh candidate flow.
