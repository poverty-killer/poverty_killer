# Fresh Executable Candidate Flow Seam

## Root Cause

The 20 minute scorecard observation run proved runtime scorecard visibility, but most records were `CANDLE_BATCH_BACKFILL_OBSERVE_ONLY`. The active REST candle path treated the raw provider batch head as the latest batch candle, even when that candle was still open, and it forwarded older batch candles through the active runtime callback. The runtime classifier also clamped negative candle close age to zero, which could make an in-progress candle look fresh instead of explicitly non-executable.

## Implementation Summary

- Split REST batch authority into provider batch head and latest closed executable batch candle.
- Active polling callbacks now forward only the latest closed candle from the REST batch.
- Older batch candles remain observe-only/backfill evidence.
- Open current candles are blocked as `CANDLE_NOT_CLOSED` / `DATA_RUNTIME_CANDLE_IN_PROGRESS`.
- Runtime candle truth now records provider id, provider batch head, latest closed batch status, candle close time, and close-at-receive evidence.
- Candidate lifecycle penalties now recognize open/in-progress runtime candles as freshness penalties.
- SectorRotation same-candle signal/vote alignment remains strict: matching candle IDs can reach `OBSERVED_PAIR_READY`; missing, stale, or mismatched evidence remains blocked with scorecard evidence preserved.
- Source-scoped REST latency remains opportunity evidence/penalty and does not erase candidates.
- Final execution/broker boundary remains unchanged: hard blockers still prevent broker mutation.

## Files Changed

- `app/models/market_data.py`
- `app/data/polling_client.py`
- `app/main_loop.py`
- `app/core/candidate_lifecycle.py`
- `tests/test_feed_provider_router_failover.py`
- `tests/test_runtime_dispatch_admission_telemetry.py`
- `reports/fresh_executable_candidate_flow_seam.md`

## Tests Run

- `venv/Scripts/python.exe -m py_compile app/models/market_data.py app/data/polling_client.py app/main_loop.py app/core/candidate_lifecycle.py`
- `venv/Scripts/python.exe -m pytest tests/test_feed_provider_router_failover.py::test_rest_polling_marks_latest_closed_candle_executable_not_open_batch_head tests/test_feed_provider_router_failover.py::test_rest_polling_has_no_executable_candle_when_batch_head_is_not_closed tests/test_runtime_dispatch_admission_telemetry.py -q`
  - Result: 30 passed.
- `venv/Scripts/python.exe -m pytest tests/test_feed_provider_router_failover.py tests/test_runtime_dispatch_admission_telemetry.py tests/test_candidate_lifecycle_scorecard_seam.py tests/test_runtime_rest_feed_connectivity_and_latency_truth.py tests/test_pre_trade_guardrail_constraints.py -q`
  - Result: 88 passed.

## What Now Reaches DecisionCompiler In Tests

A fresh runtime candle that is:

- provider-classified as runtime,
- the latest closed REST batch candle,
- inside provider freshness policy,
- paired with same-candle SectorRotation signal and vote,
- not stale or mismatched,

now reaches `DecisionCompiler.compile` and then the mocked `ExecutionEngine.submit_signal` path. The scorecard and lifecycle are preserved, including source-scoped REST latency penalty evidence. The test still applies a hard execution blocker (`QUOTE_SESSION_TRUTH_MISSING`) and confirms `broker_post=False`.

## What Remains Blocked

- Older REST batch candles: `CANDLE_BATCH_BACKFILL_OBSERVE_ONLY` / `DATA_BACKFILL_OBSERVE_ONLY`.
- Current candle before close: `CANDLE_NOT_CLOSED` / `DATA_RUNTIME_CANDLE_IN_PROGRESS`.
- Backfill, replay, synthetic, or non-runtime source candles.
- Missing provider freshness policy.
- Stale, missing, or mismatched SectorRotation observed signal/vote pairs.
- Hard final execution blockers, including quote/session truth missing and pre-trade guardrail failures.

## Next PAPER Run Recommendation

A 300 second PAPER smoke is justified next. The test seam proves that fresh closed runtime candles can reach DecisionCompiler without weakening broker safety, but a bounded PAPER run is needed to confirm the live provider cadence now shifts runtime records away from observe-only/backfill dominance and produces DecisionCompiler attempts with zero broker mutation unless every hard execution gate passes. A 20 minute PAPER observation should wait until the 300 second smoke confirms the distribution shift.
