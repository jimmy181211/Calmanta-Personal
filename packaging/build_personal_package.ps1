param(
    [string]$Version = "0.1.0"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$packagingRoot = $PSScriptRoot
$personalRoot = (Resolve-Path -LiteralPath (Join-Path $packagingRoot "..")).Path
$calmantaRoot = Split-Path -Parent $personalRoot
$coreRoot = Join-Path $calmantaRoot "Calmanta-Core"
$releaseRoot = Join-Path $calmantaRoot "releases"
$packageName = "Calmanta-Personal-Package-$Version"
$stagingRoot = Join-Path $releaseRoot $packageName
$zipPath = Join-Path $releaseRoot "$packageName.zip"

if (-not (Test-Path -LiteralPath (Join-Path $coreRoot "backend\inbox_rules.py"))) {
    throw "Calmanta-Core is missing or incomplete: $coreRoot"
}

New-Item -ItemType Directory -Force -Path $releaseRoot | Out-Null
if (Test-Path -LiteralPath $stagingRoot) {
    Remove-Item -LiteralPath $stagingRoot -Recurse -Force
}
if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}
New-Item -ItemType Directory -Force -Path $stagingRoot | Out-Null

$excludedDirectories = @(
    ".git",
    ".venv",
    "data",
    "staging",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "build",
    "dist"
)
$excludedFiles = @(
    "profile.local.json",
    "*.db",
    "*.sqlite",
    "*.sqlite3",
    "*.pyc",
    "*.pyo"
)

function Copy-PackageTree {
    param(
        [string]$Source,
        [string]$Destination
    )

    $arguments = @(
        $Source,
        $Destination,
        "/E",
        "/R:2",
        "/W:1",
        "/NFL",
        "/NDL",
        "/NJH",
        "/NJS",
        "/NP",
        "/XD"
    ) + $excludedDirectories + @("/XF") + $excludedFiles
    & robocopy @arguments | Out-Null
    if ($LASTEXITCODE -ge 8) {
        throw "Robocopy failed for $Source with exit code $LASTEXITCODE"
    }
}

Copy-PackageTree -Source $personalRoot -Destination (Join-Path $stagingRoot "Calmanta-Personal")
Copy-PackageTree -Source $coreRoot -Destination (Join-Path $stagingRoot "Calmanta-Core")
Copy-Item -LiteralPath (Join-Path $packagingRoot "START_HERE.md") -Destination $stagingRoot
Copy-Item -LiteralPath (Join-Path $packagingRoot "PACKAGE_MANIFEST.json") -Destination $stagingRoot

$forbidden = Get-ChildItem -LiteralPath $stagingRoot -Recurse -Force | Where-Object {
    $_.Name -in @(".git", ".venv", "data", "staging", "profile.local.json") -or
    $_.Extension -in @(".db", ".sqlite", ".sqlite3", ".pyc", ".pyo")
}
if ($forbidden) {
    throw "Private or generated files entered the package: $($forbidden.FullName -join ', ')"
}

Compress-Archive -Path (Join-Path $stagingRoot "*") -DestinationPath $zipPath -CompressionLevel Optimal
Write-Output $zipPath
