# Codex Session Handoff - PAPER True Capability Stage 4 Close

Date: 2026-07-19 America/Chicago
Repo: `C:\Users\shahn\OneDrive\Desktop\poverty_killer`
Branch: `master`
Stage-entry HEAD: `6340bae4aff24d272f3ba4270c641d896de10278`
Stage report: `reports/completion/PAPER_TRUE_CAPABILITY_STAGE_4_REPORT.md`

## Current Stage 4 Verdict

Shan directed `ok. Proceed with stage 4`, opening Stage 4 only. Stage 4 is
**PASS at the deterministic offline test rung only**. Alpaca stream/REST are the
only providers allowed to satisfy Alpaca executable market-data truth; bounded
breadth and protected/ranked deep transport are wired; every dynamically ranked
symbol remains observe-only with zero execution authority.

The highest proof rung is local tests plus mocked runtime wiring. No browser,
launched runtime, real provider request, broker read, PAPER run, broker mutation,
external order/fill/SELL, PnL/profitability, live action, real money, latency, or
multi-day endurance result is claimed.

## Stage 4 Implementation Truth

- `FeedProviderRouter` owns selection/failover. `alpaca_crypto_stream` and
  `alpaca_crypto_rest` are executable only at the Alpaca execution location;
  Kraken/Coinbase are advisory/reference and refuse execution-required use.
- `BatchedAlpacaPollingClient` uses multi-symbol snapshots/books, one shared
  request budget, bounded concurrency/queue/history, Retry-After circuit,
  cancellation, and secret-safe reason-coded failure.
- `AlpacaCryptoWebSocketClient` requires greeting, auth, and complete
  subscription acknowledgement; channels are ordered independently; reset/
  incremental/size-zero book semantics and bounded backpressure are enforced.
- `MarketFeeds` owns actual activation, protected-truth probes, stop-before-
  fallback, stale-generation purge, breadth/deep separation, callbacks, and
  terminal failure truth.
- Held/open-order/lifecycle symbols are non-evictable. Dynamic candidates may
  contribute observations but cannot reach execution callbacks.
- `build_market_data_universe_snapshot` uses causal robust quantiles,
  winsorization, median/MAD, exact Decimal broker increments, empirical
  percentiles, Pareto fronts, uncertainty, and residence hysteresis. No fixed
  weighted score or profitability claim was introduced.
- `StateStore` persists immutable rank snapshots with strict catalog, universe,
  role, clock, and hash lineage and rejects tampering/future/cross-role state.
- `SovereignHeartbeat` starts the centralized Alpaca owner, retains the legacy
  internal-harness path, exports transport truth, and cancels/joins feeds before
  durable state closes. Terminal market-data loss stops without flattening.
- `DataValidator` evaluates verified bar close time under the existing stale
  threshold and rejects future/in-progress/inconsistent metadata.

## Mandatory Review Loop

Fresh self-review produced nineteen recorded findings. Eighteen in-scope
transport, causal-ranking, lifecycle, schema, exact-math, and test-fixture
defects were fixed and rerun. The full finding table with file/function, root
cause, impact, and disposition is in the Stage 4 report. No independent reviewer
is claimed.

Finding 19 is out of Stage 4 scope and remains open: the existing
`tests/test_g0_hook_verification.py` invokes
`.claude/hooks/pre_tool_use.py::log_override_attempt`, which hardcodes
`state/override_log.jsonl`. The full suite appended exactly eight audit records.
Do not revert or stage that protected file. A later governance-test seam must
route the hook audit log to an isolated temp path without weakening hook law.

## Final Validation

- Scoped `py_compile`: PASS, zero errors.
- Focused Stage 4/provider/runtime lifecycle: `135 passed`, `0 failed`.
- Compatibility set: `26 passed`, `0 failed`.
- Stage 0-4 covenant set: `251 passed`, `0 failed`.
- Seven named run-path files: `119 passed`, `0 failed`.
- Exact 600-symbol binary soak: `1 passed`; 260 batched jobs over 20 cycles,
  max in-flight <=4, queue high-water <=8, histories <=7, all dynamic
  memberships observe-only.
- Full configured offline suite: `2084 passed, 14 skipped, 420 warnings, 0
  failed` in 205.61 seconds.
- Exact skip audit: `54 passed, 14 skipped`. Seven require Board broker-read
  authorization, three lack mutation approval, four legacy optional probes end
  in `URLError`; no skip is a pass.
- No deleted file, added skip/xfail, external dependency, changed Risk/OMS/
  execution owner, obvious secret, or added broker mutation surface.

## Safety and Proof Boundary

No Risk, NetEdge, economics, sizing, stale/TTL value, masking, strategy, OMS,
reconciliation, account-pin, PAPER/live, no-short, or no-naked-SELL control
weakened. Dynamic data remains observe-only; cross-venue data remains advisory.
No manual trade control, new mutation owner, fake broker truth/order/fill/PnL,
module deletion, dependency, or subsystem was added. SovereignExecutionGuard
remains dormant.

No real request, POST, cancel, close, liquidation, position mutation, PAPER
start, live action, or state authority change was authorized. The full-suite
governance audit records are protected dirty evidence, not bot state authority.

## Known Limitations

- Real Alpaca payloads, entitlements, catalog throughput, clocks, latency,
  disconnect/reconnect behavior, and current market truth remain unknown.
- Pareto sorting is quadratic and runs on the feed loop; the 600-symbol offline
  case passed, but sustained real CPU behavior is unmeasured.
- Sync callback timeout detects only after return and cannot preempt a hung sync
  callback.
