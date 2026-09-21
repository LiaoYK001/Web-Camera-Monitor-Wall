[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('start', 'stop', 'restart', 'status', 'logs', 'debug', 'frontend', 'test', 'build', 'hotfix', 'shell', 'help')]
    [string]$Action = 'start',
    [switch]$NoBuild,
    [switch]$Frontend,
    [switch]$Full,
    [switch]$IncludeRealMedia,
    [switch]$Long,
    [switch]$Open,
    [switch]$AllowNonDev,
    [string]$Image = 'webobs:dev',
    [int]$FrontendPort = 5173,
    [int]$Tail = 200,
    [string]$EnvFile = '.env'
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false

function Assert-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command is unavailable: $Name"
    }
}

function Show-Usage {
    @'
Usage: .\scripts\dev-local.ps1 [-Action] [options]

Actions: start stop restart status logs debug frontend test build hotfix shell
Options:
  -NoBuild          reuse the local image for start/restart
  -Frontend         start Vite in the background with start/restart
  -Full             run the complete local no-build suite against -Image
  -IncludeRealMedia include private RTSP/MJPEG checks when env vars are set
  -Long             run M7 8/16/32 x 900-second and fault gates
  -Open             open the local frontend URL after start
  -AllowNonDev      allow an explicit experiment outside branch dev
  -Image NAME       local image tag (default: webobs:dev)
  -FrontendPort N   Vite port (default: 5173)
  -Tail N           log lines (default: 200)
  -EnvFile PATH     private env file (default: .env)
'@ | Write-Host
}

function Invoke-Checked([string]$Command, [object[]]$Arguments) {
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed ($LASTEXITCODE): $Command"
    }
}

Assert-Command 'git'
$Repository = (git rev-parse --show-toplevel).Trim()
if (-not $Repository) { throw 'Run this script from the Web Camera Monitor Wall checkout.' }
Set-Location $Repository

$Branch = (git branch --show-current).Trim()
if ($Branch -ne 'dev' -and -not $AllowNonDev) {
    throw "This local development helper is restricted to branch dev (current: '$Branch'). Use -AllowNonDev only for an explicit local experiment."
}

Assert-Command 'docker'
$Compose = @('compose', '--env-file', (Join-Path $Repository $EnvFile), '-f', (Join-Path $Repository 'compose.yaml'))
$StateKey = ($Repository -replace '[^A-Za-z0-9]', '_')
$StateDir = Join-Path ([IO.Path]::GetTempPath()) "webobs-dev-$StateKey"
$FrontendPidFile = Join-Path $StateDir 'vite.pid'
$FrontendLogFile = Join-Path $StateDir 'vite.log'
$FrontendErrorLogFile = Join-Path $StateDir 'vite.error.log'

function Ensure-EnvFile {
    $Resolved = Join-Path $Repository $EnvFile
    if (-not (Test-Path -LiteralPath $Resolved)) {
        if ($EnvFile -ne '.env') { throw "Environment file does not exist: $Resolved" }
        Copy-Item (Join-Path $Repository '.env.example') $Resolved
        Write-Host "Created local $EnvFile from .env.example (it is Git-ignored)."
    }
}

function Invoke-Compose([object[]]$Arguments) {
    Invoke-Checked 'docker' (@($Compose) + $Arguments)
}

function Ensure-ComposeConfig {
    Ensure-EnvFile
    Invoke-Compose @('config', '--quiet')
}

function Set-LocalImage {
    # Keep the tag local and explicit. This helper never runs docker push.
    $env:WEBOBS_IMAGE = $Image
}

