# PAPER True Capability Stage 2 Report

Date: 2026-07-18 America/Chicago
Stage: 2 - Consolidate broker inventory, lots, fills, and reservations
Branch: `master`
Stage-entry HEAD: `f462356d140eaf0acccfd5be05faeb01536ae989`
Board direction: Shan approved Stage 0, directed Stage 1 to proceed, added the
mandatory pre-close review loop, and then directed `proceed` on 2026-07-18.
Close status: **PASS - LOCAL OFFLINE TEST RUNG**

## Stage-Entry Manifest

`AGENTS.md` v3, including binding Sections 23, 24, and 25, was re-read in full
before any Stage 2 source, test, configuration, schema, or runtime edit. The
current tracker, latest handoff, approved master plan, Stage 0 fixture, Stage 1
report, branch and dirty tree, affected production callers, state schemas,
broker adapter contracts, Risk/OMS contracts, baseline behavior, and focused
tests were inspected. This report is the first Stage 2 file edit.

### 1. Stage objective and binary exit

Objective: make the existing StateStore -> Reconciliation -> ExposureManager ->
Risk and StateStore -> OMS/OrderRouter authority chain carry a complete,
durable, broker-backed account inventory before any new PAPER entry can be
admitted. Inventory must distinguish opening baseline quantity, bot-acquired
quantity, pending BUY/SELL reservations, sold quantity, and unknown attribution
without creating another portfolio database or weakening any trading control.

Binary exit:

1. a cold start for the current four protected holdings reconciles the pinned
   PAPER account, complete broker position book, open orders, durable mappings,
   reservations, and known fills before new entries can be admitted;
2. ExposureManager's total quantity equals the broker snapshot for every symbol
   and identifies `ADOPTED_BASELINE`, `BOT_ACQUIRED`, `PENDING_BUY`,
   `PENDING_SELL`, `SOLD`, and `UNKNOWN_ATTRIBUTION` explicitly;
3. baseline quantity plus bot-acquired quantity minus sold quantity equals
   broker quantity for known attribution, while pending reservations and
   available cash/owned quantity balance without oversubscription;
4. same-symbol BUY is no longer refused solely because the symbol existed at
   startup, but missing, stale, account-mismatched, quantity-mismatched,
   unpriced, or unknown-attribution inventory still fails closed;
5. candidate metadata can identify an immutable reconciliation snapshot but
   cannot inject quantities, positions, orders, reservations, or lot-tracking
   permission into Risk or the protected-baseline guard;
6. duplicate, partial, late, corrected, busted, rejected, expired, canceled,
   and replaced lifecycle evidence is deterministic and idempotent across
   restart, with no double inventory or realized P&L application;
7. no executable inventory quantity is converted to float or rounded by a
   non-broker quantity step; missing Alpaca crypto increment truth stays
   explicit and fail-closed where increment validation is required;
8. the Alpaca adapter remains BUY-only until Stage 8, so Stage 2 does not enable
   SELL, naked SELL, shorting, or broker mutation; and
9. focused, adversarial, restart/recovery, run-path, mutation-audit, and full
   configured offline suites pass on the exact final candidate tree, followed
   by the Section 25 pre-close review loop.

### 2. Stop conditions

Stop immediately if:

- a second lot, position, reservation, fill, portfolio, Risk, OMS, broker, or
  reconciliation authority would be created outside StateStore,
  ReservationLifecycleCoordinator, ExposureManager, OMS/OrderRouter, and the
  existing reconciliation boundary;
- any Risk, NetEdge, fee, spread, slippage, impact, sizing, utilization,
  concentration, correlation, cash-reserve, TTL, stale-data, strategy, masking,
  account-pin, endpoint, no-short, or no-naked-SELL control must weaken;
- the active Alpaca adapter must accept SELL before Stage 8, or a test requires
  a POST, DELETE, cancel, close-all, liquidation, manual order, fake fill, fake
  broker position, or real broker request;
- the legacy float `positions` or `fills` table, signal metadata, the accepted
  opening-baseline file, or a new database becomes a competing inventory owner;
- broker quantity has to be rounded using the legacy Kraken registry, the
  static capability fixture, a hardcoded Alpaca crypto increment, or a float;
- a mismatch is hidden by force-sync, an unexplained broker delta is assigned
  to a bot lot, a cumulative status observation is summed as another delta, or
  a correction/bust is silently treated as a new fill;
- startup recovery mutates broker state, discards an unknown row, overwrites
  the original opening baseline, or admits a candidate before full-book
  reconciliation passes;
- a scoped restriction becomes `UNKNOWN`, a fingerprint changes before its
  intentional edit, another actor changes a scoped file, or files outside the
  declared feature area enter the diff;
- a required binary gate fails twice, the same blocker recurs for three work or
  review cycles, or Section 25 cannot produce a passing pre-close verdict.

### 3. In-scope files

Planned production owners:

- `app/state/state_store.py` - add backward-aware, idempotent SQLite fact and
  immutable projection persistence using TEXT decimal quantities; keep the
  legacy float tables preserved but non-authoritative;
- `app/risk/exposure_manager.py` - ingest one complete reconciled broker book,
  preserve per-sleeve lots in its existing inventory authority, expose immutable
  reconciliation evidence, and fail closed on missing/unknown book truth;
- `app/risk/reservation_lifecycle_coordinator.py` - become the existing narrow
  reconciliation transaction coordinator for startup snapshots and fill/event
  projection while retaining StateStore as durable fact owner and
  ExposureManager as portfolio-risk owner;
- `app/execution/order_router.py` - obtain existing authorized PAPER broker GET
  responses, persist broker fill/event facts, and delegate full-book snapshots
  to the existing coordinator; retain sole order-lifecycle authority;
- `app/operator_activation/paper_baseline.py` - preserve the immutable opening
  acceptance and add managed reconciliation lineage so lawful fills do not look
  like unexplained baseline drift;
- `app/main_loop.py` - consume canonical ExposureManager snapshot/lot evidence
  for portfolio and baseline admission, and stop accepting quantity authority
  from signal metadata;
- `main.py` - cold-start wiring and fail-closed startup status using the existing
  broker adapter, StateStore, coordinator, ExposureManager, and OrderRouter;
- `tests/test_paper_true_capability_stage2.py` - Stage 2 positive, negative,
  adversarial, temporal, idempotency, concurrency, restart, and mutation proof.

Planned proof/governance files:

- directly affected existing tests only where a fixture must supply lawful
  canonical reconciliation evidence or an assertion must stop granting signal
  metadata inventory authority; every intent change will be logged;
- `tests/fixtures/paper_true_capability_stage0.json` and
  `tests/test_paper_true_capability_stage0.py` - preserve historical Stage 0/1
  records and append/test an explicit Stage 2 source-delta ledger;
- this report, `CHECKPOINT_TRACKER.md`, and
  `reports/codex_handoff_latest.md` - entry, findings, proof, limitations,
  Section 25 review, Board rulings, and next boundary.

The source list may narrow. It may not expand into catalog/universe, strategy,
UI, cloud, tenant, live, or Stage 3+ work without a fresh scope-tripwire review.

### 4. Forbidden and unrelated files

Do not edit or stage UI/icon/launcher/cockpit files; operator runtime state;
credentials; live adapters or live behavior; catalog/universe breadth; strategy
models or thresholds; MarketTruthSnapshot, NetEdge, sizing, masking, risk limits,
AI, cloud/AWS, tenant code, state/log/database files, screenshots,
`reports/operator_perf/**`, old handoffs, proposal packets, or untracked audit
scripts. Do not run PAPER, a browser, a live process, or any broker request.
Do not activate `SovereignExecutionGuard`, enable adapter SELL, add a dependency,
add a subsystem, or delete a preserved module.

### 5. Current branch, commit, and complete dirty-worktree record

Current branch is `master`; entry commit is
`f462356d140eaf0acccfd5be05faeb01536ae989` (`require pre-close review loop`).
Stage 1 is closed and pushed at `4453209`; the icon-only commit `353ee65` and
later governance commits do not alter Stage 2 product truth.

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

