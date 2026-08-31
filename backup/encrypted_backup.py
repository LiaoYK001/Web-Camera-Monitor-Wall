#!/usr/bin/env python3
"""Encrypted, integrity-checked WebOBS configuration backup and restore."""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import ctypes.util
import hashlib
import json
import os
import pathlib
import shutil
import sqlite3
import struct
import tarfile
import tempfile
import time
import uuid
from typing import BinaryIO


MAGIC = b"WEBOBSB1"
CHUNK = 1024 * 1024
MAX_FILE = 1024 * 1024 * 1024
MAX_TOTAL = 8 * 1024 * 1024 * 1024


class BackupError(RuntimeError):
    pass


class SodiumStream:
    def __init__(self, library: str = ""):
        name = library or os.environ.get("WEBOBS_LIBSODIUM_LIBRARY") or ctypes.util.find_library("sodium")
        if not name:
            raise BackupError("libsodium runtime is unavailable")
        self.lib = ctypes.CDLL(name)
        if self.lib.sodium_init() < 0:
            raise BackupError("libsodium initialization failed")
        self.state_bytes = self.lib.crypto_secretstream_xchacha20poly1305_statebytes()
        self.header_bytes = self.lib.crypto_secretstream_xchacha20poly1305_headerbytes()
        self.abytes = self.lib.crypto_secretstream_xchacha20poly1305_abytes()
        self.lib.crypto_secretstream_xchacha20poly1305_init_push.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        self.lib.crypto_secretstream_xchacha20poly1305_push.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulonglong), ctypes.c_void_p,
            ctypes.c_ulonglong, ctypes.c_void_p, ctypes.c_ulonglong, ctypes.c_ubyte]
        self.lib.crypto_secretstream_xchacha20poly1305_init_pull.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        self.lib.crypto_secretstream_xchacha20poly1305_pull.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulonglong), ctypes.POINTER(ctypes.c_ubyte),
            ctypes.c_void_p, ctypes.c_ulonglong, ctypes.c_void_p, ctypes.c_ulonglong]

    def encrypt(self, source: BinaryIO, destination: BinaryIO, key: bytes) -> None:
        if len(key) != 32:
            raise BackupError("backup key must contain exactly 32 bytes")
        state = ctypes.create_string_buffer(self.state_bytes)
        header = ctypes.create_string_buffer(self.header_bytes)
        key_buffer = ctypes.create_string_buffer(key)
        if self.lib.crypto_secretstream_xchacha20poly1305_init_push(state, header, key_buffer) != 0:
            raise BackupError("backup encryption initialization failed")
        destination.write(MAGIC + header.raw)
        current = source.read(CHUNK)
        while current:
            following = source.read(CHUNK)
            tag = 3 if not following else 0
            encrypted = ctypes.create_string_buffer(len(current) + self.abytes)
            encrypted_length = ctypes.c_ulonglong()
            message = ctypes.create_string_buffer(current)
            if self.lib.crypto_secretstream_xchacha20poly1305_push(
                    state, encrypted, ctypes.byref(encrypted_length), message, len(current), None, 0, tag) != 0:
                raise BackupError("backup encryption failed")
            destination.write(struct.pack(">I", encrypted_length.value) + encrypted.raw[:encrypted_length.value])
            current = following

    def decrypt(self, source: BinaryIO, destination: BinaryIO, key: bytes) -> None:
        if len(key) != 32 or source.read(len(MAGIC)) != MAGIC:
            raise BackupError("backup key or format is invalid")
        header = source.read(self.header_bytes)
        if len(header) != self.header_bytes:
            raise BackupError("encrypted backup header is truncated")
        state = ctypes.create_string_buffer(self.state_bytes)
        if self.lib.crypto_secretstream_xchacha20poly1305_init_pull(
                state, ctypes.create_string_buffer(header), ctypes.create_string_buffer(key)) != 0:
            raise BackupError("backup decryption initialization failed")
        final_seen = False
        while length_bytes := source.read(4):
            if len(length_bytes) != 4 or final_seen:
                raise BackupError("encrypted backup framing is invalid")
            length = struct.unpack(">I", length_bytes)[0]
            if length < self.abytes or length > CHUNK + self.abytes:
                raise BackupError("encrypted backup chunk length is invalid")
            encrypted = source.read(length)
            if len(encrypted) != length:
                raise BackupError("encrypted backup is truncated")
            plaintext = ctypes.create_string_buffer(length)
            plaintext_length = ctypes.c_ulonglong()
            tag = ctypes.c_ubyte()
            if self.lib.crypto_secretstream_xchacha20poly1305_pull(
                    state, plaintext, ctypes.byref(plaintext_length), ctypes.byref(tag),
                    ctypes.create_string_buffer(encrypted), length, None, 0) != 0:
                raise BackupError("encrypted backup authentication failed")
            destination.write(plaintext.raw[:plaintext_length.value])
            final_seen = tag.value == 3
        if not final_seen:
            raise BackupError("encrypted backup has no authenticated final chunk")


