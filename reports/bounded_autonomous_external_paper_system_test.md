# Bounded Autonomous External Paper System Test

Packet: POVERTY_KILLER - APPROVED BOUNDED AUTONOMOUS EXTERNAL PAPER SYSTEM TEST

Report time: 2026-05-21T17:10:36Z

## Starting State

- Branch: master
- Starting HEAD: 460731a
- Latest expected hotfix: 460731a - Wire dynamic execution broker gateway injection
- Staged files before run: empty
- Dirty/untracked files before run: present and treated as unrelated; no unrelated dirty file was intentionally touched or staged.

## Pre-Run Safety Checks

- Execution broker selector: `POVERTY_KILLER_EXECUTION_BROKER=alpaca_paper`
- Broker mode: paper
- Runtime command used `--paper`
- Internal simulation broker selected: no
- Execution broker selection: dynamic config/env path from the hotfix, not a permanent Alpaca global assumption
- Alpaca endpoint: `https://paper-api.alpaca.markets`
- Alpaca credentials: present
- Alpaca account status before run: ACTIVE
- Alpaca environment: paper
- Live endpoint used before run: false
- Real-money mode: false
- Pre-run Alpaca positions count: 7
- Pre-run Alpaca position symbols: AAPL, AMZN, GOOGL, NVDA, QQQ, SPY, TSLA
- Pre-run Alpaca open orders count: 0
- Pre-run read-only reconciliation: succeeded
- Pre-run broker request counts from read-only proof: GET=4, POST=0
- Physical fuse: `physical_fuse_triggered=false`
- Vol fuse: `vol_fuse_triggered=false`
- Physical fuse reset audit: present, `PHYSICAL_FUSE_OPERATOR_RESET_APPLIED`, classification after `PHYSICAL_FUSE_CLEARED`
- Stale mutation approval flags: none observed or activated by this packet

## Command Run

```bash
timeout 300s venv/Scripts/python.exe main.py --paper --log-level INFO
```

Environment was loaded from the existing Alpaca PAPER environment file and exported into the Windows Python process via `WSLENV`. No secret values were printed.

Duration: bounded 300 seconds. The process exited with code 124 from the `timeout` boundary, which is the expected bounded stop for this packet.

## Runtime Route Evidence

Console startup telemetry reported:

- Broker Mode: paper
- Shadow Read Only: DISABLED
- Execution broker resolved:
  - market_data_venue=kraken
  - execution_broker=alpaca_paper
  - execution_primary_exchange=alpaca
  - execution_adapter=alpaca_paper_rest
  - shadow_read_only=False
  - broker_mode=paper
- Internal SovereignPaperBroker not wired: external paper broker gateway selected
- OrderRouter execution route:
  - paper_mode=True
  - execution_broker=alpaca_paper
  - primary_exchange=alpaca
  - broker_gateway_adapter=alpaca_paper_rest

This proves the requested external paper broker path was selected and the runtime did not intentionally fall back to `internal_paper`.

## Market Data Venue Status

- Feed-side venue remained Kraken.
- Kraken REST polling was degraded during the run with DNS failures:
  - `Cannot connect to host api.kraken.com:443 ssl:default [Could not contact DNS servers]`
- WebSocket/book processing continued during the run:
  - `FEED_BOOK` events were logged.
  - `[SHANS_DIAG] PROCESSING_BOOK` events were logged continuously for SOL/USD.
- Market-data quality guards also triggered:
  - `CROSSED_BOOK_PREVENTED`
  - `CANDLE_REJECT_DUPLICATE`

The Kraken REST issue was not hidden or fixed inside this packet.

## Post-Run Reconciliation

- Alpaca account status after run: ACTIVE
- Alpaca endpoint after run: `https://paper-api.alpaca.markets`
- Alpaca environment after run: paper
- Live endpoint used after run: false
- Mutation occurred during post-run read-only proof: false
- Post-run Alpaca positions count: 7
- Post-run Alpaca position symbols: AAPL, AMZN, GOOGL, NVDA, QQQ, SPY, TSLA
- Position count change: 0
- Open orders before run: 0
- Open orders after run: 0
- Post-run read-only reconciliation: succeeded
- Post-run broker request counts from read-only proof: GET=4, POST=0

