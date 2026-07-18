# PAPER True Capability Stage 0 Report

Date: 2026-07-18 America/Chicago
Stage: 0 - Freeze the proof baseline and define activation invariants
Branch: `master`
Stage-entry HEAD: `d3692b6 clarify lifecycle deployment proof boundary`
Board approval: Stage 0 explicitly approved by Shan on 2026-07-18
Status: **PASS - STAGE 0 CLOSED AT THE LOCAL TEST RUNG**

## Stage-Entry Manifest

`AGENTS.md` v3 plus Sections 23 and 24 were re-read in full before Stage 0
implementation. `CHECKPOINT_TRACKER.md`, the latest handoff, the master plan,
current git state, relevant source owners, tests, and the completed four-hour
run artifact were inspected before any test or fixture edit.

### Objective and binary exit

Objective: freeze current evidence and safety behavior so later true-capability
stages cannot rewrite history, silently change controls, or turn a lower proof
rung into runtime/PAPER readiness.

Binary exit:

1. a sanitized deterministic offline fixture reproduces representative
   candidate, causal-age, protected-baseline, stale-guard, no-trade, shutdown,
   and reconciliation truth from the four-hour run;
2. every Stage 0 sacred invariant maps to and passes at least one negative test;
3. threshold/default/profile, capability, authority, mutation-surface, and
   module-classification fingerprints are exact and machine-checked;
4. one activation matrix uses only `IMPLEMENTED_OFFLINE`, `OBSERVE_ONLY`,
   `MOCKED_EXECUTION_PROVEN`, `BROKER_READ_PROVEN`, and
   `BOUNDED_PAPER_PROVEN`, with explicit proof boundaries and no activation
   authority;
5. no production/runtime/UI/script behavior changes.

### Stop conditions

Stop immediately if:

- fixture construction needs a raw secret, full account ID, broker order ID,
  client order ID, position quantity, runtime state file, or copied raw log line;
- a test can pass only by weakening a guard, threshold, fixture assertion,
  endpoint pin, account pin, no-SELL rule, mutation audit, or source fingerprint;
- the activation matrix becomes a second readiness/arming authority or labels
  offline/mock/history as current runtime truth;
- current zero-mutation truth is conflated with historical broker order/fill
  activity observed at final reconciliation;
- an application, UI, script, config, state, log, database, credential, or
  unrelated dirty file must be edited;
- a broker call, PAPER run, live path, external dependency, deletion, or
  threshold/control change becomes necessary;
- an affected restriction remains `UNKNOWN`, another actor changes a scoped
  file, or a baseline fingerprint changes unexpectedly.

### In-scope files

Planned Stage 0 files:

- `tests/fixtures/paper_true_capability_stage0.json` - sanitized deterministic
  fixture, activation matrix, invariant manifest, and baseline fingerprints;
- `tests/test_paper_true_capability_stage0.py` - offline parser/schema,
  provenance, semantic fingerprint, negative-test ownership, and no-fake-
  readiness checks;
- `reports/completion/PAPER_TRUE_CAPABILITY_STAGE_0_REPORT.md` - this entry and
  close report;
- `AGENTS.md` - pre-existing Board-ratified Sections 23/24, no Stage 0 behavior
  edit planned;
- `reports/completion/PAPER_TRUE_CAPABILITY_MASTER_PLAN.md` - pre-existing
  Board-ratified plan, no Stage 0 behavior edit planned;
- `CHECKPOINT_TRACKER.md` and `reports/codex_handoff_latest.md` - Stage 0 ruling,
  evidence, status, limitations, and next boundary.

### Forbidden and unrelated files

No edits or staging are allowed for `app/**`, `ui/**`, `scripts/**`, `main.py`,
runtime config, `state/**`, `.pytest_tmp/**`, logs, databases, credentials,
secrets, screenshots, `reports/operator_perf/**`, old handoffs, UI proposal
packets, or untracked audit scripts. Source owners are read-only inputs to Stage
0 fingerprint and behavior tests.

### Complete dirty-worktree record at entry

Related in-flight planning/governance files:

```text
 M AGENTS.md
 M CHECKPOINT_TRACKER.md
 M reports/codex_handoff_latest.md
?? reports/completion/PAPER_TRUE_CAPABILITY_MASTER_PLAN.md
```

