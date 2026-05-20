# Seam 7E Strategy Fusion Runtime Wiring

## Scope

Current HEAD at implementation time: `d7f7f71`

Seam 7E wires runtime evidence flow only. It does not submit orders, mutate broker state, run a bot loop, call live endpoints, or create execution authority.

Changed files:

- `app/brain/signal_fusion.py`
- `app/strategies/council_metadata.py`
- `app/strategies/strategy_vote_adapters.py`
- `app/strategies/strategy_router.py`
- `app/portfolio/opportunity_ranking.py`
- `app/core/decision_compiler.py`
- `tests/test_seam7e_strategy_fusion_runtime_wiring.py`
- `reports/seam7e_strategy_fusion_runtime_wiring.md`

Packet path note: `app/core/signal_fusion.py` does not exist. The active implementation is `app/brain/signal_fusion.py`.

## Intent And Authority

`strategy_router.py`:

- True intent: deterministic strategy sleeve eligibility routing from `FusionDecision`.
- Authority: ranking/routing hints only; no execution, broker, allocation, or risk approval.
- Seam 7E change: added `collect_strategy_runtime_evidence(...)` to surface eligible, missing, and abstained strategy evidence with provenance.

`strategy_vote_adapters.py`:

- True intent: pure StrategySignal/recommendation to `StrategyVote` transforms.
- Authority: transform only; no runtime activation, feed wiring, risk, sizing, or execution.
- Seam 7E change: added `adapt_vote_to_runtime_evidence(...)` and `missing_strategy_runtime_evidence(...)`.

`council_metadata.py`:

- True intent: shared metadata vocabulary for council/vote metadata.
- Authority: metadata construction and validation only.
- Seam 7E change: added the normalized runtime evidence contract and summary helper.

`gamma_front.py`, `sector_rotation.py`, `liquidity_void.py`, `hedging_flow.py`:

- True intent: native strategy/protection engines requiring native inputs.
- Authority: signal/assessment/recommendation logic only in this seam.
- Seam 7E posture: inspected and represented through router/vote evidence; native missing input stays missing instead of fabricated.

`opportunity_ranking.py`:

- True intent: passive cross-asset opportunity ranking model.
- Authority: ranking only; no allocation or execution.
- Seam 7E change: added `summarize_opportunity_ranking(...)` for DecisionRecord telemetry.

`app/brain/signal_fusion.py`:

- True intent: central deterministic signal fusion and strategy routing hints.
- Authority: aggregate/rank/degrade/veto in fusion only; no broker authority.
- Seam 7E change: added strategy/intelligence/world-awareness evidence ingestion and telemetry preservation.

`decision_compiler.py` / `DecisionRecord`:

- True intent: compile immutable decision records from truth, features, votes, risk, and additional metadata.
- Authority: decision artifact compilation only.
- Seam 7E change: carries `strategy_attribution`, `intelligence_attribution`, `world_awareness_attribution`, `fusion_summary`, `opportunity_ranking_summary`, `missing_truth_summary`, `degraded_fallback_summary`, and `blocked_or_abstained_summary` through existing metadata.

## Evidence Contract

Normalized runtime evidence fields:

- `module_name`
- `category`
- `status`
- `input_truth`
- `input_source`
- `output_summary`
- `effect`
- `score_or_direction`
- `confidence`
- `reason`
- `provenance`
- `timestamp_ns`
- `contract_version`

Supported Seam 7E statuses include active strategy/protection/advisory records, degraded fallback, missing feed truth, warmup, compliance/premium/live-only blocks, failed closed, and abstain. Missing or degraded truth is summarized but not converted into signal.

## Wiring Behavior

StrategyRouter:

- Preserves multiple sleeve records instead of collapsing them to one score.
- Emits active records for fusion-eligible sleeves.
- Emits `ABSTAIN` for ineligible sleeves.
- Emits `MISSING_FEED_TRUTH` for MovingFloor/AdaptiveDC when no protective/alpha vote is supplied.
- Records `authority=ranking_only_no_execution`.

