# POVERTY_KILLER Seam Activation Queue

## Purpose

This file keeps the rebuild seam-based.

Do not fix isolated bugs unless they belong to an approved seam.

The correct rebuild unit is:

seam -> authority -> contract -> wiring -> tests -> proof

## Current Doctrine

- Every repo file is presumed intentional until repo truth proves otherwise.
- Unwired does not mean junk.
- Pre-integration modules must be preserved.
- No live mode.
- No duplicate authority.
- No broad cleanup.
- Exact-file staging only.
- Context spine gives direction; repo truth gives proof.
- Future OpenCode sessions must read the context spine before broad repo scans.

## Bundle 0 - Evidence and Module Registry Foundation

Status: PARTIALLY CLOSED

Closed:
- Architecture context spine created in commit 868aa7b.
- Evidence / collection seam repaired in commits ff5d0c7 and 1fb2441.
- Escaped docstring syntax corruption repaired in 12 legacy test files.
- app/world_awareness registered as PRE_INTEGRATION_INTENTIONAL in commit 1fb2441.
- app/world_awareness/tests passed 11/11.
- Full pytest collection passed: 718 tests collected.
- No world-awareness runtime activation was performed.
- No SignalFusion, risk, execution, main-loop, strategy, or live-mode wiring was changed.

Remaining:
- Contract surface reconciliation.
- Authority and adapter boundary clarification.
- Context spine update after each future packet.

Purpose:
Create trustworthy repo evidence and durable module memory before more runtime wiring.

Seams:
- evidence / collection seam: CLOSED
- module-intent registry seam: ACTIVE / MAINTAIN
- authority/wiring map seam: ACTIVE / MAINTAIN
- generated artifact containment seam: ACTIVE / MAINTAIN

Must not do:
- activate world-awareness without future Board packet
- wire MovingFloor
- wire NetEdge or TradeEfficiency
- change live mode
- delete intentional modules
- broad cleanup

Verification baseline:
- app/world_awareness/tests: 11 passed
- python -m pytest --collect-only -q: 718 tests collected
- git diff --check passed for closed Bundle 0B files

## Contract Surface Reconciliation Seam

Status: NEXT RECOMMENDED REBUILD WORK

Purpose:
Clarify the core model and event contracts before wiring more modules.

Likely files:
- app/models/contracts.py
- app/models/orders.py
- app/models/signals.py
- app/models/fusion.py
- app/models/enums.py
- app/utils/decimal_utils.py
- app/core/decision_compiler.py, read-only first
- app/execution/engine.py, read-only first
- app/execution/order_router.py, read-only first
- app/telemetry/fill_recorder.py, read-only first
- app/telemetry/decision_recorder.py, read-only first

Must decide:
- OrderIntent vs OrderRequest relationship
- FillEvent vs OrderFill relationship
- StrategySignal vs StrategyVote relationship
- FusionDecision vs compiled decision relationship
- timestamp authority
- Decimal vs float boundaries
- decision_uuid propagation
- whether fill telemetry needs metadata, model field, or router-state threading

Must not do:
- weaken execution gates
- fake fill evidence
- bypass risk or router
- broaden into adapter activation
- alter live mode

## Adapter Contract Seam

Status: WAITING FOR CONTRACT SURFACE RECONCILIATION

Purpose:
Prepare lawful integration of future data and broker adapters without replacing active production paths prematurely.

