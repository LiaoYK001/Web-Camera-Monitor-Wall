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
# dev-lan-environment.ps1 — 局域网联调入口 / LAN co-dev entry.
# 与 scripts/dev.ps1 相同流程，额外开启 LAN 端口转发：
#   Vite 监听 0.0.0.0，/api 代理把 Host/Origin 改写回 127.0.0.1；
#   后端仍只绑定本机回环。局域网成员访问 http://<本机IPv4>:<Port>/。
# Same pipeline as scripts/dev.ps1, plus a LAN port-forward:
#   Vite binds 0.0.0.0 and the /api proxy rewrites Host/Origin back to
#   loopback so the backend stays local-only. LAN peers use
#   http://<host-IPv4>:<Port>/.
$ErrorActionPreference = 'Stop'
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Host '[ERROR] Install Node.js 24 LTS, reopen PowerShell, then retry.' -ForegroundColor Red
    exit 1
}
if ($LanHost -and $LanHost -notmatch '^\d{1,3}(\.\d{1,3}){3}$') {
    Write-Host '[ERROR] -LanHost must be a dotted IPv4 address (e.g. 192.168.1.20).' -ForegroundColor Red
    exit 1
}
Write-Host '[WebOBS] LAN mode：仅限受信任局域网联调，不要对公网暴露 / Trusted LAN only; never expose to the public Internet.' -ForegroundColor Yellow
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
