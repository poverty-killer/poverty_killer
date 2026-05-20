# Autonomous PAPER Friday Readiness

## Current Commit

- Base HEAD before this operation: `687c1e3` - Add bot-wide shadow read-only runtime gate.
- Closeout commit for this operation: pending at report write time.

## Commands

Shadow proof command:

```bash
main.py --paper --shadow-read-only --log-level INFO
```

Equivalent env override:

```bash
POVERTY_KILLER_SHADOW_READ_ONLY=1 main.py --paper --log-level INFO
```

Autonomous PAPER command, only after explicit Board approval:

```bash
main.py --paper --log-level INFO
```

Equivalent env posture:

```bash
POVERTY_KILLER_SHADOW_READ_ONLY=0 main.py --paper --log-level INFO
```

Do not use live mode. Do not pass `--attack` unless separately approved.

## Environment

- Required broker posture: `--paper`.
- Required shadow proof posture before autonomous launch: `--shadow-read-only` or `POVERTY_KILLER_SHADOW_READ_ONLY=1`.
- If Windows venv is run from WSL, keep credentials in the existing non-secret env path pattern; do not print or copy secrets.
- Mutation approval flags from Seam 6/6C must remain unset during shadow tests.

## Risk And Sizing

- Current config initial capital observed in shadow run: `$20000.00`.
- Current PositionSizingEngine log: `risk_per_trade=2.00%`, `kelly_max=0.25`, `hard_cap=25%`.
- For future Alpaca PAPER crypto tiny-order expansion, use a notional that clears broker minimums. Recommended paper notional is at least `$11`; `$15` gives safer room for precision while still being controlled. Do not exceed Board-approved caps.

## Endpoint And Mode

- Shadow run confirmed `Broker Mode: paper`.
- Shadow run confirmed `Shadow Read Only: ENABLED`.
- No live endpoint or live broker mode appeared in the current-run mutation-marker scan.
- Alpaca PAPER remains the current proven external paper broker path; Kraken provided websocket feed truth in the shadow run.

## Friday 10:00 AM Launch Checklist

1. Confirm latest pushed HEAD includes this operation.
2. Run `git status --short` and verify no unintended staged files.
3. Run the shadow command and verify:
   - `Broker Mode: paper`
   - `Shadow Read Only: ENABLED`
   - websocket feed connects
   - broker mutation count remains zero
   - no `ORDER_SUBMIT_ATTEMPT`, `PAPERBROKER_REACH_COUNT`, `PAPER_FILL_COUNT`, `/v2/orders`, or live-mode markers
4. Review remaining blockers below.
5. Request explicit Board approval before autonomous PAPER mutation.

## Stop Conditions

- Live endpoint or live mode appears.
- Shadow mode can mutate broker state.
- Broker mutation markers appear during shadow.
- DecisionCompiler, ExecutionEngine, OrderRouter, BrokerGateway, PreTradeGuardrails, TruthKernel, or reconciliation are bypassed.
- Quote, feed, broker, state, or economic truth is missing and not labeled truthfully.
- ShansCurve runtime nopython compile error remains unresolved for the active live-data path.
- REST DNS failures prevent required read-only broker/feed truth.

## Rollback / Kill

- Stop the runtime with `Ctrl-C` in the owning terminal.
- If process control is needed, terminate the `main.py --paper ...` process. Do not run emergency liquidation in shadow mode.

## Forbidden Actions

- No live real-money trading.
- No direct broker REST bypass.
- No market orders, sell orders, rebalance, cancel/replace loops, retry storms, fake fills, fake quotes, fake PnL, fake slippage, fake net edge, or fake profitability.

## Remaining Blockers

- `app/brain/shans_curve.py:_savitzky_golay` hit a Numba nopython compile error in the 60-second shadow run: exception matching on `np.linalg.LinAlgError` is unsupported in nopython mode.
- Kraken REST polling returned DNS failures: `Cannot connect to host api.kraken.com:443 ssl:default [Could not contact DNS servers]`.
- During the shadow run, dispatch stayed at `shans_not_ready` / no executable signal. No autonomous PAPER mutation should be approved until the active live-data path is clean.
