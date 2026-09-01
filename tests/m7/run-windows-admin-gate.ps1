param(
    [string]$Image = 'webobs:m7-candidate',
    [ValidateSet('chrome', 'edge', 'both')][string]$Browser = 'both'
)

$ErrorActionPreference = 'Stop'
$repository = (git rev-parse --show-toplevel).Trim()
if (-not $repository) { throw 'Run this script from a Web Camera Monitor Wall checkout.' }
Set-Location $repository
foreach ($command in @('git', 'docker', 'python', 'pnpm')) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) { throw "Missing command: $command" }
}
$bash = 'C:\Program Files\Git\bin\bash.exe'
if (-not (Test-Path -LiteralPath $bash)) { throw 'Git for Windows Bash is required.' }

$compose = Join-Path $repository 'tests\m7\compose.yaml'
try {
    $env:WEBOBS_IMAGE = $Image
    $env:WEBOBS_M7_CAMERA_COUNT = '8'
    $env:WEBOBS_M7_GATE_SECONDS = '60'
    $env:WEBOBS_M7_KEEP = 'true'
    & $bash tests/m7/run-gate.sh
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    python tests/m7/prepare-windows-admin.py
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $env:WEBOBS_M7_CONTROL_URL = 'https://127.0.0.1:18443'
    $env:WEBOBS_M7_BROWSER_CREDENTIALS = Join-Path $repository 'tests\.m7-cluster\secrets\windows-admin-users.json'
    $projects = if ($Browser -eq 'both') { @('chrome', 'edge') } else { @($Browser) }
    foreach ($project in $projects) {
        pnpm --dir web exec playwright test -c playwright.m7.config.ts --project=$project
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    if ($Browser -eq 'both') {
        python tests/m7/write-windows-receipt.py
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    Write-Output "Windows v2-M7 administrator gate passed: $($projects -join ', ')."
}
finally {
    Remove-Item Env:WEBOBS_M7_KEEP -ErrorAction SilentlyContinue
    Remove-Item Env:WEBOBS_M7_BROWSER_CREDENTIALS -ErrorAction SilentlyContinue
    docker compose -f $compose down --volumes --remove-orphans | Out-Null
}
