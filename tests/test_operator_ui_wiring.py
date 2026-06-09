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
    assert "data-ai-chief-clear" in text
    assert "data-ai-answer-mode-ask" in text
    assert "DETERMINISTIC" in text
    assert "AI_CHAT_MODEL" in text
    assert "AI_REASONING_STRATEGY" in text
    assert "Deterministic" in text
    assert "AI Chat Model" in text
    assert "AI Reasoning" in text
    assert "/operator/ai/ask" in text
    assert "Ask what is blocking PAPER, whether the bot is ready, or what to do next..." in text
    assert "aiConversation" in text
    assert "appendAiMessage" in text
    assert "replaceAiMessage" in text
    assert "renderAiConversationThread" in text
    assert "data-ai-assistant-loading" in text
    assert "Asking Chief Quant Advisor..." in text
    assert "data-ai-answer-card" in text
    assert "data-ai-copy-answer" in text
    assert "Copy answer" in text
    assert "Next step:" in text
    assert "Evidence Summary" in text
    assert "Advanced details" in text
    assert "Known Facts" in text
    assert "Missing Evidence" in text
    assert "data-ai-chat-scroll-container" in text
    assert "ai-chief-response-end" in text
    assert "scheduleAiOverlayScroll" in text
    assert "requestAnimationFrame" in text
    assert "Type a question first." in text
    assert "Provider error shown. Local fallback is labeled; no silent provider switch occurred." in text
    assert "Deterministic local fallback. Limited advisory answer." in text
    assert "Fallback:" in text
    assert "More prompts" in text
    assert "AI_PRIMARY_PROMPT_LIMIT" in text
    overlay = text[text.index("function renderAiChiefOverlay"):text.index("function setAiOverlayOpen")]
    assert overlay.index("renderAiConversationThread") < overlay.index("ai-composer")
    message_renderer = text[text.index("function renderAiConversationMessage"):text.index("function renderAiConversationThread")]
    details_renderer = text[text.index("function renderAiCollapsedDetails"):text.index("function renderAiConversationMessage")]
    assert "renderAiNextStep(result)" not in message_renderer
    assert "renderAiEvidenceSummary(result, context)" not in message_renderer
    assert "renderAiNextStep(result)" in details_renderer
    assert "renderAiEvidenceSummary(result, context)" in details_renderer


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
    assert ".ai-chat-thread" in css
    assert "overflow-y: auto" in css
    assert "overflow: hidden" in css
    assert ".ai-chief-backdrop.open" in css
    assert "--ai-dock-width: clamp(360px, 28vw, 420px)" in css
    assert "resize: horizontal" in css
    assert ".compact-actions" in css


def test_ai_prompts_are_limited_with_more_prompts_expander():
    text = _app_text()

    assert "primaryAiPrompts" in text
    assert "moreAiPrompts" in text
    assert "AI_PRIMARY_PROMPT_LIMIT = 4" in text
    assert "What is blocking PAPER?" in text
    assert "Can I start PAPER?" in text
    assert "Summarize portfolio truth" in text
    assert "Draft Codex packet" in text
    assert "ai-more-prompts" in text
    assert "More prompts" in text
    assert "AI_QUICK_PROMPTS.slice(0, AI_PRIMARY_PROMPT_LIMIT)" in text
    assert "selectAiQuestion(aiPrompt.dataset.aiChiefPrompt)" in text
    assert "const bullets = aiEvidenceBullets" in text
    assert "uniquePrompts(bullets).slice(0, 3)" in text


def test_ai_active_provider_controls_are_clear_and_no_silent_fallback_markers():
    text = _app_text()

    assert "Active provider" in text
    assert "Active model" in text
    assert "Last answer source" in text
    assert "Last provider error" in text
    assert "Selected active provider" in text
    assert "Default router mode" in text
    assert "Use DeepSeek now" in text
    assert "Use OpenAI now" in text
    assert "Use Supreme Board packet mode" in text
    assert "data-ai-use-provider-now=\"deepseek\"" in text
    assert "data-ai-use-provider-now=\"openai\"" in text
    assert "data-ai-use-supreme-board" in text
    assert "active_provider: id" in text
    assert "no paid call occurred" in text
    assert "safe local fallback answered this question" in text
    assert "provider call failed" in text
    assert "Safe local fallback" in text
    assert "LOCAL_DETERMINISTIC" in text
    assert "modelCallAttempted" in text
    assert "modelCallOccurred" in text
    assert "providerResponseReceived" in text
    assert "fallbackReason" in text
    assert "displaySourceLabel" in text
    assert "effectiveAnswerMode" in text
    assert "ai_call_trace" in text
    assert "normalizeAiCallTrace" in text
    assert "AI Call Trace" in text
    assert "Safety filter triggered" in text
    assert "Challenge echoed" in text
    assert "Safe local fallback | ${fallbackSource} | provider call failed" in text
    assert "${providerLabel} answered | ${modelName} | ${source}" in text


