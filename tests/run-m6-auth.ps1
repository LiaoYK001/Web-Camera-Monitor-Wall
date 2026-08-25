[CmdletBinding()]
param([switch]$SkipBuild)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
Add-Type -AssemblyName System.Net.Http

$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ComposeFile = Join-Path $PSScriptRoot 'compose.smoke.yaml'
$ArtifactDirectory = Join-Path $PSScriptRoot 'artifacts'
$BaseUri = 'http://127.0.0.1:18086'
$Username = 'm6-operator'
$Password = 'm6-public-test-password-1234'
$Authorization = 'Basic ' + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("${Username}:$Password"))

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

function Invoke-M6Request {
    param(
        [Net.Http.HttpClient]$Client,
        [Net.Http.HttpMethod]$Method,
        [string]$Path,
        [string]$Body,
        [hashtable]$Headers = @{}
    )
    $Request = [Net.Http.HttpRequestMessage]::new($Method, "$BaseUri$Path")
    try {
        if ($null -ne $Body) {
            $Request.Content = [Net.Http.StringContent]::new($Body, [Text.Encoding]::UTF8, 'application/json')
        }
        foreach ($Entry in $Headers.GetEnumerator()) {
            if ($Entry.Key -eq 'Host') {
                $Request.Headers.Host = $Entry.Value
            } else {
                [void]$Request.Headers.TryAddWithoutValidation($Entry.Key, $Entry.Value)
            }
        }
        $Response = $Client.SendAsync($Request).GetAwaiter().GetResult()
        try {
            $ResponseHeaders = @{}
            foreach ($Header in $Response.Headers) { $ResponseHeaders[$Header.Key] = $Header.Value -join ',' }
            foreach ($Header in $Response.Content.Headers) { $ResponseHeaders[$Header.Key] = $Header.Value -join ',' }
            return [PSCustomObject]@{
                Status = [int]$Response.StatusCode
                Body = $Response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
                Headers = $ResponseHeaders
            }
        } finally {
            $Response.Dispose()
        }
    } finally {
        $Request.Dispose()
    }
}

