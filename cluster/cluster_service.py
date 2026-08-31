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
import hashlib
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
from urllib.parse import parse_qs, urlsplit


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
ENROLLMENT_SECONDS = 600
CERTIFICATE_SECONDS = 30 * 24 * 60 * 60
CERTIFICATE_RENEW_SECONDS = 7 * 24 * 60 * 60
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
USERNAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
VOLUME_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
SECRET_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")


PERMISSIONS = frozenset({
    "live.view", "scene.read", "scene.write", "ptz.control", "talk.control",
    "snapshot.create", "playback.view", "export.create", "recording.lock",
    "recording.delete", "event.ack", "device.manage", "storage.manage",
    "node.manage", "settings.manage", "user.manage", "audit.view", "metrics.view",
})

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "admin": PERMISSIONS,
    "operator": frozenset({
        "live.view", "scene.read", "playback.view", "snapshot.create", "ptz.control",
        "talk.control", "event.ack", "recording.lock",
    }),
    "viewer": frozenset({"live.view", "scene.read", "playback.view"}),
    "auditor": frozenset({"event.ack", "audit.view", "playback.view"}),
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
    def __init__(self, database_path: pathlib.Path, hasher: Any, signer: Any | None = None):
        self.path = database_path
        self.hasher = hasher
        self.signer = signer
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
              CREATE TABLE IF NOT EXISTS resource_reports(
                node_id TEXT PRIMARY KEY,cpu_cores INTEGER NOT NULL,memory_bytes INTEGER NOT NULL,
                capabilities_json TEXT NOT NULL,reservations_json TEXT NOT NULL,rated INTEGER NOT NULL,updated_at INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS segment_locations(
                segment_id TEXT NOT NULL,node_id TEXT NOT NULL,volume_id TEXT NOT NULL,storage_key TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,sha256 TEXT NOT NULL,assignment_generation INTEGER NOT NULL,
                archive_state TEXT NOT NULL,integrity TEXT NOT NULL,created_at INTEGER NOT NULL,
                PRIMARY KEY(segment_id,node_id,volume_id));
              CREATE TABLE IF NOT EXISTS archive_targets(
                id TEXT PRIMARY KEY,name TEXT NOT NULL,endpoint_authority TEXT NOT NULL,bucket TEXT NOT NULL,
                credentials_ref TEXT NOT NULL,enabled INTEGER NOT NULL,revision INTEGER NOT NULL);
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
              CREATE INDEX IF NOT EXISTS nodes_status_seen ON nodes(status,last_seen_at);
              CREATE INDEX IF NOT EXISTS archive_jobs_due ON archive_jobs(state,next_attempt_at);
              CREATE INDEX IF NOT EXISTS segment_locations_segment ON segment_locations(segment_id);
            """)
            self.db.execute("PRAGMA user_version=1")
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
            raise ApiError(429, "authentication_rate_limited", "too many authentication failures")
        if not isinstance(username, str) or not isinstance(password, str) or len(password.encode("utf-8")) > 128:
            self.auth_failures[client_key] = (started, failures + 1)
            return None
        with self.lock:
            row = self.db.execute("SELECT * FROM users WHERE username=? AND enabled=1", (username,)).fetchone()
            if row is None or not self.hasher.verify(row["password_hash"], password):
                self.auth_failures[client_key] = (started, failures + 1)
                return None
            self.auth_failures.pop(client_key, None)
            return self.principal(row["id"])

    def authorize(self, username: str, permission: str, camera_id: str = "", group_id: str = "") -> dict[str, Any]:
        if permission not in PERMISSIONS:
            raise ApiError(400, "invalid_permission", "permission is invalid")
        with self.lock:
            row = self.db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
            if row is None:
                raise ApiError(404, "user_not_found", "user is not managed by RBAC")
            principal = self.principal(row["id"])
        if not principal.permits(permission, camera_id, group_id):
            raise ApiError(403, "permission_rejected", "permission or resource scope was rejected")
        return {"allowed": True, "userId": principal.user_id, "permission": permission}

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
                  ON CONFLICT(node_id,id) DO UPDATE SET label=excluded.label,tier=excluded.tier,state=excluded.state,
                    capacity_bytes=excluded.capacity_bytes,free_bytes=excluded.free_bytes,reserve_bytes=excluded.reserve_bytes,
                    high_watermark=excluded.high_watermark,low_watermark=excluded.low_watermark,
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
            if not node_id:
                node_id = self._select_node(camera_id, task_type, normalized_costs, timestamp)
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
              INSERT INTO recording_assignments VALUES(?,?,?,?,?,?,?,?)
              ON CONFLICT(camera_id,profile_id) DO UPDATE SET node_id=excluded.node_id,generation=excluded.generation,
                state=excluded.state,lease_expires_at=excluded.lease_expires_at,
                isolation_deadline=excluded.isolation_deadline,updated_at=excluded.updated_at
            """, (camera_id, profile_id, node_id, generation, "active", lease_expires, isolation_deadline, timestamp))
            revision = self._bump()
        return {"cameraId": camera_id, "profileId": profile_id, "nodeId": node_id,
                "generation": generation, "leaseExpiresAt": lease_expires,
                "isolationDeadline": isolation_deadline, "taskType": task_type,
                "costs": normalized_costs, "revision": revision}

    def _select_node(self, stable_key: str, task_type: str, costs: dict[str, Any], timestamp: int) -> str:
        candidates: list[tuple[float, str]] = []
        rows = self.db.execute("""
          SELECT n.*,r.cpu_cores,r.memory_bytes,r.capabilities_json AS resources_capabilities,
                 r.reservations_json,r.rated
          FROM nodes n JOIN resource_reports r ON r.node_id=n.id
          WHERE n.revoked=0 AND n.status='online'
        """).fetchall()
        for row in rows:
            if abs(row["clock_offset_ms"]) > MAX_CLOCK_SKEW_SECONDS * 1000 or \
                    timestamp - row["last_seen_at"] > NODE_UNHEALTHY_SECONDS:
                continue
            capabilities = json.loads(row["resources_capabilities"])
            reservations = json.loads(row["reservations_json"])
            used = {field: 0.0 for field in costs}
            for reservation in reservations:
                for field in used:
                    used[field] += float(reservation.get(field, 0))
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
            if row is None or row["node_id"] != node_id or row["generation"] != generation:
                raise ApiError(409, "stale_assignment", "assignment is missing, moved, or stale")
            lease_expires = timestamp + LEASE_SECONDS
            isolation_deadline = lease_expires + ISOLATION_GRACE_SECONDS
            self.db.execute("UPDATE recording_assignments SET lease_expires_at=?,isolation_deadline=?,updated_at=? WHERE camera_id=? AND profile_id=?",
                            (lease_expires, isolation_deadline, timestamp, camera_id, profile_id))
        return {"leaseExpiresAt": lease_expires, "isolationDeadline": isolation_deadline,
                "renewAfterSeconds": LEASE_RENEW_SECONDS}

    def assignments_for(self, node_id: str) -> dict[str, Any]:
        require_identifier(node_id, "node_id")
        rows = self.db.execute("SELECT * FROM recording_assignments WHERE node_id=? ORDER BY camera_id,profile_id",
                               (node_id,)).fetchall()
        return {"assignments": [{"cameraId": row["camera_id"], "profileId": row["profile_id"],
                                  "nodeId": row["node_id"], "generation": row["generation"],
                                  "state": row["state"], "leaseExpiresAt": row["lease_expires_at"],
                                  "isolationDeadline": row["isolation_deadline"]} for row in rows],
                "revision": self.revision()}

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
                require_exact_object(segment, required, required)
                assignment = self.db.execute(
                    "SELECT * FROM recording_assignments WHERE camera_id=? AND profile_id=?",
                    (segment["cameraId"], segment["profileId"])).fetchone()
                integrity = segment["integrity"]
                if assignment is None or assignment["node_id"] != node_id or assignment["generation"] != segment["generation"]:
                    integrity = "conflict"
                    conflicts += 1
                digest = segment["sha256"]
                if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                    raise ApiError(400, "invalid_segment_hash", "segment hash is invalid")
                storage_key = segment["storageKey"]
                if not isinstance(storage_key, str) or not storage_key or len(storage_key) > 512 or storage_key.startswith("/") or ".." in storage_key.split("/"):
                    raise ApiError(400, "invalid_storage_key", "storage key is invalid")
                self.db.execute("INSERT OR REPLACE INTO segment_locations VALUES(?,?,?,?,?,?,?,?,?,?)",
                                (segment["segmentId"], node_id, segment["volumeId"], storage_key,
                                 segment["sizeBytes"], digest, segment["generation"],
                                 segment["archiveState"], integrity, now_seconds()))
                accepted += 1
            revision = self._bump()
        return {"accepted": accepted, "conflicts": conflicts, "revision": revision}

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
                                  "isolationDeadline": row["isolation_deadline"]} for row in rows],
                "revision": self.revision()}

    def create_archive_target(self, value: Any) -> dict[str, Any]:
        value = require_exact_object(value, {"name", "endpoint", "bucket", "credentialsRef", "enabled"},
                                     {"name", "endpoint", "bucket", "credentialsRef"})
        parsed = urlsplit(value["endpoint"]) if isinstance(value["endpoint"], str) else None
        if parsed is None or parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or \
                parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
            raise ApiError(400, "invalid_archive_endpoint", "archive endpoint must be an HTTPS authority")
        name = value["name"]
        bucket = value["bucket"]
        credentials_ref = value["credentialsRef"]
        if not isinstance(name, str) or not name.strip() or len(name) > 64 or \
                not isinstance(bucket, str) or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket) or \
                not isinstance(credentials_ref, str) or not SECRET_REF.fullmatch(credentials_ref):
            raise ApiError(400, "invalid_archive_target", "archive target fields are invalid")
        enabled = value.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ApiError(400, "invalid_enabled", "enabled must be a boolean")
        target_id = secrets.token_hex(16)
        authority = f"{parsed.hostname}:{parsed.port}" if parsed.port else parsed.hostname
        with self.lock, self.db:
            self.db.execute("INSERT INTO archive_targets VALUES(?,?,?,?,?,?,?)",
                            (target_id, name.strip(), authority, bucket, credentials_ref, int(enabled), 1))
            catalog_revision = self._bump()
        return {"id": target_id, "name": name.strip(), "endpointAuthority": authority,
                "bucket": bucket, "credentialsRef": credentials_ref, "enabled": enabled,
                "revision": 1, "catalogRevision": catalog_revision}

    def list_archive_targets(self) -> dict[str, Any]:
        rows = self.db.execute("SELECT * FROM archive_targets ORDER BY name LIMIT ?", (MAX_PAGE,)).fetchall()
        return {"targets": [{"id": row["id"], "name": row["name"],
                              "endpointAuthority": row["endpoint_authority"], "bucket": row["bucket"],
                              "credentialsRef": row["credentials_ref"], "enabled": bool(row["enabled"]),
                              "revision": row["revision"]} for row in rows], "revision": self.revision()}

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
        return {"id": provider_id, "name": name.strip(), "endpointAuthority": authority,
                "taskTypes": sorted(tasks), "maxConcurrent": maximum, "enabled": enabled,
                "revision": 1, "catalogRevision": catalog_revision}

    def list_providers(self) -> dict[str, Any]:
        rows = self.db.execute("SELECT * FROM external_providers ORDER BY name LIMIT ?", (MAX_PAGE,)).fetchall()
        return {"providers": [{"id": row["id"], "name": row["name"],
                                "endpointAuthority": row["endpoint_authority"],
                                "taskTypes": json.loads(row["task_types_json"]),
                                "maxConcurrent": row["max_concurrent"], "enabled": bool(row["enabled"]),
                                "revision": row["revision"]} for row in rows], "revision": self.revision()}

    def create_provider_task(self, provider_id: str, value: Any) -> dict[str, Any]:
        require_identifier(provider_id, "provider_id")
        required = {"taskType", "cameraId", "profileId"}
        value = require_exact_object(value, required | {"segmentId", "parameters"}, required)
        camera_id = require_identifier(value["cameraId"], "camera_id")
        profile_id = require_identifier(value["profileId"], "profile_id")
        segment_id = value.get("segmentId", "")
        if segment_id:
            require_identifier(segment_id, "segment_id")
        parameters = value.get("parameters", {})
        if not isinstance(parameters, dict) or len(parameters) > 32 or len(canonical_json(parameters)) > 16 * 1024:
            raise ApiError(400, "invalid_provider_parameters", "provider parameters are invalid")
        with self.lock, self.db:
            provider = self.db.execute("SELECT * FROM external_providers WHERE id=? AND enabled=1",
                                       (provider_id,)).fetchone()
            if provider is None:
                raise ApiError(404, "provider_not_found", "provider was not found")
            if value["taskType"] not in json.loads(provider["task_types_json"]):
                raise ApiError(409, "provider_task_unsupported", "provider does not accept this task type")
            active = self.db.execute("SELECT COUNT(*) FROM provider_grants WHERE provider_id=? AND expires_at>? AND used=0",
                                     (provider_id, now_seconds())).fetchone()[0]
            if active >= provider["max_concurrent"]:
                raise ApiError(429, "provider_capacity", "provider capacity is exhausted")
            task_id = secrets.token_hex(16)
            token = secrets.token_urlsafe(32)
            expires_at = now_seconds() + 60
            self.db.execute("INSERT INTO provider_grants VALUES(?,?,?,?,?,?,?,0)",
                            (hashlib.sha256(token.encode()).hexdigest(), provider_id, task_id,
                             camera_id, profile_id, segment_id, expires_at))
            self.db.execute("DELETE FROM provider_grants WHERE expires_at<=?", (now_seconds(),))
        return {"schemaVersion": 1, "taskId": task_id, "taskType": value["taskType"],
                "subject": {"cameraId": camera_id, "profileId": profile_id, **({"segmentId": segment_id} if segment_id else {})},
                "expiresAt": expires_at, "mediaGrant": {"token": token, "method": "GET",
                "path": f"/api/v2/provider-media/{task_id}"}, "parameters": parameters}

    def capacity(self) -> dict[str, Any]:
        reports = []
        for row in self.db.execute("SELECT * FROM resource_reports ORDER BY node_id LIMIT ?", (MAX_PAGE,)):
            reports.append({"nodeId": row["node_id"], "cpuCores": row["cpu_cores"],
                            "memoryBytes": row["memory_bytes"], "rated": bool(row["rated"]),
                            "capabilities": json.loads(row["capabilities_json"]),
                            "reservations": json.loads(row["reservations_json"]),
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
        elif path == "/recording-placements" and self.command == "POST":
            value = self.read_json()
            require_exact_object(value, {"cameraId", "profileId", "nodeId", "taskType", "costs"},
                                 {"cameraId", "profileId"})
            self.response(201, STORE.assign(value["cameraId"], value["profileId"], value.get("nodeId", ""),
                                            value.get("taskType", "record-copy"), value.get("costs", {})))
        elif path == "/recording-placements" and self.command == "GET":
            self.response(200, STORE.list_placements())
        elif path == "/archive-targets" and self.command == "GET":
            self.response(200, STORE.list_archive_targets())
        elif path == "/archive-targets" and self.command == "POST":
            self.response(201, STORE.create_archive_target(self.read_json()))
        elif path == "/backup-jobs" and self.command == "GET":
            self.response(200, STORE.list_backup_jobs())
        elif path == "/backup-jobs" and self.command == "POST":
            self.response(202, STORE.create_backup_job(self.read_json()))
        elif path == "/providers" and self.command == "GET":
            self.response(200, STORE.list_providers())
        elif path == "/providers" and self.command == "POST":
            self.response(201, STORE.create_provider(self.read_json()))
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
        else:
            raise ApiError(404, "not_found", "resource was not found")


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
