# POVERTY_KILLER Completion Checkpoint Tracker

Updated: 2026-07-18
Branch: master

## Checkpoint Summary

| Checkpoint | Status | Evidence |
| --- | --- | --- |
| A - Repo Validation Clean | COLLECTION/SYNTAX PROVEN; NOT A FULL-SUITE PASS | `reports/completion/PHASE_A_REPORT.md`; full-suite red baseline recorded at G-CLOSE |
| B - Module Truth Map Complete | PASS | `reports/completion/PHASE_B_MODULE_TRUTH_MAP.md`; Phase C-corrected 397 countable modules plus 2 excluded generated cache artifacts |
| C - Authority Graph Implemented | PASS | `reports/completion/PHASE_C_AUTHORITY_GRAPH_REPORT.md`; 7 owners named in code; 9 Phase B conflicts resolved as owner/contributor/reference boundaries |
| D - PAPER Readiness Truthful | PASS | `reports/completion/PHASE_D_REPORT.md`; D0-D7 PASS after D4 Board-armed read-only Alpaca PAPER baseline |
| E - AI Chief Useful | PASS | `reports/completion/PHASE_E_REPORT.md`; AI route truth and evidence contract are live; canonical blockers come from D6 readiness |
| F - UI Cockpit Understandable | PASS | `reports/completion/PHASE_F_REPORT.md`; Run PAPER cockpit shows D4 account-pin truth, disables Start without proven pin, and passed desktop/mobile browser proof |
| G - Bounded PAPER Run Ready | PASS | `reports/completion/PHASE_G_REPORT.md`; readiness proven with broker-read-only + browser proof; actual PAPER run still requires explicit Board approval |
| H - Live-Readiness Shadow Mode | NOT_STARTED | Live credentials read-only requires Board approval |
| I - Tiny Live Canary | NOT_STARTED | Individually Board-approved only |

## Phase A Result

Phase A proved its structural collection/import gate on 2026-07-09. It did not
run or prove a repository-wide behavioral suite, so it must not be cited as a
full-suite pass. The later G-CLOSE baseline recorded `1762 passed, 49 failed, 6
skipped`.

- A1 PROVEN - root and intended collection clean.
- A2 PROVEN - py_compile clean across scoped tree.
- A3 PROVEN - app/core import smoke clean.
- A4 PROVEN - `_repo_quarantine` excluded from intended pytest collection.

## Phase B Result

Phase B module truth map passed on 2026-07-09:

- B1 PASS - 397 countable code/operator modules classified after Phase C correction; 2 generated `__pycache__` artifacts excluded.
- B2 PASS - zero silent modules in the Phase B inventory.
- B3 PASS - seven authority owners named and 9 duplicate/conflict seams logged for Phase C.
- Phase C corrected classification counts: WIRED 297; BLOCKED 89; PRESERVED-DEAD 10; REJECTED-PRESERVED 1; 2 generated `__pycache__` artifacts excluded.
- Truth map: `reports/completion/PHASE_B_MODULE_TRUTH_MAP.md`.
- Report: `reports/completion/PHASE_B_REPORT.md`.

## Phase C Result

Phase C authority graph passed on 2026-07-09:

- C1 PASS - seven authorities have exactly one named owner in `app/core/authority_graph.py`.
- C2 PASS - every Phase B contender is wired as a labeled contributor or blocked/reference-only with a named reason.
- C3 PASS - duplicate-authority tests prove unique owners, contributor non-override, and all 9 Phase B conflicts covered.
- C4 PASS - false BLOCKED rows corrected and counts reported in the truth map/report.
- Validation: `python -m pytest tests/test_authority_graph.py -q --basetemp .pytest_tmp\phase_c` passed; root `pytest --collect-only -q --basetemp .pytest_tmp\phase_c_collect` collected 1783 tests with zero collection errors.

## Phase D Result

Phase D completed on 2026-07-10 under the Board convergence packet, D1-FIX packet, and D4 armed read-only broker inspection packet.

