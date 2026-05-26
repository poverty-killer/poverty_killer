# PAPER Operator Control Panel Blueprint

## Purpose

This document defines the Phase 1 blueprint for the Poverty Killer operator UI.
It is a live-ready architecture with PAPER operation enabled first. It is not a
temporary PAPER-only toy UI. The design represents SHADOW, BACKTEST, and future
LIVE capability lanes, but live operation remains locked until a separate
governance packet, server-side authority, and explicit approval allow it.

This blueprint does not implement UI code, backend endpoints, control routes,
broker logic, runtime logic, OMS logic, alpha logic, state changes, log changes,
or database changes.

Current validation baseline:

- Base: `fe4697a` - `Add broker fill hydration and TCA ledger`
- 3-hour OMS validation: PASS
- 300-second fill/TCA smoke: PASS
- 20-minute fill/TCA run: CONDITIONAL PASS, safety and OMS clean, no fresh fill
- 2-hour fill/TCA run: CONDITIONAL PASS, safety and OMS clean, 17 lawful PAPER
  BUY orders, 15 cancels, 4 fresh broker-backed fills hydrated, no fake
  fills/fees/TCA, and TCA remained UNKNOWN only where Alpaca did not provide
  fee/currency detail

The UI must reflect the current maturity: the bot can lawfully submit and cancel
PAPER orders through governed paths, OMS reconciliation works, broker-backed fill
ledger records exist, TCA can honestly remain UNKNOWN, and live trading is not
approved.

## Non-Negotiable UI Doctrine

- Read-only truth first.
- Governed controls second.
- Capability lanes may be visible before activation.
- Disabled and locked states must be explicit and informative.
- No manual trades in v1.
- No live controls active in v1.
- No forced trades.
- No bypassing bot authority.
- No bypassing guardrails.
- UI sends operator intent only.
- Existing bot authorities decide what is allowed.
- Server-side authority decides allow/refuse.
- Every operator action must create audit evidence.
- Broker-confirmed truth beats local UI truth.
- MarketTruthSnapshot beats stale/backfill/synthetic truth.
- Conflicts fail closed.
- No UI-only broker truth.
- No UI-only P&L truth.
- UI must reflect bot truth, not invent truth.
- UI must not become a second trading engine.

## Authority Model

The UI is an observation and intent surface. It never owns trading authority.

Authority chain:

1. Server-side governance and mode authority
2. Current runtime profile and launch authority
3. MarketTruthSnapshot for executable market truth
4. Broker gateway / adapter for broker endpoint and order truth
5. OMS reconciliation for post-ack order, fill, and terminal state truth
6. Risk governor, pre-trade guardrails, NetEdge, sell authority, and kill switch
7. UI display and operator intent

The UI may display, filter, and explain authority. It must not create its own
authority or infer broker, market, P&L, fill, fee, position, or live-readiness
truth.

## Mode and Capability Model

Mode states shown by the UI:

- `PAPER_ENABLED`: PAPER runtime is available and can be observed. Governed PAPER
  controls may be added later through intent endpoints.
- `SHADOW_AVAILABLE`: read-only or simulated shadow lane is available.
- `SHADOW_LOCKED`: shadow lane is represented but unavailable.
- `BACKTEST_AVAILABLE`: backtest/replay lane is available.
- `BACKTEST_LOCKED`: backtest/replay lane is represented but unavailable.
- `LIVE_LOCKED`: live lane is unavailable and refused.
- `LIVE_READINESS_PENDING`: live-readiness checks are visible but not complete.
- `LIVE_READY_BUT_DISABLED`: prerequisites may be passing, but separate approval
  has not enabled live.
- `LIVE_ENABLED`: future-only state after separate approval, server-side
  authority, live endpoint authority, real-money authority, and risk approval.

V1 live behavior:

- A live button may be shown only as locked/disabled.
- If clicked later, it opens the read-only readiness checklist.
- It must not call live broker endpoints.
- It must not mutate runtime mode.
- It must not write live config.
- It must return/refuse with reason `LIVE_NOT_APPROVED`.

## Visual Direction

- Desktop-first.
- Dark mode.
- Dense but clean.
- Terminal/operator feel.
- Institutional trading desk style.
- High information density.
- Fast status recognition.
- Minimal marketing copy.
- Clear red/yellow/green/gray status language.
- Safety and truth visible at all times.
- Beginner-friendly labels for Shan without flattening the system.

Color language:

- Green: safe, active, fresh, passed, PAPER confirmed, broker truth confirmed.
- Yellow: degraded, declined, weak evidence, missing optional module, warning,
  no trade, unknown but honest.
- Red: blocked, stale, conflict, live endpoint, real-money, mutation risk, broker
  safety failure.
- Gray: not applicable, idle, no position, no evidence, disabled.

## Global Layout

Left navigation:

- Command Center
- P&L / Net Profit
- Positions & Orders
- Bot Activity Control
- Signal & Decision Lab
- Market Data Truth
- Risk & Governor
- World Awareness
- Audit Log
- Diagnostics
- Live Readiness

Top status bar, always visible:

- Mode
- Profile
- Broker
- Endpoint
- Active universe
- Runtime state
- POST count
- Mutation count
- Live blocked
- Real-money blocked

Main panel:

- Screen-specific cards, tables, timelines, and detail drawers.

Right rail:

- Current alerts
- Dominant blocker
- Last decision
- Last broker boundary event
- Needs approval

Always-visible critical indicators:

- PAPER mode
- live endpoint blocked
- real-money blocked
- broker POST count
- `/v2/orders` count
- mutation authorized count
- active profile
- active universe and asset classes

## Core Operator Questions

The UI must let the operator answer quickly:

- Is the bot running?
- What mode is it in?
- Is it PAPER or live?
- Why is live locked?
- What must be proven before live?
- Is the broker endpoint safe?
- Is market data fresh?
- What symbols are active?
- What decisions are being made?
- Why did the bot trade or not trade?
- What is NetEdge saying?
- What positions and orders exist?
- What fills happened?
- What is TCA saying?
- Is profit protected?
- Did any safety boundary trip?
- Did any broker mutation happen?
- What needs approval?

## Screen 1: Command Center

Purpose: single operational overview for runtime, authority, safety, and current
decision state.

Status states:

- `READY`
- `RUNNING`
- `DEGRADED`
- `BLOCKED`
- `NEEDS_APPROVAL`

Must show:

- Runtime mode: PAPER / SHADOW / BACKTEST / LIVE_DISABLED
- Active profile
- Broker route
- Broker endpoint
- Market data route
- Active universe
- Runtime watchlist
- Session uptime
- Last heartbeat
- Last frame time
- Last market snapshot time
- POST/mutation status
- Live endpoint status
- Real-money status
- Physical fuse state
- Credential authority state
- Current dominant blocker
- Last decision outcome
- Current safety verdict

Important cards:

- Mode & Authority
- Runtime Health
- Broker Boundary
- Market Data Health
- Current Decision State
- Safety / Fuse State
- Alerts / Needs Approval

The Command Center must never hide live endpoint, real-money, or mutation risk
status behind secondary navigation.

## Screen 2: P&L / Net Profit

Purpose: show broker-confirmed performance and cost-adjusted economic truth.

Rules:

- Broker-confirmed P&L only.
- No fake P&L.
- No local-only profit claims.
- Estimated values must be clearly labeled as estimated.
- Broker-confirmed values must be clearly labeled as broker-confirmed.
- Net profit must include costs when cost data is available.
- If fee/currency detail is missing, TCA and realized edge stay UNKNOWN.

Must show:

- Realized P&L
- Unrealized P&L
- Net P&L
- Fees
- Spread cost
- Slippage estimate and actual slippage where available
- Latency drag
- Gross edge
- NetEdge
- NetEdge `ALLOW` / `DENY` / `UNKNOWN` / `ALLOW_REDUCED`
- Trade count
- Win/loss
- Average trade P&L
- Max drawdown
- Current exposure
- Capital used
- Available buying power
- Open risk
- Closed trade history

Truth labeling:

- `BROKER_CONFIRMED`
- `ESTIMATED`
- `UNKNOWN_INSUFFICIENT_BROKER_DETAIL`
- `UNAVAILABLE_FROM_BROKER`
- `CONFLICT_FAIL_CLOSED`

## Screen 3: Positions & Orders

Purpose: make broker-backed position, order, fill, and reconciliation truth
inspectable.

Rules:

- Broker position truth is canonical.
- Local state must be reconciled against broker truth.
- Local-only state is diagnostic, not authority.
- No selling unless broker-backed inventory exists.

Must show:

- Broker-backed positions
- Open orders
- Filled orders
- Rejected orders
- Canceled orders
- Order ID mappings
- Reservations
- Reconciliation status
- Broker/local conflicts
- MovingFloor state
- Floor price
- Floor breach status
- Exit/reduce eligibility

