# cross_asset_reference_scan

Populated from live repo reads. Scan date: 2026-05-04.

---

## Scope

9 modules scanned for import classification and cross-asset pattern type.

Import classification key:
- PRODUCTION_IMPORTED: imported by at least one non-test production file
- TEST_ONLY_IMPORTED: imported only by test files or internal package tests
- NOT_IMPORTED: no Python file imports this module (confirmed via rg scan)
- UNKNOWN_NEEDS_MANUAL_REVIEW: ambiguous; manual inspection required

Cross-asset pattern type key:
- ISOLATED: per-symbol only, no cross-symbol logic
- CROSS_ASSET_READ: reads/models multiple instruments, no shared state write
- CROSS_ASSET_WRITE: writes shared state across symbols
- PORTFOLIO_LEVEL: intentional portfolio-wide aggregation

---

## Scan results

| Module | Import classification | Pattern type | Status | Notes |
|---|---|---|---|---|
| app/markets/default_instruments.py | NOT_IMPORTED | PORTFOLIO_LEVEL | PRE-INTEGRATION NO_LIVE_WIRING | Static InstrumentProfile for crypto/equities/ETFs/futures. Only BTC/USD ETH/USD SOL/USD enabled. No runtime imports. |
| app/markets/fee_models.py | NOT_IMPORTED | CROSS_ASSET_READ | PRE-INTEGRATION NO_LIVE_WIRING | Per-market fee schedules: maker/taker/spread/impact/borrow/funding. Decimal throughout. No runtime imports. |
| app/markets/instrument_qualifier.py | NOT_IMPORTED | CROSS_ASSET_READ | PRE-INTEGRATION NO_LIVE_WIRING | Referenced in instrument_profile.py docstring only (not an import). Gates instruments by ADV/spread/depth/volatility/session. No runtime imports. |
| app/markets/session_calendar.py | NOT_IMPORTED | CROSS_ASSET_READ | PRE-INTEGRATION NO_LIVE_WIRING | Multi-venue session/auction/halt/roll calendar. Deterministic given exchange_ts_ns. Holiday and futures calendars are provisional stubs. |
| app/portfolio/opportunity_ranking.py | NOT_IMPORTED | PORTFOLIO_LEVEL | PRE-INTEGRATION NO_ALLOCATION_AUTHORITY | Cross-asset opportunity scoring by expected net edge after costs/correlation/drawdown. No allocation or execution authority. |
| app/risk/cross_asset_risk_model.py | NOT_IMPORTED | PORTFOLIO_LEVEL | PRE-INTEGRATION NO_RISK_AUTHORITY | Cross-asset exposure/correlation/concentration/capacity models. Explicit design constraint: no imports from HybridRiskGuard or UnifiedRisk. No risk authority. |
| app/world_awareness/__init__.py | TEST_ONLY_IMPORTED | CROSS_ASSET_READ | PRE-INTEGRATION NO_LIVE_CONSUMER | External imports (from app.world_awareness) found only in app/world_awareness/tests/. No production caller outside the package. No TruthFrame/strategy/risk/execution authority. |
| app/instrument_registry.py | PRODUCTION_IMPORTED | CROSS_ASSET_READ | PRODUCTION_ACTIVE | Imported by main.py, app/models/unified_market.py, app/execution/orchestrator.py, tests/test_symbol_slash_form_contract.py. Multi-market metadata registry (crypto/equity/ETF/futures). InstrumentSpec uses float for min_size/step_size (F4A concern, out of scope for G0). |
| app/session_manager.py | NOT_IMPORTED | CROSS_ASSET_READ | DISCONNECTED | Reference in unified_market.py line 457 is a comment only. No actual import found. Manages sessions for crypto/equities/futures. Uses pytz and optional holidays library. |

---

## CROSS_ASSET_WRITE findings

None found in any of the 9 scanned modules.

All cross-asset logic is CROSS_ASSET_READ or PORTFOLIO_LEVEL (passive models or read-only registries).

No BOARD_ESCALATION: CROSS_ASSET_WRITE_IN_UNAUTHORIZED_MODULE required.

---

## Pre-integration module summary

7 of 9 modules are pre-integration passive models with no live wiring:
- app/markets/default_instruments.py
- app/markets/fee_models.py
- app/markets/instrument_qualifier.py
- app/markets/session_calendar.py
- app/portfolio/opportunity_ranking.py
- app/risk/cross_asset_risk_model.py
- app/world_awareness/__init__.py (test-only attachment)

1 module is PRODUCTION_IMPORTED and active:
- app/instrument_registry.py

1 module is disconnected (comment reference only):
- app/session_manager.py

---

## Out-of-scope findings for future bundles

1. app/instrument_registry.py: InstrumentSpec uses float for min_size and step_size.
   Decimal discipline check required in F4A or a dedicated bundle.

2. app/session_manager.py: NOT_IMPORTED despite being referenced in unified_market.py comment.
   Liveness decision (wire or retire) requires Board instruction.

3. app/world_awareness/__init__.py: No production caller outside the package.
   Consumer attachment decision requires Board instruction before any production wiring.
