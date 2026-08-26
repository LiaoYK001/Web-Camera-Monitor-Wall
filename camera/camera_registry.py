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
ONVIF_CLOCK_LOCK = threading.Lock()
ONVIF_CLOCK_OFFSETS: dict[str, float] = {}


class OnvifError(RuntimeError):
    """Safe, credential-free ONVIF failure for API responses."""


class BrowserDirectProbeError(RuntimeError):
    """Bounded, endpoint-free browser media qualification failure."""


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
            """
        )


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
    return {
        "id": profile_id, "name": str(profile.get("name", profile_id))[:128], "role": role,
        "endpoint": endpoint, "videoCodec": str(profile.get("videoCodec", "unknown"))[:32].lower(),
        "audioCodec": str(profile.get("audioCodec", ""))[:32].lower(),
        "width": width, "height": height, "fps": fps,
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
    return {
        "id": camera_id, "name": name.strip(), "address": address, "adapter": adapter,
        "credentialsRef": credentials_ref, "hardwareDecode": hardware_decode,
        "capabilities": capabilities, "profiles": profiles,
    }


def camera_document(database: sqlite3.Connection, row: sqlite3.Row) -> dict:
    profiles = [dict(profile) for profile in database.execute(
        "SELECT id,name,role,endpoint,video_codec AS videoCodec,audio_codec AS audioCodec,width,height,fps "
        "FROM stream_profiles WHERE camera_id=? ORDER BY role,id", (row["id"],)
    )]
    return {
        "id": row["id"], "name": row["name"], "address": row["address"],
        "adapter": row["adapter"], "credentialsRef": row["credentials_ref"],
        "hardwareDecode": row["hardware_decode"], "capabilities": json.loads(row["capabilities_json"]),
        "health": row["health"], "profiles": profiles, "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def resolve_profile(database: sqlite3.Connection, camera_id: str, profile_id: str) -> dict:
    camera = database.execute("SELECT * FROM cameras WHERE id=?", (camera_id,)).fetchone()
    if not camera:
        raise KeyError("camera not found")
    profile = database.execute(
        "SELECT * FROM stream_profiles WHERE camera_id=? AND id=?", (camera_id, profile_id)
    ).fetchone()
    endpoint = profile["endpoint"] if profile else camera["address"]
    credentials_ref = camera["credentials_ref"]
    if credentials_ref:
        username, password = load_credentials(credentials_ref)
        endpoint = endpoint_with_credentials(endpoint, username, password)
    return {"endpoint": endpoint, "adapter": camera["adapter"],
            "hardwareDecode": camera["hardware_decode"], "cameraId": camera_id, "profileId": profile_id}


def save_camera(camera: dict, replace: bool) -> dict:
    now = int(time.time())
    with connect() as database:
        current = database.execute(
            "SELECT created_at,capabilities_json FROM cameras WHERE id=?", (camera["id"],)).fetchone()
        if current and not replace:
            raise FileExistsError("camera id already exists")
        created = current["created_at"] if current else now
        if current:
            try:
                reserved = json.loads(current["capabilities_json"] or "{}")
            except json.JSONDecodeError:
                reserved = {}
            for key in ("browserDirect", "iwaDirectLab"):
                if key in reserved:
                    camera["capabilities"][key] = reserved[key]
        database.execute(
            "INSERT OR REPLACE INTO cameras(id,name,address,adapter,credentials_ref,hardware_decode,capabilities_json,health,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (camera["id"], camera["name"], camera["address"], camera["adapter"], camera["credentialsRef"],
             camera["hardwareDecode"], json.dumps(camera["capabilities"], separators=(",", ":"), sort_keys=True),
             "unknown", created, now),
        )
        database.execute("DELETE FROM stream_profiles WHERE camera_id=?", (camera["id"],))
        database.executemany(
            "INSERT INTO stream_profiles(id,camera_id,name,role,endpoint,video_codec,audio_codec,width,height,fps) VALUES(?,?,?,?,?,?,?,?,?,?)",
            [(p["id"], camera["id"], p["name"], p["role"], p["endpoint"], p["videoCodec"],
              p["audioCodec"], p["width"], p["height"], p["fps"]) for p in camera["profiles"]],
        )
        row = database.execute("SELECT * FROM cameras WHERE id=?", (camera["id"],)).fetchone()
        return camera_document(database, row)


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

    def respond(self, status: int, value: object) -> None:
        body = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
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
                except (PermissionError, OSError, ValueError, json.JSONDecodeError): self.respond(503, {"error": "credentials_unavailable"})
                return
            if path == "/cameras":
                rows = database.execute("SELECT * FROM cameras ORDER BY name,id").fetchall()
                self.respond(200, {"cameras": [camera_document(database, row) for row in rows]}); return
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
        except PermissionError as error: self.respond(401, {"error": str(error)})
        except BrowserDirectProbeError as error: self.respond(400, {"error": str(error)})
        except OnvifError as error: self.respond(502, {"error": str(error)})
        except RuntimeError as error: self.respond(429, {"error": str(error)})
        except (ValueError, TypeError, json.JSONDecodeError) as error: self.respond(400, {"error": str(error)})

    def do_PUT(self) -> None:
        if not self.path.startswith("/cameras/"):
            self.respond(404, {"error": "not_found"}); return
        camera_id = self.path.removeprefix("/cameras/")
        try:
            if not ID_RE.fullmatch(camera_id): raise ValueError("camera id is invalid")
            self.respond(200, save_camera(validate_camera(self.payload(), camera_id), True))
        except (ValueError, TypeError, json.JSONDecodeError) as error: self.respond(400, {"error": str(error)})

    def do_DELETE(self) -> None:
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
