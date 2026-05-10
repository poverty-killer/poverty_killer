# POVERTY_KILLER OpenCode Governance

Supreme Board is the only authority. OpenCode is a tool. Models are workers. Repo/tests/diffs are evidence.

## Authority Order

1. Current Supreme Board instruction.
2. Latest continuity / Board ruling.
3. Current repo truth from files, imports, diffs, tests, and logs.
4. Stable governance / constitution.
5. Older roadmap documents.
6. Model inference only if evidence is missing, labeled as inference.

## Core Laws

- Preserve-first.
- Strengthen, do not flatten.
- Repo-truth-first.
- Active-path-first.
- No fake integration.
- No duplicate authority.
- No decorative code.
- No broad refactors.
- No threshold relaxation to hide bugs.
- No live mode.
- No `git add .`.
- No `git add -A`.
- Exact-file staging only.
- Stop on out-of-scope discovery.

## OpenCode Role

Plan/scout agents may read, map, analyze, and propose.

Build agents may edit only after an APPROVED EDIT packet from Supreme Board.

No agent may stage, commit, push, reset, clean, stash, delete, or run live mode unless explicitly approved by Supreme Board.

## Parallelism Law

Parallel read-only scouting is approved.

Parallel coding in the same working tree is forbidden.

Parallel coding is allowed only when:
- Supreme Board explicitly approves it.
- Each coding agent uses a separate git worktree.
- Files are independent.
- No shared contract, schema, routing, execution, risk, SignalFusion, StrategyRouter, MainLoop, DecisionCompiler, or model authority file is edited in parallel.
- Each worker returns a diff only.
- One integrator applies accepted diffs serially.
- One final bundle test decides acceptance.

## Stop Conditions

Stop and ask Supreme Board if:
- a needed file is outside approved scope
- tests fail after scoped change
- a contract change is required
- repo state is unexpected
- another agent touched the same file
- live mode, risk, execution, SignalFusion, StrategyRouter, MainLoop, DecisionCompiler, or model contracts become involved outside approval

## Dirty Worktree Warning

The repo may contain unrelated dirty leftovers. Do not stage, clean, delete, reset, or modify them unless the active Board packet explicitly authorizes it.
