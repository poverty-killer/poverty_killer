# Phase G Close Report - Pre-Arming Seam

Date: 2026-07-11 America/Chicago
Branch: `master`
Boot HEAD: `e8ef247 update phase G session handoff`
Packet: `PK-G-CLOSE PRE-ARMING SEAM`
Governance: `AGENTS.md` v3 re-read in full before work.

## Gate Verdict

| Item | Result | Highest proof reached |
| --- | --- | --- |
| G-C1 Governed Stop PAPER | PASS at test/process-harness rung | Real child process/fake broker mutation surfaces; no PAPER run |
| G-C2 Durable operator state | PASS | Runtime cold boot plus broker-read-only baseline proof |
| G-C3 Truthful vitality | PASS | Deterministic killed-process test plus browser proof |
| G-C4 Deprecated label removal | PASS | Source-negative UI test plus browser proof |
| G-C5 Real cockpit re-proof | PASS | Microsoft Edge/CDP desktop 1440 and mobile 390 |

Scoped seam verdict: PASS. `READY_FOR_BOUNDED_PAPER` remains the only green-light.

Repository-wide clean verdict: BLOCKED by 49 failures that are all present in the
clean `e8ef247` baseline failure set. This seam reduced the clean-HEAD baseline
from 54 failures to 49 and introduced no source-behavior failure. The scoped
240-test gate is green. No PAPER run was executed.

## Challenge Answers

### Q1 - Was the pin enforced in the child, or only carried?

The packet was correct. Before this seam, the child path only carried
`PK_ALPACA_PAPER_EXPECTED_ACCOUNT_SUFFIX=045ded`. The child broker-connect path
`main.main -> SovereignHeartbeat.__init__ -> resolve_execution_broker_gateway ->
AlpacaPaperBrokerAdapter.from_env` did not compare broker-reported account identity
to the pin. Phase G G3 therefore over-claimed the child path.

Now `main.resolve_execution_broker_gateway()` calls
`AlpacaPaperBrokerAdapter.assert_expected_account_pin()` before returning the
adapter. That method performs a PAPER `GET /v2/account`, normalizes the broker
account suffix, requires `045ded`, and raises `BrokerGatewayError` before order #1
on mismatch or missing proof.

Named tests:

- `tests/test_dynamic_execution_broker_gateway_injection.py::test_child_broker_connect_rejects_mismatched_account_pin_before_order_one`
- `tests/test_broker_gateway_adapter_layer.py::test_broker_connect_account_pin_uses_get_and_rejects_mismatch_without_post`

### Q2 - Was the same-symbol guard proven to refuse?

Before this seam, the guard was wired through
`app.main_loop._build_pre_trade_guardrail_verdict()` and
`evaluate_protected_baseline_trade()`, but no test attempted entries across the
actual funded symbols. Loading was proven; four-symbol refusal was not.

Named test added:

- `tests/test_operator_paper_baseline.py::test_funded_account_protected_symbols_refuse_new_entries_before_route`

It attempts new entries for `AVAXUSD`, `ETHUSD`, `LINKUSD`, and `SOLUSD` and
requires a pre-route refusal for each.

### Q3 - Did a governed Stop exist?

Partially. `OperatorPaperSupervisor.stop_paper()`,
`POST /operator/intent/paper/stop`, and a Bot Runtime control already existed.
The control was not present in Shan's Run PAPER cockpit, and tests proved only
that a stop signal was requested. They did not prove process exit, lease release,
zero broker mutation, or baseline preservation.

The existing Stop did not call flatten, close-all, cancel-all, liquidate,
force-exit, manual sell, or any broker adapter. That safety boundary remains.

Now `OperatorPaperSupervisor.stop_paper()` requests graceful process-group stop,
persists `STOP_REQUESTED`, waits for child exit, refreshes terminal state, releases
the active lease, and detaches the process handle. It returns exact no-mutation
truth. It does not claim broker positions were preserved without a broker read;
instead it reports `UNKNOWN_PENDING_FINAL_BROKER_RECONCILIATION` and keeps final
reconciliation mandatory.

