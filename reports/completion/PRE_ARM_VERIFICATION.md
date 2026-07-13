# PK-RUN-1 Gate Zero - Pre-Arm Verification

Date: 2026-07-12 America/Chicago
Audited run-path commit: `4f97ff0667d3ffcabea7309d18850efcb322bd56`
Current HEAD before this report: `353ee6589ba86c1839e69c64d2f7c4c636496704`

## Verdict

PASS. Gate Zero is not VOID. Every reach-to-refuse relabel has a surviving,
passing positive twin. The icon commit changed no production or run-path test
file. Its only test change was `tests/test_operator_desktop_launcher.py`.

Proof is at the local test rung. No PAPER run, broker read, broker mutation,
live mode, or real-money path was used.

## V1 - Positive Chain

### Dispatch -> compile -> submit -> route -> mocked PAPER fill

Primary positive test:

`tests/test_deterministic_end_to_end_harness.py::TestEndToEndChain::test_fresh_candidate_traverses_dispatch_compile_submit_route_fill`

Passing assertions at `4f97ff0`, re-run unchanged at `353ee65`:

- production `MainLoop._dispatch_fusion` is invoked with a fresh same-candle
  sector-rotation candidate;
- `DecisionCompiler.compile` is called exactly once;
- mocked `ExecutionEngine.submit_signal` is called exactly once and captures
  the same `StrategySignal`;
- the same captured signal is converted to an `OrderRequest`;
- real `OrderRouter(paper_mode=True)` routes it through the sovereign internal
  paper broker;
- a non-null `OrderFill` is returned with matching symbol and quantity,
  positive price, and Decimal fee.

This is not claimed as an external broker fill. The submit seam is mocked; the
router and internal paper broker leg are real production code.

Surviving positive twins also re-run and passing:

- `tests/test_deterministic_end_to_end_harness.py::TestDispatchToSubmitDeterministic::test_fresh_sector_rotation_pair_runs_full_chain`
- `tests/test_replay_parity_acceptance.py::TestSameClockReplayParityHappyPath::test_two_runs_same_t0_produce_identical_observables`
- `tests/test_upstream_dispatch_signal_submission.py::TestDispatchFusionFallbackAndDecline::test_sf_decline_with_fresh_sr_pair_reaches_decision_compiler_and_submit`

### MovingFloor exit -> sell-to-close submit

Primary positive test:

`tests/test_decision_frame_orchestration_paper_exploration_alpha.py::test_moving_floor_protective_exit_reaches_mocked_submit_as_sell_to_close`

Passing assertions at `4f97ff0`, re-run unchanged at `353ee65`:

- candidate is `moving_floor`, protective-only, and backed by an existing
  broker position;
- decision frame is `SELL` and `PASS`;
- pre-trade guardrail returns `route_permitted=true`;
- mocked `ExecutionEngine.submit_signal` is called exactly once;
- submitted metadata remains `execution_action=sell_to_close` and
  `sell_intent_classification=SELL_EXIT_EXISTING_BROKER_POSITION`.

Supporting risk test still passes in the 119-test gate:

`tests/test_phase3_risk_gate_stress_proof.py::test_g10_live_runtime_moving_floor_exit_is_broker_position_backed_sell_to_close`

No positive e2e twin was deleted, renamed to refusal, or made unreachable.

## V2 - Assertion-Intent Relabel Log

### Execution reach/refusal flips

1. Deterministic dispatch negatives, four tests:
   - `test_missing_observed_pair_blocks_compile_and_submit` ->
     `test_missing_observed_pair_records_refusal_without_submit`
   - `test_stale_observed_pair_blocks_compile_and_submit` ->
     `test_stale_observed_pair_records_refusal_without_submit`
   - `test_one_nanosecond_offset_still_blocks` ->
     `test_one_nanosecond_offset_records_refusal_without_submit`
   - `test_non_paper_broker_blocks_sr_fallback` ->
     `test_non_paper_broker_records_refusal_without_submit`

   Justification: current law requires an immutable audit DecisionRecord for a
   refused candidate. Assertions changed from compiler-unreachable to exactly
   one compile with empty votes, `execution_verdict=BLOCKED`,
   `broker_post=false`, zero submit, and zero submitted orders. Execution reach
   did not change.

