# BUNDLE 25S - Concrete Live Adapter Sandbox Read-Only Scout

Verdict: CONDITIONAL

25S confirms the repo has concrete broker read-only fetch foundations, but not a safe standalone concrete live read-only adapter boundary yet. The current concrete read surfaces live inside `OrderRouter`, which also owns submit/cancel mutation paths. No broker/network call was made, no credentials were used, and no live path was activated.

## Tests Run

- `/tmp/pk25i-venv/bin/python -m pytest tests/test_concrete_live_adapter_read_only_scout.py -q`
  - First run: 4 passed, 1 failed because local config represented missing Kraken credentials as empty strings instead of `None`.
  - Final result: 5 passed.
- `/tmp/pk25i-venv/bin/python -m pytest tests/test_micro_live_dry_run_readiness_harness.py tests/test_live_arming_gate_harness.py tests/test_live_adapter_contract_harness.py tests/test_runtime_reservation_bootstrap.py -q`
  - Result: 37 passed.

## Concrete Live Adapter Read-Only Scout

### Concrete Adapter Status

- `app/execution/live_broker.py` is still a stub: under construction, no submit/cancel/read methods, no network implementation.
- `app/execution/broker_adapter.py` is an untracked pre-integration Protocol/contract file, not active authority. It defines account/position/open-order/fill/status methods, but also submit/cancel/replace.
- `app/execution/order_router.py` is the only concrete broker surface found. It has Kraken/Alpaca endpoint definitions and private/read fetch methods, but it is also the active execution router.
- Current concrete status: mixed read/mutate foundation exists; no dedicated concrete read-only adapter exists.

### Import / Config Safety

- `Config` defaults `broker_mode` to `paper`.
- Credentials are optional and not required at import/config construction.
- Missing Kraken credentials fail closed inside `_call_kraken_private()` by returning `None`.
- `OrderRouter` constructs a `requests.Session()` at initialization, but it does not network at import or construction.
- `main.py` wires `OrderRouter(... paper_mode=config.broker_mode == "paper")`; live mode would select the same `OrderRouter` surface that includes submit/cancel.

### Credential / Environment Gating

- Kraken credentials: `kraken_api_key`, `kraken_api_secret`.
- Alpaca credentials: `alpaca_api_key`, `alpaca_api_secret`, `alpaca_paper`.
- Kraken read-only endpoints use the production Kraken REST base URL in current code; there is no explicit Kraken sandbox/testnet marker.
- Alpaca endpoint is set to `https://paper-api.alpaca.markets/v2`, but current Alpaca read/mutate methods do not show a complete credential/header gate in the inspected surface.
- There is no explicit `read_only`, `sandbox_read_only`, no-order, or no-cancel config mode.
- Environment variables could set `broker_mode=live`, but live reservation lifecycle remains blocked.

### Read-Only Capability

Found concrete fetch foundations:

- `fetch_balances()`
- `fetch_open_orders()`
- `fetch_normalized_open_orders()`
- `fetch_fills()`
- `fetch_positions()`
- `get_exchange_truth_snapshot()`
- `get_order_status()` / status query helpers

Gaps:

- No account identity method in the concrete snapshot.
- No explicit environment/sandbox marker in `get_exchange_truth_snapshot()`.
- Kraken positions are derived from fills, not broker position truth.
- Open-order and fill data require normalization before satisfying 25M-25R fields.
- Status lookup is available, but it is in the same object as mutating submit/cancel.

### No-Order / No-Cancel Safety

- Current `OrderRouter` has `submit_order()`, `_submit_order_kraken()`, `_submit_order_alpaca()`, `cancel_order()`, `_cancel_order_kraken()`, and `_cancel_order_alpaca()` in the same class as read fetchers.
- There is no current constructor flag that makes submit/cancel unavailable while allowing read methods.
- A future broker call should not use raw `OrderRouter` live mode directly for read-only proof.
- Safe next step requires a wrapper/gate that exposes only read methods and blocks submit/cancel by construction.

### Mapping To 25M-25R Contracts

Current concrete foundations can partially map:

- Balances: maps to balance truth, but needs available/held semantics and currency normalization.
- Open orders: maps to broker/client/order ID truth, status, symbol, side, quantity, remaining quantity, source/mapping fields.
- Fills/trades: maps to order ID, trade/fill ID, quantity, price, fee, timestamp; needs fee currency/source mapping.
- Status lookup: maps to terminal/cancel/status truth, but must remain read-only and known-ID only.
- Positions: currently reconstructive for Kraken; must be labeled as derived unless a broker-native position source exists.
- Account identity and environment marker remain missing in the concrete snapshot.

### Sandbox / Read-Only Feasibility

- Feasible only after a small read-only wrapper/config gate.
- Not safe to call broker from the current active router surface because read-only and mutating authority are not separated.
- No Board authorization for credentials/network calls was provided in 25S, so this packet did not call broker APIs.

## Recommended Next Packet

- 25T - Live Adapter Read-Only Wrapper / Config Gate Harness

Why this is the single next seam:

- It is the smallest safe step between offline dry-run and real sandbox/read-only broker truth.
- It preserves the existing `OrderRouter` authority while preventing raw live submit/cancel exposure.
- It can prove no-order/no-cancel safety, lazy credentials, explicit sandbox/read-only environment selection, and contract mapping before any real broker call.

## Remaining Blockers

- No dedicated concrete read-only adapter wrapper.
- No explicit no-order/no-cancel construction mode.
- No explicit sandbox/read-only config gate.
- No account identity in concrete exchange truth snapshot.
- No environment/source marker in concrete exchange truth snapshot.
- Kraken sandbox/testnet support is not explicit.
- Alpaca auth/header behavior needs a read-only wrapper review before any call.
- Broker calls still require explicit Board credential/network authorization.

## Authority Boundaries

- 25S inspected repo truth and added a static/offline scout test only.
- It did not activate `broker_adapter.py` or `live_broker.py`.
- It did not activate live mode or live reservation lifecycle.
- It did not implement a concrete live adapter.
- It did not make network calls, use credentials, query account/balance/status, submit orders, or send cancels.

## Confirmations

- Production behavior changed: no
- Real broker/network call made: no
- Credentials used: no
- Live account/balance/status query made: no
- Live order placed: no
- Live cancel sent: no
- Live mode used: no
- broker_adapter edited/activated: no
- live_broker edited/activated: no
- Live reservation lifecycle activated: no
- Concrete live adapter implemented: no
- Dormant governors activated: no
- Thresholds changed: no
- Routing/execution broadened: no
- Duplicate authority introduced: no
- Git staging/commit/push/reset/clean/stash/delete: none
