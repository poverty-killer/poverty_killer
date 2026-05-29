(function () {
  "use strict";

  const mockData = window.PK_MOCK_DATA;
  let data = clone(mockData);
  const screens = [
    ["command", "Command Center"],
    ["action", "Action Center"],
    ["runs", "Run Archive"],
    ["historical", "Historical Tests"],
    ["pnl", "P&L / Net Profit"],
    ["positions", "Positions & Orders"],
    ["activity", "Bot Activity Control"],
    ["decision", "Signal & Decision Lab"],
    ["market", "Market Data Truth"],
    ["risk", "Risk & Governor"],
    ["alerts", "Watchdog Alerts"],
    ["ai", "AI Chief Operator"],
    ["providers", "Provider Setup"],
    ["research", "Research OS"],
    ["system", "System Map"],
    ["audit", "Audit Log"],
    ["world", "World Awareness"],
    ["diagnostics", "Diagnostics"],
    ["live", "Live Readiness"]
  ];
  const DEFAULT_BACKEND_FETCH_TIMEOUT_MS = 10000;
  const HEAVY_BACKEND_FETCH_TIMEOUT_MS = 15000;
  const HEAVY_BACKEND_ENDPOINTS = new Set([
    "/operator/runs",
    "/operator/action-center",
    "/operator/alerts"
  ]);
  const AI_CONTEXT_VERSION = "operator-ui-global-ai-context-v1";
  const AI_QUICK_PROMPTS = [
    "Where is the edge?",
    "What is the weakest assumption?",
    "Is this signal statistically believable?",
    "What would invalidate this strategy?",
    "What is the safest next PAPER experiment?",
    "Where are fees/slippage hurting us?",
    "What evidence blocks live readiness?",
    "Critique latest run.",
    "Compare latest run to expected behavior.",
    "Draft a Codex packet.",
    "Review provider/data readiness."
  ];
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
    alpaca_news: {
      title: "Alpaca News",
      fields: [
        ["APCA_API_KEY_ID", "API key ID", "password", ""],
        ["APCA_API_SECRET_KEY", "API secret key", "password", ""],
        ["APCA_API_BASE_URL", "PAPER base URL", "text", "https://paper-api.alpaca.markets"]
      ]
    }
  };
  const HISTORICAL_TIMEFRAMES = ["1Min", "5Min", "15Min", "1Hour", "1Day"];
  const HISTORICAL_FEE_POLICIES = [
    ["broker_fees_unavailable_unknown", "Broker fees unavailable / unknown"],
    ["conservative_estimate_not_broker_truth", "Conservative estimate - not broker truth"]
  ];
  let activeScreenId = "command";
  let aiOverlayOpen = false;
  let aiSelectedQuestion = AI_QUICK_PROMPTS[0];
  let aiQuestionText = AI_QUICK_PROMPTS[0];
  let aiOverlayResponse = "";
  let aiOverlayError = "";
  let aiOverlayBusy = false;
  let homeAiQuestionText = "Review launch readiness, portfolio state, and the safest next PAPER step.";
  let homeAiResponse = "";
  let homeAiError = "";
  let homeAiBusy = false;
  let credentialActionStatus = {};

  function softBreakToken(value) {
    return escapeHtml(String(value))
      .replaceAll("_", "_<wbr>")
      .replaceAll("/", "/<wbr>")
      .replaceAll("-", "-<wbr>")
      .replaceAll(", ", ", <wbr>");
  }

  function badge(text, color) {
    const raw = String(text);
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
    const v = String(value).toUpperCase();
    if (v.includes("NO_ACTIVE") || v.includes("REFUSED")) return "yellow";
    if (v.includes("PASS") || v.includes("ALLOW") || v.includes("CLEAN") || v.includes("RUNNING") || v.includes("PAPER") || v.includes("READY") || v.includes("CONFIGURED")) return "green";
    if (v.includes("UNKNOWN") || v.includes("MISSING") || v.includes("DEGRADED") || v.includes("NO_TRADE") || v.includes("DECLINED")) return "yellow";
    if (v.includes("BLOCK") || v.includes("LOCK") || v.includes("DENY") || v.includes("CONFLICT") || v.includes("LIVE")) return "red";
    return "gray";
  }

  function dataSourceColor() {
    if (data.meta.dataSource === "OPERATOR_BACKEND") return "green";
    if (data.meta.dataSource === "PARTIAL_BACKEND") return "yellow";
    return "yellow";
  }

  function sourceLabel() {
    if (data.meta.dataSource === "OPERATOR_BACKEND") return "OPERATOR_BACKEND / read-only";
    if (data.meta.dataSource === "PARTIAL_BACKEND") return `PARTIAL_BACKEND / ${backendDegradedSummary()}`;
    return "MOCK DATA / sample";
  }

  function sourceSubtext() {
    if (data.meta.dataSource === "OPERATOR_BACKEND") return "OPERATOR_BACKEND / runtime truth";
    if (data.meta.dataSource === "PARTIAL_BACKEND") return `PARTIAL_BACKEND / ${backendDegradedSummary()}`;
    return "MOCK DATA / sample fallback";
  }

  function backendDegradedSummary() {
    const failures = data.meta.fetchFailures || [];
    if (!failures.length) return "status connected; secondary status pending";
    return `${failures.length} degraded: ${failures.slice(0, 2).join(" | ")}${failures.length > 2 ? " | more in Diagnostics" : ""}`;
  }

  function backendConnected() {
    return data.meta.dataSource === "OPERATOR_BACKEND" || data.meta.dataSource === "PARTIAL_BACKEND";
  }

  function screenTitle(id) {
    const found = screens.find(([screenId]) => screenId === id);
    return found ? found[1] : "Command Center";
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
      badge(s.broker, "blue"),
      badge(endpointLabel, endpointLabel === "PAPER endpoint" ? "green" : "yellow"),
      badge(s.universe.join(", "), "gray"),
      badge(`POST ${s.brokerPostCount}`, "yellow"),
      badge(`DELETE ${s.brokerDeleteCount}`, "yellow"),
      badge("Live blocked", "red"),
      badge("Real-money blocked", "red")
    ].join("");
  }

  function paperLaunchDisabledReason() {
    const launch = data.launchReadiness || {};
    const sup = data.supervisor || {};
    if (!backendConnected()) return "Disabled: backend unavailable; mock/sample mode cannot start PAPER.";
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

  function renderPaperLaunchControl(formId) {
    const launch = data.launchReadiness || {};
    const sup = data.supervisor || {};
    const disabledReason = paperLaunchDisabledReason();
    const startDisabled = disabledReason ? "disabled" : "";
    const watchlist = (sup.watchlist && sup.watchlist.length ? sup.watchlist : ["BTC/USD", "ETH/USD", "SOL/USD"]).join(",");
    return `
      <div class="card span-12 paper-launch-card" data-paper-form-card="${escapeHtml(formId)}">
        <div class="split">
          <h3>PAPER Launch Control</h3>
          ${badge(launch.finalLaunchReadiness || "UNKNOWN", statusColor(launch.finalLaunchReadiness || "UNKNOWN"))}
        </div>
        <div class="form-grid">
          <label>Watchlist
            <input data-paper-watchlist type="text" value="${escapeHtml(watchlist)}" autocomplete="off">
          </label>
          <label>Duration
            <select data-paper-duration>
              ${[300, 900, 1800, 3600].map((seconds) => `<option value="${seconds}" ${seconds === 300 ? "selected" : ""}>${seconds} seconds</option>`).join("")}
            </select>
          </label>
          <label class="checkline"><input data-paper-profile-alpha type="checkbox" checked> PAPER_EXPLORATION_ALPHA</label>
          <label class="checkline"><input data-paper-confirm-paper type="checkbox"> Confirm PAPER-only</label>
          <label class="checkline"><input data-paper-confirm-live-locked type="checkbox"> Confirm live locked</label>
          <label class="checkline"><input data-paper-confirm-real-money-blocked type="checkbox"> Confirm real-money blocked</label>
          <label class="checkline"><input data-paper-confirm-no-manual-trades type="checkbox"> Confirm no manual trades</label>
        </div>
        <div class="button-row">
          <button class="intent-button paper" data-intent="paper-start" data-paper-form="${escapeHtml(formId)}" ${startDisabled}>
            Start Bounded PAPER Run
          </button>
          <button class="intent-button live" disabled>No manual trades / force trade unavailable</button>
        </div>
        <div class="notice">${escapeHtml(disabledReason || "Ready to request the governed /operator/intent/paper/start endpoint after confirmations are checked.")}</div>
        <div class="notice mono">Endpoint target: /operator/intent/paper/start only. Last intent: ${escapeHtml(sup.lastIntentResult || "none")}</div>
      </div>
    `;
  }

  function renderHomeLaunchReadiness() {
    const launch = data.launchReadiness || {};
    const readiness = data.providerReadiness || {};
    const providerCounts = readiness.counts || {};
    return `
      <div class="card span-12" data-home-section="launch-readiness"><h3>Launch Readiness</h3>${kv([
        ["Can I run PAPER right now?", badge(launch.finalLaunchReadiness || "UNKNOWN", statusColor(launch.finalLaunchReadiness || "UNKNOWN"))],
        ["Exact blockers", tokenText((launch.reasonCodes || []).join(", ") || "none reported")],
        ["Alpaca PAPER credentials", badge(launch.alpacaPaperCredentialsConfigured ? "configured" : "missing", launch.alpacaPaperCredentialsConfigured ? "green" : "red")],
        ["Provider status", escapeHtml(`${readiness.readyOrConfiguredCount || 0} ready/configured, ${readiness.missingCredentialsCount || providerCounts.MISSING_CREDENTIALS || 0} missing`)],
        ["Live", badge("LOCKED", "red")],
        ["Real money", badge("BLOCKED", "red")],
        ["Active runtime", badge(data.supervisor.processState || "UNKNOWN", statusColor(data.supervisor.processState || "UNKNOWN"))],
        ["Safe stop", badge(launch.safeStopStatus || "UNKNOWN", statusColor(launch.safeStopStatus || "UNKNOWN"))],
        ["Storage/audit", badge(data.diagnostics.sessionStoreStatus || "UNKNOWN", statusColor(data.diagnostics.sessionStoreStatus || "UNKNOWN"))],
        ["Portfolio read", badge(launch.portfolioReadAvailability || "UNKNOWN", statusColor(launch.portfolioReadAvailability || "UNKNOWN"))]
      ])}
        ${table(
          ["Check", "Status", "Detail", "Blocker"],
          (launch.checks || []).map((check) => [
            escapeHtml(check.title || check.checkId || "unknown"),
            badge(check.status || "UNKNOWN", statusColor(check.status || "UNKNOWN")),
            escapeHtml(check.detail || ""),
            badge(check.blocker ? "yes" : "no", check.blocker ? "red" : "gray")
          ])
        )}
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
    const unavailable = portfolio.status === "BROKER_DATA_UNAVAILABLE";
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
      ) : `<p class="muted">${escapeHtml(unavailable ? `No current PAPER positions shown; broker data unavailable: ${portfolio.unavailableReason || "UNKNOWN"}.` : "No current PAPER positions.")}</p>`}</div>
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
        ["Biggest blocker", tokenText(data.status.dominantBlocker || (blockers[0] || "none reported"))],
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
    return `
      <div class="card span-12" data-home-section="ai-quant-advisor"><h3>AI Quant Advisor</h3>
        <div class="notice ai-mission">Advisory only. can_execute=false. No broker calls, no live enablement, no real-money enablement, no threshold mutation, no secrets.</div>
        <div class="notice mono">Provider: ${escapeHtml(providerLabel)}. If a model key is configured but real model calls are unavailable, /operator/ai/ask returns an honest deterministic fallback.</div>
        <div class="ai-ask-box">
          <label for="home-ai-question">Ask a question from the home page</label>
          <textarea id="home-ai-question" data-home-ai-question rows="4" placeholder="Ask what blocks PAPER, what we own, what risk matters, or what proof is needed next.">${escapeHtml(homeAiQuestionText || "")}</textarea>
          <div class="ai-question-bank" aria-label="Home AI Advisor suggestions">
            ${AI_QUICK_PROMPTS.slice(0, 6).map((prompt) => `
              <button class="ai-question" type="button" data-home-ai-prompt="${escapeHtml(prompt)}">${escapeHtml(prompt)}</button>
            `).join("")}
          </div>
          <div class="button-row">
            <button class="intent-button paper" type="button" data-home-ai-ask ${homeAiBusy ? "disabled" : ""}>${homeAiBusy ? "Asking..." : "Ask AI Quant Advisor"}</button>
            <button class="intent-button paper" type="button" data-home-ai-clear ${homeAiBusy ? "disabled" : ""}>Clear</button>
            <button class="intent-button paper" type="button" data-ai-chief-open>Open Global Drawer</button>
          </div>
          ${homeAiError ? `<div class="notice error">Error: ${escapeHtml(homeAiError)}</div>` : ""}
        </div>
        <div class="ai-response"><h3>Home Advisory Response</h3><pre>${escapeHtml(response)}</pre></div>
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
    nav.innerHTML = screens.map(([id, label], index) => `
      <button class="nav-button ${index === 0 ? "active" : ""}" data-screen="${id}">
        <span>${escapeHtml(label)}</span>
        <span class="muted">${String(index + 1).padStart(2, "0")}</span>
      </button>
    `).join("");
    nav.addEventListener("click", (event) => {
      const button = event.target.closest("[data-screen]");
      if (!button) return;
      showScreen(button.dataset.screen);
    });
  }

  function showScreen(id) {
    activeScreenId = id;
    document.querySelectorAll(".screen").forEach((el) => el.classList.toggle("active", el.id === `screen-${id}`));
    document.querySelectorAll(".nav-button").forEach((el) => el.classList.toggle("active", el.dataset.screen === id));
    renderAiChiefOverlay();
  }

  function renderCommand() {
    const s = data.status;
    const actionCounts = data.actionCenter.counts || {};
    const launch = data.launchReadiness || {};
    return `
      ${header("Command Center", "Operational truth, authority, and current runtime safety.", s.safetyVerdict)}
      <div class="grid">
        ${metric("Bot Status", s.botStatus, "green")}
        ${metric("Mode", s.runtimeMode, "green")}
        ${metric("Live", "LOCKED", "red")}
        ${metric("Real-money", "BLOCKED", "red")}
        ${renderHomeLaunchReadiness()}
        ${renderPaperLaunchControl("command")}
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
          ["Dominant blocker", badge(s.dominantBlocker, "yellow")]
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
          ["Run", "Status", "Verdict", "Profile", "Duration", "Orders", "Fills", "TCA", "Report"],
          archive.runs.map((run) => [
            escapeHtml(run.runId),
            badge(run.status, statusColor(run.status)),
            badge(run.finalVerdict, statusColor(run.finalVerdict)),
            escapeHtml(run.profile || "unknown"),
            escapeHtml(run.durationSeconds || "unknown"),
            escapeHtml(`${run.ordersSubmitted}/${run.ordersAcknowledged}/${run.ordersCanceled}`),
            escapeHtml(`${run.fillsObserved}`),
            badge(run.tcaStatus, statusColor(run.tcaStatus)),
            escapeHtml(run.reportPath || "not generated")
          ])
        )}</div>
        <div class="card span-12"><h3>Historical Alpaca Test Link</h3>
          <p class="muted">Use the Historical Tests page for the 4-month Alpaca historical control. It is advisory only and cannot start PAPER or trade.</p>
          <button class="intent-button paper" data-screen-shortcut="historical">Open Historical Tests</button>
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
            <button class="intent-button live" disabled>Does not start PAPER / does not trade</button>
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
      ${header("P&L / Net Profit", "Broker-confirmed economics only. Unknown stays unknown.", "BROKER TRUTH REQUIRED")}
      <div class="grid">
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
    const unavailable = portfolio.status === "BROKER_DATA_UNAVAILABLE";
    return `
      ${header("Positions & Orders", "Broker-confirmed PAPER portfolio truth, open orders, and position intelligence.", portfolio.status || "UNKNOWN")}
      <div class="grid">
        ${metric("Positions", summary.positionCount || 0, summary.positionCount ? "green" : "gray")}
        ${metric("Open Orders", summary.openOrderCount || 0, summary.openOrderCount ? "yellow" : "gray")}
        ${metric("Total Equity", summary.totalEquity || "unknown", summary.totalEquity ? "green" : "yellow")}
        ${metric("Unrealized P&L", summary.totalUnrealizedPnl || "unknown", summary.totalUnrealizedPnl ? statusColor(summary.totalUnrealizedPnl) : "yellow")}
        <div class="card span-12"><h3>Portfolio Summary</h3>${kv([
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
        ])}</div>
        ${unavailable ? `<div class="card span-12"><h3>Broker Data Unavailable</h3><p class="muted">Reason: ${escapeHtml(portfolio.unavailableReason || "UNKNOWN")}. No positions are invented and local-only state is not shown as broker truth.</p></div>` : ""}
        <div class="card span-12"><h3>Current PAPER Positions</h3>${positions.length ? table(
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
        ) : `<p class="muted">${escapeHtml(portfolio.empty ? "No current PAPER positions." : "No broker-confirmed positions available.")}</p>`}</div>
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
            badge(o.canCancel ? "available" : "not available", o.canCancel ? "red" : "gray")
          ])
        ) : `<p class="muted">No open broker-confirmed orders.</p>`}</div>
        <div class="card span-12"><h3>Position Intelligence</h3>${intelligence.length ? table(
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
        ) : `<p class="muted">No position intelligence available without broker-confirmed positions.</p>`}</div>
      </div>
    `;
  }

  function renderActivity() {
    const sup = data.supervisor;
    const launch = data.launchReadiness || {};
    const duration = sup.durationSeconds === null || sup.durationSeconds === undefined ? "not active" : `${sup.durationSeconds}s`;
    return `
      ${header("Bot Activity Control", "Governed PAPER intents only. Live and manual trading remain locked.", sourceLabel())}
      <div class="grid">
        <div class="card span-12"><h3>Launch Readiness</h3>${kv([
          ["Final", badge(launch.finalLaunchReadiness || "UNKNOWN", statusColor(launch.finalLaunchReadiness || "UNKNOWN"))],
          ["Alpaca PAPER credentials", badge(launch.alpacaPaperCredentialsConfigured ? "configured" : "missing", launch.alpacaPaperCredentialsConfigured ? "green" : "red")],
          ["PAPER endpoint", badge(launch.paperEndpointOnly ? "confirmed" : "blocked/unknown", launch.paperEndpointOnly ? "green" : "red")],
          ["Paper start", badge(launch.paperStartAllowed ? "allowed" : "blocked", launch.paperStartAllowed ? "green" : "red")],
          ["Safe stop", badge(launch.safeStopStatus || "UNKNOWN", statusColor(launch.safeStopStatus || "UNKNOWN"))],
          ["Backend degraded reasons", escapeHtml((launch.backendDegradedReasons || []).join(", ") || "none")]
        ])}
          <div class="status-strip">${(launch.checks || []).map((check) => badge(`${check.checkId}:${check.status}`, statusColor(check.status))).join("")}</div>
        </div>
        <div class="card span-6"><h3>Runtime Snapshot</h3>${kv([
          ["Process", badge(data.status.botStatus, statusColor(data.status.botStatus))],
          ["Profile", badge(data.status.activeProfile, "cyan")],
          ["Watchlist", escapeHtml(data.status.universe.join(", "))],
          ["Preflight", badge("PAPER_READ_ONLY_PREFLIGHT_REQUIRED", "yellow")],
          ["Credential status", "present/not present only; no secrets"]
        ])}</div>
        <div class="card span-6"><h3>Supervisor Session</h3>${kv([
          ["Supervisor", badge(sup.state, statusColor(sup.state))],
          ["Session", escapeHtml(sup.sessionId || "none")],
          ["Paper start", badge(sup.paperStartAllowed ? "allowed" : "blocked", sup.paperStartAllowed ? "green" : "yellow")],
          ["PID", escapeHtml(sup.pid || "none")],
          ["Duration", escapeHtml(duration)],
          ["Wrapper stdout", escapeHtml(sup.wrapperStdoutPath || sup.stdoutPath || "not available")],
          ["Wrapper stderr", escapeHtml(sup.wrapperStderrPath || sup.stderrPath || "not available")],
          ["Child stdout", escapeHtml(sup.childStdoutPath || "not available")],
          ["Child stderr", escapeHtml(sup.childStderrPath || "not available")]
        ])}</div>
        ${renderPaperLaunchControl("activity")}
        <div class="card span-12"><h3>Governed PAPER Intents</h3>
          <div class="stack">
            <button class="intent-button paper" data-intent="paper-start" data-paper-form="activity" ${paperLaunchDisabledReason() ? "disabled" : ""}>
              Start bounded PAPER - ${paperLaunchDisabledReason() ? escapeHtml(paperLaunchDisabledReason()) : "server-authorized intent"}
            </button>
            <button class="intent-button paper" data-intent="paper-stop" ${sup.paperStopAllowed ? "" : "disabled"}>
              Stop PAPER - ${sup.paperStopAllowed ? "graceful supervisor request" : escapeHtml(sup.paperStopRefusalReason || "disabled")}
            </button>
            <button class="intent-button paper" disabled>Export run report - future server-authorized intent</button>
            <button class="intent-button live" disabled>Live start locked - LIVE_NOT_APPROVED</button>
            <div class="notice mono">Last intent: ${escapeHtml(sup.lastIntentResult || "none")}</div>
            <div class="notice mono">Last refused intent: ${sup.lastRefusedIntent ? tokenText(sup.lastRefusedIntent) : "none"}</div>
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
    return `
      ${header("AI Quant Research Chief", "Trading edge advisor for strategy, risk, TCA, provider readiness, and Codex packets.", ai.providerState)}
      <div class="grid">
        ${metric("Provider", ai.provider, statusColor(ai.providerState))}
        ${metric("State", ai.providerState, statusColor(ai.providerState))}
        ${metric("Pending Review", ai.pendingReviewCount || 0, ai.pendingReviewCount ? "yellow" : "gray")}
        ${metric("Can Execute", "false", "gray")}
        <div class="card span-12"><h3>Mission</h3>
          <div class="notice">I analyze trading edge, execution quality, risk, validation evidence, provider readiness, portfolio state, and operator readiness. I cannot trade, call broker, enable live, or change thresholds.</div>
        </div>
        <div class="card span-6"><h3>Control Tower</h3>${kv([
          ["Identity", escapeHtml("AI Quant Research Chief / Trading Edge Advisor")],
          ["Roles", escapeHtml("Strategy Decoder, Risk/Skeptic Officer, Execution/TCA Auditor, Paper Experiment Designer, Codex Packet Drafter")],
          ["Research items", escapeHtml(`${research.hypotheses || 0} hypotheses / ${research.experiments || 0} experiments`)],
          ["Promotion gates", escapeHtml(research.promotionGates || 0)]
        ])}</div>
        <div class="card span-6"><h3>Focused Quant Prompts</h3>
          <div class="stack">${AI_QUICK_PROMPTS.slice(0, 7).map((prompt) => badge(prompt, "gray")).join("")}</div>
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
    return `
      ${header("Provider Setup / Credential Readiness", "Enter local credentials, validate readiness, and keep raw secrets out of UI responses.", "NO SECRET VALUES")}
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
          ["Visible feedback states", escapeHtml("saving / saved / failed / validation passed / validation failed / configured / missing")],
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
          <div class="credential-grid">
            ${Object.entries(CREDENTIAL_FORMS).map(([providerId, form]) => `
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
                  <button class="intent-button live" data-credential-delete="${escapeHtml(providerId)}" ${backendConnected() ? "" : "disabled"}>Delete local</button>
                </div>
                <div class="notice mono credential-feedback">${escapeHtml(credentialActionStatus[providerId] || (backendConnected() ? "ready" : "backend unavailable; local secret store cannot be changed from static mock mode"))}</div>
              </div>
            `).join("")}
          </div>
          <div class="notice mono">Last credential action: ${escapeHtml(readiness.lastCredentialResult || "none")}</div>
        </div>
        <div class="card span-12"><h3>Providers</h3>${table(
          ["Provider", "Category", "Status", "Configured", "Required Env", "Source", "Fingerprint", "Can Trade", "Setup"],
          readiness.providers.map((provider) => [
            escapeHtml(provider.displayName || provider.providerId),
            badge(provider.category || "unknown", "gray"),
            badge(provider.status || "UNKNOWN", statusColor(provider.status || "UNKNOWN")),
            badge(String(provider.configured === true), provider.configured ? "green" : "yellow"),
            escapeHtml((provider.requiredEnvVars || []).join(", ") || "none"),
            escapeHtml((provider.envStatus || []).map((row) => row.source || "NOT_CONFIGURED").join(", ") || "none"),
            escapeHtml((provider.envStatus || []).map((row) => row.fingerprint || "missing").join(", ") || "none"),
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
    const configured = provider.configured ? "configured" : "missing";
    const sources = (provider.fields || []).map((field) => `${field.name}:${field.source}`).join(", ");
    return `${configured}; ${sources || "no fields"}`;
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
      ["global", "snapshot_intent_disabled", "Snapshot intent - disabled", "button", "DISABLED_WITH_REASON", "forbidden", "PAPER_INTENT_NOT_IMPLEMENTED", null, null],
      ["global", "live_locked", "Live locked", "button", "DISABLED_WITH_REASON", "forbidden", "LIVE_NOT_APPROVED", null, null],
      ["global", "ask_quant_chief", "Ask Quant Chief", "button", "WIRED", "read_only", "", null, "open_ai_drawer"],
      ["ai_overlay", "ai_question_textarea", "Ask a page-aware question", "input", "WIRED", "read_only", "", null, "local_page_context"],
      ["ai_overlay", "ai_ask", "Ask Quant Chief", "button", "WIRED", "local_advisory_write", "", "POST", "/operator/ai/ask"],
      ["ai_overlay", "ai_clear", "Clear", "button", "WIRED", "read_only", "", null, "local_clear"],
      ["ai_overlay", "ai_close", "Close", "button", "WIRED", "read_only", "", null, "local_close"],
      ["command", "paper_watchlist", "Watchlist", "input", "WIRED", "governed_paper_start", "", null, "paper_start_payload"],
      ["command", "paper_duration", "Duration", "select", "WIRED", "governed_paper_start", "", null, "paper_start_payload"],
      ["command", "paper_start", "Start Bounded PAPER Run", "button", disabledPaperReason ? "DISABLED_WITH_REASON" : "WIRED", "governed_paper_start", disabledPaperReason, "POST", "/operator/intent/paper/start"],
      ["command", "home_ai_question", "Home AI Quant Advisor question", "input", "WIRED", "read_only", "", null, "local_page_context"],
      ["command", "home_ai_ask", "Ask AI Quant Advisor", "button", backendConnected() ? "WIRED" : "DISABLED_WITH_REASON", "local_advisory_write", backendConnected() ? "" : "backend unavailable; deterministic local advisory only", "POST", "/operator/ai/ask"],
      ["command", "home_ai_clear", "Clear home AI question", "button", "WIRED", "read_only", "", null, "local_clear"],
      ["command", "home_ui_wiring_summary", "Buttons / Controls Status", "summary", "WIRED", "read_only", "", null, "local_inventory_summary"],
      ["activity", "paper_stop", "Stop PAPER", "button", data.supervisor.paperStopAllowed ? "WIRED" : "DISABLED_WITH_REASON", "governed_paper_start", data.supervisor.paperStopAllowed ? "" : (data.supervisor.paperStopRefusalReason || "no active PAPER runtime"), "POST", "/operator/intent/paper/stop"],
      ["activity", "export_run_report", "Export run report - future server-authorized intent", "button", "NOT_IMPLEMENTED_VISIBLE", "read_only", "server-authorized export intent not implemented", null, null],
      ["activity", "live_start_locked", "Live start locked - LIVE_NOT_APPROVED", "button", "DISABLED_WITH_REASON", "forbidden", "LIVE_NOT_APPROVED", null, null],
      ["positions", "positions_preview_table", "Current PAPER Positions", "table", "WIRED", "read_only", "", "GET", "/operator/positions"],
      ["positions", "open_orders_preview_table", "Open Orders", "table", "WIRED", "read_only", "cancel/replace unavailable in operator UI", "GET", "/operator/orders/open"],
      ["positions", "position_intelligence_table", "Position Intelligence", "table", "WIRED", "read_only", "", "GET", "/operator/positions/intelligence"],
      ["world", "world_poll", "Poll Alpaca News - read-only provider intent", "button", backendConnected() ? "WIRED" : "DISABLED_WITH_REASON", "read_only", backendConnected() ? "" : "backend unavailable", "POST", "/operator/intent/world-awareness/poll"],
      ["ai", "ai_analyze", "Run advisory AI analysis", "button", backendConnected() ? "WIRED" : "DISABLED_WITH_REASON", "local_advisory_write", backendConnected() ? "" : "backend unavailable", "POST", "/operator/ai/analyze"],
      ["ai", "ai_quant_review", "Queue Quant Chief review", "button", backendConnected() ? "WIRED" : "DISABLED_WITH_REASON", "local_advisory_write", backendConnected() ? "" : "backend unavailable", "POST", "/operator/ai/quant-review"],
      ["historical", "historical_run", "Run Historical Test", "button", backendConnected() ? "WIRED" : "DISABLED_WITH_REASON", "read_only", backendConnected() ? "" : "backend unavailable", "POST", "/operator/historical-tests/run"],
      ["runs", "open_historical_tests", "Open Historical Tests", "button", "WIRED", "read_only", "", null, "local_navigation"],
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
      notImplemented: counts.NOT_IMPLEMENTED_VISIBLE || 0,
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
    return `
      ${header("Diagnostics", "Environment, repo, and local runtime sanity without secrets.", sourceLabel())}
      <div class="card">${kv([
        ["Backend source", badge(sourceLabel(), dataSourceColor())],
        ["Backend fetch", escapeHtml(data.meta.backendStatus || "not inspected")],
        ["Failed endpoints", data.meta.fetchFailures && data.meta.fetchFailures.length ? tokenText(data.meta.fetchFailures.join(", ")) : "none"],
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
      ])}</div>
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
      ${header("Live Readiness / Activation Gate", "Read-only v1. Live represented but locked.", l.state)}
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
      fills_observed: run.fillsObserved,
      tca_status: run.tcaStatus,
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
        `last_refused_intent=${data.supervisor.lastRefusedIntent || "none"}`
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
        last_refused_intent: data.supervisor.lastRefusedIntent || "none"
      },
      selected_run: latestRun,
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

  function renderAiChiefOverlay() {
    const host = document.querySelector(".ai-chief-global");
    if (!host) return;
    const context = buildAiChiefContext(aiSelectedQuestion);
    const providerState = data.ai.providerState || "AI_DISABLED";
    const providerLabel = `${data.ai.provider || "disabled"} / ${providerState}`;
    const response = aiOverlayResponse || buildAiOverlayAdvisory(aiQuestionText || aiSelectedQuestion);
    host.innerHTML = `
      <button class="ai-chief-fab ${aiOverlayOpen ? "open" : ""}" type="button" data-ai-chief-open aria-expanded="${aiOverlayOpen ? "true" : "false"}">
        <span>Ask Quant Chief</span>
        <span class="ai-chief-fab-sub">${escapeHtml(screenTitle(activeScreenId))}</span>
      </button>
      <div class="ai-chief-backdrop ${aiOverlayOpen ? "open" : ""}" data-ai-chief-close></div>
      <section class="ai-chief-drawer ${aiOverlayOpen ? "open" : ""}" aria-hidden="${aiOverlayOpen ? "false" : "true"}" aria-label="Global AI Chief advisory drawer">
        <div class="ai-chief-panel">
          <div class="ai-chief-header">
            <div>
              <div class="ai-chief-title">AI Quant Research Chief</div>
              <div class="muted mono">${escapeHtml(providerLabel)} / ADVISORY_ONLY</div>
            </div>
            <button class="ai-chief-close" type="button" data-ai-chief-close aria-label="Close AI Chief">Close</button>
          </div>
          <div class="ai-boundary">
            ${badge("cannot trade", "red")}
            ${badge("cannot call broker", "red")}
            ${badge("cannot enable live", "red")}
            ${badge("cannot change thresholds", "red")}
            ${badge("can_execute=false", "gray")}
          </div>
          <div class="notice ai-mission">I analyze trading edge, execution quality, risk, validation evidence, provider readiness, portfolio state, and operator readiness. I cannot trade, call broker, enable live, or change thresholds.</div>
          <div class="ai-chief-body">
            ${renderAiContextPreview(context)}
            <div class="ai-question-bank" aria-label="AI Chief quick questions">
              ${AI_QUICK_PROMPTS.map((prompt) => `
                <button class="ai-question ${prompt === aiSelectedQuestion ? "active" : ""}" type="button" data-ai-chief-prompt="${escapeHtml(prompt)}">
                  ${escapeHtml(prompt)}
                </button>
              `).join("")}
            </div>
            <div class="ai-ask-box">
              <label for="ai-chief-question">Ask a page-aware question</label>
              <textarea id="ai-chief-question" data-ai-chief-question rows="4" placeholder="Ask about edge, risk, TCA, provider readiness, launch blockers, or latest run evidence.">${escapeHtml(aiQuestionText || "")}</textarea>
              <div class="button-row">
                <button class="intent-button paper" type="button" data-ai-chief-ask ${aiOverlayBusy ? "disabled" : ""}>
                  ${aiOverlayBusy ? "Asking..." : "Ask Quant Chief"}
                </button>
                <button class="intent-button paper" type="button" data-ai-chief-clear ${aiOverlayBusy ? "disabled" : ""}>Clear</button>
                <button class="intent-button live" type="button" data-ai-chief-close>Close</button>
              </div>
              ${aiOverlayError ? `<div class="notice error">Error: ${escapeHtml(aiOverlayError)}</div>` : ""}
            </div>
            <div class="ai-response">
              <div class="split">
                <h3>Advisory Response</h3>
                ${badge(providerState, statusColor(providerState))}
              </div>
              <pre>${escapeHtml(response)}</pre>
            </div>
            <div class="ai-chief-actions">
              <button class="intent-button paper" type="button" data-ai-chief-analyze ${backendConnected() && !aiOverlayBusy ? "" : "disabled"}>
                ${aiOverlayBusy ? "Queueing advisory analysis..." : "Queue advisory analysis"}
              </button>
              <button class="intent-button live" type="button" disabled>Broker execution unavailable to AI</button>
            </div>
            <div class="notice mono">
              ${backendConnected()
                ? "Ask uses /operator/ai/ask. If a key is configured but real model calls are not wired, the backend returns DETERMINISTIC_FALLBACK_NO_MODEL_CALL instead of pretending a model answered. Analyze uses the governed AI endpoint and governance queue."
                : "Backend unreachable: overlay can show sample context only and will not queue runtime recommendations."}
            </div>
          </div>
        </div>
      </section>
    `;
  }

  function setAiOverlayOpen(open) {
    aiOverlayOpen = open;
    renderAiChiefOverlay();
  }

  function selectAiQuestion(question) {
    aiSelectedQuestion = question;
    aiQuestionText = question;
    aiOverlayResponse = buildAiOverlayAdvisory(question);
    aiOverlayError = "";
    aiOverlayOpen = true;
    renderAiChiefOverlay();
  }

  function clearAiQuestion() {
    aiQuestionText = "";
    aiOverlayResponse = "";
    aiOverlayError = "";
    aiOverlayOpen = true;
    renderAiChiefOverlay();
  }

  function formatAiAskResult(result) {
    return [
      `${result.response_source || "DETERMINISTIC_FALLBACK_NO_MODEL_CALL"} / ${result.provider_state || "AI_DISABLED"}`,
      result.response || "No advisory response returned.",
      `can_execute=${String(result.can_execute === true ? "true" : "false")}`,
      `broker_call_occurred=${String(result.broker_call_occurred === true ? "true" : "false")}`,
      `trading_mutation_occurred=${String(result.trading_mutation_occurred === true ? "true" : "false")}`,
      `live_enabled=${String(result.live_enabled === true ? "true" : "false")}`,
      `real_money_enabled=${String(result.real_money_enabled === true ? "true" : "false")}`
    ].join("\n");
  }

  async function askAiChiefQuestion() {
    const input = document.querySelector("[data-ai-chief-question]");
    const question = String((input && input.value) || aiQuestionText || aiSelectedQuestion || "").trim();
    aiQuestionText = question;
    aiSelectedQuestion = AI_QUICK_PROMPTS.includes(question) ? question : aiSelectedQuestion;
    aiOverlayError = "";
    if (!backendConnected()) {
      aiOverlayResponse = buildAiOverlayAdvisory(question);
      aiOverlayOpen = true;
      renderAiChiefOverlay();
      return;
    }
    aiOverlayBusy = true;
    renderAiChiefOverlay();
    try {
      const context = buildAiChiefContext(question);
      const result = await postIntent("/operator/ai/ask", {
        question,
        page_id: context.page_id,
        page_context: context,
        advisory_only: true
      });
      aiOverlayResponse = formatAiAskResult(result);
    } catch (error) {
      aiOverlayError = error.message || error.name || "ai_ask_failed";
      aiOverlayResponse = buildAiOverlayAdvisory(question);
    } finally {
      aiOverlayBusy = false;
      aiOverlayOpen = true;
      renderAiChiefOverlay();
    }
  }

  function selectHomeAiQuestion(question) {
    homeAiQuestionText = question;
    homeAiError = "";
    homeAiResponse = buildAiOverlayAdvisory(question);
    renderScreens(activeScreenId);
    renderRail();
    renderAiChiefOverlay();
  }

  function clearHomeAiQuestion() {
    homeAiQuestionText = "";
    homeAiResponse = "";
    homeAiError = "";
    renderScreens(activeScreenId);
    renderRail();
    renderAiChiefOverlay();
  }

  async function askHomeAiQuestion() {
    const input = document.querySelector("[data-home-ai-question]");
    const question = String((input && input.value) || homeAiQuestionText || "").trim();
    homeAiQuestionText = question;
    homeAiError = "";
    if (!backendConnected()) {
      homeAiResponse = buildAiOverlayAdvisory(question);
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
      context.page_id = "command";
      context.page_title = "Command Center";
      const result = await postIntent("/operator/ai/ask", {
        question,
        page_id: "command",
        page_context: context,
        advisory_only: true
      });
      homeAiResponse = formatAiAskResult(result);
    } catch (error) {
      homeAiError = error.message || error.name || "home_ai_ask_failed";
      homeAiResponse = buildAiOverlayAdvisory(question);
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
      const path = aiSelectedQuestion === "Draft a Codex packet."
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
      aiOverlayResponse = [
        "Governed AI Quant Chief endpoint returned through the advisory queue.",
        `Status: ${result.status || "QUEUED"}.`,
        `Recommendation: ${recommendation.recommendation_type || "OBSERVATION"}.`,
        `Summary: ${recommendation.summary || "No summary returned."}`,
        result.draft_packet ? `Draft packet:\n${result.draft_packet}` : "",
        `can_execute=${String(recommendation.can_execute === true ? "true" : "false")}.`,
        "Approving a PAPER research recommendation does not start PAPER automatically."
      ].filter(Boolean).join("\n");
      data = await loadData();
      data.ai.lastAnalyzeResult = `${result.status || "QUEUED"}: ${recommendation.recommendation_type || "OBSERVATION"}`;
      renderTopBar();
      renderScreens(selectedScreen);
      renderRail();
    } catch (error) {
      aiOverlayResponse = `FAILED: ${error.message || error.name || "ai_analyze_error"}\nNo broker or trading mutation was requested by the UI.`;
    } finally {
      aiOverlayBusy = false;
      aiOverlayOpen = true;
      renderAiChiefOverlay();
    }
  }

  function renderRail() {
    const critical = data.alerts.filter((alert) => alert.severity === "SAFETY_CRITICAL").length;
    const pendingAI = data.ai.pendingReviewCount || 0;
    document.querySelector(".rail").innerHTML = `
      <div class="card rail-card"><h3>Current Alerts</h3>
        <div class="stack">
          ${badge(sourceLabel(), dataSourceColor())}
          ${badge("LIVE_LOCKED", "red")}
          ${badge("REAL_MONEY_BLOCKED", "red")}
          ${badge(`${data.alerts.length} watchdog`, data.alerts.length ? "yellow" : "gray")}
          ${badge(`${critical} critical`, critical ? "red" : "gray")}
        </div>
      </div>
      <div class="card rail-card"><h3>Dominant Blocker</h3>
        <div class="mono">${tokenText(data.status.dominantBlocker)}</div>
      </div>
      <div class="card rail-card"><h3>Last Decision</h3>
        <div>${escapeHtml(data.status.lastDecision)}</div>
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
    main.innerHTML = screens.map(([id]) => `<section class="screen" id="screen-${id}">${renderers[id]()}</section>`).join("");
    window.PK_OPERATOR_UI_CONTROL_INVENTORY = buildUiControlInventory();
    showScreen(selectedId || activeScreenId || "command");
  }

  function backendFetchTimeoutMs(path) {
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

  async function fetchJson(path) {
    const timeoutMs = backendFetchTimeoutMs(path);
    const controller = new AbortController();
    let timedOut = false;
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
    }
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
      message: pick(portfolio.message, ""),
      empty: portfolio.empty === true,
      dataFreshnessTs: pick(portfolio.data_freshness_ts, null),
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
        brokerLocalReconciliationStatus: pick(summary.broker_local_reconciliation_status, "UNKNOWN")
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

  function normalizeBackendData(payload) {
    const next = clone(mockData);
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
    const aiRecommendations = payload.aiRecommendations || {};
    const providers = payload.providers || {};
    const providerReadiness = payload.providerReadiness || {};
    const credentialsProviders = payload.credentialsProviders || {};
    const portfolio = payload.portfolio || {};
    const launchReadiness = payload.launchReadiness || {};
    const research = payload.research || {};
    const evidenceGraph = payload.evidenceGraph || {};
    const historicalTests = payload.historicalTests || {};
    const endpointFailures = payload.endpointFailures || {};
    const supervisor = status.supervisor || latestRun || {};
    const activeSession = supervisor.active_session || {};
    const latestSession = supervisor.latest_session || latestRun.latest_session || {};
    const hasActiveSession = Boolean(activeSession && activeSession.session_id);
    const latestRefused = latestSession.status === "REFUSED" || runtime.process_state === "REFUSED";
    const latestRefusalReason = pick(latestSession.refusal_reason || runtime.refusal_reason, null);
    const latestRefusedIntent = latestRefused
      ? `paper_start: ${latestRefusalReason || "REFUSED"}${latestSession.session_id ? ` (${latestSession.session_id})` : ""}`
      : null;

    next.meta.dataSource = "OPERATOR_BACKEND";
    next.meta.buildMode = "operator_backend_supervisor_ready";
    next.meta.runtimeCommit = pick(runtime.runtime_commit, diagnostics.git_commit || "unknown");
    next.meta.lastUpdated = pick(status.updated_at, new Date().toISOString());

    const backendBotStatus = pick(status.bot_status, "NO_ACTIVE_RUNTIME_ATTACHED");
    next.status.botStatus = backendBotStatus === "NO_ACTIVE_RUNTIME_ATTACHED" ? "NO_ACTIVE_PAPER_RUN" : backendBotStatus;
    next.status.runtimeMode = pick(status.runtime_mode, "PAPER");
    next.status.capabilityState = pick(status.capability_state || status.mode_state, "PAPER_ENABLED");
    next.status.activeProfile = pick(status.active_profile || profile.active_threshold_profile, "UNKNOWN_NO_ACTIVE_RUNTIME");
    next.status.broker = pick(status.broker, "UNKNOWN_NO_ACTIVE_RUNTIME");
    next.status.endpoint = pick(status.endpoint, "UNKNOWN_NO_ACTIVE_RUNTIME");
    next.status.marketData = pick(status.market_data, "UNKNOWN_NO_ACTIVE_RUNTIME");
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
    next.status.dominantBlocker = pick(status.dominant_blocker, "NO_ACTIVE_RUNTIME_ATTACHED");
    next.status.lastDecision = hasActiveSession
      ? "Decision detail unavailable from backend summary"
      : (latestRefusedIntent ? `No active PAPER run; last refused intent ${latestRefusedIntent}` : "No active PAPER run");
    next.supervisor.state = pick(supervisor.state, "UNKNOWN");
    next.supervisor.sessionId = hasActiveSession ? pick(activeSession.session_id || supervisor.active_session_id, "none") : "none";
    next.supervisor.pid = hasActiveSession ? pick(activeSession.pid || runtime.pid, "none") : "none";
    next.supervisor.processState = hasActiveSession ? pick(activeSession.status || runtime.process_state, "UNKNOWN") : "NO_ACTIVE_PAPER_RUN";
    next.supervisor.durationSeconds = hasActiveSession ? pick(activeSession.duration_seconds || runtime.duration_seconds, null) : null;
    next.supervisor.profile = hasActiveSession ? pick(activeSession.profile || status.active_profile, "UNKNOWN_NO_ACTIVE_RUNTIME") : "UNKNOWN_NO_ACTIVE_RUNTIME";
    next.supervisor.watchlist = hasActiveSession ? pick(activeSession.watchlist || status.universe, []) : [];
    next.supervisor.stdoutPath = hasActiveSession ? pick(activeSession.stdout_path || runtime.stdout_path, "not available") : "not available";
    next.supervisor.stderrPath = hasActiveSession ? pick(activeSession.stderr_path || runtime.stderr_path, "not available") : "not available";
    next.supervisor.wrapperStdoutPath = hasActiveSession ? pick(activeSession.wrapper_stdout_path || runtime.wrapper_stdout_path, next.supervisor.stdoutPath) : "not available";
    next.supervisor.wrapperStderrPath = hasActiveSession ? pick(activeSession.wrapper_stderr_path || runtime.wrapper_stderr_path, next.supervisor.stderrPath) : "not available";
    next.supervisor.childStdoutPath = hasActiveSession ? pick(activeSession.child_stdout_path || runtime.child_stdout_path, "not available") : "not available";
    next.supervisor.childStderrPath = hasActiveSession ? pick(activeSession.child_stderr_path || runtime.child_stderr_path, "not available") : "not available";
    next.supervisor.paperStartAllowed = supervisor.paper_start_allowed === true || runtime.paper_start_allowed === true;
    next.supervisor.paperStopAllowed = supervisor.paper_stop_allowed === true || runtime.paper_stop_allowed === true;
    next.supervisor.paperStartRefusalReason = pick(supervisor.paper_start_refusal_reason || runtime.paper_start_refusal_reason, null);
    next.supervisor.paperStopRefusalReason = pick(supervisor.paper_stop_refusal_reason || runtime.paper_stop_refusal_reason, null);
    next.supervisor.lastRefusedIntent = latestRefusedIntent;

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
        fillsObserved: pick(run.fills && run.fills.observed, 0),
        tcaStatus: pick(run.tca && run.tca.status, "UNKNOWN"),
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
        paperStartAllowed: launchReadiness.paper_start_allowed === true,
        safeStopStatus: pick(launchReadiness.safe_stop_status, "UNKNOWN"),
        portfolioReadAvailability: pick(launchReadiness.portfolio_read_availability, "UNKNOWN"),
        backendDegradedReasons: Array.isArray(launchReadiness.backend_degraded_reasons) ? launchReadiness.backend_degraded_reasons : []
      };
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
    next.fills = [
      {
        fillId: "read_only_backend_summary",
        symbol: "all",
        side: "none",
        quantity: String(pick(fills.local_fills, 0)),
        price: "not displayed by backend v1",
        source: pick(fills.source, "NO_ACTIVE_RUNTIME_ATTACHED"),
        hydrationStatus: `fills=${pick(fills.fill_hydration_count, 0)} fee=${pick(fills.broker_fee_hydration_count, 0)} pending=${pick(fills.broker_fee_hydration_pending_count, 0)}`,
        feeStatus: pick(fills.fee_status, "FEE_PENDING_BROKER_ACTIVITY"),
        feeSource: pick(fills.fee_source, "UNAVAILABLE"),
        tca: pick(tca.execution_quality_verdict, "UNKNOWN_NO_ACTIVE_RUNTIME"),
        reason: `fill_conflicts=${pick(fills.fill_hydration_conflict_count, 0)} fee_conflicts=${pick(fills.broker_fee_hydration_conflict_count, 0)}`
      }
    ];

    return next;
  }

  async function loadData() {
    let status;
    try {
      status = await fetchJson("/operator/status");
    } catch (error) {
      logBackendFetchFailure("/operator/status", error);
      const fallback = clone(mockData);
      fallback.meta.dataSource = "MOCK_DATA";
      fallback.meta.backendStatus = `backend unavailable: ${describeFetchFailure("/operator/status", error)}`;
      fallback.meta.fetchFailures = [describeFetchFailure("/operator/status", error)];
      return fallback;
    }

    const endpoints = [
      ["health", "/operator/health"],
      ["operatorReadiness", "/operator/readiness"],
      ["storage", "/operator/storage"],
      ["runtime", "/operator/runtime"],
      ["profile", "/operator/profile"],
      ["universe", "/operator/universe"],
      ["readiness", "/operator/readiness/live"],
      ["diagnostics", "/operator/diagnostics"],
      ["contracts", "/operator/contracts"],
      ["latestRun", "/operator/latest-run"],
      ["orders", "/operator/orders-summary"],
      ["fills", "/operator/fills-summary"],
      ["tca", "/operator/tca-summary"],
      ["audit", "/operator/audit-summary"],
      ["world", "/operator/world-awareness"],
      ["worldRuntime", "/operator/world-awareness/runtime"],
      ["runs", "/operator/runs"],
      ["explain", "/operator/explain/latest"],
      ["actionCenter", "/operator/action-center"],
      ["pnlDashboard", "/operator/pnl"],
      ["tcaDashboard", "/operator/tca"],
      ["alerts", "/operator/alerts"],
      ["systemMap", "/operator/system-map"],
      ["aiStatus", "/operator/ai/status"],
      ["aiRecommendations", "/operator/ai/recommendations"],
      ["providers", "/operator/providers"],
      ["providerReadiness", "/operator/providers/readiness"],
      ["credentialsProviders", "/operator/credentials/providers"],
      ["portfolio", "/operator/portfolio"],
      ["launchReadiness", "/operator/launch-readiness"],
      ["research", "/operator/research"],
      ["evidenceGraph", "/operator/research/evidence-graph"],
      ["historicalTests", "/operator/historical-tests"]
    ];
    const payload = { status };
    const failures = [];
    const endpointFailures = {};
    await Promise.all(endpoints.map(async ([key, path]) => {
      try {
        payload[key] = await fetchJson(path);
      } catch (error) {
        if (error && error.lifecycleAbort === true) {
          logBackendFetchAbort(path, error);
          return;
        }
        const failure = describeFetchFailure(path, error);
        logBackendFetchFailure(path, error);
        failures.push(failure);
        endpointFailures[key] = failure;
      }
    }));
    payload.endpointFailures = endpointFailures;

    const normalized = normalizeBackendData(payload);
    normalized.meta.dataSource = failures.length ? "PARTIAL_BACKEND" : "OPERATOR_BACKEND";
    normalized.meta.backendStatus = failures.length
      ? `status connected; ${failures.length} secondary endpoint(s) failed`
      : "backend connected";
    normalized.meta.fetchFailures = failures;
    return normalized;
  }

  async function boot() {
    data = await loadData();
    renderTopBar();
    renderNav();
    renderScreens("command");
    renderRail();
    renderAiChiefOverlay();
  }

  async function requestJson(path, options) {
    const opts = options || {};
    const response = await fetch(`${operatorApiBase()}${path}`, {
      method: opts.method || "GET",
      headers: { "Content-Type": "application/json" },
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body || {})
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }

  async function postIntent(path, body) {
    return requestJson(path, { method: "POST", body });
  }

  function paperRunFormValues(formId) {
    const card = document.querySelector(`[data-paper-form-card="${formId || "command"}"]`) || document.querySelector("[data-paper-form-card]");
    const watchlistRaw = ((card && card.querySelector("[data-paper-watchlist]")) || {}).value || "BTC/USD,ETH/USD,SOL/USD";
    const durationRaw = ((card && card.querySelector("[data-paper-duration]")) || {}).value || "300";
    const profileAlpha = ((card && card.querySelector("[data-paper-profile-alpha]")) || {}).checked !== false;
    const confirmPaper = ((card && card.querySelector("[data-paper-confirm-paper]")) || {}).checked === true;
    const confirmLiveLocked = ((card && card.querySelector("[data-paper-confirm-live-locked]")) || {}).checked === true;
    const confirmRealMoneyBlocked = ((card && card.querySelector("[data-paper-confirm-real-money-blocked]")) || {}).checked === true;
    const confirmNoManualTrades = ((card && card.querySelector("[data-paper-confirm-no-manual-trades]")) || {}).checked === true;
    return {
      watchlist: watchlistRaw.split(",").map((item) => item.trim().toUpperCase()).filter(Boolean),
      durationSeconds: Number.parseInt(durationRaw, 10) || 300,
      profile: profileAlpha ? "PAPER_EXPLORATION_ALPHA" : data.status.activeProfile,
      confirmPaper,
      confirmLiveLocked,
      confirmRealMoneyBlocked,
      confirmNoManualTrades
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
      if (intent === "paper-start") {
        const form = paperRunFormValues(sourceButton && sourceButton.dataset ? sourceButton.dataset.paperForm : "command");
        if (!form.confirmPaper || !form.confirmLiveLocked || !form.confirmRealMoneyBlocked || !form.confirmNoManualTrades) {
          window.alert("Confirm PAPER-only, live locked, real-money blocked, and no manual trades before requesting the governed PAPER start.");
          return;
        }
        const confirmed = window.confirm(
          `Request bounded PAPER start?\n\nProfile: ${form.profile}\nWatchlist: ${form.watchlist.join(", ")}\nDuration: ${form.durationSeconds} seconds\n\nNo live trading or manual order will be sent by the UI.`
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
      }
      if (intent === "paper-stop") {
        const confirmed = window.confirm("Request governed PAPER stop? This does not send broker orders or flatten positions from the UI.");
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
    credentialActionStatus[providerId] = `${action === "save" ? "saving" : action === "validate" ? "validating" : "deleting"}...`;
    renderScreens(activeScreenId);
    try {
      let result;
      if (action === "save") {
        const credentials = credentialFormValues(providerId);
        if (!Object.keys(credentials).length) {
          credentialActionStatus[providerId] = "failed: no credential fields entered";
          window.alert("Enter at least one credential field before saving.");
          renderScreens(activeScreenId);
          return;
        }
        result = await postIntent("/operator/credentials/save", {
          provider_id: providerId,
          credentials
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

  document.addEventListener("click", (event) => {
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
    const aiPrompt = event.target.closest("[data-ai-chief-prompt]");
    if (aiPrompt) {
      selectAiQuestion(aiPrompt.dataset.aiChiefPrompt);
      return;
    }
    const aiAnalyze = event.target.closest("[data-ai-chief-analyze]");
    if (aiAnalyze && !aiAnalyze.disabled) {
      runAiOverlayAnalyze();
      return;
    }
    const aiAsk = event.target.closest("[data-ai-chief-ask]");
    if (aiAsk && !aiAsk.disabled) {
      askAiChiefQuestion();
      return;
    }
    const aiClear = event.target.closest("[data-ai-chief-clear]");
    if (aiClear && !aiClear.disabled) {
      clearAiQuestion();
      return;
    }
    const homeAiPrompt = event.target.closest("[data-home-ai-prompt]");
    if (homeAiPrompt) {
      selectHomeAiQuestion(homeAiPrompt.dataset.homeAiPrompt);
      return;
    }
    const homeAiAsk = event.target.closest("[data-home-ai-ask]");
    if (homeAiAsk && !homeAiAsk.disabled) {
      askHomeAiQuestion();
      return;
    }
    const homeAiClear = event.target.closest("[data-home-ai-clear]");
    if (homeAiClear && !homeAiClear.disabled) {
      clearHomeAiQuestion();
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
