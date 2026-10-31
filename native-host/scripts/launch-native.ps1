#requires -Version 7.2
[CmdletBinding()]
param(
    [switch]$AllowPrototype,
    [ValidatePattern('^$|^[0-9a-f]{32}$')][string]$SmokeToken = '',
    [string]$ProductConfig = '',
    [switch]$ReuseProfile,
    [ValidateRange(10,300)][int]$TimeoutSeconds = 90,
    [string]$ProcessGatePath = ''
)
$ErrorActionPreference = 'Stop'
if (-not $IsWindows) { throw 'This native development bundle is Windows x64 only.' }
if (-not $AllowPrototype) { throw 'Not a replacement product: authentication/migration/upgrade qualification is incomplete. Use -AllowPrototype only for isolated developer testing.' }
$root = $PSScriptRoot
$manifestPath = Join-Path $root 'webobs-native-prototype.json'
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($manifest.obsCommit -ne 'fb4d98bf88fae5fc85cb11fc57f7c5e309282194' -or $manifest.obsVersion -ne '32.1.2' -or $manifest.defaultProduct -ne $false) { throw 'Prototype bundle identity mismatch.' }
foreach ($relative in @('portable_mode.txt','disable_updater.txt','bin/64bit/obs64.exe','bin/64bit/platforms/qwindows.dll','obs-plugins/64bit/obs-ffmpeg.dll','obs-plugins/64bit/webobs-native-host.dll')) {
    if (-not (Test-Path -LiteralPath (Join-Path $root $relative) -PathType Leaf)) { throw "Incomplete native bundle: $relative" }
}
# The sentinel and fixed working directory are both required by OBS 32.1.2.
# This writable portable profile never imports %APPDATA%\obs-studio or desktop data.
$config = Join-Path $root 'config'
if ($SmokeToken) {
    if (-not $ReuseProfile -and (Test-Path -LiteralPath $config)) { throw 'Smoke mode requires a NEW disposable runtime with no existing profile.' }
    if ($ReuseProfile -and -not (Test-Path -LiteralPath (Join-Path $config 'obs-studio'))) { throw 'ReuseProfile requires an existing disposable portable profile.' }
    $profile = Join-Path $config 'obs-studio'
    if (-not $ReuseProfile) {
        New-Item -ItemType Directory -Path $profile | Out-Null
        # Only this new disposable profile: skip auto-config/default audio input creation.
        [IO.File]::WriteAllText((Join-Path $profile 'user.ini'), "[General]`nFirstRun=true`n[BasicWindow]`nSysTrayEnabled=false`n")
    }
    if ($ProductConfig) {
        if (-not (Test-Path -LiteralPath $ProductConfig -PathType Leaf)) { throw 'Product config file is missing.' }
        if ((Get-Item -LiteralPath $ProductConfig).Length -gt 16384) { throw 'Product config exceeds the 16 KiB limit.' }
        $product = Get-Content -LiteralPath $ProductConfig -Raw | ConvertFrom-Json
        if ($product.schema -ne 1 -or @($product.cameras).Count -ne 5) { throw 'Product config must be schema 1 with five cameras.' }
        $pluginConfig = Join-Path $profile 'plugin_config/webobs-native-host'
        New-Item -ItemType Directory -Path $pluginConfig -Force | Out-Null
        Copy-Item -LiteralPath $ProductConfig -Destination (Join-Path $pluginConfig 'product.json')
    }
}
New-Item -ItemType Directory -Path $config -Force | Out-Null
$probe = Join-Path $config ('.write-probe-' + [Guid]::NewGuid().ToString('N'))
try {
    [IO.File]::WriteAllText($probe, '')
} finally {
    if ([IO.Path]::GetFullPath($probe).StartsWith([IO.Path]::GetFullPath($config) + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) -and (Test-Path -LiteralPath $probe)) {
        Remove-Item -LiteralPath $probe
    }
}
$start = [Diagnostics.ProcessStartInfo]::new()
$start.FileName = Join-Path $root 'bin/64bit/obs64.exe'
$start.WorkingDirectory = Join-Path $root 'bin/64bit'
$start.UseShellExecute = $false
$start.ArgumentList.Add('--portable')
$start.ArgumentList.Add('--disable-updater')
foreach ($name in @('OBS_PLUGINS_PATH','OBS_PLUGINS_DATA_PATH','OBS_CONFIG_PATH','QT_PLUGIN_PATH','QT_QPA_PLATFORM_PLUGIN_PATH','QML2_IMPORT_PATH')) { $start.Environment.Remove($name) | Out-Null }
$start.Environment.Remove('WEBOBS_NATIVE_SMOKE_TOKEN') | Out-Null
if ($SmokeToken) { $start.Environment['WEBOBS_NATIVE_SMOKE_TOKEN'] = $SmokeToken }
$process = [Diagnostics.Process]::Start($start)
$gateObserved = [ordered]@{}
$gateListeners = @()
$gateSamples = 0
$gateClock = [Diagnostics.Stopwatch]::StartNew()
if ($ProcessGatePath -and -not $SmokeToken) { throw 'ProcessGatePath is only supported for the smoke launcher.' }
if ($SmokeToken) {
    $exited = $false
    while (-not $exited) {
        $exited = $process.WaitForExit(500)
        if ($exited) { break }
        if ($ProcessGatePath -and $gateClock.Elapsed.TotalSeconds -ge ($gateSamples * 2) -and $gateSamples -lt 45) {
            try {
                $all = @(Get-CimInstance Win32_Process -Property ProcessId,ParentProcessId,Name,ExecutablePath -ErrorAction Stop)
                $ids = [System.Collections.Generic.HashSet[int]]::new()
                [void]$ids.Add([int]$process.Id)
                $changed = $true
                while ($changed) {
                    $changed = $false
                    foreach ($item in $all) {
                        if ($ids.Contains([int]$item.ParentProcessId) -and -not $ids.Contains([int]$item.ProcessId)) {
                            [void]$ids.Add([int]$item.ProcessId)
                            $changed = $true
                        }
                    }
                }
                foreach ($item in $all) {
                    if ($item.ProcessId -ne $process.Id -and $ids.Contains([int]$item.ProcessId)) {
                        $key = [string]$item.Name
                        if (-not $gateObserved.Contains($key)) { $gateObserved[$key] = [string]$item.ExecutablePath }
                    }
                }
                if ($gateSamples -eq 1) {
                    try {
                        $gateListeners = @(Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object { $ids.Contains([int]$_.OwningProcess) } | ForEach-Object {
                            @{ port = [int]$_.LocalPort; name = (Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue).ProcessName }
                        })
                    } catch { $gateListeners = @() }
                }
                $gateSamples++
            } catch { }
        }
        if ($gateClock.Elapsed.TotalSeconds -gt $TimeoutSeconds) { break }
    }
    if (-not $exited) {
    $titles = @()
    try {
        Add-Type -TypeDefinition @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public static class WebObsTimeoutWindows {
    public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc callback, IntPtr lParam);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int max);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
    public static List<string> Titles(uint target) {
        var titles = new List<string>();
        EnumWindows((handle, parameter) => {
            uint owner;
            GetWindowThreadProcessId(handle, out owner);
            if (owner == target && IsWindowVisible(handle)) {
                var buffer = new StringBuilder(256);
                GetWindowText(handle, buffer, 256);
                if (buffer.Length > 0) { titles.Add(buffer.ToString()); }
            }
            return true;
        }, IntPtr.Zero);
        return titles;
    }
}
"@
        $titles = [WebObsTimeoutWindows]::Titles([uint32]$process.Id) | Select-Object -First 5
    } catch { }
    # Only the process we just created in the disposable test bundle.
    $process.Kill($true)
    $process.WaitForExit()
    $bounded = @($titles | ForEach-Object { if ($_.Length -gt 120) { $_.Substring(0, 120) } else { $_ } }) -join ' | '
    throw "Native Qt smoke timed out after $TimeoutSeconds seconds; visible windows: $bounded"
    }
} 
$process.WaitForExit()
if ($ProcessGatePath) {
    $orphans = @()
    for ($attempt = 0; $attempt -lt 3; $attempt++) {
        $orphans = @(Get-CimInstance Win32_Process -Property ProcessId,Name,ExecutablePath -ErrorAction SilentlyContinue | Where-Object {
            $_.ExecutablePath -and ([string]$_.ExecutablePath).StartsWith($root, [StringComparison]::OrdinalIgnoreCase) -and
            $_.Name -notin @('pwsh.exe', 'powershell.exe')
        } | ForEach-Object { @{ name = [string]$_.Name; path = [string]$_.ExecutablePath } })
        if ($orphans.Count -eq 0) { break }
        Start-Sleep -Milliseconds 400
    }
    $gate = @{
        schema = 1
        rootPid = [int]$process.Id
        exitCode = [int]$process.ExitCode
        samples = $gateSamples
        durationMs = [int]$gateClock.Elapsed.TotalMilliseconds
        observed = @($gateObserved.Keys | ForEach-Object { @{ name = [string]$_; path = [string]$gateObserved[$_] } })
        listeners = @($gateListeners)
        orphans = @($orphans)
    }
    $gateDir = Split-Path -Parent $ProcessGatePath
    if ($gateDir -and -not (Test-Path -LiteralPath $gateDir)) { New-Item -ItemType Directory -Path $gateDir -Force | Out-Null }
    $gate | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $ProcessGatePath -Encoding utf8
}
exit $process.ExitCode
