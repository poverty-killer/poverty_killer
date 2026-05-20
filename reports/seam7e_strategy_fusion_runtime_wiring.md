# Seam 7E Strategy Fusion Runtime Wiring

## Scope

Current HEAD at implementation time: `d7f7f71`

Seam 7E wires runtime evidence flow only. It does not submit orders, mutate broker state, run a bot loop, call live endpoints, or create execution authority.

Changed files:

- `app/strategies/council_metadata.py`
- `app/strategies/strategy_vote_adapters.py`
- `app/strategies/strategy_router.py`
- `app/brain/signal_fusion.py`
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

Result: `10 passed`.

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
