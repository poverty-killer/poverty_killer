# Bounded 20-Minute PAPER Run After Launcher Fix

Date: 2026-05-22

Start HEAD: `7a85cde` - Fix PowerShell launcher preflight execution

## Command

Run from native Windows PowerShell:

```powershell
.\scripts\run_bounded_paper.ps1 -Run -ApproveAutonomousPaper -DurationSeconds 1200 -Watchlist "BTC/USD,ETH/USD,SOL/USD"
```

Configured duration: `1200` seconds.

Captured runtime logs:

- stdout: `logs\paper_runs\bounded_paper_20260521_212913.out.log`
- stderr: `logs\paper_runs\bounded_paper_20260521_212913.err.log`

Observed stdout span: `2026-05-22 02:29:16.278` through `2026-05-22 02:49:13.138` (`1196.86` seconds). Operator reported the launcher stopped by bounded duration.

## Preflight Summary

Native PowerShell preflight passed before runtime:

- account status: `ACTIVE`
- positions before: `7`
- open orders before: `0`
- request counts: `GET=3`, `POST=0`
- credential authority: `CREDENTIAL_AUTHORITY_OK`
- execution broker: `alpaca_paper`
- adapter: `alpaca_paper_rest`
- internal paper selected: `false`
- selected provider: `coinbase_public`
- live endpoint used: `false`
- mutation occurred: `false`
- runtime universe source: `CONFIG_EXPLICIT_ALLOWED:runtime_watchlist`

## Runtime Start And Route

`main.py` started successfully. Runtime startup logs show:

- broker mode: `paper`
- shadow read-only: `DISABLED`
- execution broker: `alpaca_paper`
- execution adapter: `alpaca_paper_rest`
- OrderRouter route: `paper_mode=True execution_broker=alpaca_paper primary_exchange=alpaca broker_gateway_adapter=alpaca_paper_rest`
- internal `SovereignPaperBroker` not wired because external paper broker gateway was selected
- active symbols: `BTC/USD`, `ETH/USD`, `SOL/USD`
- market-data provider: `coinbase_public`
- provider reason: `PRIMARY_SELECTED`
- latency source: `coinbase_public`, `rest_polling`

## Activity Observed

Shans, Fusion, and DecisionCompiler were active:

- Shans order-book entries: `3480`
- Shans signal results: `1947`
- Fusion decisions: `51`
- observe-only strategy votes: `107`
- sector-rotation paper dispatch candidates admitted: `5`
- DecisionRecords compiled during the run window: `5`
- submit-signal attempts: `5`

All five submit-signal attempts returned `submitted=False` and logged `Signal rejected by execution`.

Local telemetry read-only inspection:

- `data/telemetry.db` contains `5` `decision_record` events during the run window.
- `data/state.db` has `0` rows in `orders`.
- `data/state.db` has `0` rows in `fills`.

## Five DecisionCompiler / Submit-Signal Candidate Outcomes

Evidence sources are the stdout runtime log and read-only `data/telemetry.db` decision payloads. No broker mutation was run for this section, and GET-only reconciliation was not repeated.

Common observability limits:

- Exact DecisionCompiler status code is not present in stdout. Telemetry provides `decision_type=strategy_vote`, `truth_status=drifting`, and the attached pre-trade verdict/reason codes. The missing direct DecisionCompiler status code is an observability gap.
- Signal score is not present in the candidate logs. Candidate confidence and telemetry `max_confidence` are present.
- Runtime logs do not show candidate-specific OrderRouter or BrokerGateway invocation. Telemetry module evidence says `ExecutionEngine enforces the pre-trade verdict before OrderRouter`; edge attribution lists OrderRouter/BrokerGateway as preserved execution boundaries, not as reached runtime calls.

### Candidate 1 - `8acfd91c-47f8-4adb-ab56-e838fc0bab5d`

