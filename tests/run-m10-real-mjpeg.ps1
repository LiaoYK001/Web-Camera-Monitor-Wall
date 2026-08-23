[CmdletBinding()]
param(
    [string]$Image = $(if ($env:WEBOBS_IMAGE) { $env:WEBOBS_IMAGE } else { 'webobs:m0' })
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false

$streamUrl = $env:WEBOBS_REAL_MJPEG_URL
$parsed = [Uri]$null
if ([string]::IsNullOrWhiteSpace($streamUrl) -or
    -not [Uri]::TryCreate($streamUrl, [UriKind]::Absolute, [ref]$parsed) -or
    $parsed.Scheme -notin @('http', 'https') -or
    ($null -ne $parsed.UserInfo -and $parsed.UserInfo.Length -gt 0)) {
    throw 'Set WEBOBS_REAL_MJPEG_URL to an HTTP(S) stream without embedded credentials.'
}

function Invoke-PrivateStreamContainer {
    param([string]$Script)
    $output = @(& docker run --rm `
        -e WEBOBS_REAL_MJPEG_URL `
        --entrypoint /bin/sh `
        $Image -ec $Script 2>&1)
    $status = $LASTEXITCODE
    $safeOutput = ($output -join "`n").Replace($streamUrl, '<redacted-camera>')
    if ($status -ne 0) {
        throw "Private MJPEG validation failed (exit $status):`n$safeOutput"
    }
    return $safeOutput
}

$probe = Invoke-PrivateStreamContainer @'
ffprobe -v error -rw_timeout 8000000 -select_streams v:0 \
  -show_entries stream=codec_name,width,height,r_frame_rate,avg_frame_rate \
  -of json "$WEBOBS_REAL_MJPEG_URL"
'@ | ConvertFrom-Json -Depth 16

$video = @($probe.streams)[0]
if ($null -eq $video -or $video.codec_name -ne 'mjpeg' -or
    [int]$video.width -le 0 -or [int]$video.height -le 0) {
    throw 'The endpoint did not negotiate a decodable Motion JPEG video stream.'
}

Invoke-PrivateStreamContainer @'
ffmpeg -hide_banner -loglevel error -rw_timeout 8000000 \
  -i "$WEBOBS_REAL_MJPEG_URL" -frames:v 5 -f null -
'@ | Out-Null

Write-Host ("Real server-push MJPEG gate passed: codec=mjpeg, {0}x{1}, rate={2}, decodedFrames=5; endpoint redacted." -f `
    $video.width, $video.height, $video.r_frame_rate)
