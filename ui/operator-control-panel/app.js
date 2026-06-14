(function () {
  "use strict";

  const mockData = window.PK_MOCK_DATA;
  let data = buildProductionUnavailableState("operator backend has not connected yet");
  const screens = [
    ["positions", "Portfolio Home"],
    ["command", "Run PAPER"],
    ["providers", "Keys & Providers"],
    ["ai", "AI Advisor"],
    ["activity", "Bot Runtime"],
    ["action", "Needs Attention"],
    ["runs", "Paper Run History"],
    ["historical", "4-Month Test"],
    ["pnl", "P&L Truth"],
    ["decision", "Decision Reasons"],
    ["market", "Market Data"],
    ["risk", "Risk Checks"],
    ["alerts", "Alerts"],
    ["research", "Research Proof"],
    ["world", "News & Events"],
    ["diagnostics", "Diagnostics"],
    ["system", "System Map"],
    ["audit", "Audit Log"],
    ["live", "Live Locked"]
  ];
  const NAV_GROUPS = [
    { title: "Operate", summary: "Portfolio and PAPER runtime", items: ["positions", "command", "action", "activity", "runs"] },
    { title: "Understand", summary: "P&L, decisions, risk, alerts", items: ["pnl", "decision", "market", "risk", "alerts"] },
    { title: "Setup", summary: "Keys, AI routing, historical test", items: ["providers", "ai", "historical"] },
    { title: "Research / Proof", summary: "Evidence and outside events", items: ["research", "world"] },
    { title: "System", summary: "Diagnostics, maps, audit, locks", items: ["diagnostics", "system", "audit", "live"] }
  ];
  const DEFAULT_BACKEND_FETCH_TIMEOUT_MS = 10000;
  const PAPER_CONTROL_STATE_FETCH_TIMEOUT_MS = 3000;
  const HEAVY_BACKEND_FETCH_TIMEOUT_MS = 30000;
  const HEAVY_BACKEND_ENDPOINTS = new Set([
    "/operator/runs",
    "/operator/action-center",
    "/operator/alerts",
    "/operator/providers",
    "/operator/providers/readiness",
    "/operator/portfolio",
    "/operator/launch-readiness",
    "/operator/research",
    "/operator/research/evidence-graph",
    "/operator/historical-tests"
  ]);
  const OPTIONAL_BACKEND_ENDPOINTS = new Set([
    "/operator/research/evidence-graph",
    "/operator/diagnostics",
    "/operator/runs",
    "/operator/action-center",
    "/operator/alerts",
    "/operator/system-map",
    "/operator/world-awareness",
    "/operator/world-awareness/runtime",
    "/operator/research",
    "/operator/historical-tests",
    "/operator/ai/recommendations"
  ]);
  const REQUEST_LANE_LIMITS = {
    critical: 2,
    normal: 3,
    optional: 2
  };
  const REQUEST_LANE_BY_PRIORITY = {
    0: "critical",
    1: "normal",
    2: "normal",
    3: "optional"
  };
  const RUNTIME_ACTIVE_STATUSES = new Set(["STARTING", "RUNNING", "STOP_REQUESTED"]);
  const RUNTIME_TERMINAL_STATUSES = new Set(["EXITED", "COMPLETED", "FAILED", "STOPPED", "REFUSED"]);
  const LIFECYCLE_RECONCILE_INTERVAL_MS = 5000;
  const PAPER_DRAFT_RESET_REASONS = {
    INITIAL_LOAD: "INITIAL_LOAD",
    USER_RESET: "USER_RESET",
    INVALID_DURATION_CLAMPED: "INVALID_DURATION_CLAMPED",
    RUN_STARTED: "RUN_STARTED",
    BACKEND_COMMIT_CHANGED: "BACKEND_COMMIT_CHANGED"
  };
  let dataLoadGeneration = 0;
  let activeLoadAbortController = null;
  let lifecyclePollTimer = null;
  let lifecycleEventSource = null;
  let lifecycleRefreshInFlight = false;
  let lifecycleRefreshTimer = null;
  const paperRunDrafts = {};
  const AI_CONTEXT_VERSION = "operator-ui-global-ai-context-v1";
  const AI_ANSWER_MODES = {
    DETERMINISTIC: "DETERMINISTIC",
    CHAT: "AI_CHAT_MODEL",
    REASONING: "AI_REASONING_STRATEGY"
  };
  const AI_QUICK_PROMPTS = [
    "What is blocking PAPER?",
    "Can I start PAPER?",
    "Summarize portfolio truth",
    "Draft Codex packet",
    "Explain this page.",
    "What do I do next?",
    "Why is this blocked?",
    "Explain my positions.",
    "Plan my PAPER smoke test.",
    "Audit readiness.",
    "Where is the edge?",
    "What is the weakest assumption?",
    "Is this signal statistically believable?",
    "What would invalidate this strategy?",
    "What is the safest next PAPER experiment?",
    "Where are fees/slippage hurting us?",
    "What evidence blocks live readiness?",
    "Critique latest run.",
    "Compare latest run to expected behavior.",
    "Draft Codex packet request.",
    "Review provider/data readiness."
  ];
  const AI_PRIMARY_PROMPT_LIMIT = 4;
  const AI_PRESERVED_BOOLEAN_KEYS = new Set([
    "secrets_values_exposed",
    "secretsValuesExposed",
    "raw_logs_included",
    "rawLogsIncluded",
    "broker_call_occurred",
    "brokerCallOccurred",
    "real_money_blocked",
    "realMoneyBlocked",
    "live_ready",
    "liveReady",
    "local_paper_ready",
    "localPaperReady"
  ]);
  const AI_SECRET_KEY_PATTERN = /(api[_-]?key|token|password|secret|credential|authorization|bearer)/i;
  const AI_SECRET_VALUE_PATTERN = /(sk-[A-Za-z0-9_-]{10,}|AKIA[0-9A-Z]{12,}|xox[baprs]-[A-Za-z0-9-]+|-----BEGIN [A-Z ]*PRIVATE KEY-----)/i;
  const CREDENTIAL_FORMS = {
    alpaca_paper: {
      title: "Alpaca PAPER Broker/Data",
      fields: [
        ["APCA_API_KEY_ID", "API key ID", "password", ""],
        ["APCA_API_SECRET_KEY", "API secret key", "password", ""],
        ["APCA_API_BASE_URL", "PAPER base URL", "text", "https://paper-api.alpaca.markets"]
      ]
    },
    openai: {
      title: "OpenAI",
      fields: [["OPENAI_API_KEY", "OpenAI API key", "password", ""]]
    },
    anthropic: {
      title: "Anthropic / Claude",
      fields: [["ANTHROPIC_API_KEY", "Anthropic API key", "password", ""]]
    },
    gemini: {
      title: "Gemini / Google",
      fields: [
        ["GEMINI_API_KEY", "Gemini API key", "password", ""],
        ["GOOGLE_API_KEY", "Google API key alternative", "password", ""]
      ]
    },
    xai_grok: {
      title: "Grok / xAI",
      fields: [
        ["XAI_API_KEY", "xAI API key", "password", ""],
        ["XAI_BASE_URL", "xAI base URL", "text", "https://api.x.ai/v1"]
      ]
    },
    deepseek: {
      title: "DeepSeek",
      fields: [
        ["DEEPSEEK_API_KEY", "DeepSeek API key", "password", ""],
        ["DEEPSEEK_BASE_URL", "DeepSeek base URL", "text", "https://api.deepseek.com/v1"]
      ]
    },
    kimi_moonshot: {
      title: "Kimi / Moonshot",
      fields: [
        ["KIMI_API_KEY", "Kimi API key", "password", ""],
        ["MOONSHOT_API_KEY", "Moonshot API key alternative", "password", ""],
        ["KIMI_BASE_URL", "Kimi base URL", "text", "https://api.moonshot.ai/v1"]
      ]
    },
    local_openai_compatible: {
      title: "Local OpenAI-compatible",
      fields: [
        ["LOCAL_AI_BASE_URL", "Local server base URL", "text", "http://127.0.0.1:11434/v1"],
        ["LOCAL_AI_MODEL", "Local model name", "text", "local-model"],
        ["LOCAL_AI_API_KEY", "Optional local API key", "password", ""]
      ]
    },
    alpaca_news: {
      title: "Alpaca News",
      fields: [
        ["APCA_API_KEY_ID", "API key ID", "password", ""],
        ["APCA_API_SECRET_KEY", "API secret key", "password", ""],
        ["APCA_API_BASE_URL", "PAPER base URL", "text", "https://paper-api.alpaca.markets"]
      ]
    }
  };
  const PROVIDER_GROUPS = [
    {
      title: "Trading / Broker Data",
      providerIds: ["alpaca_paper", "alpaca_news"]
    },
    {
      title: "AI Providers",
      providerIds: ["openai", "deepseek", "anthropic", "gemini", "xai_grok", "kimi_moonshot"]
    },
    {
      title: "Local / Advanced",
      providerIds: ["local_openai_compatible", "deterministic_local", "supreme_board_packet"]
    }
  ];
  const PROVIDER_LABELS = {
    openai: "OpenAI",
    deepseek: "DeepSeek",
    anthropic: "Claude",
    gemini: "Gemini",
    xai_grok: "Grok",
    kimi_moonshot: "Kimi",
    local_openai_compatible: "Local OpenAI-compatible",
    deterministic_local: "Deterministic Local",
    supreme_board_packet: "Supreme Board Packet"
  };
  const HISTORICAL_TIMEFRAMES = ["1Min", "5Min", "15Min", "1Hour", "1Day"];
  const HISTORICAL_FEE_POLICIES = [
    ["broker_fees_unavailable_unknown", "Broker fees unavailable / unknown"],
    ["conservative_estimate_not_broker_truth", "Conservative estimate - not broker truth"]
  ];
  let activeScreenId = "positions";
  let aiOverlayOpen = false;
  let aiWideMode = false;
  let aiSelectedQuestion = AI_QUICK_PROMPTS[0];
  let aiQuestionText = "";
  let aiOverlayResponse = "";
  let aiOverlayLastResult = null;
  let aiOverlayError = "";
  let aiOverlayBusy = false;
  let aiSelectedAnswerMode = AI_ANSWER_MODES.DETERMINISTIC;
  let aiConversation = [];
  let aiMessageSequence = 0;
  let aiUserPinnedScroll = false;
  let homeAiQuestionText = "Review launch readiness, portfolio state, and the safest next PAPER step.";
  let homeAiResponse = "";
  let homeAiLastResult = null;
  let homeAiError = "";
  let homeAiBusy = false;
  let homeAiAnswerMode = AI_ANSWER_MODES.DETERMINISTIC;
  let credentialActionStatus = {};

  function softBreakToken(value) {
    return escapeHtml(String(value))
      .replaceAll("_", "_<wbr>")
      .replaceAll("/", "/<wbr>")
      .replaceAll("-", "-<wbr>")
      .replaceAll(", ", ", <wbr>");
  }

  function normalizeStatusText(value) {
    const legacyCredentialTypo = "MISSING_CREDENTIAL" + "ALS";
    return String(value || "").replaceAll(legacyCredentialTypo, "MISSING_CREDENTIALS");
  }

  function badge(text, color) {
    const raw = normalizeStatusText(text);
    const sizeClass = raw.length > 18 ? "token-long" : "token-short";
    return `<span class="badge ${color || "gray"} ${sizeClass}" title="${escapeHtml(raw)}">${softBreakToken(raw)}</span>`;
  }

  function tokenText(text) {
    const raw = String(text);
    return `<span class="token-text" title="${escapeHtml(raw)}">${softBreakToken(raw)}</span>`;
  }

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function pick(value, fallback) {
    return value === undefined || value === null || value === "" ? fallback : value;
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function statusColor(value) {
    const v = normalizeStatusText(value).toUpperCase();
    if (["EXITED", "COMPLETED", "BOUNDED_RUNTIME_COMPLETED"].includes(v)) return "green";
    if (["FAILED", "STOPPED"].includes(v)) return "red";
    if (v.includes("NOT_APPROVED") || v.includes("SAFETY_CRITICAL")) return "red";
    if (v.includes("CONDITIONAL_PASS") || v.includes("PENDING") || v.includes("SKIPPED") || v.includes("PARTIAL")) return "yellow";
    if (v.includes("NO_ACTIVE") || v.includes("REFUSED")) return "yellow";
    if (v.includes("PASS") || v.includes("ALLOW") || v.includes("CLEAN") || v.includes("RUNNING") || v.includes("PAPER") || v.includes("READY") || v.includes("CONFIGURED")) return "green";
    if (v.includes("UNKNOWN") || v.includes("MISSING") || v.includes("DEGRADED") || v.includes("NO_TRADE") || v.includes("DECLINED")) return "yellow";
    if (v.includes("BLOCK") || v.includes("LOCK") || v.includes("DENY") || v.includes("CONFLICT") || v.includes("LIVE")) return "red";
    return "gray";
  }

  function modelQualityColor(value) {
    const v = String(value || "").toUpperCase();
    if (v === "HIGH_REASONING") return "green";
    if (v === "STANDARD") return "yellow";
    if (v === "LOW_REASONING" || v === "FALLBACK_ONLY" || v === "UNKNOWN") return "red";
    return statusColor(v);
  }

  function aiModelWarning() {
    const quality = String(data.ai.modelQuality || "FALLBACK_ONLY").toUpperCase();
    if (quality === "HIGH_REASONING" && data.ai.modelSuitableForGovernance === true) return "";
    if (quality === "LOW_REASONING" || quality === "STANDARD") {
      return "Lower-reasoning model active. Do not use this for final quant/risk/live-readiness decisions.";
    }
    return "High-reasoning model not configured. Quant/governance answers are limited.";
  }

  function aiProviderCards() {
    const providers = data.ai.providerRegistry || [];
    const fallbackIds = [
      ["openai", "OpenAI / GPT"],
      ["anthropic", "Claude / Anthropic"],
      ["gemini", "Gemini / Google"],
      ["xai_grok", "Grok / xAI"],
      ["deepseek", "DeepSeek"],
      ["kimi_moonshot", "Kimi / Moonshot"],
      ["local_openai_compatible", "Local OpenAI-compatible"],
      ["deterministic_local", "Deterministic Local"],
      ["supreme_board_packet", "Supreme Board Packet"]
    ];
    if (providers.length) return providers;
    return fallbackIds.map(([providerId, displayName]) => ({
      providerId,
      provider_id: providerId,
      displayName,
      display_name: displayName,
      status: providerId === "deterministic_local" || providerId === "supreme_board_packet" ? "READY" : "MISSING_CREDENTIALS",
      modelName: providerId === "supreme_board_packet" ? "chatgpt-pro-manual" : providerId === "deterministic_local" ? "deterministic-local-guide" : "not selected",
      modelQuality: providerId === "supreme_board_packet" ? "HIGH_REASONING" : providerId === "deterministic_local" ? "FALLBACK_ONLY" : "UNKNOWN",
      costMode: providerId === "supreme_board_packet" ? "CHATGPT_PRO_MANUAL" : providerId === "deterministic_local" ? "FREE_LOCAL" : "PROVIDER_ERROR",
      credentialSource: providerId === "deterministic_local" || providerId === "supreme_board_packet" ? "NOT_REQUIRED" : "NOT_CONFIGURED",
      personaEnforced: true,
      implemented: providerId !== "gemini"
    }));
  }

  function aiRoutingSettings() {
    return data.ai.routingSettings || {
      defaultMode: "LOCAL_GUIDE",
      activeProvider: "deterministic_local",
      activeModel: "deterministic-local-guide",
      lightProvider: "openai",
      lightModel: "gpt-5-mini",
      highReasoningProvider: "openai",
      highReasoningModel: "gpt-5.5-pro",
      localProvider: "local_openai_compatible",
      localBaseUrl: "http://127.0.0.1:11434/v1",
      localModel: "local-model",
      supremeBoardPacketDefault: false,
      settingsSource: "DEFAULT_SETTINGS",
      status: "DEFAULT_SETTINGS",
      settingsPathRelative: ".operator_config/ai_router_settings.json"
    };
  }

  function isHighReasoningMode(mode) {
    return mode === "HIGH_REASONING_API" || mode === "HIGH_REASONING_API_WITH_APPROVAL";
  }

  function routingValue(routing, camelKey, snakeKey, fallback) {
    if (routing && routing[camelKey] !== undefined && routing[camelKey] !== null && routing[camelKey] !== "") return routing[camelKey];
    if (routing && routing[snakeKey] !== undefined && routing[snakeKey] !== null && routing[snakeKey] !== "") return routing[snakeKey];
    return fallback;
  }

  function isExternalAiApiProvider(providerId) {
    const id = String(providerId || "").trim();
    return Boolean(id && !["deterministic_local", "supreme_board_packet", "local_openai_compatible"].includes(id));
  }

  function isPortfolioUnavailableStatus(status) {
    return ["BROKER_DATA_UNAVAILABLE", "BROKER_READ_FAILED", "AUTH_FAILED", "MISSING_CREDENTIALS", "BACKEND_DEGRADED", "STALE_BACKEND"].includes(String(status || ""));
  }

  function aiAskRoutingPayload(routing) {
    const routeMode = String(routingValue(routing, "defaultMode", "default_mode", "LOCAL_GUIDE") || "LOCAL_GUIDE");
    const activeProvider = String(routingValue(routing, "activeProvider", "active_provider", "") || "").trim();
    const activeModel = String(routingValue(routing, "activeModel", "active_model", "") || "").trim();
    if (routeMode === "LOCAL_GUIDE" || routeMode === "SUPREME_BOARD_PACKET") {
      return { routeMode, providerId: "", modelName: "" };
    }
    if (routeMode === "LOCAL_MODEL") {
      return {
        routeMode,
        providerId: "local_openai_compatible",
        modelName: String(routingValue(routing, "localModel", "local_model", "local-model") || "").trim()
      };
    }
    if (isExternalAiApiProvider(activeProvider)) {
      return { routeMode, providerId: activeProvider, modelName: activeModel };
    }
    if (isHighReasoningMode(routeMode)) {
      return {
        routeMode,
        providerId: String(routingValue(routing, "highReasoningProvider", "high_reasoning_provider", "openai") || "openai").trim(),
        modelName: String(routingValue(routing, "highReasoningModel", "high_reasoning_model", "") || "").trim()
      };
    }
    if (routeMode === "LIGHT_API") {
      return {
        routeMode,
        providerId: String(routingValue(routing, "lightProvider", "light_provider", "openai") || "openai").trim(),
        modelName: String(routingValue(routing, "lightModel", "light_model", "") || "").trim()
      };
    }
    return { routeMode: "LOCAL_GUIDE", providerId: "", modelName: "" };
  }

  function normalizeAiAnswerMode(value) {
    const raw = String(value || "").trim().toUpperCase().replaceAll("-", "_").replaceAll(" ", "_");
    if (raw === AI_ANSWER_MODES.CHAT || raw === "AI_CHAT" || raw === "CHAT" || raw === "AI_MODEL" || raw === "LIGHT_API") {
      return AI_ANSWER_MODES.CHAT;
    }
    if (raw === AI_ANSWER_MODES.REASONING || raw === "AI_REASONING" || raw === "REASONING" || raw === "STRATEGY" || raw === "HIGH_REASONING_API") {
      return AI_ANSWER_MODES.REASONING;
    }
    return AI_ANSWER_MODES.DETERMINISTIC;
  }

  function aiAnswerModeLabel(mode) {
    const normalized = normalizeAiAnswerMode(mode);
    if (normalized === AI_ANSWER_MODES.CHAT) return "AI Chat Model";
    if (normalized === AI_ANSWER_MODES.REASONING) return "AI Reasoning";
    return "Deterministic";
  }

  function aiAnswerModeDescription(mode) {
    const normalized = normalizeAiAnswerMode(mode);
    if (normalized === AI_ANSWER_MODES.CHAT) return "configured model answers";
    if (normalized === AI_ANSWER_MODES.REASONING) return "high-reasoning advisory path";
    return "our bot/local truth, no provider call";
  }

  function aiAskRoutingPayloadForMode(routing, answerMode) {
    const mode = normalizeAiAnswerMode(answerMode);
    if (mode === AI_ANSWER_MODES.DETERMINISTIC) {
      return { routeMode: "LOCAL_GUIDE", providerId: "", modelName: "", approvedPaidCall: false };
    }
    if (mode === AI_ANSWER_MODES.REASONING) {
      return {
        routeMode: "HIGH_REASONING_API",
        providerId: String(routingValue(routing, "highReasoningProvider", "high_reasoning_provider", "openai") || "openai").trim(),
        modelName: String(routingValue(routing, "highReasoningModel", "high_reasoning_model", "") || "").trim(),
        approvedPaidCall: false
      };
    }
    const activeProvider = String(routingValue(routing, "activeProvider", "active_provider", "") || "").trim();
    const activeModel = String(routingValue(routing, "activeModel", "active_model", "") || "").trim();
    if (isExternalAiApiProvider(activeProvider)) {
      return { routeMode: "LIGHT_API", providerId: activeProvider, modelName: activeModel, approvedPaidCall: false };
    }
    return {
      routeMode: "LIGHT_API",
      providerId: String(routingValue(routing, "lightProvider", "light_provider", "openai") || "openai").trim(),
      modelName: String(routingValue(routing, "lightModel", "light_model", "") || "").trim(),
      approvedPaidCall: false
    };
  }

  function renderAiAnswerModeButtons(scope, selectedMode, busy) {
    const modes = [
      [AI_ANSWER_MODES.DETERMINISTIC, "Deterministic"],
      [AI_ANSWER_MODES.CHAT, "AI Chat Model"],
      [AI_ANSWER_MODES.REASONING, "AI Reasoning"]
    ];
    return `
      <div class="ai-answer-mode-group" role="group" aria-label="${escapeHtml(scope === "home" ? "Home AI answer source" : "AI answer source")}">
        ${modes.map(([mode, label]) => `
          <button class="intent-button ai-mode-button ${normalizeAiAnswerMode(selectedMode) === mode ? "active" : ""}" type="button" data-ai-answer-mode-ask="${escapeHtml(scope)}:${escapeHtml(mode)}" ${busy ? "disabled" : ""}>
            <span>${escapeHtml(label)}</span>
            <small>${escapeHtml(aiAnswerModeDescription(mode))}</small>
          </button>
        `).join("")}
      </div>
    `;
  }

  function providerIdOf(provider) {
    return String((provider && (provider.providerId || provider.provider_id)) || "").trim();
  }

  function credentialProviderById(providers, providerId) {
    const id = String(providerId || "").trim();
    return (providers || []).find((provider) => providerIdOf(provider) === id) || null;
  }

  function configuredCredentialSources(fields) {
    const sources = (fields || [])
      .filter((field) => field && field.configured === true)
      .map((field) => normalizeStatusText(field.source || "NOT_CONFIGURED"))
      .filter((source) => source && source !== "NOT_CONFIGURED");
    return Array.from(new Set(sources)).sort();
  }

  function credentialSourceFromProvider(provider) {
    if (!provider) return "NOT_CONFIGURED";
    if (provider.credentialSource) return normalizeStatusText(provider.credentialSource);
    if (provider.credential_source) return normalizeStatusText(provider.credential_source);
    if (provider.source) return normalizeStatusText(provider.source);
    const sources = configuredCredentialSources(provider.fields || provider.envStatus || provider.env_status || []);
    if (sources.length) return sources.join("+");
    if (provider.configured === true && !(provider.requiredEnvVars || provider.required_env_vars || []).length) return "NOT_REQUIRED";
    return "NOT_CONFIGURED";
  }

  function providerDisplaySource(provider) {
    const source = credentialSourceFromProvider(provider);
    if (source !== "NOT_CONFIGURED") return source;
    const configuredRows = (provider.envStatus || [])
      .filter((row) => row && row.configured === true)
      .map((row) => normalizeStatusText(row.source || "NOT_CONFIGURED"))
      .filter((value) => value !== "NOT_CONFIGURED");
    return Array.from(new Set(configuredRows)).sort().join("+") || "NOT_CONFIGURED";
  }

  function providerDisplayFingerprints(provider) {
    const rows = provider.fields || provider.envStatus || [];
    const fingerprints = rows
      .filter((row) => row && row.configured === true && row.fingerprint)
      .map((row) => String(row.fingerprint));
    return Array.from(new Set(fingerprints)).join(", ") || "missing";
  }

  function providerDisplayLabel(providerId) {
    const id = String(providerId || "").trim();
    const card = aiProviderCards().find((provider) => providerIdOf(provider) === id);
    return (card && (card.displayName || card.display_name)) || PROVIDER_LABELS[id] || id || "Local Guide";
  }

  function providerDefaultModel(providerId) {
    const id = String(providerId || "").trim();
    const card = aiProviderCards().find((provider) => providerIdOf(provider) === id);
    if (card && (card.modelName || card.model_name || card.default_model)) {
      return card.modelName || card.model_name || card.default_model;
    }
    if (id === "deepseek") return "deepseek-chat";
    if (id === "openai") return "gpt-5-mini";
    if (id === "supreme_board_packet") return "chatgpt-pro-manual";
    if (id === "deterministic_local") return "deterministic-local-guide";
    return "";
  }

  function mergeCredentialTruthIntoProviderReadiness(target) {
    const credentialProviders = (target.credentials && target.credentials.providers) || [];
    const credentialById = new Map(credentialProviders.map((provider) => [providerIdOf(provider), provider]));
    const providerRows = Array.isArray(target.providerReadiness.providers) ? target.providerReadiness.providers : [];
    const providerById = new Map(providerRows.map((provider) => [providerIdOf(provider), provider]));
    credentialProviders.forEach((credential) => {
      const id = providerIdOf(credential);
      const existing = providerById.get(id);
      if (!existing) return;
      existing.credentialSource = credentialSourceFromProvider(credential);
      existing.fields = credential.fields || [];
      if (credential.configured === true) {
        existing.configured = true;
        if (existing.status !== "NOT_IMPLEMENTED") existing.status = "CONFIGURED";
      } else if (existing.requiredEnvVars && existing.requiredEnvVars.length && existing.status !== "NOT_IMPLEMENTED") {
        existing.configured = false;
        existing.status = "MISSING_CREDENTIALS";
      }
    });
    providerRows.forEach((provider) => {
      if (!provider.credentialSource) {
        const credential = credentialById.get(providerIdOf(provider));
        provider.credentialSource = credential ? credentialSourceFromProvider(credential) : providerDisplaySource(provider);
      }
      provider.status = normalizeStatusText(provider.status || "UNKNOWN");
    });
    const counts = {};
    providerRows.forEach((provider) => {
      const status = normalizeStatusText(provider.status || "UNKNOWN");
      counts[status] = (counts[status] || 0) + 1;
    });
    target.providerReadiness.providerCount = providerRows.length;
    target.providerReadiness.counts = counts;
    target.providerReadiness.readyOrConfiguredCount = (counts.READY || 0) + (counts.CONFIGURED || 0);
    target.providerReadiness.missingCredentialsCount = counts.MISSING_CREDENTIALS || 0;
    target.providerReadiness.notImplementedCount = counts.NOT_IMPLEMENTED || 0;
  }

  function pageAwareAiPrompts(pageId) {
    const common = ["Explain this page.", "What do I do next?"];
    const byPage = {
      positions: ["Explain my positions.", "What is my exposure?", "What is risky in my portfolio?"],
      command: ["Why is PAPER run blocked?", "Plan my PAPER smoke test.", "How do I start an approved PAPER smoke test?"],
      providers: ["Where do I enter Alpaca keys?", "Why is Alpaca missing if I entered keys?", "What does Local credential vault mean?"],
      activity: ["Why is this blocked?", "Plan my PAPER run.", "What should be monitored during the run?"],
      ai: ["Audit readiness.", "Draft Codex packet request.", "What should I ask Codex to fix?"],
      system: ["Draft Codex packet request.", "Is this a code issue, config issue, broker issue, UI issue, or strategy issue?"],
      pnl: ["Where are fees/slippage hurting us?", "What evidence is missing before live?"],
      research: ["Is this strategy statistically believable?", "What could be overfit?", "Does this look like real edge or noise?"]
    };
    return [...common, ...(byPage[pageId] || ["Why is this blocked?", "Audit readiness."])];
  }

  function uniquePrompts(prompts) {
    return (prompts || []).filter((prompt, index, arr) => prompt && arr.indexOf(prompt) === index);
  }

  function primaryAiPrompts(pageId) {
    return AI_QUICK_PROMPTS.slice(0, AI_PRIMARY_PROMPT_LIMIT);
  }

  function moreAiPrompts(pageId) {
    const primary = new Set(primaryAiPrompts(pageId));
    return uniquePrompts(pageAwareAiPrompts(pageId || activeScreenId || "positions").concat(AI_QUICK_PROMPTS)).filter((prompt) => !primary.has(prompt));
  }

  function screenIndex(id) {
    return screens.findIndex(([screenId]) => screenId === id);
  }

  function navPageNumber(id) {
    const index = screenIndex(id);
    return index >= 0 ? String(index + 1).padStart(2, "0") : "--";
  }

  function navBadge(id) {
    const badges = {
      command: "Primary",
      positions: "Home",
      providers: "Setup",
      ai: "Advisor",
      diagnostics: "Advanced",
      live: "Locked"
    };
    return badges[id] || "";
  }

  function shouldOpenAiDockFromUrl() {
    const params = new URLSearchParams(window.location.search || "");
    const value = String(params.get("aiDock") || params.get("advisor") || "").toLowerCase();
    return value === "open" || value === "1" || value === "true";
  }

  function shouldUseWideAiDockFromUrl() {
    const params = new URLSearchParams(window.location.search || "");
    const value = String(params.get("aiWide") || "").toLowerCase();
    return value === "1" || value === "true" || value === "wide";
  }

  function syncAiDockedState() {
    document.body.classList.toggle("ai-docked-open", aiOverlayOpen);
    document.body.classList.toggle("ai-docked-wide", aiOverlayOpen && aiWideMode);
  }

  function dataSourceColor() {
    if (data.meta.dataSource === "OPERATOR_BACKEND") return "green";
    if (data.meta.dataSource === "PARTIAL_BACKEND") return "yellow";
    if (data.meta.dataSource === "BACKEND_UNAVAILABLE") return "red";
    return "yellow";
  }

  function sourceLabel() {
    if (data.meta.dataSource === "OPERATOR_BACKEND") return "Backend: OK";
    if (data.meta.dataSource === "PARTIAL_BACKEND") return `Backend: Degraded - ${backendDegradedCount()} check${backendDegradedCount() === 1 ? "" : "s"}`;
    if (data.meta.dataSource === "BACKEND_UNAVAILABLE") return "Backend: Unavailable";
    return "Backend: Not connected";
  }

  function sourceSubtext() {
    if (data.meta.dataSource === "OPERATOR_BACKEND") return "operator panel / backend OK";
    if (data.meta.dataSource === "PARTIAL_BACKEND") return `operator panel / ${backendDegradedCount()} degraded check${backendDegradedCount() === 1 ? "" : "s"}`;
    if (data.meta.dataSource === "BACKEND_UNAVAILABLE") return "operator panel / backend unavailable";
    return "operator panel / backend not connected";
  }

  function formatDuration(seconds) {
    const value = Number(seconds) || 0;
    if (value % 86400 === 0 && value >= 86400) return `${value / 86400} day${value === 86400 ? "" : "s"}`;
    if (value % 3600 === 0 && value >= 3600) return `${value / 3600} hour${value === 3600 ? "" : "s"}`;
    if (value % 60 === 0 && value >= 60) return `${value / 60} minute${value === 60 ? "" : "s"}`;
    return `${value} seconds`;
  }

  function paperFormId(formId) {
    return String(formId || "command");
  }

  function paperDraftKey(formId) {
    return paperFormId(formId);
  }

  function defaultPaperWatchlist() {
    const sup = data.supervisor || {};
    const watchlist = sup.watchlist && sup.watchlist.length ? sup.watchlist : ["BTC/USD", "ETH/USD", "SOL/USD"];
    return watchlist.join(",");
  }

  function paperDurationBounds() {
    const sup = data.supervisor || {};
    const minDuration = Number(sup.minPaperDurationSeconds || sup.min_paper_duration_seconds || 60);
    const configuredMaxDuration = Number(sup.maxPaperDurationSeconds || sup.max_paper_duration_seconds || 432000);
    const runnerMaxDuration = Number(sup.runnerMaxPaperDurationSeconds || sup.runner_max_paper_duration_seconds || 432000);
    const maxDuration = Math.min(configuredMaxDuration || 432000, runnerMaxDuration || 432000, 432000);
    const durationOptions = [
      [180, "3 minutes"],
      [300, "5 minutes"],
      [900, "15 minutes"],
      [1800, "30 minutes"],
      [3600, "1 hour"],
      [14400, "4 hours"],
      [86400, "1 day"],
      [259200, "72 hours"],
      [432000, "5 days"]
    ].filter(([seconds]) => seconds >= minDuration && seconds <= maxDuration);
    const defaultDuration = durationOptions.some(([seconds]) => seconds === 300)
      ? 300
      : ((durationOptions[0] || [minDuration])[0]);
    return { minDuration, configuredMaxDuration, runnerMaxDuration, maxDuration, durationOptions, defaultDuration };
  }

  function defaultPaperRunDraft(formId) {
    const bounds = paperDurationBounds();
    return {
      formId: paperFormId(formId),
      initialized: true,
      dirty: false,
      dirtyFields: {},
      watchlistRaw: defaultPaperWatchlist(),
      durationRaw: String(bounds.defaultDuration),
      customAmountRaw: "5",
      customUnit: "minutes",
      profileAlpha: true,
      confirmPaper: false,
      confirmLiveLocked: false,
      confirmRealMoneyBlocked: false,
      confirmNoManualTrades: false,
      lastInteractionAt: null,
      lastResetReason: PAPER_DRAFT_RESET_REASONS.INITIAL_LOAD,
      backendCommit: data.meta && data.meta.runtimeCommit ? data.meta.runtimeCommit : null,
      startedSessionId: null
    };
  }

  function paperRunDraft(formId) {
    const key = paperDraftKey(formId);
    if (!paperRunDrafts[key]) {
      paperRunDrafts[key] = defaultPaperRunDraft(key);
    }
    return paperRunDrafts[key];
  }

  function paperRunDraftForRender(formId) {
    const key = paperDraftKey(formId);
    const draft = paperRunDraft(key);
    const currentCommit = data.meta && data.meta.runtimeCommit ? data.meta.runtimeCommit : null;
    if (draft.backendCommit && currentCommit && draft.backendCommit !== currentCommit) {
      return resetPaperRunDraft(key, PAPER_DRAFT_RESET_REASONS.BACKEND_COMMIT_CHANGED);
    }
    if (!draft.backendCommit && currentCommit) {
      draft.backendCommit = currentCommit;
    }
    return draft;
  }

  function resetPaperRunDraft(formId, reason) {
    const key = paperDraftKey(formId);
    paperRunDrafts[key] = {
      ...defaultPaperRunDraft(key),
      lastResetReason: reason || PAPER_DRAFT_RESET_REASONS.USER_RESET
    };
    return paperRunDrafts[key];
  }

  function normalizePaperWatchlist(raw) {
    return String(raw || "")
      .split(",")
      .map((item) => item.trim().toUpperCase())
      .filter(Boolean);
  }

  function paperDraftDurationSeconds(draft) {
    const durationRaw = String((draft && draft.durationRaw) || "300");
    if (durationRaw === "custom") {
      const customAmount = Math.max(Number.parseInt((draft && draft.customAmountRaw) || "1", 10) || 1, 1);
      const unit = (draft && draft.customUnit) || "minutes";
      const unitMultiplier = unit === "days" ? 86400 : (unit === "hours" ? 3600 : 60);
      return customAmount * unitMultiplier;
    }
    return Number.parseInt(durationRaw, 10) || 300;
  }

  function paperDraftValidation(draft, bounds) {
    const effectiveBounds = bounds || paperDurationBounds();
    const watchlist = normalizePaperWatchlist(draft && draft.watchlistRaw);
    const durationSeconds = paperDraftDurationSeconds(draft || {});
    if (!watchlist.length) {
      return {
        valid: false,
        reason: "WATCHLIST_REQUIRED",
        detail: "Enter at least one governed PAPER watchlist symbol."
      };
    }
    if (durationSeconds < effectiveBounds.minDuration) {
      return {
        valid: false,
        reason: "DURATION_BELOW_MINIMUM_SECONDS",
        detail: `Selected duration ${formatDuration(durationSeconds)} is below the current minimum ${formatDuration(effectiveBounds.minDuration)}.`
      };
    }
    if (durationSeconds > effectiveBounds.maxDuration) {
      return {
        valid: false,
        reason: "DURATION_EXCEEDS_MAX_LEASE",
        detail: `Selected duration ${formatDuration(durationSeconds)} exceeds the current governed PAPER lease max ${formatDuration(effectiveBounds.maxDuration)}.`
      };
    }
    return {
      valid: true,
      reason: "PAPER_DRAFT_VALID",
      detail: `Draft run length ${formatDuration(durationSeconds)} for ${watchlist.join(", ")}.`
    };
  }

  function syncPaperRunDraftFromDom(formId, options) {
    const opts = options || {};
    const key = paperDraftKey(formId);
    const card = document.querySelector(`[data-paper-form-card="${key}"]`) || document.querySelector("[data-paper-form-card]");
    if (!card) return paperRunDraft(key);
    const draft = paperRunDraft(key);
    const readValue = (selector, fallback) => {
      const el = card.querySelector(selector);
      return el ? el.value : fallback;
    };
    const readChecked = (selector, fallback) => {
      const el = card.querySelector(selector);
      return el ? el.checked === true : fallback;
    };
    draft.watchlistRaw = readValue("[data-paper-watchlist]", draft.watchlistRaw);
    draft.durationRaw = readValue("[data-paper-duration]", draft.durationRaw);
    draft.customAmountRaw = readValue("[data-paper-duration-amount]", draft.customAmountRaw);
    draft.customUnit = readValue("[data-paper-duration-unit]", draft.customUnit);
    draft.profileAlpha = readChecked("[data-paper-profile-alpha]", draft.profileAlpha);
    draft.confirmPaper = readChecked("[data-paper-confirm-paper]", draft.confirmPaper);
    draft.confirmLiveLocked = readChecked("[data-paper-confirm-live-locked]", draft.confirmLiveLocked);
    draft.confirmRealMoneyBlocked = readChecked("[data-paper-confirm-real-money-blocked]", draft.confirmRealMoneyBlocked);
    draft.confirmNoManualTrades = readChecked("[data-paper-confirm-no-manual-trades]", draft.confirmNoManualTrades);
    if (opts.markDirty) {
      draft.dirty = true;
      draft.lastInteractionAt = new Date().toISOString();
      (opts.dirtyFields || []).forEach((field) => {
        draft.dirtyFields[field] = true;
      });
    }
    return draft;
  }

  function paperDraftDirtyLabel(draft) {
    const reset = draft && draft.lastResetReason ? ` Last reset: ${draft.lastResetReason}.` : "";
    if (!draft || !draft.dirty) return `Using backend defaults until edited.${reset}`;
    const fields = Object.keys(draft.dirtyFields || {});
    return `Editing draft preserved locally${fields.length ? `: ${fields.join(", ")}` : ""}.${reset}`;
  }

  function refreshRunPaperControlDom() {
    document.querySelectorAll("[data-paper-form-card]").forEach((card) => {
      const formId = card.dataset.paperFormCard || "command";
      syncPaperRunDraftFromDom(formId, { markDirty: false });
      const disabledReason = paperLaunchDisabledReason();
      const draft = paperRunDraftForRender(formId);
      const validation = paperDraftValidation(draft, paperDurationBounds());
      const effectiveDisabledReason = validation.valid ? disabledReason : validation.detail;
      const sessionCard = card.querySelector("[data-runtime-session-card]");
      if (sessionCard) {
        sessionCard.outerHTML = renderSessionLifecycleCard("Active / Latest PAPER Session", "inline");
      }
      const startButton = card.querySelector("[data-run-paper-start-control]");
      if (startButton) {
        startButton.disabled = Boolean(effectiveDisabledReason);
      }
      const startState = card.querySelector("[data-run-paper-start-state]");
      if (startState) {
        startState.classList.toggle("error", Boolean(effectiveDisabledReason));
        startState.textContent = effectiveDisabledReason || "Ready to request the governed /operator/intent/paper/start endpoint after confirmations are checked.";
      }
      const draftNotice = card.querySelector("[data-paper-draft-status]");
      if (draftNotice) {
        draftNotice.textContent = `${paperDraftDirtyLabel(draft)} ${validation.detail}`;
        draftNotice.classList.toggle("error", validation.valid !== true);
      }
      const blockerText = card.querySelector("[data-run-paper-blocker-text]");
      if (blockerText) {
        const op = runPaperState();
        const canRun = op.canRunPaper || {};
        const overall = op.overallStatus || {};
        blockerText.textContent = canRun.allowed === true
          ? "No blocking readiness checks reported by backend start authority."
          : (canRun.reason || overall.detail || "Backend start authority is blocked.");
        blockerText.classList.toggle("error", canRun.allowed !== true);
      }
      const nextAction = card.querySelector("[data-run-paper-next-action]");
      if (nextAction) {
        const op = runPaperState();
        nextAction.textContent = `Next safe action: ${op.nextSafeAction || "Review launch readiness and do not run PAPER without approval."}`;
      }
    });
  }

  function sessionIdOf(session) {
    return session && (session.session_id || session.sessionId || session.run_id || session.runId);
  }

  function rawSessionStatus(session) {
    return String(session && (session.status || session.process_state || session.processState) || "").trim().toUpperCase();
  }

  function isActiveSessionStatus(status) {
    return RUNTIME_ACTIVE_STATUSES.has(String(status || "").toUpperCase());
  }

  function isTerminalSessionStatus(status) {
    return RUNTIME_TERMINAL_STATUSES.has(String(status || "").toUpperCase());
  }

  function sessionDisplayStatus(session) {
    const status = rawSessionStatus(session);
    if (status === "EXITED") {
      const exitCode = session && session.exit_code;
      return Number(exitCode) === 0 ? "COMPLETED" : "FAILED";
    }
    return status || "UNKNOWN";
  }

  function sessionTerminalVerdict(session) {
    const display = sessionDisplayStatus(session);
    if (display === "COMPLETED") return "COMPLETED";
    if (["FAILED", "STOPPED", "REFUSED"].includes(display)) return display;
    return display || "UNKNOWN";
  }

  function sessionRuntimeDetail(session, active) {
    if (!sessionIdOf(session)) return "No PAPER run currently attached.";
    const status = sessionDisplayStatus(session);
    if (active) return `PAPER supervisor process is attached: ${sessionIdOf(session)}.`;
    if (isTerminalSessionStatus(rawSessionStatus(session))) {
      const ended = session.ended_at || session.endedAt || "ended_at unavailable";
      const exitCode = session.exit_code !== undefined && session.exit_code !== null ? `; exit_code ${session.exit_code}` : "";
      return `Latest PAPER session ${status}: ${sessionIdOf(session)}; ended ${ended}${exitCode}.`;
    }
    return `Latest PAPER session ${status}: ${sessionIdOf(session)}.`;
  }

  function backendDegradedSummary() {
    const failures = data.meta.fetchFailures || [];
    if (!failures.length) return "Backend: OK";
    return `Backend: Degraded - ${failures.length} check${failures.length === 1 ? "" : "s"}. View details in Diagnostics.`;
  }

  function backendDegradedCount() {
    return (data.meta.fetchFailures || []).length;
  }

  function backendFailureRows() {
    return (data.meta.fetchFailures || []).map((failure) => {
      const text = String(failure || "unknown endpoint failure");
      const separator = text.indexOf(": ");
      return {
        endpoint: separator >= 0 ? text.slice(0, separator) : "unknown",
        reason: separator >= 0 ? text.slice(separator + 2) : text
      };
    });
  }

  function backendConnected() {
    return data.meta.dataSource === "OPERATOR_BACKEND" || data.meta.dataSource === "PARTIAL_BACKEND";
  }

  function uiBuildCommit() {
    if (window.PK_OPERATOR_UI_BUILD_COMMIT) return String(window.PK_OPERATOR_UI_BUILD_COMMIT);
    const params = new URLSearchParams(window.location.search || "");
    return params.get("v") || "UNKNOWN_UI_BUILD_COMMIT";
  }

  function isUnknownBuildCommit(value) {
    const normalized = String(value || "");
    const unavailable = ["UNKNOWN", "NOT", "AVAILABLE"].join("_");
    const missingUi = ["UNKNOWN", "UI", "BUILD", "COMMIT"].join("_");
    return !normalized || normalized === unavailable || normalized === missingUi;
  }

  function isMockAuthoritySource(source) {
    const value = String(source || "").toUpperCase();
    return value === "MOCK_DATA" || value === "STATIC_MOCK" || value.includes("MOCK_");
  }

  function hasMockRunPaperReason(codes) {
    return (Array.isArray(codes) ? codes : []).some((code) => String(code || "").toUpperCase().includes("MOCK_DATA"));
  }

  function runPaperStateHasMockAuthority(state) {
    const op = state || {};
    const canRun = op.canRunPaper || {};
    const advanced = op.advanced || {};
    return isMockAuthoritySource(op.source)
      || isMockAuthoritySource((op.endpoint || {}).source)
      || isMockAuthoritySource((op.credentials || {}).source)
      || isMockAuthoritySource((op.paperBaseline || {}).source)
      || isMockAuthoritySource((op.paperCredentialSetup || {}).source)
      || hasMockRunPaperReason(canRun.reasonCodes)
      || hasMockRunPaperReason(advanced.reasonCodes);
  }

  function uniqueCodes(codes) {
    return (codes || []).filter((code, index, arr) => code && arr.indexOf(code) === index);
  }

  function runPaperSourceMismatchCodes(state, op) {
    const codes = [];
    const launch = (state && state.launchReadiness) || {};
    const portfolio = (state && state.portfolio) || {};
    const credentials = (state && state.credentials) || {};
    const providers = Array.isArray(credentials.providers) ? credentials.providers : [];
    const alpaca = providers.find((item) => item.providerId === "alpaca_paper") || {};
    const sup = (state && state.supervisor) || {};
    const view = op || {};
    if (!launch.source || isMockAuthoritySource(launch.source) || isMockAuthoritySource(view.source)) {
      codes.push("READINESS_SOURCE_MISMATCH");
    }
    if ((credentials.source && !isMockAuthoritySource(credentials.source)) || alpaca.configured === true) {
      const source = (view.credentials || {}).source;
      if (!source || isMockAuthoritySource(source) || view.credentials && view.credentials.configured !== alpaca.configured) {
        codes.push("CREDENTIAL_SOURCE_MISMATCH");
      }
    }
    if (portfolio.status === "BROKER_CONFIRMED" || portfolio.brokerReadOccurred === true) {
      const brokerTruth = view.brokerTruth || {};
      if (!brokerTruth.brokerConfirmed || isMockAuthoritySource(brokerTruth.status) || isMockAuthoritySource(brokerTruth.label)) {
        codes.push("PORTFOLIO_SOURCE_MISMATCH");
      }
    }
    if (sup.state || sup.processState || sup.sessionId) {
      const runtime = view.runtime || {};
      const supActive = Boolean(sup.sessionId && sup.sessionId !== "none")
        || ["RUNNING", "STARTING", "STOP_REQUESTED"].includes(String(sup.processState || sup.state || "").toUpperCase());
      const runtimeState = String(runtime.state || runtime.processState || "").toUpperCase();
      if (supActive && (!runtimeState || runtimeState.includes("MOCK") || runtime.activeSessionId !== sup.sessionId && sup.sessionId && sup.sessionId !== "none")) {
        codes.push("SUPERVISOR_SOURCE_MISMATCH");
      }
    }
    return uniqueCodes(codes);
  }

  function paperBaselineFromState(state, op) {
    const standalone = (state && state.paperBaseline) || {};
    const nested = (op && op.paperBaseline) || {};
    const connected = state && state.meta
      ? (state.meta.dataSource === "OPERATOR_BACKEND" || state.meta.dataSource === "PARTIAL_BACKEND")
      : backendConnected();
    if (connected) {
      if (standalone.source && !isMockAuthoritySource(standalone.source)) return standalone;
      if (nested.source && !isMockAuthoritySource(nested.source)) return nested;
      if (standalone.accepted === true) return standalone;
      if (nested.accepted === true) return nested;
      return standalone.source ? standalone : nested;
    }
    return nested.source ? nested : standalone;
  }

  function alpacaPaperCredentialTruth(state) {
    const credentials = (state && state.credentials) || {};
    const providers = Array.isArray(credentials.providers) ? credentials.providers : [];
    const provider = providers.find((item) => item.providerId === "alpaca_paper")
      || providers.find((item) => item.providerId === "alpaca_news")
      || {};
    const fields = Array.isArray(provider.fields) ? provider.fields : [];
    const byName = new Map(fields.map((field) => [field.name, field]));
    const required = ["APCA_API_KEY_ID", "APCA_API_SECRET_KEY"];
    const rows = required.map((name) => {
      const field = byName.get(name) || {};
      const present = field.configured === true || (provider.configured === true && fields.length === 0);
      return {
        name,
        present,
        displayValue: present ? "present" : "missing",
        source: field.source || provider.source || credentials.source || "OPERATOR_LOCAL_CREDENTIAL_STORE",
        rawValueExposed: false
      };
    });
    const missingFields = rows.filter((row) => row.present !== true).map((row) => row.name);
    return {
      configured: missingFields.length === 0,
      missingFields,
      source: provider.source || credentials.source || "OPERATOR_LOCAL_CREDENTIAL_STORE",
      precedence: credentials.precedence || "ENV_PRESENT_OVERRIDES_LOCAL_SECRET",
      rows
    };
  }

  function endpointTruthFromState(state) {
    const launch = (state && state.launchReadiness) || {};
    const status = (state && state.status) || {};
    const statusEndpoint = String(status.endpoint || "");
    const display = launch.paperEndpointDisplay
      || (statusEndpoint.includes("paper-api.alpaca.markets") ? statusEndpoint : "https://paper-api.alpaca.markets");
    const family = launch.paperEndpointFamily
      || (display.includes("paper-api.alpaca.markets") ? "paper" : "unknown");
    const host = launch.paperEndpointHost
      || (display.includes("paper-api.alpaca.markets") ? "paper-api.alpaca.markets" : "");
    const source = launch.paperEndpointSource && !isMockAuthoritySource(launch.paperEndpointSource)
      ? launch.paperEndpointSource
      : (statusEndpoint.includes("paper-api.alpaca.markets") ? "OPERATOR_STATUS" : "BACKEND_LAUNCH_READINESS_UNAVAILABLE");
    const valid = family === "paper" && display.includes("paper-api.alpaca.markets");
    return {
      label: valid ? `Alpaca PAPER endpoint confirmed: ${display}` : "PAPER endpoint authority unavailable",
      display,
      family,
      host,
      source,
      configured: launch.alpacaEndpointConfigured === true,
      valid,
      status: launch.paperEndpointStatus || (valid ? "PAPER_ENDPOINT_CONFIRMED" : "UNKNOWN"),
      blockerCode: launch.paperEndpointBlockerCode || null,
      operatorAction: launch.paperEndpointOperatorAction || (valid ? "No endpoint action required." : "Reload backend launch readiness before starting PAPER.")
    };
  }

  function brokerTruthFromState(state) {
    const portfolio = (state && state.portfolio) || {};
    const brokerConfirmed = portfolio.status === "BROKER_CONFIRMED" || (portfolio.summary && Number(portfolio.summary.positionCount || 0) >= 0 && portfolio.brokerReadOccurred === true);
    return {
      status: brokerConfirmed ? "BROKER_CONFIRMED" : "BROKER_TRUTH_NOT_LOADED_IN_THIS_CARD",
      label: brokerConfirmed ? "Broker-confirmed PAPER portfolio loaded" : "Broker truth not loaded in Run PAPER card",
      detail: brokerConfirmed
        ? `${portfolio.message || "Portfolio Snapshot is broker-confirmed."} Positions: ${(portfolio.summary && portfolio.summary.positionCount) || 0}; open orders: ${(portfolio.summary && portfolio.summary.openOrderCount) || 0}.`
        : "Portfolio Snapshot remains the broker-confirmed truth area; no positions are invented here.",
      brokerConfirmed,
      brokerReadOccurred: portfolio.brokerReadOccurred === true,
      brokerReadAttempted: portfolio.brokerReadAttempted === true,
      brokerMutationOccurred: portfolio.brokerMutationOccurred === true,
      orderSubmissionOccurred: false,
      cancelOccurred: false,
      liquidationOccurred: false
    };
  }

  function buildCredentialSetupFromBackendState(state) {
    const truth = alpacaPaperCredentialTruth(state);
    const endpoint = endpointTruthFromState(state);
    const baseline = paperBaselineFromState(state, {});
    const baselineAccepted = baseline.accepted === true;
    return {
      source: "OPERATOR_BACKEND_CREDENTIALS",
      schemaVersion: "paper-credential-setup-v1",
      overallStatus: {
        code: truth.configured ? "PRESENT" : "MISSING",
        label: truth.configured ? "Alpaca PAPER credentials configured" : "Alpaca PAPER credentials missing",
        severity: truth.configured ? "ready" : "blocked",
        detail: truth.configured
          ? "Credential presence is confirmed by the operator backend; raw values are hidden."
          : "Credential presence is not confirmed by the operator backend."
      },
      requiredCredentials: truth.rows,
      missingFields: truth.missingFields,
      valuesHidden: true,
      endpoint: {
        display: endpoint.display,
        family: endpoint.family,
        host: endpoint.host,
        source: endpoint.source,
        configured: endpoint.configured,
        paperEndpointValid: endpoint.valid,
        liveEndpointBlocked: true,
        blockerCode: endpoint.blockerCode
      },
      approvedSecretPath: {
        label: "Keys & Providers -> Alpaca PAPER Broker/Data -> Save local credentials",
        storageType: "operator_secret_file",
        relativePath: ".operator_secrets/provider_credentials.json",
        credentialPrecedence: truth.precedence,
        gitignored: true,
        safeInstruction: "Use Keys & Providers when OPERATOR_BACKEND is connected; values stay local and hidden.",
        forbiddenInstruction: "Do not paste credentials into chat, do not commit .env files, and do not put raw secrets in tracked files."
      },
      preflightGate: {
        readOnlyPreflightAuthorized: false,
        readOnlyPreflightAvailable: truth.configured,
        accountCheckStatus: baselineAccepted ? "accepted_existing_positions" : "backend_launch_readiness_unavailable",
        openOrdersCheckStatus: baselineAccepted ? "accepted_existing_positions" : "backend_launch_readiness_unavailable",
        positionsCheckStatus: baselineAccepted ? "accepted_existing_positions" : "backend_launch_readiness_unavailable",
        lastPreflightAt: baseline.acceptedAt || null,
        lastPreflightResult: baseline.status || null,
        statusLabel: baselineAccepted ? "Accepted protected baseline" : "Backend launch readiness unavailable",
        detail: baselineAccepted
          ? "Accepted protected baseline is loaded from backend state. Raw credentials are not exposed."
          : "Backend credential truth is loaded, but launch readiness must return before PAPER start can be requested.",
        explicitApprovalRequired: true,
        futureChecks: ["GET /v2/account", "GET /v2/orders?status=open", "GET /v2/positions"],
        alpacaNetworkCallOccurred: false,
        accountRequestOccurred: false,
        openOrdersRequestOccurred: false,
        positionsRequestOccurred: false,
        brokerMutationOccurred: false,
        orderSubmissionOccurred: false,
        cancelOccurred: false,
        replaceOccurred: false,
        liquidationOccurred: false
      },
      nextSafeAction: truth.configured
        ? "Reload backend launch readiness; do not use offline sample authority for PAPER start decisions."
        : "Open Keys & Providers and save Alpaca PAPER credentials locally; never paste secrets into chat or tracked files.",
      safety: {
        paperStartAllowed: false,
        liveEnabled: false,
        realMoneyEnabled: false,
        brokerMutationOccurred: false,
        secretsValuesExposed: false,
        rawSecretValuesIncluded: false
      }
    };
  }

  function credentialSetupWithProviderTruth(setup, state) {
    const base = setup && setup.source && !isMockAuthoritySource(setup.source)
      ? setup
      : buildCredentialSetupFromBackendState(state);
    const truth = alpacaPaperCredentialTruth(state);
    return {
      ...base,
      requiredCredentials: truth.rows,
      missingFields: truth.missingFields,
      valuesHidden: true,
      safety: {
        ...(base.safety || {}),
        secretsValuesExposed: false,
        rawSecretValuesIncluded: false
      }
    };
  }

  function buildBackendConnectedRunPaperState(state, reason) {
    const launch = (state && state.launchReadiness) || {};
    const sup = (state && state.supervisor) || {};
    const baseline = paperBaselineFromState(state, {});
    const credentialTruth = alpacaPaperCredentialTruth(state);
    const endpoint = endpointTruthFromState(state);
    const activeRuntime = Boolean(sup.sessionId && sup.sessionId !== "none")
      || ["RUNNING", "STARTING", "STOP_REQUESTED"].includes(String(sup.processState || sup.state || "").toUpperCase());
    const reasonText = String(reason || "");
    const controlStateCode = paperControlStateFailureCode(reasonText);
    const paperControlStateUnavailable = reasonText.includes("paper-control-state");
    const credentialSource = String(credentialTruth.source || "");
    const credentialStatusUnavailable = paperControlStateUnavailable
      && (!credentialSource || credentialSource === "BACKEND_UNAVAILABLE" || credentialSource === "CREDENTIAL_STATUS_UNAVAILABLE");
    const reasonCode = activeRuntime
      ? "SUPERVISOR_PROCESS_RUNNING_OR_RECENT"
      : (paperControlStateUnavailable ? controlStateCode : "BACKEND_LAUNCH_READINESS_UNAVAILABLE");
    const mismatchCodes = runPaperSourceMismatchCodes(state, launch.runPaperOperatorState || {});
    const reasonCodes = uniqueCodes([reasonCode].concat(mismatchCodes));
    const detail = activeRuntime
      ? "PAPER supervisor process is attached; duplicate start is blocked."
      : (reasonCode === "PAPER_CONTROL_STATE_TIMEOUT"
        ? "Backend is running, but PAPER control-state endpoint timed out. Fix /operator/paper-control-state before starting PAPER."
        : (paperControlStateUnavailable
          ? `Backend is running, but canonical PAPER control-state authority did not return current state: ${reason || "unknown endpoint failure"}.`
          : `Backend status is connected, but canonical PAPER start authority did not return current state: ${reason || "unknown endpoint failure"}.`));
    const overallLabel = activeRuntime ? "PAPER supervisor running" : "Run PAPER authority unavailable";
    const baselineSource = String(baseline.source || "");
    const baselineStatusUnavailable = paperControlStateUnavailable
      && baseline.accepted !== true
      && (!baselineSource || baselineSource === "BACKEND_UNAVAILABLE" || baselineSource === "CONTROL_STATE_UNAVAILABLE");
    const displayedBaseline = baselineStatusUnavailable
      ? {
          source: "CONTROL_STATE_UNAVAILABLE",
          schemaVersion: "paper-baseline-view-v1",
          status: "CONTROL_STATE_UNAVAILABLE",
          decision: "PAPER_CONTROL_STATE_TIMEOUT",
          accepted: false,
          policy: "ADOPT_EXISTING_POSITIONS_PROTECTED",
          positionCount: 0,
          positionSymbols: [],
          openOrderCount: 0,
          endpointFamily: endpoint.family || "paper",
          liveLocked: true,
          realMoneyBlocked: true,
          startReady: false,
          reason: "Baseline launch authority is unavailable until /operator/paper-control-state returns.",
          nextSafeAction: "Backend is running, but PAPER control-state endpoint timed out. Fix /operator/paper-control-state before starting PAPER.",
          baselineSnapshotId: null,
          snapshotHash: null,
          acceptedAt: null,
          protectedSymbols: [],
          sameSymbolTradingPolicy: "CONTROL_STATE_UNAVAILABLE",
          suppressPortfolioFallback: true,
          brokerMutationOccurred: false,
          tradingMutationOccurred: false,
          alpacaNetworkCallOccurred: false,
          secretsValuesExposed: false
        }
      : baseline;
    const rawCredentialSetup = buildCredentialSetupFromBackendState(state);
    const credentialSetup = credentialStatusUnavailable
      ? {
          ...rawCredentialSetup,
          source: "CREDENTIAL_STATUS_UNAVAILABLE",
          overallStatus: {
            code: "UNKNOWN",
            label: "Credential status unavailable",
            severity: "blocked",
            detail: "Backend is connected, but credential truth is unavailable for this Run PAPER authority check; raw values remain hidden."
          },
          requiredCredentials: [
            { name: "APCA_API_KEY_ID", present: false, displayValue: "unknown", source: "CREDENTIAL_STATUS_UNAVAILABLE", rawValueExposed: false },
            { name: "APCA_API_SECRET_KEY", present: false, displayValue: "unknown", source: "CREDENTIAL_STATUS_UNAVAILABLE", rawValueExposed: false }
          ],
          missingFields: []
        }
      : rawCredentialSetup;
    return {
      source: "OPERATOR_BACKEND_DEGRADED_RUN_PAPER_VIEW",
      schemaVersion: "run-paper-command-center-v1",
      overallStatus: {
        code: "BLOCKED",
        label: overallLabel,
        severity: activeRuntime ? "yellow" : "red",
        detail
      },
      canRunPaper: {
        allowed: false,
        label: "Start blocked",
        reason: detail,
        reasonCodes,
        warningCodes: launch.backendDegradedReasons || [],
        usesExistingGovernedStartIntent: "/operator/intent/paper/start",
        requiresOperatorConfirmations: true
      },
      nextSafeAction: activeRuntime
        ? "Monitor the attached PAPER supervisor. Do not start a second run."
        : (reasonCode === "PAPER_CONTROL_STATE_TIMEOUT"
          ? "Backend is running, but PAPER control-state endpoint timed out. Fix /operator/paper-control-state before starting PAPER."
          : "Reload backend launch readiness and fix the endpoint failure before pressing Start."),
      endpoint,
      credentials: {
        label: credentialStatusUnavailable
          ? "Credential status unavailable"
          : (credentialTruth.configured ? "Alpaca PAPER credentials configured" : "Alpaca PAPER credentials missing"),
        configured: credentialStatusUnavailable ? false : credentialTruth.configured,
        missingFields: credentialStatusUnavailable ? [] : credentialTruth.missingFields,
        source: credentialStatusUnavailable ? "CREDENTIAL_STATUS_UNAVAILABLE" : credentialTruth.source,
        precedence: credentialTruth.precedence,
        rawSecretValuesIncluded: false,
        secretsValuesExposed: false
      },
      paperCredentialSetup: credentialSetup,
      paperBaseline: displayedBaseline,
      runtime: {
        label: activeRuntime ? "PAPER supervisor process is attached" : "No active PAPER run",
        state: sup.state || sup.processState || "UNKNOWN",
        processState: sup.processState || "UNKNOWN",
        activeSessionId: sup.sessionId && sup.sessionId !== "none" ? sup.sessionId : null,
        paperStartRefusalReason: sup.paperStartRefusalReason || (activeRuntime ? "SUPERVISOR_PROCESS_RUNNING_OR_RECENT" : reasonCode),
        paperStopAllowed: sup.paperStopAllowed === true,
        safeStopStatus: launch.safeStopStatus || "UNKNOWN"
      },
      brokerTruth: brokerTruthFromState(state),
      safetyLocks: {
        live: { label: "Live locked", locked: true, enabled: false },
        realMoney: { label: "Real money blocked", blocked: true, enabled: false },
        manualTrading: { label: "Manual trading unavailable", available: false },
        forceTrade: { label: "Force trade unavailable", available: false },
        brokerMutation: { label: "No broker mutation from this readiness view", occurred: false }
      },
      advanced: {
        finalLaunchReadiness: "BLOCKED",
        reasonCodes: uniqueCodes(reasonCodes.concat(launch.backendDegradedReasons || [])),
        checks: launch.checks || [],
        paperEndpointDisplay: endpoint.display,
        paperEndpointFamily: endpoint.family,
        paperEndpointHost: endpoint.host,
        paperEndpointBlockerCode: endpoint.blockerCode,
        alpacaEndpointConfigured: endpoint.configured,
        alpacaEndpointSource: endpoint.source,
        alpacaPaperEndpointValid: endpoint.valid,
        alpacaLiveEndpointBlocked: true,
        paperStartAllowed: false,
        launchReadinessStartAllowed: false,
        brokerMutationOccurred: false,
        tradingMutationOccurred: false,
        liveEnabled: false,
        realMoneyEnabled: false,
        secretsValuesExposed: false,
        backendDegradedReasons: uniqueCodes((launch.backendDegradedReasons || []).concat(mismatchCodes))
      }
    };
  }

  function paperControlStateFailureCode(reason) {
    const text = String(reason || "").toLowerCase();
    if (text.includes("timeout") || text.includes("aborterror")) return "PAPER_CONTROL_STATE_TIMEOUT";
    if (text.includes("paper-control-state")) return "PAPER_CONTROL_STATE_UNAVAILABLE";
    return "BACKEND_LAUNCH_READINESS_UNAVAILABLE";
  }

  function buildBackendUnavailableRunPaperState(reason) {
    const detail = `Operator backend is unavailable: ${reason || "status endpoint did not respond"}. Start authority, credentials, baseline, and broker truth cannot be proven.`;
    return {
      source: "BACKEND_UNAVAILABLE_RUN_PAPER_VIEW",
      schemaVersion: "run-paper-command-center-v1",
      overallStatus: {
        code: "BLOCKED",
        label: "Operator backend unavailable",
        severity: "red",
        detail
      },
      canRunPaper: {
        allowed: false,
        label: "Start blocked",
        reason: detail,
        reasonCodes: ["BACKEND_UNAVAILABLE"],
        warningCodes: [],
        usesExistingGovernedStartIntent: "/operator/intent/paper/start",
        requiresOperatorConfirmations: true
      },
      nextSafeAction: "Start or restart the operator backend, then reload this page before using Run PAPER controls.",
      endpoint: {
        label: "PAPER endpoint not proven without backend",
        display: "unavailable",
        family: "unknown",
        host: "",
        source: "BACKEND_UNAVAILABLE",
        configured: false,
        valid: false,
        status: "BACKEND_UNAVAILABLE",
        blockerCode: "BACKEND_UNAVAILABLE",
        operatorAction: "Start the operator backend before reading endpoint authority."
      },
      credentials: {
        label: "Credential truth unavailable without backend",
        configured: false,
        missingFields: ["APCA_API_KEY_ID", "APCA_API_SECRET_KEY"],
        source: "BACKEND_UNAVAILABLE",
        precedence: "ENV_PRESENT_OVERRIDES_LOCAL_SECRET",
        rawSecretValuesIncluded: false,
        secretsValuesExposed: false
      },
      paperCredentialSetup: {
        source: "BACKEND_UNAVAILABLE",
        schemaVersion: "paper-credential-setup-v1",
        overallStatus: {
          code: "UNKNOWN",
          label: "Credential truth unavailable",
          severity: "blocked",
          detail: "Operator backend is unavailable; raw values remain hidden and credential presence is not guessed."
        },
        requiredCredentials: [
          { name: "APCA_API_KEY_ID", present: false, displayValue: "unknown", source: "BACKEND_UNAVAILABLE", rawValueExposed: false },
          { name: "APCA_API_SECRET_KEY", present: false, displayValue: "unknown", source: "BACKEND_UNAVAILABLE", rawValueExposed: false }
        ],
        missingFields: ["APCA_API_KEY_ID", "APCA_API_SECRET_KEY"],
        valuesHidden: true,
        endpoint: {
          display: "unavailable",
          family: "unknown",
          host: "",
          source: "BACKEND_UNAVAILABLE",
          configured: false,
          paperEndpointValid: false,
          liveEndpointBlocked: true,
          blockerCode: "BACKEND_UNAVAILABLE"
        },
        approvedSecretPath: {
          label: "Keys & Providers -> Alpaca PAPER Broker/Data -> Save local credentials",
          storageType: "operator_secret_file",
          relativePath: ".operator_secrets/provider_credentials.json",
          credentialPrecedence: "ENV_PRESENT_OVERRIDES_LOCAL_SECRET",
          gitignored: true,
          safeInstruction: "Start the operator backend before editing credential presence.",
          forbiddenInstruction: "Do not paste credentials into chat, do not commit .env files, and do not put raw secrets in tracked files."
        },
        preflightGate: {
          readOnlyPreflightAuthorized: false,
          readOnlyPreflightAvailable: false,
          accountCheckStatus: "backend_unavailable",
          openOrdersCheckStatus: "backend_unavailable",
          positionsCheckStatus: "backend_unavailable",
          lastPreflightAt: null,
          lastPreflightResult: null,
          statusLabel: "Backend unavailable",
          detail: "Read-only preflight truth cannot be shown until the operator backend is connected.",
          explicitApprovalRequired: true,
          futureChecks: ["GET /v2/account", "GET /v2/orders?status=open", "GET /v2/positions"],
          alpacaNetworkCallOccurred: false,
          accountRequestOccurred: false,
          openOrdersRequestOccurred: false,
          positionsRequestOccurred: false,
          brokerMutationOccurred: false,
          orderSubmissionOccurred: false,
          cancelOccurred: false,
          replaceOccurred: false,
          liquidationOccurred: false
        },
        nextSafeAction: "Start or restart the operator backend, then reload the operator UI.",
        safety: {
          paperStartAllowed: false,
          liveEnabled: false,
          realMoneyEnabled: false,
          brokerMutationOccurred: false,
          secretsValuesExposed: false,
          rawSecretValuesIncluded: false
        }
      },
      paperBaseline: {
        source: "BACKEND_UNAVAILABLE",
        schemaVersion: "paper-baseline-view-v1",
        status: "UNKNOWN",
        decision: "BACKEND_UNAVAILABLE",
        accepted: false,
        policy: "ADOPT_EXISTING_POSITIONS_PROTECTED",
        positionCount: 0,
        positionSymbols: [],
        openOrderCount: 0,
        endpointFamily: "unknown",
        liveLocked: true,
        realMoneyBlocked: true,
        startReady: false,
        reason: "Baseline truth is unavailable until backend state is loaded.",
        nextSafeAction: "Start or restart the operator backend, then reload baseline truth.",
        baselineSnapshotId: null,
        snapshotHash: null,
        acceptedAt: null,
        protectedSymbols: [],
        sameSymbolTradingPolicy: "BLOCK_BASELINE_SYMBOL_TRADES_UNTIL_RUN_LOT_TRACKING",
        brokerMutationOccurred: false,
        tradingMutationOccurred: false,
        alpacaNetworkCallOccurred: false,
        secretsValuesExposed: false
      },
      runtime: {
        label: "Backend unavailable",
        state: "UNKNOWN",
        processState: "UNKNOWN",
        activeSessionId: null,
        paperStartRefusalReason: "BACKEND_UNAVAILABLE",
        paperStopAllowed: false,
        safeStopStatus: "UNKNOWN"
      },
      brokerTruth: {
        status: "BACKEND_UNAVAILABLE",
        label: "Broker truth unavailable",
        detail: "No broker portfolio truth is shown without the operator backend.",
        brokerConfirmed: false,
        brokerReadOccurred: false,
        brokerReadAttempted: false,
        brokerMutationOccurred: false,
        orderSubmissionOccurred: false,
        cancelOccurred: false,
        liquidationOccurred: false
      },
      safetyLocks: {
        live: { label: "Live locked", locked: true, enabled: false },
        realMoney: { label: "Real money blocked", blocked: true, enabled: false },
        manualTrading: { label: "Manual trading unavailable", available: false },
        forceTrade: { label: "Force trade unavailable", available: false },
        brokerMutation: { label: "No broker mutation", occurred: false }
      },
      advanced: {
        finalLaunchReadiness: "BLOCKED",
        reasonCodes: ["BACKEND_UNAVAILABLE"],
        checks: [],
        paperEndpointDisplay: "unavailable",
        paperEndpointFamily: "unknown",
        paperEndpointHost: "",
        paperEndpointBlockerCode: "BACKEND_UNAVAILABLE",
        alpacaEndpointConfigured: false,
        alpacaEndpointSource: "BACKEND_UNAVAILABLE",
        alpacaPaperEndpointValid: false,
        alpacaLiveEndpointBlocked: true,
        paperStartAllowed: false,
        launchReadinessStartAllowed: false,
        brokerMutationOccurred: false,
        tradingMutationOccurred: false,
        liveEnabled: false,
        realMoneyEnabled: false,
        secretsValuesExposed: false,
        backendDegradedReasons: [detail]
      }
    };
  }

  function buildProductionUnavailableState(reason) {
    const state = clone(mockData || {});
    const detail = reason || "operator backend unavailable";
    state.meta = {
      ...(state.meta || {}),
      dataSource: "BACKEND_UNAVAILABLE",
      buildMode: "production_backend_required",
      backendStatus: `backend unavailable: ${detail}`,
      fetchFailures: [detail],
      runtimeCommit: "UNKNOWN",
      lastUpdated: new Date().toISOString()
    };
    state.status = {
      ...(state.status || {}),
      botStatus: "BACKEND_UNAVAILABLE",
      runtimeMode: "PAPER",
      activeProfile: "UNKNOWN",
      broker: "UNKNOWN",
      endpoint: "BACKEND_UNAVAILABLE",
      marketData: "BACKEND_UNAVAILABLE",
      universe: [],
      liveBlocked: true,
      realMoneyBlocked: true,
      dominantBlocker: "BACKEND_UNAVAILABLE",
      lastDecision: "Operator backend unavailable; no broker-confirmed truth is loaded."
    };
    state.supervisor = {
      ...(state.supervisor || {}),
      state: "BACKEND_UNAVAILABLE",
      sessionId: "none",
      pid: "none",
      processState: "BACKEND_UNAVAILABLE",
      watchlist: [],
      paperStartAllowed: false,
      paperStopAllowed: false,
      paperStartRefusalReason: "BACKEND_UNAVAILABLE",
      paperStopRefusalReason: "BACKEND_UNAVAILABLE",
      maxPaperDurationSeconds: 432000,
      runnerMaxPaperDurationSeconds: 432000,
      runtimeAttachmentDetail: "Operator backend unavailable."
    };
    state.launchReadiness = {
      source: "BACKEND_UNAVAILABLE",
      finalLaunchReadiness: "BLOCKED",
      checks: [],
      reasonCodes: ["BACKEND_UNAVAILABLE"],
      alpacaPaperCredentialsConfigured: false,
      paperEndpointOnly: false,
      paperEndpointStatus: "BACKEND_UNAVAILABLE",
      paperEndpointSource: "BACKEND_UNAVAILABLE",
      paperEndpointOperatorAction: "Start the operator backend before using Run PAPER controls.",
      paperEndpointDisplay: "unavailable",
      paperEndpointFamily: "unknown",
      paperEndpointHost: "",
      paperEndpointBlockerCode: "BACKEND_UNAVAILABLE",
      alpacaEndpointConfigured: false,
      alpacaPaperEndpointValid: false,
      alpacaLiveEndpointBlocked: true,
      paperStartAllowed: false,
      runPaperOperatorState: buildBackendUnavailableRunPaperState(detail),
      safeStopStatus: "UNKNOWN",
      portfolioReadAvailability: "BACKEND_UNAVAILABLE",
      backendDegradedReasons: [detail]
    };
    state.paperControlState = {
      source: "BACKEND_UNAVAILABLE",
      paperStartAllowed: false,
      paperStopAllowed: false,
      dominantBlocker: "BACKEND_UNAVAILABLE",
      reasonCodes: ["BACKEND_UNAVAILABLE"]
    };
    state.paperBaseline = state.launchReadiness.runPaperOperatorState.paperBaseline;
    state.credentials = {
      source: "BACKEND_UNAVAILABLE",
      configuredCount: 0,
      providerCount: 0,
      precedence: "ENV_PRESENT_OVERRIDES_LOCAL_SECRET",
      providers: []
    };
    state.providerReadiness = {
      ...(state.providerReadiness || {}),
      providers: [],
      providerCount: 0,
      counts: {},
      readyOrConfiguredCount: 0,
      missingCredentialsCount: 0,
      notImplementedCount: 0
    };
    state.portfolio = {
      source: "BACKEND_UNAVAILABLE",
      dataSource: "BACKEND_UNAVAILABLE",
      status: "BACKEND_UNAVAILABLE",
      unavailableReason: "OPERATOR_BACKEND_UNAVAILABLE",
      detail: state.meta.backendStatus,
      message: "Operator backend unavailable; broker-confirmed portfolio truth is not loaded.",
      empty: true,
      dataFreshnessTs: null,
      brokerReadAttempted: false,
      brokerReadOccurred: false,
      brokerMutationOccurred: false,
      summary: {
        totalEquity: null,
        cash: null,
        buyingPower: null,
        totalMarketValue: null,
        positionCount: 0,
        openOrderCount: 0
      },
      positions: [],
      openOrders: [],
      positionIntelligence: []
    };
    state.positions = [];
    state.orders = [];
    return state;
  }

  function reconcileBackendConnectedAuthority(state, endpointFailures) {
    const failures = endpointFailures || {};
    const launch = state.launchReadiness || {};
    const op = launch.runPaperOperatorState || {};
    const launchFailure = failures.launchReadiness || "backend launch readiness payload missing";
    const launchMissing = !launch.source || isMockAuthoritySource(launch.source);
    if (launchMissing || !op.source || runPaperStateHasMockAuthority(op)) {
      const mismatchCodes = runPaperSourceMismatchCodes(state, op);
      const reasonCodes = uniqueCodes(["BACKEND_LAUNCH_READINESS_UNAVAILABLE"].concat(mismatchCodes));
      state.launchReadiness = {
        source: "OPERATOR_BACKEND_DEGRADED",
        finalLaunchReadiness: "BLOCKED",
        checks: [
          {
            checkId: "backend_launch_readiness",
            title: "Backend launch readiness",
            status: "BLOCKED",
            detail: launchMissing ? launchFailure : "Backend Run PAPER view model was stale or sample-sourced.",
            blocker: true,
            warning: false
          }
        ],
        reasonCodes,
        alpacaPaperCredentialsConfigured: alpacaPaperCredentialTruth(state).configured,
        paperEndpointOnly: endpointTruthFromState(state).valid,
        paperEndpointStatus: endpointTruthFromState(state).status,
        paperEndpointSource: endpointTruthFromState(state).source,
        paperEndpointOperatorAction: endpointTruthFromState(state).operatorAction,
        paperEndpointDisplay: endpointTruthFromState(state).display,
        paperEndpointFamily: endpointTruthFromState(state).family,
        paperEndpointHost: endpointTruthFromState(state).host,
        paperEndpointBlockerCode: endpointTruthFromState(state).blockerCode,
        alpacaEndpointConfigured: endpointTruthFromState(state).configured,
        alpacaPaperEndpointValid: endpointTruthFromState(state).valid,
        alpacaLiveEndpointBlocked: true,
        paperStartAllowed: false,
        runPaperOperatorState: buildBackendConnectedRunPaperState(state, launchFailure),
        safeStopStatus: launch.safeStopStatus || "UNKNOWN",
        portfolioReadAvailability: launch.portfolioReadAvailability || "UNKNOWN",
        backendDegradedReasons: uniqueCodes((launch.backendDegradedReasons || []).concat([launchFailure]).concat(mismatchCodes))
      };
      return;
    }
    const baseline = paperBaselineFromState(state, op);
    if (baseline && !isMockAuthoritySource(baseline.source)) {
      op.paperBaseline = baseline;
    }
    op.paperCredentialSetup = credentialSetupWithProviderTruth(op.paperCredentialSetup, state);
    const truth = alpacaPaperCredentialTruth(state);
    op.credentials = {
      label: truth.configured ? "Alpaca PAPER credentials configured" : "Alpaca PAPER credentials missing",
      configured: truth.configured,
      missingFields: truth.missingFields,
      source: truth.source,
      precedence: truth.precedence,
      rawSecretValuesIncluded: false,
      secretsValuesExposed: false
    };
    if (!op.brokerTruth || isMockAuthoritySource(op.brokerTruth.status)) {
      op.brokerTruth = brokerTruthFromState(state);
    }
    state.launchReadiness.runPaperOperatorState = op;
    state.paperBaseline = baseline;
  }

  function screenTitle(id) {
    const found = screens.find(([screenId]) => screenId === id);
    return found ? found[1] : "Portfolio Home";
  }

  function table(headers, rows) {
    return `
      <div class="table-wrap" tabindex="0">
        <table class="table">
          <thead><tr>${headers.map((h) => `<th>${escapeHtml(h)}</th>`).join("")}</tr></thead>
          <tbody>
            ${rows.map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join("")}</tr>`).join("")}
          </tbody>
        </table>
      </div>
    `;
  }

  function metric(label, value, color) {
    return `
      <div class="card metric">
        <div class="metric-label">${escapeHtml(label)}</div>
        <div class="metric-value mono">${color ? badge(value, color) : escapeHtml(value)}</div>
      </div>
    `;
  }

  function header(title, subtitle, state) {
    return `
      <div class="screen-header">
        <div>
          <h1 class="screen-title">${escapeHtml(title)}</h1>
          <p class="screen-subtitle">${escapeHtml(subtitle)}</p>
        </div>
        ${state ? badge(state, statusColor(state)) : ""}
      </div>
    `;
  }

  function kv(items) {
    return `<div class="kv">${items.map(([k, v]) => `<div>${escapeHtml(k)}</div><div>${v}</div>`).join("")}</div>`;
  }

  function operatorApiBase() {
    if (window.PK_OPERATOR_API_BASE) return window.PK_OPERATOR_API_BASE;
    const params = new URLSearchParams(window.location.search || "");
    return params.get("apiBase") || "";
  }

  function renderTopBar() {
    const s = data.status;
    const endpointLabel = String(s.endpoint || "").includes("paper-api") ? "PAPER endpoint" : pick(s.endpoint, "endpoint unknown");
    const brandSubtext = document.querySelector(".brand .muted.mono");
    if (brandSubtext) {
      brandSubtext.textContent = sourceSubtext();
    }
    document.querySelector(".status-strip").innerHTML = [
      badge(sourceLabel(), dataSourceColor()),
      badge(s.runtimeMode, "green"),
      badge(s.activeProfile, "cyan"),
      badge(`Runtime: ${data.supervisor.processState || s.botStatus || "UNKNOWN"}`, statusColor(data.supervisor.processState || s.botStatus || "UNKNOWN")),
      badge(`Broker: ${s.broker}`, "blue"),
      badge(endpointLabel, endpointLabel === "PAPER endpoint" ? "green" : "yellow"),
      badge("Live locked", "green"),
      badge("Real-money blocked", "green"),
      backendDegradedCount()
        ? `<button class="status-detail-link" type="button" data-screen-shortcut="diagnostics">View details</button>`
        : ""
    ].filter(Boolean).join("");
  }

  function legacyPaperLaunchDisabledReason() {
    const launch = data.launchReadiness || {};
    const sup = data.supervisor || {};
    if (!backendConnected()) return "Disabled: operator backend unavailable; start authority cannot be proven.";
    if ((launch.finalLaunchReadiness || "").includes("BLOCKED")) {
      const reason = (launch.reasonCodes || [])[0] || "launch readiness blocked";
      const check = (launch.checks || []).find((item) => item.checkId === reason || item.blocker === true);
      return `Disabled: ${(check && (check.detail || check.title)) || reason}.`;
    }
    if (sup.paperStartAllowed !== true) {
      return `Disabled: ${sup.paperStartRefusalReason || "supervisor start not allowed"}.`;
    }
    return "";
  }

  function runPaperState() {
    if (data.paperControlState && data.paperControlState.source === "OPERATOR_PAPER_CONTROL_STATE") {
      return buildRunPaperStateFromControlState(data.paperControlState, data);
    }
    const op = (data.launchReadiness && data.launchReadiness.runPaperOperatorState) || {};
    if (!backendConnected() && runPaperStateHasMockAuthority(op)) {
      return buildBackendUnavailableRunPaperState(data.meta.backendStatus || "operator backend status endpoint did not respond");
    }
    if (backendConnected() && (!op.source || runPaperStateHasMockAuthority(op))) {
      return buildBackendConnectedRunPaperState(data, "backend Run PAPER authority payload was missing or stale");
    }
    return op;
  }

  function severityColor(value) {
    const v = String(value || "").toLowerCase();
    if (["green", "yellow", "red", "gray", "cyan", "blue", "purple"].includes(v)) return v;
    return statusColor(value);
  }

  function paperLaunchDisabledReason() {
    const op = runPaperState();
    const canRun = op.canRunPaper || {};
    const overall = op.overallStatus || {};
    const baseline = paperBaselineFromState(data, op);
    const portfolio = data.portfolio || {};
    const positionCount = Number((portfolio.summary && portfolio.summary.positionCount) || (portfolio.positions || []).length || baseline.positionCount || 0);
    if (op.source && canRun.allowed !== true) {
      const reason = canRun.reason || overall.detail || "backend start authority is blocked";
      return `Disabled: ${reason}${/[.!?]$/.test(reason) ? "" : "."}`;
    }
    if (baseline.accepted !== true && positionCount > 0) {
      return "Disabled: Existing positions require baseline adoption.";
    }
    return legacyPaperLaunchDisabledReason();
  }

  function renderRunPaperProofTile(label, value, detail, color) {
    return `
      <div class="run-paper-proof-tile">
        <div class="proof-label">${escapeHtml(label)}</div>
        <div class="proof-value">${color ? badge(value, color) : escapeHtml(value || "unknown")}</div>
        <div class="proof-detail">${escapeHtml(detail || "")}</div>
      </div>
    `;
  }

  function renderSessionLifecycleCard(title, mode) {
    const sup = data.supervisor || {};
    const sessionId = sup.sessionId || "none";
    const status = sup.processState || sup.lifecycleStatus || "NO_ACTIVE_PAPER_RUN";
    const active = isActiveSessionStatus(status);
    const terminal = isTerminalSessionStatus(sup.rawProcessState || status);
    const rows = [
      ["session_id", escapeHtml(sessionId)],
      ["status", badge(status, statusColor(status))],
      ["raw_status", badge(sup.rawProcessState || status, statusColor(sup.rawProcessState || status))],
      ["pid", escapeHtml(active ? (sup.pid || "unknown") : (sup.pid || "not active"))],
      ["started_at", escapeHtml(sup.startedAt || "not available")],
      ["ended_at", escapeHtml(sup.endedAt || (terminal ? "not available" : "not ended"))],
      ["exit_code", escapeHtml(sup.exitCode === undefined || sup.exitCode === null ? "not available" : sup.exitCode)],
      ["duration_seconds", escapeHtml(sup.durationSeconds === null || sup.durationSeconds === undefined ? "not available" : sup.durationSeconds)],
      ["watchlist", escapeHtml((sup.watchlist || []).join(", ") || "none")],
      ["profile", escapeHtml(sup.profile || data.status.activeProfile || "PAPER_IDLE")],
      ["stdout", escapeHtml(sup.wrapperStdoutPath || sup.stdoutPath || "not available")],
      ["stderr", escapeHtml(sup.wrapperStderrPath || sup.stderrPath || "not available")],
      ["child_stdout", escapeHtml(sup.childStdoutPath || "not available")],
      ["child_stderr", escapeHtml(sup.childStderrPath || "not available")],
      ["next_safe_action", escapeHtml(runPaperState().nextSafeAction || (active ? "Monitor the active PAPER run." : "Review readiness before starting another governed PAPER run."))]
    ];
    const content = `
        <div class="split">
          <h3>${escapeHtml(title || "Active Session")}</h3>
          ${badge(status, statusColor(status))}
        </div>
        ${kv(rows)}
        <div class="notice">${escapeHtml(sup.runtimeAttachmentDetail || "No runtime attachment detail loaded.")}</div>
    `;
    if (mode === "inline") {
      return `<div class="runtime-session-inline" data-runtime-session-card>${content}</div>`;
    }
    return `
      <div class="card span-6 runtime-session-card" data-runtime-session-card>
        ${content}
      </div>
    `;
  }

  function renderPaperCredentialSetup(setup) {
    const overall = setup.overallStatus || {};
    const endpoint = setup.endpoint || {};
    const secretPath = setup.approvedSecretPath || {};
    const preflight = setup.preflightGate || {};
    const safety = setup.safety || {};
    const rows = Array.isArray(setup.requiredCredentials) ? setup.requiredCredentials : [];
    const credentialCards = rows.map((row) => `
      <div class="run-paper-proof-tile credential-preflight-field" data-paper-credential-field="${escapeHtml(row.name || "unknown")}">
        <div class="proof-label">${escapeHtml(row.name || "Credential field")}</div>
        <div class="proof-value">${badge(row.present === true ? "present" : "missing", row.present === true ? "green" : "red")}</div>
        <div class="proof-detail">Value hidden; source ${escapeHtml(row.source || "NOT_CONFIGURED")}.</div>
      </div>
    `).join("");
    const preflightDetail = [
      `Account: ${preflight.accountCheckStatus || "not_run"}`,
      `open orders: ${preflight.openOrdersCheckStatus || "not_run"}`,
      `positions: ${preflight.positionsCheckStatus || "not_run"}`
    ].join("; ");
    const credentialNoticeClass = ["MISSING", "PARTIAL", "ERROR"].includes(overall.code) ? "error" : "";
    return `
      <section class="credential-preflight-panel" data-paper-credential-setup>
        <div class="split">
          <h4>Credential Setup + Read-Only Preflight Gate</h4>
          ${badge(overall.label || "Credential setup unknown", severityColor(overall.severity || overall.code || "blocked"))}
        </div>
        <div class="notice ${credentialNoticeClass}" data-paper-credential-top-message>${escapeHtml(overall.detail || "PAPER credential setup status unavailable.")}</div>
        <div class="run-paper-proof-grid compact-proof-grid">
          ${credentialCards || renderRunPaperProofTile("APCA credentials", "not loaded", "Backend did not return credential field rows.", "yellow")}
          ${renderRunPaperProofTile("Values hidden", setup.valuesHidden !== false ? "hidden" : "unsafe", "Presence only is shown; raw values are never printed in this UI.", setup.valuesHidden !== false ? "green" : "red")}
          ${renderRunPaperProofTile("Approved local path", secretPath.relativePath || ".operator_secrets/provider_credentials.json", secretPath.safeInstruction || "Use Keys & Providers to save local credentials.", "cyan")}
          ${renderRunPaperProofTile("Do not commit", "tracked files forbidden", secretPath.forbiddenInstruction || "Do not paste credentials into chat or commit raw secrets.", "red")}
          ${renderRunPaperProofTile("Credential endpoint", endpoint.display || "https://paper-api.alpaca.markets", `Family ${endpoint.family || "paper"}; source ${endpoint.source || "safe_default"}; live endpoint blocked ${endpoint.liveEndpointBlocked !== false ? "true" : "false"}.`, endpoint.paperEndpointValid !== false ? "green" : "red")}
          ${renderRunPaperProofTile("Read-only preflight", preflight.statusLabel || "Read-only PAPER preflight not run", `${preflight.detail || "Requires explicit Shan approval before Alpaca is called."} ${preflightDetail}.`, preflight.readOnlyPreflightAvailable === true ? "yellow" : "red")}
        </div>
        <div class="notice" data-paper-credential-next-action>Credential next safe action: ${escapeHtml(setup.nextSafeAction || "Open Keys & Providers and save Alpaca PAPER credentials locally.")}</div>
        <div class="notice mono" data-paper-preflight-boundary>Read-only preflight requires explicit approval before Alpaca is called; it will check account, open orders, and positions only. It will not place, cancel, replace, liquidate, enable live, enable real money, or start PAPER.</div>
        <details class="ai-context-details" data-paper-credential-advanced>
          <summary>Advanced credential and preflight proof</summary>
          ${kv([
            ["setup_schema_version", tokenText(setup.schemaVersion || "paper-credential-setup-v1")],
            ["approved_secret_path", escapeHtml(secretPath.relativePath || ".operator_secrets/provider_credentials.json")],
            ["credential_precedence", tokenText(secretPath.credentialPrecedence || "ENV_PRESENT_OVERRIDES_LOCAL_SECRET")],
            ["read_only_preflight_authorized", badge(preflight.readOnlyPreflightAuthorized === true ? "true" : "false", preflight.readOnlyPreflightAuthorized === true ? "yellow" : "green")],
            ["read_only_preflight_available", badge(preflight.readOnlyPreflightAvailable === true ? "true" : "false", preflight.readOnlyPreflightAvailable === true ? "yellow" : "red")],
            ["account_request_occurred", badge(preflight.accountRequestOccurred === true ? "true" : "false", preflight.accountRequestOccurred === true ? "red" : "green")],
            ["open_orders_request_occurred", badge(preflight.openOrdersRequestOccurred === true ? "true" : "false", preflight.openOrdersRequestOccurred === true ? "red" : "green")],
            ["positions_request_occurred", badge(preflight.positionsRequestOccurred === true ? "true" : "false", preflight.positionsRequestOccurred === true ? "red" : "green")],
            ["alpaca_network_call_occurred", badge(preflight.alpacaNetworkCallOccurred === true ? "true" : "false", preflight.alpacaNetworkCallOccurred === true ? "red" : "green")],
            ["broker_mutation_occurred", badge(preflight.brokerMutationOccurred === true ? "true" : "false", preflight.brokerMutationOccurred === true ? "red" : "green")],
            ["paper_start_allowed", badge(safety.paperStartAllowed === true ? "true" : "false", safety.paperStartAllowed === true ? "green" : "red")],
            ["secrets_values_exposed", badge(safety.secretsValuesExposed === true ? "true" : "false", safety.secretsValuesExposed === true ? "red" : "green")]
          ])}
        </details>
      </section>
    `;
  }

  function renderPaperBaselinePanel(baseline, portfolio) {
    const summary = portfolio.summary || {};
    const positions = Array.isArray(portfolio.positions) ? portfolio.positions : [];
    const portfolioOrders = Array.isArray(portfolio.openOrders) ? portfolio.openOrders : [];
    const suppressPortfolioFallback = baseline.suppressPortfolioFallback === true || baseline.status === "CONTROL_STATE_UNAVAILABLE";
    const positionCount = baseline.accepted || suppressPortfolioFallback
      ? Number(baseline.positionCount || 0)
      : Number(summary.positionCount || positions.length || baseline.positionCount || 0);
    const openOrderCount = baseline.accepted || suppressPortfolioFallback
      ? Number(baseline.openOrderCount || 0)
      : Number(summary.openOrderCount || portfolioOrders.length || baseline.openOrderCount || 0);
    const symbols = baseline.accepted && baseline.positionSymbols && baseline.positionSymbols.length
      ? baseline.positionSymbols
      : positions.map((position) => position.symbol).filter(Boolean);
    const symbolText = symbols.length ? symbols.join(", ") : "none";
    const accepted = baseline.accepted === true;
    const hasExistingPositions = positionCount > 0;
    const controlStateUnavailable = suppressPortfolioFallback && baseline.status === "CONTROL_STATE_UNAVAILABLE";
    const statusTitle = accepted
      ? "Position-aware PAPER baseline accepted."
      : (controlStateUnavailable ? "Baseline launch authority unavailable." : (hasExistingPositions ? "Baseline adoption required - existing PAPER positions detected." : "No existing PAPER baseline accepted."));
    const explanation = accepted
      ? "This PAPER run starts from an accepted nonzero baseline. Existing positions are tracked separately from new run activity."
      : (controlStateUnavailable
          ? "Portfolio read may be available separately, but PAPER start authority cannot use baseline state until control-state returns."
          : (hasExistingPositions
          ? "Reset is not required. To run PAPER from this account, accept these positions as the starting baseline."
          : "A clean account can proceed only after the normal read-only preflight proves account, orders, and positions truth."));
    const policyDetail = accepted || hasExistingPositions
      ? "Default policy: protected baseline. Existing positions count against risk/exposure; existing baseline quantities will not be sold by default; same-symbol trading is blocked until run lot tracking is available."
      : "Baseline policy will be selected after read-only preflight truth exists.";
    const startDetail = accepted
      ? "Ready for a short position-aware PAPER smoke only if all backend gates pass. Not 72-hour ready yet."
      : (controlStateUnavailable ? "Start remains disabled until canonical PAPER control state returns." : (hasExistingPositions ? "Start remains disabled until baseline is accepted and all other gates pass." : "Start remains governed by backend launch readiness."));
    const acceptDisabled = (!backendConnected() || accepted || !hasExistingPositions || openOrderCount !== 0) ? "disabled" : "";
    const acceptReason = accepted
      ? "Baseline already accepted."
      : (!hasExistingPositions
          ? "No existing positions require adoption."
          : (openOrderCount !== 0 ? "Open orders must be zero before baseline adoption." : "Local-only acceptance is available; it does not call Alpaca or mutate broker state."));
    return `
      <section class="paper-baseline-panel ${accepted ? "accepted" : (hasExistingPositions ? "required" : "")}" data-paper-baseline-panel>
        <div class="split">
          <h4>${escapeHtml(statusTitle)}</h4>
          ${badge(accepted ? "accepted" : (hasExistingPositions ? "adoption required" : "not run"), accepted ? "green" : (hasExistingPositions ? "yellow" : "gray"))}
        </div>
        <p class="muted">${escapeHtml(explanation)}</p>
        <div class="run-paper-proof-grid compact-proof-grid">
          ${renderRunPaperProofTile("Existing positions", `${positionCount}`, `Symbols: ${symbolText}.`, hasExistingPositions ? "yellow" : "green")}
          ${renderRunPaperProofTile("Open orders", `${openOrderCount}`, openOrderCount === 0 ? "Zero open orders confirmed by current view." : "Open orders block baseline adoption; no cancel control is exposed.", openOrderCount === 0 ? "green" : "red")}
          ${renderRunPaperProofTile("Account", summary.accountStatus || "UNKNOWN", `Endpoint ${baseline.endpointFamily || "paper"}; buying power ${summary.buyingPower || "unavailable"}; equity ${summary.totalEquity || "unavailable"}.`, (summary.accountBlocked || summary.tradingBlocked) ? "red" : "green")}
          ${renderRunPaperProofTile("Policy", baseline.policy || "ADOPT_EXISTING_POSITIONS_PROTECTED", policyDetail, "cyan")}
          ${renderRunPaperProofTile("P&L attribution", "nonzero baseline labeled", "Total account P&L includes baseline carry. Bot incremental P&L requires run fill attribution.", "cyan")}
          ${renderRunPaperProofTile("Start readiness", accepted ? "position-aware smoke path" : "blocked pending baseline", startDetail, accepted ? "yellow" : "red")}
        </div>
        ${accepted ? `<div class="notice" data-paper-baseline-accepted-text>Position-aware PAPER baseline accepted. Snapshot ${escapeHtml(baseline.baselineSnapshotId || "unknown")} at ${escapeHtml(baseline.acceptedAt || "unknown")}.</div>` : ""}
        ${hasExistingPositions && !accepted ? `<div class="notice" data-paper-baseline-required-text>Existing positions require baseline adoption. Reset is not required.</div>` : ""}
        <div class="button-row">
          <button class="intent-button paper" data-intent="paper-baseline-accept" ${acceptDisabled}>Accept current positions as PAPER baseline</button>
          <span class="badge red">No liquidation / close / cancel controls</span>
        </div>
        <div class="notice ${acceptDisabled && !accepted ? "error" : ""}" data-paper-baseline-action-state>${escapeHtml(acceptReason)}</div>
        <details class="ai-context-details" data-paper-baseline-advanced>
          <summary>Advanced baseline proof</summary>
          ${kv([
            ["baseline_status", tokenText(baseline.status || "NOT_ACCEPTED")],
            ["baseline_snapshot_id", tokenText(baseline.baselineSnapshotId || "none")],
            ["snapshot_hash", tokenText(baseline.snapshotHash || "none")],
            ["accepted_at", escapeHtml(baseline.acceptedAt || "not accepted")],
            ["same_symbol_trading_policy", tokenText(baseline.sameSymbolTradingPolicy || "BLOCK_BASELINE_SYMBOL_TRADES_UNTIL_RUN_LOT_TRACKING")],
            ["baseline_account_equity", escapeHtml((baseline.pnlAttribution && baseline.pnlAttribution.baselineAccountEquity) || "unavailable")],
            ["baseline_positions_value", escapeHtml((baseline.pnlAttribution && baseline.pnlAttribution.baselinePositionsValue) || "unavailable")],
            ["run_incremental_equity_pnl_label", escapeHtml((baseline.pnlAttribution && baseline.pnlAttribution.runIncrementalEquityPnlLabel) || "pending")],
            ["broker_mutation_occurred", badge(baseline.brokerMutationOccurred === true ? "true" : "false", baseline.brokerMutationOccurred === true ? "red" : "green")],
            ["alpaca_network_call_occurred", badge(baseline.alpacaNetworkCallOccurred === true ? "true" : "false", baseline.alpacaNetworkCallOccurred === true ? "red" : "green")],
            ["secrets_values_exposed", badge(baseline.secretsValuesExposed === true ? "true" : "false", baseline.secretsValuesExposed === true ? "red" : "green")]
          ])}
        </details>
      </section>
    `;
  }

  function runPaperAdvancedRows(op, launch) {
    const advanced = op.advanced || {};
    return [
      ["data_source", tokenText(data.meta.dataSource || "UNKNOWN")],
      ["run_paper_state_source", tokenText(op.source || "UNKNOWN")],
      ["canonical_source_order", tokenText("paper-control-state > launch-readiness > latest-run > status > portfolio > credentials > paper-baseline > fail-closed")],
      ["final_launch_readiness", tokenText(advanced.finalLaunchReadiness || launch.finalLaunchReadiness || "UNKNOWN")],
      ["reason_codes", tokenText((advanced.reasonCodes || launch.reasonCodes || []).join(", ") || "none")],
      ["paper_endpoint_display", escapeHtml(advanced.paperEndpointDisplay || launch.paperEndpointDisplay || "unavailable")],
      ["paper_endpoint_family", tokenText(advanced.paperEndpointFamily || launch.paperEndpointFamily || "unknown")],
      ["paper_endpoint_host", escapeHtml(advanced.paperEndpointHost || launch.paperEndpointHost || "unavailable")],
      ["paper_endpoint_blocker_code", tokenText(advanced.paperEndpointBlockerCode || launch.paperEndpointBlockerCode || "none")],
      ["alpaca_endpoint_configured", badge(advanced.alpacaEndpointConfigured === true ? "true" : "false", advanced.alpacaEndpointConfigured === true ? "gray" : "cyan")],
      ["alpaca_endpoint_source", tokenText(advanced.alpacaEndpointSource || launch.paperEndpointSource || "UNKNOWN")],
      ["alpaca_paper_endpoint_valid", badge(advanced.alpacaPaperEndpointValid === true ? "true" : "false", advanced.alpacaPaperEndpointValid === true ? "green" : "red")],
      ["alpaca_live_endpoint_blocked", badge(advanced.alpacaLiveEndpointBlocked !== false ? "true" : "false", advanced.alpacaLiveEndpointBlocked !== false ? "red" : "yellow")],
      ["paper_start_allowed", badge(advanced.paperStartAllowed === true ? "true" : "false", advanced.paperStartAllowed === true ? "green" : "red")],
      ["launch_readiness_start_allowed", badge(advanced.launchReadinessStartAllowed === true ? "true" : "false", advanced.launchReadinessStartAllowed === true ? "green" : "red")],
      ["broker_mutation_occurred", badge(advanced.brokerMutationOccurred === true ? "true" : "false", advanced.brokerMutationOccurred === true ? "red" : "green")],
      ["trading_mutation_occurred", badge(advanced.tradingMutationOccurred === true ? "true" : "false", advanced.tradingMutationOccurred === true ? "red" : "green")],
      ["live_enabled", badge(advanced.liveEnabled === true ? "true" : "false", advanced.liveEnabled === true ? "red" : "green")],
      ["real_money_enabled", badge(advanced.realMoneyEnabled === true ? "true" : "false", advanced.realMoneyEnabled === true ? "red" : "green")],
      ["secrets_values_exposed", badge(advanced.secretsValuesExposed === true ? "true" : "false", advanced.secretsValuesExposed === true ? "red" : "green")]
    ];
  }

  function renderPaperLaunchControl(formId) {
    const launch = data.launchReadiness || {};
    const sup = data.supervisor || {};
    const op = runPaperState();
    const overall = op.overallStatus || {
      label: launch.finalLaunchReadiness || "Launch readiness unknown",
      code: launch.finalLaunchReadiness || "UNKNOWN",
      severity: statusColor(launch.finalLaunchReadiness || "UNKNOWN"),
      detail: "Launch readiness loaded from legacy fields."
    };
    const canRun = op.canRunPaper || {};
    const endpoint = op.endpoint || {};
    const credentials = op.credentials || {};
    const credentialSetup = op.paperCredentialSetup || {};
    const baseline = paperBaselineFromState(data, op);
    const runtime = op.runtime || {};
    const brokerTruth = op.brokerTruth || {};
    const safetyLocks = op.safetyLocks || {};
    const backendDisabledReason = paperLaunchDisabledReason();
    const draft = paperRunDraftForRender(formId);
    const bounds = paperDurationBounds();
    const { configuredMaxDuration, runnerMaxDuration, maxDuration, durationOptions } = bounds;
    const validation = paperDraftValidation(draft, bounds);
    const disabledReason = validation.valid ? backendDisabledReason : validation.detail;
    const startDisabled = disabledReason ? "disabled" : "";
    const watchlist = draft.watchlistRaw || defaultPaperWatchlist();
    const selectedDurationRaw = String(draft.durationRaw || bounds.defaultDuration);
    const customSelected = selectedDurationRaw === "custom" || !durationOptions.some(([seconds]) => String(seconds) === selectedDurationRaw);
    const runtimeAttachment = sup.sessionId && sup.sessionId !== "none"
      ? `PAPER run attached: ${sup.sessionId}`
      : (sup.paperStartAllowed === true ? "Ready. No PAPER run currently attached." : `No PAPER run currently attached; ${sup.paperStartRefusalReason || "start blocked"}.`);
    const endpointSourceLabel = endpoint.source || launch.paperEndpointSource || "UNKNOWN";
    const blockerText = canRun.allowed === true
      ? "No blocking readiness checks reported by backend start authority."
      : (canRun.reason || overall.detail || "Backend start authority is blocked.");
    const credentialDetail = credentials.configured === true
      ? `Source: ${credentials.source || "configured"}; precedence: ${credentials.precedence || "ENV_PRESENT_OVERRIDES_LOCAL_SECRET"}.`
      : `Missing fields: ${(credentials.missingFields || ["APCA_API_KEY_ID", "APCA_API_SECRET_KEY"]).join(", ")}.`;
    const safetyDetail = [
      safetyLocks.live && safetyLocks.live.locked ? "live locked" : "live status unknown",
      safetyLocks.realMoney && safetyLocks.realMoney.blocked ? "real money blocked" : "real money status unknown",
      safetyLocks.manualTrading && safetyLocks.manualTrading.available === false ? "manual trading unavailable" : "manual trading status unknown",
      safetyLocks.forceTrade && safetyLocks.forceTrade.available === false ? "force trade unavailable" : "force trade status unknown"
    ].join("; ");
    return `
      <div class="card span-12 paper-launch-card run-paper-command-center" data-run-paper-command-center data-paper-form-card="${escapeHtml(formId)}">
        <div class="split">
          <h3>Run PAPER Command Center</h3>
          ${badge(overall.label || overall.code || "UNKNOWN", severityColor(overall.severity || overall.code))}
        </div>
        <p class="muted">PAPER Launch Control. Starts the existing governed PAPER runner only. Current execution-authority max lease: ${escapeHtml(formatDuration(maxDuration))}. Long-running PAPER stays PAPER-only, lease-bound, supervised, and restart-auditable.</p>
        <div class="run-paper-status-banner ${escapeHtml(severityColor(overall.severity || overall.code))}" data-run-paper-top-status>
          <div>
            <div class="run-paper-status-title">${escapeHtml(overall.label || overall.code || "Readiness unknown")}</div>
            <div class="run-paper-status-detail">${escapeHtml(overall.detail || "Backend launch-readiness state is unavailable.")}</div>
          </div>
          ${badge(canRun.allowed === true ? "Start allowed" : "Start blocked", canRun.allowed === true ? "green" : "red")}
        </div>
        ${renderPaperCredentialSetup(credentialSetup)}
        ${renderPaperBaselinePanel(baseline, data.portfolio || {})}
        <div class="run-paper-proof-grid">
          ${renderRunPaperProofTile("Backend source", data.meta.dataSource || "UNKNOWN", `${backendDegradedCount()} degraded endpoint checks; Run PAPER source ${op.source || "UNKNOWN"}.`, data.meta.dataSource === "OPERATOR_BACKEND" ? "green" : (data.meta.dataSource === "PARTIAL_BACKEND" ? "yellow" : "red"))}
          ${renderRunPaperProofTile("Alpaca PAPER endpoint", endpoint.label || launch.paperEndpointDisplay || "Endpoint unavailable", `Source ${endpointSourceLabel}; family ${endpoint.family || launch.paperEndpointFamily || "unknown"}; host ${endpoint.host || launch.paperEndpointHost || "unavailable"}.`, endpoint.valid === true || launch.paperEndpointOnly ? "green" : "red")}
          ${renderRunPaperProofTile("Credentials", credentials.label || (launch.alpacaPaperCredentialsConfigured ? "Alpaca PAPER credentials configured" : "Alpaca PAPER credentials missing"), credentialDetail, credentials.configured === true || launch.alpacaPaperCredentialsConfigured ? "green" : "red")}
          ${renderRunPaperProofTile("Runtime", runtime.label || runtimeAttachment, `Supervisor ${runtime.state || sup.state || "UNKNOWN"}; safe stop ${runtime.safeStopStatus || launch.safeStopStatus || "UNKNOWN"}.`, (runtime.state || sup.state) === "RUNNING" ? "yellow" : "green")}
          ${renderRunPaperProofTile("Broker / portfolio truth", brokerTruth.label || "Broker truth not loaded in this card", brokerTruth.detail || "Portfolio Snapshot remains the broker-confirmed truth area; no positions are invented here.", brokerTruth.brokerConfirmed === true ? "green" : (brokerTruth.status === "BROKER_READ_READY_NOT_IN_THIS_VIEW" ? "yellow" : "red"))}
          ${renderRunPaperProofTile("Safety locks", "Live locked / real money blocked", safetyDetail, "green")}
          ${renderRunPaperProofTile("Start readiness", canRun.allowed === true ? "Start allowed" : "Start blocked", blockerText, canRun.allowed === true ? "green" : "red")}
          ${renderRunPaperProofTile("Max lease seconds", `${maxDuration}`, `Configured ${configuredMaxDuration}; runner ${runnerMaxDuration}; allowed durations include 72 hours and 5 days when max permits.`, maxDuration >= 432000 ? "green" : "yellow")}
        </div>
        <div class="notice ${canRun.allowed === true ? "" : "error"}" data-run-paper-blocker-text>${escapeHtml(blockerText)}</div>
        <div class="notice" data-run-paper-next-action>Next safe action: ${escapeHtml(op.nextSafeAction || "Review launch readiness and do not run PAPER without approval.")}</div>
        ${sup.lastHistoricalRefusal ? `<div class="notice mono">Last historical refusal: ${tokenText(sup.lastHistoricalRefusal)}. Not current start authority.</div>` : ""}
        ${renderSessionLifecycleCard("Active / Latest PAPER Session", "inline")}
        <div class="launch-control-layout">
          <div class="launch-input-panel">
            <div class="form-grid">
              <label>Watchlist
                <input data-paper-watchlist type="text" value="${escapeHtml(watchlist)}" autocomplete="off">
              </label>
              <label>Run length
                <select data-paper-duration data-paper-duration-max="${escapeHtml(maxDuration)}">
                  ${durationOptions.map(([seconds, label]) => `<option value="${seconds}" ${String(seconds) === selectedDurationRaw ? "selected" : ""}>${escapeHtml(label)}</option>`).join("")}
                  <option value="custom" ${customSelected ? "selected" : ""}>Custom minutes / hours / days</option>
                </select>
              </label>
              <label>Custom amount
                <input data-paper-duration-amount type="number" min="1" max="5" value="${escapeHtml(draft.customAmountRaw || "5")}" inputmode="numeric">
              </label>
              <label>Custom unit
                <select data-paper-duration-unit>
                  <option value="minutes" ${draft.customUnit === "minutes" ? "selected" : ""}>minutes</option>
                  <option value="hours" ${draft.customUnit === "hours" ? "selected" : ""}>hours</option>
                  <option value="days" ${draft.customUnit === "days" ? "selected" : ""}>days</option>
                </select>
              </label>
            </div>
            <div class="notice ${validation.valid ? "" : "error"}" data-paper-draft-status>${escapeHtml(`${paperDraftDirtyLabel(draft)} ${validation.detail}`)}</div>
          </div>
          <div class="launch-confirm-panel">
            <div class="launch-confirm-title">Safety confirmations</div>
            <div class="confirmation-grid">
              <label class="checkline"><input data-paper-profile-alpha type="checkbox" ${draft.profileAlpha !== false ? "checked" : ""}> PAPER_EXPLORATION_ALPHA</label>
              <label class="checkline"><input data-paper-confirm-paper type="checkbox" ${draft.confirmPaper === true ? "checked" : ""}> PAPER-only</label>
              <label class="checkline"><input data-paper-confirm-live-locked type="checkbox" ${draft.confirmLiveLocked === true ? "checked" : ""}> Live locked</label>
              <label class="checkline"><input data-paper-confirm-real-money-blocked type="checkbox" ${draft.confirmRealMoneyBlocked === true ? "checked" : ""}> Real-money blocked</label>
              <label class="checkline"><input data-paper-confirm-no-manual-trades type="checkbox" ${draft.confirmNoManualTrades === true ? "checked" : ""}> No manual trades</label>
            </div>
          </div>
        </div>
        <div class="button-row">
          <button class="intent-button paper primary-action" data-intent="paper-start" data-paper-form="${escapeHtml(formId)}" data-run-paper-start-control ${startDisabled}>
            Start Governed PAPER Run
          </button>
          <button class="intent-button secondary" data-paper-draft-reset="${escapeHtml(formId)}" type="button">Reset draft</button>
          <span class="badge red">No manual trades / force trade unavailable</span>
        </div>
        <div class="notice ${disabledReason ? "error" : ""}" data-run-paper-start-state>${escapeHtml(disabledReason || "Ready to request the governed /operator/intent/paper/start endpoint after confirmations are checked.")}</div>
        <details class="ai-context-details" data-run-paper-advanced>
          <summary>Advanced endpoint and start proof</summary>
          <div class="notice">Endpoint proof: ${escapeHtml(endpoint.display || launch.paperEndpointDisplay || "unavailable")} (${escapeHtml(endpoint.family || launch.paperEndpointFamily || "unknown")}; ${escapeHtml(endpoint.source || launch.paperEndpointSource || "UNKNOWN")}). Raw blocker code is kept here: ${escapeHtml(endpoint.blockerCode || launch.paperEndpointBlockerCode || "none")}.</div>
          ${kv(runPaperAdvancedRows(op, launch))}
          <div class="status-strip detail-strip">${(launch.checks || []).map((check) => badge(`${check.checkId}:${check.status}`, statusColor(check.status))).join("")}</div>
        </details>
        <div class="notice mono">Endpoint target: /operator/intent/paper/start only. Last intent: ${escapeHtml(sup.lastIntentResult || "none")}</div>
      </div>
    `;
  }

  function renderHomeLaunchReadiness() {
    const launch = data.launchReadiness || {};
    const op = runPaperState();
    const overall = op.overallStatus || {};
    const canRun = op.canRunPaper || {};
    const endpoint = op.endpoint || {};
    const credentials = op.credentials || {};
    const readiness = data.providerReadiness || {};
    const providerCounts = readiness.counts || {};
    const endpointDisplay = endpoint.display || launch.paperEndpointDisplay || "unavailable";
    const endpointFamily = endpoint.family || launch.paperEndpointFamily || "unknown";
    const endpointSource = endpoint.source || launch.paperEndpointSource || "UNKNOWN";
    const endpointReady = endpoint.valid === true || launch.paperEndpointOnly === true;
    const credentialsConfigured = credentials.configured === true || launch.alpacaPaperCredentialsConfigured === true;
    const blockerChecks = (launch.checks || []).filter((check) => {
      const status = String(check.status || "").toUpperCase();
      return check.blocker === true || status.includes("BLOCK") || status.includes("MISSING") || status.includes("DEGRADED") || status.includes("FAIL");
    });
    return `
      <div class="card span-12" data-home-section="launch-readiness"><h3>Launch Readiness</h3>${kv([
        ["Can I run PAPER right now?", badge(overall.label || launch.finalLaunchReadiness || "UNKNOWN", severityColor(overall.severity || launch.finalLaunchReadiness || "UNKNOWN"))],
        ["Why / why not", escapeHtml(canRun.allowed === true ? "Backend start authority is available after confirmations." : (canRun.reason || overall.detail || "Start authority is blocked."))],
        ["Next safe action", escapeHtml(op.nextSafeAction || "Review the blocked readiness detail before requesting Start.")],
        ["Alpaca PAPER credentials", badge(credentials.label || (credentialsConfigured ? "configured" : "missing"), credentialsConfigured ? "green" : "red")],
        ["Alpaca PAPER endpoint", badge(endpoint.label || launch.paperEndpointStatus || "UNKNOWN", endpointReady ? "green" : "red")],
        ["Endpoint display", escapeHtml(endpointDisplay)],
        ["Endpoint family", badge(endpointFamily, endpointReady ? "green" : "red")],
        ["Endpoint host", escapeHtml(endpoint.host || launch.paperEndpointHost || "unavailable")],
        ["Endpoint source", badge(endpointSource, endpointSource === "SAFE_DEFAULT_PAPER_ENDPOINT" || endpointSource === "OPERATOR_STATUS" ? "cyan" : "gray")],
        ["Endpoint configured", badge(launch.alpacaEndpointConfigured ? "yes" : "safe default", launch.alpacaEndpointConfigured ? "gray" : "cyan")],
        ["Live endpoint blocked", badge(launch.alpacaLiveEndpointBlocked ? "yes" : "no", launch.alpacaLiveEndpointBlocked ? "red" : "yellow")],
        ["Provider status", escapeHtml(`${readiness.readyOrConfiguredCount || 0} ready/configured, ${readiness.missingCredentialsCount || providerCounts.MISSING_CREDENTIALS || 0} missing`)],
        ["Live", badge("LOCKED", "red")],
        ["Real money", badge("BLOCKED", "red")],
        ["Active runtime", badge(data.supervisor.processState || "UNKNOWN", statusColor(data.supervisor.processState || "UNKNOWN"))],
        ["Safe stop", badge(launch.safeStopStatus || "UNKNOWN", statusColor(launch.safeStopStatus || "UNKNOWN"))],
        ["Storage/audit", badge(data.diagnostics.sessionStoreStatus || "UNKNOWN", statusColor(data.diagnostics.sessionStoreStatus || "UNKNOWN"))],
        ["Portfolio read", badge(launch.portfolioReadAvailability || "UNKNOWN", statusColor(launch.portfolioReadAvailability || "UNKNOWN"))]
      ])}
        <div class="notice">What this means: backend readiness is the source of truth. If this card says blocked, fix the plain-English blocker before pressing Start.</div>
        ${launch.paperEndpointOnly ? "" : `<div class="notice error">Endpoint action: ${escapeHtml(launch.paperEndpointOperatorAction || "Set APCA_API_BASE_URL to https://paper-api.alpaca.markets in Keys & Providers.")}</div>`}
        ${blockerChecks.length ? `<div class="notice error">Current blocker detail: ${escapeHtml(canRun.reason || overall.detail || "See advanced readiness checks.")}</div>` : ""}
        <details class="ai-context-details">
          <summary>Advanced readiness checks</summary>
          ${table(
            ["Check", "Status", "Detail", "Blocker"],
            (launch.checks || []).map((check) => [
              escapeHtml(check.title || check.checkId || "unknown"),
              badge(check.status || "UNKNOWN", statusColor(check.status || "UNKNOWN")),
              escapeHtml(check.detail || ""),
              badge(check.blocker ? "yes" : "no", check.blocker ? "red" : "gray")
            ])
          )}
        </details>
      </div>
    `;
  }

  function renderHomePortfolioSnapshot() {
    const portfolio = data.portfolio || {};
    const summary = portfolio.summary || {};
    return `
      <div class="card span-12" data-home-section="portfolio-snapshot"><h3>Portfolio Snapshot</h3>${kv([
        ["Broker data status", badge(portfolio.status || "UNKNOWN", statusColor(portfolio.status || "UNKNOWN"))],
        ["Message", escapeHtml(portfolio.message || "No broker portfolio message loaded.")],
        ["Total equity", escapeHtml(summary.totalEquity || "unavailable")],
        ["Cash", escapeHtml(summary.cash || "unavailable")],
        ["Buying power", escapeHtml(summary.buyingPower || "unavailable")],
        ["Market value", escapeHtml(summary.totalMarketValue || "unavailable")],
        ["Unrealized P&L", escapeHtml(summary.totalUnrealizedPnl || "unavailable")],
        ["Day P&L", escapeHtml(summary.dayPnl || "unavailable")],
        ["Positions", escapeHtml(summary.positionCount || 0)],
        ["Open orders", escapeHtml(summary.openOrderCount || 0)],
        ["Largest position", escapeHtml(summary.largestPosition || "none")],
        ["Highest-risk/stale/conflicted", escapeHtml(summary.highestRiskPosition || (summary.staleOrConflictedPositionCount ? `${summary.staleOrConflictedPositionCount} flagged` : "none"))],
        ["Freshness", escapeHtml(portfolio.dataFreshnessTs || "unavailable")]
      ])}</div>
    `;
  }

  function renderHomePositionsPreview() {
    const portfolio = data.portfolio || {};
    const positions = (portfolio.positions || []).slice(0, 5);
    const unavailable = isPortfolioUnavailableStatus(portfolio.status);
    return `
      <div class="card span-12" data-home-section="positions-preview"><h3>Current Assets / Positions Preview</h3>${positions.length ? table(
        ["Symbol", "Quantity", "Average Entry", "Current Price", "Market Value", "Unrealized P&L", "Daily Change", "Exposure", "Truth"],
        positions.map((p) => [
          escapeHtml(p.symbol || "unknown"),
          escapeHtml(p.quantity || "unknown"),
          escapeHtml(p.averageEntryPrice || "unknown"),
          escapeHtml(p.currentMarketPrice || "unknown"),
          escapeHtml(p.marketValue || "unknown"),
          escapeHtml(p.unrealizedPnl || "unknown"),
          escapeHtml(p.todayPercentChange || p.todayPriceChange || "unavailable"),
          escapeHtml(p.exposurePercentOfPortfolio || "unknown"),
          p.brokerConfirmed ? badge("broker-confirmed", "green") : badge(p.source || portfolio.dataSource || "unavailable", statusColor(p.source || portfolio.dataSource || "unavailable"))
        ])
      ) : `<p class="muted">${escapeHtml(unavailable ? `No current PAPER positions shown; broker data unavailable; broker status is ${portfolio.status || "UNKNOWN"}: ${portfolio.unavailableReason || "UNKNOWN"}.` : "No current PAPER positions.")}</p>`}</div>
    `;
  }

  function renderHomeOpenOrdersPreview() {
    const orders = ((data.portfolio && data.portfolio.openOrders) || data.orders || []).slice(0, 5);
    return `
      <div class="card span-12" data-home-section="open-orders-preview"><h3>Open Orders Preview</h3>${orders.length ? table(
        ["Symbol", "Side", "Quantity", "Order Type", "Status", "Submitted", "Read-only"],
        orders.map((o) => [
          escapeHtml(o.symbol || "unknown"),
          escapeHtml(o.side || "unknown"),
          escapeHtml(o.qty || o.quantity || "unknown"),
          escapeHtml(o.type || o.action || "unknown"),
          badge(o.status || o.state || "UNKNOWN", statusColor(o.status || o.state || "UNKNOWN")),
          escapeHtml(o.submittedAt || o.submitted_at || "unavailable"),
          badge("cancel unavailable", "gray")
        ])
      ) : `<p class="muted">No open broker-confirmed orders.</p>`}</div>
    `;
  }

  function renderHomeBotActivity() {
    const explain = data.explanation || {};
    const blockers = (explain.blockers || []).concat(explain.missingTruth || []);
    return `
      <div class="card span-12" data-home-section="bot-activity"><h3>Bot Activity / What It Is Considering</h3>${kv([
        ["Runtime", badge(data.supervisor.processState || data.status.botStatus || "UNKNOWN", statusColor(data.supervisor.processState || data.status.botStatus || "UNKNOWN"))],
        ["Latest run", escapeHtml(data.runArchive && data.runArchive.runs && data.runArchive.runs.length ? `${data.runArchive.runs[0].runId}: ${data.runArchive.runs[0].finalVerdict}` : "no latest run loaded")],
        ["Watchlist", escapeHtml((data.supervisor.watchlist && data.supervisor.watchlist.length ? data.supervisor.watchlist : data.status.universe || []).join(", ") || "unavailable")],
        ["Decision summary", escapeHtml(explain.headline || data.status.lastDecision || "unavailable")],
        ["Output", badge(explain.output || "UNKNOWN", statusColor(explain.output || "UNKNOWN"))],
        ["NetEdge", badge(explain.netEdge || "UNKNOWN", statusColor(explain.netEdge || "UNKNOWN"))],
        ["Current runtime state", tokenText(data.status.dominantBlocker || (blockers[0] || "none reported"))],
        ["Evaluating", escapeHtml(explain.nextBestAction || "No DecisionFrame summary loaded.")]
      ])}
        <div class="status-strip">${blockers.length ? blockers.map((item) => badge(item, statusColor(item))).join("") : badge("no blockers loaded", "gray")}</div>
      </div>
    `;
  }

  function renderHomeAiAdvisor() {
    const providerState = data.ai.providerState || "AI_DISABLED";
    const providerLabel = `${data.ai.provider || "disabled"} / ${providerState}`;
    const response = homeAiResponse || "No home-page question asked yet. Ask about readiness, portfolio risk, blockers, PAPER planning, or evidence quality.";
    const warning = aiModelWarning();
    const primaryPrompts = primaryAiPrompts(activeScreenId || "positions");
    const extraPrompts = moreAiPrompts(activeScreenId || "positions");
    return `
      <div class="card span-12" data-home-section="ai-quant-advisor"><h3>AI Quant Advisor</h3>
        <div class="cardless-model-strip compact-model-strip">
          ${badge(data.ai.providerMode || "NOT_CONFIGURED", statusColor(data.ai.providerMode || "NOT_CONFIGURED"))}
          ${badge(data.ai.modelName || "model unavailable", "gray")}
          ${badge(data.ai.modelQuality || "FALLBACK_ONLY", modelQualityColor(data.ai.modelQuality || "FALLBACK_ONLY"))}
          ${badge("advisory only", "gray")}
        </div>
        <div class="notice ai-mission compact">Chief Quant Advisor + Quant Engineer + Trading Systems Auditor + Operator Guide. Advisory only: can_execute=false, No broker calls, no live enablement, no real-money enablement, no threshold mutation, no secrets.</div>
        ${warning ? `<div class="notice error">${escapeHtml(warning)}</div>` : ""}
        <div class="ai-ask-box">
          <label for="home-ai-question">Ask a question from the home page</label>
          <textarea id="home-ai-question" data-home-ai-question rows="4" placeholder="Ask what blocks PAPER, what we own, what risk matters, or what proof is needed next.">${escapeHtml(homeAiQuestionText || "")}</textarea>
          <div class="ai-question-bank compact" aria-label="Home AI Advisor suggestions">
            ${primaryPrompts.map((prompt) => `
              <button class="ai-question" type="button" data-home-ai-prompt="${escapeHtml(prompt)}">${escapeHtml(prompt)}</button>
            `).join("")}
          </div>
          ${extraPrompts.length ? `
            <details class="ai-context-details ai-more-prompts">
              <summary>More prompts</summary>
              <div class="ai-question-bank compact">
                ${extraPrompts.map((prompt) => `<button class="ai-question" type="button" data-home-ai-prompt="${escapeHtml(prompt)}">${escapeHtml(prompt)}</button>`).join("")}
              </div>
            </details>
          ` : ""}
          <div class="button-row">
            <button class="intent-button paper" type="button" data-home-ai-clear ${homeAiBusy ? "disabled" : ""}>Clear</button>
            <button class="intent-button paper" type="button" data-ai-chief-open>Open Docked Advisor</button>
          </div>
          ${renderAiAnswerModeButtons("home", homeAiAnswerMode, homeAiBusy)}
          ${homeAiError ? `<div class="notice error">Error: ${escapeHtml(homeAiError)}</div>` : ""}
        </div>
        <div class="ai-response"><h3>Home Advisory Response</h3><pre>${escapeHtml(response)}</pre></div>
        <details class="ai-context-details">
          <summary>Provider and model details</summary>
          <div class="notice mono">Provider mode: ${escapeHtml(data.ai.providerMode || "NOT_CONFIGURED")} / Provider: ${escapeHtml(providerLabel)} / Model: ${escapeHtml(data.ai.modelName || "none")} / Quality: ${escapeHtml(data.ai.modelQuality || "FALLBACK_ONLY")} / Policy: ${escapeHtml(data.ai.reasoningPolicy || "FALLBACK_ONLY_LIMITED")}.</div>
        </details>
      </div>
    `;
  }

  function renderHomeWiringSummary() {
    const wiring = uiWiringSummary();
    return `
      <div class="card span-12" data-home-section="ui-wiring-summary"><h3>Buttons / Controls Status</h3>${kv([
        ["Total audited controls", escapeHtml(wiring.total)],
        ["Wired", badge(wiring.wired, wiring.wired ? "green" : "gray")],
        ["Disabled with reason", badge(wiring.disabledWithReason, wiring.disabledWithReason ? "yellow" : "gray")],
        ["Not implemented visible", badge(wiring.notImplemented, wiring.notImplemented ? "yellow" : "gray")],
        ["Broken", badge(wiring.broken, wiring.broken ? "red" : "green")]
      ])}
        <div class="notice mono">Full button-by-button inventory is available in Diagnostics / UI Wiring Audit.</div>
      </div>
    `;
  }

  function renderNav() {
    const nav = document.querySelector(".nav");
    nav.innerHTML = NAV_GROUPS.map((group) => `
      <div class="nav-group" data-nav-group="${escapeHtml(group.title)}">
        <div class="nav-group-title">${escapeHtml(group.title)}</div>
        <div class="nav-group-summary">${escapeHtml(group.summary)}</div>
        <div class="nav-group-items">
          ${group.items.map((id) => {
            const label = screenTitle(id);
            const badgeText = navBadge(id);
            return `
              <button class="nav-button ${id === "positions" ? "active" : ""}" data-screen="${id}">
                <span class="nav-label">${escapeHtml(label)}</span>
                <span class="nav-meta">
                  ${badgeText ? `<span class="nav-badge">${escapeHtml(badgeText)}</span>` : ""}
                  <span class="nav-page-number">${navPageNumber(id)}</span>
                </span>
              </button>
            `;
          }).join("")}
        </div>
      </div>
    `).join("");
    nav.addEventListener("click", (event) => {
      const button = event.target.closest("[data-screen]");
      if (!button) return;
      showScreen(button.dataset.screen);
    });
  }

  function showScreen(id) {
    activeScreenId = id;
    const existing = document.querySelector(`#screen-${id}`);
    if (!existing) {
      renderScreens(id);
      refreshActiveScreenData(id);
      return;
    }
    document.querySelectorAll(".screen").forEach((el) => el.classList.toggle("active", el.id === `screen-${id}`));
    document.querySelectorAll(".nav-button").forEach((el) => el.classList.toggle("active", el.dataset.screen === id));
    renderAiChiefOverlay();
    refreshActiveScreenData(id);
  }

  function renderCommand() {
    const s = data.status;
    const actionCounts = data.actionCenter.counts || {};
    const launch = data.launchReadiness || {};
    return `
      ${header("Run PAPER", "Start or review a governed PAPER run. Portfolio Home stays focused on what you own.", s.safetyVerdict)}
      <div class="grid">
        ${renderPaperLaunchControl("command")}
        ${metric("Bot Status", s.botStatus, "green")}
        ${metric("Mode", s.runtimeMode, "green")}
        ${metric("Live", "LOCKED", "red")}
        ${metric("Real-money", "BLOCKED", "red")}
        ${renderHomeLaunchReadiness()}
        ${renderHomePortfolioSnapshot()}
        ${renderHomePositionsPreview()}
        ${renderHomeOpenOrdersPreview()}
        ${renderHomeBotActivity()}
        ${renderHomeAiAdvisor()}
        ${renderHomeWiringSummary()}
        <div class="card span-6"><h3>Mode & Authority</h3>${kv([
          ["Capability state", badge(s.capabilityState, "green")],
          ["Active profile", badge(s.activeProfile, "cyan")],
          ["Broker route", escapeHtml(s.broker)],
          ["Endpoint", escapeHtml(s.endpoint)],
          ["Mutation authority", badge("server-side only", "yellow")]
        ])}</div>
        <div class="card span-6"><h3>Runtime Health</h3>${kv([
          ["Uptime", escapeHtml(s.uptime)],
          ["Last heartbeat", badge(s.lastHeartbeat, "green")],
          ["Market data", escapeHtml(s.marketData)],
          ["Universe", escapeHtml(s.universe.join(", "))],
          ["Current runtime state", badge(s.dominantBlocker, ["IDLE_NO_ACTIVE_PAPER_RUN", "READY_IDLE_NO_ACTIVE_PAPER_RUN"].includes(s.dominantBlocker) ? "green" : "yellow")]
        ])}</div>
        <div class="card span-4"><h3>Broker Boundary</h3>${kv([
          ["POST count", escapeHtml(s.brokerPostCount)],
          ["DELETE count", escapeHtml(s.brokerDeleteCount)],
          ["Mutation authorized", escapeHtml(s.mutationAuthorizedCount)],
          ["Boundary", badge("PAPER governed", "green")]
        ])}</div>
        <div class="card span-4"><h3>Current Decision</h3>${kv([
          ["Last decision", escapeHtml(s.lastDecision)],
          ["Safety verdict", badge(s.safetyVerdict, "green")]
        ])}</div>
        <div class="card span-4"><h3>Needs Approval</h3>${kv([
          ["Live activation", badge("not approved", "red")],
          ["Manual trading", badge("not available", "gray")],
          ["Force trade", badge("forbidden", "red")],
          ["AI review queue", badge(actionCounts.NEEDS_APPROVAL || 0, actionCounts.NEEDS_APPROVAL ? "yellow" : "gray")]
        ])}</div>
      </div>
    `;
  }

  function renderActionCenter() {
    const center = data.actionCenter;
    return `
      ${header("Action Center", "Blockers, degraded states, and advisory items needing review.", "NEEDS REVIEW")}
      <div class="grid">
        ${metric("Blockers", center.counts.BLOCKER || 0, center.counts.BLOCKER ? "red" : "gray")}
        ${metric("Warnings", center.counts.WARNING || 0, center.counts.WARNING ? "yellow" : "gray")}
        ${metric("Needs Approval", center.counts.NEEDS_APPROVAL || 0, center.counts.NEEDS_APPROVAL ? "yellow" : "gray")}
        ${metric("Safety Critical", center.counts.SAFETY_CRITICAL || 0, center.counts.SAFETY_CRITICAL ? "red" : "gray")}
        <div class="card span-12"><h3>Current Items</h3>${table(
          ["Type", "Title", "Detail", "Source", "Executable"],
          center.items.map((item) => [
            badge(item.type, statusColor(item.type)),
            escapeHtml(item.title),
            escapeHtml(item.detail),
            escapeHtml(item.source),
            badge(item.canExecute ? "yes" : "no", item.canExecute ? "red" : "gray")
          ])
        )}</div>
      </div>
    `;
  }

  function renderRuns() {
    const archive = data.runArchive;
    return `
      ${header("Run Archive / Flight Recorder", "Session evidence, log paths, safety markers, and final verdicts.", "READ ONLY")}
      <div class="grid">
        ${metric("Archived Runs", archive.runCount || 0, archive.runCount ? "green" : "gray")}
        ${metric("Latest Verdict", archive.latestVerdict || "UNKNOWN", statusColor(archive.latestVerdict || "UNKNOWN"))}
        ${metric("Report Status", archive.reportStatus || "on demand", "gray")}
        <div class="card span-12"><h3>Runs</h3>${table(
          ["Run", "Status", "Verdict", "Profile", "Duration", "Runtime New", "Historical", "POST/DELETE", "Open", "Fee/TCA", "72h", "Report"],
          archive.runs.map((run) => [
            escapeHtml(run.runId),
            badge(run.status, statusColor(run.status)),
            badge(run.finalVerdict, statusColor(run.finalVerdict)),
            escapeHtml(run.profile || "unknown"),
            escapeHtml(run.durationSeconds || "unknown"),
            escapeHtml(`posts ${run.orderPostAcknowledged}/${run.orderPostAttempted}; cancels ${run.cancelAcknowledged}/${run.cancelAttempted}; fills ${run.runtimeFills}`),
            escapeHtml(`broker fills ${run.brokerFilledOrders}; local fills ${run.localFills}; positions ${run.baselinePositionsCount}`),
            escapeHtml(`${run.postCount}/${run.deleteCount}`),
            escapeHtml(`${run.openOrdersAtShutdown}`),
            badge(run.feeTcaStatus || run.tcaStatus, statusColor(run.feeTcaStatus || run.tcaStatus)),
            badge(run.readiness72h || "UNKNOWN", statusColor(run.readiness72h || "UNKNOWN")),
            escapeHtml(run.reportPath || "not generated")
          ])
        )}</div>
        <div class="card span-12"><h3>Historical Alpaca Test Link</h3>
          <p class="muted">Use the 4-Month Test page for the Alpaca historical control. It is advisory only and cannot start PAPER or trade.</p>
          <button class="intent-button paper" data-screen-shortcut="historical">Open 4-Month Test</button>
        </div>
      </div>
    `;
  }

  function renderHistorical() {
    const tests = data.historicalTests || {};
    const presets = tests.presets || [];
    const last = tests.lastRunResult || (tests.lastResults || [])[0] || null;
    const defaultPreset = presets[0] || {};
    return `
      ${header("Historical Alpaca Test", "4-month historical data test control. Advisory only; not broker truth or future-profit proof.", tests.status || "READY_FOR_REQUEST")}
      <div class="grid">
        ${metric("Simulation Harness", tests.simulationHarnessAttached ? "attached" : "not attached", tests.simulationHarnessAttached ? "green" : "yellow")}
        ${metric("Read-only Market Data", tests.readOnlyMarketDataOnly ? "yes" : "unknown", tests.readOnlyMarketDataOnly ? "green" : "yellow")}
        ${metric("Can Execute Trades", "false", "gray")}
        ${metric("Last Status", last ? last.status : "none", last ? statusColor(last.status) : "gray")}
        <div class="card span-12 historical-card">
          <div class="split">
            <h3>Run Historical Test</h3>
            ${badge("last 4 months preset", "cyan")}
          </div>
          <div class="form-grid" data-historical-form>
            <label>Date range preset
              <select data-historical-preset>
                <option value="last_4_months" selected>Last 4 months</option>
                <option value="custom">Custom range</option>
              </select>
            </label>
            <label>Start date
              <input data-historical-start type="date" value="${escapeHtml(defaultPreset.start_date || "")}">
            </label>
            <label>End date
              <input data-historical-end type="date" value="${escapeHtml(defaultPreset.end_date || "")}">
            </label>
            <label>Watchlist
              <input data-historical-watchlist type="text" value="${escapeHtml((tests.defaultWatchlist || ["BTC/USD", "ETH/USD", "SOL/USD"]).join(","))}" autocomplete="off">
            </label>
            <label>Timeframe
              <select data-historical-timeframe>
                ${(tests.timeframes || HISTORICAL_TIMEFRAMES).map((tf) => `<option value="${escapeHtml(tf)}">${escapeHtml(tf)}</option>`).join("")}
              </select>
            </label>
            <label>Starting capital
              <input data-historical-capital type="number" min="1" step="100" value="10000">
            </label>
            <label>Fee/slippage policy
              <select data-historical-fee-policy>
                ${HISTORICAL_FEE_POLICIES.map(([value, label]) => `<option value="${escapeHtml(value)}">${escapeHtml(label)}</option>`).join("")}
              </select>
            </label>
            <label>Strategy/profile
              <input data-historical-profile type="text" value="PAPER_EXPLORATION_ALPHA" autocomplete="off">
            </label>
          </div>
          <div class="button-row">
            <button class="intent-button paper" data-intent="historical-run" ${backendConnected() ? "" : "disabled"}>Run Historical Test</button>
            <span class="badge red">Does not start PAPER / does not trade</span>
          </div>
          <div class="notice">If the governed replay/backtest harness is not attached, this returns an honest unavailable status instead of fake P&L.</div>
          <div class="notice mono">Endpoint target: /operator/historical-tests/run. Market data may be read-only in future; broker trading endpoints are forbidden.</div>
        </div>
        <div class="card span-12"><h3>Latest Historical Test Result</h3>
          ${last ? kv([
            ["Test", escapeHtml(last.testId || last.test_id || "unknown")],
            ["Status", badge(last.status || "UNKNOWN", statusColor(last.status || "UNKNOWN"))],
            ["Final equity", escapeHtml((last.result && last.result.final_equity) || "unknown - no simulation evidence")],
            ["Total return", escapeHtml((last.result && last.result.total_return) || "unknown - no simulation evidence")],
            ["Max drawdown", escapeHtml((last.result && last.result.max_drawdown) || "unknown - no simulation evidence")],
            ["Simulated trades", escapeHtml((last.result && last.result.simulated_trade_count) || 0)],
            ["Reason codes", escapeHtml(((last.result && last.result.reason_codes) || []).join(", ") || "none")],
            ["Caveats", escapeHtml(((last.result && last.result.caveats) || []).join(", "))]
          ]) : `<p class="muted">No historical test has been requested in this UI session.</p>`}
        </div>
        <div class="card span-12"><h3>Historical Test Caveats</h3>
          <div class="status-strip">
            ${["historical simulation only", "not broker-confirmed", "not live proof", "not future-profit proof", "no fake fees/P&L/TCA"].map((item) => badge(item, item.includes("not") || item.includes("no fake") ? "yellow" : "gray")).join("")}
          </div>
        </div>
      </div>
    `;
  }

  function renderPnl() {
    const p = data.pnl;
    return `
      ${header("P&L Truth", "Broker-confirmed economics only. Unknown stays unknown.", "BROKER TRUTH REQUIRED")}
      <div class="grid">
        <div class="card span-12"><h3>What This Means</h3>
          <div class="notice">This page is intentionally conservative. If realized P&L, fees, slippage, or TCA are not broker-confirmed, the UI keeps them unknown instead of inventing clean numbers.</div>
        </div>
        ${metric("Realized P&L", p.realizedPnl.source, "yellow")}
        ${metric("Unrealized P&L", p.unrealizedPnl.source, "yellow")}
        ${metric("Net P&L", p.netPnl.source, "yellow")}
        ${metric("Fees", p.fees.source, "yellow")}
        <div class="card span-6"><h3>NetEdge</h3>${kv([
          ["Current NetEdge", badge(p.netEdge, "green")],
          ["Gross edge", escapeHtml(p.grossEdge)],
          ["Spread cost", escapeHtml(p.spreadCost)],
          ["Slippage", escapeHtml(p.slippage)],
          ["Latency drag", escapeHtml(p.latencyDrag)]
        ])}</div>
        <div class="card span-6"><h3>Trade Stats</h3>${kv([
          ["Trade count", escapeHtml(p.trades)],
          ["Win/loss", badge(p.winLoss, "yellow")],
          ["Max drawdown", badge(p.maxDrawdown, "yellow")]
        ])}</div>
        <div class="card span-12"><h3>TCA / Execution Quality</h3>${kv([
          ["TCA status", badge(data.tcaDashboard.status || "UNKNOWN", statusColor(data.tcaDashboard.status || "UNKNOWN"))],
          ["TCA records", escapeHtml(data.tcaDashboard.recordsTotal || 0)],
          ["Complete", escapeHtml(data.tcaDashboard.recordsComplete || 0)],
          ["Unknown", escapeHtml(data.tcaDashboard.recordsUnknown || 0)],
          ["Fee pending", escapeHtml(data.tcaDashboard.feePending || 0)],
          ["Fake P&L", badge("forbidden", "red")],
          ["Fake fees/TCA", badge("forbidden", "red")]
        ])}</div>
      </div>
    `;
  }

  function renderPositions() {
    const portfolio = data.portfolio || {};
    const summary = portfolio.summary || {};
    const positions = portfolio.positions || [];
    const orders = portfolio.openOrders || data.orders || [];
    const intelligence = portfolio.positionIntelligence || [];
    const unavailable = isPortfolioUnavailableStatus(portfolio.status);
    const launch = data.launchReadiness || {};
    const missingAlpaca = launch.alpacaPaperCredentialsConfigured === false || portfolio.status === "MISSING_CREDENTIALS";
    const exactBrokerIssue = unavailable && !missingAlpaca;
    const biggestBlocker = missingAlpaca
        ? "Alpaca PAPER key is missing from this backend. Add it in Keys & Providers, then validate read-only."
        : exactBrokerIssue
          ? `Broker portfolio status is ${portfolio.status || "UNKNOWN"}: ${portfolio.unavailableReason || "UNKNOWN"}.`
          : (data.status.dominantBlocker || "No major blocker loaded.");
    return `
      ${header("Portfolio Home", "Current PAPER holdings, cash, exposure, and orders.", portfolio.status || "UNKNOWN")}
      <div class="grid">
        <div class="card span-12 cockpit-hero" data-home-section="portfolio-cockpit">
          <div class="cockpit-hero-main">
            <div>
              <h3>Account Cockpit</h3>
              <p>Broker-confirmed PAPER account view first. Use Run PAPER only after readiness is green and safety confirmations are checked.</p>
            </div>
            <div class="cockpit-badges">
              ${badge(portfolio.status || "UNKNOWN", statusColor(portfolio.status || "UNKNOWN"))}
              ${badge(launch.finalLaunchReadiness || "UNKNOWN", statusColor(launch.finalLaunchReadiness || "UNKNOWN"))}
              ${badge("Live locked", "red")}
              ${badge("Real-money blocked", "red")}
            </div>
          </div>
          <div class="cockpit-hero-actions">
            <button class="intent-button paper primary-action" type="button" data-screen-shortcut="command">Open Run PAPER</button>
            <button class="intent-button paper" type="button" data-screen-shortcut="providers">Keys & Providers</button>
            <button class="intent-button paper" type="button" data-ai-chief-open>Ask Docked Advisor</button>
          </div>
        </div>
        ${metric("Total Equity", summary.totalEquity || "unknown", summary.totalEquity ? "green" : "yellow")}
        ${metric("Cash", summary.cash || "unknown", summary.cash ? "green" : "yellow")}
        ${metric("Buying Power", summary.buyingPower || "unknown", summary.buyingPower ? "green" : "yellow")}
        ${metric("Unrealized P&L", summary.totalUnrealizedPnl || "unknown", summary.totalUnrealizedPnl ? statusColor(summary.totalUnrealizedPnl) : "yellow")}
        ${metric("Positions", summary.positionCount || 0, summary.positionCount ? "green" : "gray")}
        ${metric("Open Orders", summary.openOrderCount || 0, summary.openOrderCount ? "yellow" : "gray")}
        ${metric("Market Value", summary.totalMarketValue || "unknown", summary.totalMarketValue ? "green" : "yellow")}
        ${metric("Exposure", summary.netExposure || summary.grossExposure || "unknown", (summary.netExposure || summary.grossExposure) ? "yellow" : "gray")}

        <div class="card span-12 portfolio-primary">
          <div class="split">
            <h3>What You Own Right Now</h3>
            ${badge(portfolio.status || "UNKNOWN", statusColor(portfolio.status || "UNKNOWN"))}
          </div>
          ${positions.length ? table(
            ["Symbol", "Qty", "Side", "Avg Entry", "Current", "Market Value", "Unrealized", "P&L %", "Exposure", "Truth", "Risk"],
            positions.map((p) => [
              escapeHtml(p.symbol),
              escapeHtml(p.quantity || "unknown"),
              escapeHtml(p.side || "unknown"),
              escapeHtml(p.averageEntryPrice || "unknown"),
              escapeHtml(p.currentMarketPrice || "unknown"),
              escapeHtml(p.marketValue || "unknown"),
              escapeHtml(p.unrealizedPnl || "unknown"),
              escapeHtml(p.unrealizedPnlPercent || "unknown"),
              escapeHtml(p.exposurePercentOfPortfolio || "unknown"),
              badge(p.source || "UNAVAILABLE", statusColor(p.source || "UNAVAILABLE")),
              badge(p.riskStatus || "UNKNOWN", statusColor(p.riskStatus || "UNKNOWN"))
            ])
          ) : `<p class="muted">${escapeHtml(portfolio.empty ? "No current PAPER positions." : unavailable ? `No broker-confirmed positions available: ${portfolio.status || "UNKNOWN"} / ${portfolio.unavailableReason || "UNKNOWN"}.` : "No broker-confirmed positions available.")}</p>`}
        </div>

        <div class="card span-6">
          <h3>Next Useful Action</h3>${kv([
            ["Biggest blocker", tokenText(biggestBlocker)],
            ["PAPER readiness", badge(launch.finalLaunchReadiness || "UNKNOWN", statusColor(launch.finalLaunchReadiness || "UNKNOWN"))],
            ["Alpaca PAPER key", badge(launch.alpacaPaperCredentialsConfigured ? "configured" : "missing", launch.alpacaPaperCredentialsConfigured ? "green" : "red")],
            ["Live", badge("LOCKED", "red")],
            ["Real money", badge("BLOCKED", "red")]
          ])}
        </div>
        <div class="card span-6">
          <h3>Operator Shortcuts</h3>
          <div class="button-row operator-flow-actions">
            <button class="intent-button paper" type="button" data-screen-shortcut="command">Open Run PAPER</button>
            <button class="intent-button paper" type="button" data-screen-shortcut="providers">Add / Validate Keys</button>
            <button class="intent-button paper" type="button" data-ai-chief-open>Ask Docked Advisor</button>
            <span class="badge red">Live trading locked</span>
          </div>
        </div>

        <div class="card span-12"><h3>Open Orders</h3>${orders.length ? table(
          ["Order ID", "Client ID", "Symbol", "Side", "Type", "Qty", "Filled", "Limit", "Status", "Source", "Cancel"],
          orders.map((o) => [
            escapeHtml(o.orderId || o.clientOrderId || "unknown"),
            escapeHtml(o.clientOrderId || "unknown"),
            escapeHtml(o.symbol || "unknown"),
            escapeHtml(o.side || "unknown"),
            escapeHtml(o.type || o.action || "unknown"),
            escapeHtml(o.qty || "unknown"),
            escapeHtml(o.filledQty || "0"),
            escapeHtml(o.limitPrice || "none"),
            badge(o.status || o.state || "UNKNOWN", statusColor(o.status || o.state || "UNKNOWN")),
            badge(o.source || "READ_ONLY", statusColor(o.source || "READ_ONLY")),
            badge(o.canCancel ? "governed elsewhere" : "not available", o.canCancel ? "yellow" : "gray")
          ])
        ) : `<p class="muted">No open broker-confirmed orders.</p>`}</div>

        ${unavailable ? `<div class="card span-12"><h3>Portfolio Broker Truth</h3><p class="muted">Status: ${escapeHtml(portfolio.status || "UNKNOWN")}. Reason: ${escapeHtml(portfolio.unavailableReason || "UNKNOWN")}. No positions are invented and local-only state is not shown as broker truth.</p></div>` : ""}

        <div class="card span-12"><h3>Portfolio Summary</h3>
          <details class="ai-context-details" open>
            <summary>Cash, exposure, freshness, and reconciliation</summary>
            ${kv([
              ["Source", badge(portfolio.dataSource || "UNAVAILABLE", statusColor(portfolio.dataSource || "UNAVAILABLE"))],
          ["Status", badge(portfolio.status || "UNKNOWN", statusColor(portfolio.status || "UNKNOWN"))],
          ["Message", escapeHtml(portfolio.message || "")],
          ["Cash", escapeHtml(summary.cash || "unknown")],
          ["Buying power", escapeHtml(summary.buyingPower || "unknown")],
          ["Market value", escapeHtml(summary.totalMarketValue || "unknown")],
          ["Gross exposure", escapeHtml(summary.grossExposure || "unknown")],
          ["Net exposure", escapeHtml(summary.netExposure || "unknown")],
          ["Largest position", escapeHtml(summary.largestPosition || "none")],
          ["Highest risk", escapeHtml(summary.highestRiskPosition || "none")],
          ["Reconciliation", badge(summary.brokerLocalReconciliationStatus || "UNKNOWN", statusColor(summary.brokerLocalReconciliationStatus || "UNKNOWN"))],
          ["Freshness", escapeHtml(portfolio.dataFreshnessTs || "unavailable")]
            ])}
          </details>
        </div>
        <div class="card span-12"><h3>Current PAPER Positions</h3>
          <details class="ai-context-details">
            <summary>Detailed position columns: fees, TCA, asset class, and risk labels</summary>
            ${positions.length ? table(
              ["Symbol", "Asset", "Qty", "Side", "Avg Entry", "Current", "Market Value", "Unrealized", "P&L %", "Exposure", "Fees", "TCA", "Source", "Risk"],
              positions.map((p) => [
                escapeHtml(p.symbol),
                escapeHtml(p.assetClass),
                escapeHtml(p.quantity || "unknown"),
                escapeHtml(p.side || "unknown"),
                escapeHtml(p.averageEntryPrice || "unknown"),
                escapeHtml(p.currentMarketPrice || "unknown"),
                escapeHtml(p.marketValue || "unknown"),
                escapeHtml(p.unrealizedPnl || "unknown"),
                escapeHtml(p.unrealizedPnlPercent || "unknown"),
                escapeHtml(p.exposurePercentOfPortfolio || "unknown"),
                badge(p.feesStatus || "UNKNOWN", statusColor(p.feesStatus || "UNKNOWN")),
                badge(p.tcaStatus || "UNKNOWN", statusColor(p.tcaStatus || "UNKNOWN")),
                badge(p.source || "UNAVAILABLE", statusColor(p.source || "UNAVAILABLE")),
                badge(p.riskStatus || "UNKNOWN", statusColor(p.riskStatus || "UNKNOWN"))
              ])
            ) : `<p class="muted">${escapeHtml(portfolio.empty ? "No current PAPER positions." : "No broker-confirmed positions available.")}</p>`}
          </details>
        </div>
        <div class="card span-12"><h3>Position Intelligence</h3>
          <details class="ai-context-details">
            <summary>Risk, staleness, fees, slippage, and exit-logic details</summary>
            ${intelligence.length ? table(
              ["Symbol", "Exposure", "Concentration", "Fee Drag", "Slippage", "Freshness", "Exit Logic", "Blockers"],
              intelligence.map((item) => [
                escapeHtml(item.symbol),
                escapeHtml(item.exposurePercentOfPortfolio || "unknown"),
                badge(item.concentrationWarning ? "warning" : "ok/unknown", item.concentrationWarning ? "yellow" : "gray"),
                badge(item.feeDragWarning || "UNKNOWN", statusColor(item.feeDragWarning || "UNKNOWN")),
                badge(item.slippageWarning || "UNKNOWN", statusColor(item.slippageWarning || "UNKNOWN")),
                badge(item.staleDataWarning ? "stale" : "fresh/read", item.staleDataWarning ? "yellow" : "green"),
                escapeHtml(item.exitLogicStatus || "UNKNOWN"),
                escapeHtml((item.blockersConflicts || []).join(", ") || "none")
              ])
            ) : `<p class="muted">No position intelligence available without broker-confirmed positions.</p>`}
          </details>
        </div>
      </div>
    `;
  }

  function renderActivity() {
    const sup = data.supervisor;
    const launch = data.launchReadiness || {};
    const duration = sup.durationSeconds === null || sup.durationSeconds === undefined ? "not active" : `${sup.durationSeconds}s`;
    return `
      ${header("Bot Runtime", "Current PAPER process status, stop intent, and run logs.", sourceLabel())}
      <div class="grid">
        <div class="card span-12"><h3>Launch Readiness</h3>${kv([
          ["Final", badge(launch.finalLaunchReadiness || "UNKNOWN", statusColor(launch.finalLaunchReadiness || "UNKNOWN"))],
          ["Alpaca PAPER credentials", badge(launch.alpacaPaperCredentialsConfigured ? "configured" : "missing", launch.alpacaPaperCredentialsConfigured ? "green" : "red")],
          ["PAPER endpoint", badge(launch.paperEndpointStatus || (launch.paperEndpointOnly ? "confirmed" : "blocked/unknown"), launch.paperEndpointOnly ? "green" : "red")],
          ["Endpoint source", badge(launch.paperEndpointSource || "UNKNOWN", launch.paperEndpointSource === "SAFE_DEFAULT_PAPER_ENDPOINT" ? "cyan" : "gray")],
          ["Paper start", badge(launch.paperStartAllowed ? "allowed" : "blocked", launch.paperStartAllowed ? "green" : "red")],
          ["Runtime attachment", escapeHtml(sup.runtimeAttachmentDetail || "No PAPER run currently attached.")],
          ["Max duration", escapeHtml(formatDuration(sup.maxPaperDurationSeconds || 432000))],
          ["Safe stop", badge(launch.safeStopStatus || "UNKNOWN", statusColor(launch.safeStopStatus || "UNKNOWN"))],
          ["Backend checks", badge((launch.backendDegradedReasons || []).length ? `${launch.backendDegradedReasons.length} degraded` : "no degraded checks", (launch.backendDegradedReasons || []).length ? "yellow" : "green")]
        ])}
          <details class="ai-context-details">
            <summary>Advanced launch readiness details</summary>
            <div class="notice mono">Endpoint authority: ${escapeHtml(launch.paperEndpointStatus || "UNKNOWN")} / source=${escapeHtml(launch.paperEndpointSource || "UNKNOWN")} / action=${escapeHtml(launch.paperEndpointOperatorAction || "none")}</div>
            <div class="notice mono">Backend degraded reasons: ${escapeHtml((launch.backendDegradedReasons || []).join(", ") || "none")}</div>
            <div class="status-strip detail-strip">${(launch.checks || []).map((check) => badge(`${check.checkId}:${check.status}`, statusColor(check.status))).join("")}</div>
          </details>
        </div>
        <div class="card span-6"><h3>Runtime Snapshot</h3>${kv([
          ["Process", badge(data.status.botStatus, statusColor(data.status.botStatus))],
          ["Profile", badge(data.status.activeProfile, "cyan")],
          ["Watchlist", escapeHtml(data.status.universe.join(", "))],
          ["Preflight", badge("PAPER_READ_ONLY_PREFLIGHT_REQUIRED", "yellow")],
          ["Credential status", "present/not present only; no secrets"]
        ])}</div>
        ${renderSessionLifecycleCard("Active / Latest PAPER Session")}
        <div class="card span-6"><h3>Supervisor Session</h3>${kv([
          ["Supervisor", badge(sup.state, statusColor(sup.state))],
          ["Session", escapeHtml(sup.sessionId || "none")],
          ["Paper start", badge(sup.paperStartAllowed ? "allowed" : "blocked", sup.paperStartAllowed ? "green" : "yellow")],
          ["Runtime attachment", escapeHtml(sup.runtimeAttachmentDetail || "No PAPER run currently attached.")],
          ["PID", escapeHtml(sup.pid || "none")],
          ["Duration", escapeHtml(duration)],
          ["Max duration", escapeHtml(formatDuration(sup.maxPaperDurationSeconds || 432000))],
          ["Wrapper stdout", escapeHtml(sup.wrapperStdoutPath || sup.stdoutPath || "not available")],
          ["Wrapper stderr", escapeHtml(sup.wrapperStderrPath || sup.stderrPath || "not available")],
          ["Child stdout", escapeHtml(sup.childStdoutPath || "not available")],
          ["Child stderr", escapeHtml(sup.childStderrPath || "not available")]
        ])}</div>
        ${renderPaperLaunchControl("activity")}
        <div class="card span-12"><h3>Governed PAPER Intents</h3>
          <div class="stack">
            <button class="intent-button paper" data-intent="paper-start" data-paper-form="activity" ${paperLaunchDisabledReason() ? "disabled" : ""}>
              Start governed PAPER - ${paperLaunchDisabledReason() ? escapeHtml(paperLaunchDisabledReason()) : "server-authorized intent"}
            </button>
            <button class="intent-button paper" data-intent="paper-stop" ${sup.paperStopAllowed ? "" : "disabled"}>
              Stop PAPER - ${sup.paperStopAllowed ? "graceful supervisor request" : escapeHtml(sup.paperStopRefusalReason || "disabled")}
            </button>
            <div class="notice mono">Live start locked: LIVE_NOT_APPROVED</div>
            <div class="notice mono">Last intent: ${escapeHtml(sup.lastIntentResult || "none")}</div>
            <div class="notice mono">Last historical refusal: ${sup.lastHistoricalRefusal ? tokenText(sup.lastHistoricalRefusal) : "none"}</div>
          </div>
        </div>
      </div>
    `;
  }

  function renderDecision() {
    const explain = data.explanation;
    return `
      ${header("Signal & Decision Lab", "Why BUY, SELL, or NO_TRADE happened.", "DECISIONFRAME FIRST")}
      <div class="grid">
        <div class="card span-12"><h3>Plain-English Explainer</h3>${kv([
          ["Headline", escapeHtml(explain.headline)],
          ["Frame", escapeHtml(explain.frameId || "none")],
          ["Output", badge(explain.output || "UNKNOWN", statusColor(explain.output || "UNKNOWN"))],
          ["NetEdge", badge(explain.netEdge || "UNKNOWN", statusColor(explain.netEdge || "UNKNOWN"))],
          ["Confidence", badge(explain.confidence || "LOW", statusColor(explain.confidence || "LOW"))],
          ["Next action", escapeHtml(explain.nextBestAction)]
        ])}</div>
        <div class="card span-12"><h3>Explainer Blockers / Missing Truth</h3>
          <div class="status-strip">
            ${(explain.blockers || []).map((x) => badge(x, statusColor(x))).join("") || badge("none", "gray")}
            ${(explain.missingTruth || []).map((x) => badge(x, "yellow")).join("")}
          </div>
        </div>
        <div class="card span-12"><h3>DecisionFrames</h3>${table(
          ["Frame", "Symbol", "Output", "Opportunity", "Raw", "Final", "NetEdge", "Compiler", "Submit"],
          data.decisionFrames.map((d) => [d.frameId, d.symbol, badge(d.output, statusColor(d.output)), d.opportunityVerdict, d.rawScore, d.finalScore, badge(d.netEdge, statusColor(d.netEdge)), d.compiler, d.submitSignal])
        )}</div>
        <div class="card span-12"><h3>Module Evidence</h3>${table(
          ["Module", "Authority", "Status", "Direction", "Reason"],
          data.moduleEvidence.map((m) => [m[0], m[1], badge(m[2], statusColor(m[2])), m[3], m[4]])
        )}</div>
        <div class="card span-12"><h3>Action Taxonomy</h3>
          <div class="status-strip">
            ${["buy_to_open", "sell_to_close", "sell_short", "buy_to_cover", "reduce", "exit", "bearish_no_long", "no_trade"].map((x) => badge(x, x === "sell_short" ? "red" : "gray")).join("")}
          </div>
        </div>
      </div>
    `;
  }

  function renderMarket() {
    return `
      ${header("Market Data Truth", "Executable market truth vs stale, backfill, replay, or synthetic evidence.", "SNAPSHOT AUTHORITY")}
      <div class="card"><h3>MarketTruthSnapshot</h3>${table(
        ["Symbol", "Provider", "Snapshot", "Book", "Candle", "Executable", "Source"],
        data.marketTruth.map((m) => [m[0], m[1], badge(m[2], statusColor(m[2])), m[3], m[4], badge(String(m[5]), m[5] ? "green" : "red"), m[6]])
      )}</div>
      <div class="notice" style="margin-top:12px">Backfill, replay, synthetic, stale, in-progress, and mismatched snapshots must be shown as non-executable.</div>
    `;
  }

  function renderRisk() {
    return `
      ${header("Risk & Governor", "Hard gates, economic gates, and authority classes.", "FAIL CLOSED")}
      <div class="card">${table(
        ["Gate", "Category", "Decision", "Reason"],
        data.risk.map((r) => [r[0], r[1], badge(r[2], statusColor(r[2])), r[3]])
      )}</div>
    `;
  }

  function renderAlerts() {
    return `
      ${header("Watchdog Alerts", "Local queue only. No SMS, email, Discord, or broker mutation.", "LOCAL ONLY")}
      <div class="grid">
        ${metric("Alert Count", data.alerts.length, data.alerts.length ? "yellow" : "gray")}
        <div class="card span-12"><h3>Alerts</h3>${table(
          ["Severity", "Title", "Detail", "Source", "Acknowledged", "Executable"],
          data.alerts.map((alert) => [
            badge(alert.severity, statusColor(alert.severity)),
            escapeHtml(alert.title),
            escapeHtml(alert.detail),
            escapeHtml(alert.source),
            badge(String(alert.acknowledged === true), alert.acknowledged ? "green" : "gray"),
            badge(alert.canExecute ? "yes" : "no", alert.canExecute ? "red" : "gray")
          ])
        )}</div>
      </div>
    `;
  }

  function renderAI() {
    const ai = data.ai;
    const research = data.research.counts || {};
    const warning = aiModelWarning();
    const routing = aiRoutingSettings();
    const activeRoute = aiAskRoutingPayload(routing);
    const lastAiResult = aiOverlayLastResult || homeAiLastResult || {};
    const providerCards = aiProviderCards();
    const providerOptionsFor = (selected) => providerCards.map((provider) => {
      const id = provider.providerId || provider.provider_id;
      const label = provider.displayName || provider.display_name || id;
      return `<option value="${escapeHtml(id)}" ${selected === id ? "selected" : ""}>${escapeHtml(label)}</option>`;
    }).join("");
    return `
      ${header("AI Advisor", "Highest-reasoning Chief Quant Advisor for strategy, risk, TCA, provider readiness, operation, and proof.", ai.providerState)}
      <div class="grid">
        ${metric("Provider", ai.provider, statusColor(ai.providerState))}
        ${metric("Active Router", `${providerDisplayLabel(activeRoute.providerId || routing.activeProvider || "deterministic_local")} / ${activeRoute.modelName || routing.activeModel || "deterministic-local-guide"}`, "blue")}
        ${metric("Active provider", providerDisplayLabel(activeRoute.providerId || routing.activeProvider || "deterministic_local"), "blue")}
        ${metric("Active model", activeRoute.modelName || routing.activeModel || "deterministic-local-guide", "gray")}
        ${metric("Current answer source", lastAiResult.answerSource || "none yet", statusColor(lastAiResult.answerSource || "UNKNOWN"))}
        ${metric("Last provider error", lastAiResult.providerErrorCategory || "none", lastAiResult.providerErrorCategory ? "yellow" : "gray")}
        ${metric("State", ai.providerState, statusColor(ai.providerState))}
        ${metric("Provider Mode", ai.providerMode || "NOT_CONFIGURED", statusColor(ai.providerMode || "NOT_CONFIGURED"))}
        ${metric("Model Quality", ai.modelQuality || "FALLBACK_ONLY", modelQualityColor(ai.modelQuality || "FALLBACK_ONLY"))}
        ${metric("Pending Review", ai.pendingReviewCount || 0, ai.pendingReviewCount ? "yellow" : "gray")}
        ${metric("Can Execute", "false", "gray")}
        <div class="card span-12"><h3>Mission</h3>
          <div class="notice">Chief Quant Advisor + Quant Engineer + Trading Systems Auditor + Trading Strategist + Market Research Chief + Risk Officer + Execution/TCA Auditor + Operator Guide. I analyze trading edge, market structure, execution quality, portfolio exposure, risk, validation evidence, provider readiness, PAPER plans, and live-readiness proof. I cannot trade, call broker, enable live, expose secrets, mutate strategy, or bypass safety gates.</div>
          ${warning ? `<div class="notice error">${escapeHtml(warning)}</div>` : ""}
        </div>
        <div class="card span-12"><h3>AI Routing Settings</h3>
          <div class="notice">High-reasoning API uses separate paid provider billing. ChatGPT Pro web subscription does not automatically provide API quota. Supreme Board Packet uses manual ChatGPT Pro workflow. Local Guide is free and deterministic. Local Model requires your own GPU/server.</div>
          <div class="notice mono">Settings source: ${badge(routing.settingsSource || "DEFAULT_SETTINGS", statusColor(routing.settingsSource || "DEFAULT_SETTINGS"))} / status=${escapeHtml(routing.status || "DEFAULT_SETTINGS")} / path=${escapeHtml(routing.settingsPathRelative || ".operator_config/ai_router_settings.json")} / sources=PERSISTED_LOCAL_SETTINGS, DEFAULT_SETTINGS, IN_MEMORY_UNSAVED</div>
          <div class="routing-grid">
            <label>Default mode
              <select data-ai-route-default-mode>
                ${["LOCAL_GUIDE", "LIGHT_API", "HIGH_REASONING_API_WITH_APPROVAL", "SUPREME_BOARD_PACKET", "LOCAL_MODEL"].map((mode) => `<option value="${mode}" ${(routing.defaultMode === mode || (mode === "HIGH_REASONING_API_WITH_APPROVAL" && routing.defaultMode === "HIGH_REASONING_API")) ? "selected" : ""}>${mode.replaceAll("_", " ")}</option>`).join("")}
              </select>
            </label>
            <label>Active provider
              <select data-ai-active-provider>${providerOptionsFor(routing.activeProvider || "deterministic_local")}</select>
            </label>
            <label>Active model
              <input data-ai-active-model value="${escapeHtml(routing.activeModel || "deterministic-local-guide")}" placeholder="selected model">
            </label>
            <label>Local base URL
              <input data-ai-local-base-url value="${escapeHtml(routing.localBaseUrl || "http://127.0.0.1:11434/v1")}" placeholder="http://127.0.0.1:11434/v1">
            </label>
            <label>Supreme Board Packet default
              <select data-ai-supreme-board-default>
                <option value="false" ${routing.supremeBoardPacketDefault ? "" : "selected"}>off</option>
                <option value="true" ${routing.supremeBoardPacketDefault ? "selected" : ""}>on</option>
              </select>
            </label>
            <label>Light provider
              <select data-ai-light-provider>${providerOptionsFor(routing.lightProvider)}</select>
            </label>
            <label>Light model
              <input data-ai-light-model value="${escapeHtml(routing.lightModel || "")}" placeholder="gpt-5-mini">
            </label>
            <label>High-reasoning provider
              <select data-ai-high-provider>${providerOptionsFor(routing.highReasoningProvider)}</select>
            </label>
            <label>High-reasoning model
              <input data-ai-high-model value="${escapeHtml(routing.highReasoningModel || "")}" placeholder="gpt-5.5-pro">
            </label>
            <label>Local model
              <input data-ai-local-model value="${escapeHtml(routing.localModel || "")}" placeholder="local-model">
            </label>
          </div>
          <div class="button-row">
            <button class="intent-button paper" type="button" data-ai-save-routing ${backendConnected() ? "" : "disabled"}>Save AI routing settings</button>
            <button class="intent-button paper" type="button" data-ai-provider-test ${backendConnected() ? "" : "disabled"}>Test provider connection</button>
            <button class="intent-button paper" type="button" data-ai-generate-packet ${backendConnected() ? "" : "disabled"}>Generate Supreme Board Packet</button>
            <button class="intent-button paper" type="button" data-ai-use-provider-now="deepseek" ${backendConnected() ? "" : "disabled"}>Use DeepSeek now</button>
            <button class="intent-button paper" type="button" data-ai-use-provider-now="openai" ${backendConnected() ? "" : "disabled"}>Use OpenAI now</button>
            <button class="intent-button paper" type="button" data-ai-use-supreme-board>Use Supreme Board packet mode</button>
            <button class="intent-button paper" type="button" data-ai-approve-high-call ${backendConnected() ? "" : "disabled"}>Approve one high-reasoning call</button>
            <button class="intent-button paper" type="button" data-ai-use-local-guide>Use local guide only</button>
            <button class="intent-button paper" type="button" data-ai-use-light-model ${backendConnected() ? "" : "disabled"}>Use selected light model</button>
            <button class="intent-button paper" type="button" data-ai-use-local-model ${backendConnected() ? "" : "disabled"}>Use selected local model</button>
          </div>
          <div class="notice mono">Last AI result: ${escapeHtml(ai.lastAnalyzeResult || "none")}</div>
        </div>
        <div class="card span-12"><h3>Provider / Model Registry</h3>
          <details class="ai-context-details">
            <summary>Show provider registry, model quality, cost, and validation details</summary>
            ${table(
              ["Provider", "Status", "Configured", "Model", "Quality", "Cost", "Reasoning", "Persona", "Validation / Error"],
              providerCards.map((provider) => [
                escapeHtml(provider.displayName || provider.display_name || provider.providerId || provider.provider_id),
                badge(provider.status || "UNKNOWN", statusColor(provider.status || "UNKNOWN")),
                badge(String(provider.configured === true || provider.credentialSource === "NOT_REQUIRED" || provider.credential_source === "NOT_REQUIRED"), provider.configured || provider.credentialSource === "NOT_REQUIRED" || provider.credential_source === "NOT_REQUIRED" ? "green" : "yellow"),
                escapeHtml(provider.modelName || provider.model_name || provider.default_model || "not selected"),
                badge(provider.modelQuality || provider.model_quality || "UNKNOWN", modelQualityColor(provider.modelQuality || provider.model_quality || "UNKNOWN")),
                badge(provider.costMode || provider.cost_mode || provider.cost_tier || "UNKNOWN", statusColor(provider.costMode || provider.cost_mode || "UNKNOWN")),
                escapeHtml(provider.reasoningCapability || provider.reasoning_capability || provider.provider_family || "unknown"),
                badge(String(provider.personaEnforced !== false), provider.personaEnforced === false ? "red" : "green"),
                escapeHtml(provider.lastErrorCategory || provider.last_error_category || provider.lastValidationStatus || provider.last_validation_status || "NOT_RUN")
              ])
            )}
          </details>
        </div>
        <div class="card span-6"><h3>Model Policy</h3>${kv([
          ["Provider mode", badge(ai.providerMode || "NOT_CONFIGURED", statusColor(ai.providerMode || "NOT_CONFIGURED"))],
          ["Selected model", escapeHtml(ai.modelName || "none")],
          ["Model quality tier", badge(ai.modelQuality || "FALLBACK_ONLY", modelQualityColor(ai.modelQuality || "FALLBACK_ONLY"))],
          ["Reasoning policy", badge(ai.reasoningPolicy || "FALLBACK_ONLY_LIMITED", statusColor(ai.reasoningPolicy || "FALLBACK_ONLY_LIMITED"))],
          ["Suitable for governance", badge(String(ai.modelSuitableForGovernance === true), ai.modelSuitableForGovernance ? "green" : "red")],
          ["Live model/fallback", badge((ai.providerMode || "").startsWith("LIVE_") ? "live model path" : "fallback/not configured", (ai.providerMode || "").startsWith("LIVE_") ? "green" : "red")]
        ])}</div>
        <div class="card span-6"><h3>Control Tower</h3>${kv([
          ["Identity", escapeHtml("Chief Quant Advisor + Quant Engineer + Trading Systems Auditor + Operator Guide")],
          ["Roles", escapeHtml("Quant Advisor, Quant Engineer, Trading Systems Auditor, Operator Guide, Run Planner, Portfolio Reviewer, Codex Packet Advisor")],
          ["Research items", escapeHtml(`${research.hypotheses || 0} hypotheses / ${research.experiments || 0} experiments`)],
          ["Promotion gates", escapeHtml(research.promotionGates || 0)]
        ])}</div>
        <div class="card span-12"><h3>Expert Prompt Modes</h3>
          <details class="ai-context-details">
            <summary>Show advisor modes</summary>
            <div class="stack">${["QUANT_ADVISOR", "QUANT_ENGINEER", "TRADING_SYSTEMS_AUDITOR", "OPERATOR_GUIDE", "RUN_PLANNER", "PORTFOLIO_REVIEW", "SETUP_HELP", "CODEX_PACKET_ADVISOR", "UNSAFE_REQUEST_REFUSAL"].map((prompt) => badge(prompt, "gray")).join("")}</div>
          </details>
        </div>
        <div class="card span-12"><h3>Focused Quant Prompts</h3>
          <div class="ai-question-bank compact">${AI_QUICK_PROMPTS.slice(0, AI_PRIMARY_PROMPT_LIMIT).map((prompt) => `<button class="ai-question" type="button" data-ai-chief-prompt="${escapeHtml(prompt)}">${escapeHtml(prompt)}</button>`).join("")}</div>
          <details class="ai-context-details ai-more-prompts">
            <summary>More prompts</summary>
            <div class="ai-question-bank compact">${AI_QUICK_PROMPTS.slice(AI_PRIMARY_PROMPT_LIMIT).map((prompt) => `<button class="ai-question" type="button" data-ai-chief-prompt="${escapeHtml(prompt)}">${escapeHtml(prompt)}</button>`).join("")}</div>
          </details>
        </div>
        <div class="card span-12"><h3>Advisory Boundary</h3>${kv([
          ["AI direct broker calls", badge("forbidden", "red")],
          ["AI order submit/cancel/liquidate", badge("forbidden", "red")],
          ["Live enable", badge("separate approval required", "red")],
          ["Secrets exposed", badge(String(ai.secretsValuesExposed === true), ai.secretsValuesExposed ? "red" : "green")]
        ])}</div>
        <div class="card span-12"><h3>Governance Queue</h3>${table(
          ["ID", "Type", "Status", "Summary", "Action", "Executable"],
          ai.recommendations.map((rec) => [
            escapeHtml(rec.recommendationId),
            badge(rec.recommendationType, statusColor(rec.recommendationType)),
            badge(rec.status, statusColor(rec.status)),
            escapeHtml(rec.summary),
            escapeHtml(rec.proposedAction),
            badge(rec.canExecute ? "yes" : "no", rec.canExecute ? "red" : "gray")
          ])
        )}</div>
        <div class="card span-12"><h3>Advisory Analyze</h3>
          <div class="stack">
            <button class="intent-button paper" data-intent="ai-analyze" ${backendConnected() ? "" : "disabled"}>
              Run advisory AI analysis
            </button>
            <button class="intent-button paper" data-intent="ai-quant-review" ${backendConnected() ? "" : "disabled"}>
              Queue Quant Chief review
            </button>
            <div class="notice mono">Last AI result: ${escapeHtml(ai.lastAnalyzeResult || "none")}</div>
          </div>
        </div>
      </div>
    `;
  }

  function renderProviders() {
    const readiness = data.providerReadiness;
    const credentials = data.credentials || {};
    const credentialProviders = credentials.providers || [];
    const providerRows = readiness.providers || [];
    const providerById = new Map(providerRows.map((provider) => [provider.providerId, provider]));
    return `
      ${header("Keys & Providers", "Add local keys, validate read-only readiness, and keep raw secrets out of UI responses.", "NO SECRET VALUES")}
      <div class="grid">
        ${metric("Providers", readiness.providerCount || 0, readiness.providerCount ? "green" : "gray")}
        ${metric("Ready/Configured", readiness.readyOrConfiguredCount || 0, readiness.readyOrConfiguredCount ? "green" : "gray")}
        ${metric("Missing Credentials", readiness.missingCredentialsCount || 0, readiness.missingCredentialsCount ? "yellow" : "gray")}
        ${metric("Can Trade", "false", "gray")}
        <div class="card span-12"><h3>Credential Safety</h3>${kv([
          ["Raw secret values", badge("not exposed", "green")],
          ["AI secret access", badge("forbidden", "red")],
          ["Browser secret storage", badge("not used", "green")],
          ["Read-only validation", badge("presence / PAPER endpoint only", "yellow")],
          ["Visible feedback states", escapeHtml("saving / saved / failed / credential presence confirmed / validation failed / configured / missing")],
          ["Local credential vault", badge(credentials.storeExists ? "stored on this computer only" : "not created yet", credentials.storeExists ? "green" : "yellow")],
          ["Secrets sent to AI", badge("never", "green")],
          ["Precedence", badge(credentials.precedence || "ENV_PRESENT_OVERRIDES_LOCAL_SECRET", "gray")]
        ])}
          <details class="ai-context-details">
            <summary>Advanced local vault details</summary>
            <div class="notice mono">Store path: ${escapeHtml(credentials.storePath || ".operator_secrets/provider_credentials.json")}. Raw secrets are hidden and not sent to AI.</div>
          </details>
        </div>
        <div class="card span-12"><h3>Enter / Update Credentials</h3>
          <div class="provider-groups">
            ${PROVIDER_GROUPS.map((group) => `
              <section class="provider-group">
                <div class="split">
                  <h4>${escapeHtml(group.title)}</h4>
                  ${badge(`${group.providerIds.length} providers`, "gray")}
                </div>
                <div class="credential-grid provider-group-grid">
                  ${group.providerIds.map((providerId) => {
                    const form = CREDENTIAL_FORMS[providerId];
                    const provider = providerById.get(providerId) || {};
                    if (!form) {
                      return `
                        <div class="credential-box provider-status-box" data-provider-status-card="${escapeHtml(providerId)}">
                          <h4>${escapeHtml(provider.displayName || PROVIDER_LABELS[providerId] || providerId)}</h4>
                          <div class="muted">${escapeHtml(provider.purpose || "No local credential fields required.")}</div>
                          ${kv([
                            ["Status", badge(provider.status || "READY", statusColor(provider.status || "READY"))],
                            ["Configured", badge(String(provider.configured === true || providerDisplaySource(provider) === "NOT_REQUIRED"), provider.configured || providerDisplaySource(provider) === "NOT_REQUIRED" ? "green" : "yellow")],
                            ["Source", badge(providerDisplaySource(provider), statusColor(providerDisplaySource(provider)))]
                          ])}
                        </div>
                      `;
                    }
                    return `
                      <div class="credential-box" data-credential-card="${escapeHtml(providerId)}">
                        <h4>${escapeHtml(form.title)}</h4>
                        <div class="muted">${escapeHtml(credentialSummaryLine(credentialProviders, providerId))}</div>
                        ${form.fields.map(([name, label, type, placeholder]) => `
                          <label>${escapeHtml(label)}
                            <input
                              type="${escapeHtml(type)}"
                              placeholder="${escapeHtml(placeholder || "enter value")}"
                              data-credential-provider="${escapeHtml(providerId)}"
                              data-credential-field="${escapeHtml(name)}"
                              autocomplete="off"
                            >
                          </label>
                        `).join("")}
                        <div class="button-row">
                          <button class="intent-button paper" data-credential-save="${escapeHtml(providerId)}" ${backendConnected() ? "" : "disabled"}>Save local credentials</button>
                          <button class="intent-button paper" data-credential-validate="${escapeHtml(providerId)}" ${backendConnected() ? "" : "disabled"}>Validate read-only</button>
                          <button class="intent-button danger" data-credential-delete="${escapeHtml(providerId)}" ${backendConnected() ? "" : "disabled"}>Delete local</button>
                        </div>
                        <div class="notice mono credential-feedback">${escapeHtml(credentialActionStatus[providerId] || (backendConnected() ? "ready" : "backend unavailable; local secret store cannot be changed from static mock mode"))}</div>
                      </div>
                    `;
                  }).join("")}
                </div>
              </section>
            `).join("")}
          </div>
          <div class="notice mono">Last credential action: ${escapeHtml(readiness.lastCredentialResult || "none")}</div>
        </div>
        <div class="card span-12 provider-table-card"><h3>Provider Table</h3>${table(
          ["Provider", "Category", "Status", "Configured", "Required Env", "Source", "Fingerprint", "Can Trade", "Setup"],
          providerRows.map((provider) => [
            escapeHtml(provider.displayName || provider.providerId),
            badge(provider.category || "unknown", "gray"),
            badge(normalizeStatusText(provider.status || "UNKNOWN"), statusColor(provider.status || "UNKNOWN")),
            badge(String(provider.configured === true), provider.configured ? "green" : "yellow"),
            escapeHtml((provider.requiredEnvVars || []).join(", ") || "none"),
            badge(providerDisplaySource(provider), statusColor(providerDisplaySource(provider))),
            escapeHtml(providerDisplayFingerprints(provider)),
            badge(String(provider.canTrade === true), provider.canTrade ? "red" : "gray"),
            escapeHtml(provider.setupInstructions || "")
          ])
        )}</div>
      </div>
    `;
  }

  function credentialSummaryLine(providers, providerId) {
    const provider = (providers || []).find((item) => item.providerId === providerId);
    if (!provider) return "not loaded";
    const configured = provider.configured === true;
    const fields = provider.fields || [];
    const localCount = fields.filter((field) => field.source === "LOCAL_SECRET_PRESENT").length;
    const envCount = fields.filter((field) => field.source === "ENV_PRESENT").length;
    const missingCount = fields.filter((field) => !field.source || field.source === "NOT_CONFIGURED").length;
    if (configured) {
      const sourceText = [
        localCount ? `${localCount} local vault field${localCount === 1 ? "" : "s"}` : "",
        envCount ? `${envCount} environment field${envCount === 1 ? "" : "s"}` : ""
      ].filter(Boolean).join(", ");
      return `configured; ${sourceText || "safe source present"}; raw secrets hidden`;
    }
    return `missing; ${missingCount || "required"} field${missingCount === 1 ? "" : "s"} needed; raw secrets hidden`;
  }

  function credentialActionStatusText(action, providerId, result) {
    const status = String((result && result.status) || "UNKNOWN");
    const summary = (result && result.summary) || {};
    const configured = summary.configured === true || result.configured === true;
    const sources = Array.isArray(summary.fields)
      ? summary.fields.map((field) => `${field.name}:${field.source || "NOT_CONFIGURED"}`).join(", ")
      : "";
    if (action === "save" && status === "SAVED") {
      return `${providerId}: saved; ${configured ? "configured" : "missing"}; raw secrets hidden; ${sources || "source pending"}`;
    }
    if (action === "save") {
      const reason = result.reason_code || "UNKNOWN_REASON";
      const missing = Array.isArray(result.missing_fields) && result.missing_fields.length
        ? `; missing=${result.missing_fields.join(", ")}`
        : "";
      const presence = result.received_field_presence && typeof result.received_field_presence === "object"
        ? `; received=${Object.entries(result.received_field_presence).map(([name, present]) => `${name}=${present ? "present" : "missing"}`).join(", ")}`
        : "";
      const writable = result.vault_parent_writable === false ? "; vault not writable" : "";
      return `${providerId}: ${status.toLowerCase()}; reason=${reason}${missing}${presence}${writable}; raw secrets hidden`;
    }
    if (action === "validate") {
      const passed = status === "READY";
      return `${providerId}: validation ${passed ? "passed" : "failed"}; ${configured ? "configured" : "missing"}; ${(result.reason_codes || []).join(", ") || status}`;
    }
    if (action === "delete") {
      return `${providerId}: ${status === "DELETED" ? "deleted; missing" : status.toLowerCase()}; raw secrets hidden`;
    }
    return `${providerId}: ${status}`;
  }

  function renderResearch() {
    const research = data.research;
    const graph = data.evidenceGraph;
    return `
      ${header("Research OS / Evidence Graph", "Lightweight quant research registry, promotion gates, and evidence links.", "ADVISORY ONLY")}
      <div class="grid">
        ${metric("Hypotheses", research.counts.hypotheses || 0, research.counts.hypotheses ? "yellow" : "gray")}
        ${metric("Experiments", research.counts.experiments || 0, research.counts.experiments ? "yellow" : "gray")}
        ${metric("Promotion Gates", research.counts.promotionGates || 0, "yellow")}
        ${metric("Can Execute", "false", "gray")}
        <div class="card span-12"><h3>Promotion Gates</h3>${table(
          ["Gate", "Stage", "Status", "Blocks", "Required Evidence"],
          research.promotionGates.map((gate) => [
            escapeHtml(gate.gateId),
            badge(gate.stage, statusColor(gate.stage)),
            badge(gate.currentStatus, statusColor(gate.currentStatus)),
            badge(String(gate.blocksPromotion === true), gate.blocksPromotion ? "yellow" : "green"),
            escapeHtml((gate.requiredEvidence || []).join(", "))
          ])
        )}</div>
        <div class="card span-12"><h3>Research Recommendations</h3>${table(
          ["ID", "Title", "Stage", "Status", "Summary", "Executable"],
          research.recommendations.map((rec) => [
            escapeHtml(rec.id),
            escapeHtml(rec.title),
            badge(rec.promotionStage, statusColor(rec.promotionStage)),
            badge(rec.status, statusColor(rec.status)),
            escapeHtml(rec.summary),
            badge(rec.canExecute ? "yes" : "no", rec.canExecute ? "red" : "gray")
          ])
        )}</div>
        <div class="card span-12"><h3>Evidence Graph</h3>${table(
          ["Node", "Truth Label", "Summary", "Run/Path"],
          graph.nodes.map((node) => [
            escapeHtml(node.label || node.nodeId),
            badge(node.truthLabel || "advisory", "gray"),
            escapeHtml(node.summary || "unknown"),
            escapeHtml(node.runId || node.reportPath || "none")
          ])
        )}</div>
        <div class="card span-12"><h3>Missing Evidence / Promotion Blockers</h3>
          <div class="status-strip">
            ${(graph.missingEvidence || []).map((item) => badge(item, "yellow")).join("") || badge("none loaded", "gray")}
            ${(graph.promotionBlockers || []).map((item) => badge(item, statusColor(item))).join("")}
          </div>
        </div>
      </div>
    `;
  }

  function renderSystem() {
    const map = data.systemMap;
    return `
      ${header("System Map", "Plain-English operator map of engine authority boundaries.", "READ ONLY")}
      <div class="grid">
        <div class="card span-12"><h3>Report</h3>${kv([
          ["Path", escapeHtml(map.reportPath)],
          ["Live", badge("LOCKED", "red")],
          ["Real money", badge("BLOCKED", "red")],
          ["AI", badge("advisory only", "yellow")]
        ])}</div>
        <div class="card span-12"><h3>Sections</h3>
          <div class="status-strip">${map.sections.map((section) => badge(section, "gray")).join("")}</div>
        </div>
      </div>
    `;
  }

  function renderAudit() {
    return `
      ${header("Audit Log", "Operator-facing evidence timeline.", "READ ONLY")}
      <div class="card">${table(
        ["Time", "Type", "Severity", "Event", "Result"],
        data.auditLog.map((a) => [a[0], a[1], a[2], a[3], badge(a[4], statusColor(a[4]))])
      )}</div>
    `;
  }

  function renderWorld() {
    return `
      ${header("World Awareness", "External intelligence is advisory evidence only.", "NO EXECUTION AUTHORITY")}
      <div class="grid">
        <div class="card span-12"><h3>Provider Health</h3>${table(
          ["Provider", "Type", "Enabled", "Status", "Events", "Next Poll", "Backoff", "Errors", "Rule"],
          data.worldAwareness.map((w) => [
            w.source,
            w.feedType || "UNKNOWN",
            badge(String(w.enabled === true), w.enabled === true ? "green" : "gray"),
            badge(w.status, statusColor(w.status)),
            escapeHtml(w.eventCount || 0),
            badge(w.nextPollDue ? "due now" : (w.nextPollTime || "not scheduled"), w.nextPollDue ? "yellow" : "gray"),
            escapeHtml(`${w.backoffSeconds || 0}s`),
            escapeHtml(w.consecutiveErrorCount || w.errorCount || 0),
            w.rule
          ])
        )}</div>
        <div class="card span-12"><h3>Manual Read-only Poll</h3>
          <div class="stack">
            <button class="intent-button paper" data-intent="world-poll" ${backendConnected() ? "" : "disabled"}>
              Poll Alpaca News - read-only provider intent
            </button>
            <div class="notice mono">Runtime: ${escapeHtml(data.worldRuntime.manualPollOnly ? "manual poll only" : "unknown")} | Active polling: ${escapeHtml(String(data.worldRuntime.providerPollingActive))} | Last poll: ${escapeHtml(data.worldRuntime.lastPollResult || "none")}</div>
          </div>
        </div>
        <div class="card span-12"><h3>Latest Advisory Events</h3>${table(
          ["Provider", "Symbols", "Title", "Event Time", "Freshness", "Verification", "Advisory"],
          data.worldAwarenessEvents.map((event) => [
            escapeHtml(event.provider),
            escapeHtml((event.symbols || []).join(", ") || "none"),
            escapeHtml(event.title || "untitled"),
            escapeHtml(event.eventTime || "unknown"),
            escapeHtml(event.freshness || "unknown"),
            badge(event.verification || "UNVERIFIED", statusColor(event.verification || "UNVERIFIED")),
            badge(event.advisoryOnly === false ? "not advisory" : "advisory only", event.advisoryOnly === false ? "red" : "gray")
          ])
        )}</div>
        <div class="notice span-12">World Awareness is advisory evidence only. It cannot trade or bypass MarketTruthSnapshot, NetEdge, guardrails, or broker boundary.</div>
      </div>
    `;
  }

  function buildUiControlInventory() {
    const disabledPaperReason = paperLaunchDisabledReason();
    const inventory = [
      ["global", "live_locked", "Live locked", "status", "DISABLED_WITH_REASON", "forbidden", "LIVE_NOT_APPROVED", null, null],
      ["global", "ask_quant_chief", "Ask Quant Chief", "button", "WIRED", "read_only", "", null, "open_ai_drawer"],
      ["ai_overlay", "ai_question_textarea", "Ask a page-aware question", "input", "WIRED", "read_only", "", null, "local_page_context"],
      ["ai_overlay", "ai_answer_mode_deterministic", "Deterministic AI answer", "button", "WIRED", "local_advisory_write", "", "POST", "/operator/ai/ask"],
      ["ai_overlay", "ai_answer_mode_chat", "AI Chat Model answer", "button", backendConnected() ? "WIRED" : "DISABLED_WITH_REASON", "local_advisory_write", backendConnected() ? "" : "backend unavailable; local fallback labeled", "POST", "/operator/ai/ask"],
      ["ai_overlay", "ai_answer_mode_reasoning", "AI Reasoning answer", "button", backendConnected() ? "WIRED" : "DISABLED_WITH_REASON", "local_advisory_write", backendConnected() ? "" : "backend unavailable; local fallback labeled", "POST", "/operator/ai/ask"],
      ["ai_overlay", "ai_clear", "Clear", "button", "WIRED", "read_only", "", null, "local_clear"],
      ["ai_overlay", "ai_close", "Close", "button", "WIRED", "read_only", "", null, "local_close"],
      ["ai_overlay", "ai_wide", "Wide advisor", "button", "WIRED", "read_only", "", null, "toggle_ai_dock_width"],
      ["command", "paper_watchlist", "Watchlist", "input", "WIRED", "governed_paper_start", "", null, "paper_start_payload"],
      ["command", "paper_duration", "Run length", "select+number", "WIRED", "governed_paper_start", "", null, "paper_start_payload"],
      ["command", "paper_start", "Start Governed PAPER Run", "button", disabledPaperReason ? "DISABLED_WITH_REASON" : "WIRED", "governed_paper_start", disabledPaperReason, "POST", "/operator/intent/paper/start"],
      ["command", "paper_baseline_accept", "Accept PAPER baseline", "button", backendConnected() ? "WIRED" : "DISABLED_WITH_REASON", "local_operator_state_write", backendConnected() ? "" : "backend unavailable", "POST", "/operator/paper-baseline/accept"],
      ["command", "home_ai_question", "Home AI Quant Advisor question", "input", "WIRED", "read_only", "", null, "local_page_context"],
      ["command", "home_ai_answer_modes", "Home AI answer modes", "button group", backendConnected() ? "WIRED" : "DISABLED_WITH_REASON", "local_advisory_write", backendConnected() ? "" : "backend unavailable; local fallback labeled", "POST", "/operator/ai/ask"],
      ["command", "home_ai_clear", "Clear home AI question", "button", "WIRED", "read_only", "", null, "local_clear"],
      ["command", "home_ui_wiring_summary", "Buttons / Controls Status", "summary", "WIRED", "read_only", "", null, "local_inventory_summary"],
      ["positions", "open_run_paper", "Open Run PAPER", "button", "WIRED", "read_only", "", null, "local_navigation"],
      ["positions", "open_keys_providers", "Add / Validate Keys", "button", "WIRED", "read_only", "", null, "local_navigation"],
      ["positions", "ask_ai_advisor", "Ask AI Advisor", "button", "WIRED", "read_only", "", null, "open_ai_drawer"],
      ["activity", "paper_stop", "Stop PAPER", "button", data.supervisor.paperStopAllowed ? "WIRED" : "DISABLED_WITH_REASON", "governed_paper_start", data.supervisor.paperStopAllowed ? "" : (data.supervisor.paperStopRefusalReason || "no active PAPER runtime"), "POST", "/operator/intent/paper/stop"],
      ["activity", "live_start_locked", "Live start locked - LIVE_NOT_APPROVED", "status", "DISABLED_WITH_REASON", "forbidden", "LIVE_NOT_APPROVED", null, null],
      ["positions", "positions_preview_table", "Current PAPER Positions", "table", "WIRED", "read_only", "", "GET", "/operator/positions"],
      ["positions", "open_orders_preview_table", "Open Orders", "table", "WIRED", "read_only", "cancel/replace unavailable in operator UI", "GET", "/operator/orders/open"],
      ["positions", "position_intelligence_table", "Position Intelligence", "table", "WIRED", "read_only", "", "GET", "/operator/positions/intelligence"],
      ["world", "world_poll", "Poll Alpaca News - read-only provider intent", "button", backendConnected() ? "WIRED" : "DISABLED_WITH_REASON", "read_only", backendConnected() ? "" : "backend unavailable", "POST", "/operator/intent/world-awareness/poll"],
      ["ai", "ai_analyze", "Run advisory AI analysis", "button", backendConnected() ? "WIRED" : "DISABLED_WITH_REASON", "local_advisory_write", backendConnected() ? "" : "backend unavailable", "POST", "/operator/ai/analyze"],
      ["ai", "ai_quant_review", "Queue Quant Chief review", "button", backendConnected() ? "WIRED" : "DISABLED_WITH_REASON", "local_advisory_write", backendConnected() ? "" : "backend unavailable", "POST", "/operator/ai/quant-review"],
      ["historical", "historical_run", "Run Historical Test", "button", backendConnected() ? "WIRED" : "DISABLED_WITH_REASON", "read_only", backendConnected() ? "" : "backend unavailable", "POST", "/operator/historical-tests/run"],
      ["runs", "open_historical_tests", "Open 4-Month Test", "button", "WIRED", "read_only", "", null, "local_navigation"],
    ];
    screens.forEach(([id, label]) => {
      inventory.push(["navigation", `nav_${id}`, label, "button", "WIRED", "read_only", "", null, `show:${id}`]);
    });
    Object.keys(CREDENTIAL_FORMS).forEach((providerId) => {
      const disabled = backendConnected() ? "" : "backend unavailable";
      inventory.push(["providers", `credential_save_${providerId}`, `Save ${providerId} credentials`, "button", disabled ? "DISABLED_WITH_REASON" : "WIRED", "local_secret_write", disabled, "POST", "/operator/credentials/save"]);
      inventory.push(["providers", `credential_validate_${providerId}`, `Validate ${providerId} read-only`, "button", disabled ? "DISABLED_WITH_REASON" : "WIRED", "read_only", disabled, "POST", "/operator/credentials/validate-readonly"]);
      inventory.push(["providers", `credential_delete_${providerId}`, `Delete ${providerId} local credentials`, "button", disabled ? "DISABLED_WITH_REASON" : "WIRED", "local_secret_write", disabled, "DELETE", "/operator/credentials/provider/{provider_id}"]);
    });
    AI_QUICK_PROMPTS.forEach((prompt, index) => {
      inventory.push(["ai_overlay", `quick_prompt_${index + 1}`, prompt, "button", "WIRED", "read_only", "", null, "select_prompt"]);
    });
    return inventory.map(([pageId, controlId, label, type, status, safetyClass, disabledReason, method, endpoint]) => ({
      pageId,
      controlId,
      label,
      type,
      implementationStatus: status,
      safetyClass,
      disabledReason,
      method,
      endpoint
    }));
  }

  function uiWiringSummary() {
    const inventory = buildUiControlInventory();
    const counts = inventory.reduce((acc, item) => {
      acc[item.implementationStatus] = (acc[item.implementationStatus] || 0) + 1;
      return acc;
    }, {});
    return {
      inventory,
      total: inventory.length,
      wired: counts.WIRED || 0,
      disabledWithReason: counts.DISABLED_WITH_REASON || 0,
      broken: counts.BROKEN || 0,
      notImplemented: 0,
      lastAuditResult: (counts.BROKEN || 0) ? "BROKEN_CONTROLS_PRESENT" : "NO_BROKEN_CONTROLS_DECLARED",
      limitations: [
        "Static inventory is maintained in app.js; browser-level click validation is covered by focused tests and manual validation.",
        "Disabled controls remain visible with reasons instead of being removed."
      ]
    };
  }

  function renderDiagnostics() {
    const d = data.diagnostics;
    const wiring = uiWiringSummary();
    const failures = backendFailureRows();
    return `
      ${header("Diagnostics", "Environment, repo, and local runtime sanity without secrets.", sourceLabel())}
      <div class="card">${kv([
        ["Backend source", badge(sourceLabel(), dataSourceColor())],
        ["Backend fetch", escapeHtml(data.meta.backendStatus || "not inspected")],
        ["Failed endpoints", failures.length ? badge(`${failures.length} degraded`, "yellow") : badge("none", "green")],
        ["Health", badge(d.healthStatus, statusColor(d.healthStatus))],
        ["Runtime profile", badge(d.runtimeProfile, "cyan")],
        ["Hosted mode", badge(String(d.hostedMode), d.hostedMode ? "yellow" : "gray")],
        ["Git commit", escapeHtml(d.gitCommit)],
        ["Dirty worktree", badge(d.dirtyWorktree, "yellow")],
        ["Python version", escapeHtml(d.pythonVersion)],
        ["Credentials", escapeHtml(d.credentials)],
        ["Logs", escapeHtml(d.logs)],
        ["DB", escapeHtml(d.db)],
        ["Session store", badge(d.sessionStoreStatus, statusColor(d.sessionStoreStatus))],
        ["World cache", badge(d.worldCacheStatus, statusColor(d.worldCacheStatus))],
        ["Operator state", escapeHtml(d.operatorStateDir)],
        ["World cache path", escapeHtml(d.worldAwarenessCachePath)],
        ["Latest child stdout", escapeHtml(d.latestChildStdout)],
        ["Latest child stderr", escapeHtml(d.latestChildStderr)]
      ])}
        <details class="ai-context-details">
          <summary>Backend endpoint details</summary>
          ${failures.length ? table(
            ["Endpoint", "Reason"],
            failures.map((failure) => [
              tokenText(failure.endpoint),
              tokenText(failure.reason)
            ])
          ) : `<p class="muted">No backend endpoint failures are currently reported.</p>`}
        </details>
      </div>
      <div class="card" style="margin-top:12px"><h3>UI Wiring Audit</h3>${kv([
        ["Total controls", escapeHtml(wiring.total)],
        ["Wired", badge(wiring.wired, wiring.wired ? "green" : "gray")],
        ["Disabled with reason", badge(wiring.disabledWithReason, wiring.disabledWithReason ? "yellow" : "gray")],
        ["Broken", badge(wiring.broken, wiring.broken ? "red" : "green")],
        ["Not implemented visible", badge(wiring.notImplemented, wiring.notImplemented ? "yellow" : "gray")],
        ["Last audit result", badge(wiring.lastAuditResult, statusColor(wiring.lastAuditResult))]
      ])}
      ${table(
        ["Page", "Control", "Type", "Status", "Safety", "Method", "Endpoint/Action", "Reason"],
        wiring.inventory.map((item) => [
          escapeHtml(item.pageId),
          escapeHtml(item.label),
          escapeHtml(item.type),
          badge(item.implementationStatus, statusColor(item.implementationStatus)),
          badge(item.safetyClass, item.safetyClass === "forbidden" ? "red" : "gray"),
          escapeHtml(item.method || "local"),
          escapeHtml(item.endpoint || "local"),
          escapeHtml(item.disabledReason || "")
        ])
      )}
      <div class="notice mono">Known limitations: ${escapeHtml(wiring.limitations.join(" | "))}</div></div>
    `;
  }

  function renderLive() {
    const l = data.liveReadiness;
    return `
      ${header("Live Locked", "Read-only status. Real-money/live operation is still locked.", l.state)}
      <div class="grid">
        <div class="card span-6"><h3>Live Refusal</h3>${kv([
          ["State", badge(l.state, "red")],
          ["Reason", badge(l.refusal, "red")],
          ["Live start", badge("disabled in v1", "red")],
          ["Endpoint mutation", badge("forbidden", "red")]
        ])}</div>
        <div class="card span-6"><h3>Passed Evidence</h3><div class="stack">${l.passed.map((x) => badge(x, "green")).join("")}</div></div>
        <div class="card span-12"><h3>Missing Before Live</h3><div class="stack">${l.missing.map((x) => badge(x, "red")).join("")}</div></div>
      </div>
    `;
  }

  function uniqueList(items) {
    const seen = new Set();
    const result = [];
    (items || []).forEach((item) => {
      const value = String(item || "").trim();
      if (!value || seen.has(value)) return;
      seen.add(value);
      result.push(value);
    });
    return result;
  }

  function latestRunForAi() {
    const run = (data.runArchive.runs || [])[0];
    if (!run) return null;
    return {
      run_id: run.runId,
      status: run.status,
      final_verdict: run.finalVerdict,
      profile: run.profile || "unknown",
      duration_seconds: run.durationSeconds || "unknown",
      orders: `${run.ordersSubmitted}/${run.ordersAcknowledged}/${run.ordersCanceled}`,
      runtime_new: `posts ${run.orderPostAcknowledged}/${run.orderPostAttempted}; cancels ${run.cancelAcknowledged}/${run.cancelAttempted}; fills ${run.runtimeFills}`,
      historical_broker_local: `broker fills ${run.brokerFilledOrders}; local fills ${run.localFills}; baseline positions ${run.baselinePositionsCount}`,
      broker_methods: `POST ${run.postCount}; DELETE ${run.deleteCount}`,
      open_orders_at_shutdown: run.openOrdersAtShutdown,
      fills_observed: run.fillsObserved,
      tca_status: run.feeTcaStatus || run.tcaStatus,
      readiness_72h: run.readiness72h,
      report_path: run.reportPath || "not generated",
      reason_codes: Array.isArray(run.reasonCodes) ? run.reasonCodes.slice(0, 8) : []
    };
  }

  function aiBlockers() {
    const actionItems = (data.actionCenter.items || [])
      .filter((item) => ["BLOCKER", "SAFETY_CRITICAL", "WARNING", "NEEDS_APPROVAL"].includes(item.type))
      .map((item) => `${item.type}: ${item.title}${item.detail ? ` - ${item.detail}` : ""}`);
    const liveMissing = (data.liveReadiness.missing || []).map((item) => `LIVE_MISSING: ${item}`);
    const alertItems = (data.alerts || [])
      .filter((alert) => alert.severity === "SAFETY_CRITICAL" || alert.severity === "WARNING")
      .map((alert) => `${alert.severity}: ${alert.title}`);
    return uniqueList([
      data.status.dominantBlocker,
      ...actionItems,
      ...alertItems,
      ...liveMissing
    ]).slice(0, 10);
  }

  function aiMissingEvidence(pageId) {
    const p = data.pnl || {};
    const explain = data.explanation || {};
    const tca = data.tcaDashboard || {};
    const defaults = [];
    if ((data.meta.fetchFailures || []).length) defaults.push("Some secondary operator endpoints are degraded.");
    if (!backendConnected()) defaults.push("Backend is unreachable; current state is sample/mock only.");
    if (data.supervisor.state === "IDLE" || data.status.botStatus === "NO_ACTIVE_PAPER_RUN") defaults.push("No active PAPER runtime is attached.");
    if (data.ai.providerState === "AI_DISABLED" || data.ai.providerState === "CREDENTIAL_MISSING") defaults.push(`AI provider state is ${data.ai.providerState}.`);

    const pageSpecific = {
      command: ["Current page uses summarized runtime state, not raw logs."],
      action: ["Action Center items are advisory or approval workflow items; executable flags must remain false."],
      runs: ["Run archive uses metadata and report paths only; raw log contents are not included."],
      historical: ["Historical tests are advisory only; performance fields stay unknown until a governed replay/backtest harness exists."],
      pnl: [
        `Realized P&L source: ${p.realizedPnl && p.realizedPnl.source ? p.realizedPnl.source : "unknown"}.`,
        `TCA status: ${tca.status || "UNKNOWN"}.`
      ],
      positions: ["Positions and orders are summarized; broker account detail is not embedded in AI context."],
      activity: ["Supervisor paths are referenced as paths only; log contents are excluded."],
      decision: [
        `Decision confidence: ${explain.confidence || "LOW"}.`,
        ...(explain.missingTruth || []).map((item) => `Missing truth: ${item}`)
      ],
      market: ["MarketTruthSnapshot rows are summaries; stale/conflict states must stay non-executable."],
      risk: ["Risk gates are explanatory only; AI cannot override hard or economic gates."],
      alerts: ["Watchdog queue is local-only; no external alert delivery is enabled from this panel."],
      ai: ["AI recommendations route through governance and remain can_execute=false."],
      providers: ["Provider readiness is env-var presence only; secret values are never sent to the browser or AI context."],
      research: ["Research registry is advisory only; PAPER proposals require Shan approval and do not start runtime."],
      system: ["System map is explanatory; it is not an authority source for changing engine behavior."],
      audit: ["Audit page uses summarized events only; no raw runtime logs are included."],
      world: ["World Awareness is advisory only and cannot feed executable trade authority."],
      diagnostics: ["Diagnostics expose statuses and paths only; no raw secrets or environment values are included."],
      live: ["Live readiness is locked and requires separate approval outside this UI."]
    };
    return uniqueList([...(pageSpecific[pageId] || []), ...defaults]).slice(0, 10);
  }

  function pageSummaryForAi(pageId) {
    const latestRun = latestRunForAi();
    const p = data.pnl || {};
    const explain = data.explanation || {};
    const summaries = {
      command: [
        `bot=${data.status.botStatus}`,
        `mode=${data.status.runtimeMode}`,
        `supervisor=${data.supervisor.state}`,
        `dominant_blocker=${data.status.dominantBlocker}`,
        `last_decision=${data.status.lastDecision}`
      ],
      action: [
        `blockers=${data.actionCenter.counts.BLOCKER || 0}`,
        `warnings=${data.actionCenter.counts.WARNING || 0}`,
        `needs_approval=${data.actionCenter.counts.NEEDS_APPROVAL || 0}`,
        `safety_critical=${data.actionCenter.counts.SAFETY_CRITICAL || 0}`
      ],
      runs: latestRun
        ? [
            `latest_run=${latestRun.run_id}`,
            `verdict=${latestRun.final_verdict}`,
            `duration=${latestRun.duration_seconds}`,
            `report=${latestRun.report_path}`
          ]
        : ["No run archive entries loaded."],
      historical: [
        `historical_status=${data.historicalTests && data.historicalTests.status ? data.historicalTests.status : "UNKNOWN"}`,
        `simulation_harness_attached=${data.historicalTests && data.historicalTests.simulationHarnessAttached === true}`,
        `read_only_market_data_only=${data.historicalTests && data.historicalTests.readOnlyMarketDataOnly !== false}`,
        "fake_performance_numbers_allowed=false"
      ],
      pnl: [
        `realized=${p.realizedPnl && p.realizedPnl.source ? p.realizedPnl.source : "unknown"}`,
        `unrealized=${p.unrealizedPnl && p.unrealizedPnl.source ? p.unrealizedPnl.source : "unknown"}`,
        `fees=${p.fees && p.fees.source ? p.fees.source : "unknown"}`,
        `tca=${data.tcaDashboard.status || "UNKNOWN"}`,
        "fake_pnl=false"
      ],
      positions: [
        `positions=${(data.positions || []).length}`,
        `orders=${(data.orders || []).length}`,
        "broker_mutation_from_ui=false"
      ],
      activity: [
        `supervisor=${data.supervisor.state}`,
        `session=${data.supervisor.sessionId || "none"}`,
        `paper_start_allowed=${data.supervisor.paperStartAllowed === true}`,
        `last_historical_refusal=${data.supervisor.lastHistoricalRefusal || "none"}`
      ],
      decision: [
        `headline=${explain.headline}`,
        `output=${explain.output || "UNKNOWN"}`,
        `netedge=${explain.netEdge || "UNKNOWN"}`,
        `confidence=${explain.confidence || "LOW"}`,
        `blockers=${(explain.blockers || []).join(", ") || "none"}`
      ],
      market: [
        `snapshot_rows=${(data.marketTruth || []).length}`,
        `executable_rows=${(data.marketTruth || []).filter((row) => row[5] === true).length}`,
        "market_truth_bypass_allowed=false"
      ],
      risk: [
        `risk_gates=${(data.risk || []).length}`,
        `blocked_gates=${(data.risk || []).filter((row) => String(row[2]).includes("BLOCK")).length}`,
        "risk_override_allowed=false"
      ],
      alerts: [
        `alert_count=${(data.alerts || []).length}`,
        `critical=${(data.alerts || []).filter((alert) => alert.severity === "SAFETY_CRITICAL").length}`,
        "external_delivery_enabled=false"
      ],
      ai: [
        `provider=${data.ai.provider}`,
        `provider_state=${data.ai.providerState}`,
        `pending_review=${data.ai.pendingReviewCount || 0}`,
        "can_execute=false"
      ],
      providers: [
        `providers=${data.providerReadiness.providerCount || 0}`,
        `ready_or_configured=${data.providerReadiness.readyOrConfiguredCount || 0}`,
        `missing_credentials=${data.providerReadiness.missingCredentialsCount || 0}`,
        "secrets_values_exposed=false"
      ],
      research: [
        `hypotheses=${data.research.counts.hypotheses || 0}`,
        `experiments=${data.research.counts.experiments || 0}`,
        `promotion_gates=${data.research.counts.promotionGates || 0}`,
        `missing_evidence=${(data.evidenceGraph.missingEvidence || []).join(", ") || "none"}`
      ],
      system: [
        `report=${data.systemMap.reportPath}`,
        `sections=${(data.systemMap.sections || []).join(", ")}`,
        "safe_touch_requires_board_packet=true"
      ],
      audit: [
        `events=${(data.auditLog || []).length}`,
        "raw_logs_included=false"
      ],
      world: [
        `providers=${(data.worldAwareness || []).length}`,
        `active_polling=${data.worldRuntime.providerPollingActive === true}`,
        "feed_can_trade=false"
      ],
      diagnostics: [
        `source=${sourceLabel()}`,
        `backend_status=${data.meta.backendStatus || "not inspected"}`,
        `failed_endpoints=${(data.meta.fetchFailures || []).join("; ") || "none"}`,
        `runtime_profile=${data.diagnostics.runtimeProfile}`
      ],
      live: [
        `state=${data.liveReadiness.state}`,
        `refusal=${data.liveReadiness.refusal}`,
        `missing=${(data.liveReadiness.missing || []).join(", ") || "none"}`,
        "live_start_enabled=false"
      ]
    };
    return uniqueList(summaries[pageId] || summaries.command).slice(0, 10);
  }

  function redactAiContext(value, key) {
    const normalizedKey = String(key || "");
    if (AI_PRESERVED_BOOLEAN_KEYS.has(normalizedKey) && typeof value === "boolean") return value;
    if (AI_SECRET_KEY_PATTERN.test(normalizedKey)) return "REDACTED";
    if (typeof value === "string") {
      return AI_SECRET_VALUE_PATTERN.test(value) ? "REDACTED" : value;
    }
    if (Array.isArray(value)) {
      return value.slice(0, 30).map((item) => redactAiContext(item, normalizedKey));
    }
    if (value && typeof value === "object") {
      return Object.fromEntries(Object.entries(value).map(([childKey, childValue]) => [
        childKey,
        redactAiContext(childValue, childKey)
      ]));
    }
    return value;
  }

  function buildAiChiefContext(question) {
    const latestRun = latestRunForAi();
    const liveLocked = data.status.liveBlocked !== false;
    const realMoneyBlocked = data.status.realMoneyBlocked !== false;
    const context = {
      context_version: AI_CONTEXT_VERSION,
      page_id: activeScreenId,
      page_title: screenTitle(activeScreenId),
      requested_question: question || aiSelectedQuestion,
      backend_source: sourceLabel(),
      data_source: data.meta.dataSource,
      source_integrity: backendConnected()
        ? (data.meta.dataSource === "PARTIAL_BACKEND" ? "backend status connected; secondary context may be degraded" : "backend connected")
        : "sample/mock fallback only; cannot inspect live operator state",
      advisory_only: true,
      can_execute: false,
      ai_cannot: [
        "trade",
        "call broker",
        "enable live",
        "enable real money",
        "submit/cancel/liquidate orders",
        "change thresholds",
        "bypass MarketTruthSnapshot, NetEdge, Risk, BrokerBoundary, OMS, or hard gates"
      ],
      safety_flags: {
        secrets_values_exposed: data.ai.secretsValuesExposed === true,
        raw_logs_included: false,
        broker_call_occurred: false,
        trading_mutation_occurred: false,
        real_money_blocked: realMoneyBlocked,
        live_ready: data.liveReadiness.state === "LIVE_READY_BUT_DISABLED" || data.liveReadiness.state === "LIVE_ENABLED",
        local_paper_ready: data.supervisor.paperStartAllowed === true || data.status.capabilityState === "PAPER_ENABLED"
      },
      runtime: {
        bot_status: data.status.botStatus,
        mode: data.status.runtimeMode,
        profile: data.status.activeProfile,
        supervisor_state: data.supervisor.state,
        process_state: data.supervisor.processState,
        session_id: data.supervisor.sessionId || "none",
        uptime: data.status.uptime,
        paper_start_allowed: data.supervisor.paperStartAllowed === true,
        paper_stop_allowed: data.supervisor.paperStopAllowed === true,
        last_historical_refusal: data.supervisor.lastHistoricalRefusal || "none"
      },
      selected_run: latestRun,
      model_policy: {
        provider_mode: data.ai.providerMode || "NOT_CONFIGURED",
        model_name: data.ai.modelName || null,
        model_quality: data.ai.modelQuality || "FALLBACK_ONLY",
        reasoning_policy: data.ai.reasoningPolicy || "FALLBACK_ONLY_LIMITED",
        model_suitable_for_governance: data.ai.modelSuitableForGovernance === true,
        warning: aiModelWarning(),
        routing_settings: aiRoutingSettings(),
        provider_registry_count: aiProviderCards().length
      },
      provider_readiness: {
        provider_count: data.providerReadiness.providerCount || 0,
        ready_or_configured_count: data.providerReadiness.readyOrConfiguredCount || 0,
        missing_credentials_count: data.providerReadiness.missingCredentialsCount || 0,
        not_implemented_count: data.providerReadiness.notImplementedCount || 0,
        secrets_values_exposed: false
      },
      research_registry: {
        hypotheses: data.research.counts.hypotheses || 0,
        experiments: data.research.counts.experiments || 0,
        recommendations: data.research.counts.recommendations || 0,
        promotion_gates: data.research.counts.promotionGates || 0,
        can_execute: false
      },
      evidence_graph: {
        latest_run_id: data.evidenceGraph.latestRunId || null,
        missing_evidence: data.evidenceGraph.missingEvidence || [],
        promotion_blockers: data.evidenceGraph.promotionBlockers || [],
        raw_logs_included: false,
        secrets_values_exposed: false
      },
      launch_readiness: {
        final: data.launchReadiness.finalLaunchReadiness || "UNKNOWN",
        reason_codes: data.launchReadiness.reasonCodes || [],
        alpaca_paper_credentials_configured: data.launchReadiness.alpacaPaperCredentialsConfigured === true,
        paper_start_allowed: data.launchReadiness.paperStartAllowed === true,
        safe_stop_status: data.launchReadiness.safeStopStatus || "UNKNOWN"
      },
      portfolio: {
        status: data.portfolio.status || "UNKNOWN",
        data_source: data.portfolio.dataSource || "UNKNOWN",
        unavailable_reason: data.portfolio.unavailableReason || null,
        summary: data.portfolio.summary || {},
        positions: (data.portfolio.positions || []).slice(0, 10).map((p) => ({
          symbol: p.symbol,
          quantity: p.quantity,
          market_value: p.marketValue,
          unrealized_pnl: p.unrealizedPnl,
          exposure: p.exposurePercentOfPortfolio,
          source: p.source,
          broker_confirmed: p.brokerConfirmed === true,
          risk_status: p.riskStatus
        })),
        open_orders: (data.portfolio.openOrders || []).slice(0, 10).map((o) => ({
          symbol: o.symbol,
          side: o.side,
          qty: o.qty,
          type: o.type,
          status: o.status,
          read_only: true,
          can_cancel: false
        })),
        broker_mutation_occurred: false
      },
      blockers: aiBlockers(),
      missing_evidence: aiMissingEvidence(activeScreenId),
      page_summary: pageSummaryForAi(activeScreenId)
    };
    return redactAiContext(context);
  }

  function renderAiContextPreview(context) {
    const latestRun = context.selected_run || {};
    return `
      <div class="ai-context-preview">
        <div class="split">
          <h3>Allowed Context Preview</h3>
          ${badge(context.data_source || "UNKNOWN", dataSourceColor())}
        </div>
        ${kv([
          ["Page", escapeHtml(`${context.page_title} (${context.page_id})`)],
          ["Source", escapeHtml(context.backend_source)],
          ["Live locked", badge(String(data.status.liveBlocked !== false), data.status.liveBlocked !== false ? "red" : "yellow")],
          ["Real-money blocked", badge(String(context.safety_flags.real_money_blocked), context.safety_flags.real_money_blocked ? "red" : "yellow")],
          ["Runtime", escapeHtml(`${context.runtime.bot_status} / ${context.runtime.supervisor_state}`)],
          ["Model", escapeHtml(`${context.model_policy.model_name || "none"} / ${context.model_policy.model_quality}`)],
          ["Provider mode", badge(context.model_policy.provider_mode || "NOT_CONFIGURED", statusColor(context.model_policy.provider_mode || "NOT_CONFIGURED"))],
          ["Selected run", escapeHtml(latestRun.run_id || "none")],
          ["Major blockers", escapeHtml(context.blockers.slice(0, 3).join(" | ") || "none")],
          ["Missing evidence", escapeHtml(context.missing_evidence.slice(0, 3).join(" | ") || "none")],
          ["Secrets exposed", badge(String(context.safety_flags.secrets_values_exposed), context.safety_flags.secrets_values_exposed ? "red" : "green")],
          ["Raw logs included", badge(String(context.safety_flags.raw_logs_included), context.safety_flags.raw_logs_included ? "red" : "green")]
        ])}
        <details class="ai-context-details">
          <summary>Redacted JSON preview</summary>
          <pre class="code ai-context-json">${escapeHtml(JSON.stringify(context, null, 2))}</pre>
        </details>
      </div>
    `;
  }

  function buildAiOverlayAdvisory(question) {
    const context = buildAiChiefContext(question);
    const sourceWarning = backendConnected()
      ? `${context.backend_source}.`
      : "Backend is unreachable; this is sample context and cannot be treated as runtime truth.";
    const blockers = context.blockers.length ? context.blockers.slice(0, 3).join("; ") : "No major blocker is loaded for this page.";
    const missing = context.missing_evidence.length ? context.missing_evidence.slice(0, 3).join("; ") : "No page-specific missing evidence is loaded.";
    const latestRun = context.selected_run;

    if (question === "Draft a Codex packet.") {
      return [
        "Local redacted context preview, not a real model response.",
        sourceWarning,
        `Draft packet focus: inspect ${context.page_title}, preserve live/real-money locks, keep can_execute=false, do not touch broker/execution/OMS/strategy, and use only redacted operator summaries.`,
        `Primary evidence to include: ${context.page_summary.slice(0, 4).join("; ")}.`,
        "Next safest action: ask for a scoped frontend/advisory repair unless backend truth is missing."
      ].join("\n");
    }

    if (question === "Critique latest run." || question === "Compare latest run to expected behavior.") {
      return [
        "Local redacted context preview, not a real model response.",
        sourceWarning,
        latestRun
          ? `Latest run ${latestRun.run_id} is ${latestRun.final_verdict} with TCA ${latestRun.tca_status} and report ${latestRun.report_path}.`
          : "No run archive entry is loaded.",
        `Missing evidence: ${missing}`,
        "Next safest action: review the generated report path and reason codes without opening raw logs in AI context."
      ].join("\n");
    }

    if (question === "Where are fees/slippage hurting us?") {
      return [
        "Local redacted context preview, not a real model response.",
        sourceWarning,
        `NetEdge summary: ${data.pnl.netEdge || "UNKNOWN"}; TCA status: ${data.tcaDashboard.status || "UNKNOWN"}.`,
        `Fee/P&L truth labels: realized=${data.pnl.realizedPnl.source}, fees=${data.pnl.fees.source}.`,
        "Do not invent P&L, fees, fills, slippage, or TCA. Unknown must remain unknown."
      ].join("\n");
    }

    if (question === "Where is the edge?") {
      return [
        "Local redacted context preview, not a real model response.",
        sourceWarning,
        `Candidate edge evidence: ${context.page_summary.slice(0, 5).join("; ")}.`,
        `Current blockers/missing evidence: ${blockers}; ${missing}`,
        "Treat edge as unproven until DecisionFrame, MarketTruthSnapshot, NetEdge, TCA, fees, and replay/PAPER evidence agree."
      ].join("\n");
    }

    if (question === "Review provider/data readiness.") {
      return [
        "Local redacted context preview, not a real model response.",
        sourceWarning,
        `Providers loaded: ${context.provider_readiness.provider_count}; ready/configured: ${context.provider_readiness.ready_or_configured_count}; missing credentials: ${context.provider_readiness.missing_credentials_count}.`,
        "Provider context is env-var presence only. No secret values are visible to the UI or AI."
      ].join("\n");
    }

    return [
      "Local redacted context preview, not a real model response.",
      sourceWarning,
      `Current page: ${context.page_title}.`,
      `Care about: ${context.page_summary.slice(0, 4).join("; ")}.`,
      `Unsafe or missing: ${blockers}; ${missing}`,
      "Next safest action: keep this advisory-only, review blockers, and route any recommendation through governance. AI cannot trade, call broker, enable live, or change thresholds."
    ].join("\n");
  }

  function normalizeAiCallTrace(payload, answerSource) {
    const trace = payload.ai_call_trace || payload.aiCallTrace || {};
    const blockedTerms = Array.isArray(trace.blocked_terms)
      ? trace.blocked_terms
      : (Array.isArray(payload.blocked_terms) ? payload.blocked_terms : []);
    return {
      requestId: trace.request_id || payload.request_id || "",
      intent: trace.intent || payload.intent || "",
      selectedProvider: trace.selected_provider || trace.selectedProvider || payload.provider_id || payload.provider || "deterministic_local",
      selectedModel: trace.selected_model || trace.selectedModel || payload.model_name || payload.model || "deterministic-local-guide",
      actualProviderId: trace.actual_provider_id || trace.actualProviderId || payload.provider_id || payload.provider || "deterministic_local",
      actualModelName: trace.actual_model_name || trace.actualModelName || payload.actual_model_name || payload.model_name || payload.model || "deterministic-local-guide",
      routeMode: trace.route_mode || trace.routeMode || "",
      providerCallAttempted: trace.provider_call_attempted === true || trace.providerCallAttempted === true || payload.model_call_attempted === true,
      providerResponseReceived: trace.provider_response_received === true || trace.providerResponseReceived === true || payload.provider_response_received === true,
      modelCallOccurred: trace.model_call_occurred === true || trace.modelCallOccurred === true || payload.model_call_occurred === true,
      actualAnswerSource: trace.actual_answer_source || trace.actualAnswerSource || answerSource || "LOCAL_DETERMINISTIC",
      fallbackUsed: trace.fallback_used === true || trace.fallbackUsed === true,
      fallbackReason: trace.fallback_reason || trace.fallbackReason || payload.fallback_reason || "",
      safetyFilterTriggered: trace.safety_filter_triggered === true || trace.safetyFilterTriggered === true || payload.safety_filter_triggered === true,
      blockedTerms,
      challengeNoncePresent: trace.challenge_nonce_present === true || trace.challengeNoncePresent === true || payload.challenge_nonce_present === true,
      challengeNonce: trace.challenge_nonce || trace.challengeNonce || payload.challenge_nonce || "",
      challengeEchoed: trace.challenge_echoed === true || trace.challengeEchoed === true || payload.challenge_echoed === true,
      httpStatusCode: trace.http_status_code || trace.httpStatusCode || payload.http_status_code || "",
      providerRequestId: trace.provider_request_id || trace.providerRequestId || payload.provider_request_id || "",
      latencyMs: trace.latency_ms || trace.latencyMs || payload.latency_ms || "",
      endpointFamily: trace.endpoint_family || trace.endpointFamily || payload.endpoint_family || (answerSource === "LOCAL_DETERMINISTIC" ? "local_deterministic" : "unknown"),
      requestedAnswerMode: trace.requested_answer_mode || trace.requestedAnswerMode || payload.requested_answer_mode || payload.requestedAnswerMode || "",
      effectiveAnswerMode: normalizeAiAnswerMode(trace.effective_answer_mode || trace.effectiveAnswerMode || payload.effective_answer_mode || payload.answer_mode || payload.answerMode || payload.effectiveAnswerMode),
      answerModeStatus: trace.answer_mode_status || trace.answerModeStatus || payload.answer_mode_status || payload.answerModeStatus || "",
      displaySourceLabel: trace.display_source_label || trace.displaySourceLabel || payload.display_source_label || payload.displaySourceLabel || ""
    };
  }

  function normalizeAiAskResult(result, fallbackAnswer) {
    const payload = result || {};
    const providerMode = payload.provider_mode || payload.providerMode || "DETERMINISTIC_FALLBACK";
    const modelQuality = payload.model_quality || payload.modelQuality || "FALLBACK_ONLY";
    const answerSource = payload.answer_source || payload.response_source || payload.answerSource || "LOCAL_DETERMINISTIC";
    const aiCallTrace = normalizeAiCallTrace(payload, answerSource);
    return {
      status: payload.status || "ANSWERED_FALLBACK",
      requestedAnswerMode: payload.requested_answer_mode || payload.requestedAnswerMode || "",
      effectiveAnswerMode: normalizeAiAnswerMode(payload.effective_answer_mode || payload.answer_mode || payload.answerMode || aiCallTrace.effectiveAnswerMode),
      answerModeStatus: payload.answer_mode_status || payload.answerModeStatus || aiCallTrace.answerModeStatus || "",
      displaySourceLabel: payload.display_source_label || payload.displaySourceLabel || aiCallTrace.displaySourceLabel || "",
      providerId: payload.provider_id || payload.provider || payload.providerId || "deterministic_local",
      providerMode,
      providerState: payload.provider_state || payload.providerState || data.ai.providerState || "AI_DISABLED",
      modelName: payload.model_name || payload.model || payload.modelName || "deterministic-local-guide",
      modelQuality,
      costMode: payload.cost_mode || payload.costMode || "FREE_LOCAL",
      answerSource,
      reasoningPolicy: payload.reasoning_policy || payload.reasoningPolicy || "FALLBACK_ONLY_LIMITED",
      modelSuitableForGovernance: payload.model_suitable_for_governance === true || payload.governance_suitable === true,
      personaEnforced: payload.persona_enforced !== false,
      expertRolesApplied: Array.isArray(payload.expert_roles_applied) ? payload.expert_roles_applied : [],
      mode: payload.mode || "OPERATOR_GUIDE",
      evidenceLevel: payload.evidence_level || payload.evidenceLevel || "UNKNOWN",
      answer: payload.answer || payload.response || fallbackAnswer || "No advisory response returned.",
      packetText: payload.packet || payload.draft_packet || payload.packetText || "",
      knownFacts: Array.isArray(payload.known_facts) ? payload.known_facts : [],
      unknowns: Array.isArray(payload.unknowns) ? payload.unknowns : [],
      nextStepLabel: payload.next_step_label || "Review current page",
      nextStepPage: payload.next_step_page || "",
      nextStepControlId: payload.next_step_control_id || "",
      needsCodexPacket: payload.needs_codex_packet === true,
      suggestedCodexPacketSummary: payload.suggested_codex_packet_summary || "",
      providerErrorCategory: payload.provider_error_category || payload.error_category || "",
      providerErrorMessageSafe: payload.provider_error_message_safe || payload.safe_error_message || "",
      modelCallAttempted: payload.model_call_attempted === true || payload.modelCallAttempted === true,
      modelCallOccurred: payload.model_call_occurred === true || payload.modelCallOccurred === true,
      providerResponseReceived: payload.provider_response_received === true || payload.providerResponseReceived === true,
      fallbackReason: payload.fallback_reason || payload.fallbackReason || "",
      safetyFilterTriggered: payload.safety_filter_triggered === true || payload.safetyFilterTriggered === true || aiCallTrace.safetyFilterTriggered === true,
      blockedTerms: Array.isArray(payload.blocked_terms) ? payload.blocked_terms : aiCallTrace.blockedTerms,
      aiCallTrace,
      canExecute: payload.can_execute === true,
      brokerCallOccurred: payload.broker_call_occurred === true,
      tradingMutationOccurred: payload.trading_mutation_occurred === true,
      liveEnabled: payload.live_enabled === true,
      realMoneyEnabled: payload.real_money_enabled === true,
      secretsExposed: payload.secrets_exposed === true || payload.secrets_values_exposed === true,
      rawLogsIncluded: payload.raw_logs_included === true
    };
  }

  function localAiResult(question, answer, overrides) {
    const payload = {
      status: "ANSWERED_LOCAL_GUIDE",
      requested_answer_mode: AI_ANSWER_MODES.DETERMINISTIC,
      effective_answer_mode: AI_ANSWER_MODES.DETERMINISTIC,
      answer_mode: AI_ANSWER_MODES.DETERMINISTIC,
      answer_mode_status: "UI_LOCAL_DETERMINISTIC",
      display_source_label: "Deterministic local UI fallback",
      provider_id: "deterministic_local",
      provider_mode: "DETERMINISTIC_FALLBACK",
      provider_state: backendConnected() ? "LOCAL_GUIDE" : "BACKEND_UNREACHABLE",
      model_name: "deterministic-local-guide",
      model_quality: "FALLBACK_ONLY",
      cost_mode: "FREE_LOCAL",
      answer_source: "LOCAL_DETERMINISTIC",
      reasoning_policy: "FALLBACK_ONLY_LIMITED",
      model_suitable_for_governance: false,
      persona_enforced: true,
      expert_roles_applied: ["Chief Quant Advisor", "Quant Engineer", "Trading Systems Auditor", "Operator Guide"],
      mode: "OPERATOR_GUIDE",
      evidence_level: backendConnected() ? "SYSTEM_STATE" : "UNKNOWN",
      answer,
      known_facts: pageSummaryForAi(activeScreenId || "positions").slice(0, 4),
      unknowns: aiMissingEvidence(activeScreenId || "positions").slice(0, 4),
      next_step_label: "Review the highlighted blocker and use the visible safe control.",
      next_step_page: activeScreenId || "positions",
      next_step_control_id: "",
      can_execute: false,
      broker_call_occurred: false,
      trading_mutation_occurred: false,
      live_enabled: false,
      real_money_enabled: false,
      secrets_exposed: false,
      raw_logs_included: false,
      requested_question: question || ""
    };
    return normalizeAiAskResult({ ...payload, ...(overrides || {}) }, answer);
  }

  function aiFriendlyStatus(result) {
    if (aiOverlayBusy && !result) return "Asking Chief Quant Advisor...";
    if (!result) return "Local deterministic guide preview. Ask a question for a fresh advisory response.";
    if (result.providerMode === "PROVIDER_ERROR" || result.answerSource === "PROVIDER_ERROR") {
      return "Provider error shown. Local fallback is labeled; no silent provider switch occurred.";
    }
    if (result.providerMode === "DETERMINISTIC_FALLBACK" || result.modelQuality === "FALLBACK_ONLY") {
      return "Deterministic local fallback. Limited advisory answer.";
    }
    return "Live advisory response returned. Advisory only.";
  }

  function aiPacketText(result) {
    if (!result) return "";
    return result.packetText || (result.answerSource === "SUPREME_BOARD_PACKET" ? result.answer : "");
  }

  function aiProviderErrorText(result) {
    if (!result) return "";
    return result.providerErrorCategory || result.providerErrorMessageSafe || "";
  }

  function aiResultIsFallback(result) {
    if (!result) return false;
    return result.providerMode === "DETERMINISTIC_FALLBACK" || result.modelQuality === "FALLBACK_ONLY" || result.answerSource === "LOCAL_DETERMINISTIC";
  }

  function aiResultIsProviderError(result) {
    if (!result) return false;
    return result.providerMode === "PROVIDER_ERROR" || result.answerSource === "PROVIDER_ERROR" || Boolean(aiProviderErrorText(result));
  }

  function aiMessageTime(value) {
    const date = value ? new Date(value) : new Date();
    if (Number.isNaN(date.getTime())) return "";
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function nextAiMessageId(prefix) {
    aiMessageSequence += 1;
    return `${prefix || "ai"}-${aiMessageSequence}`;
  }

  function appendAiMessage(message) {
    const now = new Date().toISOString();
    const next = {
      id: message.id || nextAiMessageId(message.role || "message"),
      role: message.role || "assistant",
      status: message.status || "complete",
      question: message.question || "",
      answer: message.answer || "",
      result: message.result || null,
      routeLabel: message.routeLabel || "",
      createdAt: message.createdAt || now,
      updatedAt: message.updatedAt || now,
      error: message.error || ""
    };
    aiConversation = aiConversation.concat(next);
    return next;
  }

  function replaceAiMessage(messageId, patch) {
    const now = new Date().toISOString();
    aiConversation = aiConversation.map((message) => (
      message.id === messageId ? { ...message, ...patch, updatedAt: now } : message
    ));
  }

  function appendAiCompletedExchange(question, result, options) {
    const normalized = result && result.providerMode ? result : normalizeAiAskResult(result || {}, result && result.answer);
    if (options && options.includeUser === true) {
      appendAiMessage({ role: "user", status: "complete", question, answer: question });
    }
    appendAiMessage({
      role: "assistant",
      status: (options && options.status) || "complete",
      question,
      answer: normalized.answer,
      result: normalized,
      error: (options && options.error) || ""
    });
    aiOverlayResponse = normalized.answer;
    aiOverlayLastResult = normalized;
    return normalized;
  }

  function latestAiAssistantResult() {
    for (let index = aiConversation.length - 1; index >= 0; index -= 1) {
      const message = aiConversation[index];
      if (message && message.role === "assistant" && message.result) return message.result;
    }
    return aiOverlayLastResult;
  }

  function aiActiveRouteLabels(routing, result) {
    const route = aiAskRoutingPayload(routing);
    const selectedProviderId = routing.activeProvider || (result && result.providerId) || "deterministic_local";
    const routeMode = route.routeMode || routing.defaultMode || "LOCAL_GUIDE";
    const currentProviderId = route.providerId || (routeMode === "SUPREME_BOARD_PACKET" ? "supreme_board_packet" : "deterministic_local");
    const activeModel = route.modelName || routing.activeModel || (result && result.modelName) || "deterministic-local-guide";
    const selectedProviderDisplay = providerDisplayLabel(selectedProviderId || "deterministic_local");
    const currentAnswerSource = result && result.answerSource ? result.answerSource : "none yet";
    const fallbackAnswered = Boolean(result && aiResultIsFallback(result) && currentAnswerSource === "LOCAL_DETERMINISTIC");
    const providerFailed = Boolean(result && aiResultIsProviderError(result));
    const externalProviderSelected = isExternalAiApiProvider(selectedProviderId) || isExternalAiApiProvider(currentProviderId);
    let currentProviderDisplay = providerDisplayLabel(currentProviderId || "deterministic_local");
    let compactLine = `${currentProviderDisplay} active | Advisory only | Broker actions blocked`;
    if (providerFailed && externalProviderSelected) {
      currentProviderDisplay = "Provider error";
      compactLine = `${selectedProviderDisplay} selected | provider call failed | Broker actions blocked`;
    } else if (fallbackAnswered && externalProviderSelected) {
      currentProviderDisplay = "Safe local fallback";
      compactLine = `${selectedProviderDisplay} selected | safe local fallback answered this question | Broker actions blocked`;
    } else if (fallbackAnswered) {
      currentProviderDisplay = "Safe local fallback";
      compactLine = "Safe local fallback active | Advisory only | Broker actions blocked";
    } else if (result && currentAnswerSource === "SUPREME_BOARD_PACKET") {
      compactLine = "Supreme Board packet mode | Advisory only | Broker actions blocked";
    } else if (result && currentAnswerSource !== "none yet") {
      compactLine = `${currentProviderDisplay} answered | Advisory only | Broker actions blocked`;
    }
    return {
      route,
      selectedProviderId,
      currentProviderId,
      selectedProviderDisplay,
      currentProviderDisplay,
      activeModel,
      currentAnswerSource,
      routeMode,
      compactLine
    };
  }

  function renderAiBullets(items, emptyLabel) {
    const safeItems = (items || []).slice(0, 3);
    if (!safeItems.length) return `<p class="muted">${escapeHtml(emptyLabel || "none returned")}</p>`;
    return `<ul class="compact-list">${safeItems.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
  }

  function renderAiNextStep(result) {
    return `
      <div class="ai-next-step">
        <strong>Next step:</strong> ${escapeHtml(result.nextStepLabel || "Review current page")}
        ${result.nextStepPage ? `<span class="muted"> | ${escapeHtml(result.nextStepPage)}</span>` : ""}
        ${result.suggestedCodexPacketSummary ? `<div class="notice">${escapeHtml(result.suggestedCodexPacketSummary)}</div>` : ""}
      </div>
    `;
  }

  function aiContextLaunchReadiness(context) {
    const readiness = context && (context.launch_readiness || context.launchReadiness);
    return readiness && (readiness.final_launch_readiness || readiness.finalLaunchReadiness || readiness.final || "");
  }

  function aiContextPaperStartAllowed(context) {
    const readiness = context && (context.launch_readiness || context.launchReadiness);
    const runtime = context && context.runtime;
    return Boolean(
      (readiness && (readiness.paper_start_allowed === true || readiness.paperStartAllowed === true)) ||
      (runtime && (runtime.paper_start_allowed === true || runtime.paperStartAllowed === true))
    );
  }

  function aiReadyIdleNoActiveRuntime(context) {
    const blockers = context && Array.isArray(context.blockers) ? context.blockers : [];
    const runtime = context && context.runtime;
    const supervisorState = runtime && String(runtime.supervisor_state || runtime.supervisorState || "").toUpperCase();
    const processState = runtime && String(runtime.process_state || runtime.processState || runtime.bot_status || runtime.botStatus || "").toUpperCase();
    return (
      blockers.includes("READY_IDLE_NO_ACTIVE_RUNTIME") ||
      blockers.includes("READY_IDLE_NO_ACTIVE_PAPER_RUN") ||
      blockers.includes("IDLE_NO_ACTIVE_PAPER_RUN") ||
      (["READY_FOR_GOVERNED_PAPER", "READY_FOR_BOUNDED_PAPER"].includes(aiContextLaunchReadiness(context)) && aiContextPaperStartAllowed(context) && supervisorState === "IDLE" && processState !== "RUNNING")
    );
  }

  function aiActualBlocker(context) {
    const blockers = context && Array.isArray(context.blockers) ? context.blockers : [];
    return blockers.find((item) => {
      const value = String(item || "");
      if (!value || value === "READY_IDLE_NO_ACTIVE_RUNTIME" || value === "READY_IDLE_NO_ACTIVE_PAPER_RUN" || value === "IDLE_NO_ACTIVE_PAPER_RUN") return false;
      if (value.startsWith("WARNING:")) return false;
      if (value.startsWith("LIVE_MISSING:")) return false;
      return value.startsWith("BLOCKER:") || /^[A-Z0-9_]+$/.test(value);
    }) || "";
  }

  function aiPreferredKnownFact(result) {
    const facts = result && Array.isArray(result.knownFacts) ? result.knownFacts : [];
    return facts.find((item) => /READY_FOR_GOVERNED_PAPER|READY_FOR_BOUNDED_PAPER|Supervisor:|Paper start allowed|Launch readiness/i.test(String(item || ""))) || facts[0] || "";
  }

  function aiAnswerMetaText(result, createdAt) {
    const timestamp = aiMessageTime(createdAt);
    const trace = result.aiCallTrace || {};
    const source = trace.actualAnswerSource || result.answerSource || "LOCAL_DETERMINISTIC";
    const providerLabel = providerDisplayLabel(trace.actualProviderId || result.providerId || "deterministic_local");
    const modelName = trace.actualModelName || result.modelName || "model unknown";
    const fallbackReason = trace.fallbackReason || result.fallbackReason || result.providerErrorMessageSafe || result.providerErrorCategory || "provider unavailable";
    const modeLabel = aiAnswerModeLabel(result.effectiveAnswerMode || trace.effectiveAnswerMode);
    const displaySource = result.displaySourceLabel || trace.displaySourceLabel || source;
    if (trace.safetyFilterTriggered || result.safetyFilterTriggered) {
      return `${modeLabel} | ${displaySource} | safety filtered | ${timestamp}`;
    }
    if ((trace.modelCallOccurred === true || result.modelCallOccurred === true) && ["API_LIGHT_MODEL", "API_HIGH_REASONING_APPROVED", "LOCAL_MODEL"].includes(source)) {
      return `${modeLabel} | ${providerLabel} answered | ${modelName} | ${source} | ${timestamp}`;
    }
    if ((trace.providerCallAttempted === true || result.modelCallAttempted === true) && (trace.modelCallOccurred !== true && result.modelCallOccurred !== true)) {
      const fallbackSource = source === "PROVIDER_ERROR" ? "LOCAL_DETERMINISTIC" : source;
      return `${modeLabel} | Safe local fallback | ${fallbackSource} | provider call failed: ${fallbackReason} | ${timestamp}`;
    }
    if (aiResultIsFallback(result)) {
      return `${modeLabel} | ${displaySource} | no provider call | ${timestamp}`;
    }
    if (result.answerSource === "SUPREME_BOARD_PACKET") {
      return `${modeLabel} | Supreme Board packet mode | ${source} | ${timestamp}`;
    }
    if (aiResultIsProviderError(result)) {
      return `${modeLabel} | Provider error | ${source} | no model answer | ${timestamp}`;
    }
    return `${modeLabel} | ${providerLabel} selected | ${modelName} | ${source} | ${timestamp}`;
  }

  function aiEvidenceBullets(result, context) {
    const bullets = [];
    if (result.evidenceLevel) bullets.push(`Evidence level: ${result.evidenceLevel}`);
    const blocker = aiActualBlocker(context);
    if (aiReadyIdleNoActiveRuntime(context)) {
      bullets.push("Current state: IDLE_NO_ACTIVE_PAPER_RUN");
    } else if (blocker) {
      bullets.push(`Current blocker: ${blocker}`);
    }
    const known = aiPreferredKnownFact(result);
    if (known) bullets.push(`Known: ${known}`);
    (result.unknowns || []).slice(0, 1).forEach((item) => bullets.push(`Unknown: ${item}`));
    return uniquePrompts(bullets).slice(0, 3);
  }

  function renderAiEvidenceSummary(result, context) {
    const bullets = aiEvidenceBullets(result, context);
    return `
      <div class="ai-evidence-summary">
        <h3>Evidence Summary</h3>
        ${bullets.length ? `<ul class="compact-list">${bullets.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : `<p class="muted">No evidence bullets returned.</p>`}
      </div>
    `;
  }

  function renderAiPacketPanel(result) {
    const packet = aiPacketText(result);
    if (!packet) return "";
    return `
      <details class="ai-context-details ai-packet-details">
        <summary>View packet</summary>
        <div class="button-row compact-actions">
          <button class="intent-button paper" type="button" data-ai-copy-packet>Copy packet</button>
        </div>
        <pre class="ai-context-json">${escapeHtml(packet)}</pre>
      </details>
    `;
  }

  function renderAiCollapsedDetails(result, context) {
    return `
      <details class="ai-context-details ai-diagnostics-details">
        <summary>Advanced details</summary>
        ${renderAiEvidenceSummary(result, context)}
        ${renderAiNextStep(result)}
        <div class="ai-context-preview">
          <h3>Known Facts</h3>
          ${renderAiBullets(result.knownFacts, "No known facts returned.")}
          <h3>Missing Evidence</h3>
          ${renderAiBullets(result.unknowns, "No missing evidence returned.")}
        </div>
        ${renderAiContextPreview(context)}
        <div class="ai-context-preview">
          <h3>AI Call Trace</h3>
          ${kv([
            ["Request ID", escapeHtml(result.aiCallTrace.requestId || "none")],
            ["Effective answer mode", badge(result.aiCallTrace.effectiveAnswerMode || result.effectiveAnswerMode || "DETERMINISTIC", statusColor(result.aiCallTrace.effectiveAnswerMode || result.effectiveAnswerMode || "DETERMINISTIC"))],
            ["Answer mode status", escapeHtml(result.aiCallTrace.answerModeStatus || result.answerModeStatus || "none")],
            ["Display source", escapeHtml(result.aiCallTrace.displaySourceLabel || result.displaySourceLabel || "not returned")],
            ["Intent", badge(result.aiCallTrace.intent || "UNKNOWN", statusColor(result.aiCallTrace.intent || "UNKNOWN"))],
            ["Selected provider/model", escapeHtml(`${providerDisplayLabel(result.aiCallTrace.selectedProvider)} / ${result.aiCallTrace.selectedModel || "none"}`)],
            ["Actual provider/model", escapeHtml(`${providerDisplayLabel(result.aiCallTrace.actualProviderId)} / ${result.aiCallTrace.actualModelName || "none"}`)],
            ["Endpoint family", badge(result.aiCallTrace.endpointFamily || "unknown", statusColor(result.aiCallTrace.endpointFamily || "unknown"))],
            ["Provider call attempted", badge(String(result.aiCallTrace.providerCallAttempted), result.aiCallTrace.providerCallAttempted ? "green" : "gray")],
            ["Provider response received", badge(String(result.aiCallTrace.providerResponseReceived), result.aiCallTrace.providerResponseReceived ? "green" : "gray")],
            ["Model call occurred", badge(String(result.aiCallTrace.modelCallOccurred), result.aiCallTrace.modelCallOccurred ? "green" : "gray")],
            ["Actual answer source", badge(result.aiCallTrace.actualAnswerSource || result.answerSource, statusColor(result.aiCallTrace.actualAnswerSource || result.answerSource))],
            ["Fallback used", badge(String(result.aiCallTrace.fallbackUsed), result.aiCallTrace.fallbackUsed ? "yellow" : "green")],
            ["Fallback reason", escapeHtml(result.aiCallTrace.fallbackReason || "none")],
            ["Safety filter triggered", badge(String(result.aiCallTrace.safetyFilterTriggered), result.aiCallTrace.safetyFilterTriggered ? "red" : "green")],
            ["Blocked terms", escapeHtml((result.aiCallTrace.blockedTerms || []).join(", ") || "none")],
            ["Challenge nonce present", badge(String(result.aiCallTrace.challengeNoncePresent), result.aiCallTrace.challengeNoncePresent ? "green" : "gray")],
            ["Challenge echoed", badge(String(result.aiCallTrace.challengeEchoed), result.aiCallTrace.challengeEchoed ? "green" : "gray")],
            ["Latency ms", escapeHtml(String(result.aiCallTrace.latencyMs || "not returned"))],
            ["Provider request id", escapeHtml(result.aiCallTrace.providerRequestId || "not returned")]
          ])}
        </div>
        <div class="ai-context-preview">
          <h3>Provider / Model Diagnostics</h3>
          ${kv([
            ["Status", escapeHtml(result.status)],
            ["Answer mode", badge(result.effectiveAnswerMode || "DETERMINISTIC", statusColor(result.effectiveAnswerMode || "DETERMINISTIC"))],
            ["Display source", escapeHtml(result.displaySourceLabel || "not returned")],
            ["Provider ID", escapeHtml(result.providerId)],
            ["Provider mode", badge(result.providerMode, statusColor(result.providerMode))],
            ["Provider state", badge(result.providerState, statusColor(result.providerState))],
            ["Model", escapeHtml(result.modelName)],
            ["Model quality", badge(result.modelQuality, modelQualityColor(result.modelQuality))],
            ["Answer source", badge(result.answerSource, statusColor(result.answerSource))],
            ["Model call attempted", badge(String(result.modelCallAttempted), result.modelCallAttempted ? "green" : "gray")],
            ["Model call occurred", badge(String(result.modelCallOccurred), result.modelCallOccurred ? "green" : "gray")],
            ["Provider response received", badge(String(result.providerResponseReceived), result.providerResponseReceived ? "green" : "gray")],
            ["Fallback reason", escapeHtml(result.fallbackReason || "none")],
            ["Cost mode", badge(result.costMode, statusColor(result.costMode))],
            ["Reasoning policy", badge(result.reasoningPolicy, statusColor(result.reasoningPolicy))],
            ["Governance suitable", badge(String(result.modelSuitableForGovernance), result.modelSuitableForGovernance ? "green" : "red")],
            ["Persona enforced", badge(String(result.personaEnforced), result.personaEnforced ? "green" : "red")],
            ["Expert roles", escapeHtml(result.expertRolesApplied.join(", ") || "not returned")],
            ["Provider error category", escapeHtml(result.providerErrorCategory || "none")],
            ["Provider error message", escapeHtml(result.providerErrorMessageSafe || "none")]
          ])}
        </div>
        <div class="ai-context-preview">
          <h3>Safety Flags</h3>
          ${kv([
            ["can_execute", badge(String(result.canExecute), result.canExecute ? "red" : "green")],
            ["broker_call_occurred", badge(String(result.brokerCallOccurred), result.brokerCallOccurred ? "red" : "green")],
            ["trading_mutation_occurred", badge(String(result.tradingMutationOccurred), result.tradingMutationOccurred ? "red" : "green")],
            ["live_enabled", badge(String(result.liveEnabled), result.liveEnabled ? "red" : "green")],
            ["real_money_enabled", badge(String(result.realMoneyEnabled), result.realMoneyEnabled ? "red" : "green")],
            ["secrets_exposed", badge(String(result.secretsExposed), result.secretsExposed ? "red" : "green")],
            ["raw_logs_included", badge(String(result.rawLogsIncluded), result.rawLogsIncluded ? "red" : "green")]
          ])}
        </div>
      </details>
    `;
  }

  function renderAiConversationMessage(message, context) {
    if (message.role === "user") {
      return `
        <article class="ai-chat-message user" data-ai-message-id="${escapeHtml(message.id)}">
          <div class="ai-message-bubble">${escapeHtml(message.question || message.answer || "")}</div>
          <div class="ai-message-meta">${escapeHtml(aiMessageTime(message.createdAt))}</div>
        </article>
      `;
    }
    if (message.status === "loading") {
      return `
        <article class="ai-chat-message assistant loading" data-ai-message-id="${escapeHtml(message.id)}" data-ai-assistant-loading>
          <div class="ai-answer-card">
            <div class="ai-loading-row"><span class="ai-loading-dot" aria-hidden="true"></span><span>Asking Chief Quant Advisor...</span></div>
            <div class="ai-answer-meta">${escapeHtml(message.routeLabel || "Advisory only | Broker actions blocked")}</div>
          </div>
        </article>
      `;
    }
    const result = message.result || localAiResult(message.question || aiSelectedQuestion, message.answer || "");
    const packet = aiPacketText(result);
    const answer = packet
      ? "Supreme Board packet is ready. Use View packet to inspect it, or Copy packet to copy it. Packet mode is manual and advisory-only."
      : (message.answer || result.answer || "No advisory response returned.");
    const providerError = aiProviderErrorText(result);
    const fallback = aiResultIsFallback(result);
    const error = message.status === "error" || aiResultIsProviderError(result);
    return `
      <article class="ai-chat-message assistant" data-ai-message-id="${escapeHtml(message.id)}">
        <div class="ai-answer-card ${error ? "provider-error" : ""}" data-ai-answer-card>
          <div class="split ai-answer-toolbar">
            <h3>Answer</h3>
            <button class="ai-copy-answer" type="button" data-ai-copy-answer="${escapeHtml(message.id)}">Copy answer</button>
          </div>
          <div class="ai-answer-text">${escapeHtml(answer)}</div>
          <div class="ai-answer-meta">
            ${escapeHtml(aiAnswerMetaText(result, message.updatedAt || message.createdAt))}
          </div>
          ${error ? `<div class="notice error">Provider error: ${escapeHtml(providerError || message.error || "request failed")}</div>` : ""}
          ${fallback && !error ? `<div class="notice ai-fallback-note">Fallback: ${escapeHtml(aiFriendlyStatus(result))}</div>` : ""}
          ${renderAiPacketPanel(result)}
          ${renderAiCollapsedDetails(result, context)}
        </div>
      </article>
    `;
  }

  function renderAiConversationThread(context) {
    const messages = aiConversation.length
      ? aiConversation.map((message) => renderAiConversationMessage(message, context)).join("")
      : `
        <div class="ai-empty-state">
          <h3>Ask a question to start.</h3>
          <p>Advisor answers are advisory-only, evidence-labeled, and blocked from broker actions.</p>
        </div>
      `;
    return `
      <div class="ai-chat-thread" data-ai-chat-scroll-container>
        ${messages}
        <div id="ai-chief-response-end" class="ai-chief-response-end" aria-hidden="true"></div>
      </div>
    `;
  }

  function aiChatIsNearBottom(container) {
    if (!container) return true;
    return container.scrollHeight - container.scrollTop - container.clientHeight < 80;
  }

  function attachAiChatScrollHandler() {
    const container = document.querySelector("[data-ai-chat-scroll-container]");
    if (!container) return;
    container.addEventListener("scroll", () => {
      aiUserPinnedScroll = !aiChatIsNearBottom(container);
    }, { passive: true });
  }

  function scheduleAiOverlayScroll(options) {
    if (!aiOverlayOpen) return;
    const force = options && options.force === true;
    if (aiUserPinnedScroll && !force) return;
    const doScroll = () => {
      const container = document.querySelector("[data-ai-chat-scroll-container]");
      if (!container) return;
      if (force) {
        container.scrollTop = container.scrollHeight;
      } else {
        container.scrollTo({ top: container.scrollHeight, behavior: "smooth" });
      }
    };
    if (force) doScroll();
    window.requestAnimationFrame(doScroll);
    window.setTimeout(doScroll, 80);
    if (force) {
      window.setTimeout(doScroll, 240);
      window.setTimeout(doScroll, 520);
      window.setTimeout(doScroll, 1000);
      window.setTimeout(doScroll, 1800);
    }
  }

  function renderAiChiefOverlay() {
    const host = document.querySelector(".ai-chief-global");
    if (!host) return;
    syncAiDockedState();
    const activeQuestion = aiQuestionText || aiSelectedQuestion || "Review current operator state.";
    const context = buildAiChiefContext(activeQuestion);
    const routing = aiRoutingSettings();
    const lastResult = latestAiAssistantResult();
    const routeLabels = aiActiveRouteLabels(routing, lastResult);
    const primaryPrompts = primaryAiPrompts(activeScreenId || "positions");
    const extraPrompts = moreAiPrompts(activeScreenId || "positions");
    const warning = aiModelWarning();
    const providerError = aiProviderErrorText(lastResult);
    const answerSource = lastResult && lastResult.answerSource ? lastResult.answerSource : "none yet";
    host.innerHTML = `
      <button class="ai-chief-fab ${aiOverlayOpen ? "open" : ""}" type="button" data-ai-chief-open aria-expanded="${aiOverlayOpen ? "true" : "false"}">
        <span>Chief Quant Advisor</span>
        <span class="ai-chief-fab-sub">${escapeHtml(screenTitle(activeScreenId))}</span>
      </button>
      <div class="ai-chief-backdrop ${aiOverlayOpen ? "open" : ""}" data-ai-chief-close></div>
      <section class="ai-chief-drawer ai-chief-dock ${aiOverlayOpen ? "open" : ""} ${aiWideMode ? "wide" : ""}" aria-hidden="${aiOverlayOpen ? "false" : "true"}" aria-label="Global AI Chief advisory drawer">
        <div class="ai-chief-panel">
          <div class="ai-chief-header">
            <div class="ai-chief-heading">
              <div class="ai-chief-title">Chief Quant Advisor</div>
              <div class="ai-chief-subtitle">Ask about readiness, runtime, portfolio, risk, AI route, and Codex packets.</div>
              <div class="ai-route-compact">${escapeHtml(routeLabels.compactLine)}</div>
              ${providerError ? `<div class="ai-provider-error-line">Last provider error: ${escapeHtml(providerError)}</div>` : ""}
            </div>
            <div class="ai-chief-header-actions">
              <button class="ai-chief-close" type="button" data-ai-chief-wide aria-label="${aiWideMode ? "Use normal advisor width" : "Use wide advisor width"}">${aiWideMode ? "Normal" : "Wide"}</button>
              <button class="ai-chief-close" type="button" data-ai-chief-close aria-label="Close AI Chief">Collapse</button>
            </div>
          </div>
          <div class="ai-route-state">
            <div class="ai-route-summary-grid">
              <div><span>Saved/configured</span><strong>${escapeHtml(providerDisplayLabel(routing.activeProvider || "deterministic_local"))}</strong></div>
              <div><span>Selected active provider</span><strong>${escapeHtml(routeLabels.selectedProviderDisplay)}</strong></div>
              <div><span>Default router mode</span><strong>${escapeHtml(routeLabels.routeMode || "LOCAL_GUIDE")}</strong></div>
              <div><span>Active model</span><strong>${escapeHtml(routeLabels.activeModel || "deterministic-local-guide")}</strong></div>
              <div><span>Last answer source</span><strong>${escapeHtml(answerSource)}</strong></div>
              <div><span>Last provider error</span><strong>${escapeHtml(providerError || "none")}</strong></div>
            </div>
            <div class="button-row compact-actions">
              <button class="intent-button paper" type="button" data-ai-use-provider-now="deepseek" ${backendConnected() && !aiOverlayBusy ? "" : "disabled"}>Use DeepSeek now</button>
              <button class="intent-button paper" type="button" data-ai-use-provider-now="openai" ${backendConnected() && !aiOverlayBusy ? "" : "disabled"}>Use OpenAI now</button>
              <button class="intent-button paper" type="button" data-ai-use-supreme-board ${aiOverlayBusy ? "disabled" : ""}>Use Supreme Board packet mode</button>
            </div>
          </div>
          <div class="ai-boundary">
            ${badge("advisory only", "gray")}
            ${badge("broker actions blocked", "red")}
            ${badge("live locked", "red")}
            ${badge("real money blocked", "red")}
            ${badge("secrets hidden", "green")}
          </div>
          ${warning ? `<div class="notice error">${escapeHtml(warning)}</div>` : ""}
          <div class="ai-chief-body">
            ${renderAiConversationThread(context)}
            <div class="ai-composer">
              <label for="ai-chief-question">Ask Chief Quant Advisor</label>
              <textarea id="ai-chief-question" data-ai-chief-question rows="3" placeholder="Ask what is blocking PAPER, whether the bot is ready, or what to do next...">${escapeHtml(aiQuestionText || "")}</textarea>
              ${renderAiAnswerModeButtons("overlay", aiSelectedAnswerMode, aiOverlayBusy)}
              <div class="button-row ai-composer-actions">
                <button class="intent-button paper" type="button" data-ai-chief-clear ${aiOverlayBusy ? "disabled" : ""}>Clear</button>
                ${aiUserPinnedScroll ? `<button class="intent-button paper" type="button" data-ai-jump-latest>Jump to latest</button>` : ""}
              </div>
              ${aiOverlayError ? `<div class="notice error">Error: ${escapeHtml(aiOverlayError)}</div>` : ""}
            </div>
            <div class="ai-prompt-section">
              <div class="ai-question-bank compact" aria-label="AI Chief quick questions">
                ${primaryPrompts.map((prompt) => `
                  <button class="ai-question ${prompt === aiSelectedQuestion ? "active" : ""}" type="button" data-ai-chief-prompt="${escapeHtml(prompt)}">
                    ${escapeHtml(prompt)}
                  </button>
                `).join("")}
              </div>
              ${extraPrompts.length ? `
                <details class="ai-context-details ai-more-prompts">
                  <summary>More prompts</summary>
                  <div class="ai-question-bank compact">
                    ${extraPrompts.map((prompt) => `
                      <button class="ai-question ${prompt === aiSelectedQuestion ? "active" : ""}" type="button" data-ai-chief-prompt="${escapeHtml(prompt)}">
                        ${escapeHtml(prompt)}
                      </button>
                    `).join("")}
                  </div>
                </details>
              ` : ""}
            </div>
            <details class="ai-context-details ai-advisory-queue-details">
              <summary>Governed advisory queue</summary>
              <div class="ai-chief-actions">
                <button class="intent-button paper" type="button" data-ai-chief-analyze ${backendConnected() && !aiOverlayBusy ? "" : "disabled"}>
                  ${aiOverlayBusy ? "Queueing governed review..." : "Queue governed advisory review"}
                </button>
                <span class="badge red">Broker execution unavailable to AI</span>
              </div>
              <div class="notice mono">
                ${backendConnected()
                  ? "Ask uses /operator/ai/ask. Provider errors are shown in the answer area and fallbacks are labeled. Queue review uses governed AI endpoints without trading authority."
                  : "Backend unreachable: advisor can show local deterministic guidance only and will not queue runtime recommendations."}
              </div>
            </details>
          </div>
        </div>
      </section>
    `;
    attachAiChatScrollHandler();
    scheduleAiOverlayScroll();
  }

  function setAiOverlayOpen(open) {
    aiOverlayOpen = open;
    syncAiDockedState();
    renderAiChiefOverlay();
  }

  function toggleAiWideMode() {
    aiWideMode = !aiWideMode;
    aiOverlayOpen = true;
    syncAiDockedState();
    renderAiChiefOverlay();
  }

  function selectAiQuestion(question) {
    aiSelectedQuestion = question;
    aiQuestionText = question;
    aiOverlayError = "";
    aiOverlayOpen = true;
    syncAiDockedState();
    renderAiChiefOverlay();
  }

  function clearAiQuestion() {
    aiQuestionText = "";
    aiOverlayResponse = "";
    aiOverlayLastResult = null;
    aiOverlayError = "";
    aiConversation = [];
    aiUserPinnedScroll = false;
    aiOverlayOpen = true;
    syncAiDockedState();
    renderAiChiefOverlay();
  }

  async function copyCurrentAiPacket() {
    const result = latestAiAssistantResult();
    const packet = aiPacketText(result);
    if (!packet) {
      aiOverlayError = "No packet is available to copy.";
      renderAiChiefOverlay();
      return;
    }
    try {
      if (!navigator.clipboard || typeof navigator.clipboard.writeText !== "function") {
        throw new Error("clipboard_unavailable");
      }
      await navigator.clipboard.writeText(packet);
      data.ai.lastAnalyzeResult = "PACKET_COPIED: Supreme Board packet copied from advisor dock.";
    } catch (error) {
      aiOverlayError = `Copy failed: ${error.message || error.name || "clipboard_unavailable"}`;
    }
    renderAiChiefOverlay();
  }

  async function copyAiAnswer(messageId) {
    const message = aiConversation.find((item) => item.id === messageId);
    const result = message && message.result;
    const answer = (message && (message.answer || (result && result.answer))) || "";
    if (!answer) {
      aiOverlayError = "No answer is available to copy.";
      renderAiChiefOverlay();
      return;
    }
    try {
      if (!navigator.clipboard || typeof navigator.clipboard.writeText !== "function") {
        throw new Error("clipboard_unavailable");
      }
      await navigator.clipboard.writeText(answer);
      data.ai.lastAnalyzeResult = "ANSWER_COPIED: Advisor answer copied.";
    } catch (error) {
      aiOverlayError = `Copy failed: ${error.message || error.name || "clipboard_unavailable"}`;
    }
    renderAiChiefOverlay();
  }

  function formatAiAskResult(result) {
    const knownFacts = Array.isArray(result.known_facts) ? result.known_facts : [];
    const unknowns = Array.isArray(result.unknowns) ? result.unknowns : [];
    const normalized = normalizeAiAskResult(result);
    const friendly = aiFriendlyStatus(normalized);
    return [
      friendly,
      result.answer || result.response || "No advisory response returned.",
      "",
      `provider_id=${result.provider_id || result.provider || "deterministic_local"} / provider_mode=${result.provider_mode || "DETERMINISTIC_FALLBACK"} / provider_state=${result.provider_state || "AI_DISABLED"}`,
      `model=${result.model_name || result.model || "none"} / model_quality=${result.model_quality || "FALLBACK_ONLY"} / reasoning_policy=${result.reasoning_policy || "FALLBACK_ONLY_LIMITED"} / governance_suitable=${String(result.governance_suitable === true || result.model_suitable_for_governance === true)}`,
      `answer_source=${result.answer_source || result.response_source || "LOCAL_DETERMINISTIC"} / cost_mode=${result.cost_mode || "FREE_LOCAL"} / persona_enforced=${String(result.persona_enforced === true)} / roles=${Array.isArray(result.expert_roles_applied) ? result.expert_roles_applied.join(",") : "not returned"}`,
      `mode=${result.mode || "OPERATOR_GUIDE"} / evidence_level=${result.evidence_level || "UNKNOWN"} / source=${result.response_source || "DETERMINISTIC_FALLBACK_NO_MODEL_CALL"}`,
      knownFacts.length ? `known_facts:\n- ${knownFacts.join("\n- ")}` : "known_facts: none returned",
      unknowns.length ? `unknowns:\n- ${unknowns.join("\n- ")}` : "unknowns: none returned",
      `next_step=${result.next_step_label || "review current page"} / page=${result.next_step_page || "unknown"} / control=${result.next_step_control_id || "unknown"}`,
      `needs_codex_packet=${String(result.needs_codex_packet === true)}${result.suggested_codex_packet_summary ? ` / ${result.suggested_codex_packet_summary}` : ""}`,
      `can_execute=${String(result.can_execute === true ? "true" : "false")}`,
      `broker_call_occurred=${String(result.broker_call_occurred === true ? "true" : "false")}`,
      `trading_mutation_occurred=${String(result.trading_mutation_occurred === true ? "true" : "false")}`,
      `live_enabled=${String(result.live_enabled === true ? "true" : "false")}`,
      `real_money_enabled=${String(result.real_money_enabled === true ? "true" : "false")}`
    ].join("\n");
  }

  async function askAiChiefQuestion(questionOverride, answerModeOverride) {
    const input = document.querySelector("[data-ai-chief-question]");
    const question = String(questionOverride || (input && input.value) || aiQuestionText || "").trim();
    const answerMode = normalizeAiAnswerMode(answerModeOverride || aiSelectedAnswerMode || AI_ANSWER_MODES.DETERMINISTIC);
    if (!question) {
      aiOverlayError = "Type a question first.";
      aiOverlayOpen = true;
      renderAiChiefOverlay();
      return;
    }
    aiSelectedAnswerMode = answerMode;
    aiSelectedQuestion = question;
    aiOverlayError = "";
    aiQuestionText = "";
    aiOverlayResponse = "";
    aiUserPinnedScroll = false;
    const routing = aiRoutingSettings();
    const routeLabel = `${aiAnswerModeLabel(answerMode)} | ${aiAnswerModeDescription(answerMode)} | Advisory only | Broker actions blocked`;
    appendAiMessage({ role: "user", status: "complete", question, answer: question });
    const loadingMessage = appendAiMessage({
      role: "assistant",
      status: "loading",
      question,
      routeLabel
    });
    aiOverlayBusy = true;
    aiOverlayOpen = true;
    renderAiChiefOverlay();
    scheduleAiOverlayScroll({ force: true });
    if (!backendConnected()) {
      const localAnswer = buildAiOverlayAdvisory(question);
      const localResult = localAiResult(question, localAnswer, {
        requested_answer_mode: answerMode,
        effective_answer_mode: answerMode,
        answer_mode: answerMode,
        display_source_label: "Backend unreachable local UI fallback",
        fallback_reason: "BACKEND_UNREACHABLE"
      });
      aiOverlayResponse = localAnswer;
      aiOverlayLastResult = localResult;
      replaceAiMessage(loadingMessage.id, {
        status: "complete",
        answer: localResult.answer,
        result: localResult
      });
      aiOverlayBusy = false;
      renderAiChiefOverlay();
      scheduleAiOverlayScroll({ force: true });
      return;
    }
    try {
      const context = buildAiChiefContext(question);
      const route = aiAskRoutingPayloadForMode(routing, answerMode);
      const result = await postIntent("/operator/ai/ask", {
        question,
        page_id: context.page_id,
        page_context: context,
        advisory_only: true,
        answer_mode: answerMode,
        route_mode: route.routeMode,
        provider_id: route.providerId,
        model_name: route.modelName,
        approved_paid_call: route.approvedPaidCall === true
      });
      const normalized = normalizeAiAskResult(result);
      aiOverlayResponse = normalized.answer;
      aiOverlayLastResult = normalized;
      replaceAiMessage(loadingMessage.id, {
        status: "complete",
        answer: normalized.answer,
        result: normalized
      });
    } catch (error) {
      aiOverlayError = error.message || error.name || "ai_ask_failed";
      const fallbackAnswer = buildAiOverlayAdvisory(question);
      const fallbackResult = localAiResult(question, fallbackAnswer, {
        status: "PROVIDER_ERROR",
        provider_mode: "PROVIDER_ERROR",
        provider_state: "PROVIDER_ERROR",
        answer_source: "LOCAL_DETERMINISTIC",
        requested_answer_mode: answerMode,
        effective_answer_mode: answerMode,
        answer_mode: answerMode,
        display_source_label: "Request failed local UI fallback",
        provider_error_category: "UI_AI_ASK_REQUEST_FAILED",
        provider_error_message_safe: aiOverlayError
      });
      aiOverlayResponse = fallbackAnswer;
      aiOverlayLastResult = fallbackResult;
      replaceAiMessage(loadingMessage.id, {
        status: "error",
        answer: fallbackResult.answer,
        result: fallbackResult,
        error: aiOverlayError
      });
    } finally {
      aiOverlayBusy = false;
      aiOverlayOpen = true;
      renderAiChiefOverlay();
      scheduleAiOverlayScroll({ force: true });
    }
  }

  function selectHomeAiQuestion(question) {
    homeAiQuestionText = question;
    homeAiError = "";
    homeAiResponse = "";
    homeAiLastResult = null;
    renderScreens(activeScreenId);
    renderRail();
    renderAiChiefOverlay();
  }

  function clearHomeAiQuestion() {
    homeAiQuestionText = "";
    homeAiResponse = "";
    homeAiLastResult = null;
    homeAiError = "";
    renderScreens(activeScreenId);
    renderRail();
    renderAiChiefOverlay();
  }

  async function askHomeAiQuestion(answerModeOverride) {
    const input = document.querySelector("[data-home-ai-question]");
    const question = String((input && input.value) || homeAiQuestionText || "").trim();
    const answerMode = normalizeAiAnswerMode(answerModeOverride || homeAiAnswerMode || AI_ANSWER_MODES.DETERMINISTIC);
    homeAiQuestionText = question;
    homeAiAnswerMode = answerMode;
    homeAiError = "";
    if (!backendConnected()) {
      homeAiResponse = buildAiOverlayAdvisory(question);
      homeAiLastResult = localAiResult(question, homeAiResponse, {
        requested_answer_mode: answerMode,
        effective_answer_mode: answerMode,
        answer_mode: answerMode,
        display_source_label: "Backend unreachable local UI fallback",
        fallback_reason: "BACKEND_UNREACHABLE"
      });
      renderScreens(activeScreenId);
      renderRail();
      renderAiChiefOverlay();
      return;
    }
    homeAiBusy = true;
    renderScreens(activeScreenId);
    renderRail();
    renderAiChiefOverlay();
    try {
      const context = buildAiChiefContext(question);
      context.page_id = activeScreenId || "positions";
      context.page_title = screenTitle(activeScreenId || "positions");
      const routing = aiRoutingSettings();
      const route = aiAskRoutingPayloadForMode(routing, answerMode);
      const result = await postIntent("/operator/ai/ask", {
        question,
        page_id: context.page_id,
        page_context: context,
        advisory_only: true,
        answer_mode: answerMode,
        route_mode: route.routeMode,
        provider_id: route.providerId,
        model_name: route.modelName,
        approved_paid_call: route.approvedPaidCall === true
      });
      homeAiLastResult = normalizeAiAskResult(result);
      homeAiResponse = homeAiLastResult.answer;
    } catch (error) {
      homeAiError = error.message || error.name || "home_ai_ask_failed";
      homeAiResponse = buildAiOverlayAdvisory(question);
      homeAiLastResult = localAiResult(question, homeAiResponse, {
        status: "PROVIDER_ERROR",
        provider_mode: "PROVIDER_ERROR",
        provider_state: "PROVIDER_ERROR",
        requested_answer_mode: answerMode,
        effective_answer_mode: answerMode,
        answer_mode: answerMode,
        display_source_label: "Request failed local UI fallback",
        provider_error_category: "UI_HOME_AI_ASK_REQUEST_FAILED",
        provider_error_message_safe: homeAiError
      });
    } finally {
      homeAiBusy = false;
      renderScreens(activeScreenId);
      renderRail();
      renderAiChiefOverlay();
    }
  }

  async function runAiOverlayAnalyze() {
    if (!backendConnected() || aiOverlayBusy) {
      aiOverlayResponse = buildAiOverlayAdvisory(aiSelectedQuestion);
      aiOverlayLastResult = localAiResult(aiSelectedQuestion, aiOverlayResponse);
      appendAiCompletedExchange(aiSelectedQuestion, aiOverlayLastResult, { includeUser: true });
      renderAiChiefOverlay();
      return;
    }
    const confirmed = window.confirm("Queue advisory AI Chief analysis with redacted page context? This cannot trade, start PAPER, enable live, or call broker execution.");
    if (!confirmed) return;
    aiOverlayBusy = true;
    renderAiChiefOverlay();
    const selectedScreen = activeScreenId;
    try {
      const context = buildAiChiefContext(aiSelectedQuestion);
      const wantsCodexPacket = aiSelectedQuestion.toLowerCase().includes("draft") && aiSelectedQuestion.toLowerCase().includes("codex");
      const path = wantsCodexPacket
        ? "/operator/ai/draft-codex-packet"
        : "/operator/ai/quant-review";
      const result = await postIntent(path, {
        requested_by: "operator_ui_global_overlay",
        advisory_only: true,
        prompt: aiSelectedQuestion,
        page_id: context.page_id,
        page_context: context
      });
      const recommendation = result.recommendation || {};
      const draftPacket = result.draft_packet || "";
      aiOverlayResponse = [
        "Governed AI Quant Chief endpoint returned through the advisory queue.",
        `Status: ${result.status || "QUEUED"}.`,
        `Recommendation: ${recommendation.recommendation_type || "OBSERVATION"}.`,
        `Summary: ${recommendation.summary || "No summary returned."}`,
        draftPacket ? "Draft packet is ready. Use View packet to inspect it or Copy packet to copy it." : "",
        `can_execute=${String(recommendation.can_execute === true ? "true" : "false")}.`,
        "Approving a PAPER research recommendation does not start PAPER automatically."
      ].filter(Boolean).join("\n");
      const normalized = normalizeAiAskResult({
        status: result.status || "QUEUED",
        provider_id: "operator_ai_queue",
        provider_mode: "DETERMINISTIC_FALLBACK",
        provider_state: "GOVERNANCE_QUEUE",
        model_name: "operator-ai-queue",
        model_quality: "FALLBACK_ONLY",
        answer_source: "LOCAL_DETERMINISTIC",
        cost_mode: "FREE_LOCAL",
        reasoning_policy: "FALLBACK_ONLY_LIMITED",
        persona_enforced: true,
        expert_roles_applied: ["Chief Quant Advisor", "Trading Systems Auditor", "Operator Guide"],
        mode: "TRADING_SYSTEMS_AUDITOR",
        evidence_level: "SYSTEM_STATE",
        answer: aiOverlayResponse,
        packet: draftPacket,
        next_step_label: "Review the queued advisory item before acting.",
        next_step_page: "ai",
        can_execute: false,
        broker_call_occurred: false,
        trading_mutation_occurred: false,
        live_enabled: false,
        real_money_enabled: false
      }, aiOverlayResponse);
      appendAiCompletedExchange(aiSelectedQuestion, normalized, { includeUser: true });
      data = await loadData();
      data.ai.lastAnalyzeResult = `${result.status || "QUEUED"}: ${recommendation.recommendation_type || "OBSERVATION"}`;
      renderTopBar();
      renderScreens(selectedScreen);
      renderRail();
    } catch (error) {
      aiOverlayResponse = `FAILED: ${error.message || error.name || "ai_analyze_error"}\nNo broker or trading mutation was requested by the UI.`;
      aiOverlayLastResult = localAiResult(aiSelectedQuestion, aiOverlayResponse, {
        status: "PROVIDER_ERROR",
        provider_mode: "PROVIDER_ERROR",
        provider_state: "PROVIDER_ERROR",
        provider_error_category: "UI_AI_ANALYZE_REQUEST_FAILED",
        provider_error_message_safe: error.message || error.name || "ai_analyze_error"
      });
      appendAiCompletedExchange(aiSelectedQuestion, aiOverlayLastResult, { includeUser: true, status: "error", error: error.message || error.name || "ai_analyze_error" });
    } finally {
      aiOverlayBusy = false;
      aiOverlayOpen = true;
      renderAiChiefOverlay();
      scheduleAiOverlayScroll({ force: true });
    }
  }

  function currentAiRoutingFormValues() {
    const value = (selector, fallback) => {
      const el = document.querySelector(selector);
      return String((el && el.value) || fallback || "").trim();
    };
    return {
      default_mode: value("[data-ai-route-default-mode]", aiRoutingSettings().defaultMode || "LOCAL_GUIDE"),
      active_provider: value("[data-ai-active-provider]", aiRoutingSettings().activeProvider || "deterministic_local"),
      active_model: value("[data-ai-active-model]", aiRoutingSettings().activeModel || "deterministic-local-guide"),
      light_provider: value("[data-ai-light-provider]", aiRoutingSettings().lightProvider || "openai"),
      light_model: value("[data-ai-light-model]", aiRoutingSettings().lightModel || "gpt-5-mini"),
      high_reasoning_provider: value("[data-ai-high-provider]", aiRoutingSettings().highReasoningProvider || "openai"),
      high_reasoning_model: value("[data-ai-high-model]", aiRoutingSettings().highReasoningModel || "gpt-5.5-pro"),
      local_base_url: value("[data-ai-local-base-url]", aiRoutingSettings().localBaseUrl || "http://127.0.0.1:11434/v1"),
      local_model: value("[data-ai-local-model]", aiRoutingSettings().localModel || "local-model"),
      supreme_board_packet_default: value("[data-ai-supreme-board-default]", aiRoutingSettings().supremeBoardPacketDefault ? "true" : "false") === "true"
    };
  }

  function applyRoutingToLocalState(settings) {
    data.ai.routingSettings = {
      defaultMode: settings.default_mode || settings.defaultMode || "LOCAL_GUIDE",
      activeProvider: settings.active_provider || settings.activeProvider || "deterministic_local",
      activeModel: settings.active_model || settings.activeModel || "deterministic-local-guide",
      lightProvider: settings.light_provider || settings.lightProvider || "openai",
      lightModel: settings.light_model || settings.lightModel || "gpt-5-mini",
      highReasoningProvider: settings.high_reasoning_provider || settings.highReasoningProvider || "openai",
      highReasoningModel: settings.high_reasoning_model || settings.highReasoningModel || "gpt-5.5-pro",
      localProvider: "local_openai_compatible",
      localBaseUrl: settings.local_base_url || settings.localBaseUrl || "http://127.0.0.1:11434/v1",
      localModel: settings.local_model || settings.localModel || "local-model",
      supremeBoardPacketDefault: settings.supreme_board_packet_default === true || settings.supremeBoardPacketDefault === true,
      settingsSource: settings.settings_source || settings.settingsSource || data.ai.routingSettings && data.ai.routingSettings.settingsSource || "IN_MEMORY_UNSAVED",
      status: settings.status || data.ai.routingSettings && data.ai.routingSettings.status || "IN_MEMORY_UNSAVED",
      settingsPathRelative: settings.settings_path_relative || settings.settingsPathRelative || data.ai.routingSettings && data.ai.routingSettings.settingsPathRelative || ".operator_config/ai_router_settings.json"
    };
  }

  async function saveAiRoutingSettings() {
    const settings = currentAiRoutingFormValues();
    applyRoutingToLocalState({ ...settings, settings_source: "IN_MEMORY_UNSAVED", status: "IN_MEMORY_UNSAVED" });
    if (!backendConnected()) {
      data.ai.lastAnalyzeResult = "AI routing settings updated locally only; backend unavailable.";
      renderScreens(activeScreenId);
      return;
    }
    try {
      const result = await postIntent("/operator/ai/router/settings", settings);
      const nextSettings = result.status === "SAVED" ? ((result && result.settings) || settings) : settings;
      applyRoutingToLocalState({ ...nextSettings, status: result.status, settings_source: result.status === "SAVED" ? result.settings_source : "IN_MEMORY_UNSAVED", settings_path_relative: result.settings_path_relative });
      const errorText = Array.isArray(result.validation_errors) && result.validation_errors.length
        ? ` reason=${result.validation_errors.map((item) => item.reason_code || item.detail || "validation_failed").join(",")}`
        : "";
      const saveMessage = `${result.status || "SAVED"}: AI routing settings ${result.status === "SAVED" ? "persisted" : "not saved"}; source=${result.settings_source || "UNKNOWN"}; no paid call occurred.${errorText}`;
      data = await loadData();
      data.ai.lastAnalyzeResult = saveMessage;
      renderTopBar();
      renderScreens(activeScreenId);
      renderRail();
      renderAiChiefOverlay();
    } catch (error) {
      data.ai.lastAnalyzeResult = `FAILED: ${error.message || error.name || "ai_routing_save_failed"}`;
      renderScreens(activeScreenId);
    }
  }

  async function saveExplicitAiRoutingSettings(settings, successMessage) {
    applyRoutingToLocalState({ ...settings, settings_source: "IN_MEMORY_UNSAVED", status: "IN_MEMORY_UNSAVED" });
    if (!backendConnected()) {
      data.ai.lastAnalyzeResult = `${successMessage}; backend unavailable, local UI state only.`;
      renderScreens(activeScreenId);
      renderAiChiefOverlay();
      return;
    }
    try {
      const result = await postIntent("/operator/ai/router/settings", settings);
      const nextSettings = result.status === "SAVED" ? ((result && result.settings) || settings) : settings;
      applyRoutingToLocalState({ ...nextSettings, status: result.status, settings_source: result.status === "SAVED" ? result.settings_source : "IN_MEMORY_UNSAVED", settings_path_relative: result.settings_path_relative });
      const selectedScreen = activeScreenId;
      data = await loadData();
      data.ai.lastAnalyzeResult = `${result.status || "SAVED"}: ${successMessage}; no paid call occurred.`;
      renderTopBar();
      renderScreens(selectedScreen);
      renderRail();
      renderAiChiefOverlay();
    } catch (error) {
      data.ai.lastAnalyzeResult = `FAILED: ${error.message || error.name || "ai_routing_save_failed"}`;
      renderScreens(activeScreenId);
      renderAiChiefOverlay();
    }
  }

  function useAiProviderNow(providerId) {
    const id = String(providerId || "").trim();
    const current = currentAiRoutingFormValues();
    const model = id === "openai"
      ? (current.light_model || providerDefaultModel(id) || "gpt-5-mini")
      : id === "deepseek"
        ? "deepseek-chat"
        : (providerDefaultModel(id) || current.active_model || "");
    const settings = {
      ...current,
      default_mode: "LIGHT_API",
      active_provider: id,
      active_model: model,
      light_provider: id,
      light_model: model,
      supreme_board_packet_default: false
    };
    saveExplicitAiRoutingSettings(settings, `Active provider set to ${providerDisplayLabel(id)} / ${model}`);
  }

  function useSupremeBoardPacketMode() {
    const current = currentAiRoutingFormValues();
    const settings = {
      ...current,
      default_mode: "SUPREME_BOARD_PACKET",
      active_provider: "supreme_board_packet",
      active_model: "chatgpt-pro-manual",
      supreme_board_packet_default: true
    };
    saveExplicitAiRoutingSettings(settings, "Supreme Board packet mode selected");
  }

  async function validateSelectedAiProvider() {
    const settings = currentAiRoutingFormValues();
    const route = aiAskRoutingPayload(settings);
    const providerId = route.providerId || settings.active_provider || "deterministic_local";
    const modelName = route.modelName || settings.active_model || settings.local_model;
    try {
      const result = await postIntent("/operator/ai/providers/validate", {
        provider_id: providerId,
        model_name: modelName,
        validation_mode: "credential_presence",
        approved_paid_call: false
      });
      data.ai.lastAnalyzeResult = `${providerId}: credential presence ${result.credential_presence_status || result.validation_status || result.status}; live AI API test ${result.live_api_test_status || "NOT_TESTED"}; ${result.safe_error_message || "no provider call made"}`;
      renderScreens(activeScreenId);
    } catch (error) {
      data.ai.lastAnalyzeResult = `FAILED: ${error.message || error.name || "ai_provider_validate_failed"}`;
      renderScreens(activeScreenId);
    }
  }

  async function generateSupremeBoardPacket() {
    const question = aiQuestionText || aiSelectedQuestion || "Review the current operator state.";
    if (!backendConnected()) {
      aiOverlayResponse = buildAiOverlayAdvisory("Draft a Codex packet.");
      aiOverlayLastResult = localAiResult("Draft a Codex packet.", aiOverlayResponse);
      appendAiCompletedExchange("Draft a Codex packet.", aiOverlayLastResult, { includeUser: true });
      aiOverlayOpen = true;
      renderAiChiefOverlay();
      return;
    }
    try {
      const context = buildAiChiefContext(question);
      const result = await postIntent("/operator/ai/supreme-board-packet", {
        question,
        page_context: context,
        advisory_only: true
      });
      aiOverlayResponse = result.packet || result.answer || "No packet returned.";
      const normalized = normalizeAiAskResult({
        status: result.status || "PACKET_READY",
        provider_id: "supreme_board_packet",
        provider_mode: "DETERMINISTIC_FALLBACK",
        provider_state: "PACKET_READY",
        model_name: "chatgpt-pro-manual",
        model_quality: "HIGH_REASONING",
        answer_source: "SUPREME_BOARD_PACKET",
        cost_mode: "CHATGPT_PRO_MANUAL",
        reasoning_policy: "HIGHEST_AVAILABLE_REQUIRED",
        model_suitable_for_governance: true,
        persona_enforced: true,
        expert_roles_applied: ["Chief Quant Advisor", "Quant Engineer", "Trading Systems Auditor", "Risk Officer", "Operator Guide"],
        mode: "CODEX_PACKET_ADVISOR",
        evidence_level: "SYSTEM_STATE",
        answer: aiOverlayResponse,
        packet: aiOverlayResponse,
        next_step_label: "Copy the packet into the Supreme Board workflow.",
        next_step_page: "ai",
        needs_codex_packet: true,
        can_execute: false,
        broker_call_occurred: false,
        trading_mutation_occurred: false,
        live_enabled: false,
        real_money_enabled: false
      }, aiOverlayResponse);
      appendAiCompletedExchange(question, normalized, { includeUser: true });
      aiOverlayOpen = true;
      data.ai.lastAnalyzeResult = "PACKET_READY: Supreme Board Packet generated; no API call occurred.";
      renderScreens(activeScreenId);
      renderAiChiefOverlay();
    } catch (error) {
      aiOverlayResponse = `FAILED: ${error.message || error.name || "supreme_board_packet_failed"}`;
      aiOverlayLastResult = localAiResult(question, aiOverlayResponse, {
        status: "PROVIDER_ERROR",
        provider_mode: "PROVIDER_ERROR",
        provider_state: "PROVIDER_ERROR",
        provider_error_category: "UI_SUPREME_BOARD_PACKET_FAILED",
        provider_error_message_safe: error.message || error.name || "supreme_board_packet_failed"
      });
      appendAiCompletedExchange(question, aiOverlayLastResult, { includeUser: true, status: "error", error: error.message || error.name || "supreme_board_packet_failed" });
      aiOverlayOpen = true;
      renderAiChiefOverlay();
    }
  }

  async function approveOneHighReasoningCall() {
    const settings = currentAiRoutingFormValues();
    const confirmed = window.confirm("Approve one paid high-reasoning API call? This uses provider API billing, cannot trade, cannot call broker, cannot enable live, and cannot expose secrets.");
    if (!confirmed) return;
    const question = aiQuestionText || aiSelectedQuestion || "Audit readiness.";
    const context = buildAiChiefContext(question);
    try {
      const result = await postIntent("/operator/ai/ask", {
        question,
        page_context: context,
        answer_mode: AI_ANSWER_MODES.REASONING,
        route_mode: "HIGH_REASONING_API",
        provider_id: settings.high_reasoning_provider,
        model_name: settings.high_reasoning_model,
        approved_paid_call: true,
        advisory_only: true
      });
      const normalized = normalizeAiAskResult(result);
      aiOverlayResponse = normalized.answer;
      aiOverlayLastResult = normalized;
      appendAiCompletedExchange(question, normalized, { includeUser: true });
      aiOverlayOpen = true;
      renderAiChiefOverlay();
      scheduleAiOverlayScroll({ force: true });
    } catch (error) {
      aiOverlayResponse = `FAILED: ${error.message || error.name || "high_reasoning_call_failed"}\nNo broker or trading mutation was requested.`;
      aiOverlayLastResult = localAiResult(question, aiOverlayResponse, {
        status: "PROVIDER_ERROR",
        provider_mode: "PROVIDER_ERROR",
        provider_state: "PROVIDER_ERROR",
        provider_error_category: "UI_HIGH_REASONING_CALL_FAILED",
        provider_error_message_safe: error.message || error.name || "high_reasoning_call_failed"
      });
      appendAiCompletedExchange(question, aiOverlayLastResult, { includeUser: true, status: "error", error: error.message || error.name || "high_reasoning_call_failed" });
      aiOverlayOpen = true;
      renderAiChiefOverlay();
      scheduleAiOverlayScroll({ force: true });
    }
  }

  function renderRail() {
    const critical = data.alerts.filter((alert) => alert.severity === "SAFETY_CRITICAL").length;
    const pendingAI = data.ai.pendingReviewCount || 0;
    const readyIdle = ["IDLE_NO_ACTIVE_PAPER_RUN", "READY_IDLE_NO_ACTIVE_PAPER_RUN", "READY_IDLE_NO_ACTIVE_RUNTIME"].includes(data.status.dominantBlocker);
    const currentStateTitle = readyIdle ? "Current Runtime State" : "Dominant Blocker";
    const currentStateColor = readyIdle ? "green" : "yellow";
    const historicalRefusal = data.supervisor.lastHistoricalRefusal || "none";
    document.querySelector(".rail").innerHTML = `
      <div class="card rail-card"><h3>Current Alerts</h3>
        <div class="stack">
          ${badge(sourceLabel(), dataSourceColor())}
          ${badge("LIVE_LOCKED", "green")}
          ${badge("REAL_MONEY_BLOCKED", "green")}
          ${badge(`${data.alerts.length} watchdog`, data.alerts.length ? "yellow" : "gray")}
          ${badge(`${critical} critical`, critical ? "red" : "gray")}
        </div>
      </div>
      <div class="card rail-card"><h3>${escapeHtml(currentStateTitle)}</h3>
        <div class="stack">
          ${badge(data.status.dominantBlocker, currentStateColor)}
          <div>${escapeHtml(data.supervisor.runtimeAttachmentDetail || data.status.lastDecision)}</div>
        </div>
      </div>
      <div class="card rail-card"><h3>Last Decision</h3>
        <div>${escapeHtml(data.status.lastDecision)}</div>
      </div>
      <div class="card rail-card"><h3>Last Historical Refusal</h3>
        <div class="mono">${historicalRefusal === "none" ? "none" : tokenText(historicalRefusal)}</div>
      </div>
      <div class="card rail-card"><h3>Supervisor</h3>
        <div class="stack">
          ${badge(data.supervisor.state, statusColor(data.supervisor.state))}
          ${badge(data.supervisor.sessionId || "no session", "gray")}
        </div>
      </div>
      <div class="card rail-card"><h3>Needs Approval</h3>
        <div class="stack">
          ${badge("live governance packet", "red")}
          ${badge("server-side authority", "red")}
          ${badge("operator approval", "red")}
          ${badge(`${pendingAI} AI review`, pendingAI ? "yellow" : "gray")}
        </div>
      </div>
    `;
  }

  function renderScreens(selectedId) {
    const main = document.querySelector(".main");
    const selected = selectedId || activeScreenId || "positions";
    const renderers = {
      command: renderCommand,
      action: renderActionCenter,
      runs: renderRuns,
      historical: renderHistorical,
      pnl: renderPnl,
      positions: renderPositions,
      activity: renderActivity,
      decision: renderDecision,
      market: renderMarket,
      risk: renderRisk,
      alerts: renderAlerts,
      ai: renderAI,
      providers: renderProviders,
      research: renderResearch,
      system: renderSystem,
      audit: renderAudit,
      world: renderWorld,
      diagnostics: renderDiagnostics,
      live: renderLive
    };
    const renderer = renderers[selected] || renderPositions;
    main.innerHTML = `<section class="screen active" id="screen-${selected}">${renderer()}</section>`;
    window.PK_OPERATOR_UI_CONTROL_INVENTORY = buildUiControlInventory();
    activeScreenId = selected;
    document.querySelectorAll(".nav-button").forEach((el) => el.classList.toggle("active", el.dataset.screen === selected));
  }

  function backendFetchTimeoutMs(path) {
    if (path === "/operator/paper-control-state") return PAPER_CONTROL_STATE_FETCH_TIMEOUT_MS;
    return HEAVY_BACKEND_ENDPOINTS.has(path) ? HEAVY_BACKEND_FETCH_TIMEOUT_MS : DEFAULT_BACKEND_FETCH_TIMEOUT_MS;
  }

  function normalizeFetchError(path, error, timedOut, timeoutMs) {
    const message = timedOut
      ? `timeout after ${timeoutMs}ms`
      : (error && (error.message || error.name) ? (error.message || error.name) : "fetch_failed");
    const normalized = new Error(message);
    normalized.endpoint = path;
    normalized.name = error && error.name ? error.name : "FetchError";
    normalized.timedOut = timedOut === true;
    normalized.lifecycleAbort = timedOut !== true && error && error.name === "AbortError";
    return normalized;
  }

  async function fetchJson(path, options) {
    const opts = options || {};
    const timeoutMs = backendFetchTimeoutMs(path);
    const controller = new AbortController();
    const externalSignal = opts.signal || null;
    let timedOut = false;
    const abortFromExternalSignal = () => {
      try {
        controller.abort(new Error("request aborted by newer UI load"));
      } catch (_error) {
        controller.abort();
      }
    };
    if (externalSignal && externalSignal.aborted) {
      abortFromExternalSignal();
    } else if (externalSignal) {
      externalSignal.addEventListener("abort", abortFromExternalSignal, { once: true });
    }
    const timeout = window.setTimeout(() => {
      timedOut = true;
      try {
        controller.abort(new Error(`timeout after ${timeoutMs}ms`));
      } catch (_error) {
        controller.abort();
      }
    }, timeoutMs);
    try {
      const response = await fetch(`${operatorApiBase()}${path}`, {
        cache: "no-store",
        signal: controller.signal
      });
      if (!response.ok) {
        const error = new Error(`HTTP ${response.status}`);
        error.endpoint = path;
        throw error;
      }
      return await response.json();
    } catch (error) {
      throw normalizeFetchError(path, error, timedOut, timeoutMs);
    } finally {
      window.clearTimeout(timeout);
      if (externalSignal) {
        externalSignal.removeEventListener("abort", abortFromExternalSignal);
      }
    }
  }

  function createRequestScheduler() {
    const queues = {
      critical: [],
      normal: [],
      optional: []
    };
    const active = {
      critical: 0,
      normal: 0,
      optional: 0
    };
    function laneForPriority(priority) {
      return REQUEST_LANE_BY_PRIORITY[String(priority)] || "optional";
    }
    function pumpLane(lane) {
      const limit = REQUEST_LANE_LIMITS[lane] || 1;
      while (active[lane] < limit && queues[lane].length) {
        const task = queues[lane].shift();
        active[lane] += 1;
        fetchJson(task.path, { signal: task.signal })
          .then((payload) => task.resolve({ key: task.key, path: task.path, payload, optional: task.optional === true }))
          .catch((error) => task.reject({ key: task.key, path: task.path, error, optional: task.optional === true }))
          .finally(() => {
            active[lane] = Math.max(0, active[lane] - 1);
            pumpLane(lane);
          });
      }
    }
    return {
      schedule(task) {
        const priority = Number(task.priority ?? 3);
        const lane = task.lane || laneForPriority(priority);
        return new Promise((resolve, reject) => {
          queues[lane].push({ ...task, lane, resolve, reject });
          queues[lane].sort((a, b) => Number(a.priority ?? 3) - Number(b.priority ?? 3));
          pumpLane(lane);
        });
      }
    };
  }

  function describeFetchFailure(path, error) {
    const reason = error && (error.message || error.name) ? (error.message || error.name) : "fetch_failed";
    return `${path}: ${reason}`;
  }

  function logBackendFetchFailure(path, error) {
    if (!window.console || !window.console.warn) return;
    window.console.warn("[operator-ui] backend endpoint fetch failed", {
      endpoint: path,
      error: error && error.name ? error.name : "Error",
      message: error && error.message ? error.message : "fetch_failed"
    });
  }

  function logBackendFetchAbort(path, error) {
    if (!window.console || !window.console.info) return;
    window.console.info("[operator-ui] backend endpoint fetch aborted without downgrade", {
      endpoint: path,
      error: error && error.name ? error.name : "AbortError",
      message: error && error.message ? error.message : "request aborted"
    });
  }

  function normalizePortfolio(portfolio) {
    const summary = portfolio.summary || {};
    return {
      source: pick(portfolio.source, "OPERATOR_PORTFOLIO_READ_ONLY"),
      dataSource: pick(portfolio.data_source, "UNAVAILABLE"),
      status: pick(portfolio.status, "UNKNOWN"),
      unavailableReason: pick(portfolio.unavailable_reason, null),
      detail: pick(portfolio.detail, null),
      message: pick(portfolio.message, ""),
      empty: portfolio.empty === true,
      dataFreshnessTs: pick(portfolio.data_freshness_ts, null),
      brokerReadAttempted: portfolio.broker_read_attempted === true,
      brokerReadOccurred: portfolio.broker_read_occurred === true,
      brokerMutationOccurred: portfolio.broker_mutation_occurred === true,
      summary: {
        totalEquity: pick(summary.total_equity, null),
        cash: pick(summary.cash, null),
        buyingPower: pick(summary.buying_power, null),
        totalMarketValue: pick(summary.total_market_value, null),
        totalUnrealizedPnl: pick(summary.total_unrealized_pnl, null),
        totalRealizedPnl: pick(summary.total_realized_pnl, null),
        dayPnl: pick(summary.day_pnl, null),
        grossExposure: pick(summary.gross_exposure, null),
        netExposure: pick(summary.net_exposure, null),
        positionCount: pick(summary.position_count, 0),
        openOrderCount: pick(summary.open_order_count, 0),
        largestPosition: pick(summary.largest_position, null),
        highestRiskPosition: pick(summary.highest_risk_position, null),
        staleOrConflictedPositionCount: pick(summary.stale_or_conflicted_position_count, 0),
        brokerLocalReconciliationStatus: pick(summary.broker_local_reconciliation_status, "UNKNOWN"),
        accountStatus: pick(summary.account_status, null),
        accountId: pick(summary.account_id, null),
        currency: pick(summary.currency, null),
        tradingBlocked: summary.trading_blocked === true,
        accountBlocked: summary.account_blocked === true,
        transfersBlocked: summary.transfers_blocked === true,
        patternDayTrader: summary.pattern_day_trader === true
      },
      positions: Array.isArray(portfolio.positions) ? portfolio.positions.map((position) => ({
        symbol: pick(position.symbol, "unknown"),
        assetClass: pick(position.asset_class, "unknown"),
        quantity: pick(position.quantity, null),
        side: pick(position.side, "unknown"),
        averageEntryPrice: pick(position.average_entry_price, null),
        currentMarketPrice: pick(position.current_market_price, null),
        costBasis: pick(position.cost_basis, null),
        marketValue: pick(position.market_value, null),
        unrealizedPnl: pick(position.unrealized_pnl, null),
        unrealizedPnlPercent: pick(position.unrealized_pnl_percent, null),
        realizedPnl: pick(position.realized_pnl, null),
        todayPriceChange: pick(position.today_price_change, null),
        todayPercentChange: pick(position.today_percent_change, null),
        positionAge: pick(position.position_age, "UNKNOWN"),
        openedTime: pick(position.opened_time, null),
        latestFillTime: pick(position.latest_fill_time, null),
        latestFillPrice: pick(position.latest_fill_price, null),
        openOrderCount: pick(position.open_order_count, 0),
        feesStatus: pick(position.fees_status, "UNKNOWN"),
        tcaStatus: pick(position.tca_status, "UNKNOWN"),
        slippage: pick(position.slippage, null),
        source: pick(position.source, "UNAVAILABLE"),
        brokerConfirmed: position.broker_confirmed === true,
        omsReconciliationStatus: pick(position.oms_reconciliation_status, "UNKNOWN"),
        dataFreshnessTs: pick(position.data_freshness_ts, null),
        tradabilityStatus: pick(position.tradability_status, "UNKNOWN"),
        riskStatus: pick(position.risk_status, "UNKNOWN"),
        exposurePercentOfPortfolio: pick(position.intelligence && position.intelligence.exposure_percent_of_portfolio, null)
      })) : [],
      openOrders: Array.isArray(portfolio.open_orders) ? portfolio.open_orders.map((order) => ({
        orderId: pick(order.order_id, null),
        clientOrderId: pick(order.client_order_id, null),
        symbol: pick(order.symbol, "unknown"),
        assetClass: pick(order.asset_class, "unknown"),
        qty: pick(order.qty, null),
        filledQty: pick(order.filled_qty, "0"),
        side: pick(order.side, "unknown"),
        type: pick(order.type, "unknown"),
        timeInForce: pick(order.time_in_force, "unknown"),
        limitPrice: pick(order.limit_price, null),
        stopPrice: pick(order.stop_price, null),
        status: pick(order.status, "UNKNOWN"),
        submittedAt: pick(order.submitted_at, null),
        updatedAt: pick(order.updated_at, null),
        source: pick(order.source, "BROKER_CONFIRMED"),
        canCancel: order.can_cancel === true
      })) : [],
      positionIntelligence: Array.isArray(portfolio.position_intelligence) ? portfolio.position_intelligence.map((item) => ({
        symbol: pick(item.symbol, "unknown"),
        exposurePercentOfPortfolio: pick(item.exposure_percent_of_portfolio, null),
        concentrationWarning: item.concentration_warning === true,
        volatilityRangeWarning: pick(item.volatility_range_warning, "UNKNOWN"),
        feeDragWarning: pick(item.fee_drag_warning, "UNKNOWN"),
        slippageWarning: pick(item.slippage_warning, "UNKNOWN"),
        staleDataWarning: item.stale_data_warning === true,
        spreadLiquidityWarning: pick(item.spread_liquidity_warning, "UNKNOWN"),
        correlationClusterWarning: pick(item.correlation_cluster_warning, "UNKNOWN"),
        movingFloorStatus: pick(item.moving_floor_status, "UNKNOWN"),
        protectiveFloorStatus: pick(item.protective_floor_status, "UNKNOWN"),
        exitLogicStatus: pick(item.exit_logic_status, "UNKNOWN"),
        whyHolding: pick(item.why_holding, ""),
        blockersConflicts: Array.isArray(item.blockers_conflicts) ? item.blockers_conflicts : [],
        riskStatus: pick(item.risk_status, "UNKNOWN"),
        source: pick(item.source, "UNAVAILABLE")
      })) : []
    };
  }

  function normalizeHistoricalRun(run) {
    if (!run || typeof run !== "object") return null;
    return {
      ...run,
      testId: pick(run.test_id, run.testId || "unknown"),
      status: pick(run.status, "UNKNOWN"),
      request: run.request || {},
      result: run.result || {}
    };
  }

  function normalizePaperCredentialSetup(setup) {
    const payload = setup || {};
    const overall = payload.overall_status || {};
    const endpoint = payload.endpoint || {};
    const secretPath = payload.approved_secret_path || {};
    const preflight = payload.preflight_gate || {};
    const safety = payload.safety || {};
    return {
      source: pick(payload.source, ""),
      schemaVersion: pick(payload.schema_version, "paper-credential-setup-v1"),
      overallStatus: {
        code: pick(overall.code, "MISSING"),
        label: pick(overall.label, "PAPER credentials missing"),
        severity: pick(overall.severity, "blocked"),
        detail: pick(overall.detail, "PAPER credentials missing - add Alpaca PAPER credentials through the approved local secret path.")
      },
      requiredCredentials: Array.isArray(payload.required_credentials) ? payload.required_credentials.map((row) => ({
        name: pick(row.name, "unknown"),
        present: row.present === true,
        displayValue: pick(row.display_value, row.present === true ? "present" : "missing"),
        source: pick(row.source, "NOT_CONFIGURED"),
        rawValueExposed: row.raw_value_exposed === true
      })) : [],
      missingFields: Array.isArray(payload.missing_fields) ? payload.missing_fields : [],
      valuesHidden: payload.values_hidden !== false,
      endpoint: {
        display: pick(endpoint.display, "https://paper-api.alpaca.markets"),
        family: pick(endpoint.family, "paper"),
        host: pick(endpoint.host, "paper-api.alpaca.markets"),
        source: pick(endpoint.source, "safe_default"),
        configured: endpoint.configured === true,
        paperEndpointValid: endpoint.paper_endpoint_valid !== false,
        liveEndpointBlocked: endpoint.live_endpoint_blocked !== false,
        blockerCode: pick(endpoint.blocker_code, null)
      },
      approvedSecretPath: {
        label: pick(secretPath.label, "Keys & Providers -> Alpaca PAPER Broker/Data -> Save local credentials"),
        storageType: pick(secretPath.storage_type, "operator_secret_file"),
        relativePath: pick(secretPath.relative_path, ".operator_secrets/provider_credentials.json"),
        credentialPrecedence: pick(secretPath.credential_precedence, "ENV_PRESENT_OVERRIDES_LOCAL_SECRET"),
        gitignored: secretPath.gitignored !== false,
        safeInstruction: pick(secretPath.safe_instruction, "Open Keys & Providers, enter APCA_API_KEY_ID and APCA_API_SECRET_KEY for Alpaca PAPER Broker/Data, then save local credentials. Values stay local and hidden."),
        forbiddenInstruction: pick(secretPath.forbidden_instruction, "Do not paste credentials into chat, do not commit .env files, and do not put raw secrets in tracked files.")
      },
      preflightGate: {
        readOnlyPreflightAuthorized: preflight.read_only_preflight_authorized === true,
        readOnlyPreflightAvailable: preflight.read_only_preflight_available === true,
        accountCheckStatus: pick(preflight.account_check_status, "blocked"),
        openOrdersCheckStatus: pick(preflight.open_orders_check_status, "blocked"),
        positionsCheckStatus: pick(preflight.positions_check_status, "blocked"),
        lastPreflightAt: pick(preflight.last_preflight_at, null),
        lastPreflightResult: pick(preflight.last_preflight_result, null),
        statusLabel: pick(preflight.status_label, "Read-only PAPER preflight not run"),
        detail: pick(preflight.detail, "Read-only preflight requires explicit approval before Alpaca is called."),
        explicitApprovalRequired: preflight.explicit_approval_required !== false,
        futureChecks: Array.isArray(preflight.future_checks) ? preflight.future_checks : [],
        alpacaNetworkCallOccurred: preflight.alpaca_network_call_occurred === true,
        accountRequestOccurred: preflight.account_request_occurred === true,
        openOrdersRequestOccurred: preflight.open_orders_request_occurred === true,
        positionsRequestOccurred: preflight.positions_request_occurred === true,
        brokerMutationOccurred: preflight.broker_mutation_occurred === true,
        orderSubmissionOccurred: preflight.order_submission_occurred === true,
        cancelOccurred: preflight.cancel_occurred === true,
        replaceOccurred: preflight.replace_occurred === true,
        liquidationOccurred: preflight.liquidation_occurred === true
      },
      baselineAdoption: normalizePaperBaseline(payload.baseline_adoption || {}),
      nextSafeAction: pick(payload.next_safe_action, "Open Keys & Providers and save Alpaca PAPER credentials locally; never paste secrets into chat or tracked files."),
      safety: {
        paperStartAllowed: safety.paper_start_allowed === true,
        liveEnabled: safety.live_enabled === true,
        realMoneyEnabled: safety.real_money_enabled === true,
        brokerMutationOccurred: safety.broker_mutation_occurred === true,
        secretsValuesExposed: safety.secrets_values_exposed === true,
        rawSecretValuesIncluded: safety.raw_secret_values_included === true
      }
    };
  }

  function normalizePaperBaseline(payload) {
    const baseline = payload || {};
    const pnl = baseline.pnl_attribution || {};
    return {
      source: pick(baseline.source, "OPERATOR_PAPER_BASELINE"),
      schemaVersion: pick(baseline.schema_version, "paper-baseline-view-v1"),
      status: pick(baseline.status, "NOT_ACCEPTED"),
      decision: pick(baseline.decision, "READ_ONLY_PREFLIGHT_REQUIRED"),
      accepted: baseline.accepted === true,
      policy: pick(baseline.policy, "ADOPT_EXISTING_POSITIONS_PROTECTED"),
      positionCount: pick(baseline.position_count, 0),
      positionSymbols: Array.isArray(baseline.position_symbols) ? baseline.position_symbols : [],
      openOrderCount: pick(baseline.open_order_count, 0),
      endpointFamily: pick(baseline.endpoint_family, "paper"),
      liveLocked: baseline.live_locked !== false,
      realMoneyBlocked: baseline.real_money_blocked !== false,
      startReady: baseline.start_ready === true,
      reason: pick(baseline.reason, ""),
      nextSafeAction: pick(baseline.next_safe_action, ""),
      baselineSnapshotId: pick(baseline.baseline_snapshot_id, null),
      snapshotHash: pick(baseline.snapshot_hash, null),
      acceptedAt: pick(baseline.accepted_at, null),
      protectedSymbols: Array.isArray(baseline.protected_symbols) ? baseline.protected_symbols : [],
      sameSymbolTradingPolicy: pick(baseline.same_symbol_trading_policy, "BLOCK_BASELINE_SYMBOL_TRADES_UNTIL_RUN_LOT_TRACKING"),
      pnlAttribution: {
        baselineAccountEquity: pick(pnl.baseline_account_equity, null),
        baselinePositionsValue: pick(pnl.baseline_positions_value, null),
        runIncrementalEquityPnl: pick(pnl.run_incremental_equity_pnl, null),
        runIncrementalEquityPnlLabel: pick(pnl.run_incremental_equity_pnl_label, ""),
        baselineCarryPnlLabel: pick(pnl.baseline_carry_pnl_label, ""),
        runTradePnlLabel: pick(pnl.run_trade_pnl_label, ""),
        cleanBaselineClaimed: pnl.clean_baseline_claimed === true
      },
      brokerMutationOccurred: baseline.broker_mutation_occurred === true,
      tradingMutationOccurred: baseline.trading_mutation_occurred === true,
      alpacaNetworkCallOccurred: baseline.alpaca_network_call_occurred === true,
      secretsValuesExposed: baseline.secrets_values_exposed === true,
      store: baseline.store || {}
    };
  }

  function normalizeRunPaperOperatorState(state) {
    const payload = state || {};
    const overall = payload.overall_status || {};
    const canRun = payload.can_run_paper || {};
    const endpoint = payload.endpoint || {};
    const credentials = payload.credentials || {};
    const runtime = payload.runtime || {};
    const brokerTruth = payload.broker_truth || {};
    const safetyLocks = payload.safety_locks || {};
    const advanced = payload.advanced || {};
    return {
      source: pick(payload.source, ""),
      schemaVersion: pick(payload.schema_version, "run-paper-command-center-v1"),
      overallStatus: {
        code: pick(overall.code, "UNKNOWN"),
        label: pick(overall.label, "Readiness unknown"),
        severity: pick(overall.severity, "gray"),
        detail: pick(overall.detail, "")
      },
      canRunPaper: {
        allowed: canRun.allowed === true,
        label: pick(canRun.label, "Start blocked"),
        reason: pick(canRun.reason, null),
        reasonCodes: Array.isArray(canRun.reason_codes) ? canRun.reason_codes : [],
        warningCodes: Array.isArray(canRun.warning_codes) ? canRun.warning_codes : [],
        usesExistingGovernedStartIntent: pick(canRun.uses_existing_governed_start_intent, "/operator/intent/paper/start"),
        requiresOperatorConfirmations: canRun.requires_operator_confirmations !== false
      },
      nextSafeAction: pick(payload.next_safe_action, ""),
      endpoint: {
        label: pick(endpoint.label, ""),
        display: pick(endpoint.display, ""),
        family: pick(endpoint.family, "unknown"),
        host: pick(endpoint.host, ""),
        source: pick(endpoint.source, "UNKNOWN"),
        configured: endpoint.configured === true,
        valid: endpoint.valid === true,
        status: pick(endpoint.status, "UNKNOWN"),
        blockerCode: pick(endpoint.blocker_code, null),
        operatorAction: pick(endpoint.operator_action, "")
      },
      credentials: {
        label: pick(credentials.label, ""),
        configured: credentials.configured === true,
        missingFields: Array.isArray(credentials.missing_fields) ? credentials.missing_fields : [],
        source: pick(credentials.source, "NOT_CONFIGURED"),
        precedence: pick(credentials.precedence, "ENV_PRESENT_OVERRIDES_LOCAL_SECRET"),
        rawSecretValuesIncluded: credentials.raw_secret_values_included === true,
        secretsValuesExposed: credentials.secrets_values_exposed === true
      },
      paperCredentialSetup: normalizePaperCredentialSetup(payload.paper_credential_setup || {}),
      paperBaseline: normalizePaperBaseline(payload.paper_baseline || (payload.paper_credential_setup && payload.paper_credential_setup.baseline_adoption) || {}),
      runtime: {
        label: pick(runtime.label, ""),
        state: pick(runtime.state, "UNKNOWN"),
        processState: pick(runtime.process_state, "UNKNOWN"),
        activeSessionId: pick(runtime.active_session_id, null),
        paperStartRefusalReason: pick(runtime.paper_start_refusal_reason, null),
        paperStopAllowed: runtime.paper_stop_allowed === true,
        safeStopStatus: pick(runtime.safe_stop_status, "UNKNOWN")
      },
      brokerTruth: {
        status: pick(brokerTruth.status, "UNKNOWN"),
        label: pick(brokerTruth.label, "Broker truth unknown"),
        detail: pick(brokerTruth.detail, ""),
        brokerConfirmed: brokerTruth.broker_confirmed === true,
        brokerReadOccurred: brokerTruth.broker_read_occurred === true,
        brokerReadAttempted: brokerTruth.broker_read_attempted === true,
        brokerMutationOccurred: brokerTruth.broker_mutation_occurred === true,
        orderSubmissionOccurred: brokerTruth.order_submission_occurred === true,
        cancelOccurred: brokerTruth.cancel_occurred === true,
        liquidationOccurred: brokerTruth.liquidation_occurred === true
      },
      safetyLocks: {
        live: {
          label: pick(safetyLocks.live && safetyLocks.live.label, "Live locked"),
          locked: !safetyLocks.live || safetyLocks.live.locked !== false,
          enabled: safetyLocks.live && safetyLocks.live.enabled === true
        },
        realMoney: {
          label: pick(safetyLocks.real_money && safetyLocks.real_money.label, "Real money blocked"),
          blocked: !safetyLocks.real_money || safetyLocks.real_money.blocked !== false,
          enabled: safetyLocks.real_money && safetyLocks.real_money.enabled === true
        },
        manualTrading: {
          label: pick(safetyLocks.manual_trading && safetyLocks.manual_trading.label, "Manual trading unavailable"),
          available: safetyLocks.manual_trading && safetyLocks.manual_trading.available === true
        },
        forceTrade: {
          label: pick(safetyLocks.force_trade && safetyLocks.force_trade.label, "Force trade unavailable"),
          available: safetyLocks.force_trade && safetyLocks.force_trade.available === true
        },
        brokerMutation: {
          label: pick(safetyLocks.broker_mutation && safetyLocks.broker_mutation.label, "No broker mutation"),
          occurred: safetyLocks.broker_mutation && safetyLocks.broker_mutation.occurred === true
        }
      },
      advanced: {
        finalLaunchReadiness: pick(advanced.final_launch_readiness, "UNKNOWN"),
        reasonCodes: Array.isArray(advanced.reason_codes) ? advanced.reason_codes : [],
        checks: Array.isArray(advanced.checks) ? advanced.checks : [],
        paperEndpointAuthority: advanced.paper_endpoint_authority || {},
        paperEndpointDisplay: pick(advanced.paper_endpoint_display, ""),
        paperEndpointFamily: pick(advanced.paper_endpoint_family, "unknown"),
        paperEndpointHost: pick(advanced.paper_endpoint_host, ""),
        paperEndpointBlockerCode: pick(advanced.paper_endpoint_blocker_code, null),
        alpacaEndpointConfigured: advanced.alpaca_endpoint_configured === true,
        alpacaEndpointSource: pick(advanced.alpaca_endpoint_source, "UNKNOWN"),
        alpacaPaperEndpointValid: advanced.alpaca_paper_endpoint_valid === true,
        alpacaLiveEndpointBlocked: advanced.alpaca_live_endpoint_blocked !== false,
        paperStartAllowed: advanced.paper_start_allowed === true,
        launchReadinessStartAllowed: advanced.launch_readiness_start_allowed === true,
        brokerMutationOccurred: advanced.broker_mutation_occurred === true,
        tradingMutationOccurred: advanced.trading_mutation_occurred === true,
        liveEnabled: advanced.live_enabled === true,
        realMoneyEnabled: advanced.real_money_enabled === true,
        secretsValuesExposed: advanced.secrets_values_exposed === true,
        backendDegradedReasons: Array.isArray(advanced.backend_degraded_reasons) ? advanced.backend_degraded_reasons : [],
        paperStartAuthorityDetail: pick(advanced.paper_start_authority_detail, null)
      }
    };
  }

  function normalizePaperControlState(payload) {
    const control = payload || {};
    const artifactPaths = control.artifact_paths || {};
    const baselineContext = control.baseline_runtime_context || {};
    return {
      source: pick(control.source, ""),
      schemaVersion: pick(control.schema_version, "paper-control-state-v1"),
      backendStatus: pick(control.backend_status, "UNKNOWN"),
      repoHead: pick(control.repo_head, "UNKNOWN"),
      loadedCommit: pick(control.loaded_commit, "UNKNOWN"),
      dataSource: pick(control.data_source, "UNKNOWN"),
      paperOnly: control.paper_only === true,
      liveLocked: control.live_locked !== false,
      realMoneyBlocked: control.real_money_blocked !== false,
      credentialSource: pick(control.credential_source, "NOT_CONFIGURED"),
      credentialStatus: pick(control.credential_status, "UNKNOWN"),
      alpacaPaperConfigured: control.alpaca_paper_configured === true,
      missingCredentialFields: Array.isArray(control.missing_credential_fields) ? control.missing_credential_fields : [],
      endpointFamily: pick(control.endpoint_family, "unknown"),
      endpointHost: pick(control.endpoint_host, ""),
      endpointDisplay: pick(control.endpoint_display, ""),
      endpointSource: pick(control.endpoint_source, "UNKNOWN"),
      endpointStatus: pick(control.endpoint_status, "UNKNOWN"),
      baselineStatus: pick(control.baseline_status, "UNKNOWN"),
      baselineAccepted: control.baseline_accepted === true,
      baselineSnapshotId: pick(control.baseline_snapshot_id, null),
      baselinePolicy: pick(control.baseline_policy, null),
      baselinePositionCount: pick(control.baseline_position_count, 0),
      baselineRuntimeContext: baselineContext,
      protectedSymbols: Array.isArray(control.protected_symbols) ? control.protected_symbols : [],
      portfolioTruthStatus: pick(control.portfolio_truth_status, "UNKNOWN"),
      portfolioDataSource: pick(control.portfolio_data_source, "UNKNOWN"),
      accountStatus: pick(control.account_status, null),
      cash: pick(control.cash, null),
      equity: pick(control.equity, null),
      buyingPower: pick(control.buying_power, null),
      positionsCount: pick(control.positions_count, 0),
      openOrdersCount: pick(control.open_orders_count, 0),
      supervisorState: pick(control.supervisor_state, "UNKNOWN"),
      activeRunId: pick(control.active_run_id, null),
      activePid: pick(control.active_pid, null),
      paperStartAllowed: control.paper_start_allowed === true,
      paperStopAllowed: control.paper_stop_allowed === true,
      dominantBlocker: pick(control.dominant_blocker, "PAPER_START_BLOCKED"),
      reasonCodes: Array.isArray(control.reason_codes) ? control.reason_codes : [],
      maxLeaseSeconds: pick(control.max_lease_seconds, 432000),
      allowedDurations: Array.isArray(control.allowed_durations) ? control.allowed_durations : [],
      watchlist: Array.isArray(control.watchlist) ? control.watchlist : [],
      artifactPaths,
      lastHeartbeat: pick(control.last_heartbeat, null),
      nextSafeAction: pick(control.next_safe_action, ""),
      launchReadiness: control.launch_readiness || {},
      latestRun: control.latest_run || {},
      paperBaseline: control.paper_baseline || {},
      portfolioSummary: control.portfolio_summary || {},
      runtimeAttachmentDetail: pick(control.runtime_attachment_detail, ""),
      secretsValuesExposed: control.secrets_values_exposed === true,
      rawSecretValuesIncluded: control.raw_secret_values_included === true,
      brokerMutationOccurred: control.broker_mutation_occurred === true,
      orderSubmissionOccurred: control.order_submission_occurred === true,
      cancelOccurred: control.cancel_occurred === true,
      replaceOccurred: control.replace_occurred === true,
      liquidationOccurred: control.liquidation_occurred === true,
      closePositionOccurred: control.close_position_occurred === true,
      liveEnabled: control.live_enabled === true,
      realMoneyEnabled: control.real_money_enabled === true
    };
  }

  function paperBaselineFromControlState(control) {
    const existing = normalizePaperBaseline(control.paperBaseline || {});
    if (existing.source && existing.source !== "UNKNOWN") return existing;
    return {
      source: "OPERATOR_PAPER_CONTROL_STATE",
      status: control.baselineStatus || "UNKNOWN",
      accepted: control.baselineAccepted === true,
      baselineSnapshotId: control.baselineSnapshotId,
      snapshotHash: control.baselineRuntimeContext && control.baselineRuntimeContext.snapshot_hash,
      policy: control.baselinePolicy,
      acceptedAt: control.baselineRuntimeContext && control.baselineRuntimeContext.accepted_at,
      acceptedByOperator: "Shan/local operator",
      positionCount: Number(control.baselinePositionCount || 0),
      openOrderCount: Number(control.openOrdersCount || 0),
      protectedSymbols: Array.isArray(control.protectedSymbols) ? control.protectedSymbols : [],
      sameSymbolTradingPolicy: "BLOCK_BASELINE_SYMBOL_TRADES_UNTIL_RUN_LOT_TRACKING",
      pnlAttribution: {
        baselineAccountEquity: control.equity,
        baselinePositionsValue: null,
        runIncrementalEquityPnl: null,
        runIncrementalEquityPnlLabel: "Bot incremental P&L requires run fill attribution.",
        baselineCarryPnlLabel: "Total account P&L includes accepted baseline carry.",
        runTradePnlLabel: "Run trade P&L appears after governed PAPER fills.",
        cleanBaselineClaimed: false
      },
      brokerMutationOccurred: false,
      tradingMutationOccurred: false,
      alpacaNetworkCallOccurred: false,
      secretsValuesExposed: false,
      store: {}
    };
  }

  function buildRunPaperStateFromControlState(control, state) {
    const c = control || {};
    const activeRuntime = Boolean(c.activeRunId)
      || ["RUNNING", "STARTING", "STOP_REQUESTED"].includes(String(c.supervisorState || "").toUpperCase());
    const allowed = c.paperStartAllowed === true;
    const reasonCodes = uniqueCodes(c.reasonCodes && c.reasonCodes.length ? c.reasonCodes : [c.dominantBlocker || "PAPER_START_BLOCKED"]);
    const endpointValid = c.endpointFamily === "paper" && String(c.endpointHost || c.endpointDisplay || "").includes("paper-api.alpaca.markets");
    const credentialConfigured = c.alpacaPaperConfigured === true || c.credentialStatus === "CONFIGURED";
    const baseline = paperBaselineFromControlState(c);
    const label = allowed
      ? "Ready for governed PAPER"
      : (activeRuntime ? "PAPER supervisor running" : (c.dominantBlocker || "Start blocked"));
    const detail = allowed
      ? "Backend paper-control-state says governed PAPER start is allowed with current safety locks."
      : (activeRuntime
        ? "PAPER supervisor process is attached; duplicate start is blocked."
        : `Current backend blocker: ${c.dominantBlocker || reasonCodes[0] || "PAPER_START_BLOCKED"}.`);
    return {
      source: "OPERATOR_PAPER_CONTROL_STATE",
      schemaVersion: "run-paper-command-center-v1",
      overallStatus: {
        code: allowed ? "READY_FOR_GOVERNED_PAPER" : "BLOCKED",
        label,
        severity: allowed ? "ready" : (activeRuntime ? "yellow" : "red"),
        detail
      },
      canRunPaper: {
        allowed,
        label: allowed ? "Start allowed" : "Start blocked",
        reason: allowed ? "" : detail,
        reasonCodes,
        warningCodes: [],
        usesExistingGovernedStartIntent: "/operator/intent/paper/start",
        requiresOperatorConfirmations: true
      },
      nextSafeAction: c.nextSafeAction || (allowed ? "Choose duration and confirmations, then request governed PAPER start." : "Resolve the current backend blocker before pressing Start."),
      endpoint: {
        label: endpointValid ? `Alpaca PAPER endpoint confirmed: ${c.endpointDisplay || c.endpointHost}` : "PAPER endpoint authority unavailable",
        display: c.endpointDisplay || c.endpointHost || "unavailable",
        family: c.endpointFamily || "unknown",
        host: c.endpointHost || "",
        source: c.endpointSource || "UNKNOWN",
        configured: Boolean(c.endpointDisplay || c.endpointHost),
        valid: endpointValid,
        status: c.endpointStatus || (endpointValid ? "PAPER_ENDPOINT_CONFIRMED" : "UNKNOWN"),
        blockerCode: endpointValid ? null : "PAPER_ENDPOINT_NOT_VERIFIED",
        operatorAction: endpointValid ? "No endpoint action required." : "Verify PAPER endpoint authority before starting."
      },
      credentials: {
        label: credentialConfigured ? "Alpaca PAPER credentials configured" : "Alpaca PAPER credentials missing",
        configured: credentialConfigured,
        missingFields: c.missingCredentialFields || [],
        source: c.credentialSource || "NOT_CONFIGURED",
        precedence: "ENV_PRESENT_OVERRIDES_LOCAL_SECRET",
        rawSecretValuesIncluded: false,
        secretsValuesExposed: false
      },
      paperCredentialSetup: buildCredentialSetupFromBackendState(state || data),
      paperBaseline: baseline,
      runtime: {
        label: activeRuntime ? "PAPER supervisor process is attached" : "No active PAPER run",
        state: c.supervisorState || "UNKNOWN",
        processState: c.supervisorState || "UNKNOWN",
        activeSessionId: c.activeRunId || null,
        paperStartRefusalReason: allowed ? null : (c.dominantBlocker || reasonCodes[0]),
        paperStopAllowed: c.paperStopAllowed === true,
        safeStopStatus: c.paperStopAllowed === true ? "GOVERNED_STOP_AVAILABLE" : "NO_ACTIVE_RUN"
      },
      brokerTruth: {
        status: c.portfolioTruthStatus || "UNKNOWN",
        label: c.portfolioTruthStatus === "BROKER_CONFIRMED" ? "Broker-confirmed PAPER portfolio loaded" : "Portfolio truth not broker-confirmed in control state",
        detail: `${c.positionsCount || 0} positions; ${c.openOrdersCount || 0} open orders; account ${c.accountStatus || "unknown"}.`,
        brokerConfirmed: c.portfolioTruthStatus === "BROKER_CONFIRMED",
        brokerReadOccurred: c.portfolioTruthStatus === "BROKER_CONFIRMED",
        brokerReadAttempted: c.portfolioTruthStatus === "BROKER_CONFIRMED",
        brokerMutationOccurred: false,
        orderSubmissionOccurred: false,
        cancelOccurred: false,
        liquidationOccurred: false
      },
      safetyLocks: {
        live: { label: "Live locked", locked: c.liveLocked !== false, enabled: c.liveEnabled === true },
        realMoney: { label: "Real money blocked", blocked: c.realMoneyBlocked !== false, enabled: c.realMoneyEnabled === true },
        manualTrading: { label: "Manual trading unavailable", available: false },
        forceTrade: { label: "Force trade unavailable", available: false },
        brokerMutation: { label: "No broker mutation from control state", occurred: c.brokerMutationOccurred === true }
      },
      advanced: {
        finalLaunchReadiness: allowed ? "READY_FOR_GOVERNED_PAPER" : "BLOCKED",
        reasonCodes,
        checks: [],
        paperEndpointDisplay: c.endpointDisplay || c.endpointHost || "unavailable",
        paperEndpointFamily: c.endpointFamily || "unknown",
        paperEndpointHost: c.endpointHost || "",
        paperEndpointBlockerCode: endpointValid ? null : "PAPER_ENDPOINT_NOT_VERIFIED",
        alpacaEndpointConfigured: Boolean(c.endpointDisplay || c.endpointHost),
        alpacaEndpointSource: c.endpointSource || "UNKNOWN",
        alpacaPaperEndpointValid: endpointValid,
        alpacaLiveEndpointBlocked: c.liveLocked !== false,
        paperStartAllowed: allowed,
        launchReadinessStartAllowed: allowed,
        brokerMutationOccurred: c.brokerMutationOccurred === true,
        tradingMutationOccurred: c.orderSubmissionOccurred === true || c.cancelOccurred === true || c.replaceOccurred === true || c.liquidationOccurred === true || c.closePositionOccurred === true,
        liveEnabled: c.liveEnabled === true,
        realMoneyEnabled: c.realMoneyEnabled === true,
        secretsValuesExposed: c.secretsValuesExposed === true,
        backendDegradedReasons: []
      }
    };
  }

  function applyPaperControlState(state, control) {
    if (!control || control.source !== "OPERATOR_PAPER_CONTROL_STATE") return;
    state.paperBaseline = paperBaselineFromControlState(control);
    state.supervisor.state = control.supervisorState || state.supervisor.state;
    state.supervisor.sessionId = control.activeRunId || "none";
    state.supervisor.pid = control.activePid || "none";
    state.supervisor.processState = control.supervisorState || state.supervisor.processState;
    state.supervisor.paperStartAllowed = control.paperStartAllowed === true;
    state.supervisor.paperStopAllowed = control.paperStopAllowed === true;
    state.supervisor.paperStartRefusalReason = control.paperStartAllowed === true ? null : control.dominantBlocker;
    state.supervisor.paperStopRefusalReason = control.paperStopAllowed === true ? null : "NO_ACTIVE_RUN";
    state.supervisor.maxPaperDurationSeconds = control.maxLeaseSeconds || state.supervisor.maxPaperDurationSeconds || 432000;
    state.supervisor.runnerMaxPaperDurationSeconds = control.maxLeaseSeconds || state.supervisor.runnerMaxPaperDurationSeconds || 432000;
    state.supervisor.watchlist = control.watchlist || state.supervisor.watchlist || [];
    state.supervisor.runtimeAttachmentDetail = control.runtimeAttachmentDetail || state.supervisor.runtimeAttachmentDetail;
    state.supervisor.stdoutPath = control.artifactPaths.stdout_path || state.supervisor.stdoutPath;
    state.supervisor.stderrPath = control.artifactPaths.stderr_path || state.supervisor.stderrPath;
    state.supervisor.wrapperStdoutPath = control.artifactPaths.wrapper_stdout_path || state.supervisor.wrapperStdoutPath;
    state.supervisor.wrapperStderrPath = control.artifactPaths.wrapper_stderr_path || state.supervisor.wrapperStderrPath;
    state.supervisor.childStdoutPath = control.artifactPaths.child_stdout_path || state.supervisor.childStdoutPath;
    state.supervisor.childStderrPath = control.artifactPaths.child_stderr_path || state.supervisor.childStderrPath;
    state.launchReadiness.paperStartAllowed = control.paperStartAllowed === true;
    state.launchReadiness.reasonCodes = control.reasonCodes || [];
    state.launchReadiness.runPaperOperatorState = buildRunPaperStateFromControlState(control, state);
    state.launchReadiness.finalLaunchReadiness = control.paperStartAllowed === true ? "READY_FOR_GOVERNED_PAPER" : "BLOCKED";
    state.launchReadiness.paperEndpointDisplay = control.endpointDisplay || state.launchReadiness.paperEndpointDisplay;
    state.launchReadiness.paperEndpointFamily = control.endpointFamily || state.launchReadiness.paperEndpointFamily;
    state.launchReadiness.paperEndpointHost = control.endpointHost || state.launchReadiness.paperEndpointHost;
    state.launchReadiness.paperEndpointSource = control.endpointSource || state.launchReadiness.paperEndpointSource;
    state.launchReadiness.paperEndpointStatus = control.endpointStatus || state.launchReadiness.paperEndpointStatus;
    state.launchReadiness.alpacaPaperCredentialsConfigured = control.alpacaPaperConfigured === true;
    state.launchReadiness.alpacaPaperEndpointValid = control.endpointFamily === "paper";
    state.status.dominantBlocker = control.dominantBlocker || state.status.dominantBlocker;
    state.status.lastHeartbeat = control.lastHeartbeat || state.status.lastHeartbeat;
  }

  function lifecycleSourcesFromPayload(payload) {
    const status = (payload && payload.status) || {};
    const runtime = (payload && payload.runtime) || {};
    const latestRun = (payload && payload.latestRun) || {};
    const paperControlState = (payload && payload.paperControlState) || {};
    const controlLatestRun = (paperControlState && paperControlState.latest_run) || {};
    const supervisor = status.supervisor || latestRun || {};
    const activeSession = supervisor.active_session || latestRun.active_session || runtime.active_session || {};
    const latestSession = supervisor.latest_session
      || latestRun.latest_session
      || runtime.historical_latest_session
      || runtime.latest_session
      || controlLatestRun.latest_session
      || {};
    return { status, runtime, latestRun, paperControlState, controlLatestRun, supervisor, activeSession, latestSession };
  }

  function applyRuntimeLifecycleTruth(state, payload) {
    const sources = lifecycleSourcesFromPayload(payload || {});
    const activeSession = sources.activeSession || {};
    const latestSession = sources.latestSession || {};
    const activeStatus = rawSessionStatus(activeSession);
    const latestStatus = rawSessionStatus(latestSession);
    const hasActiveSession = Boolean(sessionIdOf(activeSession)) && isActiveSessionStatus(activeStatus);
    const selectedSession = hasActiveSession ? activeSession : (sessionIdOf(latestSession) ? latestSession : {});
    const hasSelectedSession = Boolean(sessionIdOf(selectedSession));
    const selectedStatus = rawSessionStatus(selectedSession);
    const selectedDisplayStatus = hasSelectedSession ? sessionDisplayStatus(selectedSession) : "NO_ACTIVE_PAPER_RUN";
    const selectedActive = hasActiveSession && isActiveSessionStatus(selectedStatus);
    const selectedTerminal = hasSelectedSession && isTerminalSessionStatus(selectedStatus);
    const supervisorState = pick(sources.supervisor.state || sources.paperControlState.supervisor_state || sources.runtime.supervisor_state, state.supervisor.state || "UNKNOWN");
    const backendStartAllowed = sources.supervisor.paper_start_allowed === true
      || sources.runtime.paper_start_allowed === true
      || sources.paperControlState.paper_start_allowed === true;
    const startAllowed = selectedActive ? false : backendStartAllowed;
    const stopAllowed = selectedActive && (sources.supervisor.paper_stop_allowed === true || sources.runtime.paper_stop_allowed === true || sources.paperControlState.paper_stop_allowed === true);
    state.supervisor.state = supervisorState;
    state.supervisor.sessionId = hasSelectedSession ? pick(selectedSession.session_id || selectedSession.run_id, "none") : "none";
    state.supervisor.pid = hasSelectedSession ? pick(selectedSession.pid, selectedActive ? "unknown" : "not active") : "none";
    state.supervisor.processState = selectedDisplayStatus;
    state.supervisor.rawProcessState = hasSelectedSession ? selectedStatus : "NO_ACTIVE_PAPER_RUN";
    state.supervisor.lifecycleStatus = selectedDisplayStatus;
    state.supervisor.startedAt = hasSelectedSession ? pick(selectedSession.started_at || selectedSession.requested_at, "not available") : "not available";
    state.supervisor.endedAt = hasSelectedSession ? pick(selectedSession.ended_at, "not ended") : "not available";
    state.supervisor.exitCode = hasSelectedSession ? pick(selectedSession.exit_code, selectedTerminal ? "unknown" : "not exited") : "not available";
    state.supervisor.durationSeconds = hasSelectedSession ? pick(selectedSession.duration_seconds || sources.runtime.duration_seconds, null) : null;
    state.supervisor.profile = hasSelectedSession ? pick(selectedSession.profile || selectedSession.runtime_profile || state.status.activeProfile, "PAPER_IDLE") : "PAPER_IDLE";
    state.supervisor.watchlist = hasSelectedSession ? pick(selectedSession.watchlist || state.status.universe, []) : [];
    state.supervisor.stdoutPath = hasSelectedSession ? pick(selectedSession.stdout_path || sources.runtime.stdout_path, "not available") : "not available";
    state.supervisor.stderrPath = hasSelectedSession ? pick(selectedSession.stderr_path || sources.runtime.stderr_path, "not available") : "not available";
    state.supervisor.wrapperStdoutPath = hasSelectedSession ? pick(selectedSession.wrapper_stdout_path || sources.runtime.wrapper_stdout_path, state.supervisor.stdoutPath) : "not available";
    state.supervisor.wrapperStderrPath = hasSelectedSession ? pick(selectedSession.wrapper_stderr_path || sources.runtime.wrapper_stderr_path, state.supervisor.stderrPath) : "not available";
    state.supervisor.childStdoutPath = hasSelectedSession ? pick(selectedSession.child_stdout_path || sources.runtime.child_stdout_path, "not available") : "not available";
    state.supervisor.childStderrPath = hasSelectedSession ? pick(selectedSession.child_stderr_path || sources.runtime.child_stderr_path, "not available") : "not available";
    state.supervisor.paperStartAllowed = startAllowed === true;
    state.supervisor.paperStopAllowed = stopAllowed === true;
    state.supervisor.paperStartRefusalReason = startAllowed === true ? null : pick(sources.supervisor.paper_start_refusal_reason || sources.runtime.paper_start_refusal_reason || sources.paperControlState.dominant_blocker, null);
    state.supervisor.paperStopRefusalReason = stopAllowed === true ? null : "NO_ACTIVE_RUN";
    state.supervisor.runtimeAttachmentDetail = hasSelectedSession
      ? sessionRuntimeDetail(selectedSession, selectedActive)
      : (startAllowed === true ? "Ready. No PAPER run currently attached." : "No active PAPER run currently attached.");
    state.supervisor.latestSessionTerminal = selectedTerminal;

    if (hasSelectedSession) {
      state.status.botStatus = selectedDisplayStatus;
      state.status.uptime = state.supervisor.durationSeconds === null || state.supervisor.durationSeconds === undefined
        ? "duration unavailable"
        : `${state.supervisor.durationSeconds}s`;
      state.status.lastDecision = selectedTerminal
        ? state.supervisor.runtimeAttachmentDetail
        : "PAPER supervisor process is attached.";
    } else {
      state.status.botStatus = "NO_ACTIVE_PAPER_RUN";
      state.status.uptime = "no active runtime";
      state.status.lastDecision = startAllowed === true ? "Ready. No PAPER run currently attached." : "No active PAPER run";
    }
    if (selectedActive) {
      state.status.dominantBlocker = "SUPERVISOR_PROCESS_RUNNING_OR_RECENT";
    } else if (selectedTerminal) {
      state.status.dominantBlocker = startAllowed === true ? "READY_FOR_GOVERNED_PAPER" : "IDLE_NO_ACTIVE_PAPER_RUN";
    }

    if (hasSelectedSession) {
      const existingRuns = Array.isArray(state.runArchive.runs) ? state.runArchive.runs : [];
      const runId = sessionIdOf(selectedSession);
      if (runId && !existingRuns.some((run) => run.runId === runId)) {
        state.runArchive.runs = [
          {
            runId,
            status: selectedDisplayStatus,
            finalVerdict: selectedTerminal ? sessionTerminalVerdict(selectedSession) : "RUNNING",
            profile: state.supervisor.profile,
            durationSeconds: state.supervisor.durationSeconds || selectedSession.duration_seconds || "unknown",
            ordersSubmitted: 0,
            ordersAcknowledged: 0,
            ordersCanceled: 0,
            fillsObserved: 0,
            tcaStatus: "NOT_HYDRATED",
            reasonCodes: selectedTerminal ? [selectedDisplayStatus] : ["RUNNING"],
            reportPath: selectedSession.report_path || ""
          },
          ...existingRuns
        ];
        state.runArchive.runCount = Math.max(Number(state.runArchive.runCount || 0), state.runArchive.runs.length);
        state.runArchive.latestVerdict = state.runArchive.runs[0].finalVerdict;
      }
    }
  }

  function normalizeBackendData(payload) {
    const next = buildProductionUnavailableState("backend connected; loading operator truth");
    const status = payload.status || {};
    const runtime = payload.runtime || {};
    const profile = payload.profile || {};
    const universe = payload.universe || {};
    const readiness = payload.readiness || {};
    const operatorReadiness = payload.operatorReadiness || {};
    const health = payload.health || {};
    const storage = payload.storage || {};
    const diagnostics = payload.diagnostics || {};
    const orders = payload.orders || {};
    const fills = payload.fills || {};
    const tca = payload.tca || {};
    const latestRun = payload.latestRun || {};
    const world = payload.world || {};
    const worldRuntime = payload.worldRuntime || {};
    const runs = payload.runs || {};
    const explain = payload.explain || {};
    const actionCenter = payload.actionCenter || {};
    const pnlDashboard = payload.pnlDashboard || {};
    const tcaDashboard = payload.tcaDashboard || {};
    const alerts = payload.alerts || {};
    const systemMap = payload.systemMap || {};
    const aiStatus = payload.aiStatus || {};
    const aiRouterSettings = payload.aiRouterSettings || {};
    const aiRecommendations = payload.aiRecommendations || {};
    const providers = payload.providers || {};
    const providerReadiness = payload.providerReadiness || {};
    const credentialsProviders = payload.credentialsProviders || {};
    const portfolio = payload.portfolio || {};
    const paperBaseline = payload.paperBaseline || {};
    const paperControlState = payload.paperControlState || {};
    const launchReadiness = payload.launchReadiness || {};
    const research = payload.research || {};
    const evidenceGraph = payload.evidenceGraph || {};
    const historicalTests = payload.historicalTests || {};
    const endpointFailures = payload.endpointFailures || {};
    const supervisor = status.supervisor || latestRun || {};
    const activeSession = supervisor.active_session || {};
    const latestSession = supervisor.latest_session || latestRun.latest_session || runtime.historical_latest_session || runtime.latest_session || {};
    const hasActiveSession = Boolean(activeSession && activeSession.session_id);
    const latestRefused = latestSession.status === "REFUSED";
    const latestRefusalReason = pick(latestSession.refusal_reason || runtime.historical_refusal_reason, null);
    const latestHistoricalRefusal = latestRefused
      ? `paper_start: ${latestRefusalReason || "REFUSED"}${latestSession.session_id ? ` (${latestSession.session_id})` : ""}`
      : null;
    const supervisorStartAllowed = supervisor.paper_start_allowed === true || runtime.paper_start_allowed === true;
    const readyIdleNoRuntime = !hasActiveSession
      && supervisorStartAllowed
      && (
        status.dominant_blocker === "READY_IDLE_NO_ACTIVE_PAPER_RUN"
        || status.dominant_blocker === "IDLE_NO_ACTIVE_PAPER_RUN"
        || status.dominant_blocker === "READY_IDLE_NO_ACTIVE_RUNTIME"
        || runtime.runtime_attachment_state === "READY_IDLE_NO_ACTIVE_PAPER_RUN"
        || runtime.runtime_attachment_state === "IDLE_NO_ACTIVE_PAPER_RUN"
        || runtime.runtime_attachment_state === "NO_ACTIVE_RUNTIME_ATTACHED"
        || launchReadiness.final_launch_readiness === "READY_FOR_GOVERNED_PAPER"
        || launchReadiness.final_launch_readiness === "READY_FOR_BOUNDED_PAPER"
      );

    next.meta.dataSource = "OPERATOR_BACKEND";
    next.meta.buildMode = "operator_backend_supervisor_ready";
    next.meta.runtimeCommit = pick(
      status.git_commit_short || health.loaded_commit || health.git_commit_short || runtime.runtime_commit,
      diagnostics.git_commit || "unknown"
    );
    next.meta.uiBuildCommit = pick(payload.uiBuildCommit, uiBuildCommit());
    next.meta.lastUpdated = pick(status.updated_at, new Date().toISOString());

    const backendBotStatus = pick(status.bot_status, "NO_ACTIVE_RUNTIME_ATTACHED");
    next.status.botStatus = backendBotStatus === "NO_ACTIVE_RUNTIME_ATTACHED" ? "NO_ACTIVE_PAPER_RUN" : backendBotStatus;
    next.status.runtimeMode = pick(status.runtime_mode, "PAPER");
    next.status.capabilityState = pick(status.capability_state || status.mode_state, "PAPER_ENABLED");
    next.status.activeProfile = pick(status.active_profile || profile.active_threshold_profile, "PAPER_IDLE");
    next.status.broker = pick(status.broker, "alpaca_paper");
    next.status.endpoint = pick(status.endpoint, "https://paper-api.alpaca.markets");
    next.status.marketData = pick(status.market_data, "IDLE_NO_ACTIVE_MARKET_DATA_RUNTIME");
    next.status.universe = Array.isArray(status.universe) && status.universe.length ? status.universe : pick(universe.symbols, []);
    next.status.assetClasses = Array.isArray(status.asset_classes) && status.asset_classes.length ? status.asset_classes : pick(universe.asset_classes, []);
    next.status.uptime = hasActiveSession && runtime.duration_seconds !== null && runtime.duration_seconds !== undefined
      ? `${runtime.duration_seconds}s`
      : "no active runtime";
    next.status.lastHeartbeat = pick(status.last_heartbeat_ts, "unknown");
    next.status.liveBlocked = status.live_blocked !== false;
    next.status.realMoneyBlocked = status.real_money_blocked !== false;
    next.status.brokerPostCount = pick(status.broker_post_count, 0);
    next.status.brokerDeleteCount = pick(status.broker_delete_count, 0);
    next.status.mutationAuthorizedCount = pick(status.mutation_authorized_count, 0);
    next.status.safetyVerdict = pick(status.safety_verdict, "READ_ONLY_BACKEND_IDLE");
    next.status.dominantBlocker = readyIdleNoRuntime
      ? "IDLE_NO_ACTIVE_PAPER_RUN"
      : pick(status.dominant_blocker, "IDLE_NO_ACTIVE_PAPER_RUN");
    next.status.lastDecision = hasActiveSession
      ? "Decision detail unavailable from backend summary"
      : (readyIdleNoRuntime ? "Ready. No PAPER run currently attached." : (latestHistoricalRefusal ? `No active PAPER run. Last historical refusal ${latestHistoricalRefusal}` : "No active PAPER run"));
    next.supervisor.state = pick(supervisor.state, "UNKNOWN");
    next.supervisor.sessionId = hasActiveSession ? pick(activeSession.session_id || supervisor.active_session_id, "none") : "none";
    next.supervisor.pid = hasActiveSession ? pick(activeSession.pid || runtime.pid, "none") : "none";
    next.supervisor.processState = hasActiveSession ? pick(activeSession.status || runtime.process_state, "UNKNOWN") : "NO_ACTIVE_PAPER_RUN";
    next.supervisor.durationSeconds = hasActiveSession ? pick(activeSession.duration_seconds || runtime.duration_seconds, null) : null;
    next.supervisor.profile = hasActiveSession ? pick(activeSession.profile || status.active_profile, "PAPER_IDLE") : "PAPER_IDLE";
    next.supervisor.watchlist = hasActiveSession ? pick(activeSession.watchlist || status.universe, []) : [];
    next.supervisor.stdoutPath = hasActiveSession ? pick(activeSession.stdout_path || runtime.stdout_path, "not available") : "not available";
    next.supervisor.stderrPath = hasActiveSession ? pick(activeSession.stderr_path || runtime.stderr_path, "not available") : "not available";
    next.supervisor.wrapperStdoutPath = hasActiveSession ? pick(activeSession.wrapper_stdout_path || runtime.wrapper_stdout_path, next.supervisor.stdoutPath) : "not available";
    next.supervisor.wrapperStderrPath = hasActiveSession ? pick(activeSession.wrapper_stderr_path || runtime.wrapper_stderr_path, next.supervisor.stderrPath) : "not available";
    next.supervisor.childStdoutPath = hasActiveSession ? pick(activeSession.child_stdout_path || runtime.child_stdout_path, "not available") : "not available";
    next.supervisor.childStderrPath = hasActiveSession ? pick(activeSession.child_stderr_path || runtime.child_stderr_path, "not available") : "not available";
    next.supervisor.paperStartAllowed = supervisorStartAllowed;
    next.supervisor.paperStopAllowed = supervisor.paper_stop_allowed === true || runtime.paper_stop_allowed === true;
    next.supervisor.paperStartRefusalReason = pick(supervisor.paper_start_refusal_reason || runtime.paper_start_refusal_reason, null);
    next.supervisor.paperStopRefusalReason = pick(supervisor.paper_stop_refusal_reason || runtime.paper_stop_refusal_reason, null);
    next.supervisor.minPaperDurationSeconds = pick(supervisor.min_paper_duration_seconds || runtime.min_paper_duration_seconds, 60);
    next.supervisor.maxPaperDurationSeconds = pick(supervisor.max_paper_duration_seconds || runtime.max_paper_duration_seconds, 432000);
    next.supervisor.runnerMaxPaperDurationSeconds = pick(supervisor.runner_max_paper_duration_seconds || runtime.runner_max_paper_duration_seconds, 432000);
    next.supervisor.durationAuthority = pick(supervisor.duration_authority || runtime.duration_authority, "scripts/run_bounded_paper.ps1");
    next.supervisor.runtimeAttachmentDetail = pick(status.runtime_attachment_detail || runtime.runtime_attachment_detail, readyIdleNoRuntime ? "Ready. No PAPER run currently attached." : "No active PAPER run currently attached.");
    next.supervisor.lastHistoricalRefusal = latestHistoricalRefusal;
    next.supervisor.lastRefusedIntent = latestHistoricalRefusal;

    next.liveReadiness.state = pick(readiness.live_status, "LIVE_LOCKED");
    next.liveReadiness.refusal = pick(readiness.refusal_reason, "LIVE_NOT_APPROVED");
    next.liveReadiness.passed = pick(readiness.passed_prerequisites, []);
    next.liveReadiness.missing = pick(readiness.missing_prerequisites || operatorReadiness.missing_prerequisites, next.liveReadiness.missing);

    next.diagnostics.gitCommit = pick(diagnostics.git_commit, "UNKNOWN_NOT_INSPECTED");
    next.diagnostics.dirtyWorktree = pick(diagnostics.dirty_worktree, "UNKNOWN_NOT_INSPECTED");
    next.diagnostics.pythonVersion = pick(diagnostics.python_version, "UNKNOWN_NOT_INSPECTED");
    next.diagnostics.credentials = pick(diagnostics.credentials_present, "NOT_INSPECTED_NO_SECRET_ACCESS");
    next.diagnostics.logs = pick(diagnostics.logs, "NOT_READ_BY_OPERATOR_BACKEND_V1");
    next.diagnostics.db = pick(diagnostics.db, "NOT_READ_BY_OPERATOR_BACKEND_V1");
    next.diagnostics.runtimeProfile = pick(health.runtime_profile || diagnostics.runtime_profile || storage.runtime_profile, "UNKNOWN");
    next.diagnostics.hostedMode = health.hosted_mode === true || diagnostics.hosted_mode === true || storage.hosted_mode === true;
    next.diagnostics.healthStatus = pick(health.api_status, "UNKNOWN");
    next.diagnostics.sessionStoreStatus = pick(storage.session_store && storage.session_store.status, "UNKNOWN");
    next.diagnostics.worldCacheStatus = pick(storage.world_awareness_cache && storage.world_awareness_cache.status, "UNKNOWN");
    next.diagnostics.operatorStateDir = pick(storage.operator_state_dir && storage.operator_state_dir.path, "not configured");
    next.diagnostics.worldAwarenessCachePath = pick(storage.world_awareness_cache && storage.world_awareness_cache.path, "not configured");
    next.diagnostics.latestChildStdout = next.supervisor.childStdoutPath;
    next.diagnostics.latestChildStderr = next.supervisor.childStderrPath;
    if (Array.isArray(runs.runs)) {
      next.runArchive.runCount = pick(runs.run_count, runs.runs.length);
      next.runArchive.runs = runs.runs.map((run) => ({
        runId: pick(run.run_id, "unknown"),
        status: pick(run.status, "UNKNOWN"),
        finalVerdict: pick(run.final_verdict, "UNKNOWN"),
        profile: pick(run.profile, "unknown"),
        durationSeconds: pick(run.duration_seconds, "unknown"),
        ordersSubmitted: pick(run.orders && run.orders.submitted, 0),
        ordersAcknowledged: pick(run.orders && run.orders.acknowledged, 0),
        ordersCanceled: pick(run.orders && run.orders.canceled, 0),
        orderPostAttempted: pick(run.runtime_new_activity && run.runtime_new_activity.order_post_attempted, pick(run.orders && run.orders.submitted, 0)),
        orderPostAcknowledged: pick(run.runtime_new_activity && run.runtime_new_activity.order_post_acknowledged, pick(run.orders && run.orders.acknowledged, 0)),
        cancelAttempted: pick(run.runtime_new_activity && run.runtime_new_activity.cancel_attempted, pick(run.orders && run.orders.canceled, 0)),
        cancelAcknowledged: pick(run.runtime_new_activity && run.runtime_new_activity.cancel_acknowledged, pick(run.orders && run.orders.canceled, 0)),
        runtimeFills: pick(run.runtime_new_activity && run.runtime_new_activity.fill_hydration_count, pick(run.fills && run.fills.observed, 0)),
        brokerFilledOrders: pick(run.historical_broker_local_activity && run.historical_broker_local_activity.broker_filled_orders, 0),
        localFills: pick(run.historical_broker_local_activity && run.historical_broker_local_activity.local_fills, 0),
        baselinePositionsCount: pick(run.baseline_positions && run.baseline_positions.positions_count, "unknown"),
        postCount: pick(run.broker_method_counts && run.broker_method_counts.POST, 0),
        deleteCount: pick(run.broker_method_counts && run.broker_method_counts.DELETE, 0),
        openOrdersAtShutdown: pick(run.shutdown_open_orders && run.shutdown_open_orders.open_orders_count, "unknown"),
        fillsObserved: pick(run.fills && run.fills.observed, 0),
        tcaStatus: pick(run.tca && run.tca.status, "UNKNOWN"),
        feeTcaStatus: pick(run.fee_tca && run.fee_tca.status, pick(run.tca && run.tca.fee_tca_status && run.tca.fee_tca_status.status, "UNKNOWN")),
        readiness72h: pick(run.readiness_72h && run.readiness_72h.recommendation, "UNKNOWN"),
        reasonCodes: Array.isArray(run.reason_codes) ? run.reason_codes : [],
        reportPath: pick(run.report_path, "")
      }));
      next.runArchive.latestVerdict = next.runArchive.runs.length ? next.runArchive.runs[0].finalVerdict : "UNKNOWN";
      next.runArchive.reportStatus = "on demand";
    } else {
      next.runArchive.runCount = 0;
      next.runArchive.runs = [];
      next.runArchive.latestVerdict = "UNKNOWN";
      next.runArchive.reportStatus = endpointFailures.runs
        ? `degraded: ${endpointFailures.runs}`
        : "endpoint not loaded";
    }
    next.explanation = {
      headline: pick(explain.headline, next.explanation.headline),
      frameId: pick(explain.frame_id, null),
      output: pick(explain.output, "UNKNOWN"),
      netEdge: pick(explain.netedge_result, "UNKNOWN"),
      confidence: pick(explain.confidence, "LOW"),
      nextBestAction: pick(explain.next_best_action, next.explanation.nextBestAction),
      blockers: Array.isArray(explain.blockers)
        ? explain.blockers.map((item) => typeof item === "string" ? item : `${item.source || "blocker"}:${item.reason || "UNKNOWN"}`)
        : next.explanation.blockers,
      missingTruth: Array.isArray(explain.missing_truth) ? explain.missing_truth : next.explanation.missingTruth
    };
    if (Array.isArray(actionCenter.items)) {
      next.actionCenter.items = actionCenter.items.map((item) => ({
        type: pick(item.type, "INFO"),
        title: pick(item.title, "operator item"),
        detail: pick(item.detail, ""),
        source: pick(item.source, "unknown"),
        canExecute: item.can_execute === true
      }));
      next.actionCenter.counts = {
        INFO: pick(actionCenter.counts && actionCenter.counts.INFO, 0),
        WARNING: pick(actionCenter.counts && actionCenter.counts.WARNING, 0),
        BLOCKER: pick(actionCenter.counts && actionCenter.counts.BLOCKER, 0),
        NEEDS_APPROVAL: pick(actionCenter.counts && actionCenter.counts.NEEDS_APPROVAL, 0),
        SAFETY_CRITICAL: pick(actionCenter.counts && actionCenter.counts.SAFETY_CRITICAL, 0)
      };
    } else {
      const degraded = endpointFailures.actionCenter;
      next.actionCenter.items = degraded ? [{
        type: "WARNING",
        title: "Action Center endpoint degraded",
        detail: degraded,
        source: "operator-ui",
        canExecute: false
      }] : [];
      next.actionCenter.counts = {
        INFO: 0,
        WARNING: degraded ? 1 : 0,
        BLOCKER: 0,
        NEEDS_APPROVAL: 0,
        SAFETY_CRITICAL: 0
      };
    }
    if (pnlDashboard.source) {
      next.pnl.realizedPnl = {
        value: pnlDashboard.realized_pnl && pnlDashboard.realized_pnl.value,
        source: pick(pnlDashboard.realized_pnl && pnlDashboard.realized_pnl.truth_label, "unknown")
      };
      next.pnl.unrealizedPnl = {
        value: pnlDashboard.unrealized_pnl && pnlDashboard.unrealized_pnl.value,
        source: pick(pnlDashboard.unrealized_pnl && pnlDashboard.unrealized_pnl.truth_label, "unknown")
      };
      next.pnl.netPnl = {
        value: pnlDashboard.net_pnl && pnlDashboard.net_pnl.value,
        source: pick(pnlDashboard.net_pnl && pnlDashboard.net_pnl.truth_label, "unknown")
      };
      next.pnl.fees = {
        value: null,
        source: pick(pnlDashboard.fee_hydration && pnlDashboard.fee_hydration.source, "UNKNOWN")
      };
      next.pnl.trades = pick(pnlDashboard.fill_count, 0);
      next.pnl.winLoss = "unknown without broker-confirmed realized trade outcomes";
      next.pnl.maxDrawdown = "unknown unless broker/account truth provides it";
    }
    if (tcaDashboard.source) {
      next.tcaDashboard = {
        status: pick(tcaDashboard.status, "UNKNOWN"),
        recordsTotal: pick(tcaDashboard.records && tcaDashboard.records.total, 0),
        recordsComplete: pick(tcaDashboard.records && tcaDashboard.records.complete, 0),
        recordsUnknown: pick(tcaDashboard.records && tcaDashboard.records.unknown, 0),
        feePending: pick(tcaDashboard.records && tcaDashboard.records.fee_pending, 0)
      };
    }
    if (Array.isArray(alerts.alerts)) {
      next.alerts = alerts.alerts.map((alert) => ({
        severity: pick(alert.severity, "INFO"),
        title: pick(alert.title, "alert"),
        detail: pick(alert.detail, ""),
        source: pick(alert.source, "watchdog"),
        acknowledged: alert.acknowledged === true,
        canExecute: alert.can_execute === true
      }));
    } else {
      next.alerts = endpointFailures.alerts ? [{
        severity: "WARNING",
        title: "Watchdog alerts endpoint degraded",
        detail: endpointFailures.alerts,
        source: "operator-ui",
        acknowledged: false,
        canExecute: false
      }] : [];
    }
    if (systemMap.summary) {
      next.systemMap.reportPath = pick(systemMap.report_path || systemMap.summary.report_path, next.systemMap.reportPath);
      next.systemMap.sections = Array.isArray(systemMap.summary.sections) ? systemMap.summary.sections : next.systemMap.sections;
    }
    next.ai.provider = pick(aiStatus.gateway && aiStatus.gateway.provider && aiStatus.gateway.provider.provider, next.ai.provider);
    next.ai.providerState = pick(aiStatus.gateway && aiStatus.gateway.provider && aiStatus.gateway.provider.provider_state, next.ai.providerState);
    const aiGateway = aiStatus.gateway || {};
    const aiProvider = aiGateway.provider || {};
    const aiPolicy = aiGateway.model_policy || {};
    next.ai.providerMode = pick(aiProvider.provider_mode || aiPolicy.provider_mode, next.ai.providerMode || "NOT_CONFIGURED");
    next.ai.modelName = pick(aiProvider.model_name || aiProvider.model || aiPolicy.model_name, next.ai.modelName || null);
    next.ai.modelQuality = pick(aiProvider.model_quality || aiPolicy.model_quality, next.ai.modelQuality || "FALLBACK_ONLY");
    next.ai.reasoningPolicy = pick(aiProvider.reasoning_policy || aiPolicy.reasoning_policy, next.ai.reasoningPolicy || "FALLBACK_ONLY_LIMITED");
    next.ai.modelSuitableForGovernance = aiProvider.model_suitable_for_governance === true || aiPolicy.model_suitable_for_governance === true;
    next.ai.modelQualityWarning = pick(aiProvider.model_quality_warning || aiPolicy.warning, next.ai.modelQualityWarning || "");
    const aiRegistry = aiGateway.provider_registry || {};
    if (Array.isArray(aiRegistry.providers)) {
      next.ai.providerRegistry = aiRegistry.providers.map((provider) => ({
        providerId: pick(provider.provider_id, "unknown"),
        displayName: pick(provider.display_name, provider.provider_id || "unknown"),
        status: pick(provider.status, "UNKNOWN"),
        configured: provider.configured === true,
        credentialSource: pick(provider.credential_source, "NOT_CONFIGURED"),
        modelName: pick(provider.model_name || provider.default_model, "not selected"),
        modelQuality: pick((provider.model_quality_map && provider.model_quality_map[provider.model_name]) || provider.model_quality, "UNKNOWN"),
        costMode: pick((provider.cost_tier_map && provider.cost_tier_map[provider.model_name]) || provider.cost_mode, "UNKNOWN"),
        reasoningCapability: pick((provider.reasoning_capability_map && provider.reasoning_capability_map[provider.model_name]) || provider.provider_family, "unknown"),
        implemented: provider.implemented === true,
        personaEnforced: true,
        lastValidationStatus: pick(provider.last_validation_status, "NOT_RUN"),
        lastErrorCategory: pick(provider.last_error_category, null)
      }));
    }
    const routing = aiRouterSettings.settings || aiStatus.routing_settings || aiGateway.router || {};
    next.ai.routingSettings = {
      defaultMode: pick(routing.default_mode || routing.default_route_mode, next.ai.routingSettings && next.ai.routingSettings.defaultMode || "LOCAL_GUIDE"),
      activeProvider: pick(routing.active_provider, next.ai.routingSettings && next.ai.routingSettings.activeProvider || "deterministic_local"),
      activeModel: pick(routing.active_model, next.ai.routingSettings && next.ai.routingSettings.activeModel || "deterministic-local-guide"),
      lightProvider: pick(routing.light_provider, next.ai.routingSettings && next.ai.routingSettings.lightProvider || "openai"),
      lightModel: pick(routing.light_model, next.ai.routingSettings && next.ai.routingSettings.lightModel || "gpt-5-mini"),
      highReasoningProvider: pick(routing.high_reasoning_provider, next.ai.routingSettings && next.ai.routingSettings.highReasoningProvider || "openai"),
      highReasoningModel: pick(routing.high_reasoning_model, next.ai.routingSettings && next.ai.routingSettings.highReasoningModel || "gpt-5.5-pro"),
      localProvider: pick(routing.local_provider || routing.local_model_provider, "local_openai_compatible"),
      localBaseUrl: pick(routing.local_base_url, next.ai.routingSettings && next.ai.routingSettings.localBaseUrl || "http://127.0.0.1:11434/v1"),
      localModel: pick(routing.local_model, next.ai.routingSettings && next.ai.routingSettings.localModel || "local-model"),
      supremeBoardPacketDefault: routing.supreme_board_packet_default === true,
      settingsSource: pick(aiRouterSettings.settings_source || aiStatus.routing_settings_source, next.ai.routingSettings && next.ai.routingSettings.settingsSource || "DEFAULT_SETTINGS"),
      status: pick(aiRouterSettings.status || aiStatus.routing_settings_status, next.ai.routingSettings && next.ai.routingSettings.status || "DEFAULT_SETTINGS"),
      settingsPathRelative: pick(aiRouterSettings.settings_path_relative || aiStatus.routing_settings_path_relative, ".operator_config/ai_router_settings.json")
    };
    next.ai.pendingReviewCount = pick(aiStatus.pending_review_count, next.ai.pendingReviewCount);
    next.ai.secretsValuesExposed = aiStatus.secrets_values_exposed === true;
    if (Array.isArray(aiRecommendations.recommendations)) {
      next.ai.recommendations = aiRecommendations.recommendations.map((rec) => ({
        recommendationId: pick(rec.recommendation_id, "unknown"),
        recommendationType: pick(rec.recommendation_type, "OBSERVATION"),
        status: pick(rec.status, "DRAFT"),
        summary: pick(rec.summary, ""),
        proposedAction: pick(rec.proposed_action, "NO_ACTION"),
        canExecute: rec.can_execute === true
      }));
    }
    if (Array.isArray(providers.providers)) {
      next.providerReadiness.providers = providers.providers.map((provider) => ({
        providerId: pick(provider.provider_id, "unknown"),
        displayName: pick(provider.display_name, provider.provider_id || "unknown"),
        category: pick(provider.category, "unknown"),
        purpose: pick(provider.purpose, ""),
        status: pick(provider.status, "UNKNOWN"),
        requiredEnvVars: Array.isArray(provider.required_env_vars) ? provider.required_env_vars : [],
        optionalEnvVars: Array.isArray(provider.optional_env_vars) ? provider.optional_env_vars : [],
        envStatus: Array.isArray(provider.env_status) ? provider.env_status.map((row) => ({
          name: pick(row.name, "unknown"),
          configured: row.configured === true,
          fingerprint: pick(row.fingerprint, null),
          source: pick(row.source, "NOT_CONFIGURED")
        })) : [],
        configured: provider.configured === true,
        credentialSource: pick(provider.credential_source || provider.source, "NOT_CONFIGURED"),
        readOnlyValidationSupported: provider.read_only_validation_supported === true,
        canTrade: provider.can_trade === true,
        canMutateExternalSystem: provider.can_mutate_external_system === true,
        lastValidationStatus: pick(provider.last_validation_status, "NOT_RUN"),
        lastValidationAt: pick(provider.last_validation_at, null),
        setupInstructions: pick(provider.setup_instructions, "")
      }));
      next.providerReadiness.providerCount = pick(providers.provider_count, next.providerReadiness.providers.length);
      next.providerReadiness.counts = providers.counts || {};
    }
    if (providerReadiness.source) {
      next.providerReadiness.readyOrConfiguredCount = pick(providerReadiness.ready_or_configured_count, next.providerReadiness.readyOrConfiguredCount);
      next.providerReadiness.missingCredentialsCount = pick(providerReadiness.missing_credentials_count, next.providerReadiness.missingCredentialsCount);
      next.providerReadiness.notImplementedCount = pick(providerReadiness.not_implemented_count, next.providerReadiness.notImplementedCount);
    } else if (providers.counts) {
      next.providerReadiness.readyOrConfiguredCount = (providers.counts.READY || 0) + (providers.counts.CONFIGURED || 0);
      next.providerReadiness.missingCredentialsCount = providers.counts.MISSING_CREDENTIALS || 0;
      next.providerReadiness.notImplementedCount = providers.counts.NOT_IMPLEMENTED || 0;
    }
    if (credentialsProviders.source) {
      next.credentials = {
        source: credentialsProviders.source,
        storePath: pick(credentialsProviders.store_path, ".operator_secrets/provider_credentials.json"),
        storeExists: credentialsProviders.store_exists === true,
        configuredCount: pick(credentialsProviders.configured_count, 0),
        providerCount: pick(credentialsProviders.provider_count, 0),
        precedence: pick(credentialsProviders.precedence, "ENV_PRESENT_OVERRIDES_LOCAL_SECRET"),
        providers: Array.isArray(credentialsProviders.providers) ? credentialsProviders.providers.map((provider) => ({
          providerId: pick(provider.provider_id, "unknown"),
          displayName: pick(provider.display_name, provider.provider_id || "unknown"),
          configured: provider.configured === true,
          source: pick(provider.source, "NOT_CONFIGURED"),
          fields: Array.isArray(provider.fields) ? provider.fields.map((field) => ({
            name: pick(field.name, "unknown"),
            configured: field.configured === true,
            source: pick(field.source, "NOT_CONFIGURED"),
            fingerprint: pick(field.fingerprint, null)
          })) : []
        })) : []
      };
    }
    if (portfolio.source) {
      next.portfolio = normalizePortfolio(portfolio);
      next.positions = next.portfolio.positions;
      next.orders = next.portfolio.openOrders;
      if (next.portfolio.status === "BROKER_CONFIRMED") {
        next.status.broker = "alpaca_paper";
        next.status.endpoint = "https://paper-api.alpaca.markets";
      }
    }
    if (paperBaseline.source) {
      next.paperBaseline = normalizePaperBaseline(paperBaseline);
    }
    if (launchReadiness.source) {
      next.launchReadiness = {
        source: launchReadiness.source,
        finalLaunchReadiness: pick(launchReadiness.final_launch_readiness, "UNKNOWN"),
        checks: Array.isArray(launchReadiness.checks) ? launchReadiness.checks.map((check) => ({
          checkId: pick(check.check_id, "unknown"),
          title: pick(check.title, "unknown"),
          status: pick(check.status, "UNKNOWN"),
          detail: pick(check.detail, ""),
          blocker: check.blocker === true,
          warning: check.warning === true
        })) : [],
        reasonCodes: Array.isArray(launchReadiness.reason_codes) ? launchReadiness.reason_codes : [],
        alpacaPaperCredentialsConfigured: launchReadiness.alpaca_paper_credentials_configured === true,
        paperEndpointOnly: launchReadiness.paper_endpoint_only === true,
        paperEndpointStatus: pick(launchReadiness.paper_endpoint_status, "UNKNOWN"),
        paperEndpointSource: pick(launchReadiness.paper_endpoint_source, "UNKNOWN"),
        paperEndpointOperatorAction: pick(launchReadiness.paper_endpoint_operator_action, ""),
        paperEndpointDisplay: pick(launchReadiness.paper_endpoint_display, ""),
        paperEndpointFamily: pick(launchReadiness.paper_endpoint_family, "unknown"),
        paperEndpointHost: pick(launchReadiness.paper_endpoint_host, ""),
        paperEndpointBlockerCode: pick(launchReadiness.paper_endpoint_blocker_code, ""),
        alpacaEndpointConfigured: launchReadiness.alpaca_endpoint_configured === true,
        alpacaPaperEndpointValid: launchReadiness.alpaca_paper_endpoint_valid === true,
        alpacaLiveEndpointBlocked: launchReadiness.alpaca_live_endpoint_blocked !== false,
        paperEndpointAuthority: launchReadiness.paper_endpoint_authority || {},
        paperStartAllowed: launchReadiness.paper_start_allowed === true,
        runPaperOperatorState: normalizeRunPaperOperatorState(launchReadiness.run_paper_operator_state),
        safeStopStatus: pick(launchReadiness.safe_stop_status, "UNKNOWN"),
        portfolioReadAvailability: pick(launchReadiness.portfolio_read_availability, "UNKNOWN"),
        backendDegradedReasons: Array.isArray(launchReadiness.backend_degraded_reasons) ? launchReadiness.backend_degraded_reasons : []
      };
      next.paperBaseline = normalizePaperBaseline(
        launchReadiness.run_paper_operator_state && launchReadiness.run_paper_operator_state.paper_baseline
          ? launchReadiness.run_paper_operator_state.paper_baseline
          : (paperBaseline.source ? paperBaseline : next.paperBaseline)
      );
    }
    if (research.source) {
      next.research.hypotheses = Array.isArray(research.hypotheses) ? research.hypotheses.map((item) => ({
        id: pick(item.id, "unknown"),
        title: pick(item.title, "untitled"),
        thesis: pick(item.thesis, ""),
        symbolsAssets: Array.isArray(item.symbols_assets) ? item.symbols_assets : [],
        strategyArea: pick(item.strategy_area, "UNKNOWN"),
        expectedEdge: pick(item.expected_edge, "UNKNOWN_UNPROVEN"),
        status: pick(item.status, "NEEDS_REVIEW"),
        promotionStage: pick(item.promotion_stage, "IDEA"),
        canExecute: item.can_execute === true
      })) : [];
      next.research.experiments = Array.isArray(research.experiments) ? research.experiments.map((item) => ({
        id: pick(item.id, "unknown"),
        title: pick(item.title, "untitled"),
        thesis: pick(item.thesis, ""),
        status: pick(item.status, "NEEDS_REVIEW"),
        promotionStage: pick(item.promotion_stage, "OFFLINE_RESEARCH"),
        canExecute: item.can_execute === true,
        paperStarted: item.paper_started === true
      })) : [];
      next.research.promotionGates = Array.isArray(research.promotion_gates) ? research.promotion_gates.map((gate) => ({
        gateId: pick(gate.gate_id, "unknown"),
        stage: pick(gate.stage, "IDEA"),
        requiredEvidence: Array.isArray(gate.required_evidence) ? gate.required_evidence : [],
        currentStatus: pick(gate.current_status, "NEEDS_REVIEW"),
        blocksPromotion: gate.blocks_promotion !== false,
        liveRequiresSeparateApproval: gate.live_requires_separate_approval === true
      })) : [];
      next.research.recommendations = Array.isArray(research.recommendations) ? research.recommendations.map((rec) => ({
        id: pick(rec.id, "unknown"),
        title: pick(rec.title, "untitled"),
        summary: pick(rec.summary, ""),
        status: pick(rec.status, "NEEDS_REVIEW"),
        promotionStage: pick(rec.promotion_stage, "IDEA"),
        canExecute: rec.can_execute === true
      })) : [];
      const counts = research.counts || {};
      next.research.counts = {
        hypotheses: pick(counts.hypotheses, next.research.hypotheses.length),
        experiments: pick(counts.experiments, next.research.experiments.length),
        recommendations: pick(counts.recommendations, next.research.recommendations.length),
        promotionGates: pick(counts.promotion_gates, next.research.promotionGates.length)
      };
    }
    if (evidenceGraph.source) {
      next.evidenceGraph.nodes = Array.isArray(evidenceGraph.nodes) ? evidenceGraph.nodes.map((node) => ({
        nodeId: pick(node.node_id, "unknown"),
        label: pick(node.label, "unknown"),
        truthLabel: pick(node.truth_label, "advisory"),
        summary: pick(node.summary, ""),
        runId: pick(node.run_id, null),
        reportPath: pick(node.report_path, null)
      })) : [];
      next.evidenceGraph.edges = Array.isArray(evidenceGraph.edges) ? evidenceGraph.edges : [];
      next.evidenceGraph.latestRunId = pick(evidenceGraph.latest_run_id, null);
      next.evidenceGraph.reportPath = pick(evidenceGraph.report_path, null);
      next.evidenceGraph.reasonCodes = Array.isArray(evidenceGraph.reason_codes) ? evidenceGraph.reason_codes : [];
      next.evidenceGraph.missingEvidence = Array.isArray(evidenceGraph.missing_evidence) ? evidenceGraph.missing_evidence : [];
      next.evidenceGraph.promotionBlockers = Array.isArray(evidenceGraph.promotion_blockers) ? evidenceGraph.promotion_blockers : [];
    } else if (endpointFailures.evidenceGraph) {
      next.evidenceGraph.reasonCodes = ["EVIDENCE_GRAPH_DEGRADED"];
      next.evidenceGraph.missingEvidence = [endpointFailures.evidenceGraph];
      next.evidenceGraph.promotionBlockers = ["Research OS evidence graph degraded; credential setup remains usable."];
    }
    if (historicalTests.source) {
      next.historicalTests = {
        source: historicalTests.source,
        status: pick(historicalTests.status, "UNKNOWN"),
        presets: Array.isArray(historicalTests.presets) ? historicalTests.presets : [],
        timeframes: Array.isArray(historicalTests.timeframes) ? historicalTests.timeframes : HISTORICAL_TIMEFRAMES,
        feeSlippagePolicies: Array.isArray(historicalTests.fee_slippage_policies) ? historicalTests.fee_slippage_policies : [],
        defaultWatchlist: Array.isArray(historicalTests.default_watchlist) ? historicalTests.default_watchlist : ["BTC/USD", "ETH/USD", "SOL/USD"],
        lastResults: Array.isArray(historicalTests.last_results) ? historicalTests.last_results.map(normalizeHistoricalRun) : [],
        simulationHarnessAttached: historicalTests.simulation_harness_attached === true,
        readOnlyMarketDataOnly: historicalTests.read_only_market_data_only !== false,
        brokerTradingCallOccurred: historicalTests.broker_trading_call_occurred === true,
        brokerMutationOccurred: historicalTests.broker_mutation_occurred === true,
        canExecute: historicalTests.can_execute === true,
        secretsValuesExposed: historicalTests.secrets_values_exposed === true,
        lastIntentResult: pick(next.historicalTests && next.historicalTests.lastIntentResult, "none")
      };
      next.historicalTests.lastRunResult = next.historicalTests.lastResults[0] || null;
    }
    if (Array.isArray(world.providers)) {
      const runtimeByProvider = {};
      if (Array.isArray(worldRuntime.providers)) {
        worldRuntime.providers.forEach((provider) => {
          runtimeByProvider[provider.provider] = provider;
        });
      }
      next.worldAwareness = world.providers.map((provider) => ({
        ...(() => {
          const runtimeProvider = runtimeByProvider[provider.provider] || {};
          return {
            nextPollTime: pick(runtimeProvider.next_poll_time, provider.next_poll_time || "not scheduled"),
            nextPollDue: runtimeProvider.next_poll_due === true,
            backoffSeconds: pick(runtimeProvider.backoff_seconds, provider.backoff_seconds || 0),
            errorCount: pick(runtimeProvider.error_count, provider.error_count || 0),
            consecutiveErrorCount: pick(runtimeProvider.consecutive_error_count, 0)
          };
        })(),
        source: pick(provider.provider, "unknown_provider"),
        feedType: pick(provider.feed_type, "UNKNOWN"),
        enabled: provider.enabled === true,
        status: pick(provider.status, "FEED_DISABLED"),
        eventCount: pick(provider.event_count, 0),
        staleCount: pick(provider.stale_count, 0),
        lastPollTime: pick(provider.last_poll_time, "never"),
        relevance: provider.enabled === true ? "read-only advisory provider configured" : "disabled by default",
        confidence: provider.credential_present === true ? "credential present" : "credential missing/not inspected",
        stale: false,
        verification: "UNVERIFIED",
        rule: "advisory only; cannot bypass MarketTruthSnapshot, NetEdge, guardrails, or broker boundary"
      }));
    }
    next.worldRuntime.manualPollOnly = worldRuntime.manual_poll_only !== false;
    next.worldRuntime.providerPollingActive = worldRuntime.provider_polling_active === true;
    next.worldRuntime.dueProviders = pick(worldRuntime.due_providers, []);
    if (Array.isArray(world.events)) {
      next.worldAwarenessEvents = world.events.map((event) => ({
        eventId: pick(event.event_id, "unknown"),
        provider: pick(event.provider, "unknown_provider"),
        feedType: pick(event.feed_type, "UNKNOWN"),
        symbols: Array.isArray(event.symbols) ? event.symbols : [],
        title: pick(event.title, "untitled advisory event"),
        eventTime: pick(event.event_time, "unknown"),
        freshness: `${pick(event.freshness_seconds, 0)}s`,
        stale: event.stale === true,
        verification: pick(event.verification_status, "UNVERIFIED"),
        advisoryOnly: event.advisory_only !== false,
        reason: Array.isArray(event.reason_codes) ? event.reason_codes.join(", ") : "ADVISORY_ONLY"
      }));
    }

    if (!portfolio.source) {
      next.orders = [
        {
          clientOrderId: "read_only_backend_summary",
          symbol: "all",
          side: "none",
          action: "read_only_summary",
          state: `broker_open=${pick(orders.broker_confirmed_open_orders, 0)}`,
          brokerStatus: `terminal=${pick(orders.terminal_orders, 0)}`,
          reconciliation: `conflicts=${pick(orders.reconciliation_conflicts, 0)}`
        }
      ];
    }
    const feeHydrationSkipped = fills.fee_hydration_skipped === true;
    const feeHydrationStatus = feeHydrationSkipped
      ? "Fee/activity hydration not authorized for this smoke run."
      : `fills=${pick(fills.fill_hydration_count, 0)} fee=${pick(fills.broker_fee_hydration_count, 0)} pending=${pick(fills.broker_fee_hydration_pending_count, 0)}`;
    const feeHydrationReason = feeHydrationSkipped
      ? pick(fills.fee_hydration_skip_reason, "BROKER_READ_NOT_AUTHORIZED")
      : `fill_conflicts=${pick(fills.fill_hydration_conflict_count, 0)} fee_conflicts=${pick(fills.broker_fee_hydration_conflict_count, 0)}`;
    next.fills = [
      {
        fillId: "read_only_backend_summary",
        symbol: "all",
        side: "none",
        quantity: String(pick(fills.local_fills, 0)),
        price: "not displayed by backend v1",
        source: pick(fills.source, "NO_ACTIVE_RUNTIME_ATTACHED"),
        hydrationStatus: feeHydrationStatus,
        feeStatus: pick(fills.fee_status, "FEE_PENDING_BROKER_ACTIVITY"),
        feeSource: pick(fills.fee_source, "UNAVAILABLE"),
        tca: pick(tca.execution_quality_verdict, "UNKNOWN_NO_ACTIVE_RUNTIME"),
        reason: feeHydrationReason
      }
    ];

    if (paperControlState.source) {
      next.paperControlState = normalizePaperControlState(paperControlState);
      applyPaperControlState(next, next.paperControlState);
    } else if (endpointFailures.paperControlState) {
      const controlFailureCode = paperControlStateFailureCode(endpointFailures.paperControlState);
      next.paperControlState = {
        source: controlFailureCode,
        paperStartAllowed: false,
        paperStopAllowed: next.supervisor.paperStopAllowed === true,
        dominantBlocker: controlFailureCode,
        reasonCodes: [controlFailureCode]
      };
      next.launchReadiness.runPaperOperatorState = buildBackendConnectedRunPaperState(
        next,
        `/operator/paper-control-state: ${endpointFailures.paperControlState}`
      );
    }
    applyRuntimeLifecycleTruth(next, payload);
    reconcileBackendConnectedAuthority(next, endpointFailures);
    mergeCredentialTruthIntoProviderReadiness(next);
    return next;
  }

  function statusFromLauncherStatus(launcherStatus, health) {
    const payload = launcherStatus || {};
    const healthPayload = health || {};
    const supervisorState = pick(payload.supervisor_state, healthPayload.supervisor_status || "IDLE");
    return {
      api_version: pick(healthPayload.api_version, "operator-backend-v1"),
      data_source: "OPERATOR_BACKEND",
      git_commit_short: pick(payload.loaded_commit, healthPayload.loaded_commit || healthPayload.git_commit_short),
      git_branch: pick(payload.loaded_branch, healthPayload.loaded_branch || healthPayload.git_branch),
      loaded_commit: pick(payload.loaded_commit, healthPayload.loaded_commit),
      loaded_branch: pick(payload.loaded_branch, healthPayload.loaded_branch),
      process_start_time: pick(payload.process_start_time, healthPayload.process_start_time),
      backend_pid: pick(payload.pid, healthPayload.pid || healthPayload.backend_pid),
      bot_status: supervisorState === "RUNNING" ? "RUNNING" : "IDLE_NO_ACTIVE_PAPER_RUN",
      runtime_mode: "PAPER",
      mode_state: "PAPER_ENABLED",
      capability_state: "PAPER_ENABLED",
      active_profile: "PAPER_IDLE",
      broker: "alpaca_paper",
      endpoint: "https://paper-api.alpaca.markets",
      market_data: "IDLE_NO_ACTIVE_MARKET_DATA_RUNTIME",
      universe: [],
      asset_classes: [],
      dominant_blocker: supervisorState === "RUNNING" ? "SUPERVISOR_PROCESS_RUNNING_OR_RECENT" : "IDLE_NO_ACTIVE_PAPER_RUN",
      runtime_attachment_state: supervisorState === "RUNNING" ? "SUPERVISOR_PROCESS_RUNNING_OR_RECENT" : "IDLE_NO_ACTIVE_PAPER_RUN",
      runtime_attachment_detail: supervisorState === "RUNNING" ? "PAPER supervisor process is attached." : "No PAPER run currently attached.",
      safety_verdict: "OPERATOR_SUPERVISOR_READY",
      live_blocked: true,
      real_money_blocked: true,
      manual_trading_available: false,
      force_trade_available: false,
      supervisor: {
        state: supervisorState,
        active_session_id: payload.active_run_id || null,
        paper_start_allowed: supervisorState !== "RUNNING",
        paper_stop_allowed: supervisorState === "RUNNING",
        paper_start_refusal_reason: supervisorState === "RUNNING" ? "DUPLICATE_ACTIVE_RUN" : null,
        allowed_durations: [],
        max_paper_duration_seconds: 432000
      },
      secrets_values_exposed: false,
      updated_at: pick(payload.timestamp_utc, healthPayload.timestamp_utc)
    };
  }

  function uniqueEndpointTasks(tasks) {
    const seen = new Set();
    return tasks.filter((task) => {
      const key = `${task.key}:${task.path}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }

  function endpointTasksForScreen(screenId) {
    const active = screenId || "positions";
    const common = [
      { key: "version", path: "/operator/version", priority: 0, lane: "critical" },
      { key: "health", path: "/operator/health", priority: 0, lane: "critical" },
      { key: "launcherStatus", path: "/operator/launcher-status", priority: 0, lane: "critical" },
      { key: "paperControlState", path: "/operator/paper-control-state", priority: 0, lane: "critical" },
      { key: "status", path: "/operator/status", priority: 0, lane: "critical" },
      { key: "latestRun", path: "/operator/latest-run", priority: 1, lane: "normal" },
      { key: "credentialsProviders", path: "/operator/credentials/providers", priority: 1, lane: "normal" },
      { key: "paperBaseline", path: "/operator/paper-baseline", priority: 1, lane: "normal" },
      { key: "launchReadiness", path: "/operator/launch-readiness", priority: 1, lane: "normal" },
      { key: "contracts", path: "/operator/contracts", priority: 2, lane: "normal", optional: true }
    ];
    const byScreen = {
      positions: [
        { key: "portfolio", path: "/operator/portfolio", priority: 2, lane: "normal" },
        { key: "orders", path: "/operator/orders-summary", priority: 2, lane: "normal", optional: true }
      ],
      command: [
        { key: "portfolio", path: "/operator/portfolio", priority: 2, lane: "normal" },
        { key: "runtime", path: "/operator/runtime-minimal", priority: 1, lane: "normal" },
        { key: "actionCenter", path: "/operator/action-center", priority: 3, lane: "optional", optional: true }
      ],
      activity: [
        { key: "runtime", path: "/operator/runtime", priority: 2, lane: "normal" },
        { key: "orders", path: "/operator/orders-summary", priority: 2, lane: "normal", optional: true },
        { key: "fills", path: "/operator/fills-summary", priority: 3, lane: "optional", optional: true },
        { key: "audit", path: "/operator/audit-summary", priority: 3, lane: "optional", optional: true }
      ],
      runs: [
        { key: "runs", path: "/operator/runs", priority: 3, lane: "optional", optional: true },
        { key: "explain", path: "/operator/explain/latest", priority: 3, lane: "optional", optional: true }
      ],
      pnl: [
        { key: "pnlDashboard", path: "/operator/pnl", priority: 3, lane: "optional", optional: true },
        { key: "tcaDashboard", path: "/operator/tca", priority: 3, lane: "optional", optional: true },
        { key: "fills", path: "/operator/fills-summary", priority: 3, lane: "optional", optional: true },
        { key: "tca", path: "/operator/tca-summary", priority: 3, lane: "optional", optional: true }
      ],
      decision: [
        { key: "explain", path: "/operator/explain/latest", priority: 2, lane: "normal", optional: true }
      ],
      market: [
        { key: "universe", path: "/operator/universe", priority: 2, lane: "normal", optional: true }
      ],
      risk: [
        { key: "operatorReadiness", path: "/operator/readiness", priority: 2, lane: "normal", optional: true }
      ],
      alerts: [
        { key: "alerts", path: "/operator/alerts", priority: 3, lane: "optional", optional: true }
      ],
      action: [
        { key: "actionCenter", path: "/operator/action-center", priority: 3, lane: "optional", optional: true },
        { key: "alerts", path: "/operator/alerts", priority: 3, lane: "optional", optional: true }
      ],
      providers: [
        { key: "providers", path: "/operator/providers", priority: 2, lane: "normal" },
        { key: "providerReadiness", path: "/operator/providers/readiness", priority: 2, lane: "normal" },
        { key: "aiStatus", path: "/operator/ai/status", priority: 2, lane: "normal", optional: true },
        { key: "aiRouterSettings", path: "/operator/ai/router/settings", priority: 2, lane: "normal", optional: true }
      ],
      ai: [
        { key: "aiStatus", path: "/operator/ai/status", priority: 2, lane: "normal", optional: true },
        { key: "aiRouterSettings", path: "/operator/ai/router/settings", priority: 2, lane: "normal", optional: true },
        { key: "aiRecommendations", path: "/operator/ai/recommendations", priority: 3, lane: "optional", optional: true }
      ],
      research: [
        { key: "research", path: "/operator/research", priority: 3, lane: "optional", optional: true },
        { key: "evidenceGraph", path: "/operator/research/evidence-graph", priority: 3, lane: "optional", optional: true }
      ],
      world: [
        { key: "world", path: "/operator/world-awareness", priority: 3, lane: "optional", optional: true },
        { key: "worldRuntime", path: "/operator/world-awareness/runtime", priority: 3, lane: "optional", optional: true }
      ],
      diagnostics: [
        { key: "diagnostics", path: "/operator/diagnostics", priority: 3, lane: "optional", optional: true },
        { key: "perfRecent", path: "/operator/perf/recent", priority: 3, lane: "optional", optional: true }
      ],
      system: [
        { key: "systemMap", path: "/operator/system-map", priority: 3, lane: "optional", optional: true },
        { key: "storage", path: "/operator/storage", priority: 3, lane: "optional", optional: true },
        { key: "diagnostics", path: "/operator/diagnostics", priority: 3, lane: "optional", optional: true }
      ],
      audit: [
        { key: "audit", path: "/operator/audit-summary", priority: 3, lane: "optional", optional: true },
        { key: "runs", path: "/operator/runs", priority: 3, lane: "optional", optional: true }
      ],
      historical: [
        { key: "historicalTests", path: "/operator/historical-tests", priority: 3, lane: "optional", optional: true }
      ],
      live: [
        { key: "readiness", path: "/operator/readiness/live", priority: 2, lane: "normal", optional: true }
      ]
    };
    return uniqueEndpointTasks([...common, ...(byScreen[active] || [])]);
  }

  async function loadData(options) {
    const opts = options || {};
    const selectedScreen = opts.activeScreen || activeScreenId || "positions";
    const generation = ++dataLoadGeneration;
    if (activeLoadAbortController) {
      activeLoadAbortController.abort();
    }
    activeLoadAbortController = new AbortController();
    const signal = activeLoadAbortController.signal;
    const payload = {};
    const failures = [];
    const endpointFailures = {};
    const scheduler = createRequestScheduler();
    const tasks = endpointTasksForScreen(selectedScreen);
    const taskResults = await Promise.allSettled(tasks.map((task) => scheduler.schedule({ ...task, signal })));
    if (generation !== dataLoadGeneration) {
      const stale = new Error("stale backend response ignored");
      stale.lifecycleAbort = true;
      throw stale;
    }
    taskResults.forEach((result) => {
      if (result.status === "fulfilled") {
        payload[result.value.key] = result.value.payload;
        return;
      }
      const failure = result.reason || {};
      const error = failure.error || failure;
      const path = failure.path || "unknown";
      const key = failure.key || path;
      if (error && error.lifecycleAbort === true) {
        logBackendFetchAbort(path, error);
        return;
      }
      const detail = describeFetchFailure(path, error);
      logBackendFetchFailure(path, error);
      endpointFailures[key] = detail;
      if (failure.optional !== true && !OPTIONAL_BACKEND_ENDPOINTS.has(path)) {
        failures.push(detail);
      }
    });
    if (!payload.status && (payload.launcherStatus || payload.health)) {
      payload.status = statusFromLauncherStatus(payload.launcherStatus, payload.health);
    }
    if (!payload.status) {
      return buildProductionUnavailableState(endpointFailures.status || "operator backend status unavailable");
    }
    payload.uiBuildCommit = uiBuildCommit();
    const backendCommit = String(
      (payload.version && payload.version.backend_commit)
      || (payload.status && payload.status.git_commit_short)
      || (payload.health && (payload.health.loaded_commit || payload.health.git_commit_short))
      || ""
    );
    if (!isUnknownBuildCommit(backendCommit) && !isUnknownBuildCommit(payload.uiBuildCommit) && backendCommit !== payload.uiBuildCommit) {
      const mismatch = `UI_BACKEND_COMMIT_MISMATCH: ui=${payload.uiBuildCommit} backend=${backendCommit}`;
      endpointFailures.uiBuildCommit = mismatch;
      failures.push(mismatch);
    }
    payload.endpointFailures = endpointFailures;

    const normalized = normalizeBackendData(payload);
    normalized.meta.dataSource = failures.length ? "PARTIAL_BACKEND" : "OPERATOR_BACKEND";
    normalized.meta.backendStatus = failures.length
      ? `status connected; ${failures.length} secondary endpoint(s) failed`
      : "backend connected";
    normalized.meta.fetchFailures = failures;
    return normalized;
  }

  let activeScreenRefreshToken = 0;

  async function boot() {
    data = await loadData({ activeScreen: "positions" });
    aiOverlayOpen = shouldOpenAiDockFromUrl();
    aiWideMode = aiOverlayOpen && shouldUseWideAiDockFromUrl();
    syncAiDockedState();
    renderTopBar();
    renderNav();
    renderScreens("positions");
    renderRail();
    renderAiChiefOverlay();
    startRuntimeLifecycleObservers();
  }

  async function refreshActiveScreenData(screenId) {
    const selected = screenId || activeScreenId || "positions";
    const refreshToken = ++activeScreenRefreshToken;
    try {
      const nextData = await loadData({ activeScreen: selected });
      if (refreshToken !== activeScreenRefreshToken) return;
      data = nextData;
      renderTopBar();
      renderScreens(selected);
      renderRail();
      renderAiChiefOverlay();
    } catch (error) {
      if (error && error.lifecycleAbort === true) {
        return;
      }
      logBackendFetchFailure(`screen:${selected}`, error);
    }
  }

  function renderLifecycleState() {
    renderTopBar();
    if (activeScreenId === "command" || activeScreenId === "activity") {
      refreshRunPaperControlDom();
    } else {
      renderScreens(activeScreenId || "positions");
    }
    renderRail();
    renderAiChiefOverlay();
  }

  async function fetchLifecyclePayload() {
    const tasks = [
      ["paperControlState", "/operator/paper-control-state"],
      ["latestRun", "/operator/latest-run"],
      ["status", "/operator/status"],
      ["runtime", "/operator/runtime"]
    ];
    const results = await Promise.allSettled(tasks.map(([key, path]) => fetchJson(path).then((payload) => ({ key, payload }))));
    const payload = {};
    results.forEach((result) => {
      if (result.status === "fulfilled") {
        payload[result.value.key] = result.value.payload;
      }
    });
    return payload;
  }

  async function reconcileRuntimeLifecycle(reason) {
    if (lifecycleRefreshInFlight) return;
    lifecycleRefreshInFlight = true;
    try {
      const payload = await fetchLifecyclePayload();
      if (payload.paperControlState && payload.paperControlState.source) {
        data.paperControlState = normalizePaperControlState(payload.paperControlState);
        applyPaperControlState(data, data.paperControlState);
      }
      applyRuntimeLifecycleTruth(data, payload);
      data.meta.lastUpdated = new Date().toISOString();
      data.meta.lifecycleLastRefreshReason = reason || "poll";
      renderLifecycleState();
    } catch (error) {
      logBackendFetchFailure(`runtime-lifecycle:${reason || "poll"}`, error);
    } finally {
      lifecycleRefreshInFlight = false;
    }
  }

  function scheduleLifecycleRefresh(reason, delayMs) {
    if (lifecycleRefreshTimer) return;
    lifecycleRefreshTimer = window.setTimeout(() => {
      lifecycleRefreshTimer = null;
      reconcileRuntimeLifecycle(reason);
    }, delayMs === undefined ? 250 : delayMs);
  }

  function startRuntimeLifecycleObservers() {
    if (!lifecyclePollTimer) {
      lifecyclePollTimer = window.setInterval(() => {
        scheduleLifecycleRefresh("poll", 0);
      }, LIFECYCLE_RECONCILE_INTERVAL_MS);
    }
    if (!lifecycleEventSource && "EventSource" in window) {
      try {
        lifecycleEventSource = new EventSource(`${operatorApiBase()}/operator/events`);
        ["backend_status", "launcher_status", "runtime_minimal", "paper_control_state", "supervisor_state", "run_event"].forEach((eventName) => {
          lifecycleEventSource.addEventListener(eventName, () => {
            scheduleLifecycleRefresh(`sse:${eventName}`, 500);
          });
        });
        lifecycleEventSource.onerror = () => {
          scheduleLifecycleRefresh("sse-error-poll-fallback", 0);
        };
      } catch (error) {
        logBackendFetchFailure("runtime-lifecycle:sse", error);
      }
    }
  }

  async function requestJson(path, options) {
    const opts = options || {};
    const response = await fetch(`${operatorApiBase()}${path}`, {
      method: opts.method || "GET",
      headers: { "Content-Type": "application/json" },
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body || {})
    });
    if (!response.ok) {
      let detail = "";
      try {
        const errorPayload = await response.json();
        detail = errorPayload.reason_code || errorPayload.detail || errorPayload.status || "";
      } catch (_error) {
        detail = "";
      }
      throw new Error(`HTTP ${response.status}${detail ? `: ${detail}` : ""}`);
    }
    return response.json();
  }

  async function postIntent(path, body) {
    return requestJson(path, { method: "POST", body });
  }

  function paperRunFormValues(formId) {
    const draft = syncPaperRunDraftFromDom(formId || "command", { markDirty: false });
    const bounds = paperDurationBounds();
    const validation = paperDraftValidation(draft, bounds);
    const durationSeconds = paperDraftDurationSeconds(draft);
    return {
      watchlist: normalizePaperWatchlist(draft.watchlistRaw),
      durationSeconds,
      profile: draft.profileAlpha !== false ? "PAPER_EXPLORATION_ALPHA" : data.status.activeProfile,
      maxDurationSeconds: bounds.maxDuration,
      validation,
      confirmPaper: draft.confirmPaper === true,
      confirmLiveLocked: draft.confirmLiveLocked === true,
      confirmRealMoneyBlocked: draft.confirmRealMoneyBlocked === true,
      confirmNoManualTrades: draft.confirmNoManualTrades === true
    };
  }

  function paperBaselineAcceptancePayload() {
    const portfolio = data.portfolio || {};
    const summary = portfolio.summary || {};
    const positions = Array.isArray(portfolio.positions) ? portfolio.positions : [];
    const openOrders = Array.isArray(portfolio.openOrders) ? portfolio.openOrders : [];
    return {
      policy: "ADOPT_EXISTING_POSITIONS_PROTECTED",
      accepted_by_operator: "Shan/local operator",
      preflight_snapshot: {
        endpoint_family: "paper",
        account: {
          account_id: summary.accountId || null,
          status: summary.accountStatus || "UNKNOWN",
          equity: summary.totalEquity || null,
          buying_power: summary.buyingPower || null,
          currency: summary.currency || null,
          trading_blocked: summary.tradingBlocked === true,
          account_blocked: summary.accountBlocked === true,
          transfers_blocked: summary.transfersBlocked === true,
          pattern_day_trader: summary.patternDayTrader === true
        },
        open_order_count: summary.openOrderCount || openOrders.length || 0,
        open_orders: openOrders.map((order) => ({
          order_id: order.orderId || null,
          symbol: order.symbol,
          side: order.side,
          qty: order.qty,
          type: order.type,
          status: order.status,
          submitted_at: order.submittedAt
        })),
        position_count: summary.positionCount || positions.length || 0,
        positions: positions.map((position) => ({
          symbol: position.symbol,
          asset_class: position.assetClass,
          quantity: position.quantity,
          side: position.side,
          average_entry_price: position.averageEntryPrice,
          cost_basis: position.costBasis,
          market_value: position.marketValue,
          current_market_price: position.currentMarketPrice,
          unrealized_pnl: position.unrealizedPnl,
          unrealized_pnl_percent: position.unrealizedPnlPercent,
          baseline_position: true
        }))
      }
    };
  }

  function historicalFormValues() {
    const form = document.querySelector("[data-historical-form]");
    const value = (selector, fallback) => ((form && form.querySelector(selector)) || {}).value || fallback;
    return {
      date_range_preset: value("[data-historical-preset]", "last_4_months"),
      start_date: value("[data-historical-start]", ""),
      end_date: value("[data-historical-end]", ""),
      watchlist: value("[data-historical-watchlist]", "BTC/USD,ETH/USD,SOL/USD").split(",").map((item) => item.trim().toUpperCase()).filter(Boolean),
      timeframe: value("[data-historical-timeframe]", "1Day"),
      starting_capital: value("[data-historical-capital]", "10000"),
      fee_slippage_policy: value("[data-historical-fee-policy]", "broker_fees_unavailable_unknown"),
      strategy_profile: value("[data-historical-profile]", "PAPER_EXPLORATION_ALPHA")
    };
  }

  function credentialFormValues(providerId) {
    const fields = {};
    const escapedProvider = window.CSS && CSS.escape ? CSS.escape(providerId) : String(providerId).replaceAll('"', '\\"');
    document.querySelectorAll(`[data-credential-provider="${escapedProvider}"][data-credential-field]`).forEach((input) => {
      const name = input.dataset.credentialField;
      const value = String(input.value || "").trim();
      if (value) fields[name] = value;
    });
    if ((providerId === "alpaca_paper" || providerId === "alpaca_news") && !fields.APCA_API_BASE_URL) {
      fields.APCA_API_BASE_URL = "https://paper-api.alpaca.markets";
    }
    return fields;
  }

  function clearCredentialInputs(providerId) {
    const escapedProvider = window.CSS && CSS.escape ? CSS.escape(providerId) : String(providerId).replaceAll('"', '\\"');
    document.querySelectorAll(`[data-credential-provider="${escapedProvider}"][data-credential-field]`).forEach((input) => {
      input.value = "";
    });
  }

  async function handleIntent(intent, sourceButton) {
    if (!backendConnected()) return;
    try {
      let message = "none";
      if (intent === "paper-baseline-accept") {
        const payload = paperBaselineAcceptancePayload();
        const snapshot = payload.preflight_snapshot || {};
        const count = Number(snapshot.position_count || 0);
        const openOrders = Number(snapshot.open_order_count || 0);
        if (count <= 0) {
          window.alert("No existing positions are loaded for baseline adoption.");
          return;
        }
        if (openOrders !== 0) {
          window.alert("Open orders must be zero before baseline adoption. No cancel request will be sent.");
          return;
        }
        const confirmed = window.confirm(
          `Accept protected PAPER baseline?\n\nPositions: ${count}\nOpen orders: ${openOrders}\nPolicy: ${payload.policy}\n\nThis is a local operator-state write only. It will not call Alpaca, start PAPER, place, cancel, replace, close, or liquidate orders.`
        );
        if (!confirmed) return;
        const result = await postIntent("/operator/paper-baseline/accept", payload);
        message = `${result.status || "UNKNOWN"}: ${result.baseline_snapshot_id || result.reason_code || "paper_baseline"}`;
      }
      if (intent === "paper-start") {
        const formId = sourceButton && sourceButton.dataset ? sourceButton.dataset.paperForm : "command";
        const form = paperRunFormValues(formId);
        if (!form.confirmPaper || !form.confirmLiveLocked || !form.confirmRealMoneyBlocked || !form.confirmNoManualTrades) {
          window.alert("Confirm PAPER-only, live locked, real-money blocked, and no manual trades before requesting the governed PAPER start.");
          return;
        }
        if (form.validation && form.validation.valid !== true) {
          window.alert(form.validation.detail || "Fix the Run PAPER draft before starting.");
          refreshRunPaperControlDom();
          return;
        }
        if (form.durationSeconds > form.maxDurationSeconds) {
          window.alert(`Selected duration exceeds the current governed PAPER lease max of ${formatDuration(form.maxDurationSeconds)}.`);
          return;
        }
        const confirmed = window.confirm(
          `Request governed PAPER start?\n\nProfile: ${form.profile}\nWatchlist: ${form.watchlist.join(", ")}\nDuration: ${formatDuration(form.durationSeconds)} (${form.durationSeconds} seconds)\n\nNo live trading or manual order will be sent by the UI.`
        );
        if (!confirmed) return;
        const result = await postIntent("/operator/intent/paper/start", {
          mode: "PAPER",
          profile: form.profile,
          duration_seconds: form.durationSeconds,
          watchlist: form.watchlist,
          approve_autonomous_paper: true,
          real_money: false,
          live: false
        });
        message = `${result.status}: ${result.reason_code}`;
        if (result.allowed === true || result.reason_code === "PAPER_RUN_STARTED") {
          const draft = resetPaperRunDraft(formId, PAPER_DRAFT_RESET_REASONS.RUN_STARTED);
          draft.startedSessionId = result.session_id || (result.session && result.session.session_id) || null;
        }
      }
      if (intent === "paper-stop") {
        const confirmed = window.confirm("Request governed PAPER stop? This sends only the supervisor stop intent and preserves broker positions.");
        if (!confirmed) return;
        const result = await postIntent("/operator/intent/paper/stop", {});
        message = `${result.status}: ${result.reason_code}`;
      }
      if (intent === "world-poll") {
        const confirmed = window.confirm("Request read-only Alpaca News poll? This cannot trade, bypass guardrails, or touch broker execution.");
        if (!confirmed) return;
        const result = await postIntent("/operator/intent/world-awareness/poll", {
          provider: "alpaca_news",
          force: false,
          symbols: ["BTC/USD", "ETH/USD", "SOL/USD"],
          limit: 25
        });
        message = `${result.status}: ${result.reason_code}`;
      }
      if (intent === "ai-analyze") {
        const confirmed = window.confirm("Run advisory AI Chief analysis? This cannot trade, start PAPER, enable live, or call broker execution.");
        if (!confirmed) return;
        const result = await postIntent("/operator/ai/analyze", {
          requested_by: "operator_ui",
          advisory_only: true
        });
        const recommendation = result.recommendation || {};
        message = `${result.status || "QUEUED"}: ${recommendation.recommendation_type || "OBSERVATION"}`;
      }
      if (intent === "ai-quant-review") {
        const confirmed = window.confirm("Queue AI Quant Research Chief review? This cannot trade, start PAPER, enable live, call broker execution, or change thresholds.");
        if (!confirmed) return;
        const result = await postIntent("/operator/ai/quant-review", {
          requested_by: "operator_ui",
          advisory_only: true,
          prompt: "What is the safest next PAPER experiment?"
        });
        const recommendation = result.recommendation || {};
        message = `${result.status || "QUEUED"}: ${recommendation.recommendation_type || "STRATEGY_REVIEW"}`;
      }
      if (intent === "historical-run") {
        const form = historicalFormValues();
        const confirmed = window.confirm(
          `Run historical Alpaca test request?\n\nRange: ${form.date_range_preset}\nWatchlist: ${form.watchlist.join(", ")}\nTimeframe: ${form.timeframe}\n\nThis does not start PAPER, trade, call broker trading endpoints, or produce fake performance.`
        );
        if (!confirmed) return;
        const result = await postIntent("/operator/historical-tests/run", form);
        message = `${result.status || "UNKNOWN"}: ${result.test_id || "historical_test"}`;
        data.historicalTests.lastRunResult = normalizeHistoricalRun(result);
      }
      const selectedScreen = activeScreenId;
      data = await loadData();
      if (intent === "historical-run" && message !== "none") {
        data.historicalTests.lastIntentResult = message;
      }
      data.supervisor.lastIntentResult = message;
      data.worldRuntime.lastPollResult = message;
      data.ai.lastAnalyzeResult = message;
      renderTopBar();
      renderScreens(selectedScreen);
      renderRail();
      renderAiChiefOverlay();
    } catch (error) {
      data.supervisor.lastIntentResult = `FAILED: ${error.message || error.name || "intent_error"}`;
      renderScreens(activeScreenId);
      renderRail();
      renderAiChiefOverlay();
    }
  }

  async function handleCredentialAction(action, providerId) {
    if (!backendConnected()) {
      credentialActionStatus[providerId] = "failed: backend unavailable; no local credential write occurred";
      data.providerReadiness.lastCredentialResult = `${providerId}: FAILED backend unavailable`;
      renderScreens(activeScreenId);
      renderRail();
      renderAiChiefOverlay();
      return;
    }
    let pendingCredentials = null;
    if (action === "save") {
      pendingCredentials = credentialFormValues(providerId);
      if (!Object.keys(pendingCredentials).length) {
        credentialActionStatus[providerId] = "failed: no credential fields entered";
        window.alert("Enter at least one credential field before saving.");
        renderScreens(activeScreenId);
        return;
      }
    }
    credentialActionStatus[providerId] = `${action === "save" ? "saving" : action === "validate" ? "validating" : "deleting"}...`;
    renderScreens(activeScreenId);
    try {
      let result;
      if (action === "save") {
        result = await postIntent("/operator/credentials/save", {
          provider_id: providerId,
          credentials: pendingCredentials
        });
        clearCredentialInputs(providerId);
      } else if (action === "validate") {
        result = await postIntent("/operator/credentials/validate-readonly", {
          provider_id: providerId
        });
      } else if (action === "delete") {
        const confirmed = window.confirm(`Delete local credentials for ${providerId}? This only mutates the local gitignored secret store.`);
        if (!confirmed) return;
        result = await requestJson(`/operator/credentials/provider/${encodeURIComponent(providerId)}`, { method: "DELETE" });
      }
      const selectedScreen = activeScreenId;
      data = await loadData();
      const statusText = credentialActionStatusText(action, providerId, result || {});
      credentialActionStatus[providerId] = statusText;
      data.providerReadiness.lastCredentialResult = statusText;
      renderTopBar();
      renderScreens(selectedScreen);
      renderRail();
      renderAiChiefOverlay();
    } catch (error) {
      const statusText = `${providerId}: FAILED ${error.message || error.name || "credential_error"}`;
      credentialActionStatus[providerId] = statusText;
      data.providerReadiness.lastCredentialResult = statusText;
      renderScreens(activeScreenId);
      renderRail();
    }
  }

  document.addEventListener("input", (event) => {
    const paperCard = event.target.closest("[data-paper-form-card]");
    if (paperCard && (
      event.target.matches("[data-paper-watchlist]")
      || event.target.matches("[data-paper-duration-amount]")
    )) {
      const field = event.target.matches("[data-paper-watchlist]") ? "watchlist" : "custom_duration";
      syncPaperRunDraftFromDom(paperCard.dataset.paperFormCard || "command", { markDirty: true, dirtyFields: [field] });
      refreshRunPaperControlDom();
      return;
    }
    const aiQuestion = event.target.closest("[data-ai-chief-question]");
    if (aiQuestion) {
      aiQuestionText = aiQuestion.value;
      return;
    }
    const homeQuestion = event.target.closest("[data-home-ai-question]");
    if (homeQuestion) {
      homeAiQuestionText = homeQuestion.value;
    }
  });

  document.addEventListener("change", (event) => {
    const paperCard = event.target.closest("[data-paper-form-card]");
    if (paperCard && (
      event.target.matches("[data-paper-duration]")
      || event.target.matches("[data-paper-duration-unit]")
      || event.target.matches("[data-paper-profile-alpha]")
      || event.target.matches("[data-paper-confirm-paper]")
      || event.target.matches("[data-paper-confirm-live-locked]")
      || event.target.matches("[data-paper-confirm-real-money-blocked]")
      || event.target.matches("[data-paper-confirm-no-manual-trades]")
    )) {
      let field = "confirmation";
      if (event.target.matches("[data-paper-duration]")) field = "duration";
      if (event.target.matches("[data-paper-duration-unit]")) field = "custom_duration";
      if (event.target.matches("[data-paper-profile-alpha]")) field = "profile";
      syncPaperRunDraftFromDom(paperCard.dataset.paperFormCard || "command", { markDirty: true, dirtyFields: [field] });
      refreshRunPaperControlDom();
    }
  });

  document.addEventListener("keydown", (event) => {
    const aiQuestion = event.target.closest("[data-ai-chief-question]");
    if (aiQuestion && event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (!aiOverlayBusy) askAiChiefQuestion();
      return;
    }
    const homeQuestion = event.target.closest("[data-home-ai-question]");
    if (homeQuestion && event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (!homeAiBusy) askHomeAiQuestion(homeAiAnswerMode || AI_ANSWER_MODES.DETERMINISTIC);
    }
  });

  document.addEventListener("click", (event) => {
    const paperDraftReset = event.target.closest("[data-paper-draft-reset]");
    if (paperDraftReset) {
      resetPaperRunDraft(paperDraftReset.dataset.paperDraftReset || "command", PAPER_DRAFT_RESET_REASONS.USER_RESET);
      renderScreens(activeScreenId);
      renderRail();
      return;
    }
    const aiOpen = event.target.closest("[data-ai-chief-open]");
    if (aiOpen) {
      setAiOverlayOpen(true);
      return;
    }
    const aiClose = event.target.closest("[data-ai-chief-close]");
    if (aiClose) {
      setAiOverlayOpen(false);
      return;
    }
    const aiWide = event.target.closest("[data-ai-chief-wide]");
    if (aiWide) {
      toggleAiWideMode();
      return;
    }
    const aiPrompt = event.target.closest("[data-ai-chief-prompt]");
    if (aiPrompt) {
      selectAiQuestion(aiPrompt.dataset.aiChiefPrompt);
      return;
    }
    const aiAnswerModeAsk = event.target.closest("[data-ai-answer-mode-ask]");
    if (aiAnswerModeAsk && !aiAnswerModeAsk.disabled) {
      const [scope, mode] = String(aiAnswerModeAsk.dataset.aiAnswerModeAsk || "overlay:DETERMINISTIC").split(":");
      if (scope === "home") {
        askHomeAiQuestion(mode);
      } else {
        askAiChiefQuestion(undefined, mode);
      }
      return;
    }
    const aiAnalyze = event.target.closest("[data-ai-chief-analyze]");
    if (aiAnalyze && !aiAnalyze.disabled) {
      runAiOverlayAnalyze();
      return;
    }
    const aiClear = event.target.closest("[data-ai-chief-clear]");
    if (aiClear && !aiClear.disabled) {
      clearAiQuestion();
      return;
    }
    const aiCopyPacket = event.target.closest("[data-ai-copy-packet]");
    if (aiCopyPacket && !aiCopyPacket.disabled) {
      copyCurrentAiPacket();
      return;
    }
    const aiCopyAnswer = event.target.closest("[data-ai-copy-answer]");
    if (aiCopyAnswer && !aiCopyAnswer.disabled) {
      copyAiAnswer(aiCopyAnswer.dataset.aiCopyAnswer);
      return;
    }
    const aiJumpLatest = event.target.closest("[data-ai-jump-latest]");
    if (aiJumpLatest) {
      aiUserPinnedScroll = false;
      renderAiChiefOverlay();
      scheduleAiOverlayScroll({ force: true });
      return;
    }
    const homeAiPrompt = event.target.closest("[data-home-ai-prompt]");
    if (homeAiPrompt) {
      selectHomeAiQuestion(homeAiPrompt.dataset.homeAiPrompt);
      return;
    }
    const homeAiClear = event.target.closest("[data-home-ai-clear]");
    if (homeAiClear && !homeAiClear.disabled) {
      clearHomeAiQuestion();
      return;
    }
    const aiSaveRouting = event.target.closest("[data-ai-save-routing]");
    if (aiSaveRouting && !aiSaveRouting.disabled) {
      saveAiRoutingSettings();
      return;
    }
    const aiProviderTest = event.target.closest("[data-ai-provider-test]");
    if (aiProviderTest && !aiProviderTest.disabled) {
      validateSelectedAiProvider();
      return;
    }
    const aiGeneratePacket = event.target.closest("[data-ai-generate-packet]");
    if (aiGeneratePacket && !aiGeneratePacket.disabled) {
      generateSupremeBoardPacket();
      return;
    }
    const aiUseProviderNow = event.target.closest("[data-ai-use-provider-now]");
    if (aiUseProviderNow && !aiUseProviderNow.disabled) {
      useAiProviderNow(aiUseProviderNow.dataset.aiUseProviderNow);
      return;
    }
    const aiUseSupremeBoard = event.target.closest("[data-ai-use-supreme-board]");
    if (aiUseSupremeBoard && !aiUseSupremeBoard.disabled) {
      useSupremeBoardPacketMode();
      return;
    }
    const aiApproveHigh = event.target.closest("[data-ai-approve-high-call]");
    if (aiApproveHigh && !aiApproveHigh.disabled) {
      approveOneHighReasoningCall();
      return;
    }
    const aiUseLocal = event.target.closest("[data-ai-use-local-guide]");
    if (aiUseLocal) {
      applyRoutingToLocalState({ default_mode: "LOCAL_GUIDE" });
      data.ai.lastAnalyzeResult = "LOCAL_GUIDE selected; no API call occurred.";
      renderScreens(activeScreenId);
      renderAiChiefOverlay();
      return;
    }
    const aiUseLight = event.target.closest("[data-ai-use-light-model]");
    if (aiUseLight && !aiUseLight.disabled) {
      const settings = currentAiRoutingFormValues();
      settings.default_mode = "LIGHT_API";
      applyRoutingToLocalState(settings);
      saveAiRoutingSettings();
      return;
    }
    const aiUseLocalModel = event.target.closest("[data-ai-use-local-model]");
    if (aiUseLocalModel && !aiUseLocalModel.disabled) {
      const settings = currentAiRoutingFormValues();
      settings.default_mode = "LOCAL_MODEL";
      applyRoutingToLocalState(settings);
      saveAiRoutingSettings();
      return;
    }
    const credentialSave = event.target.closest("[data-credential-save]");
    if (credentialSave) {
      handleCredentialAction("save", credentialSave.dataset.credentialSave);
      return;
    }
    const credentialValidate = event.target.closest("[data-credential-validate]");
    if (credentialValidate) {
      handleCredentialAction("validate", credentialValidate.dataset.credentialValidate);
      return;
    }
    const credentialDelete = event.target.closest("[data-credential-delete]");
    if (credentialDelete) {
      handleCredentialAction("delete", credentialDelete.dataset.credentialDelete);
      return;
    }
    const screenShortcut = event.target.closest("[data-screen-shortcut]");
    if (screenShortcut) {
      showScreen(screenShortcut.dataset.screenShortcut);
      return;
    }
    const button = event.target.closest("[data-intent]");
    if (!button || button.disabled) return;
    handleIntent(button.dataset.intent, button);
  });

  document.addEventListener("DOMContentLoaded", boot);
})();