- timestamp: `2026-05-22 02:32:57.543` admitted; telemetry timestamp_ns `1779417177547641600`
- symbol: `BTC/USD`
- side / bias: `buy`
- signal score / confidence: candidate confidence `0.9000`; telemetry `max_confidence=0.9`; signal score not present in log evidence
- DecisionCompiler verdict: DecisionRecord compiled as `type=strategy_vote`; attached pre-trade verdict `BLOCK`
- DecisionCompiler status code / reason code: exact status code not present in log evidence; observability gap. Telemetry reason codes: `PREFERRED_PORTAL_UNSUPPORTED`, `ORDER_TYPE_UNSUPPORTED`, `QUOTE_SESSION_TRUTH_MISSING`
- `submit_signal` returned `submitted=False`: yes
- exact blocker reason: pre-trade guardrail `BLOCK`; portal selection policy `PREFERRED_PORTAL_UNSUPPORTED`; order type `ORDER_TYPE_UNSUPPORTED`; quote/session `QUOTE_SESSION_TRUTH_MISSING`; ExecutionEngine blocks before OrderRouter
- risk veto if any: canonical aggression contract mode `SAFE`, veto reason `safe_mode`; sizing/risk cap allowed with `SIZING_WITHIN_KNOWN_LIMITS`
- economic veto if any: no economic block present; economics advisory missing truth `ECONOMICS_ADVISORY_MISSING_TRUTH`, NetEdgeGovernor `NET_EDGE_MISSING_TRUTH`, TradeEfficiencyGovernor `TRADE_EFFICIENCY_MISSING_TRUTH`
- stale-data / latency / safe-mode veto if any: safe-mode veto present in telemetry; nearby stdout lag window lines `5014-5015` entered safe mode before the candidate and lines `5300`, `5306` recovered after it
- market-data truth status at that moment: `truth_status=drifting`; quote/session truth missing
- execution route at that moment: startup route remained `execution_broker=alpaca_paper`, `execution_adapter=alpaca_paper_rest`, `paper_mode=True`, `primary_exchange=alpaca`, selected feed `coinbase_public`
- whether OrderRouter was reached: no runtime evidence; telemetry says ExecutionEngine blocks before OrderRouter
- whether BrokerGateway was reached: no runtime evidence
- whether any broker POST was attempted: no; marker search found `/v2/orders=0`, `POST=0`, `submit_order=0`
- exact log references / snippets:
  - stdout `5199`: `[PAPER_DISPATCH_SECTOR_ROTATION] BTC/USD: admitted decision_uuid=8acfd91c-47f8-4adb-ab56-e838fc0bab5d side=buy confidence=0.9000 risk_appetite=0.1897`
  - stdout `5204`: `[DISPATCH] BTC/USD: DecisionRecord compiled: uuid=8acfd91c-47f8-4adb-ab56-e838fc0bab5d type=strategy_vote`
  - stdout `5205`: `[DISPATCH_DIAG] reason_code=submit_signal_called ... 'submitted': False, 'submit_signal_called': True`
  - stdout `5207`: `[DISPATCH] BTC/USD: Signal rejected by execution: decision_uuid=8acfd91c-47f8-4adb-ab56-e838fc0bab5d`

### Candidate 2 - `d5ddbbe2-4e39-4139-bca7-5c08d53edc4e`