- Minute bars may repeat across 15-second breadth observations.
- Rank-snapshot DB retention/compaction and multi-day growth are not yet proven.
- No production caller currently feeds cross-venue advisory observations;
  missing basis remains explicit uncertainty.
- Fourteen conditional integration skips and 420 existing warnings remain.
- Browser/runtime, external, long-duration, profitability, cloud, and
  multi-tenant proof remain unperformed.

## Protected Worktree

Never clean, reset, stash, prune, edit, or stage:

```text
state/override_log.jsonl
state/risk_state.backup
state/risk_state.json
state/risk_state.tmp
state/session_journal.jsonl
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

## Exact Stage 4 Staging

Stage these 18 paths individually:

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

## Next Boundary

Stop after the Stage 4 commit/push. Stage 5 is **NOT OPEN**. It requires a new
governance re-read, entry manifest, truth map, red team, binary exit, and Board
direction. Stage 12 broker reads and every Stage 13 PAPER campaign retain their
separate approval gates.

---

# Historical Continuity - PAPER True Capability Stage 3 Close

Date: 2026-07-19 America/Chicago
Repo: `C:\Users\shahn\OneDrive\Desktop\poverty_killer`
Branch: `master`
Stage-entry HEAD: `4b9b8ed13583d56bfc2120fbee291e3695b1a288`
Stage report: `reports/completion/PAPER_TRUE_CAPABILITY_STAGE_3_REPORT.md`

## Current Stage 3 Verdict

Shan directed `proceed stage 3`, opening Stage 3 only. Stage 3 is **PASS at the
local offline test rung only**. A mocked complete Alpaca PAPER crypto catalog
now produces a deterministic, reason-coded eligible universe with exact Decimal
constraints, while static instrument rows and the operator priority list have
zero execution authority.

The highest proof rung is local offline tests. No browser, launched runtime,
real broker catalog read, PAPER run, broker mutation, external order/fill/SELL,
PnL/profitability, live action, real money, or arming result is claimed.

## Stage 3 Implementation Truth

- `broker_read_policy` owns a catalog-only GET profile. It accepts only
  `/v2/assets?status=active&asset_class=crypto` and denies mutation methods
  before transport.
- Alpaca owns raw asset facts. `capability_registry` is the sole deterministic
  normalization/derivation owner. `StateStore` persists immutable evidence but
  does not decide eligibility or broker truth.
- Size and price constraints remain exact Decimal text. Missing, float,
  nonfinite, nonpositive, malformed, conflicting-alias, and duplicate-conflict
  inputs fail closed.
- Entry eligibility intersects broker asset facts, pinned account permission,
  quote funding, adapter support, and market-data coverage. Every included or
  excluded symbol carries explicit reasons.
- Monitor-required membership remains independent. Reconciled held/open-order
  symbols stay governed even when new entry is denied.
- Snapshot evidence is endpoint/account/time/hash/count bound and atomically
  restart-readable. Missing, future, stale, malformed, corrupt, or cross-account
  evidence cannot fall back to static metadata.
- Static Alpaca crypto rows remain preserved as reference/display fixtures, but
  static validation refuses execution. The operator symbol list is ordering
  priority only and cannot nominate an ineligible asset.
- Supervisor start, the immediate pre-spawn check, child boot, MainLoop, and the
  intelligence spine all consume the full pinned dynamic universe. Risk,
  NetEdge, sizing, MarketTruthSnapshot, OMS, reconciliation, account pin,
  no-short, and no-naked-SELL owners remain unchanged.
- The adapter catalog operation is declared but has no production caller in
  Stage 3. Real operator start therefore remains fail-closed until a later stage
  installs the governed producer/acceptance path.

## Mandatory Review Loop

Review cycle 1 found and fixed three issues: direct static registry validation
could still approve crypto; the child discarded priority ordering; and direct
monitor-only/future-evidence refusal needed stronger tests. Every earlier result
was invalidated.

Review cycle 2 found and fixed four issue clusters: permissive string coercion
of broker identity fields; permissive persisted identity/reason coercion;
malformed priorities disappearing; and malformed suffix/held/open-order symbols
disappearing. Every earlier result was invalidated again.

Review cycle 3 re-read the fresh full diff and unhappy paths, checked authority,
fallback, corruption, restart, dependency, deletion, secret, threshold, skip,
and protected-file scope, and found no unresolved in-scope defect. The final
35-file behavior manifest composite is:

```text
ee6a81105af15256fac596b691f87831902a45f14d7c8b96bc815e6071084929
```

Review cycle 4 found that the first cached audit's result was not yet written
into the close report. That documentation-only omission was corrected without
changing the 35 behavior files; governance markers, behavior fingerprint, and
the exact cache were then revalidated.

## Final Validation

- Focused Stage 3/affected suite: `173 passed`, `0 failed`.
- Seven named run-path files: `119 passed`, `0 failed`.
- Stage 0/1/2/3 covenant suite: `150 passed`, `0 failed`.
- Final configured offline suite: `1980 passed, 14 skipped, 420 warnings, 0
  failed` in 216.50 seconds.
- Exact skip audit: `54 passed, 14 skipped`. Seven skips require explicit Board
  broker-read authorization, three lack mutation approval, and four legacy
  optional read probes ended in `URLError`. No Stage 3 test skipped and no skip
  is counted as a pass.
- Relevant AST parse, JSON fixture parse, and import smoke: PASS.
- Deleted files, added skip/xfail, external dependencies, changed risk-threshold
  owners, and obvious secret/private-key markers: zero.
- Final cached audit: 38 expected/staged paths, zero missing/extra, zero intended
  unstaged deltas, whitespace check exit 0, and 5,441 insertions / 109 deletions.
- Four assertion-intent relabels are fully logged in the report. They move stale
  static-fixture expectations to broker-derived authority without weakening a
  refusal or converting a surviving positive run path into refusal.

## Safety and Proof Boundary

No Risk, NetEdge, economics, sizing, stale/TTL, masking, strategy, OMS,
reconciliation, account-pin, PAPER/live, no-short, or no-naked-SELL control
weakened. No manual trade control, new mutation owner, fake broker truth/order/
fill/PnL, module deletion, generic replacement, dependency, or subsystem was
added. Alpaca execution remains BUY-only until Stage 8, and
SovereignExecutionGuard remains dormant.

No real request, POST, cancel, close, liquidation, position mutation, PAPER
start, live action, or state authority change occurred. The result is not an
arming claim.

## Known Limitations

- Actual Alpaca catalog content, pinned-account coverage, current eligible
  count, and external connectivity are unknown because no real GET occurred.
- Production catalog acquisition/acceptance is not wired yet; no silent fallback
  exists.
- Continuous refresh and in-run expiry, scalable feed batching/rate budgets,
  and universe ranking belong to Stage 4.
- Position-backed `sell_to_close` exists in dynamic capability truth, while the
  Alpaca adapter remains BUY-only until Stage 8; no external SELL was proven.
- Snapshot SHA-256 provides deterministic integrity, not signed/authenticated
  provenance.
- Fourteen conditional integration skips and 420 existing warnings remain.
- Browser/runtime, long-duration, fault-recovery, latency, profitability,
  cloud, and multi-tenant proof remain unperformed.

## Protected Worktree

Never clean, reset, stash, prune, edit, or stage:

```text
state/override_log.jsonl
state/risk_state.backup
state/risk_state.json
state/risk_state.tmp
state/session_journal.jsonl
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

