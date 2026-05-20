# Seam 7B Brain Math Runtime Stability

## Scope

Current pre-closeout HEAD: `b5e5de2`

Inspected files:

- `app/brain/shans_curve.py`
- `app/brain/topological_engine.py`
- `app/brain/convexity_switch.py`
- `app/brain/shadow_front_state.py`
- `app/brain/ring_buffer.py`
- `app/brain/rolling_stats.py`
- `app/brain/data_validator.py`
- `app/brain/recalibrator.py`

Changed files:

- `app/brain/shans_curve.py`
- `tests/test_seam7b_brain_math_runtime_stability.py`
- `reports/seam7b_brain_math_runtime_stability.md`

## Shans Curve Intent

`ShansCurve` is a proprietary alpha/math signal engine for asymptotic liquidity exhaustion. It consumes order-book-derived price, order-flow imbalance, and volume trajectories, then emits:

- `shans_superfluid_score`
- `shans_bias`
- `shans_confidence`
- fit/inflection observability

It is not an execution engine, order router, broker gateway, broker mutation authority, reservation authority, lifecycle authority, or reconciliation authority. Risk/safety gating remains delegated to callers.

Warmup behavior is intentional. `update_order_book()` returns `None` until the internal ring buffers reach `curvature_window`; `is_ready()` mirrors that gate. Seam 7B preserved this behavior.

## Runtime Blocker

Deterministic local reproduction:

`_savitzky_golay(np.linspace(1.0, 2.0, 9, dtype=np.float64), 7, 2)`

Original failure:

Numba nopython rejected `_savitzky_golay` at `except np.linalg.LinAlgError` with:

`Exception matching is limited to <class 'Exception'>`

The blocker was not the Shans Curve doctrine, order-book warmup, or readiness logic. It was an unsupported typed exception match inside a `@numba.njit` function.

## Repair

`_savitzky_golay` now preserves the Savitzky-Golay least-squares smoothing intent while using nopython-compatible operations:

- keeps the Vandermonde design matrix
- computes the normal equations
- solves for the smoothing rows with `np.linalg.solve`
- applies the center-row smoothing weights through scalar loops
- preserves edge handling
- preserves insufficient-data copy behavior
- preserves Numba JIT/nopython execution

Shans Curve was not flattened into SMA/EMA/textbook fallback behavior. No thresholds were lowered.

## Support Module Intent

- `topological_engine.py`: order-book topology/shape evidence producer using point clouds, persistence proxies, coherence, super-void, and structural-collapse evidence. No execution authority.
- `convexity_switch.py`: advisory regime/posture switch from asset and benchmark return correlation. No execution authority.
- `shadow_front_state.py`: deterministic shadow-front strategy state convergence layer. Analytical state only; not broker truth or reconciliation.
- `ring_buffer.py`: analytical fixed-size NumPy buffer utility. No market truth invention.
- `rolling_stats.py`: analytical rolling statistics utility. No monetary truth authority.
- `data_validator.py`: continuity and numeric validation helper. Invalid data fails closed with explicit reason.
- `recalibrator.py`: topological regime/recalibration advisory state. It emits regime labels, not broker mutation.

## Safety Scan

Static scan:

`rg -n "submit_order|cancel_order|replace_order|rebalance|liquidate|BrokerGateway|OrderRouter|ExecutionEngine|paper-api\\.alpaca\\.markets|api\\.alpaca\\.markets|POST|PATCH|DELETE|secret|token|password|credential" app/brain/shans_curve.py app/brain/topological_engine.py app/brain/convexity_switch.py app/brain/shadow_front_state.py app/brain/ring_buffer.py app/brain/rolling_stats.py app/brain/data_validator.py app/brain/recalibrator.py`

Result: no matches.

No broker mutation, direct broker REST, live endpoint, paper endpoint, order submission, cancel/replace, rebalance, credential handling, or secret material was found in the target brain/math files.

## Validation

Compile:

`venv/Scripts/python.exe -m py_compile app/brain/shans_curve.py app/brain/topological_engine.py app/brain/convexity_switch.py app/brain/shadow_front_state.py app/brain/ring_buffer.py app/brain/rolling_stats.py app/brain/data_validator.py app/brain/recalibrator.py`

Result: passed.

Focused Seam 7B:

`venv/Scripts/python.exe -m pytest -q tests/test_seam7b_brain_math_runtime_stability.py`

Result: 9 passed.

Scoped regression:

`tests/test_shadow_read_only_runtime_gate.py` was not present in the repo, so it was omitted as allowed by the packet.

`venv/Scripts/python.exe -m pytest -q tests/test_upstream_dispatch_signal_submission.py tests/test_intelligence_portfolio_state_truth_spine.py`

Result: 36 passed.

## Focused Test Coverage

The Seam 7B test proves:

- Shans Curve Savitzky-Golay native smoothing compiles and runs through Numba on deterministic numeric arrays.
- Shans Curve preserves not-ready warmup and does not emit fake signals before `curvature_window`.
- Shans Curve produces finite numeric output after sufficient deterministic order-book-like samples.
- Shans Curve output does not include fake broker/economic facts.
- TopologicalEngine emits explicit insufficient-points evidence and finite native topology evidence when sufficient points exist.
- ConvexitySwitch emits advisory posture and has no execution authority.
- ShadowFrontStateMachine handles deterministic context updates without broker truth claims.
- RingBuffer and RollingStats handle insufficient data and finite rolling calculations.
- DataContinuityValidator fails invalid data closed; Recalibrator degrades missing topology into explicit regime output.
- Target modules do not expose broker mutation authority attributes.

## Confirmations

- No broker/network mutation was performed.
- No live endpoint or live mode was used.
- No Alpaca PAPER order submission was performed.
- No mutation approval flags were set.
- No fake broker facts, fills, quotes, PnL, slippage, net edge, or profitability were invented.
- No duplicate execution, broker gateway, order router, reconciliation, reservation, or lifecycle authority was created.

## Readiness

Seam 7B modules are ready for later Seam 7C/7D/7E runtime attribution work as brain/math contributors, with these boundaries:

- Shans Curve can sign native alpha/math signal or not-ready warmup status.
- TopologicalEngine can sign topology/shape evidence or insufficient-points status.
- ConvexitySwitch can sign advisory convexity/regime posture.
- ShadowFrontStateMachine can sign analytical strategy-state status.
- RingBuffer/RollingStats can support rolling analytical feature state.
- DataValidator/Recalibrator can sign validation/recalibration status.

Later runtime wiring remains out of scope for Seam 7B.

## Blockers

No Seam 7B blocker remains.
