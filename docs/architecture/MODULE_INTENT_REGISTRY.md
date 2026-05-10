# POVERTY_KILLER Module Intent Registry

## Classification Labels

- ACTIVE_PRODUCTION: currently wired into the active runtime path.
- PARTIALLY_WIRED: present and partly connected, but not fully active or proven.
- PRE_INTEGRATION_INTENTIONAL: intentional future-engine asset, not yet wired into active runtime.
- TEST_ONLY: tests, harnesses, or proof scripts.
- GENERATED_RUNTIME_ARTIFACT: state, reports, databases, logs, temporary runtime outputs.
- DUPLICATE_AUTHORITY_RISK: module overlaps with an existing authority and must not be activated casually.
- DEPRECATED_BUT_PRESERVED: intentionally retained tombstone, shim, or retired path.
- UNKNOWN_REQUIRES_EVIDENCE: purpose or wiring unclear; requires further read-only inspection.

## Board Doctrine

Every repo file is presumed intentional until repo truth proves otherwise.

Unwired does not mean junk.
Untracked does not mean junk.
Dirty does not mean junk.
Dormant does not mean useless.

This registry is guidance. Repo truth remains proof.

## Active Production Spine

| Path | Classification | Intended Purpose | Current Wiring | Notes |
|---|---|---|---|---|
| main.py | ACTIVE_PRODUCTION | Bootstrap, lifecycle, feed setup, runtime assembly | Active entry path | High authority |
| app/main_loop.py | ACTIVE_PRODUCTION | Runtime orchestration, strategy/fusion/dispatch loop | Active spine | High authority |
| app/core/decision_compiler.py | ACTIVE_PRODUCTION | Decision UUID and decision record authority | Active before execution submit | High authority |
| app/execution/engine.py | ACTIVE_PRODUCTION | Execution admission, validation, signal-to-order conversion | Active execution path | High authority |
| app/execution/order_router.py | ACTIVE_PRODUCTION | Paper/live routing and exchange adapter authority | Active router path | High authority |
| app/execution/paper_broker.py | ACTIVE_PRODUCTION | Paper execution simulation and fills | Active in paper mode | High authority |

## Active Brain / Signal Modules

| Path | Classification | Intended Purpose | Current Wiring | Notes |
|---|---|---|---|---|
| app/brain/signal_fusion.py | ACTIVE_PRODUCTION | Fuse brain inputs into decisions | Active | Protected authority |
| app/brain/regime_detector.py | ACTIVE_PRODUCTION | Market regime detection | Active | Alternate detector exists under app/data |
| app/brain/shans_curve.py | ACTIVE_PRODUCTION | Shans Curve authority | Active | Protected differentiator |
| app/brain/whale_flow_engine.py | ACTIVE_PRODUCTION | Whale flow scoring | Active | Price/notional normalization recently addressed |
| app/brain/whale_zone_engine.py | PARTIALLY_WIRED | Whale zone analysis | Wiring not fully proven | Needs evidence before activation claims |
| app/brain/sentiment_velocity.py | ACTIVE_PRODUCTION | Sentiment velocity / acceleration | Active through runtime | Protected differentiator |
| app/brain/entropy_decoder.py | ACTIVE_PRODUCTION | Entropy decoding | Active | Protected differentiator |
| app/brain/toxicity_engine.py | ACTIVE_PRODUCTION | Market toxicity and VPIN-style notional flow toxicity | Active | VPIN notional bucket packet closed |
| app/brain/physical_validator.py | ACTIVE_PRODUCTION | Physical market verification / latency plausibility | Active | Fusion input |

## Active Risk / Telemetry / Data Modules

| Path | Classification | Intended Purpose | Current Wiring | Notes |
|---|---|---|---|---|
| app/risk/guard.py | ACTIVE_PRODUCTION | Main risk veto and risk-state persistence | Active execution gate | High authority |
| app/risk/position_sizing.py | ACTIVE_PRODUCTION | Position sizing | Active for strategy sizing | High authority |
| app/risk/unified_risk.py | PARTIALLY_WIRED | Constitutional/unified risk layer | Active path unclear | Needs authority clarification |
| app/risk/safety.py | PARTIALLY_WIRED | Safety policy/gates | Active path unclear | Must not duplicate risk guard |
| app/data/websocket_client.py | ACTIVE_PRODUCTION | Websocket market data feed | Active | Runtime data authority |
| app/data/polling_client.py | ACTIVE_PRODUCTION | REST fallback polling feed | Active | Dirty worktree file; do not stage without packet |
| app/telemetry/event_store.py | ACTIVE_PRODUCTION | Telemetry persistence | Active | World-aware evidence foundation |
| app/telemetry/decision_recorder.py | ACTIVE_PRODUCTION | Decision telemetry | Active through compiler | Evidence layer |
| app/telemetry/fill_recorder.py | ACTIVE_PRODUCTION | Fill/rejection telemetry | Active through router | Possible decision_uuid seam |
| app/telemetry/feature_recorder.py | PARTIALLY_WIRED | Feature telemetry | Limited active producer evidence | Needs evidence |

