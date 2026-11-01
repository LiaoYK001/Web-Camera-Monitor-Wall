#requires -Version 7.2
# Independent, non-default OBS frontend prototype. Does not invoke legacy build-windows.ps1.
[CmdletBinding()]
param(
    [string]$Version = '0.1.0-dev.0',
    [string]$BuildDirectory,
    [ValidateRange(1,64)][int]$Parallel = 4,
    [switch]$Offline,
    [switch]$SmokeTest,
    [switch]$PixelTest
)
$ErrorActionPreference = 'Stop'
if ($SmokeTest -and $PixelTest) { throw 'Choose startup SmokeTest OR finite PixelTest; each requires a NEW private profile.' }
if ($PixelTest -and -not (Get-Command 'node' -ErrorAction SilentlyContinue)) { throw 'PixelTest requires Node for synthetic patterns/pixel analysis, never for the native host.' }
$pixelBuild = if ($PixelTest) { 'ON' } else { 'OFF' }
if (-not $IsWindows -or -not [Environment]::Is64BitOperatingSystem -or [Runtime.InteropServices.RuntimeInformation]::OSArchitecture -ne 'X64') { throw 'The OBS prototype requires Windows x64.' }
if ($Version -notmatch '^\d+\.\d+\.\d+-dev\.[0-9A-Za-z.-]+$') { throw 'This independent prototype accepts X.Y.Z-dev.* versions only; no release/package/publication mode exists.' }
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
if (-not $BuildDirectory) { $BuildDirectory = Join-Path $repoRoot ('build/obs-native-windows/' + $Version + '-' + [Guid]::NewGuid().ToString('N').Substring(0,8)) }
$buildRoot = [IO.Path]::GetFullPath($BuildDirectory)
$cacheRoot = Join-Path $repoRoot 'desktop/.cache'
foreach ($tool in @('cmake','ctest','git','python','cl')) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "Missing $tool; use VS 2022 x64 Developer PowerShell, Python 3 and CMake >= 3.28. No toolchains are downloaded automatically." }
}
function Invoke-Checked([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Native build failed ($LASTEXITCODE): $Program" }
}
# Only verified archive cache is reused. A NEW source/build/runtime tree avoids
# stale upstream extraction receipts and never overwrites portable credentials.
$runtime = Join-Path $buildRoot 'runtime'
if (Test-Path -LiteralPath $buildRoot) { throw 'BuildDirectory already exists. Preserve its private portable config and choose a NEW directory; no automatic deletion/migration is performed.' }
$upstreamRoot = [IO.Path]::GetFullPath((Join-Path $repoRoot 'obs/obs-studio'))
if ($buildRoot.StartsWith($upstreamRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Do not build inside the upstream checkout.' }
New-Item -ItemType Directory -Path $buildRoot | Out-Null
$source = Join-Path $buildRoot 'obs-source'
$prepare = @((Join-Path $repoRoot 'native-host/scripts/prepare.py'),'--repo',$repoRoot,'--output',$source,'--cache',$cacheRoot)
if ($Offline) { $prepare += '--offline' }
Invoke-Checked 'python' $prepare
$obsBuild = Join-Path $buildRoot 'obs-build'
$obsInstall = Join-Path $buildRoot 'obs-install'
$deps = Join-Path $source '.deps/obs-deps-2025-08-23-x64'
$qt = Join-Path $source '.deps/obs-deps-qt6-2025-08-23-x64'
# Keep OBS's native frontend, Media Source, Qt deployment and D3D11 rendering.
# No headless patch, browser/Electron/GStreamer runtime or product service is used.
Invoke-Checked 'cmake' @('-S',$source,'-B',$obsBuild,'-G','Visual Studio 17 2022','-A','x64','-DCMAKE_SYSTEM_VERSION=10.0.22621.0','-DENABLE_FRONTEND=ON','-DENABLE_PLUGINS=ON','-DENABLE_SCRIPTING=OFF','-DENABLE_BROWSER=OFF','-DENABLE_VST=OFF','-DENABLE_AJA=OFF','-DENABLE_DECKLINK=OFF','-DENABLE_VLC=OFF','-DENABLE_WEBSOCKET=OFF','-DENABLE_WEBRTC=OFF','-DOBS_VERSION_OVERRIDE=32.1.2','-DCMAKE_FIND_USE_PACKAGE_REGISTRY=OFF','-DCMAKE_EXPORT_PACKAGE_REGISTRY=OFF',"-DCMAKE_INSTALL_PREFIX=$obsInstall")
Invoke-Checked 'cmake' @('--build',$obsBuild,'--config','Release','--parallel',"$Parallel")
Invoke-Checked 'cmake' @('--install',$obsBuild,'--config','Release')
Invoke-Checked 'cmake' @('--install',$obsBuild,'--config','Release','--component','Development')
# Separate executable: real pinned libobs loader with its own inert source. No
# modules, frontend, media, video/audio reset or existing portable profile. Never
# install/package the probe; PATH below exists only while running its CTest.
$loaderBuild = Join-Path $buildRoot 'real-loader-test'
Invoke-Checked 'cmake' @('-S',(Join-Path $repoRoot 'native-host/tests/real-loader'),'-B',$loaderBuild,'-G','Visual Studio 17 2022','-A','x64',"-DCMAKE_PREFIX_PATH=$obsInstall;$deps",'-DCMAKE_FIND_USE_PACKAGE_REGISTRY=OFF','-DCMAKE_EXPORT_PACKAGE_REGISTRY=OFF')
Invoke-Checked 'cmake' @('--build',$loaderBuild,'--config','Release','--parallel',"$Parallel")
$beforeLoaderPath = $env:PATH
try {
    $env:PATH = (Join-Path $obsInstall 'bin/64bit') + ';' + (Join-Path $deps 'bin') + ';' + $beforeLoaderPath
    Invoke-Checked 'ctest' @('--test-dir',$loaderBuild,'-C','Release','--output-on-failure')
} finally {
    $env:PATH = $beforeLoaderPath
}
$pluginBuild = Join-Path $buildRoot 'plugin-build'
# Explicit Qt6_DIR pins plugin ABI to the frontend's locked Qt, not PATH/system Qt.
Invoke-Checked 'cmake' @('-S',(Join-Path $repoRoot 'native-host'),'-B',$pluginBuild,'-G','Visual Studio 17 2022','-A','x64',"-DCMAKE_PREFIX_PATH=$obsInstall;$deps;$qt", "-DQt6_DIR=$qt/lib/cmake/Qt6",'-DWEBOBS_NATIVE_BUILD_TESTS=ON',"-DWEBOBS_NATIVE_PIXEL_TEST=$pixelBuild","-DSIMDE_INCLUDE_DIR=$deps/include",'-DCMAKE_FIND_USE_PACKAGE_REGISTRY=OFF','-DCMAKE_EXPORT_PACKAGE_REGISTRY=OFF')
Invoke-Checked 'cmake' @('--build',$pluginBuild,'--config','Release','--parallel',"$Parallel")
Invoke-Checked 'ctest' @('--test-dir',$pluginBuild,'-C','Release','--output-on-failure')
Invoke-Checked 'python' @((Join-Path $repoRoot 'native-host/tests/test_build_contract.py'))
# Install OBS runtime component once to an empty product-owned directory, then plugin.
# Upstream's own install rules collect Qt platform plugins and ABI dependencies.
Invoke-Checked 'cmake' @('--install',$obsBuild,'--config','Release','--prefix',$runtime)
Invoke-Checked 'cmake' @('--install',$pluginBuild,'--config','Release','--prefix',$runtime)
# P4: the Windows install rules also stage debug symbols. PDBs are build
# products, are never loaded by obs64, and the NSIS installer would package
# them. Remove them before stage.py records the file manifest and size groups.
Invoke-Checked 'python' @((Join-Path $repoRoot 'native-host/scripts/prune_runtime.py'),'--runtime',$runtime,'--report',(Join-Path $buildRoot 'native-runtime-prune.json'))
Invoke-Checked 'python' @((Join-Path $repoRoot 'native-host/scripts/stage.py'),'--repo',$repoRoot,'--source',$source,'--runtime',$runtime,'--version',$Version)
if ($PixelTest) {
    # A test-enabled runtime must never masquerade as a redistributable prototype.
    # The compiler-installed marker is checked before annotating the stage manifest.
    Invoke-Checked 'python' @((Join-Path $repoRoot 'native-host/tests/pixel_windows.py'),'--runtime',$runtime,'--mark-build')
    $pixelArguments = @((Join-Path $repoRoot 'native-host/tests/pixel_windows.py'),'--runtime',$runtime,'--result',(Join-Path $buildRoot 'native-final-pixels.json'))
    if ($Offline) { $pixelArguments += '--offline' }
    Invoke-Checked 'python' $pixelArguments
    Write-Output 'NON-REDISTRIBUTABLE PixelTest runtime: upload only the small synthetic native-final-pixels.json receipt, never runtime/config, logs, binaries or BMPs.'
}
if ($SmokeTest) {
    Invoke-Checked 'python' @((Join-Path $repoRoot 'native-host/tests/smoke_windows.py'),'--runtime',$runtime,'--result',(Join-Path $buildRoot 'native-startup-smoke.json'))
    Write-Output 'Smoke generated a disposable private config; do not upload runtime/config or treat it as a clean redistributable bundle.'
}
Write-Output "Non-default development prototype: $runtime"
Write-Output "Launch explicitly: pwsh -NoProfile -File `"$runtime/launch-native.ps1`" -AllowPrototype"
Write-Output 'Windows plugin load, source/decoder counts, portable isolation, real cameras, two projectors, auth/migration/lifecycle and install/upgrade qualification are still required. No existing product was replaced.'