| Module/area | Live-repo truth at entry | Classification and allowed authority | Stage 2 disposition |
| --- | --- | --- | --- |
| `StateStore` | Durable WAL SQLite owner; Decimal reservation/fill ledgers exist, but legacy positions/fills use REAL and no durable lot/full-book projection exists | `WIRED_WITH_ROLE`, durable fact owner only | Add immutable broker snapshots, lifecycle events, and lot projections in the same DB; no Risk or broker authority |
| `broker_fill_ledger` | Durable fill IDs and Decimal text fields; status observations can be cumulative and no inventory projection consumes them | `WIRED_WITH_ROLE`, broker fill evidence | Preserve; make delta-vs-cumulative semantics explicit and project idempotently |
| `order_id_mappings` | Durable client/broker/order namespace mapping with startup reconcile | `WIRED_WITH_ROLE`, OMS identity evidence | Preserve and use for fill/reservation attribution and unknown-order detection |
| reservation ledger/tombstones/progress | Decimal and release-once persistence; survives ack/partial/terminal restart | `WIRED_WITH_ROLE`, OMS reservation facts | Preserve; include BUY/SELL balance in reconciled inventory evidence |
| `ReservationLifecycleCoordinator` | Runtime-wired despite stale module/doc wording; translates direct lifecycle facts into guarded ExposureManager/StateStore calls but does not apply inventory lots | `WIRED_WITH_ROLE`, reconciliation transaction coordinator, never final Risk or broker authority | Extend existing coordinator; correct stale status wording; no parallel service |
| `ExposureManager` | Canonical portfolio-risk authority; only reservations hydrate at startup; inventory is empty until local fills/force-sync | `WIRED_WITH_ROLE`, sole portfolio/inventory Risk view | Ingest complete validated broker projection and expose its snapshot evidence |
| `force_inventory_sync_detailed` | Deletes symbol reservations and sleeve attribution, then rebuilds aggregate quantity | `EMERGENCY_COMPATIBILITY`, not lawful normal startup reconciliation | Preserve untouched and prove Stage 2 never calls it |
| `OrderRouter` | Sole OMS/broker lifecycle owner; reads broker status/orders/positions/account after ack and writes fill ledger | `WIRED_WITH_ROLE`, sole order lifecycle and broker boundary owner | Add read-only full-book handoff and event semantics; no second submission path |
| Alpaca PAPER adapter | PAPER endpoint/pin enforced; GET/POST/DELETE surface exists, but `_payload_for_order` permits only BUY LIMIT | `PERMANENT_SAFETY_CONTROL` plus Stage 8 lifecycle boundary | Preserve BUY-only request validation and zero mutation during Stage 2 proof |
| accepted PAPER baseline | Immutable, governed opening snapshot; runtime context hardcodes lot tracking false and compares current positions only to opening signature | Opening truth is `WIRED_WITH_ROLE`; blanket same-symbol veto is `COMMISSIONING_OR_TEST_SCAFFOLD` | Preserve opening snapshot; replace blanket veto only after reconciled lot owner proves quantity |
| `MainLoop` portfolio bridge | Passes signal metadata positions/open orders/reservations to ExposureManager; passes metadata lot-tracking flag/run quantity to baseline guard | `COMMISSIONING_OR_TEST_SCAFFOLD` around valid Risk authority | Metadata keeps IDs only; canonical ExposureManager evidence supplies book and lot facts |
| `TruthReconciler`/TruthKernel | Existing stateless cross-truth comparison and truth-frame owner; not a persistent inventory engine | `WIRED_WITH_ROLE`, reconciliation status contributor | Preserve; do not turn it into a second portfolio store or replace it |
| legacy `positions`/`fills` tables | REAL float storage used by legacy compatibility/reporting | `PRESERVED_COMPATIBILITY`, not executable inventory authority | Do not delete or promote; new executable quantities remain Decimal TEXT |

One-owner graph after Stage 2 remains: Broker owns acknowledged external
account/order/position truth; StateStore owns durable facts; Reconciliation and
its existing coordinator own attribution/status projection; ExposureManager
owns the complete portfolio view and portfolio Risk; Risk owns admission;
OMS/OrderRouter owns order lifecycle and the broker boundary; accepted baseline
owns immutable opening truth; MainLoop consumes evidence; UI and AI remain out
of scope and non-authoritative.

### 7. Current-behavior evidence and restriction ledger

Named repo evidence:

- `SovereignHeartbeat._bootstrap_reservation_lifecycle_disabled` creates
  ExposureManager and hydrates only reservation rows, tombstones, and fill
  progress. It never hydrates positions or broker fill lineage. Its name,
  docstring, and `runtime_lifecycle_wired: False` status contradict actual
  OrderRouter wiring.
- `ExposureManager.evaluate_pre_trade_portfolio_gate` uses internal book values
  when nonzero and external metadata values only when internal values are zero.
  A partially hydrated internal book can therefore omit other broker holdings.
- `MainLoop._apply_portfolio_risk_gate_to_signal` supplies
  `existing_positions`, `open_orders`, and `reservations` from signal metadata.
- `MainLoop._build_pre_trade_guardrail_verdict` supplies
  `run_acquired_qty` and `paper_baseline_lot_tracking_available` from signal
  metadata, so a candidate can claim the fact that removes the baseline veto.
- `build_paper_baseline_runtime_context` always emits
  `run_lot_tracking_available=False`; protected same-symbol entries therefore
  remain blocked regardless of durable fill evidence.
- `StateStore` stores reservations and broker fills as Decimal text but has no
  broker inventory snapshot, event semantics, or lot projection tables. Legacy
  `positions` and `fills` use SQLite REAL.
- `OrderRouter._hydrate_fill_ledger_from_broker_payload` can record either a
  broker-activity fill delta or a cumulative broker-order status using the same
  generic `quantity` field. Summing both would double inventory.
- `ReservationLifecycleCoordinator.on_partial_fill/on_full_fill` update
  reservation progress/release only. `ExposureManager.handle_fill_detailed`
  updates inventory but has no broker fill ID dedupe and is not called by the
  coordinator.
- `ExposureManager.force_inventory_sync_detailed` removes reservations and
  sleeve attribution, so it is not acceptable as normal reconciliation.
- Alpaca `_payload_for_order` rejects every non-BUY request with
  `only_buy_supported`; Stage 2 cannot enable SELL.
- The active Alpaca crypto capability contract has `quantity_step=None`; the
  legacy `InstrumentRegistry` contains floats and identifies crypto rows as
  Kraken. Neither is broker-canonical Alpaca quantity-step truth.

