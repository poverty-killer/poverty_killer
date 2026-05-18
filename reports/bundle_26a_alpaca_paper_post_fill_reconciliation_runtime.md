# BUNDLE 26A - Alpaca Paper Post-Fill Reconciliation / Runtime Integration

Verdict: PASS

Changed files:
- `tests/test_alpaca_paper_post_fill_reconciliation_runtime.py`
- `reports/bundle_26a_alpaca_paper_post_fill_reconciliation_runtime.md`

Tests run:
- `python -c "import os; print('approval_absent=' + str(os.environ.get('POVERTY_KILLER_APPROVE_ALPACA_PAPER_TINY_ORDER_25Z') is None))"`
# result
  - `approval_absent=True`
- `python -m py_compile tests/test_alpaca_paper_post_fill_reconciliation_runtime.py`
# result
  - pass
- `/tmp/pk25i-venv/bin/python -m pytest tests/test_alpaca_paper_post_fill_reconciliation_runtime.py -q -s --tb=short`
# result
  - sandbox/offline: `5 passed, 1 skipped, 72 warnings in 2.87s`
  - optional real read-only reconfirmation skipped in sandbox network.
- `/tmp/pk25i-venv/bin/python -m pytest tests/test_alpaca_paper_post_fill_reconciliation_runtime.py -q -s --tb=short`
# result
  - escalated read-only rerun: `6 passed, 72 warnings in 3.33s`
  - sanitized read-only summary: order `filled`, zero matching active open orders, AAPL position present at `0.016903`, matching activity fill found with price `295.78`, fee value not returned.
- `/tmp/pk25i-venv/bin/python -m pytest tests/test_alpaca_paper_tiny_order_execution.py tests/test_alpaca_paper_tiny_order_planning_arming.py tests/test_alpaca_paper_read_only_broker_truth.py tests/test_whole_bot_replay_regime_stress.py tests/test_whole_bot_contribution_activation_harness.py tests/test_broker_truth_whole_bot_contribution_readiness.py tests/test_live_read_only_adapter_config_gate.py tests/test_runtime_reservation_bootstrap.py tests/test_order_lifecycle_replay.py tests/test_execution_sr_decimal.py -q -s --tb=short`
# result
  - baseline escalated read-only run: `60 passed, 1 skipped, 80 warnings in 18.21s`

Post-fill reconciliation / runtime integration:
- Broker order reconfirmation:
  - Real Alpaca PAPER read-only reconfirmation ran.
  - `GET /v2/orders/{broker_order_id}` confirmed the order exists and is `filled`.
  - `GET /v2/orders?status=open` found zero matching active open orders.
  - `GET /v2/positions` reported current AAPL position qty `0.016903`.
  - `GET /v2/account` returned account truth.
  - `GET /v2/account/activities` found a matching FILL activity with price `295.78`; fee value was not returned.
- Order/client ID mapping:
  - Mapping is one-to-one across broker order ID, client order ID, deterministic external order intent ID, and deterministic execution event candidate.
  - Missing broker order ID, missing client order ID, mismatched symbol, side, qty, or filled qty fail closed.
  - Idempotency key: `alpaca-paper-fill:b47cdef4-a913-4517-9cac-5d96f319de91:pk25z-paper-aapl-buy-limit-day-1777948800000000100:filled:0.016903`.
- Fill / telemetry evidence:
  - FillRecorder-compatible passive order-lifecycle evidence was persisted through `FillRecorder.record_order_lifecycle_event`.
  - DecisionCompiler decision UUID is explicitly absent because this was a manual external Alpaca PAPER order; the test uses deterministic local ID `manual-alpaca-paper-25z-b-no-decision-compiler`.
  - Order intent ID is deterministic test/local ID `external-alpaca-paper-intent:pk25z-paper-aapl-buy-limit-day-1777948800000000100`.
  - Remaining qty is `0`, status is `filled`, source is Alpaca PAPER read-only truth.
  - No actual fill price was invented from the order payload; real activity fill price `295.78` is recorded only as broker-returned activity truth.
  - No fee, fee currency, slippage, PnL, net edge, or profitability was invented.
