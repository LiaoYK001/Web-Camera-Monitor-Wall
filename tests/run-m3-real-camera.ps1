[CmdletBinding()]
param(
    [switch]$SkipBuild,
    [string]$EnvFile,
    [string]$ChromePath = $env:WEBOBS_CHROME_BIN,
    [ValidateRange(30, 3600)]
    [int]$DurationSeconds = 30,
    [ValidateRange(16, 8192)]
    [int]$Width = 1920,
    [ValidateRange(16, 8192)]
    [int]$Height = 1080,
    [ValidateRange(1, 120)]
    [int]$Fps = 30,
    [ValidateRange(50, 100000)]
    [int]$BitrateKbps = 6000,
    [ValidateRange(1, 300)]
    [int]$ConnectTimeoutSeconds = 20,
    [ValidateSet('tcp', 'udp')]
    [string]$RtspTransport = 'tcp'
)

$ErrorActionPreference = 'Stop'

$Arguments = @{
    SkipBuild = $SkipBuild
    ChromePath = $ChromePath
    DurationSeconds = $DurationSeconds
    Width = $Width
    Height = $Height
    Fps = $Fps
    BitrateKbps = $BitrateKbps
    ConnectTimeoutSeconds = $ConnectTimeoutSeconds
    RtspTransport = $RtspTransport
    PlaybackMode = 'direct'
}
if (-not [string]::IsNullOrWhiteSpace($EnvFile)) { $Arguments.EnvFile = $EnvFile }

& (Join-Path $PSScriptRoot 'run-m2-real-camera.ps1') @Arguments
