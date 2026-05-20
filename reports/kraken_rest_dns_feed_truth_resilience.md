# Kraken REST DNS Feed Truth Resilience

Current HEAD at start: `ecd0f80`.

## Root Cause

The bounded Seam 7H shadow run proved Kraken websocket ingress could connect and deliver market messages, while Kraken REST polling for `api.kraken.com` candles/order books repeatedly failed DNS. Before this burn-down, the REST polling path recorded a last failure, but the combined runtime feed truth did not explicitly classify the mixed state as websocket-active plus REST-DNS-degraded.

## Files Inspected

- `app/data/polling_client.py`
- `app/data/websocket_client.py`
- `app/data/market_feeds.py`
- `app/data/aggregator.py`
- `app/data/depth_book.py`
- `app/monitoring/health.py`
- `app/monitoring/alerts.py`
- `app/core/decision_compiler.py`
- `app/models/contracts.py`
- Seam 7G/7H tests covering market truth and operator monitoring.

## Files Changed

- `app/data/polling_client.py`
- `app/data/websocket_client.py`
- `app/data/market_feeds.py`
- `app/monitoring/health.py`
- `app/monitoring/alerts.py`
- `tests/test_kraken_rest_dns_feed_truth_resilience.py`
- `reports/kraken_rest_dns_feed_truth_resilience.md`

## Feed Truth State Model

Added/preserved machine-readable states:

- `WEBSOCKET_ACTIVE`
- `REST_ACTIVE`
- `DNS_FAILURE_RECORDED`
- `REST_POLLING_FAILED`
- `REST_POLLING_DEGRADED`
- `WEBSOCKET_ACTIVE_REST_DNS_FAILED`
- `MARKET_DATA_PARTIAL_TRUTH`
- `MISSING_CANDLE_TRUTH`
- `MISSING_ORDER_BOOK_TRUTH`
- `STALE_MARKET_TRUTH`
- `FAILED_CLOSED`

## PollingClient DNS Behavior

`PollingClient` now:

- classifies DNS connector failures as `DNS_FAILURE_RECORDED`
- classifies timeouts/connector failures as `REST_POLLING_FAILED` when not DNS-specific
- records safe endpoint domain only, for example `api.kraken.com`
- records missing candle/order-book truth by symbol and feed type
- keeps failure history and per-symbol/feed failure status
- emits optional local feed-truth callback packets
- does not return fake candles or fake order books
- does not mark REST healthy when REST failed

## Websocket / REST Partial Truth

`KrakenWebSocketClient` now exposes `get_feed_truth_status()` with websocket-only provenance.

`MarketFeeds` now combines websocket and REST truth:

- websocket active + REST DNS failure => `WEBSOCKET_ACTIVE_REST_DNS_FAILED`
- combined market truth => `MARKET_DATA_PARTIAL_TRUTH`
- missing REST-derived candle/book truth stays explicit
- websocket truth is not relabeled as REST truth
- downstream modules can use explicit provenance to degrade or fail closed

## Monitoring And Alerts

`HealthMonitor.record_market_data_truth()` records degraded feed truth as component metadata and preserves reason codes such as `REST_DNS_FAILURE` and `DEGRADED_MARKET_DATA`.

`SovereignSentinel.alert_rest_dns_failure()` creates a local `REST_DNS_FAILURE` alert record. External webhook/Telegram dispatch remains disabled unless configured and explicitly started.

## Tests

Focused deterministic test file:

```bash
venv/Scripts/python.exe -m pytest -q tests/test_kraken_rest_dns_feed_truth_resilience.py
```

Result: `7 passed`.

Coverage:

- mocked DNS failure becomes `DNS_FAILURE_RECORDED`
- no fake candle/order-book truth is emitted
- websocket active + REST DNS failure becomes `WEBSOCKET_ACTIVE_REST_DNS_FAILED`
- `MarketFeeds` preserves websocket provenance and missing REST truth
- health reports `REST_DNS_FAILURE`
- alerts create local records without external dispatch
- DecisionCompiler carries market-data attribution metadata
- no broker mutation, no live network call, no fake market facts

## Regression

Scoped non-mutating regression to run:

```bash
venv/Scripts/python.exe -m pytest -q tests/test_seam7g_market_truth_reconciliation_spine.py tests/test_seam7h_operator_monitoring_shadow_launch_readiness.py tests/test_seam7e_strategy_fusion_runtime_wiring.py tests/test_intelligence_portfolio_state_truth_spine.py
```

Result: `30 passed`.

Compile check:

```bash
venv/Scripts/python.exe -m py_compile app/data/polling_client.py app/data/websocket_client.py app/data/market_feeds.py app/data/aggregator.py app/data/depth_book.py app/brain/signal_fusion.py app/core/decision_compiler.py app/monitoring/health.py app/monitoring/alerts.py app/monitoring/reports.py tests/test_kraken_rest_dns_feed_truth_resilience.py
```

Result: passed.

## Safety Confirmation

- No live endpoint was added.
- No broker mutation path was added.
- No orders, cancels, sells, rebalances, or emergency liquidation paths were touched.
- No secrets are read, printed, copied, or committed.
- No fake candles, fake order books, fake quotes, fake PnL, fake slippage, fake fees, fake net edge, or fake profitability were created.

## Launch Blocker #2 Status

`CLEARED_AT_DETERMINISTIC_LEVEL`

Reason: the bot now classifies Kraken websocket-active / REST-DNS-failed as explicit partial market truth instead of vague network noise. Runtime shadow verification remains optional and requires separate approval.

## Remaining Launch Blockers

- Blocker #1 remains: critical `HEALTH ALERT: Physical fuse triggered`.
- Blocker #3 remains: Alpaca PAPER read-only reconciliation truth was not proven in bounded shadow.