- D0 PASS - focused tests prove no active runtime broker submit path bypasses `OrderRouter`; rejected orchestrator is not imported by active runtime; lower-layer `PaperBroker` and `AlpacaPaperBrokerAdapter` public methods remain preserved.
- D1 PASS - `StaleDataGuard` is wired as a blocking evidence contributor under `evaluate_pre_trade_guardrails`; stale market data is rejected. `SovereignExecutionGuard` is classified mutation-capable and remains `DORMANT_BY_POLICY_PENDING_PHASE_HI_ARM`.
- D2 PASS - Alpaca PAPER execution credentials resolve only from `~/.poverty_killer_alpaca_paper_env` / `POVERTY_KILLER_ALPACA_PAPER_ENV_PATH`; `.operator_secrets` and process APCA vars are demoted for PAPER execution truth.
- D3 PASS - Alpaca PAPER endpoint is proven; live endpoint fails closed; real-money remains blocked.
- D4 PASS - Board-authorized read-only Alpaca PAPER inspection retrieved account/open-orders/positions baseline through exactly `GET /v2/account`, `GET /v2/positions`, and `GET /v2/orders?status=open&limit=100&nested=false`; account status `ACTIVE`, 4 broker-confirmed positions, 0 open orders, required Alpaca PAPER credential fields resolved from `CANONICAL_PAPER_ENV_FILE`, no mutation/live/real-money flags.
- D5 PASS - portfolio endpoint renders broker-confirmed truth when D4 is armed and exact `BROKER_READ_NOT_AUTHORIZED` failure when unarmed; no fabricated broker truth.
- D6 PASS - backend/UI green-light is exactly `READY_FOR_BOUNDED_PAPER`; deprecated `DEGRADED_BUT_RUNNABLE` and `READY_FOR_GOVERNED_PAPER` are removed from runtime contracts.
- D7 PASS - final reconciliation contract is explicit with owner `OrderRouter.finalize_oms_shutdown_reconciliation`.
- Validation: focused Phase D and adjacent suite passed: 206 tests, 72 existing warnings. `node --check` and `py_compile` passed. D4 reached broker-read-only proof rung with sanitized output and no mutation.

## Phase E Result

Phase E completed on 2026-07-10 under the Board-authorized AI Chief Useful packet.

- E1 PASS - `/operator/ai/status` exposes `AIProviderGateway` as route-truth owner plus active provider, active model, response mode, fallback state, and advisory-only/no-mutation flags.
- E2 PASS - `/operator/ai/ask` returns `evidence_bound=true`, `ai-chief-evidence-contract-v1`, structured evidence packet status, and exact missing-evidence wording instead of thin-air answers.
- E3 PASS - AI current blockers are pulled from canonical D6 launch readiness through `OPERATOR_LAUNCH_READINESS_D6_CONTRACT`; idle/no-active-runtime is not treated as a blocker.
- E4 PASS - ask/provider prompt tests prove AI cannot mutate trading/risk/broker/threshold authority and does not expose secret values.
- Adjacent Phase E safety fix: `paper_control_state` now blocks accepted protected-position baselines with `paper_baseline_position_aware_policy`, matching `launch_readiness` and removing a false-green control-state risk.
- Current canonical PAPER blocker observed in Phase E proof: `paper_baseline_position_aware_policy`.
- Validation: `python -m py_compile app\api\operator_readonly_api.py app\ai_chief_operator\provider_adapters.py` passed; `node --check ui\operator-control-panel\app.js` passed; focused readiness/AI suite passed with 128 tests and 72 existing warnings.

## D4 Account Identity Addendum

D4-ACCOUNT-IDENTITY was completed on 2026-07-10 before Phase F under read-only Board authorization.

- Canonical source `~/.poverty_killer_alpaca_paper_env` resolved to `redacted_suffix:045ded`.
- Canonical account equals funded baseline `045ded`: YES.
- Canonical broker-confirmed values: buying power `3960450.72`; cash `990112.68`; portfolio value `1000325.77`; 4 positions; 0 open orders.
- Second distinct paper account reachable only through demoted local operator vault `alpaca_paper`: `redacted_suffix:104e2a`; cash `-11`; buying power `48.58`; portfolio value `87904.72`; 12 positions; 0 open orders.
- Local stored baseline `state/operator/paper_baseline.json` is accepted/protected for `redacted_suffix:104e2a`; read-only inspection only, not staged.
- `SovereignExecutionGuard` audit thread closed as certified dormant: mutation-capable and `DORMANT_BY_POLICY_PENDING_PHASE_HI_ARM`.
- Blocking finding: code pins credential source to the canonical env file but does not hard-pin target account ID/suffix. Trading account is runtime-inferred from whichever paper account the canonical key resolves to.
- Current blocker before Phase F: `ACCOUNT_TARGET_RUNTIME_INFERRED`. Do not self-fix; Board must confirm target-account pin policy.

## D4 Account Pin Addendum

D4-ACCOUNT-PIN was completed on 2026-07-10 under Board authorization to pin Shan's funded `045ded` Alpaca PAPER account.

