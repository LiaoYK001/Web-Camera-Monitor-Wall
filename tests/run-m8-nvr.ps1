[CmdletBinding()]
param([switch]$SkipBuild, [int]$SoakMinutes = 1)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'M8 NVR acceptance requires PowerShell 7 (pwsh)' }
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Compose = Join-Path $PSScriptRoot 'compose.smoke.yaml'
$Artifacts = (Resolve-Path (Join-Path $PSScriptRoot 'artifacts')).Path
$ConfigRoot = Join-Path $Artifacts 'm8-config'
$StorageRoot = Join-Path $Artifacts 'm8-recordings'
$Base = 'http://127.0.0.1:18087'

function Assert-True([bool]$Condition, [string]$Message) { if (-not $Condition) { throw $Message } }
function Request([string]$Method, [string]$Path, [AllowNull()][object]$Body = $null) {
    $arguments = @{ Uri = "$Base$Path"; Method = $Method; NoProxy = $true; SkipHttpErrorCheck = $true; ConnectionTimeoutSeconds = 10; OperationTimeoutSeconds = 40 }
    if ($Method -ne 'GET') { $arguments.Headers = @{ Origin = $Base }; $arguments.ContentType = 'application/json' }
    if ($null -ne $Body) { $arguments.Body = $Body | ConvertTo-Json -Depth 32 -Compress }
    Invoke-WebRequest @arguments
}
function Wait-Nvr([int]$Seconds = 60) {
    $deadline = [DateTime]::UtcNow.AddSeconds($Seconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        try { $response = Request GET '/api/v1/nvr/status'; if ($response.StatusCode -eq 200) { return } } catch {}
        Start-Sleep -Milliseconds 300
    }
    docker compose -f $Compose logs --no-color --tail 160 webobs-nvr
    throw 'M8 NVR service did not become ready'
}
function Get-Segments { ((Request GET '/api/v1/nvr/segments?limit=5000').Content | ConvertFrom-Json -Depth 32).segments }

