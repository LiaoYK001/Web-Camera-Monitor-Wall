#requires -Version 7.2
[CmdletBinding()]
param(
    [string]$Version = '3.5.0-dev.android.1',
    [Nullable[int]]$VersionCode,
    [switch]$Release,
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
if ($Release) {
    . (Join-Path $PSScriptRoot 'release-version.ps1')
    $identity = Get-WebOBSAndroidReleaseIdentity -Version $Version
    if ($null -ne $VersionCode -and $VersionCode -ne $identity.VersionCode) { throw 'Stable versionCode must match the deterministic A*1000000+B*1000+C mapping.' }
    $VersionCode = $identity.VersionCode
    foreach ($name in @('WEBOBS_ANDROID_KEYSTORE', 'WEBOBS_ANDROID_KEY_ALIAS', 'WEBOBS_ANDROID_STORE_PASSWORD', 'WEBOBS_ANDROID_KEY_PASSWORD')) {
        if (-not [Environment]::GetEnvironmentVariable($name)) { throw "Set $name in the private build environment; preserve the same self-signed key for every update." }
    }
    if (-not [IO.Path]::IsPathFullyQualified($env:WEBOBS_ANDROID_KEYSTORE)) { throw 'WEBOBS_ANDROID_KEYSTORE must be an absolute path outside the repository.' }
    $keyPath = (Resolve-Path -LiteralPath $env:WEBOBS_ANDROID_KEYSTORE).Path
    if (-not (Test-Path -LiteralPath $keyPath -PathType Leaf) -or $keyPath.StartsWith($repoRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'The Android release keystore must be a file outside the repository.' }
} else {
    if ($Version -notmatch '\A\d+\.\d+\.\d+-dev\.[0-9A-Za-z.-]+\z') { throw 'Use X.Y.Z-dev.* for development or explicitly select -Release for stable v4+ candidates.' }
    if ($null -eq $VersionCode) { $VersionCode = 3050001 }
}
if ($VersionCode -lt 1 -or $VersionCode -gt 2100000000) { throw 'VersionCode must be in 1..2100000000.' }
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
    $variant = if ($Release) { 'Release' } else { 'Debug' }
    & $gradle --project-dir $projectRoot --console=plain "-PwebobsVersion=$Version" "-PwebobsVersionCode=$VersionCode" "-PwebobsRelease=$($Release.IsPresent.ToString().ToLowerInvariant())" ":app:test${variant}UnitTest" ":app:lint${variant}" ":app:assemble${variant}"
    if ($LASTEXITCODE -ne 0) { throw 'Android checks/build failed.' }
    $apk = Join-Path $projectRoot "app/build/outputs/apk/$($variant.ToLowerInvariant())/app-$($variant.ToLowerInvariant()).apk"
    $signature = & (Join-Path $SdkRoot "build-tools/$($lock.buildTools)/apksigner.bat") verify --verbose --print-certs $apk
    if ($LASTEXITCODE -ne 0) { throw 'APK signature verification failed.' }
    $certificate = ($signature | Select-String '^Signer #1 certificate SHA-256 digest: ([a-fA-F0-9]{64})$').Matches.Groups[1].Value
    if (-not $certificate) { throw 'APK signing certificate digest missing.' }
    $output = Join-Path $repoRoot 'build/android/out'
    New-Item -ItemType Directory -Force $output | Out-Null
    $label = if ($Release) { 'SELF-SIGNED' } else { 'DEVELOPMENT' }
    $named = Join-Path $output "WebOBS-$Version-android-$label.apk"
    Copy-Item -LiteralPath $apk -Destination $named -Force
    $hash = (Get-FileHash -LiteralPath $named -Algorithm SHA256).Hash.ToLowerInvariant()
    [IO.File]::WriteAllText(($named + '.sha256'), "$hash  $([IO.Path]::GetFileName($named))`n", [Text.UTF8Encoding]::new($false))
    $receipt = @{ schema = 1; mode = $(if ($Release) { 'stable-candidate' } else { 'development' }); version = $Version; versionCode = $VersionCode; apk = [IO.Path]::GetFileName($named); sha256 = $hash; certificateSha256 = $certificate.ToLowerInvariant(); checks = @('unit', 'lint', 'assemble', 'signature'); published = $false }
    [IO.File]::WriteAllText(($named + '.json'), ($receipt | ConvertTo-Json -Depth 4) + "`n", [Text.UTF8Encoding]::new($false))
    Write-Output "Built $label APK candidate (not published): $named"
    if ($Serial) {
        if (-not $Adb) { $Adb = Join-Path $SdkRoot 'platform-tools/adb.exe' }
        & $Adb -s $Serial install -r $named
        if ($LASTEXITCODE -ne 0) { throw 'ADB install failed. Keep the existing signing key; do not uninstall to conceal a signature mismatch.' }
        & $Adb -s $Serial shell am start -n "$($lock.applicationId)/.MainActivity"
        if ($LASTEXITCODE -ne 0) { throw 'ADB launch failed.' }
    }
} finally { $env:JAVA_HOME = $previousJava }
