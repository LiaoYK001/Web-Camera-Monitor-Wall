[CmdletBinding()]
param([switch]$SkipBuild)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
Add-Type -AssemblyName System.Net.Http

$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ComposeFile = Join-Path $PSScriptRoot 'compose.smoke.yaml'
$ArtifactDirectory = Join-Path $PSScriptRoot 'artifacts'
$ArtifactName = 'm4-browser-' + [Guid]::NewGuid().ToString('N') + '.mp4'
$Artifact = Join-Path $ArtifactDirectory $ArtifactName
$CacheProbe = Join-Path $ArtifactDirectory ('m4-browser-cache-' + [Guid]::NewGuid().ToString('N'))
$BaseUri = 'http://127.0.0.1:18084'
$LocalOrigin = 'http://127.0.0.1:18084'
$FixtureToken = 'm4-test-token'

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
        [hashtable]$Headers = @{}
    )
    $Request = [Net.Http.HttpRequestMessage]::new($Method, "$BaseUri$Path")
    try {
        if ($PSBoundParameters.ContainsKey('Body')) {
            $Request.Content = [Net.Http.StringContent]::new($Body, [Text.Encoding]::UTF8, 'application/json')
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

function Wait-Scene {
    param([Net.Http.HttpClient]$Client, [int]$TimeoutSeconds = 60)
    $Deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        try {
            $Response = Invoke-LocalRequest -Client $Client -Method ([Net.Http.HttpMethod]::Get) -Path '/api/v1/scene'
            if ($Response.Status -eq 200) { return $Response.Body | ConvertFrom-Json }
        } catch {}
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $Deadline)
    throw 'M4 browser-source control API did not become ready.'
}

function Update-Scene {
    param([Net.Http.HttpClient]$Client, [object]$Scene)
    $Revision = [uint64]$Scene.revision
    $Body = $Scene | ConvertTo-Json -Depth 12 -Compress
    $Response = Invoke-LocalRequest -Client $Client -Method ([Net.Http.HttpMethod]::Put) `
        -Path '/api/v1/scene' -Body $Body -Headers @{ 'If-Match' = "`"$Revision`""; Origin = $LocalOrigin }
    Assert-True ($Response.Status -eq 200) "Browser scene update failed with HTTP $($Response.Status)."
    return $Response.Body | ConvertFrom-Json
}

function Get-BrowserProcessRows {
    param([string]$ContainerId)
    $Rows = @(& docker top $ContainerId -eo pid,args)
    if ($LASTEXITCODE -ne 0) { throw 'Could not inspect browser helper processes.' }
    return @($Rows | Select-Object -Skip 1 | Where-Object { $_ -match 'obs-browser-page' })
}

function Wait-BrowserProcessCount {
    param([string]$ContainerId, [int]$Minimum, [int]$Maximum, [int]$TimeoutSeconds = 20)
    $Deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $Count = @(Get-BrowserProcessRows -ContainerId $ContainerId).Count
        if ($Count -ge $Minimum -and $Count -le $Maximum) { return $Count }
        Start-Sleep -Milliseconds 500
    } while ([DateTime]::UtcNow -lt $Deadline)
    throw "Expected between $Minimum and $Maximum browser helper processes, found $Count."
}

function Wait-RendererProcessCount {
    param([string]$ContainerId, [int]$Minimum, [int]$Maximum, [int]$TimeoutSeconds = 20)
    $Deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $Count = @(Get-BrowserProcessRows -ContainerId $ContainerId | Where-Object { $_ -match '--type=renderer' }).Count
        if ($Count -ge $Minimum -and $Count -le $Maximum) { return $Count }
        Start-Sleep -Milliseconds 500
    } while ([DateTime]::UtcNow -lt $Deadline)
    throw "Expected between $Minimum and $Maximum CEF renderer processes, found $Count."
}

function Get-ProductLogs {
    $Logs = docker compose -f $ComposeFile logs --no-color webobs-browser | Out-String
    if ($LASTEXITCODE -ne 0) { throw 'Could not read browser-source product logs.' }
    Assert-True ($Logs -notmatch [Regex]::Escape($FixtureToken)) 'Product logs exposed a browser URL query token.'
    Assert-True ($Logs -notmatch 'https?://[^/\s]+:[^@/\s]+@') 'Product logs exposed HTTP URL userinfo.'
    return $Logs
}

