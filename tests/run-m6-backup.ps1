param(
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ArtifactsRoot = Join-Path $PSScriptRoot 'artifacts'
$WorkRoot = Join-Path $ArtifactsRoot 'm6-backup'
if (-not $WorkRoot.StartsWith($ArtifactsRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Resolved backup test path escaped tests/artifacts.'
}
if (Test-Path -LiteralPath $WorkRoot) {
    Remove-Item -LiteralPath $WorkRoot -Recurse -Force
}
$ConfigRoot = Join-Path $WorkRoot 'config'
$BackupRoot = Join-Path $WorkRoot 'backups'
[void](New-Item -ItemType Directory -Path $ConfigRoot, $BackupRoot -Force)
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'scenes/m1-two-up.json') `
    -Destination (Join-Path $ConfigRoot 'scene.json')

& (Join-Path $PSScriptRoot 'run-public-audit.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Public repository audit failed.' }

if (-not $SkipBuild) {
    docker build -t webobs:m0 -f (Join-Path $RepositoryRoot 'docker/Dockerfile') $RepositoryRoot
    if ($LASTEXITCODE -ne 0) { throw 'M6 backup product image failed to build.' }
}

$MountConfig = "${ConfigRoot}:/config/webobs"
$MountBackups = "${BackupRoot}:/backups"
docker run --rm --entrypoint /opt/obs/bin/webobs-scene-tool `
    -v $MountConfig webobs:m0 validate /config/webobs/scene.json
if ($LASTEXITCODE -ne 0) { throw 'Scene migration before backup failed.' }
$ScenePath = Join-Path $ConfigRoot 'scene.json'
$StudioPath = Join-Path $ConfigRoot 'studio.json'
$CurrentScene = Get-Content -Raw -LiteralPath $ScenePath | ConvertFrom-Json -Depth 32
$Studio = [ordered]@{
    schemaVersion = 1; revision = 0; programSceneId = $CurrentScene.id; previewSceneId = $CurrentScene.id
    transition = [ordered]@{ kind = 'cut'; durationMs = 0 }; scenes = @($CurrentScene)
}
$Studio | ConvertTo-Json -Depth 32 | Set-Content -Encoding utf8NoBOM -LiteralPath $StudioPath
docker run --rm --entrypoint /opt/obs/bin/webobs-scene-tool `
    -v $MountConfig webobs:m0 validate-studio /config/webobs/studio.json
if ($LASTEXITCODE -ne 0) { throw 'Studio fixture validation before backup failed.' }
$OriginalHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $ScenePath).Hash
$OriginalStudioHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $StudioPath).Hash
$CreateOutput = @(docker run --rm --entrypoint /opt/webobs/bin/webobs-backup `
    -v $MountConfig -v $MountBackups webobs:m0 create m6-test.tar.gz 2>&1) -join "`n"
if ($LASTEXITCODE -ne 0) { throw "Backup creation failed:`n$CreateOutput" }
$Archive = Join-Path $BackupRoot 'm6-test.tar.gz'
$Checksum = "$Archive.sha256"
if (-not (Test-Path -LiteralPath $Archive) -or -not (Test-Path -LiteralPath $Checksum)) {
    throw 'Backup archive or checksum sidecar was not created.'
}
if ($CreateOutput -match 'rtsp://|password|token=') {
    throw 'Backup output leaked source or credential-like content.'
}