## Intentional Pre-Integration Assets

These files are not junk. They are future-engine organs and must be preserved unless a separate Board packet proves otherwise.

| Path | Classification | Intended Purpose | Current Wiring | Activation Prerequisites |
|---|---|---|---|---|
| app/world_awareness/* | PRE_INTEGRATION_INTENTIONAL | External/world context subsystem | Not active runtime authority | Import safety, event schema, trust/decay contract, replay determinism |
| app/data/market_data_adapter.py | PRE_INTEGRATION_INTENTIONAL | Future market data adapter protocol | Not active spine | Bridge to current websocket/polling contracts |
| app/execution/broker_adapter.py | PRE_INTEGRATION_INTENTIONAL | Future broker adapter protocol | Not active spine | Bridge to OrderRouter/PaperBroker/live broker contracts |
| app/models/instrument_profile.py | PRE_INTEGRATION_INTENTIONAL | Universal instrument profile | Not active spine | Symbol/enum alignment |
| app/markets/* | PRE_INTEGRATION_INTENTIONAL | Market catalog, fee models, session calendar, instrument qualification | Not active spine | Instrument registry alignment |
| app/portfolio/* | PRE_INTEGRATION_INTENTIONAL | Portfolio/opportunity ranking substrate | Not active spine | Portfolio truth contract |
| app/risk/cross_asset_risk_model.py | PRE_INTEGRATION_INTENTIONAL | Cross-asset risk model | Not active spine | Composition with HybridRiskGuard |
| app/risk/net_edge_governor.py | PRE_INTEGRATION_INTENTIONAL | Economic admissibility kernel | Not active spine | Single-veto composition contract |
| app/risk/trade_efficiency_governor.py | PRE_INTEGRATION_INTENTIONAL | Trade/sleeve efficiency governor | Not active spine | Single-veto composition contract |
| app/strategies/moving_floor.py | PRE_INTEGRATION_INTENTIONAL | Protection / moving floor / profit defense module | Not active spine | Deferred until prolonged paper data unless Board exception |

## Duplicate / Preserved Authority Risks

| Path | Classification | Purpose | Board Position |
|---|---|---|---|
| app/execution/orchestrator.py | DEPRECATED_BUT_PRESERVED, DUPLICATE_AUTHORITY_RISK | Old/alternate orchestration path | Do not activate; preserve unless Board decides |
| app/models.py | DEPRECATED_BUT_PRESERVED, DUPLICATE_AUTHORITY_RISK | Tombstone warning against old flat model module | Preserve as warning |
| app/data/regime_detector.py | DUPLICATE_AUTHORITY_RISK | Alternate regime detector | Do not activate unless reconciled with app/brain/regime_detector.py |
| app/utils/enums.py | DEPRECATED_BUT_PRESERVED | Enum re-export shim | Preserve shim; canonical enums live in app/models/enums.py |
| app/constants.py | ACTIVE_PRODUCTION / shim | Constants and enum compatibility shim | Do not duplicate enum authority |

## Test and Artifact Classification

| Path | Classification | Notes |
|---|---|---|
| tests/* | TEST_ONLY | Some tests are strong, some are placeholders or collection-broken |
| tests/run_*_proof.ps1 | TEST_ONLY | Packet-scoped proof scripts |
| tests/harness_live_spine.py | TEST_ONLY | Harness/proof tool |
| state/* | GENERATED_RUNTIME_ARTIFACT | Do not stage unless packet-scoped |
| data/*.db* | GENERATED_RUNTIME_ARTIFACT | Telemetry/runtime databases; do not stage |
| reports/* | GENERATED_RUNTIME_ARTIFACT | Proof/report output; do not stage by default |

## Registry Maintenance Rule

Update this file when:
- a module changes classification
- a pre-integration asset becomes partially wired
- a partially wired asset becomes active production
- duplicate authority is resolved
- a new major module is added
- a Board audit changes intended purpose
