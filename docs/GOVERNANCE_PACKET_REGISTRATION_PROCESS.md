# GOVERNANCE_PACKET_REGISTRATION_PROCESS — POVERTY_KILLER

Repo-Truth / Preserve-First / Anti-Precedent Version

This document is the standing process for adding, modifying, or removing
packet names recognized by `.claude/hooks/pre_tool_use.py`.

It exists because the hook gate enforces who-may-edit-what. Every recognized
packet name is a write authority. Adding a packet name is therefore a
governance act, not a technical convenience.

This document does not relax any existing rule. It records the lawful,
narrow path for packet registration so that no future packet ever needs to
self-register, no unrelated bundle ever needs to patch hooks as a side
effect, and no convenience exception ever erodes the unknown-packet block.

PRESERVE!!!!!

---

## 1. Purpose

Define how new packet names are added to the hook so that:

- the unknown-packet block remains intact,
- no packet self-registers,
- no unrelated technical bundle patches the hook as a side effect,
- no broad or catch-all allowlists are introduced,
- every registration is testable, traceable, and reversible,
- the precedent that hooks are RED stays inviolate outside the dedicated
  governance scope.

Packet registration is a write-authority change. It is treated with the
same care as a risk threshold change: minimal, exact, tested, attributable.

---

## 2. Authority Model

Only the Board may authorize a new packet name.

Claude Terminal:
- may not invent a packet name.
- may not add a packet name to the hook on its own initiative.
- may not modify an existing packet's allowlist on its own initiative.
- may not bypass the unknown-packet block via override, alias, or
  catch-all rule.

Authority is exercised by an explicit Board ruling (text packet, signed
or attributable), naming the active packet for the registration session.

The active packet for a registration session is **G0**.

There is no separate `BOOTSTRAP_*` packet. There is no
`GOVERNANCE_PACKET_REGISTRATION_PROCESS_BUNDLE` packet. Registration is a
G0 governance act and uses G0's existing allowlist.

---

## 3. Normal Packet-Registration Workflow

Use this workflow when the Board has authorized a new packet name in
advance, the work is non-emergency, and full G0 governance discipline can
be observed.

1. **Board ruling.** Board issues a written ruling that names the new
   packet, declares its mission, and states the exact allowlist.
2. **Active packet = G0.** Set `POVERTY_KILLER_PACKET=G0` for the
   registration session.
3. **Read-only inspection.** Read `.claude/hooks/pre_tool_use.py`,
   `tests/test_g0_hook_verification.py`, `claude.md`, and the existing
   `docs/EXECUTION_PLAN.md` entry for the prior packet of the same shape.
4. **Hook patch.** Add the new packet name and its allowlist to
   `pre_tool_use.py`. The patch must:
   - introduce a new exact-file `frozenset` for that packet,
   - introduce a tuple of allowed prefixes only when needed,
   - add packet-scoped exceptions to `LOCKED_AUTHORITY_FILES` only when
     the Board ruling explicitly grants them by exact path,
   - add a single new branch in `packet_allows_path()` that returns the
     packet-specific block reason on miss,
   - never widen `G0_ALLOWLIST` beyond governance documents,
   - never add an allowlist that overlaps another packet's mission.
5. **Test patch.** Add a new test class to
   `tests/test_g0_hook_verification.py` that proves:
   - every allowed exact file approves under the packet,
   - every allowed prefix approves under the packet,
   - every locked-authority exception approves under the packet,
   - every other locked-authority file blocks under the packet with
     `locked_authority_file` reason,
   - at least one explicitly-out-of-scope production file blocks under
     the packet with the packet-specific outside-allowlist reason,
   - dangerous Bash patterns remain blocked under the packet
     (live mode, `--attack`, dependency mods, destructive git,
     `git add .`, override-via-shell).
6. **Targeted test run.** Run only `python -m pytest
   tests/test_g0_hook_verification.py -q`. All tests must pass.
7. **Execution plan note.** Append a status block to
   `docs/EXECUTION_PLAN.md` recording the registration: packet name,
   mission, allowlist, locked exceptions if any, and acceptance status.
8. **Stop and report to Board.** Files changed, tests run, pass/fail
   counts, exact diff summary, hook behavior delta, proposed staging
   commands. No commit.
9. **Board approves staging and commit.** Only then are the named files
   staged and committed. Push requires a separate Board approval.

---

## 4. Emergency Packet-Registration Workflow

Use this workflow only when the Board declares an emergency in writing
and authorizes accelerated packet registration.

Disfavored. Override remains rejected. The emergency path narrows scope,
not safety.

1. **Board emergency ruling.** Written, attributable, names the packet,
   the mission, and the exact allowlist.
2. **Active packet = G0.** No emergency packet name is created to
   register a packet name.
3. **Smallest possible patch.** The hook patch and the test patch are
   reduced to the minimum required to register the new packet. No
   adjacent cleanup, no opportunistic edits, no doc additions beyond the
   execution-plan entry.
