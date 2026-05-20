# Operation Whole-Bot Active Edge Shadow Stress

## Files Changed

- `app/core/whole_bot_attribution.py`
- `app/core/decision_compiler.py`
- `app/brain/signal_fusion.py`
- `app/main_loop.py`
- `app/execution/engine.py`
- `main.py`
- `tests/test_whole_bot_active_edge_attribution.py`
- `reports/autonomous_paper_friday_readiness.md`
- `reports/operation_whole_bot_active_edge_shadow_stress.md`

## Attribution Schema

Each runtime signature carries:

`module_name`, `category`, `status`, `input_source`, `output_summary`, `effect`, `reason`, `timestamp`.

Allowed statuses and effects are enforced in `app/core/whole_bot_attribution.py`.

## Modules Wired

- Signal path: `SignalFusion`, `DecisionCompiler`, `DecisionRecord.metadata`.
- Strategy/alpha signatures: `MovingFloor`, `AdaptiveDC`, `ShadowFront`.
- Intelligence/portal signatures: `WhaleFlow`, `Toxicity`, `RegimeDetector`, `EntropyDecoder`, `InsiderSignalEngine`, `ShansCurve`.
- Governors: `NetEdgeGovernor`, `TradeEfficiencyGovernor`, sourced from pre-trade guardrail module evidence when available.
- Safety/truth/state: `PreTradeGuardrails`, `TruthKernel`, `InvariantChecker`, `Reconciliation`, `StateStore`.
- Venue/execution: `CapabilityRegistry`, `AlpacaPaperAdapter`, `ExecutionEngine`, `OrderRouter`, `BrokerGateway`, `ShadowReadOnlyGate`.
- Startup audit: `RuntimeBootstrap`.

## Runtime Evidence

Command:

```bash
timeout 60s venv/Scripts/python.exe main.py --paper --shadow-read-only --log-level INFO
```

Result:

- Exit code `124` from the 60-second timeout.
- Startup reached full runtime.
- `Broker Mode: paper` observed.
- `Shadow Read Only: ENABLED` observed.
- Kraken websocket connected to `wss://ws.kraken.com/v2`.
- Live `FEED_CANDLE` and `FEED_BOOK` ingress occurred.
- Startup attribution audit event recorded in `data/telemetry.db`.
- Startup attribution module count: `19`.
- Startup shadow broker mutation counts: `POST=0`, `PATCH=0`, `DELETE=0`, `cancel=0`, `replace=0`, `sell=0`, `rebalance=0`.

## Mutation Scan

Current-run log scan over `2026-05-20T03:58` and `2026-05-20T03:59` found no:

- `ORDER_SUBMIT_ATTEMPT`
- `PAPERBROKER_REACH_COUNT`
- `PAPER_FILL_COUNT`
- `/v2/orders`
- `SHADOW_READ_ONLY_BLOCKED`
- `Broker Mode: live`

No live mode, no live endpoint, no market/sell/rebalance/cancel/replace/retry storm, and no broker mutation were observed.

## Feed Truth

- Websocket feed: active, connected, produced candles/books.
- REST polling: degraded with DNS failure: `Cannot connect to host api.kraken.com:443 ssl:default [Could not contact DNS servers]`.
- Broker read-only truth was not proven in this shadow run; missing broker reconciliation truth is reported as missing/degraded rather than invented.

## Decision And Guardrails

- No `DecisionRecord compiled` line appeared in the 60-second run.
- Dispatch diagnostics reported `shans_not_ready`, for example `submit_signal_called=False`.
- No shadow would-submit packet occurred because the active dispatch path did not produce an executable signal.
- Focused tests prove that when a decision is compiled, `DecisionRecord.metadata["edge_attribution"]` carries whole-bot attribution and shadow telemetry carries it through the no-mutation boundary.

## Governor And Portal Status

- `NetEdgeGovernor`: signed as missing economic truth/advisory through guardrail evidence; no net edge or profitability was invented.
- `TradeEfficiencyGovernor`: signed as missing economic truth/advisory through guardrail evidence; no slippage or efficiency result was invented.
- `InsiderSignalEngine`: signs `MISSING_FEED_TRUTH` unless lawful live insider/corporate feed truth is supplied. No MNPI or synthetic portal data is used.

## Truth And Invariants

- `TruthKernel` signs active truth checks when a `TruthFrame` is present.
- `InvariantChecker` signs missing hot-dispatch invariant snapshot truth when the full invariant snapshot is unavailable in the dispatch packet.
- `Reconciliation` signs missing broker reconciliation snapshot truth when account/positions/open-orders truth is not attached.
- Local `StateStore` signs as supporting evidence only.

## Blockers

- `app/brain/shans_curve.py:_savitzky_golay` failed Numba nopython compilation during live order-book processing:
  `exception_match(none, LinAlgError)` is unsupported because nopython exception matching is limited to `Exception`.
- Kraken REST polling DNS failed for candle and order-book refreshes.
- Active live-data shadow did not reach executable candidate submission; autonomous PAPER launch remains blocked until the active path can run without the ShansCurve runtime error and required feed/broker truth is available.

## Tests

- `venv/Scripts/python.exe -m py_compile app/core/whole_bot_attribution.py app/core/decision_compiler.py app/brain/signal_fusion.py app/main_loop.py app/execution/engine.py main.py tests/test_whole_bot_active_edge_attribution.py` passed.
- `venv/Scripts/python.exe -m pytest -q tests/test_whole_bot_active_edge_attribution.py` passed: `6 passed`.
- `venv/Scripts/python.exe -m pytest -q tests/test_bot_wide_shadow_read_only_runtime_gate.py tests/test_upstream_dispatch_signal_submission.py` passed: `32 passed`.
- Regression slice passed: `131 passed, 1 skipped`.

Regression slice:

```bash
venv/Scripts/python.exe -m pytest -q tests/test_whole_bot_active_edge_attribution.py tests/test_bot_wide_shadow_read_only_runtime_gate.py tests/test_execution_spine_order_routing.py tests/test_broker_gateway_adapter_layer.py tests/test_pre_trade_guardrail_constraints.py tests/test_signal_fusion.py tests/test_upstream_dispatch_signal_submission.py tests/test_intelligence_portfolio_state_truth_spine.py tests/test_state_store.py tests/test_state_recovery_spine.py tests/test_venue_market_asset_capability_layer.py tests/test_seam6_controlled_alpaca_paper_portfolio_expansion_machine.py
```