Protected pre-existing runtime/evidence files, not touched or staged:

```text
 M state/override_log.jsonl
 M state/risk_state.backup
 M state/risk_state.json
 M state/risk_state.tmp
 M state/session_journal.jsonl
?? .pytest_tmp/
?? AGENTS.prev.md
?? POVERTY_KILLER_AUDIT_REPORT.txt
?? reports/codex_handoff_2026-06-02_operator_truth_sync_ai_router.md
?? reports/codex_handoff_2026-06-07_final_ai_provider_truth.md
?? reports/codex_handoff_2026-06-12_operator_control_plane_fast_synced.md
?? reports/codex_handoff_2026-06-20_p3n_24h_final_360.md
?? reports/codex_handoff_2026-06-21_p3or_funded_revalidation_blocked.md
?? reports/codex_handoff_2026-06-21_pk_ui1_operator_cockpit_build.md
?? reports/completion/PAPER_AUTONOMY_RESTRICTIONS_REVIEW.md
?? reports/completion/UI_NOVEL_OPERATOR_COCKPIT_BOARD_PACKET.md
?? reports/completion/UI_WORLD_CLASS_REDESIGN_PACKET.md
?? reports/operator_perf/
?? scripts/_paper_audit_common.py
?? scripts/audit_oms_shutdown.py
?? scripts/audit_paper_run.py
?? scripts/audit_safety_markers.py
```

Baseline tag/branch creation remains deferred. The dirty tree will not be
cleaned, reset, stashed, pruned, or normalized.

### Affected truth map and one-owner authority graph

| Area | Current purpose and data | Runtime/classification | Authority allowed in Stage 0 | Integration plan |
| --- | --- | --- | --- | --- |
| Four-hour stdout artifact | Historical text evidence from the completed commissioning run | Read-only runtime artifact; not tracked truth authority | Evidence source only | Allowlist semantic fields into a sanitized JSON fixture; retain source SHA-256 and limitations |
| Stage 0 fixture/parser | Deterministic offline evidence and baseline manifest | New test-only proof surface | No trading, readiness, broker, or UI authority | Standard-library JSON parsing and exact schema tests only |
| `MarketTruthSnapshot` | Canonical executable market truth | `WIRED_WITH_ROLE`; market-truth owner | Read-only fingerprint and existing negative test | Preserve unchanged |
| `evaluate_pre_trade_guardrails` | Hard Risk admission | `WIRED_WITH_ROLE`; Risk owner | Read-only fingerprint and existing negative tests | Preserve unchanged |
| `PositionSizingEngine` | Canonical executable sizing | `WIRED_WITH_ROLE`; sizing owner | Read-only fingerprint and existing negative test | Preserve unchanged |
| `OrderRouter` | Order/OMS lifecycle | `WIRED_WITH_ROLE`; broker-order owner | Read-only fingerprint and reconciliation tests | Preserve unchanged |
| Broker/reconciliation truth | Broker acknowledgement plus OMS reconciliation | Broker owns external facts; reconciliation owns fill/position truth | Historical evidence and mocked behavior tests only | Never relabel fixture fields as current broker truth |
| `AlpacaPaperBrokerAdapter` | Pinned PAPER GET/POST/DELETE boundary | `WIRED_WITH_ROLE`; lower-layer adapter, not final owner | Read-only fingerprint and fake-transport negative tests | Preserve current buy-only limitation for Stage 8 correction |
| `OperatorPaperSupervisor` | Singleton run/Stop lifecycle owner | `WIRED_WITH_ROLE` | Read-only fingerprint and isolated fake-runner Stop test | Preserve unchanged |
| `SovereignExecutionGuard` | Mutation-capable pre-integration guard | `PRESERVED_DORMANT` by policy | None | Assert dormant; do not instantiate or activate |
| `GammaFront` | Runtime exit role; missing lawful entry feed | `WIRED_EXIT_ONLY / ENTRY_FEED_DORMANT` | Evidence classification only | Preserve, do not force entry output |
| UI | Operator display | Display owner only | Existing negative no-manual-control test | No UI edit or readiness claim |
| AI Chief | Evidence-bound advisory | Advisory owner only | None | No prompt, provider, or authority change |

