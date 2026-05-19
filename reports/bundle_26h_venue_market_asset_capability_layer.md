# BUNDLE 26H - Venue / Market / Asset-Class Capability Layer

Verdict: PASS

Run timestamp:
- `2026-05-19T05:54:27Z`

Exact Kraken-only blocker fixed:
- Prior observed runtime selection collapsed to:
  - `primary_feed_venue = kraken`
  - `active_markets = ['crypto']`
  - `symbol_universe = BTC/USD, ETH/USD, SOL/USD`
  - `active_symbols = BTC/USD, ETH/USD, SOL/USD`
- 26H adds a capability-aware candidate surface that carries venue, asset class, environment, quote source, execution adapter, and reconciliation adapter.
- Legacy `get_active_symbols()` still returns the current Kraken feed symbols for compatibility.
- New `get_active_capability_candidates()` can represent a mixed surface:
  - `kraken / crypto / BTC/USD / sovereign_paper_broker`
  - `alpaca / crypto / BTC/USD / alpaca_paper_rest`
  - `alpaca / equity / AAPL / alpaca_paper_rest`
  - `alpaca / etf / SPY / alpaca_paper_rest`

Production files changed:
- `app/market/__init__.py`
- `app/market/venue_capabilities.py`
- `app/market/capability_registry.py`
- `app/config.py`
- `main.py`

Test/report files changed:
- `tests/test_venue_market_asset_capability_layer.py`
- `reports/bundle_26h_venue_market_asset_capability_layer.md`

Capability model summary:
- Added `VenueCapability` with:
  - `venue_id`
  - `portal_name`
  - `environment`
  - `asset_class`
  - `symbol`
  - `normalized_symbol`
  - `venue_symbol_format`
  - `quote_source`
  - `market_data_available`
  - `tradability_source`
  - `supported_order_types`
  - `supported_time_in_force`
  - `fractional_support`
  - `min_notional`
  - `min_quantity`
  - `quantity_step`
  - `market_session_status_source`
  - `execution_adapter`
  - `reconciliation_adapter`
  - `read_only`
  - `paper_mutation`
  - `sandbox_mutation`
  - `live_mutation`
  - `live_blocked`
  - disabled/unavailable/fail-closed reason fields
- Added `CapabilityAwareCandidate` so runtime selection can carry structured identity instead of only a plain symbol.
- Capability presence explicitly does not authorize mutation:
  - `mutation_authorized_by_default`: `False`
  - candidate `mutation_authorized`: `False`

Capability registry summary:
- Added `VenueCapabilityRegistry`.
- Added default static capability fixture for currently represented portals.
- Static fixture is capability metadata only; it does not create quotes, fills, prices, broker constraints, PnL, slippage, net edge, or profitability.
- Added resolution helpers for:
  - configured portals
  - usable portals
  - symbol capabilities
  - asset-class capabilities
  - operator portal selection
  - capability-aware candidate identity building

Alpaca PAPER equity capability:
- Represented for US equity symbols such as `AAPL`, `MSFT`, `NVDA`, `AMZN`, `META`, `GOOGL`, `JPM`, `JNJ`, and `WMT`.
- Environment: `paper`
- Quote source identity: `alpaca_data_latest_quote`
- Execution adapter identity: `alpaca_paper_rest`
- Reconciliation adapter identity: `alpaca_paper_rest_reconciliation`
- Live blocked: yes
- Mutation authorized by default: no

Alpaca PAPER ETF / US equity handling:
- ETF is represented as a distinct `etf` asset class for `SPY`, `QQQ`, and `DIA`.
- ETF metadata includes `etf_capable = True`.
- Execution/reconciliation identities use Alpaca PAPER.
- Live blocked: yes
- Mutation authorized by default: no

Alpaca PAPER crypto capability:
- Represented for `BTC/USD`, `ETH/USD`, and `SOL/USD`.
- Venue identity remains `alpaca`, distinct from Kraken.
- Quote source identity: `alpaca_data_crypto_latest_quote`
- Execution adapter identity: `alpaca_paper_rest`
- Reconciliation adapter identity: `alpaca_paper_rest_reconciliation`
- Live blocked: yes
- Mutation authorized by default: no

Kraken crypto preservation:
- `BTC/USD`, `ETH/USD`, and `SOL/USD` remain represented under `kraken_paper`.
- Execution adapter identity remains `sovereign_paper_broker`.
- Quote source identity remains `kraken_websocket_or_polling`.
- Existing raw-symbol feed compatibility is preserved through `get_active_symbols()`.

Future venue placeholder behavior:
- Disabled/fail-closed placeholders were added for:
  - `coinbase`: `ADAPTER_MISSING`
  - `interactive_brokers`: `CREDENTIALS_MISSING`
  - `schwab`: `NOT_CONFIGURED`
  - `tradier`: `CAPABILITY_UNPROVEN`
  - `binance_us`: `ADAPTER_MISSING`
