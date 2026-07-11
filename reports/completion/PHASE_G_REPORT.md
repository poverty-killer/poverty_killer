# Phase G Report - Bounded PAPER Run Ready

Date: 2026-07-11 America/Chicago
Branch: master
Latest commit at boot: `0911297 complete phase F operator cockpit truth`
Board packet: Phase G, D4 read-only paper broker inspection re-armed.

## Gate Verdict

| Gate | Result | Evidence |
| --- | --- | --- |
| G1 Launch readiness proves `READY_FOR_BOUNDED_PAPER` end-to-end | PASS | `/operator/launch-readiness`: `final_launch_readiness=READY_FOR_BOUNDED_PAPER`, `paper_start_allowed=true`, no reason codes. Browser controls show `Ready for governed PAPER` and `Start allowed`. |
| G2 Endpoint is paper; live blocked; real-money blocked | PASS | `/operator/launch-readiness`: `PAPER_ENDPOINT_CONFIRMED`, `live_blocked=true`, `real_money_blocked=true`; browser shows `PAPER endpoint`, `Live locked`, `Real-money blocked`. |
| G3 Account pin enforced on all broker paths | PASS | Supervisor readiness/start uses account identity assertion; child runner env carries the pin; direct PowerShell launcher preflight now validates `alpaca_paper_preflight_account_pin_status`. Stale accepted baseline from `104e2a` now blocks readiness/control-state. |
| G4 Drained-account rejection test passes | PASS | `test_preflight_account_pin_status_rejects_104e2a`; `test_stale_baseline_from_wrong_account_blocks_paper_readiness`; account mismatch returns/propagates `ALPACA_PAPER_ACCOUNT_PIN_MISMATCH` or `paper_baseline_account_pin_mismatch`. |
| G5 Open-order and position baselines known and broker-confirmed | PASS | Read-only Alpaca paper GET proof: account `redacted_suffix:045ded`, status `ACTIVE`, 4 positions (`AVAXUSD`, `ETHUSD`, `LINKUSD`, `SOLUSD`), 0 open orders, cash `990112.68`, buying power `3960450.72`, total equity `1000426.67` at final backend snapshot. |
| G6 Positive-path browser proof | PASS | Desktop and mobile CDP proof against local `/operator-ui`: pin visible, broker truth visible, 4 symbols visible, Start enabled on green backend, no horizontal overflow. Screenshots in `C:\tmp\poverty_killer_phase_g_runtime\phase_g_desktop_controls.png` and `C:\tmp\poverty_killer_phase_g_runtime\phase_g_mobile_controls.png`. |
| G7 Bounded-run parameters and final reconciliation explicit | PASS | UI and backend expose max lease `432000` seconds; allowed durations include 72 hours and 5 days; launch readiness has `final_reconciliation_required=true`. |

Verdict: Phase G is complete for readiness proof. No PAPER run was executed. The actual bounded PAPER run remains Shan/Board-gated.

## 1. Verdict

PASS, with an explicit runtime-state condition:

The bot is ready to request a Board-authorized bounded PAPER run only when launched with the configured Phase G operator state containing the broker-confirmed `045ded` baseline. The stale repo default baseline remains unmodified and is now safely blocked if used.

Proof level reached: broker-read-only rung plus desktop/mobile browser proof. No execution rung was attempted.

## 2. Files Changed

- `app/execution/alpaca_paper_adapter.py`
- `app/operator_activation/paper_baseline.py`
- `app/operator_activation/launch_readiness.py`
- `app/api/operator_readonly_api.py`
- `app/api/operator_paper_supervisor.py`
- `scripts/run_bounded_paper.ps1`
- `ui/operator-control-panel/app.js`
- `tests/test_alpaca_paper_credential_authority_guard.py`
- `tests/test_operator_paper_baseline.py`
- `tests/test_operator_readonly_api.py`
- `tests/test_operator_ui_wiring.py`
- `tests/test_windows_powershell_paper_launch_authority.py`
- `reports/completion/PHASE_G_REPORT.md`
- `CHECKPOINT_TRACKER.md`
- `reports/codex_handoff_latest.md`

