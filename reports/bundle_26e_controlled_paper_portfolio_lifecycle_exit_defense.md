# BUNDLE 26E - Controlled Paper Portfolio Lifecycle / Exit-Defense Seam

Verdict: PASS

Date/time of run:
- `2026-05-19T03:29:20Z`

Current git HEAD:
- `b087781`

Files changed:
- `tests/test_controlled_paper_portfolio_lifecycle_exit_defense.py`
- `reports/bundle_26e_controlled_paper_portfolio_lifecycle_exit_defense.md`

Production helper files changed and why:
- None.
- 26E was implemented as a non-mutating harness/report seam only.

Real broker calls made:
- Alpaca PAPER read-only GET only.
- 26E targeted GET paths:
  - `GET /v2/account`
  - `GET /v2/clock`
  - `GET /v2/positions`
  - `GET /v2/orders?status=open`
  - `GET /v2/account/activities?activity_types=FILL`
- Required baseline also ran the 26D and 26C read-only broker truth harnesses.

GET-only / endpoint / mutation confirmation:
- Endpoint: `https://paper-api.alpaca.markets`
- HTTP methods observed by 26E harness: `GET`
- Live endpoint used: no
- Live mode used: no
- Broker mutation: no
- POST: no
- PATCH: no
- DELETE: no
- cancel: no
- replace: no
- retry: no
- new order: no
- sell/rebalance/stop/take-profit order: no
- mutation approval flags used: no

Account / position / open-order summary:
- account_status: `ACTIVE`
- cash: `99965`
- buying_power: `199965.03`
- equity: `100000.03`
- portfolio_value: `100000.03`
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
    - market_value: `5.021712`
    - average_entry_price: `295.78`
    - side: `long`
    - current_price: `297.09`
  - NVDA:
    - qty: `0.022593`
    - market_value: `4.998701`
    - average_entry_price: `221.284`
    - side: `long`
    - current_price: `221.25`
  - AMZN:
    - qty: `0.018912`
    - market_value: `4.987473`
    - average_entry_price: `264.372`
    - side: `long`
    - current_price: `263.72`
  - GOOGL:
    - qty: `0.012572`
    - market_value: `5.044515`
    - average_entry_price: `397.628`
    - side: `long`
    - current_price: `401.25`
  - TSLA:
    - qty: `0.012195`
    - market_value: `4.964097`
    - average_entry_price: `409.966`
    - side: `long`
    - current_price: `407.06`
  - SPY:
    - qty: `0.006787`
    - market_value: `5.006634`
    - average_entry_price: `736.628`
    - side: `long`
    - current_price: `737.68`
  - QQQ:
    - qty: `0.007111`
    - market_value: `5.004011`
    - average_entry_price: `703.048`
    - side: `long`
    - current_price: `703.7`

Lifecycle classification summary:
- Harness verdict: `PAPER_PORTFOLIO_LIFECYCLE_READY_NON_MUTATING`
- AAPL: `HELD`
- NVDA: `HELD`
- AMZN: `HELD`
- GOOGL: `HELD`
- TSLA: `HELD`
- SPY: `HELD`
- QQQ: `HELD`
- No real broker position had exit pressure in the 26E read-only run.
- A calm held portfolio is valid for this seam because current broker truth had active account, seven expected positions, and zero open orders.

Entry/add-on interaction result:
- `AAPL`: `duplicate_or_add_on_requires_board_approval`
- `NVDA`: `duplicate_or_add_on_requires_board_approval`
- `AMD`: `fresh_entry_blocked_by_26e_lifecycle_scope`
- Existing positions remained recognized as owned exposure.
- Duplicate/add-on entry was not blindly admitted.
- Lifecycle state informed entry/add-on blocking metadata.
- No submit, cancel, replace, route, or broker mutation path was invoked.
- AMD skip reason remains the known historical 26B gap: `reason_not_emitted_by_existing_26b_harness`.
- AMD was not used as exposure evidence because current broker truth did not show an AMD position.

Protective response result:
- Protective output kind: `metadata_intent_only`
- Protective response consumed lifecycle/exposure context.
- Protective response may emit watch/protect/exit-pressure intent in fixture cases.
- Protective response did not authorize fresh entry.
- Protective response did not authorize sell/cancel/replace mutation.
- Protective response did not mutate broker state.

Exit-defense classification result:
- Exit-defense output kind: `exit_pressure_evidence_only`
- Real current portfolio exit intent symbols: none
- Fixture AAPL exit-pressure case produced `EXIT_INTENT_REQUIRES_APPROVAL`
- Exit intent, when present in fixture-only evidence, required Board/operator approval before mutation.
- No sell order submitted.
- No cancel submitted.
- No replace submitted.
- No live reservation lifecycle opened.
- No broker mutation approval flag used.
- Forbidden verdict `EXIT_APPROVED` was never emitted.

Economics advisory result:
- Economics output kind: `advisory_missing_truth_only`
- Economics consumed lifecycle context as advisory evidence only.
- Missing economic truth carried:
  - arrival price
  - slippage
  - net edge
  - profitability basis
  - fee if not returned
- PnL invented/claimed: no
- Slippage invented/claimed: no
- Arrival price invented: no
- Net edge invented/claimed: no
- Profitability invented/claimed: no
- Economics veto authority active: no
- Economics approval authority active: no

