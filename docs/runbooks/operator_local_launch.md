# Local Operator Console Launch

This runbook starts the operator API and opens the static UI. It does not start
a PAPER run by itself.

## Start

From the repository root in Windows PowerShell:

```powershell
.\scripts\open_operator_console.ps1
```

The script starts the operator API on `127.0.0.1:8765` and opens the static
operator panel from `http://127.0.0.1:8765/operator-ui/`.

The launcher enables local cockpit ownership for the backend:

- the existing `/operator/events` connection records each open cockpit;
- closing the last cockpit starts an eight-second reconnect grace period;
- after the grace period, an **idle** operator API exits through the existing
  process-only stack shutdown;
- refreshes and additional cockpit tabs cancel or defer that cleanup;
- an attached or uncertain PAPER runtime is never stopped by automatic cockpit
  cleanup;
- starting the launcher replaces an orphaned or version-stale idle backend, but
  preserves an attached runtime.

Browser `unload` callbacks are intentionally not used because they are not a
reliable lifecycle signal. The open event stream is the ownership signal.

## Verify

Open:

- `http://127.0.0.1:8765/operator/health`
- `http://127.0.0.1:8765/operator/readiness`
- `http://127.0.0.1:8765/operator/storage`

Expected:

- live is `LIVE_LOCKED`
- real-money is `BLOCKED`
- broker calls are `false`
- session store status is visible
- World Awareness cache status is visible
- `operator_ui_connection_count` reflects open cockpit event streams
- `operator_ui_idle_shutdown_enabled` is `true` for launcher-started backends

## Operating Rule

PAPER start/stop is only through governed operator intent endpoints. The UI
does not send manual orders and does not call broker APIs directly.

`Stop Backend` is an explicit process-only stack action. Automatic browser and
fresh-launch cleanup add `require_idle_supervisor=true`; the backend refuses that
automatic request if a PAPER runtime is active or uncertain. Neither path emits
orders, cancels, liquidations, closes, or any other broker mutation.
