#!/usr/bin/env python3
"""Deterministic Camera Registry and NVR reference contract tests."""

from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
import base64
import hashlib
import json
import os
import re
import shutil
import ssl
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    specification = importlib.util.spec_from_loader(name, SourceFileLoader(name, str(path)))
    assert specification and specification.loader
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


registry = load_module("webobs_camera_registry_test", Path(os.environ.get(
    "WEBOBS_TEST_CAMERA_REGISTRY", ROOT / "camera" / "camera_registry.py")))
nvr = load_module("webobs_nvr_test", Path(os.environ.get(
    "WEBOBS_TEST_NVR_SERVICE", ROOT / "nvr" / "nvr_service.py")))


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


class OnvifEmulatorHandler(BaseHTTPRequestHandler):
    profile_kind = "T"
    require_http_digest = False
    username = "test-operator"
    password = "fixture-password"
    action_log: list[str] = []
    device_clock_offset = 0
    scheme = "http"
    users: dict[str, str] = {username: "Administrator"}

    def log_message(self, format: str, *args: object) -> None:
        return

    def soap(self, body: str, status: int = 200) -> None:
        data = ('<?xml version="1.0"?><s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">'
                '<s:Body>' + body + '</s:Body></s:Envelope>').encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/soap+xml")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)
        self.close_connection = True

    def authenticated(self, root: ET.Element) -> bool:
        token = next((node for node in root.iter()
                      if local_name(node.tag) == "UsernameToken"), None)
        values = {local_name(node.tag): (node.text or "") for node in token.iter()} \
            if token is not None else {}
        try:
            nonce = base64.b64decode(values["Nonce"], validate=True)
            expected = base64.b64encode(hashlib.sha1(
                nonce + values["Created"].encode() + self.password.encode()).digest()).decode()
            return values.get("Username") == self.username and values.get("Password") == expected
        except (KeyError, ValueError):
            return False

    def digest_authenticated(self) -> bool:
        authorization = self.headers.get("Authorization", "")
        if not authorization.startswith("Digest "):
            return False
        values = {key: quoted or plain for key, quoted, plain in
                  re.findall(r'(\w+)=(?:"([^"]*)"|([^,\s]+))', authorization[7:])}
        try:
            ha1 = hashlib.md5(f'{self.username}:webobs-fixture:{self.password}'.encode()).hexdigest()
            ha2 = hashlib.md5(f'POST:{values["uri"]}'.encode()).hexdigest()
            expected = hashlib.md5(
                f'{ha1}:fixture-nonce:{values["nc"]}:{values["cnonce"]}:auth:{ha2}'.encode()).hexdigest()
            return values.get("username") == self.username and values.get("response") == expected
        except KeyError:
            return False

    def do_GET(self) -> None:
        if self.path == "/snapshot.jpg":
            data = b"\xff\xd8\xff\xe0webobs-fixture\xff\xd9"
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers()

    def do_POST(self) -> None:
        request_body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        action = self.headers.get("SOAPAction", "") + " " + self.headers.get("Content-Type", "")
        if "GetSystemDateAndTime" in action:
            current = datetime.now(timezone.utc) + timedelta(seconds=self.device_clock_offset)
            self.soap('<tds:GetSystemDateAndTimeResponse xmlns:tds="http://www.onvif.org/ver10/device/wsdl" xmlns:tt="http://www.onvif.org/ver10/schema"><tds:SystemDateAndTime><tt:UTCDateTime><tt:Time>'
                      f'<tt:Hour>{current.hour}</tt:Hour><tt:Minute>{current.minute}</tt:Minute><tt:Second>{current.second}</tt:Second>'
                      '</tt:Time><tt:Date>'
                      f'<tt:Year>{current.year}</tt:Year><tt:Month>{current.month}</tt:Month><tt:Day>{current.day}</tt:Day>'
                      '</tt:Date></tt:UTCDateTime></tds:SystemDateAndTime></tds:GetSystemDateAndTimeResponse>')
            return
        if self.require_http_digest and not self.digest_authenticated():
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Digest realm="webobs-fixture", nonce="fixture-nonce", algorithm=MD5, qop="auth"')
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            return
        root = ET.fromstring(request_body)
        if not self.authenticated(root):
            self.soap('<s:Fault xmlns:s="http://www.w3.org/2003/05/soap-envelope"/>', 403)
            return
        self.action_log.append(action)
        port = self.server.server_address[1]
        base = f"{self.scheme}://127.0.0.1:{port}"
        if "GetServices" in action:
            media_services = (f'<tds:Service><tds:Namespace>http://www.onvif.org/ver20/media/wsdl</tds:Namespace><tds:XAddr>{base}/media2</tds:XAddr></tds:Service>'
                              if self.profile_kind == "T" else "")
            media_services += f'<tds:Service><tds:Namespace>http://www.onvif.org/ver10/media/wsdl</tds:Namespace><tds:XAddr>{base}/media1</tds:XAddr></tds:Service>'
            self.soap('<tds:GetServicesResponse xmlns:tds="http://www.onvif.org/ver10/device/wsdl">' + media_services +
                      f'<tds:Service><tds:Namespace>http://www.onvif.org/ver20/ptz/wsdl</tds:Namespace><tds:XAddr>{base}/ptz</tds:XAddr></tds:Service>'
                      f'<tds:Service><tds:Namespace>http://www.onvif.org/ver10/events/wsdl</tds:Namespace><tds:XAddr>{base}/events</tds:XAddr></tds:Service>'
                      '</tds:GetServicesResponse>')
        elif "GetProfiles" in action:
            if self.profile_kind == "T" and self.path == "/media2":
                self.soap('<tr2:GetProfilesResponse xmlns:tr2="http://www.onvif.org/ver20/media/wsdl" xmlns:tt="http://www.onvif.org/ver10/schema">'
                          '<tr2:Profiles token="profile-main"><tr2:Name>Main stream</tr2:Name><tr2:Configurations><tr2:VideoEncoder><tt:Encoding>H264</tt:Encoding><tt:Resolution><tt:Width>1920</tt:Width><tt:Height>1080</tt:Height></tt:Resolution><tt:RateControl><tt:FrameRateLimit>25</tt:FrameRateLimit></tt:RateControl></tr2:VideoEncoder><tr2:AudioEncoder><tt:Encoding>AAC</tt:Encoding></tr2:AudioEncoder></tr2:Configurations></tr2:Profiles>'
                          '<tr2:Profiles token="profile-sub"><tr2:Name>Sub stream</tr2:Name><tr2:Configurations><tr2:VideoEncoder><tt:Encoding>H264</tt:Encoding><tt:Resolution><tt:Width>640</tt:Width><tt:Height>360</tt:Height></tt:Resolution><tt:Framerate>15</tt:Framerate></tr2:VideoEncoder></tr2:Configurations></tr2:Profiles>'
                          '</tr2:GetProfilesResponse>')
            else:
                self.soap('<trt:GetProfilesResponse xmlns:trt="http://www.onvif.org/ver10/media/wsdl" xmlns:tt="http://www.onvif.org/ver10/schema">'
                          '<trt:Profiles token="legacy-main"><tt:Name>Legacy stream</tt:Name><tt:VideoEncoderConfiguration><tt:Encoding>H264</tt:Encoding><tt:Resolution><tt:Width>1280</tt:Width><tt:Height>720</tt:Height></tt:Resolution><tt:RateControl><tt:FrameRateLimit>20</tt:FrameRateLimit></tt:RateControl></tt:VideoEncoderConfiguration></trt:Profiles>'
                          '</trt:GetProfilesResponse>')
        elif "GetStreamUri" in action:
            token = next((node.text for node in root.iter() if local_name(node.tag) == "ProfileToken"), "stream")
            self.soap('<trt:GetStreamUriResponse xmlns:trt="http://www.onvif.org/ver10/media/wsdl" xmlns:tt="http://www.onvif.org/ver10/schema"><trt:MediaUri><tt:Uri>'
                      f'rtsp://camera.example.invalid/{token}'
                      '</tt:Uri></trt:MediaUri></trt:GetStreamUriResponse>')
        elif "GetSnapshotUri" in action:
            self.soap('<trt:GetSnapshotUriResponse xmlns:trt="http://www.onvif.org/ver10/media/wsdl" xmlns:tt="http://www.onvif.org/ver10/schema"><trt:MediaUri><tt:Uri>' + base + '/snapshot.jpg</tt:Uri></trt:MediaUri></trt:GetSnapshotUriResponse>')
        elif "GetAudioDecoderConfigurationOptions" in action:
            self.soap('<tr2:GetAudioDecoderConfigurationOptionsResponse xmlns:tr2="http://www.onvif.org/ver20/media/wsdl"/>')
        elif "GetUsers" in action:
            users = "".join(
                '<tds:User><tt:Username>' + username + '</tt:Username><tt:UserLevel>' + level +
                '</tt:UserLevel></tds:User>' for username, level in sorted(self.users.items()))
            self.soap('<tds:GetUsersResponse xmlns:tds="http://www.onvif.org/ver10/device/wsdl" '
                      'xmlns:tt="http://www.onvif.org/ver10/schema">' + users +
                      '</tds:GetUsersResponse>')
        elif "CreateUsers" in action or "SetUser" in action:
            fields = {local_name(node.tag): (node.text or "") for node in root.iter()}
            account, level = fields.get("Username", ""), fields.get("UserLevel", "")
            if not account or level not in {"User", "Operator"}:
                self.soap('<s:Fault xmlns:s="http://www.w3.org/2003/05/soap-envelope"/>', 400)
            else:
                self.users[account] = level
                self.soap('<tds:UserMutationResponse xmlns:tds="http://www.onvif.org/ver10/device/wsdl"/>')
        elif "DeleteUsers" in action:
            usernames = [node.text or "" for node in root.iter()
                         if local_name(node.tag) == "Username"]
            account = usernames[-1] if usernames else ""
            if account != self.username:
                self.users.pop(account, None)
            self.soap('<tds:DeleteUsersResponse xmlns:tds="http://www.onvif.org/ver10/device/wsdl"/>')
        elif "GetPresets" in action:
            self.soap('<tptz:GetPresetsResponse xmlns:tptz="http://www.onvif.org/ver20/ptz/wsdl" xmlns:tt="http://www.onvif.org/ver10/schema"><tptz:Preset token="preset-1"><tt:Name>Entrance</tt:Name></tptz:Preset></tptz:GetPresetsResponse>')
        elif "SetPreset" in action:
            self.soap('<tptz:SetPresetResponse xmlns:tptz="http://www.onvif.org/ver20/ptz/wsdl"><tptz:PresetToken>preset-created</tptz:PresetToken></tptz:SetPresetResponse>')
        elif any(name in action for name in ("ContinuousMove", "RelativeMove", "AbsoluteMove", "Stop", "GotoHomePosition", "GotoPreset", "RemovePreset")):
            self.soap('<tptz:OperationResponse xmlns:tptz="http://www.onvif.org/ver20/ptz/wsdl"/>')
        elif "CreatePullPointSubscription" in action:
            self.soap('<tev:CreatePullPointSubscriptionResponse xmlns:tev="http://www.onvif.org/ver10/events/wsdl" xmlns:wsa="http://www.w3.org/2005/08/addressing"><tev:SubscriptionReference><wsa:Address>' + base + '/pullpoint</wsa:Address></tev:SubscriptionReference></tev:CreatePullPointSubscriptionResponse>')
        elif "PullMessages" in action:
            self.soap('<tev:PullMessagesResponse xmlns:tev="http://www.onvif.org/ver10/events/wsdl" xmlns:tt="http://www.onvif.org/ver10/schema"><tev:NotificationMessage><tev:Topic>tns1:RuleEngine/CellMotionDetector/Motion</tev:Topic><tev:Message><tt:Message><tt:Data><tt:SimpleItem Name="IsMotion" Value="true"/></tt:Data></tt:Message></tev:Message></tev:NotificationMessage></tev:PullMessagesResponse>')
        else:
            self.soap('<s:Fault xmlns:s="http://www.w3.org/2003/05/soap-envelope"/>', 500)


class ServerPushMjpegHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return

    def do_HEAD(self) -> None:
        self.send_response(405)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        if not self.path.startswith("/-wvhttp-01-/video.cgi?"):
            self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers(); return
        jpeg = b"\xff\xd8\xff\xe0webobs-mjpeg-fixture\xff\xd9"
        body = (b"--fixture\r\nContent-Type: image/jpeg\r\nContent-Length: " +
                str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n--fixture\r\n")
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=fixture")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class BrowserWhepHandler(BaseHTTPRequestHandler):
    allowed_origin = "https://monitor.example.invalid:28777"

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_OPTIONS(self) -> None:
        if self.headers.get("Origin") != self.allowed_origin:
            self.send_response(403); self.send_header("Content-Length", "0"); self.end_headers(); return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", self.allowed_origin)
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()


class BrowserHlsCookieHandler(BaseHTTPRequestHandler):
    allowed_origin = BrowserWhepHandler.allowed_origin

    def log_message(self, format: str, *args: object) -> None:
        return

    def response(self, status: int, content_type: str, body: bytes,
                 *, set_cookie: bool = False) -> None:
        self.send_response(status)
        self.send_header("Access-Control-Allow-Origin", self.allowed_origin)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if set_cookie:
            self.send_header(
                "Set-Cookie", "hlsSession=fixture; Path=/; Secure; SameSite=None")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.headers.get("Origin") != self.allowed_origin:
            self.response(403, "text/plain", b"")
            return
        if self.path == "/master.m3u8":
            self.response(200, "application/vnd.apple.mpegurl",
                          b"#EXTM3U\nmedia.m3u8\n", set_cookie=True)
            return
        if self.headers.get("Cookie") != "hlsSession=fixture":
            self.response(401, "text/plain", b"")
            return
        if self.path == "/media.m3u8":
            self.response(200, "application/vnd.apple.mpegurl",
                          b"#EXTM3U\n#EXTINF:1,\nsegment.ts\n")
            return
        if self.path == "/segment.ts":
            self.response(206 if self.headers.get("Range") else 200,
                          "video/mp2t", b"bounded-fixture-segment")
            return
        self.response(404, "text/plain", b"")


class CameraRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="webobs-camera-tests-")
        registry.DB_PATH = Path(self.temporary.name) / "cameras.db"
        registry.SECRET_ROOT = Path(self.temporary.name) / "secrets"
        registry.SECRET_ROOT.mkdir()
        registry.initialize()
        registry.TLS_CONTEXT = ssl.create_default_context()
        OnvifEmulatorHandler.action_log.clear()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_sqlite_wal_and_stable_profile_contract(self) -> None:
        camera = registry.validate_camera({
            "id": "front-door",
            "name": "Front Door",
            "address": "rtsp://camera.example.invalid/live",
            "adapter": "rtsp",
            "credentialsRef": "front-door",
            "hardwareDecode": "auto",
            "profiles": [{
                "id": "main", "name": "Main", "role": "main",
                "endpoint": "rtsp://camera.example.invalid/live",
                "videoCodec": "h264", "audioCodec": "aac",
                "width": 1920, "height": 1080, "fps": 25,
            }],
            "capabilities": {"ptz": False},
        })
        stored = registry.save_camera(camera, False)
        self.assertEqual(stored["id"], "front-door")
        self.assertEqual(stored["profiles"][0]["videoCodec"], "h264")
        self.assertNotIn("password", str(stored).lower())
        with registry.connect() as database:
            self.assertEqual(database.execute("PRAGMA journal_mode").fetchone()[0], "wal")

    def test_registry_v2_catalog_revision_batch_and_redaction(self) -> None:
        camera = registry.validate_camera({
            "id": "catalog-fixture", "name": "Catalog fixture",
            "address": "rtsp://camera.example.invalid/live?channel=1", "adapter": "rtsp",
            "credentialsRef": "catalog-secret", "capabilities": {"onvif": {
                "ptz": True, "snapshot": True, "talk": False,
                "services": {"ptz": "https://private.example.invalid/ptz"},
            }}, "profiles": [{
                "id": "sub", "name": "Sub", "role": "sub",
                "endpoint": "rtsp://camera.example.invalid/sub?channel=2", "videoCodec": "h264",
                "audioCodec": "", "width": 640, "height": 360, "fps": 15,
            }],
        })
        registry.save_camera(camera, False)
        page = registry.source_catalog("limit=256&q=Catalog")
        self.assertEqual(page["schemaVersion"], 2)
        self.assertEqual(page["total"], 1)
        item = page["items"][0]
        self.assertEqual(item["addressDisplay"], "rtsp://camera.example.invalid/live")
        self.assertNotIn("channel=", json.dumps(item))
        self.assertEqual(item["deviceCapabilities"], {
            "ptz": True, "snapshot": True, "talk": False,
        })
        self.assertNotIn("private.example.invalid", json.dumps(item))
        probed = registry.probe_source_camera("catalog-fixture")
        self.assertEqual([profile["id"] for profile in probed], ["sub"])
        self.assertNotIn("endpoint", probed[0])
        changed = registry.patch_source_catalog("catalog-fixture", {
            "groupId": "Entrances", "tags": ["outdoor", "priority"],
            "profiles": [{"id": "sub", "transportMode": "rtsp-tcp",
                          "liveBitrateCapKbps": 2048, "audioExpectation": "required"}],
        }, item["revision"])
        self.assertEqual(changed["groupId"], "Entrances")
        self.assertEqual(changed["profiles"][0]["liveBitrateCapKbps"], 2048)
        with self.assertRaises(registry.RevisionConflict):
            registry.patch_source_catalog("catalog-fixture", {"enabled": False}, item["revision"])
        with registry.connect() as database:
            self.assertEqual(database.execute("PRAGMA user_version").fetchone()[0], 3)
            issues = database.execute(
                "SELECT * FROM operational_issues WHERE code='AUDIO_TRACK_MISSING'").fetchall()
            self.assertEqual(len(issues), 1)
            self.assertNotIn("camera.example.invalid", json.dumps(registry.issue_document(issues[0])))

    def test_registry_v2_batch_is_atomic_on_revision_conflict(self) -> None:
        for camera_id in ("batch-one", "batch-two"):
            registry.save_camera(registry.validate_camera({
                "id": camera_id, "name": camera_id, "address": "rtsp://camera.example.invalid/live",
                "adapter": "rtsp", "credentialsRef": "", "profiles": [],
            }), False)
        catalog = registry.source_catalog("limit=256")["items"]
        revisions = {item["id"]: item["revision"] for item in catalog}
        with self.assertRaises(registry.RevisionConflict):
            registry.batch_source_catalog({"items": [
                {"cameraId": "batch-one", "revision": revisions["batch-one"], "enabled": False},
                {"cameraId": "batch-two", "revision": revisions["batch-two"] + 1, "enabled": False},
            ]})
        current = {item["id"]: item for item in registry.source_catalog("limit=256")["items"]}
        self.assertTrue(current["batch-one"]["enabled"])
        self.assertTrue(current["batch-two"]["enabled"])

    def test_registry_v2_validation_limits(self) -> None:
        with self.assertRaises(ValueError):
            registry.validate_tags(["x"] * 33)
        with self.assertRaises(ValueError):
            registry.validate_catalog_patch({"profiles": [{
                "id": "main", "transportMode": "https",
            }]}, "rtsp")
        with self.assertRaises(ValueError):
            registry.validate_catalog_patch({"profiles": [{
                "id": "main", "liveBitrateCapKbps": 31,
            }]}, "rtsp")

    def test_insecure_http_media_requires_explicit_profile_opt_in(self) -> None:
        camera = registry.validate_camera({
            "id": "http-fixture", "name": "HTTP fixture",
            "address": "http://camera.example.invalid/mjpeg", "adapter": "mjpeg",
            "credentialsRef": "", "profiles": [{
                "id": "main", "name": "Main", "role": "main",
                "endpoint": "http://camera.example.invalid/mjpeg", "videoCodec": "mjpeg",
                "audioCodec": "", "width": 640, "height": 360, "fps": 10,
            }],
        })
        saved = registry.save_camera(camera, False)
        with registry.connect() as database:
            with self.assertRaises(PermissionError):
                registry.resolve_profile(database, "http-fixture", "main")
        changed = registry.patch_source_catalog("http-fixture", {
            "profiles": [{"id": "main", "allowInsecureHttp": True}],
        }, saved["revision"])
        self.assertTrue(changed["profiles"][0]["allowInsecureHttp"])
        with registry.connect() as database:
            resolved = registry.resolve_profile(database, "http-fixture", "main")
            issue = database.execute(
                "SELECT * FROM operational_issues WHERE code='INSECURE_HTTP_MEDIA_ENABLED'").fetchone()
        self.assertEqual(resolved["endpoint"], "http://camera.example.invalid/mjpeg")
        self.assertIsNotNone(issue)
        self.assertNotIn("camera.example.invalid", json.dumps(registry.issue_document(issue)))
        with self.assertRaises(ValueError):
            registry.validate_profile({
                "id": "secure", "endpoint": "https://camera.example.invalid/live",
                "allowInsecureHttp": True,
            }, "hls")

    def test_registry_v1_to_v2_migration_is_idempotent(self) -> None:
        legacy = Path(self.temporary.name) / "legacy.db"
        database = sqlite3.connect(legacy)
        try:
            database.executescript("""
              CREATE TABLE cameras(id TEXT PRIMARY KEY,name TEXT NOT NULL,address TEXT NOT NULL,
                adapter TEXT NOT NULL,credentials_ref TEXT NOT NULL,hardware_decode TEXT NOT NULL,
                capabilities_json TEXT NOT NULL,health TEXT NOT NULL,created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL);
              CREATE TABLE stream_profiles(id TEXT NOT NULL,camera_id TEXT NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
                name TEXT NOT NULL,role TEXT NOT NULL,endpoint TEXT NOT NULL,video_codec TEXT NOT NULL,
                audio_codec TEXT NOT NULL,width INTEGER NOT NULL,height INTEGER NOT NULL,fps REAL NOT NULL,
                PRIMARY KEY(camera_id,id));
              INSERT INTO cameras VALUES('legacy-camera','Legacy','rtsp://camera.example.invalid/live','rtsp','',
                'auto','{}','unknown',1,1);
              INSERT INTO stream_profiles VALUES('main','legacy-camera','Main','main','rtsp://camera.example.invalid/live',
                'h264','',1920,1080,25);
            """)
            database.commit()
        finally:
            database.close()
        registry.DB_PATH = legacy
        registry.initialize(); registry.initialize()
        page = registry.source_catalog("limit=256")
        self.assertEqual(page["items"][0]["kind"], "camera")
        self.assertTrue(page["items"][0]["enabled"])
        self.assertEqual(page["items"][0]["profiles"][0]["transportMode"], "auto")
        with registry.connect() as database:
            self.assertEqual(database.execute("PRAGMA user_version").fetchone()[0], 3)
            self.assertEqual(database.execute("SELECT COUNT(*) FROM cameras").fetchone()[0], 1)
        self.assertEqual(list(legacy.parent.glob(f".{legacy.name}.pre-v3-*")), [])

    def test_analytics_policies_are_per_profile_atomic_and_default_off(self) -> None:
        camera = registry.validate_camera({
            "id": "analytics-fixture", "name": "Analytics fixture",
            "address": "rtsp://camera.example.invalid/live", "adapter": "rtsp",
            "credentialsRef": "", "profiles": [{
                "id": "sub", "name": "Sub", "role": "sub",
                "endpoint": "rtsp://camera.example.invalid/sub", "videoCodec": "h264",
                "audioCodec": "", "width": 640, "height": 360, "fps": 5,
            }],
        })
        registry.save_camera(camera, False)
        self.assertEqual(registry.analytics_policies(), [])
        saved = registry.save_analytics_policies({"policies": [{
            "cameraId": "analytics-fixture", "profileId": "sub",
            "motionEnabled": True, "sceneChangeEnabled": True, "personEnabled": False,
            "allowEventPromotion": True, "promotionThreshold": .75,
            "promotionHoldSeconds": 10, "promotionCooldownSeconds": 20,
            "forceAnalyticsAlwaysOn": False,
        }]})
        self.assertTrue(saved[0]["motionEnabled"] and saved[0]["sceneChangeEnabled"])
        self.assertFalse(saved[0]["personEnabled"] or saved[0]["forceAnalyticsAlwaysOn"])
        with self.assertRaises(KeyError):
            registry.save_analytics_policies({"policies": [{
                "cameraId": "analytics-fixture", "profileId": "missing",
                "motionEnabled": False, "sceneChangeEnabled": False, "personEnabled": False,
                "allowEventPromotion": False, "forceAnalyticsAlwaysOn": False,
            }]})
        self.assertEqual(len(registry.analytics_policies()), 1)
        registry.save_camera(registry.validate_camera({**camera, "name": "Renamed fixture"}, "analytics-fixture"), True)
        self.assertEqual(len(registry.analytics_policies()), 1)
        registry.save_camera(registry.validate_camera({**camera, "profiles": []}, "analytics-fixture"), True)
        self.assertEqual(registry.analytics_policies(), [])

    def test_v3_runtime_plan_and_signal_contract_is_fail_closed(self) -> None:
        camera = registry.validate_camera({
            "id": "v3-analytics", "name": "v3 analytics", "address": "rtsp://camera.example.invalid/live",
            "adapter": "rtsp", "credentialsRef": "", "profiles": [{"id": "sub", "name": "Sub", "role": "sub",
                "endpoint": "rtsp://camera.example.invalid/sub", "videoCodec": "h264", "audioCodec": "",
                "width": 640, "height": 360, "fps": 15}],
        })
        registry.save_camera(camera, False)
        registry.save_analytics_policies({"policies": [{"cameraId": "v3-analytics", "profileId": "sub",
            "motionEnabled": True, "sceneChangeEnabled": False, "personEnabled": True,
            "allowEventPromotion": False, "forceAnalyticsAlwaysOn": False,
            "person": {"executionPreference": "browser", "allowServerFallback": False}}]})
        plan = registry.analytics_runtime_plan({"cameraId": "v3-analytics", "profileId": "sub",
                                                "capabilities": {"wasm": True, "webgpu": False}})
        self.assertEqual(plan["contractVersion"], 2)
        self.assertEqual({item["kind"] for item in plan["plans"]}, {"motion", "scene-change", "person"})
        self.assertEqual(next(item for item in plan["plans"] if item["kind"] == "motion")["execution"], "browser-wasm")
        self.assertTrue(all(item["mediaTransport"] == "rtsp" for item in plan["plans"]))
        self.assertEqual(next(item for item in plan["plans"] if item["kind"] == "scene-change")["execution"], "off")
        self.assertEqual(next(item for item in plan["plans"] if item["kind"] == "person")["execution"], "browser-wasm")
        with self.assertRaises(PermissionError):
            registry.ingest_analytics_signals({"signals": [{"signalId": "disabled-01", "cameraId": "v3-analytics",
                "profileId": "sub", "kind": "scene-change", "occurredAt": int(time.time() * 1000), "confidence": .9}]}, plan["sessionId"])
        class EventResponse:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def read(self, _limit): return b'{"id":"event-1"}'
        with patch.object(registry, "urlopen", return_value=EventResponse()):
            signal = {"signalId": "motion-0001", "cameraId": "v3-analytics", "profileId": "sub", "kind": "motion",
                      "occurredAt": int(time.time() * 1000), "confidence": .8}
            self.assertEqual(registry.ingest_analytics_signals({"signals": [signal]}, plan["sessionId"])["accepted"], 1)
            with self.assertRaises(PermissionError):
                registry.ingest_analytics_signals({"signals": [signal]}, plan["sessionId"])
            person = {"signalId": "person-0001", "cameraId": "v3-analytics", "profileId": "sub",
                      "kind": "person", "occurredAt": int(time.time() * 1000), "confidence": .9,
                      "boxes": [], "modelId": registry.ANALYTICS_PERSON_MODEL_ID,
                      "modelVersion": registry.ANALYTICS_PERSON_MODEL_VERSION,
                      "modelSha256": registry.ANALYTICS_PERSON_MODEL_SHA256}
            self.assertEqual(registry.ingest_analytics_signals({"signals": [person]}, plan["sessionId"])["accepted"], 1)
            with self.assertRaisesRegex(ValueError, "approved"):
                registry.ingest_analytics_signals({"signals": [{**person, "modelSha256": "0" * 64}]}, plan["sessionId"])
        self.assertTrue(registry.close_analytics_session(plan["sessionId"]))
        with self.assertRaises(PermissionError):
            registry.ingest_analytics_signals({"signals": [signal]}, plan["sessionId"])

    def test_v3_runtime_plan_reuses_direct_probe_and_marks_gateway_media(self) -> None:
        camera = registry.validate_camera({
            "id": "v3-gateway-plan", "name": "Gateway plan", "address": "rtsp://camera.example.invalid/live",
            "adapter": "rtsp", "credentialsRef": "", "profiles": [{"id": "main", "name": "Main", "role": "main",
                "endpoint": "rtsp://camera.example.invalid/main", "videoCodec": "h264", "audioCodec": "",
                "width": 640, "height": 360, "fps": 15}],
        })
        registry.save_camera(camera, False)
        registry.save_analytics_policies({"policies": [{"cameraId": "v3-gateway-plan", "profileId": "main",
            "motionEnabled": True, "sceneChangeEnabled": False, "personEnabled": False,
            "allowEventPromotion": False, "forceAnalyticsAlwaysOn": False}]})
        plan = registry.analytics_runtime_plan({"cameraId": "v3-gateway-plan", "profileId": "main",
                                                "capabilities": {"wasm": True}})
        motion = next(item for item in plan["plans"] if item["kind"] == "motion")
        self.assertEqual(motion["execution"], "browser-wasm")
        self.assertTrue(motion["serverMediaExpected"])
        self.assertEqual(motion["reason"], "rtsp_gateway_required")
        registry.close_analytics_session(plan["sessionId"])

        direct_endpoint = "https://media.example.invalid/live"
        direct = registry.validate_camera({
            "id": "v3-direct-plan", "name": "Direct plan", "address": direct_endpoint,
            "adapter": "whep", "credentialsRef": "", "profiles": [{"id": "main", "name": "Main", "role": "main",
                "endpoint": direct_endpoint, "videoCodec": "h264", "audioCodec": "",
                "width": 640, "height": 360, "fps": 15}],
        })
        registry.save_camera(direct, False)
        registry.save_analytics_policies({"policies": [{"cameraId": "v3-direct-plan", "profileId": "main",
            "motionEnabled": True, "sceneChangeEnabled": False, "personEnabled": False,
            "allowEventPromotion": False, "forceAnalyticsAlwaysOn": False}]})
        with patch.dict(os.environ, {"WEBOBS_PWA_PUBLIC_ORIGIN": "https://pwa.example.invalid"}):
            unqualified = registry.analytics_runtime_plan({"cameraId": "v3-direct-plan", "profileId": "main",
                                                            "capabilities": {"wasm": True}})
        motion = next(item for item in unqualified["plans"] if item["kind"] == "motion")
        self.assertTrue(motion["serverMediaExpected"])
        self.assertEqual(motion["reason"], "browser_direct_not_qualified")
        registry.close_analytics_session(unqualified["sessionId"])

        with registry.connect() as database:
            capabilities = {"browserDirect": {"profiles": {"main": {
                "tlsVerified": True, "corsVerified": True,
                "pwaOriginSha256": hashlib.sha256(b"https://pwa.example.invalid").hexdigest(),
                "checkedAt": int(time.time()),
            }}}}
            database.execute("UPDATE cameras SET capabilities_json=? WHERE id=?", (
                json.dumps(capabilities, separators=(",", ":")), "v3-direct-plan"))
        with patch.dict(os.environ, {"WEBOBS_PWA_PUBLIC_ORIGIN": "https://pwa.example.invalid"}):
            qualified = registry.analytics_runtime_plan({"cameraId": "v3-direct-plan", "profileId": "main",
                                                         "capabilities": {"wasm": True}})
        motion = next(item for item in qualified["plans"] if item["kind"] == "motion")
        self.assertFalse(motion["serverMediaExpected"])
        self.assertEqual(motion["reason"], "")
        registry.close_analytics_session(qualified["sessionId"])

    def test_v3_native_motion_uses_server_onvif_capability_not_client_claim(self) -> None:
        camera = registry.validate_camera({
            "id": "v3-onvif-capability", "name": "ONVIF capability", "address": "http://camera.example.invalid/onvif/device_service",
            "adapter": "onvif", "credentialsRef": "", "capabilities": {
                "onvif": {"events": True},
            },
            "profiles": [{"id": "sub", "name": "Sub", "role": "sub",
                "endpoint": "rtsp://camera.example.invalid/sub", "videoCodec": "h264", "audioCodec": "",
                "width": 640, "height": 360, "fps": 15}],
        })
        registry.save_camera(camera, False)
        registry.save_analytics_policies({"policies": [{"cameraId": "v3-onvif-capability", "profileId": "sub",
            "motionEnabled": True, "sceneChangeEnabled": False, "personEnabled": False,
            "allowEventPromotion": False, "forceAnalyticsAlwaysOn": False}]})

        # The client cannot grant or revoke native ONVIF execution.  The
        # authoritative registry capability enables it even when the request
        # claims the opposite.
        native = registry.analytics_runtime_plan({"cameraId": "v3-onvif-capability", "profileId": "sub",
                                                   "capabilities": {"wasm": True, "onvifMotion": False}})
        self.assertEqual(native["plans"][0]["execution"], "native")
        registry.close_analytics_session(native["sessionId"])

        with registry.connect() as database:
            database.execute("UPDATE cameras SET capabilities_json=? WHERE id=?", (
                json.dumps({"onvif": {"events": False}}, separators=(",", ":")), "v3-onvif-capability"))
        browser = registry.analytics_runtime_plan({"cameraId": "v3-onvif-capability", "profileId": "sub",
                                                   "capabilities": {"wasm": True, "onvifMotion": True}})
        self.assertEqual(browser["plans"][0]["execution"], "browser-wasm")
        registry.close_analytics_session(browser["sessionId"])

    def test_v3_person_worker_preference_is_explicit_and_fallback_is_separate(self) -> None:
        camera = registry.validate_camera({
            "id": "v3-worker-plan", "name": "Worker plan", "address": "rtsp://camera.example.invalid/live",
            "adapter": "rtsp", "credentialsRef": "", "profiles": [{"id": "sub", "name": "Sub", "role": "sub",
                "endpoint": "rtsp://camera.example.invalid/sub", "videoCodec": "h264", "audioCodec": "",
                "width": 640, "height": 360, "fps": 15}],
        })
        registry.save_camera(camera, False)
        registry.save_analytics_policies({"policies": [{"cameraId": "v3-worker-plan", "profileId": "sub",
            "motionEnabled": False, "sceneChangeEnabled": False, "personEnabled": True,
            "allowEventPromotion": False, "forceAnalyticsAlwaysOn": False,
            "person": {"executionPreference": "worker", "allowServerFallback": False}}]})
        forced = registry.analytics_runtime_plan({"cameraId": "v3-worker-plan", "profileId": "sub",
                                                   "kinds": ["person"], "capabilities": {"wasm": True, "webgpu": True}})
        person = forced["plans"][0]
        self.assertEqual(person["execution"], "worker")
        self.assertEqual(person["executionOwner"], "worker")
        self.assertTrue(person["serverMediaExpected"])
        registry.close_analytics_session(forced["sessionId"])

        registry.save_analytics_policies({"policies": [{"cameraId": "v3-worker-plan", "profileId": "sub",
            "motionEnabled": False, "sceneChangeEnabled": False, "personEnabled": True,
            "allowEventPromotion": False, "forceAnalyticsAlwaysOn": False,
            "person": {"executionPreference": "browser", "allowServerFallback": True}}]})
        fallback = registry.analytics_runtime_plan({"cameraId": "v3-worker-plan", "profileId": "sub",
                                                     "kinds": ["person"], "capabilities": {"wasm": False, "webgpu": False}})
        person = fallback["plans"][0]
        self.assertEqual(person["execution"], "worker")
        self.assertEqual(person["reason"], "rtsp_gateway_required")
        registry.close_analytics_session(fallback["sessionId"])

    def test_embedded_credentials_and_secret_queries_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            registry.safe_endpoint(
                "rtsp" + "://operator:secret@camera.example.invalid/live", "rtsp"
            )
        with self.assertRaises(ValueError):
            registry.safe_endpoint("https://camera.example.invalid/live?access_token=secret", "hls")
        with self.assertRaises(ValueError):
            registry.validate_camera({
                "name": "Unsafe", "address": "rtsp://camera.example.invalid/live",
                "adapter": "rtsp", "credentialsRef": "../escape", "profiles": [],
            })

    def test_browser_direct_proof_is_tls_cors_bound_and_not_user_forgeable(self) -> None:
        openssl = shutil.which("openssl")
        if not openssl: self.skipTest("OpenSSL CLI is required for the TLS fixture")
        certificate = Path(self.temporary.name) / "browser-fixture.crt"
        private_key = Path(self.temporary.name) / "browser-fixture.key"
        subprocess.run([openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                        "-keyout", str(private_key), "-out", str(certificate), "-subj", "/CN=127.0.0.1",
                        "-addext", "subjectAltName=IP:127.0.0.1"], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        server = HTTPServer(("127.0.0.1", 0), BrowserWhepHandler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); context.load_cert_chain(certificate, private_key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            endpoint = f"https://127.0.0.1:{server.server_address[1]}/whep"
            submitted = registry.validate_camera({
                "id": "browser-fixture", "name": "Browser fixture", "address": endpoint,
                "adapter": "whep", "credentialsRef": "", "profiles": [{
                    "id": "main", "name": "Main", "role": "main", "endpoint": endpoint,
                    "videoCodec": "h264", "audioCodec": "opus", "width": 640,
                    "height": 360, "fps": 15,
                }], "capabilities": {"browserDirect": {"profiles": {
                    "main": {"tlsVerified": True, "corsVerified": True}}}},
            })
            self.assertNotIn("browserDirect", submitted["capabilities"])
            registry.save_camera(submitted, False)
            registry.TLS_CONTEXT = ssl.create_default_context(cafile=str(certificate))
            with patch.dict(os.environ, {
                    "WEBOBS_PWA_PUBLIC_ORIGIN": BrowserWhepHandler.allowed_origin,
                    "WEBOBS_CAMERA_ALLOW_TEST_ENDPOINTS": "true",
                    "WEBOBS_BROWSER_PROBE_ALLOW_LOOPBACK": "true",
            }):
                qualified = registry.browser_direct_probe("browser-fixture", "main")
            self.assertTrue(qualified["eligible"])
            with registry.connect() as database:
                proof = json.loads(database.execute(
                    "SELECT capabilities_json FROM cameras WHERE id='browser-fixture'").fetchone()[0])[
                        "browserDirect"]["profiles"]["main"]
            self.assertTrue(proof["tlsVerified"] and proof["corsVerified"])
            self.assertEqual(proof["pwaOriginSha256"], hashlib.sha256(
                BrowserWhepHandler.allowed_origin.encode()).hexdigest())

            replacement = registry.validate_camera({
                **submitted, "capabilities": {"browserDirect": {"profiles": {
                    "main": {"tlsVerified": False, "corsVerified": False}}}},
            }, "browser-fixture")
            persisted = registry.save_camera(replacement, True)
            self.assertTrue(persisted["capabilities"]["browserDirect"]["profiles"]["main"]["tlsVerified"])
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)

    def test_hls_direct_probe_preserves_bounded_session_cookie(self) -> None:
        openssl = shutil.which("openssl")
        if not openssl: self.skipTest("OpenSSL CLI is required for the TLS fixture")
        certificate = Path(self.temporary.name) / "hls-fixture.crt"
        private_key = Path(self.temporary.name) / "hls-fixture.key"
        subprocess.run([openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                        "-keyout", str(private_key), "-out", str(certificate), "-subj", "/CN=127.0.0.1",
                        "-addext", "subjectAltName=IP:127.0.0.1"], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        server = HTTPServer(("127.0.0.1", 0), BrowserHlsCookieHandler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certificate, private_key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            endpoint = f"https://127.0.0.1:{server.server_address[1]}/master.m3u8"
            camera = registry.validate_camera({
                "id": "hls-cookie-fixture", "name": "HLS cookie fixture",
                "address": endpoint, "adapter": "hls", "credentialsRef": "",
                "profiles": [{
                    "id": "main", "name": "Main", "role": "main", "endpoint": endpoint,
                    "videoCodec": "h264", "audioCodec": "aac", "width": 640,
                    "height": 360, "fps": 15,
                }],
            })
            registry.save_camera(camera, False)
            registry.TLS_CONTEXT = ssl.create_default_context(cafile=str(certificate))
            with patch.dict(os.environ, {
                    "WEBOBS_PWA_PUBLIC_ORIGIN": BrowserHlsCookieHandler.allowed_origin,
                    "WEBOBS_CAMERA_ALLOW_TEST_ENDPOINTS": "true",
                    "WEBOBS_BROWSER_PROBE_ALLOW_LOOPBACK": "true",
            }):
                qualified = registry.browser_direct_probe("hls-cookie-fixture", "main")
            self.assertTrue(qualified["eligible"])
            self.assertEqual(qualified["reason"], "")
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)

    def test_canon_wvhttp_server_push_mjpeg_detection_without_head(self) -> None:
        server = HTTPServer(("127.0.0.1", 0), ServerPushMjpegHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            address = (f"http://127.0.0.1:{server.server_address[1]}"
                       "/-wvhttp-01-/video.cgi?v=jpg%3A320x240%3A%3A5000&type=live")
            detected = registry.classify(address)
            self.assertEqual(detected["adapter"], "mjpeg")
            self.assertEqual(detected["contentType"], "multipart/x-mixed-replace")
            self.assertEqual(detected["probe"], "http-server-push-mjpeg")
            self.assertEqual(detected["profiles"][0]["videoCodec"], "mjpeg")
            self.assertNotIn("127.0.0.1", json.dumps({
                "adapter": detected["adapter"], "contentType": detected["contentType"],
                "probe": detected["probe"],
            }))
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)

    def test_nvr_accepts_registry_ids_without_raw_urls(self) -> None:
        configuration = nvr.validate_config({
            "schemaVersion": 1,
            "cameras": [{
                "id": "front-door-archive", "name": "Front Door", "policy": "continuous",
                "cameraId": "front-door", "mainProfileId": "main", "stream": "main",
            }],
        })
        camera = configuration["cameras"][0]
        self.assertEqual(camera["cameraId"], "front-door")
        self.assertEqual(camera["mainUrl"], "")
        with self.assertRaises(nvr.ConfigError):
            nvr.validate_config({
                "schemaVersion": 1,
                "cameras": [{
                    "id": "mixed", "name": "Mixed", "cameraId": "front-door",
                    "mainProfileId": "main", "mainUrl": "rtsp://camera.example.invalid/live",
                }],
            })

    def onvif_server(self, profile_kind: str, require_http_digest: bool = False, clock_offset: int = 0) -> tuple[HTTPServer, threading.Thread]:
        handler = type(f"Onvif{profile_kind}Handler", (OnvifEmulatorHandler,), {
            "profile_kind": profile_kind, "require_http_digest": require_http_digest,
            "device_clock_offset": clock_offset,
            "users": {OnvifEmulatorHandler.username: "Administrator"},
        })
        server = HTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread

    def onvif_tls_server(self) -> tuple[HTTPServer, threading.Thread, Path]:
        openssl = shutil.which("openssl")
        if not openssl: self.skipTest("OpenSSL CLI is required for the TLS fixture")
        certificate, private_key = Path(self.temporary.name) / "fixture.crt", Path(self.temporary.name) / "fixture.key"
        subprocess.run([openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                        "-keyout", str(private_key), "-out", str(certificate), "-subj", "/CN=127.0.0.1",
                        "-addext", "subjectAltName=IP:127.0.0.1"], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        handler = type("OnvifTlsHandler", (OnvifEmulatorHandler,), {
            "profile_kind": "T", "scheme": "https",
            "users": {OnvifEmulatorHandler.username: "Administrator"}})
        server = HTTPServer(("127.0.0.1", 0), handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); context.load_cert_chain(certificate, private_key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        return server, thread, certificate

    def write_fixture_secret(self) -> None:
        (registry.SECRET_ROOT / "fixture.json").write_text(json.dumps({
            "username": OnvifEmulatorHandler.username,
            "password": OnvifEmulatorHandler.password,
        }), encoding="utf-8")

    def test_authenticated_profile_t_media_probe_and_sync(self) -> None:
        self.write_fixture_secret()
        server, thread = self.onvif_server("T", require_http_digest=True)
        try:
            address = f"http://127.0.0.1:{server.server_address[1]}"
            probe = registry.onvif_probe(address, "fixture")
            self.assertEqual(probe["profileVersion"], "T")
            self.assertEqual(probe["profiles"][0]["role"], "main")
            self.assertEqual(probe["profiles"][0]["width"], 1920)
            self.assertEqual(probe["profiles"][1]["role"], "sub")
            self.assertTrue(probe["capabilities"]["onvif"]["ptz"])
            self.assertTrue(probe["capabilities"]["onvif"]["events"])
            self.assertTrue(probe["capabilities"]["onvif"]["talk"])
            self.assertTrue(probe["capabilities"]["onvif"]["userManagement"])
            self.assertNotIn(OnvifEmulatorHandler.password, json.dumps(probe))

            registry.save_camera(registry.validate_camera({
                "id": "onvif-fixture", "name": "ONVIF Fixture", "address": address,
                "adapter": "onvif", "credentialsRef": "fixture", "profiles": [],
            }), False)
            synced = registry.sync_onvif_camera("onvif-fixture")
            self.assertEqual(synced["health"], "online")
            self.assertEqual(synced["capabilities"]["onvif"]["mediaProfile"], "T")
            self.assertEqual(len(synced["profiles"]), 3)
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)

    def test_onvif_dedicated_user_lifecycle_is_secret_referenced(self) -> None:
        self.write_fixture_secret()
        (registry.SECRET_ROOT / "client-device.json").write_text(json.dumps({
            "username": "webobs-client-device",
            "password": "fixture-dedicated-password-32",
        }), encoding="utf-8")
        server, thread = self.onvif_server("T")
        try:
            address = f"http://127.0.0.1:{server.server_address[1]}"
            registry.save_camera(registry.validate_camera({
                "id": "managed-fixture", "name": "Managed Fixture", "address": address,
                "adapter": "onvif", "credentialsRef": "fixture", "profiles": [],
            }), False)
            registry.sync_onvif_camera("managed-fixture")
            created = registry.onvif_manage_dedicated_user("managed-fixture", {
                "operation": "ensure", "credentialsRef": "client-device", "role": "operator",
            })
            self.assertEqual(created["state"], "created")
            self.assertFalse(created["weakRevocation"])
            self.assertEqual(server.RequestHandlerClass.users["webobs-client-device"], "Operator")
            updated = registry.onvif_manage_dedicated_user("managed-fixture", {
                "operation": "ensure", "credentialsRef": "client-device", "role": "user",
            })
            self.assertEqual(updated["state"], "updated")
            self.assertEqual(server.RequestHandlerClass.users["webobs-client-device"], "User")
            deleted = registry.onvif_manage_dedicated_user("managed-fixture", {
                "operation": "delete", "credentialsRef": "client-device", "role": "user",
            })
            self.assertEqual(deleted["state"], "deleted")
            self.assertNotIn("webobs-client-device", server.RequestHandlerClass.users)
            operations = registry.device_audit("managed-fixture")
            self.assertTrue(any(item["operation"] == "users.ensure-dedicated" for item in operations))
            self.assertNotIn("fixture-dedicated-password-32", json.dumps(operations))
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)

    def test_guarded_device_operations_and_private_profile_tokens(self) -> None:
        self.write_fixture_secret()
        server, thread = self.onvif_server("T", require_http_digest=True)
        try:
            address = f"http://127.0.0.1:{server.server_address[1]}"
            registry.save_camera(registry.validate_camera({
                "id": "controlled-fixture", "name": "Controlled Fixture", "address": address,
                "adapter": "onvif", "credentialsRef": "fixture", "profiles": [],
            }), False)
            synced = registry.sync_onvif_camera("controlled-fixture")
            self.assertNotIn("device_token", json.dumps(synced))
            self.assertEqual(registry.onvif_presets("controlled-fixture")[0]["token"], "preset-1")
            moved = registry.onvif_ptz_command("controlled-fixture", {
                "operation": "relative", "x": 0.25, "y": -0.1, "zoom": 0,
            })
            self.assertEqual(moved["state"], "accepted")
            created = registry.onvif_preset_mutation("controlled-fixture", {
                "operation": "set", "name": "Door",
            })
            self.assertEqual(created["presetToken"], "preset-created")
            snapshot = registry.onvif_snapshot("controlled-fixture")
            self.assertEqual(snapshot["contentType"], "image/jpeg")
            self.assertEqual(base64.b64decode(snapshot["data"], validate=True)[:2], b"\xff\xd8")
            pulled = registry.onvif_pull_events("controlled-fixture")
            self.assertEqual(pulled["events"][0]["properties"]["IsMotion"], "true")
            class FakeTalkProcess:
                returncode = None
                def poll(self): return self.returncode
                def communicate(self, audio=None, timeout=None):
                    self.returncode = 0
                    return (b"", b"")
                def terminate(self): self.returncode = -15
                def kill(self): self.returncode = -9
                def wait(self, timeout=None): self.returncode = self.returncode or 0
            fake_process = FakeTalkProcess()
            with patch.object(registry.subprocess, "Popen", return_value=fake_process):
                talk = registry.onvif_talk("controlled-fixture", {
                    "operation": "start", "contentType": "audio/wav",
                    "data": base64.b64encode(b"RIFF-fixture-audio").decode(),
                })
                self.assertEqual(talk["state"], "active")
                for _ in range(20):
                    if "controlled-fixture" not in registry.TALK_PROCESSES: break
                    time.sleep(0.01)
            operations = registry.device_audit("controlled-fixture")
            self.assertTrue(any(item["operation"] == "snapshot.read" for item in operations))
            self.assertTrue(any(item["operation"] == "talk.session" for item in operations))
            time.sleep(0.11)
            with self.assertRaises(ValueError):
                registry.onvif_ptz_command("controlled-fixture", {
                    "operation": "absolute", "x": 2, "y": 0, "zoom": 0,
                })
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)

    def test_profile_s_fallback_and_xml_hardening(self) -> None:
        self.write_fixture_secret()
        server, thread = self.onvif_server("S")
        try:
            result = registry.onvif_probe(
                f"http://127.0.0.1:{server.server_address[1]}/onvif/device_service", "fixture")
            self.assertEqual(result["profileVersion"], "S")
            self.assertEqual(result["profiles"][0]["width"], 1280)
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)
        with self.assertRaises(registry.OnvifError):
            registry.parse_onvif_xml(b'<!DOCTYPE x [<!ENTITY unsafe "value">]><x>&unsafe;</x>')
        with self.assertRaises(registry.OnvifError):
            registry.parse_onvif_xml(b"<x>" + b"0" * registry.MAX_ONVIF_XML + b"</x>")

    def test_onvif_auth_failure_is_redacted(self) -> None:
        (registry.SECRET_ROOT / "wrong.json").write_text(json.dumps({
            "username": OnvifEmulatorHandler.username, "password": "wrong-fixture-value",
        }), encoding="utf-8")
        server, thread = self.onvif_server("T")
        try:
            with self.assertRaises(PermissionError) as raised:
                registry.onvif_probe(f"http://127.0.0.1:{server.server_address[1]}", "wrong")
            self.assertNotIn("wrong-fixture-value", str(raised.exception))
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)

    def test_clock_skew_and_bounded_discovery_interface(self) -> None:
        self.write_fixture_secret(); server, thread = self.onvif_server("T", True, 120)
        try:
            probe = registry.onvif_probe(f"http://127.0.0.1:{server.server_address[1]}", "fixture")
            self.assertGreater(probe["capabilities"]["onvif"]["clockOffsetSeconds"], 115)
            self.assertLess(probe["capabilities"]["onvif"]["clockOffsetSeconds"], 125)
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)
        with self.assertRaises(ValueError): registry.onvif_discover(6)
        with self.assertRaises(ValueError): registry.onvif_discover(1, "::1")

    def test_tls_device_requires_a_trusted_certificate(self) -> None:
        self.write_fixture_secret(); server, thread, certificate = self.onvif_tls_server()
        address = f"https://127.0.0.1:{server.server_address[1]}"
        try:
            with self.assertRaises(registry.OnvifError): registry.onvif_probe(address, "fixture")
            registry.TLS_CONTEXT = ssl.create_default_context(cafile=str(certificate))
            probe = registry.onvif_probe(address, "fixture")
            self.assertEqual(probe["profileVersion"], "T")
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
