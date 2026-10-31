#!/usr/bin/env python3
"""Offline preparation of immutable dev prerelease assets, using only stdlib.

Caller MUST first verify the downloaded GitHub artifact, run and source. This
script verifies local consistency, NOT GitHub origin, installer safety or real
Windows qualification. It never builds, executes, extracts, downloads, publishes,
changes tags or touches stable/Latest. The frozen publish_dev17 is not reused.

Inputs must remain quiescent: this is not a sandbox against concurrent hostile
ancestor replacement on Windows. Search prunes real win-unpacked runtime trees,
which are not asset roots. A failed copy may leave a NEW partial output without
a successful receipt; never publish/reuse it. Do NOT upload the private receipt.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

CHUNK_BYTES = 1024 * 1024
MAX_CHECKSUM_BYTES = 8192
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_RECEIPT_BYTES = 8192
MAX_SCAN_ENTRIES = 100000
MAX_SCAN_DEPTH = 64
RECEIPT_NAME = "verification-receipt.json"
VERSION_RE = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)-dev\.(?:0|[1-9][0-9]*)")
REVISION_RE = re.compile(r"[0-9a-fA-F]{40}")
CHECKSUM_RE = re.compile(r"([0-9a-f]{64})  ([A-Za-z0-9][A-Za-z0-9._-]{0,199})")
PIXELTEST_RE = re.compile(r"pixel[\s_.-]*test", re.IGNORECASE)


class VerificationError(ValueError):
    """The local assets are not an acceptable dev candidate."""


def asset_names(version: str) -> tuple[str, ...]:
    installer = f"WebOBS-{version}-windows-x64-DEVELOPMENT-UNSIGNED.exe"
    prefix = f"webobs-windows-{version}"
    return (installer, installer + ".blockmap", *(f"{prefix}-{suffix}" for suffix in (
        "sbom.cdx.json", "runtime-manifest.json", "dependencies.lock.json",
        "licenses.tar.gz", "footprint.json", "SHA256SUMS.txt")))


def _is_link_or_reparse(info) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _require_kind(info, directory: bool) -> None:
    if _is_link_or_reparse(info):
        raise VerificationError("Symlink or reparse point is not allowed")
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise VerificationError("Expected a real directory" if directory else "Expected a regular file")


@contextmanager
def _directory(path: Path):
    """No-follow every existing ancestor; POSIX descriptors pin the directory."""
    if os.name == "nt":
        current = Path(path.anchor)
        _require_kind(current.lstat(), True)
        for part in path.parts[1:]:
            current /= part
            _require_kind(current.lstat(), True)
        yield None
        return
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(path.anchor, flags)
    try:
        for part in path.parts[1:]:
            next_descriptor = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        _require_kind(os.fstat(descriptor), True)
        yield descriptor
    finally:
        os.close(descriptor)


def _windows_open_regular(path: Path) -> int:
    # OPEN_REPARSE_POINT avoids following the final Windows reparse point.
    # Share READ only, preventing writes/rename while this file is opened.
    import ctypes
    from ctypes import wintypes
    import msvcrt
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    handle = create(str(path), 0x80000000, 1, None, 3, 0x00200000 | 0x08000000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        close(handle)
        raise


def _signature(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


@contextmanager
def _regular_file(path: Path):
    with _directory(path.parent) as parent:
        before = (path.lstat() if parent is None else
            os.stat(path.name, dir_fd=parent, follow_symlinks=False))
        _require_kind(before, False)
        descriptor = (_windows_open_regular(path) if parent is None else
            os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0), dir_fd=parent))
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            _require_kind(opened, False)
            if _signature(before) != _signature(opened):
                raise VerificationError("File changed while opening")
            yield stream
            if _signature(opened) != _signature(os.fstat(stream.fileno())):
                raise VerificationError("File changed while reading")


def _read_bounded(path: Path, limit: int) -> bytes:
    with _regular_file(path) as stream:
        if os.fstat(stream.fileno()).st_size > limit:
            raise VerificationError("Metadata exceeds its byte limit")
        data = stream.read(limit + 1)
        if len(data) > limit:
            raise VerificationError("Metadata exceeds its byte limit")
        return data


def _hash_file(path: Path) -> tuple[str, int]:
    digest, size = hashlib.sha256(), 0
    with _regular_file(path) as stream:
        while chunk := stream.read(CHUNK_BYTES):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _find_checksum(root: Path, filename: str) -> Path:
    found, pending, visited = None, [(root, 0)], 0
    while pending:
        directory, depth = pending.pop()
        if depth > MAX_SCAN_DEPTH:
            raise VerificationError("Artifact search depth limit exceeded")
        with _directory(directory) as descriptor:
            with os.scandir(directory if descriptor is None else descriptor) as entries:
                for entry in entries:
                    visited += 1
                    if visited > MAX_SCAN_ENTRIES:
                        raise VerificationError("Artifact search entry limit exceeded")
                    info = entry.stat(follow_symlinks=False)
                    if _is_link_or_reparse(info):
                        raise VerificationError("Symlink or reparse point in artifact search")
                    child = directory / entry.name
                    if stat.S_ISDIR(info.st_mode):
                        if entry.name.casefold() != "win-unpacked":
                            pending.append((child, depth + 1))
                    elif not stat.S_ISREG(info.st_mode):
                        raise VerificationError("Nonregular file in artifact search")
                    elif entry.name == filename:
                        if found is not None:
                            raise VerificationError("Expected exactly one checksum file; found duplicates")
                        found = child
    if found is None:
        raise VerificationError("Expected exactly one checksum file; found none")
    return found


def _parse_checksums(data: bytes, expected: set[str]) -> dict[str, str]:
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as error:
        raise VerificationError("Checksums must be ASCII") from error
    lines = text.replace("\r\n", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    checksums = {}
    for line in lines:
        match = CHECKSUM_RE.fullmatch(line)
        if match is None:
            raise VerificationError("Malformed checksum entry or unsafe asset name")
        digest, name = match.groups()
        if name not in expected:
            raise VerificationError("Checksum entry is not an exact dev asset whitelist member")
        if name in checksums:
            raise VerificationError("Duplicate checksum entry")
        checksums[name] = digest
    if set(checksums) != expected or len(checksums) != 7:
        raise VerificationError("Checksums must contain exactly the seven required assets")
    return checksums


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise VerificationError("Duplicate JSON object key")
        result[key] = value
    return result


def _reject_json_constant(value):
    raise VerificationError("Nonstandard JSON constant is not allowed")


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(_read_bounded(path, MAX_JSON_BYTES).decode("utf-8"),
            object_pairs_hook=_unique_json_object, parse_constant=_reject_json_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise VerificationError("Invalid or excessively nested JSON metadata") from error
    if not isinstance(value, dict):
        raise VerificationError("JSON metadata must be an object")
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
        elif isinstance(item, str) and PIXELTEST_RE.search(item):
            raise VerificationError("PixelTest-marked metadata is forbidden")
    return value


def _validate_metadata(base: Path, version: str, revision: str) -> None:
    prefix = f"webobs-windows-{version}"
    manifest = _read_json(base / f"{prefix}-runtime-manifest.json")
    for key, expected in (("version", version), ("revision", revision), ("platform", "windows-x64")):
        if manifest.get(key) != expected:
            raise VerificationError(f"Runtime manifest {key} mismatch")
    sbom = _read_json(base / f"{prefix}-sbom.cdx.json")
    metadata = sbom.get("metadata")
    component = metadata.get("component") if isinstance(metadata, dict) else None
    if sbom.get("bomFormat") != "CycloneDX" or not isinstance(component, dict):
        raise VerificationError("Expected the generated CycloneDX SBOM metadata")
    # Top-level CycloneDX 'version' is the BOM revision, NOT the app version.
    if component.get("version") != version:
        raise VerificationError("SBOM component version mismatch")
    properties = metadata.get("properties")
    if not isinstance(properties, list) or any(not isinstance(item, dict) for item in properties):
        raise VerificationError("Expected SBOM metadata properties")
    revisions = [item.get("value") for item in properties if item.get("name") == "webobs:revision"]
    if revisions != [revision]:
        raise VerificationError("SBOM must contain one matching metadata webobs:revision")
    _read_json(base / f"{prefix}-dependencies.lock.json")
    if _read_json(base / f"{prefix}-footprint.json").get("version") != version:
        raise VerificationError("Footprint version mismatch")


def _verify_assets(base: Path, version: str, revision: str) -> dict:
    names = asset_names(version)
    with _directory(base) as descriptor:
        with os.scandir(base if descriptor is None else descriptor) as entries:
            if any(entry.name.casefold() == "latest.yml" for entry in entries):
                raise VerificationError("Development assets must not include stable latest.yml")
    raw = _read_bounded(base / names[-1], MAX_CHECKSUM_BYTES)
    checksums = _parse_checksums(raw, set(names[:-1]))
    result = {}
    for name in sorted(checksums):
        digest, size = _hash_file(base / name)
        if digest != checksums[name]:
            raise VerificationError(f"SHA256 mismatch: {name}")
        result[name] = {"sha256": digest, "bytes": size}
    _validate_metadata(base, version, revision)
    result[names[-1]] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    return result


def _copy_asset(source: Path, target: Path, expected: dict) -> None:
    digest, size = hashlib.sha256(), 0
    with _regular_file(source) as stream, _directory(target.parent) as parent:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        descriptor = (os.open(target, flags, 0o600) if parent is None else
            os.open(target.name, flags | os.O_NOFOLLOW, 0o600, dir_fd=parent))
        with os.fdopen(descriptor, "wb") as destination:
            while chunk := stream.read(CHUNK_BYTES):
                destination.write(chunk)
                digest.update(chunk)
                size += len(chunk)
    if {"sha256": digest.hexdigest(), "bytes": size} != expected:
        raise VerificationError("Source asset changed during copying")


def prepare_dev_prerelease(version: str, revision: str, input_directory, output_directory) -> dict:
    """Return a bounded private receipt; output's existing parent is required."""
    if len(version) > 64 or VERSION_RE.fullmatch(version) is None:
        raise VerificationError("Version must be canonical X.Y.Z-dev.N; stable/Latest is forbidden")
    if REVISION_RE.fullmatch(revision) is None:
        raise VerificationError("Revision must be the full explicit 40-hex source revision")
    root = Path(os.path.abspath(os.fspath(input_directory)))
    output = Path(os.path.abspath(os.fspath(output_directory)))
    if root == output or root in output.parents or output in root.parents:
        raise VerificationError("Input and output directories must not overlap")
    try:
        with _directory(root), _directory(output.parent):
            if os.path.lexists(output):
                raise VerificationError("Output must not already exist")
        names = asset_names(version)
        base = _find_checksum(root, names[-1]).parent
        verified = _verify_assets(base, version, revision)
        with _directory(output.parent) as parent:
            if parent is None:
                output.mkdir(mode=0o700)
            else:
                os.mkdir(output.name, mode=0o700, dir_fd=parent)
        for name in names:
            _copy_asset(base / name, output / name, verified[name])
        if _verify_assets(output, version, revision) != verified:
            raise VerificationError("Copied assets do not match the verified originals")
        with _directory(output) as descriptor:
            with os.scandir(output if descriptor is None else descriptor) as entries:
                if {entry.name for entry in entries} != set(names):
                    raise VerificationError("Output contains unexpected entries")
        receipt = {
            "schema": 1, "kind": "offline-dev-prerelease-verification",
            "version": version, "revision": revision, "platform": "windows-x64",
            "assets": [{"name": name, **verified[name]} for name in sorted(verified)],
            "checksums_and_copied_bytes_verified": True,
            "runtime_and_sbom_identity_verified": True,
            "github_source_verified": False, "publication_performed": False,
            "receipt_is_public_release_asset": False,
            "scope": "Local consistency only; caller must verify GitHub artifact/run/source and authorize dev Pre-release direct download. Never stable/Latest.",
        }
        encoded = (json.dumps(receipt, sort_keys=True, indent=2) + "\n").encode("utf-8")
        if len(encoded) > MAX_RECEIPT_BYTES:
            raise VerificationError("Verification receipt exceeds its fixed bound")
        with _directory(output) as parent:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
            descriptor = (os.open(output / RECEIPT_NAME, flags, 0o600) if parent is None else
                os.open(RECEIPT_NAME, flags | os.O_NOFOLLOW, 0o600, dir_fd=parent))
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encoded)
        return receipt
    except OSError as error:
        raise VerificationError(f"Filesystem verification failed: {error.strerror or type(error).__name__}") from error


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", required=True, help="Explicit X.Y.Z-dev.N, never stable or Latest")
    parser.add_argument("--revision", required=True, help="Explicit full 40-hex source revision")
    parser.add_argument("--input", required=True, type=Path, help="Complete already-downloaded artifact directory")
    parser.add_argument("--output", required=True, type=Path, help="New non-overlapping directory; parent must exist")
    args = parser.parse_args(argv)
    try:
        receipt = prepare_dev_prerelease(args.version, args.revision, args.input, args.output)
    except VerificationError as error:
        parser.exit(1, f"Dev prerelease verification failed: {error}\n")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
