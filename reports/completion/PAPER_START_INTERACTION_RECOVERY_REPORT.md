# PAPER Start Interaction Recovery Report

Date opened: 2026-07-15 America/Chicago
Branch: `master`
Starting commit: `a2b8000 restore truthful operator controls`
Status: COMPLETE

## Scout Note

Operator report: Shan selected a four-hour bounded PAPER run and pressed Start,
but observed no result.

Live repo/runtime facts before editing:

- backend loaded commit `a2b8000` and remained `IDLE`;
- `/operator/runtime` reported `NO_ACTIVE_RUNTIME_ATTACHED`;
- `/operator/latest-run` contained no session, PID, exit code, or refusal;
- durable `sessions.jsonl` contained no PAPER Start audit event from the attempt;
- `/operator/paper-control-state` reported
  `READY_FOR_BOUNDED_PAPER`, `paper_start_allowed=true`, and
  `paper_stop_allowed=false`;
- `14400` seconds is present in the backend allowed-duration set;
- no child process started and no broker mutation occurred.

The failure boundary is therefore before `POST /operator/intent/paper/start`.
The current UI renders the Start button from backend/duration readiness but does
not include the four local safety confirmations in its disabled state. A click
with any confirmation missing exits through `window.alert`; a click with all
confirmations exits if the separate native `window.confirm` is dismissed. These
branches produce no inline action state and no durable server event.

The exact pre-POST branch taken in Shan's already-open browser is unknown because
that browser's JavaScript memory/dialog state is not externally observable. The
strongest evidence-backed diagnosis is the client-only confirmation workflow,
not the runner, duration, account pin, broker state, or backend Start endpoint.

Scoped files:

- `ui/operator-control-panel/app.js`
- `tests/test_operator_ui_wiring.py`
- `tests/test_operator_home.py` - added after the first full-suite run exposed a
  stale literal-copy assertion for this exact confirmation workflow
- one existing operator supervisor/API test file only if needed to pin the
  already-supported `14400`-second positive contract
- this report, tracker, and latest handoff at close

Forbidden/unrelated files:

- trading strategies, Risk, NetEdge, MarketTruthSnapshot, TTL, sizing, masking,
  OMS, broker adapters/governor, thresholds, credentials, and tracked runtime
  state
- protected dirty `state/*`, `.pytest_tmp/`, old reports, screenshots, secrets,
  and untracked audit scripts

## Pre-Implementation Red Team

- **Duplicate authority:** the UI may collect confirmations and explain command
  state, but the existing supervisor remains the sole Start authority. The UI
  will not infer or override broker readiness.
- **Fake readiness:** backend readiness and operator-command readiness must be
  displayed separately. Green backend proof must not make an unconfirmed button
  look actionable.
- **Hidden broker truth:** account suffix, portfolio, positions, open orders,
  baseline, and fresh Start preflight stay canonical and unchanged.
- **Manual trade path:** the repair may only review and submit the existing
  bounded PAPER Start intent. It must not add buy, sell, force-trade, cancel,
  close, flatten, or liquidation controls.
- **Safety weakening:** all four confirmations remain required. The repair will
  replace the easy-to-miss native dialog flow with a visible two-step review,
  not remove a confirmation layer.
- **Runtime-vs-test gap:** tests must execute the confirmation-state and renderer
  behavior. Browser proof must intercept the Start POST or stop before it; Codex
  will not launch a second real PAPER run to validate UI behavior.
- **Stale/mock truth:** any browser interception is test-only and cannot be
  represented as a real run, order, fill, or broker result.
- **UI clutter:** one compact confirmation counter, exact blocker line, and one
  inline final-review panel answer the reported operator question. No unrelated
  cockpit redesign enters scope.
- **Stop condition:** halt immediately if an active child/session appears, a
  broker mutation would be required, live/real money appears, a safety gate
  would need weakening, or files outside the scoped seam enter the diff.

## Implementation Plan

1. Make the Start control fail visibly closed until backend readiness, draft
   validity, and all four safety confirmations are simultaneously true.
2. Show confirmation count and exact missing items inline; distinguish backend
   readiness from command readiness.
3. Replace the silent native pre-POST path with an inline two-step review:
   `Review & Start` then `Confirm & Start`, with exact profile, watchlist,
   duration, and no-live/no-manual-trade boundary visible.
4. Show pending, accepted, refused, and failed Start results in an `aria-live`
   status surface; invalidate a pending review when the draft changes.
5. Prove four-hour payload preservation without issuing a real Start, then run
   focused and full regression tests and browser validation with the Start POST
   intercepted.

