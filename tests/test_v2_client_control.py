#!/usr/bin/env python3
"""Security and topology contract tests for the v2 local-client control plane."""

from __future__ import annotations

import base64
import ctypes
import importlib.util
from importlib.machinery import SourceFileLoader
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
SERVICE = Path(os.environ.get(
    "WEBOBS_TEST_V2_SERVICE", ROOT / "v2" / "client_control_service.py"))
specification = importlib.util.spec_from_loader(
    "webobs_v2_client_control_test", SourceFileLoader("webobs_v2_client_control_test", str(SERVICE)))
assert specification and specification.loader
service = importlib.util.module_from_spec(specification)
sys.modules[specification.name] = service
specification.loader.exec_module(service)


def decode_b64url(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def decode_cbor(value: bytes, offset: int = 0):
    initial = value[offset]
    offset += 1
    major, additional = initial >> 5, initial & 31
    if additional < 24:
        length = additional
    elif additional == 24:
        length, offset = value[offset], offset + 1
    elif additional == 25:
        length, offset = int.from_bytes(value[offset:offset + 2], "big"), offset + 2
    elif additional == 26:
        length, offset = int.from_bytes(value[offset:offset + 4], "big"), offset + 4
    elif additional == 27:
        length, offset = int.from_bytes(value[offset:offset + 8], "big"), offset + 8
    else:
        raise ValueError("unsupported CBOR additional information")
    if major == 0:
        return length, offset
    if major == 1:
        return -1 - length, offset
    if major == 2:
        return value[offset:offset + length], offset + length
    if major == 3:
        return value[offset:offset + length].decode(), offset + length
    if major == 4:
        result = []
        for _ in range(length):
            item, offset = decode_cbor(value, offset)
            result.append(item)
        return result, offset
    if major == 5:
        result = {}
        for _ in range(length):
            key, offset = decode_cbor(value, offset)
            item, offset = decode_cbor(value, offset)
            result[key] = item
        return result, offset
    if initial == 0xF4:
        return False, offset
    if initial == 0xF5:
        return True, offset
    if initial == 0xF6:
        return None, offset
    raise ValueError("unsupported CBOR value")


class DeviceKeys:
    def __init__(self):
        sodium = service.sodium()
        self.signing_public, self.signing_secret = sodium.signing_keypair()
        library = sodium.library
        library.crypto_box_keypair.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        library.crypto_box_keypair.restype = ctypes.c_int
        library.crypto_box_seal_open.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulonglong,
            ctypes.c_void_p, ctypes.c_void_p,
        ]
        library.crypto_box_seal_open.restype = ctypes.c_int
        public = ctypes.create_string_buffer(32)
        secret = ctypes.create_string_buffer(32)
        if library.crypto_box_keypair(public, secret) != 0:
            raise RuntimeError("fixture encryption key generation failed")
        self.encryption_public, self.encryption_secret = public.raw, secret.raw

    def enrollment(self, nonce: bytes = bytes(range(32))) -> dict[str, str]:
        proof = service.enrollment_proof(
            "Test workstation", "linux", self.signing_public, self.encryption_public, nonce)
        signature = service.sodium().sign(proof, self.signing_secret)
        return {
            "name": "Test workstation", "platform": "linux",
            "signingPublicKey": service.b64url(self.signing_public),
            "encryptionPublicKey": service.b64url(self.encryption_public),
            "enrollmentNonce": service.b64url(nonce), "signature": service.b64url(signature),
        }

    def open_bundle(self, bundle: dict[str, object]) -> tuple[bytes, dict[str, object]]:
        ciphertext = decode_b64url(str(bundle["ciphertext"]))
        plaintext = ctypes.create_string_buffer(len(ciphertext) - 48)
        source = ctypes.create_string_buffer(ciphertext, len(ciphertext))
        public = ctypes.create_string_buffer(self.encryption_public, 32)
        secret = ctypes.create_string_buffer(self.encryption_secret, 32)
        result = service.sodium().library.crypto_box_seal_open(
            plaintext, source, len(ciphertext), public, secret)
        self_error = "sealed grant could not be opened by its intended recipient"
        if result != 0:
            raise AssertionError(self_error)
        signature, encoded = plaintext.raw[:64], plaintext.raw[64:]
        signing_public = decode_b64url(str(bundle["serverSigningPublicKey"]))
        if not service.sodium().verify(signature, encoded, signing_public):
            raise AssertionError("server signature on grant is invalid")
        decoded, consumed = decode_cbor(encoded)
        if consumed != len(encoded):
            raise AssertionError("grant CBOR has trailing bytes")
        return encoded, decoded


