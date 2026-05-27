# POVERTY_KILLER Hosted / Cloud PAPER Readiness

## Baseline

Cloud operation is PAPER-only until a separate live governance packet approves
otherwise.

Required services:

- operator API process
- governed PAPER supervisor
- persistent `state/operator/`
- persistent `state/world_awareness/`
- persistent `logs/`
- health check polling `/operator/health`

## Secrets

Use environment variables or a secrets manager. Do not commit secrets.

Required for PAPER operation:

- `APCA_API_KEY_ID`
- `APCA_API_SECRET_KEY`

Live credentials must not be installed until future live approval.

## Health Checks

Use:

- `/operator/health`
- `/operator/readiness`
- `/operator/storage`

Alert on degraded storage/cache, stale process state, or unexpected process
exit. Do not auto-liquidate from watchdog logic.

## Volumes

Persist:

- `state/operator/`
- `state/world_awareness/`
- `logs/`
- `archives/runs/`

Do not deploy from `_repo_quarantine/`.

## Network

Prefer localhost, VPN, or private reverse proxy. Do not expose the operator API
publicly without auth, TLS, and separate governance.

## Live

Live remains `LIVE_LOCKED` and `LIVE_NOT_APPROVED`.
