#requires -Version 7.2
# Agent-only unguarded positive control, never installed or published. The
# verified product runtime is already staged and remains byte-for-byte intact.
param([Parameter(Mandatory=$true)][string]$BuildDirectory)
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$buildRoot = [IO.Path]::GetFullPath($BuildDirectory)
$runtime = Join-Path $buildRoot 'runtime'
$obsBuild = Join-Path $buildRoot 'obs-build'
$control = Join-Path $buildRoot 'restore-negative-control'
if (Test-Path -LiteralPath $control) { throw 'Restore control output must be new.' }
$manifest = Get-Content -LiteralPath (Join-Path $runtime 'webobs-native-prototype.json') -Raw | ConvertFrom-Json
if (-not $manifest.productIntegration -or -not $manifest.publicationForbidden) { throw 'Internal integrated runtime required.' }
$productFrontend = Join-Path $runtime 'bin/64bit/obs64.exe'
$productHash = (Get-FileHash -LiteralPath $productFrontend -Algorithm SHA256).Hash
# Reconfigure only the verified disposable source/build copy. OFF removes the
# product restore interception; this executable is test input, not a candidate.
cmake -S (Join-Path $buildRoot 'obs-source') -B $obsBuild -DWEBOBS_PRODUCT_FRONTEND=OFF
if ($LASTEXITCODE -ne 0) { throw 'Unguarded frontend control configuration failed.' }
cmake --build $obsBuild --config Release --target obs-studio --parallel 4
if ($LASTEXITCODE -ne 0) { throw 'Unguarded frontend control compilation failed.' }
New-Item -ItemType Directory $control | Out-Null
$controlExe = Join-Path $control 'obs64.exe'
Copy-Item -LiteralPath (Join-Path $obsBuild 'frontend/Release/obs64.exe') -Destination $controlExe
if ((Get-FileHash -LiteralPath $controlExe -Algorithm SHA256).Hash -eq $productHash) {
    throw 'Unguarded frontend did not differ from the staged protected product.'
}
if ((Get-FileHash -LiteralPath $productFrontend -Algorithm SHA256).Hash -ne $productHash) {
    throw 'Control compilation changed the staged product frontend.'
}
& "$runtime/python/python.exe" -B (Join-Path $repoRoot 'native-host/tests/product_restore_windows.py') --runtime $runtime --control-frontend $controlExe --report (Join-Path $buildRoot 'native-product-restore.json')
if ($LASTEXITCODE -ne 0) { throw 'Actual pre-authentication restore isolation failed.' }
