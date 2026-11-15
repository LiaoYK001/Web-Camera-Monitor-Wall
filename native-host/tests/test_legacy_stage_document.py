#!/usr/bin/env python3
"""Synthetic private document tests only; no OBS, media, files or network loading.

The delegated implementation author does not run this suite; the parent owns
execution. Test URLs are assembled to avoid plaintext userinfo in source scans.
"""
import copy
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest import mock
import uuid

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import legacy_import as legacy
import legacy_stage_document as stage
sys.path.pop(0)

OPTIONS = {'hardware_decode': False, 'connect_timeout_seconds': 10}


def scene(schema=6):
    url = 'rtsp://' + 'synthetic-user' + ':' + 'synthetic-password' + '@' + 'camera.invalid/channel?token=synthetic'
    return {'schemaVersion': schema, 'revision': 1, 'id': 'scene-one', 'name': 'Private Scene',
            'canvas': {'width': 1920, 'height': 1080, 'backgroundColor': '#000000'},
            'sources': [{'id': 'source-one', 'kind': 'rtsp', 'name': 'Private Camera',
                         'rtspUrl': url, 'transport': 'tcp', 'muted': False, 'volume': 0.5,
                         'syncOffsetMs': -13, 'monitoring': 'off', 'audioTrack': 6,
                         'filters': [], 'audioInputs': []}],
            'items': [{'id': 'item-one', 'sourceId': 'source-one', 'x': -5, 'y': 20,
                       'width': 640, 'height': 360,
                       'crop': {'top': 0, 'right': 0, 'bottom': 0, 'left': 0},
                       'zIndex': 0, 'visible': False, 'scaleMode': 'contain', 'locked': True}]}


def rich_scene():
    data = scene()
    second = copy.deepcopy(data['sources'][0])
    second.update(id='source-two', name='Second Camera', transport='udp', volume=1, muted=True, syncOffsetMs=10000)
    data['sources'].append(second)  # same URL, different identity: must never merge
    item = copy.deepcopy(data['items'][0])
    item.update(id='item-two', sourceId='source-two', zIndex=1, visible=True, locked=False)
    data['items'].append(item)
    item = copy.deepcopy(item)
    item.update(id='item-three', sourceId='source-one', zIndex=2, x=777)
    data['items'].append(item)  # explicitly shared source
    return data


def canonical_hash(value):
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False,
                         separators=(',', ':'), allow_nan=False).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def locations(value, prefix=()):
    yield prefix, value
    if type(value) is dict:
        for key, child in value.items():
            yield from locations(child, prefix + (key,))
    elif type(value) is list:
        for index, child in enumerate(value):
            yield from locations(child, prefix + (index,))


def parent_at(root, path):
    result = root
    for key in path[:-1]:
        result = result[key]
    return result


def changed_leaf(value):
    if type(value) is bool:
        return not value
    if type(value) is int:
        return value + 1
    if type(value) is float:
        return value + 0.25
    if type(value) is str:
        return value + '-tampered'
    return 'tampered-null'