| Restriction/defect | Exact owner | Classification | Stage 2 action |
| --- | --- | --- | --- |
| Blanket protected-baseline same-symbol block | `paper_baseline.evaluate_protected_baseline_trade` plus MainLoop metadata bridge | `COMMISSIONING_OR_TEST_SCAFFOLD` | Narrow only when canonical full-book/lot reconciliation proves known quantity; preserve refusal otherwise |
| Metadata-supplied position/order/reservation book | `MainLoop` -> `ExposureManager.evaluate_pre_trade_portfolio_gate` | `COMMISSIONING_OR_TEST_SCAFFOLD` | Remove from active authority; permit immutable snapshot IDs only |
| Metadata-supplied lot-tracking permission | `MainLoop._build_pre_trade_guardrail_verdict` | `COMMISSIONING_OR_TEST_SCAFFOLD` | Replace with ExposureManager reconciliation evidence |
| Reservation-only startup hydration | `main.SovereignHeartbeat` bootstrap | `COMMISSIONING_OR_TEST_SCAFFOLD` | Hydrate complete broker book and known lineage before admission |
| Destructive force-sync | `ExposureManager.force_inventory_sync_detailed` | `PRESERVED_COMPATIBILITY` emergency path | Preserve but never call from Stage 2 normal or recovery path |
| Legacy REAL position/fill storage | `StateStore` | `PRESERVED_COMPATIBILITY` | Preserve; do not use for executable inventory |
| Missing Alpaca crypto quantity step | capability/catalog boundary | `BLOCKED_WITH_REASON` pending Stage 3 broker catalog | Store exact Decimal; validate step only when broker-canonical value is present; never invent one |
| Risk/NetEdge/sizing/fees/slippage/impact/TTL/strategy limits | existing authority graph | `QUANT_OR_ECONOMIC_CONTROL` | Preserve exact values and fingerprints |
| Account pin/PAPER endpoint/real-money lock | adapter/credential/supervisor authorities | `PERMANENT_SAFETY_CONTROL` and `GOVERNANCE_OR_ARMING_CONTROL` | Preserve; mismatch blocks reconciliation and admission |
| BUY-only Alpaca adapter | `AlpacaPaperBrokerAdapter._payload_for_order` | `GOVERNANCE_OR_ARMING_CONTROL` until Stage 8 governed lifecycle proof | Preserve exact behavior; Stage 2 does not enable SELL |
| No naked SELL/no short/broker-backed reduce-only | Risk/guardrails/adapter | `PERMANENT_SAFETY_CONTROL` | Preserve unchanged |
| Strict broker-read profile | broker read policy | `GOVERNANCE_OR_ARMING_CONTROL` | Preserve; no Stage 2 external GET is executed in this session |

There is no unresolved `UNKNOWN` restriction in the affected Stage 2 ledger.
Missing Alpaca crypto increments are a named Stage 3 blocker, not permission to
substitute a value or skip quantity identity checks.

### 8. Baseline fingerprints before implementation

Source SHA-256 at entry:

| File | SHA-256 |
| --- | --- |
| `app/state/state_store.py` | `55c55e69be48f5fdabd9866ed5b493e7c0d4fd2d9ef24cf4d12b0b7c55eefd6f` |
| `app/risk/exposure_manager.py` | `8a32e482d95e73077a10ef8d2b6a14113a339f51c75ac58bb8e78db9b5613cf0` |
| `app/risk/reservation_lifecycle_coordinator.py` | `d7910b57d375557392ebab8fef38a170093c37f1fedce25eb2cb672ac0e1ed0b` |
| `app/execution/order_router.py` | `25eb401926dac08910dc5eb61461b6019ba58f8543d2685deede4524a87e0b12` |
| `app/operator_activation/paper_baseline.py` | `e68df099a6e99746840a1133213374c632e6422d8a347a556081ca84e9e3d407` |
| `app/main_loop.py` | `cb37f160d59b7c60926f9272ec4be1cd17fa447d9677f397a4a1fa669f34667e` |
| `main.py` | `b55a5c447dac339d5f950e9fa0234df98111bde4d89f94bbdeba9c8cc3c211da` |
| `tests/fixtures/paper_true_capability_stage0.json` | `e320dba9203b5be84bbaa3a74e356eac12f90d3aa90a5f46942ca81348bf773f` |

Affected value/control fingerprints required unchanged at close:

- runtime portfolio Risk: utilization `0.50`, per-asset concentration `0.15`,
  cash reserve `0.10`, correlation threshold `0.80`, correlation slash `0.50`,
  policy `P3B_B1_V1`;
- ExposureManager model defaults: max utilization `0.80`, max asset
  concentration `0.25`, quantity step `0.0001`, minimum reservation quantity
  `0.0001`, stale reservation `5,000,000,000 ns`, mark stale
  `10,000,000,000 ns`; root overrides only the two documented portfolio values;
- sleeve caps: ShadowFront `0.40`, GammaFront `0.30`, LiquidityVoid `0.20`,
  SectorRotation `0.20`, AdaptiveDC `0.10`, HedgingFlow `0.50`, aggregate `1.00`;
- protected baseline default: `BLOCK_BASELINE_SYMBOL_TRADES_UNTIL_RUN_LOT_TRACKING`;
- Alpaca crypto capability: BUY and `sell_to_close` declared at guardrail level,
  min notional `10.00`, quantity step unknown; actual adapter remains BUY-only;
- adapter mutation surface: `submit_order` POST `/v2/orders`; `cancel_order`
  DELETE `/v2/orders/{id}`; `_payload_for_order` requires BUY LIMIT; Stage 2
  expected POST and DELETE count is zero;
- broker read families and strict read profile remain unchanged; account,
  positions, and open orders are the only startup truth needed by this stage;
- account suffix pin, paper endpoint, live lock, real-money lock, no naked SELL,
  no short, broker-backed reduce-only, Risk, NetEdge, fees, spread, slippage,
  impact, TTL, sizing, masking, strategy thresholds, OMS singleton authority,
  and final reconciliation remain unchanged;
- Stage 0 module classifications and Stage 1 source delta records remain
  historical and are appended, never rewritten.

### 9. Mathematical and state-model inventory

Inventory identity per normalized symbol `s`, using exact Decimal quantities:

```text
broker_qty[s]
  = adopted_baseline_remaining[s]
  + bot_acquired_remaining[s]
  + unknown_attribution_delta[s]

bot_acquired_remaining[s]
  = sum(active reconciled BUY fill deltas)
  - sum(reconciled SELL allocations against bot-acquired lots)

available_to_buy_notional
  = broker cash or non-marginable buying power
  - active broker/durable BUY reservation notional

available_to_sell_qty[s]
  = broker_qty[s]
  - active PENDING_SELL quantity[s]
```

`UNKNOWN_ATTRIBUTION` is signed reconciliation delta, not a fabricated lot.
Any nonzero unknown delta blocks same-symbol mutation. Pending BUY affects cash
and projected exposure but not filled broker quantity. Pending SELL affects
available owned quantity but does not reduce filled broker quantity before a
broker-confirmed fill.

Inputs and units:

- quantity: broker-native asset units, `Decimal` text, finite and nonnegative
  for long-only PAPER holdings;
- price: quote-currency units per asset unit, `Decimal` text, finite and
  positive where exposure valuation or WAP is claimed;
- notional: quote currency, quantity multiplied by price with Decimal
  arithmetic;
- timestamps: integer nanoseconds for observed/application order plus broker
  timestamp text/parsed nanoseconds where present;
- identity: pinned account suffix, normalized symbol, broker/client order ID,
  broker fill/activity ID, baseline snapshot ID, reconciliation snapshot ID,
  reservation ID, and immutable payload fingerprint.

Event estimator/ordering contract:

- broker activity fill IDs represent deltas;
- broker order status `filled_qty` represents cumulative quantity and only the
  latest causally ordered value per order contributes when delta activities are
  unavailable;
- duplicate event ID with the same payload is idempotent; a changed payload
  under the same ID is a conflict;
- `TRADE_CORRECT` supersedes the named fill and rebuilds the affected projection;
  `TRADE_BUST` removes the named fill effect; rejection, expiration,
  cancellation, and replacement without fill have zero inventory effect;
- late evidence triggers deterministic reprojection, never incremental
  double-application;
- bot-acquired SELL allocation is deterministic and lot-preserving; Stage 2
  cannot submit such a SELL, but historical/replay evidence must reconcile.

Assumptions and uncertainty:

- the broker position snapshot is canonical after successful PAPER GET and
  account-pin proof; local lots explain it but never override it;
- the accepted baseline is immutable opening truth, not perpetual current
  position truth;
- strict broker reads may not supply account activities, trade corrections,
  trade busts, fees, or broker quantity increments. Missing facts remain
  explicit; they do not become zero, a guessed increment, or positive authority;
- fee/TCA/P&L attribution remains owned by the existing broker fill and TCA
  path. Stage 2 prevents duplicate inventory application and does not claim
  complete fees or profitability;
- no float conversion is permitted for executable inventory. NaN, Infinity,
  invalid Decimal, duplicate symbol, negative long quantity, missing price when
  valuation is required, stale snapshot, unresolved order, or account mismatch
  fails closed;
- this stage is single-process and single-tenant. SQLite transactions and the
  existing process/lease authority protect local atomicity; future tenant
  isolation remains deferred under Section 24.

