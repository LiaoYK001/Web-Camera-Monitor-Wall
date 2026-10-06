#requires -Version 7.2
[CmdletBinding()]
param([Parameter(Mandatory)][string]$Version,
      [Parameter(Mandatory)][string]$OutputDirectory,
      [ValidateSet('base', 'next', 'next2', 'wrong-key', 'wrong-package')][string]$Kind = 'base',
      [string]$JavaHome = 'D:/zulu',
      [string]$SdkRoot = "$env:LOCALAPPDATA/WebOBS-Android/sdk")
$ErrorActionPreference = 'Stop'
$repository = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$project = Join-Path $repository 'android'
$allowed = [IO.Path]::GetFullPath((Join-Path $repository 'build/android/update-qualification')) + [IO.Path]::DirectorySeparatorChar
$output = [IO.Path]::GetFullPath($OutputDirectory)
if (-not $output.StartsWith($allowed, [StringComparison]::OrdinalIgnoreCase)) { throw 'Qualification outputs must stay under build/android/update-qualification/<owned-run>.' }
New-Item -ItemType Directory -Force -Path $output | Out-Null
. (Join-Path $repository 'android/scripts/release-version.ps1')
$identity = Get-WebOBSAndroidReleaseIdentity $Version
$lock = Get-Content (Join-Path $project 'toolchain.lock.json') -Raw | ConvertFrom-Json
if ((Get-FileHash (Join-Path $project 'gradle/wrapper/gradle-wrapper.jar') -Algorithm SHA256).Hash.ToLowerInvariant() -ne $lock.wrapperSha256) { throw 'Wrapper checksum mismatch.' }
$previousJava = $env:JAVA_HOME
try {
    $env:JAVA_HOME = $JavaHome
    $sdkProperty = $SdkRoot.Replace('\', '/').Replace(':', '\:')
    [IO.File]::WriteAllText((Join-Path $project 'local.properties'), "sdk.dir=$sdkProperty`n", [Text.UTF8Encoding]::new($false))
    $qualification = if ($Kind -eq 'wrong-package') { 'false' } else { 'true' }
    $tasks = @(':app:assembleRelease')
    if ($Kind -eq 'base') { $tasks = @(':app:testReleaseUnitTest', ':app:lintRelease', ':app:assembleRelease', ':app:assembleReleaseAndroidTest') }
    & (Join-Path $project 'gradlew.bat') --project-dir $project --console=plain "-PwebobsVersion=$Version" "-PwebobsVersionCode=$($identity.VersionCode)" '-PwebobsRelease=true' "-PwebobsUpdateQualification=$qualification" @tasks
    if ($LASTEXITCODE -ne 0) { throw 'Qualification build failed.' }
    $apk = Join-Path $project 'app/build/outputs/apk/release/app-release.apk'
    $named = Join-Path $output "$Kind.apk"
    Copy-Item -LiteralPath $apk -Destination $named
    & (Join-Path $SdkRoot 'build-tools/35.0.0/apksigner.bat') verify $named
    if ($LASTEXITCODE -ne 0) { throw 'Qualification APK signature failed.' }
    if ($Kind -eq 'base') { Copy-Item -LiteralPath (Join-Path $project 'app/build/outputs/apk/androidTest/release/app-release-androidTest.apk') -Destination (Join-Path $output 'instrumentation.apk') }
    $metadata = Get-Content (Join-Path $project 'app/build/outputs/apk/release/output-metadata.json') -Raw | ConvertFrom-Json
    @{ version=$Version; versionCode=$metadata.elements[0].versionCode; applicationId=$metadata.applicationId; sha256=(Get-FileHash $named -Algorithm SHA256).Hash.ToLowerInvariant(); published=$false } | ConvertTo-Json | Set-Content (Join-Path $output "$Kind.json")
} finally { $env:JAVA_HOME = $previousJava }
