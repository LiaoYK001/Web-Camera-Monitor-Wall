#!/usr/bin/env python3
"""WebOBS per-camera NVR and evidence service.

The HTTP listener is intentionally loopback-only. Public authentication, Origin
checks, and response hardening remain the responsibility of webobsd.
"""

from __future__ import annotations

import sys as _runtime_sys
from pathlib import Path as _RuntimePath
_runtime_sys.path.insert(0, str(_RuntimePath(__file__).resolve().parents[1]))
from runtime_support import service_port, service_http, service_rtsp, install_owner_shutdown, serve_owned, STOP, sync_directory
_runtime_sys.path.insert(0, str(_RuntimePath(__file__).resolve().parent))
from evidence import EvidenceError, ExportJobs, export_evidence

import argparse
import contextlib
import datetime as dt
import hashlib
import http.server
import json
import os
import pathlib
import re
import shutil
import signal
import sqlite3
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import uuid
import functools
import email.utils
from dataclasses import dataclass, field
from typing import Any

MAX_BODY = 1024 * 1024

def request_capture_stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == 'nt':
        # terminate() uses TerminateProcess on Windows and cannot flush MP4.
        # This private pipe accepts FFmpeg's bounded normal-quit command only.
        if process.stdin is None:
            raise RuntimeError('recording shutdown pipe is unavailable')
        try:
            process.stdin.write(b'q\n')
            process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            if process.poll() is None:raise RuntimeError('recording normal shutdown failed')
    else:
        process.terminate()

CAMERA_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
SEGMENT_ID = re.compile(r"^[a-f0-9]{32}$")
ARTIFACT_ID = re.compile(r"^[a-f0-9]{32}$")
SAFE_ARTIFACT_NAME = re.compile(r"^[A-Za-z0-9._-]{1,160}$")
VOLUME_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
POLICIES = {"continuous", "scheduled", "event", "off"}
MODES = {"auto", "copy", "transcode"}
STREAMS = {"main", "sub"}


class ConfigError(ValueError):
    pass


def export_operation(function):
    @functools.wraps(function)
    def wrapped(self, *args, **kwargs):
        if not self.export_slots.acquire(blocking=False):
            raise EvidenceError("export_capacity", "Evidence processing is busy; try later", 503)
        with self.config_lock:
            self.active_exports += 1
        try:
            return function(self, *args, **kwargs)
        finally:
            with self.config_lock:
                self.active_exports -= 1
            self.export_slots.release()
    return wrapped


def utc_ms() -> int:
    return time.time_ns() // 1_000_000


def atomic_json(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}.{uuid.uuid4().hex}")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(value, output, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def private_json(path: pathlib.Path) -> Any:
    if path.is_symlink():
        raise ConfigError("configuration path must not be a symbolic link")
    if path.stat().st_size > MAX_BODY:
        raise ConfigError("configuration exceeds 1 MiB")
    with path.open("r", encoding="utf-8") as source:
        return json.load(source)