Known numerical limitation: Alpaca crypto `quantity_step` is unavailable in the
current active capability contract and broker asset catalog work is Stage 3.
Stage 2 can prove exact quantity identities and reject a non-multiple when a
broker-canonical step is supplied, but it cannot honestly certify the current
broker's per-symbol minimum increment without Stage 3 evidence.

### 10. Planned validation matrix

Positive tests:

- cold boot with AVAXUSD `10`, ETHUSD `2`, LINKUSD `25`, SOLUSD `8` produces
  exact `ADOPTED_BASELINE` lots, complete ExposureManager book, immutable
  opening snapshot lineage, zero unknown quantity, and same-symbol BUY eligible
  for downstream unchanged gates;
- reconciled partial/final BUY fills create one `BOT_ACQUIRED` quantity and
  advance managed current truth without rewriting opening baseline;
- candidate metadata carries the reconciliation snapshot ID while Risk reads
  quantity directly from ExposureManager;
- complete account cash, broker book, and reservations balance across restart.

Negative/adversarial tests:

- missing position snapshot, stale snapshot, account-pin mismatch, wrong account,
  duplicate symbol, invalid/negative/nonfinite Decimal, price absence, unknown
  broker order, broker/local quantity mismatch, unknown attribution, and
  malformed correction/bust block admission without mutation;
- forged `existing_positions`, `run_acquired_qty`, or
  `paper_baseline_lot_tracking_available=True` metadata cannot grant authority;
- cumulative partial/final observations do not sum twice; broker activity delta
  supersedes cumulative fallback; same ID/different payload conflicts;
- late fill, duplicate fill, correction, bust, rejection, expiration,
  cancellation, and replacement reproject deterministically;
- concurrent BUY reservations cannot exceed cash/Risk limits and concurrent
  SELL reservations cannot exceed broker-confirmed available owned quantity;
- emergency force-sync is never called; adapter SELL remains rejected; no naked
  SELL, short, live endpoint, or real-money route becomes reachable.

Temporal/property/replay/parity/restart tests:

- event permutations with the same causal facts yield the same final lot book;
- snapshot and lot quantity identities hold for generated Decimal quantities;
- restart after ack, partial fill, final fill, correction, and release hydrates
  the same projection once;
- broker status fallback and broker activity event paths converge when they
  describe the same fills;
- full-book ExposureManager totals equal persisted reconciliation projection
  and broker snapshot for every symbol.

Performance and mutation audit:

- schema initialization/migration is idempotent and bounded; projection rebuild
  is measured on a representative event/book set without network access;
- instrument all broker adapter mutation methods, OrderRouter mutation methods,
  cancel/close/liquidation surfaces, and transport calls; expected count is zero;
- run focused Stage 2 tests, existing baseline/reservation/OMS/exposure tests,
  named dispatch/decision/Risk/execution/recovery run-path tests, syntax/import
  checks, then the full configured offline suite on the final tree;
- run the mandatory Section 25 review loop, fix findings, invalidate stale
  results, and rerun every affected and broader gate.

No browser proof applies because Stage 2 has no UI scope. No runtime process,
external broker read, PAPER run, or live proof is authorized in this stage
session.

### 11. Proof and approval boundary

Authorized now: reversible source/test/schema/report work in the declared
feature area; temporary SQLite databases under pytest temp directories; mocked
PAPER adapter GET responses; focused/full offline tests; static/import checks;
tracker/handoff updates; exact per-file commit and push on `master` under the
current Board direction.

Not authorized: actual broker GET; bounded or autonomous PAPER run; POST/DELETE;
cancel; SELL; close-all; liquidation; live credential or endpoint action; real
money; external dependency; new subsystem/database; module deletion; Stage 3
catalog work; UI/browser work; cloud/AWS; multi-tenant activation; staging any
protected state/log/database/screenshot/secret/unrelated report or audit file.

Offline tests may prove logic and mocked wiring only. They may not be reported
as runtime, browser, broker-read, external fill, PAPER, or readiness proof.

### 12. Pre-code independent red team

**How could this degrade or simplify the bot?** Replacing ExposureManager with a
flat position dictionary, discarding per-sleeve attribution, converting Decimal
to float, treating current broker quantity as one aggregate lot, or ignoring
corrections would flatten existing capability. The plan instead retains all
owners, stores immutable facts/projections, and hydrates ExposureManager's
existing position and reservation model.

**How could this bypass a guard?** A boolean `lot_tracking_available`, especially
from candidate metadata or configuration, could turn off the baseline veto
without proving quantity. The replacement permission must be derived only from
the current pinned-account reconciliation snapshot, exact lot identity, and
reservation balance. Any missing fact leaves the existing refusal active.

**How could this create duplicate authority?** A new lot manager, another DB,
baseline-as-current-position store, MainLoop book, or signal metadata book would
compete with StateStore/ExposureManager/OMS/Reconciliation. The design adds
tables and methods only inside existing owners; MainLoop receives evidence but
does not store or decide portfolio truth.

**How could it fake proof?** Mocked broker responses could be called broker-read
proof, or a passing same-symbol guard unit test could be called a runnable bot.
The report will label every result by proof rung. No current broker request or
PAPER run is authorized, so external truth remains not run.

**How could it lose state?** Clearing/replacing mutable lots, using force-sync,
updating memory before SQLite, or handling a late correction incrementally could
lose lineage or double inventory. The target uses immutable snapshots/events,
transactional projection writes, payload conflict detection, deterministic
reprojection, then ExposureManager hydration only after the durable commit.

**How could configuration hide behavior?** A new flag or environment variable
could silently opt out of reconciliation. No new activation flag is planned.
External PAPER selection makes complete-book reconciliation required; internal
simulation remains explicitly non-external and cannot impersonate broker truth.

**How could math be simplified or wrong?** Summing cumulative fills, rounding by
the legacy registry, treating pending orders as filled, subtracting BUY
reservations from quantity, or allocating sells beyond owned bot lots would
produce false inventory. Tests will cover delta/cumulative semantics, Decimal
identities, event permutations, reservations, corrections/busts, and unknown
deltas.

**How could green tests mask broken runtime?** Tests could call the coordinator
directly while `main.py` never invokes it; use a full snapshot while the real
adapter returns malformed rows; or leave MainLoop reading spoofable metadata.
Named root-bootstrap, OrderRouter handoff, MainLoop admission, restart, and
run-path tests must survive, and Section 25 must inspect every caller after the
implementation appears complete.

**Could Stage 2 accidentally enable SELL?** Yes, if the adapter's BUY-only
validation is broadened while adding sell provenance. The adapter source and a
negative adapter SELL test are frozen controls. Stage 2 may reconcile historical
SELL evidence but cannot submit it.

**Could startup GETs become hidden mutation?** Adapter response metadata and
transport method counts must prove GET-only. Unit tests instrument submit,
cancel, close, liquidation, and transport mutation surfaces. Actual broker GETs
remain outside this session's approval.

**Could an accepted baseline become a second current authority?** Yes, if its
file is rewritten after every fill. The opening acceptance remains immutable;
managed current state is a separately identified reconciliation lineage in
StateStore and ExposureManager. Baseline drift is explained by that lineage,
not hidden by changing history.

**Stop verdict:** the seam survives pre-code red team only under the declared
owner chain, exact Decimal and event semantics, immutable opening baseline,
BUY-only adapter preservation, fail-closed unknown state, and full Section 25
review. Any deviation triggers the stop conditions above.

### 13. Research used at entry

Official Alpaca documentation was reviewed for patterns, not copied code:

- Orders at Alpaca: order lifecycle states include new, partial fill, fill,
  cancellation, expiration, rejection, and replacement.
  <https://docs.alpaca.markets/us/docs/orders-at-alpaca>
- Alpaca activity stream: financial state changes distinguish fills, trade
  corrections, and trade busts from non-fill lifecycle activity.
  <https://docs.alpaca.markets/us/docs/activity-sse>
