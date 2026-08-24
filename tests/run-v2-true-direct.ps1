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

    $ProbeServices = @('v2-probe', 'native-rtsp-h264', 'native-rtsp-h265',
        'native-mjpeg', 'native-hls')
    $ProbeIds = @{}
    foreach ($Service in $ProbeServices) {
        $ProbeIds[$Service] = (& docker compose -p $Project -f $ComposeFile ps --all --quiet $Service).Trim()
    }
    $WebObsId = (& docker compose -p $Project -f $ComposeFile ps --all --quiet webobs).Trim()
    if (-not $WebObsId -or @($ProbeIds.Values | Where-Object { -not $_ }).Count -gt 0) {
        throw 'Fixture container identities are unavailable.'
    }
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
    Write-Host 'v2 deterministic True Direct gate passed: the production client pipeline decoded H.264/H.265 RTSP, Server Push MJPEG and HLS; the control server had no camera network or media helper. WHEP remains an exact-runtime release gate.'
}
finally {
    & docker compose -p $Project -f $ComposeFile down --volumes --remove-orphans | Out-Null
    Remove-Item Env:WEBOBS_TEST_IMAGE -ErrorAction SilentlyContinue
}