## Exact Stage 3 Staging

Stage these 38 paths individually:

```text
app/api/operator_paper_supervisor.py
app/api/operator_runtime_config.py
app/config.py
app/core/intelligence_portfolio_state_truth_spine.py
app/execution/alpaca_paper_adapter.py
app/execution/broker_gateway.py
app/execution/broker_read_policy.py
app/instrument_registry.py
app/main_loop.py
app/market/capability_registry.py
app/market/venue_capabilities.py
app/state/state_store.py
main.py
tests/fixtures/paper_true_capability_stage0.json
tests/paper_capability_test_support.py
tests/test_broker_read_policy.py
tests/test_decision_frame_orchestration_paper_exploration_alpha.py
tests/test_intelligence_portfolio_state_truth_spine.py
tests/test_operator_account_identity_pin.py
tests/test_operator_ai_ask.py
tests/test_operator_broker_preflight.py
tests/test_operator_launch_readiness.py
tests/test_operator_paper_baseline.py
tests/test_operator_paper_supervisor.py
tests/test_operator_readonly_api.py
tests/test_order_id_mapping_authority.py
tests/test_paper_true_capability_stage0.py
tests/test_paper_true_capability_stage2.py
tests/test_paper_true_capability_stage3.py
tests/test_phase3_risk_gate_stress_proof.py
tests/test_pre_trade_guardrail_constraints.py
tests/test_runtime_dispatch_admission_telemetry.py
tests/test_seam6_controlled_alpaca_paper_portfolio_expansion_machine.py
tests/test_seam7g_market_truth_reconciliation_spine.py
tests/test_venue_market_asset_capability_layer.py
reports/completion/PAPER_TRUE_CAPABILITY_STAGE_3_REPORT.md
CHECKPOINT_TRACKER.md
reports/codex_handoff_latest.md
```

## Next Boundary

Stop after the Stage 3 commit/push. Stage 4 is **NOT OPEN**. It requires a new
governance re-read, entry manifest, truth map, red team, binary exit, and Board
direction. Stage 12 broker reads and every Stage 13 PAPER campaign retain their
separate approval gates.

---

The remaining content below is historical continuity. Its Stage 2 boundary was
true when written and is superseded by the current Stage 3 section above.

# Historical Continuity - PAPER True Capability Stage 2 Close

Date: 2026-07-18 America/Chicago
Repo: `C:\Users\shahn\OneDrive\Desktop\poverty_killer`
Branch: `master`
Stage-entry HEAD: `f462356d140eaf0acccfd5be05faeb01536ae989`
Stage report: `reports/completion/PAPER_TRUE_CAPABILITY_STAGE_2_REPORT.md`

## Current Stage 2 Verdict

Shan directed `proceed`, opening Stage 2 only, and required the mandatory
pre-close review loop. Stage 2 is locally green: complete broker inventory,
lots, fills, reservations, managed baseline lineage, Risk consumption, startup
reconciliation, and supervisor read-only state wiring are implemented through
the existing authority owners. The mandatory pre-close review passed on the
exact 16-file cached candidate; Stage 3 is not open.

The highest proof rung is local offline tests. No launcher/browser/runtime
process, current broker truth, PAPER run, successful broker response, external
order/fill, SELL, PnL/profitability, live action, real money, or arming result is
claimed.

## Stage 2 Implementation Truth

- StateStore owns immutable exact-Decimal inventory events, complete broker-book
  snapshots, per-symbol projections, lot projections, strict hashes, and a
  read-only consumer mode. Existing tables are preserved.
- ReservationLifecycleCoordinator remains the projection coordinator. It joins
  pinned account, positions, open orders, accepted opening baseline, mappings,
  reservations, fills, corrections, and busts without broker or Risk authority.
- ExposureManager remains full portfolio/Risk owner. It atomically ingests the
  strict durable book, validates lots and pending reservations, accounts for
  broker cash, and blocks missing/stale/unknown/conflicting truth.
