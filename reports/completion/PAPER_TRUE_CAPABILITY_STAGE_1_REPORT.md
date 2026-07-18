# PAPER True Capability Stage 1 Report

Date: 2026-07-18 America/Chicago
Stage: 1 - Repair causal time and per-symbol state
Branch: `master`
Stage-entry HEAD: `e363f4b919d3ae52416278c810a87169ca7f1186`
Board direction: Shan approved Stage 0 and then directed `proceed` on 2026-07-18
Close status: **COMPLETE - PASS AT THE LOCAL OFFLINE TEST RUNG**

## Stage-Entry Manifest

`AGENTS.md` v3, including binding Sections 23 and 24, was re-read in full
before any Stage 1 source, test, configuration, or runtime edit. The current
tracker, latest handoff, approved master plan, Stage 0 report and fixture,
current git state, live callers, contracts, models, and focused tests were
inspected. This report is the first Stage 1 file edit.

### 1. Stage objective and binary exit

Objective: make each decision consume only evidence for its own symbol that was
available at or before the decision time, while retaining every existing Risk,
MarketTruthSnapshot, TTL, economic, sizing, OMS, reconciliation, endpoint, and
account control.

Binary exit:

1. no negative-age input can be recorded as fresh or receive temporal discount
   `1.0`;
2. BTC/ETH or any other symbols cannot share fusion cache, hysteresis, last
   decision, entropy state, physical state, stale-guard state, module evidence,
   Shans volume, or candidate topology;
3. fusion uses a deterministic same-symbol as-of join and explicitly refuses
   event or availability timestamps after the decision timestamp;
4. one persistent `StaleDataGuard` per `SymbolRuntime` consumes actual
   transport receipt/event clocks, retains kinematics, and contributes its
   assessment to the existing pre-trade Risk authority without being recreated
   there;
5. MarketTruthSnapshot remains the sole executable candle/book freshness owner;
   the 500 ms StaleDataGuard limit remains transport drift, not candle age;
6. the global WhaleFlow callback write and duplicate symbol-runtime trade write
   leave the active path, while the existing global compatibility object is
   preserved without authority;
7. all Stage 1 focused, causal/replay, run-path, invariant, and full offline
   suites pass with no broker mutation; and
8. every affected baseline fingerprint is repeated at close with an explicit
   delta ledger, while all thresholds and broker/capability contracts remain
   byte- or value-identical as applicable.

### 2. Stop conditions

Stop immediately if:

- any TTL, 500 ms drift limit, 50 ms future-skew tolerance, 5 second forward-gap
  limit, fusion hazard/attack threshold, strategy threshold, Risk, NetEdge,
  sizing, masking, reconciliation, or MarketTruthSnapshot rule must weaken;
- a second fusion, market-truth, Risk, portfolio, OMS, broker, or readiness
  authority would be created;
- a future observation must be clamped, absolute-valued, backdated, relabeled
  fresh, or silently discarded to obtain a green test;
- per-symbol isolation requires deleting or flattening an existing analytical
  module instead of moving its ownership into `SymbolRuntime` or indexing its
  existing owner;
- a raw candle start/close timestamp is reused as transport receipt time;
- tests require a fake broker response, fake fill, forced module output,
  threshold change, PAPER run, external dependency, runtime state edit, secret,
  or broker request;
- an affected restriction becomes `UNKNOWN`, a baseline fingerprint changes
  before its intentional Stage 1 edit, or another actor changes a scoped file;
- a scoped source starts importing or activating `SovereignExecutionGuard`, a
  live path, manual trade control, naked/short SELL, or a new subsystem;
- the same blocker recurs for three work cycles, a binary gate fails twice, or
  files outside this manifest enter the Stage 1 diff.

### 3. In-scope files

Planned production owners:

- `app/brain/signal_fusion.py` - keep the sole fusion authority and make its
  histories, as-of selection, hysteresis, telemetry, and last decision
  explicitly symbol-indexed;
- `app/symbol_runtime.py` - own existing per-symbol entropy, physical,
  persistent temporal-guard, latest assessment, and latest fusion state;
- `app/main_loop.py` - pass explicit symbol/source/event/receipt/decision clocks,
  remove primary-symbol evidence borrowing, use candidate topology, and consume
  the persistent guard assessment;
- `main.py` - route each trade once and remove the active global whale/fusion
  write while preserving the compatibility object;
- `app/risk/stale_data_guard.py` - use receipt minus exchange time for transport
  drift, retain persistent state, expose deterministic assessment evidence, and
  name broken-clock conditions without changing limits;
- `app/risk/pre_trade_guardrails.py` - consume a canonical assessment emitted by
  the existing persistent guard; never instantiate a guard at admission;
- `app/models/market_data.py` - carry the already-captured transport receipt
  timestamp on order-book truth without changing price/book semantics;
- `app/data/websocket_client.py` - preserve actual receive timestamps through
  book/candle callbacks instead of dropping them.

Planned proof/governance files:

- `tests/test_paper_true_capability_stage1.py` - Stage 1 causal, isolation,
  persistence, parity, restart, and mutation-surface proof;
- directly affected existing tests, limited to lawful fixture/contract updates
  where old intent instantiated an ephemeral guard or asserted the known global
  compatibility defect;
- `tests/fixtures/paper_true_capability_stage0.json` and
  `tests/test_paper_true_capability_stage0.py` - preserve original Stage 0 hashes
  and append/test an explicit approved Stage 1 source-delta ledger; never rewrite
  historical run evidence;
- this report, `CHECKPOINT_TRACKER.md`, and
  `reports/codex_handoff_latest.md` - entry, close, Board ruling, proof,
  limitations, and next boundary.

The source list may narrow after implementation. It may not expand beyond this
causal/per-symbol feature area without a fresh scout and scope-tripwire review.

### 4. Forbidden and unrelated files

Do not edit or stage UI/icon/launcher/cockpit files, broker adapters/gateways,
OMS/order routing, NetEdge, position sizing, exposure/inventory/reservations,
strategy thresholds, runtime/operator config, credentials, catalog/universe,
baseline policy, SELL/lifecycle logic, AI, cloud/AWS, tenant code, state, logs,
databases, screenshots, `reports/operator_perf/**`, old handoffs, proposal
packets, untracked audit scripts, or any Stage 2+ owner. No PAPER or live process
may be launched and no broker request is authorized.

### 5. Current branch, commit, and complete dirty-worktree record

Current branch is `master`; entry commit is
`e363f4b919d3ae52416278c810a87169ca7f1186` (`freeze paper true capability
stage 0 baseline`), already pushed before Stage 1.

Protected pre-existing files at entry, unrelated and not touched or staged:

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

No baseline tag/branch will be forced from this dirty tree. No clean, reset,
stash, prune, broad add, line-ending normalization, or protected-file workaround
is permitted.

### 6. Affected module truth map and one-owner authority graph

