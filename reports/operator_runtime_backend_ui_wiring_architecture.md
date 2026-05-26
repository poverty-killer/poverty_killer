# Operator Runtime Backend and UI Wiring Architecture

Date: 2026-05-26

## Scope

This seam moves the Operator Control Panel from a static mock shell toward a
real operator application without changing trading behavior. It adds a
read-only operator API skeleton, updates UI contracts, and lets the static UI
prefer read-only backend status when available while falling back to mock data.

This seam does not start or stop trading runs, call broker APIs, call market
feeds, mutate runtime state, mutate OMS state, or enable live trading.

## Scout Findings

### Existing Static UI

The current operator shell lives under `ui/operator-control-panel/` and is a
plain HTML/CSS/JavaScript application:

- `index.html`
- `styles.css`
- `app.js`
- `mock-data.js`
- `contracts.json`
- `README.md`

It already scaffolds the 11 required screens:

1. Command Center
2. P&L / Net Profit
3. Positions & Orders
4. Bot Activity Control
5. Signal & Decision Lab
6. Market Data Truth
7. Risk & Governor
8. Audit Log
9. World Awareness
10. Diagnostics
11. Live Readiness / Activation Gate

The shell is desktop-first, dark, dense, and mock-data driven. Live is visible
but locked. PAPER is represented as enabled. Manual trade and force-trade
controls are absent.

### Existing Dashboard Server

The legacy dashboard is `app/api/dashboard_server.py`. It can instantiate a
FastAPI app and WebSocket server, but it has command-capable routes:

- `POST /api/mode/{mode}`
- `POST /api/flatten`
- WebSocket commands including `set_mode` and `flatten`

When a bot instance is attached, these paths can call execution/control methods
such as emergency liquidation or attack mode. That surface is not appropriate
for the new operator panel v1.

Decision: do not reuse or expand this legacy dashboard for the governed
operator layer. Keep the new operator API separate and read-only.

### Existing Tests

`tests/test_seam7h_operator_monitoring_shadow_launch_readiness.py` validates
the legacy dashboard only by import/route-table inspection and intentionally
does not start it. That is consistent with the safety posture.

## Proposed Operator App Architecture

Target shape:

```text
Desktop shortcut / browser UI
  -> local or hosted Operator API
  -> Bot Supervisor
  -> Trading Engine Process
  -> Broker / Market Feeds
  -> State / Logs / Audit / Metrics
```

The UI is not the trading engine. It observes truth and sends operator intent
only. Server-side authority must validate every intent. The engine and broker
boundary remain the only trading authority.

Correct flow:

```text
UI intent
  -> Operator API validates authority
  -> Supervisor starts/stops governed PAPER process
  -> Engine decides using canonical MarketTruthSnapshot, DecisionFrame, NetEdge
  -> Broker boundary enforces safety
  -> UI observes status, orders, fills, TCA, and audit truth
```

Forbidden flow:

```text
UI direct buy/sell
UI flips live mode
UI calls broker
UI edits credentials
UI invents P&L, fills, fees, or TCA
UI bypasses guardrails or NetEdge
```

## Read-Only API Design

New safe module:

- `app/api/operator_readonly_api.py`

Phase 3 minimum endpoints:

- `GET /operator/status`
- `GET /operator/runtime`
- `GET /operator/profile`
- `GET /operator/universe`
- `GET /operator/readiness/live`
- `GET /operator/diagnostics`
- `GET /operator/contracts`
- `GET /operator/orders-summary`
- `GET /operator/fills-summary`
- `GET /operator/tca-summary`
- `GET /operator/audit-summary`

Properties:

- read-only safe defaults
- no broker imports
- no execution engine imports
- no OMS mutation imports
- no runtime script invocation
- no active log/state/DB reads in v1
- no secret inspection
- live readiness always returns `LIVE_LOCKED` / `LIVE_NOT_APPROVED`

Truth labels:

