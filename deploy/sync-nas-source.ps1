param(
    [string]$SourceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$TargetRoot = "\\100.66.1.1\docker\yishu-canvas\yishu-canvas-fnos"
)

$ErrorActionPreference = "Stop"

$source = (Resolve-Path $SourceRoot).ProviderPath.TrimEnd("\")
if (-not (Test-Path -LiteralPath $TargetRoot)) {
    throw "NAS target does not exist: $TargetRoot"
}
$target = (Resolve-Path $TargetRoot).ProviderPath.TrimEnd("\")

if ($target -notmatch "(^|[\\\/])yishu-canvas-fnos$") {
    throw "Refusing to mirror into unexpected target: $target"
}

$runtimeDirs = @(
    "deploy\fnos\api-env",
    "deploy\fnos\data",
    "deploy\fnos\output",
    "deploy\fnos\team-assets",
    "data",
    "output",
    "assets"
)

$excludeDirs = @(
    ".git",
    "__pycache__",
    ".pytest_cache",
    "api-env",
    "data",
    "output",
    "team-assets",
    "assets"
)

$excludeFiles = @(
    ".env",
    ".env.*",
    "*.log",
    "*.pyc",
    "*.pyo",
    "DEPLOYED_COMMIT.txt"
)

Write-Host "Syncing source:"
Write-Host "  from: $source"
Write-Host "  to:   $target"
Write-Host "Protected runtime paths:"
$runtimeDirs | ForEach-Object { Write-Host "  $_" }

& robocopy $source $target /MIR /FFT /R:2 /W:2 /XD $excludeDirs /XF $excludeFiles
$code = $LASTEXITCODE
if ($code -gt 7) {
    throw "robocopy failed with exit code $code"
}

$commit = (git -C $source rev-parse --short HEAD).Trim()
Set-Content -LiteralPath (Join-Path $target "DEPLOYED_COMMIT.txt") -Value $commit -Encoding UTF8
Write-Host "NAS source sync complete at commit $commit"
