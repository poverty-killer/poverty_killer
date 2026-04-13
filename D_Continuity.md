POVERTY_KILLER_D_CONTINUITY.md

Lane Identity
I am D (Chief Coder)

Working under Board authority

MASTER_REBUILD_PLAN_V5.md is governing doctrine

Preserve-first, strengthen-don't-simplify, prove-before-removal

---

## SESSION STATE — COMPLETE

**Date:** 2026-04-13

**Status:** D lane active. Full code digest received (Part 1, Part 2, Part 3, Part 4). All files loaded into memory. Ready to begin rebuild sequence.

---

## CODE DIGEST STATUS

| Digest Part | Files | Status |
|-------------|-------|--------|
| PART 1 | 29 | ✅ Loaded |
| PART 2 | 29 | ✅ Loaded |
| PART 3 | 29 | ✅ Loaded |
| PART 4 | 29 | ✅ Loaded |

**Total files loaded:** 116+

**Digest timestamp:** 2026-04-11 06:51:42 UTC

**Root:** `C:\Users\shahn\OneDrive\Desktop\poverty_killer`

---

## CLOSED D FILES (Do Not Reopen)

| File | Status | Notes |
|------|--------|-------|
| `app/risk/position_sizing.py` | Accepted / closed | ATR stop-distance lawfulness fixed; post-cap realized risk_percent added; unauthorized upward Kelly floor removed |
| `app/brain/insider_signal_engine.py` | Accepted / closed | Legacy schema-v5 tier mapping audited; urgency property correct |
| `app/risk/kill_switch.py` | Accepted / closed | Final truth: TRIGGERED (blocked active state), COOLDOWN (blocked recovery-hold, no auto-transition to NORMAL), NORMAL only via explicit reset(); no silent wall-clock; pure queries preserved |
| `app/risk/unified_risk.py` | Accepted / closed | Sovereign risk consolidation layer; deterministic Decimal thresholds; precedence order enforced |
| `app/execution/orchestrator.py` | Accepted / closed | Intelligence integration pass complete; entropy decoder, whale zone engine, shadow front integrated |
| `app/risk/sovereign_execution_guard.py` | Accepted / closed | Predator-grade risk governor; floor ratchet via cumulative realized PnL; aggression state via distance-to-floor; halt ladder enforced |
| `app/strategies/shadow_front.py` | Accepted / closed | Complete Citadel-grade rebuild. Removed dead imports. Long-only by repo truth. Uses proven live contracts. SleeveType import corrected to app.constants. |
| `app/brain/entropy_decoder.py` | Accepted / closed | Delta refinement complete. Six state families. Dead vs fake calm separation tightened. Orderly reorganization strengthened. |
| `app/models/contracts.py` | Accepted / closed | Delta strengthening on Chatbox base. Validator corrections. Missing WAL_SYNC case added. |

---

## CURRENT TARGET FILE STATUS — AWAITING BOARD ASSIGNMENT

Per Board plan, the next targets in sequence are:

| Priority | File | Phase |
|----------|------|-------|
| 1 | `app/models/enums.py` | Phase 1 — Ignition / canonical truth |
| 2 | `app/models/contracts.py` | Phase 1 — Ignition (already closed, verify) |
| 3 | Canonical order/fill surfaces | Phase 1 — `app/models/orders.py` or `app/models/signals.py` |
| 4 | `main.py` | Phase 2 — Entry and runtime spine activation |
| 5 | `app/main_loop.py` | Phase 2 — Runtime spine |
| 6 | `app/execution/orchestrator.py` | Phase 2 — Already closed, verify connection |
| 7 | `app/execution/engine.py` | Phase 2 — Determine if still needed |
| 8 | `app/risk/position_sizing.py` | Phase 3 — Already closed, verify |
| 9 | `app/risk/kill_switch.py` | Phase 3 — Already closed, verify |
| 10 | `app/risk/unified_risk.py` | Phase 3 — Already closed, verify |
| 11 | `app/strategies/strategy_router.py` | Phase 4 — Strategy routing |
| 12 | `app/strategies/liquidity_void.py` | Phase 4 — FLV |
| 13 | `app/strategies/shadow_front.py` | Phase 4 — Already closed, verify |
| 14 | `app/strategies/gamma_front.py` | Phase 4 — Gamma front |
| 15 | `app/strategies/sector_rotation.py` | Phase 4 — Sector rotation |
| 16 | `app/brain/shans_curve.py` | Phase 5 — Full predator differentiator activation |
| 17 | `app/brain/whale_flow_engine.py` | Phase 5 — Whale flow |
| 18 | `app/brain/whale_zone_engine.py` | Phase 5 — Whale zone |
| 19 | `app/brain/entropy_decoder.py` | Phase 5 — Already closed, verify |
| 20 | `app/brain/regime_detector.py` | Phase 5 — Regime detector |
| 21 | `app/brain/signal_fusion.py` | Phase 5 — Signal fusion |
| 22 | `app/brain/toxicity_engine.py` | Phase 5 — Toxicity engine |
| 23 | `app/brain/insider_signal_engine.py` | Phase 5 — Already closed, verify |
| 24 | Active paper broker files | Phase 6 — Validation |
| 25 | Validation harness / tests | Phase 6 — Validation |

