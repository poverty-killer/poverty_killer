# Operator Process Lifecycle Recovery Report

Date: 2026-07-15 America/Chicago
Branch: `master`
Starting commit: `e958abd make bounded paper start explicit`

## Scout Note (pre-code)

### Live truth

- The operator API is current at `e958abd`, PID `17708`, supervisor `IDLE`, with
  no active runtime attached. It is not a stale backend process.
- `/operator/run-visibility/status` contradicts that current supervisor truth:
  it reports `status=STOPPED` but `bot_vital_status=STALE` from a historical
  heartbeat more than two million seconds old. The cockpit renders that stale
  artifact as current bot vitality.
- The visible desktop launcher owns backend start/stop/restart through
  `scripts/open_operator_console.ps1`. Its desktop shortcut is routed through
  `scripts/open_operator_console_hidden.vbs` to that visible launcher.
- The cockpit already keeps an `EventSource` connection to `/operator/events`.
  The backend does not currently use connection lifecycle to distinguish an
  attached cockpit from an orphaned idle API.
- The existing `/operator/intent/stack/shutdown` endpoint and
  `OperatorPaperSupervisor` own process lifecycle. No second shutdown authority
  is required.
- Browser `unload` and `beforeunload` callbacks are not reliable process owners.
  The existing streaming connection can provide disconnect truth without
  depending on those callbacks.

### Scoped files

- `app/api/operator_readonly_api.py`: current supervisor vitality overlay,
  cockpit connection ownership, idle-only shutdown race guard.
- `ui/operator-control-panel/app.js`: truthful idle vitality copy and styling.
- `scripts/open_operator_console.ps1`: orphaned-idle fresh-start behavior,
  active-run protection, automatic status refresh, launcher-close cleanup.
- `scripts/open_operator_console_hidden.ps1`: preserve the same idle-only safety
  rule in the legacy direct entry path.
- `tests/test_operator_readonly_api.py`,
  `tests/test_operator_desktop_launcher.py`, and
  `tests/test_operator_ui_wiring.py`: behavioral and wiring proof.
- `docs/runbooks/operator_local_launch.md`: operator lifecycle contract.
- This report, `CHECKPOINT_TRACKER.md`, and the current handoff: continuity and
  exact staging evidence.

### Protected and unrelated files

All pre-existing `state/*`, `.pytest_tmp/`, old handoffs, UI proposal packets,
operator-performance output, and untracked audit helpers are preserved and are
not part of this seam.

## Pre-Code Self Red-Team

- **Duplicate authority:** browser and launcher code must request shutdown only
  through the existing stack-shutdown owner. They must not directly kill broad
  process-name matches.
- **Fake readiness/vitality:** an idle supervisor must not inherit a stale
  historical heartbeat as current vitality. Historical artifact staleness must
  remain disclosed as artifact evidence rather than erased.
- **Active-run safety:** automatic browser/launcher cleanup must be idle-only at
  the backend endpoint, not merely guarded by a launcher-side check that can
  race a Start request.
- **Broker truth:** cleanup must issue no broker request, order, cancel, close,
  liquidation, or manual trade action. Existing protected positions remain
  untouched.
- **Risk/economics:** no Risk, NetEdge, sizing, TTL, strategy, OMS, broker
  governor, or execution threshold is in scope.
- **Runtime-vs-test gap:** static launcher assertions alone are insufficient;
  provider tests must prove idle disconnect exits, active disconnect refuses,
  multiple browser clients do not cause early exit, and mutation flags stay
  false.
- **Browser lifecycle reliability:** do not use `unload` as a guaranteed signal.
  Reuse the existing SSE disconnect with a reconnect grace period.
- **Stop condition:** halt if any automatic path can stop an active supervisor,
  any force-kill becomes broader than the verified operator listener PID, or any
  broker mutation appears.

## Research Used (pre-code)

- MDN `Navigator.sendBeacon()` and Chrome Page Lifecycle guidance: unload and
  beforeunload are not reliable end-of-session signals; persistent connection
  loss plus a grace period is the stronger local ownership signal.
- Microsoft PowerShell process guidance: process termination should target a
  verified PID rather than a broad process-name wildcard.

## 1. Verdict

**PASS.** The screenshot exposed a real truth defect, but not a stale backend:
the current supervisor was `IDLE` while an old heartbeat artifact was being
rendered as current `BOT STALE` vitality. The cockpit now renders an unattached
runtime as `BOT IDLE` / `MKT NO_RUNTIME`, with both pulses frozen.

The last cockpit event-stream disconnect now schedules an eight-second,
reconnect-safe shutdown of an **idle** operator API through the existing
process-only stack-shutdown owner. A new launcher replaces an orphaned,
lifecycle-old, or code-stale idle backend before opening the cockpit. Both
automatic paths fail closed and preserve an active or uncertain PAPER runtime.

