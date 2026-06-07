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

function Ensure-OperatorShortcut {
    try {
        $desktop = [Environment]::GetFolderPath("Desktop")
        if ([string]::IsNullOrWhiteSpace($desktop)) {
            return
        }
        $shortcutPath = Join-Path $desktop "POVERTY_KILLER Operator.lnk"
        $scriptPath = $PSCommandPath
        if ([string]::IsNullOrWhiteSpace($scriptPath)) {
            $scriptPath = Join-Path $PSScriptRoot "open_operator_console.ps1"
        }
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut($shortcutPath)
        $shortcut.TargetPath = "powershell.exe"
        $shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -STA -File `"$scriptPath`""
        $shortcut.WorkingDirectory = $RepoRoot
        $shortcut.WindowStyle = 1
        $shortcut.Description = "POVERTY_KILLER Operator"
        $shortcut.Save()
        Write-LauncherLog "operator_shortcut_ready=$shortcutPath"
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
    $workingTreeSummary = Get-WorkingTreeSummary
    $processes = @(Get-OperatorBackendProcesses)
    $status = "STOPPED"
    $healthText = "Backend is not listening on $BaseUrl."
    $loadedCommit = "UNKNOWN_NOT_AVAILABLE"
    $loadedBranch = "UNKNOWN_NOT_AVAILABLE"
    $startTime = "UNKNOWN_NOT_AVAILABLE"
    $backendPid = if ($processes.Count) { ($processes | Select-Object -ExpandProperty ProcessId) -join "," } else { "none" }
    $warning = ""
    $freshnessStatus = "Stopped"
    $freshnessDetail = "Backend is stopped. Start Backend launches the local operator API only."
    $healthState = "Offline"
    $healthDetail = "Backend is not listening."
    $uiOpenStatus = if ($script:UiOpenedAt) { "Opened by launcher at $script:UiOpenedAt" } else { "Not opened by launcher" }

    if ($processes.Count -gt 0) {
        $status = "RUNNING"
        $freshnessStatus = "Checking"
        $freshnessDetail = "Comparing backend loaded commit to repo HEAD."
        $healthState = "Checking"
        $healthDetail = "Reading health and operator status."
        try {
            $health = Invoke-OperatorJson "/operator/health"
            $operatorStatus = Invoke-OperatorJson "/operator/status"
            $loadedCommit = First-TextValue $operatorStatus.git_commit_short $health.git_commit_short
            $loadedBranch = First-TextValue $operatorStatus.git_branch $health.git_branch
            $startTime = First-TextValue $operatorStatus.process_start_time $health.process_start_time
            $backendPid = First-TextValue $operatorStatus.backend_pid $backendPid
            $healthText = "Health=$($health.api_status); supervisor=$($health.supervisor_status); live=$($health.live_status); real_money=$($health.real_money_status)"
            $healthState = "Connected"
            $healthDetail = "Supervisor $($health.supervisor_status); live locked; real money blocked."
            if ($health.live_status -ne "LIVE_LOCKED" -or $health.real_money_status -ne "BLOCKED") {
                $status = "FAILED"
                $healthState = "Unsafe"
                $healthDetail = "Health payload is not PAPER-only safe."
                $warning = "Unsafe health payload. Do not use this backend."
            }
            if ($loadedCommit -eq "UNKNOWN_NOT_AVAILABLE") {
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
        } catch {
            $status = "FAILED"
            $freshnessStatus = "Unknown"
            $freshnessDetail = "Health/status check failed."
            $healthState = "Failed"
            $healthDetail = "Health/status endpoint failed."
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
        HealthState = $healthState
        HealthDetail = $healthDetail
        FreshnessStatus = $freshnessStatus
        FreshnessDetail = $freshnessDetail
        UiOpenStatus = $uiOpenStatus
        Warning = $warning
        WorkingTreeLabel = Get-WorkingTreeLabel $workingTreeSummary
        WorkingTreeSummary = $workingTreeSummary
        ChangeSummary = $workingTreeSummary
        LogRoot = $LogRoot
        Safety = "PAPER only. Live locked. Real money blocked. Launcher controls only the local operator API process. No PAPER start, broker mutation, live enablement, real-money enablement, state cleanup, reset, delete, stash, or prune."
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
    $arguments = @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        "`"$GuardedLauncher`"",
        "-Port",
        [string]$Port,
        "-HostAddress",
        $HostAddress,
        "-OpenBrowser:`$false"
    )
    Start-Process -FilePath "powershell.exe" -ArgumentList $arguments -WindowStyle Hidden -WorkingDirectory $RepoRoot | Out-Null
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
    $diagnostics = Get-DiagnosticsText $Model
    [System.Windows.Forms.Clipboard]::SetText($diagnostics)
    Write-LauncherLog "diagnostics_copied"
}

function Get-DiagnosticsText {
    param($Model)
    return @(
        "POVERTY_KILLER Operator Diagnostics",
        "Backend status: $($Model.Status)",
        "Backend freshness: $($Model.FreshnessStatus) - $($Model.FreshnessDetail)",
        "Backend URL: $($Model.BaseUrl)",
        "Operator UI: $($Model.UiUrl)",
        "Repo HEAD: $($Model.RepoHead)",
        "Repo branch: $($Model.RepoBranch)",
        "Backend loaded commit: $($Model.LoadedCommit)",
        "Backend loaded branch: $($Model.LoadedBranch)",
        "Backend PID: $($Model.BackendPid)",
        "Backend process start: $($Model.ProcessStartTime)",
        "Last health: $($Model.Health)",
        "Operator UI: $($Model.UiOpenStatus)",
        "Working tree: $($Model.WorkingTreeSummary)",
        "Warning: $($Model.Warning)",
        "Logs: $($Model.LogRoot)",
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
    } elseif ($model.Status -eq "FAILED") {
        $statusColor = $colorBad
        $statusLabel.ForeColor = $colorBad
    } elseif ($model.Status -eq "STARTING") {
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
    } elseif ($model.Status -eq "RUNNING" -and $model.FreshnessStatus -eq "Current") {
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

    $startButton.Enabled = $model.Status -ne "RUNNING"
    $stopButton.Enabled = $model.Status -eq "RUNNING" -or $model.Status -eq "FAILED"
    $restartButton.Enabled = $model.Status -eq "RUNNING" -or $model.Status -eq "FAILED"
    $openButton.Enabled = $model.Status -eq "RUNNING"
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
    } elseif ($model.Status -eq "RUNNING") {
        Set-ButtonTone $openButton "primary"
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
        if ($model.Status -eq "RUNNING" -or $model.Status -eq "FAILED") {
            return $model
        }
        Start-Sleep -Milliseconds 500
        [System.Windows.Forms.Application]::DoEvents()
        $model = Refresh-LauncherStatus
    }
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
        Stop-Backend
        Start-Sleep -Milliseconds 700
        Start-Backend
        $model = Wait-ForBackendReady
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

Write-LauncherLog "launcher_window_opened base_url=$BaseUrl"
[void]$form.ShowDialog()