No new production owner or subsystem is introduced. The activation matrix is a
test/report evidence index and explicitly cannot authorize Start or broker work.

### Restriction ledger

| Restriction/control | Owner | Classification | Stage 0 disposition |
| --- | --- | --- | --- |
| Six-symbol watchlist | `OperatorRuntimeConfig`/supervisor | `COMMISSIONING_OR_TEST_SCAFFOLD` | Fingerprint and retain; later Stage 3/4/9 replacement only |
| Forced `PAPER_EXPLORATION_ALPHA` profile | runtime config/main loop | `COMMISSIONING_OR_TEST_SCAFFOLD` | Fingerprint default/exploration values; do not change |
| Protected-baseline blanket refusal | baseline policy/pre-trade guard | `COMMISSIONING_OR_TEST_SCAFFOLD` with permanent broker-inventory safety beneath it | Preserve and fixture its refusal; later inventory authority must replace it |
| Adapter rejects every SELL while static registry declares `sell_to_close` | adapter/capability registry | `COMMISSIONING_OR_TEST_SCAFFOLD`, currently `BLOCKED_WITH_REASON` for external sell | Preserve contradiction visibly; Stage 8 owns repair after inventory proof |
| Alpaca PAPER endpoint only | credential/adapter authority | `PERMANENT_SAFETY_CONTROL` | Retain and negative-test live/non-paper refusal |
| Expected account suffix before order one | credential/adapter authority | `GOVERNANCE_OR_ARMING_CONTROL` | Retain and negative-test mismatch before POST |
| No live/real money | runtime config/readiness/adapter | `PERMANENT_SAFETY_CONTROL` | Retain and negative-test |
| No naked/short SELL | capability/Risk/OMS/adapter | `PERMANENT_SAFETY_CONTROL` | Retain and negative-test unsupported SELL before POST |
| Market truth, Risk, NetEdge, sizing, TTL, OMS, reconciliation | named authority owners | `QUANT_OR_ECONOMIC_CONTROL` / `PERMANENT_SAFETY_CONTROL` | Retain exact values/owners and negative tests |
| Governed Stop emits no broker mutation | supervisor | `GOVERNANCE_OR_ARMING_CONTROL` | Retain and fake-runner/fake-broker mutation-audit test |
| Five-day maximum | runtime config/supervisor/runner | `GOVERNANCE_OR_ARMING_CONTROL` in current implementation | Fingerprint and retain; Stage 9 may replace only with proven campaign envelope/lease authority |
| `SovereignExecutionGuard` dormant | authority graph/policy | `GOVERNANCE_OR_ARMING_CONTROL` | Retain dormant and negative-test no active instantiation |

No affected restriction is `UNKNOWN`. Stage 0 removes or narrows none.

### Baseline semantic fingerprints

Historical suite result, explicitly **not rerun at stage entry**:
`1820 passed, 14 skipped, 0 failed` from the latest lifecycle handoff.

Four-hour source artifact:

- relative source: `logs/paper_runs/bounded_paper_20260717_182808.out.log`;
- SHA-256: `335a67411bac595b2d5928a5d9e4fee06d2bd4d64e88c14969e8caafcd098240`;
- size previously measured: 106,512,681 bytes;
- source remains read-only and will not be staged.

Runtime configuration:

- allowed watchlist: `BTC/USD`, `ETH/USD`, `SOL/USD`, `LTC/USD`, `AVAX/USD`,
  `LINK/USD`;
- allowed profile: `PAPER_EXPLORATION_ALPHA`;
- allowed durations: `180, 300, 900, 1200, 1800, 3600, 7200, 10800, 14400,
  86400, 259200, 432000`;
- duration min/max: `60 / 432000` seconds;
- live/real-money defaults: `false / false`;
- expected PAPER account suffix: `045ded`.

Threshold profile, exact entry values:

| Threshold | Default | Exploration |
| --- | ---: | ---: |
| `shans_ready_required` | `true` | `false` |
| `fusion_min_confidence` | `0.60` | `0.35` |
| `sector_inflow_threshold` | `1.50` | `0.75` |
| `sector_rotation_min_confidence` | `0.60` | `0.45` |
| `sector_rotation_min_baseline_candles` | `10` | `3` |
| `shadowfront_whale_threshold` | `0.20` | `0.10` |
| `shadowfront_sentiment_velocity_threshold` | `1.50` | `0.10` |
| `shadowfront_min_confidence` | `0.60` | `0.45` |
| `minimum_opportunity_score` | `0.45` | `0.25` |
| `optional_alpha_quorum` | `1` | `0` |

