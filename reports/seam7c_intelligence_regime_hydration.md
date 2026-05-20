# Seam 7C Intelligence / Sentiment / Regime Hydration

## Scope

Current pre-closeout HEAD: `64c0c11`

Inspected files:

- `app/brain/sentiment_engine.py`
- `app/brain/sentiment_velocity.py`
- `app/brain/whale_zone_engine.py`
- `app/data/regime_detector.py`
- `app/data/feature_builder.py`
- `app/data/ghost_tick_detector.py`
- `app/data/validators.py`

Changed files:

- `tests/test_seam7c_intelligence_regime_hydration.py`
- `reports/seam7c_intelligence_regime_hydration.md`

No runtime wiring, broker integration, threshold relaxation, or shared attribution contract change was made in Seam 7C.

## Intent And Authority

### SentimentEngine

Intent: deterministic sentiment state aggregator. It consumes externally supplied sentiment source readings, normalizes/weights them, and emits `AggregateSentiment`.

Authority: intelligence/advisory signal producer. No execution, broker mutation, reservation, lifecycle, or reconciliation authority.

Hydration semantics:

- no source history or fewer than `min_sources`: `MISSING_FEED_TRUTH` / no effect
- fresh supplied source readings: `ACTIVE_NATIVE_SIGNAL` / `SENTIMENT_SIGNAL`
- stale source readings naturally fall out through freshness decay and can return no aggregate

### SentimentVelocityEngine

Intent: deterministic derivative engine for sentiment level, velocity, acceleration, impulse, divergence, reversion pressure, stability, and macro overlay.

Authority: advisory momentum/velocity producer. It can advise pause/kill semantics through `MacroSignal`, but it does not own execution or broker mutation.

Hydration semantics:

- missing or insufficient sentiment history: `NOT_READY_DATA_WARMUP`
- invalid timestamp/value: skipped and no vector emitted
- sufficient supplied sentiment history: `ACTIVE_NATIVE_SIGNAL` / `SENTIMENT_VELOCITY`

### WhaleZoneEngine

Intent: deterministic whale presence / accumulation structure / price-in-zone context from supplied candle volume, VWAP, and range evidence.

Authority: zone intelligence producer. It does not claim directional whale flow authority and does not submit orders.

Hydration semantics:

- insufficient zone evidence: no zone / `NO_EFFECT_WITH_REASON`
- supplied volume/VWAP/range evidence forming stable structure: `ACTIVE_NATIVE_SIGNAL` / `WHALE_ZONE`
- confidence decays if evidence stops refreshing

### RegimeDetector

Intent: deterministic market regime classifier from supplied feature vectors, including topological coherence, entropy, void depth, and momentum sign where available.

Authority: regime classifier only. No router, broker, reconciliation, or invariant authority.

Hydration semantics:

- fewer than `min_samples`: `NOT_READY_DATA_WARMUP`
- non-monotonic timestamp: fails closed with `RegimeDetectorError`
- sufficient deterministic feature truth: `ACTIVE_NATIVE_SIGNAL` / `REGIME_CLASSIFICATION`

### FeatureBuilder

Intent: point-in-time feature matrix builder from candles, optional order book data, depth history, spreads, and whale zone bounds.

Authority: feature producer. It does not fabricate missing source data and does not own market truth.

Hydration semantics:

- insufficient candle history: finite neutral warmup values
- supplied candle/depth/zone truth: `ACTIVE_FEATURES` / `FEATURE_MATRIX`
- missing optional inputs are represented by deterministic neutral defaults, not invented feeds

### GhostTickDetector

Intent: anomaly/ghost-tick validator using unified market specs, shared-memory correlation truth, and Mahalanobis-style cross-asset checks. `FastGhostTickDetector` provides a deterministic vectorized batch path.

Authority: anomaly validator. It flags or passes supplied ticks and records reasons; it does not delete source truth silently.

Hydration semantics:

