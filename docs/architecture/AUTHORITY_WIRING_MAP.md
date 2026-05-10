# POVERTY_KILLER Authority Wiring Map

## Purpose

This file is durable context for future OpenCode and Supreme Board sessions.

It summarizes current authority ownership and wiring so future sessions do not redo the same full-repo audits.

Rule: Context spine gives direction. Repo truth gives proof.

## Active Production Spine

Current active spine:

main.py -> app/main_loop.py -> app/core/decision_compiler.py -> app/execution/engine.py -> app/execution/order_router.py -> app/execution/paper_broker.py

## Core Runtime Authority

| Authority | Current Owner | Current Status | Notes |
|---|---|---|---|
| Bootstrap / lifecycle | main.py | ACTIVE_PRODUCTION | Creates major engines and starts runtime |
| Runtime orchestration | app/main_loop.py | ACTIVE_PRODUCTION | Main operational loop and dispatch path |
| Symbol runtime | app/symbol_runtime.py | ACTIVE_PRODUCTION | Per-symbol runtime state and strategy/brain instances |
| Strategy dispatch | app/main_loop.py + app/strategies/strategy_router.py | ACTIVE_PRODUCTION | Main loop dispatches through router preference and sleeve branches |
| Signal fusion | app/brain/signal_fusion.py | ACTIVE_PRODUCTION | Fusion decision authority |
| Decision compilation | app/core/decision_compiler.py | ACTIVE_PRODUCTION | Decision UUID and record authority |
| Execution admission | app/execution/engine.py | ACTIVE_PRODUCTION | Converts strategy signal into order request |
| Order routing | app/execution/order_router.py | ACTIVE_PRODUCTION | Paper/live route authority |
| Paper execution | app/execution/paper_broker.py | ACTIVE_PRODUCTION | Paper fill simulation |
| Risk veto | app/risk/guard.py | ACTIVE_PRODUCTION | Main risk gate |
| Position sizing | app/risk/position_sizing.py | ACTIVE_PRODUCTION | Position size calculation |
| Telemetry persistence | app/telemetry/event_store.py | ACTIVE_PRODUCTION | Event persistence |
| Decision telemetry | app/telemetry/decision_recorder.py | ACTIVE_PRODUCTION | Decision event recording |
| Fill telemetry | app/telemetry/fill_recorder.py | ACTIVE_PRODUCTION | Fill/rejection event recording |

## Brain Authority

| Authority | Current Owner | Current Status | Notes |
|---|---|---|---|
| Regime detection | app/brain/regime_detector.py | ACTIVE_PRODUCTION | Alternate app/data/regime_detector.py requires reconciliation before use |
| Shans Curve | app/brain/shans_curve.py | ACTIVE_PRODUCTION | Protected differentiator |
| Whale flow | app/brain/whale_flow_engine.py | ACTIVE_PRODUCTION | Active; notional normalization addressed in earlier packet |
| Whale zone | app/brain/whale_zone_engine.py | PARTIALLY_WIRED | Do not claim active without more evidence |
| Sentiment velocity | app/brain/sentiment_velocity.py | ACTIVE_PRODUCTION | Protected differentiator |
| Entropy | app/brain/entropy_decoder.py | ACTIVE_PRODUCTION | Protected differentiator |
| Toxicity | app/brain/toxicity_engine.py | ACTIVE_PRODUCTION | Uses notional VPIN buckets after a8ce4fa |
| Physical validation | app/brain/physical_validator.py | ACTIVE_PRODUCTION | Fusion input |

## Strategy Authority

| Strategy / Sleeve | Current Owner | Current Status | Notes |
|---|---|---|---|
| ShadowFront | app/strategies/shadow_front.py | ACTIVE_PRODUCTION | Active dispatch-capable sleeve |
| SectorRotation | app/strategies/sector_rotation.py | PARTIALLY_WIRED | Observed-pair / paper-gated path |
| LiquidityVoid | app/strategies/liquidity_void.py | PARTIALLY_WIRED | Observed-pair / buffered paper-only path |
| GammaFront | app/strategies/gamma_front.py | ACTIVE_PRODUCTION / PARTIAL | Exists in dispatch path; entry data requirements may not be fully wired |
| MovingFloor | app/strategies/moving_floor.py | PRE_INTEGRATION_INTENTIONAL | Deferred protection/profit-defense module; do not wire without Board packet |

## Pre-Integration Authority Candidates

These are intentional future-engine modules. They must not be dismissed, deleted, or wired casually.

| Candidate | Current Owner | Intended Authority | Required Before Wiring |
|---|---|---|---|
| World awareness | app/world_awareness/* | Subordinate external context, not direct trading authority | Import safety, event schema, trust/decay, replay determinism |
| Market data adapter protocol | app/data/market_data_adapter.py | Future data adapter interface | Bridge to websocket/polling clients |
| Broker adapter protocol | app/execution/broker_adapter.py | Future broker abstraction | Bridge to OrderRouter/PaperBroker/live broker |
| Instrument profile | app/models/instrument_profile.py | Cross-asset instrument profile | Symbol/enum alignment |
| Market catalog/session/fees | app/markets/* | Market metadata substrate | Instrument registry alignment |
| Portfolio ranking | app/portfolio/* | Opportunity/portfolio ranking substrate | Portfolio truth contract |
| Cross-asset risk | app/risk/cross_asset_risk_model.py | Cross-asset risk modeling | Composition with HybridRiskGuard |
| NetEdge governor | app/risk/net_edge_governor.py | Economic admissibility kernel | Single-veto composition contract |
| TradeEfficiency governor | app/risk/trade_efficiency_governor.py | Sleeve/trade efficiency state machine | Single-veto composition contract |

## Duplicate Authority Risks

| Risk | Files | Board Position |
|---|---|---|
| Alternate execution/orchestration authority | app/execution/orchestrator.py vs active main/execution spine | Preserve but do not activate |
| Flat model shadowing | app/models.py vs app/models/ package | app/models.py is tombstone/preserved warning |
| Regime detector duplication | app/brain/regime_detector.py vs app/data/regime_detector.py | Active owner is app/brain/regime_detector.py |
| Risk authority overlap | app/risk/guard.py vs app/risk/unified_risk.py vs app/risk/safety.py vs future governors | No parallel veto without composition contract |
| Order contract split | app/models/contracts.py vs app/models/orders.py | Needs careful bridge if touched |
| Future broker abstraction | app/execution/broker_adapter.py vs app/execution/order_router.py | Protocol not active until reconciled |

## Contract Boundaries To Preserve

- Money/risk/order boundaries should use Decimal where required.
- Strategy/fusion/market-data analytics may use floats where analytical.
- Execution and risk authority must not be duplicated.
- Live mode is not approved.
- Paper mode is the proving lane.
- MovingFloor / NetEdge / TradeEfficiency runtime wiring is deferred until explicit Board packet.
- World awareness must remain subordinate context until authority contract is approved.

## Wiring Change Rule

Any packet changing one of these files is high authority:
- main.py
- app/main_loop.py
- app/core/decision_compiler.py
- app/execution/engine.py
- app/execution/order_router.py
- app/execution/paper_broker.py
- app/risk/guard.py
- app/brain/signal_fusion.py
- app/strategies/strategy_router.py
- app/models/contracts.py
- app/models/orders.py
- app/models/enums.py

High-authority packets require:
- exact file scope
- clear producer/consumer explanation
- targeted tests
- diff audit
- no broad refactor
- no same-tree parallel coding