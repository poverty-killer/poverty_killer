param(
    [int]$Port = 8765,
    [string]$HostAddress = "127.0.0.1",
    [switch]$NoAutoOpen
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $RepoRoot "venv\Scripts\python.exe"
$BaseUrl = "http://$HostAddress`:$Port"
$script:UiUrl = "$BaseUrl/operator-ui/"
$script:UiVersion = "UNKNOWN_NOT_AVAILABLE"
$LogBase = $env:LOCALAPPDATA
if ([string]::IsNullOrWhiteSpace($LogBase)) {
    $LogBase = $env:TEMP
}
if ([string]::IsNullOrWhiteSpace($LogBase)) {
    $LogBase = $RepoRoot
}
$LogRoot = Join-Path $LogBase "PovertyKiller\operator-launcher"
$LaunchLog = Join-Path $LogRoot "launcher-control.log"
$OperatorStateBase = [Environment]::GetFolderPath("LocalApplicationData")
if ([string]::IsNullOrWhiteSpace($OperatorStateBase)) {
    $OperatorStateBase = Join-Path ([Environment]::GetFolderPath("UserProfile")) ".local\state"
}
$OperatorStateRoot = Join-Path $OperatorStateBase "PovertyKiller\state\operator"
[Environment]::SetEnvironmentVariable("PK_OPERATOR_STATE_DIR", $OperatorStateRoot, "Process")
[Environment]::SetEnvironmentVariable("PK_OPERATOR_IDLE_EXIT_ON_UI_DISCONNECT", "true", "Process")

New-Item -Path $LogRoot -ItemType Directory -Force | Out-Null
New-Item -Path $OperatorStateRoot -ItemType Directory -Force | Out-Null

function ConvertTo-SafeLauncherText {
    param([object]$Value)
    $text = [string]$Value
    $text = $text -replace '(?i)Bearer\s+[A-Za-z0-9._\-]+', 'Bearer REDACTED'
    $text = $text -replace 'sk-[A-Za-z0-9_-]{10,}', 'sk-REDACTED'
    $text = $text -replace 'AKIA[0-9A-Z]{12,}', 'AKIA-REDACTED'
    $text = $text -replace '(?i)(api[_-]?key|secret|token|password|credential|authorization)\s*=\s*[^;\s]+', '$1=REDACTED'
    return $text
}

function Write-LauncherLog {
    param([string]$Message)
    Add-Content -Path $LaunchLog -Value "$((Get-Date).ToString("o")) $(ConvertTo-SafeLauncherText $Message)"
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
        Write-LauncherLog "operator_paper_env_file=not_found"
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
        Write-LauncherLog "operator_paper_env_loaded keys=$($loadedKeys -join ',') values=REDACTED"
    } else {
        Write-LauncherLog "operator_paper_env_loaded keys=none values=REDACTED"
    }
    return $loadedKeys
}

$LauncherVersion = "operator-launcher-reliability-v1"
$script:LauncherStateOverride = $null
$script:LastStartAttemptTime = "none"
$script:LastStopAttemptTime = "none"
$script:LastFailurePhase = "none"
$script:LastFailureReason = "none"
$script:LastSpawnedPid = "none"
$script:LastCmdLauncher = "none"
$script:LastStdoutLog = "none"
$script:LastStderrLog = "none"
$script:LastCommand = "none"
$script:LastHealthUrl = "$BaseUrl/operator/health"
$script:LauncherBusy = $false

function Set-LauncherFailure {
    param(
        [string]$Phase,
        [string]$Reason
    )
    $script:LauncherStateOverride = "FAILED"
    $script:LastFailurePhase = if ([string]::IsNullOrWhiteSpace($Phase)) { "unknown" } else { $Phase }
    $script:LastFailureReason = if ([string]::IsNullOrWhiteSpace($Reason)) { "unknown failure" } else { ConvertTo-SafeLauncherText $Reason }
    Write-LauncherLog "launcher_failure phase=$script:LastFailurePhase reason=$script:LastFailureReason"
}

function Clear-LauncherFailure {
    $script:LastFailurePhase = "none"
    $script:LastFailureReason = "none"
}

function Clear-LauncherTransition {
    $script:LauncherStateOverride = $null
}

function Test-PortListening {
    try {
        $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        return @($listeners).Count -gt 0
    } catch {
        Write-LauncherLog "port_listen_check_failed=$($_.Exception.GetType().Name)"
        return $false
    }
}

function New-BackendLaunchPlan {
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss_fff"
    $stdoutLog = Join-Path $LogRoot "operator_backend_$stamp.stdout.log"
    $stderrLog = Join-Path $LogRoot "operator_backend_$stamp.stderr.log"
    $cmdLauncher = Join-Path $LogRoot "start_operator_backend_$stamp.cmd"
    $backendCommand = '"{0}" -m uvicorn app.api.operator_readonly_api:create_operator_app --factory --host {1} --port {2} > "{3}" 2> "{4}"' -f $Python, $HostAddress, $Port, $stdoutLog, $stderrLog
    return [pscustomobject]@{
        Stamp = $stamp
        StdoutLog = $stdoutLog
        StderrLog = $stderrLog
        CmdLauncher = $cmdLauncher
        Command = $backendCommand
    }
}

function Get-SafeLogTail {
    param(
        [string]$Path,
        [int]$Lines = 20
    )
    if ([string]::IsNullOrWhiteSpace($Path) -or $Path -eq "none" -or -not (Test-Path $Path)) {
        return "not available"
    }
    try {
        $tail = Get-Content -Path $Path -Tail $Lines -ErrorAction Stop
        if (-not $tail) {
            return "empty"
        }
        return (($tail | ForEach-Object { ConvertTo-SafeLauncherText $_ }) -join [Environment]::NewLine)
    } catch {
        return "failed to read log tail: $($_.Exception.GetType().Name)"
    }
}

function Get-ProcessAlive {
    param([string]$ProcessId)
    try {
        if ([string]::IsNullOrWhiteSpace($ProcessId) -or $ProcessId -eq "none") {
            return $false
        }
        $process = Get-Process -Id ([int]$ProcessId) -ErrorAction SilentlyContinue
        return $null -ne $process
    } catch {
        return $false
    }
}

function Get-GitValue {
    param([string[]]$GitArgs)
    try {
        $value = & git -C $RepoRoot @GitArgs 2>$null
        if ($LASTEXITCODE -eq 0 -and $value) {
            return ([string]($value | Select-Object -First 1)).Trim()
        }
    } catch {
        return "UNKNOWN_NOT_AVAILABLE"
    }
    return "UNKNOWN_NOT_AVAILABLE"
}

function Update-OperatorUiUrl {
    param([string]$RepoHead)
    $version = if ($RepoHead -and $RepoHead -ne "UNKNOWN_NOT_AVAILABLE") { $RepoHead } else { Get-GitValue @("rev-parse", "--short", "HEAD") }
    if ([string]::IsNullOrWhiteSpace($version) -or $version -eq "UNKNOWN_NOT_AVAILABLE") {
        $version = "GIT_HEAD_READ_FAILED"
    }
    $script:UiVersion = $version
    $timestampMs = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
    $script:UiUrl = "$BaseUrl/operator-ui/?v=$version&t=$timestampMs"
    return $script:UiUrl
}

function Get-WorkingTreeSummary {
    try {
        $lines = & git -C $RepoRoot status --short 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $lines) {
            return "clean"
        }
        $entries = @($lines | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
        $count = $entries.Count
        if ($count -le 0) {
            return "clean"
        }
        $runtimeLeftovers = @(
            "state/",
            "reports/",
            "scripts/_paper_audit_common.py",
            "scripts/audit_oms_shutdown.py",
            "scripts/audit_paper_run.py",
            "scripts/audit_safety_markers.py"
        )
        $runtimeCount = 0
        foreach ($entry in $entries) {
            $path = ([string]$entry).Substring([Math]::Min(3, ([string]$entry).Length)).Trim()
            foreach ($prefix in $runtimeLeftovers) {
                if ($path.StartsWith($prefix)) {
                    $runtimeCount += 1
                    break
                }
            }
        }
        if ($runtimeCount -eq $count) {
            return "$count local runtime/journal/audit-helper file(s) present; not a backend freshness signal."
        }
        return "$count local uncommitted file(s) present; not a backend freshness signal."
    } catch {
        return "UNKNOWN_NOT_AVAILABLE"
    }
}

