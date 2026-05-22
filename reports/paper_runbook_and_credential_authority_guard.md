# Paper Runbook + Credential Authority Guard

Date: 2026-05-21

Starting baseline: `d000b16` - Update paper test report with broker reconciliation proof

## Current PASS Baseline

The latest bounded autonomous external PAPER test is recorded as PASS in:

- `reports/bounded_autonomous_external_paper_after_rest_latency_truth_fix.md`

Baseline facts:

- 300-second autonomous PAPER run completed safely.
- Execution route: `alpaca_paper` via `alpaca_paper_rest`.
- Feed route: `coinbase_public` REST.
- REST latency truth recovered.
- Order books were processed.
- Shans/Fusion were active.
- Zero order/submission markers were observed in logs.
- No `/v2/orders` marker was observed in runtime logs.
- No broker POST marker was observed.
- No live endpoint marker was observed.
- No real-money marker was observed.
- Broker reconciliation was proven after credential authority correction.
- Alpaca PAPER account status: `ACTIVE`.
- Positions count: 7.
- Open orders count: 0.
- `mutation_occurred=false`.

Root cause of the credential incident:

- Stale inherited Codex process environment credentials overrode the valid fallback credential file.

## Credential Authority Guard

Implemented guard path:

- `validate_alpaca_paper_credential_authority()`
- `collect_alpaca_paper_read_only_preflight_truth()`
- `AlpacaPaperBrokerAdapter.from_env()`

The guard verifies:

- `APCA_API_BASE_URL` is exactly `https://paper-api.alpaca.markets`.
- `APCA_API_KEY_ID` exists.
- `APCA_API_SECRET_KEY` exists.
- key and secret lengths are nonzero.
- live endpoint `https://api.alpaca.markets` fails closed.
- process env and fallback credential file are compared when both exist.
- process env/fallback mismatch fails closed with `STALE_PROCESS_ENV_CREDENTIALS` and `CREDENTIAL_AUTHORITY_CONFLICT`.
- process env cannot silently override a conflicting fallback file.
- diagnostics include source labels, lengths, and fingerprint prefixes only.
- raw secrets are not printed.

Credential authority is supporting truth only. Broker truth remains canonical.

## Correct Credential Source Procedure

Approved fallback credential file:

- `/home/shahn/.poverty_killer_alpaca_paper_env`

Expected file keys:

```bash
APCA_API_BASE_URL=https://paper-api.alpaca.markets
APCA_API_KEY_ID=<paper key id>
APCA_API_SECRET_KEY=<paper secret key>
```

Safe update procedure:

1. Replace only the values in `/home/shahn/.poverty_killer_alpaca_paper_env`.
2. Do not add quotes unless required by shell syntax.
3. Do not leave trailing spaces.
4. Do not print the key or secret into logs.
5. Confirm the endpoint remains exactly `https://paper-api.alpaca.markets`.

To avoid stale inherited process env:

```bash
unset APCA_API_BASE_URL APCA_API_KEY_ID APCA_API_SECRET_KEY
set -a
. /home/shahn/.poverty_killer_alpaca_paper_env
set +a
```

If both process env and fallback file are present, they must match exactly. If they do not, the guard fails closed.

## Exact Preflight Steps

Before any bounded PAPER run:

1. Confirm branch and HEAD.
2. Clear stale Alpaca process env values.
3. Source `/home/shahn/.poverty_killer_alpaca_paper_env`.
4. Run credential authority guard.
5. Run read-only Alpaca PAPER broker preflight:
   - account GET
   - positions GET
   - open orders GET
   - GET count
   - POST count must be 0
   - `live_endpoint_used=false`
   - `mutation_occurred=false`
6. Stop if credential authority or read-only broker preflight fails.

Read-only preflight must pass before shadow or autonomous PAPER runtime.

## Read-Only Broker Preflight

The preflight helper performs the existing canonical read-only reconciliation path:

- `AlpacaPaperBrokerAdapter.from_env()`
- `collect_alpaca_paper_read_only_reconciliation_truth(adapter)`

It is GET-only and must return:

- account readable
- positions readable
- open orders readable
- POST count 0
- live endpoint false
- mutation false

If it fails, do not start the bot.

