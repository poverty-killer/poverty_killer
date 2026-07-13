# Phase Run-Path Green Report - Pre-Arming Failure Disposition

Date: 2026-07-12 America/Chicago
Branch: `master`
Boot HEAD: `289d047 close phase G pre-arming controls`
Packet: pre-arming run-path-green disposition of the reported 49 failures
Governance: `AGENTS.md` v3 re-read before work and after two seams.

## Gate Verdict

| Gate | Result | Highest proof reached |
| --- | --- | --- |
| E2E deterministic harness | PASS | test rung |
| Replay parity | PASS | test rung |
| Dispatch admission | PASS | test rung |
| Decision-frame orchestration | PASS | test rung |
| Risk-gate ordering | PASS | test rung |
| Upstream dispatch | PASS | test rung |
| Full local suite | PASS with documented external deferrals | test rung |

Run-path binary exit: **PASS**. The named seven-file gate is `119 passed, 0
failed`. Final full suite is `1803 passed, 14 skipped, 0 failed`. No PAPER run
was executed.

## 1. Verdict

The reported 49 failures are dispositioned by cluster without changing
production source, guards, thresholds, strategy logic, or broker authority.
Run-path fixtures now supply the evidence required by the current runtime:
fresh temporal observations, canonical candle truth, real ExposureManager
evidence, and the current MainLoop helper surface.

Tests that expected a lawful refusal to make DecisionCompiler unreachable were
wrong under the current audit contract. They now require one immutable
no-submit decision record, `execution_verdict=BLOCKED`, `broker_post=false`, and
zero calls to `ExecutionEngine.submit_signal()`.

Full green was not required by the packet, but the final local suite has zero
failures. Fourteen tests are skipped; external broker/access tests remain
explicitly deferred and are not counted as proof.

## 2. Files Changed

Test configuration:

- `pytest.ini`

Run-path fixtures and refusal contracts:

- `tests/test_decision_frame_orchestration_paper_exploration_alpha.py`
- `tests/test_deterministic_end_to_end_harness.py`
- `tests/test_integrated_paper_readiness.py`
- `tests/test_phase3_risk_gate_stress_proof.py`
- `tests/test_replay_parity_acceptance.py`
- `tests/test_runtime_dispatch_admission_telemetry.py`
- `tests/test_upstream_dispatch_signal_submission.py`

Module/off-path contract tests:

- `tests/test_gamma_front.py`
- `tests/test_concrete_live_adapter_read_only_scout.py`
- `tests/test_intelligence_contribution_spine.py`
- `tests/test_operator_home.py`
- `tests/test_seam7b_brain_math_runtime_stability.py`
- `tests/test_alpaca_paper_tiny_order_planning_arming.py`

Environment-gated broker tests:

- `tests/test_controlled_paper_portfolio_lifecycle_exit_defense.py`
- `tests/test_controlled_paper_portfolio_runtime_exposure_response.py`
- `tests/test_integrated_paper_portfolio_machine_seam.py`
- `tests/test_alpaca_paper_read_only_broker_truth.py`
- `tests/test_broker_truth_whole_bot_contribution_readiness.py`
- `tests/test_whole_bot_contribution_activation_harness.py`
- `tests/test_alpaca_paper_10_symbol_expansion_execution_machine.py`

Continuity/reporting:

- `CHECKPOINT_TRACKER.md`
- `reports/codex_handoff_latest.md`
- `reports/completion/PHASE_RUNPATH_GREEN_REPORT.md`

No production source file remains changed.

## 3. Root Cause by Cluster

### Cluster A - 33 run-path failures: stale fixtures (disposition a)

Safe pre-change reproduction across the seven named run-path files was `33
failed, 86 passed`.

The fixtures predated current runtime admission contracts:

- minimal MainLoop doubles lacked current decision-frame, economics, moving
  floor, and no-submit helper bindings;
- StrategySignal fixtures omitted `stale_data_observation`, so StaleDataGuard
  correctly returned `STALE_DATA_GUARD_OBSERVATION_MISSING`;
- a first temporal sample carried nonzero drift and correctly tripped critical
  drift velocity;
- decision-frame tests enabled the portfolio risk gate but supplied no real
  ExposureManager;
- the integrated direct-dispatch fixture omitted canonical candle execution
  truth and was correctly refused as `DATA_UNHEALTHY`;
- capture callbacks implemented the old `submit_signal` signature and rejected
  the current `decision_record` keyword.

No runtime guard was broken. Fixtures were raised to the current law.

