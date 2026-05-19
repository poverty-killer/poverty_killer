# BUNDLE 26F - Integrated Paper Portfolio Machine Seam

Verdict: PASS

Date/time of run:
- `2026-05-19T04:03:33Z`

Current git HEAD:
- `a9a09b9`

Files changed:
- `tests/test_integrated_paper_portfolio_machine_seam.py`
- `reports/bundle_26f_integrated_paper_portfolio_machine_seam.md`

Production helper files changed and why:
- None.
- 26F was implemented as a non-mutating integrated harness/report seam only.

Recent packets consolidated:
- 25U - Alpaca paper read-only broker truth - PASS - `844f441`
- 25V - Broker truth whole-bot contribution readiness - PASS - `1d495cb`
- 25W - Whole-bot contribution activation - PASS - `e0c63f1`
- 25X - Whole-bot replay regime stress - PASS - `ced2457`
- 25Y - Alpaca paper tiny order planning/arming - PASS - `a75c80a`
- 25Z - Alpaca paper tiny order execution - PASS - `c10a76c`
- 26A - Alpaca paper post-fill reconciliation/runtime - PASS - `c69bb8c`
- 26B - Alpaca paper 10-symbol batch execution - CONDITIONAL - `b8f3458`
- 26C - Alpaca paper portfolio ownership reconciliation - CONDITIONAL - `69ba982`
- 26D - Controlled paper portfolio runtime/exposure response - PASS - `b087781`
- 26E - Controlled paper portfolio lifecycle/exit defense - PASS - `a9a09b9`

Largest end-to-end machine gap addressed:
- Prior packets proved adjacent paper-portfolio seams, but not that ownership, exposure, lifecycle, protection, economics, readiness, and mutation guards consume one canonical broker state and produce one coherent non-mutating machine verdict.
- 26F builds one canonical Alpaca PAPER broker truth snapshot and validates every participating subsystem projection against that same snapshot fingerprint.

Real broker calls made:
- Alpaca PAPER read-only GET only.
- 26F targeted GET paths:
  - `GET /v2/account`
  - `GET /v2/clock`
  - `GET /v2/positions`
  - `GET /v2/orders?status=open`
  - `GET /v2/account/activities?activity_types=FILL`
- Required baseline also ran read-only 26E, 26D, 26C, and 26A broker truth paths.

GET-only / endpoint / mutation confirmation:
- Endpoint: `https://paper-api.alpaca.markets`
- HTTP methods observed by 26F harness: `GET`
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

Account / position / open-order / fill summary:
- account_status: `ACTIVE`
- cash: `99965`
- buying_power: `199964.96`
- equity: `99999.96`
- portfolio_value: `99999.96`
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
- current position symbols in canonical machine order:
  - `AAPL`
  - `AMZN`
  - `GOOGL`
  - `NVDA`
  - `QQQ`
  - `SPY`
  - `TSLA`
- positions:
  - AAPL: qty `0.016903`, market_value `5.018501`, avg_entry_price `295.78`, current_price `296.9`
  - NVDA: qty `0.022593`, market_value `4.978368`, avg_entry_price `221.284`, current_price `220.35`
  - AMZN: qty `0.018912`, market_value `4.984258`, avg_entry_price `264.372`, current_price `263.55`
  - GOOGL: qty `0.012572`, market_value `5.035337`, avg_entry_price `397.628`, current_price `400.52`
  - TSLA: qty `0.012195`, market_value `4.95117`, avg_entry_price `409.966`, current_price `406`
  - SPY: qty `0.006787`, market_value `4.998218`, avg_entry_price `736.628`, current_price `736.44`
  - QQQ: qty `0.007111`, market_value `4.991922`, avg_entry_price `703.048`, current_price `702`
- fills:
  - read-only activities were fetched for integrated context
  - no new fill was invented
  - no PnL, slippage, arrival price, net edge, or profitability was inferred from fills

