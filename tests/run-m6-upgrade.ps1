[CmdletBinding()]
param([switch]$SkipBuild)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ComposeFiles = 'tests/compose.upgrade.yaml,compose.m6-backup.yaml'
$ComposeArgs = @('--project-directory', $RepositoryRoot, '--env-file', '.env.example',
    '-f', 'tests/compose.upgrade.yaml', '-f', 'compose.m6-backup.yaml')

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

function Wait-Healthy {
    $Deadline = [DateTime]::UtcNow.AddSeconds(60)
    while ([DateTime]::UtcNow -lt $Deadline) {
        $Id = (@(docker compose @ComposeArgs ps -q webobs) -join '').Trim()
        if (-not [string]::IsNullOrWhiteSpace($Id)) {
            $Health = (@(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' $Id) -join '').Trim()
            if ($Health -eq 'healthy') { return $Id }
        }
        Start-Sleep -Milliseconds 500
    }
    throw 'Upgrade fixture did not become healthy.'
}

& (Join-Path $PSScriptRoot 'run-public-audit.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Public repository audit failed.' }
Get-Command docker -ErrorAction Stop | Out-Null
Get-Command pwsh -ErrorAction Stop | Out-Null

$BackupDirectory = Join-Path $RepositoryRoot 'backups'
[IO.Directory]::CreateDirectory($BackupDirectory) | Out-Null
foreach ($Path in [IO.Directory]::EnumerateFiles($BackupDirectory, 'pre-upgrade-*')) {
    [IO.File]::Delete($Path)
}

Push-Location $RepositoryRoot
try {
    docker compose @ComposeArgs down --volumes --remove-orphans | Out-Null
    if (-not $SkipBuild) {
        docker build -f tests/upgrade-fixture/Dockerfile.good -t webobs-upgrade-good:local .
        Assert-True ($LASTEXITCODE -eq 0) 'Good upgrade fixture image failed to build.'
        docker build -f tests/upgrade-fixture/Dockerfile.bad -t webobs-upgrade-bad:local .
        Assert-True ($LASTEXITCODE -eq 0) 'Bad upgrade fixture image failed to build.'
    }

    & (Join-Path $RepositoryRoot 'scripts/verify-image.ps1') `
        -Image webobs-upgrade-good:local -AllowLocalImage
    Assert-True ($LASTEXITCODE -eq 0) 'Local image contract verification failed.'

    docker compose @ComposeArgs up -d mediamtx fixture webobs
    Assert-True ($LASTEXITCODE -eq 0) 'Initial upgrade fixture failed to start.'
    $InitialId = Wait-Healthy
    $InitialImageId = (@(docker inspect --format '{{.Image}}' $InitialId) -join '').Trim()
    $InitialSceneHash = (@(docker exec $InitialId sha256sum /config/webobs/scene.json) -join '').Split(' ')[0]

    $RollbackOutput = (@(pwsh -NoProfile -File scripts/upgrade-image.ps1 `
        -CandidateImage webobs-upgrade-bad:local `
        -ComposeFiles $ComposeFiles -EnvFile .env.example -Service webobs `
        -HealthTimeoutSeconds 15 -AllowLocalImage 2>&1) -join "`n")
    Assert-True ($LASTEXITCODE -ne 0 -and $RollbackOutput -match 'rolled back successfully') `
        'Unhealthy candidate did not report a successful automatic rollback.'
    $RolledBackId = Wait-Healthy
    $RolledBackImageId = (@(docker inspect --format '{{.Image}}' $RolledBackId) -join '').Trim()
    $RolledBackSceneHash = (@(docker exec $RolledBackId sha256sum /config/webobs/scene.json) -join '').Split(' ')[0]
    Assert-True ($RolledBackImageId -eq $InitialImageId -and $RolledBackSceneHash -eq $InitialSceneHash) `
        'Automatic rollback did not restore the exact image and scene state.'

    $UpgradeOutput = (@(pwsh -NoProfile -File scripts/upgrade-image.ps1 `
        -CandidateImage webobs-upgrade-good:local `
        -ComposeFiles $ComposeFiles -EnvFile .env.example -Service webobs `
        -HealthTimeoutSeconds 30 -AllowLocalImage 2>&1) -join "`n")
    Assert-True ($LASTEXITCODE -eq 0 -and $UpgradeOutput -match 'Upgrade succeeded') `
        'Healthy candidate did not complete the automated upgrade path.'
    [void](Wait-Healthy)

    $Archives = @([IO.Directory]::EnumerateFiles($BackupDirectory, 'pre-upgrade-*.tar.gz'))
    $Sidecars = @([IO.Directory]::EnumerateFiles($BackupDirectory, 'pre-upgrade-*.tar.gz.sha256'))
    Assert-True ($Archives.Count -ge 2 -and $Sidecars.Count -eq $Archives.Count) `
        'Upgrade attempts did not create validated backup archives and sidecars.'
    Write-Host 'M6 image contract, pre-upgrade backup, unhealthy-candidate rollback, scene restore, and healthy upgrade acceptance passed.'
} finally {
    docker compose @ComposeArgs down --volumes --remove-orphans | Out-Null
    Pop-Location
}
