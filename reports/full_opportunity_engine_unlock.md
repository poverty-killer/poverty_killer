# Full Opportunity Engine Unlock

## Verdict

Implementation and non-mutating verification completed. Runtime PAPER smoke did not start because the local execution environment has no populated Alpaca paper credentials available to native Windows PowerShell.

## Root Cause Addressed

The bot had a veto-driven dispatch shape: alpha modules could stop the candidate before a complete shared decision frame existed, and economic admissibility was still split from the active submit path. This seam makes the runtime build a DecisionFrame around the same candidate market snapshot, records every relevant alpha contribution or abstention, lets the compiler emit BUY / SELL / NO_TRADE from the complete frame, and moves NetEdgeGovernor into active execution admission.

## Files Changed

- app/config.py
- app/core/candidate_lifecycle.py
- app/core/decision_compiler.py
- app/core/decision_frame.py
- app/execution/engine.py
- app/main_loop.py
- scripts/run_bounded_paper.ps1
- tests/test_decision_frame_orchestration_paper_exploration_alpha.py
- tests/test_full_opportunity_engine_unlock.py
- tests/test_runtime_dispatch_admission_telemetry.py
- reports/full_opportunity_engine_unlock.md

## Profile Enforcement

`PAPER_EXPLORATION_ALPHA` is explicit and paper-only. DEFAULT remains the default. The bounded Windows PowerShell script now accepts `-PaperExplorationAlpha`, sets the runtime env flags, resolves the active profile in preflight, and fails closed if the requested profile resolves inactive/default.

The profile refuses non-paper activation through config validation and preflight checks. Runtime logs include active profile, active thresholds, broker mode, Alpaca paper flag, endpoint, strategy toggles, and active symbols.

## Threshold Profile

The exploration profile relaxes only alpha/selectivity thresholds for PAPER data gathering:

- `shans_ready_required`: `True -> False`
- `fusion_min_confidence`: default strategy confidence -> `0.35`
- `sector_inflow_threshold`: `1.5 -> 0.75`
- `sector_rotation_min_confidence`: default strategy confidence -> `0.45`
- `sector_rotation_min_baseline_candles`: `10 -> 3`
- `shadowfront_whale_threshold`: default whale threshold -> `0.10`
- `shadowfront_sentiment_velocity_threshold`: default sentiment threshold -> `0.10`
- `shadowfront_min_confidence`: default strategy confidence -> `0.45`
- `minimum_opportunity_score`: `0.45 -> 0.25`
- `optional_alpha_quorum`: `1 -> 0`

These changes do not relax live endpoint, real-money, market truth, broker truth, stale/backfill/synthetic truth, quote/session, sell authority, pre-trade guardrail, invalid order, or NetEdge hard gates.

## DecisionFrame Orchestration

Runtime now builds DecisionFrame evidence for ShansCurve, ShadowFront, SectorRotation, LiquidityVoid, GammaFront, StrategyRouter, SignalFusion, StrategySignal, StrategyVote, MarketTruthSnapshot, guardrails, edge attribution, and NetEdge when available.

Normal alpha imperfections are frame evidence rather than silent erasers:

- `shans_not_ready` -> ShansCurve `MISSING_TRUTH`
- `OBSERVED_SIGNAL_MISSING` / `OBSERVED_VOTE_MISSING` -> SectorRotation `MISSING_TRUTH`
- `OBSERVED_PAIR_STALE` -> SectorRotation `STALE`
- `shadowfront_declined_*` -> ShadowFront `DECLINED`
- low sentiment / low volume z-score / weak regime / optional module absence -> penalty or decline evidence

Fusion and Router are recorded as ranking/advisory authorities. In exploration mode, Router ranking no longer suppresses otherwise registered module evidence by itself.

## NetEdge Gate

ExecutionEngine now evaluates each signal through NetEdgeGovernor before pre-trade guardrail routing. A trade may proceed only when modeled net edge is positive after modeled fee, spread, slippage, latency drag, partial-fill drag, exit cost, confidence, size, horizon, and risk inputs. Negative or unknown modeled edge blocks with reason-coded evidence and `broker_post=false`.

Modeled default execution burdens preserve the prior total economic floor shape: fee 6 bps, spread 10 bps, slippage 8 bps, latency drag 4 bps, partial-fill drag 4 bps, exit cost 4 bps.

## Hard Safety Preserved

Still hard-blocked:

- fake market truth or broker truth
- stale/backfill/replay/synthetic executable truth
- missing/stale/conflicting MarketTruthSnapshot
- live endpoint
- real-money mode
- broker mutation in tests
- quote/session truth violation
- sell-authority violation
- pre-trade guardrail block
- invalid symbol/side/qty/price
- unsupported broker action/portal
- negative or unknown modeled NetEdge
- truth conflicts

## MovingFloor

MovingFloor was not attached in this seam. The strategy and vote adapter exist, but production runtime does not yet have broker-position-backed position truth wiring that can safely prove protective-only exit authority. Attaching it now would risk mixing entry flow with exit/profit-defense authority. The immediate next seam after entry flow proof should wire MovingFloor as protective-only, broker-position-backed exit evidence that cannot open fresh trades.

## Tests Run

- `venv/Scripts/python.exe -m py_compile app/config.py app/core/candidate_lifecycle.py app/core/decision_compiler.py app/core/decision_frame.py app/execution/engine.py app/main_loop.py`
- `venv/Scripts/python.exe -m pytest tests/test_full_opportunity_engine_unlock.py tests/test_decision_frame_orchestration_paper_exploration_alpha.py -q`
- `venv/Scripts/python.exe -m pytest tests/test_full_opportunity_engine_unlock.py tests/test_decision_frame_orchestration_paper_exploration_alpha.py tests/test_candidate_lifecycle_scorecard_seam.py tests/test_canonical_market_snapshot_decision_spine.py tests/test_runtime_dispatch_admission_telemetry.py tests/test_execution_spine_order_routing.py -q`
- `venv/Scripts/python.exe -m pytest tests/test_f4a_decimal.py tests/test_execution_sr_decimal.py -q`
- `venv/Scripts/python.exe -m pytest tests/test_full_opportunity_engine_unlock.py tests/test_decision_frame_orchestration_paper_exploration_alpha.py tests/test_candidate_lifecycle_scorecard_seam.py tests/test_canonical_market_snapshot_decision_spine.py tests/test_runtime_dispatch_admission_telemetry.py tests/test_execution_spine_order_routing.py tests/test_f4a_decimal.py tests/test_execution_sr_decimal.py -q`

Final regression slice result: `94 passed`.

## Intended PAPER Smoke Command

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\Users\shahn\OneDrive\Desktop\poverty_killer\scripts\run_bounded_paper.ps1 -Run -ApproveAutonomousPaper -DurationSeconds 180 -Watchlist "BTC/USD,ETH/USD,SOL/USD" -PaperExplorationAlpha
```

Smoke status: not started. Native Windows PowerShell failed closed with `APCA_API_KEY_ID missing`. A second attempt mapped local `.env` `ALPACA_API_KEY` / `ALPACA_API_SECRET` into APCA process variables without printing secrets, but both local values are empty, so preflight failed closed again.

## Next Runtime Proof

Once Alpaca PAPER credentials are available to native Windows PowerShell, rerun the intended smoke command. Expected audit fields are active threshold profile, profile count, active thresholds, frame count, module evidence completeness, BUY/SELL/NO_TRADE counts, NetEdge allow/deny distribution, DecisionCompiler attempts, submit calls, broker posts, `/v2/orders`, live endpoint marker, real-money marker, mutation markers, local orders/fills/mappings/reservations, and stderr.