| Module/area | Current live-repo truth | Stage 1 classification and allowed authority | Planned disposition |
| --- | --- | --- | --- |
| `SignalFusion` | One global cache, external-evidence map, hysteresis state, telemetry map, and last decision; `fuse(candle.exchange_ts_ns)` | `WIRED_WITH_ROLE`, sole fusion authority; global state shape is commissioning scaffold | Index the existing authority by symbol; add deterministic as-of histories and causal provenance |
| `SymbolRuntime` | Owns book/candle/price, TPE, Shans, regime, toxicity, WhaleFlow, sentiment, and strategies, but not entropy, physical, stale guard, or last fusion | `WIRED_WITH_ROLE`, sole per-symbol mutable analytical-state container | Consolidate those existing analytical instances/state into this owner; no new subsystem |
| `SovereignHeartbeat._on_trade` | Updates global WhaleFlow + fusion, then calls both `on_trade` and `on_trade_with_whale`; one tick reaches symbol state twice | `COMMISSIONING_OR_TEST_SCAFFOLD`; transport callback only | Call the existing full per-symbol trade path once and use its returned alert for insider evidence |
| `MainLoop.on_order_book` | Per-symbol Shans/regime/TPE, but borrows primary candle volume and writes global fusion | Mixed: per-symbol wiring is valid; primary/global fallback is scaffold | Use the runtime's own candle and explicit symbol-indexed fusion lane; fail missing evidence honestly |
| `MainLoop.on_candle` | Per-symbol toxicity/whale, but global entropy/fusion and primary-symbol TPE Risk input; candle clock refreshes physical | Mixed: valid engines plus causal/global scaffolds | Use runtime entropy/physical/fusion/TPE; decision availability clock is distinct from candle identity |
| `EntropyDecoder` | Sophisticated stateful model, but one instance consumes all symbols | `WIRED_WITH_ROLE`; shared instance use is commissioning scaffold | Preserve model/math unchanged; instantiate one existing decoder per runtime |
| `PhysicalValidator` | Sophisticated exchange-health model, but global exchange history makes one symbol affect another | `WIRED_WITH_ROLE`; global active use is commissioning scaffold | Preserve model/math unchanged; instantiate one existing validator per runtime and feed real transport clocks |
| `InsiderSignalEngine` | Global object with explicit per-symbol state and monotonic admission | `WIRED_WITH_ROLE`, lawful shared keyed owner | Retain; pass explicit symbol/event/receipt provenance into fusion |
| `StaleDataGuard` | Quant-grade rolling monitor; pre-trade creates a fresh instance and compares decision/candle time to exchange time | `WIRED_WITH_ROLE` Risk contributor; recreation/clock use is commissioning scaffold | One persistent instance per runtime; pre-trade consumes its immutable assessment |
| `MarketTruthSnapshot` | Canonical executable candle/book freshness owner with source and timestamp checks | `PERMANENT_SAFETY_CONTROL`, sole executable market-truth owner | Preserve source and thresholds unchanged; never let StaleDataGuard override it |
| Pre-trade guardrails | Final hard Risk admission owner | `PERMANENT_SAFETY_CONTROL` | Preserve decision authority; replace only the stale contributor's input contract |
| Candidate TPE | Runtime computes per-symbol topology, but post-candle Risk reads primary TPE for every symbol | `COMMISSIONING_OR_TEST_SCAFFOLD` around a valid quant contributor | Supply the current candidate runtime's TPE; Risk remains final owner |
| Legacy global Shans/regime/entropy/physical/whale references | Retained for old/dormant compatibility surfaces | `PRESERVED_COMPATIBILITY`, no active multi-symbol decision authority | Preserve, visibly de-authorize in the active path, do not delete |
| Rejected `app/execution/orchestrator.py` | Preserved rejected implementation uses the legacy two-argument fusion API | `REJECTED-PRESERVED`, no runtime authority | Keep API-compatible default-symbol behavior; do not activate or edit it |

Authority after Stage 1 remains: MarketTruthSnapshot owns executable market
truth; `SignalFusion` owns fusion; `SymbolRuntime` owns per-symbol mutable
analytical state; StaleDataGuard contributes temporal risk evidence;
pre-trade/Risk owns admission; OMS/OrderRouter owns order lifecycle; Broker and
Reconciliation own acknowledged external truth. No authority is added.

### 7. Current-behavior evidence and restriction ledger

Named repo evidence:

- `SignalFusion.__init__`, `_ingest`, `fuse`, and `_issue_hard_veto` use global
  `_cache`, `_external_evidence`, `_state`, `_telemetry`, and `_last_fusion`.
- `QuantMath.temporal_discount` returns `1.0` for every `age_ns <= 0`.
- `SignalFusion.fuse` checks only `age_ns > ttl`; therefore a negative age is
  labeled `NATIVE_SIGNAL_FRESH`.
- Stage 0 preserved actual run examples: Shans age `-84,711,522,000 ns` and
  regime age `-95,000,000,000 ns`, both formerly labeled fresh.
- `MainLoop.on_order_book` reads `self._primary_runtime.last_candle` for every
  symbol and writes Shans/regime/physical into the global fusion cache.
- `MainLoop.on_candle` uses global entropy/fusion and later reads
  `self._primary_runtime.last_tpe_signal` for Risk/recalibration.
- `_append_stale_data_guard_evidence` constructs
  `StaleDataGuard(symbol=request.symbol)` on every candidate.
- `_pre_trade_stale_data_observation` uses snapshot creation versus candle close,
  conflating executable candle age with subsecond transport drift.
- Kraken captures `receive_ts_ns`; trade callbacks retain it, while book and
  candle canonical callbacks currently discard it.

| Restriction/defect | Exact owner | Classification | Stage 1 action |
| --- | --- | --- | --- |
| Global fusion cache/hysteresis/evidence/last result | `SignalFusion` | `COMMISSIONING_OR_TEST_SCAFFOLD` | Replace active global shape with symbol-indexed lanes in same owner |
| Duplicate global and per-symbol WhaleFlow writes | `SovereignHeartbeat._on_trade` | `COMMISSIONING_OR_TEST_SCAFFOLD` | Remove active duplicate path; preserve global object without authority |
| Primary candle volume for all Shans/regime updates | `MainLoop.on_order_book` | `COMMISSIONING_OR_TEST_SCAFFOLD` | Use same runtime's candle only |
| Global entropy and physical model state | `MainLoop` constructor/callers | `COMMISSIONING_OR_TEST_SCAFFOLD` | Move existing instances into `SymbolRuntime` |
| Primary TPE for every candidate | `MainLoop.on_candle` | `COMMISSIONING_OR_TEST_SCAFFOLD` | Use candidate runtime's TPE |
| Ephemeral stale guard | pre-trade guardrails | `COMMISSIONING_OR_TEST_SCAFFOLD` | Persistent runtime contributor, same Risk owner |
| Candle age treated as 500 ms transport drift | main-loop/pre-trade bridge | `COMMISSIONING_OR_TEST_SCAFFOLD` | Separate transport assessment from MarketTruthSnapshot freshness |
| Fusion TTLs/half-lives/hazard gates | `SignalFusion` | `QUANT_OR_ECONOMIC_CONTROL` | Retain exact values |
| Temporal drift/future/gap/statistical limits | `StaleDataGuard` | `QUANT_OR_ECONOMIC_CONTROL` | Retain exact values; correct clock dimensions only |
| MarketTruthSnapshot freshness | `app.core.market_snapshot` | `PERMANENT_SAFETY_CONTROL` | Preserve unchanged |
| Risk/NetEdge/sizing/OMS/reconciliation | existing authority graph | `PERMANENT_SAFETY_CONTROL` | Preserve unchanged |
| PAPER endpoint/account pin/arming | supervisor/credential authorities | `GOVERNANCE_OR_ARMING_CONTROL` | Preserve unchanged and out of scope |

