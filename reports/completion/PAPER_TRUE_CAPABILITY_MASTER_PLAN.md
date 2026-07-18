# PAPER True Capability Master Plan

Date: 2026-07-17; autonomous-campaign addendum 2026-07-18
Board: Shan
Prepared from: live repository inspection, the completed 2026-07-17 four-hour PAPER run, Board campaign direction, and official documentation research
Planning baseline: `master` at `d3692b6` (`clarify lifecycle deployment proof boundary`)
Implementation status: **NOT STARTED - STAGE AND CAMPAIGN COVENANTS RATIFIED; IMPLEMENTATION APPROVAL STILL REQUIRED**

## 1. Verdict

The bot can be opened from its commissioning configuration into a materially
broader and more capable **Alpaca PAPER-only autonomous trading system**, but it
must not be opened by deleting guards or simply replacing the six-symbol list
with every broker symbol.

The current runtime is not ready for a wider universe or broker-backed exits.
The deepest blockers are not strategy selectivity. They are authority and
causality defects:

1. one global `SignalFusion` cache is shared across all symbols;
2. future-dated evidence is treated as fresh;
3. the portfolio risk owner is not hydrated with the complete broker book;
4. inherited holdings have no durable lot/provenance model;
5. the Alpaca adapter claims `sell_to_close` capability but rejects every SELL;
6. strategy-local position state changes before broker acknowledgement/fill;
7. the current all-symbol REST polling shape cannot scale;
8. several module-contribution records infer activity instead of reporting
   source-emitted activity;
9. important portfolio and opportunity models still contain explicitly
   illustrative or placeholder arithmetic.

The corrected direction is:

> Discover the complete broker-supported PAPER crypto catalog, scan it broadly
> with bounded data cost, deeply process the strongest executable candidates and
> every held/open-order symbol, allow every candidate that survives causal market
> truth, NetEdge, risk, sizing, capability, and OMS gates, and allow only
> broker-position-backed automated sell-to-close through governed lifecycle
> reasons.

"Free to run" cannot mean unbounded risk, naked selling, stale data, manual
trades, or an indefinitely self-arming process. It means the bot, not a static
operator whitelist, chooses among every lawfully executable PAPER opportunity.

Board direction on 2026-07-18 removes the remaining commissioning mini-run
ladder from the target plan. After Stages 0-12 pass, the next external proof is
an 8-hour full-capability standard-profile autonomous PAPER campaign, followed
only on prior-gate success by 7-day and 30-day campaigns. The requested final
"until crash" trial is adjusted to a governed endurance and controlled-failure
campaign with a Board-declared maximum horizon and hard stop conditions. The
fixed five-day implementation cannot execute the requested week/month sequence
today and must be replaced by a campaign envelope plus shorter renewable fenced
worker leases, not bypassed or deleted.

No implementation, PAPER run, broker mutation, broker GET, live-mode work,
threshold change, or runtime-state edit was performed while producing this
plan.

## 2. Files Changed

- `AGENTS.md` - adds the Board-ratified true-capability stage-entry covenant and
  autonomous-campaign/future-multi-tenant covenant without replacing or
  weakening Sections 0-22.
- `reports/completion/PAPER_TRUE_CAPABILITY_MASTER_PLAN.md` - this planning and
  red-team artifact.
- `CHECKPOINT_TRACKER.md` - records that the capability-opening program is a
  pending plan, not trading authorization.
- `reports/codex_handoff_latest.md` - preserves the evidence, approval boundary,
  and correct next step for the next session.

No source, test, configuration, state, log, database, secret, or operator
baseline file was changed while drafting this report.

## 3. Evidence Base and Root Cause

### Repository and worktree truth

Current branch: `master`
Current commit: `d3692b6`

Protected pre-existing dirty/untracked files observed and not touched:

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

### Four-hour run truth

Inspected runtime evidence:

- `logs/paper_runs/bounded_paper_20260717_182808.out.log`
- size: 106,512,681 bytes
- final line: six symbols, 492 iterations, zero submitted orders
- final broker mutation counts: zero POST, DELETE, cancel, replace, sell, or
  rebalance operations
- four broker positions remained intact and final open-order count was zero
- the run stopped on its duration boundary and performed final reconciliation

The run produced 80 executable-market-truth candidate frames that reached the
decision path. Their terminal blockers were:

- 50 protected-baseline refusals across AVAX, ETH, LINK, and SOL;
- 15 lawful `BEARISH_NO_LONG` refusals on BTC/LTC without owned positions;
- 13 `STALE_DATA_GUARD_ABSOLUTE_DRIFT_LIMIT_BREACH` refusals;
- 2 `STALE_DATA_GUARD_SAFE_MODE` refusals.

Every one of those 80 carried `ECONOMICALLY_ADMISSIBLE`, but they also carried
missing/degraded evidence including WhaleFlow, TradeEfficiency, dispatch-time
InvariantChecker, dispatch-time broker reconciliation, LiquidityVoid pairs,
GammaFront entry evidence, and AdaptiveDC native evidence. This does **not**
prove that all 80 should have traded. It proves that threshold relaxation is not
the root solution and that the active evidence graph is incomplete.

The same log contains DecisionFrames that label future-dated inputs fresh, for
example:

- Shans Curve `age_ns=-84711522000`, reason `NATIVE_SIGNAL_FRESH`;
- Regime Detector `age_ns=-95000000000`, reason `NATIVE_SIGNAL_FRESH`.

Negative age means the cached input timestamp is later than the decision
timestamp. That is causal contamination, not freshness.

### Plain-English blocker one-liners

| Blocker | Plain-English truth |
| --- | --- |
| Static universe | The launcher and capability registry nominate exactly six pairs instead of asking Alpaca what this PAPER account can trade now. |
| Effective universe | Four of the six pairs are protected holdings, leaving only BTC and LTC for fresh entries in the completed run. |
| Cross-symbol fusion | BTC can consume a Shans, regime, whale, toxicity, entropy, insider, or physical cache value most recently written by another symbol. |
| Future evidence | The fusion engine treats negative signal age as perfectly fresh, allowing information from after a decision timestamp into that decision. |
| Stale guard | A new rolling `StaleDataGuard` is constructed for each candidate, so its kinematic history is discarded and a closed-candle clock is compared to a 500 ms transport-drift rule. |
| Data scaling | The REST client makes a candle request for every symbol and then a book request for every symbol each cycle; widening the list would overload the current path. |
| Venue truth | Coinbase/Kraken market data can drive an Alpaca execution decision without an Alpaca execution-venue basis being the canonical executable quote. |
| Asset metadata | `InstrumentRegistry` hard-codes float precision, labels Alpaca-confirmed crypto as Kraken, and marks spot crypto margin available even though Alpaca crypto is non-marginable. |
| Baseline ownership | The bot cannot distinguish inherited quantity, bot-acquired quantity, and quantity reserved for an open sell, so it blocks all same-symbol activity. |
| Incomplete portfolio risk | `ExposureManager` hydrates reservations but not all broker positions and fills; normal entries do not consistently supply the complete broker book. |
| No external SELL | `AlpacaPaperBrokerAdapter._payload_for_order()` rejects every side except BUY even though the capability registry advertises sell-to-close. |
| Unsafe SELL classification | A generic SELL can be labeled sell-to-close merely because matching position metadata exists; lifecycle provenance is not explicit enough. |
| Strategy state | Several strategies latch entry state when they emit a signal and book/reset local PnL when they emit an exit, before broker truth confirms either event. |
| Emergency lifecycle | active risk callbacks call a fire-and-forget `close_all_positions()` path while the sophisticated `PositionUnwindManager` has no active caller. |
| Module wiring | AdaptiveDC is test/replay-capable but not fed by the production runtime; GammaFront entry is honestly feed-dormant; WhaleFlow was missing in fusion; LiquidityVoid emitted no consumable pair in this run. |
| Quant models | `OpportunityRanker` uses placeholder costs and a fixed weighted score; `CrossAssetRiskCalculator` explicitly labels its stress factors illustrative and uncalibrated. |
| Evidence truth | `whole_bot_attribution` can label execution boundaries approved and manufacture degraded MovingFloor/AdaptiveDC signatures without a source module invocation. |
| Forced research profile | The launcher always selects `PAPER_EXPLORATION_ALPHA`, which already lowers multiple strategy/fusion thresholds; lowering them further would hide defects. |
| Service boundary | The supervised lease and explicit arming are governance controls, not alpha constraints, and may not be silently removed. |

### Named live code paths

#### Static catalog and forced profile

- `app/api/operator_runtime_config.py::DEFAULT_ALLOWED_WATCHLIST`
- `app/api/operator_runtime_config.py::OperatorRuntimeConfig.allowed_profile`
- `app/api/operator_paper_supervisor.py::DEFAULT_WATCHLIST`
- `app/api/operator_paper_supervisor.py::OperatorPaperSupervisor._validate_start_request`
- `app/api/operator_paper_supervisor.py::OperatorPaperSupervisor._build_start_spec`
- `scripts/supervise_bounded_paper.py`
- `scripts/run_bounded_paper.ps1`
- `app/market/capability_registry.py::ALPACA_PAPER_CRYPTO`
- `main.py::resolve_runtime_universe`

#### Cross-symbol and future-data causality

- `main.py::SovereignHeartbeat.__init__` creates one `SignalFusion`.
- `main.py::SovereignHeartbeat._on_trade` writes its global WhaleFlow result to
  that fusion cache before invoking the per-symbol runtime.
- `app/main_loop.py::MainLoop.on_order_book` writes per-symbol Shans/regime into
  the same global cache.
- `app/main_loop.py::MainLoop.on_candle` writes per-symbol whale/toxicity/
  entropy/insider into the same global cache and then calls `fuse()` per symbol.
- `app/brain/signal_fusion.py::SignalFusion._cache` is keyed only by module
  name, not symbol.
- `app/brain/signal_fusion.py::SignalFusion.fuse` checks only `age_ns > ttl`.
- `app/brain/signal_fusion.py::QuantMath.temporal_discount` returns 1.0 for
  `age_ns <= 0`.

#### Temporal guard mismatch

- `app/risk/pre_trade_guardrails.py::_append_stale_data_guard_evidence` creates
  `StaleDataGuard(symbol=request.symbol)` for every evaluation.
- `app/main_loop.py::_pre_trade_stale_data_observation` derives its observation
  from snapshot/candle timing.
- `app/risk/stale_data_guard.py::StaleDataGuard.assess` is explicitly a rolling
  kinematic model, but the active caller prevents it from remaining rolling.

#### Inventory and baseline

- `app/operator_activation/paper_baseline.py::build_paper_baseline_runtime_context`
  hard-codes `run_lot_tracking_available=False`.
- `app/operator_activation/paper_baseline.py::evaluate_protected_baseline_trade`
  blocks protected-symbol BUY and SELL without lot tracking.
- `BASELINE_POLICY_MANAGE_EXISTING` exists but is not the active supervisor
  policy.
- `main.py::SovereignHeartbeat._bootstrap_reservation_lifecycle_disabled`
  constructs `ExposureManager` and hydrates reservation rows, not the complete
  broker inventory.
