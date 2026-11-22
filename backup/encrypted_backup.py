#!/usr/bin/env python3
"""Encrypted, integrity-checked WebOBS configuration backup and restore."""

from __future__ import annotations

import sys as _runtime_sys
from pathlib import Path as _RuntimePath
_runtime_sys.path.insert(0, str(_RuntimePath(__file__).resolve().parents[1]))
from runtime_support import service_port, service_http, service_rtsp, install_owner_shutdown, serve_owned, STOP, sync_directory

import argparse
import contextlib
import ctypes
import ctypes.util
import hashlib
import http.client
import importlib.machinery
import importlib.util
import json
import os
import pathlib
import re
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


def file_sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


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


def stage_tree(source_root: pathlib.Path, staging: pathlib.Path, schema: str,
               excluded_parts: set[str] = frozenset()) -> None:
    staging.mkdir()
    manifest = {"format": 1, "createdAt": int(time.time()), "schema": schema, "files": []}
    for source in safe_files(source_root):
        relative = source.relative_to(source_root)
        if excluded_parts.intersection(relative.parts):
            continue
        destination = staging / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.suffix in {".db", ".sqlite3"}:
            sqlite_snapshot(source, destination)
        else:
            shutil.copyfile(source, destination)
        os.chmod(destination, 0o600)
        manifest["files"].append({"path": relative.as_posix(), "size": destination.stat().st_size,
                                  "sha256": file_sha256(destination)})
    (staging / "backup-manifest.json").write_text(
        json.dumps(manifest, separators=(",", ":"), sort_keys=True) + "\n", encoding="utf-8")


def create(config_root: pathlib.Path, backup_root: pathlib.Path, key_file: pathlib.Path,
           sodium: SodiumStream, native_profile: pathlib.Path | None = None) -> pathlib.Path:
    backup_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if backup_root.is_symlink():
        raise BackupError("backup root is unsafe")
    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    output = backup_root / f"webobs-config-{timestamp}-{uuid.uuid4().hex[:8]}.wobk"
    with tempfile.TemporaryDirectory(prefix=".webobs-backup-", dir=backup_root) as directory:
        staging = pathlib.Path(directory) / "webobs"
        stage_tree(config_root, staging, "v2-M7")
        native_staging = None
        if native_profile is not None and native_profile.is_dir() and not native_profile.is_symlink():
            native_staging = pathlib.Path(directory) / "webobs-native-profile"
            stage_tree(native_profile, native_staging, "native-profile-v1",
                       frozenset({"logs", "crashes", "Crashpad"}))
        tar_path = pathlib.Path(directory) / "snapshot.tar.gz"
        with tarfile.open(tar_path, "w:gz", format=tarfile.PAX_FORMAT) as archive:
            archive.add(staging, arcname="webobs", recursive=True)
            if native_staging is not None:
                archive.add(native_staging, arcname="webobs-native-profile", recursive=True)
        temporary = output.with_name(f".{output.name}.tmp")
        with tar_path.open("rb") as source, temporary.open("xb") as destination:
            sodium.encrypt(source, destination, read_key(key_file))
            destination.flush()
            os.fsync(destination.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, output)
        digest = file_sha256(output)
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
                file_sha256(path) != item["sha256"]:
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


JOURNAL_NAME = ".webobs-restore-journal.json"
MAX_JOURNAL = 4096


def _remove_tree(path: pathlib.Path | None) -> None:
    """Delete a staged copy that never became the live directory."""
    if path is None:
        return
    if path.is_symlink():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists():
        path.unlink()


def _journal_path(parent: pathlib.Path) -> pathlib.Path:
    return parent / JOURNAL_NAME


