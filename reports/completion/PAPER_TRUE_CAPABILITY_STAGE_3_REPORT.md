# PAPER True Capability Stage 3 Report

Date opened: 2026-07-19 America/Chicago
Stage: 3 - Broker-canonical crypto catalog and instrument capabilities
Branch: `master`
Stage-entry HEAD: `4b9b8ed13583d56bfc2120fbee291e3695b1a288`
Board direction: Shan directed `proceed stage 3` on 2026-07-19.
Close status: **PASS - OFFLINE STAGE 3 BINARY EXIT ONLY**

## Stage-Entry Manifest

`AGENTS.md` v3, including Sections 23, 24, and 25, was re-read in full before
any Stage 3 source, test, configuration, schema, runtime, or operator-contract
edit. The Stage 2 report, current tracker, latest handoff, true-capability master
plan, affected production callers, persisted state owner, operator start path,
existing tests, and official Alpaca documentation were inspected. This report
is the first Stage 3 file edit.

### 1. Objective, binary exit, and stop conditions

Stage 3 replaces six-symbol operator nomination as executable authority with a
broker-derived, immutable, reason-coded crypto catalog/universe contract. It
does not fetch the real catalog, start PAPER, submit an order, enable SELL, or
authorize a later stage.

The binary exit is exactly the master-plan gate:

> A mocked complete catalog produces a reason-coded eligible set with exact
> Decimal constraints and zero static-list execution authority.

Required exit properties:

1. only the exact PAPER `GET /v2/assets?status=active&asset_class=crypto`
   request can use the new catalog-read family;
2. default/strict and TCA profiles deny catalog reads before transport;
3. the catalog-only profile denies every broker mutation method before
   transport;
4. raw broker facts remain broker authority; capability/universe derivation is
   deterministic and cannot overwrite broker truth;
5. every normalized executable size/price constraint is a finite, positive
   `Decimal` parsed from exact text, never float-rounded;
6. catalog assets intersect pinned account permission, quote-currency funding,
   execution-adapter support, and explicit market-data coverage;
7. every asset receives explicit inclusion/exclusion reasons, while held and
   open-order symbols remain monitored even when entry is refused;
8. catalog and universe snapshots are immutable, hash-bound, restart-readable,
   account-bound, and future/stale evidence fails closed;
9. static registry rows remain available only as non-executable fixture/display
   evidence and can never rescue a missing, stale, corrupt, or blocked catalog;
10. account pin, PAPER endpoint, secret redaction, Risk, NetEdge, sizing,
    stale/TTL, OMS, reconciliation, no-short, and no-naked-SELL controls remain
    unchanged or stronger; and
11. the exact final candidate passes focused/adversarial/restart/run-path tests,
    the full configured offline suite, and the Section 25 review loop.

Hard stop conditions:

- any real broker/network access before separately approved Stage 12;
- any POST/PATCH/DELETE/cancel/order/position mutation caused by this stage;
- catalog persistence or `InstrumentRegistry` becoming a second broker owner;
- static symbols, metadata, cache, or configuration green-lighting entry after
  catalog failure, staleness, corruption, account mismatch, or missing facts;
- a Risk, NetEdge, economic, sizing, TTL, strategy, masking, OMS, account-pin,
  reconciliation, no-short, or safety threshold must move;
- a new external dependency or new subsystem becomes necessary;
- an affected restriction remains `UNKNOWN`;
- source files outside the declared scope enter the diff;
- protected runtime/evidence files would need editing or staging; or
- the same blocker repeats three cycles or the binary exit fails twice.

### 2. Session boot and complete dirty-worktree record

Stage-entry branch and commit:

```text
master
4b9b8ed13583d56bfc2120fbee291e3695b1a288
```

Recent history establishes Stage 2 as the completed dependency:

