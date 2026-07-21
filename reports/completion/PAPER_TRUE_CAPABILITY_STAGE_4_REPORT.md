# PAPER True Capability Stage 4 Report

Date opened: 2026-07-19 America/Chicago
Stage: 4 - Scalable execution-location market data and observe-only universe pipeline
Branch: `master`
Stage-entry HEAD: `6340bae4aff24d272f3ba4270c641d896de10278`
Board direction: Shan directed `ok. Proceed with stage 4` on 2026-07-19.
Close status: **IN PROGRESS - NO COMPLETION CLAIM**

## Stage-Entry Manifest

`AGENTS.md` v3, including Sections 23, 24, and 25, was re-read before any
Stage 4 source, test, configuration, schema, runtime, or operator-contract edit.
The Stage 3 report, current tracker, latest handoff, true-capability master plan,
feed/provider implementations, runtime callers, durable state owner, affected
tests, launcher defaults, and official market-data documentation were inspected.
This report is the first Stage 4 file edit.

### 1. Objective, binary exit, and stop conditions

Stage 4 replaces the active two-REST-calls-per-symbol-per-second commissioning
shape with a bounded two-tier pipeline. Alpaca execution-location data is the
only source eligible to become executable truth for Alpaca orders. Coinbase and
Kraken remain source/time-attributed cross-venue advisory evidence. The ranked
dynamic set remains observe-only throughout this stage.

The binary exit is exactly the master-plan gate:

> A synthetic full catalog runs for an offline soak with bounded memory,
> requests, queues, and log volume; all dynamic symbols remain observe-only.

Required exit properties:

1. breadth request count scales with batches rather than two calls per symbol;
2. deep monitoring always contains held, open-order, and lifecycle symbols;
3. request rate, concurrency, retries, backoff, circuit state, queues, retained
   samples, and failure history are typed, validated, bounded, and observable;
4. selected transport activation is confirmed before its data can be executable;
5. stale/failed executable transport is stopped and invalidated before routing
   can select or activate a fallback;
6. inability to activate an execution-location fallback fails executable truth
   closed; a logged candidate is never called an active transport;
7. Alpaca execution-location provenance is required for any executable callback;
8. Kraken/Coinbase evidence is explicitly advisory and cannot own
   `MarketTruthSnapshot`, limit price, NetEdge input, or order admission;
9. breadth ranking is causal, deterministic, uncertainty-aware, percentile and
   Pareto based, with no fixed weighted score and no trading threshold role;
10. immutable ranking snapshots carry catalog lineage, as-of time, observation
    cutoffs, membership reasons, minimum-residence state, and an integrity hash;
11. replay rejects future evidence and produces the same snapshot without
    survivorship or look-ahead leakage;
12. all dynamic candidates remain `OBSERVE_ONLY`; Stage 4 grants no entry,
    mutation, reservation, SELL, strategy, Risk, OMS, or broker authority; and
13. the exact final candidate passes focused, adversarial, replay, restart,
    performance/soak, mutation-audit, named run-path, full-suite, and Section 25
    review gates.

Hard stop conditions:

- keeping up would require relaxing freshness/TTL or dropping held/open-order
  monitoring;
- cross-venue prices would need to become executable or price an Alpaca order;
- a data ranking would become a replacement for NetEdge, Risk, sizing, strategy,
  capability, OMS, or broker truth;
- transport switching could leave the failed provider executable or two
  transports owning executable truth concurrently;
- request/queue/sample/log memory cannot be deterministically bounded;
- a Risk, NetEdge, economic, sizing, strategy, masking, stale/TTL, account-pin,
  no-short, no-naked-SELL, OMS, reconciliation, or mutation control must move;
- a real network/broker call, PAPER run, broker mutation, live action, new
  dependency, new subsystem, deletion, or protected-state edit becomes needed;
- any affected restriction remains `UNKNOWN`;
- an undeclared production file enters the diff; or
- the same blocker repeats three cycles or the binary exit fails twice.

### 2. Session boot and complete dirty-worktree record

Stage-entry branch and commit:

```text
master
6340bae4aff24d272f3ba4270c641d896de10278
```

Recent dependency history:

```text
6340bae build broker-canonical crypto capability universe
4b9b8ed consolidate broker inventory authority
f462356 require pre-close review loop
4453209 repair causal per-symbol decision state
```

Protected pre-existing modified files, not to edit or stage:

```text
state/override_log.jsonl
state/risk_state.backup
state/risk_state.json
state/risk_state.tmp
state/session_journal.jsonl
```

Protected pre-existing untracked files/directories, not to edit or stage:

```text
.pytest_tmp/
AGENTS.prev.md
POVERTY_KILLER_AUDIT_REPORT.txt
reports/codex_handoff_2026-06-02_operator_truth_sync_ai_router.md
reports/codex_handoff_2026-06-07_final_ai_provider_truth.md
reports/codex_handoff_2026-06-12_operator_control_plane_fast_synced.md
reports/codex_handoff_2026-06-20_p3n_24h_final_360.md
reports/codex_handoff_2026-06-21_p3or_funded_revalidation_blocked.md
reports/codex_handoff_2026-06-21_pk_ui1_operator_cockpit_build.md
reports/completion/PAPER_AUTONOMY_RESTRICTIONS_REVIEW.md
reports/completion/UI_NOVEL_OPERATOR_COCKPIT_BOARD_PACKET.md
reports/completion/UI_WORLD_CLASS_REDESIGN_PACKET.md
reports/operator_perf/
scripts/_paper_audit_common.py
scripts/audit_oms_shutdown.py
scripts/audit_paper_run.py
scripts/audit_safety_markers.py
```

The dirty tree matches the Stage 3 handoff. No packet is truncated, ambiguous,
or unsafe. No broker, runtime, browser, or network proof is authorized or needed
for this offline stage.

### 3. Declared scope and forbidden boundary

Planned production/configuration owners:

```text
app/config.py
app/data/feed_provider_router.py
app/data/polling_client.py
app/data/websocket_client.py
app/data/market_feeds.py
app/data/validators.py
app/market/capability_registry.py
app/state/state_store.py
app/operator_providers/registry.py
main.py
scripts/run_bounded_paper.ps1
```

Planned tests/evidence/governance:

```text
tests/test_paper_true_capability_stage4.py
tests/test_feed_provider_router_failover.py
tests/test_market_data_truth_stabilization_for_paper_readiness.py
tests/test_runtime_rest_feed_connectivity_and_latency_truth.py
tests/test_seam7g_market_truth_reconciliation_spine.py
tests/test_config.py
tests/test_state_store.py
tests/test_windows_powershell_paper_launch_authority.py
tests/fixtures/paper_true_capability_stage0.json
tests/test_paper_true_capability_stage0.py
reports/completion/PAPER_TRUE_CAPABILITY_STAGE_4_REPORT.md
CHECKPOINT_TRACKER.md
reports/codex_handoff_latest.md
```

Existing tests will enter the diff only if their fixture or assertion directly
encodes the corrected provider/transport contract. Every intent flip will be
logged before/after; positive execution-location and negative cross-venue twins
must survive. Newly discovered directly affected files require a scope amendment
in this report before edit.

Forbidden: strategy implementations; Risk, NetEdge, sizing, exposure, masking,
OMS, broker gateway/adapter/governor, reconciliation, account-pin, baseline,
lease, supervisor, UI, AI, and live-mode behavior; thresholds; protected
runtime/state/log/evidence files; external dependencies; new subsystems; module
deletion; real broker/data access; PAPER or live runs; manual/forced trades.