2. Deterministic negative e2e, two tests:
   - `test_missing_observed_pair_yields_no_compile_no_submit_no_fill` ->
     `test_missing_observed_pair_yields_refusal_record_no_submit_no_fill`
   - `test_stale_observed_pair_yields_no_compile_no_submit_no_fill` ->
     `test_stale_observed_pair_yields_refusal_record_no_submit_no_fill`

   Justification: same audit-record law. Both still assert zero submit, zero
   captured signal, zero submitted-order metric, and therefore no fill path.
   The positive full-chain twin named in V1 remains passing.

3. Replay negative controls, four unchanged test names:
   - `test_stale_observed_pair_rejects_identically_in_both_runs`
   - `test_one_nanosecond_offset_rejects_identically_in_both_runs`
   - `test_missing_observed_pair_rejects_identically_in_both_runs`
   - `test_live_broker_mode_rejects_same_clock_pair_identically`

   Justification: expected compilation changed from zero to one audit-only
   compile with empty votes. Stale/missing controls additionally pin BLOCKED and
   `broker_post=false`; every control keeps zero submit. Replay positive parity
   twins remain passing.

4. Integrated internal PAPER limit test:
   - `test_integrated_paper_readiness_coexists_without_new_authority_or_recovery_automation`
     -> `test_integrated_paper_readiness_refuses_fill_without_liquidity_truth`

   Justification: midpoint-only truth has no depth authority for an immediate
   limit fill. The lawful result is a pending paper order, zero fills, zero fill
   events/fees, preserved open-order recovery, and no position. The V1
   market-order paper-fill test and depth-backed reservation lifecycle test
   preserve positive fill coverage.

### Other assertion-contract relabels

5. Config scout:
   - `test_config_defaults_to_paper_and_credentials_are_optional_not_read_only_gated`
     -> `test_config_defaults_to_paper_with_optional_credentials_and_default_off_safety_gate`

   Justification: the old whole-file assertion that no `read_only` text existed
   contradicted the independent `shadow_read_only` safety gate. The relabel
   asserts that gate exists and defaults false; paper default and optional
   credential assertions remain.

6. LiquidityVoid contribution boundary:
   - `test_contributor_role_boundaries_remain_metadata_only_and_non_executing`
     changed exit feed status from `FEED_MISSING` to `FEED_REAL`.

   Justification: a real `StrategySignal` was supplied. The test now also pins
   exit-only, requires-existing-position, and execution-candidate metadata,
   while retaining negative assertions that adapters cannot submit or import
   execution authorities.

7. Shans Curve optional acceleration:
   - `test_shans_curve_savitzky_golay_nopython_path_runs_on_numeric_arrays` ->
     `test_shans_curve_savitzky_golay_runs_with_optional_nopython_acceleration`

   Justification: numerical correctness is required in both environments;
   Numba signatures are required only when Numba is installed. No algorithm,
   threshold, or production path changed.

8. GammaFront diagnostic contract, nine tests:
   - `TestInit::test_not_in_position`
   - `TestInit::test_no_position_state`
   - `TestEntrySignalContract::test_entry_latches_in_position`
   - `TestEntrySignalContract::test_entry_latches_entry_price`
   - `TestExitConditions::test_exit_clears_position_state`
   - `TestPerformanceAndReset::test_get_performance_initial_state`
   - `TestPerformanceAndReset::test_get_performance_after_winning_trade`
   - `TestPerformanceAndReset::test_get_performance_after_losing_trade`
   - `TestPerformanceAndReset::test_reset_clears_all_state`

   Justification: assertions moved from removed ledger-like private names and
   PnL keys to `_local_*`, `diagnostic_*`, `_provisional_pnl`, and the explicit
   `LOCAL_DIAGNOSTIC_ONLY_NOT_LEDGER_TRUTH` declaration. Entry/exit/reset
   outcomes did not flip. GammaFront remains `WIRED_EXIT_ONLY /
   ENTRY_FEED_DORMANT`; no strategy source changed.

Not assertion-intent flips: stale-observation fixtures, current MainLoop helper
bindings, real ExposureManager fixtures, candle truth, MovingFloor action
metadata, current operator screen IDs, callback keyword compatibility, and AST
source inspection. Those raised fixtures or preserved the same assertion
purpose; none changed reach to refuse or refuse to reach.

