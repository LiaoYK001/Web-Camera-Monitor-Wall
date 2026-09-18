[CmdletBinding()]
param(
    [ValidateSet('native', 'frontend', 'container')][string]$Mode = 'native',
    [switch]$Setup, [switch]$Check, [switch]$Composite, [switch]$Build, [switch]$Soak,
    [string]$Api = 'http://127.0.0.1:8080', [int]$Port = 5173,
    [string]$Distro = 'Ubuntu-24.04',
    [ValidateSet('docker', 'podman')][string]$Engine = 'docker',
    [string]$Builder = '', [switch]$Help
)
$ErrorActionPreference = 'Stop'
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Host '[ERROR] Install Node.js 24 LTS, reopen PowerShell, then retry.' -ForegroundColor Red
    exit 1
}
$arguments = @((Join-Path $PSScriptRoot 'dev.mjs'), '--mode', $Mode, '--api', $Api, '--port', "$Port", '--distro', $Distro, '--engine', $Engine)
if ($Setup) { $arguments += '--setup' }
if ($Check) { $arguments += '--check' }
if ($Composite) { $arguments += '--composite' }
if ($Build) { $arguments += '--build' }
if ($Soak) { $arguments += '--soak' }
if ($Builder) { $arguments += @('--builder', $Builder) }
if ($Help) { $arguments += '--help' }
# Node owns child processes and reports native stderr without PS5 RemoteException.
& node @arguments
exit $LASTEXITCODE
