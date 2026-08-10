$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false

$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ComposeFile = Join-Path $PSScriptRoot 'compose.smoke.yaml'
$ArtifactDirectory = Join-Path $PSScriptRoot 'artifacts'
$Artifact = Join-Path $ArtifactDirectory 'smoke.mp4'

New-Item -ItemType Directory -Force -Path $ArtifactDirectory | Out-Null
if (Test-Path -LiteralPath $Artifact) {
    Remove-Item -LiteralPath $Artifact -Force
}

Push-Location $RepositoryRoot
try {
    docker compose -f $ComposeFile down --volumes --remove-orphans
    docker compose -f $ComposeFile up --build --abort-on-container-exit --exit-code-from webobs webobs
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