There is no `UNKNOWN` restriction in the affected Stage 1 ledger.

### 8. Baseline fingerprints before implementation

Source SHA-256 at entry:

| File | SHA-256 |
| --- | --- |
| `app/brain/signal_fusion.py` | `f24ff9b97572fc67fbf9d5a61f98f813f9b36fc475588b1e6e65ea6071450ce0` |
| `app/main_loop.py` | `822ea28bee27e4711900e8f6d46ca1ed2ea2f3901cfaa59845b06aa3dd37190d` |
| `app/risk/stale_data_guard.py` | `6b5364a0b765f85770db31796d7f00e978ff767905842d4c3266d2671d386aad` |
| `app/risk/pre_trade_guardrails.py` | `e6bd34aaf89b2ea56e479ed169d35da0854e62328cb268070125c572293c7793` |
| `app/symbol_runtime.py` | `7e721b8f4157dfdee3587d8a5e7f664f6f6b9d817fc2174f4e5eb9a6c6f5555c` |
| `main.py` | `403d205689940ed7e213708c4d48ffb84fa13ecd42f231593f73c7671d3267e7` |
| `app/models/market_data.py` | `08ff1c4dfac0503faa834d9f2faafd07bd9b7922cbaf9e32a99e2490acc4ada4` |
| `app/data/websocket_client.py` | `135de9e24b70aaac7f0c3c64d7e5b91985e1b5ff8e35256f9505522560267031` |
| `app/brain/physical_validator.py` | `0d404f7e85a38f3a10a768b2b6a37a3e6f7a6ccd0bf28ace4f60a0c39f5956b9` |
| `app/brain/entropy_decoder.py` | `ee0b904316cf24a86d990df8f3a8c3b31acac0bc2dab28f6b9ee6c565f6d1eb1` |
| `app/brain/insider_signal_engine.py` | `9665a2bf23f7402ef014013dda102dc2478c13ca2a9d478ab8c6ca94f7d708ff` |

Affected value fingerprints, all required unchanged at close:

- fusion TTL ns: whale `15,000,000,000`; Shans `15,000,000,000`;
  physical `30,000,000,000`; toxicity `30,000,000,000`; entropy
  `60,000,000,000`; insider `120,000,000,000`; regime `300,000,000,000`;
- fusion half-life ns: whale `5,000,000,000`; Shans `7,000,000,000`;
  insider `60,000,000,000`;
- missing-input penalty: `max(0.75, 1 - 0.05 * missing_count)`;
- hard fusion gates: toxicity `>= 0.88`; toxicity spike score `> 0.60` and
  velocity `> 0.15/s`; entropy `>= 0.95`; physical health `<= 0.15`;
- attack thresholds: base `0.72`, sustain `0.55`, insider urgency `>= 0.60`,
  Shans exhaustion `>= 0.80`; no strategy/profile threshold changes;
- StaleDataGuard: drift `500 ms`, window `1000`, warmup `50`, future skew
  tolerance `50 ms`, forward gap `5,000 ms`, z-score warning/high `2.0/3.0`,
  critical velocity `100,000,000 ns/s`, sigma limit `3.0`;
- MainLoop book processing interval `200,000,000 ns`;
- MarketTruthSnapshot default book policy `5,000 ms`; candle policy remains
  provider/config evidence, not replaced by StaleDataGuard;
- broker mutation owner/methods remain `OrderRouter`, `POST /v2/orders`, and
  `DELETE /v2/orders/{order_id}`; Stage 1 authorizes zero transport calls;
- Alpaca crypto capability remains declared `buy`/`sell_to_close`, while
  external adapter SELL stays blocked `only_buy_supported` until Stage 8;
- module-classification counts remain 397 total: 297 `WIRED`, 89 `BLOCKED`,
  10 `PRESERVED-DEAD`, 1 `REJECTED-PRESERVED`; no module is deleted or
  reclassified in this stage.

### 9. Mathematical and model inventory

#### Causal as-of fusion

For symbol `s`, channel `k`, and decision availability timestamp `T`, select:

`o*(s,k,T) = arg max(event_ts, receive_ts, deterministic_tie_break)`

over observations satisfying the conjunction:

`symbol == s`, `event_ts <= T`, and `receive_ts <= T`.

An observation with `event_ts > T` is `FUSION_CAUSAL_FUTURE_EVENT`; an
observation received after `T` is `FUSION_CAUSAL_NOT_YET_AVAILABLE`. A lawful
prior observation may still be selected; otherwise the channel follows its
unchanged criticality contract: missing critical physical/toxicity fails closed,
while missing non-critical evidence remains neutral with the unchanged missing
penalty. The rejected observation remains visible in telemetry.

TTL age remains `age_ns = T - event_ts`, never absolute-valued. Temporal decay
remains:

`discount(age,h) = 2 ** (-age / h)` for `age >= 0`.

`age < 0` is a named causal-integrity error, not `1.0`. Same-time evidence has
age zero and discount one. No half-life, TTL, weight, confidence formula,
toxicity modulation, entropy modulation, resonance term, Kelly boundary,
hysteresis threshold, or sleeve rule changes.

#### Temporal transport guard

Correct transport drift is:

`drift_ns = local_receive_ts_ns - exchange_event_ts_ns`.

It is not `decision_ts_ns - candle_close_ts_ns`. Arrival interval is the delta
between consecutive same-symbol transport receipt timestamps. Existing
kinematics remain:

- `velocity = delta(drift_ns) / delta(receive_time_seconds)`;
- `acceleration = delta(velocity) / delta(receive_time_seconds)`;
- jitter is population standard deviation over the rolling drift window;
- z-score, Shannon entropy of arrival intervals, skewness, micro-stalls, and
  uptime retain their existing estimators and warmup behavior.

