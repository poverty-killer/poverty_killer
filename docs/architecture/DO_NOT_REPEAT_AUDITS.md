# POVERTY_KILLER Do Not Repeat Audits

## Purpose

This file tells future OpenCode sessions how to avoid wasting context, time, and money.

Read this file at the start of every OpenCode session.

## Required Session Start

At the start of a new OpenCode session, read these files first:

1. docs/architecture/CURRENT_REBUILD_STATUS.md
2. docs/architecture/SESSION_CHANGELOG.md
3. docs/architecture/DO_NOT_REPEAT_AUDITS.md
4. docs/architecture/MODULE_INTENT_REGISTRY.md only for relevant modules
5. docs/architecture/AUTHORITY_WIRING_MAP.md only for relevant authorities
6. docs/architecture/SEAM_ACTIVATION_QUEUE.md
7. docs/architecture/OPEN_QUESTIONS.md

Do not begin by scanning the whole repo unless the active packet explicitly requires it.

## Reuse Rule

Reuse prior audit findings unless:

- the file changed after the audit
- the file is listed in OPEN_QUESTIONS.md
- the active packet touches the file
- the prior finding was marked UNKNOWN_REQUIRES_EVIDENCE
- the claim lacks file/line evidence and is safety-critical
- there is a conflict between context spine and repo truth

## What To Inspect

Inspect only:

- files changed since the last checkpoint
- files in the active packet scope
- files marked UNKNOWN_REQUIRES_EVIDENCE
- files tied to unresolved open questions
- direct imports/call sites for the active seam
- tests required by the active seam

## What Not To Repeat

Do not repeat full repo-wide mapping of:

- active production spine
- basic OpenCode governance files
- known pre-integration intentional assets
- known duplicate authority risks
- known generated artifact categories
- accepted recent packets

Use the architecture context spine instead.

## Context Window Rule

- 0 to 60 percent context: safe
- 60 to 75 percent context: start wrapping up
- 75 to 80 percent context: checkpoint and stop
- 80 percent or higher: no coding; relaunch with checkpoint

Never begin coding in a high-context audit session.

## Checkpoint Rule

Before stopping a large audit session, create or request approval to create a checkpoint under:

docs/opencode/reports/

A checkpoint should include:

- task name
- files inspected
- facts established
- unresolved unknowns
- files not inspected
- recommended next reads
- commands already run
- do-not-repeat guidance

## Coding Session Rule

Coding sessions should start fresh.

Before coding, read only:

- CURRENT_REBUILD_STATUS.md
- SESSION_CHANGELOG.md
- DO_NOT_REPEAT_AUDITS.md
- the active approved packet file
- relevant module registry / authority map sections

Do not carry a giant audit context into coding.

## Repo Truth Rule

Context spine gives direction.
Repo truth gives proof.

When a packet touches an authority file, verify current file contents before editing.

## Safety Rule

Never use context files to justify:

- live mode
- broad cleanup
- deleting intentional modules
- bypassing tests
- bypassing risk
- duplicate authority
- fake integration
- same-tree parallel coding