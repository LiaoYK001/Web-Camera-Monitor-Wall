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
    $diagnostic = @{stage=$stage; code=$code; sampleIndex=-1; completedSamples=0; nativeError=0; compilerCodes=@(); missingTypes=@(); missingAssemblies=@()}
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
        # Fixed .NET type/assembly names only; never paths, tokens or user data.
        $diagnostic.missingTypes = @([regex]::Matches($text,"type(?: name)? '([^']{1,200})'") |
            ForEach-Object { $_.Groups[1].Value } | Where-Object { $_ -match '^[A-Za-z0-9_.+<>\[\] ]{1,200}$' } |
            Sort-Object -Unique | Select-Object -First 8)
        $diagnostic.missingAssemblies = @([regex]::Matches($text,"assembly '([^',]{1,200})") |
            ForEach-Object { $_.Groups[1].Value } | Where-Object { $_ -match '^[A-Za-z0-9_.+-]{1,200}$' } |
            Sort-Object -Unique | Select-Object -First 8)
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
        if ($state.schema -ne 1 -or $state.scope -ne 'synthetic-test-only' -or $state.pid -ne "$ExpectedProcessId" -or @($state.windows).Count -lt 1 -or @($state.windows).Count -gt 2) { $code='state-identity'; throw 'Unexpected state.' }
        $roles = @($state.windows | ForEach-Object { $_.role })
        if (@($roles | Sort-Object -Unique).Count -ne $roles.Count -or @($roles | Where-Object { $_ -notin @('main-preview','program-projector') }).Count -ne 0 -or ($roles.Count -eq 2 -and (@($roles) -notcontains 'main-preview' -or @($roles) -notcontains 'program-projector'))) { $code='state-roles'; throw 'Unexpected roles.' }
    }
    $stage='compile'
    # Core-only P/Invoke code: no Windows Drawing/Forms references needed.
    $typeDefinition = @'
