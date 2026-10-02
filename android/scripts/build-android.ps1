#requires -Version 7.2
[CmdletBinding()]
param(
    [string]$Version = '3.5.0-dev.android.1',
    [ValidateRange(1, 2100000000)][int]$VersionCode = 3050001,
    [string]$JavaHome = $env:JAVA_HOME,
    [string]$SdkRoot = $env:ANDROID_HOME,
    [string]$GradleHome,
    [string]$Adb,
    [string]$Serial
)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..')).Path
$lock = Get-Content (Join-Path $projectRoot 'toolchain.lock.json') -Raw | ConvertFrom-Json
if ((Get-FileHash (Join-Path $projectRoot 'gradle/wrapper/gradle-wrapper.jar') -Algorithm SHA256).Hash.ToLowerInvariant() -ne $lock.wrapperSha256) { throw 'Gradle wrapper JAR checksum mismatch.' }
if ($Version -notmatch '^\d+\.\d+\.\d+-dev\.[0-9A-Za-z.-]+$') { throw 'This helper creates explicitly marked development APKs; use X.Y.Z-dev.*.' }
if (-not $JavaHome) {
    $javaCommand = Get-Command java -ErrorAction SilentlyContinue
    if ($javaCommand) { $JavaHome = Split-Path (Split-Path $javaCommand.Source) }
}
if (-not $JavaHome -or -not (Test-Path (Join-Path $JavaHome 'bin/java.exe'))) { throw 'Set -JavaHome to a JDK 17–23 directory.' }
if (-not $SdkRoot) { $SdkRoot = $env:ANDROID_SDK_ROOT }
if (-not $SdkRoot) { $SdkRoot = Join-Path $env:LOCALAPPDATA 'WebOBS-Android/sdk' }
$SdkRoot = (Resolve-Path -LiteralPath $SdkRoot).Path
foreach ($required in @("platforms/android-$($lock.compileSdk)/android.jar", "build-tools/$($lock.buildTools)/apksigner.bat")) {
    if (-not (Test-Path (Join-Path $SdkRoot $required))) { throw "Missing SDK component: $required. See docs/android-client.md." }
}
$sdkProperty = $SdkRoot.Replace('\', '/').Replace(':', '\:')
[IO.File]::WriteAllText((Join-Path $projectRoot 'local.properties'), "sdk.dir=$sdkProperty`n", [Text.UTF8Encoding]::new($false))
$previousJava = $env:JAVA_HOME
try {
    $env:JAVA_HOME = $JavaHome
    $gradle = Join-Path $projectRoot 'gradlew.bat'
    if ($GradleHome) { $gradle = Join-Path $GradleHome 'bin/gradle.bat' }
    if ($GradleHome) {
        $gradleVersion = & $gradle --version
        if ($LASTEXITCODE -ne 0 -or $gradleVersion -notcontains "Gradle $($lock.gradle.version)") { throw 'Gradle must match toolchain.lock.json.' }
    }
    & $gradle --project-dir $projectRoot --console=plain "-PwebobsVersion=$Version" "-PwebobsVersionCode=$VersionCode" :app:testDebugUnitTest :app:lintDebug :app:assembleDebug
    if ($LASTEXITCODE -ne 0) { throw 'Android checks/build failed.' }
    $apk = Join-Path $projectRoot 'app/build/outputs/apk/debug/app-debug.apk'
    & (Join-Path $SdkRoot "build-tools/$($lock.buildTools)/apksigner.bat") verify --verbose --print-certs $apk
    if ($LASTEXITCODE -ne 0) { throw 'APK signature verification failed.' }
    $output = Join-Path $repoRoot 'build/android/out'
    New-Item -ItemType Directory -Force $output | Out-Null
    $named = Join-Path $output "WebOBS-$Version-android-DEVELOPMENT.apk"
    Copy-Item -LiteralPath $apk -Destination $named -Force
    $hash = (Get-FileHash -LiteralPath $named -Algorithm SHA256).Hash.ToLowerInvariant()
    [IO.File]::WriteAllText(($named + '.sha256'), "$hash  $([IO.Path]::GetFileName($named))`n", [Text.UTF8Encoding]::new($false))
    Write-Output "Built development APK: $named"
    if ($Serial) {
        if (-not $Adb) { $Adb = Join-Path $SdkRoot 'platform-tools/adb.exe' }
        & $Adb -s $Serial install -r $named
        if ($LASTEXITCODE -ne 0) { throw 'ADB install failed. Keep the existing signing key; do not uninstall to conceal a signature mismatch.' }
        & $Adb -s $Serial shell am start -n "$($lock.applicationId)/.MainActivity"
        if ($LASTEXITCODE -ne 0) { throw 'ADB launch failed.' }
    }
} finally { $env:JAVA_HOME = $previousJava }
