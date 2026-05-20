# Seam 7G Market Truth Reconciliation Spine

Current HEAD before Seam 7G work: `15f475f`

## Files Changed

- `app/data/aggregator.py`
- `app/data/depth_book.py`
- `app/data/market_feeds.py`
- `app/data/polling_client.py`
- `app/market/venue_capabilities.py`
- `app/snapshot_exporter.py`
- `app/core/decision_compiler.py`
- `tests/test_seam7g_market_truth_reconciliation_spine.py`
- `reports/seam7g_market_truth_reconciliation_spine.md`

## Contract Findings And Repairs

- `KrakenWebSocketClient` already provides lawful market ingress and emits canonical `OrderBookSnapshot` records from Kraken v2 book messages with nested exchange timestamps. No broker authority was found.
- `MarketFeeds` stored order books but still attempted to read non-canonical `order_book.market_depth`. It now derives depth from canonical `OrderBookSnapshot.depth_at_levels(10)`.
- `PollingClient` REST fallback failures were logged but not exposed as machine-readable feed truth. It now records `last_failure_status`, including `DNS_FAILURE_RECORDED` for connector/DNS failures and `FAILED_CLOSED` for other polling exceptions.
- `DepthBook` consumed canonical `OrderBookSnapshot` but still read legacy `snapshot.timestamp`. It now derives its display timestamp from canonical `exchange_ts_ns` and keeps `exchange_ts_ns` as the authoritative timestamp.
- `MultiMarketAggregator` had an import-time dataclass slot conflict on `Tick`. It now uses native dataclass slots without changing tick fields or aggregation math.
- `CapabilityAwareCandidate` dropped broker constraint fields from `VenueCapability`. It now carries `fractional_support`, `min_notional`, `min_quantity`, and `quantity_step` through the candidate identity.
- `SnapshotExporter` imported orphaned legacy symbols from `app.models`. It now imports only canonical runtime models from `app.models`; legacy snapshot-only payloads remain duck-typed and no new fake canonical models were created.
- `DecisionCompiler` metadata validation now permits Seam 7G market truth sections: market data, venue capability, instrument registry, broker truth, truth reconciliation, state hydration, session/snapshot/replay, and market truth summary.

## Runtime Authority Boundaries

- Market data modules provide feed, book, depth, aggregation, validation, and replay evidence only.
- Venue capability and instrument registry provide capability/session/constraint truth only.
- Alpaca PAPER adapter remains paper-endpoint constrained; read-only GET proof recorded `GET: 3`, `POST: 0`.
- Live read-only adapter exposes broker truth snapshots without submit/cancel mutation surfaces.
- Truth reconciliation reports canonical broker/exchange/local truth alignment or divergence; it does not mutate broker or local execution state.
- StateStore and SnapshotExporter remain supporting local evidence only.
- No execution authority was moved into data, capability, replay, state, or snapshot modules.

## Test Proof

- Compile:
  - `venv/Scripts/python.exe -m py_compile app/data/websocket_client.py app/data/market_feeds.py app/data/polling_client.py app/data/depth_book.py app/data/aggregator.py app/data/feature_builder.py app/data/ghost_tick_detector.py app/data/validators.py app/market/venue_capabilities.py app/market/capability_registry.py app/instrument_registry.py app/core/truth_reconciler.py app/core/intelligence_portfolio_state_truth_spine.py app/state/hydration_manager.py app/state/state_store.py app/session_manager.py app/snapshot_exporter.py app/execution/broker_gateway.py app/execution/alpaca_paper_adapter.py app/execution/live_read_only_adapter.py app/execution/engine.py app/brain/signal_fusion.py app/core/decision_compiler.py tests/test_seam7g_market_truth_reconciliation_spine.py`
  - Result: passed.
- Focused Seam 7G:
  - `venv/Scripts/python.exe -m pytest -q tests/test_seam7g_market_truth_reconciliation_spine.py`
  - Result: `5 passed`.
- Scoped regression:
  - `venv/Scripts/python.exe -m pytest -q tests/test_seam7e_strategy_fusion_runtime_wiring.py tests/test_seam7e_residual_math_model_repair.py tests/test_seam7f_risk_capital_defense_execution_economics.py tests/test_intelligence_portfolio_state_truth_spine.py tests/test_broker_gateway_adapter_layer.py tests/test_execution_spine_order_routing.py tests/test_pre_trade_guardrail_constraints.py`
  - Result: `63 passed`.

## Safety Confirmation

- No `main.py` runtime command was run.
- No mutation approval flags were set.
- No live endpoint or live mode was used.
- No broker POST/PATCH/DELETE/cancel/replace/sell/rebalance was performed.
- No fake feeds, fake broker facts, fake fills, fake PnL, fake slippage, fake net edge, or fake profitability were introduced.
- Broker/exchange truth remains canonical; local state remains supporting evidence.

## Remaining Blockers

- No Seam 7G blocker remains.
- Existing unrelated dirty/untracked worktree files were not staged, cleaned, reset, stashed, or deleted.