## V3 - Seven Broker Deferrals

All seven tests still exist with their bodies intact. Six use
`@pytest.mark.broker_read`; 26G uses `@pytest.mark.broker_access`. Each function's
first executable gate is:

```python
if os.environ.get("PK_BOARD_AUTHORIZED_PAPER_BROKER_READ") != "YES_D4_BOARD_AUTHORIZED":
    pytest.skip(...)
```

The gate precedes credential resolution, client construction, and network
access.

1. `test_controlled_paper_portfolio_lifecycle_exit_defense.py::test_real_alpaca_paper_portfolio_lifecycle_exit_defense_get_only`
2. `test_controlled_paper_portfolio_runtime_exposure_response.py::test_real_alpaca_paper_exposure_response_consumes_current_broker_truth_get_only`
3. `test_integrated_paper_portfolio_machine_seam.py::test_real_alpaca_paper_integrated_machine_loop_get_only`
4. `test_alpaca_paper_read_only_broker_truth.py::test_alpaca_paper_read_only_gets_map_into_25t_snapshot_without_mutation`
5. `test_broker_truth_whole_bot_contribution_readiness.py::test_alpaca_paper_read_only_truth_feeds_reconciliation_no_go_classifier`
6. `test_whole_bot_contribution_activation_harness.py::test_alpaca_paper_read_only_truth_can_contribute_to_activation_context_when_env_available`
7. `test_alpaca_paper_10_symbol_expansion_execution_machine.py::test_real_26g_alpaca_paper_expansion_machine_blocks_without_approval_or_executes_when_approved`

26G retains a second, separate exact mutation approval. Board-read
authorization alone cannot authorize its POST path.

Pre-flight 3 executed these exact seven nodeids with both authorization values
absent: `7 skipped`. Skip summaries point to the first function-level env gate;
no credential helper or network path ran. They are deferred, not passed,
deleted, stubbed, or deselected.

## V4 - Skip Count Reconciliation

The premise that there is one singular eighth skip is not accurate. Repo and
original pytest-run truth show:

- G-CLOSE baseline: 6 skipped identities.
- `4f97ff0` final: 14 skipped identities.
- Net new identities: 8.

The baseline six were 26B, 26G, portfolio ownership reconciliation, post-fill
reconciliation, 25Z, and Seam 6. Therefore 26G is one of the seven env-gated
deferrals in V3, but it was already skipped before `4f97ff0`.

Six V3 identities were genuinely added to the skip set: 25T, broker-truth
whole-bot contribution, controlled lifecycle defense, controlled exposure
response, integrated portfolio machine, and whole-bot activation.

The other two new skip identities, neither edited into an env gate, were:

1. `tests/test_alpaca_paper_tiny_order_planning_arming.py::test_optional_real_alpaca_paper_read_only_preflight_can_feed_arming_without_mutation`
2. `tests/test_whole_bot_replay_regime_stress.py::test_broker_truth_conflict_and_optional_real_paper_read_only_stress`

Both used pre-existing optional real-broker read-only paths and skipped on
network unavailability in the final safe run. In final collection order, the
literal eighth new identity is the whole-bot replay stress test. The tiny-order
preflight is the other off-list addition. Neither is a run-path test or a local
pass claim.

## Pre-Flight 1 - Positive Twins

PASS: `5 passed`.

The exact V1 full-chain and MovingFloor tests passed together with deterministic
dispatch, replay happy-path, and upstream dispatch positive twins.

## Pre-Flight 2 - Run-Path Gate

PASS: `119 passed, 0 failed`.

Files: decision-frame orchestration, deterministic e2e, integrated readiness,
risk-gate ordering, replay parity, dispatch admission, and upstream dispatch.

## Pre-Flight 3 - Deferral Integrity

PASS as deferral proof: `7 skipped` before credentials/network.

Static inspection and runtime skip locations agree on the exact Board-read env
gate. No external broker proof is claimed. No full suite was re-run because
Gate Zero does not authorize the remaining ungated optional broker-read tests.

Pre-flight complete. Arming is yours.
