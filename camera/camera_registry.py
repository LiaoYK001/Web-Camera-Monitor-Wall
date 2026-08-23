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
import os
import re
import secrets
import socket
import ssl
import sqlite3
import subprocess
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.parse import quote, urlunsplit
from urllib.request import (
    HTTPBasicAuthHandler, HTTPDigestAuthHandler, HTTPPasswordMgrWithDefaultRealm,
    HTTPSHandler, HTTPRedirectHandler, Request, build_opener, urlopen,
)
from xml.sax.saxutils import escape

DB_PATH = Path(os.environ.get("WEBOBS_CAMERA_DATABASE", "/config/webobs/cameras.db"))
LISTEN = ("127.0.0.1", 8092)
MAX_BODY = 1024 * 1024
MAX_ONVIF_XML = 2 * 1024 * 1024
ONVIF_TIMEOUT_SECONDS = 6
TLS_CONTEXT = ssl.create_default_context()
SECRET_ROOT = Path(os.environ.get(
    "WEBOBS_CAMERA_SECRET_ROOT", "/run/secrets/webobs-camera-credentials"))
ADAPTERS = {
    "onvif", "rtsp", "mjpeg", "snapshot", "hls", "http-flv", "whep",
    "srt", "rtp", "v4l2",
}
ID_RE = re.compile(r"^[a-zA-Z0-9._-]{1,64}$")
SECRET_REF_RE = re.compile(r"^[a-zA-Z0-9._/-]{0,256}$")


class OnvifError(RuntimeError):
    """Safe, credential-free ONVIF failure for API responses."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise OnvifError("ONVIF endpoint redirects are forbidden")


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=3)
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
            """
        )


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
        current = database.execute("SELECT created_at FROM cameras WHERE id=?", (camera["id"],)).fetchone()
        if current and not replace:
            raise FileExistsError("camera id already exists")
        created = current["created_at"] if current else now
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


def ws_security_header(username: str, password: str) -> str:
    if not username:
        return ""
    nonce = secrets.token_bytes(16)
    created = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
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
    envelope = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">' +
        ws_security_header(username, password) + '<s:Body>' + body + '</s:Body></s:Envelope>'
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


def onvif_media_profiles(endpoint: str, profile_kind: str, username: str, password: str) -> tuple[list[dict], str]:
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
    return [profile for _, profile in ordered], snapshot


def onvif_probe(address: str, credentials_ref: str) -> dict:
    endpoint = onvif_device_endpoint(address)
    username, password = load_credentials(credentials_ref)
    services = onvif_discover_services(endpoint, username, password)
    profile_kind = ""
    profiles: list[dict] = []
    snapshot = ""
    if "media2" in services:
        try:
            profiles, snapshot = onvif_media_profiles(services["media2"], "T", username, password)
            profile_kind = "T"
        except OnvifError:
            if "media1" not in services:
                raise
    if not profiles and "media1" in services:
        profiles, snapshot = onvif_media_profiles(services["media1"], "S", username, password)
        profile_kind = "S"
    capabilities = {
        "onvif": {
            "authenticated": bool(username),
            "mediaProfile": profile_kind,
            "profileCount": len(profiles),
            "snapshot": bool(snapshot),
            "ptz": "ptz" in services,
            "events": "events" in services,
            "imaging": "imaging" in services,
            "syncedAt": int(time.time()),
        }
    }
    if snapshot and len(profiles) < 16:
        profiles.append({
            "id": "snapshot", "name": "Snapshot", "role": "snapshot", "endpoint": snapshot,
            "videoCodec": "jpeg", "audioCodec": "", "width": 0, "height": 0, "fps": 0,
        })
    return {
        "address": endpoint, "adapter": "onvif", "probe": "onvif-authenticated",
        "profileVersion": profile_kind, "profiles": profiles, "capabilities": capabilities,
    }


def sync_onvif_camera(camera_id: str) -> dict:
    with connect() as database:
        row = database.execute("SELECT * FROM cameras WHERE id=?", (camera_id,)).fetchone()
        if not row:
            raise KeyError("camera not found")
        camera = camera_document(database, row)
    if camera["adapter"] != "onvif":
        raise ValueError("camera adapter is not onvif")
    result = onvif_probe(camera["address"], camera["credentialsRef"])
    camera["address"] = result["address"]
    camera["profiles"] = result["profiles"]
    camera["capabilities"] = result["capabilities"]
    saved = save_camera(validate_camera(camera, camera_id), True)
    with connect() as database:
        database.execute("UPDATE cameras SET health='online' WHERE id=?", (camera_id,))
        row = database.execute("SELECT * FROM cameras WHERE id=?", (camera_id,)).fetchone()
        return camera_document(database, row)


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
    elif "mjpeg" in path or "mjpg" in path: adapter = "mjpeg"
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
            request = Request(normalized, method="HEAD", headers={"User-Agent": "webobs-camera-probe/1"})
            with urlopen(request, timeout=3) as response:
                result["contentType"] = response.headers.get_content_type()
                result["probe"] = "http-head"
        except Exception:
            result["probe"] = "unreachable-or-auth-required"
    return result


def onvif_discover(timeout: float = 2.0) -> list[dict]:
    message_id = uuid.uuid4()
    probe = f'''<?xml version="1.0" encoding="UTF-8"?>
<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope" xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing" xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery" xmlns:dn="http://www.onvif.org/ver10/network/wsdl"><e:Header><w:MessageID>uuid:{message_id}</w:MessageID><w:To e:mustUnderstand="true">urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To><w:Action e:mustUnderstand="true">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action></e:Header><e:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe></e:Body></e:Envelope>'''.encode()
    found: dict[str, dict] = {}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
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
        path = self.path.split("?", 1)[0]
        if path == "/health":
            self.respond(200, {"status": "ready", "database": "sqlite-wal"}); return
        if path == "/adapters":
            self.respond(200, {"adapters": sorted(ADAPTERS), "onvif": {
                "profiles": ["T", "S"], "discovery": True, "authenticatedMediaSync": True,
            }}); return
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
                self.respond(200, {"devices": onvif_discover()}); return
            if self.path == "/onvif/probe":
                payload = self.payload()
                credentials_ref = payload.get("credentialsRef", "")
                if not isinstance(credentials_ref, str):
                    raise ValueError("credentialsRef is invalid")
                self.respond(200, onvif_probe(str(payload.get("address", "")), credentials_ref)); return
            sync_match = re.fullmatch(r"/cameras/([a-zA-Z0-9._-]{1,64})/onvif/sync", self.path)
            if sync_match:
                self.respond(200, sync_onvif_camera(sync_match.group(1))); return
            self.respond(404, {"error": "not_found"})
        except FileExistsError as error: self.respond(409, {"error": str(error)})
        except KeyError: self.respond(404, {"error": "camera not found"})
        except PermissionError as error: self.respond(401, {"error": str(error)})
        except OnvifError as error: self.respond(502, {"error": str(error)})
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
    ThreadingHTTPServer(LISTEN, Handler).serve_forever()
