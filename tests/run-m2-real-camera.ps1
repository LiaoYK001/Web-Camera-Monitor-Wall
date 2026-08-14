[CmdletBinding()]
param(
    [switch]$SkipBuild,
    [string]$EnvFile,
    [string]$ChromePath = $env:WEBOBS_CHROME_BIN,
    [ValidateRange(30, 3600)]
    [int]$DurationSeconds = 30,
    [ValidateRange(16, 8192)]
    [int]$Width = 1920,
    [ValidateRange(16, 8192)]
    [int]$Height = 1080,
    [ValidateRange(1, 120)]
    [int]$Fps = 30,
    [ValidateRange(50, 100000)]
    [int]$BitrateKbps = 6000,
    [ValidateRange(1, 300)]
    [int]$ConnectTimeoutSeconds = 20,
    [ValidateSet('tcp', 'udp')]
    [string]$RtspTransport = 'tcp',
    [ValidateSet('composite', 'direct')]
    [string]$PlaybackMode = 'composite',
    [switch]$RequireAudio
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false

$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ProductComposeFile = Join-Path $RepositoryRoot 'compose.yaml'
$TestComposeFile = Join-Path $PSScriptRoot 'compose.smoke.yaml'
$RecordingDirectory = Join-Path $RepositoryRoot 'recordings'
$ArtifactDirectory = Join-Path $PSScriptRoot 'artifacts'
$BaseUri = 'http://127.0.0.1:8080'
$Milestone = if ($RequireAudio) { 'M5' } elseif ($PlaybackMode -eq 'direct') { 'M3' } else { 'M2' }
$RecordingPrefix = if ($RequireAudio) {
    "m5-real-audio-$PlaybackMode"
} elseif ($PlaybackMode -eq 'direct') {
    'm3-real-camera'
} else {
    'm2-real-camera'
}

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

function Get-ContainerLogText {
    param([string]$Id)

    $PreviousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $Lines = @(& docker logs $Id 2>&1 | ForEach-Object { $_.ToString() })
        $Status = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $PreviousPreference
    }
    if ($Status -ne 0) { throw "Could not read the $Milestone product log." }
    return $Lines -join "`n"
}

function Get-DotEnvValue {
    param([string]$Path, [string]$Name)
    $Pattern = '^\s*' + [Regex]::Escape($Name) + '\s*=(.*)$'
    foreach ($RawLine in [IO.File]::ReadLines($Path)) {
        if ($RawLine.TrimStart().StartsWith('#')) { continue }
        $Match = [Regex]::Match($RawLine, $Pattern)
        if (-not $Match.Success) { continue }
        $Value = $Match.Groups[1].Value.Trim()
        if ($Value.Length -ge 2 -and
            (($Value[0] -eq '"' -and $Value[$Value.Length - 1] -eq '"') -or
             ($Value[0] -eq "'" -and $Value[$Value.Length - 1] -eq "'"))) {
            $Value = $Value.Substring(1, $Value.Length - 2)
        }
        return $Value
    }
    return $null
}

if (($Width % 2) -ne 0 -or ($Height % 2) -ne 0) { throw 'Width and height must both be even.' }

