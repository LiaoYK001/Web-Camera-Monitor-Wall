#!/usr/bin/env python3
"""Inspect and restore a native-host private-profile backup.

The plugin snapshots ``config/`` into ``backups/`` once per application version
before the new build writes to the profile. This tool lists those snapshots,
validates their manifests and hashes, and can replace ``config/`` with one of
them after first snapshotting the current profile.

Only the portable install root is touched. Nothing is downloaded or uploaded and
the receipt never contains camera URLs, credentials or profile contents.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

KIND = "native-config-upgrade-backup"
PRE_RESTORE_KIND = "native-config-pre-restore"
VERSION_RE = "^[0-9A-Za-z._-]{1,40}$"
SCHEMA = 1


class RestoreError(Exception):
    """A backup or target fails validation."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_relative(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise RestoreError("entry path missing")
    if "\\" in value or ":" in value:
        raise RestoreError(f"unsafe entry path {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("..", "", ".") for part in path.parts):
        raise RestoreError(f"unsafe entry path {value!r}")
    return path.as_posix()


def load_manifest(backup_dir: Path) -> dict:
    manifest_path = backup_dir / "backup.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RestoreError(f"cannot read backup manifest: {error}") from error
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA:
        raise RestoreError("unsupported backup schema")
    if manifest.get("kind") != KIND:
        raise RestoreError("not a native-host config backup")
    version = manifest.get("version")
    if not isinstance(version, str) or not version:
        raise RestoreError("backup version missing")
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise RestoreError("backup entries missing")
    listed = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise RestoreError("malformed backup entry")
        relative = _safe_relative(entry.get("path"))
        if relative in listed:
            raise RestoreError(f"duplicate backup entry {relative}")
        listed.add(relative)
        source = backup_dir / relative
        if not source.is_file() or source.is_symlink():
            raise RestoreError(f"backup payload missing {relative}")
        if entry.get("bytes") != source.stat().st_size:
            raise RestoreError(f"backup size mismatch {relative}")
        if entry.get("sha256") != _sha256(source):
            raise RestoreError(f"backup hash mismatch {relative}")
    present = {
        file.relative_to(backup_dir).as_posix()
        for file in backup_dir.rglob("*")
        if file.is_file() and not file.is_symlink() and file.name != "backup.json"
    }
    if present != listed:
        raise RestoreError("backup contains unlisted or missing files")
    if manifest.get("files") != len(entries) or manifest.get("bytes") != sum(
        entry["bytes"] for entry in entries
    ):
        raise RestoreError("backup counts do not match its entries")
    return manifest


def list_backups(install_root: Path) -> list[dict]:
    backups_root = install_root / "backups"
    if not backups_root.is_dir():
        return []
    result = []
    for candidate in sorted(backups_root.iterdir()):
        if not candidate.is_dir() or not (candidate / "backup.json").is_file():
            continue
        try:
            if json.loads((candidate / "backup.json").read_text(encoding="utf-8")).get("kind") != KIND:
                continue
        except (OSError, json.JSONDecodeError):
            continue
        manifest = load_manifest(candidate)
        result.append(
            {
                "directory": candidate.name,
                "version": manifest["version"],
                "createdAt": manifest.get("createdAt"),
                "files": manifest["files"],
                "bytes": manifest["bytes"],
            }
        )
    return result


def _copy_tree(source: Path, destination: Path) -> tuple[int, int]:
    files = 0
    total = 0
    for item in sorted(source.rglob("*")):
        if item.is_symlink():
            raise RestoreError(f"symlink in profile {item}")
        if not item.is_file():
            continue
        relative = item.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(item, target)
        files += 1
        total += item.stat().st_size
    return files, total


def _snapshot_current(config: Path, backups_root: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot = backups_root / f"pre-restore-{stamp}"
    if snapshot.exists():
        raise RestoreError("pre-restore snapshot already exists")
    snapshot.mkdir(parents=True)
    files, total = _copy_tree(config, snapshot) if config.is_dir() else (0, 0)
    (snapshot / "backup.json").write_text(
        json.dumps(
            {
                "schema": SCHEMA,
                "kind": PRE_RESTORE_KIND,
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "files": files,
                "bytes": total,
            },
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )
    return snapshot


def restore(install_root: Path, backup_dir: Path) -> dict:
    install_root = install_root.resolve()
    backup_dir = backup_dir.resolve()
    backups_root = (install_root / "backups").resolve()
    if backup_dir.parent != backups_root or not backup_dir.is_dir():
        raise RestoreError("backup is not a direct child of this install's backups directory")
    manifest = load_manifest(backup_dir)
    config = install_root / "config"
    snapshot = _snapshot_current(config, backups_root)

    staging = Path(tempfile.mkdtemp(prefix=".restore-", dir=install_root))
    try:
        for entry in manifest["entries"]:
            relative = _safe_relative(entry["path"])
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(backup_dir / relative, target)
        if config.exists():
            shutil.rmtree(config)
        staging.replace(config)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise
    return {
        "schema": SCHEMA,
        "kind": "native-config-restore",
        "restoredFrom": backup_dir.name,
        "version": manifest["version"],
        "files": manifest["files"],
        "bytes": manifest["bytes"],
        "preRestoreSnapshot": snapshot.name,
        "restoredAt": datetime.now(timezone.utc).isoformat(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-root", required=True, type=Path)
    parser.add_argument("--list", action="store_true", help="list valid backups as JSON")
    parser.add_argument("--backup", help="backup directory name to validate or restore")
    parser.add_argument("--apply", action="store_true", help="replace config/ with the backup")
    parser.add_argument("--receipt", type=Path, help="write a restore receipt here")
    args = parser.parse_args(argv)

    install_root = args.install_root.resolve()
    if not (install_root / "webobs-native-prototype.json").is_file():
        print("install root is not a WebOBS native prototype", file=sys.stderr)
        return 2
    try:
        backups = list_backups(install_root)
        if args.list and not args.backup:
            print(json.dumps({"schema": SCHEMA, "backups": backups}, indent=2))
            return 0
        if not args.backup:
            print("choose --list or --backup", file=sys.stderr)
            return 2
        selected = install_root / "backups" / args.backup
        if selected.name != args.backup or not selected.is_dir():
            raise RestoreError("backup not found")
        manifest = load_manifest(selected)
        if args.apply:
            receipt = restore(install_root, selected)
            if args.receipt:
                args.receipt.parent.mkdir(parents=True, exist_ok=True)
                args.receipt.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(receipt, indent=2))
            return 0
        print(
            json.dumps(
                {
                    "schema": SCHEMA,
                    "backup": selected.name,
                    "version": manifest["version"],
                    "files": manifest["files"],
                    "bytes": manifest["bytes"],
                    "valid": True,
                },
                indent=2,
            )
        )
        return 0
    except RestoreError as error:
        print(f"restore error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