def _write_journal(path: pathlib.Path, payload: dict) -> None:
    """Persist the swap progress so a killed process cannot hide a half swap."""
    temporary = path.with_name(f".{path.name}.tmp")
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    if len(body.encode("utf-8")) > MAX_JOURNAL:
        raise BackupError("restore journal exceeds its bounded size")
    with temporary.open("wb") as destination:
        destination.write(body.encode("utf-8") + b"\n")
        destination.flush()
        os.fsync(destination.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _journal_paths(payload: dict) -> dict:
    keys = ("configRoot", "configActivated", "configRollback", "nativeProfile",
            "nativeActivated", "nativeRollback")
    if set(payload) - set(keys) - {"schema", "state", "createdAt", "archive", "archiveSha256"}:
        raise BackupError("restore journal is invalid")
    paths = {}
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        if not isinstance(value, str) or not pathlib.Path(value).is_absolute():
            raise BackupError("restore journal is invalid")
        paths[key] = pathlib.Path(value)
    return paths


def recover_interrupted(journal_path: pathlib.Path) -> str | None:
    """Converge a half restore left by a crash into one consistent pair.

    The staged copy names tell which side already landed: the configuration
    directory is committed exactly when its staged copy is gone. Before that
    point BOTH previous halves are restored, including a native profile that
    had already been swapped out; after it the remaining staged native profile
    is landed, so configuration and native profile always move as a pair.
    Anything unexpected at a live path is parked instead of deleted, and
    previous data is never deleted here.
    """
    if not journal_path.exists():
        return None
    if journal_path.is_symlink():
        raise BackupError("restore journal is unsafe")
    if journal_path.stat().st_size > MAX_JOURNAL:
        raise BackupError("restore journal exceeds its bounded size")
    try:
        payload = json.loads(journal_path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise BackupError("restore journal is unreadable") from error
    if not isinstance(payload, dict) or payload.get("schema") != 1 or payload.get("state") != "prepared":
        raise BackupError("restore journal is invalid")
    paths = _journal_paths(payload)
    activated = paths.get("configActivated")
    activated_native = paths.get("nativeActivated")
    rollback = paths.get("configRollback")
    native_rollback = paths.get("nativeRollback")
    native_profile = paths.get("nativeProfile")
    config_root = paths.get("configRoot")
    if activated is None:
        raise BackupError("restore journal is invalid")
    if activated.exists():
        # The configuration directory never landed: put the previous pair back.
        if config_root is not None and not config_root.exists() and rollback is not None and rollback.exists():
            os.replace(rollback, config_root)
        # The native half can already be swapped out in this same window. Leaving
        # it parked would pair a recovered configuration with a missing OBS
        # profile, and nothing else ever claims that directory again.
        if (native_profile is not None and not native_profile.exists()
                and native_rollback is not None and native_rollback.exists()):
            os.replace(native_rollback, native_profile)
        _remove_tree(activated_native)
        _remove_tree(activated)
        journal_path.unlink()
        return "rolled-back"
    if activated_native is not None and activated_native.exists():
        if native_profile is None:
            _remove_tree(activated_native)
        elif native_profile.exists():
            # The configuration half landed, so the staged copy is the profile that
            # pair belongs to. Whatever stands at the live path was created after
            # the crash: park it (never delete) and land the matching pair.
            parked = native_profile.parent / \
                f".webobs-native-parked-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:8]}"
            os.replace(native_profile, parked)
            os.replace(activated_native, native_profile)
        else:
            os.replace(activated_native, native_profile)
    journal_path.unlink()
    return "completed"


def restore(config_root: pathlib.Path, archive_path: pathlib.Path, key_file: pathlib.Path,
            sodium: SodiumStream, confirmed: bool,
            native_profile: pathlib.Path | None = None) -> pathlib.Path:
    if not confirmed or not archive_path.is_file() or archive_path.is_symlink():
        raise BackupError("restore confirmation and a regular backup file are required")
    parent = config_root.parent
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    journal_path = _journal_path(parent)
    recover_interrupted(journal_path)
    with tempfile.TemporaryDirectory(prefix=".webobs-decrypt-", dir=parent) as directory:
        temporary_root = pathlib.Path(directory)
        tar_path = temporary_root / "snapshot.tar.gz"
        with archive_path.open("rb") as source, tar_path.open("xb") as destination:
            sodium.decrypt(source, destination, read_key(key_file))
        extracted = temporary_root / "extract"
        extracted.mkdir()
        native_candidate = None
        with tarfile.open(tar_path, "r:gz") as bundle:
            for member in bundle.getmembers():
                path = pathlib.PurePosixPath(member.name)
                if path.is_absolute() or ".." in path.parts or member.issym() or member.islnk() or \
                        not (member.isdir() or member.isfile()) or not path.parts or \
                        path.parts[0] not in {"webobs", "webobs-native-profile"}:
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
        native_candidate = extracted / "webobs-native-profile"
        if native_candidate.exists():
            verify_tree(native_candidate)
            if native_profile is None:
                # Restoring only the configuration half of an archive that also
                # carries a native profile would leave a mismatched pair.
                raise BackupError("restore must name the native profile of this archive")
        else:
            native_candidate = None
        activated = parent / f".webobs-restore-{uuid.uuid4().hex}"
        activated_native = None
        if native_candidate is not None:
            native_profile = pathlib.Path(native_profile)
            activated_native = native_profile.parent / f".webobs-native-restore-{uuid.uuid4().hex}"
        journal = {"schema": 1, "state": "prepared", "createdAt": time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()),
                   "archive": str(archive_path.resolve()), "archiveSha256": file_sha256(archive_path),
                   "configRoot": str(config_root), "configActivated": str(activated),
                   "configRollback": None,
                   "nativeProfile": str(native_profile) if native_profile is not None else None,
                   "nativeActivated": str(activated_native) if activated_native is not None else None,
                   "nativeRollback": None}
        try:
            shutil.copytree(candidate, activated)
            if activated_native is not None:
                shutil.copytree(native_candidate, activated_native)
        except Exception:
            _remove_tree(activated_native)
            _remove_tree(activated)
            raise
        _write_journal(journal_path, journal)
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        rollback = parent / f".webobs-rollback-{stamp}-{uuid.uuid4().hex[:8]}"
        native_rollback = None
        try:
            if config_root.exists():
                os.replace(config_root, rollback)
                journal["configRollback"] = str(rollback)
                _write_journal(journal_path, journal)
            if activated_native is not None:
                native_rollback = native_profile.parent / \
                    f".webobs-native-rollback-{stamp}-{uuid.uuid4().hex[:8]}"
                if native_profile.exists():
                    os.replace(native_profile, native_rollback)
                    journal["nativeRollback"] = str(native_rollback)
                    _write_journal(journal_path, journal)
            os.replace(activated, config_root)
            if activated_native is not None:
                os.replace(activated_native, native_profile)
        except Exception:
            if rollback.exists() and not config_root.exists():
                os.replace(rollback, config_root)
            if native_rollback is not None:
                if native_profile.exists():
                    # A live profile appeared during this failed swap; keep those
                    # bytes parked rather than delete them on an error path.
                    parked = native_profile.parent / \
                        f".webobs-native-parked-{stamp}-{uuid.uuid4().hex[:8]}"
                    os.replace(native_profile, parked)
                os.replace(native_rollback, native_profile)
            _remove_tree(activated_native)
            _remove_tree(activated)
            journal_path.unlink(missing_ok=True)
            raise
        journal_path.unlink(missing_ok=True)
        return rollback


def cluster_request(port: int, token: str, path: str, value: dict) -> dict:
    if not re.fullmatch(r"[0-9a-f]{64}", token) or not path.startswith("/backup-jobs"):
        raise BackupError("backup worker control authentication is unavailable")
    body = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request("POST", path, body=body, headers={
            "Content-Type": "application/json", "Content-Length": str(len(body)),
            "X-WebObs-Internal-Admin": token,
        })
        response = connection.getresponse()
        payload = response.read(1024 * 1024 + 1)
        if response.status >= 300 or len(payload) > 1024 * 1024:
            raise BackupError("backup worker control request was rejected")
        return json.loads(payload) if payload else {}
    except (OSError, http.client.HTTPException, json.JSONDecodeError) as error:
        raise BackupError("backup worker control request failed") from error
    finally:
        connection.close()


def upload_s3(path: pathlib.Path, target_id: str) -> str:
    """Upload a completed encrypted backup through the pinned S3 implementation."""
    configured_target = os.environ.get("WEBOBS_BACKUP_S3_TARGET_ID", "")
    config_path = pathlib.Path(os.environ.get("WEBOBS_BACKUP_S3_CONFIG", "/config/webobs/archive.json"))
    archive_program = pathlib.Path(os.environ.get("WEBOBS_ARCHIVE_PYTHON_MODULE") or os.environ.get(
        "WEBOBS_ARCHIVE_COMMAND", "/opt/webobs/bin/webobs-s3-archive"))
    if not configured_target or target_id != configured_target or not config_path.is_absolute() or \
            not archive_program.is_absolute() or not archive_program.is_file():
        raise BackupError("nonlocal_target_unavailable")
    loader = importlib.machinery.SourceFileLoader("webobs_backup_s3", str(archive_program))
    specification = importlib.util.spec_from_loader(loader.name, loader)
    if specification is None or specification.loader is None:
        raise BackupError("nonlocal_target_unavailable")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    digest = file_sha256(path)
    key = f"backups/{digest[:2]}/{digest}.wobk"
    try:
        config = module.load_config(config_path)
        client = module.S3Client(config, os.environ.get("WEBOBS_ARCHIVE_CA_FILE", ""))
        client.upload_verified(path, key, digest, path.stat().st_size)
    except Exception as error:
        raise BackupError("s3_backup_failed") from error
    return digest


def schedule(config_root: pathlib.Path, backup_root: pathlib.Path, key_file: pathlib.Path,
             sodium: SodiumStream) -> None:
    token = os.environ.get("WEBOBS_CLUSTER_INTERNAL_TOKEN", "")
    port = int(os.environ.get("WEBOBS_CLUSTER_INTERNAL_PORT", "8095"))
    next_scheduled = time.monotonic() + 15 * 60
    while not STOP.is_set():
        job: dict | None = None
        with contextlib.suppress(BackupError):
            job = cluster_request(port, token, "/backup-jobs/claim", {}).get("job")
        if job is not None:
            try:
                output = create(config_root, backup_root, key_file, sodium,
                                pathlib.Path(os.environ["WEBOBS_BACKUP_NATIVE_PROFILE"])
                                if os.environ.get("WEBOBS_BACKUP_NATIVE_PROFILE") else None)
                digest = file_sha256(output)
                if job.get("targetId") != "local":
                    digest = upload_s3(output, str(job.get("targetId", "")))
                cluster_request(port, token, f"/backup-jobs/{job['id']}/result", {
                    "state": "completed", "sha256": digest,
                })
            except BackupError as error:
                code = str(error) if re.fullmatch(r"[A-Za-z0-9._-]{1,64}", str(error)) else type(error).__name__
                with contextlib.suppress(BackupError):
                    cluster_request(port, token, f"/backup-jobs/{job['id']}/result", {
                        "state": "failed", "errorCode": code,
                    })
        if time.monotonic() >= next_scheduled:
            create(config_root, backup_root, key_file, sodium,
                   pathlib.Path(os.environ["WEBOBS_BACKUP_NATIVE_PROFILE"])
                   if os.environ.get("WEBOBS_BACKUP_NATIVE_PROFILE") else None)
            next_scheduled = time.monotonic() + 15 * 60
        STOP.wait(2)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices={"create", "restore", "recover", "schedule"})
    parser.add_argument("archive", nargs="?")
    parser.add_argument("--config-root", default=os.environ.get("WEBOBS_BACKUP_CONFIG_ROOT", "/config/webobs"))
    parser.add_argument("--native-profile-root", default=os.environ.get("WEBOBS_BACKUP_NATIVE_PROFILE", ""))
    parser.add_argument("--backup-root", default=os.environ.get("WEBOBS_BACKUP_ROOT", "/backups"))
    parser.add_argument("--key-file", default=os.environ.get("WEBOBS_BACKUP_KEY_FILE", "/run/secrets/webobs_backup_key"))
    args = parser.parse_args()
    config_root, backup_root, key_file = map(pathlib.Path, (args.config_root, args.backup_root, args.key_file))
    native_profile = pathlib.Path(args.native_profile_root) if args.native_profile_root else None
    if any(not path.is_absolute() for path in (config_root, backup_root, key_file)) or \
            (native_profile is not None and not native_profile.is_absolute()):
        raise SystemExit("backup paths must be absolute")
    sodium = SodiumStream()
    if args.action == "create":
        create(config_root, backup_root, key_file, sodium, native_profile)
    elif args.action == "restore":
        if not args.archive:
            raise SystemExit("restore requires an encrypted archive")
        restore(config_root, pathlib.Path(args.archive), key_file, sodium,
                os.environ.get("WEBOBS_RESTORE_CONFIRM") == "replace-config", native_profile)
    elif args.action == "recover":
        print(recover_interrupted(_journal_path(config_root.parent)) or "none")
    else:
        install_owner_shutdown(STOP.set)
        schedule(config_root, backup_root, key_file, sodium)


if __name__ == "__main__":
    main()
