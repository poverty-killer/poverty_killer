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

## Bundle 0 - Evidence and Module Registry Foundation

Status: NEXT FOUNDATION WORK

Purpose:
Create trustworthy repo evidence and durable module memory before more runtime wiring.

Seams:
- evidence / collection seam
- module-intent registry seam
- authority/wiring map seam
- generated artifact containment seam

Likely work:
- make pytest collect-only pass
- preserve intentional pre-integration modules
- document module classifications
- document active authority owners
- document next activation order

Must not do:
- activate world-awareness
- wire MovingFloor
- wire NetEdge or TradeEfficiency
- change live mode
- delete intentional modules
- broad cleanup

Verification:
- python -m pytest --collect-only -q
- git diff --check
- exact-file diff review

## Adapter Contract Seam

Status: WAITING FOR BUNDLE 0

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

Must not do:
- replace active data feed abruptly
- bypass OrderRouter
- introduce live broker behavior

## Telemetry and Fill Evidence Seam

Status: AFTER EVIDENCE SEAM

Purpose:
Make fill/decision telemetry reliable enough to prove signal-to-fill behavior.

Known issue candidate:
- FillEvent decision_uuid appears required while active OrderRequest may not carry decision_uuid.

Likely files:
- app/execution/engine.py
- app/execution/order_router.py
- app/models/orders.py
- app/models/contracts.py
- app/telemetry/fill_recorder.py
- app/telemetry/decision_recorder.py
- tests covering paper fills and dispatch

Must not do:
- weaken execution gates
- fake fill evidence
- bypass risk or router

## World Awareness Seam

Status: PRESERVED, NOT ACTIVE AUTHORITY

Purpose:
Connect world-awareness as subordinate external context without giving it order or risk authority.

Likely files:
- app/world_awareness/*
- app/telemetry/*
- app/brain/signal_fusion.py only if later approved
- app/models/* for event contracts if needed

Prerequisites:
- import safety
- event schema
- trust/decay semantics
- timestamp authority
- replay determinism
- no hidden order authority
- no hidden risk authority

Must not do:
- let world-awareness directly submit orders
- let world-awareness directly override risk
- wire it into live path without paper-only proof

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

Prerequisites:
- active fill telemetry reliability
- position and cash truth clarity
- reconciliation tests
- generated artifact containment

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

## Session Rule

At the start of every OpenCode session:
1. Read CURRENT_REBUILD_STATUS.md.
2. Read SESSION_CHANGELOG.md.
3. Read DO_NOT_REPEAT_AUDITS.md.
4. Read only relevant sections of MODULE_INTENT_REGISTRY.md and AUTHORITY_WIRING_MAP.md.
5. Do not redo full repo scans unless the active packet requires it.