- PASS - Account target is no longer runtime-inferred. Canonical expected PAPER account suffix is defined once in `app.operator_credentials.store` as `045ded`.
- PASS - Startup/status readiness and governed PAPER start authority consume the account-pin assertion and fail closed unless broker-reported identity matches the pin.
- PASS - Supervisor start validation forces a fresh account identity proof before the runner spec is built. A simulated drained/reachable account suffix `104e2a` is rejected with `ALPACA_PAPER_ACCOUNT_PIN_MISMATCH`, and no runner launch occurs.
- PASS - Launch readiness and paper control state expose `paper_account_identity_assertion`, expected suffix, actual suffix, and `paper_account_pinned`; `READY_FOR_BOUNDED_PAPER` cannot be true when the account pin is missing or mismatched.
- PASS - Child process env carries `PK_ALPACA_PAPER_EXPECTED_ACCOUNT_SUFFIX=045ded` from the canonical pin source.
- Validation: account-pin/readiness/supervisor/API/AI/portfolio/credential focused suites passed; py_compile passed for touched modules.
- No real broker read, PAPER run, live endpoint, real-money path, order placement, cancel, liquidation, threshold change, or secret exposure occurred in this addendum.
- `ACCOUNT_TARGET_RUNTIME_INFERRED` is CLEARED. Phase F is unblocked and now in progress.

## Phase F Result

Phase F completed on 2026-07-10 under the UI Cockpit Understandable seam after D4-ACCOUNT-PIN cleared the runtime-inference hazard.

- F0 PASS - AGENTS v3, tracker, handoff, relevant UI/API/tests, scout, red-team, and UI research were completed before edits.
- F1 PASS - Run PAPER Command Center now shows the exact current blocker and next safe action instead of a fake-green state.
- F2 PASS - Run PAPER Start is disabled unless backend truth is `READY_FOR_BOUNDED_PAPER` and account pin proof is passed.
- F3 PASS - D4 account-pin truth is visible in the cockpit: expected suffix, actual suffix, pin status, and reason code.
- F4 PASS - backend-connected Run PAPER display cannot be overridden by stale mock/local authority.
- F5 PASS - desktop and mobile browser proof showed no horizontal overflow.
- F6 PASS - advanced diagnostics remain available without replacing the primary operator cockpit.
- F7 PASS - no unsafe controls, raw secrets, broker mutation, PAPER run, live mode, real-money path, or threshold changes occurred.
- Current local browser proof intentionally shows `ALPACA_PAPER_ACCOUNT_PIN_NOT_PROVEN` because D4 broker read was not re-armed in Phase F; the UI fails closed with Start disabled.
- Validation: `node --check ui\operator-control-panel\app.js`; focused UI/API pytest suite passed with 71 tests; local Chrome CDP browser proof captured desktop and mobile controls screens.
- Phase G remains Board-gated because any bounded PAPER run requires explicit authorization.

## Phase G Result

Phase G completed on 2026-07-11 under the Board-authorized Bounded PAPER Run READY packet. D4 read-only Alpaca PAPER inspection was re-armed for account identity, account/open-orders, and positions only.

- G1 PASS - launch readiness proved `READY_FOR_BOUNDED_PAPER` end-to-end under the configured Phase G operator state.
- G2 PASS - endpoint is Alpaca PAPER; live and real-money remain blocked.
- G3 PASS - account pin is enforced on supervisor readiness/start, child runner env, direct PowerShell launcher preflight, and accepted baseline account suffix.
- G4 PASS - drained/stale account suffix `104e2a` is rejected; stale accepted baseline from `104e2a` blocks readiness/control-state with `paper_baseline_account_pin_mismatch`.
- G5 PASS - read-only broker baseline retrieved for `redacted_suffix:045ded`: account `ACTIVE`, 4 positions (`AVAXUSD`, `ETHUSD`, `LINKUSD`, `SOLUSD`), 0 open orders, cash `990112.68`, buying power `3960450.72`, final backend snapshot equity `1000426.67`.
- G6 PASS - desktop and mobile browser proof show pinned account, broker-confirmed portfolio truth, non-flat baseline, Start allowed on green backend, live locked, real-money blocked, and no horizontal overflow.
- G7 PASS - max lease is explicit at `432000` seconds and final reconciliation remains required.
- Important condition: tracked `state/operator/paper_baseline.json` remains stale for `redacted_suffix:104e2a` and was not edited/staged. If default repo state is used, readiness now fails closed. Positive Phase G proof used configured operator state under `C:\tmp\poverty_killer_phase_g_runtime\state\operator` with the broker-confirmed `045ded` protected baseline.
- No PAPER run, broker mutation, live mode, real-money path, order submit, cancel, close, liquidate, flatten, threshold change, secret exposure, or tracked runtime-state edit occurred.
- Commit pushed: `a861142 complete phase G bounded paper readiness`.