class LegacyStageDocumentTests(unittest.TestCase):
    def rejected_build(self, data, **options):
        with self.assertRaises(legacy.Rejected) as caught:
            stage.build(data, **(options or OPTIONS))
        self.assertEqual(str(caught.exception), 'unsupported_stage_document')
        self.assertIsNone(caught.exception.__cause__)

    def rejected_verify(self, data, collection, manifest, **options):
        with self.assertRaises(legacy.Rejected) as caught:
            stage.verify(data, collection, manifest, **(options or OPTIONS))
        self.assertEqual(str(caught.exception), 'stage_verification_failed')
        self.assertIsNone(caught.exception.__cause__)

    def test_private_pinned_shape_and_explicit_silence(self):
        for schema in (5, 6):
            data = scene(schema)
            before = copy.deepcopy(data)
            collection, manifest = stage.build(data, **OPTIONS)
            self.assertIsNone(stage.verify(data, collection, manifest, **OPTIONS))
            self.assertTrue(data == before)
            self.assertEqual(collection['version'], 1)
            self.assertNotIn('resolution', collection)
            media, saved_scene = collection['sources']
            self.assertEqual(media['prev_ver'], (32 << 24) | (1 << 16) | 2)
            self.assertEqual(media['id'], 'ffmpeg_source')
            self.assertEqual(media['versioned_id'], 'ffmpeg_source')
            self.assertTrue(media['settings']['input'] == data['sources'][0]['rtspUrl'])
            self.assertTrue(media['name'] == data['sources'][0]['name'])
            self.assertEqual(media['mixers'], 0)
            self.assertEqual(media['monitoring_type'], 0)
            self.assertFalse(media['muted'])  # silence is NOT faked by muting/volume zero
            self.assertEqual(media['volume'], 0.5)
            self.assertEqual(media['sync'], -13000000)
            self.assertEqual(media['settings']['ffmpeg_options'], 'rtsp_transport=tcp')
            self.assertFalse(media['settings']['log_changes'])
            self.assertNotIn('timeout', media['settings']['ffmpeg_options'])
            self.assertTrue(saved_scene['settings']['custom_size'])
            self.assertEqual(saved_scene['settings']['cx'], 1920)
            self.assertEqual(saved_scene['settings']['cy'], 1080)
            saved_item = saved_scene['settings']['items'][0]
            self.assertEqual(saved_item['source_uuid'], media['uuid'])
            self.assertTrue(saved_item['name'] == media['name'])
            self.assertFalse(saved_item['visible'])
            self.assertTrue(saved_item['locked'])
            self.assertEqual(saved_item['align'], 5)
            self.assertEqual(saved_item['bounds_type'], 2)
            self.assertEqual(saved_item['bounds_align'], 0)
            self.assertEqual(saved_item['pos'], {'x': -5, 'y': 20})
            self.assertEqual(saved_item['bounds'], {'x': 640, 'y': 360})
            self.assertGreater(saved_item['id'], 0)
            self.assertLess(saved_item['id'] + 256, 2**63 - 1)
            self.assertEqual(saved_scene['settings']['id_counter'], saved_item['id'])
            self.assertTrue(manifest['original'] == data)
            self.assertEqual(manifest['inputSha256'], canonical_hash(data))
            self.assertEqual(manifest['collectionSha256'], canonical_hash(collection))
            self.assertFalse(manifest['applied'])
            self.assertFalse(manifest['qualified'])
            for requirement in manifest['unappliedRequirements'].values():
                self.assertFalse(requirement['applied'])
            self.assertIsNone(manifest['unappliedRequirements']['fps']['value'])
            self.assertIsNone(manifest['unappliedRequirements']['outputDimensions']['value'])
            self.assertEqual(manifest['unappliedRequirements']['connectTimeoutSeconds']['value'], 10)
            # No references to input mutable containers survive the build.
            data['sources'][0]['name'] = 'Later input edit'
            self.assertTrue(manifest['original'] == before)

    def test_unicode_hashes_and_int_float_volume_preserve_private_originals(self):
        for value in (0, 1, 0.0, 1.0, 0.125):
            data = scene()
            data['name'] = '私密场景 😀'
            data['sources'][0].update(name='私密相机 é', volume=value, muted=True)
            data['sources'][0]['rtspUrl'] += '&label=私密'
            collection, manifest = stage.build(data, hardware_decode=True, connect_timeout_seconds=1)
            stage.verify(data, collection, manifest, hardware_decode=True, connect_timeout_seconds=1)
            source = collection['sources'][0]
            self.assertIs(type(source['volume']), type(value))
            self.assertEqual(source['volume'], value)
            self.assertTrue(source['muted'])
            self.assertEqual(source['mixers'], 0)
            self.assertEqual(source['monitoring_type'], 0)
            self.assertEqual(manifest['inputSha256'], canonical_hash(data))
            self.assertEqual(manifest['collectionSha256'], canonical_hash(collection))
            self.assertTrue(manifest['original'] == data)
            changed = copy.deepcopy(manifest)
            changed['original']['sources'][0]['rtspUrl'] += '-changed'
            changed['inputSha256'] = canonical_hash(changed['original'])
            self.rejected_verify(data, collection, changed, hardware_decode=True, connect_timeout_seconds=1)

    def test_same_url_different_ids_shared_source_and_reorder(self):
        data = rich_scene()
        collection, manifest = stage.build(data, **OPTIONS)
        inputs = collection['sources'][:-1]
        self.assertEqual(len(inputs), 2)
        self.assertNotEqual(inputs[0]['uuid'], inputs[1]['uuid'])
        self.assertTrue(inputs[0]['settings']['input'] == inputs[1]['settings']['input'])
        items = collection['sources'][-1]['settings']['items']
        self.assertEqual(items[0]['source_uuid'], items[2]['source_uuid'])
        self.assertNotEqual(items[0]['id'], items[2]['id'])
        identities = {m['legacyId']: m['obsItemId'] for m in manifest['items']}
        data['sources'].reverse()
        data['items'].reverse()
        reordered, mapping = stage.build(data, **OPTIONS)
        self.assertTrue(reordered == collection)
        self.assertTrue(identities == {m['legacyId']: m['obsItemId'] for m in mapping['items']})
        for index, item in enumerate(data['items']):
            item['zIndex'] = index
        for index, source in enumerate(data['sources']):
            source['name'] = 'Renamed ' + str(index)
            source['rtspUrl'] = 'rtsp://' + 'changed.invalid/stream-' + str(index)
        data['name'] = 'Renamed scene'
        changed, changed_manifest = stage.build(data, **OPTIONS)
        self.assertTrue(identities == {m['legacyId']: m['obsItemId'] for m in changed_manifest['items']})
        self.assertTrue({s['uuid'] for s in changed['sources']} == {s['uuid'] for s in collection['sources']})
        stage.verify(data, changed, changed_manifest, **OPTIONS)

    def test_reject_name_ambiguity_including_scene(self):
        data = rich_scene()
        data['sources'][1]['name'] = data['sources'][0]['name']
        self.rejected_build(data)
        data = scene()
        data['sources'][0]['name'] = data['name']
        self.rejected_build(data)

    def test_unsupported_semantics_absence_and_unknown_fields(self):
        edits = [
            lambda d: d['sources'][0].pop('audioInputs'),
            lambda d: d['sources'][0].update(audioInputs=[{'track': 0, 'gain': 1, 'muted': False, 'syncOffsetMs': 0}]),
            lambda d: d['sources'][0].update(monitoring='monitor-only'),
            lambda d: d['sources'][0].pop('monitoring'),
            lambda d: d['sources'][0].update(filters=[{}]),
            lambda d: d['sources'][0].update(kind='browser'),
            lambda d: d['sources'][0].update(unrecognized=True),
            lambda d: d['canvas'].update(backgroundColor='#010000'),
            lambda d: d['items'][0].update(scaleMode='cover'),
            lambda d: d['items'][0].update(scaleMode='stretch'),
            lambda d: d['items'][0]['crop'].update(top=1),
            lambda d: d['items'][0].update(rotation=1),
            lambda d: d['items'][0].update(opacity=0.9),
            lambda d: d['items'][0].update(blendMode='add'),
            lambda d: d['items'][0].update(groupId='group'),
            lambda d: d['items'][0].update(transform={}),
            lambda d: d.update(studio=True),
            lambda d: d.update(sources=[]),
            lambda d: d.update(items=[]),
            lambda d: d['items'][0].update(sourceId='missing'),
            lambda d: d['items'][0].update(zIndex=1),
        ]
        for index, edit in enumerate(edits):
            with self.subTest(case=index):
                data = scene()
                edit(data)
                self.rejected_build(data)
        self.rejected_build({'schemaVersion': 1, 'revision': 1, 'scenes': [scene()]})
        self.rejected_build(legacy.plan(scene(), **OPTIONS))

    def test_bounds_and_runtime_options(self):
        for key, value in [('hardware_decode', None), ('hardware_decode', 0),
                           ('connect_timeout_seconds', 0), ('connect_timeout_seconds', 301),
                           ('connect_timeout_seconds', True), ('connect_timeout_seconds', '10')]:
            opts = dict(OPTIONS)
            opts[key] = value
            self.rejected_build(scene(), **opts)
        data = scene()
        data['canvas'].update(width=8192, height=16)
        data['items'][0].update(x=-32768, y=32768, width=8192, height=1)
        stage.build(data, hardware_decode=True, connect_timeout_seconds=300)
        for edit in [lambda d: d['canvas'].update(width=8193),
                     lambda d: d['items'][0].update(x=-32769),
                     lambda d: d['items'][0].update(width=8193),
                     lambda d: d['sources'][0].update(volume=float('nan')),
                     lambda d: d['sources'][0].update(volume=float('inf')),
                     lambda d: d['sources'][0].update(rtspUrl='x' * 2049)]:
            data = scene()
            edit(data)
            self.rejected_build(data)
        data = scene()
        base_source, base_item = data['sources'][0], data['items'][0]
        data['sources'] = []
        data['items'] = []
        for index in range(64):
            source = copy.deepcopy(base_source)
            source.update(id='source-' + str(index), name='Source ' + str(index))
            data['sources'].append(source)
        for index in range(256):
            item = copy.deepcopy(base_item)
            item.update(id='item-' + str(index), sourceId='source-' + str(index % 64), zIndex=index)
            data['items'].append(item)
        candidate, manifest = stage.build(data, **OPTIONS)
        stage.verify(data, candidate, manifest, **OPTIONS)
        data['sources'].append(copy.deepcopy(base_source))
        self.rejected_build(data)
        data['sources'].pop()
        data['items'].append(copy.deepcopy(base_item))
        self.rejected_build(data)
        cyclic = scene()
        cyclic['cycle'] = cyclic
        self.rejected_build(cyclic)
        huge = scene()
        huge['unknown'] = [None] * 513
        self.rejected_build(huge)
        self.rejected_build({'oversized': 'x' * (stage.MAX_COLLECTION_BYTES + 1)})

    def test_positive_ids_collisions_and_counter_headroom(self):
        for bad_id in (0, -1, 2**63 - 1, 2**63 - 257, True):
            with mock.patch.object(stage, '_item_id', return_value=bad_id):
                self.rejected_build(scene())
        with mock.patch.object(stage, '_item_id', return_value=123):
            self.rejected_build(rich_scene())
        data = scene()
        candidate, manifest = stage.build(data, **OPTIONS)
        expected_uuid = legacy.identity('item', data['id'], data['items'][0]['id'])['nativeId']
        independent_id = (int.from_bytes(hashlib.sha256(uuid.UUID(expected_uuid).bytes).digest()[:8], 'big')
                          & (2**62 - 1)) + 1
        self.assertEqual(candidate['sources'][-1]['settings']['items'][0]['id'], independent_id)
        for field in ('id', 'id_counter'):
            for bad in (0, -1, True, 2**63 - 1):
                changed = copy.deepcopy(candidate)
                settings = changed['sources'][-1]['settings']
                if field == 'id':
                    settings['items'][0]['id'] = bad
                else:
                    settings['id_counter'] = bad
                forged = copy.deepcopy(manifest)
                forged['collectionSha256'] = canonical_hash(changed)
                self.rejected_verify(data, changed, forged)

    def test_source_uuid_is_mandatory_and_companion_name_is_not_fallback(self):
        data = rich_scene()
        collection, manifest = stage.build(data, **OPTIONS)
        for change in ('missing', 'unknown', 'other', 'name', 'duplicate-source-uuid'):
            candidate = copy.deepcopy(collection)
            saved = candidate['sources'][-1]['settings']['items'][0]
            if change == 'missing':
                del saved['source_uuid']
            elif change == 'unknown':
                saved['source_uuid'] = str(uuid.UUID(int=0))
            elif change == 'other':
                saved['source_uuid'] = candidate['sources'][1]['uuid']
            elif change == 'name':
                saved['name'] = candidate['sources'][1]['name']
            else:
                candidate['sources'][1]['uuid'] = candidate['sources'][0]['uuid']
            forged = copy.deepcopy(manifest)
            forged['collectionSha256'] = canonical_hash(candidate)
            self.rejected_verify(data, candidate, forged)

    def test_independent_verifier_does_not_call_builder_helpers(self):
        data = rich_scene()
        collection, manifest = stage.build(data, **OPTIONS)
        with mock.patch.object(stage, 'build', side_effect=AssertionError), \
             mock.patch.object(stage, '_build', side_effect=AssertionError), \
             mock.patch.object(stage, '_envelope', side_effect=AssertionError), \
             mock.patch.object(stage, '_media_settings', side_effect=AssertionError), \
             mock.patch.object(stage, '_item_id', side_effect=AssertionError):
            stage.verify(data, collection, manifest, **OPTIONS)
        settings = stage._media_settings

        def corrupt_settings(source, hardware_decode):
            result = settings(source, hardware_decode)
            result['hw_decode'] = not hardware_decode
            return result

        with mock.patch.object(stage, '_media_settings', side_effect=corrupt_settings):
            self.rejected_build(data)  # build self-checks independent semantics

    def test_every_output_leaf_change_key_deletion_and_addition_is_rejected(self):
        data = scene()
        collection, manifest = stage.build(data, **OPTIONS)
        # Forge the hash after every collection mutation so hash-only checking
        # cannot pass this test. Private manifest mutations also include original
        # names/URL, full identity mappings, hashes and every requirements field.
        for target_name, base in [('collection', collection), ('manifest', manifest)]:
            for path, value in locations(base):
                operations = []
                if path:
                    operations.append('delete')
                if type(value) in (dict, list):
                    operations.append('add')
                else:
                    operations.append('change')
                for operation in operations:
                    with self.subTest(target=target_name, path=path, operation=operation):
                        changed = copy.deepcopy(base)
                        if operation == 'delete':
                            del parent_at(changed, path)[path[-1]]
                        elif operation == 'change':
                            parent_at(changed, path)[path[-1]] = changed_leaf(value)
                        else:
                            container = changed
                            for key in path:
                                container = container[key]
                            if type(value) is dict:
                                container['unexpected'] = True
                            else:
                                container.append(None)
                        candidate = changed if target_name == 'collection' else copy.deepcopy(collection)
                        forged = changed if target_name == 'manifest' else copy.deepcopy(manifest)
                        if target_name == 'collection':
                            forged['collectionSha256'] = canonical_hash(candidate)
                        self.rejected_verify(data, candidate, forged)

    def test_reject_type_confusion_oversized_output_and_changed_original(self):
        data = scene()
        collection, manifest = stage.build(data, **OPTIONS)
        for target in (None, [], {'sources': [None] * 513}, {'large': 'x' * 9000}):
            self.rejected_verify(data, target, manifest)
            self.rejected_verify(data, collection, target)
        for field, value in [('version', True), ('version', 1.0)]:
            changed = copy.deepcopy(collection)
            changed[field] = value
            self.rejected_verify(data, changed, manifest)
        edits = [lambda d: d.update(name='Changed'),
                 lambda d: d['sources'][0].update(rtspUrl='rtsp://' + 'other.invalid/changed'),
                 lambda d: d['sources'][0].update(audioTrack=1),
                 lambda d: d['items'][0].update(visible=True),
                 lambda d: d.update(revision=2)]
        for edit in edits:
            changed = copy.deepcopy(data)
            edit(changed)
            self.rejected_verify(changed, collection, manifest)
        self.rejected_verify(data, collection, manifest, hardware_decode=True, connect_timeout_seconds=10)
        self.rejected_verify(data, collection, manifest, hardware_decode=False, connect_timeout_seconds=11)

    def test_no_private_stdout_stderr_or_raw_public_errors(self):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            data = scene()
            candidate, manifest = stage.build(data, **OPTIONS)
            stage.verify(data, candidate, manifest, **OPTIONS)
            self.rejected_build({'bad': object()})
            self.rejected_verify(data, {'bad': object()}, manifest)
            with mock.patch.object(stage.legacy_import, 'plan', side_effect=RuntimeError('private-detail')):
                self.rejected_build(data)
                self.rejected_verify(data, candidate, manifest)
        self.assertEqual(output.getvalue(), '')
        self.assertEqual(errors.getvalue(), '')


if __name__ == '__main__':
    unittest.main()
