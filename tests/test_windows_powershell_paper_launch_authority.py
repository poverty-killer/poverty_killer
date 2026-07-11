from __future__ import annotations

from pathlib import Path


SCRIPT = Path("scripts/run_bounded_paper.ps1")


def _script_text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_windows_powershell_paper_launcher_exists_and_defaults_to_preflight_only():
    text = _script_text()

    assert SCRIPT.exists()
    assert "[switch]$Run" in text
    assert "[switch]$ApproveAutonomousPaper" in text
    assert "Preflight passed. No autonomous PAPER run requested." in text
    assert "AUTONOMOUS_PAPER_APPROVAL_REQUIRED" in text


def test_launcher_sets_required_runtime_environment_in_same_process():
    text = _script_text()

    assert '$env:APCA_API_BASE_URL = $PaperEndpoint' in text
    assert '$env:POVERTY_KILLER_EXECUTION_BROKER = "alpaca_paper"' in text
    assert '$env:POVERTY_KILLER_MARKET_DATA_PROVIDERS = $MarketDataProviders' in text
    assert '$env:POVERTY_KILLER_CRYPTO_MARKET_DATA_PROVIDERS = $CryptoMarketDataProviders' in text
    assert '$env:POVERTY_KILLER_RUNTIME_WATCHLIST = $Watchlist' in text


def test_launcher_fails_closed_on_live_endpoint_internal_paper_and_missing_provider_config():
    text = _script_text()

    assert "LIVE_ENDPOINT_BLOCKED" in text
    assert "EXECUTION_BROKER_NOT_ALPACA_PAPER" in text
    assert "ALPACA_PAPER_ADAPTER_NOT_SELECTED" in text
    assert "INTERNAL_PAPER_SELECTED" in text
    assert "MISSING_MARKET_DATA_PROVIDER_CONFIG" in text
    assert "PAPER_PREFLIGHT_FAILED" in text


def test_launcher_uses_get_only_preflight_before_bounded_run():
    text = _script_text()

    preflight_index = text.index("collect_alpaca_paper_read_only_preflight_truth")
    start_process_index = text.index("Start-Process")

    assert preflight_index < start_process_index
    assert "POST_count" in text
    assert "MUTATION_OCCURRED" in text
    assert "LIVE_ENDPOINT_USED" in text
    assert "alpaca_paper_preflight_account_pin_status" in text
    assert 'account_pin["status"] != "PASS"' in text
    assert 'failures.append(account_pin["reason_code"])' in text
    assert "account_pin_verified" in text


def test_launcher_passes_duration_to_runtime_for_graceful_shutdown_accounting():
    text = _script_text()

    assert '"--duration-seconds", "$DurationSeconds"' in text
    assert "($DurationSeconds + 30) * 1000" in text
    assert "did not exit gracefully within 30 seconds" in text


def test_launcher_prints_child_log_paths_before_start_for_external_supervisor():
    text = _script_text()

    start_index = text.index("Starting bounded Alpaca PAPER run")
    process_index = text.index("Start-Process")
    child_log_block = text[start_index:process_index]

    assert 'Write-Host "stdout: $stdoutPath"' in child_log_block
    assert 'Write-Host "stderr: $stderrPath"' in child_log_block


def test_launcher_runs_preflight_from_temp_python_file_not_python_dash_c():
    text = _script_text()

    preflight_index = text.index("Running Alpaca PAPER launch preflight...")
    fail_closed_index = text.index('Fail-Closed "PAPER_PREFLIGHT_FAILED"')
    preflight_block = text[preflight_index:fail_closed_index]

    assert "& $PythonPath -c $preflightCode" not in text
    assert '$tempPreflightPath = Join-Path ([System.IO.Path]::GetTempPath())' in preflight_block
    assert "poverty_killer_preflight_{0}.py" in preflight_block
    assert "[System.IO.File]::WriteAllText($tempPreflightPath, $preflightCode" in preflight_block
    assert "& $PythonPath $tempPreflightPath" in preflight_block
    assert "Remove-Item -LiteralPath $tempPreflightPath" in preflight_block
    assert "sys.path.insert(0, os.getcwd())" in text


def test_launcher_does_not_print_or_embed_raw_secret_values():
    text = _script_text().lower()

    assert "print($env:apca_api_secret_key" not in text
    assert "write-host $env:apca_api_secret_key" not in text
    assert "write-output $env:apca_api_secret_key" not in text
    assert "<paper secret>" not in text
    assert "raw secret" not in text
