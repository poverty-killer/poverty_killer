# Windows PowerShell launch authority for bounded Alpaca PAPER runs.
# Default mode is preflight-only. Autonomous PAPER requires -Run and
# -ApproveAutonomousPaper.

[CmdletBinding()]
param(
    [switch]$Run,
    [switch]$ApproveAutonomousPaper,
    [int]$DurationSeconds = 1200,
    [string]$CredentialFile = $env:POVERTY_KILLER_ALPACA_PAPER_ENV_PATH,
    [string]$MarketDataProviders = "alpaca_crypto_stream,alpaca_crypto_rest,coinbase_public,kraken_public",
    [string]$CryptoMarketDataProviders = "alpaca_crypto_stream,alpaca_crypto_rest,coinbase_public,kraken_public",
    [string]$Watchlist = $env:POVERTY_KILLER_RUNTIME_WATCHLIST,
    [switch]$PaperExplorationAlpha,
    [switch]$TcaExtendedReads,
    [string]$PythonPath = "venv\Scripts\python.exe",
    [string]$LogDirectory = "logs\paper_runs"
)

$ErrorActionPreference = "Stop"
$PaperEndpoint = "https://paper-api.alpaca.markets"
$LiveEndpoint = "https://api.alpaca.markets"
$StrictReadProfile = "PAPER_SMOKE_STRICT_READS"
$ExtendedReadProfile = "PAPER_TCA_EXTENDED_READS"

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

