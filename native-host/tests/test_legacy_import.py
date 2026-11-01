#!/usr/bin/env python3
"""Synthetic exported JSON only: no real profiles, cameras, services or credentials."""
import copy
from contextlib import redirect_stdout
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

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/legacy_import.py'
spec = importlib.util.spec_from_file_location('legacy_import', SCRIPT)
legacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy)
OPTIONS = {'hardware_decode': False, 'connect_timeout_seconds': 10}


def scene(schema=6):
    return {'schemaVersion': schema, 'revision': 1, 'id': 'private-scene', 'name': 'PRIVATE_DISPLAY_NAME',
            'canvas': {'width': 1920, 'height': 1080, 'backgroundColor': '#000000'},
            'sources': [{'id': 'private-source', 'kind': 'rtsp', 'name': 'PRIVATE_CAMERA_NAME',
                         'rtspUrl': 'rtsp://secret-user:secret-password@camera.invalid/private-channel?secret=query',
                         'transport': 'tcp', 'muted': True, 'volume': 0.5, 'syncOffsetMs': 13,
                         'monitoring': 'off', 'audioTrack': 2, 'filters': []}],
            'items': [{'id': 'private-item', 'sourceId': 'private-source', 'x': 0, 'y': 0,
                       'width': 640, 'height': 360, 'crop': dict(top=0, right=0, bottom=0, left=0),
                       'zIndex': 0, 'visible': True, 'scaleMode': 'contain', 'locked': True}]}


