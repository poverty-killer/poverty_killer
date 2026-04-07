$rebootFile = Join-Path $PSScriptRoot "PK_REBOOT_STATE.md"

if (-not (Test-Path $rebootFile)) {
    New-Item -Path $rebootFile -ItemType File -Force | Out-Null
}

Start-Process notepad.exe $rebootFile