- timestamp: `2026-05-22 02:32:57.649` admitted; telemetry timestamp_ns `1779417177655633100`
- symbol: `BTC/USD`
- side / bias: `sell`
- signal score / confidence: candidate confidence `0.6602`; telemetry `max_confidence=0.6602`; signal score not present in log evidence
- DecisionCompiler verdict: DecisionRecord compiled as `type=strategy_vote`; attached pre-trade verdict `BLOCK`
- DecisionCompiler status code / reason code: exact status code not present in log evidence; observability gap. Telemetry reason codes: `PREFERRED_PORTAL_UNSUPPORTED`, `ACTION_UNSUPPORTED`, `ORDER_TYPE_UNSUPPORTED`, `QUOTE_SESSION_TRUTH_MISSING`
- `submit_signal` returned `submitted=False`: yes
- exact blocker reason: pre-trade guardrail `BLOCK`; portal selection policy `PREFERRED_PORTAL_UNSUPPORTED`; action `ACTION_UNSUPPORTED`; order type `ORDER_TYPE_UNSUPPORTED`; quote/session `QUOTE_SESSION_TRUTH_MISSING`; ExecutionEngine blocks before OrderRouter
- risk veto if any: canonical aggression contract mode `SAFE`, veto reason `safe_mode`; sizing/risk cap allowed with `SIZING_WITHIN_KNOWN_LIMITS`
- economic veto if any: no economic block present; economics advisory missing truth `ECONOMICS_ADVISORY_MISSING_TRUTH`, NetEdgeGovernor `NET_EDGE_MISSING_TRUTH`, TradeEfficiencyGovernor `TRADE_EFFICIENCY_MISSING_TRUTH`
- stale-data / latency / safe-mode veto if any: safe-mode veto present in telemetry; nearby stdout lag window lines `5014-5015` entered safe mode before the candidate and lines `5300`, `5306` recovered after it
- market-data truth status at that moment: `truth_status=drifting`; quote/session truth missing
- execution route at that moment: startup route remained `execution_broker=alpaca_paper`, `execution_adapter=alpaca_paper_rest`, `paper_mode=True`, `primary_exchange=alpaca`, selected feed `coinbase_public`
- whether OrderRouter was reached: no runtime evidence; telemetry says ExecutionEngine blocks before OrderRouter
- whether BrokerGateway was reached: no runtime evidence
- whether any broker POST was attempted: no; marker search found `/v2/orders=0`, `POST=0`, `submit_order=0`
- exact log references / snippets:
  - stdout `5244`: `[PAPER_DISPATCH_SECTOR_ROTATION] BTC/USD: admitted decision_uuid=d5ddbbe2-4e39-4139-bca7-5c08d53edc4e side=sell confidence=0.6602 risk_appetite=0.1701`
  - stdout `5249`: `[DISPATCH] BTC/USD: DecisionRecord compiled: uuid=d5ddbbe2-4e39-4139-bca7-5c08d53edc4e type=strategy_vote`
  - stdout `5250`: `[DISPATCH_DIAG] reason_code=submit_signal_called ... 'submitted': False, 'submit_signal_called': True`
  - stdout `5252`: `[DISPATCH] BTC/USD: Signal rejected by execution: decision_uuid=d5ddbbe2-4e39-4139-bca7-5c08d53edc4e`

### Candidate 3 - `082e9e92-4772-4de2-a859-3cbf40ec078d`