The model remains deterministic and bounded by the existing 1000-sample numpy
window. Exchange regression, excessive forward gap, future event time, local
receipt after assessment time, and assessment-clock regression fail closed with
named evidence. No tolerance changes.

#### Per-symbol quantitative state

EntropyDecoder's state-family scores, exponential weighting, hysteresis,
coherence, magnitude, and confidence are unchanged; only instance ownership
becomes per symbol. PhysicalValidator's latency, toxicity, slippage, and health
formula remains `0.4*latency + 0.4*toxicity + 0.2*slippage`; only its history is
per symbol. Shans, regime, toxicity, WhaleFlow, sentiment, and TPE already have
per-symbol instances and retain their math.

#### Inputs, units, assumptions, uncertainty, and limitations

- Event, receipt, decision, and output/candle identity are signed integer Unix
  nanoseconds; latency ratios convert with `1e9 ns/s` and `1e6 ns/ms`.
- Decision availability time must be recorded, not invented in replay. The
  candle identity can remain its start timestamp for downstream same-candle
  contracts while fusion ages evidence against the recorded receipt/decision
  time.
- Exchange timestamps and local receipt clocks are assumed comparable enough
  for the existing 50 ms skew and 500 ms drift policies; Stage 1 does not
  recalibrate them.
- Fusion histories will be bounded inside the existing fusion owner to prevent
  multi-day memory growth. The bound is an operational retention capacity, not
  a trading threshold; eviction behavior must be deterministic and tested.
- Entropy and physical models have no new calibration source in this stage.
  Their existing constants and estimators are preserved exactly.
- Analytical/fusion/stale state is intentionally not trusted across process
  restart. A new runtime starts empty and fail-closed until real per-symbol
  observations warm it; Stage 1 will test this rather than persist stale
  analytical state as truth.
- No profitability, alpha quality, external fill, latency-to-Alpaca, or PAPER
  readiness claim can follow from Stage 1 offline tests.

### 10. Planned validation matrix

Positive tests:

- same-time and lawful prior same-symbol observations remain usable with exact
  unchanged decay and decision outputs;
- BTC and ETH can carry opposite WhaleFlow/Shans/regime evidence and produce
  independent fusion decisions, telemetry, hysteresis, entropy, physical, and
  last-decision state;
- a persistent guard reaches 50-sample warmup, retains nonzero kinematics, and
  contributes `ALLOW` without acquiring final Risk authority;
- a valid one-minute closed candle uses MarketTruthSnapshot freshness while a
  recent healthy transport assessment remains an allowed Risk contribution.

Negative/adversarial tests:

- future Shans, regime, whale, physical, toxicity, entropy, insider, and
  external evidence are refused with named causal reasons and never called
  fresh;
- same-symbol mismatches, missing symbol, future receipt, negative temporal
  discount age, stale drift, exchange future, exchange regression, forward gap,
  receipt-after-assessment, and assessment-clock regression fail visibly;
- no future observation can evict or override a lawful prior as-of value;
- no global whale/fusion write or duplicate runtime trade call survives the
  active callback;
- restart produces an empty fail-closed temporal/fusion state, not a fake warm
  state.

Temporal/property/replay/parity tests:

- interleaved and grouped cross-symbol event order yields byte-equivalent
  per-symbol decisions/reason codes;
- runtime and replay guard sequences serialize identically;
- permutations of future and lawful prior evidence preserve the same as-of
  result;
- selected provenance always satisfies nonnegative event and availability age;
- bounded histories do not mix symbols or grow without limit.

Run-path and compatibility tests:

- existing dispatch -> compile -> submit -> route -> mocked fill positive chain;
- existing moving-floor sell-to-close mocked submit chain;
- replay parity, upstream dispatch, decision frame, runtime admission,
  physical/market freshness, and risk-gate ordering suites;
- legacy default-symbol `SignalFusion` unit callers and rejected-preserved
  orchestrator imports remain compatible without active multi-symbol authority;
- Stage 0 invariants/fingerprints, with an explicit Stage 1 approved-delta
  ledger, then the full configured offline suite.

Performance/mutation audit:

- symbol/channel histories are bounded and lookup behavior is deterministic;
- no test transport may call POST, DELETE, broker GET, or any adapter mutation;
- source/AST assertions prove no broker mutation surface, threshold value,
  SovereignExecutionGuard activation, live path, or manual trade control enters
  the diff.

### 11. Proof and approval boundary

- Offline source/test/report/tracker/handoff edits: approved by Stage 1 Board
  direction and Sections 10/23.
- Local offline pytest/compile/import/performance checks: approved.
- Local backend/browser runtime: not required for this backend causal seam and
  not claimed unless later evidence makes it necessary without broker access.
- Broker read: not authorized in Stage 1.
- Bounded PAPER run or any broker mutation: not authorized.
- Live credentials/read/mutation/real money: forbidden.
- New dependency or subsystem: not authorized and not planned.
- Module deletion/reclassification: not authorized and not planned.
- State/log/database/credential edits: forbidden.
- Staging: exact scoped Stage 1 files only after validation; no protected or
  unrelated file may enter the index.

## Pre-Code Independent Red-Team

### In-Stage Scope Addendum - REST transport clock truth

Before editing `app/data/polling_client.py`, the 360-degree caller inspection
found a causal defect in the same Stage 1 feature area that was not visible in
the initial caller list. `PollingClient._fetch_order_book` captures
`response_received_ns`, but `_parse_order_book` drops it. The Kraken branch then
sets `exchange_ts_ns = now_ns()` even though Kraken depth levels carry source
timestamps. That makes receipt and event time approximately equal by local
construction, so the persistent guard can report healthy drift without source
clock truth. Leaving this active REST fallback unchanged would violate the
binary exit and create fake-green temporal evidence.

`app/data/polling_client.py` is therefore added to the exact production scope
before its first edit. Its entry SHA-256 is
`76fef7cb3ad11bbbcce8902cc1bc957e0e3b0bf9f6117da12df26823a5e6db5d`.
The owner remains the existing polling transport; no subsystem or authority is
added. Planned change: pass the already-captured response receipt into
`OrderBookSnapshot`, derive Kraken event time only from source level timestamps,
and reject a snapshot with no source timestamp rather than substitute local
wall time. Coinbase's existing authoritative response timestamp remains
unchanged. Existing 500 ms drift, market freshness, risk, and broker rules do
not move. Focused parser and callback tests are added to the Stage 1 matrix.

Scope-tripwire verdict: **PASS**. This is a necessary correction inside the
declared causal/transport seam, all dirty/protected files remain unchanged, and
no forbidden or Stage 2+ authority is involved.

### Degradation or flattening

Risk: per-symbol repair could replace sophisticated entropy, physical, fusion,
or stale analytics with a generic timestamp check.

Control: retain every existing model and formula. Move instances/state into the
existing `SymbolRuntime`, and add causal wrappers/provenance inside the existing
`SignalFusion`. No differentiator or threshold is removed.

