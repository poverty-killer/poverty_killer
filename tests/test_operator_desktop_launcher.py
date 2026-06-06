from __future__ import annotations

from pathlib import Path


HIDDEN_LAUNCHER = Path("scripts/open_operator_console_hidden.ps1")
VISIBLE_LAUNCHER = Path("scripts/open_operator_console.ps1")
OPERATOR_UI_VERSION = "operator-activation-e2e-truth6-20260602"


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

    assert f'$UiVersion = "{OPERATOR_UI_VERSION}"' in text
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

    assert "open_operator_console_hidden.ps1" in text
    assert "$GuardedLauncher" in text
    assert "& $GuardedLauncher -Port $Port -HostAddress $HostAddress -OpenBrowser $false" in text
    assert "System.Windows.Forms" in text
    assert "POVERTY_KILLER Operator Launcher" in text
    assert "Start backend" in text
    assert "Stop backend" in text
    assert "Restart backend" in text
    assert "Open operator UI" in text
    assert "Refresh status" in text
    assert "Copy diagnostics" in text
    assert "Backend may be stale. Restart recommended." in text
    assert "Restart required after update" in text
    assert "/operator/health" in text
    assert "/operator/status" in text
    assert "/operator/intent/paper/start" not in text
    assert "broker mutation" in text
    assert "live enablement" in text
    assert "real-money enablement" in text


def test_desktop_vbs_entrypoint_opens_visible_launcher_not_browser_only():
    text = Path("scripts/open_operator_console_hidden.vbs").read_text(encoding="utf-8")

    assert "open_operator_console.ps1" in text
    assert "open_operator_console_hidden.ps1" not in text
    assert "-STA" in text
    assert "open_operator_console.ps1" in text


def test_operator_ui_assets_are_cache_busted_for_desktop_launcher():
    text = Path("ui/operator-control-panel/index.html").read_text(encoding="utf-8")

    assert f"styles.css?v={OPERATOR_UI_VERSION}" in text
    assert f"mock-data.js?v={OPERATOR_UI_VERSION}" in text
    assert f"app.js?v={OPERATOR_UI_VERSION}" in text
    assert "operator-credential-hotfix-20260531" not in text
