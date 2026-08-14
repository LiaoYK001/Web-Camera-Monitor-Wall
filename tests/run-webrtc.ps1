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
$Artifact = Join-Path $ArtifactDirectory 'webrtc.mp4'
$BaseUri = 'http://127.0.0.1:18081'
$LocalOrigin = 'http://127.0.0.1:18081'

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

function Invoke-WhepRequest {
    param(
        [Net.Http.HttpClient]$Client,
        [Net.Http.HttpMethod]$Method,
        [string]$Path,
        [AllowNull()][string]$Body = $null,
        [string]$ContentType = 'application/sdp',
        [hashtable]$Headers = @{}
    )
    $request = [Net.Http.HttpRequestMessage]::new($Method, "$BaseUri$Path")
    try {
        if ($PSBoundParameters.ContainsKey('Body')) {
            $request.Content = [Net.Http.StringContent]::new($Body, [Text.Encoding]::UTF8, $ContentType)
        }
        foreach ($entry in $Headers.GetEnumerator()) {
            [void]$request.Headers.TryAddWithoutValidation($entry.Key, $entry.Value)
        }
        $response = $Client.SendAsync($request).GetAwaiter().GetResult()
        try {
            return [PSCustomObject]@{
                Status = [int]$response.StatusCode
                Body = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
                Headers = $response.Headers
            }
        } finally {
            $response.Dispose()
        }
    } finally {
        $request.Dispose()
    }
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
    throw 'Chrome was not found; set WEBOBS_CHROME_BIN to a trusted Chrome executable'
}

