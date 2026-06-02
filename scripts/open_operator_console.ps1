param(
    [int]$Port = 8765,
    [string]$HostAddress = "127.0.0.1"
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$HiddenLauncher = Join-Path $PSScriptRoot "open_operator_console_hidden.ps1"

if (-not (Test-Path $HiddenLauncher)) {
    throw "Robust operator launcher not found at $HiddenLauncher"
}

Write-Host "Starting read-only operator API through guarded launcher on http://$HostAddress`:$Port"
Write-Host "This launcher does not start PAPER, live, real-money, or broker actions."

& $HiddenLauncher -Port $Port -HostAddress $HostAddress -OpenBrowser $true

Write-Host "Operator UI opened through the guarded launcher. PAPER runs must be started through governed /operator/intent/paper/start only."