- timestamp: `2026-05-22 02:37:57.334` admitted; telemetry timestamp_ns `1779417477338130800`
- symbol: `BTC/USD`
- side / bias: `buy`
- signal score / confidence: candidate confidence `0.9000`; telemetry `max_confidence=0.9`; signal score not present in log evidence
- DecisionCompiler verdict: DecisionRecord compiled as `type=strategy_vote`; attached pre-trade verdict `BLOCK`
- DecisionCompiler status code / reason code: exact status code not present in log evidence; observability gap. Telemetry reason codes: `PREFERRED_PORTAL_UNSUPPORTED`, `ORDER_TYPE_UNSUPPORTED`, `QUOTE_SESSION_TRUTH_MISSING`
- `submit_signal` returned `submitted=False`: yes
- exact blocker reason: pre-trade guardrail `BLOCK`; portal selection policy `PREFERRED_PORTAL_UNSUPPORTED`; order type `ORDER_TYPE_UNSUPPORTED`; quote/session `QUOTE_SESSION_TRUTH_MISSING`; ExecutionEngine blocks before OrderRouter
- risk veto if any: canonical aggression contract mode `SAFE`, veto reason `safe_mode`; sizing/risk cap allowed with `SIZING_WITHIN_KNOWN_LIMITS`
- economic veto if any: no economic block present; economics advisory missing truth `ECONOMICS_ADVISORY_MISSING_TRUTH`, NetEdgeGovernor `NET_EDGE_MISSING_TRUTH`, TradeEfficiencyGovernor `TRADE_EFFICIENCY_MISSING_TRUTH`
- stale-data / latency / safe-mode veto if any: safe-mode veto present in telemetry; nearby stdout lag window lines `10598-10599` entered safe mode before the candidate and lines `11279-11280` recovered after it
- market-data truth status at that moment: `truth_status=drifting`; quote/session truth missing
- execution route at that moment: startup route remained `execution_broker=alpaca_paper`, `execution_adapter=alpaca_paper_rest`, `paper_mode=True`, `primary_exchange=alpaca`, selected feed `coinbase_public`
- whether OrderRouter was reached: no runtime evidence; telemetry says ExecutionEngine blocks before OrderRouter
- whether BrokerGateway was reached: no runtime evidence
- whether any broker POST was attempted: no; marker search found `/v2/orders=0`, `POST=0`, `submit_order=0`
- exact log references / snippets:
  - stdout `11178`: `[PAPER_DISPATCH_SECTOR_ROTATION] BTC/USD: admitted decision_uuid=082e9e92-4772-4de2-a859-3cbf40ec078d side=buy confidence=0.9000 risk_appetite=0.1701`
  - stdout `11183`: `[DISPATCH] BTC/USD: DecisionRecord compiled: uuid=082e9e92-4772-4de2-a859-3cbf40ec078d type=strategy_vote`
  - stdout `11184`: `[DISPATCH_DIAG] reason_code=submit_signal_called ... 'submitted': False, 'submit_signal_called': True`
  - stdout `11186`: `[DISPATCH] BTC/USD: Signal rejected by execution: decision_uuid=082e9e92-4772-4de2-a859-3cbf40ec078d`

### Candidate 4 - `bcfeb876-8754-4dcd-9e11-4be24083c3b8`

- timestamp: `2026-05-22 02:44:12.595` admitted; telemetry timestamp_ns `1779417852598856300`
- symbol: `ETH/USD`
- side / bias: `buy`
- signal score / confidence: candidate confidence `0.7196`; telemetry `max_confidence=0.7196`; signal score not present in log evidence
- DecisionCompiler verdict: DecisionRecord compiled as `type=strategy_vote`; attached pre-trade verdict `BLOCK`
- DecisionCompiler status code / reason code: exact status code not present in log evidence; observability gap. Telemetry reason codes: `PREFERRED_PORTAL_UNSUPPORTED`, `ORDER_TYPE_UNSUPPORTED`, `QUOTE_SESSION_TRUTH_MISSING`
- `submit_signal` returned `submitted=False`: yes
- exact blocker reason: pre-trade guardrail `BLOCK`; portal selection policy `PREFERRED_PORTAL_UNSUPPORTED`; order type `ORDER_TYPE_UNSUPPORTED`; quote/session `QUOTE_SESSION_TRUTH_MISSING`; ExecutionEngine blocks before OrderRouter
- risk veto if any: canonical aggression contract mode `SAFE`, veto reason `safe_mode`; sizing/risk cap allowed with `SIZING_WITHIN_KNOWN_LIMITS`
- economic veto if any: no economic block present; economics advisory missing truth `ECONOMICS_ADVISORY_MISSING_TRUTH`, NetEdgeGovernor `NET_EDGE_MISSING_TRUTH`, TradeEfficiencyGovernor `TRADE_EFFICIENCY_MISSING_TRUTH`
- stale-data / latency / safe-mode veto if any: safe-mode veto present in telemetry; nearby stdout lag window lines `18452-18453` entered safe mode before the candidate and lines `18798`, `18805` recovered after it
- market-data truth status at that moment: `truth_status=drifting`; quote/session truth missing
- execution route at that moment: startup route remained `execution_broker=alpaca_paper`, `execution_adapter=alpaca_paper_rest`, `paper_mode=True`, `primary_exchange=alpaca`, selected feed `coinbase_public`
- whether OrderRouter was reached: no runtime evidence; telemetry says ExecutionEngine blocks before OrderRouter
- whether BrokerGateway was reached: no runtime evidence
- whether any broker POST was attempted: no; marker search found `/v2/orders=0`, `POST=0`, `submit_order=0`
- exact log references / snippets:
  - stdout `18634`: `[PAPER_DISPATCH_SECTOR_ROTATION] ETH/USD: admitted decision_uuid=bcfeb876-8754-4dcd-9e11-4be24083c3b8 side=buy confidence=0.7196 risk_appetite=0.5000`
  - stdout `18639`: `[DISPATCH] ETH/USD: DecisionRecord compiled: uuid=bcfeb876-8754-4dcd-9e11-4be24083c3b8 type=strategy_vote`
  - stdout `18640`: `[DISPATCH_DIAG] reason_code=submit_signal_called ... 'submitted': False, 'submit_signal_called': True`
  - stdout `18642`: `[DISPATCH] ETH/USD: Signal rejected by execution: decision_uuid=bcfeb876-8754-4dcd-9e11-4be24083c3b8`