### Bypass or weakened control

Risk: separating candle freshness from transport drift could be misused to skip
the stale guard.

Control: MarketTruthSnapshot remains the hard executable freshness authority;
the persistent StaleDataGuard remains a required main-loop Risk contribution.
Missing assessment on the active dispatch path fails closed. The correction
removes a unit/category error, not the 500 ms limit.

### Duplicate authority

Risk: putting last fusion or guard evidence on `SymbolRuntime` could make it a
second decision owner.

Control: runtime stores state/evidence only. `SignalFusion` remains the sole
fusion calculator and pre-trade/Risk remains the sole admission owner. Runtime
cannot route or mutate a broker.

### Fake proof

Risk: deterministic unit tests could be reported as runtime/PAPER capability.

Control: highest planned rung is local offline tests. No runtime, browser,
broker, fill, order, PnL, or readiness result will be inferred. Mocked fills
remain explicitly internal mocked proof.

### State loss and restart

Risk: moving state per runtime without persistence loses warm models on restart.

Control: analytical state was already non-canonical and unsafe to trust after a
gap. Restart intentionally begins cold/fail-closed and must warm from fresh
observations. Durable analytical recovery is not invented in this seam; the
limitation stays explicit.

### Hidden configuration or compatibility authority

Risk: the legacy primary symbol or config symbol could silently select the wrong
lane.

Control: every active MainLoop call passes symbol explicitly. Default-symbol
resolution exists only for existing single-symbol tests and the
rejected-preserved orchestrator, and a test will scan active calls for omissions.
Status will report symbol-indexed fusion rather than `signal_fusion_global`.

### Mathematical simplification or look-ahead

Risk: fixing negative ages by clamping to zero would preserve leakage.

Control: negative age raises/refuses with a named causal code. As-of selection
requires both event and availability timestamps no later than the decision.
Every selected input publishes signed ages and source provenance.

### A green test masking broken runtime

Risk: unit callers default to `config.symbol`, while production still writes a
global lane or discards actual receipt time.

Control: add active-call-site tests, callback behavior tests, WebSocket receive
propagation tests, real `SymbolRuntime` instance-isolation tests, run-path/replay
tests, and the full suite. Source tests alone are insufficient.

### Concurrency and ordering

Risk: per-symbol aliases inside one fusion object could race across callbacks or
out-of-order inputs could overwrite lawful history.

Control: symbol lanes and ingestion/fusion selection use one existing-owner
lock, bounded histories, deterministic as-of selection, and replay/permutation
tests. No mutable active-symbol alias may be observable outside the lock.

### Broker and lifecycle safety

Stage 1 does not change catalog, baseline, SELL, positions, reservations,
orders, adapters, OMS, reconciliation, run duration, Stop, or arming. No new
manual or automated broker mutation path exists. `SovereignExecutionGuard`
remains dormant.

### Red-team verdict

The plan survives red-team review only with the corrected design above: use
recorded decision availability time distinct from candle identity, require both
event and receipt time in the as-of predicate, retain MarketTruthSnapshot and
all thresholds, and fail cold after restart. There is no safety or go-live
disagreement requiring Board escalation at entry.

`STAGE_ENTRY_COVENANT: PASS`

## 1. Verdict

**PASS at the local offline test rung.** The active decision path now keeps
mutable analytical state per symbol, distinguishes event time from transport
receipt/decision availability time, performs deterministic same-symbol as-of
selection, and refuses future or not-yet-available evidence by name. The
existing MarketTruthSnapshot, Risk, NetEdge, sizing, OMS, reconciliation,
account, endpoint, and lifecycle authorities remain in place and retain their
thresholds.

The final configured offline suite passed `1858 passed, 14 skipped, 0 failed`.
This is not runtime, browser, broker-read, PAPER execution, external fill,
profitability, or arming proof. No broker authorization variable was enabled,
no broker request was made, and no PAPER or live process was started.

### Binary exit result

| Stage 1 exit | Result | Evidence |
| --- | --- | --- |
| Negative age cannot be fresh or receive discount `1.0` | **PASS** | `QuantMath.temporal_discount` raises `FUSION_CAUSAL_NEGATIVE_AGE`; causal acceptance tests cover future event and receipt clocks |
| Per-symbol mutable decision state is isolated | **PASS** | symbol-interleaving, instance-isolation, same-symbol-only runtime, and active-call-site tests |
| Fusion is deterministic and causal as of decision time | **PASS** | event and receipt must both be `<= decision_ts_ns`; future evidence is named and excluded/refused |
| One persistent temporal guard per runtime contributes to Risk | **PASS** | runtime persistence/replay tests and pre-trade contract tests; active-path missing assessment fails closed |
| Market freshness and transport drift remain separate | **PASS** | MarketTruthSnapshot remains unchanged; transport assessment uses receipt minus exchange time |
| Duplicate/global active trade evidence write is removed | **PASS** | callback tests prove exactly one per-symbol trade route; compatibility objects remain de-authorized |
| Focused, run-path, compatibility, invariant, and full offline suites pass | **PASS** | `64`, `116`, `122`, `130`, `6`, and final `1858` passing test results recorded below |
| Affected source fingerprints and unchanged controls are accounted | **PASS** | close hashes below plus Stage 0 `approved_source_deltas.stage1`; invariant/value tests pass |

## 2. Files Changed

Production owners:

- `app/brain/signal_fusion.py` - symbol-keyed bounded histories, explicit
  event/receipt/decision provenance, deterministic as-of selection, per-symbol
  hysteresis/telemetry/last-result state, concurrency serialization, and named
  causal refusals inside the existing fusion owner.
- `app/symbol_runtime.py` - one existing EntropyDecoder, PhysicalValidator, and
  persistent StaleDataGuard instance per symbol, with latest assessment/fusion
  evidence stored but no new decision authority.
- `app/risk/stale_data_guard.py` - separate exchange, receipt, and assessment
  clocks; persistent kinematics; current-sample z-score; named clock failures;
  unchanged transport limits.
- `app/risk/pre_trade_guardrails.py` - consumes the runtime's canonical temporal
  assessment and fails closed when it is missing on the active main-loop path;
  it no longer recreates a guard at admission.
- `app/models/market_data.py` - carries order-book receipt time without changing
  book or price semantics.
- `app/data/websocket_client.py` - propagates captured receipt/provider clocks
  through book, candle, and trade contracts.
- `app/data/polling_client.py` - propagates the REST response receipt clock;
  Coinbase retains its source response time and Kraken derives source event time
  from level timestamps or rejects the snapshot when none exists.
- `app/main_loop.py` - routes candidate-symbol state and clocks through the
  existing owners, removes primary-symbol evidence borrowing, consumes the
  persistent temporal assessment, and exposes last fusion per symbol.
- `main.py` - routes a trade exactly once through the complete per-symbol path;
  the legacy global compatibility objects are preserved without active
  multi-symbol authority.

