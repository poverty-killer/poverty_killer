# Phase F UI Cockpit Understandable Report

Date: 2026-07-10
Branch: master
Latest commit at Phase F open: `d8f5bfa pin alpaca paper account identity`
Active packet: Phase F UI cockpit after D4-ACCOUNT-PIN clearance.

## Gate Verdict

| Gate | Status | Proof rung | Evidence |
| --- | --- | --- | --- |
| F0 - Boot, scout, red-team, research complete | PASS | repo inspection plus research synthesis | `AGENTS.md` v3 reread confirmed; tracker/handoff/current status inspected; UI/API/tests scoped before edits; research patterns applied to cockpit hierarchy and diagnostics. |
| F1 - Operator can see whether PAPER can run and why not | PASS | focused UI tests plus browser runtime proof | Run PAPER Command Center now shows the canonical backend blocker and exact account-pin failure text instead of a fake-green state. |
| F2 - Run-PAPER button matches backend readiness truth | PASS | focused tests plus browser runtime proof | Start is disabled when backend truth is not `READY_FOR_BOUNDED_PAPER` with a proven account pin; UI no longer trusts raw `paper_start_allowed` without the pin assertion. |
| F3 - D4 account-pin truth is visible in the cockpit | PASS | focused UI/API tests plus browser runtime proof | UI normalizes and displays `paper_account_pinned`, expected suffix, actual suffix, and reason code; local validation shows expected `045ded` and unproven actual suffix when D4 read is not armed. |
| F4 - No stale mock/backend contradiction | PASS | focused UI tests | Backend-connected Run PAPER state derives from `OPERATOR_PAPER_CONTROL_STATE`; mock/offline authority cannot override backend launch truth. |
| F5 - Desktop and mobile layouts have no horizontal overflow | PASS | headless browser CDP proof | Desktop `scrollWidth=1440/clientWidth=1440`; mobile `scrollWidth=390/clientWidth=390`. |
| F6 - Advanced diagnostics are available without becoming the primary UI | PASS | UI source and browser inspection | Account pin fields are in primary proof tiles and advanced rows; advanced technical rows remain behind detail sections. |
| F7 - No unsafe UI controls, raw secrets, or broker mutation | PASS | focused tests plus runtime constraints | No PAPER run, live endpoint, real-money path, broker mutation, or secret display occurred. |

## 1. Verdict

Phase F is closed for the authorized UI cockpit seam.

The operator cockpit now presents the D4 account-pin requirement as a first-class PAPER readiness proof. A PAPER start can no longer look runnable in the frontend unless the backend has both the single canonical `READY_FOR_BOUNDED_PAPER` state and a proven pinned PAPER account identity. When the pin is missing or unproven, the Run PAPER button remains disabled and the operator sees the exact blocker.

Current local browser proof is intentionally fail-closed: `ALPACA_PAPER_ACCOUNT_PIN_NOT_PROVEN`. D4 broker read was not re-armed during Phase F browser validation, so the UI correctly shows expected suffix `045ded`, actual suffix `unknown`, and Start disabled. This is not a Phase F failure; it is the truthful state without broker-read authorization.

No PAPER run, broker mutation, live mode, real-money mode, threshold change, secret exposure, state staging, or broad cleanup occurred.

## 2. Files Changed

Runtime UI:

- `ui/operator-control-panel/app.js`

Tests:

- `tests/test_operator_ui_wiring.py`
- `tests/test_operator_readonly_api.py`

Reports/tracker:

- `reports/completion/PHASE_F_REPORT.md`
- `CHECKPOINT_TRACKER.md`
- `reports/codex_handoff_latest.md`

## 3. Root Cause

The D4 account-pin backend work created account identity truth, but the cockpit did not yet treat that proof as a primary PAPER readiness requirement. The UI could normalize launch/control state and display Run PAPER readiness without showing whether the broker-reported account identity matched the canonical `045ded` pin.

That made two bad operator outcomes possible:

- The account-pin blocker could remain hidden inside backend details instead of appearing as the visible reason PAPER cannot start.
- The frontend could derive button state from raw backend start booleans and readiness labels without independently preserving the account-pin proof in the displayed command-center state.

Adjacent UI root cause: `showScreen()` changed `activeScreenId` but did not refresh the top bar, so the Controls screen could still display the Overview heading.

## 4. Fixes Implemented

