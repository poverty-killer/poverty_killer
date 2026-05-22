# Bounded 20-Minute Autonomous Paper Run

Date: 2026-05-22

Packet: APPROVED PACKET - 20-MINUTE BOUNDED AUTONOMOUS PAPER RUN

Starting HEAD: `5c118a0` - Add paper runbook and credential authority guard

Branch: `master`

Requested command:

```bash
timeout 1200s venv/Scripts/python.exe main.py --paper --log-level INFO
```

## Summary

The 20-minute autonomous PAPER observation did not lawfully start.

The new credential authority guard and read-only Alpaca PAPER preflight passed, but the Windows venv process launched from this WSL shell did not receive the WSL runtime configuration for `POVERTY_KILLER_EXECUTION_BROKER` and market-data provider env vars. Runtime startup selected `internal_paper` instead of `alpaca_paper` and then failed closed with `MISSING_MARKET_DATA_PROVIDER_CONFIG`.

This is a launch-environment blocker, not a broker safety failure. No broker POST, order placement, cancel/replace, live endpoint, or real-money mode was observed.

## Pre-Run Git State

- Branch: `master`
- HEAD: `5c118a0`
- HEAD includes `5c118a0`: yes
- Unrelated dirty state existed before this packet in `state/risk_state.json` and `state/risk_state.tmp`; those files were not staged or intentionally modified by this packet.

## Credential Authority Guard / Read-Only Preflight

Command path:

- stale Alpaca env values cleared
- `/home/shahn/.poverty_killer_alpaca_paper_env` explicitly sourced
- `collect_alpaca_paper_read_only_preflight_truth(timeout=20.0)` executed

Result:

- credential authority status: `CREDENTIAL_AUTHORITY_OK`
- preflight status: `PAPER_READ_ONLY_PREFLIGHT_PASSED`
- endpoint: `https://paper-api.alpaca.markets`
- account status: `ACTIVE`
- positions before attempted run: 7
- open orders before attempted run: 0
- GET count: 3
- POST count: 0
- `live_endpoint_used=false`
- `mutation_occurred=false`
- stale process-env credential conflict: false

## Local Runtime Safety State

Risk state before launch attempt:

- `physical_fuse_triggered=false`
- current equity: 20000.0
- high water mark: 20000.0
- physical fuse: 15000.0
- last reset audit classification: `PHYSICAL_FUSE_CLEARED`
- reset evidence broker environment: paper
- reset evidence broker/local conflict: false
- reset evidence GET count: 3
- reset evidence POST count: 0

Credential/run config visible in the WSL shell after sourcing:

- `APCA_API_BASE_URL=https://paper-api.alpaca.markets`
- `POVERTY_KILLER_EXECUTION_BROKER=alpaca_paper`
- `POVERTY_KILLER_MARKET_DATA_PROVIDERS=coinbase_public,kraken_public`
- `POVERTY_KILLER_CRYPTO_MARKET_DATA_PROVIDERS=coinbase_public,kraken_public`

## Launch Attempt

The approved bounded command was attempted from WSL with the credential file sourced:

```bash
timeout 1200s venv/Scripts/python.exe main.py --paper --log-level INFO
```

Observed startup truth:

- paper mode: enabled
- shadow-read-only: disabled
- attack mode: disabled
- broker mode: paper
- runtime selected execution broker: `internal_paper`
- runtime selected primary exchange: `kraken`
- runtime selected execution adapter: `internal_sovereign_paper_broker`
- OrderRouter route: `paper_mode=True execution_broker=internal_paper primary_exchange=kraken broker_gateway_adapter=None`

The process then raised:

```text
RuntimeError: MISSING_MARKET_DATA_PROVIDER_CONFIG
```

Runtime did not reach the 20-minute autonomous observation loop.

## Stop Condition Triggered

The packet required stopping if:

- execution broker is not `alpaca_paper`
- internal paper fallback appears

Both appeared in startup logs. Therefore the run was stopped/fail-closed.

## Launch Environment Diagnosis

