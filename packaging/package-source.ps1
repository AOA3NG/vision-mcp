$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$version = [regex]::Match(
    (Get-Content -LiteralPath (Join-Path $projectRoot "pyproject.toml") -Raw -Encoding UTF8),
    '(?m)^version = "([^"]+)"'
).Groups[1].Value
if (-not $version) { throw "Unable to read project version" }

$stage = Join-Path $env:TEMP ("vision-mcp-source-" + [guid]::NewGuid().ToString("N"))
$target = Join-Path $stage ("vision-mcp-" + $version)
$resolvedTemp = [IO.Path]::GetFullPath($env:TEMP).TrimEnd('\') + '\'
$resolvedStage = [IO.Path]::GetFullPath($stage)
if (-not $resolvedStage.StartsWith($resolvedTemp, [StringComparison]::OrdinalIgnoreCase) -or
    -not ([IO.Path]::GetFileName($resolvedStage)).StartsWith("vision-mcp-source-")) {
    throw "Unsafe source staging path: $resolvedStage"
}
New-Item -ItemType Directory -Path $target -Force | Out-Null

$manifestPath = Join-Path $projectRoot "packaging\source-manifest.txt"
$manifest = Get-Content -LiteralPath $manifestPath -Encoding UTF8 |
    ForEach-Object { $_.Trim() } |
    Where-Object { $_ -and -not $_.StartsWith("#") }
if (-not $manifest -or $manifest.Count -ne ($manifest | Sort-Object -Unique).Count) {
    throw "Source manifest is empty or contains duplicate paths"
}
foreach ($relative in $manifest) {
    $normalized = $relative.Replace('/', '\')
    if ([IO.Path]::IsPathRooted($normalized) -or $normalized.Split('\') -contains '..') {
        throw "Unsafe source manifest path: $relative"
    }
    $source = Join-Path $projectRoot $normalized
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "Source manifest file is missing: $relative"
    }
    $destination = Join-Path $target $normalized
    New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
    Copy-Item -LiteralPath $source -Destination $destination
}

& python (Join-Path $target "scripts\release_check.py") --publication-root $target
if ($LASTEXITCODE -ne 0) { throw "Open-source release check failed" }

$outputDir = Join-Path $projectRoot "dist-installer"
New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
$zip = Join-Path $outputDir ("VisionMCP-OpenSource-" + $version + ".zip")
if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
Compress-Archive -LiteralPath $target -DestinationPath $zip -CompressionLevel Optimal
$hash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash
Set-Content -LiteralPath ($zip + ".sha256") -Value ("$hash  " + [IO.Path]::GetFileName($zip)) -Encoding ASCII
Remove-Item -LiteralPath $stage -Recurse -Force

Write-Host "Source archive: $zip"
Write-Host "SHA-256: $hash"
