# BUNDLE 26D - Controlled Paper Portfolio Runtime / Exposure Response

Verdict: PASS

Date/time of run:
- `2026-05-19T03:10:31Z`

Current git HEAD:
- `b8f3458`

Files changed:
- `tests/test_controlled_paper_portfolio_runtime_exposure_response.py`
- `reports/bundle_26d_controlled_paper_portfolio_runtime_exposure_response.md`

Real broker calls made:
- Alpaca PAPER read-only GET only.
- 26D targeted GET paths:
  - `GET /v2/account`
  - `GET /v2/clock`
  - `GET /v2/positions`
  - `GET /v2/orders?status=open`
  - `GET /v2/account/activities?activity_types=FILL`
- Required baseline also ran 26C read-only reconciliation, including known-order read-only reconciliation GETs.

GET-only / endpoint confirmation:
- Endpoint: `https://paper-api.alpaca.markets`
- HTTP methods observed by 26D harness: `GET`
- No POST.
- No PATCH.
- No DELETE.
- No cancel.
- No replace.
- No retry.
- No live endpoint.
- No live mode.

Account / position / open-order summary:
- account_status: `ACTIVE`
- cash: `99965`
- buying_power: `199964.98`
- equity: `99999.98`
- portfolio_value: `99999.98`
- open_orders_count: `0`
- active_open_orders_count: `0`
- positions_count: `7`
- expected positions present:
  - `AAPL`
  - `NVDA`
  - `AMZN`
  - `GOOGL`
  - `TSLA`
  - `SPY`
  - `QQQ`
- positions:
  - AAPL:
    - qty: `0.016903`
    - market_value: `5.020529`
    - average_entry_price: `295.78`
    - side: `long`
    - current_price: `297.02`
  - NVDA:
    - qty: `0.022593`
    - market_value: `4.987857`
    - average_entry_price: `221.284`
    - side: `long`
    - current_price: `220.77`
  - AMZN:
    - qty: `0.018912`
    - market_value: `4.987473`
    - average_entry_price: `264.372`
    - side: `long`
    - current_price: `263.72`
  - GOOGL:
    - qty: `0.012572`
    - market_value: `5.027543`
    - average_entry_price: `397.628`
    - side: `long`
    - current_price: `399.9`
  - TSLA:
    - qty: `0.012195`
    - market_value: `4.956414`
    - average_entry_price: `409.966`
    - side: `long`
    - current_price: `406.43`
  - SPY:
    - qty: `0.006787`
    - market_value: `5.001205`
    - average_entry_price: `736.628`
    - side: `long`
    - current_price: `736.88`
  - QQQ:
    - qty: `0.007111`
    - market_value: `5.000029`
    - average_entry_price: `703.048`
    - side: `long`
    - current_price: `703.14`

Exposure-aware entry response result:
- Harness verdict: `PAPER_EXPOSURE_RESPONSE_READY`
- `AAPL`: `existing_exposure_requires_board_approval`
- `NVDA`: `existing_exposure_requires_board_approval`
- `MSFT`: `blocked_pending_portfolio_aware_board_packet`
- `AMD`: `blocked_pending_portfolio_aware_board_packet`
- Duplicate/add-on entry candidates were not blindly admitted.
- No entry response called submit, router, or broker mutation.
- No threshold was changed.
- AMD skip reason remains the known 26B gap: `reason_not_emitted_by_existing_26b_harness`.
- AMD was not used as real exposure evidence because broker truth did not show an AMD position.

Protective response result:
- Protective response referenced current broker exposure.
- Protective output kind: `metadata_intent_only`.
- Protective response did not authorize fresh entry.
- Protective response did not call submit, cancel, replace, router, or broker mutation.
- Protective modules remain non-executing evidence/intent surfaces unless separately consumed by proven execution authority in a future packet.

Economics advisory result:
- Economics output kind: `advisory_only`.
- Missing economic truth carried:
  - arrival price
  - slippage
  - net edge
  - fee if not returned
  - profitability basis
- PnL claimed: no.
- Slippage claimed: no.
- Arrival price invented: no.
- Net edge claimed: no.
- Profitability claimed: no.
- Economics veto authority active: no.
- Entry authority active: no.