## Phase G Close Pre-Arming Seam

PK-G-CLOSE completed its scoped implementation on 2026-07-11. Full evidence is
in `reports/completion/PHASE_G_CLOSE_REPORT.md`.

- G-C1 PASS at the test/process-harness rung: Stop waits for terminal child state, releases the lease, emits no broker mutation, and is visible beside Start. Post-stop broker positions remain explicitly unreconciled until final reconciliation; no PAPER run was authorized.
- G-C2 PASS: production operator state now defaults to `%LOCALAPPDATA%\PovertyKiller\state\operator`; the `045ded` baseline was created through governed acceptance and survived a cold backend boot with `READY_FOR_BOUNDED_PAPER` and Start allowed.
- G-C3 PASS: BOT and MKT vitality are separate; pulse/ECG motion requires fresh heartbeat evidence; killed-process stale proof freezes animation.
- G-C4 PASS: `READY_FOR_GOVERNED_PAPER`, `governed PAPER`, and `DEGRADED_BUT_RUNNABLE` are absent from UI render sources.
- G-C5 PASS: final Edge/CDP desktop 1440 and mobile 390 proof has no horizontal overflow; Start is enabled, Stop is visible/idle-disabled, pin/broker/four-symbol truth is visible, and no `C:\tmp` dependency appears.
- Child account-pin bypass closed in `main.resolve_execution_broker_gateway()` through `AlpacaPaperBrokerAdapter.assert_expected_account_pin()` before adapter return/order #1.
- Four-symbol protected-baseline refusal is now tested for AVAX, ETH, LINK, and SOL.
- Scoped gate: 240 tests passed. Current full suite: 1762 passed, 49 failed, 6 skipped; clean `e8ef247` baseline: 1749 passed, 54 failed, 6 skipped. All 49 current failures pre-exist in the clean-HEAD set and are logged in the close report.
- No PAPER run, live mode, real money, broker mutation, threshold change, secret exposure, tracked runtime-state edit, or SovereignExecutionGuard activation occurred.
- Exact 27-file seam commit pushed: `289d047 close phase G pre-arming controls`.

## Run-Path Green Pre-Arming Disposition

Completed on 2026-07-12. Full evidence is in
`reports/completion/PHASE_RUNPATH_GREEN_REPORT.md`.

- Reported G-CLOSE baseline: `1762 passed, 49 failed, 6 skipped`.
- The 49 were dispositioned by cluster: 33 stale run-path fixtures; 3 real-broker GET tests missing an explicit Board-read gate; 9 stale GammaFront diagnostic tests; 4 stale/optional off-path contract tests.
- Run-path binary exit gate: PASS, `119 passed`, covering decision-frame orchestration, deterministic E2E, integrated readiness, risk-gate ordering, replay parity, dispatch admission, and upstream dispatch.
- Final full suite: PASS with documented deferrals, `1803 passed, 14 skipped, 0 failed`. Seven real-broker/access tests now skip before credentials/network unless `PK_BOARD_AUTHORIZED_PAPER_BROKER_READ=YES_D4_BOARD_AUTHORIZED`; the historical 26G machine also retains its separate mutation approval.
- GammaFront classification: `WIRED_EXIT_ONLY / ENTRY_FEED_DORMANT`; production strategy logic remains unchanged.
- Refusal tests now require an immutable no-submit DecisionRecord plus zero execution submission instead of expecting the audit compiler to remain unreachable.
- No production source, guard, threshold, risk, NetEdge, TTL, sizing, masking, OMS, broker-governor, or strategy logic changed.
- No PAPER run, live mode, real-money path, broker mutation, secret exposure, or tracked runtime-state edit occurred.

## Launcher / App Icon Upgrade

Completed on 2026-07-12 as a reversible post-G operator UX seam. Full evidence
is in `reports/completion/LAUNCHER_APP_ICON_UPGRADE_REPORT.md`.

- PASS - the generic `shell32.dll,220` launcher glyph was replaced by one
  tracked product identity in editable SVG and exact multi-resolution Windows
  ICO formats.
- PASS - `Ensure-OperatorShortcut` remains the sole shortcut owner, applies the
  icon, and updates an existing Windows/OneDrive Desktop shortcut without
  creating a second launcher identity.
