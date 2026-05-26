# Operator Control Panel Static Shell

This directory contains the Phase 3/4 static shell for the Poverty Killer
operator control panel.

Scope:

- Static UI with read-only backend fallback support.
- If `/operator/*` endpoints are unavailable, it uses mock data.
- If `/operator/*` endpoints are available, it reads status/readiness/contracts
  only and labels the source as `READ_ONLY_BACKEND`.
- No broker calls.
- No runtime mutation calls.
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
