#requires -Version 7.2
# Test-only UI Automation for an explicitly supplied disposable product process.
# Credentials enter over stdin and are never echoed or placed on a command line.
param([Parameter(Mandatory=$true)][int]$FrontendPid,
      [Parameter(Mandatory=$true)][string]$RootHwnd)
$ErrorActionPreference = 'Stop'
$stage = 'initialize'
$code = 'assemblies'
try {
    Add-Type -AssemblyName UIAutomationClient,UIAutomationTypes,System.Windows.Forms
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class ProductTestWindow {
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr window);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr window,int command);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr window,out uint pid);
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr window,IntPtr after,int x,int y,int width,int height,uint flags);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr window,uint message,IntPtr wParam,IntPtr lParam);
}
'@
    $operation = [Console]::In.ReadToEnd() | ConvertFrom-Json
    $code = 'product-window'
    if ($RootHwnd -notmatch '^[0-9a-f]{1,16}$') { throw 'Invalid owned root handle.' }
    $window = [System.Windows.Automation.AutomationElement]::FromHandle(
        [IntPtr]::new([Convert]::ToInt64($RootHwnd,16)))
    if ($null -eq $window -or $window.Current.ProcessId -ne $FrontendPid) {
        throw 'Product window process identity mismatch.'
    }
    $null = [ProductTestWindow]::ShowWindow([IntPtr]$window.Current.NativeWindowHandle, 9)
    $null = [ProductTestWindow]::SetForegroundWindow([IntPtr]$window.Current.NativeWindowHandle)
    function Find-Control([string]$Identity) {
        $script:code = 'find-' + $Identity
        $found = $window.FindFirst([System.Windows.Automation.TreeScope]::Descendants,
            [System.Windows.Automation.PropertyCondition]::new(
                [System.Windows.Automation.AutomationElement]::AutomationIdProperty, $Identity))
        $kind = $null
        $name = $null
        if ($null -eq $found) {
            $kind = [System.Windows.Automation.ControlType]::Button
            $name = switch ($Identity) {
                'webobsUsername' { $kind = [System.Windows.Automation.ControlType]::Edit; '账号' }
                'webobsPassword' { $kind = [System.Windows.Automation.ControlType]::Edit; '密码' }
                'webobsLogin' { '登录' }
                'webobsCreateAccount' { '创建首个管理员账号' }
                'webobsWatch' { '开始原生监看' }
                'webobsSaveLayout' { '保存布局' }
                'webobsLogout' { '退出账号' }
                'webobsRefreshCatalog' { '刷新设备目录' }
                'webobsWatchScene' { '监看所选 Studio 场景' }
                'webobsCameraCount' { $kind = [System.Windows.Automation.ControlType]::Spinner; '监看路数' }
                'webobsStudioScene' { $kind = [System.Windows.Automation.ControlType]::ComboBox; '已保存的 Studio 场景' }
                'webobsFixedProjector1' { '固定场景投影 1' }
                'webobsFixedProjector2' { '固定场景投影 2' }
                'webobsCloseProjectors' { '关闭固定投影' }
                'webobsProgramProjector' { '打开 Program 投影' }
                'webobsHostStats' { 'OBS 宿主统计' }
                'webobsManageDevices' { '设备与来源管理' }
                'webobsManageAudio' { '音频与监听' }
                'webobsManageAnalytics' { '分析策略' }
                'webobsManageEvents' { '事件与通知' }
                'webobsManageArchive' { '录像与回放' }
                'webobsManageStorage' { '录像与存储' }
                'webobsManageGo2rtc' { '网站来源' }
                'webobsManageAdmin' { '账号与权限' }
                'webobsManageAccount' { '我的账号' }
                'webobsManageSettings' { '系统设置' }
                'webobsVideoHealth' { $kind = [System.Windows.Automation.ControlType]::Text; '' }
                default {
                    if ($Identity -match '^webobsCameraSlot([1-9][0-9]?)$' -and [int]$Matches[1] -le 64) {
                        $kind = [System.Windows.Automation.ControlType]::ComboBox
                        "画面 $($Matches[1])"
                    } else {
                        # Unknown identities still get the AutomationId suffix
                        # fallback below; do not fail before that query.
                        $kind = $null
                        $null
                    }
                }
            }
        }
        if ($null -eq $found -and $name) {
            # Prefer a direct property query over enumerating a fully loaded
            # OBS window. This is both faster and less likely to race a display
            # teardown while a Program projector is closing.
            $nameCondition = [System.Windows.Automation.PropertyCondition]::new(
                [System.Windows.Automation.AutomationElement]::NameProperty, $name)
            $typeCondition = [System.Windows.Automation.PropertyCondition]::new(
                [System.Windows.Automation.AutomationElement]::ControlTypeProperty, $kind)
            $nameAndType = [System.Windows.Automation.AndCondition]::new(
                [System.Windows.Automation.Condition[]]@($nameCondition, $typeCondition))
            $found = $window.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $nameAndType)
        }
        if ($null -eq $found) {
            # Some Qt Windows providers qualify AutomationId with the QObject
            # ancestry. Search only this exact process-owned product root.
            $descendants = $window.FindAll([System.Windows.Automation.TreeScope]::Descendants,
                [System.Windows.Automation.Condition]::TrueCondition)
            $controlCandidates = @($descendants | Where-Object {
                ([string]$_.Current.AutomationId).EndsWith('.' + $Identity, [StringComparison]::Ordinal)
            })
            if ($controlCandidates.Count -eq 1) { $found = $controlCandidates[0] }
        }
        if ($null -eq $found) {
            $controlCandidates = @($descendants | Where-Object {
                ($_.Current.Name -eq $name -or ($Identity -eq 'webobsVideoHealth' -and
                    $_.Current.Name -match '^视频输入：')) -and $_.Current.ControlType -eq $kind
            })
            if ($controlCandidates.Count -eq 1) { $found = $controlCandidates[0] }
        }
        if ($null -eq $found) { throw 'Product control missing.' }
        return $found
    }
    function Invoke-Control([string]$Identity) {
        $control = Find-Control $Identity
        $script:code = 'invoke-' + $Identity
        if (-not $control.Current.IsEnabled) { throw 'Product control disabled.' }
        $control.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
    }
    function Set-Control([string]$Identity, [string]$Value) {
        $control = Find-Control $Identity
        $script:code = 'set-' + $Identity
        if (-not $control.Current.IsEnabled) { throw 'Product text control disabled.' }
        $pattern = $null
        if ($Identity -eq 'webobsCameraCount' -and $control.TryGetCurrentPattern(
            [System.Windows.Automation.RangeValuePattern]::Pattern, [ref]$pattern)) {
            $pattern.SetValue([double]$Value)
            return
        }
        $valueSet = $false
        if ($control.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern, [ref]$pattern)) {
            try { $pattern.SetValue($Value); $valueSet = $true } catch { }
        }
        if (-not $valueSet) {
            # Fixture credentials deliberately contain only SendKeys-safe ASCII.
            if ($Value -notmatch '^[A-Za-z0-9_-]{1,128}$') { throw 'Unsafe fixture text.' }
            $control.SetFocus()
            [System.Windows.Forms.SendKeys]::SendWait('^a')
            [System.Windows.Forms.SendKeys]::SendWait($Value)
        }
    }
    $stage = [string]$operation.action
    switch ($operation.action) {
        'inspect' {
            $null = Find-Control 'webobsUsername'
            $null = Find-Control 'webobsPassword'
            $null = Find-Control 'webobsLogin'
            if ((Find-Control 'webobsHostStats').Current.IsEnabled) { throw 'Host stats enabled before login.' }
        }
        'management-entries' {
            foreach ($identity in @('webobsManageAudio', 'webobsManageAnalytics', 'webobsManageEvents',
                    'webobsManageArchive', 'webobsManageStorage', 'webobsManageGo2rtc', 'webobsManageAdmin',
                    'webobsManageAccount', 'webobsManageSettings')) {
                $control = Find-Control $identity
                if (-not $control.Current.IsEnabled) { throw "Management entry $identity is disabled." }
            }
        }
        'login' {
            Set-Control 'webobsUsername' $operation.username
            Set-Control 'webobsPassword' $operation.password
            Invoke-Control 'webobsLogin'
        }
        'create' {
            Set-Control 'webobsUsername' $operation.username
            Set-Control 'webobsPassword' $operation.password
            Invoke-Control 'webobsCreateAccount'
        }
        'resize' {
            $count = [int]$operation.count
            if ($count -lt 1 -or $count -gt 64) { throw 'Invalid bounded fixture count.' }
            Set-Control 'webobsCameraCount' ([string]$count)
            [System.Windows.Forms.SendKeys]::SendWait('{TAB}')
        }
        'choose' {
            $count = @($operation.indices).Count
            if ($count -lt 1 -or $count -gt 64) { throw 'Invalid bounded fixture count.' }
            Set-Control 'webobsCameraCount' ([string]$count)
            [System.Windows.Forms.SendKeys]::SendWait('{TAB}')
            for ($index=0; $index -lt $count; ++$index) {
                $choice = [int]$operation.indices[$index]
                if ($choice -lt 1 -or $choice -gt 5) { throw 'Invalid fixture index.' }
                $control = Find-Control "webobsCameraSlot$($index+1)"
                $code = "expand-camera-$($index+1)"
                # Qt's noneditable combo accessibility action opens its popup;
                # SetFocus alone need not focus that combo. Commit the highlighted
                # popup entry with Enter, then read the actual combo value back.
                $expand = $control.GetCurrentPattern([System.Windows.Automation.ExpandCollapsePattern]::Pattern)
                $expand.Expand()
                $code = "focus-camera-$($index+1)"
                [uint32]$foregroundPid = 0
                $null = [ProductTestWindow]::GetWindowThreadProcessId(
                    [ProductTestWindow]::GetForegroundWindow(), [ref]$foregroundPid)
                if ($foregroundPid -ne $FrontendPid) { throw 'Fixture product does not own keyboard input.' }
                $code = "choose-camera-$($index+1)"
                [System.Windows.Forms.SendKeys]::SendWait('{HOME}' + ('{DOWN}' * $choice) + '{ENTER}')
                $value = $control.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
                $deadline = [DateTime]::UtcNow.AddSeconds(2)
                while ($value.Current.Value -ne "Fixture $choice / Main" -and [DateTime]::UtcNow -lt $deadline) {
                    Start-Sleep -Milliseconds 25
                }
                $code = "verify-camera-$($index+1)"
                if ($value.Current.Value -ne "Fixture $choice / Main") { throw 'Fixture camera choice was not committed.' }
            }
            Invoke-Control 'webobsWatch'
        }
        'save' { Invoke-Control 'webobsSaveLayout' }
        'stats' { Invoke-Control 'webobsHostStats' }
        'stats-close' { $window.GetCurrentPattern([System.Windows.Automation.WindowPattern]::Pattern).Close() }
        'video-progress' {
            if ([int]$operation.sources -lt 1 -or [int]$operation.sources -gt 5) { throw 'Invalid synthetic source count.' }
            $stalled = [int]$operation.stalled
            if ($stalled -notin @(0,1) -or $stalled -gt [int]$operation.sources) { throw 'Invalid synthetic stall count.' }
            $health = Find-Control 'webobsVideoHealth'
            $code = 'verify-video-input-progress'
            $expected = '视频输入：' + [int]$operation.sources + ' 路，已收帧 ' +
                [int]$operation.sources + '，近期推进 ' + ([int]$operation.sources - $stalled) + '，停滞 ' + $stalled + '，状态未知 0。'
            if ($health.Current.Name -ne $expected) { throw 'Video input callbacks have not progressed.' }
        }
        'projector' {
            if ([int]$operation.slot -notin @(1,2)) { throw 'Invalid fixed projector slot.' }
            Invoke-Control "webobsFixedProjector$([int]$operation.slot)"
        }
        'projector-close' { Invoke-Control 'webobsCloseProjectors' }
        'program-projector' { Invoke-Control 'webobsProgramProjector' }
        'projector-window-close' {
            # OBSProjector does not expose a reliable UIA WindowPattern.Close
            # action on Windows. Exercise the same WM_CLOSE path as the title bar.
            if (-not [ProductTestWindow]::PostMessage([IntPtr]$window.Current.NativeWindowHandle,
                0x0010, [IntPtr]::Zero, [IntPtr]::Zero)) {
                throw 'Owned projector close request failed.'
            }
        }
        'projector-place' {
            if ([int]$operation.slot -notin @(1,2)) { throw 'Invalid projector fixture slot.' }
            if (-not [ProductTestWindow]::SetWindowPos([IntPtr]$window.Current.NativeWindowHandle,
                [IntPtr]::Zero,120,120,800,500,20)) { throw 'Owned projector placement failed.' }
        }
        'projector-fullscreen' {
            if ([ProductTestWindow]::GetForegroundWindow() -ne [IntPtr]$window.Current.NativeWindowHandle) {
                throw 'Owned projector is not the foreground root.'
            }
            [System.Windows.Forms.SendKeys]::SendWait('{F11}')
        }
        'scene' {
            $choice = [int]$operation.index
            if ($choice -lt 1 -or $choice -gt 64 -or
                $operation.fixtureName -notin @('Fixture Studio five', 'Fixture Studio five updated')) {
                throw 'Invalid synthetic Studio selection.'
            }
            $control = Find-Control 'webobsStudioScene'
            $code = 'expand-studio-scene'
            $control.GetCurrentPattern([System.Windows.Automation.ExpandCollapsePattern]::Pattern).Expand()
            [uint32]$foregroundPid = 0
            $null = [ProductTestWindow]::GetWindowThreadProcessId(
                [ProductTestWindow]::GetForegroundWindow(), [ref]$foregroundPid)
            if ($foregroundPid -ne $FrontendPid) { throw 'Fixture product does not own keyboard input.' }
            [System.Windows.Forms.SendKeys]::SendWait('{HOME}' + ('{DOWN}' * $choice) + '{ENTER}')
            $value = $control.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
            $deadline = [DateTime]::UtcNow.AddSeconds(2)
            while ($value.Current.Value -ne $operation.fixtureName -and [DateTime]::UtcNow -lt $deadline) {
                Start-Sleep -Milliseconds 25
            }
            $code = 'verify-studio-scene'
            if ($value.Current.Value -ne $operation.fixtureName) { throw 'Studio fixture selection was not committed.' }
            Invoke-Control 'webobsWatchScene'
        }
        'logout' { Invoke-Control 'webobsLogout' }
        'refresh' { Invoke-Control 'webobsRefreshCatalog' }
        'close' { $window.GetCurrentPattern([System.Windows.Automation.WindowPattern]::Pattern).Close() }
        default { throw 'Unknown product test action.' }
    }
    [Console]::Out.WriteLine((@{passed=$true;stage=$stage} | ConvertTo-Json -Compress))
} catch {
    # Fixed stage only: UIA exceptions can contain private paths or input values.
    [Console]::Out.WriteLine((@{passed=$false;stage=$stage;code=$code;exceptionType=$_.Exception.GetType().FullName} | ConvertTo-Json -Compress))
    exit 1
}
