# Final Runway Opportunity Scorecard / Execution Boundary Seam

## Scope

This packet combines the requested final-runway tasks into one seam:

- Candidate Lifecycle Ledger
- Opportunity Scorecard
- Gate Reclassification
- Latency Authority Separation
- Execution Boundary Separation
- Machine-readable candidate attribution / explainability

The implementation does not lower execution thresholds, force trades, bypass pre-trade guardrails, invent broker facts, invent market facts, or create a broker mutation path.

## Files Changed

- `app/core/candidate_lifecycle.py`
- `app/main_loop.py`
- `app/execution/engine.py`
- `tests/test_candidate_lifecycle_scorecard_seam.py`
- `tests/test_runtime_rest_feed_connectivity_and_latency_truth.py`
- `tests/test_runtime_dispatch_admission_telemetry.py`
- `reports/final_runway_opportunity_scorecard_execution_boundary_seam.md`

## Candidate Lifecycle Ledger

`app/core/candidate_lifecycle.py` adds an immutable dataclass-backed candidate record with machine-readable gates:

- `candidate_created`
- `market_truth_snapshot`
- `strategy_module_evidence`
- `opportunity_scorecard`
- `decision_compiler_result`
- `pre_trade_guardrail_result`
- `execution_admission_result`
- `broker_boundary_result`
- `final_outcome`

`MainLoop._dispatch_fusion()` now creates the lifecycle before `DecisionCompiler.compile()`, attaches the scorecard to signal metadata and DecisionCompiler additional inputs, then records the execution result after `ExecutionEngine.submit_signal()`.

## Gate Reclassification

Reclassified as evidence / scorecard material where lawful:

- `SAFE_MODE_ACTIVE`: execution blocker, not opportunity eraser.
- Slow `market_data.rest_polling_rtt`: latency evidence / penalty, not global safe-mode trigger.
- `CANDLE_STALE` / `DATA_BACKFILL_OBSERVE_ONLY`: execution market-truth blocker, observe-only opportunity evidence.
- `OBSERVED_PAIR_STALE` / observed-pair missing: module decline evidence.
- ShadowFront no-signal decline: module decline evidence.
- `QUOTE_SESSION_TRUTH_MISSING`: execution blocker, scorecard preserved.
- `PRE_TRADE_GUARDRAIL_BLOCKED`: execution blocker, scorecard preserved.
- `ACTION_UNSUPPORTED` sell / `SELL_AUTHORITY_MISSING`: broker authority blocker unless exit authority is proven.

Still fatal / fail-closed:

- live endpoint / live mode / non-paper mutation
- fake or synthetic truth pretending to be executable live truth
- invalid symbol / malformed side / malformed qty / malformed price
- broker truth conflict
- market truth corruption
- risk kill switch
- missing universe authority

## Latency Authority

`ExecutionEngine._classify_latency_truth()` now emits source scope:

- `market_data_candle_rtt`
- `market_data_book_rtt`
- `broker_order_rtt`
- `websocket_rtt`
- `system_loop_lag`

Slow or missing REST polling RTT is recorded as market-data latency evidence and does not globally freeze the engine. Execution-critical latency, including websocket/order-router latency above the unchanged `200ms` threshold, still produces `LAG_ABORT_ACTIVE` and blocks submission through safe mode.

## Candle Freshness

REST 1m candle freshness now uses candle close-time authority:

`candle_close_ts_ns = candle_start_ts_ns + timeframe_ns`

The provider freshness budget is measured from close time, not the bucket start. Older batch/backfill/replay/synthetic data remains observe-only and non-executable.

## Scorecard vs Execution

The opportunity scorecard records:

- `raw_opportunity_score`
- module contributions
- module declines
- freshness penalties
- latency penalties
- final opportunity score
- opportunity verdict

Execution admission remains separate:

- pre-trade guardrails still block before OrderRouter
- safe mode still blocks broker admission when sourced from execution-critical latency/risk state
- data health still blocks executable market truth
- broker boundary remains fail-closed

## Broker Safety

Final broker mutation safety is unchanged:

- no broker POST unless all hard gates pass
- no live endpoint
- no real-money mode
- broker truth remains canonical
- market-data truth remains canonical
- conflicts fail closed
- shadow-read-only still blocks mutation before OrderRouter
- tests use mocks/stubs only; no live broker mutation was run

## Verification

Passed:

- `venv/Scripts/python.exe -m py_compile app/core/candidate_lifecycle.py app/main_loop.py app/execution/engine.py`
- `venv/Scripts/python.exe -m pytest tests/test_candidate_lifecycle_scorecard_seam.py -q`
  - `7 passed`
- `venv/Scripts/python.exe -m pytest tests/test_runtime_rest_feed_connectivity_and_latency_truth.py tests/test_lag_abort_infms_shadow_readiness.py tests/test_pre_trade_guardrail_constraints.py tests/test_runtime_dispatch_admission_telemetry.py tests/test_whole_bot_active_edge_attribution.py -q`
  - `65 passed`
- `git diff --check -- app/core/candidate_lifecycle.py app/main_loop.py app/execution/engine.py tests/test_candidate_lifecycle_scorecard_seam.py tests/test_runtime_rest_feed_connectivity_and_latency_truth.py tests/test_runtime_dispatch_admission_telemetry.py`

Additional widened checks run but not counted as acceptance:

- `tests/test_execution_spine_order_routing.py tests/test_broker_gateway_adapter_layer.py -q`
  - failed in external gateway-selection expectations unrelated to the scorecard seam; current `OrderRouter` only selects the gateway when `execution_broker="alpaca_paper"` is explicit, while several older tests instantiate only `broker_gateway_adapter=adapter`.
- `tests/test_dynamic_execution_broker_gateway_injection.py -q`
  - one failure in expected missing-credentials message: current code reports `alpaca_paper_adapter_blocked:credential_authority_blocked`.
- full `git diff --check`
  - blocked by pre-existing trailing whitespace in `app/monitoring/logger.py`; scoped diff check for this packet passed.

## PAPER Run Recommendation

A PAPER run is justified next, but only after review of this diff.

Recommended sequence:

1. 300s shadow/PAPER observation to verify candidate lifecycle lines and confirm slow REST candle RTT no longer creates global safe mode by itself.
2. 20m PAPER observation if the 300s run shows scorecards for candidates and no broker POST without full hard-gate passage.
3. 6h PAPER observation only after the 20m run proves stable lifecycle output, no live endpoint, no real-money mode, and no unintended broker mutation.

No autonomous PAPER run was started by this packet.
