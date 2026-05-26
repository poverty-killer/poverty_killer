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

The Start PAPER and Stop PAPER controls are visible only as operator intents.
They call the operator backend, not broker APIs. The backend must validate
PAPER-only mode, profile, watchlist, bounded duration, duplicate-run status,
and live/real-money refusal before starting or stopping a process.
