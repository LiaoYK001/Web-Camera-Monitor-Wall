[CmdletBinding()]
param([switch]$SkipBuild)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'M9 acceptance requires PowerShell 7' }
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Compose = Join-Path $PSScriptRoot 'compose.smoke.yaml'
$Artifacts = (Resolve-Path (Join-Path $PSScriptRoot 'artifacts')).Path
$ConfigRoot = Join-Path $Artifacts 'm9-config'
$StorageRoot = Join-Path $Artifacts 'm9-recordings'
$Base = 'http://127.0.0.1:18087'

function Assert-True([bool]$Condition, [string]$Message) { if (-not $Condition) { throw $Message } }
function Request([string]$Method, [string]$Path, [AllowNull()][object]$Body = $null, [hashtable]$Headers = @{}) {
    $arguments = @{ Uri = "$Base$Path"; Method = $Method; NoProxy = $true; SkipHttpErrorCheck = $true; ConnectionTimeoutSeconds = 10; OperationTimeoutSeconds = 320; Headers = $Headers }
    if ($Method -in @('PUT','POST')) { $arguments.ContentType = 'application/json' }
    if ($null -ne $Body) { $arguments.Body = $Body | ConvertTo-Json -Depth 32 -Compress }
    Invoke-WebRequest @arguments
}
function Wait-Nvr([int]$Seconds = 75) {
    $deadline = [DateTime]::UtcNow.AddSeconds($Seconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        try { if ((Request GET '/api/v1/nvr/health').StatusCode -eq 200) { return } } catch {}
        Start-Sleep -Milliseconds 300
    }
    docker compose -f $Compose logs --no-color --tail 120 webobs-nvr
    throw 'M9 NVR service did not become ready'
}
function Get-Segments { @(((Request GET '/api/v1/nvr/segments?limit=5000').Content | ConvertFrom-Json -Depth 32).segments) }