Named tests:

- `tests/test_operator_paper_supervisor.py::test_governed_stop_halts_loop_releases_lease_without_broker_mutation_and_preserves_positions`
- `tests/test_operator_paper_supervisor.py::test_supervisor_adopts_running_prior_pid_on_startup_and_allows_governed_stop`

## 1. Verdict

The five packet items are implemented and proven to the highest lawful rung
without executing PAPER. The cockpit can now start from durable state, exposes
start/stop symmetry, freezes liveness when heartbeat evidence is stale, and
renders only bounded-PAPER readiness language.

Important proof boundary: the Stop exit is PASS at the isolated process/test
rung. A real mid-PAPER Stop, broker post-stop position reconciliation, and proof
that protective automation remains effective after child termination were not
run because the packet forbids a PAPER run. The response exposes that unknown
instead of claiming broker preservation.

## 2. Files Changed

Runtime/backend:

- `app/api/operator_paper_supervisor.py`
- `app/api/operator_readonly_api.py`
- `app/api/operator_runtime_config.py`
- `app/execution/alpaca_paper_adapter.py`
- `app/operator_activation/launch_readiness.py`
- `app/operator_intelligence/decision_explainer.py`
- `app/operator_intelligence/system_map.py`
- `app/operator_providers/registry.py`
- `app/run_visibility.py`
- `main.py`

Launchers:

- `scripts/open_operator_console.ps1`
- `scripts/open_operator_console_hidden.ps1`

Tests:

- `tests/test_broker_gateway_adapter_layer.py`
- `tests/test_dynamic_execution_broker_gateway_injection.py`
- `tests/test_operator_ai_ask.py`
- `tests/test_operator_desktop_launcher.py`
- `tests/test_operator_paper_baseline.py`
- `tests/test_operator_paper_supervisor.py`
- `tests/test_operator_readonly_api.py`
- `tests/test_operator_runtime_config.py`
- `tests/test_operator_ui_wiring.py`
- `tests/test_run_visibility.py`

Cockpit:

- `ui/operator-control-panel/app.js`
- `ui/operator-control-panel/contracts.json`
- `ui/operator-control-panel/mock-data.js`
- `ui/operator-control-panel/styles.css`

Reports/continuity:

- `reports/completion/PHASE_G_CLOSE_REPORT.md`
- `CHECKPOINT_TRACKER.md`
- `reports/codex_handoff_latest.md`

The tracker and handoff already contained unrelated unstaged UI-proposal hunks
before this seam. This report recommends leaving both files unstaged rather than
silently staging those unrelated changes.

## 3. Root Cause

1. Child account identity was environment transport, not broker-connect enforcement.
2. Same-symbol protection lacked a test against the four actual funded symbols.
3. Stop signaled the process but did not wait for terminal state or prove lease release.
4. Production operator state defaulted to an ephemeral/proof-specific path instead of an OS-owned durable path.
5. The cockpit animated a decorative heartbeat and conflated machine liveness with market freshness.
6. UI display sources retained bounded-readiness aliases such as `Ready for governed PAPER`.
7. The prior Phase G browser proof depended on a hand-built `C:\tmp` baseline.

## 4. Fixes Implemented

### G-C1 Governed Stop

- Kept lifecycle ownership in `OperatorPaperSupervisor`; no new module.
- Added a public runner `wait_for_exit()` contract and used it after graceful stop.
- Stop now fails honestly on exit timeout and does not release the lease early.
- Clean exit moves the session to terminal state, releases the lease, and removes the active process handle.
- Surfaced Stop beside Start in the Run PAPER command center.
- Kept every broker mutation surface untouched.
- Removed post-code fake claims of broker-position preservation. Stop now says no position mutation was requested, broker post-state is unreconciled, lifecycle authority is unchanged, the child lifecycle process is inactive after exit, and final reconciliation is required.

### G-C2 Durable operator state