#### Pre-close scope amendment 1 - candle timestamp truth

Fresh adversarial review found that Alpaca minute-bar `t` is the bar-start time,
while `DataValidator.validate_candle` measures staleness directly from
`exchange_ts_ns`. The Stage 4 adapters also omitted the existing canonical
`Candle` close/receipt metadata. That combination would reject valid newly
closed one-minute bars under the unchanged 10-second stale threshold, and the
validator's negative-age behavior did not itself reject future/in-progress
data. This is an active Stage 4 runtime blocker, not Stage 5 strategy work.

`app/data/validators.py` is therefore added to the declared production scope
before editing. Its Stage-entry SHA-256 is
`b3471f80353ce0dd1c2b59364bae3fbea553c5143b1457f8c81d450cdee9cbbd`.
The permitted change is limited to validating a deterministic timeframe-derived
close timestamp, rejecting inconsistent/future/in-progress metadata, and then
applying the existing stale threshold from that close. No stale/TTL value or
admission owner may change. The Stage 0 approved-source chain, focused tests,
named run path, and full suite must include this source delta on the final
candidate.

### 4. Affected module truth map and one-owner authority graph

| Module/area | Live-repo truth at entry | Allowed Stage 4 role | Planned disposition |
|---|---|---|---|
| `FeedProviderRouter` | Selects descriptors deterministically, but Kraken/Coinbase are incorrectly executable for Alpaca and selection does not activate transport | Sole provider-selection and failover decision owner | Add Alpaca crypto stream/REST descriptors; classify cross-venue providers advisory; expose transport identity; retain fail-closed conflicts |
| `PollingClient` | Kraken/Coinbase fallback creates candle and book tasks for every symbol every second; DNS backoff and timestamp checks exist | Bounded REST transport owner | Preserve parsers/truth checks; add Alpaca batches, budgets, bounded workers/queues/history, 429/backoff/circuit metrics, and two-tier cadence |
| `KrakenWebSocketClient` | Bounded queue and strict timestamps; Kraken only | Cross-venue advisory stream adapter | Preserve and label advisory; add an Alpaca crypto adapter in the same transport module rather than a new subsystem |
| `MarketFeeds` | Intended central owner, but only startup-selects once and cannot switch; runtime bypasses it | Sole active market-data transport lifecycle and tier owner | Activate/stop/switch selected adapters atomically, invalidate truth before switch, maintain protected deep subscriptions, emit transport truth |
| `SovereignHeartbeat` | Duplicates WebSocket/polling thread ownership and only logs a fallback candidate while old transport remains | Runtime consumer of `MarketFeeds`; display/status owner only | Consolidate startup/stop into `MarketFeeds`; route only execution-location deep facts to executable callbacks; dynamic candidates remain observation-only |
| capability registry | Owns immutable broker catalog and execution-eligibility universe; no market-quality membership model | Existing derived-universe owner | Add immutable causal observation/ranking snapshot and hysteresis functions; never mutate broker catalog or own trade admission |
| `StateStore` | Persists immutable catalog/universe evidence with hashes | Durable fact persistence only | Persist/reload immutable market-data universe snapshots with hash/lineage checks; never rank or authorize |
| `DataConfig` | One 1-second polling interval and WebSocket queue size only | Typed operational policy owner | Add bounded breadth/deep cadence, batch, concurrency, request, circuit, queue, sample, residence, and candidate-capacity fields |
| launcher | Defaults executable crypto data to Coinbase/Kraken | Configuration transport only | Default to Alpaca execution-location stream then REST, with cross-venue advisory fallbacks visibly ordered |
| operator provider registry | Calls Coinbase executable truth and Kraken comparison without exact authority labels | Display/configuration description only | Correct descriptions; no provider or trading authority |
| MarketTruthSnapshot / NetEdge / Risk / sizing / OMS / broker / reconciliation | Existing downstream hard owners | Unchanged | Fingerprint and mutation-audit; no edit |

Authority chain after Stage 4:

```text
Broker catalog facts -> capability_registry eligibility (Stage 3 owner)
causal market observations -> capability_registry Pareto/rank snapshot (observe-only)
FeedProviderRouter -> selected provider descriptor
MarketFeeds -> confirmed active transport + breadth/deep subscriptions
Alpaca execution-location facts -> existing MarketTruthSnapshot validation
cross-venue facts -> advisory basis diagnostics only
MarketTruthSnapshot -> existing NetEdge -> existing Risk/sizing -> existing OMS
Broker acknowledgement -> existing reconciliation
StateStore -> immutable evidence persistence only
UI/operator registry -> display only
```

No second final decision owner is introduced.

### 5. Restriction ledger and removal burden

| Restriction/behavior | Exact owner/callers/purpose/current effect | Classification | Stage 4 disposition and replacement proof |
|---|---|---|---|
| Two REST calls per symbol per second | `PollingClient._poll_all_symbols`; `MarketFeeds` and `SovereignHeartbeat`; commissioning fallback | `COMMISSIONING_OR_TEST_SCAFFOLD` | Replace with provider batches plus fixed workers/queues and two cadences; request-scaling and soak tests required |
| Provider selection without transport switch | `main.SovereignHeartbeat._on_feed_truth`; logs candidate only | `COMMISSIONING_OR_TEST_SCAFFOLD` (broken implementation) | Move lifecycle into existing `MarketFeeds`; stop/invalidate old provider before confirmed activation; switch/failure tests required |
| Kraken/Coinbase executable for Alpaca prices | default descriptors and launcher; allowed wrong-venue execution truth | `COMMISSIONING_OR_TEST_SCAFFOLD` (wrong authority classification) | Make both advisory/reference for Alpaca; Alpaca stream/REST becomes execution-location owner; negative authority tests required |
| Bounded request/concurrency/queue/history/log budgets | absent in REST path; WebSocket queue partly bounded | `PERMANENT_SAFETY_CONTROL` | Add typed transport limits; never interpret them as trade thresholds |
| Freshness, TTL, timestamps, malformed/crossed-book rejection | validators, parsers, MarketTruthSnapshot | `QUANT_OR_ECONOMIC_CONTROL` | Retain unchanged or strengthen provenance; fingerprint and adversarial tests |
| Held/open-order/lifecycle deep priority | Stage 3 universe monitor membership; transport currently treats all equally | `PERMANENT_SAFETY_CONTROL` | Make non-evictable in deep set across churn/restart |
| Dynamic membership observe-only through Stages 5-11 | true-capability master plan and Section 24 | `GOVERNANCE_OR_ARMING_CONTROL` | Persist explicit `OBSERVE_ONLY`; never route candidate membership as entry authority |
| Minimum residence/hysteresis | absent | `QUANT_OR_ECONOMIC_CONTROL` (transport stability, not admission) | Add deterministic membership continuity with protected-symbol override; no trading threshold changes |
| Risk/NetEdge/sizing/OMS/broker/reconciliation guards | existing hard owners | `PERMANENT_SAFETY_CONTROL` / `QUANT_OR_ECONOMIC_CONTROL` | Retain and fingerprint; forbidden to edit |

