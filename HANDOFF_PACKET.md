# POVERTY_KILLER — Sovereign Handoff Packet

## Purpose
This file preserves the exact current resume point, accepted scope, blockers, and approved files.
It does not replace `CLAUDE.md`.
It does not replace `POVERTY_KILLER_Master_Rebuild_Pack_v3_Final.docx`.
It exists to preserve tactical continuity between sessions.

## Resume Rule
Do not restart.
Do not ask me to repeat the rules.

Operate under:
- `CLAUDE.md`
- `POVERTY_KILLER_Master_Rebuild_Pack_v3_Final.docx`
- the current governed rebuild workflow defined by `CLAUDE.md` and this handoff packet

## Governing Workflow
1. file-by-file only
2. full-file replacements only
3. we audit the full file in chat
4. only approved files get pasted into VS Code
5. if rejected, reasons are listed
6. next revision must fix those reasons
7. no partial or truncated replacement files
8. no unilateral code changes without approval

## Quality Standard
Target:
- Citadel-grade bot
- novel strategies
- unique capabilities
- deterministic
- replay-safe
- no wall-clock dependence in core logic
- Decimal-only where governed
- nanosecond integer timing
- exacting contract integrity
- no hallucinated compatibility layers
- no fake production claims

## Strict Enhancement Filter
Only accept enhancement suggestions that likely improve bot capability by about 20 percent or more, or provide truly significant novel value.

Reject:
- cosmetic upgrades
- minor polish
- ordinary convenience tweaks
- complexity without major edge, risk, or architecture gain

## Current Session Mode
Do not resume auditing automatically unless I explicitly say:

`let’s get back to auditing`

## Current Audit Target
`app/strategies/strategy_router.py` — CLOSED

## Current Status
`app/strategies/strategy_router.py` is AUDIT-CLOSED.

Both accepted upgrades are applied and approved:
1. deterministic strategy dependency graph — Kahn's topological sort, order preserved when no edges exist, cycle detection at init
2. correlated exposure constraints — three-rule tie-break on routing-stage fields only, routing-order preservation in Rule 3

## Rejected Upgrades
1. dynamic symbol-tier migration
2. priority score recalibration from historical win-rate

These remain rejected under the strict 20 percent / novel-value filter.

## Remaining Open Items
1. `app/models.py` old shadowed file — still on disk, permanently unreachable; must be deleted or renamed in a dedicated bounded session
2. `app/strategies/gamma_front.py` — still an empty stub; dependency/correlation doctrine for this sleeve cannot be established until implemented
3. `app/strategies/sector_rotation.py` — still an empty stub; same constraint as above
4. `StrategyRouter` has zero call sites and zero tests; integration and test coverage deferred

## Instructions When Audit Resumes
Do not reopen `app/strategies/strategy_router.py` unless new direct evidence justifies a bounded follow-up. Current remaining open items are `app/models.py` shadowed-file cleanup, `gamma_front.py` implementation, `sector_rotation.py` implementation, and `StrategyRouter` integration/test coverage.

Do not:
- add any other enhancements
- redesign the file
- reopen rejected ideas

## Approved / Closed Files So Far

### Models / Utilities
- `app/models/enums.py`
- `app/models/contracts.py`
- `app/models/events.py`
- `app/models/invariants.py`
- `app/utils/decimal_utils.py`
- `app/utils/time_utils.py`
- `app/models/fusion.py` — NEW; migrates FusionDecision from unreachable app/models.py into governed package; mutable-default fix applied
- `app/models/__init__.py` — updated to export FusionDecision from app.models.fusion

### Brain Layer
- `app/brain/data_validator.py`
- `app/brain/ring_buffer.py`
- `app/brain/rolling_stats.py`
- `app/brain/recalibrator.py`
- `app/brain/regime_detector.py`
- `app/brain/signal_fusion.py`
- `app/brain/whale_flow_engine.py`
- `app/brain/sentiment_velocity.py`
- `app/brain/sentiment_engine.py`
- `app/brain/shadow_front_state.py`
- `app/brain/toxicity_engine.py`
- `app/brain/insider_signal_engine.py`

### Strategies Layer
- `app/strategies/strategy_router.py` — dependency graph and correlated exposure infrastructure approved; default doctrine remains empty pending future evidenced configuration

## Binding Lessons Preserved
1. no wall-clock use in core logic
2. no fake production compatibility
3. no unilateral code changes without approval
4. full-file replacements only
5. no truncation
6. deterministic behavior only
7. replay-safe only
8. Decimal-only where governed architecture requires it
9. nanosecond integer timing only
10. no cross-layer architectural drift
11. no cosmetic enhancement acceptance
12. only meaningful capability upgrades are allowed
13. preserve purity of pure routing paths
14. audit trail/state must not violate purity boundaries
15. no adaptive drift or performance-chasing logic unless explicitly approved later

## Exact Resume Command
Resume POVERTY_KILLER from governed rebuild state.
Do not restart.
Do not ask me to repeat the rules.
`app/strategies/strategy_router.py` is CLOSED — do not reopen unless new direct evidence justifies a bounded follow-up.
Remaining open items: `app/models.py` shadowed-file cleanup, `gamma_front.py` implementation, `sector_rotation.py` implementation, `StrategyRouter` integration/test coverage.
Everything else stays rejected under the 20 percent / novel-value filter.