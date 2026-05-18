# BUNDLE 25W - Whole-Bot Contribution Activation Harness

Verdict: PASS

25W added a seam-wide contribution activation harness. The harness proves that broker no-go context, protective intents, entry candidates/ranking evidence, economics advisory gaps, and intelligence/fusion evidence can coexist in one governed readiness decision without calling execution, submitting orders, activating live mode, or waking dormant economics veto authority.

This rerun used the existing 25W packet only. The Alpaca PAPER environment was present, the endpoint matched `https://paper-api.alpaca.markets`, and the real broker-network leg ran read-only against Alpaca PAPER. Offline broker snapshot fixtures still covered the required adversarial broker branches.

Changed files:
- `tests/test_whole_bot_contribution_activation_harness.py`
- `reports/bundle_25w_whole_bot_contribution_activation.md`

Tests run:
- `/tmp/pk25i-venv/bin/python -m pytest tests/test_whole_bot_contribution_activation_harness.py -q -s`
  - Initial sandboxed attempt reached the real broker leg but failed DNS before completing.
- `/tmp/pk25i-venv/bin/python -m pytest tests/test_whole_bot_contribution_activation_harness.py -q -s --tb=short`
  - `4 passed, 74 warnings in 5.81s`
- `/tmp/pk25i-venv/bin/python -m pytest tests/test_broker_truth_whole_bot_contribution_readiness.py tests/test_alpaca_paper_read_only_broker_truth.py tests/test_live_read_only_adapter_config_gate.py tests/test_integrated_paper_readiness.py tests/test_protective_capital_defense_spine.py tests/test_entry_expansion_spine.py tests/test_economic_truth_spine.py tests/test_intelligence_contribution_spine.py tests/test_durable_recovery_automation_spine.py tests/test_runtime_reservation_bootstrap.py -q`
  - `48 passed, 86 warnings in 12.62s`

Whole-bot contribution activation proven:
- Broker truth/no-go contribution:
  - Harness ran the real Alpaca PAPER read-only path.
  - `APCA_API_BASE_URL` matched the exact PAPER endpoint.
  - `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` were present and used from env vars only.
  - Offline snapshots prove clean flat broker context can support readiness context only, not order approval.
  - Broker open order without local mapping blocks readiness.
  - Broker position while local is flat blocks readiness.
  - Stale/missing broker snapshot blocks readiness.
  - Empty positions/open orders are valid broker truth.
- Protective enforcement contribution:
  - MovingFloor produces a governed protective-exit candidate.
  - HedgingFlow produces a governed hedge candidate only when exposure exists.
  - Recalibrator produces a freeze/block condition.
  - Protective freeze blocks new-entry readiness in the harness.
  - Protective contributors do not call ExecutionEngine, OrderRouter, PaperBroker, broker_adapter, or live_broker.
- Multi-contributor entry selection:
  - OpportunityRanking contributes ranking evidence only, with no allocation or execution authority.
  - GammaFront, AdaptiveDC, SectorRotation, and LiquidityVoid contribute governed candidate/vote metadata.
  - Conflicting entry contributors produce one readiness classification and no duplicate execution authority.
  - Ranking evidence alone cannot submit.
- Economics advisory contribution:
  - Passive fee/fill evidence can contribute advisory readiness metadata.
  - Missing `slippage_bps`, `arrival_price`, `expected_fill_price`, `net_pnl`, `net_edge`, and profitability evidence is carried as a gap.
  - Economics veto remains disabled.
  - NetEdgeGovernor and TradeEfficiencyGovernor remain dormant as veto authorities.
- Intelligence/fusion contribution:
  - Physical and toxicity evidence can support readiness.
  - Missing critical physical evidence produces a fusion veto/readiness block.
  - Intelligence/fusion evidence does not execute.
- Combined readiness scenarios:
  - Scenario A: clean broker context plus entry/intelligence/economics evidence returns eligible-for-governed-paper-decision-path, not order approval.
  - Scenario B: protective freeze blocks entry readiness.
  - Scenario C: broker open-order conflict blocks readiness and does not mutate broker state.
  - Scenario D: economics gap is recorded without profitability/net-edge claims or veto activation.
  - Scenario E: conflicting entry contributors are reduced to one readiness classification, not duplicate orders.

Adversarial cases proven:
- MovingFloor breach with no position does not create a fresh short; it blocks as `protective_intent_requires_existing_position`.
- Missing hedge exposure does not invent a hedge.
- Recalibrator freeze does not submit.
- Broker conflict blocks readiness without broker mutation.
- Missing critical physical evidence preserves hard-veto behavior.
- Ranking evidence alone cannot submit.
- Hidden economics veto activation is rejected as forbidden.

Contribution activation matrix:
- Active in governed readiness:
  - Broker read-only no-go context
  - Protective metadata/readiness intents
  - Entry candidate metadata and ranking evidence
  - Intelligence/fusion support or veto evidence
  - Economics advisory gap metadata
- Advisory/candidate only:
  - MovingFloor
  - HedgingFlow
  - Recalibrator
  - OpportunityRanking
  - GammaFront
  - AdaptiveDC
  - SectorRotation
  - LiquidityVoid
- Passive evidence only:
  - PaperBroker fee/fill evidence
  - FillRecorder-style economic telemetry
  - Missing economics fields recorded as gaps
- Dormant protected authority:
  - NetEdgeGovernor
  - TradeEfficiencyGovernor
  - broker_adapter
  - live_broker
- Blocked pending production wiring:
  - Governed production wiring for protective block/reduce/freeze/operator escalation.
  - Governed production wiring for multi-contributor entry selection.
  - Governed production wiring for economics advisory metadata before any veto authority.
  - Controlled paper-runtime loop evidence over real or replayed market data.
- Unsafe to activate now:
  - live mode
  - broker mutation
  - live reservation lifecycle
  - economics veto
  - direct protective execution

Remaining blockers:
- Repo still lacks production wiring that turns the governed activation model into a controlled paper-runtime contribution loop.
- Economics advisory is gap-reporting only until real slippage, arrival, expected fill, net PnL, net edge, and profitability evidence exists.

Recommended next packet:
- 25X - Controlled Paper Runtime Contribution Loop
- Why this is the single next seam:
  - 25W proves the activation harness model and adversarial blocks.
  - The next productive step is to run broker truth, protective contribution, entry selection, economics advisory, intelligence, and telemetry together over controlled paper-runtime or replayed market data.
  - This keeps one governed seam and still forbids live mode, broker mutation, economics veto activation, and duplicate execution authority.

Authority boundaries confirmed:
- Exact Alpaca PAPER endpoint required before broker calls.
- GET-only allowlist in the broker leg.
- `/v2/orders` allowed only with `status=open`.
- No POST/PATCH/DELETE.
- No order submit/cancel/replace.
- No production live runtime wiring.
- No dormant economics veto activation.

Confirmations:
- Production behavior changed: no
- If yes, exact helper only:
  - n/a
- Real broker/network call made: yes, Alpaca PAPER read-only only
- Credentials used: yes, env vars only, not written to files
- Secrets printed/written/committed: no in the final passing rerun and report; no secrets written or committed
- Live endpoint used: no
- Paper endpoint used: yes
- Orders/cancels/replaces: no
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
