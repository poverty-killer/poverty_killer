(function () {
  "use strict";

  window.PK_MOCK_DATA = {
    meta: {
      title: "Poverty Killer Operator Control Panel",
      buildMode: "static_mock",
      dataSource: "MOCK_DATA",
      runtimeCommit: "fe4697a",
      lastUpdated: "2026-05-26T01:38:32Z"
    },
    status: {
      botStatus: "RUNNING",
      runtimeMode: "PAPER",
      capabilityState: "PAPER_ENABLED",
      activeProfile: "PAPER_EXPLORATION_ALPHA",
      broker: "alpaca_paper",
      endpoint: "https://paper-api.alpaca.markets",
      marketData: "coinbase_public",
      universe: ["BTC/USD", "ETH/USD", "SOL/USD"],
      assetClasses: ["crypto"],
      uptime: "02:00:00",
      lastHeartbeat: "fresh",
      liveBlocked: true,
      realMoneyBlocked: true,
      brokerPostCount: 17,
      brokerDeleteCount: 15,
      mutationAuthorizedCount: 0,
      safetyVerdict: "CLEAN",
      dominantBlocker: "BROKER_FEE_DETAIL_UNAVAILABLE",
      lastDecision: "BUY -> PAPER order acknowledged -> cancel acknowledged"
    },
    supervisor: {
      state: "MOCK_ONLY",
      sessionId: "mock-session",
      pid: "not running",
      processState: "MOCK_ONLY",
      durationSeconds: 300,
      profile: "PAPER_EXPLORATION_ALPHA",
      watchlist: ["BTC/USD", "ETH/USD", "SOL/USD"],
      stdoutPath: "not available in mock mode",
      stderrPath: "not available in mock mode",
      paperStartAllowed: false,
      paperStopAllowed: false,
      paperStartRefusalReason: "MOCK_DATA_NO_BACKEND",
      paperStopRefusalReason: "MOCK_DATA_NO_BACKEND",
      lastIntentResult: "none"
    },
    pnl: {
      realizedPnl: { value: null, source: "UNKNOWN_INSUFFICIENT_BROKER_DETAIL" },
      unrealizedPnl: { value: null, source: "BROKER_CONFIRMED_REQUIRED" },
      netPnl: { value: null, source: "UNKNOWN_INSUFFICIENT_BROKER_DETAIL" },
      fees: { value: null, source: "FEE_PENDING_BROKER_ACTIVITY" },
      spreadCost: "modeled only",
      slippage: "unknown until complete TCA detail",
      latencyDrag: "modeled",
      grossEdge: "available in DecisionFrame",
      netEdge: "ALLOW",
      trades: 17,
      winLoss: "not computed without complete broker fill economics",
      maxDrawdown: "broker/account truth required"
    },
    positions: [
      {
        symbol: "BTC/USD",
        assetClass: "crypto",
        brokerQuantity: "broker-confirmed",
        source: "BROKER_CONFIRMED",
        movingFloor: "ARMED",
        exitEligibility: "sell_to_close requires broker position truth"
      },
      {
        symbol: "ETH/USD",
        assetClass: "crypto",
        brokerQuantity: "broker-confirmed",
        source: "BROKER_CONFIRMED",
        movingFloor: "ARMED",
        exitEligibility: "sell_to_close requires broker position truth"
      },
      {
        symbol: "SOL/USD",
        assetClass: "crypto",
        brokerQuantity: "broker-confirmed",
        source: "BROKER_CONFIRMED",
        movingFloor: "ARMED",
        exitEligibility: "sell_to_close requires broker position truth"
      }
    ],
    orders: [
      {
        clientOrderId: "sector_rotation_BTC/USD_1779757140000000000",
        symbol: "BTC/USD",
        side: "buy",
        action: "buy_to_open",
        state: "CANCELED_WITH_PARTIAL_FILL",
        brokerStatus: "canceled",
        reconciliation: "PASS"
      },
      {
        clientOrderId: "sector_rotation_SOL/USD_1779756900000000000",
        symbol: "SOL/USD",
        side: "buy",
        action: "buy_to_open",
        state: "FILLED",
        brokerStatus: "filled",
        reconciliation: "PASS"
      }
    ],
    fills: [
      {
        fillId: "broker_activity:alpaca:mock-001",
        symbol: "BTC/USD",
        side: "buy",
        quantity: "0.029925",
        price: "76635.835",
        source: "broker_activity",
        hydrationStatus: "PARTIAL",
        feeStatus: "FEE_PENDING_BROKER_ACTIVITY",
        feeSource: "UNAVAILABLE",
        tca: "UNKNOWN_INSUFFICIENT_BROKER_DETAIL",
        reason: "Broker fee detail may post later as CFEE/FEE activity; no fee is invented."
      },
      {
        fillId: "broker_activity:alpaca:mock-002",
        symbol: "SOL/USD",
        side: "buy",
        quantity: "0.49467034",
        price: "84.255",
        source: "broker_activity",
        hydrationStatus: "PARTIAL",
        feeStatus: "FEE_ACTIVITY_MATCHED",
        feeSource: "BROKER_CFEE",
        tca: "UNKNOWN_INSUFFICIENT_BROKER_DETAIL",
        reason: "Broker fee matched; execution quality remains unknown until all modeled/broker fields are present."
      }
    ],
    decisionFrames: [
      {
        frameId: "df_e5126d62",
        symbol: "SOL/USD",
        assetClass: "crypto",
        candleId: "1779750900000000000",
        snapshotId: "mts_81824c1e",
        profile: "PAPER_EXPLORATION_ALPHA",
        output: "BUY",
        opportunityVerdict: "PLAUSIBLE_CANDIDATE",
        rawScore: 0.6125,
        finalScore: 0.521,
        netEdge: "ALLOW",
        compiler: "COMPILED",
        submitSignal: "SUBMITTED_TO_EXECUTION"
      },
      {
        frameId: "df_locked_sell",
        symbol: "ETH/USD",
        assetClass: "crypto",
        candleId: "mock",
        snapshotId: "mock",
        profile: "PAPER_EXPLORATION_ALPHA",
        output: "SELL",
        opportunityVerdict: "BEARISH_NO_LONG",
        rawScore: 0.48,
        finalScore: 0.31,
        netEdge: "UNKNOWN",
        compiler: "NO_TRADE",
        submitSignal: "NOT_EXECUTABLE_SELL_AUTHORITY"
      }
    ],
    moduleEvidence: [
      ["MarketTruthSnapshot", "MARKET_TRUTH", "CONTRIBUTED", "NONE", "PASS"],
      ["StrategySignal", "ALPHA", "CONTRIBUTED", "BUY", "OBSERVED_PAIR_READY"],
      ["StrategyVote", "ALPHA", "CONTRIBUTED", "BUY", "SAME_CANDLE_READY"],
      ["SignalFusion", "ALPHA", "CONTRIBUTED", "NONE", "FUSION_ATTRIBUTION_PRESENT"],
      ["ShansCurve", "ALPHA", "CONTRIBUTED", "NONE", "NATIVE_SIGNAL_FRESH"],
      ["ShadowFront", "ALPHA", "DECLINED", "NONE", "NO_WHALE_EDGE"],
      ["SectorRotation", "ALPHA", "CONTRIBUTED", "BUY", "OBSERVED_PAIR_READY"],
      ["LiquidityVoid", "ALPHA", "MISSING_TRUTH", "NONE", "OBSERVED_PAIR_MISSING"],
      ["GammaFront", "ALPHA", "DECLINED", "NONE", "EXIT_ONLY"],
      ["StrategyRouter", "ADVISORY", "CONTRIBUTED", "NONE", "RANKING_ONLY"],
      ["NetEdgeGovernor", "RISK", "CONTRIBUTED", "NO_ACTION", "ECONOMICALLY_ADMISSIBLE"],
      ["PreTradeGuardrails", "RISK", "CONTRIBUTED", "NO_ACTION", "ALLOW"],
      ["MovingFloor", "RISK", "DECLINED", "NONE", "NO_BREACH"],
      ["OrderRouter/BrokerGateway", "EXECUTION", "CONTRIBUTED", "NONE", "PAPER_BOUNDARY_CLEAN"]
    ],
    marketTruth: [
      ["BTC/USD", "coinbase_public", "PASS", "fresh", "fresh", true, "runtime"],
      ["ETH/USD", "coinbase_public", "PASS", "fresh", "fresh", true, "runtime"],
      ["SOL/USD", "coinbase_public", "PASS", "fresh", "fresh", true, "runtime"]
    ],
    risk: [
      ["Market truth", "HARD_GATE", "ALLOW", "canonical snapshot pass"],
      ["Broker truth", "HARD_GATE", "ALLOW", "Alpaca PAPER canonical"],
      ["Quote/session", "HARD_GATE", "ALLOW", "continuous crypto session"],
      ["Sell authority", "HARD_GATE", "BLOCKED_WHEN_FLAT", "broker position required"],
      ["NetEdge", "ECONOMIC_GATE", "ALLOW", "positive modeled net edge"],
      ["Live endpoint", "HARD_GATE", "BLOCKED", "LIVE_NOT_APPROVED"],
      ["Real-money", "HARD_GATE", "BLOCKED", "REAL_MONEY_NOT_APPROVED"]
    ],
    auditLog: [
      ["23:38:26", "PROFILE", "INFO", "PAPER_EXPLORATION_ALPHA active", "PASS"],
      ["23:46:00", "DECISION", "INFO", "DecisionFrame BUY SOL/USD", "COMPILED"],
      ["23:46:01", "BROKER", "INFO", "PAPER POST acknowledged", "POST=1"],
      ["23:46:06", "BROKER", "INFO", "PAPER cancel acknowledged", "DELETE=1"],
      ["01:38:32", "OMS", "INFO", "Shutdown reconciliation clean", "PASS"]
    ],
    worldAwareness: [
      {
        source: "alpaca_news",
        feedType: "NEWS",
        enabled: false,
        status: "ADVISORY_ONLY",
        relevance: "disabled by default; no polling active",
        confidence: "unknown",
        stale: false,
        verification: "UNVERIFIED",
        rule: "cannot bypass MarketTruthSnapshot, NetEdge, or guardrails"
      },
      {
        source: "sec_insider_filings",
        feedType: "SEC_FILING",
        enabled: false,
        status: "FEED_DISABLED",
        relevance: "equities-only advisory lane; not crypto execution authority",
        confidence: "unknown",
        stale: false,
        verification: "UNVERIFIED",
        rule: "Form 4-style data contributes advisory evidence only"
      },
      {
        source: "economic_calendar",
        feedType: "ECONOMIC_CALENDAR",
        enabled: false,
        status: "FEED_DISABLED",
        relevance: "provider TBD",
        confidence: "unknown",
        stale: false,
        verification: "UNVERIFIED",
        rule: "macro events are context, not direct order authority"
      }
    ],
    worldAwarenessEvents: [
      {
        eventId: "mock-alpaca-news-001",
        provider: "alpaca_news",
        feedType: "NEWS",
        symbols: ["BTC/USD", "ETH/USD"],
        title: "Mock Alpaca News headline",
        eventTime: "2026-05-26T12:00:00Z",
        freshness: "60s",
        stale: false,
        verification: "UNVERIFIED",
        advisoryOnly: true,
        reason: "Advisory display only; no DecisionFrame score impact."
      }
    ],
    diagnostics: {
      gitCommit: "fe4697a",
      dirtyWorktree: "warning surface required",
      pythonVersion: "runtime reported later",
      credentials: "present/not present only",
      logs: "not read by static shell",
      db: "not read by static shell"
    },
    liveReadiness: {
      state: "LIVE_LOCKED",
      refusal: "LIVE_NOT_APPROVED",
      passed: [
        "PAPER OMS reconciliation proven",
        "broker-backed fill ledger exists",
        "no live endpoint in PAPER validation",
        "no real-money mode in PAPER validation"
      ],
      missing: [
        "separate live governance packet",
        "live endpoint authority",
        "real-money authority",
        "risk governor live approval",
        "operator approval",
        "live-readiness audit"
      ]
    }
  };
})();
