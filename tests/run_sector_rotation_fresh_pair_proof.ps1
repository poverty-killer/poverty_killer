# SECTOR_ROTATION_FRESH_OBSERVED_PAIR_PROOF_BUNDLE Paper Proof Script
# Run: powershell -ExecutionPolicy Bypass -File tests\run_sector_rotation_fresh_pair_proof.ps1
# Do not patch source files. Do not commit unless Board approves separately.
# Duration: 900 seconds.
# Board approval required before running.

$env:POVERTY_KILLER_PACKET = "SECTOR_ROTATION_FRESH_OBSERVED_PAIR_PROOF_BUNDLE"
$env:STRATEGIES = '{"sector_rotation_ranging_eligible": true}'
$env:PAPER_PROOF_WINDOW_OVERRIDE = "2"

$ts          = Get-Date -Format "yyyyMMdd_HHmmss"
$base        = "reports\paper_run_sr_fresh_pair_$ts"
$stdout_log  = "$base.stdout.log"
$stderr_log  = "$base.stderr.log"
$summary     = "$base.summary.txt"

Write-Host "Proof starting."
Write-Host "STRATEGIES=$($env:STRATEGIES)"
Write-Host "PAPER_PROOF_WINDOW_OVERRIDE=$($env:PAPER_PROOF_WINDOW_OVERRIDE)"
Write-Host "stdout_log : $stdout_log"
Write-Host "stderr_log : $stderr_log"

$proc = Start-Process -FilePath python `
    -ArgumentList @("main.py", "--paper", "--log-level", "INFO") `
    -RedirectStandardOutput $stdout_log `
    -RedirectStandardError  $stderr_log `
    -NoNewWindow -PassThru

Write-Host "PID=$($proc.Id). Waiting 900s..."

$exited = $proc.WaitForExit(900000)
if (-not $exited) {
    $proc.Kill()
    Write-Host "Process killed after 900s timeout."
} else {
    Write-Host "Process exited early. ExitCode=$($proc.ExitCode)."
}

# --- Combine both log files for scanning ---
$all_text = ""
if (Test-Path $stdout_log) { $all_text += (Get-Content $stdout_log -Raw) }
if (Test-Path $stderr_log)  { $all_text += (Get-Content $stderr_log  -Raw) }

if ($all_text.Length -eq 0) {
    Write-Host "WARNING: both log files are empty."
}

# --- Counter function ---
function Count-Match($text, $pat) {
    $opts = [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
    return ([regex]::Matches($text, $pat, $opts)).Count
}

# --- Counters ---
$broker_paper      = Count-Match $all_text "Broker Mode: paper"
$live_leak         = Count-Match $all_text "broker_mode.*live|LIVE.*mode.*true"
$regime_ranging    = Count-Match $all_text "regime=ranging|Regime RANGING|regime.*ranging"
$sr_eligible       = Count-Match $all_text "sector_rotation_eligible=True|sr_ranging=True"
$sr_freshness_pass = Count-Match $all_text "PAPER_DISPATCH_SECTOR_ROTATION.*admitted"
$sr_freshness_fail = Count-Match $all_text "PAPER_DISPATCH_SECTOR_ROTATION.*freshness fail"
$sr_pair_missing   = Count-Match $all_text "PAPER_DISPATCH_SECTOR_ROTATION.*observed pair missing"
$sr_dispatch       = Count-Match $all_text "PAPER_DISPATCH_SECTOR_ROTATION|dispatch.*sector_rotation|sector_rotation.*dispatch"
$signal_submitted  = Count-Match $all_text "SIGNAL_SUBMITTED|submit_signal"
$pb_reach          = Count-Match $all_text "PaperBroker|paper.*broker|paper.*order"
$paper_fill        = Count-Match $all_text "PAPER_FILL|paper.*fill"
$tracebacks        = Count-Match $all_text "Traceback"
$typeerrors        = Count-Match $all_text "TypeError"
$decimal_errs      = Count-Match $all_text "Decimal.*float|float.*Decimal"
$atomic_fail       = Count-Match $all_text "ATOMIC_WRITE_FAILED"

$errors = $tracebacks + $typeerrors + $decimal_errs + $live_leak + $atomic_fail

# --- Verdict ---
if ($sr_freshness_pass -ge 1 -and $signal_submitted -ge 1 -and $pb_reach -ge 1 -and $errors -eq 0) {
    $verdict = "PASS"
} elseif ($sr_freshness_pass -ge 1 -and $signal_submitted -ge 1 -and $pb_reach -eq 0 -and $errors -eq 0) {
    $verdict = "PARTIAL PASS - freshness admitted, signal submitted, PaperBroker not reached"
} elseif ($sr_freshness_pass -ge 1 -and $signal_submitted -eq 0 -and $errors -eq 0) {
    $verdict = "PARTIAL PASS - freshness gate cleared, submission blocked (downstream gate)"
} elseif ($sr_freshness_pass -eq 0 -and $errors -eq 0) {
    $verdict = "FAIL - SR_FRESHNESS_PASS=0: fresh observed pair never admitted in 900s"
} elseif ($errors -gt 0) {
    $verdict = "FAIL - errors detected"
} else {
    $verdict = "FAIL - dispatch or submission criteria not met"
}

# --- Summary lines ---
$lines = @(
    "SECTOR_ROTATION_FRESH_OBSERVED_PAIR PAPER PROOF SUMMARY",
    "Timestamp : $ts",
    "stdout    : $stdout_log",
    "stderr    : $stderr_log",
    "",
    "ENV",
    "PAPER_PROOF_WINDOW_OVERRIDE      : 2",
    "STRATEGIES                       : {sector_rotation_ranging_eligible: true}",
    "",
    "COUNTERS",
    "BROKER_MODE_PAPER         : $broker_paper",
    "LIVE_MODE_LEAK            : $live_leak",
    "REGIME_RANGING_SEEN       : $regime_ranging",
    "SR_ELIGIBLE_TRUE          : $sr_eligible",
    "SR_FRESHNESS_PASS         : $sr_freshness_pass",
    "SR_FRESHNESS_FAIL         : $sr_freshness_fail",
    "SR_PAIR_MISSING           : $sr_pair_missing",
    "SR_DISPATCH_EVIDENCE      : $sr_dispatch",
    "SIGNAL_SUBMITTED          : $signal_submitted",
    "PAPERBROKER_REACH_COUNT   : $pb_reach",
    "PAPER_FILL_COUNT          : $paper_fill",
    "TRACEBACK_COUNT           : $tracebacks",
    "TYPEERROR_COUNT           : $typeerrors",
    "DECIMAL_FLOAT_ERROR_COUNT : $decimal_errs",
    "ATOMIC_WRITE_FAILED       : $atomic_fail",
    "",
    "VERDICT: $verdict"
)

$lines | ForEach-Object { Write-Host $_ }
$lines | Out-File -FilePath $summary -Encoding utf8

Write-Host "Summary written: $summary"
