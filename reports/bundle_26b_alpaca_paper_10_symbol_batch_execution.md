# BUNDLE 26B - Controlled 10-Symbol Alpaca Paper Batch Execution + Reconciliation

Verdict: CONDITIONAL

Changed files:
- `tests/test_alpaca_paper_10_symbol_batch_execution.py`
- `reports/bundle_26b_alpaca_paper_10_symbol_batch_execution.md`

Run status:
- 26B actual Alpaca PAPER batch execution completed once under the explicit approval flag.
- The approval flag has since been unset or must be treated as absent.
- Do not rerun the mutating harness.
- Do not POST again.
- Do not submit more orders.
- Do not cancel.
- Do not replace.

Tests / commands run:
- `/tmp/pk25i-venv/bin/python -m pytest tests/test_alpaca_paper_10_symbol_batch_execution.py -q -s -rs --tb=short`
# result
  - `5 passed in 5.56s`
  - Harness summary emitted:
    - `attempted_count`: `6`
    - `submitted_count`: `6`
    - `filled_count`: `0` at immediate ACK classification
    - `open_count`: `6` at immediate ACK classification
    - `rejected_count`: `0`
    - `ambiguous_count`: `0`
    - `skipped_count`: `4`
    - `open_orders_after`: `0`
    - `positions_after`: `7`
    - `account_status_after`: `ACTIVE`
- Read-only Alpaca PAPER reconciliation GETs after the mutating run
# result
  - Six 26B client-order IDs were found as filled.
  - No open orders remained after reconciliation.
  - No cancel, replace, retry, live endpoint, or live mode was used.

10-symbol batch execution:
- Approval:
  - Present for the completed execution run.
  - Now unset or treated as absent.
  - No further mutating run is authorized by this report.
- Endpoint / mode:
  - Alpaca PAPER only.
  - No live endpoint.
  - No live mode.
- Submit:
  - `POST /v2/orders` count: `6`.
  - One POST per submitted eligible symbol.
  - No retry.
  - No cancel.
  - No replace.
- Reconciliation:
  - Filled after read-only reconciliation: `6`.
  - Open orders after reconciliation: `0`.
  - Rejected: `0`.
  - Ambiguous: `0`.
  - Account status after: `ACTIVE`.
  - Positions after: `7`.

Batch result summary:
- attempted_count: `6`
- submitted_count: `6`
- filled_count after read-only reconciliation: `6`
- skipped_count: `4`
- rejected_count: `0`
- ambiguous_count: `0`
- open_orders_after: `0`
- positions_after: `7`
- account status after: `ACTIVE`
- `POST /v2/orders` count: `6`

Submitted and filled:
- NVDA:
  - qty: `0.022593`
  - limit: `221.3`
  - avg fill: `221.284`
- AMZN:
  - qty: `0.018912`
  - limit: `264.38`
  - avg fill: `264.372`
- GOOGL:
  - qty: `0.012572`
  - limit: `397.68`
  - avg fill: `397.628`
- TSLA:
  - qty: `0.012195`
  - limit: `409.98`
  - avg fill: `409.966`
- SPY:
  - qty: `0.006787`
  - limit: `736.67`
  - avg fill: `736.628`
- QQQ:
  - qty: `0.007111`
  - limit: `703.12`
  - avg fill: `703.048`

Skipped safely:
- AAPL:
  - reason: `existing_position_present`
- MSFT:
  - reason: `quote_wide_spread`
- META:
  - reason: `quote_wide_spread`
- AMD:
  - reason: skipped, exact reason not emitted by the existing harness.
  - gap: Current harness summary emits aggregate `skipped_count` but does not preserve the exact original per-symbol skip reason for every skipped symbol. AMD must be carried as a documentation gap unless a future read-only-only reporting path can recover it without any POST risk.

Conditional verdict basis:
- PASS: Six symbols were submitted through Alpaca PAPER and filled successfully.
- PASS: Four symbols were skipped safely.
- PASS: No open orders remained after read-only reconciliation.
- PASS: No rejected or ambiguous submission remained in the recorded outcome.
- PASS: No cancel, replace, retry, live endpoint, or live mode was used.
- GAP: AMD skip reason was not emitted by the current harness.
- CONDITION: Do not rerun the mutating harness; the approval flag is absent or must be treated as absent.

Adversarial no-go cases preserved by the harness:
- Missing 26B batch approval blocks before POST.
- Live endpoint blocks.
- Market order blocks.
- Per-symbol notional above `$5.00` blocks.
- Duplicate symbol / multiple orders for same symbol blocks.
- More than ten symbols blocks.
- Retry enabled blocks.
- Auto-resubmit enabled blocks.
- Existing open order conflict skips the symbol.
- Existing position conflict skips the symbol.
- Missing quote skips the symbol.
- Stale quote skips the symbol.
- Zero/negative derived quantity skips the symbol.
- Wide spread skips the symbol.
- Attempted cancel blocks.
- Attempted replace blocks.
- Duplicate POST per symbol is rejected.
- Economics veto activation attempt blocks.
- broker_adapter activation attempt blocks.
- live_broker activation attempt blocks.
- Live mode blocks.
- Live reservation lifecycle blocks.

What this does NOT authorize:
- No further order placement.
- No order placement without the exact 26B approval flag.
- No live endpoint.
- No live mode.
- No cancel.
- No replace.
- No DELETE.
- No PATCH.
- No retry.
- No auto-resubmit.
- No more than 10 POSTs in the completed batch.
- No more than one POST per submitted symbol.
- No notional above `$5.00` per symbol.
- No market orders.
- No short selling.
- No dormant authority activation.
- No PnL, slippage, net edge, profitability, or alpha claim.

Authority boundaries confirmed:
- No production behavior changed by this report update.
- No broker_adapter/live_broker activation.
- No live reservation lifecycle activation.
- No NetEdge/TradeEfficiency veto activation.
- No StrategyAllocator/SovereignGovernor/SovereignExecutionGuard activation.
- No threshold changes.
- No routing/execution broadening.
- No duplicate execution/risk/economics authority.

Confirmations:
- Production behavior changed: no
- Report update only: yes
- Real broker/network call made by this report update: no
- Credentials printed/written/committed: no
- Live endpoint used: no
- Paper endpoint used in completed 26B run: yes
- Orders placed in completed 26B run: yes, count `6`
- Additional orders placed after completed 26B run: no
- Cancels sent: no
- Replaces sent: no
- HTTP methods used in completed 26B run:
  - GET preflight and reconciliation
  - POST `/v2/orders` count `6`
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