function Get-WorkingTreeLabel {
    param([string]$Summary)
    if ($Summary -eq "clean") {
        return "Working tree clean"
    }
    if ($Summary -eq "UNKNOWN_NOT_AVAILABLE") {
        return "Working tree unknown"
    }
    return "Local files present"
}

function Get-OperatorShortcutPaths {
    $shortcutName = "POVERTY_KILLER Operator.lnk"
    $desktopCandidates = @([Environment]::GetFolderPath("Desktop"))
    foreach ($oneDriveRoot in @($env:OneDrive, $env:OneDriveConsumer)) {
        if (-not [string]::IsNullOrWhiteSpace($oneDriveRoot)) {
            $desktopCandidates += Join-Path $oneDriveRoot "Desktop"
        }
    }
    $desktopCandidates = @($desktopCandidates | Where-Object {
        -not [string]::IsNullOrWhiteSpace($_)
    } | Select-Object -Unique)

    $existingShortcuts = @($desktopCandidates | ForEach-Object {
        $candidate = Join-Path $_ $shortcutName
        if (Test-Path -LiteralPath $candidate) {
            $candidate
        }
    })
    if ($existingShortcuts.Count -gt 0) {
        return $existingShortcuts
    }

    $primaryDesktop = $desktopCandidates | Where-Object {
        Test-Path -LiteralPath $_ -PathType Container
    } | Select-Object -First 1
    if ([string]::IsNullOrWhiteSpace($primaryDesktop)) {
        return @()
    }
    return ,(Join-Path $primaryDesktop $shortcutName)
}

function Ensure-OperatorShortcut {
    try {
        $shortcutPaths = @(Get-OperatorShortcutPaths)
        if ($shortcutPaths.Count -eq 0) {
            return
        }
        $scriptPath = $PSCommandPath
        if ([string]::IsNullOrWhiteSpace($scriptPath)) {
            $scriptPath = Join-Path $PSScriptRoot "open_operator_console.ps1"
        }
        $iconPath = Join-Path $RepoRoot "ui\operator-control-panel\assets\poverty-killer-operator.ico"
        $iconAvailable = Test-Path -LiteralPath $iconPath -PathType Leaf
        if (-not $iconAvailable) {
            Write-LauncherLog "operator_icon_missing=$iconPath"
        }
        $shell = New-Object -ComObject WScript.Shell
        foreach ($shortcutPath in $shortcutPaths) {
            $shortcut = $shell.CreateShortcut($shortcutPath)
            $shortcut.TargetPath = "powershell.exe"
            $shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -STA -File `"$scriptPath`""
            $shortcut.WorkingDirectory = $RepoRoot
            $shortcut.WindowStyle = 1
            $shortcut.Description = "POVERTY_KILLER Operator"
            if ($iconAvailable) {
                $shortcut.IconLocation = "$iconPath,0"
            }
            $shortcut.Save()
            Write-LauncherLog "operator_shortcut_ready=$shortcutPath"
        }
    } catch {
        Write-LauncherLog "operator_shortcut_failed=$($_.Exception.GetType().Name)"
    }
}

function Get-OperatorBackendProcesses {
    $matches = @()
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
                $matches += [pscustomobject]@{
                    ProcessId = $processId
                    CommandLine = $commandLine
                }
            }
        }
    } catch {
        Write-LauncherLog "backend_process_lookup_failed=$($_.Exception.GetType().Name)"
    }
    return $matches
}

function Invoke-OperatorJson {
    param(
        [string]$Path,
        [int]$TimeoutSec = 2
    )
    $response = Invoke-WebRequest -Uri "$BaseUrl$Path" -UseBasicParsing -TimeoutSec $TimeoutSec
    if ([int]$response.StatusCode -ne 200) {
        throw "HTTP $($response.StatusCode)"
    }
    return $response.Content | ConvertFrom-Json
}

function Request-OperatorStackShutdown {
    param(
        [string]$RequestedBy = "desktop_launcher",
        [bool]$RequireIdle = $false
    )
    try {
        $payload = @{
            confirm_shutdown_stack = $true
            confirm_api_process_exit = $true
            confirm_preserve_broker_positions = $true
            confirm_no_broker_cleanup_requested = $true
            require_idle_supervisor = $RequireIdle
            requested_by = $RequestedBy
        } | ConvertTo-Json -Compress
        $response = Invoke-WebRequest -Uri "$BaseUrl/operator/intent/stack/shutdown" -Method POST -ContentType "application/json" -Body $payload -UseBasicParsing -TimeoutSec 2
        $result = $response.Content | ConvertFrom-Json
        Write-LauncherLog "stack_shutdown_intent_result endpoint=/operator/intent/stack/shutdown requested_by=$RequestedBy require_idle=$RequireIdle allowed=$($result.allowed) reason=$($result.reason_code)"
        return $result
    } catch {
        Write-LauncherLog "stack_shutdown_intent_failed=$($_.Exception.GetType().Name):$($_.Exception.Message)"
        return $null
    }
}

function First-TextValue {
    param(
        [object]$Primary,
        [object]$Secondary,
        [string]$DefaultValue = "UNKNOWN_NOT_AVAILABLE"
    )
    if ($null -ne $Primary -and -not [string]::IsNullOrWhiteSpace([string]$Primary)) {
        return [string]$Primary
    }
    if ($null -ne $Secondary -and -not [string]::IsNullOrWhiteSpace([string]$Secondary)) {
        return [string]$Secondary
    }
    return $DefaultValue
}