4. **Targeted tests must still pass.** No skipping. No `--no-verify`.
   No threshold relaxation in tests to accommodate the new packet.
5. **Stop and report.** Same report shape as the normal workflow, plus
   an explicit `EMERGENCY=true` note and the Board's stated reason.
6. **Commit only after Board approval.** Push only after a separate
   Board approval.

The emergency path does not bypass tests, does not bypass unknown-packet
block, does not add catch-all permissions, does not weaken protected
patterns. It only compresses the schedule.

---

## 5. Allowed Files (registration phase)

Under `POVERTY_KILLER_PACKET=G0`, a registration session may write only:

- `.claude/hooks/pre_tool_use.py` — to add the new packet branch and
  allowlist.
- `tests/test_g0_hook_verification.py` — to add the new test class.
- `docs/EXECUTION_PLAN.md` — to record the registration.
- `docs/packets/<packet_name>.md` — only if pre-existing in
  `G0_ALLOWLIST` for that exact packet doc, or added to `G0_ALLOWLIST`
  in the same registration patch.
- `docs/GOVERNANCE_PACKET_REGISTRATION_PROCESS.md` — only when the
  Board explicitly authorizes a process update.

No file outside this list may be touched during the registration phase.
The packet's own production patch phase is a separate Board-approved
phase under the new packet name and is not part of registration.

---

## 6. Disallowed Files (registration phase)

Under any registration session:

- no `app/` file may be edited.
- no `main.py` edit.
- no `state/` write outside the journal/override-log files written by
  the hooks themselves.
- no `reports/` write.
- no `data/` write.
- no `requirements.txt`, `pyproject.toml`, lock-file, or other
  dependency manifest edit.
- no `.env`, `.env.*`, or other secret-bearing file edit.
- no `.claude/settings.json` schema change unrelated to packet
  registration.
- no commit, no push, no `git add .`, no `git add --all`, no `git add -A`.

The hook itself enforces most of these. The process forbids attempting
them in the first place.

---

## 7. Mandatory Tests

Every registration patch must include a new test class in
`tests/test_g0_hook_verification.py` that proves, at minimum:

1. **Allowed paths approved.** Every exact file in the new packet's
   allowlist returns `decision == "approve"` under that packet.
2. **Allowed prefixes approved.** Every prefix (e.g. `tests/`)
   returns `decision == "approve"` for at least one representative
   path under that packet.
3. **Locked exceptions approved.** Every locked-authority file with a
   packet-scoped exception returns `decision == "approve"` under that
   packet.
4. **Locked non-exceptions blocked.** At least one locked-authority
   file without a packet-scoped exception returns `decision == "block"`
   with `locked_authority_file` in the reason under that packet.
5. **Out-of-scope production files blocked.** At least one
   non-locked production file outside the packet's allowlist returns
   `decision == "block"` with the packet-specific
   `<packet>_outside_allowlist` reason.
6. **Unknown packet still blocks.** A typo'd or unrelated packet name
   continues to block with `no_active_packet_or_unknown_packet`.
7. **Dangerous Bash still blocks under the packet.** At least one of
   each pattern class — live mode, `--attack`, destructive git,
   dependency change, `git add .`, override-via-shell — returns
   `decision == "block"` with `dangerous_bash` in the reason.

The Board may demand additional invariants for high-authority packets
(e.g. those with locked-authority exceptions).

---

## 8. Evidence Required Before Commit

Before any registration patch is staged or committed, the Board must
receive a report containing:

- exact list of files changed,
- exact list of files created,
- exact list of tests added,
- exact pytest command run, and exit code,
- pass/fail count for the targeted run,
- diff summary (line additions/deletions per file),
- explicit statement that no production/trading file changed,
- explicit statement that no allowlist outside the new packet was
  widened (G0 allowlist additions for governance docs are explicitly
  noted),
- explicit statement that no dangerous-pattern protection was relaxed,
- proposed exact `git add` commands listing each file by name.

Reports that say "all green, ready to commit" without listing the
above are insufficient.

---

## 9. Exact-File Staging Rule

Staging during a registration session must:

- list every file by exact relative path,
- never use `git add .`, `git add --all`, `git add -A`, or any
  recursive add,
- never stage files outside the registration phase allowlist,
- be issued only after Board approval of the registration report.

A typical staging command set looks like:

    git add .claude/hooks/pre_tool_use.py
    git add tests/test_g0_hook_verification.py
    git add docs/EXECUTION_PLAN.md
    git add docs/packets/<new_packet>.md

Each line is reviewed by the Board before execution.

---

## 10. Commit and Push Approval Rule

- Commit requires a separate Board approval after the registration
  report is reviewed.
- Push requires a further separate Board approval after the commit is
  inspected with `git show`.
- `--no-verify`, `--no-gpg-sign`, and `--amend` are not used in
  registration commits.
