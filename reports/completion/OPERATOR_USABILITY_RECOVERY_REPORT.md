# Operator Usability Recovery Report

Date closed: 2026-07-15 America/Chicago
Branch: `master`
Starting commit: `07ec0aa verify pre-arm run gate`
Governance: `AGENTS.md` v3 read in full before work; SHA-256
`87608620E92822CFDC3E7145E237DC9F852C5018AC8A0A8D344B7A2B1502D504`.
Board authorization: Shan reported that the opened bot did not allow useful
interaction, requested a 360-degree analysis and approval gate, then approved
the proposed repair with `proceed`.

## 1. Verdict

PASS for the scoped operator-usability recovery.

The cockpit now exposes a lawful, explicit Alpaca PAPER GET-only verification
action; Start remains fail-closed until that verification passes; Start performs
another fresh verification before process launch; Controls renders without the
runtime JavaScript exception that made the interface appear dead; event updates
no longer remount broad screens or poll continuously while SSE is healthy; AI
route labels distinguish configured, selected, and actual answer truth.

Final proof reached all applicable rungs for this seam:

- tests proved local logic: `1815 passed, 14 skipped, 0 failed`;
- runtime proved the durable launcher and API wiring;
- browser proof showed working screen navigation, stable input focus, truthful
  command states, and no horizontal overflow at 1440 and 390 pixels;
- Board-authorized Alpaca PAPER read-only proof showed the pinned account,
  current positions, and open orders through GET-only calls.

No PAPER run was started. Start was not clicked. No live or real-money mode was
enabled. No broker POST, order submission, cancel, replace, close, liquidation,
or other broker mutation occurred.

## 2. Files Changed

Production:

- `app/api/operator_paper_supervisor.py` - owns process-scoped GET-only
  authorization, broker-preflight proof state, fail-closed Start admission, and
  proof invalidation.
- `app/api/operator_readonly_api.py` - exposes governed verification, performs
  fresh Start preflight, returns exact readiness/AI route truth, and suppresses
  unchanged SSE payloads.
- `app/operator_activation/launch_readiness.py` - makes broker verification an
  explicit readiness condition and preserves the exact broker-confirmed
  refusal.
- `ui/operator-control-panel/app.js` - adds the verification control, corrects
  command and credential copy, fixes Controls rendering, preserves focus, and
  separates AI route labels.

Tests:

- `tests/test_operator_broker_preflight.py` - new governed verification and
  fresh-Start proof suite.
- `tests/test_operator_account_identity_pin.py`
- `tests/test_operator_ai_ask.py`
- `tests/test_operator_launch_readiness.py`
- `tests/test_operator_paper_baseline.py`
- `tests/test_operator_paper_supervisor.py`
- `tests/test_operator_readonly_api.py`
- `tests/test_operator_ui_wiring.py`

Governance records:

- `reports/completion/OPERATOR_USABILITY_RECOVERY_REPORT.md`
- `CHECKPOINT_TRACKER.md`
- `reports/codex_handoff_latest.md`

Protected repo runtime state, `.pytest_tmp/`, screenshots, secrets, old
handoffs, operator-performance reports, and untracked audit scripts were not
edited for the solution and are excluded from staging.

## 3. Root Cause

Plain-English blocker disposition:

1. **No lawful verification control:** the UI could show that broker proof was
   required but gave Shan no governed way to obtain it, so Start could never
   become legitimately ready from a fresh backend.
2. **Start used stale proof:** Start admission checked previously assembled
   readiness instead of forcing current account, positions, and open-order
   truth immediately before child launch.
3. **Update paths fought the operator:** SSE, five-second polling, unchanged
   one-second server events, and broad rerenders caused request churn and could
   steal focus, making controls feel unresponsive.
4. **Credential copy over-claimed:** `Validate read-only` only checked local
   credential setup and did not contact Alpaca, so the label misstated what the
   button proved.
5. **AI route truth was conflated:** the UI mixed the gateway default, the
   operator-selected route, and the provider that actually answered.
6. **Readiness hid the useful reason:** a failed broker-confirmed preflight
   could be flattened into a generic not-run message, so the operator did not
   see the exact safe next action.
7. **Controls crashed at render time:** `renderPaperLaunchControl` referenced
   `credentialConfigured`, `endpointValid`, and `activeRuntime` without defining
   them; clicking Controls raised `ReferenceError` and left the screen on
   Overview, which was the direct live-browser cause of "nothing works."

