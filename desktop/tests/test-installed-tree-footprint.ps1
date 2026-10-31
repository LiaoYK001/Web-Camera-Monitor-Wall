#requires -Version 7.2
[CmdletBinding()]
param()
# Standalone Windows API contracts. Only brand-new synthetic temp directories are
# inspected; no installer, product, personal directory or service is launched.
$ErrorActionPreference = 'Stop'
if (-not $IsWindows) {
    @{schema=1;status='skipped';reason='Windows native filesystem APIs required';productStarted=$false;installerRequired=$false} | ConvertTo-Json -Compress
    return
}
. (Join-Path $PSScriptRoot 'installed-tree-footprint.ps1')

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
namespace WebOBS.InstalledTreeFootprintContract
{
    public static class FixtureApi
    {
        [StructLayout(LayoutKind.Sequential)]
        private struct StandardInfo
        {
            public long AllocationSize;
            public long EndOfFile;
            public uint NumberOfLinks;
            [MarshalAs(UnmanagedType.U1)] public bool DeletePending;
            [MarshalAs(UnmanagedType.U1)] public bool Directory;
        }
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern SafeFileHandle CreateFileW(string name, uint access, uint share,
            IntPtr security, uint creation, uint flags, IntPtr template);
        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool GetFileInformationByHandleEx(SafeFileHandle handle, int infoClass,
            out StandardInfo value, uint size);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool CreateHardLinkW(string link, string existing, IntPtr security);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        [return: MarshalAs(UnmanagedType.U1)]
        public static extern bool CreateSymbolicLinkW(string link, string target, uint flags);
        public static long[] Probe(string name)
        {
            using (SafeFileHandle handle = CreateFileW(name, 0x80, 1, IntPtr.Zero, 3, 0x00200000, IntPtr.Zero))
            {
                if (handle.IsInvalid) throw new InvalidOperationException("fixture_probe_open_failed");
                StandardInfo value;
                if (Marshal.SizeOf(typeof(StandardInfo)) != 24 ||
                    !GetFileInformationByHandleEx(handle, 1, out value, 24))
                    throw new InvalidOperationException("fixture_probe_standard_info_failed");
                return new long[] { value.EndOfFile, value.AllocationSize, value.NumberOfLinks };
            }
        }
    }
}
'@

