param(
    [int]$Port = 8765,
    [string]$HostAddress = "127.0.0.1",
    [switch]$NoAutoOpen
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$GuardedLauncher = Join-Path $PSScriptRoot "open_operator_console_hidden.ps1"
$Python = Join-Path $RepoRoot "venv\Scripts\python.exe"
$BaseUrl = "http://$HostAddress`:$Port"
$UiUrl = "$BaseUrl/operator-ui/?v=operator-activation-e2e-truth6-20260602"
$LogBase = $env:LOCALAPPDATA
if ([string]::IsNullOrWhiteSpace($LogBase)) {
    $LogBase = $env:TEMP
}
if ([string]::IsNullOrWhiteSpace($LogBase)) {
    $LogBase = $RepoRoot
}
$LogRoot = Join-Path $LogBase "PovertyKiller\operator-launcher"
$LaunchLog = Join-Path $LogRoot "launcher-control.log"

New-Item -Path $LogRoot -ItemType Directory -Force | Out-Null

function Write-LauncherLog {
    param([string]$Message)
    Add-Content -Path $LaunchLog -Value "$((Get-Date).ToString("o")) $Message"
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

function Get-CodeChangeSummary {
    try {
        $lines = & git -C $RepoRoot status --short -- app scripts ui tests 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $lines) {
            return "clean"
        }
        $count = @($lines | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }).Count
        if ($count -le 0) {
            return "clean"
        }
        return "$count code/script/UI/test change(s) present; restart recommended after updates."
    } catch {
        return "UNKNOWN_NOT_AVAILABLE"
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
    param([string]$Path)
    $response = Invoke-WebRequest -Uri "$BaseUrl$Path" -UseBasicParsing -TimeoutSec 3
    if ([int]$response.StatusCode -ne 200) {
        throw "HTTP $($response.StatusCode)"
    }
    return $response.Content | ConvertFrom-Json
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
    $changeSummary = Get-CodeChangeSummary
    $processes = @(Get-OperatorBackendProcesses)
    $status = "STOPPED"
    $healthText = "Backend is not listening on $BaseUrl."
    $loadedCommit = "UNKNOWN_NOT_AVAILABLE"
    $loadedBranch = "UNKNOWN_NOT_AVAILABLE"
    $startTime = "UNKNOWN_NOT_AVAILABLE"
    $backendPid = if ($processes.Count) { ($processes | Select-Object -ExpandProperty ProcessId) -join "," } else { "none" }
    $warning = ""
    $uiOpenStatus = if ($script:UiOpenedAt) { "Opened at $script:UiOpenedAt" } else { "Not opened by this launcher session" }

    if ($processes.Count -gt 0) {
        $status = "RUNNING"
        try {
            $health = Invoke-OperatorJson "/operator/health"
            $operatorStatus = Invoke-OperatorJson "/operator/status"
            $loadedCommit = First-TextValue $operatorStatus.git_commit_short $health.git_commit_short
            $loadedBranch = First-TextValue $operatorStatus.git_branch $health.git_branch
            $startTime = First-TextValue $operatorStatus.process_start_time $health.process_start_time
            $backendPid = First-TextValue $operatorStatus.backend_pid $backendPid
            $healthText = "Health=$($health.api_status); supervisor=$($health.supervisor_status); live=$($health.live_status); real_money=$($health.real_money_status)"
            if ($health.live_status -ne "LIVE_LOCKED" -or $health.real_money_status -ne "BLOCKED") {
                $status = "FAILED"
                $warning = "Unsafe health payload. Do not use this backend."
            }
            if ($loadedCommit -eq "UNKNOWN_NOT_AVAILABLE") {
                $warning = "Backend commit unavailable. Backend may be stale. Restart recommended."
            } elseif ($repoHead -ne "UNKNOWN_NOT_AVAILABLE" -and $loadedCommit -ne $repoHead) {
                $warning = "Backend may be stale. Restart recommended."
            } elseif ($changeSummary -ne "clean") {
                $warning = "Restart required after update: $changeSummary"
            }
        } catch {
            $status = "FAILED"
            $healthText = "Health check failed: $($_.Exception.Message)"
            $warning = "Backend failed health/status check. Restart recommended."
        }
    }

    return [pscustomobject]@{
        Status = $status
        BaseUrl = $BaseUrl
        UiUrl = $UiUrl
        RepoHead = $repoHead
        RepoBranch = $repoBranch
        LoadedCommit = $loadedCommit
        LoadedBranch = $loadedBranch
        ProcessStartTime = $startTime
        BackendPid = $backendPid
        Health = $healthText
        UiOpenStatus = $uiOpenStatus
        Warning = $warning
        ChangeSummary = $changeSummary
        LogRoot = $LogRoot
        Safety = "Launcher controls only the local operator API process. No PAPER start, broker mutation, live enablement, real-money enablement, state cleanup, reset, delete, stash, or prune."
    }
}

function Start-Backend {
    if (-not (Test-Path $Python)) {
        throw "Python venv not found at $Python"
    }
    if (-not (Test-Path $GuardedLauncher)) {
        throw "Guarded backend launcher not found at $GuardedLauncher"
    }
    Write-LauncherLog "start_backend_requested port=$Port"
    & $GuardedLauncher -Port $Port -HostAddress $HostAddress -OpenBrowser $false
}

function Stop-Backend {
    Write-LauncherLog "stop_backend_requested port=$Port"
    $processes = @(Get-OperatorBackendProcesses)
    foreach ($process in $processes) {
        Write-LauncherLog "stopping_backend_pid=$($process.ProcessId)"
        Stop-Process -Id ([int]$process.ProcessId) -Force -ErrorAction SilentlyContinue
    }
}

function Open-OperatorUi {
    Start-Process $UiUrl | Out-Null
    $script:UiOpenedAt = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    Write-LauncherLog "operator_ui_opened=$UiUrl"
}

function Copy-Diagnostics {
    param($Model)
    $diagnostics = @(
        "POVERTY_KILLER Operator Launcher Diagnostics",
        "Backend status: $($Model.Status)",
        "Backend URL: $($Model.BaseUrl)",
        "Operator UI: $($Model.UiUrl)",
        "Repo HEAD: $($Model.RepoHead)",
        "Repo branch: $($Model.RepoBranch)",
        "Backend loaded commit: $($Model.LoadedCommit)",
        "Backend loaded branch: $($Model.LoadedBranch)",
        "Backend PID: $($Model.BackendPid)",
        "Backend process start: $($Model.ProcessStartTime)",
        "Last health: $($Model.Health)",
        "Operator UI open status: $($Model.UiOpenStatus)",
        "Repo changes: $($Model.ChangeSummary)",
        "Warning: $($Model.Warning)",
        "Logs: $($Model.LogRoot)",
        "Safety: $($Model.Safety)"
    ) -join [Environment]::NewLine
    [System.Windows.Forms.Clipboard]::SetText($diagnostics)
    Write-LauncherLog "diagnostics_copied"
}

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

$script:UiOpenedAt = $null
$script:LastStatus = $null

$form = New-Object System.Windows.Forms.Form
$form.Text = "POVERTY_KILLER Operator Launcher"
$form.StartPosition = "CenterScreen"
$form.Size = New-Object System.Drawing.Size(720, 520)
$form.MinimumSize = New-Object System.Drawing.Size(640, 460)
$form.TopMost = $false

$title = New-Object System.Windows.Forms.Label
$title.Text = "POVERTY_KILLER Operator Launcher"
$title.Font = New-Object System.Drawing.Font("Segoe UI", 14, [System.Drawing.FontStyle]::Bold)
$title.AutoSize = $true
$title.Location = New-Object System.Drawing.Point(18, 16)
$form.Controls.Add($title)

$statusLabel = New-Object System.Windows.Forms.Label
$statusLabel.Text = "Backend status: CHECKING"
$statusLabel.Font = New-Object System.Drawing.Font("Segoe UI", 12, [System.Drawing.FontStyle]::Bold)
$statusLabel.AutoSize = $true
$statusLabel.Location = New-Object System.Drawing.Point(20, 58)
$form.Controls.Add($statusLabel)

$warningLabel = New-Object System.Windows.Forms.Label
$warningLabel.Text = ""
$warningLabel.ForeColor = [System.Drawing.Color]::DarkRed
$warningLabel.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Bold)
$warningLabel.AutoSize = $false
$warningLabel.Size = New-Object System.Drawing.Size(660, 36)
$warningLabel.Location = New-Object System.Drawing.Point(20, 88)
$form.Controls.Add($warningLabel)

