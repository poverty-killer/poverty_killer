# POVERTY_KILLER REBOOT STATE

Last Updated: 2026-04-06
Status: ACTIVE
Reboot Authority: This file is the primary session reboot and continuity document for POVERTY_KILLER work across chats.

---

## 1. PRIMARY OPERATING RULE

At the start of any new session, upload or paste this file first.
The assistant must treat this file as the current continuity handoff, current-state checkpoint, and active workflow reference.
Do not restart the rebuild from older audit history unless this file explicitly says to.

---

## 2. GOVERNANCE STACK

The following governance remains in force:

* Sovereign / Citadel constitution
* Master Rebuild Plan Pack v3
* CLAUDE.md
* HANDOFF_PACKET.md
* File-by-file workflow only
* No unilateral architecture drift
* Deterministic and replay-safe behavior
* No wall-clock dependence in core logic
* Integer nanosecond timing discipline
* Decimal-only at governed monetary truth boundaries
* No truncation
* No placeholders
* Cost-efficient bounded instruction packets only
* Delta-first for mature files
* Full-file replacement only when truly required
* One complete packet only when asked for a packet
* No patch chains in operating workflow

---

## 3. CORE REBUILD PHILOSOPHY

The rebuild is governed by these standing principles:

* Differentiators must be operational, not decorative
* Do not accept code merely because contracts/imports are cleaner
* Verify differentiators are functionally wired and live
* Prefer bounded, high-signal prompts
* Avoid repeated rediscovery
* Avoid prompt-loop waste
* Preserve accepted base where possible
* Use delta-first for mature files
* Use full-file replacement only when the file is unstable or contract changes require it
* Feed code on demand / on the go rather than storing large stale code context in chat memory
* Board lane should focus on final audit / accept / reject / narrow revision packet only

---

## 4. DIFFERENTIATOR DOCTRINE

### 4.1 Shan's Curve

Shan's Curve must be live in:

* EV
* sizing
* aggression
* stop behavior
* attack mode

Router influence must come indirectly through EV, not by hard overriding sleeve selection directly.

Exact field doctrine:

* `shans_superfluid_score` = distance to asymptote / exhaustion state; consumed by attack mode trigger and stop-width/tightening behavior
* `shans_bias` = directional derivative/sign; feeds fusion directional sign
* `shans_confidence` = density/quality of resting liquidity supporting the curve; feeds sizing / Kelly scaling

### 4.2 Entropy Decoder

Entropy Decoder is:

* confidence / unlock / veto
* not a direction source

It should:

* unlock/scale Shadow-Front
* unlock/confirm FLV
* confirm Gamma Front
* be irrelevant to Sector Rotation
* veto noisy trend-following at high entropy
* veto mean-reversion into deterministic breakouts at very low entropy

### 4.3 Regime Detector

Regime Detector is:

* sleeve authorization system
* risk modifier
* regime bitmask producer

### 4.4 Whale / Insider / Toxicity

* Whale = directional alpha
* Insider = urgency / attack escalation
* Toxicity = tiered suppression / veto

### 4.5 Physical Verification

Layered doctrine:

* pre-filter bad data
* suppress confidence inside fusion on degradation
* hard veto after fusion on severe failure

### 4.6 Mixed-Latency Fusion Doctrine

* slow signals update asynchronously into shared state
* medium signals update routing bitmask on slower cadence
* fast signals run on the low-latency loop
* the fast fusion loop reads latest-known slow/medium state without waiting

### 4.7 Strategy Router Output Doctrine

Strategy Router should output:

* `allowed_sleeves`
* `blocked_sleeves`
* `ranked_sleeves`
* `preferred_sleeve`

`preferred_sleeve` = `ranked_sleeves[0]`

Regime changes should:

* kill incompatible active sleeves
* hand unwind control to risk/orchestrator
* authorize new sleeves from flat

---

## 5. WORKFLOW MODEL

### 5.1 Lane Ownership

* Claude lane = governed audit / migration analysis / bounded repair engineering
* D lane = primary targeted codegen / micro-delta / bounded rebuild lane
* External lane = Chatbox-GPT4o + Gemini on separately assigned files only
* No lane collision
* Keep ownership separated unless explicitly changed

### 5.2 Session Start Flow

1. Load governance context from local files
2. Load this reboot file
3. Confirm current target
4. Upload only active file(s) and direct dependencies
5. Work bounded scope only
6. At session end, replace this file with updated full content