### Candidate 5 - `3364e384-8fed-410c-92d4-122eaa632b0e`

- timestamp: `2026-05-22 02:45:38.588` admitted; telemetry timestamp_ns `1779417938592897800`
- symbol: `SOL/USD`
- side / bias: `buy`
- signal score / confidence: candidate confidence `0.7263`; telemetry `max_confidence=0.7263`; signal score not present in log evidence
- DecisionCompiler verdict: DecisionRecord compiled as `type=strategy_vote`; attached pre-trade verdict `BLOCK`
- DecisionCompiler status code / reason code: exact status code not present in log evidence; observability gap. Telemetry reason codes: `PREFERRED_PORTAL_UNSUPPORTED`, `ORDER_TYPE_UNSUPPORTED`, `QUOTE_SESSION_TRUTH_MISSING`
- `submit_signal` returned `submitted=False`: yes
- exact blocker reason: pre-trade guardrail `BLOCK`; portal selection policy `PREFERRED_PORTAL_UNSUPPORTED`; order type `ORDER_TYPE_UNSUPPORTED`; quote/session `QUOTE_SESSION_TRUTH_MISSING`; ExecutionEngine blocks before OrderRouter
- risk veto if any: canonical aggression contract mode `SAFE`, veto reason `safe_mode`; sizing/risk cap allowed with `SIZING_WITHIN_KNOWN_LIMITS`
- economic veto if any: no economic block present; economics advisory missing truth `ECONOMICS_ADVISORY_MISSING_TRUTH`, NetEdgeGovernor `NET_EDGE_MISSING_TRUTH`, TradeEfficiencyGovernor `TRADE_EFFICIENCY_MISSING_TRUTH`
- stale-data / latency / safe-mode veto if any: safe-mode veto present in telemetry; nearby stdout lag window lines `20113-20114` entered safe mode before the candidate and lines `20536`, `20543` recovered after it
- market-data truth status at that moment: `truth_status=drifting`; quote/session truth missing
- execution route at that moment: startup route remained `execution_broker=alpaca_paper`, `execution_adapter=alpaca_paper_rest`, `paper_mode=True`, `primary_exchange=alpaca`, selected feed `coinbase_public`
- whether OrderRouter was reached: no runtime evidence; telemetry says ExecutionEngine blocks before OrderRouter
- whether BrokerGateway was reached: no runtime evidence
- whether any broker POST was attempted: no; marker search found `/v2/orders=0`, `POST=0`, `submit_order=0`
- exact log references / snippets:
  - stdout `20372`: `[PAPER_DISPATCH_SECTOR_ROTATION] SOL/USD: admitted decision_uuid=3364e384-8fed-410c-92d4-122eaa632b0e side=buy confidence=0.7263 risk_appetite=0.5000`
  - stdout `20377`: `[DISPATCH] SOL/USD: DecisionRecord compiled: uuid=3364e384-8fed-410c-92d4-122eaa632b0e type=strategy_vote`
  - stdout `20378`: `[DISPATCH_DIAG] reason_code=submit_signal_called ... 'submitted': False, 'submit_signal_called': True`
  - stdout `20380`: `[DISPATCH] SOL/USD: Signal rejected by execution: decision_uuid=3364e384-8fed-410c-92d4-122eaa632b0e`