Rows should expose:

- Symbol
- Asset class
- Broker quantity
- Local diagnostic quantity
- Average price where broker-confirmed
- Current price source
- Open order IDs
- Fill ledger coverage
- Terminal lifecycle state
- Reconciliation reason codes

## Screen 4: Bot Activity Control

V1 posture: read-only first, governed PAPER controls later.

Must show:

- Current process state
- Last launch command
- Duration
- Runtime profile
- Watchlist
- Preflight result
- Credential status without printing secrets
- Broker route
- Market data provider
- Start/stop history
- Last shutdown reason
- Last error

Allowed later PAPER controls:

- Start bounded PAPER run
- Stop current PAPER run
- Select approved PAPER profile
- Select approved watchlist
- Request status snapshot
- Export run report

Hard exclusions:

- No active live start button.
- No real-money start button.
- No force order.
- No bypass guardrail.
- No manual trade.

Future controls must be intent endpoints. The UI sends a request such as
`/intent/paper/start`; the server validates authority and returns allow/refuse.

## Screen 5: Signal & Decision Lab

Purpose: primary diagnostic screen. It explains why BUY, SELL, or NO_TRADE
happened.

Must show:

- DecisionFrame list
- `frame_id`
- Symbol
- Asset class
- `candle_id`
- `snapshot_id`
- Profile
- Frame output
- Opportunity verdict
- Raw opportunity score
- Final opportunity score
- Module evidence
- Blockers
- Penalties
- Reason codes
- NetEdge result
- DecisionCompiler result
- `submit_signal` status

Module evidence rows:

- MarketTruthSnapshot
- StrategySignal
- StrategyVote
- SignalFusion
- ShansCurve
- ShadowFront
- SectorRotation
- LiquidityVoid
- GammaFront
- StrategyRouter
- NetEdgeGovernor
- PreTradeGuardrails
- MovingFloor
- OrderRouter / BrokerGateway diagnostics

Each row must show:

- Status
- Direction
- Confidence
- Score contribution
- Penalty
- Reason code
- Timestamp
- Evidence age
- Source snapshot

Action taxonomy:

- `buy_to_open`
- `sell_to_close`
- `sell_short`
- `buy_to_cover`
- `reduce`
- `exit`
- `bearish_no_long`
- `no_trade`

Bearish signal while flat must show as bearish/no-long or short-unavailable, not
as executable sell.

## Screen 6: Market Data Truth

Purpose: expose whether executable market truth exists and why.

Must show:

- Provider status
- Coinbase status
- Kraken status
- Candle freshness
- Book freshness
- Latest closed candle
- In-progress candle block
- Stale data block
- Backfill block
- Synthetic/replay label
- Provider latency
- Book RTT
- Candle RTT
- `snapshot_id`
- `candle_id`
- Candle close time
- Receive time
- `provider_id`
- `executable_market_truth` true/false
- Source type
- Reason codes

Hard visual warnings:

- Stale
- Backfill
- Synthetic
- Replay
- Candle not closed
- Provider mismatch
- Snapshot conflict
- Market truth missing

The screen must distinguish stale/observe-only evidence from executable market
truth. It must not imply that backfill, replay, synthetic, stale, or mismatched
truth is executable.

## Screen 7: Risk & Governor

Purpose: explain hard gates, economic gates, score penalties, and authority.

Must show:

- Hard gate status
- Broker truth
- Market truth
- Quote/session truth
- Sell authority
- Position authority
- Pre-trade guardrails
- Exposure limits
- Max position size
- Buying power
- Concentration limits
- Correlation/exposure
- Unsupported action
- Unsupported portal
- Live endpoint block
- Real-money block
- Physical fuse
- Mutation authority
- Safe mode

Gate categories:

- `HARD_GATE`
- `ECONOMIC_GATE`
- `SCORE_PENALTY`
- `SIZE_ADJUSTER`
- `URGENCY_ADJUSTER`
- `EXIT_ONLY`
- `TELEMETRY_ONLY`

Risk decisions:

- `ALLOW`
- `DENY`
- `ALLOW_REDUCED`
- `UNKNOWN`
- `BLOCKED`

## Screen 8: Audit Log

Purpose: immutable operator-facing evidence timeline.

Must show:

- Runtime events
- Operator actions
- Preflight results
- Profile activation
- Mode changes
- Start/stop events
- Decision frames
- Compiler results
- NetEdge results
- Guardrail blocks
- Broker boundary events
- Broker mutation counts
- Order attempts
- Safety alerts
- Errors/warnings