- Economic truth classification:
  - `economics_truth_status = partial/passive`.
  - Limit-price notional estimate: `0.016903 * 295.79 = 4.99973837`.
  - Real activity fill price exists: `295.78`; fee value remains absent.
  - PnL, slippage, net edge, fee-adjusted result, and profitability remain uncomputed gaps.
- Reservation / exposure candidate model:
  - Filled terminal truth produces a passive release candidate only.
  - Candidate requires broker order identity, client order identity, filled status, filled qty, and terminal truth.
  - No live reservation mutation, exposure mutation, release mutation, or active reservation ledger creation occurred.
  - Local reservation absence is expected because the order was an external/manual Alpaca PAPER test packet, not a DecisionCompiler path.
- Position/account/open-order reconciliation:
  - Open orders do not contain a matching active order.
  - Terminal filled order truth wins over empty open orders.
  - AAPL position is present at broker with qty `0.016903`; broker position truth is canonical.
  - The bot must not assume flat state after this fill.
  - Local/broker mismatch is classified as expected external-paper-order reconciliation work and blocks flat-state assumptions.
- Recovery / replay idempotency:
  - Reprocessing the same broker filled order maps to the same idempotency key.
  - Replay projection stores one telemetry candidate and treats the second processing as idempotent.
  - Terminal filled state remains terminal.
  - Empty open orders do not resurrect an open reservation.
  - Approval flag absent prevents the 25Z execution test from reaching any POST path.

Broker truth:
- broker_order_id: `b47cdef4-a913-4517-9cac-5d96f319de91`
- client_order_id: `pk25z-paper-aapl-buy-limit-day-1777948800000000100`
- symbol: `AAPL`
- side: `buy`
- type: `limit`
- time_in_force: `day`
- qty: `0.016903`
- filled_qty: `0.016903`
- limit_price: `295.79`
- actual_fill_price if returned: `295.78` from matching account activity FILL
- fee if returned: not returned
- fee_currency if returned: not returned; account currency observed as `USD`
- status: `filled`
- submitted_at: `2026-05-18T17:10:54.81619546Z`
- updated_at: `2026-05-18T17:10:54.832884729Z`
- open_orders_current: zero matching active open orders
- position_current: AAPL position present, qty `0.016903`

Gaps explicitly carried:
- No DecisionCompiler decision UUID exists for this external/manual paper order.
- No production order intent exists for this external/manual paper order.
- Fee not returned.
- Fee currency not returned as a fee field.
- Slippage not computed.
- Net edge not computed.
- PnL not computed.
- Profitability not claimed.
- Local runtime did not own the original order path; local/broker reconciliation remains required before any flat-state assumption.

Recommended next packet:
- 26B - Alpaca Paper Controlled Batch Planning / Arming
- Why this is the single next seam:
  - 26A proved the one real filled Alpaca PAPER order can be represented, reconciled, made passive-telemetry-compatible, and replayed idempotently without broker mutation.
  - The next capability should plan a controlled 10-symbol tiny PAPER batch without execution, using the 25Z/26A broker-truth and post-fill ownership constraints.

Authority boundaries confirmed:
- No production behavior changed.
- No broker POST, PATCH, DELETE, cancel, or replace.
- No second order.
- No live endpoint.
- No live mode.
- No broker_adapter/live_broker activation.
- No live reservation lifecycle activation.
- No NetEdge/TradeEfficiency veto activation.
- No StrategyAllocator/SovereignGovernor/SovereignExecutionGuard activation.
- No threshold changes.
- No routing/execution broadening.
- No duplicate execution/risk/economics authority.

Confirmations:
- Production behavior changed: no
- If yes, exact helper only:
  - n/a
- Real broker/network call made: yes, Alpaca PAPER read-only only
- Credentials used: yes, env vars only
- Secrets printed/written/committed: no
- Live endpoint used: no
- Paper endpoint used: yes
- Order placed in this packet: no
- Cancel sent: no
- Replace sent: no
- HTTP methods used:
  - GET only
- Live mode used: no
- broker_adapter edited/activated: no
- live_broker edited/activated: no
- Live reservation lifecycle activated: no
- Dormant governors activated: no
- Economics veto activated: no
- Thresholds changed: no
- Routing/execution broadened: no
- Duplicate authority introduced: no
- Git staging/commit/push/reset/clean/stash/delete: none