$details = New-Object System.Windows.Forms.TextBox
$details.Multiline = $true
$details.ReadOnly = $true
$details.ScrollBars = "Vertical"
$details.Font = New-Object System.Drawing.Font("Consolas", 9)
$details.Location = New-Object System.Drawing.Point(20, 132)
$details.Size = New-Object System.Drawing.Size(660, 240)
$details.Anchor = "Top,Left,Right,Bottom"
$form.Controls.Add($details)

$startButton = New-Object System.Windows.Forms.Button
$startButton.Text = "Start backend"
$startButton.AccessibleName = "Start backend"
$startButton.Size = New-Object System.Drawing.Size(120, 34)
$startButton.Location = New-Object System.Drawing.Point(20, 392)
$startButton.Anchor = "Left,Bottom"
$form.Controls.Add($startButton)

$stopButton = New-Object System.Windows.Forms.Button
$stopButton.Text = "Stop backend"
$stopButton.AccessibleName = "Stop backend"
$stopButton.Size = New-Object System.Drawing.Size(120, 34)
$stopButton.Location = New-Object System.Drawing.Point(150, 392)
$stopButton.Anchor = "Left,Bottom"
$form.Controls.Add($stopButton)

$restartButton = New-Object System.Windows.Forms.Button
$restartButton.Text = "Restart backend"
$restartButton.AccessibleName = "Restart backend"
$restartButton.Size = New-Object System.Drawing.Size(130, 34)
$restartButton.Location = New-Object System.Drawing.Point(280, 392)
$restartButton.Anchor = "Left,Bottom"
$form.Controls.Add($restartButton)

