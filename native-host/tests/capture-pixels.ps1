#requires -Version 7.2
# TEST ONLY. Exactly the synthetic-owned Qt child/projector clients, not desktop
# screenshots or source textures. No title/geometry-based window selection.
[CmdletBinding(DefaultParameterSetName='Capture')]
param(
    [Parameter(Mandatory=$true,ParameterSetName='Capture')][int]$ExpectedProcessId,
    [Parameter(Mandatory=$true,ParameterSetName='Capture')][string]$ExpectedExecutable,
    [Parameter(Mandatory=$true,ParameterSetName='Capture')][string]$ExpectedCreationTime,
    [Parameter(Mandatory=$true,ParameterSetName='Capture')][string]$StateFile,
    [Parameter(Mandatory=$true,ParameterSetName='Capture')][string]$OutputDirectory,
    # Compile only: never reads state, opens a process or captures pixels. This
    # tests the real inline C# on Windows without weakening any capture guard.
    [Parameter(Mandatory=$true,ParameterSetName='CompileOnly')][switch]$CompileOnly
)
$ErrorActionPreference = 'Stop'
$stage = 'input'; $code = 'input-validation'; $compilerErrors = @()
$results = @()
function Get-SafeDiagnostic($record, [bool]$native = $false) {
    # Never emit Exception.Message, ErrorRecord text, paths, token, PID or HWND.
    # Only our fixed stage/code fields and numeric progress/compiler codes leave
    # this private subprocess. Unknown CLR failures retain their operation code.
    $diagnostic = @{stage=$stage; code=$code; sampleIndex=-1; completedSamples=0; nativeError=0; compilerCodes=@()}
    if ($native) {
        $diagnostic.stage = [ObsPixelCapture]::Stage
        $diagnostic.code = [ObsPixelCapture]::Code
        $diagnostic.sampleIndex = [ObsPixelCapture]::SampleIndex
        $diagnostic.completedSamples = [ObsPixelCapture]::CompletedSamples
        $diagnostic.nativeError = [ObsPixelCapture]::NativeError
    }
    if ($stage -eq 'compile') {
        $text = (@($compilerErrors) + @($record) | Out-String)
        $diagnostic.compilerCodes = @([regex]::Matches($text,'\bCS[0-9]{4}\b') | ForEach-Object { $_.Value } | Sort-Object -Unique | Select-Object -First 8)
    }
    return $diagnostic
}
function Write-Report($report) {
    [Console]::Out.WriteLine(($report | ConvertTo-Json -Depth 8 -Compress))
}
try {
    if (-not $IsWindows) { $code='windows-required'; throw 'Windows required.' }
    if (-not $CompileOnly) {
        if (-not (Test-Path -LiteralPath $OutputDirectory -PathType Container)) { $code='output-directory'; throw 'Private directory required.' }
        if ((Get-Item -LiteralPath $StateFile).Length -gt 65536) { $code='state-size'; throw 'Oversized state.' }
        $state = Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json
        if ($state.schema -ne 1 -or $state.scope -ne 'synthetic-test-only' -or $state.pid -ne "$ExpectedProcessId" -or @($state.windows).Count -ne 2) { $code='state-identity'; throw 'Unexpected state.' }
        $roles = @($state.windows | ForEach-Object { $_.role })
        if (@($roles | Sort-Object -Unique).Count -ne 2 -or $roles -notcontains 'main-preview' -or $roles -notcontains 'program-projector') { $code='state-roles'; throw 'Unexpected roles.' }
    }
    $stage='assembly-load'; $code='reference-assemblies'
    Add-Type -AssemblyName System.Drawing
    Add-Type -AssemblyName System.Windows.Forms
    # PS 6+ -ReferencedAssemblies REPLACES default .NET references. The previous
    # Drawing/Forms-only list omitted System.Diagnostics.Process used below and
    # can fail before the first BMP. Use PowerShell's trusted reference pack,
    # plus the actual Windows Drawing/Forms assemblies (not only forwarders).
    # Do not resolve references from the disposable profile or current directory.
    $referenceDirectory = Join-Path $PSHOME 'ref'
    if (-not (Test-Path -LiteralPath $referenceDirectory -PathType Container)) { throw 'Trusted reference pack missing.' }
    $references = @((Get-ChildItem -LiteralPath $referenceDirectory -Filter '*.dll' -File).FullName)
    $references += @([System.Drawing.Bitmap].Assembly.Location, [System.Windows.Forms.Screen].Assembly.Location)
    $references = @($references | Group-Object { [IO.Path]::GetFileName($_) } | ForEach-Object { $_.Group[0] })
    $stage='compile'; $code='csharp-compilation'
    Add-Type -ReferencedAssemblies $references -ErrorVariable compilerErrors -TypeDefinition @'
using System;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Imaging;
using System.Globalization;
using System.IO;
using System.Runtime.InteropServices;
using System.Windows.Forms;
public static class ObsPixelCapture {
    [StructLayout(LayoutKind.Sequential)] public struct Rect { public int left, top, right, bottom; }
    [StructLayout(LayoutKind.Sequential)] public struct Point { public int x, y; public Point(int a,int b) { x=a; y=b; } }
    [DllImport("user32.dll")] static extern bool IsWindow(IntPtr hwnd);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr hwnd,out uint pid);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr hwnd);
    [DllImport("user32.dll")] static extern bool IsChild(IntPtr parent,IntPtr child);
    [DllImport("user32.dll",SetLastError=true)] static extern bool GetClientRect(IntPtr hwnd,out Rect rect);
    [DllImport("user32.dll",SetLastError=true)] static extern bool ClientToScreen(IntPtr hwnd,ref Point point);
    [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr hwnd,int command);
    [DllImport("user32.dll",SetLastError=true)] static extern bool SetWindowPos(IntPtr hwnd,IntPtr after,int x,int y,int w,int h,uint flags);
    [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr hwnd);
    [DllImport("user32.dll",SetLastError=true)] static extern IntPtr SetThreadDpiAwarenessContext(IntPtr context);
    [DllImport("user32.dll")] static extern IntPtr WindowFromPoint(Point point);
    [DllImport("user32.dll")] static extern IntPtr GetAncestor(IntPtr hwnd,uint flags);
    [DllImport("dwmapi.dll")] static extern int DwmFlush();
    public static long[] SampleElapsedMs;
    public static string Stage, Code;
    public static int SampleIndex, CompletedSamples, NativeError;
    static void Mark(string stage,string code) { Stage=stage; Code=code; NativeError=0; }
    static Exception Failure(string stage,string code,int nativeError=0) {
        Mark(stage,code); NativeError=nativeError;
        return new InvalidOperationException("Synthetic owned-client capture failed.");
    }
    static IntPtr Parse(string hex) { return new IntPtr(checked((long)UInt64.Parse(hex,NumberStyles.HexNumber,CultureInfo.InvariantCulture))); }
    static void Identity(uint pid,string executable,long creation,IntPtr hwnd,IntPtr root) {
        Mark("identity","process-inspection");
        using (var process=Process.GetProcessById((int)pid)) {
            if (process.HasExited || !String.Equals(Path.GetFullPath(process.MainModule.FileName),executable,StringComparison.OrdinalIgnoreCase) || process.StartTime.ToUniversalTime().ToFileTimeUtc()!=creation)
                throw Failure("identity","process-identity");
        }
        uint actual,actualRoot;
        if (!IsWindow(hwnd) || !IsWindow(root) || GetWindowThreadProcessId(hwnd,out actual)==0 || GetWindowThreadProcessId(root,out actualRoot)==0 || actual!=pid || actualRoot!=pid || GetAncestor(hwnd,2)!=root || GetAncestor(root,2)!=root)
            throw Failure("identity","window-identity");
    }
    public static void Capture(uint pid,string executable,string creationText,string handle,string rootHandle,string role,string directory) {
        Mark("input","native-arguments"); SampleIndex=-1; CompletedSamples=0;
        var hwnd=Parse(handle); var root=Parse(rootHandle);
        long creation=Int64.Parse(creationText,CultureInfo.InvariantCulture);
        var clock=Stopwatch.StartNew(); SampleElapsedMs=new long[8];
        Mark("dpi","dpi-awareness");
        var previous=SetThreadDpiAwarenessContext(new IntPtr(-4));
        if (previous==IntPtr.Zero) throw Failure("dpi","dpi-awareness",Marshal.GetLastWin32Error());
        bool topmost=false;
        try {
            Identity(pid,executable,creation,hwnd,root);
            Mark("expose","interactive-screen");
            var screen=Screen.PrimaryScreen.Bounds;
            ShowWindow(root,9);
            if (role=="main-preview") {
                ShowWindow(root,3); // Maximize the main UI, not its child widget.
                if (!SetWindowPos(root,new IntPtr(-1),0,0,0,0,0x0001|0x0002|0x0040)) throw Failure("expose","main-preview-expose",Marshal.GetLastWin32Error());
            } else {
                if (hwnd!=root || !SetWindowPos(root,new IntPtr(-1),screen.Left+20,screen.Top+20,Math.Min(1100,screen.Width-40),Math.Min(740,screen.Height-40),0x0040)) throw Failure("expose","program-projector-expose",Marshal.GetLastWin32Error());
            }
            topmost=true; SetForegroundWindow(root); System.Threading.Thread.Sleep(400);
            for (int i=0;i<8;i++) {
                SampleIndex=i;
                Identity(pid,executable,creation,hwnd,root);
                if (!IsWindowVisible(hwnd) || !IsWindowVisible(root)) throw Failure("visibility","client-hidden");
                Mark("geometry","client-geometry");
                Rect rect; var origin=new Point(0,0);
                if (!GetClientRect(hwnd,out rect) || !ClientToScreen(hwnd,ref origin)) throw Failure("geometry","client-geometry",Marshal.GetLastWin32Error());
                int width=rect.right-rect.left,height=rect.bottom-rect.top;
                if (width<320 || height<180 || width>8192 || height>8192 || !screen.Contains(new Rectangle(origin.x,origin.y,width,height))) throw Failure("geometry","client-bounds");
                for (int y=1;y<=5;y++) for (int x=1;x<=5;x++) {
                    var hit=WindowFromPoint(new Point(origin.x+width*x/6,origin.y+height*y/6));
                    if (GetAncestor(hit,2)!=root || (hit!=hwnd && !IsChild(hwnd,hit))) throw Failure("occlusion","client-obscured");
                }
                Mark("dwm","composition-sync");
                int dwm=DwmFlush(); if (dwm!=0) throw Failure("dwm","composition-sync",dwm);
                Mark("copy","screen-copy");
                using (var bitmap=new Bitmap(width,height,PixelFormat.Format24bppRgb))
                using (var graphics=Graphics.FromImage(bitmap)) {
                    graphics.CopyFromScreen(origin.x,origin.y,0,0,new Size(width,height),CopyPixelOperation.SourceCopy);
                    SampleElapsedMs[i]=clock.ElapsedMilliseconds;
                    Mark("write","bitmap-write");
                    bitmap.Save(Path.Combine(directory,"client-"+i+".bmp"),ImageFormat.Bmp);
                    CompletedSamples=i+1;
                }
                if (i<7) System.Threading.Thread.Sleep(310);
            }
            Mark("complete","capture-complete");
        } finally {
            if (topmost && IsWindow(root)) SetWindowPos(root,new IntPtr(-2),0,0,0,0,0x0001|0x0002|0x0010);
            if (previous!=IntPtr.Zero) SetThreadDpiAwarenessContext(previous);
        }
    }
}
'@
    if ($CompileOnly) {
        Write-Report @{schema=1; compileOnly=$true; captureFailed=$false; captures=@()}
        exit 0
    }
    foreach ($window in $state.windows) {
        $stage='input'; $code='window-state'
        if ($window.hwnd -notmatch '^[0-9a-f]{1,16}$' -or $window.rootHwnd -notmatch '^[0-9a-f]{1,16}$') { throw 'Invalid handle.' }
        if (($window.role -eq 'main-preview' -and $window.qtClass -ne 'OBSBasicPreview') -or ($window.role -eq 'program-projector' -and $window.qtClass -ne 'OBSProjector')) { throw 'Incorrect widget.' }
        $target = Join-Path $OutputDirectory $window.role
        $roleResult = @{role=$window.role; sampleElapsedMs=@(); startedAtUnixMs=[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds(); sampleCount=0; capture='visible-synthetic-owned-client'; captureFailed=$true}
        $nativeStarted=$false
        try {
            $stage='role-directory'; $code='role-directory'
            if (Test-Path -LiteralPath $target) { throw 'Existing capture directory.' }
            New-Item -ItemType Directory -Path $target | Out-Null
            $nativeStarted=$true
            [ObsPixelCapture]::Capture([uint32]$ExpectedProcessId,[IO.Path]::GetFullPath($ExpectedExecutable),$ExpectedCreationTime,$window.hwnd,$window.rootHwnd,$window.role,$target)
            $roleResult.sampleElapsedMs=@([ObsPixelCapture]::SampleElapsedMs)
            $roleResult.sampleCount=8; $roleResult.captureFailed=$false
        } catch {
            $roleResult.diagnostic=Get-SafeDiagnostic $_ $nativeStarted
            if ($nativeStarted) {
                $roleResult.sampleCount=[ObsPixelCapture]::CompletedSamples
                $roleResult.sampleElapsedMs=@([ObsPixelCapture]::SampleElapsedMs | Select-Object -First $roleResult.sampleCount)
            }
        }
        # Even if Preview fails, attempt the separately identified Program role.
        # Already-written BMPs remain for all-eight analysis; no recapture/retry.
        $results += $roleResult
    }
    $failed = @($results | Where-Object { $_.captureFailed }).Count -gt 0
    Write-Report @{schema=1; captureFailed=$failed; captures=$results}
    if ($failed) { exit 1 }
} catch {
    Write-Report @{schema=1; captureFailed=$true; diagnostic=(Get-SafeDiagnostic $_); captures=$results}
    exit 1
}