$Modes = @(docker run --rm --entrypoint stat -v $MountBackups webobs:m0 `
    -c '%a' /backups/m6-test.tar.gz /backups/m6-test.tar.gz.sha256)
if ($LASTEXITCODE -ne 0 -or @($Modes | Where-Object { $_.Trim() -ne '600' }).Count -ne 0) {
    throw 'Backup archive and checksum must use mode 0600.'
}
docker run --rm --entrypoint /opt/webobs/bin/webobs-backup `
    -v $MountConfig -v $MountBackups webobs:m0 verify /backups/m6-test.tar.gz
if ($LASTEXITCODE -ne 0) { throw 'Fresh backup verification failed.' }

$Changed = Get-Content -Raw -LiteralPath $ScenePath | ConvertFrom-Json
$Changed.name = 'M6 backup mutation fixture'
$Changed | ConvertTo-Json -Depth 12 | Set-Content -Encoding utf8NoBOM -LiteralPath $ScenePath
$ChangedHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $ScenePath).Hash
if ($ChangedHash -eq $OriginalHash) { throw 'Backup test scene mutation did not change the file.' }
$ChangedStudio = Get-Content -Raw -LiteralPath $StudioPath | ConvertFrom-Json -Depth 32
$ChangedStudio.scenes[0].name = 'M7 Studio backup mutation fixture'
$ChangedStudio | ConvertTo-Json -Depth 32 | Set-Content -Encoding utf8NoBOM -LiteralPath $StudioPath
$ChangedStudioHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $StudioPath).Hash
if ($ChangedStudioHash -eq $OriginalStudioHash) { throw 'Backup test Studio mutation did not change the file.' }

docker run --rm --entrypoint /opt/webobs/bin/webobs-backup `
    -v $MountConfig -v $MountBackups webobs:m0 restore /backups/m6-test.tar.gz 2>$null
if ($LASTEXITCODE -eq 0) { throw 'Restore succeeded without the explicit confirmation value.' }
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $ScenePath).Hash -ne $ChangedHash) {
    throw 'Rejected restore modified the scene file.'
}
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $StudioPath).Hash -ne $ChangedStudioHash) {
    throw 'Rejected restore modified the Studio file.'
}

$RestoreOutput = @(docker run --rm --entrypoint /opt/webobs/bin/webobs-backup `
    -e WEBOBS_RESTORE_CONFIRM=replace-scene -v $MountConfig -v $MountBackups `
    webobs:m0 restore /backups/m6-test.tar.gz 2>&1) -join "`n"
if ($LASTEXITCODE -ne 0) { throw "Confirmed restore failed:`n$RestoreOutput" }
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $ScenePath).Hash -ne $OriginalHash) {
    throw 'Confirmed restore did not reproduce the original scene.'
}
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $StudioPath).Hash -ne $OriginalStudioHash) {
    throw 'Confirmed restore did not reproduce the original Studio collection.'
}
if ($RestoreOutput -match 'rtsp://|password|token=') {
    throw 'Restore output leaked source or credential-like content.'
}

$CorruptArchive = Join-Path $BackupRoot 'm6-corrupt.tar.gz'
$CorruptChecksum = "$CorruptArchive.sha256"
Copy-Item -LiteralPath $Archive -Destination $CorruptArchive
$Bytes = [IO.File]::ReadAllBytes($CorruptArchive)
$Bytes[[Math]::Floor($Bytes.Length / 2)] = $Bytes[[Math]::Floor($Bytes.Length / 2)] -bxor 0xff
[IO.File]::WriteAllBytes($CorruptArchive, $Bytes)
$Hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Archive).Hash.ToLowerInvariant()
Set-Content -Encoding ascii -LiteralPath $CorruptChecksum -Value "$Hash  m6-corrupt.tar.gz"
docker run --rm --entrypoint /opt/webobs/bin/webobs-backup `
    -v $MountConfig -v $MountBackups webobs:m0 verify /backups/m6-corrupt.tar.gz 2>$null
if ($LASTEXITCODE -eq 0) { throw 'Corrupted backup unexpectedly passed verification.' }

docker run --rm --entrypoint /opt/obs/bin/webobs-scene-tool `
    -v $MountConfig webobs:m0 validate /config/webobs/scene.json
if ($LASTEXITCODE -ne 0) { throw 'Restored scene failed product validation.' }
docker run --rm --entrypoint /opt/obs/bin/webobs-scene-tool `
    -v $MountConfig webobs:m0 validate-studio /config/webobs/studio.json
if ($LASTEXITCODE -ne 0) { throw 'Restored Studio collection failed product validation.' }

Write-Host 'M7 config backup creation, checksum, permissions, confirmation, scene/Studio restore, corruption rejection, validation, and redaction acceptance passed.'