There is no `UNKNOWN` restriction in the affected scope. The three scaffolds are
proven active by the inspected code paths: unbounded per-symbol task creation,
the explicit warning that active transport remains unchanged, and executable
provider descriptors/launcher defaults for non-Alpaca venues. Their replacements
remain inside the existing provider, transport, universe, and state owners.

### 6. Baseline fingerprints

Source SHA-256 at Stage 4 entry:

```text
app/config.py 72609f669eabbb248a910ee606dd1ecf9f855389fe73d91e1b862f21ac4e43a6
app/data/feed_provider_router.py c2e7bd46bb739a4b9d93efcd1e8a6d5bdf292f8272d735631997dd89a8afb544
app/data/polling_client.py 49a8a335883d8b60270e0c4265ead7b809fe0534521b773b86c4b2f1a7aa5e24
app/data/websocket_client.py 8ed521fc4f6d518d11c2a4eddea461a1fb9b711536943702ccb7d943db8d911f
app/data/market_feeds.py 6a2466c111ddc0237b5b87e4e3ba4ae489496758ecd015741e58ba8d6578b7b0
app/market/capability_registry.py d22f89019b9970488a3dcdc360023244388a40bfba6f6c041f69ff10b74e518c
app/state/state_store.py 3f8b3728521565ba8508f1dbefe7210d91583989320cdd0e3db0a1497b5b9495
app/operator_providers/registry.py 2a8453f7b1c1318c0cc8e27ba7d5d5456e71dbd43467fce830955160290d6bc7
main.py 8db1a78eb0a9c4907c7f14727c6fdd3f5b4029523148a76ac8bdcd5de793a67a
scripts/run_bounded_paper.ps1 75a2c9f1e54350a78e2f328810b79b6a414f99b8a41a02836a5729b04ed79383
```

Effective data/runtime defaults at entry:

```json
{"broker_mode":"paper","crypto_market_data_providers":[],"data":{"feature_window_fast":10,"feature_window_slow":50,"max_candles_per_symbol":1000,"polling_interval_seconds":1.0,"websocket_max_queue_size":10000,"websocket_ping_interval":30,"websocket_reconnect_delay":5},"market_data_providers":[],"shadow_read_only":false}
```

Provider capability baseline with credential presence represented only as a
boolean: Kraken and Coinbase are `executable_market_data`,
`execution_eligible=true`, `advisory_only=false`; `alpaca_market_data` covers
only equity/ETF and is `MISSING_ENTITLEMENT` plus `MISSING_TRANSPORT`.

Launcher baseline: both market-data defaults are the ordered literal
`coinbase_public,kraken_public`.

Unchanged authority/control fingerprints:

- Stage 0 standard/exploration threshold fingerprint remains exactly the frozen
  fixture; no threshold value or activation profile is in scope.
- Stage 3 immutable broker catalog/universe and dynamic capability contracts
  remain the capability authority; no static row gains execution authority.
- broker mutation surface remains outside Stage 4: adapter `submit_order` and
  `cancel_order`; router POST/DELETE surfaces; no Stage 4 transport accepts a
  trading endpoint or mutation method.
- module roles remain: MarketTruthSnapshot executable truth; Risk hard
  admission; OMS/OrderRouter lifecycle; Reconciliation fill/position truth; AI
  advisory; UI display. Stage 4 changes only market-data provider/transport and
  observe-only rank evidence roles.

### 7. Mathematical and model inventory

Stage 4 will not use `OpportunityRanker` because its fixed weighted score and
placeholder costs belong to Stage 7 and would create the wrong authority.

Planned observation inputs, all per-symbol and at or before snapshot `as_of_ns`:

- event/source/receive timestamps in nanoseconds;
- quote midpoint and cross-venue midpoint in quote currency per base unit;
- dollar volume and depth/capacity in quote-currency units;
- trade count as non-negative count;
- spread and basis in basis points;
- log returns as dimensionless values;
- listing age and observation continuity in seconds/fractions;
- broker minimum quantity, quantity increment, price increment, and minimum
  notional as exact positive `Decimal` values; and
- quote-currency fundability as broker/account evidence, never inferred price.

Planned estimators:

1. deterministic finite-sample quantiles with explicit interpolation;
2. symmetric winsorization using empirical 5th/95th percentiles before log
   dollar-volume/trade-count summaries;
3. median and median absolute deviation (MAD), with `1.4826 * MAD` as a robust
   scale estimate where the sample supports it;
4. spread/depth/impact summaries using medians and MAD rather than means;
5. realized robust volatility from causal log returns and explicit gap/jump
   diagnostics, with no annualization or calibration claim in this stage;
6. empirical desirability percentiles and nondominated Pareto fronts across
   completeness/clock, liquidity/capacity, continuity, volatility/jump, and
   basis diagnostics;
7. uncertainty from missingness, effective sample size, and robust dispersion;
   ranking uses Pareto front, uncertainty ordering, and median percentile only,
   never a fixed weighted sum; and
8. membership hysteresis/minimum residence applied after ranking as transport
   stability. Held/open-order/lifecycle symbols override eviction.

Assumptions and limitations at entry:

- market observations in Stage 4 proof are synthetic/replay only;
- cross-venue basis is diagnostic and cannot prove Alpaca executability;
- no profitability, edge, fill probability, market impact calibration, or
  optimal universe-size claim is made;
- finite samples can leave uncertainty high and must remain observable;
- `Decimal` owns broker increments and capacity boundaries; float math is
  limited to finite statistical diagnostics with explicit domain checks;
- NaN/Inf, future timestamps, non-positive prices, negative sizes/counts,
  malformed arrays, and missing lineage fail closed rather than score neutral;
- transport-capacity settings are operational resource limits, not relaxed
  freshness, economic, risk, or strategy thresholds.

### 8. Planned validation matrix

Positive:

- Alpaca execution-location stream activates; REST activates as actual fallback;
- 1, 6, 56, and larger catalogs batch deterministically;
- held/open/lifecycle symbols remain deep while ranked candidates churn;
- immutable snapshot persists/reloads and hashes/replays identically.

Negative/adversarial:

- cross-venue data cannot satisfy an execution-required request or executable
  callback;
- activation failure leaves no executable provider and no stale old transport;
- 429, timeout, DNS, disconnect, malformed JSON/schema, crossed book, future
  time, NaN/Inf, non-positive price, slow consumer, and queue saturation fail
  closed with bounded diagnostics;
- no secret appears in status, exception, report, or persisted snapshot.

Temporal/causal/property/replay:

- permutations with identical causal facts produce the same snapshot;
- observations after `as_of_ns` are rejected, not silently dropped into rank;
- prior membership uses only a prior snapshot; no future constituent leakage;
- percentiles/Pareto fronts remain deterministic under ties and missingness;
- malformed or non-finite numeric domains never become attractive rank values.

Restart/recovery/performance:

- persisted snapshot integrity/lineage/cutoff is verified on cold reload;
- minimum-residence state survives reload;
- failed transport is stopped before alternate activation;
- offline soak proves bounded requests, in-flight concurrency, queue high-water,
  sample/history retention, task count, memory proxy counts, and log events.

Safety/mutation/parity:

- mock session records GET-only data endpoints and zero broker/order mutation;
- named run-path tests remain green without converting a positive twin to
  refusal;
- Stage 0 fingerprints add only an explicit Stage 4 approved source delta;
- focused tests, affected suites, full offline suite, source/config scan, and
  Section 25 final-candidate rerun are mandatory.