def read_key(path: pathlib.Path) -> bytes:
    if not path.is_file() or path.is_symlink() or path.stat().st_size != 32:
        raise BackupError("backup key must be a private 32-byte secret file")
    return path.read_bytes()


def safe_files(root: pathlib.Path) -> list[pathlib.Path]:
    if not root.is_dir() or root.is_symlink():
        raise BackupError("configuration root is unavailable or unsafe")
    result = []
    total = 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise BackupError("configuration contains a symbolic link")
        if path.is_dir():
            continue
        if not path.is_file() or path.name.endswith(("-wal", "-shm")) or path.name.startswith(".webobs-"):
            continue
        size = path.stat().st_size
        if size > MAX_FILE:
            raise BackupError("configuration file exceeds backup limit")
        total += size
        if total > MAX_TOTAL:
            raise BackupError("configuration backup exceeds total limit")
        result.append(path)
    return result


def sqlite_snapshot(source: pathlib.Path, destination: pathlib.Path) -> None:
    source_db = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True, timeout=10)
    target_db = sqlite3.connect(destination)
    try:
        source_db.backup(target_db)
        if target_db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise BackupError("database snapshot integrity check failed")
    finally:
        target_db.close()
        source_db.close()


def create(config_root: pathlib.Path, backup_root: pathlib.Path, key_file: pathlib.Path,
           sodium: SodiumStream) -> pathlib.Path:
    backup_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if backup_root.is_symlink():
        raise BackupError("backup root is unsafe")
    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    output = backup_root / f"webobs-config-{timestamp}-{uuid.uuid4().hex[:8]}.wobk"
    with tempfile.TemporaryDirectory(prefix=".webobs-backup-", dir=backup_root) as directory:
        staging = pathlib.Path(directory) / "webobs"
        staging.mkdir()
        manifest = {"format": 1, "createdAt": int(time.time()), "schema": "v2-M7", "files": []}
        for source in safe_files(config_root):
            relative = source.relative_to(config_root)
            destination = staging / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.suffix in {".db", ".sqlite3"}:
                sqlite_snapshot(source, destination)
            else:
                shutil.copyfile(source, destination)
            os.chmod(destination, 0o600)
            manifest["files"].append({"path": relative.as_posix(), "size": destination.stat().st_size,
                                      "sha256": hashlib.sha256(destination.read_bytes()).hexdigest()})
        (staging / "backup-manifest.json").write_text(
            json.dumps(manifest, separators=(",", ":"), sort_keys=True) + "\n", encoding="utf-8")
        tar_path = pathlib.Path(directory) / "snapshot.tar.gz"
        with tarfile.open(tar_path, "w:gz", format=tarfile.PAX_FORMAT) as archive:
            archive.add(staging, arcname="webobs", recursive=True)
        temporary = output.with_name(f".{output.name}.tmp")
        with tar_path.open("rb") as source, temporary.open("xb") as destination:
            sodium.encrypt(source, destination, read_key(key_file))
            destination.flush()
            os.fsync(destination.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, output)
        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        checksum = output.with_suffix(output.suffix + ".sha256")
        checksum.write_text(f"{digest}  {output.name}\n", encoding="ascii")
        os.chmod(checksum, 0o600)
    return output