Added `normalizePaperAccountPin()` and `paperAccountPinFromState()` to make account-pin display a structured frontend contract rather than scattered field checks.

Preserved backend account-pin fields through UI normalization:

- `paper_account_identity_assertion`
- `paper_account_pinned`
- `paper_account_expected_suffix`
- `paper_account_actual_suffix`
- `paper_account_reason_code`

Updated Run PAPER state derivation so `allowed` is true only when:

- backend `paperStartAllowed === true`
- final launch readiness is exactly `READY_FOR_BOUNDED_PAPER`
- account pin proof is `pinned === true`

If account pin proof is required but not proven, the Run PAPER state adds `ALPACA_PAPER_ACCOUNT_PIN_NOT_PROVEN`, disables Start, and shows the backend account-pin detail.

Added a primary proof tile in the Run PAPER Command Center:

- title: `Pinned PAPER account`
- expected suffix
- actual suffix
- detail/reason
- green/pass only when the pin is proven

Added account-pin rows to advanced launch diagnostics:

- `paper_account_pinned`
- `paper_account_expected_suffix`
- `paper_account_actual_suffix`
- `paper_account_reason_code`

Updated Home Launch Readiness to include pinned account status and corrected safe lock colors so `Live endpoint blocked`, `Live LOCKED`, and `Real money BLOCKED` render as safe/green instead of danger/red.

Fixed top-bar synchronization by re-rendering the top bar inside `showScreen()` after `activeScreenId` changes.

## 5. 360 Adjacent Improvements

The UI now treats account identity as part of the same operator decision surface as credentials, endpoint, runtime, portfolio truth, and safety locks.

The command center no longer allows a stale backend-connected display path to keep a green Start decision when account-pin proof is absent.

Safe negative states are visually distinct from dangerous negative states:

- live endpoint blocked is safe
- live mode locked is safe
- real money blocked is safe
- account pin missing/mismatched is a blocker

The active-screen top bar now matches the selected cockpit section, reducing operator confusion during Controls and Settings review.

Adjacent issue found but deferred: `/operator/action-center` and `/operator/alerts` were slow enough during local runtime validation to create one degraded endpoint check. The cockpit handled this truthfully and still rendered fail-closed, but endpoint latency should be handled in a later ops/performance seam rather than absorbed into Phase F.

## 6. Tests / Checks

Passed:

```powershell
node --check ui\operator-control-panel\app.js
```

Passed:

```powershell
python -m pytest tests\test_operator_ui_wiring.py tests\test_operator_readonly_api.py -q --basetemp .pytest_tmp\phase_f_ui_api3
```

Result:

```text
71 passed in 21.80s
```

Earlier backend syntax check also passed before the final JS-only top-bar fix:

```powershell
python -m py_compile app\api\operator_readonly_api.py app\operator_activation\launch_readiness.py
```

Focused assertions now prove:

- cockpit contains `Pinned PAPER account`
- frontend preserves `paperAccountPin`
- account pin fields flow from backend payload into UI state
- `ALPACA_PAPER_ACCOUNT_PIN_NOT_PROVEN` is visible as a blocker
- Run PAPER start requires `READY_FOR_BOUNDED_PAPER` plus `accountPinPassed`
- backend API test fixture exposes a pinned `045ded` account when the backend assertion is PASS
- screen switching re-renders the top bar

## 7. Browser / Runtime Validation

The in-app browser connector could not be used because the node-backed browser tool failed with:

```text
codex/sandbox-state-meta: missing field sandboxPolicy
```

Fallback validation used local `uvicorn` plus Chrome DevTools Protocol against the operator UI. No PAPER run, live endpoint, broker mutation, order placement, cancel, liquidation, or state staging occurred.

Runtime server:

```powershell
python -m uvicorn app.api.operator_readonly_api:create_operator_app --factory --host 127.0.0.1 --port 8765
```

Observed backend/UI state:

```text
paper_control_source: OPERATOR_PAPER_CONTROL_STATE
paper_start_allowed: false
dominant_blocker: ALPACA_PAPER_ACCOUNT_PIN_NOT_PROVEN
paper_account_pinned: false
paper_account_expected_suffix: 045ded
paper_account_actual_suffix: null
```

Desktop proof:

