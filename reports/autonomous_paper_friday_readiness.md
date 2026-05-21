# Autonomous PAPER Friday Readiness

Current commit at Seam 7H start: `8b0cc34` - Wire market truth reconciliation spine.

Friday target: Friday 10:00 AM America/Chicago.

## Commands

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

Do not run autonomous PAPER mutation until approval is given after shadow evidence is reviewed.

## Environment

- `POVERTY_KILLER_SHADOW_READ_ONLY=1` for shadow.
- `POVERTY_KILLER_SHADOW_READ_ONLY=0` for autonomous paper only after explicit approval.
- `POVERTY_KILLER_ALPACA_PAPER_ENV_PATH=...` only if Windows venv from WSL needs the existing non-secret credential path override.
- Do not print, copy, or commit secrets.
- Do not set mutation approval flags during shadow-read-only tests.

## Broker And Venue

- Alpaca PAPER only for broker mutation.
- Required endpoint: `https://paper-api.alpaca.markets`.
- No live endpoint.
- No live mode.
- Kraken/websocket feed may provide lawful market feed truth where configured.
- Broker truth remains canonical; local state remains supporting evidence only.

## Sizing And Risk

- Current config default initial capital: `$20000`.
- Current autonomous paper posture must use existing risk, guardrail, sizing, broker constraint, reconciliation, and invariant paths.
- Prior broker evidence showed Alpaca PAPER crypto rejects below `$10` cost basis. If a future approved paper crypto expansion is needed, use a controlled notional above that minimum only when config/Board approval supports it; `$11` or `$15` is operationally safer than `$10` for precision room.
- No threshold change is approved by this runbook.

## Required Pre-Launch Checks

1. Confirm latest pushed HEAD includes Seam 7H.
2. Run scoped `git status --short` and verify no unintended staged files.
3. Run compile and focused Seam 7H tests.
4. Run the Seam 7G/7F/7E/shadow/execution/broker/guardrail/state regression set.
5. Run bounded shadow only after approval:
   `timeout 60s venv/Scripts/python.exe main.py --paper --shadow-read-only --log-level INFO`
6. Verify shadow output:
   - paper mode confirmed
   - shadow-read-only confirmed
   - no live endpoint
   - no live mode
   - broker mutation count zero
   - no broker mutation in shadow
   - no POST/PATCH/DELETE/cancel/replace/sell/rebalance
   - feed truth or explicit feed failure recorded
   - broker read-only truth or explicit missing/DNS failure recorded
   - TruthKernel, InvariantChecker, and reconciliation status recorded or exact blocker reported
7. Request explicit approval before running autonomous PAPER.

## Stop Conditions

- Live endpoint appears.
- Live mode appears.
- Broker mutation in shadow.
- POST/PATCH/DELETE in shadow.
- Unexpected sell, rebalance, cancel, replace, retry storm, or emergency liquidation.
- Invariant failure.
- State/broker reconciliation conflict.
- Feed stale beyond configured threshold.
- DNS failures prevent required truth.
- Missing broker truth prevents canonical reconciliation.
- Risk, guardrail, DecisionCompiler, ExecutionEngine, OrderRouter, BrokerGateway, TruthKernel, or reconciliation is bypassed.
- Unhandled exception loop.

## Rollback And Kill

- Stop foreground runtime with `Ctrl+C`.
- If Windows process hangs:

```powershell
taskkill /IM python.exe /F
```

- Disable autonomous paper by setting `POVERTY_KILLER_SHADOW_READ_ONLY=1`.
- Remove paper mutation approval flags.
- Do not use emergency liquidation in shadow mode.

## Forbidden Actions

- No live real-money trading.
- No live endpoint.
- No unapproved broker mutation.
- No direct broker REST bypass.
- No market orders unless separately approved by governing execution law.
- No sell, rebalance, cancel/replace loop, retry storm, fake fills, fake quotes, fake PnL, fake slippage, fake fees, fake net edge, or fake profitability.

## Readiness Status

Seam 7H compile/focused/regression proof:

- Compile check passed.
- Focused Seam 7H operator/monitoring/readiness test passed: `5 passed`.
- Scoped Seam 7G/7F/7E/execution/broker/guardrail/state regression passed: `68 passed`.
- Packet-listed `tests/test_shadow_read_only_runtime_gate.py` does not exist and was omitted under the packet's missing-file rule.
- Approved bounded shadow command ran:
  `timeout 60s venv/Scripts/python.exe main.py --paper --shadow-read-only --log-level INFO`
- Bounded shadow result: exited `124` at the external 60-second timeout.
- Paper mode confirmed in runtime output/logs: `Broker Mode: paper`.
- Shadow mode confirmed in runtime output/logs: `Shadow Read Only: ENABLED`.
- Feed ingress confirmed: Kraken websocket connected, `FEED_CANDLE #1`, `FEED_BOOK #1`, and later `FEED_BOOK #2200`.
- Fusion path active: `FUSION_UPDATE_CALLED` appeared for runtime symbols.
- No current-run broker mutation/order markers were found in the bounded-window log scan.