### 9. Research used

Primary-source patterns inspected before design:

- Alpaca crypto historical bars: multi-symbol comma-separated requests, with
  response limit applying to total returned datapoints;
- Alpaca crypto real-time stream: authenticated crypto WebSocket with explicit
  trade, quote, order-book, and bar subscriptions;
- Alpaca market-data limits: account request limits return HTTP 429 when
  exceeded, so batching and explicit retry/circuit behavior are required;
- Alpaca latest crypto pricing/order-book surfaces: execution-location facts
  must retain Alpaca source and source time;
- QuantConnect universe guidance: minimum time in universe reduces churn, and
  held/open-order assets remain subscribed after ordinary universe removal.

Applied: batching, incremental deep subscriptions, minimum residence,
non-evictable protected symbols, provider/source timestamps, 429-aware budgets,
and explicit transport activation truth.

Rejected: copying a terminal design; treating API plan limits as trading
thresholds; cross-venue executable substitution; fixed weighted ranking;
unbounded all-symbol streaming; implicit retry forever; using asynchronous
universe selection with portfolio/order state as an unversioned side channel.

### 10. Proof and approval boundary

Authorized now: source/tests/docs/config/schema edits inside declared scope;
offline mocked/replay/soak tests; local syntax/import/test execution; exact
per-file staging, commit, and push after all gates.

Not authorized and not planned: real Alpaca or other provider requests; broker
read; PAPER run; broker mutation; browser claim; live credentials/action;
real-money enablement; dependency/subsystem addition; module deletion; risk or
threshold change; protected-state write/staging; Stage 5 work.

Proof ladder ceiling for Stage 4 is offline tests plus local runtime wiring under
mock transports. It cannot claim external market-data, broker-read, PAPER,
browser, fill, profitability, or endurance proof.

### 11. Pre-code independent red team

**Degradation:** A broad scan can starve held symbols, flood tasks/logs, or let
429 retries synchronize. Adjustment: separate breadth/deep cadence, protected
deep priority, fixed workers, bounded queues/history, exponential backoff with
jitter, and measurable high-water marks. Stop if freshness requires starvation.

**Bypass:** Calling Kraken/Coinbase a fallback could silently price Alpaca
orders. Adjustment: their descriptors become advisory and fail every
execution-required request; runtime callback routing checks execution-location
provenance. No compatibility fallback may restore executability.

**Duplicate authority:** A new scanner could become a second universe, NetEdge,
or Risk owner; reusing `SovereignThrottler` could mix data and order pacing.
Adjustment: ranking is added to the existing capability/universe owner and is
explicitly observe-only; `MarketFeeds` remains the existing transport owner;
execution throttling and every downstream owner stay untouched.

**Fake proof:** Router selection could pass while transport startup fails, or a
mock payload could be called broker truth. Adjustment: selection, activation,
and executable-truth states are distinct; tests assert stop-before-switch and
confirmed activation; all proof is labeled synthetic/offline.

**State loss:** In-memory hysteresis could reset and churn after restart, while
a cache could become a second authority. Adjustment: persist immutable,
hash-checked rank snapshots in `StateStore`; the capability owner recomputes and
validates, while storage never ranks or authorizes.

**Hidden configuration:** Hard-coded request counts or environment-only flags
could change behavior invisibly. Adjustment: all operational budgets live in
typed `DataConfig`, status exposes effective values, and launcher provider order
is explicit and tested. Immutable safety invariants remain code-enforced.

**Math simplification:** A one-line weighted score could hide missingness and
capacity. Adjustment: robust quantiles, median/MAD, causal checks, empirical
percentiles, Pareto fronts, uncertainty, and exact Decimal constraints; no
profitability or calibrated-impact claim.

**Green tests masking broken runtime:** Unit tests could call helpers while
`main.py` still starts its old direct clients. Adjustment: runtime must consume
the centralized owner, the old duplicate startup path must leave active
authority, and a local mocked lifecycle integration test must inspect the
actual `SovereignHeartbeat` wiring without starting a broker or network call.

**Stop control:** Stop immediately if two executable transports can overlap,
old provider data survives invalidation, dynamic candidates reach broker
admission, protected symbols can be evicted, a secret is observable, or any
forbidden owner must change.

The plan survives this red team with the adjustments above. No law, threshold,
assertion, authority, broker surface, or valuable quantitative module is being
weakened, deleted, flattened, or bypassed.

STAGE_ENTRY_COVENANT: PASS

## Implementation Record

### Scope amendment 1 and assertion-intent relabel log

The first affected-suite run after provider classification produced `8 failed,
40 passed, 6 errors`. The six errors were Windows permission failures creating
the default pytest temp directory and did not execute their test bodies; they
must be rerun with the governed repo-local base temp.

All eight failures were confined to `tests/test_feed_provider_router_failover.py`
and encoded the superseded assertion that Kraken/Coinbase public data could
satisfy an execution-required Alpaca market-data request. Production failed
closed exactly as the new contract requires. Before editing that test file, the
assertion-intent changes are recorded:

| Existing assertion intent | Before | After and justification |
|---|---|---|
| configured Kraken priority | Kraken selected as executable | Kraken selected only for `execution_required=False` advisory request; preserves priority test without wrong venue authority |
| Coinbase-before-Kraken order | Coinbase selected as executable | same ordering for advisory request only; add separate Alpaca-stream executable positive |
| degraded/crossed/duplicate Kraken fallback | Coinbase selected as executable fallback | Coinbase selected as advisory fallback; add Alpaca-stream-to-Alpaca-REST executable fallback twin |
| selection telemetry | executable Coinbase after Kraken failure | reference/advisory Coinbase after Kraken failure; activation truth is separately tested in `MarketFeeds` |
| telemetry mutation isolation | selected provider type equals executable | selected provider type equals reference and remains broker-disconnected; Alpaca positive covers executable type |
| Coinbase unsupported trade/ticker reasons | only unsupported type under execution request | retain only unsupported type under advisory request; separate execution request must additionally show advisory/non-executable refusal |
| initial REST protected-truth probe | cache candle/book while activation is pending and assert zero execution-consumer callbacks even after transport reports executable | seed the existing execution consumer with the complete protected book-then-candle state before any executable status; add a refusal twin proving a rejected seed aborts activation without a green flash. The old assertion encoded fake readiness and therefore contradicts current truth law. |

No positive reachability test is converted to refusal without a surviving
positive twin. The relabel raises fixtures to the corrected source-authority law;
it does not weaken an assertion, provider filter, timestamp check, or trading
gate.

### Scope amendment 2 and frozen-source assertion log

`tests/fixtures/paper_true_capability_stage0.json` and
`tests/test_paper_true_capability_stage0.py` will add an explicit `stage4`
approved-source delta after the Stage 4 production candidate is frozen. Before,
the test permits exactly the completed Stage 1-3 deltas and therefore correctly
rejects any Stage 4 source edit as unrecorded. After, it will require exactly the
eleven declared Stage 4 production/configuration files, their Stage-entry hashes,
their final hashes, the Stage-entry HEAD/covenant/report, and hash continuity for
every file shared with Stage 3. The unchanged baseline then walks Stage 1, 2, 3,
and 4 in order before comparing live file hashes.

This is a provenance extension, not a relaxed oracle: unknown files, missing
files, changed Risk/NetEdge/OMS sources, a wrong before hash, a wrong final hash,
or a missing covenant report still fails. The Stage 0 historical broker/run
records, thresholds, authority graph, mutation surface, and module counts remain
unchanged. No positive reachability assertion changes intent.

