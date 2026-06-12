param(
    [string]$BaseUrl = "http://127.0.0.1:8765",
    [int]$Iterations = 50,
    [int]$TimeoutSeconds = 3,
    [string]$OutputRoot = "reports/operator_perf"
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Net.Http
[System.Net.ServicePointManager]::DefaultConnectionLimit = 256

function New-OperatorHttpClient {
    $handler = [System.Net.Http.HttpClientHandler]::new()
    $handler.MaxConnectionsPerServer = 256
    $client = [System.Net.Http.HttpClient]::new($handler, $true)
    $client.Timeout = [TimeSpan]::FromSeconds($TimeoutSeconds)
    return $client
}

$script:OperatorHttpClient = New-OperatorHttpClient

function New-LatencyOutputDir {
    $stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMdd_HHmmss")
    $dir = Join-Path $OutputRoot $stamp
    New-Item -Path $dir -ItemType Directory -Force | Out-Null
    return $dir
}

function Invoke-TimedOperatorRequest {
    param(
        [string]$Path,
        [int]$TimeoutSec = 3
    )
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    $statusCode = 0
    $errorClass = $null
    try {
        $response = $script:OperatorHttpClient.GetAsync("$BaseUrl$Path").GetAwaiter().GetResult()
        $statusCode = [int]$response.StatusCode
        $response.Dispose()
    } catch {
        $errorClass = $_.Exception.GetType().Name
    } finally {
        $watch.Stop()
    }
    [pscustomobject]@{
        path = $Path
        status_code = $statusCode
        ok = ($statusCode -ge 200 -and $statusCode -lt 300)
        elapsed_ms = [math]::Round($watch.Elapsed.TotalMilliseconds, 3)
        error_class = $errorClass
        timestamp_utc = (Get-Date).ToUniversalTime().ToString("o")
    }
}

function Invoke-SerialProbe {
    param(
        [string]$Path,
        [int]$Count
    )
    $results = @()
    for ($i = 0; $i -lt $Count; $i++) {
        $results += Invoke-TimedOperatorRequest -Path $Path
    }
    return $results
}

function Invoke-ConcurrentProbe {
    param(
        [string]$Name,
        [string[]]$Paths,
        [int]$BatchTimeoutSec = 15
    )
    $client = New-OperatorHttpClient
    $requests = @()
    foreach ($path in $Paths) {
        $watch = [System.Diagnostics.Stopwatch]::StartNew()
        $requests += [pscustomobject]@{
            path = $path
            watch = $watch
            task = $client.GetAsync("$BaseUrl$path")
        }
    }
    $deadline = (Get-Date).AddSeconds($BatchTimeoutSec)
    while ((Get-Date) -lt $deadline) {
        foreach ($request in $requests) {
            if ($request.task.IsCompleted -and $request.watch.IsRunning) {
                $request.watch.Stop()
            }
        }
        $pending = @($requests | Where-Object { -not $_.task.IsCompleted })
        if ($pending.Count -eq 0) { break }
        Start-Sleep -Milliseconds 25
    }
    $results = @()
    foreach ($request in $requests) {
        if ($request.watch.IsRunning) {
            $request.watch.Stop()
        }
        if ($request.task.IsCompleted) {
            $statusCode = 0
            $errorClass = $null
            try {
                $response = $request.task.GetAwaiter().GetResult()
                $statusCode = [int]$response.StatusCode
                $response.Dispose()
            } catch {
                $errorClass = $_.Exception.GetType().Name
            }
            $results += [pscustomobject]@{
                batch = $Name
                path = $request.path
                status_code = $statusCode
                ok = ($statusCode -ge 200 -and $statusCode -lt 300)
                elapsed_ms = [math]::Round($request.watch.Elapsed.TotalMilliseconds, 3)
                error_class = $errorClass
                timestamp_utc = (Get-Date).ToUniversalTime().ToString("o")
            }
        } else {
            $results += [pscustomobject]@{
                batch = $Name
                path = $request.path
                status_code = 0
                ok = $false
                elapsed_ms = $BatchTimeoutSec * 1000
                error_class = "CONCURRENT_BATCH_TIMEOUT"
                timestamp_utc = (Get-Date).ToUniversalTime().ToString("o")
            }
        }
    }
    $client.Dispose()
    return $results
}

function Measure-LatencySummary {
    param([object[]]$Rows)
    $groups = $Rows | Group-Object path
    $summaries = @()
    foreach ($group in $groups) {
        $values = @($group.Group | ForEach-Object { [double]$_.elapsed_ms } | Sort-Object)
        $count = $values.Count
        $failures = @($group.Group | Where-Object { -not $_.ok }).Count
        if ($count -eq 0) { continue }
        $p50Index = [math]::Min($count - 1, [int][math]::Floor(($count - 1) * 0.50))
        $p95Index = [math]::Min($count - 1, [int][math]::Floor(($count - 1) * 0.95))
        $summaries += [pscustomobject]@{
            path = $group.Name
            count = $count
            ok = $count - $failures
            failures = $failures
            p50_ms = [math]::Round($values[$p50Index], 3)
            p95_ms = [math]::Round($values[$p95Index], 3)
            max_ms = [math]::Round(($values | Measure-Object -Maximum).Maximum, 3)
        }
    }
    return $summaries
}

$outputDir = New-LatencyOutputDir
$criticalPaths = @(
    "/operator/health",
    "/operator/launcher-status",
    "/operator/paper-control-state",
    "/operator/status"
)
$dashboardPaths = @(
    "/operator/version",
    "/operator/runtime-minimal",
    "/operator/latest-run",
    "/operator/credentials/providers",
    "/operator/paper-baseline",
    "/operator/portfolio",
    "/operator/perf/recent"
)

$rows = @()
foreach ($path in $criticalPaths) {
    $rows += Invoke-SerialProbe -Path $path -Count $Iterations
}

$mixedPaths = @()
1..20 | ForEach-Object { $mixedPaths += "/operator/health" }
1..20 | ForEach-Object { $mixedPaths += "/operator/launcher-status" }
1..20 | ForEach-Object { $mixedPaths += "/operator/paper-control-state" }
for ($i = 0; $i -lt 20; $i++) {
    $mixedPaths += $dashboardPaths[$i % $dashboardPaths.Count]
}
$rows += Invoke-ConcurrentProbe -Name "mixed-control-dashboard" -Paths $mixedPaths

$summary = Measure-LatencySummary -Rows $rows
$report = [ordered]@{
    source = "operator_latency_diagnostic"
    base_url = $BaseUrl
    iterations = $Iterations
    generated_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    no_paper_start = $true
    no_broker_mutation = $true
    secrets_values_exposed = $false
    summary = $summary
    rows = $rows
}

$jsonPath = Join-Path $outputDir "operator_latency.json"
$mdPath = Join-Path $outputDir "operator_latency.md"
$report | ConvertTo-Json -Depth 6 | Set-Content -Path $jsonPath -Encoding UTF8

$markdown = @()
$markdown += "# Operator Latency Diagnostic"
$markdown += ""
$markdown += "- Base URL: $BaseUrl"
$markdown += "- Iterations: $Iterations"
$markdown += "- Generated UTC: $($report.generated_at_utc)"
$markdown += "- PAPER start: not requested"
$markdown += "- Broker mutation: not requested"
$markdown += ""
$markdown += "| Path | Count | OK | Failures | p50 ms | p95 ms | max ms |"
$markdown += "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"
foreach ($item in $summary) {
    $markdown += "| $($item.path) | $($item.count) | $($item.ok) | $($item.failures) | $($item.p50_ms) | $($item.p95_ms) | $($item.max_ms) |"
}
$markdown | Set-Content -Path $mdPath -Encoding UTF8

Write-Output "operator_latency_report_json=$jsonPath"
Write-Output "operator_latency_report_md=$mdPath"
$summary | Format-Table -AutoSize
$script:OperatorHttpClient.Dispose()
