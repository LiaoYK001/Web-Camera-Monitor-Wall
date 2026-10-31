#requires -Version 7.2
# TEST ONLY. Exactly the synthetic-owned Qt child/projector clients, not desktop
# screenshots or source textures. No title/geometry-based window selection.
param(
    [Parameter(Mandatory=$true)][int]$ExpectedProcessId,
    [Parameter(Mandatory=$true)][string]$ExpectedExecutable,
    [Parameter(Mandatory=$true)][string]$ExpectedCreationTime,
    [Parameter(Mandatory=$true)][string]$StateFile,
    [Parameter(Mandatory=$true)][string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
if (-not $IsWindows) { throw 'Final native window pixels require Windows.' }
if (-not (Test-Path -LiteralPath $OutputDirectory -PathType Container)) { throw 'Use an existing private temporary capture directory.' }
if ((Get-Item -LiteralPath $StateFile).Length -gt 65536) { throw 'Oversized finite test state.' }
$state = Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json
if ($state.schema -ne 1 -or $state.scope -ne 'synthetic-test-only' -or $state.pid -ne "$ExpectedProcessId" -or @($state.windows).Count -ne 2) { throw 'Unexpected synthetic state identity.' }
$roles = @($state.windows | ForEach-Object { $_.role })
if (@($roles | Sort-Object -Unique).Count -ne 2 -or $roles -notcontains 'main-preview' -or $roles -notcontains 'program-projector') { throw 'Only the fixed Preview and Program roles are allowed.' }
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
Add-Type -ReferencedAssemblies System.Drawing,System.Windows.Forms -TypeDefinition @'
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
    [DllImport("user32.dll")] static extern bool GetClientRect(IntPtr hwnd,out Rect rect);
    [DllImport("user32.dll")] static extern bool ClientToScreen(IntPtr hwnd,ref Point point);
    [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr hwnd,int command);
    [DllImport("user32.dll")] static extern bool SetWindowPos(IntPtr hwnd,IntPtr after,int x,int y,int w,int h,uint flags);
    [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr hwnd);
    [DllImport("user32.dll")] static extern IntPtr SetThreadDpiAwarenessContext(IntPtr context);
    [DllImport("user32.dll")] static extern IntPtr WindowFromPoint(Point point);
    [DllImport("user32.dll")] static extern IntPtr GetAncestor(IntPtr hwnd,uint flags);
    [DllImport("dwmapi.dll")] static extern int DwmFlush();
    public static long[] SampleElapsedMs;
    static IntPtr Parse(string hex) { return new IntPtr(checked((long)UInt64.Parse(hex,NumberStyles.HexNumber,CultureInfo.InvariantCulture))); }
    static void Identity(uint pid,string executable,long creation,IntPtr hwnd,IntPtr root) {
        using (var process=Process.GetProcessById((int)pid)) {
            if (process.HasExited || !String.Equals(Path.GetFullPath(process.MainModule.FileName),executable,StringComparison.OrdinalIgnoreCase) || process.StartTime.ToUniversalTime().ToFileTimeUtc()!=creation)
                throw new InvalidOperationException("Owned executable/process creation identity changed.");
        }
        uint actual,actualRoot;
        if (!IsWindow(hwnd) || !IsWindow(root) || GetWindowThreadProcessId(hwnd,out actual)==0 || GetWindowThreadProcessId(root,out actualRoot)==0 || actual!=pid || actualRoot!=pid || GetAncestor(hwnd,2)!=root || GetAncestor(root,2)!=root)
            throw new InvalidOperationException("Exact synthetic Qt HWND/root/process identity changed.");
    }
    public static void Capture(uint pid,string executable,string creationText,string handle,string rootHandle,string role,string directory) {
        var hwnd=Parse(handle); var root=Parse(rootHandle);
        long creation=Int64.Parse(creationText,CultureInfo.InvariantCulture);
        var clock=Stopwatch.StartNew(); SampleElapsedMs=new long[8];
        var previous=SetThreadDpiAwarenessContext(new IntPtr(-4));
        bool topmost=false;
        try {
            Identity(pid,executable,creation,hwnd,root);
            var screen=Screen.PrimaryScreen.Bounds;
            ShowWindow(root,9);
            if (role=="main-preview") {
                ShowWindow(root,3); // Maximize the main UI, not its child widget.
                if (!SetWindowPos(root,new IntPtr(-1),0,0,0,0,0x0001|0x0002|0x0040)) throw new InvalidOperationException("Cannot expose owned main Preview.");
            } else {
                if (hwnd!=root || !SetWindowPos(root,new IntPtr(-1),screen.Left+20,screen.Top+20,Math.Min(1100,screen.Width-40),Math.Min(740,screen.Height-40),0x0040)) throw new InvalidOperationException("Cannot expose owned Program projector.");
            }
            topmost=true; SetForegroundWindow(root); System.Threading.Thread.Sleep(400);
            for (int i=0;i<8;i++) {
                Identity(pid,executable,creation,hwnd,root);
                if (!IsWindowVisible(hwnd) || !IsWindowVisible(root)) throw new InvalidOperationException("Owned native client is hidden.");
                Rect rect; var origin=new Point(0,0);
                if (!GetClientRect(hwnd,out rect) || !ClientToScreen(hwnd,ref origin)) throw new InvalidOperationException("Owned client geometry unavailable.");
                int width=rect.right-rect.left,height=rect.bottom-rect.top;
                if (width<320 || height<180 || width>8192 || height>8192 || !screen.Contains(new Rectangle(origin.x,origin.y,width,height))) throw new InvalidOperationException("Owned client is too small/offscreen/oversized.");
                for (int y=1;y<=5;y++) for (int x=1;x<=5;x++) {
                    var hit=WindowFromPoint(new Point(origin.x+width*x/6,origin.y+height*y/6));
                    if (GetAncestor(hit,2)!=root || (hit!=hwnd && !IsChild(hwnd,hit))) throw new InvalidOperationException("Owned client obscured or no interactive desktop; refusing other pixels.");
                }
                if (DwmFlush()!=0) throw new InvalidOperationException("DWM composition synchronization failed.");
                using (var bitmap=new Bitmap(width,height,PixelFormat.Format24bppRgb))
                using (var graphics=Graphics.FromImage(bitmap)) {
                    graphics.CopyFromScreen(origin.x,origin.y,0,0,new Size(width,height),CopyPixelOperation.SourceCopy);
                    SampleElapsedMs[i]=clock.ElapsedMilliseconds;
                    bitmap.Save(Path.Combine(directory,"client-"+i+".bmp"),ImageFormat.Bmp);
                }
                if (i<7) System.Threading.Thread.Sleep(310);
            }
        } finally {
            if (topmost && IsWindow(root)) SetWindowPos(root,new IntPtr(-2),0,0,0,0,0x0001|0x0002|0x0010);
            if (previous!=IntPtr.Zero) SetThreadDpiAwarenessContext(previous);
        }
    }
}
'@
$results = @()
foreach ($window in $state.windows) {
    if ($window.hwnd -notmatch '^[0-9a-f]{1,16}$' -or $window.rootHwnd -notmatch '^[0-9a-f]{1,16}$') { throw 'Invalid exact native handle.' }
    if (($window.role -eq 'main-preview' -and $window.qtClass -ne 'OBSBasicPreview') -or ($window.role -eq 'program-projector' -and $window.qtClass -ne 'OBSProjector')) { throw 'Incorrect Qt widget identity.' }
    $target = Join-Path $OutputDirectory $window.role
    if (Test-Path -LiteralPath $target) { throw 'Refuse an existing capture role directory.' }
    New-Item -ItemType Directory -Path $target | Out-Null
    $started = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
    [ObsPixelCapture]::Capture([uint32]$ExpectedProcessId,[IO.Path]::GetFullPath($ExpectedExecutable),$ExpectedCreationTime,$window.hwnd,$window.rootHwnd,$window.role,$target)
    $results += @{role=$window.role; sampleElapsedMs=@([ObsPixelCapture]::SampleElapsedMs); startedAtUnixMs=$started; sampleCount=8; capture='visible-synthetic-owned-client'}
}
@{schema=1; captures=$results} | ConvertTo-Json -Depth 5 -Compress
