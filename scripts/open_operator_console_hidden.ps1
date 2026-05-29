param(
    [int]$Port = 8765,
    [string]$HostAddress = "127.0.0.1",
    [bool]$OpenBrowser = $true
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Pythonw = Join-Path $RepoRoot "venv\Scripts\pythonw.exe"
$Python = Join-Path $RepoRoot "venv\Scripts\python.exe"
$UiPath = Join-Path $RepoRoot "ui\operator-control-panel\index.html"
$BaseUrl = "http://$HostAddress`:$Port"

if (-not (Test-Path $UiPath)) {
    throw "Operator UI not found at $UiPath"
}

$PythonLauncher = $Pythonw
if (-not (Test-Path $PythonLauncher)) {
    $PythonLauncher = $Python
}
if (-not (Test-Path $PythonLauncher)) {
    throw "Python venv not found at $Python"
}

function Test-OperatorApi {
    try {
        $response = Invoke-WebRequest -Uri "$BaseUrl/operator/health" -UseBasicParsing -TimeoutSec 2
        return [int]$response.StatusCode -ge 200 -and [int]$response.StatusCode -lt 500
    } catch {
        return $false
    }
}

$env:PK_OPERATOR_API_BASE = $BaseUrl

if (-not (Test-OperatorApi)) {
    Start-Process -FilePath $PythonLauncher -ArgumentList @(
        "-m", "uvicorn",
        "app.api.operator_readonly_api:create_operator_app",
        "--factory",
        "--host", $HostAddress,
        "--port", "$Port"
    ) -WorkingDirectory $RepoRoot -WindowStyle Hidden | Out-Null

    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Milliseconds 500
        if (Test-OperatorApi) {
            break
        }
    }
}

if ($OpenBrowser) {
    Start-Process "$BaseUrl/operator-ui/?v=desktop-launcher" | Out-Null
}
