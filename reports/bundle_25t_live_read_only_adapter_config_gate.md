# BUNDLE 25T - Live Adapter Read-Only Wrapper / Config Gate Harness

Verdict: PASS

25T adds and proves a non-executing read-only broker truth boundary. The new wrapper is dependency-injected, performs no broker/network work by itself, exposes only read methods, fails closed on ambiguous config, and cannot forward submit/cancel/replace methods even when the injected underlying object has them.

## Tests Run

- `/tmp/pk25i-venv/bin/python -m pytest tests/test_live_read_only_adapter_config_gate.py -q`
  - Result: 6 passed
- `/tmp/pk25i-venv/bin/python -m py_compile app/execution/live_read_only_adapter.py`
  - Result: passed
- `/tmp/pk25i-venv/bin/python -m pytest tests/test_concrete_live_adapter_read_only_scout.py tests/test_micro_live_dry_run_readiness_harness.py tests/test_live_arming_gate_harness.py tests/test_live_adapter_contract_harness.py tests/test_runtime_reservation_bootstrap.py -q`
  - Result: 42 passed

## Read-Only Broker Truth Boundary Proven

### Config / Read-Only Gate

- `ReadOnlyAdapterConfig` requires explicit `read_only_enabled=True`.
- `allow_mutation=True` fails closed.
- Missing source/broker name fails closed.
- Missing environment marker fails closed.
- Production/live/prod environment fails closed without being accepted as sandbox/read-only.
- Missing account identity fails closed when account identity is required.
- Missing credentials do not fail import/construction, but block actual read calls when credentials are required.
- Missing or stale snapshot timestamp blocks readiness before source calls.

### Wrapper Method Surface

Exposes only:

- `get_account_identity()`
- `fetch_balances()`
- `fetch_positions()`
- `fetch_open_orders()`
- `fetch_recent_fills()`
- `fetch_order_status_read_only()`
- `get_exchange_truth_snapshot()`
- `validate_gate()`

Does not expose:

- `submit_order()`
- `cancel_order()`
- `replace_order()`
- `place_order()`
- `place_market_order()`
- `place_limit_order()`

### No-Order / No-Cancel Safety

- Test fake underlying object includes `submit_order`, `cancel_order`, and `replace_order`.
- The wrapper has no matching mutation attributes.
- Attempted mutation-method access raises `AttributeError`.
- Read methods call only read surfaces on the injected object.
- Blocked gates do not call the underlying object.

### Snapshot / Account / Environment Identity

`ReadOnlyBrokerSnapshot` carries:

- source
- environment
- account_id
- account identity status
- balances
- positions
- open orders
- recent fills
- optional order statuses
- receive timestamp
- as-of timestamp
- `read_only=True`
- `mutation_allowed=False`
- reason/status fields

### Mapping To 25M-25R Contracts

The wrapper snapshot shape can carry:

- account/source/environment/timestamp for 25Q
- balance currency/available/total for 25Q
- position symbol/instrument/quantity for 25Q
- open order client/broker/status evidence for 25O/25Q
- recent fill ID/quantity/price/fee/currency/timestamps for 25P/25Q
- no-submit/no-cancel/read-only boundary for 25M-25R

### Fail-Closed Cases

- default/empty config
- `read_only_enabled=False`
- `allow_mutation=True`
- missing environment marker
- production environment
- missing source/broker name
- missing required account identity
- missing credentials for actual read call
- attempted mutation method access
- missing snapshot timestamp
- stale snapshot timestamp

## Production Behavior Changed

- yes
- Exact non-executing read-only behavior only:
  - Added `app/execution/live_read_only_adapter.py`.
  - It defines a read-only wrapper/config gate and snapshot shape.
  - It is not wired into runtime.
  - It does not import or activate `broker_adapter.py` or `live_broker.py`.
  - It performs no network calls by itself.

## Remaining Blockers

- No Board-authorized broker/sandbox credential/network call has been made.
- No real broker read-only response has been mapped yet.
- No concrete account identity from broker has been proven.
- No production runtime wiring to the read-only wrapper exists yet.
- Kraken sandbox/testnet behavior remains unproven.
- Alpaca auth/header read-only behavior remains unproven.
- Live arming still must remain blocked until real read-only broker truth is proven.

## Recommended Next Packet

- 25U - Sandbox Read-Only Broker Truth Harness

Why this is the single next seam:

- 25T separates read-only broker truth from mutation authority.
- The next useful proof is to inject a Board-authorized sandbox/read-only source into this wrapper and map the returned read-only facts into the 25Q/25P/25O reconciliation contracts.
- Without that, another offline-only contract packet would repeat already-proven boundaries.

## Authority Boundaries

- The wrapper may validate config, expose read-only snapshot shape, normalize injected read facts, and fail closed.
- It may not submit, cancel, replace, mutate reservations, record production live fills, decide live readiness, decide profitability, or become execution/risk/economics authority.
- No `OrderRouter` live submit/cancel path was touched.
- `broker_adapter.py` and `live_broker.py` remain inactive.

## Confirmations

- Real broker/network call made: no
- Credentials used: no
- Live account/balance/status query made: no
- Live order placed: no
- Live cancel sent: no
- Live mode used: no
- broker_adapter edited/activated: no
- live_broker edited/activated: no
- Live reservation lifecycle activated: no
- Concrete mutating live adapter implemented: no
- Dormant governors activated: no
- Thresholds changed: no
- Routing/execution broadened: no
- Duplicate authority introduced: no
- Git staging/commit/push/reset/clean/stash/delete: none
