# PK-P3O Trade Acceptance Telemetry Truth Report

Date: 2026-06-20 23:34 to 2026-06-21 00:34 America/Chicago / 2026-06-21 04:34 to 05:34 UTC
Branch: master
Latest commit after code fixes: `6539b3e fix(operator): surface reconciled fill ledger visibility`
Status page: `http://127.0.0.1:8765/operator/run-visibility`

## 1. VERDICT

PK-P3O is a safety pass and an acceptance partial/fail.

The three requested code fixes were implemented as three separate commits and validated with focused tests. The bounded native Windows PAPER re-validation run completed cleanly with supervisor exit code `0`, no stderr, no deadlock, no timezone crash, no live trading, no real-money path, and no raw secrets exposed.

The buying-power fix worked in the safety sense: the bot no longer POSTed unfundable buy orders to Alpaca and produced `0` `BROKER_40310000` broker rejections. It did not meet the acceptance goal: all 9 broker-boundary order attempts were blocked before POST with `BUYING_POWER_INSUFFICIENT_PRE_POST`, so accepted broker POSTs remained `0` and there were no new fills in this one-hour validation run.

Plain English: we stopped the bad broker rejections, but the bot still is not sizing or planning new buys against the actual paper account cash. The next seam is not another rejection decoder; it is fundable sizing / cash-aware order planning that re-runs all economic and safety gates before any POST.

## 2. FILES CHANGED

Committed code/test files:

- `app/risk/guard.py`
- `app/execution/order_router.py`
- `app/run_visibility.py`
- `app/api/operator_readonly_api.py`
- `tests/test_canonical_paper_oms_lifecycle.py`
- `tests/test_broker_gateway_adapter_layer.py`
- `tests/test_run_visibility.py`
- `tests/test_execution_spine_order_routing.py`
- `tests/test_bot_wide_shadow_read_only_runtime_gate.py`
- `tests/test_pre_trade_guardrail_constraints.py`

Report files updated by Codex:

- `reports/codex_handoff_latest.md`
- `reports/codex_handoff_2026-06-21_p3o_trade_acceptance_telemetry_truth.md`

Runtime artifacts inspected, not staged:

- `logs/paper_runs/bounded_paper_20260620_233422.out.log`
- `logs/paper_runs/bounded_paper_20260620_233422.err.log`
- `logs/paper_runs/p3o_revalidation_parent_20260620_233407.out.log`
- `logs/paper_runs/p3o_revalidation_parent_20260620_233407.err.log`
- `logs/runtime/paper_supervisor_status.json`
- `logs/runtime/paper_heartbeat.json`

## 3. ROOT CAUSE

Fix A root cause: risk zombie-order assessment mixed aware and naive datetimes when `oldest_pending_order_ts` was present.

Fix B root cause: buy/add orders reached the Alpaca paper POST boundary without first proving account cash/buying-power truth could fund the order. Alpaca rejected those orders as buying-power failures. After the fix, the next revealed problem is account/sizing truth: the validation run account cash basis was `-11`, while proposed buy notionals ranged roughly from `$22` to `$2,999`.

Fix C root cause: the operator status page used heartbeat fill count as primary truth, so it could show `0` fills while the reconciled broker fill ledger had rows.

## 4. FIXES IMPLEMENTED

Commit `24ca90e fix(risk): use aware datetime for zombie assessment`

- Normalized pending-order timestamps before zombie age math.
- Used timezone-aware `datetime.now(timezone.utc)`.
- Added regression coverage for aware pending-order timestamps.

Commit `81e3cbb fix(execution): gate paper buys on account buying power`

- Added pre-POST buying-power admission for buy/add orders in the Alpaca paper order router.
- Reads broker account and open orders before buy POST.
- Uses conservative cash/buying-power basis and subtracts reserved open buy notional.
- Blocks unfundable buys with `BUYING_POWER_INSUFFICIENT_PRE_POST` before broker mutation.
- Keeps sell/exit lifecycle exempt from the buying-power gate.
- Keeps min-notional checks pre-POST.
- Adds broker-boundary telemetry with sanitized broker messages.

Commit `6539b3e fix(operator): surface reconciled fill ledger visibility`

- Added read-only SQLite broker fill ledger visibility.
- Operator status now exposes `fills.count`, `fills.source`, `broker_confirmed`, ledger rows, heartbeat fill count, and `last_fill`.
- Status page displays a compact fills metric.
- No `StateStore` instantiation in runtime page code, so this does not create DB tables.

## 5. 360 ADJACENT IMPROVEMENTS

Operator page truth improved:

- Page URL serves HTTP `200`: `http://127.0.0.1:8765/operator/run-visibility`
- Status endpoint: `/operator/run-visibility/status`
- Final status: `STOPPED`
- Supervisor state: `EXITED`
- Exit code: `0`
- Auto-restart: `false`
- Manual restart required: `true`
- Page has fills metric.
- Fills source: `broker_fill_ledger`
- Fills count: `71`
- Heartbeat filled-orders count: `0`
- Last fill populated from broker ledger.