- unknown symbol / no instrument truth: `MISSING_FEED_TRUTH`
- insufficient correlated assets or untrained covariance: explicit no-ghost result with reason
- trained cross-asset truth: `GHOST_TICK_FLAG`

### DataValidator

Intent: data validation layer for candles, order books, prices, quantities, OHLCV consistency, ordering, and staleness.

Authority: validation/fail-closed layer. It does not bypass TruthKernel or InvariantChecker.

Hydration semantics:

- valid supplied data: `ACTIVE_VALIDATION`
- stale, malformed, out-of-order, or impossible data: `INVALID_INPUT` / fail closed
- missing previous timestamp truth: stale status reports unknown as stale

## Safety Scan

Static scan:

`rg -n "submit_order|cancel_order|replace_order|rebalance|liquidate|BrokerGateway|OrderRouter|ExecutionEngine|paper-api\\.alpaca\\.markets|api\\.alpaca\\.markets|POST|PATCH|DELETE|secret|token|password|credential" app/brain/sentiment_engine.py app/brain/sentiment_velocity.py app/brain/whale_zone_engine.py app/data/regime_detector.py app/data/feature_builder.py app/data/ghost_tick_detector.py app/data/validators.py`

Result: no matches.

No broker mutation behavior, live endpoint, paper endpoint, direct broker REST, credential printing/copying, or execution authority was found in the Seam 7C target files.

## Validation

Compile:

`venv/Scripts/python.exe -m py_compile app/brain/sentiment_engine.py app/brain/sentiment_velocity.py app/brain/whale_zone_engine.py app/data/regime_detector.py app/data/feature_builder.py app/data/ghost_tick_detector.py app/data/validators.py`

Result: passed.

Focused Seam 7C:

`venv/Scripts/python.exe -m pytest -q tests/test_seam7c_intelligence_regime_hydration.py`

Result: 8 passed.

Scoped regression:

`venv/Scripts/python.exe -m pytest -q tests/test_seam7b_brain_math_runtime_stability.py tests/test_intelligence_portfolio_state_truth_spine.py tests/test_upstream_dispatch_signal_submission.py`

Result: 45 passed.

## Focused Test Evidence

The Seam 7C test proves:

- SentimentEngine returns missing-truth when no source sentiment exists and active native output from supplied source sentiment.
- SentimentVelocityEngine returns warmup/missing history truth before producing finite derivative vectors.
- WhaleZoneEngine detects a zone only from deterministic candle volume/VWAP/range evidence.
- RegimeDetector returns warmup until enough feature samples exist and then classifies from supplied feature truth.
- FeatureBuilder produces finite point-in-time features and warmup-neutral values for insufficient history.
- GhostTickDetector reports missing instrument truth without deleting or mutating tick truth.
- DataValidator passes valid data and fails stale/invalid data explicitly.
- Target modules can be adapted into `module_name/status/input_truth/output_summary/effect/reason`.
- Target modules do not expose broker mutation authority attributes.

## Confirmations

- No broker/network mutation was performed.
- No live endpoint or live mode was used.
- No Alpaca PAPER order submission was performed.
- No mutation approval flags were set.
- No fake sentiment, whale flow, regime, market, broker, fill, PnL, slippage, net edge, or profitability facts were invented.
- No duplicate execution, order router, broker gateway, reconciliation, reservation, or lifecycle authority was created.

## Readiness

Seam 7C target modules are ready for later Seam 7D/7E/7G runtime attribution as advisory intelligence/data contributors:

- sentiment modules can sign native, warmup, or missing-truth states
- whale zone can sign zone evidence or no-effect state
- regime detector can sign warmup, fail-closed, or classification state
- feature builder can sign feature matrix or warmup-neutral state
- ghost tick detector can sign anomaly/missing-truth status
- validators can sign validation pass/fail state

Later runtime wiring remains out of scope for Seam 7C.

## Blockers

No Seam 7C blocker remains.