Push-Location $Root
try {
    docker compose -f $Compose down --volumes --remove-orphans
    foreach ($directory in @($ConfigRoot, $StorageRoot)) {
        $resolvedParent = [IO.Path]::GetFullPath((Split-Path -Parent $directory))
        Assert-True ($resolvedParent -eq $Artifacts) 'M8 cleanup target escaped tests/artifacts'
        if (Test-Path -LiteralPath $directory) { Remove-Item -LiteralPath $directory -Recurse -Force }
        New-Item -ItemType Directory -Path $directory | Out-Null
    }
    foreach ($path in @(Join-Path $Artifacts 'm8-program.mp4')) {
        if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force }
    }
    Get-ChildItem -LiteralPath $Artifacts -File -Filter '.m8-program.mp4.webobsd-*.mkv' | Remove-Item -Force
    $cameras = 1..4 | ForEach-Object {
        [ordered]@{
            id = "fixture-$_"; name = "Fixture $_"; policy = 'continuous'
            mainUrl = 'rtsp://mediamtx:8554/m0-test'; subUrl = 'rtsp://mediamtx:8554/m0-test'
            stream = if ($_ -eq 2) { 'sub' } else { 'main' }
            mode = if ($_ -eq 4) { 'transcode' } else { 'auto' }
            transport = 'tcp'; segmentSeconds = 2; maxAgeHours = 24; maxBytes = 0
            preEventSeconds = 0; schedule = @()
        }
    }
    $config = [ordered]@{ schemaVersion = 1; segmentSeconds = 2; maxAgeHours = 24; maxBytes = 0; minFreeBytes = 0; cameras = @($cameras) }
    $config | ConvertTo-Json -Depth 32 | Set-Content -Encoding utf8NoBOM -LiteralPath (Join-Path $ConfigRoot 'nvr.json')
    if (-not $SkipBuild) {
        docker compose -f $Compose build mediamtx fixture webobs-nvr
        Assert-True ($LASTEXITCODE -eq 0) 'M8 images failed to build'
    }
    docker compose -f $Compose up --no-build -d mediamtx fixture webobs-nvr
    Assert-True ($LASTEXITCODE -eq 0) 'M8 services failed to start'
    Wait-Nvr

    $deadline = [DateTime]::UtcNow.AddSeconds([Math]::Max(30, $SoakMinutes * 60))
    do {
        Start-Sleep -Seconds 2
        $segments = @(Get-Segments)
        $counts = @($segments | Group-Object cameraId)
    } while ([DateTime]::UtcNow -lt $deadline -and ($counts.Count -lt 4 -or @($counts | Where-Object Count -lt 2).Count -gt 0))
    Assert-True ($counts.Count -eq 4 -and @($counts | Where-Object Count -lt 2).Count -eq 0) 'Each of four NVR cameras must finalize at least two segments'
    Assert-True (@($segments | Where-Object { $_.videoCodec -ne 'h264' -or $_.integrity -ne 'verified' -or $_.durationMs -le 0 }).Count -eq 0) `
        'Every catalog segment must be verified H.264 with positive monotonic duration'
    Assert-True (@($segments.id | Sort-Object -Unique).Count -eq $segments.Count) 'Segment ids must remain unique across simultaneous timestamps'
    $publicConfig = (Request GET '/api/v1/nvr/config').Content
    Assert-True ($publicConfig -notmatch 'mediamtx|8554|m0-test' -and $publicConfig -match 'rtsp://\*\*\*') 'Public NVR config must redact every source endpoint'
    $publicRoundTrip = $publicConfig | ConvertFrom-Json -Depth 32
    Assert-True ((Request PUT '/api/v1/nvr/config' $publicRoundTrip).StatusCode -eq 200) 'Redacted public config must safely round-trip without replacing stored secrets'
    $privateConfig = Get-Content -Raw -LiteralPath (Join-Path $ConfigRoot 'nvr.json')
    Assert-True ($privateConfig -match 'mediamtx:8554/m0-test' -and $privateConfig -notmatch 'rtsp://\*\*\*') 'Round-trip must preserve private source endpoints only in the mode-0600 config'
    $statusBody = (Request GET '/api/v1/nvr/status').Content
    Assert-True ($statusBody -notmatch 'rtsp://|mediamtx|m0-test') 'NVR status must contain stable camera ids only'
    Assert-True ((Test-Path -LiteralPath (Join-Path $StorageRoot 'catalog.sqlite3')) -and (Test-Path -LiteralPath (Join-Path $StorageRoot 'catalog.sqlite3-wal'))) `
        'NVR catalog must run in SQLite WAL mode'
    docker compose -f $Compose exec -T webobs-nvr /opt/webobs/bin/webobs-nvrd --config /test-config/nvr.json --validate-config
    Assert-True ($LASTEXITCODE -eq 0) 'Private NVR configuration validator must accept the active schema without starting another service'

    $locked = $segments | Sort-Object startUtcMs | Select-Object -First 1
    $lockResponse = Request PUT "/api/v1/nvr/locks/$($locked.id)" @{ locked = $true }
    Assert-True ($lockResponse.StatusCode -eq 200) 'Evidence lock request failed'

    $completedBeforeKill = @($segments.id)
    Start-Sleep -Milliseconds 700
    docker compose -f $Compose kill -s KILL webobs-nvr
    Assert-True ($LASTEXITCODE -eq 0) 'M8 arbitrary-phase kill failed'
    docker compose -f $Compose up --no-build -d webobs-nvr
    Wait-Nvr
    Start-Sleep -Seconds 6
    $afterRecovery = @(Get-Segments)
    foreach ($id in $completedBeforeKill) { Assert-True ($afterRecovery.id -contains $id) "Completed segment $id was lost after crash recovery" }
    Assert-True (@($afterRecovery | Where-Object integrity -eq 'missing').Count -eq 0) 'Recovery must not mark a completed segment missing'
    $recoveryStatus = (Request GET '/api/v1/nvr/status').Content | ConvertFrom-Json -Depth 32
    Assert-True ($recoveryStatus.quarantined -ge 0 -and $recoveryStatus.recovered -ge 0) 'Recovery counters must be present'

    $config.cameras[1].policy = 'scheduled'
    $config.cameras[1].schedule = @(
        [ordered]@{ days = @(0,1,2,3,4,5,6); start = '00:00'; end = '12:00' },
        [ordered]@{ days = @(0,1,2,3,4,5,6); start = '12:00'; end = '23:59' },
        [ordered]@{ days = @(0,1,2,3,4,5,6); start = '23:59'; end = '00:01' })
    $config.cameras[2].policy = 'event'
    $config.cameras[2].preEventSeconds = 4
    $config.cameras[3].policy = 'off'
    Assert-True ((Request PUT '/api/v1/nvr/config' $config).StatusCode -eq 200) 'NVR policy update failed'
    Start-Sleep -Seconds 4
    $policyStatus = (Request GET '/api/v1/nvr/status').Content | ConvertFrom-Json -Depth 32
    Assert-True (($policyStatus.cameras | Where-Object id -eq 'fixture-2').state -eq 'recording') 'Scheduled policy must be active in the deterministic UTC window'
    Assert-True (($policyStatus.cameras | Where-Object id -eq 'fixture-4').state -eq 'idle') 'Off policy must stop new segments'
    Assert-True ((Request POST '/api/v1/nvr/events/fixture-3' @{ active = $true }).StatusCode -eq 200) 'Event policy activation failed'
    Start-Sleep -Seconds 5
    Assert-True ((Request POST '/api/v1/nvr/events/fixture-3' @{ active = $false }).StatusCode -eq 200) 'Event policy deactivation failed'
    $eventSegments = @(Get-Segments | Where-Object { $_.cameraId -eq 'fixture-3' -and $_.kind -in @('pre-event','event') })
    Assert-True ($eventSegments.Count -ge 1) 'Event policy must promote a bounded pre-event ring or finalize an event segment'

    $config.maxBytes = 1
    $config.minFreeBytes = 1152921504606846976
    foreach ($camera in $config.cameras) { $camera.policy = 'off'; $camera.schedule = @() }
    $putConfig = Request PUT '/api/v1/nvr/config' $config
    Assert-True ($putConfig.StatusCode -eq 200) 'Retention configuration update failed'
    $retentionDeadline = [DateTime]::UtcNow.AddSeconds(15)
    do { Start-Sleep -Seconds 1; $retained = @(Get-Segments) } while ([DateTime]::UtcNow -lt $retentionDeadline -and $retained.Count -gt 1)
    Assert-True ($retained.id -contains $locked.id) 'Evidence-locked segment must survive quota pressure'
    Assert-True (@($retained | Where-Object id -ne $locked.id).Count -eq 0) 'Oldest eligible segments must be removed under quota pressure'
    $pressureStatus = (Request GET '/api/v1/nvr/status').Content | ConvertFrom-Json -Depth 32
    Assert-True ($pressureStatus.diskPressure) 'Minimum free-space reserve must expose disk pressure'
    $nvrMetrics = (Request GET '/api/v1/nvr/metrics').Content
    Assert-True ($nvrMetrics -match 'webobs_nvr_disk_pressure 1' -and $nvrMetrics -match 'camera_id="fixture-1"' -and $nvrMetrics -notmatch 'rtsp://|mediamtx') `
        'NVR Prometheus metrics must expose bounded stable labels without source endpoints'

    docker compose -f $Compose stop -t 20 webobs-nvr
    Assert-True ($LASTEXITCODE -eq 0) 'M8 product container did not stop cleanly'
    $allMedia = Get-ChildItem -LiteralPath $StorageRoot -Recurse -File -Filter '*.mp4'
    Assert-True ($allMedia.Count -ge 1) 'Evidence-locked media file is missing'
    foreach ($media in $allMedia) {
        docker run --rm --mount "type=bind,source=$StorageRoot,target=/nvr,readonly" webobs-m0-rtsp-fixture:local `
            ffprobe -v error -select_streams v:0 -show_entries stream=codec_name -of default=nw=1:nk=1 "/nvr/$($media.FullName.Substring($StorageRoot.Length + 1).Replace('\','/'))" | Out-Null
        Assert-True ($LASTEXITCODE -eq 0) "NVR media failed decode probe: $($media.Name)"
    }
    docker run --rm --entrypoint /opt/webobs/bin/webobs-nvrd `
        --mount "type=bind,source=$ConfigRoot,target=/cfg,readonly" `
        --mount "type=bind,source=$StorageRoot,target=/read-only,readonly" `
        webobs:m0 --config /cfg/nvr.json --storage /read-only --port 8092 2>$null
    Assert-True ($LASTEXITCODE -ne 0) 'NVR must fail closed when its storage volume is unwritable'
    $logs = @(& docker compose -f $Compose logs --no-color webobs-nvr) -join "`n"
    $nvrAudit = @($logs -split "`n" | Where-Object { $_ -match '"component":"nvr"' }) -join "`n"
    Assert-True ($nvrAudit -notmatch 'rtsp://|mediamtx:8554|m0-test') 'NVR catalog/audit logs must not expose source endpoints'
    Write-Host "M8 NVR gate passed: four cameras, copy/transcode, WAL catalog, crash recovery, quota retention, evidence lock, and redaction."
} finally {
    docker compose -f $Compose down --volumes --remove-orphans
    Pop-Location
}