if (-not [string]::IsNullOrWhiteSpace($EnvFile)) {
    if (-not [IO.Path]::IsPathRooted($EnvFile)) { $EnvFile = Join-Path $RepositoryRoot $EnvFile }
    if (-not (Test-Path -LiteralPath $EnvFile -PathType Leaf)) {
        throw 'The selected local environment file was not found.'
    }
    $EnvFile = (Resolve-Path -LiteralPath $EnvFile).Path
    $RtspUrl = Get-DotEnvValue -Path $EnvFile -Name 'WEBOBS_RTSP_URL'
}
elseif (-not [string]::IsNullOrWhiteSpace($env:WEBOBS_RTSP_URL)) {
    $RtspUrl = $env:WEBOBS_RTSP_URL
}
else {
    $EnvFile = Join-Path $RepositoryRoot '.env'
    if (-not (Test-Path -LiteralPath $EnvFile -PathType Leaf)) {
        throw 'WEBOBS_RTSP_URL is not set and the local .env file was not found.'
    }
    $RtspUrl = Get-DotEnvValue -Path $EnvFile -Name 'WEBOBS_RTSP_URL'
}
if ([string]::IsNullOrWhiteSpace($RtspUrl) -or $RtspUrl.Contains('${')) {
    throw "$Milestone real-camera acceptance requires a literal WEBOBS_RTSP_URL."
}
try { $ParsedRtspUrl = [Uri]$RtspUrl }
catch { throw 'WEBOBS_RTSP_URL is not a valid absolute URI.' }
if (-not $ParsedRtspUrl.IsAbsoluteUri -or $ParsedRtspUrl.Scheme -notin @('rtsp', 'rtsps')) {
    throw 'WEBOBS_RTSP_URL must be an absolute rtsp:// or rtsps:// URI.'
}

$CredentialTokens = [Collections.Generic.List[string]]::new()
if (-not [string]::IsNullOrEmpty($ParsedRtspUrl.UserInfo)) {
    $CredentialTokens.Add($ParsedRtspUrl.UserInfo)
    try {
        $Decoded = [Uri]::UnescapeDataString($ParsedRtspUrl.UserInfo)
        if ($Decoded -ne $ParsedRtspUrl.UserInfo) { $CredentialTokens.Add($Decoded) }
    } catch {}
    $Separator = $ParsedRtspUrl.UserInfo.IndexOf(':')
    if ($Separator -ge 0) {
        $Username = $ParsedRtspUrl.UserInfo.Substring(0, $Separator)
        $Password = $ParsedRtspUrl.UserInfo.Substring($Separator + 1)
        if ($Username.Length -ge 4) { $CredentialTokens.Add($Username) }
        if ($Password.Length -ge 4) { $CredentialTokens.Add($Password) }
    }
}

function Test-CredentialLeak {
    param([string]$Text)
    if ([Regex]::IsMatch($Text, '(?i)\brtsps?://(?!(?:\*{3}:\*{3})@)[^\s/@]+(?::[^\s/@]*)?@')) {
        return $true
    }
    foreach ($Token in $CredentialTokens) {
        if (-not [string]::IsNullOrEmpty($Token) -and
            $Text.IndexOf($Token, [StringComparison]::Ordinal) -ge 0) { return $true }
    }
    return $false
}

