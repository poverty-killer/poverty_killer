param(
    [string]$OutFile = ".\CODE_DUMP.txt",
    [string[]]$Files
)

$root = Get-Location

"===== CODE DUMP START =====" | Set-Content -Encoding UTF8 $OutFile

foreach ($file in $Files) {
    if (Test-Path $file) {
        $full = (Resolve-Path $file).Path
        $relative = $full.Substring($root.Path.Length).TrimStart('\')

        Add-Content -Encoding UTF8 $OutFile ""
        Add-Content -Encoding UTF8 $OutFile ("=" * 100)
        Add-Content -Encoding UTF8 $OutFile ("FILE: " + $relative)
        Add-Content -Encoding UTF8 $OutFile ("=" * 100)
        Add-Content -Encoding UTF8 $OutFile ""

        Get-Content $file | Add-Content -Encoding UTF8 $OutFile
    } else {
        Add-Content -Encoding UTF8 $OutFile ""
        Add-Content -Encoding UTF8 $OutFile ("MISSING FILE: " + $file)
    }
}

Add-Content -Encoding UTF8 $OutFile ""
Add-Content -Encoding UTF8 $OutFile "===== CODE DUMP END ====="

Write-Output "Saved: $OutFile"
