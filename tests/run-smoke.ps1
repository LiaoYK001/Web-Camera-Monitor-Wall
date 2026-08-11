param(
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false

$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ComposeFile = Join-Path $PSScriptRoot 'compose.smoke.yaml'
$ArtifactDirectory = Join-Path $PSScriptRoot 'artifacts'
$Artifact = Join-Path $ArtifactDirectory 'smoke.mp4'

& (Join-Path $PSScriptRoot 'run-public-audit.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Public-repository audit failed' }

New-Item -ItemType Directory -Force -Path $ArtifactDirectory | Out-Null
if (Test-Path -LiteralPath $Artifact) {
    Remove-Item -LiteralPath $Artifact -Force
}
Get-ChildItem -LiteralPath $ArtifactDirectory -Filter '.smoke.mp4.webobsd-*.mkv' -File -ErrorAction SilentlyContinue |
    Remove-Item -Force

Push-Location $RepositoryRoot
try {
    docker compose -f $ComposeFile down --volumes --remove-orphans
    $buildOption = if ($SkipBuild) { '--no-build' } else { '--build' }
    docker compose -f $ComposeFile up $buildOption --abort-on-container-exit --exit-code-from webobs webobs
    if ($LASTEXITCODE -ne 0) { throw 'M0 recording container failed' }
    docker compose -f $ComposeFile run --rm validator
    if ($LASTEXITCODE -ne 0) { throw 'M0 recording validation failed' }
    & (Join-Path $PSScriptRoot 'run-contracts.ps1') -ComposeFile $ComposeFile -ArtifactDirectory $ArtifactDirectory
    if ($LASTEXITCODE -ne 0) { throw 'M0 contract tests failed' }
}
finally {
    docker compose -f $ComposeFile down --volumes --remove-orphans
    Pop-Location
}
