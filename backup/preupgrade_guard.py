#!/usr/bin/env python3
"""One-time, fail-closed v2-M7 configuration migration guard."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import shutil
import sqlite3
import time
import uuid


PENDING = ".v2-m7-upgrade-pending.json"
READY = ".v2-m7-schema-ready.json"
BACKUP_DIR = ".upgrade-backups"
MAX_FILE = 1024 * 1024 * 1024
MAX_TOTAL = 8 * 1024 * 1024 * 1024


class UpgradeError(RuntimeError):
    pass


def digest(path: pathlib.Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def atomic_json(path: pathlib.Path, value: dict) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temporary.open("x", encoding="utf-8") as output:
        json.dump(value, output, separators=(",", ":"), sort_keys=True)
        output.write("\n"); output.flush(); os.fsync(output.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def regular_files(root: pathlib.Path, include_runtime: bool = False) -> list[pathlib.Path]:
    result: list[pathlib.Path] = []
    total = 0
    if not root.is_dir() or root.is_symlink():
        raise UpgradeError("configuration root is unavailable or unsafe")
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise UpgradeError("configuration contains a symbolic link")
        if path.is_dir():
            continue
        if not path.is_file():
            raise UpgradeError("configuration contains an unsupported entry")
        relative = path.relative_to(root)
        if not include_runtime and (relative.parts[0] == BACKUP_DIR or
                                    path.name in {PENDING, READY} or
                                    path.name.endswith(("-wal", "-shm")) or
                                    path.name.startswith(".webobs-")):
            continue
        size = path.stat().st_size
        if size > MAX_FILE:
            raise UpgradeError("configuration file exceeds upgrade backup limit")
        total += size
        if total > MAX_TOTAL:
            raise UpgradeError("configuration exceeds upgrade backup limit")
        result.append(path)
    return result


def sqlite_snapshot(source: pathlib.Path, destination: pathlib.Path) -> None:
    source_db = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True, timeout=10)
    target_db = sqlite3.connect(destination)
    try:
        source_db.backup(target_db)
        if target_db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise UpgradeError("upgrade database snapshot failed integrity validation")
    finally:
        target_db.close(); source_db.close()


def verify_backup(backup: pathlib.Path) -> tuple[dict, pathlib.Path]:
    manifest_path = backup / "manifest.json"
    if backup.is_symlink() or not backup.is_dir() or not manifest_path.is_file() or manifest_path.is_symlink():
        raise UpgradeError("upgrade backup is unavailable")
    value = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) != {"format", "createdAt", "files"} or \
            value["format"] != "webobs-pre-v2-m7-v1" or not isinstance(value["files"], list):
        raise UpgradeError("upgrade backup manifest is invalid")
    snapshot = backup / "snapshot"
    expected = set()
    for item in value["files"]:
        if not isinstance(item, dict) or set(item) != {"path", "size", "sha256"}:
            raise UpgradeError("upgrade backup entry is invalid")
        relative = pathlib.PurePosixPath(item["path"])
        if relative.is_absolute() or not relative.parts or ".." in relative.parts:
            raise UpgradeError("upgrade backup path is unsafe")
        path = snapshot.joinpath(*relative.parts)
        if not path.is_file() or path.is_symlink() or path.stat().st_size != item["size"] or \
                digest(path) != item["sha256"]:
            raise UpgradeError("upgrade backup digest validation failed")
        if path.suffix in {".db", ".sqlite", ".sqlite3"}:
            database = sqlite3.connect(path)
            try:
                if database.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise UpgradeError("upgrade backup database is corrupt")
            finally:
                database.close()
        expected.add(relative.as_posix())
    actual = {path.relative_to(snapshot).as_posix() for path in snapshot.rglob("*") if path.is_file()}
    if actual != expected:
        raise UpgradeError("upgrade backup contains undeclared files")
    return value, snapshot


def pending_backup(config_root: pathlib.Path) -> pathlib.Path:
    pending = config_root / PENDING
    if not pending.is_file() or pending.is_symlink() or pending.stat().st_size > 4096:
        raise UpgradeError("upgrade pending marker is invalid")
    value = json.loads(pending.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) != {"backupName"} or \
            not isinstance(value["backupName"], str) or \
            not re.fullmatch(r"pre-v2-m7-[0-9]{10}-[0-9a-f]{8}", value["backupName"]):
        raise UpgradeError("upgrade pending marker is invalid")
    backup_parent = config_root / BACKUP_DIR
    backup = backup_parent / value["backupName"]
    if backup.parent.resolve() != backup_parent.resolve():
        raise UpgradeError("upgrade backup escaped its configured parent")
    return backup


def prepare(config_root: pathlib.Path) -> bool:
    config_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if config_root.is_symlink():
        raise UpgradeError("configuration root is unsafe")
    if (config_root / READY).is_file():
        return False
    if (config_root / PENDING).exists():
        rollback(config_root)
    name = f"pre-v2-m7-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    backup_parent = config_root / BACKUP_DIR
    backup_parent.mkdir(mode=0o700, exist_ok=True)
    if backup_parent.is_symlink():
        raise UpgradeError("upgrade backup root is unsafe")
    backup = backup_parent / name
    backup.mkdir(mode=0o700)
    snapshot = backup / "snapshot"
    snapshot.mkdir(mode=0o700)
    entries = []
    try:
        for source in regular_files(config_root):
            relative = source.relative_to(config_root)
            destination = snapshot / relative
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if source.suffix in {".db", ".sqlite", ".sqlite3"}:
                sqlite_snapshot(source, destination)
            else:
                shutil.copyfile(source, destination)
            os.chmod(destination, 0o600)
            entries.append({"path": relative.as_posix(), "size": destination.stat().st_size,
                            "sha256": digest(destination)})
        atomic_json(backup / "manifest.json", {
            "format": "webobs-pre-v2-m7-v1", "createdAt": int(time.time()), "files": entries,
        })
        verify_backup(backup)
        atomic_json(config_root / PENDING, {"backupName": name})
    except Exception:
        shutil.rmtree(backup, ignore_errors=True)
        raise
    return True


def rollback(config_root: pathlib.Path) -> pathlib.Path:
    backup = pending_backup(config_root)
    _, snapshot = verify_backup(backup)
    # Validate the complete source before changing the active tree. Runtime WAL,
    # SHM and newly created migration files are deliberately removed.
    for path in sorted(config_root.rglob("*"), key=lambda candidate: len(candidate.parts), reverse=True):
        if path == config_root / PENDING:
            continue
        relative = path.relative_to(config_root)
        if relative.parts and relative.parts[0] == BACKUP_DIR:
            continue
        if path.is_symlink() or (not path.is_file() and not path.is_dir()):
            raise UpgradeError("active configuration became unsafe during upgrade")
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            with __import__("contextlib").suppress(OSError):
                path.rmdir()
    for source in sorted(snapshot.rglob("*")):
        relative = source.relative_to(snapshot)
        destination = config_root / relative
        if source.is_dir():
            destination.mkdir(parents=True, exist_ok=True, mode=0o700)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copyfile(source, destination); os.chmod(destination, 0o600)
    (config_root / PENDING).unlink()
    return backup


def commit(config_root: pathlib.Path) -> pathlib.Path | None:
    if not (config_root / PENDING).exists():
        return None
    backup = pending_backup(config_root)
    verify_backup(backup)
    atomic_json(config_root / READY, {
        "schema": "v2-M7", "completedAt": int(time.time()), "backupName": backup.name,
    })
    (config_root / PENDING).unlink()
    return backup


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices={"prepare", "commit", "rollback"})
    parser.add_argument("--config-root", default=os.environ.get("WEBOBS_CONFIG_ROOT", "/config/webobs"))
    args = parser.parse_args()
    root = pathlib.Path(args.config_root)
    if not root.is_absolute():
        raise SystemExit("upgrade configuration root must be absolute")
    try:
        result = {"prepare": prepare, "commit": commit, "rollback": rollback}[args.action](root)
    except (OSError, sqlite3.Error, json.JSONDecodeError, UpgradeError) as error:
        raise SystemExit(f"v2-M7 upgrade guard failed: {error}") from error
    print(f"v2-M7 upgrade guard {args.action}: {'changed' if result else 'already-complete'}")


if __name__ == "__main__":
    main()