- Added the production default `%LOCALAPPDATA%\PovertyKiller\state\operator` on Windows.
- Kept explicit `repo_root` construction isolated for tests.
- Made the operator session store follow the durable state directory by default.
- Updated both desktop launchers to create/use the LocalAppData operator directory.
- Created the accepted `045ded` baseline through `POST /operator/paper-baseline/accept` from a broker-confirmed read-only snapshot.
- Cold-booted the backend against that durable path and re-proved readiness.
- Left ignored repo state `state/operator/paper_baseline.json` unchanged.

### G-C3 Vitality truth

- Added independent BOT and MKT status lights.
- BOT pulse/ECG animation is allowed only when the runtime heartbeat is fresh.
- MKT status derives from the last loop market event and is explicitly not executable MarketTruthSnapshot authority.
- Removed the invented account sparkline and replaced it with an unavailable-evidence statement.
- Added a killed-process stale-threshold proof using a real child process and deterministic visibility clock.

### G-C4 Deprecated labels

- Replaced governed/degraded readiness display copy with bounded-PAPER language.
- Added a source-negative UI test for `READY_FOR_GOVERNED_PAPER`, `governed PAPER`, and `DEGRADED_BUT_RUNNABLE`.

### G-C5 Cockpit re-proof

- Re-ran the actual local operator cockpit from the durable state directory.
- Captured final Edge/CDP desktop, mobile, and vitality proof.
- Fixed mobile sticky-header obstruction discovered during browser validation.

## 5. 360-Degree Adjacent Improvements

- The Start label now names a bounded PAPER run and Stop is adjacent and state-truthful.
- The four protected symbols are visible in the baseline summary.
- Mobile controls no longer sit beneath an oversized sticky header.
- AI and display-source wording now consumes the same bounded-PAPER vocabulary.
- The operator-state summary exposes whether its path is durable.
- Tests no longer depend on ambient canonical credentials when exercising missing-credential branches.
- A post-code red-team removed two absolute Stop claims that the code could not prove.

## 6. Tests and Checks

### Final scoped gate - PASS, test rung

```text
240 passed, 72 warnings in 95.01s
```

Coverage includes child pin enforcement, adapter GET/no-POST proof, funded-symbol
refusal, governed Stop, durable state, desktop launchers, vitality, read-only API,
UI wiring, AI wording, launch readiness, account pinning, and PowerShell authority.

### Final UI negative gate - PASS, test rung

```text
tests/test_operator_ui_wiring.py
51 passed in 0.49s
```

`node --check ui/operator-control-panel/app.js`: PASS.

Touched Python `py_compile`: PASS.

`git diff --check`: PASS with line-ending warnings only for the two touched
PowerShell launchers and pre-existing protected `state/*` files.

### Full repository inventory - NOT GREEN

Current source, isolated bytecode/temp paths, all mutation approval variables
absent, broker-read-only network allowed:

```text
49 failed, 1762 passed, 6 skipped, 385 warnings in 117.76s
```

Clean temporary clone at `e8ef247` under the same conditions:

```text
54 failed, 1749 passed, 6 skipped, 385 warnings in 125.48s
```

Every one of the 49 current failures is present in the clean-HEAD set. The five
baseline failures removed by this seam are the dynamic missing-credentials test
and four AI readiness-answer tests. The full suite was run before the final
localized Stop response-field truth correction; the final post-correction scoped
240-test gate passed. The full suite was not rerun after that final localized edit.

Exact current full-suite failures:

