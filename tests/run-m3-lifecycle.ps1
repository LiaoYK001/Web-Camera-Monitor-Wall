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
$ArtifactName = 'm3-lifecycle-' + [Guid]::NewGuid().ToString('N') + '.mp4'
$Artifact = Join-Path $ArtifactDirectory $ArtifactName
$BaseUri = 'http://127.0.0.1:18083'
$LocalOrigin = 'http://127.0.0.1:18083'

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

function Invoke-LocalRequest {
    param(
        [Net.Http.HttpClient]$Client,
        [Net.Http.HttpMethod]$Method,
        [string]$Path,
        [AllowNull()][string]$Body = $null,
        [string]$ContentType = 'application/json',
        [hashtable]$Headers = @{}
    )
    $Request = [Net.Http.HttpRequestMessage]::new($Method, "$BaseUri$Path")
    try {
        if ($PSBoundParameters.ContainsKey('Body')) {
            $Request.Content = [Net.Http.StringContent]::new($Body, [Text.Encoding]::UTF8, $ContentType)
        }
        foreach ($Entry in $Headers.GetEnumerator()) {
            [void]$Request.Headers.TryAddWithoutValidation($Entry.Key, $Entry.Value)
        }
        $Response = $Client.SendAsync($Request).GetAwaiter().GetResult()
        try {
            return [PSCustomObject]@{
                Status = [int]$Response.StatusCode
                Body = $Response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
            }
        } finally { $Response.Dispose() }
    } finally { $Request.Dispose() }
}

function Get-Capabilities {
    param([Net.Http.HttpClient]$Client)
    $Response = Invoke-LocalRequest -Client $Client -Method ([Net.Http.HttpMethod]::Get) `
        -Path '/api/v1/playback/capabilities'
    if ($Response.Status -ne 200) { return $null }
    Assert-True ($Response.Body -notmatch 'rtsp://|(?:direct|hybrid)-[a-f0-9]{32}|mediamtx') `
        'Playback capabilities exposed an internal route or RTSP endpoint.'
    return ($Response.Body | ConvertFrom-Json)
}

function Wait-SourceClassification {
    param(
        [Net.Http.HttpClient]$Client,
        [string]$SourceId,
        [string]$Strategy,
        [string]$Codec,
        [int]$TimeoutSeconds = 45
    )
    $Deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        try {
            $Capabilities = Get-Capabilities -Client $Client
            $Source = $Capabilities.sources | Where-Object sourceId -eq $SourceId
            if ($null -ne $Source -and $Source.strategy -eq $Strategy -and $Source.codec -eq $Codec) {
                return $Capabilities
            }
        } catch {}
        Start-Sleep -Milliseconds 500
    } while ([DateTime]::UtcNow -lt $Deadline)
    throw "Source '$SourceId' did not become $Strategy/$Codec within $TimeoutSeconds seconds."
}

function Get-TranscoderCount {
    param([string]$ContainerId)
    $Rows = @(& docker top $ContainerId -eo pid,comm)
    if ($LASTEXITCODE -ne 0) { throw 'Could not inspect M3 lifecycle transcoder processes.' }
    return @($Rows | Select-Object -Skip 1 | Where-Object {
        (($_.Trim() -split '\s+') | Select-Object -Last 1) -eq 'ffmpeg'
    }).Count
}

function Wait-TranscoderCount {
    param([string]$ContainerId, [int]$Expected, [int]$TimeoutSeconds = 30)
    $Deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $Count = Get-TranscoderCount -ContainerId $ContainerId
        if ($Count -eq $Expected) { return }
        Start-Sleep -Seconds 1
    } while ([DateTime]::UtcNow -lt $Deadline)
    throw "Expected $Expected Hybrid transcoders, found $Count."
}

function Get-ProductLogs {
    $Logs = docker compose -f $ComposeFile logs --no-color webobs-hybrid | Out-String
    if ($LASTEXITCODE -ne 0) { throw 'Could not read M3 lifecycle product logs.' }
    Assert-True ($Logs -notmatch 'rtsp://[^/\s]+:[^@/\s]+@') 'Product logs exposed RTSP credentials.'
    return $Logs
}

