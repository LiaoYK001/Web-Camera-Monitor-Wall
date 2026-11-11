#requires -Version 7.2
# Test-only UI Automation for an explicitly supplied disposable product process.
# Credentials enter over stdin and are never echoed or placed on a command line.
param([Parameter(Mandatory=$true)][int]$FrontendPid)
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
}
'@
    $operation = [Console]::In.ReadToEnd() | ConvertFrom-Json
    $condition = [System.Windows.Automation.PropertyCondition]::new(
        [System.Windows.Automation.AutomationElement]::ProcessIdProperty, $FrontendPid)
    $windows = [System.Windows.Automation.AutomationElement]::RootElement.FindAll(
        [System.Windows.Automation.TreeScope]::Children, $condition)
    $window = @($windows | Where-Object { $_.Current.AutomationId -eq 'webobsProductWindow' })
    $code = 'product-window'
    if ($window.Count -ne 1) { throw 'Expected exactly one owned product window.' }
    $window = $window[0]
    $null = [ProductTestWindow]::ShowWindow([IntPtr]$window.Current.NativeWindowHandle, 9)
    $null = [ProductTestWindow]::SetForegroundWindow([IntPtr]$window.Current.NativeWindowHandle)
    function Find-Control([string]$Identity) {
        $script:code = 'find-' + $Identity
        $found = $window.FindFirst([System.Windows.Automation.TreeScope]::Descendants,
            [System.Windows.Automation.PropertyCondition]::new(
                [System.Windows.Automation.AutomationElement]::AutomationIdProperty, $Identity))
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
        $pattern = $null
        if ($control.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern, [ref]$pattern)) {
            $pattern.SetValue($Value)
        } else {
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
        'choose' {
            if (@($operation.indices).Count -ne 5) { throw 'Five fixture choices required.' }
            for ($index=0; $index -lt 5; ++$index) {
                $choice = [int]$operation.indices[$index]
                if ($choice -lt 1 -or $choice -gt 5) { throw 'Invalid fixture index.' }
                $control = Find-Control "webobsCameraSlot$($index+1)"
                $control.SetFocus()
                [System.Windows.Forms.SendKeys]::SendWait('{HOME}')
                for ($step=0; $step -lt $choice; ++$step) {
                    [System.Windows.Forms.SendKeys]::SendWait('{DOWN}')
                }
                [System.Windows.Forms.SendKeys]::SendWait('{ESC}')
            }
            Invoke-Control 'webobsWatch'
        }
        'save' { Invoke-Control 'webobsSaveLayout' }
        'logout' { Invoke-Control 'webobsLogout' }
        'refresh' { Invoke-Control 'webobsRefreshCatalog' }
        'close' { $window.GetCurrentPattern([System.Windows.Automation.WindowPattern]::Pattern).Close() }
        default { throw 'Unknown product test action.' }
    }
    [Console]::Out.WriteLine((@{passed=$true;stage=$stage} | ConvertTo-Json -Compress))
} catch {
    # Fixed stage only: UIA exceptions can contain private paths or input values.
    [Console]::Out.WriteLine((@{passed=$false;stage=$stage;code=$code} | ConvertTo-Json -Compress))
    exit 1
}