Canonical machine state summary:
- Canonical source: `alpaca_paper_broker_truth`
- account_id_known: `true`
- environment: `paper`
- read_only: `true`
- mutation_allowed: `false`
- active_open_orders_count: `0`
- subsystem fingerprints match canonical state: `true`

Subsystems consuming canonical state:
- ownership reconciliation: same account/status/symbol/open-order fingerprint
- exposure/add-on response: same account/status/symbol/open-order fingerprint
- lifecycle/exit-defense: same account/status/symbol/open-order fingerprint
- protective posture: same account/status/symbol/open-order fingerprint
- economics advisory: same account/status/symbol/open-order fingerprint
- readiness/no-go: same account/status/symbol/open-order fingerprint
- mutation guard: same account/status/symbol/open-order fingerprint

Ownership reconciliation result:
- current broker positions are treated as owned portfolio exposure
- expected paper positions present: all 7
- missing expected positions: none
- extra positions: none
- broker truth is canonical
- local state remains supporting evidence only
- conflicts fail closed in fixture cases

Exposure / add-on result:
- `AAPL`: `EXISTING_EXPOSURE_REQUIRES_APPROVAL_FOR_ADDON`
- `NVDA`: `EXISTING_EXPOSURE_REQUIRES_APPROVAL_FOR_ADDON`
- `MSFT`: `NEW_ENTRY_BLOCKED_BY_26F_MACHINE_SCOPE`
- `AMD`: `NEW_ENTRY_BLOCKED_BY_26F_MACHINE_SCOPE`
- duplicate/add-on entries were not blindly admitted
- no submit, route, or broker mutation was called
- AMD skip reason remains the historical 26B gap: `reason_not_emitted_by_existing_26b_harness`
- AMD was not used as exposure evidence because broker truth did not show an AMD position

Lifecycle / exit-defense result:
- AAPL: `HELD`
- NVDA: `HELD`
- AMZN: `HELD`
- GOOGL: `HELD`
- TSLA: `HELD`
- SPY: `HELD`
- QQQ: `HELD`
- exit-defense verdict surface: `EXIT_DEFENSE_EVIDENCE_ONLY` in fixture pressure cases only
- real current portfolio had no exit-pressure symbols
- exit pressure, when present in fixtures, requires approval
- lifecycle classification does not create order authority

Protective posture result:
- protective verdict: `PROTECTIVE_INTENT_METADATA_ONLY`
- protective posture consumes the canonical lifecycle/exposure state
- protective posture does not authorize fresh entry
- protective posture does not authorize sell/cancel/replace mutation
- protective posture did not mutate broker state

Economics advisory result:
- economics verdict: `ECONOMICS_ADVISORY_MISSING_TRUTH`
- economics consumes the canonical broker state
- missing economic truth carried:
  - arrival price
  - slippage
  - net edge
  - profitability basis
  - fee if not returned
- PnL invented/claimed: no
- slippage invented/claimed: no
- arrival price invented: no
- net edge invented/claimed: no
- profitability invented/claimed: no
- economics veto/approval authority active: no

No-go / readiness result:
- clean current broker state produced verdict: `PAPER_PORTFOLIO_MACHINE_READY_NON_MUTATING`
- live_ready: no
- live_approved: no
- new orders require a future Board packet
- exits require a future Board packet
- no subsystem contradicted another
- forbidden verdicts were never emitted:
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

Mutation guard result:
- post_called: `false`
- patch_called: `false`
- delete_called: `false`
- cancel_called: `false`
- replace_called: `false`
- sell_called: `false`
- rebalance_called: `false`
- approval_flags_required: `false`
- live_mode: `false`
- broker_adapter active authority: `false`
- live_broker active authority: `false`
- live reservation lifecycle opened: `false`
- dormant governors authority active: `false`