```text
tests/test_concrete_live_adapter_read_only_scout.py::test_config_defaults_to_paper_and_credentials_are_optional_not_read_only_gated
tests/test_controlled_paper_portfolio_lifecycle_exit_defense.py::test_real_alpaca_paper_portfolio_lifecycle_exit_defense_get_only
tests/test_controlled_paper_portfolio_runtime_exposure_response.py::test_real_alpaca_paper_exposure_response_consumes_current_broker_truth_get_only
tests/test_decision_frame_orchestration_paper_exploration_alpha.py::test_fresh_buy_frame_reaches_mocked_submit_with_broker_post_false_under_hard_blocker
tests/test_decision_frame_orchestration_paper_exploration_alpha.py::test_paper_exploration_router_ranking_does_not_suppress_sector_rotation_submit_path
tests/test_decision_frame_orchestration_paper_exploration_alpha.py::test_moving_floor_protective_exit_reaches_mocked_submit_as_sell_to_close
tests/test_deterministic_end_to_end_harness.py::TestDispatchToSubmitDeterministic::test_fresh_sector_rotation_pair_runs_full_chain
tests/test_deterministic_end_to_end_harness.py::TestDispatchToSubmitDeterministic::test_fresh_shadow_front_signal_runs_full_chain
tests/test_deterministic_end_to_end_harness.py::TestDispatchToSubmitDeterministic::test_missing_observed_pair_blocks_compile_and_submit
tests/test_deterministic_end_to_end_harness.py::TestDispatchToSubmitDeterministic::test_stale_observed_pair_blocks_compile_and_submit
tests/test_deterministic_end_to_end_harness.py::TestDispatchToSubmitDeterministic::test_one_nanosecond_offset_still_blocks
tests/test_deterministic_end_to_end_harness.py::TestDispatchToSubmitDeterministic::test_non_paper_broker_blocks_sr_fallback
tests/test_deterministic_end_to_end_harness.py::TestEndToEndChain::test_fresh_candidate_traverses_dispatch_compile_submit_route_fill
tests/test_deterministic_end_to_end_harness.py::TestEndToEndNegativeChain::test_missing_observed_pair_yields_no_compile_no_submit_no_fill
tests/test_deterministic_end_to_end_harness.py::TestEndToEndNegativeChain::test_stale_observed_pair_yields_no_compile_no_submit_no_fill
tests/test_gamma_front.py::TestInit::test_not_in_position
tests/test_gamma_front.py::TestInit::test_no_position_state
tests/test_gamma_front.py::TestEntrySignalContract::test_entry_latches_in_position
tests/test_gamma_front.py::TestEntrySignalContract::test_entry_latches_entry_price
tests/test_gamma_front.py::TestExitConditions::test_exit_clears_position_state
tests/test_gamma_front.py::TestPerformanceAndReset::test_get_performance_initial_state
tests/test_gamma_front.py::TestPerformanceAndReset::test_get_performance_after_winning_trade
tests/test_gamma_front.py::TestPerformanceAndReset::test_get_performance_after_losing_trade
tests/test_gamma_front.py::TestPerformanceAndReset::test_reset_clears_all_state
tests/test_integrated_paper_portfolio_machine_seam.py::test_real_alpaca_paper_integrated_machine_loop_get_only
tests/test_integrated_paper_readiness.py::test_integrated_paper_readiness_coexists_without_new_authority_or_recovery_automation
tests/test_intelligence_contribution_spine.py::test_contributor_role_boundaries_remain_metadata_only_and_non_executing
tests/test_operator_home.py::test_home_control_inventory_covers_required_pages_and_forbidden_controls_absent
tests/test_phase3_risk_gate_stress_proof.py::test_g4_live_runtime_correlation_slash_runs_before_netedge
tests/test_phase3_risk_gate_stress_proof.py::test_p3d_live_runtime_per_symbol_cap_clamps_before_netedge_and_broker_route
tests/test_replay_parity_acceptance.py::TestReplayTimeIsolation::test_two_parity_runs_observe_no_state_leak
tests/test_replay_parity_acceptance.py::TestSameClockReplayParityHappyPath::test_two_runs_same_t0_produce_identical_observables
tests/test_replay_parity_acceptance.py::TestSameClockReplayParityHappyPath::test_run_a_does_not_leak_into_run_b_via_runtime_state
tests/test_replay_parity_acceptance.py::TestSameClockReplayParityHappyPath::test_same_clock_invariant_holds_in_each_run
tests/test_replay_parity_acceptance.py::TestSameClockReplayParityHappyPath::test_decimal_discipline_holds_under_replay
tests/test_replay_parity_acceptance.py::TestReplayParityAcrossT0Shift::test_path_shape_identical_only_timestamps_shift
tests/test_replay_parity_acceptance.py::TestReplayParityNegativeControls::test_stale_observed_pair_rejects_identically_in_both_runs
tests/test_replay_parity_acceptance.py::TestReplayParityNegativeControls::test_one_nanosecond_offset_rejects_identically_in_both_runs
tests/test_replay_parity_acceptance.py::TestReplayParityNegativeControls::test_missing_observed_pair_rejects_identically_in_both_runs
tests/test_replay_parity_acceptance.py::TestReplayParityNegativeControls::test_live_broker_mode_rejects_same_clock_pair_identically
tests/test_replay_parity_acceptance.py::TestReplayParitySafetyInvariants::test_attack_mode_remains_false_through_each_run
tests/test_runtime_dispatch_admission_telemetry.py::test_fresh_executable_sector_rotation_same_candle_reaches_compiler_with_scorecard
tests/test_runtime_dispatch_admission_telemetry.py::test_pre_trade_guardrail_uses_alpaca_crypto_default_limit_gtc_for_non_attack
tests/test_runtime_dispatch_admission_telemetry.py::test_submitted_false_diag_includes_status_code_and_execution_block
tests/test_runtime_dispatch_admission_telemetry.py::test_sell_to_close_requires_broker_position_backed_inventory
tests/test_runtime_dispatch_admission_telemetry.py::test_buy_path_still_selects_capability_when_lawful
tests/test_seam7b_brain_math_runtime_stability.py::test_shans_curve_savitzky_golay_nopython_path_runs_on_numeric_arrays
tests/test_upstream_dispatch_signal_submission.py::TestDispatchFusionFallbackAndDecline::test_sf_decline_with_fresh_sr_pair_reaches_decision_compiler_and_submit
tests/test_upstream_dispatch_signal_submission.py::TestAdvisoryMetadataSpine::test_fusion_aggression_metadata_is_advisory_to_commander_contract_on_admit_path
```

