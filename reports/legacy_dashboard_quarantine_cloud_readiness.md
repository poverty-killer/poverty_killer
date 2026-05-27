# Legacy Dashboard Quarantine / Cloud Readiness

Date: 2026-05-27

## Scope

This cleanup isolates the old `SovereignDashboard` surface from the supported
operator architecture. The new operator path is:

- `ui/operator-control-panel/`
- `app/api/operator_readonly_api.py`
- `app/api/operator_paper_supervisor.py`
- `/operator/*` endpoints only

No broker, execution, OMS, strategy, alpha, run script, state, DB, log, or
secret behavior is changed by this cleanup.

## Scout Findings

The legacy dashboard source was `app/api/dashboard_server.py` with template
`app/api/templates/index.html`.

Unsafe legacy routes and command surfaces found:

- `POST /api/mode/{mode}`
- `POST /api/flatten`
- WebSocket command handling for `set_mode`
- WebSocket command handling for `flatten`

When a bot instance is attached, those paths can call control or liquidation
behavior such as emergency liquidation or attack-mode transitions. That is not
part of the governed operator UI architecture.

The new static operator UI does not call stale `/api/catalog`, `/api/status`,
`/api/suppliers`, or `/api/catalog/recommendations` paths. It calls
`/operator/*` endpoints and uses mock fallback when the backend is unavailable.
The observed stale `/api/*` 404s are consistent with an old browser tab, stale
cached page, or unrelated non-operator UI caller.

## Dependency Check

Active source imports of `app.api.dashboard_server` were limited to the legacy
Seam 7H readiness test. That test has been updated to assert that the supported
operator app exposes `/operator/*` and does not expose `/api/mode/{mode}` or
`/api/flatten`.

Historical reports still mention `dashboard_server.py` as prior evidence. They
are retained as history and should not be treated as the active operator path.

## Quarantined Files

The following legacy files were moved to local quarantine for review, not
deleted:

- `_repo_quarantine/legacy_dashboard/app/api/dashboard_server.py`
- `_repo_quarantine/legacy_dashboard/app/api/templates/index.html`

`_repo_quarantine/` is ignored and must not be deployed from. Inspect these
files before any permanent deletion.

## Replacement Path

Use `/operator/*` only:

- `/operator/status`
- `/operator/runtime`
- `/operator/readiness/live`
- `/operator/intent/paper/start`
- `/operator/intent/paper/stop`
- `/operator/world-awareness`

Live remains locked and refused with `LIVE_NOT_APPROVED`. Manual trading and
force trading remain unavailable.

## Rollback Note

If a future review needs the legacy dashboard, restore it from
`_repo_quarantine/legacy_dashboard/` into its original paths, then re-run the
operator API tests and inspect all command-capable routes before use. It must
not be connected to the supported operator UI without a separate governance
packet.

## Remaining Risks

Historical documents may still refer to the legacy dashboard. That is
acceptable as archived evidence, but active docs and UI should point to
`/operator/*`.
