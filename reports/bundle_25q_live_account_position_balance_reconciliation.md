# BUNDLE 25Q - Live Account / Position / Balance Reconciliation Harness

Verdict: PASS

25Q proves an offline account / position / balance reconciliation contract. It does not call a broker, query live account/balances/status, activate live mode, edit `broker_adapter.py`, edit `live_broker.py`, wire production reconciliation, or enable live reservation lifecycle.

## Tests Run

- `/tmp/pk25i-venv/bin/python -m pytest tests/test_live_account_position_balance_reconciliation_harness.py -q`
  - Result: 9 passed
- `/tmp/pk25i-venv/bin/python -m pytest tests/test_live_adapter_contract_harness.py tests/test_live_arming_gate_harness.py tests/test_live_cancel_terminal_reconciliation_harness.py tests/test_live_fill_telemetry_truth_harness.py tests/test_micro_live_readiness_scout.py tests/test_reconcile_namespace_authority.py tests/test_order_id_mapping_authority.py tests/test_runtime_reservation_bootstrap.py tests/test_economic_truth_spine.py tests/test_durable_recovery_automation_spine.py -q`
  - Result: 90 passed

## Proven

| Domain | Proof |
| --- | --- |
| Account snapshot identity | Account ID, source, receive timestamp, environment marker, and base currency are required. Missing or stale account snapshot fails closed. Ambiguous account identity blocks readiness. |
| Balance reconciliation | Broker available balance is canonical when present. Missing available balance, currency mismatch, negative/impossible balances, and stale balances fail closed. Local reservation is supporting constraint only and does not become broker truth. Held broker cash prevents double-counting local reserve. |
| Position reconciliation | Broker position quantity is canonical for live factual position. Local exposure mismatch blocks readiness. Unknown instrument mapping and unknown broker quantity fail closed. Flat must be proven by broker truth, not assumed locally. |
| Open order reconciliation | Broker orphan open order, local orphan open order, unmapped broker order, stale open-order snapshot, and terminal/tombstone local state with broker-open order all block readiness. No live cancel action is taken. |
| Recent fill / telemetry reconciliation | Broker recent trade can reveal missing local telemetry. Local/broker quantity, fee, and timestamp mismatches block readiness. Local fill missing from broker snapshot blocks readiness. Duplicate known fills reconcile cleanly. |
| Exposure / reservation reconciliation | Live reservation lifecycle remains disabled. Active local reservation without broker open-order support blocks readiness. Broker open order without local reservation blocks readiness. Tombstone/terminal reservation conflicting with broker open order blocks readiness. |
| Snapshot freshness / ordering | Stale account, balance, position, and open-order snapshots cannot prove readiness. Older snapshots cannot override newer known local truth. |
| Operator/no-go reason codes | Unsafe branches return explicit reason codes and block submit readiness. Operator review must be clear. |
| Tiny-live readiness implication | A clean fixture can satisfy only the offline reconciliation prerequisite. Any account/balance/position/open-order/fill/reservation/operator blocker prevents micro-live readiness. |

## Reason Codes

- `account_snapshot_missing`
- `account_snapshot_stale`
- `account_identity_ambiguous`
- `broker_environment_missing`
- `base_currency_missing`
- `balance_available_missing`
- `balance_currency_mismatch`
- `balance_negative_or_impossible`
- `balance_snapshot_stale`
- `local_reservation_supporting_constraint_only`
- `position_mismatch`
- `broker_position_unknown`
- `instrument_mapping_unknown`
- `position_snapshot_stale`
- `open_order_orphan_broker`
- `open_order_orphan_local`
- `open_order_snapshot_stale`
- `reservation_open_order_conflict`
- `broker_recent_fill_missing_local_telemetry`
- `fill_telemetry_mismatch`
- `local_fill_missing_from_broker_snapshot`
- `fill_identity_missing`
- `fill_snapshot_stale`
- `local_reservation_without_broker_support`
- `broker_open_order_without_local_reservation`
- `operator_review_required`

## Remaining Blockers Before Micro-Live

- No concrete live adapter implementation.
- No broker sandbox/read-only proof.
- No production Board/operator arming gate.
- No production live reconciliation wiring.
- No production live fill ingestion into `FillRecorder`.
- No live-mode operator escape dry-run.
- Live reservation lifecycle remains blocked by design.
- This is offline contract proof, not broker/sandbox proof.

## Authority Boundaries

- The 25Q harness classifies offline snapshot facts only.
- It does not submit orders, cancel orders, query broker, mutate live reservations, mutate live exposure, record production live fills, release exposure, decide profitability, or become broker/risk/economics authority.
- Broker truth is canonical for live factual account/position/balance/order/fill facts. Local state is supporting evidence. Unknown or conflicting state fails closed.

## Confirmations

- Production behavior changed: no
- Real broker/network call made: no
- Credentials used: no
- Live order placed: no
- Live cancel sent: no
- Live status/account/balance query made: no
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