Likely files:
- app/data/market_data_adapter.py
- app/execution/broker_adapter.py
- app/data/websocket_client.py
- app/data/polling_client.py
- app/execution/order_router.py
- app/execution/paper_broker.py
- app/models/*

Must decide:
- canonical data adapter contract
- broker adapter contract
- enum mapping
- Decimal/money boundaries
- replay and timestamp requirements
- whether adapters are subordinate to active clients/routers or become future interfaces

Must not do:
- replace active data feed abruptly
- bypass OrderRouter
- introduce live broker behavior
- wire adapter protocols into runtime without tests

## Telemetry and Fill Evidence Seam

Status: AFTER CONTRACT SURFACE RECONCILIATION

Purpose:
Make fill/decision telemetry reliable enough to prove signal-to-fill behavior.

Known issue candidate:
- FillEvent decision_uuid appears required while active OrderRequest may not carry decision_uuid.

Likely files:
- app/core/decision_compiler.py
- app/execution/engine.py
- app/execution/order_router.py
- app/execution/paper_broker.py
- app/models/orders.py
- app/models/contracts.py
- app/telemetry/fill_recorder.py
- app/telemetry/decision_recorder.py
- tests covering paper fills and dispatch

Must prove:
- decision created
- signal submitted
- order routed
- paper broker reached
- fill recorded
- fill links back to decision_uuid

Must not do:
- weaken execution gates
- fake fill evidence
- bypass risk or router
- alter live mode

## World Awareness Seam

Status: REGISTERED / PRESERVED / NOT ACTIVE AUTHORITY

Purpose:
Connect world-awareness as subordinate external context without giving it order or risk authority.

Current state:
- app/world_awareness is now registered in commit 1fb2441.
- app/world_awareness/tests passed 11/11.
- Full pytest collection passed after registration.
- Package is PRE_INTEGRATION_INTENTIONAL.
- Package is not active trading authority.

Likely files:
- app/world_awareness/*
- app/telemetry/*
- app/models/* for event contracts if needed
- app/brain/signal_fusion.py only if later approved
- app/main_loop.py only if later approved

Prerequisites:
- event schema
- trust/decay semantics
- timestamp authority
- replay determinism
- no hidden order authority
- no hidden risk authority
- no live consumer attachment unless Board-approved

Must not do:
- let world-awareness directly submit orders
- let world-awareness directly override risk
- let world-awareness bypass SignalFusion
- wire it into live path without paper-only proof
- convert it from subordinate context into decision authority without a contract packet

## Economic / Risk Governor Composition Seam

Status: DEFERRED UNTIL EVIDENCE AND CONTRACTS ARE READY

Purpose:
Compose active risk guard with economic/risk governors without duplicate veto authority.

Likely files:
- app/risk/guard.py
- app/risk/cross_asset_risk_model.py
- app/risk/net_edge_governor.py
- app/risk/trade_efficiency_governor.py
- app/execution/engine.py
- app/models/*

Prerequisites:
- single final risk/admission authority
- deterministic composition formula
- telemetry evidence
- paper-only proof
- clear relationship to active HybridRiskGuard

Must not do:
- create parallel veto systems
- weaken current HybridRiskGuard
- bypass execution admission
- activate Bundle 3 protection wiring before prolonged paper evidence

## MovingFloor / Protection Seam

Status: PROTECTED / DEFERRED

Purpose:
MovingFloor is a protection/profit-defense organ, not a random strategy patch.

Likely files:
- app/strategies/moving_floor.py
- app/risk/*
- app/main_loop.py
- app/brain/signal_fusion.py only if approved
- tests for protection behavior

Prerequisites:
- prolonged paper-run evidence
- clear output contract
- no fresh short authority unless explicitly approved
- no risk weakening
- no bypassing existing protections

Must not do:
- wire MovingFloor casually
- touch Bundle 3 protection stack before Board approval
- change live risk behavior
- add fresh short authority unless explicitly approved

## Portfolio Truth Seam

Status: PARTIALLY PRESENT, NOT NEXT

Purpose:
Make portfolio truth, opportunity ranking, and reconciliation trustworthy across assets.

Likely files:
- app/core/truth_kernel.py
- app/core/truth_reconciler.py
- app/portfolio/*
- app/models/contracts.py
- app/main_loop.py
- app/execution/paper_broker.py
- app/telemetry/fill_recorder.py

Prerequisites:
- active fill telemetry reliability
- position and cash truth clarity
- reconciliation tests
- generated artifact containment
- clear relationship between fills and portfolio truth

## Strategy Dispatch Seam

Status: ACTIVE BUT STILL MATURING

Purpose:
Ensure all strategy sleeves emit lawful signals/votes and dispatch through one authority.

Current sleeves:
- ShadowFront
- SectorRotation
- LiquidityVoid
- GammaFront
- MovingFloor deferred

Must preserve:
- StrategyRouter authority
- SignalFusion authority
- same-candle/freshness gates unless explicitly changed
- paper-only proof gates for partially wired sleeves

Must not do:
- fake observed pairs
- bypass SignalFusion
- bypass StrategyRouter
- force signal submission
- weaken freshness gates to hide bugs

## Long Paper Proof Seam

Status: FUTURE

Purpose:
Prepare and run prolonged paper proof only after contract, telemetry, risk, and execution seams are reliable.

Prerequisites:
- collect-only remains clean
- signal-to-paper-fill proof works
- fill telemetry links to decision_uuid
- risk state persistence is stable
- no live-mode leakage
- report generation is reliable

Must not do:
- run live mode
- run broad proof before evidence seams are stable
- treat paper profit alone as sufficient proof

## Session Rule

At the start of every OpenCode session:
1. Read CURRENT_REBUILD_STATUS.md.
2. Read SESSION_CHANGELOG.md.
3. Read DO_NOT_REPEAT_AUDITS.md.
4. Read only relevant sections of MODULE_INTENT_REGISTRY.md and AUTHORITY_WIRING_MAP.md.
5. Read SEAM_ACTIVATION_QUEUE.md for dependency order.
6. Do not redo full repo scans unless the active packet requires it.
7. Inspect changed files, UNKNOWN items, and active packet scope only.

## End-of-Packet Rule

After every accepted audit/edit/commit/push:
1. Update CURRENT_REBUILD_STATUS.md if project status changed.
2. Update SESSION_CHANGELOG.md with commits and accepted evidence.
3. Update MODULE_INTENT_REGISTRY.md if classification changed.
4. Update AUTHORITY_WIRING_MAP.md if wiring/authority changed.
5. Update SEAM_ACTIVATION_QUEUE.md if dependency order changed.
6. Update OPEN_QUESTIONS.md when questions are answered or new questions appear.
7. Do not let context spine drift behind repo truth.