Strategy vote adapters:

- Convert active StrategyVotes into `ACTIVE_STRATEGY_VOTE`.
- Convert MovingFloor protective recommendations into `ACTIVE_PROTECTION` / `PROTECT_TOTAL_PROFIT`.
- Preserve missing feed status as `MISSING_FEED_TRUTH`.

SignalFusion:

- Accepts strategy, intelligence, and world-awareness advisory evidence.
- Preserves records in telemetry sections and `edge_attribution`.
- Does not silently drop missing/degraded contributors.
- Still fails closed on missing/stale critical fusion inputs.

DecisionCompiler:

- Uses existing `DecisionRecord.metadata`.
- Does not add a new contract field or break execution spine callers.

Opportunity ranking:

- Summarizes ranking as `RANKED` or `ABSTAIN`.
- Records `execution_authority=none`.

## Module Outcomes

Wired:

- StrategyRouter runtime evidence collection
- StrategyVote adapter evidence normalization
- Council runtime evidence summary
- SignalFusion strategy/intelligence/world-awareness telemetry preservation
- DecisionCompiler attribution metadata carry-through
- Passive opportunity-ranking summary
- Seam 7D source catalog status as world-awareness advisory context

Missing/degraded by truth:

- MovingFloor: `MISSING_FEED_TRUTH` unless a protective recommendation vote is supplied.
- AdaptiveDC: `MISSING_FEED_TRUTH` unless a recommendation vote is supplied.
- Sentiment/whale/regime/world-awareness samples in deterministic tests: missing or blocked when native feed truth is absent.

Intentionally blocked:

- SEC EDGAR live source status remains `INTENTIONALLY_BLOCKED_LIVE_ONLY` from Seam 7D source catalog.
- No live scraping, premium query, or portal fact fabrication was added.

## Seam 7E Completion Correction - Native Activation Proof

Current rework HEAD before commit: `e6c7e37`

The completion correction adds a focused native activation test that calls each in-scope module through its native API, normalizes the real native output into runtime evidence, feeds that evidence through `SignalFusion`, and carries it into `DecisionCompiler` metadata. It also fixes one exact `SignalFusion` attribution collision: when externally supplied native evidence already owns a module key such as `ShansCurve`, fusion-cache attribution is retained under `ShansCurve:fusion_cache` instead of overwriting the native record.

Native strategy/alpha proof:

| Module | Native API called | Native output carried | Runtime entry | Decision metadata proof |
| --- | --- | --- | --- | --- |
| MovingFloor | `TopologicalMovingFloor.process_tick(FloorMarketTick)` | protective recommendation converted through `adapt_moving_floor_to_vote` with native provenance | `SignalFusion.update_strategy_evidence(...)` | `strategy_attribution` and `edge_attribution["moving_floor"]` |
| Shans Curve | `ShansCurve.update_order_book(...)` | `ShansCurveSignal` | `SignalFusion.update_strategy_evidence(...)` | `strategy_attribution` and `edge_attribution["ShansCurve"]` |
| AdaptiveDC | `AdaptiveDC.process_tick(DCMarketTick)` | DC recommendation converted through `adapt_adaptive_dc_to_vote` with native provenance | `SignalFusion.update_strategy_evidence(...)` | `strategy_attribution` and `edge_attribution["adaptive_dc"]` |
| gamma_front | `GammaFrontStrategy.update_dark_pool(DarkPoolPrint)` | `StrategySignal` | `SignalFusion.update_strategy_evidence(...)` | `strategy_attribution` and `edge_attribution["gamma_front"]` |
| sector_rotation | `SectorRotationStrategy.update_candle(...)` | `StrategySignal` | `SignalFusion.update_strategy_evidence(...)` | `strategy_attribution` and `edge_attribution["sector_rotation"]` |
| liquidity_void | `LiquidityVoidStrategy.update_topology(...)` plus `update_order_book(...)` | `StrategySignal` | `SignalFusion.update_strategy_evidence(...)` | `strategy_attribution` and `edge_attribution["liquidity_void"]` |
| hedging_flow | `HedgingFlow.assess(...)` plus `recommend(...)` | `HedgeRecommendation` | `SignalFusion.update_strategy_evidence(...)` | `strategy_attribution` and `edge_attribution["hedging_flow"]` |

