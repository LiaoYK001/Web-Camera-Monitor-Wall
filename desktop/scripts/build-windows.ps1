#requires -Version 7.2
[CmdletBinding()]
param(
    [string]$Version = '3.4.0-dev.0',
    [switch]$Release,
    [switch]$SkipPackage
)
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$desktopRoot = Join-Path $repoRoot 'desktop'
$buildRoot = Join-Path $repoRoot 'build\desktop-windows'
$cacheRoot = Join-Path $desktopRoot '.cache'
$runtimeRoot = Join-Path $desktopRoot 'runtime'
if (-not $IsWindows -and $PSVersionTable.PSEdition -eq 'Core') { throw 'Windows x64 is required.' }
if (-not [Environment]::Is64BitOperatingSystem) { throw 'x64 Windows is required.' }
if ($Version -notmatch '^\d+\.\d+\.\d+(-dev\.[0-9A-Za-z.-]+)?$') { throw 'Use a stable X.Y.Z or X.Y.Z-dev.* version.' }
if ($Release -and ($Version -match '-' -or -not $env:CSC_LINK -or -not $env:WEBOBS_SIGNING_PUBLISHER)) { throw 'Official builds require stable version, CSC_LINK, CSC_KEY_PASSWORD and WEBOBS_SIGNING_PUBLISHER.' }
if (-not $Release -and $Version -notmatch '-dev\.') { throw 'Unsigned builds require a -dev.* version.' }
foreach ($tool in @('cmake','git','python','node','pnpm')) { if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "Build dependency missing: $tool. Run in a VS 2022 x64 Developer PowerShell with CMake >= 3.28 and Node 24." } }
if (-not (Get-Command cl -ErrorAction SilentlyContinue)) { throw 'No MSVC x64 compiler. Open VS 2022 x64 Developer PowerShell; desktop builds do not install compilers automatically.' }
function Invoke-Checked([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Build command failed ($LASTEXITCODE): $Program" }
}
New-Item -ItemType Directory -Force $buildRoot,$cacheRoot | Out-Null
$lock = Get-Content -LiteralPath (Join-Path $desktopRoot 'dependencies.lock.json') -Raw | ConvertFrom-Json
Invoke-Checked 'node' @((Join-Path $PSScriptRoot 'lock.mjs'))
if ((& git -C (Join-Path $repoRoot 'obs\obs-studio') rev-parse HEAD).Trim() -ne $lock.obsCommit) { throw 'OBS submodule pin mismatch.' }
if ((& git -C (Join-Path $repoRoot 'go2rtc\go2rtc') rev-parse HEAD).Trim() -ne $lock.go2rtcCommit) { throw 'go2rtc submodule pin mismatch.' }
foreach ($artifact in $lock.artifacts) {
    $download = Join-Path $cacheRoot ($artifact.id + '.zip')
    if (-not (Test-Path -LiteralPath $download) -or (Get-FileHash -LiteralPath $download -Algorithm SHA256).Hash.ToLowerInvariant() -ne $artifact.sha256) {
        Write-Output "Downloading locked dependency: $($artifact.id) $($artifact.version)"
        $temporary = $download + '.partial'
        Invoke-WebRequest -Uri $artifact.url -OutFile $temporary -MaximumRetryCount 4
        if ((Get-FileHash -LiteralPath $temporary -Algorithm SHA256).Hash.ToLowerInvariant() -ne $artifact.sha256) { throw "Dependency checksum failed: $($artifact.id)" }
        Move-Item -LiteralPath $temporary -Destination $download -Force
    }
}
$vcpkgRoot = Join-Path $buildRoot 'vcpkg'
if (-not (Test-Path -LiteralPath (Join-Path $vcpkgRoot 'bootstrap-vcpkg.bat'))) {
    Expand-Archive -LiteralPath (Join-Path $cacheRoot 'vcpkg.zip') -DestinationPath (Join-Path $buildRoot 'vcpkg-source') -Force
    $extracted = Join-Path $buildRoot ('vcpkg-source\vcpkg-' + $lock.vcpkgCommit)
    Move-Item -LiteralPath $extracted -Destination $vcpkgRoot
}
# The locked source archive excludes Git history; the baseline database is still
# pinned by commit. Bootstrap a local repository and fetch that exact commit.
if (-not (Test-Path -LiteralPath (Join-Path $vcpkgRoot '.git'))) {
    Invoke-Checked 'git' @('-C',$vcpkgRoot,'init')
    Invoke-Checked 'git' @('-C',$vcpkgRoot,'remote','add','origin','https://github.com/microsoft/vcpkg.git')
    Invoke-Checked 'git' @('-C',$vcpkgRoot,'fetch','--depth','1','origin',$lock.vcpkgCommit)
    Invoke-Checked 'git' @('-C',$vcpkgRoot,'reset','--mixed','FETCH_HEAD')
}
Invoke-Checked (Join-Path $vcpkgRoot 'bootstrap-vcpkg.bat') @('-disableMetrics')
$vcpkgInstalled = Join-Path $buildRoot 'vcpkg-installed'
$vcpkgBinaryCache = Join-Path $cacheRoot 'vcpkg-binaries'
New-Item -ItemType Directory -Force $vcpkgBinaryCache | Out-Null
$env:VCPKG_BINARY_SOURCES = "clear;files,$vcpkgBinaryCache,readwrite"
Invoke-Checked (Join-Path $vcpkgRoot 'vcpkg.exe') @('install','--triplet=x64-windows',"--x-manifest-root=$desktopRoot","--x-install-root=$vcpkgInstalled",'--disable-metrics')
$obsSource = Join-Path $buildRoot 'obs-source'
if (-not (Test-Path -LiteralPath (Join-Path $obsSource 'CMakeLists.txt'))) {
    # Copy the upstream checkout; configure/build never modifies the submodule.
    Invoke-Checked 'python' @('-c','import shutil,sys; shutil.copytree(sys.argv[1],sys.argv[2],ignore=shutil.ignore_patterns(".git",".deps","build","build_*","build-*","__pycache__"))',(Join-Path $repoRoot 'obs\obs-studio'),$obsSource)
}
Invoke-Checked 'python' @((Join-Path $PSScriptRoot 'prepare-obs-headless.py'),$obsSource)
$obsDeps = Join-Path $obsSource '.deps'
New-Item -ItemType Directory -Force $obsDeps | Out-Null
foreach ($item in @(@('obs-deps','windows-deps-2025-08-23-x64.zip'),@('obs-qt','windows-deps-qt6-2025-08-23-x64.zip'),@('obs-cef','cef_binary_6533_windows_x64_v2.zip'))) {
    Copy-Item -LiteralPath (Join-Path $cacheRoot ($item[0]+'.zip')) -Destination (Join-Path $obsDeps $item[1]) -Force
}
$obsBuild = Join-Path $buildRoot 'obs-build'
$obsInstall = Join-Path $buildRoot 'obs-install'
Invoke-Checked 'cmake' @('-S',$obsSource,'-B',$obsBuild,'-G','Visual Studio 17 2022','-A','x64','-DENABLE_UI=OFF','-DENABLE_FRONTEND=OFF','-DENABLE_SCRIPTING=OFF','-DENABLE_BROWSER=ON','-DENABLE_BROWSER_PANELS=OFF','-DENABLE_VST=OFF','-DENABLE_AJA=OFF','-DENABLE_DECKLINK=OFF','-DENABLE_VLC=OFF','-DENABLE_WEBSOCKET=OFF','-DOBS_VERSION_OVERRIDE=32.1.2',"-DCMAKE_INSTALL_PREFIX=$obsInstall")
Invoke-Checked 'cmake' @('--build',$obsBuild,'--config','Release','--parallel','4')
Invoke-Checked 'cmake' @('--build',$obsBuild,'--config','Release','--target','obs-browser-helper','--parallel','4')
Invoke-Checked 'cmake' @('--install',$obsBuild,'--config','Release')
Invoke-Checked 'cmake' @('--install',$obsBuild,'--config','Release','--component','Development')
$coreBuild = Join-Path $buildRoot 'core-build'
$coreInstall = Join-Path $buildRoot 'core-install'
$corePrefix = "$obsInstall;$vcpkgInstalled\x64-windows;$obsSource\.deps\obs-deps-2025-08-23-x64"
Invoke-Checked 'cmake' @('-S',$repoRoot,'-B',$coreBuild,'-G','Visual Studio 17 2022','-A','x64',"-DCMAKE_TOOLCHAIN_FILE=$vcpkgRoot/scripts/buildsystems/vcpkg.cmake",'-DVCPKG_MANIFEST_MODE=OFF',"-DVCPKG_INSTALLED_DIR=$vcpkgInstalled",'-DVCPKG_TARGET_TRIPLET=x64-windows',"-DCMAKE_PREFIX_PATH=$corePrefix", "-DWEBOBS_OBS_PREFIX=$obsInstall", "-DWEBOBS_VERSION_OVERRIDE=$Version", "-DCMAKE_INSTALL_PREFIX=$coreInstall")
Invoke-Checked 'cmake' @('--build',$coreBuild,'--config','Release','--parallel','4')
$savedPath = $env:PATH
try {
    $env:PATH = "$obsInstall\bin\64bit;$vcpkgInstalled\x64-windows\bin;$savedPath"
    Invoke-Checked 'ctest' @('--test-dir',$coreBuild,'-C','Release','--output-on-failure')
} finally { $env:PATH = $savedPath }
Invoke-Checked 'cmake' @('--install',$coreBuild,'--config','Release')
Invoke-Checked 'pnpm' @('--dir',(Join-Path $repoRoot 'web'),'install','--frozen-lockfile')
Invoke-Checked 'pnpm' @('--dir',(Join-Path $repoRoot 'web'),'typecheck')
$env:WEBOBS_BUILD_VERSION=$Version
Invoke-Checked 'pnpm' @('--dir',(Join-Path $repoRoot 'web'),'build')
Invoke-Checked 'pnpm' @('--dir',(Join-Path $repoRoot 'web'),'go2rtc:ui')
if (Test-Path -LiteralPath $runtimeRoot) {
    $resolved = (Resolve-Path -LiteralPath $runtimeRoot).Path
    if ($resolved -ne (Join-Path $repoRoot 'desktop\runtime') -or (Get-Item -LiteralPath $runtimeRoot).Attributes.HasFlag([IO.FileAttributes]::ReparsePoint)) { throw 'Unsafe runtime cleanup target.' }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}
Invoke-Checked 'python' @((Join-Path $PSScriptRoot 'stage-runtime.py'),'--cache',$cacheRoot,'--core',$coreInstall,'--obs',$obsInstall,'--vcpkg',(Join-Path $vcpkgInstalled 'x64-windows'),'--output',$runtimeRoot)
Invoke-Checked 'pnpm' @('--dir',$desktopRoot,'install','--frozen-lockfile')
$env:WEBOBS_DESKTOP_VERSION=$Version
$env:WEBOBS_RELEASE_BUILD=if($Release){'true'}else{'false'}
$env:WEBOBS_PACKAGE_SUFFIX=if($Release){''}else{'-DEVELOPMENT-UNSIGNED'}
Invoke-Checked 'node' @((Join-Path $PSScriptRoot 'manifest.mjs'))
Invoke-Checked 'pnpm' @('--dir',$desktopRoot,'test')
Invoke-Checked 'pnpm' @('--dir',$desktopRoot,'test:electron')
Invoke-Checked 'python' @((Join-Path $repoRoot 'desktop\tests\test_native_runtime.py'))
Invoke-Checked 'pnpm' @('--dir',$desktopRoot,'test:runtime')
if (-not $SkipPackage) {
    $distributionPath = Join-Path $desktopRoot 'src\distribution.json'
    $savedDistribution = [IO.File]::ReadAllBytes($distributionPath)
    try {
        Invoke-Checked 'pnpm' @('--dir',$desktopRoot,'exec','electron-builder','--win','nsis','--x64','--publish','never','--config','builder.config.cjs',"--config.extraMetadata.version=$Version")
    } finally { [IO.File]::WriteAllBytes($distributionPath,$savedDistribution) }
    Invoke-Checked 'node' @((Join-Path $PSScriptRoot 'release-assets.mjs'),$Version)
}
Write-Output "Built WebOBS $Version. Runtime: $runtimeRoot. Windows 10/11 installation and actual camera checks remain separate qualification steps."