A non-mutating Windows venv resolver precheck was attempted with WSL exports for:

- `POVERTY_KILLER_EXECUTION_BROKER=alpaca_paper`
- `POVERTY_KILLER_MARKET_DATA_PROVIDERS=coinbase_public,kraken_public`
- `POVERTY_KILLER_CRYPTO_MARKET_DATA_PROVIDERS=coinbase_public,kraken_public`
- `POVERTY_KILLER_RUNTIME_WATCHLIST=BTC/USD,ETH/USD,SOL/USD`

The Windows venv process still resolved:

- execution broker: `internal_paper`
- adapter: `internal_sovereign_paper_broker`
- configured crypto providers: empty
- provider result: `MISSING_MARKET_DATA_PROVIDER_CONFIG`

This indicates WSL exports are not reliably crossing into the Windows venv process environment.

Additional Windows-side env injection attempts through `cmd.exe` and `powershell.exe` were blocked from this WSL shell with:

```text
UtilBindVsockAnyPort:309: socket failed 1
```

## Post-Attempt Reconciliation

GET-only Alpaca PAPER reconciliation after the blocked launch attempt:

- preflight status: `PAPER_READ_ONLY_PREFLIGHT_PASSED`
- endpoint: `https://paper-api.alpaca.markets`
- account status: `ACTIVE`
- positions after attempted run: 7
- open orders after attempted run: 0
- GET count: 3
- POST count: 0
- `live_endpoint_used=false`
- `mutation_occurred=false`

## Local Order / Fill / Reservation State

Local state after the blocked launch attempt:

- `orders_total`: 0
- `fills_total`: 0
- `order_id_mappings_total`: 0
- `reservation_ledger_total`: 0
- `reservation_fill_progress_total`: 0
- `reservation_release_tombstones_total`: 0
- `events_total`: 0

Telemetry database:

- `telemetry_events_total`: 29

No local order/fill/reservation records were created by the blocked launch attempt.

## Runtime Markers

Observed in the launch attempt output/logs:

- no live endpoint marker
- no real-money marker
- no `/v2/orders` runtime marker
- no order submission marker
- no broker POST marker
- no cancel/replace/liquidation marker
- no fake broker truth
- no fake market truth

The runtime did initialize `SovereignPaperBroker` because `internal_paper` was selected, but it failed before autonomous operation and before any order submission.

## Selected Feed Provider

No selected feed provider was established for the attempted run.

Reason:

- Windows venv process saw empty configured market-data provider lists
- startup failed with `MISSING_MARKET_DATA_PROVIDER_CONFIG`

## Shans / Fusion Activity

No Shans/Fusion activity occurred in this packet's launch attempt because runtime stopped during startup before market-data operation.

## Order Summary

- submitted orders: 0
- filled orders: 0
- open orders after reconciliation: 0
- rejected orders: 0
- canceled orders: 0
- broker POST count: 0
- broker mutation occurred: false

## Final Safety State

- endpoint: `https://paper-api.alpaca.markets`
- account status: `ACTIVE`
- positions count: 7
- open orders count: 0
- live endpoint used: false
- real-money mode observed: false
- mutation occurred: false
- physical fuse triggered: false
- broker/local conflict observed: false

## Verdict

FAIL.

The 20-minute autonomous PAPER run did not complete and did not lawfully start because the runtime selected `internal_paper` instead of the required `alpaca_paper` external broker route. This is an explicit stop/fail condition in the packet. The same launch environment also failed to pass market-data provider config into the Windows venv process, causing `MISSING_MARKET_DATA_PROVIDER_CONFIG`.

Safety was preserved: credential preflight passed, post-attempt Alpaca PAPER reconciliation passed, POST count remained 0, no broker mutation occurred, no live endpoint appeared, no real-money mode appeared, and no orders/fills/reservations were created.

Required next step: run the 20-minute command from native Windows PowerShell with the required runtime env vars set in that same Windows process, or add a separately approved launch wrapper/preflight that makes the Windows runtime environment explicit before starting autonomous PAPER.
