# Market Data Truth Stabilization For Paper Readiness

Packet: POVERTY_KILLER - MARKET DATA TRUTH STABILIZATION FOR EXECUTABLE PAPER READINESS

Report time: 2026-05-21T18:12:00Z

## Starting State

- Starting HEAD: 122c316
- Prior result: CONDITIONAL bounded autonomous external PAPER test
- Prior command: `timeout 300s venv/Scripts/python.exe main.py --paper --log-level INFO`
- Prior safe outcome: no live endpoint, no real-money mode, no `/v2/orders`, no broker POST markers, zero orders, Alpaca PAPER reconciliation succeeded

## Files Changed

- `app/data/websocket_client.py`
- `tests/test_market_data_truth_stabilization_for_paper_readiness.py`
- `reports/market_data_truth_stabilization_for_paper_readiness.md`

No strategy thresholds, risk guardrails, SignalFusion standards, DecisionCompiler criteria, ExecutionEngine mutation path, OrderRouter broker gateway logic, Alpaca adapter logic, state reconciliation, or live trading logic were changed.

## Root Cause From 300-Second Run

The previous run exposed three separate market-data truth issues:

1. Kraken REST DNS remained degraded:
   - Runtime evidence: `Cannot connect to host api.kraken.com:443 ssl:default [Could not contact DNS servers]`
   - Classification remains external/network degradation, not a reason to mark REST healthy.

2. Crossed books entered the runtime parser path:
   - The WebSocket client subscribed to Kraken book depth 10 but kept accumulated local bid/ask maps beyond the subscribed depth.
   - Kraken's official WebSocket v2 book maintenance guide says the local book must be truncated to subscribed depth after each update because levels that fall out of scope do not necessarily arrive later as delete events.
   - Without truncation, stale out-of-scope local levels could survive and later make the accumulated local book cross.

3. Duplicate candles reached MainLoop:
   - Kraken OHLC WebSocket updates can reuse the same interval timestamp while the in-progress candle is updated.
   - MainLoop correctly rejected equal timestamps as duplicate candles, but the duplicate updates were noisy and reached the runtime instead of being quarantined at the feed adapter boundary.

## Implementation Summary

`app/data/websocket_client.py` now:

- Tracks the subscribed book depth as `book_depth`, defaulting to 10.
- Subscribes to Kraken book using that same depth.
- Replaces local bid/ask maps on `snapshot` messages.
- Applies incremental price-level changes on `update` messages.
- Truncates both local bid and ask maps to subscribed depth after every update.
- Rejects crossed books and records machine-readable book quality:
  - `BOOK_QUARANTINED`
  - `CROSSED_BOOK_PREVENTED`
  - source message type
  - best bid / best ask
  - subscribed depth
- Clears the poisoned local accumulator after a crossed local book so later clean feed truth can recover instead of being permanently poisoned by stale local levels.
- Records clean book recovery as `BOOK_ACTIVE` / `CLEAN_BOOK_EMITTED`.
- Suppresses same-timestamp or backward OHLC updates before they reach runtime callbacks:
  - `CANDLE_DUPLICATE_QUARANTINED`
  - `CANDLE_STALE_QUARANTINED`
- Exposes book quality and candle duplicate quarantine counters through `get_stats()` and `get_feed_truth_status()`.

This does not accept crossed books, fabricate missing depth, fabricate candles, lower thresholds, or mark REST healthy when DNS fails.

## Fail-Closed Behavior Preserved

- Crossed books are still rejected, never emitted as valid market truth.
- Missing timestamps are still rejected.
- One-sided books are still not emitted.
- Duplicate or stale candle timestamps are not appended into runtime.
- REST DNS failure remains degraded truth.
- Missing required market truth still reports `FAILED_CLOSED` in focused tests.
- No broker path was touched.

## Tests

Compile:

```bash
venv/Scripts/python.exe -m py_compile app/data/websocket_client.py tests/test_market_data_truth_stabilization_for_paper_readiness.py
```

Result: passed.

Focused test:

```bash
venv/Scripts/python.exe -m pytest tests/test_market_data_truth_stabilization_for_paper_readiness.py -q
```

Result: 5 passed.

Related regression slice:

```bash
venv/Scripts/python.exe -m pytest tests/test_kraken_rest_dns_feed_truth_resilience.py tests/test_ws_book_callback_flow.py tests/test_ws_candle_callback_flow.py -q
```

Result: 20 passed.

Known warnings: existing Pydantic deprecation warnings and existing datetime deprecation warnings.

## Shadow-Read-Only Proof

Command:

```bash
timeout 60s venv/Scripts/python.exe main.py --paper --shadow-read-only --log-level INFO
```

Result: exited with code 124 at the timeout boundary, expected for the bounded command.

Observed proof:

- Broker Mode: paper
- Shadow Read Only: ENABLED
- Execution broker resolved:
  - market_data_venue=kraken
  - execution_broker=alpaca_paper
  - execution_adapter=alpaca_paper_rest
  - shadow_read_only=True
- Internal SovereignPaperBroker not wired.
- OrderRouter route remained `broker_gateway_adapter=alpaca_paper_rest`.
- WebSocket connected and subscribed to book/trade/OHLC.
- Book truth telemetry reported local L2 truncation to subscribed depth 10.
- WebSocket book processing was active:
  - `FEED_BOOK` observed.
  - `[SHANS_DIAG] PROCESSING_BOOK` count in run-window scan: 498.
- Duplicate OHLC updates were quarantined at the WebSocket adapter:
  - `CANDLE_DUPLICATE_QUARANTINED` count in run-window scan: 29.
- Prior MainLoop duplicate rejection marker was absent:
  - `CANDLE_REJECT_DUPLICATE` count in run-window scan: 0.
- Crossed-book marker was absent:
  - `CROSSED_BOOK_PREVENTED` count in run-window scan: 0.
- Latency initially recovered:
  - `Latency recovered: 104.9ms, exiting safe mode`
- Later runtime health recorded stale WebSocket RTT:
  - `LATENCY TRUTH BLOCK: status=STALE_MARKET_TRUTH reason=WEBSOCKET_RTT_STALE`
- Kraken REST DNS remained degraded and truthfully logged.

Mutation proof from focused run-window scans:

- No `/v2/orders`
- No broker POST marker
- No order submission marker
- No broker order ID
- No client order ID
- No live Alpaca endpoint
- No real-money mode marker

POST count proof: no broker POST or `/v2/orders` marker was found in the shadow-read-only run window.

Live endpoint verdict: no live Alpaca endpoint marker was found.

## Source Reference

Kraken's official WebSocket v2 book maintenance guide states that clients must process all updates, remove levels with `qty: 0`, and truncate the book to subscribed depth after each update because out-of-scope levels do not necessarily receive delete events:

- https://docs.kraken.com/api/docs/guides/spot-ws-book-v2/

Kraken's official WebSocket v2 book channel documentation confirms the `book` channel depth values and default depth 10:

- https://docs.kraken.com/api/docs/websocket-v2/book/

## Readiness Impact

Code-side market-data truth handling is improved:

- The parser no longer keeps stale depth beyond the subscribed Kraken book depth.
- Crossed local books are quarantined and no longer allowed to poison the symbol indefinitely.
- Clean later book data recovers in focused tests.
- Duplicate OHLC updates are quarantined before MainLoop.
- WebSocket book truth remained usable while REST DNS was degraded.

The next bounded autonomous PAPER run is not a full PASS-unblocked state yet because external/runtime truth still shows Kraken REST DNS degradation and a later stale WebSocket RTT block in the 60-second proof. A next run would need separate approval and should be treated as conditional unless the network/feed truth is accepted as partial or an additional market data source is approved.

## Final Verdict

CONDITIONAL

The code-side repairs are correct and focused: data guards were not weakened, no fake market truth was created, focused tests and related regressions passed, and the shadow-read-only proof showed zero broker mutation with no live endpoint. Runtime WebSocket book truth improved materially: no crossed-book markers appeared, duplicate candle updates were quarantined before MainLoop, and book processing continued.

The verdict remains conditional because Kraken REST DNS still failed externally during the proof, and WebSocket RTT later became stale. Those are remaining feed/network truth issues, not broker safety violations and not reasons to fabricate readiness.
