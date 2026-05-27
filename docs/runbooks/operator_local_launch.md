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

## Operating Rule

PAPER start/stop is only through governed operator intent endpoints. The UI
does not send manual orders and does not call broker APIs directly.