function Protect-RealCameraLog {
    param([string]$Text)
    $Safe = [Regex]::Replace($Text, '(?i)\brtsps?://[^\s''"]+', 'rtsp://<redacted>')
    foreach ($Token in $CredentialTokens) {
        if (-not [string]::IsNullOrEmpty($Token)) { $Safe = $Safe.Replace($Token, '***') }
    }
    return $Safe
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

& (Join-Path $PSScriptRoot 'run-public-audit.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Public-repository audit failed.' }
Get-Command docker -ErrorAction Stop | Out-Null
docker compose version | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Docker Compose is unavailable.' }

New-Item -ItemType Directory -Force -Path $RecordingDirectory, $ArtifactDirectory | Out-Null
$Timestamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
$RecordingName = "$RecordingPrefix-$Timestamp.mp4"
$RecordingPath = Join-Path $RecordingDirectory $RecordingName
$LogPath = Join-Path $ArtifactDirectory "$RecordingPrefix-$Timestamp.log"
$Profile = Join-Path $ArtifactDirectory ("chrome-$RecordingPrefix-" + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $Profile | Out-Null
$ProjectName = ("webobs-$RecordingPrefix-$Timestamp").ToLowerInvariant()

$ManagedEnvironment = @{
    WEBOBS_RTSP_URL = $RtspUrl
    WEBOBS_OUTPUT = "/recordings/$RecordingName"
    WEBOBS_DURATION_SECONDS = '0'
    WEBOBS_WIDTH = $Width.ToString()
    WEBOBS_HEIGHT = $Height.ToString()
    WEBOBS_FPS = $Fps.ToString()
    WEBOBS_BITRATE_KBPS = $BitrateKbps.ToString()
    WEBOBS_CONNECT_TIMEOUT_SECONDS = $ConnectTimeoutSeconds.ToString()
    WEBOBS_RTSP_TRANSPORT = $RtspTransport
    WEBOBS_WEBRTC_ENABLED = 'true'
}
$PreviousEnvironment = @{}
foreach ($Name in $ManagedEnvironment.Keys) {
    $Existing = Get-Item -LiteralPath "Env:$Name" -ErrorAction SilentlyContinue
    $PreviousEnvironment[$Name] = [PSCustomObject]@{
        Exists = $null -ne $Existing
        Value = if ($null -ne $Existing) { $Existing.Value } else { $null }
    }
    Set-Item -LiteralPath "Env:$Name" -Value $ManagedEnvironment[$Name]
}

$ComposeArguments = @('compose', '-p', $ProjectName, '-f', $ProductComposeFile)
$ContainerId = $null
$ChromeProcess = $null
$RawLog = $null

Push-Location $RepositoryRoot
try {
    if (-not $SkipBuild) {
        & docker @ComposeArguments build webobs
        if ($LASTEXITCODE -ne 0) { throw 'Could not build the product image.' }
        docker compose -f $TestComposeFile build validator
        if ($LASTEXITCODE -ne 0) { throw 'Could not build the recording validator image.' }
    }

    & docker @ComposeArguments up --no-build -d webobs
    if ($LASTEXITCODE -ne 0) { throw "Could not start the isolated $Milestone product container." }
    $ContainerId = (@(& docker @ComposeArguments ps -q webobs) -join '').Trim()
    if ([string]::IsNullOrWhiteSpace($ContainerId)) { throw "Could not resolve the $Milestone product container ID." }

    $Ready = $false
    $Deadline = [DateTime]::UtcNow.AddSeconds($ConnectTimeoutSeconds + 45)
    while ([DateTime]::UtcNow -lt $Deadline) {
        try {
            if ($PlaybackMode -eq 'direct') {
                $CapabilityResponse = Invoke-WebRequest -UseBasicParsing `
                    -Uri "$BaseUri/api/v1/playback/capabilities" -TimeoutSec 2
                Assert-True ($CapabilityResponse.Content -notmatch 'rtsp://|(?:direct|hybrid)-[a-f0-9]{32}|mediamtx') `
                    'M3 real-camera capabilities exposed an RTSP or internal endpoint.'
                $Capabilities = $CapabilityResponse.Content | ConvertFrom-Json
                $Capability = $Capabilities.sources | Where-Object sourceId -eq 'camera-1'
                if ($Capabilities.modes.direct.enabled -eq $true -and
                    $Capability.endpoint -eq '/api/v1/sources/camera-1/whep') {
                    $Ready = $true
                    break
                }
            } else {
                $Status = Invoke-RestMethod -Uri "$BaseUri/api/v1/program/status" -TimeoutSec 2
                if ($Status.enabled -eq $true -and $Status.endpoint -eq '/api/v1/program/whep') {
                    $Ready = $true
                    break
                }
            }
        } catch { Start-Sleep -Milliseconds 250 }
    }
    Assert-True $Ready "$Milestone product did not expose the expected same-origin playback endpoint."

    if ($RequireAudio) {
        $AudioUpdateStage = 'scene GET'
        try {
            $SceneResponse = Invoke-WebRequest -UseBasicParsing -Uri "$BaseUri/api/v1/scene" -TimeoutSec 5
            $AudioUpdateStage = 'scene validation'
            $Scene = $SceneResponse.Content | ConvertFrom-Json
            Assert-True (@($Scene.sources).Count -eq 1) 'M5 real-audio acceptance requires one bootstrap source.'
            $Scene.sources[0].muted = $false
            $Scene.sources[0].volume = 1.0
            $Scene.sources[0].syncOffsetMs = 0
            $Scene.sources[0].monitoring = 'off'
            $Scene.sources[0].audioTrack = 1
            $ETag = [string]$SceneResponse.Headers['ETag']
            Assert-True (-not [string]::IsNullOrWhiteSpace($ETag)) 'M5 scene response did not include an ETag.'
            $Headers = @{
                'If-Match' = $ETag
                'Origin' = $BaseUri
            }
            $AudioUpdateStage = 'scene PUT'
            $UpdatedScene = Invoke-WebRequest -UseBasicParsing -Method Put `
                -Uri "$BaseUri/api/v1/scene" -Headers $Headers -ContentType 'application/json' `
                -Body ($Scene | ConvertTo-Json -Depth 12 -Compress) -TimeoutSec ($ConnectTimeoutSeconds + 10)
            Assert-True ($UpdatedScene.StatusCode -eq 200) 'M5 could not enable the real source audio.'
        }
        catch {
            throw "M5 could not enable the real source audio at $AudioUpdateStage; endpoint-bearing diagnostics were suppressed."
        }
    }

    $ChromeArguments = @(
        '--headless=new', '--disable-gpu', '--disable-features=WebRtcHideLocalIpsWithMdns',
        '--no-first-run', '--no-default-browser-check', '--autoplay-policy=no-user-gesture-required',
        "--user-data-dir=$Profile", $(if ($PlaybackMode -eq 'direct') { "$BaseUri/#direct" } else { "$BaseUri/" })
    )
    $ChromeProcess = Start-Process -FilePath $ChromePath -ArgumentList $ChromeArguments `
        -WindowStyle Hidden -PassThru
    Start-Sleep -Seconds $DurationSeconds
    Assert-True (-not $ChromeProcess.HasExited) "Headless Chrome exited before $Milestone real-camera playback completed."

    $RawLog = Get-ContainerLogText -Id $ContainerId
    if ($PlaybackMode -eq 'direct') {
        $CapabilityResponse = Invoke-WebRequest -UseBasicParsing `
            -Uri "$BaseUri/api/v1/playback/capabilities" -TimeoutSec 5
        Assert-True ($CapabilityResponse.Content -notmatch 'rtsp://|(?:direct|hybrid)-[a-f0-9]{32}|mediamtx') `
            'M3 real-camera capabilities exposed an RTSP or internal endpoint.'
        $Capabilities = $CapabilityResponse.Content | ConvertFrom-Json
        $Capability = $Capabilities.sources | Where-Object sourceId -eq 'camera-1'
        Assert-True ($Capability.strategy -in @('passthrough', 'transcode') -and
            -not [string]::IsNullOrWhiteSpace($Capability.codec)) `
            'M3 real-camera source was not classified for Direct/Hybrid playback.'
        if ($RequireAudio) {
            Assert-True (-not [string]::IsNullOrWhiteSpace($Capability.audioCodec)) `
                'M5 real-camera source did not expose a classified audio codec.'
        }
        $ExpectedPath = if ($Capability.strategy -eq 'transcode') { 'hybrid' } else { 'direct' }
        $ExpectedTracks = if ($RequireAudio) {
            "2 tracks \((?:H264, Opus|Opus, H264)\)"
        } else {
            "(?:1 track \(H264\)|2 tracks \((?:H264, Opus|Opus, H264)\))"
        }
        Assert-True ($RawLog -match "is reading from path '$ExpectedPath-[a-f0-9]{32}', $ExpectedTracks") `
            'Chrome did not establish the classified source-scoped H.264[/Opus] WHEP reader.'
    } else {
        Assert-True ($RawLog -match "is reading from path 'program', 2 tracks \((?:H264, Opus|Opus, H264)\)") `
            'Chrome did not establish an H.264/Opus program WHEP reader for the real source.'
    }
    if (Test-CredentialLeak -Text $RawLog) {
        throw 'Credential redaction failed; raw output was suppressed.'
    }

    Stop-Process -Id $ChromeProcess.Id -Force -ErrorAction SilentlyContinue
    $ChromeProcess.WaitForExit(5000) | Out-Null
    $ChromeProcess.Dispose()
    $ChromeProcess = $null

    & docker @ComposeArguments stop webobs
    if ($LASTEXITCODE -ne 0) { throw "The $Milestone product container did not stop cleanly." }
    $ExitCode = (@(& docker inspect --format '{{.State.ExitCode}}' $ContainerId) -join '').Trim()
    Assert-True ($LASTEXITCODE -eq 0 -and $ExitCode -eq '0') "$Milestone product process returned a non-zero status."

    $RawLog = Get-ContainerLogText -Id $ContainerId
    if (Test-CredentialLeak -Text $RawLog) { throw 'Credential redaction failed; raw output was suppressed.' }
    [IO.File]::WriteAllText($LogPath, (Protect-RealCameraLog -Text $RawLog) + "`n",
                            [Text.UTF8Encoding]::new($false))

    Assert-True ((Test-Path -LiteralPath $RecordingPath -PathType Leaf) -and
        (Get-Item -LiteralPath $RecordingPath).Length -gt 0) 'The M2 real-camera recording is missing or empty.'
    $Mount = "type=bind,source=$RecordingDirectory,target=/artifacts,readonly"
    $ValidatorArguments = @(
        'run', '--rm', '--mount', $Mount,
        '--entrypoint', '/usr/local/bin/probe-recording',
        '-e', "TEST_RECORDING=/artifacts/$RecordingName",
        '-e', "TEST_DIMENSIONS=${Width}x${Height}",
        '-e', "TEST_FRAME_RATE=$Fps/1",
        '-e', "TEST_MIN_DURATION=$DurationSeconds",
        '-e', "TEST_MAX_DURATION=$($DurationSeconds + 45)",
        '-e', 'TEST_REJECT_BLACKOUT=1',
        '-e', 'TEST_BLACKOUT_YAVG_MAX=16.5'
    )
    if ($RequireAudio) {
        $ValidatorArguments += @('-e', 'TEST_REQUIRE_AUDIBLE=1', '-e', 'TEST_MIN_MEAN_VOLUME_DB=-80')
    }
    $ValidatorArguments += 'webobs-m0-rtsp-fixture:local'
    & docker @ValidatorArguments
    if ($LASTEXITCODE -ne 0) { throw "$Milestone real-camera recording validation failed." }

    Write-Host "$Milestone real-camera $PlaybackMode WebRTC acceptance passed. Recording: $RecordingPath"
    Write-Host "Endpoint-redacted local log (do not attach publicly): $LogPath"
}
finally {
    if ($null -ne $ChromeProcess) {
        if (-not $ChromeProcess.HasExited) { Stop-Process -Id $ChromeProcess.Id -Force -ErrorAction SilentlyContinue }
        $ChromeProcess.Dispose()
    }
    & docker @ComposeArguments down --volumes --remove-orphans | Out-Null
    Pop-Location
    foreach ($Name in $ManagedEnvironment.Keys) {
        if ($PreviousEnvironment[$Name].Exists) {
            Set-Item -LiteralPath "Env:$Name" -Value $PreviousEnvironment[$Name].Value
        } else {
            Remove-Item -LiteralPath "Env:$Name" -ErrorAction SilentlyContinue
        }
    }
    $ResolvedProfile = [IO.Path]::GetFullPath($Profile)
    $ResolvedArtifacts = [IO.Path]::GetFullPath($ArtifactDirectory) + [IO.Path]::DirectorySeparatorChar
    if ($ResolvedProfile.StartsWith($ResolvedArtifacts, [StringComparison]::OrdinalIgnoreCase) -and
        (Test-Path -LiteralPath $ResolvedProfile)) {
        [IO.Directory]::Delete($ResolvedProfile, $true)
    }
}
