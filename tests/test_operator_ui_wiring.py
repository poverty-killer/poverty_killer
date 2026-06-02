from __future__ import annotations

from pathlib import Path


APP_JS = Path("ui/operator-control-panel/app.js")
MOCK_JS = Path("ui/operator-control-panel/mock-data.js")
STYLES_CSS = Path("ui/operator-control-panel/styles.css")


def _app_text() -> str:
    return APP_JS.read_text(encoding="utf-8")


def test_ask_quant_chief_drawer_has_visible_question_flow():
    text = _app_text()

    assert "data-ai-chief-open" in text
    assert "ai-chief-dock" in text
    assert "data-ai-chief-wide" in text
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
    assert "Chief Quant Advisor + Quant Engineer + Trading Systems Auditor + Trading Strategist + Market Research Chief + Risk Officer + Execution/TCA Auditor + Operator Guide" in text
    assert "Advisor Answer" in text
    assert "Next Step" in text
    assert "Compact Evidence Summary" in text
    assert "Advanced details: context, provider diagnostics, safety flags" in text
    assert "data-ai-chat-scroll-container" in text
    assert "ai-chief-response-end" in text
    assert "scheduleAiOverlayScroll" in text
    assert "requestAnimationFrame" in text
    assert "AI provider error. Local fallback can still explain operator status." in text
    assert "DETERMINISTIC FALLBACK - not a full AI quant reasoning response." in text
    assert "More prompts" in text
    assert "AI_PRIMARY_PROMPT_LIMIT" in text
    overlay = text[text.index("function renderAiChiefOverlay"):text.index("function setAiOverlayOpen")]
    assert overlay.index("Advisor Answer") < overlay.index("renderAiCollapsedDetails")


def test_commercial_navigation_groups_keep_all_pages_accessible():
    text = _app_text()

    assert "NAV_GROUPS" in text
    for group in ["Operate", "Understand", "Setup", "Research / Proof", "System"]:
        assert group in text
    for page_id in [
        "positions",
        "command",
        "action",
        "activity",
        "runs",
        "pnl",
        "decision",
        "market",
        "risk",
        "alerts",
        "providers",
        "ai",
        "historical",
        "research",
        "world",
        "diagnostics",
        "system",
        "audit",
        "live",
    ]:
        assert f'"{page_id}"' in text
    assert "main.innerHTML = screens.map" in text
    assert "group.items.map" in text
    assert "showScreen(button.dataset.screen)" in text


def test_ai_advisor_is_docked_and_resizes_layout_not_overlay_first():
    app_text = _app_text()
    css = STYLES_CSS.read_text(encoding="utf-8")

    assert "syncAiDockedState" in app_text
    assert "ai-docked-open" in app_text
    assert "ai-docked-wide" in app_text
    assert "shouldOpenAiDockFromUrl" in app_text
    assert "aiDock" in app_text
    assert "data-ai-chat-scroll-container" in app_text
    assert "ai-chief-response-end" in app_text
    assert "body.ai-docked-open .shell" in css
    assert "calc(100vw - var(--ai-dock-width))" in css
    assert ".ai-chief-drawer.open" in css
    assert "pointer-events: auto" in css
    assert ".ai-chief-body" in css
    assert "overflow-y: auto" in css
    assert ".ai-chief-backdrop.open" in css


def test_ai_prompts_are_limited_with_more_prompts_expander():
    text = _app_text()

    assert "primaryAiPrompts" in text
    assert "moreAiPrompts" in text
    assert "AI_PRIMARY_PROMPT_LIMIT = 6" in text
    assert "ai-more-prompts" in text
    assert "More prompts" in text
    assert "AI_QUICK_PROMPTS.slice(0, AI_PRIMARY_PROMPT_LIMIT)" in text


def test_portfolio_home_has_commercial_cockpit_lane_and_primary_actions():
    text = _app_text()
    css = STYLES_CSS.read_text(encoding="utf-8")

    assert 'data-home-section="portfolio-cockpit"' in text
    assert "Account Cockpit" in text
    assert "Broker-confirmed PAPER account view first" in text
    assert "Ask Docked Advisor" in text
    assert "primary-action" in text
    assert ".cockpit-hero" in css
    assert ".launch-control-layout" in css
    assert ".confirmation-grid" in css


