# Alpaca News World Awareness Provider Lane

Date: 2026-05-26

## Scope

This seam adds the first real World Awareness provider lane for Alpaca News as a read-only, config-gated advisory feed.

It does not change trading decisions, execution, OMS, broker safety, alpha thresholds, or DecisionFrame scoring.

## Safety Doctrine

- Alpaca News is advisory evidence only.
- Events cannot submit orders, cancel orders, liquidate, force trades, or activate live mode.
- Events cannot bypass MarketTruthSnapshot, NetEdge, pre-trade guardrails, risk governors, or broker boundary authority.
- Events default to `decisionframe_eligible=false`, `signal=NONE`, and `score_delta=0.0`.
- Stale, unverified, or conflicting events remain labeled and cannot become executable truth.
- Credentials are referenced by environment-variable names only. Secret values are never serialized.

## Provider Activation Model

`alpaca_news` remains disabled by default through `WorldAwarenessConfig`.

When explicitly enabled, the provider requires:

- `APCA_API_KEY_ID`
- `APCA_API_SECRET_KEY`

Missing credentials return `CREDENTIAL_MISSING`; disabled config returns `FEED_DISABLED`. Neither condition crashes the operator API.

The adapter supports a read-only Alpaca News HTTP client, but the operator API does not auto-poll it. Runtime polling requires an explicit future wiring decision or an injected polling service.

## Cache Model

The new in-memory `WorldAwarenessEventCache` stores normalized advisory events only.

It:

- dedupes by provider source id when available
- falls back to provider event id or stable payload-derived event id
- keeps a bounded latest-N cache
- tracks duplicate ignored count
- tracks provider runtime health snapshots
- remains replaceable by a later persistent event store

The cache does not poll providers by itself.

## Provider Health

Provider rows expose:

- provider id
- feed type
- enabled flag
- credential-present flag without secret values
- status
- last poll time
- latest event time
- event count
- stale count
- error count
- last error type
- duplicate ignored count
- advisory-only flag
- reason codes

Statuses include:

- `FEED_DISABLED`
- `CREDENTIAL_MISSING`
- `FEED_READY`
- `FEED_POLLING`
- `FEED_RATE_LIMITED`
- `FEED_UNAVAILABLE`
- `FEED_STALE`
- `FEED_ERROR`

## Operator API

The operator API exposes read-only summaries:

- `GET /operator/world-awareness`
- `GET /operator/world-awareness/providers`
- `GET /operator/world-awareness/events`

The endpoints return cached provider/event truth only. They do not call Alpaca, broker endpoints, trading engine endpoints, or run scripts.

## UI Behavior

The Operator Control Panel World Awareness screen now shows:

- provider health/status
- Alpaca News enabled/disabled/credential/rate-limit/error state
- latest advisory events
- symbols mapped from events
- event time and freshness
- stale/unverified badges
- advisory-only warning

The UI has no trade button, no live control, and no feed-to-trade path.

## Tests

Tests use fake Alpaca News clients only. They prove:

- disabled-by-default behavior
- missing credentials fail soft
- fake Alpaca News payload normalization
- event dedupe
- stale detection
- rate-limit/network error status mapping
- read-only operator API provider/event summaries
- no trade authority and no score impact
- no secrets in serialized output

## Limitations

- No live polling service is active by default.
- No API key is committed or required for tests.
- Operator API does not auto-fetch provider data.
- SEC/Finnhub/economic live polling remains outside this seam.
- Future persistent storage, scheduler, and hosted polling supervision are separate seams.

## Next Provider Lanes

Recommended next lanes:

1. Add an operator-controlled read-only polling service with scheduler/backoff and no trading authority.
2. Add SEC/Finnhub insider polling only after provider credentials/config are governed.
3. Add hosted/cloud world-awareness cache persistence.
4. Add advisory DecisionFrame display wiring without score impact.
