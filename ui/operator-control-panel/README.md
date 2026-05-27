# Operator Control Panel Static Shell

This directory contains the Phase 3/4 static shell for the Poverty Killer
operator control panel.

Scope:

- Static UI with governed operator backend fallback support.
- If `/operator/*` endpoints are unavailable, it uses mock data.
- If `/operator/*` endpoints are available, it reads status/readiness/contracts
  and supervisor state and labels the source as `OPERATOR_BACKEND`.
- No broker calls.
- No runtime mutation calls except future server-authorized bounded PAPER
  start/stop intents through `/operator/intent/paper/*`.
- No state, DB, log, or secret reads.
- No manual trade controls.
- No live controls active.

Open `index.html` directly in a browser to inspect the shell.

The mock data is contract-shaped for the future read-only endpoints listed in
`contracts.json`. Future controls are represented as disabled server-authorized
intent concepts only.

Backend base URL:

- Same-origin `/operator/*` is used by default.
- Set `window.PK_OPERATOR_API_BASE` before `app.js` if a hosted/local operator
API lives on another origin during development.
- Or open `index.html?apiBase=http%3A%2F%2F127.0.0.1%3A8765` for a local
  operator API launched from a file URL.

The Start PAPER and Stop PAPER controls are visible only as operator intents.
They call the operator backend, not broker APIs. The backend must validate
PAPER-only mode, profile, watchlist, bounded duration, duplicate-run status,
and live/real-money refusal before starting or stopping a process.

Local app-style launch:

- Run `scripts/open_operator_console.ps1` from Windows PowerShell.
- The launcher starts only the operator API and opens this UI.
- The API serves this static UI at `/operator-ui/` so `/operator/*` calls stay
  same-origin.
- It does not start PAPER automatically.
- Session metadata is stored under `state/operator/` by default.
- World Awareness advisory cache metadata is stored under `state/world_awareness/`
  by default.
- Runtime logs remain under `logs/operator_runs/` and `logs/paper_runs/`.

New readiness endpoints:

- `/operator/health`
- `/operator/readiness`
- `/operator/storage`

These endpoints report storage/cache/config health, live refusal, and readiness
without exposing secrets or calling broker APIs.
