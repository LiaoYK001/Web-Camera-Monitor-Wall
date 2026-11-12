"""Windows-only read-only process API. No command lines, environment or product control."""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import os
from pathlib import Path

if os.name != "nt":
    raise ImportError("Windows process collector requires Windows x64")
if C.sizeof(C.c_void_p) != 8:
    raise ImportError("Use a 64-bit Python interpreter for Windows x64 collection")

kernel = C.WinDLL("kernel32", use_last_error=True)
psapi = C.WinDLL("psapi", use_last_error=True)
advapi = C.WinDLL("advapi32", use_last_error=True)


class FILETIME(C.Structure):
    _fields_ = [("low", W.DWORD), ("high", W.DWORD)]
    @property
    def ticks(self):
        return (self.high << 32) | self.low


class PROCESSENTRY32W(C.Structure):
    _fields_ = [("dwSize", W.DWORD), ("cntUsage", W.DWORD), ("th32ProcessID", W.DWORD),
                ("th32DefaultHeapID", C.c_size_t), ("th32ModuleID", W.DWORD), ("cntThreads", W.DWORD),
                ("th32ParentProcessID", W.DWORD), ("pcPriClassBase", W.LONG), ("dwFlags", W.DWORD),
                ("szExeFile", W.WCHAR * 260)]


class MEMORY(C.Structure):
    _fields_ = [("cb", W.DWORD), ("PageFaultCount", W.DWORD), ("PeakWorkingSetSize", C.c_size_t),
                ("WorkingSetSize", C.c_size_t), ("QuotaPeakPagedPoolUsage", C.c_size_t),
                ("QuotaPagedPoolUsage", C.c_size_t), ("QuotaPeakNonPagedPoolUsage", C.c_size_t),
                ("QuotaNonPagedPoolUsage", C.c_size_t), ("PagefileUsage", C.c_size_t),
                ("PeakPagefileUsage", C.c_size_t), ("PrivateUsage", C.c_size_t)]


class SECURITY_ATTRIBUTES(C.Structure):
    _fields_ = [("nLength", W.DWORD), ("lpSecurityDescriptor", C.c_void_p), ("bInheritHandle", W.BOOL)]


def signature(library, name, result, arguments):
    function = getattr(library, name)
    function.restype = result; function.argtypes = arguments
    return function


CloseHandle = signature(kernel, "CloseHandle", W.BOOL, [W.HANDLE])
OpenProcess = signature(kernel, "OpenProcess", W.HANDLE, [W.DWORD, W.BOOL, W.DWORD])
GetProcessTimes = signature(kernel, "GetProcessTimes", W.BOOL, [W.HANDLE] + [C.POINTER(FILETIME)] * 4)
WaitForSingleObject = signature(kernel, "WaitForSingleObject", W.DWORD, [W.HANDLE, W.DWORD])
QueryFullProcessImageNameW = signature(kernel, "QueryFullProcessImageNameW", W.BOOL,
                                     [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)])
GetProcessMemoryInfo = signature(psapi, "GetProcessMemoryInfo", W.BOOL, [W.HANDLE, C.POINTER(MEMORY), W.DWORD])
CreateToolhelp32Snapshot = signature(kernel, "CreateToolhelp32Snapshot", W.HANDLE, [W.DWORD, W.DWORD])
Process32FirstW = signature(kernel, "Process32FirstW", W.BOOL, [W.HANDLE, C.POINTER(PROCESSENTRY32W)])
Process32NextW = signature(kernel, "Process32NextW", W.BOOL, [W.HANDLE, C.POINTER(PROCESSENTRY32W)])
GetActiveProcessorCount = signature(kernel, "GetActiveProcessorCount", W.DWORD, [W.WORD])
GetSystemTimePreciseAsFileTime = signature(kernel, "GetSystemTimePreciseAsFileTime", None, [C.POINTER(FILETIME)])
GetCurrentProcess = signature(kernel, "GetCurrentProcess", W.HANDLE, [])
OpenProcessToken = signature(advapi, "OpenProcessToken", W.BOOL, [W.HANDLE, W.DWORD, C.POINTER(W.HANDLE)])
GetTokenInformation = signature(advapi, "GetTokenInformation", W.BOOL,
                                [W.HANDLE, C.c_int, C.c_void_p, W.DWORD, C.POINTER(W.DWORD)])
ConvertSidToStringSidW = signature(advapi, "ConvertSidToStringSidW", W.BOOL, [C.c_void_p, C.POINTER(W.LPWSTR)])
ConvertStringSecurityDescriptorToSecurityDescriptorW = signature(advapi, "ConvertStringSecurityDescriptorToSecurityDescriptorW", W.BOOL,
                                                                [W.LPCWSTR, W.DWORD, C.POINTER(C.c_void_p), C.POINTER(W.DWORD)])
LocalFree = signature(kernel, "LocalFree", C.c_void_p, [C.c_void_p])
CreateDirectoryW = signature(kernel, "CreateDirectoryW", W.BOOL, [W.LPCWSTR, C.POINTER(SECURITY_ATTRIBUTES)])
GetDriveTypeW = signature(kernel, "GetDriveTypeW", W.UINT, [W.LPCWSTR])
GetVolumeInformationW = signature(kernel, "GetVolumeInformationW", W.BOOL,
                                  [W.LPCWSTR, W.LPWSTR, W.DWORD, C.POINTER(W.DWORD), C.POINTER(W.DWORD),
                                   C.POINTER(W.DWORD), W.LPWSTR, W.DWORD])


