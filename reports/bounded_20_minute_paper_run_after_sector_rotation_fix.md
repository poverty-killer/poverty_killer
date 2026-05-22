# Bounded 20-Minute PAPER Run After SectorRotation Fix

Date: 2026-05-22
Command:

```powershell
.\scripts\run_bounded_paper.ps1 -Run -ApproveAutonomousPaper -DurationSeconds 1200 -Watchlist "BTC/USD,ETH/USD,SOL/USD"
```

Logs:

- stdout: `logs\paper_runs\bounded_paper_20260522_001709.out.log`
- stderr: `logs\paper_runs\bounded_paper_20260522_001709.err.log`

## Verdict

CONDITIONAL.

## Summary

The SectorRotation observed-pair repair worked in runtime. Candidates reached `OBSERVED_PAIR_READY`, DecisionCompiler, and `submit_signal_called`.

## Safety / Reconciliation

- Alpaca PAPER reconciliation passed.
- Account: `ACTIVE`
- Positions: `7 -> 7`
- Open orders: `0 -> 0`
- GET: `3`
- POST: `0`
- `/v2/orders` marker in run log: `0`
- Broker POST marker: `0`
- Local orders: `0`
- Local fills: `0`
- `mutation_occurred=false`
- `live_endpoint_used=false`
- stderr only had a Python datetime deprecation warning.

## Runtime Activity Counts

- DecisionRecords compiled: `3`
- `submit_signal_called`: `3`
- submitted true: `0`
- submitted false: `3`
- `observed_pair_stored`: `112`
- `OBSERVED_PAIR_READY`: `118`
- `OBSERVED_PAIR_STALE`: `12`
- `OBSERVED_SIGNAL_MISSING`: `62`
- `OBSERVED_VOTE_MISSING`: `0`
- `OBSERVED_PAIR_CANDLE_MISMATCH`: `0`
- `OBSERVED_PAIR_SYMBOL_MISMATCH`: `0`
- safe-mode lag cycles: `98`
- ShadowFront whale-condition declines: `15`
- Shans/Fusion active: `1911` Shans signal results / Fusion updates

## Candidate Outcomes

1. `SOL/USD` buy, `8ec2dde8-...`
   - `OBSERVED_PAIR_READY`
   - DecisionRecord compiled
   - pre-trade guardrails: `ALLOW`
   - `submitted=False`
   - blocker: `EXECUTION_ADMISSION_BLOCKED`, `DATA_UNHEALTHY`
   - no broker POST

2. `SOL/USD` buy, `944ea150-...`
   - `OBSERVED_PAIR_READY`
   - DecisionRecord compiled
   - pre-trade guardrails: `ALLOW`
   - `submitted=False`
   - blocker: `EXECUTION_ADMISSION_BLOCKED`, `DATA_UNHEALTHY`
   - no broker POST

3. `SOL/USD` sell, `1a5bb03f-...`
   - `OBSERVED_PAIR_READY`
   - DecisionRecord compiled
   - `submitted=False`
   - blocker: `PRE_TRADE_GUARDRAIL_BLOCKED`
   - reason codes:
     - `PREFERRED_PORTAL_UNSUPPORTED`
     - `ACTION_UNSUPPORTED`
     - `QUOTE_SESSION_TRUTH_MISSING`
   - execution admission also blocked:
     - `SAFE_MODE_ACTIVE`
   - no broker POST

## Final Interpretation

The run proves the SectorRotation observed-pair fix successfully moved candidates downstream.

The bot is now blocked later in execution admission / data health / sell guardrail authority, not by observed-pair readiness.

Buy-side pre-trade guardrails allowed, but execution admission blocked due `DATA_UNHEALTHY`.

Sell-side remains intentionally fail-closed because sell/exit/short authority and quote-session truth are not sufficiently proven.

No orders were submitted because the bot correctly blocked before broker mutation.

This is `CONDITIONAL`, not `PASS`, because executable broker submission still did not occur.

## Next Blocker

Primary next seam: `DATA_UNHEALTHY` / execution-admission causal repair for buy candidates, plus safe-mode lag-cycle classification.

Secondary seam: sell-path authority and quote-session truth repair, preserving `ACTION_UNSUPPORTED` unless real sell/exit/short authority and position intent are proven.

## Governance

- no fake market truth
- no fake broker truth
- no threshold lowering
- no forced trades
- no bypassing guardrails
- no live endpoint
- no broker mutation outside approved PAPER
- broker truth canonical
- market-data truth canonical
- conflicts fail closed
