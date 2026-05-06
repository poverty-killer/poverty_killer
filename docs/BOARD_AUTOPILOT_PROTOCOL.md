# BOARD_AUTOPILOT_PROTOCOL — POVERTY_KILLER

## Purpose

Reduce approval noise while preserving Board safety at real risk boundaries.

The Board approves phases, not keystrokes.
Claude stops at the next risk boundary, not after every read, grep, diff, or test command.

---

## Principle

After the Board approves a phase, Claude executes the phase checklist autonomously
using GREEN actions and stops only at RED or BLACK boundaries.

This preserves full Board control over commits, production patches, live mode,
overrides, destructive actions, and out-of-scope edits — while eliminating
low-value repeated approvals for read-only, diagnostic, and targeted-test operations.

---

## Action Classification

### GREEN — execute automatically after phase approval

- read files / inspect code
- Grep, Glob, search
- git status --short
- git log --oneline -n N
- git diff, git diff --stat, git diff --cached --stat, git diff --cached --name-only
- python -m pytest tests/<named_file>.py -q (targeted)
- python -m py_compile (syntax check)
- PowerShell: Test-Path, Measure-Object, dir, Get-ChildItem, Get-Content (non-secret)
- Select-String for in-repo proof/report/log files
- python -c safe single-line checks
- python .claude/hooks/pre_tool_use.py hook checks
- proof log counter extraction
- split malformed safe command into smaller safe commands

### YELLOW — one Board approval per phase, then execute the batch

- packet registration phase
- proof script creation phase
- test creation phase
- targeted test batch
- exact file staging (named files, not git add .)
- one approved paper proof run

### RED — always stop for explicit Board approval

- production code patch before approved patch boundary
- git commit
- git push
- git add . / git add --all / git add -A
- git reset / git clean / git restore / destructive checkout
- file deletion
- dependency changes
- credential / secret / .env edits
- live mode
- override mode
- risk weakening or threshold relaxation
- second proof run
- broad refactor
- edit outside active packet allowlist
- failed test requiring diagnosis
- hook block requiring investigation
- diff exceeding declared scope

### BLACK — forbidden unless Board changes governance

- live trading command
- git push --force
- git clean -fd / git reset --hard
- recursive destructive delete
- editing secrets or .env files
- bypassing SignalFusion, StrategyRouter, Shans Curve, or RiskGuard
- fake signals, fake fills, fake observed pairs
- POVERTY_KILLER_OVERRIDE=true or LIVE_MODE=true via shell

---

## Phase Approval Format

When requesting Board approval for a phase, Claude must state:

1. Phase goal
2. Files in scope
3. Commands and checks to run (classified GREEN/YELLOW)
4. Stop conditions (what will trigger a RED/BLACK halt)
5. Expected outputs

After Board approves, Claude executes the checklist without asking again unless
a stop condition is reached.

---

## Stop Conditions (Claude halts and reports to Board)

- RED action reached
- BLACK action would be needed
- Hook block triggered
- Test fails with error requiring diagnosis
- Diff exceeds declared scope
- Out-of-scope file touched
- Live mode appears in any command or config
- Proof produces error requiring diagnosis
- Continuity conflict detected (CURRENT_STATUS vs git log vs packet doc)

---

## Relation to Prior Rules

G0.1 (Bounded Read-Only Evidence Extraction) is superseded by GREEN actions above.
GREEN actions are a strict superset of G0.1's bounded read-only allowlist.

All prior packet allowlists (F4A, F4B, F4C, STRATEGY_ADMISSION, EXECUTION_SR_DECIMAL,
REGIME_AWARE_SR_ADMISSION, SECTOR_ROTATION_FRESH_OBSERVED_PAIR_PROOF_BUNDLE) remain
active. GREEN/YELLOW/RED/BLACK classifications apply within the active packet boundary.

---

Installed: G0.6 — BOARD_AUTOPILOT_AND_CONTINUITY_PROTOCOL
