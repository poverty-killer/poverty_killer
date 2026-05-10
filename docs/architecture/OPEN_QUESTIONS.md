# POVERTY_KILLER Open Questions

## Purpose

This file tracks unresolved questions so future OpenCode sessions do not repeat broad audits.

Only inspect files related to these questions or files changed since the last checkpoint.

## Evidence / Collection Questions

- Which exact files currently break `python -m pytest --collect-only -q`?
- Are the collection errors only syntax/import defects, or do they reveal deeper contract drift?
- Which broken tests are intentional future tests versus corrupted/legacy tests?
- Does `app/world_awareness/normalizer.py` only need syntax repair, or does it reveal a world-awareness contract issue?

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

- What is the exact activation path for `app/world_awareness/*`?
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

- Should Bundle 0 be split into separate commits for collection integrity and docs registry?
- What is the smallest safe evidence-seam packet that improves trust without drifting into isolated bug fixing?
- What is the first runtime seam after Bundle 0: adapter contracts, telemetry fill UUID, or world-awareness import safety?