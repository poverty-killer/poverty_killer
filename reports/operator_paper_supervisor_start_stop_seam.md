# Operator PAPER Supervisor Start/Stop Seam

Date: 2026-05-26

## Scope

This seam adds a governed local PAPER supervisor for the Operator API. It lets
the operator backend accept or refuse bounded PAPER start/stop intents without
changing broker execution logic, OMS logic, strategy logic, alpha thresholds, or
live trading authority.

The supervisor starts only the existing governed PowerShell launch path:

```text
scripts/run_bounded_paper.ps1
  -Run
  -ApproveAutonomousPaper
  -PaperExplorationAlpha
  -DurationSeconds <bounded>
  -Watchlist BTC/USD,ETH/USD,SOL/USD
```

It does not call broker APIs directly.

## Safety Laws Preserved

- no live endpoint
- no real-money mode
- no live start or live toggle
- no manual buy/sell
- no force trade
- no guardrail bypass
- no direct broker command from UI or supervisor
- no UI-only broker truth
- no fake fills, fees, TCA, broker truth, or market truth
- no threshold or alpha tuning
- no execution strategy changes
- no OMS/broker behavior changes
- all operator controls are intent based
- all intent outcomes return audit IDs
- live intents return `LIVE_NOT_APPROVED`

## Start Workflow

1. UI sends `/operator/intent/paper/start`.
2. Backend validates:
   - mode is `PAPER`
   - real money is false
   - live is false
   - `approve_autonomous_paper=true`
   - profile is `PAPER_EXPLORATION_ALPHA`
   - watchlist is within the allowed PAPER supervisor set
   - duration is one of the bounded allowed durations
   - no active run exists
   - the Windows PowerShell runner is available
3. Supervisor creates a session ID and wrapper stdout/stderr paths.
4. Supervisor starts the existing bounded PAPER script.
5. Response returns session, PID, command summary, log paths, and audit ID.

The command summary contains no secrets.

## Stop Workflow

The stop endpoint is intentionally conservative. It does not call broker cancel,
flatten, liquidation, or execution APIs.

If a process is active and the local runner can issue a safe process-group
graceful stop, `/operator/intent/paper/stop` records `STOP_REQUESTED`.

Important implementation note: `main.py` handles `SIGTERM` by running a
termination handler that can flatten positions. Therefore the supervisor must
not use generic terminate/kill as the normal UI stop path. If the safe local
runner cannot issue a supported graceful stop signal, stop is refused with a
reason such as `SAFE_STOP_UNAVAILABLE_NON_WINDOWS`.

## Session Registry Model

The current registry is in-memory and tracks the current/latest local PAPER
session:

- `session_id`
- `requested_at`
- `started_at`
- `ended_at`
- `status`
- `pid`
- `profile`
- `watchlist`
- `duration_seconds`
- `command_summary`
- `stdout_path`
- `stderr_path`
- `exit_code`
- `refusal_reason`
- `last_status_check_at`
- `stop_requested_at`
- `stop_reason`

Future hosted/cloud operation should replace this with a persistent session
registry.

## Duplicate-Run Prevention

Before any start, the supervisor refreshes process state. If a session is in
`STARTING`, `RUNNING`, or `STOP_REQUESTED`, the start intent is refused with
`DUPLICATE_ACTIVE_RUN`.

## Audit Event Design

Every intent result includes:

- `intent_id`
- `allowed`
- `status`
- `reason_code`
- `audit_event_id`
- `audit_event_written`
- `session_id`
- `broker_call_occurred=false`
- `live_endpoint_touched=false`
- `real_money_touched=false`

The current audit store is in-memory. A future seam should persist operator
audit events alongside runtime audit evidence.

## Windows / Local Behavior

The default runner requires native Windows PowerShell because the existing
governed PAPER script requires native Windows. It refuses if:

- the bounded PAPER script is missing
- the Windows venv Python is missing
- the OS is not Windows
- PowerShell is unavailable

Tests use an injected fake runner and never launch a real process.

## Future Hosted / Cloud Behavior

The supervisor is designed so a later hosted runner can replace the local
PowerShell runner:

- runner is injectable
- session registry can move to a database
- log directory is configurable
- request/profile/watchlist validation stays server side
- JSON status responses are stable
- secrets are never serialized

Reserved future profile names:

- `LOCAL_PAPER`
- `CLOUD_PAPER`
- `CLOUD_SHADOW`
- `CLOUD_LIVE_LOCKED`
- `CLOUD_LIVE_APPROVED`

Only local/cloud PAPER should become operational before any live governance.

## Operator API Changes

New/updated endpoints:

- `GET /operator/status`
- `GET /operator/runtime`
- `GET /operator/latest-run`
- `GET /operator/audit-summary`
- `POST /operator/intent/paper/start`
- `POST /operator/intent/paper/stop`
- `POST /operator/intent/live/request-enable`
- `POST /operator/intent/live/start`

Live endpoints remain refusal-only.

## UI Changes

The static Operator Control Panel now:

- labels `MOCK_DATA` vs `OPERATOR_BACKEND`
- displays supervisor session state
- displays PID, duration, profile, watchlist, stdout path, stderr path
- enables Start PAPER only when backend says it is allowed
- enables Stop PAPER only when backend says it is allowed
- sends only `/operator/intent/paper/start` and `/operator/intent/paper/stop`
- keeps live locked
- keeps manual trade and force trade absent

## Limitations

- The session registry is in-memory.
- The default local runner is Windows-only.
- Stop is conservative and refuses if safe stop authority is unavailable.
- The UI does not yet stream live runtime telemetry from logs/state.
- No cloud deployment is implemented in this seam.

## Tests and Checks

Focused tests cover:

- safe PAPER start with fake runner
- duplicate active run refusal
- live/real-money/profile/watchlist/duration/approval refusals
- stop intent behavior
- runner unavailable refusal
- API status/runtime/latest-run route behavior
- live refusal
- old unsafe dashboard routes not included in new operator app

## Next Seam

Deferred Broker Fee Hydration / CFEE-FEE Activity Matching is the immediate
next seam unless this supervisor seam uncovers a blocking issue. After that,
continue hosted/cloud deployment readiness and 24/7 watchdog work.
