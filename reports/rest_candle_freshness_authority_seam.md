# REST Candle Freshness Authority Seam

## Verdict

PASS for the scoped repair. No autonomous PAPER run was performed. No broker mutation path was exercised.

## Files Changed

- `app/models/market_data.py`
- `app/data/polling_client.py`
- `app/data/market_feeds.py`
- `app/main_loop.py`
- `main.py`
- `tests/test_feed_provider_router_failover.py`
- `tests/test_pre_trade_guardrail_constraints.py`
- `tests/test_runtime_dispatch_admission_telemetry.py`

## Causal Fix

The previous `DATA_BACKFILL_OBSERVE_ONLY` gate used `DataContinuityValidator.max_stale_age_ms=5000` to judge 1-minute REST candle buckets. That was the wrong authority for candle bucket freshness. The validator remains strict for packet/book health, while REST candles now use the selected provider's `candle_stale_seconds` policy.

## Runtime Classification

`PollingClient` now annotates REST candles with:

- `data_source_type`
- `provider_id`
- `latest_batch_candle`
- `candle_batch_received_ns`
- `candle_freshness_policy_ms`

`MainLoop` now allows executable candle dispatch only when:

- source is runtime provider data
- provider candle freshness policy is present
- candle is the latest candle in the REST batch
- candle age is within the provider candle freshness budget

Older REST batch candles remain observe-only with:

- `candle_freshness_reason_code=CANDLE_BATCH_BACKFILL_OBSERVE_ONLY`
- `data_health_reason_code=DATA_BACKFILL_OBSERVE_ONLY`

Stale latest candles remain observe-only with:

- `candle_freshness_reason_code=CANDLE_STALE`
- `data_health_reason_code=DATA_BACKFILL_OBSERVE_ONLY`

Missing policy and missing timestamps fail closed.

## Preserved Boundaries

- `DataContinuityValidator` 5-second packet health remains strict.
- Backfill/replay/synthetic candles cannot become executable.
- Broker, risk, sell, OrderRouter, BrokerGateway, and DecisionCompiler behavior were not changed.
- No thresholds were lowered to force trades.

## Tests Run

- `venv/Scripts/python.exe -m py_compile app/models/market_data.py app/data/polling_client.py app/data/market_feeds.py main.py app/main_loop.py app/brain/data_validator.py app/execution/engine.py`
- `cmd.exe /c "venv\\Scripts\\python.exe -m pytest tests\\test_runtime_dispatch_admission_telemetry.py tests\\test_pre_trade_guardrail_constraints.py tests\\test_feed_provider_router_failover.py tests\\test_lag_abort_infms_shadow_readiness.py -q"`

Result: 78 passed.

## Diff Check

- `git diff --check -- app/models/market_data.py app/data/polling_client.py app/data/market_feeds.py main.py app/main_loop.py tests/test_runtime_dispatch_admission_telemetry.py tests/test_pre_trade_guardrail_constraints.py tests/test_feed_provider_router_failover.py`

Result: clean, with only the existing Git line-ending warning for `app/models/market_data.py`.

## Next Smoke

A 300-second bounded PAPER smoke test is justified next. Expected proof:

- older REST batch candles log `CANDLE_BATCH_BACKFILL_OBSERVE_ONLY`
- latest Coinbase 1m candle within the 60-second provider policy can proceed past candle freshness
- `DataContinuityValidator` still blocks stale packet/book health at 5 seconds
- no broker mutation unless a candidate lawfully passes all existing downstream gates
