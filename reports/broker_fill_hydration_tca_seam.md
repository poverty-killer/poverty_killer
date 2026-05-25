# Broker Fill Hydration And TCA Ledger Seam

## Purpose

The 3-hour Alpaca PAPER run proved OMS reconciliation, but exposed an honest accounting gap:

- `filled_orders=11`
- `fill_hydration_missing_count=11`
- `fill_hydration_count=0`
- `local_fills=0`

Broker truth showed terminal filled orders, but local fill detail was not hydrated into a canonical ledger. The system correctly did not invent fills. This seam turns terminal broker fill truth into local broker-backed fill/TCA records when data exists, and preserves explicit unavailable telemetry when it does not.

## What Changed

- Added read-only Alpaca PAPER account activity access through the governed broker adapter:
  - `GET /v2/account/activities`
  - `activity_types=FILL`
  - no broker mutation

- Added a canonical `broker_fill_ledger` state table for broker-backed fill facts:
  - supports nullable fee fields
  - supports partial hydration
  - stores hydration status and reason code
  - stores TCA fields when available
  - prevents duplicate fill insertion by stable broker/activity keys

- Preserved the legacy `fills` table as strict full-detail storage:
  - populated only when fee and fee currency are available
  - no fake `0` fee is inserted when fee is absent

- Extended OMS shutdown accounting with:
  - `fill_hydration_attempted_count`
  - `fill_hydration_count`
  - `fill_hydration_partial_count`
  - `fill_hydration_missing_count`
  - `fill_hydration_conflict_count`
  - `broker_filled_orders`
  - `broker_partially_filled_orders`
  - `broker_canceled_with_fill_count`
  - `tca_records_count`
  - `tca_unknown_count`
  - `realized_vs_modeled_netedge_available_count`
  - `realized_vs_modeled_netedge_unknown_count`
  - `legacy_local_fills`

- Carried `net_edge_context` and `net_edge_evaluation` into order metadata so TCA can compare modeled NetEdge against fill execution when the required broker data exists.

## What Was Not Changed

- No alpha tuning.
- No threshold changes.
- No DecisionFrame redesign.
- No SELL taxonomy change.
- No MovingFloor strategy change.
- No broker mutation path change.
- No fake fills, fees, prices, or quantities.
- No live endpoint or real-money path.

## Safety Laws Preserved

- Broker truth remains canonical after acknowledgement.
- Missing broker fill details produce explicit unavailable/unknown telemetry.
- Fee, slippage, and realized edge are computed only from available broker-backed fields.
- Activity/order mismatches fail into conflict telemetry.
- Tests use fake broker responses only and perform no real broker mutation.

## Validation Plan

Focused tests prove:

- filled order hydrates from broker order status
- broker activity hydrates canonical fill ledger with fee data
- repeated hydration is idempotent
- canceled order with filled quantity records partial fill truth
- missing fill detail reports unavailable without fake fills
- TCA/realized NetEdge only appear when required fields exist
- no broker mutation in tests

Runtime proof is a short Alpaca PAPER smoke with `PAPER_EXPLORATION_ALPHA`. A short smoke may be conditional if no natural fill occurs, but it must still prove safety and clean OMS shutdown.

## Remaining Limitations

- Realized NetEdge remains unknown when broker activity lacks fee or execution detail.
- Legacy `fills` remains strict; canonical local fill truth now lives in `broker_fill_ledger`.
- Longer 20-minute and 4-hour PAPER runs are still required to prove fill hydration under repeated natural broker fills.
