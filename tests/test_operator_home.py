from __future__ import annotations

from pathlib import Path


APP_JS = Path("ui/operator-control-panel/app.js")
CONTRACTS_JSON = Path("ui/operator-control-panel/contracts.json")


def _app_text() -> str:
    return APP_JS.read_text(encoding="utf-8")


def test_command_center_home_contains_operator_answer_sections():
    text = _app_text()

    required_sections = [
        "Launch Readiness",
        "PAPER Launch Control",
        "Portfolio Snapshot",
        "Current Assets / Positions Preview",
        "Open Orders Preview",
        "Bot Activity / What It Is Considering",
        "AI Quant Advisor",
        "Buttons / Controls Status",
    ]
    for section in required_sections:
        assert section in text

    assert 'data-home-section="launch-readiness"' in text
    assert 'data-home-section="portfolio-snapshot"' in text
    assert 'data-home-section="positions-preview"' in text
    assert 'data-home-section="open-orders-preview"' in text
    assert 'data-home-section="bot-activity"' in text
    assert 'data-home-section="ai-quant-advisor"' in text
    assert 'data-home-section="ui-wiring-summary"' in text


def test_home_paper_launch_control_requires_all_safety_confirmations():
    text = _app_text()

    assert "data-paper-watchlist" in text
    assert "BTC/USD\", \"ETH/USD\", \"SOL/USD" in text
    assert "[300, 900, 1800, 3600]" in text
    assert "data-paper-confirm-paper" in text
    assert "data-paper-confirm-live-locked" in text
    assert "data-paper-confirm-real-money-blocked" in text
    assert "data-paper-confirm-no-manual-trades" in text
    assert "/operator/intent/paper/start" in text
    assert "Confirm PAPER-only, live locked, real-money blocked, and no manual trades" in text
    assert "paperLaunchDisabledReason" in text


def test_home_portfolio_and_position_preview_are_honest_when_unavailable_or_empty():
    text = _app_text()

    assert "No current PAPER positions." in text
    assert "broker data unavailable" in text.lower()
    assert "No open broker-confirmed orders." in text
    assert "broker-confirmed" in text
    assert "unavailable" in text
    assert "fake" not in " ".join([
        "Portfolio Snapshot",
        "Current Assets / Positions Preview",
        "Open Orders Preview",
    ]).lower()


def test_home_ai_advisor_is_visible_and_uses_safe_ai_ask_endpoint():
    text = _app_text()

    assert "data-home-ai-question" in text
    assert "data-home-ai-ask" in text
    assert "data-home-ai-clear" in text
    assert "data-home-ai-prompt" in text
    assert "Ask AI Quant Advisor" in text
    assert "/operator/ai/ask" in text
    assert "DETERMINISTIC_FALLBACK_NO_MODEL_CALL" in text
    assert "can_execute=false" in text
    assert "No broker calls" in text
    assert "no live enablement" in text.lower()
    assert "no real-money enablement" in text.lower()


def test_home_control_inventory_covers_required_pages_and_forbidden_controls_absent():
    text = _app_text()

    required_inventory_fragments = [
        '["command", "paper_start"',
        '["command", "home_ai_ask"',
        '["activity", "paper_stop"',
        '["positions", "positions_preview_table"',
        '["positions", "open_orders_preview_table"',
        '["providers", `credential_save_${providerId}`',
        '["ai_overlay", "ai_ask"',
    ]
    for fragment in required_inventory_fragments:
        assert fragment in text

    lower = text.lower()
    forbidden_active_fragments = [
        'data-intent="buy',
        'data-intent="sell',
        'data-intent="cancel',
        'data-intent="flatten',
        'data-intent="liquidate',
        'data-intent="force',
        '/api/flatten',
    ]
    for fragment in forbidden_active_fragments:
        assert fragment not in lower


def test_operator_home_contract_is_recorded():
    text = CONTRACTS_JSON.read_text(encoding="utf-8")

    assert '"operator_home_contract"' in text
    assert '"first_screen": "Command Center"' in text
    assert '"home_ai_endpoint": "/operator/ai/ask"' in text
    assert '"paper_start_endpoint": "/operator/intent/paper/start"' in text
    assert '"fake_broker_truth_allowed": false' in text