## 1. Verdict

PASS for the scoped interaction recovery.

The original operator attempt did not start a run: no Start request, audit
event, session, PID, refusal, order, or broker mutation reached the backend.
Four hours was and remains a lawful configured duration. The browser control was
the failure: backend green state made the button look actionable before its four
operator confirmations were complete, and all pre-POST exits relied on native
browser dialogs with no persistent inline result.

The repaired control now has three truthful stages:

1. backend readiness and draft validity;
2. four visible operator confirmations;
3. an inline final review followed by an explicit `Confirm & Start` action.

Pending, accepted, refused, and response-unknown states render inline. The
server remains the only Start authority and still performs fresh broker
preflight immediately before launching a child.

No real PAPER run was started during the repair or validation.

## 2. Files Changed

- `ui/operator-control-panel/app.js` - truthful confirmation gate, inline final
  review, pending/result state, lost-response safety, and exact command copy.
- `tests/test_operator_ui_wiring.py` - executable renderer and two-step Start
  contract coverage.
- `tests/test_operator_home.py` - confirmation requirement now asserts the
  actual four-field gate and two-step intents instead of one obsolete popup
  sentence.
- `tests/test_operator_broker_preflight.py` - positive 14,400-second fake-runner
  proof after fresh broker preflight.
- `reports/completion/PAPER_START_INTERACTION_RECOVERY_REPORT.md` - this record.
- `CHECKPOINT_TRACKER.md` - Board report, result, and current boundary.
- `reports/codex_handoff_latest.md` - continuation truth.

No broker, Risk, strategy, threshold, OMS, credential, launcher, or tracked
runtime-state file changed.

## 3. Root Cause

Primary root cause: the UI had two different definitions of "Start allowed."
The green badge/button used backend readiness and duration validity, while the
click handler separately required four unchecked-by-default confirmations. A
click could therefore appear valid and then return before the POST.

Secondary root cause: every pre-POST outcome used transient `window.alert` or
`window.confirm`. No inline state said which confirmations were missing, whether
the final request had been reviewed, whether a POST was pending, or whether the
backend accepted/refused it. A popup dismissed, hidden behind another window,
or simply not noticed looked exactly like a dead button.

Four hours was not the blocker. The live backend explicitly included `14400` in
its allowed-duration set and reported `READY_FOR_BOUNDED_PAPER` with Start
allowed.

The exact dialog/return branch taken inside Shan's already-open browser remains
unknown. Repo/runtime evidence proves only that the POST was never sent; this
report does not promote the strongest inference into a fact.

## 4. Fixes Implemented

- Added one canonical `PAPER_START_CONFIRMATION_FIELDS` map for PAPER-only, live
  locked, real-money blocked, and no manual trades.
- Added a pure confirmation-state function with count, missing fields, and
  operator-readable English.
- Added `paperStartDisabledReason`; the primary control now fails visibly closed
  on backend refusal, invalid draft, or any missing confirmation.
- Changed the backend badge to `Backend ready` instead of implying that the
  entire operator command was ready.
- Added separate proof tiles for backend Start authority, operator
  confirmations, and command readiness.
- Renamed the first action to `Review & Start Bounded PAPER Run`. It assembles
  and displays the exact profile, duration, watchlist, and authority boundary but
  sends no request.
- Added `Confirm & Start Bounded PAPER Run` as the second explicit action.
- Added an `aria-live=polite` action-status surface for idle, review-ready,
  pending, accepted, refused, cancelled, invalidated, and response-unknown
  states.
- Draft or confirmation changes invalidate an existing final review.
- A request error clears the reviewed payload and refreshes runtime state. It
  explicitly tells the operator not to retry blindly because the response could
  have been lost after server acceptance.
- The POST payload is frozen at review and compared with the current draft
  before submission.

## 5. 360-Degree Adjacent Improvements

- The primary button's `disabled`, `aria-disabled`, tooltip, and
  `data-disabled-reason` now stay synchronized during lifecycle refreshes.
- The final-confirm button is disabled if readiness changes or a request is
  already pending.
- Cancel review is explicit and records `No Start request was sent`.
- Reset draft clears any reviewed Start payload.
- Background SSE refresh still patches targeted lifecycle state without broad
  form remounting.
- Backend and UI continue to use the existing bounded Start endpoint; no second
  control plane or lifecycle owner was introduced.
- A 14,400-second positive test proves the backend passes the duration to the
  existing fake runner after a fresh account/positions/open-orders preflight.

## 6. Tests and Checks