Authority graph:

- version `authority-graph-v1`;
- market truth: `app.core.market_snapshot.MarketTruthSnapshot`;
- Risk: `app.risk.pre_trade_guardrails.evaluate_pre_trade_guardrails`;
- sizing: `app.risk.position_sizing.PositionSizingEngine`;
- broker/order lifecycle: `app.execution.order_router.OrderRouter`;
- portfolio/position truth: `app.risk.exposure_manager.ExposureManager`;
- AI advisory: `app.ai_chief_operator.provider_gateway.AIProviderGateway`;
- UI display: `ui/operator-control-panel/app.js`.

Phase B classification baseline: 397 countable modules: 297 `WIRED`, 89
`BLOCKED`, 10 `PRESERVED-DEAD`, and 1 `REJECTED-PRESERVED`. Generated
`__pycache__` artifacts remain excluded. The Stage 0 fixture does not reclassify
any module.

Broker mutation surface:

- final owner: `OrderRouter`;
- lower adapter POST: `AlpacaPaperBrokerAdapter.submit_order -> POST /v2/orders`;
- lower adapter DELETE: `cancel_order -> DELETE /v2/orders/{order_id}`;
- current adapter payload: positive-quantity BUY limit only;
- live endpoint blocked; live mutation false; no Stage 0 test permits transport
  POST/DELETE;
- registry currently declares Alpaca PAPER crypto `buy` and `sell_to_close`,
  while external adapter SELL remains blocked. This is a named Stage 8 blocker,
  not a Stage 0 pass.

### Source SHA-256 fingerprints

```text
4ec83796c3de5464554da7a4ad524e48c760e90c5075cc4f8d8cf8a9f87ab94a  app/core/decision_frame.py
822ea28bee27e4711900e8f6d46ca1ed2ea2f3901cfaa59845b06aa3dd37190d  app/main_loop.py
f8e08c8234f3104929bace10989d908c3892d5ca66ce5aca7737dca24a5a3955  app/execution/alpaca_paper_adapter.py
9ecf7ebb866dcd284bd2b8c5cd1d168e332751bad3d2451c2d1085ad9b79e158  app/market/capability_registry.py
f6c7ac908a3be8252827b83cbd458072198735214d3c4c9498c00cab262f7068  app/core/authority_graph.py
31f0c17173449d9a27f92c88a5e704347891d2eaf95ebb98cfffc52f3b654085  app/api/operator_paper_supervisor.py
3f79b4cf63e58de7d01c60b327fd9a5737f0db0cd79932105f7eec2b0cd6ac95  app/api/operator_runtime_config.py
25f33b3ec1867b8431e0e6c3019531b2d2f9f604f4edef75ae99ddd421bbe46b  app/operator_credentials/store.py
403d205689940ed7e213708c4d48ffb84fa13ecd42f231593f73c7671d3267e7  main.py
d3b1a3f8b89b5d1a165f31ba859c7d55addf416c04722932731e195425660e1f  app/core/market_snapshot.py
e6bd34aaf89b2ea56e479ed169d35da0854e62328cb268070125c572293c7793  app/risk/pre_trade_guardrails.py
635f3c0301db73a744543cd00e31c2543fbc1565b85acf932f09f7cc81617eeb  app/risk/net_edge_governor.py
02612060e6adbc653c215db702a8bcae8e61bbb5ef97d482979f3f2fa1f35921  app/risk/position_sizing.py
25eb401926dac08910dc5eb61461b6019ba58f8543d2685deede4524a87e0b12  app/execution/order_router.py
918092f7d335fa58556f92c824dd88298c590283de62a5766451bfd65222bc3f  ui/operator-control-panel/app.js
4857b57e4dbc4570622eed268def78b3c9ae03ed275149b120b432572339925f  reports/completion/PHASE_B_MODULE_TRUTH_MAP.md
```

### Mathematical/model inventory

Stage 0 changes no strategy, scoring, Risk, sizing, NetEdge, covariance,
execution, fee, slippage, TTL, or portfolio mathematics.