- `app/risk/exposure_manager.py` already contains durable reservation,
  fill/inventory, forced reconciliation, concentration, and correlation-aware
  machinery and should remain the risk owner.
- `app/state/state_store.py` already contains positions, active order mappings,
  reservation ledgers, fill progress, release tombstones, and the canonical
  broker fill ledger.

#### Execution and exits

- `app/execution/alpaca_paper_adapter.py::AlpacaPaperBrokerAdapter._payload_for_order`
  appends `only_buy_supported` for every SELL.
- `app/market/capability_registry.py::_alpaca_crypto_capability` advertises
  `buy` and `sell_to_close`, creating a contract contradiction.
- `app/main_loop.py::MainLoop._build_moving_floor_signal` constructs a
  broker-position-backed sell-to-close only when its worst-case price is above
  average entry, so it is profit protection, not a general stop-loss.
- `app/main_loop.py::_classify_sell_intent` can infer exit authority too broadly
  from matching position metadata.
- `app/execution/order_router.py::_gateway_buying_power_pre_post_response` has a
  final broker-read gate for BUY only; there is no equivalent fresh-position and
  open-sell-reservation gate for SELL.
- `app/execution/order_router.py::_gateway_request_from_order` drops most
  lifecycle provenance before adapter submission.
- `app/execution/engine.py::ExecutionEngine._emergency_liquidate_all` calls
  `OrderRouter.close_all_positions()` fire-and-forget.
- `app/risk/position_unwind.py::PositionUnwindManager` provides a sophisticated
  campaign, tranche, retry, escalation, partial-fill, and dust-aware owner but
  has no production construction/caller.

#### Strategy and evidence state

- `SectorRotationStrategy`, `ShadowFrontStrategy`, `LiquidityVoidStrategy`, and
  `GammaFrontStrategy` keep local/provisional position state.
- SectorRotation and ShadowFront calculate/book local PnL and clear position
  state at exit-signal generation, not reconciled sell fill.
- GammaFront is correctly labeled local diagnostic PnL, but its entry feed
  remains dormant.
- `app/strategies/adaptive_dc.py::AdaptiveDC` is exercised by tests/replay and
  has a vote adapter, but has no production MainLoop feed.
- `app/core/whole_bot_attribution.py::build_runtime_edge_attribution` inserts
  generic signatures for modules and execution boundaries even when their
  native path did not run.

#### Simplified or illustrative quant surfaces

- `app/portfolio/opportunity_ranking.py::OpportunityRanker.rank` uses hard-coded
  fee/impact placeholders and a fixed 40/35/25 weighted average.
- `app/risk/cross_asset_risk_model.py::CrossAssetRiskCalculator` receives but
  does not use correlation estimates in its report and labels scenario shocks
  `illustrative_only` and `no_covariance_calibration`.
- `app/strategies/sector_rotation.py::_calculate_position_size` uses fixed
  simulated capital, although the downstream canonical
  `PositionSizingEngine` later resizes the signal.
- `app/risk/position_sizing.py::PositionSizingEngine` is the correct executable
  sizing owner and must absorb richer portfolio/tail/liquidity evidence rather
  than allowing strategy-local quantities to become authoritative.

## 4. Research Used

### Official Alpaca documentation