- OrderRouter/OMS remains order-lifecycle and broker-boundary owner. Startup and
  post-ack GET reconciliation hydrate all returned partial-fill activities,
  preserve exact identities, and revoke admission after any incomplete refresh.
- MainLoop strips candidate inventory quantities/permissions. External broker
  inventory requirement forces the existing Risk gate on even if the legacy
  PAPER flag is false.
- Opening baseline remains immutable. Managed current quantity and exact cost
  basis require integrity-verified baseline-linked lineage and fresh re-ingest
  before candidate admission.
- Slash/hyphen/no-separator symbols match across broker inventory and correlation
  evidence. Conflicting correlation aliases fail closed. No correlation math or
  threshold changed.

## Final Validation

- Scoped Python compile: PASS.
- Affected Stage 2/bootstrap/baseline/supervisor set: `134 passed`.
- Existing broker/OMS/reservation compatibility set: `212 passed`.
- Seven named run-path files: `119 passed`.
- Stage 0/1/2 covenant and fingerprint set: `115 passed`.
- Final configured offline suite: `1936 passed, 14 skipped, 420 warnings,
  0 failed` in 181.22 seconds.
- Exact skip audit: 14 named tests skipped. Seven require the Board read env,
  three lack exact mutation approval, and four legacy optional reads ended in
  `URLError`. No broker response or truth was obtained.
- Schema restart/idempotency node: exit 0; 4.4788556 seconds process wall time.
- Final cache review: exact 16 paths; `git diff --cached --check` exit 0; 8,064
  insertions and 134 deletions; no intended unstaged delta; protected runtime
  state remains excluded.

The first formal final run is intentionally preserved as failure history:
`test_g4_live_runtime_correlation_slash_runs_before_netedge` produced one
failure (`118 passed, 1 failed`) because broker symbol normalization hid
slash-form correlation evidence. The positive test was not relabeled or
weakened. Normalized pair lookup fixed the root cause, a contradictory-alias
refusal was added, all earlier results were invalidated, and every final gate
above was rerun on the new fingerprint.

## Safety and Proof Boundary

No Risk, NetEdge, sizing, stale/TTL, masking, strategy, correlation,
utilization, concentration, cash-reserve, OMS, account-pin, endpoint, baseline,
or no-short control weakened. No manual trade control, new mutation owner,
module deletion, generic replacement, or external dependency was added.

Alpaca PAPER remains BUY-only until Stage 8. SovereignExecutionGuard remains
dormant. Realized PnL lineage is labeled `GROSS_EX_FEES`; fee-complete/net PnL
and profitability are unknown. No fake fill, broker truth, readiness, or higher
proof rung is claimed.

## Known Limitations

- No current broker truth or process/browser wiring proof was obtained.
- Broker fill activities use one page of at most 100; missing evidence blocks,
  but complete pagination/stream lifecycle belongs to Stage 8.
- Broker instrument increments/catalog/dynamic universe remain Stage 3.
- External SELL and managed existing-position exits remain Stages 8/9.
- Runtime throughput, long-duration recovery, disk/network faults, cloud, and
  multi-tenant isolation remain unproven.
- Fourteen broker/access skips and existing Pydantic/datetime warnings remain.
- Four legacy optional read tests should adopt the Board env gate in a properly
  scoped future test-governance seam; they are not called fixed here.
- The worktree retains protected runtime state and pre-existing untracked
  evidence. No baseline tag/branch may be forced.

## Protected Worktree

Never clean, reset, stash, prune, edit, or stage:

```text
state/override_log.jsonl
state/risk_state.backup
state/risk_state.json
state/risk_state.tmp
state/session_journal.jsonl
.pytest_tmp/
AGENTS.prev.md
POVERTY_KILLER_AUDIT_REPORT.txt
old reports/codex_handoff_*.md files
reports/completion/PAPER_AUTONOMY_RESTRICTIONS_REVIEW.md
reports/completion/UI_NOVEL_OPERATOR_COCKPIT_BOARD_PACKET.md
reports/completion/UI_WORLD_CLASS_REDESIGN_PACKET.md
reports/operator_perf/
scripts/_paper_audit_common.py
scripts/audit_oms_shutdown.py
scripts/audit_paper_run.py
scripts/audit_safety_markers.py
```

## Exact Stage 2 Staging

These 16 files were staged individually and passed every Section 11 cached
check:

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

## Next Boundary

Stop after the Stage 2 commit/push. Stage 3 needs a fresh governance re-read,
entry manifest, truth map, red team, and Board direction. Broker reads and every
PAPER campaign retain separate approval gates.

---

The remaining content below is historical continuity from earlier stages and
packets. Its statements that Stage 2 was unopened were true when written and
are superseded by the current section above.

# Historical Continuity - PAPER True Capability Stage 1 Complete

Date: 2026-07-18 America/Chicago
Repo: `C:\Users\shahn\OneDrive\Desktop\poverty_killer`
Branch: `master`
Stage-entry HEAD: `e363f4b919d3ae52416278c810a87169ca7f1186`
Close commit: this handoff is carried by the Stage 1 close commit; verify with
`git log -1 --oneline`
Stage report: `reports/completion/PAPER_TRUE_CAPABILITY_STAGE_1_REPORT.md`

## Current Verdict

Shan directed `proceed`, opening Stage 1 only. Stage 1 is complete and **PASS at
the local offline test rung**. Stage 2 has not been opened.