Run acceptance telemetry:

- Duration: `3600` seconds
- Shutdown mode: `graceful_self_stop`
- `broker_flatten_called=false`
- `broker_post=false` at bounded-duration shutdown marker
- Shutdown accounting `order_post_attempted=0`
- Shutdown accounting `order_post_authorized=0`
- Shutdown accounting `order_post_acknowledged=0`
- `buying_power_pre_post_gate_event_count=9`
- `BROKER_40310000=0`
- `pending_terminal_leak_count=0`
- `reconciliation_conflict_count=0`
- `active_pending_orders=0`
- `broker_confirmed_open_orders=0`
- `last_broker_positions_count=12`

Market-data and signal evidence:

- `NetEdge` pass markers: `60`
- `MARKET_DATA_LATENCY_DEGRADED`: `2091` in one hour, about `34.9/min`, still near the known `~36/min` baseline.
- Stale/data-health block markers remained present; pausing OneDrive and Defender exclusions did not materially remove this pressure.

## 6. TESTS / CHECKS

Passed:

- `py_compile app/risk/guard.py app/execution/order_router.py app/run_visibility.py app/api/operator_readonly_api.py`
- `tests/test_broker_gateway_adapter_layer.py`
- `tests/test_run_visibility.py`
- selected execution-spine, shadow-gate, pre-trade-guardrail, canonical OMS lifecycle tests
- `tests/test_phase3_risk_gate_stress_proof.py`

Bounded runtime validation:

- Native Windows module form: `.\venv\Scripts\python.exe -m scripts.supervise_bounded_paper`
- Duration: `3600`
- Watchlist: BTC/ETH/SOL/LTC/AVAX/LINK
- Alpaca PAPER only
- TCA extended reads on
- Auto-restart disabled
- Supervisor exit code: `0`
- Child stderr length: `0`

## 7. BROWSER / RUNTIME VALIDATION

Status page:

- `http://127.0.0.1:8765/operator/run-visibility`
- HTTP `200`
- Content includes status and fills metric.

Status endpoint:

- `http://127.0.0.1:8765/operator/run-visibility/status`
- Final status `STOPPED`
- `last_error=null`
- Supervisor `state=EXITED`
- Supervisor `child_running=false`
- Supervisor `exit_code=0`
- `read_only=true`
- `live_enabled=false`
- `real_money_enabled=false`
- `secrets_values_exposed=false`

## 8. GOVERNANCE / SAFETY CONFIRMATION

- No live trading enabled.
- No real-money path enabled.
- No manual buy/sell controls added.
- No force-trade controls added.
- No raw secrets printed.
- No `.env` or credential file staged.
- No risk/economic/stale/TTL thresholds weakened.
- No fake fills, fake broker truth, or fake TCA introduced.
- Broker mutation counts during validation run: `GET=165`, `POST=0`, `DELETE=0`.
- Reports/logs/state remain unstaged.

## 9. LIMITATIONS / KNOWN FOLLOW-UP

1. Acceptance is still not solved. The bot needs cash-aware sizing or safe resize-down/re-plan before the broker boundary. Any resize must re-run min-notional, NetEdge, exposure, stale/TTL, and broker-position authority gates before POST.
2. The operator fill metric is now truthful to the broker fill ledger, but it is ledger-global, not run-scoped. For commercial operation, add run-scoped fill/reconciliation counts so the page can say "this run produced N fills" separately from "ledger has N total rows."
3. TCA/fee truth remains incomplete: shutdown reconciliation still showed historical broker fee hydration unmatched/conflict counts and no realized-vs-modeled NetEdge availability.
4. Market-data latency degraded rate is still essentially at baseline, about `34.9/min` in this run.
5. The paper account appears over-allocated for new buy/add orders: cash basis was reported as `-11` during pre-POST buying-power checks while 12 positions were already present.

## 10. STAGING RECOMMENDATION

Code fixes are already committed:

- `24ca90e`
- `81e3cbb`
- `6539b3e`

Do not stage runtime/state/log files.

Reports are intentionally left unstaged unless Shan explicitly approves staging them:

- `reports/codex_handoff_latest.md`
- `reports/codex_handoff_2026-06-21_p3o_trade_acceptance_telemetry_truth.md`

RESEARCH USED

- Comparable systems/patterns reviewed: official Alpaca account and order API docs.
- Lessons applied: account buying-power/cash truth must be checked before creating broker orders; order rejections can be caused by insufficient tradable balance and should be prevented when local truth is available.
- Lessons rejected: relying on broker rejection as normal control flow.
- Impact on our bot: safer broker-boundary telemetry and a fail-closed pre-POST buying-power gate for buy/add orders.
