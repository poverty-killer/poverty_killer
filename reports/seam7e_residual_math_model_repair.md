# Seam 7E Residual Math/Model Repair

Current HEAD before repair commit: `59077e9`

## Files Inspected

- `app/data/feature_builder.py`
- `app/data/ghost_tick_detector.py`
- `app/models/market_data.py`
- `app/data/depth_book.py`
- Seam 7B/7C/7E focused tests and reports for prior blocker context

## FeatureBuilder Contract Finding

`FeatureBuilder.calculate_depth_contraction(...)` expected `order_book.market_depth`, but canonical `OrderBookSnapshot` exposes:

- `bids`
- `asks`
- `depth_at_levels(levels)`
- `imbalance`
- `spread_bps`

`DepthBook.market_depth` already defines depth as bid depth plus ask depth across the top levels. The repair therefore does not add a fake `market_depth` field to `OrderBookSnapshot`. `FeatureBuilder` now derives current depth from canonical bid/ask levels through `depth_at_levels(10)` when available, or by summing bid/ask sizes directly.

Missing depth truth is explicit:

- `MISSING_DEPTH_TRUTH`: absent bid/ask depth, non-finite history, or non-positive baseline.
- `NOT_READY_DATA_WARMUP`: insufficient historical depth samples.
- `ACTIVE_DEPTH_TRUTH`: finite two-sided current depth and finite positive historical baseline.

The feature dictionary remains numeric for existing consumers. The explicit status is exposed through `last_depth_contraction_status` and `last_depth_contraction_reason`.

## Ghost Tick Covariance Finding

`FastGhostTickDetector.detect_vector(...)` previously built a multi-instrument covariance matrix, then computed a one-dimensional Mahalanobis expression and attempted `np.sum(..., axis=1)`, producing an axis error for 2+ instruments.

The repair treats the current prices as a basket vector:

```text
diff = current_prices - historical_mean
distance = sqrt(diff.T @ inv_cov @ diff)
```

The output remains a boolean array matching `len(instrument_ids)`. The detector returns a shared basket anomaly verdict with `np.full(...)`, preserving the simple vector contract without inventing per-instrument contribution attribution.

Fail-closed statuses are explicit:

- `NOT_READY_DATA_WARMUP`: single-instrument vector, missing buffer, or insufficient sample history.
- `FAILED_CLOSED`: bad vector shape, non-finite prices/history, invalid covariance, non-finite distance, or unrecoverable covariance error.
- `ACTIVE_COVARIANCE_TRUTH`: regularized covariance inversion succeeded.
- `ACTIVE_COVARIANCE_TRUTH_PINV`: pseudo-inverse fallback used if regularized inverse fails.

The detector now tracks per-instrument sample counts so zero-filled buffers are not treated as real covariance history.

## Test Results

Compile:

```text
venv/Scripts/python.exe -m py_compile app/data/feature_builder.py app/data/ghost_tick_detector.py tests/test_seam7e_residual_math_model_repair.py
```

Result: passed.

Focused repair:

```text
venv/Scripts/python.exe -m pytest -q tests/test_seam7e_residual_math_model_repair.py
```

Result: `10 passed`.

Scoped regression:

```text
venv/Scripts/python.exe -m pytest -q tests/test_seam7e_strategy_fusion_runtime_wiring.py tests/test_seam7c_intelligence_regime_hydration.py tests/test_seam7b_brain_math_runtime_stability.py
```

Result: `28 passed`.

## Confirmations

- No broker mutation was added or executed.
- No live endpoint or live mode was used.
- No fake depth was invented; depth is derived only from canonical bid/ask sizes.
- No fake covariance was invented; covariance uses tracked price history and fails closed on missing or invalid truth.
- No fake broker facts, fills, PnL, slippage, net edge, or profitability were created.
- No duplicate execution, broker, gateway, router, reconciliation, or allocation authority was created.

## Remaining Blockers

None for the two recorded Seam 7E residual blockers.