Proof files:

- `tests/test_paper_true_capability_stage1.py` - new causal, isolation,
  persistence, replay, parser, active-call-site, invariant, and mutation-surface
  acceptance coverage.
- `tests/fixtures/paper_true_capability_stage0.json` and
  `tests/test_paper_true_capability_stage0.py` - retain every original Stage 0
  fingerprint and add a separately named, covenant-bound Stage 1 delta ledger.
- Sixteen existing affected test modules received only contract/fixture updates
  needed to supply explicit symbol identity, real temporal assessments, or a
  decision clock no earlier than their native evidence.
- This report, `CHECKPOINT_TRACKER.md`, and
  `reports/codex_handoff_latest.md` close the governed record.

No state, log, secret, database, screenshot, old handoff, proposal packet, or
untracked audit script belongs to this stage or its staging recommendation.

## 3. Root Cause

The decision path had four coupled commissioning defects:

1. `SignalFusion` held one global cache, hysteresis state, telemetry map, and
   last decision, so interleaved symbols could overwrite or influence one
   another.
2. Fusion freshness used signed `decision - signal` age but treated every
   nonpositive value as maximally fresh. A future-dated event therefore received
   temporal discount `1.0` instead of being refused.
3. Several active callers used event identity as though it were receipt or
   decision availability time, dropped already-captured transport clocks, or
   borrowed primary-symbol state. That allowed look-ahead and cross-symbol
   contamination even when individual model math was correct.
4. Pre-trade admission instantiated a new StaleDataGuard per candidate and fed
   it candle-age-like values. Its rolling kinematics could not persist, and its
   500 ms transport-drift contract was conflated with MarketTruthSnapshot's
   executable market-freshness responsibility.

The advanced entropy, physical, toxicity, WhaleFlow, Shans, regime, topology,
fusion, MarketTruthSnapshot, and Risk systems were not the problem and were not
flattened. The defect was ownership, clock provenance, and active-path wiring.

## 4. Fixes Implemented

### Causal fusion

- Every observation records `symbol`, `source`, `event_ts_ns`,
  `received_ts_ns`, and deterministic ingestion sequence.
- Fusion selects only same-symbol observations whose event and receipt clocks
  are no later than the requested decision clock.
- Future event time reports `FUSION_CAUSAL_FUTURE_EVENT`; future availability
  reports `FUSION_CAUSAL_NOT_YET_AVAILABLE`; negative temporal age reports
  `FUSION_CAUSAL_NEGATIVE_AGE`; decision-clock regression reports
  `FUSION_DECISION_TIMESTAMP_REGRESSION`.
- A future critical observation cannot satisfy critical-signal presence; when
  no lawful prior critical observation exists, fusion hard-vetoes. Future
  noncritical evidence is missing/neutral and retains the existing missing-input
  penalty.
- Histories are bounded to `512` observations per symbol/channel while
  retaining the last lawful as-of anchor. This is an operational memory bound,
  not a strategy, TTL, Risk, or economic threshold.

### Per-symbol state and transport truth

- `SymbolRuntime` now owns the existing stateful analytical instances for its
  symbol. Fusion remains the sole fusion calculator and Risk remains the sole
  final admission authority.
- Trade callbacks update the per-symbol WhaleFlow path once. Candle callbacks
  no longer re-ingest the latest trade as a new whale observation.
- Same-symbol candle volume, regime, topology, physical, entropy, toxicity,
  whale, insider, strategy, and world-awareness evidence is passed with explicit
  provenance. Missing same-symbol regime is `UNKNOWN`, not borrowed.
- WebSocket and REST paths carry actual receipt time. Kraken no longer
  substitutes local wall time for an absent provider event timestamp.

### Persistent temporal Risk evidence

- Transport drift is `receive_ts_ns - exchange_ts_ns`; assessment time is a
  separate monotonic admission clock.
- The guard retains its rolling samples and derivatives per runtime. First
  derivatives remain zero until a prior sample exists; current-sample deviation
  is visible rather than computed against a window that excludes the current
  observation.
- Existing drift, future-skew, forward-gap, z-score, and velocity limits remain
  value-identical.
- The active main-loop pre-trade path cannot replace the assessment with a raw
  metadata map. Missing canonical evidence fails closed.

## 5. 360-Degree Adjacent Improvements

- The order-book model now preserves the receipt timestamp already known at the
  transport boundary, closing the same causal defect in both WebSocket and REST
  fallback paths.
- External attribution batches carry their maximum event and receipt clocks so
  a batch containing not-yet-available evidence cannot leak through an older
  wrapper timestamp.
- Fusion mutation and selection are serialized inside the existing owner; no
  mutable active-symbol alias escapes the lock.
- Compatibility defaults remain for single-symbol tests and the
  rejected-preserved orchestrator, but all active MainLoop calls pass symbol
  identity explicitly.
- The close red-team found and removed one unhappy-path process-global regime
  fallback. If a runtime's symbol-owned detector is unavailable, the active path
  now emits explicit `UNKNOWN` regime evidence rather than borrowing another
  symbol's detector state.
- The Stage 0 fingerprint fixture remains historical evidence rather than being
  rewritten. Its new delta ledger makes the three intentionally changed pinned
  sources auditable against this stage and covenant.

No universe, catalog, protected baseline, execution profile, SELL capability,
position lifecycle, run-duration ceiling, UI, launcher, AI, cloud, tenant, or
Stage 2+ behavior was changed.

## 6. Tests and Checks

Highest proof rung reached: **local offline tests**.

Final results on the Stage 1 source/test tree:

- scoped Python compile: **PASS**;
- Stage 1 acceptance plus native fusion and Seam 7E compatibility:
  **`64 passed`**;
- affected integration/guardrail suite: **`116 passed`**;
- explicit run-path gate covering deterministic end-to-end, replay parity,
  runtime dispatch admission, decision frame, Risk-gate ordering, upstream
  dispatch, and physical/market-freshness alignment: **`122 passed`**;
- fusion/runtime compatibility suite: **`130 passed`**;
- Stage 0 invariant/fingerprint suite after the delta ledger: **`6 passed`**;
- final Stage 0 + Stage 1 covenant/acceptance rerun after closing this report:
  **`38 passed, 72 warnings`**;
- final configured full suite: **`1858 passed, 14 skipped, 384 warnings,
  0 failed`** in `281.60s`.

The 14 skips remain conditional broker/access tests. They were not deleted,
stubbed, relabeled as passes, or enabled with authorization variables.

### Honest failure history

- The first post-report covenant rerun was `37 passed, 1 setup error` because
  pytest selected the inaccessible Windows user temp directory. It was not
  counted as proof. The identical command with workspace-local `--basetemp`
  passed `38`.
