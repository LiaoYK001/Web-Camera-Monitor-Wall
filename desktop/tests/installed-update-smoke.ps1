#requires -Version 7.2
[CmdletBinding()]
param([Parameter(Mandatory)][string]$PreviousVersion,[Parameter(Mandatory)][string]$Version)
$ErrorActionPreference='Stop'
$repo=(Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
foreach($value in @($Version,$PreviousVersion)){if($value -notmatch '^\d+\.\d+\.\d+$'){throw 'Stable versions required'}}
function ProductEntries {
    @(Get-ChildItem 'HKCU:/Software/Microsoft/Windows/CurrentVersion/Uninstall','HKLM:/Software/Microsoft/Windows/CurrentVersion/Uninstall' -ErrorAction SilentlyContinue | Get-ItemProperty -ErrorAction SilentlyContinue | Where-Object {$_.DisplayName -match '^WebOBS($|\s)'})
}
if((ProductEntries).Count){throw 'Existing WebOBS installation must remain untouched'}
$shortcuts=@((Join-Path ([Environment]::GetFolderPath('Desktop')) 'WebOBS.lnk'),(Join-Path ([Environment]::GetFolderPath('Programs')) 'WebOBS.lnk'))
if(@($shortcuts|Where-Object {Test-Path -LiteralPath $_}).Count){throw 'Existing shortcuts must remain untouched'}
$build=(Join-Path $repo 'build')
$root=Join-Path $build ('unsigned-upgrade-check-'+[Guid]::NewGuid().ToString('N'))
$installation=Join-Path $root '客户端 安装'
New-Item -ItemType Directory -Path $root -Force|Out-Null
$old=Join-Path $repo "desktop/out/$PreviousVersion/WebOBS-$PreviousVersion-windows-x64-UNSIGNED.exe"
$savedProfile=$env:LOCALAPPDATA
$electronPath=(& node -e "process.stdout.write(require(require('node:path').join(process.argv[1],'desktop/node_modules/electron')))" $repo).Trim()
if($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $electronPath -PathType Leaf)){throw 'Pinned Electron runtime unavailable'}
$installed=$false
try {
    $env:LOCALAPPDATA=Join-Path $root 'profile'
    $first=Start-Process -FilePath $old -ArgumentList @('/S',"/D=$installation") -WindowStyle Hidden -Wait -PassThru
    if($first.ExitCode -ne 0){throw 'Initial isolated NSIS installation failed'}
    $installed=$true
    $env:WEBOBS_UPGRADE_SMOKE_ROOT=$root;$env:WEBOBS_UPGRADE_SMOKE_INSTALL=$installation
    $env:WEBOBS_UPGRADE_SMOKE_ARTIFACTS=Join-Path $repo "desktop/out/$Version"
    $env:WEBOBS_UPGRADE_SMOKE_FROM=$PreviousVersion;$env:WEBOBS_UPGRADE_SMOKE_VERSION=$Version
    & $electronPath (Join-Path $PSScriptRoot 'installed-update-smoke.cjs')
    if($LASTEXITCODE -ne 0){throw 'Actual unsigned update smoke failed'}
} finally {
    if($installed -and (Test-Path -LiteralPath (Join-Path $installation 'Uninstall WebOBS.exe'))){
        $removed=Start-Process -FilePath (Join-Path $installation 'Uninstall WebOBS.exe') -ArgumentList '/S' -WindowStyle Hidden -Wait -PassThru
        if($removed.ExitCode -ne 0){Write-Warning 'Isolated test uninstall failed; retained its test directory'}
    }
    $env:LOCALAPPDATA=$savedProfile
    Remove-Item Env:WEBOBS_UPGRADE_SMOKE_ROOT,Env:WEBOBS_UPGRADE_SMOKE_INSTALL,Env:WEBOBS_UPGRADE_SMOKE_ARTIFACTS,Env:WEBOBS_UPGRADE_SMOKE_FROM,Env:WEBOBS_UPGRADE_SMOKE_VERSION -ErrorAction SilentlyContinue
    if(-not (ProductEntries).Count -and $root.StartsWith($build+[IO.Path]::DirectorySeparatorChar+'unsigned-upgrade-check-',[StringComparison]::OrdinalIgnoreCase) -and -not (Get-Item -LiteralPath $root).Attributes.HasFlag([IO.FileAttributes]::ReparsePoint)){Remove-Item -LiteralPath $root -Recurse -Force}
}