function Receive-WebSocketText {
    param([Net.WebSockets.ClientWebSocket]$Socket)
    $Memory = [IO.MemoryStream]::new()
    try {
        do {
            $Buffer = [byte[]]::new(65536)
            $Result = $Socket.ReceiveAsync([ArraySegment[byte]]::new($Buffer),
                [Threading.CancellationToken]::None).GetAwaiter().GetResult()
            Assert-True ($Result.MessageType -eq [Net.WebSockets.WebSocketMessageType]::Text) `
                'Authenticated WebSocket did not return a text snapshot.'
            $Memory.Write($Buffer, 0, $Result.Count)
        } while (-not $Result.EndOfMessage)
        return [Text.Encoding]::UTF8.GetString($Memory.ToArray())
    } finally {
        $Memory.Dispose()
    }
}

& (Join-Path $PSScriptRoot 'run-public-audit.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Public-repository audit failed.' }
Get-Command docker -ErrorAction Stop | Out-Null

New-Item -ItemType Directory -Force -Path $ArtifactDirectory | Out-Null
$RecordingPath = Join-Path $ArtifactDirectory 'm6-auth.mp4'
if (Test-Path -LiteralPath $RecordingPath) { Remove-Item -LiteralPath $RecordingPath -Force }
$Handler = [Net.Http.HttpClientHandler]::new()
$Handler.UseProxy = $false
$Client = [Net.Http.HttpClient]::new($Handler)
$Client.Timeout = [TimeSpan]::FromSeconds(20)
$SessionHandler = [Net.Http.HttpClientHandler]::new()
$SessionHandler.UseProxy = $false
$SessionHandler.UseCookies = $true
$SessionHandler.CookieContainer = [Net.CookieContainer]::new()
$SessionClient = [Net.Http.HttpClient]::new($SessionHandler)
$SessionClient.Timeout = [TimeSpan]::FromSeconds(20)
$ContainerId = $null

Push-Location $RepositoryRoot
try {
    docker compose -f $ComposeFile down --volumes --remove-orphans | Out-Null
    if (-not $SkipBuild) {
        docker compose -f $ComposeFile build webobs-auth validator
        Assert-True ($LASTEXITCODE -eq 0) 'M6 authentication images failed to build.'
    }
    docker compose -f $ComposeFile up --no-build -d mediamtx fixture webobs-auth
    Assert-True ($LASTEXITCODE -eq 0) 'M6 authentication fixture failed to start.'
    $ContainerId = (@(docker compose -f $ComposeFile ps -q webobs-auth) -join '').Trim()
    Assert-True (-not [string]::IsNullOrWhiteSpace($ContainerId)) 'M6 product container ID is unavailable.'

    $Ready = $false
    $Deadline = [DateTime]::UtcNow.AddSeconds(60)
    while ([DateTime]::UtcNow -lt $Deadline) {
        try {
            $Health = Invoke-M6Request -Client $Client -Method ([Net.Http.HttpMethod]::Get) `
                -Path '/api/v1/health'
            $Readiness = Invoke-M6Request -Client $Client -Method ([Net.Http.HttpMethod]::Get) `
                -Path '/api/v1/ready'
            if ($Health.Status -eq 200 -and $Readiness.Status -eq 200) { $Ready = $true; break }
        } catch {}
        Start-Sleep -Milliseconds 250
    }
    Assert-True $Ready 'M6 public liveness/readiness probes did not become ready.'
    Assert-True ($Health.Body -eq '{"status":"ok","milestone":"v1-M11"}' -and
        $Readiness.Body -eq '{"status":"ready"}') `
        'M6 probes returned an unexpected public payload.'
    $ReadyAt = [DateTime]::UtcNow

    $PublicRoot = Invoke-M6Request -Client $Client -Method ([Net.Http.HttpMethod]::Get) -Path '/'
    Assert-True ($PublicRoot.Status -eq 200 -and $PublicRoot.Body -match '<div id="root"></div>' -and
        -not $PublicRoot.Headers.ContainsKey('WWW-Authenticate')) `
        'The login shell must load without triggering a browser Basic Auth challenge.'
    foreach ($ProtectedPath in @('/api/v1/scene', '/api/v1/program/status',
            '/api/v1/playback/capabilities', '/api/v1/sources/status',
            '/api/v1/system/capabilities', '/metrics')) {
        $Protected = Invoke-M6Request -Client $Client -Method ([Net.Http.HttpMethod]::Get) -Path $ProtectedPath
        Assert-True ($Protected.Status -eq 401 -and -not $Protected.Headers.ContainsKey('WWW-Authenticate')) `
            "Unauthenticated request unexpectedly reached $ProtectedPath or issued a Basic challenge."
    }
    foreach ($ProtectedWhepPath in @('/api/v1/program/whep', '/api/v1/sources/camera-left/whep')) {
        $ProtectedWhep = Invoke-M6Request -Client $Client -Method ([Net.Http.HttpMethod]::Post) `
            -Path $ProtectedWhepPath -Body 'unauthenticated-offer'
        Assert-True ($ProtectedWhep.Status -eq 401) `
            "Unauthenticated request unexpectedly reached $ProtectedWhepPath."
    }

    $AssetMatch = [Regex]::Match($PublicRoot.Body, 'src="(?<path>/assets/[^"?]+\.js)"')
    Assert-True $AssetMatch.Success 'The public login shell did not reference its JavaScript asset.'
    $AssetWithoutAuth = Invoke-M6Request -Client $Client -Method ([Net.Http.HttpMethod]::Get) `
        -Path $AssetMatch.Groups['path'].Value
    Assert-True ($AssetWithoutAuth.Status -eq 200) 'The login page JavaScript must be publicly loadable.'

    $Login = Invoke-M6Request -Client $SessionClient -Method ([Net.Http.HttpMethod]::Post) `
        -Path '/api/v1/auth/login' -Body (@{ username = $Username; password = $Password } | ConvertTo-Json -Compress)
    $LoginBody = $Login.Body | ConvertFrom-Json
    Assert-True ($Login.Status -eq 200 -and $LoginBody.authenticated -eq $true -and
        $LoginBody.expiresInSeconds -eq 604800 -and
        $Login.Headers['Set-Cookie'] -match 'HttpOnly' -and
        $Login.Headers['Set-Cookie'] -match 'SameSite=Strict' -and
        $Login.Headers['Set-Cookie'] -notmatch '; Secure') `
        'Session login did not create the expected seven-day test cookie.'
    $Session = Invoke-M6Request -Client $SessionClient -Method ([Net.Http.HttpMethod]::Get) `
        -Path '/api/v1/auth/session'
    $SessionBody = $Session.Body | ConvertFrom-Json
    $MinimumExpiry = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() + 604700
    Assert-True ($Session.Status -eq 200 -and $SessionBody.authenticated -eq $true -and
        $SessionBody.via -eq 'session' -and $SessionBody.expiresAt -ge $MinimumExpiry) `
        'The browser session was not accepted or its inactivity expiry did not slide.'
    $SessionScene = Invoke-M6Request -Client $SessionClient -Method ([Net.Http.HttpMethod]::Get) `
        -Path '/api/v1/scene'
    Assert-True ($SessionScene.Status -eq 200) 'The session cookie did not authorize the control API.'
    $SessionProbe = "import sqlite3; rows=sqlite3.connect('/config/webobs/auth-sessions.db').execute('SELECT session_id_hash FROM auth_sessions').fetchall(); print(str(len(rows))+'|'+str(sum(len(row[0]) == 64 and all(ch in '0123456789abcdef' for ch in row[0]) for row in rows)))"
    $StoredSessionShape = (@(docker exec $ContainerId python3 -c $SessionProbe) -join '').Trim()
    Assert-True ($LASTEXITCODE -eq 0 -and $StoredSessionShape -eq '1|1') `
        'The session database did not store exactly one SHA-256 token hash.'

    $AuthHeaders = @{ Authorization = $Authorization }

    $CapabilitiesResponse = Invoke-M6Request -Client $Client -Method ([Net.Http.HttpMethod]::Get) `
        -Path '/api/v1/system/capabilities' -Headers $AuthHeaders
    $Capabilities = $CapabilitiesResponse.Body | ConvertFrom-Json
    Assert-True ($CapabilitiesResponse.Status -eq 200 -and
        $Capabilities.videoEncoder.requested -eq 'nvenc' -and
        $Capabilities.videoEncoder.selected -eq 'x264' -and
        $Capabilities.videoEncoder.fallback -eq $true -and
        $Capabilities.videoEncoder.backends.x264.ready -eq $true -and
        $Capabilities.videoEncoder.backends.nvenc.ready -eq $false -and
        $CapabilitiesResponse.Body -notmatch '/dev/|PCI|rtsp://') `
        'Unavailable NVENC must report a credential-free x264 fallback capability state.'

    $RemoteHeaders = @{
        Authorization = $Authorization
        Host = 'monitor.example.invalid'
        Origin = 'https://monitor.example.invalid'
    }
    $SceneResponse = Invoke-M6Request -Client $Client -Method ([Net.Http.HttpMethod]::Get) `
        -Path '/api/v1/scene' -Headers $RemoteHeaders
    Assert-True ($SceneResponse.Status -eq 200 -and $SceneResponse.Headers.ContainsKey('ETag')) `
        'An authenticated, allowlisted HTTPS reverse-proxy authority must reach the scene API.'
    $Scene = $SceneResponse.Body | ConvertFrom-Json
    $Scene.name = 'M6 Authenticated Fixture'
    $RemotePutHeaders = $RemoteHeaders.Clone()
    $RemotePutHeaders['If-Match'] = $SceneResponse.Headers['ETag']
    $Updated = Invoke-M6Request -Client $Client -Method ([Net.Http.HttpMethod]::Put) `
        -Path '/api/v1/scene' -Body ($Scene | ConvertTo-Json -Depth 12 -Compress) -Headers $RemotePutHeaders
    Assert-True ($Updated.Status -eq 200) 'Authenticated remote scene mutation did not succeed.'

    $ForeignOriginHeaders = $RemoteHeaders.Clone()
    $ForeignOriginHeaders['Origin'] = 'https://foreign.example.invalid'
    $ForeignOriginHeaders['If-Match'] = $Updated.Headers['ETag']
    $ForeignOrigin = Invoke-M6Request -Client $Client -Method ([Net.Http.HttpMethod]::Put) `
        -Path '/api/v1/scene' -Body $Updated.Body -Headers $ForeignOriginHeaders
    Assert-True ($ForeignOrigin.Status -eq 403) 'Authenticated cross-origin mutation must still be rejected.'
    $UnknownHost = Invoke-M6Request -Client $Client -Method ([Net.Http.HttpMethod]::Get) `
        -Path '/api/v1/scene' -Headers @{ Authorization = $Authorization; Host = 'unknown.example.invalid' }
    Assert-True ($UnknownHost.Status -eq 421) 'Authenticated requests with an unlisted Host must be rejected.'

    $Socket = [Net.WebSockets.ClientWebSocket]::new()
    try {
        $Socket.Options.SetRequestHeader('Authorization', $Authorization)
        $Socket.Options.SetRequestHeader('Origin', $BaseUri)
        [void]$Socket.ConnectAsync([Uri]'ws://127.0.0.1:18086/api/v1/ws',
            [Threading.CancellationToken]::None).GetAwaiter().GetResult()
        $Snapshot = Receive-WebSocketText -Socket $Socket | ConvertFrom-Json
        Assert-True ($Snapshot.type -eq 'scene.snapshot' -and $Snapshot.scene.name -eq 'M6 Authenticated Fixture') `
            'Authenticated WebSocket did not receive the current scene snapshot.'
    } finally {
        $Socket.Dispose()
    }
    $UnauthenticatedSocket = [Net.WebSockets.ClientWebSocket]::new()
    $UnauthenticatedConnected = $false
    try {
        $UnauthenticatedSocket.Options.SetRequestHeader('Origin', $BaseUri)
        try {
            [void]$UnauthenticatedSocket.ConnectAsync([Uri]'ws://127.0.0.1:18086/api/v1/ws',
                [Threading.CancellationToken]::None).GetAwaiter().GetResult()
            $UnauthenticatedConnected = $true
        } catch {}
    } finally {
        $UnauthenticatedSocket.Dispose()
    }
    Assert-True (-not $UnauthenticatedConnected) 'WebSocket upgrade succeeded without credentials.'

    $InitialSourceStatus = Invoke-M6Request -Client $Client -Method ([Net.Http.HttpMethod]::Get) `
        -Path '/api/v1/sources/status' -Headers $AuthHeaders
    $InitialSources = $InitialSourceStatus.Body | ConvertFrom-Json
    Assert-True ($InitialSourceStatus.Status -eq 200 -and $InitialSources.visible -eq 2 -and
        $InitialSources.healthy -eq 2 -and $InitialSources.unhealthy -eq 0 -and
        $InitialSources.totalRestarts -eq 0 -and $InitialSourceStatus.Body -notmatch 'rtsp://') `
        'Authenticated source health did not report a credential-free healthy baseline.'

    $InvalidHeaders = @{ Authorization = 'Basic Zm9vOmJhcg==' }
    $FirstFailure = Invoke-M6Request -Client $Client -Method ([Net.Http.HttpMethod]::Get) `
        -Path '/api/v1/scene' -Headers $InvalidHeaders
    $SecondFailure = Invoke-M6Request -Client $Client -Method ([Net.Http.HttpMethod]::Get) `
        -Path '/api/v1/scene' -Headers $InvalidHeaders
    $ThirdFailure = Invoke-M6Request -Client $Client -Method ([Net.Http.HttpMethod]::Get) `
        -Path '/api/v1/scene' -Headers $InvalidHeaders
    Assert-True ($FirstFailure.Status -eq 401 -and $SecondFailure.Status -eq 401 -and
        $ThirdFailure.Status -eq 429 -and $ThirdFailure.Headers['Retry-After'] -eq '2') `
        'Authentication failure rate limiting did not enforce the configured window.'
    $BlockedValid = Invoke-M6Request -Client $Client -Method ([Net.Http.HttpMethod]::Get) `
        -Path '/api/v1/scene' -Headers $AuthHeaders
    Assert-True ($BlockedValid.Status -eq 429) 'A rate-limited client bypassed its lockout with valid credentials.'
    Start-Sleep -Seconds 3
    $Recovered = Invoke-M6Request -Client $Client -Method ([Net.Http.HttpMethod]::Get) `
        -Path '/api/v1/scene' -Headers $AuthHeaders
    Assert-True ($Recovered.Status -eq 200) 'The client did not recover after the bounded lockout expired.'

    $Metrics = Invoke-M6Request -Client $Client -Method ([Net.Http.HttpMethod]::Get) `
        -Path '/metrics' -Headers $AuthHeaders
    Assert-True ($Metrics.Status -eq 200 -and
        $Metrics.Headers['Content-Type'] -match '^text/plain; version=0\.0\.4' -and
        $Metrics.Body -match '(?m)^webobs_ready 1$' -and
        $Metrics.Body -match '(?m)^webobs_sources_visible 2$' -and
        $Metrics.Body -match '(?m)^webobs_sources_healthy 2$' -and
        $Metrics.Body -match '(?m)^webobs_sources_unhealthy 0$' -and
        $Metrics.Body -match '(?m)^webobs_source_restarts_total 0$' -and
        $Metrics.Body -match '(?m)^webobs_video_encoder_selected\{backend="x264"\} 1$' -and
        $Metrics.Body -match '(?m)^webobs_video_encoder_selected\{backend="nvenc"\} 0$' -and
        $Metrics.Body -match '(?m)^webobs_video_encoder_fallback 1$' -and
        $Metrics.Body -match '(?m)^webobs_video_encoder_available\{backend="x264"\} 1$' -and
        $Metrics.Body -match '(?m)^webobs_auth_failures_total 3$') `
        'Authenticated Prometheus metrics did not report readiness, source health, encoder fallback, and rejected credentials.'
    $HealthStatus = ''
    $HealthDeadline = [DateTime]::UtcNow.AddSeconds(15)
    while ([DateTime]::UtcNow -lt $HealthDeadline) {
        $HealthStatus = (@(docker inspect --format '{{.State.Health.Status}}' $ContainerId) -join '').Trim()
        if ($HealthStatus -eq 'healthy') { break }
        Assert-True ($HealthStatus -ne 'unhealthy') 'The product Docker healthcheck became unhealthy.'
        Start-Sleep -Milliseconds 250
    }
    Assert-True ($HealthStatus -eq 'healthy') 'The product Docker healthcheck did not become healthy.'

    docker compose -f $ComposeFile stop -t 5 fixture
    Assert-True ($LASTEXITCODE -eq 0) 'Could not stop the RTSP publisher for recovery acceptance.'
    $OutageObserved = $false
    $OutageDeadline = [DateTime]::UtcNow.AddSeconds(20)
    while ([DateTime]::UtcNow -lt $OutageDeadline) {
        try {
            $OutageStatusResponse = Invoke-M6Request -Client $Client -Method ([Net.Http.HttpMethod]::Get) `
                -Path '/api/v1/sources/status' -Headers $AuthHeaders
            $OutageReadiness = Invoke-M6Request -Client $Client -Method ([Net.Http.HttpMethod]::Get) `
                -Path '/api/v1/ready'
            $OutageSources = $OutageStatusResponse.Body | ConvertFrom-Json
            if ($OutageStatusResponse.Status -eq 200 -and $OutageSources.unhealthy -eq 2 -and
                $OutageSources.totalRestarts -ge 2 -and $OutageReadiness.Status -eq 503) {
                $OutageObserved = $true
                break
            }
        } catch {}
        Start-Sleep -Milliseconds 250
    }
    Assert-True $OutageObserved `
        'Source frame staleness did not degrade readiness and request bounded RTSP restarts.'
    $OutageMetrics = Invoke-M6Request -Client $Client -Method ([Net.Http.HttpMethod]::Get) `
        -Path '/metrics' -Headers $AuthHeaders
    Assert-True ($OutageMetrics.Body -match '(?m)^webobs_ready 0$' -and
        $OutageMetrics.Body -match '(?m)^webobs_sources_unhealthy 2$' -and
        $OutageMetrics.Body -match '(?m)^webobs_source_restarts_total (?:[2-9]|[1-9][0-9]+)$') `
        'Outage metrics did not expose aggregate unhealthy and restart state.'

    docker compose -f $ComposeFile start fixture
    Assert-True ($LASTEXITCODE -eq 0) 'Could not restart the RTSP publisher for recovery acceptance.'
    $SourceRecovered = $false
    $RecoveryDeadline = [DateTime]::UtcNow.AddSeconds(40)
    while ([DateTime]::UtcNow -lt $RecoveryDeadline) {
        try {
            $RecoveredStatusResponse = Invoke-M6Request -Client $Client -Method ([Net.Http.HttpMethod]::Get) `
                -Path '/api/v1/sources/status' -Headers $AuthHeaders
            $RecoveredReadiness = Invoke-M6Request -Client $Client -Method ([Net.Http.HttpMethod]::Get) `
                -Path '/api/v1/ready'
            $RecoveredSources = $RecoveredStatusResponse.Body | ConvertFrom-Json
            if ($RecoveredSources.healthy -eq 2 -and $RecoveredSources.unhealthy -eq 0 -and
                $RecoveredSources.totalRestarts -ge 2 -and $RecoveredReadiness.Status -eq 200) {
                $SourceRecovered = $true
                break
            }
        } catch {}
        Start-Sleep -Milliseconds 250
    }
    Assert-True $SourceRecovered 'RTSP sources did not recover and restore readiness after publisher restart.'

    $Logout = Invoke-M6Request -Client $SessionClient -Method ([Net.Http.HttpMethod]::Post) `
        -Path '/api/v1/auth/logout'
    $AfterLogout = Invoke-M6Request -Client $SessionClient -Method ([Net.Http.HttpMethod]::Get) `
        -Path '/api/v1/scene'
    Assert-True ($Logout.Status -eq 204 -and $AfterLogout.Status -eq 401 -and
        $Logout.Headers['Set-Cookie'] -match 'Max-Age=0') `
        'Logout did not revoke the server-side session and clear the browser cookie.'

    $Logs = @(docker logs $ContainerId 2>&1 | ForEach-Object { $_.ToString() }) -join "`n"
    Assert-True ($Logs -notmatch [Regex]::Escape($Username) -and
        $Logs -notmatch [Regex]::Escape($Password) -and
        $Logs -match 'HTTP Basic authentication is enabled' -and
        $Logs -notmatch 'listener is unauthenticated' -and
        $Logs -match '"event":"authentication"' -and
        $Logs -match '"event":"scene_update"' -and
        $Logs -match '"event":"source_recovery"' -and
        $Logs -match '"outcome":"recovered"') `
        'Structured audit logs were incomplete, exposed credentials, or reported the wrong security mode.'

    $MinimumRecordingStopAt = $ReadyAt.AddSeconds(6)
    if ([DateTime]::UtcNow -lt $MinimumRecordingStopAt) {
        Start-Sleep -Milliseconds ([int][Math]::Ceiling(($MinimumRecordingStopAt - [DateTime]::UtcNow).TotalMilliseconds))
    }
    docker compose -f $ComposeFile stop -t 20 webobs-auth
    Assert-True ($LASTEXITCODE -eq 0) 'M6 authentication product did not stop cleanly.'
    $ExitCode = (@(docker inspect --format '{{.State.ExitCode}}' $ContainerId) -join '').Trim()
    if ($ExitCode -ne '0') {
        docker logs --tail 240 $ContainerId
    }
    Assert-True ($ExitCode -eq '0') 'M6 authentication product returned a non-zero status.'
    docker compose -f $ComposeFile run --rm `
        -e TEST_RECORDING=/artifacts/m6-auth.mp4 `
        -e TEST_MIN_DURATION=5 -e TEST_MAX_DURATION=180 `
        -e TEST_REQUIRE_PILLARBOX=0 validator
    Assert-True ($LASTEXITCODE -eq 0) 'M6 authentication recording was not finalized correctly.'

    Write-Host 'M6 authentication, authorization, rate limit, source health, recovery, audit, metrics, healthcheck, and redaction acceptance passed.'
} finally {
    $SessionClient.Dispose()
    $SessionHandler.Dispose()
    $Client.Dispose()
    $Handler.Dispose()
    docker compose -f $ComposeFile down --volumes --remove-orphans | Out-Null
    Pop-Location
}
