#!/usr/bin/env python3
"""Loopback-only v2 client enrollment, grant, and media-path service.

The public C++ control plane owns authentication and proxies a fixed route set
to this service.  Camera credentials only occur inside a canonical-CBOR grant
that is signed with Ed25519 and sealed to an enrolled X25519 public key.
"""

from __future__ import annotations

import base64
import ctypes
import ctypes.util
import hashlib
import json
import math
import os
import re
import secrets
import sqlite3
import struct
import time
import uuid
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen


LISTEN = ("127.0.0.1", 8094)
DB_PATH = Path(os.environ.get("WEBOBS_V2_DATABASE", "/config/webobs/v2-clients.db"))
CAMERA_DB_PATH = Path(os.environ.get("WEBOBS_CAMERA_DATABASE", "/config/webobs/cameras.db"))
NVR_CONFIG_PATH = Path(os.environ.get("WEBOBS_NVR_CONFIG", "/config/webobs/nvr.json"))
SCENES_PATH = Path(os.environ.get(
    "WEBOBS_V2_SHARED_SCENES", "/config/webobs/shared-scenes-v2.json"))
SECRET_ROOT = Path(os.environ.get(
    "WEBOBS_CAMERA_SECRET_ROOT", "/run/secrets/webobs-camera-credentials"))
KEY_PATH = Path(os.environ.get(
    "WEBOBS_V2_SIGNING_KEY", "/config/webobs/keys/client-grant-signing.key"))
MAX_BODY = 1024 * 1024
MAX_REGISTRY_RESPONSE = 4 * 1024 * 1024
ENROLLMENT_SECONDS = 10 * 60
DEFAULT_GRANT_SECONDS = 30 * 24 * 60 * 60


def configured_grant_seconds(environment: Mapping[str, str]) -> int:
    if environment.get("WEBOBS_V2_ACCEPTANCE_SHORT_GRANT") != "true":
        return DEFAULT_GRANT_SECONDS
    raw = environment.get("WEBOBS_V2_GRANT_SECONDS", "")
    if not re.fullmatch(r"[0-9]{2,3}", raw):
        raise RuntimeError("acceptance grant duration must be a bounded integer")
    seconds = int(raw)
    if not 30 <= seconds <= 120:
        raise RuntimeError("acceptance grant duration must be between 30 and 120 seconds")
    return seconds


GRANT_SECONDS = configured_grant_seconds(os.environ)
PLAN_SECONDS = 5 * 60
ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
PLATFORMS = {"windows", "linux", "android"}
PERMISSIONS = {"view", "ptz", "talk", "snapshot", "record-local"}
POLICIES = {"auto", "true-direct-only", "gateway", "hybrid", "composite"}
RECEIVERS = {"native", "browser"}
NETWORKS = {"lan", "vpn", "wan"}
DIRECT_ADAPTERS_NATIVE = {"rtsp", "mjpeg", "hls", "whep"}
DIRECT_ADAPTERS_BROWSER = {"mjpeg", "hls", "whep"}
DIRECT_VIDEO_CODECS = {"h264", "h265", "hevc", "mjpeg", "jpeg"}


class ApiError(RuntimeError):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def connect(path: Path | None = None) -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH if path is None else path, timeout=3,
                                 factory=ClosingConnection)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def decode_b64url(value: object, expected: int, field: str) -> bytes:
    if not isinstance(value, str) or len(value) > 256 or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ApiError(400, "invalid_key", f"{field} must be unpadded base64url")
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, base64.binascii.Error) as error:
        raise ApiError(400, "invalid_key", f"{field} is invalid") from error
    if len(decoded) != expected:
        raise ApiError(400, "invalid_key", f"{field} must decode to {expected} bytes")
    return decoded


def sha256(value: bytes | str) -> bytes:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).digest()


def constant_equal(left: bytes, right: bytes) -> bool:
    return secrets.compare_digest(left, right)


def pairing_digest(code: str, salt: bytes | None = None) -> bytes:
    """Return salt || scrypt(code) so a stolen database cannot cheaply enumerate codes."""
    actual_salt = secrets.token_bytes(16) if salt is None else salt
    if len(actual_salt) != 16:
        raise ValueError("pairing-code salt must contain 16 bytes")
    digest = hashlib.scrypt(code.encode("ascii"), salt=actual_salt,
                            n=16384, r=8, p=1, dklen=32)
    return actual_salt + digest


def pairing_matches(stored: bytes, code: str) -> bool:
    value = bytes(stored)
    if len(value) != 48:
        return False
    return constant_equal(value, pairing_digest(code, value[:16]))


def require_internal_admin(value: str) -> None:
    expected = os.environ.get("WEBOBS_V2_INTERNAL_TOKEN", "")
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ApiError(503, "internal_auth_unavailable", "internal administrator authentication is unavailable")
    if not isinstance(value, str) or not secrets.compare_digest(value, expected):
        raise ApiError(403, "internal_auth_rejected", "internal administrator authentication was rejected")


def unique_json(text: str) -> object:
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("duplicate JSON field")
            result[key] = value
        return result
    def reject_constant(value: str):
        raise ValueError(f"non-finite JSON number {value} is not allowed")

    return json.loads(text, object_pairs_hook=pairs, parse_constant=reject_constant)


def _cbor_head(major: int, value: int) -> bytes:
    if value < 0:
        raise ValueError("CBOR length must be non-negative")
    if value < 24:
        return bytes([(major << 5) | value])
    if value <= 0xFF:
        return bytes([(major << 5) | 24, value])
    if value <= 0xFFFF:
        return bytes([(major << 5) | 25]) + struct.pack(">H", value)
    if value <= 0xFFFFFFFF:
        return bytes([(major << 5) | 26]) + struct.pack(">I", value)
    return bytes([(major << 5) | 27]) + struct.pack(">Q", value)


def canonical_cbor(value: object) -> bytes:
    """Encode the bounded grant value with RFC 8949 deterministic ordering."""
    if value is None:
        return b"\xf6"
    if value is False:
        return b"\xf4"
    if value is True:
        return b"\xf5"
    if isinstance(value, int) and not isinstance(value, bool):
        return _cbor_head(0, value) if value >= 0 else _cbor_head(1, -1 - value)
    if isinstance(value, bytes):
        return _cbor_head(2, len(value)) + value
    if isinstance(value, str):
        encoded = value.encode("utf-8")
        return _cbor_head(3, len(encoded)) + encoded
    if isinstance(value, list):
        return _cbor_head(4, len(value)) + b"".join(canonical_cbor(item) for item in value)
    if isinstance(value, dict):
        encoded = [(canonical_cbor(key), canonical_cbor(item)) for key, item in value.items()]
        encoded.sort(key=lambda item: (len(item[0]), item[0]))
        return _cbor_head(5, len(encoded)) + b"".join(key + item for key, item in encoded)
    raise TypeError(f"unsupported CBOR value: {type(value).__name__}")


