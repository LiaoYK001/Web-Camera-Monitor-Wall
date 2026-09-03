#!/usr/bin/env python3
"""Internal Camera Registry and source-adapter service.

The public control plane proxies this loopback-only service. It never accepts
credentials embedded in URLs and stores only references to externally mounted
secrets.
"""

from __future__ import annotations

import json
import base64
import hashlib
import ipaddress
import os
import re
import secrets
import socket
import ssl
import sqlite3
import subprocess
import threading
import time
import tempfile
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from http.cookiejar import CookieJar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urljoin, urlsplit
from urllib.parse import quote, urlunsplit
from urllib.request import (
    HTTPBasicAuthHandler, HTTPDigestAuthHandler, HTTPPasswordMgrWithDefaultRealm,
    HTTPSHandler, HTTPCookieProcessor, HTTPRedirectHandler, Request, build_opener, urlopen,
)
from xml.sax.saxutils import escape

DB_PATH = Path(os.environ.get("WEBOBS_CAMERA_DATABASE", "/config/webobs/cameras.db"))
LISTEN = ("127.0.0.1", 8092)
MAX_BODY = 1024 * 1024
MAX_ONVIF_XML = 2 * 1024 * 1024
ONVIF_TIMEOUT_SECONDS = 6
TLS_CONTEXT = ssl.create_default_context(
    cafile=os.environ.get("WEBOBS_CAMERA_TLS_CA") or None)
SECRET_ROOT = Path(os.environ.get(
    "WEBOBS_CAMERA_SECRET_ROOT", "/run/secrets/webobs-camera-credentials"))
ADAPTERS = {
    "onvif", "rtsp", "mjpeg", "snapshot", "hls", "http-flv", "whep",
    "srt", "rtp", "v4l2",
}
ID_RE = re.compile(r"^[a-zA-Z0-9._-]{1,64}$")
SECRET_REF_RE = re.compile(r"^[a-zA-Z0-9._/-]{0,256}$")
PTZ_RATE_LOCK = threading.Lock()
PTZ_LAST_COMMAND: dict[str, float] = {}
PTZ_STOP_TIMERS: dict[str, threading.Timer] = {}
TALK_LOCK = threading.Lock()
TALK_PROCESSES: dict[str, subprocess.Popen] = {}
MAX_TALK_BYTES = 512 * 1024
MAX_TRACKS_PER_PROFILE = 16
MAX_CATALOG_PAGE = 256
MAX_OPERATIONAL_ISSUES = 4096
PROBE_TIMEOUT_SECONDS = 10
PROBE_OUTPUT_LIMIT = 1024 * 1024
PROBE_SEMAPHORE = threading.BoundedSemaphore(4)
PROBE_LOCKS_GUARD = threading.Lock()
PROBE_LOCKS: dict[str, threading.Lock] = {}
ONVIF_CLOCK_LOCK = threading.Lock()
ONVIF_CLOCK_OFFSETS: dict[str, float] = {}
ANALYTICS_SESSION_LOCK = threading.Lock()
ANALYTICS_PERSON_MODEL_ID = "ssd-mobilenet-v1-12-person"
ANALYTICS_PERSON_MODEL_VERSION = "onnx-model-zoo-4c46cd00"
ANALYTICS_PERSON_MODEL_SHA256 = "b8fba5e404077d4048d27fcd1667e85e27e192eb9bf51e696c46a3acd7d21058"
ANALYTICS_SESSIONS: dict[str, tuple[int, str, str]] = {}
# Bounded replay/rate state for browser analytics sessions.  Values contain no
# frames or endpoint data and are discarded when a session expires/closes.
ANALYTICS_SIGNAL_SEEN: dict[str, set[str]] = {}
ANALYTICS_SIGNAL_RATE: dict[str, tuple[int, int]] = {}
ANALYTICS_PROFILE_RATE: dict[tuple[str, str], tuple[int, int]] = {}


class OnvifError(RuntimeError):
    """Safe, credential-free ONVIF failure for API responses."""


class BrowserDirectProbeError(RuntimeError):
    """Bounded, endpoint-free browser media qualification failure."""


class RevisionConflict(RuntimeError):
    """Optimistic Camera Registry revision did not match."""


