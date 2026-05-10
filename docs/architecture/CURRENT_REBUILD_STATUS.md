# POVERTY_KILLER Current Rebuild Status

## Latest Pushed Master

Latest pushed master:
- ccd54bb - Thread decision UUID through order telemetry path
- 1fb2441 - Register world awareness pre-integration package
- ff5d0c7 - Fix collection syntax in legacy tests
- 868aa7b - Add architecture context spine
- f0bd38e - Add OpenCode Supreme Board governance
- a8ce4fa - Fix ToxicityEngine VPIN notional buckets
- f192725 - Relax SignalFusion noncritical input vetoes

## Current Stage

POVERTY_KILLER is in the 360 rebuild phase.

Current status:
- Core active runtime spine exists.
- Strategy/fusion/execution/paper path exists.
- Advanced modules are intentional pre-integration assets.
- Full quant engine integration is not complete.
- Evidence collection seam has been repaired.
- World-awareness package is now registered as PRE_INTEGRATION_INTENTIONAL.
- Live-money mode is not approved.

Plain-English status:
The engine has a working core spine and several advanced organs. Some advanced modules are registered and preserved but are not yet connected to the active trading bloodstream.

## Active Production Spine

Current active spine:

main.py -> app/main_loop.py -> app/core/decision_compiler.py -> app/execution/engine.py -> app/execution/order_router.py -> app/execution/paper_broker.py

High-authority active modules:
- app/brain/signal_fusion.py
- app/brain/regime_detector.py
- app/brain/shans_curve.py
- app/brain/whale_flow_engine.py
- app/brain/sentiment_velocity.py
- app/brain/entropy_decoder.py
- app/brain/toxicity_engine.py
- app/risk/guard.py
- app/risk/position_sizing.py
- app/telemetry/event_store.py
- app/telemetry/decision_recorder.py
- app/telemetry/fill_recorder.py

## Accepted Recent Packets

### Bundle 1 - Decision UUID Order Telemetry Seam

Status:
- PUSHED / CLOSED

Commit:
- ccd54bb - Thread decision UUID through order telemetry path

Accepted outcome:
- decision_uuid now threads from decision context into OrderRequest and order telemetry.
- Fill/rejection telemetry no longer relies on untyped getattr(order, "decision_uuid", None).
- Targeted tests passed: 41.
- Full collect-only passed: 718 tests collected.
- No live mode, risk weakening, strategy threshold change, or world-awareness activation.

### Bundle 0B - Evidence Collection Seam

Status:
- PUSHED / CLOSED

Commits:
- ff5d0c7 - Fix collection syntax in legacy tests
- 1fb2441 - Register world awareness pre-integration package

Accepted outcome:
- Legacy test files with escaped docstring corruption were repaired.
- app/world_awareness/ was registered as a preserved PRE_INTEGRATION_INTENTIONAL package.
- No world-awareness runtime activation was performed.
- No SignalFusion, risk, execution, main-loop, strategy, or live-mode wiring was changed.
- app/world_awareness/tests passed: 11/11.
- Full pytest collection passed: 718 tests collected.

### Architecture Context Spine Packet

Status:
- PUSHED / CLOSED

Commit:
- 868aa7b - Add architecture context spine

Accepted outcome:
- Durable repo memory created under docs/architecture.
- Future OpenCode sessions should read context spine before broad repo scans.
- Context spine gives direction; repo truth gives proof.

### OpenCode Supreme Board Governance Packet

Status:
- PUSHED / CLOSED

Commit:
- f0bd38e - Add OpenCode Supreme Board governance

Accepted outcome:
- OpenCode installed and working: 1.14.46.
- Auth works through ChatGPT/OpenAI.
- Working model: GPT-5.3 Codex.
- GPT-5.5 Pro was visible but rejected under the current ChatGPT/Codex auth route.
- Ctrl+Shift+V paste works in legacy PowerShell ConsoleHost.
- AGENTS.md added.
- .opencode scout and approved-builder agents added.
- docs/opencode governance prompts and parallelism policy added.
- Read-only smoke test passed.
- repo-map-scout test passed.

### Toxicity VPIN Notional Bucket Packet

Status:
- PUSHED / CLOSED

Commit:
- a8ce4fa - Fix ToxicityEngine VPIN notional buckets

Accepted outcome:
- ToxicityEngine VPIN trade buckets now use USD notional, not raw crypto units.
- BTC/XBT default bucket: 100,000 USD.
- ETH default bucket: 50,000 USD.
- SOL default bucket: 20,000 USD.
- fallback default bucket: 50,000 USD.
- legacy custom volume_bucket_units is honored as a notional bucket override.
- serialization advanced to v4 to preserve buy/sell notional bucket splits.
- fake 10k forced-finalize behavior was removed.
- targeted test passed: tests/test_toxicity_engine_vpin_notional.py 9/9.

## Current Known Bottlenecks

1. Contract surface seam
   - OrderIntent / OrderRequest / FillEvent / OrderFill relationships need reconciliation before deeper execution telemetry work.
   - decision_uuid propagation to fill telemetry remains an important candidate seam.

2. Adapter boundary seam
   - market_data_adapter.py and broker_adapter.py are intentional pre-integration contracts.
   - They must be reconciled with current websocket/polling and OrderRouter/PaperBroker paths before activation.

3. Authority composition seam
   - Active risk guard and future governors need composition rules before wiring.
   - NetEdgeGovernor, TradeEfficiencyGovernor, CrossAssetRiskModel, and MovingFloor are not to be activated casually.

4. World-awareness seam
   - app/world_awareness is now registered and tested.
   - It remains subordinate and non-authoritative.
   - It must not submit orders, override risk, bypass SignalFusion, or attach to live runtime without a future Board packet.

5. Dirty worktree containment
   - Other dirty/untracked files may exist.
   - Do not stage them without exact packet scope.

## Dirty Worktree Warning

The working tree may contain:
- modified runtime files
- generated state files
- telemetry databases
- reports
- proof artifacts
- intentional pre-integration modules
- deleted old docs/scripts

Do not run:
- git add .
- git add -A
- git reset
- git clean
- broad cleanup

Exact-file staging only.

## Current Board Doctrine

- Every repo file is presumed intentional until repo truth proves otherwise.
- Unwired does not mean junk.
- Untracked does not mean junk.
- Dirty does not mean junk.
- Dormant does not mean useless.
- Work must be seam-based, not isolated bug-fix driven.
- Context spine gives direction; repo truth gives proof.
- No live mode.
- No broad refactor.
- No duplicate authority.
- No fake integration.
- No deleting intentional modules without a Board packet.

## Next Recommended Rebuild Work

Next major seam:
- Bundle 1 - Contract Surface Reconciliation

Likely focus:
- OrderIntent vs OrderRequest
- FillEvent vs OrderFill
- StrategySignal vs StrategyVote
- FusionDecision vs compiled decision
- Decimal vs float boundaries
- timestamp authority
- decision_uuid propagation

Before coding:
- use OpenCode read-only architecture packet
- read context spine first
- inspect only active contract files and direct producers/consumers
- do not redo full repo scan