[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$CandidateImage,
    [string]$ComposeFiles = 'compose.yaml,compose.m6-backup.yaml',
    [string]$EnvFile = '.env',
    [string]$Service = 'webobs',
    [string]$Repository = 'LiaoYK001/Web-Camera-Monitor-Wall',
    [ValidateRange(10, 600)][int]$HealthTimeoutSeconds = 120,
    [switch]$AllowLocalImage
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

function Assert-Condition {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

function Invoke-Compose {
    param([string[]]$Arguments, [switch]$Capture)
    $Base = @('compose', '--project-directory', $RepositoryRoot, '--env-file', $ResolvedEnvFile)
    foreach ($File in $ResolvedComposeFiles) { $Base += @('-f', $File) }
    if ($Capture) { return @(docker @Base @Arguments) }
    docker @Base @Arguments
}

function Wait-ServiceHealthy {
    param([int]$TimeoutSeconds)
    $Deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $Deadline) {
        $Id = (@(Invoke-Compose -Arguments @('ps', '-q', $Service) -Capture) -join '').Trim()
        if (-not [string]::IsNullOrWhiteSpace($Id)) {
            $State = (@(docker inspect --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' $Id) -join '').Trim()
            if ($State -eq 'running healthy') { return $true }
            if ($State -match '^(exited|dead)') { return $false }
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

Push-Location $RepositoryRoot
$OriginalImageOverride = [Environment]::GetEnvironmentVariable('WEBOBS_IMAGE', 'Process')
try {
    $ResolvedEnvFile = (Resolve-Path -LiteralPath $EnvFile).Path
    $ResolvedComposeFiles = @()
    foreach ($File in $ComposeFiles.Split(',', [StringSplitOptions]::RemoveEmptyEntries)) {
        $ResolvedComposeFiles += (Resolve-Path -LiteralPath $File.Trim()).Path
    }
    Assert-Condition (@($ResolvedComposeFiles | Where-Object { [IO.Path]::GetFileName($_) -eq 'compose.m6-backup.yaml' }).Count -eq 1) `
        'Upgrade requires compose.m6-backup.yaml exactly once.'

    & (Join-Path $PSScriptRoot 'verify-image.ps1') -Image $CandidateImage `
        -Repository $Repository -AllowLocalImage:$AllowLocalImage

    $CurrentId = (@(Invoke-Compose -Arguments @('ps', '-q', $Service) -Capture) -join '').Trim()
    Assert-Condition (-not [string]::IsNullOrWhiteSpace($CurrentId)) 'The current product service is not running.'
    $PreviousImageId = (@(docker inspect --format '{{.Image}}' $CurrentId) -join '').Trim()
    Assert-Condition ($PreviousImageId -match '^sha256:[0-9a-f]{64}$') 'Unable to resolve the current immutable image ID.'

    $BackupName = 'pre-upgrade-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ') + '.tar.gz'
    [Environment]::SetEnvironmentVariable('WEBOBS_IMAGE', $PreviousImageId, 'Process')
    Invoke-Compose -Arguments @('stop', '-t', '20', $Service)
    Assert-Condition ($LASTEXITCODE -eq 0) 'Unable to stop the current product before backup.'
    Invoke-Compose -Arguments @('run', '--rm', '--no-deps', '--entrypoint',
        '/opt/webobs/bin/webobs-backup', $Service, 'create', $BackupName)
    Assert-Condition ($LASTEXITCODE -eq 0) 'Pre-upgrade validated backup failed; candidate was not started.'

    [Environment]::SetEnvironmentVariable('WEBOBS_IMAGE', $CandidateImage, 'Process')
    Invoke-Compose -Arguments @('up', '-d', '--no-build', '--force-recreate', $Service)
    $CandidateStarted = $LASTEXITCODE -eq 0
    if ($CandidateStarted -and (Wait-ServiceHealthy -TimeoutSeconds $HealthTimeoutSeconds)) {
        Write-Host "Upgrade succeeded. Rollback image ID: $PreviousImageId; backup: $BackupName"
        exit 0
    }

    Write-Warning 'Candidate did not become healthy; restoring the validated scene and previous image.'
    Invoke-Compose -Arguments @('stop', '-t', '20', $Service) | Out-Null
    [Environment]::SetEnvironmentVariable('WEBOBS_IMAGE', $PreviousImageId, 'Process')
    Invoke-Compose -Arguments @('run', '--rm', '--no-deps', '-e',
        'WEBOBS_RESTORE_CONFIRM=replace-scene', '--entrypoint',
        '/opt/webobs/bin/webobs-backup', $Service, 'restore', "/backups/$BackupName")
    Assert-Condition ($LASTEXITCODE -eq 0) 'Automatic rollback could not restore the pre-upgrade scene.'
    Invoke-Compose -Arguments @('up', '-d', '--no-build', '--force-recreate', $Service)
    Assert-Condition ($LASTEXITCODE -eq 0 -and (Wait-ServiceHealthy -TimeoutSeconds $HealthTimeoutSeconds)) `
        'Automatic rollback could not restore the previous healthy image.'
    throw "Candidate failed health validation and was rolled back successfully to $PreviousImageId."
} finally {
    [Environment]::SetEnvironmentVariable('WEBOBS_IMAGE', $OriginalImageOverride, 'Process')
    Pop-Location
}