- Force pushes are forbidden. Push to `master` is treated as RED in
  every case.

---

## 11. Anti-Precedent Rule

Unrelated technical bundles must not patch the hook.

A bundle whose mission is execution Decimal discipline, sentiment
concurrency, paper-fill repair, dispatch-path repair, or any similar
production-side mission **must stop** if the hook gate blocks it. It
must not propose a hook patch as part of the same bundle. It must
report the gate problem and wait for a separate registration session.

This rule prevents three failure modes:

- the **hidden-registration** failure mode, where a packet expands its
  own allowlist mid-mission;
- the **convenience-bypass** failure mode, where Claude or a future
  operator widens the hook to make a recurring stop go away;
- the **drift** failure mode, where each successive bundle leaves the
  hook slightly weaker than it found it.

Hook edits are RED outside the registration scope. The unknown-packet
block is the spine of write-authority enforcement. It does not bend.

---

## 12. Multi-Mission Packets

A packet may cover more than one mission only when:

- both missions are explicitly named in the Board ruling,
- the union of their write scopes is explicitly enumerated and is
  narrower than the union of unrelated production authorities,
- the test class proves each allowlist entry independently,
- the packet name reflects both missions (no euphemisms).

Multi-mission packets are disfavored. Splitting into two narrowly
scoped packets is the default. A multi-mission packet must justify
itself in the EXECUTION_PLAN entry.

---

## 13. Temporary Packet Aliases

Temporary aliases are rejected.

There is no `_TMP`, `_DRAFT`, `_BOOTSTRAP`, or any short-lived packet
name. Every recognized packet has a stable name, a recorded mission,
and a written closing status.

If a packet's mission narrows or expands during execution, the Board
issues a new packet ruling under a new name. The hook is patched in a
fresh registration session. The old packet is closed in
`docs/EXECUTION_PLAN.md` with status PARTIAL, REPLACED, or CLOSED.

---

## 14. Preventing Hook Edits From Becoming a Convenience Bypass

The following invariants are enforced by tests and reinforced by this
process:

- The unknown-packet branch returns `block` with
  `no_active_packet_or_unknown_packet` whenever the packet env var is
  unset, blank, or unrecognized.
- No catch-all packet name (e.g. `ALL`, `*`, `ANY`, `BYPASS`,
  `BOOTSTRAP`) is added.
- No allowlist contains a wildcard that resolves to all files.
- No locked-authority file is removed from `LOCKED_AUTHORITY_FILES`
  without an explicit Board ruling.
- No dangerous Bash pattern is removed without an explicit Board
  ruling.
- Every `LOCKED_AUTHORITY_FILES` exception is recorded by exact path
  in a packet-specific exception set.
- The hook test suite remains the single source of governance proof,
  and is run on every registration.

A registration that violates any of these is rejected at the patch
review step and never reaches commit.

---

## 15. Checklist for Future Packet Registration

Use this checklist literally. Each item must be checked before the
registration report is issued.

- [ ] Board ruling received in writing, naming packet, mission, and
      exact allowlist.
- [ ] Active packet env set to `G0`.
- [ ] Read `.claude/hooks/pre_tool_use.py` (full).
- [ ] Read `tests/test_g0_hook_verification.py` (full).
- [ ] Read prior comparable packet's allowlist for shape reference.
- [ ] Hook patch adds exactly one new packet branch.
- [ ] Hook patch adds exactly one new exact-file allowlist `frozenset`.
- [ ] Hook patch adds prefix tuple only when required.
- [ ] Hook patch adds locked-authority exceptions only by exact path.
- [ ] Hook patch does not widen any other packet's allowlist.
- [ ] Hook patch does not weaken any dangerous pattern.
- [ ] Hook patch does not weaken any safe-shape rule.
- [ ] G0 allowlist is widened only for governance docs and only when
      explicitly required.
- [ ] Test class added to `tests/test_g0_hook_verification.py`.
- [ ] Test class covers every mandatory invariant in §7.
- [ ] Targeted pytest run executes and passes with zero failures.
- [ ] `docs/EXECUTION_PLAN.md` entry appended with packet name,
      mission, allowlist, locked exceptions, and acceptance status.
- [ ] Optional packet doc `docs/packets/<name>.md` added only if
      already in `G0_ALLOWLIST` or added in the same patch.
- [ ] Registration report issued to Board listing every change,
      every test, and the pass/fail summary.
- [ ] No commit attempted before Board approval.
- [ ] Staging uses exact-file `git add` commands only.
- [ ] Push requires a separate Board approval.

---

## 16. Final Command

Do not register a packet to make a stop go away.

Do not weaken the unknown-packet block.

Do not create alias packets.

Do not patch hooks as a side effect.

Do not widen allowlists for convenience.

Do not commit or push without Board approval.

Use this process. Hold the line.

PRESERVE!!!!!