```text
4b9b8ed consolidate broker inventory authority
f462356 require pre-close review loop
4453209 repair causal per-symbol decision state
e363f4b freeze paper true capability stage 0 baseline
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

The dirty tree matches the Stage 2 close handoff. No packet is truncated,
ambiguous, or unsafe. The missing real catalog is a known proof boundary, not
permission to call Alpaca during Stage 3.

### 3. Declared Stage 3 scope

Planned production owners:

```text
app/execution/broker_read_policy.py
app/execution/alpaca_paper_adapter.py
app/execution/broker_gateway.py
app/market/venue_capabilities.py
app/market/capability_registry.py
app/instrument_registry.py
app/state/state_store.py
app/config.py
main.py
app/api/operator_runtime_config.py
app/api/operator_paper_supervisor.py
```

Scope amendment 1 (2026-07-19, before either file was edited): full caller
inspection found that `app/main_loop.py::_build_pre_trade_guardrail_verdict` and
`app/core/intelligence_portfolio_state_truth_spine.py` each instantiate the
static capability registry internally. They are direct active consumers of the
same capability authority and must accept the broker-derived registry, or the
Stage 3 catalog would be bypassed after runtime bootstrap. These two production
files are therefore added to scope. Their directly affected fixture tests may
be updated only to inject an explicit static test registry or a broker-derived
mock registry; each assertion-intent change will be logged. No strategy, Risk,
NetEdge, sizing, TTL, OMS, or broker-governor behavior enters scope.

Scope amendment 2 (2026-07-19, before the remaining newly named files were
edited): expanded caller validation found three additional test-only consumers
whose offline positive fixtures instantiate the default static Alpaca crypto
registry: `tests/test_pre_trade_guardrail_constraints.py`,
`tests/test_seam6_controlled_alpaca_paper_portfolio_expansion_machine.py`, and
`tests/test_seam7g_market_truth_reconciliation_spine.py`. The first was already
covered by amendment 1's directly affected fixture-test allowance when its
fixture was repaired; this amendment names all three explicitly before the
Seam 6 and Seam 7g files are edited. They are added only for broker-derived
mock-registry injection and truthful assertion relabeling.
The environment-gated real Seam 6 broker-mutation test remains skipped,
unchanged in authority, and outside Stage 3 proof. The Stage 0 fixture/test is
also in the original declared scope and will record the exact Stage 3 source
delta and renamed negative-test node after the final candidate freezes.

Scope amendment 3 (2026-07-19, before these files are edited): the first full
seven-file run-path gate produced `111 passed, 8 failed`. All eight surviving
positive tests reached decision construction and were then refused only because
their fixtures still relied on the default static Alpaca crypto rows that Stage
3 correctly made non-authoritative. The directly affected fixture owners are
`tests/test_decision_frame_orchestration_paper_exploration_alpha.py`,
`tests/test_phase3_risk_gate_stress_proof.py`, and
`tests/test_runtime_dispatch_admission_telemetry.py`. They enter scope solely
to inject deterministic broker-derived mock capability evidence into the
existing positive paths. No positive assertion will be converted to refusal.
The MovingFloor sell-to-close positive also exposed an implementation
regression: Stage 3 had narrowed derived capability metadata to BUY even though
the entry fingerprint preserves BUY plus position-backed `sell_to_close` and
defers actual adapter SELL support to Stage 8. The derived capability declaration
will preserve that existing positive contract; the Alpaca adapter remains
BUY-only, and its pre-transport SELL refusal remains mandatory.

Scope amendment 4 (2026-07-19, before these files are edited): the first full
offline-suite review produced `1957 passed, 14 skipped, 19 failed`. Production
failed closed; 17 failures were older positive operator fixtures that proved
baseline/preflight readiness but did not install the now-mandatory immutable
broker catalog/universe evidence. The other two failures were an obsolete
literal-source assertion for the now-configurable `StateStore` path and a
positive unprotected-symbol guardrail fixture that still depended on the static
non-executable registry. The following test-only files enter scope so fixtures
can rise to the stronger contract without changing production behavior:
`tests/paper_capability_test_support.py`,
`tests/test_operator_account_identity_pin.py`,
`tests/test_operator_ai_ask.py`,
`tests/test_operator_broker_preflight.py`,
`tests/test_operator_launch_readiness.py`,
`tests/test_operator_paper_baseline.py`,
`tests/test_operator_readonly_api.py`,
`tests/test_order_id_mapping_authority.py`, and
`tests/test_paper_true_capability_stage2.py`. The shared helper will build and
persist deterministic, current, test-only broker-derived evidence through the
production normalizer, universe builder, and `StateStore`; it grants no fake
production or broker proof. The source assertion will retain its ownership
intent while accepting the configurable state path. Both positive guardrail
tests retain `ALLOW`; neither is relabeled to refusal. No production guard,
threshold, assertion, or safety policy enters this amendment.

Planned tests/evidence/governance:

```text
tests/test_paper_true_capability_stage3.py
tests/test_broker_read_policy.py
tests/test_venue_market_asset_capability_layer.py
tests/test_config.py
tests/test_operator_runtime_config.py
tests/test_operator_paper_supervisor.py
tests/test_state_store.py
tests/fixtures/paper_true_capability_stage0.json
tests/test_paper_true_capability_stage0.py
reports/completion/PAPER_TRUE_CAPABILITY_STAGE_3_REPORT.md
CHECKPOINT_TRACKER.md
reports/codex_handoff_latest.md
```

The existing PowerShell/supervision scripts were inspected because they
transport the current watchlist. They are not initially edited: production
admission will require a pinned durable universe snapshot in `main.py` and the
supervisor, so a script default cannot authorize execution. If that cannot be
proved without a script change, the scope tripwire requires a report update
before such a file may be touched.

Explicitly out of scope: Stage 4 feed batching/ranking/rate budgets; Stage 5
strategy-feed integration; Stage 6 standard-profile activation; Stage 7 model
upgrades; Stage 8 external SELL/order lifecycle; Stage 9 managed-existing exit
policy; Stage 10 campaign envelope; Stage 11 operator UX; Stage 12 real broker
reads; all PAPER campaigns; cloud/AWS; multi-tenant activation; live or real
money; dormant mutation authorities; threshold changes; deletions.

### 4. Affected module truth map and one-owner authority graph

| Module/area | Live-repo truth at entry | Allowed Stage 3 role | Planned disposition |
|---|---|---|---|
| AlpacaPaperBrokerAdapter | Single-asset `GET /v2/assets/{id}` path exists, but list `/v2/assets` is unsupported/unknown; adapter still owns PAPER broker boundary | Exact GET transport only; never catalog interpretation or eligibility | Add exact catalog method/query and catalog-only mutation denial; no real call |
| BrokerReadPermissionProfile | Strict permits account/orders/positions; extended adds TCA activity; `READ_ASSETS` covers only single-asset prefix and no profile permits it | Narrow network permission/refusal owner | Add distinct `READ_ASSET_CATALOG` and catalog-only profile; unknown/default remains fail-closed |
| BrokerGateway protocol | Exposes single-asset GET and order mutation contracts | Interface declaration only | Add catalog GET protocol method; no authority change |
| VenueCapability model | Carries Decimal min-notional/min-quantity/step but lacks explicit broker asset identity/status/exchange/price increment/provenance | Derived execution-capability schema | Add explicit immutable broker capability fields with backward-safe defaults |
| VenueCapabilityRegistry | Static Alpaca/Kraken capabilities and selection; current static Alpaca rows can be selected | Sole derived capability/eligibility owner under broker facts | Normalize broker assets and build reason-coded catalog/universe snapshots; disable static Alpaca execution authorization |
| InstrumentRegistry | Global static metadata; crypto values are floats; BTC/ETH/SOL and Alpaca-confirmed pairs are labeled Kraken, with some margin flags true | Compatibility/reference model; not broker or eligibility authority | Use Decimal metadata, correct Alpaca venue/margin truth, mark static rows non-executable, allow broker-derived specs |
| StateStore | Existing durable WAL/SQLite fact owner with strict hash-checked inventory snapshots | Immutable catalog/universe evidence store only | Add atomic normalized snapshot/items/membership tables and strict reads; never decide eligibility or broker truth |
| Config | Explicit `runtime_watchlist`/`symbol_universe` currently feeds runtime resolution | Typed transport of pinned snapshot identity and non-authoritative priorities | Add pinned catalog/universe IDs and state path; static lists become observe-only priorities |
| main.resolve_runtime_universe | Explicit watchlist/symbol list plus static InstrumentRegistry currently owns runtime symbol acceptance | Consumer of one derived universe snapshot | Require pinned, fresh, integrity-checked durable universe for executable runtime; static resolution is visibly non-executable |
| SovereignHeartbeat | Starts feed/runtime from `resolve_runtime_universe`; initializes StateStore before universe resolution | Runtime enforcement consumer | Pass the existing StateStore into resolution and refuse non-executable/static/missing catalog truth |
| OperatorRuntimeConfig | Publishes six-symbol `allowed_watchlist` and exploration profile | Operator metadata/paths only | Mark list as priority/non-authoritative and expose catalog/universe state path/IDs without secret values |
| OperatorPaperSupervisor | Validates operator watchlist against six symbols and passes it as the child universe | Process lifecycle owner; display/validation consumer only | Read strict durable universe, surface exact blocker/lineage, prevent operator nomination from granting execution, pass broker-derived symbols |
| Risk/NetEdge/sizing/OMS/reconciliation | Downstream hard owners | Unchanged final authorities | Fingerprint and regression test; no threshold/control edit |

Authority chain after Stage 3:

```text
Alpaca PAPER GET response
  -> broker raw asset facts (broker authority)
  -> capability_registry deterministic normalization/eligibility (derived owner)
  -> StateStore immutable catalog + universe evidence (durable fact store)
  -> supervisor/main pinned strict consumer (admission/display)
  -> MarketTruthSnapshot + NetEdge + Risk + sizing + OMS remain downstream owners
