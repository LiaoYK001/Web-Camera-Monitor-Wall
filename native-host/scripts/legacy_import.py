#!/usr/bin/env python3
"""Conservative, read-only planning of explicitly exported legacy scene JSON.

No network, profile/DB discovery, OBS writes, credential extraction or apply mode.
Only plain RTSP scenes are positive candidates; all other semantics block apply.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager, ExitStack
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import uuid
from urllib.parse import urlsplit

MAX_BYTES = 1024 * 1024
NAMESPACE = uuid.UUID('a70d5858-331c-4f19-b551-71a16bd5f7e0')
ID = re.compile(r'[A-Za-z0-9._-]{1,64}\Z', re.ASCII)
COLOR = re.compile(r'#[0-9A-Fa-f]{6}\Z', re.ASCII)


class Rejected(ValueError):
    """Contains a fixed public diagnostic code, never input content."""


def require(ok, code='invalid_export'):
    if not ok:
        raise Rejected(code)


def integer(value, low, high):
    return type(value) is int and low <= value <= high


def number(value, low, high):
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high


def text(value, limit, empty=False):
    return isinstance(value, str) and (empty or bool(value)) and len(value.encode('utf-8')) <= limit and not any(ord(c) < 32 for c in value)


def fields(obj, allowed, required=None):
    require(type(obj) is dict and set(obj) <= set(allowed), 'unsupported_or_invalid_fields')
    require(set(required or allowed) <= set(obj), 'missing_fields')


def identity(kind, *parts):
    # Identity derives only from immutable namespace + legacy IDs, never URL/name.
    framed = json.dumps([kind, *parts], ensure_ascii=True, separators=(',', ':'))
    digest = hashlib.sha256(framed.encode()).hexdigest()
    return {'legacyIdentityHash': digest, 'nativeId': str(uuid.uuid5(NAMESPACE, framed))}


def unique_ids(entries):
    ids = [entry.get('id') for entry in entries if type(entry) is dict]
    require(len(ids) == len(entries) and all(isinstance(i, str) and ID.fullmatch(i) for i in ids))
    require(len(ids) == len(set(ids)), 'duplicate_identity')
    return set(ids)


def plan_scene(scene, options):
    fields(scene, ('schemaVersion', 'revision', 'id', 'name', 'canvas', 'sources', 'items'))
    require(integer(scene['schemaVersion'], 5, 6) and integer(scene['revision'], 0, 2**63-1))
    require(isinstance(scene['id'], str) and ID.fullmatch(scene['id']) and text(scene['name'], 128))
    canvas = scene['canvas']
    fields(canvas, ('width', 'height', 'backgroundColor'))
    require(all(integer(canvas[k], 16, 8192) and canvas[k] % 2 == 0 for k in ('width', 'height')))
    require(isinstance(canvas['backgroundColor'], str) and COLOR.fullmatch(canvas['backgroundColor']))
    require(type(scene['sources']) is list and len(scene['sources']) <= 64)
    require(type(scene['items']) is list and len(scene['items']) <= 256)
    source_ids = unique_ids(scene['sources'])
    unique_ids(scene['items'])
    blockers = set()
    if options['hardwareDecode'] is None or options['connectTimeoutSeconds'] is None:
        blockers.add('runtime_options_not_confirmed')
    if canvas['backgroundColor'].lower() != '#000000':
        blockers.add('canvas_background_requires_adapter')
    mapped_sources = []
    common = {'id', 'kind', 'name', 'muted', 'volume', 'syncOffsetMs', 'monitoring', 'audioTrack', 'filters'}
    for source in scene['sources']:
        require(text(source.get('kind'), 16) and text(source.get('name'), 128))
        entry = identity('source', scene['id'], source['id'])
        entry['sceneId'] = identity('scene', scene['id'])['nativeId']
        if source['kind'] != 'rtsp':
            # Do not interpret/echo unsupported browser, registry, media or nested data.
            blockers.add('non_rtsp_source_requires_adapter')
            entry['candidate'] = False
            mapped_sources.append(entry)
            continue
        fields(source, common | {'rtspUrl', 'transport', 'audioInputs'}, common | {'rtspUrl', 'transport'})
        require(type(source['muted']) is bool and number(source['volume'], 0, 1))
        require(integer(source['syncOffsetMs'], -10000, 10000) and integer(source['audioTrack'], 1, 6))
        require(source['monitoring'] in ('off', 'monitor-only', 'monitor-and-output'))
        require(source['transport'] in ('tcp', 'udp') and text(source['rtspUrl'], 2048))
        try:
            url = urlsplit(source['rtspUrl'])
            require(url.scheme == 'rtsp' and bool(url.hostname) and not url.fragment and not any(c.isspace() for c in source['rtspUrl']))
            require(url.port is None or 1 <= url.port <= 65535)
        except ValueError:
            raise Rejected('invalid_rtsp_source') from None
        require(type(source['filters']) is list and len(source['filters']) <= 16)
        if source['filters']:
            blockers.add('filters_require_adapter')
        audio = source.get('audioInputs')
        if 'audioInputs' in source:
            require(type(audio) is list and len(audio) <= 8)
            tracks = []
            for track in audio:
                fields(track, ('track', 'gain', 'muted', 'syncOffsetMs'))
                require(integer(track['track'], 0, 31) and number(track['gain'], 0, 1))
                require(type(track['muted']) is bool and integer(track['syncOffsetMs'], -10000, 10000))
                tracks.append(track['track'])
            require(len(tracks) == len(set(tracks)))
            if audio:
                blockers.add('explicit_audio_inputs_require_gateway')
        entry.update(candidate=not source['filters'] and not audio,
                     transport=source['transport'], outputAudioBus=source['audioTrack'],
                     audioSelection='silent' if audio == [] else 'explicit' if audio is not None else 'legacy',
                     muted=source['muted'], volume=source['volume'], syncOffsetMs=source['syncOffsetMs'],
                     monitoring=source['monitoring'])
        mapped_sources.append(entry)
    mapped_items = []
    indexes = []
    required = {'id', 'sourceId', 'x', 'y', 'width', 'height', 'crop', 'zIndex', 'visible'}
    optional = {'scaleMode', 'locked', 'groupId', 'rotation', 'opacity', 'blendMode'}
    for item in scene['items']:
        fields(item, required | optional, required)
        require(item['sourceId'] in source_ids, 'missing_source_reference')
        require(all(integer(item[k], -32768, 32768) for k in ('x', 'y')))
        require(all(integer(item[k], 1, 8192) for k in ('width', 'height')))
        require(integer(item['zIndex'], 0, 255) and type(item['visible']) is bool)
        fields(item['crop'], ('top', 'right', 'bottom', 'left'))
        require(all(integer(v, 0, 8192) for v in item['crop'].values()))
        require(item.get('scaleMode', 'contain') in ('contain', 'cover', 'stretch'))
        require(type(item.get('locked', False)) is bool)
        require(text(item.get('groupId', ''), 64, empty=True))
        require(number(item.get('rotation', 0), -360, 360) and number(item.get('opacity', 1), 0, 1))
        require(item.get('blendMode', 'normal') in ('normal', 'add', 'multiply', 'screen'))
        if item.get('groupId') or item.get('rotation', 0) != 0 or item.get('opacity', 1) != 1 or item.get('blendMode', 'normal') != 'normal':
            blockers.add('advanced_item_requires_adapter')
        entry = identity('item', scene['id'], item['id'])
        entry.update(sourceId=identity('source', scene['id'], item['sourceId'])['nativeId'])
        for key in ('x', 'y', 'width', 'height', 'zIndex', 'visible', 'crop'):
            entry[key] = item[key]
        entry['scaleMode'] = item.get('scaleMode', 'contain')
        entry['locked'] = item.get('locked', False)
        mapped_items.append(entry)
        indexes.append(item['zIndex'])
    require(sorted(indexes) == list(range(len(indexes))), 'invalid_layer_order')
    return {**identity('scene', scene['id']), 'schemaVersion': scene['schemaVersion'],
            'canvas': dict(canvas), 'sources': mapped_sources, 'items': mapped_items,
            'blockers': sorted(blockers)}


def plan(document, *, hardware_decode=None, connect_timeout_seconds=None):
    require(hardware_decode is None or type(hardware_decode) is bool, 'invalid_runtime_options')
    require(connect_timeout_seconds is None or integer(connect_timeout_seconds, 1, 300), 'invalid_runtime_options')
    options = {'hardwareDecode': hardware_decode, 'connectTimeoutSeconds': connect_timeout_seconds}
    require(type(document) is dict)
    studio = 'scenes' in document
    if studio:
        fields(document, ('schemaVersion', 'revision', 'programSceneId', 'previewSceneId', 'transition', 'scenes'))
        require(type(document['schemaVersion']) is int and document['schemaVersion'] == 1)
        require(integer(document['revision'], 0, 2**63-1))
        require(type(document['scenes']) is list and 1 <= len(document['scenes']) <= 64)
        ids = unique_ids(document['scenes'])
        require(document['programSceneId'] in ids and document['previewSceneId'] in ids, 'missing_scene_reference')
        fields(document['transition'], ('kind', 'durationMs'))
        require(document['transition']['kind'] in ('cut', 'fade') and integer(document['transition']['durationMs'], 0, 10000))
        scenes = [plan_scene(scene, options) for scene in document['scenes']]
        require(len({(s['canvas']['width'], s['canvas']['height']) for s in scenes}) == 1)
    else:
        scenes = [plan_scene(document, options)]
    blockers = sorted({b for scene in scenes for b in scene['blockers']})
    report = {'schema': 1, 'kind': 'native-legacy-import-dry-run', 'status': 'blocked' if blockers else 'candidate',
              'dryRun': True, 'applied': False, 'qualified': False, 'inputKind': 'studio' if studio else 'scene',
              'runtimeOptions': options, 'blockers': blockers, 'scenes': scenes,
              'excluded': ['accounts', 'sessions', 'internalTokens', 'cameraRegistry', 'privateKeys', 'assetFiles']}
    if studio:
        report['selection'] = {key: identity('scene', document[key])['nativeId'] for key in ('programSceneId', 'previewSceneId')}
        report['transition'] = dict(document['transition'])
    return report


def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate_json_key')
        result[key] = value
    return result


def reject_constant(_):
    raise Rejected('nonfinite_json_number')


@contextmanager
def guarded_parent(path):
    """Hold each ancestor: no POSIX symlink traversal; no Windows reparse/rename."""
    require(path.is_absolute() and '..' not in path.parts, 'unsafe_path')
    if os.name == 'nt':
        require(all(':' not in part and part == part.rstrip(' .') for part in path.parts[1:]), 'unsafe_path')
    with ExitStack() as stack:
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            require(bool(path.drive) and not str(path).startswith('\\\\'), 'unsafe_path')
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            create = kernel.CreateFileW
            create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
            create.restype = wintypes.HANDLE
            close = kernel.CloseHandle
            close.argtypes = [wintypes.HANDLE]
            close.restype = wintypes.BOOL
            get_attrs = kernel.GetFileAttributesW
            get_attrs.argtypes = [wintypes.LPCWSTR]
            get_attrs.restype = wintypes.DWORD
            current = Path(path.anchor)
            for part in path.parent.parts[1:]:
                current = current / part
                handle = create(str(current), 0x80000000, 1, None, 3, 0x02200000, None)
                require(handle != ctypes.c_void_p(-1).value, 'unsafe_or_unreadable_path')
                stack.callback(close, handle)
                attrs = get_attrs(str(current))
                require(attrs != 0xFFFFFFFF and not attrs & 0x400 and attrs & 0x10, 'unsafe_path')
            yield None
        else:
            fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
            stack.callback(os.close, fd)
            for part in path.parent.parts[1:]:
                fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                stack.callback(os.close, fd)
            yield fd


def windows_read_descriptor(path):
    """Open the final name itself, never follow a raced reparse target."""
    import ctypes
    from ctypes import wintypes
    import msvcrt
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL

    class Information(ctypes.Structure):
        _fields_ = [('attributes', wintypes.DWORD), ('created', wintypes.FILETIME),
                    ('accessed', wintypes.FILETIME), ('written', wintypes.FILETIME),
                    ('volume', wintypes.DWORD), ('sizeHigh', wintypes.DWORD),
                    ('sizeLow', wintypes.DWORD), ('links', wintypes.DWORD),
                    ('indexHigh', wintypes.DWORD), ('indexLow', wintypes.DWORD)]

    info_call = kernel.GetFileInformationByHandle
    info_call.argtypes = [wintypes.HANDLE, ctypes.POINTER(Information)]
    info_call.restype = wintypes.BOOL
    type_call = kernel.GetFileType
    type_call.argtypes = [wintypes.HANDLE]
    type_call.restype = wintypes.DWORD
    # OPEN_REPARSE_POINT, not a follow-then-check. Share READ only: no writer/rename.
    handle = create(str(path), 0x80000000, 1, None, 3, 0x00200000, None)
    require(handle != ctypes.c_void_p(-1).value, 'unsafe_or_unreadable_input')
    try:
        info = Information()
        require(bool(info_call(handle, ctypes.byref(info))) and type_call(handle) == 1,
                'unsafe_input_file')
        require(not info.attributes & (0x400 | 0x10) and info.links == 1, 'unsafe_input_file')
        require((info.sizeHigh << 32 | info.sizeLow) <= MAX_BYTES, 'unsafe_or_large_input')
        descriptor = msvcrt.open_osfhandle(int(handle), os.O_RDONLY | os.O_BINARY)
        handle = None  # ownership transferred to the CRT descriptor
        return descriptor
    finally:
        if handle is not None:
            close(handle)


def read_export(path):
    require(path.suffix.lower() == '.json', 'expected_json_export')
    with guarded_parent(path) as parent:
        before = os.lstat(path) if parent is None else os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and not getattr(before, 'st_file_attributes', 0) & 0x400, 'unsafe_input_file')
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_BINARY', 0)
        fd = windows_read_descriptor(path) if os.name == 'nt' else os.open(path.name, flags, dir_fd=parent)
        try:
            opened = os.fstat(fd)
            require(stat.S_ISREG(opened.st_mode) and opened.st_nlink == 1 and opened.st_size <= MAX_BYTES and (before.st_dev, before.st_ino) == (opened.st_dev, opened.st_ino), 'unsafe_or_large_input')
            with os.fdopen(os.dup(fd), 'rb') as stream:
                data = stream.read(MAX_BYTES + 1)
            after = os.fstat(fd)
            require(0 < len(data) <= MAX_BYTES and (opened.st_size, opened.st_mtime_ns) == (after.st_size, after.st_mtime_ns), 'input_changed_or_large')
        finally:
            os.close(fd)
    try:
        return json.loads(data.decode('utf-8'), object_pairs_hook=no_duplicates, parse_constant=reject_constant)
    except (UnicodeError, ValueError, RecursionError):
        raise Rejected('invalid_json_export') from None


def run(source, output, **options):
    source, output = Path(source), Path(output)
    require(source.is_absolute() and output.is_absolute(), 'absolute_paths_required')
    require(not output.is_relative_to(source.parent) and output.suffix.lower() == '.json', 'report_must_be_outside_export_directory')
    report = plan(read_export(source), **options)
    payload = (json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    with guarded_parent(output) as parent:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)
        fd = os.open(output if parent is None else output.name, flags, 0o600, **({} if parent is None else {'dir_fd': parent}))
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload)
    return report


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's default error includes raw values and unknown arguments.
        self.exit(2, 'Invalid migration-preflight arguments. No input was applied.\n')


def main(argv=None):
    parser = SafeArgumentParser(description='Read-only explicit legacy JSON export preflight; no apply mode.')
    parser.add_argument('--input', required=True)
    parser.add_argument('--report', required=True)
    parser.add_argument('--hardware-decode', choices=('on', 'off'))
    parser.add_argument('--connect-timeout-seconds', type=int)
    args = parser.parse_args(argv)
    try:
        report = run(args.input, args.report,
                     hardware_decode=None if args.hardware_decode is None else args.hardware_decode == 'on',
                     connect_timeout_seconds=args.connect_timeout_seconds)
        print(json.dumps({'status': report['status'], 'dryRun': True, 'applied': False}))
        return 0 if report['status'] == 'candidate' else 4
    except (Rejected, OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError):
        print(json.dumps({'status': 'rejected', 'code': 'unsafe_or_unsupported_export'}))
        return 2


if __name__ == '__main__':
    sys.exit(main())