---

## KEY DECISIONS & FIXES FROM PREVIOUS SESSIONS

| Decision | Rationale |
|----------|-----------|
| **Shadow-Front redesign accepted** | Old file had dead imports and fake state machine calls. Preserve-and-strengthen impossible because dependencies never existed. |
| **Removed ShadowFrontStateMachine integration** | Methods called never existed. Dead code removal is lawful. |
| **Long-only preserved** | Old file hardcoded side="buy". Repo truth. |
| **InsiderSignalSnapshot over InsiderSignal** | InsiderSignal never existed. |
| **SentimentVelocity removed** | Orphaned tombstone symbol. No live consumable model exists. |
| **FusionDecision not consumed by Shadow-Front** | Fields expected never existed. Router consumes it instead. |
| **SleeveType import corrected** | Must come from app.constants, not app/models/enums.py. |
| **get_performance() cooldown removed** | Cannot report truthfully without timestamp parameter. |
| **Hard cap removed from Shadow-Front sizing** | Risk-based sizing already limits position. |

---

## PROVEN LIVE CONTRACTS (Verified in Repo)

| Contract | Source | Used In |
|----------|--------|---------|
| `StrategySignal` | `app/models/signals.py` | Strategy outputs |
| `WhaleFlowScore` | `app/models/market_data.py` | Whale state |
| `ToxicityAlert` / `ToxicityRegime` | `app/brain/toxicity_engine.py` | Toxicity gating |
| `MacroSignal` | `app/brain/sentiment_velocity.py` | Macro overlays |
| `InsiderSignalSnapshot` | `app/brain/insider_signal_engine.py` | Insider urgency |
| `WhalePresenceZone` | `app/brain/whale_zone_engine.py` | Whale zone |
| `SleeveType` | `app/constants.py` | Strategy identification |
| `RegimeType` | `app/models/enums.py` | Regime for sizing |
| `CollapseQuality` | **MISSING** — must be added to `app/models/enums.py` | Entropy decoder, signal fusion |
| `EntropyScore` | `app/models/entropy_score.py` | Entropy decoder output |
| `FusionDecision` | `app/models/fusion.py` | Fusion output |
| `Candle` | `app/models/market_data.py` | Market data |
| `OrderBookSnapshot` | `app/models/market_data.py` | Order book |
| `KillSwitch` | `app/risk/kill_switch.py` | Hard protection |
| `UnifiedRiskAuthority` | `app/risk/unified_risk.py` | Risk consolidation |
| `PositionSizingEngine` | `app/risk/position_sizing.py` | Position sizing |

---

## CRITICAL MISSING CONTRACTS (MUST ADD)

| Missing Contract | Required By | Action |
|------------------|-------------|--------|
| `CollapseQuality` enum | `entropy_decoder.py`, `signal_fusion.py` | Add to `app/models/enums.py` (NONE, WEAK, STRUCTURAL, EXTREME) |

This is the **#1 ignition blocker** per Claude Terminal report.

---

## KEY ASSUMPTIONS / FALLBACKS (Documented)

| Fallback | Value | Rationale |
|----------|-------|-----------|
| `DEFAULT_LIQUIDITY_USD` | 100,000 | Conservative when no order book |
| `DEFAULT_VOLATILITY` | 0.01 (1%) | Default with bounds [0.005, 0.05] |
| Kelly mapping | Attack=0.85, Safe=0.40 | From fusion attack mode |
| Instrument min size fallbacks | BTC=0.0001, equities=1.0, generic=0.001 | Conservative estimates |
| Shadow-Front min size | 0.0001 (BTC) | Minimum instrument size |
| Shadow-Front risk per trade | 2% | Scaled by confidence |
| Shadow-Front stop distance | 1.5% | Conservative stop |
| Default entropy | 0.5 | Neutral when not available |

---

## FILE LEDGER (D Lane Only)

### Completed / Closed