function Start-Frontend {
    Assert-Command 'pnpm'
    Ensure-EnvFile
    if (Test-Path -LiteralPath $FrontendPidFile) {
        $ExistingPid = [int](Get-Content -LiteralPath $FrontendPidFile -Raw).Trim()
        if (Get-Process -Id $ExistingPid -ErrorAction SilentlyContinue) {
            Write-Host "Vite is already running (PID $ExistingPid): http://127.0.0.1:$FrontendPort/"
            return
        }
        Remove-Item -LiteralPath $FrontendPidFile -Force -ErrorAction SilentlyContinue
    }
    New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
    $PnpmCommand = Get-Command pnpm.cmd -ErrorAction SilentlyContinue
    if (-not $PnpmCommand) { $PnpmCommand = Get-Command pnpm -ErrorAction Stop }
    $Pnpm = $PnpmCommand.Source
    $Arguments = "dev -- --host 127.0.0.1 --port $FrontendPort"
    if ([IO.Path]::GetExtension($Pnpm) -eq '.ps1') {
        $PnpmArguments = "-NoProfile -ExecutionPolicy Bypass -File `"$Pnpm`" $Arguments"
        $Process = Start-Process -FilePath 'powershell.exe' -ArgumentList $PnpmArguments `
            -WorkingDirectory (Join-Path $Repository 'web') -WindowStyle Hidden `
            -RedirectStandardOutput $FrontendLogFile -RedirectStandardError $FrontendErrorLogFile `
            -PassThru
    } else {
        $Process = Start-Process -FilePath $Pnpm -ArgumentList $Arguments `
            -WorkingDirectory (Join-Path $Repository 'web') -WindowStyle Hidden `
            -RedirectStandardOutput $FrontendLogFile -RedirectStandardError $FrontendErrorLogFile `
            -PassThru
    }
    Set-Content -LiteralPath $FrontendPidFile -Value $Process.Id -NoNewline
    Write-Host "Vite started in the background (PID $($Process.Id)): http://127.0.0.1:$FrontendPort/"
    Write-Host "Vite logs: $FrontendLogFile and $FrontendErrorLogFile"
}

function Stop-Frontend {
    if (-not (Test-Path -LiteralPath $FrontendPidFile)) {
        Write-Host 'Vite is not tracked as running.'
        return
    }
    $FrontendProcessId = [int](Get-Content -LiteralPath $FrontendPidFile -Raw).Trim()
    Remove-Item -LiteralPath $FrontendPidFile -Force -ErrorAction SilentlyContinue
    if (Get-Process -Id $FrontendProcessId -ErrorAction SilentlyContinue) {
        & taskkill.exe /PID $FrontendProcessId /T /F *> $null
    }
    Write-Host "Stopped Vite process tree (PID $FrontendProcessId)."
}

function Show-Status {
    Ensure-ComposeConfig
    Invoke-Compose @('ps')
    try {
        $Health = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8080/api/v1/health' -TimeoutSec 3
        Write-Host "Health: HTTP $($Health.StatusCode)"
    } catch {
        Write-Host 'Health: unavailable at http://127.0.0.1:8080 (the container may be stopped).'
    }
    if (Test-Path -LiteralPath $FrontendPidFile) {
        $FrontendProcessId = [int](Get-Content -LiteralPath $FrontendPidFile -Raw).Trim()
        if (Get-Process -Id $FrontendProcessId -ErrorAction SilentlyContinue) {
            Write-Host "Frontend: running at http://127.0.0.1:$FrontendPort (PID $FrontendProcessId)"
        } else {
            Write-Host 'Frontend: stale PID file; run frontend or stop.'
        }
    } else {
        Write-Host 'Frontend: not started by this helper.'
    }
}

function Wait-Health {
    for ($Attempt = 0; $Attempt -lt 30; $Attempt++) {
        try {
            $Response = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8080/api/v1/health' -TimeoutSec 2
            if ($Response.StatusCode -ge 200 -and $Response.StatusCode -lt 300) { return }
        } catch { }
        Start-Sleep -Seconds 1
    }
    throw 'webobs health endpoint did not become ready within 30 seconds.'
}

function Start-Backend([bool]$Build) {
    Ensure-ComposeConfig
    Set-LocalImage
    if ($Build) {
        Invoke-Compose @('build', 'webobs')
    }
    Invoke-Compose @('up', '-d', '--no-build', 'webobs')
    Wait-Health
    Write-Host "Backend ready: http://127.0.0.1:8080/ (local image: $Image)"
}

function Run-Tests {
    Assert-Command 'pnpm'
    Assert-Command 'python'
    if ($Full) {
        $FullArguments = @('-NoProfile', '-File', (Join-Path $Repository 'scripts/test-local-full.ps1'), '-Image', $Image)
        if ($IncludeRealMedia) { $FullArguments += '-IncludeRealMedia' }
        if ($Long) { $FullArguments += '-Long' }
        Invoke-Checked 'pwsh' $FullArguments
        return
    }
    & (Join-Path $Repository 'tests/run-public-audit.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'Public audit failed.' }
    Push-Location (Join-Path $Repository 'web')
    try {
        Invoke-Checked 'pnpm' @('typecheck')
        Invoke-Checked 'pnpm' @('test:iwa')
        Invoke-Checked 'pnpm' @('test:local')
    } finally { Pop-Location }
}

switch ($Action) {
    'help' { Show-Usage }
    'start' {
        Start-Backend (-not $NoBuild)
        if ($Frontend) { Start-Frontend }
        if ($Open) { Start-Process "http://127.0.0.1:$FrontendPort/" }
        elseif (-not $Frontend) { Write-Host 'For hot reload run: .\scripts\dev-local.ps1 frontend' }
    }
    'stop' { Stop-Frontend; Ensure-ComposeConfig; Invoke-Compose @('stop') }
    'restart' { Stop-Frontend; Start-Backend (-not $NoBuild); if ($Frontend) { Start-Frontend } }
    'status' { Show-Status }
    'logs' { Ensure-ComposeConfig; Invoke-Compose @('logs', '--tail', "$Tail", '-f', 'webobs') }
    'debug' { Show-Status; Ensure-ComposeConfig; Invoke-Compose @('logs', '--tail', "$Tail", 'webobs') }
    'frontend' { Start-Frontend }
    'test' { Run-Tests }
    'build' { Ensure-ComposeConfig; Set-LocalImage; Invoke-Compose @('build', 'webobs') }
    'hotfix' {
        Ensure-ComposeConfig
        Set-LocalImage
        Invoke-Compose @('build', 'webobs')
        Invoke-Compose @('up', '-d', '--force-recreate', '--no-build', 'webobs')
        Wait-Health
        Write-Host "Hotfix image is running locally as $Image; nothing was pushed."
    }
    'shell' { Ensure-ComposeConfig; Invoke-Compose @('exec', 'webobs', 'sh') }
}
