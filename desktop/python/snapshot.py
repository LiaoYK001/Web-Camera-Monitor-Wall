"""Consistent offline snapshot. Owner stops all writers before invoking this tool."""
import argparse
import hashlib
import json
import pathlib
import shutil
import sqlite3
import os
import uuid
from contextlib import closing

def inventory(root):
    result = []
    for file in sorted(root.rglob("*")):
        if file.is_symlink() or getattr(file.lstat(), "st_file_attributes", 0) & 0x400: raise ValueError("snapshot links are prohibited")
        if file.is_file():
            digest = hashlib.sha256()
            with file.open("rb") as source:
                while chunk := source.read(1024*1024): digest.update(chunk)
            result.append({"path": file.relative_to(root).as_posix(), "sha256": digest.hexdigest()})
    return result

def snapshot(data, recordings, destination, version):
    if destination.exists(): raise ValueError("snapshot destination already exists")
    temporary = destination.with_name(destination.name + ".partial." + uuid.uuid4().hex)
    temporary.mkdir(parents=True, mode=0o700)
    try:
        inventory(data) # Reject links before copy; files remain inaccessible to other users.
        shutil.copytree(data, temporary / "config")
        # NVR metadata is separate from large recordings; do not copy live video files.
        catalog = recordings / "catalog.sqlite3"
        if catalog.exists():
            with closing(sqlite3.connect(f"{catalog.as_uri()}?mode=ro", uri=True)) as source, closing(sqlite3.connect(temporary / "catalog.sqlite3")) as target:
                source.backup(target)
        for file in (temporary / "config").rglob("*"):
            if file.is_file() and file.suffix in {".db", ".sqlite3"}:
                with closing(sqlite3.connect(file)) as connection:
                    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok": raise ValueError("database integrity check failed")
        manifest = {"schema": 1, "version": version, "recordingDirectory": str(recordings), "files": inventory(temporary)}
        (temporary / "snapshot.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, destination)
    finally:
        if temporary.exists(): shutil.rmtree(temporary)

def restore(snapshot_root, data, recordings):
    manifest = json.loads((snapshot_root / "snapshot.json").read_text(encoding="utf-8"))
    actual = [item for item in inventory(snapshot_root) if item["path"] != "snapshot.json"]
    if manifest.get("schema") != 1 or manifest.get("files") != actual: raise ValueError("snapshot digest failed")
    if not (snapshot_root / "config").is_dir(): raise ValueError("snapshot configuration missing")
    if data.exists(): raise ValueError("restore target must be an empty staging directory")
    shutil.copytree(snapshot_root / "config", data)
    if (snapshot_root / "catalog.sqlite3").exists():
        recordings.mkdir(parents=True, exist_ok=True)
        temporary = recordings / ("catalog.sqlite3.restore." + uuid.uuid4().hex)
        try:
            shutil.copyfile(snapshot_root / "catalog.sqlite3", temporary)
            with closing(sqlite3.connect(temporary)) as connection:
                if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok": raise ValueError("catalog integrity check failed")
            existing = recordings / "catalog.sqlite3"
            if existing.exists(): shutil.copyfile(existing, recordings / ("catalog.sqlite3.before-restore." + uuid.uuid4().hex))
            os.replace(temporary, existing)
        finally:
            temporary.unlink(missing_ok=True)
        for suffix in ("-wal", "-shm"):
            (recordings / ("catalog.sqlite3" + suffix)).unlink(missing_ok=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["create", "restore"])
    parser.add_argument("--data", required=True, type=pathlib.Path)
    parser.add_argument("--recordings", required=True, type=pathlib.Path)
    parser.add_argument("--snapshot", required=True, type=pathlib.Path)
    parser.add_argument("--version", default="unknown")
    args = parser.parse_args()
    if not all(p.is_absolute() for p in (args.data,args.recordings,args.snapshot)): raise SystemExit(2)
    if args.action == "create": snapshot(args.data,args.recordings,args.snapshot,args.version)
    else: restore(args.snapshot,args.data,args.recordings)