- Future placeholders do not execute.
- Paper/sandbox/live mutation is disabled on placeholders.

Operator portal-selection policy:
- Added config knobs:
  - `portal_selection_policy`
  - `preferred_trading_portal`
  - `allow_portal_fallback`
  - `enabled_trading_portals`
- Default policy is `explicit_preferred_venue` with `preferred_trading_portal = alpaca_paper`, matching current Board policy that Alpaca PAPER is preferred where it supports the request.
- Supported policy modes:
  - `explicit_preferred_venue`
  - `capability_first`
  - `fail_closed`
- Preferred venue selection succeeds only when the requested portal supports symbol, asset class, environment, action, order type, and TIF.
- Unsupported preferred venue fails closed unless fallback is explicitly enabled.

Ambiguous venue fail-closed behavior:
- If both Alpaca PAPER and Kraken PAPER can support `BTC/USD` crypto and `capability_first` has no tie-break, resolution returns `AMBIGUOUS_PORTAL`.
- No fee/speed/spread/liquidity ranking was invented.
- Missing portal-quality metrics remain `UNKNOWN`.

Live blocked confirmation:
- Live environment is represented by a blocked Alpaca live placeholder.
- Live mutation remains disabled.
- No live endpoint was activated.

Mutation blocked by default confirmation:
- Capability records can state that a portal supports paper mutation as a capability.
- Candidate identity still reports `mutation_authorized = False`.
- 26H did not submit orders.
- 26H did not POST/PATCH/DELETE/cancel/replace/sell/rebalance.

Runtime selection no longer Kraken-only:
- `main.py` now exposes `get_active_capability_candidates()`.
- `SovereignHeartbeat` stores capability-aware candidates in `_capability_candidates`.
- `get_status()` reports capability identities.
- Existing `active_symbols` remains a legacy feed-symbol set for the current MainLoop string-symbol contract.
- A mixed config scenario produced:
  - `('kraken', 'crypto', 'BTC/USD', 'sovereign_paper_broker', False)`
  - `('alpaca', 'crypto', 'BTC/USD', 'alpaca_paper_rest', False)`
  - `('alpaca', 'equity', 'AAPL', 'alpaca_paper_rest', False)`
  - `('alpaca', 'etf', 'SPY', 'alpaca_paper_rest', False)`

Integrated baseline result:
- Integrated baseline passed with all mutation approval flags unset:
  - `31 passed, 72 warnings in 9.83s`

Tests run:
- `/tmp/pk25i-venv/bin/python -m pytest tests/test_venue_market_asset_capability_layer.py -q`
  - result: `12 passed, 72 warnings in 5.59s`
- `env -u POVERTY_KILLER_APPROVE_ALPACA_PAPER_TINY_ORDER_25Z -u POVERTY_KILLER_APPROVE_ALPACA_PAPER_10_SYMBOL_BATCH_26B -u POVERTY_KILLER_APPROVE_ALPACA_PAPER_10_SYMBOL_EXPANSION_26G /tmp/pk25i-venv/bin/python -m pytest tests/test_venue_market_asset_capability_layer.py tests/test_integrated_paper_portfolio_machine_seam.py tests/test_controlled_paper_portfolio_lifecycle_exit_defense.py tests/test_controlled_paper_portfolio_runtime_exposure_response.py tests/test_live_read_only_adapter_config_gate.py -q`
  - sandbox result: `3 failed, 28 passed, 72 warnings in 9.70s`
  - failures were DNS failures for existing Alpaca PAPER read-only GET tests.
  - no broker mutation occurred.
- `env -u POVERTY_KILLER_APPROVE_ALPACA_PAPER_TINY_ORDER_25Z -u POVERTY_KILLER_APPROVE_ALPACA_PAPER_10_SYMBOL_BATCH_26B -u POVERTY_KILLER_APPROVE_ALPACA_PAPER_10_SYMBOL_EXPANSION_26G /tmp/pk25i-venv/bin/python -m pytest tests/test_venue_market_asset_capability_layer.py tests/test_integrated_paper_portfolio_machine_seam.py tests/test_controlled_paper_portfolio_lifecycle_exit_defense.py tests/test_controlled_paper_portfolio_runtime_exposure_response.py tests/test_live_read_only_adapter_config_gate.py -q`
  - escalated read-only result: `31 passed, 72 warnings in 9.83s`

Safety confirmations:
- No live endpoint used.
- No live mode used.
- No live adapter activation.
- No live reservation lifecycle activation.
- No broker mutation.
- No actual orders.
- No fake symbols.
- No fake quote/price/quantity/fill/economic facts.
- No invented cost/speed/fee rankings.
- No invented PnL/slippage/net edge/profitability.
- No threshold changes.
- No dormant governors activated as authority.
