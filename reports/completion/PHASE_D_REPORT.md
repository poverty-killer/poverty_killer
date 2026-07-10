# Phase D Paper Readiness Truth Report

Date: 2026-07-10
Branch: master
Latest commit at original Phase D open: `eff471d phase C authority graph`
Latest commit before D4 armed addendum: `0ad558b complete phase D paper readiness truth`
Active packet: Phase D convergence + D1-FIX Board packet + D4 armed read-only broker inspection packet.

## Gate Verdict

| Gate | Status | Proof rung | Evidence |
| --- | --- | --- | --- |
| D0 - Single active broker path | PASS | focused tests prove topology | `tests/test_phase_d_paper_readiness_truth.py` proves active runtime broker submit remains `ExecutionEngine -> OrderRouter -> broker_gateway/adapter`; rejected orchestrator is not imported by active runtime. |
| D1 - Safety guard liveness | PASS | focused tests prove behavior | `StaleDataGuard` is now a blocking contributor under `evaluate_pre_trade_guardrails`; stale market data is rejected. `SovereignExecutionGuard` is mutation-capable and remains `DORMANT_BY_POLICY_PENDING_PHASE_HI_ARM`, represented as such. |
| D2 - Single Alpaca PAPER credential source | PASS | focused tests prove resolver behavior | Alpaca PAPER execution credentials resolve only from `~/.poverty_killer_alpaca_paper_env` or `POVERTY_KILLER_ALPACA_PAPER_ENV_PATH`; `.operator_secrets` and process APCA vars are demoted for PAPER execution truth. |
| D3 - Paper endpoint proven / live and real money blocked | PASS | focused tests prove failure modes | Canonical live endpoint fails closed with `LIVE_ENDPOINT_BLOCKED`; PAPER endpoint normalizes to `https://paper-api.alpaca.markets`; real money remains blocked. |
| D4 - Account / open-orders / positions baseline known | PASS | broker-read-only runtime proof | Board-authorized read-only Alpaca PAPER inspection made exactly `GET /v2/account`, `GET /v2/positions`, and `GET /v2/orders?status=open&limit=100&nested=false`; account/open-orders/positions baseline retrieved. |
| D5 - Portfolio truth broker-confirmed or exact failure | PASS | broker-read-only runtime proof + focused API test | Authorized `/operator/portfolio` path returned `BROKER_CONFIRMED` data with no fabricated values; unarmed path remains exact `BROKER_READ_NOT_AUTHORIZED` failure. |
| D6 - Run-PAPER button/backend truth | PASS | focused tests + JS syntax check | Backend and UI gate on exactly `READY_FOR_BOUNDED_PAPER`; `DEGRADED_BUT_RUNNABLE` and `READY_FOR_GOVERNED_PAPER` are removed from runtime/UI contracts. |
| D7 - Final reconciliation explicit | PASS | focused API test proves contract | Launch readiness exposes `final_reconciliation_required` and owner `OrderRouter.finalize_oms_shutdown_reconciliation`. |

## 1. Verdict

Phase D is fully closed for D0-D7. PAPER was not run. The D4 read-only broker inspection was Board-armed and completed against Alpaca PAPER only.

D1 was resolved without creating new authority: `StaleDataGuard` contributes a veto under the existing pre-trade guardrail owner, while `SovereignExecutionGuard` is classified as mutation-capable and kept dormant by policy until a future live-arming phase.

## 2. Files Changed

Runtime/backend:

- `app/risk/pre_trade_guardrails.py`
- `app/main_loop.py`
- `app/core/authority_graph.py`
- `app/operator_credentials/store.py`
- `app/execution/alpaca_paper_adapter.py`
- `app/operator_activation/launch_readiness.py`
- `app/operator_activation/paper_baseline.py`
- `app/operator_portfolio/snapshot.py`
- `app/operator_providers/readiness.py`
- `app/api/operator_readonly_api.py`
- `app/api/operator_paper_supervisor.py`

UI/contracts:

- `ui/operator-control-panel/app.js`
- `ui/operator-control-panel/contracts.json`

Tests:

- `tests/test_phase_d_paper_readiness_truth.py`
- `tests/test_pre_trade_guardrail_constraints.py`
- `tests/test_alpaca_paper_credential_authority_guard.py`
- `tests/test_operator_launch_readiness.py`
- `tests/test_operator_credentials.py`
- `tests/test_operator_portfolio.py`
- `tests/test_operator_readonly_api.py`
- `tests/test_operator_ai_ask.py`
- `tests/test_operator_ui_wiring.py`

