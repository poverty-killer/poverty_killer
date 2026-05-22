# Windows PowerShell launch authority for bounded Alpaca PAPER runs.
# Default mode is preflight-only. Autonomous PAPER requires -Run and
# -ApproveAutonomousPaper.

[CmdletBinding()]
param(
    [switch]$Run,
    [switch]$ApproveAutonomousPaper,
    [int]$DurationSeconds = 1200,
    [string]$CredentialFile = $env:POVERTY_KILLER_ALPACA_PAPER_ENV_PATH,
    [string]$MarketDataProviders = "coinbase_public,kraken_public",
    [string]$CryptoMarketDataProviders = "coinbase_public,kraken_public",
    [string]$Watchlist = $env:POVERTY_KILLER_RUNTIME_WATCHLIST,
    [string]$PythonPath = "venv\Scripts\python.exe",
    [string]$LogDirectory = "logs\paper_runs"
)

$ErrorActionPreference = "Stop"
$PaperEndpoint = "https://paper-api.alpaca.markets"
$LiveEndpoint = "https://api.alpaca.markets"

function Fail-Closed {
    param([string]$Reason)
    Write-Error "FAILED_CLOSED: $Reason"
    exit 1
}

function Import-AlpacaCredentialFile {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return
    }
    if (-not (Test-Path -LiteralPath $Path)) {
        Fail-Closed "CREDENTIAL_FILE_NOT_FOUND"
    }

    $allowed = @("APCA_API_BASE_URL", "APCA_API_KEY_ID", "APCA_API_SECRET_KEY")
    foreach ($rawLine in Get-Content -LiteralPath $Path) {
        $line = $rawLine.Trim()
        if ([string]::IsNullOrWhiteSpace($line) -or $line.StartsWith("#") -or -not $line.Contains("=")) {
            continue
        }
        $parts = $line.Split("=", 2)
        $key = $parts[0].Trim()
        if ($key.StartsWith("export ")) {
            $key = $key.Substring(7).Trim()
        }
        if ($allowed -notcontains $key) {
            continue
        }
        $value = $parts[1].Trim().Trim("'").Trim('"')
        [Environment]::SetEnvironmentVariable($key, $value, "Process")
    }
    [Environment]::SetEnvironmentVariable("POVERTY_KILLER_ALPACA_PAPER_ENV_PATH", $Path, "Process")
}

