#requires -Version 7.2
# Read-only measurement of a scope captured BEFORE its isolated directory exists.
# Dot-source this file; importing it never enumerates a directory or starts a process.
$ErrorActionPreference = 'Stop'
if (-not $IsWindows) { throw 'installed_tree_footprint_requires_windows' }

if (-not ('WebOBS.InstalledTreeFootprint.Reader' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

namespace WebOBS.InstalledTreeFootprint
{
    public sealed class Scope
    {
        internal readonly string Root;
        internal readonly string ParentIdentity;
        internal readonly string Purpose;
        internal bool Consumed;
        internal Scope(string root, string parentIdentity, string purpose)
        { Root = root; ParentIdentity = parentIdentity; Purpose = purpose; }
        public override string ToString() { return "unconsumed-isolated-install-tree-scope"; }
    }

    public sealed class Result
    {
        public long LogicalBytes { get; internal set; }
        public long MainStreamAllocationBytes { get; internal set; }
        public long FileCount { get; internal set; }
        public long DirectoryCount { get; internal set; }
        public long AllocationUnitBytes { get; internal set; }
        public long ElapsedMilliseconds { get; internal set; }
        public string StartedAt { get; internal set; }
        public string CompletedAt { get; internal set; }
        public string Purpose { get; internal set; }
    }

    public static class Reader
    {
        private const uint ReadAttributes = 0x80, ShareRead = 1;
        private const uint OpenExisting = 3, OpenReparsePoint = 0x00200000, BackupSemantics = 0x02000000;
        private const uint DirectoryAttribute = 0x10, DeviceAttribute = 0x40, ReparseAttribute = 0x400;
        private const uint FileTypeDisk = 1, DriveFixed = 3;
        private const int FileStandardInfo = 1, FileAttributeTagInfo = 9, FileIdInfo = 18;

        [StructLayout(LayoutKind.Sequential)]
        private struct StandardInfo
        {
            internal long AllocationSize;
            internal long EndOfFile;
            internal uint NumberOfLinks;
            [MarshalAs(UnmanagedType.U1)] internal bool DeletePending;
            [MarshalAs(UnmanagedType.U1)] internal bool Directory;
        }
        [StructLayout(LayoutKind.Sequential)]
        private struct AttributeInfo { internal uint Attributes; internal uint ReparseTag; }
        [StructLayout(LayoutKind.Sequential)]
        private struct IdInfo { internal ulong VolumeSerialNumber; internal ulong Low; internal ulong High; }

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern SafeFileHandle CreateFileW(string fileName, uint access, uint share,
            IntPtr security, uint creation, uint flags, IntPtr template);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern uint GetFileType(SafeFileHandle handle);
        [DllImport("kernel32.dll", EntryPoint = "GetFileInformationByHandleEx", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool GetStandard(SafeFileHandle handle, int infoClass, out StandardInfo value, uint size);
        [DllImport("kernel32.dll", EntryPoint = "GetFileInformationByHandleEx", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool GetAttributes(SafeFileHandle handle, int infoClass, out AttributeInfo value, uint size);
        [DllImport("kernel32.dll", EntryPoint = "GetFileInformationByHandleEx", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool GetIdentity(SafeFileHandle handle, int infoClass, out IdInfo value, uint size);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern uint GetFileAttributesW(string path);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
        private static extern uint GetDriveTypeW(string root);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool GetDiskFreeSpaceW(string root, out uint sectorsPerCluster,
            out uint bytesPerSector, out uint freeClusters, out uint clusters);

        private sealed class Rejected : Exception
        {
            internal readonly string Code;
            internal Rejected(string code) { Code = code; }
        }
        private static void Require(bool condition, string code)
        { if (!condition) throw new Rejected(code); }
        private static string Normalize(string path)
        {
            Require(!String.IsNullOrEmpty(path) && Path.IsPathFullyQualified(path), "absolute_local_path_required");
            Require(!path.StartsWith(@"\\", StringComparison.Ordinal) && path.IndexOf(':', 2) < 0,
                "unc_device_or_stream_path_rejected");
            string full = Path.GetFullPath(path).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            string volume = Path.GetPathRoot(full);
            Require(full.Length > volume.TrimEnd('\\').Length && GetDriveTypeW(volume) == DriveFixed,
                "local_fixed_nonvolume_root_required");
            return full;
        }
        private static SafeFileHandle Open(string path)
        {
            // No write/delete sharing: keep this observed entry from being replaced or
            // converted into a reparse point while its descendants are enumerated.
            SafeFileHandle handle = CreateFileW(path, ReadAttributes, ShareRead, IntPtr.Zero,
                OpenExisting, OpenReparsePoint | BackupSemantics, IntPtr.Zero);
            if (handle.IsInvalid) { handle.Dispose(); throw new Rejected("read_handle_unavailable"); }
            return handle;
        }
        private static StandardInfo Inspect(SafeFileHandle handle, bool directory)
        {
            AttributeInfo attributes;
            StandardInfo standard;
            Require(GetFileType(handle) == FileTypeDisk, "non_disk_entry_rejected");
            Require(GetAttributes(handle, FileAttributeTagInfo, out attributes, (uint)Marshal.SizeOf(typeof(AttributeInfo))),
                "attributes_unavailable");
            Require((attributes.Attributes & ReparseAttribute) == 0 && attributes.ReparseTag == 0,
                "reparse_entry_rejected");
            Require((attributes.Attributes & DeviceAttribute) == 0, "device_entry_rejected");
            Require(GetStandard(handle, FileStandardInfo, out standard, (uint)Marshal.SizeOf(typeof(StandardInfo))),
                "standard_info_unavailable");
            Require(standard.Directory == directory && ((attributes.Attributes & DirectoryAttribute) != 0) == directory,
                "entry_type_changed_or_nonregular");
            Require(!standard.DeletePending && standard.AllocationSize >= 0 && standard.EndOfFile >= 0,
                "invalid_or_deleting_entry");
            if (!directory) Require(standard.NumberOfLinks == 1, "hard_link_rejected");
            return standard;
        }
        private static string Identity(SafeFileHandle handle)
        {
            IdInfo id;
            Require(GetIdentity(handle, FileIdInfo, out id, (uint)Marshal.SizeOf(typeof(IdInfo))), "file_identity_unavailable");
            return id.VolumeSerialNumber.ToString("X16") + ":" + id.Low.ToString("X16") + id.High.ToString("X16");
        }
        private static List<SafeFileHandle> OpenAncestors(string directory)
        {
            var paths = new List<string>();
            for (string current = directory; current != null; current = Path.GetDirectoryName(current)) paths.Add(current);
            paths.Reverse();
            var handles = new List<SafeFileHandle>();
            try
            {
                foreach (string path in paths)
                {
                    SafeFileHandle handle = Open(path);
                    handles.Add(handle);
                    Inspect(handle, true);
                }
                return handles;
            }
            catch { foreach (SafeFileHandle handle in handles) handle.Dispose(); throw; }
        }
        private static void EnsureAbsent(string path)
        {
            uint attributes = GetFileAttributesW(path);
            int error = Marshal.GetLastWin32Error();
            Require(attributes == UInt32.MaxValue && (error == 2 || error == 3), "scope_root_must_not_exist");
        }
        public static Scope BeforeCreation(string root, string purpose)
        {
            try
            {
                Require(purpose == "isolated-nsis-install-before-first-start" || purpose == "synthetic-new-test-fixture",
                    "unsupported_scope_purpose");
                root = Normalize(root);
                string parent = Path.GetDirectoryName(root);
                List<SafeFileHandle> ancestors = OpenAncestors(parent);
                try
                {
                    EnsureAbsent(root);
                    return new Scope(root, Identity(ancestors[ancestors.Count - 1]), purpose);
                }
                finally { foreach (SafeFileHandle handle in ancestors) handle.Dispose(); }
            }
            catch (Rejected error) { throw new InvalidOperationException("installed_tree_footprint: " + error.Code); }
            catch { throw new InvalidOperationException("installed_tree_footprint: scope_inspection_failed"); }
        }

        private sealed class Scan
        {
            internal readonly Result Result;
            internal readonly Stopwatch Clock = Stopwatch.StartNew();
            internal readonly HashSet<string> Identities = new HashSet<string>(StringComparer.Ordinal);
            internal readonly int MaximumFiles, MaximumDirectories, MaximumDepth, MaximumSeconds;
            internal Scan(Result result, int files, int directories, int depth, int seconds)
            { Result = result; MaximumFiles = files; MaximumDirectories = directories; MaximumDepth = depth; MaximumSeconds = seconds; }
            private void Bound()
            { Require(Clock.Elapsed.TotalSeconds <= MaximumSeconds, "measurement_time_limit"); }
            internal void Visit(string directory, int depth)
            {
                Bound();
                Require(depth <= MaximumDepth, "directory_depth_limit");
                using (SafeFileHandle handle = Open(directory))
                {
                    Inspect(handle, true);
                    Require(Identities.Add(Identity(handle)), "duplicate_file_identity_rejected");
                    Result.DirectoryCount = checked(Result.DirectoryCount + 1);
                    Require(Result.DirectoryCount <= MaximumDirectories, "directory_count_limit");
                    // Directory is pinned without write/delete sharing. No recursion/follow-link
                    // option is delegated to the filesystem enumerator; every child is inspected.
                    var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                    foreach (string entry in Directory.EnumerateFileSystemEntries(directory))
                    {
                        Bound();
                        Require(names.Add(Path.GetFileName(entry)), "duplicate_directory_entry");
                        Require(names.Count <= MaximumFiles + MaximumDirectories, "entry_count_limit");
                        uint attributes = GetFileAttributesW(entry);
                        Require(attributes != UInt32.MaxValue, "entry_attributes_unavailable");
                        Require((attributes & ReparseAttribute) == 0, "reparse_entry_rejected");
                        if ((attributes & DirectoryAttribute) != 0) Visit(entry, depth + 1);
                        else
                        {
                            using (SafeFileHandle file = Open(entry))
                            {
                                StandardInfo before = Inspect(file, false);
                                Require(Identities.Add(Identity(file)), "duplicate_file_identity_rejected");
                                Result.FileCount = checked(Result.FileCount + 1);
                                Require(Result.FileCount <= MaximumFiles, "file_count_limit");
                                Result.LogicalBytes = checked(Result.LogicalBytes + before.EndOfFile);
                                Result.MainStreamAllocationBytes = checked(Result.MainStreamAllocationBytes + before.AllocationSize);
                                StandardInfo after = Inspect(file, false);
                                Require(before.EndOfFile == after.EndOfFile && before.AllocationSize == after.AllocationSize,
                                    "file_changed_during_measurement");
                            }
                        }
                    }
                    var afterNames = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                    foreach (string entry in Directory.EnumerateFileSystemEntries(directory))
                    {
                        Bound();
                        Require(afterNames.Add(Path.GetFileName(entry)), "duplicate_directory_entry");
                        Require(afterNames.Count <= MaximumFiles + MaximumDirectories, "entry_count_limit");
                    }
                    Require(names.SetEquals(afterNames), "directory_changed_during_measurement");
                    Inspect(handle, true);
                }
            }
        }
        public static Result Measure(Scope scope, int maximumFiles, int maximumDirectories, int maximumDepth, int maximumSeconds)
        {
            try
            {
                Require(scope != null && !scope.Consumed, "new_unconsumed_scope_required");
                scope.Consumed = true;
                Require(maximumFiles >= 1 && maximumFiles <= 1000000 && maximumDirectories >= 1 && maximumDirectories <= 100000 &&
                    maximumDepth >= 1 && maximumDepth <= 256 && maximumSeconds >= 1 && maximumSeconds <= 900,
                    "invalid_measurement_limits");
                Require(Marshal.SizeOf(typeof(StandardInfo)) == 24 && Marshal.SizeOf(typeof(IdInfo)) == 24,
                    "native_structure_layout_mismatch");
                var result = new Result { Purpose = scope.Purpose, StartedAt = DateTime.UtcNow.ToString("o") };
                var scan = new Scan(result, maximumFiles, maximumDirectories, maximumDepth, maximumSeconds);
                List<SafeFileHandle> ancestors = OpenAncestors(Path.GetDirectoryName(scope.Root));
                try
                {
                    Require(Identity(ancestors[ancestors.Count - 1]) == scope.ParentIdentity, "scope_parent_identity_changed");
                    uint sectors, bytes, free, total;
                    Require(GetDiskFreeSpaceW(Path.GetPathRoot(scope.Root), out sectors, out bytes, out free, out total) &&
                        sectors > 0 && bytes > 0, "allocation_unit_unavailable");
                    result.AllocationUnitBytes = checked((long)sectors * bytes);
                    scan.Visit(scope.Root, 0);
                    result.CompletedAt = DateTime.UtcNow.ToString("o");
                    result.ElapsedMilliseconds = scan.Clock.ElapsedMilliseconds;
                    return result;
                }
                finally { foreach (SafeFileHandle handle in ancestors) handle.Dispose(); }
            }
            catch (Rejected error) { throw new InvalidOperationException("installed_tree_footprint: " + error.Code); }
            catch (OverflowException) { throw new InvalidOperationException("installed_tree_footprint: integer_overflow"); }
            catch { throw new InvalidOperationException("installed_tree_footprint: measurement_failed_no_partial_totals"); }
        }
    }
}
'@
}

function New-InstalledTreeFootprintScope {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][ValidateSet('isolated-nsis-install-before-first-start','synthetic-new-test-fixture')][string]$Purpose
    )
    # A caller cannot attach this API to an existing/private directory: capture first,
    # then let NSIS (or the synthetic fixture) create this exact, new root.
    [WebOBS.InstalledTreeFootprint.Reader]::BeforeCreation($Root, $Purpose)
}

function Measure-InstalledTreeFootprint {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][WebOBS.InstalledTreeFootprint.Scope]$Scope,
        [ValidateRange(1,1000000)][int]$MaximumFiles = 200000,
        [ValidateRange(1,100000)][int]$MaximumDirectories = 20000,
        [ValidateRange(1,256)][int]$MaximumDepth = 128,
        [ValidateRange(1,900)][int]$MaximumSeconds = 300
    )
    $measurement = [WebOBS.InstalledTreeFootprint.Reader]::Measure($Scope, $MaximumFiles, $MaximumDirectories, $MaximumDepth, $MaximumSeconds)
    [ordered]@{
        schema = 1
        scope = $measurement.Purpose
        status = 'measured'
        logicalBytes = $measurement.LogicalBytes
        fileCount = $measurement.FileCount
        directoryCountIncludingRoot = $measurement.DirectoryCount
        mainStreamAllocationBytes = $measurement.MainStreamAllocationBytes
        allocationUnitBytes = $measurement.AllocationUnitBytes
        startedAt = $measurement.StartedAt
        completedAt = $measurement.CompletedAt
        elapsedMilliseconds = $measurement.ElapsedMilliseconds
        method = [ordered]@{
            logical = 'GetFileInformationByHandleEx(FILE_STANDARD_INFO).EndOfFile; sum regular unnamed data streams'
            allocation = 'GetFileInformationByHandleEx(FILE_STANDARD_INFO).AllocationSize; sum regular unnamed data streams'
            identity = 'GetFileInformationByHandleEx(FILE_ID_INFO); hard links and duplicate identities rejected'
            reparsePoints = 'rejected for root, ancestors and every entry; no link traversal'
            unknownOrFailure = 'fail closed; no partial result and no replacement zero'
        }
        limits = [ordered]@{
            maximumFiles = $MaximumFiles; maximumDirectories = $MaximumDirectories
            maximumDepth = $MaximumDepth; maximumSeconds = $MaximumSeconds
            atomicSnapshot = $false
            consistency = 'before first product start; read handles and entry-set checks, not a filesystem snapshot'
            totalVolumeUsage = $false
            excludes = @('filesystem metadata and directory allocation','alternate data streams','external user profiles, recordings, caches and other directories','installer archive and space on other volumes')
        }
    }
}