### Cluster B - negative run-path expectations: stale law (disposition a)

Missing, stale, one-nanosecond-offset, and non-PAPER candidates are now compiled
into an audit-only no-submit DecisionRecord. The old tests expected zero compile
calls even though current law records the refusal.

Relabel log:

- four deterministic dispatch negative tests now say
  `records_refusal_without_submit`;
- two deterministic negative E2E tests now say
  `yields_refusal_record_no_submit_no_fill`;
- replay negative controls now expect one empty-vote refusal compilation and
  zero submission;
- the integrated internal-paper test now says
  `refuses_fill_without_liquidity_truth` and requires pending/open state, zero
  fills, zero fees, and durable open-order recovery.

The integrated relabel is intentional: a limit order with midpoint-only truth
has no depth authority for an immediate fill. Separate depth-backed broker tests
retain fill and lifecycle coverage.

### Cluster C - three real Alpaca tests: missing environment gate (disposition c)

The three G-CLOSE failures loaded canonical credentials and performed real
Alpaca PAPER GETs without first requiring the explicit Board-read variable.
They now skip before credential resolution or network access unless:

`PK_BOARD_AUTHORIZED_PAPER_BROKER_READ=YES_D4_BOARD_AUTHORIZED`

They are deferred, not passed.

### Cluster D - nine GammaFront failures: stale tests plus role classification

GammaFront is not wholly dormant. Repo truth shows:

- `SymbolRuntime.initialize_engines()` constructs `GammaFrontStrategy`;
- MainLoop consumes GammaFront as an exit-only contribution;
- fresh entry remains feed-dormant because no lawful dark-pool entry feed is
  wired.

Classification: `WIRED_EXIT_ONLY / ENTRY_FEED_DORMANT`.

The nine failures used removed ledger-like private names and old performance
keys. Tests now use `_local_*`, `diagnostic_*`, and require
`LOCAL_DIAGNOSTIC_ONLY_NOT_LEDGER_TRUTH`. Production GammaFront code is
unchanged.

### Cluster E - four off-path failures (dispositions a/c)

- Config scout: stale whole-file assertion rejected the independent default-off
  `shadow_read_only` safety gate. The relabeled test now proves optional
  credentials and `shadow_read_only=False` coexist.
- LiquidityVoid contribution: a supplied real StrategySignal lawfully maps to
  `FEED_REAL`, not `FEED_MISSING`; exit/position boundaries remain asserted.
- Operator inventory: stale screen IDs were updated to current controls,
  advisor, trades, connections, and log IDs. Forbidden trade controls remain
  negatively asserted.
- Shans Curve: Numba is optional. Numeric output is always tested; compiled
  signatures are required only when Numba is installed.

### Cluster F - five environment-sensitive leftovers exposed by full run

After the packet's 49 were repaired, the first complete suite in the explicit
safe environment returned `1802 passed, 5 failed, 10 skipped`. Four additional
historical Alpaca tests had the same missing Board-read gate; one 26G test can
also mutate only under its separate exact approval. They now defer before
network access. The local fifth failure used `inspect.getsource()` against a
stale cross-environment code filename and was fixed with `ast.parse()` over the
checked-out file.

This environment-sensitive set is reported separately from the packet's
recorded 49 rather than silently rewriting the historical count.

### Broken production code (disposition b)

None remains. A temporary OrderRouter paper-matching edit was made during
diagnosis, then removed in self-red-team when the existing compatibility
fallback was proven intentional. Focused lifecycle tests passed after restoring
the production path.

## 4. Fixes Implemented

- Added explicit fresh temporal observations to lawful positive fixtures.
- Bound current MainLoop helper methods into minimal harness doubles.
- Wired real ExposureManager evidence where the configured portfolio risk gate
  requires it.
- Supplied canonical candle-execution truth to direct dispatch.
- Updated mock submit callbacks for current decision context.
- Strengthened refusal tests around audit records and zero execution reach.
- Corrected MovingFloor test metadata to include canonical `action` and
  `execution_action` for broker-backed `sell_to_close`.
- Relabeled the no-depth internal PAPER limit test to assert pending/no-fill
  truth.
- Updated GammaFront tests to diagnostic-only semantics.
- Registered `broker_read` and `broker_access` markers and gated seven external
  tests before credentials/network.
- Replaced one fragile source-inspection check with AST parsing.
- Removed unrelated proposal-only UI content from tracker/handoff.
- Corrected Checkpoint A to collection/syntax proof, not full-suite PASS.

