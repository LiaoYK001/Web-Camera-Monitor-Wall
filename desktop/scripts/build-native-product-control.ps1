#requires -Version 7.2
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$BuildDirectory,
    [Parameter(Mandatory=$true)][string]$Version,
    [ValidateRange(1,64)][int]$Parallel = 4,
    [switch]$Offline
)
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$buildRoot = [IO.Path]::GetFullPath($BuildDirectory)
$cacheRoot = Join-Path $repoRoot 'desktop/.cache'
$lock = Get-Content -LiteralPath (Join-Path $repoRoot 'desktop/dependencies.lock.json') -Raw | ConvertFrom-Json
function Invoke-Checked([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Product control build failed ($LASTEXITCODE): $Program" }
}
$stager = Join-Path $repoRoot 'native-host/scripts/stage_product_runtime.py'
$prepareArguments = @($stager,'prepare','--repo',$repoRoot,'--build-root',$buildRoot,'--cache',$cacheRoot)
if ($Offline) { $prepareArguments += '--offline' }
Invoke-Checked 'python' $prepareArguments
$vcpkgRoot = Join-Path $buildRoot ('vcpkg-source/vcpkg-' + $lock.vcpkgCommit)
if ($Offline) { throw 'Product offline builds require a prequalified vcpkg toolchain; runtime installation itself is offline.' }
Invoke-Checked 'git' @('-C',$vcpkgRoot,'init')
Invoke-Checked 'git' @('-C',$vcpkgRoot,'config','core.longpaths','true')
Invoke-Checked 'git' @('-C',$vcpkgRoot,'remote','add','origin','https://github.com/microsoft/vcpkg.git')
Invoke-Checked 'git' @('-C',$vcpkgRoot,'fetch','--depth','1','origin',$lock.vcpkgCommit)
Invoke-Checked 'git' @('-C',$vcpkgRoot,'reset','--mixed','FETCH_HEAD')
Invoke-Checked (Join-Path $vcpkgRoot 'bootstrap-vcpkg.bat') @('-disableMetrics')
$vcpkgInstalled = Join-Path $buildRoot 'product-vcpkg-installed'
$binaryCache = Join-Path $cacheRoot 'vcpkg-binaries'
New-Item -ItemType Directory -Force $binaryCache | Out-Null
$env:VCPKG_BINARY_SOURCES = "clear;files,$binaryCache,readwrite"
# Port version checkouts append long content hashes and patch names. Keep that
# disposable build tree short independently of the user's repository location.
$portBuildRoot = Join-Path ([IO.Path]::GetTempPath()) ('wv-' + [Guid]::NewGuid().ToString('N').Substring(0,8))
New-Item -ItemType Directory $portBuildRoot | Out-Null
Invoke-Checked (Join-Path $vcpkgRoot 'vcpkg.exe') @('install','--triplet=x64-windows',"--x-manifest-root=$repoRoot/desktop", "--x-buildtrees-root=$portBuildRoot", "--x-install-root=$vcpkgInstalled",'--disable-metrics')
if ($env:GITHUB_ENV) { 'WEBOBS_PRODUCT_PORTS_READY=true' | Out-File -FilePath $env:GITHUB_ENV -Append -Encoding utf8 }
$obsInstall = Join-Path $buildRoot 'obs-install'
$deps = Join-Path $buildRoot 'obs-source/.deps/obs-deps-2025-08-23-x64'
$coreBuild = Join-Path $buildRoot 'product-core-build'
$coreInstall = Join-Path $buildRoot 'product-core-install'
$prefix = "$obsInstall;$vcpkgInstalled/x64-windows;$deps"
Invoke-Checked 'cmake' @('-S',$repoRoot,'-B',$coreBuild,'-G','Visual Studio 17 2022','-A','x64',
    "-DCMAKE_TOOLCHAIN_FILE=$vcpkgRoot/scripts/buildsystems/vcpkg.cmake",'-DVCPKG_MANIFEST_MODE=OFF',
    "-DVCPKG_INSTALLED_DIR=$vcpkgInstalled",'-DVCPKG_TARGET_TRIPLET=x64-windows',"-DCMAKE_PREFIX_PATH=$prefix",
    "-DWEBOBS_OBS_PREFIX=$obsInstall",'-DWEBOBS_BUILD_PRODUCT_LAUNCHER=ON', "-DWEBOBS_VERSION_OVERRIDE=$Version",'-DWEBOBS_MILESTONE_OVERRIDE=v4-M1-dev',
    "-DCMAKE_INSTALL_PREFIX=$coreInstall")
Invoke-Checked 'cmake' @('--build',$coreBuild,'--config','Release','--parallel',"$Parallel")
$previousPath = $env:PATH
$previousSodium = $env:WEBOBS_LIBSODIUM_LIBRARY
try {
    $env:PATH = "$obsInstall/bin/64bit;$vcpkgInstalled/x64-windows/bin;$previousPath"
    $env:WEBOBS_LIBSODIUM_LIBRARY = "$vcpkgInstalled/x64-windows/bin/libsodium.dll"
    Invoke-Checked 'ctest' @('--test-dir',$coreBuild,'-C','Release','--output-on-failure')
} finally {
    $env:PATH = $previousPath
    $env:WEBOBS_LIBSODIUM_LIBRARY = $previousSodium
}
Invoke-Checked 'cmake' @('--install',$coreBuild,'--config','Release')
Invoke-Checked 'npx' @('--yes','pnpm@11.16.0','--dir',"$repoRoot/web",'install','--frozen-lockfile')
Invoke-Checked 'npx' @('--yes','pnpm@11.16.0','--dir',"$repoRoot/web",'typecheck')
$env:WEBOBS_BUILD_VERSION = $Version
$env:WEBOBS_BUILD_MILESTONE = 'v4-M1-dev'
Invoke-Checked 'npx' @('--yes','pnpm@11.16.0','--dir',"$repoRoot/web",'build')
Invoke-Checked 'python' @($stager,'stage','--repo',$repoRoot,'--build-root',$buildRoot,'--cache',$cacheRoot,
    '--core',$coreInstall,'--vcpkg',"$vcpkgInstalled/x64-windows")
$runtime = Join-Path $buildRoot 'runtime'
$previousPath = $env:PATH
$previousSodium = $env:WEBOBS_LIBSODIUM_LIBRARY
try {
    $env:PATH = "$runtime/bin;$runtime/bin/64bit;$env:SystemRoot/System32"
    $env:WEBOBS_LIBSODIUM_LIBRARY = "$runtime/bin/libsodium.dll"
    Invoke-Checked "$runtime/python/python.exe" @('-B',"$repoRoot/native-host/tests/product_http_runtime.py",'--binary',"$runtime/bin/webobsd.exe")
} finally {
    $env:PATH = $previousPath
    $env:WEBOBS_LIBSODIUM_LIBRARY = $previousSodium
}
Write-Output 'Integrated control/services staged and packaged-interpreter HTTP checks passed.'