## 7. Browser, Runtime, and Broker-Read-Only Proof

### Durable cold boot

- Path: `%LOCALAPPDATA%\PovertyKiller\state\operator\paper_baseline.json`
- Baseline created through the governed acceptance endpoint, not copied or hand-placed.
- `final_launch_readiness=READY_FOR_BOUNDED_PAPER`
- `paper_start_allowed=true`
- expected/actual pin suffix `045ded`
- protected same-symbol guard active
- protected symbol count `4`
- portfolio status `BROKER_CONFIRMED`
- positions `AVAXUSD`, `ETHUSD`, `LINKUSD`, `SOLUSD`
- open orders `0`
- broker mutation false
- no `C:\tmp` runtime dependency

The ignored repo baseline is not tracked (`git ls-files` returns nothing) and is
ignored by `.gitignore:17`. Its SHA-256 remained
`F13A3E2E81D32DDBFF69C824D4A4B948107E6FFFEF7B7019ADD5F40CEE0C06A0`.
The durable governed baseline has a different hash and the repo file was not
modified or staged.

### Desktop Edge/CDP

- viewport/client/scroll width `1440/1440/1440`
- no document or main horizontal overflow
- Start visible and enabled: `Start Bounded PAPER Run`
- Stop visible and disabled while idle: `Stop PAPER Run`
- pin visible; broker truth visible; four protected symbols visible
- live locked and real-money blocked visible
- deprecated labels absent
- `C:\tmp` reference absent

### Mobile Edge/CDP

- viewport/client/scroll width `390/390/390`
- no document or main horizontal overflow
- same Start, Stop, pin, broker, symbol, and safety truth as desktop
- no incoherent control overlap after mobile header correction

### Vitality browser proof

- BOT `STALE`
- MKT `UNKNOWN`
- ECG animation data flag `false`
- account time-series unavailable; no trend inferred