The preexisting readiness gate itself was not the defect. Requiring current
broker truth before Start is lawful and necessary; the missing governed action
and broken renderer made that gate operationally unreachable.

## 4. Fixes Implemented

### Governed broker verification

- Added `POST /operator/intent/paper/verify-readonly` inside the existing
  operator control plane, not a new authority or subsystem.
- Requires four exact confirmations: PAPER read-only, account/positions/orders
  GET-only scope, no broker mutation, and current-process-only authorization.
- Refuses non-PAPER, live, real-money, incomplete-confirmation, and active-run
  requests before broker access.
- Authorization is process scoped and resets on backend restart.
- Allowed broker methods/families are explicitly reported as GET-only account,
  positions, and open orders; all mutation authorities remain false.
- The resulting proof checks account status, blocking flags, expected/actual
  suffix, accepted-baseline suffix, current positions, current open orders, and
  baseline readiness. A mismatch or unsafe condition remains an exact refusal.

### Fresh Start admission

- `OperatorSnapshotProvider.paper_start_intent()` now validates the Start
  request without side effects, requires process authorization, executes a
  fresh broker preflight, and only then delegates to the existing supervisor.
- Malformed or unsafe requests are refused before broker access.
- The preflight is invalidated when the PAPER credential configuration or
  accepted baseline changes. Unrelated AI credential updates do not erase valid
  PAPER proof.
- The child account-pin check, baseline guard, Risk, MarketTruthSnapshot,
  NetEdge, TTL, sizing, OMS, and broker boundaries remain unchanged.

### Truthful interaction lifecycle

- EventSource is the primary runtime transport.
- Fifteen-second polling starts only when SSE is unavailable or errors, and
  stops after SSE reconnects.
- The server fingerprints stable payload content, emits only changes, and sends
  a comment keepalive after 15 seconds instead of identical one-second events.
- Lifecycle updates refresh command visibility and targeted status nodes. They
  do not broadly remount the current screen, AI panel, or active input.
- Controls now derives its credential, endpoint, and runtime booleans from the
  normalized backend payload before rendering.

### Operator copy and route truth

- Renamed the local credential action to `Check credential setup`.
- Added a separate `Verify PAPER broker truth` action with an explicit
  confirmation dialog naming the three GET families and all prohibited actions.
- AI status now exposes and displays `configured_gateway_default`,
  `selected_routes`, and `last_actual_route` separately.
- Broker-confirmed but policy-blocked readiness reports
  `BROKER_CONFIRMED_START_BLOCKED` and its exact reason instead of saying the
  broker read was not run.
- Historical audit facts are retained without crowding the exact current
  blocker out of the evidence packet.

## 5. 360-Degree Adjacent Improvements

- The verification endpoint is listed in the operator API contract and remains
  absent from all legacy manual-trade route families.
- Status, runtime, control state, launch readiness, and AI evidence consume the
  same supervisor-owned preflight state.
- Restart truth is explicit: a historical proof is not silently resurrected in
  a new backend process.
- A PAPER provider-credential change revokes proof because the external
  authority may have changed; changing an AI provider credential does not.
- Start result flags distinguish GET activity from mutation. A fresh preflight
  means `broker_call_occurred=true` can coexist lawfully with
  `broker_mutation_occurred=false`.
- The UI renderer regression test executes the production Controls renderer in
  Node with normalized backend data. Static source-string assertions alone did
  not catch the undefined identifiers.
- BOT and MKT vitality behavior from G-CLOSE remains evidence-bound. On the idle
  proof backend, BOT rendered STALE, MKT rendered UNKNOWN, and ECG animation was
  frozen.

## 6. Tests and Checks

### Before/after

- First full-suite run after the initial implementation exposed three stale
  account-pin/start fixtures: `1811 passed, 14 skipped, 3 failed`.
- Fixtures were raised to perform governed baseline acceptance and broker
  verification; no gate was weakened. The next full run was
  `1814 passed, 14 skipped, 0 failed`.
- Live browser navigation then found the Controls `ReferenceError`. The renderer
  was fixed and an executable regression test was added.
- Final full suite: `1815 passed, 14 skipped, 384 warnings, 0 failed` in
  176.83 seconds.
- Final focused operator gate: `177 passed, 72 warnings, 0 failed` in
  103.21 seconds.
- `python -m py_compile` passed for all 11 touched Python source/test files.
- `node --check ui/operator-control-panel/app.js` passed.

The 14 skips remain conditional external or environment-dependent deferrals;
none was deleted, stubbed, converted into a fake pass, or used to hide a
run-path failure.

