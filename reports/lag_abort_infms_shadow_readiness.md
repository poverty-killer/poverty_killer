# Lag Abort INFMS Shadow Readiness

Current HEAD at packet start: `c682211`.

## Files Inspected

- `app/execution/engine.py`
- `app/execution/order_router.py`
- `app/risk/guard.py`
- `app/data/websocket_client.py`
- `app/main_loop.py`
- `main.py`
- `app/monitoring/health.py`
- `app/monitoring/alerts.py`
- `reports/autonomous_paper_friday_readiness.md`
- `reports/seam7h_operator_monitoring_shadow_launch_readiness.md`

## Authority Finding

Lag-abort execution safety is split by existing authority:

- `OrderRouter.get_websocket_rtt_ms()` owns the websocket RTT measurement surface.
- `ExecutionEngine._monitor_loop()` owns execution-side latency monitoring and safe-mode entry/exit.
- `HybridRiskGuard.update_latency(...)` owns the hard lag-abort threshold state and emits `LAG ABORT: ...`.
- `ExecutionEngine._on_lag_detected()` is the callback that enters execution safe mode after a real guard lag abort.

The 200ms threshold is preserved:

- `main.py` constructs `HybridRiskGuard(max_latency_ms=200.0)`.
- `main.py` constructs `OrderRouter(latency_threshold_ms=200.0)`.
- `ExecutionEngine` defaults `lag_threshold_ms=200.0`.

## Root Cause

`infms` was not a measured finite latency breach.

Root path:

```text
OrderRouter.get_websocket_rtt_ms()
  -> returns float("inf") when websocket ping/pong timestamps are missing
ExecutionEngine._monitor_loop()
  -> passed float("inf") directly to HybridRiskGuard.update_latency(...)
HybridRiskGuard.update_latency(...)
  -> formatted float("inf") as "infms"
  -> emitted LAG ABORT
  -> triggered ExecutionEngine safe mode
```

Classification before fix:

- status effectively reported as `LAG_ABORT_ACTIVE`
- displayed latency: `infms`
- true missing source: websocket ping/pong timestamp truth was not initialized yet

This was startup/warmup timing truth, not a finite measured latency above 200ms.

## Fix Applied

`ExecutionEngine` now classifies latency truth before calling `HybridRiskGuard.update_latency(...)`.

New execution-side truth packet:

- `LatencyTruthResult`
- `ExecutionState.last_latency_truth`
- `ExecutionEngine._classify_latency_truth(...)`
- `ExecutionEngine._apply_latency_truth(...)`

Behavior:

- finite latency `<= 200ms`: `LATENCY_OK`
- finite latency `> 200ms`: `LAG_ABORT_ACTIVE` with measured `latency_ms`
- missing websocket ping/pong RTT: `MISSING_LATENCY_TRUTH`
- invalid pong-before-ping or negative RTT: `CLOCK_DELTA_INVALID`
- stale websocket RTT timestamp: `STALE_MARKET_TRUTH`

The safety boundary is preserved:

- real finite over-threshold latency still flows through `HybridRiskGuard.update_latency(...)`
- missing or invalid latency no longer calls `update_latency(inf)`
- missing/invalid/stale latency still keeps `ExecutionEngine` in safe mode
- safe mode exits only after finite `LATENCY_OK`
- no threshold was lowered
- no broker path was touched

## Deterministic Test Results

Compile:

```bash
venv/Scripts/python.exe -m py_compile app/execution/engine.py app/main_loop.py app/monitoring/health.py app/monitoring/alerts.py app/data/websocket_client.py app/data/market_feeds.py app/data/polling_client.py app/data/depth_book.py app/data/aggregator.py app/execution/latency_model.py app/execution/throttler.py app/core/decision_compiler.py app/brain/signal_fusion.py app/config.py main.py app/state/state_store.py app/state/hydration_manager.py app/core/intelligence_portfolio_state_truth_spine.py tests/test_lag_abort_infms_shadow_readiness.py
```

Result: passed.

Focused test:

```bash
venv/Scripts/python.exe -m pytest -q tests/test_lag_abort_infms_shadow_readiness.py
```

Result: `8 passed` before the recovery helper extraction, then `9 passed` after adding the explicit warmup-to-OK safe-mode exit proof.

Scoped regression:

```bash
venv/Scripts/python.exe -m pytest -q tests/test_apply_physical_fuse_reset_shadow_readiness.py tests/test_physical_fuse_operator_reset_readiness.py tests/test_final_launch_blocker_burndown_physical_fuse_alpaca_reconciliation.py tests/test_seam7h_operator_monitoring_shadow_launch_readiness.py tests/test_kraken_rest_dns_feed_truth_resilience.py tests/test_seam7g_market_truth_reconciliation_spine.py tests/test_seam7f_risk_capital_defense_execution_economics.py tests/test_pre_trade_guardrail_constraints.py tests/test_intelligence_portfolio_state_truth_spine.py
```

Result: `64 passed`.

Sandbox note: Windows venv pytest hit the known WSL vsock binding error inside sandbox. The same packet-listed pytest commands passed when rerun outside the sandbox.

## Bounded Shadow Result

Approved command:

```bash
timeout 60s venv/Scripts/python.exe main.py --paper --shadow-read-only --log-level INFO
```

Result: exited `124` because the external timeout stopped the long-running runtime at the bound.

Observed:

- paper mode confirmed: `Broker Mode: paper`
- shadow-read-only confirmed: `Shadow Read Only: ENABLED`
- no live mode was used
- startup latency truth was reported as:
  `LATENCY TRUTH BLOCK: status=MISSING_LATENCY_TRUTH reason=WEBSOCKET_RTT_NOT_READY source=order_router.websocket_rtt missing_source=websocket_ping_or_pong_timestamp threshold=200.0ms`
- no `LAG ABORT: infms > 200.0ms` appeared in the bounded command output
- Kraken websocket connected and produced feed ingress
- `FEED_CANDLE`, `FEED_BOOK`, `SHANS_RESULT`, and `FUSION_UPDATE_CALLED` appeared
- Kraken REST DNS failures continued and remain structured feed degradation
- no autonomous paper command was run
- no mutation approval flags were set
- no order submission was intentionally allowed

## Current Readiness Verdict

`NOT_READY_FOR_AUTONOMOUS_PAPER`

The specific false `LAG_ABORT_ACTIVE / infms` blocker is repaired. The runtime now reports the startup condition as missing latency truth instead of fake infinite measured lag.

Remaining blocker:

- `MISSING_LATENCY_TRUTH` must be absent or followed by proven finite `LATENCY_OK` in a clean readiness snapshot before autonomous PAPER can be marked ready.

This is internal timing truth, not an equity market-session issue and not a broker endpoint issue.

## Final Finite RTT Follow-Up

The next burn-down found that the websocket health callback still mixed liveness and RTT truth:

- `KrakenWebSocketClient.connect()` reported `(now, now)` as health on connection.
- `KrakenWebSocketClient._process_message(...)` reported every received message as `(receive_ts_ns, receive_ts_ns)`.

That behavior could initialize a finite zero-millisecond RTT from generic message receipt. It was corrected so router websocket health is emitted only on explicit Kraken `pong`, using the recorded sent ping timestamp and the pong receive timestamp.

Fresh bounded shadow-read-only result after this correction:

- startup: `MISSING_LATENCY_TRUTH`
- post-pong finite recovery: `Latency recovered: 101.1ms, exiting safe mode`
- no `LAG ABORT: infms > 200.0ms`
- no broker mutation or live endpoint markers

Final latency readiness status: finite latency truth proven in shadow, with the `200.0ms` threshold preserved.

## Safety Confirmation

- No live endpoint.
- No autonomous PAPER mutation.
- No order submission.
- No POST/PATCH/DELETE approval flags.
- No cancel/replace.
- No sell or rebalance.
- No emergency liquidation.
- No fake latency, feed, broker, account, position, open-order, PnL, slippage, fee, net-edge, or profitability truth.
