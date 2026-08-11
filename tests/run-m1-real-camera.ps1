[CmdletBinding()]
param(
    [switch]$SkipBuild,
    [switch]$UseSyntheticFixture,
    [string]$EnvFile,
    [ValidateRange(10, 3600)]
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
$ProductComposeFile = Join-Path $RepositoryRoot 'compose.yaml'
$TestComposeFile = Join-Path $PSScriptRoot 'compose.smoke.yaml'
$RecordingDirectory = Join-Path $RepositoryRoot 'recordings'
$ArtifactDirectory = Join-Path $PSScriptRoot 'artifacts'

function Get-DotEnvValue {
    param([string]$Path, [string]$Name)

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

if (-not $UseSyntheticFixture -and $DurationSeconds -lt 30) {
    throw 'The real-camera M1 acceptance duration must be at least 30 seconds.'
}
if (($Width % 2) -ne 0 -or ($Height % 2) -ne 0) {
    throw 'Width and height must both be even.'
}

if ($UseSyntheticFixture) {
    $RtspUrl = ('rts' + 'p://mediamtx:8554/m0-test')
}
else {
    $exampleUrl = Get-DotEnvValue -Path (Join-Path $RepositoryRoot '.env.example') -Name 'WEBOBS_RTSP_URL'
    if (-not [string]::IsNullOrWhiteSpace($EnvFile)) {
        if (-not [IO.Path]::IsPathRooted($EnvFile)) {
            $EnvFile = Join-Path $RepositoryRoot $EnvFile
        }
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
    if ([string]::IsNullOrWhiteSpace($RtspUrl)) {
        throw 'WEBOBS_RTSP_URL is missing from the selected configuration source.'
    }
    if ($RtspUrl -eq $exampleUrl) {
        throw 'WEBOBS_RTSP_URL still contains the .env.example placeholder.'
    }
    if ($RtspUrl.Contains('${')) {
        throw 'The M1 real-camera runner requires WEBOBS_RTSP_URL to be a literal value.'
    }
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
        $decoded = [Uri]::UnescapeDataString($ParsedRtspUrl.UserInfo)
        if ($decoded -ne $ParsedRtspUrl.UserInfo) { $CredentialTokens.Add($decoded) }
    } catch {}
    $separator = $ParsedRtspUrl.UserInfo.IndexOf(':')
    if ($separator -ge 0) {
        $username = $ParsedRtspUrl.UserInfo.Substring(0, $separator)
        $password = $ParsedRtspUrl.UserInfo.Substring($separator + 1)
        if ($username.Length -ge 4) { $CredentialTokens.Add($username) }
        if ($password.Length -ge 4) { $CredentialTokens.Add($password) }
    }
}

function Test-CredentialLeak {
    param([string]$Text)
    if ([Regex]::IsMatch($Text, '(?i)\brtsps?://(?!(?:\*{3}:\*{3})@)[^\s/@]+(?::[^\s/@]*)?@')) {
        return $true
    }
    foreach ($token in $CredentialTokens) {
        if (-not [string]::IsNullOrEmpty($token) -and
            $Text.IndexOf($token, [StringComparison]::Ordinal) -ge 0) {
            return $true
        }
    }
    return $false
}

function Protect-RealCameraLog {
    param([string]$Text)
    $safe = [Regex]::Replace($Text, '(?i)\brtsps?://[^\s''"]+', 'rtsp://<redacted>')
    foreach ($token in $CredentialTokens) {
        if (-not [string]::IsNullOrEmpty($token)) { $safe = $safe.Replace($token, '***') }
    }
    return $safe
}

& (Join-Path $PSScriptRoot 'run-public-audit.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Public-repository audit failed.' }
Get-Command docker -ErrorAction Stop | Out-Null
docker compose version | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Docker Compose is unavailable.' }

New-Item -ItemType Directory -Force -Path $RecordingDirectory, $ArtifactDirectory | Out-Null
$timestamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
$recordingPrefix = if ($UseSyntheticFixture) { 'm1-real-camera-rehearsal' } else { 'm1-real-camera' }
$recordingName = "$recordingPrefix-$timestamp.mp4"
$recordingPath = Join-Path $RecordingDirectory $recordingName
$logPath = Join-Path $ArtifactDirectory "$recordingPrefix-$timestamp.log"
$projectName = ("webobs-m1-real-$timestamp").ToLowerInvariant()

$managedEnvironment = @{
    WEBOBS_RTSP_URL = $RtspUrl
    WEBOBS_REAL_RECORDING_NAME = $recordingName
    WEBOBS_REAL_WIDTH = $Width.ToString()
    WEBOBS_REAL_HEIGHT = $Height.ToString()
    WEBOBS_REAL_FPS = $Fps.ToString()
    WEBOBS_REAL_BITRATE_KBPS = $BitrateKbps.ToString()
    WEBOBS_REAL_CONNECT_TIMEOUT_SECONDS = $ConnectTimeoutSeconds.ToString()
    WEBOBS_REAL_RTSP_TRANSPORT = $RtspTransport
}
$previousEnvironment = @{}
foreach ($name in $managedEnvironment.Keys) {
    $existing = Get-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
    $previousEnvironment[$name] = [PSCustomObject]@{
        Exists = $null -ne $existing
        Value = if ($null -ne $existing) { $existing.Value } else { $null }
    }
    Set-Item -LiteralPath "Env:$name" -Value $managedEnvironment[$name]
}

$composeArguments = @('compose', '-p', $projectName, '-f', $TestComposeFile)
$containerId = $null
$logSaved = $false
$leakDetected = $false

function Save-ContainerLog {
    if ($script:logSaved -or [string]::IsNullOrWhiteSpace($script:containerId)) { return }
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $rawLines = @(& docker logs $script:containerId 2>&1 | ForEach-Object { $_.ToString() })
        $logStatus = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($logStatus -ne 0) { throw 'Docker could not read the M1 product container log.' }
    $rawText = $rawLines -join "`n"
    $script:leakDetected = Test-CredentialLeak -Text $rawText
    $safeText = Protect-RealCameraLog -Text $rawText
    [IO.File]::WriteAllText($logPath, $safeText + "`n", [Text.UTF8Encoding]::new($false))
    $script:logSaved = $true
}

Push-Location $RepositoryRoot
try {
    if (-not $SkipBuild) {
        docker compose -f $ProductComposeFile build webobs
        if ($LASTEXITCODE -ne 0) { throw 'Could not build the product image.' }
        docker compose -f $TestComposeFile build validator
        if ($LASTEXITCODE -ne 0) { throw 'Could not build the M1 control/validator image.' }
        if ($UseSyntheticFixture) {
            docker compose -f $TestComposeFile build mediamtx
            if ($LASTEXITCODE -ne 0) { throw 'Could not build the synthetic MediaMTX fixture.' }
        }
    }

    if ($UseSyntheticFixture) {
        & docker @composeArguments up --no-build -d mediamtx fixture
        if ($LASTEXITCODE -ne 0) { throw 'Could not start the synthetic RTSP fixture.' }
        $fixtureReady = $false
        $fixtureDeadline = [DateTime]::UtcNow.AddSeconds(30)
        while ([DateTime]::UtcNow -lt $fixtureDeadline) {
            $fixtureLog = @(& docker @composeArguments logs --no-color mediamtx 2>&1) -join "`n"
            if ($fixtureLog -match '\[path m0-test\] stream is available and online') {
                $fixtureReady = $true
                break
            }
            Start-Sleep -Milliseconds 250
        }
        if (-not $fixtureReady) { throw 'Synthetic RTSP fixture did not publish a stream within 30 seconds.' }
    }
    & docker @composeArguments up --no-build -d --no-deps webobs-real-control
    if ($LASTEXITCODE -ne 0) { throw 'Could not start the isolated M1 real-camera product container.' }
    $containerId = (@(& docker @composeArguments ps -q webobs-real-control) -join '').Trim()
    if ([string]::IsNullOrWhiteSpace($containerId)) { throw 'Could not resolve the M1 product container ID.' }

    & docker @composeArguments run --rm --no-deps real-control-client
    if ($LASTEXITCODE -ne 0) { throw 'M1 real-camera API mutations failed.' }

    Start-Sleep -Seconds $DurationSeconds
    & docker @composeArguments stop webobs-real-control
    if ($LASTEXITCODE -ne 0) { throw 'The M1 real-camera container did not stop cleanly.' }
    $exitCode = (@(& docker inspect --format '{{.State.ExitCode}}' $containerId) -join '').Trim()
    if ($LASTEXITCODE -ne 0 -or $exitCode -ne '0') { throw 'The M1 real-camera process returned a non-zero status.' }

    Save-ContainerLog
    if ($leakDetected) {
        throw "Credential redaction failed. Raw output was suppressed; inspect only the endpoint-redacted log at '$logPath'."
    }
    if (-not (Test-Path -LiteralPath $recordingPath -PathType Leaf) -or
        (Get-Item -LiteralPath $recordingPath).Length -eq 0) {
        throw 'The M1 real-camera recording is missing or empty.'
    }

    $mount = "type=bind,source=$RecordingDirectory,target=/artifacts,readonly"
    $validatorArguments = @(
        'run', '--rm', '--mount', $mount,
        '--entrypoint', '/usr/local/bin/probe-recording',
        '-e', "TEST_RECORDING=/artifacts/$recordingName",
        '-e', "TEST_DIMENSIONS=${Width}x${Height}",
        '-e', "TEST_FRAME_RATE=$Fps/1",
        '-e', "TEST_MIN_DURATION=$DurationSeconds",
        '-e', "TEST_MAX_DURATION=$($DurationSeconds + 30)",
        '-e', 'TEST_REJECT_BLACKOUT=1',
        '-e', 'TEST_BLACKOUT_YAVG_MAX=16.5',
        'webobs-m0-rtsp-fixture:local'
    )
    & docker @validatorArguments
    if ($LASTEXITCODE -ne 0) { throw 'M1 real-camera recording validation failed.' }

    $mode = if ($UseSyntheticFixture) { 'synthetic rehearsal' } else { 'real camera' }
    Write-Host "M1 $mode acceptance passed. Recording: $recordingPath"
    Write-Host "Endpoint-redacted local log (do not attach publicly): $logPath"
}
finally {
    try { Save-ContainerLog } catch { Write-Warning "Could not save the endpoint-redacted local container log: $($_.Exception.Message)" }
    & docker @composeArguments down --volumes --remove-orphans | Out-Null
    Pop-Location
    foreach ($name in $managedEnvironment.Keys) {
        if ($previousEnvironment[$name].Exists) {
            Set-Item -LiteralPath "Env:$name" -Value $previousEnvironment[$name].Value
        } else {
            Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
        }
    }
}
