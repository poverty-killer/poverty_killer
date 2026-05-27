param(
    [int]$Port = 8765,
    [string]$HostAddress = "127.0.0.1"
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $RepoRoot "venv\Scripts\python.exe"
$UiPath = Join-Path $RepoRoot "ui\operator-control-panel\index.html"

if (-not (Test-Path $Python)) {
    throw "Python venv not found at $Python"
}

if (-not (Test-Path $UiPath)) {
    throw "Operator UI not found at $UiPath"
}

$env:PK_OPERATOR_API_BASE = "http://$HostAddress`:$Port"

Write-Host "Starting read-only operator API on http://$HostAddress`:$Port"
Write-Host "This launcher does not start PAPER, live, real-money, or broker actions."

Start-Process -FilePath $Python -ArgumentList @(
    "-m", "uvicorn",
    "app.api.operator_readonly_api:create_operator_app",
    "--factory",
    "--host", $HostAddress,
    "--port", "$Port"
) -WorkingDirectory $RepoRoot

Start-Sleep -Seconds 2
Start-Process "http://$HostAddress`:$Port/operator-ui/"

Write-Host "Operator UI opened. PAPER runs must be started through governed /operator/intent/paper/start only."
