param(
    [string]$ComposeFile = (Join-Path $PSScriptRoot 'compose.smoke.yaml'),
    [string]$ArtifactDirectory = (Join-Path $PSScriptRoot 'artifacts')
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false

$SignalContainer = 'webobs-m0-signal-test'

function Invoke-ExpectedExit {
    param(
        [int]$Expected,
        [string]$Label,
        [scriptblock]$Command
    )

    $commandOutput = (& $Command 2>&1 | Out-String)
    $status = $LASTEXITCODE
    if ($status -ne $Expected) {
        Write-Error "$Label`: expected exit $Expected, got $status`n$commandOutput"
    }
    Write-Host "$Label`: exit $status verified"
    return $commandOutput
}

function Remove-SignalContainer {
    docker rm -f $SignalContainer 2>$null | Out-Null
}

New-Item -ItemType Directory -Force -Path $ArtifactDirectory | Out-Null
Remove-Item -LiteralPath (Join-Path $ArtifactDirectory 'signal.mp4') -Force -ErrorAction SilentlyContinue
Remove-SignalContainer

try {
    Invoke-ExpectedExit 2 'missing URL' {
        docker run --rm --entrypoint /opt/obs/bin/webobsd -e WEBOBS_RTSP_URL= webobs:m0
    } | Out-Null

    Invoke-ExpectedExit 5 'missing output directory' {
        docker run --rm --entrypoint /opt/obs/bin/webobsd `
            -e WEBOBS_RTSP_URL=rtsp://camera.invalid/live `
            -e WEBOBS_OUTPUT=/directory-that-does-not-exist/capture.mp4 `
            webobs:m0
    } | Out-Null

    $credentialOutput = Invoke-ExpectedExit 4 'unreachable RTSP' {
        docker run --rm `
            -e WEBOBS_RTSP_URL=rtsp://test-user:supersecret@127.0.0.1:65534/unreachable `
            -e WEBOBS_OUTPUT=/recordings/unreachable.mp4 `
            -e WEBOBS_CONNECT_TIMEOUT_SECONDS=1 `
            -e WEBOBS_LOG_LEVEL=debug `
            webobs:m0
    }
    if ($credentialOutput.Contains('test-user') -or $credentialOutput.Contains('supersecret')) {
        throw 'credential redaction: clear-text RTSP credentials leaked'
    }
    if (-not $credentialOutput.Contains('rtsp://***:***@127.0.0.1')) {
        throw 'credential redaction: masked URL was not found in logs'
    }
    Write-Host 'credential redaction: verified'

    $artifactMount = "${ArtifactDirectory}:/artifacts"
    Invoke-ExpectedExit 5 'existing output refusal' {
        docker run --rm --entrypoint /opt/obs/bin/webobsd `
            -v $artifactMount `
            -e WEBOBS_RTSP_URL=rtsp://camera.invalid/live `
            -e WEBOBS_OUTPUT=/artifacts/smoke.mp4 `
            webobs:m0
    } | Out-Null

    docker compose -f $ComposeFile up -d mediamtx fixture
    if ($LASTEXITCODE -ne 0) { throw 'Could not start RTSP fixture for SIGTERM test' }
    docker compose -f $ComposeFile run --detach --name $SignalContainer `
        -e WEBOBS_OUTPUT=/artifacts/signal.mp4 `
        -e WEBOBS_DURATION_SECONDS=0 `
        -e WEBOBS_CONNECT_TIMEOUT_SECONDS=30 `
        webobs | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not start SIGTERM test container' }

    $started = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        $logs = (docker logs $SignalContainer 2>&1 | Out-String)
        if ($logs.Contains('Recording started:')) {
            $started = $true
            break
        }
        $running = docker inspect -f '{{.State.Running}}' $SignalContainer
        if ($running -ne 'true') { break }
        Start-Sleep -Seconds 1
    }
    if (-not $started) {
        docker logs $SignalContainer
        throw 'SIGTERM test: recording did not start'
    }

    Start-Sleep -Seconds 3
    docker stop --time 20 $SignalContainer | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'SIGTERM test: docker stop failed' }
    $signalExit = docker inspect -f '{{.State.ExitCode}}' $SignalContainer
    if ([int]$signalExit -ne 0) {
        docker logs $SignalContainer
        throw "SIGTERM test: expected exit 0, got $signalExit"
    }
    docker compose -f $ComposeFile run --rm `
        -e TEST_RECORDING=/artifacts/signal.mp4 `
        -e TEST_MIN_DURATION=2 `
        -e TEST_MAX_DURATION=10 `
        validator
    if ($LASTEXITCODE -ne 0) { throw 'SIGTERM test: recording validation failed' }
    Write-Host 'SIGTERM test: graceful MP4 finalization verified'
}
finally {
    Remove-SignalContainer
}
