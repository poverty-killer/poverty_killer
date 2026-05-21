# Dynamic Universe + Asset-Class Feed + World-Awareness Seam

Date/time: 2026-05-21T19:41:56Z

Starting HEAD: 44351f5

Final verdict: CONDITIONAL

## Files Changed

- `app/config.py`
- `app/data/feed_provider_router.py`
- `app/data/market_feeds.py`
- `main.py`
- `tests/test_feed_provider_router_failover.py`
- `reports/dynamic_universe_asset_class_feed_world_awareness_seam.md`

## Kraken Dependency Audit

Kraken remains a provider registry option, but it is no longer a hidden runtime
default or silent sole market-data authority.

Runtime blockers fixed:

- `primary_feed_venue` no longer defaults to `kraken`; it is now a legacy
  explicit override only.
- Market-data provider config no longer silently defaults to a Kraken-first list.
- Empty provider config fails closed with `MISSING_MARKET_DATA_PROVIDER_CONFIG`.
- Runtime provider selection is driven by configured provider priority and
  provider health/quality truth.
- Runtime no longer starts Kraken just because paper mode is active. The selected
  provider must resolve through the router and must have a transport mapping.
- When Kraken reports DNS failure and no implemented fallback exists, the router
  emits `MISSING_MARKET_TRUTH` with skipped provider reasons instead of faking a
  fallback.

Allowed Kraken references preserved:

- `kraken_public` provider registry entry.
- Test fixtures, report examples, and documentation examples.
- Kraken WebSocket/REST transport code, because it remains a valid public crypto
  feed option when explicitly configured and healthy enough.

## Provider Policy

Provider priority is now configuration-driven. The shadow proof used:

`coinbase_public,binance_us_public,kraken_public`

The result was truthful:

- `coinbase_public` skipped: `MISSING_TRANSPORT`
- `binance_us_public` skipped: `MISSING_TRANSPORT`
- `kraken_public` selected only because it was explicitly configured and was the
  only currently implemented public crypto transport at startup.
- When Kraken REST DNS degraded later, Kraken was skipped with `DNS_FAILURE` and
  the router failed closed with `MISSING_MARKET_TRUTH`.

No fake Coinbase, Binance, Alpaca, options, reference, or event data was created.

## Symbol / Universe Audit

Runtime hardcoded universe authority was removed.

Runtime universe now resolves from explicit configuration only:

- `POVERTY_KILLER_RUNTIME_WATCHLIST`
- existing explicit `symbol_universe`

If neither exists, runtime fails closed with `MISSING_UNIVERSE_TRUTH`.

Audit classifications:

- Test fixture symbols: `TEST_FIXTURE_ALLOWED`
- Report/documentation symbols: `REPORT_OR_DOC_ALLOWED`
- Explicit configured watchlists/universe values: `CONFIG_EXPLICIT_ALLOWED`
- Provider registry IDs and examples: `PROVIDER_REGISTRY_ALLOWED`
- Hidden runtime default symbol list: `RUNTIME_BLOCKER`, fixed

The shadow proof used an explicit runtime watchlist:

`BTC/USD,ETH/USD,SOL/USD`

## Feed Lanes

Added explicit provider lanes:

- `crypto_market_data`
- `equity_etf_market_data`
- `options_market_data`
- `reference_market_data`
- `event_news_advisory`

Router telemetry now records:

- `asset_class`
- `provider_lane`
- `selected_provider`
- provider priority/fallback path
- skipped provider reason codes
- missing truth reason

## Equity / ETF Lane

Equity/ETF market-data providers are represented separately from execution
broker routing.

Current entries:

- `alpaca_market_data`: entitlement unknown, not assumed from Alpaca PAPER
  execution credentials.
- `alpaca_iex_limited`: labeled `limited_iex_not_full_sip`, not full SIP truth.
- `tiingo_optional`: config/registry hook only.

Missing entitlement or transport is explicit through `MISSING_ENTITLEMENT`,
`MISSING_TRANSPORT`, or `MISSING_EQUITY_MARKET_DATA_TRUTH`.

## Options Lane

Options market data is separated from crypto/equity routing.

Current entry:

- `polygon_or_massive_optional`

No options/gamma/hedging-flow truth is fabricated. If no approved options feed
qualifies, the router emits `MISSING_OPTIONS_FEED_TRUTH`.

## Reference / Advisory Lane

Reference providers cannot satisfy executable quote, book, spread, or liquidity
truth.

Advisory/event providers are classified as `event_news_advisory` and
`advisory_only`:

- `sec_edgar`
- `openinsider`
- `capitol_trades`
- `official_company_press_releases`
- `official_calendars`

These providers route as world-awareness/advisory evidence first and cannot
directly become executable market truth.

## Verification

Scoped compile:

`venv/Scripts/python.exe -m py_compile main.py app/config.py app/data/feed_provider_router.py app/data/market_feeds.py tests/test_feed_provider_router_failover.py`

Result: passed.

Focused tests:

`venv/Scripts/python.exe -m pytest tests/test_feed_provider_router_failover.py -q`

Result: 21 passed.

Relevant regressions:

`venv/Scripts/python.exe -m pytest tests/test_kraken_rest_dns_feed_truth_resilience.py tests/test_final_paper_readiness_latency_shadow_proof.py tests/test_market_data_truth_stabilization_for_paper_readiness.py tests/test_config.py tests/test_dynamic_execution_broker_gateway_injection.py -q`

Result: 33 passed.

## Shadow Proof

Command:

`timeout 60s venv/Scripts/python.exe main.py --paper --shadow-read-only --log-level INFO`

Environment for proof:

- `POVERTY_KILLER_EXECUTION_BROKER=alpaca_paper`
- `POVERTY_KILLER_RUNTIME_WATCHLIST=BTC/USD,ETH/USD,SOL/USD`
- `POVERTY_KILLER_CRYPTO_MARKET_DATA_PROVIDERS=coinbase_public,binance_us_public,kraken_public`

Observed:

- paper mode confirmed
- shadow-read-only confirmed
- execution broker resolved to `alpaca_paper`
- runtime universe resolved from explicit watchlist, count 3
- market-data provider selection was explicit and lane-aware
- Kraken was not a hidden default; it was selected only after configured
  Coinbase/Binance candidates were skipped for `MISSING_TRANSPORT`
- Kraken REST DNS degradation was recorded as `DNS_FAILURE`
- with no implemented fallback transport, market truth failed closed as
  `MISSING_MARKET_TRUTH`
- no `/v2/orders`
- no order submission marker
- no live endpoint marker
- no real-money marker

Broker mutation proof:

- POST/order marker search returned zero matches for the shadow proof log scope.

## Remaining Conditional Items

The seam is now dynamic and asset-class aware, but full live provider redundancy
requires separate provider-specific work:

- Implement a lawful unauthenticated Coinbase public transport, or mark it
  unavailable until a supported channel is wired.
- Implement a lawful Binance US public transport, or leave it as
  `MISSING_TRANSPORT`.
- Add/read Alpaca market-data entitlement truth before claiming equity/ETF
  executable feed readiness.
- Add an approved options provider before options/gamma truth can be used.

No broker mutation occurred in this packet.
