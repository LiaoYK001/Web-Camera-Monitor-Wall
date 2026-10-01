"""Set a protected current-user ACL without invoking a shell or system PATH."""
import ctypes
import os
import pathlib
import sys
from ctypes import wintypes

def protect(directory):
    directory = pathlib.Path(directory).absolute()
    directory.mkdir(parents=True, exist_ok=True)
    # Refuse existing junctions/reparse points anywhere in the private root.
    for ancestor in [directory, *directory.parents]:
        if getattr(ancestor.lstat(), "st_file_attributes", 0) & 0x400:
            raise ValueError("private data root must not contain a reparse point")
    if os.name != "nt":
        directory.chmod(0o700); return
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    token = wintypes.HANDLE()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)): raise ctypes.WinError(ctypes.get_last_error())
    try:
        size = wintypes.DWORD()
        advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)): raise ctypes.WinError(ctypes.get_last_error())
        sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
        sid_text = wintypes.LPWSTR()
        advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
        if not advapi.ConvertSidToStringSidW(sid, ctypes.byref(sid_text)): raise ctypes.WinError(ctypes.get_last_error())
        try:
            descriptor = ctypes.c_void_p()
            sddl = f"O:{sid_text.value}D:P(A;OICI;FA;;;{sid_text.value})"
            advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
            if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None): raise ctypes.WinError(ctypes.get_last_error())
            try:
                advapi.SetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
                for target in [directory, *directory.rglob('*')]:
                    try:attributes=target.lstat()
                    except FileNotFoundError:
                        if target==directory:raise
                        continue  # Browser cache entries may disappear during startup.
                    if getattr(attributes, 'st_file_attributes', 0) & 0x400: raise ValueError('private directory contains a reparse point')
                    if not advapi.SetFileSecurityW(str(target), 0x80000005, descriptor):
                        error=ctypes.get_last_error()
                        if target!=directory and error in (2,3):continue
                        raise ctypes.WinError(error)
            finally: kernel.LocalFree(descriptor)
        finally: kernel.LocalFree(ctypes.cast(sid_text, ctypes.c_void_p))
    finally: kernel.CloseHandle(token)

if __name__ == "__main__":
    if len(sys.argv) != 2: raise SystemExit(2)
    protect(sys.argv[1])
