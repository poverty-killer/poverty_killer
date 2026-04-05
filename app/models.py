"""
app/models.py — DEAD FILE / GOVERNANCE TOMBSTONE

This file is permanently shadowed by the app/models/ package directory.
CPython always binds 'app.models' to the package; this file is never loaded.

DO NOT add imports, model definitions, or logic here.
DO NOT attempt to use this file as a compatibility shim.

All canonical model definitions live in the governed package:

    app/models/__init__.py      — canonical public API
    app/models/contracts.py     — EventEnvelope, TruthFrame, OrderIntent, FillEvent, ...
    app/models/enums.py         — RegimeType, OrderSide, EventType, ControlMode, ...
    app/models/signals.py       — DarkPoolPrint, OptionsFlow, StrategySignal
    app/models/fusion.py        — FusionDecision
    app/models/market_data.py   — Candle, OrderBookSnapshot, LiquidityMetrics,
                                  PhysicalVerification, WhaleFlowScore, EntropyScore
    app/models/events.py        — BaseEvent, TradeEvent, QuoteEvent, OrderBookSnapshotEvent, ...
    app/models/invariants.py    — NormalInvariant, KillSwitchInvariant, ...

Orphaned legacy symbols (defined here only, never accessible):
    ControlCommand, SystemStatus, OrderRequest, OrderFill,
    RiskSnapshot, HealthSnapshot, PositionRecord, TradeRecord,
    DailySummary, SentimentVelocity, CurvatureSignal, LARSignal,
    MarketMemorySignal, TopologicalSignal

Importers that reference these orphaned symbols are pre-existing broken paths
outside the governed rebuild tranche and must be addressed in a future bounded pass:
    app/control_plane.py
    app/execution/engine.py
    app/execution/order_router.py
    app/execution/orchestrator.py
    app/snapshot_exporter.py
    app/strategies/liquidity_void.py
    app/strategies/shadow_front.py
"""