class LegacyImportTests(unittest.TestCase):
    def test_schema_five_six_and_safe_public_projection(self):
        for version in (5, 6):
            report = legacy.plan(scene(version), **OPTIONS)
            self.assertEqual(report['status'], 'candidate')
            self.assertFalse(report['applied'])
            self.assertFalse(report['qualified'])
            encoded = json.dumps(report)
            for secret in ('PRIVATE_DISPLAY_NAME', 'PRIVATE_CAMERA_NAME', 'private-scene',
                           'private-source', 'private-item', 'secret-user', 'secret-password',
                           'camera.invalid', 'private-channel', 'secret=query'):
                self.assertNotIn(secret, encoded)
            mapped = report['scenes'][0]['sources'][0]
            self.assertEqual(mapped['outputAudioBus'], 2)
            self.assertEqual(mapped['audioSelection'], 'legacy')
            self.assertEqual(mapped['syncOffsetMs'], 13)
            self.assertEqual(report['scenes'][0]['items'][0]['sourceId'], mapped['nativeId'])

    def test_identity_is_not_url_or_name_or_layer_order(self):
        data = scene()
        original = legacy.plan(data, **OPTIONS)['scenes'][0]['sources'][0]['nativeId']
        data['name'] = 'renamed'
        data['sources'][0]['name'] = 'renamed camera'
        data['sources'][0]['rtspUrl'] = 'rtsp://other.invalid/changed'
        self.assertEqual(original, legacy.plan(data, **OPTIONS)['scenes'][0]['sources'][0]['nativeId'])
        second = copy.deepcopy(data['sources'][0])
        second['id'] = 'second-source'
        data['sources'].append(second)
        report = legacy.plan(data, **OPTIONS)
        self.assertNotEqual(*[s['nativeId'] for s in report['scenes'][0]['sources']])
        data['sources'].reverse()
        again = legacy.plan(data, **OPTIONS)
        self.assertEqual({s['nativeId'] for s in report['scenes'][0]['sources']},
                         {s['nativeId'] for s in again['scenes'][0]['sources']})

    def test_runtime_decode_and_timeout_are_not_invented(self):
        report = legacy.plan(scene())
        self.assertEqual(report['status'], 'blocked')
        self.assertIn('runtime_options_not_confirmed', report['blockers'])
        for value in (0, -1, 301, True, '10'):
            with self.assertRaises(legacy.Rejected):
                legacy.plan(scene(), hardware_decode=False, connect_timeout_seconds=value)

    def test_explicit_audio_requires_gateway_but_empty_means_silence(self):
        data = scene()
        data['sources'][0]['audioInputs'] = []
        report = legacy.plan(data, **OPTIONS)
        self.assertEqual(report['status'], 'candidate')
        self.assertEqual(report['scenes'][0]['sources'][0]['audioSelection'], 'silent')
        data['sources'][0]['audioInputs'] = [{'track': 0, 'gain': 1.0, 'muted': False, 'syncOffsetMs': 0}]
        report = legacy.plan(data, **OPTIONS)
        self.assertIn('explicit_audio_inputs_require_gateway', report['blockers'])
        self.assertFalse(report['scenes'][0]['sources'][0]['candidate'])
        data['sources'][0]['audioInputs'] *= 2
        with self.assertRaises(legacy.Rejected):
            legacy.plan(data, **OPTIONS)

    def test_filters_unsupported_kinds_and_advanced_items_are_blocked(self):
        for change, code in (
            (lambda d: d['sources'][0].update(filters=[{'enabled': False, 'value': 'PRIVATE_FILTER'}]), 'filters_require_adapter'),
            (lambda d: d['sources'][0].update(kind='camera', cameraId='PRIVATE_REGISTRY_ID'), 'non_rtsp_source_requires_adapter'),
            (lambda d: d['items'][0].update(rotation=90), 'advanced_item_requires_adapter'),
        ):
            data = scene()
            change(data)
            report = legacy.plan(data, **OPTIONS)
            self.assertEqual(report['status'], 'blocked')
            self.assertIn(code, report['blockers'])
            self.assertNotIn('PRIVATE_FILTER', json.dumps(report))
            self.assertNotIn('PRIVATE_REGISTRY_ID', json.dumps(report))

    def test_invalid_references_types_unknown_fields_and_bounds_reject(self):
        mutations = (
            lambda d: d.update(schemaVersion=True),
            lambda d: d.update(password='PRIVATE_UNKNOWN_VALUE'),
            lambda d: d['sources'][0].update(extra='PRIVATE_UNKNOWN_VALUE'),
            lambda d: d['sources'].append(copy.deepcopy(d['sources'][0])),
            lambda d: d['items'][0].update(sourceId='missing'),
            lambda d: d['items'][0].update(zIndex=1),
            lambda d: d['items'][0].update(visible=1),
            lambda d: d['canvas'].update(width=1919),
            lambda d: d['sources'][0].update(rtspUrl='https://camera.invalid/'),
            lambda d: d['sources'][0].update(volume=float('nan')),
            lambda d: d['sources'][0].update(muted=1),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                data = scene()
                mutate(data)
                with self.assertRaises(legacy.Rejected):
                    legacy.plan(data, **OPTIONS)

    def test_studio_scopes_and_program_preview_are_preserved_without_take(self):
        first, second = scene(), scene(5)
        second['id'] = 'second-scene'
        data = {'schemaVersion': 1, 'revision': 3, 'programSceneId': first['id'],
                'previewSceneId': second['id'], 'transition': {'kind': 'fade', 'durationMs': 300},
                'scenes': [first, second]}
        report = legacy.plan(data, **OPTIONS)
        self.assertEqual(report['status'], 'candidate')
        self.assertEqual(report['selection']['programSceneId'], report['scenes'][0]['nativeId'])
        self.assertNotEqual(report['scenes'][0]['sources'][0]['nativeId'], report['scenes'][1]['sources'][0]['nativeId'])
        data['previewSceneId'] = 'missing'
        with self.assertRaises(legacy.Rejected):
            legacy.plan(data, **OPTIONS)

    def setup_paths(self, root):
        exports, reports = root / 'exports', root / 'reports'
        exports.mkdir()
        reports.mkdir()
        source = exports / 'scene.json'
        source.write_text(json.dumps(scene()), encoding='utf-8')
        return source, reports / 'report.json'

    def test_read_only_input_and_exclusive_external_report(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = self.setup_paths(Path(directory))
            source.chmod(0o400)
            before = source.read_bytes()
            report = legacy.run(source, output, **OPTIONS)
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(json.loads(output.read_text()), report)
            with self.assertRaises(FileExistsError):
                legacy.run(source, output, **OPTIONS)
            with self.assertRaises(legacy.Rejected):
                legacy.run(source, source.parent / 'forbidden.json', **OPTIONS)
            source.chmod(0o600)

    def test_bad_json_duplicate_nonfinite_large_and_directory_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = self.setup_paths(Path(directory))
            for data in (b'{"schemaVersion":6,"schemaVersion":5}', b'{"value":NaN}', b'[]', b'x' * (legacy.MAX_BYTES + 1)):
                source.write_bytes(data)
                with self.assertRaises(legacy.Rejected):
                    legacy.run(source, output, **OPTIONS)
                self.assertFalse(output.exists())
            with self.assertRaises(legacy.Rejected):
                legacy.run(source.parent, output, **OPTIONS)

    def test_symlink_and_hardlink_inputs_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = self.setup_paths(Path(directory))
            linked = source.parent / 'linked.json'
            try:
                os.link(source, linked)
            except OSError:
                self.skipTest('Hardlink creation unavailable on this filesystem')
            with self.assertRaises(legacy.Rejected):
                legacy.run(linked, output, **OPTIONS)
            linked.unlink()
            try:
                linked.symlink_to(source)
            except OSError:
                self.skipTest('Symlink creation requires unavailable Windows privilege')
            with self.assertRaises((legacy.Rejected, OSError)):
                legacy.run(linked, output, **OPTIONS)

    @unittest.skipUnless(os.name == 'nt', 'Windows kernel handle contract')
    def test_windows_final_open_never_follows_reparse_before_stream_conversion(self):
        import ctypes
        import msvcrt
        kernel = mock.Mock()
        kernel.CreateFileW.return_value = 1234
        kernel.GetFileType.return_value = 1

        def reparse_information(handle, pointer):
            pointer._obj.attributes = 0x400
            pointer._obj.links = 1
            return True

        kernel.GetFileInformationByHandle.side_effect = reparse_information
        with mock.patch.object(ctypes, 'WinDLL', return_value=kernel), mock.patch.object(msvcrt, 'open_osfhandle') as convert:
            with self.assertRaises(legacy.Rejected):
                legacy.windows_read_descriptor(Path('C:/exports/input.json'))
            args = kernel.CreateFileW.call_args.args
            self.assertEqual(args[5] & 0x00200000, 0x00200000, 'Final open must carry FILE_FLAG_OPEN_REPARSE_POINT')
            self.assertEqual(args[2], 1, 'Input handle may share reads only')
            convert.assert_not_called()
            kernel.CloseHandle.assert_called_once_with(1234)

    def test_final_component_replacement_is_not_followed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = self.setup_paths(root)
            outside = root / 'outside'
            outside.mkdir()
            target = outside / 'secret.json'
            target.write_text(json.dumps(scene()), encoding='utf-8')
            called = []

            def replace_final():
                called.append(True)
                source.unlink()
                if os.name == 'nt':
                    made = subprocess.run(['cmd', '/c', 'mklink', '/J', str(source), str(outside)], capture_output=True)
                    self.assertEqual(made.returncode, 0, 'Temporary Windows junction fixture creation failed')
                else:
                    source.symlink_to(target)

            native_open = legacy.windows_read_descriptor
            posix_open = os.open

            def raced_windows(path):
                replace_final()
                return native_open(path)

            def raced_posix(path, flags, *args, **kwargs):
                if path == source.name:
                    replace_final()
                return posix_open(path, flags, *args, **kwargs)

            patcher = mock.patch.object(legacy, 'windows_read_descriptor', side_effect=raced_windows) if os.name == 'nt' else mock.patch.object(legacy.os, 'open', side_effect=raced_posix)
            try:
                with patcher:
                    with self.assertRaises((legacy.Rejected, OSError)):
                        legacy.run(source, output, **OPTIONS)
                self.assertEqual(called, [True])
                self.assertFalse(output.exists())
                self.assertEqual(json.loads(target.read_text()), scene())
            finally:
                if os.name == 'nt' and source.is_dir():
                    source.rmdir()

    def test_ancestor_links_and_existing_link_reports_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = self.setup_paths(root)
            alias = root / 'alias'
            if os.name == 'nt':
                made = subprocess.run(['cmd', '/c', 'mklink', '/J', str(alias), str(source.parent)], capture_output=True)
                self.assertEqual(made.returncode, 0, 'Temporary Windows junction fixture creation failed')
            else:
                alias.symlink_to(source.parent, target_is_directory=True)
            try:
                with self.assertRaises((legacy.Rejected, OSError)):
                    legacy.run(alias / source.name, output, **OPTIONS)
            finally:
                if os.name == 'nt':
                    alias.rmdir()
                else:
                    alias.unlink()
            sentinel = output.parent / 'existing.json'
            sentinel.write_text('do not overwrite', encoding='utf-8')
            try:
                output.symlink_to(sentinel)
            except OSError:
                # Windows symlink permission is separate from junction handling.
                output.write_text('existing report', encoding='utf-8')
            with self.assertRaises(FileExistsError):
                legacy.run(source, output, **OPTIONS)
            self.assertEqual(sentinel.read_text(), 'do not overwrite')

    def test_cli_redacts_errors_and_never_accepts_apply(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = self.setup_paths(Path(directory))
            source.write_text('{"private":"SECRET_BROKEN_VALUE",', encoding='utf-8')
            completed = subprocess.run([sys.executable, '-B', str(SCRIPT), '--input', str(source), '--report', str(output)], capture_output=True, text=True)
            self.assertEqual(completed.returncode, 2)
            self.assertNotIn('SECRET_BROKEN_VALUE', completed.stdout + completed.stderr)
            self.assertNotIn(str(source), completed.stdout + completed.stderr)
            self.assertFalse(output.exists())
            stream = io.StringIO()
            source.write_text(json.dumps(scene()), encoding='utf-8')
            with redirect_stdout(stream):
                result = legacy.main(['--input', str(source), '--report', str(output)])
            self.assertEqual(result, 4)
            self.assertNotIn('secret-password', stream.getvalue())
            self.assertEqual(json.loads(output.read_text())['status'], 'blocked')
            for extra in (['--apply', 'SECRET_NOT_ECHOED'], ['--hardware-decode', 'SECRET_NOT_ECHOED']):
                completed = subprocess.run([sys.executable, '-B', str(SCRIPT), '--input', str(source), '--report', str(output), *extra], capture_output=True, text=True)
                self.assertEqual(completed.returncode, 2)
                self.assertNotIn('SECRET_NOT_ECHOED', completed.stdout + completed.stderr)
                self.assertNotIn(str(source), completed.stdout + completed.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