## Validation and Pre-Close Review

## Completion Record

### 1. Verdict

**PASS at the deterministic offline test rung.** Stage 4 meets its binary exit
gate on the frozen candidate rooted at Stage-entry HEAD
`6340bae4aff24d272f3ba4270c641d896de10278`:

- the exact binary soak covers 600 synthetic broker-catalog symbols for 20
  cycles;
- REST work is 13 batched GET jobs per cycle, 260 total, rather than 600
  per-symbol jobs per cycle;
- measured in-flight work remains at or below 4, queue high-water at or below 8,
  and failure/event histories at or below 7;
- all 600 symbols remain classified and visible, 16 occupy deep capacity (four
  protected plus twelve ranked candidates), every membership is
  `OBSERVE_ONLY`, and none has execution authority; and
- the full configured offline suite has zero failures.

This verdict does not claim a real provider connection, current market truth,
broker truth, PAPER readiness, a PAPER run, fill behavior, profitability,
latency, or multi-day endurance. Stage 5 is not opened by this report.

### 2. Files Changed

Production/configuration:

| File | Reason |
|---|---|
| `app/config.py` | Typed, relationship-validated transport capacity, cadence, timeout, circuit, and ranking controls |
| `app/data/feed_provider_router.py` | Alpaca stream/REST execution-location descriptors and cross-venue advisory classification |
| `app/data/market_feeds.py` | Central two-tier transport lifecycle, failover, protected truth, breadth/rank flow, bounded caches, and truthful status |
| `app/data/polling_client.py` | Batched Alpaca snapshots/books, shared rate budget, bounded workers/queue/history, retry/backoff/circuit, exact timestamps |
| `app/data/validators.py` | Verified bar-close semantics and future/in-progress refusal under the unchanged stale threshold |
| `app/data/websocket_client.py` | Authenticated Alpaca stream, acknowledged subscriptions, ordered channels, bounded queue, stateful reset/delta book |
| `app/market/capability_registry.py` | Immutable observations/rank snapshots, robust estimators, Pareto fronts, exact Decimal constraints, observe-only membership |
| `app/operator_providers/registry.py` | Truthful provider descriptions; no false cross-venue execution claim |
| `app/state/state_store.py` | Hash-checked immutable market-data universe snapshot persistence/reload |
| `main.py` | Alpaca runtime wiring to `MarketFeeds`, lifecycle-only callbacks, transport failure shutdown, status and governed stop ordering |
| `scripts/run_bounded_paper.ps1` | Explicit Alpaca execution-location provider priority before advisory sources |

Tests/evidence/governance:

| File | Reason |
|---|---|
| `tests/test_paper_true_capability_stage4.py` | Positive, negative, adversarial, temporal, restart, persistence, runtime-wiring, and soak proof |
| `tests/test_feed_provider_router_failover.py` | Corrected advisory/executable provider contract with surviving Alpaca positive twins |
| `tests/fixtures/paper_true_capability_stage0.json` | Exact approved Stage 4 source-hash delta for eleven production/configuration files |
| `tests/test_paper_true_capability_stage0.py` | Requires and validates the Stage 4 integrity delta without broadening accepted scope |
| `reports/completion/PAPER_TRUE_CAPABILITY_STAGE_4_REPORT.md` | Entry manifest, review loop, evidence, safety proof, and limitations |
| `CHECKPOINT_TRACKER.md` | Stage 4 close and out-of-scope test-isolation finding |
| `reports/codex_handoff_latest.md` | Exact continuation boundary; Stage 5 remains unopened |

No file was deleted. Protected `state/*`, `.pytest_tmp/`, logs, screenshots,
secrets, untracked audit scripts, and unrelated reports are excluded from the
staging recommendation.

### 3. Root Cause

At entry, the broker-derived Stage 3 universe could enumerate eligible Alpaca
crypto, but the runtime market-data path still had commissioning assumptions:

1. provider selection treated public Kraken/Coinbase data as if it could satisfy
   an Alpaca execution-required request;
2. the old REST lane created per-symbol work without a bounded shared provider
   budget, backpressure, or explicit circuit truth;
3. no authenticated Alpaca crypto stream owner implemented acknowledged dynamic
   subscriptions and stateful order-book deltas;
4. transport selection, actual activation, protected-symbol truth, and runtime
   liveness were not one coherent lifecycle;
5. market breadth had no causal, immutable, robust, observe-only ranking owner;
6. restart could not restore a lineage-checked ranking snapshot; and
7. minute-bar start time could be misread as freshness time, rejecting a valid
   newly closed bar or accepting inconsistent future metadata.

The restriction was infrastructure incompleteness, not Risk, NetEdge, sizing,
strategy, or OMS strictness. Those owners did not need to move.

### 4. Fixes Implemented

1. `FeedProviderRouter` now has explicit `alpaca_crypto_stream` and
   `alpaca_crypto_rest` execution-location providers. Kraken/Coinbase remain
   public advisory/reference sources and fail every execution-required request.
2. `BatchedAlpacaPollingClient` issues bounded multi-symbol snapshot and book
   requests through one reusable request budget, fixed concurrency, a bounded
   job queue, capped histories, retry/backoff, Retry-After handling, and a
   single-probe half-open circuit.
3. `AlpacaCryptoWebSocketClient` proves greeting, auth, and the full subscription
   acknowledgement before activation; orders each channel independently;
   applies reset/incremental/size-zero book semantics; and terminates authority
   on overflow, malformed truth, or subscription failure.
4. `MarketFeeds` starts one executable transport at a time, stops the prior
   generation before fallback, requires complete current protected truth before
   executable activation, purges stale generations, and propagates terminal
   transport or execution-consumer refusal to the runtime shell.
5. Breadth and deep lanes are separate. Held, open-order, and lifecycle symbols
   are non-evictable. Dynamic symbols can contribute observations but remain
   explicitly observe-only and cannot enter runtime execution callbacks.
6. `build_market_data_universe_snapshot` uses causal observations, finite-sample
   quantiles, symmetric winsorization, median/MAD, exact Decimal broker
   constraints, worst-component clock quality, empirical percentiles,
   nondominated Pareto fronts, uncertainty ordering, and residence hysteresis.
   It does not introduce a simplified weighted score or profitability claim.
7. Immutable rank snapshots carry broker-catalog, broker-universe, role, time,
   and content-hash lineage. `StateStore` strictly persists/reloads them and
   rejects tampering, future creation, role mismatch, and relational corruption.
8. `SovereignHeartbeat` uses the centralized owner for Alpaca, retains legacy
   feed clients for the internal harness, exports transport/breadth/deep/
   lifecycle truth, cancels and joins market data before closing durable state,
   and stops without flattening if executable market-data authority is lost.
9. Bar validation derives a verified close timestamp from timeframe metadata,
   rejects future/in-progress/inconsistent facts, and then applies the existing
   unchanged stale threshold.

### 5. 360-Degree Adjacent Improvements

- Callback acceptance is now a truth-bearing return value; a downstream
  consumer cannot silently reject protected truth while transport stays green.
- REST non-JSON error bodies retain HTTP status and headers, so a 429 cannot
  hide its Retry-After evidence behind JSON decoding failure.
