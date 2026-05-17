# BUNDLE 25U - Alpaca Paper Read-Only Broker Truth Harness

Verdict: PASS

25U passed from the Board terminal where Alpaca PAPER environment variables were visible. The harness made real Alpaca PAPER read-only broker/network calls, used env-var credentials only, and did not print or write secrets.

The harness treats a successful `/v2/positions` response of `[]` as valid broker position truth. Positions may validly be empty. It still requires the positions endpoint to be called, still rejects invalid positions payload shape, and still validates `symbol` and decimal `qty` for non-empty position rows.

## Tests Run

- `/tmp/pk25i-venv/bin/python -m pytest tests/test_alpaca_paper_read_only_broker_truth.py -q -s`
  - Board terminal result: `2 passed in 1.50s`
- `/tmp/pk25i-venv/bin/python -m pytest tests/test_live_read_only_adapter_config_gate.py tests/test_micro_live_dry_run_readiness_harness.py tests/test_live_arming_gate_harness.py tests/test_live_account_position_balance_reconciliation_harness.py -q`
  - Baseline result: `30 passed, 72 warnings`

## Pre-Broker Safety Verification

- Exact paper endpoint required: `https://paper-api.alpaca.markets`.
- Live/prod endpoint is rejected before network.
- HTTP helper constructs `urllib.request.Request(..., method="GET", ...)` only.
- Allowed GET paths are explicit:
  - `/v2/account`
  - `/v2/positions`
  - `/v2/orders`
  - `/v2/account/activities`
  - `/v2/clock`
- `/v2/orders` is allowed only with `status=open`.
- Mutation-shaped paths containing `submit`, `cancel`, `replace`, `close`, or `liquidate` are rejected before network.
- Local negative guard test verifies rejection of:
  - `/v2/orders` with `status=all`
  - `/v2/orders/abc/cancel`
  - `/v2/account/configurations`
  - `https://api.alpaca.markets`

## Alpaca Paper Read-Only Broker Truth

### Environment / Base URL

- Paper endpoint used: yes.
- Endpoint: `https://paper-api.alpaca.markets`.
- Real broker/network call made: yes, Alpaca PAPER read-only only.
- Live endpoint used: no.

### Credential Handling

- Credentials used: yes, env vars only.
- Secrets printed: no.
- Secrets written: no.

### Account / Balance Truth

- Real Alpaca PAPER account/balance read-only truth was requested through `GET /v2/account`.
- No account or balance values were invented in this report.

### Positions Truth

- Real Alpaca PAPER positions read-only truth was requested through `GET /v2/positions`.
- Positions may validly be empty.
- `positions_count` may be `0`.
- Successful `[]` is valid broker truth.
- Non-empty positions still require valid row shape, non-empty `symbol`, and decimal `qty`.
- Missing endpoint call, invalid payload shape, missing symbol, missing qty, or non-decimal qty still fails the harness.

### Open Orders Truth

- Real Alpaca PAPER open-orders read-only truth was requested through `GET /v2/orders?status=open`.
- HTTP method used: GET only.
- Order placed: no.
- Cancel sent: no.
- Replace sent: no.

### Recent Activities / Fills Truth

- Real Alpaca PAPER activities/fills read-only truth was requested through `GET /v2/account/activities?activity_types=FILL`.

### Snapshot Mapping

- The harness maps successful read-only results through `LiveReadOnlyBrokerAdapter`.
- The prepared snapshot shape carries source, environment, account id, balances, positions, open orders, recent fills, receive timestamp, read-only flag, and mutation block.
- Empty positions are valid broker truth for 25U.

## Authority Boundaries Confirmed

- Real broker/network call made: yes, Alpaca PAPER read-only only.
- Paper endpoint used: yes.
- Credentials used: yes, env vars only, not printed/written.
- HTTP methods used: GET only.
- Order placed: no.
- Cancel sent: no.
- Replace sent: no.
- Live mode used: no.
- Live reservation lifecycle activated: no.
- broker_adapter edited or activated: no.
- live_broker edited or activated: no.
- Production behavior changed: no.
- Baseline passed: yes.
- Concrete mutating live adapter implemented: no.
- Dormant governors activated: no.
- Thresholds changed: no.
- Routing/execution broadened: no.
- Duplicate authority introduced: no.
- Secrets printed/written/committed: no.
- Git staging/commit/push/reset/clean/stash/delete: none.