Screenshots and metrics are under `C:\tmp` and are intentionally unstaged.

The required in-app Browser bootstrap was attempted twice, but the local MCP
bridge rejected missing sandbox metadata before navigation. Final browser proof
therefore used real Microsoft Edge via CDP, not the in-app Browser tool.

## 8. Self Red-Team and Anti-Hallucination Check

- Duplicate authority: none added. Child pin stays in the existing Alpaca adapter; Stop stays in the supervisor; baseline stays in `PaperBaselineStore`; UI remains display-only.
- Fake readiness: closed the child pin bypass and removed the temp-path dependency.
- Hidden broker truth: broker identity/portfolio proof is redacted and broker-read-only. No response claims post-stop broker state without reconciliation.
- UI clutter: only Stop and BOT/MKT vitality were pulled forward; N1 proof ring, badge declutter, refusal line, and lease tempo were not implemented.
- Risk/economics/TTL/sizing/masking: untouched.
- Test-only green: scoped logic is paired with durable runtime, Edge/CDP, and broker-read-only proof. Stop remains test-rung only because PAPER was forbidden.
- Mock/stale truth: animation freezes without fresh heartbeat; no fake account trend remains.
- AI hallucination: no AI authority change; readiness copy remains evidence-bound.
- Sophisticated modules: none deleted, flattened, activated, or reclassified.
- Stop overclaim: caught after implementation and corrected before report.

Actually inspected: AGENTS v3, tracker, handoff, Phase G report/commit, supervisor,
adapter, main child path, baseline authority, runtime config, launchers, read-only
API, visibility API, cockpit source/styles/contracts/mocks, and scoped tests.

Actually proven: scoped tests, syntax, durable cold boot, live local API wiring,
Edge/CDP desktop/mobile/vitality, and authorized Alpaca PAPER read-only account,
positions, and open-orders truth.

Inference: none is used to claim external broker state. The clean-HEAD comparison
proves failure-set ancestry but does not explain every historical failure root cause.

Unknown/not run: real PAPER start, real mid-run Stop, post-stop broker
reconciliation, actual child broker-connect positive path, sustained multi-day
heartbeat behavior, and active protective lifecycle after child termination.

## 9. Safety Confirmation

- No PAPER run.
- No live mode or live credentials.
- No real money.
- No order submission, cancel, replace, close, liquidation, flatten, or force exit.
- No manual buy/sell or force-trade control.
- No risk, NetEdge, economic, TTL, sizing, masking, or strategy threshold change.
- No secret value printed, logged, staged, or pasted.
- No state/log/database/runtime file staged.
- Read-only broker calls were limited to account, positions, and open orders.
- SovereignExecutionGuard remains dormant.
- Existing automated lifecycle code and authority were not weakened or removed.

## 10. Module Status

| Module | Status and role |
| --- | --- |
| `AlpacaPaperBrokerAdapter` | WIRED - PAPER broker boundary and child account-pin assertion |
| `main.resolve_execution_broker_gateway` | WIRED - child broker-connect fail-closed caller |
| `OperatorPaperSupervisor` | WIRED - bounded run process/lease lifecycle and governed Stop |
| `PaperBaselineStore` | WIRED - sole accepted-baseline persistence authority |
| `OperatorRuntimeConfig` | WIRED - durable operator-state path owner |
| `run_visibility` | WIRED - read-only heartbeat and market-event liveness evidence |
| Operator cockpit | WIRED - display and intent request only, no truth authority |
| Existing position lifecycle | PRESERVED - code/authority unchanged; runtime inactive after child termination and post-stop broker state requires reconciliation |
| `SovereignExecutionGuard` | DORMANT_BY_POLICY_PENDING_PHASE_HI_ARM |

No touched module is silent.

## 11. Disagreements and Corrected Packet Assumptions