### New proof cases

- `test_get_only_verification_requires_all_confirmations_and_makes_no_call_when_refused`
- `test_get_only_verification_proves_account_positions_orders_and_resets_on_restart`
- `test_verification_refuses_pin_mismatch_open_orders_and_baseline_drift`
- `test_start_revalidates_fresh_broker_truth_before_launching_fake_runner`
- `test_unrelated_ai_credential_change_preserves_paper_proof_but_paper_credential_change_revokes_it`
- `test_operator_event_stream_emits_changes_not_idle_one_second_duplicates`
- `test_command_center_renderer_executes_with_normalized_backend_truth`
- `test_runtime_lifecycle_uses_sse_with_polling_only_as_transport_fallback`
- `test_paper_verification_control_and_credential_copy_are_truthful`
- `test_ai_status_separates_gateway_default_selected_route_and_last_actual_answer`
- `test_ai_route_ui_separates_gateway_selected_and_actual_truth`

### Assertion-intent relabel log

- `test_supervisor_rejects_account_pin_mismatch_before_runner_launch` became
  `test_supervisor_rejects_account_pin_mismatch_after_governed_verification_before_runner_launch`.
  The refusal remains the assertion; the fixture now reaches it through the
  lawful verification gate.
- `test_supervisor_passes_pinned_account_to_child_env_when_identity_matches`
  became
  `test_supervisor_passes_verified_pinned_account_to_child_env_when_identity_matches`.
  The positive child-env assertion survives after current broker proof.
- `test_operator_baseline_accept_endpoint_is_local_only_and_readiness_uses_it`
  became
  `test_operator_baseline_accept_is_local_only_and_does_not_bypass_broker_preflight`.
  Local baseline acceptance is no longer treated as external broker proof.
- `test_historical_duplicate_refusal_is_not_current_runtime_blocker` became
  `test_historical_duplicate_refusal_is_not_current_blocker_but_restart_requires_fresh_preflight`.
  The historical refusal remains non-current, while restart now lawfully
  requires new process proof.
- Existing positive supervisor/API/readiness/AI fixtures that start a fake child
  now accept a lawful test baseline and pass a fake GET-only broker preflight
  first. Their original lifecycle assertions remain.
- Existing fast status/control fixtures that previously expected Start allowed
  from credentials alone now assert `PAPER_BROKER_PREFLIGHT_REQUIRED`. This is a
  reach-to-refuse contract correction: credentials and local state are not
  broker truth.
- The UI lifecycle test changed from parallel SSE plus polling to SSE primary
  with polling only as transport fallback, and now asserts that lifecycle
  updates do not remount broad UI surfaces.

No test assertion was weakened, no threshold moved, and no mock broker fill or
mutation was introduced.

## 7. Browser, Runtime, and Broker Read-Only Proof

### Cold runtime

The existing idle backend was terminated through the governed stack-shutdown
intent. Result: `NO_ACTIVE_RUN`, process-only shutdown, no broker call, no broker
mutation, and no order/liquidation action. The fixed backend then launched from
the existing hidden launcher with durable operator state at:

`%LOCALAPPDATA%\PovertyKiller\state\operator`

Cold boot before authorization truthfully reported `BLOCKED` /
`PAPER_BROKER_PREFLIGHT_REQUIRED`; the accepted protected baseline existed for
the pinned account and contained four positions.

### Alpaca PAPER GET-only proof

The governed verification returned:

- authorization scope: `CURRENT_OPERATOR_PROCESS_ONLY`;
- status/reason: `VERIFIED` / `PAPER_BROKER_PREFLIGHT_PASS`;
- account status: `ACTIVE`;
- expected/actual account suffix: `045ded` / `045ded`;
- account pin: passed;
- position count/symbols: 4 / `AVAXUSD`, `ETHUSD`, `LINKUSD`, `SOLUSD`;
- open-order count: 0;
- portfolio status: `BROKER_CONFIRMED`;
- final readiness: `READY_FOR_BOUNDED_PAPER`;
- `paper_start_allowed=true`;
- `paper_stop_allowed=false` while idle;
- live blocked and real money blocked;
- broker mutation, order, cancel, replace, close, and liquidation flags: false.

Production verification reads account, positions, and open orders, and the
independent account-pin assertion reads account again. Later browser hydration
may perform more approved GET-only portfolio refreshes. The exact total GET
count was not instrumented and is therefore unknown; this report does not claim
an exact external call count.

