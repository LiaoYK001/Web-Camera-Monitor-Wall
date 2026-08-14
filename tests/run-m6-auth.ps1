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
    Assert-True ($Health.Body -match '"milestone":"M6"' -and $Readiness.Body -eq '{"status":"ready"}') `
        'M6 probes returned an unexpected public payload.'
    $ReadyAt = [DateTime]::UtcNow

    $UnauthorizedRoot = Invoke-M6Request -Client $Client -Method ([Net.Http.HttpMethod]::Get) -Path '/'
    Assert-True ($UnauthorizedRoot.Status -eq 401 -and
        $UnauthorizedRoot.Headers['WWW-Authenticate'] -match '^Basic realm="WebOBS"') `
        'The Web editor must issue a Basic challenge when credentials are absent.'
    foreach ($ProtectedPath in @('/api/v1/scene', '/api/v1/program/status',
            '/api/v1/playback/capabilities', '/metrics')) {
        $Protected = Invoke-M6Request -Client $Client -Method ([Net.Http.HttpMethod]::Get) -Path $ProtectedPath
        Assert-True ($Protected.Status -eq 401) "Unauthenticated request unexpectedly reached $ProtectedPath."
    }
    foreach ($ProtectedWhepPath in @('/api/v1/program/whep', '/api/v1/sources/camera-left/whep')) {
        $ProtectedWhep = Invoke-M6Request -Client $Client -Method ([Net.Http.HttpMethod]::Post) `
            -Path $ProtectedWhepPath -Body 'unauthenticated-offer'
        Assert-True ($ProtectedWhep.Status -eq 401) `
            "Unauthenticated request unexpectedly reached $ProtectedWhepPath."
    }

    $AuthHeaders = @{ Authorization = $Authorization }
    $Root = Invoke-M6Request -Client $Client -Method ([Net.Http.HttpMethod]::Get) -Path '/' -Headers $AuthHeaders
    Assert-True ($Root.Status -eq 200 -and $Root.Body -match '<div id="root"></div>') `
        'Valid credentials did not unlock the bundled Web editor.'
    $AssetMatch = [Regex]::Match($Root.Body, 'src="(?<path>/assets/[^"?]+\.js)"')
    Assert-True $AssetMatch.Success 'The authenticated Web editor did not reference its JavaScript asset.'
    $AssetWithoutAuth = Invoke-M6Request -Client $Client -Method ([Net.Http.HttpMethod]::Get) `
        -Path $AssetMatch.Groups['path'].Value
    $AssetWithAuth = Invoke-M6Request -Client $Client -Method ([Net.Http.HttpMethod]::Get) `
        -Path $AssetMatch.Groups['path'].Value -Headers $AuthHeaders
    Assert-True ($AssetWithoutAuth.Status -eq 401 -and $AssetWithAuth.Status -eq 200) `
        'Hashed UI assets must be protected by the same authentication boundary.'

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
        $Metrics.Body -match '(?m)^webobs_auth_failures_total 3$') `
        'Authenticated Prometheus metrics did not report readiness and rejected credentials.'
    $HealthStatus = ''
    $HealthDeadline = [DateTime]::UtcNow.AddSeconds(15)
    while ([DateTime]::UtcNow -lt $HealthDeadline) {
        $HealthStatus = (@(docker inspect --format '{{.State.Health.Status}}' $ContainerId) -join '').Trim()
        if ($HealthStatus -eq 'healthy') { break }
        Assert-True ($HealthStatus -ne 'unhealthy') 'The product Docker healthcheck became unhealthy.'
        Start-Sleep -Milliseconds 250
    }
    Assert-True ($HealthStatus -eq 'healthy') 'The product Docker healthcheck did not become healthy.'

    $Logs = @(docker logs $ContainerId 2>&1 | ForEach-Object { $_.ToString() }) -join "`n"
    Assert-True ($Logs -notmatch [Regex]::Escape($Username) -and
        $Logs -notmatch [Regex]::Escape($Password) -and
        $Logs -match 'HTTP Basic authentication is enabled' -and
        $Logs -notmatch 'listener is unauthenticated') `
        'Authentication logs exposed credentials or reported the wrong security mode.'

    $MinimumRecordingStopAt = $ReadyAt.AddSeconds(6)
    if ([DateTime]::UtcNow -lt $MinimumRecordingStopAt) {
        Start-Sleep -Milliseconds ([int][Math]::Ceiling(($MinimumRecordingStopAt - [DateTime]::UtcNow).TotalMilliseconds))
    }
    docker compose -f $ComposeFile stop -t 20 webobs-auth
    Assert-True ($LASTEXITCODE -eq 0) 'M6 authentication product did not stop cleanly.'
    $ExitCode = (@(docker inspect --format '{{.State.ExitCode}}' $ContainerId) -join '').Trim()
    Assert-True ($ExitCode -eq '0') 'M6 authentication product returned a non-zero status.'
    docker compose -f $ComposeFile run --rm `
        -e TEST_RECORDING=/artifacts/m6-auth.mp4 `
        -e TEST_MIN_DURATION=5 -e TEST_MAX_DURATION=180 `
        -e TEST_REQUIRE_PILLARBOX=0 validator
    Assert-True ($LASTEXITCODE -eq 0) 'M6 authentication recording was not finalized correctly.'

    Write-Host 'M6 file authentication, Host/Origin authorization, WebSocket protection, rate limit, probes, metrics, healthcheck, and redaction acceptance passed.'
} finally {
    $Client.Dispose()
    $Handler.Dispose()
    docker compose -f $ComposeFile down --volumes --remove-orphans | Out-Null
    Pop-Location
}
