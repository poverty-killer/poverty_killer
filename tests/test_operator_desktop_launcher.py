from __future__ import annotations

from pathlib import Path


HIDDEN_LAUNCHER = Path("scripts/open_operator_console_hidden.ps1")
VISIBLE_LAUNCHER = Path("scripts/open_operator_console.ps1")
OPERATOR_UI_BUILD_PLACEHOLDER = "operator-ui-build"
STALE_OPERATOR_UI_VERSION = "operator-activation-e2e-truth6-20260602"


def _launcher_text() -> str:
    return HIDDEN_LAUNCHER.read_text(encoding="utf-8")


def test_hidden_launcher_uses_logged_python_backend_not_silent_pythonw():
    text = _launcher_text()
    lower = text.lower()

    assert "pythonw.exe" not in lower
    assert 'venv\\Scripts\\python.exe' in text
    assert 'Start-Process -FilePath "cmd.exe"' in text
    assert "$backendCommand" in text
    assert "$CmdLauncher" in text
    assert "start_operator_backend_$Stamp.cmd" in text
    assert "Set-Content -Path $CmdLauncher" in text
    assert "$StdoutLog" in text
    assert "$StderrLog" in text
    assert "PovertyKiller\\operator-launcher" in text
    assert "$env:LOCALAPPDATA" in text


def test_hidden_launcher_requires_operator_health_before_browser_open():
    text = _launcher_text()

    assert 'Invoke-WebRequest -Uri "$BaseUrl/operator/health"' in text
    assert "ConvertFrom-Json" in text
    assert 'live_status -ne "LIVE_LOCKED"' in text
    assert 'real_money_status -ne "BLOCKED"' in text
    assert '$ExpectedActivationVersion = "operator-activation-e2e-truth6-20260602"' in text
    assert "operator_activation_version -ne $ExpectedActivationVersion" in text
    assert "[int]$response.StatusCode -lt 500" not in text
    assert "accepted_provider_ids" in text
    assert "alpaca_paper" in text
    assert "vault_writable" in text
    assert "last_save_received_field_presence" in text

    assert "git -C $RepoRoot rev-parse --short HEAD" in text
    assert "$UiVersion = [string]$gitHead" in text
    browser_open = 'Start-Process "$BaseUrl/operator-ui/?v=$UiVersion"'
    assert browser_open in text
    browser_index = text.index(browser_open)
    assert "$operatorReady = Test-OperatorApi" in text
    health_gate_index = text.rindex("if (-not $operatorReady)", 0, browser_index)
    assert health_gate_index < browser_index


def test_hidden_launcher_reports_backend_start_failure_to_user():
    text = _launcher_text()

    assert "Show-LauncherFailure" in text
    assert "backend_start_dispatched=$CmdLauncher" in text
    assert "Backend did not answer" in text
    assert "launcher.log" in text
    assert "exit 1" in text


def test_hidden_launcher_rejects_and_stops_stale_operator_backend():
    text = _launcher_text()

    assert "Stop-StaleOperatorBackend" in text
    assert "Get-NetTCPConnection -LocalPort $Port -State Listen" in text
    assert "Get-CimInstance Win32_Process" in text
    assert "app.api.operator_readonly_api:create_operator_app" in text
    assert "Stopping stale operator backend" in text
    assert "Stop-Process -Id $processId -Force" in text