class Sodium:
    PUBLIC_KEY_BYTES = 32
    SECRET_KEY_BYTES = 64
    SIGNATURE_BYTES = 64
    SEAL_BYTES = 48

    def __init__(self) -> None:
        library = os.environ.get("WEBOBS_LIBSODIUM_LIBRARY") or ctypes.util.find_library("sodium")
        if not library:
            raise RuntimeError("pinned libsodium runtime is unavailable")
        self.library = ctypes.CDLL(library)
        if self.library.sodium_init() < 0:
            raise RuntimeError("libsodium initialization failed")
        self.library.crypto_sign_keypair.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.library.crypto_sign_keypair.restype = ctypes.c_int
        self.library.crypto_sign_detached.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulonglong), ctypes.c_void_p,
            ctypes.c_ulonglong, ctypes.c_void_p,
        ]
        self.library.crypto_sign_detached.restype = ctypes.c_int
        self.library.crypto_sign_verify_detached.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulonglong, ctypes.c_void_p,
        ]
        self.library.crypto_sign_verify_detached.restype = ctypes.c_int
        self.library.crypto_box_seal.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulonglong, ctypes.c_void_p,
        ]
        self.library.crypto_box_seal.restype = ctypes.c_int

    def signing_keypair(self) -> tuple[bytes, bytes]:
        public = ctypes.create_string_buffer(self.PUBLIC_KEY_BYTES)
        secret = ctypes.create_string_buffer(self.SECRET_KEY_BYTES)
        if self.library.crypto_sign_keypair(public, secret) != 0:
            raise RuntimeError("could not create grant signing key")
        return public.raw, secret.raw

    def sign(self, message: bytes, secret_key: bytes) -> bytes:
        signature = ctypes.create_string_buffer(self.SIGNATURE_BYTES)
        length = ctypes.c_ulonglong()
        source = ctypes.create_string_buffer(message, len(message))
        secret = ctypes.create_string_buffer(secret_key, len(secret_key))
        if self.library.crypto_sign_detached(
                signature, ctypes.byref(length), source, len(message), secret) != 0:
            raise RuntimeError("could not sign client grant")
        if length.value != self.SIGNATURE_BYTES:
            raise RuntimeError("client grant signature length is invalid")
        return signature.raw

    def verify(self, signature: bytes, message: bytes, public_key: bytes) -> bool:
        source = ctypes.create_string_buffer(message, len(message))
        signature_buffer = ctypes.create_string_buffer(signature, len(signature))
        public = ctypes.create_string_buffer(public_key, len(public_key))
        return self.library.crypto_sign_verify_detached(
            signature_buffer, source, len(message), public) == 0

    def seal(self, message: bytes, public_key: bytes) -> bytes:
        output = ctypes.create_string_buffer(len(message) + self.SEAL_BYTES)
        source = ctypes.create_string_buffer(message, len(message))
        recipient = ctypes.create_string_buffer(public_key, len(public_key))
        if self.library.crypto_box_seal(output, source, len(message), recipient) != 0:
            raise RuntimeError("could not encrypt client grant")
        return output.raw


SODIUM: Sodium | None = None


def sodium() -> Sodium:
    global SODIUM
    if SODIUM is None:
        SODIUM = Sodium()
    return SODIUM