Native intelligence/data proof:

| Module | Native API called | Native output carried | Runtime entry | Decision metadata proof |
| --- | --- | --- | --- | --- |
| sentiment_engine | `SentimentEngine.update_source(...)` plus `aggregate(...)` | `AggregateSentiment` | `SignalFusion.update_intelligence_evidence(...)` | `intelligence_attribution` and `edge_attribution["sentiment_engine"]` |
| sentiment_velocity | `SentimentVelocityEngine.update_sentiment(...)` plus `analyze(...)` | `SentimentVector`; `MacroSignal` asserted present | `SignalFusion.update_intelligence_evidence(...)` | `intelligence_attribution` and `edge_attribution["sentiment_velocity"]` |
| whale_zone_engine | `WhaleZoneEngine.update(...)` | `WhalePresenceZone` | `SignalFusion.update_intelligence_evidence(...)` | `intelligence_attribution` and `edge_attribution["whale_zone_engine"]` |
| regime_detector | `RegimeDetector.update(FeatureVector, ...)` | `RegimeType` plus detector confidence | `SignalFusion.update_intelligence_evidence(...)` | `intelligence_attribution` and `edge_attribution["regime_detector"]` |
| feature_builder | `FeatureBuilder.build_all_features(...)` | feature dict with `volatility_zscore` and `order_book_imbalance` | `SignalFusion.update_intelligence_evidence(...)` | `intelligence_attribution` and `edge_attribution["feature_builder"]` |
| ghost_tick_detector | `FastGhostTickDetector.update(...)` plus `detect_vector(...)` | `np.ndarray[bool]` for supported single-instrument vector path | `SignalFusion.update_intelligence_evidence(...)` | `intelligence_attribution` and `edge_attribution["ghost_tick_detector"]` |
| validators | `DataValidator.validate_order_book(...)` | `ValidationResult` | `SignalFusion.update_intelligence_evidence(...)` | `intelligence_attribution` and `edge_attribution["validators"]` |

World-awareness and ranking proof:

| Module | Native API called | Native output carried | Runtime entry | Decision metadata proof |
| --- | --- | --- | --- | --- |
| world_awareness/source_catalog | `source_status_signature(SourceFamily.SEC_EDGAR)` | source status signature | `SignalFusion.update_world_awareness_evidence(...)` | `world_awareness_attribution` and `edge_attribution["world_awareness/source_catalog"]` |
| openinsider | `OpenInsiderAdapter.normalize_payload(...)` | `WorldAwarenessEvent` with `canonical_truth_claimed=False`, `live_attached=False` | `SignalFusion.update_world_awareness_evidence(...)` | `world_awareness_attribution` and `edge_attribution["openinsider_adapter"]` |
| sec_edgar | `SecEdgarAdapter.normalize_payload(...)` | `WorldAwarenessEvent` with no live/premium truth claim | `SignalFusion.update_world_awareness_evidence(...)` | `world_awareness_attribution` and `edge_attribution["sec_edgar_adapter"]` |
| capitol_trades | `CapitolTradesAdapter.normalize_payload(...)` | `WorldAwarenessEvent` with no live/premium truth claim | `SignalFusion.update_world_awareness_evidence(...)` | `world_awareness_attribution` and `edge_attribution["capitol_trades_adapter"]` |
| quiver_free | `QuiverFreeAdapter.normalize_payload(...)` | `WorldAwarenessEvent` with no live/premium truth claim | `SignalFusion.update_world_awareness_evidence(...)` | `world_awareness_attribution` and `edge_attribution["quiver_free_adapter"]` |
| official_calendars | `OfficialCalendarsAdapter.normalize_payload(...)` | `WorldAwarenessEvent` with no live/premium truth claim | `SignalFusion.update_world_awareness_evidence(...)` | `world_awareness_attribution` and `edge_attribution["official_calendars_adapter"]` |
| official_releases | `OfficialReleasesAdapter.normalize_payload(...)` | `WorldAwarenessEvent` with no live/premium truth claim | `SignalFusion.update_world_awareness_evidence(...)` | `world_awareness_attribution` and `edge_attribution["official_releases_adapter"]` |
| opportunity_ranking | `OpportunityRanker.rank(...)` plus `summarize_opportunity_ranking(...)` | `OpportunityRankingReport`, `status=RANKED`, `execution_authority=none` | Decision metadata via `opportunity_ranking_summary` | `record.metadata["opportunity_ranking_summary"]` |