- First scoped run: `57 passed, 3 failed`. The three failures were stale UI
  assertions for old popup/direct-Start copy and a renderer harness that omitted
  disabled-reason attributes.
- Updated scoped run: `60 passed, 0 failed`.
- Integrated operator gate: `178 passed, 72 warnings, 0 failed`.
- First full suite: `1815 passed, 14 skipped, 1 failed`. The sole failure was
  `test_home_paper_launch_control_requires_all_safety_confirmations`, which
  asserted one removed literal popup sentence.
- Post-relabel focused run: `66 passed, 0 failed`.
- Final full suite: `1816 passed, 14 skipped, 384 warnings, 0 failed` in
  198.70 seconds.
- `node --check ui/operator-control-panel/app.js`: PASS.

The 14 skips remain the existing conditional external/environment deferrals;
none became a fake pass.

### Assertion-intent relabel log

- `test_command_center_has_paper_launch_control_and_safe_duration_options` now
  asserts `Command readiness` and the canonical max-lease validation reason
  rather than removed direct-alert copy. Safety intent is unchanged.
- `test_command_center_renderer_executes_with_normalized_backend_truth` now
  executes both states: Start review disabled at 3/4 and enabled at 4/4. Its old
  tag matcher could miss a `disabled` attribute that appeared before
  `data-intent`; the matcher now inspects the complete button tag.
- `test_run_paper_start_payload_uses_preserved_draft_values` now asserts review,
  final confirmation, payload signature, pending/unknown handling, and absence
  of native popup branches.
- `test_home_paper_launch_control_requires_all_safety_confirmations` moved from
  one literal sentence to the four exact confirmation fields, confirmation
  state/disabled functions, visible status surface, and two-step intent names.
- Added
  `test_four_hour_start_reaches_existing_fake_runner_after_fresh_preflight` to
  preserve the positive 14,400-second server/runner twin.

No assertion, guard, or threshold weakened.

## 7. Browser, Runtime, and Broker Proof

### Original attempt

Immediately after Shan's report:

- backend: `a2b8000`, `IDLE`;
- runtime: `NO_ACTIVE_RUNTIME_ATTACHED`;
- latest session/PID/refusal: none;
- durable Start audit event: none;
- four-hour duration allowed: true;
- broker mutation: none.

This proves the click stopped before the backend Start endpoint.

### Repaired browser flow

The bundled in-app browser again failed to initialize with
`missing field sandboxPolicy`; Microsoft Edge headless CDP was the honest
fallback. Cache was disabled.

At desktop width 1440:

- initial state: Start review disabled;
- confirmation text: `0/4 safety confirmations complete` plus all four missing
  items;
- selected duration: `14400`;
- after 4/4: review action enabled;
- review panel: profile, `4 hours (14400s)`, six-symbol watchlist, and
  PAPER-only/live-locked/no-manual-trades authority visible;
- review badge: `Start not sent`;
- intercepted requests before final confirmation: 0;
- final click generated exactly one intercepted Start-shaped request with
  `duration_seconds=14400`, `real_money=false`, and `live=false`;
- test response rendered `START_REFUSED: INTERCEPTED_TEST_ONLY_NO_RUN` inline;
- browser exceptions: 0;
- console errors: 0;
- horizontal overflow: false.

At mobile width 390:

- `clientWidth=390`, `scrollWidth=390`, horizontal overflow false;
- the intercepted refusal remained present in the live-region status surface.

The Start POST was intercepted inside the browser before network dispatch. A
post-proof runtime check still reported no active runtime, no session, and Stop
not allowed. Screenshots were visually inspected and are excluded from staging.

## 8. Self-Red-Team and Anti-Hallucination Check

- **Inspected:** live endpoints, allowed durations, durable audit tail, UI
  renderer/handlers, related tests, browser DOM/network payload, screenshots,
  console/exception counts, and final git diff.
- **Tests prove:** confirmation gating, renderer state, exact four-hour fake
  runner payload, existing fresh preflight, and repository regression health.
- **Runtime proves:** the original attempt and all Codex validation left no real
  run attached.
- **Browser proves:** the repaired UI produces visible 0/4, 4/4, review, and
  result states and preserves the 14,400-second payload.
- **Inference:** Shan most likely encountered missing confirmations or a native
  dialog boundary. The exact browser branch is unknown.
- **Not proved:** a real post-fix child launch, real run heartbeat, Stop during
  that run, orders/fills, or final reconciliation.
- **No summarized-away failure:** both initial scoped failures and the first
  full-suite stale assertion are recorded above.
