[CmdletBinding()]
param([Parameter(Mandatory)][string]$InstallDirectory)
$ErrorActionPreference = 'Stop'
$destination = [IO.Path]::GetFullPath($InstallDirectory)
$backup = "$destination.previous"
$temporary = "$destination.rollback"
foreach ($path in @($destination, $backup)) {
    if (-not (Test-Path -LiteralPath $path -PathType Container)) { throw "Required directory is missing: $path" }
    if ((Get-Item -LiteralPath $path).Attributes.HasFlag([IO.FileAttributes]::ReparsePoint)) {
        throw "Refusing to move reparse point $path"
    }
}
if (Test-Path -LiteralPath $temporary) { throw 'Rollback temporary target already exists' }
Move-Item -LiteralPath $destination -Destination $temporary
try {
    Move-Item -LiteralPath $backup -Destination $destination
    Move-Item -LiteralPath $temporary -Destination $backup
}
catch {
    if (-not (Test-Path -LiteralPath $destination) -and (Test-Path -LiteralPath $temporary)) {
        Move-Item -LiteralPath $temporary -Destination $destination
    }
    throw
}
Write-Host 'Portable client rollback completed; the replaced build remains available for reversal.'