function Wait-HybridReaderCount {
    param([string]$Path, [int]$Minimum, [int]$TimeoutSeconds = 50)
    $Pattern = "is reading from path '$([Regex]::Escape($Path))', 1 track \(H264\)"
    $Deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $Count = [Regex]::Matches((Get-ProductLogs), $Pattern).Count
        if ($Count -ge $Minimum) { return }
        Start-Sleep -Seconds 1
    } while ([DateTime]::UtcNow -lt $Deadline)
    throw "Hybrid browser reader did not reconnect within $TimeoutSeconds seconds."
}

function Update-Scene {
    param([Net.Http.HttpClient]$Client, [object]$Scene)
    $Revision = [uint64]$Scene.revision
    $Body = $Scene | ConvertTo-Json -Depth 12 -Compress
    $Response = Invoke-LocalRequest -Client $Client -Method ([Net.Http.HttpMethod]::Put) `
        -Path '/api/v1/scene' -Body $Body -Headers @{ 'If-Match' = "`"$Revision`""; Origin = $LocalOrigin }
    Assert-True ($Response.Status -eq 200) "Scene update from revision $Revision failed with HTTP $($Response.Status)."
    $Updated = $Response.Body | ConvertFrom-Json
    Assert-True ([uint64]$Updated.revision -eq ($Revision + 1)) 'Scene mutation did not advance revision exactly once.'
    return $Updated
}

function Stop-ChromeTree {
    param([Diagnostics.Process]$Process)
    if ($Process.HasExited) { return }
    & taskkill.exe /PID $Process.Id /T /F 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0 -and -not $Process.HasExited) {
        Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
    }
    $Process.WaitForExit(5000) | Out-Null
}

function Close-ChromePage {
    param([int]$DebugPort)
    $Targets = Invoke-RestMethod -Uri "http://127.0.0.1:$DebugPort/json/list" -TimeoutSec 5
    $Target = $Targets | Where-Object { $_.type -eq 'page' -and $_.url -like "$BaseUri/*" } |
        Select-Object -First 1
    if ($null -eq $Target -or [string]::IsNullOrWhiteSpace($Target.id)) {
        throw 'Could not resolve the M3 lifecycle browser page for a graceful close.'
    }
    Invoke-RestMethod -Uri "http://127.0.0.1:$DebugPort/json/close/$($Target.id)" -TimeoutSec 5 | Out-Null
}

if (-not $ChromePath) {
    $ChromeCandidates = @(
        (Join-Path $env:ProgramFiles 'Google\Chrome\Application\chrome.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Google\Chrome\Application\chrome.exe'),
        (Join-Path $env:LOCALAPPDATA 'Google\Chrome\Application\chrome.exe')
    )
    $ChromePath = $ChromeCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $ChromePath -or -not (Test-Path -LiteralPath $ChromePath -PathType Leaf)) {
    throw 'Chrome was not found; set WEBOBS_CHROME_BIN to a trusted Chrome executable.'
}