The active decision path now uses per-symbol mutable analytical state and a
deterministic causal contract: a selected observation must belong to the same
symbol and have both event and receipt/availability timestamps no later than
the decision timestamp. Future or regressing clocks fail closed with named
reasons. Existing model math, MarketTruthSnapshot, Risk, NetEdge, sizing, OMS,
reconciliation, account, endpoint, and lifecycle controls remain intact.

## Implementation Truth

- `SignalFusion` remains the sole fusion owner and now indexes histories,
  hysteresis, telemetry, and last decisions by symbol. Histories are bounded to
  512 records per symbol/channel without changing any signal TTL or threshold.
- `SymbolRuntime` owns one existing EntropyDecoder, PhysicalValidator, and
  persistent StaleDataGuard instance per symbol. It stores evidence; it does not
  gain final trade authority.
- The guard assesses receipt minus exchange time, retains per-symbol kinematics,
  and supplies the canonical assessment to the existing pre-trade Risk owner.
  Missing active-path assessment fails closed. MarketTruthSnapshot still owns
  executable candle/book freshness.
- WebSocket and REST paths preserve actual receipt time. Kraken source event
  time comes from its level timestamps; missing source time rejects rather than
  being replaced with local wall time.
- MainLoop uses candidate-symbol candle volume, regime, topology, entropy,
  physical, toxicity, whale, insider, and fusion state. The primary symbol is no
  longer borrowed for another candidate. A close-audit branch that could use the
  process-global regime detector when a runtime detector was missing was also
  removed; missing same-symbol regime evidence now emits `UNKNOWN`.
- The trade callback routes once through the full per-symbol path. Legacy global
  objects remain preserved for compatibility but have no active multi-symbol
  decision authority.

## Validation

- Scoped Python compile: PASS.
- Stage 1 plus native fusion/Seam 7E compatibility: `64 passed`.
- Affected integration/guardrail suite: `116 passed`.
- Explicit run-path gate: `122 passed`.
- Compatibility gate: `130 passed`.
- Stage 0 invariant/fingerprint gate: `6 passed`.
- Final Stage 0 + Stage 1 covenant/acceptance rerun: `38 passed`.
- Final configured full suite: `1858 passed, 14 skipped, 384 warnings,
  0 failed` in `281.60s`.

The failure history is preserved in the report, including a discarded
post-report setup error caused by pytest selecting an inaccessible Windows temp
directory; the identical workspace-local-basetemp rerun passed. No
assertion-intent flip occurred. Fixtures were raised to the stricter contract with runtime-owned
temporal assessments, explicit symbol identity, and lawful decision clocks.
The 14 conditional broker/access skips remain skips, not passes.

## Proof and Safety Boundary

The highest rung reached is local offline tests. No UI/browser, live-feed
runtime, broker read, PAPER run, broker mutation, external submit/fill/sell-to-
close, PnL, profitability, live action, real money, or arming result is claimed.
No broker authorization variable was enabled.

No guard, threshold, strategy math, Risk, NetEdge, MarketTruthSnapshot, TTL,
sizing, masking, OMS, reconciliation, account pin, PAPER/live lock, no-short, or
no-naked-SELL control weakened. No module was deleted, flattened, forced to fire,
or replaced with a generic subsystem. SovereignExecutionGuard remains dormant.

## Known Limitations Preserved

- Analytical guard/fusion state restarts cold and fail-closed; warm persistence
  was not invented without a gap/reconciliation authority.
- Identical event/receipt/source duplicates use stable ingestion order as their
  final tie-break.
- External evidence batches conservatively use their maximum event/receipt
  clocks; one future record can hold back the batch.
- External feed timestamp quality, runtime throughput/memory, multi-day
  recovery, and broker behavior are unproven.
- Fusion is internally serialized, but concurrent same-symbol WebSocket/REST
  ordering across every upstream analytical engine was not stress-tested.
- Fourteen broker/access tests remain conditionally skipped; existing Pydantic
  and timezone-naive datetime warnings remain.
- The dynamic universe, protected baseline, forced exploration profile,
  external SELL adapter limitation, five-day ceiling, portfolio economics,
  campaign recovery, and multi-tenant isolation remain Stage 2+ work.

## Dirty Tree and Staging Boundary

Known test/runtime state files and pre-existing untracked evidence remain
protected. Never clean, reset, stash, prune, edit, or stage them. The Stage 1
report contains the exact 29-file staging list. It excludes `state/**`,
`.pytest_tmp/**`, old handoffs, proposal/restriction-review packets,
`reports/operator_perf/**`, logs, screenshots, secrets, databases, and untracked
audit scripts.

## Next Boundary

Stop at Stage 1. Stage 2 needs a new governance re-read, live-repo truth map,
entry manifest, independent red-team, binary exit, and explicit Board direction.
Stage 12 broker-read-only work and every Stage 13 PAPER campaign retain separate
approvals. Nothing in Stage 1 authorizes arming or execution.

## Governance Ruling After Stage 1

Shan directed a mandatory review loop before every future stage completion
report. `AGENTS.md` Section 25 is now the single owner of that process and is
cross-linked into Sections 5, 6, 8, 20, 21, and 23.

Before any future PASS report, the executor must freeze the candidate tree,
review the complete diff and active/unhappy paths as a fresh adversarial pass,
record every finding, fix root causes, and repeat review and tests whenever the
candidate changes. Behavioral fixes invalidate earlier green evidence. The
final exact tree must pass its declared gates, explicit critical run paths, and
full configured suite with zero failures when production behavior changed.
Higher proof rungs remain honest and separately authorized.

Every final report must contain a numbered review-cycle record and exactly one
current `PRE_CLOSE_REVIEW: PASS`, `FAIL`, or `BLOCKED` line. Only PASS permits a
completion verdict. A staged diff that differs from the reviewed candidate
invalidates the review.