using System;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Runtime.InteropServices;
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
    [StructLayout(LayoutKind.Sequential)] struct BitmapInfoHeader { public uint biSize; public int biWidth; public int biHeight; public ushort biPlanes; public ushort biBitCount; public uint biCompression; public uint biSizeImage; public int biXPelsPerMeter; public int biYPelsPerMeter; public uint biClrUsed; public uint biClrImportant; }
    [DllImport("user32.dll")] static extern int GetSystemMetrics(int index);
    [DllImport("user32.dll")] static extern IntPtr GetDC(IntPtr hwnd);
    [DllImport("user32.dll")] static extern int ReleaseDC(IntPtr hwnd,IntPtr dc);
    [DllImport("gdi32.dll")] static extern IntPtr CreateCompatibleDC(IntPtr dc);
    [DllImport("gdi32.dll")] static extern IntPtr CreateCompatibleBitmap(IntPtr dc,int width,int height);
    [DllImport("gdi32.dll")] static extern IntPtr SelectObject(IntPtr dc,IntPtr obj);
    [DllImport("gdi32.dll")] static extern bool DeleteObject(IntPtr obj);
    [DllImport("gdi32.dll")] static extern bool DeleteDC(IntPtr dc);
    [DllImport("gdi32.dll")] static extern bool BitBlt(IntPtr dst,int x,int y,int width,int height,IntPtr src,int sx,int sy,uint rop);
    [DllImport("gdi32.dll")] static extern int GetDIBits(IntPtr dc,IntPtr bitmap,uint start,uint lines,byte[] bits,ref BitmapInfoHeader info,uint usage);
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
            int screenWidth=GetSystemMetrics(0),screenHeight=GetSystemMetrics(1);
            if (screenWidth<=0 || screenHeight<=0) throw Failure("expose","interactive-screen");
            ShowWindow(root,9);
            if (role=="main-preview") {
                ShowWindow(root,3); // Maximize the main UI, not its child widget.
                if (!SetWindowPos(root,new IntPtr(-1),0,0,0,0,0x0001|0x0002|0x0040)) throw Failure("expose","main-preview-expose",Marshal.GetLastWin32Error());
            } else {
                if (hwnd!=root || !SetWindowPos(root,new IntPtr(-1),20,20,Math.Min(1100,screenWidth-40),Math.Min(740,screenHeight-40),0x0040)) throw Failure("expose","program-projector-expose",Marshal.GetLastWin32Error());
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
                if (width<320 || height<180 || width>8192 || height>8192 || origin.x<0 || origin.y<0 || origin.x+width>screenWidth || origin.y+height>screenHeight) throw Failure("geometry","client-bounds");
                for (int y=1;y<=5;y++) for (int x=1;x<=5;x++) {
                    var hit=WindowFromPoint(new Point(origin.x+width*x/6,origin.y+height*y/6));
                    if (GetAncestor(hit,2)!=root || (hit!=hwnd && !IsChild(hwnd,hit))) throw Failure("occlusion","client-obscured");
                }
                Mark("dwm","composition-sync");
                int dwm=DwmFlush(); if (dwm!=0) throw Failure("dwm","composition-sync",dwm);
                Mark("copy","screen-copy");
                var pixels=CaptureClient(origin.x,origin.y,width,height);
                SampleElapsedMs[i]=clock.ElapsedMilliseconds;
                Mark("write","bitmap-write");
                WriteBmp(Path.Combine(directory,"client-"+i+".bmp"),width,height,pixels);
                CompletedSamples=i+1;
                if (i<7) System.Threading.Thread.Sleep(310);
            }
            Mark("complete","capture-complete");
        } finally {
            if (topmost && IsWindow(root)) SetWindowPos(root,new IntPtr(-2),0,0,0,0,0x0001|0x0002|0x0010);
            if (previous!=IntPtr.Zero) SetThreadDpiAwarenessContext(previous);
        }
    }
    static byte[] CaptureClient(int x,int y,int width,int height) {
        int stride=(width*3+3)/4*4;
        var pixels=new byte[checked(stride*height)];
        var header=new BitmapInfoHeader { biSize=(uint)Marshal.SizeOf(typeof(BitmapInfoHeader)), biWidth=width, biHeight=height, biPlanes=1, biBitCount=24, biCompression=0, biSizeImage=(uint)pixels.Length };
        IntPtr screen=GetDC(IntPtr.Zero);
        if (screen==IntPtr.Zero) throw Failure("copy","screen-copy",Marshal.GetLastWin32Error());
        IntPtr memory=IntPtr.Zero,bitmap=IntPtr.Zero,previous=IntPtr.Zero;
        try {
            memory=CreateCompatibleDC(screen); bitmap=CreateCompatibleBitmap(screen,width,height);
            if (memory==IntPtr.Zero || bitmap==IntPtr.Zero) throw Failure("copy","screen-copy",Marshal.GetLastWin32Error());
            previous=SelectObject(memory,bitmap);
            if (previous==IntPtr.Zero) throw Failure("copy","screen-copy",Marshal.GetLastWin32Error());
            if (!BitBlt(memory,0,0,width,height,screen,x,y,0x00CC0020)) throw Failure("copy","screen-copy",Marshal.GetLastWin32Error());
            // GetDIBits requires the bitmap to be deselected first.
            SelectObject(memory,previous); previous=IntPtr.Zero;
            if (GetDIBits(memory,bitmap,0,(uint)height,pixels,ref header,0)!=height) throw Failure("copy","screen-copy",Marshal.GetLastWin32Error());
        } finally {
            if (memory!=IntPtr.Zero) { if (previous!=IntPtr.Zero) SelectObject(memory,previous); if (bitmap!=IntPtr.Zero) DeleteObject(bitmap); DeleteDC(memory); }
            else if (bitmap!=IntPtr.Zero) DeleteObject(bitmap);
            ReleaseDC(IntPtr.Zero,screen);
        }
        return pixels;
    }
    static void WriteBmp(string path,int width,int height,byte[] pixels) {
        int offset=54,size=checked(offset+pixels.Length);
        var file=new byte[size];
        file[0]=(byte)0x42; file[1]=(byte)0x4D;
        Buffer.BlockCopy(BitConverter.GetBytes(size),0,file,2,4);
        Buffer.BlockCopy(BitConverter.GetBytes(offset),0,file,10,4);
        Buffer.BlockCopy(BitConverter.GetBytes(40),0,file,14,4);
        Buffer.BlockCopy(BitConverter.GetBytes(width),0,file,18,4);
        Buffer.BlockCopy(BitConverter.GetBytes(height),0,file,22,4);
        file[26]=1; file[28]=24;
        Buffer.BlockCopy(BitConverter.GetBytes(pixels.Length),0,file,34,4);
        Buffer.BlockCopy(pixels,0,file,offset,pixels.Length);
        File.WriteAllBytes(path,file);
    }
}
'@
    Add-Type -ErrorVariable compilerErrors -TypeDefinition $typeDefinition
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