function Get-LauncherStatus {
    $repoHead = Get-GitValue @("rev-parse", "--short", "HEAD")
    $repoBranch = Get-GitValue @("branch", "--show-current")
    $uiUrl = Update-OperatorUiUrl $repoHead
    $workingTreeSummary = Get-WorkingTreeSummary
    $processes = @(Get-OperatorBackendProcesses)
    $portListening = Test-PortListening
    $status = "STOPPED"
    $healthText = "Backend is not listening on $BaseUrl."
    $loadedCommit = "BACKEND_NOT_RUNNING"
    $loadedBranch = "BACKEND_NOT_RUNNING"
    $startTime = "BACKEND_NOT_RUNNING"
    $backendPid = if ($processes.Count) { ($processes | Select-Object -ExpandProperty ProcessId) -join "," } else { "none" }
    $warning = ""
    $freshnessStatus = "Stopped"
    $freshnessDetail = "Backend is stopped. Start Backend launches the local operator API only."
    $healthState = "Offline"
    $healthDetail = "Backend is not listening."
    $uiOpenStatus = if ($script:UiOpenedAt) { "Opened by launcher at $script:UiOpenedAt" } else { "Not opened by launcher" }
    $supervisorState = "UNKNOWN"
    $activeRunId = "none"
    $operatorUiConnectionCount = -1
    $operatorUiIdleShutdownEnabled = $false

    if ($script:LauncherStateOverride -eq "FAILED") {
        $status = "FAILED"
        $freshnessStatus = "Unknown"
        $freshnessDetail = "Launcher failure phase: $script:LastFailurePhase"
        $healthState = "Failed"
        $healthDetail = $script:LastFailureReason
        $healthText = "Failure: $script:LastFailurePhase - $script:LastFailureReason"
        $warning = "Backend control failed at $script:LastFailurePhase. Copy Diagnostics for details."
    } elseif ($script:LauncherStateOverride -eq "STARTING" -and $processes.Count -eq 0) {
        $status = $script:LauncherStateOverride
        $freshnessStatus = "Checking"
        $freshnessDetail = "Backend transition in progress."
        $healthState = "Checking"
        $healthDetail = "Waiting on local backend process/health truth."
        $healthText = "$status; health URL $script:LastHealthUrl"
    } elseif ($script:LauncherStateOverride -eq "STOPPING" -and ($processes.Count -gt 0 -or $portListening)) {
        $status = "STOPPING"
        $freshnessStatus = "Checking"
        $freshnessDetail = "Waiting for backend process and port release."
        $healthState = "Checking"
        $healthDetail = "Stop requested; verifying port $Port is released."
        $healthText = "STOPPING; port_listening=$portListening"
    } elseif ($processes.Count -gt 0) {
        $status = "RUNNING"
        $freshnessStatus = "Checking"
        $freshnessDetail = "Comparing backend loaded commit to repo HEAD."
        $healthState = "Checking"
        $healthDetail = "Reading health and launcher-status."
        try {
            $health = Invoke-OperatorJson "/operator/health" 1
            $loadedCommit = First-TextValue $health.loaded_commit $health.git_commit_short "BACKEND_HEALTH_COMMIT_MISSING"
            $loadedBranch = First-TextValue $health.loaded_branch $health.git_branch "BACKEND_HEALTH_BRANCH_MISSING"
            $startTime = First-TextValue $health.process_start_time $health.timestamp_utc "BACKEND_HEALTH_START_TIME_MISSING"
            $backendPid = First-TextValue $health.backend_pid $backendPid
            $healthText = "Health=$($health.api_status); supervisor=$($health.supervisor_status); live=$($health.live_status); real_money=$($health.real_money_status)"
            $healthState = "Connected"
            $healthDetail = "Supervisor $($health.supervisor_status); live locked; real money blocked."
            if ($health.live_status -ne "LIVE_LOCKED" -or $health.real_money_status -ne "BLOCKED") {
                $status = "FAILED"
                $healthState = "Unsafe"
                $healthDetail = "Health payload is not PAPER-only safe."
                $warning = "Unsafe health payload. Do not use this backend."
            }
            try {
                $launcherStatus = Invoke-OperatorJson "/operator/launcher-status" 1
                $loadedCommit = First-TextValue $launcherStatus.loaded_commit $loadedCommit
                $loadedBranch = First-TextValue $launcherStatus.loaded_branch $loadedBranch
                $startTime = First-TextValue $launcherStatus.process_start_time $startTime
                $backendPid = First-TextValue $launcherStatus.pid $backendPid
                $supervisorState = First-TextValue $launcherStatus.supervisor_state "UNKNOWN"
                $activeRunId = First-TextValue $launcherStatus.active_run_id "none"
                if ($null -ne $launcherStatus.operator_ui_connection_count) {
                    $operatorUiConnectionCount = [int]$launcherStatus.operator_ui_connection_count
                }
                $operatorUiIdleShutdownEnabled = $launcherStatus.operator_ui_idle_shutdown_enabled -eq $true
                $healthDetail = "Supervisor $supervisorState; active run $activeRunId; cockpit clients $operatorUiConnectionCount."
                if ($launcherStatus.api_status -ne "OK") {
                    $status = "DEGRADED"
                    $warning = "Launcher status degraded: $($launcherStatus.degraded_reason_codes -join ',')."
                }
            } catch {
                $status = "RUNNING_LAUNCHER_STATUS_TIMEOUT"
                $healthState = "Connected"
                $healthDetail = "Health OK; /operator/launcher-status timed out. Backend remains running; launcher status is degraded."
                $warning = "Backend health connected; /operator/launcher-status timed out. This is degraded, not failed."
                Write-LauncherLog "operator_launcher_status_timeout=$($_.Exception.GetType().Name):$($_.Exception.Message)"
            }
            if ($loadedCommit -eq "UNKNOWN_NOT_AVAILABLE" -or $loadedCommit -like "BACKEND_*") {
                $freshnessStatus = "Unknown"
                $freshnessDetail = "Backend commit unavailable from read-only status."
                $warning = "Backend commit unavailable. Backend may be stale. Restart recommended."
            } elseif ($repoHead -ne "UNKNOWN_NOT_AVAILABLE" -and $loadedCommit -ne $repoHead) {
                $freshnessStatus = "Stale"
                $freshnessDetail = "Loaded commit $loadedCommit differs from repo HEAD $repoHead."
                $warning = "Backend stale. Restart recommended."
            } elseif ($repoHead -eq "UNKNOWN_NOT_AVAILABLE") {
                $freshnessStatus = "Unknown"
                $freshnessDetail = "Repo HEAD unavailable; cannot compare backend freshness."
            } else {
                $freshnessStatus = "Current"
                $freshnessDetail = "Backend code current. Loaded commit matches repo HEAD."
            }
            Clear-LauncherTransition
        } catch {
            $status = "RUNNING_STATUS_TIMEOUT"
            $freshnessStatus = "Unknown"
            $freshnessDetail = "Backend process and port are present, but health/status timed out or was unreachable."
            $healthState = "Status timeout"
            $healthDetail = "Backend process is running on port $Port, but health did not return inside launcher timeout."
            $healthText = "Health check failed: $($_.Exception.Message)"
            $loadedCommit = "BACKEND_HEALTH_TIMEOUT"
            $loadedBranch = "BACKEND_HEALTH_TIMEOUT"
            $startTime = "BACKEND_HEALTH_TIMEOUT"
            $warning = "Backend status timeout. This is degraded, not generic FAILED; refresh or restart if it persists."
            Write-LauncherLog "operator_health_timeout=$($_.Exception.GetType().Name):$($_.Exception.Message)"
        }
    } elseif ($portListening) {
        $status = "FAILED"
        $freshnessStatus = "Unknown"
        $freshnessDetail = "Port $Port is listening, but no matching operator backend process was found."
        $healthState = "Failed"
        $healthDetail = "Port occupied by non-operator or unrecognized process."
        $healthText = "Port $Port listening without operator backend match."
        $loadedCommit = "PORT_NOT_OPERATOR_BACKEND"
        $loadedBranch = "PORT_NOT_OPERATOR_BACKEND"
        $startTime = "PORT_NOT_OPERATOR_BACKEND"
        $warning = "Port $Port is occupied by a non-operator process. Start Backend cannot safely proceed."
    }

    return [pscustomobject]@{
        LauncherVersion = $LauncherVersion
        Status = $status
        BaseUrl = $BaseUrl
        UiUrl = $uiUrl
        HealthUrl = $script:LastHealthUrl
        RepoHead = $repoHead
        RepoBranch = $repoBranch
        LoadedCommit = $loadedCommit
        LoadedBranch = $loadedBranch
        ProcessStartTime = $startTime
        BackendPid = $backendPid
        SpawnedPid = $script:LastSpawnedPid
        PortListening = $portListening
        Health = $healthText
        HealthState = $healthState
        HealthDetail = $healthDetail
        SupervisorState = $supervisorState
        ActiveRunId = $activeRunId
        OperatorUiConnectionCount = $operatorUiConnectionCount
        OperatorUiIdleShutdownEnabled = $operatorUiIdleShutdownEnabled
        FreshnessStatus = $freshnessStatus
        FreshnessDetail = $freshnessDetail
        UiOpenStatus = $uiOpenStatus
        Warning = $warning
        LastStartAttemptTime = $script:LastStartAttemptTime
        LastStopAttemptTime = $script:LastStopAttemptTime
        LastFailurePhase = $script:LastFailurePhase
        LastFailureReason = $script:LastFailureReason
        LastCommand = $script:LastCommand
        LastCmdLauncher = $script:LastCmdLauncher
        LastStdoutLog = $script:LastStdoutLog
        LastStderrLog = $script:LastStderrLog
        WorkingTreeLabel = Get-WorkingTreeLabel $workingTreeSummary
        WorkingTreeSummary = $workingTreeSummary
        ChangeSummary = $workingTreeSummary
        LogRoot = $LogRoot
        Safety = "PAPER only. Live locked. Real money blocked. Launcher controls only the local operator API process. No PAPER start, broker mutation, live enablement, real-money enablement, state cleanup, reset, delete, stash, or prune."
    }
}

