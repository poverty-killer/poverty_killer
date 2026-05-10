# APPROVED EDIT TEMPLATE

APPROVED EDIT - <packet name>

Approved files:
- <file 1>
- <file 2>

Forbidden files:
- everything else

Goal:
<one sentence>

Required changes:
1. <specific change>
2. <specific change>

Do not:
- stage
- commit
- push
- run broad tests
- edit unrelated files
- refactor
- clean formatting outside touched lines
- change thresholds
- touch live mode
- touch risk/execution/SignalFusion/StrategyRouter/MainLoop unless listed above

Verification:
- <compile command>
- <targeted pytest command>
- git diff --check -- <approved files>

Stop if:
- another file is required
- tests fail after scoped change
- contract change is needed
- repo state is unexpected

After editing:
- show concise diff summary only
- do not stage
