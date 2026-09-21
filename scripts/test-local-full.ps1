[CmdletBinding()]
param(
    [string]$Image = $(if ($env:WEBOBS_DEV_IMAGE) { $env:WEBOBS_DEV_IMAGE } else { 'webobs:dev' }),
    [switch]$IncludeRealMedia,
    [switch]$Long
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false

$Repository = (git rev-parse --show-toplevel).Trim()
if (-not $Repository) { throw 'Run this script from the Web Camera Monitor Wall checkout.' }
Set-Location $Repository
if ((git branch --show-current).Trim() -ne 'dev') { throw 'Full local validation is restricted to branch dev.' }
Get-Command docker -ErrorAction Stop | Out-Null
Get-Command pwsh -ErrorAction Stop | Out-Null
Get-Command python -ErrorAction Stop | Out-Null
Get-Command pnpm -ErrorAction Stop | Out-Null

$ImageId = (@(docker image inspect $Image --format '{{.Id}}' 2>$null) -join '').Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($ImageId)) {
    throw "Local test image '$Image' is unavailable. Build it separately or pass -Image to an existing local tag."
}

function Invoke-Checked {
    param([string]$Command, [object[]]$Arguments)
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed ($LASTEXITCODE): $Command" }
}

function Invoke-PwshTest {
    param([string]$Path, [object[]]$Arguments = @())
    Invoke-Checked 'pwsh' (@('-NoProfile', '-File', (Join-Path $Repository $Path)) + $Arguments)
}

function Invoke-ShellTest {
    param([string]$Path, [object[]]$Arguments = @())
    $Bash = (Get-Command bash -ErrorAction SilentlyContinue)
    if (-not $Bash) { $Bash = Get-Command bash.exe -ErrorAction SilentlyContinue }
    if (-not $Bash) { throw 'Git Bash is required for shell-based deterministic tests.' }
    $SafeRepository = $Repository -replace "'", "'\\''"
    $Command = "cd '$SafeRepository' && ./$(($Path -replace '\\','/'))"
    foreach ($Argument in $Arguments) {
        $SafeArgument = ([string]$Argument) -replace "'", "'\\''"
        $Command += " '$SafeArgument'"
    }
    Invoke-Checked $Bash.Source @('-lc', $Command)
}

$OldImageId = (@(docker image inspect webobs:m0 --format '{{.Id}}' 2>$null) -join '').Trim()
$HadOldImage = -not [string]::IsNullOrWhiteSpace($OldImageId)
$env:WEBOBS_TEST_IMAGE = $Image
$env:WEBOBS_IMAGE = $Image

try {
    # Several historical deterministic fixtures use the stable local name
    # webobs:m0. Alias only the existing image; no layer is built or pushed.
    Invoke-Checked 'docker' @('tag', $Image, 'webobs:m0')

    Invoke-PwshTest 'tests/run-public-audit.ps1'
    Invoke-Checked 'python' @('clients/scripts/verify_dependency_lock.py')
    Invoke-Checked 'python' @('clients/tests/test_release_workflow_policy.py')
    Invoke-Checked 'python' @('-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_*.py')

    Push-Location (Join-Path $Repository 'web')
    try {
        Invoke-Checked 'pnpm' @('install', '--frozen-lockfile')
        Invoke-Checked 'pnpm' @('typecheck')
        Invoke-Checked 'pnpm' @('test:iwa')
        Invoke-Checked 'pnpm' @('build')
        Invoke-Checked 'pnpm' @('test:local:chrome')
        Invoke-Checked 'pnpm' @('exec', 'playwright', 'test', '--project=chromium')
        Invoke-Checked 'pnpm' @('exec', 'playwright', 'test', '--project=chrome')
        Invoke-Checked 'pnpm' @('exec', 'playwright', 'test', '--project=edge')
    } finally { Pop-Location }

    # Deterministic v1/v2 functional suites. Every invoked suite receives
    # -SkipBuild; the product image and all fixture images must already exist.
    Invoke-PwshTest 'tests/run-smoke.ps1' @('-SkipBuild')
    Invoke-PwshTest 'tests/run-browser-source.ps1' @('-SkipBuild')
    Invoke-PwshTest 'tests/run-m5-audio.ps1' @('-SkipBuild')
    Invoke-PwshTest 'tests/run-m6-auth.ps1' @('-SkipBuild')
    Invoke-PwshTest 'tests/run-m6-backup.ps1' @('-SkipBuild', '-Image', $Image)
    Invoke-PwshTest 'tests/run-m6-tls-turn.ps1' @('-SkipBuild')
    Invoke-PwshTest 'tests/run-m6-upgrade.ps1' @('-SkipBuild')
    Invoke-PwshTest 'tests/run-m7-studio.ps1' @('-SkipBuild')
    Invoke-PwshTest 'tests/run-m8-nvr.ps1' @('-SkipBuild', '-SoakMinutes', '1')
    Invoke-PwshTest 'tests/run-m9-timeline.ps1' @('-SkipBuild')
    Invoke-PwshTest 'tests/run-v2-true-direct.ps1' @('-SkipBuild', '-Image', $Image)

    if ($Long) {
        $env:WEBOBS_IMAGE = $Image
        foreach ($Count in @(8, 16, 32)) {
            $env:WEBOBS_M7_CAMERA_COUNT = "$Count"
            $env:WEBOBS_M7_GATE_SECONDS = '900'
            Invoke-ShellTest 'tests/m7/run-gate.sh'
        }
        Invoke-ShellTest 'tests/m7/run-fault-gate.sh'
    } else {
        Write-Host 'M7 8/16/32 x 900-second scale and fault gates not run; use -Long for those optional long tests.'
    }

    if ($IncludeRealMedia) {
        if ($env:WEBOBS_RTSP_URL) { Invoke-PwshTest 'tests/run-m3-real-camera.ps1' @('-SkipBuild') }
        if ($env:WEBOBS_REAL_MJPEG_URL) { Invoke-PwshTest 'tests/run-m10-real-mjpeg.ps1' @('-Image', $Image) }
        if (-not $env:WEBOBS_RTSP_URL -and -not $env:WEBOBS_REAL_MJPEG_URL) {
            throw '-IncludeRealMedia was requested but no private media environment variable is set.'
        }
    }

    Write-Host "Full local no-build validation passed for $Image. No image was built or pushed."
} finally {
    if ($HadOldImage) {
        docker tag $OldImageId webobs:m0 | Out-Null
    } else {
        docker image rm webobs:m0 2>$null | Out-Null
    }
    Remove-Item Env:WEBOBS_TEST_IMAGE -ErrorAction SilentlyContinue
    Remove-Item Env:WEBOBS_IMAGE -ErrorAction SilentlyContinue
}