function Require-NonEmptyEnv {
    param([string]$Name)
    $value = [Environment]::GetEnvironmentVariable($Name, "Process")
    if ([string]::IsNullOrWhiteSpace($value)) {
        Fail-Closed "$Name missing"
    }
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    Fail-Closed "WINDOWS_POWERSHELL_REQUIRED"
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptRoot
Set-Location $repoRoot

if (-not (Test-Path -LiteralPath $PythonPath)) {
    Fail-Closed "WINDOWS_VENV_PYTHON_NOT_FOUND"
}

if ($DurationSeconds -lt 1 -or $DurationSeconds -gt 86400) {
    Fail-Closed "INVALID_DURATION_SECONDS"
}

if (-not [string]::IsNullOrWhiteSpace($CredentialFile)) {
    Import-AlpacaCredentialFile -Path $CredentialFile
}

if ([string]::IsNullOrWhiteSpace($env:APCA_API_BASE_URL)) {
    $env:APCA_API_BASE_URL = $PaperEndpoint
}

Require-NonEmptyEnv "APCA_API_BASE_URL"
Require-NonEmptyEnv "APCA_API_KEY_ID"
Require-NonEmptyEnv "APCA_API_SECRET_KEY"

if ($env:APCA_API_BASE_URL.TrimEnd("/") -eq $LiveEndpoint) {
    Fail-Closed "LIVE_ENDPOINT_BLOCKED"
}
if ($env:APCA_API_BASE_URL.TrimEnd("/") -ne $PaperEndpoint) {
    Fail-Closed "ALPACA_PAPER_ENDPOINT_REQUIRED"
}

$env:POVERTY_KILLER_EXECUTION_BROKER = "alpaca_paper"
$env:POVERTY_KILLER_MARKET_DATA_PROVIDERS = $MarketDataProviders
$env:POVERTY_KILLER_CRYPTO_MARKET_DATA_PROVIDERS = $CryptoMarketDataProviders
if (-not [string]::IsNullOrWhiteSpace($Watchlist)) {
    $env:POVERTY_KILLER_RUNTIME_WATCHLIST = $Watchlist
}

Require-NonEmptyEnv "POVERTY_KILLER_EXECUTION_BROKER"
Require-NonEmptyEnv "POVERTY_KILLER_MARKET_DATA_PROVIDERS"
Require-NonEmptyEnv "POVERTY_KILLER_CRYPTO_MARKET_DATA_PROVIDERS"

$preflightCode = @'
import json
import sys

from app.config import Config
from app.data.feed_provider_router import select_configured_market_data_provider
from app.execution.alpaca_paper_adapter import collect_alpaca_paper_read_only_preflight_truth
import main

proof = collect_alpaca_paper_read_only_preflight_truth(timeout=20.0)
account = proof.reconciliation.broker_truth.get("account") if proof.reconciliation else {}
account_status = account.get("status") if isinstance(account, dict) else None

config = Config.from_env()
config.broker_mode = "paper"
broker, primary_exchange, adapter, adapter_id = main.resolve_execution_broker_gateway(config)
universe = main.resolve_runtime_universe(config)
providers = main.get_configured_market_data_providers(config, "crypto")
selection = select_configured_market_data_provider(
    symbol=universe.symbols[0] if universe.symbols else "",
    asset_class="crypto",
    required_data_type="order_book",
    configured_provider_ids=providers,
)

summary = {
    "credential_authority_status": proof.credential_authority.status,
    "preflight_status": proof.status,
    "endpoint": proof.credential_authority.endpoint,
    "account_status": account_status,
    "positions_count": proof.reconciliation.positions_count if proof.reconciliation else None,
    "open_orders_count": proof.reconciliation.open_orders_count if proof.reconciliation else None,
    "GET_count": proof.reconciliation.request_counts.get("GET", 0) if proof.reconciliation else 0,
    "POST_count": proof.reconciliation.request_counts.get("POST", 0) if proof.reconciliation else 0,
    "live_endpoint_used": proof.reconciliation.live_endpoint_used if proof.reconciliation else proof.credential_authority.live_endpoint_used,
    "mutation_occurred": proof.reconciliation.mutation_occurred if proof.reconciliation else False,
    "execution_broker": broker,
    "primary_exchange": primary_exchange,
    "adapter_id": adapter_id,
    "internal_paper_selected": broker == "internal_paper",
    "runtime_universe_reason": universe.reason,
    "runtime_universe_source": universe.source,
    "candidate_count": len(universe.symbols),
    "configured_crypto_providers": list(providers),
    "provider_status": selection.status,
    "provider_reason": selection.reason,
    "selected_provider_id": selection.selected_provider.provider_id if selection.selected_provider else None,
    "fallback_path": list(selection.fallback_path),
}

failures = []
if proof.status != "PAPER_READ_ONLY_PREFLIGHT_PASSED":
    failures.append("READ_ONLY_PREFLIGHT_FAILED")
if summary["POST_count"] != 0:
    failures.append("POST_COUNT_NONZERO")
if summary["live_endpoint_used"]:
    failures.append("LIVE_ENDPOINT_USED")
if summary["mutation_occurred"]:
    failures.append("MUTATION_OCCURRED")
if broker != "alpaca_paper":
    failures.append("EXECUTION_BROKER_NOT_ALPACA_PAPER")
if adapter_id != "alpaca_paper_rest":
    failures.append("ALPACA_PAPER_ADAPTER_NOT_SELECTED")
if broker == "internal_paper":
    failures.append("INTERNAL_PAPER_SELECTED")
if universe.reason != "UNIVERSE_READY":
    failures.append("MISSING_UNIVERSE_TRUTH")
if not providers:
    failures.append("MISSING_MARKET_DATA_PROVIDER_CONFIG")
if selection.status != "SELECTED":
    failures.append(selection.reason or "MARKET_DATA_PROVIDER_NOT_SELECTED")

summary["failures"] = failures
print(json.dumps(summary, indent=2, sort_keys=True))
if failures:
    sys.exit(2)
'@

Write-Host "Running Alpaca PAPER launch preflight..."
& $PythonPath -c $preflightCode
if ($LASTEXITCODE -ne 0) {
    Fail-Closed "PAPER_PREFLIGHT_FAILED"
}

if (-not $Run) {
    Write-Host "Preflight passed. No autonomous PAPER run requested."
    exit 0
}

if (-not $ApproveAutonomousPaper) {
    Fail-Closed "AUTONOMOUS_PAPER_APPROVAL_REQUIRED"
}

New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$stdoutPath = Join-Path $LogDirectory "bounded_paper_$stamp.out.log"
$stderrPath = Join-Path $LogDirectory "bounded_paper_$stamp.err.log"

Write-Host "Starting bounded Alpaca PAPER run for $DurationSeconds seconds..."
$process = Start-Process `
    -FilePath $PythonPath `
    -ArgumentList @("main.py", "--paper", "--log-level", "INFO") `
    -NoNewWindow `
    -PassThru `
    -RedirectStandardOutput $stdoutPath `
    -RedirectStandardError $stderrPath

if (-not $process.WaitForExit($DurationSeconds * 1000)) {
    Write-Host "Duration elapsed; stopping bounded PAPER process."
    $process.Kill()
    $process.WaitForExit()
}

Write-Host "Bounded PAPER process exit code: $($process.ExitCode)"
Write-Host "stdout: $stdoutPath"
Write-Host "stderr: $stderrPath"
exit $process.ExitCode
