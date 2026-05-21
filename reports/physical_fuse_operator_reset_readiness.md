# Physical Fuse Operator Reset Readiness

Current HEAD at start: `a53b96b`.

## Files Inspected

- `app/risk/guard.py`
- `app/monitoring/health.py`
- `app/control_plane.py`
- `main.py`
- `state/risk_state.json`
- `reports/final_launch_blocker_burndown_physical_fuse_alpaca_reconciliation.md`
- `reports/autonomous_paper_friday_readiness.md`
- `reports/seam7h_operator_monitoring_shadow_launch_readiness.md`

## Fuse Owner

The physical fuse owner is `HybridRiskGuard` in `app/risk/guard.py`.

Authoritative code paths:

- Trigger: `HybridRiskGuard.check_physical_fuse(current_equity)`
- Trade block: `HybridRiskGuard.can_trade()`
- Existing manual reset: `HybridRiskGuard.reset_fuse()`
- Status: `HybridRiskGuard.get_status()`
- Persistence: `state/risk_state.json` and `state/risk_state.backup`

Monitoring, reports, and readiness logic consume fuse truth. They do not own reset authority.

## Persisted Fuse State

Read-only inspection of `state/risk_state.json` showed:

- `physical_fuse_triggered`: `true`
- `current_equity`: `20000.0`
- `high_water_mark`: `20000.0`
- computed physical fuse: `15000.0`
- `last_breach_time`: `2026-05-08T08:08:13.711138`

Current classification: `PHYSICAL_FUSE_STALE`.

Meaning: the persisted fuse flag remains active, but current local risk state no longer shows equity below the fuse threshold. This remains blocking until the owning guard clears it through a lawful operator reset path.

## Reset Path Added

Added owner-side reset evidence types and method in `HybridRiskGuard`:

- `PhysicalFuseOperatorResetEvidence`
- `PhysicalFuseOperatorResetResult`
- `HybridRiskGuard.classify_physical_fuse_state()`
- `HybridRiskGuard.reset_stale_physical_fuse_with_evidence(...)`

The new method fails closed unless all required evidence is present:

- fuse is `PHYSICAL_FUSE_STALE`, not active
- operator acknowledgment is present
- broker read-only reconciliation is proven
- broker environment is `paper`
- no live endpoint was used
- broker mutation did not occur
- POST/PATCH/DELETE count is `0`
- shadow-read-only evidence is present
- broker/local conflict is absent
- no other fuse state is active

Successful reset records an audit event in the owning risk state as `last_operator_reset_audit`.

## Reset Performed

No real persisted fuse reset was performed in this packet.

Reason: the packet allowed implementing and testing the owner-respecting path, but did not separately authorize mutating the real persisted fuse state. The real state remains blocked until an operator explicitly applies the new evidence-gated reset path.

## Evidence Used

Deterministic tests used temp risk-state files and deterministic safety fixtures only.

The prior real Alpaca PAPER read-only reconciliation proof from commit `a53b96b` remains relevant evidence:

- endpoint: `https://paper-api.alpaca.markets`
- environment: `paper`
- request counts: `GET=3`, `POST=0`
- mutation: `false`
- live endpoint: `false`
- open orders: `0`
- positions: `7`

That proof is not represented as live truth in deterministic tests; tests label fixture data as deterministic safety fixtures.

## Test Results

Compile:

```bash
venv/Scripts/python.exe -m py_compile app/monitoring/health.py app/monitoring/alerts.py app/control_plane.py app/config.py main.py app/main_loop.py app/risk/guard.py app/risk/safety.py app/risk/kill_switch.py app/risk/unified_risk.py app/risk/sovereign_execution_guard.py app/risk/drawdown_guard.py app/risk/exposure_manager.py app/state/state_store.py app/state/hydration_manager.py tests/test_physical_fuse_operator_reset_readiness.py
```

Result: passed.

Focused deterministic test:

```bash
venv/Scripts/python.exe -m pytest -q tests/test_physical_fuse_operator_reset_readiness.py
```

Result: `9 passed`.

Scoped regression:

```bash
venv/Scripts/python.exe -m pytest -q tests/test_final_launch_blocker_burndown_physical_fuse_alpaca_reconciliation.py tests/test_seam7h_operator_monitoring_shadow_launch_readiness.py tests/test_kraken_rest_dns_feed_truth_resilience.py tests/test_seam7g_market_truth_reconciliation_spine.py tests/test_seam7f_risk_capital_defense_execution_economics.py tests/test_pre_trade_guardrail_constraints.py tests/test_intelligence_portfolio_state_truth_spine.py
```

Result: `48 passed`.

## Shadow Run

Bounded shadow-read-only runtime was not run in this packet.

Reason: the real persisted fuse was not reset, so the launch blocker remains and a bounded runtime would still be expected to report the physical fuse block.