1. The packet said Phase G had an approved 19-file staging list waiting to be committed. Live repo truth showed Phase G already committed/pushed as `a861142` with 15 files, followed by pushed handoff commit `e8ef247`. No duplicate commit was made.
2. The packet described `state/operator/paper_baseline.json` as tracked. It is ignored and not tracked. It was preserved unchanged.
3. Q1 was correct: child pin enforcement was missing and G3 was over-claimed.
4. Q2 was correct: the actual four-symbol refusal test was missing.
5. Q3 was partially correct: Stop existed, but it was not cockpit-visible and lacked terminal/lease/no-mutation proof.
6. The simultaneous requirements to terminate the child and keep the automated lifecycle active cannot both be claimed literally. After Stop, the lifecycle authority/code is preserved, but its child process is inactive. The response now exposes that fact and requires final reconciliation. If the Board requires active protection after Stop, a separate explicit design ruling is needed; it was not invented in this seam.
7. The tracker says Checkpoint A is PASS, but the current full repository suite is not green and the clean `e8ef247` clone also has 54 failures. This is logged as a pre-existing repository gate regression, not hidden or absorbed into the frozen G-close scope.

## 12. Limitations and Unknowns

- No PAPER run or real mid-run Stop proof.
- No broker-read after Stop; post-stop positions remain unknown until final reconciliation.
- The four baseline positions are protected from same-symbol entry/exit routing, but an active protective lifecycle after child termination is not proven.
- Full repository tests remain non-green with 49 baseline failures.
- In-app Browser control was unavailable; Edge/CDP was used.
- Browser screenshots are proof artifacts in `C:\tmp`, not staged evidence files.
- The local backend remains running for operator inspection at `http://127.0.0.1:8765/operator-ui/`.
- `CHECKPOINT_TRACKER.md` and `reports/codex_handoff_latest.md` contain unrelated pre-existing UI-proposal diffs and cannot be staged as exact seam files without also staging those changes.

## Research Used

Patterns reviewed:

- [Kubernetes liveness, readiness, and startup probes](https://kubernetes.io/docs/concepts/workloads/pods/probes/)
- [Grafana status history visualization](https://grafana.com/docs/grafana/latest/panels-visualizations/visualizations/status-history/)

Applied: separate machine life from readiness/market freshness, bind animation to
fresh evidence, and freeze status motion when evidence goes stale.

Rejected: invented trend data, decorative pulse, automatic restart, and a new
proof-ring/lease-tempo subsystem outside the packet scope.

Safety impact: BOT life can no longer imply market freshness or execution
readiness, and stale evidence cannot keep an animated alive signal moving.

## 13. Exact Staging Recommendation

Stage exactly these 27 files:

```text
app/api/operator_paper_supervisor.py
app/api/operator_readonly_api.py
app/api/operator_runtime_config.py
app/execution/alpaca_paper_adapter.py
app/operator_activation/launch_readiness.py
app/operator_intelligence/decision_explainer.py
app/operator_intelligence/system_map.py
app/operator_providers/registry.py
app/run_visibility.py
main.py
scripts/open_operator_console.ps1
scripts/open_operator_console_hidden.ps1
tests/test_broker_gateway_adapter_layer.py
tests/test_dynamic_execution_broker_gateway_injection.py
tests/test_operator_ai_ask.py
tests/test_operator_desktop_launcher.py
tests/test_operator_paper_baseline.py
tests/test_operator_paper_supervisor.py
tests/test_operator_readonly_api.py
tests/test_operator_runtime_config.py
tests/test_operator_ui_wiring.py
tests/test_run_visibility.py
ui/operator-control-panel/app.js
ui/operator-control-panel/contracts.json
ui/operator-control-panel/mock-data.js
ui/operator-control-panel/styles.css
reports/completion/PHASE_G_CLOSE_REPORT.md
```

Do not stage:

- `CHECKPOINT_TRACKER.md` or `reports/codex_handoff_latest.md` in the same commit because their pre-existing UI-proposal hunks are outside this seam.
- any `state/*`, `.pytest_tmp/`, screenshot, metric, log, database, secret, old report, operator performance artifact, or untracked audit script.