Every row:

- Timestamp
- Event type
- Severity
- Component
- Symbol
- `frame_id`
- `decision_id`
- Action
- Result
- Reason code
- Source
- Audit hash/id if available

Audit must answer:

- Who or what requested this?
- What mode was active?
- What authority allowed or denied it?
- Did broker mutation happen?
- Was endpoint PAPER or live?
- Was this replay, backtest, or runtime?
- What evidence supported the outcome?

## Screen 9: World Awareness / External Intelligence

Purpose: show advisory external intelligence without giving it execution
authority.

Architecture:

- `world_awareness` is the front door for event/news/advisory feeds.
- Market data stays in `app/data` and the market feed router.
- Broker execution stays separate.
- UI shows world awareness as advisory evidence unless promoted by bot authority.

Must show:

- News/event feed status
- Source
- Timestamp
- Symbol/topic mapping
- Relevance
- Sentiment
- Confidence
- Advisory impact
- Whether it contributed to DecisionFrame
- Whether it was ignored, stale, or untrusted

Rules:

- External news cannot directly trade.
- External feed cannot bypass market truth.
- External feed cannot bypass NetEdge.
- External feed cannot bypass guardrails.
- External feed contributes evidence only.

## Screen 10: System Diagnostics

Purpose: make runtime environment and repo health visible.

Must show:

- Process status
- Python version
- Git commit hash
- Dirty worktree indicator
- Active config
- Environment sanity
- Credentials present/not present without printing secrets
- DB status
- Log paths
- Last stdout/stderr
- Test status if available
- Module load/import status
- Missing untracked runtime dependency warning
- Feature flags
- Profile flags
- Latency metrics

Important warning:

- UI must warn if the running local tree differs from the pushed commit.

## Screen 11: Live Readiness / Activation Gate

Purpose: show live-readiness without activating live.

V1 status: read-only, locked.

Must show:

- `LIVE_LOCKED` status
- Current git commit
- Dirty worktree warning
- Broker endpoint authority
- Credential authority
- Physical fuse
- Real-money approval status
- Risk governor status
- Account status
- Position reconciliation
- Order reconciliation
- Fill ledger health
- TCA / realized edge status
- Market truth health
- Kill switch status
- Audit logging status
- Operator approval status
- Missing prerequisites
- Passed prerequisites
- Reason codes
- Authority chain
- Last live-readiness audit
- What would be required before live activation
- Reason live is currently refused

No active live start control exists in v1.

Future live controls require:

- Separate governance packet
- Server-side authority
- Audit events
- Explicit user approval
- Live endpoint authority
- Real-money authority
- Risk governor approval
- Kill switch readiness

Live readiness states:

- `LIVE_LOCKED`
- `LIVE_READINESS_PENDING`
- `LIVE_READY_BUT_DISABLED`
- `LIVE_ENABLED` future only

Readiness refusal examples:

- `LIVE_NOT_APPROVED`
- `LIVE_ENDPOINT_AUTHORITY_MISSING`
- `REAL_MONEY_AUTHORITY_MISSING`
- `KILL_SWITCH_NOT_READY`
- `DIRTY_WORKTREE_BLOCKS_LIVE`
- `BROKER_RECONCILIATION_NOT_CLEAN`
- `FILL_LEDGER_NOT_PROVEN`
- `TCA_NOT_PROVEN`
- `MARKET_TRUTH_NOT_HEALTHY`
- `OPERATOR_APPROVAL_MISSING`

## Read-Only Data Contracts

These contracts are conceptual Phase 2 backend schemas. They are read-only in v1
unless explicitly marked as future intent endpoints. This blueprint does not
implement them.

### `/status`

Fields:

- `bot_status`
- `runtime_state`
- `mode_state`
- `active_profile`
- `last_heartbeat_ts`
- `session_uptime_s`
- `dominant_blocker`
- `safety_verdict`
- `needs_approval`

### `/runtime`

Fields:

- `process_state`
- `launch_command`
- `duration_seconds`
- `started_at`
- `shutdown_reason`
- `bounded_timer_started`
- `bounded_duration_elapsed`
- `active_config_hash`
- `runtime_commit`

### `/profile`

Fields:

- `active_threshold_profile`
- `profile_enabled`
- `paper_only`
- `thresholds`
- `threshold_change_reason_codes`
- `activation_status`
- `activation_refusal_reason`

### `/universe`

Fields:

- `symbols`
- `asset_classes`
- `venues`
- `runtime_watchlist`
- `universe_source`
- `excluded_symbols`
- `exclusion_reason_codes`

### `/market-truth`

Fields:

- `snapshot_id`
- `symbol`
- `book_ts_ns`
- `candle_id`
- `candle_close_ts_ns`
- `provider_id`
- `receive_ts_ns`
- `book_fresh`
- `candle_fresh`
- `executable_market_truth`
- `source_type`
- `snapshot_status`
- `snapshot_reason_codes`
- `book_rtt_ms`
- `candle_rtt_ms`

### `/decision-frames`

Fields:

- `frame_id`
- `snapshot_id`
- `symbol`
- `asset_class`
- `candle_id`
- `created_at_ns`
- `expires_at_ns`
- `active_threshold_profile`
- `frame_output`
- `frame_status`
- `frame_reason_codes`
- `raw_opportunity_score`
- `final_opportunity_score`
- `opportunity_verdict`

### `/module-evidence`

Fields:

- `frame_id`
- `module_name`
- `authority_class`
- `status`
- `signal`
- `confidence`
- `score_delta`
- `penalty`
- `reason_codes`
- `snapshot_id`
- `candle_id`
- `metadata`

### `/netedge`

Fields:

- `frame_id`
- `decision_id`
- `symbol`
- `side`
- `gross_edge`
- `modeled_cost`
- `net_edge`
- `decision`
- `reason_code`
- `sizing_multiplier`
- `fee_bps`
- `spread_bps`
- `slippage_bps`
- `latency_drag_bps`
- `realized_vs_modeled_status`

### `/risk`

Fields:

- `hard_gate_status`
- `economic_gate_status`
- `pre_trade_guardrail_status`
- `sell_authority_status`
- `quote_session_truth`
- `position_authority`
- `broker_truth`
- `market_truth`
- `mutation_authority`
- `physical_fuse`
- `kill_switch`
- `reason_codes`

### `/positions`

Fields:

- `symbol`
- `asset_class`
- `broker_quantity`
- `average_entry_price`
- `market_value`
- `unrealized_pnl`
- `position_source`
- `reconciliation_status`
- `moving_floor_status`
- `exit_eligibility`

### `/orders`

Fields:

- `client_order_id`
- `broker_order_id`
- `decision_id`
- `frame_id`
- `symbol`
- `side`
- `action_semantics`
- `order_type`
- `time_in_force`
- `lifecycle_state`
- `broker_status`
- `submitted_at`
- `updated_at`
- `reconciliation_status`

### `/fills`

Fields:

- `fill_id`
- `broker_activity_id`
- `broker_order_id`
- `client_order_id`
- `decision_id`
- `symbol`
- `side`
- `quantity`
- `price`
- `fill_timestamp`
- `fee_amount`
- `fee_currency`
- `source`
- `hydration_status`
- `hydration_reason_code`
- `conflict_status`

### `/tca`

Fields:

- `fill_id`
- `decision_id`
- `frame_id`
- `modeled_entry_price`
- `fill_price`
- `quantity`
- `notional`
- `spread_at_decision`
- `slippage`
- `slippage_bps`
- `fee_amount`
- `fee_bps`
- `decision_to_ack_latency_ms`
- `ack_to_fill_latency_ms`
- `realized_entry_cost`
- `realized_vs_modeled_netedge`
- `execution_quality_verdict`

### `/pnl`

Fields:

- `realized_pnl`
- `unrealized_pnl`
- `net_pnl`
- `gross_pnl`
- `fees`
- `spread_cost`
- `slippage_cost`
- `latency_drag`
- `source`
- `source_status`
- `unknown_reason_codes`

### `/moving-floor`

Fields:

- `symbol`
- `position_truth_status`
- `position_quantity`
- `floor_phase`
- `floor_price`
- `highest_price_seen`
- `breach_status`
- `protective_exit_candidate`
- `sell_to_close_authority`
- `reason_codes`

### `/audit-log`

Fields:

- `audit_id`
- `timestamp`
- `event_type`
- `severity`
- `component`
- `symbol`
- `frame_id`
- `decision_id`
- `action`
- `result`
- `reason_code`
- `authority`
- `endpoint_mode`
- `mutation_occurred`
- `source`

### `/world-awareness`

Fields:

- `event_id`
- `source`
- `timestamp`
- `topic`
- `symbol_map`
- `relevance`
- `sentiment`
- `confidence`
- `advisory_impact`
- `decision_frame_contribution`
- `status`
- `reason_codes`

