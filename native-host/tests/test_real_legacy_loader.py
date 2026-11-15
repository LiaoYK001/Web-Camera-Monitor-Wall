#!/usr/bin/env python3
"""Synthetic stdin-only real-libobs loader contract. Never load a media plugin.

The probe registers its own inert source implementation. This runner never reads
an export, profile or camera address and must never be pointed at a live host.
"""
import argparse
import copy
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import legacy_stage_document as stage
sys.path.pop(0)

PROBE = None
OPTIONS = {'hardware_decode': False, 'connect_timeout_seconds': 10}
SUCCESS = {'schema': 1, 'status': 'passed', 'obsVersion': '32.1.2', 'loads': 2,
           'videoContext': False, 'libraryIdentity': 'runtime-version-checked'}


def fixture(schema=6, rich=True):
    source = {'id': 'synthetic-source-one', 'kind': 'rtsp',
              'name': 'P3 synthetic camera one',
              'rtspUrl': 'rtsp://p3-synthetic.invalid/stream-a',
              'transport': 'tcp', 'muted': False, 'volume': 0.5,
              'syncOffsetMs': -13, 'monitoring': 'off', 'audioTrack': 6,
              'filters': [], 'audioInputs': []}
    item = {'id': 'synthetic-item-one', 'sourceId': source['id'], 'x': -5, 'y': 20,
            'width': 1234, 'height': 321,
            'crop': {'top': 0, 'right': 0, 'bottom': 0, 'left': 0},
            'zIndex': 0, 'visible': False, 'scaleMode': 'contain', 'locked': True}
    data = {'schemaVersion': schema, 'revision': 1, 'id': 'synthetic-scene-one',
            'name': 'P3 synthetic scene',
            'canvas': {'width': 1920, 'height': 1080, 'backgroundColor': '#000000'},
            'sources': [source], 'items': [item]}
    if rich:
        second = copy.deepcopy(source)
        # Deliberately identical input URL but independent source identity.
        second.update(id='synthetic-source-two', name='P3 synthetic camera two',
                      transport='udp', volume=1, muted=True, syncOffsetMs=10000)
        data['sources'].append(second)
        other = copy.deepcopy(item)
        other.update(id='synthetic-item-two', sourceId=second['id'], zIndex=1,
                     x=700, y=-18, width=333, height=777, visible=True, locked=False)
        data['items'].append(other)
        shared = copy.deepcopy(other)
        shared.update(id='synthetic-item-three', sourceId=source['id'], zIndex=2, x=777)
        data['items'].append(shared)
    return data


def packet(data=None, **options):
    original = fixture() if data is None else data
    collection, manifest = stage.build(original, **(options or OPTIONS))
    stage.verify(original, collection, manifest, **(options or OPTIONS))
    return {'collection': collection, 'manifest': manifest}