function Wait-LogPatternCount {
    param([string]$Pattern, [int]$Minimum, [int]$TimeoutSeconds = 20)
    $Deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $Count = [Regex]::Matches((Get-ProductLogs), $Pattern).Count
        if ($Count -ge $Minimum) { return }
        Start-Sleep -Milliseconds 500
    } while ([DateTime]::UtcNow -lt $Deadline)
    throw "Log pattern '$Pattern' did not reach count $Minimum."
}

function Kill-RendererPool {
    param([string]$ContainerId)
    $Script = 'targets=; for file in /proc/[0-9]*/cmdline; do pid=${file#/proc/}; pid=${pid%/cmdline}; exe=$(readlink "/proc/$pid/exe" 2>/dev/null || true); case "$exe" in */obs-browser-page) ;; *) continue ;; esac; if tr "\000" " " < "$file" 2>/dev/null | grep -q -- "--type=renderer"; then targets="$targets $pid"; fi; done; test -n "$targets"; for pid in $targets; do kill -KILL "$pid"; done; echo $targets'
    $Killed = (& docker exec $ContainerId /bin/sh -c $Script | Out-String).Trim()
    Assert-True ($LASTEXITCODE -eq 0 -and $Killed -match '^\d+( \d+)*$') `
        'Could not target the CEF renderer pool for recovery testing.'
}

New-Item -ItemType Directory -Force -Path $ArtifactDirectory | Out-Null
$Handler = [Net.Http.HttpClientHandler]::new()
$Handler.UseProxy = $false
$Client = [Net.Http.HttpClient]::new($Handler)
$Client.Timeout = [TimeSpan]::FromSeconds(20)
$PreviousArtifactName = $env:WEBOBS_BROWSER_RECORDING_NAME
$env:WEBOBS_BROWSER_RECORDING_NAME = $ArtifactName

Push-Location $RepositoryRoot
try {
    docker compose -f $ComposeFile down --volumes --remove-orphans
    if (Test-Path -LiteralPath $Artifact) { Remove-Item -LiteralPath $Artifact -Force }
    docker compose -f $ComposeFile up -d --build --wait --wait-timeout 60 browser-fixture
    if ($LASTEXITCODE -ne 0) { throw 'M4 browser fixture failed to start.' }

    $Rejected = docker compose -f $ComposeFile run --rm --no-deps `
        -e WEBOBS_BROWSER_ALLOW_PRIVATE_NETWORKS=false webobs-browser 2>&1 | Out-String
    Assert-True ($LASTEXITCODE -ne 0) 'Private browser destination started without the explicit private-network opt-in.'
    Assert-True ($Rejected -notmatch [Regex]::Escape($FixtureToken)) 'Rejected browser-source logs exposed a query token.'

    $BuildOption = if ($SkipBuild) { '--no-build' } else { '--build' }
    docker compose -f $ComposeFile up $BuildOption -d --wait --wait-timeout 60 browser-fixture webobs-browser
    if ($LASTEXITCODE -ne 0) { throw 'M4 browser-source services failed to start.' }

    $Scene = Wait-Scene -Client $Client
    Assert-True ($Scene.schemaVersion -eq 3) 'Browser scene API did not expose schemaVersion 3.'
    Assert-True ($Scene.sources.Count -eq 1 -and $Scene.sources[0].kind -eq 'browser') `
        'Browser scene API did not expose the expected browser source.'
    $PublicScene = $Scene | ConvertTo-Json -Depth 12 -Compress
    Assert-True ($PublicScene -notmatch [Regex]::Escape($FixtureToken)) 'Scene API exposed the browser query token.'
    Assert-True ($Scene.sources[0].url -eq 'http://browser-fixture:8080/?***#***') `
        'Scene API did not return the stable browser URL placeholder.'

    $Capabilities = (Invoke-LocalRequest -Client $Client -Method ([Net.Http.HttpMethod]::Get) `
        -Path '/api/v1/playback/capabilities').Body | ConvertFrom-Json
    Assert-True ($Capabilities.sources[0].preferred -eq 'composite' -and `
                 $Capabilities.sources[0].strategy -eq 'composite' -and `
                 $null -eq $Capabilities.sources[0].endpoint) `
        'Browser source must be classified as composite-only without a source-scoped WHEP endpoint.'

    $ContainerId = (@(& docker compose -f $ComposeFile ps -q webobs-browser) -join '').Trim()
    Assert-True (-not [string]::IsNullOrWhiteSpace($ContainerId)) 'Could not resolve the browser-source product container.'
    $InitialCount = Wait-BrowserProcessCount -ContainerId $ContainerId -Minimum 1 -Maximum 8
    Assert-True ($InitialCount -le 8) 'CEF helper count exceeded the tested process ceiling.'
    [void](Wait-RendererProcessCount -ContainerId $ContainerId -Minimum 1 -Maximum 4)
    $InitialCreated = [Regex]::Matches((Get-ProductLogs), 'Browser instance created').Count
    $InitialClosed = [Regex]::Matches((Get-ProductLogs), 'Browser instance closed').Count

    $Scene.items[0].visible = $false
    $Scene = Update-Scene -Client $Client -Scene $Scene
    Wait-LogPatternCount -Pattern 'Browser instance closed' -Minimum ($InitialClosed + 1)
    [void](Wait-BrowserProcessCount -ContainerId $ContainerId -Minimum 1 -Maximum 8)
    [void](Wait-RendererProcessCount -ContainerId $ContainerId -Minimum 0 -Maximum 4)

    $Scene.items[0].visible = $true
    $Scene = Update-Scene -Client $Client -Scene $Scene
    Wait-LogPatternCount -Pattern 'Browser instance created' -Minimum ($InitialCreated + 1)
    [void](Wait-RendererProcessCount -ContainerId $ContainerId -Minimum 1 -Maximum 4)
    [void](Wait-BrowserProcessCount -ContainerId $ContainerId -Minimum 1 -Maximum 8)

    Kill-RendererPool -ContainerId $ContainerId
    $Deadline = [DateTime]::UtcNow.AddSeconds(25)
    do {
        Start-Sleep -Milliseconds 500
        $Logs = Get-ProductLogs
        $Recovered = $Logs -match 'Webpage has crashed unexpectedly' -and `
                     @(Get-BrowserProcessRows -ContainerId $ContainerId | Where-Object { $_ -match '--type=renderer' }).Count -ge 1
    } while (-not $Recovered -and [DateTime]::UtcNow -lt $Deadline)
    Assert-True $Recovered 'CEF renderer crash did not log and recover within the timeout.'

    Start-Sleep -Seconds 3
    docker compose -f $ComposeFile stop -t 20 webobs-browser
    if ($LASTEXITCODE -ne 0) { throw 'Could not stop the browser-source product container cleanly.' }
    Assert-True (Test-Path -LiteralPath $Artifact -PathType Leaf) 'Browser-source recording was not finalized.'

    New-Item -ItemType Directory -Path $CacheProbe | Out-Null
    docker cp "${ContainerId}:/config/obs/plugin_config/obs-browser/." $CacheProbe 2>$null | Out-Null
    Assert-True ($LASTEXITCODE -ne 0) 'CEF cache survived clean container shutdown.'

    docker compose -f $ComposeFile run --rm --no-deps `
        -e TEST_RECORDING="/artifacts/$ArtifactName" `
        -e TEST_DIMENSIONS=640x360 -e TEST_FRAME_RATE=10/1 `
        -e TEST_MIN_DURATION=5 -e TEST_MAX_DURATION=45 `
        -e TEST_REQUIRE_PILLARBOX=0 -e TEST_SAMPLE_FROM_END_SECONDS=1 -e TEST_MIN_YAVG=30 validator
    if ($LASTEXITCODE -ne 0) { throw 'Browser-source recording validation failed.' }

    $FinalLogs = Get-ProductLogs
    Assert-True ($FinalLogs -match "Loaded OBS module 'obs-browser'") 'obs-browser was not loaded as a required module.'
    Write-Host 'M4 deterministic browser-source lifecycle, recovery, policy, redaction, and cache-cleanup acceptance passed.'
} finally {
    $Client.Dispose()
    $Handler.Dispose()
    docker compose -f $ComposeFile down --volumes --remove-orphans | Out-Null
    if (Test-Path -LiteralPath $CacheProbe) {
        $ResolvedProbe = [IO.Path]::GetFullPath($CacheProbe)
        $ResolvedArtifacts = [IO.Path]::GetFullPath($ArtifactDirectory).TrimEnd([IO.Path]::DirectorySeparatorChar) +
            [IO.Path]::DirectorySeparatorChar
        Assert-True ($ResolvedProbe.StartsWith($ResolvedArtifacts, [StringComparison]::OrdinalIgnoreCase)) `
            'Refusing to recursively remove a cache probe outside the test artifact directory.'
        Remove-Item -LiteralPath $ResolvedProbe -Recurse -Force
    }
    if ($null -eq $PreviousArtifactName) {
        Remove-Item Env:WEBOBS_BROWSER_RECORDING_NAME -ErrorAction SilentlyContinue
    } else {
        $env:WEBOBS_BROWSER_RECORDING_NAME = $PreviousArtifactName
    }
    Pop-Location
}
