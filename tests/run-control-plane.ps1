[CmdletBinding()]
param(
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
Add-Type -AssemblyName System.Net.Http

$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ComposeFile = Join-Path $PSScriptRoot 'compose.smoke.yaml'
$ArtifactDirectory = Join-Path $PSScriptRoot 'artifacts'
$Artifact = Join-Path $ArtifactDirectory 'control-plane.mp4'
$LiveMutationArtifact = Join-Path $ArtifactDirectory 'control-plane-live-mutation.mp4'
$BaseUri = 'http://127.0.0.1:18080'
$LocalOrigin = 'http://127.0.0.1:18080'

function Assert-True {
    param(
        [bool]$Condition,
        [string]$Message
    )
    if (-not $Condition) {
        throw $Message
    }
}

function Invoke-ControlRequest {
    param(
        [Net.Http.HttpClient]$Client,
        [Net.Http.HttpMethod]$Method,
        [string]$Path,
        [AllowNull()][string]$Body = $null,
        [string]$ContentType = 'application/json',
        [hashtable]$Headers = @{}
    )

    $request = [Net.Http.HttpRequestMessage]::new($Method, "$BaseUri$Path")
    try {
        if ($PSBoundParameters.ContainsKey('Body')) {
            $request.Content = [Net.Http.StringContent]::new($Body, [Text.Encoding]::UTF8, $ContentType)
        }
        foreach ($entry in $Headers.GetEnumerator()) {
            if ($entry.Key -eq 'Host') {
                $request.Headers.Host = $entry.Value
            } else {
                [void]$request.Headers.TryAddWithoutValidation($entry.Key, $entry.Value)
            }
        }

        $response = $Client.SendAsync($request).GetAwaiter().GetResult()
        try {
            $content = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
            return [PSCustomObject]@{
                Status = [int]$response.StatusCode
                Body = $content
                Headers = $response.Headers
                ContentHeaders = $response.Content.Headers
            }
        } finally {
            $response.Dispose()
        }
    } finally {
        $request.Dispose()
    }
}

function Receive-WebSocketText {
    param(
        [Net.WebSockets.ClientWebSocket]$Socket,
        [int]$TimeoutSeconds = 8
    )

    $buffer = New-Object byte[] 65536
    $segment = [ArraySegment[byte]]::new($buffer)
    $builder = [Text.StringBuilder]::new()
    $cancellation = [Threading.CancellationTokenSource]::new([TimeSpan]::FromSeconds($TimeoutSeconds))
    try {
        do {
            $result = $Socket.ReceiveAsync($segment, $cancellation.Token).GetAwaiter().GetResult()
            if ($result.MessageType -eq [Net.WebSockets.WebSocketMessageType]::Close) {
                throw 'WebSocket closed before the expected event was received'
            }
            [void]$builder.Append([Text.Encoding]::UTF8.GetString($buffer, 0, $result.Count))
        } while (-not $result.EndOfMessage)
        return $builder.ToString()
    } finally {
        $cancellation.Dispose()
    }
}

New-Item -ItemType Directory -Force -Path $ArtifactDirectory | Out-Null
if (Test-Path -LiteralPath $Artifact) {
    Remove-Item -LiteralPath $Artifact -Force
}
if (Test-Path -LiteralPath $LiveMutationArtifact) {
    Remove-Item -LiteralPath $LiveMutationArtifact -Force
}

$handler = [Net.Http.HttpClientHandler]::new()
$handler.UseProxy = $false
$client = [Net.Http.HttpClient]::new($handler)
$client.Timeout = [TimeSpan]::FromSeconds(20)
$socket = $null

Push-Location $RepositoryRoot
try {
    docker compose -f $ComposeFile down --volumes --remove-orphans
    $buildOption = if ($SkipBuild) { '--no-build' } else { '--build' }
    docker compose -f $ComposeFile up $buildOption -d mediamtx fixture webobs-control
    if ($LASTEXITCODE -ne 0) { throw 'M1 control-plane fixtures failed to start' }

    $health = $null
    $lastHealthDetail = 'no response received'
    $deadline = [DateTime]::UtcNow.AddSeconds(60)
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $candidate = Invoke-ControlRequest -Client $client -Method ([Net.Http.HttpMethod]::Get) -Path '/api/v1/health'
            if ($candidate.Status -eq 200) {
                $health = $candidate
                break
            }
            $lastHealthDetail = "HTTP $($candidate.Status): $($candidate.Body)"
        } catch {
            $lastHealthDetail = $_.Exception.Message
            Start-Sleep -Milliseconds 250
        }
    }
    if ($null -eq $health) {
        docker compose -f $ComposeFile ps -a
        docker compose -f $ComposeFile logs --no-color --tail 120 webobs-control
        Write-Host "Last health probe: $lastHealthDetail"
    }
    Assert-True ($null -ne $health) 'M1 control endpoint did not become healthy'
    Assert-True ($health.Body -match '"status":"ok"') 'Health response must report ok'
    Assert-True (($health.Headers.GetValues('Cache-Control') -join ',') -match 'no-store') 'Responses must disable caching'
    Assert-True (($health.Headers.GetValues('X-Content-Type-Options') -join ',') -eq 'nosniff') 'Responses must set nosniff'
    Assert-True (($health.Headers.GetValues('Content-Security-Policy') -join ',') -match "default-src 'none'") 'Responses must set a restrictive CSP'

    $editor = Invoke-ControlRequest -Client $client -Method ([Net.Http.HttpMethod]::Get) -Path '/'
    Assert-True ($editor.Status -eq 200) 'Web editor index must be served by the product container'
    Assert-True ($editor.ContentHeaders.ContentType.MediaType -eq 'text/html') 'Web editor index must use an HTML content type'
    Assert-True ($editor.Body -match '<title>WebOBS Monitor Wall</title>') 'Web editor index must contain product metadata'
    $assetMatch = [Regex]::Match($editor.Body, 'src="(?<path>/assets/[^\"]+\.js)"')
    Assert-True ($assetMatch.Success) 'Web editor index must reference a bundled JavaScript asset'
    $editorAsset = Invoke-ControlRequest -Client $client -Method ([Net.Http.HttpMethod]::Get) -Path $assetMatch.Groups['path'].Value
    Assert-True ($editorAsset.Status -eq 200) 'Bundled Web editor JavaScript must be served'
    Assert-True ($editorAsset.ContentHeaders.ContentType.MediaType -eq 'text/javascript') 'Web editor JavaScript must use a script content type'
    Assert-True (($editorAsset.Headers.GetValues('Cache-Control') -join ',') -match 'immutable') 'Hashed Web assets must use immutable caching'
    $traversal = Invoke-ControlRequest -Client $client -Method ([Net.Http.HttpMethod]::Get) -Path '/assets/..%2Findex.html'
    Assert-True ($traversal.Status -eq 404) 'Encoded traversal paths must not access Web editor files'

    $initial = Invoke-ControlRequest -Client $client -Method ([Net.Http.HttpMethod]::Get) -Path '/api/v1/scene'
    Assert-True ($initial.Status -eq 200) 'GET scene must succeed'
    Assert-True ($initial.Headers.ETag.Tag -eq '"3"') 'GET scene must expose the current revision as ETag'
    $initialScene = $initial.Body | ConvertFrom-Json
    Assert-True ($initialScene.revision -eq 3) 'Initial scene revision must be three'

    $socket = [Net.WebSockets.ClientWebSocket]::new()
    $socket.Options.SetRequestHeader('Origin', $LocalOrigin)
    [void]$socket.ConnectAsync([Uri]'ws://127.0.0.1:18080/api/v1/ws', [Threading.CancellationToken]::None).GetAwaiter().GetResult()
    $snapshotEvent = Receive-WebSocketText -Socket $socket | ConvertFrom-Json
    Assert-True ($snapshotEvent.type -eq 'scene.snapshot') 'WebSocket must start with a scene.snapshot event'
    Assert-True ($snapshotEvent.scene.revision -eq 3) 'WebSocket snapshot must contain the current revision'

    $initialScene.items[0].x = 10
    $initialScene.items[0].width = 300
    $initialScene.items[0].crop.left = 12
    $initialScene.items[0].zIndex = 1
    $initialScene.items[1].x = 330
    $initialScene.items[1].width = 300
    $initialScene.items[1].zIndex = 0
    $initialScene.items[1].visible = $false
    $initialScene.sources[1].muted = $false
    $initialScene.sources[1].volume = 0.25
    $replacement = $initialScene | ConvertTo-Json -Depth 10 -Compress
    $updated = Invoke-ControlRequest -Client $client -Method ([Net.Http.HttpMethod]::Put) -Path '/api/v1/scene' `
        -Body $replacement -Headers @{ 'If-Match' = '"3"'; Origin = $LocalOrigin }
    Assert-True ($updated.Status -eq 200) 'Matching scene PUT must succeed'
    Assert-True ($updated.Headers.ETag.Tag -eq '"4"') 'Successful PUT must advance ETag exactly once'
    $updatedScene = $updated.Body | ConvertFrom-Json
    Assert-True ($updatedScene.revision -eq 4) 'Successful PUT must advance the document revision exactly once'
    Assert-True ($updatedScene.items[0].crop.left -eq 12 -and $updatedScene.items[0].zIndex -eq 1) `
        'Successful PUT must apply crop and layer order'
    Assert-True (-not $updatedScene.items[1].visible) 'Successful PUT must apply source visibility'

    $updatedEvent = Receive-WebSocketText -Socket $socket | ConvertFrom-Json
    Assert-True ($updatedEvent.type -eq 'scene.updated') 'Successful PUT must broadcast scene.updated'
    Assert-True ($updatedEvent.scene.revision -eq 4) 'WebSocket update must contain the committed revision'

    $updatedScene.items[1].visible = $true
    $updatedScene.sources = @($updatedScene.sources) + [PSCustomObject]@{
        id = 'camera-added'
        kind = 'rtsp'
        name = 'Added Test Camera'
        rtspUrl = 'rtsp://mediamtx:8554/m0-test'
        transport = 'tcp'
        muted = $true
        volume = 0.6
        syncOffsetMs = -80
        monitoring = 'off'
        audioTrack = 2
    }
    $updatedScene.items = @($updatedScene.items) + [PSCustomObject]@{
        id = 'item-added'
        sourceId = 'camera-added'
        x = 0
        y = 0
        width = 640
        height = 360
        scaleMode = 'contain'
        crop = [PSCustomObject]@{ top = 0; right = 0; bottom = 0; left = 0 }
        zIndex = 2
        visible = $true
    }
    $addBody = $updatedScene | ConvertTo-Json -Depth 10 -Compress
    $added = Invoke-ControlRequest -Client $client -Method ([Net.Http.HttpMethod]::Put) -Path '/api/v1/scene' `
        -Body $addBody -Headers @{ 'If-Match' = '"4"'; Origin = $LocalOrigin }
    Assert-True ($added.Status -eq 200) `
        "Adding an RTSP source while recording must succeed (HTTP $($added.Status): $($added.Body))"
    Assert-True ($added.Headers.ETag.Tag -eq '"5"') 'Adding a source must advance ETag exactly once'
    $addedScene = $added.Body | ConvertFrom-Json
    Assert-True ($addedScene.sources.Count -eq 3 -and $addedScene.items.Count -eq 3) 'Added source and item must be returned'
    $addedAudio = $addedScene.sources | Where-Object { $_.id -eq 'camera-added' }
    Assert-True ($addedAudio.syncOffsetMs -eq -80 -and $addedAudio.monitoring -eq 'off' -and `
                 $addedAudio.audioTrack -eq 2) 'Unified M5 audio settings must round-trip through the API'
    $addedEvent = Receive-WebSocketText -Socket $socket | ConvertFrom-Json
    Assert-True ($addedEvent.type -eq 'scene.updated' -and $addedEvent.scene.revision -eq 5) `
        'Adding a source must broadcast revision five'

    $addedScene.sources = @($addedScene.sources | Where-Object { $_.id -eq 'camera-added' })
    $addedScene.items = @($addedScene.items | Where-Object { $_.id -eq 'item-added' })
    $addedScene.items[0].zIndex = 0
    $removeBody = $addedScene | ConvertTo-Json -Depth 10 -Compress
    $removed = Invoke-ControlRequest -Client $client -Method ([Net.Http.HttpMethod]::Put) -Path '/api/v1/scene' `
        -Body $removeBody -Headers @{ 'If-Match' = '"5"'; Origin = $LocalOrigin }
    Assert-True ($removed.Status -eq 200) 'Removing RTSP sources while recording must succeed'
    Assert-True ($removed.Headers.ETag.Tag -eq '"6"') 'Removing sources must advance ETag exactly once'
    $currentScene = $removed.Body | ConvertFrom-Json
    Assert-True ($currentScene.sources.Count -eq 1 -and $currentScene.sources[0].id -eq 'camera-added') `
        'Removed sources must disappear from the committed document'
    $removedEvent = Receive-WebSocketText -Socket $socket | ConvertFrom-Json
    Assert-True ($removedEvent.type -eq 'scene.updated' -and $removedEvent.scene.revision -eq 6) `
        'Removing sources must broadcast revision six'

    $persistedText = @(& docker compose -f $ComposeFile exec -T webobs-control sh -c 'cat /test-config/scene.json') -join "`n"
    if ($LASTEXITCODE -ne 0) { throw 'Could not read the persisted scene from the test container' }
    $persisted = $persistedText | ConvertFrom-Json
    Assert-True ($persisted.revision -eq 6) 'Source CRUD must persist the committed revision'
    Assert-True ($persisted.sources.Count -eq 1 -and $persisted.sources[0].id -eq 'camera-added') `
        'Source CRUD must persist the final source set'
    Assert-True ($persisted.sources[0].syncOffsetMs -eq -80 -and $persisted.sources[0].audioTrack -eq 2) `
        'Source CRUD must persist unified audio settings'
    Assert-True ($persisted.items[0].width -eq 640) 'Source CRUD must persist the final full-canvas transform'
    $mode = (@(& docker compose -f $ComposeFile exec -T webobs-control stat -c '%a' /test-config/scene.json) -join '').Trim()
    Assert-True ($LASTEXITCODE -eq 0 -and $mode -eq '600') 'Persisted scene must retain mode 0600'
    $directoryMode = (@(& docker compose -f $ComposeFile exec -T webobs-control stat -c '%a' /test-config) -join '').Trim()
    Assert-True ($LASTEXITCODE -eq 0 -and $directoryMode -eq '700') 'Persisted scene directory must retain mode 0700'

    $stale = Invoke-ControlRequest -Client $client -Method ([Net.Http.HttpMethod]::Put) -Path '/api/v1/scene' `
        -Body $replacement -Headers @{ 'If-Match' = '"3"'; Origin = $LocalOrigin }
    Assert-True ($stale.Status -eq 412) 'Stale If-Match must return 412'
    Assert-True (($stale.Body | ConvertFrom-Json).revision -eq 6) 'Conflict response must expose the current revision'

    $currentBody = $currentScene | ConvertTo-Json -Depth 10 -Compress
    $unreachableScene = $currentBody | ConvertFrom-Json
    $unreachableScene.sources = @($unreachableScene.sources) + [PSCustomObject]@{
        id = 'camera-unreachable'
        kind = 'rtsp'
        name = 'Unreachable Test Camera'
        rtspUrl = 'rtsp://mediamtx:8554/m1-missing'
        transport = 'tcp'
        muted = $true
        volume = 1.0
        syncOffsetMs = 0
        monitoring = 'off'
        audioTrack = 1
    }
    $unreachableScene.items = @($unreachableScene.items) + [PSCustomObject]@{
        id = 'item-unreachable'
        sourceId = 'camera-unreachable'
        x = 0
        y = 0
        width = 320
        height = 180
        scaleMode = 'contain'
        crop = [PSCustomObject]@{ top = 0; right = 0; bottom = 0; left = 0 }
        zIndex = 1
        visible = $true
    }
    $unreachableBody = $unreachableScene | ConvertTo-Json -Depth 10 -Compress
    $unreachable = Invoke-ControlRequest -Client $client -Method ([Net.Http.HttpMethod]::Put) -Path '/api/v1/scene' `
        -Body $unreachableBody -Headers @{ 'If-Match' = '"6"'; Origin = $LocalOrigin }
    Assert-True ($unreachable.Status -eq 409) 'An unreachable added source must reject the transaction'
    Assert-True (($unreachable.Body | ConvertFrom-Json).revision -eq 6) `
        'A rejected source transaction must retain the current revision'
    $afterRejectedSource = Invoke-ControlRequest -Client $client -Method ([Net.Http.HttpMethod]::Get) -Path '/api/v1/scene'
    $afterRejectedScene = $afterRejectedSource.Body | ConvertFrom-Json
    Assert-True ($afterRejectedSource.Headers.ETag.Tag -eq '"6"' -and $afterRejectedScene.sources.Count -eq 1) `
        'A rejected source transaction must leave the active scene unchanged'

    $missing = Invoke-ControlRequest -Client $client -Method ([Net.Http.HttpMethod]::Put) -Path '/api/v1/scene' `
        -Body $currentBody -Headers @{ Origin = $LocalOrigin }
    Assert-True ($missing.Status -eq 428) 'Missing If-Match must return 428'

    $wrongType = Invoke-ControlRequest -Client $client -Method ([Net.Http.HttpMethod]::Put) -Path '/api/v1/scene' `
        -Body '{}' -ContentType 'text/plain' -Headers @{ 'If-Match' = '"6"'; Origin = $LocalOrigin }
    Assert-True ($wrongType.Status -eq 415) 'Non-JSON scene PUT must return 415'

    $foreignOrigin = Invoke-ControlRequest -Client $client -Method ([Net.Http.HttpMethod]::Put) -Path '/api/v1/scene' `
        -Body $currentBody -Headers @{ 'If-Match' = '"6"'; Origin = 'http://example.invalid' }
    Assert-True ($foreignOrigin.Status -eq 403) 'Foreign Origin must return 403'

    $badHost = Invoke-ControlRequest -Client $client -Method ([Net.Http.HttpMethod]::Get) -Path '/api/v1/health' `
        -Headers @{ Host = 'example.invalid' }
    Assert-True ($badHost.Status -eq 421) 'Non-loopback Host must return 421'

    $oversized = 'x' * (1024 * 1024 + 1)
    $tooLarge = Invoke-ControlRequest -Client $client -Method ([Net.Http.HttpMethod]::Put) -Path '/api/v1/scene' `
        -Body $oversized -Headers @{ 'If-Match' = '"6"'; Origin = $LocalOrigin }
    Assert-True ($tooLarge.Status -eq 413) 'Scene request over one MiB must return 413'

    $largeHeader = Invoke-ControlRequest -Client $client -Method ([Net.Http.HttpMethod]::Get) -Path '/api/v1/health' `
        -Headers @{ 'X-Test-Padding' = ('x' * (17 * 1024)) }
    Assert-True ($largeHeader.Status -eq 431) 'Headers over 16 KiB must return 431'

    Start-Sleep -Seconds 3
    $socket.Dispose()
    $socket = $null
    docker compose -f $ComposeFile stop webobs-control
    if ($LASTEXITCODE -ne 0) { throw 'M1 control-plane container did not stop cleanly' }
    Move-Item -LiteralPath $Artifact -Destination $LiveMutationArtifact
    docker compose -f $ComposeFile run --rm `
        -e TEST_RECORDING=/artifacts/control-plane-live-mutation.mp4 `
        -e TEST_MIN_DURATION=1 `
        -e TEST_MAX_DURATION=60 `
        -e TEST_REQUIRE_PILLARBOX=1 `
        -e TEST_SAMPLE_FROM_END_SECONDS=1 `
        -e TEST_REJECT_BLACKOUT=1 `
        validator
    if ($LASTEXITCODE -ne 0) { throw 'M1 live source CRUD recording validation failed' }

    docker compose -f $ComposeFile up -d --no-deps webobs-control
    if ($LASTEXITCODE -ne 0) { throw 'M1 persisted-scene restart failed' }
    $restartHealth = $null
    $restartDeadline = [DateTime]::UtcNow.AddSeconds(60)
    while ([DateTime]::UtcNow -lt $restartDeadline) {
        try {
            $candidate = Invoke-ControlRequest -Client $client -Method ([Net.Http.HttpMethod]::Get) -Path '/api/v1/health'
            if ($candidate.Status -eq 200) {
                $restartHealth = $candidate
                break
            }
        } catch {
            Start-Sleep -Milliseconds 250
        }
    }
    if ($null -eq $restartHealth) {
        docker compose -f $ComposeFile ps -a
        docker compose -f $ComposeFile logs --no-color --tail 160 webobs-control
    }
    Assert-True ($null -ne $restartHealth) 'Control plane must become healthy after a persisted-scene restart'
    $restarted = Invoke-ControlRequest -Client $client -Method ([Net.Http.HttpMethod]::Get) -Path '/api/v1/scene'
    $restartedScene = $restarted.Body | ConvertFrom-Json
    Assert-True ($restarted.Status -eq 200 -and $restarted.Headers.ETag.Tag -eq '"6"') `
        'Restart must restore the last committed revision'
    Assert-True ($restartedScene.sources.Count -eq 1 -and $restartedScene.sources[0].id -eq 'camera-added') `
        'Restart must restore the last committed source set'
    Start-Sleep -Seconds 2
    docker compose -f $ComposeFile stop webobs-control
    if ($LASTEXITCODE -ne 0) { throw 'Restarted M1 control-plane container did not stop cleanly' }
    docker compose -f $ComposeFile run --rm `
        -e TEST_RECORDING=/artifacts/control-plane.mp4 `
        -e TEST_MIN_DURATION=1 `
        -e TEST_MAX_DURATION=60 `
        -e TEST_REQUIRE_PILLARBOX=1 `
        validator
    if ($LASTEXITCODE -ne 0) { throw 'M1 persisted-scene restart recording validation failed' }

    $logs = @(& docker compose -f $ComposeFile logs --no-color webobs-control) -join "`n"
    $rtspUserinfoPattern = 'rts' + 'p://[^\s]+@'
    Assert-True ($logs -notmatch $rtspUserinfoPattern) 'Control-plane logs must not expose RTSP userinfo'
    Write-Host 'M1 control-plane acceptance passed: live source CRUD, transforms, REST, ETag, WebSocket, restart persistence, security, and recording.'
} finally {
    if ($null -ne $socket) {
        $socket.Dispose()
    }
    $client.Dispose()
    $handler.Dispose()
    docker compose -f $ComposeFile down --volumes --remove-orphans
    Pop-Location
}
