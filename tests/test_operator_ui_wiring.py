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
    assert "provider_mode=" in text
    assert "model_quality=" in text
    assert "reasoning_policy=" in text
    assert "governance_suitable=" in text
    assert "Chief Quant Advisor + Quant Engineer + Trading Systems Auditor + Operator Guide" in text


def test_command_center_has_paper_launch_control_and_safe_duration_options():
    text = _app_text()

    assert "PAPER Launch Control" in text
    assert "data-paper-watchlist" in text
    assert "data-paper-duration" in text
    assert "data-paper-duration-amount" in text
    assert "data-paper-duration-unit" in text
    assert "data-paper-confirm-no-manual-trades" in text
    assert "7 days" in text
    assert "604800" in text
    assert "/operator/intent/paper/start" in text
    assert "Start Bounded PAPER Run" in text
    assert "Portfolio Snapshot" in text
    assert "Current Assets / Positions Preview" in text
    assert "AI Quant Advisor" in text


def test_historical_test_control_is_visible_and_honest():
    text = _app_text()

    assert "[\"historical\", \"4-Month Test\"]" in text
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
    assert '["positions", "open_run_paper"' in text
    assert '["positions", "open_orders_preview_table"' in text


def test_provider_setup_uses_beginner_safe_credential_labels():
    text = _app_text()

    assert "Local credential vault" in text
    assert "stored on this computer only" in text
    assert "Raw secrets are hidden and not sent to AI" in text
    assert "Local store" not in text
    assert "validation passed" in text
    assert "validation failed" in text
    assert "alpaca_paper" in text
    assert "APCA_API_KEY_ID" in text
    assert "APCA_API_SECRET_KEY" in text
    assert "APCA_API_BASE_URL" in text
    assert "/operator/credentials/save" in text
    assert "reason=${reason}" in text
    assert "received_field_presence" in text


def test_ai_panel_shows_model_quality_and_lower_reasoning_warning():
    text = _app_text()

    assert "Provider Mode" in text
    assert "Model Quality" in text
    assert "Model Policy" in text
    assert "Model quality tier" in text
    assert "Suitable for governance" in text
    assert "High-reasoning model not configured. Quant/governance answers are limited." in text
    assert "Lower-reasoning model active. Do not use this for final quant/risk/live-readiness decisions." in text
    assert "HIGH_REASONING" in text
    assert "FALLBACK_ONLY_LIMITED" in text


def test_ai_prompt_chips_exist_for_required_operator_workflows():
    text = _app_text()

    for prompt in [
        "Explain this page.",
        "What do I do next?",
        "Why is PAPER run blocked?",
        "Explain my positions.",
        "Plan my PAPER run.",
        "Audit readiness.",
        "Draft Codex packet request.",
    ]:
        assert prompt in text


def test_credential_save_captures_inputs_before_saving_rerender():
    text = _app_text()
    start = text.index("async function handleCredentialAction")
    capture = text.index("pendingCredentials = credentialFormValues(providerId)", start)
    saving_status = text.index("credentialActionStatus[providerId] = `${action === \"save\" ? \"saving\"", start)
    saving_render = text.index("renderScreens(activeScreenId);", saving_status)

    assert capture < saving_status < saving_render
    assert "credentials: pendingCredentials" in text


def test_evidence_graph_timeout_is_optional_for_provider_setup():
    text = _app_text()

    assert "OPTIONAL_BACKEND_ENDPOINTS" in text
    assert '"/operator/research/evidence-graph"' in text
    assert "EVIDENCE_GRAPH_DEGRADED" in text
    assert "Research OS evidence graph degraded; credential setup remains usable." in text


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
