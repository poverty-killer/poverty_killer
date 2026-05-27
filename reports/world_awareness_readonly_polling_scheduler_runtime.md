# World Awareness Read-only Polling Scheduler / Provider Runtime

Date: 2026-05-26

## Scope

This seam adds a provider-agnostic World Awareness runtime for manual read-only polling, due calculation, retry/backoff, provider health, and operator UI visibility.

It builds on the already-pushed Alpaca News provider lane. It does not redo the provider lane and does not add trading authority.

## Safety Doctrine

- No provider auto-starts on import.
- Polling is manual intent only.
- Polling is read-only external-feed access.
- No broker endpoint is called.
- No order, cancel, liquidation, live-mode, or real-money path is added.
- Feed events remain `advisory_only=true`, `decisionframe_eligible=false`, `signal=NONE`, and `score_delta=0.0`.
- Provider data cannot bypass MarketTruthSnapshot, NetEdge, guardrails, or broker boundary authority.
- Tests use fake clients only and perform no network calls.

## Runtime Model

`WorldAwarenessProviderRuntime` tracks provider state in memory:

- enabled/disabled state
- current provider status
- next poll time
- due/not-due decision
- minimum poll interval
- backoff seconds
- last poll time
- last success time
- latest event time
- poll count
- error count
- consecutive error count
- last error type
- latest added/duplicate counts
- stale event count

The runtime owns no background thread and no scheduler loop. It only runs when a caller invokes `poll_provider`.

## Manual Poll Intent

The operator API exposes:

- `GET /operator/world-awareness/runtime`
- `POST /operator/intent/world-awareness/poll`

The POST endpoint is an audited-style operator intent. It returns allow/refuse, reason code, provider status, cache effects, next poll time, and explicit safety flags:

- `broker_call_occurred=false`
- `trade_authority=false`
- `decisionframe_score_impact=0.0`
- `live_endpoint_touched=false`
- `real_money_touched=false`

Disabled providers, missing credentials, unknown providers, missing adapters, and not-due providers are refused safely.

## Backoff / Rate Limit Behavior

Successful polls schedule the next poll using `min_poll_interval_seconds`.

Soft failures such as rate limits or provider unavailability schedule the next poll using `backoff_seconds`, increment error counters, and preserve advisory-only status.

No failure grants execution authority or changes trading decisions.

## Cache / Health

The existing in-memory `WorldAwarenessEventCache` remains the event store for this seam. The runtime updates it only after an allowed manual provider poll.

Cache summary exposes:

- event count
- duplicate ignored count
- provider runtime snapshots
- stale counts
- latest event time

## UI

The Operator Control Panel World Awareness screen now shows:

- next poll time
- due status
- backoff seconds
- error counts
- manual read-only Alpaca News poll button
- explicit advisory-only warning

The UI intent calls only `/operator/intent/world-awareness/poll`. It does not call broker/execution endpoints and cannot trade.

## Tests

Focused tests cover:

- no auto-start/no poll on runtime construction
- disabled provider refusal
- due calculation
- manual poll cache update
- duplicate event suppression
- rate-limit backoff
- operator API runtime endpoint
- operator manual poll endpoint
- no secrets in output
- no trade authority or DecisionFrame score impact

## Limitations

- Runtime state is in-memory only.
- No background polling loop is active.
- Only Alpaca News has a concrete adapter lane in this pass.
- Real credential-enabled provider polling requires explicit local/operator configuration and should be validated separately.

## Next Phase

Recommended next phases:

1. Add hosted/cloud-safe persistent World Awareness cache.
2. Add governed scheduler loop with explicit start/stop controls, still no trading authority.
3. Add SEC/Finnhub/economic provider runtime lanes after credential/config governance.
4. Add DecisionFrame display-only advisory event linkage with zero score impact.