This ruling is prospective and governance-only. Stage 1 history is not
rewritten; Stage 2 remains unopened. No product source, test contract, runtime,
broker, PAPER, live, or real-money behavior is changed or authorized.

Amendment review is itself governed by the new loop. Review Cycle 1 rejected
the initial candidate because Section 6 could place final binary exit tests
after `PRE_CLOSE_REVIEW: PASS`; Section 6 was corrected so those tests run
inside the loop. The first structural check also had two Unicode-matching false
negatives and is not proof. Review Cycle 2 then passed 13/13 semantic and safety
assertions plus `git diff --check` on the corrected governance candidate; no
product tests or higher proof rungs were run because no product behavior
changed. The review-record edit requires a final Cycle 3 diff and staged-scope
check. Subject to those exact-candidate checks, the terminal result is
`PRE_CLOSE_REVIEW: PASS`.

---

# Prior Handoff - PAPER True Capability Stage 0 Complete

Date: 2026-07-18 America/Chicago
Repo: `C:\Users\shahn\OneDrive\Desktop\poverty_killer`
Branch: `master`
Stage-entry HEAD: `d3692b6 clarify lifecycle deployment proof boundary`
Stage report: `reports/completion/PAPER_TRUE_CAPABILITY_STAGE_0_REPORT.md`

## Current Verdict

Shan explicitly approved Stage 0. It is complete and **PASS** at the local test
rung. At that historical Stage 0 boundary, Stage 1 had not been opened; the
current Stage 1 close truth is recorded above.

Stage 0 added only a deterministic sanitized fixture, six offline regression
tests, and its governance/evidence updates. No production application, UI,
script, runtime configuration, state, broker state, or trading authority changed.

## Evidence Frozen

- Historical source:
  `logs/paper_runs/bounded_paper_20260717_182808.out.log`, SHA-256
  `335a67411bac595b2d5928a5d9e4fee06d2bd4d64e88c14969e8caafcd098240`,
  106,512,681 bytes. The raw log remains unstaged.
- Sanitized fixture: 80 decision-path candidates; 50 protected-baseline
  refusals; 15 `BEARISH_NO_LONG`; 13 absolute-drift refusals; 2 safe-mode
  refusals; zero order submissions.
- Signed ages `-84711522000` and `-95000000000` ns remain classified as
  future-dated causal contamination, not freshness.
- The run made zero broker mutations, preserved four positions, expired at the
  14,400-second boundary without flattening, and reconciled with zero open
  orders or conflicts.
- Final reconciliation also observed 55 older broker-filled orders and 92
  missing hydration attempts. Those are historical broker rows, not fills from
  this run and not silently rewritten to zero.

## Frozen Invariants and Proof Vocabulary

Seventeen invariants map to 20 unique executable negative tests: PAPER endpoint
only; account pin before order one; live/real-money disabled; no naked/short
SELL; no manual trade controls; MarketTruthSnapshot freshness; Risk; NetEdge;
sizing; TTL; OMS; reconciliation/no fake fills; governed Stop with zero broker
mutation; dormant SovereignExecutionGuard; unchanged defaults; and no readiness
from lower proof rungs.

The only allowed activation states are `IMPLEMENTED_OFFLINE`, `OBSERVE_ONLY`,
`MOCKED_EXECUTION_PROVEN`, `BROKER_READ_PROVEN`, and
`BOUNDED_PAPER_PROVEN`. Every fixture row has Start, broker mutation, current
activation, and live authority set false.

The fixture also pins the six-symbol commissioning list, forced
`PAPER_EXPLORATION_ALPHA` profile, allowed durations/five-day ceiling, ten
default/exploration threshold pairs, expected suffix `045ded`, seven authority
owners, Phase B's 397-module classification, broker POST/DELETE surface, and 16
source hashes.

## Validation

- Python compile: PASS.
- Stage 0 focused: `6 passed`.
- Exact invariant nodes: `20 passed`, 75 warnings.
- Run-path gate: `119 passed`, 78 warnings.
- Full suite: `1826 passed, 14 skipped, 384 warnings, 0 failed`.

Two harness mistakes are explicitly non-results: a first focused command used a
fixed `C:\tmp` base path that pytest could not create, and a first full-suite
wrapper had a one-second process timeout. Both were rerun correctly; neither is
counted as proof. The 14 broker/access tests remain conditional skips, not
passes. No broker authorization variable was enabled.

## Known Blockers Preserved

- The capability registry declares Alpaca crypto `sell_to_close`, while
  `AlpacaPaperBrokerAdapter._payload_for_order()` still rejects every SELL with
  `only_buy_supported`. This is a named Stage 8 blocker, not a pass.
- The six-symbol universe, forced exploration profile, protected-baseline
  blanket veto, buy-only external adapter, and five-day ceiling remain current
  commissioning limitations.
- GammaFront remains `WIRED_EXIT_ONLY / ENTRY_FEED_DORMANT`.
- SovereignExecutionGuard remains preserved dormant.
- Existing Pydantic and timezone-naive datetime deprecation warnings remain
  visible and unresolved.

## Proof and Approval Boundary

The highest rung climbed is local tests. No browser, runtime, market-freshness,
current broker, external submit/fill/sell-to-close, recovery, dynamic-universe,
or profitability claim was made. No broker GET, PAPER run, broker mutation,
live action, real money, threshold/control change, dependency, deletion, or
module activation occurred.

Stop at the Stage 0 boundary. Stage 1 needs its own full re-read, truth map,
stage-entry manifest/red-team, and explicit direction from Shan. Stage 12 broker
reads and every Stage 13 PAPER campaign remain separately Board-gated.

