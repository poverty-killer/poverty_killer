# Bounded Autonomous External Paper After REST Latency Truth Fix

## Packet

- Packet: APPROVED PACKET - BOUNDED AUTONOMOUS PAPER TEST AFTER REST LATENCY TRUTH FIX
- Date/time: 2026-05-21
- Starting commit: `f42b817` - Fix REST feed connectivity and latency truth
- Branch: `master`
- Command requested: `timeout 300s venv/Scripts/python.exe main.py --paper --log-level INFO`
- Runtime execution: run from Windows PowerShell outside this WSL shell because WSL could not launch the Windows venv (`UtilBindVsockAnyPort:309: socket failed 1`)
- Observed log window: `2026-05-21T23:28:16Z` through `2026-05-21T23:33:27Z`
- No production code changed in this packet
- No second autonomous run was launched by Codex

## Pre-Run Checks

- Branch: `master`
- HEAD: `f42b817`
- HEAD includes `f42b817`: yes
- Alpaca endpoint: `https://paper-api.alpaca.markets`
- Paper endpoint verdict: true
- Live endpoint used: false
- Credentials present in pre-run environment: true
- Alpaca account readable before run: true
- Account status before run: `ACTIVE`
- Trading blocked before run: false
- Positions before run: 7
- Open orders before run: 0
- Pre-run broker request count: GET 3, POST 0
- Physical fuse triggered: false
- Volatility fuse triggered: false
- Physical fuse audit: `PHYSICAL_FUSE_CLEARED`
- Broker/local conflict in reset evidence: false
- Stale mutation approval flags: none found in active config/state scan

## Runtime Route Evidence

Latest run startup logs show:

- Broker mode: paper
- Shadow read-only: disabled
- Paper mode forced by command line
- Execution broker resolved to `alpaca_paper`
- Execution adapter: `alpaca_paper_rest`
- OrderRouter route: `paper_mode=True execution_broker=alpaca_paper primary_exchange=alpaca broker_gateway_adapter=alpaca_paper_rest`
- Internal PaperBroker was not wired on the external paper broker route

No unintended `internal_paper` fallback was observed.

## Feed And Latency Truth

Selected market-data route:

- Provider: `coinbase_public`
- Provider lane: `crypto_market_data`
- Venue: `coinbase`
- Transport adapter: `coinbase_exchange_public_rest`
- Fallback path: `coinbase_public`, `kraken_public`
- Runtime universe source: `CONFIG_EXPLICIT_ALLOWED:symbol_universe`
- Runtime symbols: `BTC/USD`, `ETH/USD`, `SOL/USD`

REST latency truth behavior:

- Initial missing latency was classified truthfully as `MISSING_LATENCY_TRUTH`
- Reason: `REST_RTT_NOT_READY`
- Source: `market_data.rest_polling_rtt`
- Missing source: `rest_request_or_response_timestamp`
- Latency later recovered repeatedly below the 200ms threshold
- Examples: `111.0ms`, `106.0ms`, `96.0ms`, `42.0ms`, `40.0ms`
- ExecutionEngine exited safe mode after finite REST latency truth recovered

Market-data processing observed:

- Order books processed for `BTC/USD`, `ETH/USD`, and `SOL/USD`
- Data feed recovered after good packets for all three symbols
- Counted in latest run window:
  - order book processing records: 864
  - data feed recovered records: 333
  - Shans signal records: 349
  - fusion update records: 349
  - fusion decision records: 10
  - latency recovery records: 22

No fake candles, books, spreads, liquidity, fills, or PnL were created by this report.

## No-Trade / No-Submission Evidence

Broker/order mutation markers in the latest run logs:

- `/v2/orders`: 0
- `ORDER_SUBMIT` / `ORDER_SUBMISSION`: 0
- `submit_order`: 0
- `client_order_id`: 0
- `broker_order_id`: 0
- live endpoint markers: 0
- real-money markers: 0

Local state/telemetry since `2026-05-21T23:28:16Z`:

- `orders`: 0
- `fills`: 0
- `order_id_mappings`: 0
- `reservation_ledger`: 0
- `reservation_fill_progress`: 0
- `reservation_release_tombstones`: 0
- order-like telemetry events: 0
- submit-like telemetry events: 0

Observed no-trade reasons:

- Fusion decisions were generated, but strategy dispatch did not produce an executable order.
- Runtime logs include `update_price returned None (gate blocked)` and `all_sleeves_declined`.
- Some Shans outputs returned `result_type=None`.
- The bot processed market truth and advisory/fusion updates, then lawfully declined to submit.

## Post-Run Broker Reconciliation

Codex attempted read-only Alpaca PAPER reconciliation after the run through the repository helper path:

- `AlpacaPaperBrokerAdapter.from_env()`
- `collect_alpaca_paper_read_only_reconciliation_truth(adapter)`

Credential environment checks:

- `APCA_API_BASE_URL` present: true
- `APCA_API_KEY_ID` present: true
- `APCA_API_SECRET_KEY` present: true
- Endpoint: `https://paper-api.alpaca.markets`
- Paper endpoint verdict: true
- Live endpoint used: false
- Credential values were not printed

Helper result:

- Reconciliation status: `FAILED_CLOSED`
- Reason codes: `BROKER_READ_ONLY_GET_FAILED`
- Account status: `missing`
- Positions count returned by helper: 0
- Open orders count returned by helper: 0
- Request counts: GET 3, POST 0
- Mutation occurred: false
- Live endpoint used: false

Individual read-only adapter GET results:

- `/v2/account`: `HTTP_401`, message `unauthorized.`
- `/v2/positions`: `HTTP_401`, message `unauthorized.`
- `/v2/orders?status=open`: `HTTP_401`, message `unauthorized.`

Order history count:

- Not checked through the existing helper. The current adapter helper supports account, positions, and open-order GETs only; its safety contract restricts `/v2/orders` to `status=open`, so an all-order history query is not supported by that path.

Therefore post-run broker reconciliation is not proven. Pre-run broker reconciliation was successful, and runtime/local evidence shows no order submission path was reached, but broker truth is canonical and the post-run broker GETs still failed authorization from this environment.

## Post-Run Counts

- Positions before run: 7
- Positions after run: unavailable from broker because helper-based post-run Alpaca GETs returned `HTTP_401 unauthorized`
- Open orders before run: 0
- Open orders after run: unavailable from broker because helper-based post-run Alpaca GETs returned `HTTP_401 unauthorized`
- Submitted orders: 0 observed in runtime logs/local state
- Filled orders: 0 observed in runtime logs/local state
- Open orders: 0 observed in runtime logs/local state
- Rejected orders: 0 observed in runtime logs/local state
- Canceled orders: 0 observed in runtime logs/local state
- Broker POST count during helper-based post-run reconciliation attempt: 0
- Broker POST/order-submission markers in logs: 0

## Safety Verdict

- No live endpoint observed
- No real-money mode observed
- No `/v2/orders` marker observed in runtime logs
- No broker POST/order submission marker observed in runtime logs
- No local order/fill/reservation records were created during the run window
- No internal PaperBroker fallback observed
- No forced trade
- No forced symbol
- No threshold change
- No 300-second rerun by Codex

## Final Verdict

CONDITIONAL.

The bounded autonomous external PAPER runtime completed safely enough to prove the REST feed connectivity and REST latency truth fix improved executable market-data readiness: Coinbase public REST was selected, order books were processed for all configured symbols, finite REST latency recovered, and the ExecutionEngine exited safe mode. The bot still submitted zero orders because the normal strategy/fusion/dispatch path lawfully declined to produce an executable order.

The verdict is conditional rather than pass because helper-based post-run Alpaca PAPER reconciliation from this environment failed with `HTTP_401 unauthorized` despite regenerated credentials being present and the endpoint remaining `https://paper-api.alpaca.markets`. Broker truth is canonical, so positions-after, open-orders-after, and broker order-history-after cannot be claimed as proven until read-only Alpaca reconciliation succeeds from a valid credential environment.