Reports/tracker:

- `reports/completion/PHASE_D_REPORT.md`
- `CHECKPOINT_TRACKER.md`
- `reports/codex_handoff_latest.md`

D4 armed addendum changed only the report/tracker/handoff files above. No source code, tests, state, logs, runtime DB, or secret files were edited for the D4 broker-read proof.

## 3. Root Cause

D1 root cause: `StaleDataGuard` existed as a module but was not consumed by the live pre-trade guardrail evidence path. Static Phase C classification was correct enough to flag the gap.

D2 root cause: Alpaca PAPER credentials had multiple effective readers: process env, `.operator_secrets/provider_credentials.json`, and the paper env file. That could make the operator UI appear configured while execution used a different source.

D6 root cause: readiness had multiple green-ish states and OR logic across supervisor/runtime/launch signals. That could produce fake green when one layer was ready and another was blocked.

## 4. Fixes Implemented

`StaleDataGuard` now runs inside `evaluate_pre_trade_guardrails` as a labeled evidence contributor. It can block a trade but cannot size, route, submit, or mutate broker state.

`main_loop` now passes market truth timing into pre-trade guardrails. If the live dispatch path cannot provide stale-data observation, it fails closed with `STALE_DATA_GUARD_OBSERVATION_MISSING`.

`SovereignExecutionGuard` remains dormant as `DORMANT_BY_POLICY_PENDING_PHASE_HI_ARM` because live-repo evidence shows it can issue execution/capital authorization receipts. It was not activated.

Alpaca PAPER execution credentials now resolve from the canonical paper env file only. Local vault values remain redacted/local provider data but no longer satisfy PAPER execution readiness.

Launch readiness and UI control state now use exactly one green-light: `READY_FOR_BOUNDED_PAPER`.

Portfolio endpoint now returns exact `BROKER_READ_NOT_AUTHORIZED` failure when D4 broker read has not been armed.

Final reconciliation is explicit in the launch-readiness contract.

## 5. 360 Adjacent Improvements

Clean accepted PAPER baselines now load as valid runtime baseline context when there are no positions. Protected-position baselines still require protected symbols and remain warning-blocked until the Board authorizes the position-aware PAPER path.

Provider readiness no longer falls back from an empty canonical Alpaca PAPER result to process/local secrets. That was a real D2 leak and is now closed.

AI readiness answers now derive from the single readiness state and no longer treat deprecated degraded/governed aliases as runnable.

Tests now isolate `POVERTY_KILLER_ALPACA_PAPER_ENV_PATH` so they cannot pass accidentally because Shan's real machine has a canonical env file.

## 6. Tests / Checks

Passed:

```powershell
node --check ui/operator-control-panel/app.js
```

Passed:

```powershell
python -m py_compile app\risk\pre_trade_guardrails.py app\main_loop.py app\core\authority_graph.py app\operator_credentials\store.py app\execution\alpaca_paper_adapter.py app\operator_activation\launch_readiness.py app\operator_activation\paper_baseline.py app\operator_portfolio\snapshot.py app\operator_providers\readiness.py app\api\operator_readonly_api.py app\api\operator_paper_supervisor.py
```

Passed:

```powershell
rg -n "DEGRADED_BUT_RUNNABLE|READY_FOR_GOVERNED_PAPER" app ui tests -S
```

Only the negative assertions in `tests/test_phase_d_paper_readiness_truth.py` remain.

Passed:

```powershell
python -m pytest tests/test_phase_d_paper_readiness_truth.py tests/test_pre_trade_guardrail_constraints.py tests/test_alpaca_paper_credential_authority_guard.py tests/test_operator_launch_readiness.py tests/test_operator_credentials.py tests/test_operator_portfolio.py tests/test_operator_readonly_api.py tests/test_operator_ai_ask.py tests/test_operator_ui_wiring.py tests/test_operator_paper_supervisor.py -q --basetemp .pytest_tmp\phase_d_focused_all
```

Result: 206 passed, 72 existing warnings.

## 7. Runtime / Browser / Broker Proof

Runtime server proof: not run; the build phase used focused in-process API/unit proof.

Browser proof: not run; UI change was contract/JS logic and `node --check` only.

Broker read proof: completed under the D4 armed packet using the same operator backend provider boundary:

```text
Credential source: CANONICAL_PAPER_ENV_FILE for required Alpaca PAPER fields
Endpoint: https://paper-api.alpaca.markets
Calls: GET /v2/account; GET /v2/positions; GET /v2/orders?status=open&limit=100&nested=false
Portfolio status: BROKER_CONFIRMED
Account status: ACTIVE
Account id: redacted_suffix:045ded
Currency: USD
Trading blocked: false
Account blocked: false
Transfers blocked: false
Pattern day trader: false
Open orders: 0
Positions: 4
Total equity: 1000327.32
Cash: 990112.68
Buying power: 3960450.72
Total market value: 10214.638362
Total unrealized P&L: 10214.638362
Broker read profile: PAPER_SMOKE_STRICT_READS
Account activities: SKIPPED_NOT_AUTHORIZED
Freshness: 2026-07-10T17:01:18.931176+00:00
```

Broker-confirmed positions:

| Symbol | Asset class | Quantity | Side | Market value | Unrealized P&L | Source |
| --- | --- | ---: | --- | ---: | ---: | --- |
| AVAXUSD | crypto | 475.373488709 | long | 3187.902153 | 3187.902153 | BROKER_CONFIRMED |
| ETHUSD | crypto | 2.233125238 | long | 4010.514277 | 4010.514277 | BROKER_CONFIRMED |
| LINKUSD | crypto | 374.74289054 | long | 2977.392224 | 2977.392224 | BROKER_CONFIRMED |
| SOLUSD | crypto | 0.498972077 | long | 38.829708 | 38.829708 | BROKER_CONFIRMED |

Open orders: none.

Broker mutation/PAPER run: not run.

## 8. Self-Red-Team

Fake readiness vector: a test could pass while production still reads `.operator_secrets`. Closed by changing `LocalCredentialStore.resolve_provider_field`, `effective_env`, `alpaca_paper_adapter`, and provider readiness, then testing stale local/process values against a canonical file.

Hidden broker path vector: public adapter methods could be mistaken for active bypasses. D0 tests distinguish preserved lower-layer APIs from active runtime dispatch.

Guard weakening vector: wiring stale guard could alter thresholds. No stale threshold was changed; guard result is consumed as evidence/veto only.

UI fake-green vector: UI could OR supervisor/runtime/launch truth. UI and backend now require exact `READY_FOR_BOUNDED_PAPER`.

Portfolio fake truth vector: cached/fake portfolio could appear broker-confirmed without D4. `/operator/portfolio` now returns exact no-read authorization failure.

## 9. Governance / Safety Confirmation

No Sacred Safety Law was weakened.

No risk, stale/TTL, economic, sizing, masking, strategy, NetEdge, OMS, broker, or threshold value was weakened.

Broker read-only inspection was performed only after explicit D4 Board arming.

The read-only proof recorded these mutation and safety flags as false: `broker_mutation_occurred`, `order_submission_occurred`, `cancel_occurred`, `liquidation_occurred`, `live_enabled`, `real_money_enabled`.

No broker mutation occurred.

No PAPER run occurred.

No live endpoint was enabled or touched.

No real-money path was enabled or touched.

No raw secrets were read, printed, written, or staged.

No state, log, runtime DB, `.operator_secrets`, credential file, or screenshot is recommended for staging.

## 10. Module Status

| Module | Status | Role / reason |
| --- | --- | --- |
| `app.execution.order_router.OrderRouter` | WIRED | Sole active broker/order lifecycle owner. |
| `app.execution.orchestrator` | REJECTED-PRESERVED | Reference-only rejected orchestrator, not active runtime. |
| `app.risk.pre_trade_guardrails` | WIRED | Risk-gate owner; consumes stale guard evidence. |
| `app.risk.stale_data_guard.StaleDataGuard` | WIRED | Blocking stale-data evidence contributor; no broker mutation/sizing authority. |
| `app.risk.sovereign_execution_guard.SovereignExecutionGuard` | BLOCKED/DORMANT_BY_POLICY | Mutation-capable capital/execution authorization guard; intentionally dormant until Phase H/I arming. |
| `app.operator_credentials.store` | WIRED | Canonical Alpaca PAPER credential source enforcement. |
| `app.execution.alpaca_paper_adapter` | WIRED | Uses canonical paper env file; live endpoint blocked. |
| `app.operator_activation.launch_readiness` | WIRED | Single readiness green-light and final reconciliation contract. |
| `app.operator_portfolio.snapshot` | WIRED | Exact broker-read-not-authorized failure when D4 is not armed. |
| `ui/operator-control-panel/app.js` | WIRED | Run-PAPER UI derives enabled state from exact backend readiness truth. |

## 11. D0 Details

D0 active broker-path proof remains: active broker submit goes through `OrderRouter`. Preserved lower-layer public methods on paper broker/adapters are not violations by themselves.