Integrated fail-closed fixture results:
- `stale_broker_snapshot` blocked.
- `missing_broker_positions` blocked.
- `broker_local_position_conflict` blocked.
- `nonzero_unknown_open_orders` blocked.
- `orphan_broker_open_order` blocked.
- `local_reservation_conflict` blocked.
- `missing_account_identity` blocked.
- `wrong_environment_or_live_like_endpoint` blocked.
- `missing_fill_or_economic_basis` blocked.
- `exit_intent_requires_approval` classified as evidence-only, not exit-approved.
- `protective_intent_attempted_broker_mutation` blocked.
- `economics_attempted_profitability_invention` blocked.
- `conflicting_subsystem_verdicts` blocked.
- Fixture-only cases were not represented as real broker facts.

Approval flag confirmation:
- All 26F targeted and baseline pytest processes were run with both mutation approval flags explicitly removed:
  - `POVERTY_KILLER_APPROVE_ALPACA_PAPER_TINY_ORDER_25Z`
  - `POVERTY_KILLER_APPROVE_ALPACA_PAPER_10_SYMBOL_BATCH_26B`
- 26F test-process confirmation:
  - `POVERTY_KILLER_APPROVE_ALPACA_PAPER_TINY_ORDER_25Z`: `False`
  - `POVERTY_KILLER_APPROVE_ALPACA_PAPER_10_SYMBOL_BATCH_26B`: `False`
- 26F did not require or use a mutation approval flag.

Tests run:
- `env -u POVERTY_KILLER_APPROVE_ALPACA_PAPER_TINY_ORDER_25Z -u POVERTY_KILLER_APPROVE_ALPACA_PAPER_10_SYMBOL_BATCH_26B /tmp/pk25i-venv/bin/python -m pytest tests/test_integrated_paper_portfolio_machine_seam.py -q -s --tb=short`
# result
  - sandbox run: `2 failed, 2 passed in 3.11s`
  - one fixture assertion expected historical symbol order instead of canonical sorted machine order and was fixed
  - sandbox DNS blocked Alpaca PAPER read-only GET with `URLError`
- `env -u POVERTY_KILLER_APPROVE_ALPACA_PAPER_TINY_ORDER_25Z -u POVERTY_KILLER_APPROVE_ALPACA_PAPER_10_SYMBOL_BATCH_26B /tmp/pk25i-venv/bin/python -m pytest tests/test_integrated_paper_portfolio_machine_seam.py -q -s --tb=short`
# result
  - escalated Alpaca PAPER read-only run: `4 passed in 2.66s`
  - HTTP methods: `GET`
  - open orders: `0`
  - positions: `7`
  - subsystem fingerprints matched canonical broker truth
- `env -u POVERTY_KILLER_APPROVE_ALPACA_PAPER_TINY_ORDER_25Z -u POVERTY_KILLER_APPROVE_ALPACA_PAPER_10_SYMBOL_BATCH_26B /tmp/pk25i-venv/bin/python -m pytest tests/test_integrated_paper_portfolio_machine_seam.py tests/test_controlled_paper_portfolio_lifecycle_exit_defense.py tests/test_controlled_paper_portfolio_runtime_exposure_response.py tests/test_alpaca_paper_portfolio_ownership_reconciliation.py tests/test_alpaca_paper_post_fill_reconciliation_runtime.py tests/test_broker_truth_whole_bot_contribution_readiness.py tests/test_whole_bot_contribution_activation_harness.py tests/test_whole_bot_replay_regime_stress.py tests/test_live_read_only_adapter_config_gate.py tests/test_micro_live_dry_run_readiness_harness.py -q -s --tb=short`
# result
  - `48 passed, 78 warnings in 19.40s`

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
- 26F consumed real Alpaca PAPER read-only broker truth.
- One canonical machine state was built and validated.
- Ownership, exposure/admission, lifecycle/exit-defense, protection, economics advisory, readiness/no-go, and mutation guards consumed the same truth.
- No subsystem contradicted another.
- Unsafe fixture states failed closed.
- No broker mutation occurred.
- No live mode occurred.
- No secrets were printed or written.
- Authority boundaries were preserved.
- The integrated non-mutating paper portfolio machine effect was proven.
