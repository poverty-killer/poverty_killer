# BUNDLE 25Z / 25Z-B - Alpaca Paper Tiny Order Execution

Verdict: PASS after manual read-only reconciliation.

Changed files:
- `tests/test_alpaca_paper_tiny_order_execution.py`
- `reports/bundle_25z_alpaca_paper_tiny_order_execution.md`

What changed:
- The 25Z execution test no longer assumes a submitted paper order must remain in `GET /v2/orders?status=open`.
- Reconciliation now accepts either a matching open order by `client_order_id` / broker order ID, or a direct read-only `GET /v2/orders/{broker_order_id}` result showing the same identity with `filled` terminal status.
- The exactly-one-POST guard remains.
- The approval gate remains.
- No retry, cancel, replace, live endpoint, live mode, secret printing, or broad execution surface was added.

Actual broker truth from the prior approved 25Z-B manual run:
- One Alpaca PAPER order was placed and filled.
- `broker_order_id`: `b47cdef4-a913-4517-9cac-5d96f319de91`
- `client_order_id`: `pk25z-paper-aapl-buy-limit-day-1777948800000000100`
- `symbol`: `AAPL`
- `side`: `buy`
- `type`: `limit`
- `time_in_force`: `day`
- `qty`: `0.016903`
- `limit_price`: `295.79`
- `status`: `filled`
- `filled_qty`: `0.016903`
- `created_at` / `submitted_at`: `2026-05-18T17:10:54.81619546Z`
- `updated_at`: `2026-05-18T17:10:54.832884729Z`
- Open orders after lookup: `[]`

Tests run:
- `python -c "import os; print('approval_absent=' + str(os.environ.get('POVERTY_KILLER_APPROVE_ALPACA_PAPER_TINY_ORDER_25Z') is None))"`
  - Result: `approval_absent=True`
- `/tmp/pk25i-venv/bin/python -m pytest tests/test_alpaca_paper_tiny_order_execution.py -q -s --tb=short`
  - Result: `5 passed, 1 skipped in 1.62s`
  - The real execution path skipped before network POST because the approval flag was absent.
  - The recorded/manual reconciliation fixture proved the filled-order/direct-lookup path without posting.
- `/tmp/pk25i-venv/bin/python -m pytest tests/test_alpaca_paper_tiny_order_planning_arming.py tests/test_alpaca_paper_read_only_broker_truth.py tests/test_whole_bot_replay_regime_stress.py tests/test_whole_bot_contribution_activation_harness.py tests/test_broker_truth_whole_bot_contribution_readiness.py tests/test_live_read_only_adapter_config_gate.py tests/test_runtime_reservation_bootstrap.py tests/test_order_lifecycle_replay.py tests/test_execution_sr_decimal.py -q --tb=short`
  - Sandbox result: `3 failed, 50 passed, 2 skipped, 80 warnings in 24.55s`
  - Failure cause: sandbox DNS resolution errors on read-only Alpaca GETs.
  - Escalated read-only rerun result: `55 passed, 80 warnings in 16.14s`

Rerun mutation/accounting:
- POSTs in this rerun: none.
- Approval flag absent in this rerun: yes.
- Secrets printed or written: no.
- Second order POST: no.
- Cancel sent: no.
- Replace sent: no.
- DELETE/PATCH sent: no.
- Live endpoint used: no.
- Live mode used: no.
- Broker mutation in this rerun: no.
- Paper read-only GETs in baseline: yes.
- Approval flag after the order: absent/unset in this process.
- Staging/commit/push/reset/clean/stash/delete: none.

Authority boundaries confirmed:
- No production behavior changed outside the scoped 25Z test harness/report.
- `broker_adapter` and `live_broker` were not edited.
- No live reservation lifecycle was activated.
- No thresholds were relaxed.
- No routing or execution authority was broadened.
- No duplicate authority was introduced.
