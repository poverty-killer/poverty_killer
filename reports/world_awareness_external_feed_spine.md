# World Awareness / External Intelligence Feed Spine

Date: 2026-05-26

## Doctrine

World Awareness is an advisory evidence system. It is not a trading engine, a market truth source, a broker authority, a risk override, or an execution path.

External feeds may inform operator visibility and future DecisionFrame evidence, but they cannot:

- submit orders
- cancel or liquidate
- bypass MarketTruthSnapshot
- bypass NetEdge
- bypass risk/pre-trade guardrails
- bypass broker boundary authority
- become canonical truth without a future approved governance seam

## Scout Findings

The repo already contained `app/world_awareness/` with:

- subordinate `WorldAwarenessEvent` models
- source catalog
- normalizer
- persistence/replay scaffolding
- scheduler
- non-live-attached starter adapters for SEC EDGAR, OpenInsider, Capitol Trades, Quiver, official releases, and official calendars
- tests proving non-authoritative behavior

This seam strengthens the existing package instead of creating a duplicate intelligence subsystem.

## Feed Categories

The normalized feed spine represents these lanes:

- `NEWS`
- `INSIDER_TRANSACTION`
- `SEC_FILING`
- `EARNINGS_EVENT`
- `MACRO_EVENT`
- `ECONOMIC_CALENDAR`
- `FED_EVENT`
- `CRYPTO_EVENT`
- `ONCHAIN_EVENT`
- `SOCIAL_SENTIMENT`
- `BROKER_NOTICE`
- `MARKET_STRUCTURE_EVENT`

## Provider Registry

Providers are disabled by default unless explicitly configured.

Initial lanes:

- `alpaca_news`: read-only advisory news lane, credentials required when enabled
- `sec_insider_filings`: read-only Form 3/4/5-style advisory lane, equities only
- `finnhub_insider`: disabled-by-default insider transaction lane, credential-gated
- `economic_calendar`: provider-TBD macro/calendar lane
- `crypto_onchain`: reserved future crypto/on-chain lane
- `social_sentiment`: reserved future social sentiment lane

Provider status values:

- `FEED_DISABLED`
- `CREDENTIAL_MISSING`
- `FEED_AVAILABLE`
- `FEED_RATE_LIMITED`
- `FEED_UNAVAILABLE`
- `FEED_STALE`

## Normalized Event Schema

The new `ExternalIntelligenceEvent` carries:

- event id
- provider
- feed type
- source url/id
- symbols
- asset class
- topic/title/summary
- event time
- received time
- freshness age
- stale flag
- confidence
- relevance
- sentiment
- severity
- direction hint
- verification status
- advisory-only flag
- DecisionFrame eligibility flag
- reason codes
- raw payload hash

Verification states:

- `CONFIRMED`
- `UNVERIFIED`
- `CONFLICTING`
- `STALE`

All events default to `advisory_only=true` and `decisionframe_eligible=false`.

## DecisionFrame Advisory Evidence

The event model can produce advisory evidence with:

- `module_name=WorldAwareness`
- `authority_class=ADVISORY`
- `signal=NONE`
- `score_delta=0.0`
- reason `ADVISORY_ONLY_NO_TRADE_AUTHORITY`

This seam does not change DecisionCompiler behavior and does not allow feed evidence to move score, trade, or block execution.

## UI / Operator Model

The operator API now exposes a safe read-only `/operator/world-awareness` summary.

The UI can show:

- provider name
- feed type
- enabled/disabled status
- credential-present status without secrets
- advisory-only warning
- event counts
- stale/high-relevance counts
- reason codes

No UI control can trade from World Awareness.

## Rate Limiting / Caching Strategy

This seam defines status/config boundaries only. Live polling remains disabled by default.

Future approved polling should use:

- provider-specific `min_poll_interval_seconds`
- bounded `max_items_per_fetch`
- timeout/backoff fields
- persistence under `state/world_awareness`
- raw payload hashes for dedupe/replay
- no secrets in logs

## Secrets / Config Strategy

Provider credentials are referenced by environment-variable names only. No key values are stored or printed.

Missing credentials produce `CREDENTIAL_MISSING`, not a crash.

## Activation Phases

1. Models, registry, disabled adapters, UI summary.
2. Read-only provider polling with fake-client tests.
3. Local cache/replay ingestion.
4. Advisory DecisionFrame contribution with zero score impact.
5. Separately governed score/weight usage only after replay validation.

## Safety Gates

- External feeds are advisory only.
- Stale events cannot be fresh truth.
- Unverified events remain unverified.
- Conflicting events fail closed.
- Insider events are equity advisory context and not crypto execution authority.
- Tests use fake payloads only.
- No broker mutation.
- No live/real-money path.

## Limitations

- No live feed polling is active.
- Alpaca News network fetch is not implemented.
- SEC/Finnhub/economic adapters are disabled-by-default stubs.
- No DecisionFrame runtime wiring is active beyond advisory contract shape.
- No sentiment/on-chain provider is live-attached.
