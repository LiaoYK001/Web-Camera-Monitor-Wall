#!/usr/bin/env python3
"""Real core + account Handler/Argon2id + Registry, using disposable private data."""
from __future__ import annotations

import argparse
import contextlib
from http.server import ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]


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
        cluster.INTERNAL_TOKEN = secrets.token_hex(32)
        cluster.STORE = cluster.ClusterStore(private / "accounts.db", cluster.PasswordHasher(),
                                            camera_registry_path=camera.DB_PATH)
        cleanup.callback(cluster.STORE.close)
        password = secrets.token_urlsafe(24)
        cluster.STORE.create_user({"username": "native-viewer", "password": password,
            "roles": ["viewer"], "scopes": [{"kind": "camera", "id": "camera-a"}]})
        resolved = []
        authority_paths = []

        class AccountHandler(cluster.Handler):
            def do_POST(self):
                authority_paths.append(self.path)
                super().do_POST()

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

        def request(path, value=None, *, method=None, secret=host_secret, request_origin=origin, use_cookie=True):
            headers = {"Origin": request_origin, "Content-Type": "application/json", "X-WebOBS-Native-Host": secret}
            if cookie and use_cookie:
                headers["Cookie"] = cookie
            data = None if value is None else json.dumps(value).encode()
            message = urllib.request.Request(origin + path, data=data, headers=headers, method=method)
            try:
                reply = opener.open(message, timeout=13)
            except urllib.error.HTTPError as error:
                reply = error
            with reply:
                return reply.status, reply.headers.get("Set-Cookie", ""), json.loads(reply.read())

        with (private / "private-core.log").open("wb") as log:
            process = subprocess.Popen([str(binary), "--duration-seconds", "120"], env=environment,
                stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}))
            try:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    if process.poll() is not None:
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
                with contextlib.closing(sqlite3.connect(private / "sessions.db")) as database:
                    row = database.execute("SELECT user_id,auth_epoch FROM auth_sessions").fetchone()
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
                assert len(resolved) == before, "configuration renewal unexpectedly read endpoint credentials"
                # Real account epoch change invalidates the existing session.
                with cluster.STORE.lock, cluster.STORE.db:
                    cluster.STORE.db.execute("UPDATE users SET auth_epoch=? WHERE username=?",
                                             (secrets.token_hex(16), "native-viewer"))
                assert request("/api/v1/native/auth/session")[0] == 401
                assert request("/api/v1/native/cameras/resolve", selection)[0] == 401
                _, issued, _ = request("/api/v1/native/auth/login", login)
                cookie = issued.split(";", 1)[0]
                assert request("/api/v1/native/auth/logout", {}, method="POST")[0] == 200
                assert request("/api/v1/native/auth/session")[0] == 401
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    exercise(parser.parse_args().binary.resolve(strict=True))