- Cross-venue advisory ingress rejects future source or receipt timestamps and
  cannot repair missing Alpaca execution truth.
- Incomplete and stale catalog members remain explicit in
  `unranked_symbols`; silence no longer looks like an attractive zero metric.
- The rank as-of clock is pinned once per snapshot, making replay independent of
  loop iteration timing.
- Book capacity uses the thinner side and exact rounded-up quantity/price
  increments instead of averaging away one-sided illiquidity.
- Operator/provider copy states that cross-venue producers are not currently
  wired, preventing a diagnostic descriptor from looking like live evidence.

### 6. Tests and Checks

All commands below ran on the frozen source/test/config candidate after the
Stage 0 hashes were refreshed:

| Gate | Exact result | Proof rung |
|---|---|---|
| Scoped `py_compile` | PASS, 14 Python files, 0 errors | Syntax |
| Final focused Stage 4/provider/runtime lifecycle | `135 passed`, `0 failed`, `72 warnings` in 15.59s | Logic and mocked wiring |
| Final compatibility set | `26 passed`, `0 failed`, `85 warnings` in 10.04s | Logic/regression |
| Stage 0-4 covenant set | `251 passed`, `0 failed`, `100 warnings` in 21.21s | Integrity/logic |
| Named seven-file run path | `119 passed`, `0 failed`, `78 warnings` in 11.11s | Offline e2e/run path |
| Exact 600-symbol binary soak node | `1 passed`, `0 failed`, `72 warnings` in 8.51s | Offline capacity/authority |
| Full configured offline suite | `2084 passed`, `14 skipped`, `0 failed`, `420 warnings` in 205.61s | Full local regression |
| Explicit skip-bearing subset with reasons | `54 passed`, `14 skipped`, `0 failed`, `78 warnings` in 7.76s | Skip-mechanism audit |
| `git diff --check` | PASS; only CRLF/LF conversion warnings | Diff hygiene |
| Added skip/xfail scan | zero additions | Test integrity |
| Deleted-file scan | zero deleted files | Preserve-first |
| New import scan | standard library plus existing project imports only | Dependency safety |
| Risk/OMS/execution-owner diff scan | zero changed files in those owners | Control fingerprint |
| Added mutation-token scan | only `...NO_FLATTEN`; no submit/cancel/POST/DELETE/order endpoint | Broker-mutation audit |
| Secret/private-key marker scan | zero findings | Secret safety |

Named run-path files, all passing:

- `tests/test_decision_frame_orchestration_paper_exploration_alpha.py`
- `tests/test_deterministic_end_to_end_harness.py`
- `tests/test_integrated_paper_readiness.py`
- `tests/test_phase3_risk_gate_stress_proof.py`
- `tests/test_replay_parity_acceptance.py`
- `tests/test_runtime_dispatch_admission_telemetry.py`
- `tests/test_upstream_dispatch_signal_submission.py`

The 14 skips were inspected individually and are not counted as passes:

| Class | Count | Current mechanism and disposition |
|---|---:|---|
| Board-gated Alpaca PAPER read | 7 | Conditional skip requires `PK_BOARD_AUTHORIZED_PAPER_BROKER_READ=YES_D4_BOARD_AUTHORIZED`; preserved |
| Broker-mutation approval absent | 3 | Conditional skip states no POST/mutation approval; preserved |
| Legacy read-only network probe unavailable | 4 | Conditional `URLError` skip; external truth remains unproven |

### 7. Browser, Runtime, and Broker Proof

- Browser proof: **NOT RUN**. Stage 4 changes no UI and makes no browser claim.
- Real process/runtime proof: **NOT RUN**. Runtime lifecycle is proven only by
  deterministic local tests and mocked transports.
- External market-data proof: **NOT RUN**. No provider network request was
  authorized or made for Stage 4.
- Broker read-only proof: **NOT RUN**. Current account, position, and open-order
  truth are not claimed.
- PAPER/broker mutation proof: **NOT RUN and not authorized**. No PAPER process,
  order POST, cancel, liquidation, manual trade, or real-money action occurred.

### 8. Self-Red-Team and Anti-Hallucination Check

What was actually inspected: every changed production/test/fixture file; active
router, stream, REST, `MarketFeeds`, rank, persistence, runtime startup/status/
shutdown, launcher-default, callback, and fallback paths; test fixtures and
intent relabels; skips; imports; mutation markers; secret markers; exact source
hashes; scope; and the staged-file plan.

What tests prove: deterministic parsing, validation, batching, rate limits,
circuit concurrency, backpressure, cancellation, auth/subscription handling,
book deltas, causality, robust ranking, persistence/restart, protected-symbol
priority, observe-only isolation, mocked runtime wiring/shutdown, unchanged run
path, and bounded synthetic full-catalog behavior.

What remains inference or unknown: real Alpaca payload/entitlement behavior,
network latency and disconnect characteristics, real catalog throughput,
multi-day memory/CPU/DB growth, provider clock quality, live cross-venue basis,
and downstream trading performance. Tests do not upgrade any of those unknowns.

No failure was summarized away. Earlier results invalidated by later edits are
listed in the pre-close record. No independent reviewer is claimed; this was a
fresh adversarial self-review. One out-of-scope test-isolation defect was found
after full-suite execution and is preserved/logged rather than hidden.

### 9. Safety Confirmation

- PAPER-only/live/real-money/account-pin controls are unchanged.
- Risk, NetEdge, sizing, strategy, stale/TTL values, masking, OMS, broker
  gateway/adapter/governor, reconciliation, no-short, and no-naked-SELL owners
  are unchanged.
- Operational data-transport capacities were added; no trading/economic/risk
  threshold moved.
- Dynamic market-data membership is hard observe-only and grants no dispatch,
  order, reservation, or broker authority.
- Cross-venue data is advisory and cannot satisfy Alpaca executable truth.
- Loss of executable market-data truth ends the run loop with an explicit
  no-flatten reason. It does not close, cancel, liquidate, or manually sell.
- No source/test module was deleted; advanced logic is preserved or upgraded.
- No external dependency, secret, manual trade control, live behavior, or
  broker mutation was added.

### 10. Module Status

| Module | Status | Role/evidence or blocker |
|---|---|---|
| `FeedProviderRouter` | WIRED | Sole provider selection/failover owner; executable/advisory twins pass |
| `BatchedAlpacaPollingClient` | WIRED | Bounded Alpaca REST breadth/deep fallback; batching/circuit/soak tests pass |
| `AlpacaCryptoWebSocketClient` | WIRED | Primary Alpaca execution-location stream; auth/subscription/book/backpressure tests pass |
| `MarketFeeds` | WIRED | Sole transport activation/lifecycle owner; failure, stale, recovery, callback tests pass |
| `MarketBreadthObservation` and `MarketDataUniverseSnapshot` | WIRED, OBSERVE_ONLY | Diagnostic/rank evidence only; causal/Pareto/replay tests pass |
| `StateStore` rank persistence | WIRED | Storage owner only; strict reload/tamper/restart tests pass |
| `DataValidator` close-time path | WIRED | Existing freshness authority with corrected close metadata; future/stale tests pass |
| `SovereignHeartbeat` integration | WIRED | Alpaca starts centralized owner; internal harness retains legacy path; lifecycle tests pass |
| Kraken/Coinbase provider descriptors | WIRED, ADVISORY_ONLY | Selection/parse diagnostics only; execution-required refusal tests pass |
| Production cross-venue observation producer | BLOCKED_WITH_REASON | No active caller invokes `record_cross_venue_advisory`; Stage 4 does not fake basis evidence |
| Dynamic-symbol execution activation | BLOCKED_WITH_REASON | Deliberately observe-only until later activation stages prove full decision-path authority |
| Legacy Kraken/Polling clients | PRESERVED and WIRED for internal harness | Not allowed to replace Alpaca executable truth |

