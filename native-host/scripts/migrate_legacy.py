#!/usr/bin/env python3
"""Migrate an explicitly supplied legacy WebOBS config into a new native profile.

The source is read-only. Databases are copied through SQLite's backup API so a
stopped legacy profile with WAL sidecars becomes one consistent destination.
No profile discovery, network access, silent overwrite or credential logging is
performed. The destination must be empty; the old installation remains intact.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import tempfile

DATABASES = ("cluster.sqlite3", "cameras.db", "events.db", "v2-clients.db")
JSON_FILES = ("scene.json", "studio.json", "nvr.json", "archive.json", "desktop.json")
DIRECTORIES = ("keys", "camera-secrets", "notification-secrets", "secrets", "go2rtc")
PREVIEW_WORKSPACE = re.compile(r"^workspace-([a-f0-9]{32})\.json$")
RECEIPT = "native-migration.json"


class MigrationError(Exception):
    """A bounded migration diagnostic that never contains private values."""


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def safe_file(path: Path, limit: int) -> Path:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise MigrationError("legacy file is missing, linked or oversized")
    return path


def copy_json(source: Path, destination: Path):
    safe_file(source, 8 * 1024 * 1024)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise MigrationError("legacy JSON is invalid") from None
    if not isinstance(value, (dict, list)):
        raise MigrationError("legacy JSON is not an object")
    shutil.copy2(source, destination)


def copy_database(source: Path, destination: Path):
    safe_file(source, 4 * 1024 * 1024 * 1024)
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as reader:
        reader.execute("PRAGMA query_only=ON")
        with closing(sqlite3.connect(destination)) as writer:
            reader.backup(writer)
            result = writer.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise MigrationError("migrated database failed integrity_check")
    if destination.stat().st_size == 0:
        raise MigrationError("migrated database is empty")


def copy_tree(source: Path, destination: Path):
    if source.is_symlink() or not source.is_dir():
        raise MigrationError("legacy secret directory is unsafe")
    for item in source.rglob("*"):
        if item.is_symlink():
            raise MigrationError("legacy secret directory contains a link")
        if not item.is_file():
            continue
        relative = item.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if item.stat().st_size > 16 * 1024 * 1024:
            raise MigrationError("legacy secret file is oversized")
        shutil.copy2(item, target)


def copy_preview_workspaces(preview_profile: Path, staging: Path) -> list[str]:
    """Copy only account-bound native monitor workspaces from a v4.5 profile."""
    if preview_profile.is_symlink() or not preview_profile.is_dir():
        raise MigrationError("v4.5 native profile is unavailable")
    copied = []
    for item in sorted(preview_profile.iterdir()):
        if PREVIEW_WORKSPACE.fullmatch(item.name) is None:
            continue
        safe_file(item, 256 * 1024)
        try:
            value = json.loads(item.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            raise MigrationError("v4.5 workspace is invalid") from None
        if not isinstance(value, dict) or value.get("schema") not in (1, 2):
            raise MigrationError("v4.5 workspace has an unsupported schema")
        target = staging / "native-profile" / item.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
        copied.append("native-profile/" + item.name)
    return copied


def dpapi_key(source: Path) -> bytes | None:
    """Best-effort decrypt of Electron safeStorage's current-user DPAPI blob."""
    if os.name != "nt" or source.is_symlink() or not source.is_file():
        return None
    blob = source.read_bytes()
    if not 32 <= len(blob) <= 16384:
        return None

    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
    incoming = DataBlob(len(blob), buffer)
    outgoing = DataBlob()
    if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(incoming), None, None, None, None, 0, ctypes.byref(outgoing)):
        return None
    try:
        value = bytes(bytearray(outgoing.pbData[:outgoing.cbData]))
    finally:
        ctypes.windll.kernel32.LocalFree(outgoing.pbData)
    try:
        text = value.decode("ascii").strip()
    except UnicodeError:
        return None
    if not re.fullmatch(r"[a-fA-F0-9]{64}", text):
        return None
    return bytes.fromhex(text)


