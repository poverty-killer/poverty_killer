# DATA_UNHEALTHY / Execution Admission Causal Seam

## Verdict

PASS for the scoped seam. No autonomous PAPER run was performed. No broker mutation path was exercised.

## Files Changed

- `app/brain/data_validator.py`
- `app/execution/engine.py`
- `app/main_loop.py`
- `tests/test_runtime_dispatch_admission_telemetry.py`
- `tests/test_pre_trade_guardrail_constraints.py`

## Causal Finding

The buy-side `DATA_UNHEALTHY` blocker was a wiring/cadence issue, not a reason to lower thresholds.

Runtime candles from REST polling could continue through the executable candle path even when their exchange timestamp was older than the data-validator freshness budget. At the same time, fresh candles were not updating `DataContinuityValidator`; the validator was only being refreshed from books/trades. With Coinbase public REST, book timestamp truth may be unavailable, so candle-driven SectorRotation candidates could reach execution admission without a fresh validator timestamp for that symbol.

## Repair

- Added `DataContinuityValidator.health_snapshot()` with machine-readable causal fields for `DATA_UNHEALTHY`.
- Execution admission now records block evidence for `DATA_UNHEALTHY`, including symbol, gap state, last valid data timestamp/age, freshness threshold, latest book/candle timestamps, reason code, and source type.
- Fresh same-symbol runtime candles now update the validator before executable dispatch.
- Stale/backfill/observe-only candles remain observable but are stopped before Fusion/DecisionCompiler/execution dispatch with `DATA_BACKFILL_OBSERVE_ONLY`.
- Execution admission also fails closed if a signal is explicitly tagged as backfill/replay/synthetic/observe-only market truth.

## Safe Mode

Safe mode was not weakened. `SAFE_MODE_ACTIVE` now carries latency and recovery evidence:

- latency truth status and reason code
- latency value and threshold
- latency source
- safe-mode entered timestamp
- last latency-ok timestamp
- recovery state

Recovery still clears only on real `LATENCY_OK` truth.

## Sell Path

Sell enablement was not changed. Sell signals now get diagnostic intent classification:

- `SELL_AUTHORITY_MISSING`
- `SELL_EXIT_LOCAL_SIM_ONLY`
- `SELL_SHORT_UNSUPPORTED`
- `SELL_EXIT_EXISTING_BROKER_POSITION`

Without proven broker position truth, sell remains blocked. Even with a mocked proven broker position, existing venue capability still keeps sell blocked by `ACTION_UNSUPPORTED`.

## Tests Run

- `venv/Scripts/python.exe -m py_compile app/brain/data_validator.py app/execution/engine.py app/main_loop.py`
- `cmd.exe /c "venv\\Scripts\\python.exe -m pytest tests\\test_runtime_dispatch_admission_telemetry.py tests\\test_pre_trade_guardrail_constraints.py tests\\test_lag_abort_infms_shadow_readiness.py -q"`

Result: 45 passed.

## Diff Check

- `git diff --check -- app/brain/data_validator.py app/execution/engine.py app/main_loop.py tests/test_runtime_dispatch_admission_telemetry.py tests/test_pre_trade_guardrail_constraints.py`

Result: clean, with only the existing Git line-ending warning for `app/brain/data_validator.py`.

## Next Smoke

A short bounded PAPER smoke test is justified after review because this seam should move buy candidates from opaque `DATA_UNHEALTHY` into either:

- `DATA_BACKFILL_OBSERVE_ONLY` before DecisionCompiler when REST candles are stale/backfill, or
- executable admission when fresh same-symbol runtime truth exists and safe mode is clear.