The only fixture mathematics are exact integer counts, booleans, string reason
codes, and signed nanosecond ages copied by semantic allowlist. Negative age is
preserved as a causal defect and is never absolute-valued, clamped to zero, or
called fresh. No estimator, calibration, tolerance, stochastic seed, float
conversion, or statistical inference is introduced. Exact equality is the
parser/test contract. Known limitation: summarized counts depend on the audited
four-hour artifact and do not establish alpha quality or profitability.

### Planned proof and test matrix

New Stage 0 tests will prove:

1. standard-library JSON parsing, schema version, record-kind completeness, and
   deterministic record identity;
2. source SHA-256 provenance plus allowlist sanitization; no key/secret/account/
   order ID, position quantity, raw P&L, fee, or raw line survives;
3. candidate/no-trade/refusal counts remain internally consistent;
4. zero run POST/DELETE acknowledgement remains distinct from 55 historical
   broker filled orders and 92 missing local fill-ledger hydration rows observed
   by final reconciliation;
5. negative causal ages, stale guard refusals, no-flatten shutdown, and final
   reconciliation are not rewritten as positive readiness;
6. all five activation states have one unambiguous definition, every matrix row
   names proof/limitations, and no row grants Start/live/broker authority;
7. invariant test node IDs still exist as concrete pytest functions;
8. runtime/default/threshold/authority/capability/module/source fingerprints
   match the frozen entry manifest.

Focused negative behavior nodes include endpoint/live refusal, account-pin
mismatch before order one, unsupported SELL before POST, no manual controls,
stale MarketTruthSnapshot refusal, Risk conflict refusal, negative/unknown
NetEdge refusal, sizing authority/cap enforcement, hard TTL behavior, OMS
conflict/reconciliation failure, governed Stop zero mutation, dormant Sovereign
guard, and unchanged threshold defaults.

Validation plan: compile the new test, run its tests, run every manifest-owned
negative node, run the established run-path suite, then run the full configured
suite with a temp root outside protected `.pytest_tmp/`. No browser or runtime
server is required because Stage 0 changes no UI/runtime behavior. No broker
read or mutation is authorized.

### Proof/approval boundary

- Offline source/test/report work: approved.
- Runtime/browser launch: not needed for Stage 0 and not claimed.
- Alpaca PAPER broker read: not authorized this stage.
- PAPER run/mutation: not authorized.
- Live credentials/read/mutation/real money: not authorized.
- Dependency/subsystem/module deletion/reclassification: not authorized.
- Runtime/state/log/database/secret edits: forbidden.
- Staging: exact Stage 0 test/fixture/report plus the related pending governance,
  plan, tracker, and current handoff only after validation.

## Pre-Code Independent Red-Team

### Duplicate authority

Risk: an activation matrix could become a second readiness registry.

Control: it lives only under `tests/fixtures`, is labeled historical/offline,
has no app import, grants no Start/broker/live authority, and is tested to keep
all authority flags false. Existing readiness, authority graph, Broker, Risk,
OMS, reconciliation, AI, and UI owners remain unchanged.

### Fake readiness or hidden broker truth

Risk: `IMPLEMENTED_OFFLINE`, `MOCKED_EXECUTION_PROVEN`, or the historical
four-hour run could be presented as current full-capability readiness.

Control: every matrix row states its rung, source date, limitation, and
`current_activation_authority=false`. Historical broker reads are not current
authorization. Fixture reconciliation preserves historical filled-order counts
and missing fill-ledger truth alongside zero mutations from this run.

### Guard/threshold/economic weakening

Risk: a convenient fixture could omit hard refusals or normalize negative ages.

Control: preserve reason codes and signed ages exactly; semantic tests compare
current thresholds/defaults and hard-owner hashes. No source or fixture value is
changed to obtain green.

### Tests green while runtime fails

Risk: meta-tests could only prove that test names exist.

Control: run every named behavior node, the run-path gate, and the full suite.
Report the proof rung as offline tests only. No runtime or broker claim follows.

### Mock/stale data represented as real

Risk: sanitized records lose provenance and look broker-confirmed.

Control: fixture-level `evidence_rung`, `historical`, `sanitized`, `source_sha256`,
and per-record truth class are mandatory. Mocked and broker-read rows remain
distinct. The fixture never becomes an executable input.