class V2ClientControlTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        service.DB_PATH = root / "v2-clients.db"
        service.CAMERA_DB_PATH = root / "cameras.db"
        service.NVR_CONFIG_PATH = root / "nvr.json"
        service.SCENES_PATH = root / "shared-scenes-v2.json"
        service.SECRET_ROOT = root / "secrets"
        service.KEY_PATH = root / "keys" / "client-grant-signing.key"
        service.SECRET_ROOT.mkdir()
        (service.SECRET_ROOT / "camera-test.json").write_text(json.dumps({
            "username": "fixture-viewer", "password": "fixture-password",
        }), encoding="utf-8")
        with sqlite3.connect(service.CAMERA_DB_PATH) as database:
            database.executescript("""
              CREATE TABLE cameras(id TEXT PRIMARY KEY,name TEXT,address TEXT,adapter TEXT,
                credentials_ref TEXT,hardware_decode TEXT,capabilities_json TEXT,health TEXT,
                created_at INTEGER,updated_at INTEGER);
              CREATE TABLE stream_profiles(id TEXT,camera_id TEXT,name TEXT,role TEXT,
                endpoint TEXT,video_codec TEXT,audio_codec TEXT,width INTEGER,height INTEGER,
                fps REAL,PRIMARY KEY(camera_id,id));
              INSERT INTO cameras VALUES('camera-test','Fixture camera','rtsp://camera.invalid',
                'rtsp','camera-test','auto','{}','healthy',1,1);
              INSERT INTO stream_profiles VALUES('sub','camera-test','Sub stream','sub',
                'rtsp://camera.invalid/sub','h264','aac',640,360,15);
            """)
        service.NVR_CONFIG_PATH.write_text(json.dumps({"cameras": [{
            "cameraId": "camera-test", "policy": "continuous", "mode": "copy",
        }]}), encoding="utf-8")
        service.SCENES_PATH.write_text(json.dumps({
            "schemaVersion": 1, "scenes": [{
                "schemaVersion": 5, "revision": 1, "id": "shared-grid", "name": "Shared grid",
                "canvas": {"width": 640, "height": 360, "backgroundColor": "#000000"},
                "sources": [{"id": "source-camera-test", "kind": "camera",
                    "name": "Fixture camera", "cameraId": "camera-test", "profileId": "sub",
                    "hardwareDecode": "auto", "muted": True, "volume": 1,
                    "syncOffsetMs": 0, "monitoring": "off", "audioTrack": 1,
                    "filters": []}],
                "items": [{"id": "item-camera-test", "sourceId": "source-camera-test",
                    "x": 0, "y": 0, "width": 640, "height": 360, "scaleMode": "contain",
                    "crop": {"top": 0, "right": 0, "bottom": 0, "left": 0},
                    "zIndex": 0, "visible": True, "locked": False, "rotation": 0,
                    "opacity": 1, "blendMode": "normal"}],
            }],
        }), encoding="utf-8")
        service.initialize()
        self.keys = DeviceKeys()

    def tearDown(self):
        self.temporary.cleanup()

    def enroll_and_approve(self):
        enrollment = service.start_enrollment(self.keys.enrollment(os.urandom(32)))
        approved = service.approve_enrollment(enrollment["enrollmentId"], {
            "pairingCode": enrollment["pairingCode"], "cameraGrants": [{
                "cameraId": "camera-test", "profileIds": ["sub"],
                "permissions": ["view", "snapshot"], "credentialMode": "existing",
            }],
        })
        return enrollment, approved

    def test_signed_enrollment_rejects_forgery_and_replay(self):
        payload = self.keys.enrollment(os.urandom(32))
        enrollment = service.start_enrollment(payload)
        with service.connect() as database:
            stored = bytes(database.execute(
                "SELECT pairing_code_hash FROM enrollments WHERE id=?",
                (enrollment["enrollmentId"],)).fetchone()["pairing_code_hash"])
        self.assertEqual(len(stored), 48)
        self.assertNotEqual(stored, service.sha256(enrollment["pairingCode"]))
        self.assertTrue(service.pairing_matches(stored, enrollment["pairingCode"]))
        self.assertFalse(service.pairing_matches(stored, "00000000"))
        with self.assertRaisesRegex(service.ApiError, "already been used") as replay:
            service.start_enrollment(payload)
        self.assertEqual(replay.exception.status, 409)
        forged = self.keys.enrollment(os.urandom(32))
        forged["name"] = "Tampered name"
        with self.assertRaisesRegex(service.ApiError, "does not prove possession") as error:
            service.start_enrollment(forged)
        self.assertEqual(error.exception.status, 403)

    def test_internal_administrator_token_is_fail_closed(self):
        token = "a" * 64
        with mock.patch.dict(os.environ, {"WEBOBS_V2_INTERNAL_TOKEN": token}):
            service.require_internal_admin(token)
            with self.assertRaises(service.ApiError) as rejected:
                service.require_internal_admin("b" * 64)
            self.assertEqual(rejected.exception.status, 403)
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(service.ApiError) as unavailable:
                service.require_internal_admin(token)
            self.assertEqual(unavailable.exception.status, 503)

    def test_http_admin_boundary_and_device_bootstrap(self):
        token = "c" * 64
        enrollment, _ = self.enroll_and_approve()
        server = service.ThreadingHTTPServer(("127.0.0.1", 0), service.Handler)
        server.daemon_threads = True
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        origin = f"http://127.0.0.1:{server.server_port}"
        try:
            with mock.patch.dict(os.environ, {"WEBOBS_V2_INTERNAL_TOKEN": token}):
                with self.assertRaises(urllib.error.HTTPError) as rejected:
                    urllib.request.urlopen(origin + "/enrollments", timeout=2)
                self.assertEqual(rejected.exception.code, 403)
                request = urllib.request.Request(origin + "/enrollments",
                    headers={"X-WebObs-Internal-Admin": token})
                with urllib.request.urlopen(request, timeout=2) as response:
                    self.assertEqual(response.status, 200)
                request = urllib.request.Request(origin + "/client/bootstrap?sinceRevision=0",
                    headers={"X-WebObs-Device-Token": enrollment["deviceToken"]})
                with urllib.request.urlopen(request, timeout=2) as response:
                    body = json.load(response)
                self.assertEqual(body["contractVersion"], 1)
                self.assertNotIn("endpoint", json.dumps(body["cameras"]))
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)

    def test_encrypted_signed_grant_and_redacted_bootstrap(self):
        enrollment, approved = self.enroll_and_approve()
        status, completed = service.complete_enrollment(
            enrollment["enrollmentId"], enrollment["deviceToken"])
        self.assertEqual(status, 200)
        encoded, grant = self.keys.open_bundle(completed["grantBundle"])
        self.assertEqual(grant["clientId"], approved["clientId"])
        self.assertEqual(grant["cameras"][0]["credentials"]["username"], "fixture-viewer")
        self.assertIn(b"fixture-password", encoded)
        client = service.authenticate_device(enrollment["deviceToken"])
        bootstrap = service.bootstrap(client, 0)
        self.assertTrue(bootstrap["changed"])
        public_json = json.dumps({key: value for key, value in bootstrap.items()
                                  if key != "grantBundle"})
        self.assertNotIn("fixture-password", public_json)
        self.assertNotIn("rtsp://", public_json)
        self.assertEqual(bootstrap["onlineValidationIntervalSeconds"], 10)
        self.assertEqual(bootstrap["sharedScenes"][0]["id"], "shared-grid")
        self.assertTrue(bootstrap["cameras"][0]["weakRevocation"])
        unchanged = service.bootstrap(client, bootstrap["revision"])
        self.assertFalse(unchanged["changed"])
        self.assertEqual(unchanged["cameras"], [])
        self.assertEqual(unchanged["sharedScenes"], [])

        original = service.SCENES_PATH.read_text(encoding="utf-8")
        unsafe = json.loads(original)
        unsafe["scenes"][0]["sources"][0]["endpoint"] = "rtsp://camera.invalid/live"
        service.SCENES_PATH.write_text(json.dumps(unsafe), encoding="utf-8")
        with self.assertRaisesRegex(service.ApiError, "unsafe"):
            service.shared_scenes()
        service.SCENES_PATH.write_text(original, encoding="utf-8")

        secret = service.SECRET_ROOT / "camera-test.json"
        secret.write_text(
            '{"username":"fixture-viewer","password":"one","password":"two"}',
            encoding="utf-8")
        with self.assertRaisesRegex(service.ApiError, "unavailable"):
            service._load_secret("camera-test")

    def test_shared_scenes_reject_non_finite_and_invalid_transforms(self):
        original = service.SCENES_PATH.read_text(encoding="utf-8")
        document = json.loads(original)
        document["scenes"][0]["items"][0]["opacity"] = float("nan")
        service.SCENES_PATH.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaisesRegex(service.ApiError, "invalid"):
            service.shared_scenes()

        document = json.loads(original)
        document["scenes"][0]["items"][0]["crop"] = {
            "top": 0, "right": 0, "bottom": 0, "left": -1,
        }
        service.SCENES_PATH.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaisesRegex(service.ApiError, "unsafe"):
            service.shared_scenes()
        service.SCENES_PATH.write_text(original, encoding="utf-8")

    def test_shared_scenes_accept_bounded_filters_and_two_nested_levels(self):
        document = json.loads(service.SCENES_PATH.read_text(encoding="utf-8"))
        root = document["scenes"][0]
        root["sources"][0]["filters"] = [{
            "id": "scale-sub", "kind": "scaling", "enabled": True,
            "amount": 1, "value": "640x360",
        }, {
            "id": "dim-sub", "kind": "opacity", "enabled": True,
            "amount": 0.8, "value": "",
        }]
        child = json.loads(json.dumps(root))
        child.update({"id": "shared-child", "name": "Shared child"})
        grandchild = json.loads(json.dumps(root))
        grandchild.update({"id": "shared-grandchild", "name": "Shared grandchild"})
        child["sources"].append({
            "id": "nested-grandchild", "kind": "nested", "name": "Grandchild",
            "sceneId": "shared-grandchild", "muted": True, "volume": 1,
            "syncOffsetMs": 0, "monitoring": "off", "audioTrack": 1, "filters": [],
        })
        child["items"].append({
            "id": "item-grandchild", "sourceId": "nested-grandchild",
            "x": 0, "y": 0, "width": 320, "height": 180, "scaleMode": "contain",
            "crop": {"top": 0, "right": 0, "bottom": 0, "left": 0},
            "zIndex": 1, "visible": True, "locked": False, "groupId": "",
            "rotation": 0, "opacity": 1, "blendMode": "normal",
        })
        root["sources"].append({
            "id": "nested-child", "kind": "nested", "name": "Child",
            "sceneId": "shared-child", "muted": True, "volume": 1,
            "syncOffsetMs": 0, "monitoring": "off", "audioTrack": 1, "filters": [],
        })
        root["items"].append({
            "id": "item-child", "sourceId": "nested-child",
            "x": 320, "y": 0, "width": 320, "height": 180, "scaleMode": "contain",
            "crop": {"top": 0, "right": 0, "bottom": 0, "left": 0},
            "zIndex": 1, "visible": True, "locked": False, "groupId": "",
            "rotation": 0, "opacity": 1, "blendMode": "normal",
        })
        document["scenes"] = [root, child, grandchild]
        service.SCENES_PATH.write_text(json.dumps(document), encoding="utf-8")
        self.assertEqual(len(service.shared_scenes()), 3)

        document["scenes"][2]["sources"].append({
            "id": "cycle-root", "kind": "nested", "name": "Cycle",
            "sceneId": "shared-grid", "muted": True, "volume": 1,
            "syncOffsetMs": 0, "monitoring": "off", "audioTrack": 1, "filters": [],
        })
        document["scenes"][2]["items"].append({
            "id": "item-cycle", "sourceId": "cycle-root", "x": 0, "y": 180,
            "width": 320, "height": 180, "scaleMode": "contain",
            "crop": {"top": 0, "right": 0, "bottom": 0, "left": 0},
            "zIndex": 1, "visible": True, "locked": False, "groupId": "",
            "rotation": 0, "opacity": 1, "blendMode": "normal",
        })
        service.SCENES_PATH.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaisesRegex(service.ApiError, "unsafe"):
            service.shared_scenes()

    def test_shared_scenes_reject_unsafe_filter_parameters(self):
        document = json.loads(service.SCENES_PATH.read_text(encoding="utf-8"))
        source = document["scenes"][0]["sources"][0]
        source["filters"] = [{
            "id": "unsafe-mask", "kind": "mask-blend", "enabled": True,
            "amount": 1, "value": "/assets/../private/mask.png",
        }]
        service.SCENES_PATH.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaisesRegex(service.ApiError, "unsafe"):
            service.shared_scenes()

    def test_true_direct_plan_keeps_live_and_archive_topologies_independent(self):
        enrollment, _ = self.enroll_and_approve()
        client = service.authenticate_device(enrollment["deviceToken"])
        request = {
            "cameraId": "camera-test", "profileId": "sub", "policy": "auto",
            "receiverKind": "native", "networkClass": "lan", "reachability": "reachable",
            "protocols": ["rtsp"], "videoCodecs": ["h264"],
            "hardwareDecoders": ["vaapi"], "requiresComposite": False,
        }
        plans = [service.create_media_plan(client, request)[1] for _ in range(16)]
        self.assertTrue(all(plan["topology"] == "true-direct" for plan in plans))
        self.assertTrue(all(plan["liveServerMediaExpected"] is False for plan in plans))
        self.assertTrue(all(plan["archiveTopology"] == "server-copy" for plan in plans))
        self.assertTrue(all(plan["upstreamOwner"].startswith("client:") for plan in plans))
        self.assertTrue(all(plan["decoder"] == "vaapi" for plan in plans))

    def test_device_operations_enforce_each_camera_permission(self):
        enrollment, _ = self.enroll_and_approve()
        client = service.authenticate_device(enrollment["deviceToken"])
        client_id = client["id"]
        with mock.patch.object(service, "registry_request", return_value={"ok": True}) as request:
            self.assertEqual(
                service.client_camera_operation(client_id, "camera-test", "snapshot", None),
                {"ok": True})
            request.assert_called_once_with("POST", "camera-test", "snapshot")

        for operation, payload in (("ptz", {"action": "stop"}),
                                   ("presets", None),
                                   ("talk", {"action": "stop"})):
            with self.subTest(operation=operation), self.assertRaises(service.ApiError) as rejected:
                service.client_camera_operation(client_id, "camera-test", operation, payload)
            self.assertEqual(rejected.exception.status, 403)

    def test_device_operations_forward_only_the_fixed_registry_routes(self):
        enrollment = service.start_enrollment(self.keys.enrollment(os.urandom(32)))
        approved = service.approve_enrollment(enrollment["enrollmentId"], {
            "pairingCode": enrollment["pairingCode"], "cameraGrants": [{
                "cameraId": "camera-test", "profileIds": ["sub"],
                "permissions": ["view", "snapshot", "ptz", "talk"],
                "credentialMode": "existing",
            }],
        })
        with mock.patch.object(service, "registry_request", return_value={"ok": True}) as request:
            service.client_camera_operation(approved["clientId"], "camera-test", "presets", None)
            request.assert_called_once_with("GET", "camera-test", "presets")
            request.reset_mock()
            service.client_camera_operation(
                approved["clientId"], "camera-test", "ptz", {"action": "move", "x": 1})
            request.assert_called_once_with(
                "POST", "camera-test", "ptz", {"action": "move", "x": 1})
            request.reset_mock()
            service.client_camera_operation(
                approved["clientId"], "camera-test", "talk", {"action": "stop"})
            request.assert_called_once_with(
                "POST", "camera-test", "talk", {"action": "stop"})

        with self.assertRaises(service.ApiError) as body_rejected:
            service.client_camera_operation(
                approved["clientId"], "camera-test", "snapshot", {"unexpected": True})
        self.assertEqual(body_rejected.exception.status, 400)

        with mock.patch.object(service, "urlopen", side_effect=urllib.error.URLError(
                "rtsp://fixture-user:fixture-password@camera.invalid")):
            with self.assertRaises(service.ApiError) as hidden:
                service.registry_request("POST", "camera-test", "snapshot")
        self.assertEqual(hidden.exception.status, 503)
        self.assertNotIn("fixture-password", str(hidden.exception))

    def test_no_silent_fallback_and_online_revocation(self):
        enrollment, approved = self.enroll_and_approve()
        client = service.authenticate_device(enrollment["deviceToken"])
        status, plan = service.create_media_plan(client, {
            "cameraId": "camera-test", "profileId": "sub", "policy": "true-direct-only",
            "receiverKind": "native", "networkClass": "wan", "reachability": "unreachable",
            "protocols": ["rtsp"], "videoCodecs": ["h264"], "hardwareDecoders": [],
        })
        self.assertEqual(status, 409)
        self.assertEqual(plan["status"], "rejected")
        self.assertEqual(plan["fallbackReason"], "network_not_lan_or_vpn")
        service.revoke_client(approved["clientId"])
        with self.assertRaisesRegex(service.ApiError, "invalid") as error:
            service.authenticate_device(enrollment["deviceToken"])
        self.assertEqual(error.exception.status, 401)

    def test_expired_grant_and_bounded_audit(self):
        enrollment, approved = self.enroll_and_approve()
        with service.connect() as database:
            database.execute("UPDATE clients SET grant_expires_at=? WHERE id=?",
                             (int(time.time()) - 1, approved["clientId"]))
        with self.assertRaisesRegex(service.ApiError, "expired") as error:
            service.authenticate_device(enrollment["deviceToken"])
        self.assertEqual(error.exception.status, 401)
        with self.assertRaisesRegex(service.ApiError, "at most 128"):
            service.audit_batch(approved["clientId"], {"events": [{}] * 129})


if __name__ == "__main__":
    unittest.main(verbosity=2)
