(function () {
  "use strict";

  const mockData = window.PK_MOCK_DATA;
  let data = clone(mockData);
  const screens = [
    ["command", "Command Center"],
    ["action", "Action Center"],
    ["runs", "Run Archive"],
    ["pnl", "P&L / Net Profit"],
    ["positions", "Positions & Orders"],
    ["activity", "Bot Activity Control"],
    ["decision", "Signal & Decision Lab"],
    ["market", "Market Data Truth"],
    ["risk", "Risk & Governor"],
    ["alerts", "Watchdog Alerts"],
    ["ai", "AI Chief Operator"],
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
    "Explain this page",
    "What should I care about?",
    "What is unsafe or missing?",
    "What is the next safest action?",
    "Draft Codex packet",
    "Review latest run",
    "Critique TCA/NetEdge evidence"
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
  let activeScreenId = "command";
  let aiOverlayOpen = false;
  let aiSelectedQuestion = AI_QUICK_PROMPTS[0];
  let aiOverlayResponse = "";
  let aiOverlayBusy = false;

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
    if (v.includes("PASS") || v.includes("ALLOW") || v.includes("CLEAN") || v.includes("RUNNING") || v.includes("PAPER")) return "green";
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
    if (data.meta.dataSource === "PARTIAL_BACKEND") return "PARTIAL_BACKEND / status connected";
    return "MOCK DATA / sample";
  }

  function sourceSubtext() {
    if (data.meta.dataSource === "OPERATOR_BACKEND") return "OPERATOR_BACKEND / runtime truth";
    if (data.meta.dataSource === "PARTIAL_BACKEND") return "PARTIAL_BACKEND / secondary endpoint degraded";
    return "MOCK DATA / sample fallback";
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
    return `
      ${header("Command Center", "Operational truth, authority, and current runtime safety.", s.safetyVerdict)}
      <div class="grid">
        ${metric("Bot Status", s.botStatus, "green")}
        ${metric("Mode", s.runtimeMode, "green")}
        ${metric("Live", "LOCKED", "red")}
        ${metric("Real-money", "BLOCKED", "red")}
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
    return `
      ${header("Positions & Orders", "Broker-backed position truth, OMS lifecycle, and reconciliation.", "RECONCILED")}
      <div class="grid">
        <div class="card span-12"><h3>Broker-backed Positions</h3>${table(
          ["Symbol", "Asset", "Quantity", "Source", "MovingFloor", "Exit Eligibility"],
          data.positions.map((p) => [p.symbol, p.assetClass, p.brokerQuantity, badge(p.source, "green"), p.movingFloor, p.exitEligibility])
        )}</div>
        <div class="card span-12"><h3>Orders</h3>${table(
          ["Client Order ID", "Symbol", "Side", "Action", "State", "Broker", "Reconciliation"],
          data.orders.map((o) => [o.clientOrderId, o.symbol, o.side, o.action, badge(o.state, statusColor(o.state)), o.brokerStatus, badge(o.reconciliation, "green")])
        )}</div>
      </div>
    `;
  }

  function renderActivity() {
    const sup = data.supervisor;
    const duration = sup.durationSeconds === null || sup.durationSeconds === undefined ? "not active" : `${sup.durationSeconds}s`;
    return `
      ${header("Bot Activity Control", "Governed PAPER intents only. Live and manual trading remain locked.", sourceLabel())}
      <div class="grid">
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
        <div class="card span-12"><h3>Governed PAPER Intents</h3>
          <div class="stack">
            <button class="intent-button paper" data-intent="paper-start" ${sup.paperStartAllowed ? "" : "disabled"}>
              Start bounded PAPER - ${sup.paperStartAllowed ? "server-authorized intent" : escapeHtml(sup.paperStartRefusalReason || "disabled")}
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
    return `
      ${header("AI Chief Operator", "Advisory-only model gateway and governance queue.", ai.providerState)}
      <div class="grid">
        ${metric("Provider", ai.provider, statusColor(ai.providerState))}
        ${metric("State", ai.providerState, statusColor(ai.providerState))}
        ${metric("Pending Review", ai.pendingReviewCount || 0, ai.pendingReviewCount ? "yellow" : "gray")}
        ${metric("Can Execute", "false", "gray")}
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
            <div class="notice mono">Last AI result: ${escapeHtml(ai.lastAnalyzeResult || "none")}</div>
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

  function renderDiagnostics() {
    const d = data.diagnostics;
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

    if (question === "Draft Codex packet") {
      return [
        "Local redacted context preview, not a real model response.",
        sourceWarning,
        `Draft packet focus: inspect ${context.page_title}, preserve live/real-money locks, keep can_execute=false, do not touch broker/execution/OMS/strategy, and use only redacted operator summaries.`,
        `Primary evidence to include: ${context.page_summary.slice(0, 4).join("; ")}.`,
        "Next safest action: ask for a scoped frontend/advisory repair unless backend truth is missing."
      ].join("\n");
    }

    if (question === "Review latest run") {
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

    if (question === "Critique TCA/NetEdge evidence") {
      return [
        "Local redacted context preview, not a real model response.",
        sourceWarning,
        `NetEdge summary: ${data.pnl.netEdge || "UNKNOWN"}; TCA status: ${data.tcaDashboard.status || "UNKNOWN"}.`,
        `Fee/P&L truth labels: realized=${data.pnl.realizedPnl.source}, fees=${data.pnl.fees.source}.`,
        "Do not invent P&L, fees, fills, slippage, or TCA. Unknown must remain unknown."
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
    const response = aiOverlayResponse || buildAiOverlayAdvisory(aiSelectedQuestion);
    host.innerHTML = `
      <button class="ai-chief-fab ${aiOverlayOpen ? "open" : ""}" type="button" data-ai-chief-open aria-expanded="${aiOverlayOpen ? "true" : "false"}">
        <span>Ask AI Chief</span>
        <span class="ai-chief-fab-sub">${escapeHtml(screenTitle(activeScreenId))}</span>
      </button>
      <div class="ai-chief-backdrop ${aiOverlayOpen ? "open" : ""}" data-ai-chief-close></div>
      <section class="ai-chief-drawer ${aiOverlayOpen ? "open" : ""}" aria-hidden="${aiOverlayOpen ? "false" : "true"}" aria-label="Global AI Chief advisory drawer">
        <div class="ai-chief-panel">
          <div class="ai-chief-header">
            <div>
              <div class="ai-chief-title">AI Chief Operator</div>
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
          <div class="ai-chief-body">
            ${renderAiContextPreview(context)}
            <div class="ai-question-bank" aria-label="AI Chief quick questions">
              ${AI_QUICK_PROMPTS.map((prompt) => `
                <button class="ai-question ${prompt === aiSelectedQuestion ? "active" : ""}" type="button" data-ai-chief-prompt="${escapeHtml(prompt)}">
                  ${escapeHtml(prompt)}
                </button>
              `).join("")}
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
                ? "Analyze uses the governed AI endpoint and governance queue. Provider disabled/mock states remain clearly labeled."
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
    aiOverlayResponse = buildAiOverlayAdvisory(question);
    aiOverlayOpen = true;
    renderAiChiefOverlay();
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
      const result = await postIntent("/operator/ai/analyze", {
        requested_by: "operator_ui_global_overlay",
        advisory_only: true,
        prompt: aiSelectedQuestion,
        page_id: context.page_id,
        page_context: context
      });
      const recommendation = result.recommendation || {};
      aiOverlayResponse = [
        "Governed AI endpoint returned through the advisory queue.",
        `Status: ${result.status || "QUEUED"}.`,
        `Recommendation: ${recommendation.recommendation_type || "OBSERVATION"}.`,
        `Summary: ${recommendation.summary || "No summary returned."}`,
        `can_execute=${String(recommendation.can_execute === true ? "true" : "false")}.`,
        "Approving a PAPER research recommendation does not start PAPER automatically."
      ].join("\n");
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
      pnl: renderPnl,
      positions: renderPositions,
      activity: renderActivity,
      decision: renderDecision,
      market: renderMarket,
      risk: renderRisk,
      alerts: renderAlerts,
      ai: renderAI,
      system: renderSystem,
      audit: renderAudit,
      world: renderWorld,
      diagnostics: renderDiagnostics,
      live: renderLive
    };
    main.innerHTML = screens.map(([id]) => `<section class="screen" id="screen-${id}">${renderers[id]()}</section>`).join("");
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
      ["aiRecommendations", "/operator/ai/recommendations"]
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

  async function postIntent(path, body) {
    const response = await fetch(`${operatorApiBase()}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {})
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }

  async function handleIntent(intent) {
    if (!backendConnected()) return;
    try {
      let message = "none";
      if (intent === "paper-start") {
        const confirmed = window.confirm(
          "Request bounded PAPER start?\n\nProfile: PAPER_EXPLORATION_ALPHA\nWatchlist: BTC/USD, ETH/USD, SOL/USD\nDuration: 300 seconds\n\nNo live trading or manual order will be sent by the UI."
        );
        if (!confirmed) return;
        const result = await postIntent("/operator/intent/paper/start", {
          mode: "PAPER",
          profile: "PAPER_EXPLORATION_ALPHA",
          duration_seconds: 300,
          watchlist: ["BTC/USD", "ETH/USD", "SOL/USD"],
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
      const selectedScreen = activeScreenId;
      data = await loadData();
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
    const button = event.target.closest("[data-intent]");
    if (!button || button.disabled) return;
    handleIntent(button.dataset.intent);
  });

  document.addEventListener("DOMContentLoaded", boot);
})();
