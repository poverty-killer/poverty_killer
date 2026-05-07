# PAPER_FILL_COMPLETION_PROOF_BUNDLE Paper Proof Script
# Run: powershell -ExecutionPolicy Bypass -File tests\run_paper_fill_completion_proof.ps1
# Do not patch source files. Do not commit unless Board approves separately.
# Duration: 120 seconds controlled window.
# Board approval required before running.

$env:POVERTY_KILLER_PACKET        = "PAPER_FILL_COMPLETION_PROOF_BUNDLE"
$env:STRATEGIES                   = '{"sector_rotation_ranging_eligible": true}'
$env:PAPER_PROOF_WINDOW_OVERRIDE  = "2"

$ts         = Get-Date -Format "yyyyMMdd_HHmmss"
$base       = "reports\paper_run_fill_proof_$ts"
$stdout_log = "$base.stdout.log"
$stderr_log = "$base.stderr.log"
$summary    = "$base.summary.txt"

Write-Host "PAPER_FILL_COMPLETION_PROOF_BUNDLE proof starting."
Write-Host "POVERTY_KILLER_PACKET=$($env:POVERTY_KILLER_PACKET)"
Write-Host "STRATEGIES=$($env:STRATEGIES)"
Write-Host "PAPER_PROOF_WINDOW_OVERRIDE=$($env:PAPER_PROOF_WINDOW_OVERRIDE)"
Write-Host "stdout_log : $stdout_log"
Write-Host "stderr_log : $stderr_log"
Write-Host "Duration   : 120 seconds"

$proc = Start-Process -FilePath python `
    -ArgumentList @("main.py", "--paper", "--log-level", "INFO") `
    -RedirectStandardOutput $stdout_log `
    -RedirectStandardError  $stderr_log `
    -NoNewWindow -PassThru

Write-Host "PID=$($proc.Id). Waiting 120s..."

$exited = $proc.WaitForExit(120000)
if (-not $exited) {
    $proc.Kill()
    Write-Host "Process killed after 120s timeout."
} else {
    Write-Host "Process exited early. ExitCode=$($proc.ExitCode)."
}

# ---------------------------------------------------------------------------
# Load combined log text
# ---------------------------------------------------------------------------
$all_text = ""
if (Test-Path $stdout_log) { $all_text += (Get-Content $stdout_log -Raw) }
if (Test-Path $stderr_log)  { $all_text += (Get-Content $stderr_log  -Raw) }

if ($all_text.Length -eq 0) {
    Write-Host "WARNING: both log files are empty - bot may have failed to start."
}

# ---------------------------------------------------------------------------
# Counter helpers
# ---------------------------------------------------------------------------

# Count occurrences of an exact literal string (case-sensitive)
function Count-Exact {
    param($text, $literal)
    $escaped = [regex]::Escape($literal)
    return ([regex]::Matches($text, $escaped)).Count
}