- Alpaca trade updates: execution updates include execution/order identity,
  position quantity, quantity, price, and timestamp.
  <https://docs.alpaca.markets/v1.4.2/docs/websocket-streaming>
- Alpaca positions: current broker positions are retrieved from `/v2/positions`
  and remain broker-canonical after acknowledgement.
  <https://docs.alpaca.markets/us/docs/working-with-positions>

Applied lessons: separate fill deltas from cumulative order state; preserve
execution IDs; model corrections/busts explicitly; reconcile against the whole
current position book; keep non-fill terminal states from changing inventory.
Rejected: inferring fills from status labels alone, treating any local fill as
broker truth, polling activities without the existing read authorization, and
hardcoding broker quantity increments before Stage 3 catalog evidence.

`STAGE_ENTRY_COVENANT: PASS`

The stage may now enter implementation. This line does not claim the Stage 2
binary exit, current runtime wiring, external broker truth, or completion.

## Stage Close Report

### 1. Verdict

Stage 2 satisfies its binary exit at the **local offline test rung**. The
existing StateStore, ReservationLifecycleCoordinator, ExposureManager,
OrderRouter/OMS, baseline, MainLoop, supervisor, and root runtime now form one
broker-inventory authority chain. The chain requires a complete, pinned,
GET-only PAPER account/positions/open-orders snapshot before external PAPER
admission; persists exact Decimal event and projection lineage; reconstructs
adopted, bot-acquired, pending, sold, and unknown quantities; and refuses any
missing, stale, conflicting, corrupt, or unattributed truth.

This verdict does not say the bot traded, reached an external broker, obtained
current account truth, ran as a process, rendered in a browser, submitted an
order, received a fill, proved SELL, or is armed. No PAPER run was authorized or
performed. The external Alpaca PAPER adapter remains BUY-only until Stage 8.

The final configured offline suite result on the source/test/fixture-frozen
tree is `1936 passed, 14 skipped, 0 failed` with 420 warnings. The final cached
diff contains exactly the 16 declared paths, passes `git diff --cached --check`,
and records 8,064 insertions and 134 deletions. No intended file has an
unstaged delta; the five protected runtime-state modifications remain unstaged.

### 2. Files changed

Production owners:

- `app/state/state_store.py` - adds immutable inventory event, snapshot,
  per-symbol projection, and lot-projection persistence; strict readback hashes;
  read-only consumer mode; exact TEXT Decimal contracts.
- `app/risk/reservation_lifecycle_coordinator.py` - projects complete broker
  inventory from the accepted opening baseline, immutable events, active
  mappings/reservations, and current broker book without taking Risk or broker
  authority.
- `app/risk/exposure_manager.py` - ingests the complete durable book atomically,
  keeps existing per-sleeve Risk ownership, exposes immutable broker inventory
  evidence, enforces cash/owned-quantity reservation parity, and normalizes
  correlation pair identities without changing correlation math.
- `app/execution/order_router.py` - uses the existing broker adapter GET boundary
  for startup/post-ack reconciliation, hydrates exact fill facts, processes all
  returned partial-fill activities, and revokes stale inventory authority on
  every incomplete refresh.
- `app/operator_activation/paper_baseline.py` - retains the immutable opening
  snapshot while accepting only integrity-verified managed reconciliation
  lineage as current-position explanation.
- `app/main_loop.py` - strips candidate-supplied inventory authority, consumes
  ExposureManager evidence, derives sell-to-close backing from the current
  reconciled book, and makes external inventory requirement override a disabled
  legacy risk flag.
- `main.py` - hydrates reservations, wires the existing owners, requires
  external PAPER inventory reconciliation, and invokes startup reconciliation
  before candidate admission.
- `app/api/operator_paper_supervisor.py` - reads managed lineage from the
  canonical runtime data path in strict read-only mode so baseline drift can be
  explained without rewriting the opening acceptance or mutating runtime state.

Tests and frozen evidence:

- `tests/test_paper_true_capability_stage2.py` - 77 positive, negative,
  adversarial, permutation, concurrency, restart, corruption, mutation-audit,
  baseline, runtime, and supervisor tests after parametrization.
- `tests/test_runtime_reservation_bootstrap.py` - proves root startup wiring and
  the external PAPER reconciliation requirement.
- `tests/test_operator_paper_baseline.py` - raises fixtures to include exact
  accepted cost basis and verifies it survives runtime-context loading.
- `tests/fixtures/paper_true_capability_stage0.json` - appends an explicit Stage
  2 approved source-delta ledger; original Stage 0 evidence remains unchanged.
- `tests/test_paper_true_capability_stage0.py` - validates the Stage 0 -> Stage 1
  -> Stage 2 hash chain and current Stage 2 production hashes.

Governance/continuity:

- `reports/completion/PAPER_TRUE_CAPABILITY_STAGE_2_REPORT.md` - entry manifest,
  implementation truth, review findings, exact proof, limitations, and staging.
- `CHECKPOINT_TRACKER.md` - Stage 2 result and next unopened boundary.
- `reports/codex_handoff_latest.md` - exact continuation state for the next
  session.

No UI, launcher, icon, strategy, catalog, threshold, live, credential, runtime
state, log, screenshot, audit-script, or unrelated report file is in scope.

### 3. Root cause

The prior runtime had the right sophisticated components but incomplete
portfolio truth wiring:

1. StateStore carried order mappings, reservations, fills, and legacy positions
   but did not persist a complete immutable broker book plus lot projection.
2. ExposureManager hydrated reservations but did not atomically ingest the
   complete broker account inventory before candidate Risk evaluation.
3. The accepted opening baseline was correctly immutable but was also treated
   as if it must equal current quantity forever, so a lawful fill would look
   like unexplained drift.
4. Candidate metadata could carry quantities and lot-tracking booleans into
   Risk/baseline decisions, creating a bypassable second source of inventory
   claims.
5. OrderRouter reconciled individual lifecycle state but did not join all
   broker positions, open orders, durable mappings, reservations, fills,
   corrections, and busts into one startup admission snapshot.
6. External PAPER selection required broker inventory in ExposureManager, but a
   legacy MainLoop flag could label the same Risk gate not configured and let
   downstream code trust that false authorization.

The remedy consolidates rather than replaces: StateStore owns durable facts,
the broker owns acknowledged external truth, the coordinator owns deterministic
projection, ExposureManager owns portfolio Risk, OrderRouter/OMS owns order
lifecycle, MainLoop consumes evidence, and the UI/supervisor remains display and
process authority only.

### 4. Fixes implemented

#### Durable fact and projection contract

- Added `broker_inventory_events`, `broker_inventory_snapshots`,
  `broker_inventory_snapshot_positions`, and
  `broker_inventory_lot_projections` inside StateStore's existing SQLite
  authority. Legacy float tables remain preserved and are not promoted to
  executable inventory truth.
- Quantities, prices, fees, and derived inventory values are validated as
  finite Decimal and persisted as exact text. A supplied broker quantity step
  is enforced exactly; missing Stage 3 instrument increment truth is not
  invented.
- Stable payload/book hashes, position counts, immutable IDs, and strict reads
  make altered events or projections refuse admission. Schema creation/reopen
  remains idempotent.
- StateStore read-only mode opens the existing database with SQLite `mode=ro`
  and `query_only=ON`; supervisor reads run no schema creation or recovery.

#### Causal inventory and lot mathematics

- The coordinator validates paper endpoint/environment, freshness, nonfuture
  observation, GET-only methods, response shape, account status/block flags,
  pinned suffix, baseline suffix, complete positions/open orders, cash truth,
  and observation ordering.
- It explicitly projects `ADOPTED_BASELINE`, `BOT_ACQUIRED`, `PENDING_BUY`,
  `PENDING_SELL`, `SOLD`, and `UNKNOWN_ATTRIBUTION` lineage.
- The known identity is `baseline remaining + bot-owned = broker quantity`;
  `bot acquired - sold = bot-owned`; pending reservations remain separate from
  filled quantity; available sell quantity is broker quantity less pending
  sells. Any nonzero unknown delta blocks.