## 5. 360-Degree Adjacent Improvements

- Negative-path tests now prove the decision audit trail instead of treating
  audit compilation as execution.
- Broker tests cannot silently become network tests because credentials happen
  to exist.
- The potentially mutating 26G historical machine is separately marked and
  still requires its original exact mutation approval after broker-read
  authorization.
- GammaFront diagnostics can no longer be mistaken for ledger PnL.
- Optional acceleration no longer makes pure-Python correctness appear broken.
- Current UI inventory tests still reject buy, sell, cancel, flatten,
  liquidate, and force controls.

No UI implementation or operator workflow changed, so research was not required
for this test-disposition seam.

## 6. Tests and Checks

### Before state

| Evidence | Result |
| --- | --- |
| G-CLOSE recorded full suite | `1762 passed, 49 failed, 6 skipped` |
| Safe run-path reproduction | `86 passed, 33 failed` |
| GammaFront reproduction | `33 passed, 9 failed` |
| Local off-path last-failed reproduction | 4 named failures |

The packet's 49 were not rerun as one unsafe pre-edit command because historical
broker tests could perform external calls merely from ambient credentials. The
G-CLOSE report is the source for the 49 count; local reproductions established
the safe clusters before edits.

### Run-path exit gate - PASS, test rung

```text
119 passed, 78 warnings in 14.70s
```

Files: decision-frame orchestration, deterministic E2E, integrated readiness,
Phase 3 risk ordering, replay parity, runtime dispatch admission, and upstream
dispatch.

### Off-path/Gamma focused gate - PASS, test rung

```text
46 passed, 72 warnings in 13.08s
```

### Restored paper-matching path - PASS, test rung

```text
23 passed, 78 warnings in 4.56s
```

### Full suite - PASS with skips, test rung

```text
1803 passed, 14 skipped, 384 warnings in 129.22s
```

The command explicitly removed Board broker-read authorization and the relevant
PAPER mutation approval variables. External skips are not elevated to pass.

New explicit broker/access deferrals:

- controlled lifecycle exit defense;
- controlled runtime exposure response;
- integrated portfolio machine;
- 25T read-only broker truth;
- broker-truth whole-bot contribution;
- whole-bot activation contribution;
- 26G expansion access, which also retains its separate mutation approval.

Preserved existing deferrals:

- 26B and 25Z mutation approvals absent;
- Seam 6 mutation approval absent;
- portfolio ownership, post-fill reconciliation, tiny-order preflight, and
  whole-bot replay read-only network unavailable.

### Static/diff checks

- `git diff --check` passed for intended test/config changes.
- No production source diff remains.
- No risk/threshold/NetEdge/TTL/sizing/masking/OMS/broker-governor source changed.

## 7. Browser, Runtime, and Broker-Read-Only Proof

- Browser: not run; no UI implementation changed.
- Runtime server: not used as proof.
- PAPER run: not run.
- Broker mutation: not run.
- Broker read-only: an intermediate full run reached historical GET-only tests
  before the missing gate was identified. No mutation occurred and those
  results are not used as proof. The final suite deferred all seven newly gated
  tests before credentials/network.

Highest claimed rung for this seam: tests.

## 8. Self-Red-Team and Anti-Hallucination Check

### Before implementation

- Duplicate authority risk: none; tests consume existing owners only.
- Fake readiness risk: prevented by keeping external broker tests skipped and
  labeled instead of passing them locally.
- Guard weakening risk: stop condition was any production guard, threshold, or
  assertion relaxation. None was required.
- Runtime/test divergence risk: fixtures bind production MainLoop helpers and
  real ExposureManager evidence rather than duplicating gate logic.
- Dormant-module risk: GammaFront was inspected before classification and was
  not incorrectly declared wholly dormant.

### After implementation

- Actually inspected: all touched tests, MainLoop dispatch/frame path,
  StaleDataGuard, ExposureManager sell-to-close contract, GammaFront runtime
  construction/dispatch role, paper matching behavior, tracker, and handoff.
- Tests prove: run-path behavior, refusal recording, full local regression
  status, optional Numba fallback, GammaFront diagnostics, and pre-network skip
  behavior.
- Tests do not prove: external broker state, a PAPER run, browser state, or
  multi-day runtime behavior.
- Inference: none is used for the exit verdict.
- Unknown: the seven external broker/access tests have not been rerun under
  their explicit Board-read authorization in this seam.
- Failure not summarized away: the intermediate five-failure full result and
  the removed unnecessary production edit are both recorded.
