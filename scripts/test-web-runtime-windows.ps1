param(
    [switch]$ReleaseGate,
    [string]$PrivateGateCommand = $env:WEBOBS_PRIVATE_PWA_GATE_COMMAND
)

$ErrorActionPreference = 'Stop'
$repository = (git rev-parse --show-toplevel).Trim()
if (-not $repository) { throw 'Run this script from a Web Camera Monitor Wall checkout.' }
Set-Location $repository

foreach ($command in @('git', 'node', 'pnpm', 'python', 'docker')) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "Required command is unavailable: $command"
    }
}

& .\tests\run-public-audit.ps1
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python .\clients\tests\test_release_workflow_policy.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python .\clients\tests\test_local_gate_receipts.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Push-Location web
try {
    Remove-Item -Recurse -Force node_modules -ErrorAction SilentlyContinue
    pnpm install --frozen-lockfile
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    pnpm typecheck
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    pnpm test:iwa
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    pnpm build
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    pnpm test:local:chrome
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    pnpm exec playwright test --project=chrome
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    pnpm exec playwright test --project=edge
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
finally { Pop-Location }

docker build --target v2-service-test -f docker/Dockerfile .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
docker build --target core-builder -f docker/Dockerfile .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if ($ReleaseGate) {
    if (-not $PrivateGateCommand) { throw 'PrivateGateCommand is required with -ReleaseGate.' }
    $env:WEBOBS_PRIVATE_PWA_GATE_COMMAND = $PrivateGateCommand
    python .\scripts\run-private-pwa-gate.py --platform windows --evidence-dir build/private-gates
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Output 'Windows Web runtime qualification passed.'
