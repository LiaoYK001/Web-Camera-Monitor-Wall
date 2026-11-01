#!/usr/bin/env python3
"""Private synthetic staging only: no actual profile, OBS host or network."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import legacy_stage as stage
import legacy_import as legacy

fixture_spec = importlib.util.spec_from_file_location('legacy_test_fixture', Path(__file__).with_name('test_legacy_import.py'))
fixture = importlib.util.module_from_spec(fixture_spec)
fixture_spec.loader.exec_module(fixture)


def document():
    value = fixture.scene()
    value['sources'][0]['audioInputs'] = []
    return value


class LegacyStageTests(unittest.TestCase):
    def paths(self, root):
        exports, config, output = root / 'exports', root / 'existing-config', root / 'staging'
        for path in (exports, config, output):
            path.mkdir()
        source = exports / 'explicit.json'
        source.write_text(json.dumps(document()), encoding='utf-8')
        marker = config / 'do-not-touch.json'
        marker.write_bytes(b'EXISTING_CONFIG_MUST_NOT_CHANGE')
        return source, config, output / 'candidate'

    def run_stage(self, source, config, destination, **extra):
        options = dict(existing_config_roots=[config], hardware_decode=False,
                       connect_timeout_seconds=10)
        options.update(extra)
        return stage.run(source, destination, **options)

    def test_private_candidate_readback_without_input_or_existing_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            source, config, target = self.paths(Path(directory))
            before = source.read_bytes()
            receipt = self.run_stage(source, config, target)
            self.assertEqual(receipt, {'status': 'staged', 'kind': 'native-legacy-offline-private-candidate',
                                      'applied': False, 'qualified': False, 'liveHostLoaded': False})
            self.assertEqual(before, source.read_bytes())
            self.assertEqual((config / 'do-not-touch.json').read_bytes(), b'EXISTING_CONFIG_MUST_NOT_CHANGE')
            self.assertEqual({p.name for p in target.iterdir()}, {'collection.json', 'manifest.json', 'completion.json'})
            collection = stage.decode_member((target / 'collection.json').read_bytes())
            manifest = stage.decode_member((target / 'manifest.json').read_bytes())
            stage.document_stage.verify(document(), collection, manifest, hardware_decode=False,
                                        connect_timeout_seconds=10)
            self.assertIn(document()['sources'][0]['rtspUrl'], json.dumps(collection))
            public = json.dumps(receipt)
            for secret in ('PRIVATE_', 'camera.invalid', 'fixture-password', str(source), str(target), hashlib.sha256(before).hexdigest()):
                self.assertNotIn(secret, public)
            if os.name != 'nt':
                self.assertEqual(target.stat().st_mode & 0o777, 0o700)
                for path in target.iterdir():
                    self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_existing_destination_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            source, config, target = self.paths(Path(directory))
            self.run_stage(source, config, target)
            before = {p.name: p.read_bytes() for p in target.iterdir()}
            with self.assertRaises((ValueError, OSError)):
                self.run_stage(source, config, target)
            self.assertEqual({p.name: p.read_bytes() for p in target.iterdir()}, before)

    def test_explicit_exclusions_and_export_tree_fail_before_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            source, config, target = self.paths(Path(directory))
            for destination, roots in ((source.parent / 'new', [config]), (config / 'new', [config]), (target, [])):
                with self.subTest(destination=destination):
                    with self.assertRaises(legacy.Rejected):
                        self.run_stage(source, config, destination, existing_config_roots=roots)
                    self.assertFalse(destination.exists())

    def assert_alias_rejected(self, forbidden_selector):
        with tempfile.TemporaryDirectory() as directory:
            source, config, target = self.paths(Path(directory))
            actual_identity = stage.directory_identity
            forbidden = forbidden_selector(source, config)
            def aliased_identity(path):
                return actual_identity(forbidden if path == target.parent else path)
            with mock.patch.object(stage, 'directory_identity', side_effect=aliased_identity):
                with mock.patch.object(stage.private_stage, 'stage') as writer:
                    with self.assertRaises(legacy.Rejected):
                        self.run_stage(source, config, target)
                    writer.assert_not_called()
            self.assertFalse(target.exists())

    def test_input_directory_alias_identity_rejected_before_writer(self):
        self.assert_alias_rejected(lambda source, config: source.parent)

    def test_configuration_alias_identity_rejected_before_writer(self):
        self.assert_alias_rejected(lambda source, config: config)

    def test_location_guards_live_through_transaction_and_failure_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            source, config, target = self.paths(Path(directory))
            guard, active = legacy.guarded_parent, set()
            @contextlib.contextmanager
            def tracked(path):
                with guard(path) as handle:
                    active.add(path)
                    try:
                        yield handle
                    finally:
                        active.remove(path)
            def writer(*args):
                for root in (source.parent, config, target.parent):
                    self.assertIn(root / 'native-stage-exclusion-sentinel', active)
                raise stage.private_stage.Rejected('injected')
            with mock.patch.object(legacy, 'guarded_parent', tracked):
                with mock.patch.object(stage.private_stage, 'stage', side_effect=writer):
                    with self.assertRaises(stage.private_stage.Rejected):
                        self.run_stage(source, config, target)
            self.assertFalse(active)
            self.assertFalse(target.exists())

    @unittest.skipUnless(os.name == 'nt', 'actual Windows DOS directory aliases')
    def test_windows_dos_drive_alias_rejects_input_and_configuration_trees(self):
        import ctypes as c
        from ctypes import wintypes as w
        kernel = c.WinDLL('kernel32', use_last_error=True)
        query = kernel.QueryDosDeviceW
        query.argtypes, query.restype = [w.LPCWSTR, w.LPWSTR, w.DWORD], w.DWORD
        define = kernel.DefineDosDeviceW
        define.argtypes, define.restype = [w.DWORD, w.LPCWSTR, w.LPCWSTR], w.BOOL
        buffer = c.create_unicode_buffer(32768)
        available = None
        for letter in 'ZYXWVUTSRQP':
            drive = letter + ':'
            if not query(drive, buffer, len(buffer)) and c.get_last_error() == 2:
                available = drive
                break
        self.assertIsNotNone(available, 'an unused test-only DOS drive is required')
        with tempfile.TemporaryDirectory() as directory:
            source, config, target = self.paths(Path(directory))
            for root in (source.parent, config):
                raw_target = '\\??\\' + str(root)
                self.assertTrue(define(9, available, raw_target))
                try:
                    alias_target = Path(available + '\\') / 'alias-candidate'
                    self.assertEqual(stage.directory_identity(alias_target.parent), stage.directory_identity(root))
                    with mock.patch.object(stage.private_stage, 'stage') as writer:
                        with self.assertRaises(legacy.Rejected):
                            self.run_stage(source, config, alias_target)
                        writer.assert_not_called()
                    self.assertFalse(alias_target.exists())
                finally:
                    self.assertTrue(define(15, available, raw_target))
            self.assertEqual((config / 'do-not-touch.json').read_bytes(), b'EXISTING_CONFIG_MUST_NOT_CHANGE')

    def test_unsupported_semantics_never_create_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            source, config, target = self.paths(Path(directory))
            value = document()
            del value['sources'][0]['audioInputs']
            source.write_text(json.dumps(value), encoding='utf-8')
            with self.assertRaises(legacy.Rejected):
                self.run_stage(source, config, target)
            self.assertFalse(target.exists())

    def test_readback_must_use_independent_verifier_and_unchanged_original(self):
        with tempfile.TemporaryDirectory() as directory:
            source, config, target = self.paths(Path(directory))
            captured = []
            def transaction(destination, members, verify):
                damaged = dict(members)
                damaged['collection.json'] = b'{"PRIVATE_FAULT":true}'
                with self.assertRaises(legacy.Rejected):
                    verify(damaged)
                verify(dict(members))
                captured.append(True)
            with mock.patch.object(stage.private_stage, 'stage', side_effect=transaction):
                self.run_stage(source, config, target)
            self.assertEqual(captured, [True])
            self.assertFalse(target.exists())

    def test_rejected_cli_does_not_echo_private_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            source, config, target = self.paths(Path(directory))
            command = [sys.executable, '-B', str(SCRIPTS / 'legacy_stage.py'), '--input', str(source),
                       '--destination', str(target), '--existing-config-root', str(config),
                       '--hardware-decode', 'off', '--connect-timeout-seconds', '10']
            result = subprocess.run(command + ['--apply', 'PRIVATE_CLI_SECRET'], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 2)
            self.assertNotIn('PRIVATE_CLI_SECRET', result.stdout + result.stderr)
            self.assertNotIn(str(source), result.stdout + result.stderr)
            self.assertFalse(target.exists())
            value = document()
            value['sources'][0]['audioInputs'] = [{'track': 0, 'gain': 1, 'muted': False, 'syncOffsetMs': 0}]
            source.write_text(json.dumps(value), encoding='utf-8')
            result = subprocess.run(command, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 2)
            receipt = json.loads(result.stdout)
            self.assertFalse(receipt['applied'])
            self.assertNotIn('PRIVATE_', result.stdout + result.stderr)
            self.assertNotIn(str(source), result.stdout + result.stderr)
            self.assertFalse(target.exists())

    def test_duplicate_nonfinite_and_extra_readback_keys_reject(self):
        for payload in (b'{"a":1,"a":2}', b'{"a":NaN}', b'null\0', b'\xff'):
            with self.assertRaises(legacy.Rejected):
                stage.decode_member(payload)


if __name__ == '__main__':
    unittest.main(verbosity=2)