Code commit: `3e71c55 make operator backend lifecycle truthful`.

## 2. Files Changed

- `app/api/operator_readonly_api.py`: authoritative idle vitality overlay,
  cockpit connection counting, reconnect grace, idle-only shutdown admission,
  and Start-versus-shutdown serialization.
- `ui/operator-control-panel/app.js`: operator-readable idle/no-runtime vitality
  detail without a false stale alarm.
- `scripts/open_operator_console.ps1`: fresh-idle startup, guarded restart,
  two-second status refresh, lifecycle diagnostics, and launcher-close cleanup.
- `scripts/open_operator_console_hidden.ps1`: the legacy direct launcher now
  uses the same backend-enforced idle-only stale-process rule.
- `tests/test_operator_readonly_api.py`: event-stream ownership, multiple-client,
  reconnect, active-run refusal, zero-mutation, and Start/shutdown race tests.
- `tests/test_run_visibility.py`: current supervisor truth takes precedence over
  orphan historical artifacts.
- `tests/test_operator_desktop_launcher.py`: scoped process and lifecycle wiring
  assertions.
- `tests/test_operator_ui_wiring.py`: exact idle/no-runtime copy assertions.
- `docs/runbooks/operator_local_launch.md`: durable operator lifecycle contract.
- This report, `CHECKPOINT_TRACKER.md`, and
  `reports/codex_handoff_latest.md`: proof and continuity.

Protected `state/*`, `.pytest_tmp/`, old handoffs, UI proposal packets,
operator-performance output, and untracked audit helpers were not edited for
this seam and were not staged.

## 3. Root Cause

### Cluster A - false stale vitality

`OperatorSnapshotProvider.run_visibility_status()` read local historical
runtime artifacts and allowed their old heartbeat to define current vitality
even when `OperatorPaperSupervisor.status_snapshot()` said `IDLE`. The API
therefore returned contradictory truth (`STOPPED` plus `BOT STALE`) and the UI
faithfully displayed the contradiction.

### Cluster B - orphan backend lifetime

The cockpit already opened `/operator/events`, but the server did not account
for event-stream clients. Browser closure therefore had no lifecycle effect and
could leave an idle API running indefinitely.

### Cluster C - launcher reuse without lifecycle freshness

The visible launcher could detect code freshness, but startup reused a listening
backend without deciding whether it was idle, orphaned, or running an older
lifecycle contract. The hidden launcher also had a force-stop fallback after a
failed health check without a backend-owned idle admission condition.

## 4. Fixes Implemented

1. The supervisor is authoritative for attachment. When it is `IDLE`, the API
   now returns `status=IDLE`, `bot_vital_status=IDLE`,
   `market_vital_status=NO_RUNTIME`, and disallows both pulse animations. The
   stale artifact remains disclosed in `runtime_artifact_note`; it was not
   deleted or relabeled as fresh.
2. `/operator/events` now increments/decrements a server-side cockpit-client
   count in the stream generator's `try/finally` lifecycle.
3. The last disconnect starts an eight-second timer. A reconnect or another
   cockpit cancels/defer it. Expiry requests the existing
   `/operator/intent/stack/shutdown` lifecycle with
   `require_idle_supervisor=true`.
4. The backend atomically serializes Start and stack shutdown. After shutdown
   admission, a racing Start is refused as `STACK_SHUTDOWN_IN_PROGRESS`.
5. Idle-only shutdown is refused as
   `ACTIVE_OR_UNCERTAIN_RUNTIME_PROTECTED_FROM_AUTOMATIC_SHUTDOWN` unless the
   supervisor is authoritatively `IDLE`.
6. Launcher startup replaces only an orphaned, lifecycle-old, or code-stale
   idle backend. It reuses a current attached cockpit and preserves an active or
   uncertain runtime.
7. Existing `Stop Backend` remains the explicit, process-only operator command.
   Restart and automatic cleanup are idle-only. No new shutdown subsystem or
   second owner was created.

## 5. 360-Degree Adjacent Improvements

- `/operator/launcher-status` now exposes cockpit count, idle-exit enablement,
  grace seconds, and the last disconnect action.
- The visible launcher refreshes its truth every two seconds and shows
  supervisor state, active run, cockpit clients, and idle-exit configuration in
  diagnostics.
- Closing the launcher window cleans up only when no cockpit is connected and
  the supervisor is idle; otherwise it records why the backend was preserved.
- The hidden launcher no longer force-kills after an idle-only shutdown refusal
  or unavailable response.
- Refreshes and short navigation disconnects do not tear down the API because
  the grace timer is generation-cancelled by reconnection.

## 6. Tests and Checks

### Logic rung

