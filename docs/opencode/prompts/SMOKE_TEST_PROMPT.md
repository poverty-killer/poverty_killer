READ-ONLY SMOKE TEST.

Do not edit files.
Do not stage.
Do not commit.
Do not push.
Do not delete.
Do not run tests.
Do not run cleanup.

Confirm:
1. You can see AGENTS.md.
2. You can see .opencode/agents.
3. List the available custom agents.
4. Run only read-only status checks:
   git status --short AGENTS.md .opencode docs/opencode
   git log --oneline -n 3

Return the output only. No recommendations. No edits.
