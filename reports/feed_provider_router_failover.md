# Feed Provider Router + Public Feed Failover Seam

Date/time: 2026-05-21 19:07 UTC

Starting HEAD: `42bd6c1`

## Files Changed

- `app/data/feed_provider_router.py`
- `app/config.py`
- `app/data/market_feeds.py`
- `main.py`
- `tests/test_feed_provider_router_failover.py`

## Provider Registry Design

Added a pluggable `FeedProviderRouter` with explicit provider descriptors, runtime health input, deterministic configured priority, failover selection, conflict detection, and machine-readable telemetry.

Each provider declares:

- `provider_id`
- `provider_type`
- supported asset classes
- data capabilities
- auth and credential state
- rate-limit policy
- freshness policy
- quality checks
- execution eligibility
- advisory-only status
- provider health / reason codes
- transport adapter status

The router receives a `FeedProviderRequest` for symbol, asset class, and required data type, filters unsupported or unsafe providers, and returns a `FeedSelectionResult` with selected provider, fallback path, skipped providers, and fail-closed reason.

## Provider List And Classification

Public/no-signup executable crypto candidates:

- `kraken_public`: executable crypto market data; current implemented transport `kraken_public_ws_rest`.
- `coinbase_public`: executable crypto market data candidate; public/no-signup registry entry; transport adapter not implemented in this packet.
- `binance_us_public`: executable crypto market data candidate; public/no-signup registry entry with US jurisdiction flag; transport adapter not implemented in this packet.

Reference-only crypto providers:

- `coingecko_reference`: reference/advisory only; not execution-eligible.
- `coinmarketcap_reference`: reference/advisory only; API key required.

Equity/ETF candidates:

- `alpaca_market_data`: credential/entitlement-gated; not assumed available.
- `tiingo_optional`: credential-gated placeholder.
- `polygon_or_massive_optional`: credential/entitlement-gated placeholder.

Public event/advisory providers:

- `sec_edgar`
- `openinsider`
- `capitol_trades`
- `official_company_press_releases`
- `official_calendars`

Advisory providers remain non-executable and cannot satisfy order-book/candle/trade market-truth requests.

Primary documentation checked:

- Kraken public WebSocket market data: https://docs.kraken.com/api/docs/guides/spot-ws-intro/
- Coinbase public market data API: https://docs.cdp.coinbase.com/exchange/docs/apis/get-product-candles
- Binance.US public API docs portal notice: https://support.binance.us/en/articles/9843443-binance-us-launches-new-api-documentation-portal-for-traders-and-developers

## Config Keys

Added narrow provider-selection config:

- `market_data_providers`
- `crypto_market_data_providers`
- `equity_market_data_providers`
- `event_providers`
- `reference_data_providers`

Default crypto provider order:

`kraken_public, coinbase_public, binance_us_public`

No config key activates live trading.

## Provider Selection

Selection is deterministic:

1. Read the configured provider order.
2. Filter unknown providers.
3. Filter unsupported asset class or data type.
4. Filter missing credentials/entitlements.
5. Reject advisory/reference providers for executable market-data requests.
6. Filter providers with failover-worthy runtime health reasons such as `DNS_FAILURE`, `CROSSED_BOOK`, `DUPLICATE_CANDLE`, or stale feed truth.
7. Fail closed on material provider conflicts unless an explicit trusted-source priority is configured.
8. Return selected provider and fallback path as telemetry.

## Runtime Wiring

`main.py` now resolves market-data provider selection separately from execution broker selection.

Observed shadow startup selection:

- execution broker: `alpaca_paper`
- market-data provider: `kraken_public`
- selected provider type: `executable_market_data`
- fallback path: `kraken_public -> coinbase_public -> binance_us_public`

Kraken remains the only active transport adapter in this packet. When Kraken REST DNS failed during shadow proof, runtime telemetry selected `coinbase_public` as deterministic fallback candidate and recorded:

- skipped `kraken_public`: `DNS_FAILURE`
- selected fallback candidate: `coinbase_public`
- fallback candidate transport: `not_implemented`

No Coinbase or Binance.US market data was fabricated.

## Conflict Handling

Material provider disagreement fails closed with `PROVIDER_CONFLICT` unless `trusted_source_priority` is explicitly configured. The router records all conflicting provider IDs and observed values.

No averaging or blending is used.

## Reference/Advisory Protection

Reference providers and event/news/advisory providers are blocked from executable order-book truth. Tests prove:

- `coingecko_reference` cannot satisfy executable order-book truth.
- `sec_edgar` cannot satisfy executable market-data truth.
- missing credentials fail closed with `MISSING_CREDENTIALS`.

## Verification

Compile:

`venv/Scripts/python.exe -m py_compile main.py app/config.py app/data/feed_provider_router.py app/data/market_feeds.py`

Result: passed.

Focused router tests:

`venv/Scripts/python.exe -m pytest tests/test_feed_provider_router_failover.py -q`

Result: `12 passed`.

Required feed regressions:

`venv/Scripts/python.exe -m pytest tests/test_kraken_rest_dns_feed_truth_resilience.py tests/test_final_paper_readiness_latency_shadow_proof.py -q`

Result: `20 passed, 93 warnings`.

Related scoped regression slice:

`venv/Scripts/python.exe -m pytest tests/test_market_data_truth_stabilization_for_paper_readiness.py tests/test_config.py tests/test_dynamic_execution_broker_gateway_injection.py -q`

Result: `13 passed, 72 warnings`.

## Shadow-Read-Only Proof

Command:

`timeout 60s venv/Scripts/python.exe main.py --paper --shadow-read-only --log-level INFO`

Result: exited at timeout boundary with code `124`, expected for bounded shadow runtime.

Observed:

- broker mode: paper
- shadow-read-only: enabled
- execution broker: `alpaca_paper`
- execution adapter: `alpaca_paper_rest`
- market-data provider selection explicit
- selected provider at startup: `kraken_public`
- fallback path recorded: `kraken_public -> coinbase_public -> binance_us_public`
- Kraken REST DNS failure recorded
- fallback candidate recorded: `coinbase_public`
- fallback candidate transport reported as not implemented
- no fake fallback market data created
- WebSocket book processing continued

Broker mutation proof:

- `/v2/orders`: 0 matches
- `ORDER_SUBMIT` / order submission markers: 0 matches
- `POST`: 0 matches
- live endpoint marker: 0 matches
- real-money marker: 0 matches

Live endpoint verdict: no live endpoint observed.

## Remaining Signups / Credentials

No signup is required for the current `kraken_public` metadata entry.

`coinbase_public` and `binance_us_public` are registered as public/no-signup candidates, but their runtime transports are not implemented in this packet.

Credential or entitlement required before use:

- `alpaca_market_data`
- `coinmarketcap_reference`
- `tiingo_optional`
- `polygon_or_massive_optional`

## Final Verdict

CONDITIONAL.

The registry, provider selection, failover decision seam, conflict handling, advisory/reference protections, config keys, tests, and non-mutating shadow proof are complete. Kraken is no longer an implicit sole dependency at the selection layer.

The remaining condition is transport depth: Coinbase/Binance.US public providers are registered and selectable as fallback candidates, but their actual data adapters are not implemented yet. Runtime does not fabricate their candles, books, spreads, liquidity, or latency.
