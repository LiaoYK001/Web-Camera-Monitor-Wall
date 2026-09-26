[CmdletBinding()]
param(
    [ValidateSet('native', 'frontend', 'container')][string]$Mode = 'native',
    [switch]$Setup, [switch]$Check, [switch]$Composite, [switch]$Build, [switch]$Soak,
    [string]$Api = 'http://127.0.0.1:8080', [int]$Port = 5173,
    [string]$Distro = 'Ubuntu-24.04',
    [ValidateSet('docker', 'podman')][string]$Engine = 'docker',
    [string]$Builder = '',
    [string]$LanHost = '',
    [switch]$Help
)
# dev-lan-environment.ps1 -- LAN co-dev entry (same pipeline as scripts/dev.ps1).
# Enables a LAN HTTPS port-forward: Vite binds 0.0.0.0 with a self-signed cert
# (SAN includes the LAN IP) and the /api proxy rewrites Host/Origin back to
# 127.0.0.1 so the backend stays loopback-only. LAN peers use
# https://<host-IPv4>:<Port>/ and must trust the cert once so
# window.isSecureContext enables browser media and PWA features.
# Keep Write-Host strings ASCII-only: Windows PowerShell 5.1 parses a BOM-less
# .ps1 as ANSI and would garble UTF-8 Chinese here. Bilingual notes live in
# scripts/dev.mjs.
$ErrorActionPreference = 'Stop'
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Host '[ERROR] Install Node.js 24 LTS, reopen PowerShell, then retry.' -ForegroundColor Red
    exit 1
}
if ($LanHost -and $LanHost -notmatch '^\d{1,3}(\.\d{1,3}){3}$') {
    Write-Host '[ERROR] -LanHost must be a dotted IPv4 address (e.g. 192.168.1.20).' -ForegroundColor Red
    exit 1
}
Write-Host '[WebOBS] LAN mode (HTTPS): trusted LAN only; never expose to the public Internet. Trust the self-signed cert once per browser.' -ForegroundColor Yellow
$arguments = @((Join-Path $PSScriptRoot 'dev.mjs'), '--lan', '--mode', $Mode, '--api', $Api, '--port', "$Port", '--distro', $Distro, '--engine', $Engine)
if ($LanHost) { $arguments += @('--lan-host', $LanHost) }
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
