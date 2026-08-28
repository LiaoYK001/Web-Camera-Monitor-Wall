param(
    [switch]$SkipBuild,
    [string]$Image = 'webobs:m0'
)

$ErrorActionPreference = 'Stop'
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
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
    docker build -t $Image -f (Join-Path $RepositoryRoot 'docker/Dockerfile') $RepositoryRoot
    if ($LASTEXITCODE -ne 0) { throw 'M6 backup product image failed to build.' }
}

$MountConfig = "${ConfigRoot}:/config/webobs"
$MountBackups = "${BackupRoot}:/backups"
docker run --rm --entrypoint /opt/obs/bin/webobs-scene-tool `
    -v $MountConfig $Image validate /config/webobs/scene.json
if ($LASTEXITCODE -ne 0) { throw 'Scene migration before backup failed.' }
$ScenePath = Join-Path $ConfigRoot 'scene.json'
$StudioPath = Join-Path $ConfigRoot 'studio.json'
$CurrentScene = Get-Content -Raw -LiteralPath $ScenePath | ConvertFrom-Json
$Studio = [ordered]@{
    schemaVersion = 1; revision = 0; programSceneId = $CurrentScene.id; previewSceneId = $CurrentScene.id
    transition = [ordered]@{ kind = 'cut'; durationMs = 0 }; scenes = @($CurrentScene)
}
[IO.File]::WriteAllText($StudioPath, ($Studio | ConvertTo-Json -Depth 32), $Utf8NoBom)
$CameraDbPath = Join-Path $ConfigRoot 'cameras.db'
$V2DbPath = Join-Path $ConfigRoot 'v2-clients.db'
$SharedScenesPath = Join-Path $ConfigRoot 'shared-scenes-v2.json'
$KeyRoot = Join-Path $ConfigRoot 'keys'
$GrantKeyPath = Join-Path $KeyRoot 'client-grant-signing.key'
[void](New-Item -ItemType Directory -Path $KeyRoot -Force)
python -c "import sqlite3,sys; [sqlite3.connect(path).execute('CREATE TABLE fixture(value TEXT)').connection.execute('INSERT INTO fixture VALUES (?)', ('original',)).connection.commit() for path in sys.argv[1:]]" $CameraDbPath $V2DbPath
if ($LASTEXITCODE -ne 0) { throw 'SQLite backup fixtures could not be created.' }
[IO.File]::WriteAllText($SharedScenesPath, (@{ schemaVersion = 1; scenes = @() } | ConvertTo-Json -Compress), $Utf8NoBom)
[IO.File]::WriteAllBytes($GrantKeyPath, [byte[]](0..95))
docker run --rm --entrypoint /opt/obs/bin/webobs-scene-tool `
    -v $MountConfig $Image validate-studio /config/webobs/studio.json
if ($LASTEXITCODE -ne 0) { throw 'Studio fixture validation before backup failed.' }
$OriginalHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $ScenePath).Hash
$OriginalStudioHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $StudioPath).Hash
$OriginalCameraDbHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $CameraDbPath).Hash
$OriginalV2DbHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $V2DbPath).Hash
$OriginalSharedScenesHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $SharedScenesPath).Hash
$OriginalGrantKeyHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $GrantKeyPath).Hash
$CreateOutput = @(docker run --rm --entrypoint /opt/webobs/bin/webobs-backup `
    -v $MountConfig -v $MountBackups $Image create m6-test.tar.gz 2>&1) -join "`n"
if ($LASTEXITCODE -ne 0) { throw "Backup creation failed:`n$CreateOutput" }
$Archive = Join-Path $BackupRoot 'm6-test.tar.gz'
$Checksum = "$Archive.sha256"
if (-not (Test-Path -LiteralPath $Archive) -or -not (Test-Path -LiteralPath $Checksum)) {
    throw 'Backup archive or checksum sidecar was not created.'
}
if ($CreateOutput -match 'rtsp://|password|token=') {
    throw 'Backup output leaked source or credential-like content.'
}

$Modes = @(docker run --rm --entrypoint stat -v $MountBackups $Image `
    -c '%a' /backups/m6-test.tar.gz /backups/m6-test.tar.gz.sha256)
if ($LASTEXITCODE -ne 0 -or @($Modes | Where-Object { $_.Trim() -ne '600' }).Count -ne 0) {
    throw 'Backup archive and checksum must use mode 0600.'
}
docker run --rm --entrypoint /opt/webobs/bin/webobs-backup `
    -v $MountConfig -v $MountBackups $Image verify /backups/m6-test.tar.gz
if ($LASTEXITCODE -ne 0) { throw 'Fresh backup verification failed.' }

$Changed = Get-Content -Raw -LiteralPath $ScenePath | ConvertFrom-Json
$Changed.name = 'M6 backup mutation fixture'
[IO.File]::WriteAllText($ScenePath, ($Changed | ConvertTo-Json -Depth 12), $Utf8NoBom)
$ChangedHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $ScenePath).Hash
if ($ChangedHash -eq $OriginalHash) { throw 'Backup test scene mutation did not change the file.' }
$ChangedStudio = Get-Content -Raw -LiteralPath $StudioPath | ConvertFrom-Json
$ChangedStudio.scenes[0].name = 'M7 Studio backup mutation fixture'
[IO.File]::WriteAllText($StudioPath, ($ChangedStudio | ConvertTo-Json -Depth 32), $Utf8NoBom)
$ChangedStudioHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $StudioPath).Hash
if ($ChangedStudioHash -eq $OriginalStudioHash) { throw 'Backup test Studio mutation did not change the file.' }
python -c "import sqlite3,sys; [sqlite3.connect(path).execute('UPDATE fixture SET value=?', ('changed',)).connection.commit() for path in sys.argv[1:]]" $CameraDbPath $V2DbPath
if ($LASTEXITCODE -ne 0) { throw 'SQLite backup fixtures could not be mutated.' }

$PreviousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = 'SilentlyContinue'
docker run --rm --entrypoint /opt/webobs/bin/webobs-backup `
    -v $MountConfig -v $MountBackups $Image restore /backups/m6-test.tar.gz 2>$null
$RejectedRestoreExit = $LASTEXITCODE
$ErrorActionPreference = $PreviousErrorActionPreference
if ($RejectedRestoreExit -eq 0) { throw 'Restore succeeded without the explicit confirmation value.' }
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $ScenePath).Hash -ne $ChangedHash) {
    throw 'Rejected restore modified the scene file.'
}
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $StudioPath).Hash -ne $ChangedStudioHash) {
    throw 'Rejected restore modified the Studio file.'
}

$RestoreOutput = @(docker run --rm --entrypoint /opt/webobs/bin/webobs-backup `
    -e WEBOBS_RESTORE_CONFIRM=replace-scene -v $MountConfig -v $MountBackups `
    $Image restore /backups/m6-test.tar.gz 2>&1) -join "`n"
if ($LASTEXITCODE -ne 0) { throw "Confirmed restore failed:`n$RestoreOutput" }
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $ScenePath).Hash -ne $OriginalHash) {
    throw 'Confirmed restore did not reproduce the original scene.'
}
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $StudioPath).Hash -ne $OriginalStudioHash) {
    throw 'Confirmed restore did not reproduce the original Studio collection.'
}
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $CameraDbPath).Hash -ne $OriginalCameraDbHash -or
    (Get-FileHash -Algorithm SHA256 -LiteralPath $V2DbPath).Hash -ne $OriginalV2DbHash -or
    (Get-FileHash -Algorithm SHA256 -LiteralPath $SharedScenesPath).Hash -ne $OriginalSharedScenesHash -or
    (Get-FileHash -Algorithm SHA256 -LiteralPath $GrantKeyPath).Hash -ne $OriginalGrantKeyHash) {
    throw 'Confirmed restore did not reproduce v2 Registry, sync, shared Scene, and signing-key state.'
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
$PreviousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = 'SilentlyContinue'
docker run --rm --entrypoint /opt/webobs/bin/webobs-backup `
    -v $MountConfig -v $MountBackups $Image verify /backups/m6-corrupt.tar.gz 2>$null
$CorruptVerifyExit = $LASTEXITCODE
$ErrorActionPreference = $PreviousErrorActionPreference
if ($CorruptVerifyExit -eq 0) { throw 'Corrupted backup unexpectedly passed verification.' }

docker run --rm --entrypoint /opt/obs/bin/webobs-scene-tool `
    -v $MountConfig $Image validate /config/webobs/scene.json
if ($LASTEXITCODE -ne 0) { throw 'Restored scene failed product validation.' }
docker run --rm --entrypoint /opt/obs/bin/webobs-scene-tool `
    -v $MountConfig $Image validate-studio /config/webobs/studio.json
if ($LASTEXITCODE -ne 0) { throw 'Restored Studio collection failed product validation.' }

Write-Host 'v2.1 config backup creation, SQLite checkpoint/integrity, signing-key pairing, restore, corruption rejection, validation, and redaction acceptance passed.'