def test_ai_packet_output_is_collapsed_and_copyable_by_default():
    text = _app_text()

    assert "renderAiPacketPanel" in text
    assert "View packet" in text
    assert "Copy packet" in text
    assert "data-ai-copy-packet" in text
    assert "packetText" in text
    assert "Supreme Board packet is ready. Use View packet" in text
    assert "Draft packet is ready. Use View packet" in text


def test_ai_chat_thread_has_user_loading_answer_and_latest_anchor_slots():
    text = _app_text()

    assert "aiConversation" in text
    assert "appendAiMessage({ role: \"user\", status: \"complete\"" in text
    assert "status: \"loading\"" in text
    assert "data-ai-assistant-loading" in text
    assert "replaceAiMessage(loadingMessage.id" in text
    assert "data-ai-answer-card" in text
    assert "data-ai-copy-answer" in text
    assert "data-ai-chat-scroll-container" in text
    assert "ai-chief-response-end" in text
    assert "container.scrollTop = container.scrollHeight" in text


def test_ai_evidence_labels_ready_idle_as_state_not_blocker():
    text = _app_text()

    assert "function aiReadyIdleNoActiveRuntime" in text
    assert "Current state: READY_IDLE_NO_ACTIVE_RUNTIME" in text
    assert "Current blocker: ${blocker}" in text
    assert "value === \"READY_IDLE_NO_ACTIVE_RUNTIME\"" in text


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

    assert "Run PAPER Command Center" in text
    assert "runPaperOperatorState" in text
    assert "normalizeRunPaperOperatorState" in text
    assert "normalizePaperCredentialSetup" in text
    assert "data-run-paper-command-center" in text
    assert "data-run-paper-top-status" in text
    assert "data-run-paper-start-control" in text
    assert "data-run-paper-start-state" in text
    assert "data-run-paper-advanced" in text
    assert "run-paper-proof-grid" in text
    assert "Start readiness" in text
    assert "Broker / portfolio truth" in text
    assert "Credential Setup + Read-Only Preflight Gate" in text
    assert "data-paper-credential-setup" in text
    assert "data-paper-credential-field" in text
    assert "data-paper-credential-top-message" in text
    assert "data-paper-credential-next-action" in text
    assert "data-paper-preflight-boundary" in text
    assert "data-paper-credential-advanced" in text
    assert "APCA_API_KEY_ID" in text
    assert "APCA_API_SECRET_KEY" in text
    assert ".operator_secrets/provider_credentials.json" in text
    assert "Values hidden" in text
    assert "Do not commit" in text
    assert "Read-only PAPER preflight not run" in text
    assert "requires explicit approval before Alpaca is called" in text
    assert "account, open orders, and positions" in text
    assert "will not place, cancel, replace, liquidate, enable live, enable real money, or start PAPER" in text
    assert "Next safe action:" in text
    assert "Advanced endpoint and start proof" in text
    assert "Raw blocker code is kept here" in text
    assert "PAPER Launch Control" in text
    assert "Alpaca PAPER endpoint" in text
    assert "Endpoint source" in text
    assert "paperEndpointStatus" in text
    assert "paperEndpointOperatorAction" in text
    assert "paperEndpointDisplay" in text
    assert "paperEndpointFamily" in text
    assert "paperEndpointHost" in text
    assert "paperEndpointBlockerCode" in text
    assert "alpacaLiveEndpointBlocked" in text
    assert "Endpoint action:" in text
    assert "Endpoint display" in text
    assert "Endpoint family" in text
    assert "Endpoint host" in text
    assert "Endpoint proof:" in text
    assert "Live endpoint blocked" in text
    assert "data-paper-watchlist" in text
    assert "data-paper-duration" in text
    assert "data-paper-duration-max" in text
    assert "data-paper-duration-amount" in text
    assert "data-paper-duration-unit" in text
    assert "data-paper-confirm-no-manual-trades" in text
    assert "1 day" in text
    assert "86400" in text
    assert "Longer multi-day runs require separate approval/readiness." in text
    assert "Ready. No PAPER run currently attached." in text
    assert "Last historical refusal" in text
    assert "Selected duration exceeds the current runner authority max" in text
    assert "Custom minutes / hours" in text
    assert "604800" not in text
    assert "/operator/intent/paper/start" in text
    assert "Start Bounded PAPER Run" in text
    assert "Portfolio Snapshot" in text
    assert "Current Assets / Positions Preview" in text
    assert "AI Quant Advisor" in text


