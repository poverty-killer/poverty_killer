# POVERTY_KILLER Open Questions

## Purpose

This file tracks unresolved questions so future OpenCode sessions do not repeat broad audits.

Only inspect files related to these questions or files changed since the last checkpoint.

## Evidence / Collection Questions

Closed:
- Bundle 0B repaired the collection seam.
- Legacy escaped docstring corruption was repaired in 12 test files.
- app/world_awareness was registered as PRE_INTEGRATION_INTENTIONAL.
- app/world_awareness/tests passed 11/11.
- Full pytest collection passed: 718 tests collected.

Remaining:
- Keep collection clean after every future packet.
- If new collection errors appear, classify them by seam before editing.

## Authority Questions

- What is the final relationship between `app/risk/guard.py`, `app/risk/unified_risk.py`, `app/risk/safety.py`, `app/risk/net_edge_governor.py`, and `app/risk/trade_efficiency_governor.py`?
- What is the final relationship between `app/execution/order_router.py` and `app/execution/broker_adapter.py`?
- What is the final relationship between current data clients and `app/data/market_data_adapter.py`?
- Should `app/data/regime_detector.py` remain dormant, become a data-layer helper, or be deprecated/preserved?

## Contract Questions

- How should `OrderIntent`, `OrderRequest`, `FillEvent`, and `OrderFill` be bridged without duplicate order authority?
- Does fill telemetry need `decision_uuid` carried through `OrderRequest`, metadata, router state, or another canonical path?
- What is the canonical handoff contract for world-awareness events?
- What is the canonical instrument profile contract for cross-asset expansion?
- Which modules may use float analytics and which boundaries require Decimal?

## Pre-Integration Module Questions

- What is the exact future activation path for `app/world_awareness/*` now that it is registered but still non-authoritative and not runtime-wired?
- What is the exact activation path for `app/markets/*` and `app/models/instrument_profile.py`?
- What is the exact activation path for `app/portfolio/*`?
- What is the exact activation path for `app/risk/cross_asset_risk_model.py`?
- What is the exact activation path for `app/risk/net_edge_governor.py` and `app/risk/trade_efficiency_governor.py`?
- What is the exact activation path for `app/strategies/moving_floor.py`?

## Dirty Worktree Questions

- Which dirty tracked runtime files are intentional current work?
- Which untracked files should become packet-scoped source files later?
- Which state/report/data files are generated and must stay uncommitted?
- Which deleted tracked docs/scripts should stay deleted versus be restored?

## Next Decision Questions

- What is the first runtime seam after Bundle 0: contract surface reconciliation, telemetry fill UUID, or adapter boundary mapping?
- What is the smallest safe evidence-seam packet that improves trust without drifting into isolated bug fixing?
