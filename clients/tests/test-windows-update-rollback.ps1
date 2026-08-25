$ErrorActionPreference = 'Stop'
$TestRoot = Join-Path ([IO.Path]::GetTempPath()) ("webobs-rollback-" + [Guid]::NewGuid().ToString('N'))
$Destination = Join-Path $TestRoot 'webobs-native'
$Backup = "$Destination.previous"
try {
    New-Item -ItemType Directory -Path $Destination, $Backup | Out-Null
    Set-Content -LiteralPath (Join-Path $Destination 'version.txt') -Value 'current-build' -NoNewline
    Set-Content -LiteralPath (Join-Path $Backup 'version.txt') -Value 'previous-build' -NoNewline
    & (Join-Path $PSScriptRoot '..\packaging\windows\Restore-PortableRollback.ps1') `
        -InstallDirectory $Destination | Out-Null
    if ((Get-Content -Raw -LiteralPath (Join-Path $Destination 'version.txt')) -ne 'previous-build' -or
        (Get-Content -Raw -LiteralPath (Join-Path $Backup 'version.txt')) -ne 'current-build') {
        throw 'First portable rollback did not atomically exchange versions'
    }
    & (Join-Path $PSScriptRoot '..\packaging\windows\Restore-PortableRollback.ps1') `
        -InstallDirectory $Destination | Out-Null
    if ((Get-Content -Raw -LiteralPath (Join-Path $Destination 'version.txt')) -ne 'current-build' -or
        (Get-Content -Raw -LiteralPath (Join-Path $Backup 'version.txt')) -ne 'previous-build') {
        throw 'Second portable rollback did not preserve reversibility'
    }
}
finally {
    if (Test-Path -LiteralPath $TestRoot) {
        Remove-Item -LiteralPath $TestRoot -Recurse -Force
    }
}
