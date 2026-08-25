#!/usr/bin/env python3
"""Architecture-level v2 True Direct grant and RTSP decode fixture."""

from __future__ import annotations

import base64
import ctypes
import importlib.util
from importlib.machinery import SourceFileLoader
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request


CONTROL = os.environ.get("WEBOBS_FIXTURE_CONTROL", "http://webobs:8080")
ENDPOINT = os.environ.get("WEBOBS_FIXTURE_RTSP", "rtsp://camera:8554/v2-direct")
TEST_SERVER_FALLBACK = os.environ.get("WEBOBS_TEST_SERVER_FALLBACK", "false") == "true"
SERVICE = Path("/fixture/client_control_service.py")


def load_service():
    specification = importlib.util.spec_from_loader(
        "webobs_v2_fixture_service", SourceFileLoader("webobs_v2_fixture_service", str(SERVICE)))
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


service = load_service()


def decode_b64url(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def decode_cbor(value: bytes, offset: int = 0):
    initial = value[offset]
    offset += 1
    major, additional = initial >> 5, initial & 31
    if initial in (0xF4, 0xF5, 0xF6):
        return ({0xF4: False, 0xF5: True, 0xF6: None}[initial], offset)
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
        raise ValueError("unsupported CBOR length")
    if major == 0:
        return length, offset
    if major == 1:
        return -1 - length, offset
    if major == 2:
        return value[offset:offset + length], offset + length
    if major == 3:
        return value[offset:offset + length].decode("utf-8"), offset + length
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
    raise ValueError("unsupported CBOR value")


class DeviceKeys:
    def __init__(self):
        sodium = service.sodium()
        self.signing_public, self.signing_secret = sodium.signing_keypair()
        sodium.library.crypto_box_keypair.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        sodium.library.crypto_box_keypair.restype = ctypes.c_int
        public = ctypes.create_string_buffer(32)
        secret = ctypes.create_string_buffer(32)
        if sodium.library.crypto_box_keypair(public, secret) != 0:
            raise RuntimeError("fixture encryption key generation failed")
        self.encryption_public, self.encryption_secret = public.raw, secret.raw

    def enrollment(self) -> dict[str, str]:
        nonce = os.urandom(32)
        proof = service.enrollment_proof(
            "True Direct fixture", "linux", self.signing_public, self.encryption_public, nonce)
        return {
            "name": "True Direct fixture", "platform": "linux",
            "signingPublicKey": service.b64url(self.signing_public),
            "encryptionPublicKey": service.b64url(self.encryption_public),
            "enrollmentNonce": service.b64url(nonce),
            "signature": service.b64url(service.sodium().sign(proof, self.signing_secret)),
        }

    def open_bundle(self, bundle: dict[str, object]) -> dict[str, object]:
        ciphertext = decode_b64url(str(bundle["ciphertext"]))
        plaintext = ctypes.create_string_buffer(len(ciphertext) - service.Sodium.SEAL_BYTES)
        source = ctypes.create_string_buffer(ciphertext, len(ciphertext))
        public = ctypes.create_string_buffer(self.encryption_public, 32)
        secret = ctypes.create_string_buffer(self.encryption_secret, 32)
        library = service.sodium().library
        library.crypto_box_seal_open.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_ulonglong, ctypes.c_void_p, ctypes.c_void_p]
        library.crypto_box_seal_open.restype = ctypes.c_int
        if library.crypto_box_seal_open(
                plaintext, source, len(ciphertext), public, secret) != 0:
            raise RuntimeError("sealed grant rejected")
        signature = plaintext.raw[:service.Sodium.SIGNATURE_BYTES]
        encoded = plaintext.raw[service.Sodium.SIGNATURE_BYTES:]
        signing_public = decode_b64url(str(bundle["serverSigningPublicKey"]))
        if not service.sodium().verify(signature, encoded, signing_public):
            raise RuntimeError("grant signature rejected")
        result, consumed = decode_cbor(encoded)
        if consumed != len(encoded) or not isinstance(result, dict):
            raise RuntimeError("grant CBOR rejected")
        return result