## Safety Confirmation

- No autonomous paper launch.
- No order submission.
- No cancel/replace.
- No sell or rebalance.
- No emergency liquidation.
- No broker mutation.
- No mutation approval flags.
- No live endpoint added.
- No secrets printed or committed.
- No direct deletion of fuse state.
- No report or monitoring layer was allowed to clear the fuse.

## Final Fuse Status

Current real persisted fuse status: `PHYSICAL_FUSE_STALE`.

The lawful owner-side reset path now exists, but the real persisted fuse remains active/stale until an operator explicitly applies that evidence-gated reset.

## Final Readiness Verdict

`NOT_READY_FOR_AUTONOMOUS_PAPER`

Remaining blocker: `PHYSICAL_FUSE_REQUIRES_OPERATOR_ACTION`.

## Applied Reset And Fresh Shadow Validation

Current HEAD at reset application: `a663d86`.

The operator-approved reset packet applied the real persisted reset through the owning guard path only:

```python
HybridRiskGuard.reset_stale_physical_fuse_with_evidence(...)
```

Reset evidence used:

- operator acknowledgment: `true`
- broker read-only reconciliation: `true`
- broker environment: `paper`
- endpoint proof: `https://paper-api.alpaca.markets`
- request counts: `GET=3`, `POST=0`, `PATCH=0`, `DELETE=0`
- positions count: `7`
- open orders count: `0`
- shadow-read-only evidence: `true`
- live endpoint used: `false`
- broker mutation occurred: `false`
- broker/local conflict: `false`

Reset result:

- before: `PHYSICAL_FUSE_STALE`
- result: `PHYSICAL_FUSE_CLEARED`
- persisted `physical_fuse_triggered`: `false`
- `can_trade`: `true` immediately after reset evaluation
- audit event: `PHYSICAL_FUSE_OPERATOR_RESET_APPLIED`
- audit persisted in `state/risk_state.json` as `last_operator_reset_audit`

The reset did not delete fuse state. It recorded the owner-side audit trail and updated the persisted risk state through `HybridRiskGuard`.

## Fresh Bounded Shadow Result

Approved bounded shadow command:

```bash
timeout 60s venv/Scripts/python.exe main.py --paper --shadow-read-only --log-level INFO
```

Result: exited `124` because the external timeout stopped the long-running runtime at the bound.

Observed clean evidence:

- paper mode confirmed: `Broker Mode: paper`
- shadow-read-only confirmed: `Shadow Read Only: ENABLED`
- Kraken websocket connected to `wss://ws.kraken.com/v2`
- live feed ingress occurred: `FEED_CANDLE #1`, `FEED_BOOK #1`, and later book updates
- fusion/dispatch path ran and recorded not-ready/declined diagnostics
- current-run physical fuse alert scan found `0` matches
- current-run order mutation marker scan found `0` matches for `ORDER_SUBMIT_ATTEMPT`, `OrderRouter.submit_order`, `/v2/orders`, `POST /v2/orders`, `BROKER_MUTATION`, or `SHADOW_READ_ONLY_BLOCKED_BROKER_MUTATION`

Observed remaining blockers/degraded truth:

- runtime triggered `LAG ABORT: infms > 200.0ms`
- `ExecutionEngine` entered safe mode, then later logged latency recovery
- Kraken REST candle/order-book polling still emitted DNS failures for `api.kraken.com`
- websocket order-book validation prevented crossed book snapshots with `CROSSED_BOOK_PREVENTED`

## Applied Reset Test Results

Focused deterministic test added:

```bash
venv/Scripts/python.exe -m pytest -q tests/test_apply_physical_fuse_reset_shadow_readiness.py
```

This test file proves the reset remains owner-gated, refuses live/mutation evidence, updates physical fuse readiness only after the owner reset, and still blocks readiness when the fresh shadow evidence contains latency abort, mutation markers, live endpoint markers, or missing broker truth.

Verification results for applied reset packet:

- compile: passed for the packet-listed risk, monitoring, runtime, execution, reconciliation, and new test files
- focused test: `7 passed`
- scoped regression: `57 passed`
- initial sandboxed pytest attempts hit WSL vsock binding errors; the same packet-listed pytest commands passed when rerun outside the sandbox

## Current Verdict After Applied Reset

`NOT_READY_FOR_AUTONOMOUS_PAPER`

The original physical fuse blocker is lawfully cleared and audited. Alpaca PAPER read-only reconciliation is proven with real sanitized GET-only evidence. The fresh bounded shadow run exposed a separate safety blocker: `LAG_ABORT_ACTIVE` / runtime safe mode. Autonomous PAPER should remain blocked until that latency abort condition is diagnosed and a fresh bounded shadow run is clean.
