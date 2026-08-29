[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Image,
    [Parameter(Mandatory = $true)]
    [string]$Version
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false

if ($Image -cnotmatch '^ghcr\.io/[a-z0-9][a-z0-9._-]{0,127}/[a-z0-9][a-z0-9._-]{0,127}$') {
    throw 'Image must be ghcr.io/owner/repository in lowercase.'
}
if ($Version -ne 'dev' -and $Version -cnotmatch '^v[0-9]+\.[0-9]+(?:\.[0-9]+)?$') {
    throw 'Version must be dev, vX.Y, or vX.Y.Z.'
}

$repositoryRoot = (git rev-parse --show-toplevel).Trim()
if ($LASTEXITCODE -ne 0 -or -not $repositoryRoot) { throw 'Not inside a Git repository.' }
$repositoryRoot = (Resolve-Path -LiteralPath $repositoryRoot).Path
Set-Location $repositoryRoot

git diff --quiet --ignore-submodules=none
if ($LASTEXITCODE -ne 0) { throw 'Working tree is not clean.' }
git diff --cached --quiet --ignore-submodules=none
if ($LASTEXITCODE -ne 0) { throw 'Git index is not clean.' }

& .\tests\run-public-audit.ps1
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python .\scripts\verify-local-gate-receipts.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$revision = (git rev-parse HEAD).Trim()
$shortRevision = (git rev-parse --short=12 HEAD).Trim()
$buildRoot = [IO.Path]::GetFullPath((Join-Path $repositoryRoot 'build'))
$cacheRoot = [IO.Path]::GetFullPath((Join-Path $buildRoot 'release-cache'))
$nextCache = [IO.Path]::GetFullPath((Join-Path $buildRoot 'release-cache-next'))
if ((Split-Path -Parent $cacheRoot) -ne $buildRoot -or
    (Split-Path -Parent $nextCache) -ne $buildRoot) {
    throw 'Refusing unexpected BuildKit cache paths.'
}
if (Test-Path -LiteralPath $nextCache) {
    Remove-Item -LiteralPath $nextCache -Recurse -Force
}

$tags = @('--tag', "${Image}:${Version}", '--tag', "${Image}:sha-${shortRevision}")
if ($Version -eq 'dev') {
    $tags += @('--tag', "${Image}:dev")
    $buildVersion = "2.2.0-dev.${shortRevision}"
    $buildMilestone = 'v2-M6-dev'
}
else {
    $tags += @('--tag', "${Image}:latest")
    $buildVersion = $Version.Substring(1)
    $buildMilestone = if ($Version -match '^v2\.2(?:\.|$)') { 'v2-M6' }
        elseif ($Version -match '^v2\.1(?:\.|$)') { 'v2-M5' }
        else { 'v2-M3' }
}

$cacheArguments = @()
if (Test-Path -LiteralPath $cacheRoot) {
    $cacheArguments += @('--cache-from', "type=local,src=${cacheRoot}")
}
$cacheArguments += @('--cache-to', "type=local,dest=${nextCache},mode=max")

docker buildx build --platform linux/amd64 --file docker/Dockerfile `
    --build-arg "WEBOBS_BUILD_VERSION=${buildVersion}" `
    --build-arg "WEBOBS_BUILD_MILESTONE=${buildMilestone}" `
    --label "org.opencontainers.image.revision=${revision}" `
    --label "org.opencontainers.image.version=${Version}" `
    @cacheArguments --provenance=mode=max --sbom=true @tags --push .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (Test-Path -LiteralPath $cacheRoot) {
    Remove-Item -LiteralPath $cacheRoot -Recurse -Force
}
Move-Item -LiteralPath $nextCache -Destination $cacheRoot
docker buildx imagetools inspect "${Image}:sha-${shortRevision}" | Out-Null
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Output "Published ${Image}:${Version} and ${Image}:sha-${shortRevision}."
