# Bot-Wide Shadow Read-Only Runtime Gate

## Summary

Implemented one explicit bot-wide shadow/read-only runtime gate. The gate preserves the existing runtime path through feeds, SignalFusion/candidate logic, pre-trade guardrails, DecisionCompiler, and ExecutionEngine admission, but blocks broker mutation before `OrderRouter.submit_order()` can be reached.

## Files Changed

- `app/config.py`
- `main.py`
- `app/execution/engine.py`
- `tests/test_bot_wide_shadow_read_only_runtime_gate.py`
- `reports/bot_wide_shadow_read_only_runtime_gate.md`

## Flag

- CLI: `--shadow-read-only`
- Env: `POVERTY_KILLER_SHADOW_READ_ONLY=1`

`shadow_read_only=True` is invalid with `broker_mode="live"` and fails closed.

## Shadow Run Command

Bounded runtime command:

```bash
timeout 20s venv/Scripts/python.exe main.py --paper --shadow-read-only --log-level INFO
```

The external timeout is the bounded runtime control. No mutation approval flags are used.

## Broker Mutation Block

The shared gate is in `ExecutionEngine.submit_signal()`, after decision/guardrail inputs are available and before the execution queue can reach `_execute_signal()` and `OrderRouter.submit_order()`.

Shadow telemetry records:

- timestamp
- symbol
- asset class
- side
- order type
- notional/quantity intent when available
- guardrail verdict
- reason `SHADOW_READ_ONLY_BLOCKED_BROKER_MUTATION`
- broker mutation counts fixed at `POST=0`, `PATCH=0`, `DELETE=0`, `cancel=0`, `replace=0`, `sell=0`, `rebalance=0`

Additional guards block cancellation and emergency liquidation paths in shadow mode.

## Normal Paper Mode

Focused tests prove the Alpaca PAPER gateway path still submits a normal paper `POST /v2/orders` when `shadow_read_only=False`.

## Live-Data Shadow Result

Command result: exited `124` from external `timeout`.

Observed in logs for the run window:

- `Broker Mode: paper`
- `Shadow Read Only: ENABLED`
- `WebSocket connected to wss://ws.kraken.com/v2`
- live `FEED_CANDLE` and `FEED_BOOK` ingress

Forbidden broker mutation markers searched for the run window and not found:

- `ORDER_SUBMIT_ATTEMPT`
- `PAPERBROKER_REACH_COUNT`
- `PAPER_FILL_COUNT`
- `SHADOW_READ_ONLY_BLOCKED`
- `MARKET SELL COMMANDS`
- `EMERGENCY: Closing`
- `cancel_order`
- `/v2/orders`
- `POST`
- `Broker Mode: live`
- `Shadow Read Only: DISABLED`

REST polling during the bounded run reported DNS errors for `api.kraken.com`, while websocket data did arrive. No Alpaca PAPER mutation approval flag was set.

## Verification

```bash
python -m py_compile app/config.py main.py app/execution/engine.py tests/test_bot_wide_shadow_read_only_runtime_gate.py
```

Passed.

```bash
venv/Scripts/python.exe -m pytest -q tests/test_bot_wide_shadow_read_only_runtime_gate.py
```

Result: `5 passed`.

```bash
venv/Scripts/python.exe -m pytest -q tests/test_execution_spine_order_routing.py tests/test_pre_trade_guardrail_constraints.py tests/test_live_read_only_adapter_config_gate.py tests/test_venue_market_asset_capability_layer.py tests/test_intelligence_portfolio_state_truth_spine.py tests/test_order_id_mapping_authority.py
```

Result: `73 passed`.

## Remaining Notes

- The full runtime still uses external `timeout` for bounded runs.
- Alpaca PAPER read-only GET wiring remains a separate existing adapter/harness surface; this gate makes bot-wide broker mutation impossible but does not add new broker read wiring.