New-Item -ItemType Directory -Force -Path $ArtifactDirectory | Out-Null
$Profile = Join-Path $ArtifactDirectory ('chrome-m3-lifecycle-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $Profile | Out-Null
$Handler = [Net.Http.HttpClientHandler]::new()
$Handler.UseProxy = $false
$Client = [Net.Http.HttpClient]::new($Handler)
$Client.Timeout = [TimeSpan]::FromSeconds(20)
$ChromeProcess = $null
$PortProbe = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
$PortProbe.Start()
$ChromeDebugPort = ([Net.IPEndPoint]$PortProbe.LocalEndpoint).Port
$PortProbe.Stop()
$PreviousArtifactName = $env:WEBOBS_HYBRID_RECORDING_NAME
$env:WEBOBS_HYBRID_RECORDING_NAME = $ArtifactName

Push-Location $RepositoryRoot
try {
    docker compose -f $ComposeFile down --volumes --remove-orphans
    if (Test-Path -LiteralPath $Artifact) { Remove-Item -LiteralPath $Artifact -Force }
    $BuildOption = if ($SkipBuild) { '--no-build' } else { '--build' }
    docker compose -f $ComposeFile up $BuildOption -d mediamtx fixture fixture-hevc webobs-hybrid
    if ($LASTEXITCODE -ne 0) { throw 'M3 lifecycle services failed to start.' }

    $Capabilities = $null
    $ReadyDeadline = [DateTime]::UtcNow.AddSeconds(75)
    do {
        try { $Capabilities = Get-Capabilities -Client $Client } catch {}
        if ($null -ne $Capabilities -and $Capabilities.sources.Count -eq 2) { break }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $ReadyDeadline)
    Assert-True ($null -ne $Capabilities -and $Capabilities.sources.Count -eq 2) `
        'M3 lifecycle capabilities did not become ready.'

    $ChromeArguments = @(
        '--headless=new', '--disable-gpu', '--disable-features=WebRtcHideLocalIpsWithMdns',
        '--no-first-run', '--no-default-browser-check', '--autoplay-policy=no-user-gesture-required',
        '--remote-debugging-address=127.0.0.1', "--remote-debugging-port=$ChromeDebugPort",
        "--user-data-dir=$Profile", "$BaseUri/#direct"
    )
    $ChromeProcess = Start-Process -FilePath $ChromePath -ArgumentList $ChromeArguments `
        -WindowStyle Hidden -PassThru

    [void](Wait-SourceClassification -Client $Client -SourceId 'camera-h264' -Strategy passthrough -Codec h264)
    [void](Wait-SourceClassification -Client $Client -SourceId 'camera-hevc' -Strategy transcode -Codec hevc)
    $ContainerId = (@(& docker compose -f $ComposeFile ps -q webobs-hybrid) -join '').Trim()
    Assert-True (-not [string]::IsNullOrWhiteSpace($ContainerId)) 'Could not resolve the M3 lifecycle product container.'
    Wait-TranscoderCount -ContainerId $ContainerId -Expected 1
    $InitialLogs = Get-ProductLogs
    $InitialHybridMatch = [Regex]::Match($InitialLogs, "is reading from path '(hybrid-[a-f0-9]{32})', 1 track \(H264\)")
    Assert-True $InitialHybridMatch.Success 'Initial HEVC source did not establish a Hybrid H.264 browser reader.'
    $InitialHybridPath = $InitialHybridMatch.Groups[1].Value
    $InitialReaderCount = [Regex]::Matches(
        $InitialLogs,
        "is reading from path '$([Regex]::Escape($InitialHybridPath))', 1 track \(H264\)"
    ).Count

    docker compose -f $ComposeFile stop -t 5 fixture-hevc
    if ($LASTEXITCODE -ne 0) { throw 'Could not stop the HEVC fixture for reconnect testing.' }
    Start-Sleep -Seconds 5
    docker compose -f $ComposeFile start fixture-hevc
    if ($LASTEXITCODE -ne 0) { throw 'Could not restart the HEVC fixture for reconnect testing.' }
    Wait-HybridReaderCount -Path $InitialHybridPath -Minimum ($InitialReaderCount + 1)
    Wait-TranscoderCount -ContainerId $ContainerId -Expected 1

    $SceneResponse = Invoke-LocalRequest -Client $Client -Method ([Net.Http.HttpMethod]::Get) -Path '/api/v1/scene'
    Assert-True ($SceneResponse.Status -eq 200) 'Could not load the M3 lifecycle scene.'
    $Scene = $SceneResponse.Body | ConvertFrom-Json
    ($Scene.sources | Where-Object id -eq 'camera-hevc').rtspUrl = 'rtsp://mediamtx:8554/m0-test'
    ($Scene.sources | Where-Object id -eq 'camera-hevc').name = 'Switched H264'
    $Scene = Update-Scene -Client $Client -Scene $Scene
    [void](Wait-SourceClassification -Client $Client -SourceId 'camera-hevc' -Strategy passthrough -Codec h264)
    Wait-TranscoderCount -ContainerId $ContainerId -Expected 0

    ($Scene.sources | Where-Object id -eq 'camera-hevc').rtspUrl = 'rtsp://mediamtx:8554/m3-hevc'
    ($Scene.sources | Where-Object id -eq 'camera-hevc').name = 'Restored HEVC'
    $Scene = Update-Scene -Client $Client -Scene $Scene
    [void](Wait-SourceClassification -Client $Client -SourceId 'camera-hevc' -Strategy transcode -Codec hevc)
    Wait-TranscoderCount -ContainerId $ContainerId -Expected 1
    $RestoredLogs = Get-ProductLogs
    $HybridPaths = @([Regex]::Matches(
        $RestoredLogs,
        "is reading from path '(hybrid-[a-f0-9]{32})', 1 track \(H264\)"
    ) | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique)
    Assert-True ($HybridPaths.Count -ge 2 -and $HybridPaths -contains $InitialHybridPath) `
        'Restored HEVC source did not receive a fresh opaque Hybrid route.'

    $Scene.sources = @($Scene.sources | Where-Object id -ne 'camera-hevc')
    $Scene.items = @($Scene.items | Where-Object sourceId -ne 'camera-hevc')
    $Scene = Update-Scene -Client $Client -Scene $Scene
    $RemovalDeadline = [DateTime]::UtcNow.AddSeconds(30)
    do {
        $Capabilities = Get-Capabilities -Client $Client
        if ($Capabilities.sources.Count -eq 1 -and $Capabilities.sources[0].sourceId -eq 'camera-h264') { break }
        Start-Sleep -Milliseconds 500
    } while ([DateTime]::UtcNow -lt $RemovalDeadline)
    Assert-True ($Capabilities.sources.Count -eq 1 -and $Capabilities.sources[0].sourceId -eq 'camera-h264') `
        'Removed HEVC source remained in playback capabilities.'
    Wait-TranscoderCount -ContainerId $ContainerId -Expected 0
    $RemovedEndpoint = Invoke-LocalRequest -Client $Client -Method ([Net.Http.HttpMethod]::Post) `
        -Path '/api/v1/sources/camera-hevc/whep' -Body 'v=0' -ContentType 'application/sdp'
    Assert-True ($RemovedEndpoint.Status -eq 404) 'Removed source Direct endpoint must return 404.'
    Assert-True (-not $ChromeProcess.HasExited) 'Headless Chrome exited during M3 lifecycle mutations.'

    Close-ChromePage -DebugPort $ChromeDebugPort
    Stop-ChromeTree -Process $ChromeProcess
    $ChromeProcess.Dispose()
    $ChromeProcess = $null
    docker compose -f $ComposeFile stop -t 20 webobs-hybrid
    if ($LASTEXITCODE -ne 0) { throw 'M3 lifecycle product service did not stop cleanly.' }
    docker compose -f $ComposeFile run --rm `
        -e TEST_RECORDING="/artifacts/$ArtifactName" `
        -e TEST_MIN_DURATION=35 `
        -e TEST_MAX_DURATION=180 `
        -e TEST_REQUIRE_PILLARBOX=0 `
        -e TEST_REJECT_BLACKOUT=1 `
        validator
    if ($LASTEXITCODE -ne 0) { throw 'M3 lifecycle recording validation failed.' }
    Write-Host 'M3 live mutation, reconnect, route replacement, and cleanup acceptance passed.'
}
catch {
    Write-Warning 'M3 lifecycle acceptance failed; emitting product log tail for diagnosis.'
    docker compose -f $ComposeFile logs --no-color --tail 180 webobs-hybrid
    throw
}
finally {
    if ($null -ne $ChromeProcess) {
        Stop-ChromeTree -Process $ChromeProcess
        $ChromeProcess.Dispose()
    }
    $Client.Dispose()
    $Handler.Dispose()
    docker compose -f $ComposeFile down --volumes --remove-orphans
    $env:WEBOBS_HYBRID_RECORDING_NAME = $PreviousArtifactName
    Pop-Location
    $ResolvedProfile = [IO.Path]::GetFullPath($Profile)
    $ResolvedArtifacts = [IO.Path]::GetFullPath($ArtifactDirectory) + [IO.Path]::DirectorySeparatorChar
    if ($ResolvedProfile.StartsWith($ResolvedArtifacts, [StringComparison]::OrdinalIgnoreCase) -and
        (Test-Path -LiteralPath $ResolvedProfile)) {
        [IO.Directory]::Delete($ResolvedProfile, $true)
    }
}
