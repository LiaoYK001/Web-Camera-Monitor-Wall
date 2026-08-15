[CmdletBinding()]
param([switch]$SkipBuild)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw 'M7 Studio acceptance requires PowerShell 7 (pwsh) for HTTP status assertions'
}
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Compose = Join-Path $PSScriptRoot 'compose.smoke.yaml'
$Artifacts = Join-Path $PSScriptRoot 'artifacts'
$Assets = Join-Path $Artifacts 'm7-assets'
$Output = Join-Path $Artifacts 'control-plane.mp4'
$FirstOutput = Join-Path $Artifacts 'm7-studio-first.mp4'
$Base = 'http://127.0.0.1:18080'
$Origin = $Base

function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}

function Invoke-Control {
    param([string]$Method, [string]$Path, [AllowNull()][object]$Body = $null,
          [AllowNull()][string]$IfMatch = $null)
    $headers = @{}
    if ($Method -ne 'GET') { $headers.Origin = $Origin }
    if ($null -ne $IfMatch) { $headers['If-Match'] = $IfMatch }
    $arguments = @{
        Uri = "$Base$Path"; Method = $Method; Headers = $headers
        SkipHttpErrorCheck = $true; UseBasicParsing = $true; TimeoutSec = 30
    }
    if ($null -ne $Body) {
        $arguments.ContentType = 'application/json'
        $arguments.Body = $Body | ConvertTo-Json -Depth 32 -Compress
    }
    Invoke-WebRequest @arguments
}

function Wait-Healthy {
    $deadline = [DateTime]::UtcNow.AddSeconds(60)
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $response = Invoke-Control GET '/api/v1/health'
            if ($response.StatusCode -eq 200) { return }
        } catch {}
        Start-Sleep -Milliseconds 300
    }
    docker compose -f $Compose logs --no-color --tail 160 webobs-control
    throw 'M7 Studio control service did not become healthy'
}

function Base-Source([string]$Id, [string]$Kind, [string]$Name) {
    [ordered]@{
        id = $Id; kind = $Kind; name = $Name; muted = $true; volume = 1.0
        syncOffsetMs = 0; monitoring = 'off'; audioTrack = 1; filters = @()
    }
}

function Item([string]$Id, [string]$SourceId, [int]$X, [int]$Y, [int]$Width,
              [int]$Height, [int]$Z, [string]$Group = '', [double]$Opacity = 1.0) {
    [ordered]@{
        id = $Id; sourceId = $SourceId; x = $X; y = $Y; width = $Width; height = $Height
        scaleMode = 'contain'; crop = [ordered]@{ top = 0; right = 0; bottom = 0; left = 0 }
        zIndex = $Z; visible = $true; locked = $false; groupId = $Group; rotation = 0.0
        opacity = $Opacity; blendMode = 'normal'
    }
}

function Scene([string]$Id, [string]$Name, [object[]]$Sources, [object[]]$Items,
               [string]$Background = '#000000') {
    [ordered]@{
        schemaVersion = 4; revision = 0; id = $Id; name = $Name
        canvas = [ordered]@{ width = 640; height = 360; backgroundColor = $Background }
        sources = $Sources; items = $Items
    }
}