if ($DurationSeconds -lt 1 -or $DurationSeconds -gt 432000) {
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
if ($PaperExplorationAlpha) {
    $env:POVERTY_KILLER_PAPER_EXPLORATION_ALPHA = "1"
    $env:PAPER_EXPLORATION_ALPHA = "1"
}

Require-NonEmptyEnv "POVERTY_KILLER_EXECUTION_BROKER"
Require-NonEmptyEnv "POVERTY_KILLER_MARKET_DATA_PROVIDERS"
Require-NonEmptyEnv "POVERTY_KILLER_CRYPTO_MARKET_DATA_PROVIDERS"

if ($TcaExtendedReads) {
    $env:PK_BROKER_READ_PROFILE = $ExtendedReadProfile
}
if ([string]::IsNullOrWhiteSpace($env:PK_BROKER_READ_PROFILE)) {
    $env:PK_BROKER_READ_PROFILE = $StrictReadProfile
}
if ($env:PK_BROKER_READ_PROFILE -eq $StrictReadProfile) {
    $env:PK_BROKER_READ_ALLOWLIST = "account,orders,positions"
    $env:PK_BROKER_READ_DENY_ACCOUNT_ACTIVITIES = "1"
    $env:PK_FEE_HYDRATION_ALLOWED = "0"
    $env:PK_ACCOUNT_ACTIVITY_READS_ALLOWED = "0"
}
if ($env:PK_BROKER_READ_PROFILE -eq $ExtendedReadProfile) {
    $env:PK_BROKER_READ_ALLOWLIST = "account,orders,positions,account_activities,fill_activity_hydration,fee_hydration,fee_activities"
    $env:PK_BROKER_READ_DENY_ACCOUNT_ACTIVITIES = "0"
    $env:PK_FEE_HYDRATION_ALLOWED = "1"
    $env:PK_ACCOUNT_ACTIVITY_READS_ALLOWED = "1"
    $env:PK_ACCOUNT_ACTIVITY_TYPES_ALLOWLIST = "FILL,CFEE,FEE"
}
if ($env:PK_BROKER_READ_PROFILE -eq $StrictReadProfile) {
    $allowedReadFamilies = @("account", "orders", "positions")
    $configuredReadFamilies = @()
    if (-not [string]::IsNullOrWhiteSpace($env:PK_BROKER_READ_ALLOWLIST)) {
        $configuredReadFamilies = $env:PK_BROKER_READ_ALLOWLIST.Split(",") | ForEach-Object { $_.Trim().ToLowerInvariant() } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    }
    foreach ($requiredReadFamily in $allowedReadFamilies) {
        if ($configuredReadFamilies -notcontains $requiredReadFamily) {
            Fail-Closed "BROKER_READ_ALLOWLIST_MISSING_$($requiredReadFamily.ToUpperInvariant())"
        }
    }
    foreach ($configuredReadFamily in $configuredReadFamilies) {
        if ($allowedReadFamilies -notcontains $configuredReadFamily) {
            Fail-Closed "BROKER_READ_NOT_AUTHORIZED_$($configuredReadFamily.ToUpperInvariant())"
        }
    }
    if ($env:PK_ACCOUNT_ACTIVITY_READS_ALLOWED -ne "0") {
        Fail-Closed "ACCOUNT_ACTIVITY_READS_NOT_AUTHORIZED"
    }
    if ($env:PK_FEE_HYDRATION_ALLOWED -ne "0") {
        Fail-Closed "FEE_HYDRATION_NOT_AUTHORIZED"
    }
}
if ($env:PK_BROKER_READ_PROFILE -eq $ExtendedReadProfile) {
    $allowedReadFamilies = @("account", "orders", "positions", "account_activities", "fill_activity_hydration", "fee_hydration", "fee_activities")
    $configuredReadFamilies = @()
    if (-not [string]::IsNullOrWhiteSpace($env:PK_BROKER_READ_ALLOWLIST)) {
        $configuredReadFamilies = $env:PK_BROKER_READ_ALLOWLIST.Split(",") | ForEach-Object { $_.Trim().ToLowerInvariant() } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    }
    foreach ($requiredReadFamily in $allowedReadFamilies) {
        if ($configuredReadFamilies -notcontains $requiredReadFamily) {
            Fail-Closed "BROKER_READ_ALLOWLIST_MISSING_$($requiredReadFamily.ToUpperInvariant())"
        }
    }
    foreach ($configuredReadFamily in $configuredReadFamilies) {
        if ($allowedReadFamilies -notcontains $configuredReadFamily) {
            Fail-Closed "BROKER_READ_NOT_AUTHORIZED_$($configuredReadFamily.ToUpperInvariant())"
        }
    }
    if ($env:PK_ACCOUNT_ACTIVITY_READS_ALLOWED -ne "1") {
        Fail-Closed "ACCOUNT_ACTIVITY_READS_REQUIRED_FOR_TCA_EXTENDED"
    }
    if ($env:PK_FEE_HYDRATION_ALLOWED -ne "1") {
        Fail-Closed "FEE_HYDRATION_REQUIRED_FOR_TCA_EXTENDED"
    }
    if ($env:PK_ACCOUNT_ACTIVITY_TYPES_ALLOWLIST -ne "FILL,CFEE,FEE") {
        Fail-Closed "ACCOUNT_ACTIVITY_TYPES_NOT_TCA_SCOPED"
    }
}
Write-Host "Broker read profile: $($env:PK_BROKER_READ_PROFILE)"

if ($env:PK_PAPER_BASELINE_REQUIRED -eq "1") {
    Require-NonEmptyEnv "PK_PAPER_BASELINE_PATH"
    Require-NonEmptyEnv "PK_PAPER_BASELINE_SNAPSHOT_ID"
    Require-NonEmptyEnv "PK_PAPER_BASELINE_SNAPSHOT_HASH"
    Require-NonEmptyEnv "PK_PAPER_BASELINE_POLICY"
    Require-NonEmptyEnv "PK_PAPER_BASELINE_PROTECTED_SYMBOLS"
    if ($env:PK_PAPER_BASELINE_POLICY -ne "ADOPT_EXISTING_POSITIONS_PROTECTED") {
        Fail-Closed "PAPER_BASELINE_POLICY_MISMATCH"
    }
    if (-not (Test-Path -LiteralPath $env:PK_PAPER_BASELINE_PATH)) {
        Fail-Closed "PAPER_BASELINE_RUNTIME_CONTEXT_REQUIRED"
    }
    Write-Host "Protected PAPER baseline context present: $($env:PK_PAPER_BASELINE_SNAPSHOT_ID)"
}

$preflightCode = @'
import json
import os
import sys

sys.path.insert(0, os.getcwd())

from app.config import Config
from app.core.decision_frame import resolve_active_threshold_profile
from app.data.feed_provider_router import select_configured_market_data_provider
from app.execution.alpaca_paper_adapter import (
    alpaca_paper_preflight_account_pin_status,
    collect_alpaca_paper_read_only_preflight_truth,
)
import main

proof = collect_alpaca_paper_read_only_preflight_truth(timeout=20.0)
account = proof.reconciliation.broker_truth.get("account") if proof.reconciliation else {}
account_status = account.get("status") if isinstance(account, dict) else None
account_pin = alpaca_paper_preflight_account_pin_status(proof)

config = Config.from_env()
config.broker_mode = "paper"
active_threshold_profile = resolve_active_threshold_profile(config)
broker, primary_exchange, adapter, adapter_id = main.resolve_execution_broker_gateway(config)
universe = main.resolve_runtime_universe(config)
providers = main.get_configured_market_data_providers(config, "crypto")
selection = select_configured_market_data_provider(
    symbol=universe.symbols[0] if universe.symbols else None,
    asset_class="crypto",
    required_data_type="order_book",
    configured_provider_ids=providers,
)

summary = {
    "credential_authority_status": proof.credential_authority.status,
    "preflight_status": proof.status,
    "endpoint": proof.credential_authority.endpoint,
    "account_status": account_status,
    "expected_account_suffix": account_pin["expected_suffix"],
    "actual_account_suffix": account_pin["actual_suffix"],
    "account_pin_verified": account_pin["account_pin_verified"],
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
    "paper_exploration_alpha_requested": bool(os.environ.get("POVERTY_KILLER_PAPER_EXPLORATION_ALPHA") or os.environ.get("PAPER_EXPLORATION_ALPHA")),
    "active_threshold_profile": active_threshold_profile,
}

failures = []
if proof.status != "PAPER_READ_ONLY_PREFLIGHT_PASSED":
    failures.append("READ_ONLY_PREFLIGHT_FAILED")
if account_pin["status"] != "PASS":
    failures.append(account_pin["reason_code"])
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
if summary["paper_exploration_alpha_requested"] and active_threshold_profile.get("profile_name") != "PAPER_EXPLORATION_ALPHA":
    failures.append("PAPER_EXPLORATION_ALPHA_REQUESTED_BUT_PROFILE_DEFAULT")
if summary["paper_exploration_alpha_requested"] and active_threshold_profile.get("enabled") is not True:
    failures.append("PAPER_EXPLORATION_ALPHA_REQUESTED_BUT_INACTIVE")

summary["failures"] = failures
print(json.dumps(summary, indent=2, sort_keys=True))
if failures:
    sys.exit(2)
'@

Write-Host "Running Alpaca PAPER launch preflight..."
$tempPreflightPath = Join-Path ([System.IO.Path]::GetTempPath()) ("poverty_killer_preflight_{0}.py" -f [guid]::NewGuid().ToString("N"))
$preflightExitCode = 1
try {
    [System.IO.File]::WriteAllText($tempPreflightPath, $preflightCode, [System.Text.UTF8Encoding]::new($false))
    & $PythonPath $tempPreflightPath
    $preflightExitCode = $LASTEXITCODE
}
finally {
    if (Test-Path -LiteralPath $tempPreflightPath) {
        Remove-Item -LiteralPath $tempPreflightPath -Force -ErrorAction SilentlyContinue
    }
}
if ($preflightExitCode -ne 0) {
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
Write-Host "stdout: $stdoutPath"
Write-Host "stderr: $stderrPath"
$process = Start-Process `
    -FilePath $PythonPath `
    -ArgumentList @("main.py", "--paper", "--log-level", "INFO", "--duration-seconds", "$DurationSeconds") `
    -NoNewWindow `
    -PassThru `
    -RedirectStandardOutput $stdoutPath `
    -RedirectStandardError $stderrPath

if (-not $process.WaitForExit(($DurationSeconds + 30) * 1000)) {
    Write-Host "Duration elapsed; bounded PAPER process did not exit gracefully within 30 seconds; stopping process."
    $process.Kill()
    $process.WaitForExit()
}

Write-Host "Bounded PAPER process exit code: $($process.ExitCode)"
Write-Host "stdout: $stdoutPath"
Write-Host "stderr: $stderrPath"
exit $process.ExitCode