## 12. D1 Details

Challenge result:

- `StaleDataGuard` is block-only for this seam: it returns risk actions and evidence, no broker/order calls.
- `SovereignExecutionGuard` is mutation-capable by design because it produces authorization receipts and capital/execution allowance fields. It remains dormant by policy.

Proof:

- Stale market data in the live pre-trade guardrail path is rejected.
- Sovereign guard evidence appears as dormant, not silently live and not hidden.

## 13. D2 Details

Canonical source: `~/.poverty_killer_alpaca_paper_env`, overrideable in tests/operator process by `POVERTY_KILLER_ALPACA_PAPER_ENV_PATH`.

Demoted source: `.operator_secrets/provider_credentials.json` is not PAPER execution truth.

Process APCA variables are not allowed to override the canonical paper file for PAPER execution readiness.

## 14. D3 Details

The allowed endpoint is `https://paper-api.alpaca.markets`.

`https://api.alpaca.markets` fails closed as `LIVE_ENDPOINT_BLOCKED`.

Real-money remains blocked; no code enables it.

## 15. D4 Details

D4 is PASS.

The authorized read path was challenged before use:

- `AlpacaPaperReadOnlyClient.get_json` constructs `urllib.request.Request(..., method="GET")` only.
- `build_portfolio_snapshot` calls only `/v2/account`, `/v2/positions`, and `/v2/orders?status=open&limit=100&nested=false` under the strict D4 profile.
- Account activities stayed skipped because the strict read profile does not authorize them.
- `app.execution.alpaca_paper_adapter` still contains governed POST/DELETE methods for execution, but that adapter is not the D4 operator portfolio read path.

Retrieved broker-confirmed baseline:

- account status: `ACTIVE`
- account id: `redacted_suffix:045ded`
- currency: `USD`
- trading/account/transfers blocked: `false` / `false` / `false`
- pattern day trader: `false`
- open orders: `0`
- positions: `4`
- symbols: `AVAXUSD`, `ETHUSD`, `LINKUSD`, `SOLUSD`
- total equity: `1000327.32`
- cash: `990112.68`
- buying power: `3960450.72`
- total market value: `10214.638362`
- total unrealized P&L: `10214.638362`
- credential source: required Alpaca PAPER fields resolved from `CANONICAL_PAPER_ENV_FILE`
- endpoint status: `PAPER_ENDPOINT_CONFIRMED`
- mutation/live/real-money flags: all false

## 16. D5 Details

D5 is PASS at broker-read-only proof rung.

When D4 broker read is armed, portfolio truth renders broker-confirmed values from the read-only Alpaca PAPER response:

- `status`: `BROKER_CONFIRMED`
- `data_source`: `BROKER_CONFIRMED`
- positions and open orders are broker-confirmed only; no fabricated fallback rows are promoted.
- read-only order rows cannot cancel, replace, or liquidate.

When broker read is not armed, the unarmed path still shows exact failure:

- `status`: `BACKEND_DEGRADED`
- `unavailable_reason`: `BROKER_READ_NOT_AUTHORIZED`
- `broker_read_attempted`: `False`
- no fake account, positions, orders, P&L, fees, TCA, or broker-confirmed values.

## 17. D6 Details

The only runnable state is `READY_FOR_BOUNDED_PAPER`.

Removed runnable aliases:

- `DEGRADED_BUT_RUNNABLE`
- `READY_FOR_GOVERNED_PAPER`

No OR-logic remains for UI button enablement across runtime/supervisor/launch truth.

## 18. D7 Details

Launch readiness exposes final reconciliation as required:

- `final_reconciliation_required`: `True`
- owner: `OrderRouter.finalize_oms_shutdown_reconciliation`
- failure policy: a future authorized run cannot be marked complete without final broker reconciliation evidence or exact failure reason.

## 19. Limitations / Unknowns

No browser screenshot proof was captured for the UI button.

No end-to-end dev server proof was run.

No PAPER run was executed.

Existing unrelated dirty/untracked files remain preserved.

## 20. Exact Staging Recommendation

Stage exactly:

```powershell
git add -- reports/completion/PHASE_D_REPORT.md
git add -- CHECKPOINT_TRACKER.md
git add -- reports/codex_handoff_latest.md
```

Do not stage:

- `state/*`
- `.pytest_tmp/`
- `AGENTS.prev.md`
- `POVERTY_KILLER_AUDIT_REPORT.txt`
- untracked old handoff reports
- `reports/operator_perf/`
- untracked audit scripts
- secrets, logs, DB/runtime files, screenshots, or quarantine.