- Fill deltas and cumulative order observations converge through a causal high
  water mark. Duplicate facts are idempotent; same-ID different payload,
  cumulative regression, equal cumulative quantity with different price,
  inconsistent delta/cumulative evidence, correction conflict, and bust
  conflict refuse.
- Corrections and busts must target an existing event and cannot change order,
  client, fill, symbol, or side identity. Future inventory facts cannot be
  projected into an older broker snapshot.
- Realized PnL follows the acquired lot's sleeve and is explicitly
  `GROSS_EX_FEES`; Stage 2 does not claim fee-complete or net realized PnL.

#### Risk and reservation authority

- ExposureManager atomically builds a candidate per-sleeve inventory from the
  strict durable readback, checks total lot quantity against each broker
  position, verifies pending reservation parity, validates invariants, then
  swaps the in-memory book. A failed ingest restores prior state and revokes
  admission.
- External PAPER BUY needs reconciled broker cash and outstanding BUY
  reservations plus the candidate cannot exceed it. SELL reservation checks use
  owned quantity and pending SELL only; an unfilled BUY cannot back a sell.
- Candidate metadata fields for positions, orders, reservations, run-acquired
  quantity, lot-tracking permission, and broker-position backing are removed
  whenever broker inventory is required. Only the ExposureManager snapshot ID
  may travel as evidence.
- Same-symbol BUY is no longer blocked merely because a symbol was in the
  opening baseline. Existing Risk, concentration, utilization, correlation,
  sizing, stale-data, economics, NetEdge, and strategy gates still decide it.
- External broker inventory requirement forces the existing portfolio Risk
  gate on even if the legacy PAPER flag is false. This closes a configuration
  bypass without changing a threshold.
- Broker-style no-separator symbols and slash/hyphen correlation keys resolve
  to the same identity. Conflicting aliases fail with
  `CORRELATION_TRUTH_CONFLICT`; the existing 0.80 threshold and 0.50 slash proof
  remain unchanged.

#### OMS, fill hydration, and recovery

- Startup resolves active durable mappings against GET-only broker order truth,
  hydrates complete fill evidence, then reconciles account, positions, and open
  orders before external inventory authorization.
- An open broker order must match durable reservation and mapping identity,
  original/filled/remaining quantities, symbol, side, broker order ID, and
  limit price. Missing broker quantity or price stays missing truth.
- Activity-level FILL is a delta fact and cannot borrow cumulative quantity,
  average price, timestamp, or fee from an order-status row. Incomplete
  activity persists no false fill or event.
- All matching partial-fill activities in the returned page are processed;
  each stable broker activity ID is applied once. Cumulative status remains a
  fail-closed fallback when activity reads are unavailable.
- Any invalid GET contract, adapter exception, mapping recovery failure,
  coordinator exception, or post-ack reconciliation gap calls the existing
  ExposureManager revocation path. A previous good snapshot remains diagnostic
  history but cannot keep authorizing new entries after a failed refresh.
- Startup and reconciliation never call submit, cancel, close-all,
  liquidation, flatten, or manual trade surfaces.

#### Opening baseline and operator preflight

- The opening acceptance retains symbol, quantity, side, asset class, and exact
  average entry price. It is never rewritten after a fill.
- Current drift may be explained only by a matching pinned-account,
  baseline-linked, integrity-verified reconciliation with known attribution and
  exact current broker quantity plus cost basis. The next child must re-ingest
  fresh broker truth before candidate admission.
- OperatorPaperSupervisor uses the existing canonical runtime `data_dir/state.db`
  path and strict read-only StateStore. Missing/corrupt/mismatched managed state
  blocks rather than editing the runtime database or faking readiness.

### 5. 360-degree adjacent improvements

- The review added exact cost-basis lineage; quantity-only equality could have
  hidden a broker cost-basis conflict and false PnL attribution.
- Fee truth is now carried in Risk snapshots as gross-ex-fees and incomplete,
  preventing a commercial UI or AI layer from calling Stage 2 realized PnL net.
- Corrupted event and projection hashes are exercised as admission failures,
  not treated as empty books.
- Broker adapter exceptions are converted to named fail-closed evidence without
  leaking exception text into authority or crashing startup recovery.
- Multiple activities for one order are processed in deterministic order; the
  earlier single-activity assumption would have missed valid partial fills.
- A failed post-ack refresh now revokes prior inventory authority. This removes
  stale-green admission after a later broker contract failure.
- The surviving G4 correlation-slash positive test prevented a broker symbol
  normalization change from silently disabling sophisticated correlation Risk.

No Stage 3 catalog, Stage 8 SELL, Stage 9 managed-sell policy, UI, cloud,
multi-tenant, campaign, live, or threshold work was absorbed into this seam.

### 6. Tests and checks

Final exact-tree commands and results:

| Gate | Exact result | Proof rung |
|---|---:|---|
| `python -m py_compile` on 8 production owners and 5 affected test modules | PASS, exit 0 | syntax |
| Stage 2 + bootstrap + baseline + supervisor affected set | `134 passed, 0 failed` | local logic/wiring tests |
| Existing broker/OMS/reservation/baseline compatibility set | `212 passed, 0 failed` | local compatibility tests |
| Seven named decision/e2e/readiness/Risk/replay/dispatch run-path files | `119 passed, 0 failed` | local run-path tests |
| Stage 0 + Stage 1 + Stage 2 covenant/fingerprint set | `115 passed, 0 failed` | local covenant tests |
| Final configured offline suite | `1936 passed, 14 skipped, 0 failed`, 420 warnings, 181.22 s | local full-suite tests |
| Exact 14 conditional external/access node IDs with `-rs` | `14 skipped`, 0 pass/fail | skip-mechanism audit |
| Restart/correction/schema-reopen idempotency node under `Measure-Command` | exit 0, 4.4788556 s process wall time | local timing observation |
| `git diff --check` before report close | PASS | working-diff hygiene |

The 14 skips are not passes:

- Seven functions first require
  `PK_BOARD_AUTHORIZED_PAPER_BROKER_READ=YES_D4_BOARD_AUTHORIZED`; 26G also
  retains a separate mutation approval.
- 26B, 25Z, and Seam 6 stop on their exact missing mutation approvals before
  POST.
- Four preserved optional read-only tests reached their legacy network helper,
  received `URLError`, and skipped. No broker response or broker truth was
  obtained. Their missing Board-env gate is recorded in limitations and is not
  silently called fixed in Stage 2.

Warnings are existing Pydantic v2 migration and timezone-naive datetime
deprecations plus test-specific repeats. They are not hidden, but none was a
failure or used to grant readiness.

### 7. Browser, runtime, and broker proof

- Browser proof: **NOT RUN**. Stage 2 changed no UI and claims no browser truth.
- Runtime-process proof: **NOT RUN**. No child process, launcher, supervisor
  session, heartbeat, or autonomous run was started.
- Broker-read proof: **NOT OBTAINED**. Mock adapters proved GET-only wiring.
  Four legacy optional tests attempted a read and skipped on `URLError`; no
  broker response or current external truth was received.
- PAPER mutation proof: **NOT RUN / NOT AUTHORIZED**. No external POST, DELETE,
  cancel, SELL, close, liquidation, flatten, or fill occurred.
- Live and real-money proof: **NOT RUN / FORBIDDEN**.

The highest rung claimed is local offline tests. Historical broker/PAPER facts
in the Stage 0 fixture remain historical and grant no current authority.

### 8. Self-red-team and mandatory pre-close review

#### Implementation-review findings before formal freeze

Every finding below was fixed before the first candidate-close freeze; all
earlier targeted results were invalidated after each source/test change.

