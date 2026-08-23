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
$Artifact = Join-Path $ArtifactDirectory 'direct.mp4'
$BaseUri = 'http://127.0.0.1:18082'

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
        [string]$ContentType = 'application/sdp',
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
$Profile = Join-Path $ArtifactDirectory ('chrome-direct-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $Profile | Out-Null
$Handler = [Net.Http.HttpClientHandler]::new()
$Handler.UseProxy = $false
$Client = [Net.Http.HttpClient]::new($Handler)
$Client.Timeout = [TimeSpan]::FromSeconds(20)
$ChromeProcess = $null

Push-Location $RepositoryRoot
try {
    docker compose -f $ComposeFile down --volumes --remove-orphans
    if (Test-Path -LiteralPath $Artifact) { Remove-Item -LiteralPath $Artifact -Force }
    $BuildOption = if ($SkipBuild) { '--no-build' } else { '--build' }
    docker compose -f $ComposeFile up $BuildOption -d mediamtx fixture webobs-direct
    if ($LASTEXITCODE -ne 0) { throw 'M3 deterministic Direct service failed to start.' }

    $CapabilitiesResponse = $null
    $Deadline = [DateTime]::UtcNow.AddSeconds(60)
    while ([DateTime]::UtcNow -lt $Deadline) {
        try {
            $Candidate = Invoke-LocalRequest -Client $Client -Method ([Net.Http.HttpMethod]::Get) `
                -Path '/api/v1/playback/capabilities'
            if ($Candidate.Status -eq 200) { $CapabilitiesResponse = $Candidate; break }
        } catch { Start-Sleep -Milliseconds 250 }
    }
    Assert-True ($null -ne $CapabilitiesResponse) 'M3 playback capabilities did not become ready.'
    Assert-True ($CapabilitiesResponse.Body -notmatch 'rtsp://|direct-[a-f0-9]|mediamtx') `
        'Playback capabilities exposed an internal endpoint or RTSP URL.'
    $Capabilities = $CapabilitiesResponse.Body | ConvertFrom-Json
    Assert-True ($Capabilities.defaultMode -eq 'direct') 'Gateway Direct relay must be the low-load default mode.'
    Assert-True ($Capabilities.modes.composite.enabled -eq $true -and $Capabilities.modes.direct.enabled -eq $true) `
        'Deterministic M3 service must expose both explicit playback modes.'
    Assert-True ($Capabilities.sources.Count -eq 2) 'M3 capabilities must contain both scene sources.'
    $ExpectedEndpoints = @('/api/v1/sources/camera-left/whep', '/api/v1/sources/camera-right/whep')
    Assert-True ((@($Capabilities.sources.endpoint | Sort-Object) -join ',') -eq `
        (@($ExpectedEndpoints | Sort-Object) -join ',')) 'Direct endpoints must be same-origin and source-scoped.'

    $WrongType = Invoke-LocalRequest -Client $Client -Method ([Net.Http.HttpMethod]::Post) `
        -Path '/api/v1/sources/camera-left/whep' -Body '{}' -ContentType 'application/json'
    Assert-True ($WrongType.Status -eq 415) 'Direct WHEP must reject non-SDP content.'
    $WrongOrigin = Invoke-LocalRequest -Client $Client -Method ([Net.Http.HttpMethod]::Post) `
        -Path '/api/v1/sources/camera-left/whep' -Body 'v=0' -Headers @{ Origin = 'http://example.invalid' }
    Assert-True ($WrongOrigin.Status -eq 403) 'Direct WHEP must reject a foreign Origin.'
    $Unknown = Invoke-LocalRequest -Client $Client -Method ([Net.Http.HttpMethod]::Post) `
        -Path '/api/v1/sources/not-in-scene/whep' -Body 'v=0'
    Assert-True ($Unknown.Status -eq 404) 'Direct WHEP must reject sources outside the active scene.'

    $ChromeArguments = @(
        '--headless=new', '--disable-gpu', '--disable-features=WebRtcHideLocalIpsWithMdns',
        '--no-first-run', '--no-default-browser-check', '--autoplay-policy=no-user-gesture-required',
        "--user-data-dir=$Profile", "$BaseUri/#direct"
    )
    $ChromeProcess = Start-Process -FilePath $ChromePath -ArgumentList $ChromeArguments `
        -WindowStyle Hidden -PassThru
    Start-Sleep -Seconds 25
    Assert-True (-not $ChromeProcess.HasExited) 'Headless Chrome exited before Direct playback completed.'

    $Logs = docker compose -f $ComposeFile logs --no-color webobs-direct | Out-String
    Assert-True ($LASTEXITCODE -eq 0) 'Could not read the M3 Direct service logs.'
    $Readers = [Regex]::Matches($Logs, "is reading from path 'direct-[a-f0-9]{32}', 1 track \(H264\)").Count
    Assert-True ($Readers -ge 2) 'Chrome did not establish one H.264 Direct reader per visible source.'
    Assert-True ($Logs -notmatch "path 'direct-(camera-left|camera-right)") `
        'Internal MediaMTX paths must not derive from public source IDs.'
    Assert-True ($Logs -notmatch 'rtsp://[^/\s]+:[^@/\s]+@') 'Runtime logs must not expose RTSP credentials.'

    Stop-Process -Id $ChromeProcess.Id -Force -ErrorAction SilentlyContinue
    $ChromeProcess.WaitForExit(5000) | Out-Null
    $ChromeProcess.Dispose()
    $ChromeProcess = $null

    docker compose -f $ComposeFile stop -t 20 webobs-direct
    if ($LASTEXITCODE -ne 0) { throw 'M3 Direct service did not stop cleanly.' }
    docker compose -f $ComposeFile run --rm `
        -e TEST_RECORDING=/artifacts/direct.mp4 `
        -e TEST_MIN_DURATION=20 `
        -e TEST_MAX_DURATION=60 `
        -e TEST_REQUIRE_PILLARBOX=0 `
        -e TEST_REJECT_BLACKOUT=1 `
        validator
    if ($LASTEXITCODE -ne 0) { throw 'M3 Direct regression recording validation failed.' }
    Write-Host 'M3 deterministic two-source Direct WHEP acceptance passed.'
}
finally {
    if ($null -ne $ChromeProcess) {
        if (-not $ChromeProcess.HasExited) { Stop-Process -Id $ChromeProcess.Id -Force -ErrorAction SilentlyContinue }
        $ChromeProcess.Dispose()
    }
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