- PASS - the existing OneDrive Desktop shortcut target and arguments were
  verified unchanged after its icon metadata update.
- PASS - the operator cockpit uses the same identity for its favicon; the live
  local server returned HTTP 200 for both SVG and ICO assets.
- Validation: 22 focused launcher tests passed; 97 launcher/UI/API tests passed;
  PowerShell syntax passed; exact 16 through 256 pixel rendered frames were
  visually inspected on light and dark backgrounds.
- Browser automation was unavailable, so no browser-tab screenshot claim is
  made. No PAPER run, broker read/mutation, live mode, real money, threshold,
  guard, strategy, OMS, readiness, or tracked runtime-state change occurred.

## Operator Usability Recovery

Completed on 2026-07-15 after Shan reported that the opened cockpit did not
allow useful interaction and approved the scoped repairs with `proceed`. Full
evidence is in
`reports/completion/OPERATOR_USABILITY_RECOVERY_REPORT.md`.

- PASS - the cockpit now exposes an explicit, process-scoped Alpaca PAPER
  GET-only verification action. It cannot submit, cancel, replace, close, or
  liquidate an order and it resets on backend restart.
- PASS - Start remains fail-closed until current broker proof passes and forces
  a fresh account/positions/open-orders preflight immediately before fake or
  real child launch.
- PASS - the live Controls crash was root-caused to undefined renderer
  variables. The renderer is fixed and now executed by a Node regression test.
- PASS - SSE is primary; polling is only a fallback; unchanged server state uses
  keepalives; background lifecycle updates do not remount active operator input.
- PASS - credential setup, external broker verification, and Start admission
  are labeled as separate proofs. AI gateway default, selected route, and last
  actual answer route are also separate.
- Final full suite: `1815 passed, 14 skipped, 384 warnings, 0 failed`.
- Runtime/browser proof: durable LocalAppData cold boot; Controls navigation
  works; focus stable for 20 seconds; no requests in that stable window; desktop
  1440 and mobile 390 have no horizontal overflow; truthful BOT/MKT vitality.
- Board-authorized read-only PAPER proof: suffix `045ded`, account `ACTIVE`, 4
  positions (`AVAXUSD`, `ETHUSD`, `LINKUSD`, `SOLUSD`), 0 open orders,
  `BROKER_CONFIRMED`, `READY_FOR_BOUNDED_PAPER`, Start enabled while idle.
- Exact total GET count is not instrumented and is recorded as unknown. No
  PAPER run, Start click, broker mutation, live/real-money path, manual trade,
  threshold change, or tracked runtime-state edit occurred.

## PAPER Start Interaction Recovery

Completed on 2026-07-15 after Shan selected four hours and pressed the bounded
PAPER Start control, but observed no result. Full evidence is in
`reports/completion/PAPER_START_INTERACTION_RECOVERY_REPORT.md`.

- Root cause boundary proved: the backend remained `IDLE`, runtime was
  unattached, latest session/PID/refusal were absent, and the durable journal
  contained no Start event. The original click never reached the Start endpoint.
- Four hours was not blocked: `14400` is in the existing server duration set and
  a fresh-preflight fake-runner test proves that exact duration reaches the
  existing runner unchanged.
- UI defect fixed: backend-green state no longer makes the command look
  actionable while its four operator confirmations are incomplete.
- Start is now a visible two-step command: `Review & Start` shows exact profile,
  duration, watchlist, and authority with `Start not sent`; `Confirm & Start`
  sends the reviewed payload only if nothing changed.
- Pending, accepted, refused, cancelled, invalidated, and response-unknown states
  are visible in an `aria-live=polite` status surface. Lost responses prohibit a
  blind retry until runtime state is understood.
- Browser proof with Start interception: 0/4 disabled with exact missing list;
  4/4 review showed `4 hours (14400s)`; exactly one test-only intercepted payload
  preserved `duration_seconds=14400`; desktop/mobile overflow false; zero browser
  exceptions or console errors. The real backend remained idle.
- Final integrated operator gate: `178 passed, 72 warnings`.
- Final full suite: `1816 passed, 14 skipped, 384 warnings, 0 failed`.
- No real PAPER run was started during recovery/validation. No broker mutation,
  live/real-money path, order, cancel, close, liquidation, threshold change, or
  tracked runtime-state edit occurred.

## Operator Process Lifecycle Recovery