# Count occurrences of a regex pattern (case-insensitive)
function Count-Pattern {
    param($text, $pat)
    $opts = [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
    return ([regex]::Matches($text, $pat, $opts)).Count
}

# Extract the last integer value following an exact diagnostic prefix.
# Returns 0 if the marker never appears.
function Last-DiagValue {
    param($text, $prefix)
    $escaped = [regex]::Escape($prefix)
    $matches = [regex]::Matches($text, "$escaped\s*(\d+)")
    if ($matches.Count -eq 0) { return 0 }
    return [int]($matches[$matches.Count - 1].Groups[1].Value)
}

# ---------------------------------------------------------------------------
# Counter extraction — exact diagnostic markers only
# ---------------------------------------------------------------------------

# BROKER_MODE_PAPER: exact log phrase written by main loop / engine init
$broker_paper    = Count-Exact  $all_text "Broker Mode: paper"

# LIVE_MODE_LEAK: any reference to live credentials or live mode flag active
$live_leak       = Count-Pattern $all_text "broker_mode.*live|LIVE_MODE.*true|live_mode.*active"

# SIGNAL_SUBMITTED: exact engine diagnostic
$signal_sub      = Count-Exact  $all_text "[EXEC_DIAG] SIGNAL_SUBMITTED:"

# PAPERBROKER_REACH_COUNT: parse last cumulative value from exact marker
$pb_reach        = Last-DiagValue $all_text "[EXEC_DIAG] PAPERBROKER_REACH_COUNT:"

# PAPER_FILL_COUNT: parse last cumulative value from exact marker
$paper_fill      = Last-DiagValue $all_text "[EXEC_DIAG] PAPER_FILL_COUNT:"

# ORDER_REJECT_COUNT: exact engine diagnostic or order submission failure
$order_reject    = Count-Exact  $all_text "[EXEC_DIAG] ORDER_REJECT:"
if ($order_reject -eq 0) {
    $order_reject = Count-Pattern $all_text "Order submission failed|INSUFFICIENT_INVENTORY"
}

# Error counters
$tracebacks      = Count-Exact  $all_text "Traceback"
$typeerrors      = Count-Exact  $all_text "TypeError"
$decimal_errs    = Count-Pattern $all_text "DECIMAL_CONVERSION_ERROR|InvalidOperation.*decimal"
$atomic_fail     = Count-Exact  $all_text "ATOMIC_WRITE_FAILED"

$total_errors = $tracebacks + $typeerrors + $decimal_errs + $live_leak + $atomic_fail

# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

if ($broker_paper -ge 1 -and $pb_reach -ge 1 -and $paper_fill -ge 1 -and $total_errors -eq 0) {
    $verdict = "PASS"
} elseif ($pb_reach -ge 1 -and $paper_fill -eq 0 -and $total_errors -eq 0) {
    $verdict = "PARTIAL PASS - PaperBroker reached, PAPER_FILL_COUNT=0, no errors detected"
} elseif ($signal_sub -ge 1 -and $pb_reach -eq 0 -and $total_errors -eq 0) {
    $verdict = "PARTIAL PASS - SIGNAL_SUBMITTED, PaperBroker not reached, no errors"
} elseif ($total_errors -gt 0) {
    $verdict = "FAIL - errors detected (TRACEBACK=$tracebacks TYPEERROR=$typeerrors DECIMAL=$decimal_errs LIVE_LEAK=$live_leak ATOMIC=$atomic_fail)"
} else {
    $verdict = "FAIL - PaperBroker not reached and no signal or other criteria not met"
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

$lines = @(
    "PAPER_FILL_COMPLETION_PROOF_BUNDLE PAPER PROOF SUMMARY",
    "Timestamp  : $ts",
    "stdout_log : $stdout_log",
    "stderr_log : $stderr_log",
    "",
    "ENV",
    "POVERTY_KILLER_PACKET        : PAPER_FILL_COMPLETION_PROOF_BUNDLE",
    "PAPER_PROOF_WINDOW_OVERRIDE  : 2",
    "STRATEGIES                   : {sector_rotation_ranging_eligible: true}",
    "",
    "COUNTERS",
    "BROKER_MODE_PAPER         : $broker_paper",
    "LIVE_MODE_LEAK            : $live_leak",
    "SIGNAL_SUBMITTED          : $signal_sub",
    "PAPERBROKER_REACH_COUNT   : $pb_reach",
    "PAPER_FILL_COUNT          : $paper_fill",
    "ORDER_REJECT_COUNT        : $order_reject",
    "TRACEBACK_COUNT           : $tracebacks",
    "TYPEERROR_COUNT           : $typeerrors",
    "DECIMAL_FLOAT_ERROR_COUNT : $decimal_errs",
    "ATOMIC_WRITE_FAILED       : $atomic_fail",
    "",
    "PASS CRITERIA",
    "  PAPERBROKER_REACH_COUNT >= 1 : $($pb_reach -ge 1)",
    "  PAPER_FILL_COUNT >= 1        : $($paper_fill -ge 1)",
    "  TRACEBACK_COUNT = 0          : $($tracebacks -eq 0)",
    "  TYPEERROR_COUNT = 0          : $($typeerrors -eq 0)",
    "  DECIMAL_FLOAT_ERROR_COUNT =0 : $($decimal_errs -eq 0)",
    "  LIVE_MODE_LEAK = 0           : $($live_leak -eq 0)",
    "  ATOMIC_WRITE_FAILED = 0      : $($atomic_fail -eq 0)",
    "  BROKER_MODE_PAPER >= 1       : $($broker_paper -ge 1)",
    "",
    "VERDICT: $verdict"
)

$lines | ForEach-Object { Write-Host $_ }
$lines | Out-File -FilePath $summary -Encoding utf8

Write-Host ""
Write-Host "Summary written: $summary"