| Severity | Finding and root cause | Impact if retained | Disposition |
|---|---|---|---|
| High | Accepted/managed positions lacked exact average entry price parity. | Quantity could reconcile while cost basis and PnL lineage were false. | Opening and current cost basis are exact Decimal and mismatch blocks. |
| High | Nonfinite Decimal, malformed lot identity, future event, and durable hash cases were incomplete. | Corrupt or temporally impossible state could enter a projection. | Finite/identity/time/hash validation and adversarial tests added. |
| High | Correction/bust target identity was not fully pinned. | A correction could rewrite another order/symbol/side. | Replacement identity equality is mandatory and parametrically tested. |
| High | Open orders could reconcile without complete broker original/filled/remaining quantity and price truth. | Pending exposure could be understated. | All identities must exactly match reservation and mapping; missing truth blocks. |
| High | An activity-level delta could borrow cumulative order fields. | One partial activity could be persisted as a false larger fill. | Activity fields must stand alone; incomplete rows persist nothing. |
| High | Only one matching activity was hydrated. | Multiple broker partial fills could be omitted. | Every returned matching activity ID is processed once. |
| High | A later invalid refresh did not always revoke a prior good inventory authorization. | New candidates could route on stale broker truth. | All early/error/post-ack failure paths revoke admission. |
| High | External inventory requirement could be bypassed when the legacy portfolio-risk flag was false. | The child could label a mandatory Risk owner not configured. | ExposureManager's `broker_inventory_required` evidence forces the existing gate on. |
| Medium | Unexpected adapter errors could escape a recovery path. | Startup could crash without stable refusal evidence. | Named fail-closed results, mapping preservation, and no mutation are tested. |
| Medium | Supervisor managed lineage used no strict canonical runtime database read. | Opening drift could remain falsely blocked or corrupt state could be trusted. | Canonical `data_dir/state.db`, read-only mode, strict hashes, and corruption refusal added. |
| Medium | Realized PnL basis/fee completeness was not explicit. | Downstream surfaces could present gross values as net. | `GROSS_EX_FEES`, fee status, and no-net-claim fields are pinned. |

No existing positive test was relabeled into a refusal. One new Stage 2
assertion was raised from a generic remaining-quantity conflict to the stricter
`RESERVATION_BROKER_QUANTITY_TRUTH_MISSING_OR_INVALID` reason after the fixture
omitted broker original/filled truth; its intent remained refusal. Existing
baseline fixtures gained lawful average-entry-price evidence. The G4 positive
test remained positive and was never weakened.

#### Formal review cycle 1

Candidate fingerprint:

- entry HEAD `f462356d140eaf0acccfd5be05faeb01536ae989` plus scoped working diff;
- `ExposureManager` SHA-256
  `a210d43d4c4e9b0ec0d741d3fc0e96e41a70b82f720a0de62f39fd7fbecd0a01`;
- Stage 2 test SHA-256
  `2f3c5ce3cbf024cb02b01f1a0504f1a6c2cb89129d4015561aee3dfa1bbe98d1`;
- covenant fixture SHA-256
  `8ee2aa82fcc8ed903d53c9b886adf6073c70da810b899008d805b22dc01d2b80`.

Reviewer scope: full production diff; StateStore schema and strict reads;
coordinator causal projection; ExposureManager ingestion/Risk/correlation;
OrderRouter startup/post-ack/fill paths; root/supervisor wiring; existing and new
tests; defaults, mutations, skips, protected files, and named run paths.

Finding: the first exact run-path attempt produced `118 passed, 1 failed`.
`test_g4_live_runtime_correlation_slash_runs_before_netedge` was a surviving
positive twin and failed because Stage 2 canonicalized broker symbols without
separators while `_lookup_correlation_pair` still compared raw slash-form keys.
The verdict became `CORRELATION_TRUTH_MISSING` instead of applying the existing
correlation slash before NetEdge.

Fix: correlation lookup now normalizes tuple and `|`/`:` pair identities and
fails closed when aliases disagree. The positive G4 node passed; a new negative
test proves conflicting aliases return `CORRELATION_TRUTH_CONFLICT`. No
threshold, slash factor, quantity step, or economic control changed.

Disposition: Cycle 1 failed and is not completion evidence. The parallel
orchestrator did not return sibling command outputs after the run-path failure;
they are not inferred or reused. Every behavioral gate was rerun after the fix.

#### Formal review cycle 2

Final candidate fingerprint:

```text
app/api/operator_paper_supervisor.py          90be76db49dd8145634eec6d499167c628ef1133ea15a9bf3f0311a1f0832b43
app/execution/order_router.py                 405d19603e0ffbff9bfb7f7d2c818b8950baaa28e910dbbe4565fd272939ab98
app/main_loop.py                              f82f59d019e337a7840e94e0c1ebd9d4bbc3ed0b9b3a65d2910ee0d8f875070d
app/operator_activation/paper_baseline.py     a96e6d529c7d986dc61644059f8bcfcbfd3edf190c6eb9c6b3bec10b24e43af6
app/risk/exposure_manager.py                  0cc7efaef0989fdaf21adabc2e5cac72509dfa8eb9e16494f3deaf8f8d9534d4
app/risk/reservation_lifecycle_coordinator.py 1ebdf87c2ca98daa7ad463697894ccda00f3f0f61deab6e0b9c6af9dc4e4d018
app/state/state_store.py                      dae3ff16f2f8151af0db63e9c424995e6e45d77ffc7af214787e390523800c28
main.py                                       e089772d5142df5105ed3b837d259c5c16ac9bf7547e37eea49d7b10930644e5
tests/test_paper_true_capability_stage2.py    743fabdc18da3d2ba099c82dfb572e73e2c9faad9816c69e4749e5cf45826304
tests/fixtures/paper_true_capability_stage0.json
                                              b803c0db0bffe7ff0d0290d6913afbdb5e4b474b2bbcaf16d92860526773047a
```

Reviewer scope repeated the full authority, schema, failure, restart,
concurrency, activity, correction, baseline, configuration, test-integrity,
skip, mutation, secret, scope, and staging review. Final result after staging:
zero unresolved in-scope safety, correctness, authority, data-truth,
test-integrity, or operator-truth findings. Exact final commands and counts are
in Section 6. The cache contains exactly the declared 16-file candidate;
`git diff --cached --check` exits 0; the summary creates only this report and
the Stage 2 test module; a staged added-line scan found no forbidden manual
trade/flatten/cancel/liquidation control; and a credential-like assigned-value
scan returned zero matches. Git could not read the sandboxed user-level global
ignore file, but no implicit ignore behavior was relied upon: staged membership
was enumerated directly and every path was added individually.

#### Requirement to code to proof matrix

| Requirement | Production path | Final proof |
|---|---|---|
| Four holdings cold-start exactly and without mutation | `main.py` bootstrap -> `OrderRouter.reconcile_startup_broker_inventory` -> coordinator -> StateStore -> ExposureManager | `test_cold_start_reconciles_all_four_baseline_positions_without_mutation` |
| Complete provenance and exact quantity identities | coordinator projection + ExposureManager ingest | generated Decimal, fill lineage, sold-sleeve, pending reservation, and total mismatch tests |
| Opening baseline remains immutable while managed current truth advances | baseline managed reconciliation + supervisor read-only strict read | managed reconciliation, cost-basis immutability, and supervisor cold-boot tests |
| Same-symbol BUY is not blocked only because it existed at startup | MainLoop canonical inventory evidence + existing Risk gate | `test_same_symbol_buy_is_not_blocked_by_opening_baseline_after_complete_reconciliation` |
| Missing/stale/mismatched/unattributed/corrupt truth refuses | coordinator validators, strict StateStore reads, ExposureManager revocation | account/stale/future/short/hash/mapping/adapter/post-ack negative tests |
| Candidate cannot inject inventory authority | `_strip_candidate_inventory_authority` + ExposureManager evidence | `test_candidate_metadata_cannot_supply_inventory_authority` |
| Lifecycle facts are causal, exact, idempotent, and restart-safe | StateStore event hashes + coordinator causal reprojection + OrderRouter hydration | correction/bust/permutation/cumulative/activity/restart tests |
| Reservations cannot overspend or oversell | ExposureManager serialized reservations + broker/open-order parity | concurrent cash/owned tests and complete open-order identity tests |
| External inventory requirement cannot be configured away | `_portfolio_risk_gate_enabled` consumes ExposureManager requirement | legacy false-flag refusal plus post-reconciliation positive test |
| Existing correlation Risk survives symbol canonicalization | normalized correlation lookup | G4 positive run-path and alias-conflict refusal test |
| No broker mutation or SELL activation | GET contract validators; existing BUY-only adapter unchanged | startup mutation-surface test, adapter compatibility, full suite |
| Source and default drift is frozen | Stage 0 approved source-delta chain | 115 covenant/fingerprint tests |