class RealLegacyLoaderTests(unittest.TestCase):
    def run_probe(self, value=None, *, raw=None):
        encoded = raw if raw is not None else json.dumps(
            value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
        try:
            result = subprocess.run([str(PROBE)], input=encoded, capture_output=True, timeout=8)
        except subprocess.TimeoutExpired:
            self.fail('probe exceeded the fixed runtime limit')
        # Never echo input, raw OBS logs or arbitrary stderr in an assertion.
        try:
            response = json.loads(result.stdout)
        except (ValueError, UnicodeError):
            self.fail('probe did not return the fixed JSON protocol')
        return result.returncode, response, result.stderr

    def assert_success_response(self, code, response, error):
        self.assertTrue(code == 0, 'real loader probe failed')
        self.assertTrue(response == SUCCESS, 'probe success protocol mismatch')
        self.assertTrue(error == b'', 'probe success emitted unexpected diagnostics')

    def assert_passes(self, value):
        self.assert_success_response(*self.run_probe(value))

    def assert_rejected(self, value=None, *, raw=None, before_start=False):
        code, response, error = self.run_probe(value, raw=raw)
        self.assertTrue(code != 0, 'tampered candidate unexpectedly passed')
        valid = (isinstance(response, dict) and
                 set(response) == {'schema', 'status', 'started'} and
                 type(response['schema']) is int and response['schema'] == 1 and
                 response['status'] == 'failed' and type(response['started']) is bool)
        self.assertTrue(valid, 'probe failure protocol mismatch')
        match = re.fullmatch(rb'native_loader_probe_failed:([a-z_]+)\n', error)
        self.assertTrue(match is not None, 'probe failure diagnostics mismatch')
        # A crash, setup failure or teardown defect must not masquerade as a
        # successful semantic tamper rejection.
        allowed = ({b'input', b'input_size', b'shape', b'source_type', b'synthetic_boundary', b'item_transform'}
                   if before_start else
                   {b'shape', b'source_identity', b'source_state', b'source_settings',
                    b'item_order', b'item_identity', b'item_transform', b'item_state',
                    b'scene_canvas', b'id_counter'})
        self.assertTrue(match.group(1) in allowed, 'probe failed outside expected rejection boundary')
        if before_start:
            self.assertTrue(response['started'] is False, 'unsafe input reached OBS startup')

    def test_failure_diagnostics_never_echo_captured_output(self):
        marker = 'synthetic-sensitive-marker'
        cases = [
            subprocess.CompletedProcess([], 1, marker.encode(), b''),
            subprocess.CompletedProcess([], 1, json.dumps({'unexpected': marker}).encode(), marker.encode()),
            subprocess.TimeoutExpired('probe', 8, output=marker.encode(), stderr=marker.encode()),
        ]
        for result in cases:
            options = ({'side_effect': result} if isinstance(result, Exception)
                       else {'return_value': result})
            with mock.patch('subprocess.run', **options), self.assertRaises(AssertionError) as failure:
                self.assert_passes(packet())
            self.assertTrue(marker not in str(failure.exception), 'captured diagnostics leaked')

    def test_supported_schemas_and_reused_source_identity(self):
        for schema in (5, 6):
            for rich in (False, True):
                with self.subTest(schema=schema, rich=rich):
                    self.assert_passes(packet(fixture(schema, rich)))

    def test_unicode_names_and_separate_urls(self):
        data = fixture()
        data['name'] = 'P3 synthetic 场景'
        data['sources'][0]['name'] = 'P3 synthetic 摄像机一'
        data['sources'][1]['name'] = 'P3 synthetic 摄像机二'
        data['sources'][1]['rtspUrl'] = 'rtsp://p3-synthetic.invalid/stream-b'
        self.assert_passes(packet(data))

    def test_integer_zero_and_float_volumes_and_declared_hw_setting(self):
        data = fixture()
        data['sources'][0]['volume'] = 0
        data['sources'][1]['volume'] = 0.375
        self.assert_passes(packet(data, hardware_decode=True, connect_timeout_seconds=3))

    def test_serialized_item_mutations_are_not_accepted_as_expectations(self):
        mutations = {
            'position': lambda item: item['pos'].update(x=item['pos']['x'] + 100),
            'bounds': lambda item: item['bounds'].update(y=item['bounds']['y'] + 100),
            'scale': lambda item: item['scale'].update(x=2.0),
            'visibility': lambda item: item.update(visible=not item['visible']),
            'lock': lambda item: item.update(locked=not item['locked']),
            'alignment': lambda item: item.update(align=0),
            'rotation': lambda item: item.update(rot=90.0),
            'crop': lambda item: item.update(crop_left=20),
            'item_identity': lambda item: item.update(id=item['id'] + 1),
        }
        for name, mutate in mutations.items():
            with self.subTest(field=name):
                value = packet()
                mutate(value['collection']['sources'][-1]['settings']['items'][0])
                self.assert_rejected(value)
        value = packet()
        value['collection']['sources'][-1]['settings']['items'].reverse()
        self.assert_rejected(value)

    def test_serialized_source_mutations_are_not_accepted_as_expectations(self):
        mutations = {
            'mute': lambda src: src.update(muted=not src['muted']),
            'volume': lambda src: src.update(volume=0.25),
            'sync': lambda src: src.update(sync=src['sync'] + 1000000),
            'mixers': lambda src: src.update(mixers=1),
            'monitoring': lambda src: src.update(monitoring_type=1),
            'hardware_setting': lambda src: src['settings'].update(hw_decode=True),
            'transport': lambda src: src['settings'].update(ffmpeg_options='rtsp_transport=udp'),
        }
        for name, mutate in mutations.items():
            with self.subTest(field=name):
                value = packet()
                mutate(value['collection']['sources'][0])
                self.assert_rejected(value)
        value = packet()
        saved = value['collection']['sources'][-1]['settings']['items'][0]
        saved['source_uuid'] = value['collection']['sources'][1]['uuid']
        self.assert_rejected(value)

    def test_scene_neutral_state_mutations(self):
        for field, replacement in {'enabled': False, 'muted': True, 'volume': 0.25,
                                   'sync': 1000000, 'mixers': 1, 'monitoring_type': 1}.items():
            with self.subTest(field=field):
                value = packet()
                value['collection']['sources'][-1][field] = replacement
                self.assert_rejected(value)

    def test_unsafe_serialized_numeric_layout_rejects_before_startup(self):
        for field in ('bounds', 'scale', 'scale_ref'):
            for invalid in (-1, 0, 1e-300, 100000000):
                value = packet()
                value['collection']['sources'][-1]['settings']['items'][0][field]['x'] = invalid
                self.assert_rejected(value, before_start=True)
        for field in ('align', 'bounds_type', 'bounds_align', 'crop_left', 'rot'):
            value = packet()
            value['collection']['sources'][-1]['settings']['items'][0][field] = 2147483647
            self.assert_rejected(value, before_start=True)

    def test_custom_canvas_and_item_counter_mutations(self):
        for field in ('cx', 'cy', 'id_counter'):
            value = packet()
            value['collection']['sources'][-1]['settings'][field] += 1
            self.assert_rejected(value)

    def test_non_synthetic_input_and_plugin_type_reject_before_startup(self):
        for mutate in ('original_url', 'saved_url', 'source_type', 'name'):
            with self.subTest(field=mutate):
                value = packet()
                if mutate == 'original_url':
                    value['manifest']['original']['sources'][0]['rtspUrl'] = 'rtsp://forbidden.invalid/input'
                elif mutate == 'saved_url':
                    value['collection']['sources'][0]['settings']['input'] = 'rtsp://forbidden.invalid/input'
                elif mutate == 'source_type':
                    value['collection']['sources'][0]['id'] = 'browser_source'
                    value['collection']['sources'][0]['versioned_id'] = 'browser_source'
                else:
                    value['collection']['sources'][0]['name'] = 'not a synthetic source'
                self.assert_rejected(value, before_start=True)

    def test_oversized_and_malformed_stdin_reject_before_startup(self):
        for raw in (b'x' * (1024 * 1024 + 1), b'{', b'[]', b'{}'):
            self.assert_rejected(raw=raw, before_start=True)

    def test_binary_stdin_boundary_and_escaped_strings(self):
        data = fixture()
        data['name'] = 'P3 synthetic quote " slash \\ scene'
        encoded = json.dumps(packet(data), ensure_ascii=False,
                             separators=(',', ':')).encode('utf-8')
        limit = 1024 * 1024
        # Exact raw-byte limit, including CRLF, is accepted on every platform.
        padded = encoded + b'\r\n' + b' ' * (limit - len(encoded) - 2)
        code, response, error = self.run_probe(raw=padded)
        self.assert_success_response(code, response, error)
        for raw in (padded + b' ', encoded + b'\x1a' + b'x' * limit,
                    encoded + b'\x00', b'{"collection":{},"collection":{}}'):
            self.assert_rejected(raw=raw, before_start=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe', required=True, type=Path)
    args, remaining = parser.parse_known_args()
    PROBE = args.probe.resolve(strict=True)
    unittest.main(argv=[sys.argv[0], *remaining], verbosity=2)
