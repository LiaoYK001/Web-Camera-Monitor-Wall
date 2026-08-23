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
import sys
import tempfile
import threading
import unittest
import xml.etree.ElementTree as ET
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
        values = {local_name(node.tag): (node.text or "") for node in root.iter()}
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

    def do_POST(self) -> None:
        request_body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
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
        action = self.headers.get("SOAPAction", "") + " " + self.headers.get("Content-Type", "")
        port = self.server.server_address[1]
        base = f"http://127.0.0.1:{port}"
        if "GetServices" in action:
            media_services = (f'<tds:Service><tds:Namespace>http://www.onvif.org/ver20/media/wsdl</tds:Namespace><tds:XAddr>{base}/media2</tds:XAddr></tds:Service>'
                              if self.profile_kind == "T" else "")
            media_services += f'<tds:Service><tds:Namespace>http://www.onvif.org/ver10/media/wsdl</tds:Namespace><tds:XAddr>{base}/media1</tds:XAddr></tds:Service>'
            self.soap('<tds:GetServicesResponse xmlns:tds="http://www.onvif.org/ver10/device/wsdl">' + media_services +
                      f'<tds:Service><tds:Namespace>http://www.onvif.org/ver20/ptz/wsdl</tds:Namespace><tds:XAddr>{base}/ptz</tds:XAddr></tds:Service>'
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
            self.soap('<trt:GetSnapshotUriResponse xmlns:trt="http://www.onvif.org/ver10/media/wsdl" xmlns:tt="http://www.onvif.org/ver10/schema"><trt:MediaUri><tt:Uri>http://camera.example.invalid/snapshot.jpg</tt:Uri></trt:MediaUri></trt:GetSnapshotUriResponse>')
        else:
            self.soap('<s:Fault xmlns:s="http://www.w3.org/2003/05/soap-envelope"/>', 500)


class CameraRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="webobs-camera-tests-")
        registry.DB_PATH = Path(self.temporary.name) / "cameras.db"
        registry.SECRET_ROOT = Path(self.temporary.name) / "secrets"
        registry.SECRET_ROOT.mkdir()
        registry.initialize()

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

    def onvif_server(self, profile_kind: str, require_http_digest: bool = False) -> tuple[HTTPServer, threading.Thread]:
        handler = type(f"Onvif{profile_kind}Handler", (OnvifEmulatorHandler,), {
            "profile_kind": profile_kind, "require_http_digest": require_http_digest,
        })
        server = HTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread

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


if __name__ == "__main__":
    unittest.main()