## Exact Stage 0 Staging Scope

```text
AGENTS.md
CHECKPOINT_TRACKER.md
reports/codex_handoff_latest.md
reports/completion/PAPER_TRUE_CAPABILITY_MASTER_PLAN.md
reports/completion/PAPER_TRUE_CAPABILITY_STAGE_0_REPORT.md
tests/fixtures/paper_true_capability_stage0.json
tests/test_paper_true_capability_stage0.py
```

Never stage protected `state/**`, `.pytest_tmp/**`, logs, old handoffs, UI
proposal/restriction-review packets, `reports/operator_perf/**`, screenshots,
untracked audit scripts, credentials, secrets, databases, or runtime artifacts.

---

# Prior Handoff - PAPER True Capability Planning

Date: 2026-07-18 America/Chicago
Repo: `C:\Users\shahn\OneDrive\Desktop\poverty_killer`
Branch: `master`
Planning baseline: `d3692b6 clarify lifecycle deployment proof boundary`
Full report: `reports/completion/PAPER_TRUE_CAPABILITY_MASTER_PLAN.md`

## Current Verdict

Shan requested a complete, red-teamed plan to remove commissioning-only PAPER
restrictions, broaden the tradable crypto universe, and let the bot lawfully
manage existing holdings. The plan, non-degradation covenant, and autonomous-
campaign addendum are complete; implementation has not started and approval is
pending.

Live-repo inspection showed that replacing the six-symbol list or enabling SELL
first would expose existing causal and authority defects. The adjusted program
therefore repairs per-symbol/time causality and consolidates broker inventory
truth before dynamic catalog activation, fill-driven strategies, governed
sell-to-close, upgraded portfolio economics, and natural PAPER proof.

No source, test, configuration, runtime state, broker state, guard, threshold,
or trading authority changed. No test, runtime, browser, broker read, or PAPER
run was performed in this planning session.

## Approval Boundary and Next Step

- Await explicit Board approval for offline implementation Stages 0-11.
- Before every stage, execute the Board-ratified `AGENTS.md` Section 23 manifest
  and record `STAGE_ENTRY_COVENANT: PASS`; otherwise that stage cannot begin.
- On approval, begin with Stage 0 and Stage 1 only; run their binary exit gates
  and report before wider-universe or SELL work.
- Stage 12 broker-read-only validation requires a separate approval.
- Every Stage 13 autonomous PAPER campaign requires its own separate approval.
- No live mode, real money, manual buy/sell/force controls, shorting, naked SELL,
  threshold weakening, or self-arming is proposed.

## Board-Ratified Non-Degradation Covenant

On 2026-07-18 Shan directed that every true-capability stage hard-bind a
non-degradation and restriction-removal covenant. It is now encoded in
`AGENTS.md` Section 23 and referenced immediately beneath every Stage 0-13
heading in the master plan.

The covenant prohibits deletion, flattening, truncation, dumbing down,
code/math/quant simplification, control or limit loosening, target trade counts,
test weakening, hidden configuration expansion, fake proof, silent modules,
duplicate authority, and unapproved money-adjacent work. It also requires
causality, broker truth, reconciliation, robust uncertainty-aware mathematics,
state/restart integrity, rate-limit/capacity proof, exact staging, and honest
unknowns. A commissioning restriction can be replaced only after named repo
proof, classification, a complete production owner, adversarial tests, and an
accounted before/after capability matrix. An affected `UNKNOWN` remains
fail-closed; a proven scaffold must leave the active path and cannot survive as
a renamed or hidden veto. Quant research integrity, out-of-sample claims,
numeric failure handling, uncertainty, and full net economics are mandatory.

This ruling strengthens execution governance only. Implementation remains not
started and still awaits Board approval.

## Autonomous Campaign and Future Multi-Tenant Direction

On 2026-07-18 Shan directed that commissioning mini-runs end after the true-
capability prerequisites pass. The intended external PAPER sequence is now:

1. 8 continuous hours with the full standard-profile lawful capability;
2. 7 continuous days after the 8-hour gate passes;
3. 30 continuous days after the 7-day gate passes;
4. governed endurance and controlled-failure certification after the month.

The current code cannot execute this sequence: runner, supervisor, runtime
config, API/UI, and tests enforce a five-day (`432000` seconds) maximum. Do not
delete that validation or merely increase scattered literals. The master plan
and `AGENTS.md` Section 24 require one typed, versioned, immutable finite
campaign envelope in the existing owners plus a shorter renewable fenced worker
lease. Autonomous renewal/recovery is allowed only inside the approved horizon,
with current health/fingerprint checks and broker reconciliation before new
entries. It cannot self-arm or extend the campaign.

`FULL_CAPABILITY` means every `WIRED_WITH_ROLE` module receives its lawful
production inputs and reports source-emitted truth through the standard profile,
dynamic broker universe, broker-backed entry/exit lifecycle, and unchanged
MarketTruthSnapshot/NetEdge/Risk/sizing/OMS/reconciliation gates. It does not
force every module or candidate to fire. Dormant/inapplicable modules remain
truthful, and zero natural trades is lawful.

The literal request to run without limit until a crash is a surfaced safety
disagreement. Its lawful, stronger replacement is a Board-bounded endurance
campaign with defined steady state, controlled process/host/network/broker/feed/
clock/storage/restart faults, hard stop conditions, fencing, and final
reconciliation. Each external PAPER campaign still requires separate approval.
No PAPER run is authorized by this planning update.