def checked(ok):
    if not ok:
        raise C.WinError(C.get_last_error())
    return ok


def create_private_directory(path: Path) -> None:
    """Create with protected current-user + SYSTEM inheritable DACL, no inherited public read."""
    if str(path).startswith("\\\\") or GetDriveTypeW(path.anchor) != 3:  # DRIVE_FIXED
        raise ValueError("Private output requires a local fixed disk, not a UNC/removable/network path")
    flags = W.DWORD()
    checked(GetVolumeInformationW(path.anchor, None, 0, None, None, C.byref(flags), None, 0))
    if not flags.value & 0x8:  # FILE_PERSISTENT_ACLS; FAT-style filesystems cannot enforce this DACL.
        raise ValueError("Private output filesystem must support persistent ACLs")
    token = W.HANDLE(); checked(OpenProcessToken(GetCurrentProcess(), 0x0008, C.byref(token)))
    try:
        length = W.DWORD()
        GetTokenInformation(token, 1, None, 0, C.byref(length))
        if not length.value:
            raise C.WinError(C.get_last_error())
        buffer = C.create_string_buffer(length.value)
        checked(GetTokenInformation(token, 1, buffer, length, C.byref(length)))
        sid = C.cast(buffer, C.POINTER(C.c_void_p))[0]
        text = W.LPWSTR()
        checked(ConvertSidToStringSidW(sid, C.byref(text)))
        try:
            sddl = f"D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;{text.value})"
        finally:
            LocalFree(C.cast(text, C.c_void_p))
        descriptor = C.c_void_p()
        checked(ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, C.byref(descriptor), None))
        try:
            attrs = SECURITY_ATTRIBUTES(C.sizeof(SECURITY_ATTRIBUTES), descriptor, False)
            checked(CreateDirectoryW(str(path), C.byref(attrs)))
        finally:
            LocalFree(descriptor)
    finally:
        CloseHandle(token)


def system_file_time() -> int:
    value = FILETIME(); GetSystemTimePreciseAsFileTime(C.byref(value))
    return value.ticks


def logical_processors() -> int:
    # ALL_PROCESSOR_GROUPS: do not silently normalize by just the current processor group.
    result = GetActiveProcessorCount(0xFFFF)
    if not result:
        raise C.WinError(C.get_last_error())
    return result


def snapshot() -> list[dict]:
    handle = CreateToolhelp32Snapshot(0x00000002, 0)
    if handle == C.c_void_p(-1).value:
        raise C.WinError(C.get_last_error())
    entries = []
    try:
        entry = PROCESSENTRY32W(); entry.dwSize = C.sizeof(entry)
        ok = Process32FirstW(handle, C.byref(entry))
        while ok:
            entries.append({"pid": entry.th32ProcessID, "parentPid": entry.th32ParentProcessID,
                            "exeName": entry.szExeFile})
            ok = Process32NextW(handle, C.byref(entry))
        if C.get_last_error() != 18:  # ERROR_NO_MORE_FILES
            raise C.WinError(C.get_last_error())
        return entries
    finally:
        CloseHandle(handle)


class Process:
    def __init__(self, pid: int, parent_pid: int, name: str, parent_identity: str | None):
        self.handle = OpenProcess(0x1000 | 0x100000, False, pid)  # QUERY_LIMITED_INFORMATION | SYNCHRONIZE
        if not self.handle:
            raise C.WinError(C.get_last_error())
        self.pid = pid; self.parent_pid = parent_pid; self.name = name; self.parent_identity = parent_identity
        self.created = 0; self.exited = False; self.exit_time = 0
        try:
            self.created = self.times()[0]
        except BaseException:
            self.close(); raise
        self.identity = f"{pid}:{self.created}"

    def close(self):
        if self.handle:
            CloseHandle(self.handle); self.handle = None

    def image(self) -> str:
        buffer = C.create_unicode_buffer(32768); length = W.DWORD(len(buffer))
        checked(QueryFullProcessImageNameW(self.handle, 0, buffer, C.byref(length)))
        return buffer.value

    def times(self) -> tuple[int, int, int]:
        created = FILETIME(); exited = FILETIME(); kernel_time = FILETIME(); user = FILETIME()
        checked(GetProcessTimes(self.handle, C.byref(created), C.byref(exited), C.byref(kernel_time), C.byref(user)))
        return created.ticks, exited.ticks, kernel_time.ticks + user.ticks

    def observe(self) -> dict:
        result = {"identity": self.identity, "pid": self.pid, "parentPid": self.parent_pid,
                  "parentIdentity": self.parent_identity, "exeName": self.name,
                  "createdFileTime": self.created, "cpuTime100ns": None,
                  "exitFileTime": None, "workingSetBytes": None, "privateBytes": None, "errors": []}
        status = WaitForSingleObject(self.handle, 0)
        if status not in (0, 0x102):
            raise C.WinError(C.get_last_error())
        self.exited = status == 0
        result["exited"] = self.exited
        try:
            created, self.exit_time, result["cpuTime100ns"] = self.times()
            if created != self.created:
                raise ValueError("Retained process handle identity changed")
            result["exitFileTime"] = self.exit_time if self.exited else None
        except OSError:
            result["errors"].append("cpuReadUnavailable")
        if not self.exited:
            memory = MEMORY(); memory.cb = C.sizeof(memory)
            if GetProcessMemoryInfo(self.handle, C.byref(memory), memory.cb):
                result["workingSetBytes"] = memory.WorkingSetSize
                result["privateBytes"] = memory.PrivateUsage
            else:
                result["errors"].append("memoryReadUnavailable")
        return result