- Python compile: **PASS**.
- JavaScript `node --check`: **PASS**.
- PowerShell parser, visible and hidden launchers: **PASS**.
- Relevant `git diff --check`: **PASS**.
- Focused tests using a workspace-owned temp base: **111 passed**.
- Broader explicit operator API/launcher/UI/visibility set: **279 passed**.
- Full repository suite: **1820 passed, 14 skipped, 0 failed** in 269.69s.

The first focused run produced `78 passed, 33 errors` because Windows denied the
default pytest temp directory before 33 tests reached their bodies. A retry
using `C:\tmp` produced the same environmental access denial. The run was then
repeated against a workspace-owned temp base and passed. One intervening broader
command used a malformed wildcard and collected zero tests; it was rejected and
replaced by an explicit file list. None of those failed attempts is counted as
a pass.

### Relabel log

- `test_operator_run_visibility_endpoint_and_page_are_read_only` became
  `test_operator_run_visibility_endpoint_prefers_idle_supervisor_over_orphan_running_artifacts`.
  Its assertion intent changed from treating a historical `RUNNING` artifact as
  current truth to requiring the current `IDLE` supervisor to own vitality while
  retaining the artifact note. This is an authority correction, not a guard or
  threshold weakening.

No other assertion-intent flip occurred.

## 7. Browser, Runtime, and Broker-Read-Only Proof

### Isolated runtime/browser proof

The exact committed application was started on isolated port `8766` with an
isolated workspace state directory and idle-exit enabled.

- A real cockpit EventSource client was observed by the backend.
- Closing that exact browser tab caused the idle backend to exit in 10.254s.
- Final desktop proof at 1440x1000: `BOT IDLE`, `MKT NO_RUNTIME`, both pulse
  values false, `innerWidth=scrollWidth=1440`.
- Final mobile proof at 390x844: the same vitality truth, both pulses false,
  `innerWidth=scrollWidth=390`.
- Closing the final proof browser caused backend exit in 9.64s.

The in-app browser bootstrap failed with `missing field sandboxPolicy`; no
in-app-browser claim is made. Edge/CDP was used as the recorded fallback. A
first CDP retry collided with an existing debug port and displayed an old 8765
tab; it was rejected as evidence and the existing session was not touched. The
proof was repeated on unused port 9333. A first cleanup filter matched its own
helper PowerShell command; that helper ended, but no operator backend or trading
runtime matched or was terminated. Exact test PIDs were then used. Test ports
8766/9333 had no listeners and temporary proof directories were removed.

### Current launcher/runtime proof

The updated interactive launcher replaced verified-idle backend PID `17708`
with PID `20824` and loaded commit `3e71c55`. The current launcher status then
reported supervisor `IDLE`, no active run, idle exit enabled, and attached
cockpit clients. A verification poll initially watched the obsolete
`loaded_git_commit_short` field and therefore timed out; the canonical
`loaded_commit` field already contained `3e71c55`. That command error was not
treated as a failed deployment.

Current live local truth after the Board-authorized Alpaca PAPER GET-only
preflight:

- `final_launch_readiness=READY_FOR_BOUNDED_PAPER`
- `paper_start_allowed=true`; `paper_stop_allowed=false` because no run exists
- expected/actual account suffix: `045ded` / `045ded`
- account status: `ACTIVE`
- portfolio truth: `BROKER_CONFIRMED`
- positions: 4 (`AVAXUSD`, `ETHUSD`, `LINKUSD`, `SOLUSD`)
- open orders: 0
- visibility: `IDLE`; BOT `IDLE`; MKT `NO_RUNTIME`; pulse false
- broker read occurred: true
- broker mutation/order/cancel/replace/close/liquidation: all false
- PAPER Start occurred: false; live and real-money endpoints untouched

This climbs tests, runtime, browser, and the explicitly authorized PAPER
broker-read-only rung. It does not claim a PAPER-run rung.

## 8. Self Red-Team and Anti-Hallucination Check

- **Actually inspected:** current API payloads, supervisor/runtime attachment,
  launcher ownership, event-stream wiring, exact process IDs, code diff, tests,
  desktop/mobile DOM metrics, and authorized PAPER account/positions/open-order
  GET results.
- **Tests prove:** idle disconnect exit, multiple-client protection, reconnect
  cancellation, active/uncertain refusal, Start/shutdown serialization, frozen
  idle pulses, and zero mutation flags.
- **Runtime proves:** real SSE disconnect closes an idle process after grace and
  the current launcher loaded `3e71c55` on a new PID.
- **Browser proves:** rendered current vitality and responsive no-overflow state
  on desktop/mobile against the same implementation.
- **Broker-read-only proves:** suffix, account status, four positions, zero open
  orders, and broker-confirmed portfolio state without mutation.
