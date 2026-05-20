# Seam 7D World Awareness Specialized Portals Compliance Filters

## Scope

Current HEAD at implementation time: `30bdb85`

Seam 7D validated the world-awareness portal layer as a lawful advisory source layer. It does not wire these portals into SignalFusion or execution; runtime routing is reserved for Seam 7E.

Changed files:

- `app/world_awareness/source_catalog.py`
- `tests/test_seam7d_world_awareness_compliance_filters.py`
- `reports/seam7d_world_awareness_compliance_filters.md`

Inspected world-awareness files:

- `app/world_awareness/config.py`
- `app/world_awareness/decay.py`
- `app/world_awareness/dedupe.py`
- `app/world_awareness/events.py`
- `app/world_awareness/models.py`
- `app/world_awareness/normalizer.py`
- `app/world_awareness/persistence.py`
- `app/world_awareness/replay.py`
- `app/world_awareness/scheduler.py`
- `app/world_awareness/trust.py`
- `app/world_awareness/adapters/openinsider.py`
- `app/world_awareness/adapters/sec_edgar.py`
- `app/world_awareness/adapters/capitol_trades.py`
- `app/world_awareness/adapters/quiver_free.py`
- `app/world_awareness/adapters/official_calendars.py`
- `app/world_awareness/adapters/official_releases.py`

## Implementation

`source_catalog.py` now exposes `source_status_signature(...)`, a catalog-only readiness classifier for portal contribution state. It does not fetch, scrape, authorize live attachment, claim canonical truth, or grant execution authority.

Status outcomes covered:

- `ACTIVE_LOCAL_CACHE`
- `ACTIVE_REPLAY`
- `ACTIVE_PUBLIC_CONFIGURED`
- `INTENTIONALLY_BLOCKED_PREMIUM_KEY_MISSING`
- `INTENTIONALLY_BLOCKED_COMPLIANCE_UNVERIFIED`
- `INTENTIONALLY_BLOCKED_LIVE_ONLY`
- `MISSING_FEED_TRUTH`

The signature includes:

- `module_name`
- `source_name`
- `status`
- `input_truth`
- `output_summary`
- `effect`
- `reason`

## Portal Posture

SEC EDGAR:

- Default status: `INTENTIONALLY_BLOCKED_LIVE_ONLY`
- Cache/replay can be explicitly represented when available.
- Normalized fixture metadata remains advisory and non-canonical.

OpenInsider:

- Default status: `INTENTIONALLY_BLOCKED_LIVE_ONLY`
- Local cache can report `ACTIVE_LOCAL_CACHE`.
- Adapter `fetch()` returns no live data.

Capitol Trades:

- Default status: `INTENTIONALLY_BLOCKED_LIVE_ONLY`
- Replay can report `ACTIVE_REPLAY`.
- Normalized disclosure metadata remains advisory and non-canonical.

Quiver Free:

- Default status: `INTENTIONALLY_BLOCKED_PREMIUM_KEY_MISSING`
- Cache fixture normalization is allowed as cache truth only.
- No premium credential or live feed is fabricated.

Official calendars and releases:

- Default status: `INTENTIONALLY_BLOCKED_LIVE_ONLY`
- Fixture/cache normalization can produce advisory events only.

## Compliance

- No material nonpublic information was ingested, simulated, fabricated, or acted on.
- No live scraping or network attachment was added.
- No broker gateway, order router, execution engine, or paper/live broker mutation authority was added.
- Normalized events set `canonical_truth_claimed=false` and `live_attached=false`.
- Portal outputs remain advisory evidence only.
- Local cache and replay truth remain subordinate to later broker/market truth.

Safety scan across the Seam 7D world-awareness target files found no broker mutation authority, Alpaca endpoints, POST/PATCH/DELETE path, network client import, or secret value. The only match was the intentional premium credential-status reason text in `source_catalog.py`.

## Verification

Compile:

```text
venv/Scripts/python.exe -m py_compile app/world_awareness/source_catalog.py app/world_awareness/config.py app/world_awareness/decay.py app/world_awareness/dedupe.py app/world_awareness/events.py app/world_awareness/models.py app/world_awareness/normalizer.py app/world_awareness/persistence.py app/world_awareness/replay.py app/world_awareness/scheduler.py app/world_awareness/trust.py app/world_awareness/adapters/openinsider.py app/world_awareness/adapters/sec_edgar.py app/world_awareness/adapters/capitol_trades.py app/world_awareness/adapters/quiver_free.py app/world_awareness/adapters/official_calendars.py app/world_awareness/adapters/official_releases.py
```

Result: passed.

Focused Seam 7D:

```text
venv/Scripts/python.exe -m pytest -q tests/test_seam7d_world_awareness_compliance_filters.py
```

Result: `10 passed in 0.54s`.

Related non-mutating regression:

```text
venv/Scripts/python.exe -m pytest -q tests/test_seam7c_intelligence_regime_hydration.py tests/test_seam7b_brain_math_runtime_stability.py tests/test_intelligence_portfolio_state_truth_spine.py tests/test_upstream_dispatch_signal_submission.py
```

Result: `53 passed in 3.91s`.

## 7E Readiness

Seam 7D leaves the portal layer ready for Seam 7E runtime routing as advisory contribution evidence. It does not make these portals execution authorities and does not claim active live-feed truth where none exists.

Remaining blocker for active runtime contribution: Seam 7E must route these signatures and any lawful cache/replay events into the DecisionRecord/telemetry path without fabricating feed truth or bypassing guardrails.
