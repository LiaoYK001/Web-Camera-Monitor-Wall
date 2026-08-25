[CmdletBinding()]
param(
    [switch]$SkipBuild,
    [string]$ChromePath = $env:WEBOBS_CHROME_BIN
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
Add-Type -AssemblyName System.Net.Http

$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ComposeFile = Join-Path $PSScriptRoot 'compose.smoke.yaml'
$ArtifactDirectory = Join-Path $PSScriptRoot 'artifacts'
$BaseUri = 'http://127.0.0.1:18085'
$CdpPort = 20000 + (Get-Random -Maximum 20000)
$script:CdpIdentifier = 0

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

function Send-CdpCommand {
    param(
        [Net.WebSockets.ClientWebSocket]$Socket,
        [string]$Method,
        [hashtable]$Parameters = @{}
    )
    $script:CdpIdentifier += 1
    $Identifier = $script:CdpIdentifier
    $Payload = @{ id = $Identifier; method = $Method; params = $Parameters } | ConvertTo-Json -Compress -Depth 12
    $Bytes = [Text.Encoding]::UTF8.GetBytes($Payload)
    [void]$Socket.SendAsync([ArraySegment[byte]]::new($Bytes), [Net.WebSockets.WebSocketMessageType]::Text,
        $true, [Threading.CancellationToken]::None).GetAwaiter().GetResult()
    while ($true) {
        $Memory = [IO.MemoryStream]::new()
        try {
            do {
                $Buffer = [byte[]]::new(65536)
                $Result = $Socket.ReceiveAsync([ArraySegment[byte]]::new($Buffer),
                    [Threading.CancellationToken]::None).GetAwaiter().GetResult()
                if ($Result.MessageType -eq [Net.WebSockets.WebSocketMessageType]::Close) {
                    throw 'Chrome DevTools socket closed unexpectedly'
                }
                $Memory.Write($Buffer, 0, $Result.Count)
            } while (-not $Result.EndOfMessage)
            $Message = [Text.Encoding]::UTF8.GetString($Memory.ToArray()) | ConvertFrom-Json
            if ($Message.id -eq $Identifier) {
                if ($null -ne $Message.error) { throw "CDP $Method failed: $($Message.error.message)" }
                return $Message.result
            }
        } finally {
            $Memory.Dispose()
        }
    }
}

function Invoke-CdpExpression {
    param([Net.WebSockets.ClientWebSocket]$Socket, [string]$Expression)
    $Response = Send-CdpCommand -Socket $Socket -Method 'Runtime.evaluate' -Parameters @{
        expression = $Expression
        returnByValue = $true
        awaitPromise = $true
    }
    if ($null -ne $Response.exceptionDetails) { throw 'Chrome expression raised an exception' }
    return $Response.result.value
}

function Invoke-CdpClick {
    param([Net.WebSockets.ClientWebSocket]$Socket, [string]$Selector)
    $Bounds = Invoke-CdpExpression -Socket $Socket -Expression @"
(() => {
  const element = document.querySelector('$Selector');
  if (!element) return null;
  const bounds = element.getBoundingClientRect();
  return { x: bounds.left + bounds.width / 2, y: bounds.top + bounds.height / 2 };
})()
"@
    Assert-True ($null -ne $Bounds) "Could not find browser control $Selector"
    foreach ($Type in @('mousePressed', 'mouseReleased')) {
        [void](Send-CdpCommand -Socket $Socket -Method 'Input.dispatchMouseEvent' -Parameters @{
            type = $Type
            x = [double]$Bounds.x
            y = [double]$Bounds.y
            button = 'left'
            clickCount = 1
        })
    }
}

function Connect-Cdp {
    param([Net.Http.HttpClient]$Client, [string]$ExpectedUrl)
    $Deadline = [DateTime]::UtcNow.AddSeconds(20)
    while ([DateTime]::UtcNow -lt $Deadline) {
        try {
            $Targets = $Client.GetStringAsync("http://127.0.0.1:$CdpPort/json/list").GetAwaiter().GetResult() |
                ConvertFrom-Json
            $Target = $Targets | Where-Object { $_.type -eq 'page' -and $_.url.StartsWith($ExpectedUrl) } |
                Select-Object -First 1
            if ($null -ne $Target) {
                $Socket = [Net.WebSockets.ClientWebSocket]::new()
                [void]$Socket.ConnectAsync([Uri]$Target.webSocketDebuggerUrl,
                    [Threading.CancellationToken]::None).GetAwaiter().GetResult()
                return $Socket
            }
        } catch {
            Start-Sleep -Milliseconds 200
        }
    }
    throw 'Chrome DevTools target did not become available'
}

function Wait-CdpExpression {
    param(
        [Net.WebSockets.ClientWebSocket]$Socket,
        [string]$Expression,
        [int]$TimeoutSeconds = 30,
        [string]$Message = 'Browser condition did not become true'
    )
    $Deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $Deadline) {
        if (Invoke-CdpExpression -Socket $Socket -Expression $Expression) { return }
        Start-Sleep -Milliseconds 200
    }
    throw $Message
}