1. [Crypto Spot Trading](https://docs.alpaca.markets/us/docs/crypto-trading)
   documents a broker-discoverable catalog, 20+ crypto assets and 56 pairs at
   the time of the documentation, per-asset minimum size/trade increment/price
   increment, non-marginable/non-shortable spot crypto, and market/limit/
   stop-limit orders with GTC or IOC.
2. [Get Assets](https://docs.alpaca.markets/us/reference/get-v2-assets-1)
   identifies `/v2/assets` as Alpaca's master list for trade and data
   consumption.
3. [Crypto Snapshots](https://docs.alpaca.markets/us/reference/cryptosnapshots-1)
   accepts a comma-separated symbol set and returns latest trade, quote, minute
   bar, daily bar, and prior daily bar. This supports a breadth tier without
   two REST calls per symbol per second.
4. [Real-time Crypto Data](https://docs.alpaca.markets/us/docs/real-time-crypto-pricing-data)
   provides symbol-tagged trades, quotes, order books, and bars over WebSocket
   and makes the market-data location/source explicit.
5. [WebSocket Streaming](https://docs.alpaca.markets/us/docs/websocket-streaming)
   documents `trade_updates` events for new, partial fill, fill, cancel,
   expiration, rejection, and replacement. Streaming plus REST reconciliation
   is the correct lifecycle pattern.
6. [Placing Orders](https://docs.alpaca.markets/us/docs/orders-at-alpaca)
   recommends streaming for open-order state and documents the broker order
   lifecycle.
7. [Paper Trading](https://docs.alpaca.markets/us/docs/paper-trading) states that
   PAPER is an end-to-end real-time simulation but does not account for market
   impact, information leakage, latency slippage, queue position, price
   improvement, regulatory fees, or dividends. It also documents simulated fill
   and liquidity assumptions. Applied lesson: long PAPER campaigns prove system
   operation and simulated execution, not live execution quality or profitability.

No Alpaca endpoint was called while preparing this report. The actual catalog
available to the pinned PAPER account remains unknown until Shan separately
authorizes the narrow read-only GET.

### Mature-system patterns considered

1. [Freqtrade dynamic pairlists](https://www.freqtrade.io/en/stable/plugins/)
   chain volume, listing age, delist, precision, price, spread, stability, and
   volatility filters. Applied lesson: broad discovery must be followed by
   independently evidenced eligibility filters, and costly deep analysis must
   occur after breadth reduction.
2. [QuantConnect universe key concepts](https://www.quantconnect.com/docs/v2/writing-algorithms/algorithm-framework/universe-selection/key-concepts)
   separate universe selection from downstream alpha models.
3. [QuantConnect universe behavior](https://www.quantconnect.com/docs/v1/algorithm-reference/universes)
   retains data for held assets and assets with open orders even after universe
   deselection. Applied lesson: holdings and active orders remain in the deep
   tier regardless of rank.

### Autonomous campaign, resilience, and tenant-isolation research

1. [AWS SaaS tenant isolation](https://docs.aws.amazon.com/whitepapers/latest/saas-architecture-fundamentals/tenant-isolation.html)
   separates tenant isolation from ordinary authentication and authorization.
   Applied lesson: tenant context must constrain every credential, state,
   execution, risk, and evidence resource; a tenant ID or authenticated session
   alone is insufficient.
2. [AWS tenant isolation strategies](https://docs.aws.amazon.com/whitepapers/latest/saas-tenant-isolation-strategies/saas-tenant-isolation-strategies.html)
   describes silo, pool, bridge, and identity-aware isolation patterns. Applied
   lesson: choose and threat-model the isolation model before admitting a second
   tester; do not retrofit it after pooled state exists.
3. [DynamoDB concurrent-update guidance](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/BestPractices_ImplementingVersionControl.html)
   documents conditional writes and lease/heartbeat locking for long-running
   distributed coordination. Applied lesson: any future distributed campaign
   coordinator needs fencing/conditional ownership; a heartbeat timestamp alone
   cannot prevent two broker mutation owners. This is a design lesson, not a
   dependency decision.
4. [AWS Fault Injection Service stop conditions](https://docs.aws.amazon.com/fis/latest/userguide/stop-conditions.html)
   requires a defined steady state and can stop an experiment through CloudWatch
   alarms. Applied lesson: an endurance/chaos campaign needs declared steady
   state, fault scope, stop conditions, and a maximum experiment boundary. AWS
   FIS is not approved or provisioned by this plan.

### Applied design lessons

- Broker catalog is canonical for availability and precision.
- Executable price truth comes from the execution venue/data location; other
  venues are advisory features only.
- Use a broad, cheap tier and a bounded, deep tier.
- Retain every held/open-order symbol even when it falls out of the opportunity
  universe.
- Consume broker order events incrementally but reconcile against REST truth.
- Dynamic membership needs refresh cadence, hysteresis, reason codes, and
  reproducible snapshots.
- A long autonomous campaign needs an immutable outer authorization envelope and
  renewable fenced worker leases rather than one week/month-long stale lock.
- Crash/restart proof must reconcile broker truth before entries and must prove
  the prior mutation owner cannot resume.
- Tenant isolation is a separate resource-access invariant, not a login feature.
- PAPER stability and PnL cannot be promoted to live execution proof.

### Intentionally rejected patterns

- No proprietary UI/design copying.
- No blind top-volume whitelist.
- No trading every listed pair.
- No static catalog fallback represented as broker truth.
- No user-facing manual close/sell/cancel-all control.
- No market order as a universal entry mechanism.
- No automatic self-arming beyond an explicitly approved finite campaign
  envelope.
- No unbounded broker-mutating "run until crash" experiment.
- No forced module output or target trade count as proof of full capability.
- No pooled multi-tenant execution before credential/state/lease/order isolation.
- No new exchange, cloud subsystem, AWS resource, or external dependency in this
  planning addendum.

## 5. Restriction Disposition

| Current restriction/control | Disposition | Reason |
| --- | --- | --- |
| Six-symbol operator whitelist | **REPLACE** | Broker discovery plus executable-data filters should own eligible PAPER crypto. Keep six only as deterministic test fixtures. |
| Static `InstrumentRegistry` execution metadata | **CONSOLIDATE/REPLACE** | Hydrate the existing registry/capability owner from broker asset facts; stale static values cannot authorize execution. |
| All protected-symbol BUY/SELL blocked forever | **REPLACE** | A reconciled inventory/lot owner can safely distinguish inherited, acquired, sold, and reserved quantity. |
| Governed baseline acceptance | **RETAIN** | It proves the starting broker book/account and must evolve into an opening-inventory snapshot, not disappear. |
| `run_lot_tracking_available=False` | **IMPLEMENT IN EXISTING OWNERS** | Use StateStore, ExposureManager, OMS mappings, broker fill ledger, and reconciliation; do not create a parallel ledger. |
| Alpaca adapter BUY-only | **REPLACE** | Add only explicit broker-backed sell-to-close; continue blocking naked/short SELL. |
| Limit-only adapter | **REPLACE WITH CAPABILITY POLICY** | Support broker-valid order types/TIF by lifecycle and market conditions, with conservative escalation. |
| Forced `PAPER_EXPLORATION_ALPHA` | **REMOVE AS DEFAULT** | It is a threshold-relaxation test profile, not production capability. Preserve it as an explicitly labeled research/replay profile. |
| Existing default strategy/risk thresholds | **RETAIN** | Do not weaken. The standard runtime returns to existing defaults after data and wiring are corrected. |
| Poll every symbol deeply | **REPLACE** | Batch/stream breadth then bounded deep subscriptions with rate budgets and backpressure. |
| Feed-router fallback that does not switch transport | **FIX IN EXISTING ROUTER** | A selected fallback must become the active transport or execution truth must fail closed. |
| Broker account suffix pin | **RETAIN** | It prevents the child from trading the wrong PAPER account. |
| PAPER endpoint and live lock | **RETAIN** | This plan contains no live or real-money enablement. |
| No crypto margin/shorting | **RETAIN** | Alpaca spot capability, not a training wheel. |
| SELL requires fresh owned quantity | **RETAIN AND STRENGTHEN** | Required to prevent naked/oversell and duplicate exits. |
| MarketTruthSnapshot, stale/TTL, NetEdge | **RETAIN AND UPGRADE INPUTS** | Professional hard controls; defects must be fixed without relaxing limits. |
| Position sizing/concentration/drawdown | **RETAIN AND UPGRADE MATH** | Broad scanning must not become broad uncontrolled exposure. |
| OMS/idempotency/reconciliation | **RETAIN AND COMPLETE** | Required for partial fills, restart, duplicate events, and broker truth. |
| Singleton mutation owner | **RETAIN** | Prevents duplicate broker commands. |
| Fixed `432000`-second runner ceiling and duration list | **REPLACE AFTER OFFLINE CERTIFICATION** | It blocks the Board's 7-day and 30-day campaigns and is scattered across runner/API/UI/tests. Replace it through the existing config/supervisor owners with a typed campaign policy; never simply delete the ceiling. |
| Explicit Board arming and finite campaign envelope | **RETAIN AND EXTEND** | Required by governance. Every campaign pins a maximum horizon and immutable authority fingerprints. |
| Renewable fenced worker lease inside a campaign | **IMPLEMENT IN EXISTING SUPERVISOR OWNER** | Short renewal limits stale ownership while permitting autonomous operation inside the approved horizon; it never extends or creates a campaign. |
| Governed Stop does not flatten | **RETAIN** | Stop halts new work and releases the lease; positions remain under automated lifecycle. |
| Legacy `close_all_positions()` active emergency caller | **DE-AUTHORIZE, PRESERVE CODE** | Route automated emergency lifecycle through PositionUnwindManager and OMS. Do not delete dormant compatibility code without Board approval. |
| GammaFront entry feed | **PRESERVED-DORMANT** | No lawful dark-pool/options entry feed exists for this crypto runtime. Exit-only/local diagnostics remain honest. |
| AdaptiveDC runtime silence | **WIRE** | Native module and vote adapter exist; feed it causal per-symbol market ticks through the existing strategy path. |
| SovereignExecutionGuard | **RETAIN DORMANT** | Do not activate it in this program. |
| Manual buy/sell/force/cancel-all UI | **RETAIN FORBIDDEN** | Bot lifecycle only; UI remains observation and run control. |

## 6. Initial Draft Plan Before Red-Team

The first architecture draft was:

1. replace the static six-symbol list with Alpaca's crypto catalog;
2. move market data to Alpaca snapshots/WebSocket;
3. add durable lot tracking and manage the accepted baseline holdings;
4. enable Alpaca sell-to-close and supported order types;
5. wire missing module feeds;
6. upgrade opportunity ranking, covariance risk, sizing, and NetEdge;
7. move emergency exits to PositionUnwindManager;
8. expose all decisions/module contributions in the cockpit;
9. improve supervised recovery inside a finite authorization boundary;
10. run offline proof, then progressively longer natural PAPER trials.

That ordering was **rejected by the red team** because it widened the universe
before repairing cross-symbol/future-data contamination and because it enabled
SELL before the inventory and order-reservation authority was proven.

## 7. Independent Third-Party Red-Team

Role assumed: adversarial quant engineer, broker-integration auditor, and
incident responder with authority to reject the plan.

### Finding RT-1: Wider universe magnifies false signals

One global SignalFusion cache and one global WhaleFlow callback already mix
symbols. Adding 56 pairs could make the most recently updated symbol dominate
another symbol's decision. This is a go-live blocker.

**Required correction:** causal/symbol isolation becomes Stage 1, before catalog
activation.

### Finding RT-2: The completed run contains look-ahead evidence

Negative ages are accepted as fresh. A broader system trained or evaluated on
those frames could learn from future information and look better than it is.

**Required correction:** reject future timestamps, implement as-of joins, and
re-run replay parity before any alpha or universe conclusion.

### Finding RT-3: Catalog membership is not execution eligibility

An active Alpaca asset can still be unfundable by quote currency, unsupported
by the account/jurisdiction, missing market data, too young, too wide, too thin,
or below viable NetEdge after precision and cost.

**Required correction:** catalog discovery feeds a reason-coded eligibility
pipeline; it never directly feeds execution.

### Finding RT-4: Cross-venue prices can create fictitious edge

Coinbase/Kraken quotes can differ from Alpaca's executable market. Using the
wrong venue's spread/depth in NetEdge and limit-price construction can create
fake economics.

**Required correction:** Alpaca/location-matched data owns executable market
truth for Alpaca orders. Cross-venue data is advisory only and basis divergence
is a veto/warning input.

### Finding RT-5: The data plane will self-denial-of-service

The current 2N REST request cycle already suffered latency with six symbols.
Catalog expansion without batching, concurrency limits, backpressure, and deep
tier caps would cause stale data and false SAFE_MODE.

**Required correction:** observe-only breadth/deep architecture is proven under
load before any dynamic symbol reaches dispatch.

### Finding RT-6: Portfolio risk can be falsely green

ExposureManager is active but does not own the complete broker inventory after
cold start. A candidate can carry `ExposureManager authorized` while the
in-memory book is incomplete.

**Required correction:** hydrate and reconcile the complete broker book into
the existing owner before candidate admission; missing attribution fails closed.

### Finding RT-7: Managing inherited positions can become manual liquidation

Simply changing the baseline policy to `ADOPT_AND_MANAGE_EXISTING_POSITIONS`
would allow code paths that have not proven lot, lifecycle, or strategy
provenance to sell Shan's holdings.

**Required correction:** governed acceptance records an `ADOPTED_BASELINE` lot
class. Only automated moving-floor, stop-loss, time-barrier, or risk-unwind
policies may produce sell-to-close, never a UI selection or generic bearish
vote.

### Finding RT-8: SELL intent is too easy to misclassify

Matching positive position metadata is not enough to convert a generic SELL
into a legal exit. It could turn a short alpha opinion into a liquidation.

**Required correction:** require explicit lifecycle reason, owning policy,
position/lot IDs, broker snapshot ID, reduce-only flag, quantity cap, and
decision UUID end to end.

### Finding RT-9: Partial fills and duplicate events can oversell

REST reconciliation plus streaming events can arrive duplicated, out of order,
or after restart. Two exit policies can also reserve the same position.

**Required correction:** one durable per-symbol sell reservation, idempotent
event keys, cumulative-fill monotonicity, and a fresh final broker-position read
immediately before SELL POST.

### Finding RT-10: Strategy-local state invents positions and PnL

Signal emission is not a fill. Local latches can suppress future entries,
generate invalid exits, or report PnL for trades the broker never accepted.

**Required correction:** strategies emit intents and diagnostics; OMS/fill
reconciliation changes executable position state and realized PnL.

### Finding RT-11: Market orders can turn a safety fix into uncontrolled loss

Alpaca supports market orders, but enabling them for all entries/exits would
remove price bounds and make paper results mostly execution noise in thin pairs.

**Required correction:** lifecycle-specific order policy with staged
aggression, quantity tranches, current depth/impact evidence, and market orders
only as a final automated emergency-unwind action when the risk owner explicitly
prefers exit certainty over price certainty.

### Finding RT-12: Existing emergency code is both broad and unreliable

The active fire-and-forget close-all path clears local pending state, launches
asynchronous cancels, and then queries the wrong paper position surface for an
external Alpaca PAPER gateway.

**Required correction:** de-authorize its active callbacks and wire the existing
PositionUnwindManager through DecisionRecord, OMS, gateway, feedback, and
reconciliation.

### Finding RT-13: "All modules must fire" would create fake integration

GammaFront legitimately lacks a crypto dark-pool/options entry feed. Trade
Efficiency legitimately lacks enough broker-confirmed round trips. Forcing an
output would fabricate evidence.

**Required correction:** every module must report one of CONTRIBUTED,
DECLINED, NOT_APPLICABLE, MISSING_FEED_TRUTH, or PRESERVED_DORMANT with source
evidence. It need not emit a trade.

### Finding RT-14: Exploration already weakened selectivity

The current launcher lowers Shans readiness, fusion confidence, SectorRotation
inflow/confidence/history, ShadowFront whale/sentiment/confidence, opportunity
score, and optional-module quorum.

**Required correction:** do not loosen any threshold. Standard PAPER capability
uses the existing default profile; exploration remains a named research mode.

### Finding RT-15: Larger universe increases multiple-testing and correlation risk

Scanning more assets increases the chance of selecting noise and clustering
into highly correlated crypto exposures even if each individual signal passes.

**Required correction:** use causal out-of-sample calibration, false-discovery/
selection diagnostics, shrinkage covariance, marginal expected shortfall,
liquidity capacity, and portfolio-level exposure authority. Do not use a naive
weighted score.

### Finding RT-16: Continuous recovery can bypass explicit arming

An auto-restarting service could silently re-arm after its authorization
expires, overlap a predecessor, or restart after a reconciliation conflict.

**Required correction:** recovery is allowed only inside the same signed
campaign envelope, account pin, baseline/inventory snapshot lineage, code/config
fingerprints, and unexpired horizon. Each worker generation needs a fencing
token and reconciliation. A new campaign always requires the operator and Board
approval required by current governance.

### Finding RT-17: Logging volume can become an operational outage

The four-hour run produced 106.5 MB, dominated by repeated diagnostics. A
multi-day, wider-universe run would create excessive disk and parsing pressure.

**Required correction:** persist every decision/state transition, but coalesce
repeated unchanged observations, rate-limit debug diagnostics, rotate files,
and retain structured lossless records for candidates, orders, fills, errors,
and safety events.

### Finding RT-18: A narrow broker-read expansion can become broad permission

Adding `/v2/assets` to the adapter without a read-family gate would silently
expand production network behavior.

**Required correction:** add an exact catalog read family/profile and keep it
environment/Board gated. Mocked catalog tests precede any real GET.

### Finding RT-19: A week or month encoded as one lease preserves stale authority

A single long-lived lock cannot prove that the original process, account,
configuration, broker snapshot, or safety state remains the lawful mutation
owner for the entire campaign. A dead process can also leave a stale lock while
a blind restart creates an overlapping trader.

**Required correction:** separate the immutable, finite campaign authorization
from a shorter renewable worker lease. Fence every owner generation, renew only
from current health and reconciliation truth, and prohibit renewal past the
campaign horizon.

### Finding RT-20: "Run until crash" is an unbounded mutation authorization

Crash is neither a deterministic completion condition nor an adequate resilience
test. A bot could run indefinitely while accumulating hidden evidence loss, or
crash once without exercising the failure modes that matter.

**Required correction:** use a governed endurance campaign with a Board-set
maximum horizon, defined steady state, controlled fault schedule, hard stop
conditions, recovery budget, and final broker reconciliation. Run fault injection
offline first; any external PAPER fault campaign requires its own approval.

### Finding RT-21: Longer PAPER PnL can create false live confidence

Alpaca PAPER does not model market impact, information leakage, latency slippage,
queue position, price improvement, or all real fees. A stable or profitable
30-day simulation can therefore overstate live execution quality and capacity.

**Required correction:** label PAPER results as simulated execution evidence,
carry unmodelled live effects as explicit uncertainty, and keep every tiny-money
Checkpoint I action separately approved and capped.

### Finding RT-22: Adding a tenant ID later can cross accounts and secrets

Authentication does not isolate tenant credentials, state, campaign leases,
orders, risk, reconciliation, logs, or AI evidence. A shared singleton or missing
scope could route one tester's decision to another tester's account.

**Required correction:** defer activation as directed, avoid unnecessary
single-tenant literals now, and require an explicit isolation architecture,
threat model, per-tenant/account mutation owner, namespace/secret policy, and
cross-tenant negative tests before a second tester is admitted.

### Finding RT-23: "Do not hardcode" can accidentally make safety chat-mutable

Externalizing every invariant would allow configuration drift or an operator
input to weaken PAPER/live separation, naked-SELL prevention, numeric fail-closed
behavior, or one-owner enforcement.

**Required correction:** operational choices belong in typed, versioned,
validated configuration owned by the correct existing module. Sacred invariants
stay hard enforcement and are never AI/chat mutable.

### Red-team verdict

**INITIAL DRAFT: REJECTED.** It sequenced breadth and sell capability before
causal, inventory, and lifecycle truth. The adjusted plan below corrects that
ordering and adds explicit rollback/stop conditions.

## 8. Adjustments Made After Red-Team

1. Causal and per-symbol isolation moved to the first behavior stage.
2. Broker inventory/lot/reconciliation authority moved before any SELL support.
3. Dynamic catalog work is mock-first and observe-only until a separate broker
   GET authorization and all downstream gates pass.
4. Alpaca execution-venue data becomes canonical for Alpaca executable price;
   cross-venue feeds become advisory.
5. Every held/open-order symbol is pinned in the deep data tier regardless of
   opportunity rank.
6. SELL now requires explicit lifecycle provenance and a final broker position/
   reservation gate, not merely a matching symbol.
7. Strategy state becomes fill-driven; signal-driven PnL is diagnostic only.
8. PositionUnwindManager replaces the active emergency close-all caller without
   deleting preserved legacy code.
9. The standard threshold profile becomes the target; no value is lowered.
10. Placeholder opportunity/risk math is upgraded before broad candidate
    activation.
11. Module truth becomes source-emitted; dormant/missing is acceptable and
    visible.
12. Supervisor recovery remains inside an approved finite campaign envelope and
    cannot self-arm a new campaign or extend its horizon.
13. Offline, mocked, replay, and soak gates precede all broker-read and PAPER
    proof.
14. Actual broker reads and every PAPER run remain separate approval events.
15. The commissioning mini-run ladder is replaced by 8-hour, 7-day, and 30-day
    full-capability autonomous campaigns after Stages 0-12 pass.
16. A finite immutable campaign envelope is separated from a shorter renewable
    fenced worker lease; recovery cannot extend or create approval.
17. The literal unbounded "until crash" trial is replaced by governed endurance
    and controlled-failure certification with declared stop conditions.
18. PAPER execution limitations remain explicit and block automatic promotion to
    live money.
19. Multi-tenant activation is deferred; current owners must avoid unnecessary
    single-tenant hardcoding without creating a speculative parallel subsystem.

## 9. Adjusted Final Stage-by-Stage Plan

### Binding entry gate for every stage

Board rulings dated 2026-07-18: `AGENTS.md` Sections 23 and 24 are binding at the
start and close of every Stage 0-13. Before any source, test, configuration, or
runtime edit, the stage report must contain the complete Section 23.3 manifest and
`STAGE_ENTRY_COVENANT: PASS`. A missing manifest, unresolved `UNKNOWN`, failed
fingerprint, degradation, deletion, simplification, weakened control, fake
proof, or unapproved money-adjacent action stops and voids the stage. This
ruling does not itself approve implementation, a broker call, or a PAPER run.

### Stage 0 - Freeze the proof baseline and define activation invariants

**Mandatory stage entry:** execute and record `AGENTS.md` Sections 23 and 24 before any
stage edit. No `STAGE_ENTRY_COVENANT: PASS`, no work.

**Purpose:** prevent a large program from rewriting history or losing the
current safety baseline.

**Work:**

- Record the current full-suite historical baseline as **not rerun this turn**:
  `1820 passed, 14 skipped, 0 failed` from the latest handoff/report.
- Add a deterministic offline parser fixture from the four-hour run containing
  representative candidate, causal-age, baseline, stale-guard, no-trade,
  shutdown, and reconciliation records. Do not copy secrets or runtime state.
- Pin invariants in tests:
  - PAPER endpoint only;
  - account suffix assertion before order one;
  - no live/real money;
  - no naked/short SELL;
  - no manual trade controls;
  - MarketTruthSnapshot, Risk, NetEdge, sizing, TTL, OMS, and reconciliation
    remain hard;
  - Stop emits no broker mutation;
  - SovereignExecutionGuard remains dormant;
  - no default threshold value changes.
- Define one activation matrix with states `IMPLEMENTED_OFFLINE`,
  `OBSERVE_ONLY`, `MOCKED_EXECUTION_PROVEN`, `BROKER_READ_PROVEN`, and
  `BOUNDED_PAPER_PROVEN`. None is called PAPER-ready merely because code exists.

**Likely owners/files:** existing tests, completion report, tracker/handoff only.

**Binary exit:** current behavior is reproducible from fixtures; every sacred
invariant has a negative test; no runtime behavior changes.

**Stop condition:** any fixture requires editing a guard/threshold or using a
real broker response as a fake local pass.

### Stage 1 - Repair causal time and per-symbol state

**Mandatory stage entry:** execute and record `AGENTS.md` Sections 23 and 24 before any
stage edit. No `STAGE_ENTRY_COVENANT: PASS`, no work.

**Purpose:** ensure every decision uses only that symbol's evidence available at
or before the decision timestamp.

**Work:**

- Move fusion caches, hysteresis, last fusion, and module evidence into existing
  per-symbol runtime ownership, or make the existing SignalFusion cache
  explicitly symbol-indexed. Keep SignalFusion as the single fusion authority.
- Remove the global WhaleFlow write in `SovereignHeartbeat._on_trade`; route
  trades once into the correct `SymbolRuntime`.
- Reject `input_ts_ns > decision_ts_ns` with a named causal-integrity reason.
  Negative age can never receive `NATIVE_SIGNAL_FRESH` or a temporal discount of
  1.0.
- Use as-of joins: for each module, select the latest same-symbol observation
  whose timestamp is `<= decision_ts_ns` and whose TTL is still valid.
- Make Shans, regime, physical, toxicity, entropy, insider, whale, and external
  evidence carry symbol/source/event timestamps.
- Keep a persistent `StaleDataGuard` per symbol in SymbolRuntime. Feed it actual
  transport/event observations. Do not recreate it at pre-trade evaluation.
- Separate candle freshness from transport drift: MarketTruthSnapshot remains
  executable freshness authority; StaleDataGuard contributes drift/jitter/
  kinematic risk using the correct receive and exchange clocks.
- Remove primary-symbol TPE as the implicit risk input for every symbol. A
  candidate uses its own topology; portfolio risk aggregation remains with the
  risk owner.

**Likely owners/files:** `main.py`, `app/main_loop.py`,
`app/brain/signal_fusion.py`, `app/risk/stale_data_guard.py`,
`app/risk/pre_trade_guardrails.py`, `app/symbol_runtime.py` or the existing
SymbolRuntime definition, focused tests.

**Required tests:**

- same module updates for BTC and ETH cannot cross-contaminate;
- out-of-order cross-symbol events preserve deterministic results;
- future Shans/regime/whale/physical/toxicity/entropy/insider evidence is
  refused;
- same-time and lawful prior-time evidence remains usable;
- persistent stale guard warms, retains kinematics, and replay matches runtime;
- valid one-minute closed candles are not failed by a 500 ms transport-drift
  category error;
- genuinely stale, future, backward, or broken-clock data remains blocked;
- replay A/B byte-equivalent decision reason codes.

**Binary exit:** zero negative-age `FRESH` records; zero cross-symbol cache
effects; existing stale/TTL thresholds unchanged; run-path and replay suites
green offline.

**Stop condition:** the fix requires weakening a TTL/drift threshold instead of
correcting clock semantics.

### Stage 2 - Consolidate broker inventory, lots, fills, and reservations

**Mandatory stage entry:** execute and record `AGENTS.md` Sections 23 and 24 before any
stage edit. No `STAGE_ENTRY_COVENANT: PASS`, no work.

**Purpose:** give Risk and OMS complete, durable ownership truth before allowing
same-symbol activity or SELL.

**Work:**

- Use `StateStore`, broker fill ledger, order ID mappings, reservation ledger,
  `ReservationLifecycleCoordinator`, `ExposureManager`, and reconciliation as
  the existing authority chain. Do not add a second portfolio database.
- On cold start, reconcile broker account, positions, open orders, and known
  fills before new entries can be admitted.
- Represent inventory provenance explicitly:
  - `ADOPTED_BASELINE` - quantity accepted at startup, broker-backed;
  - `BOT_ACQUIRED` - quantity from reconciled broker fill IDs;
  - `PENDING_BUY` and `PENDING_SELL` - OMS reservations;
  - `SOLD` - cumulative reconciled sell fills;
  - `UNKNOWN_ATTRIBUTION` - broker quantity that cannot be assigned, which
    blocks new same-symbol mutation until reconciled.
- Track quantity with Decimal using broker min trade increment. Never float-
  round executable inventory.
- Reconcile partial fills cumulatively and idempotently; handle duplicate,
  late, corrected, rejected, expired, canceled, and replaced events.
- Make ExposureManager ingest the complete broker book and expose it directly
  to every candidate. Candidate metadata may carry immutable snapshot IDs, but
  must not become a second risk book.
- Make accepted baseline truth advance after broker-confirmed fills so each
  lawful bot trade does not create a false baseline-drift lock. Preserve the
  original opening snapshot and a reconciliation lineage.
- Same-symbol BUY becomes possible only after current broker quantity,
  attributed lots, and open reservations reconcile. SELL remains disabled at
  the adapter until Stage 8.

**Likely owners/files:** `app/state/state_store.py`,
`app/risk/exposure_manager.py`,
`app/risk/reservation_lifecycle_coordinator.py`,
`app/execution/order_router.py`, reconciliation/truth kernel,
`app/operator_activation/paper_baseline.py`, `main.py`, focused tests.

**Required tests:**

- cold boot with the four current holdings produces exact adopted inventory;
- accepted baseline remains opening truth without perpetually blocking managed
  quantity;
- no broker position, unknown attribution, stale snapshot, or mismatch fails
  closed;
- duplicate/late/partial fill events never double inventory or PnL;
- concurrent BUY/SELL reservations cannot exceed cash or owned quantity;
- restart between acknowledgement and partial/final fill recovers exactly;
- baseline account mismatch still blocks;
- no broker mutation in tests.

**Binary exit:** ExposureManager total inventory equals broker snapshot for every
symbol; reservation plus available quantity identities balance; same-symbol
activity is no longer blocked solely because a symbol existed at startup, but
unknown/mismatched quantity still blocks.

**Stop condition:** the design creates another lot/position authority outside
StateStore + ExposureManager + OMS + Reconciliation.

### Stage 3 - Build broker-canonical crypto catalog and instrument capabilities

**Mandatory stage entry:** execute and record `AGENTS.md` Sections 23 and 24 before any
stage edit. No `STAGE_ENTRY_COVENANT: PASS`, no work.

**Purpose:** replace operator nomination with broker truth while retaining
fail-closed execution eligibility.

**Work:**

- Add an exact read-only `GET /v2/assets?status=active&asset_class=crypto` method
  to `AlpacaPaperBrokerAdapter` behind a new narrow `READ_ASSET_CATALOG` family.
- Mock the endpoint first. A real GET is Stage 12 and requires separate Board
  authorization.
- Normalize each broker asset into the existing capability/instrument model:
  symbol/asset ID, status, tradable, fractionable, marginable, shortable,
  min order size, min trade increment, price increment, exchange/venue, asset
  class, and observed timestamp/source.
- Use the broker asset record as execution capability truth. Static entries may
  be test fixtures or display fallbacks, never execution authorization.
- Correct current registry contradictions: Alpaca crypto cannot be labeled
  Kraken execution or margin-available; Decimal precision replaces float
  executable metadata.
- Intersect catalog with account/jurisdiction permission, execution adapter,
  quote-currency funding, and market-data coverage.
- Cache the catalog durably with source timestamp/hash for restart support, but
  stale/unavailable catalog cannot green-light a new symbol. Held/open-order
  symbols remain monitored while new entry is blocked.
- Record an immutable universe snapshot ID and a reason for every inclusion and
  exclusion.

**Likely owners/files:** `app/execution/alpaca_paper_adapter.py`,
`app/execution/broker_read_policy.py`, `app/market/capability_registry.py`,
`app/market/venue_capabilities.py`, `app/instrument_registry.py`, runtime
configuration/supervisor read contract, tests.

**Required tests:**

- catalog GET is impossible under strict/default read profile;
- exact authorized profile permits only GET and never POST/PATCH/DELETE;
- active/tradable/precision facts normalize deterministically;
- inactive/nontradable/missing-precision/margin/short claims fail closed;
- static six cannot silently authorize a catalog failure;
- symbol aliases and slash encoding do not duplicate one asset;
- account suffix, endpoint, and secret-redaction laws remain.

**Binary exit:** mocked complete catalog produces a reason-coded eligible set
with exact Decimal constraints and zero static-list execution authority.

**Stop condition:** actual broker access occurs without the separate Stage 12
authorization or catalog state becomes a second broker authority.

### Stage 4 - Replace poll-all with a scalable market-data and universe pipeline

**Mandatory stage entry:** execute and record `AGENTS.md` Sections 23 and 24 before any
stage edit. No `STAGE_ENTRY_COVENANT: PASS`, no work.

**Purpose:** scan the full eligible catalog without overwhelming the runtime or
using the wrong venue as executable truth.

**Work:**

- Keep `FeedProviderRouter` as provider-selection owner and make its selected
  fallback actually start/switch transport. If transport cannot switch,
  executable truth fails closed rather than merely logging a fallback.
- Use Alpaca execution-location market data as canonical for Alpaca executable
  quotes/books/bars. Coinbase/Kraken remain cross-venue advisory features with
  explicit source/basis age.
- Introduce two tiers inside existing feed/universe ownership:
  - breadth tier: batched snapshots/quotes/bars across eligible symbols at a
    bounded refresh cadence;
  - deep tier: streaming trades, quotes, books, and bars for current holdings,
    open orders, lifecycle exits, and a bounded candidate set.
- Enforce global and per-provider request budgets, semaphore concurrency,
  exponential backoff with jitter, `429` handling, circuit state, queue
  backpressure, and observability. These are transport controls, not trading
  thresholds.
- Rank breadth eligibility with robust, time-aligned evidence:
  - data completeness and clock quality;
  - robust/winsorized log dollar volume and trade count;
  - median/MAD spread and depth/market-impact estimates;
  - volatility regime and jump/gap diagnostics;
  - listing age and continuity;
  - quote-currency fundability;
  - cross-venue basis divergence;
  - capacity under broker increments/minimums.
- Use percentile/Pareto dominance and uncertainty-aware ranking rather than a
  fixed one-line weighted average. NetEdge and Risk remain downstream hard
  owners.
- Apply membership hysteresis and minimum residence so symbols do not churn on
  transient ranks. No threshold changes are made in this stage.
- Holdings and open orders are never evicted from deep monitoring.
- Keep the dynamic set observe-only until Stages 5-11 pass.

**Likely owners/files:** `app/data/feed_provider_router.py`,
`app/data/polling_client.py`, Alpaca market-data provider surfaces,
`app/data/market_feeds.py`, `main.py`, existing opportunity/capability models,
tests.

**Required tests:**

- request count scales by batches, not two calls per symbol per second;
- hard concurrency/rate budgets under 1, 6, 56, and synthetic larger catalogs;
- `429`, timeout, DNS, disconnect, slow consumer, and malformed payload paths;
- no stale provider can remain executable after fallback;
- execution-venue quote is required for limit price/NetEdge;
- cross-venue data cannot own MarketTruthSnapshot;
- held/open-order symbols remain subscribed through universe churn;
- deterministic universe snapshot/replay with no look-ahead or survivorship
  leakage.

**Binary exit:** a synthetic full catalog runs for an offline soak with bounded
memory, requests, queues, and log volume; all dynamic symbols remain observe-only.

**Stop condition:** the only way to keep up is relaxing freshness/TTL, dropping
held-symbol monitoring, or treating cross-venue prices as executable.

### Stage 5 - Make strategies fill-driven and wire honest module inputs

**Mandatory stage entry:** execute and record `AGENTS.md` Sections 23 and 24 before any
stage edit. No `STAGE_ENTRY_COVENANT: PASS`, no work.

**Purpose:** let every valuable module contribute lawfully without inventing
positions, PnL, or missing feeds.

**Work:**

- Convert strategy entry/exit state transitions into explicit intents pending
  OMS truth. Strategy signal emission does not set broker position state.
- Feed broker acknowledgement/fill/partial/terminal events back to the owning
  strategy through existing lifecycle/DecisionRecord identifiers.
- Realized PnL, wins/losses, fees, and TCA come only from reconciled broker
  fills. Local path estimates remain clearly diagnostic.
- SectorRotation retains its inflow/regime logic but its fixed simulated-capital
  quantity becomes non-authoritative risk appetite. PositionSizingEngine owns
  quantity.
- ShadowFront gets same-symbol per-trade WhaleFlow and sentiment evidence. Do
  not relax whale/sentiment/confidence thresholds.
- LiquidityVoid retains order-book-native logic. Add reason-level diagnostics
  for each internal decline and prove its buffered observation is consumed only
  when causal, same-symbol, fresh, and unconsumed. Do not assume the completed
  run's missing pair was a bug until those diagnostics identify the gate.
- Wire AdaptiveDC from real, same-symbol, time-ordered market ticks through its
  existing vote adapter and StrategyRouter. Keep its authority contributory.
- GammaFront remains `WIRED_EXIT_ONLY / ENTRY_FEED_DORMANT`; do not synthesize
  dark-pool or options truth for crypto.
- MovingFloor continues to monitor every broker-owned long position, but its
  eventual SELL route remains gated until Stages 6 and 8.
- TradeEfficiency contributes only after sufficient broker-confirmed round
  trips; before that it reports insufficient evidence, not a neutral fake pass.
- Attach current InvariantChecker and broker reconciliation snapshot IDs at the
  candidate decision time.
- StrategyRouter continues to rank; it never becomes Risk/OMS authority.

**Likely owners/files:** per-symbol runtime/MainLoop, existing strategy files,
strategy vote adapters, candidate lifecycle/DecisionFrame, OMS fill feedback,
TradeEfficiency/Invariant/Reconciliation owners, tests.

**Required tests:**

- emitted BUY without broker ack/fill leaves strategy flat;
- rejected/canceled/expired BUY clears pending intent without fake loss;
- partial/final fill creates exact owned quantity and starts lifecycle clock at
  broker fill time;
- emitted SELL does not clear position or book PnL until reconciled fill;
- restart rehydrates owning strategy from broker/lot truth;
- each module reports exact CONTRIBUTED/DECLINED/MISSING/DORMANT reason;
- AdaptiveDC native path is reached from real modeled market events;
- GammaFront entry cannot be reached without its lawful feed;
- no strategy can route directly to broker.

**Binary exit:** strategy state, inventory, DecisionRecord, and broker fill
ledger agree across ack, partial fill, fill, cancel, reject, expiry, and restart.

**Stop condition:** a module must fake a feed or retain independent position/PnL
authority to appear active.

### Stage 6 - Implement governed automated position lifecycle for held positions

**Mandatory stage entry:** execute and record `AGENTS.md` Sections 23 and 24 before any
stage edit. No `STAGE_ENTRY_COVENANT: PASS`, no work.

**Purpose:** allow the bot to sell owned PAPER holdings when an explicit
automated lifecycle policy says it makes sense, without creating manual trade
control.

**Work:**

- Define one end-to-end sell-to-close intent contract containing:
  lifecycle reason, policy owner, symbol, adopted/acquired lot IDs, current
  broker position snapshot ID/age, owned quantity, reserved quantity, requested
  quantity, reduce-only flag, DecisionRecord UUID, MarketTruthSnapshot ID,
  valid-until, NetEdge/exit-economics treatment, and reconciliation lineage.
- Permit only these automated sources under current Sacred Safety Laws:
  - stop-loss;
  - MovingFloor protective exit;
  - time barrier/TTL;
  - emergency PositionUnwind campaign.
- A generic bearish alpha vote remains `BEARISH_NO_LONG` unless it is an exit
  signal from the policy that owns a broker-confirmed lot. Matching position
  metadata alone is insufficient.
- Adopted baseline holdings may be enrolled in governed management only through
  the existing governed baseline-acceptance flow and a displayed policy version.
  The operator cannot select a symbol and press Sell.
- Use per-position lifecycle state. MovingFloor remains profit-protection;
  stop-loss remains loss defense; time barrier remains duration defense;
  PositionUnwind remains portfolio emergency defense. Do not collapse them into
  one generic exit rule.
- Wire `PositionUnwindManager` as the existing campaign planner. Its
  recommendations flow through DecisionCompiler, Risk, NetEdge exit treatment,
  OMS, and broker boundary. It never calls broker directly.
- Replace active callbacks to `_emergency_liquidate_all`/`close_all_positions`
  with the governed campaign path. Preserve legacy code dormant until separate
  deletion approval.
- Keep governed Stop exactly non-mutating. Stopping the process does not issue
  sells/cancels; active broker positions remain under lifecycle only while the
  run is active. The UI must state when no active process is managing them.

**Likely owners/files:** `app/main_loop.py`, strategy lifecycle owners,
`app/risk/position_unwind.py`, `app/risk/guard.py`,
`app/execution/engine.py`, `app/execution/order_router.py`, baseline policy,
DecisionFrame/compiler, tests.

**Required tests:**

- each of the four adopted holdings can generate an automated lifecycle intent
  under modeled trigger evidence;
- no trigger means no SELL;
- generic bearish signal cannot liquidate an adopted or bot-acquired holding;
- explicit lifecycle cannot sell more than available broker quantity minus
  active sell reservations;
- concurrent MovingFloor/stop/time/emergency intents deduplicate to one owner;
- stale position/market/reconciliation truth blocks;
- PositionUnwind partial fill/retry/escalation/dust/restart behavior;
- Stop mid-run still emits zero POST/PATCH/DELETE/cancel/sell and releases lease;
- no UI/manual caller can construct the lifecycle contract.

**Binary exit:** modeled stop-loss, MovingFloor, time-barrier, and emergency
intent each traverse the full mocked decision/OMS boundary; manual/generic/
oversell paths are refused.

**Stop condition:** an implementation introduces a close-all shortcut, manual
sell, naked SELL, or bypasses DecisionFrame/Risk/NetEdge/OMS.

### Stage 7 - Upgrade portfolio, sizing, opportunity, and execution economics

**Mandatory stage entry:** execute and record `AGENTS.md` Sections 23 and 24 before any
stage edit. No `STAGE_ENTRY_COVENANT: PASS`, no work.

**Purpose:** make a larger universe quant-grade rather than simply more active.

**Work:**

- Preserve NetEdge as a hard economic gate and replace point placeholders with
  source-bound components:
  - broker maker/taker fee schedule and fee uncertainty;
  - half/full spread by intended order type;
  - order-book sweep/participation impact;
  - fill-probability and partial-fill burden;
  - latency/adverse-selection cost;
  - cross-venue basis risk;
  - entry plus expected exit execution burden;
  - model uncertainty and a lower confidence bound.
- A candidate must pass on conservative/lower-bound net edge, not average gross
  return. Missing critical cost truth blocks.
- Upgrade CrossAssetRiskCalculator using existing installed numerical libraries:
  time-aligned log returns, OAS/Ledoit-Wolf shrinkage covariance, eigenvalue/
  condition diagnostics, exponentially weighted regime adaptation, and
  block-bootstrap/historical stress expected shortfall. It remains a risk
  contributor; ExposureManager owns admission.
- Replace illustrative static stress factors with calibrated scenario records
  where history exists. Missing history remains explicitly uncalibrated and
  cannot be shown as authoritative.
- Add marginal contribution to expected shortfall, cluster concentration,
  liquidity-adjusted exposure, and jump/correlation-break stress to the existing
  ExposureManager evidence.
- Upgrade PositionSizingEngine so executable quantity is the minimum of
  independently evidenced caps:
  risk capital at stop/ATR distance, marginal expected-shortfall budget,
  portfolio utilization, symbol/sleeve concentration, liquidity participation,
  broker min/increment, cash reserve, correlation cluster, uncertainty, and
  capped Kelly overlay where sufficient history exists.
- Kelly never overrides hard caps and never uses provisional/fake PnL.
- Replace OpportunityRanker's placeholder fee/impact and fixed 40/35/25 score
  with a passive Pareto/lexicographic rank based on positive lower-bound NetEdge,
  data quality, marginal portfolio risk, liquidity capacity, and calibrated
  confidence. Risk/NetEdge remain veto owners.
- Measure multiple-testing/selection pressure as universe breadth grows. Track
  false-discovery and out-of-sample degradation diagnostics without changing a
  strategy threshold to make trades happen.
- Use Decimal at broker/risk/order boundaries; use vectorized floats only
  inside statistically appropriate numerical estimation with explicit
  conversion and reproducibility.

**Likely owners/files:** `app/risk/net_edge_governor.py`,
`app/risk/cross_asset_risk_model.py`, `app/risk/exposure_manager.py`,
`app/risk/position_sizing.py`, `app/portfolio/opportunity_ranking.py`, fee/
slippage/latency models, TradeEfficiency/TCA, tests.

**Required tests:**

- no look-ahead in return/covariance samples;
- shrinkage covariance is positive semidefinite and stable under collinearity/
  short history;
- stress/expected-shortfall results are deterministic under fixed replay seed;
- higher uncertainty, spread, impact, correlation, or latency never increases
  executable size/edge;
- all missing-cost paths fail closed;
- broker increments/minimums are exact Decimal;
- no default threshold constant changes (source snapshot test);
- robust behavior under heavy tails, jumps, illiquidity, zero volume, crossed
  books, singular covariance, and correlated portfolio clusters.

**Binary exit:** no placeholder cost or illustrative risk result can authorize
an order; every quantity and economic allow has a traceable source/model version
and conservative scenario proof.

**Stop condition:** any improvement is achieved by lowering a threshold, using
future data, or making an uncalibrated model authoritative.

### Stage 8 - Complete the Alpaca PAPER order and sell-to-close contract

**Mandatory stage entry:** execute and record `AGENTS.md` Sections 23 and 24 before any
stage edit. No `STAGE_ENTRY_COVENANT: PASS`, no work.

**Purpose:** make the external adapter agree with capabilities and prove the
full order lifecycle offline before any broker mutation.

**Work:**

- Extend `AlpacaPaperBrokerAdapter._payload_for_order` to accept:
  - BUY only when all existing entry gates pass;
  - SELL only when `sell_to_close` lifecycle provenance passes;
  - broker-supported crypto `limit`, `stop_limit`, and narrowly governed
    `market` forms;
  - broker-supported `GTC` and `IOC` only.
- Make CapabilityRegistry and adapter share the same tested contract so a
  capability can never advertise an action the adapter rejects.
- Add a final pre-POST SELL gate in OrderRouter:
  account pin/status, paper endpoint, current asset tradable status, fresh
  broker position, exact available quantity, active open SELL orders,
  reservations, no oversell/reversal, current MarketTruthSnapshot, precision,
  min size/notional treatment, valid lifecycle UUID, idempotency, and TTL.
- Carry full lifecycle provenance through `_gateway_request_from_order`; do not
  strip it at the final boundary.
- Lifecycle-specific order policy:
  - entry: passive or bounded marketable limit when NetEdge remains positive;
  - normal profit/time exit: limit or IOC marketable limit with depth/impact
    bounds;
  - stop/emergency: tranche and escalate via PositionUnwind policy; market is a
    last automated emergency action only when the risk owner explicitly records
    why non-fill risk exceeds bounded price risk.
- Add Alpaca `trade_updates` consumption to the existing OMS lifecycle with
  reconnect/replay/dedupe and periodic REST reconciliation. Streaming is speed;
  broker REST state remains reconciliation truth.
- Handle every documented status: accepted/new/pending/partial/fill/canceled/
  expired/rejected/replaced and uncommon terminal/conflict cases.
- Persist request IDs, client/broker order IDs, execution/fill IDs, cumulative
  quantity, price, fee truth status, and source timestamps without secrets.

**Likely owners/files:** adapter, gateway request model, CapabilityRegistry,
OrderRouter, ExecutionEngine, OMS mapping/fill recorder/StateStore, tests.

**Required positive chain:**

`strategy/lifecycle intent -> DecisionFrame -> DecisionCompiler ->
ExecutionEngine -> OrderRouter -> mocked Alpaca POST -> broker ack -> partial
fill -> final fill -> broker position -> ExposureManager -> strategy lifecycle ->
fee/TCA record`

Prove this separately for BUY and broker-position-backed sell-to-close.

**Required negative tests:** wrong suffix, live endpoint, unowned symbol, generic
SELL, stale position, oversell, duplicate client ID, open SELL reservation,
invalid asset, missing precision, invalid TIF/order type, stale market truth,
negative NetEdge, risk refusal, partial-fill race, stream duplicate/out-of-order,
REST conflict, and expired lease.

**Binary exit:** mocked BUY and sell-to-close both reach reconciled fill truth;
every unsafe SELL fails before POST; adapter/capability contract parity passes.

**Stop condition:** a SELL can reach POST without an immediately current broker
position and durable reservation, or a mocked fill is represented as broker
proof.

### Stage 9 - Activate standard-profile dynamic PAPER dispatch behind one gate

**Mandatory stage entry:** execute and record `AGENTS.md` Sections 23 and 24 before any
stage edit. No `STAGE_ENTRY_COVENANT: PASS`, no work.

**Purpose:** remove commissioning-only runtime restrictions only after their
replacements are proven.

**Work:**

- Replace supervisor static-watchlist authority with a `BROKER_DYNAMIC_CRYPTO`
  runtime mode that references the immutable catalog/universe snapshot.
- Keep explicit static mode for deterministic tests, not the default governed
  operator run.
- Stop forcing `PAPER_EXPLORATION_ALPHA`. Default governed PAPER uses the
  existing standard thresholds:
  - Shans ready required;
  - fusion minimum confidence 0.60;
  - SectorRotation inflow 1.5, confidence 0.60, baseline 10 candles;
  - ShadowFront whale 0.20, sentiment velocity 1.5, confidence 0.60;
  - opportunity score 0.45;
  - optional alpha quorum 1.
- Preserve exploration profile as explicitly labeled observe/research mode and
  never call it the standard capability result.
- Enable managed-existing baseline policy only when Stage 2 inventory lineage
  and Stage 6 lifecycle version match the accepted baseline.
- Permit dynamic symbols to dispatch only when Stages 1-8 activation evidence
  is complete and current.
- Keep one singleton mutation owner, explicit finite campaign envelope, final
  reconciliation, account pin, PAPER endpoint, live lock, and governed Stop.
- Replace the fixed five-day duration ceiling only after offline proof with a
  typed, versioned campaign-horizon policy in the existing runtime-config and
  supervisor owners. Do not scatter duration literals or create a second timer.
- Run the worker under a shorter renewable fenced lease inside the campaign.
  Renewal requires current heartbeat, account/endpoint pin, market truth, clock,
  storage, credentials, Risk, broker truth, reconciliation, and code/config
  fingerprints and may never extend the campaign horizon.
- Recovery inside an active campaign must obtain a new fencing token, prove the
  prior mutation owner is dead, and re-pin account, catalog/universe,
  baseline/inventory lineage, state schema, code commit, and effective config
  before new entries. Reconciliation conflict blocks recovery.
- Browser closure does not kill a legitimately active run; the launcher remains
  the process owner. Closing the launcher/backend performs governed Stop, not
  liquidation. No duplicate backend survives a fresh launcher start.

**Likely owners/files:** runtime config, OperatorPaperSupervisor, launcher/run
scripts, launch readiness, baseline policy, run visibility/heartbeat, tests.

**Required tests:**

- standard profile is default and exact constants are unchanged;
- dynamic catalog snapshot, inventory lineage, account pin, and market provider
  are required for Start;
- static six is not hidden fallback authority;
- Start cannot occur with observe-only stage status;
- duplicate supervisor/runtime blocked;
- crash/restart inside the campaign uses a new fencing token and reconciles
  before entries;
- expired campaign or worker lease, live predecessor, new commit/config, or
  account/catalog/baseline mismatch requires fail-closed Stop and new arm;
- lease renewal cannot extend the campaign and two fencing generations cannot
  mutate concurrently;
- Stop remains zero mutation and holdings intact.

**Binary exit:** launcher can arm one finite, full-capability, standard-profile
dynamic PAPER campaign only when every truth source agrees; its worker can renew
and recover only inside that envelope; no auto-arm or live path exists.

**Stop condition:** activation relies on a stale cached green, an exploration
threshold, competing mutation owners, or automatic re-arming/renewal beyond the
campaign envelope.

### Stage 10 - Make every decision and module contribution operator-readable

**Mandatory stage entry:** execute and record `AGENTS.md` Sections 23 and 24 before any
stage edit. No `STAGE_ENTRY_COVENANT: PASS`, no work.

**Purpose:** Shan can see what the bot considered, why it traded/did not trade,
what owns each position, and what proof backs the answer.

**Work:**

- Keep DecisionFrame, CandidateLifecycle, DecisionRecorder, RunArchive,
  reconciliation, and broker fill ledger as existing evidence owners.
- Replace generic attribution signatures with source-emitted records bound to
  symbol, event time, snapshot ID, and module version.
- Never label AlpacaAdapter/OrderRouter/ExecutionEngine `APPROVED` merely because
  shadow mode is off. Show `NOT_REACHED`, `REFUSED`, `POSTED`, `ACKNOWLEDGED`,
  `PARTIAL`, `FILLED`, or `RECONCILIATION_CONFLICT` from actual lifecycle.
- Add operator views for:
  - catalog -> eligible -> breadth-ranked -> deep -> candidate -> trade funnel;
  - current universe snapshot and inclusion/exclusion reasons;
  - module contribution/decline/missing/dormant reasons;
  - every DecisionFrame and gate in plain English with technical expander;
  - broker inventory with adopted/bot-acquired/reserved provenance;
  - active automated lifecycle reason/floor/stop/time barrier;
  - orders, partial fills, fees, TCA, realized/unrealized PnL by reconciled truth;
  - run/lease/process/market heartbeat and reconciliation health.
- No manual buy, sell, close, liquidate, force, or cancel-all button.
- Coalesce identical high-frequency observations while persisting all candidate,
  decision, safety, order, fill, error, and state-transition records.
- Add log rotation/retention and a manifest so evidence remains discoverable.

**Likely owners/files:** whole-bot attribution, CandidateLifecycle,
DecisionFrame/Recorder, RunArchive, operator API/UI, run visibility, logging,
tests.

**Required tests/browser proof:**

- source module did not run -> UI says did not run/missing/dormant, never
  contributed;
- decision list reconstructs the full gate chain;
- broker truth and local inference are visually distinct;
- no forbidden controls/labels/secrets/raw JSON as primary UX;
- desktop 1440 and mobile 390, no horizontal overflow;
- stale process/market lights freeze independently;
- bounded log-volume soak with lossless decision/order/fill counts.

**Binary exit:** Shan can answer "what did it scan, decide, refuse, submit,
fill, hold, and plan to exit, and why?" from the cockpit with source proof.

**Stop condition:** UI growth does not answer an operator truth question or
relabels inference as execution/broker truth.

### Stage 11 - Offline adversarial certification

**Mandatory stage entry:** execute and record `AGENTS.md` Sections 23 and 24 before any
stage edit. No `STAGE_ENTRY_COVENANT: PASS`, no work.

**Purpose:** prove the complete system without network or broker mutation.

**Proof sequence:**

1. syntax/import/collection;
2. focused unit and contract suites for every stage;
3. run-path positive chain and every refusal path;
4. replay parity with causal/as-of data;
5. multi-symbol concurrency and race tests;
6. dynamic-universe churn tests;
7. partial-fill/restart/reconciliation fault injection;
8. rate-limit/disconnect/clock-skew/corrupt-state/disk-pressure tests;
9. time-compressed 8-hour, 7-day, and 30-day offline campaign soaks with lease
   renewal, log rotation, storage growth, clock, and reconciliation invariants;
10. controlled process-death, predecessor-revival, host-restart, network,
    broker-error/rate-limit, stale-feed, credential, clock, disk-pressure, and
    corrupt-state fault injection with hard stop assertions;
11. full suite with documented environment skips only;
12. browser desktop/mobile proof;
13. source scan proving no threshold/guard/manual/live/Sovereign changes.

**Mandatory run-path positive twins:**

- dynamic eligible candidate -> dispatch -> compile -> submit -> route -> mocked
  broker ack -> mocked reconciled fill;
- broker-owned position -> MovingFloor/stop/time lifecycle -> sell-to-close
  submit -> mocked broker ack -> mocked reconciled fill;
- emergency risk -> PositionUnwind campaign -> governed per-position OMS path;
- restart -> new fencing generation -> prior owner cannot mutate -> broker
  reconciliation -> no duplicate order -> lifecycle resumes only inside the
  same campaign envelope.

**Binary exit:** full offline suite green, no new unexplained skip, no run-path
failure, no mutation, no threshold delta, and all red-team cases pass.

**Stop condition:** any positive proof bypasses a production gate or substitutes
mock truth for the later broker proof rung.

### Stage 12 - Narrow broker-read-only validation (separate approval)

**Mandatory stage entry:** execute and record `AGENTS.md` Sections 23 and 24 before any
stage edit or broker read. No `STAGE_ENTRY_COVENANT: PASS`, no work.

**This stage is not authorized by approval of the implementation plan.**

After Stages 0-11 pass, request Board authorization for exact Alpaca PAPER GETs:

- account/account suffix and status;
- positions;
- open orders;
- crypto asset catalog;
- current asset records for selected/held symbols;
- market-data snapshots needed to prove execution-location coverage, if the
  credential/read policy requires authorization.

No POST/PATCH/DELETE/cancel/replace/sell. Do not print secrets or full account
IDs.

**Binary exit:** actual account catalog/precision/tradability/market-data
coverage reconcile to the implementation; every GET is counted and redacted;
zero mutation.

### Stage 13 - Autonomous full-capability PAPER campaigns

**Mandatory stage entry:** execute and record `AGENTS.md` Sections 23 and 24
before any stage edit or campaign. No `STAGE_ENTRY_COVENANT: PASS`, no work.

**This stage is not authorized by approval of the implementation plan. Every
external PAPER campaign remains a separate Board decision.** Approval of one
campaign does not authorize the next or any live action.

#### Campaign entry contract

Before Campaign A can be armed:

1. Stages 0-12 and every binary exit gate pass with current evidence.
2. The runtime uses the full standard profile, broker-discovered dynamic crypto
   universe, held/open-order symbol priority, and the complete proven module
   manifest. No commissioning whitelist, exploration thresholds, protected-
   baseline blanket veto, or hidden reduced-capability fallback remains active.
3. Every module is truthfully `WIRED_WITH_ROLE`, `PRESERVED_DORMANT`, or
   `BLOCKED_WITH_REASON`. `FULL_CAPABILITY` never forces a dormant/inapplicable
   module to fabricate a contribution or forces a candidate to trade.
4. The current fixed `432000`-second supervisor/runner/API/UI ceiling has been
   replaced through the existing canonical owners by typed, versioned campaign
   policy and a renewable fenced worker lease. The 7-day and 30-day campaigns
   are impossible under the current implementation and may not be enabled by
   deleting validation or scattering larger literals.
5. The deployment target passes cold boot, durable-state, clock, credential,
   log/storage rotation, archive, recovery, process ownership, and operator-
   visibility qualification. This gate is platform-neutral; no AWS resource is
   authorized by this plan.
6. A fresh read-only preflight pins PAPER endpoint/account, reconciles positions,
   orders, fills, catalog/universe, inventory lineage, and state schema, and
   proves no unknown open order or competing mutation owner.
7. The immutable campaign envelope records maximum horizon, code/config/module
   fingerprints, broker and state lineages, acceptance metrics, stop conditions,
   and required final reconciliation before Start is enabled.

#### Board campaign ladder

1. **Campaign A - 8 continuous hours.** This is the next external test. It runs
   the complete lawful standard-profile capability, not an observe-only or
   exploration profile.
2. **Campaign B - 7 continuous days.** Arm only after Campaign A's report passes
   its declared operations, safety, reconciliation, evidence, capacity, and
   recovery gate and no blocker is carried forward silently.
3. **Campaign C - 30 continuous days.** Arm only after Campaign B passes and
   storage growth, log/archive retention, broker/data rate budgets, recovery,
   clock, credential longevity, and decision-evidence capacity support a month.
4. **Campaign D - governed endurance and controlled-failure certification.**
   Arm only after Campaign C. The Board selects the maximum horizon from current
   evidence; it is deliberately not hard-coded in this plan. Define steady state,
   fault schedule, recovery budget, hard stop alarms, and final reconciliation
   before approval.

Once a campaign is explicitly armed, normal scanning, decisions, entries,
broker-position-backed automated exits, monitoring, evidence capture, worker-
lease renewal, and lawful crash recovery operate autonomously inside the
campaign envelope. Routine human trade decisions or periodic re-approval clicks
are not required inside the approved horizon. The bot cannot self-arm a new
campaign or extend the current horizon.

#### Binary campaign acceptance contract

Each campaign report must prove or honestly mark unknown:

- exact code, effective config, campaign, account, catalog/universe, opening
  broker snapshot, state schema, and module-manifest fingerprints remained
  pinned;
- one fenced mutation owner at all times; no predecessor resurrection, duplicate
  order, naked/oversell, unknown open order, or mutation beyond the envelope;
- independent BOT and market vitality, current executable market truth, clock,
  storage, log/archive, credential, broker, Risk, OMS, and reconciliation health;
- every scanned candidate's causal funnel and every module's source-emitted
  contribution/decline/missing/dormant status remain reconstructable;
- every natural order has broker acknowledgement; every claimed fill has a
  reconciled broker fill/execution ID; partial/reject/cancel/replace states match
  broker truth; fees and TCA are confirmed or explicitly unavailable/pending;
- every natural automated sell-to-close has lifecycle provenance, fresh broker
  quantity, reservation, broker acknowledgement, and reconciled fill; no holding
  is sold merely to exercise the path;
- every restart/failover remains inside the campaign, fences the predecessor,
  reconciles before new entries, and neither loses nor replays an order;
- telemetry loss, evidence gaps, rate limiting, stale inputs, storage pressure,
  numeric failure, degraded mode, exceptions, restart counts, and recovery time
  are fully counted against predeclared acceptance criteria;
- horizon completion or governed Stop ceases new work, releases the lease,
  preserves positions without manual liquidation, and completes final cash/
  positions/orders/fills reconciliation.

No campaign has a target trade count. If no candidate survives unchanged gates,
the campaign may pass operational/safety refusal criteria, but any unexercised
external positive lifecycle remains explicitly unproven and blocks claims that
it fired. The remedy is evidence review, lawful replay, or a later approved
horizon, never threshold relaxation or force-trading.

Campaign D does not literally run without limit until a crash. Its controlled
fault matrix begins offline and covers process termination and predecessor
revival, host restart, network/DNS/TLS interruption, broker 429/5xx/timeout and
ambiguous acknowledgement, stale/disordered market feed, credential failure,
clock drift, disk pressure, database checkpoint/contention/corruption recovery,
partial fills, duplicate/out-of-order events, and log/archive failure. Any
external PAPER fault injection is separately Board-approved and stops on its
declared alarm or maximum horizon.

No stage claims profitability from one or several runs. Alpaca PAPER omits
material live effects, so capability, operational resilience, simulated
execution quality, statistical strategy evidence, and live capacity remain
separate questions.

## 10. Module Status and Intended Role

| Module/area | Current truth | Adjusted role |
| --- | --- | --- |
| MarketTruthSnapshot | WIRED authority | Remains sole executable market-truth owner; execution-location source added. |
| SignalFusion | WIRED but global/cache-causal defect | Remains fusion owner with per-symbol/as-of state. |
| ShansCurve | Per-symbol producer, global fusion cache | Same alpha contribution with causal symbol binding. |
| WhaleFlow | Per-symbol engine exists; global duplicate and missing fusion truth observed | Single per-symbol trade-flow path; no synthetic candle whale input. |
| Regime/Entropy/Toxicity/Insider/Physical | Wired but shared fusion cache | Same contributing roles, symbol/time-bound. |
| ShadowFront | WIRED but whale conditions never qualified in run | Preserve thresholds; feed honest per-symbol whale/sentiment; fill-driven state. |
| SectorRotation | Main productive candidate source | Preserve alpha; remove local quantity/PnL authority; fill-driven state. |
| LiquidityVoid | Producer/consumer wired; no consumable pair in run | Preserve book-native edge; add internal decline diagnostics and causal buffered proof. |
| GammaFront | WIRED_EXIT_ONLY / ENTRY_FEED_DORMANT | Preserve exactly; no fake dark-pool/options feed. |
| AdaptiveDC | Native module tested/replay-capable, missing production feed | Wire per-symbol market ticks as contributory alpha. |
| MovingFloor | Monitors broker holdings, mocked sell path only | Preserve profit-floor role; broker-backed governed sell-to-close after proof. |
| Stop-loss/time barrier | Strategy-local intents not broker-fill authoritative | Bind to broker-confirmed lot lifecycle and OMS. |
| PositionUnwindManager | Sophisticated preserved module, no production caller | Wire as emergency campaign planner through existing decision/OMS path. |
| ExposureManager | Active risk owner with incomplete broker inventory hydration | Remains risk owner; hydrate full broker book/lots/reservations/fills. |
| CrossAssetRiskCalculator | Passive, illustrative/un-calibrated | Upgrade as calibrated contributor; never second risk owner. |
| PositionSizingEngine | Canonical downstream sizing owner | Remains owner; add tail/correlation/liquidity/uncertainty caps. |
| OpportunityRanker | Passive placeholder cost/simple score | Upgrade passive robust ranking; no execution/veto authority. |
| NetEdgeGovernor | Active hard gate | Remains hard; improve source-bound conservative cost distribution. |
| TradeEfficiencyGovernor | Missing confirmed history in run | Contribute only with sufficient reconciled round trips; otherwise missing truth. |
| DecisionFrame/Compiler | Active | Remain decision artifact/compiler; add exact lifecycle/universe/inventory evidence. |
| OrderRouter/OMS | Active BUY route/reconciliation | Remain order owner; add SELL reservation/final position gate/stream lifecycle. |
| AlpacaPaperAdapter | PAPER-only, pinned, BUY-limit only | Add contract-parity catalog read and explicit governed sell-to-close; live stays blocked. |
| StateStore | Durable supporting truth | Persist canonical mappings/lots/reservations/fills/lineage; not broker authority. |
| Reconciliation | Startup/shutdown/post-ack pieces exist | Attach current snapshot at decision time and drive inventory/strategy truth. |
| WholeBotAttribution | Mixed source and inferred signatures | Source-emitted status only; no generic approved activity. |
| Supervisor/launcher | Governed singleton with fixed five-day ceiling | Preserve explicit arming/Stop; add immutable finite campaign envelope, shorter renewable fenced worker lease, and reconciled recovery only inside the same envelope. |
| SovereignExecutionGuard | DORMANT_BY_POLICY | Remains dormant. |

No module is proposed for deletion. Every module is wired with a lawful role or
preserved/block-classified with a named reason.

## 11. Disagreements and Board Decisions Needed

### Disagreement 1: "Take away restrictions" cannot include hard safety/economic controls

I recommend removing commissioning constraints only after replacing them with
stronger authorities. I do **not** recommend removing MarketTruthSnapshot,
stale/TTL, NetEdge, risk, sizing, concentration, drawdown, OMS, reconciliation,
account pin, PAPER endpoint, no-short/no-naked-sell, singleton mutation owner,
finite campaign envelope, fenced worker lease, or explicit arming. Those are
normal professional bot controls and binding laws.

### Disagreement 2: Existing holdings cannot be sold on a generic "makes sense" score

The phrase must be made executable and auditable. Under current law, adopted
holdings may be sold only by a governed automated position lifecycle: stop-loss,
MovingFloor, time barrier, or emergency PositionUnwind, with fresh broker
quantity and no manual instruction. A generic bearish strategy opinion is not
enough.

### Disagreement 3: Longer autonomy is accepted; unbounded mutation is not

I accept Shan's direction to end commissioning mini-runs. After Stages 0-12
pass, the next test is the 8-hour full-capability campaign, followed by 7 days
and 30 days only on evidence-gated promotion. The existing five-day cap is not
the final design and must be replaced through the canonical config/supervisor
owners by a finite campaign envelope and renewable fenced worker lease.

I do **not** accept "run until crash" as a literally unbounded broker-mutating
authorization. Campaign D provides the stronger test: a Board-set maximum
horizon, controlled faults, deterministic stop conditions, fenced recovery, and
final reconciliation. Removing the outer boundary would violate Sections 10,
19, and 24 and remains a surfaced safety disagreement.

### Disagreement 4: Multi-tenant design must not be activated before isolation proof

I agree the bot should become multi-tenant after the campaign program. Current
work should avoid unnecessary single-tenant hardcoding, but adding a speculative
parallel tenant authority now would increase the immediate execution blast
radius. Multi-tenant activation remains a separate post-test program with a
truth map, threat model, per-tenant/account mutation authority, credential/state/
lease/order isolation, negative leakage tests, and any new dependency or
subsystem approval.

### Approval requested now

Approve **implementation of Stages 0-11 only**, with these boundaries:

- PAPER-only code/config/test/UI work;
- no actual PAPER run;
- no actual broker GET or mutation;
- no live/real-money path;
- no threshold/guard weakening;
- no manual trade controls;
- no module deletion;
- no new external dependency or new subsystem;
- exact per-file staging after each bounded seam.

Stages 12 and 13 require later, separate approvals.

## 12. Tests, Proof Ladder, Limitations, and Unknowns

### What this planning turn actually proved

- **Repo-read proof:** named source/functions/contracts above were inspected.
- **Runtime-log proof:** the 2026-07-17 four-hour log was inspected; it proves
  492 iterations, zero orders, module/gate evidence, future-age contamination,
  and completed shutdown behavior.
- **Documentation proof:** official Alpaca, Freqtrade, and QuantConnect patterns
  plus official AWS campaign-resilience and tenant-isolation patterns were
  reviewed.

### What this planning turn did not prove

- No tests were run during this planning turn.
- The latest `1820 passed, 14 skipped, 0 failed` full-suite result is historical
  evidence from the current handoff/report, not a rerun here.
- No source was compiled or executed.
- No backend or browser was launched.
- No Alpaca GET was made.
- No PAPER order/run or broker mutation occurred.
- The current `432000`-second implementation ceiling remains unchanged. A 7-day
  or 30-day campaign cannot be started by the current code.
- No campaign envelope, renewable/fenced lease, autonomous restart, campaign
  policy schema, long-horizon storage proof, or controlled-failure harness has
  been implemented or tested.
- No AWS resource, Linux deployment, cloud credential integration, distributed
  coordinator, or AWS Fault Injection Service experiment was created or run.
- Multi-tenant execution is not implemented or proven. Tenant isolation, tenant-
  scoped state/credentials/leases/orders/risk/reconciliation, and cross-tenant
  negative tests remain future work after the campaign program.
- No catalog count for the pinned account was proven. The documentation's 20+
  assets/56 pairs is not an account-specific runtime claim.
- No BUY or SELL is currently proven through the real external Alpaca adapter
  from natural signal to reconciled fill.
- The existing positive MovingFloor test stops at a mocked submit boundary and
  bypasses the live protected-baseline/external-adapter problem; it is not
  external sell proof.
- The exact internal reason LiquidityVoid produced no pair in the run is not yet
  proven; the plan adds diagnostics before changing logic.
- Profitability, alpha validity, capacity, and optimal thresholds remain unknown.
- PAPER cannot prove market impact, information leakage, latency slippage, queue
  position, price improvement, or full live fee behavior; one month of PAPER
  evidence would not remove those unknowns.
- Fee/TCA completeness remains limited by missing historical broker hydration.
- The actual provider plan/rate limits for a full catalog must be validated
  after narrow authorized reads and offline load tests.

### Anti-hallucination self-check

- Did I call the bot ready? **No.**
- Did I call the historical test suite rerun? **No.**
- Did I claim the documented catalog is available to this account? **No.**
- Did I treat mocked fill/order tests as broker proof? **No.**
- Did I force every module to contribute? **No.**
- Did I hide future timestamp, cross-symbol, sell, emergency, inventory, or
  placeholder-math defects? **No.**
- Did I propose a duplicate authority? **No;** the plan consolidates into
  existing owners.
- Did I propose a threshold reduction? **No.**
- Did I propose manual controls, live mode, or unbounded self-arm? **No.**
- Did I claim the 8-hour/7-day/30-day campaign ladder works today? **No;** the
  five-day ceiling and campaign-lifecycle implementation are still blockers.
- Did I call authentication multi-tenant isolation? **No.**
- What remains inference? The likely operational benefit of the staged design;
  it must be proven stage by stage.

## 13. Safety Confirmation and Exact Staging Recommendation

### Safety confirmation

- No PAPER run.
- No broker GET/POST/PATCH/DELETE/cancel/replace/sell/liquidation.
- No live or real money.
- No manual buy/sell/force/close/cancel-all control.
- No naked SELL or shorting.
- No threshold, NetEdge, Risk, TTL, sizing, masking, OMS, or strategy gate
  weakened.
- No secret read, printed, logged, or staged.
- No state/log/database/runtime file edited.
- No module deleted, flattened, stubbed, or silently activated.
- SovereignExecutionGuard remains dormant.
- Existing accepted baseline and four positions were not modified.

### Exact staging recommendation for this planning turn

Do not stage or commit implementation because Board approval is pending. If the
Board wants this plan artifact recorded before implementation, stage exactly:

```powershell
git add -- AGENTS.md
git add -- reports/completion/PAPER_TRUE_CAPABILITY_MASTER_PLAN.md
git add -- CHECKPOINT_TRACKER.md
git add -- reports/codex_handoff_latest.md
```

Do not stage any other report or handoff, `state/*`, `.pytest_tmp/`, log,
database, screenshot, secret, or untracked audit script with these files.

### Approval boundary

Upon explicit approval, begin with Stage 0 and Stage 1 only, complete their
binary exit gates, report the diff/tests, and then proceed in order. Do not jump
to catalog activation, SELL support, or a PAPER run because those later stages
are the visible capabilities; the causal and inventory foundations gate them.