function Start-Backend {
    $script:LauncherStateOverride = "STARTING"
    $script:LastStartAttemptTime = (Get-Date).ToString("o")
    Clear-LauncherFailure
    Write-LauncherLog "start_backend_requested port=$Port"
    if (-not (Test-Path $Python)) {
        Set-LauncherFailure "spawn_failed" "Python venv not found at $Python"
        throw "Python venv not found at $Python"
    }
    if (Test-PortListening) {
        $existing = @(Get-OperatorBackendProcesses)
        if ($existing.Count -gt 0) {
            Write-LauncherLog "start_backend_skipped_already_running port=$Port"
            Clear-LauncherTransition
            return
        }
        Set-LauncherFailure "wrong_port" "Port $Port is already listening, but no matching operator backend process was found."
        throw "Port $Port is already listening, but no matching operator backend process was found."
    }
    try {
        New-Item -Path $LogRoot -ItemType Directory -Force | Out-Null
        Import-OperatorPaperEnvFile | Out-Null
        $plan = New-BackendLaunchPlan
        $script:LastCmdLauncher = $plan.CmdLauncher
        $script:LastStdoutLog = $plan.StdoutLog
        $script:LastStderrLog = $plan.StderrLog
        $script:LastCommand = $plan.Command
        New-Item -Path $plan.StdoutLog -ItemType File -Force | Out-Null
        New-Item -Path $plan.StderrLog -ItemType File -Force | Out-Null
        Set-Content -Path $plan.CmdLauncher -Value @(
            "@echo off",
            "cd /d `"$RepoRoot`"",
            $plan.Command
        ) -Encoding ASCII
        Write-LauncherLog "backend_launch_artifacts cmd=$($plan.CmdLauncher) stdout=$($plan.StdoutLog) stderr=$($plan.StderrLog)"
        Write-LauncherLog "backend_launch_command=$($plan.Command)"
        $process = Start-Process -FilePath "cmd.exe" -ArgumentList @("/d", "/c", "`"$($plan.CmdLauncher)`"") -WorkingDirectory $RepoRoot -WindowStyle Hidden -PassThru -ErrorAction Stop
        if ($null -eq $process -or $process.Id -le 0) {
            Set-LauncherFailure "spawn_failed" "Start-Process returned no process id."
            throw "Start-Process returned no process id."
        }
        $script:LastSpawnedPid = [string]$process.Id
        Write-LauncherLog "backend_start_dispatched=$($plan.CmdLauncher) spawned_pid=$($process.Id)"
    } catch {
        if ($script:LauncherStateOverride -ne "FAILED") {
            Set-LauncherFailure "spawn_failed" $_.Exception.Message
        }
        throw
    }
}

function Stop-Backend {
    param([switch]$RequireIdle)
    $script:LauncherStateOverride = "STOPPING"
    $script:LastStopAttemptTime = (Get-Date).ToString("o")
    Write-LauncherLog "stop_backend_requested port=$Port"
    $processes = @(Get-OperatorBackendProcesses)
    if ($processes.Count -eq 0) {
        if (Test-PortListening) {
            Set-LauncherFailure "stop_failed" "Port $Port is listening, but no matching operator backend process was found."
            throw "Port $Port is listening, but no matching operator backend process was found."
        }
        Write-LauncherLog "stop_backend_no_operator_process port=$Port"
        Clear-LauncherTransition
        return $true
    }
    $shutdown = Request-OperatorStackShutdown "visible_launcher_stop_backend" ([bool]$RequireIdle)
    if ($null -ne $shutdown -and $shutdown.allowed -eq $true) {
        for ($i = 0; $i -lt 24; $i += 1) {
            Start-Sleep -Milliseconds 250
            [System.Windows.Forms.Application]::DoEvents()
            if (-not (Test-PortListening)) {
                Write-LauncherLog "backend_stop_confirmed_via_stack_shutdown port=$Port"
                Clear-LauncherTransition
                return $true
            }
        }
        Write-LauncherLog "stack_shutdown_port_still_listening_fallback_to_scoped_process_stop port=$Port"
    } elseif ($RequireIdle) {
        $reason = if ($null -ne $shutdown) { [string]$shutdown.reason_code } else { "IDLE_ONLY_SHUTDOWN_UNAVAILABLE" }
        Write-LauncherLog "idle_only_backend_stop_preserved reason=$reason"
        Clear-LauncherTransition
        return $false
    }
    foreach ($process in $processes) {
        Write-LauncherLog "stopping_backend_pid=$($process.ProcessId)"
        try {
            Stop-Process -Id ([int]$process.ProcessId) -Force -ErrorAction Stop
        } catch {
            Set-LauncherFailure "stop_failed" "Failed to stop backend pid=$($process.ProcessId): $($_.Exception.Message)"
            throw
        }
    }
    $released = $false
    for ($i = 0; $i -lt 20; $i += 1) {
        Start-Sleep -Milliseconds 250
        [System.Windows.Forms.Application]::DoEvents()
        if (-not (Test-PortListening)) {
            $released = $true
            break
        }
    }
    if (-not $released) {
        Set-LauncherFailure "port_not_released" "Port $Port did not release after stopping backend process."
        throw "Port $Port did not release after stopping backend process."
    }
    Write-LauncherLog "backend_stop_confirmed port=$Port"
    Clear-LauncherTransition
    return $true
}

function Restart-Backend {
    param([switch]$RequireIdle)
    Write-LauncherLog "restart_backend_requested port=$Port"
    try {
        $stopped = Stop-Backend -RequireIdle:$RequireIdle
        if ($stopped -ne $true) {
            Write-LauncherLog "restart_backend_preserved_active_or_uncertain_runtime"
            return $false
        }
    } catch {
        if ($script:LastFailurePhase -eq "none") {
            Set-LauncherFailure "stop_failed" $_.Exception.Message
        }
        throw
    }
    if (Test-PortListening) {
        Set-LauncherFailure "port_not_released" "Port $Port still listening after stop phase."
        throw "Port $Port still listening after stop phase."
    }
    try {
        Start-Backend
    } catch {
        if ($script:LastFailurePhase -eq "none") {
            Set-LauncherFailure "spawn_failed" $_.Exception.Message
        }
        throw
    }
    return $true
}

function Ensure-FreshIdleBackend {
    param($Model)
    if ($null -eq $Model -or $Model.Status -notin @("RUNNING", "RUNNING_STATUS_TIMEOUT", "RUNNING_LAUNCHER_STATUS_TIMEOUT")) {
        return $Model
    }
    $activeOrUncertain = $Model.SupervisorState -ne "IDLE" -or $Model.ActiveRunId -ne "none"
    $orphaned = $Model.OperatorUiConnectionCount -eq 0
    $lifecycleUpgradeRequired = $Model.OperatorUiConnectionCount -lt 0 -or -not $Model.OperatorUiIdleShutdownEnabled
    $codeRefreshRequired = $Model.FreshnessStatus -in @("Stale", "Unknown")
    if (-not ($orphaned -or $lifecycleUpgradeRequired -or $codeRefreshRequired)) {
        Write-LauncherLog "startup_backend_reused_current_attached_cockpit clients=$($Model.OperatorUiConnectionCount)"
        return $Model
    }
    if ($activeOrUncertain) {
        Write-LauncherLog "startup_backend_preserved_active_or_uncertain supervisor=$($Model.SupervisorState) active_run=$($Model.ActiveRunId)"
        return $Model
    }
    Write-LauncherLog "startup_fresh_idle_backend_requested orphaned=$orphaned lifecycle_upgrade=$lifecycleUpgradeRequired code_refresh=$codeRefreshRequired"
    $restarted = Restart-Backend -RequireIdle
    if ($restarted -ne $true) {
        return (Refresh-LauncherStatus)
    }
    return (Wait-ForBackendReady)
}

function Open-OperatorUi {
    Update-OperatorUiUrl (Get-GitValue @("rev-parse", "--short", "HEAD")) | Out-Null
    Start-Process $script:UiUrl | Out-Null
    $script:UiOpenedAt = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    Write-LauncherLog "operator_ui_opened=$script:UiUrl"
}

function Copy-Diagnostics {
    param($Model)
    $diagnostics = Get-DiagnosticsText $Model
    [System.Windows.Forms.Clipboard]::SetText($diagnostics)
    Write-LauncherLog "diagnostics_copied"
}

function Get-DiagnosticsText {
    param($Model)
    return @(
        "POVERTY_KILLER Operator Diagnostics",
        "Launcher version: $($Model.LauncherVersion)",
        "Repo path: $RepoRoot",
        "Backend status: $($Model.Status)",
        "Backend freshness: $($Model.FreshnessStatus) - $($Model.FreshnessDetail)",
        "Backend URL: $($Model.BaseUrl)",
        "Health URL: $($Model.HealthUrl)",
        "Operator UI: $($Model.UiUrl)",
        "Repo HEAD: $($Model.RepoHead)",
        "Repo branch: $($Model.RepoBranch)",
        "Backend loaded commit: $($Model.LoadedCommit)",
        "Backend loaded branch: $($Model.LoadedBranch)",
        "Backend PID: $($Model.BackendPid)",
        "Spawned launcher PID: $($Model.SpawnedPid)",
        "Supervisor state: $($Model.SupervisorState)",
        "Active run: $($Model.ActiveRunId)",
        "Cockpit clients: $($Model.OperatorUiConnectionCount)",
        "Idle exit on last cockpit close: $($Model.OperatorUiIdleShutdownEnabled)",
        "Port listening: $($Model.PortListening)",
        "Backend process start: $($Model.ProcessStartTime)",
        "Last health: $($Model.Health)",
        "Operator UI: $($Model.UiOpenStatus)",
        "Last start attempt: $($Model.LastStartAttemptTime)",
        "Last stop attempt: $($Model.LastStopAttemptTime)",
        "Last failure phase: $($Model.LastFailurePhase)",
        "Last failure reason: $($Model.LastFailureReason)",
        "Start command: $($Model.LastCommand)",
        "Start cmd wrapper: $($Model.LastCmdLauncher)",
        "Stdout log: $($Model.LastStdoutLog)",
        "Stderr log: $($Model.LastStderrLog)",
        "Working tree: $($Model.WorkingTreeSummary)",
        "Warning: $($Model.Warning)",
        "Logs: $($Model.LogRoot)",
        "Latest stdout tail:",
        (Get-SafeLogTail $Model.LastStdoutLog 20),
        "Latest stderr tail:",
        (Get-SafeLogTail $Model.LastStderrLog 20),
        "Safety: $($Model.Safety)"
    ) -join [Environment]::NewLine
}

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

function Hide-ConsoleHost {
    try {
        if (-not ("Win32.ConsoleWindow" -as [type])) {
            Add-Type -Namespace Win32 -Name ConsoleWindow -MemberDefinition @"
[System.Runtime.InteropServices.DllImport("kernel32.dll")]
public static extern System.IntPtr GetConsoleWindow();
[System.Runtime.InteropServices.DllImport("user32.dll")]
public static extern bool ShowWindow(System.IntPtr hWnd, int nCmdShow);
"@
        }
        $handle = [Win32.ConsoleWindow]::GetConsoleWindow()
        if ($handle -ne [System.IntPtr]::Zero) {
            [void][Win32.ConsoleWindow]::ShowWindow($handle, 0)
        }
    } catch {
        Write-LauncherLog "hide_console_failed=$($_.Exception.GetType().Name)"
    }
}

Hide-ConsoleHost

$script:UiOpenedAt = $null
$script:LastStatus = $null

$colorBackground = [System.Drawing.Color]::FromArgb(15, 19, 26)
$colorPanel = [System.Drawing.Color]::FromArgb(27, 34, 45)
$colorPanelAlt = [System.Drawing.Color]::FromArgb(35, 43, 55)
$colorBorder = [System.Drawing.Color]::FromArgb(62, 74, 91)
$colorText = [System.Drawing.Color]::FromArgb(238, 243, 248)
$colorMuted = [System.Drawing.Color]::FromArgb(157, 170, 186)
$colorAccent = [System.Drawing.Color]::FromArgb(59, 130, 246)
$colorGood = [System.Drawing.Color]::FromArgb(22, 163, 74)
$colorWarn = [System.Drawing.Color]::FromArgb(217, 119, 6)
$colorBad = [System.Drawing.Color]::FromArgb(220, 38, 38)
$colorNeutral = [System.Drawing.Color]::FromArgb(71, 85, 105)

function New-BadgeLabel {
    param(
        [string]$Text,
        [int]$X,
        [int]$Y,
        [int]$Width
    )
    $label = New-Object System.Windows.Forms.Label
    $label.Text = $Text
    $label.Font = New-Object System.Drawing.Font("Segoe UI", 8.5, [System.Drawing.FontStyle]::Bold)
    $label.TextAlign = "MiddleCenter"
    $label.AutoSize = $false
    $label.Size = New-Object System.Drawing.Size($Width, 26)
    $label.Location = New-Object System.Drawing.Point($X, $Y)
    $label.ForeColor = [System.Drawing.Color]::White
    $label.BackColor = $colorNeutral
    return $label
}

function Set-Badge {
    param(
        $Badge,
        [string]$Text,
        [System.Drawing.Color]$BackColor
    )
    $Badge.Text = $Text
    $Badge.BackColor = $BackColor
    $Badge.ForeColor = [System.Drawing.Color]::White
}

function New-StatusCard {
    param(
        [string]$Title,
        [int]$X,
        [int]$Y,
        [int]$Width,
        [int]$Height
    )
    $panel = New-Object System.Windows.Forms.Panel
    $panel.Location = New-Object System.Drawing.Point($X, $Y)
    $panel.Size = New-Object System.Drawing.Size($Width, $Height)
    $panel.BackColor = $colorPanel
    $panel.BorderStyle = "FixedSingle"

    $titleLabel = New-Object System.Windows.Forms.Label
    $titleLabel.Text = $Title
    $titleLabel.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Regular)
    $titleLabel.ForeColor = $colorMuted
    $titleLabel.AutoSize = $false
    $titleLabel.Size = New-Object System.Drawing.Size(($Width - 20), 18)
    $titleLabel.Location = New-Object System.Drawing.Point(10, 9)
    $panel.Controls.Add($titleLabel)

    $valueLabel = New-Object System.Windows.Forms.Label
    $valueLabel.Text = "CHECKING"
    $valueLabel.Font = New-Object System.Drawing.Font("Segoe UI", 12.5, [System.Drawing.FontStyle]::Bold)
    $valueLabel.ForeColor = $colorText
    $valueLabel.AutoSize = $false
    $valueLabel.AutoEllipsis = $false
    $valueLabel.UseMnemonic = $false
    $valueLabel.Size = New-Object System.Drawing.Size(($Width - 20), 27)
    $valueLabel.Location = New-Object System.Drawing.Point(10, 31)
    $panel.Controls.Add($valueLabel)

    $detailLabel = New-Object System.Windows.Forms.Label
    $detailLabel.Text = ""
    $detailLabel.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Regular)
    $detailLabel.ForeColor = $colorMuted
    $detailLabel.AutoSize = $false
    $detailLabel.AutoEllipsis = $false
    $detailLabel.UseMnemonic = $false
    $detailLabel.Size = New-Object System.Drawing.Size(($Width - 20), ($Height - 64))
    $detailLabel.Location = New-Object System.Drawing.Point(10, 60)
    $panel.Controls.Add($detailLabel)

    $form.Controls.Add($panel)
    return [pscustomobject]@{
        Panel = $panel
        Title = $titleLabel
        Value = $valueLabel
        Detail = $detailLabel
    }
}

