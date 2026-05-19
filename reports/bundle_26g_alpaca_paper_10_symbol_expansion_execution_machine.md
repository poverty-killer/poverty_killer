# BUNDLE 26G - Alpaca Paper 10-Symbol Expansion Execution Machine

Verdict: BLOCKED

Date/time of run:
- `2026-05-19T04:57:01Z`

Current git HEAD before 26G closeout:
- `4d9c89f`

Files changed:
- `tests/test_alpaca_paper_10_symbol_expansion_execution_machine.py`
- `reports/bundle_26g_alpaca_paper_10_symbol_expansion_execution_machine.md`

Production helper files changed and why:
- None.
- 26G was implemented as a governed pytest harness and report only.

Blocked verdict basis:
- Exact 26G approval flag was absent in the test process:
  - `POVERTY_KILLER_APPROVE_ALPACA_PAPER_10_SYMBOL_EXPANSION_26G`: `False`
- Older mutation approval flags were explicitly unset in the test process:
  - `POVERTY_KILLER_APPROVE_ALPACA_PAPER_TINY_ORDER_25Z`: `False`
  - `POVERTY_KILLER_APPROVE_ALPACA_PAPER_10_SYMBOL_BATCH_26B`: `False`
- The real 26G broker path performed read-only Alpaca PAPER and Alpaca DATA GETs only.
- `POST /v2/orders` count: `0`
- Submitted symbols: none
- Reconciled submitted orders: none
- Open orders after read-only reconciliation: `0`
- Positions after read-only reconciliation: `7`
- Account status after read-only reconciliation: `ACTIVE`

Real broker/data calls made:
- Alpaca PAPER endpoint:
  - `https://paper-api.alpaca.markets`
- Alpaca DATA endpoint:
  - `https://data.alpaca.markets`
- Trading HTTP methods observed:
  - `GET`
- Data HTTP methods observed:
  - `GET`
- Live endpoint used: no
- Live mode used: no
- POST used: no
- PATCH used: no
- DELETE used: no
- cancel used: no
- replace used: no
- retry used: no
- sell/rebalance used: no

Account / position / order summary:
- account_status: `ACTIVE`
- cash: `99965`
- buying_power: `199964.96`
- equity: `99999.96`
- portfolio_value: `99999.96`
- open_orders_count: `0`
- active_open_orders_count: `0`
- positions_count: `7`
- current known exposure present:
  - `AAPL`
  - `NVDA`
  - `AMZN`
  - `GOOGL`
  - `TSLA`
  - `SPY`
  - `QQQ`

26G candidate universe:
- `JPM`
- `V`
- `MA`
- `UNH`
- `HD`
- `COST`
- `AVGO`
- `CRM`
- `NFLX`
- `XOM`
- `JNJ`
- `PG`
- `KO`
- `PEP`
- `WMT`

Observed 26G action ledger:
- `JPM`: `SKIP_STALE_QUOTE`; reason `quote_missing`
- `V`: `SKIP_WIDE_SPREAD`; reason `quote_wide_spread`; qty `0.014347`; limit `348.50`; intended_notional `4.99`
- `MA`: `SKIP_WIDE_SPREAD`; reason `quote_wide_spread`; qty `0.009454`; limit `528.83`; intended_notional `4.99`
- `UNH`: `SKIP_WIDE_SPREAD`; reason `quote_wide_spread`; qty `0.012213`; limit `409.39`; intended_notional `4.99`
- `HD`: `SKIP_STALE_QUOTE`; reason `quote_missing`
- `COST`: `SKIP_WIDE_SPREAD`; reason `quote_wide_spread`; qty `0.004549`; limit `1099.12`; intended_notional `4.99`
- `AVGO`: `SKIP_STALE_QUOTE`; reason `quote_missing`
- `CRM`: `SKIP_WIDE_SPREAD`; reason `quote_wide_spread`; qty `0.026455`; limit `189.00`; intended_notional `4.99`
- `NFLX`: `SKIP_WIDE_SPREAD`; reason `quote_wide_spread`; qty `0.053937`; limit `92.70`; intended_notional `4.99`
- `XOM`: `SKIP_WIDE_SPREAD`; reason `quote_wide_spread`; qty `0.029655`; limit `168.60`; intended_notional `4.99`
- `JNJ`: `SKIP_STALE_QUOTE`; reason `quote_missing`
- `PG`: `SKIP_STALE_QUOTE`; reason `quote_missing`
- `KO`: `SKIP_STALE_QUOTE`; reason `quote_missing`
- `PEP`: `SKIP_WIDE_SPREAD`; reason `quote_wide_spread`; qty `0.031748`; limit `157.49`; intended_notional `4.99`
- `WMT`: `SKIP_WIDE_SPREAD`; reason `quote_wide_spread`; qty `0.036161`; limit `138.27`; intended_notional `4.99`

