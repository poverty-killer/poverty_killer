# Dynamic Execution Broker Gateway Injection Hotfix

## Packet

POVERTY_KILLER - HOTFIX PACKET: DYNAMIC EXECUTION BROKER GATEWAY INJECTION

## Date/Time

2026-05-21T16:52:39Z

## Starting HEAD

5832f12 - Prove finite latency shadow readiness for paper launch

## Files Changed

- main.py
- app/execution/order_router.py
- tests/test_dynamic_execution_broker_gateway_injection.py
- reports/dynamic_execution_broker_gateway_injection_hotfix.md

## Root Cause

The active runtime conflated market-data venue with execution broker. `main.py` built `OrderRouter(primary_exchange="kraken", paper_mode=True)` without injecting a broker gateway adapter. In paper mode, that allowed the active route to use the internal sovereign `PaperBroker` even when the intended external paper broker path was Alpaca PAPER.

That made the planned autonomous external paper system test untruthful because the route could skip:

ExecutionEngine -> OrderRouter -> BrokerGateway -> external paper broker adapter -> broker reconciliation

## Config/Env Selection

Execution broker selection is now controlled by:

`POVERTY_KILLER_EXECUTION_BROKER`

Current supported values:

- `internal_paper`
- `alpaca_paper`

Unsupported values fail closed. External execution brokers require paper mode.

## Implementation Summary

`main.py` now resolves execution broker separately from market-data venue before constructing `OrderRouter`.

For `internal_paper`, the runtime keeps the existing internal sovereign paper broker path.

For `alpaca_paper`, the runtime constructs `AlpacaPaperBrokerAdapter.from_env()`, validates adapter identity, credentials, paper environment, live-endpoint blocking, and venue identity, then injects the adapter into `OrderRouter`.

`OrderRouter` now accepts `execution_broker` and `broker_gateway_adapter`. If an external paper broker is requested, it validates that a paper, live-blocked gateway adapter is present and that the adapter venue matches the router execution venue. It does not wire the internal sovereign `PaperBroker` for external paper execution.

## Platform-Agnostic Preservation

Alpaca is not a global broker assumption. It is only the currently supported adapter case behind the execution-broker selector. Future external paper brokers can be added as additional adapter registry entries without changing the market-data venue concept.

Kraken remains feed-side through `config.primary_feed_venue`. In the shadow proof, runtime telemetry reported:

- `market_data_venue=kraken`
- `execution_broker=alpaca_paper`
- `execution_primary_exchange=alpaca`
- `execution_adapter=alpaca_paper_rest`

## Internal PaperBroker Preservation

The internal sovereign `PaperBroker` remains available only through explicit `POVERTY_KILLER_EXECUTION_BROKER=internal_paper` or the default local simulation path. It is no longer an accidental fallback when an external paper broker is requested.

## Fail-Closed Cases Proven

Focused tests prove:

- default execution broker resolves to explicit `internal_paper`
- configured `alpaca_paper` wires the Alpaca PAPER adapter from env
- Kraken market-data venue can remain separate from Alpaca execution
- external paper execution routes through gateway instead of internal paper fallback
- external paper request without adapter fails closed
- unsupported broker fails closed
- adapter/primary-exchange mismatch fails closed
- missing credentials fail closed
- live Alpaca endpoint fails closed
- internal paper simulation remains explicit

## Verification

Compile:

`venv/Scripts/python.exe -m py_compile main.py app/execution/order_router.py app/execution/broker_gateway.py app/execution/alpaca_paper_adapter.py`

Result: passed.

Focused test:

`venv/Scripts/python.exe -m pytest tests/test_dynamic_execution_broker_gateway_injection.py -q`

Result: passed, `8 passed, 72 warnings`. Warnings were existing Pydantic deprecation warnings.

No broad pytest was run.

## Shadow-Read-Only Proof

Command:

`. "$HOME/.poverty_killer_alpaca_paper_env"; export APCA_API_BASE_URL APCA_API_KEY_ID APCA_API_SECRET_KEY; export POVERTY_KILLER_EXECUTION_BROKER=alpaca_paper; export WSLENV=APCA_API_BASE_URL:APCA_API_KEY_ID:APCA_API_SECRET_KEY:POVERTY_KILLER_EXECUTION_BROKER; timeout 60s venv/Scripts/python.exe main.py --paper --shadow-read-only --log-level INFO`

Result: bounded timeout exit `124` after the 60-second proof window.

Runtime evidence:

- paper mode confirmed
- shadow-read-only confirmed
- configured execution broker resolved
- selected execution adapter reported as `alpaca_paper_rest`
- internal sovereign `PaperBroker` was not wired for external paper execution
- OrderRouter route reported `execution_broker=alpaca_paper primary_exchange=alpaca broker_gateway_adapter=alpaca_paper_rest`
- Kraken remained feed-side and WebSocket book processing continued
- current-run scan found no `/v2/orders`
- current-run scan found no `POST`
- current-run scan found no order submit markers
- current-run scan found no live Alpaca endpoint marker
- current-run scan found no sell/rebalance/cancel/replace markers

POST count proof: `0` by absence of current-run POST and `/v2/orders` markers during shadow-read-only.

Live endpoint verdict: no live endpoint was selected or used. Alpaca adapter construction remains blocked unless the APCA base URL is exactly the paper endpoint.

## Runtime Health Notes

The shadow proof still exposed Kraken REST DNS degradation:

`Cannot connect to host api.kraken.com:443 ssl:default [Could not contact DNS servers]`

This is feed-side REST degradation, not broker mutation, and WebSocket market-data processing continued. It remains a truthful degraded runtime condition for the next operational packet to evaluate during pre-run safety checks.

## Bounded Autonomous External Paper Run Status

The routing blocker is corrected. The active runtime can now select and inject the configured external paper broker gateway instead of silently falling into internal paper simulation.

The next bounded autonomous external PAPER run remains subject to separate Supreme Board approval and normal pre-run safety checks.

## Final Verdict

CONDITIONAL

The dynamic execution broker gateway injection hotfix is implemented and verified without broker mutation. The verdict is conditional because the shadow proof restated non-dangerous Kraken REST DNS degradation that should remain visible to the next autonomous external paper system-test packet.