### 5.3 Session End Flow

At end of session, assistant must provide:

* updated current status
* work completed
* work remaining
* next exact target
* next upload requirements
* any newly adopted standing rules
* a full replacement for this reboot file

### 5.4 Operating Efficiency Rule

* One complete packet only when asked for a packet
* No patch chains
* When coding: full-file replacement only
* Board lane should review full returned files only

---

## 6. CURRENT LIVE CHECKPOINT

### 6.1 Completed / Accepted This Session

#### D lane

Target:

* `app/brain/shans_curve.py`

Result:

* accepted as pasted baseline
* grade: Sovereign-Grade
* hybrid rebuild accepted for forward progress

Accepted truths:

* doctrinal triad preserved and live:

  * `shans_superfluid_score`
  * `shans_bias`
  * `shans_confidence`
* hybrid direction preserved:

  * OFI-centered asymptotic core
  * topological persistence redesigned but retained in substance
  * denoising redesigned but retained in substance
  * fill calibration / shadow air-gap preserved
* risk/safety gating truth-cleaned and delegated to caller
* reset contract corrected
* nanosecond handling hardened enough for acceptance

#### External lane

Target:

* `app/strategies/gamma_front.py`

Result:

* accepted as pasted baseline for forward progress
* do not reopen during current rebuild unless direct blocker appears

Accepted truths:

* file did not get dumbed down
* real strategy spine preserved:

  * dark-pool rolling baseline trigger
  * directional front-running behavior
  * macro suppression
  * toxicity suppression
  * options-flow confirmation
  * TTL/cooldown regime
  * ordered exit stack
  * reset/introspection
* hardened with:

  * stronger provisional quantity semantics
  * stronger local diagnostic accounting boundaries
  * stale-position cleanup under halted-feed conditions
  * clearer separation between realized local exits and administrative cleanup

Deferred to endgame hardening:

* external contract-surface certainty
* `StrategySignal.quantity` semantics hard-proofing
* `update_options_flow()` administrative routing certainty

### 6.2 Current Active Problem

#### D lane

Target:

* `app/brain/signal_fusion.py`

Status:

* NOT accepted yet
* current repo has split-brain contract drift
* old SHM / `SovereignSignal` / hydration branch still exists on disk
* reboot-contract fusion path is the intended direction

### 6.3 Claude Contract Audit Verdict

Claude audit established:

* current repo `app/brain/signal_fusion.py` and D reboot candidate were from different contract families
* repo was in split-brain state
* `app/execution/orchestrator.py` is the authoritative consumer contract
* `app/paper_tading.py` is a secondary conflicting caller and may still need separate audit later
* direct paste of the old SHM branch or the wrong fusion branch is not lawful

### 6.4 Current Board Verdict on Signal Fusion

Current pasted/seen old SHM-style `app/brain/signal_fusion.py` is the wrong branch and not accepted.

The correct direction is:

* rebuild `app/brain/signal_fusion.py` against orchestrator-owned reboot contract

Current D reboot candidate is **not yet accepted** because:

1. `update_regime(...)` is effectively unimplemented (`pass`)
2. symbol handling inside `update_regime(...)` is not lawfully resolved
3. `update_market_state(...)` / `get_decision(...)` need tighter, truthful contract handling around optional fields
4. `should_override(...)` / `get_attack_urgency(...)` need hardened handling around stale or missing cached decisions

---

## 7. WHAT IS ALREADY PRESERVED OUTSIDE CHAT

These files already exist in the `poverty_killer` folder and are the main continuity anchors:

* Master Rebuild Plan Pack v3
* CLAUDE.md
* HANDOFF_PACKET.md
* CHATBOX_GPT4O_MASTER_STANDARD.md

This reboot file supplements them and becomes the daily up-to-date state document.

---

## 8. MEMORY STRATEGY

Chat memory should hold only:

* core governance
* doctrine
* workflow preferences
* current checkpoint

Do not rely on chat memory for:

* large code dumps
* stale file snapshots
* old procedural breadcrumbs
* superseded audit loops

Code should be kept locally and uploaded on demand.

---

## 9. FILE FEEDING STRATEGY

### 9.1 For a micro-delta

Upload only:

* target file
* exact contract/type file it depends on
* one or two direct sibling files only if required
* relevant test file only if behavior is under review

### 9.2 For a strategy audit

Upload only:

* target strategy file
* router/contracts file
* emitted/consumed model or type files
* relevant tests

### 9.3 For a brain/differentiator file

Upload only:

* target file
* exact score/signal contract definitions
* immediate producer/consumer files if integration is in question
* relevant tests

### 9.4 For final acceptance review

Upload only:

* target file
* direct contracts
* nearest tests
* any call-site or consumer file whose exact interface matters

---

## 10. CURRENT WORK DONE / WORK REMAINING

### 10.1 Work Done

* governance anchored locally
* `shans_curve.py` accepted and pasted as Sovereign-Grade baseline
* `gamma_front.py` accepted and pasted as forward-progress baseline
* `signal_fusion.py` contract drift identified
* authoritative consumer for fusion established as `app/execution/orchestrator.py`
* workflow corrected to avoid more blind rewrites against the wrong fusion branch

### 10.2 Work Remaining

* receive next D full-file replacement for `app/brain/signal_fusion.py`
* board-review it against:

  * `app/execution/orchestrator.py`
  * `app/models/fusion.py`
  * exact type contracts for `EntropyState` and `UnifiedMarketData`
* determine whether `app/paper_tading.py` needs separate contract reconciliation after fusion is fixed
* continue downstream integration after fusion is accepted

---

## 11. EXTERNAL LANE OWNERSHIP

### 11.1 External Lane Files

Owned files in order:

1. `app/strategies/gamma_front.py`
2. `app/strategies/sector_rotation.py`

### 11.2 External Lane Must Not Touch

* `app/brain/entropy_decoder.py`
* `app/brain/shans_curve.py`
* `app/brain/signal_fusion.py`
* Shan’s Curve downstream migration files
* core risk files
* core execution files
* core spine files
* any file under active Claude/D lane review

### 11.3 External Lane Review Flow

* work one file at a time in assigned order
* audit first if risky, contract-sensitive, or migration-sensitive
* use Gemini as critique/design support only
* when the file is believed ready:

  * produce final candidate
  * provide visible quality rating
  * mark whether it is:

    * not ready
    * close
    * board-ready pending external review
* user brings final candidate to board lane for final audit

---

## 12. NEXT SESSION EXPECTED INPUT

At next session start, provide:

* this reboot file
* current D candidate for `app/brain/signal_fusion.py`
* `app/execution/orchestrator.py`
* `app/models/fusion.py`
* exact type file for `EntropyState` if separate
* exact type file for `UnifiedMarketData` if separate

Optional later support file only if needed:

* `app/paper_tading.py`

---

## 13. NEXT SESSION STARTER PROMPT

Use this at the start of a new chat:

Continue POVERTY_KILLER from reboot state. Board-review mode. One complete packet only when requested. No patch chains. Full-file replacements only when coding.

Locked decisions:

* `app/brain/shans_curve.py` is accepted and already pasted.
* `app/strategies/gamma_front.py` is accepted as pasted baseline for forward progress; final Citadel-grade cleanup deferred to endgame hardening.
* `app/brain/signal_fusion.py` is not accepted yet.

Current state:

* `signal_fusion.py` is on the reboot path, but the current D candidate is blocked because `update_regime(...)` is effectively unimplemented, symbol handling is not lawfully resolved there, and override/urgency behavior needs contract-clean review against orchestrator.
* `app/execution/orchestrator.py` is the authoritative consumer contract.

Current active target:

* D lane on `app/brain/signal_fusion.py`

Task:
Review the attached `signal_fusion.py` candidate against `app/execution/orchestrator.py` and the attached contract/type files. If not accepted, give the next D packet only. If accepted, say approved for paste.

---

## 14. SESSION-END UPDATE TEMPLATE

At the end of each session, replace this whole file with updated content containing:

* Last Updated
* Current status
* Governance changes, if any
* New standing rules adopted, if any
* Work completed this session
* Current accepted baseline
* Work remaining
* Next exact target
* Next required upload set
* Any new warnings, blockers, or truth-disclosure notes

---

## 15. TRUTH-DISCLOSURE RULE

If the public repo, older handoff text, chat history, or pasted code conflict with this reboot file or the newest uploaded source-of-truth files:

* prefer the newest direct source evidence
* explicitly disclose the conflict
* do not silently merge contradictory states

---

## 16. OPERATOR NOTE

This file is the daily reboot memory for POVERTY_KILLER.
At the end of every session, the assistant should provide a full replacement for this file, not a patch.
