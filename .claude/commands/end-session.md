# End Session Closeout

Purpose:
Preserve continuity after each bundle, proof, or major commit.

## Closeout Summary

At session end or bundle close, produce:

1. What was completed this session
2. Commits created (hash + message)
3. Tests passed (file + result)
4. Proofs run (command + verdict)
5. Counters and verdict if proof ran (PASS / PARTIAL PASS / FAIL)
6. Current blocker
7. Next bundle
8. Expected POVERTY_KILLER_PACKET for next session
9. Authorized files for next packet
10. Forbidden files for next packet
11. Known noisy/unrelated files in worktree
12. Exact next Board action

## docs/CURRENT_STATUS.md Update

If Board approves, update docs/CURRENT_STATUS.md with the closeout summary.

## Rules

- Keep status short. No raw log dumps. No secrets.
- Do not overwrite historical packet docs.
- Do not stage or commit closeout updates without Board approval.
- Do not push unless separately authorized.
- Updating CURRENT_STATUS.md is a RED action — requires Board approval.
- Committing closeout is a RED action — requires Board approval.
