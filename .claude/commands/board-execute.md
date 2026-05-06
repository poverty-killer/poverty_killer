# Board Execute

Use after Board approves a phase.

## Inputs Required

- Active packet (POVERTY_KILLER_PACKET value)
- Phase goal
- Files in scope
- Forbidden files
- Commands and checks to run
- Stop conditions

## Process

1. Classify each planned action as GREEN, YELLOW, RED, or BLACK per Board Autopilot Law.
2. Execute GREEN actions automatically without stopping.
3. For YELLOW phase actions, use the Board's one phase approval and execute the full batch.
4. Stop immediately at any RED or BLACK action — do not proceed without explicit Board approval.

## Output

- Files changed (list)
- Commands run (exact commands)
- Tests passed or failed (file + result)
- Proof counters if any
- Diff summary (files and line counts)
- Next risk boundary
- Board decision needed (if any RED/BLACK was reached)

## Rules

- No self-certification of phase completion.
- No claims of readiness based on import success alone.
- No claims of behavior from tests that don't touch the patched path.
- If a stop condition is reached, report the exact condition before halting.
- Split malformed safe commands into smaller safe commands automatically — do not ask Board.

## Action Classification Reference

GREEN: reads, searches, git status/log/diff, targeted pytest, syntax checks, log counters, hook checks.
YELLOW: packet registration, proof run, test batch, exact file staging, proof script creation.
RED: git commit, git push, git add ., file deletion, live mode, override, production patch, broad refactor.
BLACK: force push, destructive delete, fake signals, live trading, bypassing risk/fusion/routing.