Submission / reconciliation summary:
- attempted_count: `0`
- submitted_count: `0`
- filled_count after reconciliation: `0`
- skipped_count: `15`
- rejected_count: `0`
- ambiguous_count: `0`
- open_orders_after: `0`
- positions_after: `7`
- broker order IDs: none
- client order IDs: none
- Reconciliation did not need direct submitted-order lookups because no order was submitted.

Machine summary:
- Harness verdict: `PAPER_EXPANSION_MACHINE_BLOCKED_BY_APPROVAL`
- Read-only: `true`
- Mutation allowed: `false`
- Subsystem fingerprints match: `true`
- Protective verdict: `PROTECTIVE_INTENT_METADATA_ONLY`
- Economics verdict: `ECONOMICS_ADVISORY_MISSING_TRUTH`
- Live ready: `false`
- New orders require exact 26G approval: `true`
- Post-execution reconciliation required before any future filled/submitted claim: `true`

Fixture / guardrail coverage:
- Missing exact 26G approval blocks before POST.
- Older approval flags do not authorize 26G POST.
- Live endpoint blocks.
- Market order blocks.
- Duplicate per-symbol order blocks.
- Per-symbol notional above `$5.00` blocks.
- More than ten submitted symbols blocks.
- Cancel, replace, DELETE, PATCH, retry, sell, rebalance, and live-mode attempts block.
- Missing quote blocks.
- Stale quote blocks.
- Wide spread blocks.
- Existing exposure blocks.
- Open order conflict blocks.
- Fixture-only cases were not represented as real broker facts.

Tests run:
- `env -u POVERTY_KILLER_APPROVE_ALPACA_PAPER_TINY_ORDER_25Z -u POVERTY_KILLER_APPROVE_ALPACA_PAPER_10_SYMBOL_BATCH_26B -u POVERTY_KILLER_APPROVE_ALPACA_PAPER_10_SYMBOL_EXPANSION_26G /tmp/pk25i-venv/bin/python -m pytest tests/test_alpaca_paper_10_symbol_expansion_execution_machine.py -q -s --tb=short`
  - sandbox result: `1 failed, 4 passed in 2.23s`
  - failure was sandbox DNS for Alpaca PAPER read-only GET: `URLError`
- `env -u POVERTY_KILLER_APPROVE_ALPACA_PAPER_TINY_ORDER_25Z -u POVERTY_KILLER_APPROVE_ALPACA_PAPER_10_SYMBOL_BATCH_26B -u POVERTY_KILLER_APPROVE_ALPACA_PAPER_10_SYMBOL_EXPANSION_26G /tmp/pk25i-venv/bin/python -m pytest tests/test_alpaca_paper_10_symbol_expansion_execution_machine.py -q -s --tb=short`
  - escalated read-only result: `4 passed, 1 skipped in 4.15s`
  - skip reason: exact 26G expansion approval flag missing; no POST allowed
  - trading HTTP methods: `GET`
  - data HTTP methods: `GET`
  - submitted_orders_count: `0`
  - open_orders_count: `0`
  - positions_count: `7`
- `env -u POVERTY_KILLER_APPROVE_ALPACA_PAPER_TINY_ORDER_25Z -u POVERTY_KILLER_APPROVE_ALPACA_PAPER_10_SYMBOL_BATCH_26B -u POVERTY_KILLER_APPROVE_ALPACA_PAPER_10_SYMBOL_EXPANSION_26G /tmp/pk25i-venv/bin/python -m pytest tests/test_alpaca_paper_10_symbol_expansion_execution_machine.py tests/test_integrated_paper_portfolio_machine_seam.py tests/test_controlled_paper_portfolio_lifecycle_exit_defense.py tests/test_controlled_paper_portfolio_runtime_exposure_response.py tests/test_alpaca_paper_portfolio_ownership_reconciliation.py tests/test_alpaca_paper_post_fill_reconciliation_runtime.py tests/test_broker_truth_whole_bot_contribution_readiness.py tests/test_whole_bot_contribution_activation_harness.py tests/test_whole_bot_replay_regime_stress.py tests/test_live_read_only_adapter_config_gate.py tests/test_micro_live_dry_run_readiness_harness.py -q -s --tb=short`
  - escalated read-only baseline result: `52 passed, 1 skipped, 78 warnings in 21.18s`

What this does not authorize:
- No 26G order placement without the exact 26G approval flag and value.
- No reuse of 25Z or 26B approval flags.
- No live endpoint.
- No live mode.
- No cancel.
- No replace.
- No DELETE.
- No PATCH.
- No retry.
- No auto-resubmit.
- No market order.
- No short selling.
- No threshold relaxation.
- No dormant authority activation.
- No PnL, slippage, net edge, profitability, or alpha claim.

Authority boundaries confirmed:
- No production behavior changed.
- No broker_adapter/live_broker edit or activation.
- No live reservation lifecycle activation.
- No NetEdge/TradeEfficiency veto activation.
- No StrategyAllocator/SovereignGovernor/SovereignExecutionGuard activation.
- No threshold changes.
- No routing/execution broadening.
- No duplicate execution/risk/economics authority.
- No secrets printed or written.
