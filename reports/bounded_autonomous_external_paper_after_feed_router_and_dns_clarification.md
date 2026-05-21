# Bounded Autonomous External Paper After Feed Router and DNS Clarification

## Packet

- Packet: APPROVED PACKET - BOUNDED AUTONOMOUS PAPER TEST AFTER FEED/DNS CLARIFICATION
- Date/time: 2026-05-21
- Branch: master
- Starting HEAD: 07769da
- Command run: `timeout 300s venv/Scripts/python.exe main.py --paper --log-level INFO`
- Duration: bounded 300-second run, ended by `timeout` with exit code 124

## Pre-Run State

- Execution broker: `alpaca_paper`
- Broker mode: paper
- Shadow read-only: disabled for the approved autonomous paper test
- Alpaca endpoint: `https://paper-api.alpaca.markets`
- Alpaca endpoint verdict: PAPER
- Live endpoint used: false
- Credentials present: true
- Account readable: true
- Account status before run: ACTIVE
- Positions before run: 7
- Open orders before run: 0
- Pre-run broker GET count: 3
- Pre-run broker POST count: 0
- Physical fuse triggered: false
- Volatility fuse triggered: false
- Physical fuse reset audit: `PHYSICAL_FUSE_OPERATOR_RESET_APPLIED`
- Physical fuse classification after reset: `PHYSICAL_FUSE_CLEARED`
- Broker/local conflict in reset evidence: false

## Runtime Route

The runtime selected the external paper broker path:

- `Execution broker resolved: market_data_venue=None execution_broker=alpaca_paper execution_primary_exchange=alpaca execution_adapter=alpaca_paper_rest shadow_read_only=False broker_mode=paper`
- `Internal SovereignPaperBroker not wired: external paper broker gateway selected`
- `OrderRouter execution route: paper_mode=True execution_broker=alpaca_paper primary_exchange=alpaca broker_gateway_adapter=alpaca_paper_rest`

No unintended `internal_paper` fallback was observed.

## Universe And Market Data

- Runtime universe source: `CONFIG_EXPLICIT_ALLOWED:symbol_universe`
- Runtime symbols: `BTC/USD`, `ETH/USD`, `SOL/USD`
- Provider lane: `crypto_market_data`
- Initial selected provider: `coinbase_public`
- Initial provider reason: `PRIMARY_SELECTED`
- Coinbase transport adapter: `coinbase_exchange_public_rest`
- Fallback path: `coinbase_public`, `kraken_public`
- WebSocket state: no WebSocket transport active for market-data venue `coinbase`; REST polling transport used for supported data types.

During the run, Coinbase REST candle requests failed from the Windows Python/aiohttp runtime:

- `Cannot connect to host api.exchange.coinbase.com:443 ssl:default [Could not contact DNS servers]`
- Symbols affected: `BTC/USD`, `ETH/USD`, `SOL/USD`
- Router telemetry skipped `coinbase_public` with `DNS_FAILURE`
- Router selected `kraken_public` as fallback candidate
- Active transport remained `coinbase_public`
- Warning recorded: `Market-data fallback candidate selected but active transport remains coinbase_public: candidate=kraken_public`

This means Kraken remained a fallback candidate only. It did not silently become the hidden active runtime transport.

Prior diagnostics outside the Codex sandbox showed WSL/Windows resolver access to:

- `api.kraken.com`
- `api.exchange.coinbase.com`
- `api.binance.us`
- `paper-api.alpaca.markets`

The 300-second runtime still hit DNS failure from the actual Windows Python/aiohttp path, so the remaining blocker is runtime feed connectivity truth, not broker safety.

## No-Trade Explanation

Orders submitted: 0.

Exact no-trade reasons observed:

- Coinbase executable market-data transport could not retrieve candles because `api.exchange.coinbase.com` DNS failed in the runtime path.
- WebSocket RTT latency truth was unavailable: `MISSING_LATENCY_TRUTH`, `WEBSOCKET_RTT_NOT_READY`.
- No active WebSocket transport existed for Coinbase REST mode.
- Health checks reported WebSocket disconnected.
- The bot failed closed before broker order submission rather than inventing candles, spreads, liquidity, latency, or feed health.

## Post-Run Reconciliation

- Account status after run: ACTIVE
- Trading blocked: false
- Endpoint: `https://paper-api.alpaca.markets`
- Endpoint verdict: PAPER
- Live endpoint used: false
- Positions after run: 7
- Open orders after run: 0
- Positions change: 7 -> 7
- Open orders change: 0 -> 0

Order counts since run:

- Submitted: 0
- Filled: 0
- Open: 0
- Rejected: 0
- Canceled: 0

Broker request accounting:

- Post-run broker GET count: 4
- Post-run broker POST count: 0
- Orders returned since run: none

## Safety Markers

Checked markers:

- No `/v2/orders` log marker found
- No order submission marker found
- No `client_order_id` marker found
- No live endpoint marker found
- No real-money marker found
- No broker POST mutation observed
- No fake fill observed
- No forced trade observed
- No forced symbol command-line override used
- No threshold change made
- No production code changed in this packet

## Final Health State

- Broker route: safe external Alpaca PAPER route
- Broker reconciliation: succeeded before and after
- Broker mutation: none
- Paper/live verdict: paper only
- Physical fuse: not triggered
- Volatility fuse: not triggered
- Feed route: explicit Coinbase primary with Kraken fallback candidate
- Feed blocker: runtime DNS failure to `api.exchange.coinbase.com`
- Latency blocker: WebSocket RTT not ready because no active Coinbase WebSocket transport was present

## Verdict

CONDITIONAL.

The bounded autonomous external PAPER run completed safely with Alpaca PAPER selected as execution broker, no live endpoint, no real-money mode, no broker POST, no orders, and successful pre/post reconciliation. The run did not produce executable market truth because the active Coinbase public REST transport hit DNS failure in the runtime path and latency truth remained unavailable. This is a feed/runtime connectivity blocker, not a broker safety failure.
