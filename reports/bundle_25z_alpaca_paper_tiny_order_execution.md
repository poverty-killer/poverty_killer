# BUNDLE 25Z - Alpaca Paper Tiny Order Execution

Verdict: BLOCKED

Changed files:
- `tests/test_alpaca_paper_tiny_order_execution.py`
- `reports/bundle_25z_alpaca_paper_tiny_order_execution.md`

Tests run:
- `/tmp/pk25i-venv/bin/python -m pytest tests/test_alpaca_paper_tiny_order_execution.py -q -s --tb=short`
# result
  - `4 passed, 1 skipped in 0.96s`
  - The real execution test skipped before network POST because `POVERTY_KILLER_APPROVE_ALPACA_PAPER_TINY_ORDER_25Z` was not set to `YES_I_APPROVE_ONE_PAPER_LIMIT_ORDER`.
- `/tmp/pk25i-venv/bin/python -m pytest tests/test_alpaca_paper_tiny_order_planning_arming.py tests/test_alpaca_paper_read_only_broker_truth.py tests/test_whole_bot_replay_regime_stress.py tests/test_whole_bot_contribution_activation_harness.py tests/test_broker_truth_whole_bot_contribution_readiness.py tests/test_live_read_only_adapter_config_gate.py tests/test_runtime_reservation_bootstrap.py tests/test_order_lifecycle_replay.py tests/test_execution_sr_decimal.py -q --tb=short`
# result
  - `55 passed, 80 warnings in 15.45s`

Tiny Alpaca PAPER order execution:
- Board approval:
  - BLOCKED before POST.
  - Required approval flag missing: `POVERTY_KILLER_APPROVE_ALPACA_PAPER_TINY_ORDER_25Z=YES_I_APPROVE_ONE_PAPER_LIMIT_ORDER`.
  - The harness does not default to approved.
- Preflight:
  - Alpaca PAPER env was internally checked as present and exact for PAPER.
  - Actual execution preflight was not allowed to proceed to POST because Board approval flag was missing.
  - Offline gate tests proved account/order/position/local-safety no-go behavior before POST.
- Quote / price basis:
  - No live quote was fetched for execution because approval was missing.
  - Offline quote fixtures proved bounded LIMIT price and no-go behavior for missing, stale, wide-spread, and invalid price basis.
  - No real price was invented.
- Quantity / notional:
  - Offline clean fixture computed a bounded fractional quantity from a fixture ask price and verified notional stayed under `$5.00`.
  - No real order quantity was sent.
  - Missing, zero, invalid, or oversized quantity/notional gates block before POST.
- Submit:
  - No submit occurred.
  - Exactly zero `POST /v2/orders` calls were sent.
  - The real submit test skips before POST unless the explicit 25Z approval flag is present.
- ACK / broker response:
  - No ACK exists because no order was submitted.
  - ACK parsing requirements are encoded for the approved path, but no broker mutation happened in this run.
- Post-submit reconciliation:
  - Not applicable because no order was submitted.
  - Baseline read-only Alpaca broker truth tests still passed.
- Telemetry/report evidence:
  - Report records BLOCKED state, no order identity, no fill claim, no PnL, no slippage, no net edge, no profitability.

Order result:
- broker_order_id_masked: n/a
- client_order_id: n/a
- symbol: AAPL planned only
- side: BUY planned only
- type: LIMIT planned only
- time_in_force: DAY planned only
- qty/notional: not submitted; planned cap `$5.00`
- limit_price: not submitted; no real price invented
- status: not submitted
- filled_qty if returned: n/a
- submitted_at if returned: n/a

Adversarial no-go cases proven:
- Missing Board approval flag blocks before POST.
- Live endpoint configured blocks before POST.
- Market order requested blocks before POST.
- Notional above `$5.00` blocks before POST.
- Missing quote blocks before POST.
- Stale quote blocks before POST.
- Wide spread blocks before POST.
- Missing/invalid limit price blocks before POST.
- Multiple orders block before POST.
- Multiple symbols block before POST.
- Short sell blocks before POST.
- Extended hours blocks before POST.
- Bracket/OCO/OTO fields block before POST.
- Existing open AAPL order blocks before POST.
- Existing AAPL position without explicit approval blocks before POST.
- Missing account truth blocks before POST.
- Missing buying power/cash blocks before POST.
- Kill switch active blocks before POST.
- broker_adapter activation attempt blocks before POST.
- live_broker activation attempt blocks before POST.

What this does NOT authorize:
- No order placement.
- No cancel.
- No replace.
- No DELETE.
- No PATCH.
- No second POST.
- No live endpoint.
- No live mode.
- No live reservation lifecycle.
- No broker_adapter/live_broker activation.
- No invented price.
- No invented PnL, slippage, net edge, profitability, or alpha.
- No future execution without explicit approval flag and fresh preflight.

Recommended next packet:
- 25Z-RERUN - Board-Approved Alpaca Paper Tiny Order Execution With Approval Flag
- Why this is the single next seam:
  - 25Z harness and no-go gates are in place.
  - The only blocker in this run is the missing explicit Board approval flag.
  - A rerun with that exact flag present can attempt one controlled Alpaca PAPER `POST /v2/orders` only if all fresh preflight, quote, quantity, and local safety gates pass.

Authority boundaries confirmed:
- No production behavior changed.
- No live endpoint.
- No live mode.
- No broker_adapter/live_broker activation.
- No live reservation lifecycle.
- No cancel/replace/delete/patch.
- No retry storm.
- No thresholds changed.
- No routing/execution broadened.
- No duplicate authority.

Confirmations:
- Production behavior changed: no
- If yes, exact helper only:
  - n/a
- Real broker/network call made: yes, Alpaca PAPER read-only only in baseline; no execution POST
- Credentials used: yes, env vars only for read-only baseline
- Secrets printed/written/committed: no
- Live endpoint used: no
- Paper endpoint used: yes
- Order placed: no
- Cancel sent: no
- Replace sent: no
- HTTP methods used:
  - GET in baseline read-only tests
  - POST /v2/orders: no, approval flag missing
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