- The first affected-suite command used a fixed `C:\tmp` pytest base directory
  that this process could not create: `93 passed, 2 failed, 21 errors`. The 21
  ACL errors were an invalid harness result. The two failures were real stale
  Phase 3 fixtures; they were corrected and the valid rerun passed `116`.
- The first run-path rerun exposed eight fixtures that instantiated the former
  raw/ephemeral freshness contract. They were updated to provide the canonical
  runtime assessment; the final gate passed `122`.
- The first compatibility rerun was `126 passed, 4 failed`. Those fixtures
  omitted explicit symbol identity or chose a decision time earlier than native
  evidence; after lawful fixture correction the suite passed `130`.
- The first full suite was `1856 passed, 14 skipped, 2 failed`. One trade-through
  fixture lacked runtime temporal evidence and one whole-bot attribution fixture
  lacked symbol identity. Both were corrected; the final full suite passed.

### Assertion-intent relabel log

**NONE.** No test changed from expecting a reachable positive path to expecting
a refusal, or vice versa. No assertion was weakened or removed. Fixture changes
only raised inputs to the stricter current contract:

- raw or serialized freshness metadata became a real runtime-owned temporal
  assessment;
- implicit symbol identity became explicit symbol identity; and
- a fixture decision clock that preceded its native evidence moved to that
  evidence's latest lawful time.

Existing dispatch-to-mocked-fill and moving-floor sell-to-close positive paths
remain passing. Mocked fills are still labeled internal test proof and are not
reported as broker fills.

### Close fingerprints

| File | Close SHA-256 |
| --- | --- |
| `app/brain/signal_fusion.py` | `e33fad70026f29c86b6de21fc475250d194c86d9969966639725b869fec457bc` |
| `app/data/polling_client.py` | `49a8a335883d8b60270e0c4265ead7b809fe0534521b773b86c4b2f1a7aa5e24` |
| `app/data/websocket_client.py` | `8ed521fc4f6d518d11c2a4eddea461a1fb9b711536943702ccb7d943db8d911f` |
| `app/main_loop.py` | `cb37f160d59b7c60926f9272ec4be1cd17fa447d9677f397a4a1fa669f34667e` |
| `app/models/market_data.py` | `5595ce63166cdde9452a18783fe9a1c9f4e61d4037be73fbb62be5f75988827e` |
| `app/risk/pre_trade_guardrails.py` | `c8d2a2a8ca3717847cf19f7ecc8c81d6e7a67fe1c7e3dfe36e6a4f370bbc9a23` |
| `app/risk/stale_data_guard.py` | `6af78cf12915dc2fddb180dd5065a078049c01bcf759d2dbf3113805b1d79dfc` |
| `app/symbol_runtime.py` | `3a4bb5695745d5f13e922bdcc4f828167ebe96a822b1c892957b4891ed14104d` |
| `main.py` | `b55a5c447dac339d5f950e9fa0234df98111bde4d89f94bbdeba9c8cc3c211da` |

The unchanged PhysicalValidator, EntropyDecoder, and InsiderSignalEngine source
hashes and all numeric value fingerprints listed in the entry manifest remain
the same. The Stage 0 fixture's original `baseline_fingerprints.source_sha256`
object remains untouched. `approved_source_deltas.stage1` accounts for the
intentional `app/main_loop.py`, `main.py`, and pre-trade source changes against
entry HEAD and this report's covenant.

## 7. Browser, Runtime, and Broker-Read-Only Proof

- Browser proof: **NOT RUN; NOT CLAIMED**. This stage did not modify UI.
- Local backend/live-feed runtime proof: **NOT RUN; NOT CLAIMED**.
- Broker read-only proof: **NOT AUTHORIZED; NOT RUN**.
- Bounded PAPER execution: **NOT AUTHORIZED; NOT RUN**.
- Broker mutation/external order/fill/sell-to-close proof: **NONE**.
- Live credentials, live endpoint, real money: **NOT USED**.

The run-path tests prove wiring through mocked execution contracts only. They do
not prove current exchange timestamps, provider latency, production throughput,
external routing, fills, PnL, or profitability.

## 8. Self-Red-Team and Anti-Hallucination Check

- Duplicate authority: none added. SymbolRuntime stores keyed state/evidence;
  SignalFusion still owns fusion and Risk still owns admission.
- Fake readiness: none claimed. Test green does not set readiness, Start,
  broker-proof, or activation state.
- Hidden broker truth: broker and reconciliation owners were not edited, and no
  external truth was synthesized.
- Risk/economic weakening: none. MarketTruthSnapshot, Risk, NetEdge, sizing,
  OMS, reconciliation, TTLs, drift limits, and strategy thresholds stay intact.
- Mock/stale leakage: future event or receipt clocks are named refusals; Kraken
  missing source time rejects instead of using local wall time.
- Unhappy-path isolation: the post-code audit found a dormant-in-normal-startup
  global regime fallback. It was removed and source-tested before staging;
  missing per-symbol regime state now stays `UNKNOWN`.
- Flattening/deletion: no advanced model or module was deleted, genericized, or
  replaced. Compatibility objects and rejected-preserved code remain present.
- Tests versus runtime: tests prove the repaired contracts and active Python
  call graph. They do not prove a live exchange feed, process restart under load,
  broker I/O, or multi-day operation.
- State/restart: a restart intentionally begins analytical guard/fusion state
  cold and fail-closed. No fake durable warm state was introduced.
- Dirty tree: test execution modified known protected `state/**` files. Those
  files are not implementation evidence and will remain unstaged and untouched.
- What was inspected: scoped source/callers, contracts/models, affected tests,
  Stage 0 fingerprints, test collection/results, git diff/status, and official
  event-time/keyed-state references.
- What remains inference: expected live provider timestamp quality and runtime
  capacity are design inferences until separately proven.
- Unknown: real feed disorder/latency distribution, full runtime memory profile,
  crash/recovery behavior during a campaign, and external broker outcomes.

I did not summarize away the intermediate failures or skips, call mocked fills
real, claim module profitability, or call later-stage restrictions removed.

## 9. Safety Confirmation

**PASS.** No Sacred Safety Law, Quality Law, Risk/NetEdge/economic rule,
MarketTruthSnapshot freshness rule, sizing/masking authority, OMS/reconciliation
rule, account pin, PAPER/live endpoint lock, no-short/no-naked-SELL rule,
strategy threshold, or existing temporal limit was weakened.

No manual buy/sell/force control, live mode, real-money path, broker mutation,
hidden fallback, fake order/fill/PnL/TCA, external dependency, subsystem,
SovereignExecutionGuard activation, module deletion, credential access, or
secret exposure was introduced. The governed automated position lifecycle was
not touched.

## 10. Module Status

