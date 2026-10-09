#requires -Version 7.2
[CmdletBinding()]
param(
    [string]$Version = '3.4.0-dev.0',
    [string]$Milestone = $env:WEBOBS_TARGET_MILESTONE,
    [switch]$Release,
    [switch]$Sign,
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
if ($Release -and $Version -match '-') { throw 'Release builds require a stable X.Y.Z version.' }
if ($Sign -and (-not $Release -or -not $env:CSC_LINK -or -not $env:WEBOBS_SIGNING_PUBLISHER)) { throw 'Signing requires -Release, CSC_LINK and WEBOBS_SIGNING_PUBLISHER.' }
if (-not $Release -and $Version -notmatch '-dev\.') { throw 'Development builds require a -dev.* version.' }
. (Join-Path $PSScriptRoot 'release-milestone.ps1')
$buildMilestone = Resolve-WebOBSDesktopMilestone -Version $Version -Release $Release.IsPresent -Milestone $Milestone
if (-not $Sign) {$env:CSC_IDENTITY_AUTO_DISCOVERY='false';Remove-Item Env:CSC_LINK,Env:CSC_KEY_PASSWORD -ErrorAction SilentlyContinue}
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
Invoke-Checked 'cmake' @('-S',$repoRoot,'-B',$coreBuild,'-G','Visual Studio 17 2022','-A','x64',"-DCMAKE_TOOLCHAIN_FILE=$vcpkgRoot/scripts/buildsystems/vcpkg.cmake",'-DVCPKG_MANIFEST_MODE=OFF',"-DVCPKG_INSTALLED_DIR=$vcpkgInstalled",'-DVCPKG_TARGET_TRIPLET=x64-windows',"-DCMAKE_PREFIX_PATH=$corePrefix", "-DWEBOBS_OBS_PREFIX=$obsInstall", "-DWEBOBS_VERSION_OVERRIDE=$Version", "-DWEBOBS_MILESTONE_OVERRIDE=$buildMilestone", "-DCMAKE_INSTALL_PREFIX=$coreInstall")
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
$env:WEBOBS_BUILD_MILESTONE=$buildMilestone
Invoke-Checked 'pnpm' @('--dir',(Join-Path $repoRoot 'web'),'build')
Invoke-Checked 'pnpm' @('--dir',(Join-Path $repoRoot 'web'),'go2rtc:ui')
if (Test-Path -LiteralPath $runtimeRoot) {
    $resolved = (Resolve-Path -LiteralPath $runtimeRoot).Path
    if ($resolved -ne (Join-Path $repoRoot 'desktop\runtime') -or (Get-Item -LiteralPath $runtimeRoot).Attributes.HasFlag([IO.FileAttributes]::ReparsePoint)) { throw 'Unsafe runtime cleanup target.' }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}
Invoke-Checked 'python' @((Join-Path $PSScriptRoot 'stage-runtime.py'),'--cache',$cacheRoot,'--core',$coreInstall,'--obs',$obsInstall,'--vcpkg',(Join-Path $vcpkgInstalled 'x64-windows'),'--output',$runtimeRoot)
Invoke-Checked 'pnpm' @('--dir',$desktopRoot,'install','--frozen-lockfile')
$npmLicenses = & pnpm --dir $desktopRoot licenses list --prod --json
if ($LASTEXITCODE -ne 0) { throw 'Bundled npm license inventory failed.' }
$npmLicenses | Set-Content -LiteralPath (Join-Path $cacheRoot 'npm-licenses.json') -Encoding utf8
$webLicenses = & pnpm --dir (Join-Path $repoRoot 'web') licenses list --prod --json
if ($LASTEXITCODE -ne 0) { throw 'Bundled WebUI license inventory failed.' }
$webLicenses | Set-Content -LiteralPath (Join-Path $cacheRoot 'web-npm-licenses.json') -Encoding utf8
$env:WEBOBS_DESKTOP_VERSION=$Version
$env:WEBOBS_RELEASE_BUILD=if($Release){'true'}else{'false'}
$env:WEBOBS_SIGN_BUILD=if($Sign){'true'}else{'false'}
Invoke-Checked 'node' @((Join-Path $PSScriptRoot 'manifest.mjs'))
Invoke-Checked 'pnpm' @('--dir',$desktopRoot,'test')
Invoke-Checked 'pnpm' @('--dir',$desktopRoot,'test:electron')
Invoke-Checked 'pnpm' @('--dir',$desktopRoot,'test:updates')
Invoke-Checked 'python' @((Join-Path $repoRoot 'desktop\tests\test_native_runtime.py'))
$savedCameraTest = $env:WEBOBS_TEST_CAMERA_REGISTRY
$savedNvrTest = $env:WEBOBS_TEST_NVR_SERVICE
try {
    $env:WEBOBS_TEST_CAMERA_REGISTRY = Join-Path $runtimeRoot 'services\camera\camera_registry.py'
    $env:WEBOBS_TEST_NVR_SERVICE = Join-Path $runtimeRoot 'services\nvr\nvr_service.py'
    # Exercise the installed services with embedded Python, without writing
    # bytecode into the immutable runtime or depending on developer packages.
    Invoke-Checked (Join-Path $runtimeRoot 'python\python.exe') @('-I','-B',(Join-Path $repoRoot 'tests\test_camera_registry.py'),
        'CameraRegistryTests.test_video_reordering_is_probed_and_persisted_without_an_extra_read',
        'CameraRegistryTests.test_invalid_continuous_move_never_reaches_the_camera',
        'CameraRegistryTests.test_device_ptz_timeout_is_negotiated_persisted_and_sent',
        'CameraRegistryTests.test_ptz_duration_outside_device_range_never_moves',
        'CameraRegistryTests.test_device_ptz_timeout_stops_without_backend_watchdog',
        'CameraRegistryTests.test_ptz_timeout_discovery_rejects_invalid_ranges_and_bounds_reads',
        'CameraRegistryTests.test_legacy_ptz_tokens_migrate_without_inventing_device_timeout',
        'CameraRegistryTests.test_ptz_timeout_rejection_never_retries_without_timeout',
        'CameraRegistryTests.test_valid_continuous_move_still_stops_the_synthetic_soap_device',
        'CameraRegistryTests.test_lost_continuous_response_still_requests_stop',
        'CameraRegistryTests.test_ptz_stop_orders_after_inflight_move_without_blocking_other_devices',
        'CameraRegistryTests.test_late_move_response_recovers_after_stop_waiter_timeout',
        'CameraRegistryTests.test_failed_automatic_stop_is_audited_and_releases_timer_and_session',
        'CameraRegistryTests.test_guarded_device_operations_and_private_profile_tokens')
} finally {
    if ($null -eq $savedCameraTest) { Remove-Item Env:WEBOBS_TEST_CAMERA_REGISTRY -ErrorAction SilentlyContinue } else { $env:WEBOBS_TEST_CAMERA_REGISTRY = $savedCameraTest }
    if ($null -eq $savedNvrTest) { Remove-Item Env:WEBOBS_TEST_NVR_SERVICE -ErrorAction SilentlyContinue } else { $env:WEBOBS_TEST_NVR_SERVICE = $savedNvrTest }
}
Invoke-Checked 'pnpm' @('--dir',(Join-Path $repoRoot 'web'),'exec','playwright','install','chromium')
Invoke-Checked 'pnpm' @('--dir',$desktopRoot,'test:runtime')
Invoke-Checked 'pnpm' @('--dir',$desktopRoot,'test:source-ui','--runtime',$runtimeRoot,'--receipt',(Join-Path $buildRoot 'windows-source-ui.json'))
Invoke-Checked 'pnpm' @('--dir',$desktopRoot,'test:main')
if (-not $SkipPackage) {
    $distributionPath = Join-Path $desktopRoot 'src\distribution.json'
    $savedDistribution = [IO.File]::ReadAllBytes($distributionPath)
    try {
        Invoke-Checked 'pnpm' @('--dir',$desktopRoot,'exec','electron-builder','--win','nsis','--x64','--publish','never','--config','builder.config.cjs',"--config.extraMetadata.version=$Version")
    } finally { [IO.File]::WriteAllBytes($distributionPath,$savedDistribution) }
    Invoke-Checked 'pnpm' @('--dir',$desktopRoot,'test:package')
    Invoke-Checked 'pnpm' @('--dir',$desktopRoot,'test:install')
    Copy-Item -LiteralPath (Join-Path $buildRoot 'windows-source-ui.json') -Destination (Join-Path $desktopRoot "out/$Version/windows-source-ui.json")
    Invoke-Checked 'node' @((Join-Path $PSScriptRoot 'release-assets.mjs'),$Version)
}
Write-Output "Built WebOBS $Version. Runtime: $runtimeRoot. Windows 10/11 installation and actual camera checks remain separate qualification steps."
