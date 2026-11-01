"""PRIVATE, pure in-memory legacy -> pinned OBS 32.1.2 JSON candidate.

This is not an OBS compatibility fixture or an authorization/apply mechanism.
Never pass a candidate to a frontend/media loader as an offline validator.
The caller owns private file handling; neither returned object is public output.

Contract reviewed against the pinned upstream obs.c:2276-2350,2472-2500,
obs-scene.c:1119-1295,1308-1455,2289,4114-4127 and
obs-ffmpeg-source.c:117-128,414-473,784-807. No upstream code is executed.
Names remain verbatim: duplicate raw names INCLUDING the scene are rejected.
Timeout has no faithful legacy-to-media-source mapping and stays UNAPPLIED.
"""
from __future__ import annotations

import hashlib
import json
import math
import uuid

import legacy_import

MAX_COLLECTION_BYTES = 1024 * 1024
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
INT64_MAX = 2**63 - 1
# The lower half of positive int64 reserves ample subsequent allocation headroom.
_ITEM_MASK = 2**62 - 1
_PIN = (32 << 24) | (1 << 16) | 2


def _require(ok):
    if not ok:
        raise legacy_import.Rejected('unsupported_stage_document')


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def _hash(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _snapshot(value, limit):
    """Bound before cloning/encoding; never invoke user objects or repr()."""
    budget = [0, 0]

    def visit(obj, depth):
        _require(depth <= 16)
        budget[0] += 1
        _require(budget[0] <= 30000)
        kind = type(obj)
        if kind is dict:
            _require(len(obj) <= 64)
            result = {}
            for key, child in obj.items():
                _require(type(key) is str and len(key) <= 128)
                budget[1] += len(key.encode('utf-8')) + 4
                result[key] = visit(child, depth + 1)
        elif kind is list:
            _require(len(obj) <= 512)
            result = [visit(child, depth + 1) for child in obj]
        elif kind is str:
            _require(len(obj) <= 8192)
            budget[1] += len(obj.encode('utf-8')) + 2
            result = obj
        elif kind is int:
            _require(-INT64_MAX - 1 <= obj <= INT64_MAX)
            budget[1] += 24
            result = obj
        elif kind is float:
            _require(math.isfinite(obj))
            budget[1] += 32
            result = obj
        else:
            _require(kind in (bool, type(None)))
            budget[1] += 5
            result = obj
        _require(budget[1] <= limit)
        return result

    result = visit(value, 0)
    _require(len(_canonical(result)) <= limit)
    return result


def _input(document, hardware_decode, connect_timeout_seconds):
    _require(type(hardware_decode) is bool)
    _require(type(connect_timeout_seconds) is int and 1 <= connect_timeout_seconds <= 300)
    original = _snapshot(document, legacy_import.MAX_BYTES)
    _require(type(original) is dict and 'scenes' not in original)
    report = legacy_import.plan(original, hardware_decode=hardware_decode,
                                connect_timeout_seconds=connect_timeout_seconds)
    _require(report['status'] == 'candidate')
    _require(1 <= len(original['sources']) <= 64 and 1 <= len(original['items']) <= 256)
    names = [original['name']]
    for source in original['sources']:
        _require(source['kind'] == 'rtsp' and source.get('audioInputs') == []
                 and 'audioInputs' in source and source['monitoring'] == 'off'
                 and source['filters'] == [])
        names.append(source['name'])
    _require(len(names) == len(set(names)))
    for item in original['items']:
        _require(item.get('scaleMode', 'contain') == 'contain'
                 and all(v == 0 for v in item['crop'].values()))
    return original


def _item_id(scene_id, legacy_id):
    native = legacy_import.identity('item', scene_id, legacy_id)['nativeId']
    return (int.from_bytes(hashlib.sha256(uuid.UUID(native).bytes).digest()[:8], 'big')
            & _ITEM_MASK) + 1


def _envelope(name, native_id, kind, settings, *, volume=1.0, muted=False, sync=0):
    # Exactly the pinned obs_save_source envelope; no invented source aliases.
    return {'prev_ver': _PIN, 'name': name, 'uuid': native_id, 'id': kind,
            'versioned_id': kind, 'settings': settings, 'mixers': 0, 'sync': sync,
            'flags': 0, 'volume': volume, 'balance': 0.5, 'enabled': True,
            'muted': muted, 'push-to-mute': False, 'push-to-mute-delay': 0,
            'push-to-talk': False, 'push-to-talk-delay': 0, 'hotkeys': {},
            'deinterlace_mode': 0, 'deinterlace_field_order': 0,
            'monitoring_type': 0, 'private_settings': {}}


def _media_settings(source, hardware_decode):
    # Deliberately disable the source's input-change diagnostics as well; this
    # does NOT make loading a private candidate safe or authorize a connection.
    return {'is_local_file': False, 'input': source['rtspUrl'], 'input_format': '',
            'hw_decode': hardware_decode,
            'ffmpeg_options': 'rtsp_transport=' + source['transport'],
            'looping': False, 'clear_on_media_end': True, 'restart_on_activate': True,
            'linear_alpha': False, 'reconnect_delay_sec': 10, 'buffering_mb': 2,
            'speed_percent': 100, 'log_changes': False, 'close_when_inactive': False,
            'color_range': 0, 'full_decode': False, 'seekable': False}


def _build(original, hardware_decode, timeout):
    scene_identity = legacy_import.identity('scene', original['id'])
    source_map = {}
    mappings = []
    sources = []
    for source in sorted(original['sources'], key=lambda s: s['id']):
        ident = legacy_import.identity('source', original['id'], source['id'])
        _require(ident['nativeId'] not in source_map)
        source_map[ident['nativeId']] = source
        mappings.append({'legacyId': source['id'], **ident})
        sources.append(_envelope(source['name'], ident['nativeId'], 'ffmpeg_source',
                                 _media_settings(source, hardware_decode),
                                 volume=source['volume'], muted=source['muted'],
                                 sync=source['syncOffsetMs'] * 1000000))
    _require(scene_identity['nativeId'] not in source_map)
    by_id = {s['id']: s for s in original['sources']}
    items, item_mappings, used = [], [], set()
    canvas = original['canvas']
    for item in sorted(original['items'], key=lambda i: i['zIndex']):
        ident = legacy_import.identity('item', original['id'], item['id'])
        item_id = _item_id(original['id'], item['id'])
        _require(type(item_id) is int and 0 < item_id < INT64_MAX - 256 and item_id not in used)
        used.add(item_id)
        source = by_id[item['sourceId']]
        source_uuid = legacy_import.identity('source', original['id'], source['id'])['nativeId']
        item_mappings.append({'legacyId': item['id'], **ident, 'obsItemId': item_id,
                              'sourceUuid': source_uuid})
        items.append({'name': source['name'], 'source_uuid': source_uuid,
                      'visible': item['visible'], 'locked': item.get('locked', False),
                      'rot': 0.0, 'scale_ref': {'x': canvas['width'], 'y': canvas['height']},
                      'align': 5, 'bounds_type': 2, 'bounds_align': 0, 'bounds_crop': False,
                      'crop_left': 0, 'crop_top': 0, 'crop_right': 0, 'crop_bottom': 0,
                      'id': item_id, 'group_item_backup': False,
                      'pos': {'x': item['x'], 'y': item['y']}, 'scale': {'x': 1.0, 'y': 1.0},
                      'bounds': {'x': item['width'], 'y': item['height']},
                      'scale_filter': 'disable', 'blend_method': 'default', 'blend_type': 'normal',
                      'show_transition': {'duration': 0}, 'hide_transition': {'duration': 0},
                      'private_settings': {}})
    counter = max(used)
    _require(counter + 256 < INT64_MAX)
    sources.append(_envelope(original['name'], scene_identity['nativeId'], 'scene',
                             {'id_counter': counter, 'custom_size': True,
                              'cx': canvas['width'], 'cy': canvas['height'], 'items': items}))
    collection = {'name': original['name'], 'version': 1, 'sources': sources,
                  'groups': [], 'scene_order': [{'name': original['name']}],
                  'current_scene': original['name'], 'current_program_scene': original['name']}
    manifest = {'schema': 1, 'kind': 'private-native-legacy-stage-candidate',
                'obsVersion': '32.1.2', 'applied': False, 'qualified': False,
                'namePolicy': 'distinct-raw-scene-and-source-names',
                'inputSha256': _hash(original), 'collectionSha256': _hash(collection),
                'original': original, 'scene': {'legacyId': original['id'], **scene_identity},
                'sources': mappings, 'items': item_mappings,
                'runtimeOptions': {'hardwareDecode': hardware_decode, 'connectTimeoutSeconds': timeout},
                'unappliedRequirements': {
                    'globalCanvas': {'width': canvas['width'], 'height': canvas['height'], 'applied': False},
                    'outputDimensions': {'value': None, 'reason': 'not_in_export', 'applied': False},
                    'fps': {'value': None, 'reason': 'not_in_export', 'applied': False},
                    'connectTimeoutSeconds': {'value': timeout, 'reason': 'no_faithful_pinned_mapping', 'applied': False}}}
    return (_snapshot(collection, MAX_COLLECTION_BYTES), _snapshot(manifest, MAX_MANIFEST_BYTES))


def _equal(actual, expected):
    """Type-strict comparison (not Python's True == 1 equivalence)."""
    _require(type(actual) is type(expected))
    if type(expected) is dict:
        _require(actual.keys() == expected.keys())
        for key in expected:
            _equal(actual[key], expected[key])
    elif type(expected) is list:
        _require(len(actual) == len(expected))
        for left, right in zip(actual, expected):
            _equal(left, right)
    else:
        _require(actual == expected)


def _shape(obj, keys):
    _require(type(obj) is dict and set(obj) == set(keys.split()))


def _decode_source(raw):
    """Independent exact-shape decoder, NOT an inverse call into _envelope."""
    _shape(raw, 'prev_ver name uuid id versioned_id settings mixers sync flags volume balance '
           'enabled muted push-to-mute push-to-mute-delay push-to-talk push-to-talk-delay '
           'hotkeys deinterlace_mode deinterlace_field_order monitoring_type private_settings')
    neutral = {'prev_ver': 536936450, 'mixers': 0, 'flags': 0, 'balance': 0.5,
               'enabled': True, 'push-to-mute': False, 'push-to-mute-delay': 0,
               'push-to-talk': False, 'push-to-talk-delay': 0, 'hotkeys': {},
               'deinterlace_mode': 0, 'deinterlace_field_order': 0,
               'monitoring_type': 0, 'private_settings': {}}
    for key, value in neutral.items():
        _equal(raw[key], value)
    _require(type(raw['name']) is str and type(raw['uuid']) is str)
    _require(str(uuid.UUID(raw['uuid'])) == raw['uuid'])
    _require(type(raw['id']) is str and raw['id'] in ('scene', 'ffmpeg_source'))
    _equal(raw['versioned_id'], raw['id'])
    if raw['id'] == 'scene':
        _equal(raw['sync'], 0)
        _equal(raw['volume'], 1.0)
        _equal(raw['muted'], False)
        return None
    settings = raw['settings']
    _shape(settings, 'is_local_file input input_format hw_decode ffmpeg_options looping '
           'clear_on_media_end restart_on_activate linear_alpha reconnect_delay_sec '
           'buffering_mb speed_percent log_changes close_when_inactive color_range full_decode seekable')
    for key, value in {'is_local_file': False, 'input_format': '', 'looping': False,
                       'clear_on_media_end': True, 'restart_on_activate': True,
                       'linear_alpha': False, 'reconnect_delay_sec': 10, 'buffering_mb': 2,
                       'speed_percent': 100, 'log_changes': False, 'close_when_inactive': False,
                       'color_range': 0, 'full_decode': False, 'seekable': False}.items():
        _equal(settings[key], value)
    _require(type(settings['input']) is str and type(settings['hw_decode']) is bool)
    _require(settings['ffmpeg_options'] in ('rtsp_transport=tcp', 'rtsp_transport=udp'))
    _require(type(raw['sync']) is int and raw['sync'] % 1000000 == 0)
    _require(type(raw['muted']) is bool and type(raw['volume']) in (int, float))
    return {'uuid': raw['uuid'], 'name': raw['name'], 'url': settings['input'],
            'transport': settings['ffmpeg_options'][15:], 'hardwareDecode': settings['hw_decode'],
            'muted': raw['muted'], 'volume': raw['volume'], 'syncOffsetMs': raw['sync'] // 1000000}


def _decode_collection(collection):
    _shape(collection, 'name version sources groups scene_order current_scene current_program_scene')
    _equal(collection['version'], 1)
    _equal(collection['groups'], [])
    _require(type(collection['name']) is str)
    _equal(collection['scene_order'], [{'name': collection['name']}])
    _equal(collection['current_scene'], collection['name'])
    _equal(collection['current_program_scene'], collection['name'])
    _require(type(collection['sources']) is list and 2 <= len(collection['sources']) <= 65)
    sources, uuids, names, scene = [], set(), set(), None
    for raw in collection['sources']:
        decoded = _decode_source(raw)
        _require(raw['uuid'] not in uuids and raw['name'] not in names)
        uuids.add(raw['uuid'])
        names.add(raw['name'])
        if decoded is None:
            _require(scene is None)
            scene = raw
        else:
            _require(scene is None)  # emitted source order: input sources, then scene
            sources.append(decoded)
    _require(scene is not None)
    _equal(scene['name'], collection['name'])
    settings = scene['settings']
    _shape(settings, 'id_counter custom_size cx cy items')
    _equal(settings['custom_size'], True)
    _require(type(settings['cx']) is int and type(settings['cy']) is int)
    _require(type(settings['items']) is list and 1 <= len(settings['items']) <= 256)
    source_lookup = {s['uuid']: s for s in sources}
    items, item_ids = [], set()
    for raw in settings['items']:
        _shape(raw, 'name source_uuid visible locked rot scale_ref align bounds_type bounds_align '
               'bounds_crop crop_left crop_top crop_right crop_bottom id group_item_backup '
               'pos scale bounds scale_filter blend_method blend_type show_transition hide_transition private_settings')
        for key, value in {'rot': 0.0, 'align': 5, 'bounds_type': 2, 'bounds_align': 0,
                           'bounds_crop': False, 'crop_left': 0, 'crop_top': 0, 'crop_right': 0,
                           'crop_bottom': 0, 'group_item_backup': False,
                           'scale': {'x': 1.0, 'y': 1.0}, 'scale_filter': 'disable',
                           'blend_method': 'default', 'blend_type': 'normal',
                           'show_transition': {'duration': 0}, 'hide_transition': {'duration': 0},
                           'private_settings': {},
                           'scale_ref': {'x': settings['cx'], 'y': settings['cy']}}.items():
            _equal(raw[key], value)
        _require(type(raw['source_uuid']) is str and raw['source_uuid'] in source_lookup)
        _equal(raw['name'], source_lookup[raw['source_uuid']]['name'])
        _require(type(raw['id']) is int and 0 < raw['id'] < INT64_MAX - 256 and raw['id'] not in item_ids)
        item_ids.add(raw['id'])
        _require(type(raw['visible']) is bool and type(raw['locked']) is bool)
        _shape(raw['pos'], 'x y')
        _shape(raw['bounds'], 'x y')
        _require(all(type(v) is int for v in (*raw['pos'].values(), *raw['bounds'].values())))
        items.append({'obsItemId': raw['id'], 'sourceUuid': raw['source_uuid'],
                      'x': raw['pos']['x'], 'y': raw['pos']['y'],
                      'width': raw['bounds']['x'], 'height': raw['bounds']['y'],
                      'visible': raw['visible'], 'locked': raw['locked']})
    _require(type(settings['id_counter']) is int and settings['id_counter'] == max(item_ids)
             and settings['id_counter'] + 256 < INT64_MAX)
    return {'uuid': scene['uuid'], 'name': scene['name'], 'width': settings['cx'],
            'height': settings['cy'], 'sources': sources, 'items': items}


def _expect_original(original, hardware_decode):
    """Decode original semantics independently of every build-side helper."""
    sources, source_map, mappings = [], {}, []
    for source in sorted(original['sources'], key=lambda s: s['id']):
        ident = legacy_import.identity('source', original['id'], source['id'])
        source_map[source['id']] = ident['nativeId']
        mappings.append({'legacyId': source['id'], **ident})
        sources.append({'uuid': ident['nativeId'], 'name': source['name'], 'url': source['rtspUrl'],
                        'transport': source['transport'], 'hardwareDecode': hardware_decode,
                        'muted': source['muted'], 'volume': source['volume'],
                        'syncOffsetMs': source['syncOffsetMs']})
    items, item_mappings, used = [], [], set()
    for item in sorted(original['items'], key=lambda i: i['zIndex']):
        ident = legacy_import.identity('item', original['id'], item['id'])
        # Independently spell out the int64 derivation, not _item_id().
        digest = hashlib.sha256(bytes.fromhex(ident['nativeId'].replace('-', ''))).digest()
        obs_id = (int(digest[:8].hex(), 16) % (2**62)) + 1
        _require(obs_id not in used)
        used.add(obs_id)
        source_uuid = source_map[item['sourceId']]
        item_mappings.append({'legacyId': item['id'], **ident, 'obsItemId': obs_id, 'sourceUuid': source_uuid})
        items.append({'obsItemId': obs_id, 'sourceUuid': source_uuid,
                      'x': item['x'], 'y': item['y'], 'width': item['width'], 'height': item['height'],
                      'visible': item['visible'], 'locked': item.get('locked', False)})
    scene_ident = legacy_import.identity('scene', original['id'])
    return ({'uuid': scene_ident['nativeId'], 'name': original['name'],
             'width': original['canvas']['width'], 'height': original['canvas']['height'],
             'sources': sources, 'items': items},
            {'legacyId': original['id'], **scene_ident}, mappings, item_mappings)


def _verify(original, collection, manifest, hardware_decode, timeout):
    decoded = _decode_collection(collection)
    expected, scene, sources, items = _expect_original(original, hardware_decode)
    _equal(decoded, expected)
    # This expected manifest is independently assembled from the ORIGINAL, never
    # trusted output metadata. The collection hash alone would not prove semantics.
    expected_manifest = {
        'schema': 1, 'kind': 'private-native-legacy-stage-candidate', 'obsVersion': '32.1.2',
        'applied': False, 'qualified': False, 'namePolicy': 'distinct-raw-scene-and-source-names',
        'inputSha256': hashlib.sha256(_canonical(original)).hexdigest(),
        'collectionSha256': hashlib.sha256(_canonical(collection)).hexdigest(),
        'original': original, 'scene': scene, 'sources': sources, 'items': items,
        'runtimeOptions': {'hardwareDecode': hardware_decode, 'connectTimeoutSeconds': timeout},
        'unappliedRequirements': {
            'globalCanvas': {'width': original['canvas']['width'], 'height': original['canvas']['height'], 'applied': False},
            'outputDimensions': {'value': None, 'reason': 'not_in_export', 'applied': False},
            'fps': {'value': None, 'reason': 'not_in_export', 'applied': False},
            'connectTimeoutSeconds': {'value': timeout, 'reason': 'no_faithful_pinned_mapping', 'applied': False}}}
    _equal(manifest, expected_manifest)


def build(document, *, hardware_decode: bool, connect_timeout_seconds: int) -> tuple[dict, dict]:
    """Return PRIVATE (collection candidate, manifest); perform no I/O or loading.

    Public errors are always Rejected('unsupported_stage_document'). Original
    exports only: the sanitized legacy_import report cannot restore private data.
    """
    try:
        original = _input(document, hardware_decode, connect_timeout_seconds)
        collection, manifest = _build(original, hardware_decode, connect_timeout_seconds)
        _verify(original, collection, manifest, hardware_decode, connect_timeout_seconds)
        return collection, manifest
    except Exception:
        raise legacy_import.Rejected('unsupported_stage_document') from None


def verify(document, collection, manifest, *, hardware_decode: bool, connect_timeout_seconds: int) -> None:
    """Independently compare original semantics, exact output shape and manifest.

    No call to build/_build/_envelope/_media_settings/_item_id is made here.
    All malformed/mutated/unsupported inputs expose only stage_verification_failed.
    """
    try:
        original = _input(document, hardware_decode, connect_timeout_seconds)
        candidate = _snapshot(collection, MAX_COLLECTION_BYTES)
        private_manifest = _snapshot(manifest, MAX_MANIFEST_BYTES)
        _verify(original, candidate, private_manifest, hardware_decode, connect_timeout_seconds)
    except Exception:
        raise legacy_import.Rejected('stage_verification_failed') from None


__all__ = ['build', 'verify']
