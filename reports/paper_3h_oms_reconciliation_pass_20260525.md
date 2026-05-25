# 3h PAPER OMS Reconciliation Pass - 2026-05-25

## Verdict

PASS

The 3-hour Alpaca PAPER observation run completed successfully after commit
`e6dcda60b5244c9cb1da6ef7ca17dca6c1f6e3f3`
(`OMS final reconciliation + fill ledger cleanup`).

Primary question answered: the OMS final reconciliation and fill-ledger cleanup held over a long PAPER run with real approved PAPER broker POST and DELETE activity.

## Run Evidence

- stdout: `logs/paper_runs/bounded_paper_20260525_115049.out.log`
- stderr: `logs/paper_runs/bounded_paper_20260525_115049.err.log`
- command: `.\scripts\run_bounded_paper.ps1 -Run -ApproveAutonomousPaper -PaperExplorationAlpha -DurationSeconds 10800 -Watchlist "BTC/USD,ETH/USD,SOL/USD"`
- start: `2026-05-25 16:50:54.403`
- end: `2026-05-25 19:50:56.897`
- observed runtime: `10,799.752s` of requested `10,800s`
- `BOUNDED_RUNTIME_TIMER_STARTED`: present
- `BOUNDED_RUNTIME_DURATION_ELAPSED`: present
- `Poverty Killer shutdown complete`: present
- stderr: empty, `0` lines

## Profile, Universe, And Safety

- `PAPER_EXPLORATION_ALPHA`: active
- active universe: `BTC/USD`, `ETH/USD`, `SOL/USD`
- active asset class: crypto only
- `AAPL`: `0`
- `SPY`: `0`
- live endpoint marker: `0`
- real-money marker: `0`
- `broker_post=True`: `0`
- unauthorized mutation: none found
- naked SELL count: `0`
- unsupported short broker submission: `0`
- MovingFloor did not open trades

PAPER broker mutation occurred only through the approved Alpaca PAPER path. The `/v2/orders` markers and `mutation_occurred=True` records are expected for approved PAPER POST and DELETE operations and are not safety failures.

## Decision And Order Activity

- `candidate_lifecycle`: `702`
- `opportunity_scorecard`: `669`
- unique `frame_id`: `188`
- `decision_compile_attempted`: `187`
- `DecisionRecord compiled`: `187`
- `submit_signal_called=True`: `16`
- canonical submitted count: `15`
- `order_post_attempted`: `15`
- `order_post_authorized`: `15`
- `order_post_acknowledged`: `15`
- `cancel_attempted`: `14`
- `cancel_authorized`: `14`
- `cancel_acknowledged`: `14`
- final `mutation_method_counts`: `GET=198`, `POST=15`, `DELETE=14`

Raw broker acknowledgement markers may appear higher in log searches because shutdown replays broker boundary history. The canonical shutdown split fields are the authority for mutation counts.

## OMS And Reconciliation

- `SHUTDOWN_ACCOUNTING`: present
- `SHUTDOWN_RECONCILIATION`: present
- `open_orders`: `0`
- `broker_confirmed_open_orders`: `0`
- `local_open_without_broker_match_count`: `0`
- `pending_terminal_leak_count`: `0`
- `engine_pending_orders`: `0`
- `engine_pending_order_ids`: `()`
- `terminal_orders`: `72`
- `filled_orders`: `11`
- `canceled_orders`: `61`
- `reconciliation_conflicts`: `0`
- `zombie_sweeper_errors`: `0`
- `ZOMBIE_SWEEP_FAILED`: `0`
- `CANCEL_ALREADY_ATTEMPTED`: `0`
- `cancel_denials`: `{}`

The previous long-run failure is fixed. Local shutdown `open_orders` no longer disagrees with broker final open-order truth.

## Conditional Item

- `fill_hydration_missing_count`: `11`
- `fill_hydration_count`: `0`
- `local_fills`: `0`

This is not an OMS reconciliation failure. The system reported missing fill detail honestly instead of inventing fills. The next seam should hydrate broker fill/activity data and attach fee, slippage, realized-vs-modeled NetEdge, and execution quality/TCA accounting.

## Plain-English Summary

The 3-hour PAPER run worked. The bot ran the full duration, used the intended PAPER exploration profile, stayed in the crypto watchlist, made lawful Alpaca PAPER BUY submissions, processed approved PAPER cancels, reconciled broker state at shutdown, and left no local/broker open-order mismatch. The OMS bug that previously left a local open order when the broker had none stayed fixed.

## Recommended Next Action

Move to the execution quality / TCA / fill economics seam:

- broker activity/fill hydration
- fee and slippage ledger
- realized vs modeled NetEdge
- order lifecycle performance accounting
- PAPER execution quality dashboards and audit tooling

Do not overclaim institutional-grade status until repeated long-run PAPER passes, fill economics, replay/live-paper parity, cloud watchdogs, alerts, status UI, and runbooks are proven.