- Duplicate authority: none introduced.
- Production behavior: unchanged.

## 9. Safety Confirmation

- No PAPER run.
- No live mode or real-money enablement.
- No broker POST, cancel, replace, close, liquidate, flatten, or manual sell.
- No guard, threshold, assertion, risk, NetEdge, TTL, sizing, masking, OMS,
  broker-governor, or strategy behavior weakened.
- No SovereignExecutionGuard activation.
- No raw secret printed, logged, staged, or added to reports.
- Canonical credential source remains unchanged.
- No tracked `state/*`, logs, databases, screenshots, or audit scripts are in
  the staging recommendation.
- Protected dirty runtime state was preserved and not edited by hand.

## 10. Module Status

| Module/area | Status |
| --- | --- |
| MainLoop dispatch/DecisionFrame | WIRED; fixtures now match current contract |
| StaleDataGuard | WIRED blocking authority; unchanged |
| ExposureManager | WIRED portfolio risk authority; unchanged |
| ExecutionEngine/OrderRouter/PaperBroker | WIRED; production unchanged |
| GammaFront | WIRED_EXIT_ONLY / ENTRY_FEED_DORMANT |
| Shans Curve Numba path | OPTIONAL_ACCELERATION; pure Python fallback proven |
| Alpaca historical broker tests | BLOCKED/DEFERRED without explicit Board-read environment |
| 26G expansion machine | BLOCKED/DEFERRED without Board read plus separate mutation approval |
| SovereignExecutionGuard | DORMANT_BY_POLICY; unchanged |

No module was deleted, flattened, stubbed, or silently omitted.

## 11. Disagreements / What I Would Do Differently

The packet's 49 count was environment-dependent: the explicit safe full run
later exposed five more failures. I kept the historical 49 intact and reported
the five separately.

During diagnosis I initially treated symbol-aware paper matching as broken.
Reading `PaperBroker.process_matching_detailed()` showed the compatibility mode
already maps the single fallback context lawfully. I removed my production edit
and re-ran focused lifecycle tests. The remaining pending order was correct
because no depth truth existed.

## 12. Limitations and Unknowns

- Fourteen tests are skipped in the final full run. Seven are newly explicit
  broker/access deferrals; the others are existing optional/environment gates.
- No external broker proof is claimed from this seam.
- No PAPER run or real mid-run Stop proof was executed.
- No browser or runtime-server proof was needed or run.
- The suite emits 384 warnings; warning cleanup was outside this packet.
- GammaFront fresh-entry feed remains dormant; this seam did not invent a feed.
- The tracked stale `state/operator/paper_baseline.json` remains preserved and
  unstaged.

## 13. Exact Staging Recommendation

Stage exactly these 24 files:

1. `pytest.ini`
2. `tests/test_alpaca_paper_10_symbol_expansion_execution_machine.py`
3. `tests/test_alpaca_paper_read_only_broker_truth.py`
4. `tests/test_alpaca_paper_tiny_order_planning_arming.py`
5. `tests/test_broker_truth_whole_bot_contribution_readiness.py`
6. `tests/test_concrete_live_adapter_read_only_scout.py`
7. `tests/test_controlled_paper_portfolio_lifecycle_exit_defense.py`
8. `tests/test_controlled_paper_portfolio_runtime_exposure_response.py`
9. `tests/test_decision_frame_orchestration_paper_exploration_alpha.py`
10. `tests/test_deterministic_end_to_end_harness.py`
11. `tests/test_gamma_front.py`
12. `tests/test_integrated_paper_portfolio_machine_seam.py`
13. `tests/test_integrated_paper_readiness.py`
14. `tests/test_intelligence_contribution_spine.py`
15. `tests/test_operator_home.py`
16. `tests/test_phase3_risk_gate_stress_proof.py`
17. `tests/test_replay_parity_acceptance.py`
18. `tests/test_runtime_dispatch_admission_telemetry.py`
19. `tests/test_seam7b_brain_math_runtime_stability.py`
20. `tests/test_upstream_dispatch_signal_submission.py`
21. `tests/test_whole_bot_contribution_activation_harness.py`
22. `reports/completion/PHASE_RUNPATH_GREEN_REPORT.md`
23. `CHECKPOINT_TRACKER.md`
24. `reports/codex_handoff_latest.md`

Do not stage `state/*`, `.pytest_tmp/`, logs, databases, screenshots, secrets,
`reports/operator_perf/*`, old handoffs, UI proposal packets, or untracked audit
scripts.
