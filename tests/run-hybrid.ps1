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
$ArtifactName = 'hybrid-' + [Guid]::NewGuid().ToString('N') + '.mp4'
$Artifact = Join-Path $ArtifactDirectory $ArtifactName
$BaseUri = 'http://127.0.0.1:18083'

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

function Get-Capabilities {
    param([Net.Http.HttpClient]$Client)
    $Response = $Client.GetAsync("$BaseUri/api/v1/playback/capabilities").GetAwaiter().GetResult()
    try {
        if ([int]$Response.StatusCode -ne 200) { return $null }
        return ($Response.Content.ReadAsStringAsync().GetAwaiter().GetResult() | ConvertFrom-Json)
    } finally { $Response.Dispose() }
}

function Get-TranscoderCount {
    param([string]$ContainerId)
    $Value = @(& docker top $ContainerId -eo pid,comm)
    if ($LASTEXITCODE -ne 0) { throw 'Could not inspect Hybrid transcoder processes.' }
    return @($Value | Select-Object -Skip 1 | Where-Object {
        (($_.Trim() -split '\s+') | Select-Object -Last 1) -eq 'ffmpeg'
    }).Count
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
        throw 'Could not resolve the Hybrid browser page for a graceful close.'
    }
    Invoke-RestMethod -Uri "http://127.0.0.1:$DebugPort/json/close/$($Target.id)" -TimeoutSec 5 |
        Out-Null
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
$Profile = Join-Path $ArtifactDirectory ('chrome-hybrid-' + [Guid]::NewGuid().ToString('N'))
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
    if ($LASTEXITCODE -ne 0) { throw 'M3 deterministic Hybrid service failed to start.' }

    $Capabilities = $null
    $Deadline = [DateTime]::UtcNow.AddSeconds(75)
    while ([DateTime]::UtcNow -lt $Deadline) {
        try {
            $Capabilities = Get-Capabilities -Client $Client
            if ($null -ne $Capabilities) { break }
        } catch { Start-Sleep -Milliseconds 250 }
    }
    Assert-True ($null -ne $Capabilities -and $Capabilities.sources.Count -eq 2) `
        'M3 Hybrid capabilities did not become ready.'

    $ChromeArguments = @(
        '--headless=new', '--disable-gpu', '--disable-features=WebRtcHideLocalIpsWithMdns',
        '--no-first-run', '--no-default-browser-check', '--autoplay-policy=no-user-gesture-required',
        '--remote-debugging-address=127.0.0.1', "--remote-debugging-port=$ChromeDebugPort",
        "--user-data-dir=$Profile", "$BaseUri/#direct"
    )
    $ChromeProcess = Start-Process -FilePath $ChromePath -ArgumentList $ChromeArguments `
        -WindowStyle Hidden -PassThru

    $Classified = $false
    $ClassificationDeadline = [DateTime]::UtcNow.AddSeconds(45)
    while ([DateTime]::UtcNow -lt $ClassificationDeadline) {
        Start-Sleep -Milliseconds 500
        try {
            $Capabilities = Get-Capabilities -Client $Client
            $H264 = $Capabilities.sources | Where-Object sourceId -eq 'camera-h264'
            $Hevc = $Capabilities.sources | Where-Object sourceId -eq 'camera-hevc'
            if ($H264.strategy -eq 'passthrough' -and $H264.codec -eq 'h264' -and
                $Hevc.strategy -eq 'transcode' -and $Hevc.codec -eq 'hevc') {
                $Classified = $true
                break
            }
        } catch {}
    }
    $ClassificationSummary = @($Capabilities.sources | ForEach-Object {
        "$($_.sourceId)=$($_.strategy)/$($_.codec)"
    }) -join ', '
    Assert-True $Classified `
        "M3 did not classify H.264 as passthrough and HEVC as transcode ($ClassificationSummary)."
    Start-Sleep -Seconds 12
    Assert-True (-not $ChromeProcess.HasExited) 'Headless Chrome exited before Hybrid playback completed.'

    $ContainerId = (@(& docker compose -f $ComposeFile ps -q webobs-hybrid) -join '').Trim()
    Assert-True (-not [string]::IsNullOrWhiteSpace($ContainerId)) 'Could not resolve the Hybrid product container.'
    Assert-True ((Get-TranscoderCount -ContainerId $ContainerId) -eq 1) `
        'Hybrid mode must run exactly one transcoder for the one incompatible source.'

    $Logs = docker compose -f $ComposeFile logs --no-color webobs-hybrid | Out-String
    Assert-True ($LASTEXITCODE -eq 0) 'Could not read M3 Hybrid logs.'
    Assert-True ($Logs -match "is reading from path 'direct-[a-f0-9]{32}', 1 track \(H264\)") `
        'Compatible H.264 source did not use a Direct WHEP reader.'
    Assert-True ($Logs -match "is reading from path 'hybrid-[a-f0-9]{32}', 1 track \(H264\)") `
        'Incompatible HEVC source did not use a transcoded H.264 WHEP reader.'
    Assert-True ($Logs -notmatch 'rtsp://[^/\s]+:[^@/\s]+@') 'Hybrid logs must not expose RTSP credentials.'

    Close-ChromePage -DebugPort $ChromeDebugPort
    $CleanupDeadline = [DateTime]::UtcNow.AddSeconds(25)
    do {
        Start-Sleep -Seconds 1
        $TranscoderCount = Get-TranscoderCount -ContainerId $ContainerId
    } while ($TranscoderCount -ne 0 -and [DateTime]::UtcNow -lt $CleanupDeadline)
    Assert-True ($TranscoderCount -eq 0) `
        'On-demand Hybrid transcoder did not exit after its last browser page closed.'
    Stop-ChromeTree -Process $ChromeProcess
    $ChromeProcess.Dispose()
    $ChromeProcess = $null

    docker compose -f $ComposeFile stop -t 20 webobs-hybrid
    if ($LASTEXITCODE -ne 0) { throw 'M3 Hybrid service did not stop cleanly.' }
    docker compose -f $ComposeFile run --rm `
        -e TEST_RECORDING="/artifacts/$ArtifactName" `
        -e TEST_MIN_DURATION=20 `
        -e TEST_MAX_DURATION=75 `
        -e TEST_REQUIRE_PILLARBOX=0 `
        -e TEST_REJECT_BLACKOUT=1 `
        validator
    if ($LASTEXITCODE -ne 0) { throw 'M3 Hybrid regression recording validation failed.' }
    Write-Host 'M3 selective Hybrid passthrough/transcode acceptance passed.'
}
catch {
    Write-Warning 'M3 Hybrid acceptance failed; emitting synthetic fixture logs for diagnosis.'
    docker compose -f $ComposeFile logs --no-color --tail 200 webobs-hybrid fixture-hevc
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