```

The catalog does not authorize a trade. `mutation_authorized_by_default` remains
false, and later market truth/economic/risk/lifecycle gates remain mandatory.

### 5. Restriction ledger and classification

| Restriction | Owner/current behavior | Classification | Stage 3 disposition |
|---|---|---|---|
| Six-symbol operator allowlist | runtime config, supervisor, capability registry, main | `COMMISSIONING_OR_TEST_SCAFFOLD` | Remove from executable authority after durable broker universe passes; preserve as priority/fixture/display evidence only |
| Static Alpaca crypto capability rows | capability registry can currently select them | `COMMISSIONING_OR_TEST_SCAFFOLD` | Make non-executable with explicit `BROKER_CATALOG_REQUIRED`; broker-derived rows replace them |
| Static float precision | InstrumentRegistry supplies float min/step/tick | `COMMISSIONING_OR_TEST_SCAFFOLD` | Replace executable metadata with exact Decimal broker-derived fields; retain non-executable reference values |
| Kraken/margin labels on Alpaca crypto | InstrumentRegistry labels crypto Kraken; major pairs margin true | `COMMISSIONING_OR_TEST_SCAFFOLD` | Correct to Alpaca/non-marginable and test no Kraken execution claim |
| Exact catalog read authorization | broker read policy denies unknown `/v2/assets` list | `GOVERNANCE_OR_ARMING_CONTROL` | Retain fail-closed default; add separately named catalog-only profile and zero-mutation enforcement |
| PAPER endpoint/account pin | credential and account identity authorities | `PERMANENT_SAFETY_CONTROL` | Preserve unchanged and bind snapshots to endpoint/account suffix |
| Catalog completeness/integrity/freshness | missing at entry | `PERMANENT_SAFETY_CONTROL` | Add positive finite-time/hash/count checks; missing/stale/future/corrupt blocks entry |
| Active/tradable/fractionable/precision facts | currently static/partial | `PERMANENT_SAFETY_CONTROL` | Require exact broker fields; malformed or missing facts refuse that asset |
| Margin/short claims | static contradictions exist | `PERMANENT_SAFETY_CONTROL` for spot crypto | Any true or malformed claim refuses entry; no short/margin capability is created |
| Account crypto permission and blocks | account GET exists; universe does not consume crypto status | `PERMANENT_SAFETY_CONTROL` | Require ACTIVE account and crypto status plus no blocking/suspension flags |
| Quote funding/data coverage/adapter support | not intersected by static list | `QUANT_OR_ECONOMIC_CONTROL` plus data-truth control | Explicit reason-coded intersection; absence never defaults true |
| Held/open-order monitoring | static universe may omit non-nominated symbols | `PERMANENT_SAFETY_CONTROL` | Monitor regardless of new-entry eligibility; no forced entry or mutation |
| Risk/NetEdge/sizing/TTL/strategy thresholds | downstream hard gates | `QUANT_OR_ECONOMIC_CONTROL` | No changes permitted |
| Board PAPER/live gates | governance and campaign controls | `GOVERNANCE_OR_ARMING_CONTROL` | Preserve; Stage 3 authorizes no external action |

No affected restriction remains `UNKNOWN`.

### 6. Baseline fingerprints

Stage-entry source SHA-256:

```text
app/execution/broker_read_policy.py   0f31e932f66c49cc269f26c6d181b17141f397af171a88128cbf03ed9417cbf0
app/execution/alpaca_paper_adapter.py f8e08c8234f3104929bace10989d908c3892d5ca66ce5aca7737dca24a5a3955
app/execution/broker_gateway.py       d8a0b980d0d3a17507a977d988846f693c1b040e10dd479f2b0723cb2d8bf6c0
app/market/capability_registry.py     9ecf7ebb866dcd284bd2b8c5cd1d168e332751bad3d2451c2d1085ad9b79e158
app/market/venue_capabilities.py      38be75d584aacfca5680f96537158d954a6cda33a56904d6cdc68f90266d3c0d
app/instrument_registry.py            7a4145a73f1e664435605b523f49ca78ee8c99cd788a58f6ce5d2af2dd7a8fbd
app/state/state_store.py              dae3ff16f2f8151af0db63e9c424995e6e45d77ffc7af214787e390523800c28
app/config.py                         348327083db97559e22933713be0f9bac9e9005a262633353af580f3396d452e
main.py                               e089772d5142df5105ed3b837d259c5c16ac9bf7547e37eea49d7b10930644e5
app/api/operator_runtime_config.py    3f79b4cf63e58de7d01c60b327fd9a5737f0db0cd79932105f7eec2b0cd6ac95
app/api/operator_paper_supervisor.py  90be76db49dd8145634eec6d499167c628ef1133ea15a9bf3f0311a1f0832b43
```

Entry behavior/default pins:

- `PAPER_SMOKE_STRICT_READS` permits only account/orders/positions;
- `PAPER_TCA_EXTENDED_READS` adds only the existing TCA activity families;
- no existing profile permits `/v2/assets` catalog or single-asset reads;
- adapter mutation surface remains `POST /v2/orders` and
  `DELETE /v2/orders/{id}` under existing OMS/governance authority;
- static runtime list is BTC/ETH/SOL/LTC/AVAX/LINK USD pairs;
- `PAPER_EXPLORATION_ALPHA`, duration bounds 60..432000 seconds, expected
  account suffix `045ded`, PAPER-only endpoint, live blocked, real money blocked;
- static Alpaca crypto advertises BUY + sell-to-close capability metadata but
  the external adapter remains BUY-only until Stage 8;
- `VenueCapability.mutation_authorized_by_default` is false;
- InstrumentRegistry crypto executable-looking size/step/tick fields are float;
  BTC/ETH/SOL are Kraken + margin-available, and LTC/AVAX/LINK are Kraken-labeled;
- Stage 0 threshold profile, Risk, NetEdge, sizing, TTL, correlation,
  concentration, utilization, cash reserve, strategy, and OMS fingerprints are
  unchanged and outside the Stage 3 modification plan.

Entry focused baseline:

```text
65 passed, 72 warnings, 0 failed
```

Command scope: broker-read policy, venue/capability layer, Config, operator
runtime config, supervisor, StateStore, and Stage 0 covenant tests. This is only
entry evidence and cannot support the final verdict after source changes.

### 7. Mathematical and model inventory

Stage 3 adds no alpha score, ranking estimator, forecast, probability model,
Risk threshold, NetEdge threshold, or trade-size heuristic.

Deterministic transformations planned:

1. Canonical symbol identity is derived from broker asset ID plus normalized
   pair form. Slash, URL-encoded slash, hyphen, underscore, and unseparated
   legacy aliases may map to one asset only when identity/facts agree. Conflicts
   block the catalog.
2. `min_order_size`, `min_trade_increment`, and `price_increment` are exact
   base-asset/base-asset/quote-price increments parsed from broker text into
   finite positive Decimal values. Float inputs are rejected as non-exact.
3. Asset entry eligibility is a logical intersection, not a weighted score:

```text
asset facts valid
AND account suffix/status/crypto permission valid
AND account mutation-block flags false
AND quote currency has positive available funding truth
AND execution adapter supports Alpaca PAPER crypto
AND market-data coverage is explicitly proven
AND catalog/universe evidence is current and integrity-valid
```

4. Every false term produces a named reason; no missing value is coerced to
   zero, false safety, or positive eligibility.
5. Catalog and universe hashes use canonical sorted JSON and SHA-256. Identity
   is stable under input ordering. Duplicate identical aliases are idempotent;
   conflicting duplicates fail closed.
6. Freshness is `observed_at_ns <= as_of_ns <= valid_until_ns`. The validity
   horizon must be supplied by the future authorized producer/config owner;
   Stage 3 does not hardcode a TTL. Future observations, expired evidence, or
   missing bounds refuse new entry.
7. Complexity is bounded by normalization plus canonical sorting, expected
   `O(n log n)` for `n` broker assets. Stage 4 owns request/data budgets and
   breadth/deep ranking; Stage 3 may not pretend to prove those capacities.

Assumptions and limitations:

- Alpaca returns precision fields as exact strings, consistent with its
  official crypto example. A numeric JSON float is rejected to avoid preserving
  an already-rounded value.
- Account `crypto_status` must be ACTIVE. Missing status is not inferred from
  general account status.
- USD funding can derive from exact broker cash; non-USD quote funding requires
  explicit reconciled available-balance evidence.
- Market-data coverage is an explicit input until Stage 4 proves the transport.
- Catalog membership is necessary but never sufficient for execution, edge,
  liquidity, or profitability.

### 8. Planned proof matrix

Positive tests:

- exact catalog profile performs one mocked GET with exact query and no body;
- active/tradable/fractionable/non-marginable/non-shortable assets with exact
  positive precision normalize deterministically;
- eligible USD pairs use ACTIVE pinned account, positive exact cash, Alpaca
  adapter support, and explicit data coverage;
- durable restart returns identical strict catalog/universe facts and hashes;
- valid held/open-order symbols remain monitored;
- main/supervisor consume the full pinned eligible set, not an operator subset.

Negative/adversarial tests:

- strict/default/TCA/unknown profiles deny catalog before transport;
- catalog-only profile denies POST, PATCH, DELETE, order submission, cancel,
  single-asset GET, wrong path, wrong query, extra query, and GET payload;
- live/non-PAPER endpoint, account-suffix mismatch, inactive account/crypto
  status, broker block flags, missing cash/funding, adapter mismatch, and missing
  market data refuse;
- inactive, nontradable, nonfractionable, marginable, shortable, missing IDs,
  malformed booleans, missing/zero/negative/nonfinite/float precision, wrong
  class, Kraken claims, and malformed symbols refuse;
- duplicate aliases deduplicate only with identical identity/facts; conflicting
  asset IDs/symbol facts block;
- missing, future, expired, count-mismatched, hash-corrupt, account-mismatched,
  or universe/catalog-lineage-mismatched state refuses;
- static six, static InstrumentRegistry, config watchlist, and stale cache cannot
  rescue entry;
- secret values never appear in normalized snapshots, status, logs, errors, or
  report evidence.

Temporal/property/replay/recovery/performance tests:

- input permutations produce the same item ordering/hash and eligibility;
- repeated persistence is duplicate/idempotent while same-ID conflicting data
  is rejected;
- restart/reopen and read-only strict mode preserve the same snapshot;
- held/open-order monitoring survives catalog exclusion/staleness;
- synthetic larger catalogs normalize deterministically without quadratic
  duplicate behavior; no network throughput claim is made.

Regression/run-path tests:

- Stage 0/1/2 fingerprint chain remains intact with an explicit Stage 3 delta;
- account pin, PAPER endpoint, broker preflight, supervisor start refusal,
  runtime dispatch, capability, guardrail, Risk-ordering, and mutation-audit
  positives/refusals survive;
- no positive test is converted to refusal without a documented contract change
  and surviving lawful positive twin;
- full configured offline suite has zero failures on the exact final tree.

### 9. Proof and approval boundary

Authorized in Stage 3: source/tests/docs/schema work, mocked transports, temporary
test SQLite databases, offline runtime object tests, local process-free API
tests, full pytest, exact report/tracker/handoff staging, commit, and push.

Not authorized: any real Alpaca GET, any broker mutation, any PAPER run, any
launcher/browser claim, any live credential/read/action, real money, new
dependency/subsystem, module deletion, dormant authority activation, manual
trade control, threshold change, protected state edit/staging, AWS/cloud, or
multi-tenant activation.

Highest possible Stage 3 proof rung under this approval is local offline tests.
Mocked transport proves contract logic only. Runtime process, browser, broker
read, PAPER, fill, SELL, profitability, and arming truth must be reported as not
run/not obtained.

### 10. Research used

Official primary sources inspected on 2026-07-19:

- Alpaca `GET /v2/assets` reference:
  https://docs.alpaca.markets/us/reference/get-v2-assets-1
- Alpaca crypto spot trading and asset precision example:
  https://docs.alpaca.markets/us/docs/crypto-trading
- Alpaca-py Asset and TradeAccount models:
  https://alpaca.markets/sdks/python/api_reference/trading/models.html
- Alpaca asset request filters:
  https://alpaca.markets/sdks/python/api_reference/trading/requests.html
- Alpaca single-asset slash/legacy symbology reference:
  https://docs.alpaca.markets/us/reference/get-v2-assets-symbol_or_asset_id
- Alpaca 2026 borrow-status schema change, confirming asset schemas evolve:
  https://docs.alpaca.markets/us/changelog/2026-06-05-borrow-status-6b96a5a

Applied lessons:

- `/v2/assets` is the broker master list and supports status/asset-class filters;
- active and tradable are distinct facts;
- crypto precision is per asset and may change, so it must be snapshot-bound;
- Alpaca spot crypto is fractionable, non-marginable, and non-shortable in the
  documented model;
- TradeAccount exposes separate `crypto_status` and blocking/suspension flags;
- slash and legacy crypto symbology both exist;
- changing asset schemas require tolerant preservation of unknown display
  metadata but strict validation of execution-critical known fields.

Intentionally rejected:

- copying Alpaca SDK float models into executable metadata;
- assuming every active asset is tradable/fundable/data-covered;
- a static fallback, blind top-volume list, or all-listed-pairs execution;
- treating broker catalog membership as MarketTruthSnapshot, NetEdge, Risk, or
  order authorization;
- a real GET during this stage.

### 11. Pre-code self-red-team

This is an adversarial executor review, not a claimed second-agent or external
audit.

**Duplicate authority:** StateStore could become a broker/catalog decision
owner if it recalculates facts on read. Adjustment: it stores normalized
immutable rows/hashes only; Alpaca owns raw facts and capability_registry owns
derived inclusion. Runtime consumers cannot alter either.

**Fake readiness:** A valid catalog could be displayed as permission to trade.
Adjustment: catalog/universe status explicitly says derived eligibility,
`mutation_authorized_by_default` remains false, and supervisor/main still
require all existing start, market truth, economic, Risk, sizing, OMS, and
reconciliation gates.

**Hidden broker truth:** Static registry or cached rows could overwrite a newer
broker response. Adjustment: static rows are non-executable, snapshots are
append-only and ID/hash/account/time-bound, and missing/stale/conflicting truth
cannot fall back.

**Permission expansion:** Adding `/v2/assets` could make arbitrary asset/network
reads possible or allow mutation under a read profile. Adjustment: separate
family, exact path/query, distinct catalog-only profile, and pre-transport
method denial. Existing profiles do not inherit it.

**Risk/NetEdge/economic weakening:** A wider catalog could be mistaken for a
reason to lower filters or optimize trade count. Adjustment: Stage 3 has no
ranking or threshold changes; zero eligible/traded assets remains lawful.

**State loss/corruption:** Partial writes or duplicate aliases could make a
restart silently use incomplete capability truth. Adjustment: one atomic
snapshot transaction, strict count/hash reads, deterministic dedupe, conflict
rejection, and restart tests.

**Cross-account/tenant contamination:** A cache could be reused under another
account. Adjustment: bind catalog and universe to PAPER endpoint family and
normalized account suffix; supervisor/main compare the current pin. No tenant
subsystem is invented.

**Hidden configuration:** A hardcoded TTL, funding currency, or data provider
could silently determine eligibility. Adjustment: validity deadline and
coverage/funding evidence are explicit snapshot inputs and outputs. Immutable
safety invariants remain code-enforced.

**Math simplification/numeric failure:** Floats or permissive coercion could
round executable increments or convert NaN/missing to zero. Adjustment: reject
floats/nonfinite/missing/nonpositive precision and retain exact Decimal text.

**Tests green while runtime broken:** Direct normalizer tests could pass while
main/supervisor still use the static six. Adjustment: named production-path
tests prove static non-authority, strict durable read, full eligible-set
transport, missing/stale refusal, and surviving run-path positives.

**Held/open-order lifecycle loss:** Excluding an asset could stop monitoring an
owned position. Adjustment: monitor-required is independent from entry
eligibility and derives from reconciled held/open-order symbols.

**UI clutter/truth:** Stage 3 is not a UI redesign. Adjustment: add only compact
backend status fields/lineage for later UI consumption; no browser claim.

**Stop condition:** Any real request, mutation, duplicate owner, fallback
authorization, threshold movement, unclassified restriction, unrelated file,
or unprovable runtime contract stops the stage immediately.

Red-team verdict: the adjusted plan is safe to implement offline. It removes a
commissioning scaffold only after installing the correct broker-derived owner,
keeps permanent/quant/governance controls, and does not authorize activity.

STAGE_ENTRY_COVENANT: PASS

## Stage Close Report

### 1. Verdict

**PASS for the Stage 3 offline binary exit.** A mocked complete Alpaca PAPER
crypto catalog now produces a deterministic, reason-coded eligible universe
with exact Decimal constraints and zero static-list execution authority. The
reviewed behavior candidate passed the focused suite, all Stage 0-3 covenants,
the named run-path suite, and the full configured offline suite with zero
failures.

This verdict does not claim a real broker catalog read, production catalog
acceptance, a launched runtime, browser behavior, PAPER execution, broker
mutation, continuous refresh, SELL routing, profitability, or readiness for an
autonomous run. Those proof rungs were neither authorized nor performed.

### 2. Files Changed

Production authority and runtime wiring (13):

- `app/api/operator_paper_supervisor.py`
- `app/api/operator_runtime_config.py`
- `app/config.py`
- `app/core/intelligence_portfolio_state_truth_spine.py`
- `app/execution/alpaca_paper_adapter.py`
- `app/execution/broker_gateway.py`
- `app/execution/broker_read_policy.py`
- `app/instrument_registry.py`
- `app/main_loop.py`
- `app/market/capability_registry.py`
- `app/market/venue_capabilities.py`
- `app/state/state_store.py`
- `main.py`

Tests and frozen fixture evidence (22):

- `tests/fixtures/paper_true_capability_stage0.json`
- `tests/paper_capability_test_support.py`
- `tests/test_broker_read_policy.py`
- `tests/test_decision_frame_orchestration_paper_exploration_alpha.py`
- `tests/test_intelligence_portfolio_state_truth_spine.py`
- `tests/test_operator_account_identity_pin.py`
- `tests/test_operator_ai_ask.py`
- `tests/test_operator_broker_preflight.py`
- `tests/test_operator_launch_readiness.py`
- `tests/test_operator_paper_baseline.py`
- `tests/test_operator_paper_supervisor.py`
- `tests/test_operator_readonly_api.py`
- `tests/test_order_id_mapping_authority.py`
- `tests/test_paper_true_capability_stage0.py`
- `tests/test_paper_true_capability_stage2.py`
- `tests/test_paper_true_capability_stage3.py`
- `tests/test_phase3_risk_gate_stress_proof.py`
- `tests/test_pre_trade_guardrail_constraints.py`
- `tests/test_runtime_dispatch_admission_telemetry.py`
- `tests/test_seam6_controlled_alpaca_paper_portfolio_expansion_machine.py`
- `tests/test_seam7g_market_truth_reconciliation_spine.py`
- `tests/test_venue_market_asset_capability_layer.py`

Close governance files (3):

- `reports/completion/PAPER_TRUE_CAPABILITY_STAGE_3_REPORT.md`
- `CHECKPOINT_TRACKER.md`
- `reports/codex_handoff_latest.md`

The four predeclared scope amendments in the entry manifest account for every
test file added after initial scouting. No production file outside the declared
functional area entered the diff.

### 3. Root Cause

The system treated an operator-maintained six-symbol list and static instrument
metadata as executable crypto-universe authority. That commissioning scaffold
could not truthfully represent the broker's current asset inventory, exact
quantity/price increments, account-specific permissions, funding compatibility,
adapter support, or market-data coverage. It also mixed entry eligibility with
the obligation to keep monitoring already-held or open-order symbols.

The correct owner split is now explicit: Alpaca owns raw catalog facts;
`capability_registry` owns deterministic derivation; `StateStore` owns durable
immutable evidence; Risk/NetEdge/sizing/MarketTruthSnapshot/OMS retain their
existing downstream authority; and the operator symbol list is priority only.

### 4. Fixes Implemented

1. Added the distinct `PAPER_ASSET_CATALOG_READS` policy family and exact
   `READ_ASSET_CATALOG` operation. Only GET
   `/v2/assets?status=active&asset_class=crypto` is accepted, and mutation
   methods are denied before transport.
2. Added a broker-gateway catalog contract and Alpaca adapter implementation
   without adding any production caller that performs a real GET in Stage 3.
3. Added strict broker-canonical asset normalization. Malformed types, missing
   identity, alias conflicts, duplicate conflicts, nonfinite or nonpositive
   constraints, and unsupported facts fail closed rather than being stringified
   or rounded.
4. Added deterministic catalog and universe snapshots with explicit provenance,
   account/endpoint pins, count/hash integrity, validity windows, and exact
   Decimal text.
5. Derived entry eligibility from the intersection of broker asset facts,
   account permission, quote-currency funding, adapter support, and market-data
   coverage. Each symbol carries reason codes.
6. Separated `entry_eligible` from `monitor_required`, so excluded assets cannot
   open new entries while reconciled holdings/open orders remain visible to the
   governed lifecycle.
7. Added atomic durable catalog/universe persistence and strict restart reads.
   Missing, future, stale, hash-corrupt, count-mismatched, cross-account, or
   malformed evidence is refused.
8. Removed static Alpaca crypto execution authority. Static registry rows remain
   preserved for fixture/reference/display uses, and even direct static
   `InstrumentRegistry.validate_order()` now refuses execution.
9. Injected the dynamic registry into the main loop and intelligence portfolio
   spine, eliminating internal static-registry rescue paths.
10. Made the operator/supervisor symbol list priority-only. The full eligible
    broker-derived universe is transported to the child; an outside or malformed
    priority symbol blocks independently and cannot grant eligibility.
11. Added supervisor pre-start and child-boot checks for the pinned endpoint,
    account suffix, snapshot identity, integrity, freshness, and full universe.
    The evidence is checked again immediately before spawn.
12. Added offline production-path, corruption, restart, permutation, direct
    bypass, run-path, and invariant tests. The helper constructs evidence through
    production normalizers/builders/StateStore and is not a production shortcut.

### 5. 360-Degree Adjacent Improvements

- Non-string account suffixes, held symbols, open-order symbols, and priority
  values can no longer disappear through permissive coercion.
- Exact broker price increment joined the existing capability contract; no float
  is admitted for executable size or price constraints.
- Deterministic alias handling makes input ordering irrelevant and rejects
  conflicting representations instead of selecting whichever row arrived last.
- Full-universe transport preserves operator priority ordering while proving
  that ordering confers no execution permission.
- Static reference metadata remains intact for its legitimate informational
  role. No module was deleted, flattened, or silently bypassed.
- Existing run-path positives survived unchanged in authority: dispatch,
  compilation, submission, routing, mocked fill, and position-backed exit paths
  remain covered by their dedicated tests.

### 6. Tests and Checks

Proof ladder reached: **logic/tests only**.

Final exact-candidate validation:

| Check | Result |
|---|---|
| Focused Stage 3 and directly affected suite | `173 passed`, `0 failed`, `107 warnings` in 17.07s |
| Named seven-file run-path suite | `119 passed`, `0 failed`, `78 warnings` in 14.83s |
| Stage 0-3 covenant suite | `150 passed`, `0 failed`, `100 warnings` in 12.67s |
| Full configured offline suite | `1980 passed`, `14 skipped`, `0 failed`, `420 warnings` in 216.50s |
| Explicit skip audit | `54 passed`, `14 skipped`, `0 failed`, `78 warnings` in 8.48s |
| Relevant Python AST parse | PASS for 15 files |
| Stage 0 JSON fixture parse | PASS |
| Relevant import smoke | PASS |
| New skip/xfail scan | zero added |
| Deleted-file scan | zero deleted |
| New external-dependency scan | zero added |
| Obvious secret/private-key marker scan | zero findings |
| Risk-threshold-owner diff scan | zero files changed |
| Final cached membership | 38 expected, 38 staged, zero missing, zero extra |
| Final cached whitespace check | PASS (`git diff --cached --check`, exit 0) |
| Final cached stat | 38 files, 5,441 insertions, 109 deletions |
| Intended-file worktree parity | zero unstaged delta across all 38 paths |

Named run-path files, all passing:

- `tests/test_decision_frame_orchestration_paper_exploration_alpha.py`
- `tests/test_deterministic_end_to_end_harness.py`
- `tests/test_integrated_paper_readiness.py`
- `tests/test_phase3_risk_gate_stress_proof.py`
- `tests/test_replay_parity_acceptance.py`
- `tests/test_runtime_dispatch_admission_telemetry.py`
- `tests/test_upstream_dispatch_signal_submission.py`

The full-suite skips were inspected individually; none is a Stage 3 test and
none is counted as a pass:

| Class | Count | Disposition |
|---|---:|---|
| Explicit Board-gated broker read | 7 | Preserved conditional skip; requires `PK_BOARD_AUTHORIZED_PAPER_BROKER_READ=YES_D4_BOARD_AUTHORIZED` |
| Explicit broker-mutation approval absent | 3 | Preserved conditional skip; no POST or mutation was attempted |
| Legacy read-only network probe unavailable | 4 | Preserved conditional skip reporting `URLError`; not external proof |

The exact skipped nodes were the broker integration checks in the 10-symbol
expansion, read-only truth, whole-bot contribution, lifecycle exit defense,
runtime exposure, integrated portfolio machine, and contribution activation
files; the three mutation-gated nodes were batch execution, tiny-order
execution, and Seam 6 expansion; the four network-unavailable nodes were
ownership reconciliation, post-fill reconciliation, tiny-order planning, and
whole-bot replay stress.

Assertion-intent relabel log:

1. `test_supervisor_rejects_live_real_money_unknown_profile_and_watchlist` was
   relabeled `...ineligible_priority_symbol`: the obsolete static-six refusal
   became the broker-derived eligibility refusal. The assertion remains a
   refusal and is owned by the correct authority.
2. `test_alpaca_paper_crypto_internal_five_dollar_cap_blocks_before_broker_minimum`
   was relabeled `...broker_minimum_quantity_blocks_before_routing`: the fake
   static `$10` minimum was replaced by exact broker minimum quantity. The
   internal maximum remains separately tested.
3. `test_venue_capability_and_instrument_registry_sign_truth_and_fail_closed`
   was relabeled
   `test_broker_derived_venue_capability_and_static_instrument_reference_fail_closed`:
   dynamic broker evidence proves the positive capability and static validation
   now proves refusal.
4. `test_alpaca_crypto_supports_sell_to_close_but_not_sell_short` was relabeled
   with a `stage3_dynamic` prefix: its positive position-backed capability twin
   now comes from the broker-derived registry; generic shorting remains refused.

Related expected reasons changed from the obsolete static minimum-notional
assumption to `MIN_QUANTITY_NOT_MET` in the intelligence spine and Seam 6
fixtures. `STATIC_UNIVERSE_REFERENCE_ONLY` replaces the misleading static
`UNIVERSE_READY` label. No positive run-path test was flipped into a refusal.

Invalidated evidence: every focused or full-suite result obtained before review
findings were fixed was treated as provisional and is not the close proof. Only
the final counts above apply to the frozen candidate.

Frozen behavior candidate: 35 files. A reproducible SHA-256 manifest is built
by sorting relative paths, writing `path<TAB>lowercase-file-sha256<LF>` for each,
and hashing the UTF-8 manifest. Final composite:

```text
ee6a81105af15256fac596b691f87831902a45f14d7c8b96bc815e6071084929
```

The 13 production-file hashes are recorded in the Stage 0 frozen fixture and
were independently rechecked by the Stage 0 covenant test.

### 7. Browser, Runtime, and Broker-Read-Only Proof

- Browser: **NOT RUN**. Stage 3 added no UI and claims no browser proof.
- Runtime/backend launch: **NOT RUN**. No process was started and no production
  catalog was accepted.
- Broker read-only: **NOT RUN**. No real `/v2/assets` request occurred; Stage 12
  remains the separately authorized external-proof boundary.
- PAPER/broker mutation: **NOT RUN and not authorized**. No order, cancel,
  close, liquidation, or position mutation occurred.

### 8. Self-Red-Team and Anti-Hallucination Review

Mandatory review cycle 1 found three material gaps:

1. Direct `InstrumentRegistry.validate_order()` could still approve a static
   non-authoritative crypto row. It was changed to refuse, and a direct bypass
   test was added.
2. The supervisor described the operator list as priority-only but the child
   discarded its ordering. Full-universe transport now preserves ordering, and
   outside/malformed priorities block independently.
3. Direct monitor-only resolver refusal and future-dated universe evidence were
   under-tested. Both negative paths received production-path tests.

Mandatory review cycle 2 found four strictness gaps:

1. Non-string broker asset identity/exchange fields could be coerced with
   `str()`. Normalization now rejects them.
2. StateStore could normalize malformed identity/reason fields during strict
   reads. Schema validation now rejects them.
3. Malformed priority values could disappear during normalization. Child boot
   now refuses them explicitly.
4. Non-string account suffixes could stringify into the pin, and malformed
   held/open-order symbols could disappear. All now fail closed.

All results before those fixes were invalidated. Review cycle 3 re-read the
fresh full diff, traced unhappy paths and authority ownership, reran exact-tree
validation, and found no unresolved in-scope defect.

Review cycle 4 found a documentation-evidence omission after the first cached
audit: the close report recommended the audit but did not record its actual
membership/check/stat result. The report, tracker, and handoff were amended with
that evidence; behavior files and their fingerprint did not change. The three
documents were revalidated, re-staged individually, and the cached audit was
repeated before commit.

What was actually inspected: every changed production/test/fixture file; direct
callers of the static/dynamic registries; supervisor start and child boot;
adapter and read-policy method/path enforcement; snapshot write/read integrity;
run-path positive coverage; the full diff; skip mechanisms; dependency/deletion/
secret/threshold scans; and protected-worktree scope.

What tests prove: deterministic offline normalization/derivation/persistence,
strict corruption and stale/future refusal, static non-authority, full-universe
transport, surviving run-path behavior, and no regression in the configured
local suite.

What remains inference or unknown: actual Alpaca catalog shape and coverage for
the pinned account, external connectivity, real market-data capacity, runtime
refresh behavior, execution quality, SELL implementation, and profitability.
No claim in this report promotes those unknowns to proof.

### 9. Safety Confirmation

- No Risk, NetEdge, economics, sizing, TTL, masking, strategy, OMS,
  reconciliation, account-pin, no-short, or broker-governor threshold weakened.
- No manual buy/sell, force-trade, live mode, real-money path, hidden mutation,
  fake broker truth, fake order, fake fill, or fake P&L was added.
- `SovereignExecutionGuard` remains dormant.
- MarketTruthSnapshot remains executable market-truth authority; broker catalog
  membership alone cannot authorize an order.
- Position-backed monitoring is preserved independently of new-entry refusal.
- Static sophistication is preserved as reference evidence and stripped only of
  authority it should never have owned.
- No module or file was deleted. No new dependency or subsystem was introduced.
- Protected `state/*`, `.pytest_tmp/`, legacy reports/scripts, secrets, logs,
  screenshots, and operator-performance output were not edited or staged.

### 10. Module Status

| Module | Final Stage 3 status and role |
|---|---|
| `broker_read_policy` | WIRED: exact catalog GET admission; mutation denial |
| `alpaca_paper_adapter` / `broker_gateway` | WIRED contract, producer BLOCKED until authorized real read |
| `capability_registry` | WIRED: sole deterministic catalog/universe derivation owner |
| `venue_capabilities` | WIRED: explicit exact broker constraints/provenance evidence |
| `StateStore` | WIRED: immutable, hash/count/time/account-bound evidence persistence |
| `InstrumentRegistry` | WIRED as static reference/display fixture; execution authority refused |
| operator supervisor/config | WIRED: pinned snapshot start admission and priority-only metadata |
| `main.py` / `main_loop` | WIRED offline contract: strict dynamic registry injection and full-universe enrollment |
| intelligence portfolio spine | WIRED: consumes injected capability facts; no static rescue |
| Risk, NetEdge, sizing, MarketTruthSnapshot, OMS, reconciliation | PRESERVED active owners; unchanged by Stage 3 |
| Alpaca SELL adapter path | BLOCKED until Stage 8; no external SELL capability claimed |
| production catalog acquisition/acceptance | BLOCKED until later authorized stage; no silent fallback |
| continuous catalog refresh and scalable feed batching | BLOCKED until Stage 4 |

No in-scope module is silently dormant or ambiguously authoritative.

### 11. Disagreements / What I Would Do Differently

No unresolved safety or go-live disagreement exists. I would not interpret
"open the bot up" as deleting the catalog intersection or weakening economic
and risk gates. Stage 3 removes an artificial six-symbol nomination authority
while replacing it with stricter broker/account/data/adapter evidence. I also
would not call this production-ready until the later producer, refresh, feed
capacity, execution, reconciliation, and long-run stages independently pass.

### 12. Limitations and Unknowns

1. No real `/v2/assets` GET occurred, so actual broker/account catalog content
   and current eligible-symbol count are unknown.
2. The adapter exposes the exact GET, but no production catalog producer or
   governed acceptance workflow calls/persists it yet. Real operator start
   therefore fails closed until a later stage wires that producer.
3. Catalog evidence is checked at supervisor start, immediately before spawn,
   and at child boot. Continuous refresh/in-run expiry is Stage 4 and is not
   proven here.
4. Existing per-symbol polling cannot yet scale across a broad broker universe;
   batching/rate budgeting/ranking is Stage 4.
5. Dynamic capability truth represents position-backed `sell_to_close`, but the
   Alpaca execution adapter remains BUY-only until Stage 8. No external SELL
   submit was tested.
6. Snapshot hashes provide integrity and deterministic identity, not a signed or
   authenticated provenance chain.
7. The 14 integration skips remain conditional external/mutation gates. They
   are documented, preserved, and not counted as passes.
8. The 420 full-suite warnings are existing deprecation/runtime warnings and
   were not hidden. They did not fail this stage but remain technical debt.
9. No browser, launched runtime, broker-read-only, PAPER, long-duration,
   profitability, latency, or multi-tenant proof was performed.

### 13. Exact Staging Recommendation

Stage exactly the 38 files listed in Section 2: the 35 frozen behavior files,
this report, `CHECKPOINT_TRACKER.md`, and `reports/codex_handoff_latest.md`.
Use explicit per-file `git add`; verify cached name list, whitespace check, and
stat before commit. Never stage protected `state/*`, `.pytest_tmp/`, old
handoffs, UI proposal packets, operator-performance output, screenshots, logs,
secrets, or untracked audit scripts.

### Research Used

Official Alpaca Trading API asset documentation informed the exact catalog
request, tradable/status/class semantics, and precision fields. Dynamic-universe
patterns from professional trading and observability systems informed immutable
snapshot IDs, provenance, explicit exclusion reasons, entry-versus-monitor
membership, and fail-closed expiry. Applied lessons: broker facts are canonical,
universe derivation is reproducible, constraints retain exact decimal text, and
operators need reason-coded exclusions. Rejected lessons: opaque auto-discovery,
silent cache fallback, UI-only green status, ranking-by-trade-count, and any
catalog fact acting as order authority.

PRE_CLOSE_REVIEW: PASS
