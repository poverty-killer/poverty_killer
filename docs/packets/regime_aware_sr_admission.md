# REGIME_AWARE_SR_ADMISSION — Governance Packet

## Status

ACTIVE — Step 1 (governance registration)

Step 2 (runtime behavior patch) requires separate Board authorization.

---

## Design Decision

Option B accepted by the Board.

SectorRotation eligibility gate is **proof-only / opt-in**, inserted at the
signal_fusion layer, conditioned on RANGING regime detection. Default: OFF.

No runtime behavior change is authorized in Step 1.

---

## Prior Bundle

EXECUTION_SR_DECIMAL — PATCH CLOSED / PARTIAL PASS
Commit: 7c50777 Fix EXECUTION_SR_DECIMAL execution boundary

---

## Write Allowlist (Step 2 — active bundle)

Non-locked files:
- app/config.py
- tests/ (prefix match)

Locked authority file with packet-scoped exception:
- app/brain/signal_fusion.py

---

## Explicitly Blocked

- app/main_loop.py
- app/strategies/* (all, including sector_rotation.py and shadow_front.py)
- app/risk/*
- app/core/*
- app/execution/*
- app/models/*
- app/brain/* except app/brain/signal_fusion.py

---

## Acceptance

test_g0_hook_verification.py passes with zero failures after Step 1.

Step 2 acceptance criteria to be defined by Board at Step 2 authorization.

---

## Step 1 Files Changed

- .claude/hooks/pre_tool_use.py — REGIME_AWARE_SR_ADMISSION routing added
- tests/test_g0_hook_verification.py — TestRegimeAwareSRAdmissionPacket added
- docs/EXECUTION_PLAN.md — G0.4 section added
- docs/packets/regime_aware_sr_admission.md — this file