function Assert-Contract([bool]$Condition, [string]$Code) {
    if (-not $Condition) { throw ('installed_tree_contract: '+$Code) }
}
function Assert-Rejected([scriptblock]$Action, [string]$Code) {
    $rejected = $false
    try { $null = & $Action } catch {
        $rejected = $_.Exception.ToString().Contains('installed_tree_footprint: '+$Code)
    }
    Assert-Contract $rejected ('expected_rejection_'+$Code)
}
function Write-Fixture([string]$Path, [int]$Size) {
    # Write+flush actual bytes, not SetLength (which could create sparse/lazy data).
    $stream = [IO.File]::Open($Path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try {
        $buffer = [byte[]]::new([Math]::Min(65536,[Math]::Max(1,$Size)))
        [Random]::new(42).NextBytes($buffer)
        $remaining = $Size
        while ($remaining -gt 0) {
            $count = [Math]::Min($remaining,$buffer.Length)
            $stream.Write($buffer,0,$count)
            $remaining -= $count
        }
        $stream.Flush($true)
    } finally { $stream.Dispose() }
}

$tempParent = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd([IO.Path]::DirectorySeparatorChar)
$testRoot = Join-Path $tempParent ('webobs-installed-tree-contract-'+[Guid]::NewGuid().ToString('N'))
if (Test-Path -LiteralPath $testRoot) { throw 'fixture_root_already_exists' }
[IO.Directory]::CreateDirectory($testRoot) | Out-Null
$links = [Collections.Generic.List[object]]::new()
$checks = [ordered]@{}
$symlinkStatus = 'not-run'
try {
    $root = Join-Path $testRoot 'new Unicode 安装 fixture'
    $scope = New-InstalledTreeFootprintScope -Root $root -Purpose synthetic-new-test-fixture
    [IO.Directory]::CreateDirectory((Join-Path $root 'nested')) | Out-Null
    $files = @((Join-Path $root 'empty.bin'),(Join-Path $root 'unaligned.bin'),(Join-Path $root 'nested/second.bin'))
    $sizes = @(0,1048593,65539)
    for ($index=0;$index -lt $files.Count;$index++) { Write-Fixture $files[$index] $sizes[$index] }
    $digests = @($files | ForEach-Object { (Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash })
    $native = @($files | ForEach-Object { ,([WebOBS.InstalledTreeFootprintContract.FixtureApi]::Probe($_)) })
    $expectedLogical = [long]0; $expectedAllocation = [long]0
    foreach ($item in $native) { $expectedLogical += $item[0]; $expectedAllocation += $item[1] }
    $result = Measure-InstalledTreeFootprint -Scope $scope
    Assert-Contract ($result.logicalBytes -eq (1048593+65539) -and $result.logicalBytes -eq $expectedLogical) 'logical_main_stream_bytes'
    Assert-Contract ($result.fileCount -eq 3 -and $result.directoryCountIncludingRoot -eq 2) 'regular_entry_counts'
    Assert-Contract ($result.mainStreamAllocationBytes -eq $expectedAllocation) 'allocation_matches_independent_native_query'
    Assert-Contract ($native[0][0] -eq 0 -and $native[0][1] -eq 0) 'empty_file_native_zero'
    Assert-Contract ($result.allocationUnitBytes -gt 0) 'allocation_unit_available'
    $attributes = [IO.File]::GetAttributes($files[1])
    if (-not $attributes.HasFlag([IO.FileAttributes]::Compressed) -and -not $attributes.HasFlag([IO.FileAttributes]::SparseFile)) {
        # The deliberately large ordinary file cannot be resident MFT data. Do not
        # infer allocation for compressed/sparse files from rounding or file length.
        Assert-Contract ($native[1][1] -ge $native[1][0] -and $native[1][1] % $result.allocationUnitBytes -eq 0) 'ordinary_file_allocation_alignment'
        Assert-Contract ($native[1][1] -ne $native[1][0]) 'allocation_is_not_logical_length'
        $checks.ordinaryFileAllocationAlignment = 'passed'
    } else { $checks.ordinaryFileAllocationAlignment = 'skipped-inherited-compressed-or-sparse-storage' }
    for ($index=0;$index -lt $files.Count;$index++) {
        Assert-Contract ((Get-FileHash -LiteralPath $files[$index] -Algorithm SHA256).Hash -eq $digests[$index]) 'read_only_contents_unchanged'
    }
    $encoded = $result | ConvertTo-Json -Depth 6 -Compress
    Assert-Contract (-not $encoded.Contains($testRoot) -and -not $encoded.Contains('empty.bin') -and -not $encoded.Contains('unaligned.bin')) 'aggregate_receipt_has_no_paths'
    Assert-Contract (-not $result.limits.atomicSnapshot -and -not $result.limits.totalVolumeUsage) 'scope_limits_explicit'
    Assert-Contract ($result.method.allocation.Contains('FILE_STANDARD_INFO).AllocationSize')) 'allocation_method_explicit'
    Assert-Rejected { Measure-InstalledTreeFootprint -Scope $scope } 'new_unconsumed_scope_required'
    Assert-Rejected { New-InstalledTreeFootprintScope -Root $root -Purpose synthetic-new-test-fixture } 'scope_root_must_not_exist'
    $checks.nativeLogicalAllocationCountsEmptyAndReadOnly = 'passed'
    $checks.noPathsAndNoWholeDiskClaim = 'passed'
    $checks.existingRootAndScopeReuseRejected = 'passed'

    $emptyRoot = Join-Path $testRoot 'new-empty-root'
    $emptyScope = New-InstalledTreeFootprintScope -Root $emptyRoot -Purpose synthetic-new-test-fixture
    [IO.Directory]::CreateDirectory($emptyRoot) | Out-Null
    $empty = Measure-InstalledTreeFootprint -Scope $emptyScope
    Assert-Contract ($empty.fileCount -eq 0 -and $empty.logicalBytes -eq 0 -and $empty.mainStreamAllocationBytes -eq 0 -and $empty.directoryCountIncludingRoot -eq 1) 'genuinely_empty_directory'
    $checks.emptyNewDirectory = 'passed'

    $missingRoot = Join-Path $testRoot 'never-created'
    $missingScope = New-InstalledTreeFootprintScope -Root $missingRoot -Purpose synthetic-new-test-fixture
    Assert-Rejected { Measure-InstalledTreeFootprint -Scope $missingScope } 'read_handle_unavailable'
    $checks.missingRootFailsWithoutPartialOrZero = 'passed'

    $limitRoot = Join-Path $testRoot 'bounded-root'
    $limitScope = New-InstalledTreeFootprintScope -Root $limitRoot -Purpose synthetic-new-test-fixture
    [IO.Directory]::CreateDirectory($limitRoot) | Out-Null
    Write-Fixture (Join-Path $limitRoot 'one') 1
    Write-Fixture (Join-Path $limitRoot 'two') 2
    Assert-Rejected { Measure-InstalledTreeFootprint -Scope $limitScope -MaximumFiles 1 } 'file_count_limit'
    $checks.fileCountLimitFailsClosed = 'passed'

    $hardRoot = Join-Path $testRoot 'new-hardlink-root'
    $hardScope = New-InstalledTreeFootprintScope -Root $hardRoot -Purpose synthetic-new-test-fixture
    [IO.Directory]::CreateDirectory($hardRoot) | Out-Null
    $hardTarget = Join-Path $hardRoot 'target.bin'; $hardLink = Join-Path $hardRoot 'alias.bin'
    Write-Fixture $hardTarget 128
    Assert-Contract ([WebOBS.InstalledTreeFootprintContract.FixtureApi]::CreateHardLinkW($hardLink,$hardTarget,[IntPtr]::Zero)) 'fixture_hardlink_creation'
    Assert-Contract (([WebOBS.InstalledTreeFootprintContract.FixtureApi]::Probe($hardTarget))[2] -eq 2) 'fixture_hardlink_native_count'
    Assert-Rejected { Measure-InstalledTreeFootprint -Scope $hardScope } 'hard_link_rejected'
    $checks.actualHardLinksRejected = 'passed'

    $linkTarget = Join-Path $testRoot 'own-junction-target'
    [IO.Directory]::CreateDirectory($linkTarget) | Out-Null
    Write-Fixture (Join-Path $linkTarget 'must-not-traverse.bin') 13
    $junctionRoot = Join-Path $testRoot 'new-junction-child-root'
    $junctionScope = New-InstalledTreeFootprintScope -Root $junctionRoot -Purpose synthetic-new-test-fixture
    [IO.Directory]::CreateDirectory($junctionRoot) | Out-Null
    $junction = Join-Path $junctionRoot 'link'
    New-Item -ItemType Junction -Path $junction -Target $linkTarget | Out-Null
    $links.Add(@{path=$junction;directory=$true})
    Assert-Rejected { Measure-InstalledTreeFootprint -Scope $junctionScope } 'reparse_entry_rejected'
    $rootJunction = Join-Path $testRoot 'new-root-junction'
    $rootJunctionScope = New-InstalledTreeFootprintScope -Root $rootJunction -Purpose synthetic-new-test-fixture
    New-Item -ItemType Junction -Path $rootJunction -Target $linkTarget | Out-Null
    $links.Add(@{path=$rootJunction;directory=$true})
    Assert-Rejected { Measure-InstalledTreeFootprint -Scope $rootJunctionScope } 'reparse_entry_rejected'
    Assert-Rejected { New-InstalledTreeFootprintScope -Root (Join-Path $rootJunction 'new-child') -Purpose synthetic-new-test-fixture } 'reparse_entry_rejected'
    $checks.actualRootChildAndAncestorReparsePointsRejected = 'passed'

    $symbolicRoot = Join-Path $testRoot 'new-symbolic-root'
    $symbolicScope = New-InstalledTreeFootprintScope -Root $symbolicRoot -Purpose synthetic-new-test-fixture
    [IO.Directory]::CreateDirectory($symbolicRoot) | Out-Null
    $symbolicLink = Join-Path $symbolicRoot 'symbolic.bin'
    # ALLOW_UNPRIVILEGED_CREATE is only a request, not an elevation attempt.
    if ([WebOBS.InstalledTreeFootprintContract.FixtureApi]::CreateSymbolicLinkW($symbolicLink,$files[1],2)) {
        $links.Add(@{path=$symbolicLink;directory=$false})
        Assert-Rejected { Measure-InstalledTreeFootprint -Scope $symbolicScope } 'reparse_entry_rejected'
        $symlinkStatus = 'passed'
    } else {
        $nativeError = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
        Assert-Contract ($nativeError -eq 1314 -or $nativeError -eq 87) 'unexpected_symlink_fixture_error'
        $symlinkStatus = 'skipped-no-unprivileged-symlink-permission; actual junction reparse tests passed'
    }
    $checks.actualSymbolicLinkRejected = $symlinkStatus
    Assert-Rejected { New-InstalledTreeFootprintScope -Root ($root+':stream') -Purpose synthetic-new-test-fixture } 'unc_device_or_stream_path_rejected'
    $checks.streamScopeRejected = 'passed'

    @{schema=1;status='passed';scope='new-synthetic-fixtures-only';checks=$checks;productStarted=$false;installerRequired=$false;actualNsisInstallMeasured=$false;qualification='Windows filesystem API contracts only; actual NSIS record requires next full build'} | ConvertTo-Json -Depth 5
} finally {
    # Delete only this exact new fixture root, never a supplied/arbitrary path.
    $absolute = [IO.Path]::GetFullPath($testRoot)
    $expectedParent = [IO.Path]::GetFullPath($tempParent)
    if ([IO.Path]::GetDirectoryName($absolute) -ne $expectedParent -or [IO.Path]::GetFileName($absolute) -notmatch '^webobs-installed-tree-contract-[0-9a-f]{32}$') {
        throw 'fixture_cleanup_scope_mismatch'
    }
    foreach ($link in $links) {
        $linkPath = [IO.Path]::GetFullPath($link.path)
        if (-not $linkPath.StartsWith($absolute+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) { throw 'fixture_link_cleanup_scope_mismatch' }
        if ($link.directory) { [IO.Directory]::Delete($linkPath) } else { [IO.File]::Delete($linkPath) }
    }
    Assert-Contract (-not (Get-Item -LiteralPath $absolute -Force).Attributes.HasFlag([IO.FileAttributes]::ReparsePoint)) 'fixture_cleanup_root_not_reparse'
    Remove-Item -LiteralPath $absolute -Recurse -Force
}