Broker no-go / fail-closed fixture results:
- `stale_broker_snapshot` blocked.
- `missing_broker_positions` blocked.
- `broker_local_position_conflict` blocked.
- `nonzero_unknown_open_orders` blocked.
- `orphan_broker_open_order` blocked.
- `local_reservation_conflict` blocked.
- `missing_account_identity` blocked.
- `wrong_environment_or_live_like_endpoint` blocked.
- `missing_fill_basis_for_lifecycle` blocked.
- `missing_market_or_economic_evidence` blocked.
- `protective_intent_attempted_broker_mutation` blocked.
- Fixture-only cases were labeled in test scope and were not represented as real broker facts.
- Unsafe verdicts were never emitted:
  - `LIVE_READY`
  - `LIVE_APPROVED`
  - `SUBMIT_REAL_ORDER`
  - `CANCEL_REAL_ORDER`
  - `SELL_REAL_ORDER`
  - `REBALANCE_REAL_ORDER`
  - `MUTATE_BROKER`
  - `PROFITABLE`
  - `NET_EDGE_POSITIVE`
  - `EXIT_APPROVED`

Approval flag confirmation:
- All 26E targeted and baseline pytest processes were run with both mutation approval flags explicitly removed:
  - `POVERTY_KILLER_APPROVE_ALPACA_PAPER_TINY_ORDER_25Z`
  - `POVERTY_KILLER_APPROVE_ALPACA_PAPER_10_SYMBOL_BATCH_26B`
- 26E test-process confirmation:
  - `POVERTY_KILLER_APPROVE_ALPACA_PAPER_TINY_ORDER_25Z`: `False`
  - `POVERTY_KILLER_APPROVE_ALPACA_PAPER_10_SYMBOL_BATCH_26B`: `False`
- 26E did not require or use a mutation approval flag.

Tests run:
- `env -u POVERTY_KILLER_APPROVE_ALPACA_PAPER_TINY_ORDER_25Z -u POVERTY_KILLER_APPROVE_ALPACA_PAPER_10_SYMBOL_BATCH_26B /tmp/pk25i-venv/bin/python -m pytest tests/test_controlled_paper_portfolio_lifecycle_exit_defense.py -q -s --tb=short`
# result
  - sandbox run: `1 failed, 4 passed in 3.12s`
  - failure was sandbox DNS for Alpaca PAPER read-only GET: `URLError`
- `env -u POVERTY_KILLER_APPROVE_ALPACA_PAPER_TINY_ORDER_25Z -u POVERTY_KILLER_APPROVE_ALPACA_PAPER_10_SYMBOL_BATCH_26B /tmp/pk25i-venv/bin/python -m pytest tests/test_controlled_paper_portfolio_lifecycle_exit_defense.py -q -s --tb=short`
# result
  - escalated Alpaca PAPER read-only run: `5 passed in 2.16s`
  - HTTP methods: `GET`
  - open orders: `0`
  - positions: `7`
- `env -u POVERTY_KILLER_APPROVE_ALPACA_PAPER_TINY_ORDER_25Z -u POVERTY_KILLER_APPROVE_ALPACA_PAPER_10_SYMBOL_BATCH_26B /tmp/pk25i-venv/bin/python -m pytest tests/test_controlled_paper_portfolio_lifecycle_exit_defense.py tests/test_controlled_paper_portfolio_runtime_exposure_response.py tests/test_alpaca_paper_portfolio_ownership_reconciliation.py tests/test_broker_truth_whole_bot_contribution_readiness.py tests/test_whole_bot_contribution_activation_harness.py tests/test_live_read_only_adapter_config_gate.py tests/test_micro_live_dry_run_readiness_harness.py -q -s --tb=short`
# result
  - `35 passed, 74 warnings in 13.76s`

Authority boundary confirmation:
- Execution authority remains with the existing paper path: DecisionCompiler / ExecutionEngine / OrderRouter / PaperBroker.
- No production routing broadening.
- No execution-path broadening.
- No broker mutation implementation.
- No broker_adapter.py edit or activation.
- No live_broker.py edit or activation.
- Live reservation lifecycle remains disabled.
- NetEdgeGovernor and TradeEfficiencyGovernor remain advisory/dormant, not active veto authority.
- SovereignExecutionGuard was not activated.
- StrategyAllocator / SovereignGovernor were not activated.
- HydrationManager / TruthKernel / InvariantChecker were not made runtime authority.
- Protective modules remained metadata/intent only and did not mutate broker state.
- No fake broker account, position, fill, or open-order facts.
- No invented PnL, slippage, arrival price, net edge, profitability, or alpha.
- No threshold changes.

Secrets confirmation:
- Alpaca credentials were used from environment / local credential file only.
- Secrets were not printed.
- Secrets were not written to the report.
- Secrets were not committed.

Final verdict:
- PASS.
- 26E consumed real Alpaca PAPER read-only portfolio truth.
- Owned-position lifecycle classification was proven.
- Lifecycle state influenced entry/protective/economics/readiness behavior without mutation.
- Exit-pressure / exit-defense classification remained evidence-only and required approval before any mutation.
- Protective response remained metadata/intent only.
- Economics remained advisory and did not invent facts.
- Broker no-go fixture states failed closed.
- No live mode, broker mutation, or secret exposure occurred.