| Module/area | Close status | Lawful role |
| --- | --- | --- |
| SignalFusion | `WIRED_WITH_ROLE` | sole same-symbol causal fusion owner |
| SymbolRuntime | `WIRED_WITH_ROLE` | keyed mutable analytical-state container; no trade authority |
| EntropyDecoder | `WIRED_WITH_ROLE` | unchanged quant contributor, one instance per symbol runtime |
| PhysicalValidator | `WIRED_WITH_ROLE` | unchanged exchange-health contributor, one instance per symbol runtime |
| InsiderSignalEngine | `WIRED_WITH_ROLE` | preserved shared, internally symbol-keyed evidence owner |
| WhaleFlow/Shans/regime/toxicity/TPE | `WIRED_WITH_ROLE` | same-symbol contributors with existing math and thresholds |
| StaleDataGuard | `WIRED_WITH_ROLE` | persistent per-symbol temporal Risk evidence contributor |
| MarketTruthSnapshot | `PERMANENT_SAFETY_CONTROL` | sole executable candle/book truth and freshness owner |
| Pre-trade/Risk | `PERMANENT_SAFETY_CONTROL` | sole final admission authority |
| WebSocket/polling transports | `WIRED_WITH_ROLE` | source/event/receipt clock carriers; no decision authority |
| Legacy global analytical references | `PRESERVED_COMPATIBILITY` | de-authorized on active multi-symbol path; not deleted |
| Rejected orchestrator | `REJECTED-PRESERVED` | import/API compatibility only; not activated |
| SovereignExecutionGuard | `PRESERVED-DORMANT` | unchanged and not activated |

No affected module is silent or `UNKNOWN`.

## 11. Disagreements and Decisions

There is no unresolved safety or go-live disagreement in Stage 1.

I intentionally did not persist warm analytical state across process restart.
Doing so here would have created a new durability/validity authority without a
gap-reconciliation contract. Cold, fail-closed recovery is more truthful and is
recorded as a later operational design concern rather than faked as complete.

I also rejected adding Flink, Beam, a watermark service, or another streaming
subsystem. Their documented patterns informed the repair, but introducing one
would exceed this stage, duplicate current ownership, and require separate Board
approval. The existing owners can enforce the required causal contract.

## 12. Limitations and Unknowns

- Evidence stops at local tests; there is no browser/runtime/broker/PAPER rung.
- Identical symbol/source/event/receipt-clock duplicates use ingestion sequence
  as the final deterministic tie-break. Replay parity therefore assumes a
  stable source order for otherwise indistinguishable duplicates.
- An external-evidence batch uses conservative maximum event/receipt clocks. A
  single future record can make the whole batch unavailable rather than
  partially admitting it.
- Fusion history is bounded in memory but no production throughput, contention,
  or long-duration capacity benchmark was run.
- SignalFusion mutation/selection is locked, but concurrent same-symbol
  WebSocket/REST ordering through all upstream analytical engines was not
  stress-tested; those engines consume the callback order they receive.
- Analytical state is deliberately cold after restart and must warm from fresh
  observations before admission.
- Kraken order-book level timestamps may be older than expected and will now
  truthfully trip the existing transport guard; live-feed behavior is unproven.
- WebSocket candle-close and provider receipt semantics were validated from
  local contracts, not an external exchange session.
- Legacy global compatibility objects remain preserved/de-authorized rather
  than deleted.
- Fourteen conditional broker/access tests remain skipped. Existing Pydantic
  and timezone-naive datetime deprecation warnings remain visible.
- Stage 2+ restrictions remain: the commissioning universe, protected baseline,
  forced exploration profile, external SELL adapter limitation, five-day run
  ceiling, dynamic catalog, broker inventory consolidation, full economics,
  campaign recovery, and multi-tenant isolation are not changed here.
- No claim is made that every module will naturally fire, that trades will
  occur, or that the system is profitable.

## Research Used

Primary-source patterns reviewed:

- Apache Flink event-time/watermark documentation: event time is distinct from
  processing/arrival time, inputs may be out of order, and progress/completeness
  needs an explicit temporal rule:
  `https://nightlies.apache.org/flink/flink-docs-stable/docs/dev/datastream/event-time/generating_watermarks/`.
- Apache Flink keyed-state documentation: mutable state is scoped to a
  deterministic record key rather than shared across unrelated records:
  `https://nightlies.apache.org/flink/flink-docs-stable/docs/dev/datastream/fault-tolerance/state/`.
- Apache Beam's model documentation: event time and processing time are separate
  dimensions, and late/out-of-order data requires explicit window/trigger
  semantics: `https://beam.apache.org/documentation/basics/`.
- Microsoft Azure Stream Analytics temporal JOIN documentation: streaming joins
  require explicit temporal bounds rather than unbounded matching:
  `https://learn.microsoft.com/en-us/stream-analytics-query/join-azure-stream-analytics`.

Applied: distinct event/receipt/decision clocks, deterministic symbol keys,
bounded histories, explicit same-symbol temporal predicates, and named handling
for future/late evidence. Rejected: proprietary design copying, wall-clock
substitution, timestamp clamping/backdating, unbounded global state, a new
dependency, and a new watermark/stream-processing subsystem.

Safety/truth impact: the bot can no longer call future evidence fresh or let one
symbol's analytical state silently influence another, while every existing hard
trading and economic authority remains intact.

## 13. Exact Staging Recommendation

Stage exactly these 29 files, by explicit path only:

```text
app/brain/signal_fusion.py
app/data/polling_client.py
app/data/websocket_client.py
app/main_loop.py
app/models/market_data.py
app/risk/pre_trade_guardrails.py
app/risk/stale_data_guard.py
app/symbol_runtime.py
main.py
tests/fixtures/paper_true_capability_stage0.json
tests/test_decision_frame_orchestration_paper_exploration_alpha.py
tests/test_deterministic_end_to_end_harness.py
tests/test_integrated_paper_readiness.py
tests/test_operator_paper_baseline.py
tests/test_paper_true_capability_stage0.py
tests/test_paper_true_capability_stage1.py
tests/test_phase3_risk_gate_stress_proof.py
tests/test_phase_d_paper_readiness_truth.py
tests/test_physical_freshness_dispatch_alignment.py
tests/test_pre_trade_guardrail_constraints.py
tests/test_replay_parity_acceptance.py
tests/test_runtime_dispatch_admission_telemetry.py
tests/test_seam7e_strategy_fusion_runtime_wiring.py
tests/test_trade_through_readiness_harness.py
tests/test_upstream_dispatch_signal_submission.py
tests/test_whole_bot_active_edge_attribution.py
CHECKPOINT_TRACKER.md
reports/codex_handoff_latest.md
reports/completion/PAPER_TRUE_CAPABILITY_STAGE_1_REPORT.md
```

Do not stage protected `state/**`, `.pytest_tmp/**`, logs, credentials, secrets,
databases, screenshots, `reports/operator_perf/**`, old handoffs, proposal or
restriction-review packets, or untracked audit scripts. After exact staged-diff
checks, commit honestly and push `master`, then stop at the Stage 1 boundary.
Stage 2 is not opened by this report.