Push-Location $Root
try {
    docker compose -f $Compose down --volumes --remove-orphans
    New-Item -ItemType Directory -Force -Path $Assets | Out-Null
    foreach ($path in @($Output, $FirstOutput, (Join-Path $Assets 'test.png'), (Join-Path $Assets 'test.mp4'))) {
        if (Test-Path -LiteralPath $path) {
            $archived = "$path.previous"
            Move-Item -LiteralPath $path -Destination $archived -Force
        }
    }
    Get-ChildItem -LiteralPath $Artifacts -Filter '.control-plane.mp4.webobsd-*.mkv' -File -ErrorAction SilentlyContinue |
        Remove-Item -Force
    if (-not $SkipBuild) {
        docker compose -f $Compose build mediamtx fixture webobs-control
        if ($LASTEXITCODE -ne 0) { throw 'M7 images failed to build' }
    }
    docker run --rm --mount "type=bind,source=$Assets,target=/out" webobs-m0-rtsp-fixture:local `
        ffmpeg -hide_banner -loglevel error -y -f lavfi -i 'testsrc2=size=640x360:rate=10' -frames:v 1 /out/test.png
    if ($LASTEXITCODE -ne 0) { throw 'M7 image fixture generation failed' }
    docker run --rm --mount "type=bind,source=$Assets,target=/out" webobs-m0-rtsp-fixture:local `
        ffmpeg -hide_banner -loglevel error -y -f lavfi -i 'testsrc2=size=640x360:rate=10' -t 3 -c:v libx264 -pix_fmt yuv420p /out/test.mp4
    if ($LASTEXITCODE -ne 0) { throw 'M7 media fixture generation failed' }

    docker compose -f $Compose up --no-build -d mediamtx fixture webobs-control
    if ($LASTEXITCODE -ne 0) { throw 'M7 Studio fixtures failed to start' }
    Wait-Healthy

    $initialResponse = Invoke-Control GET '/api/v1/studio'
    Assert-True ($initialResponse.StatusCode -eq 200) 'Initial Studio GET must succeed'
    $initial = $initialResponse.Content | ConvertFrom-Json -Depth 32
    Assert-True ($initial.scenes.Count -eq 1 -and $initial.revision -eq 0) 'Studio bootstrap must contain one scene at s0'
    $programBefore = (Invoke-Control GET '/api/v1/scene').Content

    $redSource = Base-Source 'solid-red' 'color' 'Red'
    $redSource.color = '#b91c1c'
    $redSource.filters = @([ordered]@{ id = 'red-correction'; kind = 'color-correction'; enabled = $true; amount = 0.05; value = '' })
    $red = Scene 'red' 'Red Studio' @($redSource) @((Item 'red-item' 'solid-red' 0 0 640 360 0 '' 0.92)) '#200000'

    $blueSource = Base-Source 'solid-blue' 'color' 'Blue'
    $blueSource.color = '#1d4ed8'
    $textSource = Base-Source 'title' 'text' 'Title'
    $textSource.text = 'WebOBS M7'
    $textSource.color = '#ffffff'
    $textSource.filters = @([ordered]@{ id = 'title-opacity'; kind = 'opacity'; enabled = $true; amount = 0.9; value = '' })
    $blue = Scene 'blue' 'Blue and Text' @($blueSource, $textSource) @(
        (Item 'blue-item' 'solid-blue' 0 0 640 360 0 'hero'),
        (Item 'title-item' 'title' 120 120 400 120 1 'hero' 0.85)) '#001030'

    $imageSource = Base-Source 'image-test' 'image' 'Image Fixture'
    $imageSource.filePath = '/assets/test.png'
    $image = Scene 'image' 'Image Scene' @($imageSource) @((Item 'image-item' 'image-test' 0 0 640 360 0))

    $mediaSource = Base-Source 'media-test' 'media' 'Media Fixture'
    $mediaSource.filePath = '/assets/test.mp4'
    $mediaSource.loop = $true
    $media = Scene 'media' 'Media Scene' @($mediaSource) @((Item 'media-item' 'media-test' 0 0 640 360 0))

    $nestedSource = Base-Source 'nested-blue' 'nested' 'Nested Blue'
    $nestedSource.sceneId = 'blue'
    $sharedCamera = $initial.scenes[0].sources[0]
    $fixtureUsername = "fixture-$([Guid]::NewGuid().ToString('N'))"
    $fixturePassword = [Guid]::NewGuid().ToString('N')
    $sharedCamera.rtspUrl = 'rtsp://' + $fixtureUsername + ':' + $fixturePassword + '@mediamtx:8554/m0-test'
    $nested = Scene 'nested' 'Nested and Shared' @($nestedSource, $sharedCamera) @(
        (Item 'nested-item' 'nested-blue' 0 0 480 360 0 'nested-group'),
        (Item 'shared-item' $sharedCamera.id 480 0 160 120 1 'nested-group'))

    $candidate = [ordered]@{
        schemaVersion = 1; revision = 0; programSceneId = 'main'; previewSceneId = 'red'
        transition = [ordered]@{ kind = 'fade'; durationMs = 20 }
        scenes = @($initial.scenes[0], $red, $blue, $image, $media, $nested)
    }
    $savedResponse = Invoke-Control PUT '/api/v1/studio' $candidate '"0"'
    Assert-True ($savedResponse.StatusCode -eq 200) "Studio collection PUT failed: $($savedResponse.Content)"
    $studio = $savedResponse.Content | ConvertFrom-Json -Depth 32
    Assert-True ($studio.scenes.Count -eq 6 -and $studio.revision -eq 1) 'Six-scene collection must persist at s1'
    Assert-True ($savedResponse.Content -notmatch [Regex]::Escape($fixturePassword)) 'Studio response must redact RTSP credentials'
    Assert-True ((Invoke-Control GET '/api/v1/scene').Content -eq $programBefore) 'Preview edit must not alter Program before Take'

    $stale = Invoke-Control PUT '/api/v1/studio' $candidate '"0"'
    Assert-True ($stale.StatusCode -eq 412) 'Stale Studio If-Match must be rejected'
    $capabilities = Invoke-Control GET '/api/v1/studio/capabilities'
    Assert-True ($capabilities.StatusCode -eq 200 -and $capabilities.Content -match 'requires Composite' -and $capabilities.Content -notmatch [Regex]::Escape($fixturePassword)) `
        'Capability matrix must disclose Composite fallback without secrets'

    $takeResponse = Invoke-Control POST '/api/v1/studio/take' $null '"1"'
    Assert-True ($takeResponse.StatusCode -eq 200) "Initial Fade Take failed: $($takeResponse.Content)"
    $afterTake = $takeResponse.Content | ConvertFrom-Json -Depth 32
    Assert-True ($afterTake.programSceneId -eq 'red' -and $afterTake.revision -eq 2) 'Take must atomically promote Preview'
    $undoResponse = Invoke-Control POST '/api/v1/studio/undo' $null '"2"'
    Assert-True ($undoResponse.StatusCode -eq 200) "Studio undo failed: $($undoResponse.Content)"
    $undone = $undoResponse.Content | ConvertFrom-Json -Depth 32
    Assert-True ($undone.programSceneId -eq 'main') 'Undo must restore the previous Program state'
    $redoResponse = Invoke-Control POST '/api/v1/studio/redo' $null "`"$($undone.revision)`""
    Assert-True ($redoResponse.StatusCode -eq 200) "Studio redo failed: $($redoResponse.Content)"
    $studio = $redoResponse.Content | ConvertFrom-Json -Depth 32
    $roundTrip = $studio | ConvertTo-Json -Depth 32 -Compress
    $expectedRoundTrip = $afterTake | ConvertTo-Json -Depth 32 -Compress
    $roundTrip = $roundTrip -replace '"revision":\d+', '"revision":0'
    $expectedRoundTrip = $expectedRoundTrip -replace '"revision":\d+', '"revision":0'
    Assert-True ($roundTrip -eq $expectedRoundTrip) 'Undo/redo must restore byte-equivalent canonical Studio state apart from revision'

    foreach ($target in @('image', 'media', 'nested', 'red')) {
        $studio.previewSceneId = $target
        $put = Invoke-Control PUT '/api/v1/studio' $studio "`"$($studio.revision)`""
        Assert-True ($put.StatusCode -eq 200) "Preview switch to $target failed: $($put.Content)"
        $studio = $put.Content | ConvertFrom-Json -Depth 32
        $take = Invoke-Control POST '/api/v1/studio/take' $null "`"$($studio.revision)`""
        Assert-True ($take.StatusCode -eq 200) "Take of $target failed: $($take.Content)"
        $studio = $take.Content | ConvertFrom-Json -Depth 32
        Assert-True ($studio.programSceneId -eq $target) "Program must become $target"
    }

    for ($index = 0; $index -lt 500; $index++) {
        $target = if (($index % 2) -eq 0) { 'blue' } else { 'red' }
        $studio.previewSceneId = $target
        $studio.transition.kind = if (($index % 4) -lt 2) { 'cut' } else { 'fade' }
        $studio.transition.durationMs = if ($studio.transition.kind -eq 'fade') { 20 } else { 0 }
        $put = Invoke-Control PUT '/api/v1/studio' $studio "`"$($studio.revision)`""
        Assert-True ($put.StatusCode -eq 200) "Studio switch PUT #$index failed: $($put.Content)"
        $studio = $put.Content | ConvertFrom-Json -Depth 32
        $take = Invoke-Control POST '/api/v1/studio/take' $null "`"$($studio.revision)`""
        Assert-True ($take.StatusCode -eq 200) "Studio Take #$index failed: $($take.Content)"
        $studio = $take.Content | ConvertFrom-Json -Depth 32
        Assert-True ($studio.programSceneId -eq $target) "Studio Take #$index returned stale Program state"
        if (($index % 50) -eq 49) {
            Assert-True ((Invoke-Control GET '/api/v1/health').StatusCode -eq 200) "Health failed after Take #$index"
        }
    }

    $sameProgram = $studio.programSceneId
    $sameScene = $studio.scenes | Where-Object id -eq $sameProgram | Select-Object -First 1
    $sameScene.name = 'Red Studio Retaken'
    $samePut = Invoke-Control PUT '/api/v1/studio' $studio "`"$($studio.revision)`""
    Assert-True ($samePut.StatusCode -eq 200) "Same-Program edit failed: $($samePut.Content)"
    $studio = $samePut.Content | ConvertFrom-Json -Depth 32
    Assert-True ($studio.programSceneId -eq $studio.previewSceneId) 'Same-scene retake fixture must keep Program and Preview ids equal'
    $sceneBeforeRetake = (Invoke-Control GET '/api/v1/scene').Content
    $sameTake = Invoke-Control POST '/api/v1/studio/take' $null "`"$($studio.revision)`""
    Assert-True ($sameTake.StatusCode -eq 200) "Same-Program Take failed: $($sameTake.Content)"
    $studio = $sameTake.Content | ConvertFrom-Json -Depth 32
    $sceneAfterRetake = (Invoke-Control GET '/api/v1/scene').Content
    Assert-True ($sceneAfterRetake -ne $sceneBeforeRetake -and $sceneAfterRetake -match 'Red Studio Retaken') `
        'Take must apply saved edits even when Program and Preview reference the same scene id'

    $migrationMode = (@(& docker compose -f $Compose exec -T webobs-control stat -c '%a' /test-config/scene.json.pre-v4.backup) -join '').Trim()
    Assert-True ($LASTEXITCODE -eq 0 -and $migrationMode -eq '600') 'Pre-v4 migration backup must exist with mode 0600'
    docker compose -f $Compose exec -T webobs-control sh -c 'cmp -s /test-config/scene.json.pre-v4.backup /test-scenes/m1-two-up.json'
    Assert-True ($LASTEXITCODE -eq 0) 'Migration backup must preserve the exact v3 fixture'
    $studioMode = (@(& docker compose -f $Compose exec -T webobs-control stat -c '%a' /test-config/studio.json) -join '').Trim()
    Assert-True ($LASTEXITCODE -eq 0 -and $studioMode -eq '600') 'Studio collection must persist with mode 0600'

    docker compose -f $Compose stop -t 20 webobs-control
    Assert-True ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $Output)) 'M7 Program recording must finalize on stop'
    Move-Item -LiteralPath $Output -Destination $FirstOutput
    docker compose -f $Compose up --no-build -d webobs-control
    Wait-Healthy
    $restarted = (Invoke-Control GET '/api/v1/studio').Content | ConvertFrom-Json -Depth 32
    Assert-True ($restarted.revision -eq $studio.revision -and $restarted.programSceneId -eq $studio.programSceneId -and $restarted.scenes.Count -eq 6) `
        'Studio collection and Program/Preview state must survive restart'
    docker compose -f $Compose stop -t 20 webobs-control
    Assert-True ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $Output)) 'Restarted M7 recording must finalize'

    $probe = & docker run --rm --mount "type=bind,source=$Artifacts,target=/artifacts,readonly" webobs-m0-rtsp-fixture:local `
        ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,width,height -show_entries format=duration -of json /artifacts/m7-studio-first.mp4
    Assert-True ($LASTEXITCODE -eq 0 -and ($probe -join "`n") -match '"codec_name": "h264"') 'M7 recording must be playable H.264'
    $black = @(& docker run --rm --mount "type=bind,source=$Artifacts,target=/artifacts,readonly" webobs-m0-rtsp-fixture:local `
        ffmpeg -hide_banner -nostats -i /artifacts/m7-studio-first.mp4 -vf 'blackdetect=d=0.20:pix_th=0.02' -an -f null - 2>&1) -join "`n"
    Assert-True ($LASTEXITCODE -eq 0 -and $black -notmatch 'black_duration:') 'M7 Cut/Fade recording must contain no black Program interval'
    $logs = @(& docker compose -f $Compose logs --no-color webobs-control) -join "`n"
    Assert-True ($logs -notmatch [Regex]::Escape($fixturePassword) -and $logs -notmatch [Regex]::Escape($fixtureUsername)) 'M7 logs must not expose RTSP credentials'
    Write-Host 'M7 Studio gate passed: six scenes, mixed sources, migration, isolation, undo/redo, restart, and 500 Cut/Fade operations.'
} finally {
    docker compose -f $Compose down --volumes --remove-orphans
    Pop-Location
}
