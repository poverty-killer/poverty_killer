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
        nextPollTime: "not scheduled",
        nextPollDue: false,
        backoffSeconds: 300,
        errorCount: 0,
        consecutiveErrorCount: 0,
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
        nextPollTime: "not scheduled",
        nextPollDue: false,
        backoffSeconds: 300,
        errorCount: 0,
        consecutiveErrorCount: 0,
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
        nextPollTime: "not scheduled",
        nextPollDue: false,
        backoffSeconds: 300,
        errorCount: 0,
        consecutiveErrorCount: 0,
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
    worldRuntime: {
      manualPollOnly: true,
      providerPollingActive: false,
      dueProviders: [],
      lastPollResult: "none"
    },
    diagnostics: {
      gitCommit: "fe4697a",
      dirtyWorktree: "warning surface required",
      pythonVersion: "runtime reported later",
      credentials: "present/not present only",
      logs: "not read by static shell",
      db: "not read by static shell",
      runtimeProfile: "LOCAL_PAPER",
      hostedMode: false,
      healthStatus: "MOCK_ONLY",
      sessionStoreStatus: "MOCK_ONLY",
      worldCacheStatus: "MOCK_ONLY",
      operatorStateDir: "state/operator/",
      worldAwarenessCachePath: "state/world_awareness/operator_events.jsonl",
      latestChildStdout: "not available in mock mode",
      latestChildStderr: "not available in mock mode"
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
    },
    runArchive: {
      runCount: 1,
      latestVerdict: "CONDITIONAL_PASS",
      reportStatus: "on demand",
      runs: [
        {
          runId: "mock-paper-run",
          status: "EXITED",
          finalVerdict: "CONDITIONAL_PASS",
          profile: "PAPER_EXPLORATION_ALPHA",
          durationSeconds: 300,
          ordersSubmitted: 1,
          ordersAcknowledged: 1,
          ordersCanceled: 1,
          fillsObserved: 1,
          tcaStatus: "UNKNOWN",
          reasonCodes: ["MOCK_DATA_SAMPLE", "BROKER_FEE_DETAIL_PENDING"],
          reportPath: "not generated in mock mode"
        }
      ]
    },
    explanation: {
      headline: "Mock DecisionFrame BUY passed hard blockers; economics still require broker-confirmed TCA before performance claims.",
      frameId: "df_e5126d62",
      output: "BUY",
      netEdge: "ALLOW",
      confidence: "MEDIUM",
      nextBestAction: "Audit fill hydration, fees, OMS reconciliation, and TCA before drawing performance conclusions.",
      blockers: [],
      missingTruth: ["BROKER_FEE_DETAIL_PENDING"]
    },
    actionCenter: {
      counts: {
        INFO: 2,
        WARNING: 2,
        BLOCKER: 2,
        NEEDS_APPROVAL: 0,
        SAFETY_CRITICAL: 0
      },
      items: [
        {
          type: "BLOCKER",
          title: "Live trading is locked",
          detail: "LIVE_NOT_APPROVED remains active.",
          source: "readiness",
          canExecute: false
        },
        {
          type: "WARNING",
          title: "Broker fee detail pending",
          detail: "Fee/TCA remains unknown until broker evidence arrives.",
          source: "fills-summary",
          canExecute: false
        }
      ]
    },
    tcaDashboard: {
      status: "PENDING_FEE_DETAIL",
      recordsTotal: 0,
      recordsComplete: 0,
      recordsUnknown: 0,
      feePending: 1
    },
    alerts: [
      {
        severity: "WARNING",
        title: "No active runtime",
        detail: "Mock mode is not attached to a PAPER supervisor.",
        source: "status",
        acknowledged: false,
        canExecute: false
      }
    ],
    ai: {
      provider: "disabled",
      providerState: "AI_DISABLED",
      pendingReviewCount: 0,
      secretsValuesExposed: false,
      lastAnalyzeResult: "none",
      recommendations: [
        {
          recommendationId: "mock-ai-rec",
          recommendationType: "OBSERVATION",
          status: "DRAFT",
          summary: "AI Chief is advisory-only and disabled in mock mode.",
          proposedAction: "NO_ACTION",
          canExecute: false
        }
      ]
    },
    providerReadiness: {
      providerCount: 5,
      readyOrConfiguredCount: 2,
      missingCredentialsCount: 1,
      notImplementedCount: 2,
      counts: {
        READY: 2,
        MISSING_CREDENTIALS: 1,
        NOT_IMPLEMENTED: 2
      },
      providers: [
        {
          providerId: "alpaca_paper",
          displayName: "Alpaca Paper Broker/Data",
          category: "broker",
          purpose: "Governed PAPER broker and account/order/fill truth source.",
          status: "MISSING_CREDENTIALS",
          requiredEnvVars: ["APCA_API_KEY_ID", "APCA_API_SECRET_KEY"],
          optionalEnvVars: ["APCA_API_BASE_URL"],
          envStatus: [
            { name: "APCA_API_KEY_ID", configured: false, fingerprint: null },
            { name: "APCA_API_SECRET_KEY", configured: false, fingerprint: null }
          ],
          configured: false,
          readOnlyValidationSupported: true,
          canTrade: false,
          canMutateExternalSystem: false,
          lastValidationStatus: "NOT_RUN",
          lastValidationAt: null,
          setupInstructions: "Set Alpaca PAPER env vars in the runtime environment. UI never sees raw values."
        },
        {
          providerId: "coinbase_public",
          displayName: "Coinbase Public",
          category: "market_data",
          purpose: "Public crypto market-data route.",
          status: "READY",
          requiredEnvVars: [],
          optionalEnvVars: [],
          envStatus: [],
          configured: true,
          readOnlyValidationSupported: false,
          canTrade: false,
          canMutateExternalSystem: false,
          lastValidationStatus: "NOT_RUN",
          lastValidationAt: null,
          setupInstructions: "No credentials required. MarketTruthSnapshot still decides executability."
        },
        {
          providerId: "openai",
          displayName: "OpenAI Placeholder",
          category: "ai_provider",
          purpose: "Future AI Quant Research Chief model provider.",
          status: "NOT_IMPLEMENTED",
          requiredEnvVars: ["OPENAI_API_KEY"],
          optionalEnvVars: ["OPENAI_MODEL"],
          envStatus: [{ name: "OPENAI_API_KEY", configured: false, fingerprint: null }],
          configured: false,
          readOnlyValidationSupported: true,
          canTrade: false,
          canMutateExternalSystem: false,
          lastValidationStatus: "NOT_RUN",
          lastValidationAt: null,
          setupInstructions: "Future provider setup only. Tests make no real model calls."
        }
      ]
    },
    research: {
      counts: {
        hypotheses: 0,
        experiments: 0,
        recommendations: 1,
        promotionGates: 3
      },
      hypotheses: [],
      experiments: [],
      promotionGates: [
        {
          gateId: "idea_to_offline_research",
          stage: "IDEA",
          requiredEvidence: ["clear thesis", "falsifiable invalidation condition"],
          currentStatus: "NEEDS_REVIEW",
          blocksPromotion: true,
          liveRequiresSeparateApproval: false
        },
        {
          gateId: "replay_to_bounded_paper",
          stage: "REPLAY_REVIEW",
          requiredEvidence: ["DecisionFrame", "MarketTruthSnapshot", "NetEdge/TCA"],
          currentStatus: "NEEDS_REVIEW",
          blocksPromotion: true,
          liveRequiresSeparateApproval: false
        },
        {
          gateId: "any_live_transition",
          stage: "LIVE_REQUIRES_SEPARATE_APPROVAL",
          requiredEvidence: ["separate live governance packet"],
          currentStatus: "BLOCKED",
          blocksPromotion: true,
          liveRequiresSeparateApproval: true
        }
      ],
      recommendations: [
        {
          id: "mock-research-rec",
          title: "Review latest run evidence before expanding PAPER",
          summary: "Check DecisionFrame, NetEdge, fees, fills, TCA, OMS, watchdog, and provider readiness before the next PAPER experiment.",
          status: "NEEDS_REVIEW",
          promotionStage: "IDEA",
          canExecute: false
        }
      ]
    },
    evidenceGraph: {
      nodes: [
        { nodeId: "latest_run", label: "Latest Run", truthLabel: "operator_archive", summary: "CONDITIONAL_PASS", runId: "mock-paper-run", reportPath: "not generated in mock mode" },
        { nodeId: "decision_explainer", label: "Decision Explainer", truthLabel: "decisionframe_summary", summary: "Mock BUY explanation" },
        { nodeId: "fills_tca_fees", label: "Fills / TCA / Fees", truthLabel: "broker_confirmed_when_available", summary: "fee detail pending" }
      ],
      edges: [
        { from: "latest_run", to: "decision_explainer", relationship: "run_decision_context" }
      ],
      latestRunId: "mock-paper-run",
      reportPath: "not generated in mock mode",
      reasonCodes: ["MOCK_DATA_SAMPLE", "BROKER_FEE_DETAIL_PENDING"],
      missingEvidence: ["BROKER_CONFIRMED_REALIZED_PNL_UNAVAILABLE", "TCA_COMPLETE_EVIDENCE_UNAVAILABLE"],
      promotionBlockers: ["BROKER_FEE_DETAIL_PENDING"],
      rawLogsIncluded: false,
      secretsValuesExposed: false
    },
    systemMap: {
      reportPath: "reports/poverty_killer_system_map_operator_explainer.md",
      sections: [
        "runtime launcher",
        "MarketTruthSnapshot",
        "DecisionFrame",
        "NetEdge",
        "ExecutionEngine",
        "BrokerBoundary",
        "OMS",
        "Fill/TCA/Fee hydration",
        "Operator API",
        "Supervisor",
        "UI",
        "World Awareness",
        "AI Chief Operator",
        "live readiness gates"
      ]
    }
  };
})();
