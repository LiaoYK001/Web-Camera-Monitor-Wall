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

    $ProbeId = (& docker compose -p $Project -f $ComposeFile ps --all --quiet v2-probe).Trim()
    $WebObsId = (& docker compose -p $Project -f $ComposeFile ps --all --quiet webobs).Trim()
    if (-not $ProbeId -or -not $WebObsId) { throw 'Fixture container identities are unavailable.' }
    $Exited = $false
    for ($Attempt = 0; $Attempt -lt 180; $Attempt++) {
        $State = (& docker inspect --format '{{.State.Status}}' $ProbeId).Trim()
        if ($State -eq 'exited') { $Exited = $true; break }
        if ($State -notin @('running', 'created')) { break }
        Start-Sleep -Seconds 1
    }
    & docker compose -p $Project -f $ComposeFile logs --no-color v2-probe
    if (-not $Exited) { throw 'True Direct probe did not finish within 180 seconds.' }
    $ProbeExit = (& docker inspect --format '{{.State.ExitCode}}' $ProbeId).Trim()
    if ($ProbeExit -ne '0') { throw "True Direct probe failed with exit code $ProbeExit." }

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
    Write-Host 'v2 architecture-level True Direct gate passed: control-only server network, client-owned H.264 RTSP decode, no server media helper.'
}
finally {
    & docker compose -p $Project -f $ComposeFile down --volumes --remove-orphans | Out-Null
    Remove-Item Env:WEBOBS_TEST_IMAGE -ErrorAction SilentlyContinue
}
