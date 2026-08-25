[CmdletBinding()]
param(
    [string]$Image = $(if ($env:WEBOBS_TEST_IMAGE) { $env:WEBOBS_TEST_IMAGE } else { 'webobs:v2-m1-dev' })
)

$ErrorActionPreference = 'Stop'
$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ComposeFile = Join-Path $PSScriptRoot 'compose.v2-true-direct.yaml'
$Project = "webobsv2direct$PID"
$env:WEBOBS_TEST_IMAGE = $Image

try {
    & docker image inspect $Image | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Test image '$Image' is unavailable." }
    & docker compose -p $Project -f $ComposeFile up --detach --build
    if ($LASTEXITCODE -ne 0) { throw 'Could not start the True Direct fixture.' }

    $ProbeServices = @('v2-probe', 'v2-fallback-probe', 'v2-nvr-coexist-probe',
        'native-rtsp-h264', 'native-rtsp-h265',
        'native-mjpeg', 'native-hls', 'native-batch', 'native-reconnect',
        'native-lifecycle')
    $ProbeIds = @{}
    foreach ($Service in $ProbeServices) {
        $ProbeIds[$Service] = (& docker compose -p $Project -f $ComposeFile ps --all --quiet $Service).Trim()
    }
    $WebObsId = (& docker compose -p $Project -f $ComposeFile ps --all --quiet webobs).Trim()
    $FallbackId = (& docker compose -p $Project -f $ComposeFile ps --all --quiet webobs-fallback).Trim()
    if (-not $WebObsId -or -not $FallbackId -or @($ProbeIds.Values | Where-Object { -not $_ }).Count -gt 0) {
        throw 'Fixture container identities are unavailable.'
    }
    $ReconnectId = (& docker compose -p $Project -f $ComposeFile ps --all --quiet native-reconnect).Trim()
    if (-not $ReconnectId) { throw 'Native reconnect probe identity is unavailable.' }
    $Ready = $false
    for ($Attempt = 0; $Attempt -lt 45; $Attempt++) {
        $ReconnectLogs = (& docker compose -p $Project -f $ComposeFile logs --no-color native-reconnect) -join "`n"
        if ($ReconnectLogs.Contains('"result":"ready"')) { $Ready = $true; break }
        if ((& docker inspect --format '{{.State.Status}}' $ReconnectId).Trim() -ne 'running') { break }
        Start-Sleep -Seconds 1
    }
    if (-not $Ready) { throw 'Native reconnect probe did not become ready.' }
    & docker network disconnect --force "${Project}_camera-media" $ReconnectId
    if ($LASTEXITCODE -ne 0) { throw 'Could not isolate the native reconnect probe.' }
    Start-Sleep -Seconds 5
    $ReconnectStarted = [System.Diagnostics.Stopwatch]::StartNew()
    & docker network connect "${Project}_camera-media" $ReconnectId
    if ($LASTEXITCODE -ne 0) { throw 'Could not restore the native reconnect probe network.' }
    $Reconnected = $false
    for ($Attempt = 0; $Attempt -lt 10; $Attempt++) {
        $ReconnectLogs = (& docker compose -p $Project -f $ComposeFile logs --no-color native-reconnect) -join "`n"
        if ($ReconnectLogs.Contains('"result":"reconnected"')) { $Reconnected = $true; break }
        Start-Sleep -Seconds 1
    }
    $ReconnectStarted.Stop()
    if (-not $Reconnected -or $ReconnectStarted.Elapsed.TotalSeconds -gt 10) {
        throw 'Native reconnect exceeded the ten-second recovery budget.'
    }
    $LifecycleId = $ProbeIds['native-lifecycle']
    $LifecycleReady = $false
    for ($Attempt = 0; $Attempt -lt 45; $Attempt++) {
        $LifecycleLogs = (& docker compose -p $Project -f $ComposeFile logs --no-color native-lifecycle) -join "`n"
        if ($LifecycleLogs.Contains('"result":"ready"')) { $LifecycleReady = $true; break }
        if ((& docker inspect --format '{{.State.Status}}' $LifecycleId).Trim() -ne 'running') { break }
        Start-Sleep -Seconds 1
    }
    if (-not $LifecycleReady) { throw 'Native lifecycle probe did not become ready.' }
    & docker exec $LifecycleId sh -ceu "printf '%s`n' background > /tmp/webobs-lifecycle-command"
    if ($LASTEXITCODE -ne 0) { throw 'Could not request native background release.' }
    $Released = $false
    for ($Attempt = 0; $Attempt -lt 5; $Attempt++) {
        $LifecycleLogs = (& docker compose -p $Project -f $ComposeFile logs --no-color native-lifecycle) -join "`n"
        if ($LifecycleLogs.Contains('"result":"background-released"')) { $Released = $true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $Released) { throw 'Native lifecycle probe did not release media within five seconds.' }
    & docker exec $LifecycleId sh -ceu "printf '%s`n' foreground > /tmp/webobs-lifecycle-command"
    if ($LASTEXITCODE -ne 0) { throw 'Could not request native foreground resume.' }
    foreach ($Service in $ProbeServices) {
        $ProbeId = $ProbeIds[$Service]
        $Exited = $false
        for ($Attempt = 0; $Attempt -lt 240; $Attempt++) {
            $State = (& docker inspect --format '{{.State.Status}}' $ProbeId).Trim()
            if ($State -eq 'exited') { $Exited = $true; break }
            if ($State -notin @('running', 'created')) { break }
            Start-Sleep -Seconds 1
        }
        & docker compose -p $Project -f $ComposeFile logs --no-color $Service
        if (-not $Exited) { throw "True Direct probe '$Service' did not finish within 240 seconds." }
        $ProbeExit = (& docker inspect --format '{{.State.ExitCode}}' $ProbeId).Trim()
        if ($ProbeExit -ne '0') { throw "True Direct probe '$Service' failed with exit code $ProbeExit." }
    }

    $Inspect = @(& docker inspect $WebObsId | ConvertFrom-Json)[0]
    $Networks = @($Inspect.NetworkSettings.Networks.PSObject.Properties.Name)
    if ($Networks.Count -ne 1 -or $Networks[0] -ne "${Project}_control") {
        throw "Server network isolation failed: observed '$($Networks -join ',')'."
    }
    & docker exec $WebObsId sh -c 'if getent hosts camera >/dev/null 2>&1; then exit 7; fi; if pgrep -x ffmpeg || pgrep -x mediamtx || pgrep -x obs-ffmpeg-mux; then exit 8; fi'
    if ($LASTEXITCODE -ne 0) { throw 'Server could reach the camera or retained a media helper.' }
    $ServerLogs = (& docker compose -p $Project -f $ComposeFile logs --no-color webobs) -join "`n"
    if ($ServerLogs -notmatch [regex]::Escape('Gateway Direct-only mode is active; OBS decode, scene composition, and encoding are not initialized')) {
        throw 'Server did not report the no-composition runtime mode.'
    }
    if ($ServerLogs.Contains('rtsp://camera:8554')) {
        throw 'Camera endpoint leaked into server logs.'
    }
    & docker exec $FallbackId sh -c "curl -fsS http://127.0.0.1:9997/v3/config/paths/list | grep -Eq 'direct-|hybrid-' && exit 9 || ! pgrep -x ffmpeg"
    if ($LASTEXITCODE -ne 0) { throw 'Released v2 fallback retained a MediaMTX route or transcoder.' }
    $FallbackLogs = (& docker compose -p $Project -f $ComposeFile logs --no-color webobs-fallback) -join "`n"
    if ($FallbackLogs -match 'fixture-viewer|fixture-password|rtsp://[^/\s]+:[^@/\s]+@') {
        throw 'Fallback logs exposed camera credentials.'
    }
    Write-Host 'v2 deterministic gate passed: production client RTSP/MJPEG/HLS stayed off-server, forced network and lifecycle transitions recovered within budget, 16 concurrent viewers did not add NVR upstream sessions, and authenticated Gateway fallback cleaned up without residue. Exact-runtime WHEP is verified by the locked desktop gate.'
}
finally {
    & docker compose -p $Project -f $ComposeFile down --volumes --remove-orphans | Out-Null
    Remove-Item Env:WEBOBS_TEST_IMAGE -ErrorAction SilentlyContinue
}