Broker no-go / fail-closed fixture results:
- `stale_broker_snapshot` blocked.
- `missing_broker_positions` blocked.
- `local_broker_position_conflict` blocked.
- `unknown_or_nonzero_open_orders` blocked.
- `orphan_broker_open_order` blocked.
- `local_reservation_conflict` blocked.
- `missing_account_identity` blocked.
- `wrong_environment_or_live_like_endpoint` blocked.
- Fixture-only cases were labeled and were not represented as real broker facts.
- Unsafe verdicts were never emitted:
  - `LIVE_READY`
  - `LIVE_APPROVED`
  - `SUBMIT_REAL_ORDER`
  - `CANCEL_REAL_ORDER`
  - `MUTATE_BROKER`
  - `PROFITABLE`
  - `NET_EDGE_POSITIVE`

Approval flag confirmation:
- Ambient shell had the 26B approval value present before 26D test execution.
- All 26D targeted and baseline pytest processes were run with both mutation approval flags explicitly removed:
  - `POVERTY_KILLER_APPROVE_ALPACA_PAPER_TINY_ORDER_25Z`
  - `POVERTY_KILLER_APPROVE_ALPACA_PAPER_10_SYMBOL_BATCH_26B`
- 26D test-process confirmation:
  - `POVERTY_KILLER_APPROVE_ALPACA_PAPER_TINY_ORDER_25Z`: `False`
  - `POVERTY_KILLER_APPROVE_ALPACA_PAPER_10_SYMBOL_BATCH_26B`: `False`
- 26D does not require or use a mutation approval flag.

Tests run:
- `env -u POVERTY_KILLER_APPROVE_ALPACA_PAPER_TINY_ORDER_25Z -u POVERTY_KILLER_APPROVE_ALPACA_PAPER_10_SYMBOL_BATCH_26B /tmp/pk25i-venv/bin/python -m pytest tests/test_controlled_paper_portfolio_runtime_exposure_response.py -q -s --tb=short`
# result
  - initial sandbox run: `2 failed, 2 passed in 5.30s`
  - one fixture reason-code spelling bug was found and fixed
  - sandbox network also blocked Alpaca PAPER read-only GET with `URLError`
- `env -u POVERTY_KILLER_APPROVE_ALPACA_PAPER_TINY_ORDER_25Z -u POVERTY_KILLER_APPROVE_ALPACA_PAPER_10_SYMBOL_BATCH_26B /tmp/pk25i-venv/bin/python -m pytest tests/test_controlled_paper_portfolio_runtime_exposure_response.py -q -s --tb=short`
# result
  - escalated Alpaca PAPER read-only run: `4 passed in 2.79s`
  - HTTP methods: `GET`
  - open orders: `0`
  - positions: `7`
- `env -u POVERTY_KILLER_APPROVE_ALPACA_PAPER_TINY_ORDER_25Z -u POVERTY_KILLER_APPROVE_ALPACA_PAPER_10_SYMBOL_BATCH_26B /tmp/pk25i-venv/bin/python -m pytest tests/test_controlled_paper_portfolio_runtime_exposure_response.py tests/test_alpaca_paper_portfolio_ownership_reconciliation.py tests/test_broker_truth_whole_bot_contribution_readiness.py tests/test_whole_bot_contribution_activation_harness.py tests/test_live_read_only_adapter_config_gate.py tests/test_micro_live_dry_run_readiness_harness.py -q -s --tb=short`
# result
  - `30 passed, 74 warnings in 16.37s`

Authority boundary confirmation:
- Execution authority remains with existing paper execution path authority; 26D did not broaden it.
- `broker_adapter.py` was not edited or activated.
- `live_broker.py` was not edited or activated.
- Live reservation lifecycle remains disabled.
- NetEdgeGovernor and TradeEfficiencyGovernor remain advisory/dormant, not active veto authority.
- StrategyAllocator / SovereignGovernor were not activated.
- SovereignExecutionGuard was not activated.
- HydrationManager / TruthKernel / InvariantChecker were not made production runtime authority.
- No production routing broadening.
- No execution-path broadening.
- No threshold changes.
- No fake local fills.
- No fake broker facts.
- No invented PnL, slippage, arrival price, net edge, profitability, or alpha.

Secrets confirmation:
- Alpaca credentials were used from environment / local credential file only.
- Secrets were not printed.
- Secrets were not written to report output.
- Secrets were not committed.

Final verdict:
- PASS.
- 26D consumed real Alpaca PAPER broker exposure in read-only mode.
- Existing exposure changed entry/readiness behavior without mutation.
- Protective response remained non-executing.
- Economics remained advisory and did not invent facts.
- Broker no-go fixture states failed closed.
- No live mode, broker mutation, or secret exposure occurred.
