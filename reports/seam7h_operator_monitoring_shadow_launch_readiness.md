# Seam 7H Operator Monitoring Shadow Launch Readiness

Current HEAD at Seam 7H start: `8b0cc34`.

## Files Inspected

- `app/control_plane.py`
- `app/api/dashboard_server.py`
- `app/monitoring/alerts.py`
- `app/monitoring/health.py`
- `app/monitoring/performance_attribution.py`
- `app/monitoring/reports.py`
- `main.py`
- `app/config.py`
- `app/main_loop.py`
- `app/execution/engine.py`
- `app/execution/order_router.py`
- `app/execution/broker_gateway.py`
- `app/execution/alpaca_paper_adapter.py`
- `app/execution/live_read_only_adapter.py`
- `app/core/decision_compiler.py`
- `app/brain/signal_fusion.py`
- `app/core/intelligence_portfolio_state_truth_spine.py`
- `app/state/state_store.py`

## Authority Findings

- `ControlPlane`: operator control and local mode-file authority. It can change local runtime mode and emergency-halt posture, but it does not own broker mutation, order routing, reconciliation, or live endpoint authority.
- `SovereignDashboard`: dashboard/server visibility surface. It exposes FastAPI routes and websocket status helpers. Server start opens a port and command endpoints can call bot control/liquidation methods if a bot is attached, so server start is intentionally blocked in Seam 7H tests.
- `SovereignSentinel`: local heartbeat/alerting watchdog. It can write local alert state and can dispatch webhook/Telegram only when configured. Seam 7H validates local alert records only; external alerts are intentionally blocked/unconfigured.
- `HealthMonitor`: canonical local systemic health authority. It signs component health and violations. It does not own execution or broker mutation.
- `PerformanceAttributor`: attribution engine for provided realized trade truth. Empty/missing trade truth returns partial zero attribution and does not invent PnL/performance.
- `ReportGenerator`: forensic report packet generator from provided structured evidence. It does not generate source truth or broker facts.
- `main.py`/`Config`: expose `--paper`, `--shadow-read-only`, `POVERTY_KILLER_SHADOW_READ_ONLY`, and enforce `shadow_read_only` only with paper mode.
- `ExecutionEngine`: owns execution submission boundary. In shadow-read-only it records would-submit telemetry and blocks broker mutation before OrderRouter mutation.
- `OrderRouter`/`BrokerGateway`/`AlpacaPaperBrokerAdapter`: broker routing/adaptation boundary. Alpaca PAPER endpoint is `https://paper-api.alpaca.markets`; live endpoint is not required for Seam 7H.
- `LiveReadOnlyBrokerAdapter`: read-only broker truth surface; no submit/cancel mutation surface.

## Operator Monitoring Contribution Posture

- `ControlPlane`: `ACTIVE_OPERATOR_CONTROL`, effect `DOCUMENTS_ROLLBACK`, reason `MODE_FILE_OPERATOR_CONTROL_ONLY`.
- `SovereignDashboard`: `INTENTIONALLY_BLOCKED_SERVER_START`, effect `NO_EFFECT_WITH_REASON`, reason `TESTS_MUST_NOT_OPEN_PORTS_OR_EXERCISE_MUTATING_OPERATOR_ENDPOINTS`.
- `SovereignSentinel`: `ACTIVE_ALERTING_LOCAL`, effect `EMITS_ALERT`, reason `EXTERNAL_ALERTS_UNCONFIGURED_AND_NOT_SENT`.
- `HealthMonitor`: `ACTIVE_HEALTH_CHECK`, effect `CHECKS_HEALTH`, reason `EXPLICIT_COMPONENT_HEARTBEAT`.
- `PerformanceAttributor`: `ACTIVE_PERFORMANCE_ATTRIBUTION`, effect `ATTRIBUTES_PERFORMANCE`, reason `USES_PROVIDED_REALIZED_TRADE_TRUTH_ONLY`.
- `ReportGenerator`: `ACTIVE_REPORTING`, effect `GENERATES_REPORT`, reason `PACKAGES_PROVIDED_EVIDENCE_ONLY`.
- `ShadowReadOnlyGate`: `ACTIVE_SHADOW_RUNTIME`, effect `BLOCKS_MUTATION`, reason `SHADOW_READ_ONLY_BLOCKED_BROKER_MUTATION`.

## Launch Commands

Shadow command:

```bash
venv/Scripts/python.exe main.py --paper --shadow-read-only --log-level INFO
```

Optional bounded shadow command:

```bash
timeout 60s venv/Scripts/python.exe main.py --paper --shadow-read-only --log-level INFO
```

Autonomous PAPER command, only after explicit user approval:

```bash
venv/Scripts/python.exe main.py --paper --log-level INFO
```

Required env posture:

- `POVERTY_KILLER_SHADOW_READ_ONLY=1` for shadow.
- `POVERTY_KILLER_SHADOW_READ_ONLY=0` only for approved autonomous PAPER.
- `POVERTY_KILLER_ALPACA_PAPER_ENV_PATH=...` only if Windows venv from WSL needs the existing non-secret credential path override.

## Stop And Rollback

- Stop foreground runtime with `Ctrl+C`.
- If Windows process hangs:

```powershell
taskkill /IM python.exe /F
```

- Re-enable shadow posture with `POVERTY_KILLER_SHADOW_READ_ONLY=1`.
- Remove paper mutation approval flags.
- Do not use emergency liquidation in shadow mode.

## No-Mutation And No-Live Proof

- Config rejects `shadow_read_only=True` with `broker_mode="live"`.
- Alpaca PAPER adapter endpoint constant is `https://paper-api.alpaca.markets`.
- Existing shadow gate regression proves no broker mutation in shadow and broker POST/PATCH/DELETE/cancel/replace/sell/rebalance counts remain zero.
- Seam 7H focused tests do not call broker APIs, do not start `main.py`, do not open dashboard ports, do not send external alerts, and do not set mutation approval flags.
- No live endpoint was used by Seam 7H tests.
- Bounded shadow stress log scan for `2026-05-20T21:59` through `2026-05-20T22:00` found no current-run `ORDER_SUBMIT_ATTEMPT`, `/v2/orders`, live broker mode, POST order, sell, rebalance, cancel, replace, emergency liquidation, or broker mutation markers.

## Test Results

- Compile check:
  - `venv/Scripts/python.exe -m py_compile app/control_plane.py app/api/dashboard_server.py app/monitoring/alerts.py app/monitoring/health.py app/monitoring/performance_attribution.py app/monitoring/reports.py main.py app/config.py app/main_loop.py app/execution/engine.py app/execution/order_router.py app/execution/broker_gateway.py app/execution/alpaca_paper_adapter.py app/execution/live_read_only_adapter.py app/core/decision_compiler.py app/brain/signal_fusion.py app/core/intelligence_portfolio_state_truth_spine.py app/state/state_store.py tests/test_seam7h_operator_monitoring_shadow_launch_readiness.py`
  - Result: passed.
- Focused Seam 7H:
  - `venv/Scripts/python.exe -m pytest -q tests/test_seam7h_operator_monitoring_shadow_launch_readiness.py`
  - Result: `5 passed`.
- Scoped non-mutating regression:
  - `venv/Scripts/python.exe -m pytest -q tests/test_seam7g_market_truth_reconciliation_spine.py tests/test_seam7f_risk_capital_defense_execution_economics.py tests/test_seam7e_strategy_fusion_runtime_wiring.py tests/test_seam7e_residual_math_model_repair.py tests/test_execution_spine_order_routing.py tests/test_broker_gateway_adapter_layer.py tests/test_pre_trade_guardrail_constraints.py tests/test_intelligence_portfolio_state_truth_spine.py`
  - Result: `68 passed`.
- Packet-listed file omitted because it does not exist:
  - `tests/test_shadow_read_only_runtime_gate.py`
  - Existing repo file with similar coverage: `tests/test_bot_wide_shadow_read_only_runtime_gate.py`; not run in this Seam 7H regression because it was not the exact pre-approved filename.

## Shadow Stress Result

Approved bounded shadow command:

```bash
timeout 60s venv/Scripts/python.exe main.py --paper --shadow-read-only --log-level INFO
```

Result: exited `124` because the external `timeout 60s` killed the long-running runtime at the bound.

Observed runtime evidence:

- Paper mode confirmed: `Broker Mode: paper`.
- Shadow mode confirmed: `Shadow Read Only: ENABLED`.
- Candidate runtime posture recorded paper venues with `mutation_authorized: False`.
- Kraken websocket connected to `wss://ws.kraken.com/v2`.
- Feed ingress occurred: `FEED_CANDLE #1`, `FEED_BOOK #1`, and later `FEED_BOOK #2200`.
- Signal/fusion path was active: `FUSION_UPDATE_CALLED` for runtime symbols.
- Initial dispatch diagnostics recorded no submit on not-ready state: `submit_signal_called=False`.
- No current-run broker mutation/order markers were found in the bounded-window log scan.

Observed blockers/degraded truth:

- Kraken REST candle and order-book polling repeatedly failed DNS with `Cannot connect to host api.kraken.com:443 ssl:default [Could not contact DNS servers]`.
- Runtime health emitted repeated critical alerts: `HEALTH ALERT: Physical fuse triggered!`.
- Broker read-only reconciliation truth was not proven by this 60-second run output.

## Remaining Blockers

- Critical launch blocker: bounded shadow run emitted `HEALTH ALERT: Physical fuse triggered!`.
- Market data blocker/degradation: Kraken REST polling DNS failures prevented full REST candle/order-book truth despite websocket feed ingress.
- Broker truth blocker: Alpaca PAPER read-only reconciliation truth was not proven in the bounded shadow output.
- Dashboard server start is intentionally blocked in tests because it opens a port and contains operator command endpoints.
- External alert dispatch is intentionally blocked/unconfigured in tests.

## Final Verdict

`NOT_READY_FOR_AUTONOMOUS_PAPER`

Reason: operator/monitoring launch controls and no-live/no-mutation posture are validated, and the bounded shadow run showed feed/fusion activity without broker mutation. However, critical health fuse alerts, REST DNS truth gaps, and missing broker read-only reconciliation proof must be cleared before Friday autonomous PAPER launch can be marked ready.
