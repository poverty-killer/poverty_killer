# BUNDLE 25Y - Alpaca Paper Tiny Order Planning / Arming

Verdict: PASS

Changed files:
- `tests/test_alpaca_paper_tiny_order_planning_arming.py`
- `reports/bundle_25y_alpaca_paper_tiny_order_planning_arming.md`

Tests run:
- `/tmp/pk25i-venv/bin/python -m pytest tests/test_alpaca_paper_tiny_order_planning_arming.py -q -s --tb=short`
# result
  - `5 passed, 72 warnings in 5.38s`
- `/tmp/pk25i-venv/bin/python -m pytest tests/test_whole_bot_replay_regime_stress.py tests/test_whole_bot_contribution_activation_harness.py tests/test_broker_truth_whole_bot_contribution_readiness.py tests/test_alpaca_paper_read_only_broker_truth.py tests/test_live_read_only_adapter_config_gate.py tests/test_micro_live_dry_run_readiness_harness.py tests/test_runtime_reservation_bootstrap.py tests/test_order_lifecycle_replay.py tests/test_execution_sr_decimal.py -q --tb=short`
# result
  - `59 passed, 80 warnings in 12.41s`

Tiny paper order planning / arming proven:
- Planned broker/environment:
  - Broker: Alpaca.
  - Environment: PAPER only.
  - Endpoint: `https://paper-api.alpaca.markets`.
  - Future mutation endpoint, if separately approved in 25Z: `POST /v2/orders`.
- Planned symbol/side:
  - Symbol: `AAPL`.
  - Side: `BUY`.
  - One symbol only.
  - Short selling forbidden.
- Planned order type/time in force:
  - Order type: `LIMIT` only.
  - Time in force: `DAY`.
  - Market orders forbidden.
  - Extended hours false.
  - Bracket/OCO/OTO false.
  - Margin/leverage forbidden.
- Planned notional/quantity constraints:
  - Max notional cap: `$5.00`.
  - One order only.
  - No retry storm.
  - No auto-resubmit.
  - Exact future quantity is deferred to 25Z and must be derived from a fresh read-only quote/NBBO and broker constraints immediately before submit.
  - If fractional/minimum quantity/notional constraints are unavailable or fail validation, 25Z must abort.
- Limit price rule:
  - No live/future limit price was invented in 25Y.
  - 25Z must compute a bounded limit price from a fresh read-only quote/NBBO immediately before any submit.
  - 25Z must abort on stale quote, missing quote, wide spread, missing quantity, missing broker constraint validation, or price outside Board cap.
- Preflight read-only checks:
  - `APCA_API_BASE_URL` exactly `https://paper-api.alpaca.markets`.
  - `APCA_API_KEY_ID` present.
  - `APCA_API_SECRET_KEY` present and never printed/written.
  - `GET /v2/account`.
  - `GET /v2/positions`.
  - `GET /v2/orders?status=open`.
  - `GET /v2/clock`.
  - Account reachable, paper status acceptable, trading not blocked if field exists, currency known, cash/buying power known from broker truth.
  - Open orders known; no open broker order for `AAPL`.
  - Positions known; any existing `AAPL` position requires explicit Board decision.
  - Empty positions/open orders are valid broker truth.
  - Bot-local reservations for `AAPL` absent or reconciled, no pending runtime order intent, PaperBroker durable state clean or isolated.
  - Kill switch clear, Board approval present, operator approval present, single order flag, single symbol flag, max notional cap present.
- No-go blockers:
  - Missing Board approval.
  - Missing operator approval.
  - Kill switch active.
  - Live endpoint configured.
  - Missing Alpaca paper credentials.
  - Account endpoint unavailable.
  - Account status blocked.
  - Missing cash/buying power.
  - Max notional missing or above `$5.00`.
  - Market order requested.
  - Short order requested.
  - Multiple orders.
  - Multiple symbols.
  - Extended hours requested.
  - Open broker order exists for `AAPL`.
  - Local reservation exists without broker order.
  - Broker position exists but plan assumes flat.
  - Quote/limit/quantity missing in future execution packet.
  - Live reservation lifecycle enabled.
  - broker_adapter/live_broker activation attempted.
  - Any POST/DELETE/PATCH attempted in 25Y.