function Set-StatusCard {
    param(
        $Card,
        [string]$Value,
        [string]$Detail,
        [System.Drawing.Color]$ValueColor
    )
    $Card.Value.Text = $Value
    $Card.Value.ForeColor = $ValueColor
    $Card.Detail.Text = $Detail
}

function New-LauncherButton {
    param(
        [string]$Text,
        [int]$X,
        [int]$Y,
        [int]$Width
    )
    $button = New-Object System.Windows.Forms.Button
    $button.Text = $Text
    $button.AccessibleName = $Text
    $button.Size = New-Object System.Drawing.Size($Width, 38)
    $button.Location = New-Object System.Drawing.Point($X, $Y)
    $button.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Bold)
    $button.FlatStyle = "Flat"
    $button.FlatAppearance.BorderColor = $colorBorder
    $button.FlatAppearance.BorderSize = 1
    $button.BackColor = $colorPanelAlt
    $button.ForeColor = $colorText
    $button.UseVisualStyleBackColor = $false
    return $button
}

function Set-ButtonTone {
    param(
        $Button,
        [string]$Tone
    )
    if ($Tone -eq "primary") {
        $Button.BackColor = $colorAccent
        $Button.ForeColor = [System.Drawing.Color]::White
        $Button.FlatAppearance.BorderColor = [System.Drawing.Color]::FromArgb(147, 197, 253)
    } elseif ($Tone -eq "good") {
        $Button.BackColor = $colorGood
        $Button.ForeColor = [System.Drawing.Color]::White
        $Button.FlatAppearance.BorderColor = [System.Drawing.Color]::FromArgb(134, 239, 172)
    } elseif ($Tone -eq "restart") {
        $Button.BackColor = [System.Drawing.Color]::FromArgb(37, 99, 235)
        $Button.ForeColor = [System.Drawing.Color]::White
        $Button.FlatAppearance.BorderColor = [System.Drawing.Color]::FromArgb(96, 165, 250)
    } elseif ($Tone -eq "stop") {
        $Button.BackColor = [System.Drawing.Color]::FromArgb(39, 45, 56)
        $Button.ForeColor = [System.Drawing.Color]::FromArgb(248, 196, 196)
        $Button.FlatAppearance.BorderColor = [System.Drawing.Color]::FromArgb(127, 29, 29)
    } elseif ($Tone -eq "warning") {
        $Button.BackColor = $colorWarn
        $Button.ForeColor = [System.Drawing.Color]::White
        $Button.FlatAppearance.BorderColor = [System.Drawing.Color]::FromArgb(251, 191, 36)
    } else {
        $Button.BackColor = $colorPanelAlt
        $Button.ForeColor = $colorText
        $Button.FlatAppearance.BorderColor = $colorBorder
    }
}

