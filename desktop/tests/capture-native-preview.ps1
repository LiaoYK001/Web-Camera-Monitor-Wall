# TEST ONLY: capture the final visible native client, never a camera-health API.
# Only an isolated test-owned webobsd descendant with the exact executable and
# window class is accepted. No full desktop image is stored or published.
param(
    [Parameter(Mandatory=$true)][int]$OwnerProcessId,
    [Parameter(Mandatory=$true)][string]$NativeExecutable,
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [ValidateRange(1,12)][int]$SampleCount = 8
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
$processes = @(Get-CimInstance Win32_Process)
$byId = @{}; foreach ($entry in $processes) { $byId[[int]$entry.ProcessId] = $entry }
$expected = [IO.Path]::GetFullPath($NativeExecutable)
$candidates = @($processes | Where-Object {
    if (-not $_.ExecutablePath -or -not [string]::Equals([IO.Path]::GetFullPath($_.ExecutablePath), $expected, [StringComparison]::OrdinalIgnoreCase)) { return $false }
    $cursor = [int]$_.ProcessId; $seen = @{}
    for ($depth=0; $depth -lt 16 -and $byId.ContainsKey($cursor) -and -not $seen.ContainsKey($cursor); $depth++) {
        if ($cursor -eq $OwnerProcessId) { return $true }
        $seen[$cursor] = $true; $cursor = [int]$byId[$cursor].ParentProcessId
    }
    return $false
})
if ($candidates.Count -ne 1) { throw 'Expected exactly one native executable descended from the isolated test owner.' }
if (-not (Test-Path -LiteralPath $OutputDirectory -PathType Container)) { throw 'Capture output must be an existing isolated test directory.' }
Add-Type -ReferencedAssemblies System.Drawing,System.Windows.Forms -TypeDefinition @'
using System;
using System.Drawing;
using System.Drawing.Imaging;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;
public static class NativePreviewCapture {
    public delegate bool EnumProc(IntPtr handle, IntPtr data);
    [StructLayout(LayoutKind.Sequential)] public struct Rect { public int left, top, right, bottom; }
    [StructLayout(LayoutKind.Sequential)] public struct Point { public int x, y; public Point(int a, int b) { x=a; y=b; } }
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc callback, IntPtr data);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetClassName(IntPtr handle, StringBuilder name, int count);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr handle, out uint pid);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr handle);
    [DllImport("user32.dll")] static extern bool GetClientRect(IntPtr handle, out Rect rect);
    [DllImport("user32.dll")] static extern bool ClientToScreen(IntPtr handle, ref Point point);
    [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr handle, int command);
    [DllImport("user32.dll")] static extern bool SetWindowPos(IntPtr handle, IntPtr after, int x, int y, int w, int h, uint flags);
    [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr handle);
    [DllImport("user32.dll")] static extern IntPtr SetThreadDpiAwarenessContext(IntPtr context);
    [DllImport("user32.dll")] static extern IntPtr WindowFromPoint(Point point);
    [DllImport("user32.dll")] static extern IntPtr GetAncestor(IntPtr handle, uint flags);
    [DllImport("dwmapi.dll")] static extern int DwmFlush();
    static IntPtr Find(uint expectedPid) {
        IntPtr found=IntPtr.Zero; int matches=0;
        EnumWindows(delegate(IntPtr handle, IntPtr data) {
            uint pid; GetWindowThreadProcessId(handle, out pid);
            if (pid != expectedPid) return true;
            var name=new StringBuilder(256); GetClassName(handle,name,name.Capacity);
            // The Job launcher uses STARTF_USESHOWWINDOW/SW_HIDE. Win32 may
            // apply that startup preference to the first ShowWindow call even
            // though the core requested SW_SHOW. Find only our owned HWND,
            // then explicitly expose it below before reading final pixels.
            if (name.ToString()=="WebOBS.NativeProgram") { found=handle; matches++; }
            return true;
        },IntPtr.Zero);
        if (matches!=1) throw new InvalidOperationException("Expected exactly one test-owned native Program window (including startup-hidden windows).");
        return found;
    }
    public static bool Capture(uint pid, string directory, int samples) {
        var previous=SetThreadDpiAwarenessContext(new IntPtr(-4));
        try {
            var handle=Find(pid); var screen=Screen.PrimaryScreen.Bounds;
            bool initiallyVisible=IsWindowVisible(handle);
            ShowWindow(handle,9);
            if (!SetWindowPos(handle,new IntPtr(-1),screen.Left+20,screen.Top+20,Math.Min(1100,screen.Width-40),Math.Min(760,screen.Height-40),0x0040))
                throw new InvalidOperationException("Cannot expose native test window.");
            SetForegroundWindow(handle); System.Threading.Thread.Sleep(300);
            if (!IsWindowVisible(handle)) throw new InvalidOperationException("Test-owned native window could not be made visible.");
            for (int i=0;i<samples;i++) {
                Rect client; var origin=new Point(0,0);
                if (!GetClientRect(handle,out client) || !ClientToScreen(handle,ref origin)) throw new InvalidOperationException("Native client rectangle unavailable.");
                int width=client.right-client.left,height=client.bottom-client.top;
                if (width<320 || height<180) throw new InvalidOperationException("Native test client is too small.");
                if (!screen.Contains(new Rectangle(origin.x,origin.y,width,height))) throw new InvalidOperationException("Native test client is offscreen.");
                // Detect occlusion/hidden desktop rather than mistaking another
                // application's pixels for an OBS success/failure.
                for (int y=1;y<=5;y++) for(int x=1;x<=5;x++)
                    if (GetAncestor(WindowFromPoint(new Point(origin.x+width*x/6,origin.y+height*y/6)),2)!=handle)
                        throw new InvalidOperationException("Native test client is obscured or no interactive desktop is available.");
                DwmFlush();
                using (var image=new Bitmap(width,height,PixelFormat.Format24bppRgb))
                using (var graphics=Graphics.FromImage(image)) {
                    graphics.CopyFromScreen(origin.x,origin.y,0,0,new Size(width,height),CopyPixelOperation.SourceCopy);
                    image.Save(System.IO.Path.Combine(directory,"client-"+i+".bmp"),ImageFormat.Bmp);
                }
                if (i+1<samples) System.Threading.Thread.Sleep(310);
            }
            SetWindowPos(handle,new IntPtr(-2),0,0,0,0,0x0001|0x0002|0x0010);
            return initiallyVisible;
        } finally { if(previous!=IntPtr.Zero) SetThreadDpiAwarenessContext(previous); }
    }
}
'@
$initiallyVisible = [NativePreviewCapture]::Capture([uint32]$candidates[0].ProcessId, [IO.Path]::GetFullPath($OutputDirectory), $SampleCount)
@{ schema=1; samples=$SampleCount; capture='visible-native-client'; scope='synthetic-fixture-only'; initiallyVisible=$initiallyVisible; testExposedAndResized=$true } | ConvertTo-Json -Compress