### Browser proof

The preferred in-app browser tool could not start because its tool invocation
failed with `missing field sandboxPolicy`. That failure is not hidden. Local
Microsoft Edge headless CDP was used as the fallback against the running app.

Observed after the renderer fix with cache disabled:

- a real click changed Overview to Controls with no JavaScript exception;
- desktop: `scrollWidth=1440`, `clientWidth=1440`, no horizontal overflow;
- mobile: `scrollWidth=390`, `clientWidth=390`, no horizontal overflow;
- Start visible and enabled on current green broker truth;
- Stop visible and correctly disabled while idle;
- Verify visible and enabled;
- `READY_FOR_BOUNDED_PAPER`, suffix `045ded`, `BROKER_CONFIRMED`, and all four
  baseline symbols visible;
- AI input remained connected, focused, and unchanged for 20 seconds;
- zero network requests occurred during that stable 20-second window;
- zero browser console errors and zero runtime exceptions after the fix;
- BOT STALE, MKT UNKNOWN, and frozen ECG while no bot process heartbeat existed.

Desktop and mobile screenshots were visually inspected, then removed with the
temporary browser profile/test artifacts. They are not staged. No persistent
screenshot artifact is claimed.

## 8. Self-Red-Team and Anti-Hallucination Check

### Before implementation

- **Duplicate authority:** rejected any design in which the UI or readiness
  module could decide broker truth. The supervisor owns authorization/proof;
  the existing provider performs reads; readiness and UI consume it.
- **Fake readiness:** proof resets on backend restart and Start revalidates.
  Local credentials or accepted baseline alone cannot green-light Start.
- **Hidden broker truth:** exact account pin, account state, position count,
  symbols, open-order count, and refusal reason remain visible and structured.
- **Manual trade path:** the new control performs only verification. It cannot
  submit, cancel, replace, close, liquidate, or force an order.
- **Risk/economic weakening:** no MarketTruthSnapshot, NetEdge, stale/TTL,
  sizing, masking, Risk, OMS, strategy, or broker-governor threshold was changed.
- **Mock/stale truth:** test clients are confined to tests; production truth is
  marked broker-confirmed only after approved GETs.
- **UI clutter:** one verification command was placed beside the existing
  bounded-run controls because it answers the immediate blocker. No N1/N2/N3
  dashboard expansion was added.
- **Stop condition:** any broker mutation, live endpoint, raw secret, duplicate
  authority, unsafe Start, or unrelated diff would have halted the seam. None
  occurred.

### After implementation

- Inspected: affected supervisor, API, readiness, UI lifecycle/renderer, tests,
  git diff, runtime API values, CDP DOM/console/network behavior, and sanitized
  broker-read results.
- Tests prove local contracts and regression behavior, including fake runner
  launch only after verification. They do not prove a real PAPER child run.
- Runtime proves the launcher, durable-state wiring, process-scoped proof, and
  backend/UI contract. Runtime did not prove Stop against a real child in this
  seam.
- Browser proves interaction and rendering for the observed Edge session. The
  preferred in-app browser was unavailable and screenshots were not retained.
- Broker-read-only proves the external account/positions/orders snapshot at the
  time observed. It does not prove future state and exact GET count is unknown.
- No profitability, fill, fee, TCA, P&L, execution quality, or run success is
  inferred from readiness.
- No failure was summarized away: the initial three fixture failures, the later
  live Controls exception, tool failure, warnings, skips, and proof limits are
  recorded.

## 9. Safety Confirmation

- No PAPER run.
- No live mode or live credentials.
- No real-money enablement.
- No broker mutation.
- No order submit, cancel, replace, close, flatten, liquidation, or manual sell.
- No manual trade control.
- No guard, threshold, Risk, NetEdge, stale/TTL, sizing, masking, strategy, OMS,
  or broker-governor weakening.
- No fake broker truth, order, fill, fee, P&L, TCA, liveness, or green state.
- No raw secrets printed, logged in this report, staged, or exposed in UI.
- `SovereignExecutionGuard` remains dormant and untouched.
- The governed automated position lifecycle remains intact and untouched.
- Tracked repo runtime state remains excluded from staging.

## 10. Module Status

- `OperatorPaperSupervisor`: WIRED - sole owner of PAPER process lifecycle,
  process-scoped broker-read authorization, current proof state, and Start
  admission.
- `OperatorSnapshotProvider`: WIRED - executes existing read-only portfolio and
  account-pin paths and supplies the canonical operator contracts.