def test_run_paper_command_center_keeps_raw_codes_and_secrets_out_of_main_ui():
    text = _app_text()
    css = STYLES_CSS.read_text(encoding="utf-8")

    assert "canRun.reason" in text
    assert "Advanced endpoint and start proof" in text
    assert "runPaperAdvancedRows" in text
    assert "paper_endpoint_blocker_code" in text
    assert "secrets_values_exposed" in text
    assert "rawSecretValuesIncluded" in text
    assert "paperCredentialSetup" in text
    assert "readOnlyPreflightAuthorized" in text
    assert "alpacaNetworkCallOccurred" in text
    assert "accountRequestOccurred" in text
    assert "openOrdersRequestOccurred" in text
    assert "positionsRequestOccurred" in text
    assert "replaceOccurred" in text
    assert "broker_mutation_occurred" in text
    assert "trading_mutation_occurred" in text
    assert "orderSubmissionOccurred" in text
    assert "liquidationOccurred" in text
    assert "No broker mutation" in text
    assert ".run-paper-status-banner" in css
    assert ".run-paper-proof-grid" in css
    assert ".run-paper-proof-tile" in css
    assert ".credential-preflight-panel" in css
    assert ".credential-preflight-field" in css


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
    assert '["command", "home_ai_answer_modes"' in text
    assert '["positions", "open_run_paper"' in text
    assert '["positions", "open_orders_preview_table"' in text


def test_provider_setup_uses_beginner_safe_credential_labels():
    text = _app_text()

    assert "Local credential vault" in text
    assert "stored on this computer only" in text
    assert "Raw secrets are hidden and not sent to AI" in text
    assert "Local store" not in text
    assert "credential presence confirmed" in text
    assert "validation failed" in text
    assert "alpaca_paper" in text
    assert "APCA_API_KEY_ID" in text
    assert "APCA_API_SECRET_KEY" in text
    assert "APCA_API_BASE_URL" in text
    assert "/operator/credentials/save" in text
    assert "reason=${reason}" in text
    assert "received_field_presence" in text


def test_keys_providers_layout_groups_cards_and_reconciles_table_truth():
    text = _app_text()
    css = STYLES_CSS.read_text(encoding="utf-8")

    assert "Trading / Broker Data" in text
    assert "AI Providers" in text
    assert "Local / Advanced" in text
    assert "PROVIDER_GROUPS" in text
    assert "provider-groups" in text
    assert "provider-group-grid" in text
    assert "Provider Table" in text
    assert "mergeCredentialTruthIntoProviderReadiness" in text
    assert "credentialSource" in text
    assert "providerDisplaySource(provider)" in text
    assert "MISSING_CREDENTIALALS" not in text
    assert ".provider-group-grid" in css
    assert ".provider-table-card .table" in css
    assert "overflow-x: hidden" in css


def test_provider_truth_endpoints_use_long_backend_timeout():
    text = _app_text()
    heavy_block = text[text.index("const HEAVY_BACKEND_ENDPOINTS"):text.index("const OPTIONAL_BACKEND_ENDPOINTS")]

    assert "HEAVY_BACKEND_FETCH_TIMEOUT_MS = 30000" in text
    for endpoint in [
        "/operator/providers",
        "/operator/providers/readiness",
        "/operator/portfolio",
        "/operator/launch-readiness",
    ]:
        assert endpoint in heavy_block


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
    assert "function aiAskRoutingPayloadForMode" in text
    assert "isExternalAiApiProvider(activeProvider)" in text
    assert "providerId: activeProvider" in text
    assert "answer_mode: answerMode" in text
    assert "route_mode: route.routeMode" in text
    assert "provider_id: route.providerId" in text
    assert "model_name: route.modelName" in text
    save_fn = text[text.index("async function saveAiRoutingSettings"):text.index("async function validateSelectedAiProvider")]
    assert "data = await loadData()" in save_fn
    assert "renderTopBar()" in save_fn
    assert "Active Router" in text
    assert "compactLine = `${currentProviderDisplay} active" in text
    assert "safe local fallback answered this question" in text
    assert "Default router mode" in text


def test_ai_three_answer_mode_buttons_send_explicit_answer_mode():
    text = _app_text()
    css = STYLES_CSS.read_text(encoding="utf-8")

    assert "renderAiAnswerModeButtons" in text
    assert 'data-ai-answer-mode-ask="${escapeHtml(scope)}:${escapeHtml(mode)}"' in text
    assert "AI_ANSWER_MODES.DETERMINISTIC" in text
    assert "AI_ANSWER_MODES.CHAT" in text
    assert "AI_ANSWER_MODES.REASONING" in text
    assert "answer_mode: answerMode" in text
    assert "normalizeAiAnswerMode" in text
    assert "our bot/local truth, no provider call" in text
    assert "configured model answers" in text
    assert "high-reasoning advisory path" in text
    assert "selectAiQuestion(aiPrompt.dataset.aiChiefPrompt)" in text
    assert "askAiChiefQuestion(aiPrompt.dataset.aiChiefPrompt)" not in text
    assert ".ai-answer-mode-group" in css
    assert ".ai-mode-button.active" in css


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