## Bounded Shadow Command

Shadow-read-only proof command:

```bash
timeout 60s venv/Scripts/python.exe main.py --paper --shadow-read-only --log-level INFO
```

Expected shadow truth:

- paper mode
- shadow-read-only
- execution broker `alpaca_paper`
- route `alpaca_paper_rest`
- no `/v2/orders`
- no broker POST
- no order submission
- no live endpoint
- no real-money mode

## Bounded Autonomous PAPER Command

Autonomous PAPER command requires separate explicit approval:

```bash
timeout 300s venv/Scripts/python.exe main.py --paper --log-level INFO
```

This command is PAPER broker-mutation capable. Do not run it without a separate approval packet.

Valid outcomes:

- zero orders, truthfully explained by guardrails/signals/market truth/risk/economics
- lawful Alpaca PAPER orders only if generated through the existing bot path

Invalid outcomes:

- live endpoint
- real-money mode
- accidental `internal_paper` fallback for `alpaca_paper`
- broker/local conflict
- fake market/broker truth
- unapproved threshold change
- forced symbols or forced trades

## Stop Conditions

Stop before or during runtime if any of these appear:

- credential authority conflict
- `STALE_PROCESS_ENV_CREDENTIALS`
- `CREDENTIAL_AUTHORITY_CONFLICT`
- endpoint is not `https://paper-api.alpaca.markets`
- live endpoint appears
- read-only broker preflight fails
- pre-run POST count is not 0
- physical fuse triggered
- unresolved safe-mode/latency issue
- broker/local reconciliation conflict
- secrets would be printed
- order submission outside the existing execution path
- retry storm
- unhandled exception

## Post-Run Reconciliation Requirements

After any bounded autonomous PAPER run:

1. Run read-only Alpaca PAPER reconciliation:
   - account GET
   - positions GET
   - open orders GET
2. Record:
   - endpoint
   - account status
   - positions before/after
   - open orders before/after
   - submitted/filled/open/rejected/canceled counts
   - GET count
   - POST count
   - live endpoint verdict
   - mutation verdict
3. Confirm:
   - no live endpoint
   - no real-money mode
   - no fake orders/fills/PnL
   - broker truth reconciles with local state or conflicts fail closed

## No-Secrets Rule

Never print:

- raw Alpaca key ID
- raw Alpaca secret key
- full credential file contents

Allowed diagnostics:

- present/missing
- length
- source label
- stable fingerprint prefix
- endpoint if it is paper/live/nonstandard-redacted

## Verification Summary

Implementation files:

- `app/execution/alpaca_paper_adapter.py`
- `tests/test_alpaca_paper_credential_authority_guard.py`
- `reports/paper_runbook_and_credential_authority_guard.md`

Focused test coverage proves:

- matching process env and fallback file passes
- mismatched process env and fallback file fails closed
- missing key/secret fails closed
- live endpoint fails closed
- valid paper endpoint with nonempty credentials proceeds to GET-only preflight
- no raw secrets are included in sanitized diagnostics
- POST count remains 0 in the mocked preflight path

Commands run:

```bash
python3 -m py_compile app/execution/alpaca_paper_adapter.py tests/test_alpaca_paper_credential_authority_guard.py
```

Result: passed.

```bash
/tmp/pk_pytest_venv/bin/python -m pytest tests/test_alpaca_paper_credential_authority_guard.py -q
```

Result: 6 passed.

Additional manual focused guard verification was run with temporary credential files and a stub transport.

Result: 6 checks passed.

Notes:

- No autonomous PAPER command was run.
- No broker network preflight was run in this packet.
- No broker POST was performed.
- No mutation-capable broker path was touched.
- A small optional adapter/dynamic regression slice was attempted in a temporary WSL venv but was not expanded because that venv lacks larger runtime dependencies such as `pydantic` and `numpy`; this packet's focused guard tests passed.

## Final Verdict

PASS.

The stale inherited process-env credential problem is now detectable and fail-closed before paper runtime. The runbook defines a stable launch procedure that clears stale env values, sources the approved fallback file, runs credential authority validation, runs GET-only broker preflight, and only then permits separately approved shadow or autonomous PAPER commands.