Completed on 2026-07-15 after Shan showed `NO_ACTIVE_PAPER_RUN` together with
`BOT STALE` and requested fresh launcher/backend ownership. Full evidence is in
`reports/completion/OPERATOR_PROCESS_LIFECYCLE_RECOVERY_REPORT.md`.

- Root cause: the backend was current and supervisor-idle, not stale; a
  historical heartbeat artifact was incorrectly overriding current vitality.
- PASS - idle cockpit truth is now `BOT IDLE` / `MKT NO_RUNTIME`; both vitality
  animations are frozen and the historical artifact remains disclosed.
- PASS - closing the last cockpit event stream starts an eight-second grace and
  exits only an idle operator API through the existing stack-shutdown owner.
- PASS - reconnects/multiple tabs cancel or defer exit; active or uncertain
  PAPER runtimes are refused automatic shutdown and remain under governed Stop.
- PASS - a new launcher replaces an orphaned, lifecycle-old, or code-stale idle
  backend and preserves any active/uncertain runtime.
- Validation: 111 focused tests passed; 279 broader operator tests passed; full
  suite `1820 passed, 14 skipped, 0 failed`; Python/JavaScript/PowerShell syntax
  passed.
- Browser/runtime proof: desktop 1440 and mobile 390 rendered BOT IDLE / MKT
  NO_RUNTIME with frozen pulses and no overflow; last-tab closure stopped two
  isolated idle backends in 10.254s and 9.64s.
- Deployment stages: code commit `3e71c55` loaded on verified-idle PID `20824`;
  after evidence commit `9cf1e25`, guarded refresh loaded that then-current HEAD
  on PID `4072` with supervisor `IDLE`, lifecycle enabled, and cockpit clients
  attached. Final session close must re-prove `loaded_commit == repo_head` after
  the last documentation commit rather than predict its self-referential hash.
- Board-authorized PAPER GET-only proof: `READY_FOR_BOUNDED_PAPER`, Start
  allowed, suffix `045ded`, `BROKER_CONFIRMED`, 4 protected positions, zero open
  orders, and zero broker mutation.
- No PAPER run, Start click, order, cancel, close, liquidation, live/real-money
  action, threshold change, or protected state staging occurred.
- Safety ruling surfaced: browser closure never kills an active or uncertain
  runtime; browser chrome is not a trading-lifecycle authority.

## PAPER True Capability Planning

Deep-dive planning completed on 2026-07-17 after Shan requested a staged program
to remove commissioning restrictions, broaden PAPER trading, and permit lawful
automated management of broker-backed holdings. Full evidence, independent
red-team, and adjusted plan are in
`reports/completion/PAPER_TRUE_CAPABILITY_MASTER_PLAN.md`.

- **PLAN ONLY / IMPLEMENTATION NOT STARTED** - no source, test, configuration,
  runtime state, broker state, or trading authority changed.
- Repo inspection found causal and authority prerequisites that must precede
  wider trading: cross-symbol fusion state, future-evidence acceptance,
  incomplete broker-book hydration, pre-fill strategy state, a declared-but-
  rejected Alpaca SELL contract, non-scalable poll-all data access, inferred
  module attribution, and placeholder/illustrative portfolio economics.
- The adjusted plan has Stages 0-11 for offline implementation and adversarial
  certification. Board approval is pending; execution begins with Stages 0 and
  1 only and advances only through binary exit gates.
- Stage 12 broker-read-only validation remains a separate Board approval. Stage
  13 contains progressively bounded PAPER runs, each separately Board-approved.
- "Open trading" is defined as a broker-discovered PAPER universe plus the
  bot's governed, broker-position-backed automated lifecycle. It does not mean
  live mode, real money, manual trade controls, shorting, naked SELL, or weaker
  Risk/NetEdge/TTL/sizing/OMS/reconciliation controls.
- No phase transition, PAPER run, broker call, threshold change, or live action
  was authorized by creation of this plan.
- Board addendum 2026-07-18: `AGENTS.md` Section 23 now binds every Stage 0-13
  to a written pre-code stage-entry manifest, restriction-classification burden
  of proof, unchanged-control fingerprints, non-degradation covenant, and
  closing anti-hallucination audit. The covenant forbids deletion, dumbing down,
  code/math simplification, threshold or limit loosening, trade-count targets,
  fake proof, and silent module loss. Only restrictions proven to be
  commissioning/test scaffolds may be replaced by the complete production
  authority; affected `UNKNOWN` remains fail-closed. A scaffold whose full proof
  burden passes must leave the active path rather than survive as a renamed or
  hidden veto. Quant research integrity, out-of-sample claims, numerical failure
  handling, uncertainty, and full net economics are also explicit covenant
  requirements.