## Safety, Feed, And Latency Events

The run was safe, but not clean enough for a PASS verdict:

- `LAG ABORT`: `80`
- `LAG DETECTED`: `80`
- `Latency recovered`: `80`
- data-feed recovered events: `1355`
- first health line showed `mode=SAFE`, `orders=0/0`, `invalid_books=0`, `symbols=3`
- stderr contained only a Python `datetime.utcnow()` deprecation warning
- no traceback
- no `ERROR`
- no `CRITICAL`

No-trade / non-submission evidence:

- `submitted=False`: `5`
- `Signal rejected by execution`: `5`
- `observed_pair_missing`: `16`
- `observed_pair_stale`: `6`
- `volume_zscore_below_threshold`: `753`
- `in_position`: `218`

Representative exact no-trade path:

1. Sector-rotation candidate admitted.
2. DecisionRecord compiled.
3. `submit_signal_called` logged.
4. submission result was `submitted=False`.
5. signal was rejected before broker submission.

Additional repeated blockers included stale/missing observed pairs, low Fusion confidence around `0.17` to `0.22` on several dispatches, neutral whale contribution, `attack_mode=False`, and repeated lag/safe-mode episodes.

## Broker Mutation Marker Search

Runtime log marker search:

- `/v2/orders`: `0`
- `POST`: `0`
- `submit_order`: `0`
- broker POST marker: `0`
- live endpoint marker: `0`
- `https://api.alpaca.markets`: `0`
- real-money marker: `0`

Broker order counts:

- submitted: `0`
- filled: `0`
- open: `0`
- broker rejected: `0`
- canceled: `0`

Local execution rejected five candidate signals before broker submission. These were not broker order rejections.

## Post-Run GET-Only Reconciliation

Reconciliation used the existing Alpaca PAPER read-only helper:

- `AlpacaPaperBrokerAdapter.from_env(...)`
- `collect_alpaca_paper_read_only_reconciliation_truth(adapter)`

Only the supported helper path was used:

- account GET
- positions GET
- open orders GET

The existing helper does not support full order-history GET; its `/v2/orders` access is guarded to `status=open`.

Sanitized post-run result:

- status: `BROKER_READ_ONLY_RECONCILED`
- reason: `BROKER_READ_ONLY_GETS_SUCCEEDED`
- endpoint: `https://paper-api.alpaca.markets`
- environment: `paper`
- account status: `ACTIVE`
- positions after: `7`
- position symbols: `AAPL`, `AMZN`, `GOOGL`, `NVDA`, `QQQ`, `SPY`, `TSLA`
- open orders after: `0`
- request counts: `GET=3`, `POST=0`
- mutation occurred: `false`
- live endpoint used: `false`

Position/open-order comparison:

- positions before: `7`
- positions after: `7`
- open orders before: `0`
- open orders after: `0`

## Verdict

CONDITIONAL

The run completed safely under the bounded Windows PowerShell launcher and post-run broker reconciliation succeeded. No live endpoint, real-money marker, `/v2/orders` marker, broker POST, unauthorized mutation, broker conflict, fake truth, traceback, or unreconciled broker state was found.

The verdict is conditional rather than pass because the run exposed operational blockers: repeated lag abort / safe-mode cycles and zero broker orders. Five strategy candidates reached DecisionCompiler and submit-signal handling, but all five were rejected before broker submission. Zero orders are truthfully explained by pre-broker execution rejection plus recurring stale/missing observed-pair, volume-threshold, in-position, and latency/safe-mode conditions.