Focused assertion proof:

- `test_seam7e_completion_correction_calls_every_native_module_and_carries_output_to_decision_record` asserts every listed module is called through the native API, carries native output/provenance, enters `SignalFusion` evidence ingestion, and appears in `DecisionCompiler` metadata.
- The same test asserts `OpportunityRanker` produces a ranked report while preserving `execution_authority=none`.
- The test asserts world-awareness adapter fixtures do not claim canonical live truth or live attachment.

Residual native branch blockers:

- `FeatureBuilder.calculate_depth_contraction(...)` is not counted as activated. Its optional `depth_history` branch currently expects `order_book.market_depth`, but the canonical `OrderBookSnapshot` used by the test does not expose `market_depth`. The module is activated through `build_all_features(...)` on supported candle/order-book/spread/whale-zone inputs only.
- `FastGhostTickDetector.detect_vector(...)` multi-instrument covariance branch is not counted as activated. The branch currently computes a one-dimensional Mahalanobis expression and then sums on `axis=1`, producing `numpy.exceptions.AxisError: axis 1 is out of bounds for array of dimension 1` for the two-instrument fixture. The module is activated through the supported single-instrument vector path only.

## Verification

Compile:

```text
venv/Scripts/python.exe -m py_compile app/strategies/strategy_router.py app/strategies/strategy_vote_adapters.py app/strategies/council_metadata.py app/strategies/gamma_front.py app/strategies/sector_rotation.py app/strategies/liquidity_void.py app/strategies/hedging_flow.py app/portfolio/opportunity_ranking.py app/brain/signal_fusion.py app/core/decision_compiler.py app/models/contracts.py app/models/signals.py tests/test_seam7e_strategy_fusion_runtime_wiring.py
```

Result: passed.

Focused Seam 7E:

```text
venv/Scripts/python.exe -m pytest -q tests/test_seam7e_strategy_fusion_runtime_wiring.py
```

Result: `11 passed`.

Scoped non-mutating regression:

```text
venv/Scripts/python.exe -m pytest -q tests/test_seam7a_local_worktree_asset_recovery.py tests/test_seam7b_brain_math_runtime_stability.py tests/test_seam7c_intelligence_regime_hydration.py tests/test_seam7d_world_awareness_compliance_filters.py tests/test_intelligence_portfolio_state_truth_spine.py tests/test_upstream_dispatch_signal_submission.py
```

Result: `68 passed`.

Safety scan across changed files found no broker mutation authority, Alpaca live endpoint, POST/PATCH/DELETE path, network client import, or secret value. Matches were limited to the adapter docstring phrase `side string` and the focused test's forbidden-attribute assertions.

## Confirmations

- No live endpoint or live mode was used.
- No broker mutation was added or executed.
- No Alpaca PAPER order submission occurred.
- No cancel, replace, sell, rebalance, liquidation, or mutation approval flag was used.
- No fake strategy, intelligence, world-awareness, broker, PnL, slippage, net-edge, or profitability facts were invented.
- No duplicate execution, broker, reconciliation, or reservation authority was created.

## Seam 7F Readiness

Seam 7E carries runtime evidence into fusion and DecisionRecord metadata. Seam 7F can now attach risk/governor/economic enforcement to these records without needing to fabricate missing truth or move execution authority into strategy/fusion modules.
