#requires -Version 7.2
# Build and qualify a fresh internal integrated installation. No legacy upgrade,
# stable feed, existing installation/profile or public binary publication.
param([Parameter(Mandatory=$true)][string]$BuildDirectory)
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$buildRoot = [IO.Path]::GetFullPath($BuildDirectory)
$runtime = Join-Path $buildRoot 'runtime'
$python = Join-Path $runtime 'python/python.exe'
$verifier = Join-Path $repoRoot 'native-host/scripts/product_package.py'
$manifest = Get-Content -LiteralPath (Join-Path $runtime 'webobs-native-prototype.json') -Raw | ConvertFrom-Json
$preview = $manifest.releaseProfile -eq 'native-monitor-preview'
$complete = (Test-Path -LiteralPath (Join-Path $runtime 'services/events/event_service.py')) -and
            (Test-Path -LiteralPath (Join-Path $runtime 'bin/go2rtc.exe'))
$appKey = 'HKCU:\Software\WebOBS\WallIntegration'
$uninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\WebOBSWallIntegration'
$shortcut = Join-Path ([Environment]::GetFolderPath('Programs')) 'WebOBS Wall Integration.lnk'
if ($complete) {
    $appKey = 'HKCU:\Software\WebOBS\Wall'
    $uninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\WebOBSWall'
    $shortcut = Join-Path ([Environment]::GetFolderPath('Programs')) 'WebOBS Wall.lnk'
}
if ($preview) {
    $appKey = 'HKCU:\Software\WebOBS\WallPreview'
    $uninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\WebOBSWallPreview'
    $shortcut = Join-Path ([Environment]::GetFolderPath('Programs')) 'WebOBS Wall v4.5 Preview.lnk'
}
if ((Test-Path $appKey) -or (Test-Path $uninstallKey) -or (Test-Path -LiteralPath $shortcut)) {
    throw 'Existing integration installation or shortcut: qualification refuses to replace it.'
}
$out = Join-Path $buildRoot 'internal-installer'
if (Test-Path -LiteralPath $out) { throw 'Installer gate requires a new output directory.' }
New-Item -ItemType Directory $out | Out-Null
$removals = Join-Path $out 'owned-removals.nsh'
$payloadJson = & $python -B $verifier --runtime $runtime --removals $removals
if ($LASTEXITCODE -ne 0) { throw 'Clean product payload verification failed.' }
$payload = $payloadJson | ConvertFrom-Json
$version = $payload.version
$makensis = (Get-Command makensis.exe -ErrorAction Stop).Source
$nsisArgs = @('/V2',"/DVERSION=$version","/DPACKAGE_DIR=$runtime","/DOUTPUT_DIR=$out","/DOWNED_REMOVALS=$removals")
if ($preview) { $nsisArgs += '/DNATIVE_PREVIEW' }
if ($complete) { $nsisArgs += '/DCOMPLETE' }
& $makensis @nsisArgs (Join-Path $repoRoot 'native-host/installer/WebOBSProductIntegration.nsi')
if ($LASTEXITCODE -ne 0) { throw 'Internal integrated NSIS compilation failed.' }
$setup = Join-Path $out "WebOBS-Wall-$version-INTERNAL-SETUP.exe"
if ($preview) { $setup = Join-Path $out "WebOBS-Wall-$version-windows-x64-PREVIEW-UNSIGNED.exe" }
if ($complete) { $setup = Join-Path $out "WebOBS-Wall-$version-windows-x64-SETUP.exe" }
if (-not (Test-Path -LiteralPath $setup -PathType Leaf)) { throw 'Internal installer missing.' }
$privateRoot = Join-Path ([IO.Path]::GetTempPath()) ('WebOBS Wall 安装-' + [Guid]::NewGuid().ToString('N'))
& $python -B (Join-Path $repoRoot 'desktop/python/private_directory.py') $privateRoot
if ($LASTEXITCODE -ne 0) { throw 'Private install scope protection failed.' }
$installed = Join-Path $privateRoot 'app'
$profile = Join-Path $privateRoot 'profile'
if ($preview) { $profile = Join-Path $privateRoot 'local-data/WebOBS/NativePreview' }
$report = [ordered]@{
    schema=1;kind=$(if ($complete) { 'native-complete-candidate-nsis' } else { 'internal-native-product-nsis' })
    version=$version;sourceRevision=$payload.sourceRevision
    passed=$false;publicationForbidden=$payload.publicationForbidden;freshInstalledEntryQualified=$false
    legacyUpgradeQualified=$false;fullFeatureMigrationQualified=$false
    setupBytes=(Get-Item -LiteralPath $setup).Length
    setupSha256=(Get-FileHash -LiteralPath $setup -Algorithm SHA256).Hash.ToLowerInvariant()
}
$phase = 'install'
try {
    . (Join-Path $repoRoot 'desktop/tests/installed-tree-footprint.ps1')
    $scope = New-InstalledTreeFootprintScope -Root $installed -Purpose isolated-nsis-install-before-first-start
    $install = Start-Process -FilePath $setup -ArgumentList '/S', "/D=$installed" -Wait -PassThru
    if ($install.ExitCode -ne 0) { throw 'Actual NSIS fresh installation failed.' }
    $phase = 'installed-registration'
    if ((Get-ItemProperty $appKey).InstallDir -ne $installed -or
        (Get-ItemProperty $uninstallKey).InstallLocation -ne $installed) { throw 'Installed registry identity mismatch.' }
    $phase = 'installed-payload'
    $installedPayload = & $python -B $verifier --runtime $installed --installed
    if ($LASTEXITCODE -ne 0) { throw 'Installed payload hash verification failed.' }
    $installedPayload = $installedPayload | ConvertFrom-Json
    $phase = 'installed-footprint'
    $footprint = Measure-InstalledTreeFootprint -Scope $scope
    if ($footprint.logicalBytes -ne $installedPayload.totalBytes) { throw 'Installed byte accounting mismatch.' }
    $report.footprint = $footprint
    $phase = 'installed-shortcut'
    if (-not (Test-Path -LiteralPath $shortcut -PathType Leaf)) { throw 'Installed integration shortcut missing.' }
    # WScript.Shell.TargetPath loses Unicode in this runner's ACP 1252 even
    # when the link is valid. Read the actual IShellLinkW target/arguments.
    $probe = Join-Path $out 'shortcut-probe.exe'
    & cl.exe /nologo /std:c++20 /EHsc /W4 /WX (Join-Path $repoRoot 'desktop/tests/native-shortcut-probe.cpp') "/Fe:$probe" "/Fo:$out/shortcut-probe.obj" ole32.lib uuid.lib
    if ($LASTEXITCODE -ne 0) { throw 'Native Unicode shortcut reader compilation failed.' }
    $expectedTarget = [IO.Path]::GetFullPath((Join-Path $installed 'bin/webobs-wall.exe'))
    $observedShortcut = & $probe $shortcut $expectedTarget | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw 'Native Unicode shortcut reader failed.' }
    $report.shortcutReader = 'IShellLinkW/GetPath/GetArguments'
    $report.shortcutTargetPresent = $observedShortcut.targetLength -gt 0
    $report.shortcutTargetExists = $observedShortcut.nativeTargetExists
    $report.shortcutTargetMatches = $observedShortcut.canonicalTargetMatches
    $report.shortcutArgumentsEmpty = $observedShortcut.argumentsEmpty
    if (-not $report.shortcutTargetPresent -or -not $report.shortcutTargetExists -or
        -not $report.shortcutTargetMatches -or -not $report.shortcutArgumentsEmpty) {
        throw 'Installed shortcut does not target the unified native entry.'
    }
    $phase = 'installed-entry-ui-and-media'
    & $python -B (Join-Path $repoRoot 'native-host/tests/product_windows.py') --runtime $installed --with-media --retained-profile $profile --report (Join-Path $buildRoot 'native-product-installed-ui.json')
    if ($LASTEXITCODE -ne 0) { throw 'Actual installed product entry/UI/media gate failed.' }
    $report.freshInstalledEntryQualified = $true
    foreach ($file in @('config/cluster.sqlite3','config/cameras.db')) {
        if (-not (Test-Path -LiteralPath (Join-Path $profile $file))) { throw 'Installed account/camera data missing.' }
    }
    $phase = 'interrupted-restore-pair-recovery'
    # The installed runtime's own backup service and supervisor: a restore killed
    # between its two directory swaps must converge on the next product start.
    $restoreParent = Join-Path $env:RUNNER_TEMP 'native-restore-pair'
    if (Test-Path -LiteralPath $restoreParent) { Remove-Item -Recurse -Force -LiteralPath $restoreParent }
    New-Item -ItemType Directory -Path $restoreParent | Out-Null
    & $python -B (Join-Path $repoRoot 'native-host/tests/backup_restore_windows.py') --runtime $installed --profile-parent $restoreParent --report (Join-Path $buildRoot 'native-product-restore-pair.json')
    if ($LASTEXITCODE -ne 0) { throw 'Installed restore-pair recovery gate failed.' }
    $report.restorePairRecoveryQualified = $true
    function Get-ProfileFingerprint {
        # Hash only durable user data. Update metadata, generated backups,
        # logs/crash dumps, per-run sentinels and SQLite WAL sidecars are
        # runtime artifacts; opening a WAL database read-only can create an
        # empty WAL/SHM pair even when no user row changed.
        $state = @{}
        foreach ($file in @(Get-ChildItem -LiteralPath $profile -Recurse -File)) {
            $relative = $file.FullName.Substring($profile.Length + 1).Replace('\', '/')
            if ($relative -match '^(run|backups)/' -or
                $relative -match '(^|/)(logs|crashes)/' -or
                $relative -match '(^|/)\.sentinel(/|$)' -or
                $relative -match '\.(db|sqlite3)-(wal|shm)$') {
                continue
            }
            $state[$relative] = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
        }
        return $state
    }
    function Compare-ProfileFingerprint($before, $after) {
        $paths = @(@($before.Keys) + @($after.Keys) | Sort-Object -Unique)
        return ,@($paths | Where-Object { $before[$_] -ne $after[$_] })
    }
    $before = Get-ProfileFingerprint
    if ($complete) {
        $phase = 'installed-lan-entry'
        & $python -B (Join-Path $repoRoot 'native-host/tests/lan_entry_windows.py') --runtime $installed --report (Join-Path $buildRoot 'native-product-lan.json')
        if ($LASTEXITCODE -ne 0) { throw 'Installed LAN/Web HTTPS entry gate failed.' }
        # The receipt states whether a private LAN HTTPS interface actually existed on this
        # machine. Copy its real value; a runner without a private IPv4 must not be recorded
        # as qualified LAN delivery.
        $lanReceiptPath = Join-Path $buildRoot 'native-product-lan.json'
        if (-not (Test-Path -LiteralPath $lanReceiptPath)) { throw 'LAN entry receipt is missing.' }
        $lanReceipt = Get-Content -LiteralPath $lanReceiptPath -Raw | ConvertFrom-Json
        if ($lanReceipt.passed -ne $true) { throw 'LAN entry receipt did not pass.' }
        $report.lanEntryQualified = [bool]$lanReceipt.lanHttpsQualified
        $report.lanEntrySkipReason = [string]$lanReceipt.lanHttpsSkipReason
        $phase = 'same-machine-upgrade'
        $match = [regex]::Match($version, '^(5\.[01]\.0-rc\.)([0-9]+)$')
        if (-not $match.Success) { throw 'Complete candidate version is not rc.N.' }
        $upgradeVersion = $match.Groups[1].Value + ([int]$match.Groups[2].Value + 1)
        $upgradeOut = Join-Path $buildRoot 'upgrade-installer'
        New-Item -ItemType Directory $upgradeOut | Out-Null
        $upgradeRuntime = Join-Path $buildRoot 'upgrade-runtime'
        & $python -B (Join-Path $repoRoot 'native-host/tests/prepare_upgrade_runtime.py') --runtime $runtime --output $upgradeRuntime --version $upgradeVersion
        if ($LASTEXITCODE -ne 0) { throw 'Distinct upgrade runtime preparation failed.' }
        $upgradeRemovals = Join-Path $upgradeOut 'owned-removals.nsh'
        $null = & $python -B $verifier --runtime $upgradeRuntime --removals $upgradeRemovals
        if ($LASTEXITCODE -ne 0) { throw 'Upgrade payload verification failed.' }
        $upgradeArgs = @('/V2',"/DVERSION=$upgradeVersion","/DPACKAGE_DIR=$upgradeRuntime",
            "/DOUTPUT_DIR=$upgradeOut","/DOWNED_REMOVALS=$upgradeRemovals",'/DCOMPLETE')
        & $makensis @upgradeArgs (Join-Path $repoRoot 'native-host/installer/WebOBSProductIntegration.nsi')
        if ($LASTEXITCODE -ne 0) { throw 'Upgrade NSIS compilation failed.' }
        $upgradeSetup = Join-Path $upgradeOut "WebOBS-Wall-$upgradeVersion-windows-x64-SETUP.exe"
        if (-not (Test-Path -LiteralPath $upgradeSetup -PathType Leaf)) { throw 'Upgrade installer missing.' }
        if ((Get-FileHash -LiteralPath $upgradeSetup -Algorithm SHA256).Hash -eq
            (Get-FileHash -LiteralPath $setup -Algorithm SHA256).Hash) {
            throw 'Upgrade installer is byte-identical to the fresh installer.'
        }
        & $python -B (Join-Path $repoRoot 'native-host/tests/update_windows.py') --runtime $runtime --installer $upgradeSetup --profile $profile --installed $installed --report (Join-Path $buildRoot 'native-product-updater.json')
        if ($LASTEXITCODE -ne 0) { throw 'Actual installed updater/NSIS upgrade failed.' }
        $phase = 'same-machine-upgrade-version'
        $registeredVersion = (Get-ItemProperty $uninstallKey).DisplayVersion
        $report.registeredVersion = $registeredVersion
        if ($registeredVersion -ne $upgradeVersion) { throw 'Upgrade did not update the installed version registration.' }
        $phase = 'same-machine-upgrade-profile-fingerprint'
        $afterUpgrade = Get-ProfileFingerprint
        $changedAfterUpgrade = Compare-ProfileFingerprint $before $afterUpgrade
        $report.profileFingerprintBeforeCount = $before.Count
        $report.profileFingerprintAfterCount = $afterUpgrade.Count
        if ($changedAfterUpgrade.Count -ne 0) {
            $report.profileFingerprintChangedPaths = @($changedAfterUpgrade | Select-Object -First 32)
            throw 'Upgrade changed retained account/profile data.'
        }
        $report.upgradeVersion = $upgradeVersion
        $report.sameMachineUpgradeQualified = $true
        $report.installedUpdaterQualified = $true
        $report.retentionScope = 'durable profile files excluding run/backups, logs/crashes/sentinels and SQLite WAL sidecars'
        $phase = 'same-machine-upgrade-inventory'
        $null = & $python -B $verifier --runtime $installed --installed
        if ($LASTEXITCODE -ne 0) { throw 'Upgraded runtime inventory/version failed.' }
        $phase = 'upgraded-entry-ui-and-media'
        & $python -B (Join-Path $repoRoot 'native-host/tests/product_windows.py') --runtime $installed --with-media --retained-profile (Join-Path $privateRoot 'upgraded-profile') --report (Join-Path $buildRoot 'native-product-upgraded-ui.json')
        if ($LASTEXITCODE -ne 0) { throw 'New payload did not pass actual upgraded entry/media.' }
        $report.upgradedEntryQualified = $true
    }
    $unknown = Join-Path $installed 'user-notes.txt'
    [IO.File]::WriteAllText($unknown, 'private synthetic uninstall-retention marker')
    $phase = 'uninstall-and-retain-data'
    $uninstall = Start-Process -FilePath (Join-Path $installed 'Uninstall.exe') -ArgumentList '/S' -Wait -PassThru
    if ($uninstall.ExitCode -ne 0) { throw 'Actual NSIS uninstall failed.' }
    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    do {
        $remaining = @(Get-ChildItem -LiteralPath $installed -Recurse -File -ErrorAction SilentlyContinue)
        $done = -not (Test-Path $appKey) -and -not (Test-Path $uninstallKey) -and
                -not (Test-Path -LiteralPath $shortcut) -and $remaining.Count -eq 1 -and
                $remaining[0].FullName -eq $unknown
        if (-not $done) { Start-Sleep -Milliseconds 100 }
    } until ($done -or [DateTime]::UtcNow -ge $deadline)
    if (-not $done) { throw 'Owned files/registration/shortcut survived uninstall.' }
    $afterUninstall = Get-ProfileFingerprint
    $changedAfterUninstall = Compare-ProfileFingerprint $before $afterUninstall
    $report.profileFingerprintAfterUninstallCount = $afterUninstall.Count
    if ($changedAfterUninstall.Count -ne 0 -or
        [IO.File]::ReadAllText($unknown) -ne 'private synthetic uninstall-retention marker') {
        if ($changedAfterUninstall.Count -ne 0) {
            $report.profileFingerprintChangedPaths = @($changedAfterUninstall | Select-Object -First 32)
        }
        throw 'Uninstall changed retained account/profile or unknown files.'
    }
    $report.retainedProfileUnchanged = $true
    $report.unknownFilesRetained = $true
    $report.passed = $true
    # All processes were checked by the actual UI/Job gate, and uninstall has
    # removed every owned binary. Only this new synthetic scope is deleted.
    Remove-Item -LiteralPath $privateRoot -Recurse -Force
} catch {
    $report.failurePhase = $phase
    $report.exceptionType = $_.Exception.GetType().FullName
    $report.errorId = if ($_.FullyQualifiedErrorId -match '^[A-Za-z0-9_.-]{1,96}$') { $_.FullyQualifiedErrorId } else { 'private-detail-redacted' }
    throw 'Internal native product installer gate failed; see sanitized phase receipt.'
} finally {
    $report | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath (Join-Path $buildRoot 'native-product-nsis.json') -Encoding utf8
    $report | ConvertTo-Json -Depth 16 -Compress | Write-Output
}