def request(method: str, path: str, body: object | None = None,
            device_token: str = "") -> tuple[int, dict[str, object]]:
    # The fixture reaches an isolated Docker DNS name, but the development
    # control plane intentionally accepts only loopback authorities without
    # HTTPS/file authentication. Preserve that public authority in Host.
    headers = {"Accept": "application/json", "Host": "127.0.0.1:8080"}
    data = None
    if body is not None:
        data = json.dumps(body, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if device_token:
        headers["Authorization"] = "WebObs-Device " + device_token
    message = urllib.request.Request(CONTROL + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(message, timeout=5) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


def request_sdp(method: str, path: str, token: str, body: str = "") -> tuple[int, str, str]:
    headers = {
        "Accept": "application/sdp", "Host": "127.0.0.1:8080",
        "Authorization": "Bearer " + token,
    }
    data = None
    if body:
        data = body.encode("utf-8")
        headers["Content-Type"] = "application/sdp"
    message = urllib.request.Request(CONTROL + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(message, timeout=20) as response:
            return response.status, response.headers.get("Location", ""), response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        return error.code, error.headers.get("Location", ""), error.read().decode("utf-8")


def exercise_server_fallback(token: str) -> str:
    status, plan = request("POST", "/api/v2/media-plans", {
        "cameraId": "v2-direct-fixture", "profileId": "sub", "policy": "auto",
        "receiverKind": "native", "networkClass": "lan", "reachability": "unreachable",
        "protocols": ["rtsp"], "videoCodecs": ["h264"], "hardwareDecoders": [],
        "requiresComposite": False,
    }, token)
    if status != 201 or plan.get("topology") != "gateway-direct":
        raise RuntimeError("Gateway fallback topology was not selected")
    plan_id = str(plan["planId"])
    status, activation = request(
        "POST", f"/api/v2/media-plans/{plan_id}/activate", {}, token)
    if status != 200 or activation.get("mediaEndpoint", {}).get("endpoint") != \
            f"/api/v2/media-plans/{plan_id}/whep":
        raise RuntimeError("Gateway fallback lease activation failed")
    forged_status, _, _ = request_sdp(
        "POST", f"/api/v2/media-plans/{'0' * 32}/whep", token, "v=0\r\n")
    if forged_status != 404:
        raise RuntimeError("forged Gateway fallback plan was not rejected")
    stolen_status, _, _ = request_sdp(
        "POST", f"/api/v2/media-plans/{plan_id}/whep", "0" * 64, "v=0\r\n")
    if stolen_status != 401:
        raise RuntimeError("invalid Gateway fallback bearer was not rejected")
    offer = "\r\n".join([
        "v=0", "o=- 0 0 IN IP4 127.0.0.1", "s=-", "t=0 0",
        "a=group:BUNDLE 0", "m=video 9 UDP/TLS/RTP/SAVPF 96", "c=IN IP4 0.0.0.0",
        "a=mid:0", "a=recvonly", "a=rtcp-mux", "a=rtpmap:96 H264/90000",
        "a=ice-ufrag:fixture", "a=ice-pwd:fixture-ice-credential-0001",
        "a=fingerprint:sha-256 " + ":".join(["11"] * 32), "a=setup:actpass", "",
    ])
    status, location, _ = request_sdp(
        "POST", f"/api/v2/media-plans/{plan_id}/whep", token, offer)
    if status == 201:
        if not location.startswith(f"/api/v2/media-plans/{plan_id}/whep/session/"):
            raise RuntimeError("Gateway fallback returned an unsafe WHEP session location")
        closed, _, _ = request_sdp("DELETE", location, token)
        if closed not in {200, 204}:
            raise RuntimeError("Gateway fallback WHEP session did not close")
    elif status != 502:
        raise RuntimeError(f"Gateway fallback did not reach WHEP upstream safely: HTTP {status}")
    released, value = request(
        "DELETE", f"/api/v2/media-plans/{plan_id}/activation", None, token)
    if released != 200 or value.get("released") is not True:
        raise RuntimeError("Gateway fallback lease did not release")
    status, _ = request("GET", f"/api/v2/media-plans/{plan_id}/activation", None, token)
    if status != 409:
        raise RuntimeError("released Gateway fallback lease remained usable")
    stale_status, _, _ = request_sdp(
        "POST", f"/api/v2/media-plans/{plan_id}/whep", token, offer)
    if stale_status != 409:
        raise RuntimeError("released Gateway fallback WHEP endpoint remained usable")
    return plan["topology"]


def wait_ready() -> None:
    for _ in range(120):
        try:
            status, _ = request("GET", "/api/v1/ready")
            if status == 200:
                return
        except (OSError, ValueError):
            pass
        time.sleep(0.5)
    raise RuntimeError("control plane did not become ready")


def wait_rtsp() -> None:
    for _ in range(60):
        result = subprocess.run([
            "ffprobe", "-v", "error", "-rtsp_transport", "tcp", "-read_intervals", "%+1",
            "-select_streams", "v:0", "-show_entries", "stream=codec_name", "-of", "json", ENDPOINT,
        ], check=False, capture_output=True, text=True, timeout=8)
        if result.returncode == 0:
            return
        time.sleep(0.5)
    raise RuntimeError("RTSP fixture did not become ready")


def main() -> None:
    wait_ready()
    wait_rtsp()
    status, camera = request("POST", "/api/v1/cameras", {
        "id": "v2-direct-fixture", "name": "True Direct fixture", "address": ENDPOINT,
        "adapter": "rtsp", "credentialsRef": "v2-direct-fixture", "hardwareDecode": "auto",
        "capabilities": {}, "profiles": [{
            "id": "sub", "name": "Sub", "role": "sub", "endpoint": ENDPOINT,
            "videoCodec": "h264", "audioCodec": "", "width": 640, "height": 360, "fps": 15,
        }],
    })
    if status != 201 or camera.get("id") != "v2-direct-fixture":
        raise RuntimeError("camera fixture registration failed")
    keys = DeviceKeys()
    status, enrollment = request("POST", "/api/v2/enrollments", keys.enrollment())
    if status != 201:
        raise RuntimeError("client enrollment failed")
    status, approval = request("POST", f"/api/v2/enrollments/{enrollment['enrollmentId']}/approve", {
        "pairingCode": enrollment["pairingCode"], "cameraGrants": [{
            "cameraId": "v2-direct-fixture", "profileIds": ["sub"],
            "permissions": ["view", "snapshot", "record-local"], "credentialMode": "existing",
        }],
    })
    if status != 200 or approval.get("state") != "approved":
        raise RuntimeError("administrator approval failed")
    token = str(enrollment["deviceToken"])
    status, completion = request(
        "POST", f"/api/v2/enrollments/{enrollment['enrollmentId']}/complete", {}, token)
    if status != 200:
        raise RuntimeError("client enrollment completion failed")
    grant = keys.open_bundle(completion["grantBundle"])
    granted_camera = grant["cameras"][0]
    profile = granted_camera["profiles"][0]
    if profile["endpoint"] != ENDPOINT or profile["adapter"] != "rtsp" or \
            granted_camera["credentials"]["username"] != "fixture-viewer":
        raise RuntimeError("grant did not contain the expected encrypted camera access")
    status, plan = request("POST", "/api/v2/media-plans", {
        "cameraId": "v2-direct-fixture", "profileId": "sub", "policy": "true-direct-only",
        "receiverKind": "native", "networkClass": "lan", "reachability": "reachable",
        "protocols": ["rtsp"], "videoCodecs": ["h264"], "hardwareDecoders": [],
        "requiresComposite": False,
    }, token)
    if status != 201 or plan.get("topology") != "true-direct" or \
            plan.get("liveServerMediaExpected") is not False or not str(plan.get("upstreamOwner", "")).startswith("client:"):
        raise RuntimeError("True Direct topology contract failed")
    result = subprocess.run([
        "ffprobe", "-v", "error", "-rtsp_transport", "tcp", "-read_intervals", "%+8",
        "-select_streams", "v:0", "-count_frames", "-show_entries",
        "stream=codec_name,width,height,nb_read_frames", "-of", "json", profile["endpoint"],
    ], check=False, capture_output=True, text=True, timeout=20)
    if result.returncode != 0:
        raise RuntimeError("direct RTSP decode failed")
    probe = json.loads(result.stdout)
    stream = probe.get("streams", [{}])[0]
    if stream.get("codec_name") != "h264" or int(stream.get("nb_read_frames", 0)) < 30:
        raise RuntimeError("direct RTSP decode produced insufficient video")
    fallback = exercise_server_fallback(token) if TEST_SERVER_FALLBACK else "not-tested"
    print(json.dumps({
        "result": "passed", "topology": plan["topology"],
        "liveServerMediaExpected": plan["liveServerMediaExpected"],
        "codec": stream["codec_name"], "decodedFrames": int(stream["nb_read_frames"]),
        "serverFallback": fallback,
    }, separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    main()
