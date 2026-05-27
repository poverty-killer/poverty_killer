# Hosted / Cloud Operator Readiness + Persistent Runtime State

Date: 2026-05-27

## Scope

This seam adds the operator foundation needed for local app mode and future
hosted/cloud PAPER operation. It does not deploy cloud infrastructure and does
not change broker, execution, OMS, alpha, strategy, DecisionFrame scoring, or
run-script behavior.

Live remains locked with `LIVE_NOT_APPROVED`.

## Current Architecture

Supported operator path:

- `ui/operator-control-panel/`
- `app/api/operator_readonly_api.py`
- `app/api/operator_paper_supervisor.py`
- `/operator/*` endpoints

The legacy command-capable dashboard has been removed from the active path.

## Implemented Foundation

### Runtime Config

`app/api/operator_runtime_config.py` defines a local/cloud-safe operator config
surface:

- `PK_RUNTIME_PROFILE`
- `PK_DATA_DIR`
- `PK_LOG_DIR`
- `PK_OPERATOR_STATE_DIR`
- `PK_OPERATOR_SESSION_STORE_PATH`
- `PK_WORLD_AWARENESS_CACHE_PATH`
- `PK_HOSTED_MODE`
- `PK_ALLOWED_WATCHLIST`
- `PK_ALLOWED_DURATIONS`
- `PK_LIVE_ENABLED`
- `PK_REAL_MONEY_ENABLED`

Secret values are never returned by diagnostics. Only booleans such as
`alpaca_credentials_present` are exposed.

### Persistent Supervisor State

`app/api/operator_session_store.py` adds an append-only JSONL session store.
It records session metadata, wrapper log paths, child bounded PAPER log paths,
exit status, refusal reasons, and audit ids. It stores metadata only, not log
contents and not secrets.

The supervisor writes session start/update/end/refusal records and reloads the
latest session on API startup. If a prior active session is found after API
restart without a process handle, the state is reported as
`PROCESS_STATE_UNKNOWN_AFTER_RESTART` and duplicate start is refused.

### Persistent World Awareness Cache

`app/world_awareness/persistent_cache.py` mirrors advisory events to JSONL when
configured. Dedupe survives API restart. Events remain advisory-only and cannot
trade or affect DecisionFrame scoring.

### Operator API Health

Added read-only endpoints:

- `GET /operator/health`
- `GET /operator/readiness`
- `GET /operator/storage`

These expose config, store, cache, local/cloud readiness, and locked live
status. They do not call broker APIs.

### UI Visibility

The static operator shell now reads the new endpoints and shows:

- runtime profile
- hosted mode
- health status
- session store status
- World Awareness cache status
- wrapper log paths
- child bounded PAPER log paths

## Target Local App Model

Desktop shortcut or launcher:

1. Start operator API on `127.0.0.1`.
2. Open `ui/operator-control-panel/index.html`.
3. Operator sees status, readiness, session history, World Awareness cache, and
   live refusal.
4. PAPER start/stop remains governed through `/operator/intent/paper/*`.

The launcher must never start trading automatically.

## Target Hosted / Cloud PAPER Model

Hosted node:

- runs operator API under a process supervisor
- injects secrets through environment or a secrets manager
- mounts data/log/state volumes
- exposes `/operator/health` to local/VPN/reverse-proxy health checks
- keeps live disabled by default
- runs PAPER only until a separate live governance packet exists

Suggested profiles:

- `LOCAL_DEV`
- `LOCAL_PAPER`
- `CLOUD_PAPER`
- `CLOUD_SHADOW`
- `CLOUD_LIVE_LOCKED`
- `CLOUD_LIVE_APPROVED` reserved, not operational

## Storage Layout

Runtime files are local/ignored:

- `state/operator/sessions.jsonl`
- `state/world_awareness/operator_events.jsonl`
- `logs/operator_runs/`
- `logs/paper_runs/`
- `archives/runs/`

Do not stage generated runtime state, logs, DBs, or archives.

## Secrets Boundary

Examples and diagnostics use placeholders only. Runtime code may inspect whether
required variables are present, but must not serialize values:

- `APCA_API_KEY_ID`
- `APCA_API_SECRET_KEY`
- future provider keys

## 24/7 Watchdog Design

This seam provides the status surfaces a watchdog needs:

- `/operator/health`
- `/operator/readiness`
- `/operator/storage`
- `/operator/runtime`
- `/operator/world-awareness/runtime`

Future watchdog should alert on:

- API unavailable
- stale active session
- session store degraded
- World Awareness cache degraded
- runtime process exited unexpectedly
- live flag attempted but refused

It must not liquidate, trade, or flip live mode.

## Rollback

The new stores are metadata-only JSONL files. Rollback code by commit, then
preserve or archive `state/operator/` and `state/world_awareness/` for audit.

## Limitations

- Store is JSONL, not a database. It is DB-replaceable later.
- Process recovery after API restart is intentionally conservative.
- Cloud deployment is documented but not performed.
- Live remains locked and unavailable.