No in-scope module is silent or presented as more active than its call path.

### 11. Disagreements and Alternative Judgment

There was no safety or go-live-gating disagreement with the Board packet.
Engineering judgment differed from a naive all-symbol stream: streaming every
catalog member would create uncontrolled subscription and event pressure.
Stage 4 instead implements bounded breadth batches plus protected/ranked deep
subscriptions while retaining every catalog symbol in classified observations.

The full suite exposed an existing governance-test isolation problem:
`tests/test_g0_hook_verification.py` calls `.claude/hooks/pre_tool_use.py`, whose
`log_override_attempt()` appends to the fixed protected path
`state/override_log.jsonl`. Exactly eight audit records were added by the full
suite. The records are preserved and excluded from staging. Fixing that hook/test
belongs to its governance owner and would require a new scoped seam; changing it
inside frozen Stage 4 would violate scope and invalidate the candidate.

### 12. Limitations and Unknowns

1. No real provider, runtime process, browser, broker read, PAPER run, order, or
   fill was exercised.
2. Pareto sorting is quadratic in catalog size and runs on the feed event loop.
   The deterministic 600-symbol test passed, but real sustained CPU latency is
   unmeasured.
3. A synchronous callback timeout can detect an overrun only after that callback
   returns; it cannot preempt a permanently hung synchronous callback.
4. Repeated 15-second breadth snapshots may repeat the same minute-bar values;
   robust medians tolerate repeats, but no claim of independent samples is made.
5. Snapshot DB retention/compaction is not implemented in Stage 4; multi-day
   storage growth is unknown and belongs to the archive/retention stage.
6. Cross-venue adapters/descriptors exist, but no production producer currently
   supplies advisory observations. Missing basis remains explicit uncertainty.
7. External provider limits, entitlements, symbols, schemas, timestamp quality,
   and reconnect behavior remain unproven.
8. The eight protected override-log records prove an existing test-isolation
   defect. The file remains dirty, preserved, and unstaged.
9. Existing Pydantic and `datetime.utcnow()` deprecation warnings remain; they
   did not fail this stage and were not broadened into unrelated cleanup.

### 13. Exact Staging Recommendation

Stage exactly these 18 paths, individually:

```text
app/config.py
app/data/feed_provider_router.py
app/data/market_feeds.py
app/data/polling_client.py
app/data/validators.py
app/data/websocket_client.py
app/market/capability_registry.py
app/operator_providers/registry.py
app/state/state_store.py
main.py
scripts/run_bounded_paper.ps1
tests/test_paper_true_capability_stage4.py
tests/test_feed_provider_router_failover.py
tests/fixtures/paper_true_capability_stage0.json
tests/test_paper_true_capability_stage0.py
reports/completion/PAPER_TRUE_CAPABILITY_STAGE_4_REPORT.md
CHECKPOINT_TRACKER.md
reports/codex_handoff_latest.md
```

Never stage the five protected `state/*` paths, `.pytest_tmp/`, untracked audit
scripts, screenshots, secrets, `reports/operator_perf/`, or unrelated reports.

## Mandatory Pre-Close Review

PRE_CLOSE_REVIEW: PASS

### Candidate Fingerprint

Frozen production/configuration SHA-256 values:

| Path | SHA-256 |
|---|---|
| `app/config.py` | `4d22c8f7b111e519b5500024bb71841672fcfede081964939e889278c3884e8d` |
| `app/data/feed_provider_router.py` | `4fd6fa76be89d8bbf0a61d392aa8bcb1e1657e212fdb3cc92ff1ba1543e7110b` |
| `app/data/market_feeds.py` | `7e921b5d1f168397ae651a3504c1fa532eb76ab80a4c923129a6ef5bca36dc2b` |
| `app/data/polling_client.py` | `c80e1206cfba9e58593b290e34e48efca14ad5a7a71b0307121eb3f25abbde15` |
| `app/data/validators.py` | `fa773259adb4cf81bb3e520e6e0dcf7b9d6acbd88731e2bb11ec55495335d6c0` |
| `app/data/websocket_client.py` | `ae94ff34c3f73aa3dc8082316bf5c0f700c06106f9f0adb9f12fc2447a0dbcab` |
| `app/market/capability_registry.py` | `145e3bd4a4e1d0ef89fde59d56ab0a60eed2c15b25761b9a3c94b9204203748c` |
| `app/operator_providers/registry.py` | `dbe5bed672f9b189d23eb7cfef54a4227c2f60ecdf7e6cb1780f836cf9c2d07f` |
| `app/state/state_store.py` | `c8526b2aa047b02174003cdf99f345f619281088e93e7df61fe8a35cc770485e` |
| `main.py` | `cc5a697fb0d58d78d9f37f58bdbe03edabde5f0c1cfb9a27936f1598ed464b90` |
| `scripts/run_bounded_paper.ps1` | `a11d23676d13a0be0799a588b0d9e1dcec5348607e5e962e8fd7f193112c5f27` |

Frozen behavior-test/fixture SHA-256 values:

| Path | SHA-256 |
|---|---|
| `tests/test_paper_true_capability_stage4.py` | `f85c0581d9898d469d133824bb54b16c73621498f68406674db457183af69ada` |
| `tests/test_feed_provider_router_failover.py` | `3bf9ddf33676429b6792c96d357f3587084696b714b670cb1c44f955719b38bb` |
| `tests/fixtures/paper_true_capability_stage0.json` | `d01d8ff24541b875a2652166e8c778a8219db6e778ec274efb911622fdffb58c` |
| `tests/test_paper_true_capability_stage0.py` | `08c23f60d80dadbb8bab6436deecf77734614302de746f5313216054686f875f` |

### Numbered Review/Fix Cycle Log