New-Item -ItemType Directory -Force -Path $ArtifactDirectory | Out-Null
$Profile = Join-Path $ArtifactDirectory ('chrome-whep-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $Profile | Out-Null

$Handler = [Net.Http.HttpClientHandler]::new()
$Handler.UseProxy = $false
$Client = [Net.Http.HttpClient]::new($Handler)
$Client.Timeout = [TimeSpan]::FromSeconds(20)

Push-Location $RepositoryRoot
try {
    docker compose -f $ComposeFile down --volumes --remove-orphans
    if (Test-Path -LiteralPath $Artifact) { Remove-Item -LiteralPath $Artifact -Force }
    $BuildOption = if ($SkipBuild) { '--no-build' } else { '--build' }
    docker compose -f $ComposeFile up $BuildOption -d mediamtx fixture
    if ($LASTEXITCODE -ne 0) { throw 'M2 RTSP fixtures failed to start' }

    $FixtureReady = $false
    $FixtureDeadline = [DateTime]::UtcNow.AddSeconds(45)
    while ([DateTime]::UtcNow -lt $FixtureDeadline) {
        $FixtureLogs = docker compose -f $ComposeFile logs --no-color mediamtx | Out-String
        if ($FixtureLogs -match "is publishing to path 'm0-test'") {
            $FixtureReady = $true
            break
        }
        Start-Sleep -Milliseconds 250
    }
    Assert-True $FixtureReady 'Synthetic RTSP fixture did not publish before the M2 deadline'

    $WhipFailureArtifact = Join-Path $ArtifactDirectory 'whip-failure.mp4'
    if (Test-Path -LiteralPath $WhipFailureArtifact) { Remove-Item -LiteralPath $WhipFailureArtifact -Force }
    docker compose -f $ComposeFile run --rm `
        -e WEBOBS_WHIP_URL=http://127.0.0.1:9/program/whip `
        -e WEBOBS_CONNECT_TIMEOUT_SECONDS=8 `
        -e WEBOBS_OUTPUT=/artifacts/whip-failure.mp4 `
        webobs-webrtc
    Assert-True ($LASTEXITCODE -eq 5) 'Unreachable WHIP signaling must return the output-failure exit code'
    Assert-True (-not (Test-Path -LiteralPath $WhipFailureArtifact)) `
        'Unreachable WHIP signaling must not produce a successful MP4'
    $WhipTemporary = Get-ChildItem -LiteralPath $ArtifactDirectory -Filter '.whip-failure.mp4.webobsd-*.mkv' `
        -File -ErrorAction SilentlyContinue
    Assert-True ($null -eq $WhipTemporary) 'Unreachable WHIP signaling must remove its temporary muxer file'

    docker compose -f $ComposeFile up $BuildOption -d webobs-webrtc
    if ($LASTEXITCODE -ne 0) { throw 'M2 WebRTC product service failed to start' }

    $Status = $null
    $Deadline = [DateTime]::UtcNow.AddSeconds(60)
    while ([DateTime]::UtcNow -lt $Deadline) {
        try {
            $Candidate = Invoke-WhepRequest -Client $Client -Method ([Net.Http.HttpMethod]::Get) -Path '/api/v1/program/status'
            if ($Candidate.Status -eq 200) {
                $Status = $Candidate
                break
            }
        } catch {
            Start-Sleep -Milliseconds 250
        }
    }
    Assert-True ($null -ne $Status) 'M2 program status endpoint did not become ready'
    $StatusBody = $Status.Body | ConvertFrom-Json
    Assert-True ($StatusBody.enabled -eq $true) 'M2 deterministic service must enable WebRTC'
    Assert-True ($StatusBody.endpoint -eq '/api/v1/program/whep') 'Browser must receive only the same-origin WHEP route'

    $WrongType = Invoke-WhepRequest -Client $Client -Method ([Net.Http.HttpMethod]::Post) `
        -Path '/api/v1/program/whep' -Body '{}' -ContentType 'application/json'
    Assert-True ($WrongType.Status -eq 415) 'WHEP must reject non-SDP request bodies'

    $WrongOrigin = Invoke-WhepRequest -Client $Client -Method ([Net.Http.HttpMethod]::Post) `
        -Path '/api/v1/program/whep' -Body 'v=0' -Headers @{ Origin = 'http://example.invalid' }
    Assert-True ($WrongOrigin.Status -eq 403) 'WHEP must reject cross-origin offers'

    $Oversized = Invoke-WhepRequest -Client $Client -Method ([Net.Http.HttpMethod]::Post) `
        -Path '/api/v1/program/whep' -Body ('v=0' + ('a' * 65534)) -Headers @{ Origin = $LocalOrigin }
    Assert-True ($Oversized.Status -eq 413) 'WHEP must enforce its 64 KiB SDP limit'

    $Forged = Invoke-WhepRequest -Client $Client -Method ([Net.Http.HttpMethod]::Delete) `
        -Path '/api/v1/program/whep/session/00000000000000000000000000000000'
    Assert-True ($Forged.Status -eq 404) 'WHEP must reject unknown opaque session tokens'

    # Keep an isolated Chrome process alive in real time while its recvonly peer
    # gathers ICE and decodes the H.264 program. Virtual-time mode would
    # incorrectly fast-forward the browser's ICE timeout before network callbacks
    # can complete.
    $ChromeArguments = @(
        '--headless=new',
        '--disable-gpu',
        '--disable-features=WebRtcHideLocalIpsWithMdns',
        '--no-first-run',
        '--no-default-browser-check',
        '--autoplay-policy=no-user-gesture-required',
        "--user-data-dir=$Profile",
        "$BaseUri/"
    )
    $ChromeProcess = Start-Process -FilePath $ChromePath -ArgumentList $ChromeArguments `
        -WindowStyle Hidden -PassThru
    try {
        Start-Sleep -Seconds 20
        Assert-True (-not $ChromeProcess.HasExited) 'Headless Chrome exited before WHEP playback could be observed'

        $InitialLogs = docker compose -f $ComposeFile logs --no-color webobs-webrtc | Out-String
        Assert-True ($LASTEXITCODE -eq 0) 'Could not read the initial M2 WebRTC service logs'
        Assert-True ($InitialLogs -match "is reading from path 'program', 2 tracks \((?:H264, Opus|Opus, H264)\)") `
            'Chrome did not establish its initial H.264/Opus WHEP reader session'

        docker compose -f $ComposeFile stop -t 20 webobs-webrtc
        if ($LASTEXITCODE -ne 0) { throw 'M2 WebRTC service did not stop for the reconnect test' }
        if (Test-Path -LiteralPath $Artifact) { Remove-Item -LiteralPath $Artifact -Force }
        docker compose -f $ComposeFile start webobs-webrtc
        if ($LASTEXITCODE -ne 0) { throw 'M2 WebRTC service did not restart for the reconnect test' }

        $RestartReady = $false
        $RestartDeadline = [DateTime]::UtcNow.AddSeconds(60)
        while ([DateTime]::UtcNow -lt $RestartDeadline) {
            try {
                $RestartStatus = Invoke-WhepRequest -Client $Client -Method ([Net.Http.HttpMethod]::Get) `
                    -Path '/api/v1/program/status'
                if ($RestartStatus.Status -eq 200) {
                    $RestartReady = $true
                    break
                }
            } catch {
                Start-Sleep -Milliseconds 250
            }
        }
        Assert-True $RestartReady 'M2 program endpoint did not return after a product restart'
        Start-Sleep -Seconds 20
        Assert-True (-not $ChromeProcess.HasExited) 'Headless Chrome exited before automatic reconnect completed'
    } finally {
        if (-not $ChromeProcess.HasExited) {
            Stop-Process -Id $ChromeProcess.Id -Force -ErrorAction SilentlyContinue
            $ChromeProcess.WaitForExit(5000) | Out-Null
        }
        $ChromeProcess.Dispose()
    }

    $Logs = docker compose -f $ComposeFile logs --no-color webobs-webrtc | Out-String
    Assert-True ($LASTEXITCODE -eq 0) 'Could not read M2 WebRTC service logs'
    $ReaderSessions = [Regex]::Matches($Logs, "is reading from path 'program', 2 tracks \((?:H264, Opus|Opus, H264)\)").Count
    Assert-True ($ReaderSessions -ge 2) 'Chrome did not reconnect WHEP after the product restart'
    Assert-True ($Logs -notmatch 'rtsp://[^/\s]+:[^@/\s]+@') 'Runtime logs must not expose RTSP credentials'

    docker compose -f $ComposeFile stop -t 20 webobs-webrtc
    if ($LASTEXITCODE -ne 0) { throw 'M2 WebRTC service did not stop cleanly' }
    docker compose -f $ComposeFile run --rm `
        -e TEST_RECORDING=/artifacts/webrtc.mp4 `
        -e TEST_MIN_DURATION=15 `
        -e TEST_MAX_DURATION=45 `
        -e TEST_REQUIRE_PILLARBOX=1 `
        validator
    if ($LASTEXITCODE -ne 0) { throw 'M2 WebRTC recording validation failed' }
}
finally {
    $Client.Dispose()
    $Handler.Dispose()
    docker compose -f $ComposeFile down --volumes --remove-orphans
    Pop-Location
    $ResolvedProfile = [IO.Path]::GetFullPath($Profile)
    $ResolvedArtifacts = [IO.Path]::GetFullPath($ArtifactDirectory) + [IO.Path]::DirectorySeparatorChar
    if ($ResolvedProfile.StartsWith($ResolvedArtifacts, [StringComparison]::OrdinalIgnoreCase) -and
        (Test-Path -LiteralPath $ResolvedProfile)) {
        [IO.Directory]::Delete($ResolvedProfile, $true)
    }
}
