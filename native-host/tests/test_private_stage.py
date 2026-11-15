#!/usr/bin/env python3
"""Offline synthetic private-stage tests; no user configuration or network."""
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

MODULE = Path(__file__).resolve().parents[1] / 'scripts' / 'private_stage.py'
spec = importlib.util.spec_from_file_location('private_stage', MODULE)
ps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ps)
BACKEND = ps._Windows if os.name == 'nt' else ps._Posix


class PrivateStageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.destination = self.base / 'new-private'
        self.members = {'collection.json': b'{"private":"synthetic-url"}', 'manifest.json': b'{"schema":1}'}

    def run_stage(self, verify=lambda _: None):
        return ps.stage(self.destination, self.members, verify)

    def rejected(self, operation):
        with self.assertRaises(ps.Rejected) as result:
            operation()
        self.assertRegex(str(result.exception), r'^stage_[a-z_]+$')
        self.assertNotIn(str(self.base), str(result.exception))
        return str(result.exception)

    def assert_incomplete(self):
        self.assertFalse((self.destination / ps.MARKER).exists())

    def test_real_permissions_readback_marker_order_and_private_hashes(self):
        out, err, observed = io.StringIO(), io.StringIO(), []
        def verify(data):
            observed.append(data)
            self.assertEqual(data, self.members)
            self.assertIsNot(data, self.members)
            self.assert_incomplete()
        with redirect_stdout(out), redirect_stderr(err):
            self.assertIsNone(self.run_stage(verify))
        self.assertEqual((out.getvalue(), err.getvalue()), ('', ''))
        self.assertEqual(len(observed), 1)
        marker = json.loads((self.destination / ps.MARKER).read_bytes())
        self.assertEqual(marker['schema'], 1)
        self.assertEqual(marker['kind'], ps.COMPLETION_KIND)
        self.assertEqual(marker['durability'], BACKEND.durability)
        self.assertEqual(set(marker['members']), set(self.members))
        for name, data in self.members.items():
            self.assertEqual((self.destination / name).read_bytes(), data)
            self.assertEqual(marker['members'][name], {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)})
        if os.name != 'nt':
            self.assertEqual(stat.S_IMODE(self.destination.stat().st_mode), 0o700)
            self.assertEqual(self.destination.stat().st_uid, os.geteuid())
            for child in self.destination.iterdir():
                info = child.stat()
                self.assertEqual(stat.S_IMODE(info.st_mode), 0o600)
                self.assertEqual(info.st_uid, os.geteuid())
                self.assertEqual(info.st_nlink, 1)

    def test_existing_file_and_directory_untouched(self):
        for kind in ('file', 'directory'):
            with self.subTest(kind=kind):
                self.destination = self.base / kind
                if kind == 'file':
                    self.destination.write_bytes(b'existing')
                else:
                    self.destination.mkdir()
                    (self.destination / 'keep').write_bytes(b'existing')
                before = self.destination.stat()
                self.rejected(self.run_stage)
                self.assertEqual(self.destination.stat().st_ino, before.st_ino)
                target = self.destination if kind == 'file' else self.destination / 'keep'
                self.assertEqual(target.read_bytes(), b'existing')

    def test_hostile_names_bytes_types_limits_and_no_io(self):
        hostile = ['', '.', '..', '../collection.json', '/collection.json', 'x/collection.json',
                   'x\\collection.json', 'collection.json:ads', 'collection.json ', 'collection.JSON',
                   'completion.json', 'CON.json', '\x00.json', 'unknown.json']
        invalid = [{name: b'x'} for name in hostile]
        invalid += [{}, {'collection.json': 'private'}, {'collection.json': bytearray(b'x')},
                    {'collection.json': memoryview(b'x')}, {'collection.json': None},
                    {'collection.json': b'x' * (ps.MAX_BYTES + 1)},
                    {'collection.json': b'x' * ps.MAX_BYTES, 'manifest.json': b'x'},
                    {'a.json': b'', 'b.json': b'', 'c.json': b'', 'd.json': b''}]
        for members in invalid:
            with self.subTest(keys=list(members)):
                with mock.patch.object(BACKEND, '__init__', side_effect=AssertionError('must not touch filesystem')):
                    self.rejected(lambda: ps.stage(self.destination, members, lambda _: None))
                self.assertFalse(self.destination.exists())

    def test_absolute_new_directory_and_callable_required(self):
        for destination in (Path('relative'), self.base / '..' / 'bad', Path(self.base.anchor), str(self.destination)):
            self.rejected(lambda: ps.stage(destination, self.members, lambda _: None))
        self.rejected(lambda: ps.stage(self.destination, self.members, None))
        self.assertFalse(self.destination.exists())

    def test_windows_path_aliases_rejected_on_every_platform(self):
        from pathlib import PureWindowsPath
        for value in ('C:/normal/new-private', 'd:/Unicode-暂存/new'):
            self.assertTrue(ps._windows_path_safe(PureWindowsPath(value)))
        for value in ('//server/share/new', '//?/C:/new', '//./C:/new', 'C:/new:ads',
                      'C:/CON.json/new', 'C:/NUL/new', 'C:/aux/new', 'C:/LPT9/new',
                      'C:/COM1.json', 'C:/COM¹.json', 'C:/trailing./new', 'C:/space /new', 'C:/a*/new'):
            with self.subTest(value=value):
                self.assertFalse(ps._windows_path_safe(PureWindowsPath(value)))

    def test_windows_owned_handles_close_exactly_once_after_early_cleanup(self):
        # Ownership logic is platform-independent; exercise cleanup-close plus
        # ExitStack replay without requiring or pretending to emulate Win32 ACLs.
        probe = ps._Windows.__new__(ps._Windows)
        probe.handles = {11, 22}
        probe.k = mock.Mock()
        probe.stack = ps.ExitStack()
        probe.stack.callback(probe._close_handle, 11)
        probe.stack.callback(probe._close_handle, 22)
        probe._close_handle(11)
        probe.close()
        probe.close()
        self.assertEqual(probe.k.CloseHandle.call_args_list, [mock.call(11), mock.call(22)])
        self.assertEqual(probe.handles, set())

    def test_cap_boundary_and_zero_length_bytes(self):
        ps.stage(self.destination, {'collection.json': b'x' * ps.MAX_BYTES, 'manifest.json': b''}, lambda _: None)
        self.assertEqual((self.destination / 'collection.json').stat().st_size, ps.MAX_BYTES)
        self.assertEqual((self.destination / 'manifest.json').read_bytes(), b'')

    def test_verify_failure_sanitized_silent_and_clean(self):
        def fail(_):
            raise ValueError('synthetic-url private path ' + str(self.base))
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(self.rejected(lambda: self.run_stage(fail)), 'stage_verification_failed')
        self.assertEqual(out.getvalue() + err.getvalue(), '')
        self.assert_incomplete()
        self.assertFalse(self.destination.exists())

    def test_callback_dict_cannot_mutate_expected_members(self):
        def verify(data):
            data.clear()
            self.members.clear()
        self.run_stage(verify)
        self.assertEqual((self.destination / 'collection.json').read_bytes(), b'{"private":"synthetic-url"}')

    def test_fault_after_every_write_reopen_and_directory_sync(self):
        # Three creates (including completion), five reopens, two namespace syncs.
        for method, count in (('create', 3), ('read', 5), ('sync', 2)):
            original = getattr(BACKEND, method)
            for fail_at in range(1, count + 1):
                for after in (False, True):
                    with self.subTest(method=method, fail_at=fail_at, after=after):
                        self.destination = self.base / f'{method}-{fail_at}-{after}'
                        calls = [0]
                        def fault(store, *args):
                            calls[0] += 1
                            if calls[0] == fail_at and not after:
                                raise OSError('private-path synthetic-url')
                            result = original(store, *args)
                            if calls[0] == fail_at and after:
                                raise OSError('private-path synthetic-url')
                            return result
                        with mock.patch.object(BACKEND, method, fault):
                            self.rejected(self.run_stage)
                        self.assert_incomplete()
                        self.assertFalse(self.destination.exists())

    def test_no_input_reads_and_only_owned_output_reads(self):
        if os.name == 'nt':
            # Win32 implementation uses only its explicit held output names.
            with mock.patch('builtins.open', side_effect=AssertionError('no Python input streams')):
                self.run_stage()
            return
        real_open, real_read = os.open, os.read
        directory_fds, file_fds = set(), set()
        def opened(path, flags, *args, **kwargs):
            fd = real_open(path, flags, *args, **kwargs)
            if flags & os.O_DIRECTORY:
                directory_fds.add(fd)
            else:
                self.assertIn(path, {*self.members, ps.MARKER})
                self.assertIn(kwargs['dir_fd'], directory_fds)
                file_fds.add(fd)
            return fd
        def read(fd, count):
            self.assertIn(fd, file_fds)
            return real_read(fd, count)
        with mock.patch.object(ps.os, 'open', opened), mock.patch.object(ps.os, 'read', read), mock.patch('builtins.open', side_effect=AssertionError('no input streams')):
            self.run_stage()

    def test_foreign_entry_prevents_recursive_cleanup(self):
        def fail(_):
            (self.destination / 'foreign').write_bytes(b'do-not-delete')
            raise RuntimeError('stop')
        self.rejected(lambda: self.run_stage(fail))
        self.assert_incomplete()
        self.assertEqual((self.destination / 'foreign').read_bytes(), b'do-not-delete')
        self.assertEqual(set(p.name for p in self.destination.iterdir()), {'foreign'})

    def test_preexisting_marker_during_callback_not_overwritten(self):
        def verify(_):
            (self.destination / ps.MARKER).write_bytes(b'foreign-not-a-completion')
        self.rejected(lambda: self.run_stage(verify))
        self.assertEqual((self.destination / ps.MARKER).read_bytes(), b'foreign-not-a-completion')

    def test_symlink_ancestor_and_existing_final_symlink(self):
        real = self.base / 'real'
        real.mkdir()
        link = self.base / 'link'
        try:
            link.symlink_to(real, target_is_directory=True)
        except OSError as exc:
            if os.name == 'nt' and getattr(exc, 'winerror', None) == 1314:
                self.skipTest('Windows symlink privilege unavailable; junction test is separate')
            raise
        self.destination = link / 'new'
        self.rejected(self.run_stage)
        self.assertFalse((real / 'new').exists())
        self.destination = link
        self.rejected(self.run_stage)
        self.assertTrue(link.is_symlink())
        self.assertEqual(list(real.iterdir()), [])

    @unittest.skipIf(os.name == 'nt', 'POSIX deterministic replacement races')
    def test_member_symlink_hardlink_and_regular_replacements_never_followed_or_deleted(self):
        for replacement in ('symlink', 'hardlink', 'regular'):
            with self.subTest(replacement=replacement):
                self.destination = self.base / replacement
                target = self.base / ('foreign-' + replacement)
                target.write_bytes(b'foreign-private')
                original = BACKEND.read
                replaced = [False]
                def raced(store, name):
                    if not replaced[0]:
                        replaced[0] = True
                        member = self.destination / name
                        member.unlink()
                        if replacement == 'symlink':
                            member.symlink_to(target)
                        elif replacement == 'hardlink':
                            os.link(target, member)
                        else:
                            member.write_bytes(b'foreign-regular')
                            member.chmod(0o600)
                    return original(store, name)
                with mock.patch.object(BACKEND, 'read', raced):
                    self.rejected(self.run_stage)
                self.assert_incomplete()
                self.assertEqual(target.read_bytes(), b'foreign-private')
                member = self.destination / 'collection.json'
                self.assertTrue(member.exists())
                self.assertEqual(member.read_bytes(), b'foreign-regular' if replacement == 'regular' else b'foreign-private')

    @unittest.skipIf(os.name == 'nt', 'POSIX callback tamper checks; Windows denies concurrent write')
    def test_callback_tamper_hardlink_or_permission_change_fails(self):
        for kind in ('bytes', 'hardlink', 'permissions'):
            with self.subTest(kind=kind):
                self.destination = self.base / ('tamper-' + kind)
                def verify(_):
                    member = self.destination / 'collection.json'
                    if kind == 'bytes':
                        member.write_bytes(b'tamper')
                    elif kind == 'hardlink':
                        os.link(member, self.base / 'outside-link')
                    else:
                        member.chmod(0o644)
                self.rejected(lambda: self.run_stage(verify))
                self.assert_incomplete()

    @unittest.skipIf(os.name == 'nt', 'POSIX root replacement; Windows held root denies rename')
    def test_replaced_root_leaves_foreign_target_untouched(self):
        old = self.base / 'renamed-owned-root'
        def verify(_):
            self.destination.rename(old)
            self.destination.mkdir()
            (self.destination / 'foreign').write_bytes(b'keep')
        self.rejected(lambda: self.run_stage(verify))
        self.assert_incomplete()
        self.assertEqual((self.destination / 'foreign').read_bytes(), b'keep')
        self.assertEqual((old / 'collection.json').read_bytes(), self.members['collection.json'])

    @unittest.skipIf(os.name == 'nt', 'POSIX syscall faults')
    def test_each_actual_file_write_flush_and_short_write(self):
        real_write = os.write
        def short(fd, data):
            return real_write(fd, data[:2])
        with mock.patch.object(ps.os, 'write', short):
            self.run_stage()
        for syscall in ('write', 'fsync'):
            for fail_at in range(1, 8 if syscall == 'fsync' else 4):
                self.destination = self.base / f'fault-{syscall}-{fail_at}'
                original = getattr(os, syscall)
                calls = [0]
                def fault(*args):
                    calls[0] += 1
                    if calls[0] == fail_at:
                        raise OSError('secret')
                    return original(*args)
                with mock.patch.object(ps.os, syscall, fault):
                    self.rejected(self.run_stage)
                self.assert_incomplete()

    def windows_bindings(self, configure):
        # Keep real handles, creation-time descriptors and ACL validation. Only
        # replace selected functions on this instance after ctypes has bound them.
        original = ps._Windows._bind
        def bind(store):
            original(store)
            configure(store)
        return mock.patch.object(ps._Windows, '_bind', bind)

    @unittest.skipUnless(os.name == 'nt', 'actual Windows DACL validation before WriteFile')
    def test_windows_dacl_validation_failure_never_calls_writefile(self):
        for boundary in ('root', 'member'):
            with self.subTest(boundary=boundary):
                self.destination = self.base / ('dacl-' + boundary)
                injected, writes = [], []
                def configure(store):
                    real_control = store.a.GetSecurityDescriptorControl
                    real_write = store.k.WriteFile
                    def control(descriptor, flags, revision):
                        result = real_control(descriptor, flags, revision)
                        if result and not injected and (boundary == 'root' or store.files):
                            # Read the actual descriptor, then make just this
                            # validation observe an unprotected DACL. The real
                            # object remains private, including during cleanup.
                            out = store.c.cast(flags, store.c.POINTER(store.w.WORD))
                            out[0] &= ~0x1000
                            injected.append(True)
                        return result
                    def write(*args):
                        writes.append(True)
                        return real_write(*args)
                    store.a.GetSecurityDescriptorControl = control
                    store.k.WriteFile = write
                verify = mock.Mock()
                with self.windows_bindings(configure):
                    self.assertEqual(self.rejected(lambda: self.run_stage(verify)), 'stage_acl_failed')
                self.assertEqual(injected, [True])
                self.assertEqual(writes, [])
                verify.assert_not_called()
                self.assert_incomplete()
                if boundary == 'member':
                    self.assertFalse(self.destination.exists())
                elif self.destination.exists():
                    # A constructor rejection precedes root_identity ownership;
                    # best-effort cleanup may leave only the empty private root.
                    self.assertEqual({p.name for p in self.destination.iterdir()}, set())

    @unittest.skipUnless(os.name == 'nt', 'actual Windows WriteFile failure and progress checks')
    def test_windows_writefile_failure_and_zero_progress_rejected(self):
        for name in ('collection.json', ps.MARKER):
            for mode in ('failure', 'zero'):
                with self.subTest(member=name, mode=mode):
                    self.destination = self.base / f'write-{name}-{mode}'
                    injected = []
                    def configure(store):
                        real_write = store.k.WriteFile
                        def write(handle, buffer, size, written, overlapped):
                            if not injected and handle == store.files.get(name, (None,))[0]:
                                injected.append(True)
                                store.c.cast(written, store.c.POINTER(store.w.DWORD))[0] = size if mode == 'failure' else 0
                                store.c.set_last_error(29)
                                return mode == 'zero'
                            return real_write(handle, buffer, size, written, overlapped)
                        store.k.WriteFile = write
                    verify = mock.Mock()
                    with self.windows_bindings(configure):
                        self.assertEqual(self.rejected(lambda: self.run_stage(verify)), 'stage_write_failed')
                    self.assertEqual(injected, [True])
                    if name == ps.MARKER:
                        verify.assert_called_once_with(self.members)
                    else:
                        verify.assert_not_called()
                    self.assert_incomplete()
                    self.assertFalse(self.destination.exists())

    @unittest.skipUnless(os.name == 'nt', 'actual Windows WriteFile short writes')
    def test_windows_real_short_writefile_completes_members_and_marker(self):
        calls = []
        def configure(store):
            real_write = store.k.WriteFile
            def write(handle, buffer, size, written, overlapped):
                # Do not fabricate progress: the kernel really writes this
                # prefix and advances its file position on every call.
                result = real_write(handle, buffer, min(size, 3), written, overlapped)
                count = store.c.cast(written, store.c.POINTER(store.w.DWORD))[0]
                calls.append((next(reversed(store.files)), size, count, bool(result)))
                return result
            store.k.WriteFile = write
        verify = mock.Mock()
        with self.windows_bindings(configure):
            self.run_stage(verify)
        verify.assert_called_once_with(self.members)
        for name, data in self.members.items():
            self.assertTrue((self.destination / name).read_bytes() == data, 'short writes must preserve all member bytes')
        marker = json.loads((self.destination / ps.MARKER).read_bytes())
        self.assertEqual(marker['kind'], ps.COMPLETION_KIND)
        self.assertEqual(marker['durability'], ps._Windows.durability)
        self.assertEqual(marker['members'], {
            name: {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
            for name, data in self.members.items()})
        for name in (*self.members, ps.MARKER):
            with self.subTest(member=name):
                writes = [call for call in calls if call[0] == name]
                self.assertGreater(len(writes), 1)
                self.assertTrue(all(ok and 0 < count <= min(size, 3) for _, size, count, ok in writes))
                self.assertTrue(any(count < size for _, size, count, _ in writes))

    @unittest.skipUnless(os.name == 'nt', 'actual Windows ReadFile failure and premature EOF')
    def test_windows_readfile_failure_and_early_zero_rejected(self):
        for boundary in ('member', 'marker'):
            for mode in ('failure', 'early-zero'):
                with self.subTest(boundary=boundary, mode=mode):
                    self.destination = self.base / f'read-{boundary}-{mode}'
                    injected, prefixes = [], []
                    def configure(store):
                        real_read = store.k.ReadFile
                        def read(handle, buffer, size, count, overlapped):
                            # The first readback is a member; the only readback
                            # after marker creation is the marker itself.
                            target = (ps.MARKER in store.files) == (boundary == 'marker')
                            if target and not injected:
                                out = store.c.cast(count, store.c.POINTER(store.w.DWORD))
                                if mode == 'early-zero' and not prefixes:
                                    result = real_read(handle, buffer, min(size, 3), count, overlapped)
                                    prefixes.append((bool(result), out[0]))
                                    return result
                                out[0] = 0
                                store.c.set_last_error(30)
                                injected.append(True)
                                return mode == 'early-zero'
                            return real_read(handle, buffer, size, count, overlapped)
                        store.k.ReadFile = read
                    verify = mock.Mock()
                    with self.windows_bindings(configure):
                        expected = 'stage_read_failed' if mode == 'failure' else 'stage_content_changed'
                        self.assertEqual(self.rejected(lambda: self.run_stage(verify)), expected)
                    self.assertEqual(injected, [True])
                    self.assertEqual(prefixes, [(True, 3)] if mode == 'early-zero' else [])
                    if boundary == 'marker':
                        verify.assert_called_once_with(self.members)
                    else:
                        verify.assert_not_called()
                    self.assert_incomplete()
                    self.assertFalse(self.destination.exists())

    @unittest.skipUnless(os.name == 'nt', 'actual Windows file and directory FlushFileBuffers boundaries')
    def test_windows_flushfilebuffers_file_failures_and_directory_error_policy(self):
        cases = [('collection.json', 5, 1), (ps.MARKER, 5, 1),
                 ('root', 5, None), ('parent', 5, None)]
        cases += [(directory, 1117, fail_at) for directory in ('root', 'parent') for fail_at in (1, 2)]
        for boundary, error, fail_at in cases:
            with self.subTest(boundary=boundary, error=error, fail_at=fail_at):
                self.destination = self.base / f'flush-{boundary}-{error}-{fail_at}'
                calls, injected = [], []
                def configure(store):
                    real_flush = store.k.FlushFileBuffers
                    def flush(handle):
                        target = (store.root if boundary == 'root' else store.parent if boundary == 'parent'
                                  else store.files.get(boundary, (None,))[0])
                        if handle == target:
                            calls.append(True)
                            if fail_at is None or len(calls) == fail_at:
                                injected.append(True)
                                store.c.set_last_error(error)
                                return False
                        return real_flush(handle)
                    store.k.FlushFileBuffers = flush
                verify = mock.Mock()
                with self.windows_bindings(configure):
                    if fail_at is None:
                        self.run_stage(verify)
                    else:
                        self.assertEqual(self.rejected(lambda: self.run_stage(verify)), 'stage_flush_failed')
                self.assertEqual(len(calls), 2 if fail_at is None else fail_at)
                self.assertEqual(len(injected), 2 if fail_at is None else 1)
                if boundary == 'collection.json':
                    verify.assert_not_called()
                else:
                    verify.assert_called_once_with(self.members)
                if fail_at is None:
                    marker = json.loads((self.destination / ps.MARKER).read_bytes())
                    self.assertEqual(marker['kind'], ps.COMPLETION_KIND)
                    self.assertEqual(marker['durability'], ps._Windows.durability)
                    for name, data in self.members.items():
                        self.assertTrue((self.destination / name).read_bytes() == data,
                                        'allowed directory flush error must preserve members')
                else:
                    self.assert_incomplete()
                    self.assertFalse(self.destination.exists())

    @unittest.skipUnless(os.name == 'nt', 'actual Windows failed handle-disposition cleanup')
    def test_windows_cleanup_failure_leaves_only_private_partial_member(self):
        import ctypes as c
        from ctypes import wintypes as w
        prefixes, failed_writes, deletes = [], [], []
        foreign = self.base / 'foreign-keep'
        foreign.write_bytes(b'do-not-delete')
        def configure(store):
            real_write = store.k.WriteFile
            def write(handle, buffer, size, written, overlapped):
                if not prefixes:
                    result = real_write(handle, buffer, min(size, 3), written, overlapped)
                    count = c.cast(written, c.POINTER(w.DWORD))[0]
                    prefixes.append((bool(result), count))
                    return result
                if not failed_writes:
                    c.cast(written, c.POINTER(w.DWORD))[0] = 0
                    c.set_last_error(29)
                    failed_writes.append(True)
                    return False
                return real_write(handle, buffer, size, written, overlapped)
            def disposition(handle, kind, buffer, size):
                deletes.append(('root' if handle == store.root else 'member', kind,
                                bool(c.cast(buffer, c.POINTER(w.BOOL))[0]), size))
                c.set_last_error(5)
                return False
            store.k.WriteFile = write
            store.k.SetFileInformationByHandle = disposition
        verify = mock.Mock()
        with self.windows_bindings(configure):
            self.assertEqual(self.rejected(lambda: self.run_stage(verify)), 'stage_write_failed')
        self.assertEqual(prefixes, [(True, 3)])
        self.assertEqual(failed_writes, [True])
        self.assertEqual(deletes, [('member', 4, True, c.sizeof(w.BOOL)), ('root', 4, True, c.sizeof(w.BOOL))])
        verify.assert_not_called()
        self.assert_incomplete()
        self.assertEqual({p.name for p in self.destination.iterdir()}, {'collection.json'})
        self.assertTrue((self.destination / 'collection.json').read_bytes() == self.members['collection.json'][:3],
                        'failed cleanup must retain only the actual short-written prefix')
        self.assertTrue(foreign.read_bytes() == b'do-not-delete', 'foreign sibling must remain unchanged')
        # All injected functions are now gone. Reopen the real leftovers and
        # independently exercise the actual owner/protected-DACL verifier.
        probe = ps._Windows.__new__(ps._Windows)
        probe.c, probe.w, probe.stack, probe.handles = c, w, ps.ExitStack(), set()
        probe.k, probe.a = c.WinDLL('kernel32', use_last_error=True), c.WinDLL('advapi32', use_last_error=True)
        try:
            probe._bind()
            probe._security()
            probe._info(probe._open(self.destination, directory=True), directory=True, private=True)
            probe._info(probe._open(self.destination / 'collection.json'), private=True)
        finally:
            probe.close()

    @unittest.skipUnless(os.name == 'nt', 'actual Windows owner/DACL and sharing checks')
    def test_windows_real_protected_owner_dacl_and_rename_write_denial(self):
        import ctypes as c
        from ctypes import wintypes as w
        def verify(_):
            with self.assertRaises(OSError):
                self.destination.rename(self.base / 'renamed')
            with self.assertRaises(OSError):
                (self.destination / 'collection.json').write_bytes(b'tamper')
        self.run_stage(verify)
        probe = ps._Windows.__new__(ps._Windows)
        probe.c, probe.w = c, w
        probe.stack = ps.ExitStack()
        probe.handles = set()
        probe.k, probe.a = c.WinDLL('kernel32', use_last_error=True), c.WinDLL('advapi32', use_last_error=True)
        probe._bind()
        probe._security()
        convert = probe.a.ConvertSecurityDescriptorToStringSecurityDescriptorW
        convert.argtypes = [c.c_void_p, w.DWORD, w.DWORD, c.c_void_p, c.c_void_p]
        convert.restype = w.BOOL
        try:
            for path in (self.destination, *self.destination.iterdir()):
                handle = probe._open(path, directory=path == self.destination)
                probe._info(handle, directory=path == self.destination, private=True)
                descriptor, owner, acl = c.c_void_p(), c.c_void_p(), c.c_void_p()
                self.assertEqual(probe.a.GetSecurityInfo(handle, 1, 5, c.byref(owner), None, c.byref(acl), None, c.byref(descriptor)), 0)
                text = w.LPWSTR()
                try:
                    self.assertTrue(convert(descriptor, 1, 5, c.byref(text), None))
                    self.assertIn('D:P', text.value)
                    self.assertEqual(text.value.count('('), 1)
                    self.assertIn('(A;;FA;;;', text.value)
                finally:
                    if text:
                        probe.k.LocalFree(c.cast(text, c.c_void_p))
                    probe.k.LocalFree(descriptor)
        finally:
            probe.stack.close()

    @unittest.skipUnless(os.name == 'nt', 'native Windows junction without ACL shell')
    def test_windows_junction_ancestor_refused(self):
        import ctypes as c
        from ctypes import wintypes as w
        real, junction = self.base / 'real-junction', self.base / 'junction'
        real.mkdir()
        junction.mkdir()
        kernel = c.WinDLL('kernel32', use_last_error=True)
        create = kernel.CreateFileW
        create.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, c.c_void_p, w.DWORD, w.DWORD, w.HANDLE]
        create.restype = w.HANDLE
        close = kernel.CloseHandle
        close.argtypes, close.restype = [w.HANDLE], w.BOOL
        ioctl = kernel.DeviceIoControl
        ioctl.argtypes = [w.HANDLE, w.DWORD, c.c_void_p, w.DWORD, c.c_void_p, w.DWORD, c.c_void_p, c.c_void_p]
        ioctl.restype = w.BOOL
        handle = create(str(junction), 0x40000000, 0, None, 3, 0x02200000, None)
        self.assertNotEqual(handle, c.c_void_p(-1).value)
        substitute = ('\\??\\' + str(real)).encode('utf-16le')
        printable = str(real).encode('utf-16le')
        paths = substitute + b'\0\0' + printable + b'\0\0'
        import struct
        data = struct.pack('<IHHHHHH', 0xA0000003, 8 + len(paths), 0, 0, len(substitute), len(substitute) + 2, len(printable)) + paths
        buffer, returned = c.create_string_buffer(data), w.DWORD()
        try:
            self.assertTrue(ioctl(handle, 0x900A4, buffer, len(data), None, 0, c.byref(returned), None))
        finally:
            close(handle)
        self.addCleanup(lambda: junction.rmdir() if junction.exists() else None)
        self.destination = junction / 'new'
        self.rejected(self.run_stage)
        self.assertFalse((real / 'new').exists())


if __name__ == '__main__':
    unittest.main()
