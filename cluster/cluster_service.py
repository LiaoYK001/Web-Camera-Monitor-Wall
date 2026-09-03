#!/usr/bin/env python3
"""WebOBS v2-M7 cluster, RBAC, placement and lease control service.

The administrator listener is loopback-only and trusted exclusively through the
per-process internal token. The cluster listener is optional and requires mTLS.
No camera endpoint, credential, private key, or host path is stored here.
"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import ctypes.util
import datetime as dt
import hashlib
import hmac
import http.server
import json
import os
import pathlib
import re
import secrets
import sqlite3
import ssl
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import parse_qs, quote, urlencode, urlsplit


MAX_BODY = 1024 * 1024
MAX_PAGE = 256
MAX_AUDIT = 8192
MAX_NODES = 256
MAX_VOLUMES = 256
HEARTBEAT_SECONDS = 5
NODE_UNHEALTHY_SECONDS = 20
LEASE_SECONDS = 30
LEASE_RENEW_SECONDS = 10
ISOLATION_GRACE_SECONDS = 120
MAX_CLOCK_SKEW_SECONDS = 5
ARCHIVE_TICKET_SECONDS = 60
MAX_BROWSER_ARCHIVE_BYTES = 512 * 1024 * 1024
ANALYTICS_MEDIA_GRANT_SECONDS = 60
MAX_ANALYTICS_FRAME_BYTES = 160 * 90 * 4
MAX_ANALYTICS_FRAME_REQUESTS = 60
ENROLLMENT_SECONDS = 600
CERTIFICATE_SECONDS = 30 * 24 * 60 * 60
CERTIFICATE_RENEW_SECONDS = 7 * 24 * 60 * 60
ANALYTICS_MODEL_ID = "ssd-mobilenet-v1-12-person"
ANALYTICS_MODEL_VERSION = "onnx-model-zoo-4c46cd00"
ANALYTICS_MODEL_SHA256 = "b8fba5e404077d4048d27fcd1667e85e27e192eb9bf51e696c46a3acd7d21058"
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
USERNAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
VOLUME_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
SECRET_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")


PERMISSIONS = frozenset({
    "live.view", "scene.read", "scene.write", "ptz.control", "talk.control",
    "snapshot.create", "playback.view", "export.create", "recording.lock",
    "recording.delete", "event.ack", "device.manage", "storage.manage",
    "node.manage", "settings.manage", "user.manage", "audit.view", "metrics.view",
    "analytics.view", "analytics.run", "analytics.manage",
})

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "admin": PERMISSIONS,
    "operator": frozenset({
        "live.view", "scene.read", "playback.view", "snapshot.create", "ptz.control",
        "talk.control", "event.ack", "recording.lock", "analytics.view", "analytics.run",
    }),
    "viewer": frozenset({"live.view", "scene.read", "playback.view", "analytics.view", "analytics.run"}),
    "auditor": frozenset({"event.ack", "audit.view", "playback.view", "analytics.view"}),
    "exporter": frozenset({"playback.view", "export.create"}),
}

TASK_PRIORITY = {
    "record-copy": 0, "record-transcode": 1, "gateway-transcode": 2,
    "composite": 3, "export": 4, "detector-reserved": 5,
}
REFERENCE_TIERS = {
    "copy-8": {"streams": 8, "profile": "640x360@15", "taskType": "record-copy"},
    "copy-16": {"streams": 16, "profile": "640x360@15", "taskType": "record-copy"},
    "copy-32": {"streams": 32, "profile": "640x360@15", "taskType": "record-copy"},
}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def now_seconds() -> int:
    return int(time.time())


def canonical_json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def aws_signing_key(secret: str, date: str, region: str) -> bytes:
    date_key = hmac.new(("AWS4" + secret).encode(), date.encode(), hashlib.sha256).digest()
    region_key = hmac.new(date_key, region.encode(), hashlib.sha256).digest()
    service_key = hmac.new(region_key, b"s3", hashlib.sha256).digest()
    return hmac.new(service_key, b"aws4_request", hashlib.sha256).digest()


def require_identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ApiError(400, f"invalid_{field}", f"{field} is invalid")
    return value


def require_exact_object(value: Any, allowed: set[str], required: set[str] = set()) -> dict[str, Any]:
    if not isinstance(value, dict) or not required.issubset(value) or set(value) - allowed:
        raise ApiError(400, "invalid_request", "request fields are invalid")
    return value


class PasswordHasher:
    """Pinned libsodium Argon2id password hashing."""

    STR_BYTES = 128

    def __init__(self) -> None:
        library = os.environ.get("WEBOBS_LIBSODIUM_LIBRARY") or ctypes.util.find_library("sodium")
        if not library:
            raise RuntimeError("pinned libsodium runtime is unavailable")
        self.lib = ctypes.CDLL(library)
        if self.lib.sodium_init() < 0:
            raise RuntimeError("libsodium initialization failed")
        self.lib.crypto_pwhash_str_alg.argtypes = [
            ctypes.c_char_p, ctypes.c_char_p, ctypes.c_ulonglong,
            ctypes.c_ulonglong, ctypes.c_size_t, ctypes.c_int,
        ]
        self.lib.crypto_pwhash_str_alg.restype = ctypes.c_int
        self.lib.crypto_pwhash_str_verify.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_ulonglong]
        self.lib.crypto_pwhash_str_verify.restype = ctypes.c_int

    def hash(self, password: str) -> str:
        encoded = password.encode("utf-8")
        if len(encoded) < 16 or len(encoded) > 128:
            raise ApiError(400, "invalid_password", "password must be 16 to 128 UTF-8 bytes")
        output = ctypes.create_string_buffer(self.STR_BYTES)
        # libsodium interactive limits and Argon2id13.
        if self.lib.crypto_pwhash_str_alg(output, encoded, len(encoded), 2, 64 * 1024 * 1024, 2) != 0:
            raise RuntimeError("password hashing failed")
        return output.value.decode("ascii")

    def verify(self, encoded_hash: str, password: str) -> bool:
        encoded = password.encode("utf-8")
        if len(encoded) > 128:
            return False
        return self.lib.crypto_pwhash_str_verify(
            encoded_hash.encode("ascii"), encoded, len(encoded)) == 0


class CertificateSigner:
    def __init__(self, ca_cert: pathlib.Path, ca_key: pathlib.Path):
        self.ca_cert = ca_cert
        self.ca_key = ca_key
        if not ca_cert.is_file() or not ca_key.is_file():
            raise RuntimeError("cluster CA certificate and key are required")

    def sign(self, node_id: str, csr_pem: str) -> tuple[str, str, int]:
        if len(csr_pem) > 64 * 1024 or "BEGIN CERTIFICATE REQUEST" not in csr_pem:
            raise ApiError(400, "invalid_csr", "node CSR is invalid")
        with tempfile.TemporaryDirectory(prefix="webobs-csr-") as directory:
            root = pathlib.Path(directory)
            csr = root / "node.csr"
            cert = root / "node.crt"
            serial = secrets.token_hex(16)
            csr.write_text(csr_pem, encoding="ascii")
            command = [
                "openssl", "x509", "-req", "-in", str(csr), "-CA", str(self.ca_cert),
                "-CAkey", str(self.ca_key), "-set_serial", f"0x{serial}", "-days", "30",
                "-sha256", "-out", str(cert), "-extfile", "/dev/stdin",
            ]
            extensions = f"basicConstraints=CA:FALSE\nkeyUsage=digitalSignature\nextendedKeyUsage=clientAuth\nsubjectAltName=URI:webobs-node:{node_id}\n"
            completed = subprocess.run(command, input=extensions, text=True, capture_output=True,
                                       timeout=10, check=False)
            if completed.returncode != 0:
                raise ApiError(400, "csr_signing_failed", "node CSR could not be signed")
            return cert.read_text(encoding="ascii"), serial, now_seconds() + CERTIFICATE_SECONDS


@dataclass(frozen=True)
class Principal:
    user_id: str
    username: str
    roles: tuple[str, ...]
    permissions: frozenset[str]
    scopes: tuple[tuple[str, str], ...]

    def permits(self, permission: str, camera_id: str = "", group_id: str = "") -> bool:
        if permission not in self.permissions:
            return False
        if "admin" in self.roles or not camera_id:
            return True
        return ("camera", camera_id) in self.scopes or (group_id and ("group", group_id) in self.scopes)


class ClusterStore:
    def __init__(self, database_path: pathlib.Path, hasher: Any, signer: Any | None = None,
                 secrets_root: pathlib.Path | None = None,
                 camera_registry_path: pathlib.Path | None = None):
        self.path = database_path
        self.hasher = hasher
        self.signer = signer
        self.secrets_root = secrets_root or pathlib.Path(os.environ.get("WEBOBS_SECRETS_ROOT", "/run/secrets"))
        self.camera_registry_path = camera_registry_path or pathlib.Path(os.environ.get(
            "WEBOBS_CAMERA_DATABASE", "/config/webobs/cameras.db"))
        self.lock = threading.RLock()
        self.auth_failures: dict[str, tuple[int, int]] = {}
        database_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(database_path, check_same_thread=False, timeout=15)
        self.db.row_factory = sqlite3.Row
        with self.db:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.execute("PRAGMA foreign_keys=ON")
            self.db.executescript("""
              CREATE TABLE IF NOT EXISTS metadata(id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL);
              INSERT OR IGNORE INTO metadata(id,revision) VALUES(1,1);
              CREATE TABLE IF NOT EXISTS users(
                id TEXT PRIMARY KEY,username TEXT NOT NULL UNIQUE,password_hash TEXT NOT NULL,
                enabled INTEGER NOT NULL,created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,revision INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS user_roles(
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,role TEXT NOT NULL,
                PRIMARY KEY(user_id,role));
              CREATE TABLE IF NOT EXISTS user_scopes(
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,scope_kind TEXT NOT NULL,scope_id TEXT NOT NULL,
                PRIMARY KEY(user_id,scope_kind,scope_id));
              CREATE TABLE IF NOT EXISTS rbac_audit(
                id INTEGER PRIMARY KEY AUTOINCREMENT,event TEXT NOT NULL,actor_id TEXT NOT NULL,
                subject_id TEXT NOT NULL,result TEXT NOT NULL,created_at INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS node_enrollments(
                id TEXT PRIMARY KEY,name TEXT NOT NULL,role TEXT NOT NULL,token_hash TEXT NOT NULL UNIQUE,
                state TEXT NOT NULL,csr_pem TEXT NOT NULL,certificate_pem TEXT NOT NULL,certificate_serial TEXT NOT NULL,
                expires_at INTEGER NOT NULL,certificate_expires_at INTEGER NOT NULL,created_at INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS nodes(
                id TEXT PRIMARY KEY,name TEXT NOT NULL,role TEXT NOT NULL,status TEXT NOT NULL,
                certificate_serial TEXT NOT NULL UNIQUE,certificate_expires_at INTEGER NOT NULL,
                version TEXT NOT NULL,last_seen_at INTEGER NOT NULL,clock_offset_ms INTEGER NOT NULL,
                capabilities_json TEXT NOT NULL,revoked INTEGER NOT NULL,revision INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS storage_volumes(
                id TEXT NOT NULL,node_id TEXT NOT NULL,label TEXT NOT NULL,tier TEXT NOT NULL,state TEXT NOT NULL,
                capacity_bytes INTEGER NOT NULL,free_bytes INTEGER NOT NULL,reserve_bytes INTEGER NOT NULL,
                high_watermark REAL NOT NULL,low_watermark REAL NOT NULL,read_only INTEGER NOT NULL,
                last_scrub_at INTEGER NOT NULL,revision INTEGER NOT NULL,PRIMARY KEY(node_id,id));
              CREATE TABLE IF NOT EXISTS recording_assignments(
                camera_id TEXT NOT NULL,profile_id TEXT NOT NULL,node_id TEXT NOT NULL,generation INTEGER NOT NULL,
                state TEXT NOT NULL,lease_expires_at INTEGER NOT NULL,isolation_deadline INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,PRIMARY KEY(camera_id,profile_id));
              CREATE TABLE IF NOT EXISTS analytics_jobs(
                id TEXT PRIMARY KEY,camera_id TEXT NOT NULL,profile_id TEXT NOT NULL,kind TEXT NOT NULL,
                node_id TEXT NOT NULL,generation INTEGER NOT NULL,state TEXT NOT NULL,
                lease_expires_at INTEGER NOT NULL,model_id TEXT NOT NULL,model_sha256 TEXT NOT NULL,
                requested_resources_json TEXT NOT NULL,result_json TEXT NOT NULL,last_result_at INTEGER NOT NULL,
                last_error_code TEXT NOT NULL,revision INTEGER NOT NULL,created_at INTEGER NOT NULL);
              CREATE INDEX IF NOT EXISTS analytics_jobs_node_state ON analytics_jobs(node_id,state,created_at);
              CREATE TABLE IF NOT EXISTS analytics_media_grants(
                token_hash TEXT PRIMARY KEY,job_id TEXT NOT NULL,camera_id TEXT NOT NULL,
                profile_id TEXT NOT NULL,node_id TEXT NOT NULL,expires_at INTEGER NOT NULL,
                request_count INTEGER NOT NULL DEFAULT 0,max_requests INTEGER NOT NULL DEFAULT 60,
                revoked INTEGER NOT NULL DEFAULT 0,created_at INTEGER NOT NULL);
              CREATE INDEX IF NOT EXISTS analytics_media_grants_job ON analytics_media_grants(job_id,expires_at);
              CREATE TABLE IF NOT EXISTS resource_reports(
                node_id TEXT PRIMARY KEY,cpu_cores INTEGER NOT NULL,memory_bytes INTEGER NOT NULL,
                capabilities_json TEXT NOT NULL,reservations_json TEXT NOT NULL,rated INTEGER NOT NULL,updated_at INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS segment_locations(
                segment_id TEXT NOT NULL,node_id TEXT NOT NULL,volume_id TEXT NOT NULL,storage_key TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,sha256 TEXT NOT NULL,assignment_generation INTEGER NOT NULL,
                archive_state TEXT NOT NULL,integrity TEXT NOT NULL,created_at INTEGER NOT NULL,
                camera_id TEXT NOT NULL DEFAULT '',profile_id TEXT NOT NULL DEFAULT '',
                start_utc_ms INTEGER NOT NULL DEFAULT 0,end_utc_ms INTEGER NOT NULL DEFAULT 0,
                duration_ms INTEGER NOT NULL DEFAULT 0,kind TEXT NOT NULL DEFAULT 'continuous',
                video_codec TEXT NOT NULL DEFAULT '',audio_codec TEXT NOT NULL DEFAULT '',
                locked INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(segment_id,node_id,volume_id));
              CREATE TABLE IF NOT EXISTS archive_targets(
                id TEXT PRIMARY KEY,name TEXT NOT NULL,endpoint_authority TEXT NOT NULL,bucket TEXT NOT NULL,
                credentials_ref TEXT NOT NULL,enabled INTEGER NOT NULL,revision INTEGER NOT NULL,
                region TEXT NOT NULL DEFAULT 'us-east-1');
              CREATE TABLE IF NOT EXISTS archive_jobs(
                id TEXT PRIMARY KEY,segment_id TEXT NOT NULL,target_id TEXT NOT NULL,state TEXT NOT NULL,
                attempts INTEGER NOT NULL,next_attempt_at INTEGER NOT NULL,last_error_code TEXT NOT NULL,created_at INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS backup_jobs(
                id TEXT PRIMARY KEY,state TEXT NOT NULL,target_id TEXT NOT NULL,sha256 TEXT NOT NULL,
                created_at INTEGER NOT NULL,completed_at INTEGER NOT NULL,error_code TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS integrations(
                id TEXT PRIMARY KEY,kind TEXT NOT NULL,name TEXT NOT NULL,enabled INTEGER NOT NULL,
                config_json TEXT NOT NULL,credentials_ref TEXT NOT NULL,revision INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS external_providers(
                id TEXT PRIMARY KEY,name TEXT NOT NULL,endpoint_authority TEXT NOT NULL,path TEXT NOT NULL,
                task_types_json TEXT NOT NULL,credentials_ref TEXT NOT NULL,max_concurrent INTEGER NOT NULL,
                enabled INTEGER NOT NULL,revision INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS provider_grants(
                token_hash TEXT PRIMARY KEY,provider_id TEXT NOT NULL,task_id TEXT NOT NULL,camera_id TEXT NOT NULL,
                profile_id TEXT NOT NULL,segment_id TEXT NOT NULL,expires_at INTEGER NOT NULL,used INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS provider_tasks(
                id TEXT PRIMARY KEY,provider_id TEXT NOT NULL,task_type TEXT NOT NULL,
                camera_id TEXT NOT NULL,profile_id TEXT NOT NULL,segment_id TEXT NOT NULL,
                state TEXT NOT NULL,created_at INTEGER NOT NULL,expires_at INTEGER NOT NULL,
                media_opened_at INTEGER NOT NULL,result_code TEXT NOT NULL);
              CREATE INDEX IF NOT EXISTS nodes_status_seen ON nodes(status,last_seen_at);
              CREATE INDEX IF NOT EXISTS archive_jobs_due ON archive_jobs(state,next_attempt_at);
              CREATE INDEX IF NOT EXISTS segment_locations_segment ON segment_locations(segment_id);
              CREATE INDEX IF NOT EXISTS segment_locations_camera_time
                ON segment_locations(camera_id,start_utc_ms,end_utc_ms);
              CREATE INDEX IF NOT EXISTS provider_tasks_provider_time
                ON provider_tasks(provider_id,created_at DESC,id DESC);
            """)
            assignment_columns = {row[1] for row in self.db.execute("PRAGMA table_info(recording_assignments)")}
            if "task_type" not in assignment_columns:
                self.db.execute("ALTER TABLE recording_assignments ADD COLUMN task_type TEXT NOT NULL DEFAULT 'record-copy'")
            if "costs_json" not in assignment_columns:
                self.db.execute("ALTER TABLE recording_assignments ADD COLUMN costs_json TEXT NOT NULL DEFAULT '{}'")
            location_columns = {row[1] for row in self.db.execute("PRAGMA table_info(segment_locations)")}
            if "camera_id" not in location_columns:
                self.db.execute("ALTER TABLE segment_locations ADD COLUMN camera_id TEXT NOT NULL DEFAULT ''")
            if "profile_id" not in location_columns:
                self.db.execute("ALTER TABLE segment_locations ADD COLUMN profile_id TEXT NOT NULL DEFAULT ''")
            location_migrations = {
                "start_utc_ms": "INTEGER NOT NULL DEFAULT 0",
                "end_utc_ms": "INTEGER NOT NULL DEFAULT 0",
                "duration_ms": "INTEGER NOT NULL DEFAULT 0",
                "kind": "TEXT NOT NULL DEFAULT 'continuous'",
                "video_codec": "TEXT NOT NULL DEFAULT ''",
                "audio_codec": "TEXT NOT NULL DEFAULT ''",
                "locked": "INTEGER NOT NULL DEFAULT 0",
            }
            for name, declaration in location_migrations.items():
                if name not in location_columns:
                    self.db.execute(f"ALTER TABLE segment_locations ADD COLUMN {name} {declaration}")
            self.db.execute("CREATE INDEX IF NOT EXISTS segment_locations_camera_time "
                            "ON segment_locations(camera_id,start_utc_ms,end_utc_ms)")
            target_columns = {row[1] for row in self.db.execute("PRAGMA table_info(archive_targets)")}
            if "region" not in target_columns:
                self.db.execute("ALTER TABLE archive_targets ADD COLUMN region TEXT NOT NULL DEFAULT 'us-east-1'")
            self.db.execute("PRAGMA user_version=6")
        with contextlib.suppress(OSError):
            os.chmod(database_path, 0o600)

    def close(self) -> None:
        with self.lock:
            self.db.close()

    def revision(self) -> int:
        return int(self.db.execute("SELECT revision FROM metadata WHERE id=1").fetchone()[0])

    def _bump(self) -> int:
        self.db.execute("UPDATE metadata SET revision=revision+1 WHERE id=1")
        return self.revision()

    def _audit(self, event: str, actor: str, subject: str, result: str) -> None:
        self.db.execute("INSERT INTO rbac_audit(event,actor_id,subject_id,result,created_at) VALUES(?,?,?,?,?)",
                        (event[:64], actor[:64], subject[:64], result, now_seconds()))
        self.db.execute("DELETE FROM rbac_audit WHERE id NOT IN (SELECT id FROM rbac_audit ORDER BY id DESC LIMIT ?)",
                        (MAX_AUDIT,))

    def list_audit(self, query: dict[str, list[str]]) -> dict[str, Any]:
        if not set(query).issubset({"limit", "before"}):
            raise ApiError(400, "invalid_audit_query", "audit query contains unsupported fields")
        limit_values = query.get("limit", ["100"])
        before_values = query.get("before", [])
        if len(limit_values) != 1 or not limit_values[0].isdigit():
            raise ApiError(400, "invalid_audit_query", "audit limit is invalid")
        limit = int(limit_values[0])
        if not 1 <= limit <= MAX_PAGE or len(before_values) > 1 or \
                (before_values and (not before_values[0].isdigit() or int(before_values[0]) < 1)):
            raise ApiError(400, "invalid_audit_query", "audit pagination is invalid")
        before = int(before_values[0]) if before_values else None
        statement = "SELECT * FROM rbac_audit"
        parameters: tuple[Any, ...] = ()
        if before is not None:
            statement += " WHERE id<?"
            parameters = (before,)
        rows = self.db.execute(statement + " ORDER BY id DESC LIMIT ?", (*parameters, limit + 1)).fetchall()
        has_more = len(rows) > limit
        rows = rows[:limit]
        records = [{"id": row["id"], "event": row["event"], "actorId": row["actor_id"],
                    "subjectId": row["subject_id"], "result": row["result"],
                    "createdAt": row["created_at"]} for row in rows]
        return {"records": records, "nextBefore": rows[-1]["id"] if has_more and rows else None}

    def create_user(self, value: Any, actor: str = "legacy-admin") -> dict[str, Any]:
        value = require_exact_object(value, {"username", "password", "roles", "scopes"},
                                     {"username", "password", "roles"})
        username = value["username"]
        if not isinstance(username, str) or not USERNAME.fullmatch(username):
            raise ApiError(400, "invalid_username", "username is invalid")
        roles = value["roles"]
        if not isinstance(roles, list) or not roles or len(roles) > len(ROLE_PERMISSIONS) or any(
                role not in ROLE_PERMISSIONS for role in roles) or len(set(roles)) != len(roles):
            raise ApiError(400, "invalid_roles", "roles are invalid")
        scopes = self._validate_scopes(value.get("scopes", []))
        user_id = secrets.token_hex(16)
        password_hash = self.hasher.hash(value["password"])
        timestamp = now_seconds()
        try:
            with self.lock, self.db:
                self.db.execute("INSERT INTO users VALUES(?,?,?,?,?,?,?)",
                                (user_id, username, password_hash, 1, timestamp, timestamp, 1))
                self.db.executemany("INSERT INTO user_roles VALUES(?,?)", [(user_id, role) for role in roles])
                self.db.executemany("INSERT INTO user_scopes VALUES(?,?,?)",
                                    [(user_id, kind, identifier) for kind, identifier in scopes])
                catalog_revision = self._bump()
                self._audit("user.created", actor, user_id, "completed")
        except sqlite3.IntegrityError as error:
            raise ApiError(409, "username_exists", "username already exists") from error
        return {"id": user_id, "username": username, "enabled": True, "roles": sorted(roles),
                "scopes": [{"kind": kind, "id": identifier} for kind, identifier in scopes],
                "revision": 1, "catalogRevision": catalog_revision}

    @staticmethod
    def _validate_scopes(value: Any) -> list[tuple[str, str]]:
        if not isinstance(value, list) or len(value) > 256:
            raise ApiError(400, "invalid_scopes", "scopes are invalid")
        result: list[tuple[str, str]] = []
        for item in value:
            if not isinstance(item, dict) or set(item) != {"kind", "id"} or item["kind"] not in {"camera", "group"}:
                raise ApiError(400, "invalid_scopes", "scopes are invalid")
            result.append((item["kind"], require_identifier(item["id"], "scope_id")))
        if len(set(result)) != len(result):
            raise ApiError(400, "invalid_scopes", "scopes contain duplicates")
        return result

    def authenticate(self, username: Any, password: Any, client_key: str = "loopback",
                     timestamp: int | None = None) -> Principal | None:
        timestamp = timestamp or now_seconds()
        if not isinstance(client_key, str) or not client_key or len(client_key) > 128:
            client_key = "invalid"
        started, failures = self.auth_failures.get(client_key, (timestamp, 0))
        if timestamp - started >= 60:
            started, failures = timestamp, 0
        if failures >= 5:
            with self.lock, self.db:
                self._audit("auth.login", "anonymous", "session", "rate-limited")
            raise ApiError(429, "authentication_rate_limited", "too many authentication failures")
        if not isinstance(username, str) or not isinstance(password, str) or len(password.encode("utf-8")) > 128:
            self.auth_failures[client_key] = (started, failures + 1)
            with self.lock, self.db:
                self._audit("auth.login", "anonymous", "session", "rejected")
            return None
        with self.lock, self.db:
            row = self.db.execute("SELECT * FROM users WHERE username=? AND enabled=1", (username,)).fetchone()
            if row is None or not self.hasher.verify(row["password_hash"], password):
                self.auth_failures[client_key] = (started, failures + 1)
                self._audit("auth.login", "anonymous", "session", "rejected")
                return None
            self.auth_failures.pop(client_key, None)
            principal = self.principal(row["id"])
            self._audit("auth.login", principal.user_id, "session", "succeeded")
            return principal

    def authorize(self, username: str, permission: str, camera_id: str = "", group_id: str = "") -> dict[str, Any]:
        if permission not in PERMISSIONS:
            raise ApiError(400, "invalid_permission", "permission is invalid")
        principal: Principal | None = None
        rejection: ApiError | None = None
        with self.lock, self.db:
            row = self.db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
            if row is None:
                self._audit("auth.authorization", "anonymous", permission, "user-unknown")
                rejection = ApiError(404, "user_not_found", "user is not managed by RBAC")
            else:
                try:
                    principal = self.principal(row["id"])
                except ApiError:
                    self._audit("auth.authorization", row["id"], permission, "user-disabled")
                    rejection = ApiError(404, "user_not_found", "user is not managed by RBAC")
                if principal is not None:
                    resolved_group = group_id or self._camera_group(camera_id)
                    if not principal.permits(permission, camera_id, resolved_group):
                        self._audit("auth.authorization", principal.user_id, permission, "rejected")
                        rejection = ApiError(403, "permission_rejected",
                                             "permission or resource scope was rejected")
        if rejection is not None:
            raise rejection
        assert principal is not None
        return {"allowed": True, "userId": principal.user_id, "permission": permission}

    def _camera_group(self, camera_id: str) -> str:
        """Resolve a shared Registry group without copying its catalog into RBAC state."""
        if not camera_id or not IDENTIFIER.fullmatch(camera_id) or not self.camera_registry_path.is_absolute():
            return ""
        database: sqlite3.Connection | None = None
        try:
            database = sqlite3.connect(
                f"file:{self.camera_registry_path.as_posix()}?mode=ro", uri=True, timeout=1)
            row = database.execute("SELECT group_id FROM cameras WHERE id=?", (camera_id,)).fetchone()
        except sqlite3.Error:
            return ""
        finally:
            if database is not None:
                database.close()
        group_id = row[0] if row else ""
        return group_id if isinstance(group_id, str) and IDENTIFIER.fullmatch(group_id) else ""

    def _camera_profile_exists(self, camera_id: str, profile_id: str) -> bool:
        """Bind detector jobs to the authoritative Camera Registry.

        The cluster database deliberately does not copy Camera/Profile rows. A
        read-only lookup prevents a stale or forged job from being scheduled
        for an arbitrary identifier while keeping Registry secrets out of the
        cluster service.
        """
        if not self.camera_registry_path.is_absolute():
            return False
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(
                f"file:{self.camera_registry_path.as_posix()}?mode=ro", uri=True, timeout=1)
            return connection.execute(
                "SELECT 1 FROM cameras c JOIN stream_profiles p ON p.camera_id=c.id "
                "WHERE c.id=? AND p.id=? LIMIT 1", (camera_id, profile_id)).fetchone() is not None
        except sqlite3.Error:
            return False
        finally:
            if connection is not None:
                connection.close()

    def _analytics_worker_authorized(self, camera_id: str, profile_id: str) -> bool:
        """Return whether this Camera/Profile explicitly permits server inference.

        Detector jobs are a media-chain expansion and therefore must never be
        created merely because a caller has ``analytics.run`` or because the
        approved model is available.  The authoritative Registry policy must
        opt the stream into person analytics and either select the worker
        execution preference or explicitly permit a server fallback.  Missing
        tables, rows, or malformed values fail closed so an older/corrupt
        Registry cannot silently start a detector ingest.
        """
        if not self.camera_registry_path.is_absolute():
            return False
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(
                f"file:{self.camera_registry_path.as_posix()}?mode=ro", uri=True, timeout=1)
            row = connection.execute(
                "SELECT person_enabled, person_execution_preference, person_allow_server_fallback "
                "FROM analytics_policies WHERE camera_id=? AND profile_id=? LIMIT 1",
                (camera_id, profile_id),
            ).fetchone()
            if row is None:
                return False
            enabled, preference, fallback = row
            return bool(enabled) and (
                preference == "worker" or bool(fallback)
            )
        except (sqlite3.Error, TypeError, ValueError):
            return False
        finally:
            if connection is not None:
                connection.close()

    def principal(self, user_id: str) -> Principal:
        row = self.db.execute("SELECT * FROM users WHERE id=? AND enabled=1", (user_id,)).fetchone()
        if row is None:
            raise ApiError(403, "user_disabled", "user is disabled or missing")
        roles = tuple(sorted(item[0] for item in self.db.execute("SELECT role FROM user_roles WHERE user_id=?", (user_id,))))
        permissions = frozenset().union(*(ROLE_PERMISSIONS[role] for role in roles)) if roles else frozenset()
        scopes = tuple((item[0], item[1]) for item in self.db.execute(
            "SELECT scope_kind,scope_id FROM user_scopes WHERE user_id=? ORDER BY scope_kind,scope_id", (user_id,)))
        return Principal(user_id, row["username"], roles, permissions, scopes)

    def list_users(self) -> dict[str, Any]:
        users = []
        with self.lock:
            for row in self.db.execute("SELECT id,username,enabled,revision FROM users ORDER BY username LIMIT ?", (MAX_PAGE,)):
                principal = self.principal(row["id"]) if row["enabled"] else None
                users.append({"id": row["id"], "username": row["username"], "enabled": bool(row["enabled"]),
                              "roles": list(principal.roles) if principal else [],
                              "scopes": [{"kind": kind, "id": identifier} for kind, identifier in (principal.scopes if principal else ())],
                              "revision": row["revision"]})
        return {"users": users, "revision": self.revision()}

    def has_enabled_admin(self) -> bool:
        with self.lock:
            return self.db.execute("""SELECT 1 FROM users u
                JOIN user_roles r ON r.user_id=u.id
                WHERE u.enabled=1 AND r.role='admin' LIMIT 1""").fetchone() is not None

    def update_user(self, user_id: str, value: Any, expected_revision: int,
                    actor: str = "web-session") -> dict[str, Any]:
        require_identifier(user_id, "user_id")
        value = require_exact_object(value, {"enabled", "password", "roles", "scopes"})
        if not value:
            raise ApiError(400, "empty_patch", "at least one user field is required")
        roles = None
        scopes = None
        if "roles" in value:
            roles = value["roles"]
            if not isinstance(roles, list) or not roles or len(set(roles)) != len(roles) or any(
                    role not in ROLE_PERMISSIONS for role in roles):
                raise ApiError(400, "invalid_roles", "roles are invalid")
        if "scopes" in value:
            scopes = self._validate_scopes(value["scopes"])
        if "enabled" in value and not isinstance(value["enabled"], bool):
            raise ApiError(400, "invalid_enabled", "enabled must be a boolean")
        password_hash = self.hasher.hash(value["password"]) if "password" in value else None
        with self.lock, self.db:
            row = self.db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if row is None:
                raise ApiError(404, "user_not_found", "user was not found")
            if row["revision"] != expected_revision:
                raise ApiError(409, "revision_conflict", "user revision does not match")
            current_roles = {item[0] for item in self.db.execute(
                "SELECT role FROM user_roles WHERE user_id=?", (user_id,))}
            resulting_roles = set(roles) if roles is not None else current_roles
            resulting_enabled = value.get("enabled", bool(row["enabled"]))
            if row["enabled"] and "admin" in current_roles and (
                    not resulting_enabled or "admin" not in resulting_roles):
                remaining = self.db.execute("""
                  SELECT COUNT(DISTINCT u.id) FROM users u
                  JOIN user_roles r ON r.user_id=u.id
                  WHERE u.enabled=1 AND r.role='admin' AND u.id<>?
                """, (user_id,)).fetchone()[0]
                if remaining == 0:
                    raise ApiError(409, "last_admin", "the last enabled administrator cannot be removed")
            revision = row["revision"] + 1
            self.db.execute("UPDATE users SET enabled=?,password_hash=COALESCE(?,password_hash),updated_at=?,revision=? WHERE id=?",
                            (int(resulting_enabled), password_hash, now_seconds(), revision, user_id))
            if roles is not None:
                self.db.execute("DELETE FROM user_roles WHERE user_id=?", (user_id,))
                self.db.executemany("INSERT INTO user_roles VALUES(?,?)", [(user_id, role) for role in roles])
            if scopes is not None:
                self.db.execute("DELETE FROM user_scopes WHERE user_id=?", (user_id,))
                self.db.executemany("INSERT INTO user_scopes VALUES(?,?,?)",
                                    [(user_id, kind, identifier) for kind, identifier in scopes])
            global_revision = self._bump()
            self._audit("user.updated", actor, user_id, "completed")
        principal = self.principal(user_id) if resulting_enabled else None
        return {"id": user_id, "username": row["username"], "enabled": bool(resulting_enabled),
                "roles": list(principal.roles) if principal else [],
                "scopes": [{"kind": kind, "id": identifier} for kind, identifier in
                           (principal.scopes if principal else ())],
                "revision": revision, "catalogRevision": global_revision}

    def create_enrollment(self, value: Any) -> dict[str, Any]:
        value = require_exact_object(value, {"name", "role"}, {"name", "role"})
        name = value["name"]
        role = value["role"]
        if not isinstance(name, str) or not name.strip() or len(name) > 64 or role not in {"recorder", "worker"}:
            raise ApiError(400, "invalid_enrollment", "node name or role is invalid")
        token = secrets.token_urlsafe(32)
        enrollment_id = secrets.token_hex(16)
        timestamp = now_seconds()
        with self.lock, self.db:
            count = self.db.execute("SELECT COUNT(*) FROM nodes WHERE revoked=0").fetchone()[0]
            if count >= MAX_NODES:
                raise ApiError(409, "node_limit", "node limit reached")
            self.db.execute(
                "INSERT INTO node_enrollments VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (enrollment_id, name.strip(), role, hashlib.sha256(token.encode()).hexdigest(), "created", "", "", "",
                 timestamp + ENROLLMENT_SECONDS, 0, timestamp))
            revision = self._bump()
        return {"id": enrollment_id, "token": token, "expiresAt": timestamp + ENROLLMENT_SECONDS,
                "state": "created", "revision": revision}

    def submit_enrollment(self, value: Any) -> dict[str, Any]:
        value = require_exact_object(value, {"id", "token", "csr"}, {"id", "token", "csr"})
        enrollment_id = require_identifier(value["id"], "enrollment_id")
        token_hash = hashlib.sha256(str(value["token"]).encode()).hexdigest()
        csr = value["csr"]
        if not isinstance(csr, str) or len(csr) > 64 * 1024:
            raise ApiError(400, "invalid_csr", "node CSR is invalid")
        with self.lock, self.db:
            row = self.db.execute("SELECT * FROM node_enrollments WHERE id=?", (enrollment_id,)).fetchone()
            if row is None or not secrets.compare_digest(row["token_hash"], token_hash) or row["expires_at"] <= now_seconds():
                raise ApiError(403, "enrollment_rejected", "node enrollment was rejected")
            if row["state"] not in {"created", "submitted"}:
                raise ApiError(409, "enrollment_state", "node enrollment cannot accept a CSR")
            self.db.execute("UPDATE node_enrollments SET csr_pem=?,state='submitted' WHERE id=?", (csr, enrollment_id))
            self._bump()
        return {"id": enrollment_id, "state": "submitted"}

    def approve_enrollment(self, enrollment_id: str) -> dict[str, Any]:
        require_identifier(enrollment_id, "enrollment_id")
        if self.signer is None:
            raise ApiError(503, "cluster_ca_unavailable", "cluster CA is unavailable")
        with self.lock, self.db:
            row = self.db.execute("SELECT * FROM node_enrollments WHERE id=?", (enrollment_id,)).fetchone()
            if row is None:
                raise ApiError(404, "enrollment_not_found", "node enrollment was not found")
            if row["state"] != "submitted" or row["expires_at"] <= now_seconds():
                raise ApiError(409, "enrollment_state", "node enrollment is not ready for approval")
            node_id = secrets.token_hex(16)
            certificate, serial, expires_at = self.signer.sign(node_id, row["csr_pem"])
            timestamp = now_seconds()
            self.db.execute("UPDATE node_enrollments SET state='approved',certificate_pem=?,certificate_serial=?,certificate_expires_at=? WHERE id=?",
                            (certificate, serial, expires_at, enrollment_id))
            self.db.execute("INSERT INTO nodes VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                            (node_id, row["name"], row["role"], "enrolled", serial, expires_at,
                             "", 0, 0, "{}", 0, 1))
            revision = self._bump()
        return {"id": enrollment_id, "nodeId": node_id, "state": "approved", "revision": revision}

    def complete_enrollment(self, enrollment_id: str, token: str) -> dict[str, Any]:
        require_identifier(enrollment_id, "enrollment_id")
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self.lock, self.db:
            row = self.db.execute("SELECT * FROM node_enrollments WHERE id=?", (enrollment_id,)).fetchone()
            if row is None or not secrets.compare_digest(row["token_hash"], token_hash) or row["state"] != "approved":
                raise ApiError(403, "enrollment_rejected", "node enrollment was rejected")
            node = self.db.execute("SELECT id FROM nodes WHERE certificate_serial=?", (row["certificate_serial"],)).fetchone()
            self.db.execute("UPDATE node_enrollments SET state='completed',token_hash=? WHERE id=?",
                            (hashlib.sha256(secrets.token_bytes(32)).hexdigest(), enrollment_id))
            self._bump()
        return {"nodeId": node["id"], "certificate": row["certificate_pem"],
                "certificateExpiresAt": row["certificate_expires_at"], "renewBeforeSeconds": CERTIFICATE_RENEW_SECONDS}

    def renew_certificate(self, node_id: str, value: Any) -> dict[str, Any]:
        """Rotate a node certificate while the current mTLS identity is valid."""
        require_identifier(node_id, "node_id")
        value = require_exact_object(value, {"csr"}, {"csr"})
        if self.signer is None:
            raise ApiError(503, "cluster_ca_unavailable", "cluster CA is unavailable")
        with self.lock, self.db:
            node = self.db.execute(
                "SELECT * FROM nodes WHERE id=? AND revoked=0", (node_id,)).fetchone()
            if node is None:
                raise ApiError(403, "node_rejected", "node is missing or revoked")
            certificate, serial, expires_at = self.signer.sign(node_id, value["csr"])
            revision = node["revision"] + 1
            self.db.execute(
                "UPDATE nodes SET certificate_serial=?,certificate_expires_at=?,revision=? WHERE id=?",
                (serial, expires_at, revision, node_id))
            self._bump()
        return {"nodeId": node_id, "certificate": certificate,
                "certificateExpiresAt": expires_at,
                "renewBeforeSeconds": CERTIFICATE_RENEW_SECONDS,
                "revision": revision}

    def heartbeat(self, node_id: str, value: Any, timestamp: int | None = None) -> dict[str, Any]:
        require_identifier(node_id, "node_id")
        value = require_exact_object(value, {"version", "nodeTime", "capabilities", "volumes", "resources"},
                                     {"version", "nodeTime", "capabilities", "volumes", "resources"})
        timestamp = timestamp or now_seconds()
        node_time = value["nodeTime"]
        if not isinstance(node_time, int):
            raise ApiError(400, "invalid_node_time", "nodeTime must be an integer")
        clock_offset_ms = (node_time - timestamp) * 1000
        capabilities = value["capabilities"]
        if not isinstance(capabilities, dict) or len(canonical_json(capabilities)) > 64 * 1024:
            raise ApiError(400, "invalid_capabilities", "node capabilities are invalid")
        status = "clock-skew" if abs(clock_offset_ms) > MAX_CLOCK_SKEW_SECONDS * 1000 else "online"
        volumes = self._validate_volumes(value["volumes"])
        resources = self._validate_resources(value["resources"])
        with self.lock, self.db:
            node = self.db.execute("SELECT * FROM nodes WHERE id=? AND revoked=0", (node_id,)).fetchone()
            if node is None:
                raise ApiError(403, "node_rejected", "node is missing or revoked")
            self.db.execute("UPDATE nodes SET status=?,version=?,last_seen_at=?,clock_offset_ms=?,capabilities_json=?,revision=revision+1 WHERE id=?",
                            (status, str(value["version"])[:64], timestamp, clock_offset_ms,
                             canonical_json(capabilities), node_id))
            for volume in volumes:
                self.db.execute("""
                  INSERT INTO storage_volumes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                  ON CONFLICT(node_id,id) DO UPDATE SET
                    capacity_bytes=excluded.capacity_bytes,free_bytes=excluded.free_bytes,
                    state=CASE WHEN excluded.read_only=1 THEN 'read-only'
                               WHEN storage_volumes.state='offline' THEN 'online'
                               ELSE storage_volumes.state END,
                    read_only=excluded.read_only,revision=storage_volumes.revision+1
                """, (volume["id"], node_id, volume["label"], volume["tier"], volume["state"],
                       volume["capacityBytes"], volume["freeBytes"], volume["reserveBytes"],
                       volume["highWatermark"], volume["lowWatermark"], int(volume["readOnly"]),
                       volume.get("lastScrubAt", 0), 1))
            self.db.execute("""
              INSERT INTO resource_reports VALUES(?,?,?,?,?,?,?)
              ON CONFLICT(node_id) DO UPDATE SET cpu_cores=excluded.cpu_cores,memory_bytes=excluded.memory_bytes,
                capabilities_json=excluded.capabilities_json,reservations_json=excluded.reservations_json,
                rated=excluded.rated,updated_at=excluded.updated_at
            """, (node_id, resources["cpuCores"], resources["memoryBytes"],
                   canonical_json(resources["capabilities"]), canonical_json(resources["reservations"]),
                   int(resources["rated"]), timestamp))
            revision = self._bump()
        return {"nodeId": node_id, "status": status, "serverTime": timestamp,
                "heartbeatSeconds": HEARTBEAT_SECONDS, "revision": revision}

    @staticmethod
    def _validate_volumes(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list) or len(value) > MAX_VOLUMES:
            raise ApiError(400, "invalid_volumes", "volume inventory is invalid")
        result = []
        for volume in value:
            required = {"id", "label", "tier", "state", "capacityBytes", "freeBytes", "reserveBytes",
                        "highWatermark", "lowWatermark", "readOnly"}
            require_exact_object(volume, required | {"lastScrubAt"}, required)
            if not isinstance(volume["id"], str) or not VOLUME_ID.fullmatch(volume["id"]):
                raise ApiError(400, "invalid_volume_id", "volume id is invalid")
            if volume["tier"] not in {"hot", "warm", "archive"} or volume["state"] not in {
                    "online", "degraded", "read-only", "evacuating", "offline"}:
                raise ApiError(400, "invalid_volume_state", "volume tier or state is invalid")
            if not all(isinstance(volume[name], int) and volume[name] >= 0 for name in
                       ("capacityBytes", "freeBytes", "reserveBytes")):
                raise ApiError(400, "invalid_volume_capacity", "volume capacity is invalid")
            if volume["freeBytes"] > volume["capacityBytes"] or volume["reserveBytes"] > volume["capacityBytes"]:
                raise ApiError(400, "invalid_volume_capacity", "volume free or reserve bytes exceed capacity")
            if not (isinstance(volume["lowWatermark"], (int, float)) and
                    isinstance(volume["highWatermark"], (int, float)) and
                    0.5 <= volume["lowWatermark"] < volume["highWatermark"] <= 0.99):
                raise ApiError(400, "invalid_watermark", "volume watermarks are invalid")
            result.append(volume)
        return result

    @staticmethod
    def _validate_resources(value: Any) -> dict[str, Any]:
        required = {"cpuCores", "memoryBytes", "capabilities", "reservations", "rated"}
        require_exact_object(value, required, required)
        if not isinstance(value["cpuCores"], int) or not 1 <= value["cpuCores"] <= 4096 or \
                not isinstance(value["memoryBytes"], int) or value["memoryBytes"] < 64 * 1024 * 1024 or \
                not isinstance(value["capabilities"], dict) or not isinstance(value["reservations"], list) or \
                len(value["reservations"]) > 4096 or not isinstance(value["rated"], bool):
            raise ApiError(400, "invalid_resources", "resource report is invalid")
        for reservation in value["reservations"]:
            if not isinstance(reservation, dict) or reservation.get("taskType") not in TASK_PRIORITY or \
                    set(reservation) - {"taskType", "count", "cpuCores", "memoryBytes", "decodeSlots",
                                        "encodeSlots", "diskBytesPerSecond"}:
                raise ApiError(400, "invalid_reservations", "resource reservations are invalid")
            for field in ("count", "cpuCores", "memoryBytes", "decodeSlots", "encodeSlots", "diskBytesPerSecond"):
                if field in reservation and (not isinstance(reservation[field], (int, float)) or
                                             isinstance(reservation[field], bool) or reservation[field] < 0):
                    raise ApiError(400, "invalid_reservations", "resource reservation costs are invalid")
        return value

    def list_nodes(self, timestamp: int | None = None) -> dict[str, Any]:
        timestamp = timestamp or now_seconds()
        with self.lock, self.db:
            self.db.execute("UPDATE nodes SET status='offline' WHERE revoked=0 AND last_seen_at>0 AND last_seen_at<?",
                            (timestamp - NODE_UNHEALTHY_SECONDS,))
            nodes = [{
                "id": row["id"], "name": row["name"], "role": row["role"],
                "status": "revoked" if row["revoked"] else row["status"], "version": row["version"],
                "lastSeenAt": row["last_seen_at"], "clockOffsetMs": row["clock_offset_ms"],
                "certificateExpiresAt": row["certificate_expires_at"], "revision": row["revision"],
            } for row in self.db.execute("SELECT * FROM nodes ORDER BY name LIMIT ?", (MAX_PAGE,))]
        return {"nodes": nodes, "revision": self.revision()}

    def revoke_node(self, node_id: str, expected_revision: int) -> dict[str, Any]:
        require_identifier(node_id, "node_id")
        with self.lock, self.db:
            row = self.db.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
            if row is None:
                raise ApiError(404, "node_not_found", "node was not found")
            if row["revision"] != expected_revision:
                raise ApiError(409, "revision_conflict", "node revision does not match")
            if row["revoked"]:
                return {"id": node_id, "state": "revoked", "revision": row["revision"]}
            revision = row["revision"] + 1
            self.db.execute("UPDATE nodes SET revoked=1,status='revoked',revision=? WHERE id=?", (revision, node_id))
            self.db.execute("UPDATE recording_assignments SET state='revoked',lease_expires_at=0 WHERE node_id=?", (node_id,))
            self._bump()
            self._audit("node.revoked", "web-session", node_id, "completed")
        return {"id": node_id, "state": "revoked", "revision": revision}

    def assign(self, camera_id: str, profile_id: str, node_id: str = "",
               task_type: str = "record-copy", costs: Any = None,
               timestamp: int | None = None) -> dict[str, Any]:
        for value, field in ((camera_id, "camera_id"), (profile_id, "profile_id")):
            require_identifier(value, field)
        if node_id:
            require_identifier(node_id, "node_id")
        if task_type not in TASK_PRIORITY:
            raise ApiError(400, "invalid_task_type", "task type is invalid")
        costs = costs if costs is not None else {}
        require_exact_object(costs, {"cpuCores", "memoryBytes", "decodeSlots", "encodeSlots", "diskBytesPerSecond"})
        normalized_costs = {name: costs.get(name, 0) for name in
                            ("cpuCores", "memoryBytes", "decodeSlots", "encodeSlots", "diskBytesPerSecond")}
        for field, value in normalized_costs.items():
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
                raise ApiError(400, "invalid_task_cost", f"{field} cost is invalid")
        timestamp = timestamp or now_seconds()
        with self.lock, self.db:
            node_id = self._select_node(camera_id, profile_id, task_type, normalized_costs, timestamp, node_id)
            node = self.db.execute("SELECT * FROM nodes WHERE id=? AND revoked=0 AND status='online'", (node_id,)).fetchone()
            if node is None or abs(node["clock_offset_ms"]) > MAX_CLOCK_SKEW_SECONDS * 1000:
                raise ApiError(409, "node_not_eligible", "node is not eligible for recording")
            current = self.db.execute("SELECT * FROM recording_assignments WHERE camera_id=? AND profile_id=?",
                                      (camera_id, profile_id)).fetchone()
            if current is not None and current["node_id"] != node_id and current["isolation_deadline"] > timestamp:
                raise ApiError(409, "assignment_isolation", "existing recorder isolation deadline has not elapsed")
            generation = (current["generation"] + 1) if current else 1
            lease_expires = timestamp + LEASE_SECONDS
            isolation_deadline = lease_expires + ISOLATION_GRACE_SECONDS
            self.db.execute("""
              INSERT INTO recording_assignments(camera_id,profile_id,node_id,generation,state,lease_expires_at,
                isolation_deadline,updated_at,task_type,costs_json) VALUES(?,?,?,?,?,?,?,?,?,?)
              ON CONFLICT(camera_id,profile_id) DO UPDATE SET node_id=excluded.node_id,generation=excluded.generation,
                state=excluded.state,lease_expires_at=excluded.lease_expires_at,
                isolation_deadline=excluded.isolation_deadline,updated_at=excluded.updated_at,
                task_type=excluded.task_type,costs_json=excluded.costs_json
            """, (camera_id, profile_id, node_id, generation, "active", lease_expires, isolation_deadline,
                  timestamp, task_type, canonical_json(normalized_costs)))
            revision = self._bump()
        return {"cameraId": camera_id, "profileId": profile_id, "nodeId": node_id,
                "generation": generation, "leaseExpiresAt": lease_expires,
                "isolationDeadline": isolation_deadline, "taskType": task_type,
                "costs": normalized_costs, "revision": revision}

    def _select_node(self, stable_key: str, profile_id: str, task_type: str, costs: dict[str, Any], timestamp: int,
                     required_node: str = "") -> str:
        candidates: list[tuple[float, str]] = []
        rows = self.db.execute("""
          SELECT n.*,r.cpu_cores,r.memory_bytes,r.capabilities_json AS resources_capabilities,
                 r.reservations_json,r.rated
          FROM nodes n JOIN resource_reports r ON r.node_id=n.id
          WHERE n.revoked=0 AND n.status='online' AND (? <> 'detector-reserved' OR n.role='worker')
        """, (task_type,)).fetchall()
        for row in rows:
            if required_node and row["id"] != required_node:
                continue
            if abs(row["clock_offset_ms"]) > MAX_CLOCK_SKEW_SECONDS * 1000 or \
                    timestamp - row["last_seen_at"] > NODE_UNHEALTHY_SECONDS:
                continue
            capabilities = json.loads(row["resources_capabilities"])
            reservations = json.loads(row["reservations_json"])
            reported = {field: 0.0 for field in costs}
            for reservation in reservations:
                for field in reported:
                    reported[field] += float(reservation.get(field, 0))
            scheduled = {field: 0.0 for field in costs}
            assignments = self.db.execute(
                """SELECT costs_json FROM recording_assignments
                   WHERE node_id=? AND state='active' AND isolation_deadline>?
                     AND NOT (camera_id=? AND profile_id=?)""",
                (row["id"], timestamp, stable_key, profile_id),
            ).fetchall()
            for assignment in assignments:
                with contextlib.suppress(json.JSONDecodeError, TypeError, ValueError):
                    reservation = json.loads(assignment["costs_json"])
                    for field in scheduled:
                        scheduled[field] += float(reservation.get(field, 0))
            detector_jobs = self.db.execute(
                "SELECT requested_resources_json FROM analytics_jobs WHERE node_id=? AND state='running' AND lease_expires_at>?",
                (row["id"], timestamp)).fetchall()
            for job in detector_jobs:
                with contextlib.suppress(json.JSONDecodeError, TypeError, ValueError):
                    reservation = json.loads(job["requested_resources_json"])
                    for field in scheduled:
                        scheduled[field] += float(reservation.get(field, 0))
            used = {field: max(reported[field], scheduled[field]) for field in costs}
            conservative = 1.0 if row["rated"] else 0.25
            limits = {
                "cpuCores": row["cpu_cores"] * conservative,
                "memoryBytes": row["memory_bytes"] * conservative,
                "decodeSlots": capabilities.get("decodeSlots", 0) if row["rated"] else 0,
                "encodeSlots": capabilities.get("encodeSlots", 0) if row["rated"] else 0,
                "diskBytesPerSecond": capabilities.get("diskBytesPerSecond", 0) * conservative,
            }
            if any(used[field] + float(costs[field]) > float(limits[field]) for field in costs):
                continue
            volumes = self.db.execute("SELECT free_bytes,reserve_bytes,state,read_only FROM storage_volumes WHERE node_id=?",
                                      (row["id"],)).fetchall()
            usable = sum(max(0, volume["free_bytes"] - volume["reserve_bytes"]) for volume in volumes
                         if volume["state"] == "online" and not volume["read_only"])
            if task_type.startswith("record-") and usable <= 0:
                continue
            stable = int(hashlib.sha256(f"{stable_key}\0{row['id']}".encode()).hexdigest()[:12], 16) / float(1 << 48)
            score = usable / max(1, 1 << 30) + stable
            candidates.append((score, row["id"]))
        if not candidates:
            if required_node:
                raise ApiError(409, "node_not_eligible",
                               "node is not eligible or lacks declared capacity; CPU fallback was not started")
            raise ApiError(409, "resource_capacity_exhausted",
                           "no eligible node has the declared task capacity; CPU fallback was not started")
        return max(candidates)[1]

    def renew(self, node_id: str, value: Any, timestamp: int | None = None) -> dict[str, Any]:
        value = require_exact_object(value, {"cameraId", "profileId", "generation"},
                                     {"cameraId", "profileId", "generation"})
        timestamp = timestamp or now_seconds()
        camera_id = require_identifier(value["cameraId"], "camera_id")
        profile_id = require_identifier(value["profileId"], "profile_id")
        generation = value["generation"]
        if not isinstance(generation, int) or generation < 1:
            raise ApiError(400, "invalid_generation", "assignment generation is invalid")
        with self.lock, self.db:
            row = self.db.execute("SELECT * FROM recording_assignments WHERE camera_id=? AND profile_id=?",
                                  (camera_id, profile_id)).fetchone()
            if row is None or row["node_id"] != node_id or row["generation"] != generation or \
                    row["state"] != "active":
                raise ApiError(409, "stale_assignment", "assignment is missing, moved, or stale")
            lease_expires = timestamp + LEASE_SECONDS
            isolation_deadline = lease_expires + ISOLATION_GRACE_SECONDS
            self.db.execute("UPDATE recording_assignments SET lease_expires_at=?,isolation_deadline=?,updated_at=? WHERE camera_id=? AND profile_id=?",
                            (lease_expires, isolation_deadline, timestamp, camera_id, profile_id))
        return {"leaseExpiresAt": lease_expires, "isolationDeadline": isolation_deadline,
                "renewAfterSeconds": LEASE_RENEW_SECONDS}

    def create_analytics_job(self, value: Any, timestamp: int | None = None) -> dict[str, Any]:
        """Queue an explicitly requested detector job without touching recording ownership."""
        value = require_exact_object(value, {"cameraId", "profileId", "kind", "modelId", "modelSha256", "requestedResources", "nodeId"},
                                     {"cameraId", "profileId", "kind"})
        camera_id = require_identifier(value["cameraId"], "camera_id")
        profile_id = require_identifier(value["profileId"], "profile_id")
        if value["kind"] != "person":
            raise ApiError(400, "invalid_analytics_kind", "only person detector jobs are supported")
        if not self._camera_profile_exists(camera_id, profile_id):
            raise ApiError(404, "camera_profile_not_found", "the detector Camera/Profile is not registered")
        model_id = value.get("modelId", ANALYTICS_MODEL_ID)
        model_sha = value.get("modelSha256", "")
        if model_id != ANALYTICS_MODEL_ID or model_sha != ANALYTICS_MODEL_SHA256:
            raise ApiError(400, "invalid_analytics_model", "model is not approved")
        if not self._analytics_worker_authorized(camera_id, profile_id):
            raise ApiError(409, "analytics_not_authorized",
                           "server detector execution is not authorized for this Camera/Profile")
        resources = value.get("requestedResources", {"cpuCores": .5, "memoryBytes": 128 * 1024 * 1024,
                                                        "decodeSlots": 0, "encodeSlots": 0, "diskBytesPerSecond": 0})
        require_exact_object(resources, {"cpuCores", "memoryBytes", "decodeSlots", "encodeSlots", "diskBytesPerSecond"})
        if any(isinstance(resources.get(field), bool) or not isinstance(resources.get(field), (int, float)) or resources[field] < 0
               for field in ("cpuCores", "memoryBytes", "decodeSlots", "encodeSlots", "diskBytesPerSecond")):
            raise ApiError(400, "invalid_analytics_resources", "requested resources are invalid")
        timestamp = timestamp or now_seconds()
        node_id = value.get("nodeId", "")
        with self.lock, self.db:
            node_id = self._select_node(camera_id, profile_id, "detector-reserved", resources, timestamp, node_id)
            current = self.db.execute("SELECT MAX(generation) FROM analytics_jobs WHERE camera_id=? AND profile_id=?",
                                      (camera_id, profile_id)).fetchone()[0] or 0
            job_id = secrets.token_hex(16)
            self.db.execute("""INSERT INTO analytics_jobs
                (id,camera_id,profile_id,kind,node_id,generation,state,lease_expires_at,model_id,model_sha256,
                 requested_resources_json,result_json,last_result_at,last_error_code,revision,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (job_id, camera_id, profile_id, "person", node_id, int(current) + 1, "queued", 0,
                 model_id, model_sha, canonical_json(resources), "{}", 0, "", 1, timestamp))
            revision = self._bump()
            self._audit("analytics.job.created", "web-session", job_id, "queued")
        return {"jobId": job_id, "cameraId": camera_id, "profileId": profile_id, "kind": "person",
                "nodeId": node_id, "generation": int(current) + 1, "state": "queued", "leaseExpiresAt": 0,
                "modelId": model_id, "modelSha256": model_sha, "lastResultAt": None, "lastErrorCode": None,
                "revision": revision}

    def _analytics_media_source(self) -> tuple[str, int, str] | None:
        """Return the explicitly configured loopback frame source.

        The controller never resolves Camera URLs for detector jobs.  A
        recorder/gateway may expose one bounded RGBA frame at a time through a
        loopback HTTP endpoint.  Requiring a loopback authority and a fixed
        path prevents a job from turning this service into an SSRF proxy.
        """
        authority = os.environ.get("WEBOBS_ANALYTICS_MEDIA_ENDPOINT", "")
        try:
            parsed = urlsplit(authority)
            if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password or \
                    parsed.query or parsed.fragment or not parsed.hostname or parsed.path in {"", "/"} or \
                    "\r" in parsed.path or "\n" in parsed.path or any(part == ".." for part in parsed.path.split("/")):
                return None
            if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
                return None
            return parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), parsed.path
        except ValueError:
            return None

    @staticmethod
    def _validate_analytics_frame(value: Any) -> dict[str, Any]:
        """Validate the private one-frame JSON protocol without persisting it."""
        import base64
        if not isinstance(value, dict) or set(value) - {"width", "height", "rgbaBase64", "capturedAt"} or \
                not {"width", "height", "rgbaBase64"}.issubset(value):
            raise ApiError(502, "analytics_frame_invalid", "analytics frame is invalid")
        width, height, encoded = value["width"], value["height"], value["rgbaBase64"]
        if isinstance(width, bool) or not isinstance(width, int) or not 2 <= width <= 160 or \
                isinstance(height, bool) or not isinstance(height, int) or not 2 <= height <= 90 or \
                not isinstance(encoded, str) or len(encoded) > MAX_ANALYTICS_FRAME_BYTES * 2:
            raise ApiError(502, "analytics_frame_invalid", "analytics frame dimensions are invalid")
        try:
            rgba = base64.b64decode(encoded.encode("ascii"), validate=True)
        except (ValueError, UnicodeEncodeError):
            raise ApiError(502, "analytics_frame_invalid", "analytics frame encoding is invalid") from None
        if len(rgba) != width * height * 4 or len(rgba) > MAX_ANALYTICS_FRAME_BYTES:
            raise ApiError(502, "analytics_frame_invalid", "analytics frame size is invalid")
        captured_at = value.get("capturedAt", now_seconds() * 1000)
        if isinstance(captured_at, bool) or not isinstance(captured_at, int) or \
                abs(now_seconds() * 1000 - captured_at) > 300_000:
            raise ApiError(502, "analytics_frame_invalid", "analytics frame timestamp is invalid")
        return {"width": width, "height": height, "rgbaBase64": encoded, "capturedAt": captured_at}

    def consume_analytics_media_frame(self, node_id: str, job_id: str, token: str) -> dict[str, Any]:
        """Consume one bounded frame from an approved, short-lived Worker grant.

        The grant is reusable for at most 60 requests/seconds and is revoked
        as soon as its analytics job completes.  Only the mTLS node identity
        and exact job binding are trusted; the client cannot supply a URL.
        """
        import http.client
        require_identifier(node_id, "node_id")
        require_identifier(job_id, "job_id")
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token):
            raise ApiError(401, "analytics_grant_rejected", "analytics media grant was rejected")
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        current = now_seconds()
        with self.lock:
            grant = self.db.execute(
                "SELECT * FROM analytics_media_grants WHERE token_hash=? AND job_id=?",
                (token_hash, job_id)).fetchone()
            job = self.db.execute("SELECT * FROM analytics_jobs WHERE id=?", (job_id,)).fetchone()
            if grant is None or job is None or grant["node_id"] != node_id or job["node_id"] != node_id or \
                    job["state"] != "running" or job["generation"] <= 0 or grant["revoked"] or \
                    grant["expires_at"] <= current or grant["request_count"] >= grant["max_requests"] or \
                    job["lease_expires_at"] < current:
                raise ApiError(401, "analytics_grant_rejected", "analytics media grant was rejected")
        source = self._analytics_media_source()
        if source is None:
            raise ApiError(503, "analytics_media_unavailable", "no approved detector media source is configured")
        host, port, path = source
        headers = {
            "Accept": "application/vnd.webobs.analytics-frame+json",
            "X-WebObs-Analytics-Job": job_id,
            "X-WebObs-Analytics-Camera": job["camera_id"],
            "X-WebObs-Analytics-Profile": job["profile_id"],
            "X-WebObs-Analytics-Grant": token,
        }
        connection: http.client.HTTPConnection | http.client.HTTPSConnection
        if os.environ.get("WEBOBS_ANALYTICS_MEDIA_ENDPOINT", "").startswith("https://"):
            context = ssl.create_default_context()
            connection = http.client.HTTPSConnection(host, port, context=context, timeout=3)
        else:
            connection = http.client.HTTPConnection(host, port, timeout=3)
        try:
            connection.request("GET", path, headers=headers)
            response = connection.getresponse()
            if response.getheader("Location") or response.status != 200 or \
                    response.getheader("Content-Type", "").split(";", 1)[0].lower() != "application/json":
                raise ApiError(503, "analytics_media_unavailable", "detector media source rejected the frame request")
            body = response.read(MAX_BODY + 1)
            if len(body) > MAX_BODY:
                raise ApiError(502, "analytics_frame_invalid", "analytics frame response exceeded one MiB")
            try:
                value = json.loads(body)
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise ApiError(502, "analytics_frame_invalid", "analytics frame response is invalid") from None
        except ApiError:
            raise
        except (OSError, ssl.SSLError, http.client.HTTPException):
            raise ApiError(503, "analytics_media_unavailable", "detector media source is unavailable") from None
        finally:
            connection.close()
        frame = self._validate_analytics_frame(value)
        # Count only a successfully validated frame.  A simultaneous result or
        # revocation still wins the compare-and-update below.
        with self.lock, self.db:
            updated = self.db.execute(
                "UPDATE analytics_media_grants SET request_count=request_count+1 "
                "WHERE token_hash=? AND job_id=? AND revoked=0 AND expires_at>? AND request_count<max_requests",
                (token_hash, job_id, current)).rowcount
            if updated != 1:
                raise ApiError(401, "analytics_grant_rejected", "analytics media grant was revoked")
        # Keep the token out of the returned frame and any persisted metadata.
        frame["grantExpiresAt"] = grant["expires_at"]
        frame["remainingRequests"] = max(0, grant["max_requests"] - grant["request_count"] - 1)
        return frame

    def list_analytics_jobs(self) -> dict[str, Any]:
        with self.lock, self.db:
            self.db.execute("DELETE FROM analytics_media_grants WHERE expires_at<=? OR revoked=1", (now_seconds(),))
            rows = self.db.execute("SELECT * FROM analytics_jobs ORDER BY created_at DESC,id DESC LIMIT ?", (MAX_PAGE,)).fetchall()
        return {"jobs": [{"jobId": row["id"], "cameraId": row["camera_id"], "profileId": row["profile_id"],
                          "kind": row["kind"], "nodeId": row["node_id"], "generation": row["generation"],
                          "state": row["state"], "leaseExpiresAt": row["lease_expires_at"], "modelId": row["model_id"],
                          "modelSha256": row["model_sha256"], "lastResultAt": row["last_result_at"] or None,
                          "lastErrorCode": row["last_error_code"] or None, "revision": row["revision"]} for row in rows],
                "revision": self.revision()}

    def claim_analytics_job(self, node_id: str, timestamp: int | None = None) -> dict[str, Any]:
        require_identifier(node_id, "node_id")
        timestamp = timestamp or now_seconds()
        with self.lock, self.db:
            node = self.db.execute("SELECT role,status,revoked,clock_offset_ms FROM nodes WHERE id=?", (node_id,)).fetchone()
            if node is None or node["role"] != "worker" or node["status"] != "online" or node["revoked"] or \
                    abs(node["clock_offset_ms"]) > MAX_CLOCK_SKEW_SECONDS * 1000:
                raise ApiError(409, "node_not_eligible", "only a healthy worker node may claim detector jobs")
            self.db.execute("DELETE FROM analytics_media_grants WHERE expires_at<=? OR revoked=1", (timestamp,))
            row = self.db.execute("SELECT * FROM analytics_jobs WHERE node_id=? AND state='queued' ORDER BY created_at,id LIMIT 1",
                                  (node_id,)).fetchone()
            if row is None:
                return {"job": None}
            lease = timestamp + LEASE_SECONDS
            self.db.execute("UPDATE analytics_jobs SET state='running',lease_expires_at=?,revision=revision+1 WHERE id=? AND state='queued'",
                            (lease, row["id"]))
            token = secrets.token_urlsafe(48)
            grant_expires = timestamp + ANALYTICS_MEDIA_GRANT_SECONDS
            self.db.execute("INSERT INTO analytics_media_grants(token_hash,job_id,camera_id,profile_id,node_id,expires_at,request_count,max_requests,revoked,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                            (hashlib.sha256(token.encode()).hexdigest(), row["id"], row["camera_id"], row["profile_id"],
                             node_id, grant_expires, 0, MAX_ANALYTICS_FRAME_REQUESTS, 0, timestamp))
            return {"job": {"jobId": row["id"], "cameraId": row["camera_id"], "profileId": row["profile_id"],
                             "kind": row["kind"], "nodeId": row["node_id"], "generation": row["generation"],
                             "leaseExpiresAt": lease, "modelId": row["model_id"], "modelSha256": row["model_sha256"],
                             "requestedResources": json.loads(row["requested_resources_json"]),
                             "mediaGrant": {"method": "GET", "path": f"/internal/v1/analytics/jobs/{row['id']}/frame",
                                             "token": token, "expiresAt": grant_expires,
                                             "maxRequests": MAX_ANALYTICS_FRAME_REQUESTS}}}

    def renew_analytics_job(self, node_id: str, value: Any, timestamp: int | None = None) -> dict[str, Any]:
        value = require_exact_object(value, {"jobId", "generation"}, {"jobId", "generation"})
        job_id = require_identifier(value["jobId"], "job_id")
        generation = value["generation"]
        if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
            raise ApiError(400, "invalid_generation", "analytics generation is invalid")
        timestamp = timestamp or now_seconds()
        with self.lock, self.db:
            row = self.db.execute("SELECT * FROM analytics_jobs WHERE id=?", (job_id,)).fetchone()
            if row is None or row["node_id"] != node_id or row["generation"] != generation or row["state"] != "running" or row["lease_expires_at"] < timestamp:
                raise ApiError(409, "stale_analytics_job", "analytics job lease is stale")
            lease = timestamp + LEASE_SECONDS
            self.db.execute("UPDATE analytics_jobs SET lease_expires_at=?,revision=revision+1 WHERE id=?", (lease, job_id))
            self.db.execute("UPDATE analytics_media_grants SET expires_at=? WHERE job_id=? AND node_id=? AND revoked=0 AND expires_at>?",
                            (timestamp + ANALYTICS_MEDIA_GRANT_SECONDS, job_id, node_id, timestamp))
        return {"jobId": job_id, "generation": generation, "leaseExpiresAt": lease, "renewAfterSeconds": LEASE_RENEW_SECONDS}

    def report_analytics_job_result(self, node_id: str, value: Any, timestamp: int | None = None) -> dict[str, Any]:
        value = require_exact_object(value, {"jobId", "generation", "state", "resultCode", "signals", "modelSha256"},
                                     {"jobId", "generation", "state", "resultCode"})
        job_id = require_identifier(value["jobId"], "job_id")
        generation = value["generation"]
        state = value["state"]
        result_code = value.get("resultCode", "")
        signals = value.get("signals", [])
        model_sha = value.get("modelSha256", "")
        timestamp = timestamp or now_seconds()
        if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1 or state not in {"completed", "failed"} or \
                not isinstance(result_code, str) or len(result_code) > 64 or not re.fullmatch(r"[A-Za-z0-9._-]*", result_code) or \
                not isinstance(signals, list) or len(signals) > 32 or \
                (model_sha and (not isinstance(model_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", model_sha))):
            raise ApiError(400, "invalid_analytics_result", "analytics job result is invalid")
        safe_signals = []
        for signal in signals:
            if not isinstance(signal, dict) or signal.get("kind") != "person":
                raise ApiError(400, "invalid_analytics_result", "only person signals are accepted")
            confidence = signal.get("confidence")
            boxes = signal.get("boxes", [])
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1 or \
                    not isinstance(boxes, list) or len(boxes) > 16:
                raise ApiError(400, "invalid_analytics_result", "analytics signal values are invalid")
            safe_boxes = []
            for box in boxes:
                if not isinstance(box, dict):
                    raise ApiError(400, "invalid_analytics_result", "analytics box is invalid")
                safe = {name: box.get(name) for name in ("x", "y", "width", "height")}
                if any(isinstance(item, bool) or not isinstance(item, (int, float)) or not 0 <= item <= 1 for item in safe.values()) or \
                        safe["x"] + safe["width"] > 1 or safe["y"] + safe["height"] > 1:
                    raise ApiError(400, "invalid_analytics_result", "analytics box is out of range")
                safe_boxes.append(safe)
            occurred_at = signal.get("occurredAt", timestamp * 1000)
            if isinstance(occurred_at, bool) or not isinstance(occurred_at, int) or \
                    abs(timestamp * 1000 - occurred_at) > 300_000:
                raise ApiError(400, "invalid_analytics_result", "analytics signal timestamp is invalid")
            safe_signals.append({"kind": "person", "confidence": float(confidence), "boxes": safe_boxes,
                                 "occurredAt": occurred_at})
        with self.lock, self.db:
            row = self.db.execute("SELECT * FROM analytics_jobs WHERE id=?", (job_id,)).fetchone()
            if row is None or row["node_id"] != node_id or row["generation"] != generation or row["state"] != "running" or row["lease_expires_at"] < timestamp:
                raise ApiError(409, "stale_analytics_job", "analytics job lease is stale")
            if signals and (not model_sha or model_sha != row["model_sha256"]):
                raise ApiError(400, "invalid_analytics_result", "analytics model digest does not match the job")
            self.db.execute("UPDATE analytics_jobs SET state=?,lease_expires_at=0,result_json=?,last_result_at=?,last_error_code=?,revision=revision+1 WHERE id=?",
                            (state, canonical_json({"signals": safe_signals}), timestamp, result_code if state == "failed" else "", job_id))
            self.db.execute("UPDATE analytics_media_grants SET revoked=1 WHERE job_id=?", (job_id,))
            revision = self._bump()
            self._audit("analytics.job.result", node_id, job_id, state)
        return {"jobId": job_id, "state": state, "resultCode": result_code, "acceptedSignals": len(safe_signals), "revision": revision}

    def assignments_for(self, node_id: str) -> dict[str, Any]:
        require_identifier(node_id, "node_id")
        rows = self.db.execute("SELECT * FROM recording_assignments WHERE node_id=? ORDER BY camera_id,profile_id",
                               (node_id,)).fetchall()
        volumes = self.db.execute("SELECT * FROM storage_volumes WHERE node_id=? ORDER BY id",
                                  (node_id,)).fetchall()
        return {"assignments": [{"cameraId": row["camera_id"], "profileId": row["profile_id"],
                                  "nodeId": row["node_id"], "generation": row["generation"],
                                  "state": row["state"], "leaseExpiresAt": row["lease_expires_at"],
                                  "isolationDeadline": row["isolation_deadline"],
                                  "taskType": row["task_type"],
                                  "costs": json.loads(row["costs_json"])} for row in rows],
                "volumes": [{"id": row["id"], "label": row["label"], "tier": row["tier"],
                             "state": row["state"], "reserveBytes": row["reserve_bytes"],
                             "highWatermark": row["high_watermark"],
                             "lowWatermark": row["low_watermark"]} for row in volumes],
                "revision": self.revision()}

    def report_job_result(self, node_id: str, value: Any,
                          timestamp: int | None = None) -> dict[str, Any]:
        value = require_exact_object(
            value,
            {"cameraId", "profileId", "generation", "state", "resultCode"},
            {"cameraId", "profileId", "generation", "state"},
        )
        camera_id = require_identifier(value["cameraId"], "camera_id")
        profile_id = require_identifier(value["profileId"], "profile_id")
        generation = value["generation"]
        state = value["state"]
        result_code = value.get("resultCode", "")
        if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
            raise ApiError(400, "invalid_generation", "assignment generation is invalid")
        if state not in {"completed", "failed"} or \
                (state == "completed" and result_code != "") or \
                (state == "failed" and (not isinstance(result_code, str) or
                                         not IDENTIFIER.fullmatch(result_code))):
            raise ApiError(400, "invalid_job_result", "job result is invalid")
        timestamp = timestamp or now_seconds()
        with self.lock, self.db:
            row = self.db.execute(
                "SELECT * FROM recording_assignments WHERE camera_id=? AND profile_id=?",
                (camera_id, profile_id),
            ).fetchone()
            if row is None or row["node_id"] != node_id or row["generation"] != generation or \
                    row["state"] != "active":
                raise ApiError(409, "stale_assignment", "assignment is missing, moved, or stale")
            self.db.execute(
                """UPDATE recording_assignments
                   SET state=?,lease_expires_at=0,isolation_deadline=0,updated_at=?
                   WHERE camera_id=? AND profile_id=?""",
                (state, timestamp, camera_id, profile_id),
            )
            revision = self._bump()
            subject = hashlib.sha256(f"{camera_id}\0{profile_id}".encode()).hexdigest()[:32]
            self._audit("node.job.result", node_id, subject, state)
        return {"cameraId": camera_id, "profileId": profile_id, "nodeId": node_id,
                "generation": generation, "taskType": row["task_type"], "state": state,
                "resultCode": result_code, "revision": revision}

    def accept_catalog(self, node_id: str, value: Any) -> dict[str, Any]:
        value = require_exact_object(value, {"segments"}, {"segments"})
        segments = value["segments"]
        if not isinstance(segments, list) or len(segments) > 256:
            raise ApiError(400, "invalid_catalog_batch", "catalog batch is invalid")
        accepted = 0
        conflicts = 0
        with self.lock, self.db:
            for segment in segments:
                required = {"segmentId", "cameraId", "profileId", "volumeId", "storageKey",
                            "sizeBytes", "sha256", "generation", "archiveState", "integrity"}
                metadata = {"startUtcMs", "endUtcMs", "durationMs", "kind", "videoCodec",
                            "audioCodec", "locked"}
                require_exact_object(segment, required | metadata, required)
                segment_id = require_identifier(segment["segmentId"], "segment_id")
                camera_id = require_identifier(segment["cameraId"], "camera_id")
                profile_id = require_identifier(segment["profileId"], "profile_id")
                volume_id = segment["volumeId"]
                if not isinstance(volume_id, str) or not VOLUME_ID.fullmatch(volume_id):
                    raise ApiError(400, "invalid_volume_id", "volume_id is invalid")
                size_bytes = segment["sizeBytes"]
                generation = segment["generation"]
                if not isinstance(size_bytes, int) or isinstance(size_bytes, bool) or not 0 <= size_bytes <= (1 << 46) or \
                        not isinstance(generation, int) or isinstance(generation, bool) or generation < 0:
                    raise ApiError(400, "invalid_segment_metadata", "segment size or generation is invalid")
                start_ms = segment.get("startUtcMs", 0)
                end_ms = segment.get("endUtcMs", 0)
                duration_ms = segment.get("durationMs", max(0, end_ms - start_ms)
                                          if isinstance(start_ms, int) and isinstance(end_ms, int) else 0)
                kind = segment.get("kind", "continuous")
                video_codec = segment.get("videoCodec", "")
                audio_codec = segment.get("audioCodec", "")
                locked = segment.get("locked", False)
                if any(not isinstance(item, int) or isinstance(item, bool) or item < 0 or item >= (1 << 63)
                       for item in (start_ms, end_ms, duration_ms)) or \
                        (start_ms and (end_ms <= start_ms or duration_ms != end_ms - start_ms)) or \
                        kind not in {"continuous", "event", "pre-event", "manual", "recovered", "orphan"} or \
                        not isinstance(video_codec, str) or len(video_codec) > 32 or \
                        not isinstance(audio_codec, str) or len(audio_codec) > 32 or not isinstance(locked, bool):
                    raise ApiError(400, "invalid_segment_metadata", "segment timeline metadata is invalid")
                assignment = self.db.execute(
                    "SELECT * FROM recording_assignments WHERE camera_id=? AND profile_id=?",
                    (camera_id, profile_id)).fetchone()
                integrity = segment["integrity"]
                if not isinstance(integrity, str) or not IDENTIFIER.fullmatch(integrity):
                    raise ApiError(400, "invalid_segment_integrity", "segment integrity is invalid")
                archive_state = segment["archiveState"]
                if not isinstance(archive_state, str) or not IDENTIFIER.fullmatch(archive_state):
                    raise ApiError(400, "invalid_archive_state", "segment archive state is invalid")
                if assignment is None or assignment["node_id"] != node_id or assignment["generation"] != generation:
                    integrity = "conflict"
                    conflicts += 1
                digest = segment["sha256"]
                if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                    raise ApiError(400, "invalid_segment_hash", "segment hash is invalid")
                storage_key = segment["storageKey"]
                if not isinstance(storage_key, str) or not storage_key or len(storage_key) > 512 or storage_key.startswith("/") or ".." in storage_key.split("/"):
                    raise ApiError(400, "invalid_storage_key", "storage key is invalid")
                self.db.execute("""INSERT OR REPLACE INTO segment_locations(
                    segment_id,node_id,volume_id,storage_key,size_bytes,sha256,assignment_generation,
                    archive_state,integrity,created_at,camera_id,profile_id,start_utc_ms,end_utc_ms,
                    duration_ms,kind,video_codec,audio_codec,locked)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                (segment_id, node_id, volume_id, storage_key, size_bytes, digest, generation,
                                 archive_state, integrity, now_seconds(), camera_id, profile_id,
                                 start_ms, end_ms, duration_ms, kind, video_codec, audio_codec, int(locked)))
                accepted += 1
            revision = self._bump()
        return {"accepted": accepted, "conflicts": conflicts, "revision": revision}

    def recording_catalog(self, query: dict[str, list[str]]) -> dict[str, Any]:
        try:
            start = int(query.get("from", ["0"])[0])
            end = int(query.get("to", [str((1 << 63) - 1)])[0])
            limit = int(query.get("limit", [str(MAX_PAGE)])[0])
        except (TypeError, ValueError) as error:
            raise ApiError(400, "invalid_recording_range", "recording range is invalid") from error
        if not 0 <= start < end < (1 << 63) or not 1 <= limit <= MAX_PAGE:
            raise ApiError(400, "invalid_recording_range", "recording range is invalid")
        camera_values = query.get("cameraId", [])
        if len(camera_values) > 1 or any(not IDENTIFIER.fullmatch(value) for value in camera_values):
            raise ApiError(400, "invalid_camera_filter", "recording camera filter is invalid")
        clauses = ["start_utc_ms>0", "end_utc_ms>=?", "start_utc_ms<=?", "integrity!='deleted'"]
        parameters: list[Any] = [start, end]
        if camera_values:
            clauses.append("camera_id IN (" + ",".join("?" for _ in camera_values) + ")")
            parameters.extend(camera_values)
        parameters.append(limit)
        rows = self.db.execute(
            "SELECT * FROM segment_locations WHERE " + " AND ".join(clauses) +
            " ORDER BY start_utc_ms,segment_id,node_id LIMIT ?", tuple(parameters)).fetchall()
        items = [{
            "id": row["segment_id"], "cameraId": row["camera_id"], "profileId": row["profile_id"],
            "startUtcMs": row["start_utc_ms"], "endUtcMs": row["end_utc_ms"],
            "durationMs": row["duration_ms"], "kind": row["kind"],
            "videoCodec": row["video_codec"], "audioCodec": row["audio_codec"],
            "sizeBytes": row["size_bytes"], "integrity": row["integrity"],
            "locked": bool(row["locked"]), "nodeId": row["node_id"],
            "volumeId": row["volume_id"], "archiveState": row["archive_state"],
            "playbackState": "archived" if row["archive_state"] == "uploaded" else "recorder",
        } for row in rows]
        return {"recordings": items, "revision": self.revision()}

    def recording_timeline(self, query: dict[str, list[str]]) -> dict[str, Any]:
        started = time.monotonic_ns()
        catalog = self.recording_catalog({**query, "limit": [str(MAX_PAGE)]})
        try:
            start = int(query.get("from", ["0"])[0])
            end = int(query.get("to", [str((1 << 63) - 1)])[0])
        except (TypeError, ValueError) as error:
            raise ApiError(400, "invalid_recording_range", "recording range is invalid") from error
        if end - start > 31 * 86_400_000:
            raise ApiError(400, "invalid_recording_range", "timeline range is limited to 31 days")
        requested = query.get("cameraId", [])
        camera_ids = requested or sorted({item["cameraId"] for item in catalog["recordings"]})
        cameras = []
        for camera_id in camera_ids:
            segments = [item for item in catalog["recordings"] if item["cameraId"] == camera_id]
            cursor = start
            gaps = []
            for item in segments:
                if item["integrity"] in {"missing", "corrupt", "quarantined", "conflict"}:
                    gaps.append({"fromUtcMs": max(start, item["startUtcMs"]),
                                 "toUtcMs": min(end, item["endUtcMs"]), "reason": item["integrity"]})
                    continue
                if item["startUtcMs"] > cursor + 250:
                    gaps.append({"fromUtcMs": cursor, "toUtcMs": item["startUtcMs"], "reason": "offline"})
                cursor = max(cursor, item["endUtcMs"])
            if cursor < end:
                gaps.append({"fromUtcMs": cursor, "toUtcMs": end, "reason": "offline"})
            cameras.append({"cameraId": camera_id, "recordedStream": "profile",
                            "retentionBoundaryUtcMs": min((item["startUtcMs"] for item in segments), default=None),
                            "segments": segments, "gaps": gaps})
        return {"fromUtcMs": start, "toUtcMs": end, "storageTimeZone": "UTC", "cameras": cameras,
                "queryDurationMs": max(0, (time.monotonic_ns() - started) // 1_000_000),
                "revision": catalog["revision"]}

    def archive_playback_ticket(self, segment_id: str, camera_id: str,
                                timestamp: dt.datetime | None = None) -> dict[str, Any]:
        require_identifier(segment_id, "segment_id")
        require_identifier(camera_id, "camera_id")
        rows = self.db.execute("""SELECT * FROM segment_locations
            WHERE segment_id=? AND camera_id=? AND archive_state='uploaded'
              AND integrity IN ('verified','ok')
            ORDER BY node_id,volume_id""", (segment_id, camera_id)).fetchall()
        if not rows:
            raise ApiError(404, "archived_recording_not_found", "archived recording was not found")
        identities = {(row["sha256"], row["size_bytes"]) for row in rows}
        if len(identities) != 1:
            raise ApiError(409, "archive_location_conflict", "archived recording locations disagree")
        digest, size_bytes = identities.pop()
        if not re.fullmatch(r"[0-9a-f]{64}", digest) or not 1 <= size_bytes <= MAX_BROWSER_ARCHIVE_BYTES:
            raise ApiError(409, "archive_browser_limit", "archived recording is not eligible for browser playback")
        targets = self.db.execute("SELECT * FROM archive_targets WHERE enabled=1 ORDER BY id LIMIT 2").fetchall()
        if len(targets) != 1:
            raise ApiError(409, "archive_target_ambiguous", "exactly one archive target must be enabled")
        target = targets[0]
        secret_path = (self.secrets_root / target["credentials_ref"]).resolve()
        try:
            secret_path.relative_to(self.secrets_root.resolve())
        except (OSError, ValueError) as error:
            raise ApiError(503, "archive_credentials_unavailable", "archive credentials are unavailable") from error
        if not secret_path.is_file() or secret_path.is_symlink() or secret_path.stat().st_size > 4096:
            raise ApiError(503, "archive_credentials_unavailable", "archive credentials are unavailable")
        try:
            credentials = json.loads(secret_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ApiError(503, "archive_credentials_unavailable", "archive credentials are unavailable") from error
        if not isinstance(credentials, dict) or set(credentials) != {"accessKeyId", "secretAccessKey"} or \
                not all(isinstance(value, str) and 8 <= len(value) <= 256 for value in credentials.values()):
            raise ApiError(503, "archive_credentials_unavailable", "archive credentials are unavailable")
        current = timestamp or dt.datetime.now(dt.timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=dt.timezone.utc)
        amz_date = current.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        short_date = current.astimezone(dt.timezone.utc).strftime("%Y%m%d")
        scope = f"{short_date}/{target['region']}/s3/aws4_request"
        object_key = f"segments/{digest[:2]}/{digest}"
        canonical_uri = f"/{quote(target['bucket'], safe='-_.~')}/{quote(object_key, safe='/-_.~')}"
        parameters = {
            "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
            "X-Amz-Credential": f"{credentials['accessKeyId']}/{scope}",
            "X-Amz-Date": amz_date,
            "X-Amz-Expires": str(ARCHIVE_TICKET_SECONDS),
            "X-Amz-SignedHeaders": "host",
        }
        canonical_query = urlencode(sorted(parameters.items()), quote_via=quote, safe="-_.~")
        authority = target["endpoint_authority"]
        canonical_request = "\n".join([
            "GET", canonical_uri, canonical_query, f"host:{authority}\n", "host", "UNSIGNED-PAYLOAD",
        ])
        string_to_sign = "\n".join([
            "AWS4-HMAC-SHA256", amz_date, scope,
            hashlib.sha256(canonical_request.encode()).hexdigest(),
        ])
        signature = hmac.new(aws_signing_key(credentials["secretAccessKey"], short_date,
                                              target["region"]), string_to_sign.encode(),
                             hashlib.sha256).hexdigest()
        expires_at = int(current.timestamp()) + ARCHIVE_TICKET_SECONDS
        return {"segmentId": segment_id, "cameraId": camera_id,
                "url": f"https://{authority}{canonical_uri}?{canonical_query}&X-Amz-Signature={signature}",
                "sha256": digest, "sizeBytes": size_bytes,
                "contentType": "video/mp4" if rows[0]["storage_key"].endswith(".mp4")
                else "application/octet-stream",
                "expiresAt": expires_at, "credentialExposure": "ephemeral"}

    def list_volumes(self) -> dict[str, Any]:
        rows = self.db.execute("SELECT * FROM storage_volumes ORDER BY node_id,id LIMIT ?", (MAX_PAGE,)).fetchall()
        return {"volumes": [{"id": row["id"], "nodeId": row["node_id"], "label": row["label"],
                              "tier": row["tier"], "state": row["state"],
                              "capacityBytes": row["capacity_bytes"], "freeBytes": row["free_bytes"],
                              "reserveBytes": row["reserve_bytes"], "highWatermark": row["high_watermark"],
                              "lowWatermark": row["low_watermark"], "readOnly": bool(row["read_only"]),
                              "lastScrubAt": row["last_scrub_at"], "revision": row["revision"]} for row in rows],
                "revision": self.revision()}

    def update_volume(self, node_id: str, volume_id: str, value: Any,
                      expected_revision: int) -> dict[str, Any]:
        require_identifier(node_id, "node_id")
        if not VOLUME_ID.fullmatch(volume_id):
            raise ApiError(400, "invalid_volume_id", "volume id is invalid")
        value = require_exact_object(value, {"label", "tier", "state", "reserveBytes",
                                             "highWatermark", "lowWatermark"})
        if not value:
            raise ApiError(400, "empty_patch", "at least one volume field is required")
        with self.lock, self.db:
            row = self.db.execute("SELECT * FROM storage_volumes WHERE node_id=? AND id=?",
                                  (node_id, volume_id)).fetchone()
            if row is None:
                raise ApiError(404, "volume_not_found", "storage volume was not found")
            if row["revision"] != expected_revision:
                raise ApiError(409, "revision_conflict", "storage volume revision does not match")
            candidate = {
                "label": value.get("label", row["label"]), "tier": value.get("tier", row["tier"]),
                "state": value.get("state", row["state"]),
                "reserveBytes": value.get("reserveBytes", row["reserve_bytes"]),
                "highWatermark": value.get("highWatermark", row["high_watermark"]),
                "lowWatermark": value.get("lowWatermark", row["low_watermark"]),
            }
            if not isinstance(candidate["label"], str) or not candidate["label"].strip() or len(candidate["label"]) > 64:
                raise ApiError(400, "invalid_volume_label", "volume label is invalid")
            if candidate["tier"] not in {"hot", "warm", "archive"} or candidate["state"] not in {
                    "online", "degraded", "read-only", "evacuating", "offline"}:
                raise ApiError(400, "invalid_volume_state", "volume tier or state is invalid")
            if not isinstance(candidate["reserveBytes"], int) or candidate["reserveBytes"] < 0:
                raise ApiError(400, "invalid_volume_reserve", "volume reserve is invalid")
            if not (isinstance(candidate["lowWatermark"], (int, float)) and
                    isinstance(candidate["highWatermark"], (int, float)) and
                    0.5 <= candidate["lowWatermark"] < candidate["highWatermark"] <= 0.99):
                raise ApiError(400, "invalid_watermark", "volume watermarks are invalid")
            revision = row["revision"] + 1
            self.db.execute("""
              UPDATE storage_volumes SET label=?,tier=?,state=?,reserve_bytes=?,high_watermark=?,
                low_watermark=?,revision=? WHERE node_id=? AND id=?
            """, (candidate["label"].strip(), candidate["tier"], candidate["state"],
                  candidate["reserveBytes"], candidate["highWatermark"], candidate["lowWatermark"],
                  revision, node_id, volume_id))
            self._bump()
        return {"id": volume_id, "nodeId": node_id, **candidate, "revision": revision}

    def list_placements(self) -> dict[str, Any]:
        rows = self.db.execute("SELECT * FROM recording_assignments ORDER BY camera_id,profile_id LIMIT ?",
                               (MAX_PAGE,)).fetchall()
        return {"placements": [{"cameraId": row["camera_id"], "profileId": row["profile_id"],
                                  "nodeId": row["node_id"], "generation": row["generation"],
                                  "state": row["state"], "leaseExpiresAt": row["lease_expires_at"],
                                  "isolationDeadline": row["isolation_deadline"],
                                  "taskType": row["task_type"],
                                  "costs": json.loads(row["costs_json"])} for row in rows],
                "revision": self.revision()}

    def create_archive_target(self, value: Any) -> dict[str, Any]:
        value = require_exact_object(value, {"name", "endpoint", "bucket", "credentialsRef", "enabled", "region"},
                                     {"name", "endpoint", "bucket", "credentialsRef"})
        parsed = urlsplit(value["endpoint"]) if isinstance(value["endpoint"], str) else None
        if parsed is None or parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or \
                parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
            raise ApiError(400, "invalid_archive_endpoint", "archive endpoint must be an HTTPS authority")
        name = value["name"]
        bucket = value["bucket"]
        credentials_ref = value["credentialsRef"]
        region = value.get("region", "us-east-1")
        if not isinstance(name, str) or not name.strip() or len(name) > 64 or \
                not isinstance(bucket, str) or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket) or \
                not isinstance(credentials_ref, str) or not SECRET_REF.fullmatch(credentials_ref) or \
                not isinstance(region, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,31}", region):
            raise ApiError(400, "invalid_archive_target", "archive target fields are invalid")
        enabled = value.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ApiError(400, "invalid_enabled", "enabled must be a boolean")
        target_id = secrets.token_hex(16)
        authority = f"{parsed.hostname}:{parsed.port}" if parsed.port else parsed.hostname
        with self.lock, self.db:
            self.db.execute("""INSERT INTO archive_targets(
                id,name,endpoint_authority,bucket,credentials_ref,enabled,revision,region)
                VALUES(?,?,?,?,?,?,?,?)""",
                            (target_id, name.strip(), authority, bucket, credentials_ref,
                             int(enabled), 1, region))
            catalog_revision = self._bump()
        return {"id": target_id, "name": name.strip(), "endpointAuthority": authority,
                "bucket": bucket, "credentialsRef": credentials_ref, "enabled": enabled,
                "region": region, "revision": 1, "catalogRevision": catalog_revision}

    def list_archive_targets(self) -> dict[str, Any]:
        rows = self.db.execute("SELECT * FROM archive_targets ORDER BY name LIMIT ?", (MAX_PAGE,)).fetchall()
        return {"targets": [{"id": row["id"], "name": row["name"],
                               "endpointAuthority": row["endpoint_authority"], "bucket": row["bucket"],
                               "credentialsRef": row["credentials_ref"], "enabled": bool(row["enabled"]),
                               "region": row["region"], "revision": row["revision"]} for row in rows],
                "revision": self.revision()}

    def create_backup_job(self, value: Any) -> dict[str, Any]:
        value = require_exact_object(value, {"targetId"})
        target_id = value.get("targetId", "local")
        if target_id != "local":
            require_identifier(target_id, "target_id")
            if self.db.execute("SELECT 1 FROM archive_targets WHERE id=? AND enabled=1", (target_id,)).fetchone() is None:
                raise ApiError(404, "archive_target_not_found", "archive target was not found")
        job_id = secrets.token_hex(16)
        timestamp = now_seconds()
        with self.lock, self.db:
            self.db.execute("INSERT INTO backup_jobs VALUES(?,?,?,?,?,?,?)",
                            (job_id, "queued", target_id, "", timestamp, 0, ""))
            revision = self._bump()
        return {"id": job_id, "state": "queued", "targetId": target_id,
                "createdAt": timestamp, "revision": revision}

    def list_backup_jobs(self) -> dict[str, Any]:
        rows = self.db.execute("SELECT * FROM backup_jobs ORDER BY created_at DESC LIMIT ?", (MAX_PAGE,)).fetchall()
        return {"jobs": [{"id": row["id"], "state": row["state"], "targetId": row["target_id"],
                           "sha256": row["sha256"], "createdAt": row["created_at"],
                           "completedAt": row["completed_at"], "errorCode": row["error_code"]} for row in rows],
                "revision": self.revision()}

    def claim_backup_job(self) -> dict[str, Any]:
        with self.lock, self.db:
            row = self.db.execute(
                "SELECT * FROM backup_jobs WHERE state='queued' ORDER BY created_at LIMIT 1").fetchone()
            if row is None:
                return {"job": None}
            self.db.execute("UPDATE backup_jobs SET state='running' WHERE id=? AND state='queued'", (row["id"],))
            self._bump()
        return {"job": {"id": row["id"], "targetId": row["target_id"],
                        "createdAt": row["created_at"]}}

    def complete_backup_job(self, job_id: str, value: Any) -> dict[str, Any]:
        require_identifier(job_id, "job_id")
        value = require_exact_object(value, {"state", "sha256", "errorCode"}, {"state"})
        state = value["state"]
        digest = value.get("sha256", "")
        error = value.get("errorCode", "")
        if state not in {"completed", "failed"} or \
                (state == "completed" and not re.fullmatch(r"[0-9a-f]{64}", str(digest))) or \
                (state == "failed" and (not isinstance(error, str) or not IDENTIFIER.fullmatch(error))):
            raise ApiError(400, "invalid_backup_result", "backup result is invalid")
        with self.lock, self.db:
            row = self.db.execute("SELECT state FROM backup_jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise ApiError(404, "backup_job_not_found", "backup job was not found")
            if row["state"] != "running":
                raise ApiError(409, "backup_job_state", "backup job is not running")
            self.db.execute("UPDATE backup_jobs SET state=?,sha256=?,completed_at=?,error_code=? WHERE id=?",
                            (state, digest if state == "completed" else "", now_seconds(),
                             error if state == "failed" else "", job_id))
            revision = self._bump()
        return {"id": job_id, "state": state, "revision": revision}

    def create_provider(self, value: Any) -> dict[str, Any]:
        required = {"name", "endpoint", "taskTypes", "credentialsRef", "maxConcurrent"}
        value = require_exact_object(value, required | {"enabled"}, required)
        parsed = urlsplit(value["endpoint"]) if isinstance(value["endpoint"], str) else None
        tasks = value["taskTypes"]
        if parsed is None or parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or \
                parsed.query or parsed.fragment or not parsed.path.startswith("/") or len(parsed.path) > 256:
            raise ApiError(400, "invalid_provider_endpoint", "provider endpoint must be an HTTPS URL")
        if not isinstance(tasks, list) or not tasks or len(set(tasks)) != len(tasks) or any(
                task not in {"external-nvr", "export", "detector"} for task in tasks):
            raise ApiError(400, "invalid_provider_tasks", "provider task types are invalid")
        name = value["name"]
        credentials_ref = value["credentialsRef"]
        maximum = value["maxConcurrent"]
        enabled = value.get("enabled", True)
        if not isinstance(name, str) or not name.strip() or len(name) > 64 or \
                not isinstance(credentials_ref, str) or not SECRET_REF.fullmatch(credentials_ref) or \
                not isinstance(maximum, int) or isinstance(maximum, bool) or not 1 <= maximum <= 64 or \
                not isinstance(enabled, bool):
            raise ApiError(400, "invalid_provider", "provider fields are invalid")
        provider_id = secrets.token_hex(16)
        authority = f"{parsed.hostname}:{parsed.port}" if parsed.port else parsed.hostname
        with self.lock, self.db:
            self.db.execute("INSERT INTO external_providers VALUES(?,?,?,?,?,?,?,?,?)",
                            (provider_id, name.strip(), authority, parsed.path,
                             canonical_json(sorted(tasks)), credentials_ref, maximum, int(enabled), 1))
            catalog_revision = self._bump()
            self._audit("provider.created", "web-session", provider_id, "completed")
        return {"id": provider_id, "name": name.strip(), "endpointAuthority": authority,
                "taskTypes": sorted(tasks), "maxConcurrent": maximum, "enabled": enabled,
                "revision": 1, "catalogRevision": catalog_revision}

    def list_providers(self) -> dict[str, Any]:
        self._expire_provider_tasks()
        rows = self.db.execute("SELECT * FROM external_providers ORDER BY name LIMIT ?", (MAX_PAGE,)).fetchall()
        providers = []
        for row in rows:
            counts = {item["state"]: item["count"] for item in self.db.execute(
                "SELECT state,COUNT(*) AS count FROM provider_tasks WHERE provider_id=? GROUP BY state",
                (row["id"],))}
            providers.append({"id": row["id"], "name": row["name"],
                              "endpointAuthority": row["endpoint_authority"],
                              "taskTypes": json.loads(row["task_types_json"]),
                              "maxConcurrent": row["max_concurrent"], "enabled": bool(row["enabled"]),
                              "taskCounts": counts, "revision": row["revision"]})
        return {"providers": providers, "revision": self.revision()}

    def _expire_provider_tasks(self, timestamp: int | None = None) -> None:
        current = timestamp or now_seconds()
        with self.lock, self.db:
            self.db.execute("""UPDATE provider_tasks
                SET state='expired',result_code='grant_expired'
                WHERE state IN ('offered','media-opened') AND expires_at<=?""", (current,))
            self.db.execute("DELETE FROM provider_grants WHERE expires_at<=?", (current,))

    def list_provider_tasks(self, provider_id: str, query: dict[str, list[str]]) -> dict[str, Any]:
        require_identifier(provider_id, "provider_id")
        if not set(query).issubset({"limit"}):
            raise ApiError(400, "invalid_provider_task_query", "provider task query is invalid")
        values = query.get("limit", ["100"])
        if len(values) != 1 or not values[0].isdigit() or not 1 <= int(values[0]) <= MAX_PAGE:
            raise ApiError(400, "invalid_provider_task_query", "provider task limit is invalid")
        self._expire_provider_tasks()
        if self.db.execute("SELECT 1 FROM external_providers WHERE id=?", (provider_id,)).fetchone() is None:
            raise ApiError(404, "provider_not_found", "provider was not found")
        rows = self.db.execute("""SELECT * FROM provider_tasks WHERE provider_id=?
            ORDER BY created_at DESC,id DESC LIMIT ?""", (provider_id, int(values[0]))).fetchall()
        return {"tasks": [{"id": row["id"], "providerId": row["provider_id"],
                            "taskType": row["task_type"], "cameraId": row["camera_id"],
                            "profileId": row["profile_id"], "segmentId": row["segment_id"] or None,
                            "state": row["state"], "createdAt": row["created_at"],
                            "expiresAt": row["expires_at"],
                            "mediaOpenedAt": row["media_opened_at"] or None,
                            "resultCode": row["result_code"] or None} for row in rows]}

    def create_provider_task(self, provider_id: str, value: Any) -> dict[str, Any]:
        require_identifier(provider_id, "provider_id")
        required = {"taskType", "cameraId", "profileId"}
        value = require_exact_object(value, required | {"segmentId", "parameters"}, required)
        camera_id = require_identifier(value["cameraId"], "camera_id")
        profile_id = require_identifier(value["profileId"], "profile_id")
        segment_id = value.get("segmentId", "")
        if segment_id and (not isinstance(segment_id, str) or not re.fullmatch(r"[a-f0-9]{32}", segment_id)):
            raise ApiError(400, "invalid_segment_id", "segment id is invalid")
        parameters = value.get("parameters", {})
        if not isinstance(parameters, dict) or len(parameters) > 32 or len(canonical_json(parameters)) > 16 * 1024:
            raise ApiError(400, "invalid_provider_parameters", "provider parameters are invalid")
        with self.lock, self.db:
            current = now_seconds()
            self.db.execute("""UPDATE provider_tasks SET state='expired',result_code='grant_expired'
                WHERE state IN ('offered','media-opened') AND expires_at<=?""", (current,))
            self.db.execute("DELETE FROM provider_grants WHERE expires_at<=?", (current,))
            provider = self.db.execute("SELECT * FROM external_providers WHERE id=? AND enabled=1",
                                       (provider_id,)).fetchone()
            if provider is None:
                raise ApiError(404, "provider_not_found", "provider was not found")
            if value["taskType"] not in json.loads(provider["task_types_json"]):
                raise ApiError(409, "provider_task_unsupported", "provider does not accept this task type")
            if segment_id and self.db.execute(
                    """SELECT 1 FROM segment_locations WHERE segment_id=? AND camera_id=? AND profile_id=?
                       AND integrity IN ('verified','ok') LIMIT 1""",
                    (segment_id, camera_id, profile_id)).fetchone() is None:
                raise ApiError(404, "provider_segment_not_found",
                               "the authorized recording segment was not found for this camera profile")
            active = self.db.execute("""SELECT COUNT(*) FROM provider_tasks
                WHERE provider_id=? AND state IN ('offered','media-opened') AND expires_at>?""",
                                     (provider_id, current)).fetchone()[0]
            if active >= provider["max_concurrent"]:
                raise ApiError(429, "provider_capacity", "provider capacity is exhausted")
            task_id = secrets.token_hex(16)
            token = secrets.token_urlsafe(32)
            expires_at = current + 60
            self.db.execute("INSERT INTO provider_tasks VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                            (task_id, provider_id, value["taskType"], camera_id, profile_id,
                             segment_id, "offered", current, expires_at, 0, ""))
            self.db.execute("INSERT INTO provider_grants VALUES(?,?,?,?,?,?,?,0)",
                            (hashlib.sha256(token.encode()).hexdigest(), provider_id, task_id,
                             camera_id, profile_id, segment_id, expires_at))
            self._audit("provider.task.created", "web-session", task_id, "offered")
        return {"schemaVersion": 1, "taskId": task_id, "taskType": value["taskType"], "state": "offered",
                "subject": {"cameraId": camera_id, "profileId": profile_id, **({"segmentId": segment_id} if segment_id else {})},
                "expiresAt": expires_at, "mediaGrant": {"token": token, "method": "GET",
                "path": f"/api/v2/provider-media/{task_id}"}, "parameters": parameters}

    def consume_provider_grant(self, task_id: str, token: str) -> dict[str, Any]:
        require_identifier(task_id, "task_id")
        if not isinstance(token, str) or not 32 <= len(token) <= 128 or \
                not re.fullmatch(r"[A-Za-z0-9_-]+", token):
            raise ApiError(401, "provider_grant_rejected", "provider media grant was rejected")
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self.lock, self.db:
            row = self.db.execute(
                "SELECT * FROM provider_grants WHERE token_hash=? AND task_id=?",
                (token_hash, task_id),
            ).fetchone()
            if row is None or row["used"] or row["expires_at"] <= now_seconds():
                raise ApiError(401, "provider_grant_rejected", "provider media grant was rejected")
            updated = self.db.execute(
                "UPDATE provider_grants SET used=1 WHERE token_hash=? AND task_id=? AND used=0 AND expires_at>?",
                (token_hash, task_id, now_seconds()),
            )
            if updated.rowcount != 1:
                raise ApiError(401, "provider_grant_rejected", "provider media grant was rejected")
            self.db.execute("""UPDATE provider_tasks SET state='media-opened',media_opened_at=?,result_code=''
                WHERE id=? AND state='offered' AND expires_at>?""", (now_seconds(), task_id, now_seconds()))
            self._audit("provider.media.opened", row["provider_id"], task_id, "completed")
        return {"taskId": task_id, "cameraId": row["camera_id"], "profileId": row["profile_id"],
                "segmentId": row["segment_id"] or None, "expiresAt": row["expires_at"],
                "credentialExposure": "none"}

    def capacity(self) -> dict[str, Any]:
        scheduled: dict[str, dict[str, Any]] = {}
        for row in self.db.execute(
                "SELECT node_id,task_type,costs_json FROM recording_assignments WHERE state='active'"):
            aggregate = scheduled.setdefault(row["node_id"], {
                "taskCount": 0, "taskTypes": {}, "costs": {
                    "cpuCores": 0.0, "memoryBytes": 0.0, "decodeSlots": 0.0,
                    "encodeSlots": 0.0, "diskBytesPerSecond": 0.0,
                },
            })
            aggregate["taskCount"] += 1
            aggregate["taskTypes"][row["task_type"]] = aggregate["taskTypes"].get(row["task_type"], 0) + 1
            with contextlib.suppress(json.JSONDecodeError, TypeError, ValueError):
                costs = json.loads(row["costs_json"])
                for field in aggregate["costs"]:
                    aggregate["costs"][field] += float(costs.get(field, 0))
        for row in self.db.execute("SELECT node_id,requested_resources_json FROM analytics_jobs WHERE state='running' AND lease_expires_at>?", (now_seconds(),)):
            aggregate = scheduled.setdefault(row["node_id"], {
                "taskCount": 0, "taskTypes": {}, "costs": {
                    "cpuCores": 0.0, "memoryBytes": 0.0, "decodeSlots": 0.0,
                    "encodeSlots": 0.0, "diskBytesPerSecond": 0.0,
                },
            })
            aggregate["taskCount"] += 1
            aggregate["taskTypes"]["detector-reserved"] = aggregate["taskTypes"].get("detector-reserved", 0) + 1
            with contextlib.suppress(json.JSONDecodeError, TypeError, ValueError):
                costs = json.loads(row["requested_resources_json"])
                for field in aggregate["costs"]:
                    aggregate["costs"][field] += float(costs.get(field, 0))
        reports = []
        for row in self.db.execute("SELECT * FROM resource_reports ORDER BY node_id LIMIT ?", (MAX_PAGE,)):
            reports.append({"nodeId": row["node_id"], "cpuCores": row["cpu_cores"],
                            "memoryBytes": row["memory_bytes"], "rated": bool(row["rated"]),
                            "capabilities": json.loads(row["capabilities_json"]),
                            "reservations": json.loads(row["reservations_json"]),
                            "scheduledReservations": scheduled.get(row["node_id"], {
                                "taskCount": 0, "taskTypes": {}, "costs": {},
                            }),
                            "updatedAt": row["updated_at"]})
        return {"nodes": reports, "taskPriorities": TASK_PRIORITY, "referenceTiers": REFERENCE_TIERS,
                "revision": self.revision()}


STORE: ClusterStore | None = None
INTERNAL_TOKEN = ""


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "webobs-cluster/1"

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def response(self, status: int, value: Any = None) -> None:
        body = b"" if value is None else canonical_json(value).encode("utf-8")
        self.send_response(status)
        if body:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def read_json(self) -> Any:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ApiError(400, "invalid_length", "Content-Length is invalid") from error
        if length < 0 or length > MAX_BODY or self.headers.get_content_type() != "application/json":
            raise ApiError(400, "invalid_body", "bounded application/json body is required")
        try:
            return json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ApiError(400, "invalid_json", "request JSON is invalid") from error

    def admin(self) -> None:
        value = self.headers.get("X-WebObs-Internal-Admin", "")
        if not INTERNAL_TOKEN or not secrets.compare_digest(value, INTERNAL_TOKEN):
            raise ApiError(403, "internal_auth_rejected", "internal administrator authentication was rejected")

    def if_match(self) -> int:
        value = self.headers.get("If-Match", "")
        match = re.fullmatch(r'"?([1-9][0-9]{0,18})"?', value)
        if match is None:
            raise ApiError(428, "revision_required", "a valid If-Match revision is required")
        return int(match.group(1))

    def handle_request(self) -> None:
        assert STORE is not None
        path = urlsplit(self.path).path
        if self.command == "GET" and path == "/health":
            self.response(200, {"status": "ok", "revision": STORE.revision()})
            return
        if path == "/auth/login" and self.command == "POST":
            value = self.read_json()
            require_exact_object(value, {"username", "password", "clientKey"}, {"username", "password", "clientKey"})
            principal = STORE.authenticate(value["username"], value["password"], value["clientKey"])
            if principal is None:
                raise ApiError(401, "invalid_credentials", "credentials were rejected")
            self.response(200, {"userId": principal.user_id, "username": principal.username,
                                "roles": principal.roles, "permissions": sorted(principal.permissions),
                                "scopes": [{"kind": kind, "id": identifier} for kind, identifier in principal.scopes]})
            return
        if path.startswith("/provider-media/") and self.command in {"GET", "POST"}:
            if self.command == "GET":
                token = self.headers.get("X-WebObs-Provider-Token", "")
                if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token):
                    raise ApiError(401, "provider_grant_rejected", "provider media grant was rejected")
            else:
                value = self.read_json()
                require_exact_object(value, {"token"}, {"token"})
                token = value["token"]
            self.response(200, STORE.consume_provider_grant(path.split("/")[2], token))
            return
        self.admin()
        if path == "/auth/authorize" and self.command == "POST":
            value = self.read_json()
            require_exact_object(value, {"username", "permission", "cameraId", "groupId"},
                                 {"username", "permission"})
            self.response(200, STORE.authorize(value["username"], value["permission"],
                                                value.get("cameraId", ""), value.get("groupId", "")))
        elif path == "/roles" and self.command == "GET":
            self.response(200, {"roles": [{"id": role, "permissions": sorted(permissions)}
                                           for role, permissions in ROLE_PERMISSIONS.items()]})
        elif path == "/audit" and self.command == "GET":
            self.response(200, STORE.list_audit(parse_qs(urlsplit(self.path).query)))
        elif path == "/users" and self.command == "GET":
            self.response(200, STORE.list_users())
        elif path == "/users" and self.command == "POST":
            self.response(201, STORE.create_user(self.read_json()))
        elif path.startswith("/users/") and self.command == "PATCH":
            self.response(200, STORE.update_user(path.split("/")[2], self.read_json(), self.if_match()))
        elif path == "/nodes" and self.command == "GET":
            self.response(200, STORE.list_nodes())
        elif path.startswith("/nodes/") and self.command == "DELETE":
            self.response(200, STORE.revoke_node(path.split("/")[2], self.if_match()))
        elif path == "/node-enrollments" and self.command == "POST":
            self.response(201, STORE.create_enrollment(self.read_json()))
        elif path.startswith("/node-enrollments/") and path.endswith("/approve") and self.command == "POST":
            enrollment_id = path.split("/")[2]
            self.response(200, STORE.approve_enrollment(enrollment_id))
        elif path == "/storage-volumes" and self.command == "GET":
            self.response(200, STORE.list_volumes())
        elif path.startswith("/storage-volumes/") and self.command == "PATCH":
            parts = path.split("/")
            if len(parts) != 4:
                raise ApiError(404, "not_found", "resource was not found")
            self.response(200, STORE.update_volume(parts[2], parts[3], self.read_json(), self.if_match()))
        elif path == "/resource-capacity" and self.command == "GET":
            self.response(200, STORE.capacity())
        elif path == "/analytics-jobs" and self.command == "GET":
            self.response(200, STORE.list_analytics_jobs())
        elif path == "/analytics-jobs" and self.command == "POST":
            self.response(202, STORE.create_analytics_job(self.read_json()))
        elif path == "/recording-placements" and self.command == "POST":
            value = self.read_json()
            require_exact_object(value, {"cameraId", "profileId", "nodeId", "taskType", "costs"},
                                 {"cameraId", "profileId"})
            self.response(201, STORE.assign(value["cameraId"], value["profileId"], value.get("nodeId", ""),
                                            value.get("taskType", "record-copy"), value.get("costs", {})))
        elif path == "/recording-placements" and self.command == "GET":
            self.response(200, STORE.list_placements())
        elif path == "/recordings" and self.command == "GET":
            self.response(200, STORE.recording_catalog(parse_qs(urlsplit(self.path).query)))
        elif path == "/recordings/timeline" and self.command == "GET":
            self.response(200, STORE.recording_timeline(parse_qs(urlsplit(self.path).query)))
        elif path.startswith("/recordings/") and path.endswith("/playback-ticket") and self.command == "POST":
            parts = path.split("/")
            camera_ids = parse_qs(urlsplit(self.path).query).get("cameraId", [])
            if len(parts) != 4 or len(camera_ids) != 1:
                raise ApiError(400, "invalid_archive_ticket", "archive playback ticket is invalid")
            self.response(201, STORE.archive_playback_ticket(parts[2], camera_ids[0]))
        elif path == "/archive-targets" and self.command == "GET":
            self.response(200, STORE.list_archive_targets())
        elif path == "/archive-targets" and self.command == "POST":
            self.response(201, STORE.create_archive_target(self.read_json()))
        elif path == "/backup-jobs" and self.command == "GET":
            self.response(200, STORE.list_backup_jobs())
        elif path == "/backup-jobs" and self.command == "POST":
            self.response(202, STORE.create_backup_job(self.read_json()))
        elif path == "/backup-jobs/claim" and self.command == "POST":
            self.response(200, STORE.claim_backup_job())
        elif path.startswith("/backup-jobs/") and path.endswith("/result") and self.command == "POST":
            self.response(200, STORE.complete_backup_job(path.split("/")[2], self.read_json()))
        elif path == "/providers" and self.command == "GET":
            self.response(200, STORE.list_providers())
        elif path == "/providers" and self.command == "POST":
            self.response(201, STORE.create_provider(self.read_json()))
        elif path.startswith("/providers/") and path.endswith("/tasks") and self.command == "GET":
            self.response(200, STORE.list_provider_tasks(
                path.split("/")[2], parse_qs(urlsplit(self.path).query)))
        elif path.startswith("/providers/") and path.endswith("/tasks") and self.command == "POST":
            self.response(202, STORE.create_provider_task(path.split("/")[2], self.read_json()))
        else:
            raise ApiError(404, "not_found", "resource was not found")

    def do_GET(self) -> None:  # noqa: N802
        self.dispatch()

    def do_POST(self) -> None:  # noqa: N802
        self.dispatch()

    def do_PATCH(self) -> None:  # noqa: N802
        self.dispatch()

    def do_DELETE(self) -> None:  # noqa: N802
        self.dispatch()

    def dispatch(self) -> None:
        try:
            self.handle_request()
        except ApiError as error:
            self.response(error.status, {"error": {"code": error.code, "message": error.message}})
        except Exception:
            self.response(500, {"error": {"code": "internal_error", "message": "cluster service failed safely"}})


class ClusterHandler(Handler):
    def admin(self) -> None:
        return

    def handle_request(self) -> None:
        assert STORE is not None
        path = urlsplit(self.path).path
        if self.command == "GET" and path == "/health":
            self.response(200, {"status": "ok"})
            return
        # Enrollment is the only pre-certificate operation. It is protected by
        # a short-lived, one-time token and never accepts a node identity from
        # request headers. Every other route requires the verified mTLS URI SAN.
        if path == "/internal/v1/nodes/enroll" and self.command == "POST":
            self.response(200, STORE.submit_enrollment(self.read_json()))
            return
        if path == "/internal/v1/nodes/enroll/complete" and self.command == "POST":
            value = self.read_json()
            self.response(200, STORE.complete_enrollment(value.get("id", ""), value.get("token", "")))
            return
        peer = self.connection.getpeercert() if isinstance(self.connection, ssl.SSLSocket) else None
        uris = [value for kind, value in (peer or {}).get("subjectAltName", []) if kind == "URI"]
        node_ids = [value.removeprefix("webobs-node:") for value in uris if value.startswith("webobs-node:")]
        path_node_id = self.headers.get("X-WebObs-Node-Id", "")
        # The header only binds the request to the single verified URI SAN. It
        # is never accepted as node authentication by itself.
        if len(node_ids) != 1 or not path_node_id or node_ids[0] != path_node_id:
            raise ApiError(403, "node_identity_rejected", "node mTLS identity was rejected")
        node_id = node_ids[0]
        if path == "/internal/v1/nodes/heartbeat" and self.command == "POST":
            self.response(200, STORE.heartbeat(node_id, self.read_json()))
        elif path == "/internal/v1/nodes/certificate/renew" and self.command == "POST":
            self.response(200, STORE.renew_certificate(node_id, self.read_json()))
        elif path == "/internal/v1/assignments" and self.command == "GET":
            self.response(200, STORE.assignments_for(node_id))
        elif path == "/internal/v1/leases/renew" and self.command == "POST":
            self.response(200, STORE.renew(node_id, self.read_json()))
        elif path == "/internal/v1/catalog/batch" and self.command == "POST":
            self.response(200, STORE.accept_catalog(node_id, self.read_json()))
        elif self.command == "GET" and re.fullmatch(
                r"/internal/v1/analytics/jobs/[A-Za-z0-9][A-Za-z0-9._-]{0,63}/frame", path):
            token = self.headers.get("X-WebObs-Analytics-Grant", "")
            job_id = path.split("/")[5]
            self.response(200, STORE.consume_analytics_media_frame(node_id, job_id, token))
        elif path == "/internal/v1/jobs/result" and self.command == "POST":
            self.response(200, STORE.report_job_result(node_id, self.read_json()))
        elif path == "/internal/v1/analytics/jobs/claim" and self.command == "POST":
            self.response(200, STORE.claim_analytics_job(node_id))
        elif path == "/internal/v1/analytics/jobs/renew" and self.command == "POST":
            self.response(200, STORE.renew_analytics_job(node_id, self.read_json()))
        elif path == "/internal/v1/analytics/jobs/result" and self.command == "POST":
            self.response(200, STORE.report_analytics_job_result(node_id, self.read_json()))
        else:
            raise ApiError(404, "not_found", "resource was not found")


def validate_compatibility_auth(value: str, store: ClusterStore) -> None:
    if value not in {"true", "false"}:
        raise RuntimeError("WEBOBS_COMPAT_BASIC_AUTH must be true or false")
    if value == "false" and not store.has_enabled_admin():
        raise RuntimeError(
            "compatibility Basic Auth cannot be disabled before an enabled database administrator exists")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default=os.environ.get("WEBOBS_CLUSTER_DATABASE", "/config/webobs/cluster.sqlite3"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("WEBOBS_CLUSTER_INTERNAL_PORT", "8095")))
    parser.add_argument("--cluster-port", type=int, default=int(os.environ.get("WEBOBS_CLUSTER_PORT", "9443")))
    parser.add_argument("--role", default=os.environ.get("WEBOBS_NODE_ROLE", "standalone"))
    args = parser.parse_args()
    database = pathlib.Path(args.database)
    if not database.is_absolute() or not 1 <= args.port <= 65535 or not 1 <= args.cluster_port <= 65535:
        raise SystemExit("cluster database must be absolute and ports must be valid")
    global STORE, INTERNAL_TOKEN
    INTERNAL_TOKEN = os.environ.get("WEBOBS_CLUSTER_INTERNAL_TOKEN", "")
    if len(INTERNAL_TOKEN) != 64 or not re.fullmatch(r"[0-9a-f]{64}", INTERNAL_TOKEN):
        raise SystemExit("WEBOBS_CLUSTER_INTERNAL_TOKEN must be a 64-character lowercase hexadecimal secret")
    signer = None
    ca_cert = os.environ.get("WEBOBS_CLUSTER_CA_CERT_FILE", "")
    ca_key = os.environ.get("WEBOBS_CLUSTER_CA_KEY_FILE", "")
    if ca_cert or ca_key:
        signer = CertificateSigner(pathlib.Path(ca_cert), pathlib.Path(ca_key))
    STORE = ClusterStore(database, PasswordHasher(), signer)
    compatibility_auth = os.environ.get("WEBOBS_COMPAT_BASIC_AUTH", "true")
    try:
        validate_compatibility_auth(compatibility_auth, STORE)
    except RuntimeError as error:
        STORE.close()
        raise SystemExit(str(error)) from error
    admin_server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    servers: list[http.server.ThreadingHTTPServer] = [admin_server]
    if args.role == "controller" and os.environ.get("WEBOBS_CLUSTER_LISTEN", "false") == "true":
        cert_file = os.environ.get("WEBOBS_CLUSTER_SERVER_CERT_FILE", "")
        key_file = os.environ.get("WEBOBS_CLUSTER_SERVER_KEY_FILE", "")
        client_ca = os.environ.get("WEBOBS_CLUSTER_CLIENT_CA_FILE", "")
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.load_cert_chain(cert_file, key_file)
        context.load_verify_locations(client_ca)
        # The TLS stack requests a certificate so bootstrap enrollment can use
        # the same private listener. ClusterHandler fails closed for every
        # post-enrollment operation when no verified client certificate exists.
        context.verify_mode = ssl.CERT_OPTIONAL
        cluster_server = http.server.ThreadingHTTPServer(("0.0.0.0", args.cluster_port), ClusterHandler)
        cluster_server.socket = context.wrap_socket(cluster_server.socket, server_side=True)
        servers.append(cluster_server)
        threading.Thread(target=cluster_server.serve_forever, daemon=True).start()
    try:
        admin_server.serve_forever()
    finally:
        for server in servers:
            server.shutdown()
        STORE.close()


if __name__ == "__main__":
    main()
