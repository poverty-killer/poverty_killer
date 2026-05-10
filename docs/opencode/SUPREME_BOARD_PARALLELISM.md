# Supreme Board Parallelism Policy for OpenCode

## Default Agent Caps

- Read-only scouts: up to 7
- Diff auditors: up to 3
- Test scouts: up to 3
- Coding agents in same tree: 1
- Coding agents in isolated worktrees: up to 3, only with Board approval
- Final integrator: 1

## Safe Pattern

1. Scouts inspect in parallel.
2. Board synthesizes findings.
3. Board issues exact edit packet.
4. Builder edits exact files only.
5. Tests run.
6. Diff is audited.
7. Board accepts or rejects.
8. Exact files are staged.
9. Commit/push require explicit approval.

## Never Edit These in Parallel

- main.py
- app/main_loop.py
- app/models/*
- app/core/decision_compiler.py
- app/execution/*
- app/brain/signal_fusion.py
- app/strategies/strategy_router.py
- app/risk/*
- config files
- credentials
- shared schemas
- shared enums
- live broker path

## Allowed Parallel Coding Candidates

Only with Board approval:
- independent test files
- isolated docs
- isolated telemetry helpers
- isolated adapters
- leaf modules with no contract changes

## Attribution Law

Every parallel worker must report:
- worktree path
- assigned files
- exact diff
- tests run
- files touched
- out-of-scope discoveries

No worker stages, commits, pushes, resets, cleans, stashes, or deletes.
