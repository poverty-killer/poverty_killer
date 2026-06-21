from __future__ import annotations

from pathlib import Path


APP_JS = Path("ui/operator-control-panel/app.js")
MOCK_JS = Path("ui/operator-control-panel/mock-data.js")
STYLES_CSS = Path("ui/operator-control-panel/styles.css")
LAUNCHER_PS1 = Path("scripts/open_operator_console_hidden.ps1")
VISIBLE_LAUNCHER_PS1 = Path("scripts/open_operator_console.ps1")


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
    for group in ["Watch", "Intelligence", "Operate", "Proof"]:
        assert group in text
    for page_id in [
        "overview",
        "performance",
        "trades",
        "markets",
        "advisor",
        "health",
        "controls",
        "log",
        "connections",
        "command",
        "positions",
        "providers",
        "diagnostics",
    ]:
        assert f'"{page_id}"' in text
    assert '"Activation Proof"' not in text
    for page_id in [
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
    assert "const renderer = renderers[selected] || renderPositions" in text
    assert "main.innerHTML = screens.map" not in text
    assert "group.items.map" in text
    assert "showScreen(button.dataset.screen)" in text


def test_operator_cockpit_is_default_and_has_server_gated_selector_controls():
    text = _app_text()
    css = STYLES_CSS.read_text(encoding="utf-8")
    index = Path("ui/operator-control-panel/index.html").read_text(encoding="utf-8")

    assert "Poverty Killer Operator Cockpit" in index
    assert 'let activeScreenId = "overview"' in text
    assert 'renderScreens("overview")' in text
    assert "/operator/cockpit/capabilities" in text
    assert "/operator/cockpit/asset-mandate" in text
    assert "/operator/cockpit/day-trader-mode" in text
    assert "renderAssetClassSelector" in text
    assert "data-cockpit-asset" in text
    assert "data-cockpit-day-trader" in text
    assert "NEXT_CAPITAL_ONLY_EXISTING_POSITIONS_RIDE" in text
    assert "existingPositionsLiquidated" in text
    assert "brokerMutationOccurred" in text
    assert "strategyMutationOccurred" in text
    assert "liquidation=${result.liquidation_occurred === true}" in text
    assert "Live Alpaca credentials are deliberately not accepted on this screen." in text
    assert "renderConnections" in text
    assert "No manual buy/sell, close, cancel, force-trade, flatten, or liquidation controls exist in this cockpit." in text
    assert ".asset-selector" in css
    assert ".cockpit-truth-banner" in css
    assert ".scan-strip" in css
    assert ".market-chip-grid" in css


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
    assert "Current state: IDLE_NO_ACTIVE_PAPER_RUN" in text
    assert "Current blocker: ${blocker}" in text
    assert "value === \"READY_IDLE_NO_ACTIVE_RUNTIME\"" in text
    assert "READY_FOR_GOVERNED_PAPER" in text


def test_fills_summary_labels_strict_smoke_fee_hydration_skip():
    text = _app_text()

    assert "Fee/activity hydration not authorized for this smoke run." in text
    assert "fee_hydration_skipped" in text
    assert "fee_hydration_skip_reason" in text


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
    assert "Baseline adoption required - existing PAPER positions detected." in text
    assert "Reset is not required" in text
    assert "Position-aware PAPER baseline accepted." in text
    assert "Accept current positions as PAPER baseline" in text
    assert "No liquidation / close / cancel controls" in text
    assert "/operator/paper-baseline/accept" in text
    assert "BLOCK_BASELINE_SYMBOL_TRADES_UNTIL_RUN_LOT_TRACKING" in text
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
    assert "5 days" in text
    assert "432000" in text
    assert "Long-running PAPER stays PAPER-only" in text
    assert "Ready. No PAPER run currently attached." in text
    assert "Last historical refusal" in text
    assert "Selected duration exceeds the current governed PAPER lease max" in text
    assert "Custom minutes / hours / days" in text
    assert "604800" not in text
    assert "/operator/intent/paper/start" in text
    assert "Start Governed PAPER Run" in text
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
    assert "paperBaseline" in text
    assert "data-paper-baseline-panel" in text
    assert "data-paper-baseline-advanced" in text
    assert ".paper-baseline-panel" in css
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


def test_backend_connected_run_paper_never_keeps_mock_authority():
    text = _app_text()

    assert "function reconcileBackendConnectedAuthority" in text
    assert "function runPaperStateHasMockAuthority" in text
    assert "function runPaperSourceMismatchCodes" in text
    assert "OPERATOR_BACKEND_DEGRADED_RUN_PAPER_VIEW" in text
    assert "BACKEND_LAUNCH_READINESS_UNAVAILABLE" in text
    assert "READINESS_SOURCE_MISMATCH" in text
    assert "CREDENTIAL_SOURCE_MISMATCH" in text
    assert "PORTFOLIO_SOURCE_MISMATCH" in text
    assert "SUPERVISOR_SOURCE_MISMATCH" in text
    assert "reconcileBackendConnectedAuthority(next, endpointFailures)" in text
    assert text.index("reconcileBackendConnectedAuthority(next, endpointFailures)") < text.index("mergeCredentialTruthIntoProviderReadiness(next)")
    assert "paperBaselineFromState(data, op)" in text
    assert "renderPaperBaselinePanel(baseline, data.portfolio || {})" in text
    assert "buildCredentialSetupFromBackendState" in text
    assert "credentialSetupWithProviderTruth" in text
    assert "OPERATOR_BACKEND_CREDENTIALS" in text
    assert "OPERATOR_LOCAL_CREDENTIAL_STORE" in text
    assert "Backend source" in text
    assert "canonical_source_order" in text
    assert "paper-control-state > launch-readiness" in text
    assert "function createRequestScheduler" in text
    assert 'path: "/operator/paper-control-state", priority: 0, lane: "critical"' in text
    assert 'path: "/operator/launcher-status", priority: 0, lane: "critical"' in text
    assert "Promise.allSettled" in text
    assert "await Promise.all(endpoints.map" not in text
    assert "REQUEST_LANE_LIMITS" in text
    assert "buildProductionUnavailableState" in text
    assert "let data = clone(mockData)" not in text
    assert "const next = clone(mockData)" not in text
    assert "Max lease seconds" in text
    assert "BACKEND_UNAVAILABLE_RUN_PAPER_VIEW" in text
    assert 'fallback.meta.dataSource = "MOCK_DATA"' not in text
    assert "Operator backend unavailable; broker-confirmed portfolio truth is not loaded." in text
    assert "Disabled: operator backend unavailable; start authority cannot be proven." in text
    assert "Mock data cannot start PAPER" not in text
    assert "Mock PAPER credentials missing" not in text
    assert "Sample data" not in text
    assert "sample data fallback" not in text
    assert "mock/sample mode cannot start PAPER" not in text


def test_operator_ui_uses_scheduler_and_active_screen_rendering():
    text = _app_text()

    assert "function endpointTasksForScreen" in text
    assert "priority: 0" in text
    assert "critical: 2" in text
    assert "normal: 3" in text
    assert "optional: 2" in text
    assert "activeLoadAbortController.abort()" in text
    assert "stale backend response ignored" in text
    assert "const renderer = renderers[selected] || renderPositions" in text
    assert 'main.innerHTML = `<section class="screen active" id="screen-${selected}">${renderer()}</section>`' in text
    assert 'screens.map(([id]) => `<section class="screen"' not in text
    assert "refreshActiveScreenData(id)" in text
    assert 'path: "/operator/ai/recommendations", priority: 3, lane: "optional", optional: true' in text


def test_runtime_lifecycle_reconciles_completed_latest_session_without_refresh():
    text = _app_text()
    css = STYLES_CSS.read_text(encoding="utf-8")

    assert "RUNTIME_ACTIVE_STATUSES" in text
    assert "RUNTIME_TERMINAL_STATUSES" in text
    assert "\"EXITED\"" in text
    assert "\"COMPLETED\"" in text
    assert "function sessionDisplayStatus" in text
    assert "Number(exitCode) === 0 ? \"COMPLETED\" : \"FAILED\"" in text
    assert "function applyRuntimeLifecycleTruth" in text
    assert "const selectedSession = hasActiveSession ? activeSession" in text
    assert "const startAllowed = selectedActive ? false : backendStartAllowed" in text
    assert "sessionRuntimeDetail(selectedSession, selectedActive)" in text
    assert "state.supervisor.paperStopAllowed = stopAllowed === true" in text
    assert "state.supervisor.paperStartAllowed = startAllowed === true" in text
    assert "state.runArchive.runs = [" in text
    assert "Latest PAPER session ${status}" in text
    assert "applyRuntimeLifecycleTruth(next, payload)" in text
    assert "applyRuntimeLifecycleTruth(data, payload)" in text
    assert "renderSessionLifecycleCard" in text
    assert "Active / Latest PAPER Session" in text
    assert "session_id" in text
    assert "started_at" in text
    assert "ended_at" in text
    assert "exit_code" in text
    assert "duration_seconds" in text
    assert "child_stdout" in text
    assert "child_stderr" in text
    assert ".runtime-session-inline" in css


def test_run_archive_ui_surfaces_report_truth_buckets_and_mock_data_is_labeled():
    text = _app_text()
    mock = MOCK_JS.read_text(encoding="utf-8")

    assert "Runtime New" in text
    assert "Historical" in text
    assert "POST/DELETE" in text
    assert "Fee/TCA" in text
    assert "72h" in text
    assert "run.runtime_new_activity && run.runtime_new_activity.order_post_acknowledged" in text
    assert "run.historical_broker_local_activity && run.historical_broker_local_activity.broker_filled_orders" in text
    assert "run.baseline_positions && run.baseline_positions.positions_count" in text
    assert "run.broker_method_counts && run.broker_method_counts.POST" in text
    assert "run.shutdown_open_orders && run.shutdown_open_orders.open_orders_count" in text
    assert "run.fee_tca && run.fee_tca.status" in text
    assert "run.readiness_72h && run.readiness_72h.recommendation" in text
    assert "CONDITIONAL_PASS" in text
    assert "NOT_APPROVED" in text
    forbidden_mock_claim = "Mock DecisionFrame" + " BUY passed hard blockers"
    assert forbidden_mock_claim not in mock
    assert "Static mock-only DecisionFrame sample" in mock
    assert "STATIC_MOCK_DATA_NOT_RUNTIME_EVIDENCE" in mock
    assert "NOT_APPROVED_MOCK_DATA" in mock


def test_runtime_lifecycle_uses_sse_and_polling_fallback():
    text = _app_text()

    assert "LIFECYCLE_RECONCILE_INTERVAL_MS = 5000" in text
    assert "function startRuntimeLifecycleObservers" in text
    assert "new EventSource(`${operatorApiBase()}/operator/events`)" in text
    assert "scheduleLifecycleRefresh(`sse:${eventName}`, 500)" in text
    assert "scheduleLifecycleRefresh(\"sse-error-poll-fallback\", 0)" in text
    assert "window.setInterval(() => {" in text
    assert "reconcileRuntimeLifecycle(reason)" in text
    assert "[\"paperControlState\", \"/operator/paper-control-state\"]" in text
    assert "[\"latestRun\", \"/operator/latest-run\"]" in text
    assert "[\"runtime\", \"/operator/runtime\"]" in text
    assert "state.runArchive.runs = [" in text
    assert "startRuntimeLifecycleObservers()" in text


def test_run_paper_form_draft_survives_lifecycle_reconciliation():
    text = _app_text()

    assert "const paperRunDrafts = {}" in text
    assert "function paperRunDraftForRender" in text
    assert "function syncPaperRunDraftFromDom" in text
    assert "function refreshRunPaperControlDom" in text
    assert "function paperDraftValidation" in text
    assert "data-paper-draft-status" in text
    assert "data-paper-draft-reset" in text
    assert "const selectedDurationRaw = String(draft.durationRaw" in text
    assert "String(seconds) === selectedDurationRaw" in text
    assert "draft.watchlistRaw || defaultPaperWatchlist()" in text
    assert "draft.profileAlpha !== false" in text
    assert "draft.confirmPaper === true" in text
    assert "PAPER_DRAFT_RESET_REASONS.RUN_STARTED" in text
    assert "PAPER_DRAFT_RESET_REASONS.BACKEND_COMMIT_CHANGED" in text


def test_lifecycle_refresh_patches_run_paper_without_remounting_form_controls():
    text = _app_text()

    assert 'if (activeScreenId === "command" || activeScreenId === "activity")' in text
    assert "refreshRunPaperControlDom();" in text
    assert 'renderScreens(activeScreenId || "positions")' in text
    assert "syncPaperRunDraftFromDom(formId, { markDirty: false })" in text
    assert '["paperControlState", "/operator/paper-control-state"]' in text
    assert '["latestRun", "/operator/latest-run"]' in text
    assert "applyPaperControlState(data, data.paperControlState)" in text
    assert "applyRuntimeLifecycleTruth(data, payload)" in text
    assert "sessionCard.outerHTML = renderSessionLifecycleCard" in text
    assert "startButton.disabled = Boolean(effectiveDisabledReason)" in text


def test_run_paper_start_payload_uses_preserved_draft_values():
    text = _app_text()

    assert "const draft = syncPaperRunDraftFromDom(formId || \"command\", { markDirty: false })" in text
    assert "durationSeconds = paperDraftDurationSeconds(draft)" in text
    assert "watchlist: normalizePaperWatchlist(draft.watchlistRaw)" in text
    assert "validation," in text
    assert "if (form.validation && form.validation.valid !== true)" in text
    assert "duration_seconds: form.durationSeconds" in text
    assert "watchlist: form.watchlist" in text
    assert "syncPaperRunDraftFromDom(paperCard.dataset.paperFormCard || \"command\", { markDirty: true, dirtyFields: [field] })" in text
    assert "event.target.matches(\"[data-paper-duration]\")" in text
    assert "event.target.matches(\"[data-paper-watchlist]\")" in text


def test_paper_control_state_timeout_is_precise_fail_closed_authority():
    text = _app_text()

    assert "PAPER_CONTROL_STATE_FETCH_TIMEOUT_MS = 3000" in text
    assert 'if (path === "/operator/paper-control-state") return PAPER_CONTROL_STATE_FETCH_TIMEOUT_MS' in text
    assert "function paperControlStateFailureCode" in text
    assert "PAPER_CONTROL_STATE_TIMEOUT" in text
    assert "Backend is running, but PAPER control-state endpoint timed out. Fix /operator/paper-control-state before starting PAPER." in text
    assert "CONTROL_STATE_UNAVAILABLE" in text
    assert "suppressPortfolioFallback" in text
    assert "Credential status unavailable" in text
    assert "CREDENTIAL_STATUS_UNAVAILABLE" in text
    assert "Baseline launch authority unavailable." in text
    assert "Portfolio read may be available separately, but PAPER start authority cannot use baseline state until control-state returns." in text
    assert "Start remains disabled until canonical PAPER control state returns." in text
    assert "BACKEND_PAPER_CONTROL_STATE_UNAVAILABLE" not in text


def test_operator_launcher_cache_busts_ui_with_loaded_commit():
    text = LAUNCHER_PS1.read_text(encoding="utf-8")
    visible = VISIBLE_LAUNCHER_PS1.read_text(encoding="utf-8")

    assert "git -C $RepoRoot rev-parse --short HEAD" in text
    assert "$UiVersion = [string]$gitHead" in text
    assert "Opening browser at $BaseUrl/operator-ui/?v=$UiVersion" in text
    assert '$UiVersion = "operator-activation-e2e-truth6-20260602"' not in text
    assert "function Update-OperatorUiUrl" in visible
    assert "$BaseUrl/operator-ui/?v=$version&t=$timestampMs" in visible
    assert "operator_ui_opened=$script:UiUrl" in visible
    assert "operator-activation-e2e-truth6-20260602" not in visible


def test_operator_ui_tracks_frontend_backend_commit_mismatch():
    text = _app_text()

    assert "function uiBuildCommit" in text
    assert "function isUnknownBuildCommit" in text
    assert "window.PK_OPERATOR_UI_BUILD_COMMIT" in text
    assert "UI_BACKEND_COMMIT_MISMATCH" in text
    assert "payload.uiBuildCommit = uiBuildCommit()" in text
    assert 'next.meta.uiBuildCommit = pick(payload.uiBuildCommit, uiBuildCommit())' in text
    assert "UNKNOWN_NOT_A" not in text


def test_top_banner_treats_safety_locks_and_idle_as_good_states():
    text = _app_text()

    assert 'badge("Live locked", "green")' in text
    assert 'badge("Real-money blocked", "green")' in text
    assert 'badge("LIVE_LOCKED", "green")' in text
    assert 'badge("REAL_MONEY_BLOCKED", "green")' in text
    assert 'next.status.broker = pick(status.broker, "alpaca_paper")' in text
    assert 'next.status.endpoint = pick(status.endpoint, "https://paper-api.alpaca.markets")' in text
    assert 'next.status.activeProfile = pick(status.active_profile || profile.active_threshold_profile, "PAPER_IDLE")' in text
    assert 'IDLE_NO_ACTIVE_PAPER_RUN' in text


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
    assert "NOT_IMPLEMENTED_VISIBLE" not in text
    assert "future server-authorized intent" not in text
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