def initialize() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    KEY_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with connect() as database:
        database.execute("PRAGMA journal_mode=WAL")
        database.execute("PRAGMA synchronous=NORMAL")
        database.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata(
              key TEXT PRIMARY KEY,value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS enrollments(
              id TEXT PRIMARY KEY,name TEXT NOT NULL,platform TEXT NOT NULL,
              signing_public_key BLOB NOT NULL,encryption_public_key BLOB NOT NULL,
              nonce_hash BLOB NOT NULL,
              device_token_hash BLOB NOT NULL,pairing_code_hash BLOB NOT NULL,
              state TEXT NOT NULL,created_at INTEGER NOT NULL,expires_at INTEGER NOT NULL,
              client_id TEXT
            );
            CREATE INDEX IF NOT EXISTS enrollments_expiry ON enrollments(expires_at);
            CREATE TABLE IF NOT EXISTS enrollment_nonces(
              nonce_hash BLOB PRIMARY KEY,created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS clients(
              id TEXT PRIMARY KEY,name TEXT NOT NULL,platform TEXT NOT NULL,
              signing_public_key BLOB NOT NULL,encryption_public_key BLOB NOT NULL,
              device_token_hash BLOB NOT NULL,status TEXT NOT NULL,
              created_at INTEGER NOT NULL,last_seen INTEGER NOT NULL,
              grant_expires_at INTEGER NOT NULL,revision INTEGER NOT NULL,
              revoked_at INTEGER
            );
            CREATE INDEX IF NOT EXISTS clients_token ON clients(device_token_hash);
            CREATE TABLE IF NOT EXISTS grants(
              client_id TEXT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
              camera_id TEXT NOT NULL,profile_ids_json TEXT NOT NULL,
              permissions_json TEXT NOT NULL,credential_mode TEXT NOT NULL,
              credentials_ref TEXT NOT NULL,weak_revocation INTEGER NOT NULL,
              revision INTEGER NOT NULL,updated_at INTEGER NOT NULL,
              PRIMARY KEY(client_id,camera_id)
            );
            CREATE TABLE IF NOT EXISTS media_plans(
              id TEXT PRIMARY KEY,client_id TEXT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
              camera_id TEXT NOT NULL,profile_id TEXT NOT NULL,body_json TEXT NOT NULL,
              created_at INTEGER NOT NULL,expires_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS media_plans_client_expiry
              ON media_plans(client_id,expires_at);
            CREATE TABLE IF NOT EXISTS media_plan_leases(
              plan_id TEXT PRIMARY KEY REFERENCES media_plans(id) ON DELETE CASCADE,
              client_id TEXT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
              activated_at INTEGER NOT NULL,last_seen INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS client_audit(
              id INTEGER PRIMARY KEY AUTOINCREMENT,client_id TEXT NOT NULL,
              sequence INTEGER NOT NULL,event_type TEXT NOT NULL,outcome TEXT NOT NULL,
              camera_id TEXT NOT NULL,created_at INTEGER NOT NULL,
              UNIQUE(client_id,sequence)
            );
            """
        )
        if database.execute("SELECT value FROM metadata WHERE key='revision'").fetchone() is None:
            database.execute("INSERT INTO metadata(key,value) VALUES('revision','0')")
    load_or_create_signing_key()


def load_or_create_signing_key() -> tuple[bytes, bytes]:
    if KEY_PATH.exists():
        if KEY_PATH.is_symlink() or not KEY_PATH.is_file():
            raise RuntimeError("client grant signing key must be a regular file")
        data = KEY_PATH.read_bytes()
        if len(data) != 96:
            raise RuntimeError("client grant signing key length is invalid")
        return data[:32], data[32:]
    public, secret = sodium().signing_keypair()
    temporary = KEY_PATH.with_name(f".{KEY_PATH.name}.{os.getpid()}.{secrets.token_hex(4)}")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, public + secret)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, KEY_PATH)
    os.chmod(KEY_PATH, 0o600)
    return public, secret


def revision(database: sqlite3.Connection, advance: bool = False) -> int:
    current = int(database.execute(
        "SELECT value FROM metadata WHERE key='revision'").fetchone()["value"])
    if advance:
        current += 1
        database.execute("UPDATE metadata SET value=? WHERE key='revision'", (str(current),))
    return current


def public_client(row: sqlite3.Row) -> dict[str, object]:
    return {
        "id": row["id"], "name": row["name"], "platform": row["platform"],
        "status": row["status"], "createdAt": row["created_at"],
        "lastSeen": row["last_seen"], "grantExpiresAt": row["grant_expires_at"],
        "revision": row["revision"], "revokedAt": row["revoked_at"],
    }


def clean_text(value: object, field: str, maximum: int = 128) -> str:
    if not isinstance(value, str):
        raise ApiError(400, "invalid_request", f"{field} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized.encode("utf-8")) > maximum or any(ord(c) < 32 for c in normalized):
        raise ApiError(400, "invalid_request", f"{field} is invalid")
    return normalized


def enrollment_proof(name: str, platform: str, signing_key: bytes,
                     encryption_key: bytes, nonce: bytes) -> bytes:
    return canonical_cbor({
        "purpose": "webobs-client-enrollment-v1", "name": name, "platform": platform,
        "signingPublicKey": signing_key, "encryptionPublicKey": encryption_key,
        "nonce": nonce,
    })


def start_enrollment(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict) or set(payload) != {
            "name", "platform", "signingPublicKey", "encryptionPublicKey",
            "enrollmentNonce", "signature"}:
        raise ApiError(400, "invalid_enrollment", "enrollment fields are invalid")
    name = clean_text(payload["name"], "name")
    platform = clean_text(payload["platform"], "platform", 16).lower()
    if platform not in PLATFORMS:
        raise ApiError(400, "invalid_platform", "platform is unsupported")
    signing_key = decode_b64url(payload["signingPublicKey"], 32, "signingPublicKey")
    encryption_key = decode_b64url(payload["encryptionPublicKey"], 32, "encryptionPublicKey")
    nonce = decode_b64url(payload["enrollmentNonce"], 32, "enrollmentNonce")
    signature = decode_b64url(payload["signature"], 64, "signature")
    proof = enrollment_proof(name, platform, signing_key, encryption_key, nonce)
    if not sodium().verify(signature, proof, signing_key):
        raise ApiError(403, "enrollment_signature_rejected",
                       "enrollment signature does not prove possession of the signing key")
    now = int(time.time())
    enrollment_id = uuid.uuid4().hex
    pairing_code = f"{secrets.randbelow(100_000_000):08d}"
    device_token = secrets.token_urlsafe(48)
    with connect() as database:
        database.execute("DELETE FROM enrollments WHERE expires_at<=?", (now,))
        if database.execute("SELECT COUNT(*) AS count FROM enrollments WHERE state='pending'").fetchone()["count"] >= 32:
            raise ApiError(429, "enrollment_limit", "too many pending enrollments")
        try:
            database.execute("INSERT INTO enrollment_nonces(nonce_hash,created_at) VALUES(?,?)",
                             (sha256(nonce), now))
        except sqlite3.IntegrityError as error:
            raise ApiError(409, "enrollment_replayed",
                           "this enrollment nonce has already been used") from error
        database.execute(
            "INSERT INTO enrollments(id,name,platform,signing_public_key,encryption_public_key,"
            "nonce_hash,device_token_hash,pairing_code_hash,state,created_at,expires_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (enrollment_id, name, platform, signing_key, encryption_key, sha256(nonce),
             sha256(device_token), pairing_digest(pairing_code), "pending", now,
             now + ENROLLMENT_SECONDS),
        )
    return {
        "enrollmentId": enrollment_id, "pairingCode": pairing_code,
        "deviceToken": device_token, "expiresAt": now + ENROLLMENT_SECONDS,
    }


def list_enrollments() -> dict[str, object]:
    now = int(time.time())
    with connect() as database:
        rows = database.execute(
            "SELECT id,name,platform,state,created_at,expires_at FROM enrollments "
            "WHERE expires_at>? ORDER BY created_at DESC LIMIT 32", (now,)).fetchall()
    return {"enrollments": [{
        "id": row["id"], "name": row["name"], "platform": row["platform"],
        "state": row["state"], "createdAt": row["created_at"], "expiresAt": row["expires_at"],
    } for row in rows]}


def _safe_reference(value: object, field: str) -> str:
    if not isinstance(value, str) or len(value) > 256 or ".." in value.split("/") or not re.fullmatch(
            r"[A-Za-z0-9._/-]{1,256}", value):
        raise ApiError(400, "invalid_credentials_ref", f"{field} is invalid")
    return value


def _load_secret(reference: str) -> dict[str, str]:
    root = SECRET_ROOT.resolve()
    path = (root / f"{reference}.json").resolve()
    if root not in path.parents or not path.is_file() or path.is_symlink():
        raise ApiError(409, "credentials_unavailable", "camera credentials are unavailable")
    try:
        value = unique_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ApiError(409, "credentials_unavailable", "camera credentials are unavailable") from error
    if not isinstance(value, dict) or set(value) != {"username", "password"} or not all(
            isinstance(value[key], str) and len(value[key]) <= 512 for key in value):
        raise ApiError(409, "credentials_unavailable", "camera credentials are unavailable")
    return {"username": value["username"], "password": value["password"]}


def _camera(camera_id: str) -> tuple[sqlite3.Row, list[sqlite3.Row]]:
    if not CAMERA_DB_PATH.is_file():
        raise ApiError(503, "camera_registry_unavailable", "Camera Registry is unavailable")
    with connect(CAMERA_DB_PATH) as database:
        camera = database.execute("SELECT * FROM cameras WHERE id=?", (camera_id,)).fetchone()
        if camera is None:
            raise ApiError(404, "camera_not_found", "camera is unknown")
        profiles = database.execute(
            "SELECT id,name,role,endpoint,video_codec,audio_codec,width,height,fps "
            "FROM stream_profiles WHERE camera_id=? ORDER BY role,id", (camera_id,)).fetchall()
    return camera, profiles


def _profile_adapter(camera_adapter: str, endpoint: str) -> str:
    scheme = urlsplit(endpoint).scheme.lower()
    if scheme in {"rtsp", "rtsps"}:
        return "rtsp"
    if camera_adapter == "onvif" and scheme in {"http", "https"}:
        return "mjpeg"
    return camera_adapter.lower()


def _validate_grants(raw_grants: object) -> list[dict[str, object]]:
    if not isinstance(raw_grants, list) or not 1 <= len(raw_grants) <= 64:
        raise ApiError(400, "invalid_grants", "cameraGrants must contain one to 64 cameras")
    grants = []
    seen = set()
    for raw in raw_grants:
        allowed = {"cameraId", "profileIds", "permissions", "credentialMode", "credentialsRef"}
        if not isinstance(raw, dict) or not set(raw).issubset(allowed):
            raise ApiError(400, "invalid_grants", "camera grant fields are invalid")
        camera_id = raw.get("cameraId")
        if not isinstance(camera_id, str) or not ID_RE.fullmatch(camera_id) or camera_id in seen:
            raise ApiError(400, "invalid_grants", "cameraId is invalid or duplicated")
        seen.add(camera_id)
        camera, profiles = _camera(camera_id)
        known_profiles = {row["id"] for row in profiles}
        profile_ids = raw.get("profileIds", sorted(known_profiles))
        if not isinstance(profile_ids, list) or not 1 <= len(profile_ids) <= 16 or any(
                not isinstance(item, str) or item not in known_profiles for item in profile_ids):
            raise ApiError(400, "invalid_grants", "profileIds contains an unknown profile")
        permissions = raw.get("permissions", ["view"])
        if not isinstance(permissions, list) or not permissions or any(
                not isinstance(item, str) or item not in PERMISSIONS for item in permissions):
            raise ApiError(400, "invalid_grants", "permissions are invalid")
        permissions = sorted(set(permissions))
        if "view" not in permissions:
            raise ApiError(400, "invalid_grants", "view permission is required")
        mode = raw.get("credentialMode", "existing")
        if mode not in {"existing", "dedicated"}:
            raise ApiError(400, "invalid_grants", "credentialMode is invalid")
        reference = raw.get("credentialsRef", camera["credentials_ref"])
        reference = _safe_reference(reference, "credentialsRef")
        _load_secret(reference)
        if mode == "dedicated" and reference == camera["credentials_ref"]:
            raise ApiError(409, "dedicated_credentials_required",
                           "dedicated mode requires a distinct credential reference")
        grants.append({
            "cameraId": camera_id, "profileIds": sorted(set(profile_ids)),
            "permissions": permissions, "credentialMode": mode,
            "credentialsRef": reference, "weakRevocation": mode != "dedicated",
        })
    return grants


def approve_enrollment(enrollment_id: str, payload: object) -> dict[str, object]:
    if not isinstance(payload, dict) or set(payload) != {"pairingCode", "cameraGrants"}:
        raise ApiError(400, "invalid_approval", "approval fields are invalid")
    code = payload.get("pairingCode")
    if not isinstance(code, str) or not re.fullmatch(r"[0-9]{8}", code):
        raise ApiError(400, "invalid_pairing_code", "pairingCode must contain eight digits")
    grants = _validate_grants(payload["cameraGrants"])
    now = int(time.time())
    with connect() as database:
        row = database.execute("SELECT * FROM enrollments WHERE id=?", (enrollment_id,)).fetchone()
        if row is None:
            raise ApiError(404, "enrollment_not_found", "enrollment is unknown")
        if row["expires_at"] <= now:
            raise ApiError(410, "enrollment_expired", "enrollment has expired")
        if row["state"] != "pending":
            raise ApiError(409, "enrollment_state", "enrollment is not pending")
        if not pairing_matches(row["pairing_code_hash"], code):
            raise ApiError(403, "pairing_code_rejected", "pairing code does not match")
        client_id = uuid.uuid4().hex
        next_revision = revision(database, True)
        expires = now + GRANT_SECONDS
        database.execute(
            "INSERT INTO clients(id,name,platform,signing_public_key,encryption_public_key,"
            "device_token_hash,status,created_at,last_seen,grant_expires_at,revision) "
            "VALUES(?,?,?,?,?,?,'active',?,?,?,?)",
            (client_id, row["name"], row["platform"], row["signing_public_key"],
             row["encryption_public_key"], row["device_token_hash"], now, now, expires, next_revision),
        )
        for grant in grants:
            database.execute(
                "INSERT INTO grants(client_id,camera_id,profile_ids_json,permissions_json,"
                "credential_mode,credentials_ref,weak_revocation,revision,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (client_id, grant["cameraId"], json.dumps(grant["profileIds"], separators=(",", ":")),
                 json.dumps(grant["permissions"], separators=(",", ":")), grant["credentialMode"],
                 grant["credentialsRef"], int(grant["weakRevocation"]), next_revision, now),
            )
        database.execute("UPDATE enrollments SET state='approved',client_id=? WHERE id=?",
                         (client_id, enrollment_id))
    return {"clientId": client_id, "state": "approved", "grantExpiresAt": expires,
            "revision": next_revision}


def _grant_payload(database: sqlite3.Connection, client: sqlite3.Row) -> dict[str, object]:
    items = []
    rows = database.execute("SELECT * FROM grants WHERE client_id=? ORDER BY camera_id",
                            (client["id"],)).fetchall()
    for row in rows:
        camera, profiles = _camera(row["camera_id"])
        profile_ids = set(json.loads(row["profile_ids_json"]))
        selected = [{
            "id": profile["id"], "name": profile["name"], "role": profile["role"],
            "endpoint": profile["endpoint"],
            "adapter": _profile_adapter(camera["adapter"], profile["endpoint"]),
            "videoCodec": profile["video_codec"],
            "audioCodec": profile["audio_codec"], "width": profile["width"],
            "height": profile["height"], "fpsMilli": int(round(profile["fps"] * 1000)),
        } for profile in profiles if profile["id"] in profile_ids]
        credentials = _load_secret(row["credentials_ref"])
        items.append({
            "cameraId": row["camera_id"], "name": camera["name"], "adapter": camera["adapter"],
            "profiles": selected, "permissions": json.loads(row["permissions_json"]),
            "credentials": credentials, "credentialMode": row["credential_mode"],
            "weakRevocation": bool(row["weak_revocation"]),
        })
    return {
        "format": "webobs-client-grant-v1", "contractVersion": 1,
        "clientId": client["id"], "issuedAt": int(time.time()),
        "expiresAt": client["grant_expires_at"], "revision": client["revision"],
        "cameras": items,
    }


def sealed_bundle(database: sqlite3.Connection, client: sqlite3.Row) -> dict[str, object]:
    public, secret = load_or_create_signing_key()
    encoded = canonical_cbor(_grant_payload(database, client))
    signature = sodium().sign(encoded, secret)
    sealed = sodium().seal(signature + encoded, client["encryption_public_key"])
    return {
        "format": "webobs-client-grant+cbor-sealed-v1", "contractVersion": 1,
        "keyId": hashlib.sha256(public).hexdigest()[:16],
        "serverSigningPublicKey": b64url(public), "ciphertext": b64url(sealed),
    }


def complete_enrollment(enrollment_id: str, token: str) -> tuple[int, dict[str, object]]:
    now = int(time.time())
    with connect() as database:
        row = database.execute("SELECT * FROM enrollments WHERE id=?", (enrollment_id,)).fetchone()
        if row is None:
            raise ApiError(404, "enrollment_not_found", "enrollment is unknown")
        if row["expires_at"] <= now:
            raise ApiError(410, "enrollment_expired", "enrollment has expired")
        if not constant_equal(row["device_token_hash"], sha256(token)):
            raise ApiError(401, "device_token_rejected", "device token is invalid")
        if row["state"] == "pending":
            return 202, {"enrollmentId": enrollment_id, "state": "pending", "expiresAt": row["expires_at"]}
        if row["state"] != "approved" or not row["client_id"]:
            raise ApiError(409, "enrollment_state", "enrollment cannot be completed")
        client = database.execute("SELECT * FROM clients WHERE id=?", (row["client_id"],)).fetchone()
        return 200, {"client": public_client(client), "grantBundle": sealed_bundle(database, client)}


def authenticate_device(token: str) -> sqlite3.Row:
    if not isinstance(token, str) or not 32 <= len(token) <= 128:
        raise ApiError(401, "device_token_required", "device token is required")
    now = int(time.time())
    token_hash = sha256(token)
    with connect() as database:
        client = database.execute(
            "SELECT * FROM clients WHERE status='active' AND device_token_hash=?", (token_hash,)).fetchone()
        if client is None:
            raise ApiError(401, "device_token_rejected", "device token is invalid")
        if client["grant_expires_at"] <= now:
            raise ApiError(401, "grant_expired", "offline authorization has expired")
        expires = now + GRANT_SECONDS
        database.execute("UPDATE clients SET last_seen=?,grant_expires_at=? WHERE id=?",
                         (now, expires, client["id"]))
        return database.execute("SELECT * FROM clients WHERE id=?", (client["id"],)).fetchone()


def _shared_scene_valid(scene: object) -> bool:
    """Validate the v2 local subset without accepting hidden endpoint or secret fields."""
    root_fields = {"schemaVersion", "revision", "id", "name", "canvas", "sources", "items"}
    source_fields = {
        "id", "kind", "name", "cameraId", "profileId", "hardwareDecode",
        "text", "color", "filePath", "muted", "volume", "syncOffsetMs",
        "monitoring", "audioTrack", "filters", "sceneId",
    }
    item_fields = {
        "id", "sourceId", "x", "y", "width", "height", "scaleMode", "crop",
        "zIndex", "visible", "locked", "groupId", "rotation", "opacity", "blendMode",
    }
    if not isinstance(scene, dict) or set(scene) != root_fields or scene.get("schemaVersion") != 5 or \
            not isinstance(scene.get("revision"), int) or scene["revision"] < 0 or \
            not isinstance(scene.get("id"), str) or not ID_RE.fullmatch(scene["id"]) or \
            not isinstance(scene.get("name"), str) or not 1 <= len(scene["name"].encode("utf-8")) <= 128:
        return False
    canvas = scene.get("canvas")
    if not isinstance(canvas, dict) or set(canvas) != {"width", "height", "backgroundColor"} or \
            not all(isinstance(canvas.get(key), int) and 16 <= canvas[key] <= 8192
                    and canvas[key] % 2 == 0 for key in ("width", "height")) or \
            not isinstance(canvas.get("backgroundColor"), str) or \
            not re.fullmatch(r"#[0-9A-Fa-f]{6}", canvas["backgroundColor"]):
        return False
    sources = scene.get("sources")
    items = scene.get("items")
    if not isinstance(sources, list) or len(sources) > 64 or not isinstance(items, list) or len(items) > 256:
        return False
    source_ids: set[str] = set()
    for source in sources:
        if not isinstance(source, dict) or not set(source).issubset(source_fields):
            return False
        source_id = source.get("id")
        kind = source.get("kind")
        if not isinstance(source_id, str) or not ID_RE.fullmatch(source_id) or source_id in source_ids or \
                kind not in {"camera", "text", "color", "image", "nested"}:
            return False
        source_ids.add(source_id)
        if not isinstance(source.get("name"), str) or not 1 <= len(source["name"].encode("utf-8")) <= 128:
            return False
        if kind == "camera" and (not isinstance(source.get("cameraId"), str) or
                not ID_RE.fullmatch(source["cameraId"]) or
                not isinstance(source.get("profileId"), str) or
                not ID_RE.fullmatch(source["profileId"]) or
                source.get("hardwareDecode", "auto") not in {"auto", "on", "off"}):
            return False
        if kind == "text" and (not isinstance(source.get("text"), str) or
                not 1 <= len(source["text"].encode("utf-8")) <= 8192 or
                not isinstance(source.get("color"), str) or
                not re.fullmatch(r"#[0-9A-Fa-f]{6}", source["color"])):
            return False
        if kind == "color" and (not isinstance(source.get("color"), str) or
                not re.fullmatch(r"#[0-9A-Fa-f]{6}", source["color"])):
            return False
        if "muted" in source and not isinstance(source["muted"], bool):
            return False
        if "volume" in source and (not isinstance(source["volume"], (int, float)) or
                isinstance(source["volume"], bool) or not math.isfinite(source["volume"]) or
                not 0 <= source["volume"] <= 1):
            return False
        if "syncOffsetMs" in source and (not isinstance(source["syncOffsetMs"], int) or
                isinstance(source["syncOffsetMs"], bool) or not -10000 <= source["syncOffsetMs"] <= 10000):
            return False
        if source.get("monitoring", "off") not in {"off", "monitor-only", "monitor-and-output"}:
            return False
        if "audioTrack" in source and (not isinstance(source["audioTrack"], int) or
                isinstance(source["audioTrack"], bool) or not 1 <= source["audioTrack"] <= 6):
            return False
        filters = source.get("filters", [])
        if not isinstance(filters, list) or len(filters) > 16:
            return False
        filter_ids: set[str] = set()
        for scene_filter in filters:
            if not isinstance(scene_filter, dict) or set(scene_filter) != {
                    "id", "kind", "enabled", "amount", "value"}:
                return False
            filter_id = scene_filter.get("id")
            filter_kind = scene_filter.get("kind")
            amount = scene_filter.get("amount")
            value = scene_filter.get("value")
            if not isinstance(filter_id, str) or not ID_RE.fullmatch(filter_id) or \
                    filter_id in filter_ids or filter_kind not in {
                        "crop-pad", "opacity", "color-correction", "mask-blend",
                        "lut", "scaling", "delay"} or \
                    not isinstance(scene_filter.get("enabled"), bool) or \
                    not isinstance(amount, (int, float)) or isinstance(amount, bool) or \
                    not math.isfinite(amount) or not -10000 <= amount <= 10000 or \
                    not isinstance(value, str) or len(value.encode("utf-8")) > 4096:
                return False
            filter_ids.add(filter_id)
            if filter_kind in {"mask-blend", "lut"} and (
                    not value.startswith("/assets/") or ".." in value.split("/")):
                return False
            if filter_kind == "scaling":
                match = re.fullmatch(r"([0-9]{2,4})x([0-9]{2,4})", value)
                if not match or any(not 16 <= int(dimension) <= 8192 for dimension in match.groups()):
                    return False
        if kind == "image":
            file_path = source.get("filePath")
            if not isinstance(file_path, str) or not file_path.startswith("/assets/") or ".." in file_path.split("/"):
                return False
        if kind == "nested" and (not isinstance(source.get("sceneId"), str) or
                not ID_RE.fullmatch(source["sceneId"]) or source["sceneId"] == scene["id"]):
            return False
    item_ids: set[str] = set()
    for item in items:
        if not isinstance(item, dict) or not set(item).issubset(item_fields):
            return False
        item_id = item.get("id")
        if not isinstance(item_id, str) or not ID_RE.fullmatch(item_id) or item_id in item_ids or \
                item.get("sourceId") not in source_ids:
            return False
        item_ids.add(item_id)
        for field in ("x", "y", "width", "height", "zIndex", "visible", "locked",
                      "rotation", "opacity", "blendMode"):
            if field not in item:
                return False
        if any(not isinstance(item[field], int) or isinstance(item[field], bool) or
               not -32768 <= item[field] <= 32768 for field in ("x", "y")) or \
                any(not isinstance(item[field], int) or isinstance(item[field], bool) or
                    not 1 <= item[field] <= 8192 for field in ("width", "height")) or \
                not isinstance(item["zIndex"], int) or isinstance(item["zIndex"], bool) or \
                not 0 <= item["zIndex"] < len(items) or \
                not isinstance(item["visible"], bool) or not isinstance(item["locked"], bool) or \
                not isinstance(item["rotation"], (int, float)) or isinstance(item["rotation"], bool) or \
                not math.isfinite(item["rotation"]) or not -360 <= item["rotation"] <= 360 or \
                not isinstance(item["opacity"], (int, float)) or isinstance(item["opacity"], bool) or \
                not math.isfinite(item["opacity"]) or not 0 <= item["opacity"] <= 1:
            return False
        crop = item.get("crop")
        if not isinstance(crop, dict) or set(crop) != {"top", "right", "bottom", "left"} or \
                any(not isinstance(crop[field], int) or isinstance(crop[field], bool) or
                    not 0 <= crop[field] <= 8192 for field in crop):
            return False
        if "groupId" in item and (not isinstance(item["groupId"], str) or
                (item["groupId"] and not ID_RE.fullmatch(item["groupId"]))):
            return False
        if item.get("scaleMode", "contain") not in {"contain", "cover", "stretch"} or \
                item.get("blendMode", "normal") != "normal":
            return False
    if sorted(item["zIndex"] for item in items) != list(range(len(items))):
        return False
    return True


def _shared_scene_graph_valid(scenes: list[object]) -> bool:
    """Require every nested reference to exist and cap expansion at two levels."""
    by_id: dict[str, dict[str, object]] = {}
    for scene in scenes:
        if not isinstance(scene, dict) or scene["id"] in by_id:
            return False
        by_id[scene["id"]] = scene

    graph: dict[str, set[str]] = {}
    for scene_id, scene in by_id.items():
        graph[scene_id] = {
            source["sceneId"] for source in scene["sources"]
            if source.get("kind") == "nested"
        }
        if any(target not in by_id for target in graph[scene_id]):
            return False

    def visit(scene_id: str, path: tuple[str, ...]) -> bool:
        if scene_id in path or len(path) > 2:
            return False
        return all(visit(target, path + (scene_id,)) for target in graph[scene_id])

    return all(visit(scene_id, ()) for scene_id in by_id)


def shared_scenes() -> list[object]:
    try:
        value = unique_json(SCENES_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        raise ApiError(503, "shared_scenes_unavailable", "shared Scene document is invalid")
    if not isinstance(value, dict) or set(value) != {"schemaVersion", "scenes"} or \
            value["schemaVersion"] != 1 or not isinstance(value["scenes"], list) or \
            len(value["scenes"]) > 64:
        raise ApiError(503, "shared_scenes_unavailable", "shared Scene document is invalid")
    encoded = json.dumps(value["scenes"], separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_BODY or re.search(
            r'(?i)(rtsp|rtsps|https?)://|"(?:password|credentials?|secret|token|endpoint|url|rtspUrl)"\s*:',
            encoded) or \
            any(not _shared_scene_valid(scene) for scene in value["scenes"]) or \
            not _shared_scene_graph_valid(value["scenes"]):
        raise ApiError(503, "shared_scenes_unavailable", "shared Scene document is unsafe")
    return value["scenes"]


def bootstrap(client: sqlite3.Row, since: int) -> dict[str, object]:
    with connect() as database:
        current = revision(database)
        grants = database.execute("SELECT * FROM grants WHERE client_id=? ORDER BY camera_id",
                                  (client["id"],)).fetchall()
        cameras = []
        for grant in grants:
            camera, profiles = _camera(grant["camera_id"])
            selected = set(json.loads(grant["profile_ids_json"]))
            cameras.append({
                "id": camera["id"], "name": camera["name"], "adapter": camera["adapter"],
                "health": camera["health"], "profiles": [{
                    "id": item["id"], "name": item["name"], "role": item["role"],
                    "videoCodec": item["video_codec"], "audioCodec": item["audio_codec"],
                    "width": item["width"], "height": item["height"], "fps": item["fps"],
                } for item in profiles if item["id"] in selected],
                "permissions": json.loads(grant["permissions_json"]),
                "weakRevocation": bool(grant["weak_revocation"]),
            })
        changed = since < current
        return {
            "contractVersion": 1, "revision": current, "changed": changed,
            "client": public_client(client), "cameras": cameras if changed else [],
            "grantBundle": sealed_bundle(database, client),
            "sharedScenes": shared_scenes() if changed else [],
            "syncPolicy": "server-read-only-local-layouts",
            "onlineValidationIntervalSeconds": 10,
        }


def archive_topology(camera_id: str) -> str:
    try:
        value = json.loads(NVR_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "off"
    for camera in value.get("cameras", []) if isinstance(value, dict) else []:
        if isinstance(camera, dict) and (camera.get("cameraId") == camera_id or camera.get("id") == camera_id):
            if camera.get("policy", "off") == "off":
                return "off"
            return "server-transcode" if camera.get("mode") == "transcode" else "server-copy"
    return "off"


def _profile_for_client(client_id: str, camera_id: str, profile_id: str) -> tuple[sqlite3.Row, sqlite3.Row]:
    with connect() as database:
        grant = database.execute("SELECT * FROM grants WHERE client_id=? AND camera_id=?",
                                 (client_id, camera_id)).fetchone()
    if grant is None or "view" not in json.loads(grant["permissions_json"]):
        raise ApiError(403, "camera_scope_rejected", "client is not granted this camera")
    if profile_id not in json.loads(grant["profile_ids_json"]):
        raise ApiError(403, "profile_scope_rejected", "client is not granted this profile")
    camera, profiles = _camera(camera_id)
    profile = next((item for item in profiles if item["id"] == profile_id), None)
    if profile is None:
        raise ApiError(404, "profile_not_found", "profile is unknown")
    return camera, profile


def require_camera_permission(client_id: str, camera_id: str, permission: str) -> None:
    with connect() as database:
        grant = database.execute("SELECT permissions_json FROM grants WHERE client_id=? AND camera_id=?",
                                 (client_id, camera_id)).fetchone()
    if grant is None or permission not in json.loads(grant["permissions_json"]):
        raise ApiError(403, "camera_permission_rejected",
                       f"client is not granted {permission} permission for this camera")


def registry_request(method: str, camera_id: str, operation: str,
                     payload: object | None = None) -> object:
    path = f"/cameras/{camera_id}/onvif/{operation}"
    body = None if payload is None else json.dumps(
        payload, separators=(",", ":"), allow_nan=False).encode("utf-8")
    request = Request(f"http://127.0.0.1:8092{path}", data=body, method=method,
                      headers={"Accept": "application/json", **(
                          {"Content-Type": "application/json"} if body is not None else {})})
    try:
        with urlopen(request, timeout=12) as response:
            encoded = response.read(MAX_REGISTRY_RESPONSE + 1)
            if len(encoded) > MAX_REGISTRY_RESPONSE:
                raise ApiError(502, "device_operation_failed", "device operation response is too large")
            value = unique_json(encoded.decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("registry response is not an object")
            return value
    except HTTPError as error:
        status = error.code if error.code in {400, 401, 404, 409, 429, 502, 503} else 502
        raise ApiError(status, "device_operation_failed", "camera operation failed safely") from error
    except (URLError, TimeoutError, UnicodeDecodeError, ValueError, OSError) as error:
        raise ApiError(503, "device_operation_unavailable",
                       "camera operation service is unavailable") from error


def client_camera_operation(client_id: str, camera_id: str, operation: str,
                            payload: object | None) -> object:
    permission = "snapshot" if operation == "snapshot" else "talk" if operation == "talk" else "ptz"
    require_camera_permission(client_id, camera_id, permission)
    if operation == "presets":
        return registry_request("GET", camera_id, operation)
    if operation == "snapshot":
        if payload not in (None, {}):
            raise ApiError(400, "invalid_device_operation", "snapshot does not accept a request body")
        return registry_request("POST", camera_id, operation)
    if not isinstance(payload, dict):
        raise ApiError(400, "invalid_device_operation", "camera operation requires a JSON object")
    return registry_request("POST", camera_id, operation, payload)


def _decoder(platform: str, hardware: list[str], codec: str) -> str:
    normalized = {str(item).lower() for item in hardware if isinstance(item, str)}
    candidates = {
        "windows": ("d3d11", "d3d11"), "linux": ("vaapi", "vaapi"),
        "android": ("mediacodec", "mediacodec"),
    }
    requested, selected = candidates[platform]
    if requested in normalized and codec in DIRECT_VIDEO_CODECS:
        return selected
    return "software"


def create_media_plan(client: sqlite3.Row, payload: object) -> tuple[int, dict[str, object]]:
    allowed = {"cameraId", "profileId", "policy", "receiverKind", "networkClass", "reachability",
               "protocols", "videoCodecs", "hardwareDecoders", "requiresComposite", "browserDirectEligible"}
    if not isinstance(payload, dict) or not set(payload).issubset(allowed):
        raise ApiError(400, "invalid_media_plan", "media plan fields are invalid")
    camera_id = payload.get("cameraId")
    profile_id = payload.get("profileId")
    if not isinstance(camera_id, str) or not ID_RE.fullmatch(camera_id) or not isinstance(
            profile_id, str) or not ID_RE.fullmatch(profile_id):
        raise ApiError(400, "invalid_media_plan", "cameraId and profileId are required")
    policy = payload.get("policy", "auto")
    receiver = payload.get("receiverKind", "native")
    network = payload.get("networkClass", "lan")
    reachability = payload.get("reachability", "unknown")
    if policy not in POLICIES or receiver not in RECEIVERS or network not in NETWORKS or reachability not in {
            "reachable", "unreachable", "unknown"}:
        raise ApiError(400, "invalid_media_plan", "media plan policy or topology fields are invalid")
    for field in ("protocols", "videoCodecs", "hardwareDecoders"):
        if not isinstance(payload.get(field, []), list) or len(payload.get(field, [])) > 32:
            raise ApiError(400, "invalid_media_plan", f"{field} is invalid")
    camera, profile = _profile_for_client(client["id"], camera_id, profile_id)
    adapter = _profile_adapter(camera["adapter"], profile["endpoint"])
    codec = profile["video_codec"].lower().replace(".", "")
    if codec == "hevc":
        codec = "h265"
    protocols = {str(item).lower() for item in payload.get("protocols", []) if isinstance(item, str)}
    codecs = {str(item).lower().replace(".", "") for item in payload.get("videoCodecs", []) if isinstance(item, str)}
    direct_adapters = DIRECT_ADAPTERS_NATIVE if receiver == "native" else DIRECT_ADAPTERS_BROWSER
    browser_allowed = receiver == "native" or payload.get("browserDirectEligible") is True
    direct_reason = ""
    if network == "wan":
        direct_reason = "network_not_lan_or_vpn"
    elif reachability != "reachable":
        direct_reason = "camera_not_reachable" if reachability == "unreachable" else "reachability_not_proven"
    elif payload.get("requiresComposite") is True:
        direct_reason = "composite_feature_required"
    elif adapter not in direct_adapters or adapter not in protocols:
        direct_reason = "protocol_not_supported"
    elif codec not in codecs:
        direct_reason = "codec_not_supported"
    elif not browser_allowed:
        direct_reason = "browser_direct_policy_unverified"

    status = "active"
    if policy == "true-direct-only" and direct_reason:
        topology = "true-direct"
        status = "rejected"
    elif policy == "composite" or payload.get("requiresComposite") is True:
        topology = "composite"
    elif policy == "hybrid":
        topology = "hybrid"
    elif policy == "gateway":
        topology = "gateway-direct"
    elif not direct_reason:
        topology = "true-direct"
    elif direct_reason == "codec_not_supported":
        topology = "hybrid"
    elif direct_reason == "composite_feature_required":
        topology = "composite"
    else:
        topology = "gateway-direct"

    decoder = _decoder(client["platform"], payload.get("hardwareDecoders", []), codec) \
        if topology == "true-direct" else "browser" if topology == "gateway-direct" else "server"
    renderer = "qt-quick" if topology == "true-direct" and receiver == "native" else \
        "browser" if receiver == "browser" or topology == "gateway-direct" else "libobs"
    encoder = "none" if topology in {"true-direct", "gateway-direct"} else \
        "track-converter" if topology == "hybrid" else "obs-program"
    owner = f"client:{client['id']}" if topology == "true-direct" else \
        "docker:mediamtx" if topology == "gateway-direct" else \
        "docker:transcoder" if topology == "hybrid" else "docker:libobs"
    now = int(time.time())
    plan_id = uuid.uuid4().hex
    plan = {
        "contractVersion": 1, "planId": plan_id, "cameraId": camera_id,
        "profileId": profile_id, "status": status, "topology": topology,
        "receiverKind": receiver, "archiveTopology": archive_topology(camera_id),
        "decoder": decoder, "renderer": renderer, "encoder": encoder,
        "upstreamOwner": owner, "liveServerMediaExpected": topology != "true-direct",
        "fallbackReason": direct_reason if topology != "true-direct" or status == "rejected" else "",
        "expiresAt": now + PLAN_SECONDS,
    }
    with connect() as database:
        database.execute(
            "DELETE FROM media_plans WHERE expires_at<=? AND NOT EXISTS "
            "(SELECT 1 FROM media_plan_leases WHERE media_plan_leases.plan_id=media_plans.id)",
            (now,))
        database.execute(
            "INSERT INTO media_plans(id,client_id,camera_id,profile_id,body_json,created_at,expires_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (plan_id, client["id"], camera_id, profile_id,
             json.dumps(plan, separators=(",", ":"), sort_keys=True), now, now + PLAN_SECONDS),
        )
    return (409 if status == "rejected" else 201), plan


def _media_plan_row(client_id: str, plan_id: str, allow_expired: bool = False) -> sqlite3.Row:
    if not re.fullmatch(r"[0-9a-f]{32}", plan_id):
        raise ApiError(404, "media_plan_not_found", "media plan is unknown")
    with connect() as database:
        row = database.execute("SELECT * FROM media_plans WHERE id=? AND client_id=?",
                               (plan_id, client_id)).fetchone()
    if row is None or (not allow_expired and row["expires_at"] <= int(time.time())):
        raise ApiError(404, "media_plan_not_found", "media plan is unknown or expired")
    return row


def get_media_plan(client_id: str, plan_id: str) -> dict[str, object]:
    row = _media_plan_row(client_id, plan_id)
    return json.loads(row["body_json"])


def activate_media_plan(client_id: str, plan_id: str) -> dict[str, object]:
    row = _media_plan_row(client_id, plan_id)
    plan = json.loads(row["body_json"])
    if plan.get("status") != "active" or plan.get("topology") == "true-direct":
        raise ApiError(409, "media_plan_not_activatable",
                       "only an active server fallback plan can be activated")
    # Recheck the grant at activation time so a stale plan can never widen a
    # client's Camera/Profile authorization.
    _profile_for_client(client_id, row["camera_id"], row["profile_id"])
    now = int(time.time())
    with connect() as database:
        database.execute(
            "INSERT INTO media_plan_leases(plan_id,client_id,activated_at,last_seen) VALUES(?,?,?,?) "
            "ON CONFLICT(plan_id) DO UPDATE SET last_seen=excluded.last_seen",
            (plan_id, client_id, now, now),
        )
    return {
        "contractVersion": 1, "planId": plan_id, "clientId": client_id,
        "cameraId": row["camera_id"], "profileId": row["profile_id"],
        "topology": plan["topology"], "fallbackReason": plan["fallbackReason"],
        "expiresAt": row["expires_at"],
        "mediaEndpoint": {
            "adapter": "whep", "endpoint": f"/api/v2/media-plans/{plan_id}/whep",
            "authorization": "device-bearer",
        },
    }


def media_plan_activation(client_id: str, plan_id: str) -> dict[str, object]:
    row = _media_plan_row(client_id, plan_id)
    _profile_for_client(client_id, row["camera_id"], row["profile_id"])
    now = int(time.time())
    with connect() as database:
        lease = database.execute(
            "SELECT * FROM media_plan_leases WHERE plan_id=? AND client_id=?",
            (plan_id, client_id)).fetchone()
        if lease is not None:
            database.execute(
                "UPDATE media_plan_leases SET last_seen=? WHERE plan_id=? AND client_id=?",
                (now, plan_id, client_id))
    if lease is None:
        raise ApiError(409, "media_plan_not_active", "media plan has no active server lease")
    plan = json.loads(row["body_json"])
    return {
        "contractVersion": 1, "planId": plan_id, "clientId": client_id,
        "cameraId": row["camera_id"], "profileId": row["profile_id"],
        "topology": plan["topology"], "fallbackReason": plan["fallbackReason"],
        "expiresAt": row["expires_at"],
    }


def release_media_plan(client_id: str, plan_id: str) -> dict[str, object]:
    row = _media_plan_row(client_id, plan_id, allow_expired=True)
    with connect() as database:
        removed = database.execute(
            "DELETE FROM media_plan_leases WHERE plan_id=? AND client_id=?",
            (plan_id, client_id)).rowcount
        if row["expires_at"] <= int(time.time()):
            database.execute("DELETE FROM media_plans WHERE id=? AND client_id=?",
                             (plan_id, client_id))
    return {"planId": plan_id, "released": bool(removed)}


def audit_batch(client_id: str, payload: object) -> dict[str, object]:
    if not isinstance(payload, dict) or set(payload) != {"events"} or not isinstance(payload["events"], list) or \
            len(payload["events"]) > 128:
        raise ApiError(400, "invalid_audit_batch", "events must be an array of at most 128 items")
    accepted = 0
    with connect() as database:
        for event in payload["events"]:
            if not isinstance(event, dict) or set(event) != {
                    "sequence", "type", "outcome", "cameraId", "createdAt"}:
                raise ApiError(400, "invalid_audit_event", "audit event fields are invalid")
            sequence = event["sequence"]
            event_type = event["type"]
            outcome = event["outcome"]
            camera_id = event["cameraId"]
            created = event["createdAt"]
            if not isinstance(sequence, int) or sequence < 0 or not isinstance(created, int) or created < 0 or \
                    not isinstance(event_type, str) or not re.fullmatch(r"[a-z0-9._-]{1,64}", event_type) or \
                    outcome not in {"accepted", "completed", "failed", "denied", "stopped"} or \
                    (camera_id != "" and (not isinstance(camera_id, str) or not ID_RE.fullmatch(camera_id))):
                raise ApiError(400, "invalid_audit_event", "audit event value is invalid")
            cursor = database.execute(
                "INSERT OR IGNORE INTO client_audit(client_id,sequence,event_type,outcome,camera_id,created_at) "
                "VALUES(?,?,?,?,?,?)", (client_id, sequence, event_type, outcome, camera_id, created))
            accepted += cursor.rowcount
        database.execute("DELETE FROM client_audit WHERE id NOT IN "
                         "(SELECT id FROM client_audit ORDER BY id DESC LIMIT 8192)")
    return {"accepted": accepted, "received": len(payload["events"])}


def list_clients() -> dict[str, object]:
    with connect() as database:
        rows = database.execute("SELECT * FROM clients ORDER BY created_at DESC LIMIT 256").fetchall()
        clients = []
        for row in rows:
            summary = database.execute(
                "SELECT COUNT(*) AS camera_count,MAX(weak_revocation) AS weak_revocation "
                "FROM grants WHERE client_id=?", (row["id"],)).fetchone()
            item = public_client(row)
            item["cameraCount"] = summary["camera_count"]
            item["weakRevocation"] = bool(summary["weak_revocation"])
            clients.append(item)
    return {"clients": clients}


def revoke_client(client_id: str) -> dict[str, object]:
    if not ID_RE.fullmatch(client_id):
        raise ApiError(404, "client_not_found", "client is unknown")
    now = int(time.time())
    with connect() as database:
        row = database.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()
        if row is None:
            raise ApiError(404, "client_not_found", "client is unknown")
        next_revision = revision(database, True)
        database.execute("UPDATE clients SET status='revoked',revoked_at=?,revision=? WHERE id=?",
                         (now, next_revision, client_id))
        database.execute("DELETE FROM media_plans WHERE client_id=?", (client_id,))
    return {"clientId": client_id, "status": "revoked", "revokedAt": now,
            "revision": next_revision, "offlineEffectiveNoLaterThan": row["grant_expires_at"]}


class Handler(BaseHTTPRequestHandler):
    server_version = "webobs-v2/1"
    sys_version = ""

    def log_message(self, _format, *_args):
        return

    def send_json(self, status: int, value: object) -> None:
        body = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def payload(self) -> object:
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise ApiError(415, "content_type", "Content-Type must be application/json")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ApiError(400, "invalid_body", "Content-Length is invalid") from error
        if not 1 <= length <= MAX_BODY:
            raise ApiError(413 if length > MAX_BODY else 400, "invalid_body", "JSON body is empty or too large")
        try:
            return unique_json(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
            raise ApiError(400, "invalid_json", "request body must be unique-field UTF-8 JSON") from error

    def device_token(self) -> str:
        token = self.headers.get("X-WebObs-Device-Token", "")
        return token

    def dispatch(self) -> tuple[int, object]:
        parsed = urlsplit(self.path)
        path = parsed.path
        if path == "/health" and self.command == "GET":
            return 200, {"status": "ok", "contractVersion": 1}
        if path == "/enrollments" and self.command == "POST":
            return 201, start_enrollment(self.payload())
        if path == "/enrollments" and self.command == "GET":
            require_internal_admin(self.headers.get("X-WebObs-Internal-Admin", ""))
            return 200, list_enrollments()
        match = re.fullmatch(r"/enrollments/([0-9a-f]{32})/(approve|complete)", path)
        if match and self.command == "POST":
            if match.group(2) == "approve":
                require_internal_admin(self.headers.get("X-WebObs-Internal-Admin", ""))
                return 200, approve_enrollment(match.group(1), self.payload())
            token = self.device_token()
            return complete_enrollment(match.group(1), token)
        if path == "/clients" and self.command == "GET":
            require_internal_admin(self.headers.get("X-WebObs-Internal-Admin", ""))
            return 200, list_clients()
        match = re.fullmatch(r"/clients/([A-Za-z0-9._-]{1,64})", path)
        if match and self.command == "DELETE":
            require_internal_admin(self.headers.get("X-WebObs-Internal-Admin", ""))
            return 200, revoke_client(match.group(1))

        client = authenticate_device(self.device_token())
        if path == "/client/bootstrap" and self.command == "GET":
            values = parse_qs(parsed.query, keep_blank_values=True)
            if set(values) - {"sinceRevision"} or len(values.get("sinceRevision", ["0"])) != 1 or not re.fullmatch(
                    r"[0-9]{1,18}", values.get("sinceRevision", ["0"])[0]):
                raise ApiError(400, "invalid_revision", "sinceRevision must be a non-negative integer")
            return 200, bootstrap(client, int(values.get("sinceRevision", ["0"])[0]))
        if path == "/media-plans" and self.command == "POST":
            return create_media_plan(client, self.payload())
        match = re.fullmatch(r"/media-plans/([0-9a-f]{32})", path)
        if match and self.command == "GET":
            return 200, get_media_plan(client["id"], match.group(1))
        match = re.fullmatch(r"/media-plans/([0-9a-f]{32})/(activate|activation)", path)
        if match:
            plan_id, operation = match.groups()
            if operation == "activate" and self.command == "POST":
                return 200, activate_media_plan(client["id"], plan_id)
            if operation == "activation" and self.command == "GET":
                return 200, media_plan_activation(client["id"], plan_id)
            if operation == "activation" and self.command == "DELETE":
                return 200, release_media_plan(client["id"], plan_id)
        if path == "/client/audit/batch" and self.command == "POST":
            return 200, audit_batch(client["id"], self.payload())
        operation_match = re.fullmatch(
            r"/client/cameras/([A-Za-z0-9._-]{1,64})/(ptz|presets|snapshot|talk)", path)
        if operation_match:
            operation = operation_match.group(2)
            if operation == "presets" and self.command == "GET":
                return 200, client_camera_operation(
                    client["id"], operation_match.group(1), operation, None)
            if operation in {"ptz", "snapshot", "talk"} and self.command == "POST":
                payload = {} if operation == "snapshot" and self.headers.get("Content-Length", "0") == "0" \
                    else self.payload()
                status = 202 if operation == "talk" else 200
                return status, client_camera_operation(
                    client["id"], operation_match.group(1), operation, payload)
        raise ApiError(404, "not_found", "resource not found")

    def handle_method(self) -> None:
        try:
            status, body = self.dispatch()
            self.send_json(status, body)
        except ApiError as error:
            self.send_json(error.status, {"error": {"code": error.code, "message": error.message}})
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception:
            self.send_json(500, {"error": {"code": "internal_error", "message": "v2 service failed safely"}})

    do_GET = handle_method
    do_POST = handle_method
    do_DELETE = handle_method


def main() -> None:
    initialize()
    server = ThreadingHTTPServer(LISTEN, Handler)
    server.daemon_threads = True
    print(json.dumps({"event": "v2.client_control.ready", "contractVersion": 1},
                     separators=(",", ":"), sort_keys=True), flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
