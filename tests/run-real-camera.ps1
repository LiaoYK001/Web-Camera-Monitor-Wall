[CmdletBinding()]
param(
    [switch]$SkipBuild,
    [string]$EnvFile,
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
    [string]$RtspTransport = 'tcp'
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false

$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ComposeFile = Join-Path $RepositoryRoot 'compose.yaml'
$SmokeComposeFile = Join-Path $PSScriptRoot 'compose.smoke.yaml'
$RecordingDirectory = Join-Path $RepositoryRoot 'recordings'
$ArtifactDirectory = Join-Path $PSScriptRoot 'artifacts'
$PlaceholderUrl = 'rtsp://user:password@192.168.1.10:554/stream'

function Get-DotEnvValue {
    param(
        [string]$Path,
        [string]$Name
    )

    $pattern = '^\s*' + [Regex]::Escape($Name) + '\s*=(.*)$'
    foreach ($rawLine in [IO.File]::ReadLines($Path)) {
        if ($rawLine.TrimStart().StartsWith('#')) { continue }
        $match = [Regex]::Match($rawLine, $pattern)
        if (-not $match.Success) { continue }

        $value = $match.Groups[1].Value.Trim()
        if ($value.Length -ge 2) {
            $first = $value[0]
            $last = $value[$value.Length - 1]
            if (($first -eq '"' -and $last -eq '"') -or ($first -eq "'" -and $last -eq "'")) {
                $value = $value.Substring(1, $value.Length - 2)
            }
        }
        return $value
    }
    return $null
}

if (($Width % 2) -ne 0 -or ($Height % 2) -ne 0) {
    throw 'Width and height must both be even.'
}

if ([string]::IsNullOrWhiteSpace($EnvFile)) {
    $EnvFile = Join-Path $RepositoryRoot '.env'
}
elseif (-not [IO.Path]::IsPathRooted($EnvFile)) {
    $EnvFile = Join-Path $RepositoryRoot $EnvFile
}

if (-not (Test-Path -LiteralPath $EnvFile -PathType Leaf)) {
    throw "Local environment file not found. Copy .env.example to .env and edit it before running this test."
}
$EnvFile = (Resolve-Path -LiteralPath $EnvFile).Path

$RtspUrl = Get-DotEnvValue -Path $EnvFile -Name 'WEBOBS_RTSP_URL'
if ([string]::IsNullOrWhiteSpace($RtspUrl)) {
    throw 'WEBOBS_RTSP_URL is missing from the selected environment file.'
}
if ($RtspUrl -eq $PlaceholderUrl) {
    throw 'WEBOBS_RTSP_URL still contains the .env.example placeholder.'
}
if ($RtspUrl.Contains('${')) {
    throw 'The real-camera runner requires WEBOBS_RTSP_URL to be a literal value, not an interpolation.'
}

try {
    $ParsedRtspUrl = [Uri]$RtspUrl
}
catch {
    throw 'WEBOBS_RTSP_URL is not a valid absolute URI.'
}
if (-not $ParsedRtspUrl.IsAbsoluteUri -or $ParsedRtspUrl.Scheme -notin @('rtsp', 'rtsps')) {
    throw 'WEBOBS_RTSP_URL must be an absolute rtsp:// or rtsps:// URI.'
}

$CredentialTokens = [Collections.Generic.List[string]]::new()
if (-not [string]::IsNullOrEmpty($ParsedRtspUrl.UserInfo)) {
    $CredentialTokens.Add($ParsedRtspUrl.UserInfo)
    try {
        $decodedUserInfo = [Uri]::UnescapeDataString($ParsedRtspUrl.UserInfo)
        if ($decodedUserInfo -ne $ParsedRtspUrl.UserInfo) {
            $CredentialTokens.Add($decodedUserInfo)
        }
    }
    catch {
        # The URI itself is already valid; generic URL detection remains active.
    }

    $separator = $ParsedRtspUrl.UserInfo.IndexOf(':')
    if ($separator -ge 0) {
        $username = $ParsedRtspUrl.UserInfo.Substring(0, $separator)
        $password = $ParsedRtspUrl.UserInfo.Substring($separator + 1)
        if ($username.Length -ge 4) { $CredentialTokens.Add($username) }
        if ($password.Length -ge 4) { $CredentialTokens.Add($password) }
    }
}

function Protect-LogLine {
    param([string]$Line)

    $safeLine = [Regex]::Replace(
        $Line,
        '(?i)\b(rtsps?://)[^\s/@]+(?::[^\s/@]*)?@',
        '$1***:***@'
    )
    foreach ($token in $CredentialTokens) {
        if (-not [string]::IsNullOrEmpty($token)) {
            $safeLine = $safeLine.Replace($token, '***')
        }
    }
    return $safeLine
}

function Test-CredentialLeak {
    param([string]$Line)

    if ([Regex]::IsMatch($Line, '(?i)\brtsps?://(?!(?:\*{3}:\*{3})@)[^\s/@]+(?::[^\s/@]*)?@')) {
        return $true
    }
    foreach ($token in $CredentialTokens) {
        if (-not [string]::IsNullOrEmpty($token) -and
            $Line.IndexOf($token, [StringComparison]::Ordinal) -ge 0) {
            return $true
        }
    }
    return $false
}

& (Join-Path $PSScriptRoot 'run-public-audit.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Public-repository audit failed' }

Get-Command docker -ErrorAction Stop | Out-Null
docker compose version | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Docker Compose is unavailable.' }

New-Item -ItemType Directory -Force -Path $RecordingDirectory, $ArtifactDirectory | Out-Null
$timestamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
$recordingName = "m0-real-camera-$timestamp.mp4"
$recordingPath = Join-Path $RecordingDirectory $recordingName
$logPath = Join-Path $ArtifactDirectory "m0-real-camera-$timestamp.log"

Push-Location $RepositoryRoot
try {
    if (-not $SkipBuild) {
        docker compose --env-file $EnvFile -f $ComposeFile build webobs
        if ($LASTEXITCODE -ne 0) { throw 'Could not build the product image.' }
        docker compose -f $SmokeComposeFile build validator
        if ($LASTEXITCODE -ne 0) { throw 'Could not build the recording validator image.' }
    }

    $recordArguments = @(
        'compose', '--env-file', $EnvFile, '-f', $ComposeFile,
        'run', '--rm', '-T',
        '-e', "WEBOBS_OUTPUT=/recordings/$recordingName",
        '-e', "WEBOBS_DURATION_SECONDS=$DurationSeconds",
        '-e', "WEBOBS_WIDTH=$Width",
        '-e', "WEBOBS_HEIGHT=$Height",
        '-e', "WEBOBS_FPS=$Fps",
        '-e', "WEBOBS_BITRATE_KBPS=$BitrateKbps",
        '-e', "WEBOBS_CONNECT_TIMEOUT_SECONDS=$ConnectTimeoutSeconds",
        '-e', "WEBOBS_RTSP_TRANSPORT=$RtspTransport",
        'webobs'
    )

    $utf8NoBom = [Text.UTF8Encoding]::new($false)
    $writer = [IO.StreamWriter]::new($logPath, $false, $utf8NoBom)
    $leakDetected = $false
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & docker @recordArguments 2>&1 | ForEach-Object {
            $rawLine = $_.ToString()
            if (Test-CredentialLeak -Line $rawLine) { $leakDetected = $true }
            $safeLine = Protect-LogLine -Line $rawLine
            $writer.WriteLine($safeLine)
            $writer.Flush()
            Write-Host $safeLine
        }
        $recordStatus = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
        $writer.Dispose()
    }

    if ($leakDetected) {
        throw "Credential redaction failed. Raw credentials were suppressed; inspect the sanitized log at '$logPath'."
    }
    if ($recordStatus -ne 0) {
        throw "Real-camera recording failed with exit code $recordStatus. Sanitized log: '$logPath'."
    }
    if (-not (Test-Path -LiteralPath $recordingPath -PathType Leaf) -or
        (Get-Item -LiteralPath $recordingPath).Length -eq 0) {
        throw 'The real-camera recording is missing or empty.'
    }

    $minimumDuration = [Math]::Max(28, $DurationSeconds - 2)
    $maximumDuration = $DurationSeconds + 10
    $mount = "type=bind,source=$RecordingDirectory,target=/artifacts,readonly"
    $validatorArguments = @(
        'run', '--rm', '--mount', $mount,
        '--entrypoint', '/usr/local/bin/probe-recording',
        '-e', "TEST_RECORDING=/artifacts/$recordingName",
        '-e', "TEST_DIMENSIONS=${Width}x${Height}",
        '-e', "TEST_FRAME_RATE=$Fps/1",
        '-e', "TEST_MIN_DURATION=$minimumDuration",
        '-e', "TEST_MAX_DURATION=$maximumDuration",
        'webobs-m0-rtsp-fixture:local'
    )
    & docker @validatorArguments
    if ($LASTEXITCODE -ne 0) { throw 'ffprobe/FFmpeg validation failed for the real-camera recording.' }

    Write-Host "M0 real-camera acceptance passed. Recording: $recordingPath"
    Write-Host "Sanitized local log (do not attach publicly): $logPath"
}
finally {
    Pop-Location
}