function Start-AudioChrome {
    param([string]$Url, [string]$Profile)
    $Arguments = @(
        '--headless=new', '--disable-gpu', '--disable-features=WebRtcHideLocalIpsWithMdns',
        '--no-first-run', '--no-default-browser-check', '--no-proxy-server',
        "--remote-debugging-port=$CdpPort", '--remote-debugging-address=127.0.0.1',
        '--remote-allow-origins=*', "--user-data-dir=$Profile", $Url
    )
    return Start-Process -FilePath $ChromePath -ArgumentList $Arguments -WindowStyle Hidden -PassThru
}

function Stop-AudioChrome {
    param([AllowNull()][Diagnostics.Process]$Process, [AllowNull()][Net.WebSockets.ClientWebSocket]$Socket)
    if ($null -ne $Socket) {
        $Socket.Dispose()
    }
    if ($null -ne $Process) {
        if (-not $Process.HasExited) {
            Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
            $Process.WaitForExit(5000) | Out-Null
        }
        $Process.Dispose()
    }
}

function Invoke-AudioRecording {
    param([string]$Scene, [string]$Name, [int]$Duration, [int]$Fps = 10)
    $Path = Join-Path $ArtifactDirectory $Name
    if (Test-Path -LiteralPath $Path) { Remove-Item -LiteralPath $Path -Force }
    docker compose -f $ComposeFile run --rm `
        -e "WEBOBS_AUDIO_SCENE=$Scene" `
        -e "WEBOBS_OUTPUT=/artifacts/$Name" `
        -e "WEBOBS_DURATION_SECONDS=$Duration" `
        -e "WEBOBS_FPS=$Fps" `
        webobs-audio
    Assert-True ($LASTEXITCODE -eq 0) "Audio recording $Name failed"
}

if (-not $ChromePath) {
    $Candidates = @(
        (Join-Path $env:ProgramFiles 'Google\Chrome\Application\chrome.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Google\Chrome\Application\chrome.exe'),
        (Join-Path $env:LOCALAPPDATA 'Google\Chrome\Application\chrome.exe')
    )
    $ChromePath = $Candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $ChromePath -or -not (Test-Path -LiteralPath $ChromePath -PathType Leaf)) {
    throw 'Chrome was not found; set WEBOBS_CHROME_BIN to a trusted Chrome executable'
}

New-Item -ItemType Directory -Force -Path $ArtifactDirectory | Out-Null
$DirectProfile = Join-Path $ArtifactDirectory ('chrome-m5-direct-' + [Guid]::NewGuid().ToString('N'))
$CompositeProfile = Join-Path $ArtifactDirectory ('chrome-m5-composite-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $DirectProfile | Out-Null
New-Item -ItemType Directory -Path $CompositeProfile | Out-Null
$Handler = [Net.Http.HttpClientHandler]::new()
$Handler.UseProxy = $false
$Client = [Net.Http.HttpClient]::new($Handler)
$Client.Timeout = [TimeSpan]::FromSeconds(20)
$ChromeProcess = $null
$CdpSocket = $null

Push-Location $RepositoryRoot
try {
    docker compose -f $ComposeFile down --volumes --remove-orphans
    $BuildOption = if ($SkipBuild) { '--no-build' } else { '--build' }
    docker compose -f $ComposeFile up $BuildOption -d mediamtx fixture-audio-a fixture-audio-b
    Assert-True ($LASTEXITCODE -eq 0) 'M5 audio fixtures failed to start'
    $FixtureDeadline = [DateTime]::UtcNow.AddSeconds(45)
    $FixtureReady = $false
    while ([DateTime]::UtcNow -lt $FixtureDeadline) {
        $FixtureLogs = docker compose -f $ComposeFile logs --no-color mediamtx | Out-String
        if ($FixtureLogs.Contains("m5-audio-a") -and $FixtureLogs.Contains("m5-audio-b")) {
            $FixtureReady = $true
            break
        }
        Start-Sleep -Milliseconds 250
    }
    Assert-True $FixtureReady 'M5 audio fixtures did not publish before the deadline'

    $BrowserArtifact = Join-Path $ArtifactDirectory 'm5-browser-audio.mp4'
    if (Test-Path -LiteralPath $BrowserArtifact) { Remove-Item -LiteralPath $BrowserArtifact -Force }
    $env:WEBOBS_AUDIO_RECORDING_NAME = 'm5-browser-audio.mp4'
    $env:WEBOBS_AUDIO_DURATION_SECONDS = '0'
    docker compose -f $ComposeFile up $BuildOption -d webobs-audio
    Assert-True ($LASTEXITCODE -eq 0) 'M5 browser audio service failed to start'
    $ReadyDeadline = [DateTime]::UtcNow.AddSeconds(60)
    while ([DateTime]::UtcNow -lt $ReadyDeadline) {
        try {
            $Response = $Client.GetAsync("$BaseUri/api/v1/playback/capabilities").GetAwaiter().GetResult()
            if ($Response.IsSuccessStatusCode) { break }
        } catch { Start-Sleep -Milliseconds 250 }
    }
    Assert-True ($null -ne $Response -and $Response.IsSuccessStatusCode) 'M5 audio control plane did not become ready'
    $Capabilities = $Response.Content.ReadAsStringAsync().GetAwaiter().GetResult() | ConvertFrom-Json
    Assert-True ($Capabilities.sources.Count -eq 2) 'M5 Direct audio scene must expose two sources'

    $DirectUrl = "$BaseUri/#direct"
    $ChromeProcess = Start-AudioChrome -Url $DirectUrl -Profile $DirectProfile
    $CdpSocket = Connect-Cdp -Client $Client -ExpectedUrl $DirectUrl
    try {
        Wait-CdpExpression -Socket $CdpSocket -Expression @"
(() => {
  const control = document.querySelector('.direct-audio-control');
  const videos = [...document.querySelectorAll('.direct-tile video')];
  return control?.dataset.audioState === 'disabled' && control?.dataset.audioInputs === '2' &&
    videos.length === 2 && videos.every(video => video.muted);
})()
"@ -Message 'Direct audio was not muted by default with two mixer inputs'
    } catch {
        $InitialDiagnostics = Invoke-CdpExpression -Socket $CdpSocket -Expression @"
JSON.stringify({ href: location.href, body: document.body.innerText.slice(0, 300),
  state: document.querySelector('.direct-audio-control')?.dataset.audioState ?? null,
  inputs: document.querySelector('.direct-audio-control')?.dataset.audioInputs ?? null,
  videos: [...document.querySelectorAll('.direct-tile video')].map(video => ({ muted: video.muted, readyState: video.readyState }))
})
"@
        throw "Direct default-muted state did not settle: $InitialDiagnostics"
    }
    Invoke-CdpClick -Socket $CdpSocket -Selector '.direct-audio-control button'
    Wait-CdpExpression -Socket $CdpSocket -Expression "document.querySelector('.direct-audio-control')?.dataset.audioState === 'running'" `
        -Message 'Trusted Direct audio gesture did not start the Web Audio context'
    try {
        Wait-CdpExpression -Socket $CdpSocket -TimeoutSeconds 15 -Expression "Number(document.querySelector('.direct-audio-control')?.dataset.audioLevel ?? 0) > 0.01" `
            -Message 'Direct Web Audio analyser did not observe an audible mixed signal'
    } catch {
        $MediaDiagnostics = Invoke-CdpExpression -Socket $CdpSocket -Expression @"
JSON.stringify([...document.querySelectorAll('.direct-tile video')].map(video => ({
  paused: video.paused, muted: video.muted, readyState: video.readyState,
  audioTracks: video.srcObject?.getAudioTracks().map(track => ({ muted: track.muted, readyState: track.readyState })) ?? []
})))
"@
        throw "Direct Web Audio analyser did not observe a signal: $MediaDiagnostics"
    }
    $MixerSettings = Invoke-CdpExpression -Socket $CdpSocket -Expression @"
JSON.stringify([...document.querySelectorAll('.direct-tile')].map(tile => ({
  gain: tile.dataset.audioGain, sync: tile.dataset.audioSyncMs
})).sort((a, b) => a.sync.localeCompare(b.sync)))
"@ | ConvertFrom-Json
    Assert-True ($MixerSettings.Count -eq 2 -and $MixerSettings[0].gain -eq '1.000' -and
        $MixerSettings[0].sync -eq '0' -and $MixerSettings[1].gain -eq '0.250' -and
        $MixerSettings[1].sync -eq '125') 'Direct mixer did not apply per-source gain and sync settings'

    $InitialLogs = docker compose -f $ComposeFile logs --no-color webobs-audio | Out-String
    $ReaderPattern = "is reading from path '(?:direct|hybrid)-[a-f0-9]{32}', 2 tracks \((?:H264, Opus|Opus, H264)\)"
    $InitialReaders = [Regex]::Matches($InitialLogs, $ReaderPattern).Count
    Assert-True ($InitialReaders -ge 2 -and
        $InitialLogs -match "is reading from path 'direct-[a-f0-9]{32}', 2 tracks \((?:H264, Opus|Opus, H264)\)" -and
        $InitialLogs -match "is reading from path 'hybrid-[a-f0-9]{32}', 2 tracks \((?:H264, Opus|Opus, H264)\)") `
        'Direct browser did not establish one Opus passthrough and one AAC-to-Opus Hybrid reader'
    $ResolvedCapabilities = $Client.GetStringAsync("$BaseUri/api/v1/playback/capabilities").GetAwaiter().GetResult() |
        ConvertFrom-Json
    Assert-True ((@($ResolvedCapabilities.sources.audioCodec | Sort-Object -Unique) -join ',') -eq 'aac,opus') `
        'Playback capability probing must report both AAC and Opus audio codecs'
    Assert-True ((@($ResolvedCapabilities.sources.strategy | Sort-Object -Unique) -join ',') -eq 'hybrid,passthrough') `
        'Opus must stay on passthrough while AAC uses the Hybrid Opus fallback'
    docker compose -f $ComposeFile stop fixture-audio-b
    Assert-True ($LASTEXITCODE -eq 0) 'Could not stop the second audio publisher for reconnect coverage'
    Start-Sleep -Seconds 4
    docker compose -f $ComposeFile start fixture-audio-b
    Assert-True ($LASTEXITCODE -eq 0) 'Could not restart the second audio publisher'
    $ReconnectDeadline = [DateTime]::UtcNow.AddSeconds(45)
    $Reconnected = $false
    while ([DateTime]::UtcNow -lt $ReconnectDeadline) {
        $ReconnectLogs = docker compose -f $ComposeFile logs --no-color webobs-audio | Out-String
        $Readers = [Regex]::Matches($ReconnectLogs, $ReaderPattern).Count
        if ($Readers -gt $InitialReaders) { $Reconnected = $true; break }
        Start-Sleep -Milliseconds 500
    }
    Assert-True $Reconnected 'Direct H.264/Opus reader did not reconnect after publisher recovery'
    Wait-CdpExpression -Socket $CdpSocket -Expression "document.querySelector('.direct-audio-control')?.dataset.audioState === 'running'" `
        -Message 'Direct Web Audio context did not remain active across reconnect'
    Invoke-CdpClick -Socket $CdpSocket -Selector '.direct-audio-control button'
    Wait-CdpExpression -Socket $CdpSocket -Expression @"
document.querySelector('.direct-audio-control')?.dataset.audioState === 'disabled' &&
[...document.querySelectorAll('.direct-tile video')].every(video => video.muted)
"@ -Message 'Direct audio disable did not suspend output and remute every video'
    Stop-AudioChrome -Process $ChromeProcess -Socket $CdpSocket
    $ChromeProcess = $null
    $CdpSocket = $null

    $CdpPort += 1
    $CompositeUrl = "$BaseUri/#composite"
    $ChromeProcess = Start-AudioChrome -Url $CompositeUrl -Profile $CompositeProfile
    $CdpSocket = Connect-Cdp -Client $Client -ExpectedUrl $CompositeUrl
    try {
        Wait-CdpExpression -Socket $CdpSocket -Expression @"
document.querySelector('.program-audio-control')?.dataset.audioState === 'disabled' &&
document.querySelector('.program-preview video')?.muted === true &&
document.querySelector('.program-preview')?.classList.contains('live')
"@ -Message 'Composite Opus did not become live and muted by default'
    } catch {
        $CompositeDiagnostics = Invoke-CdpExpression -Socket $CdpSocket -Expression @"
JSON.stringify({ href: location.href, body: document.body.innerText.slice(0, 300),
  audioState: document.querySelector('.program-audio-control')?.dataset.audioState ?? null,
  live: document.querySelector('.program-preview')?.classList.contains('live') ?? false,
  video: (() => { const video = document.querySelector('.program-preview video'); return video ?
    { muted: video.muted, paused: video.paused, readyState: video.readyState } : null })() })
"@
        $CompositeLogs = docker compose -f $ComposeFile logs --no-color --tail 120 webobs-audio | Out-String
        throw "Composite default-muted state did not settle: $CompositeDiagnostics`n$CompositeLogs"
    }
    Invoke-CdpClick -Socket $CdpSocket -Selector '.program-audio-control button'
    Wait-CdpExpression -Socket $CdpSocket -Expression @"
document.querySelector('.program-audio-control')?.dataset.audioState === 'running' &&
document.querySelector('.program-preview video')?.muted === false
"@ -Message 'Trusted Composite audio gesture did not enable Opus playback'
    $ProgramLogs = docker compose -f $ComposeFile logs --no-color webobs-audio | Out-String
    Assert-True ($ProgramLogs -match "is reading from path 'program', 2 tracks \((?:H264, Opus|Opus, H264)\)") `
        'Composite WHEP reader did not receive H.264 and Opus tracks'
    Stop-AudioChrome -Process $ChromeProcess -Socket $CdpSocket
    $ChromeProcess = $null
    $CdpSocket = $null

    docker compose -f $ComposeFile stop -t 20 webobs-audio
    Assert-True ($LASTEXITCODE -eq 0) 'M5 browser audio service did not stop cleanly'
    docker compose -f $ComposeFile run --rm `
        -e TEST_RECORDING=/artifacts/m5-browser-audio.mp4 `
        -e TEST_MIN_DURATION=12 -e TEST_MAX_DURATION=120 `
        -e TEST_REQUIRE_PILLARBOX=0 -e TEST_REQUIRE_AUDIBLE=1 validator
    Assert-True ($LASTEXITCODE -eq 0) 'Composite browser audio recording was not finalized and audible'

    Invoke-AudioRecording -Scene 'm5-audio-full.json' -Name 'm5-audio-full.mp4' -Duration 10
    Invoke-AudioRecording -Scene 'm5-audio-mix.json' -Name 'm5-audio-quarter.mp4' -Duration 10
    Invoke-AudioRecording -Scene 'm5-audio-muted.json' -Name 'm5-audio-muted.mp4' -Duration 10
    Invoke-AudioRecording -Scene 'm5-audio-sync-zero.json' -Name 'm5-audio-sync-zero.mp4' -Duration 24 -Fps 20
    Invoke-AudioRecording -Scene 'm5-audio-sync-offset.json' -Name 'm5-audio-sync-offset.mp4' -Duration 24 -Fps 20
    docker compose -f $ComposeFile run --rm --entrypoint /usr/local/bin/probe-audio-recordings validator `
        --full /artifacts/m5-audio-full.mp4 `
        --quarter /artifacts/m5-audio-quarter.mp4 `
        --muted /artifacts/m5-audio-muted.mp4 `
        --sync-zero /artifacts/m5-audio-sync-zero.mp4 `
        --sync-offset /artifacts/m5-audio-sync-offset.mp4
    Assert-True ($LASTEXITCODE -eq 0) 'M5 mix, mute, volume, sync, or drift verification failed'

    $Logs = docker compose -f $ComposeFile logs --no-color | Out-String
    Assert-True ($Logs -notmatch 'rtsp://[^/\s]+:[^@/\s]+@') 'M5 audio logs must not expose RTSP credentials'
    Write-Host 'M5 Direct Web Audio, Composite Opus, AAC recording, autoplay, reconnect, mix, mute, volume, sync, and drift acceptance passed.'
}
finally {
    Stop-AudioChrome -Process $ChromeProcess -Socket $CdpSocket
    $Client.Dispose()
    $Handler.Dispose()
    Remove-Item Env:WEBOBS_AUDIO_RECORDING_NAME -ErrorAction SilentlyContinue
    Remove-Item Env:WEBOBS_AUDIO_DURATION_SECONDS -ErrorAction SilentlyContinue
    docker compose -f $ComposeFile down --volumes --remove-orphans
    Pop-Location
    $ArtifactsRoot = [IO.Path]::GetFullPath($ArtifactDirectory) + [IO.Path]::DirectorySeparatorChar
    foreach ($Profile in @($DirectProfile, $CompositeProfile)) {
        $Resolved = [IO.Path]::GetFullPath($Profile)
        if ($Resolved.StartsWith($ArtifactsRoot, [StringComparison]::OrdinalIgnoreCase) -and
            (Test-Path -LiteralPath $Resolved)) {
            [IO.Directory]::Delete($Resolved, $true)
        }
    }
}