Not staged or edited intentionally: `state/*`, `.operator_secrets/*`, logs, screenshots, `.pytest_tmp/`, old untracked reports/scripts.

## 3. Root Cause

Three issues blocked a truthful Phase G close:

1. Direct bounded-paper launcher path did not independently assert the pinned Alpaca paper account suffix after read-only preflight.
2. Accepted nonzero baseline readiness was previously treated as blocked/degraded even when protected baseline runtime context and same-symbol guard were loaded.
3. Browser proof exposed two UI truth issues: `/operator-ui` no-slash route served broken relative asset paths, and the Run PAPER button inherited a legacy disabled reason despite canonical `OPERATOR_PAPER_CONTROL_STATE` being green.

Additional red-team finding: repo default `state/operator/paper_baseline.json` is a stale accepted baseline for `redacted_suffix:104e2a`. Without a baseline-account pin guard, a future path could accidentally combine pinned `045ded` broker truth with a stale `104e2a` baseline. That is now blocked.

## 4. Fixes Implemented

- Added `alpaca_paper_preflight_account_pin_status()` to validate the broker-reported account suffix from read-only Alpaca paper preflight.
- Added direct launcher preflight failure on account pin mismatch or missing account identity.
- Added shared `accepted_baseline_account_suffix()` extraction in the baseline authority.
- Added launch-readiness and paper-control-state blockers for accepted baseline account suffix mismatch.
- Made protected nonzero baseline readiness PASS only when protected baseline runtime context is loaded and same-symbol baseline guard is active.
- Made supervisor baseline context honor configured `PK_OPERATOR_STATE_DIR` instead of always falling back to repo default state.
- Fixed `/operator-ui` no-slash asset hydration by rendering `/operator-ui/...` asset URLs.
- Fixed Run PAPER UI disabled-state derivation so canonical `canRun.allowed=true` does not fall through to legacy disabled reasons.
- Removed stale UI copy saying a green bounded path was “Not 72-hour ready yet”; replaced with the actual protected-baseline condition.

## 5. 360 Adjacent Improvements

- Browser proof found and fixed the no-slash UI route hydration failure.
- Runtime proof found and fixed configured operator state being ignored by supervisor baseline loading.
- Red-team proof found and fixed stale default baseline account mismatch as a readiness blocker.
- UI copy now aligns with the backend readiness contract and non-flat account policy.

## 6. Tests / Checks

Final source-state checks:

```text
python -m pytest tests\test_operator_paper_baseline.py tests\test_alpaca_paper_credential_authority_guard.py tests\test_windows_powershell_paper_launch_authority.py tests\test_operator_readonly_api.py tests\test_operator_ui_wiring.py -q --basetemp .pytest_tmp\phase_g_final_core3
106 passed, 72 existing warnings
```

```text
python -m pytest tests\test_phase_d_paper_readiness_truth.py tests\test_operator_account_identity_pin.py tests\test_operator_launch_readiness.py tests\test_operator_paper_supervisor.py tests\test_broker_gateway_adapter_layer.py -q --basetemp .pytest_tmp\phase_g_final_adjacent3
66 passed, 72 existing warnings
```

```text
python -m py_compile app\operator_activation\launch_readiness.py app\api\operator_readonly_api.py app\api\operator_paper_supervisor.py app\execution\alpaca_paper_adapter.py app\operator_activation\paper_baseline.py
PASS
```

```text
node --check ui\operator-control-panel\app.js
PASS
```

