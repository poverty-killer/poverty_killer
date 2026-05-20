# Seam 7A Local Worktree Asset Recovery

## Scope

Current pre-closeout HEAD: `7fd13b9`

Recovered local ghost assets:

- `app/strategies/moving_floor.py`
- `app/risk/net_edge_governor.py`
- `app/risk/trade_efficiency_governor.py`

Added validation:

- `tests/test_seam7a_local_worktree_asset_recovery.py`

This seam did not wire these assets into runtime execution, did not change thresholds, and did not add broker mutation behavior.

## File Truth

The three recovered assets were present as untracked local files at closeout discovery and were non-empty source files:

- `app/strategies/moving_floor.py`: 571 lines
- `app/risk/net_edge_governor.py`: 254 lines
- `app/risk/trade_efficiency_governor.py`: 325 lines

`git ls-files --stage` returned no tracked entries for the three assets before staging, confirming they were local ghost assets relative to the current HEAD.

## Intent And Authority

### TopologicalMovingFloor

`app/strategies/moving_floor.py` defines a topology-aware moving floor strategy kernel. It tracks price/floor state, detects floor initialization, ratchet-up, breach, and suppressed bad-book events, and can emit a protective recommendation on topological breach.

Authority classification:

- strategy/protective evidence producer
- not an execution engine
- not an order router
- not a broker gateway
- not a reconciliation authority

The `SignalDirection.SHORT` output is documented in the asset as structural exit/protection evidence, not authorization to open autonomous short exposure. Any later wiring must validate existing exposure and pass the normal guardrail, compiler, execution, router, broker, truth, and reconciliation path.

### NetEdgeGovernor

`app/risk/net_edge_governor.py` defines the per-trade economic admissibility kernel. It evaluates supplied gross edge, explicit execution costs, adversarial burdens, confidence, validity window, sleeve efficiency, and kill-switch state.

Authority classification:

- economic admissibility kernel
- veto/deny capable
- sizing multiplier contributor
- not an execution engine
- not an order router
- not a broker gateway
- not a reconciliation authority

It does not invent fees, slippage, net edge, profitability, or PnL. It evaluates only supplied economic truth.

### TradeEfficiencyGovernor

`app/risk/trade_efficiency_governor.py` defines the rolling sleeve/system efficiency governor. It records supplied trade-result metrics into bounded O(1) rolling windows and transitions sleeves through normal, throttled, dehydrated, quarantined, and recovery-observation states.

Authority classification:

- stateful efficiency governor
- sizing multiplier source
- quarantine authority for sleeve efficiency state
- not an execution engine
- not an order router
- not a broker gateway
- not a reconciliation authority

It does not submit, cancel, replace, sell, rebalance, or mutate broker state.

## Safety Scan

Static scan command:

`rg -n "POST|PATCH|DELETE|submit_order|cancel|replace|sell|rebalance|liquidate|api\\.alpaca\\.markets|paper-api\\.alpaca\\.markets|secret|key|token|password|credential" app/strategies/moving_floor.py app/risk/net_edge_governor.py app/risk/trade_efficiency_governor.py`

Result: no matches.

No live endpoint, paper endpoint, credential handling, direct broker REST, order submission, cancel/replace, sell, rebalance, liquidation, or secret material was found in the recovered assets.

## Validation

Compile proof:

`venv/Scripts/python.exe -m py_compile app/strategies/moving_floor.py app/risk/net_edge_governor.py app/risk/trade_efficiency_governor.py tests/test_seam7a_local_worktree_asset_recovery.py`

Result: passed.

Focused Seam 7A proof:

`venv/Scripts/python.exe -m pytest -q tests/test_seam7a_local_worktree_asset_recovery.py`

Result: 5 passed.

Related non-mutating regression:

`venv/Scripts/python.exe -m pytest -q tests/test_pre_trade_guardrail_constraints.py tests/test_intelligence_portfolio_state_truth_spine.py tests/test_upstream_dispatch_signal_submission.py`

Result: 46 passed.

## Focused Test Coverage

The Seam 7A test proves:

- MovingFloor initializes and ratchets a floor from deterministic market ticks.
- MovingFloor emits protective breach evidence only, without calling `OrderRouter` or `ExecutionEngine`.
- MovingFloor suppresses output when book integrity is untrustworthy.
- NetEdgeGovernor uses supplied economic truth to allow positive net edge and deny non-positive net edge.
- NetEdgeGovernor fails closed on stale economics, low confidence, and malformed empty gross-edge source.
- TradeEfficiencyGovernor transitions an inefficient sleeve to throttled, exposes sizing reduction, and can hard-quarantine without execution authority.

## Later Wiring Readiness

These assets are safe candidates for later runtime wiring if a later Board packet explicitly authorizes that wiring:

- MovingFloor can contribute protective strategy evidence through the existing decision/guardrail path. Protective sell/exit interpretation must validate existing exposure upstream and must not authorize short entry by itself.
- NetEdgeGovernor can contribute economic advisory/veto status if real fee, spread, slippage, burden, validity, and confidence inputs are supplied.
- TradeEfficiencyGovernor can contribute sleeve state and sizing multiplier if real trade-result telemetry is supplied.

Required later constraints:

- no fake PnL
- no fake slippage
- no fake net edge
- no fake profitability
- no direct broker REST
- no bypass of DecisionCompiler, ExecutionEngine, OrderRouter, BrokerGateway, PreTradeGuardrails, TruthKernel, or reconciliation
- broker truth remains canonical

## Blockers

No Seam 7A recovery blocker remains after validation.

Runtime wiring remains out of scope for Seam 7A and was not performed.
