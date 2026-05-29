from __future__ import annotations

from pathlib import Path


APP_JS = Path("ui/operator-control-panel/app.js")
MOCK_JS = Path("ui/operator-control-panel/mock-data.js")


def _app_text() -> str:
    return APP_JS.read_text(encoding="utf-8")


def test_ask_quant_chief_drawer_has_visible_question_flow():
    text = _app_text()

    assert "data-ai-chief-open" in text
    assert "data-ai-chief-question" in text
    assert "data-ai-chief-ask" in text
    assert "data-ai-chief-clear" in text
    assert "/operator/ai/ask" in text
    assert "Ask a page-aware question" in text
    assert "DETERMINISTIC_FALLBACK_NO_MODEL_CALL" in text


def test_command_center_has_paper_launch_control_and_safe_duration_options():
    text = _app_text()

    assert "PAPER Launch Control" in text
    assert "data-paper-watchlist" in text
    assert "data-paper-duration" in text
    assert "data-paper-confirm-no-manual-trades" in text
    assert "[300, 900, 1800, 3600]" in text
    assert "/operator/intent/paper/start" in text
    assert "Start Bounded PAPER Run" in text
    assert "Portfolio Snapshot" in text
    assert "Current Assets / Positions Preview" in text
    assert "AI Quant Advisor" in text


def test_historical_test_control_is_visible_and_honest():
    text = _app_text()

    assert "[\"historical\", \"Historical Tests\"]" in text
    assert "Historical Alpaca Test" in text
    assert "data-historical-preset" in text
    assert "last_4_months" in text
    assert "/operator/historical-tests/run" in text
    assert "unknown - no simulation evidence" in text


def test_ui_control_inventory_declares_statuses_and_no_broken_defaults():
    text = _app_text()

    assert "buildUiControlInventory" in text
    assert "UI Wiring Audit" in text
    assert "DISABLED_WITH_REASON" in text
    assert "NOT_IMPLEMENTED_VISIBLE" in text
    assert "NO_BROKEN_CONTROLS_DECLARED" in text
    assert '["global", "ask_quant_chief"' in text
    assert '["command", "home_ai_ask"' in text
    assert '["positions", "open_orders_preview_table"' in text


def test_provider_setup_uses_beginner_safe_credential_labels():
    text = _app_text()

    assert "Local credential vault" in text
    assert "stored on this computer only" in text
    assert "Raw secrets are hidden and not sent to AI" in text
    assert "Local store" not in text
    assert "validation passed" in text
    assert "validation failed" in text


def test_visible_mutating_controls_are_governed_or_disabled_not_direct_trades():
    text = _app_text().lower()

    forbidden_endpoint_fragments = [
        "/api/flatten",
        "/api/mode/",
        "/operator/intent/live/start\" data-intent",
        "data-intent=\"force",
        "data-intent=\"buy",
        "data-intent=\"sell",
        "data-intent=\"cancel",
        "data-intent=\"liquidate",
    ]
    for fragment in forbidden_endpoint_fragments:
        assert fragment not in text
    assert "broker execution unavailable to ai" in text
    assert "does not start paper / does not trade" in text


def test_mock_data_is_labeled_as_sample_not_runtime_truth_and_has_no_secrets():
    text = MOCK_JS.read_text(encoding="utf-8")

    assert "MOCK_SAMPLE_NO_RUNTIME" in text
    assert "MOCK_SAMPLE_NOT_BROKER_TRUTH" in text
    assert "sk-" not in text
    assert "raw_secret" not in text.lower()