## Orders

- Submitted orders: 0
- Filled orders: 0
- Open orders: 0
- Rejected orders: 0
- Canceled orders: 0
- Broker order IDs: none
- Client order IDs: none

Focused log scans for the run window found no:

- `/v2/orders`
- `ORDER_SUBMIT_ATTEMPT`
- broker order IDs
- client order IDs
- broker gateway order response markers
- order submission markers
- broker POST markers

## Exact No-Trade Reasons Observed

The bot reached strategy/dispatch evaluation and lawfully produced no executable submission. Observed reasons included:

- `shadowfront_declined_sentiment_condition`
- `shadowfront_declined_whale_condition`
- `observed_pair_missing`
- `volume_zscore_below_threshold`
- `CROSSED_BOOK_PREVENTED`
- `CANDLE_REJECT_DUPLICATE`
- Kraken REST DNS failure while WebSocket book processing continued

Representative dispatch diagnostics included `submit_signal_called: False`, meaning the observed strategy paths did not call into execution submission.

## Stop Conditions Checked

Focused scans in the run window found no evidence of:

- Live Alpaca endpoint
- Real-money mode
- `/v2/orders`
- Broker POST
- Internal PaperBroker handling requested `alpaca_paper` execution
- Physical fuse trigger
- `LAG_ABORT_ACTIVE`
- Broker/local conflict
- Retry storm
- Unhandled exception or traceback
- Fake fill or fake broker truth
- Unexpected sell/rebalance/cancel/replace path
- Secrets printed

## Runtime Health

- Physical fuse final state: false
- Vol fuse final state: false
- Physical fuse audit: valid owner-path reset evidence remained present
- Latency: startup reported missing WebSocket RTT truth; no mutation was attempted while no executable signal existed. No unrecovered `LAG_ABORT_ACTIVE` marker was found.
- Safe mode: no mutation attempted under an unrecovered safe-mode condition was found.
- Stale data / data quality: degraded; duplicate candles and crossed-book prevention were recorded.
- Kraken REST DNS truth: degraded and truthfully classified by errors.
- WebSocket truth: active book processing was recorded.
- Alpaca reconciliation truth: succeeded before and after the run.

## Module Attribution

Native runtime evidence observed:

- Config/env execution broker selection
- Dynamic execution broker route telemetry
- OrderRouter external adapter route selection
- Alpaca PAPER adapter pre-run and post-run reconciliation
- Kraken feed-side WebSocket/book processing
- Polling client REST failure telemetry
- Main loop candle/order-book processing
- Shans diagnostics
- Sector rotation diagnostics
- ShadowFront dispatch diagnostics
- Data quality guards

Advisory or conditional evidence observed:

- Sentiment condition evidence used by ShadowFront dispatch
- Whale condition evidence used by ShadowFront dispatch
- Sector rotation observation/volume evidence

Missing or degraded evidence:

- Kraken REST candles/order books were unavailable because DNS resolution failed.
- Some book/candle data failed quality guards due crossed books or duplicate candle timestamps.
- No broker execution/fill evidence exists because no executable signal reached submission.

## Final Verdict

CONDITIONAL

The bounded autonomous external PAPER run completed to the 300-second timeout boundary with `alpaca_paper` selected as the dynamic execution broker and no live endpoint observed. Alpaca PAPER reconciliation succeeded before and after the run. No orders were submitted, and focused scans found no broker POST or `/v2/orders` marker.

The outcome is conditional rather than full pass because the run exposed non-dangerous degraded truth that must be handled before longer autonomous paper operation: Kraken REST DNS remained degraded, and feed quality guards rejected crossed books and duplicate candles. The system did not force a trade and did not fake broker, fill, or profitability evidence.