- `broker_confirmed`: canonical after broker acknowledgement/reconciliation
- `local_diagnostic`: useful evidence, not authority
- `estimated`: non-authoritative estimate, visibly labeled
- `unknown`: unavailable, not invented

## Future Intent API Design

Intent endpoints are represented as refused stubs only in this seam:

- `POST /operator/intent/paper/start`
- `POST /operator/intent/paper/stop`
- `POST /operator/intent/snapshot/export`
- `POST /operator/intent/live/request-enable`
- `POST /operator/intent/live/start`
- `POST /operator/intent/emergency-stop`

Current behavior:

- returns `REFUSED`
- returns a refusal reason such as `PAPER_INTENT_NOT_IMPLEMENTED` or
  `LIVE_NOT_APPROVED`
- reports `mutation_occurred=false`
- reports `broker_call_occurred=false`
- reports `runtime_mutation_occurred=false`

Future PAPER controls must:

- validate authority server-side
- create an audit event
- prevent duplicate runs
- start only governed bounded PAPER runs
- keep endpoint/mode/profile safety checks fail-closed
- never call broker directly from UI logic

Future live controls require a separate governance packet and must stay refused
until server authority, live endpoint authority, real-money authority, risk
governor approval, kill switch readiness, operator approval, and audit readiness
are proven.

## Supervisor Design

The future supervisor should be a separate authority layer, not UI JavaScript.

Responsibilities:

- process/session registry
- PID tracking
- start time and command capture
- stdout/stderr log path capture
- heartbeat tracking
- bounded duration enforcement
- stale-process detection
- graceful stop before hard kill
- duplicate-run prevention
- active profile and watchlist validation
- paper/live endpoint validation
- audit events for every operator request and outcome

The supervisor should expose status through the Operator API and should be the
only component allowed to start/stop governed PAPER runtime processes.

## Process and Session Registry

Future registry fields:

- `session_id`
- `mode`
- `profile`
- `watchlist`
- `pid`
- `started_at`
- `requested_duration_s`
- `stdout_path`
- `stderr_path`
- `heartbeat_ts`
- `shutdown_reason`
- `last_exit_code`
- `duplicate_run_blocked`
- `operator_request_id`
- `authority_result`

No registry field should contain secrets.

## Local Desktop Launcher

Phase 1 launcher should only open the UI or start the read-only backend. It
must not start trading automatically.

Acceptable future local entry points:

- open static UI in browser
- start read-only Operator API
- open browser to local Operator API UI host

Unacceptable:

- double-click starts live trading
- double-click starts broker mutation without preflight and approval
- launcher prints credentials
- launcher edits mode/config files

## 24/7 Operating Model

The long-run path should become:

1. Operator opens UI.
2. Operator sees current mode, profile, endpoint, universe, safety, OMS, fills,
   TCA, and readiness.
3. Operator requests a governed PAPER run through an intent.
4. Server validates authority.
5. Supervisor starts a bounded or supervised PAPER runtime.
6. UI observes structured status and audit events.
7. Supervisor handles graceful shutdown and accounting.

For 24/7 operation, the supervisor must eventually support process restart
policy, alerting, lock files/session locks, and stale-process recovery without
duplicating trading engines.

## Hosted and Cloud Transition

Avoid:

- hardcoded `C:\Users\shahn\...` paths
- UI reading local files forever
- secrets in repo or config files
- source-code-only manual operation
- unstructured logs as the only status source

Design toward:

- environment variables
- configurable data/log/state directories
- secrets manager or injected environment variables
- hosted Operator API base URL
- structured JSON status
- persistent audit/event store
- role/permission model
- health/readiness endpoints
- cloud PAPER profile
- live locked by default

Future profiles:

- `LOCAL_DEV`
- `LOCAL_PAPER`
- `CLOUD_PAPER`
- `CLOUD_SHADOW`
- `CLOUD_LIVE_LOCKED`
- `CLOUD_LIVE_APPROVED`

Only local/cloud PAPER should become operational before any live governance.

## Environment and Secrets Strategy

The UI must never display secret values. The operator API may show only:

- credentials present
- credentials missing
- credential authority refused
- credential authority approved

Secret sources should be environment variables or a secrets manager. Repo files
must not store broker secrets.

## Storage, Logs, and Audit Strategy

Operator backend v1 does not read active logs/state/DBs. Future backend phases
should read structured summaries or event stores, not scrape arbitrary raw logs
as primary truth.

Recommended future stores:

- runtime session registry
- structured audit log
- OMS summary store
- broker fill ledger
- TCA summary store
- readiness audit store

Broker truth remains canonical after broker acknowledgement. MarketTruthSnapshot
remains canonical for executable market truth. Conflicts fail closed.

## Live-Locked Behavior

`/operator/readiness/live` must remain read-only in v1 and return:

- `live_status=LIVE_LOCKED`
- `refusal_reason=LIVE_NOT_APPROVED`

The UI may show live readiness and missing prerequisites, but no active live
start control is allowed.

## Safety Gates

Hard gates that cannot be bypassed by UI:

- no live endpoint without approval
- no real-money without approval
- no direct broker calls from UI
- no manual trades
- no force trades
- no guardrail bypass
- no NetEdge bypass
- no broker truth invention
- no market truth invention
- no fill/fee/TCA invention
- no sell without broker-position-backed authority

## Implementation Phases

### Phase 1: Blueprint

Done in `reports/ui_operator_control_panel_blueprint.md`.

### Phase 2: Contracts

Done/updated in `ui/operator-control-panel/contracts.json`.

### Phase 3: Read-Only Backend Skeleton

Done in `app/api/operator_readonly_api.py`.

### Phase 4: UI Read-Only Backend Fallback

Done in `ui/operator-control-panel/app.js`. The UI attempts read-only backend
fetches and falls back to mock data when unavailable.

### Phase 5: Governed PAPER Supervisor

Future seam. Implement session registry, duplicate-run prevention, bounded
PAPER start/stop intents, audit events, and no live activation.

### Phase 6: Runtime Telemetry Reader

Future seam. Read structured runtime summaries and fill/TCA/OMS truth without
mutating active state.

### Phase 7: Hosted Deployment Readiness

Future seam. Add cloud profile, service wrapper, deployment docs, health checks,
and secrets-manager integration.

### Phase 8: Future Live Readiness

Future only after separate approval. Live stays locked until server-side
authority, real-money authority, risk governor approval, operator approval, and
audit readiness are proven.

## Files Likely Touched in Future Seams

- `app/api/operator_readonly_api.py`
- `app/api/operator_supervisor.py` (future)
- `app/api/operator_runtime_reader.py` (future)
- `ui/operator-control-panel/app.js`
- `ui/operator-control-panel/contracts.json`
- `scripts/open_operator_panel.ps1` (future, UI/read-only backend only)
- tests under `tests/test_operator_*`
- documentation under `reports/` and `ui/operator-control-panel/README.md`

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Legacy dashboard command routes are reused accidentally | New operator API is separate and read-only |
| UI becomes a second trading engine | UI sends only future intents; backend authority decides |
| Live controls appear active | Live readiness is read-only and returns `LIVE_NOT_APPROVED` |
| Broker truth is invented | API labels unknown and local diagnostic values explicitly |
| Duplicate PAPER runs | Future supervisor owns session registry and duplicate-run lock |
| Local-to-cloud rework | Contracts use environment/config-ready endpoint shapes |
| Active PAPER run disruption | This seam does not touch runtime scripts, state, logs, DBs, broker, OMS, or engine code |

## Acceptance Criteria

This seam is acceptable if:

- the new backend endpoints are read-only
- disabled intent endpoints refuse without mutation
- live readiness is locked/refused
- static UI still works from mock data
- static UI can read backend status when available
- UI shows `MOCK_DATA` or `READ_ONLY_BACKEND`
- no broker/execution/OMS/alpha/strategy behavior changes
- no logs/state/DB/secrets/quarantine changes
- tests and static checks pass