Multi-tenant activation is deferred until the campaign program finishes. Avoid
unnecessary single-tenant hardcoding now, but do not invent a parallel tenant
subsystem. Before a second tester, credentials, account pin, state, campaign,
lease/fencing, Risk, OMS, orders/fills, reconciliation, audit, UI, logs, and AI
evidence must be isolated per tenant/account and pass cross-tenant negative
tests. Authentication alone is not isolation.

Tiny live-money work remains Checkpoint I and individually Board-gated. Alpaca
PAPER omits market impact, information leakage, latency slippage, queue position,
price improvement, and some live fees, so even stable or profitable month-long
PAPER evidence cannot automatically authorize live trading.

No source, test, runtime configuration, state, broker state, cloud resource,
PAPER run, or live path changed in this planning update. No tests/runtime/browser
or broker calls were run.

## Protected Worktree

Pre-existing modified `state/*` files and untracked reports, audit scripts,
`.pytest_tmp/`, and operator-performance artifacts remain protected and were
not cleaned, reset, staged, or modified. The only planning files intended for
possible staging are `AGENTS.md`, the master plan, `CHECKPOINT_TRACKER.md`, and
this handoff.

---

# Prior Handoff - Operator Process Lifecycle Recovery

Date: 2026-07-15 America/Chicago
Repo: `C:\Users\shahn\OneDrive\Desktop\poverty_killer`
Branch: `master`
Starting commit: `e958abd make bounded paper start explicit`
Code commit: `3e71c55 make operator backend lifecycle truthful`
Full report: `reports/completion/OPERATOR_PROCESS_LIFECYCLE_RECOVERY_REPORT.md`

## Current Verdict

The screenshot's `BOT STALE` state was false current vitality, not a stale
backend. The current supervisor was idle while a historical heartbeat artifact
was overriding it. The cockpit and local process lifecycle are fixed.

- Full suite: `1820 passed, 14 skipped, 0 failed`.
- Desktop/mobile browser proof: BOT IDLE, MKT NO_RUNTIME, frozen pulses, no
  horizontal overflow.
- Isolated last-cockpit shutdown proof: idle backend exited in 10.254s and 9.64s.
- No PAPER run, broker mutation, live mode, or real money.

## Implemented Contract

1. `/operator/events` counts attached cockpit streams.
2. Closing the last stream starts an eight-second reconnect grace.
3. Grace expiry requests the existing stack-shutdown owner with
   `require_idle_supervisor=true`.
4. The backend refuses automatic shutdown unless the supervisor is exactly
   `IDLE`; active/uncertain runtimes are preserved.
5. Start and shutdown admission are serialized, so a Start cannot race an
   accepted shutdown.
6. Launcher startup replaces an orphaned/lifecycle-old/code-stale idle backend
   and opens the current cockpit.
7. Existing `Stop Backend` remains the explicit process-only operator command.

No unload callback, broad process-name kill, new shutdown subsystem, or browser
authority over trading lifecycle was added.

## Recorded Live Truth and Final Close Gate

The updated launcher first replaced backend PID `17708` with PID `20824` and
loaded code commit `3e71c55`. After evidence commit `9cf1e25`, a second guarded
idle refresh loaded that then-current HEAD on PID `4072`; a current cockpit was
opened and two event streams attached.

- supervisor: `IDLE`; no active run
- idle exit: enabled; cockpit clients attached
- final readiness: `READY_FOR_BOUNDED_PAPER`
- Start allowed: true; Stop allowed: false while idle
- expected/actual account suffix: `045ded` / `045ded`
- portfolio: `BROKER_CONFIRMED`
- positions: 4 (`AVAXUSD`, `ETHUSD`, `LINKUSD`, `SOLUSD`)
- open orders: 0
- visibility: BOT `IDLE`, MKT `NO_RUNTIME`, pulse false
- broker read: true; broker/order/cancel/close/liquidation mutation: false

The GET-only verification is process-scoped and must be repeated after a future
backend restart. Codex did not press Start.

Committing this handoff necessarily changes HEAD again. Session close must
therefore perform one last guarded idle refresh and re-run the GET-only proof,
then require `loaded_commit == repo_head`. The exact final commit/PID belongs in
terminal/final-response evidence; this versioned file does not predict its own
commit hash.

## Honest Validation Notes

- Default pytest temp and `C:\tmp` were access-denied on two attempts; the same
  tests passed using a workspace-owned temp base.
- One malformed wildcard command collected zero tests and was replaced by an
  explicit file list.
- In-app browser bootstrap failed (`missing field sandboxPolicy`); Edge/CDP was
  the recorded browser fallback.
- A collided CDP port showed an old tab and was rejected as evidence; proof was
  repeated on unused port 9333.
- A cleanup helper overmatched its own PowerShell command only; no operator or
  trading process was killed by that mistake.
- A post-deploy poll used obsolete field `loaded_git_commit_short`; canonical
  `loaded_commit` proved the new backend was already current.

## Safety Boundary

The literal "kill all on browser close" behavior is intentionally bounded:
closing the last cockpit stops only an idle API. It never kills an active or
uncertain PAPER runtime. Governed Stop remains the run-lifecycle authority and
protected positions remain under the bot's automated lifecycle.

No Risk, NetEdge, sizing, TTL, masking, strategy, OMS, broker-governor, or
execution threshold changed. `SovereignExecutionGuard` remains dormant.

## Exact Remaining Staging

Stage exactly:

1. `reports/completion/OPERATOR_PROCESS_LIFECYCLE_RECOVERY_REPORT.md`
2. `CHECKPOINT_TRACKER.md`
3. `reports/codex_handoff_latest.md`

Never stage protected `state/*`, `.pytest_tmp/`, screenshots, logs, secrets,
old handoffs, UI proposal packets, operator-performance output, or untracked
audit scripts.
