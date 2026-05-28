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

  function badge(text, color) {
    return `<span class="badge ${color || "gray"}">${escapeHtml(String(text))}</span>`;
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
    if (v.includes("PASS") || v.includes("ALLOW") || v.includes("CLEAN") || v.includes("RUNNING") || v.includes("PAPER")) return "green";
    if (v.includes("UNKNOWN") || v.includes("MISSING") || v.includes("DEGRADED") || v.includes("NO_TRADE") || v.includes("DECLINED")) return "yellow";
    if (v.includes("BLOCK") || v.includes("LOCK") || v.includes("DENY") || v.includes("CONFLICT") || v.includes("LIVE")) return "red";
    return "gray";
  }

  function dataSourceColor() {
    return data.meta.dataSource === "MOCK_DATA" ? "yellow" : "green";
  }

  function table(headers, rows) {
    return `
      <table class="table">
        <thead><tr>${headers.map((h) => `<th>${escapeHtml(h)}</th>`).join("")}</tr></thead>
        <tbody>
          ${rows.map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join("")}</tr>`).join("")}
        </tbody>
      </table>
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
    document.querySelector(".status-strip").innerHTML = [
      badge(data.meta.dataSource, dataSourceColor()),
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
    document.querySelectorAll(".screen").forEach((el) => el.classList.toggle("active", el.id === `screen-${id}`));
    document.querySelectorAll(".nav-button").forEach((el) => el.classList.toggle("active", el.dataset.screen === id));
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
    return `
      ${header("Bot Activity Control", "Governed PAPER intents only. Live and manual trading remain locked.", data.meta.dataSource)}
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
          ["PID", escapeHtml(sup.pid || "none")],
          ["Duration", escapeHtml(`${sup.durationSeconds || "unknown"}s`)],
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
            <button class="intent-button paper" data-intent="ai-analyze" ${data.meta.dataSource === "OPERATOR_BACKEND" ? "" : "disabled"}>
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
            <button class="intent-button paper" data-intent="world-poll" ${data.meta.dataSource === "OPERATOR_BACKEND" ? "" : "disabled"}>
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
      ${header("Diagnostics", "Environment, repo, and local runtime sanity without secrets.", data.meta.dataSource)}
      <div class="card">${kv([
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

  function renderRail() {
    const critical = data.alerts.filter((alert) => alert.severity === "SAFETY_CRITICAL").length;
    const pendingAI = data.ai.pendingReviewCount || 0;
    document.querySelector(".rail").innerHTML = `
      <div class="card rail-card"><h3>Current Alerts</h3>
        <div class="stack">
          ${badge(data.meta.dataSource, dataSourceColor())}
          ${badge("LIVE_LOCKED", "red")}
          ${badge("REAL_MONEY_BLOCKED", "red")}
          ${badge(`${data.alerts.length} watchdog`, data.alerts.length ? "yellow" : "gray")}
          ${badge(`${critical} critical`, critical ? "red" : "gray")}
        </div>
      </div>
      <div class="card rail-card"><h3>Dominant Blocker</h3>
        <div class="mono">${escapeHtml(data.status.dominantBlocker)}</div>
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

  function renderScreens() {
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
    showScreen("command");
  }

  async function fetchJson(path) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 1500);
    try {
      const response = await fetch(`${operatorApiBase()}${path}`, {
        cache: "no-store",
        signal: controller.signal
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } finally {
      window.clearTimeout(timeout);
    }
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
    const supervisor = status.supervisor || latestRun || {};
    const activeSession = supervisor.active_session || supervisor.latest_session || {};

    next.meta.dataSource = "OPERATOR_BACKEND";
    next.meta.buildMode = "operator_backend_supervisor_ready";
    next.meta.runtimeCommit = pick(runtime.runtime_commit, diagnostics.git_commit || "unknown");
    next.meta.lastUpdated = pick(status.updated_at, new Date().toISOString());

    next.status.botStatus = pick(status.bot_status, "NO_ACTIVE_RUNTIME_ATTACHED");
    next.status.runtimeMode = pick(status.runtime_mode, "PAPER");
    next.status.capabilityState = pick(status.capability_state || status.mode_state, "PAPER_ENABLED");
    next.status.activeProfile = pick(status.active_profile || profile.active_threshold_profile, "UNKNOWN_NO_ACTIVE_RUNTIME");
    next.status.broker = pick(status.broker, "UNKNOWN_NO_ACTIVE_RUNTIME");
    next.status.endpoint = pick(status.endpoint, "UNKNOWN_NO_ACTIVE_RUNTIME");
    next.status.marketData = pick(status.market_data, "UNKNOWN_NO_ACTIVE_RUNTIME");
    next.status.universe = Array.isArray(status.universe) && status.universe.length ? status.universe : pick(universe.symbols, []);
    next.status.assetClasses = Array.isArray(status.asset_classes) && status.asset_classes.length ? status.asset_classes : pick(universe.asset_classes, []);
    next.status.uptime = runtime.duration_seconds === null || runtime.duration_seconds === undefined ? "no active runtime" : `${runtime.duration_seconds}s`;
    next.status.lastHeartbeat = pick(status.last_heartbeat_ts, "unknown");
    next.status.liveBlocked = status.live_blocked !== false;
    next.status.realMoneyBlocked = status.real_money_blocked !== false;
    next.status.brokerPostCount = pick(status.broker_post_count, 0);
    next.status.brokerDeleteCount = pick(status.broker_delete_count, 0);
    next.status.mutationAuthorizedCount = pick(status.mutation_authorized_count, 0);
    next.status.safetyVerdict = pick(status.safety_verdict, "READ_ONLY_BACKEND_IDLE");
    next.status.dominantBlocker = pick(status.dominant_blocker, "NO_ACTIVE_RUNTIME_ATTACHED");
    next.status.lastDecision = runtime.process_state === "NO_ACTIVE_RUNTIME_ATTACHED" ? "No active runtime attached" : next.status.lastDecision;
    next.supervisor.state = pick(supervisor.state, "UNKNOWN");
    next.supervisor.sessionId = pick(activeSession.session_id || supervisor.active_session_id, "none");
    next.supervisor.pid = pick(activeSession.pid || runtime.pid, "none");
    next.supervisor.processState = pick(activeSession.status || runtime.process_state, "UNKNOWN");
    next.supervisor.durationSeconds = pick(activeSession.duration_seconds || runtime.duration_seconds, 300);
    next.supervisor.profile = pick(activeSession.profile || status.active_profile, "PAPER_EXPLORATION_ALPHA");
    next.supervisor.watchlist = pick(activeSession.watchlist || status.universe, ["BTC/USD", "ETH/USD", "SOL/USD"]);
    next.supervisor.stdoutPath = pick(activeSession.stdout_path || runtime.stdout_path, "not available");
    next.supervisor.stderrPath = pick(activeSession.stderr_path || runtime.stderr_path, "not available");
    next.supervisor.wrapperStdoutPath = pick(activeSession.wrapper_stdout_path || runtime.wrapper_stdout_path, next.supervisor.stdoutPath);
    next.supervisor.wrapperStderrPath = pick(activeSession.wrapper_stderr_path || runtime.wrapper_stderr_path, next.supervisor.stderrPath);
    next.supervisor.childStdoutPath = pick(activeSession.child_stdout_path || runtime.child_stdout_path, "not available");
    next.supervisor.childStderrPath = pick(activeSession.child_stderr_path || runtime.child_stderr_path, "not available");
    next.supervisor.paperStartAllowed = supervisor.paper_start_allowed === true || runtime.paper_start_allowed === true;
    next.supervisor.paperStopAllowed = supervisor.paper_stop_allowed === true || runtime.paper_stop_allowed === true;
    next.supervisor.paperStartRefusalReason = pick(supervisor.paper_start_refusal_reason || runtime.paper_start_refusal_reason, null);
    next.supervisor.paperStopRefusalReason = pick(supervisor.paper_stop_refusal_reason || runtime.paper_stop_refusal_reason, null);

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
        reportPath: pick(run.report_path, "")
      }));
      next.runArchive.latestVerdict = next.runArchive.runs.length ? next.runArchive.runs[0].finalVerdict : "UNKNOWN";
      next.runArchive.reportStatus = "on demand";
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
    try {
      const [status, health, operatorReadiness, storage, runtime, profile, universe, readiness, diagnostics, contracts, latestRun, orders, fills, tca, audit, world, worldRuntime, runs, explain, actionCenter, pnlDashboard, tcaDashboard, alerts, systemMap, aiStatus, aiRecommendations] = await Promise.all([
        fetchJson("/operator/status"),
        fetchJson("/operator/health"),
        fetchJson("/operator/readiness"),
        fetchJson("/operator/storage"),
        fetchJson("/operator/runtime"),
        fetchJson("/operator/profile"),
        fetchJson("/operator/universe"),
        fetchJson("/operator/readiness/live"),
        fetchJson("/operator/diagnostics"),
        fetchJson("/operator/contracts"),
        fetchJson("/operator/latest-run"),
        fetchJson("/operator/orders-summary"),
        fetchJson("/operator/fills-summary"),
        fetchJson("/operator/tca-summary"),
        fetchJson("/operator/audit-summary"),
        fetchJson("/operator/world-awareness"),
        fetchJson("/operator/world-awareness/runtime"),
        fetchJson("/operator/runs"),
        fetchJson("/operator/explain/latest"),
        fetchJson("/operator/action-center"),
        fetchJson("/operator/pnl"),
        fetchJson("/operator/tca"),
        fetchJson("/operator/alerts"),
        fetchJson("/operator/system-map"),
        fetchJson("/operator/ai/status"),
        fetchJson("/operator/ai/recommendations")
      ]);
      return normalizeBackendData({ status, health, operatorReadiness, storage, runtime, profile, universe, readiness, diagnostics, contracts, latestRun, orders, fills, tca, audit, world, worldRuntime, runs, explain, actionCenter, pnlDashboard, tcaDashboard, alerts, systemMap, aiStatus, aiRecommendations });
    } catch (error) {
      const fallback = clone(mockData);
      fallback.meta.dataSource = "MOCK_DATA";
      fallback.meta.backendStatus = `backend unavailable: ${error.name || "fetch_failed"}`;
      return fallback;
    }
  }

  async function boot() {
    data = await loadData();
    renderTopBar();
    renderNav();
    renderScreens();
    renderRail();
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
    if (data.meta.dataSource !== "OPERATOR_BACKEND") return;
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
      data = await loadData();
      data.supervisor.lastIntentResult = message;
      data.worldRuntime.lastPollResult = message;
      data.ai.lastAnalyzeResult = message;
      renderTopBar();
      renderScreens();
      renderRail();
    } catch (error) {
      data.supervisor.lastIntentResult = `FAILED: ${error.message || error.name || "intent_error"}`;
      renderScreens();
      renderRail();
    }
  }

  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-intent]");
    if (!button || button.disabled) return;
    handleIntent(button.dataset.intent);
  });

  document.addEventListener("DOMContentLoaded", boot);
})();
