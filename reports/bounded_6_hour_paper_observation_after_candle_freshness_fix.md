# 6 Hour PAPER Observation After Candle Freshness Fix

## Verdict

CONDITIONAL.

The run completed safely and produced downstream SectorRotation candidates, but no candidate reached broker submission. The dominant next blocker is execution safe mode from latency truth, specifically `market_data.rest_polling_rtt` crossing the 200 ms threshold at execution admission.

## Run Inputs

- stdout: `logs/paper_runs/bounded_paper_20260522_022343.out.log`
- stderr: `logs/paper_runs/bounded_paper_20260522_022343.err.log`
- Preflight before run: `PAPER_READ_ONLY_PREFLIGHT_PASSED`
- Account before run: `ACTIVE`
- Endpoint before run: `https://paper-api.alpaca.markets`
- Execution broker before run: `alpaca_paper`
- Adapter before run: `alpaca_paper_rest`
- Selected feed provider before run: `coinbase_public`
- Runtime universe source before run: `CONFIG_EXPLICIT_ALLOWED:runtime_watchlist`
- Positions before run: `7`
- Open orders before run: `0`
- Preflight GET count before run: `3`
- Preflight POST count before run: `0`
- Preflight live endpoint used: `false`
- Preflight mutation occurred: `false`

## Reconciliation

Post-run broker GET reconciliation could not be completed from the audit shell because the Windows environment available to this process did not expose `APCA_API_KEY_ID` or `POVERTY_KILLER_ALPACA_PAPER_ENV_PATH`, and the repo `.env` intentionally contains blank paper credentials. This is recorded as an audit environment limitation, not broker evidence.

Read-only local and log evidence showed no broker mutation:

- `/v2/orders` markers: `0`
- broker POST markers: `0`
- generic `POST` markers in run log: `0`
- live endpoint markers: `0`
- real-money markers: `0`
- `mutation_occurred` markers: `0`
- `live_endpoint_used` markers: `0`
- `submitted=True`: `0`
- BrokerGateway markers: `0`
- Local `orders`: `0`
- Local `fills`: `0`
- Local `order_id_mappings`: `0`
- Local `reservation_ledger`: `0`
- Local `reservation_fill_progress`: `0`
- Local `reservation_release_tombstones`: `0`

## Runtime Counts

- `CANDLE_RUNTIME_FRESH`: `0`
- `CANDLE_BATCH_BACKFILL_OBSERVE_ONLY`: `861`
- `DATA_BACKFILL_OBSERVE_ONLY`: `973`
- `DATA_UNHEALTHY`: `0`
- `CANDLE_STALE`: `112`
- `OBSERVED_PAIR_READY`: `214`
- `OBSERVED_PAIR_STALE`: `68`
- `OBSERVED_SIGNAL_MISSING`: `64`
- `OBSERVED_VOTE_MISSING`: `0`
- `OBSERVED_PAIR_CANDLE_MISMATCH`: `0`
- `OBSERVED_PAIR_SYMBOL_MISMATCH`: `0`
- Decision compile attempts: `2`
- DecisionRecords compiled: `2`
- `submit_signal_called=True`: `2`
- `submit_signal_called=False`: `1080`
- `submitted=True`: `0`
- `submitted=False`: `2`
- `SAFE_MODE_ACTIVE` admission blocks: `2`
- `LAG ABORT`: `1246`
- `Lag resolved`: `1246`
- `Latency recovered`: `1247`
- ShadowFront whale-condition declines: `35`
- Shans results: `63703`
- Fusion updates: `38709`

## Candidate Outcomes

### SOL/USD Sell Candidate

- Timestamp: `2026-05-22 08:40:57`
- Decision UUID: `ab82d291-e54b-4a7e-904c-213c13bdf31d`
- Side: `sell`
- SectorRotation status: `OBSERVED_PAIR_READY`
- DecisionCompiler: compiled `strategy_vote`
- `submit_signal_called`: `true`
- `submitted`: `false`
- DecisionCompiler status: `PRE_TRADE_GUARDRAIL_BLOCKED`
- Guardrail reason codes:
  - `PREFERRED_PORTAL_UNSUPPORTED`
  - `ACTION_UNSUPPORTED`
  - `QUOTE_SESSION_TRUTH_MISSING`
  - `SELL_AUTHORITY_MISSING`
- Execution admission also blocked: `SAFE_MODE_ACTIVE`
- Latency truth status: `LAG_ABORT_ACTIVE`
- Latency truth reason: `LATENCY_THRESHOLD_EXCEEDED`
- Latency: `416.901 ms`
- Threshold: `200.0 ms`
- Latency source: `market_data.rest_polling_rtt`
- Broker POST attempted: no

### SOL/USD Buy Candidate

- Timestamp: `2026-05-22 08:45:57`
- Decision UUID: `df8b7c92-2c5f-48b7-a44f-5ef365a75627`
- Side: `buy`
- SectorRotation status: `OBSERVED_PAIR_READY`
- DecisionCompiler: compiled `strategy_vote`
- Pre-trade guardrails: `ALLOW`
- `submit_signal_called`: `true`
- `submitted`: `false`
- DecisionCompiler status: `EXECUTION_ADMISSION_BLOCKED`
- DecisionCompiler reason codes: `PRE_TRADE_GUARDRAILS_ALLOW`
- Execution admission reason: `SAFE_MODE_ACTIVE`
- Latency truth status: `LAG_ABORT_ACTIVE`
- Latency truth reason: `LATENCY_THRESHOLD_EXCEEDED`
- Latency: `437.8774 ms`
- Threshold: `200.0 ms`
- Latency source: `market_data.rest_polling_rtt`
- Broker POST attempted: no

## Interpretation

The 6 hour observation shows that the candle freshness and SectorRotation work moved candidates downstream far enough to reach DecisionCompiler and `submit_signal`. The old observed-pair blocker is no longer the dominant blocker.

The buy-side candidate passed pre-trade guardrails but was stopped by execution safe mode. The sell-side candidate remained correctly fail-closed because sell/exit authority and quote/session truth were not proven.

The key architectural issue is that `market_data.rest_polling_rtt` currently contributes to global execution safe mode. This can kill candidates before the full opportunity stack produces an institutional-grade scorecard.

## Dominant Next Blocker

Primary next seam: separate opportunity scoring from execution admission, and split latency authority by source.

- REST market-data polling latency should become market-data health or opportunity-penalty evidence.
- Broker/order-router latency should remain an execution blocker at the broker boundary.
- Final broker mutation must remain fail-closed.
- Thresholds should not be lowered.
- Guardrails should not be bypassed.

Recommended packet: `Opportunity Scorecard Before Execution Admission` plus `Latency Source-Scope and Candle Close-Time Freshness Authority`.

## Governance

- No production code changed in this report.
- No autonomous rerun performed during audit.
- No broker POST performed during audit.
- No order placement, cancel, or replace performed during audit.
- No live endpoint evidence found in the run log.
- No real-money marker found in the run log.
- No fake market truth accepted.
- No fake broker truth accepted.
- Broker truth remains canonical.
- Market-data truth remains canonical.
- Conflicts remain fail-closed.
