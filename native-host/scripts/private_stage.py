#!/usr/bin/env python3
"""Private offline staging, not authorization, live import or cross-file atomicity.

The caller owns input/configuration separation and independent semantic checks.
Readers must revalidate all members. POSIX success requires file/root/parent fsync.
Windows flushes files but directory crash durability is explicitly unconfirmed.
Same-user/admin adversaries are not a security boundary. Never log private data.
"""
from __future__ import annotations
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Callable

MAX_MEMBERS = 3
MAX_BYTES = 8 * 1024 * 1024
MEMBER_NAMES = frozenset({'collection.json', 'manifest.json'})
MARKER = 'completion.json'
COMPLETION_KIND = 'native-legacy-private-stage-completion'


class Rejected(ValueError):
    """A fixed public error code, never private paths/bytes/fingerprints."""


def _require(ok, code='stage_unsafe_object'):
    if not ok:
        raise Rejected(code)


def _identity(info):
    return info.st_dev, info.st_ino


def _write(fd, data):
    view = memoryview(data)
    while view:
        count = os.write(fd, view)
        _require(0 < count <= len(view), 'stage_write_failed')
        view = view[count:]
    os.fsync(fd)


class _Posix:
    durability = 'file-and-directory-synced'

    def __init__(self, destination):
        self.destination, self.stack, self.files = destination, ExitStack(), {}
        self.root = self.root_identity = self.parent = None
        try:
            _require(hasattr(os, 'O_NOFOLLOW') and hasattr(os, 'O_DIRECTORY'), 'stage_unsupported_platform')
            fd = os.open(destination.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            self.stack.callback(os.close, fd)
            for part in destination.parent.parts[1:]:
                _require(stat.S_ISDIR(os.fstat(fd).st_mode))
                fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                self.stack.callback(os.close, fd)
            self.parent = fd
            os.mkdir(destination.name, 0o700, dir_fd=fd)  # exclusive atomic mkdir
            self.root = os.open(destination.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            self.stack.callback(os.close, self.root)
            self.root_identity = _identity(os.fstat(self.root))
            self.check_root()
        except BaseException:
            self.cleanup()
            self.close()
            raise

    def _check_file(self, fd, identity=None):
        info = os.fstat(fd)
        _require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
                 and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1)
        _require(identity is None or _identity(info) == identity)
        return info

    def check_root(self):
        info = os.fstat(self.root)
        _require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
                 and stat.S_IMODE(info.st_mode) == 0o700 and info.st_nlink >= 2)
        named = os.stat(self.destination.name, dir_fd=self.parent, follow_symlinks=False)
        _require(_identity(named) == self.root_identity and stat.S_ISDIR(named.st_mode))

    def create(self, name, data):
        self.check_root()
        fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self.root)
        self.stack.callback(os.close, fd)
        self.files[name] = (fd, _identity(os.fstat(fd)))
        self._check_file(fd)
        _write(fd, data)
        self._check_file(fd)

    def read(self, name):
        self.check_root()
        held, identity = self.files[name]
        self._check_file(held, identity)
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.root)
        try:
            before = self._check_file(fd, identity)
            _require(before.st_size <= MAX_BYTES, 'stage_content_changed')
            chunks, size = [], 0
            while True:
                chunk = os.read(fd, min(65536, MAX_BYTES + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                _require(size <= MAX_BYTES, 'stage_content_changed')
            after = self._check_file(fd, identity)
            _require((before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                     == (after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'stage_content_changed')
            return b''.join(chunks)
        finally:
            os.close(fd)

    def sync(self):
        self.check_root()
        os.fsync(self.root)
        os.fsync(self.parent)

    def cleanup(self):
        # Never enumerate/delete unknown entries. Names AND held identities must
        # match. Same-user rename races remain outside the security boundary.
        if self.root is None or self.root_identity is None:
            return
        try:
            self.check_root()
        except (OSError, Rejected):
            return
        for name, (fd, identity) in reversed(tuple(self.files.items())):
            try:
                held = os.fstat(fd)
                named = os.stat(name, dir_fd=self.root, follow_symlinks=False)
                if _identity(held) == identity == _identity(named) and stat.S_ISREG(named.st_mode) and named.st_nlink == 1:
                    os.unlink(name, dir_fd=self.root)
            except OSError:
                pass
        try:
            self.check_root()
            os.rmdir(self.destination.name, dir_fd=self.parent)
            os.fsync(self.parent)
        except (OSError, Rejected):
            pass

    def close(self):
        self.stack.close()


class _Windows:
    """Protected owner-only DACL supplied at creation; verify via held handles.

    All names are opened OPEN_REPARSE_POINT, with DELETE sharing denied by held
    handles. Only expected unsupported/access directory flush errors are relaxed.
    """
    durability = 'file-flushed-directory-unconfirmed'

    def __init__(self, destination):
        import ctypes as c
        from ctypes import wintypes as w
        self.c, self.w = c, w
        self.destination, self.stack, self.files = destination, ExitStack(), {}
        self.handles = set()
        self.root = self.root_identity = None
        self.k = c.WinDLL('kernel32', use_last_error=True)
        self.a = c.WinDLL('advapi32', use_last_error=True)
        self._bind()
        try:
            self._security()
            current = Path(destination.anchor)
            self.parent = self._open(current, directory=True)
            self._info(self.parent, directory=True)
            self._filesystem(self.parent)
            for part in destination.parent.parts[1:]:
                current = current / part
                self.parent = self._open(current, directory=True)
                self._info(self.parent, directory=True)
            _require(bool(self.k.CreateDirectoryW(str(destination), c.byref(self.sa))), 'stage_create_failed')
            self.root = self._open(destination, directory=True, owned=True)
            self.root_identity = self._info(self.root, directory=True, private=True)
            self._filesystem(self.root)
            self.check_root()
        except BaseException:
            self.cleanup()
            self.close()
            raise

    def _bind(self):
        c, w = self.c, self.w
        def bind(lib, name, args, result):
            fn = getattr(lib, name)
            fn.argtypes, fn.restype = args, result
        bind(self.k, 'CreateFileW', [w.LPCWSTR, w.DWORD, w.DWORD, c.c_void_p, w.DWORD, w.DWORD, w.HANDLE], w.HANDLE)
        bind(self.k, 'CreateDirectoryW', [w.LPCWSTR, c.c_void_p], w.BOOL)
        bind(self.k, 'CloseHandle', [w.HANDLE], w.BOOL)
        bind(self.k, 'GetCurrentProcess', [], w.HANDLE)
        bind(self.k, 'LocalFree', [c.c_void_p], c.c_void_p)
        bind(self.k, 'GetFileType', [w.HANDLE], w.DWORD)
        bind(self.k, 'GetFileInformationByHandle', [w.HANDLE, c.c_void_p], w.BOOL)
        bind(self.k, 'GetVolumeInformationByHandleW', [w.HANDLE, w.LPWSTR, w.DWORD, c.c_void_p, c.c_void_p, c.c_void_p, w.LPWSTR, w.DWORD], w.BOOL)
        bind(self.k, 'FlushFileBuffers', [w.HANDLE], w.BOOL)
        bind(self.k, 'ReadFile', [w.HANDLE, c.c_void_p, w.DWORD, c.c_void_p, c.c_void_p], w.BOOL)
        bind(self.k, 'WriteFile', [w.HANDLE, c.c_void_p, w.DWORD, c.c_void_p, c.c_void_p], w.BOOL)
        bind(self.k, 'SetFileInformationByHandle', [w.HANDLE, c.c_int, c.c_void_p, w.DWORD], w.BOOL)
        bind(self.a, 'OpenProcessToken', [w.HANDLE, w.DWORD, c.c_void_p], w.BOOL)
        bind(self.a, 'GetTokenInformation', [w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.c_void_p], w.BOOL)
        bind(self.a, 'ConvertSidToStringSidW', [c.c_void_p, c.c_void_p], w.BOOL)
        bind(self.a, 'ConvertStringSecurityDescriptorToSecurityDescriptorW', [w.LPCWSTR, w.DWORD, c.c_void_p, c.c_void_p], w.BOOL)
        bind(self.a, 'GetSecurityInfo', [w.HANDLE, c.c_int, w.DWORD, c.c_void_p, c.c_void_p, c.c_void_p, c.c_void_p, c.c_void_p], w.DWORD)
        bind(self.a, 'GetSecurityDescriptorControl', [c.c_void_p, c.c_void_p, c.c_void_p], w.BOOL)
        bind(self.a, 'EqualSid', [c.c_void_p, c.c_void_p], w.BOOL)
        bind(self.a, 'GetAce', [c.c_void_p, w.DWORD, c.c_void_p], w.BOOL)

    def _security(self):
        c, w = self.c, self.w
        token = w.HANDLE()
        _require(bool(self.a.OpenProcessToken(self.k.GetCurrentProcess(), 8, c.byref(token))), 'stage_acl_failed')
        self.stack.callback(self.k.CloseHandle, token)
        length = w.DWORD()
        self.a.GetTokenInformation(token, 1, None, 0, c.byref(length))
        _require(0 < length.value <= 65536, 'stage_acl_failed')
        self.token_buffer = c.create_string_buffer(length.value)
        _require(bool(self.a.GetTokenInformation(token, 1, self.token_buffer, length, c.byref(length))), 'stage_acl_failed')
        self.sid = c.cast(self.token_buffer, c.POINTER(c.c_void_p))[0]
        sid_text = w.LPWSTR()
        _require(bool(self.a.ConvertSidToStringSidW(self.sid, c.byref(sid_text))), 'stage_acl_failed')
        try:
            sddl = 'O:' + sid_text.value + 'D:P(A;;FA;;;' + sid_text.value + ')'
        finally:
            self.k.LocalFree(c.cast(sid_text, c.c_void_p))
        self.sd = c.c_void_p()
        _require(bool(self.a.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, c.byref(self.sd), None)), 'stage_acl_failed')
        self.stack.callback(self.k.LocalFree, self.sd)
        class SecurityAttributes(c.Structure):
            _fields_ = [('length', w.DWORD), ('descriptor', c.c_void_p), ('inherit', w.BOOL)]
        self.sa = SecurityAttributes(c.sizeof(SecurityAttributes), self.sd, False)

    def _open(self, path, directory=False, owned=False, create=False):
        c = self.c
        access = 0x80000000 | (0x40000000 | 0x10000 if create else 0x10000 if owned else 0)
        flags = 0x00200000 | (0x02000000 if directory else 0)
        handle = self.k.CreateFileW(str(path), access, 1, c.byref(self.sa) if create else None, 1 if create else 3, flags, None)
        _require(handle != c.c_void_p(-1).value, 'stage_open_failed')
        self.handles.add(handle)
        self.stack.callback(self._close_handle, handle)
        return handle

    def _close_handle(self, handle):
        if handle in self.handles:
            self.handles.remove(handle)
            self.k.CloseHandle(handle)

    def _filesystem(self, handle):
        c, w = self.c, self.w
        flags, name = w.DWORD(), c.create_unicode_buffer(64)
        _require(bool(self.k.GetVolumeInformationByHandleW(handle, None, 0, None, None, c.byref(flags), name, 64))
                 and flags.value & 8 and name.value in ('NTFS', 'ReFS'), 'stage_unsupported_filesystem')

    def _private(self, handle):
        c, w = self.c, self.w
        owner, acl, descriptor = c.c_void_p(), c.c_void_p(), c.c_void_p()
        _require(self.a.GetSecurityInfo(handle, 1, 5, c.byref(owner), None, c.byref(acl), None, c.byref(descriptor)) == 0, 'stage_acl_failed')
        try:
            control, revision = w.WORD(), w.DWORD()
            _require(bool(owner.value and acl.value and self.a.EqualSid(owner, self.sid)), 'stage_acl_failed')
            _require(bool(self.a.GetSecurityDescriptorControl(descriptor, c.byref(control), c.byref(revision)))
                     and control.value & 0x1000 and control.value & 4, 'stage_acl_failed')
            class Acl(c.Structure):
                _fields_ = [('revision', c.c_ubyte), ('reserved', c.c_ubyte), ('size', w.WORD), ('count', w.WORD), ('reserved2', w.WORD)]
            header = c.cast(acl, c.POINTER(Acl)).contents
            _require(header.revision in (2, 4) and header.count == 1, 'stage_acl_failed')
            ace = c.c_void_p()
            _require(bool(self.a.GetAce(acl, 0, c.byref(ace))), 'stage_acl_failed')
            raw = c.string_at(ace, 8)
            _require(raw[0] == 0 and raw[1] == 0 and int.from_bytes(raw[2:4], 'little') >= 16
                     and int.from_bytes(raw[4:8], 'little') == 0x1F01FF
                     and bool(self.a.EqualSid(c.c_void_p(ace.value + 8), self.sid)), 'stage_acl_failed')
        finally:
            self.k.LocalFree(descriptor)

    def _info(self, handle, directory=False, private=False):
        c, w = self.c, self.w
        class Info(c.Structure):
            _fields_ = [('attributes', w.DWORD), ('created', w.FILETIME), ('accessed', w.FILETIME),
                        ('written', w.FILETIME), ('volume', w.DWORD), ('sizeHigh', w.DWORD),
                        ('sizeLow', w.DWORD), ('links', w.DWORD), ('indexHigh', w.DWORD), ('indexLow', w.DWORD)]
        info = Info()
        _require(bool(self.k.GetFileInformationByHandle(handle, c.byref(info))) and self.k.GetFileType(handle) == 1)
        _require(not info.attributes & 0x400 and bool(info.attributes & 0x10) == directory)
        _require(directory or info.links == 1)
        if private:
            self._private(handle)
        return info.volume, info.indexHigh, info.indexLow

    def check_root(self):
        _require(self._info(self.root, directory=True, private=True) == self.root_identity)

    def create(self, name, data):
        c, w = self.c, self.w
        self.check_root()
        handle = self._open(self.destination / name, owned=True, create=True)
        self.files[name] = (handle, self._info(handle))
        self._info(handle, private=True)  # BEFORE any private bytes
        offset = 0
        while offset < len(data):
            part = data[offset:offset + 65536]
            buffer, written = c.create_string_buffer(part), w.DWORD()
            _require(bool(self.k.WriteFile(handle, buffer, len(part), c.byref(written), None))
                     and 0 < written.value <= len(part), 'stage_write_failed')
            offset += written.value
        _require(bool(self.k.FlushFileBuffers(handle)), 'stage_flush_failed')
        self._info(handle, private=True)

    def read(self, name):
        c, w = self.c, self.w
        self.check_root()
        held, identity = self.files[name]
        _require(self._info(held, private=True) == identity)
        # Reopen acknowledges held write/delete access; held handle still denies
        # other writers/deleters. Open the name itself, never its reparse target.
        handle = self.k.CreateFileW(str(self.destination / name), 0x80000000, 7, None, 3, 0x00200000, None)
        _require(handle != c.c_void_p(-1).value, 'stage_reopen_failed')
        try:
            _require(self._info(handle, private=True) == identity)
            chunks, size = [], 0
            while True:
                buffer, count = c.create_string_buffer(65536), w.DWORD()
                _require(bool(self.k.ReadFile(handle, buffer, 65536, c.byref(count), None)), 'stage_read_failed')
                if not count.value:
                    break
                size += count.value
                _require(size <= MAX_BYTES, 'stage_content_changed')
                chunks.append(buffer.raw[:count.value])
            _require(self._info(handle, private=True) == identity)
            return b''.join(chunks)
        finally:
            self.k.CloseHandle(handle)

    def sync(self):
        self.check_root()
        for handle in (self.root, self.parent):
            if not self.k.FlushFileBuffers(handle):
                _require(self.c.get_last_error() in (1, 5, 50, 87), 'stage_flush_failed')

    def cleanup(self):
        if self.root is None or self.root_identity is None:
            return
        try:
            self.check_root()
        except (OSError, Rejected):
            return
        c, w = self.c, self.w
        flag = w.BOOL(True)
        for handle, identity in reversed(tuple(self.files.values())):
            try:
                if self._info(handle) == identity:
                    self.k.SetFileInformationByHandle(handle, 4, c.byref(flag), c.sizeof(flag))
            except (OSError, Rejected):
                pass
        # Pending child deletes must complete before directory deletion.
        for handle, _ in self.files.values():
            self._close_handle(handle)
        self.files.clear()
        self.k.SetFileInformationByHandle(self.root, 4, c.byref(flag), c.sizeof(flag))

    def close(self):
        self.stack.close()


def _windows_path_safe(destination):
    # Only ordinary local drive-letter paths: no UNC/device namespace, ADS,
    # Win32 trimming aliases, wildcard syntax or reserved DOS device basenames.
    drive = destination.drive
    if not (len(drive) == 2 and drive[0] in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz' and drive[1] == ':'):
        return False
    reserved = {'CON', 'PRN', 'AUX', 'NUL', 'CLOCK$', 'CONIN$', 'CONOUT$'}
    reserved.update(prefix + digit for prefix in ('COM', 'LPT') for digit in '123456789¹²³')
    return all(part and part == part.rstrip(' .')
               and part.split('.')[0].upper() not in reserved
               and not any(ch in '<>:"|?*' or ord(ch) < 32 for ch in part)
               for part in destination.parts[1:])


def _validate(destination, members, verify):
    _require(isinstance(destination, Path) and destination.is_absolute()
             and '..' not in destination.parts and bool(destination.name), 'stage_unsafe_path')
    if os.name == 'nt':
        _require(_windows_path_safe(destination), 'stage_unsafe_path')
    _require(type(members) is dict and 1 <= len(members) <= MAX_MEMBERS, 'stage_invalid_members')
    _require(all(type(name) is str and name in MEMBER_NAMES and type(value) is bytes
                 for name, value in members.items()), 'stage_invalid_members')
    _require(sum(map(len, members.values())) <= MAX_BYTES, 'stage_too_large')
    _require(callable(verify), 'stage_invalid_verifier')
    return dict(sorted(members.items()))


def stage(destination: Path, members: dict[str, bytes], verify: Callable[[dict[str, bytes]], None]) -> None:
    """Create a NEW private directory; publish completion.json after verification.

    verify receives re-read immutable bytes, not the original dict. Its exceptions
    become fixed stage_verification_failed. The primitive performs no input reads.
    Windows success is file-flushed-directory-unconfirmed, not crash durability.
    """
    store = None
    try:
        expected = _validate(destination, members, verify)
        store = (_Windows if os.name == 'nt' else _Posix)(destination)
        for name, data in expected.items():
            store.create(name, data)
        reread = {name: store.read(name) for name in expected}
        _require(reread == expected, 'stage_content_changed')
        try:
            verify(dict(reread))
        except Exception:
            raise Rejected('stage_verification_failed') from None
        _require({name: store.read(name) for name in expected} == expected, 'stage_content_changed')
        store.sync()
        marker = {'schema': 1, 'kind': COMPLETION_KIND, 'durability': store.durability,
                  'members': {name: {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
                              for name, data in expected.items()}}
        payload = (json.dumps(marker, sort_keys=True, separators=(',', ':')) + '\n').encode('ascii')
        store.create(MARKER, payload)
        _require(store.read(MARKER) == payload, 'stage_content_changed')
        store.sync()
    except BaseException as exc:
        if store is not None:
            try:
                store.cleanup()
            except Exception:
                # Cleanup is best effort; never replace a fixed diagnostic with
                # an OS error containing a private path, or guess at foreign names.
                pass
        if isinstance(exc, Rejected):
            raise Rejected(str(exc)) from None
        if isinstance(exc, Exception):
            raise Rejected('stage_io_failed') from None
        raise
    finally:
        if store is not None:
            store.close()