$openButton = New-Object System.Windows.Forms.Button
$openButton.Text = "Open operator UI"
$openButton.AccessibleName = "Open operator UI"
$openButton.Size = New-Object System.Drawing.Size(130, 34)
$openButton.Location = New-Object System.Drawing.Point(420, 392)
$openButton.Anchor = "Left,Bottom"
$form.Controls.Add($openButton)

$refreshButton = New-Object System.Windows.Forms.Button
$refreshButton.Text = "Refresh status"
$refreshButton.AccessibleName = "Refresh status"
$refreshButton.Size = New-Object System.Drawing.Size(120, 34)
$refreshButton.Location = New-Object System.Drawing.Point(560, 392)
$refreshButton.Anchor = "Left,Bottom"
$form.Controls.Add($refreshButton)

$copyButton = New-Object System.Windows.Forms.Button
$copyButton.Text = "Copy diagnostics"
$copyButton.AccessibleName = "Copy diagnostics"
$copyButton.Size = New-Object System.Drawing.Size(140, 34)
$copyButton.Location = New-Object System.Drawing.Point(20, 436)
$copyButton.Anchor = "Left,Bottom"
$form.Controls.Add($copyButton)

$safetyLabel = New-Object System.Windows.Forms.Label
$safetyLabel.Text = "Safe controls only: local backend process management. No PAPER start, broker mutation, live, real-money, or state cleanup."
$safetyLabel.AutoSize = $false
$safetyLabel.Size = New-Object System.Drawing.Size(520, 36)
$safetyLabel.Location = New-Object System.Drawing.Point(170, 434)
$safetyLabel.Anchor = "Left,Right,Bottom"
$form.Controls.Add($safetyLabel)

function Set-Busy {
    param([bool]$Busy, [string]$StateText)
    $startButton.Enabled = -not $Busy
    $stopButton.Enabled = -not $Busy
    $restartButton.Enabled = -not $Busy
    $openButton.Enabled = -not $Busy
    $refreshButton.Enabled = -not $Busy
    $copyButton.Enabled = -not $Busy
    if ($StateText) {
        $statusLabel.Text = "Backend status: $StateText"
    }
    [System.Windows.Forms.Application]::DoEvents()
}

function Refresh-LauncherStatus {
    $model = Get-LauncherStatus
    $script:LastStatus = $model
    $statusLabel.Text = "Backend status: $($model.Status)"
    if ($model.Status -eq "RUNNING") {
        $statusLabel.ForeColor = [System.Drawing.Color]::DarkGreen
    } elseif ($model.Status -eq "FAILED") {
        $statusLabel.ForeColor = [System.Drawing.Color]::DarkRed
    } elseif ($model.Status -eq "STARTING") {
        $statusLabel.ForeColor = [System.Drawing.Color]::DarkOrange
    } else {
        $statusLabel.ForeColor = [System.Drawing.Color]::DimGray
    }
    $warningLabel.Text = $model.Warning
    $details.Text = @(
        "Backend URL: $($model.BaseUrl)",
        "Operator UI: $($model.UiUrl)",
        "Loaded commit: $($model.LoadedCommit)",
        "Loaded branch: $($model.LoadedBranch)",
        "Repo HEAD: $($model.RepoHead)",
        "Repo branch: $($model.RepoBranch)",
        "Backend PID: $($model.BackendPid)",
        "Backend start time: $($model.ProcessStartTime)",
        "Last health check: $($model.Health)",
        "Operator UI open status: $($model.UiOpenStatus)",
        "Repo changes: $($model.ChangeSummary)",
        "Logs: $($model.LogRoot)",
        "",
        $model.Safety
    ) -join [Environment]::NewLine
    $startButton.Enabled = $model.Status -ne "RUNNING"
    $stopButton.Enabled = $model.Status -eq "RUNNING" -or $model.Status -eq "FAILED"
    $restartButton.Enabled = $model.Status -eq "RUNNING" -or $model.Status -eq "FAILED"
    $openButton.Enabled = $model.Status -eq "RUNNING"
    $refreshButton.Enabled = $true
    $copyButton.Enabled = $true
    return $model
}

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
        $model = Refresh-LauncherStatus
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
        Stop-Backend
        Start-Sleep -Milliseconds 700
        Start-Backend
        $model = Refresh-LauncherStatus
        if ($model.Status -eq "RUNNING" -and -not $model.Warning) {
            Open-OperatorUi
            Refresh-LauncherStatus | Out-Null
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

$form.Add_Shown({
    try {
        $model = Refresh-LauncherStatus
        if ($model.Status -eq "STOPPED") {
            Set-Busy $true "STARTING"
            Start-Backend
            $model = Refresh-LauncherStatus
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

Write-LauncherLog "launcher_window_opened base_url=$BaseUrl"
[void]$form.ShowDialog()