### `/diagnostics`

Fields:

- `python_version`
- `git_commit`
- `dirty_worktree`
- `active_config`
- `credentials_present`
- `db_status`
- `log_paths`
- `last_stdout_line`
- `last_stderr_line`
- `test_status`
- `module_import_status`
- `feature_flags`
- `profile_flags`
- `latency_metrics`

### `/readiness/live`

Read-only in v1.

Fields:

- `live_state`
- `current_git_commit`
- `dirty_worktree`
- `broker_endpoint_authority`
- `credential_authority`
- `physical_fuse`
- `real_money_approval_status`
- `risk_governor_status`
- `account_status`
- `position_reconciliation`
- `order_reconciliation`
- `fill_ledger_health`
- `tca_realized_edge_status`
- `market_truth_health`
- `kill_switch_status`
- `audit_logging_status`
- `operator_approval_status`
- `passed_prerequisites`
- `missing_prerequisites`
- `reason_codes`
- `authority_chain`
- `last_live_readiness_audit`
- `required_before_activation`
- `live_refusal_reason`

## Future Intent Endpoints

These are future server-side authority contracts. They are not direct action
endpoints, and this blueprint does not implement them.

- `/intent/paper/start`
- `/intent/paper/stop`
- `/intent/snapshot/export`
- Future only: `/intent/live/request-enable`
- Future only: `/intent/live/start`
- Future only: `/intent/emergency-stop`

Every intent endpoint must:

- Validate authority server-side.
- Emit an audit event.
- Return allow/refuse.
- Include refusal reason.
- Never bypass the bot engine.
- Never call broker directly from UI logic.
- Never allow live mutation without future explicit approval and live authority.

## Build Order

Phase 1 - Blueprint only:

- Create this report.
- No app code.
- No runtime changes.
- No endpoint implementation.

Phase 2 - Read-only backend contracts:

- Define or expose schemas for status, runtime, universe, market truth, decision
  frames, module evidence, NetEdge, risk, positions/orders, fills/TCA, audit log,
  world awareness, diagnostics, and live readiness.
- Keep `/readiness/live` read-only.

Phase 3 - Static UI mock:

- Create desktop-first dark mock using sample data.
- No active broker controls.
- No runtime mutation.

Phase 4 - Live read-only UI:

- Connect UI to actual runtime telemetry.
- Still no controls.
- No broker mutation path.

Phase 5 - Governed PAPER controls:

- Add start/stop/status for bounded PAPER only.
- Controls require confirmation, server-side authority, and audit events.

Phase 6 - Profit defense view:

- Show MovingFloor and position protection state.
- Protective-only truth remains broker-position-backed.

Phase 7 - External awareness view:

- Show `world_awareness` advisory/event feed.
- External intelligence remains evidence-only.

Phase 8 - Future live-readiness activation:

- Only after separate approval.
- Live controls remain server-gated.
- Live endpoint and real-money authority remain explicit hard requirements.

## Acceptance Criteria

The blueprint is acceptable only if:

- It avoids a rebuild later.
- It defines a full live-ready architecture.
- Live capabilities are represented but locked.
- PAPER operation is the first enabled path.
- No live operation can be activated from UI v1.
- No manual trade controls exist in v1.
- No force trade exists ever.
- Every future control uses audited intent plus server authority.
- UI shows why live is locked.
- UI shows what must be proven before live.
- UI remains truth-first and broker/market-authority grounded.
- Operator can see if bot is safe to run.
- Operator can see PAPER vs live clearly.
- Operator can see active profile.
- Operator can see active universe and asset classes.
- Operator can see market truth freshness.
- Operator can see every DecisionFrame.
- Operator can see why BUY/SELL/NO_TRADE happened.
- Operator can see NetEdge breakdown.
- Operator can see broker-backed positions/orders.
- Operator can see broker-backed fills/TCA status.
- Operator can see MovingFloor protection.
- Operator can see all hard gate failures.
- Operator can see broker mutation counts.
- Operator can see audit log.
- UI cannot bypass bot authority.
- UI cannot hide safety problems.

## Phase 1 Non-Interference Statement

This Phase 1 blueprint is report-only. It does not touch:

- Runtime process
- Broker code
- OMS code
- Execution code
- Alpha/strategy code
- Backend endpoint code
- Frontend implementation code
- Logs
- State
- Databases
- Secrets
- Quarantine

The blueprint is safe to create while a PAPER run is active because it writes only
the report file and does not read or modify active runtime artifacts.
