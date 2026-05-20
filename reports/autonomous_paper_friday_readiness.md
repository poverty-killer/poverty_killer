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

Current verdict: `NOT_READY_FOR_AUTONOMOUS_PAPER`.

Reason: module-level operator/monitoring readiness and no-live/no-mutation posture passed, but the bounded shadow run exposed launch blockers:

- Critical health alert: `HEALTH ALERT: Physical fuse triggered!`.
- Kraken REST candle/order-book polling DNS failures: `Cannot connect to host api.kraken.com:443 ssl:default [Could not contact DNS servers]`.
- Alpaca PAPER read-only account/positions/open-orders reconciliation truth was not proven in the bounded shadow output.

Autonomous PAPER mutation should not be launched until these blockers are cleared and a fresh bounded shadow run is clean.