$form = New-Object System.Windows.Forms.Form
$form.Text = "POVERTY_KILLER Operator"
$form.StartPosition = "CenterScreen"
$form.Size = New-Object System.Drawing.Size(840, 730)
$form.MinimumSize = New-Object System.Drawing.Size(800, 690)
$form.TopMost = $false
$form.BackColor = $colorBackground
$form.ForeColor = $colorText

$title = New-Object System.Windows.Forms.Label
$title.Text = "POVERTY_KILLER Operator"
$title.Font = New-Object System.Drawing.Font("Segoe UI", 15.5, [System.Drawing.FontStyle]::Bold)
$title.ForeColor = $colorText
$title.AutoSize = $true
$title.Location = New-Object System.Drawing.Point(22, 18)
$form.Controls.Add($title)

$subtitle = New-Object System.Windows.Forms.Label
$subtitle.Text = "Local backend control panel. PAPER only. No broker or trading actions."
$subtitle.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Regular)
$subtitle.ForeColor = $colorMuted
$subtitle.AutoSize = $true
$subtitle.Location = New-Object System.Drawing.Point(24, 48)
$form.Controls.Add($subtitle)

$backendStatusBadge = New-BadgeLabel "CHECKING" 474 22 102
$freshnessStatusBadge = New-BadgeLabel "CHECKING" 586 22 112
$safetyStatusBadge = New-BadgeLabel "PAPER ONLY" 708 22 96
$form.Controls.Add($backendStatusBadge)
$form.Controls.Add($freshnessStatusBadge)
$form.Controls.Add($safetyStatusBadge)

$statusLabel = New-Object System.Windows.Forms.Label
$statusLabel.Text = "Backend status: CHECKING"
$statusLabel.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Bold)
$statusLabel.ForeColor = $colorMuted
$statusLabel.AutoSize = $true
$statusLabel.Location = New-Object System.Drawing.Point(24, 74)
$form.Controls.Add($statusLabel)

$warningLabel = New-Object System.Windows.Forms.Label
$warningLabel.Text = ""
$warningLabel.ForeColor = $colorMuted
$warningLabel.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Bold)
$warningLabel.AutoSize = $false
$warningLabel.Size = New-Object System.Drawing.Size(780, 26)
$warningLabel.Location = New-Object System.Drawing.Point(24, 96)
$form.Controls.Add($warningLabel)

$backendCard = New-StatusCard "Backend status" 24 124 176 106
$freshnessCard = New-StatusCard "Backend freshness" 212 124 260 106
$safetyCard = New-StatusCard "Safety posture" 484 124 320 106

$versionCard = New-StatusCard "Loaded code" 24 244 250 110
$connectionCard = New-StatusCard "Connection" 286 244 250 110
$healthCard = New-StatusCard "Health check" 548 244 256 110

$uiCard = New-StatusCard "Operator UI" 24 368 384 94
$workingTreeCard = New-StatusCard "Local files" 420 368 384 94

$diagnosticsHeader = New-Object System.Windows.Forms.Label
$diagnosticsHeader.Text = "Diagnostics"
$diagnosticsHeader.Font = New-Object System.Drawing.Font("Segoe UI", 10, [System.Drawing.FontStyle]::Bold)
$diagnosticsHeader.ForeColor = $colorText
$diagnosticsHeader.AutoSize = $true
$diagnosticsHeader.Location = New-Object System.Drawing.Point(24, 480)
$form.Controls.Add($diagnosticsHeader)

$diagnosticsPreview = New-Object System.Windows.Forms.Label
$diagnosticsPreview.Text = "Hidden by default. Copy Diagnostics includes full local status without secrets."
$diagnosticsPreview.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Regular)
$diagnosticsPreview.ForeColor = $colorMuted
$diagnosticsPreview.AutoSize = $false
$diagnosticsPreview.AutoEllipsis = $false
$diagnosticsPreview.Size = New-Object System.Drawing.Size(500, 36)
$diagnosticsPreview.Location = New-Object System.Drawing.Point(24, 506)
$form.Controls.Add($diagnosticsPreview)

$toggleDiagnosticsButton = New-LauncherButton "Show Diagnostics" 538 500 132
$form.Controls.Add($toggleDiagnosticsButton)

$copyButton = New-LauncherButton "Copy Diagnostics" 682 500 122
$copyButton.Anchor = "Right,Bottom"
$form.Controls.Add($copyButton)

$diagnosticsPanel = New-Object System.Windows.Forms.Panel
$diagnosticsPanel.Location = New-Object System.Drawing.Point(24, 548)
$diagnosticsPanel.Size = New-Object System.Drawing.Size(780, 48)
$diagnosticsPanel.BackColor = $colorPanel
$diagnosticsPanel.BorderStyle = "FixedSingle"
$diagnosticsPanel.Visible = $false
$diagnosticsPanel.Anchor = "Left,Right,Bottom"
$form.Controls.Add($diagnosticsPanel)

$diagnosticsText = New-Object System.Windows.Forms.TextBox
$diagnosticsText.Multiline = $true
$diagnosticsText.ReadOnly = $true
$diagnosticsText.ScrollBars = "Vertical"
$diagnosticsText.Font = New-Object System.Drawing.Font("Consolas", 8.5)
$diagnosticsText.ForeColor = $colorText
$diagnosticsText.BackColor = [System.Drawing.Color]::FromArgb(11, 15, 20)
$diagnosticsText.BorderStyle = "None"
$diagnosticsText.HideSelection = $true
$diagnosticsText.TabStop = $false
$diagnosticsText.Location = New-Object System.Drawing.Point(10, 7)
$diagnosticsText.Size = New-Object System.Drawing.Size(758, 34)
$diagnosticsText.Anchor = "Top,Left,Right,Bottom"
$diagnosticsPanel.Controls.Add($diagnosticsText)