def test_visible_launcher_presents_safe_backend_control_window():
    text = VISIBLE_LAUNCHER.read_text(encoding="utf-8")

    assert "open_operator_console_hidden.ps1" not in text
    assert "$GuardedLauncher" not in text
    assert "New-BackendLaunchPlan" in text
    assert 'Start-Process -FilePath "cmd.exe"' in text
    assert "-PassThru" in text
    assert "$script:LastCmdLauncher" in text
    assert "$script:LastStdoutLog" in text
    assert "$script:LastStderrLog" in text
    assert "backend_launch_artifacts" in text
    assert "backend_start_dispatched" in text
    assert "Wait-ForBackendReady" in text
    assert "System.Windows.Forms" in text
    assert '$form.Text = "POVERTY_KILLER Operator"' in text
    assert '$title.Text = "POVERTY_KILLER Operator"' in text
    assert "New-Object System.Drawing.Size(840, 730)" in text
    assert "New-Object System.Windows.Forms.Timer" in text
    assert "Hide-ConsoleHost" in text
    assert "New-StatusCard" in text
    assert "Backend status" in text
    assert "Backend freshness" in text
    assert "Safety posture" in text
    assert "Loaded code" in text
    assert "Local files" in text
    assert "Start Backend" in text
    assert "Stop Backend" in text
    assert "Restart Backend" in text
    assert "Open Operator UI" in text
    assert "Refresh" in text
    assert "Copy Diagnostics" in text
    assert "Show Diagnostics" in text
    assert "$diagnosticsPanel.Visible = $false" in text
    assert "Diagnostics only. Restart only on commit mismatch." in text
    assert 'Set-ButtonTone $openButton "primary"' in text
    assert 'Set-ButtonTone $restartButton "restart"' in text
    assert 'Set-ButtonTone $stopButton "stop"' in text
    assert "Backend stale. Restart recommended." in text
    assert "Backend code current. Loaded commit matches repo HEAD." in text
    assert "Restart required after update" not in text
    assert "/operator/health" in text
    assert "/operator/status" in text
    assert "Update-OperatorUiUrl" in text
    assert "$BaseUrl/operator-ui/?v=$version&t=$timestampMs" in text
    assert "operator_ui_opened=$script:UiUrl" in text
    assert STALE_OPERATOR_UI_VERSION not in text
    assert "/operator/intent/paper/start" not in text
    assert "broker mutation" in text
    assert "live enablement" in text
    assert "real-money enablement" in text


def test_visible_launcher_start_backend_creates_artifacts_and_surfaces_spawn_failure():
    text = VISIBLE_LAUNCHER.read_text(encoding="utf-8")

    assert "function Start-Backend" in text
    assert "start_operator_backend_$stamp.cmd" in text
    assert "operator_backend_$stamp.stdout.log" in text
    assert "operator_backend_$stamp.stderr.log" in text
    assert "New-Item -Path $plan.StdoutLog -ItemType File -Force" in text
    assert "New-Item -Path $plan.StderrLog -ItemType File -Force" in text
    assert "Set-Content -Path $plan.CmdLauncher" in text
    assert "$script:LastCommand = $plan.Command" in text
    assert "$script:LastSpawnedPid = [string]$process.Id" in text
    assert 'Set-LauncherFailure "spawn_failed"' in text
    assert 'Set-LauncherFailure "wrong_port"' in text
    assert "Start-Process returned no process id" in text


def test_visible_launcher_health_timeout_and_import_crash_are_not_silent():
    text = VISIBLE_LAUNCHER.read_text(encoding="utf-8")

    assert "function Wait-ForBackendReady" in text
    assert "RUNNING_STATUS_TIMEOUT" in text
    assert 'Backend status timeout. This is degraded, not generic FAILED' in text
    assert '$loadedCommit = "BACKEND_NOT_RUNNING"' in text
    assert '$loadedCommit = "BACKEND_HEALTH_TIMEOUT"' in text
    assert '$loadedCommit = "PORT_NOT_OPERATOR_BACKEND"' in text
    assert '$loadedCommit = "UNKNOWN_NOT_AVAILABLE"' not in text
    assert '$phase = "health_timeout"' in text
    assert '$phase = "import_crash"' in text
    assert "Traceback|ImportError|ModuleNotFoundError|Error loading ASGI app|Exception" in text
    assert "stderr_tail=" in text


def test_visible_launcher_stop_backend_is_port_and_operator_process_scoped():
    text = VISIBLE_LAUNCHER.read_text(encoding="utf-8")

    assert "function Stop-Backend" in text
    assert "Get-OperatorBackendProcesses" in text
    assert "app.api.operator_readonly_api:create_operator_app" in text
    assert 'Set-LauncherFailure "stop_failed"' in text
    assert 'Set-LauncherFailure "port_not_released"' in text
    assert "Port $Port is listening, but no matching operator backend process was found." in text
    assert "Stop-Process -Id ([int]$process.ProcessId) -Force" in text


def test_visible_launcher_restart_reports_stop_port_and_spawn_phases():
    text = VISIBLE_LAUNCHER.read_text(encoding="utf-8")

    assert "function Restart-Backend" in text
    assert "restart_backend_requested" in text
    assert 'Set-LauncherFailure "stop_failed"' in text
    assert 'Set-LauncherFailure "port_not_released"' in text
    assert 'Set-LauncherFailure "spawn_failed"' in text
    assert "Restart-Backend" in text[text.index("$restartButton.Add_Click") :]


