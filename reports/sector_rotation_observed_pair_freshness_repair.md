# SectorRotation Observed-Pair Freshness Repair

Date: 2026-05-21
Branch: master

## Root Cause

The latest 20-minute PAPER run failed before DecisionCompiler because SectorRotation dispatch did not have a fresh observed signal/vote pair for the active consumer candle. The old code correctly failed closed for stale or missing pairs, but its diagnostics collapsed the causes into `observed_pair_missing` / `observed_pair_stale`, and the consumer freshness check allowed a pair through when either the signal timestamp or the vote timestamp matched the consumer candle.

Classification: wiring/observability bug in the observed-pair consumer and producer storage sequence. The runtime should require signal, vote, and consumer candle identity to all match. It also should not leave a half-pair if vote adaptation fails after signal production.

## Producer / Consumer Answers

- Observed signal producer: `MainLoop._observe_sector_rotation()` calls `SectorRotationStrategy.update_candle()` and `update_price()` on the admitted candle.
- Observed vote producer: `MainLoop._observe_sector_rotation()` calls `adapt_sector_rotation_to_vote()` for each real SectorRotation signal.
- Same candle window: yes when production succeeds; the vote adapter receives `candle.exchange_ts_ns`, and the signal is expected to carry that same candle timestamp.
- Timestamp/candle comparability: repaired to use canonical candle identity from the exchange timestamp in nanoseconds for signal, vote, and consumer.
- Symbol normalization: repaired with strict uppercase/trim comparison for consumer symbol, signal symbol, and vote metadata symbol when symbol evidence is present.
- Stale/missing cause classification: now machine-readable as `OBSERVED_SIGNAL_MISSING`, `OBSERVED_VOTE_MISSING`, `OBSERVED_PAIR_STALE`, `OBSERVED_PAIR_CANDLE_MISMATCH`, `OBSERVED_PAIR_SYMBOL_MISMATCH`, or `OBSERVED_PAIR_READY`.
- Blocking correctness: stale or missing observed-pair blocking remains correct safety behavior. The repaired part is stricter readiness classification and avoiding stored half-pairs.

## Files Changed

- `app/main_loop.py`
- `tests/test_runtime_dispatch_admission_telemetry.py`
- `tests/test_upstream_dispatch_signal_submission.py`
- `reports/sector_rotation_observed_pair_freshness_repair.md`

## Repair Summary

- Added canonical observed-pair detail fields for signal/vote/consumer timestamps and candle IDs.
- Replaced the old OR freshness gate with strict same-candle readiness: signal timestamp, vote timestamp, and consumer timestamp must all match.
- Added symbol-mismatch classification before freshness admission.
- Preserved fail-closed behavior for missing, stale, mismatched, or cross-symbol pairs.
- Reordered SectorRotation observe storage so vote adaptation must succeed before signal/vote are recorded together.
- Added dispatch diagnostics that include `observed_signal_present`, `observed_vote_present`, `signal_timestamp`, `vote_timestamp`, `consumer_timestamp`, `signal_candle_id`, `vote_candle_id`, `consumer_candle_id`, `stale_age_ns`, and symbol evidence.

## Verification

- `venv/Scripts/python.exe -m py_compile app/main_loop.py tests/test_runtime_dispatch_admission_telemetry.py tests/test_upstream_dispatch_signal_submission.py` passed.
- `python3 -m py_compile app/main_loop.py tests/test_runtime_dispatch_admission_telemetry.py tests/test_upstream_dispatch_signal_submission.py tests/test_physical_freshness_dispatch_alignment.py` passed.
- `cmd.exe /c "venv\Scripts\python.exe -m pytest tests\test_runtime_dispatch_admission_telemetry.py tests\test_upstream_dispatch_signal_submission.py -q"` passed: 44 passed.
- `cmd.exe /c "venv\Scripts\python.exe -m pytest tests\test_physical_freshness_dispatch_alignment.py -q"` passed: 6 passed.
- `git diff --check -- app/main_loop.py tests/test_runtime_dispatch_admission_telemetry.py tests/test_upstream_dispatch_signal_submission.py` passed.

No autonomous PAPER run was executed. No broker POST, order placement, cancel, replace, or live endpoint was used.

## Remaining Blockers

Future PAPER evidence may still correctly block if real SectorRotation signal or vote truth is absent for a consumer candle. That is now expected to surface with one of the machine-readable observed-pair reason codes instead of requiring manual log archaeology.

## Verdict

PASS: SectorRotation observed-pair readiness is now strictly produced/consumed, stale/missing/mismatch causes are machine-readable, focused tests pass, and no broker mutation occurred.