$startButton = New-LauncherButton "Start Backend" 24 612 144
$startButton.Anchor = "Left,Bottom"
$form.Controls.Add($startButton)

$openButton = New-LauncherButton "Open Operator UI" 180 612 176
$openButton.Anchor = "Left,Bottom"
$form.Controls.Add($openButton)

$restartButton = New-LauncherButton "Restart Backend" 368 612 162
$restartButton.Anchor = "Left,Bottom"
$form.Controls.Add($restartButton)

$stopButton = New-LauncherButton "Stop Backend" 542 612 126
$stopButton.Anchor = "Left,Bottom"
$form.Controls.Add($stopButton)

$refreshButton = New-LauncherButton "Refresh" 680 612 124
$refreshButton.Anchor = "Left,Bottom"
$form.Controls.Add($refreshButton)

$safetyLabel = New-Object System.Windows.Forms.Label
$safetyLabel.Text = "Controls manage the local backend process only. No PAPER start, broker mutation, live, real money, or state cleanup."
$safetyLabel.AutoSize = $false
$safetyLabel.Size = New-Object System.Drawing.Size(780, 30)
$safetyLabel.Location = New-Object System.Drawing.Point(24, 654)
$safetyLabel.Anchor = "Left,Right,Bottom"
$safetyLabel.Font = New-Object System.Drawing.Font("Segoe UI", 8.5, [System.Drawing.FontStyle]::Regular)
$safetyLabel.ForeColor = $colorMuted
$form.Controls.Add($safetyLabel)

function Set-Busy {
    param([bool]$Busy, [string]$StateText)
    $script:LauncherBusy = $Busy
    $startButton.Enabled = -not $Busy
    $stopButton.Enabled = -not $Busy
    $restartButton.Enabled = -not $Busy
    $openButton.Enabled = -not $Busy
    $refreshButton.Enabled = -not $Busy
    $copyButton.Enabled = -not $Busy
    $toggleDiagnosticsButton.Enabled = -not $Busy
    if ($StateText) {
        $statusLabel.Text = "Backend status: $StateText"
        Set-Badge $backendStatusBadge $StateText $colorWarn
        Set-StatusCard $backendCard $StateText "Local operator API process transition in progress." $colorWarn
    }
    [System.Windows.Forms.Application]::DoEvents()
}

function Refresh-LauncherStatus {
    $model = Get-LauncherStatus
    $script:LastStatus = $model
    $statusLabel.Text = "Backend status: $($model.Status)"
    $statusColor = $colorNeutral
    if ($model.Status -eq "RUNNING") {
        $statusColor = $colorGood
        $statusLabel.ForeColor = $colorGood
    } elseif ($model.Status -in @("RUNNING_STATUS_TIMEOUT", "RUNNING_LAUNCHER_STATUS_TIMEOUT")) {
        $statusColor = $colorWarn
        $statusLabel.ForeColor = $colorWarn
    } elseif ($model.Status -eq "FAILED") {
        $statusColor = $colorBad
        $statusLabel.ForeColor = $colorBad
    } elseif ($model.Status -in @("STARTING", "STOPPING")) {
        $statusColor = $colorWarn
        $statusLabel.ForeColor = $colorWarn
    } else {
        $statusLabel.ForeColor = $colorMuted
    }
    $freshnessColor = $colorNeutral
    if ($model.FreshnessStatus -eq "Current") {
        $freshnessColor = $colorGood
    } elseif ($model.FreshnessStatus -eq "Stale") {
        $freshnessColor = $colorWarn
    } elseif ($model.FreshnessStatus -eq "Unknown") {
        $freshnessColor = $colorWarn
    }

    Set-Badge $backendStatusBadge $model.Status $statusColor
    Set-Badge $freshnessStatusBadge $model.FreshnessStatus $freshnessColor
    Set-Badge $safetyStatusBadge "PAPER ONLY" $colorGood

    if ($model.Warning) {
        $warningLabel.Text = $model.Warning
        $warningLabel.ForeColor = $colorWarn
    } elseif ($model.Status -in @("RUNNING", "RUNNING_STATUS_TIMEOUT", "RUNNING_LAUNCHER_STATUS_TIMEOUT") -and $model.FreshnessStatus -eq "Current") {
        $warningLabel.Text = "Backend code current. Local uncommitted files are diagnostics only."
        $warningLabel.ForeColor = $colorGood
    } elseif ($model.Status -eq "STOPPED") {
        $warningLabel.Text = "Backend stopped. Start Backend launches the local operator API only."
        $warningLabel.ForeColor = $colorMuted
    } else {
        $warningLabel.Text = "Status refreshed. Safety remains PAPER only."
        $warningLabel.ForeColor = $colorMuted
    }

    Set-StatusCard $backendCard $model.Status "PID: $($model.BackendPid)" $statusColor
    Set-StatusCard $freshnessCard $model.FreshnessStatus $model.FreshnessDetail $freshnessColor
    Set-StatusCard $safetyCard "PAPER ONLY" "Live locked. Real money blocked." $colorGood
    Set-StatusCard $versionCard "Loaded $($model.LoadedCommit)" "Repo HEAD $($model.RepoHead); branch $($model.RepoBranch)" $colorText
    Set-StatusCard $connectionCard $model.BaseUrl "Operator UI: /operator-ui/" $colorText
    Set-StatusCard $healthCard $model.HealthState $model.HealthDetail $colorText
    Set-StatusCard $uiCard $model.UiOpenStatus "Open Operator UI uses the browser; it does not start PAPER." $colorText
    Set-StatusCard $workingTreeCard $model.WorkingTreeLabel "Diagnostics only. Restart only on commit mismatch." $colorMuted

    $diagnosticsText.Text = Get-DiagnosticsText $model
    $diagnosticsText.SelectionStart = 0
    $diagnosticsText.SelectionLength = 0
    if ($model.FreshnessStatus -eq "Stale") {
        $diagnosticsPreview.Text = "Backend loaded commit differs from repo HEAD. Restart recommended."
    } elseif ($model.FreshnessStatus -eq "Current" -and $model.WorkingTreeSummary -eq "clean") {
        $diagnosticsPreview.Text = "Backend code current. Working tree clean."
    } elseif ($model.FreshnessStatus -eq "Current") {
        $diagnosticsPreview.Text = "Backend code current. Local uncommitted files are diagnostics only."
    } else {
        $diagnosticsPreview.Text = "$($model.FreshnessDetail) Local files are diagnostics only."
    }

    $startButton.Enabled = $model.Status -notin @("RUNNING", "RUNNING_STATUS_TIMEOUT", "RUNNING_LAUNCHER_STATUS_TIMEOUT", "STARTING", "STOPPING")
    $stopButton.Enabled = $model.Status -in @("RUNNING", "RUNNING_STATUS_TIMEOUT", "RUNNING_LAUNCHER_STATUS_TIMEOUT", "FAILED")
    $restartButton.Enabled = $model.Status -in @("RUNNING", "RUNNING_STATUS_TIMEOUT", "RUNNING_LAUNCHER_STATUS_TIMEOUT", "FAILED")
    $openButton.Enabled = $model.Status -in @("RUNNING", "RUNNING_STATUS_TIMEOUT", "RUNNING_LAUNCHER_STATUS_TIMEOUT") -and $model.HealthState -eq "Connected"
    $refreshButton.Enabled = $true
    $copyButton.Enabled = $true
    $toggleDiagnosticsButton.Enabled = $true

    Set-ButtonTone $startButton "secondary"
    Set-ButtonTone $openButton "secondary"
    Set-ButtonTone $restartButton "restart"
    Set-ButtonTone $stopButton "stop"
    Set-ButtonTone $refreshButton "secondary"
    Set-ButtonTone $copyButton "secondary"
    Set-ButtonTone $toggleDiagnosticsButton "secondary"
    if ($model.Status -eq "STOPPED") {
        Set-ButtonTone $startButton "good"
    } elseif ($model.Status -in @("RUNNING", "RUNNING_STATUS_TIMEOUT", "RUNNING_LAUNCHER_STATUS_TIMEOUT")) {
        if ($openButton.Enabled) {
            Set-ButtonTone $openButton "primary"
        }
        if ($model.FreshnessStatus -eq "Stale" -or $model.FreshnessStatus -eq "Unknown") {
            Set-ButtonTone $restartButton "warning"
        }
    } elseif ($model.Status -eq "FAILED") {
        Set-ButtonTone $restartButton "warning"
    }
    return $model
}