def test_visible_launcher_diagnostics_include_launch_artifacts_and_redacted_log_tails():
    text = VISIBLE_LAUNCHER.read_text(encoding="utf-8")

    assert "ConvertTo-SafeLauncherText" in text
    assert "Bearer REDACTED" in text
    assert "Launcher version:" in text
    assert "Repo path:" in text
    assert "Health URL:" in text
    assert "Spawned launcher PID:" in text
    assert "Port listening:" in text
    assert "Last start attempt:" in text
    assert "Last failure phase:" in text
    assert "Start command:" in text
    assert "Start cmd wrapper:" in text
    assert "Stdout log:" in text
    assert "Stderr log:" in text
    assert "Latest stdout tail:" in text
    assert "Latest stderr tail:" in text
    assert "Get-SafeLogTail" in text


def test_desktop_vbs_entrypoint_opens_visible_launcher_not_browser_only():
    text = Path("scripts/open_operator_console_hidden.vbs").read_text(encoding="utf-8")

    assert "open_operator_console.ps1" in text
    assert "open_operator_console_hidden.ps1" not in text
    assert "-STA" in text
    assert "open_operator_console.ps1" in text


def test_visible_launcher_stale_warning_is_commit_based_not_dirty_tree_based():
    text = VISIBLE_LAUNCHER.read_text(encoding="utf-8")

    assert "Get-WorkingTreeSummary" in text
    assert "WorkingTreeSummary" in text
    assert "not a backend freshness signal" in text
    assert "Backend stale. Restart recommended." in text
    assert "Loaded commit $loadedCommit differs from repo HEAD $repoHead." in text
    assert '$freshnessStatus = "Current"' in text
    assert "Loaded commit matches repo HEAD" in text
    assert "git -C $RepoRoot status --short -- app scripts ui tests" not in text
    assert "Restart required after update" not in text
    assert "$model.Warning" not in text[text.find("Working tree:") : text.find("Warning:")]


def test_visible_launcher_forbidden_leftovers_are_diagnostics_only():
    text = VISIBLE_LAUNCHER.read_text(encoding="utf-8")

    assert '"state/"' in text
    assert '"reports/"' in text
    assert '"scripts/_paper_audit_common.py"' in text
    assert '"scripts/audit_oms_shutdown.py"' in text
    assert '"scripts/audit_paper_run.py"' in text
    assert '"scripts/audit_safety_markers.py"' in text
    assert "local runtime/journal/audit-helper file(s) present; not a backend freshness signal." in text
    assert "Local uncommitted files are diagnostics only." in text
    assert 'return "Local files present"' in text


def test_visible_launcher_creates_stable_taskbar_pin_shortcut_identity():
    text = VISIBLE_LAUNCHER.read_text(encoding="utf-8")

    assert "Ensure-OperatorShortcut" in text
    assert '"POVERTY_KILLER Operator.lnk"' in text
    assert "CreateShortcut" in text
    assert '$shortcut.TargetPath = "powershell.exe"' in text
    assert '$shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -STA -File `"$scriptPath`""' in text
    assert "ShowWindow($handle, 0)" in text
    assert "open_operator_console.ps1" in text
    assert "$shortcut.WorkingDirectory = $RepoRoot" in text
    assert '$shortcut.Description = "POVERTY_KILLER Operator"' in text
    assert "APCA_API_SECRET_KEY" not in text
    assert "DEEPSEEK_API_KEY" not in text


def test_operator_ui_assets_are_cache_busted_for_desktop_launcher():
    text = Path("ui/operator-control-panel/index.html").read_text(encoding="utf-8")

    assert f"styles.css?v={OPERATOR_UI_BUILD_PLACEHOLDER}" in text
    assert f"mock-data.js?v={OPERATOR_UI_BUILD_PLACEHOLDER}" in text
    assert f"app.js?v={OPERATOR_UI_BUILD_PLACEHOLDER}" in text
    assert STALE_OPERATOR_UI_VERSION not in text
    assert "operator-credential-hotfix-20260531" not in text