- `launch_readiness`: WIRED - consumer of current supervisor/broker proof; no
  broker or process authority.
- operator control panel: WIRED - display and explicit intent collection only;
  no truth or trading authority.
- operator SSE transport: WIRED - change and keepalive transport only.
- AI route display/evidence: WIRED ADVISORY-ONLY - separates configuration,
  selection, and actual answer route; no broker authority.
- `SovereignExecutionGuard`: PRESERVED DORMANT - unchanged by this seam.
- 14 conditionally skipped external/environment tests: BLOCKED/DEFERRED with
  their existing named environment reasons; not silently passed.

No scoped module is silent, stubbed, deleted, or replaced.

## 11. Disagreements and What I Would Do Differently

The strongest correction to the prior implementation is that static UI wiring
tests were insufficient. They proved that Controls-related strings and handlers
existed but did not execute the renderer, so three free identifiers survived
and the primary operator screen crashed. A production operator cockpit should
retain the new executable renderer smoke test and live screen-navigation proof
for every arming-control change.

I did not convert broker verification into a persistent authorization setting.
That would make a restart look more ready than its current process evidence and
would weaken truth. The operator must verify again after a backend restart.

## 12. Limitations and Unknowns

- No PAPER Start was clicked and no real PAPER child process was launched.
- Stop was visible and its existing tests remain green, but it was not exercised
  against a real run in this seam.
- External broker truth is point-in-time and may change after verification.
- Exact total external GET count is unknown because calls are not globally
  instrumented; mutation flags and HTTP method/path behavior were inspected.
- Process-scoped verification resets on backend restart by design.
- The preferred in-app browser tool failed; Edge/CDP fallback proof was used.
- Browser screenshots were inspected but intentionally not retained/staged.
- The final suite has 14 conditional skips and 384 warnings; it has zero local
  failures, but skips/warnings are not claimed as passes.
- No profitability, market-entry opportunity, moving-floor exit, fill,
  reconciliation after a real run, or multi-day liveness claim was tested here.
- Protected dirty runtime files and old untracked artifacts remain in the
  worktree and continue to prevent a clean-tree baseline tag.

## 13. Exact Staging Recommendation

Stage exactly these files and nothing else:

1. `app/api/operator_paper_supervisor.py`
2. `app/api/operator_readonly_api.py`
3. `app/operator_activation/launch_readiness.py`
4. `ui/operator-control-panel/app.js`
5. `tests/test_operator_broker_preflight.py`
6. `tests/test_operator_account_identity_pin.py`
7. `tests/test_operator_ai_ask.py`
8. `tests/test_operator_launch_readiness.py`
9. `tests/test_operator_paper_baseline.py`
10. `tests/test_operator_paper_supervisor.py`
11. `tests/test_operator_readonly_api.py`
12. `tests/test_operator_ui_wiring.py`
13. `reports/completion/OPERATOR_USABILITY_RECOVERY_REPORT.md`
14. `CHECKPOINT_TRACKER.md`
15. `reports/codex_handoff_latest.md`

Explicitly exclude `state/*`, `.pytest_tmp/`, secrets, logs, databases,
screenshots, `reports/operator_perf/*`, old untracked handoffs, and untracked
audit scripts.

## Research Used

Comparable operating patterns reviewed:

- WHATWG Server-Sent Events processing model and MDN `EventSource` behavior for
  reconnecting one-way status streams.
- Browser focus/`activeElement` behavior for avoiding input destruction during
  background status refresh.
- Professional observability and trading-control patterns that separate
  transport health, backend process health, market freshness, external truth
  verification, and command admission.

Applied lessons:

- SSE is the primary stream; polling is a fallback, not a parallel heartbeat.
- Unchanged status produces keepalives instead of broad render work.
- Operator input nodes survive background lifecycle updates.
- Local credential configuration, external broker verification, and Start
  admission are distinct proofs and distinct controls.
- Configured AI route, selected route, and actual answer route are distinct
  operator facts.

Rejected patterns:

- persistent implicit broker authorization across restart;
- automatic verification without an explicit operator confirmation;
- making Start enabled from cached/local state alone;
- adding manual trade controls or using Stop to flatten positions;
- decorative liveness movement without current heartbeat evidence;
- broad cockpit redesign unrelated to the reported blocker.

Safety/truth impact: the applied design adds one explicit GET-only bridge to the
existing authority graph while making readiness stricter and more explainable.
It does not add trading authority or weaken any execution gate.