Push-Location $Root
try {
    $env:WEBOBS_TEST_NVR_CONFIG_ROOT = $ConfigRoot
    $env:WEBOBS_TEST_NVR_STORAGE_ROOT = $StorageRoot
    docker compose -f $Compose down --volumes --remove-orphans
    foreach ($directory in @($ConfigRoot, $StorageRoot)) {
        Assert-True ([IO.Path]::GetFullPath((Split-Path -Parent $directory)) -eq $Artifacts) 'M9 cleanup target escaped tests/artifacts'
        if (Test-Path -LiteralPath $directory) { Remove-Item -LiteralPath $directory -Recurse -Force }
        New-Item -ItemType Directory -Path $directory | Out-Null
    }
    Get-ChildItem -LiteralPath $Artifacts -File -Filter '.m8-program.mp4.webobsd-*.mkv' | Remove-Item -Force
    $programOutput = Join-Path $Artifacts 'm8-program.mp4'
    if (Test-Path -LiteralPath $programOutput) { Remove-Item -LiteralPath $programOutput -Force }
    $cameras = 1..4 | ForEach-Object {
        [ordered]@{
            id = "archive-$_"; name = "Archive $_"; policy = 'continuous'
            mainUrl = 'rtsp://mediamtx:8554/m0-test'; subUrl = 'rtsp://mediamtx:8554/m0-test'
            stream = if ($_ -gt 2) { 'sub' } else { 'main' }; mode = 'auto'; transport = 'tcp'
            segmentSeconds = 2; maxAgeHours = 24; maxBytes = 0; preEventSeconds = 0; schedule = @()
        }
    }
    $config = [ordered]@{ schemaVersion = 1; segmentSeconds = 2; maxAgeHours = 24; maxBytes = 0; minFreeBytes = 0; cameras = @($cameras) }
    $config | ConvertTo-Json -Depth 32 | Set-Content -Encoding utf8NoBOM -LiteralPath (Join-Path $ConfigRoot 'nvr.json')
    if (-not $SkipBuild) {
        docker compose -f $Compose build mediamtx fixture webobs-nvr
        Assert-True ($LASTEXITCODE -eq 0) 'M9 images failed to build'
    }
    docker compose -f $Compose up --no-build -d mediamtx fixture webobs-nvr
    Assert-True ($LASTEXITCODE -eq 0) 'M9 services failed to start'
    Wait-Nvr

    $deadline = [DateTime]::UtcNow.AddSeconds(75)
    do {
        Start-Sleep -Seconds 2
        $segments = @(Get-Segments)
        $counts = @($segments | Group-Object cameraId)
    } while ([DateTime]::UtcNow -lt $deadline -and ($counts.Count -lt 4 -or @($counts | Where-Object Count -lt 2).Count -gt 0))
    Assert-True ($counts.Count -eq 4 -and @($counts | Where-Object Count -lt 2).Count -eq 0) 'Four cameras must provide at least two timeline segments'
    foreach ($camera in $config.cameras) { $camera.policy = 'off' }
    Assert-True ((Request PUT '/api/v1/nvr/config' $config).StatusCode -eq 200) 'M9 fixture freeze failed'

    $from = [long](($segments | Measure-Object startUtcMs -Minimum).Minimum - 1000)
    $to = [long](($segments | Measure-Object endUtcMs -Maximum).Maximum + 1000)
    $cameraQuery = ($cameras | ForEach-Object { "cameraId=$($_.id)" }) -join '&'
    $timelinePath = "/api/v1/nvr/timeline?from=$from&to=$to&$cameraQuery"
    $timeline = (Request GET $timelinePath).Content | ConvertFrom-Json -Depth 32
    Assert-True ($timeline.storageTimeZone -eq 'UTC' -and $timeline.cameras.Count -eq 4 -and $timeline.queryDurationMs -ge 0) 'Timeline must be UTC normalized and return four authorized cameras'
    Assert-True (@($timeline.cameras | Where-Object { $_.recordedStream -notin @('main','sub') }).Count -eq 0) 'Timeline must disclose the recorded main/sub profile'

    $latencies = 1..40 | ForEach-Object { $watch = [Diagnostics.Stopwatch]::StartNew(); $null = Request GET $timelinePath; $watch.Stop(); $watch.Elapsed.TotalMilliseconds }
    $p95 = ($latencies | Sort-Object)[[Math]::Floor($latencies.Count * 0.95) - 1]
    Assert-True ($p95 -lt 500) "Timeline local-query p95 exceeded 500 ms: $p95"

    $primary = $segments | Where-Object cameraId -eq 'archive-1' | Sort-Object startUtcMs | Select-Object -First 1
    $range = Request GET "/api/v1/nvr/media/$($primary.id)" $null @{ Range = 'bytes=0-1023' }
    Assert-True ($range.StatusCode -eq 206 -and $range.Headers.'Content-Range' -match '^bytes 0-1023/') "Archive playback must honor HTTP Range (status=$($range.StatusCode), range=$($range.Headers.'Content-Range'))"

    $thumbnailPath = Join-Path $Artifacts 'm9-thumbnail.jpg'
    Invoke-WebRequest -Uri "$Base/api/v1/nvr/thumbnails/$($primary.id)?offsetMs=500" -OutFile $thumbnailPath -NoProxy
    $thumbnailBytes = [IO.File]::ReadAllBytes($thumbnailPath)
    Assert-True ($thumbnailBytes.Length -gt 100 -and $thumbnailBytes[0] -eq 0xff -and $thumbnailBytes[1] -eq 0xd8) 'Bounded thumbnail endpoint must return JPEG'
    $snapshot = (Request POST '/api/v1/nvr/snapshots' @{ segmentId = $primary.id; offsetMs = 500 }).Content | ConvertFrom-Json -Depth 32
    $snapshotPath = Join-Path $Artifacts 'm9-snapshot.jpg'
    Invoke-WebRequest -Uri "$Base$($snapshot.downloadUrl)" -OutFile $snapshotPath -NoProxy
    Assert-True ((Get-FileHash -Algorithm SHA256 -LiteralPath $snapshotPath).Hash.ToLowerInvariant() -eq $snapshot.sha256) 'Snapshot SHA-256 must match downloaded evidence'

    $exportFrom = [long]$primary.startUtcMs + 250
    $exportTo = [long]$primary.endUtcMs - 250
    Assert-True ($exportTo -gt $exportFrom) 'Fixture segment is too short for exact export'
    $fast = (Request POST '/api/v1/nvr/exports' @{ cameraIds = @('archive-1','archive-2','archive-3','archive-4'); fromUtcMs = $from + 1000; toUtcMs = $to - 1000; mode = 'fast'; lock = $true }).Content | ConvertFrom-Json -Depth 32
    $exact = (Request POST '/api/v1/nvr/exports' @{ cameraIds = @('archive-1'); fromUtcMs = $exportFrom; toUtcMs = $exportTo; mode = 'exact'; lock = $true; programRecordingId = 'program-fixture-001' }).Content | ConvertFrom-Json -Depth 32
    Assert-True ($fast.files.Count -eq 4 -and $fast.effectiveRange.fromUtcMs -le ($from + 1000) -and $fast.effectiveRange.toUtcMs -ge ($to - 1000)) 'Fast export must report keyframe/segment-aligned effective boundaries'
    Assert-True ($exact.effectiveRange.fromUtcMs -eq $exportFrom -and $exact.effectiveRange.toUtcMs -eq $exportTo) 'Exact export must report the requested frame boundary'
    Assert-True ($exact.programRecordingId -eq 'program-fixture-001') 'Exact evidence must preserve a safe logical program-recording association'
    foreach ($export in @($fast, $exact)) {
        $manifestPath = Join-Path $Artifacts "m9-$($export.exportId)-manifest.json"
        Invoke-WebRequest -Uri "$Base$($export.manifestUrl)" -OutFile $manifestPath -NoProxy
        Assert-True ((Get-FileHash -Algorithm SHA256 -LiteralPath $manifestPath).Hash.ToLowerInvariant() -eq $export.manifestSha256) 'Manifest SHA-256 mismatch'
        $manifestText = Get-Content -Raw -LiteralPath $manifestPath
        Assert-True ($manifestText -notmatch 'rtsp://|mediamtx|storageKey|recordings/' -and $manifestText -match 'auditId') 'Evidence manifest must contain audit identity without endpoints or physical paths'
        foreach ($file in $export.files) {
            $download = Join-Path $Artifacts "m9-$($export.exportId)-$($file.name)"
            Invoke-WebRequest -Uri "$Base$($file.downloadUrl)" -OutFile $download -NoProxy
            Assert-True ((Get-FileHash -Algorithm SHA256 -LiteralPath $download).Hash.ToLowerInvariant() -eq $file.sha256) 'Export file SHA-256 mismatch'
            docker run --rm --mount "type=bind,source=$Artifacts,target=/artifacts,readonly" webobs-m0-rtsp-fixture:local ffprobe -v error -select_streams v:0 -show_entries stream=codec_name -of default=nw=1:nk=1 "/artifacts/$([IO.Path]::GetFileName($download))" | Out-Null
            Assert-True ($LASTEXITCODE -eq 0) 'Exported evidence must be playable'
            if ($export.mode -eq 'exact') {
                $probeJson = docker run --rm --mount "type=bind,source=$Artifacts,target=/artifacts,readonly" webobs-m0-rtsp-fixture:local ffprobe -v error -select_streams v:0 -show_entries stream=avg_frame_rate:format=duration -of json "/artifacts/$([IO.Path]::GetFileName($download))" | ConvertFrom-Json -Depth 8
                $rateParts = $probeJson.streams[0].avg_frame_rate -split '/'
                $frameSeconds = [double]$rateParts[1] / [double]$rateParts[0]
                $requestedSeconds = ($exportTo - $exportFrom) / 1000.0
                Assert-True ([Math]::Abs([double]$probeJson.format.duration - $requestedSeconds) -le ($frameSeconds + 0.02)) 'Exact export duration must stay within one output frame of the requested range'
            }
        }
    }

    $corrupt = $segments | Where-Object { $_.id -ne $primary.id -and $_.cameraId -eq 'archive-1' } | Select-Object -First 1
    docker compose -f $Compose exec -T webobs-nvr python3 -c "import sqlite3,sys; c=sqlite3.connect('/recordings/nvr/catalog.sqlite3'); c.execute('UPDATE segments SET integrity=? WHERE id=?',('corrupt',sys.argv[1])); c.commit()" $corrupt.id
    Assert-True ($LASTEXITCODE -eq 0) 'Corrupt-segment fixture update failed'
    $timelineAfterCorrupt = (Request GET $timelinePath).Content | ConvertFrom-Json -Depth 32
    Assert-True (@(($timelineAfterCorrupt.cameras | Where-Object cameraId -eq 'archive-1').gaps | Where-Object reason -eq 'corrupt').Count -ge 1) 'Timeline must render corrupt media as an explicit recoverable gap'

    $leap = (Request GET '/api/v1/nvr/timeline?from=1709164800000&to=1709251200000&cameraId=archive-1').Content | ConvertFrom-Json -Depth 32
    Assert-True ($leap.storageTimeZone -eq 'UTC' -and $leap.fromUtcMs -eq 1709164800000) 'Leap-day queries must preserve exact UTC storage boundaries'
    Assert-True ((Request DELETE "/api/v1/nvr/segments/$($primary.id)").StatusCode -eq 409) 'Export-locked evidence must reject deletion'
    Assert-True ((Request PUT "/api/v1/nvr/locks/$($primary.id)" @{ locked = $false }).StatusCode -eq 200) 'Evidence unlock failed'
    $lease = (Request POST '/api/v1/nvr/playback-leases' @{ segmentId = $primary.id; ttlSeconds = 30 }).Content | ConvertFrom-Json -Depth 8
    Assert-True ((Request DELETE "/api/v1/nvr/segments/$($primary.id)").StatusCode -eq 409) 'Active playback must reject deletion'
    $config.maxBytes = 1
    Assert-True ((Request PUT '/api/v1/nvr/config' $config).StatusCode -eq 200) 'Playback-retention pressure update failed'
    Start-Sleep -Seconds 3
    Assert-True (@(Get-Segments).id -contains $primary.id) 'Retention must skip a segment with an active playback reader'
    $config.maxBytes = 0
    Assert-True ((Request PUT '/api/v1/nvr/config' $config).StatusCode -eq 200) 'Playback-retention pressure reset failed'
    Assert-True ((Request DELETE "/api/v1/nvr/playback-leases/$($lease.id)").StatusCode -eq 200) 'Playback lease release failed'
    Assert-True ((Request DELETE "/api/v1/nvr/segments/$($primary.id)").StatusCode -eq 200) 'Authorized unlocked deletion failed'

    docker compose -f $Compose exec -T webobs-nvr python3 -c "import datetime as d,zoneinfo; z=zoneinfo.ZoneInfo('America/New_York'); a=d.datetime(2024,11,3,5,30,tzinfo=d.timezone.utc).astimezone(z); b=d.datetime(2024,11,3,6,30,tzinfo=d.timezone.utc).astimezone(z); assert a.replace(tzinfo=None)==b.replace(tzinfo=None) and a.utcoffset()!=b.utcoffset()"
    Assert-True ($LASTEXITCODE -eq 0) 'DST duplicate wall-clock times must remain distinguishable by UTC and offset'

    $logs = @(& docker compose -f $Compose logs --no-color webobs-nvr) -join "`n"
    $nvrAudit = @($logs -split "`n" | Where-Object { $_ -match '"component":"nvr"' }) -join "`n"
    foreach ($event in @('nvr.playback.opened','nvr.playback.lease','nvr.playback.released','nvr.snapshot.created','nvr.export.created','nvr.segment.lock','nvr.segment.deleted','nvr.artifact.downloaded')) {
        Assert-True ($nvrAudit -match [Regex]::Escape($event)) "Missing M9 audit event: $event"
    }
    Assert-True ($nvrAudit -notmatch 'rtsp://|mediamtx:8554|m0-test|recordings/') 'M9 audit must not expose endpoints or storage paths'
    Write-Host "M9 timeline gate passed: UTC/gaps, p95=$([Math]::Round($p95,1)) ms, Range playback, JPEG evidence, four-way fast and exact exports, hashes, locks, delete, and audit."
} finally {
    docker compose -f $Compose down --volumes --remove-orphans
    Remove-Item Env:WEBOBS_TEST_NVR_CONFIG_ROOT -ErrorAction SilentlyContinue
    Remove-Item Env:WEBOBS_TEST_NVR_STORAGE_ROOT -ErrorAction SilentlyContinue
    Pop-Location
}
