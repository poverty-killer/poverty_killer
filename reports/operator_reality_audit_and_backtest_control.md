# Operator Reality Audit and Historical Test Control

Current pushed base inspected: `8b1f2a9` - Add local operator activation control center.

This report records the operator UI/API reality audit for the seam that adds UI wiring proof, fixes decorative controls, and adds an honest 4-month historical Alpaca test control. It is based on repo source reads, not runtime claims.

## Governance Read

- `AGENTS.md`: Supreme Board authority, preserve-first, repo-truth-first, no fake integration, no broad refactor, no live mode, exact-file staging only.
- `docs/BOARD_AUTOPILOT_PROTOCOL.md`: live mode, commits, pushes, broad refactors, credential edits, destructive Git, and risk weakening are RED/BLACK boundaries.
- `docs/architecture/AUTHORITY_WIRING_MAP.md`: active spine is `main.py -> app/main_loop.py -> app/core/decision_compiler.py -> app/execution/engine.py -> app/execution/order_router.py -> app/execution/paper_broker.py`; these are high-authority and intentionally not touched.
- `docs/architecture/CURRENT_REBUILD_STATUS.md`: advanced organs are preserved, live-money mode is not approved, and context spine gives direction while repo truth gives proof.
- `docs/runbooks/operator_local_launch.md`: local operator console starts API/UI only and does not start PAPER automatically.
- `ui/operator-control-panel/contracts.json`: read-only UI policy, no manual trading, no force trade, server authority required, broker direct calls from UI forbidden.
- `app/operator_intelligence/system_map.py`: MarketTruthSnapshot, DecisionFrame, NetEdge, ExecutionEngine, BrokerBoundary, OMS, Fill/TCA/Fee hydration, Operator API, Supervisor, UI, World Awareness, AI Chief, and live gates were reviewed as the operator boundary map.

## Current Operator Pages

| Page | Supposed job | Existing controls before repair | Wiring after repair |
|---|---|---|---|
| Command Center | At-a-glance runtime truth, launch readiness, blockers, authority state | Status cards, launch readiness only | Adds visible PAPER Launch Control with watchlist, duration, confirmations, disabled reason, and `/operator/intent/paper/start` target |
| Action Center | Consolidate blockers, warnings, approvals, safety critical items | Read-only table | Wired read-only from `/operator/action-center` |
| Run Archive | Flight recorder archive and run reports | Read-only archive table | Wired read-only from `/operator/runs`; adds link to Historical Tests |
| Historical Tests | 4-month Alpaca historical test control | Missing | Added page, form, 4-month preset, read-only/advisory endpoint target `/operator/historical-tests/run` |
| P&L / Net Profit | Broker-confirmed economics and TCA labels | Read-only summary | Wired read-only from `/operator/pnl` and `/operator/tca`; unknown values remain unknown |
| Positions & Orders | PAPER portfolio truth, open orders, position intelligence | Read-only portfolio tables | Wired read-only from `/operator/portfolio`; no cancel/flatten/buy/sell controls |
| Bot Activity Control | Runtime/supervisor status and governed PAPER intents | Form existed but not visible from Command Center | Keeps governed PAPER controls and uses the same safe form model; duplicate start control remains visible rather than removed |
| Signal & Decision Lab | Explain why BUY/SELL/NO_TRADE happened | Read-only DecisionFrame/explainer tables | Wired read-only from `/operator/explain/latest` and summaries |
| Market Data Truth | Show executable vs stale/synthetic/replay truth | Read-only table | Wired display only; no market-truth bypass |
| Risk & Governor | Hard/economic gate display | Read-only table | Display only; no risk override |
| Watchdog Alerts | Local alert queue visibility | Read-only table | Wired from `/operator/alerts`; no external alert delivery |
| AI Chief Operator | Governance queue and advisory AI state | Analyze/review queue buttons | Still wired; global drawer now has a real freeform question flow |
| Provider Setup | Credential/readiness setup | Forms existed but feedback was too weak | Adds per-provider feedback states and disabled backend reason |
| Research OS | Research registry/evidence graph | Read-only/advisory tables | Wired from `/operator/research` and `/operator/research/evidence-graph` |
| System Map | Plain-English engine map | Read-only system map | Wired from `/operator/system-map` |
| Audit Log | Operator evidence timeline | Read-only table | Wired from audit summary/mock |
| World Awareness | Advisory external intelligence | Manual poll button | Wired to `/operator/intent/world-awareness/poll`; advisory only |
| Diagnostics | Backend and runtime diagnostics | Environment/status table | Adds UI Wiring Audit panel with control counts, statuses, endpoints, and reasons |
| Live Readiness | Live gate visibility | Read-only live refusal | Live remains locked and read-only |

## Control Inventory and Wiring Proof

Every visible interactive control is now represented by `buildUiControlInventory()` in `ui/operator-control-panel/app.js`. The Diagnostics page renders the inventory and counts:

- `WIRED`
- `DISABLED_WITH_REASON`
- `NOT_IMPLEMENTED_VISIBLE`
- `BROKEN`
- `REMOVED`

The implemented inventory includes:

| Page | Control | Type | Endpoint/local action | Safety class | Status |
|---|---|---|---|---|---|
| global | Snapshot intent - disabled | button | none | forbidden | DISABLED_WITH_REASON |
| global | Live locked | button | none | forbidden | DISABLED_WITH_REASON |
| global | Ask Quant Chief | button | local open drawer | read_only | WIRED |
| navigation | All page nav buttons | button | local `showScreen` | read_only | WIRED |
| ai_overlay | Quick prompt buttons | button | local prompt selection | read_only | WIRED |
| ai_overlay | Question textarea | input | page context prompt | read_only | WIRED |
| ai_overlay | Ask Quant Chief | button | `POST /operator/ai/ask` | local_advisory_write | WIRED |
| ai_overlay | Clear | button | local clear | read_only | WIRED |
| ai_overlay | Close | button | local close | read_only | WIRED |
| command | PAPER watchlist | input | `/operator/intent/paper/start` payload | governed_paper_start | WIRED |
| command | PAPER duration | select | `/operator/intent/paper/start` payload | governed_paper_start | WIRED |
| command | Start Bounded PAPER Run | button | `POST /operator/intent/paper/start` | governed_paper_start | WIRED or DISABLED_WITH_REASON |
| activity | Start bounded PAPER | button | `POST /operator/intent/paper/start` | governed_paper_start | WIRED or DISABLED_WITH_REASON |
| activity | Stop PAPER | button | `POST /operator/intent/paper/stop` | governed_paper_start | WIRED or DISABLED_WITH_REASON |
| activity | Export run report | button | none | read_only | NOT_IMPLEMENTED_VISIBLE |
| activity | Live start locked | button | none | forbidden | DISABLED_WITH_REASON |
| providers | Save local credentials | button | `POST /operator/credentials/save` | local_secret_write | WIRED or DISABLED_WITH_REASON |
| providers | Validate read-only | button | `POST /operator/credentials/validate-readonly` | read_only | WIRED or DISABLED_WITH_REASON |
| providers | Delete local credentials | button | `DELETE /operator/credentials/provider/{provider_id}` | local_secret_write | WIRED or DISABLED_WITH_REASON |
| world | Poll Alpaca News | button | `POST /operator/intent/world-awareness/poll` | read_only | WIRED or DISABLED_WITH_REASON |
| ai | Run advisory AI analysis | button | `POST /operator/ai/analyze` | local_advisory_write | WIRED or DISABLED_WITH_REASON |
| ai | Queue Quant Chief review | button | `POST /operator/ai/quant-review` | local_advisory_write | WIRED or DISABLED_WITH_REASON |
| historical | Run Historical Test | button | `POST /operator/historical-tests/run` | read_only | WIRED or DISABLED_WITH_REASON |
| runs | Open Historical Tests | button | local navigation | read_only | WIRED |

No visible control is intentionally left as a silent click. If backend is unavailable, credential/historical/PAPER/AI controls are disabled or return explicit feedback.

## Broken or Decorative Controls Found

1. **Ask Quant Chief global button**
   - Finding: Button existed, but the drawer did not expose a freeform question textarea, Ask button, Clear button, or direct ask endpoint.
   - Fix: Added visible textarea, Ask/Clear/Close buttons, prompt suggestions, loading/error state, advisory banner, and `POST /operator/ai/ask`.

2. **Command Center PAPER launch**
   - Finding: Launch readiness was visible, but the Command Center did not show the watchlist, duration, confirmations, or visible start button.
   - Fix: Added PAPER Launch Control directly to Command Center and kept Bot Activity Control access.

3. **Credential flow feedback**
   - Finding: Credential forms could appear to save silently.
   - Fix: Added per-provider feedback states: saving, saved/status, validating, deleting, failed, backend unavailable.

4. **Backend status clarity**
   - Finding: `PARTIAL_BACKEND` was too vague.
   - Fix: Source label and Diagnostics now show exact failed endpoint reasons from `data.meta.fetchFailures`.

5. **Historical Alpaca test**
   - Finding: No operator surface or endpoint existed for a 4-month Alpaca historical test.
   - Fix: Added Historical Tests page and backend endpoints. The system honestly reports that no governed simulation harness is attached and does not invent performance numbers.

## Endpoint Wiring

Existing read-only/advisory endpoints inspected:

- `GET /operator/status`
- `GET /operator/runtime`
- `GET /operator/latest-run`
- `GET /operator/action-center`
- `GET /operator/providers/readiness`
- `GET /operator/credentials/providers`
- `POST /operator/credentials/save`
- `POST /operator/credentials/validate-readonly`
- `DELETE /operator/credentials/provider/{provider_id}`
- `GET /operator/launch-readiness`
- `POST /operator/intent/paper/start`
- `GET /operator/portfolio`
- `GET /operator/positions`
- `GET /operator/orders/open`
- `GET /operator/positions/intelligence`
- `GET /operator/research`
- `GET /operator/research/evidence-graph`
- `GET /operator/ai/status`
- `GET /operator/ai/recommendations`
- `POST /operator/ai/analyze`
- `POST /operator/ai/quant-review`
- `POST /operator/ai/draft-codex-packet`
- `GET /operator/world-awareness`
- `GET /operator/world-awareness/providers`
- `GET /operator/world-awareness/events`
- `GET /operator/world-awareness/runtime`
- `GET /operator/readiness/live`
- `GET /operator/health`
- `GET /operator/readiness`
- `GET /operator/storage`
- `GET /operator/runs`
- `GET /operator/pnl`
- `GET /operator/tca`
- `GET /operator/alerts`
- `GET /operator/system-map`

New endpoints added:

- `POST /operator/ai/ask`
- `GET /operator/historical-tests`
- `POST /operator/historical-tests/run`
- `GET /operator/historical-tests/{test_id}`
- `GET /operator/historical-tests/{test_id}/report`

## Missing or Degraded Endpoints

The static UI now treats `/operator/status` as primary backend truth. Secondary endpoint failures are recorded by endpoint and displayed as specific degraded reasons. A partial backend should now be inspectable without opening dev tools.

The historical test endpoint is intentionally not a performance engine yet. It returns:

- `NOT_IMPLEMENTED_READY_FOR_HARNESS` when no historical data client or replay harness is attached.
- `DATA_READY_SIMULATION_NOT_AVAILABLE` when a read-only/fake historical data client provides data but no governed simulation harness exists.

## Pages That Overlap and Should Be Considered for Future Collapse

No pages were removed, hidden, or collapsed in this seam because Shan explicitly required approval before removal/collapse.

Recommended future grouping, pending Shan approval:

1. Command Center
   - launch readiness
   - PAPER launch
   - runtime state
   - biggest blockers
   - AI drawer access
2. Portfolio & Orders
   - positions
   - open orders
   - P&L/TCA
   - position intelligence
3. Runs & Historical Tests
   - run archive
   - reports
   - historical test
4. Signals & Market Truth
   - decision lab
   - market data truth
   - world awareness summary
5. Risk & Governance
   - risk/governor
   - action center
   - watchdog
   - live readiness
6. Setup & Providers
   - credentials
   - provider readiness
   - storage/diagnostics
7. Research OS / AI Chief
   - AI Quant Chief
   - research registry
   - evidence graph
   - promotion gates
8. System / Audit
   - system map
   - audit log
   - UI wiring audit

## Implemented but Previously Not Exposed Enough

- Governed PAPER start existed at `/operator/intent/paper/start`, but Command Center did not expose the form/button.
- AI Quant Chief existed, but the global overlay lacked a freeform question experience.
- Local credential save/load existed, but feedback was not explicit enough.
- Provider readiness existed, but backend degraded reasons were too vague.
- Replay components exist under `app/replay`, but there is no Alpaca historical-data-to-strategy replay harness exposed to the operator. The historical test control now makes that gap explicit.

## Historical Test Honesty

The historical control is not executable truth:

- It does not start PAPER.
- It does not call broker trading endpoints.
- It does not place, cancel, flatten, or liquidate.
- It does not mutate strategy, alpha, scoring, thresholds, Risk, OMS, or execution.
- It does not claim broker-confirmed P&L.
- It does not invent fees, fills, slippage, TCA, equity curves, win/loss, drawdown, or returns.
- It labels outputs as historical simulation only, not broker-confirmed, not live proof, and not future-profit proof.

Repo finding: `app/replay/*` is a deterministic local-file replay engine. It is not an Alpaca historical data backtest harness and should not be presented as one until a governed adapter and strategy replay bridge are built.

## Safe Fixes Done In This Seam

- Operator API advisory/read-only additions only.
- Operator UI wiring/feedback additions only.
- Historical test foundation with no trading mutation.
- Tests for AI ask, historical tests, UI wiring, route existence.
- Contract and README/report updates.

## Out of Scope

The following were intentionally not touched:

- `app/execution/*`
- broker adapters
- OMS internals
- strategy/alpha/scoring/threshold files
- run scripts
- runtime logs
- `state/*`
- DBs
- quarantine
- secrets
- untracked audit scripts

## Plain-English Summary

The operator UI had some real control-surface gaps: the AI button did not have a proper question flow, the Command Center did not expose the PAPER start form, credential actions were too quiet, backend degradation was vague, and historical testing had no home. This seam turns those into explicit, wired, tested operator controls while preserving the safety boundary. The historical test is deliberately honest: it gives Shan a place to request the 4-month Alpaca test, but it refuses to fake performance until a governed replay/backtest harness exists.