#### Anti-hallucination self-check

- Actually inspected: all scoped diffs, active callers/callees, schema/readback,
  runtime construction, broker GET response contracts, reservation and fill
  identities, baseline/supervisor state path, test assertions, skips, source
  hashes, dirty tree, and intended staging list.
- Tests prove: deterministic offline logic and mocked wiring only.
- Runtime proves: nothing in this stage; no process was run.
- Browser proves: nothing in this stage.
- Broker proves: nothing current; no response was obtained.
- Inference: external Alpaca behavior should follow the adapter contracts, but
  this is unproven until separately authorized broker/PAPER stages.
- Unknown: current account/positions/orders, real activity pagination behavior,
  external fill details/fees, runtime throughput, multi-day recovery, and
  profitability.
- No failure was summarized away: the G4 failure and all invalidated results are
  recorded above; 14 skips remain skips.
- No module was omitted, deleted, flattened, activated beyond its stage, or
  given duplicate authority.

### 9. Safety confirmation

- PAPER endpoint and pinned suffix checks remain hard; live and real money stay
  blocked.
- No Risk, utilization, concentration, cash reserve, correlation, NetEdge,
  strategy, sizing, stale/TTL, masking, OMS, account, or baseline threshold was
  reduced or bypassed.
- No manual buy/sell/cancel/flatten/close/liquidate control was added.
- No naked SELL or short authority was added. Stage 2 reconciles sell facts but
  the external adapter still refuses SELL.
- No test issued a successful broker call. Mocked adapter GETs were read-only;
  mutation surface assertions remained zero. Four optional network attempts
  ended in `URLError` and produced no broker truth.
- No fake order, fill, fee, TCA, PnL, broker position, readiness, or liveness was
  created. A fill requires stable broker activity/order identity and durable
  reconciliation.
- Realized PnL is labeled gross ex fees and fee-incomplete; no net or
  profitability claim exists.
- SovereignExecutionGuard remains dormant. Existing force-sync remains
  preserved but is not used as the external startup authority.
- No module/dependency/subsystem was added outside existing owners. The new
  SQLite tables live within StateStore, the existing durable owner.
- Protected `state/**`, `.pytest_tmp/**`, logs, databases, secrets, screenshots,
  old handoffs, proposal packets, operator-performance reports, and audit
  scripts remain unstaged.

### 10. Module status

| Module | Stage 2 status and lawful role |
|---|---|
| StateStore | WIRED - durable event/snapshot/lot fact owner with strict integrity reads; not broker or Risk authority. |
| ReservationLifecycleCoordinator | WIRED - deterministic projection transaction coordinator; no broker command or Risk ownership. |
| ExposureManager | WIRED - complete portfolio/Risk and reservation authority after reconciliation. |
| OrderRouter/OMS | WIRED - broker order/fill/mapping lifecycle and reconciliation caller; sole broker mutation owner remains unchanged. |
| PaperBaselineStore/baseline logic | WIRED - immutable opening acceptance plus managed lineage verification; not current broker owner. |
| MainLoop | WIRED - evidence consumer; candidate metadata cannot own inventory. |
| SovereignHeartbeat root | WIRED - constructs/hydrates owners and invokes startup reconciliation before external admission. |
| OperatorPaperSupervisor | WIRED - process/preflight display owner using strict read-only lineage; no trade authority. |
| AlpacaPaperBrokerAdapter | PRESERVED/WIRED BUY-only - GET contracts used; SELL remains blocked until Stage 8. |
| SovereignExecutionGuard | PRESERVED-DORMANT - untouched and unactivated. |
| Legacy StateStore position/fill tables | PRESERVED non-authoritative compatibility data; not deleted or promoted. |

### 11. Disagreements and what I would do differently

- The master plan says to use broker minimum trade increment in Stage 2, but
  current broker-canonical per-symbol increments do not exist until Stage 3's
  asset catalog. Hardcoding one now would fake truth. Stage 2 validates an
  increment when supplied and otherwise preserves exact Decimal; Stage 3 must
  supply the canonical capability.
- The four legacy optional read-only tests should eventually use the same Board
  authorization gate as the seven governed deferrals. Altering those unrelated
  historical test modules after the final Stage 2 scope freeze would violate
  the scope tripwire. Their network-unavailable skips are reported, not hidden.
- The timing observation is a local process-wall measurement, not a production
  latency SLO. A future campaign should measure reconciliation latency and
  database growth under realistic long-run event volume.

No safety or go-live disagreement was resolved silently. Stage 2 does not
authorize Stage 3, broker reads, PAPER, SELL, or a campaign.

### 12. Limitations and unknowns

- No real broker snapshot, broker activity, order, fill, fee, or account truth
  was obtained. Mock adapter fidelity cannot prove Alpaca behavior.
- Broker fill activities are currently read as one page of at most 100. Missing
  activity cannot create false inventory because cumulative/order/position
  mismatches block, but complete pagination belongs with the Stage 8 stream and
  lifecycle work.
- External adapter SELL remains disabled until Stage 8, so Stage 2 does not
  prove sell-to-close submit or managed exits.
- Stage 9 managed-existing baseline sell policy is not activated.
- Instrument catalog, tradability, fractionability, status, increments, and
  dynamic universe remain Stage 3.
- Fee attribution remains incomplete; realized PnL is gross ex fees. TCA,
  slippage, profitability, benchmark, drawdown, and paper-vs-backtest claims are
  not established.
- Startup wiring is tested but not proven in a live process. Broker rate limits,
  pagination, clock quality, latency, disconnection, process crash, disk-full,
  and multi-day recovery remain unproven.
- Runtime mutation remains single-process and single-tenant. Multi-process
  submit serialization, tenant/account isolation, custom deployment paths,
  noisy-neighbor limits, and cloud durability are later campaign/deployment
  concerns.
- Fourteen external/access tests remain skipped. Four legacy optional reads use
  network availability instead of the common Board env gate.
- Existing Pydantic and datetime deprecation warnings remain.
- The worktree remains dirty with protected runtime state and pre-existing
  untracked evidence. No baseline tag/branch is forced.

### 13. Exact staging recommendation

Stage exactly these 16 files, individually:

```text
app/api/operator_paper_supervisor.py
app/execution/order_router.py
app/main_loop.py
app/operator_activation/paper_baseline.py
app/risk/exposure_manager.py
app/risk/reservation_lifecycle_coordinator.py
app/state/state_store.py
main.py
tests/fixtures/paper_true_capability_stage0.json
tests/test_operator_paper_baseline.py
tests/test_paper_true_capability_stage0.py
tests/test_paper_true_capability_stage2.py
tests/test_runtime_reservation_bootstrap.py
reports/completion/PAPER_TRUE_CAPABILITY_STAGE_2_REPORT.md
CHECKPOINT_TRACKER.md
reports/codex_handoff_latest.md
```

Never stage the protected `state/**` files, `.pytest_tmp/**`, old handoffs,
proposal/restriction-review packets, `reports/operator_perf/**`, logs,
screenshots, secrets, databases, or untracked audit scripts. No broad `git add`
is permitted.

Actual cached result: exactly the 16 paths above; `git diff --cached --check`
PASS; 16 files changed, 8,064 insertions, 134 deletions; two expected new files;
no intended unstaged delta; protected runtime/evidence files remain outside the
cache.

PRE_CLOSE_REVIEW: PASS