- Telemetry/recovery/reconciliation plan:
  - Future decision intent format: `pk25z:{symbol}:{side}:{tif}:{ts_ns}`.
  - Future client order id format: `pk25z-paper-aapl-buy-limit-day-{ts_ns}`.
  - FillRecorder fields required: client order id, broker order id, symbol, side, quantity, fill price, fill timestamp, commission, source.
  - Reservation candidate fields required: decision uuid, client order id, symbol, side, quantity, price basis, notional basis.
  - Recovery snapshot fields required: read-only broker snapshot, local reservation ledger, order lifecycle replay context.
  - Post-order reconciliation expectations for 25Z: read-only open orders, positions, and account after submit.
- Future execution packet requirements:
  - 25Z must have separate explicit Board approval before any `POST /v2/orders`.
  - 25Z must recompute quote, limit price, quantity, broker constraints, cash/buying power, open orders, positions, and local reservations immediately before submit.
  - 25Y PASS is not permission to execute.

Adversarial cases proven:
- Plan with market order fails.
- Plan with live endpoint fails.
- Plan with missing Board approval fails.
- Plan with missing operator approval fails.
- Plan with kill switch active fails.
- Plan with too-large notional fails.
- Plan with multiple orders fails.
- Plan with multiple symbols fails.
- Plan with open broker order conflict fails.
- Plan with existing position conflict fails.
- Plan with missing telemetry plan fails.
- Plan with missing client_order_id plan fails.
- Plan with live reservation lifecycle enabled fails.
- Plan with broker_adapter/live_broker activation attempt fails.
- Plan with missing credentials fails.
- Plan with unavailable account endpoint fails.
- Plan with blocked account status fails.
- Plan with missing cash/buying power fails.
- Attempted POST/DELETE/PATCH in 25Y is trapped as forbidden mutation.

What this does NOT authorize:
- No order placement.
- No cancel.
- No replace.
- No POST.
- No DELETE.
- No PATCH.
- No live endpoint.
- No live mode.
- No live reservation lifecycle.
- No broker_adapter/live_broker activation.
- No invented limit price.
- No invented quote.
- No invented PnL, slippage, net edge, profitability, or alpha claim.
- No production order readiness without separate 25Z Board approval.

Recommended next packet:
- 25Z - Board-Approved Alpaca Paper Tiny Order Execution
- Why this is the single next seam:
  - 25Y proves the future tiny order plan and arming gates without mutation.
  - The next capability seam is one separately approved Alpaca PAPER `POST /v2/orders` using the exact 25Y constraints, fresh read-only preflight, bounded quote-derived limit price, and immediate reconciliation.
  - 25Z must still be separately authorized because 25Y is planning only.

Authority boundaries confirmed:
- Planning/arming only.
- Alpaca PAPER endpoint only.
- Read-only preflight GETs only in 25Y.
- No POST/DELETE/PATCH.
- No order submit/cancel/replace.
- No live endpoint fallback.
- No live mode.
- No live reservation lifecycle.
- No broker_adapter/live_broker activation.
- No NetEdgeGovernor or TradeEfficiencyGovernor veto activation.
- No StrategyAllocator/SovereignGovernor/SovereignExecutionGuard activation.
- No thresholds changed.
- No routing/execution broadened.
- No duplicate authority introduced.

Confirmations:
- Production behavior changed: no
- If yes, exact helper only:
  - n/a
- Real broker/network call made: yes, Alpaca PAPER read-only only
- Credentials used: yes, env vars only
- Secrets printed/written/committed: no
- Live endpoint used: no
- Paper endpoint used: yes
- Order placed: no
- Cancel sent: no
- Replace sent: no
- HTTP methods used:
  - GET only
- Live mode used: no
- broker_adapter edited/activated: no
- live_broker edited/activated: no
- Live reservation lifecycle activated: no
- Dormant governors activated: no
- Economics veto activated: no
- Thresholds changed: no
- Routing/execution broadened: no
- Duplicate authority introduced: no
- Git staging/commit/push/reset/clean/stash/delete: none
