# Deferred Broker Fee Hydration / CFEE-FEE Matching

Date: 2026-05-26

## Scope

This seam extends the broker-backed fill/TCA ledger so fee detail can be hydrated later from Alpaca read-only account activities when CFEE/FEE records become available.

It does not change alpha, thresholds, order submission, cancellation, SELL taxonomy, broker safety gates, or runtime trading behavior.

## Why This Exists

Recent PAPER validation proved that fills hydrate from broker truth, but TCA remains `UNKNOWN_INSUFFICIENT_BROKER_DETAIL` when Alpaca normal FILL/order payloads do not include fee amount and currency.

Alpaca crypto fee detail may post separately as `CFEE` or `FEE` account activity, often after the fill itself. The correct behavior is deferred broker-fee hydration, not estimating or inventing fees.

## Fee Hydration Model

Read-only Alpaca account activities are queried for:

- `CFEE`
- `FEE`

Fee records are normalized while preserving raw broker details:

- broker fee activity id
- activity type
- symbol
- linked order/client id when present
- fee amount when broker-provided
- fee currency when broker-provided
- transaction time
- quantity/price when present
- description

If fee amount or currency is missing, no broker-confirmed fee is recorded.

## Matching Strategy

The matcher uses deterministic, conservative rules:

1. Exact match by broker order id, client order id, or broker activity linkage.
2. Strong composite match only when unambiguous by symbol, fill timestamp window, and quantity/price when available.
3. Ambiguous matches remain conflicts/unmatched and do not update TCA.
4. Duplicate fee activities are ignored rather than double-counted.

Weak or many-to-one matches are never promoted to broker-confirmed fee truth.

## Fee Statuses

The ledger now surfaces fee accounting states:

- `FEE_PENDING_BROKER_ACTIVITY`
- `FEE_ACTIVITY_MATCHED`
- `FEE_ACTIVITY_UNMATCHED`
- `FEE_ACTIVITY_CONFLICT`
- `FEE_UNAVAILABLE`

Broker-confirmed fee sources:

- `BROKER_CFEE`
- `BROKER_FEE`

Estimated fee policy is intentionally deferred. No estimated fee is labeled broker-confirmed.

## TCA Behavior

If a broker-confirmed fee is matched, the fill ledger is enriched with fee amount, currency, fee bps, fee source, and fee match evidence.

TCA is only upgraded when all required inputs are available. If modeled edge, slippage, fee, or other required fields are missing, execution quality remains `UNKNOWN_INSUFFICIENT_BROKER_DETAIL`.

## Shutdown / Audit Telemetry

Shutdown accounting can now report:

- `broker_fee_hydration_attempted_count`
- `broker_fee_hydration_count`
- `broker_fee_hydration_pending_count`
- `broker_fee_hydration_unmatched_count`
- `broker_fee_hydration_conflict_count`
- `broker_fee_activity_records_seen_count`
- `broker_fee_activity_records_matched_count`
- `broker_fee_activity_duplicate_ignored_count`
- `tca_complete_count`
- `tca_estimated_count`
- `tca_fee_pending_count`

Existing fill hydration counts remain unchanged.

## Safety Laws Preserved

- No fake fees
- No fake fills
- No fake TCA
- No live endpoint
- No real-money mode
- No broker mutation in tests
- No order submission or cancel behavior changes
- Broker truth remains canonical
- Ambiguity fails closed

## Runtime Validation Plan

Short PAPER runs may not see same-day CFEE/FEE records because fee activity can post later. Acceptance for this seam is primarily fixture-backed matching proof plus runtime safety.

Recommended follow-up:

1. Run normal PAPER observation.
2. After fee activities have time to post, run a read-only fee audit against prior broker-filled orders.
3. Confirm matched CFEE/FEE records update fee/TCA fields without duplicate fills or invented fees.

## Limitations

- Same-run fee records may not exist.
- Alpaca PAPER may not expose all live-like fee details.
- Estimated fee policy is deferred and must remain clearly labeled if added later.