- **Inference:** browser/OS crashes that close TCP should produce the same SSE
  disconnect; graceful timing under every crash mode is not claimed.
- **Unknown:** the OS scheduler can add delay beyond the eight-second grace;
  no exact universal shutdown maximum is claimed.
- **Not run:** no real PAPER run, no Start click, no order path, no live read,
  and no live/real-money action.
- No failure was summarized away; the temp-directory errors, malformed command,
  browser-tool failure, CDP collision, cleanup-helper overmatch, and post-deploy
  field-name mistake are recorded above.

## 9. Safety Confirmation

- No Risk, NetEdge, sizing, TTL, strategy, masking, OMS, execution, or broker
  threshold changed.
- No manual buy/sell, force-exit, flatten, close-all, cancel-all, liquidation,
  or broker cleanup control was added.
- Automatic shutdown is process-only, emits zero broker mutation, and is
  admitted only while the supervisor is `IDLE`.
- Closing the browser cannot stop an active or uncertain PAPER run. Its
  governed automated position lifecycle remains authoritative.
- Existing protected positions remained intact through validation.
- No live mode, real money, live endpoint, secret exposure, PAPER Start, or
  SovereignExecutionGuard activation occurred.

## 10. Module Status

- `OperatorPaperSupervisor`: **WIRED, lifecycle authority unchanged**.
- `OperatorSnapshotProvider` event lifecycle: **WIRED, connection evidence and
  idle-only request contributor**.
- Visible desktop launcher: **WIRED, current operator entry point**.
- Hidden PowerShell launcher: **WIRED legacy entry, same idle-only guard**.
- Cockpit vitality renderer: **WIRED to current supervisor/runtime truth**.
- Historical runtime artifacts: **PRESERVED read-only evidence; blocked from
  overriding current attachment truth**.
- Browser unload hooks: **intentionally not added** because they are not a
  reliable lifecycle owner.

## 11. Disagreements / What I Would Do Differently

The literal request to kill every backend process whenever the browser closes
would make browser chrome an authority over an active trading lifecycle. I did
not implement that unsafe interpretation. Closing the last cockpit stops an
idle backend; an active or uncertain PAPER runtime is preserved until governed
Stop handles it. A new launcher likewise replaces only a verified idle stale
backend. This safety disagreement is surfaced to Shan rather than hidden.

## 12. Limitations and Unknowns

- Shutdown is not instantaneous: configured grace is 8s; measured isolated
  end-to-end exits were 9.64s and 10.254s.
- If another cockpit tab remains open, the backend correctly remains alive.
- A hard OS/power failure cannot execute graceful cleanup; the next launcher
  still detects and replaces a surviving orphaned idle backend.
- The user's existing Chrome tabs were not forcibly closed. Current live API
  truth was verified; visual close behavior was proved in isolated Edge/CDP.
- Current process-scoped broker verification will reset on the next backend
  restart and must be re-established through the governed GET-only action.
- The full suite retains 14 documented skips and warnings; it has zero failures.

## 13. Exact Staging Recommendation

Code commit `3e71c55` staged exactly these nine files:

1. `app/api/operator_readonly_api.py`
2. `docs/runbooks/operator_local_launch.md`
3. `scripts/open_operator_console.ps1`
4. `scripts/open_operator_console_hidden.ps1`
5. `tests/test_operator_desktop_launcher.py`
6. `tests/test_operator_readonly_api.py`
7. `tests/test_operator_ui_wiring.py`
8. `tests/test_run_visibility.py`
9. `ui/operator-control-panel/app.js`

The evidence commit should stage exactly:

1. `reports/completion/OPERATOR_PROCESS_LIFECYCLE_RECOVERY_REPORT.md`
2. `CHECKPOINT_TRACKER.md`
3. `reports/codex_handoff_latest.md`

Never stage protected `state/*`, `.pytest_tmp/`, screenshots, logs, secrets,
old handoffs, UI proposal packets, operator-performance output, or untracked
audit helpers.

## Research Applied

- MDN `Navigator.sendBeacon()` and Chrome Page Lifecycle guidance were used to
  reject `unload`/`beforeunload` as guaranteed shutdown signals:
  https://developer.mozilla.org/en-US/docs/Web/API/Navigator/sendBeacon and
  https://developer.chrome.com/docs/web-platform/page-lifecycle-api
- Microsoft `Stop-Process` guidance informed verified-PID targeting instead of
  broad process-name termination:
  https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.management/stop-process
- Applied: persistent-connection ownership, reconnect grace, server-side
  admission, scoped PID fallback, and visible lifecycle diagnostics.
- Rejected: browser unload as authority, broad `taskkill`/process-name kills,
  immediate teardown on transient refresh, and any browser-triggered active-run
  stop.
