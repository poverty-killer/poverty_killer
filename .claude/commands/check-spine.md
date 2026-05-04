# /check-spine - Live Spine Status

Reports wiring status of the live spine seams. Does not run the bot.

Required report:

SPINE_STATUS_REPORT
harness_file: tests/harness_live_spine.py
last_harness_result: PASS / FAIL / NOT_RUN
last_run_date: <date or UNKNOWN>

Seam classification (for each seam in harness):
- PASS: seam reached and returned expected result
- NOT_REACHED: upstream condition prevented activation (note cause)
- FAIL: seam raised exception or returned unexpected result
- NOT_CHECKED: harness does not cover this seam

Known NOT_REACHED cause:
Shans buffer requires 60 samples. If fewer fed, fusion vetoes, preferred=None,
SHADOW_FRONT branch not entered, downstream seams not reached.
This is buffer-insufficient, not a wiring fault.

Spine verdict:
- SPINE_LIVE: all seams PASS or NOT_REACHED with known non-fault cause
- SPINE_PARTIAL: some seams FAIL or NOT_CHECKED with unknown cause
- SPINE_BROKEN: any seam raised exception or contract mismatch

Board escalation required if: SPINE_BROKEN or unknown NOT_REACHED cause.
