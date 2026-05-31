param(
    [int]$Port = 8765,
    [string]$HostAddress = "127.0.0.1",
    [bool]$OpenBrowser = $true
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $RepoRoot "venv\Scripts\python.exe"
$UiPath = Join-Path $RepoRoot "ui\operator-control-panel\index.html"
$BaseUrl = "http://$HostAddress`:$Port"
$LogBase = $env:LOCALAPPDATA
if ([string]::IsNullOrWhiteSpace($LogBase)) {
    $LogBase = $env:TEMP
}
if ([string]::IsNullOrWhiteSpace($LogBase)) {
    $LogBase = $RepoRoot
}
$LogRoot = Join-Path $LogBase "PovertyKiller\operator-launcher"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LaunchLog = Join-Path $LogRoot "launcher.log"
$StdoutLog = Join-Path $LogRoot "operator_backend_$Stamp.stdout.log"
$StderrLog = Join-Path $LogRoot "operator_backend_$Stamp.stderr.log"
$CmdLauncher = Join-Path $LogRoot "start_operator_backend_$Stamp.cmd"

New-Item -Path $LogRoot -ItemType Directory -Force | Out-Null

function Write-LaunchLog {
    param([string]$Message)
    Add-Content -Path $LaunchLog -Value "$((Get-Date).ToString("o")) $Message"
}

function Show-LauncherFailure {
    param([string]$Message)
    Write-LaunchLog "ERROR $Message"
    try {
        $shell = New-Object -ComObject WScript.Shell
        $body = "POVERTY_KILLER Operator backend did not start.`n`n$Message`n`nLogs:`n$LogRoot"
        $shell.Popup($body, 15, "POVERTY_KILLER Operator", 16) | Out-Null
    } catch {
        # Hidden launcher fallback: failure is still recorded in launcher.log.
    }
}

if (-not (Test-Path $UiPath)) {
    Show-LauncherFailure "Operator UI not found at $UiPath"
    exit 1
}
if (-not (Test-Path $Python)) {
    Show-LauncherFailure "Python venv not found at $Python"
    exit 1
}

function Test-OperatorApi {
    try {
        $response = Invoke-WebRequest -Uri "$BaseUrl/operator/health" -UseBasicParsing -TimeoutSec 2
        if ([int]$response.StatusCode -ne 200) {
            return $false
        }
        $payload = $response.Content | ConvertFrom-Json
        if ($payload.live_status -ne "LIVE_LOCKED") {
            return $false
        }
        if ($payload.real_money_status -ne "BLOCKED") {
            return $false
        }
        $diagnosticsResponse = Invoke-WebRequest -Uri "$BaseUrl/operator/credentials/diagnostics" -UseBasicParsing -TimeoutSec 2
        if ([int]$diagnosticsResponse.StatusCode -ne 200) {
            return $false
        }
        $diagnostics = $diagnosticsResponse.Content | ConvertFrom-Json
        $expectedRoot = [System.IO.Path]::GetFullPath($RepoRoot).TrimEnd('\')
        $actualRoot = [System.IO.Path]::GetFullPath([string]$diagnostics.backend_repo_root).TrimEnd('\')
        if ($actualRoot -ne $expectedRoot) {
            Write-LaunchLog "Existing backend repo root mismatch. expected=$expectedRoot actual=$actualRoot"
            return $false
        }
        if ($diagnostics.credential_vault_relative_path -ne ".operator_secrets/provider_credentials.json") {
            Write-LaunchLog "Existing backend credential vault path mismatch: $($diagnostics.credential_vault_relative_path)"
            return $false
        }
        return $true
    } catch {
        return $false
    }
}

$env:PK_OPERATOR_API_BASE = $BaseUrl

$operatorReady = Test-OperatorApi

if (-not $operatorReady) {
    Write-LaunchLog "Starting operator backend on $BaseUrl"
    Write-LaunchLog "stdout=$StdoutLog stderr=$StderrLog"

    $backendCommand = '"{0}" -m uvicorn app.api.operator_readonly_api:create_operator_app --factory --host {1} --port {2} > "{3}" 2> "{4}"' -f $Python, $HostAddress, $Port, $StdoutLog, $StderrLog
    Set-Content -Path $CmdLauncher -Value @(
        "@echo off",
        "cd /d `"$RepoRoot`"",
        $backendCommand
    ) -Encoding ASCII
    Start-Process -FilePath "cmd.exe" -ArgumentList @("/d", "/c", "`"$CmdLauncher`"") -WorkingDirectory $RepoRoot -WindowStyle Hidden | Out-Null
    Write-LaunchLog "backend_start_dispatched=$CmdLauncher"

    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 500
        $operatorReady = Test-OperatorApi
        if ($operatorReady) {
            break
        }
    }
}

if (-not $operatorReady) {
    Show-LauncherFailure "Backend did not answer $BaseUrl/operator/health with the expected locked operator health payload within 20 seconds."
    exit 1
}

if ($OpenBrowser) {
    Write-LaunchLog "Opening browser at $BaseUrl/operator-ui/?v=desktop-launcher"
    Start-Process "$BaseUrl/operator-ui/?v=desktop-launcher" | Out-Null
}
