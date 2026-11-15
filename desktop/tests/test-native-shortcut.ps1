#requires -Version 7.2
# Actual NSIS/Shell-Link reproduction with an inert payload, not product qualification.
param([Parameter(Mandatory=$true)][string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$output = [IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path -LiteralPath $output) { throw 'Shortcut contract output must be new.' }
New-Item -ItemType Directory $output | Out-Null
$probe = Join-Path $output 'shortcut-probe.exe'
& cl.exe /nologo /std:c++20 /EHsc /W4 /WX (Join-Path $PSScriptRoot 'native-shortcut-probe.cpp') "/Fe:$probe" "/Fo:$output/shortcut-probe.obj" ole32.lib uuid.lib
if ($LASTEXITCODE -ne 0) { throw 'Native Shell Link reader compilation failed.' }
$shortcut = Join-Path ([Environment]::GetFolderPath('Programs')) 'WebOBS Wall Integration.lnk'
$appKey = 'HKCU:\Software\WebOBS\WallIntegration'
$uninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\WebOBSWallIntegration'
if ((Test-Path $appKey) -or (Test-Path $uninstallKey) -or (Test-Path -LiteralPath $shortcut)) {
    throw 'Existing integration installation or shortcut must remain untouched.'
}
$payload = Join-Path $output 'inert-payload'
New-Item -ItemType Directory (Join-Path $payload 'bin') | Out-Null
[IO.File]::WriteAllText((Join-Path $payload 'bin/webobs-wall.exe'), 'Inert nonexecutable shortcut fixture.')
$removals = Join-Path $output 'owned-removals.nsh'
[IO.File]::WriteAllText($removals, 'Delete "$INSTDIR\bin\webobs-wall.exe"' + "`n" + 'RMDir "$INSTDIR\bin"' + "`n")
& makensis.exe /V2 /DVERSION=4.1.0-dev.shortcut "/DPACKAGE_DIR=$payload" "/DOUTPUT_DIR=$output" "/DOWNED_REMOVALS=$removals" (Join-Path $repo 'native-host/installer/WebOBSProductIntegration.nsi')
if ($LASTEXITCODE -ne 0) { throw 'Synthetic payload installer compilation failed.' }
$setup = Join-Path $output 'WebOBS-Wall-4.1.0-dev.shortcut-INTERNAL-SETUP.exe'
$results = @()
foreach ($scope in @('ascii', 'unicode')) {
    $name = if ($scope -eq 'ascii') { 'WebOBS Wall shortcut-' } else { 'WebOBS Wall 安装-' }
    $installed = Join-Path ([IO.Path]::GetTempPath()) ($name + [Guid]::NewGuid().ToString('N') + '\app')
    try {
        $child = Start-Process -FilePath $setup -ArgumentList '/S', "/D=$installed" -Wait -PassThru
        if ($child.ExitCode -ne 0 -or (Get-ItemProperty $appKey).InstallDir -ne $installed) { throw 'Synthetic install failed.' }
        $expected = Join-Path $installed 'bin/webobs-wall.exe'
        if (-not (Test-Path -LiteralPath $expected -PathType Leaf)) { throw 'Synthetic target missing.' }
        $native = & $probe $shortcut $expected | ConvertFrom-Json
        if ($LASTEXITCODE -ne 0) { throw 'Native Unicode link read failed.' }
        if (-not $native.nativeTargetExists -or -not $native.canonicalTargetMatches -or -not $native.argumentsEmpty) {
            throw 'Native Unicode shortcut target or arguments are invalid.'
        }
        $shell = New-Object -ComObject WScript.Shell
        $link = $shell.CreateShortcut($shortcut)
        $native | Add-Member -NotePropertyName scope -NotePropertyValue $scope
        $native | Add-Member -NotePropertyName wscriptTargetExists -NotePropertyValue (Test-Path -LiteralPath $link.TargetPath -PathType Leaf)
        $native | Add-Member -NotePropertyName wscriptTargetMatches -NotePropertyValue ([string]::Equals($link.TargetPath,$expected,[StringComparison]::OrdinalIgnoreCase))
        if ($scope -eq 'ascii') {
            $negativePath = Join-Path $output 'nonempty-arguments.lnk'
            $negativeLink = $shell.CreateShortcut($negativePath)
            $negativeLink.TargetPath = $expected
            $negativeLink.Arguments = '--fixture-extra'
            $negativeLink.Save()
            [Runtime.InteropServices.Marshal]::FinalReleaseComObject($negativeLink) | Out-Null
            $negative = & $probe $negativePath $expected | ConvertFrom-Json
            if ($LASTEXITCODE -ne 0 -or $negative.argumentsEmpty -or -not $negative.canonicalTargetMatches) {
                throw 'Native argument refusal control failed.'
            }
            $wrong = & $probe $shortcut (Join-Path $installed 'bin/other-entry.exe') | ConvertFrom-Json
            if ($LASTEXITCODE -ne 0 -or $wrong.canonicalTargetMatches) { throw 'Native wrong-target refusal control failed.' }
        }
        [Runtime.InteropServices.Marshal]::FinalReleaseComObject($link) | Out-Null
        [Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell) | Out-Null
        $results += $native
    } finally {
        if (Test-Path -LiteralPath (Join-Path $installed 'Uninstall.exe')) {
            $child = Start-Process -FilePath (Join-Path $installed 'Uninstall.exe') -ArgumentList '/S' -Wait -PassThru
            $deadline = [DateTime]::UtcNow.AddSeconds(10)
            while (((Test-Path $appKey) -or (Test-Path $uninstallKey) -or (Test-Path -LiteralPath $shortcut)) -and [DateTime]::UtcNow -lt $deadline) {
                Start-Sleep -Milliseconds 50
            }
        }
        if ((Test-Path $appKey) -or (Test-Path $uninstallKey) -or (Test-Path -LiteralPath $shortcut)) { throw 'Synthetic installer cleanup failed.' }
    }
}
[ordered]@{schema=1;kind='synthetic-native-nsis-shortcut';productQualified=$false;results=$results} |
    ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $output 'shortcut-contracts.json') -Encoding utf8
$results | ConvertTo-Json -Depth 4 -Compress
