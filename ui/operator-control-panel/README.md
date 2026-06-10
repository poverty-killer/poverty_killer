# Operator Control Panel Static Shell

This directory contains the Phase 3/4 static shell for the Poverty Killer
operator control panel.

Scope:

- Static UI with governed operator backend support.
- Production Run PAPER authority comes from `/operator/paper-control-state`,
  then backend readiness/status endpoints. If backend authority is unavailable,
  the UI fails closed as `BACKEND_UNAVAILABLE` or a precise degraded backend
  reason code.
- Mock data is an offline development fixture only and must not render as
  credential, baseline, endpoint, portfolio, supervisor, or Run PAPER authority
  once any backend truth is present.
- No broker mutation calls. Portfolio pages may request read-only PAPER broker
  account/positions/orders truth through governed `/operator/portfolio`.
- No runtime mutation calls except server-authorized governed PAPER
  start/stop intents through `/operator/intent/paper/*`.
- No DB/log reads from the UI. Credential forms send secrets only to the local
  backend secret store and never store raw values in the browser.
- No manual trade controls.
- No live controls active.

Open `index.html` directly in a browser to inspect the offline shell. Use the
served `/operator-ui/` route for production operation.

The mock data is contract-shaped for offline UI development only. Production
controls must be wired to a backend endpoint or removed from the operator path.

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

Operator intelligence endpoints:

- `/operator/runs`
- `/operator/runs/{run_id}`
- `/operator/runs/{run_id}/report`
- `/operator/explain/latest`
- `/operator/action-center`
- `/operator/pnl`
- `/operator/tca`
- `/operator/alerts`
- `/operator/system-map`
- `/operator/ai/status`
- `/operator/ai/ask`
- `/operator/ai/recommendations`
- `/operator/credentials/providers`
- `/operator/credentials/save`
- `/operator/credentials/validate-readonly`
- `/operator/portfolio`
- `/operator/positions`
- `/operator/orders/open`
- `/operator/positions/intelligence`
- `/operator/launch-readiness`
- `/operator/historical-tests`
- `/operator/historical-tests/run`

AI Chief Operator remains advisory only. `/operator/ai/analyze` queues a
recommendation through the governance queue; it cannot trade, start PAPER,
enable live, or call broker execution.

Global AI Chief overlay:

- The `Ask AI Chief` drawer is available from every operator page.
- It builds a small page-aware context preview from redacted operator summaries.
- The preview includes source label, page id/title, runtime summary, selected
  latest run id when available, blockers, missing evidence, and safety booleans.
- It never includes raw logs, secret values, API keys, tokens, or passwords.
- If the backend is unavailable, the overlay labels the context as mock/sample
  and does not present it as runtime truth.
- Queueing analysis uses the governed AI advisory endpoint and governance queue;
  recommendations remain `can_execute=false`.
- `/operator/ai/ask` attempts a real advisory OpenAI or Anthropic model call
  when a saved key is present. Provider errors or missing keys return an honest
  deterministic fallback instead of a fake model answer.

AI Quant Research Chief / Research OS:

- The AI identity is constrained to trading edge, execution quality, risk,
  validation evidence, provider readiness, PAPER experiment design, and Codex
  packet drafting.
- Provider Setup shows env-var readiness and masked fingerprints only; raw
  credentials are never sent to the browser.
- Research OS shows advisory hypotheses, experiments, promotion gates,
  recommendations, and a lightweight evidence graph.
- Research and AI recommendations cannot start PAPER automatically and cannot
  trade, call broker, enable live, enable real money, or change thresholds.

Operator activation:

- Provider Setup includes local credential forms for Alpaca PAPER, OpenAI,
  Anthropic, and Alpaca News.
- Saved credentials go only to `.operator_secrets/provider_credentials.json`,
  which is gitignored. GET responses show configured status and masked
  fingerprints only.
- Launch Readiness answers whether governed PAPER can run now, with explicit
  blockers for missing credentials, non-paper endpoints, active runtime,
  storage, safe stop, and portfolio read availability.
- Portfolio Home is the first screen and uses broker-confirmed PAPER data when credentials are
  available; otherwise it displays unavailable/degraded truth and does not
  invent positions.
- The governed PAPER setup flow calls only `/operator/intent/paper/start` with
  PAPER-only/live-locked/real-money-blocked confirmations. Run PAPER accepts
  lease-bound minutes/hours/days from 60 seconds through 5 days.

Reality audit / historical test control:

- Diagnostics includes a UI wiring audit so visible controls are classified as
  wired, disabled with reason, removed, or broken.
- The global AI drawer includes a freeform question box and calls
  `/operator/ai/ask`. Provider/model failures are explicitly labeled as
  deterministic fallback, not a real model answer.
- Run PAPER includes the visible governed PAPER launch form and disabled
  reason when launch readiness blocks it.
- 4-Month Test provides the Alpaca historical test control. Until a
  governed strategy replay/backtest harness exists, it returns honest unavailable
  status and never invents P&L, fees, TCA, fills, or performance metrics.
