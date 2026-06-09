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
      botStatus: "MOCK_SAMPLE_NO_RUNTIME",
      runtimeMode: "PAPER",
      capabilityState: "PAPER_ENABLED",
      activeProfile: "PAPER_EXPLORATION_ALPHA",
      broker: "alpaca_paper",
      endpoint: "https://paper-api.alpaca.markets",
      marketData: "coinbase_public",
      universe: ["BTC/USD", "ETH/USD", "SOL/USD"],
      assetClasses: ["crypto"],
      uptime: "mock sample only",
      lastHeartbeat: "mock sample",
      liveBlocked: true,
      realMoneyBlocked: true,
      brokerPostCount: 0,
      brokerDeleteCount: 0,
      mutationAuthorizedCount: 0,
      safetyVerdict: "MOCK_SAMPLE_NOT_RUNTIME_TRUTH",
      dominantBlocker: "MOCK_DATA_NO_BACKEND",
      lastDecision: "Mock sample only; connect OPERATOR_BACKEND for runtime truth."
    },
    supervisor: {
      state: "MOCK_ONLY",
      sessionId: "mock-session",
      pid: "not running",
      processState: "MOCK_ONLY",
      durationSeconds: 300,
      minPaperDurationSeconds: 60,
      maxPaperDurationSeconds: 432000,
      runnerMaxPaperDurationSeconds: 432000,
      durationAuthority: "scripts/run_bounded_paper.ps1",
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
    historicalTests: {
      source: "MOCK_DATA",
      status: "READY_FOR_REQUEST_HARNESS_NOT_ATTACHED",
      presets: [
        { id: "last_4_months", label: "Last 4 months", start_date: "2026-01-26", end_date: "2026-05-26" }
      ],
      timeframes: ["1Min", "5Min", "15Min", "1Hour", "1Day"],
      feeSlippagePolicies: ["broker_fees_unavailable_unknown", "conservative_estimate_not_broker_truth"],
      defaultWatchlist: ["BTC/USD", "ETH/USD", "SOL/USD"],
      lastResults: [],
      lastRunResult: null,
      simulationHarnessAttached: false,
      readOnlyMarketDataOnly: true,
      brokerTradingCallOccurred: false,
      brokerMutationOccurred: false,
      canExecute: false,
      secretsValuesExposed: false,
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
    launchReadiness: {
      source: "MOCK_DATA",
      finalLaunchReadiness: "BLOCKED",
      checks: [
        { checkId: "alpaca_paper_credentials", title: "Alpaca PAPER credentials", status: "BLOCKED", detail: "mock sample credentials missing", blocker: true, warning: false },
        { checkId: "paper_endpoint_only", title: "PAPER endpoint only", status: "PASS", detail: "paper endpoint only", blocker: false, warning: false },
        { checkId: "live_blocked", title: "Live blocked", status: "PASS", detail: "LIVE_LOCKED", blocker: false, warning: false }
      ],
      reasonCodes: ["alpaca_paper_credentials"],
      alpacaPaperCredentialsConfigured: false,
      paperEndpointOnly: true,
      paperStartAllowed: false,
      runPaperOperatorState: {
        source: "MOCK_DATA",
        schemaVersion: "run-paper-command-center-v1",
        overallStatus: {
          code: "BLOCKED",
          label: "Mock data cannot start PAPER",
          severity: "red",
          detail: "Connect OPERATOR_BACKEND for current launch readiness truth."
        },
        canRunPaper: {
          allowed: false,
          label: "Start blocked",
          reason: "Mock/sample mode cannot start PAPER.",
          reasonCodes: ["MOCK_DATA_NO_BACKEND"],
          warningCodes: [],
          usesExistingGovernedStartIntent: "/operator/intent/paper/start",
          requiresOperatorConfirmations: true
        },
        nextSafeAction: "Start the operator backend before using Run PAPER controls.",
        endpoint: {
          label: "Mock PAPER endpoint sample",
          display: "https://paper-api.alpaca.markets",
          family: "paper",
          host: "paper-api.alpaca.markets",
          source: "MOCK_DATA",
          configured: false,
          valid: true,
          status: "PAPER_ENDPOINT_CONFIRMED",
          blockerCode: null,
          operatorAction: "Connect backend for real endpoint authority."
        },
        credentials: {
          label: "Mock credentials missing",
          configured: false,
          missingFields: ["APCA_API_KEY_ID", "APCA_API_SECRET_KEY"],
          source: "MOCK_DATA",
          precedence: "ENV_PRESENT_OVERRIDES_LOCAL_SECRET",
          rawSecretValuesIncluded: false,
          secretsValuesExposed: false
        },
        paperCredentialSetup: {
          source: "MOCK_DATA",
          schemaVersion: "paper-credential-setup-v1",
          overallStatus: {
            code: "MISSING",
            label: "Mock PAPER credentials missing",
            severity: "blocked",
            detail: "PAPER credentials missing - connect OPERATOR_BACKEND for current local credential truth."
          },
          requiredCredentials: [
            { name: "APCA_API_KEY_ID", present: false, displayValue: "missing", source: "MOCK_DATA", rawValueExposed: false },
            { name: "APCA_API_SECRET_KEY", present: false, displayValue: "missing", source: "MOCK_DATA", rawValueExposed: false }
          ],
          missingFields: ["APCA_API_KEY_ID", "APCA_API_SECRET_KEY"],
          valuesHidden: true,
          endpoint: {
            display: "https://paper-api.alpaca.markets",
            family: "paper",
            host: "paper-api.alpaca.markets",
            source: "safe_default",
            configured: false,
            paperEndpointValid: true,
            liveEndpointBlocked: true,
            blockerCode: null
          },
          approvedSecretPath: {
            label: "Keys & Providers -> Alpaca PAPER Broker/Data -> Save local credentials",
            storageType: "operator_secret_file",
            relativePath: ".operator_secrets/provider_credentials.json",
            credentialPrecedence: "ENV_PRESENT_OVERRIDES_LOCAL_SECRET",
            gitignored: true,
            safeInstruction: "Use Keys & Providers when OPERATOR_BACKEND is connected; values stay local and hidden.",
            forbiddenInstruction: "Do not paste credentials into chat, do not commit .env files, and do not put raw secrets in tracked files."
          },
          preflightGate: {
            readOnlyPreflightAuthorized: false,
            readOnlyPreflightAvailable: false,
            accountCheckStatus: "blocked",
            openOrdersCheckStatus: "blocked",
            positionsCheckStatus: "blocked",
            lastPreflightAt: null,
            lastPreflightResult: null,
            statusLabel: "Read-only PAPER preflight not run",
            detail: "Mock/sample mode cannot call Alpaca or prove account, open-orders, or positions truth.",
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
          nextSafeAction: "Connect OPERATOR_BACKEND, then use Keys & Providers to save Alpaca PAPER credentials locally.",
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
          source: "MOCK_DATA",
          schemaVersion: "paper-baseline-view-v1",
          status: "PREFLIGHT_BLOCKED_BASELINE_ADOPTION_REQUIRED",
          decision: "PAPER_BASELINE_ADOPTION_REQUIRED",
          accepted: false,
          policy: "ADOPT_EXISTING_POSITIONS_PROTECTED",
          positionCount: 10,
          positionSymbols: ["AAPL", "AMZN", "BTCUSD", "ETHUSD", "GOOGL", "NVDA", "QQQ", "SOLUSD", "SPY", "TSLA"],
          openOrderCount: 0,
          endpointFamily: "paper",
          liveLocked: true,
          realMoneyBlocked: true,
          startReady: false,
          reason: "Existing PAPER positions require explicit baseline adoption.",
          nextSafeAction: "Accept current positions as the protected PAPER baseline, then prepare a short position-aware PAPER smoke packet.",
          baselineSnapshotId: null,
          snapshotHash: null,
          acceptedAt: null,
          protectedSymbols: [],
          sameSymbolTradingPolicy: "BLOCK_BASELINE_SYMBOL_TRADES_UNTIL_RUN_LOT_TRACKING",
          pnlAttribution: {
            baselineAccountEquity: null,
            baselinePositionsValue: null,
            runIncrementalEquityPnl: null,
            runIncrementalEquityPnlLabel: "current account equity - baseline account equity; deposits/withdrawals not adjusted unless transfer data is added",
            baselineCarryPnlLabel: "baseline carry P&L from mark-to-market movement in pre-existing positions; shown separately from bot run fills where available",
            runTradePnlLabel: "pending flight-recorder/fill attribution until a bounded PAPER run is approved and reconciled",
            cleanBaselineClaimed: false
          },
          brokerMutationOccurred: false,
          tradingMutationOccurred: false,
          alpacaNetworkCallOccurred: false,
          secretsValuesExposed: false
        },
        runtime: {
          label: "Mock runtime only",
          state: "MOCK_ONLY",
          processState: "MOCK_ONLY",
          activeSessionId: null,
          paperStartRefusalReason: "MOCK_DATA_NO_BACKEND",
          paperStopAllowed: false,
          safeStopStatus: "NO_ACTIVE_RUNTIME"
        },
        brokerTruth: {
          status: "MOCK_SAMPLE_NOT_BROKER_TRUTH",
          label: "Broker truth unavailable in mock mode",
          detail: "No broker portfolio truth is invented without OPERATOR_BACKEND.",
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
          brokerMutation: { label: "No broker mutation from mock readiness", occurred: false }
        },
        advanced: {
          finalLaunchReadiness: "BLOCKED",
          reasonCodes: ["MOCK_DATA_NO_BACKEND"],
          checks: [],
          paperEndpointDisplay: "https://paper-api.alpaca.markets",
          paperEndpointFamily: "paper",
          paperEndpointHost: "paper-api.alpaca.markets",
          paperEndpointBlockerCode: null,
          alpacaEndpointConfigured: false,
          alpacaEndpointSource: "MOCK_DATA",
          alpacaPaperEndpointValid: true,
          alpacaLiveEndpointBlocked: true,
          paperStartAllowed: false,
          brokerMutationOccurred: false,
          tradingMutationOccurred: false,
          liveEnabled: false,
          realMoneyEnabled: false,
          secretsValuesExposed: false,
          backendDegradedReasons: []
        }
      },
      safeStopStatus: "NO_ACTIVE_RUNTIME",
      portfolioReadAvailability: "UNAVAILABLE_MISSING_CREDENTIALS",
      backendDegradedReasons: []
    },
    paperBaseline: {
      source: "MOCK_DATA",
      schemaVersion: "paper-baseline-view-v1",
      status: "PREFLIGHT_BLOCKED_BASELINE_ADOPTION_REQUIRED",
      decision: "PAPER_BASELINE_ADOPTION_REQUIRED",
      accepted: false,
      policy: "ADOPT_EXISTING_POSITIONS_PROTECTED",
      positionCount: 10,
      positionSymbols: ["AAPL", "AMZN", "BTCUSD", "ETHUSD", "GOOGL", "NVDA", "QQQ", "SOLUSD", "SPY", "TSLA"],
      openOrderCount: 0,
      endpointFamily: "paper",
      liveLocked: true,
      realMoneyBlocked: true,
      startReady: false,
      reason: "Existing PAPER positions require explicit baseline adoption.",
      nextSafeAction: "Accept current positions as the protected PAPER baseline, then prepare a short position-aware PAPER smoke packet.",
      baselineSnapshotId: null,
      snapshotHash: null,
      acceptedAt: null,
      protectedSymbols: [],
      sameSymbolTradingPolicy: "BLOCK_BASELINE_SYMBOL_TRADES_UNTIL_RUN_LOT_TRACKING",
      pnlAttribution: {
        baselineAccountEquity: null,
        baselinePositionsValue: null,
        runIncrementalEquityPnl: null,
        runIncrementalEquityPnlLabel: "current account equity - baseline account equity; deposits/withdrawals not adjusted unless transfer data is added",
        baselineCarryPnlLabel: "baseline carry P&L from mark-to-market movement in pre-existing positions; shown separately from bot run fills where available",
        runTradePnlLabel: "pending flight-recorder/fill attribution until a bounded PAPER run is approved and reconciled",
        cleanBaselineClaimed: false
      },
      brokerMutationOccurred: false,
      tradingMutationOccurred: false,
      alpacaNetworkCallOccurred: false,
      secretsValuesExposed: false
    },
    credentials: {
      source: "MOCK_DATA",
      storePath: ".operator_secrets/provider_credentials.json",
      storeExists: false,
      configuredCount: 0,
      providerCount: 4,
      precedence: "ENV_PRESENT_OVERRIDES_LOCAL_SECRET",
      providers: [
        {
          providerId: "alpaca_paper",
          displayName: "Alpaca PAPER Broker/Data",
          configured: false,
          source: "NOT_CONFIGURED",
          fields: [
            { name: "APCA_API_KEY_ID", configured: false, source: "NOT_CONFIGURED", fingerprint: null },
            { name: "APCA_API_SECRET_KEY", configured: false, source: "NOT_CONFIGURED", fingerprint: null },
            { name: "APCA_API_BASE_URL", configured: false, source: "NOT_CONFIGURED", fingerprint: null }
          ]
        },
        {
          providerId: "openai",
          displayName: "OpenAI",
          configured: false,
          source: "NOT_CONFIGURED",
          fields: [{ name: "OPENAI_API_KEY", configured: false, source: "NOT_CONFIGURED", fingerprint: null }]
        },
        {
          providerId: "anthropic",
          displayName: "Anthropic / Claude",
          configured: false,
          source: "NOT_CONFIGURED",
          fields: [{ name: "ANTHROPIC_API_KEY", configured: false, source: "NOT_CONFIGURED", fingerprint: null }]
        },
        {
          providerId: "alpaca_news",
          displayName: "Alpaca News",
          configured: false,
          source: "NOT_CONFIGURED",
          fields: [
            { name: "APCA_API_KEY_ID", configured: false, source: "NOT_CONFIGURED", fingerprint: null },
            { name: "APCA_API_SECRET_KEY", configured: false, source: "NOT_CONFIGURED", fingerprint: null }
          ]
        }
      ]
    },
    portfolio: {
      source: "MOCK_DATA",
      dataSource: "MOCK_SAMPLE",
      status: "MOCK_SAMPLE_NOT_BROKER_TRUTH",
      unavailableReason: null,
      message: "Mock sample PAPER positions. This is not broker truth; backend mode uses broker-confirmed data or unavailable.",
      empty: false,
      dataFreshnessTs: "2026-05-26T01:38:32Z",
      brokerReadOccurred: false,
      brokerMutationOccurred: false,
      summary: {
        totalEquity: "85758.29",
        cash: "available in backend",
        buyingPower: "91187.83",
        totalMarketValue: "existing baseline market value",
        totalUnrealizedPnl: "broker-confirmed in backend",
        totalRealizedPnl: null,
        dayPnl: null,
        grossExposure: "existing baseline exposure",
        netExposure: "existing baseline exposure",
        positionCount: 10,
        openOrderCount: 0,
        largestPosition: "NVDA",
        highestRiskPosition: "BTCUSD",
        staleOrConflictedPositionCount: 0,
        brokerLocalReconciliationStatus: "BROKER_CONFIRMED_NO_LOCAL_TRUTH_PROMOTED",
        accountStatus: "ACTIVE",
        accountId: "redacted_suffix:mocked",
        currency: "USD",
        tradingBlocked: false,
        accountBlocked: false,
        transfersBlocked: false,
        patternDayTrader: false
      },
      positions: ["AAPL", "AMZN", "BTCUSD", "ETHUSD", "GOOGL", "NVDA", "QQQ", "SOLUSD", "SPY", "TSLA"].map((symbol) => ({
        symbol,
        assetClass: symbol.endsWith("USD") && !["SPY", "QQQ"].includes(symbol) ? "crypto" : "us_equity",
        quantity: "baseline",
        side: "long",
        averageEntryPrice: "broker-confirmed in backend",
        currentMarketPrice: "broker-confirmed in backend",
        costBasis: "broker-confirmed in backend",
        marketValue: "broker-confirmed in backend",
        unrealizedPnl: "broker-confirmed in backend",
        unrealizedPnlPercent: "broker-confirmed in backend",
        realizedPnl: null,
        todayPriceChange: null,
        todayPercentChange: null,
        positionAge: "UNKNOWN",
        latestFillTime: null,
        latestFillPrice: null,
        openOrderCount: 0,
        feesStatus: "UNKNOWN",
        tcaStatus: "UNKNOWN",
        slippage: null,
        source: "MOCK_SAMPLE",
        brokerConfirmed: false,
        omsReconciliationStatus: "BASELINE_ADOPTION_REQUIRED",
        dataFreshnessTs: "2026-05-26T01:38:32Z",
        tradabilityStatus: "PROTECTED_BASELINE_PENDING_ACCEPTANCE",
        riskStatus: "BASELINE_COUNTS_AGAINST_EXPOSURE",
        exposurePercentOfPortfolio: "broker-confirmed in backend"
      })),
      openOrders: [],
      positionIntelligence: ["AAPL", "AMZN", "BTCUSD", "ETHUSD", "GOOGL", "NVDA", "QQQ", "SOLUSD", "SPY", "TSLA"].map((symbol) => ({
        symbol,
        exposurePercentOfPortfolio: "broker-confirmed in backend",
        concentrationWarning: false,
        volatilityRangeWarning: "UNKNOWN",
        feeDragWarning: "UNKNOWN_FEE_DETAIL",
        slippageWarning: "UNKNOWN_SLIPPAGE_DETAIL",
        staleDataWarning: false,
        spreadLiquidityWarning: "UNKNOWN",
        correlationClusterWarning: "UNKNOWN",
        movingFloorStatus: "BASELINE_PROTECTED",
        protectiveFloorStatus: "BASELINE_PROTECTED",
        exitLogicStatus: "READ_ONLY_NO_MANUAL_EXIT_CONTROL",
        whyHolding: "Existing PAPER position pending protected baseline adoption.",
        blockersConflicts: [],
        riskStatus: "BASELINE_COUNTS_AGAINST_EXPOSURE",
        source: "MOCK_SAMPLE"
      }))
    },
    positions: [
      {
        symbol: "BTC/USD",
        assetClass: "crypto",
        brokerQuantity: "mock sample",
        source: "MOCK_SAMPLE",
        movingFloor: "ARMED",
        exitEligibility: "sell_to_close requires broker position truth"
      },
      {
        symbol: "ETH/USD",
        assetClass: "crypto",
        brokerQuantity: "mock sample",
        source: "MOCK_SAMPLE",
        movingFloor: "ARMED",
        exitEligibility: "sell_to_close requires broker position truth"
      },
      {
        symbol: "SOL/USD",
        assetClass: "crypto",
        brokerQuantity: "mock sample",
        source: "MOCK_SAMPLE",
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
      providerMode: "NOT_CONFIGURED",
      modelName: null,
      modelQuality: "FALLBACK_ONLY",
      reasoningPolicy: "FALLBACK_ONLY_LIMITED",
      modelSuitableForGovernance: false,
      modelQualityWarning: "High-reasoning model not configured. Quant/governance answers are limited.",
      routingSettings: {
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
      },
      providerRegistry: [
        { providerId: "openai", displayName: "OpenAI / GPT", status: "MISSING_CREDENTIALS", configured: false, credentialSource: "NOT_CONFIGURED", modelName: "gpt-5.5-pro", modelQuality: "HIGH_REASONING", costMode: "PAID_API_APPROVED", reasoningCapability: "highest", personaEnforced: true, implemented: true },
        { providerId: "anthropic", displayName: "Claude / Anthropic", status: "MISSING_CREDENTIALS", configured: false, credentialSource: "NOT_CONFIGURED", modelName: "claude-opus-4.7", modelQuality: "HIGH_REASONING", costMode: "PAID_API_APPROVED", reasoningCapability: "highest", personaEnforced: true, implemented: true },
        { providerId: "gemini", displayName: "Gemini / Google", status: "NOT_IMPLEMENTED", configured: false, credentialSource: "NOT_CONFIGURED", modelName: "gemini-2.5-pro", modelQuality: "HIGH_REASONING", costMode: "PAID_API_APPROVED", reasoningCapability: "high", personaEnforced: true, implemented: false },
        { providerId: "xai_grok", displayName: "Grok / xAI", status: "MISSING_CREDENTIALS", configured: false, credentialSource: "NOT_CONFIGURED", modelName: "grok-4", modelQuality: "HIGH_REASONING", costMode: "PAID_API_APPROVED", reasoningCapability: "high", personaEnforced: true, implemented: true },
        { providerId: "deepseek", displayName: "DeepSeek", status: "MISSING_CREDENTIALS", configured: false, credentialSource: "NOT_CONFIGURED", modelName: "deepseek-reasoner", modelQuality: "HIGH_REASONING", costMode: "PAID_API_APPROVED", reasoningCapability: "high", personaEnforced: true, implemented: true },
        { providerId: "kimi_moonshot", displayName: "Kimi / Moonshot", status: "MISSING_CREDENTIALS", configured: false, credentialSource: "NOT_CONFIGURED", modelName: "kimi-k2-thinking", modelQuality: "HIGH_REASONING", costMode: "PAID_API_APPROVED", reasoningCapability: "high", personaEnforced: true, implemented: true },
        { providerId: "local_openai_compatible", displayName: "Local OpenAI-compatible", status: "MISSING_CREDENTIALS", configured: false, credentialSource: "NOT_CONFIGURED", modelName: "local-model", modelQuality: "LOCAL_UNEVALUATED", costMode: "LOCAL_INFRA_COST", reasoningCapability: "local_unevaluated", personaEnforced: true, implemented: true },
        { providerId: "deterministic_local", displayName: "Deterministic Local", status: "READY", configured: true, credentialSource: "NOT_REQUIRED", modelName: "deterministic-local-guide", modelQuality: "FALLBACK_ONLY", costMode: "FREE_LOCAL", reasoningCapability: "limited_operator_guidance", personaEnforced: true, implemented: true },
        { providerId: "supreme_board_packet", displayName: "Supreme Board Packet", status: "READY", configured: true, credentialSource: "NOT_REQUIRED", modelName: "chatgpt-pro-manual", modelQuality: "HIGH_REASONING", costMode: "CHATGPT_PRO_MANUAL", reasoningCapability: "manual_highest_reasoning_workflow", personaEnforced: true, implemented: true }
      ],
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
            { name: "APCA_API_KEY_ID", configured: false, source: "NOT_CONFIGURED", fingerprint: null },
            { name: "APCA_API_SECRET_KEY", configured: false, source: "NOT_CONFIGURED", fingerprint: null }
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
          envStatus: [{ name: "OPENAI_API_KEY", configured: false, source: "NOT_CONFIGURED", fingerprint: null }],
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