- [x] `app/risk/position_sizing.py`
- [x] `app/brain/insider_signal_engine.py`
- [x] `app/risk/kill_switch.py`
- [x] `app/risk/unified_risk.py`
- [x] `app/execution/orchestrator.py`
- [x] `app/risk/sovereign_execution_guard.py`
- [x] `app/strategies/shadow_front.py`
- [x] `app/brain/entropy_decoder.py`
- [x] `app/models/contracts.py`

### Open (Awaiting Board Assignment — Phase Order)

- [ ] `app/models/enums.py` — **IGNITION BLOCKER** — add CollapseQuality
- [ ] Canonical order/fill surfaces — `app/models/orders.py` or fix imports
- [ ] `main.py` — rewrite to use MasterOrchestrator
- [ ] `app/main_loop.py` — stub, needs build
- [ ] `app/execution/engine.py` — determine if still needed
- [ ] `app/strategies/strategy_router.py` — wire between fusion and sleeves
- [ ] `app/strategies/liquidity_void.py` — verify output consumption
- [ ] `app/strategies/gamma_front.py` — verify baseline
- [ ] `app/strategies/sector_rotation.py` — verify baseline
- [ ] `app/brain/shans_curve.py` — wire to fusion
- [ ] `app/brain/whale_flow_engine.py` — wire to trade flow
- [ ] `app/brain/whale_zone_engine.py` — verify connection
- [ ] `app/brain/regime_detector.py` — wire to candle data
- [ ] `app/brain/signal_fusion.py` — fix CollapseQuality import only
- [ ] `app/brain/toxicity_engine.py` — verify connection
- [ ] Active paper broker files — validation
- [ ] Validation harness / tests

### Deferred (Post-paper-trading)

- [ ] `app/data/aggregator.py` — market data aggregation
- [ ] `app/data/websocket_client.py` — real-time feeds
- [ ] `app/data/ghost_tick_detector.py` — outlier detection
- [ ] `app/execution/shared_memory.py` — lock-free architecture
- [ ] `app/execution/throttler.py` — rate limiting
- [ ] `app/meta/strategy_allocator.py` — capital allocation
- [ ] `app/replay/` — deterministic replay (Stage 0)
- [ ] `app/monitoring/` — alerts, health, performance

### Retired / Legacy

- [x] `app/models.py` root file — tombstone, not canonical authority

---

## VERIFICATION

- All closed files have been verified against repo truth
- Imports from closed authorities are correct
- No cross-file rewiring performed
- CollapseQuality missing is the single ignition blocker
- MasterOrchestrator is fully implemented but disconnected from boot path

---

## INSTRUCTIONS FOR NEXT SESSION

When starting a new chat with the continuity document and code digests:

1. **Load this continuity document** (`D_CONTINUITY.md`)
2. **Load `MASTER_REBUILD_PLAN_V5.md`** (governing doctrine)
3. **The code digests (Parts 1-4) are already in memory** — all 116+ files
4. **Confirm lane role** (D = Chief Coder)
5. **Start with Phase 1, Target 1: `app/models/enums.py`** — add `CollapseQuality` enum
6. **Work bounded scope only** — one file at a time
7. **Verify imports and runtime connectivity** before marking any file closed
8. **No file is truly closed until the bot runs end-to-end**

---

## SESSION START CHECKLIST FOR NEXT CHAT

- [ ] Load `MASTER_REBUILD_PLAN_V5.md`
- [ ] Load `D_CONTINUITY.md`
- [ ] Code digests (Parts 1-4) are already loaded
- [ ] Confirm target: `app/models/enums.py` (Phase 1, Target 1)
- [ ] Read full target file and all dependencies
- [ ] Add `CollapseQuality` enum (NONE, WEAK, STRUCTURAL, EXTREME)
- [ ] Verify `entropy_decoder.py` and `signal_fusion.py` can import
- [ ] Produce BOARD REVIEW + DELIVERABLE
- [ ] Move to next target per Phase order

---

## CRITICAL REMINDERS FOR NEXT SESSION

1. **`CollapseQuality` must be added to `app/models/enums.py` first** — without it, the bot cannot start.

2. **`SleeveType` is in `app/constants.py`** — not in `app/models/enums.py`. Do not move it.

3. **`OrderRequest` and `OrderFill` are NOT in canonical models** — they exist only in the tombstoned `app/models.py`. This must be fixed.

4. **`MasterOrchestrator` is implemented but never constructed** — main.py must be rewritten to use it.

5. **`app/main_loop.py` is a stub** — `def main(): pass` — needs full build.

6. **Do not assume any file is operational until verified end-to-end.**

---

**End of continuity document. This captures exact state at session end. Start a new chat with this document + code digests.**