```text
screenshot: C:\tmp\poverty_killer_phase_f_browser\desktop-controls-cdp.png
topbar: Controls & Settings / Server-gated PAPER controls and future modes
screen: controls
hasPinnedBanner: true
hasPinnedTile: true
scrollWidth: 1440
clientWidth: 1440
bodyScrollWidth: 1440
innerWidth: 1440
startDisabled: true
blocker: Expected Alpaca PAPER account suffix 045ded, but read-only broker account identity is not authorized/proven.
```

Mobile proof:

```text
screenshot: C:\tmp\poverty_killer_phase_f_browser\mobile-controls-cdp.png
topbar: Controls & Settings / Server-gated PAPER controls and future modes
screen: controls
hasPinnedBanner: true
hasPinnedTile: true
scrollWidth: 390
clientWidth: 390
bodyScrollWidth: 390
innerWidth: 390
startDisabled: true
blocker: Expected Alpaca PAPER account suffix 045ded, but read-only broker account identity is not authorized/proven.
```

Screenshots are proof artifacts under `C:\tmp`; they are not staged.

## 8. Governance / Safety Confirmation

`AGENTS.md` v3 was reread at Phase F boot. Current branch, recent commits, tracker, handoff, relevant UI/API files, and tests were inspected before editing.

Sacred safety laws preserved:

- no live trading mode
- no real-money enablement
- no manual buy/sell controls
- no force-trade controls
- no hidden broker mutation
- no broker mutation in tests
- no fake broker truth
- no fake orders/fills/fees/TCA/P&L
- no threshold, risk, economic, sizing, TTL, or strategy weakening
- conflicts fail closed
- no raw secrets displayed, logged, tested, or reported

Authority confirmation:

- Backend readiness remains the authority for PAPER start truth.
- UI display remains a display/diagnostic authority only.
- Account identity authority remains the D4/D4-pin backend contract; the UI only normalizes, displays, and refuses to show a green start without that proof.
- No duplicate broker, risk, sizing, AI, or UI final-decision authority was introduced.

## 9. Limitations / Known Follow-Up

Phase F did not re-arm D4 broker read. The browser proof therefore shows account pin as not proven, which is the expected fail-closed display when broker identity proof is unavailable.

The local browser proof saw one degraded backend check caused by slow optional endpoints (`/operator/action-center` and `/operator/alerts`). This is a follow-up performance/observability issue, not a reason to fake readiness.

Phase F did not redesign the entire cockpit. It completed the approved safety-critical UI truth seam: PAPER command center, account pin visibility, button truth, top-bar sync, and responsive proof.

No Phase G PAPER run has been performed. PAPER remains Board-gated.

## 10. Staging Recommendation

Stage exactly:

```powershell
git add -- ui/operator-control-panel/app.js
git add -- tests/test_operator_ui_wiring.py
git add -- tests/test_operator_readonly_api.py
git add -- reports/completion/PHASE_F_REPORT.md
git add -- CHECKPOINT_TRACKER.md
git add -- reports/codex_handoff_latest.md
```

Do not stage:

- `state/*`
- `.pytest_tmp/`
- `AGENTS.prev.md`
- `POVERTY_KILLER_AUDIT_REPORT.txt`
- old untracked `reports/codex_handoff_*`
- `reports/operator_perf/`
- untracked audit scripts under `scripts/`
- screenshots
- secrets
- logs
- DB/runtime files

## Research Used

Comparable systems/patterns reviewed:

- Bach et al., dashboard design patterns: https://arxiv.org/abs/2205.00757
- Setlur et al., actionable dashboard heuristics: https://arxiv.org/abs/2308.04514
- ActionNex outage/incident manager patterns: https://arxiv.org/abs/2604.03512

Lessons applied:

- A cockpit should be a curated operator lens, not a raw mirror of every backend field.
- The top of the UI should answer status, exact blocker, source, and next safe action before diagnostics.
- Advanced details should be available but not dominate the primary control surface.
- Incident-style UIs must expose the current blocking condition and partial-observability state without implying readiness.

Lessons rejected:

- No proprietary trading-terminal layout or protected design was copied.
- No decorative redesign was absorbed into the safety seam.
- No visual polish was used to hide missing broker-read proof.

Impact on our bot:

- The Run PAPER command area now behaves like a safety cockpit: exact blocker first, proof tiles second, diagnostics behind details, and the start button disabled unless backend truth is fully green.
