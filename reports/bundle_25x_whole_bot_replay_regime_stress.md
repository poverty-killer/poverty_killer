# BUNDLE 25X - Whole-Bot Replay / Regime Stress Harness

Verdict: PASS

Changed files:
- `tests/test_whole_bot_replay_regime_stress.py`
- `reports/bundle_25x_whole_bot_replay_regime_stress.md`

Tests run:
- `/tmp/pk25i-venv/bin/python -m pytest tests/test_whole_bot_replay_regime_stress.py -q -s --tb=short`
# result
  - `3 passed, 76 warnings in 5.49s`
- `/tmp/pk25i-venv/bin/python -m pytest tests/test_whole_bot_contribution_activation_harness.py tests/test_broker_truth_whole_bot_contribution_readiness.py tests/test_alpaca_paper_read_only_broker_truth.py tests/test_integrated_paper_readiness.py tests/test_protective_capital_defense_spine.py tests/test_entry_expansion_spine.py tests/test_economic_truth_spine.py tests/test_intelligence_contribution_spine.py tests/test_durable_recovery_automation_spine.py tests/test_runtime_reservation_bootstrap.py -q --tb=short`
# result
  - `46 passed, 88 warnings in 12.16s`

Whole-bot replay/regime stress proven:
- Quiet / no-trade regime:
  - Deterministic stress fixture with ranking metadata only classifies as neutral/no-go.
  - Low/missing executable entry evidence does not force entry.
  - No fake signal, no execution, no broker mutation.
- Trend-supportive regime:
  - GammaFront, AdaptiveDC, SectorRotation, LiquidityVoid, and OpportunityRanking can align as candidate/readiness evidence.
  - Candidate evidence remains governed metadata.
  - Classification is eligible for governed paper decision path, not order approved.
- Choppy / conflicting contributor regime:
  - Opposing entry contributor directions classify as neutral/no-go.
  - Ranking/candidate/advisory evidence remains metadata.
  - Duplicate authority is not created.
- Protective breach / capital defense regime:
  - MovingFloor, HedgingFlow, and Recalibrator protective intents block/freeze entry readiness.
  - Protective exit/hedge remains candidate/intent.
  - Protective modules do not open fresh entries or execute.
- Stale or missing critical data regime:
  - Missing physical evidence hard-vetoes through SignalFusion.
  - Stale toxicity evidence hard-vetoes through SignalFusion.
  - Noncritical missing contributor evidence neutralizes instead of faking confidence.
- Broker truth conflict regime:
  - Broker open order without local mapping blocks readiness.
  - Broker position while local is flat blocks readiness.
  - Stale broker snapshot blocks readiness.
  - Empty positions/open orders are valid broker truth.
  - Alpaca PAPER read-only GET path ran when env/network were available.
- Economics gap regime:
  - Missing `slippage_bps`, `arrival_price`, `expected_fill_price`, `net_pnl`, `net_edge`, and profitability are explicit gaps.
  - NetEdgeGovernor and TradeEfficiencyGovernor remain dormant.
  - No PnL, net edge, or profitability is invented.
- Recovery / restart regime:
  - SymbolRuntime recovery remains symbol-local.
  - Missing contributor state neutralizes/fails closed.
  - Stale recovered symbol state fails closed.
  - Restart does not auto-arm live mode or create duplicate reservations.
- Timing / latency observation:
  - Harness records available deterministic timing points: fixture exchange timestamp, snapshot receive timestamp, and decision evaluation timestamp.
  - Decision-flow latency instrumentation is absent and classified as a future performance packet.
  - No latency metric is invented.

Adversarial cases proven:
- Trend candidate with protective freeze blocks as protective block/freeze.
- Entry support with stale critical data hard-vetoes.
- High ranking with broker open-order conflict blocks readiness.
- Candidate with missing economics truth records explicit economics gap.
- Conflicting contributors classify neutral/no-go.
- Missing symbol runtime contributor state after restart neutralizes/fails closed.
- Stale broker read snapshot blocks readiness.
- Attempted duplicate candidate authority is rejected.
- Attempted economics veto activation remains false and is blocked.
- Attempted fake PnL/net-edge claim is blocked.
- Broker/live mutation surfaces remain absent from protected contributor and recovery sources.

What this does NOT prove:
- Profitability.
- Alpha quality.
- Sharpe.
- Expectancy.
- Real live readiness.
- Slippage-adjusted edge.
- Production order readiness.
- That deterministic stress fixtures equal market proof.

Remaining empirical gaps:
- Real historical replay depth.
- Decision-flow latency measurement.
- Profitability metrics.
- Slippage, arrival price, net PnL, and net edge evidence.
- Live/order mutation proof remains intentionally absent.
- Production controlled paper-runtime contribution loop remains future work.

Recommended next packet:
- 25Y - Historical Replay Evidence Depth Harness
- Why this is the single next seam:
  - 25X proves deterministic behavioral safety across regimes and adverse cases.
  - The next useful seam is deeper replay coverage over real historical/replayed market data while preserving no-live, no-mutation, no-profitability-claim boundaries.
  - Latency optimization should wait until historical replay depth and timing instrumentation are present.

Authority boundaries confirmed:
- Deterministic replay fixtures are stress inputs only, not real performance evidence.
- Alpaca PAPER endpoint only.
- GET-only broker read path.
- `/v2/orders` allowed only with `status=open`.
- No POST/PATCH/DELETE.
- No order submit/cancel/replace.
- No live endpoint.
- No live mode.
- No broker_adapter/live_broker activation.
- No dormant economics veto activation.
- No StrategyAllocator/SovereignGovernor/SovereignExecutionGuard activation.
- No thresholds changed.
- No production runtime wiring.

Confirmations:
- Production behavior changed: no
- If yes, exact helper only:
  - n/a
- Real broker/network call made: yes, Alpaca PAPER read-only only
- Credentials used: yes, env vars only
- Secrets printed/written/committed: no
- Live endpoint used: no
- Paper endpoint used: yes
- Order placed: no
- Cancel sent: no
- Replace sent: no
- HTTP methods used:
  - GET only
- Live mode used: no
- broker_adapter edited/activated: no
- live_broker edited/activated: no
- Live reservation lifecycle activated: no
- Dormant governors activated: no
- Economics veto activated: no
- Thresholds changed: no
- Routing/execution broadened: no
- Duplicate authority introduced: no
- Git staging/commit/push/reset/clean/stash/delete: none