def migrate(source: Path, destination: Path, *, confirm_stopped: bool,
            include_backup_key: bool, include_preview_workspaces: bool = False) -> dict:
    if os.name != "nt":
        os.umask(0o077)
    source, destination = source.resolve(), destination.resolve()
    if not confirm_stopped:
        raise MigrationError("legacy product must be stopped and confirmed")
    if not source.is_dir() or source.is_symlink():
        raise MigrationError("legacy config directory is unavailable")
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise MigrationError("destination profile is not empty")
    if destination == source or source in destination.parents or destination in source.parents:
        raise MigrationError("destination must be a separate new profile")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".webobs-migration-", dir=destination.parent))
    files = []
    try:
        for name in JSON_FILES:
            candidate = source / name
            if candidate.is_file() and not candidate.is_symlink():
                copy_json(candidate, staging / name)
                files.append(name)
        for name in DATABASES:
            candidate = source / name
            if candidate.is_file() and not candidate.is_symlink():
                copy_database(candidate, staging / name)
                files.append(name)
        for name in DIRECTORIES:
            candidate = source / name
            if candidate.is_dir() and not candidate.is_symlink():
                copy_tree(candidate, staging / name)
                files.append(name + "/")
        preview_workspaces = []
        if include_preview_workspaces:
            preview_workspaces = copy_preview_workspaces(source.parent / "native-profile", staging)
            files.extend(preview_workspaces)
        if not files:
            raise MigrationError("legacy profile contains no supported product data")
        recordings = None
        desktop = source / "desktop.json"
        if desktop.is_file() and not desktop.is_symlink():
            try:
                settings = json.loads(desktop.read_text(encoding="utf-8"))
                candidate = settings.get("recordingDirectory") if isinstance(settings, dict) else None
                if isinstance(candidate, str) and candidate and Path(candidate).is_absolute():
                    recordings = Path(candidate)
            except (OSError, UnicodeError, ValueError):
                recordings = None
        if recordings is None:
            profile = os.environ.get("USERPROFILE")
            recordings = Path(profile) / "Videos" / "WebOBS" if profile else None
        key_migrated = False
        if include_backup_key:
            key = dpapi_key(source.parent / "backup-key.dpapi")
            if key is not None:
                (staging / "backup.key").write_bytes(key)
                key_migrated = True
        manifest = {
            "schema": 1, "kind": "native-legacy-config-migration",
            "sourceKind": ("explicit-native-preview" if include_preview_workspaces else
                           "explicit-legacy-config"), "destinationKind": "new-native-profile",
            "files": files, "backupKeyMigrated": key_migrated,
            "previewWorkspacesCopied": len(preview_workspaces),
            "recordingsPath": str(recordings) if recordings is not None else None,
        }
        (staging / "native-migration.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        destination.mkdir(parents=True, exist_ok=True)
        for item in sorted(staging.iterdir()):
            shutil.move(str(item), str(destination / item.name))
        receipt = {
            "schema": 1, "status": "migrated", "kind": "native-legacy-config-migration",
            "files": len(files), "backupKeyMigrated": key_migrated,
            "previewWorkspacesCopied": len(preview_workspaces),
            "recordingsConfigured": recordings is not None,
            "sourcePreserved": True, "applied": True,
        }
        return receipt
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--confirm-stopped", action="store_true")
    parser.add_argument("--include-backup-key", action="store_true")
    parser.add_argument("--include-preview-workspaces", action="store_true",
                        help="copy account-bound monitor workspaces from a v4.5 NativePreview profile")
    arguments = parser.parse_args(argv)
    try:
        result = migrate(Path(arguments.source), Path(arguments.destination),
                         confirm_stopped=arguments.confirm_stopped,
                         include_backup_key=arguments.include_backup_key,
                         include_preview_workspaces=arguments.include_preview_workspaces)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (MigrationError, OSError, sqlite3.Error):
        print("Legacy migration failed; the old profile was not modified.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
