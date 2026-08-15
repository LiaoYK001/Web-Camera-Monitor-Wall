[CmdletBinding()]
param([switch]$SkipBuild)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false

$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ComposeFile = Join-Path $PSScriptRoot 'compose.smoke.yaml'
$ArtifactDirectory = Join-Path $PSScriptRoot 'artifacts'
$SecretDirectory = Join-Path $ArtifactDirectory 'm6-tls-secrets'
$Service = 'webobs-tls-turn'
$PublicAuthority = 'monitor.test:18443'

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

function New-RandomSecret {
    param([int]$Bytes = 32)
    $Buffer = [byte[]]::new($Bytes)
    [Security.Cryptography.RandomNumberGenerator]::Fill($Buffer)
    return [Convert]::ToHexString($Buffer).ToLowerInvariant()
}

& (Join-Path $PSScriptRoot 'run-public-audit.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Public repository audit failed.' }
Get-Command docker -ErrorAction Stop | Out-Null
Get-Command curl.exe -ErrorAction Stop | Out-Null

New-Item -ItemType Directory -Force -Path $SecretDirectory | Out-Null
$Username = 'm6-tls-operator'
$Password = New-RandomSecret
$TurnUsername = 'AUTH_SECRET'
$TurnPassword = New-RandomSecret
[IO.File]::WriteAllText((Join-Path $SecretDirectory 'auth-username'), $Username + "`n")
[IO.File]::WriteAllText((Join-Path $SecretDirectory 'auth-password'), $Password + "`n")
[IO.File]::WriteAllText((Join-Path $SecretDirectory 'turn-username'), $TurnUsername + "`n")
[IO.File]::WriteAllText((Join-Path $SecretDirectory 'turn-password'), $TurnPassword + "`n")

$Rsa = [Security.Cryptography.RSA]::Create(2048)
try {
    $Request = [Security.Cryptography.X509Certificates.CertificateRequest]::new(
        'CN=monitor.test', $Rsa, [Security.Cryptography.HashAlgorithmName]::SHA256,
        [Security.Cryptography.RSASignaturePadding]::Pkcs1)
    $San = [Security.Cryptography.X509Certificates.SubjectAlternativeNameBuilder]::new()
    $San.AddDnsName('monitor.test')
    $Request.CertificateExtensions.Add($San.Build())
    $Request.CertificateExtensions.Add(
        [Security.Cryptography.X509Certificates.X509BasicConstraintsExtension]::new($false, $false, 0, $true))
    $Certificate = $Request.CreateSelfSigned([DateTimeOffset]::UtcNow.AddMinutes(-5),
        [DateTimeOffset]::UtcNow.AddHours(2))
    try {
        [IO.File]::WriteAllText((Join-Path $SecretDirectory 'tls-cert.pem'), $Certificate.ExportCertificatePem())
        [IO.File]::WriteAllText((Join-Path $SecretDirectory 'tls-key.pem'), $Rsa.ExportPkcs8PrivateKeyPem())
    } finally {
        $Certificate.Dispose()
    }
} finally {
    $Rsa.Dispose()
}

$HeaderPath = Join-Path $ArtifactDirectory 'm6-tls-headers.txt'
$BodyPath = Join-Path $ArtifactDirectory 'm6-tls-body.json'
$RecordingPath = Join-Path $ArtifactDirectory 'm6-tls-turn.mp4'
[IO.File]::Delete($RecordingPath)
$ContainerId = $null

