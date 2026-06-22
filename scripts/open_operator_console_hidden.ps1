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
$ExpectedActivationVersion = "operator-activation-e2e-truth6-20260602"
$UiVersion = $ExpectedActivationVersion
try {
    $gitHead = (& git -C $RepoRoot rev-parse --short HEAD 2>$null)
    if (-not [string]::IsNullOrWhiteSpace($gitHead)) {
        $UiVersion = [string]$gitHead
    }
} catch {
    $UiVersion = $ExpectedActivationVersion
}
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

function ConvertTo-SafeLaunchText {
    param([object]$Value)
    $text = [string]$Value
    $text = $text -replace '(?i)Bearer\s+[A-Za-z0-9._\-]+', 'Bearer REDACTED'
    $text = $text -replace 'sk-[A-Za-z0-9_-]{10,}', 'sk-REDACTED'
    $text = $text -replace 'AKIA[0-9A-Z]{12,}', 'AKIA-REDACTED'
    $text = $text -replace '(?i)(api[_-]?key|secret|token|password|credential|authorization)\s*=\s*[^;\s]+', '$1=REDACTED'
    return $text
}

function Get-OperatorPaperEnvFile {
    $candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($env:PK_OPERATOR_PAPER_ENV_FILE)) {
        $candidates += $env:PK_OPERATOR_PAPER_ENV_FILE
    }
    $candidates += (Join-Path $RepoRoot ".poverty_killer_alpaca_paper_env")
    $userProfile = [Environment]::GetFolderPath("UserProfile")
    if (-not [string]::IsNullOrWhiteSpace($userProfile)) {
        $candidates += (Join-Path $userProfile ".poverty_killer_alpaca_paper_env")
    }
    foreach ($candidate in $candidates) {
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and (Test-Path -LiteralPath $candidate)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    return $null
}

function Import-OperatorPaperEnvFile {
    $envFile = Get-OperatorPaperEnvFile
    if ([string]::IsNullOrWhiteSpace($envFile)) {
        Write-LaunchLog "operator_paper_env_file=not_found"
        return @()
    }
    $loadedKeys = @()
    $approvedPattern = '^APCA_API_(KEY_ID|SECRET_KEY|BASE_URL)$'
    foreach ($line in (Get-Content -LiteralPath $envFile -ErrorAction Stop)) {
        $trimmed = ([string]$line).Trim()
        if ([string]::IsNullOrWhiteSpace($trimmed) -or $trimmed.StartsWith("#")) {
            continue
        }
        if ($trimmed.StartsWith("export ")) {
            $trimmed = $trimmed.Substring(7).Trim()
        }
        $parts = $trimmed -split "=", 2
        if ($parts.Count -ne 2) {
            continue
        }
        $key = $parts[0].Trim()
        if ($key -notmatch $approvedPattern) {
            continue
        }
        $value = $parts[1].Trim()
        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        [Environment]::SetEnvironmentVariable($key, $value, "Process")
        $loadedKeys += $key
    }
    if ($loadedKeys.Count -gt 0) {
        Write-LaunchLog (ConvertTo-SafeLaunchText "operator_paper_env_loaded keys=$($loadedKeys -join ',') values=REDACTED")
    } else {
        Write-LaunchLog "operator_paper_env_loaded keys=none values=REDACTED"
    }
    return $loadedKeys
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
        if ($payload.operator_activation_version -ne $ExpectedActivationVersion) {
            Write-LaunchLog "Existing backend activation version mismatch. expected=$ExpectedActivationVersion actual=$($payload.operator_activation_version)"
            return $false
        }
        $diagnosticsResponse = Invoke-WebRequest -Uri "$BaseUrl/operator/credentials/diagnostics" -UseBasicParsing -TimeoutSec 2
        if ([int]$diagnosticsResponse.StatusCode -ne 200) {
            return $false
        }
        $diagnostics = $diagnosticsResponse.Content | ConvertFrom-Json
        if ($diagnostics.operator_activation_version -ne $ExpectedActivationVersion) {
            Write-LaunchLog "Existing backend credential diagnostic activation version mismatch. expected=$ExpectedActivationVersion actual=$($diagnostics.operator_activation_version)"
            return $false
        }
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
        $diagnosticFields = $diagnostics.PSObject.Properties.Name
        if (-not ($diagnosticFields -contains "accepted_provider_ids")) {
            Write-LaunchLog "Existing backend missing hotfix diagnostic field accepted_provider_ids"
            return $false
        }
        if (-not ($diagnostics.accepted_provider_ids -contains "alpaca_paper")) {
            Write-LaunchLog "Existing backend credential diagnostics does not accept alpaca_paper"
            return $false
        }
        if (-not ($diagnosticFields -contains "vault_writable")) {
            Write-LaunchLog "Existing backend missing hotfix diagnostic field vault_writable"
            return $false
        }
        if (-not ($diagnosticFields -contains "last_save_received_field_presence")) {
            Write-LaunchLog "Existing backend missing hotfix diagnostic field last_save_received_field_presence"
            return $false
        }
        return $true
    } catch {
        return $false
    }
}

function Request-OperatorStackShutdown {
    param([string]$RequestedBy = "hidden_launcher_stale_backend")
    try {
        $payload = @{
            confirm_shutdown_stack = $true
            confirm_api_process_exit = $true
            confirm_preserve_broker_positions = $true
            confirm_no_broker_cleanup_requested = $true
            requested_by = $RequestedBy
        } | ConvertTo-Json -Compress
        Invoke-WebRequest -Uri "$BaseUrl/operator/intent/stack/shutdown" -Method POST -ContentType "application/json" -Body $payload -UseBasicParsing -TimeoutSec 2 | Out-Null
        Write-LaunchLog "stack_shutdown_intent_sent endpoint=/operator/intent/stack/shutdown requested_by=$RequestedBy"
        return $true
    } catch {
        Write-LaunchLog "stack_shutdown_intent_failed=$($_.Exception.GetType().Name):$($_.Exception.Message)"
        return $false
    }
}

function Stop-StaleOperatorBackend {
    try {
        $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        foreach ($listener in $listeners) {
            $processId = [int]$listener.OwningProcess
            if ($processId -le 0) {
                continue
            }
            $process = Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction SilentlyContinue
            $commandLine = [string]$process.CommandLine
            if ($commandLine -like "*app.api.operator_readonly_api:create_operator_app*") {
                Write-LaunchLog "Stopping stale operator backend pid=$processId"
                $graceful = Request-OperatorStackShutdown "hidden_launcher_stale_backend"
                if ($graceful) {
                    Start-Sleep -Milliseconds 1000
                }
                if (Get-Process -Id $processId -ErrorAction SilentlyContinue) {
                    Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
                }
            } else {
                Write-LaunchLog "Port $Port is occupied by non-operator process pid=$processId"
            }
        }
        Start-Sleep -Milliseconds 500
    } catch {
        Write-LaunchLog "Stale backend stop check failed: $($_.Exception.GetType().Name)"
    }
}

$env:PK_OPERATOR_API_BASE = $BaseUrl

$operatorReady = Test-OperatorApi

if (-not $operatorReady) {
    Stop-StaleOperatorBackend
    Write-LaunchLog "Starting operator backend on $BaseUrl"
    Write-LaunchLog "stdout=$StdoutLog stderr=$StderrLog"
    Import-OperatorPaperEnvFile | Out-Null

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
    Write-LaunchLog "Opening browser at $BaseUrl/operator-ui/?v=$UiVersion"
    Start-Process "$BaseUrl/operator-ui/?v=$UiVersion" | Out-Null
}
