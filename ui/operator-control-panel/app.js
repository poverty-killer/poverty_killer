(function () {
  "use strict";

  const data = window.PK_MOCK_DATA;
  const screens = [
    ["command", "Command Center"],
    ["pnl", "P&L / Net Profit"],
    ["positions", "Positions & Orders"],
    ["activity", "Bot Activity Control"],
    ["decision", "Signal & Decision Lab"],
    ["market", "Market Data Truth"],
    ["risk", "Risk & Governor"],
    ["audit", "Audit Log"],
    ["world", "World Awareness"],
    ["diagnostics", "Diagnostics"],
    ["live", "Live Readiness"]
  ];

  function badge(text, color) {
    return `<span class="badge ${color || "gray"}">${escapeHtml(String(text))}</span>`;
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

  function renderTopBar() {
    const s = data.status;
    document.querySelector(".status-strip").innerHTML = [
      badge(s.runtimeMode, "green"),
      badge(s.activeProfile, "cyan"),
      badge(s.broker, "blue"),
      badge("PAPER endpoint", "green"),
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
        <span class="muted">0${index + 1}</span>
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
          ["Force trade", badge("forbidden", "red")]
        ])}</div>
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
    return `
      ${header("Bot Activity Control", "Read-only now. Future PAPER controls are audited server-side intents.", "MOCK ONLY")}
      <div class="grid">
        <div class="card span-6"><h3>Runtime Snapshot</h3>${kv([
          ["Process", badge("RUNNING", "green")],
          ["Profile", badge(data.status.activeProfile, "cyan")],
          ["Watchlist", escapeHtml(data.status.universe.join(", "))],
          ["Preflight", badge("PAPER_READ_ONLY_PREFLIGHT_REQUIRED", "yellow")],
          ["Credential status", "present/not present only; no secrets"]
        ])}</div>
        <div class="card span-6"><h3>Future PAPER Intents</h3>
          <div class="stack">
            <button class="intent-button paper" disabled>Request bounded PAPER start - future server-authorized intent</button>
            <button class="intent-button paper" disabled>Request PAPER stop - future server-authorized intent</button>
            <button class="intent-button paper" disabled>Export run report - future server-authorized intent</button>
            <button class="intent-button live" disabled>Live start locked - LIVE_NOT_APPROVED</button>
          </div>
        </div>
      </div>
    `;
  }

  function renderDecision() {
    return `
      ${header("Signal & Decision Lab", "Why BUY, SELL, or NO_TRADE happened.", "DECISIONFRAME FIRST")}
      <div class="grid">
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
    const w = data.worldAwareness[0];
    return `
      ${header("World Awareness", "External intelligence is advisory evidence only.", "NO EXECUTION AUTHORITY")}
      <div class="card">${kv([
        ["Source", escapeHtml(w.source)],
        ["Status", badge(w.status, "yellow")],
        ["Relevance", escapeHtml(w.relevance)],
        ["Rule", escapeHtml(w.rule)]
      ])}</div>
    `;
  }

  function renderDiagnostics() {
    const d = data.diagnostics;
    return `
      ${header("Diagnostics", "Environment, repo, and local runtime sanity without secrets.", "STATIC MOCK")}
      <div class="card">${kv([
        ["Git commit", escapeHtml(d.gitCommit)],
        ["Dirty worktree", badge(d.dirtyWorktree, "yellow")],
        ["Python version", escapeHtml(d.pythonVersion)],
        ["Credentials", escapeHtml(d.credentials)],
        ["Logs", escapeHtml(d.logs)],
        ["DB", escapeHtml(d.db)]
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
    document.querySelector(".rail").innerHTML = `
      <div class="card rail-card"><h3>Current Alerts</h3>
        <div class="stack">
          ${badge("LIVE_LOCKED", "red")}
          ${badge("REAL_MONEY_BLOCKED", "red")}
          ${badge("BROKER_FEE_DETAIL_UNAVAILABLE", "yellow")}
        </div>
      </div>
      <div class="card rail-card"><h3>Dominant Blocker</h3>
        <div class="mono">${escapeHtml(data.status.dominantBlocker)}</div>
      </div>
      <div class="card rail-card"><h3>Last Decision</h3>
        <div>${escapeHtml(data.status.lastDecision)}</div>
      </div>
      <div class="card rail-card"><h3>Needs Approval</h3>
        <div class="stack">
          ${badge("live governance packet", "red")}
          ${badge("server-side authority", "red")}
          ${badge("operator approval", "red")}
        </div>
      </div>
    `;
  }

  function renderScreens() {
    const main = document.querySelector(".main");
    const renderers = {
      command: renderCommand,
      pnl: renderPnl,
      positions: renderPositions,
      activity: renderActivity,
      decision: renderDecision,
      market: renderMarket,
      risk: renderRisk,
      audit: renderAudit,
      world: renderWorld,
      diagnostics: renderDiagnostics,
      live: renderLive
    };
    main.innerHTML = screens.map(([id]) => `<section class="screen" id="screen-${id}">${renderers[id]()}</section>`).join("");
    showScreen("command");
  }

  function boot() {
    renderTopBar();
    renderNav();
    renderScreens();
    renderRail();
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
