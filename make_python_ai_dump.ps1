# TARGETED AI-FRIENDLY PYTHON CODE DUMP
# Run from POVERTY_KILLER repo root

$repoRoot = (Get-Location).Path
$outDir = Join-Path $repoRoot "python_ai_dump"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

function Normalize-RelPath {
    param([string]$fullPath, [string]$rootPath)
    $rel = $fullPath.Substring($rootPath.Length).TrimStart('\','/')
    return ($rel -replace '\\','/')
}

$allPyFiles = Get-ChildItem -Path $repoRoot -Recurse -File -Filter *.py | Where-Object {
    $full = $_.FullName
    $rel  = Normalize-RelPath $full $repoRoot

    if ($full -match '\\(\.git|\.venv|venv|__pycache__|node_modules|dist|build|logs|reports|data|state|test_checkpoints)\\') {
        return $false
    }

    if ($rel -match '^app/.+\.py$')   { return $true }
    if ($rel -match '^tests/.+\.py$') { return $true }
    if ($rel -match '^[^/]+\.py$')    { return $true }

    return $false
} | Sort-Object FullName

if (-not $allPyFiles -or $allPyFiles.Count -eq 0) {
    Write-Host "No matching Python files found."
    return
}

$fileInfo = New-Object System.Collections.Generic.List[object]

foreach ($f in $allPyFiles) {
    $rel = Normalize-RelPath $f.FullName $repoRoot

    try {
        $content = Get-Content -Path $f.FullName -Raw -ErrorAction Stop
    }
    catch {
        $content = "[ERROR READING FILE] $($_.Exception.Message)"
    }

    $charCount = if ($null -ne $content) { $content.Length } else { 0 }

    $fileInfo.Add([PSCustomObject]@{
        FullName     = $f.FullName
        RelativePath = $rel
        Content      = $content
        CharCount    = $charCount
    })
}

$partCount = 4
$parts = @()

for ($i = 1; $i -le $partCount; $i++) {
    $parts += [PSCustomObject]@{
        Index      = $i
        TotalChars = 0
        Files      = New-Object System.Collections.Generic.List[object]
    }
}

foreach ($item in ($fileInfo | Sort-Object CharCount -Descending)) {
    $target = $parts | Sort-Object TotalChars, Index | Select-Object -First 1
    $target.Files.Add($item)
    $target.TotalChars += $item.CharCount
}

foreach ($part in $parts) {
    $sorted = $part.Files | Sort-Object RelativePath
    $part.Files.Clear()
    foreach ($s in $sorted) {
        $part.Files.Add($s)
    }
}

$manifestPath = Join-Path $outDir "00_manifest.txt"
$manifest = New-Object System.Text.StringBuilder

[void]$manifest.AppendLine("POVERTY_KILLER TARGETED PYTHON AI DUMP")
[void]$manifest.AppendLine("Repo Root: $repoRoot")
[void]$manifest.AppendLine("Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
[void]$manifest.AppendLine("Scope: app/**/*.py, tests/**/*.py, root-level *.py")
[void]$manifest.AppendLine("Total Files: $($fileInfo.Count)")
[void]$manifest.AppendLine("")

[void]$manifest.AppendLine("FULL FILE INDEX")
[void]$manifest.AppendLine(("=" * 100))
foreach ($f in ($fileInfo | Sort-Object RelativePath)) {
    [void]$manifest.AppendLine(("{0}  [{1} chars]" -f $f.RelativePath, $f.CharCount))
}
[void]$manifest.AppendLine("")

foreach ($part in ($parts | Sort-Object Index)) {
    [void]$manifest.AppendLine(("=" * 100))
    [void]$manifest.AppendLine("PART $($part.Index)")
    [void]$manifest.AppendLine("Approx Characters: $($part.TotalChars)")
    [void]$manifest.AppendLine("Files: $($part.Files.Count)")
    [void]$manifest.AppendLine(("=" * 100))
    foreach ($f in $part.Files) {
        [void]$manifest.AppendLine(("{0}  [{1} chars]" -f $f.RelativePath, $f.CharCount))
    }
    [void]$manifest.AppendLine("")
}

$manifest.ToString() | Set-Content -Path $manifestPath -Encoding UTF8

foreach ($part in ($parts | Sort-Object Index)) {
    $outFile = Join-Path $outDir ("code_dump_part_{0}.txt" -f $part.Index)
    $sb = New-Object System.Text.StringBuilder

    [void]$sb.AppendLine("POVERTY_KILLER TARGETED PYTHON AI DUMP")
    [void]$sb.AppendLine("PART: $($part.Index)")
    [void]$sb.AppendLine("TOTAL FILES IN PART: $($part.Files.Count)")
    [void]$sb.AppendLine("APPROX TOTAL CHARS: $($part.TotalChars)")
    [void]$sb.AppendLine("")

    [void]$sb.AppendLine("FILES IN THIS PART:")
    foreach ($f in $part.Files) {
        [void]$sb.AppendLine("- $($f.RelativePath)")
    }
    [void]$sb.AppendLine("")

    foreach ($f in $part.Files) {
        [void]$sb.AppendLine(("=" * 120))
        [void]$sb.AppendLine("FILE_START: $($f.RelativePath)")
        [void]$sb.AppendLine("LANGUAGE: python")
        [void]$sb.AppendLine("CHAR_COUNT: $($f.CharCount)")
        [void]$sb.AppendLine(("=" * 120))
        [void]$sb.AppendLine("```python")
        [void]$sb.AppendLine($f.Content)
        [void]$sb.AppendLine("```")
        [void]$sb.AppendLine("FILE_END: $($f.RelativePath)")
        [void]$sb.AppendLine("")
        [void]$sb.AppendLine("")
    }

    $sb.ToString() | Set-Content -Path $outFile -Encoding UTF8
    Write-Host "Wrote $outFile"
}

Write-Host ""
Write-Host "Done."
Write-Host "Manifest: $manifestPath"
Write-Host "Parts folder: $outDir"