### UI clutter or AI hallucination

No UI or AI file is changed. The activation matrix is not exposed through API
or UI. AI receives no new evidence source in Stage 0.

### Flattening, deletion, or module loss

No module is changed, deleted, activated, simplified, or reclassified. The
current adapter/capability contradiction and GammaFront dormant-entry boundary
remain visible rather than being hidden for a cleaner matrix.

### State/restart and hidden configuration

No state migration or runtime restart occurs. Current runtime config and source
files are hash/semantic inputs only. The report calls the six-symbol exploration
profile and five-day ceiling current facts, not production targets.

### Red-team verdict

The seam survives only as a test/report certification layer with zero production
authority and exact provenance. The stop conditions above halt it if that
boundary changes.

`STAGE_ENTRY_COVENANT: PASS`

## 1. Verdict

**PASS.** Stage 0's binary exit is satisfied at the local test rung:

1. the sanitized fixture deterministically preserves the required historical
   candidate, causal-age, baseline, stale-guard, no-trade, shutdown, and
   reconciliation evidence;
2. all 17 frozen invariants map to existing negative-regression tests and the
   20 unique mapped nodes pass;
3. runtime defaults, exploration thresholds, authority owners, module counts,
   Alpaca capability/adapter contradiction, mutation surface, and 16 source
   hashes are machine-pinned;
4. the five-state activation vocabulary grants no Start, broker-mutation, or
   live authority; and
5. no production/runtime/UI/script behavior changed.

Stage 1 is not opened. No lower proof rung has been relabeled as current
readiness or full-capability PAPER proof.

## 2. Files Changed

Stage 0 implementation/evidence files:

- `tests/fixtures/paper_true_capability_stage0.json` - sanitized deterministic
  evidence, activation matrix, invariant manifest, and fingerprints;
- `tests/test_paper_true_capability_stage0.py` - six offline regression tests;
- `reports/completion/PAPER_TRUE_CAPABILITY_STAGE_0_REPORT.md` - entry manifest,
  red-team, results, and close audit;
- `CHECKPOINT_TRACKER.md` - Stage 0 approval/result and next boundary;
- `reports/codex_handoff_latest.md` - current continuity state.

Related Board-ratified planning/governance files already dirty before Stage 0
and included in the exact staging recommendation:

- `AGENTS.md` - Sections 23/24 non-degradation and campaign governance;
- `reports/completion/PAPER_TRUE_CAPABILITY_MASTER_PLAN.md` - approved staged
  program and Stage 0 contract.

No file under `app/**`, `ui/**`, `scripts/**`, `state/**`, or runtime/log/secret
storage was edited by Stage 0.

## 3. Root Cause

The true-capability program currently depends on dispersed historical reports,
large mutable runtime logs, and many independent safety tests. Without one
sanitized fixture, invariant manifest, activation vocabulary, and exact
fingerprints, later stages could accidentally rewrite the baseline or overclaim
their proof rung.

## 4. Fixes Implemented

1. Added one allowlisted JSON fixture with source path, source SHA-256, byte
   size, historical/sanitized flags, and explicit non-authority flags.
2. Preserved the completed run's exact decision-path totals: 80 candidates, 50
   protected-baseline refusals, 15 `BEARISH_NO_LONG`, 13 absolute-drift blocks,
   2 safe-mode blocks, and zero submissions.
3. Preserved signed future-dated ages (`-84711522000` and `-95000000000` ns) as
   causal contamination. They are not absolute-valued, clamped, or called
   fresh by the Stage 0 interpretation.
4. Kept two different truths separate: this run made zero broker mutations,
   while final reconciliation observed 55 older broker-filled orders and 92
   missing hydration attempts. The fixture cannot imply zero historical broker
   activity.
5. Defined and represented exactly `IMPLEMENTED_OFFLINE`, `OBSERVE_ONLY`,
   `MOCKED_EXECUTION_PROVEN`, `BROKER_READ_PROVEN`, and
   `BOUNDED_PAPER_PROVEN`. Every row denies current activation, PAPER Start,
   broker mutation, and live authority.
