# Start Session Intake

Purpose:
Prevent Claude from rediscovering prior work after restart.

At every new Claude Code session, before diagnosis, patching, proof runs, staging,
or commits, perform bounded startup intake.

## Intake Reads (in order)

1. claude.md
2. docs/CURRENT_STATUS.md
3. docs/EXECUTION_PLAN.md
4. Active packet doc from docs/packets/ if it exists
5. docs/BOARD_AUTOPILOT_PROTOCOL.md
6. git log --oneline -n 10
7. git status --short

## Startup Report

After reads, produce:

- active bundle
- current phase
- expected POVERTY_KILLER_PACKET value
- latest relevant commit hash and message
- last closed bundle
- current blocker
- authorized files for active packet
- forbidden files for active packet
- current test/proof status
- whether patching is allowed in this phase
- noisy worktree warning (if unrelated files present)
- exact next action

## Rules

- Do not reread the full repo.
- Do not patch during startup intake.
- Do not run proof during startup intake.
- Do not commit during startup intake.
- If the expected packet does not match the environment packet, stop and alert Board.
- If CURRENT_STATUS conflicts with git log or packet docs, stop and report the conflict.
- All intake reads are GREEN actions (no Board approval needed per Board Autopilot Law).