def safe_rtsp(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or len(value) > 2048 or not re.match(r"^rtsps?://[^\s/?#]+", value):
        raise ConfigError(f"{field_name} must be an absolute RTSP URL")
    return value


def bounded_int(value: Any, minimum: int, maximum: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ConfigError(f"{field_name} must be between {minimum} and {maximum}")
    return value


def validate_schedule(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 32:
        raise ConfigError("schedule must contain at most 32 windows")
    result = []
    for window in value:
        if not isinstance(window, dict) or set(window) != {"days", "start", "end"}:
            raise ConfigError("schedule windows require only days, start, and end")
        days = window["days"]
        if not isinstance(days, list) or not days or len(set(days)) != len(days) or any(
            isinstance(day, bool) or not isinstance(day, int) or day < 0 or day > 6 for day in days
        ):
            raise ConfigError("schedule days must be unique UTC weekdays from 0 through 6")
        for name in ("start", "end"):
            if not isinstance(window[name], str) or not re.match(r"^(?:[01]\d|2[0-3]):[0-5]\d$", window[name]):
                raise ConfigError(f"schedule {name} must use HH:MM UTC")
        result.append({"days": sorted(days), "start": window["start"], "end": window["end"]})
    return result


def validate_config(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - {
        "schemaVersion", "segmentSeconds", "maxAgeHours", "maxBytes", "minFreeBytes", "cameras"
    }:
        raise ConfigError("NVR configuration contains unsupported fields")
    if value.get("schemaVersion") != 1:
        raise ConfigError("NVR schemaVersion must be 1")
    result: dict[str, Any] = {
        "schemaVersion": 1,
        "segmentSeconds": bounded_int(value.get("segmentSeconds", 60), 2, 3600, "segmentSeconds"),
        "maxAgeHours": bounded_int(value.get("maxAgeHours", 720), 1, 24 * 3650, "maxAgeHours"),
        "maxBytes": bounded_int(value.get("maxBytes", 0), 0, 1 << 60, "maxBytes"),
        "minFreeBytes": bounded_int(value.get("minFreeBytes", 1 << 30), 0, 1 << 60, "minFreeBytes"),
        "cameras": [],
    }
    cameras = value.get("cameras", [])
    if not isinstance(cameras, list) or len(cameras) > 64:
        raise ConfigError("cameras must contain at most 64 entries")
    seen: set[str] = set()
    for raw in cameras:
        allowed = {
            "id", "name", "policy", "mainUrl", "subUrl", "stream", "mode", "transport",
            "cameraId", "mainProfileId", "subProfileId", "segmentSeconds", "maxAgeHours",
            "maxBytes", "preEventSeconds", "schedule",
        }
        if not isinstance(raw, dict) or set(raw) - allowed:
            raise ConfigError("camera configuration contains unsupported fields")
        camera_id = raw.get("id")
        if not isinstance(camera_id, str) or not CAMERA_ID.fullmatch(camera_id) or camera_id in seen:
            raise ConfigError("camera ids must be unique safe identifiers")
        seen.add(camera_id)
        name = raw.get("name", camera_id)
        if not isinstance(name, str) or not name or len(name) > 128 or any(ord(char) < 32 for char in name):
            raise ConfigError("camera name is invalid")
        policy = raw.get("policy", "off")
        stream = raw.get("stream", "main")
        mode = raw.get("mode", "auto")
        transport = raw.get("transport", "tcp")
        if policy not in POLICIES or stream not in STREAMS or mode not in MODES or transport not in {"tcp", "udp"}:
            raise ConfigError("camera policy, stream, mode, or transport is invalid")
        registry_camera_id = raw.get("cameraId", "")
        if registry_camera_id:
            if not isinstance(registry_camera_id, str) or not CAMERA_ID.fullmatch(registry_camera_id):
                raise ConfigError("cameraId must be a safe Camera Registry identifier")
            if raw.get("mainUrl") or raw.get("subUrl"):
                raise ConfigError("Camera Registry references cannot be combined with raw RTSP URLs")
            main_profile_id = raw.get("mainProfileId", "main")
            sub_profile_id = raw.get("subProfileId", "")
            if not isinstance(main_profile_id, str) or not CAMERA_ID.fullmatch(main_profile_id):
                raise ConfigError("mainProfileId is invalid")
            if sub_profile_id and (not isinstance(sub_profile_id, str) or not CAMERA_ID.fullmatch(sub_profile_id)):
                raise ConfigError("subProfileId is invalid")
            if stream == "sub" and not sub_profile_id:
                raise ConfigError("sub stream selection requires subProfileId")
            main_url = ""
            sub_url = ""
        else:
            main_profile_id = ""
            sub_profile_id = ""
            main_url = safe_rtsp(raw.get("mainUrl"), "mainUrl")
            sub_url = raw.get("subUrl", "")
            if sub_url:
                sub_url = safe_rtsp(sub_url, "subUrl")
            if stream == "sub" and not sub_url:
                raise ConfigError("sub stream selection requires subUrl")
        result["cameras"].append({
            "id": camera_id,
            "name": name,
            "policy": policy,
            "mainUrl": main_url,
            "subUrl": sub_url,
            "cameraId": registry_camera_id,
            "mainProfileId": main_profile_id,
            "subProfileId": sub_profile_id,
            "stream": stream,
            "mode": mode,
            "transport": transport,
            "segmentSeconds": bounded_int(raw.get("segmentSeconds", result["segmentSeconds"]), 2, 3600, "camera segmentSeconds"),
            "maxAgeHours": bounded_int(raw.get("maxAgeHours", result["maxAgeHours"]), 1, 24 * 3650, "camera maxAgeHours"),
            "maxBytes": bounded_int(raw.get("maxBytes", 0), 0, 1 << 60, "camera maxBytes"),
            "preEventSeconds": bounded_int(raw.get("preEventSeconds", 0), 0, 300, "preEventSeconds"),
            "schedule": validate_schedule(raw.get("schedule")),
        })
    return result


def redacted_config(config: dict[str, Any]) -> dict[str, Any]:
    result = json.loads(json.dumps(config))
    for camera in result["cameras"]:
        if camera["mainUrl"]:
            camera["mainUrl"] = "rtsp://***"
        if camera["subUrl"]:
            camera["subUrl"] = "rtsp://***"
    return result


def resolve_registry_source(camera: dict[str, Any]) -> str:
    profile_id = camera["subProfileId"] if camera["stream"] == "sub" else camera["mainProfileId"]
    path = "/resolve/{}/{}".format(
        urllib.parse.quote(camera["cameraId"], safe=""), urllib.parse.quote(profile_id, safe="")
    )
    request = urllib.request.Request(service_http(8092, '') + path, method="GET")
    with urllib.request.urlopen(request, timeout=3) as response:
        body = response.read(MAX_BODY + 1)
    if len(body) > MAX_BODY:
        raise RuntimeError("Camera Registry response is too large")
    resolved = json.loads(body)
    endpoint = resolved.get("endpoint", "") if isinstance(resolved, dict) else ""
    return safe_rtsp(endpoint, "resolved endpoint")


def schedule_active(camera: dict[str, Any], now: dt.datetime) -> bool:
    if camera["policy"] == "continuous":
        return True
    if camera["policy"] != "scheduled":
        return False
    minute = now.hour * 60 + now.minute
    for window in camera["schedule"]:
        start_h, start_m = map(int, window["start"].split(":"))
        end_h, end_m = map(int, window["end"].split(":"))
        start = start_h * 60 + start_m
        end = end_h * 60 + end_m
        if start <= end:
            if now.weekday() in window["days"] and start <= minute < end:
                return True
        else:
            previous_day = (now.weekday() - 1) % 7
            if (now.weekday() in window["days"] and minute >= start) or (
                previous_day in window["days"] and minute < end
            ):
                return True
    return False


class Catalog:
    def __init__(self, path: pathlib.Path):
        self.path = path
        self.lock = threading.RLock()
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, check_same_thread=False, timeout=15)
        os.chmod(path, 0o600)
        existing_tables = {row[0] for row in self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        existing_columns = ({row[1] for row in self.connection.execute("PRAGMA table_info(segments)")}
                            if "segments" in existing_tables else set())
        migrations = {
            "node_id": "TEXT NOT NULL DEFAULT 'standalone'",
            "profile_id": "TEXT NOT NULL DEFAULT 'main'",
            "volume_id": "TEXT NOT NULL DEFAULT 'default'",
            "sha256": "TEXT NOT NULL DEFAULT ''",
            "assignment_generation": "INTEGER NOT NULL DEFAULT 0",
            "archive_state": "TEXT NOT NULL DEFAULT 'local'",
        }
        backup_path = path.with_name(path.name + ".pre-v2.3.backup")
        upgrading = bool(existing_columns and set(migrations) - existing_columns)
        if upgrading and not backup_path.exists():
            backup = sqlite3.connect(backup_path)
            try:
                self.connection.backup(backup)
                if backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ConfigError("pre-v2.3 catalog backup failed integrity validation")
            finally:
                backup.close()
            os.chmod(backup_path, 0o600)
        try:
            with self.connection:
                self.connection.execute("PRAGMA journal_mode=WAL")
                self.connection.execute("PRAGMA synchronous=FULL")
                self.connection.execute("PRAGMA foreign_keys=ON")
                self.connection.executescript("""
                CREATE TABLE IF NOT EXISTS cameras (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, policy TEXT NOT NULL,
                    stream TEXT NOT NULL, mode TEXT NOT NULL, updated_utc_ms INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS segments (
                    id TEXT PRIMARY KEY, camera_id TEXT NOT NULL, start_utc_ms INTEGER NOT NULL,
                    end_utc_ms INTEGER NOT NULL, duration_ms INTEGER NOT NULL,
                    storage_key TEXT NOT NULL UNIQUE, kind TEXT NOT NULL,
                    video_codec TEXT NOT NULL, audio_codec TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL, integrity TEXT NOT NULL,
                    locked INTEGER NOT NULL DEFAULT 0, created_utc_ms INTEGER NOT NULL,
                    FOREIGN KEY(camera_id) REFERENCES cameras(id)
                );
                CREATE INDEX IF NOT EXISTS segments_camera_time
                    ON segments(camera_id, start_utc_ms, end_utc_ms);
                CREATE INDEX IF NOT EXISTS segments_retention
                    ON segments(locked, integrity, start_utc_ms);
                CREATE TABLE IF NOT EXISTS exports (
                    id TEXT PRIMARY KEY, audit_id TEXT NOT NULL, created_utc_ms INTEGER NOT NULL,
                    storage_key TEXT NOT NULL, manifest_key TEXT NOT NULL, mode TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS snapshots (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, camera_id TEXT NOT NULL,
                    sha256 TEXT NOT NULL, created_utc_ms INTEGER NOT NULL
                );
                """)
                columns = {row[1] for row in self.connection.execute("PRAGMA table_info(segments)")}
                for name, declaration in migrations.items():
                    if name not in columns:
                        self.connection.execute(f"ALTER TABLE segments ADD COLUMN {name} {declaration}")
                export_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(exports)")}
                for name, declaration in {"owner": "TEXT NOT NULL DEFAULT ''", "request_json": "TEXT NOT NULL DEFAULT '{}'"}.items():
                    if name not in export_columns:
                        self.connection.execute(f"ALTER TABLE exports ADD COLUMN {name} {declaration}")
                self.connection.execute("PRAGMA user_version=2")
                if self.connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ConfigError("migrated catalog failed integrity validation")
        except Exception:
            self.connection.close()
            if upgrading and backup_path.is_file():
                shutil.copy2(backup_path, path)
                for suffix in ("-wal", "-shm"):
                    with contextlib.suppress(FileNotFoundError):
                        pathlib.Path(str(path) + suffix).unlink()
            raise

    def execute(self, sql: str, parameters: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        with self.lock, self.connection:
            return self.connection.execute(sql, parameters)

    def query(self, sql: str, parameters: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self.lock:
            self.connection.row_factory = sqlite3.Row
            return list(self.connection.execute(sql, parameters))

    def sync_cameras(self, config: dict[str, Any]) -> None:
        now = utc_ms()
        for camera in config["cameras"]:
            self.execute(
                "INSERT INTO cameras(id,name,policy,stream,mode,updated_utc_ms) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET name=excluded.name,policy=excluded.policy,"
                "stream=excluded.stream,mode=excluded.mode,updated_utc_ms=excluded.updated_utc_ms",
                (camera["id"], camera["name"], camera["policy"], camera["stream"], camera["mode"], now),
            )

    def add_segment(self, segment: dict[str, Any]) -> None:
        self.execute(
            "INSERT OR IGNORE INTO segments(id,camera_id,start_utc_ms,end_utc_ms,duration_ms,storage_key,"
            "kind,video_codec,audio_codec,size_bytes,integrity,locked,created_utc_ms,node_id,volume_id,sha256,"
            "profile_id,assignment_generation,archive_state) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                segment["id"], segment["cameraId"], segment["startUtcMs"], segment["endUtcMs"],
                segment["durationMs"], segment["storageKey"], segment["kind"], segment["videoCodec"],
                segment["audioCodec"], segment["sizeBytes"], segment["integrity"],
                int(segment.get("locked", False)), utc_ms(), segment.get("nodeId", "standalone"),
                segment.get("volumeId", "default"), segment.get("sha256", ""),
                segment.get("profileId", "main"),
                segment.get("assignmentGeneration", 0), segment.get("archiveState", "local"),
            ),
        )


class VolumeManager:
    """Restricts NVR writes to the legacy root or pre-mounted volume IDs."""

    def __init__(self, legacy_root: pathlib.Path, volumes_root: pathlib.Path | None):
        self.legacy_root = legacy_root
        self.volumes_root = volumes_root
        self.roots: dict[str, pathlib.Path] = {"default": legacy_root}
        if volumes_root is not None:
            volumes_root.mkdir(mode=0o700, parents=True, exist_ok=True)
            if volumes_root.is_symlink():
                raise ConfigError("volumes root must not be a symbolic link")
            for child in sorted(volumes_root.iterdir()):
                if child.is_dir() and not child.is_symlink() and VOLUME_ID.fullmatch(child.name):
                    self.roots[child.name] = child

    def choose(self, reserve_bytes: int, policies: dict[str, dict[str, Any]] | None = None,
               excluded: set[str] | None = None) -> tuple[str, pathlib.Path]:
        policies = policies or {}
        excluded = excluded or set()
        candidates = []
        for volume_id, root in self.roots.items():
            if volume_id in excluded:
                continue
            if volume_id == "default" and len(self.roots) > 1:
                continue
            usage = shutil.disk_usage(root)
            policy = policies.get(volume_id, {})
            state = policy.get("state", "online")
            high = policy.get("highWatermark", 0.90)
            policy_reserve = policy.get("reserveBytes", 0)
            effective_reserve = max(reserve_bytes, policy_reserve if isinstance(policy_reserve, int) else 0)
            used_ratio = 1 - (usage.free / max(1, usage.total))
            if state == "online" and isinstance(high, (int, float)) and used_ratio < high and \
                    os.access(root, os.W_OK) and usage.free > effective_reserve:
                candidates.append((usage.free - effective_reserve, volume_id, root))
        if not candidates:
            raise RuntimeError("no writable recording volume has sufficient reserve")
        _, volume_id, root = max(candidates, key=lambda item: (item[0], item[1]))
        return volume_id, root

    def path(self, volume_id: str, storage_key: str) -> pathlib.Path:
        root = self.roots.get(volume_id)
        if root is None or not storage_key or storage_key.startswith("/") or ".." in storage_key.split("/"):
            raise RuntimeError("segment location is invalid")
        candidate = (root / storage_key).resolve()
        resolved_root = root.resolve()
        if candidate != resolved_root and resolved_root not in candidate.parents:
            raise RuntimeError("segment escaped its recording volume")
        return candidate

    def inventories(self) -> list[dict[str, Any]]:
        result = []
        for volume_id, root in sorted(self.roots.items()):
            usage = shutil.disk_usage(root)
            result.append({"id": volume_id, "capacityBytes": usage.total, "freeBytes": usage.free,
                           "readOnly": not os.access(root, os.W_OK)})
        return result


def file_sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class WorkerState:
    state: str = "idle"
    last_error: str = ""
    segments: int = 0
    bytes: int = 0
    failures: int = 0
    write_latency_ms: int = 0
    process: subprocess.Popen[bytes] | None = None
    shutdown_failed: bool = False
    event_active: bool = False


@dataclass
class RuntimeStats:
    started_monotonic: float = field(default_factory=time.monotonic)
    recovered: int = 0
    quarantined: int = 0
    retention_deletes: int = 0
    disk_pressure: bool = False


class NvrService:
    def __init__(self, config_path: pathlib.Path, storage_root: pathlib.Path):
        self.config_path = config_path
        self.storage_root = storage_root
        self.catalog = Catalog(storage_root / "catalog.sqlite3")
        configured_volumes = os.environ.get("WEBOBS_NVR_VOLUMES_ROOT", "")
        volumes_root = pathlib.Path(configured_volumes) if configured_volumes else None
        if volumes_root is not None and not volumes_root.is_absolute():
            raise ConfigError("WEBOBS_NVR_VOLUMES_ROOT must be absolute")
        self.volumes = VolumeManager(storage_root, volumes_root)
        self.node_role = os.environ.get("WEBOBS_NODE_ROLE", "standalone")
        self.node_id = os.environ.get("WEBOBS_NODE_ID", "standalone")
        self.assignment_path = pathlib.Path(os.environ.get(
            "WEBOBS_NODE_ASSIGNMENTS_FILE", "/config/webobs/node/assignments.json"))
        self.config_lock = threading.RLock()
        self.active_exports = 0
        self.export_slots = threading.BoundedSemaphore(2)
        self.config = self._load_or_default()
        self.catalog.sync_cameras(self.config)
        self.stop_event = threading.Event()
        self.workers: dict[str, tuple[threading.Thread, threading.Event, WorkerState]] = {}
        self.stats = RuntimeStats()
        self.ffmpeg = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
        self.ffprobe = shutil.which("ffprobe") or "/usr/bin/ffprobe"
        self.exports_root = storage_root / "exports"
        self.quarantine_root = storage_root / ".quarantine"
        self.ring_root = storage_root / ".pre-event"
        self.thumbnail_root = storage_root / ".thumbnails"
        self.snapshot_root = self.exports_root / "snapshots"
        self.thumbnail_slots = threading.BoundedSemaphore(4)
        self.reader_lock = threading.RLock()
        self.active_readers: dict[str, int] = {}
        self.playback_leases: dict[str, tuple[str, float, str]] = {}
        self.archive_cache_root = storage_root / ".archive-cache"
        self.archive_retrieval_enabled = os.environ.get("WEBOBS_ARCHIVE_RETRIEVAL_ENABLED", "false") == "true"
        self.archive_command = os.environ.get("WEBOBS_ARCHIVE_COMMAND", "/opt/webobs/bin/webobs-s3-archive")
        self.archive_cache_max_bytes = int(os.environ.get("WEBOBS_ARCHIVE_CACHE_MAX_BYTES", str(2 << 30)))
        if not 0 <= self.archive_cache_max_bytes <= 1 << 50:
            raise ConfigError("WEBOBS_ARCHIVE_CACHE_MAX_BYTES is invalid")
        self.archive_locks: dict[str, threading.Lock] = {}
        self.last_scrub_monotonic = 0.0
        for directory in (storage_root, self.exports_root, self.quarantine_root, self.ring_root,
                          self.archive_cache_root,
                          self.thumbnail_root, self.snapshot_root):
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.reconcile()
        self.jobs = ExportJobs(self)

    def _load_or_default(self) -> dict[str, Any]:
        if not self.config_path.exists():
            value = validate_config({"schemaVersion": 1, "cameras": []})
            atomic_json(self.config_path, value)
            return value
        return validate_config(private_json(self.config_path))

    def update_config(self, value: Any) -> dict[str, Any]:
        with self.config_lock:
            if not isinstance(value, dict):
                raise ConfigError("NVR configuration must be an object")
            restored = json.loads(json.dumps(value))
            existing = {camera["id"]: camera for camera in self.config["cameras"]}
            cameras = restored.get("cameras", [])
            if isinstance(cameras, list):
                for camera in cameras:
                    if not isinstance(camera, dict) or not isinstance(camera.get("id"), str):
                        continue
                    previous = existing.get(camera["id"])
                    for field_name in ("mainUrl", "subUrl"):
                        if camera.get(field_name) != "rtsp://***":
                            continue
                        if previous is None or not previous.get(field_name):
                            raise ConfigError(f"{field_name} redaction placeholder has no existing secret")
                        camera[field_name] = previous[field_name]
            candidate = validate_config(restored)
            atomic_json(self.config_path, candidate)
            self.config = candidate
        self.catalog.sync_cameras(candidate)
        self.restart_workers()
        self.audit("nvr.config.updated", camera_count=len(candidate["cameras"]))
        return redacted_config(candidate)

    def audit(self, event: str, **fields: Any) -> None:
        record = {"component": "nvr", "event": event, "utcMs": utc_ms(), **fields}
        print(json.dumps(record, separators=(",", ":"), sort_keys=True), flush=True)

    def start(self) -> None:
        self.jobs.start()
        self.reconcile_workers()
        threading.Thread(target=self._maintenance_loop, name="nvr-maintenance", daemon=True).start()

    def shutdown(self) -> None:
        self.jobs.drain()
        deadline = time.monotonic() + 20
        while self.active_exports and time.monotonic() < deadline:
            time.sleep(0.1)
        if self.active_exports:
            raise RuntimeError("active evidence export did not finish before shutdown")
        self.stop_event.set()
        self._stop_workers()

    def _stop_workers(self) -> None:
        workers = list(self.workers.values())
        self.workers.clear()
        for _, worker_stop, state in workers:
            worker_stop.set()
            if state.process and state.process.poll() is None:
                request_capture_stop(state.process)
        deadline = time.monotonic() + 25
        for thread, _, _ in workers:
            thread.join(timeout=max(0, deadline - time.monotonic()))
        if any(thread.is_alive() or state.shutdown_failed for thread, _, state in workers):
            raise RuntimeError('recording writers did not finish before shutdown')

    def restart_workers(self) -> None:
        self._stop_workers()
        if not self.stop_event.is_set():
            self.reconcile_workers()

    def reconcile_workers(self) -> None:
        with self.config_lock:
            cameras = {camera["id"]: camera for camera in self.config["cameras"]}
        for camera_id in list(self.workers):
            if camera_id not in cameras or self.workers[camera_id][0].is_alive() is False:
                thread, worker_stop, state = self.workers.pop(camera_id)
                worker_stop.set()
                if state.process and state.process.poll() is None:
                    request_capture_stop(state.process)
                thread.join(timeout=25)
                if thread.is_alive() or state.shutdown_failed:raise RuntimeError('recording writer did not stop')
        for camera_id in cameras:
            if camera_id not in self.workers:
                worker_stop = threading.Event()
                state = WorkerState()
                thread = threading.Thread(
                    target=self._worker_loop, args=(camera_id, worker_stop, state),
                    name=f"nvr-{camera_id}", daemon=True,
                )
                self.workers[camera_id] = (thread, worker_stop, state)
                thread.start()

    def camera(self, camera_id: str) -> dict[str, Any] | None:
        with self.config_lock:
            return next((dict(camera) for camera in self.config["cameras"] if camera["id"] == camera_id), None)

    def assignment_generation(self, camera: dict[str, Any]) -> int | None:
        if self.node_role != "recorder":
            return 0
        try:
            value = private_json(self.assignment_path)
            node_id = value.get("nodeId", "")
            if self.node_id != "standalone" and node_id != self.node_id:
                return None
            registry_camera = camera.get("cameraId") or camera["id"]
            profile = camera.get("subProfileId") if camera["stream"] == "sub" else camera.get("mainProfileId")
            profile = profile or camera["stream"]
            now = int(time.time())
            for assignment in value.get("assignments", []):
                if assignment.get("cameraId") == registry_camera and assignment.get("profileId") == profile and \
                        assignment.get("state") == "active" and assignment.get("isolationDeadline", 0) > now and \
                        isinstance(assignment.get("generation"), int) and assignment["generation"] > 0:
                    return assignment["generation"]
        except (OSError, ValueError, TypeError, json.JSONDecodeError, ConfigError):
            pass
        return None

    @staticmethod
    def profile_id(camera: dict[str, Any]) -> str:
        value = camera.get("subProfileId") if camera["stream"] == "sub" else camera.get("mainProfileId")
        return value or camera["stream"]

    def current_node_id(self) -> str:
        if self.node_role == "recorder":
            with contextlib.suppress(OSError, ValueError, TypeError, json.JSONDecodeError, ConfigError):
                value = private_json(self.assignment_path).get("nodeId", "")
                if isinstance(value, str) and re.fullmatch(r"[a-f0-9]{32}", value):
                    return value
        return self.node_id

    def volume_policies(self) -> dict[str, dict[str, Any]]:
        if self.node_role != "recorder":
            return {}
        with contextlib.suppress(OSError, ValueError, TypeError, json.JSONDecodeError, ConfigError):
            values = private_json(self.assignment_path).get("volumes", [])
            result: dict[str, dict[str, Any]] = {}
            for value in values[:256]:
                if isinstance(value, dict) and VOLUME_ID.fullmatch(str(value.get("id", ""))):
                    result[value["id"]] = value
            return result
        return {}

    def _worker_loop(self, camera_id: str, worker_stop: threading.Event, state: WorkerState) -> None:
        while not self.stop_event.is_set() and not worker_stop.is_set():
            camera = self.camera(camera_id)
            if camera is None:
                return
            now = dt.datetime.now(dt.timezone.utc)
            active = schedule_active(camera, now)
            assignment_generation = self.assignment_generation(camera)
            if assignment_generation is None:
                active = False
            kind = "continuous"
            ring = False
            if camera["policy"] == "event":
                active = state.event_active or camera["preEventSeconds"] > 0
                kind = "event" if state.event_active else "pre-event"
                ring = not state.event_active
            if not active:
                state.state = "idle"
                worker_stop.wait(0.5)
                continue
            state.state = "recording"
            try:
                segment = self._capture_segment(camera, kind, state, worker_stop, ring,
                                                assignment_generation or 0)
                if segment and not ring:
                    self.catalog.add_segment(segment)
                    state.segments += 1
                    state.bytes += segment["sizeBytes"]
                    self.audit("nvr.segment.finalized", camera_id=camera_id, segment_id=segment["id"],
                               size_bytes=segment["sizeBytes"], integrity=segment["integrity"])
                if ring:
                    if state.event_active:
                        self._promote_ring(camera)
                    else:
                        self._trim_ring(camera)
            except Exception as error:  # bounded message; URLs never included
                state.state = "degraded"
                state.last_error = type(error).__name__
                state.failures += 1
                self.audit("nvr.segment.failed", camera_id=camera_id, error=state.last_error)
                worker_stop.wait(min(5.0, 0.5 * (2 ** min(state.failures, 4))))
        state.state = "stopped"

    def _probe(self, path_or_url: str, transport: str | None = None) -> dict[str, Any]:
        command = [self.ffprobe, "-v", "error"]
        if transport:
            command += ["-rtsp_transport", transport]
        command += ["-show_entries", "format=duration:stream=codec_type,codec_name,avg_frame_rate,duration", "-of", "json", path_or_url]
        completed = subprocess.run(command, capture_output=True, timeout=15, check=False)
        if completed.returncode != 0 or len(completed.stdout) > MAX_BODY:
            raise RuntimeError("media probe failed")
        return json.loads(completed.stdout)

    def _capture_segment(self, camera: dict[str, Any], kind: str, state: WorkerState,
                         worker_stop: threading.Event, ring: bool,
                         assignment_generation: int = 0) -> dict[str, Any] | None:
        source_url = resolve_registry_source(camera) if camera.get("cameraId") else (
            camera["subUrl"] if camera["stream"] == "sub" else camera["mainUrl"]
        )
        start_utc = utc_ms()
        start_monotonic = time.monotonic_ns()
        segment_id = uuid.uuid4().hex
        timestamp = dt.datetime.fromtimestamp(start_utc / 1000, dt.timezone.utc)
        if ring:
            directory = self.ring_root / camera["id"]
            volume_id = "default"
            volume_root = self.storage_root
        else:
            volume_id, volume_root = self.volumes.choose(self.config["minFreeBytes"], self.volume_policies())
            directory = volume_root / camera["id"] / timestamp.strftime("%Y/%m/%d")
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        final = directory / f"{timestamp.strftime('%Y%m%dT%H%M%S.%fZ')}-{segment_id}.mp4"
        partial = directory / f".{final.name}.partial"
        probe = self._probe(source_url, camera["transport"])
        streams = probe.get("streams", [])
        video_codec = next((entry.get("codec_name", "") for entry in streams if entry.get("codec_type") == "video"), "")
        audio_codec = next((entry.get("codec_name", "") for entry in streams if entry.get("codec_type") == "audio"), "")
        copy_compatible = video_codec in {"h264", "hevc"}
        use_copy = camera["mode"] == "copy" or (camera["mode"] == "auto" and copy_compatible)
        commands: list[list[str]] = []
        common = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-rtsp_transport",
                  camera["transport"], "-i", source_url, "-t", str(camera["segmentSeconds"])]
        if os.name == 'nt':
            common.remove('-nostdin')
            common[common.index('-i'):common.index('-i')] = ['-timeout','8000000']
        if use_copy:
            commands.append(common + ["-map", "0", "-c", "copy", "-movflags",
                                      "+frag_keyframe+empty_moov+default_base_moof", "-f", "mp4", str(partial)])
        if not use_copy or camera["mode"] == "auto":
            commands.append(common + ["-map", "0:v:0", "-an", "-c:v", "libx264", "-preset", "veryfast",
                                      "-profile:v", "high", "-g", "60", "-pix_fmt", "yuv420p",
                                      "-movflags", "+frag_keyframe+empty_moov+default_base_moof",
                                      "-f", "mp4", str(partial)])
        succeeded = False
        for command in commands:
            with contextlib.suppress(FileNotFoundError):
                partial.unlink()
            state.process = subprocess.Popen(command, stdin=subprocess.PIPE if os.name == 'nt' else subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            while state.process.poll() is None and not self.stop_event.is_set() and not worker_stop.is_set():
                time.sleep(0.1)
            if (self.stop_event.is_set() or worker_stop.is_set()) and state.process.poll() is None:
                request_capture_stop(state.process)
            try:
                return_code = state.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                state.shutdown_failed = True
                state.process.kill()
                state.process.wait(timeout=5)
                raise RuntimeError('recording normal shutdown timed out')
            finally:
                if state.process.stdin:state.process.stdin.close()
            state.process = None
            stopped = self.stop_event.is_set() or worker_stop.is_set()
            if (return_code == 0 or (stopped and return_code == 255)) and partial.exists() and partial.stat().st_size > 0:
                succeeded = True
                break
        if not succeeded:
            raise RuntimeError("segment capture failed")
        media = self._probe(str(partial))
        output_streams = media.get("streams", [])
        duration_ms = max(1, (time.monotonic_ns() - start_monotonic) // 1_000_000)
        reported = media.get("format", {}).get("duration")
        if reported is not None:
            with contextlib.suppress(ValueError, TypeError):
                duration_ms = max(1, int(float(reported) * 1000))
        os.replace(partial, final)
        state.write_latency_ms = int((time.monotonic_ns() - start_monotonic) // 1_000_000)
        storage_key = final.relative_to(volume_root).as_posix()
        return {
            "id": segment_id, "cameraId": camera["id"], "startUtcMs": start_utc,
            "endUtcMs": start_utc + duration_ms, "durationMs": duration_ms,
            "storageKey": storage_key, "kind": kind,
            "videoCodec": next((entry.get("codec_name", "") for entry in output_streams if entry.get("codec_type") == "video"), ""),
            "audioCodec": next((entry.get("codec_name", "") for entry in output_streams if entry.get("codec_type") == "audio"), ""),
            "sizeBytes": final.stat().st_size, "integrity": "verified", "locked": False,
            "nodeId": self.current_node_id(), "volumeId": volume_id, "sha256": file_sha256(final),
            "profileId": self.profile_id(camera),
            "assignmentGeneration": assignment_generation, "archiveState": "local",
        }

    def _trim_ring(self, camera: dict[str, Any]) -> None:
        directory = self.ring_root / camera["id"]
        keep = max(1, (camera["preEventSeconds"] + camera["segmentSeconds"] - 1) // camera["segmentSeconds"])
        files = sorted(directory.glob("*.mp4"), key=lambda path: path.stat().st_mtime_ns)
        for path in files[:-keep]:
            path.unlink(missing_ok=True)

    def set_event(self, camera_id: str, active: bool) -> None:
        worker = self.workers.get(camera_id)
        camera = self.camera(camera_id)
        if not worker or not camera or camera["policy"] != "event":
            raise KeyError(camera_id)
        state = worker[2]
        previously = state.event_active
        state.event_active = active
        if active and not previously:
            self._promote_ring(camera)
        self.audit("nvr.event.changed", camera_id=camera_id, active=active)

    def _promote_ring(self, camera: dict[str, Any]) -> None:
        directory = self.ring_root / camera["id"]
        for path in sorted(directory.glob("*.mp4")):
            try:
                segment_id = path.stem.rsplit("-", 1)[-1]
                if not SEGMENT_ID.fullmatch(segment_id):
                    segment_id = uuid.uuid4().hex
                start = int(path.stat().st_mtime * 1000)
                media = self._probe(str(path))
                duration = max(1, int(float(media.get("format", {}).get("duration", 0)) * 1000))
                volume_id, volume_root = self.volumes.choose(self.config["minFreeBytes"], self.volume_policies())
                target_dir = volume_root / camera["id"] / dt.datetime.fromtimestamp(
                    start / 1000, dt.timezone.utc).strftime("%Y/%m/%d")
                target_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
                target = target_dir / path.name
                os.replace(path, target)
                streams = media.get("streams", [])
                self.catalog.add_segment({
                    "id": segment_id, "cameraId": camera["id"], "startUtcMs": start,
                    "endUtcMs": start + duration, "durationMs": duration,
                    "storageKey": target.relative_to(volume_root).as_posix(), "kind": "pre-event",
                    "videoCodec": next((entry.get("codec_name", "") for entry in streams if entry.get("codec_type") == "video"), ""),
                    "audioCodec": next((entry.get("codec_name", "") for entry in streams if entry.get("codec_type") == "audio"), ""),
                    "sizeBytes": target.stat().st_size, "integrity": "verified", "locked": False,
                    "nodeId": self.current_node_id(), "volumeId": volume_id, "sha256": file_sha256(target),
                    "profileId": self.profile_id(camera),
                    "assignmentGeneration": self.assignment_generation(camera) or 0, "archiveState": "local",
                })
            except Exception:
                self.stats.quarantined += 1
                target = self.quarantine_root / f"{uuid.uuid4().hex}.mp4"
                with contextlib.suppress(OSError):
                    os.replace(path, target)

    def reconcile(self) -> None:
        known = {(row["volume_id"], row["storage_key"]) for row in self.catalog.query(
            "SELECT volume_id,storage_key FROM segments")}
        for volume_id, volume_root in self.volumes.roots.items():
            for partial in volume_root.rglob("*.partial"):
                if self.quarantine_root in partial.parents:
                    continue
                try:
                    media = self._probe(str(partial))
                    duration = max(1, int(float(media.get("format", {}).get("duration", 0)) * 1000))
                    final = partial.with_name(partial.name.removeprefix(".").removesuffix(".partial"))
                    os.replace(partial, final)
                    camera_id = final.relative_to(volume_root).parts[0]
                    if not CAMERA_ID.fullmatch(camera_id) or self.camera(camera_id) is None:
                        raise RuntimeError("unknown partial owner")
                    segment_id = final.stem.rsplit("-", 1)[-1]
                    if not SEGMENT_ID.fullmatch(segment_id):
                        segment_id = uuid.uuid4().hex
                    start = int(final.stat().st_mtime * 1000) - duration
                    streams = media.get("streams", [])
                    self.catalog.add_segment({
                        "id": segment_id, "cameraId": camera_id, "startUtcMs": start,
                        "endUtcMs": start + duration, "durationMs": duration,
                        "storageKey": final.relative_to(volume_root).as_posix(), "kind": "recovered",
                        "videoCodec": next((entry.get("codec_name", "") for entry in streams if entry.get("codec_type") == "video"), ""),
                        "audioCodec": next((entry.get("codec_name", "") for entry in streams if entry.get("codec_type") == "audio"), ""),
                        "sizeBytes": final.stat().st_size, "integrity": "recovered", "locked": False,
                        "nodeId": self.current_node_id(), "volumeId": volume_id, "sha256": file_sha256(final),
                        "profileId": self.profile_id(self.camera(camera_id) or {"stream": "main"}),
                        "assignmentGeneration": 0, "archiveState": "local",
                    })
                    self.stats.recovered += 1
                except Exception:
                    target = self.quarantine_root / f"{uuid.uuid4().hex}.partial"
                    with contextlib.suppress(OSError):
                        os.replace(partial, target)
                    self.stats.quarantined += 1
            for path in volume_root.glob("*/*/*/*/*.mp4"):
                storage_key = path.relative_to(volume_root).as_posix()
                if (volume_id, storage_key) in known:
                    continue
                camera_id = storage_key.split("/", 1)[0]
                camera = self.camera(camera_id)
                if not camera:
                    continue
                try:
                    media = self._probe(str(path))
                    duration = max(1, int(float(media.get("format", {}).get("duration", 0)) * 1000))
                    segment_id = path.stem.rsplit("-", 1)[-1]
                    if not SEGMENT_ID.fullmatch(segment_id):
                        segment_id = uuid.uuid4().hex
                    start = int(path.stat().st_mtime * 1000) - duration
                    streams = media.get("streams", [])
                    self.catalog.add_segment({
                        "id": segment_id, "cameraId": camera_id, "startUtcMs": start,
                        "endUtcMs": start + duration, "durationMs": duration, "storageKey": storage_key,
                        "kind": "orphan", "videoCodec": next((entry.get("codec_name", "") for entry in streams if entry.get("codec_type") == "video"), ""),
                        "audioCodec": next((entry.get("codec_name", "") for entry in streams if entry.get("codec_type") == "audio"), ""),
                        "sizeBytes": path.stat().st_size, "integrity": "reconciled", "locked": False,
                        "nodeId": self.current_node_id(), "volumeId": volume_id, "sha256": file_sha256(path),
                        "profileId": self.profile_id(camera),
                        "assignmentGeneration": 0, "archiveState": "local",
                    })
                except Exception:
                    self.stats.quarantined += 1
        for row in self.catalog.query("SELECT id,volume_id,storage_key FROM segments WHERE integrity NOT IN ('deleted','missing')"):
            try:
                exists = self.volumes.path(row["volume_id"], row["storage_key"]).is_file()
            except RuntimeError:
                exists = False
            if not exists:
                self.catalog.execute("UPDATE segments SET integrity='missing' WHERE id=?", (row["id"],))

    def _maintenance_loop(self) -> None:
        while not self.stop_event.wait(2):
            self.apply_retention()
            self.migrate_under_pressure()
            if time.monotonic() - self.last_scrub_monotonic >= 24 * 60 * 60:
                self.scrub_once()
                self.last_scrub_monotonic = time.monotonic()
            self.trim_archive_cache()

    def trim_archive_cache(self) -> None:
        entries = []
        total = 0
        with contextlib.suppress(OSError):
            for path in self.archive_cache_root.iterdir():
                if path.is_file() and SEGMENT_ID.fullmatch(path.name):
                    stat = path.stat()
                    total += stat.st_size
                    entries.append((stat.st_atime_ns, path, stat.st_size))
        for _, path, size in sorted(entries):
            if total <= self.archive_cache_max_bytes:
                break
            segment_id = path.name
            with self.reader_lock:
                if self._segment_active(segment_id):
                    continue
                with contextlib.suppress(OSError):
                    path.unlink()
                    total -= size

    def migrate_under_pressure(self) -> bool:
        policies = self.volume_policies()
        for volume_id, root in self.volumes.roots.items():
            if volume_id == "default" and len(self.volumes.roots) > 1:
                continue
            usage = shutil.disk_usage(root)
            policy = policies.get(volume_id, {})
            high = policy.get("highWatermark", 0.90)
            state = policy.get("state", "online")
            if state != "evacuating" and (not isinstance(high, (int, float)) or
                                            1 - usage.free / max(1, usage.total) < high):
                continue
            try:
                target_id, target_root = self.volumes.choose(
                    self.config["minFreeBytes"], policies, {volume_id})
            except RuntimeError:
                return False
            rows = self.catalog.query("""
              SELECT * FROM segments WHERE volume_id=? AND locked=0
                AND integrity NOT IN ('deleted','missing','corrupt')
              ORDER BY start_utc_ms LIMIT 32
            """, (volume_id,))
            for row in rows:
                with self.reader_lock:
                    if self._segment_active(row["id"]):
                        continue
                with self.reader_lock:
                    current = self.catalog.query("SELECT locked FROM segments WHERE id=?", (row["id"],))
                    if self._segment_active(row["id"]) or not current or current[0]["locked"]:
                        continue
                    try:
                        source = self.volumes.path(volume_id, row["storage_key"])
                        target = self.volumes.path(target_id, row["storage_key"])
                        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.migrating")
                        shutil.copyfile(source, temporary)
                        digest = file_sha256(temporary)
                        expected = row["sha256"] or file_sha256(source)
                        if digest != expected or temporary.stat().st_size != row["size_bytes"]:
                            raise RuntimeError("migrated segment digest mismatch")
                        os.replace(temporary, target)
                        self.catalog.execute("UPDATE segments SET volume_id=?,sha256=? WHERE id=?",
                                             (target_id, digest, row["id"]))
                        with contextlib.suppress(OSError):
                            source.unlink()
                        self.audit("nvr.segment.migrated", segment_id=row["id"],
                                   source_volume=volume_id, target_volume=target_id)
                        return True
                    except (OSError, RuntimeError):
                        with contextlib.suppress(UnboundLocalError, OSError):
                            temporary.unlink()
                        self.catalog.execute("UPDATE segments SET integrity='migration-failed' WHERE id=?",
                                             (row["id"],))
                        return False
        return False

    def scrub_once(self, limit: int = 128) -> dict[str, int]:
        checked = 0
        corrupt = 0
        rows = self.catalog.query("""
          SELECT * FROM segments WHERE integrity NOT IN ('deleted','missing','corrupt')
            AND length(sha256)=64 ORDER BY start_utc_ms LIMIT ?
        """, (max(1, min(limit, 4096)),))
        for row in rows:
            with self.reader_lock:
                if self._segment_active(row["id"]):
                    continue
            try:
                valid = file_sha256(self.volumes.path(row["volume_id"], row["storage_key"])) == row["sha256"]
            except (OSError, RuntimeError):
                valid = False
            checked += 1
            if not valid:
                corrupt += 1
                self.catalog.execute("UPDATE segments SET integrity='corrupt' WHERE id=?", (row["id"],))
                self.audit("nvr.segment.scrub-failed", segment_id=row["id"])
        return {"checked": checked, "corrupt": corrupt}

    def apply_retention(self) -> None:
        with self.config_lock:
            config = json.loads(json.dumps(self.config))
        now = utc_ms()
        inventories = self.volumes.inventories()
        pressure = any(item["freeBytes"] < config["minFreeBytes"] for item in inventories)
        self.stats.disk_pressure = pressure
        camera_config = {camera["id"]: camera for camera in config["cameras"]}
        rows = self.catalog.query(
            "SELECT * FROM segments WHERE locked=0 AND integrity NOT IN ('deleted','missing') ORDER BY start_utc_ms ASC"
        )
        total = sum(row["size_bytes"] for row in rows)
        camera_totals: dict[str, int] = {}
        for row in rows:
            camera_totals[row["camera_id"]] = camera_totals.get(row["camera_id"], 0) + row["size_bytes"]
        for row in rows:
            with self.reader_lock:
                self._expire_playback_leases()
                if self._segment_active(row["id"]):
                    continue
            camera = camera_config.get(row["camera_id"])
            if not camera:
                continue
            expired = row["end_utc_ms"] < now - camera["maxAgeHours"] * 3_600_000
            camera_over = camera["maxBytes"] > 0 and camera_totals[row["camera_id"]] > camera["maxBytes"]
            global_over = config["maxBytes"] > 0 and total > config["maxBytes"]
            if not (expired or camera_over or global_over or pressure):
                continue
            with self.reader_lock:
                current = self.catalog.query("SELECT locked,integrity FROM segments WHERE id=?", (row["id"],))
                if self._segment_active(row["id"]) or not current or current[0]["locked"] or current[0]["integrity"] == "deleted":
                    continue
                try:
                    path = self.volumes.path(row["volume_id"], row["storage_key"])
                except RuntimeError:
                    self.catalog.execute("UPDATE segments SET integrity='missing' WHERE id=?", (row["id"],))
                    continue
                with contextlib.suppress(FileNotFoundError):
                    path.unlink()
                self.catalog.execute("UPDATE segments SET integrity='deleted',size_bytes=0 WHERE id=?", (row["id"],))
            total -= row["size_bytes"]
            camera_totals[row["camera_id"]] -= row["size_bytes"]
            self.stats.retention_deletes += 1
            inventories = self.volumes.inventories()
            pressure = any(item["freeBytes"] < config["minFreeBytes"] for item in inventories)
            self.audit("nvr.retention.deleted", camera_id=row["camera_id"], segment_id=row["id"])
        self.stats.disk_pressure = pressure
        self._trim_thumbnails()

    def status(self, owner=None, permission="playback.view") -> dict[str, Any]:
        inventories = self.volumes.inventories()
        cameras = []
        workers = dict(self.workers)
        with self.config_lock:
            configured = {camera["id"]: camera for camera in self.config["cameras"]}
        camera_ids = sorted(configured.keys() | workers.keys())
        allowed = self.authorized_cameras(owner, permission, camera_ids, require_all=False) if owner is not None else None
        for camera_id in camera_ids:
            if allowed is not None and camera_id not in allowed:
                continue
            camera = configured.get(camera_id)
            state = workers[camera_id][2] if camera_id in workers else WorkerState()
            cameras.append({
                "id": camera_id, "policy": camera["policy"] if camera else "off", "state": state.state,
                "segments": state.segments, "bytes": state.bytes, "failures": state.failures,
                "writeLatencyMs": state.write_latency_ms, "eventActive": state.event_active,
                "lastError": state.last_error,
            })
        return {
            "status": "degraded" if self.stats.disk_pressure or any(item["state"] == "degraded" for item in cameras) else "ok",
            "activeExports": self.active_exports,
            "queuedExports": self.jobs.outstanding(),
            "uptimeSeconds": int(time.monotonic() - self.stats.started_monotonic),
            "freeBytes": sum(item["freeBytes"] for item in inventories),
            "volumes": inventories, "diskPressure": self.stats.disk_pressure,
            "recovered": self.stats.recovered, "quarantined": self.stats.quarantined,
            "retentionDeletes": self.stats.retention_deletes, "cameras": cameras,
        }

    def segments(self, query: dict[str, list[str]], owner=None) -> list[dict[str, Any]]:
        cameras = [value for value in query.get("cameraId", []) if CAMERA_ID.fullmatch(value)]
        if len(cameras) != len(query.get("cameraId", [])) or len(cameras) > 64:
            raise ConfigError("cameraId values are invalid")
        if owner is not None:
            known = cameras or [row['id'] for row in self.catalog.query('SELECT id FROM cameras LIMIT 1025')]
            cameras = self.authorized_cameras(owner, "playback.view", known, require_all=bool(cameras))
            if not cameras:
                return []
        start = int(query.get("from", ["0"])[0])
        end = int(query.get("to", [str((1 << 63) - 1)])[0])
        limit = min(5000, max(1, int(query.get("limit", ["1000"])[0])))
        clauses = ["end_utc_ms>=?", "start_utc_ms<=?", "integrity!='deleted'"]
        parameters: list[Any] = [start, end]
        if cameras:
            clauses.append("camera_id IN (" + ",".join("?" for _ in cameras) + ")")
            parameters.extend(cameras)
        parameters.append(limit)
        rows = self.catalog.query(
            "SELECT id,camera_id,start_utc_ms,end_utc_ms,duration_ms,kind,video_codec,audio_codec,"
            "size_bytes,integrity,locked,node_id,volume_id,archive_state FROM segments WHERE " + " AND ".join(clauses) +
            " ORDER BY start_utc_ms LIMIT ?", tuple(parameters),
        )
        return [{
            "id": row["id"], "cameraId": row["camera_id"], "startUtcMs": row["start_utc_ms"],
            "endUtcMs": row["end_utc_ms"], "durationMs": row["duration_ms"], "kind": row["kind"],
            "videoCodec": row["video_codec"], "audioCodec": row["audio_codec"],
            "sizeBytes": row["size_bytes"], "integrity": row["integrity"], "locked": bool(row["locked"]),
            "nodeId": row["node_id"], "volumeId": row["volume_id"], "archiveState": row["archive_state"],
            "mediaUrl": f"/api/v1/nvr/media/{row['id']}",
        } for row in rows]

    def timeline(self, query: dict[str, list[str]], owner=None) -> dict[str, Any]:
        started = time.monotonic_ns()
        start = bounded_int(int(query.get("from", [str(utc_ms() - 86_400_000)])[0]), 0, (1 << 63) - 1, "from")
        end = bounded_int(int(query.get("to", [str(utc_ms())])[0]), 1, (1 << 63) - 1, "to")
        if start >= end or end - start > 31 * 86_400_000:
            raise ConfigError("timeline range must be positive and at most 31 days")
        requested = [value for value in query.get("cameraId", []) if CAMERA_ID.fullmatch(value)]
        if len(requested) != len(query.get("cameraId", [])) or len(requested) > 64:
            raise ConfigError("cameraId values are invalid")
        with self.config_lock:
            camera_config = {camera["id"]: camera for camera in self.config["cameras"]}
            known = list(camera_config)
        camera_ids = requested or known
        if any(camera_id not in known for camera_id in camera_ids):
            raise ConfigError("timeline cameraId is unknown")
        if owner is not None:
            camera_ids = self.authorized_cameras(owner, "playback.view", camera_ids, require_all=bool(requested))
        segment_query = {"from": [str(start)], "to": [str(end)], "limit": ["5000"]}
        if camera_ids:
            segment_query["cameraId"] = camera_ids
        segments = self.segments(segment_query) if camera_ids else []
        cameras: list[dict[str, Any]] = []
        for camera_id in camera_ids:
            items = [item for item in segments if item["cameraId"] == camera_id]
            items.sort(key=lambda item: (item["startUtcMs"], item["id"]))
            gaps: list[dict[str, Any]] = []
            cursor = start
            for item in items:
                if item["integrity"] in {"missing", "corrupt", "quarantined"}:
                    gaps.append({"fromUtcMs": max(start, item["startUtcMs"]),
                                 "toUtcMs": min(end, item["endUtcMs"]), "reason": item["integrity"]})
                    continue
                if item["startUtcMs"] > cursor + 250:
                    gaps.append({"fromUtcMs": cursor, "toUtcMs": item["startUtcMs"], "reason": "offline"})
                cursor = max(cursor, item["endUtcMs"])
            if cursor < end:
                gaps.append({"fromUtcMs": cursor, "toUtcMs": end, "reason": "offline"})
            boundary_rows = self.catalog.query(
                "SELECT MIN(start_utc_ms) AS boundary FROM segments WHERE camera_id=? AND integrity NOT IN ('deleted','missing')",
                (camera_id,),
            )
            boundary = boundary_rows[0]["boundary"] if boundary_rows and boundary_rows[0]["boundary"] is not None else None
            cameras.append({"cameraId": camera_id, "recordedStream": camera_config[camera_id]["stream"],
                            "segments": items, "gaps": gaps,
                            "retentionBoundaryUtcMs": boundary})
        return {"fromUtcMs": start, "toUtcMs": end, "storageTimeZone": "UTC", "cameras": cameras,
                "queryDurationMs": max(0, (time.monotonic_ns() - started) // 1_000_000)}

    def set_lock(self, segment_id: str, locked: bool) -> None:
        with self.reader_lock:
            cursor = self.catalog.execute("UPDATE segments SET locked=? WHERE id=? AND integrity!='deleted'", (int(locked), segment_id))
            if cursor.rowcount != 1:
                raise KeyError(segment_id)
        self.audit("nvr.segment.lock", segment_id=segment_id, locked=locked)

    def segment_row(self, segment_id: str) -> sqlite3.Row:
        rows = self.catalog.query("SELECT * FROM segments WHERE id=? AND integrity NOT IN ('deleted','missing')", (segment_id,))
        if not rows:
            raise KeyError(segment_id)
        return rows[0]

    def media_path(self, segment_id: str) -> pathlib.Path:
        row = self.segment_row(segment_id)
        try:
            path = self.volumes.path(row["volume_id"], row["storage_key"])
        except RuntimeError:
            raise KeyError(segment_id) from None
        if not path.is_file():
            path = self.restore_archived_segment(row)
        with contextlib.suppress(OSError):
            stat = path.stat()
            os.utime(path, ns=(time.time_ns(), stat.st_mtime_ns))
        return path

    def restore_archived_segment(self, row: sqlite3.Row) -> pathlib.Path:
        if not self.archive_retrieval_enabled or row["archive_state"] != "uploaded" or \
                not re.fullmatch(r"[0-9a-f]{64}", row["sha256"] or ""):
            raise KeyError(row["id"])
        destination = self.archive_cache_root / row["id"]
        with self.reader_lock:
            lock = self.archive_locks.setdefault(row["id"], threading.Lock())
        with lock:
            if not destination.is_file():
                command = [self.archive_command, "--retrieve-segment", row["id"],
                           "--destination", str(destination)]
                result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, timeout=120, check=False)
                if result.returncode != 0:
                    raise KeyError(row["id"])
            try:
                valid = destination.stat().st_size == row["size_bytes"] and \
                    file_sha256(destination) == row["sha256"]
            except OSError:
                valid = False
            if not valid:
                with contextlib.suppress(OSError):
                    destination.unlink()
                raise KeyError(row["id"])
        return destination

    @contextlib.contextmanager
    def pin_segments(self, segment_ids: list[str]):
        with self.reader_lock:
            for segment_id in segment_ids:
                self.segment_row(segment_id)
            for segment_id in segment_ids:
                self.active_readers[segment_id] = self.active_readers.get(segment_id, 0) + 1
        try:
            yield
        finally:
            with self.reader_lock:
                for segment_id in segment_ids:
                    remaining = self.active_readers.get(segment_id, 1) - 1
                    if remaining > 0:
                        self.active_readers[segment_id] = remaining
                    else:
                        self.active_readers.pop(segment_id, None)

    @contextlib.contextmanager
    def playback_reader(self, segment_id: str):
        with self.pin_segments([segment_id]):
            path = self.media_path(segment_id)
            self.audit("nvr.playback.opened", segment_id=segment_id)
            yield path

    def _expire_playback_leases(self) -> None:
        now = time.monotonic()
        for lease_id, (_, expiry, _) in list(self.playback_leases.items()):
            if expiry <= now:
                self.playback_leases.pop(lease_id, None)

    def _segment_active(self, segment_id: str) -> bool:
        return self.active_readers.get(segment_id, 0) > 0 or any(
            leased_segment == segment_id for leased_segment, _, _ in self.playback_leases.values()
        )

    def create_playback_lease(self, value: Any, owner="local-only") -> dict[str, Any]:
        if not isinstance(value, dict) or set(value) != {"segmentId", "ttlSeconds"}:
            raise ConfigError("playback lease requires segmentId and ttlSeconds")
        segment_id = value["segmentId"]
        if not isinstance(segment_id, str) or not SEGMENT_ID.fullmatch(segment_id):
            raise ConfigError("playback lease segmentId is invalid")
        ttl = bounded_int(value["ttlSeconds"], 10, 300, "ttlSeconds")
        lease_id = uuid.uuid4().hex
        with self.reader_lock:
            self._expire_playback_leases()
            self.segment_row(segment_id)
            if len(self.playback_leases) >= 1024 or sum(value[2] == owner for value in self.playback_leases.values()) >= 64:
                raise EvidenceError("playback_lease_capacity", "Too many playback leases; release unused playback or retry later", 429)
            self.playback_leases[lease_id] = (segment_id, time.monotonic() + ttl, owner)
        self.audit("nvr.playback.lease", segment_id=segment_id, lease_id=lease_id, ttl_seconds=ttl)
        return {"id": lease_id, "segmentId": segment_id, "expiresUtcMs": utc_ms() + ttl * 1000}

    def release_playback_lease(self, lease_id: str, owner="local-only") -> None:
        with self.reader_lock:
            lease = self.playback_leases.get(lease_id)
            if lease is None or lease[2] != owner:
                raise KeyError(lease_id)
            lease = self.playback_leases.pop(lease_id, None)
        if lease is None:
            raise KeyError(lease_id)
        self.audit("nvr.playback.released", segment_id=lease[0], lease_id=lease_id)

    def thumbnail(self, segment_id: str, offset_ms: int) -> pathlib.Path:
        offset_ms = bounded_int(offset_ms, 0, 86_400_000, "offsetMs")
        row = self.segment_row(segment_id)
        if offset_ms >= row["duration_ms"]:
            offset_ms = max(0, row["duration_ms"] - 1)
        target = self.thumbnail_root / f"{segment_id}-{offset_ms}.jpg"
        if target.is_file():
            stat = target.stat()
            os.utime(target, ns=(time.time_ns(), stat.st_mtime_ns))
            return target
        if not self.thumbnail_slots.acquire(timeout=10):
            raise RuntimeError("thumbnail capacity exhausted")
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.partial")
        try:
            command = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-ss",
                       f"{offset_ms / 1000:.3f}", "-i", str(self.media_path(segment_id)), "-frames:v", "1",
                       "-vf", "scale=320:-2", "-q:v", "4", "-f", "image2", "-y", str(temporary)]
            completed = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       timeout=20, check=False)
            if completed.returncode != 0 or not temporary.is_file() or temporary.stat().st_size == 0:
                temporary.unlink(missing_ok=True)
                raise RuntimeError("thumbnail generation failed")
            os.replace(temporary, target)
            return target
        finally:
            with contextlib.suppress(OSError):
                temporary.unlink(missing_ok=True)
            self.thumbnail_slots.release()

    def _trim_thumbnails(self) -> None:
        files = sorted(self.thumbnail_root.glob("*.jpg"), key=lambda path: path.stat().st_atime_ns, reverse=True)
        cutoff = time.time() - 24 * 3600
        for path in files[1000:]:
            path.unlink(missing_ok=True)
        for path in files[:1000]:
            if path.stat().st_atime < cutoff:
                path.unlink(missing_ok=True)

    @export_operation
    def snapshot(self, value: Any, owner="local-only") -> dict[str, Any]:
        if not isinstance(value, dict) or set(value) != {"segmentId", "offsetMs"}:
            raise ConfigError("snapshot requires segmentId and offsetMs")
        segment_id = value["segmentId"]
        if not isinstance(segment_id, str) or not SEGMENT_ID.fullmatch(segment_id):
            raise ConfigError("snapshot segmentId is invalid")
        offset_ms = bounded_int(value["offsetMs"], 0, 86_400_000, "offsetMs")
        snapshot_id = uuid.uuid4().hex
        target = self.snapshot_root / f"{snapshot_id}.jpg"
        with self.pin_segments([segment_id]):
            camera_id = self.segment_row(segment_id)["camera_id"]
            source = self.thumbnail(segment_id, offset_ms)
            temporary = target.with_suffix(".jpg.partial")
            try:
                shutil.copyfile(source, temporary)
                digest = self._sha256(temporary)
                os.replace(temporary, target)
                self.catalog.execute("INSERT INTO snapshots VALUES(?,?,?,?,?)", (snapshot_id, owner, camera_id, digest, utc_ms()))
            except Exception:
                temporary.unlink(missing_ok=True)
                target.unlink(missing_ok=True)
                raise
        self.audit("nvr.snapshot.created", segment_id=segment_id, snapshot_id=snapshot_id)
        return {"id": snapshot_id, "segmentId": segment_id, "offsetMs": offset_ms,
                "sha256": digest, "downloadUrl": f"/api/v1/nvr/downloads/{snapshot_id}.jpg"}

    @staticmethod
    def _sha256(path: pathlib.Path, cancel=None) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                if cancel is not None and cancel.is_set():
                    raise EvidenceError("export_cancelled", "Export cancelled")
                digest.update(block)
        return digest.hexdigest()

    def validate_export(self, value: Any) -> dict[str, Any]:
        allowed = {"cameraIds", "fromUtcMs", "toUtcMs", "mode", "lock", "programRecordingId"}
        if not isinstance(value, dict) or set(value) - allowed:
            raise ConfigError("export request contains unsupported fields")
        camera_ids = value.get("cameraIds")
        if (not isinstance(camera_ids, list) or not 1 <= len(camera_ids) <= 4 or
                any(not isinstance(item, str) or not CAMERA_ID.fullmatch(item) for item in camera_ids) or
                len(set(camera_ids)) != len(camera_ids)):
            raise ConfigError("export cameraIds must contain one to four unique ids")
        start = bounded_int(value.get("fromUtcMs"), 0, 8_640_000_000_000_000, "fromUtcMs")
        end = bounded_int(value.get("toUtcMs"), 1, 8_640_000_000_000_000, "toUtcMs")
        if start >= end or end - start > 24 * 3600 * 1000:
            raise ConfigError("export range must be positive and at most 24 hours")
        mode = value.get("mode", "fast")
        if mode not in {"fast", "exact"}:
            raise ConfigError("export mode must be fast or exact")
        lock = value.get("lock", True)
        if not isinstance(lock, bool):
            raise ConfigError("export lock must be boolean")
        program_recording_id = value.get("programRecordingId")
        if program_recording_id is not None and (
            not isinstance(program_recording_id, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", program_recording_id)
        ):
            raise ConfigError("programRecordingId must be a safe stable identifier")
        return {"cameraIds": camera_ids, "fromUtcMs": start, "toUtcMs": end, "mode": mode,
                "lock": lock, "programRecordingId": program_recording_id}

    def authorized_cameras(self, owner: str, permission: str, camera_ids: list[str], *, require_all=True) -> list[str]:
        if len(camera_ids) > 1024:
            raise ConfigError("specify cameraId to narrow this recording query")
        token = os.environ.get("WEBOBS_CLUSTER_INTERNAL_TOKEN", "")
        if not token and os.environ.get("WEBOBS_CLUSTER_ENABLED", "false") != "true":
            return camera_ids
        if not re.fullmatch(r"[a-f0-9]{64}", token):
            raise EvidenceError("authorization_unavailable", "Recording authorization is unavailable", 503)
        mappings = {}
        for camera_id in camera_ids:
            camera = self.camera(camera_id)
            mappings[camera_id] = (camera.get("cameraId") or camera_id) if camera else camera_id
        scopes = list(dict.fromkeys(mappings.values()))
        allowed = set()
        deadline = time.monotonic() + 10
        for offset in range(0, max(1, len(scopes)), 64):
            timeout = min(3, deadline - time.monotonic())
            if timeout <= 0:
                raise EvidenceError("authorization_unavailable", "Recording authorization is unavailable", 503)
            batch = scopes[offset:offset + 64]
            payload = json.dumps({"username": owner, "permission": permission, "cameraIds": batch}).encode()
            request = urllib.request.Request(service_http(8095, "/auth/authorize-cameras"), data=payload,
                headers={"Content-Type": "application/json", "X-WebObs-Internal-Admin": token})
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    encoded = response.read(16385)
                    if response.status != 200 or len(encoded) > 16384:
                        raise ValueError("invalid authorization response")
                    value = json.loads(encoded)
                    approved = value.get("cameraIds") if isinstance(value, dict) else None
                    if not isinstance(value, dict) or value.get("permission") != permission or not isinstance(approved, list) or any(
                            not isinstance(item, str) or item not in batch for item in approved):
                        raise ValueError("invalid authorization response")
                    allowed.update(approved)
            except urllib.error.HTTPError as error:
                status = error.code
                error.close()
                if status in {403, 404}:
                    raise EvidenceError("recording_scope_rejected", "Recording permission or camera scope was revoked", 403) from None
                raise EvidenceError("authorization_unavailable", "Recording authorization is unavailable", 503) from None
            except (OSError, ValueError, urllib.error.URLError):
                raise EvidenceError("authorization_unavailable", "Recording authorization is unavailable", 503) from None
        if require_all and any(scope not in allowed for scope in scopes):
            raise EvidenceError("recording_scope_rejected", "Recording permission or camera scope was revoked", 403)
        return [camera_id for camera_id in camera_ids if mappings[camera_id] in allowed]

    def authorize_segment(self, owner: str, permission: str, segment_id: str) -> None:
        row = self.segment_row(segment_id)
        self.authorized_cameras(owner, permission, [row["camera_id"]])

    def authorize_export(self, owner: str, value: dict[str, Any], *, checked=None, deadline=None) -> None:
        token = os.environ.get("WEBOBS_CLUSTER_INTERNAL_TOKEN", "")
        if not token and os.environ.get("WEBOBS_CLUSTER_ENABLED", "false") != "true":
            return
        if not re.fullmatch(r"[a-f0-9]{64}", token):
            raise EvidenceError("authorization_unavailable", "Export authorization is unavailable", 503)
        for camera_id in value["cameraIds"]:
            camera = self.camera(camera_id)
            scope = (camera.get("cameraId") or camera_id) if camera else camera_id
            if checked is not None and scope in checked:
                continue
            timeout = min(2, deadline - time.monotonic()) if deadline is not None else 2
            if timeout <= 0:
                raise EvidenceError("authorization_unavailable", "Export authorization is unavailable", 503)
            payload = json.dumps({"username": owner, "permission": "export.create", "cameraId": scope}).encode()
            request = urllib.request.Request(service_http(8095, "/auth/authorize"), data=payload,
                headers={"Content-Type": "application/json", "X-WebObs-Internal-Admin": token})
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    if response.status != 200 or len(response.read(4097)) > 4096:
                        raise EvidenceError("authorization_unavailable", "Export authorization is unavailable", 503)
                    if checked is not None:
                        checked.add(scope)
            except urllib.error.HTTPError as error:
                status = error.code
                error.close()
                if status in {403, 404}:
                    raise EvidenceError("export_scope_rejected", "Export permission or camera scope was revoked", 403) from None
                raise EvidenceError("authorization_unavailable", "Export authorization is unavailable", 503) from None
            except (OSError, urllib.error.URLError):
                raise EvidenceError("authorization_unavailable", "Export authorization is unavailable", 503) from None

    write_evidence_manifest = staticmethod(atomic_json)

    @export_operation
    def export_clip(self, value: Any, *, job_id=None, cancel=None, owner="local-only") -> dict[str, Any]:
        return export_evidence(self, value, job_id=job_id, cancel=cancel, owner=owner)

    def download_path(self, relative: str, owner: str = "local-only") -> tuple[pathlib.Path, str]:
        parts = relative.split("/")
        if len(parts) == 1 and SAFE_ARTIFACT_NAME.fullmatch(parts[0]) and parts[0].endswith(".jpg"):
            artifact_id = parts[0][:-4]
            if not ARTIFACT_ID.fullmatch(artifact_id):
                raise KeyError(relative)
            snapshots = self.catalog.query("SELECT owner,camera_id FROM snapshots WHERE id=?", (artifact_id,))
            if snapshots:
                if snapshots[0]["owner"] != owner:
                    raise KeyError(relative)
                self.authorized_cameras(owner, "snapshot.create", [snapshots[0]["camera_id"]])
            else:
                # Pre-migration artifacts have no trustworthy ownership record.
                self.authorized_cameras(owner, "storage.manage", [])
            path = self.snapshot_root / parts[0]
            content_type = "image/jpeg"
        elif (len(parts) == 2 and ARTIFACT_ID.fullmatch(parts[0]) and
              SAFE_ARTIFACT_NAME.fullmatch(parts[1]) and parts[1].endswith((".mp4", ".json"))):
            exports = self.catalog.query("SELECT owner,request_json FROM exports WHERE id=?", (parts[0],))
            if not exports:
                raise KeyError(relative)
            if exports[0]["owner"]:
                if exports[0]["owner"] != owner:
                    raise KeyError(relative)
                self.authorize_export(owner, json.loads(exports[0]["request_json"]))
            else:
                self.authorized_cameras(owner, "storage.manage", [])
            path = self.exports_root / parts[0] / parts[1]
            content_type = "video/mp4" if parts[1].endswith(".mp4") else "application/json; charset=utf-8"
        else:
            raise KeyError(relative)
        resolved = path.resolve()
        if self.exports_root.resolve() not in resolved.parents or not resolved.is_file():
            raise KeyError(relative)
        return resolved, content_type

    def delete_segment(self, segment_id: str) -> None:
        with self.reader_lock:
            row = self.segment_row(segment_id)
            if row["locked"]:
                raise ConfigError("locked evidence cannot be deleted")
            self._expire_playback_leases()
            if self._segment_active(segment_id):
                raise ConfigError("segment is active in playback")
            self.media_path(segment_id).unlink()
            self.catalog.execute("UPDATE segments SET integrity='deleted',size_bytes=0 WHERE id=?", (segment_id,))
        self.audit("nvr.segment.deleted", segment_id=segment_id, camera_id=row["camera_id"])


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "webobs-nvrd"
    access_recheck_seconds = 30

    @property
    def service(self) -> NvrService:
        return self.server.service  # type: ignore[attr-defined]

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    @property
    def principal(self) -> str:
        value = self.headers.get("X-WebObs-Nvr-Principal", "local-only")
        if not CAMERA_ID.fullmatch(value):
            raise EvidenceError("invalid_principal", "Export principal is invalid", 403)
        return value

    @property
    def public_principal(self):
        # Product-owned loopback maintenance calls have no browser principal.
        return self.principal if "X-WebObs-Nvr-Principal" in self.headers else None

    def authorize(self, permission: str, segment_id=None, camera_id=None):
        owner = self.public_principal
        if owner is None:
            return
        if segment_id is not None:
            self.service.authorize_segment(owner, permission, segment_id)
        else:
            self.service.authorized_cameras(owner, permission, [camera_id] if camera_id is not None else [])

    def end_headers(self):
        self._response_started = True
        super().end_headers()

    def send_json(self, status: int, value: Any) -> None:
        if getattr(self, "_response_started", False):
            self.close_connection = True
            return  # Never append a second HTTP response to a partially sent file.
        encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(encoded)

    def send_bytes(self, status: int, content_type: str, value: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(value)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(value)

    def send_file(self, path: pathlib.Path, content_type: str, check_access=None) -> None:
        self.connection.settimeout(30)
        with path.open("rb") as source:
            stat = os.fstat(source.fileno())
            size = stat.st_size
            # Product recordings/artifacts are immutable. This validator binds
            # the open file instance, without hashing gigabytes before playback.
            etag = '"' + hashlib.sha256(f"{stat.st_ino}:{stat.st_mtime_ns}:{size}".encode()).hexdigest() + '"'
            if_none_match = self.headers.get("If-None-Match", "")
            if if_none_match == "*" or etag in [value.strip().removeprefix("W/") for value in if_none_match.split(",")]:
                self.send_response(304)
                self.send_header("ETag", etag)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            start, end = 0, size - 1
            range_header = self.headers.get("Range", "") if self.command == "GET" else ""
            if_range = self.headers.get("If-Range", "")
            if if_range and if_range != etag:
                try:
                    unchanged = not if_range.startswith(('"', 'W/')) and int(stat.st_mtime) <= email.utils.parsedate_to_datetime(if_range).timestamp()
                except (ValueError, TypeError, AttributeError, OverflowError):
                    unchanged = False
                if not unchanged:
                    range_header = ""
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header) if len(range_header) <= 128 else None
            invalid = bool(range_header and (not match or not any(match.groups())))
            if match and not invalid:
                if match.group(1):
                    start = int(match.group(1))
                    if match.group(2):
                        end = min(end, int(match.group(2)))
                else:
                    suffix = int(match.group(2))
                    invalid = suffix == 0
                    start = max(0, size - suffix)
                invalid = invalid or start > end or start >= size
            if invalid:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", "0")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            length = max(0, end - start + 1)
            self.send_response(206 if match else 200)
            self.send_header("Content-Type", content_type)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("ETag", etag)
            self.send_header("Last-Modified", email.utils.formatdate(stat.st_mtime, usegmt=True))
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            if urllib.parse.urlsplit(self.path).path.startswith("/downloads/"):
                self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
            if match:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            if self.command == "HEAD":
                return
            source.seek(start)
            remaining = length
            next_check = time.monotonic() + self.access_recheck_seconds
            while remaining:
                if check_access is not None and time.monotonic() >= next_check:
                    check_access()
                    next_check = time.monotonic() + self.access_recheck_seconds
                block = source.read(min(64 * 1024, remaining))
                if not block:
                    raise OSError("recording was truncated during transfer")
                self.wfile.write(block)
                remaining -= len(block)

    def metrics(self) -> bytes:
        status = self.service.status(self.public_principal, "metrics.view")
        lines = [
            "# TYPE webobs_nvr_up gauge", "webobs_nvr_up 1",
            "# TYPE webobs_nvr_free_bytes gauge", f"webobs_nvr_free_bytes {status['freeBytes']}",
            "# TYPE webobs_nvr_disk_pressure gauge", f"webobs_nvr_disk_pressure {1 if status['diskPressure'] else 0}",
            "# TYPE webobs_nvr_recovered_segments_total counter", f"webobs_nvr_recovered_segments_total {status['recovered']}",
            "# TYPE webobs_nvr_quarantined_segments_total counter", f"webobs_nvr_quarantined_segments_total {status['quarantined']}",
            "# TYPE webobs_nvr_retention_deletes_total counter", f"webobs_nvr_retention_deletes_total {status['retentionDeletes']}",
        ]
        for camera in status["cameras"]:
            camera_id = camera["id"]
            lines += [
                f'webobs_nvr_camera_recording{{camera_id="{camera_id}"}} {1 if camera["state"] == "recording" else 0}',
                f'webobs_nvr_camera_segments_total{{camera_id="{camera_id}"}} {camera["segments"]}',
                f'webobs_nvr_camera_bytes_total{{camera_id="{camera_id}"}} {camera["bytes"]}',
                f'webobs_nvr_camera_failures_total{{camera_id="{camera_id}"}} {camera["failures"]}',
                f'webobs_nvr_camera_write_latency_ms{{camera_id="{camera_id}"}} {camera["writeLatencyMs"]}',
            ]
        return ("\n".join(lines) + "\n").encode()

    def body(self) -> Any:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > MAX_BODY:
            raise ConfigError("request body size is invalid")
        return json.loads(self.rfile.read(length))

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlsplit(self.path)
        try:
            if parsed.path == "/health":
                self.send_json(200, {"status": "ok", "milestone": "M10-foundation"})
            elif parsed.path == "/status":
                self.send_json(200, self.service.status(self.public_principal))
            elif parsed.path == "/config":
                self.authorize("storage.manage")
                with self.service.config_lock:
                    self.send_json(200, redacted_config(self.service.config))
            elif parsed.path == "/metrics":
                self.send_bytes(200, "text/plain; version=0.0.4; charset=utf-8", self.metrics())
            elif parsed.path == "/segments":
                self.send_json(200, {"segments": self.service.segments(urllib.parse.parse_qs(parsed.query, keep_blank_values=True), self.public_principal)})
            elif parsed.path == "/timeline":
                self.send_json(200, self.service.timeline(urllib.parse.parse_qs(parsed.query, keep_blank_values=True), self.public_principal))
            elif parsed.path.startswith("/thumbnails/"):
                segment_id = parsed.path.removeprefix("/thumbnails/")
                if not SEGMENT_ID.fullmatch(segment_id):
                    raise KeyError(segment_id)
                query = urllib.parse.parse_qs(parsed.query)
                offset_ms = int(query.get("offsetMs", ["0"])[0])
                self.authorize("playback.view", segment_id=segment_id)
                with self.service.pin_segments([segment_id]):
                    self.send_file(self.service.thumbnail(segment_id, offset_ms), "image/jpeg")
            elif parsed.path.startswith("/media/"):
                segment_id = parsed.path.removeprefix("/media/")
                if not SEGMENT_ID.fullmatch(segment_id):
                    raise KeyError(segment_id)
                self.authorize("playback.view", segment_id=segment_id)
                with self.service.playback_reader(segment_id) as path:
                    self.send_file(path, "video/mp4", lambda: self.authorize("playback.view", segment_id=segment_id))
            elif parsed.path == "/exports/jobs":
                self.send_json(200, self.service.jobs.list(self.principal))
            elif parsed.path.startswith("/exports/jobs/"):
                self.send_json(200, self.service.jobs.get(self.principal, parsed.path.removeprefix("/exports/jobs/")))
            elif parsed.path.startswith("/downloads/"):
                relative = parsed.path.removeprefix("/downloads/")
                path, content_type = self.service.download_path(relative, self.principal)
                self.service.audit("nvr.artifact.downloaded", artifact_id=relative.split("/", 1)[0])
                self.send_file(path, content_type, lambda: self.service.download_path(relative, self.principal))
            else:
                self.send_json(404, {"error": {"code": "not_found", "message": "NVR resource not found"}})
        except EvidenceError as error:
            self.send_json(error.status, {"error": {"code": error.code, "message": str(error)}})
        except (ConfigError, ValueError) as error:
            self.send_json(422, {"error": {"code": "invalid_request", "message": str(error)}})
        except (KeyError, FileNotFoundError):
            self.send_json(404, {"error": {"code": "not_found", "message": "NVR resource not found"}})
        except Exception as error:
            self.send_json(500, {"error": {"code": "nvr_error", "message": type(error).__name__}})

    def do_PUT(self) -> None:  # noqa: N802
        try:
            if self.path == "/config":
                self.authorize("storage.manage")
                self.send_json(200, self.service.update_config(self.body()))
            elif self.path.startswith("/locks/"):
                segment_id = self.path.removeprefix("/locks/")
                if not SEGMENT_ID.fullmatch(segment_id):
                    raise KeyError(segment_id)
                self.authorize("recording.lock", segment_id=segment_id)
                body = self.body()
                if not isinstance(body, dict) or set(body) != {"locked"} or not isinstance(body["locked"], bool):
                    raise ConfigError("lock request requires one boolean locked field")
                self.service.set_lock(segment_id, body["locked"])
                self.send_json(200, {"id": segment_id, "locked": body["locked"]})
            else:
                self.send_json(404, {"error": {"code": "not_found", "message": "NVR resource not found"}})
        except EvidenceError as error:
            self.send_json(error.status, {"error": {"code": error.code, "message": str(error)}})
        except ConfigError as error:
            self.send_json(422, {"error": {"code": "invalid_nvr_config", "message": str(error)}})
        except KeyError:
            self.send_json(404, {"error": {"code": "not_found", "message": "NVR resource not found"}})

    def do_POST(self) -> None:  # noqa: N802
        try:
            if self.path == "/snapshots":
                value = self.body()
                if not isinstance(value, dict) or not isinstance(value.get("segmentId"), str) or not SEGMENT_ID.fullmatch(value["segmentId"]):
                    raise ConfigError("snapshot segmentId is invalid")
                self.authorize("snapshot.create", segment_id=value["segmentId"])
                self.send_json(201, self.service.snapshot(value, self.principal))
            elif self.path == "/exports":
                value = self.service.validate_export(self.body())
                self.service.authorize_export(self.principal, value)
                self.send_json(201, self.service.export_clip(value, owner=self.principal))
            elif self.path == "/exports/jobs":
                self.send_json(202, self.service.jobs.submit(self.principal, self.body()))
            elif self.path.startswith("/exports/jobs/") and self.path.endswith("/cancel"):
                if self.body() != {}:
                    raise ConfigError("cancel requires an empty object")
                job_id = self.path.removeprefix("/exports/jobs/").removesuffix("/cancel")
                self.send_json(200, self.service.jobs.cancel(self.principal, job_id))
            elif self.path == "/playback-leases":
                value = self.body()
                if not isinstance(value, dict) or not isinstance(value.get("segmentId"), str) or not SEGMENT_ID.fullmatch(value["segmentId"]):
                    raise ConfigError("playback lease segmentId is invalid")
                self.authorize("playback.view", segment_id=value["segmentId"])
                self.send_json(201, self.service.create_playback_lease(value, self.principal))
            elif self.path.startswith("/events/"):
                camera_id = self.path.removeprefix("/events/")
                if not CAMERA_ID.fullmatch(camera_id):
                    raise KeyError(camera_id)
                self.authorize("event.ack", camera_id=camera_id)
                body = self.body()
                if not isinstance(body, dict) or set(body) != {"active"} or not isinstance(body["active"], bool):
                    raise ConfigError("event request requires one boolean active field")
                self.service.set_event(camera_id, body["active"])
                self.send_json(200, {"cameraId": camera_id, "active": body["active"]})
            else:
                self.send_json(404, {"error": {"code": "not_found", "message": "NVR resource not found"}})
        except EvidenceError as error:
            self.send_json(error.status, {"error": {"code": error.code, "message": str(error)}})
        except ConfigError as error:
            self.send_json(422, {"error": {"code": "invalid_request", "message": str(error)}})
        except KeyError:
            self.send_json(404, {"error": {"code": "not_found", "message": "NVR resource not found"}})
        except Exception:
            self.send_json(500, {"error": {"code": "nvr_error", "message": "Evidence processing failed; check source availability and storage"}})

    def do_DELETE(self) -> None:  # noqa: N802
        try:
            if self.path.startswith("/playback-leases/"):
                lease_id = self.path.removeprefix("/playback-leases/")
                if not ARTIFACT_ID.fullmatch(lease_id):
                    raise KeyError(lease_id)
                self.service.release_playback_lease(lease_id, self.principal)
                self.send_json(200, {"id": lease_id, "released": True})
            elif self.path.startswith("/segments/"):
                segment_id = self.path.removeprefix("/segments/")
                if not SEGMENT_ID.fullmatch(segment_id):
                    raise KeyError(segment_id)
                self.authorize("recording.delete", segment_id=segment_id)
                self.service.delete_segment(segment_id)
                self.send_json(200, {"id": segment_id, "deleted": True})
            else:
                self.send_json(404, {"error": {"code": "not_found", "message": "NVR resource not found"}})
        except EvidenceError as error:
            self.send_json(error.status, {"error": {"code": error.code, "message": str(error)}})
        except ConfigError as error:
            self.send_json(409, {"error": {"code": "segment_conflict", "message": str(error)}})
        except KeyError:
            self.send_json(404, {"error": {"code": "not_found", "message": "NVR resource not found"}})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=os.environ.get("WEBOBS_NVR_CONFIG", "/config/webobs/nvr.json"))
    parser.add_argument("--storage", default=os.environ.get("WEBOBS_NVR_STORAGE", "/recordings/nvr"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("WEBOBS_NVR_INTERNAL_PORT", "8091")))
    parser.add_argument("--validate-config", action="store_true")
    args = parser.parse_args()
    config_path = pathlib.Path(args.config)
    storage_root = pathlib.Path(args.storage)
    if not config_path.is_absolute() or not storage_root.is_absolute() or not 1 <= args.port <= 65535:
        raise SystemExit("NVR config/storage must be absolute and port must be valid")
    os.umask(0o077)
    if args.validate_config:
        validate_config(private_json(config_path))
        return 0
    service = NvrService(config_path, storage_root)
    service.start()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.service = service  # type: ignore[attr-defined]
    server.daemon_threads = True

    def stop(_signum: int, _frame: Any) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    install_owner_shutdown(lambda: stop(0, None))
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    service.audit("nvr.started", camera_count=len(service.config["cameras"]))
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        service.shutdown()
        server.server_close()
        service.audit("nvr.stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
