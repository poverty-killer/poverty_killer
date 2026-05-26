# Operator Control Panel Static Shell

This directory contains the Phase 3 static shell for the Poverty Killer operator
control panel.

Scope:

- Static mock UI only.
- No backend integration.
- No broker calls.
- No runtime calls.
- No state, DB, log, or secret reads.
- No manual trade controls.
- No live controls active.

Open `index.html` directly in a browser to inspect the shell.

The mock data is contract-shaped for the future read-only endpoints listed in
`contracts.json`. Future controls are represented as disabled server-authorized
intent concepts only.