```text
git diff --check
PASS; only existing line-ending warnings on `state/*` and touched PowerShell file.
```

## 7. Browser / Runtime Validation

Read-only broker/backend proof used local API with:

- `PK_OPERATOR_STATE_DIR=C:\tmp\poverty_killer_phase_g_runtime\state\operator`
- `PK_BOARD_AUTHORIZED_PAPER_BROKER_READ=YES_D4_BOARD_AUTHORIZED`
- canonical Alpaca PAPER credential source only
- no live endpoint
- no broker mutation
- no PAPER run

Final backend proof:

- `launch_final=READY_FOR_BOUNDED_PAPER`
- `launch_start_allowed=true`
- `launch_paper_endpoint_status=PAPER_ENDPOINT_CONFIRMED`
- `launch_paper_account_pinned=true`
- `launch_actual_suffix=045ded`
- `launch_expected_suffix=045ded`
- `control_dominant_blocker=READY_FOR_BOUNDED_PAPER`
- `control_baseline_account_suffix=045ded`
- `control_baseline_account_matches_pin=true`
- `control_max_lease_seconds=432000`
- `portfolio_status=BROKER_CONFIRMED`
- `portfolio_account_id=redacted_suffix:045ded`
- `portfolio_position_count=4`
- `portfolio_open_order_count=0`
- `portfolio_symbols=AVAXUSD, ETHUSD, LINKUSD, SOLUSD`
- `portfolio_cash=990112.68`
- `portfolio_buying_power=3960450.72`
- `portfolio_total_equity=1000426.67`
- all mutation/live/real-money flags false

Desktop browser proof:

- `screen=controls`
- `backendConnected=true`
- `pinnedAccountVisible=true`
- `startAllowedVisible=true`
- `readyVisible=true`
- `brokerTruthVisible=true`
- `symbolsVisible=true`
- `liveLockedVisible=true`
- `realMoneyBlockedVisible=true`
- `boundedCopyVisible=true`
- `staleCopyAbsent=true`
- `startDisabled=false`
- `scrollWidth=1440`, `clientWidth=1440`, `horizontalOverflow=false`

Mobile browser proof:

- same truth flags as desktop
- `scrollWidth=390`, `clientWidth=390`, `horizontalOverflow=false`

## 8. Governance / Safety Confirmation

- No PAPER run.
- No live mode.
- No real-money path.
- No order placement.
- No cancel/replace/close/liquidate/flatten.
- No manual buy/sell controls.
- No threshold/gate/economic/risk weakening.
- No raw secrets printed or staged.
- No `.operator_secrets/*`, state, logs, screenshots, or runtime files staged.
- Governed lifecycle remains intact as the only lawful broker-mutating exception for a later authorized run.

## 9. Challenge Note Results

Challenge answers from live repo:

- Broker paths: direct PowerShell launcher needed its own account-pin assertion; fixed.
- Existing 4 positions: readiness can be true only with accepted protected baseline, loaded runtime context, same-symbol baseline guard, and matching baseline account suffix. The UI surfaces non-flat status, not a clean-flat assumption.
- Readiness authority: `OPERATOR_LAUNCH_READINESS` and `OPERATOR_PAPER_CONTROL_STATE` are now aligned on baseline/account blockers; UI button consumes canonical `OPERATOR_PAPER_CONTROL_STATE`.

## 10. All-Paths Pin Proof

- Arming/status path: `OperatorPaperSupervisor._paper_account_identity_assertion()` and launch readiness require `paper_account_pinned=true`.
- Supervisor start path: `paper_start_intent` forces a fresh account identity proof before runner spec creation.
- Child/run path: supervisor process env carries `PK_ALPACA_PAPER_EXPECTED_ACCOUNT_SUFFIX=045ded`.
- Direct script path: `scripts/run_bounded_paper.ps1` calls `alpaca_paper_preflight_account_pin_status()` and fails preflight on mismatch.
- Baseline path: accepted baseline account suffix must match the pinned suffix, blocking stale `104e2a` local baseline state.

## 11. Existing Positions Handling

Current broker-confirmed non-flat account:

- `AVAXUSD`
- `ETHUSD`
- `LINKUSD`
- `SOLUSD`

Policy:

- Existing positions are accepted as a protected baseline.
- Existing baseline quantities are not sold by default.
- Same-symbol baseline trading remains blocked until run-lot tracking exists.
- Bot incremental P&L remains separated from baseline carry; no fake clean baseline is shown.

## 12. Disagreements / Board Notes

No safety disagreement remains for Phase G readiness.

The actual PAPER run remains Board-gated. Pressing Start later still requires Shan's explicit run authorization and operator confirmations. This report does not authorize a run.

## 13. Limitations / Unknowns

- No PAPER execution proof was run.
- Broker equity moved slightly during repeated read-only proof because market values changed; final backend snapshot was `1000426.67`, while browser captures observed nearby values.
- Tracked `state/operator/paper_baseline.json` remains stale for `redacted_suffix:104e2a` and was not edited or staged. If default repo state is used, readiness now fails closed with `paper_baseline_account_pin_mismatch`. The positive Phase G proof used the configured operator state path under `C:\tmp` containing the broker-confirmed `045ded` baseline.
- Account activity/transfer history was not read; D4 scope was account/open-orders/positions only.

## 14. Research Used

No new external research was performed for Phase G. This was a safety/runtime proof seam, and the relevant UI patterns were inherited from Phase F cockpit work: status-first control center, explicit blockers, proof tiles, fail-closed button state, and advanced details behind expanders.

## 15. Self Red-Team / Anti-Hallucination

- Fake readiness via stale baseline: closed by baseline account suffix guard.
- Fake readiness via UI no-slash shell: closed by absolute `/operator-ui/...` assets.
- Fake readiness via legacy disabled reason: closed by canonical `canRun.allowed=true` short-circuit.
- Hidden second broker path: direct launcher now validates pin after read-only preflight.
- Broker mutation hidden in proof: portfolio and preflight proof flags show no order submission/cancel/liquidation/live/real-money.

## 16. Runtime Proof Rung

Highest rung reached: broker-read-only plus browser proof.

Not reached: PAPER execution/run proof.

## 17. Exact Changed Runtime State

No tracked runtime state was edited intentionally.

Temporary proof files created outside repo:

- `C:\tmp\poverty_killer_phase_g_runtime\final_backend_summary.json`
- `C:\tmp\poverty_killer_phase_g_runtime\browser_desktop_metrics.json`
- `C:\tmp\poverty_killer_phase_g_runtime\browser_mobile_metrics.json`
- `C:\tmp\poverty_killer_phase_g_runtime\phase_g_desktop_controls.png`
- `C:\tmp\poverty_killer_phase_g_runtime\phase_g_mobile_controls.png`

## 18. Dirty Tree Status

Protected dirty/untracked files still exist and must not be staged:

- `state/override_log.jsonl`
- `state/risk_state.backup`
- `state/risk_state.json`
- `state/risk_state.tmp`
- `state/session_journal.jsonl`
- `.pytest_tmp/`
- `AGENTS.prev.md`
- `POVERTY_KILLER_AUDIT_REPORT.txt`
- old untracked `reports/codex_handoff_*`
- `reports/operator_perf/`
- untracked audit scripts under `scripts/`

## 19. Staging Recommendation

Stage exactly:

```powershell
git add -- app/execution/alpaca_paper_adapter.py
git add -- app/operator_activation/paper_baseline.py
git add -- app/operator_activation/launch_readiness.py
git add -- app/api/operator_readonly_api.py
git add -- app/api/operator_paper_supervisor.py
git add -- scripts/run_bounded_paper.ps1
git add -- ui/operator-control-panel/app.js
git add -- tests/test_alpaca_paper_credential_authority_guard.py
git add -- tests/test_operator_paper_baseline.py
git add -- tests/test_operator_readonly_api.py
git add -- tests/test_operator_ui_wiring.py
git add -- tests/test_windows_powershell_paper_launch_authority.py
git add -- reports/completion/PHASE_G_REPORT.md
git add -- CHECKPOINT_TRACKER.md
git add -- reports/codex_handoff_latest.md
```

Do not stage `state/*`, `.pytest_tmp/`, screenshots, logs, old untracked reports, runtime files, or secrets.

## 20. Next Safe Action

Await Shan's explicit bounded PAPER run packet. If Shan authorizes the run, use the configured operator state that contains the broker-confirmed `045ded` protected baseline, or refresh/accept a `045ded` baseline through an approved local operator-state path before attempting start. The run must remain duration-bound and must end with final broker reconciliation.