def verify_tree(root: pathlib.Path) -> None:
    manifest_path = root / "backup-manifest.json"
    value = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("format") != 1 or not isinstance(value.get("files"), list):
        raise BackupError("backup manifest is invalid")
    expected = set()
    for item in value["files"]:
        if not isinstance(item, dict) or set(item) != {"path", "size", "sha256"}:
            raise BackupError("backup manifest entry is invalid")
        relative = pathlib.PurePosixPath(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise BackupError("backup manifest path is unsafe")
        path = root.joinpath(*relative.parts)
        if not path.is_file() or path.is_symlink() or path.stat().st_size != item["size"] or \
                hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            raise BackupError("backup file integrity verification failed")
        expected.add(relative.as_posix())
        if path.suffix in {".db", ".sqlite3"}:
            connection = sqlite3.connect(path)
            try:
                if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise BackupError("restored database integrity check failed")
            finally:
                connection.close()
    actual = {path.relative_to(root).as_posix() for path in root.rglob("*")
              if path.is_file() and path.name != "backup-manifest.json"}
    if actual != expected:
        raise BackupError("backup contains undeclared files")


def restore(config_root: pathlib.Path, archive_path: pathlib.Path, key_file: pathlib.Path,
            sodium: SodiumStream, confirmed: bool) -> pathlib.Path:
    if not confirmed or not archive_path.is_file() or archive_path.is_symlink():
        raise BackupError("restore confirmation and a regular backup file are required")
    parent = config_root.parent
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix=".webobs-decrypt-", dir=parent) as directory:
        temporary_root = pathlib.Path(directory)
        tar_path = temporary_root / "snapshot.tar.gz"
        with archive_path.open("rb") as source, tar_path.open("xb") as destination:
            sodium.decrypt(source, destination, read_key(key_file))
        extracted = temporary_root / "extract"
        extracted.mkdir()
        with tarfile.open(tar_path, "r:gz") as bundle:
            for member in bundle.getmembers():
                path = pathlib.PurePosixPath(member.name)
                if path.is_absolute() or ".." in path.parts or member.issym() or member.islnk() or \
                        not (member.isdir() or member.isfile()) or not path.parts or path.parts[0] != "webobs":
                    raise BackupError("backup archive member is unsafe")
                target = extracted.joinpath(*path.parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    source = bundle.extractfile(member)
                    if source is None:
                        raise BackupError("backup member cannot be read")
                    with target.open("xb") as destination:
                        shutil.copyfileobj(source, destination, CHUNK)
                    os.chmod(target, 0o600)
        candidate = extracted / "webobs"
        verify_tree(candidate)
        activated = parent / f".webobs-restore-{uuid.uuid4().hex}"
        shutil.copytree(candidate, activated)
        rollback = parent / f".webobs-rollback-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
        if config_root.exists():
            os.replace(config_root, rollback)
        try:
            os.replace(activated, config_root)
        except Exception:
            if rollback.exists() and not config_root.exists():
                os.replace(rollback, config_root)
            raise
        return rollback


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices={"create", "restore", "schedule"})
    parser.add_argument("archive", nargs="?")
    parser.add_argument("--config-root", default=os.environ.get("WEBOBS_BACKUP_CONFIG_ROOT", "/config/webobs"))
    parser.add_argument("--backup-root", default=os.environ.get("WEBOBS_BACKUP_ROOT", "/backups"))
    parser.add_argument("--key-file", default=os.environ.get("WEBOBS_BACKUP_KEY_FILE", "/run/secrets/webobs_backup_key"))
    args = parser.parse_args()
    config_root, backup_root, key_file = map(pathlib.Path, (args.config_root, args.backup_root, args.key_file))
    if any(not path.is_absolute() for path in (config_root, backup_root, key_file)):
        raise SystemExit("backup paths must be absolute")
    sodium = SodiumStream()
    if args.action == "create":
        create(config_root, backup_root, key_file, sodium)
    elif args.action == "restore":
        if not args.archive:
            raise SystemExit("restore requires an encrypted archive")
        restore(config_root, pathlib.Path(args.archive), key_file, sodium,
                os.environ.get("WEBOBS_RESTORE_CONFIRM") == "replace-config")
    else:
        while True:
            time.sleep(900)
            create(config_root, backup_root, key_file, sodium)


if __name__ == "__main__":
    main()