Push-Location $RepositoryRoot
try {
    docker compose -f $ComposeFile down --volumes --remove-orphans | Out-Null
    if (-not $SkipBuild) {
        docker compose -f $ComposeFile build $Service
        Assert-True ($LASTEXITCODE -eq 0) 'M6 TLS product image failed to build.'
    }
    $RejectedTls = (@(docker run --rm `
        -e WEBOBS_TLS_ENABLED=true `
        -e WEBOBS_LISTEN_ADDRESS=0.0.0.0 `
        -e WEBOBS_ALLOW_INSECURE_REMOTE=false `
        webobs:m0 2>&1) -join "`n")
    Assert-True ($LASTEXITCODE -eq 3 -and
        $RejectedTls -match 'TLS mode requires WEBOBS_LISTEN_ADDRESS=127\.0\.0\.1') `
        'TLS mode did not reject an externally reachable backend listener.'
    $RejectedTurn = (@(docker run --rm `
        -e WEBOBS_TURN_URL='turn:relay.example.invalid:3478?transport=tcp' `
        -e WEBOBS_WEBRTC_ENABLED=true `
        webobs:m0 2>&1) -join "`n")
    Assert-True ($LASTEXITCODE -eq 3 -and
        $RejectedTurn -match 'TURN username file path must be absolute') `
        'TURN mode did not reject missing secret-file configuration.'

    docker compose -f $ComposeFile up --no-build -d mediamtx fixture $Service
    Assert-True ($LASTEXITCODE -eq 0) 'M6 TLS/TURN fixture failed to start.'
    $ContainerId = (@(docker compose -f $ComposeFile ps -q $Service) -join '').Trim()
    Assert-True (-not [string]::IsNullOrWhiteSpace($ContainerId)) 'M6 TLS product container ID is unavailable.'

    $Ready = $false
    $Deadline = [DateTime]::UtcNow.AddSeconds(60)
    while ([DateTime]::UtcNow -lt $Deadline) {
        curl.exe --silent --show-error --fail --noproxy '*' `
            --cacert (Join-Path $SecretDirectory 'tls-cert.pem') `
            --resolve "$PublicAuthority`:127.0.0.1" `
            -u "${Username}:$Password" -D $HeaderPath -o $BodyPath `
            "https://$PublicAuthority/api/v1/ready" 2>$null
        if ($LASTEXITCODE -eq 0) { $Ready = $true; break }
        Start-Sleep -Milliseconds 250
    }
    Assert-True $Ready 'The trusted HTTPS endpoint did not become ready.'
    $Headers = Get-Content -LiteralPath $HeaderPath -Raw
    $Body = Get-Content -LiteralPath $BodyPath -Raw
    Assert-True ($Headers -match '(?im)^HTTP/\S+ 200' -and
        $Headers -match '(?im)^Strict-Transport-Security: max-age=31536000; includeSubDomains\s*$' -and
        $Headers -notmatch '(?im)^Server:' -and $Body -eq '{"status":"ready"}') `
        'HTTPS readiness response or hardened proxy headers were incorrect.'

    curl.exe --silent --show-error --fail --noproxy '*' `
        --cacert (Join-Path $SecretDirectory 'tls-cert.pem') `
        --resolve "$PublicAuthority`:127.0.0.1" `
        -u "${Username}:$Password" -o $BodyPath `
        "https://$PublicAuthority/api/v1/scene" 2>$null
    Assert-True ($LASTEXITCODE -eq 0) 'Authenticated scene API failed through HTTPS.'

    $PublishedPorts = (@(docker port $ContainerId) -join "`n")
    Assert-True ($PublishedPorts -match '8443/tcp' -and $PublishedPorts -notmatch '8080/tcp') `
        'TLS deployment must publish HTTPS without publishing the backend HTTP port.'
    $Processes = (@(docker exec $ContainerId sh -c 'for f in /proc/[0-9]*/comm; do cat "$f" 2>/dev/null || true; done') -join "`n")
    Assert-True ($Processes -match '(?m)^caddy$' -and $Processes -match '(?m)^mediamtx$') `
        'The single product container did not supervise both HTTPS and media gateways.'

    $MediaConfigText = (@(docker exec $ContainerId curl -fsS `
        http://127.0.0.1:9997/v3/config/global/get) -join '')
    Assert-True ($LASTEXITCODE -eq 0) 'MediaMTX runtime configuration was not readable inside the container.'
    $MediaConfig = $MediaConfigText | ConvertFrom-Json
    $IceServer = @($MediaConfig.webrtcICEServers2)[0]
    Assert-True ($MediaConfig.webrtcICEServers2.Count -eq 1 -and
        $IceServer.url -eq 'turn:relay.example.invalid:3478?transport=tcp' -and
        $IceServer.username -eq $TurnUsername -and
        $IceServer.password -eq $TurnPassword -and $IceServer.clientOnly -eq $true) `
        'TURN secret-file settings were not applied exactly once to MediaMTX.'

    $Inspect = (@(docker inspect $ContainerId) -join "`n")
    Assert-True ($Inspect -notmatch [Regex]::Escape($Password) -and
        $Inspect -notmatch [Regex]::Escape($TurnPassword)) `
        'A runtime credential leaked into inspectable container environment/configuration.'
    $Logs = (@(docker logs $ContainerId 2>&1) -join "`n")
    Assert-True ($Logs -notmatch [Regex]::Escape($Password) -and
        $Logs -notmatch [Regex]::Escape($TurnPassword) -and
        $Logs -notmatch 'Authorization:|userinfo') `
        'A runtime credential leaked into product logs.'

    $HealthDeadline = [DateTime]::UtcNow.AddSeconds(20)
    $HealthStatus = ''
    while ([DateTime]::UtcNow -lt $HealthDeadline) {
        $HealthStatus = (@(docker inspect --format '{{.State.Health.Status}}' $ContainerId) -join '').Trim()
        if ($HealthStatus -eq 'healthy') { break }
        Assert-True ($HealthStatus -ne 'unhealthy') 'The HTTPS-aware Docker healthcheck became unhealthy.'
        Start-Sleep -Milliseconds 500
    }
    Assert-True ($HealthStatus -eq 'healthy') 'The HTTPS-aware Docker healthcheck did not become healthy.'

    docker stop --time 20 $ContainerId | Out-Null
    Assert-True ($LASTEXITCODE -eq 0) 'M6 TLS product container did not stop cleanly.'
    $DurationText = (@(docker run --rm --entrypoint ffprobe `
        -v "$ArtifactDirectory`:/artifacts:ro" webobs:m0 `
        -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 `
        /artifacts/m6-tls-turn.mp4) -join '').Trim()
    $Duration = 0.0
    Assert-True ($LASTEXITCODE -eq 0 -and
        [double]::TryParse($DurationText, [Globalization.NumberStyles]::Float,
            [Globalization.CultureInfo]::InvariantCulture, [ref]$Duration) -and $Duration -ge 5.0) `
        'Graceful TLS deployment shutdown did not finalize a playable recording.'
    Write-Host 'M6 trusted HTTPS, backend isolation, TURN secret-file configuration, health, supervision, and redaction acceptance passed.'
} finally {
    docker compose -f $ComposeFile down --volumes --remove-orphans | Out-Null
    Pop-Location
}