Final blocker burn-down update at `4b7ac8e` plus current working packet:

- Kraken REST DNS / feed truth blocker: cleared at deterministic level by explicit `WEBSOCKET_ACTIVE_REST_DNS_FAILED` / `MARKET_DATA_PARTIAL_TRUTH` handling.
- Alpaca PAPER read-only reconciliation: proven with sanitized real read-only GETs through `AlpacaPaperBrokerAdapter`.
  - endpoint: `https://paper-api.alpaca.markets`
  - environment: `paper`
  - account_status: `read`
  - positions_count: `7`
  - open_orders_count: `0`
  - request_counts: `GET=3`, `POST=0`
  - mutation_occurred: `false`
  - live_endpoint_used: `false`
- Physical fuse: `PHYSICAL_FUSE_STALE`.
  - persisted `physical_fuse_triggered=true`
  - `current_equity=20000.0`
  - `high_water_mark=20000.0`
  - `physical_fuse=15000.0`
  - `last_breach_time=2026-05-08T08:08:13.711138`
  - requires operator action through the owning `HybridRiskGuard` reset path.

Current verdict: `NOT_READY_FOR_AUTONOMOUS_PAPER`.

Reason: module-level operator/monitoring readiness and no-live/no-mutation posture passed, and Alpaca PAPER read-only reconciliation is now proven. Autonomous PAPER mutation remains blocked because the persisted physical fuse is still active/stale and must not be bypassed.

- Remaining blocker: `PHYSICAL_FUSE_REQUIRES_OPERATOR_ACTION`.

Autonomous PAPER mutation should not be launched until the physical fuse is lawfully reset/acknowledged by the owning guard and a fresh bounded shadow run is clean.

Physical fuse operator reset packet update:

- Owner-confirmed reset authority: `HybridRiskGuard` in `app/risk/guard.py`.
- Lawful reset path added: `HybridRiskGuard.reset_stale_physical_fuse_with_evidence(...)`.
- Reset requirements: stale fuse classification, explicit operator acknowledgment, paper broker read-only reconciliation, no live endpoint, no broker mutation, POST/PATCH/DELETE count `0`, shadow-read-only evidence, no broker/local conflict, and no other active fuse.
- Real persisted state was not reset in this packet.
- Current real fuse status remains `PHYSICAL_FUSE_STALE`.
- Current final verdict remains `NOT_READY_FOR_AUTONOMOUS_PAPER` until the operator applies the evidence-gated reset path and a fresh bounded shadow-read-only run is clean.

## Applied Physical Fuse Reset Update

Current HEAD at reset application: `a663d86`.

The physical fuse operator reset was applied through `HybridRiskGuard.reset_stale_physical_fuse_with_evidence(...)` using explicit operator approval and fresh sanitized Alpaca PAPER read-only evidence:

- endpoint: `https://paper-api.alpaca.markets`
- environment: `paper`
- account status: `read`
- positions count: `7`
- open orders count: `0`
- request counts: `GET=3`, `POST=0`, `PATCH=0`, `DELETE=0`
- mutation occurred: `false`
- live endpoint used: `false`

Physical fuse result:

- before: `PHYSICAL_FUSE_STALE`
- after: `PHYSICAL_FUSE_CLEARED`
- persisted `physical_fuse_triggered`: `false`
- reset audit event: `PHYSICAL_FUSE_OPERATOR_RESET_APPLIED`

Fresh bounded shadow command:

```bash
timeout 60s venv/Scripts/python.exe main.py --paper --shadow-read-only --log-level INFO
```

Fresh bounded shadow result:

- exited `124` at the external 60-second timeout
- paper mode confirmed
- shadow-read-only confirmed
- Kraken websocket connected
- feed ingress and fusion/dispatch diagnostics occurred
- current-run physical fuse alert scan found no physical fuse alerts
- current-run broker mutation marker scan found no order submission or broker mutation markers
- Kraken REST DNS failures continued for candle/order-book polling
- websocket crossed-book validation prevented invalid book snapshots
- runtime triggered `LAG ABORT: infms > 200.0ms`
- `ExecutionEngine` entered safe mode and later logged latency recovery

Current verdict: `NOT_READY_FOR_AUTONOMOUS_PAPER`.

The physical fuse and Alpaca PAPER reconciliation launch blockers are cleared. The fresh shadow run exposed a separate safety blocker, `LAG_ABORT_ACTIVE`, so autonomous PAPER launch remains blocked until latency/safe-mode readiness is clean in a new bounded shadow run.

Applied reset verification:

- compile: passed
- focused test: `7 passed`
- scoped regression: `57 passed`
- no mutation approval flags were set
- no autonomous PAPER launch was run