- This governance addendum is not implementation approval and authorizes no
  broker read, PAPER run, live action, mutation, dependency, subsystem, module
  deletion, or control change.
- Board campaign direction 2026-07-18: after Stages 0-12 pass, retire the
  commissioning mini-run ladder. The next external PAPER test is an 8-hour
  autonomous full-capability standard-profile campaign, followed only on binary
  gate success by 7-day and 30-day campaigns.
- Live repo truth: the current runner, supervisor, runtime config, API/UI, and
  tests enforce a `432000`-second (five-day) maximum, so the week/month sequence
  is not currently executable. The plan replaces that commissioning ceiling
  through the existing owners with a typed finite campaign envelope and a
  shorter renewable fenced worker lease; it does not delete validation or
  scatter larger hard-coded duration values.
- `AGENTS.md` Section 24 now binds full-capability campaign semantics: all
  lawfully wired standard-profile modules receive real production inputs and
  report truthful statuses; dormant/inapplicable modules are not forced to fire;
  zero natural trades is lawful; no guard, threshold, Risk, NetEdge, TTL, sizing,
  OMS, reconciliation, account-pin, PAPER/live, no-short, or no-naked-SELL
  control weakens.
- Safety disagreement recorded: the requested literal "run until crash" has no
  maximum mutation horizon and is rejected as written. Its lawful replacement
  is a separately approved endurance/controlled-failure campaign with a Board-
  selected maximum horizon, steady-state definition, fault schedule, hard stop
  conditions, fenced recovery, and final reconciliation.
- Operational horizons, deployment/tenant/account identifiers, recovery/data/
  log budgets, and capability manifests become typed, validated, versioned,
  operator-visible configuration in the correct existing owner. Immutable
  safety invariants remain hard enforcement and are never chat-mutable.
- Multi-tenant activation is deferred until after the campaign program as Shan
  directed. Current work avoids unnecessary single-tenant literals but does not
  create a parallel tenant subsystem. A second tester requires explicit
  credential/state/lease/order/risk/reconciliation/audit isolation and negative
  cross-tenant proof; authentication alone is insufficient.
- Tiny live-money testing remains Checkpoint I and is not authorized. PAPER
  results do not model market impact, information leakage, latency slippage,
  queue position, price improvement, or complete live fees and cannot
  automatically promote the bot to live trading.
- This update changed governance/planning documents only. No source, runtime
  config, state, broker state, cloud resource, test, PAPER run, or live path was
  changed or executed. Implementation approval for Stages 0-11 is still pending;
  Stage 12 reads and every Stage 13 campaign remain separate approvals.

## PAPER True Capability Stage 0

Stage 0 was explicitly approved by Shan on 2026-07-18 and is complete at the
local test rung. Full entry manifest, red-team, evidence, limitations, and exact
staging recommendation are in
`reports/completion/PAPER_TRUE_CAPABILITY_STAGE_0_REPORT.md`.

- PASS - one deterministic sanitized fixture freezes the four-hour run's 80
  candidate outcomes, two future-dated causal ages, 50 protected-baseline
  refusals, 15 stale-guard refusals, zero current-run mutations, bounded
  no-flatten shutdown, and final reconciliation.
- PASS - zero current-run broker mutations remain distinct from 55 older
  broker-filled rows and 92 missing hydration attempts observed during final
  reconciliation; Stage 0 does not claim the account has no historical orders.
- PASS - exactly five evidence states are defined and represented:
  `IMPLEMENTED_OFFLINE`, `OBSERVE_ONLY`, `MOCKED_EXECUTION_PROVEN`,
  `BROKER_READ_PROVEN`, and `BOUNDED_PAPER_PROVEN`. None grants Start, broker
  mutation, current readiness, or live authority.
- PASS - 17 frozen invariants map to 20 concrete negative-regression nodes. The
  exact node gate passed `20 passed`; it covers PAPER endpoint/account pin,
  live/real-money locks, SELL authority, no manual controls, MarketTruthSnapshot,
  Risk, NetEdge, sizing, TTL, OMS, reconciliation, governed Stop, dormant
  SovereignExecutionGuard, default thresholds, and proof-rung boundaries.
- PASS - the seven-file run-path gate reproduced `119 passed`.
- PASS - current full suite is `1826 passed, 14 skipped, 0 failed` with 384
  deprecation warnings. The six-pass increase from the frozen historical
  `1820 passed` baseline is exactly the new Stage 0 test module.