function Wait-ForBackendReady {
    param([int]$Attempts = 18)
    $model = Refresh-LauncherStatus
    for ($attempt = 0; $attempt -lt $Attempts; $attempt += 1) {
        if ($model.Status -in @("RUNNING", "RUNNING_STATUS_TIMEOUT", "RUNNING_LAUNCHER_STATUS_TIMEOUT", "FAILED")) {
            return $model
        }
        Start-Sleep -Milliseconds 500
        [System.Windows.Forms.Application]::DoEvents()
        $model = Refresh-LauncherStatus
    }
    $stderrTail = Get-SafeLogTail $script:LastStderrLog 20
    $phase = "health_timeout"
    if ($stderrTail -match "Traceback|ImportError|ModuleNotFoundError|Error loading ASGI app|Exception") {
        $phase = "import_crash"
    } elseif (-not (Test-PortListening) -and -not (Get-ProcessAlive $script:LastSpawnedPid)) {
        $phase = "spawn_failed"
    }
    Set-LauncherFailure $phase "Backend did not reach healthy RUNNING state at $script:LastHealthUrl. stderr_tail=$stderrTail"
    $model = Refresh-LauncherStatus
    return $model
}

$toggleDiagnosticsButton.Add_Click({
    $diagnosticsPanel.Visible = -not $diagnosticsPanel.Visible
    if ($diagnosticsPanel.Visible) {
        $toggleDiagnosticsButton.Text = "Hide Diagnostics"
        $toggleDiagnosticsButton.AccessibleName = "Hide Diagnostics"
    } else {
        $toggleDiagnosticsButton.Text = "Show Diagnostics"
        $toggleDiagnosticsButton.AccessibleName = "Show Diagnostics"
    }
})

$refreshButton.Add_Click({
    try {
        Set-Busy $true "CHECKING"
        Refresh-LauncherStatus | Out-Null
    } catch {
        $warningLabel.Text = "Refresh failed: $($_.Exception.Message)"
        Write-LauncherLog "refresh_failed=$($_.Exception.Message)"
    } finally {
        Set-Busy $false $null
        Refresh-LauncherStatus | Out-Null
    }
})

$startButton.Add_Click({
    try {
        Set-Busy $true "STARTING"
        Start-Backend
        $model = Wait-ForBackendReady
        if ($model.Status -eq "RUNNING" -and -not $model.Warning) {
            Open-OperatorUi
            Refresh-LauncherStatus | Out-Null
        }
    } catch {
        $warningLabel.Text = "Start failed: $($_.Exception.Message)"
        Write-LauncherLog "start_failed=$($_.Exception.Message)"
    } finally {
        Set-Busy $false $null
        Refresh-LauncherStatus | Out-Null
    }
})

$stopButton.Add_Click({
    try {
        Set-Busy $true "STOPPING"
        Stop-Backend
        Start-Sleep -Milliseconds 500
    } catch {
        $warningLabel.Text = "Stop failed: $($_.Exception.Message)"
        Write-LauncherLog "stop_failed=$($_.Exception.Message)"
    } finally {
        Set-Busy $false $null
        Refresh-LauncherStatus | Out-Null
    }
})

$restartButton.Add_Click({
    try {
        Set-Busy $true "RESTARTING"
        $restarted = Restart-Backend -RequireIdle
        $model = if ($restarted -eq $true) { Wait-ForBackendReady } else { Refresh-LauncherStatus }
        if ($model.Status -eq "RUNNING" -and -not $model.Warning) {
            Open-OperatorUi
            Refresh-LauncherStatus | Out-Null
        } elseif ($restarted -ne $true) {
            $warningLabel.Text = "Restart preserved an active or uncertain runtime. Use governed Stop before restarting."
        }
    } catch {
        $warningLabel.Text = "Restart failed: $($_.Exception.Message)"
        Write-LauncherLog "restart_failed=$($_.Exception.Message)"
    } finally {
        Set-Busy $false $null
        Refresh-LauncherStatus | Out-Null
    }
})

$openButton.Add_Click({
    try {
        Open-OperatorUi
        Refresh-LauncherStatus | Out-Null
    } catch {
        $warningLabel.Text = "Open UI failed: $($_.Exception.Message)"
        Write-LauncherLog "open_ui_failed=$($_.Exception.Message)"
    }
})

$copyButton.Add_Click({
    try {
        $model = if ($script:LastStatus) { $script:LastStatus } else { Refresh-LauncherStatus }
        Copy-Diagnostics $model
        $warningLabel.Text = "Diagnostics copied to clipboard."
    } catch {
        $warningLabel.Text = "Copy diagnostics failed: $($_.Exception.Message)"
        Write-LauncherLog "copy_diagnostics_failed=$($_.Exception.Message)"
    }
})

$startupTimer = New-Object System.Windows.Forms.Timer
$startupTimer.Interval = 250
$startupTimer.Add_Tick({
    $startupTimer.Stop()
    try {
        Ensure-OperatorShortcut
        $model = Refresh-LauncherStatus
        if ($model.Status -eq "STOPPED") {
            Set-Busy $true "STARTING"
            Start-Backend
            $model = Wait-ForBackendReady
        } else {
            Set-Busy $true "CHECKING LIFECYCLE"
            $model = Ensure-FreshIdleBackend $model
        }
        if ($model.Status -eq "RUNNING" -and -not $model.Warning -and -not $NoAutoOpen.IsPresent) {
            Open-OperatorUi
            Refresh-LauncherStatus | Out-Null
        }
    } catch {
        $warningLabel.Text = "Startup failed: $($_.Exception.Message)"
        Write-LauncherLog "startup_failed=$($_.Exception.Message)"
    } finally {
        Set-Busy $false $null
        Refresh-LauncherStatus | Out-Null
    }
})

$form.Add_Shown({
    $statusLabel.Text = "Backend status: CHECKING"
    [System.Windows.Forms.Application]::DoEvents()
    $startupTimer.Start()
})

$statusPollTimer = New-Object System.Windows.Forms.Timer
$statusPollTimer.Interval = 2000
$statusPollTimer.Add_Tick({
    if (-not $script:LauncherBusy) {
        try {
            Refresh-LauncherStatus | Out-Null
        } catch {
            Write-LauncherLog "status_poll_failed=$($_.Exception.GetType().Name):$($_.Exception.Message)"
        }
    }
})
$statusPollTimer.Start()

$form.Add_FormClosing({
    $statusPollTimer.Stop()
    try {
        $model = Get-LauncherStatus
        if ($model.Status -in @("RUNNING", "RUNNING_STATUS_TIMEOUT", "RUNNING_LAUNCHER_STATUS_TIMEOUT") -and
            $model.OperatorUiConnectionCount -le 0 -and
            $model.SupervisorState -eq "IDLE") {
            Stop-Backend -RequireIdle | Out-Null
        } else {
            Write-LauncherLog "launcher_window_close_preserved_backend supervisor=$($model.SupervisorState) cockpit_clients=$($model.OperatorUiConnectionCount)"
        }
    } catch {
        Write-LauncherLog "launcher_window_close_cleanup_failed=$($_.Exception.GetType().Name):$($_.Exception.Message)"
    }
})

Write-LauncherLog "launcher_window_opened base_url=$BaseUrl"
[void]$form.ShowDialog()
