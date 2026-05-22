# Windows PowerShell Paper Launch Authority

Date: 2026-05-22

Starting HEAD: `6376100` - Record bounded 20-minute autonomous paper run

## Objective

Create a stable Windows PowerShell launch authority for bounded Alpaca PAPER runs so actual runtime launches no longer depend on WSL-to-Windows environment inheritance.

Implemented launcher:

- `scripts/run_bounded_paper.ps1`

No autonomous PAPER run was executed in this packet.

## Why WSL Is Not Runtime Authority

WSL/Codex remains useful for:

- code edits
- reports
- static checks
- Git
- scoped Python checks that do not depend on the Windows venv

It is not reliable as the runtime authority for the Windows venv because the project runtime uses:

```text
venv\Scripts\python.exe
```

Prior launch attempts from WSL showed two unsafe launch-authority failures:

- WSL exported runtime env values did not reliably reach the Windows Python process.
- Direct `cmd.exe` / `powershell.exe` launch attempts from WSL can fail with `UtilBindVsockAnyPort:309: socket failed 1`.

That caused runtime startup to select `internal_paper` and miss market-data provider config even when the WSL shell had the correct values.

## Why PowerShell Is Runtime Authority

Native Windows PowerShell is the correct launch authority because it runs in the same operating-system environment as `venv\Scripts\python.exe`.

The launcher sets all required process env vars in that same PowerShell process before invoking Python. That removes the WSL-to-Windows inheritance boundary.

## Required Environment Variables

The launcher validates or sets:

- `APCA_API_BASE_URL=https://paper-api.alpaca.markets`
- `APCA_API_KEY_ID`
- `APCA_API_SECRET_KEY`
- `POVERTY_KILLER_EXECUTION_BROKER=alpaca_paper`
- `POVERTY_KILLER_MARKET_DATA_PROVIDERS=coinbase_public,kraken_public`
- `POVERTY_KILLER_CRYPTO_MARKET_DATA_PROVIDERS=coinbase_public,kraken_public`
- `POVERTY_KILLER_RUNTIME_WATCHLIST` only when explicitly supplied/configured

The launcher never permits:

- `https://api.alpaca.markets`
- empty Alpaca key
- empty Alpaca secret
- missing provider config
- accidental `internal_paper` selection

## Credential Source

The launcher can use either:

1. current Windows PowerShell process env, or
2. an explicit credential file passed through `-CredentialFile`

When a credential file is used, the launcher imports only:

- `APCA_API_BASE_URL`
- `APCA_API_KEY_ID`
- `APCA_API_SECRET_KEY`

It also sets:

- `POVERTY_KILLER_ALPACA_PAPER_ENV_PATH`

so the Python credential authority guard compares the same source and can detect conflicts.

No raw secrets are printed.

## Preflight Steps

Default command:

```powershell
.\scripts\run_bounded_paper.ps1 -Watchlist "BTC/USD,ETH/USD,SOL/USD"
```

Default mode is preflight-only.

Preflight performs:

1. Windows-only launch check.
2. Windows venv path check.
3. Alpaca PAPER endpoint check.
4. Alpaca key/secret presence check.
5. Runtime env setup in the same PowerShell process:
   - execution broker
   - market-data providers
   - crypto providers
   - optional explicit watchlist
6. Python credential authority guard.
7. GET-only Alpaca PAPER preflight:
   - account GET
   - positions GET
   - open orders GET
   - GET count
   - POST count
   - `live_endpoint_used`
   - `mutation_occurred`
8. Runtime resolver proof:
   - execution broker `alpaca_paper`
   - adapter `alpaca_paper_rest`
   - `internal_paper` not selected
   - runtime universe ready
   - market-data provider selected

If any proof fails, the launcher exits fail-closed before `main.py`.

## Bounded Run Command

Autonomous PAPER is disabled unless both flags are present:

```powershell
.\scripts\run_bounded_paper.ps1 -Run -ApproveAutonomousPaper -DurationSeconds 1200 -Watchlist "BTC/USD,ETH/USD,SOL/USD"
```

The launcher runs:

```powershell
venv\Scripts\python.exe main.py --paper --log-level INFO
```

under a bounded process timeout controlled by `-DurationSeconds`.

## Stop Conditions

Stop before `main.py` if:

- Windows PowerShell is not the runtime shell
- Windows venv Python is missing
- Alpaca endpoint is not `https://paper-api.alpaca.markets`
- live endpoint appears
- Alpaca key or secret is missing
- credential authority guard fails
- account/positions/open-orders GET preflight fails
- POST count is nonzero during preflight
- `mutation_occurred=true`
- execution broker is not `alpaca_paper`
- adapter is not `alpaca_paper_rest`
- `internal_paper` is selected
- runtime universe is missing
- market-data provider config is missing
- market-data provider selection fails
- autonomous mode is requested without `-ApproveAutonomousPaper`

Stop/fail after runtime if logs or reconciliation show:

- live endpoint
- real-money mode
- unexpected cancel/replace/liquidation
- unauthorized broker mutation
- broker/local conflict
- fake broker/feed truth
- unhandled exception

## Post-Run Reconciliation

After any bounded run:

1. Run GET-only Alpaca PAPER reconciliation.
2. Record:
   - endpoint
   - account status
   - positions before/after
   - open orders before/after
   - submitted/filled/open/rejected/canceled counts
   - GET count
   - POST count
   - `live_endpoint_used`
   - `mutation_occurred`
3. Inspect runtime logs for:
   - `/v2/orders`
   - order submission markers
   - live endpoint markers
   - real-money markers
   - cancel/replace/liquidation markers
4. Broker truth remains canonical.

## Verification

Files changed:

- `scripts/run_bounded_paper.ps1`
- `tests/test_windows_powershell_paper_launch_authority.py`
- `reports/paper_runbook_and_credential_authority_guard.md`
- `reports/windows_powershell_paper_launch_authority.md`

Verification performed:

- PowerShell launcher added in preflight-only default mode.
- Focused static tests added for launcher safety requirements.
- `python3 -m py_compile tests/test_windows_powershell_paper_launch_authority.py` passed.
- `/tmp/pk_pytest_venv/bin/python -m pytest tests/test_windows_powershell_paper_launch_authority.py -q` passed: 5 passed.
- `git diff --check` passed for intended files.
- `pwsh` syntax parse could not be run from this WSL shell because `pwsh` is not installed.
- No autonomous PAPER run was executed.
- No broker POST was executed.
- No production trading behavior changed.

Native Windows PowerShell preflight was not executed from this WSL shell because this packet exists specifically to stop using WSL as the Windows venv launch authority. The next operator step is to run preflight-only from native Windows PowerShell:

```powershell
cd C:\Users\shahn\OneDrive\Desktop\poverty_killer
.\scripts\run_bounded_paper.ps1 -Watchlist "BTC/USD,ETH/USD,SOL/USD"
```

## Verdict

PASS for implementation and static verification of the Windows PowerShell launch authority.

The actual runtime authority must now be native Windows PowerShell. WSL should no longer be used to launch bounded autonomous PAPER runs against the Windows venv.
