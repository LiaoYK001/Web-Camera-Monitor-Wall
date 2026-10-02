#requires -Version 7.2
[CmdletBinding()]
param([string]$Version = '')
# Actual per-user NSIS validation. Never replace an existing product installation.
# This is a host smoke test, not clean-machine or camera qualification.
$ErrorActionPreference='Stop'
if (-not $IsWindows -or -not [Environment]::Is64BitOperatingSystem) {throw 'Requires Windows x64'}
$repoRoot=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
if(-not $Version){$Version=$env:WEBOBS_DESKTOP_VERSION}
if(-not $Version){$Version=(Get-Content -LiteralPath (Join-Path $repoRoot 'desktop/package.json') -Raw|ConvertFrom-Json).version}
if($Version -notmatch '^\d+\.\d+\.\d+(?:-dev\.[0-9A-Za-z.-]+)?$'){throw 'Invalid installer version'}
function ProductEntries {
    @(Get-ChildItem 'HKCU:/Software/Microsoft/Windows/CurrentVersion/Uninstall','HKLM:/Software/Microsoft/Windows/CurrentVersion/Uninstall' -ErrorAction SilentlyContinue | Get-ItemProperty -ErrorAction SilentlyContinue | Where-Object {$_.DisplayName -match '^WebOBS($|\s)'})
}
if ((ProductEntries).Count) { throw 'An existing WebOBS installation is present; installer validation will not replace it.' }
$shortcuts=@((Join-Path ([Environment]::GetFolderPath('Desktop')) 'WebOBS.lnk'),(Join-Path ([Environment]::GetFolderPath('Programs')) 'WebOBS.lnk'))
if (@($shortcuts | Where-Object {Test-Path -LiteralPath $_}).Count) { throw 'Existing WebOBS shortcuts must remain untouched.' }
$lease=[Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,18080)
try {$lease.Start()} finally {$lease.Stop()}
$buildRoot=Join-Path $repoRoot 'build'
New-Item -ItemType Directory -Path $buildRoot -Force | Out-Null
$testRoot=Join-Path $buildRoot ('nsis-check-'+[Guid]::NewGuid().ToString('N'))
$installRoot=Join-Path $testRoot '客户端 安装'
$profileRoot=Join-Path $testRoot 'profile'
$dataRoot=Join-Path $profileRoot 'WebOBS'
$recordings=Join-Path $testRoot 'Videos/WebOBS'
New-Item -ItemType Directory -Path $dataRoot,$recordings -Force | Out-Null
@{recordingDirectory=$recordings} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $dataRoot 'desktop.json') -Encoding utf8NoBOM
$candidates=@(Get-ChildItem -LiteralPath (Join-Path $repoRoot "desktop/out/$Version") -Filter "WebOBS-$Version-windows-x64*.exe" -File)
if($candidates.Count -ne 1){throw 'Expected exactly one complete NSIS installer'}
$installer=$candidates[0].FullName
$originalLocalAppData=$env:LOCALAPPDATA
$originalPath=$env:PATH
$testApp=$null;$installed=$false;$validated=$false
try {
    $env:LOCALAPPDATA=$profileRoot
    $installation=Start-Process -FilePath $installer -ArgumentList @('/S',"/D=$installRoot") -WindowStyle Hidden -Wait -PassThru
    if($installation.ExitCode -ne 0) {throw "NSIS install failed ($($installation.ExitCode))"}
    $installed=$true
    if(-not (Test-Path -LiteralPath (Join-Path $installRoot 'WebOBS.exe'))) {throw 'Installer omitted the executable'}
    if((ProductEntries).Count -ne 1) {throw 'Per-user installation registration missing'}
    node (Join-Path $repoRoot 'desktop/scripts/verify-runtime.mjs') (Join-Path $installRoot 'resources/runtime')
    if($LASTEXITCODE -ne 0) {throw 'Installed runtime failed integrity validation'}
    $testedManifest=Get-Content -LiteralPath (Join-Path $installRoot 'resources/runtime/manifest.json') -Raw | ConvertFrom-Json
    $env:PATH=Join-Path $env:SystemRoot 'System32'
    $testApp=Start-Process -FilePath (Join-Path $installRoot 'WebOBS.exe') -WorkingDirectory $installRoot -WindowStyle Hidden -PassThru
    $origin='http://127.0.0.1:18080'
    $deadline=[DateTime]::UtcNow.AddSeconds(120)
    $ready=$false
    while([DateTime]::UtcNow -lt $deadline) {
        if($testApp.HasExited) {throw "Installed app exited ($($testApp.ExitCode))"}
        try {$response=Invoke-WebRequest -Uri "$origin/api/v1/health" -TimeoutSec 1; $ready=$response.StatusCode -eq 200} catch {$ready=$false}
        if($ready){break};Start-Sleep -Milliseconds 300
    }
    if(-not $ready){throw 'Installed native services failed to start'}
    $credentials=@{username='nsis-validation-admin';password=([Guid]::NewGuid().ToString('N')+[Guid]::NewGuid().ToString('N'))}|ConvertTo-Json -Compress
    $setup=Invoke-WebRequest -Uri "$origin/api/v1/auth/setup" -Method Post -Headers @{Origin=$origin} -ContentType 'application/json' -Body $credentials
    if($setup.StatusCode -ne 201){throw 'Installed first-account setup failed'}
    $login=Invoke-WebRequest -Uri "$origin/api/v1/auth/login" -Method Post -Headers @{Origin=$origin} -ContentType 'application/json' -Body $credentials -SessionVariable accountSession
    if($login.StatusCode -ne 200){throw 'Installed first login failed'}
    foreach($route in @('/api/v1/auth/session','/api/v1/runtime/info','/api/v1/go2rtc/api/streams')) {
        $response=Invoke-WebRequest -Uri ($origin+$route) -Headers @{Origin=$origin} -WebSession $accountSession
        if($response.StatusCode -ne 200){throw "Installed authenticated route failed ($route)"}
    }
    $marker=Join-Path $dataRoot 'uninstall-retention.marker';'isolated validation'|Set-Content -LiteralPath $marker
    Stop-Process -Id $testApp.Id
    $deadline=[DateTime]::UtcNow.AddSeconds(45)
    do {
        $remaining=@(Get-CimInstance Win32_Process | Where-Object {$_.ExecutablePath -and $_.ExecutablePath.StartsWith($installRoot+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)})
        if($remaining.Count){Start-Sleep -Milliseconds 500}
    } while($remaining.Count -and [DateTime]::UtcNow -lt $deadline)
    if($remaining.Count){throw 'Installed application left child processes running'}
    $uninstaller=Join-Path $installRoot 'Uninstall WebOBS.exe'
    $removed=Start-Process -FilePath $uninstaller -ArgumentList '/S' -WindowStyle Hidden -Wait -PassThru
    if($removed.ExitCode -ne 0){throw "Uninstall failed ($($removed.ExitCode))"}
    $installed=$false
    if(-not (Test-Path -LiteralPath $marker)){throw 'Default uninstall removed user data'}
    if((ProductEntries).Count){throw 'Uninstall left product registration'}
    if(@($shortcuts|Where-Object {Test-Path -LiteralPath $_}).Count){throw 'Uninstall left product shortcuts'}
    $hostOS=Get-CimInstance Win32_OperatingSystem
    @{schema=1;revision=$testedManifest.revision;version=$Version;installerSha256=(Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant();hostOS=$hostOS.Caption;hostVersion=$hostOS.Version;testedAt=[DateTime]::UtcNow.ToString('o');checks=@{nsisInstall='passed';unicodePath='passed';runtimeIntegrity='passed';cleanPathStartup='passed';firstLogin='passed';authenticatedGo2rtc='passed';ownerCrashCleanup='passed';defaultUninstallDataRetention='passed';registrationAndShortcutCleanup='passed'};qualification='host-smoke-only; not clean-machine, camera or signed-update qualification'} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $candidates[0].DirectoryName 'windows-install-smoke.json') -Encoding utf8NoBOM
    $validated=$true
    Write-Output 'Actual Windows x64 NSIS install, Unicode path, clean-PATH startup, first login, authenticated go2rtc, owner cleanup and uninstall data retention passed. This is a host smoke test; clean-machine, Windows 10/11 media and signed-update qualification remain separate.'
} finally {
    $env:LOCALAPPDATA=$originalLocalAppData;$env:PATH=$originalPath
    if($testApp -and -not $testApp.HasExited) {Stop-Process -Id $testApp.Id -ErrorAction SilentlyContinue}
    if($installed -and (Test-Path -LiteralPath (Join-Path $installRoot 'Uninstall WebOBS.exe'))) {
        $cleanup=Start-Process -FilePath (Join-Path $installRoot 'Uninstall WebOBS.exe') -ArgumentList '/S' -WindowStyle Hidden -Wait -PassThru
    }
    if($validated) {
        $absolute=[IO.Path]::GetFullPath($testRoot)
        if($absolute.StartsWith($buildRoot+[IO.Path]::DirectorySeparatorChar+'nsis-check-',[StringComparison]::OrdinalIgnoreCase) -and -not (Get-Item -LiteralPath $absolute).Attributes.HasFlag([IO.FileAttributes]::ReparsePoint)) {Remove-Item -LiteralPath $absolute -Recurse -Force}
    }
}
