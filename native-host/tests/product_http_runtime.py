#!/usr/bin/env python3
"""Real core + account Handler/Argon2id + Registry, using disposable private data."""
from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
from http.server import ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import sqlite3
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]


class WebSocketProbe:
    """Bounded real TCP/RFC6455 observer, without an extra runtime dependency."""
    def __init__(self, port, cookie):
        self.socket = socket.create_connection(("127.0.0.1", port), timeout=6)
        self.reader = self.socket.makefile("rb")
        try:
            key = base64.b64encode(secrets.token_bytes(16)).decode()
            origin = f"http://127.0.0.1:{port}"
            self.socket.sendall((f"GET /api/v1/ws HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
                f"Origin: {origin}\r\nCookie: {cookie}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
            assert self.reader.readline(4096).startswith(b"HTTP/1.1 101 "), "real WebSocket upgrade failed"
            headers = {}
            size = 0
            for _ in range(128):
                line = self.reader.readline(4096)
                size += len(line)
                assert line and size <= 16384
                if line == b"\r\n":
                    break
                name, value = line.split(b":", 1)
                headers[name.lower()] = value.strip()
            else:
                raise AssertionError("WebSocket upgrade headers exceeded limit")
            expected = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest())
            assert headers.get(b"sec-websocket-accept") == expected
            opcode, payload = self.frame()
            assert opcode == 1 and isinstance(json.loads(payload), dict)
        except BaseException:
            self.close()
            raise

    def frame(self):
        def read(count):
            data = self.reader.read(count)
            if len(data) != count:
                raise EOFError("owned WebSocket closed")
            return data
        first, second = read(2)
        assert first & 0x80 and not first & 0x70 and not second & 0x80
        length = second & 0x7f
        if length == 126:
            length = struct.unpack("!H", read(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", read(8))[0]
        assert length <= 2 * 1024 * 1024
        return first & 0x0f, read(length)

    def ping(self):
        payload, mask = b"health", secrets.token_bytes(4)
        self.socket.sendall(bytes((0x89, 0x80 | len(payload))) + mask +
            bytes(value ^ mask[index % 4] for index, value in enumerate(payload)))
        opcode, reply = self.frame()
        assert opcode == 10 and reply == payload, "unrevoked WebSocket did not remain usable"

    def wait_closed(self):
        deadline = time.monotonic() + 6
        try:
            while time.monotonic() < deadline:
                self.socket.settimeout(max(0.01, deadline - time.monotonic()))
                if self.frame()[0] == 8:
                    return
        except (EOFError, ConnectionResetError, ConnectionAbortedError):
            return
        raise AssertionError("revoked WebSocket remained open beyond its deadline")

    def close(self):
        self.reader.close()
        self.socket.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def exercise(binary):
    with tempfile.TemporaryDirectory(prefix="webobs-product-http-") as temporary, contextlib.ExitStack() as cleanup:
        private = Path(temporary)
        if os.name == "nt":
            load("product_private_directory", ROOT / "desktop/python/private_directory.py").protect(private)
        cluster = load("product_account_runtime", ROOT / "cluster/cluster_service.py")
        camera = load("product_registry_runtime", ROOT / "camera/camera_registry.py")
        camera.DB_PATH = private / "cameras.db"
        camera.SECRET_ROOT = private / "secrets"
        camera.initialize()
        with camera.connect() as database:
            for name in ("camera-a", "camera-b"):
                database.execute(
                    "INSERT INTO cameras(id,name,address,adapter,credentials_ref,hardware_decode,"
                    "capabilities_json,health,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (name, name, "rtsp://127.0.0.1:9/synthetic", "rtsp", "", "auto", "{}", "unknown", 1, 1))
                database.execute(
                    "INSERT INTO stream_profiles(id,camera_id,name,role,endpoint,video_codec,audio_codec,width,height,fps) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    ("main", name, "Main", "main", "rtsp://127.0.0.1:9/synthetic", "h265", "", 320, 180, 10))
            database.execute("UPDATE cameras SET hardware_decode='off' WHERE id='camera-a'")
            database.execute("UPDATE stream_profiles SET transport_mode='rtsp-tcp' WHERE camera_id='camera-a'")
        def scene(identifier, camera_ids):
            sources = [{"id": f"source-{index}", "name": f"Source {index}", "kind": "camera",
                "cameraId": camera_id, "profileId": "main", "hardwareDecode": "auto"}
                for index, camera_id in enumerate(camera_ids)]
            return {"schemaVersion": 6, "revision": 0, "id": identifier, "name": identifier,
                "canvas": {"width": 1920, "height": 1080, "backgroundColor": "#000000"},
                "sources": sources, "items": [{"id": f"item-{index}", "sourceId": source["id"],
                    "x": index * 640, "y": 0, "width": 640, "height": 360, "scaleMode": "contain",
                    "zIndex": index, "visible": True,
                    "crop": {"top": 0, "right": 0, "bottom": 0, "left": 0}} for index, source in enumerate(sources)]}
        allowed_scene = scene("allowed", ["camera-a"])
        denied_scene = scene("denied", ["camera-a", "camera-b"])
        raw_scene = scene("unbound", ["camera-a"])
        raw_scene["sources"] = [{"id": "source-0", "name": "Unbound private source", "kind": "rtsp",
            "rtspUrl": "rtsp://private:private@127.0.0.1:9/not-a-catalog-binding", "transport": "tcp"}]
        nested_scene = scene("nested", ["camera-a"])
        nested_scene["sources"] = [{"id": "source-0", "name": "Nested allowed", "kind": "nested", "sceneId": "allowed"}]
        for document in (allowed_scene, denied_scene, raw_scene, nested_scene):
            for source in document["sources"]:
                source.update(muted=True, volume=1, syncOffsetMs=0, monitoring="off", audioTrack=1)
        fixture_studio = {"schemaVersion": 1, "revision": 0,
            "programSceneId": "allowed", "previewSceneId": "allowed", "transition": {"kind": "cut", "durationMs": 300},
            "scenes": [allowed_scene, denied_scene, raw_scene, nested_scene]}
        cluster.INTERNAL_TOKEN = secrets.token_hex(32)
        cluster.STORE = cluster.ClusterStore(private / "accounts.db", cluster.PasswordHasher(),
                                            camera_registry_path=camera.DB_PATH)
        cleanup.callback(cluster.STORE.close)
        password = secrets.token_urlsafe(24)
        cluster.STORE.create_user({"username": "native-viewer", "password": password,
            "roles": ["viewer"], "scopes": [{"kind": "camera", "id": "camera-a"}]})
        resolved = []
        authority_paths = []
        batch_hooks = []
        identity_hooks = []
        authority_overrides = {}
        before_authority_hooks, after_authority_hooks, authorization_statuses = [], [], []
        account_hooks = []

        class AccountHandler(cluster.Handler):
            def response(self, status, value=None):
                if self.path == "/auth/native-authorize":
                    authorization_statuses.append(status)
                super().response(status, value)

            def do_POST(self):
                authority_paths.append(self.path)
                if self.path in authority_overrides:
                    self.response(*authority_overrides.pop(self.path))
                    return
                if self.path == "/auth/native-authorize-batch" and batch_hooks:
                    batch_hooks.pop(0)()
                if self.path == "/auth/native-session" and identity_hooks:
                    identity_hooks.pop(0)()
                if self.path == "/auth/native-authorize" and before_authority_hooks:
                    before_authority_hooks.pop(0)()
                if self.path == "/auth/native-authorize" and after_authority_hooks:
                    hook = after_authority_hooks.pop(0)
                    # Hold the real authority RLock through reply + role change;
                    # a second decision cannot overtake this deterministic fence.
                    with cluster.STORE.lock:
                        super().do_POST()
                        hook()
                    return
                super().do_POST()

            def do_PATCH(self):
                if self.path.startswith("/account/") and account_hooks:
                    account_hooks.pop(0)(self.headers)
                super().do_PATCH()

        class RegistryHandler(camera.Handler):
            def do_GET(self):
                if self.path.startswith("/resolve/"):
                    resolved.append(self.path)
                super().do_GET()

        account_server = ThreadingHTTPServer(("127.0.0.1", 0), AccountHandler)
        camera_server = ThreadingHTTPServer(("127.0.0.1", 0), RegistryHandler)
        for server in (account_server, camera_server):
            cleanup.callback(server.server_close)
            cleanup.callback(server.shutdown)
            threading.Thread(target=server.serve_forever, daemon=True).start()
        with socket.socket() as lease:
            lease.bind(("127.0.0.1", 0))
            port = lease.getsockname()[1]
        host_secret = secrets.token_hex(32)
        environment = {key: value for key, value in os.environ.items() if not key.startswith("WEBOBS_")}
        environment.update(WEBOBS_HTTP_PORT=str(port), WEBOBS_LISTEN_ADDRESS="127.0.0.1",
            WEBOBS_CLUSTER_INTERNAL_PORT=str(account_server.server_port),
            WEBOBS_CAMERA_INTERNAL_PORT=str(camera_server.server_port),
            WEBOBS_CLUSTER_INTERNAL_TOKEN=cluster.INTERNAL_TOKEN, WEBOBS_NATIVE_HOST_TOKEN=host_secret,
            WEBOBS_COMPAT_BASIC_AUTH="false", WEBOBS_SESSION_COOKIE_SECURE="false",
            WEBOBS_SESSION_DATABASE=str(private / "sessions.db"), WEBOBS_SCENE_FILE=str(private / "scene.json"),
            WEBOBS_WEBRTC_ENABLED="true", WEBOBS_COMPOSITE_ENABLED="false", WEBOBS_NVR_ENABLED="false",
            WEBOBS_FPS="15",
            WEBOBS_WHIP_URL="http://127.0.0.1:9/synthetic/whip", NO_PROXY="127.0.0.1,localhost")
        origin = f"http://127.0.0.1:{port}"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        cookie = ""

        def request(path, value=None, *, method=None, secret=host_secret, request_origin=origin,
                    use_cookie=True, cookie_override=None, revision=None, extra_headers=None):
            headers = {"Origin": request_origin, "Content-Type": "application/json", "X-WebOBS-Native-Host": secret}
            headers.update(extra_headers or {})
            effective_cookie = cookie if cookie_override is None else cookie_override
            if effective_cookie and use_cookie:
                headers["Cookie"] = effective_cookie
            if revision is not None:
                headers["If-Match"] = '"' + str(revision) + '"'
            data = None if value is None else json.dumps(value).encode()
            message = urllib.request.Request(origin + path, data=data, headers=headers, method=method)
            try:
                reply = opener.open(message, timeout=13)
            except urllib.error.HTTPError as error:
                reply = error
            with reply:
                payload = reply.read()
                return reply.status, reply.headers.get("Set-Cookie", ""), json.loads(payload) if payload else {}

        with (private / "private-core.log").open("wb") as log:
            process = subprocess.Popen([str(binary), "--duration-seconds", "120"], env=environment,
                stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}))
            try:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        # Public diagnostics contain only exit status and fixed
                        # startup categories, never private logs/URLs/paths.
                        categories = ("Could not load Studio state", "Could not initialize Studio state",
                                      "scene storage error", "Could not start native control server")
                        try:
                            tail = (private / "private-core.log").read_bytes()[-65536:].decode("utf-8", errors="replace")
                        except OSError:
                            tail = ""
                        print(json.dumps({"phase": "readiness", "exitCode": process.returncode,
                            "startupCategories": [marker for marker in categories if marker in tail]}))
                        raise AssertionError("isolated control process exited before readiness")
                    try:
                        if request("/api/v1/health")[0] == 200:
                            break
                    except OSError:
                        time.sleep(0.1)
                else:
                    raise AssertionError("isolated control process did not become ready")
                if os.name == "nt":
                    # Exercise the actual Windows core before UI/media gates.
                    with socket.socket() as competitor:
                        competitor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                        try:
                            competitor.bind(("127.0.0.1", port))
                        except OSError as error:
                            assert error.winerror in (10013, 10048)
                        else:
                            raise AssertionError("native listener permitted a forced rebind")
                login = {"username": "native-viewer", "password": password}
                assert request("/api/v1/auth/setup")[2]["registrationOpen"] is True
                first_admin = {"username": "native-admin", "password": secrets.token_urlsafe(24)}
                assert request("/api/v1/auth/setup", first_admin)[0] == 201
                assert request("/api/v1/auth/setup")[2]["registrationOpen"] is False
                assert request("/api/v1/auth/setup", first_admin)[0] == 409
                # Save the fixture through the real authenticated controller and
                # private atomic writer, rather than pre-seeding a platform file.
                code, setup_issued, _ = request("/api/v1/auth/login", first_admin, use_cookie=False)
                assert code == 200 and setup_issued
                setup_cookie = setup_issued.split(";", 1)[0]
                assert request("/api/v1/auth/session", cookie_override=setup_cookie)[0] == 200
                assert request("/api/v2/account/me", cookie_override=setup_cookie)[0] == 200
                authority_overrides["/auth/native-session"] = (503, {"error": {
                    "code": "fixture_unavailable", "message": "synthetic unavailable"}})
                assert request("/api/v1/auth/session", cookie_override=setup_cookie)[0] == 503
                assert request("/api/v1/auth/session", cookie_override=setup_cookie)[0] == 200, \
                    "authority outage permanently revoked a valid account session"
                authority_overrides["/auth/native-session"] = (200, {"authenticated": True,
                    "userId": "0" * 32, "authEpoch": "0" * 32})
                assert request("/api/v1/auth/session", cookie_override=setup_cookie)[0] == 503
                authority_overrides["/auth/native-authorize"] = (200, {"allowed": True,
                    "permission": "scene.read", "userId": "0" * 32, "authEpoch": "0" * 32})
                assert request("/api/v1/studio", cookie_override=setup_cookie)[0] == 503
                assert request("/api/v1/studio", cookie_override=setup_cookie)[0] == 200
                with contextlib.closing(sqlite3.connect(private / "sessions.db")) as database:
                    row = database.execute("SELECT user_id,auth_epoch FROM auth_sessions WHERE user_name=?",
                                           (first_admin["username"],)).fetchone()
                    assert row and all(isinstance(value, str) and len(value) == 32 for value in row), \
                        "ordinary native-product login did not bind identity"
                # A legacy username-only cookie cannot acquire a current identity
                # merely by visiting either management or native routes.
                code, legacy_issued, _ = request("/api/v1/auth/login", first_admin, use_cookie=False)
                assert code == 200 and legacy_issued
                legacy_cookie = legacy_issued.split(";", 1)[0]
                legacy_hash = hashlib.sha256(legacy_cookie.split("=", 1)[1].encode()).hexdigest()
                with contextlib.closing(sqlite3.connect(private / "sessions.db")) as database, database:
                    changed = database.execute("UPDATE auth_sessions SET user_id=NULL,auth_epoch=NULL "
                                               "WHERE session_id_hash=?", (legacy_hash,))
                    assert changed.rowcount == 1
                authority_paths.clear()
                assert request("/api/v1/native/auth/session", cookie_override=legacy_cookie)[0] == 401
                assert request("/api/v1/auth/session", cookie_override=legacy_cookie)[0] == 401
                assert authority_paths == [], "unbound management session reached authoritative identity lookup"
                assert request("/api/v1/studio", cookie_override=setup_cookie)[0] == 200, \
                    "rejecting an unbound cookie revoked another bound login"
                code, retiring_issued, _ = request("/api/v1/auth/login", first_admin, use_cookie=False)
                assert code == 200 and retiring_issued
                retiring_cookie = retiring_issued.split(";", 1)[0]
                retiring_hash = hashlib.sha256(retiring_cookie.split("=", 1)[1].encode()).hexdigest()
                def retire_inflight_session():
                    with contextlib.closing(sqlite3.connect(private / "sessions.db")) as database, database:
                        database.execute("DELETE FROM auth_sessions WHERE session_id_hash=?", (retiring_hash,))
                identity_hooks.append(retire_inflight_session)
                assert request("/api/v1/auth/session", cookie_override=retiring_cookie)[0] == 401
                assert not identity_hooks
                assert request("/api/v1/auth/session", cookie_override=setup_cookie)[0] == 200, \
                    "one session logout revoked another session for the same identity"
                code, _, bootstrap_studio = request("/api/v1/studio", cookie_override=setup_cookie)
                assert code == 200 and bootstrap_studio["revision"] == 0
                code, _, stored_fixture = request("/api/v1/studio", fixture_studio, method="PUT", revision=0,
                    cookie_override=setup_cookie)
                assert code == 200 and stored_fixture["revision"] == 1, \
                    f"ordinary Studio API did not persist the fixture (HTTP {code})"
                assert request("/api/v1/native/auth/login", login, secret="0" * 64)[0] == 403
                assert request("/api/v1/native/auth/login", login, request_origin="https://untrusted.invalid")[0] == 403
                assert request("/api/v1/native/auth/session")[0] == 401
                status, issued, identity = request("/api/v1/native/auth/login", login)
                assert status == 200 and issued, "native login did not issue a bound session"
                assert len(identity["userId"]) == 32
                cookie = issued.split(";", 1)[0]
                assert request("/api/v1/native/auth/session")[0] == 200
                status, _, catalog = request("/api/v1/native/cameras")
                assert status == 200 and [item["id"] for item in catalog["cameras"]] == ["camera-a"], \
                    "native catalog exposed an unauthorized camera"
                status, _, scenes = request("/api/v1/native/scenes")
                assert status == 200 and scenes["revision"] == 1
                assert [item["id"] for item in scenes["scenes"]] == ["allowed", "denied", "unbound", "nested"]
                assert "rtsp://" not in json.dumps(scenes) and "127.0.0.1" not in json.dumps(scenes)
                for scene_id, expected in (("denied", 403), ("unbound", 409), ("missing", 409)):
                    assert request("/api/v1/native/scenes/resolve", {"sceneId": scene_id, "revision": 1})[0] == expected
                    assert resolved == [], "rejected scene resolved a private endpoint"
                for invalid in ({"sceneId": "allowed", "revision": True},
                                {"sceneId": "allowed", "revision": 1, "cameras": []},
                                {"sceneId": "../allowed", "revision": 1}):
                    assert request("/api/v1/native/scenes/resolve", invalid)[0] == 400
                assert request("/api/v1/native/scenes/resolve", {"sceneId": "allowed", "revision": 0})[0] == 412
                fingerprints = {}
                for scene_id in ("allowed", "nested"):
                    status, _, value = request("/api/v1/native/scenes/resolve", {"sceneId": scene_id, "revision": 1})
                    assert status == 200 and value["studioRevision"] == 1 and value["cameraVersions"] == {"camera-a": 1}
                    assert len(value["cameras"]) == 1 and value["cameras"][0]["cameraId"] == "camera-a"
                    fingerprints[scene_id] = value["sceneFingerprint"]
                    assert re.fullmatch(r"[a-f0-9]{64}", fingerprints[scene_id])
                    assert value["scene"]["sources"][0]["kind"] == "camera" and "rtsp://" not in json.dumps(value["scene"])
                    before = list(resolved)
                    status, _, renewed_scene = request("/api/v1/native/scenes/authorize", {"sceneId": scene_id, "revision": 1})
                    assert status == 200 and renewed_scene["studioRevision"] == 1 and "scene" not in renewed_scene
                    assert resolved == before and "url" not in json.dumps(renewed_scene)
                    assert request("/api/v1/native/scenes/authorize", {
                        "sceneId": scene_id, "fingerprint": fingerprints[scene_id]})[0] == 200
                resolved.clear()
                # Change the canonical document through the ordinary admin API,
                # rather than editing a file that the live controller cannot see.
                code, admin_issued, _ = request("/api/v1/auth/login", first_admin, use_cookie=False)
                assert code == 200 and admin_issued
                admin_cookie = admin_issued.split(";", 1)[0]
                code, _, studio = request("/api/v1/studio", cookie_override=admin_cookie)
                assert code == 200 and studio["revision"] == 1
                studio["scenes"][0]["name"] = "Allowed revised through existing API"
                assert request("/api/v1/studio", studio, method="PUT", revision=1)[0] == 403
                code, _, updated = request("/api/v1/studio", studio, method="PUT", revision=1,
                    cookie_override=admin_cookie)
                assert code == 200 and updated["revision"] == 2
                assert request("/api/v1/native/scenes/authorize", {"sceneId": "allowed", "revision": 1})[0] == 412
                assert request("/api/v1/native/scenes/resolve", {"sceneId": "allowed", "revision": 1})[0] == 412
                assert request("/api/v1/native/scenes/authorize", {
                    "sceneId": "allowed", "fingerprint": fingerprints["allowed"]})[0] == 412
                assert resolved == [], "stale canonical scene read private endpoints after an ordinary API update"
                code, _, active_scene = request("/api/v1/native/scenes/authorize", {"sceneId": "allowed", "revision": 2})
                assert code == 200
                active_fingerprint = active_scene["sceneFingerprint"]
                unrelated = json.loads(json.dumps(updated))
                unrelated["scenes"][1]["name"] = "Unrelated scene updated"
                code, _, unrelated = request("/api/v1/studio", unrelated, method="PUT", revision=2,
                    cookie_override=admin_cookie)
                assert code == 200 and unrelated["revision"] == 3
                code, _, unchanged_scene = request("/api/v1/native/scenes/authorize", {
                    "sceneId": "allowed", "fingerprint": active_fingerprint})
                assert code == 200 and unchanged_scene["studioRevision"] == 3
                assert unchanged_scene["sceneFingerprint"] == active_fingerprint
                assert request("/api/v1/native/scenes/authorize", {"sceneId": "allowed", "revision": 2})[0] == 412
                for invalid in ("", "0" * 63, "A" * 64):
                    assert request("/api/v1/native/scenes/authorize", {"sceneId": "allowed", "fingerprint": invalid})[0] == 400
                assert request("/api/v1/native/scenes/authorize", {"sceneId": "allowed", "fingerprint": "0" * 64})[0] == 412
                assert request("/api/v1/native/scenes/authorize", {
                    "sceneId": "allowed", "revision": 3, "fingerprint": active_fingerprint})[0] == 400
                assert resolved == [], "fingerprint renewal read a private endpoint"
                code, _, content_resolved = request("/api/v1/native/scenes/resolve", {
                    "sceneId": "allowed", "fingerprint": active_fingerprint})
                assert code == 200 and content_resolved["studioRevision"] == 3
                assert content_resolved["sceneFingerprint"] == active_fingerprint and len(resolved) == 1
                resolved.clear()
                # Edit through the real public controller while the native
                # request is in its batch-authority call. The final content
                # recheck must distinguish unrelated and relevant changes.
                concurrent_results = []
                concurrent = json.loads(json.dumps(unrelated))
                concurrent["scenes"][1]["name"] = "Unrelated concurrent edit"
                batch_hooks.append(lambda: concurrent_results.append(request("/api/v1/studio", concurrent,
                    method="PUT", revision=3, cookie_override=admin_cookie)))
                code, _, concurrent_authorized = request("/api/v1/native/scenes/authorize", {
                    "sceneId": "allowed", "fingerprint": active_fingerprint})
                assert concurrent_results[0][0] == 200 and concurrent_results[0][2]["revision"] == 4
                assert code == 200 and concurrent_authorized["studioRevision"] == 4
                concurrent = json.loads(json.dumps(concurrent_results[0][2]))
                # Large enough to survive the nested scene's integer scaling.
                concurrent["scenes"][0]["items"][0]["x"] += 120
                batch_hooks.append(lambda: concurrent_results.append(request("/api/v1/studio", concurrent,
                    method="PUT", revision=4, cookie_override=admin_cookie)))
                assert request("/api/v1/native/scenes/authorize", {
                    "sceneId": "allowed", "fingerprint": active_fingerprint})[0] == 412
                assert concurrent_results[1][0] == 200 and concurrent_results[1][2]["revision"] == 5
                assert request("/api/v1/native/scenes/authorize", {
                    "sceneId": "nested", "fingerprint": fingerprints["nested"]})[0] == 412
                code, _, current_scene = request("/api/v1/native/scenes/authorize", {"sceneId": "allowed", "revision": 5})
                assert code == 200
                active_fingerprint = current_scene["sceneFingerprint"]
                assert resolved == [], "concurrent scene renewal read endpoint credentials"
                # A queued mutation must not treat the first successful HTTP
                # decision as a durable execution grant. Change roles after
                # that real response while preserving identity/epoch.
                executor_password = secrets.token_urlsafe(24)
                executor = cluster.STORE.create_user({"username": "mutation-admin", "password": executor_password,
                                                      "roles": ["admin"]})
                code, executor_issued, _ = request("/api/v1/auth/login", {
                    "username": "mutation-admin", "password": executor_password}, use_cookie=False)
                assert code == 200 and executor_issued
                executor_cookie = executor_issued.split(";", 1)[0]
                code, _, before_mutation = request("/api/v1/studio", cookie_override=admin_cookie)
                assert code == 200
                mutation = json.loads(json.dumps(before_mutation))
                mutation["scenes"][0]["name"] = "Rejected mutation must not persist"
                authorization_statuses.clear()
                after_authority_hooks.append(lambda: cluster.STORE.update_user(
                    executor["id"], {"roles": ["auditor"]}, executor["revision"]))
                code, _, _ = request("/api/v1/studio", mutation, method="PUT",
                    revision=before_mutation["revision"], cookie_override=executor_cookie)
                assert code == 403 and authorization_statuses == [200, 403], \
                    "queued mutation reused an earlier role grant"
                assert request("/api/v1/studio", cookie_override=admin_cookie)[2] == before_mutation
                assert request("/api/v1/auth/session", cookie_override=executor_cookie)[0] == 200
                cluster.STORE.update_user(executor["id"], {"roles": ["admin"]}, executor["revision"] + 1)
                executor_hash = hashlib.sha256(executor_cookie.split("=", 1)[1].encode()).hexdigest()
                def retire_executor_session():
                    with contextlib.closing(sqlite3.connect(private / "sessions.db")) as database, database:
                        database.execute("DELETE FROM auth_sessions WHERE session_id_hash=?", (executor_hash,))
                after_authority_hooks.append(lambda: before_authority_hooks.append(retire_executor_session))
                authorization_statuses.clear()
                code, clearing_cookie, _ = request("/api/v1/studio", mutation, method="PUT",
                    revision=before_mutation["revision"], cookie_override=executor_cookie)
                assert code == 401 and authorization_statuses == [200, 200] and "Max-Age=0" in clearing_cookie, \
                    "queued mutation ignored logout during execution authorization"
                assert request("/api/v1/studio", cookie_override=admin_cookie)[2] == before_mutation
                print("PASS queued real Studio mutations recheck roles and in-flight local logout before persistence")
                code, operation_issued, _ = request("/api/v1/auth/login", {
                    "username": "mutation-admin", "password": executor_password}, use_cookie=False)
                assert code == 200 and operation_issued
                operation_cookie = operation_issued.split(";", 1)[0]
                with cluster.STORE.lock:
                    operation_row = cluster.STORE.db.execute("SELECT id,auth_epoch FROM users WHERE username=?",
                                                             ("mutation-admin",)).fetchone()
                def replace_account_after_core_validation(headers):
                    assert headers.get("X-WebObs-Principal") == "mutation-admin"
                    assert headers.get("X-WebObs-Account-Id") == operation_row["id"]
                    assert headers.get("X-WebObs-Account-Epoch") == operation_row["auth_epoch"]
                    assert headers.get("Cookie") is None and headers.get("X-WebOBS-Native-Host") is None
                    with cluster.STORE.lock, cluster.STORE.db:
                        cluster.STORE.db.execute("DELETE FROM users WHERE id=?", (operation_row["id"],))
                    cluster.STORE.create_user({"username": "mutation-admin", "password": executor_password,
                                              "roles": ["auditor"]})
                account_hooks.append(replace_account_after_core_validation)
                code, clearing_cookie, _ = request("/api/v2/account/me", {"displayName": "Must not transfer"},
                    method="PATCH", cookie_override=operation_cookie, extra_headers={
                        "X-WebObs-Principal": "native-admin", "X-WebObs-Account-Id": "0" * 32,
                        "X-WebObs-Account-Epoch": "0" * 32})
                assert code == 401 and "Max-Age=0" in clearing_cookie and not account_hooks
                code, replacement_issued, _ = request("/api/v1/auth/login", {
                    "username": "mutation-admin", "password": executor_password}, use_cookie=False)
                assert code == 200 and replacement_issued
                replacement_cookie = replacement_issued.split(";", 1)[0]
                code, _, profile = request("/api/v2/account/me", cookie_override=replacement_cookie)
                assert code == 200 and profile["displayName"] == "mutation-admin", \
                    "a stale forwarded actor modified its same-name replacement"
                code, _, profile = request("/api/v2/account/me", {"displayName": "Current own account"},
                    method="PATCH", cookie_override=replacement_cookie)
                assert code == 200 and profile["displayName"] == "Current own account"
                code, _, changed_password = request("/api/v2/account/password", {
                    "currentPassword": executor_password, "newPassword": executor_password},
                    cookie_override=replacement_cookie)
                assert code == 200 and changed_password == {"changed": True}
                assert request("/api/v1/auth/session", cookie_override=replacement_cookie)[0] == 401
                print("PASS real account proxy binds immutable actor inside own-account transaction")
                with contextlib.closing(sqlite3.connect(private / "sessions.db")) as database:
                    row = database.execute("SELECT user_id,auth_epoch FROM auth_sessions WHERE user_id=?",
                        (identity["userId"],)).fetchone()
                    assert row and len(row[0]) == len(row[1]) == 32, "session was not identity-bound"
                selection = {"cameras": [{"cameraId": "camera-a", "profileId": "main"}]}
                denied = {"cameras": selection["cameras"] + [{"cameraId": "camera-b", "profileId": "main"}]}
                assert request("/api/v1/native/cameras/resolve", denied)[0] == 403
                assert resolved == [], "denied selection resolved a private endpoint"
                authority_paths.clear()
                status, _, authorized = request("/api/v1/native/cameras/authorize", selection)
                assert status == 200 and authorized["video"] == {"width": 1920, "height": 1080, "fps": 15}
                assert authorized["cameraVersions"] == {"camera-a": 1}
                assert authority_paths.count("/auth/native-authorize-batch") == 1
                assert authority_paths.count("/auth/native-authorize") == 2, "selection used per-camera authorization requests"
                assert resolved == [], "authorization unexpectedly resolved an endpoint"
                status, _, value = request("/api/v1/native/cameras/resolve", selection)
                assert status == 200 and len(value["cameras"]) == 1
                assert value["cameras"][0]["url"].startswith("rtsp://127.0.0.1:9/")
                assert value["cameras"][0]["hardwareDecode"] == "off"
                assert value["cameras"][0]["transport"] == "tcp"
                assert resolved == ["/resolve/camera-a/main?requireProfile=1"]
                for configured, expected in (("auto", "tcp"), ("rtsp-udp", "udp"),
                                             ("rtsp-udp-multicast", "udp_multicast")):
                    with camera.connect() as database:
                        database.execute("UPDATE stream_profiles SET transport_mode=? WHERE camera_id='camera-a'",
                                         (configured,))
                    status, _, value = request("/api/v1/native/cameras/resolve", selection)
                    assert status == 200 and value["cameras"][0]["transport"] == expected
                missing = {"cameras": [{"cameraId": "camera-a", "profileId": "missing"}]}
                assert request("/api/v1/native/cameras/resolve", missing)[0] == 503, "unknown profile silently fell back"
                assert request("/api/v1/native/cameras/resolve", {"cameras": [{"cameraId": "../bad", "profileId": "main"}]})[0] == 400
                for table in ("cameras", "stream_profiles"):
                    before = len(resolved)
                    with camera.connect() as database:
                        database.execute(f"UPDATE {table} SET enabled=0")
                    assert request("/api/v1/native/cameras/authorize", selection)[0] == 403
                    assert request("/api/v1/native/scenes/authorize", {
                        "sceneId": "allowed", "fingerprint": active_fingerprint})[0] == 403
                    assert request("/api/v1/native/cameras/resolve", selection)[0] == 403
                    assert len(resolved) == before, "disabled Profile reached private endpoint resolution"
                    with camera.connect() as database:
                        database.execute(f"UPDATE {table} SET enabled=1")
                    assert request("/api/v1/native/cameras/authorize", selection)[0] == 200
                before = len(resolved)
                changed = camera.patch_source_catalog("camera-a", {"profiles": [
                    {"id": "main", "transportMode": "auto"}]}, 1)
                assert changed["revision"] == 2
                code, _, renewed = request("/api/v1/native/cameras/authorize", selection)
                assert code == 200 and renewed["cameraVersions"] == {"camera-a": 2}
                code, _, renewed_scene = request("/api/v1/native/scenes/authorize", {
                    "sceneId": "allowed", "fingerprint": active_fingerprint})
                assert code == 200 and renewed_scene["cameraVersions"] == {"camera-a": 2}
                assert len(resolved) == before, "configuration renewal unexpectedly read endpoint credentials"
                code, browser_issued, browser_identity = request("/api/v1/auth/login", login, use_cookie=False)
                assert code == 200 and browser_issued and "authEpoch" not in browser_identity
                browser_cookie = browser_issued.split(";", 1)[0]
                assert request("/api/v1/auth/session", cookie_override=browser_cookie)[0] == 200
                assert request("/api/v1/studio", cookie_override=browser_cookie)[0] == 200
                # Real account epoch change invalidates the existing session.
                with cluster.STORE.lock, cluster.STORE.db:
                    cluster.STORE.db.execute("UPDATE users SET auth_epoch=? WHERE username=?",
                                             (secrets.token_hex(16), "native-viewer"))
                assert request("/api/v1/studio", cookie_override=browser_cookie)[0] == 401, \
                    "ordinary management API accepted a revoked identity"
                assert request("/api/v1/auth/session", cookie_override=browser_cookie)[0] == 401
                assert request("/api/v1/native/auth/session")[0] == 401
                assert request("/api/v1/native/scenes/authorize", {
                    "sceneId": "allowed", "fingerprint": active_fingerprint})[0] == 401
                assert request("/api/v1/native/cameras/resolve", selection)[0] == 401
                _, issued, _ = request("/api/v1/native/auth/login", login)
                cookie = issued.split(";", 1)[0]
                assert request("/api/v1/native/auth/logout", {}, method="POST")[0] == 200
                assert request("/api/v1/native/auth/session")[0] == 401
                code, fresh_issued, _ = request("/api/v1/auth/login", login, use_cookie=False)
                assert code == 200 and fresh_issued
                fresh_cookie = fresh_issued.split(";", 1)[0]
                assert request("/api/v1/auth/session", cookie_override=fresh_cookie)[0] == 200
                cluster.STORE.change_own_password("native-viewer", {
                    "currentPassword": password, "newPassword": password})
                assert request("/api/v1/auth/session", cookie_override=fresh_cookie)[0] == 401, \
                    "session-only validation accepted an actual password reset"
                code, old_issued, _ = request("/api/v1/auth/login", login, use_cookie=False)
                assert code == 200 and old_issued
                old_cookie = old_issued.split(";", 1)[0]
                with cluster.STORE.lock, cluster.STORE.db:
                    cluster.STORE.db.execute("DELETE FROM users WHERE username=?", ("native-viewer",))
                cluster.STORE.create_user({"username": "native-viewer", "password": password,
                    "roles": ["viewer"], "scopes": [{"kind": "camera", "id": "camera-a"}]})
                code, recreated_issued, _ = request("/api/v1/auth/login", login, use_cookie=False)
                assert code == 200 and recreated_issued
                recreated_cookie = recreated_issued.split(";", 1)[0]
                assert request("/api/v2/account/me", cookie_override=old_cookie)[0] == 401
                assert request("/api/v2/account/me", cookie_override=recreated_cookie)[0] == 200, \
                    "rejecting a former account revoked its same-name replacement"
                # Real upgraded sockets must not outlive logout/password/role
                # changes, and closing one token must preserve another login.
                code, parallel_issued, _ = request("/api/v1/auth/login", login, use_cookie=False)
                assert code == 200 and parallel_issued
                parallel_cookie = parallel_issued.split(";", 1)[0]
                with WebSocketProbe(port, recreated_cookie) as first_ws, \
                        WebSocketProbe(port, parallel_cookie) as second_ws:
                    first_ws.ping()
                    second_ws.ping()
                    assert request("/api/v1/auth/logout", {}, cookie_override=recreated_cookie)[0] == 204
                    first_ws.wait_closed()
                    second_ws.ping()
                    assert request("/api/v1/auth/session", cookie_override=parallel_cookie)[0] == 200
                    cluster.STORE.change_own_password("native-viewer", {
                        "currentPassword": password, "newPassword": password})
                    second_ws.wait_closed()
                code, role_issued, _ = request("/api/v1/auth/login", login, use_cookie=False)
                assert code == 200 and role_issued
                role_cookie = role_issued.split(";", 1)[0]
                with WebSocketProbe(port, role_cookie) as role_ws:
                    with cluster.STORE.lock:
                        row = cluster.STORE.db.execute("SELECT id,revision FROM users WHERE username=?",
                                                       ("native-viewer",)).fetchone()
                    cluster.STORE.update_user(row["id"], {"roles": ["auditor"]}, row["revision"])
                    role_ws.wait_closed()
                # Identity-only session/own-account access still works without
                # media roles; an active socket never becomes a cached grant.
                assert request("/api/v1/auth/session", cookie_override=role_cookie)[0] == 200
                assert request("/api/v2/account/me", cookie_override=role_cookie)[0] == 200
                assert request("/api/v1/studio", cookie_override=role_cookie)[0] == 403
                cluster.STORE.update_user(row["id"], {"roles": ["viewer"]}, row["revision"] + 1)
                with WebSocketProbe(port, role_cookie) as unavailable_ws:
                    authority_overrides["/auth/native-authorize"] = (503, {"error": {
                        "code": "fixture_unavailable", "message": "synthetic unavailable"}})
                    unavailable_ws.wait_closed()
                assert request("/api/v1/auth/session", cookie_override=role_cookie)[0] == 200
                with WebSocketProbe(port, role_cookie) as retiring_ws:
                    retiring_ws.ping()
                # A closed peer must release its timer/self-reference rather
                # than keep authorizing forever without a live consumer.
                time.sleep(2.2)
                retired_authority_calls = len(authority_paths)
                time.sleep(2.2)
                assert len(authority_paths) == retired_authority_calls, \
                    "closed WebSocket retained a repeating authority timer"
                print("PASS real WebSocket logout/password/role revocation and same-identity session isolation")
                print("PASS real native login, bound identity, scope, strict Profile, epoch revocation and logout")
            finally:
                if process.poll() is None:
                    if os.name == "nt":
                        process.terminate()
                    else:
                        os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)

        # Reuse only this disposable fixture to check the non-native HTTP
        # compatibility path; this is not an installed legacy-upgrade test.
        legacy_environment = dict(environment)
        legacy_environment.pop("WEBOBS_NATIVE_HOST_TOKEN")
        with (private / "private-legacy-core.log").open("wb") as legacy_log:
            process = subprocess.Popen([str(binary), "--duration-seconds", "30"], env=legacy_environment,
                stdin=subprocess.DEVNULL, stdout=legacy_log, stderr=legacy_log,
                start_new_session=os.name != "nt")
            try:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    assert process.poll() is None, "compatibility control process exited before readiness"
                    try:
                        if request("/api/v1/health")[0] == 200:
                            break
                    except OSError:
                        time.sleep(0.1)
                else:
                    raise AssertionError("compatibility control process did not become ready")
                code, compatibility_issued, _ = request("/api/v1/auth/login", login, use_cookie=False)
                assert code == 200 and compatibility_issued
                compatibility_cookie = compatibility_issued.split(";", 1)[0]
                compatibility_hash = hashlib.sha256(compatibility_cookie.split("=", 1)[1].encode()).hexdigest()
                with contextlib.closing(sqlite3.connect(private / "sessions.db")) as database:
                    row = database.execute("SELECT user_id,auth_epoch FROM auth_sessions WHERE session_id_hash=?",
                                           (compatibility_hash,)).fetchone()
                    assert row == (None, None), "non-native compatibility login protocol changed"
                assert request("/api/v1/auth/session", cookie_override=compatibility_cookie)[0] == 200
                code, _, legacy_studio = request("/api/v1/studio", cookie_override=compatibility_cookie)
                assert code == 200
                legacy_studio["scenes"][1]["name"] = "Legacy HTTP mutation remains available"
                assert request("/api/v1/studio", legacy_studio, method="PUT", revision=legacy_studio["revision"],
                               cookie_override=setup_cookie)[0] == 200
                code, _, legacy_profile = request("/api/v2/account/me", {"displayName": "Legacy own account"},
                    method="PATCH", cookie_override=compatibility_cookie, extra_headers={
                        "X-WebObs-Principal": "native-admin", "X-WebObs-Account-Id": "0" * 32,
                        "X-WebObs-Account-Epoch": "0" * 32})
                assert code == 200 and legacy_profile["username"] == "native-viewer" and \
                    legacy_profile["displayName"] == "Legacy own account"
                with WebSocketProbe(port, compatibility_cookie) as compatibility_ws:
                    compatibility_ws.ping()
                assert request("/api/v1/native/auth/session", cookie_override=compatibility_cookie)[0] == 404
                print("PASS non-native username-session HTTP compatibility (isolated fixture, not upgrade proof)")
            finally:
                if process.poll() is None:
                    if os.name == "nt":
                        process.terminate()
                    else:
                        os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    exercise(parser.parse_args().binary.resolve(strict=True))