class InsecureHttpDenied(PermissionError):
    """A cleartext media endpoint was used without explicit Profile approval."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise OnvifError("ONVIF endpoint redirects are forbidden")


class SameOriginRedirect(HTTPRedirectHandler):
    """Follow same-origin redirects (e.g. MediaMTX live HLS session redirects)
    while forbidding any cross-origin hop."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if code not in (301, 302, 303, 307, 308):
            return None
        old = urlsplit(req.full_url)
        new = urlsplit(urljoin(req.full_url, newurl))
        if (old.scheme, old.hostname, old.port) != (new.scheme, new.hostname, new.port):
            raise OnvifError("cross-origin redirect is forbidden")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class ClosingConnection(sqlite3.Connection):
    """Commit or roll back a transaction and always release its file handle."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=3, factory=ClosingConnection)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def initialize() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    migration_backup: Path | None = None
    # A SQLite online backup captures a consistent pre-migration snapshot,
    # including databases currently using WAL.  Keep it beside the database
    # with restrictive permissions and remove it after a successful startup.
    # If any DDL/default backfill fails, restore the exact old bytes and let
    # the caller continue on the previous schema instead of a half-migrated
    # registry.
    if DB_PATH.is_file():
        try:
            source = sqlite3.connect(DB_PATH)
            try:
                user_version = int(source.execute("PRAGMA user_version").fetchone()[0])
                if user_version > 3:
                    raise RuntimeError("camera registry schema is newer than this runtime")
                if user_version < 3:
                    descriptor, temporary_name = tempfile.mkstemp(
                        prefix=f".{DB_PATH.name}.pre-v3-", dir=DB_PATH.parent)
                    os.close(descriptor)
                    migration_backup = Path(temporary_name)
                    os.chmod(migration_backup, 0o600)
                    destination = sqlite3.connect(migration_backup)
                    try:
                        source.backup(destination)
                    finally:
                        destination.close()
            finally:
                source.close()
        except Exception:
            if migration_backup:
                migration_backup.unlink(missing_ok=True)
            raise
    try:
      with connect() as database:
        database.execute("PRAGMA journal_mode=WAL")
        database.execute("PRAGMA synchronous=NORMAL")
        database.executescript(
            """
            CREATE TABLE IF NOT EXISTS cameras(
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              address TEXT NOT NULL,
              adapter TEXT NOT NULL,
              credentials_ref TEXT NOT NULL,
              hardware_decode TEXT NOT NULL,
              capabilities_json TEXT NOT NULL,
              health TEXT NOT NULL,
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS stream_profiles(
              id TEXT NOT NULL,
              camera_id TEXT NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
              name TEXT NOT NULL,
              role TEXT NOT NULL,
              endpoint TEXT NOT NULL,
              video_codec TEXT NOT NULL,
              audio_codec TEXT NOT NULL,
              width INTEGER NOT NULL,
              height INTEGER NOT NULL,
              fps REAL NOT NULL,
              PRIMARY KEY(camera_id,id)
            );
            CREATE INDEX IF NOT EXISTS stream_profiles_camera ON stream_profiles(camera_id);
            CREATE TABLE IF NOT EXISTS analytics_policies(
              camera_id TEXT NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
              profile_id TEXT NOT NULL,
              motion_enabled INTEGER NOT NULL DEFAULT 0,
              scene_change_enabled INTEGER NOT NULL DEFAULT 0,
              person_enabled INTEGER NOT NULL DEFAULT 0,
              allow_event_promotion INTEGER NOT NULL DEFAULT 0,
              promotion_threshold REAL NOT NULL DEFAULT 0.6,
              promotion_hold_seconds INTEGER NOT NULL DEFAULT 15,
              promotion_cooldown_seconds INTEGER NOT NULL DEFAULT 30,
              force_analytics_always_on INTEGER NOT NULL DEFAULT 0,
              motion_sensitivity REAL NOT NULL DEFAULT 0.15,
              motion_sample_fps REAL NOT NULL DEFAULT 2,
              motion_debounce_ms INTEGER NOT NULL DEFAULT 500,
              motion_cooldown_ms INTEGER NOT NULL DEFAULT 5000,
              scene_change_threshold REAL NOT NULL DEFAULT 0.55,
              scene_change_confirm_frames INTEGER NOT NULL DEFAULT 2,
              scene_change_cooldown_ms INTEGER NOT NULL DEFAULT 30000,
              person_confidence_threshold REAL NOT NULL DEFAULT 0.6,
              person_sample_fps REAL NOT NULL DEFAULT 1,
              person_max_boxes INTEGER NOT NULL DEFAULT 16,
              person_execution_preference TEXT NOT NULL DEFAULT 'auto',
              person_allow_server_fallback INTEGER NOT NULL DEFAULT 0,
              revision INTEGER NOT NULL DEFAULT 1,
              updated_at INTEGER NOT NULL,
              PRIMARY KEY(camera_id,profile_id)
            );
            CREATE TABLE IF NOT EXISTS onvif_profile_tokens(
              camera_id TEXT NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
              profile_id TEXT NOT NULL,
              device_token TEXT NOT NULL,
              PRIMARY KEY(camera_id,profile_id)
            );
            CREATE TABLE IF NOT EXISTS device_operation_audit(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              camera_id TEXT NOT NULL,
              operation TEXT NOT NULL,
              result TEXT NOT NULL,
              created_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS device_operation_audit_camera_time
              ON device_operation_audit(camera_id,created_at DESC);
            CREATE TABLE IF NOT EXISTS profile_tracks(
              camera_id TEXT NOT NULL,
              profile_id TEXT NOT NULL,
              track_index INTEGER NOT NULL,
              kind TEXT NOT NULL,
              codec TEXT NOT NULL,
              bitrate_kbps INTEGER,
              width INTEGER NOT NULL DEFAULT 0,
              height INTEGER NOT NULL DEFAULT 0,
              fps REAL NOT NULL DEFAULT 0,
              sample_rate INTEGER NOT NULL DEFAULT 0,
              channels INTEGER NOT NULL DEFAULT 0,
              source TEXT NOT NULL DEFAULT 'probe',
              PRIMARY KEY(camera_id,profile_id,track_index),
              FOREIGN KEY(camera_id,profile_id) REFERENCES stream_profiles(camera_id,id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS operational_issues(
              id TEXT PRIMARY KEY,
              fingerprint TEXT NOT NULL UNIQUE,
              code TEXT NOT NULL,
              severity TEXT NOT NULL,
              state TEXT NOT NULL,
              scope_kind TEXT NOT NULL,
              scope_id TEXT NOT NULL,
              component TEXT NOT NULL,
              first_seen_at INTEGER NOT NULL,
              last_seen_at INTEGER NOT NULL,
              occurrences INTEGER NOT NULL,
              summary TEXT NOT NULL,
              explanation TEXT NOT NULL,
              actions_json TEXT NOT NULL,
              details_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS operational_issues_state_time
              ON operational_issues(state,last_seen_at DESC);
            CREATE TABLE IF NOT EXISTS runtime_settings(
              id INTEGER PRIMARY KEY CHECK(id=1),
              revision INTEGER NOT NULL,
              settings_json TEXT NOT NULL,
              updated_at INTEGER NOT NULL
            );
            """
        )
        camera_columns = {row["name"] for row in database.execute("PRAGMA table_info(cameras)")}
        for name, definition in (
            ("kind", "TEXT NOT NULL DEFAULT 'camera'"),
            ("enabled", "INTEGER NOT NULL DEFAULT 1"),
            ("group_id", "TEXT NOT NULL DEFAULT ''"),
            ("tags_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("revision", "INTEGER NOT NULL DEFAULT 1"),
        ):
            if name not in camera_columns:
                database.execute(f"ALTER TABLE cameras ADD COLUMN {name} {definition}")
        profile_columns = {row["name"] for row in database.execute("PRAGMA table_info(stream_profiles)")}
        for name, definition in (
            ("enabled", "INTEGER NOT NULL DEFAULT 1"),
            ("transport_mode", "TEXT NOT NULL DEFAULT 'auto'"),
            ("live_bitrate_cap_kbps", "INTEGER"),
            ("audio_expectation", "TEXT NOT NULL DEFAULT 'auto'"),
            ("allow_insecure_http", "INTEGER NOT NULL DEFAULT 0"),
            ("probe_state", "TEXT NOT NULL DEFAULT 'legacy'"),
            ("last_probe_at", "INTEGER NOT NULL DEFAULT 0"),
        ):
            if name not in profile_columns:
                database.execute(f"ALTER TABLE stream_profiles ADD COLUMN {name} {definition}")
        policy_columns = {row["name"] for row in database.execute("PRAGMA table_info(analytics_policies)")}
        for name, definition in (
            ("motion_sensitivity", "REAL NOT NULL DEFAULT 0.15"),
            ("motion_sample_fps", "REAL NOT NULL DEFAULT 2"),
            ("motion_debounce_ms", "INTEGER NOT NULL DEFAULT 500"),
            ("motion_cooldown_ms", "INTEGER NOT NULL DEFAULT 5000"),
            ("scene_change_threshold", "REAL NOT NULL DEFAULT 0.55"),
            ("scene_change_confirm_frames", "INTEGER NOT NULL DEFAULT 2"),
            ("scene_change_cooldown_ms", "INTEGER NOT NULL DEFAULT 30000"),
            ("person_confidence_threshold", "REAL NOT NULL DEFAULT 0.6"),
            ("person_sample_fps", "REAL NOT NULL DEFAULT 1"),
            ("person_max_boxes", "INTEGER NOT NULL DEFAULT 16"),
            ("person_execution_preference", "TEXT NOT NULL DEFAULT 'auto'"),
            ("person_allow_server_fallback", "INTEGER NOT NULL DEFAULT 0"),
            ("revision", "INTEGER NOT NULL DEFAULT 1"),
        ):
            if name not in policy_columns:
                database.execute(f"ALTER TABLE analytics_policies ADD COLUMN {name} {definition}")
        database.execute("""CREATE TABLE IF NOT EXISTS analytics_metadata(
            id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL DEFAULT 1,
            updated_at INTEGER NOT NULL)""")
        database.execute("INSERT OR IGNORE INTO analytics_metadata(id,revision,updated_at) VALUES(1,1,?)", (int(time.time()),))
        defaults = {
            "defaultTransportMode": "auto", "probeTimeoutSeconds": PROBE_TIMEOUT_SECONDS,
            "sourceRecoveryEnabled": True, "issueRetentionLimit": MAX_OPERATIONAL_ISSUES,
        }
        database.execute(
            "INSERT OR IGNORE INTO runtime_settings(id,revision,settings_json,updated_at) VALUES(1,1,?,?)",
            (json.dumps(defaults, separators=(",", ":"), sort_keys=True), int(time.time())),
        )
        database.execute("PRAGMA user_version=3")
    except Exception:
        if migration_backup and migration_backup.is_file():
            for suffix in ("", "-wal", "-shm"):
                Path(f"{DB_PATH}{suffix}").unlink(missing_ok=True)
            os.replace(migration_backup, DB_PATH)
        raise
    finally:
        if migration_backup:
            migration_backup.unlink(missing_ok=True)


def audit_device_operation(camera_id: str, operation: str, result: str) -> None:
    safe_operation = re.sub(r"[^a-zA-Z0-9._-]", "-", operation)[:64]
    safe_result = result if result in {"accepted", "completed", "stopped", "failed", "denied"} else "failed"
    with connect() as database:
        database.execute(
            "INSERT INTO device_operation_audit(camera_id,operation,result,created_at) VALUES(?,?,?,?)",
            (camera_id, safe_operation, safe_result, int(time.time())),
        )
        database.execute(
            "DELETE FROM device_operation_audit WHERE id NOT IN "
            "(SELECT id FROM device_operation_audit ORDER BY id DESC LIMIT 4096)"
        )
    print(json.dumps({"event": "device_operation", "cameraId": camera_id,
                      "operation": safe_operation, "result": safe_result},
                     separators=(",", ":"), sort_keys=True), flush=True)


def safe_endpoint(value: str, adapter: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 2048 or any(ord(c) < 32 for c in value):
        raise ValueError("endpoint is required and must be at most 2048 bytes")
    if adapter == "v4l2":
        if not re.fullmatch(r"/dev/video[0-9]{1,3}", value):
            raise ValueError("v4l2 endpoint must be /dev/video<n>")
        return value
    parsed = urlsplit(value if "://" in value else "http://" + value)
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("embedded URL credentials are forbidden; use credentialsRef")
    if parsed.fragment or any(key in parsed.query.lower() for key in ("token", "pass", "secret", "key", "sig")):
        raise ValueError("credential-like URL query or fragment is forbidden")
    schemes = {
        "onvif": {"http", "https"}, "rtsp": {"rtsp", "rtsps"},
        "mjpeg": {"http", "https"}, "snapshot": {"http", "https"},
        "hls": {"http", "https"}, "http-flv": {"http", "https"},
        "whep": {"http", "https"}, "srt": {"srt"}, "rtp": {"rtp", "udp"},
    }
    if parsed.scheme.lower() not in schemes[adapter] or not parsed.hostname:
        raise ValueError(f"endpoint scheme is not valid for {adapter}")
    return value if "://" in value else "http://" + value


def load_credentials(credentials_ref: str) -> tuple[str, str]:
    if not credentials_ref:
        return "", ""
    if not SECRET_REF_RE.fullmatch(credentials_ref) or ".." in credentials_ref.split("/"):
        raise PermissionError("camera credential reference is invalid")
    secret_root = SECRET_ROOT.resolve()
    secret_path = (secret_root / f"{credentials_ref}.json").resolve()
    if secret_root not in secret_path.parents or not secret_path.is_file():
        raise PermissionError("camera credential reference is unavailable")
    try:
        secret = json.loads(secret_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise PermissionError("camera credential secret is invalid") from error
    username, password = secret.get("username", ""), secret.get("password", "")
    if (not isinstance(username, str) or not isinstance(password, str) or not username or
            len(username) > 256 or len(password) > 512):
        raise PermissionError("camera credential secret is invalid")
    return username, password


def endpoint_with_credentials(endpoint: str, username: str, password: str) -> str:
    if not username:
        return endpoint
    parsed = urlsplit(endpoint)
    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    if parsed.port:
        host = f"{host}:{parsed.port}"
    authority = f"{quote(username, safe='')}:{quote(password, safe='')}@{host}"
    return urlunsplit((parsed.scheme, authority, parsed.path, parsed.query, ""))


def validate_tags(value: object) -> list[str]:
    if not isinstance(value, list) or len(value) > 32:
        raise ValueError("tags must contain at most 32 strings")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not 1 <= len(item.strip()) <= 32 or any(ord(c) < 32 for c in item):
            raise ValueError("each tag must contain 1 to 32 printable characters")
        normalized = item.strip()
        if normalized not in result:
            result.append(normalized)
    return result


def transport_modes_for(adapter: str) -> set[str]:
    if adapter in {"rtsp", "onvif"}:
        return {"auto", "rtsp-tcp", "rtsp-udp", "rtsp-udp-multicast"}
    if adapter in {"mjpeg", "snapshot", "hls", "http-flv", "whep"}:
        return {"auto", "http", "https"}
    return {"auto"}


def validate_profile(profile: dict, adapter: str) -> dict:
    if not isinstance(profile, dict):
        raise ValueError("profiles must contain objects")
    profile_id = profile.get("id", "main")
    if not isinstance(profile_id, str) or not ID_RE.fullmatch(profile_id):
        raise ValueError("profile id is invalid")
    endpoint_adapter = "rtsp" if adapter == "onvif" and str(profile.get("endpoint", "")).startswith(("rtsp://", "rtsps://")) else adapter
    endpoint = safe_endpoint(profile.get("endpoint", ""), endpoint_adapter)
    role = profile.get("role", "main")
    if role not in ("main", "sub", "snapshot", "auxiliary"):
        raise ValueError("profile role is invalid")
    width = int(profile.get("width", 0))
    height = int(profile.get("height", 0))
    fps = float(profile.get("fps", 0))
    if width < 0 or width > 16384 or height < 0 or height > 16384 or fps < 0 or fps > 240:
        raise ValueError("profile media dimensions are out of range")
    enabled = profile.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError("profile enabled must be boolean")
    transport_mode = profile.get("transportMode", "auto")
    if transport_mode not in transport_modes_for(adapter):
        raise ValueError("profile transportMode is not valid for this adapter")
    bitrate_cap = profile.get("liveBitrateCapKbps")
    if bitrate_cap is not None and (isinstance(bitrate_cap, bool) or not isinstance(bitrate_cap, int) or
                                    not 32 <= bitrate_cap <= 1_000_000):
        raise ValueError("liveBitrateCapKbps must be null or between 32 and 1000000")
    audio_expectation = profile.get("audioExpectation", "auto")
    if audio_expectation not in {"auto", "required", "disabled"}:
        raise ValueError("audioExpectation must be auto, required, or disabled")
    allow_insecure_http = profile.get("allowInsecureHttp", False)
    if not isinstance(allow_insecure_http, bool):
        raise ValueError("allowInsecureHttp must be boolean")
    if allow_insecure_http and not endpoint.startswith("http://"):
        raise ValueError("allowInsecureHttp is only valid for an HTTP media endpoint")
    return {
        "id": profile_id, "name": str(profile.get("name", profile_id))[:128], "role": role,
        "endpoint": endpoint, "videoCodec": str(profile.get("videoCodec", "unknown"))[:32].lower(),
        "audioCodec": str(profile.get("audioCodec", ""))[:32].lower(),
        "width": width, "height": height, "fps": fps,
        "enabled": enabled, "transportMode": transport_mode,
        "liveBitrateCapKbps": bitrate_cap, "audioExpectation": audio_expectation,
        "allowInsecureHttp": allow_insecure_http,
        "probeState": str(profile.get("probeState", "legacy"))[:32],
        "lastProbeAt": int(profile.get("lastProbeAt", 0)),
    }


def validate_camera(payload: dict, existing_id: str | None = None) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("camera document must be an object")
    camera_id = existing_id or payload.get("id") or f"camera-{uuid.uuid4().hex[:12]}"
    if not isinstance(camera_id, str) or not ID_RE.fullmatch(camera_id):
        raise ValueError("camera id is invalid")
    name = payload.get("name", "")
    adapter = payload.get("adapter", "")
    if not isinstance(name, str) or not name.strip() or len(name) > 128:
        raise ValueError("camera name must contain 1 to 128 characters")
    if adapter not in ADAPTERS:
        raise ValueError("camera adapter is unsupported")
    address = safe_endpoint(payload.get("address", ""), adapter)
    credentials_ref = payload.get("credentialsRef", "")
    if not isinstance(credentials_ref, str) or not SECRET_REF_RE.fullmatch(credentials_ref) or ".." in credentials_ref.split("/"):
        raise ValueError("credentialsRef is invalid")
    hardware_decode = payload.get("hardwareDecode", "auto")
    if hardware_decode not in ("auto", "on", "off"):
        raise ValueError("hardwareDecode must be auto, on, or off")
    profiles = [validate_profile(profile, adapter) for profile in payload.get("profiles", [])]
    if len(profiles) > 16 or len({profile["id"] for profile in profiles}) != len(profiles):
        raise ValueError("camera must have at most 16 uniquely named profiles")
    capabilities = payload.get("capabilities", {})
    if not isinstance(capabilities, dict):
        raise ValueError("capabilities must be an object")
    capabilities = dict(capabilities)
    capabilities.pop("browserDirect", None)
    capabilities.pop("iwaDirectLab", None)
    kind = payload.get("kind", "camera")
    enabled = payload.get("enabled", True)
    group_id = payload.get("groupId", "")
    if kind not in {"camera", "network-stream"}:
        raise ValueError("camera kind must be camera or network-stream")
    if not isinstance(enabled, bool):
        raise ValueError("camera enabled must be boolean")
    if not isinstance(group_id, str) or len(group_id) > 64 or any(ord(c) < 32 for c in group_id):
        raise ValueError("groupId must contain at most 64 printable characters")
    tags = validate_tags(payload.get("tags", []))
    revision = payload.get("revision", 1)
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError("camera revision must be a positive integer")
    return {
        "id": camera_id, "name": name.strip(), "address": address, "adapter": adapter,
        "credentialsRef": credentials_ref, "hardwareDecode": hardware_decode,
        "capabilities": capabilities, "profiles": profiles, "kind": kind,
        "enabled": enabled, "groupId": group_id.strip(), "tags": tags, "revision": revision,
    }


def track_documents(database: sqlite3.Connection, camera_id: str, profile: sqlite3.Row) -> list[dict]:
    rows = database.execute(
        "SELECT track_index,kind,codec,bitrate_kbps,width,height,fps,sample_rate,channels,source "
        "FROM profile_tracks WHERE camera_id=? AND profile_id=? ORDER BY track_index",
        (camera_id, profile["id"]),
    ).fetchall()
    if rows:
        return [{
            "index": item["track_index"], "kind": item["kind"], "codec": item["codec"],
            "bitrateKbps": item["bitrate_kbps"], "width": item["width"], "height": item["height"],
            "fps": item["fps"], "sampleRate": item["sample_rate"], "channels": item["channels"],
            "source": item["source"],
        } for item in rows]
    result = []
    if profile["video_codec"]:
        result.append({"index": 0, "kind": "video", "codec": profile["video_codec"],
                       "bitrateKbps": None, "width": profile["width"], "height": profile["height"],
                       "fps": profile["fps"], "sampleRate": 0, "channels": 0, "source": "legacy"})
    if profile["audio_codec"]:
        result.append({"index": len(result), "kind": "audio", "codec": profile["audio_codec"],
                       "bitrateKbps": None, "width": 0, "height": 0, "fps": 0,
                       "sampleRate": 0, "channels": 0, "source": "legacy"})
    return result


def profile_document(database: sqlite3.Connection, camera_id: str, profile: sqlite3.Row,
                     include_endpoint: bool = True) -> dict:
    result = {
        "id": profile["id"], "name": profile["name"], "role": profile["role"],
        "videoCodec": profile["video_codec"], "audioCodec": profile["audio_codec"],
        "width": profile["width"], "height": profile["height"], "fps": profile["fps"],
        "enabled": bool(profile["enabled"]), "transportMode": profile["transport_mode"],
        "liveBitrateCapKbps": profile["live_bitrate_cap_kbps"],
        "audioExpectation": profile["audio_expectation"],
        "allowInsecureHttp": bool(profile["allow_insecure_http"]), "probeState": profile["probe_state"],
        "lastProbeAt": profile["last_probe_at"], "tracks": track_documents(database, camera_id, profile),
    }
    if include_endpoint:
        result["endpoint"] = profile["endpoint"]
    return result


def camera_document(database: sqlite3.Connection, row: sqlite3.Row) -> dict:
    profile_rows = database.execute(
        "SELECT * FROM stream_profiles WHERE camera_id=? ORDER BY role,id", (row["id"],)
    ).fetchall()
    profiles = [profile_document(database, row["id"], profile) for profile in profile_rows]
    return {
        "id": row["id"], "name": row["name"], "address": row["address"],
        "adapter": row["adapter"], "credentialsRef": row["credentials_ref"],
        "hardwareDecode": row["hardware_decode"], "capabilities": json.loads(row["capabilities_json"]),
        "health": row["health"], "profiles": profiles, "createdAt": row["created_at"],
        "updatedAt": row["updated_at"], "kind": row["kind"], "enabled": bool(row["enabled"]),
        "groupId": row["group_id"], "tags": json.loads(row["tags_json"]), "revision": row["revision"],
    }


def sanitized_endpoint(value: str) -> str:
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        if parsed.port:
            host = f"{host}:{parsed.port}"
        return urlunsplit((parsed.scheme, host, parsed.path, "", ""))
    except ValueError:
        return "unavailable"


def source_catalog_document(database: sqlite3.Connection, row: sqlite3.Row) -> dict:
    profile_rows = database.execute(
        "SELECT * FROM stream_profiles WHERE camera_id=? ORDER BY role,id", (row["id"],)
    ).fetchall()
    profiles = []
    total_tracks = 0
    for profile in profile_rows:
        value = profile_document(database, row["id"], profile, include_endpoint=False)
        value["endpointDisplay"] = sanitized_endpoint(profile["endpoint"])
        total_tracks += len(value["tracks"])
        profiles.append(value)
    try:
        onvif = json.loads(row["capabilities_json"] or "{}").get("onvif", {})
    except (json.JSONDecodeError, AttributeError):
        onvif = {}
    safe_capabilities = {
        "ptz": bool(onvif.get("ptz", False)),
        "snapshot": bool(onvif.get("snapshot", False)),
        "talk": bool(onvif.get("talk", False)),
    }
    return {
        "schemaVersion": 2, "id": row["id"], "name": row["name"], "kind": row["kind"],
        "adapter": row["adapter"], "enabled": bool(row["enabled"]), "groupId": row["group_id"],
        "tags": json.loads(row["tags_json"]), "addressDisplay": sanitized_endpoint(row["address"]),
        "health": row["health"], "hardwareDecode": row["hardware_decode"],
        "deviceCapabilities": safe_capabilities,
        "profileCount": len(profiles), "trackCount": total_tracks, "profiles": profiles,
        "revision": row["revision"], "createdAt": row["created_at"], "updatedAt": row["updated_at"],
    }


def analytics_policy_document(row: sqlite3.Row) -> dict:
    return {
        "cameraId": row["camera_id"], "profileId": row["profile_id"],
        "motionEnabled": bool(row["motion_enabled"]),
        "sceneChangeEnabled": bool(row["scene_change_enabled"]),
        "personEnabled": bool(row["person_enabled"]),
        "allowEventPromotion": bool(row["allow_event_promotion"]),
        "promotionThreshold": row["promotion_threshold"],
        "promotionHoldSeconds": row["promotion_hold_seconds"],
        "promotionCooldownSeconds": row["promotion_cooldown_seconds"],
        "forceAnalyticsAlwaysOn": bool(row["force_analytics_always_on"]),
        "revision": row["revision"],
        "motion": {"sensitivity": row["motion_sensitivity"], "sampleFps": row["motion_sample_fps"],
                    "debounceMs": row["motion_debounce_ms"], "cooldownMs": row["motion_cooldown_ms"]},
        "sceneChange": {"threshold": row["scene_change_threshold"], "confirmFrames": row["scene_change_confirm_frames"],
                        "cooldownMs": row["scene_change_cooldown_ms"]},
        "person": {"confidenceThreshold": row["person_confidence_threshold"], "sampleFps": row["person_sample_fps"],
                   "maxBoxes": row["person_max_boxes"], "executionPreference": row["person_execution_preference"],
                   "allowServerFallback": bool(row["person_allow_server_fallback"])},
        "updatedAt": row["updated_at"],
    }


def analytics_policies() -> list[dict]:
    with connect() as database:
        rows = database.execute("SELECT * FROM analytics_policies ORDER BY camera_id,profile_id").fetchall()
        return [analytics_policy_document(row) for row in rows]


def save_analytics_policies(payload: dict) -> list[dict]:
    values = payload.get("policies") if isinstance(payload, dict) else None
    if not isinstance(values, list) or not values or len(values) > 256:
        raise ValueError("policies must contain 1 to 256 items")
    normalized = []
    for value in values:
        if not isinstance(value, dict):
            raise ValueError("policy must be an object")
        camera_id, profile_id = value.get("cameraId"), value.get("profileId")
        if not isinstance(camera_id, str) or not ID_RE.fullmatch(camera_id) or \
                not isinstance(profile_id, str) or not ID_RE.fullmatch(profile_id):
            raise ValueError("cameraId or profileId is invalid")
        booleans = [value.get(key, False) for key in (
            "motionEnabled", "sceneChangeEnabled", "personEnabled", "allowEventPromotion",
            "forceAnalyticsAlwaysOn")]
        if any(not isinstance(item, bool) for item in booleans):
            raise ValueError("analytics switches must be boolean")
        threshold = value.get("promotionThreshold", .6)
        hold = value.get("promotionHoldSeconds", 15)
        cooldown = value.get("promotionCooldownSeconds", 30)
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1:
            raise ValueError("promotionThreshold must be between 0 and 1")
        if isinstance(hold, bool) or not isinstance(hold, int) or not 1 <= hold <= 3600 or \
                isinstance(cooldown, bool) or not isinstance(cooldown, int) or not 0 <= cooldown <= 86400:
            raise ValueError("promotion timing is out of range")
        motion = value.get("motion") if isinstance(value.get("motion"), dict) else {}
        scene = value.get("sceneChange") if isinstance(value.get("sceneChange"), dict) else {}
        person = value.get("person") if isinstance(value.get("person"), dict) else {}
        motion_sensitivity = motion.get("sensitivity", .15); motion_fps = motion.get("sampleFps", 2)
        motion_debounce = motion.get("debounceMs", 500); motion_cooldown = motion.get("cooldownMs", 5000)
        scene_threshold = scene.get("threshold", .55); scene_confirm = scene.get("confirmFrames", 2); scene_cooldown = scene.get("cooldownMs", 30000)
        person_threshold = person.get("confidenceThreshold", .6); person_fps = person.get("sampleFps", 1); person_boxes = person.get("maxBoxes", 16)
        person_execution = person.get("executionPreference", "auto"); person_fallback = person.get("allowServerFallback", False)
        if (isinstance(motion_sensitivity, bool) or not isinstance(motion_sensitivity, (int, float)) or not .01 <= motion_sensitivity <= 1 or
            isinstance(motion_fps, bool) or not isinstance(motion_fps, (int, float)) or not .1 <= motion_fps <= 5 or
            any(isinstance(item, bool) or not isinstance(item, int) or not 0 <= item <= 3_600_000 for item in (motion_debounce, motion_cooldown))):
            raise ValueError("motion analytics settings are out of range")
        if (isinstance(scene_threshold, bool) or not isinstance(scene_threshold, (int, float)) or not .05 <= scene_threshold <= 1 or
            isinstance(scene_confirm, bool) or not isinstance(scene_confirm, int) or not 1 <= scene_confirm <= 5 or
            isinstance(scene_cooldown, bool) or not isinstance(scene_cooldown, int) or not 0 <= scene_cooldown <= 3_600_000):
            raise ValueError("scene change settings are out of range")
        if (isinstance(person_threshold, bool) or not isinstance(person_threshold, (int, float)) or not .05 <= person_threshold <= 1 or
            isinstance(person_fps, bool) or not isinstance(person_fps, (int, float)) or not .1 <= person_fps <= 5 or
            isinstance(person_boxes, bool) or not isinstance(person_boxes, int) or not 1 <= person_boxes <= 16 or
            person_execution not in {"auto", "browser", "worker"} or not isinstance(person_fallback, bool)):
            raise ValueError("person analytics settings are out of range")
        normalized.append((camera_id, profile_id, *[int(item) for item in booleans], float(threshold), hold, cooldown,
                           float(motion_sensitivity), float(motion_fps), motion_debounce, motion_cooldown,
                           float(scene_threshold), scene_confirm, scene_cooldown, float(person_threshold), float(person_fps),
                           person_boxes, person_execution, int(person_fallback), int(time.time())))
    with connect() as database:
        for camera_id, profile_id, *_ in normalized:
            exists = database.execute(
                "SELECT 1 FROM stream_profiles WHERE camera_id=? AND id=?", (camera_id, profile_id)).fetchone()
            if not exists:
                raise KeyError("camera profile not found")
        database.executemany(
            "INSERT INTO analytics_policies(camera_id,profile_id,motion_enabled,scene_change_enabled,person_enabled,"
            "allow_event_promotion,force_analytics_always_on,promotion_threshold,promotion_hold_seconds,"
            "promotion_cooldown_seconds,motion_sensitivity,motion_sample_fps,motion_debounce_ms,motion_cooldown_ms,"
            "scene_change_threshold,scene_change_confirm_frames,scene_change_cooldown_ms,person_confidence_threshold,"
            "person_sample_fps,person_max_boxes,person_execution_preference,person_allow_server_fallback,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(camera_id,profile_id) DO UPDATE SET motion_enabled=excluded.motion_enabled,"
            "scene_change_enabled=excluded.scene_change_enabled,person_enabled=excluded.person_enabled,"
            "allow_event_promotion=excluded.allow_event_promotion,force_analytics_always_on=excluded.force_analytics_always_on,"
            "promotion_threshold=excluded.promotion_threshold,promotion_hold_seconds=excluded.promotion_hold_seconds,"
            "promotion_cooldown_seconds=excluded.promotion_cooldown_seconds,motion_sensitivity=excluded.motion_sensitivity,"
            "motion_sample_fps=excluded.motion_sample_fps,motion_debounce_ms=excluded.motion_debounce_ms,motion_cooldown_ms=excluded.motion_cooldown_ms,"
            "scene_change_threshold=excluded.scene_change_threshold,scene_change_confirm_frames=excluded.scene_change_confirm_frames,"
            "scene_change_cooldown_ms=excluded.scene_change_cooldown_ms,person_confidence_threshold=excluded.person_confidence_threshold,"
            "person_sample_fps=excluded.person_sample_fps,person_max_boxes=excluded.person_max_boxes,"
            "person_execution_preference=excluded.person_execution_preference,person_allow_server_fallback=excluded.person_allow_server_fallback,"
            "revision=analytics_policies.revision+1,updated_at=excluded.updated_at",
            normalized,
        )
        database.execute("UPDATE analytics_metadata SET revision=revision+1,updated_at=? WHERE id=1", (int(time.time()),))
        keys = {(item[0], item[1]) for item in normalized}
        rows = database.execute("SELECT * FROM analytics_policies ORDER BY camera_id,profile_id").fetchall()
        return [analytics_policy_document(row) for row in rows if (row["camera_id"], row["profile_id"]) in keys]


def analytics_revision() -> int:
    with connect() as database:
        row = database.execute("SELECT revision FROM analytics_metadata WHERE id=1").fetchone()
        return int(row["revision"] if row else 1)


def analytics_v3_policies(payload: dict, expected_revision: int | None = None) -> dict:
    current = analytics_revision()
    if expected_revision is not None and expected_revision != current:
        raise RevisionConflict(str(current))
    policies = save_analytics_policies(payload)
    return {"schemaVersion": 2, "revision": analytics_revision(), "policies": policies}


def analytics_runtime_plan(payload: dict) -> dict:
    if not isinstance(payload, dict): raise ValueError("runtime plan must be an object")
    camera_id, profile_id = payload.get("cameraId", ""), payload.get("profileId", "")
    if not isinstance(camera_id, str) or not ID_RE.fullmatch(camera_id) or not isinstance(profile_id, str) or not ID_RE.fullmatch(profile_id):
        raise ValueError("camera or profile id is invalid")
    kinds = payload.get("kinds", ["motion", "scene-change", "person"])
    if not isinstance(kinds, list) or not kinds or len(kinds) > 3 or any(item not in {"motion", "scene-change", "person"} for item in kinds):
        raise ValueError("analytics kinds are invalid")
    capabilities = payload.get("capabilities", {}) if isinstance(payload.get("capabilities", {}), dict) else {}
    webgpu = capabilities.get("webgpu") is True; wasm = capabilities.get("wasm") is not False
    with connect() as database:
        row = database.execute(
            "SELECT p.*, c.adapter, c.credentials_ref, c.capabilities_json, c.enabled AS camera_enabled, "
            "s.enabled AS profile_enabled, s.endpoint, s.allow_insecure_http "
            "FROM analytics_policies p JOIN cameras c ON c.id=p.camera_id "
            "JOIN stream_profiles s ON s.camera_id=p.camera_id AND s.id=p.profile_id "
            "WHERE p.camera_id=? AND p.profile_id=?", (camera_id, profile_id)).fetchone()
    if not row: raise KeyError("analytics policy not found")
    if not bool(row["camera_enabled"]) or not bool(row["profile_enabled"]):
        raise PermissionError("camera profile is disabled")

    # Browser True Direct is a server-computed qualification.  A client may
    # report its capabilities, but it cannot assert that a profile is safe to
    # load directly.  Reuse only the proof written by browser_direct_probe:
    # HTTPS, no URL credentials/query, no Camera Secret, and a recent
    # TLS/CORS check bound to the configured PWA origin.  HTTP exemptions and
    # RTSP therefore remain Gateway/Hybrid media paths.
    adapter = str(row["adapter"]).lower()
    media_transport = adapter if adapter in {"whep", "hls", "mjpeg"} else "rtsp"
    direct_eligible = False
    if media_transport in {"whep", "hls", "mjpeg"}:
        try:
            parsed_endpoint = urlsplit(str(row["endpoint"]))
            capabilities_json = json.loads(row["capabilities_json"] or "{}")
            proof = (((capabilities_json.get("browserDirect") or {}).get("profiles") or {}).get(profile_id) or {})
            origin = configured_pwa_origin()
            checked_at = int(proof.get("checkedAt", 0))
            direct_eligible = (
                parsed_endpoint.scheme.lower() == "https"
                and not parsed_endpoint.username and not parsed_endpoint.password
                and not parsed_endpoint.query and not parsed_endpoint.fragment
                and not str(row["credentials_ref"])
                and not bool(row["allow_insecure_http"])
                and proof.get("tlsVerified") is True
                and proof.get("corsVerified") is True
                and proof.get("pwaOriginSha256") == hashlib.sha256(origin.encode()).hexdigest()
                and checked_at >= int(time.time()) - 48 * 3600
            )
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            direct_eligible = False

    expires = int(time.time()) + 600; session_id = secrets.token_urlsafe(32)
    with ANALYTICS_SESSION_LOCK:
        ANALYTICS_SESSIONS[session_id] = (expires, camera_id, profile_id)
        ANALYTICS_SIGNAL_SEEN[session_id] = set()
        ANALYTICS_SIGNAL_RATE[session_id] = (int(time.time() // 60), 0)
    result = []
    for kind in ("motion", "scene-change", "person"):
        enabled = bool(row[{"motion": "motion_enabled", "scene-change": "scene_change_enabled", "person": "person_enabled"}[kind]])
        if kind == "person":
            # ``worker`` is an explicit execution choice; ``allowServerFallback``
            # permits the same server path only after the preferred browser
            # providers are unavailable.  A ``browser`` preference therefore
            # never expands the media chain unless that separate fallback
            # switch is enabled.
            preference = row["person_execution_preference"]
            if not enabled:
                execution = "off"
            elif preference == "worker":
                execution = "worker"
            elif webgpu:
                execution = "browser-webgpu"
            elif wasm:
                execution = "browser-wasm"
            elif row["person_allow_server_fallback"]:
                execution = "worker"
            else:
                execution = "unsupported"
            owner = "browser" if execution.startswith("browser") else "worker" if execution == "worker" else "none"
            sample = float(row["person_sample_fps"])
        else:
            execution = "native" if enabled and kind == "motion" and capabilities.get("onvifMotion") is True else "browser-wasm" if enabled and wasm else "unsupported" if enabled else "off"
            owner = "camera" if execution == "native" else "browser" if execution.startswith("browser") else "none"
            sample = float(row["motion_sample_fps"] if kind == "motion" else 1)
        server_media_expected = execution == "worker" or (execution.startswith("browser") and not direct_eligible)
        reason = "" if direct_eligible else ("rtsp_gateway_required" if media_transport == "rtsp" else "browser_direct_not_qualified")
        plan_reason = ("" if execution in {"off", "native"} else
                       ("worker_not_allowed" if kind == "person" and execution == "unsupported" and
                        not row["person_allow_server_fallback"] and row["person_execution_preference"] != "worker" else
                        "runtime_unavailable" if execution == "unsupported" else reason))
        result.append({"contractVersion": 2, "planId": uuid.uuid4().hex, "cameraId": camera_id, "profileId": profile_id, "kind": kind,
                   "execution": execution, "executionOwner": owner, "sampleFps": sample,
                   "serverMediaExpected": server_media_expected, "reason": plan_reason, "expiresAt": expires,
                   "offlineConfigExpiresAt": int(time.time()) + 7 * 24 * 3600,
                   "runtimeKind": "pwa", "mediaTransport": media_transport,
                   "credentialExposure": "none"})
    return {"contractVersion": 2, "sessionId": session_id, "expiresAt": expires, "plans": [item for item in result if item["kind"] in kinds]}


def close_analytics_session(session_id: str) -> bool:
    with ANALYTICS_SESSION_LOCK:
        closed = ANALYTICS_SESSIONS.pop(session_id, None) is not None
        ANALYTICS_SIGNAL_SEEN.pop(session_id, None)
        ANALYTICS_SIGNAL_RATE.pop(session_id, None)
        return closed


def ingest_analytics_signals(payload: dict, session_id: str) -> dict:
    with ANALYTICS_SESSION_LOCK:
        session = ANALYTICS_SESSIONS.get(session_id)
    if not session or session[0] <= int(time.time()):
        close_analytics_session(session_id)
        raise PermissionError("analytics runtime session is expired")
    values = payload.get("signals") if isinstance(payload, dict) else None
    if not isinstance(values, list) or not values or len(values) > 32:
        raise ValueError("signals must contain 1 to 32 items")
    now = int(time.time())
    minute = now // 60
    # Validate the entire batch before creating any event, so a malformed item
    # cannot leave a partially accepted batch behind.
    prepared: list[tuple[dict, dict]] = []
    seen_ids: set[str] = set()
    with connect() as database:
        policy = database.execute(
            "SELECT * FROM analytics_policies WHERE camera_id=? AND profile_id=?",
            (session[1], session[2]),
        ).fetchone()
    if not policy:
        raise PermissionError("analytics policy not found")
    for value in values:
        if not isinstance(value, dict): raise ValueError("signal must be an object")
        camera_id, profile_id = value.get("cameraId"), value.get("profileId")
        if camera_id != session[1] or profile_id != session[2] or value.get("kind") not in {"motion", "scene-change", "person"}:
            raise PermissionError("signal scope does not match runtime session")
        signal_id = value.get("signalId")
        if not isinstance(signal_id, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{8,128}", signal_id):
            raise ValueError("signalId is invalid")
        if signal_id in seen_ids:
            raise ValueError("duplicate signalId in batch")
        seen_ids.add(signal_id)
        occurred = value.get("occurredAt", int(time.time() * 1000))
        confidence = value.get("confidence", 0)
        if isinstance(occurred, bool) or not isinstance(occurred, int) or abs(int(time.time() * 1000) - occurred) > 300_000:
            raise ValueError("signal timestamp is invalid")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise ValueError("signal confidence is invalid")
        boxes = value.get("boxes", [])
        if not isinstance(boxes, list) or len(boxes) > 16:
            raise ValueError("signal boxes are invalid")
        safe_boxes = []
        for box in boxes:
            if not isinstance(box, dict): raise ValueError("signal box is invalid")
            safe = {key: box.get(key) for key in ("x", "y", "width", "height")}
            if any(isinstance(item, bool) or not isinstance(item, (int, float)) or not 0 <= item <= 1 for item in safe.values()) or \
                    safe["x"] + safe["width"] > 1 or safe["y"] + safe["height"] > 1:
                raise ValueError("signal box is out of range")
            safe_boxes.append(safe)
        enabled_column = {"motion": "motion_enabled", "scene-change": "scene_change_enabled", "person": "person_enabled"}[value["kind"]]
        if not bool(policy[enabled_column]):
            raise PermissionError("analytics policy is disabled")
        if value["kind"] != "person" and safe_boxes:
            raise ValueError("boxes are only valid for person signals")
        if value["kind"] == "person":
            model_id = value.get("modelId")
            model_version = value.get("modelVersion")
            model_sha = value.get("modelSha256", "")
            if model_id != ANALYTICS_PERSON_MODEL_ID or model_version != ANALYTICS_PERSON_MODEL_VERSION or \
                    model_sha != ANALYTICS_PERSON_MODEL_SHA256:
                raise ValueError("person model is not approved")
        prepared.append((value, {"cameraId": camera_id, "type": "object" if value["kind"] == "person" else value["kind"],
                 "source": "browser-detector" if value["kind"] == "person" else "browser-motion",
                 "occurredAt": occurred, "confidence": float(confidence), "label": "person" if value["kind"] == "person" else "",
                 "properties": {"analytics": {"schemaVersion": 2, "signalId": signal_id, "boxes": safe_boxes, "runtime": "browser"}}}))
    with ANALYTICS_SESSION_LOCK:
        current_rate_minute, current_rate = ANALYTICS_SIGNAL_RATE.get(session_id, (minute, 0))
        if current_rate_minute != minute:
            current_rate = 0
        profile_minute, profile_rate = ANALYTICS_PROFILE_RATE.get((session[1], session[2]), (minute, 0))
        if profile_minute != minute:
            profile_rate = 0
        if current_rate + len(prepared) > 60 or profile_rate + len(prepared) > 12:
            raise RuntimeError("analytics signal rate limit exceeded")
        existing = ANALYTICS_SIGNAL_SEEN.setdefault(session_id, set())
        if any(item[0]["signalId"] in existing for item in prepared):
            raise PermissionError("analytics signal replay detected")
        existing.update(item[0]["signalId"] for item in prepared)
        ANALYTICS_SIGNAL_RATE[session_id] = (minute, current_rate + len(prepared))
        ANALYTICS_PROFILE_RATE[(session[1], session[2])] = (minute, profile_rate + len(prepared))
    accepted = []
    for value, event in prepared:
        if value["kind"] == "person":
            event["properties"]["analytics"]["modelId"] = str(value.get("modelId", ""))[:64]
            event["properties"]["analytics"]["modelVersion"] = str(value.get("modelVersion", ""))[:32]
            event["properties"]["analytics"]["modelSha256"] = value["modelSha256"]
        body = json.dumps(event, separators=(",", ":")).encode()
        try:
            request = Request("http://127.0.0.1:8093/events", data=body, headers={"Content-Type": "application/json"}, method="POST")
            with urlopen(request, timeout=1) as response:
                accepted.append(json.loads(response.read(64 * 1024)))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise RuntimeError("event service unavailable") from error
    return {"accepted": len(accepted), "events": accepted}


def resolve_profile(database: sqlite3.Connection, camera_id: str, profile_id: str) -> dict:
    camera = database.execute("SELECT * FROM cameras WHERE id=?", (camera_id,)).fetchone()
    if not camera:
        raise KeyError("camera not found")
    profile = database.execute(
        "SELECT * FROM stream_profiles WHERE camera_id=? AND id=?", (camera_id, profile_id)
    ).fetchone()
    if not bool(camera["enabled"]) or (profile is not None and not bool(profile["enabled"])):
        raise PermissionError("camera profile is disabled")
    if profile is not None and profile["live_bitrate_cap_kbps"] is not None:
        tracks = track_documents(database, camera_id, profile)
        measured = sum(track["bitrateKbps"] or 0 for track in tracks)
        if measured > profile["live_bitrate_cap_kbps"]:
            raise PermissionError("camera profile exceeds the live bitrate cap")
    endpoint = profile["endpoint"] if profile else camera["address"]
    if endpoint.startswith("http://") and (profile is None or not bool(profile["allow_insecure_http"])):
        raise InsecureHttpDenied("insecure HTTP media requires explicit per-profile approval")
    credentials_ref = camera["credentials_ref"]
    if credentials_ref:
        username, password = load_credentials(credentials_ref)
        endpoint = endpoint_with_credentials(endpoint, username, password)
    return {"endpoint": endpoint, "adapter": camera["adapter"],
            "hardwareDecode": camera["hardware_decode"], "cameraId": camera_id, "profileId": profile_id,
            "transportMode": profile["transport_mode"] if profile else "auto"}


def save_camera(camera: dict, replace: bool) -> dict:
    now = int(time.time())
    with connect() as database:
        current = database.execute(
            "SELECT created_at,capabilities_json,revision FROM cameras WHERE id=?", (camera["id"],)).fetchone()
        if current and not replace:
            raise FileExistsError("camera id already exists")
        created = current["created_at"] if current else now
        revision = current["revision"] + 1 if current else 1
        if current:
            try:
                reserved = json.loads(current["capabilities_json"] or "{}")
            except json.JSONDecodeError:
                reserved = {}
            for key in ("browserDirect", "iwaDirectLab"):
                if key in reserved:
                    camera["capabilities"][key] = reserved[key]
        database.execute(
            "INSERT INTO cameras(id,name,address,adapter,credentials_ref,hardware_decode,capabilities_json,health,created_at,updated_at,kind,enabled,group_id,tags_json,revision) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,address=excluded.address,"
            "adapter=excluded.adapter,credentials_ref=excluded.credentials_ref,hardware_decode=excluded.hardware_decode,"
            "capabilities_json=excluded.capabilities_json,health=excluded.health,updated_at=excluded.updated_at,"
            "kind=excluded.kind,enabled=excluded.enabled,group_id=excluded.group_id,tags_json=excluded.tags_json,"
            "revision=excluded.revision",
            (camera["id"], camera["name"], camera["address"], camera["adapter"], camera["credentialsRef"],
             camera["hardwareDecode"], json.dumps(camera["capabilities"], separators=(",", ":"), sort_keys=True),
             "unknown", created, now, camera["kind"], int(camera["enabled"]), camera["groupId"],
             json.dumps(camera["tags"], separators=(",", ":"), ensure_ascii=False), revision),
        )
        database.execute("DELETE FROM stream_profiles WHERE camera_id=?", (camera["id"],))
        database.executemany(
            "INSERT INTO stream_profiles(id,camera_id,name,role,endpoint,video_codec,audio_codec,width,height,fps,enabled,transport_mode,live_bitrate_cap_kbps,audio_expectation,probe_state,last_probe_at,allow_insecure_http) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(p["id"], camera["id"], p["name"], p["role"], p["endpoint"], p["videoCodec"],
              p["audioCodec"], p["width"], p["height"], p["fps"], int(p["enabled"]),
              p["transportMode"], p["liveBitrateCapKbps"], p["audioExpectation"],
              p["probeState"], p["lastProbeAt"], int(p["allowInsecureHttp"])) for p in camera["profiles"]],
        )
        if camera["profiles"]:
            placeholders = ",".join("?" for _ in camera["profiles"])
            database.execute(
                f"DELETE FROM analytics_policies WHERE camera_id=? AND profile_id NOT IN ({placeholders})",
                (camera["id"], *[profile["id"] for profile in camera["profiles"]]),
            )
        else:
            database.execute("DELETE FROM analytics_policies WHERE camera_id=?", (camera["id"],))
        row = database.execute("SELECT * FROM cameras WHERE id=?", (camera["id"],)).fetchone()
        reconcile_audio_issues(database, camera["id"])
        return camera_document(database, row)


ISSUE_TEMPLATES = {
    "AUDIO_TRACK_MISSING": (
        "warning", "要求的音频轨道不可用", "该 Profile 配置为要求音频，但最近的安全媒体信息中没有音频轨道。",
        ["检查摄像机音频是否启用", "重新探测该 Profile", "不需要音频时改为自动或禁用"],
    ),
    "MEDIA_PROBE_FAILED": (
        "warning", "媒体信息探测失败", "服务未能在限定时间和输出大小内读取该 Profile 的媒体信息。",
        ["检查设备连通性和协议", "确认凭据 Secret 可用", "必要时手工选择传输方式后重试"],
    ),
    "LIVE_BITRATE_CAP_EXCEEDED": (
        "warning", "实时监看码率超过上限", "已测量轨道码率高于该 Profile 的实时监看准入上限。",
        ["选择更低码率的子码流", "调整实时监看码率上限", "检查设备编码配置"],
    ),
    "INSECURE_HTTP_MEDIA_ENABLED": (
        "warning", "已允许 HTTP 明文媒体", "该 Profile 的媒体传输未加密，只允许经 Docker Gateway/NVR 使用。",
        ["优先为摄像机配置 HTTPS", "确认摄像机位于受信任网络", "不再需要时关闭 HTTP 豁免"],
    ),
}


def issue_fingerprint(code: str, scope_kind: str, scope_id: str, component: str) -> str:
    return hashlib.sha256(f"{code}\0{scope_kind}\0{scope_id}\0{component}".encode()).hexdigest()


def upsert_issue(database: sqlite3.Connection, code: str, scope_kind: str, scope_id: str,
                 component: str, details: dict[str, object] | None = None) -> None:
    if code not in ISSUE_TEMPLATES or scope_kind not in {
            "device", "profile", "source", "media-plan", "nvr", "system"} or not ID_RE.fullmatch(scope_id):
        raise ValueError("operational issue contains an unsupported field")
    severity, summary, explanation, actions = ISSUE_TEMPLATES[code]
    safe_details = {}
    for key, value in (details or {}).items():
        if key in {"adapter", "transportMode", "codec", "httpStatus", "retryCount", "lastFrameAgeMs"} and \
                isinstance(value, (str, int, float, bool)):
            safe_details[key] = value
    fingerprint = issue_fingerprint(code, scope_kind, scope_id, component)
    issue_id = fingerprint[:32]
    now = int(time.time())
    database.execute(
        "INSERT INTO operational_issues(id,fingerprint,code,severity,state,scope_kind,scope_id,component,"
        "first_seen_at,last_seen_at,occurrences,summary,explanation,actions_json,details_json) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(fingerprint) DO UPDATE SET "
        "state='open',last_seen_at=excluded.last_seen_at,occurrences=operational_issues.occurrences+1,"
        "details_json=excluded.details_json",
        (issue_id, fingerprint, code, severity, "open", scope_kind, scope_id, component, now, now, 1,
         summary, explanation, json.dumps(actions, ensure_ascii=False, separators=(",", ":")),
         json.dumps(safe_details, ensure_ascii=False, separators=(",", ":"), sort_keys=True)),
    )
    settings_row = database.execute("SELECT settings_json FROM runtime_settings WHERE id=1").fetchone()
    retention_limit = MAX_OPERATIONAL_ISSUES
    if settings_row:
        try:
            retention_limit = int(json.loads(settings_row["settings_json"]).get(
                "issueRetentionLimit", MAX_OPERATIONAL_ISSUES))
        except (ValueError, TypeError, json.JSONDecodeError):
            retention_limit = MAX_OPERATIONAL_ISSUES
    excess = database.execute("SELECT MAX(0,COUNT(*)-?) FROM operational_issues",
                              (retention_limit,)).fetchone()[0]
    if excess:
        database.execute(
            "DELETE FROM operational_issues WHERE id IN (SELECT id FROM operational_issues "
            "ORDER BY CASE state WHEN 'resolved' THEN 0 WHEN 'acknowledged' THEN 1 ELSE 2 END,"
            "CASE severity WHEN 'info' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,last_seen_at LIMIT ?)",
            (excess,))


def resolve_issue(database: sqlite3.Connection, code: str, scope_kind: str,
                  scope_id: str, component: str) -> None:
    database.execute(
        "UPDATE operational_issues SET state='resolved',last_seen_at=? WHERE fingerprint=? AND state!='resolved'",
        (int(time.time()), issue_fingerprint(code, scope_kind, scope_id, component)),
    )


def issue_document(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"], "code": row["code"], "severity": row["severity"], "state": row["state"],
        "scopeKind": row["scope_kind"], "scopeId": row["scope_id"], "component": row["component"],
        "firstSeenAt": row["first_seen_at"], "lastSeenAt": row["last_seen_at"],
        "occurrences": row["occurrences"], "summary": row["summary"],
        "explanation": row["explanation"], "recommendedActions": json.loads(row["actions_json"]),
        "technicalDetails": json.loads(row["details_json"]),
    }


def reconcile_audio_issues(database: sqlite3.Connection, camera_id: str) -> None:
    profiles = database.execute(
        "SELECT * FROM stream_profiles WHERE camera_id=?", (camera_id,)).fetchall()
    for profile in profiles:
        scope_id = f"{camera_id}.{profile['id']}"
        if len(scope_id) > 64:
            scope_id = hashlib.sha256(scope_id.encode()).hexdigest()[:32]
        has_audio = bool(profile["audio_codec"]) or database.execute(
            "SELECT 1 FROM profile_tracks WHERE camera_id=? AND profile_id=? AND kind='audio' LIMIT 1",
            (camera_id, profile["id"]),
        ).fetchone() is not None
        if profile["audio_expectation"] == "required" and not has_audio:
            upsert_issue(database, "AUDIO_TRACK_MISSING", "profile", scope_id, "media-probe",
                         {"codec": profile["audio_codec"] or "none"})
        else:
            resolve_issue(database, "AUDIO_TRACK_MISSING", "profile", scope_id, "media-probe")
        tracks = track_documents(database, camera_id, profile)
        measured_kbps = sum(track["bitrateKbps"] or 0 for track in tracks)
        if profile["live_bitrate_cap_kbps"] is not None and measured_kbps > profile["live_bitrate_cap_kbps"]:
            upsert_issue(database, "LIVE_BITRATE_CAP_EXCEEDED", "profile", scope_id, "session-admission",
                         {"codec": profile["video_codec"] or "unknown"})
        else:
            resolve_issue(database, "LIVE_BITRATE_CAP_EXCEEDED", "profile", scope_id, "session-admission")
        if bool(profile["allow_insecure_http"]) and profile["endpoint"].startswith("http://"):
            upsert_issue(database, "INSECURE_HTTP_MEDIA_ENABLED", "profile", scope_id, "transport-policy",
                         {"transportMode": "http"})
        else:
            resolve_issue(database, "INSECURE_HTTP_MEDIA_ENABLED", "profile", scope_id, "transport-policy")


def expected_revision(header: str | None) -> int:
    if not header or not re.fullmatch(r'"[1-9][0-9]*"', header.strip()):
        raise ValueError("If-Match must contain one quoted positive revision")
    return int(header.strip()[1:-1])


def validate_catalog_patch(payload: dict, adapter: str) -> tuple[dict, list[dict]]:
    allowed = {"name", "kind", "enabled", "groupId", "tags", "hardwareDecode", "profiles"}
    if not payload or set(payload) - allowed:
        raise ValueError("source catalog patch contains an unsupported field")
    camera_updates: dict[str, object] = {}
    if "name" in payload:
        if not isinstance(payload["name"], str) or not 1 <= len(payload["name"].strip()) <= 128:
            raise ValueError("name must contain 1 to 128 characters")
        camera_updates["name"] = payload["name"].strip()
    if "kind" in payload:
        if payload["kind"] not in {"camera", "network-stream"}:
            raise ValueError("kind must be camera or network-stream")
        camera_updates["kind"] = payload["kind"]
    if "enabled" in payload:
        if not isinstance(payload["enabled"], bool):
            raise ValueError("enabled must be boolean")
        camera_updates["enabled"] = int(payload["enabled"])
    if "groupId" in payload:
        value = payload["groupId"]
        if not isinstance(value, str) or len(value) > 64 or any(ord(c) < 32 for c in value):
            raise ValueError("groupId must contain at most 64 printable characters")
        camera_updates["group_id"] = value.strip()
    if "tags" in payload:
        camera_updates["tags_json"] = json.dumps(
            validate_tags(payload["tags"]), separators=(",", ":"), ensure_ascii=False)
    if "hardwareDecode" in payload:
        if payload["hardwareDecode"] not in {"auto", "on", "off"}:
            raise ValueError("hardwareDecode must be auto, on, or off")
        camera_updates["hardware_decode"] = payload["hardwareDecode"]
    profile_updates = payload.get("profiles", [])
    if not isinstance(profile_updates, list) or len(profile_updates) > 16:
        raise ValueError("profiles patch must contain at most 16 items")
    normalized_profiles = []
    for value in profile_updates:
        if not isinstance(value, dict) or set(value) - {
                "id", "enabled", "transportMode", "liveBitrateCapKbps", "audioExpectation", "allowInsecureHttp"}:
            raise ValueError("profile patch contains an unsupported field")
        profile_id = value.get("id")
        if not isinstance(profile_id, str) or not ID_RE.fullmatch(profile_id):
            raise ValueError("profile id is invalid")
        update: dict[str, object] = {"id": profile_id}
        if "enabled" in value:
            if not isinstance(value["enabled"], bool):
                raise ValueError("profile enabled must be boolean")
            update["enabled"] = int(value["enabled"])
        if "transportMode" in value:
            if value["transportMode"] not in transport_modes_for(adapter):
                raise ValueError("profile transportMode is not valid for this adapter")
            update["transport_mode"] = value["transportMode"]
        if "liveBitrateCapKbps" in value:
            cap = value["liveBitrateCapKbps"]
            if cap is not None and (isinstance(cap, bool) or not isinstance(cap, int) or
                                    not 32 <= cap <= 1_000_000):
                raise ValueError("liveBitrateCapKbps must be null or between 32 and 1000000")
            update["live_bitrate_cap_kbps"] = cap
        if "audioExpectation" in value:
            if value["audioExpectation"] not in {"auto", "required", "disabled"}:
                raise ValueError("audioExpectation must be auto, required, or disabled")
            update["audio_expectation"] = value["audioExpectation"]
        if "allowInsecureHttp" in value:
            if not isinstance(value["allowInsecureHttp"], bool):
                raise ValueError("allowInsecureHttp must be boolean")
            update["allow_insecure_http"] = int(value["allowInsecureHttp"])
        normalized_profiles.append(update)
    return camera_updates, normalized_profiles


def patch_source_catalog(camera_id: str, payload: dict, revision: int) -> dict:
    with connect() as database:
        row = database.execute("SELECT * FROM cameras WHERE id=?", (camera_id,)).fetchone()
        if not row:
            raise KeyError("camera not found")
        if row["revision"] != revision:
            raise RevisionConflict(str(row["revision"]))
        camera_updates, profile_updates = validate_catalog_patch(payload, row["adapter"])
        for profile in profile_updates:
            stored_profile = database.execute(
                "SELECT endpoint FROM stream_profiles WHERE camera_id=? AND id=?", (camera_id, profile["id"])).fetchone()
            if not stored_profile:
                raise KeyError("camera profile not found")
            if profile.get("allow_insecure_http") == 1 and not stored_profile["endpoint"].startswith("http://"):
                raise ValueError("allowInsecureHttp is only valid for an HTTP media endpoint")
        now = int(time.time())
        if camera_updates:
            assignments = ",".join(f"{field}=?" for field in camera_updates)
            database.execute(f"UPDATE cameras SET {assignments},updated_at=?,revision=revision+1 WHERE id=?",
                             (*camera_updates.values(), now, camera_id))
        else:
            database.execute("UPDATE cameras SET updated_at=?,revision=revision+1 WHERE id=?", (now, camera_id))
        for profile in profile_updates:
            values = {key: value for key, value in profile.items() if key != "id"}
            if values:
                assignments = ",".join(f"{field}=?" for field in values)
                database.execute(f"UPDATE stream_profiles SET {assignments} WHERE camera_id=? AND id=?",
                                 (*values.values(), camera_id, profile["id"]))
        reconcile_audio_issues(database, camera_id)
        updated = database.execute("SELECT * FROM cameras WHERE id=?", (camera_id,)).fetchone()
        return source_catalog_document(database, updated)


def batch_source_catalog(payload: dict) -> list[dict]:
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list) or not 1 <= len(items) <= 256:
        raise ValueError("items must contain 1 to 256 patches")
    normalized = []
    with connect() as database:
        for item in items:
            if not isinstance(item, dict) or set(item) - {"cameraId", "revision", "enabled", "groupId", "tags"}:
                raise ValueError("batch item contains an unsupported field")
            camera_id, revision = item.get("cameraId"), item.get("revision")
            if not isinstance(camera_id, str) or not ID_RE.fullmatch(camera_id) or \
                    isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
                raise ValueError("batch cameraId or revision is invalid")
            row = database.execute("SELECT * FROM cameras WHERE id=?", (camera_id,)).fetchone()
            if not row:
                raise KeyError("camera not found")
            if row["revision"] != revision:
                raise RevisionConflict(f"{camera_id}:{row['revision']}")
            changes, profiles = validate_catalog_patch(
                {key: value for key, value in item.items() if key not in {"cameraId", "revision"}}, row["adapter"])
            if profiles:
                raise ValueError("batch profile changes are not supported")
            normalized.append((camera_id, changes))
        now = int(time.time())
        for camera_id, changes in normalized:
            assignments = ",".join(f"{field}=?" for field in changes)
            database.execute(f"UPDATE cameras SET {assignments},updated_at=?,revision=revision+1 WHERE id=?",
                             (*changes.values(), now, camera_id))
        rows = []
        for camera_id, _ in normalized:
            row = database.execute("SELECT * FROM cameras WHERE id=?", (camera_id,)).fetchone()
            rows.append(source_catalog_document(database, row))
        return rows


def parse_rate(value: object) -> float:
    if not isinstance(value, str) or not value:
        return 0
    try:
        numerator, denominator = value.split("/", 1)
        return 0 if float(denominator) == 0 else float(numerator) / float(denominator)
    except (ValueError, ZeroDivisionError):
        return 0


def probe_source_profile(camera_id: str, profile_id: str) -> dict:
    with PROBE_LOCKS_GUARD:
        lock = PROBE_LOCKS.setdefault(camera_id, threading.Lock())
    if not lock.acquire(blocking=False):
        raise RuntimeError("camera probe is already running")
    if not PROBE_SEMAPHORE.acquire(blocking=False):
        lock.release()
        raise RuntimeError("global camera probe limit reached")
    try:
        with connect() as database:
            camera = database.execute("SELECT * FROM cameras WHERE id=?", (camera_id,)).fetchone()
            profile = database.execute(
                "SELECT * FROM stream_profiles WHERE camera_id=? AND id=?", (camera_id, profile_id)).fetchone()
            if not camera or not profile:
                raise KeyError("camera or profile not found")
            if camera["credentials_ref"]:
                database.execute(
                    "UPDATE stream_profiles SET probe_state='cached',last_probe_at=? WHERE camera_id=? AND id=?",
                    (int(time.time()), camera_id, profile_id))
                reconcile_audio_issues(database, camera_id)
                refreshed = database.execute(
                    "SELECT * FROM stream_profiles WHERE camera_id=? AND id=?", (camera_id, profile_id)).fetchone()
                return profile_document(database, camera_id, refreshed, include_endpoint=False)
            endpoint, transport_mode = profile["endpoint"], profile["transport_mode"]
            if endpoint.startswith("http://") and not bool(profile["allow_insecure_http"]):
                raise InsecureHttpDenied("insecure HTTP media requires explicit per-profile approval")
            settings = database.execute("SELECT settings_json FROM runtime_settings WHERE id=1").fetchone()
            probe_timeout = int(json.loads(settings["settings_json"])["probeTimeoutSeconds"])
        command = ["ffprobe", "-v", "error", "-show_entries",
                   "stream=index,codec_type,codec_name,bit_rate,width,height,avg_frame_rate,sample_rate,channels",
                   "-of", "json"]
        if endpoint.startswith(("rtsp://", "rtsps://")) and transport_mode in {"rtsp-tcp", "rtsp-udp", "rtsp-udp-multicast"}:
            command += ["-rtsp_transport", "tcp" if transport_mode == "rtsp-tcp" else "udp"]
        command.append(endpoint)
        try:
            result = subprocess.run(command, capture_output=True, timeout=probe_timeout,
                                    check=False, env={**os.environ, "LC_ALL": "C"})
            if result.returncode or len(result.stdout) > PROBE_OUTPUT_LIMIT or len(result.stderr) > PROBE_OUTPUT_LIMIT:
                raise ValueError("probe_failed")
            parsed = json.loads(result.stdout)
            streams = parsed.get("streams", [])
            if not isinstance(streams, list) or not 1 <= len(streams) <= MAX_TRACKS_PER_PROFILE:
                raise ValueError("probe_tracks_invalid")
            tracks = []
            for item in streams:
                kind = item.get("codec_type")
                if kind not in {"video", "audio", "data"}:
                    continue
                bitrate = int(item["bit_rate"]) // 1000 if str(item.get("bit_rate", "")).isdigit() else None
                tracks.append({
                    "index": int(item.get("index", len(tracks))), "kind": kind,
                    "codec": str(item.get("codec_name", "unknown"))[:32].lower(), "bitrateKbps": bitrate,
                    "width": int(item.get("width", 0) or 0), "height": int(item.get("height", 0) or 0),
                    "fps": parse_rate(item.get("avg_frame_rate", "")),
                    "sampleRate": int(item.get("sample_rate", 0) or 0),
                    "channels": int(item.get("channels", 0) or 0), "source": "probe",
                })
            if not tracks:
                raise ValueError("probe_tracks_invalid")
        except (OSError, subprocess.TimeoutExpired, ValueError, TypeError, json.JSONDecodeError):
            with connect() as database:
                database.execute(
                    "UPDATE stream_profiles SET probe_state='failed',last_probe_at=? WHERE camera_id=? AND id=?",
                    (int(time.time()), camera_id, profile_id))
                upsert_issue(database, "MEDIA_PROBE_FAILED", "profile",
                             f"{camera_id}.{profile_id}"[:64], "media-probe", {"transportMode": transport_mode})
            raise ValueError("media probe failed")
        with connect() as database:
            database.execute("DELETE FROM profile_tracks WHERE camera_id=? AND profile_id=?", (camera_id, profile_id))
            database.executemany(
                "INSERT INTO profile_tracks(camera_id,profile_id,track_index,kind,codec,bitrate_kbps,width,height,fps,sample_rate,channels,source) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                [(camera_id, profile_id, item["index"], item["kind"], item["codec"], item["bitrateKbps"],
                  item["width"], item["height"], item["fps"], item["sampleRate"], item["channels"], "probe")
                 for item in tracks],
            )
            video = next((item for item in tracks if item["kind"] == "video"), None)
            audio = next((item for item in tracks if item["kind"] == "audio"), None)
            database.execute(
                "UPDATE stream_profiles SET video_codec=?,audio_codec=?,width=?,height=?,fps=?,probe_state='ready',last_probe_at=? "
                "WHERE camera_id=? AND id=?",
                (video["codec"] if video else "", audio["codec"] if audio else "",
                 video["width"] if video else 0, video["height"] if video else 0,
                 video["fps"] if video else 0, int(time.time()), camera_id, profile_id),
            )
            resolve_issue(database, "MEDIA_PROBE_FAILED", "profile", f"{camera_id}.{profile_id}"[:64], "media-probe")
            refreshed = database.execute(
                "SELECT * FROM stream_profiles WHERE camera_id=? AND id=?", (camera_id, profile_id)).fetchone()
            measured = sum(track["bitrateKbps"] or 0 for track in tracks)
            if refreshed["live_bitrate_cap_kbps"] is not None and measured > refreshed["live_bitrate_cap_kbps"]:
                upsert_issue(database, "LIVE_BITRATE_CAP_EXCEEDED", "profile",
                             f"{camera_id}.{profile_id}"[:64], "session-admission")
            else:
                resolve_issue(database, "LIVE_BITRATE_CAP_EXCEEDED", "profile",
                              f"{camera_id}.{profile_id}"[:64], "session-admission")
            reconcile_audio_issues(database, camera_id)
            return profile_document(database, camera_id, refreshed, include_endpoint=False)
    finally:
        PROBE_SEMAPHORE.release()
        lock.release()


def probe_source_camera(camera_id: str) -> list[dict]:
    if not ID_RE.fullmatch(camera_id):
        raise ValueError("camera id is invalid")
    with connect() as database:
        exists = database.execute("SELECT 1 FROM cameras WHERE id=?", (camera_id,)).fetchone()
        if not exists:
            raise KeyError("camera not found")
        profile_ids = [row["id"] for row in database.execute(
            "SELECT id FROM stream_profiles WHERE camera_id=? ORDER BY role,id", (camera_id,)).fetchall()]
    if not profile_ids:
        raise ValueError("camera has no profiles to probe")
    return [probe_source_profile(camera_id, profile_id) for profile_id in profile_ids]


def validate_runtime_settings(payload: dict, current: dict) -> dict:
    allowed = {"defaultTransportMode", "probeTimeoutSeconds", "sourceRecoveryEnabled", "issueRetentionLimit"}
    if not payload or set(payload) - allowed:
        raise ValueError("settings patch contains an unsupported field")
    result = dict(current)
    if "defaultTransportMode" in payload:
        if payload["defaultTransportMode"] not in {"auto", "rtsp-tcp", "rtsp-udp"}:
            raise ValueError("defaultTransportMode is invalid")
        result["defaultTransportMode"] = payload["defaultTransportMode"]
    if "probeTimeoutSeconds" in payload:
        value = payload["probeTimeoutSeconds"]
        if isinstance(value, bool) or not isinstance(value, int) or not 2 <= value <= 30:
            raise ValueError("probeTimeoutSeconds must be between 2 and 30")
        result["probeTimeoutSeconds"] = value
    if "sourceRecoveryEnabled" in payload:
        if not isinstance(payload["sourceRecoveryEnabled"], bool):
            raise ValueError("sourceRecoveryEnabled must be boolean")
        result["sourceRecoveryEnabled"] = payload["sourceRecoveryEnabled"]
    if "issueRetentionLimit" in payload:
        value = payload["issueRetentionLimit"]
        if isinstance(value, bool) or not isinstance(value, int) or not 128 <= value <= MAX_OPERATIONAL_ISSUES:
            raise ValueError("issueRetentionLimit must be between 128 and 4096")
        result["issueRetentionLimit"] = value
    return result


def source_catalog(query: str) -> dict:
    values = parse_qs(query, keep_blank_values=True)
    try:
        page = int(values.get("page", ["1"])[0])
        limit = int(values.get("limit", ["50"])[0])
    except ValueError as error:
        raise ValueError("page and limit must be integers") from error
    if page < 1 or not 1 <= limit <= MAX_CATALOG_PAGE:
        raise ValueError("source catalog pagination is out of range")
    clauses, arguments = [], []
    filters = {
        "group": ("group_id", 64), "adapter": ("adapter", 32), "health": ("health", 32),
    }
    for key, (column, maximum) in filters.items():
        value = values.get(key, [""])[0].strip()
        if value:
            if len(value) > maximum or any(ord(c) < 32 for c in value):
                raise ValueError(f"{key} filter is invalid")
            clauses.append(f"{column}=?"); arguments.append(value)
    enabled = values.get("enabled", [""])[0]
    if enabled:
        if enabled not in {"true", "false"}:
            raise ValueError("enabled filter must be true or false")
        clauses.append("enabled=?"); arguments.append(int(enabled == "true"))
    tag = values.get("tag", [""])[0].strip()
    if tag:
        if len(tag) > 32:
            raise ValueError("tag filter is invalid")
        clauses.append("EXISTS(SELECT 1 FROM json_each(cameras.tags_json) WHERE value=?)")
        arguments.append(tag)
    search = values.get("q", [""])[0].strip()
    if search:
        if len(search) > 128 or any(ord(c) < 32 for c in search):
            raise ValueError("search query is invalid")
        clauses.append("(name LIKE ? ESCAPE '\\' OR group_id LIKE ? ESCAPE '\\' OR "
                       "EXISTS(SELECT 1 FROM json_each(cameras.tags_json) WHERE value LIKE ? ESCAPE '\\'))")
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        arguments += [f"%{escaped}%", f"%{escaped}%", f"%{escaped}%"]
    sort = values.get("sort", ["name"])[0]
    direction = values.get("direction", ["asc"])[0]
    columns = {"name": "name", "status": "health", "updated": "updated_at", "group": "group_id"}
    if sort not in columns or direction not in {"asc", "desc"}:
        raise ValueError("source catalog sort is invalid")
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with connect() as database:
        total = database.execute(f"SELECT COUNT(*) FROM cameras{where}", arguments).fetchone()[0]
        rows = database.execute(
            f"SELECT * FROM cameras{where} ORDER BY {columns[sort]} {direction.upper()},id "
            "LIMIT ? OFFSET ?", (*arguments, limit, (page - 1) * limit)).fetchall()
        return {"schemaVersion": 2, "page": page, "limit": limit, "total": total,
                "items": [source_catalog_document(database, row) for row in rows]}


def runtime_settings() -> dict:
    with connect() as database:
        row = database.execute("SELECT * FROM runtime_settings WHERE id=1").fetchone()
        return {"schemaVersion": 1, "revision": row["revision"], "values": json.loads(row["settings_json"]),
                "deployment": {"tls": "read-only", "ports": "read-only", "secrets": "read-only",
                               "gpuDevice": "read-only"}}


def patch_runtime_settings(payload: dict, revision: int) -> dict:
    with connect() as database:
        row = database.execute("SELECT * FROM runtime_settings WHERE id=1").fetchone()
        if row["revision"] != revision:
            raise RevisionConflict(str(row["revision"]))
        values = validate_runtime_settings(payload, json.loads(row["settings_json"]))
        database.execute("UPDATE runtime_settings SET revision=revision+1,settings_json=?,updated_at=? WHERE id=1",
                         (json.dumps(values, separators=(",", ":"), sort_keys=True), int(time.time())))
        updated = database.execute("SELECT * FROM runtime_settings WHERE id=1").fetchone()
        return {"schemaVersion": 1, "revision": updated["revision"], "values": values,
                "deployment": {"tls": "read-only", "ports": "read-only", "secrets": "read-only",
                               "gpuDevice": "read-only"}}


def configured_pwa_origin() -> str:
    raw = os.environ.get("WEBOBS_PWA_PUBLIC_ORIGIN", "").strip()
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as error:
        raise BrowserDirectProbeError("pwa_origin_invalid") from error
    if parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username or parsed.password or \
            parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise BrowserDirectProbeError("pwa_origin_invalid")
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    return f"https://{host}" + (f":{port}" if port not in {None, 443} else "")


def browser_probe_request(endpoint: str, origin: str, method: str = "GET",
                          headers: dict[str, str] | None = None, opener=None):
    try:
        parsed = urlsplit(endpoint)
        addresses = {entry[4][0] for entry in socket.getaddrinfo(
            parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)}
    except (ValueError, OSError, TypeError) as error:
        raise BrowserDirectProbeError("endpoint_resolution_failed") from error
    allow_test_loopback = os.environ.get("WEBOBS_CAMERA_ALLOW_TEST_ENDPOINTS") == "true" and \
        os.environ.get("WEBOBS_BROWSER_PROBE_ALLOW_LOOPBACK") == "true"
    if not addresses or len(addresses) > 8:
        raise BrowserDirectProbeError("endpoint_resolution_unbounded")
    for address in addresses:
        value = ipaddress.ip_address(address.split("%", 1)[0])
        if value.is_unspecified or value.is_multicast or value.is_link_local or \
                (value.is_loopback and not allow_test_loopback):
            raise BrowserDirectProbeError("endpoint_address_forbidden")
    request_headers = {"Origin": origin, "User-Agent": "WebOBS-Browser-Qualification/1"}
    request_headers.update(headers or {})
    opener = opener or build_opener(SameOriginRedirect(), HTTPSHandler(context=TLS_CONTEXT))
    try:
        response = opener.open(Request(endpoint, method=method, headers=request_headers),
                               timeout=ONVIF_TIMEOUT_SECONDS)
    except (HTTPError, URLError, TimeoutError, ssl.SSLError, OSError, OnvifError) as error:
        raise BrowserDirectProbeError("endpoint_unreachable_or_tls_invalid") from error
    if response.headers.get("Access-Control-Allow-Origin", "").strip() != origin:
        response.close()
        raise BrowserDirectProbeError("cors_origin_rejected")
    return response


def bounded_http_body(response, limit: int = 128 * 1024) -> bytes:
    try:
        body = response.read(limit + 1)
    except (TimeoutError, OSError) as error:
        raise BrowserDirectProbeError("media_probe_read_failed") from error
    finally:
        response.close()
    if len(body) > limit:
        raise BrowserDirectProbeError("media_probe_response_too_large")
    return body


def bounded_http_prefix(response, limit: int) -> bytes:
    try:
        return response.read(limit)
    except (TimeoutError, OSError) as error:
        raise BrowserDirectProbeError("media_probe_read_failed") from error
    finally:
        response.close()


def qualify_hls(endpoint: str, origin: str) -> None:
    current = endpoint
    cookies = CookieJar()
    opener = build_opener(
        SameOriginRedirect(), HTTPCookieProcessor(cookies), HTTPSHandler(context=TLS_CONTEXT))
    for depth in range(2):
        response = browser_probe_request(
            current, origin, headers={"Accept": "application/vnd.apple.mpegurl"}, opener=opener)
        if len(cookies) > 16 or any(len(cookie.name) + len(cookie.value) > 4096 for cookie in cookies):
            response.close()
            raise BrowserDirectProbeError("hls_cookie_state_unbounded")
        content_type = response.headers.get_content_type().lower()
        if content_type not in {"application/vnd.apple.mpegurl", "application/x-mpegurl", "audio/mpegurl"}:
            response.close()
            raise BrowserDirectProbeError("hls_content_type_invalid")
        try:
            playlist = bounded_http_body(response).decode("utf-8", "strict")
        except UnicodeDecodeError as error:
            raise BrowserDirectProbeError("hls_manifest_invalid") from error
        if not playlist.startswith("#EXTM3U"):
            raise BrowserDirectProbeError("hls_manifest_invalid")
        resources = [line.strip() for line in playlist.splitlines()
                     if line.strip() and not line.lstrip().startswith("#")]
        if not resources or len(resources) > 4096:
            raise BrowserDirectProbeError("hls_manifest_unbounded")
        try:
            child = urlsplit(urljoin(current, resources[0]))
            parent = urlsplit(endpoint)
            child_port, parent_port = child.port, parent.port
        except ValueError as error:
            raise BrowserDirectProbeError("hls_child_origin_rejected") from error
        if child.scheme.lower() != "https" or child.hostname != parent.hostname or child_port != parent_port or \
                child.username or child.password or child.fragment:
            raise BrowserDirectProbeError("hls_child_origin_rejected")
        child_url = child.geturl()
        if child.path.lower().endswith(".m3u8") and depth == 0:
            current = child_url
            continue
        segment = browser_probe_request(
            child_url, origin, headers={"Range": "bytes=0-1023"}, opener=opener)
        if not bounded_http_prefix(segment, 1024):
            raise BrowserDirectProbeError("hls_segment_empty")
        return
    raise BrowserDirectProbeError("hls_media_playlist_missing")


def browser_direct_probe(camera_id: str, profile_id: str) -> dict:
    origin = configured_pwa_origin()
    with connect() as database:
        camera = database.execute("SELECT * FROM cameras WHERE id=?", (camera_id,)).fetchone()
        profile = database.execute(
            "SELECT * FROM stream_profiles WHERE camera_id=? AND id=?", (camera_id, profile_id)).fetchone()
        if not camera or not profile:
            raise KeyError("camera or profile not found")
        adapter = camera["adapter"]
        endpoint = profile["endpoint"]
        reason = ""
        try:
            parsed = urlsplit(endpoint)
            if adapter not in {"whep", "hls", "mjpeg"}:
                raise BrowserDirectProbeError("protocol_not_supported")
            if parsed.scheme.lower() != "https" or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise BrowserDirectProbeError("browser_https_endpoint_required")
            if camera["credentials_ref"]:
                raise BrowserDirectProbeError("long_term_credentials_forbidden")
            if adapter == "whep":
                response = browser_probe_request(endpoint, origin, "OPTIONS", {
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "content-type",
                })
                allowed = {item.strip().upper() for item in response.headers.get(
                    "Access-Control-Allow-Methods", "").split(",")}
                response.close()
                if "POST" not in allowed:
                    raise BrowserDirectProbeError("whep_post_cors_rejected")
            elif adapter == "hls":
                qualify_hls(endpoint, origin)
            else:
                response = browser_probe_request(
                    endpoint, origin, headers={"Accept": "multipart/x-mixed-replace"})
                if response.headers.get_content_type().lower() != "multipart/x-mixed-replace":
                    response.close()
                    raise BrowserDirectProbeError("mjpeg_content_type_invalid")
                response.close()
        except BrowserDirectProbeError as error:
            reason = str(error)
        passed = not reason
        try:
            capabilities = json.loads(camera["capabilities_json"] or "{}")
        except json.JSONDecodeError:
            capabilities = {}
        direct = capabilities.setdefault("browserDirect", {})
        proofs = direct.setdefault("profiles", {})
        proofs[profile_id] = {
            "tlsVerified": passed, "corsVerified": passed,
            "pwaOriginSha256": hashlib.sha256(origin.encode()).hexdigest(),
            "checkedAt": int(time.time()), "reason": reason,
        }
        database.execute("UPDATE cameras SET capabilities_json=?,updated_at=? WHERE id=?", (
            json.dumps(capabilities, separators=(",", ":"), sort_keys=True), int(time.time()), camera_id))
    return {"cameraId": camera_id, "profileId": profile_id, "eligible": passed,
            "reason": reason, "checkedAt": proofs[profile_id]["checkedAt"]}


def xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].split(":", 1)[-1]


def xml_text(element: ET.Element | None, names: tuple[str, ...]) -> str:
    if element is None:
        return ""
    wanted = set(names)
    for child in element.iter():
        if xml_local_name(child.tag) in wanted and child.text:
            return child.text.strip()
    return ""


def parse_onvif_xml(data: bytes) -> ET.Element:
    if len(data) > MAX_ONVIF_XML:
        raise OnvifError("ONVIF response exceeds the size limit")
    lowered = data.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise OnvifError("ONVIF response contains forbidden XML declarations")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        raise OnvifError("ONVIF response is malformed XML") from error
    if any(xml_local_name(node.tag) == "Fault" for node in root.iter()):
        raise OnvifError("ONVIF device returned a SOAP fault")
    return root


def ws_security_header(username: str, password: str, offset_seconds: float = 0) -> str:
    if not username:
        return ""
    nonce = secrets.token_bytes(16)
    created = datetime.fromtimestamp(time.time() + offset_seconds, timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")
    digest = base64.b64encode(hashlib.sha1(nonce + created.encode() + password.encode()).digest()).decode()
    encoded_nonce = base64.b64encode(nonce).decode()
    return (
        '<s:Header><wsse:Security s:mustUnderstand="true" '
        'xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd" '
        'xmlns:wsu="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">'
        '<wsse:UsernameToken><wsse:Username>' + escape(username) + '</wsse:Username>'
        '<wsse:Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest">' + digest + '</wsse:Password>'
        '<wsse:Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">' + encoded_nonce + '</wsse:Nonce>'
        '<wsu:Created>' + created + '</wsu:Created></wsse:UsernameToken></wsse:Security></s:Header>'
    )


def onvif_soap(endpoint: str, action: str, body: str, username: str, password: str) -> ET.Element:
    endpoint = safe_endpoint(endpoint, "onvif")
    with ONVIF_CLOCK_LOCK:
        clock_offset = ONVIF_CLOCK_OFFSETS.get(urlsplit(endpoint).netloc.lower(), 0.0)
    envelope = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">' +
        ws_security_header(username, password, clock_offset) + '<s:Body>' + body + '</s:Body></s:Envelope>'
    ).encode()
    password_manager = HTTPPasswordMgrWithDefaultRealm()
    if username:
        password_manager.add_password(None, endpoint, username, password)
    opener = build_opener(
        NoRedirect(),
        HTTPDigestAuthHandler(password_manager),
        HTTPBasicAuthHandler(password_manager),
        HTTPSHandler(context=TLS_CONTEXT),
    )
    request = Request(endpoint, data=envelope, method="POST", headers={
        "Content-Type": f'application/soap+xml; charset=utf-8; action="{action}"',
        "SOAPAction": f'"{action}"',
        "User-Agent": "webobs-onvif/1",
        "Accept": "application/soap+xml, application/xml",
    })
    try:
        with opener.open(request, timeout=ONVIF_TIMEOUT_SECONDS) as response:
            data = response.read(MAX_ONVIF_XML + 1)
    except HTTPError as error:
        status = error.code
        try:
            error.close()
        except (KeyError, ResourceWarning):
            pass
        if status in (401, 403):
            raise PermissionError("ONVIF authentication failed") from error
        raise OnvifError(f"ONVIF request failed with HTTP {status}") from error
    except (URLError, TimeoutError, OSError) as error:
        raise OnvifError("ONVIF endpoint is unavailable") from error
    return parse_onvif_xml(data)


def onvif_device_endpoint(address: str) -> str:
    normalized = safe_endpoint(address, "onvif")
    parsed = urlsplit(normalized)
    if parsed.path in ("", "/"):
        return urlunsplit((parsed.scheme, parsed.netloc, "/onvif/device_service", "", ""))
    return normalized


def onvif_device_time_offset(endpoint: str) -> float:
    """Read device UTC without credentials and return a bounded WS-Security skew."""
    try:
        root = onvif_soap(
            endpoint, "http://www.onvif.org/ver10/device/wsdl/GetSystemDateAndTime",
            '<tds:GetSystemDateAndTime xmlns:tds="http://www.onvif.org/ver10/device/wsdl"/>', "", "",
        )
        values: dict[str, int] = {}
        for node in root.iter():
            name = xml_local_name(node.tag)
            if name in {"Year", "Month", "Day", "Hour", "Minute", "Second"} and node.text:
                values[name] = int(node.text)
        device_time = datetime(values["Year"], values["Month"], values["Day"], values["Hour"],
                               values["Minute"], values["Second"], tzinfo=timezone.utc).timestamp()
        offset = device_time - time.time()
        if abs(offset) > 86400:
            raise OnvifError("ONVIF device clock skew exceeds 24 hours")
        return offset
    except (KeyError, ValueError, TypeError, PermissionError, OnvifError):
        return 0.0


def onvif_service_endpoints(root: ET.Element) -> dict[str, str]:
    services: dict[str, str] = {}
    for node in root.iter():
        if xml_local_name(node.tag) != "Service":
            continue
        namespace = xml_text(node, ("Namespace",)).lower()
        address = xml_text(node, ("XAddr",))
        if not address:
            continue
        if "/ver20/media/" in namespace:
            services["media2"] = onvif_returned_endpoint(address, "onvif")
        elif "/ver10/media/" in namespace:
            services["media1"] = onvif_returned_endpoint(address, "onvif")
        elif "/ptz/" in namespace:
            services["ptz"] = onvif_returned_endpoint(address, "onvif")
        elif "/events/" in namespace:
            services["events"] = onvif_returned_endpoint(address, "onvif")
        elif "/imaging/" in namespace:
            services["imaging"] = onvif_returned_endpoint(address, "onvif")
    return services


def onvif_capability_endpoints(root: ET.Element) -> dict[str, str]:
    services: dict[str, str] = {}
    mapping = {"Media": "media1", "PTZ": "ptz", "Events": "events", "Imaging": "imaging"}
    for node in root.iter():
        kind = mapping.get(xml_local_name(node.tag))
        if kind:
            address = xml_text(node, ("XAddr",))
            if address:
                services[kind] = onvif_returned_endpoint(address, "onvif")
    return services


def onvif_discover_services(endpoint: str, username: str, password: str) -> dict[str, str]:
    services: dict[str, str] = {}
    try:
        root = onvif_soap(
            endpoint, "http://www.onvif.org/ver10/device/wsdl/GetServices",
            '<tds:GetServices xmlns:tds="http://www.onvif.org/ver10/device/wsdl"><tds:IncludeCapability>true</tds:IncludeCapability></tds:GetServices>',
            username, password,
        )
        services.update(onvif_service_endpoints(root))
    except OnvifError:
        pass
    if "media1" not in services and "media2" not in services:
        root = onvif_soap(
            endpoint, "http://www.onvif.org/ver10/device/wsdl/GetCapabilities",
            '<tds:GetCapabilities xmlns:tds="http://www.onvif.org/ver10/device/wsdl"><tds:Category>All</tds:Category></tds:GetCapabilities>',
            username, password,
        )
        services.update(onvif_capability_endpoints(root))
    if "media1" not in services and "media2" not in services:
        raise OnvifError("ONVIF device exposes no Media service")
    return services


def onvif_configuration(profile: ET.Element, video: bool) -> ET.Element | None:
    candidates = ({"VideoEncoderConfiguration", "VideoEncoder"} if video else
                  {"AudioEncoderConfiguration", "AudioEncoder"})
    return next((node for node in profile.iter() if xml_local_name(node.tag) in candidates), None)


def onvif_number(element: ET.Element | None, names: tuple[str, ...], integer: bool = True):
    value = xml_text(element, names)
    try:
        return int(float(value)) if integer and value else float(value) if value else 0
    except ValueError:
        return 0


def onvif_returned_endpoint(endpoint: str, adapter: str) -> str:
    try:
        return safe_endpoint(endpoint, adapter)
    except ValueError as error:
        raise OnvifError("ONVIF device returned an invalid endpoint") from error


def onvif_uri(root: ET.Element, adapter: str) -> str:
    uri = xml_text(root, ("Uri", "URI"))
    return onvif_returned_endpoint(uri, adapter) if uri else ""


def onvif_media_profiles(endpoint: str, profile_kind: str, username: str,
                          password: str) -> tuple[list[dict], str, dict[str, str]]:
    media2 = profile_kind == "T"
    namespace = "http://www.onvif.org/ver20/media/wsdl" if media2 else "http://www.onvif.org/ver10/media/wsdl"
    prefix = "tr2" if media2 else "trt"
    root = onvif_soap(
        endpoint, f"{namespace}/GetProfiles",
        f'<{prefix}:GetProfiles xmlns:{prefix}="{namespace}"/>', username, password,
    )
    raw_profiles = [node for node in root.iter()
                    if xml_local_name(node.tag) in ("Profiles", "Profile") and node.get("token")]
    discovered: list[tuple[str, dict]] = []
    used_ids: set[str] = set()
    for index, node in enumerate(raw_profiles[:16]):
        token = str(node.get("token", ""))[:256]
        if not token:
            continue
        identifier = re.sub(r"[^a-zA-Z0-9._-]", "-", token).strip("-")[:64] or f"profile-{index + 1}"
        while identifier in used_ids:
            identifier = (identifier[:56] + f"-{index + 1}")[:64]
        used_ids.add(identifier)
        video = onvif_configuration(node, True)
        audio = onvif_configuration(node, False)
        resolution = next((child for child in video.iter()
                           if xml_local_name(child.tag) == "Resolution"), None) if video is not None else None
        discovered.append((token, {
            "id": identifier,
            "name": (xml_text(node, ("Name",)) or identifier)[:128],
            "role": "auxiliary",
            "endpoint": "",
            "videoCodec": (xml_text(video, ("Encoding",)) or "unknown").lower(),
            "audioCodec": xml_text(audio, ("Encoding",)).lower(),
            "width": onvif_number(resolution, ("Width",)),
            "height": onvif_number(resolution, ("Height",)),
            "fps": onvif_number(video, ("FrameRateLimit", "Framerate"), False),
        }))
    if not discovered:
        raise OnvifError("ONVIF Media service returned no profiles")
    for token, profile in discovered:
        escaped_token = escape(token)
        if media2:
            body = (f'<tr2:GetStreamUri xmlns:tr2="{namespace}"><tr2:Protocol>RTSP</tr2:Protocol>'
                    f'<tr2:ProfileToken>{escaped_token}</tr2:ProfileToken></tr2:GetStreamUri>')
        else:
            body = (f'<trt:GetStreamUri xmlns:trt="{namespace}" xmlns:tt="http://www.onvif.org/ver10/schema">'
                    '<trt:StreamSetup><tt:Stream>RTP-Unicast</tt:Stream><tt:Transport><tt:Protocol>RTSP</tt:Protocol>'
                    f'</tt:Transport></trt:StreamSetup><trt:ProfileToken>{escaped_token}</trt:ProfileToken></trt:GetStreamUri>')
        uri_root = onvif_soap(endpoint, f"{namespace}/GetStreamUri", body, username, password)
        profile["endpoint"] = onvif_uri(uri_root, "rtsp")
    ordered = sorted(discovered, key=lambda item: item[1]["width"] * item[1]["height"], reverse=True)
    for index, (_, profile) in enumerate(ordered):
        profile["role"] = "main" if index == 0 else "sub" if index == 1 else "auxiliary"
    snapshot = ""
    try:
        token = escape(ordered[0][0])
        body = f'<{prefix}:GetSnapshotUri xmlns:{prefix}="{namespace}"><{prefix}:ProfileToken>{token}</{prefix}:ProfileToken></{prefix}:GetSnapshotUri>'
        snapshot = onvif_uri(onvif_soap(endpoint, f"{namespace}/GetSnapshotUri", body, username, password), "snapshot")
    except (OnvifError, ValueError):
        pass
    profiles = [profile for _, profile in ordered]
    tokens = {profile["id"]: token for token, profile in ordered}
    return profiles, snapshot, tokens


def onvif_backchannel_supported(endpoint: str, username: str, password: str) -> bool:
    namespace = "http://www.onvif.org/ver20/media/wsdl"
    try:
        onvif_soap(
            endpoint, f"{namespace}/GetAudioDecoderConfigurationOptions",
            f'<tr2:GetAudioDecoderConfigurationOptions xmlns:tr2="{namespace}"/>',
            username, password,
        )
        return True
    except OnvifError:
        return False


def onvif_users(endpoint: str, username: str, password: str) -> dict[str, str]:
    namespace = "http://www.onvif.org/ver10/device/wsdl"
    root = onvif_soap(
        endpoint, f"{namespace}/GetUsers",
        f'<tds:GetUsers xmlns:tds="{namespace}"/>', username, password,
    )
    users: dict[str, str] = {}
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] != "User":
            continue
        fields = {child.tag.rsplit("}", 1)[-1]: (child.text or "") for child in node}
        account = fields.get("Username", "")
        level = fields.get("UserLevel", "")
        if account and len(account) <= 64 and level in {"Administrator", "Operator", "User"}:
            users[account] = level
    return users


def onvif_user_management_supported(endpoint: str, username: str, password: str) -> bool:
    if not username:
        return False
    try:
        onvif_users(endpoint, username, password)
        return True
    except (OnvifError, PermissionError):
        return False


def _dedicated_onvif_credentials(camera: dict, reference: object) -> tuple[str, str]:
    if not isinstance(reference, str) or not reference or reference == camera["credentialsRef"]:
        raise ValueError("dedicated ONVIF credentials require a distinct Secret reference")
    dedicated_username, dedicated_password = load_credentials(reference)
    administrator_username, _ = load_credentials(camera["credentialsRef"])
    if not re.fullmatch(r"webobs-[A-Za-z0-9._-]{1,57}", dedicated_username) or \
            dedicated_username == administrator_username or \
            not 16 <= len(dedicated_password.encode("utf-8")) <= 128:
        raise ValueError("dedicated ONVIF credentials violate the reserved account policy")
    return dedicated_username, dedicated_password


def onvif_manage_dedicated_user(camera_id: str, payload: dict) -> dict:
    if not isinstance(payload, dict) or set(payload) != {"operation", "credentialsRef", "role"}:
        raise ValueError("dedicated ONVIF user request fields are invalid")
    operation = payload.get("operation")
    role = payload.get("role")
    if operation not in {"ensure", "delete"} or role not in {"user", "operator"}:
        raise ValueError("dedicated ONVIF user operation or role is invalid")
    camera, _, administrator_username, administrator_password = onvif_camera_context(camera_id)
    if camera["adapter"] != "onvif" or not camera.get("capabilities", {}).get(
            "onvif", {}).get("userManagement", False):
        raise ValueError("camera does not advertise ONVIF user management")
    account, account_password = _dedicated_onvif_credentials(
        camera, payload.get("credentialsRef"))
    endpoint = onvif_device_endpoint(camera["address"])
    existing = onvif_users(endpoint, administrator_username, administrator_password)
    namespace = "http://www.onvif.org/ver10/device/wsdl"
    if operation == "delete":
        if account in existing:
            body = (f'<tds:DeleteUsers xmlns:tds="{namespace}">'
                    f'<tds:Username>{escape(account)}</tds:Username></tds:DeleteUsers>')
            onvif_soap(endpoint, f"{namespace}/DeleteUsers", body,
                       administrator_username, administrator_password)
        audit_device_operation(camera_id, "users.delete-dedicated", "completed")
        return {"cameraId": camera_id, "state": "deleted", "weakRevocation": False}

    level = "Operator" if role == "operator" else "User"
    action = "SetUser" if account in existing else "CreateUsers"
    body = (f'<tds:{action} xmlns:tds="{namespace}" xmlns:tt="http://www.onvif.org/ver10/schema">'
            '<tds:User><tt:Username>' + escape(account) + '</tt:Username>'
            '<tt:Password>' + escape(account_password) + '</tt:Password>'
            '<tt:UserLevel>' + level + f'</tt:UserLevel></tds:User></tds:{action}>')
    onvif_soap(endpoint, f"{namespace}/{action}", body,
               administrator_username, administrator_password)
    audit_device_operation(camera_id, "users.ensure-dedicated", "completed")
    return {"cameraId": camera_id, "state": "updated" if account in existing else "created",
            "userLevel": level, "weakRevocation": False}


def onvif_probe(address: str, credentials_ref: str, include_private_tokens: bool = False) -> dict:
    endpoint = onvif_device_endpoint(address)
    username, password = load_credentials(credentials_ref)
    clock_offset = onvif_device_time_offset(endpoint)
    with ONVIF_CLOCK_LOCK:
        ONVIF_CLOCK_OFFSETS[urlsplit(endpoint).netloc.lower()] = clock_offset
    services = onvif_discover_services(endpoint, username, password)
    profile_kind = ""
    profiles: list[dict] = []
    snapshot = ""
    profile_tokens: dict[str, str] = {}
    if "media2" in services:
        try:
            profiles, snapshot, profile_tokens = onvif_media_profiles(
                services["media2"], "T", username, password)
            profile_kind = "T"
        except OnvifError:
            if "media1" not in services:
                raise
    if not profiles and "media1" in services:
        profiles, snapshot, profile_tokens = onvif_media_profiles(
            services["media1"], "S", username, password)
        profile_kind = "S"
    capabilities = {
        "onvif": {
            "authenticated": bool(username),
            "clockOffsetSeconds": round(clock_offset, 3),
            "mediaProfile": profile_kind,
            "profileCount": len(profiles),
            "snapshot": bool(snapshot),
            "ptz": "ptz" in services,
            "events": "events" in services,
            "imaging": "imaging" in services,
            "talk": bool(profile_kind == "T" and "media2" in services and
                         onvif_backchannel_supported(services["media2"], username, password)),
            "userManagement": onvif_user_management_supported(endpoint, username, password),
            "syncedAt": int(time.time()),
        }
    }
    if snapshot and len(profiles) < 16:
        profiles.append({
            "id": "snapshot", "name": "Snapshot", "role": "snapshot", "endpoint": snapshot,
            "videoCodec": "jpeg", "audioCodec": "", "width": 0, "height": 0, "fps": 0,
        })
    result = {
        "address": endpoint, "adapter": "onvif", "probe": "onvif-authenticated",
        "profileVersion": profile_kind, "profiles": profiles, "capabilities": capabilities,
    }
    if include_private_tokens:
        result["_profileTokens"] = profile_tokens
        result["_services"] = services
    return result


def sync_onvif_camera(camera_id: str) -> dict:
    with connect() as database:
        row = database.execute("SELECT * FROM cameras WHERE id=?", (camera_id,)).fetchone()
        if not row:
            raise KeyError("camera not found")
        camera = camera_document(database, row)
    if camera["adapter"] != "onvif":
        raise ValueError("camera adapter is not onvif")
    result = onvif_probe(camera["address"], camera["credentialsRef"], True)
    profile_tokens = result.pop("_profileTokens")
    result.pop("_services", None)
    camera["address"] = result["address"]
    camera["profiles"] = result["profiles"]
    camera["capabilities"] = result["capabilities"]
    saved = save_camera(validate_camera(camera, camera_id), True)
    with connect() as database:
        database.execute("DELETE FROM onvif_profile_tokens WHERE camera_id=?", (camera_id,))
        database.executemany(
            "INSERT INTO onvif_profile_tokens(camera_id,profile_id,device_token) VALUES(?,?,?)",
            [(camera_id, profile_id, token) for profile_id, token in profile_tokens.items()],
        )
        database.execute("UPDATE cameras SET health='online' WHERE id=?", (camera_id,))
        row = database.execute("SELECT * FROM cameras WHERE id=?", (camera_id,)).fetchone()
        return camera_document(database, row)


def onvif_camera_context(camera_id: str) -> tuple[dict, dict[str, str], str, str]:
    if not ID_RE.fullmatch(camera_id):
        raise ValueError("camera id is invalid")
    with connect() as database:
        row = database.execute("SELECT * FROM cameras WHERE id=?", (camera_id,)).fetchone()
        if not row:
            raise KeyError("camera not found")
        camera = camera_document(database, row)
    if camera["adapter"] != "onvif":
        raise ValueError("camera adapter is not onvif")
    username, password = load_credentials(camera["credentialsRef"])
    services = onvif_discover_services(onvif_device_endpoint(camera["address"]), username, password)
    return camera, services, username, password


def onvif_profile_token(camera_id: str, profile_id: str = "") -> str:
    if profile_id and not ID_RE.fullmatch(profile_id):
        raise ValueError("profile id is invalid")
    with connect() as database:
        if profile_id:
            row = database.execute(
                "SELECT device_token FROM onvif_profile_tokens WHERE camera_id=? AND profile_id=?",
                (camera_id, profile_id),
            ).fetchone()
        else:
            row = database.execute(
                "SELECT t.device_token FROM onvif_profile_tokens t "
                "JOIN stream_profiles p ON p.camera_id=t.camera_id AND p.id=t.profile_id "
                "WHERE t.camera_id=? ORDER BY CASE p.role WHEN 'main' THEN 0 WHEN 'sub' THEN 1 ELSE 2 END,p.id LIMIT 1",
                (camera_id,),
            ).fetchone()
    if not row:
        raise OnvifError("ONVIF profiles must be synchronized before device control")
    return str(row["device_token"])


def bounded_float(payload: dict, name: str, minimum: float, maximum: float,
                  default: float = 0.0) -> float:
    try:
        value = float(payload.get(name, default))
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be numeric") from error
    if value < minimum or value > maximum:
        raise ValueError(f"{name} is out of range")
    return value


def onvif_ptz_stop(camera_id: str, profile_id: str = "", audit: bool = True) -> dict:
    _, services, username, password = onvif_camera_context(camera_id)
    if "ptz" not in services:
        raise ValueError("camera does not advertise PTZ")
    token = escape(onvif_profile_token(camera_id, profile_id))
    onvif_soap(
        services["ptz"], "http://www.onvif.org/ver20/ptz/wsdl/Stop",
        '<tptz:Stop xmlns:tptz="http://www.onvif.org/ver20/ptz/wsdl">'
        f'<tptz:ProfileToken>{token}</tptz:ProfileToken>'
        '<tptz:PanTilt>true</tptz:PanTilt><tptz:Zoom>true</tptz:Zoom></tptz:Stop>',
        username, password,
    )
    with PTZ_RATE_LOCK:
        timer = PTZ_STOP_TIMERS.pop(camera_id, None)
        if timer and timer is not threading.current_thread():
            timer.cancel()
    if audit:
        audit_device_operation(camera_id, "ptz.stop", "stopped")
    return {"cameraId": camera_id, "state": "stopped"}


def scheduled_ptz_stop(camera_id: str, profile_id: str) -> None:
    try:
        onvif_ptz_stop(camera_id, profile_id)
    except (KeyError, ValueError, PermissionError, OnvifError):
        audit_device_operation(camera_id, "ptz.auto-stop", "failed")


def onvif_ptz_command(camera_id: str, payload: dict) -> dict:
    operation = payload.get("operation", "")
    if operation not in {"continuous", "relative", "absolute", "stop", "home", "gotoPreset"}:
        raise ValueError("PTZ operation is unsupported")
    profile_id = str(payload.get("profileId", ""))
    if operation == "stop":
        return onvif_ptz_stop(camera_id, profile_id)
    now = time.monotonic()
    with PTZ_RATE_LOCK:
        if now - PTZ_LAST_COMMAND.get(camera_id, 0.0) < 0.1:
            audit_device_operation(camera_id, f"ptz.{operation}", "denied")
            raise RuntimeError("PTZ command rate limit exceeded")
        PTZ_LAST_COMMAND[camera_id] = now
    _, services, username, password = onvif_camera_context(camera_id)
    if "ptz" not in services:
        raise ValueError("camera does not advertise PTZ")
    token = escape(onvif_profile_token(camera_id, profile_id))
    namespace = "http://www.onvif.org/ver20/ptz/wsdl"
    if operation in {"continuous", "relative", "absolute"}:
        x = bounded_float(payload, "x", -1.0, 1.0)
        y = bounded_float(payload, "y", -1.0, 1.0)
        zoom = bounded_float(payload, "zoom", -1.0, 1.0)
        vector = (f'<tt:PanTilt xmlns:tt="http://www.onvif.org/ver10/schema" x="{x:.6f}" y="{y:.6f}"/>'
                  f'<tt:Zoom xmlns:tt="http://www.onvif.org/ver10/schema" x="{zoom:.6f}"/>')
        element = {"continuous": "Velocity", "relative": "Translation", "absolute": "Position"}[operation]
        action_name = operation.capitalize() + "Move"
        body = (f'<tptz:{action_name} xmlns:tptz="{namespace}"><tptz:ProfileToken>{token}</tptz:ProfileToken>'
                f'<tptz:{element}>{vector}</tptz:{element}></tptz:{action_name}>')
    elif operation == "home":
        action_name = "GotoHomePosition"
        body = (f'<tptz:GotoHomePosition xmlns:tptz="{namespace}">'
                f'<tptz:ProfileToken>{token}</tptz:ProfileToken></tptz:GotoHomePosition>')
    else:
        preset = str(payload.get("presetToken", ""))
        if not preset or len(preset) > 256 or any(ord(character) < 32 for character in preset):
            raise ValueError("presetToken is invalid")
        action_name = "GotoPreset"
        body = (f'<tptz:GotoPreset xmlns:tptz="{namespace}"><tptz:ProfileToken>{token}</tptz:ProfileToken>'
                f'<tptz:PresetToken>{escape(preset)}</tptz:PresetToken></tptz:GotoPreset>')
    onvif_soap(services["ptz"], f"{namespace}/{action_name}", body, username, password)
    audit_device_operation(camera_id, f"ptz.{operation}", "accepted")
    result = {"cameraId": camera_id, "operation": operation, "state": "accepted"}
    if operation == "continuous":
        duration_ms = int(bounded_float(payload, "durationMs", 100, 2000, 500))
        timer = threading.Timer(duration_ms / 1000.0, scheduled_ptz_stop,
                                args=(camera_id, profile_id))
        timer.daemon = True
        with PTZ_RATE_LOCK:
            previous = PTZ_STOP_TIMERS.pop(camera_id, None)
            if previous:
                previous.cancel()
            PTZ_STOP_TIMERS[camera_id] = timer
        timer.start()
        result["autoStopMs"] = duration_ms
    return result


def onvif_presets(camera_id: str, profile_id: str = "") -> list[dict]:
    _, services, username, password = onvif_camera_context(camera_id)
    if "ptz" not in services:
        raise ValueError("camera does not advertise PTZ")
    token = escape(onvif_profile_token(camera_id, profile_id))
    namespace = "http://www.onvif.org/ver20/ptz/wsdl"
    root = onvif_soap(
        services["ptz"], f"{namespace}/GetPresets",
        f'<tptz:GetPresets xmlns:tptz="{namespace}"><tptz:ProfileToken>{token}</tptz:ProfileToken></tptz:GetPresets>',
        username, password,
    )
    presets: list[dict] = []
    for node in root.iter():
        if xml_local_name(node.tag) != "Preset":
            continue
        preset_token = str(node.get("token", ""))[:256]
        if preset_token:
            presets.append({"token": preset_token, "name": (xml_text(node, ("Name",)) or preset_token)[:128]})
    return presets[:128]


def onvif_preset_mutation(camera_id: str, payload: dict) -> dict:
    operation = payload.get("operation", "")
    if operation not in {"set", "remove"}:
        raise ValueError("preset operation is unsupported")
    profile_id = str(payload.get("profileId", ""))
    preset_token = str(payload.get("presetToken", ""))
    if preset_token and (len(preset_token) > 256 or any(ord(character) < 32 for character in preset_token)):
        raise ValueError("presetToken is invalid")
    _, services, username, password = onvif_camera_context(camera_id)
    if "ptz" not in services:
        raise ValueError("camera does not advertise PTZ")
    profile_token = escape(onvif_profile_token(camera_id, profile_id))
    namespace = "http://www.onvif.org/ver20/ptz/wsdl"
    if operation == "set":
        name = str(payload.get("name", "Preset")).strip()
        if not name or len(name) > 128 or any(ord(character) < 32 for character in name):
            raise ValueError("preset name is invalid")
        optional_token = (f"<tptz:PresetToken>{escape(preset_token)}</tptz:PresetToken>"
                          if preset_token else "")
        root = onvif_soap(
            services["ptz"], f"{namespace}/SetPreset",
            f'<tptz:SetPreset xmlns:tptz="{namespace}"><tptz:ProfileToken>{profile_token}</tptz:ProfileToken>'
            f'<tptz:PresetName>{escape(name)}</tptz:PresetName>{optional_token}</tptz:SetPreset>',
            username, password,
        )
        preset_token = xml_text(root, ("PresetToken",)) or preset_token
    else:
        if not preset_token:
            raise ValueError("presetToken is required")
        onvif_soap(
            services["ptz"], f"{namespace}/RemovePreset",
            f'<tptz:RemovePreset xmlns:tptz="{namespace}"><tptz:ProfileToken>{profile_token}</tptz:ProfileToken>'
            f'<tptz:PresetToken>{escape(preset_token)}</tptz:PresetToken></tptz:RemovePreset>',
            username, password,
        )
    audit_device_operation(camera_id, f"preset.{operation}", "completed")
    return {"cameraId": camera_id, "operation": operation, "presetToken": preset_token}


def onvif_snapshot(camera_id: str) -> dict:
    camera, _, username, password = onvif_camera_context(camera_id)
    profile = next((item for item in camera["profiles"] if item["role"] == "snapshot"), None)
    if not profile:
        raise ValueError("camera does not advertise snapshots")
    endpoint = safe_endpoint(profile["endpoint"], "snapshot")
    password_manager = HTTPPasswordMgrWithDefaultRealm()
    if username:
        password_manager.add_password(None, endpoint, username, password)
    opener = build_opener(NoRedirect(), HTTPDigestAuthHandler(password_manager),
                          HTTPBasicAuthHandler(password_manager), HTTPSHandler(context=TLS_CONTEXT))
    try:
        with opener.open(Request(endpoint, headers={"User-Agent": "webobs-snapshot/1"}),
                         timeout=ONVIF_TIMEOUT_SECONDS) as response:
            content_type = response.headers.get_content_type()
            data = response.read(MAX_TALK_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        raise OnvifError("camera snapshot is unavailable") from error
    if content_type not in {"image/jpeg", "image/png"} or not data or len(data) > MAX_TALK_BYTES:
        raise OnvifError("camera returned an invalid snapshot")
    audit_device_operation(camera_id, "snapshot.read", "completed")
    return {"cameraId": camera_id, "contentType": content_type,
            "sha256": hashlib.sha256(data).hexdigest(),
            "data": base64.b64encode(data).decode()}


def finish_talk_process(camera_id: str, process: subprocess.Popen, audio: bytes) -> None:
    result = "failed"
    try:
        process.communicate(audio, timeout=12)
        result = "completed" if process.returncode == 0 else "failed"
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
    finally:
        audit_device_operation(camera_id, "talk.session", result)
        with TALK_LOCK:
            if TALK_PROCESSES.get(camera_id) is process:
                TALK_PROCESSES.pop(camera_id, None)


def onvif_talk(camera_id: str, payload: dict) -> dict:
    operation = payload.get("operation", "")
    if operation == "stop":
        with TALK_LOCK:
            process = TALK_PROCESSES.pop(camera_id, None)
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
        audit_device_operation(camera_id, "talk.stop", "stopped")
        return {"cameraId": camera_id, "state": "stopped"}
    if operation != "start":
        raise ValueError("talk operation must be start or stop")
    camera, _, username, password = onvif_camera_context(camera_id)
    if not camera.get("capabilities", {}).get("onvif", {}).get("talk", False):
        audit_device_operation(camera_id, "talk.start", "denied")
        raise ValueError("camera does not advertise ONVIF backchannel audio")
    content_type = payload.get("contentType", "")
    if content_type not in {"audio/webm", "audio/ogg", "audio/wav", "audio/mp4"}:
        raise ValueError("talk audio content type is unsupported")
    encoded = payload.get("data", "")
    if not isinstance(encoded, str) or len(encoded) > MAX_TALK_BYTES * 2:
        raise ValueError("talk audio payload is too large")
    try:
        audio = base64.b64decode(encoded, validate=True)
    except ValueError as error:
        raise ValueError("talk audio payload is invalid base64") from error
    if not audio or len(audio) > MAX_TALK_BYTES:
        raise ValueError("talk audio payload is empty or too large")
    profile = next((item for item in camera["profiles"] if item["role"] == "main"), None)
    if not profile:
        raise ValueError("camera has no main media profile")
    endpoint = endpoint_with_credentials(profile["endpoint"], username, password)
    command = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-re",
        "-i", "pipe:0", "-t", "10", "-vn", "-ac", "1", "-ar", "8000",
        "-c:a", "pcm_alaw", "-rtsp_transport", "tcp", "-f", "rtsp", endpoint,
    ]
    with TALK_LOCK:
        current = TALK_PROCESSES.get(camera_id)
        if current and current.poll() is None:
            audit_device_operation(camera_id, "talk.start", "denied")
            raise RuntimeError("talk session is already active")
        try:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL)
        except OSError as error:
            raise OnvifError("talk media process is unavailable") from error
        TALK_PROCESSES[camera_id] = process
    worker = threading.Thread(target=finish_talk_process, args=(camera_id, process, audio), daemon=True)
    worker.start()
    audit_device_operation(camera_id, "talk.start", "accepted")
    return {"cameraId": camera_id, "state": "active", "maximumSeconds": 10}


def onvif_pull_events(camera_id: str) -> dict:
    _, services, username, password = onvif_camera_context(camera_id)
    if "events" not in services:
        raise ValueError("camera does not advertise ONVIF events")
    event_namespace = "http://www.onvif.org/ver10/events/wsdl"
    root = onvif_soap(
        services["events"], f"{event_namespace}/CreatePullPointSubscription",
        f'<tev:CreatePullPointSubscription xmlns:tev="{event_namespace}"/>',
        username, password,
    )
    subscription = ""
    for node in root.iter():
        if xml_local_name(node.tag) == "SubscriptionReference":
            subscription = xml_text(node, ("Address",))
            break
    if not subscription:
        subscription = xml_text(root, ("Address",))
    subscription = onvif_returned_endpoint(subscription, "onvif")
    pulled = onvif_soap(
        subscription, f"{event_namespace}/PullMessages",
        f'<tev:PullMessages xmlns:tev="{event_namespace}"><tev:Timeout>PT1S</tev:Timeout>'
        '<tev:MessageLimit>64</tev:MessageLimit></tev:PullMessages>',
        username, password,
    )
    events: list[dict] = []
    for notification in pulled.iter():
        if xml_local_name(notification.tag) != "NotificationMessage":
            continue
        topic = xml_text(notification, ("Topic",))[:256]
        message = next((node for node in notification.iter()
                        if xml_local_name(node.tag) == "Message"), notification)
        properties: dict[str, str] = {}
        for item in message.iter():
            name = item.get("Name")
            value = item.get("Value")
            if name and value and len(properties) < 32:
                properties[re.sub(r"[^a-zA-Z0-9._-]", "-", name)[:64]] = value[:256]
        events.append({"topic": topic or "unknown", "properties": properties})
    audit_device_operation(camera_id, "events.pull", "completed")
    for event in events:
        topic = event["topic"].lower()
        event_type = "motion" if "motion" in topic else "tamper" if "tamper" in topic else "line-crossing" if "line" in topic else "region-crossing" if "region" in topic else "input"
        try:
            payload = json.dumps({"cameraId": camera_id, "type": event_type, "source": "onvif",
                                  "topic": event["topic"], "properties": event["properties"]},
                                 separators=(",", ":")).encode()
            request = Request("http://127.0.0.1:8093/events", data=payload, method="POST",
                              headers={"Content-Type": "application/json"})
            with urlopen(request, timeout=.5) as response:
                response.read(1024)
        except (HTTPError, URLError, TimeoutError, OSError):
            pass
    return {"cameraId": camera_id, "events": events[:64], "subscription": "ephemeral"}


def onvif_event_worker() -> None:
    """Renew bounded ephemeral PullPoint subscriptions without owning recording state."""
    interval = max(10, min(int(os.environ.get("WEBOBS_ONVIF_EVENT_POLL_SECONDS", "30")), 3600))
    while True:
        try:
            with connect() as database:
                rows = database.execute("SELECT id,capabilities_json FROM cameras WHERE adapter='onvif'").fetchall()
            for row in rows[:64]:
                try:
                    capabilities = json.loads(row["capabilities_json"])
                    if capabilities.get("onvif", {}).get("events"):
                        onvif_pull_events(row["id"])
                except (KeyError, ValueError, PermissionError, OnvifError, json.JSONDecodeError):
                    continue
        except (OSError, sqlite3.Error, ValueError):
            pass
        time.sleep(interval)


def device_audit(camera_id: str) -> list[dict]:
    with connect() as database:
        rows = database.execute(
            "SELECT id,operation,result,created_at AS createdAt FROM device_operation_audit "
            "WHERE camera_id=? ORDER BY id DESC LIMIT 200", (camera_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def classify(address: str) -> dict:
    normalized = address if "://" in address else "http://" + address
    parsed = urlsplit(normalized)
    if parsed.username or parsed.password:
        raise ValueError("embedded credentials are forbidden")
    scheme, path = parsed.scheme.lower(), parsed.path.lower()
    adapter = "onvif"
    if scheme in ("rtsp", "rtsps"): adapter = "rtsp"
    elif scheme == "srt": adapter = "srt"
    elif scheme in ("rtp", "udp"): adapter = "rtp"
    elif path.endswith(".m3u8"): adapter = "hls"
    elif path.endswith(".flv"): adapter = "http-flv"
    elif path.endswith((".jpg", ".jpeg")): adapter = "snapshot"
    elif ("mjpeg" in path or "mjpg" in path or
          path.endswith("/-wvhttp-01-/video.cgi")): adapter = "mjpeg"
    elif "whep" in path: adapter = "whep"
    result = {"address": normalized, "adapter": adapter, "profiles": [], "probe": "classified"}
    if adapter in {"rtsp", "hls", "http-flv", "srt", "rtp"}:
        result["profiles"] = [{
            "id": "main", "name": "Main", "role": "main", "endpoint": normalized,
            "videoCodec": "unknown", "audioCodec": "", "width": 0, "height": 0, "fps": 0,
        }]
        try:
            completed = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height,r_frame_rate",
                 "-of", "json", normalized], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                timeout=6, check=True,
            )
            streams = json.loads(completed.stdout).get("streams", [])
            video = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
            audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), {})
            result["profiles"] = [{
                "id": "main", "name": "Main", "role": "main", "endpoint": normalized,
                "videoCodec": video.get("codec_name", "unknown"), "audioCodec": audio.get("codec_name", ""),
                "width": video.get("width", 0), "height": video.get("height", 0), "fps": 0,
            }]
            result["probe"] = "ffprobe"
        except (subprocess.SubprocessError, OSError, ValueError, json.JSONDecodeError):
            result["probe"] = "unreachable-or-unsupported"
    elif adapter in {"mjpeg", "snapshot", "whep", "onvif"}:
        try:
            # Server-push MJPEG endpoints frequently do not implement HEAD. Read
            # only the first bounded block so protocol detection cannot retain a
            # camera stream or buffer an unbounded multipart response.
            method = "GET" if adapter == "mjpeg" else "HEAD"
            request = Request(normalized, method=method, headers={"User-Agent": "webobs-camera-probe/1"})
            with urlopen(request, timeout=3) as response:
                content_type = response.headers.get_content_type().lower()
                result["contentType"] = content_type
                if method == "GET":
                    block = response.read1(65536)
                    if (content_type != "multipart/x-mixed-replace" or
                            (b"image/jpeg" not in block.lower() and b"\xff\xd8" not in block)):
                        raise ValueError("HTTP endpoint is not a server-push MJPEG stream")
                    result["profiles"] = [{
                        "id": "main", "name": "Main", "role": "main", "endpoint": normalized,
                        "videoCodec": "mjpeg", "audioCodec": "", "width": 0, "height": 0, "fps": 0,
                    }]
                    result["probe"] = "http-server-push-mjpeg"
                else:
                    result["probe"] = "http-head"
        except Exception:
            result["probe"] = "unreachable-or-auth-required"
    return result


def onvif_discover(timeout: float = 2.0, interface_address: str = "") -> list[dict]:
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 0.1 <= timeout <= 5:
        raise ValueError("discovery timeout must be between 0.1 and 5 seconds")
    if interface_address:
        try:
            interface = ipaddress.ip_address(interface_address)
        except ValueError as error:
            raise ValueError("discovery interface must be an IPv4 address") from error
        if interface.version != 4 or interface.is_multicast or interface.is_unspecified:
            raise ValueError("discovery interface must be a specific IPv4 address")
    message_id = uuid.uuid4()
    probe = f'''<?xml version="1.0" encoding="UTF-8"?>
<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope" xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing" xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery" xmlns:dn="http://www.onvif.org/ver10/network/wsdl"><e:Header><w:MessageID>uuid:{message_id}</w:MessageID><w:To e:mustUnderstand="true">urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To><w:Action e:mustUnderstand="true">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action></e:Header><e:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe></e:Body></e:Envelope>'''.encode()
    found: dict[str, dict] = {}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        if interface_address:
            sock.bind((interface_address, 0))
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF,
                            socket.inet_aton(interface_address))
        sock.settimeout(0.25)
        sock.sendto(probe, ("239.255.255.250", 3702))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                data, peer = sock.recvfrom(65535)
            except socket.timeout:
                continue
            text = data.decode("utf-8", "ignore")
            match = re.search(r"<[^:>]*:?XAddrs>([^<]+)</", text)
            if match:
                for address in match.group(1).split():
                    if address.startswith(("http://", "https://")):
                        found[address] = {"address": address, "host": peer[0], "adapter": "onvif"}
    finally:
        sock.close()
    return list(found.values())[:128]


class Handler(BaseHTTPRequestHandler):
    server_version = "webobs-camera-registry"

    def log_message(self, format: str, *args: object) -> None:
        return

    def respond(self, status: int, value: object, headers: dict[str, str] | None = None) -> None:
        body = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        for name, header_value in (headers or {}).items():
            self.send_header(name, header_value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def payload(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_BODY:
            raise ValueError("request body is empty or too large")
        value = json.loads(self.rfile.read(length))
        if not isinstance(value, dict):
            raise ValueError("request JSON must be an object")
        return value

    def do_GET(self) -> None:
        path, _, query = self.path.partition("?")
        if path == "/health":
            self.respond(200, {"status": "ready", "database": "sqlite-wal"}); return
        if path == "/adapters":
            self.respond(200, {"adapters": sorted(ADAPTERS), "onvif": {
                "profiles": ["T", "S"], "discovery": True, "authenticatedMediaSync": True,
                "ptz": True, "presets": True, "snapshots": True,
                "pullPointEvents": True, "guardedTalk": True,
            }}); return
        if path == "/source-catalog":
            try:
                self.respond(200, source_catalog(query))
            except ValueError as error:
                self.respond(400, {"error": str(error)})
            return
        catalog_match = re.fullmatch(r"/source-catalog/([a-zA-Z0-9._-]{1,64})", path)
        if catalog_match:
            with connect() as database:
                row = database.execute("SELECT * FROM cameras WHERE id=?", (catalog_match.group(1),)).fetchone()
                if not row:
                    self.respond(404, {"error": "camera not found"}); return
                value = source_catalog_document(database, row)
                self.respond(200, value, {"ETag": f'"{value["revision"]}"'})
            return
        if path == "/operations/issues":
            values = parse_qs(query, keep_blank_values=True)
            state, severity, component = (values.get(name, [""])[0] for name in ("state", "severity", "component"))
            if state and state not in {"open", "acknowledged", "resolved"} or \
                    severity and severity not in {"info", "warning", "error"} or len(component) > 64:
                self.respond(400, {"error": "issue filter is invalid"}); return
            clauses, arguments = [], []
            for column, value in (("state", state), ("severity", severity), ("component", component)):
                if value: clauses.append(f"{column}=?"); arguments.append(value)
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            with connect() as database:
                rows = database.execute(
                    f"SELECT * FROM operational_issues{where} ORDER BY CASE state WHEN 'open' THEN 0 "
                    "WHEN 'acknowledged' THEN 1 ELSE 2 END,last_seen_at DESC LIMIT 4096", arguments).fetchall()
                self.respond(200, {"issues": [issue_document(row) for row in rows]})
            return
        if path == "/settings":
            value = runtime_settings()
            self.respond(200, value, {"ETag": f'"{value["revision"]}"'}); return
        if path == "/settings/schema":
            self.respond(200, {"schemaVersion": 1, "groups": [
                "interface", "video", "audio", "recording", "analytics", "telemetry", "watchdog", "security-pwa"],
                "writable": ["defaultTransportMode", "probeTimeoutSeconds", "sourceRecoveryEnabled", "issueRetentionLimit"],
                "deploymentReadOnly": ["tls", "ports", "secrets", "gpuDevice"],
            }); return
        if path == "/analytics/policies":
            self.respond(200, {"schemaVersion": 2, "revision": analytics_revision(), "policies": analytics_policies()}); return
        if path == "/analytics/status":
            policies = analytics_policies()
            statuses = []
            for policy in policies:
                try:
                    value = analytics_runtime_plan({"cameraId": policy["cameraId"], "profileId": policy["profileId"], "kinds": ["motion", "scene-change", "person"], "capabilities": {"wasm": True}})
                    close_analytics_session(value["sessionId"])
                    key_by_kind = {"motion": "motion", "scene-change": "sceneChange", "person": "person"}
                    statuses.append({"cameraId": policy["cameraId"], "profileId": policy["profileId"], **{
                        key_by_kind[item["kind"]]: item for item in value["plans"] if item["kind"] in key_by_kind
                    }})
                except (KeyError, ValueError, PermissionError):
                    continue
            self.respond(200, {"statuses": statuses}); return
        presets_match = re.fullmatch(r"/cameras/([a-zA-Z0-9._-]{1,64})/onvif/presets", path)
        if presets_match:
            try:
                profile_id = parse_qs(query, strict_parsing=False).get("profileId", [""])[0]
                self.respond(200, {"cameraId": presets_match.group(1),
                                   "presets": onvif_presets(presets_match.group(1), profile_id)})
            except KeyError: self.respond(404, {"error": "camera not found"})
            except PermissionError as error: self.respond(401, {"error": str(error)})
            except OnvifError as error: self.respond(502, {"error": str(error)})
            except (ValueError, TypeError) as error: self.respond(400, {"error": str(error)})
            return
        audit_match = re.fullmatch(r"/cameras/([a-zA-Z0-9._-]{1,64})/operations", path)
        if audit_match:
            self.respond(200, {"cameraId": audit_match.group(1),
                               "operations": device_audit(audit_match.group(1))}); return
        with connect() as database:
            if path.startswith("/resolve/"):
                parts = path.removeprefix("/resolve/").split("/")
                if len(parts) != 2 or not all(ID_RE.fullmatch(part) for part in parts):
                    self.respond(404, {"error": "not_found"}); return
                try: self.respond(200, resolve_profile(database, parts[0], parts[1]))
                except KeyError: self.respond(404, {"error": "not_found"})
                except InsecureHttpDenied: self.respond(403, {"error": "insecure_http_not_approved"})
                except (PermissionError, OSError, ValueError, json.JSONDecodeError): self.respond(503, {"error": "credentials_unavailable"})
                return
            if path == "/cameras":
                rows = database.execute("SELECT * FROM cameras ORDER BY name,id").fetchall()
                self.respond(200, {"cameras": [camera_document(database, row) for row in rows]}); return
            if path == "/cameras/analytics-policies":
                self.respond(200, {"policies": analytics_policies()}); return
            if path.startswith("/cameras/"):
                camera_id = path.removeprefix("/cameras/")
                if not ID_RE.fullmatch(camera_id): self.respond(404, {"error": "not_found"}); return
                row = database.execute("SELECT * FROM cameras WHERE id=?", (camera_id,)).fetchone()
                if not row: self.respond(404, {"error": "not_found"}); return
                self.respond(200, camera_document(database, row)); return
        self.respond(404, {"error": "not_found"})

    def do_POST(self) -> None:
        try:
            if self.path == "/cameras":
                self.respond(201, save_camera(validate_camera(self.payload()), False)); return
            if self.path == "/analytics/runtime-plans":
                self.respond(200, analytics_runtime_plan(self.payload())); return
            if self.path == "/analytics/signals/batch":
                session_id = self.headers.get("X-WebObs-Analytics-Session", "")
                if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", session_id): raise PermissionError("analytics runtime session is missing")
                self.respond(202, ingest_analytics_signals(self.payload(), session_id)); return
            session_match = re.fullmatch(r"/analytics/runtime-sessions/([A-Za-z0-9_-]{32,128})", self.path)
            if session_match:
                self.respond(200, {"closed": close_analytics_session(session_match.group(1))}); return
            if self.path == "/detect":
                payload = self.payload(); self.respond(200, classify(str(payload.get("address", "")))); return
            if self.path == "/onvif/discover":
                payload = self.payload(); timeout_ms = payload.get("timeoutMs", 2000)
                if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int):
                    raise ValueError("timeoutMs must be an integer")
                self.respond(200, {"devices": onvif_discover(
                    timeout_ms / 1000, str(payload.get("interfaceAddress", "")))}); return
            if self.path == "/onvif/probe":
                payload = self.payload()
                credentials_ref = payload.get("credentialsRef", "")
                if not isinstance(credentials_ref, str):
                    raise ValueError("credentialsRef is invalid")
                self.respond(200, onvif_probe(str(payload.get("address", "")), credentials_ref)); return
            if self.path == "/source-catalog/batch":
                self.respond(200, {"items": batch_source_catalog(self.payload())}); return
            camera_probe_match = re.fullmatch(
                r"/source-catalog/([a-zA-Z0-9._-]{1,64})/probe", self.path)
            if camera_probe_match:
                if int(self.headers.get("Content-Length", "0")):
                    self.payload()
                camera_id = camera_probe_match.group(1)
                self.respond(200, {"cameraId": camera_id,
                                   "profiles": probe_source_camera(camera_id)}); return
            catalog_probe_match = re.fullmatch(
                r"/source-catalog/([a-zA-Z0-9._-]{1,64})/profiles/([a-zA-Z0-9._-]{1,64})/probe",
                self.path,
            )
            if catalog_probe_match:
                if int(self.headers.get("Content-Length", "0")):
                    self.payload()
                self.respond(200, {"cameraId": catalog_probe_match.group(1),
                                   "profile": probe_source_profile(*catalog_probe_match.groups())}); return
            issue_ack_match = re.fullmatch(
                r"/operations/issues/([a-f0-9]{32})/acknowledge", self.path)
            if issue_ack_match:
                if int(self.headers.get("Content-Length", "0")):
                    self.payload()
                with connect() as database:
                    changed = database.execute(
                        "UPDATE operational_issues SET state='acknowledged',last_seen_at=? WHERE id=? AND state='open'",
                        (int(time.time()), issue_ack_match.group(1))).rowcount
                    row = database.execute("SELECT * FROM operational_issues WHERE id=?", (issue_ack_match.group(1),)).fetchone()
                    if not row:
                        self.respond(404, {"error": "issue not found"})
                    else:
                        self.respond(200, issue_document(row))
                return
            sync_match = re.fullmatch(r"/cameras/([a-zA-Z0-9._-]{1,64})/onvif/sync", self.path)
            if sync_match:
                self.respond(200, sync_onvif_camera(sync_match.group(1))); return
            browser_probe_match = re.fullmatch(
                r"/cameras/([a-zA-Z0-9._-]{1,64})/profiles/([a-zA-Z0-9._-]{1,64})/browser-direct/probe",
                self.path,
            )
            if browser_probe_match:
                if int(self.headers.get("Content-Length", "0")):
                    self.payload()
                self.respond(200, browser_direct_probe(*browser_probe_match.groups())); return
            operation_match = re.fullmatch(
                r"/cameras/([a-zA-Z0-9._-]{1,64})/onvif/(ptz|presets|snapshot|events/pull|talk|users)",
                self.path,
            )
            if operation_match:
                camera_id, operation = operation_match.groups()
                if operation == "ptz":
                    self.respond(200, onvif_ptz_command(camera_id, self.payload()))
                elif operation == "presets":
                    self.respond(200, onvif_preset_mutation(camera_id, self.payload()))
                elif operation == "snapshot":
                    if int(self.headers.get("Content-Length", "0")):
                        self.payload()
                    self.respond(200, onvif_snapshot(camera_id))
                elif operation == "events/pull":
                    if int(self.headers.get("Content-Length", "0")):
                        self.payload()
                    self.respond(200, onvif_pull_events(camera_id))
                elif operation == "users":
                    self.respond(200, onvif_manage_dedicated_user(camera_id, self.payload()))
                else:
                    self.respond(202, onvif_talk(camera_id, self.payload()))
                return
            self.respond(404, {"error": "not_found"})
        except FileExistsError as error: self.respond(409, {"error": str(error)})
        except KeyError: self.respond(404, {"error": "camera not found"})
        except InsecureHttpDenied: self.respond(403, {"error": "insecure_http_not_approved"})
        except PermissionError as error: self.respond(401, {"error": str(error)})
        except BrowserDirectProbeError as error: self.respond(400, {"error": str(error)})
        except OnvifError as error: self.respond(502, {"error": str(error)})
        except RevisionConflict as error: self.respond(409, {"error": "revision_conflict", "revision": str(error)})
        except RuntimeError as error: self.respond(429, {"error": str(error)})
        except (ValueError, TypeError, json.JSONDecodeError) as error: self.respond(400, {"error": str(error)})

    def do_PUT(self) -> None:
        if self.path == "/cameras/analytics-policies":
            try:
                self.respond(200, {"policies": save_analytics_policies(self.payload())})
            except KeyError as error: self.respond(404, {"error": str(error)})
            except (ValueError, TypeError, json.JSONDecodeError) as error: self.respond(400, {"error": str(error)})
            return
        if not self.path.startswith("/cameras/"):
            self.respond(404, {"error": "not_found"}); return
        camera_id = self.path.removeprefix("/cameras/")
        try:
            if not ID_RE.fullmatch(camera_id): raise ValueError("camera id is invalid")
            self.respond(200, save_camera(validate_camera(self.payload(), camera_id), True))
        except (ValueError, TypeError, json.JSONDecodeError) as error: self.respond(400, {"error": str(error)})

    def do_PATCH(self) -> None:
        try:
            revision = expected_revision(self.headers.get("If-Match"))
        except ValueError as error:
            self.respond(428 if not self.headers.get("If-Match") else 400, {"error": str(error)}); return
        try:
            if self.path == "/analytics/policies":
                value = analytics_v3_policies(self.payload(), revision)
                self.respond(200, value, {"ETag": f'"{value["revision"]}"'}); return
            catalog_match = re.fullmatch(r"/source-catalog/([a-zA-Z0-9._-]{1,64})", self.path)
            if catalog_match:
                value = patch_source_catalog(catalog_match.group(1), self.payload(), revision)
                self.respond(200, value, {"ETag": f'"{value["revision"]}"'}); return
            if self.path == "/settings":
                value = patch_runtime_settings(self.payload(), revision)
                self.respond(200, value, {"ETag": f'"{value["revision"]}"'}); return
            self.respond(404, {"error": "not_found"})
        except RevisionConflict as error:
            self.respond(409, {"error": "revision_conflict", "revision": str(error)})
        except KeyError as error:
            self.respond(404, {"error": str(error)})
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            self.respond(400, {"error": str(error)})

    def do_DELETE(self) -> None:
        session_match = re.fullmatch(r"/analytics/runtime-sessions/([A-Za-z0-9_-]{32,128})", self.path)
        if session_match:
            self.respond(200, {"closed": close_analytics_session(session_match.group(1))}); return
        if not self.path.startswith("/cameras/"):
            self.respond(404, {"error": "not_found"}); return
        camera_id = self.path.removeprefix("/cameras/")
        if not ID_RE.fullmatch(camera_id): self.respond(404, {"error": "not_found"}); return
        with connect() as database:
            removed = database.execute("DELETE FROM cameras WHERE id=?", (camera_id,)).rowcount
        self.respond(200 if removed else 404, {"id": camera_id, "deleted": bool(removed)})


if __name__ == "__main__":
    initialize()
    threading.Thread(target=onvif_event_worker, daemon=True).start()
    ThreadingHTTPServer(LISTEN, Handler).serve_forever()