- Pinned limitation - Alpaca crypto capability declares `sell_to_close`, but
  the external PAPER adapter still rejects SELL with `only_buy_supported`.
  Stage 0 records this as a Stage 8 blocker and does not call it working.
- No production source/UI/script/config behavior changed. No browser/runtime
  proof, broker read, PAPER run, broker mutation, external fill, live action,
  real money, threshold change, module deletion, or protected state edit/stage
  occurred.
- Stage 1 and every later stage remain **NOT STARTED**. Stage 1 requires a new
  stage-entry covenant and Board direction; Stage 12 broker reads and every
  Stage 13 PAPER campaign retain their separate approval boundaries.

## Dirty Tree / Baseline Status

The worktree remains dirty from protected runtime files and pre-existing
untracked report/script leftovers. Do not create `pre-completion-baseline` yet. Per AGENTS.md v3, baseline
tag and `completion/main` branch require a clean tree and must not be forced by
clean/stash/reset.

## Current Board Rulings Captured

- Shan authorized Phase A reversible work to fix collection/syntax/import health.
- Shan authorized Phase B reversible work to write and commit the truth-map document and tracker.
- Shan authorized Phase D build after accepting Codex's challenge note. Board rulings: `~/.poverty_killer_alpaca_paper_env` is the single canonical Alpaca PAPER credential authority for D2; only `READY_FOR_BOUNDED_PAPER` may green-light Run PAPER for D6; D0 proof means no active runtime path outside `OrderRouter`.
- Shan authorized Phase D1-FIX: `StaleDataGuard` is wired as a blocking evidence contributor under `evaluate_pre_trade_guardrails`; `SovereignExecutionGuard` is mutation-capable and remains dormant by policy pending Phase H/I arming.
- Shan authorized D4 read-only Alpaca PAPER inspection: account status, open orders, and positions only; canonical env credential source; paper endpoint only; no order placement/cancel/close/liquidate/flatten and no PAPER run.
- Shan authorized Phase E AI Chief Useful: AI remains advisory-only; no broker/live/threshold touch; provider/model route truth, evidence-bound answers, canonical D6 blockers, and mutation/secret refusal proofs required.
- Shan authorized D4-ACCOUNT-IDENTITY read-only proof before Phase F. Result: canonical account is funded `redacted_suffix:045ded`, second account `redacted_suffix:104e2a` is reachable only through demoted local vault/state, but account identity is runtime-inferred in code, so Phase F is blocked pending Board confirmation of the account-pin fix.
- Shan authorized D4-ACCOUNT-PIN to hard-pin PAPER operation to funded account suffix `045ded`. Result: account identity assertion is wired into readiness/supervisor start, mismatch fails closed, demoted/drained suffix `104e2a` is rejected in tests, and Phase F is unblocked.
- Phase F UI cockpit is complete. Result: Run PAPER cockpit renders account-pin truth, disables Start without proven pin, and passed desktop/mobile browser validation. Phase G bounded PAPER run remains Board-gated.
- Shan authorized Phase G Bounded PAPER Run READY with D4 read-only broker re-arm. Result: Phase G readiness is PASS with broker-read-only and browser proof; actual PAPER execution remains Shan/Board-gated.
- Shan directed the pre-arming run-path-green disposition: root-cause the reported 49 by cluster, require zero named run-path failures, preserve off-path deferrals, and do not weaken any guard, threshold, or assertion. Result: run path and full local suite have zero failures; external broker proofs remain explicitly environment-gated.
- Shan reported that the opened bot did not allow useful interaction, required a
  360-degree blocker analysis and approval gate, then approved the scoped fixes
  with `proceed`. Result: the unreachable verification path, stale Start proof,
  competing update transports, misleading copy, conflated AI route truth, masked
  refusal reason, and live Controls renderer exception were fixed and proved.
- Shan explicitly authorized and attempted a four-hour bounded PAPER run by
  selecting four hours and pressing Start. Repo/runtime truth proved that the UI
  never sent the request, so no run started. Codex repaired the interaction but
  did not infer permission to resend the failed Start automatically; final Start
  remains Shan's explicit browser action.
- No live mode, live read-only mode, or broker mutation was authorized.
- Shan explicitly approved PAPER True Capability Stage 0 on 2026-07-18. Result:
  Stage 0 passed its offline fixture/invariant/fingerprint gate and full local
  suite without changing production behavior. This approval does not open Stage
  1, authorize broker reads, execute PAPER, or alter any live/money boundary.
