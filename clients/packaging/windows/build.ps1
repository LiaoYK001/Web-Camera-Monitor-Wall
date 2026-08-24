[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidatePattern('^[0-9]+\.[0-9]+\.[0-9]+([-.][0-9A-Za-z.-]+)?$')][string]$Version,
    [Parameter(Mandatory)][string]$QtRoot,
    [Parameter(Mandatory)][string]$GStreamerRoot,
    [Parameter(Mandatory)][string]$SodiumRoot,
    [Parameter(Mandatory)][string]$OutputDirectory,
    [string]$SigningCertificateSha1 = ''
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$qtRootPath = (Resolve-Path -LiteralPath $QtRoot).Path
$gstRootPath = (Resolve-Path -LiteralPath $GStreamerRoot).Path
$sodiumRootPath = (Resolve-Path -LiteralPath $SodiumRoot).Path
$outputPath = [IO.Path]::GetFullPath($OutputDirectory)
$build = Join-Path $root 'clients\build-windows'
$stage = Join-Path $build 'stage'

$qtpaths = Join-Path $qtRootPath 'bin\qtpaths.exe'
$gstLaunch = Join-Path $gstRootPath 'bin\gst-launch-1.0.exe'
$gstInspect = Join-Path $gstRootPath 'bin\gst-inspect-1.0.exe'
$windeployqt = Join-Path $qtRootPath 'bin\windeployqt.exe'
$qtEffects = Join-Path $qtRootPath 'qml\Qt5Compat\GraphicalEffects\qmldir'
foreach ($required in @($qtpaths, $gstLaunch, $gstInspect, $windeployqt, $qtEffects)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Required reviewed SDK tool is missing: $required" }
}
if ((& $qtpaths --qt-version).Trim() -ne '6.11.2') { throw 'Release Qt must be exactly 6.11.2' }
if ((& $gstLaunch --version | Select-String '^GStreamer 1\.28\.6$').Count -ne 1) {
    throw 'Release GStreamer must be exactly 1.28.6'
}
foreach ($element in @('rtspsrc', 'uridecodebin3', 'decodebin3', 'qml6glsink', 'whepclientsrc',
        'rtph264depay', 'rtph265depay', 'h264parse', 'h265parse', 'matroskamux',
        'matroskademux', 'mp4mux', 'd3d11h264dec', 'd3d11h265dec')) {
    & $gstInspect $element | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Required release GStreamer element is missing: $element" }
}
$sodiumDll = Get-ChildItem -LiteralPath $sodiumRootPath -Filter 'libsodium*.dll' -Recurse -File | Select-Object -First 1
if (-not $sodiumDll) { throw 'Reviewed libsodium 1.0.22 DLL is missing' }

if (Test-Path -LiteralPath $build) { Remove-Item -LiteralPath $build -Recurse -Force }
New-Item -ItemType Directory -Path $stage, $outputPath -Force | Out-Null
$env:CMAKE_PREFIX_PATH = $qtRootPath
$env:PKG_CONFIG_PATH = "$(Join-Path $gstRootPath 'lib\pkgconfig');$(Join-Path $sodiumRootPath 'lib\pkgconfig')"
cmake -S (Join-Path $root 'clients') -B (Join-Path $build 'cmake') -G Ninja `
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$stage" `
    -DWEBOBS_PACKAGE_VERSION="$Version" -DWEBOBS_ENFORCE_LOCKED_DEPENDENCIES=ON
cmake --build (Join-Path $build 'cmake') --parallel
ctest --test-dir (Join-Path $build 'cmake') --output-on-failure
cmake --install (Join-Path $build 'cmake') --strip
$application = Join-Path $stage 'bin\webobs-native.exe'
& $windeployqt --release --qmldir (Join-Path $root 'clients\qml') $application
Copy-Item -LiteralPath $sodiumDll.FullName -Destination (Join-Path $stage 'bin')
Copy-Item -Path (Join-Path $gstRootPath 'bin\*') -Destination (Join-Path $stage 'bin') -Recurse -Force
Copy-Item -LiteralPath (Join-Path $gstRootPath 'lib\gstreamer-1.0') `
    -Destination (Join-Path $stage 'lib\gstreamer-1.0') -Recurse -Force

$stable = $Version -notmatch '[-]'
if ($stable -and [string]::IsNullOrWhiteSpace($SigningCertificateSha1)) {
    throw 'Stable Windows packages require an Authenticode certificate SHA-1 selector'
}
if (-not [string]::IsNullOrWhiteSpace($SigningCertificateSha1)) {
    $signTool = (Get-Command signtool.exe -ErrorAction Stop).Source
    Get-ChildItem -LiteralPath $stage -Recurse -File -Include *.exe,*.dll | ForEach-Object {
        & $signTool sign /sha1 $SigningCertificateSha1 /fd SHA256 /td SHA256 `
            /tr 'http://timestamp.digicert.com' $_.FullName
        if ($LASTEXITCODE -ne 0) { throw "Authenticode signing failed for $($_.Name)" }
    }
}

$portable = Join-Path $outputPath "webobs-native-$Version-windows-x86_64-portable.zip"
Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $portable -CompressionLevel Optimal
$nsis = (Get-Command makensis.exe -ErrorAction Stop).Source
$installerScript = Join-Path $build 'installer.nsi'
$escapedStage = $stage.Replace('\', '\\')
$escapedOutput = (Join-Path $outputPath "webobs-native-$Version-windows-x86_64-setup.exe").Replace('\', '\\')
@"
Unicode true
Name "WebObs Native $Version"
OutFile "$escapedOutput"
InstallDir "`$LOCALAPPDATA\WebObsNative"
RequestExecutionLevel user
Section
  SetOutPath "`$INSTDIR"
  File /r "$escapedStage\*"
  CreateShortcut "`$DESKTOP\WebObs Native.lnk" "`$INSTDIR\bin\webobs-native.exe"
SectionEnd
"@ | Set-Content -LiteralPath $installerScript -Encoding UTF8
& $nsis $installerScript
if ($LASTEXITCODE -ne 0) { throw 'NSIS packaging failed' }
$installer = Join-Path $outputPath "webobs-native-$Version-windows-x86_64-setup.exe"
if (-not [string]::IsNullOrWhiteSpace($SigningCertificateSha1)) {
    & $signTool sign /sha1 $SigningCertificateSha1 /fd SHA256 /td SHA256 `
        /tr 'http://timestamp.digicert.com' $installer
    if ($LASTEXITCODE -ne 0) { throw 'Authenticode signing failed for the NSIS installer' }
    foreach ($signedFile in @($application, $installer)) {
        & $signTool verify /pa /all $signedFile
        if ($LASTEXITCODE -ne 0) { throw "Authenticode verification failed for $signedFile" }
    }
}

Get-ChildItem -LiteralPath $outputPath -File | ForEach-Object {
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLowerInvariant()
    "$hash  $($_.Name)" | Set-Content -LiteralPath "$($_.FullName).sha256" -Encoding ascii
}