6. Mapped 17 sacred invariants to 20 unique negative test nodes covering PAPER
   endpoint/account pin/live/real-money, SELL authority, manual controls,
   MarketTruthSnapshot freshness, Risk, NetEdge, sizing, TTL, OMS,
   reconciliation, governed Stop, dormant SovereignExecutionGuard, unchanged
   defaults, and proof-rung non-escalation.
7. Added semantic pins for current runtime universe/profile/durations, all ten
   default/exploration threshold pairs, the seven authority owners, Phase B
   module counts, the declared `sell_to_close` capability versus the adapter's
   `only_buy_supported` refusal, the POST/DELETE mutation surface, and 16
   source-file hashes.

## 5. 360-Degree Adjacent Improvements

- The fixture schema rejects secret/order/account identifiers and absolute
  scratch paths, so it is portable test evidence rather than copied runtime
  state.
- Test-node ownership is AST-validated, including class-qualified pytest nodes;
  a renamed or deleted safety test fails Stage 0 instead of silently reducing
  coverage.
- The account pin, default exploration profile, six-symbol commissioning list,
  and five-day ceiling are frozen as current facts, not endorsed as final
  production design.
- The capability registry/adapter SELL disagreement is deliberately a failing
  capability boundary for Stage 8, not a fake green row.
- The exact run-path gate and full suite were rerun after the new pins, proving
  the test-only seam did not regress the active local behavior covered there.
- Research was not required: this stage changed no UI, operator workflow,
  trading model, portfolio/risk method, or production diagnostics.

## 6. Tests and Checks

| Check | Result | Proof rung |
| --- | --- | --- |
| `python -m py_compile tests/test_paper_true_capability_stage0.py` | PASS | syntax |
| Standard-library JSON parse | PASS: schema v1, 7 records, 17 invariants, 5 activation rows | offline fixture |
| First focused invocation with fixed `C:\tmp` basetemp | **NON-RESULT:** 5 tests passed, sixth failed in pytest setup with `PermissionError`; no application assertion failed | harness failure, not proof |
| Focused Stage 0 rerun with unique OS temp path | PASS: `6 passed` | local tests |
| Exact invariant-node gate | PASS: `20 passed`, 75 warnings | local negative-regression tests |
| Seven-file run-path gate | PASS: `119 passed`, 78 warnings | local run-path tests |
| First full-suite wrapper with one-second command timeout | **NON-RESULT:** wrapper killed before a test result; it left no new Python process | harness failure, not proof |
| Full suite rerun with valid timeout | PASS: `1826 passed, 14 skipped, 384 warnings, 0 failed` in 133.60s | local full-suite tests |

The entry value `1820 passed, 14 skipped, 0 failed` remains correctly labeled
historical inside the fixture. The current rerun is 1826 passes because Stage 0
adds six tests. The 14 conditional skips remain skips; Stage 0 did not enable
broker-access authorization variables.

Warnings are existing Pydantic v2 deprecations and timezone-naive datetime
deprecations. They were not converted to passes or suppressed, and are not
within this certification-only seam.

## 7. Browser, Runtime, and Broker-Read-Only Proof

Not run. Stage 0 performed no browser validation, local runtime boot, broker
GET, PAPER run, order submission, cancel, replacement, close, liquidation, or
external fill. The highest rung climbed is local test proof.

## 8. Self-Red-Team and Anti-Hallucination Check

### What was actually inspected

- Full binding `AGENTS.md`, tracker, handoff, master plan, current git state,
  relevant production owners, mapped safety tests, Phase B truth map, source
  fingerprints, and the audited four-hour evidence summary.
- The raw four-hour log's hash/size and exact final semantic fields already
  audited in the master plan; Stage 0 did not copy raw lines or identifiers.
- Fixture/test diffs and all named validation gates above.

### What tests prove

- The sanitized fixture is deterministic, secret-safe, non-authoritative, and
  semantically equal to the frozen evidence fields.
- The 17 invariants still have executable negative-regression owners and their
  20 unique nodes pass.
- Current default/config/authority/capability/module/source fingerprints match
  the freeze.
- The run-path gate and full local suite have zero failures.

### What tests do not prove

- Current process health, browser truth, market-data freshness, Alpaca account
  state, external submit/fill/sell-to-close, autonomous recovery, dynamic
  universe behavior, or profitable trading.
