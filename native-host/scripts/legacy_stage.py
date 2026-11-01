#!/usr/bin/env python3
"""Explicit offline private candidate only; never load OBS or apply configuration."""
from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
import json
import os
from pathlib import Path
import stat
import sys

import legacy_import as legacy
import legacy_stage_document as document_stage
import private_stage


def decode_member(data):
    legacy.require(type(data) is bytes and 0 < len(data) <= 8 * 1024 * 1024, 'invalid_member')
    try:
        return json.loads(data.decode('utf-8'), object_pairs_hook=legacy.no_duplicates,
                          parse_constant=legacy.reject_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise legacy.Rejected('invalid_member') from None


def encode_member(document):
    return (json.dumps(document, ensure_ascii=True, allow_nan=False,
                       sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')


def validate_locations(source, destination, existing_config_roots):
    # Exclusions are explicit, not profile discovery. New-directory-only staging
    # also ensures that an incorrectly supplied exclusion cannot overwrite files.
    legacy.require(source.is_absolute() and destination.is_absolute()
                   and '..' not in source.parts and '..' not in destination.parts,
                   'absolute_paths_required')
    legacy.require(bool(existing_config_roots), 'explicit_config_exclusion_required')
    legacy.require(not destination.is_relative_to(source.parent), 'unsafe_stage_location')
    for root in existing_config_roots:
        legacy.require(root.is_absolute() and '..' not in root.parts, 'unsafe_config_exclusion')
        legacy.require(not destination.is_relative_to(root), 'unsafe_stage_location')


def directory_identity(path):
    info = os.stat(path, follow_symlinks=False)
    legacy.require(stat.S_ISDIR(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400,
                   'unsafe_stage_location')
    legacy.require(info.st_ino != 0, 'unavailable_directory_identity')
    return info.st_dev, info.st_ino


@contextmanager
def guarded_locations(source, destination, roots):
    validate_locations(source, destination, roots)
    protected = [source.parent, *roots]
    if os.name == 'nt':
        legacy.require(all(private_stage._windows_path_safe(path)
                           for path in (source, destination, *roots)), 'unsafe_stage_location')
    with ExitStack() as stack:
        for path in [*protected, destination.parent]:
            stack.enter_context(legacy.guarded_parent(path / 'native-stage-exclusion-sentinel'))
        forbidden = {directory_identity(path) for path in protected}
        # Compare volume/file identities, not spelling: drive aliases, 8.3 names
        # and POSIX bind aliases may denote an excluded directory without reparse.
        for ancestor in (destination.parent, *destination.parent.parents):
            legacy.require(directory_identity(ancestor) not in forbidden, 'unsafe_stage_location')
        yield


def run(source, destination, *, existing_config_roots, hardware_decode,
        connect_timeout_seconds):
    source, destination = Path(source), Path(destination)
    roots = [Path(root) for root in existing_config_roots]
    with guarded_locations(source, destination, roots):
        return stage_guarded(source, destination, hardware_decode=hardware_decode,
                             connect_timeout_seconds=connect_timeout_seconds)


def stage_guarded(source, destination, *, hardware_decode, connect_timeout_seconds):
    original = legacy.read_export(source)
    options = dict(hardware_decode=hardware_decode,
                   connect_timeout_seconds=connect_timeout_seconds)
    collection, manifest = document_stage.build(original, **options)
    document_stage.verify(original, collection, manifest, **options)
    members = {'collection.json': encode_member(collection),
               'manifest.json': encode_member(manifest)}

    def verify_readback(readback):
        legacy.require(set(readback) == {'collection.json', 'manifest.json'}, 'invalid_members')
        document_stage.verify(original, decode_member(readback['collection.json']),
                              decode_member(readback['manifest.json']), **options)

    private_stage.stage(destination, members, verify_readback)
    # No private paths, names, exact fingerprints, registry IDs or contents.
    return {'status': 'staged', 'kind': 'native-legacy-offline-private-candidate',
            'applied': False, 'qualified': False, 'liveHostLoaded': False}


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, 'Invalid offline-staging arguments. No configuration was applied.\n')


def main(argv=None):
    parser = SafeParser(description='Create a new private offline candidate; no apply mode.')
    parser.add_argument('--input', required=True)
    parser.add_argument('--destination', required=True)
    parser.add_argument('--existing-config-root', action='append', required=True)
    parser.add_argument('--hardware-decode', choices=('on', 'off'), required=True)
    parser.add_argument('--connect-timeout-seconds', type=int, required=True)
    args = parser.parse_args(argv)
    try:
        receipt = run(args.input, args.destination,
                      existing_config_roots=args.existing_config_root,
                      hardware_decode=args.hardware_decode == 'on',
                      connect_timeout_seconds=args.connect_timeout_seconds)
        print(json.dumps(receipt, sort_keys=True))
        return 0
    except (legacy.Rejected, private_stage.Rejected, OSError, ValueError,
            TypeError, KeyError, OverflowError, RecursionError):
        print(json.dumps({'status': 'rejected', 'code': 'unsafe_or_unsupported_stage',
                          'applied': False, 'qualified': False}))
        return 2


if __name__ == '__main__':
    sys.exit(main())
