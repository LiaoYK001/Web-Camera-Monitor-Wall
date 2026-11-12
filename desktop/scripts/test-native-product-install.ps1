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
$appKey = 'HKCU:\Software\WebOBS\WallIntegration'
$uninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\WebOBSWallIntegration'
$shortcut = Join-Path ([Environment]::GetFolderPath('Programs')) 'WebOBS Wall Integration.lnk'
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
& $makensis /V2 "/DVERSION=$version" "/DPACKAGE_DIR=$runtime" "/DOUTPUT_DIR=$out" "/DOWNED_REMOVALS=$removals" (Join-Path $repoRoot 'native-host/installer/WebOBSProductIntegration.nsi')
if ($LASTEXITCODE -ne 0) { throw 'Internal integrated NSIS compilation failed.' }
$setup = Join-Path $out "WebOBS-Wall-$version-INTERNAL-SETUP.exe"
if (-not (Test-Path -LiteralPath $setup -PathType Leaf)) { throw 'Internal installer missing.' }
$privateRoot = Join-Path ([IO.Path]::GetTempPath()) ('WebOBS Wall 安装-' + [Guid]::NewGuid().ToString('N'))
& $python -B (Join-Path $repoRoot 'desktop/python/private_directory.py') $privateRoot
if ($LASTEXITCODE -ne 0) { throw 'Private install scope protection failed.' }
$installed = Join-Path $privateRoot 'app'
$profile = Join-Path $privateRoot 'profile'
$report = [ordered]@{
    schema=1;kind='internal-native-product-nsis';version=$version;sourceRevision=$payload.sourceRevision
    passed=$false;publicationForbidden=$true;freshInstalledEntryQualified=$false
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
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($shortcut)
    $expectedTarget = [IO.Path]::GetFullPath((Join-Path $installed 'bin/webobs-wall.exe'))
    # Shell links may return existing 8.3 aliases. GetFullPath only performs
    # lexical normalization; expand both existing paths before exact comparison.
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;
public static class WebOBSInstalledShortcutPath {
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, ExactSpelling=true, SetLastError=true)]
    private static extern uint GetLongPathNameW(string path, StringBuilder result, uint size);
    public static string ExistingLongPath(string path) {
        var result = new StringBuilder(32768);
        uint count = GetLongPathNameW(path, result, (uint)result.Capacity);
        if (count == 0 || count >= result.Capacity) throw new Win32Exception(Marshal.GetLastWin32Error());
        return result.ToString();
    }
}
'@
    $target = [string]$link.TargetPath
    $report.shortcutTargetPresent = -not [string]::IsNullOrEmpty($target)
    $report.shortcutTargetExists = $report.shortcutTargetPresent -and (Test-Path -LiteralPath $target -PathType Leaf)
    $report.shortcutTargetUsesShortAlias = $target -match '(?i)~[0-9]+(?:\\|$)'
    $report.shortcutTargetFileNameMatches = [string]::Equals([IO.Path]::GetFileName($target), 'webobs-wall.exe', [StringComparison]::OrdinalIgnoreCase)
    $report.shortcutTargetMatches = $report.shortcutTargetExists -and [string]::Equals(
        [WebOBSInstalledShortcutPath]::ExistingLongPath([IO.Path]::GetFullPath($target)),
        [WebOBSInstalledShortcutPath]::ExistingLongPath($expectedTarget), [StringComparison]::OrdinalIgnoreCase)
    $report.shortcutArgumentsEmpty = [string]::IsNullOrEmpty($link.Arguments)
    if (-not $report.shortcutTargetMatches -or -not $report.shortcutArgumentsEmpty) {
        throw 'Installed shortcut does not target the unified native entry.'
    }
    [Runtime.InteropServices.Marshal]::FinalReleaseComObject($link) | Out-Null
    [Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell) | Out-Null
    $phase = 'installed-entry-ui-and-media'
    & $python -B (Join-Path $repoRoot 'native-host/tests/product_windows.py') --runtime $installed --with-media --retained-profile $profile --report (Join-Path $buildRoot 'native-product-installed-ui.json')
    if ($LASTEXITCODE -ne 0) { throw 'Actual installed product entry/UI/media gate failed.' }
    $report.freshInstalledEntryQualified = $true
    foreach ($file in @('config/cluster.sqlite3','config/cameras.db')) {
        if (-not (Test-Path -LiteralPath (Join-Path $profile $file))) { throw 'Installed account/camera data missing.' }
    }
    function Get-ProfileFingerprint {
        @((Get-ChildItem -LiteralPath $profile -Recurse -File | Sort-Object FullName) | ForEach-Object {
            $_.FullName.Substring($profile.Length) + ':' + (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
        }) -join "`n"
    }
    $before = Get-ProfileFingerprint
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
    if ((Get-ProfileFingerprint) -ne $before -or [IO.File]::ReadAllText($unknown) -ne 'private synthetic uninstall-retention marker') {
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