- **No duplicate authority:** UI state collects/reviews intent only; supervisor
  admission remains canonical.
- **No fake result:** `INTERCEPTED_TEST_ONLY_NO_RUN` is test-only, visibly
  refused, and is not claimed as runtime execution.

## 9. Safety Confirmation

- No real PAPER Start by Codex.
- No live mode or real money.
- No broker mutation, order, cancel, replace, close, flatten, liquidation, or
  manual trade control.
- No Risk, NetEdge, MarketTruthSnapshot, stale/TTL, sizing, masking, strategy,
  OMS, broker-governor, or threshold change.
- Fresh broker preflight and account pin remain required by the backend.
- Existing governed Stop and automated position lifecycle are unchanged.
- `SovereignExecutionGuard` remains dormant.
- No secrets printed, exposed, edited, or staged.
- Protected runtime state remains unstaged.

## 10. Module Status

- operator Start UI: WIRED - confirmation collection, review, request status,
  and display only.
- `OperatorPaperSupervisor`: WIRED/UNCHANGED - sole lifecycle and Start admission
  authority.
- `OperatorSnapshotProvider.paper_start_intent`: WIRED/UNCHANGED - fresh broker
  preflight before supervisor delegation.
- bounded PAPER runner: WIRED/UNCHANGED - receives validated duration only after
  server admission.
- governed Stop: WIRED/UNCHANGED.
- broker/Risk/OMS/strategy authorities: WIRED/UNCHANGED.
- `SovereignExecutionGuard`: PRESERVED DORMANT.

No scoped module is silent, stubbed, deleted, or replaced.

## 11. Disagreements and What I Would Do Differently

The prior UI treated native browser dialogs as sufficient operator feedback.
That was not operator-grade for a multi-step arming control: dialog state is
ephemeral, can be obscured by window focus, and leaves no page-level truth. The
inline review and status surface should have existed before Shan's first Start
attempt.

I did not automatically resend Shan's failed Start request. Reconstructing and
issuing a money-adjacent request from inference would be unsafe, even in PAPER.
The repaired UI returns control to Shan with the exact request visible.

## 12. Limitations and Unknowns

- The exact pre-POST branch taken by Shan's original browser is unknown.
- No real post-fix PAPER child was launched; browser proof used interception and
  backend proof used a fake runner.
- Stop, heartbeat, decisions, orders, fills, and final reconciliation were not
  exercised in a real run.
- External broker truth remains point-in-time. The existing process-scoped
  verification resets on backend restart.
- Exact external GET count remains uninstrumented.
- The preferred in-app browser was unavailable; Edge/CDP fallback was used.
- Temporary screenshots are evidence observed during the session, not staged
  artifacts.
- The full suite has 14 skips and 384 warnings; they are not claimed as passes.
- Protected dirty runtime and old untracked artifacts remain in the worktree.

## 13. Exact Staging Recommendation

Stage exactly:

1. `ui/operator-control-panel/app.js`
2. `tests/test_operator_ui_wiring.py`
3. `tests/test_operator_home.py`
4. `tests/test_operator_broker_preflight.py`
5. `reports/completion/PAPER_START_INTERACTION_RECOVERY_REPORT.md`
6. `CHECKPOINT_TRACKER.md`
7. `reports/codex_handoff_latest.md`

Exclude `state/*`, `.pytest_tmp/`, all `.test-*` directories, screenshots,
secrets, logs, databases, old handoffs, operator-performance reports, and
untracked audit scripts.

## Research Used

Patterns reviewed:

- W3C WAI-ARIA status-message guidance: dynamic action results that do not move
  focus need a programmatically determinable status/live region.
- W3C guidance for `aria-live=polite`: announce updates at a graceful
  opportunity without interrupting the operator's current task.
- IBM Carbon high/medium-impact action patterns: show consequences before the
  action and show a pending/completion notification when an action is not
  immediate.

Applied:

- persistent inline review before the final action;
- an `aria-live=polite` pending/result surface;
- exact consequences and boundaries adjacent to the confirmation control;
- explicit `Start not sent` and `Do not retry` truth.

Rejected:

- removing a confirmation layer;
- automatic retry after a lost response;
- modal-only/native-popup-only state;
- enabling Start from backend green state without local confirmations;
- any automatic run, manual trade, or broker cleanup control.

Sources:

- https://www.w3.org/WAI/WCAG22/Techniques/aria/ARIA19
- https://www.w3.org/TR/wai-aria/#aria-live
- https://carbondesignsystem.com/community/patterns/remove-pattern/
