from __future__ import annotations

from pathlib import Path


HIDDEN_LAUNCHER = Path("scripts/open_operator_console_hidden.ps1")


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
    assert "[int]$response.StatusCode -lt 500" not in text

    browser_open = 'Start-Process "$BaseUrl/operator-ui/?v=desktop-launcher"'
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