| # | Severity | File/function or evidence | Root cause and impact | Disposition |
|---:|---|---|---|---|
| 1 | HIGH | `AlpacaCryptoWebSocketClient._request_subscription_change`, `_receive_messages` | Subscription acknowledgement and a market event sharing a frame could race or lose the event | Serialize pending change truth and process non-ack messages; adversarial shared-frame tests pass |
| 2 | HIGH | `MarketFeeds._on_transport_truth`, `SovereignHeartbeat._start_market_feeds` | A terminal transport failure could end an inner task without ending the outer run loop | Propagate terminal truth to no-flatten fail-closed shutdown; runtime lifecycle tests pass |
| 3 | MEDIUM | `MarketDataRequestBudget.slot` | Release time was calculated from acquisition time, shortening the provider window | Record completion/release time; exact-window test passes |
| 4 | HIGH | `MarketFeeds._seed_protected_execution_callbacks`, `_accept_*` | A seed could combine fresh book/trade with stale candle truth or leak partial green activation | Require complete current protected truth for activation while preserving fresh observations as non-executable; positive/refusal twins pass |
| 5 | HIGH | `BatchedAlpacaPollingClient._request`, `_open_circuit` | An in-flight success could clear or shorten a sibling request's Retry-After circuit | Generation-safe monotonic circuit deadline; concurrency test passes |
| 6 | HIGH | REST circuit and observe-only validation paths | Multiple half-open probes, uncapped Retry-After, invalid dynamic contamination, future snapshot creation, or stale provider carryover could create false recovery | Single probe, bounded delay, per-symbol isolation, strict future refusal, terminal callback, and stale purge; adversarial tests pass |
| 7 | HIGH | `_observation_metrics` | Clock quality used the freshest component and hid an older required component | Use worst required component age; clock-quality test passes |
| 8 | MEDIUM | `build_market_data_universe_snapshot` | Incomplete symbols could disappear rather than show why they were not ranked | Add explicit deterministic `unranked_symbols`; coverage test passes |
| 9 | HIGH | `MarketFeeds._rankable_breadth_rows` | Old valid samples could remain rankable indefinitely | Enforce unchanged observation max age and expose stale members as unranked; stale-symbol test passes |
| 10 | MEDIUM | rank recovery/apply flow | Restored stale samples could be replayed as duplicate current evidence | Separate restored membership from current observation history; recovery tests pass |
| 11 | MEDIUM | `_refresh_ranked_universe` | Per-symbol wall-clock reads could produce different rank cutoffs in one snapshot | Pin one `as_of_ns`; replay test passes |
| 12 | HIGH | `_observation_metrics` depth/capacity | Averaging both sides could hide a thin bid or ask side | Use the thinner side; rank/capacity tests pass |
| 13 | LOW/HARNESS | Stage 4 timestamp fixture | `timestamp + 1ns` was intermittently future on Windows clock resolution | Fixture now uses the same lawful timestamp; no validator weakened; rerun passed |
| 14 | HIGH | `MarketFeeds.record_cross_venue_advisory` | Future receipt timestamps were accepted at advisory ingress | Reject future source and receipt time; negative test passes |
| 15 | HIGH | `MarketFeeds._revoke_execution_consumer_truth`, `main._on_market_transport_truth` | Downstream rejection revoked local truth but did not notify the runtime shell | Async terminal notification and no-flatten shutdown; rejection propagation test passes |
| 16 | MEDIUM | `BatchedAlpacaPollingClient._default_request_json` | Non-JSON 429 bodies could hide status/Retry-After behind decode failure | Preserve non-200 status/headers with empty payload; dedicated test passes |
| 17 | HIGH | `_strict_text`, snapshot `from_dict` paths | `str()` normalization could turn malformed provenance into apparently valid lineage | Require genuine nonblank strings before normalization; schema test passes |
| 18 | HIGH | `_observation_metrics` exact capacity | Capacity validated increments but did not use rounded broker quantity/price increments | Decimal `ROUND_CEILING` minimum executable quantity/reference price now drive capacity/impact; exact-math test passes |
| 19 | MEDIUM/OUT-OF-SCOPE | `tests/test_g0_hook_verification.py`; `.claude/hooks/pre_tool_use.py::log_override_attempt` | Full suite writes eight test audit records to protected `state/override_log.jsonl` because the governance hook hardcodes the repo path | Preserved and unstaged; logged to tracker. No Stage 4 file can lawfully fix this frozen, governance-owned isolation defect |

Findings 1-18 are resolved in scope. Finding 19 is a named, non-dependent,
out-of-scope governance-test isolation defect and does not alter Stage 4
production/test/config hashes or its binary behavior. It is not called fixed.

### Requirement-to-Code-to-Proof Matrix

| Requirement | Production path | Final proof |
|---|---|---|
| Alpaca is the only executable data source for Alpaca | `build_default_feed_provider_router`, `FeedProviderRouter.select` | Alpaca primary/REST fallback positives plus cross-venue execution refusals |
| Bounded full-catalog breadth | `BatchedAlpacaPollingClient.poll_once`, `_run_jobs`, request budget | batch-size properties, cancellation, queue/concurrency tests, 600-symbol soak |
| Protected/ranked deep lane | `resolve_initial_market_data_deep_symbols`, `update_deep_symbols`, `MarketFeeds.apply_universe_snapshot` | protected priority/non-eviction/residence/restart tests |
| Authenticated ordered stream and stateful book | `AlpacaCryptoWebSocketClient` auth/subscription/process/book methods | greeting/auth/ack, ordering, reset/delta/delete, race, backpressure tests |
| Actual activation/failover truth | `MarketFeeds._activate_selection`, `_perform_failover`, `_refresh_executable_transport_truth` | initial failure, runtime failure, stale failover, consumer-refusal tests |
| Causal robust ranking | `_observation_metrics`, `_empirical_percentiles`, `_pareto_fronts`, `build_market_data_universe_snapshot` | causal/deterministic/Pareto/stale/incomplete/exact-Decimal tests |
| Durable immutable rank state | `StateStore.write/read_market_data_universe_snapshot` | persist/reload/tamper/relational/restart lineage tests |
| Dynamic symbols never execute | callback symbol boundary and `MARKET_DATA_OBSERVE_ONLY` snapshots | observe-only callback isolation and 600-symbol binary soak |
| Runtime owner/start/stop/status | `SovereignHeartbeat._start_market_feeds`, `_request_market_feeds_stop`, status callbacks | mocked runtime routing, rejection, shutdown ordering/status tests |
| Existing dispatch/lifecycle positives survive | unchanged decision/Risk/OMS paths | named seven-file run path, `119 passed` |

### Invalidated Earlier Evidence

1. The first affected provider suite (`40 passed, 8 failed, 6 errors`) preceded
   the lawful provider-intent relabel and used an unavailable default pytest temp
   directory. It is failure history, not close proof.
2. A later Stage 4 run (`97 passed, 1 failed`) exposed the Windows `+1ns` future
   fixture. It was invalidated by the fixture correction and full rerun.
3. Intermediate `100 passed`, targeted three-node/five-node passes, and every
   green run before the last production fixes were invalidated when source or
   tests changed.
4. Pre-freeze `135 passed` and `26 passed` runs established readiness to freeze,
   but were rerun on the final hash-bound tree. Only the final compact results in
   Section 6 support the verdict.
5. One attempted targeted command named a nonexistent node. It was a harness
   command error and supplied no product evidence.

### Plain Review Answer

After I believed implementation was done, I reread the full diff and active
callers across provider selection, transport activation, stream/REST parsing,
callbacks, ranking, persistence, runtime lifecycle, configuration, launcher,
and tests. That review broke the happy-path assumption nineteen times: eighteen
in-scope correctness/authority/test defects were fixed and retested, while the
nineteenth exposed an existing governance-test write to protected state and is
preserved as an out-of-scope finding. I then froze and hash-bound the eleven
production/config files and four behavior-test/fixture files, reran focused,
compatibility, covenant, run-path, binary-soak, full-suite, skip, syntax, scope,
mutation, dependency, threshold-owner, and secret checks on that exact tree.

### Exact Cached-Diff Result

- Expected and staged paths: 18; missing: 0; extra: 0.
- `git diff --cached --check`: exit 0.
- Intended-file unstaged delta: 0 paths.
- Forbidden/protected cached paths: 0.
- Final cached stat: 18 files, 9,928 insertions, 179 deletions.
- The report-marker update was restaged alone and the complete cache was audited
  again; production/test/config hashes remained unchanged.

STAGE_EXIT_COVENANT: PASS
