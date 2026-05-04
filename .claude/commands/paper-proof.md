# /paper-proof — Paper-Mode Acceptance Template

Slash-command template. Do not run the bot. Do not invent counters.

## Prerequisites the Board must confirm before invoking

- `BROKER_MODE=paper` (or equivalent paper flag) is set in the active run environment.
- No live API keys are loaded.
- A controlled paper-mode run has already completed and produced log output.

## Step 1 — Locate log/report output

Identify where the completed paper run wrote its output:

- Console stdout/stderr captured to a file, or
- `reports/` directory for any written report, or
- `state/session_journal.jsonl` (journaling events only — not bot order submissions).

Do not assume any file contains order data. Read what is actually present.

## Step 2 — Measure required counters

For each counter below, scan the available log/report output.

Classify each as:

- `MEASURED` — value found in output, exact number recorded
- `NOT_LOGGED` — output exists but counter not present in it
- `NOT_APPLICABLE` — counter is not relevant to this run configuration
- `ZERO_AND_CONCERNING` — counter found and equals zero when non-zero is expected

| Counter | Classification | Observed Value | Notes |
|---|---|---|---|
| REGIME_FALLBACK_COUNT | | | |
| PRICE_MOVED_REJECT_COUNT | | | |
| PRICE_MOVED_36_REJECT_COUNT | | | |
| ATOMIC_WRITE_FAILED | | | |
| ATOMIC_WRITE_TRANSIENT | | | |
| RESTORED_FROM_BACKUP | | | |
| TRACEBACK_COUNT | | | |
| EXECUTION_DECIMAL_ERROR_COUNT | | | |
| SHANS_SIGNAL_PRODUCED | | | |
| FUSION_REGIME_LINES | | | |
| SECTOR_ROTATION_ADMITTED | | | |
| SIGNAL_SUBMITTED | | | |
| SIGNAL_REJECTED | | | |
| PAPERBROKER_REACH_COUNT | | | |
| PAPER_FILL_COUNT | | | |

## Step 3 — Produce acceptance report

Fill in from observed evidence only. Do not assume.

```
PAPER_PROOF_REPORT

run_log_source:
broker_mode_confirmed: yes / no / unknown
live_keys_detected: yes / no / unknown

counter_summary:
  MEASURED: <count>
  NOT_LOGGED: <count>
  NOT_APPLICABLE: <count>
  ZERO_AND_CONCERNING: <count>

zero_and_concerning_list:
  <list each ZERO_AND_CONCERNING counter with note, or NONE>

not_logged_list:
  <list each NOT_LOGGED counter, or NONE>

verdict: PASS | PARTIAL | FAIL

verdict_basis:
  PASS   — TRACEBACK_COUNT=0, EXECUTION_DECIMAL_ERROR_COUNT=0,
            PAPERBROKER_REACH_COUNT >= 1, PAPER_FILL_COUNT >= 1,
            no ZERO_AND_CONCERNING on execution path counters.
  PARTIAL — some execution-path counters NOT_LOGGED or
             SHANS_SIGNAL_PRODUCED=0 (buffer not full).
  FAIL   — TRACEBACK_COUNT > 0, EXECUTION_DECIMAL_ERROR_COUNT > 0,
             live mode detected, or PAPERBROKER_REACH_COUNT=0 when
             SIGNAL_SUBMITTED > 0.

board_escalation_required: yes / no
escalation_detail:
```