def test_header_compacts_backend_degraded_status_and_keeps_details_in_diagnostics():
    text = _app_text()

    render_topbar = text[text.index("function renderTopBar"):text.index("function paperLaunchDisabledReason")]
    diagnostics = text[text.index("function renderDiagnostics"):text.index("function renderLive")]

    assert "Backend: OK" in text
    assert "Backend: Degraded -" in text
    assert "View details" in render_topbar
    assert "data-screen-shortcut=\"diagnostics\"" in render_topbar
    assert "backendDegradedSummary()" not in render_topbar
    assert "Backend endpoint details" in diagnostics
    assert "backendFailureRows" in text
    assert "Failed endpoints" in diagnostics


def test_responsive_css_wraps_header_tables_cards_and_ai_drawer():
    text = STYLES_CSS.read_text(encoding="utf-8")

    assert ".status-detail-link" in text
    assert "overflow-x: hidden" in text
    assert ".table-wrap" in text
    assert "overflow-x: auto" in text
    assert ".ai-chief-body" in text
    assert "scroll-behavior: smooth" in text
    assert ".two-column-summary" in text
    assert "@media (max-width: 640px)" in text


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


def test_ai_provider_model_router_controls_are_visible_and_cost_labeled():
    text = _app_text()

    assert "AI Routing Settings" in text
    assert "Settings source:" in text
    assert "PERSISTED_LOCAL_SETTINGS" in text
    assert "DEFAULT_SETTINGS" in text
    assert "IN_MEMORY_UNSAVED" in text
    assert ".operator_config/ai_router_settings.json" in text
    assert "data-ai-route-default-mode" in text
    assert "data-ai-active-provider" in text
    assert "data-ai-active-model" in text
    assert "data-ai-light-provider" in text
    assert "data-ai-high-provider" in text
    assert "data-ai-local-base-url" in text
    assert "data-ai-local-model" in text
    assert "Save AI routing settings" in text
    assert "Test provider connection" in text
    assert "Generate Supreme Board Packet" in text
    assert "Approve one high-reasoning call" in text
    assert "Use local guide only" in text
    assert "Use selected light model" in text
    assert "Use selected local model" in text
    assert "High-reasoning API uses separate paid provider billing." in text
    assert "ChatGPT Pro web subscription does not automatically provide API quota." in text
    assert "Supreme Board Packet uses manual ChatGPT Pro workflow." in text
    assert "Local Guide is free and deterministic." in text
    assert "/operator/ai/router/settings" in text
    assert "/operator/ai/providers/validate" in text
    assert "/operator/ai/supreme-board-packet" in text


def test_ai_ask_uses_active_router_provider_and_refreshes_after_settings_save():
    text = _app_text()

    assert "function aiAskRoutingPayload" in text
    assert "isExternalAiApiProvider(activeProvider)" in text
    assert "providerId: activeProvider" in text
    assert "route_mode: route.routeMode" in text
    assert "provider_id: route.providerId" in text
    assert "model_name: route.modelName" in text
    save_fn = text[text.index("async function saveAiRoutingSettings"):text.index("async function validateSelectedAiProvider")]
    assert "data = await loadData()" in save_fn
    assert "renderTopBar()" in save_fn
    assert "Active Router" in text
    assert "active ${activeProviderLabel}" in text


def test_portfolio_ui_accepts_exact_unavailable_statuses_not_only_old_generic_status():
    text = _app_text()

    assert "function isPortfolioUnavailableStatus" in text
    for status in ["BROKER_READ_FAILED", "AUTH_FAILED", "MISSING_CREDENTIALS", "BACKEND_DEGRADED", "STALE_BACKEND"]:
        assert status in text
    assert "portfolio.status === \"BROKER_DATA_UNAVAILABLE\"" not in text

    for provider_id in [
        "openai",
        "anthropic",
        "gemini",
        "xai_grok",
        "deepseek",
        "kimi_moonshot",
        "local_openai_compatible",
        "deterministic_local",
        "supreme_board_packet",
    ]:
        assert provider_id in text


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