- That every module is production-fed or that Stage 1-13 prerequisites pass.
- That the current SELL contract works externally; it is proven blocked.

### Adversarial answers

- Duplicate authority: no. The fixture is under `tests/fixtures`, is not an app
  import, and every authority flag is false.
- Fake readiness: no. Historical/mock/offline rows remain distinct and cannot
  authorize Start.
- Hidden broker truth: no. Zero current-run mutation and nonzero older broker
  history are both retained.
- Guard/threshold weakening: none. Exact defaults and source hashes now fail on
  drift.
- Test-only happy path: no. Every mapped negative node, the run path, and the
  full suite ran; two harness mistakes are recorded as non-results.
- Mock/stale data passed as real: no. Provenance and limitation fields are
  mandatory and tested.
- Module loss/flattening: none. GammaFront's dormant entry feed and the adapter
  SELL blocker stay visible.
- UI cosmetics over broken truth: no UI file changed.
- Unknowns summarized away: no. Proof limitations and deferred stages remain
  explicit below.

## 9. Safety Confirmation

PASS. Stage 0 performed no broker call, PAPER run, live action, order, cancel,
replace, close, liquidation, threshold change, source behavior change, runtime
config change, state edit, secret read, dependency addition, module activation,
module deletion, or authority transfer. MarketTruthSnapshot, Risk, NetEdge,
sizing, TTL, OMS, reconciliation, endpoint/account pins, no-short/no-naked-SELL,
governed Stop, and dormant SovereignExecutionGuard remain unchanged.

## 10. Module Status

No module status changed. Affected production modules remain as recorded in the
entry truth map. Specifically:

- MarketTruthSnapshot, Risk, PositionSizingEngine, OrderRouter, broker truth,
  supervisor, UI display, and AI advisory owners remain `WIRED_WITH_ROLE`;
- `SovereignExecutionGuard` remains `PRESERVED_DORMANT`;
- GammaFront remains `WIRED_EXIT_ONLY / ENTRY_FEED_DORMANT`;
- Alpaca external SELL remains `BLOCKED_WITH_REASON: only_buy_supported` even
  though the registry declares `sell_to_close`.

The fixture/parser itself is test-only `IMPLEMENTED_OFFLINE` with no production
authority.

## 11. Disagreements

No disagreement with Stage 0. The activation matrix must remain evidence, not
runtime authority. The existing registry/adapter SELL disagreement is surfaced,
not resolved here; changing it before broker-inventory and sell-provenance proof
would violate the staged plan. The prior safety disagreement over an unbounded
"run until crash" remains governed by Section 24's finite endurance campaign.

## 12. Limitations and Unknowns

- Stage 0 is certification, not capability activation. It removes no
  commissioning restriction and changes no production behavior.
- Browser/runtime/broker-read-only/external-mutation proof was not run.
- The six-symbol universe, forced exploration profile, protected-baseline veto,
  buy-only external adapter, and five-day ceiling remain active limitations.
- The full suite's 14 broker/access skips are preserved conditional deferrals,
  not passes.
- Historical reconciliation contains 55 broker-filled rows and 92 missing
  hydration attempts not created by this run; exact per-row lineage is outside
  Stage 0.
- Source-byte hashes intentionally make any change visible, but a deliberate
  later source change must update the freeze only with its own stage evidence;
  Stage 0 itself does not approve such an update.
- Existing deprecation warnings remain unresolved and visible.
- Stage 1 and all later stages are not started. Stage 12 broker reads and every
  Stage 13 PAPER campaign still require their own Board approvals.

## 13. Exact Staging Recommendation

Stage exactly these seven files by explicit path:

```text
AGENTS.md
CHECKPOINT_TRACKER.md
reports/codex_handoff_latest.md
reports/completion/PAPER_TRUE_CAPABILITY_MASTER_PLAN.md
reports/completion/PAPER_TRUE_CAPABILITY_STAGE_0_REPORT.md
tests/fixtures/paper_true_capability_stage0.json
tests/test_paper_true_capability_stage0.py
```

Do not stage `state/**`, `.pytest_tmp/**`, logs, screenshots,
`reports/operator_perf/**`, old handoffs, UI proposal/restriction-review
packets, untracked audit scripts, secrets, databases, or runtime artifacts.
